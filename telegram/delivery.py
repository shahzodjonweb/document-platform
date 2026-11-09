"""Independent durable result delivery. Retrying never reprocesses or recharges a job."""
import asyncio
import html
import re
import secrets
from datetime import timedelta
from urllib.parse import urlsplit, urlunsplit
from asgiref.sync import sync_to_async
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError,TelegramRetryAfter
from aiogram.types import BufferedInputFile,InlineKeyboardButton,InlineKeyboardMarkup,WebAppInfo
from cryptography.fernet import InvalidToken
from django.db import transaction
from django.utils import timezone
from apps.core.errors import DomainError
from apps.core.models import BotCallback
from apps.core import storage
from apps.commerce.models import BotDelivery
from apps.commerce.providers import telegram_config
from .ux_copy import EDIT_BUTTON_COPY, UX


RESULT_COPY = {
    'en': {
        'ready': '✅ Done!',
        'large': '✅ Done! The file is too large for Telegram. Download it from Recent tasks on the web within 24 hours of processing.',
        'open': '🌐 Open web app',
        'share': '✅ 📎 Made with {bot}',
    },
    'uz': {
        'ready': '✅ Tayyor!',
        'large': '✅ Tayyor! Fayl Telegram uchun juda katta. Qayta ishlanganidan keyin 24 soat ichida veb ilovadagi So‘nggi vazifalardan yuklab oling.',
        'open': '🌐 Veb ilova',
        'share': '✅ 📎 {bot} yordamida tayyorlandi',
    },
    'ru': {
        'ready': '✅ Готово!',
        'large': '✅ Готово! Файл слишком большой для Telegram. Скачайте его из последних задач на сайте в течение 24 часов после обработки.',
        'open': '🌐 Открыть сайт',
        'share': '✅ 📎 Сделано в {bot}',
    },
}


def share_link(account, username):
    """(username, link) to the bot for whoever this file is forwarded to, or ('', '').

    It carries the owner's referral code, so someone who starts the bot from a
    forwarded file is counted as their invitation. Nothing here may stop a
    delivery: without a configured username, or on any failure, the caption
    simply has no link.
    """
    username = (username or '').strip().lstrip('@')
    if not re.fullmatch(r'[A-Za-z0-9_]{5,32}', username):
        return '', ''
    link = f'https://t.me/{username}'
    try:
        from apps.commerce.services import referral_code
        code = referral_code(account).code
        if re.fullmatch(r'[A-Za-z0-9_-]{1,60}', code):
            link += f'?start=ref_{code}'
    except Exception:
        pass
    return username, link


def ready_caption(copy, username, link):
    """One short line under the file: who made it, linking to the bot.

    Without a bot to link to, just "Done!".
    """
    if not link:
        return html.escape(copy['ready'])
    mention = f'<a href="{html.escape(link)}">@{html.escape(username)}</a>'
    return html.escape(copy['share']).replace('{bot}', mention)


def enqueue(artifact,key):
    if artifact.account.telegram_user_id is None: raise DomainError('telegram_link_required',409)
    delivery,_=BotDelivery.objects.get_or_create(account=artifact.account,artifact=artifact,idempotency_key=key)
    return delivery


@transaction.atomic
def claim(delivery_id):
    delivery=BotDelivery.objects.select_for_update().select_related('account','artifact__file').get(pk=delivery_id)
    now=timezone.now()
    if delivery.status in ('delivered','failed','blocked'): return None
    if delivery.status=='sending' and delivery.lease_until and delivery.lease_until>now: return None
    if delivery.next_attempt_at>now: return None
    delivery.status='sending';delivery.lease_until=now+timedelta(seconds=120);delivery.attempts+=1
    delivery.save(update_fields=['status','lease_until','attempts'])
    return delivery


def finish(delivery_id,*,status,message_id=None,error='',delay=0):
    values={'status':status,'message_id':message_id,'error_code':error,'lease_until':None,'next_attempt_at':timezone.now()+timedelta(seconds=delay)}
    if status=='delivered': values['delivered_at']=timezone.now()
    BotDelivery.objects.filter(pk=delivery_id,status='sending').update(**values)


def revisable_draft(delivery):
    """The draft behind a generated document, when there is one to change."""
    from apps.studio.domain import GENERATION_IDS, RENDER_IDS
    job = delivery.artifact.job
    if job.feature_id not in GENERATION_IDS | RENDER_IDS:
        return ''
    identifier = (job.parameters or {}).get('generation_draft_id', '')
    if not identifier:
        return ''
    from apps.studio.models import GenerationDraft
    exists = GenerationDraft.objects.filter(account=delivery.account, id=identifier,
                                            expires_at__gt=timezone.now()).exists()
    return str(identifier) if exists else ''


