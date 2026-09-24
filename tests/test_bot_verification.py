"""Native verification runs before domain handlers and survives process resets."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from aiogram.methods import SendMessage
from aiogram.types import Document, PreCheckoutQuery, Update
from django.utils import timezone
from django.db import close_old_connections, connection

from apps.core.models import Account, AuthChallenge, BotConversation, BotVerification, FileAsset
from operations.models import IntegrationConfig
from telegram.verification import COPY, consume, cleanup_expired_pending
from tests.test_bot_onboarding import GateHarness, challenge, link_button


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def enable_verification():
    IntegrationConfig.objects.create(key='antibot', configuration={'bot_enabled': True})


def verification_button(uid=42, correct=True):
    state = BotVerification.objects.get(pk=uid)
    choice = next(item for item in state.challenge['choices']
                  if (item['token'] == state.challenge['answer']) == correct)
    return f'human:{uid}:{state.nonce}:{choice["token"]}'


def start(h, locale='en'):
    h.message(text='/start')
    h.click(h.language(locale))


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_language_first_then_single_tap_verification_before_any_handler(locale):
    h = GateHarness()
    h.message(text='/start')
    assert not BotVerification.objects.exists() and not Account.objects.exists()
    h.click(h.language(locale))
    state = BotVerification.objects.get(pk=42)
    assert h.session.calls[-1].text == COPY[locale]['prompt'].format(icon=state.challenge['icon'])
    assert not h.ready and not h.handled and not Account.objects.exists()
    controls = [button for row in h.session.calls[-1].reply_markup.inline_keyboard for button in row]
    assert len(controls) == 8 and len({button.text for button in controls}) == 8
    assert all(len(button.callback_data.encode()) <= 64 for button in controls)
    h.click(verification_button())
    assert len(h.ready) == 1 and h.ready[0][1].id == 42 and h.ready[0][2] == locale
    state.refresh_from_db()
    assert timezone.now() + timedelta(days=29) < state.verified_until < timezone.now() + timedelta(days=31)
    assert not state.nonce and not state.challenge and not state.pending
    h.message(text='/tools')
    assert len(h.handled) == 1


def test_direct_commands_uploads_and_old_callbacks_cannot_bypass_verification():
    BotConversation.objects.create(telegram_user_id=42, locale='en', language_selected_at=timezone.now())
    h = GateHarness()
    h.click('old-sensitive-action')
    nonce = BotVerification.objects.get(pk=42).nonce
    for text in ('/start', '/tools', '/menu', '/account', '/cancel', 'hello'):
        h.message(text=text)
    h.message(document=Document(file_id='file', file_unique_id='file'))
    assert not h.handled and not h.ready and not Account.objects.exists()
    assert len([call for call in h.session.calls if isinstance(call, SendMessage)]) == 1
    assert BotVerification.objects.get(pk=42).nonce == nonce


def test_callbacks_are_owner_chat_nonce_and_single_use_bound():
    h = GateHarness()
    start(h)
    token = verification_button()
    h.click(token, uid=43)
    h.click(token, chat_id=43)
    h.click(token, chat_id=-100, chat_type='group')
    h.click(token.replace(':42:', ':43:'))
    h.click(token.replace(BotVerification.objects.get(pk=42).nonce, 'abcdefghijklmnop'))
    assert not h.ready and not h.handled
    assert not BotVerification.objects.get(pk=42).verified_until
    h.click(token)
    h.click(token)
    assert len(h.ready) == 1 and not h.handled


def test_challenge_and_verified_state_survive_new_dispatcher():
    h = GateHarness()
    start(h)
    token = verification_button()
    fresh = GateHarness()
    fresh.click(token)
    assert len(fresh.ready) == 1
    restarted = GateHarness()
    restarted.message(text='/tools')
    assert len(restarted.handled) == 1 and not restarted.session.calls


@pytest.mark.skipif(connection.vendor != 'postgresql', reason='Production row-lock concurrency requires PostgreSQL')
def test_concurrent_correct_callbacks_consume_challenge_only_once():
    h = GateHarness()
    start(h)
    token = verification_button()
    barrier = Barrier(2)

    def submit():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            return consume(42, token)['status']
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: submit(), range(2)))
    assert sorted(results) == ['already_verified', 'verified']


def test_three_wrong_attempts_lock_out_old_buttons_until_cooldown_then_rotate_nonce():
    h = GateHarness()
    start(h)
    right, wrong = verification_button(), verification_button(correct=False)
    for _ in range(3):
        h.click(wrong)
    state = BotVerification.objects.get(pk=42)
    assert state.failures == 3 and state.cooldown_until > timezone.now()
    assert state.challenge == {} and state.nonce == ''
    h.click(right)
    h.message(text='/start')
    h.message(text='/language')
    h.click(h.language('ru'))
    assert not h.ready and not h.handled and not state.verified_until
    BotVerification.objects.filter(pk=42).update(cooldown_until=timezone.now() - timedelta(seconds=1))
    h.message(text='/start')
    state.refresh_from_db()
    assert state.failures == 0 and state.nonce and state.nonce not in right
    h.click(right)
    assert not h.ready
    h.click(verification_button())
    assert len(h.ready) == 1 and h.ready[0][2] == 'ru'


def test_expired_challenge_auto_issues_new_buttons_and_rejects_old_solution():
    h = GateHarness()
    start(h)
    old = verification_button()
    BotVerification.objects.filter(pk=42).update(expires_at=timezone.now() - timedelta(seconds=1))
    h.click(old)
    assert not h.ready
    new = verification_button()
    assert old != new
    h.click(old)
    assert not h.ready
    h.click(new)
    assert len(h.ready) == 1


def test_verification_expires_after_thirty_days_and_old_button_never_works_again():
    h = GateHarness()
    start(h)
    old = verification_button()
    h.click(old)
    BotVerification.objects.filter(pk=42).update(verified_until=timezone.now() - timedelta(seconds=1))
    h.message(text='/tools')
    h.click(old)
    assert len(h.ready) == 1 and not h.handled
    h.click(verification_button())
    assert len(h.ready) == 2


def test_first_files_survive_both_language_and_verification_without_private_captions():
    h = GateHarness()
    h.message(document=Document(file_id='before', file_unique_id='before'), caption='private-caption')
    h.click(h.language('en'))
    h.message(document=Document(file_id='after', file_unique_id='after'), caption='private-caption')
    state = BotVerification.objects.get(pk=42)
    assert [item['document']['file_id'] for item in state.pending['uploads']] == ['before', 'after']
    assert 'private-caption' not in json.dumps(state.pending)
    assert not h.ready and not Account.objects.exists()
    h.click(verification_button())
    assert [item['document']['file_id'] for item in h.ready[0][3]['uploads']] == ['before', 'after']
    assert not BotVerification.objects.get(pk=42).pending


def test_file_album_is_bounded_deduplicated_and_cancel_discards_files():
    h = GateHarness()
    start(h)
    for number in range(12):
        message = h.message(document=Document(file_id=str(number), file_unique_id=str(number)))
        asyncio.run(h.dispatcher.feed_update(h.bot, Update(update_id=800 + number, message=message)))
    state = BotVerification.objects.get(pk=42)
    assert len(state.pending['uploads']) == 10 and state.pending['resend_file'] is True
    assert len([call for call in h.session.calls if isinstance(call, SendMessage)]) == 2
    h.message(text='/cancel')
    h.click(verification_button())
    assert h.ready[0][3] == {}


@pytest.mark.parametrize('intent', ['login', 'link'])
def test_auth_intent_takes_priority_over_files_and_survives_language_change(intent):
    c = challenge('private-token', intent=intent)
    h = GateHarness()
    h.message(text='/start login_private-token')
    h.click(h.language('en'))
    h.message(document=Document(file_id='private-file', file_unique_id='private-file'))
    h.message(text='/language')
    h.click(h.language('uz'))
    state = BotVerification.objects.get(pk=42)
    assert state.pending == {'challenge_id': str(c.pk), 'resend_file': True}
    assert 'private-token' not in json.dumps(state.pending)
    h.click(verification_button())
    assert h.ready[0][3] == {'challenge_id': str(c.pk), 'resend_file': True}
    assert not Account.objects.filter(telegram_user_id=42).exists()
    c.refresh_from_db()
    assert c.approved_at is None


def test_existing_link_confirmation_is_gated_and_resumed_without_creating_account():
    c = challenge('old-link')
    control = link_button(c)
    BotConversation.objects.create(telegram_user_id=42, locale='en', language_selected_at=timezone.now())
    h = GateHarness()
    h.click(control.token)
    assert not h.handled and not h.ready
    h.click(verification_button())
    assert h.ready[0][3] == {'challenge_id': str(c.pk)}
    assert not Account.objects.filter(telegram_user_id=42).exists()
    h.click(control.token)
    assert len(h.handled) == 1


def test_auth_expiring_during_verification_never_becomes_new_account_flow():
    from tests.test_bot_transport import Harness
    c = challenge('expiring-link')
    h = Harness(onboard=False)
    h.command('/start login_expiring-link')
    h.click(h.language('en'))
    AuthChallenge.objects.filter(pk=c.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    h.click(verification_button())
    assert not Account.objects.filter(telegram_user_id=42).exists()


def test_real_bot_defers_account_and_download_until_verified_then_resumes_first_file():
    from tests.test_bot_transport import Harness, pdf
    h = Harness(onboard=False)
    h.document('private-file', pdf())
    h.click(h.language('en'))
    assert not Account.objects.exists() and not FileAsset.objects.exists()
    h.click(verification_button())
    assert Account.objects.filter(telegram_user_id=42).count() == 1
    assert FileAsset.objects.count() == 1
    h.click('human:42:abcdefghijklmnop:00000000')
    assert FileAsset.objects.count() == 1


def test_local_simulator_preserves_staged_bytes_between_language_and_verification(settings):
    from apps.core.identity import resolve_account
    from telegram.local import _pending_directory, dispatch_local
    from tests.test_bot_local_pending_upload import language_token, pdf
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    account = resolve_account({'id': 996001, 'first_name': 'Local verification'}, is_test=True)
    first = dispatch_local(account, uploaded=pdf())
    dispatch_local(account, callback_data=language_token(first))
    state = BotVerification.objects.get(pk=account.telegram_user_id)
    identifier = state.pending['uploads'][0]['document']['file_id']
    path = _pending_directory(account) / identifier
    assert path.exists() and not FileAsset.objects.exists()
    dispatch_local(account, callback_data=verification_button(account.telegram_user_id))
    assert not path.exists() and FileAsset.objects.filter(account=account).count() == 1


def test_native_payment_events_bypass_verification_without_creating_challenge_state():
    h = GateHarness()
    h.message(successful_payment={
        'currency': 'XTR', 'total_amount': 100, 'invoice_payload': 'invoice',
        'telegram_payment_charge_id': 'charge', 'provider_payment_charge_id': 'provider',
    })
    query = PreCheckoutQuery(id='checkout', from_user=h.user(), currency='XTR', total_amount=100, invoice_payload='invoice')
    asyncio.run(h.dispatcher.feed_update(h.bot, Update(update_id=999, pre_checkout_query=query)))
    assert len(h.handled) == 2 and not h.session.calls
    assert not BotVerification.objects.exists() and not BotConversation.objects.exists()


def test_cleanup_removes_expired_file_handles_but_preserves_auth_and_verification():
    h = GateHarness()
    start(h)
    h.message(document=Document(file_id='private', file_unique_id='private'))
    BotVerification.objects.filter(pk=42).update(expires_at=timezone.now() - timedelta(seconds=1))
    cleanup_expired_pending(timezone.now())
    state = BotVerification.objects.get(pk=42)
    assert state.pending == {'resend_file': True}
    assert state.nonce


@pytest.mark.parametrize('data', ['human:42:broken:00000000', 'human:42:abcdefghijklmnop:no', 'human:invalid'])
def test_malformed_callbacks_do_not_create_state(data):
    assert consume(42, data) == {'status': 'invalid'}
    assert not BotVerification.objects.exists()


def test_admin_can_disable_verification_without_changing_language_first():
    IntegrationConfig.objects.filter(key='antibot').update(configuration={'bot_enabled': False})
    h = GateHarness()
    start(h)
    assert len(h.ready) == 1 and not BotVerification.objects.exists()
