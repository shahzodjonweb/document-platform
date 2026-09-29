"""Worker completion and durable Telegram result navigation."""
import asyncio
import io
from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone
from pypdf import PdfWriter

from apps.commerce.models import BotDelivery
from apps.core.identity import resolve_account
from apps.core.models import Account, BotCallback, Job, UsageLedger
from apps.core.services import create_quote, execute_job, settle_job, submit_job, upload_file
from telegram.delivery import RESULT_COPY, attempt, enqueue
from telegram.ux_copy import UX


pytestmark = pytest.mark.django_db(transaction=True)


def completed_job(*, origin='bot', locale='en', execute=True):
    account = resolve_account({'id': 667788, 'first_name': 'Delivery fixture', 'language_code': locale}, is_test=True)
    stream = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    writer.write(stream)
    asset = upload_file(account, SimpleUploadedFile('source.pdf', stream.getvalue()))
    quote = create_quote(account, 'pdf.rotate', [str(asset.id)], {'angle': 90})
    job, _ = submit_job(account, quote.id, 'delivery-ux-job', origin=origin)
    if execute:
        job = execute_job(job.id)
        assert job.status == 'succeeded', job.error_code
    return account, job


def test_worker_completion_atomically_enqueues_one_delivery_without_transport(monkeypatch):
    monkeypatch.setattr('aiogram.Bot.send_document', AsyncMock(side_effect=AssertionError('Settlement must not contact Telegram')))
    account, job = completed_job()
    artifact = job.artifacts.get()
    delivery = BotDelivery.objects.get()
    assert delivery.status == 'pending' and delivery.attempts == 0
    assert delivery.account_id == account.pk and delivery.artifact_id == artifact.pk
    assert delivery.idempotency_key == f'job:{job.id}:{artifact.id}'
    assert enqueue(artifact, delivery.idempotency_key).pk == delivery.pk
    settle_job(job.id, 'succeeded')
    execute_job(job.id)
    assert BotDelivery.objects.count() == 1
    assert UsageLedger.objects.filter(job=job, kind='consume', meter='file_tasks').count() == 1


def test_delivery_and_settlement_roll_back_together():
    account, job = completed_job(execute=False)
    with pytest.raises(RuntimeError, match='rollback'):
        with transaction.atomic():
            result = execute_job(job.id)
            assert result.status == 'succeeded' and BotDelivery.objects.count() == 1
            raise RuntimeError('rollback')
    job.refresh_from_db()
    assert job.status == 'queued' and not job.artifacts.exists()
    assert not BotDelivery.objects.exists()
    assert not UsageLedger.objects.filter(job=job, kind='consume').exists()


@pytest.mark.parametrize('origin', ['web', 'mini_app'])
def test_browser_jobs_do_not_send_unsolicited_telegram_results(origin):
    _, job = completed_job(origin=origin)
    assert job.status == 'succeeded' and not BotDelivery.objects.exists()


def test_unlinked_identity_does_not_fail_successful_processing():
    account, job = completed_job(execute=False)
    Account.objects.filter(pk=account.pk).update(telegram_user_id=None)
    job = execute_job(job.id)
    assert job.status == 'succeeded' and not BotDelivery.objects.exists()


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_result_caption_and_navigation_are_localized_and_owner_bound(locale):
    account, job = completed_job(locale=locale)
    delivery = BotDelivery.objects.get()
    bot = Mock(send_document=AsyncMock(return_value=Mock(message_id=321)))
    asyncio.run(attempt(delivery.id, bot))
    delivery.refresh_from_db()
    assert delivery.status == 'delivered' and delivery.message_id == 321
    args = bot.send_document.await_args
    assert args.args[0] == account.telegram_user_id
    assert args.kwargs['caption'] == RESULT_COPY[locale]['ready']
    buttons = [row[0] for row in args.kwargs['reply_markup'].inline_keyboard]
    assert [button.text for button in buttons] == [UX[locale][key] for key in ('home', 'recent', 'new_task')]
    for button, action in zip(buttons, ('home', 'recent', 'new')):
        callback = BotCallback.objects.get(pk=button.callback_data)
        assert callback.account_id == account.pk and callback.action == action
        assert callback.payload == {'delivery_id': str(delivery.id)}
        assert callback.expires_at == job.artifacts.get().file.expires_at
    asyncio.run(attempt(delivery.id, bot))
    assert bot.send_document.await_count == 1


def _deliver(monkeypatch, locale='en', username='PdfMasterTestBot'):
    monkeypatch.setattr('telegram.delivery.telegram_config', lambda: {'username': username, 'webapp_url': ''})
    account, job = completed_job(locale=locale)
    delivery = BotDelivery.objects.get()
    bot = Mock(send_document=AsyncMock(return_value=Mock(message_id=330)))
    asyncio.run(attempt(delivery.id, bot))
    delivery.refresh_from_db()
    assert delivery.status == 'delivered'
    return account, delivery, bot, bot.send_document.await_args.kwargs


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_a_forwarded_file_carries_a_link_to_the_bot_with_its_owners_referral(monkeypatch, locale):
    from apps.commerce.models import ReferralCode
    account, _, _, sent = _deliver(monkeypatch, locale)
    code = ReferralCode.objects.get(account=account).code
    link = f'https://t.me/PdfMasterTestBot?start=ref_{code}'
    assert sent['parse_mode'] == 'HTML'
    assert sent['caption'].startswith(RESULT_COPY[locale]['ready'])
    assert f'<a href="{link}">@PdfMasterTestBot</a>' in sent['caption']
    before, after = RESULT_COPY[locale]['share'].split('{bot}')
    assert before in sent['caption'] and after in sent['caption']
    assert len(sent['caption']) <= 1024, 'Telegram caption limit'


