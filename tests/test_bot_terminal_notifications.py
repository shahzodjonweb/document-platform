"""Failed/no-op asynchronous bot tasks get durable, localized recovery UI."""
import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from aiogram import Bot
from django.db import transaction
from django.utils import timezone

from apps.core.allowance import file_jobs_this_week
from apps.core.models import Account, BotCallback, BotJobNotice, Job
from apps.core.services import execute_job, settle_job
from telegram.notifications import (
    COPY, MAX_ATTEMPTS, attempt_notice, claim_notice, drain_notices,
    enqueue_notice, finish_notice,
)
from tests.test_bot_delivery_ux import completed_job

pytestmark = pytest.mark.django_db(transaction=True)


def terminal_job(status='failed', *, origin='bot', locale='en', test=True):
    account, job = completed_job(origin=origin, locale=locale, execute=False)
    if not test:
        account.is_test = False; account.save(update_fields=['is_test'])
    job = settle_job(job.id, status, error_code='processing_failed' if status == 'failed' else '')
    return account, job


@pytest.mark.parametrize('status', ['failed', 'no_op', 'canceled', 'expired'])
@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_terminal_notice_is_localized_owner_bound_and_does_not_run_or_count(status, locale):
    account, job = terminal_job(status, locale=locale)
    notice = enqueue_notice(job)
    assert enqueue_notice(job).id == notice.id
    bot = Mock(send_message=AsyncMock(return_value=Mock(message_id=321)))
    asyncio.run(attempt_notice(notice.id, bot))
    asyncio.run(attempt_notice(notice.id, bot))
    notice.refresh_from_db()
    assert notice.status == 'delivered' and notice.message_id == 321 and bot.send_message.await_count == 1
    args = bot.send_message.await_args
    assert args.args[0] == account.telegram_user_id
    assert COPY[locale][status] in args.args[1] and COPY[locale]['not_counted'] in args.args[1]
    controls = [row[0] for row in args.kwargs['reply_markup'].inline_keyboard]
    assert len(controls) == 4
    for button, action in zip(controls, ('job', 'new', 'recent', 'home')):
        ref = BotCallback.objects.get(pk=button.callback_data)
        assert ref.account_id == account.id and ref.action == action
        assert ref.payload['notice_id'] == str(notice.id)
        if action == 'job': assert ref.payload['job_id'] == str(job.id)
    job.refresh_from_db()
    assert job.status == status and job.attempt_count == 0
    assert file_jobs_this_week(account) == 0, 'a task that produced nothing gives its place back'


def test_enqueue_is_transactional_and_does_not_backfill_historical_jobs():
    _, job = terminal_job()
    # No scanner creates an outbox entry for already finished jobs.
    BotJobNotice.objects.all().delete()
    bot = Mock(send_message=AsyncMock())
    asyncio.run(drain_notices(bot))
    assert bot.send_message.await_count == 0 and not BotJobNotice.objects.exists()
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            enqueue_notice(job)
            raise RuntimeError('rollback')
    assert not BotJobNotice.objects.exists()


@pytest.mark.parametrize('origin', ['web', 'mini_app'])
def test_browser_terminal_jobs_never_create_telegram_notice(origin):
    _, job = terminal_job(origin=origin)
    assert enqueue_notice(job) is None and not BotJobNotice.objects.exists()


def test_retries_are_bounded_and_reuse_same_controls():
    account, job = terminal_job()
    notice = enqueue_notice(job)
    bot = Mock(send_message=AsyncMock(side_effect=RuntimeError('Do not log raw provider error')))
    previous = None
    for attempt in range(MAX_ATTEMPTS):
        BotJobNotice.objects.filter(pk=notice.id).update(next_attempt_at=timezone.now() - timedelta(seconds=1))
        asyncio.run(attempt_notice(notice.id, bot))
        tokens = set(BotCallback.objects.values_list('token', flat=True))
        if previous is not None: assert tokens == previous
        previous = tokens
    notice.refresh_from_db()
    assert notice.status == 'failed' and notice.attempts == MAX_ATTEMPTS
    asyncio.run(attempt_notice(notice.id, bot))
    assert bot.send_message.await_count == MAX_ATTEMPTS
    assert BotCallback.objects.count() == 4
    assert file_jobs_this_week(account) == 0


