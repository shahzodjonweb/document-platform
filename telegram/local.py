"""Token-free localhost Telegram simulator using the real aiogram dispatcher."""
import asyncio
import hashlib
import json
import os
import re
import secrets
import stat
import time
from pathlib import Path
from datetime import datetime,timezone
from asgiref.sync import sync_to_async,async_to_sync
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage,EditMessageText,EditMessageReplyMarkup,SendDocument,SendPhoto,AnswerCallbackQuery,GetFile,SetMyCommands,SetChatMenuButton
from aiogram.types import Message,Chat,User,Document,Update,CallbackQuery,File,InlineKeyboardMarkup,ReplyKeyboardMarkup
from django.conf import settings
from django.utils import timezone as django_timezone
from django.db.models import Max
from apps.core.errors import DomainError
from apps.core.models import BotConversation,BotVerification,FileAsset
from apps.core.services import storage_path
from apps.commerce.models import LocalBotMessage
from apps.commerce.services import require_sandbox

# Only the local, sandbox-gated transport stages bytes. Telegram onboarding
# stores metadata and downloads from Telegram only after language selection.
PENDING_UPLOAD_BYTES = 20 * 1024 * 1024
PENDING_UPLOAD_COUNT = 10
PENDING_UPLOAD_TTL = 30 * 60
_LOCAL_FILE_ID = re.compile(r'[a-f0-9]{24}')


def _pending_directory(account, *, create=False):
    root = Path(settings.PRIVATE_STORAGE_ROOT) / '.local-bot-pending'
    directory = root / account.pk.hex
    if create:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if root.is_symlink() or directory.is_symlink():
            raise DomainError('file_unavailable', 404)
        root.chmod(0o700)
        directory.mkdir(mode=0o700, exist_ok=True)
        directory.chmod(0o700)
    elif root.is_symlink() or directory.is_symlink():
        raise DomainError('file_unavailable', 404)
    return directory


def _staged_path(account, file_id):
    if not isinstance(file_id, str) or not _LOCAL_FILE_ID.fullmatch(file_id):
        raise DomainError('file_unavailable', 404)
    return _pending_directory(account) / file_id


def _staged_size(account, file_id):
    path = _staged_path(account, file_id)
    try:
        details = path.lstat()
    except FileNotFoundError:
        raise DomainError('file_unavailable', 404) from None
    if (not stat.S_ISREG(details.st_mode) or details.st_size > PENDING_UPLOAD_BYTES
            or details.st_mtime <= time.time() - PENDING_UPLOAD_TTL):
        if not path.is_dir():
            path.unlink(missing_ok=True)
        raise DomainError('file_unavailable', 404)
    return details.st_size


def _read_staged(account, file_id):
    path = _staged_path(account, file_id)
    _staged_size(account, file_id)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, 'rb') as source:
            details = os.fstat(source.fileno())
            if (not stat.S_ISREG(details.st_mode) or details.st_size > PENDING_UPLOAD_BYTES
                    or details.st_mtime <= time.time() - PENDING_UPLOAD_TTL):
                raise DomainError('file_unavailable', 404)
            payload = source.read(PENDING_UPLOAD_BYTES + 1)
            if len(payload) > PENDING_UPLOAD_BYTES:
                raise DomainError('bot_transport_limit', 413)
    except OSError:
        raise DomainError('file_unavailable', 404) from None
    finally:
        path.unlink(missing_ok=True)
    return payload


def _pending_ids(account):
    conversation = BotConversation.objects.filter(pk=account.telegram_user_id).first()
    verification = BotVerification.objects.filter(pk=account.telegram_user_id).first()
    uploads = []
    now = django_timezone.now()
    for state, expires in ((conversation, getattr(conversation, 'language_expires_at', None)),
                           (verification, getattr(verification, 'expires_at', None))):
        if state and expires and expires > now and isinstance(state.pending.get('uploads'), list):
            uploads.extend(state.pending['uploads'])
    identifiers = set()
    for upload in uploads[:PENDING_UPLOAD_COUNT]:
        if not isinstance(upload, dict) or upload.get('user_id') != account.telegram_user_id or upload.get('chat_id') != account.telegram_user_id:
            continue
        value = upload.get('document')
        if not value and isinstance(upload.get('photo'), list) and upload['photo']:
            value = upload['photo'][-1]
        file_id = value.get('file_id') if isinstance(value, dict) else None
        if isinstance(file_id, str) and _LOCAL_FILE_ID.fullmatch(file_id):
            identifiers.add(file_id)
    return identifiers