def test_the_forwarded_link_is_a_working_invitation(monkeypatch):
    """Someone new who starts the bot from the link is counted as the owner's invitation."""
    from apps.commerce.models import Referral
    from apps.commerce.services import claim_referral
    from types import SimpleNamespace
    from telegram.onboarding import _pending_for
    owner, _, _, sent = _deliver(monkeypatch)
    start = sent['caption'].split('?start=', 1)[1].split('"', 1)[0]
    # What Telegram sends the bot when the link is opened.
    pending = _pending_for(SimpleNamespace(text=f'/start {start}', document=None, photo=None))
    newcomer = resolve_account({'id': 991122, 'first_name': 'Friend', 'language_code': 'en'}, is_test=True)
    claim_referral(newcomer, pending['referral_code'])
    assert Referral.objects.get(invitee=newcomer).inviter_id == owner.pk


def test_every_delivery_to_one_owner_uses_the_same_referral_code(monkeypatch):
    from apps.commerce.models import ReferralCode
    account, delivery, bot, first = _deliver(monkeypatch)
    BotDelivery.objects.filter(pk=delivery.pk).update(status='retrying', next_attempt_at=timezone.now())
    asyncio.run(attempt(delivery.id, bot))
    assert bot.send_document.await_args.kwargs['caption'] == first['caption']
    assert ReferralCode.objects.filter(account=account).count() == 1


@pytest.mark.parametrize('username', ['', '@', 'bad name', 'x"><script>', 'abc', 'a' * 40])
def test_without_a_valid_bot_username_the_caption_has_no_link(monkeypatch, username):
    _, _, _, sent = _deliver(monkeypatch, username=username)
    assert sent['caption'] == RESULT_COPY['en']['ready'] and '<' not in sent['caption']


def test_a_referral_that_cannot_be_made_still_links_the_bot(monkeypatch):
    def broken(account):
        raise RuntimeError('database hiccup')
    monkeypatch.setattr('apps.commerce.services.referral_code', broken)
    _, _, _, sent = _deliver(monkeypatch, username='@PdfMasterTestBot')
    assert '<a href="https://t.me/PdfMasterTestBot">@PdfMasterTestBot</a>' in sent['caption']


def test_failed_send_reuses_navigation_tokens_and_does_not_recharge():
    _, job = completed_job()
    delivery = BotDelivery.objects.get()
    bot = Mock(send_document=AsyncMock(side_effect=RuntimeError('private transport failure')))
    asyncio.run(attempt(delivery.id, bot))
    first_tokens = set(BotCallback.objects.values_list('token', flat=True))
    assert len(first_tokens) == 3
    delivery.refresh_from_db()
    assert delivery.status == 'retrying'
    BotDelivery.objects.filter(pk=delivery.pk).update(next_attempt_at=timezone.now() - timedelta(seconds=1))
    bot.send_document = AsyncMock(return_value=Mock(message_id=322))
    asyncio.run(attempt(delivery.id, bot))
    assert set(BotCallback.objects.values_list('token', flat=True)) == first_tokens
    assert Job.objects.get(pk=job.pk).attempt_count == 1
    assert UsageLedger.objects.filter(job=job, kind='consume', meter='file_tasks').count() == 1


def test_large_result_has_actionable_web_link_without_reading_the_file(monkeypatch):
    _, job = completed_job(locale='uz')
    artifact = job.artifacts.get()
    artifact.file.size_bytes = 51 * 1024 * 1024
    artifact.file.save(update_fields=['size_bytes'])
    monkeypatch.setattr('telegram.delivery.telegram_config', lambda: {'webapp_url': 'https://pdfmaster.example/uz/app'})
    monkeypatch.setattr('telegram.delivery.storage_path', lambda key: (_ for _ in ()).throw(AssertionError('Large file must not be read')))
    bot = Mock(send_message=AsyncMock(return_value=Mock(message_id=323)), send_document=AsyncMock())
    delivery = BotDelivery.objects.get()
    asyncio.run(attempt(delivery.id, bot))
    delivery.refresh_from_db()
    assert delivery.status == 'delivered' and not bot.send_document.called
    args = bot.send_message.await_args
    assert args.args[1] == RESULT_COPY['uz']['large']
    assert args.kwargs['reply_markup'].inline_keyboard[0][0].url == 'https://pdfmaster.example/uz/app'
    assert len(args.kwargs['reply_markup'].inline_keyboard) == 4


def test_expired_result_does_not_create_navigation_or_call_telegram():
    _, job = completed_job()
    artifact = job.artifacts.get()
    artifact.file.expires_at = timezone.now() - timedelta(seconds=1)
    artifact.file.save(update_fields=['expires_at'])
    bot = Mock(send_document=AsyncMock())
    delivery = BotDelivery.objects.get()
    asyncio.run(attempt(delivery.id, bot))
    delivery.refresh_from_db()
    assert delivery.status == 'failed' and delivery.error_code == 'file_expired'
    assert not BotCallback.objects.exists() and not bot.send_document.called