def test_lease_prevents_parallel_claim_and_old_sender_cannot_finish_new_attempt():
    _, job = terminal_job()
    notice = enqueue_notice(job)
    first = claim_notice(notice.id)
    assert first is not None and claim_notice(notice.id) is None
    BotJobNotice.objects.filter(pk=notice.id).update(lease_until=timezone.now() - timedelta(seconds=1))
    second = claim_notice(notice.id)
    finish_notice(first, 'delivered', message_id=11)
    notice.refresh_from_db(); assert notice.status == 'sending' and notice.message_id is None
    finish_notice(second, 'delivered', message_id=22)
    notice.refresh_from_db(); assert notice.status == 'delivered' and notice.message_id == 22


def test_live_transport_cannot_send_test_notices_and_drain_ignores_test_account():
    _, job = terminal_job()
    notice = enqueue_notice(job)
    fake = Mock(send_message=AsyncMock())
    asyncio.run(drain_notices(fake))
    assert fake.send_message.await_count == 0
    async def run():
        bot = Bot('123456:TEST_DO_NOT_USE_NETWORK')
        bot.send_message = AsyncMock(side_effect=AssertionError('Network must not be contacted'))
        try:
            await attempt_notice(notice.id, bot)
            assert bot.send_message.await_count == 0
        finally:
            await bot.session.close()
    asyncio.run(run())
    notice.refresh_from_db()
    assert notice.status == 'blocked' and notice.error_code == 'test_account_delivery'


def test_unlinked_customer_is_not_notified_and_non_test_notice_drains():
    account, job = terminal_job(test=False)
    notice = enqueue_notice(job)
    Account.objects.filter(pk=account.pk).update(telegram_user_id=None)
    bot = Mock(send_message=AsyncMock(return_value=Mock(message_id=12)))
    asyncio.run(drain_notices(bot))
    notice.refresh_from_db()
    assert notice.status == 'blocked' and bot.send_message.await_count == 0
    Account.objects.filter(pk=account.pk).update(telegram_user_id=667788)
    BotJobNotice.objects.filter(pk=notice.id).update(status='pending', next_attempt_at=timezone.now())
    asyncio.run(drain_notices(bot))
    notice.refresh_from_db()
    assert notice.status == 'delivered' and bot.send_message.await_count == 1


def test_real_worker_failure_atomically_enqueues_and_delivery_loop_notifies_once(settings, monkeypatch):
    from processors import ProcessorError
    from telegram.delivery import drain
    settings.LOCAL_SYNC_JOBS = False
    account, job = completed_job(execute=False)
    account.is_test = False; account.save(update_fields=['is_test'])
    def fail_processing(*args, **kwargs):
        raise ProcessorError('processing_failed')
    monkeypatch.setattr('processors.sandbox.execute_sandbox', fail_processing)
    failed = execute_job(job.id)
    assert failed.status == 'failed' and failed.attempt_count == 1
    notice = BotJobNotice.objects.get(job=failed)
    assert notice.status == 'pending' and notice.attempts == 0
    # Replay execution/settlement does not process again or enqueue twice.
    execute_job(job.id); settle_job(job.id, 'failed')
    assert BotJobNotice.objects.count() == 1
    bot = Mock(send_message=AsyncMock(return_value=Mock(message_id=901)))
    asyncio.run(drain(bot)); asyncio.run(drain(bot))
    assert bot.send_message.await_count == 1
    notice.refresh_from_db(); assert notice.status == 'delivered'
    job.refresh_from_db(); assert job.attempt_count == 1
    assert file_jobs_this_week(job.account) == 0