def app_url(webapp_url, locale, route=''):
    """A page of the web app, in the customer's language."""
    url = urlsplit(webapp_url)
    parts = url.path.rstrip('/').split('/')
    if len(parts) > 1 and parts[1] in ('en', 'uz', 'ru'):
        parts[1] = locale
    return urlunsplit((url.scheme, url.netloc, '/'.join(parts) + ('/' + route if route else ''), '', ''))


def app_button(label, url):
    """Opens a page as a Mini App where Telegram allows one (https), else as a link."""
    if url.startswith('https://'):
        return InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url))
    return InlineKeyboardButton(text=label, url=url)


def editable_pdf(asset):
    """A file the editor would open now: the same refusals as studio.views.editors."""
    return (asset.mime_type == 'application/pdf' and not asset.metadata.get('encrypted')
            and asset.state == 'ready' and asset.expires_at > timezone.now())


def editable_deck(account, identifier):
    """A deck the editor would draw now: the same refusal as render_export, as a live
    draft can have no pins. One that cannot be read is no reason to hold the file back."""
    from apps.studio.domain import unpack
    from apps.studio.models import GenerationDraft
    from apps.studio.render_export import _editable
    draft = GenerationDraft.objects.filter(account=account, id=identifier, expires_at__gt=timezone.now()).first()
    if draft is None:
        return False
    try:
        _editable(draft, unpack(draft.encrypted_data))
    except (DomainError, InvalidToken, ValueError):
        return False
    return True


def deck_route(account, draft, flags):
    """Where ✏️ Edit takes a deck's file: back to its slides, while the deck editor is on and the deck is drawn."""
    return f'editor/deck/{draft}' if flags['deck_editor'] and draft and editable_deck(account, draft) else ''


def edit_route(delivery, flags):
    """Where ✏️ Edit takes this result, or '' when there is nothing to open.

    An edited PDF goes back to the upload its marks are on, so it comes up with
    them; all a deck makes, in either format, goes back to its slides.
    """
    from apps.studio.domain import RENDER_IDS, SLIDES
    from apps.studio.models import EditorDocument
    asset = delivery.artifact.file
    document = asset.metadata.get('editor_document_id')
    if document:
        source = EditorDocument.objects.select_related('file').filter(account=delivery.account, id=document).first()
        return f'editor?file_id={source.file_id}' if source and editable_pdf(source.file) else ''
    if delivery.artifact.job.feature_id in RENDER_IDS | {SLIDES}:
        return deck_route(delivery.account, asset.metadata.get('generation_draft_id'), flags)
    return f'editor?file_id={asset.id}' if editable_pdf(asset) else ''


def edit_url(account, route):
    """The page ✏️ Edit opens for `route`, or '' when no button is drawn: Telegram refuses
    a message whose button has no address, and the file matters more."""
    locale = account.locale if account.locale in UX else 'en'
    url = app_url(telegram_config()['webapp_url'], locale, route) if route else ''
    return url if url.startswith(('https://', 'http://')) else ''


def deck_change_label(account, draft):
    """The UX key of the button under a deck's file that changes it, as result_controls draws them:
    ✏️ Edit where it is drawn, else the AI change, which every deck made from a draft has."""
    from operations.integrations import editor_flags
    flags = editor_flags()
    if flags['edit_buttons'] and edit_url(account, deck_route(account, draft, flags)):
        return 'edit'
    return EDIT_BUTTON_COPY['ai_revise'] if flags['edit_buttons'] else 'ai_revise'