def _sync_pending_files(account, files=None):
    """Keep at most ten unexpired uploads still referenced by this account.

    Reconcile before and after each local interaction: cancellation, auth
    linking, expired pickers and successful consumption remove staged bytes.
    Unvisited expired files are inaccessible and removed on the next interaction.
    """
    keep = _pending_ids(account)
    directory = _pending_directory(account)
    if directory.exists():
        for path in directory.iterdir():
            if path.is_dir() and not path.is_symlink():
                continue
            if path.name not in keep:
                path.unlink(missing_ok=True)
                continue
            try:
                _staged_size(account, path.name)
            except DomainError:
                pass
    for file_id, payload in (files or {}).items():
        if file_id not in keep:
            continue
        if len(payload) > PENDING_UPLOAD_BYTES:
            raise DomainError('bot_transport_limit', 413)
        directory = _pending_directory(account, create=True)
        path = directory / file_id
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(descriptor, 'wb') as target:
            target.write(payload)


class LocalTelegramSession(BaseSession):
    def __init__(self,account):
        super().__init__();self.account=account;self.files={};self.counter=None
    async def close(self): pass
    async def stream_content(self,url,**kwargs):
        file_id=url.rsplit('/',1)[-1]
        if not _LOCAL_FILE_ID.fullmatch(file_id): raise DomainError('file_unavailable',404)
        if file_id in self.files:
            yield self.files[file_id]
        else:
            yield await sync_to_async(_read_staged)(self.account,file_id)
    async def make_request(self,bot,method,timeout=None):
        if isinstance(method,(SetMyCommands,SetChatMenuButton)):
            # Native-menu metadata is not a chat message. Keep simulation local.
            return True
        if isinstance(method,AnswerCallbackQuery):
            if method.text:
                self.counter=await sync_to_async(lambda:LocalBotMessage.objects.filter(account=self.account,direction='outbound').aggregate(value=Max('telegram_message_id'))['value'] or 100000)()
                self.counter+=1
                await self.save(method.text,[])
            return True
        if isinstance(method,GetFile):
            size=len(self.files[method.file_id]) if method.file_id in self.files else await sync_to_async(_staged_size)(self.account,method.file_id)
            return File(file_id=method.file_id,file_unique_id=method.file_id,file_size=size,file_path=method.file_id)
        if self.counter is None:
            self.counter=await sync_to_async(lambda:LocalBotMessage.objects.filter(account=self.account,direction='outbound').aggregate(value=Max('telegram_message_id'))['value'] or 100000)()
        editing=isinstance(method,(EditMessageText,EditMessageReplyMarkup))
        if not editing:self.counter+=1
        message_id=method.message_id if editing else self.counter
        buttons=[];markup=getattr(method,'reply_markup',None)
        if isinstance(markup,InlineKeyboardMarkup):
            buttons=[[{'label':button.text,'callback_data':button.callback_data,'url':button.url} for button in row] for row in markup.inline_keyboard]
        elif isinstance(markup,ReplyKeyboardMarkup):
            buttons=[[{'label':button.text,'callback_data':None,'url':None,'text':button.text} for button in row] for row in markup.keyboard]
        asset=None
        if isinstance(method,(SendDocument,SendPhoto)):
            document=method.document if isinstance(method,SendDocument) else method.photo
            data=getattr(document,'data',b'')
            if data:
                digest=hashlib.sha256(data).hexdigest()
                asset=await sync_to_async(lambda:FileAsset.objects.filter(account=self.account,sha256=digest,state='ready').order_by('-created_at').first())()
        text=getattr(method,'text','') or getattr(method,'caption','') or ''
        if editing:
            previous=await sync_to_async(lambda:LocalBotMessage.objects.filter(account=self.account,direction='outbound',telegram_message_id=message_id).order_by('-created_at').first())()
            if not previous:raise DomainError('controls_expired',409)
            if isinstance(method,EditMessageReplyMarkup):text=previous.text
            previous.text=text;previous.buttons=buttons
            await sync_to_async(previous.save)(update_fields=['text','buttons'])
        else:
            await self.save(text,buttons,asset)
        values={'message_id':message_id,'date':datetime.now(timezone.utc),'chat':Chat(id=self.account.telegram_user_id,type='private'),'from_user':User(id=123456,is_bot=True,first_name='PDF Master local simulator')}
        if isinstance(method,(SendMessage,EditMessageText,EditMessageReplyMarkup)):
            values.update(text=text)
            # Telegram's returned Message includes inline keyboards only.
            if isinstance(markup,InlineKeyboardMarkup):values['reply_markup']=markup
        if isinstance(method,SendDocument): values['document']=Document(file_id='local-result',file_unique_id='local-result',file_name=getattr(method.document,'filename','result.pdf'))
        return Message(**values).as_(bot)
    async def save(self,text,buttons,asset=None):
        return await sync_to_async(LocalBotMessage.objects.create)(account=self.account,direction='outbound',text=text,buttons=buttons,asset=asset,telegram_message_id=self.counter)


