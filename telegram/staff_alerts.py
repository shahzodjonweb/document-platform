"""Telegram messages to the owner about the platform itself.

Sent to the Telegram ID set for payment alerts (Admin → Integrations → Card
payments). Retried with backoff when Telegram is unavailable; sent once.
"""
from datetime import timedelta

from asgiref.sync import sync_to_async
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from django.db import transaction
from django.utils import timezone

MAX_ATTEMPTS = 6


@transaction.atomic
def claim(alert_id):
    from apps.core.models import StaffAlert
    alert = StaffAlert.objects.select_for_update().filter(pk=alert_id).first()
    now = timezone.now()
    # A 'sending' alert whose time has passed was interrupted mid-send; take it again.
    if alert is None or alert.status not in ('pending', 'retrying', 'sending') or alert.next_attempt_at > now:
        return None
    alert.status, alert.attempts = 'sending', alert.attempts + 1
    alert.next_attempt_at = now + timedelta(seconds=120)  # a stuck send is retried after this
    alert.save(update_fields=['status', 'attempts', 'next_attempt_at'])
    return alert


def finish(alert_id, *, status, error='', delay=0):
    from apps.core.models import StaffAlert
    values = {'status': status, 'error_code': error, 'next_attempt_at': timezone.now() + timedelta(seconds=delay)}
    if status == 'delivered':
        values['delivered_at'] = timezone.now()
    StaffAlert.objects.filter(pk=alert_id, status='sending').update(**values)


def recipient():
    from operations.integrations import manual_payment_config
    return manual_payment_config()['alert_telegram_id']


async def attempt(alert_id, bot):
    alert = await sync_to_async(claim)(alert_id)
    if not alert:
        return
    owner = await sync_to_async(recipient)()
    if not owner:
        return await sync_to_async(finish)(alert.id, status='skipped', error='no_alert_recipient')
    try:
        await bot.send_message(owner, alert.text, disable_web_page_preview=True)
        await sync_to_async(finish)(alert.id, status='delivered')
    except TelegramRetryAfter as exc:
        await sync_to_async(finish)(alert.id, status='retrying', error='telegram_rate_limited',
                                    delay=min(3600, max(1, exc.retry_after)))
    except TelegramForbiddenError:
        await sync_to_async(finish)(alert.id, status='blocked', error='telegram_blocked')
    except Exception:
        await sync_to_async(finish)(alert.id, status='failed' if alert.attempts >= MAX_ATTEMPTS else 'retrying',
                                    error='telegram_delivery_failed', delay=min(3600, 2 ** alert.attempts * 10))


async def drain(bot):
    from apps.core.models import StaffAlert
    now = timezone.now()
    due = await sync_to_async(lambda: list(
        StaffAlert.objects.filter(status__in=('pending', 'retrying', 'sending'), next_attempt_at__lte=now)
        .order_by('created_at').values_list('id', flat=True)[:10]))()
    for identifier in due:
        await attempt(identifier, bot)