@transaction.atomic
def result_controls(delivery):
    """Stable owner-bound navigation; retries reuse tokens instead of adding rows."""
    BotDelivery.objects.select_for_update().get(pk=delivery.pk)
    locale = delivery.account.locale if delivery.account.locale in UX else 'en'
    from operations.integrations import editor_flags
    flags = editor_flags()
    rows = []
    payload = {'delivery_id': str(delivery.id)}
    # A link holds no token, so a retry draws the same button.
    url = edit_url(delivery.account, edit_route(delivery, flags) if flags['edit_buttons'] else '')
    if url:
        rows.append([app_button(UX[locale]['edit'], url)])
    # A generated document can be changed by asking; a converted file cannot.
    revise = revisable_draft(delivery)
    if revise:
        controls = BotCallback.objects.filter(account=delivery.account, action='ai_revise', payload={'draft_id': revise})
        # One button for a draft however often it is sent: it lasts as long as the newest file.
        controls.filter(expires_at__lt=delivery.artifact.file.expires_at).update(expires_at=delivery.artifact.file.expires_at)
        control = controls.first()
        if control is None:
            control = BotCallback.objects.create(
                token=secrets.token_urlsafe(12), account=delivery.account, action='ai_revise',
                payload={'draft_id': revise}, expires_at=delivery.artifact.file.expires_at,
            )
        label = EDIT_BUTTON_COPY['ai_revise'] if flags['edit_buttons'] else 'ai_revise'
        rows.append([InlineKeyboardButton(text=UX[locale][label], callback_data=control.token)])
    for action, label in (('home', 'home'), ('recent', 'recent'), ('new', 'new_task')):
        control = BotCallback.objects.filter(account=delivery.account, action=action, payload=payload).first()
        if control is None:
            control = BotCallback.objects.create(
                token=secrets.token_urlsafe(12), account=delivery.account, action=action,
                payload=payload, expires_at=delivery.artifact.file.expires_at,
            )
        rows.append([InlineKeyboardButton(text=UX[locale][label], callback_data=control.token)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def attempt(delivery_id,bot):
    delivery=await sync_to_async(claim)(delivery_id)
    if not delivery: return
    if delivery.account.telegram_user_id is None:
        return await sync_to_async(finish)(delivery.id,status='blocked',error='telegram_link_required')
    from aiogram.client.session.aiohttp import AiohttpSession
    if delivery.account.is_test and isinstance(getattr(bot,'session',None),AiohttpSession):
        return await sync_to_async(finish)(delivery.id,status='blocked',error='test_account_delivery')
    asset=delivery.artifact.file
    if asset.state!='ready' or asset.expires_at<=timezone.now():
        return await sync_to_async(finish)(delivery.id,status='failed',error='file_expired')
    try:
        locale = delivery.account.locale if delivery.account.locale in RESULT_COPY else 'en'
        copy = RESULT_COPY[locale]
        controls = await sync_to_async(result_controls)(delivery)
        if asset.size_bytes>50*1024*1024:
            cfg=await sync_to_async(telegram_config)()
            controls.inline_keyboard.insert(0, [InlineKeyboardButton(text=copy['open'], url=cfg['webapp_url'])])
            response=await bot.send_message(delivery.account.telegram_user_id,copy['large'],reply_markup=controls)
        else:
            payload=await sync_to_async(lambda:storage.read_bytes(asset.object_key))()
            # The buttons belong to the owner; whoever the file is forwarded to
            # finds the way to the bot in the caption itself.
            cfg=await sync_to_async(telegram_config)()
            username,link=await sync_to_async(share_link)(delivery.account,cfg.get('username',''))
            response=await bot.send_document(delivery.account.telegram_user_id,BufferedInputFile(payload,filename=asset.name),caption=ready_caption(copy,username,link),parse_mode='HTML',reply_markup=controls)
        await sync_to_async(finish)(delivery.id,status='delivered',message_id=response.message_id)
    except TelegramRetryAfter as exc:
        await sync_to_async(finish)(delivery.id,status='retrying',error='telegram_rate_limited',delay=min(3600,max(1,exc.retry_after)))
    except TelegramForbiddenError:
        await sync_to_async(finish)(delivery.id,status='blocked',error='telegram_blocked')
    except Exception:
        await sync_to_async(finish)(delivery.id,status='failed' if delivery.attempts>=5 else 'retrying',error='telegram_delivery_failed',delay=min(3600,2**delivery.attempts*10))


async def drain(bot):
    ids=await sync_to_async(lambda:list(BotDelivery.objects.filter(account__is_test=False,status__in=('pending','retrying','sending'),next_attempt_at__lte=timezone.now()).order_by('created_at').values_list('id',flat=True)[:20]))()
    for identifier in ids: await attempt(identifier,bot)
    from .notifications import drain_notices
    await drain_notices(bot)
    from .payment_notices import drain as drain_payment_notices
    await drain_payment_notices(bot)
    from .referral_notices import drain as drain_referral_notices
    await drain_referral_notices(bot)
    from .staff_alerts import drain as drain_staff_alerts
    await drain_staff_alerts(bot)


async def delivery_loop(bot):
    while True:
        await drain(bot)
        await asyncio.sleep(2)


async def standalone():
    cfg=await sync_to_async(telegram_config)()
    if not cfg.get('token'): raise RuntimeError('Configure the Telegram bot token in the admin panel.')
    bot=Bot(cfg['token'])
    try:
        await drain(bot)
        from .posts import standalone_drain
        await standalone_drain(bot)
    finally: await bot.session.close()
