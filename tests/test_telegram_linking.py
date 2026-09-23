"""Telegram linking requires both bot confirmation and the original browser."""
import asyncio
import hashlib
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiogram.types import Chat, Update
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory
from django.utils import timezone

from apps.commerce.models import BotDelivery, Invoice
from apps.commerce.providers import TelegramStarsProvider
from apps.commerce.services import create_invoice, record_payment, validate_precheckout
from apps.core.errors import DomainError
from apps.core.identity import exchange_challenge, resolve_account
from apps.core.models import Account, AuthChallenge, BotCallback
from apps.core.services import create_quote, execute_job, submit_job, upload_file
from telegram.delivery import attempt, enqueue
from telegram.local import dispatch_local
from tests.test_bot_transport import Harness, pdf

pytestmark = pytest.mark.django_db(transaction=True)


def email_account(**values):
    return Account.objects.create(email='owner@example.com', email_verified_at=timezone.now(), **values)


def challenge_for(account):
    token, verifier = 'telegram-link-deep-link-token', 'original-browser-only-verifier'
    challenge = AuthChallenge.objects.create(
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        verifier_hash=hashlib.sha256(verifier.encode()).hexdigest(),
        browser_hint='Account settings in the initiating browser',
        expires_at=timezone.now()+timedelta(minutes=5),
        intent='link', link_account=account, link_auth_version=account.auth_version,
    )
    return challenge, token, verifier


def test_link_does_not_create_telegram_account_before_browser_finishes():
    account = email_account()
    challenge, token, verifier = challenge_for(account)
    harness = Harness()
    harness.command('/start login_'+token)
    callback = BotCallback.objects.get(action='link_login')
    assert callback.account_id == account.id
    assert Account.objects.count() == 1
    assert not Account.objects.filter(telegram_user_id=42).exists()
    challenge.refresh_from_db()
    assert challenge.approved_at is None

    harness.click(harness.token('Confirm Telegram link'))
    account.refresh_from_db()
    challenge.refresh_from_db()
    assert challenge.approved_at is not None
    assert account.telegram_user_id is None
    assert Account.objects.count() == 1
    linked = exchange_challenge(challenge.id, verifier, link_account=account)
    account.refresh_from_db()
    assert linked.id == account.id and account.telegram_user_id == 42
    assert resolve_account({'id':42,'first_name':'Telegram user'}, 'bot').id == account.id
    assert Account.objects.count() == 1


def test_link_callback_rejects_another_telegram_sender_without_creating_account():
    account = email_account()
    challenge, token, _ = challenge_for(account)
    harness = Harness()
    harness.command('/start login_'+token)
    button = harness.token('Confirm Telegram link')
    harness.click(button, uid=43)
    challenge.refresh_from_db()
    assert challenge.approved_at is None
    assert Account.objects.count() == 1
    harness.click(button)
    challenge.refresh_from_db()
    assert challenge.approved_at is not None
    assert challenge.telegram_user['id'] == 42
    assert Account.objects.count() == 1


def test_link_request_requires_private_bot_conversation():
    account = email_account()
    challenge, token, _ = challenge_for(account)
    harness = Harness()
    message = harness.incoming(text='/start login_'+token, entities=[{'type':'bot_command','offset':0,'length':6}])
    message = message.model_copy(update={'chat':Chat(id=-42, type='group')})
    asyncio.run(harness.dispatcher.feed_update(harness.bot, Update(update_id=10, message=message)))
    challenge.refresh_from_db()
    assert not BotCallback.objects.exists()
    assert challenge.approved_at is None
    assert Account.objects.count() == 1


def test_link_does_not_merge_another_existing_telegram_customer():
    target = email_account()
    existing = resolve_account({'id':42,'first_name':'Existing Telegram customer'})
    challenge, token, _ = challenge_for(target)
    harness = Harness()
    harness.command('/start login_'+token)
    harness.click(harness.token('Confirm Telegram link'))
    challenge.refresh_from_db()
    target.refresh_from_db()
    existing.refresh_from_db()
    assert challenge.approved_at is None
    assert target.telegram_user_id is None
    assert existing.telegram_user_id == 42
    assert Account.objects.count() == 2


def test_expired_link_confirmation_and_invalid_start_have_no_account_side_effect():
    harness = Harness()
    harness.command('/start login_unknown')
    assert Account.objects.count() == 0
    account = email_account()
    challenge, token, _ = challenge_for(account)
    harness.command('/start login_'+token)
    button = harness.token('Confirm Telegram link')
    BotCallback.objects.filter(token=button).update(expires_at=timezone.now()-timedelta(seconds=1))
    harness.click(button)
    challenge.refresh_from_db()
    assert challenge.approved_at is None
    assert Account.objects.count() == 1
    BotCallback.objects.filter(token=button).delete()
    harness.click(button)
    assert Account.objects.count() == 1


def test_telegram_invoice_and_provider_calls_require_linked_identity():
    account = email_account(is_test=True)
    with pytest.raises(DomainError, match='telegram_link_required'):
        create_invoice(account, 'plus', 'unlinked-invoice-key')
    assert Invoice.objects.count() == 0
    provider = TelegramStarsProvider()
    provider.call = Mock(side_effect=AssertionError('Telegram must not be called'))
    payment = SimpleNamespace(account=account)
    for action in (
        lambda: provider.invoice_link(payment, 'unused'),
        lambda: provider.set_renewal(payment, True),
        lambda: provider.refund(payment),
    ):
        with pytest.raises(DomainError, match='telegram_link_required'):
            action()
    provider.call.assert_not_called()
    with pytest.raises(DomainError, match='invalid_invoice'):
        validate_precheckout(None, 'unused', 'XTR', 50)
    with pytest.raises(DomainError, match='invalid_invoice'):
        record_payment(None, 'unused', 'XTR', 50, 'unused')


def test_email_account_can_process_pdf_but_cannot_enqueue_telegram_delivery():
    account = email_account()
    asset = upload_file(account, SimpleUploadedFile('source.pdf', pdf((210,))))
    quote = create_quote(account, 'pdf.rotate', [str(asset.id)], {'angle':90})
    job, _ = submit_job(account, quote.id, 'email-customer-pdf-job')
    job = execute_job(job.id)
    assert job.status == 'succeeded', job.error_code
    artifact = job.artifacts.get()
    with pytest.raises(DomainError, match='telegram_link_required'):
        enqueue(artifact, 'unlinked-delivery')
    from apps.commerce.views import deliver_artifact
    request = RequestFactory().post('/api/v1/artifacts/'+str(artifact.id)+'/deliver', HTTP_IDEMPOTENCY_KEY='unlinked-delivery-browser')
    request.account = account
    with pytest.raises(DomainError, match='telegram_link_required'):
        deliver_artifact.__wrapped__(request, artifact.id)
    assert BotDelivery.objects.count() == 0
    # A stale queued delivery must also stop before transport or file access.
    delivery = BotDelivery.objects.create(account=account, artifact=artifact, idempotency_key='stale-unlinked-delivery')
    bot = Mock(send_message=AsyncMock(), send_document=AsyncMock())
    asyncio.run(attempt(delivery.id, bot))
    delivery.refresh_from_db()
    assert delivery.status == 'blocked' and delivery.error_code == 'telegram_link_required'
    bot.send_message.assert_not_awaited()
    bot.send_document.assert_not_awaited()


def test_local_bot_simulator_requires_telegram_identity(settings):
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    account = email_account(is_test=True)
    with pytest.raises(DomainError, match='telegram_link_required'):
        dispatch_local(account, text='/start')
