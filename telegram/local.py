"""Token-free localhost Telegram simulator using the real aiogram dispatcher."""
import asyncio
import hashlib
import json
import secrets
from datetime import datetime,timezone
from asgiref.sync import sync_to_async,async_to_sync
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage,EditMessageText,EditMessageReplyMarkup,SendDocument,SendPhoto,AnswerCallbackQuery,GetFile,SetMyCommands,SetChatMenuButton
from aiogram.types import Message,Chat,User,Document,Update,CallbackQuery,File,InlineKeyboardMarkup,ReplyKeyboardMarkup
from django.utils import timezone as django_timezone
from django.db.models import Max
from apps.core.errors import DomainError
from apps.core.models import FileAsset
from apps.core.services import storage_path
from apps.commerce.models import LocalBotMessage
from apps.commerce.services import require_sandbox

class LocalTelegramSession(BaseSession):
    def __init__(self,account):
        super().__init__();self.account=account;self.files={};self.counter=None
    async def close(self): pass
    async def stream_content(self,url,**kwargs):
        yield self.files[url.rsplit('/',1)[-1]]
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
            if method.file_id not in self.files: raise DomainError('file_unavailable',404)
            return File(file_id=method.file_id,file_unique_id=method.file_id,file_size=len(self.files[method.file_id]),file_path=method.file_id)
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
        file_id=secrets.token_hex(12);session.files[file_id]=uploaded.read()
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
    async_to_sync(run)()
    return history(account)
