"""Bot messages about payments (card transfers and inPAY): to the customer, and to the owner.

Durable like result delivery: a notice is claimed under a lease, sent once,
and retried with backoff when Telegram is unavailable, so an approval is never
silently lost and never announced twice.
"""
from datetime import timedelta

from asgiref.sync import sync_to_async
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from django.db import transaction
from django.utils import timezone

MAX_ATTEMPTS = 5
CUSTOMER_KINDS = ('approved', 'rejected', 'renewal_reminder', 'paid', 'paid_test')


def subject(notice):
    """What a notice is about: its card transfer, or its automatic payment."""
    return notice.manual if notice.manual_id else notice.checkout


@transaction.atomic
def claim(notice_id):
    from apps.commerce.models import PaymentNotice
    notice = PaymentNotice.objects.select_for_update(of=('self',)).select_related('manual__account', 'checkout__account').filter(pk=notice_id).first()
    now = timezone.now()
    if notice is None or notice.status not in ('pending', 'retrying', 'sending'):
        return None
    if notice.status == 'sending' and notice.lease_until and notice.lease_until > now:
        return None
    if notice.next_attempt_at > now:
        return None
    notice.status, notice.lease_until, notice.attempts = 'sending', now + timedelta(seconds=120), notice.attempts + 1
    notice.save(update_fields=['status', 'lease_until', 'attempts'])
    return notice


def finish(notice_id, *, status, message_id=None, error='', delay=0):
    from apps.commerce.models import PaymentNotice
    values = {'status': status, 'message_id': message_id, 'error_code': error, 'lease_until': None,
              'next_attempt_at': timezone.now() + timedelta(seconds=delay)}
    if status == 'delivered':
        values['delivered_at'] = timezone.now()
    PaymentNotice.objects.filter(pk=notice_id, status='sending').update(**values)


def compose(notice):
    """(chat_id, text) for a notice, or (None, reason) when it cannot be sent."""
    from apps.commerce.models import SubscriptionPeriod
    from operations.integrations import manual_payment_config
    from .billing import COPY, money
    from .clock import local_time
    if notice.checkout_id:
        return compose_checkout(notice)
    payment = notice.manual
    account = payment.account
    if notice.kind == 'staff_new':
        owner = manual_payment_config()['alert_telegram_id']
        if not owner:
            return None, 'no_alert_recipient'
        from apps.core.links import admin_url
        link = admin_url(f'/ops/payments/manual/{payment.id}')
        lines = ['💳 New card payment to review',
                 f"{payment.plan.title()} · {money(payment.amount)} so'm · {payment.reference}",
                 f'From: {account.display_name or account.telegram_user_id}']
        if payment.payer_note:
            lines.append(f'Note: {payment.payer_note}')
        lines.append(link or 'Admin → Payments')
        return owner, '\n'.join(lines)
    if account.telegram_user_id is None:
        return None, 'telegram_link_required'
    copy = COPY.get(account.locale, COPY['en'])
    if notice.kind == 'approved':
        period = SubscriptionPeriod.objects.filter(payment=payment.payment).first()
        date = local_time(account, period.ends_at).strftime('%d.%m.%Y') if period else ''
        return account.telegram_user_id, copy['manual_approved'].format(plan=payment.plan.title(), date=date)
    if notice.kind == 'rejected':
        return account.telegram_user_id, copy['manual_rejected'].format(reference=payment.reference,
                                                                        reason=payment.decision_note)
    if notice.kind == 'renewal_reminder':
        period = SubscriptionPeriod.objects.filter(payment=payment.payment).first()
        date = local_time(account, period.ends_at).strftime('%d.%m.%Y') if period else ''
        return account.telegram_user_id, copy['manual_reminder'].format(plan=payment.plan.title(), date=date)
    return None, 'unknown_notice'


def compose_checkout(notice):
    """(chat_id, text) for a notice about an automatic payment, or (None, reason)."""
    from apps.commerce.models import SubscriptionPeriod
    from .billing import COPY
    from .clock import local_time
    row = notice.checkout
    account = row.account
    if account.telegram_user_id is None:
        # Paid on the website by someone the bot has never met: the website shows it.
        return None, 'telegram_link_required'
    copy = COPY.get(account.locale, COPY['en'])
    if notice.kind == 'paid_test':
        return account.telegram_user_id, copy['checkout_paid_test']
    if notice.kind in ('paid', 'renewal_reminder'):
        period = SubscriptionPeriod.objects.filter(payment=row.payment).first() if row.payment_id else None
        date = local_time(account, period.ends_at).strftime('%d.%m.%Y') if period else ''
        key = 'checkout_paid' if notice.kind == 'paid' else 'manual_reminder'
        return account.telegram_user_id, copy[key].format(plan=row.plan.title(), date=date)
    return None, 'unknown_notice'


async def buttons(notice):
    """A Plans button under the renewal reminder, or nothing.

    The reminder is how a card customer comes back to pay, so its way to the
    plans says where it is: the admin counts it as a message from the bot
    (funnel.PLAN_SOURCES). The /plans in its text stays for anyone who taps
    that instead, and is counted as the command it sends.
    """
    if notice.kind != 'renewal_reminder':
        return None
    try:
        from aiogram.types import InlineKeyboardMarkup
        from .billing import button
        plans = await button(subject(notice).account, 'plans', 'plans', {'from': 'notice'})
        return InlineKeyboardMarkup(inline_keyboard=[[plans]])
    except Exception:
        # The reminder matters more than its button.
        return None


async def attempt(notice_id, bot):
    notice = await sync_to_async(claim)(notice_id)
    if not notice:
        return
    from aiogram.client.session.aiohttp import AiohttpSession
    if notice.kind in CUSTOMER_KINDS and subject(notice).account.is_test and isinstance(getattr(bot, 'session', None), AiohttpSession):
        return await sync_to_async(finish)(notice.id, status='blocked', error='test_account_delivery')
    chat, text = await sync_to_async(compose)(notice)
    if chat is None:
        return await sync_to_async(finish)(notice.id, status='skipped', error=text)
    markup = await buttons(notice)
    try:
        # Plain text: a rejection carries the owner's own words.
        response = await bot.send_message(chat, text, disable_web_page_preview=True, reply_markup=markup)
        await sync_to_async(finish)(notice.id, status='delivered', message_id=response.message_id)
    except TelegramRetryAfter as exc:
        await sync_to_async(finish)(notice.id, status='retrying', error='telegram_rate_limited',
                                    delay=min(3600, max(1, exc.retry_after)))
    except TelegramForbiddenError:
        await sync_to_async(finish)(notice.id, status='blocked', error='telegram_blocked')
    except Exception:
        await sync_to_async(finish)(notice.id, status='failed' if notice.attempts >= MAX_ATTEMPTS else 'retrying',
                                    error='telegram_delivery_failed', delay=min(3600, 2 ** notice.attempts * 10))


async def drain(bot):
    from apps.commerce.models import PaymentNotice
    due = await sync_to_async(lambda: list(
        PaymentNotice.objects.filter(status__in=('pending', 'retrying', 'sending'), next_attempt_at__lte=timezone.now())
        .order_by('created_at').values_list('id', flat=True)[:20]))()
    for identifier in due:
        await attempt(identifier, bot)
