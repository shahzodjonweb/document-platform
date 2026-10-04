"""Independent durable result delivery. Retrying never reprocesses or recharges a job."""
import asyncio
import html
import re
import secrets
from datetime import timedelta
from asgiref.sync import sync_to_async
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError,TelegramRetryAfter
from aiogram.types import BufferedInputFile,InlineKeyboardButton,InlineKeyboardMarkup
from django.db import transaction
from django.utils import timezone
from apps.core.errors import DomainError
from apps.core.models import BotCallback
from apps.core import storage
from apps.commerce.models import BotDelivery
from apps.commerce.providers import telegram_config
from .ux_copy import UX


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
    from apps.studio.domain import GENERATION_IDS
    job = delivery.artifact.job
    if job.feature_id not in GENERATION_IDS:
        return ''
    identifier = (job.parameters or {}).get('generation_draft_id', '')
    if not identifier:
        return ''
    from apps.studio.models import GenerationDraft
    exists = GenerationDraft.objects.filter(account=delivery.account, id=identifier,
                                            expires_at__gt=timezone.now()).exists()
    return str(identifier) if exists else ''


@transaction.atomic
def result_controls(delivery):
    """Stable owner-bound navigation; retries reuse tokens instead of adding rows."""
    BotDelivery.objects.select_for_update().get(pk=delivery.pk)
    locale = delivery.account.locale if delivery.account.locale in UX else 'en'
    rows = []
    payload = {'delivery_id': str(delivery.id)}
    # A generated document can be changed by asking; a converted file cannot.
    revise = revisable_draft(delivery)
    if revise:
        control = BotCallback.objects.filter(account=delivery.account, action='ai_revise',
                                             payload={'draft_id': revise}).first()
        if control is None:
            control = BotCallback.objects.create(
                token=secrets.token_urlsafe(12), account=delivery.account, action='ai_revise',
                payload={'draft_id': revise}, expires_at=delivery.artifact.file.expires_at,
            )
        rows.append([InlineKeyboardButton(text=UX[locale]['ai_revise'], callback_data=control.token)])
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


async def delivery_loop(bot):
    while True:
        await drain(bot)
        await asyncio.sleep(2)


async def standalone():
    cfg=await sync_to_async(telegram_config)()
    if not cfg.get('token'): raise RuntimeError('Configure the Telegram bot token in the admin panel.')
    bot=Bot(cfg['token'])
    try: await drain(bot)
    finally: await bot.session.close()
