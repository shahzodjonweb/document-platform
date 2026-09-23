"""Independent durable result delivery. Retrying never reprocesses or recharges a job."""
import asyncio
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
from apps.core.services import storage_path
from apps.commerce.models import BotDelivery
from apps.commerce.providers import telegram_config
from .ux_copy import UX


RESULT_COPY = {
    'en': {
        'ready': 'Your result is ready. Server files expire 24 hours after processing; the file delivered here remains in your Telegram chat.',
        'large': 'Your result is ready. This file is too large to send in Telegram. Download it from Recent tasks in the web app. Server files expire 24 hours after processing.',
        'open': 'Open web app',
    },
    'uz': {
        'ready': 'Natija tayyor. Server fayllari qayta ishlangandan 24 soat keyin o‘chiriladi; bu yerga yuborilgan fayl Telegram chattingizda qoladi.',
        'large': 'Natija tayyor. Faylni Telegram orqali yuborish uchun hajmi juda katta. Uni veb ilovadagi So‘nggi vazifalardan yuklab oling. Server fayllari qayta ishlangandan 24 soat keyin o‘chiriladi.',
        'open': 'Veb ilovani ochish',
    },
    'ru': {
        'ready': 'Результат готов. Файлы на сервере удаляются через 24 часа после обработки; отправленный сюда файл останется в вашем чате Telegram.',
        'large': 'Результат готов. Файл слишком большой для отправки в Telegram. Скачайте его в разделе последних задач на сайте. Файлы на сервере удаляются через 24 часа после обработки.',
        'open': 'Открыть веб-приложение',
    },
}


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


@transaction.atomic
def result_controls(delivery):
    """Stable owner-bound navigation; retries reuse tokens instead of adding rows."""
    BotDelivery.objects.select_for_update().get(pk=delivery.pk)
    locale = delivery.account.locale if delivery.account.locale in UX else 'en'
    rows = []
    payload = {'delivery_id': str(delivery.id)}
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
            payload=await sync_to_async(lambda:storage_path(asset.object_key).read_bytes())()
            response=await bot.send_document(delivery.account.telegram_user_id,BufferedInputFile(payload,filename=asset.name),caption=copy['ready'],reply_markup=controls)
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
