"""Failed/no-op asynchronous bot tasks get durable, localized recovery UI."""
import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from aiogram import Bot
from django.db import transaction
from django.utils import timezone

from apps.core.models import Account, BotCallback, BotJobNotice, Job, UsageLedger
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
def test_terminal_notice_is_localized_owner_bound_and_does_not_run_or_charge(status, locale):
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
    assert COPY[locale][status] in args.args[1] and COPY[locale]['balance'] in args.args[1]
    controls = [row[0] for row in args.kwargs['reply_markup'].inline_keyboard]
    assert len(controls) == 4
    for button, action in zip(controls, ('job', 'new', 'recent', 'home')):
        ref = BotCallback.objects.get(pk=button.callback_data)
        assert ref.account_id == account.id and ref.action == action
        assert ref.payload['notice_id'] == str(notice.id)
        if action == 'job': assert ref.payload['job_id'] == str(job.id)
    job.refresh_from_db()
    assert job.status == status and job.attempt_count == 0
    assert not UsageLedger.objects.filter(kind='consume').exists()


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
    _, job = terminal_job()
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
    assert not UsageLedger.objects.filter(kind='consume').exists()


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
    assert not UsageLedger.objects.filter(job=job, kind='consume').exists()


def test_async_settlement_and_notice_roll_back_together(settings):
    settings.LOCAL_SYNC_JOBS = False
    _, job = completed_job(execute=False)
    original_ledger = list(UsageLedger.objects.filter(job=job).values_list('id', 'kind', 'amount'))
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            settle_job(job.id, 'failed', error_code='processing_failed')
            assert BotJobNotice.objects.filter(job=job).exists()
            raise RuntimeError('rollback')
    job.refresh_from_db()
    assert job.status == 'queued' and not BotJobNotice.objects.filter(job=job).exists()
    assert list(UsageLedger.objects.filter(job=job).values_list('id', 'kind', 'amount')) == original_ledger


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
