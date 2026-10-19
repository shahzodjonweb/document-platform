"""Durable, bounded notifications for asynchronous bot jobs without a result.

Only settlement enqueues notices: there is no historical job scan or backfill.
Sending cannot execute a job, use up a weekly allowance, or modify its document draft.
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
from .ux_copy import UX, STATUS, TOOL_NAMES
from .errors import bot_error

NOTICE_STATUSES = frozenset(('failed', 'no_op', 'canceled', 'expired'))
MAX_ATTEMPTS = 5
COPY = {
    'en': {
        'failed': 'We couldn’t finish this task.',
        'no_op': 'No useful changes this time. Your file is unchanged.',
        'canceled': 'Task cancelled.',
        'expired': 'This task has expired.',
        'not_counted': 'It doesn’t count towards this week’s limit.',
        'edit_not_counted': 'This edit isn’t counted against this file’s edits.',
        'details': '🔎 Task details',
    },
    'uz': {
        'failed': 'Bu vazifani yakunlay olmadik.',
        'no_op': 'Faylni yaxshilay olmadik. O‘z holicha qoldi.',
        'canceled': 'Vazifa bekor qilindi.',
        'expired': 'Bu vazifaning muddati tugagan.',
        'not_counted': 'Bu haftalik limitingizga kirmaydi.',
        'edit_not_counted': 'Bu tahrir fayl uchun ajratilgan AI tahrirlar soniga kirmaydi.',
        'details': '🔎 Tafsilotlar',
    },
    'ru': {
        'failed': 'Не удалось завершить задачу.',
        'no_op': 'Улучшить файл не удалось. Он остался без изменений.',
        'canceled': 'Задача отменена.',
        'expired': 'Срок этой задачи истёк.',
        'not_counted': 'В недельный лимит это не засчитывается.',
        'edit_not_counted': 'Эта правка не засчитывается в лимит правок файла.',
        'details': '🔎 Подробности',
    },
}
# Words an error message uses when it already says the task was not counted:
# the shared messages for a failed AI step end that way (i18n provider_failed,
# ocr_failed and others), and the notice should not say it twice.
ALREADY_SAID = ("doesn't count", 'doesn’t count', 'hisoblanmaydi', 'kirmaydi', 'не засчитыва')


def not_counted(job, locale):
    """The line saying this task used nothing up, or '' when there is nothing to say.

    It names the limit the task would have used: a file's edits for an AI edit,
    the week otherwise. A plan without that limit is not told about one.
    """
    from apps.core.allowance import quote_kind
    from apps.core.policy import plan_limits
    kind = quote_kind(job)
    key = {'edit': 'edits_per_file', 'file': 'weekly_file_jobs'}.get(kind, 'weekly_ai_documents')
    if plan_limits(job.account).get(key) is None:
        return ''
    return COPY[locale]['edit_not_counted' if kind == 'edit' else 'not_counted']


def model_failed(job):
    """Whether this is a new AI document the model could not finish.

    Most of these were one reply our checks refused, and a short description
    with no topic, audience or length makes that likelier. Its notice says so,
    and offers Retry and a new description beside the usual buttons. An
    outline or a change to a delivered document keeps the plain notice: the
    advice is about describing a new document.
    """
    from apps.core.allowance import quote_kind
    return job.status == 'failed' and job.error_code == 'provider_failed' and quote_kind(job) == 'ai_document'


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
    account, job = notice.job.account, notice.job
    locale = account.locale if account.locale in COPY else 'en'
    layout = [[('job', COPY[locale]['details'])], [('new', UX[locale]['new_task'])],
              [('recent', UX[locale]['recent'])], [('home', UX[locale]['home'])]]
    if model_failed(job):
        # The way forward first: the same description again (its review is
        # shown before anything runs), or a new one. "New task" is the file
        # tools' fresh start, so it gives way here.
        layout = [[('ai_retry', UX[locale]['retry_task'])], [('ai_tool', UX[locale]['ai_change_topic'])],
                  [('job', COPY[locale]['details']), ('recent', UX[locale]['recent'])], [('home', UX[locale]['home'])]]
    rows = []
    for row in layout:
        rows.append([])
        for action, label in row:
            payload = {'notice_id': str(notice.id)}
            if action in ('job', 'ai_retry'):
                payload['job_id'] = str(notice.job_id)
            if action == 'ai_tool':
                payload['feature_id'] = job.feature_id
            control = BotCallback.objects.filter(account=account, action=action, payload=payload).first()
            if control is None:
                control = BotCallback.objects.create(token=secrets.token_urlsafe(12), account=account, action=action,
                                                     payload=payload, expires_at=timezone.now() + timedelta(hours=24))
            rows[-1].append(InlineKeyboardButton(text=label, callback_data=control.token))
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
    advice = model_failed(job)
    if advice:
        # Which service failed, in place of "We couldn't finish this task":
        # the error below already says it, and this is the AI's, not a file's.
        lines[1] = TOOL_NAMES[job.feature_id][locale]
    said = False
    if job.status == 'failed':
        error = bot_error(DomainError(job.error_code or 'processing_failed'), locale)
        lines.append(error)
        said = any(words in error for words in ALREADY_SAID)
    counted = '' if said else await sync_to_async(not_counted)(job, locale)
    if counted:
        lines.extend(['', counted])
    if advice:
        # A CV is described by what it says about the person, not by a topic and a length.
        lines.extend(['', UX[locale]['cv_failed_advice' if job.feature_id == 'ai.cv' else 'ai_failed_advice']])
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