def test_async_settlement_and_notice_roll_back_together(settings):
    settings.LOCAL_SYNC_JOBS = False
    account, job = completed_job(execute=False)
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            settle_job(job.id, 'failed', error_code='processing_failed')
            assert BotJobNotice.objects.filter(job=job).exists()
            raise RuntimeError('rollback')
    job.refresh_from_db()
    assert job.status == 'queued' and not BotJobNotice.objects.filter(job=job).exists()
    assert file_jobs_this_week(account) == 1, 'the queued task still holds its place'


def test_rate_limit_retries_are_also_bounded():
    from aiogram.exceptions import TelegramRetryAfter
    from aiogram.methods import SendMessage
    _, job = terminal_job()
    notice = enqueue_notice(job)
    error = TelegramRetryAfter(method=SendMessage(chat_id=667788, text='Retry'), message='Too many requests', retry_after=100)
    bot = Mock(send_message=AsyncMock(side_effect=error))
    for _ in range(MAX_ATTEMPTS):
        BotJobNotice.objects.filter(pk=notice.id).update(next_attempt_at=timezone.now() - timedelta(seconds=1))
        asyncio.run(attempt_notice(notice.id, bot))
    notice.refresh_from_db()
    assert notice.status == 'failed' and notice.error_code == 'telegram_rate_limited'
    assert notice.attempts == MAX_ATTEMPTS and bot.send_message.await_count == MAX_ATTEMPTS



def sent_notice(job):
    """The notice text for this job; a notice already sent for it is sent again."""
    BotJobNotice.objects.filter(job=job).delete()
    job.refresh_from_db()
    notice = enqueue_notice(job)
    bot = Mock(send_message=AsyncMock(return_value=Mock(message_id=77)))
    asyncio.run(attempt_notice(notice.id, bot))
    return bot.send_message.await_args.args[1]


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_a_plan_without_the_limit_is_not_told_a_task_did_not_count(locale):
    """Premium has no weekly limits, so "it doesn't count towards this week's
    limit" says nothing true to it; Plus has none for file tools."""
    account, job = terminal_job('failed', locale=locale)
    assert COPY[locale]['not_counted'] in sent_notice(job), 'Free counts file tasks'
    for plan in ('premium', 'plus'):
        Account.objects.filter(pk=account.pk).update(staff_plan=plan)
        text = sent_notice(job)
        assert COPY[locale]['failed'] in text
        assert COPY[locale]['not_counted'] not in text and COPY[locale]['edit_not_counted'] not in text, plan


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_a_failed_ai_edit_names_the_files_edits_not_the_week(locale):
    from apps.studio.domain import DOCUMENT
    _, job = terminal_job('canceled', locale=locale)
    Job.objects.filter(pk=job.pk).update(feature_id=DOCUMENT, parameters={'revision': True, 'root_draft_id': 'draft'})
    text = sent_notice(job)
    assert COPY[locale]['edit_not_counted'] in text and COPY[locale]['not_counted'] not in text


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_an_error_that_already_says_it_did_not_count_is_not_followed_by_it_again(locale):
    from apps.core.errors import DomainError, error_data
    from apps.studio.domain import DOCUMENT
    _, job = terminal_job('failed', locale=locale)
    Job.objects.filter(pk=job.pk).update(feature_id=DOCUMENT, parameters={}, error_code='provider_failed')
    text = sent_notice(job)
    assert error_data(DomainError('provider_failed'), locale)['message'] in text
    assert COPY[locale]['not_counted'] not in text, 'said once, by the error itself'
    # A file error in the bot's own words does not say it, so the notice does.
    Job.objects.filter(pk=job.pk).update(feature_id='pdf.rotate', error_code='processing_failed')
    assert COPY[locale]['not_counted'] in sent_notice(job)