def message_data(message):
    asset=None
    if message.asset_id:
        file=message.asset
        asset={'id':str(file.id),'name':file.name,'mime_type':file.mime_type,'size_bytes':file.size_bytes,'download_url':f'/api/v1/files/{file.id}/download','preview_url':f'/api/v1/files/{file.id}/preview' if file.mime_type=='application/pdf' and not file.metadata.get('encrypted') else None,'expires_at':file.expires_at}
    return {'id':str(message.id),'direction':message.direction,'text':message.text,'buttons':message.buttons,'asset':asset,'created_at':message.created_at}


def history(account):
    require_sandbox(account)
    messages=list(LocalBotMessage.objects.filter(account=account).select_related('asset').order_by('-created_at')[:150])
    return {'sandbox':True,'transport':'local_aiogram','messages':[message_data(m) for m in reversed(messages)]}


def deliver_local(account,delivery):
    require_sandbox(account)
    if account.telegram_user_id is None: raise DomainError('telegram_link_required',409)
    async def run():
        from .delivery import attempt
        bot=Bot('123456:LOCAL_SIMULATOR_NO_NETWORK',session=LocalTelegramSession(account))
        try:await attempt(delivery.id,bot)
        finally:await bot.session.close()
    async_to_sync(run)()
    delivery.refresh_from_db()
    return delivery


def dispatch_local(account,*,text=None,callback_data=None,uploaded=None):
    require_sandbox(account)
    if account.telegram_user_id is None: raise DomainError('telegram_link_required',409)
    if not text and not callback_data and not uploaded: raise DomainError('invalid_request')
    _sync_pending_files(account)
    if text and (not isinstance(text,str) or len(text)>4096): raise DomainError('invalid_request')
    message_id=secrets.randbelow(2_000_000_000)+1
    user=User(id=account.telegram_user_id,is_bot=False,first_name=account.display_name or 'Local explorer',username=account.username or None,language_code=account.locale)
    now=datetime.now(timezone.utc)
    data={'message_id':message_id,'date':now,'chat':Chat(id=account.telegram_user_id,type='private'),'from_user':user}
    session=LocalTelegramSession(account)
    stored=text or ''
    # Passwords are never requested through chat; avoid persisting explicitly named secrets.
    if text and (text.startswith('/password') or (text.startswith('/parameters') and any(word in text.lower() for word in ('password','secret')))): stored='[Password omitted; use secure web entry]'
    if uploaded:
        if uploaded.size>20*1024*1024: raise DomainError('bot_transport_limit',413)
        file_id=secrets.token_hex(12);session.files[file_id]=uploaded.read(PENDING_UPLOAD_BYTES+1)
        if len(session.files[file_id])>PENDING_UPLOAD_BYTES: raise DomainError('bot_transport_limit',413)
        data['document']=Document(file_id=file_id,file_unique_id=file_id,file_name=uploaded.name,file_size=len(session.files[file_id]))
        stored=uploaded.name
    elif callback_data:
        stored='[Button selected]'
    else:
        data['text']=text
        if text.startswith('/'): data['entities']=[{'type':'bot_command','offset':0,'length':len(text.split()[0])}]
    LocalBotMessage.objects.create(account=account,direction='inbound',text=stored,telegram_message_id=message_id)
    callback_message=None
    if callback_data:
        # Preserve the originating bot message so inline edits behave exactly
        # like Telegram instead of creating a second, misleading screen.
        for candidate in LocalBotMessage.objects.filter(account=account,direction='outbound').order_by('-created_at')[:150]:
            if any(button.get('callback_data')==callback_data for row in candidate.buttons for button in row):
                callback_message=candidate
                break
    async def run():
        from .bot import build_dispatcher
        bot=Bot('123456:LOCAL_SIMULATOR_NO_NETWORK',session=session)
        try:
            if callback_data:
                message=Message(message_id=callback_message.telegram_message_id if callback_message else message_id,date=now,chat=data['chat'],from_user=User(id=123456,is_bot=True,first_name='PDF Master'),text=callback_message.text if callback_message else 'Local controls')
                update=Update(update_id=message_id,callback_query=CallbackQuery(id=str(message_id),from_user=user,chat_instance='local',message=message,data=callback_data))
            else: update=Update(update_id=message_id,message=Message(**data))
            await build_dispatcher().feed_update(bot,update)
        finally: await bot.session.close()
    try:
        async_to_sync(run)()
    finally:
        _sync_pending_files(account,session.files)
    return history(account)
