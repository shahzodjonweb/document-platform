"""Durable, bounded notifications for asynchronous bot jobs without a result.

Only settlement enqueues notices: there is no historical job scan or backfill.
Sending cannot execute a job, consume credits, or modify its document draft.
"""
import secrets
from datetime import timedelta

from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from asgiref.sync import sync_to_async
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.errors import DomainError
from apps.core.models import BotCallback, BotJobNotice
from .ux_copy import UX, STATUS
from .errors import bot_error

NOTICE_STATUSES = frozenset(('failed', 'no_op', 'canceled', 'expired'))
MAX_ATTEMPTS = 5
COPY = {
    'en': {
        'failed': 'We couldn’t finish this task.',
        'no_op': 'No useful changes this time. Your file is unchanged.',
        'canceled': 'Task cancelled.',
        'expired': 'This task has expired.',
        'balance': 'Your balance wasn’t charged.',
        'details': '🔎 Task details',
    },
    'uz': {
        'failed': 'Bu vazifani yakunlay olmadik.',
        'no_op': 'Faylni yaxshilay olmadik. O‘z holicha qoldi.',
        'canceled': 'Vazifa bekor qilindi.',
        'expired': 'Bu vazifaning muddati tugagan.',
        'balance': 'Balansingizdan yechilmadi.',
        'details': '🔎 Tafsilotlar',
    },
    'ru': {
        'failed': 'Не удалось завершить задачу.',
        'no_op': 'Улучшить файл не удалось. Он остался без изменений.',
        'canceled': 'Задача отменена.',
        'expired': 'Срок этой задачи истёк.',
        'balance': 'С баланса ничего не списано.',
        'details': '🔎 Подробности',
    },
}


def enqueue_notice(job):
    """Call inside settlement after saving the terminal state; never sends."""
    if job.origin_channel != 'bot' or job.status not in NOTICE_STATUSES or job.account.telegram_user_id is None:
        return None
    notice, _ = BotJobNotice.objects.get_or_create(job=job)
    return notice


@transaction.atomic
def claim_notice(identifier):
    notice = BotJobNotice.objects.select_for_update().select_related('job__account').get(pk=identifier)
    now = timezone.now()
    if notice.status not in ('pending', 'retrying', 'sending') or notice.next_attempt_at > now:
        return None
    if notice.status == 'sending' and notice.lease_until and notice.lease_until > now:
        return None
    if notice.attempts >= MAX_ATTEMPTS:
        notice.status, notice.error_code, notice.lease_until = 'failed', 'telegram_notice_attempts_exhausted', None
        notice.save(update_fields=['status', 'error_code', 'lease_until'])
        return None
    notice.status, notice.lease_until, notice.attempts = 'sending', now + timedelta(seconds=120), notice.attempts + 1
    notice.save(update_fields=['status', 'lease_until', 'attempts'])
    return notice


def finish_notice(notice, status, *, error='', message_id=None, delay=0):
    values = {'status': status, 'lease_until': None, 'error_code': error,
              'message_id': message_id, 'next_attempt_at': timezone.now() + timedelta(seconds=delay)}
    if status == 'delivered':
        values['delivered_at'] = timezone.now()
    # A slow previous sender must not overwrite a newer lease/attempt.
    BotJobNotice.objects.filter(pk=notice.pk, status='sending', attempts=notice.attempts).update(**values)


@transaction.atomic
def notice_controls(notice):
    BotJobNotice.objects.select_for_update().get(pk=notice.pk)
    account = notice.job.account
    locale = account.locale if account.locale in COPY else 'en'
    rows = []
    for action, label in (('job', COPY[locale]['details']), ('new', UX[locale]['new_task']),
                          ('recent', UX[locale]['recent']), ('home', UX[locale]['home'])):
        payload = {'notice_id': str(notice.id)}
        if action == 'job':
            payload['job_id'] = str(notice.job_id)
        control = BotCallback.objects.filter(account=account, action=action, payload=payload).first()
        if control is None:
            control = BotCallback.objects.create(token=secrets.token_urlsafe(12), account=account, action=action,
                                                 payload=payload, expires_at=timezone.now() + timedelta(hours=24))
        rows.append([InlineKeyboardButton(text=label, callback_data=control.token)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def attempt_notice(identifier, bot):
    notice = await sync_to_async(claim_notice)(identifier)
    if not notice:
        return
    account, job = notice.job.account, notice.job
    if not account.telegram_user_id:
        return await sync_to_async(finish_notice)(notice, 'blocked', error='telegram_link_required')
    if account.is_test and isinstance(getattr(bot, 'session', None), AiohttpSession):
        return await sync_to_async(finish_notice)(notice, 'blocked', error='test_account_delivery')
    if job.origin_channel != 'bot' or job.status not in NOTICE_STATUSES:
        return await sync_to_async(finish_notice)(notice, 'blocked', error='invalid_notice_job')
    locale = account.locale if account.locale in COPY else 'en'
    copy = COPY[locale]
    lines = ['PDF Master · ' + STATUS[locale][job.status], copy[job.status]]
    if job.status == 'failed':
        lines.append(bot_error(DomainError(job.error_code or 'processing_failed'), locale))
    lines.extend(['', copy['balance']])
    try:
        controls = await sync_to_async(notice_controls)(notice)
        response = await bot.send_message(account.telegram_user_id, '\n'.join(lines), reply_markup=controls)
        await sync_to_async(finish_notice)(notice, 'delivered', message_id=response.message_id)
    except TelegramForbiddenError:
        await sync_to_async(finish_notice)(notice, 'blocked', error='telegram_blocked')
    except TelegramRetryAfter as exc:
        await sync_to_async(finish_notice)(notice, 'failed' if notice.attempts >= MAX_ATTEMPTS else 'retrying',
                                         error='telegram_rate_limited', delay=min(3600, max(1, exc.retry_after)))
    except Exception:
        await sync_to_async(finish_notice)(notice, 'failed' if notice.attempts >= MAX_ATTEMPTS else 'retrying',
                                         error='telegram_notice_failed', delay=min(3600, 2 ** notice.attempts * 10))


async def drain_notices(bot):
    now = timezone.now()
    identifiers = await sync_to_async(lambda: list(BotJobNotice.objects.filter(
        job__account__is_test=False, status__in=('pending', 'retrying', 'sending'), next_attempt_at__lte=now,
    ).filter(Q(lease_until__isnull=True) | Q(lease_until__lte=now)).order_by('created_at').values_list('pk', flat=True)[:20]))()
    for identifier in identifiers:
        await attempt_notice(identifier, bot)
