"""Language-first routing with a real dispatcher, database and offline Telegram."""
import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone as dt_timezone

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, SendMessage, SetMyCommands
from aiogram.types import CallbackQuery, Chat, Document, Message, PreCheckoutQuery, Update, User
from django.utils import timezone

from apps.core.identity import approve_challenge_id, exchange_challenge
from apps.core.models import Account, AuthChallenge, BotCallback, BotConversation
from telegram.onboarding import LINK_RETURN_TEXT, chosen_locale, install_onboarding


pytestmark = pytest.mark.django_db(transaction=True)


class Session(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def close(self):
        pass

    async def stream_content(self, url, **kwargs):
        raise AssertionError('Onboarding must never download files')
        yield b''

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, (AnswerCallbackQuery, SetMyCommands)):
            return True
        assert isinstance(method, SendMessage), 'Onboarding should only send text and keyboards'
        return Message(
            message_id=100 + len(self.calls), date=datetime.now(dt_timezone.utc),
            chat=Chat(id=method.chat_id, type='private'), from_user=User(id=123, is_bot=True, first_name='Bot'),
            text=method.text, reply_markup=method.reply_markup,
        ).as_(bot)


class GateHarness:
    def __init__(self):
        self.session = Session()
        self.bot = Bot('123456:OFFLINE_TEST_TOKEN', session=self.session)
        self.dispatcher = Dispatcher()
        self.handled = []
        self.ready = []
        self.counter = 0

        async def handle(event, **data):
            self.handled.append((event, data.get('bot_locale')))

        async def ready(message, user, locale, pending):
            self.ready.append((message, user, locale, pending))

        self.dispatcher.message.register(handle)
        self.dispatcher.callback_query.register(handle)
        self.dispatcher.pre_checkout_query.register(handle)
        install_onboarding(self.dispatcher, ready)

    @staticmethod
    def user(uid=42, language='en'):
        return User(id=uid, is_bot=False, first_name='Customer', language_code=language)

    def message(self, uid=42, chat_id=None, chat_type='private', language='en', **values):
        self.counter += 1
        msg = Message(
            message_id=self.counter, date=datetime.now(dt_timezone.utc),
            chat=Chat(id=chat_id or uid, type=chat_type), from_user=self.user(uid, language), **values,
        )
        asyncio.run(self.dispatcher.feed_update(self.bot, Update(update_id=self.counter, message=msg)))
        return msg

    def click(self, data, uid=42, chat_id=None, chat_type='private'):
        self.counter += 1
        query = CallbackQuery(
            id=str(self.counter), from_user=self.user(uid), chat_instance='fixture', data=data,
            message=Message(
                message_id=100, date=datetime.now(dt_timezone.utc),
                chat=Chat(id=chat_id or uid, type=chat_type),
                from_user=User(id=123, is_bot=True, first_name='Bot'), text='Choose language',
            ),
        )
        asyncio.run(self.dispatcher.feed_update(self.bot, Update(update_id=self.counter, callback_query=query)))

    def button(self, label):
        for call in reversed(self.session.calls):
            if isinstance(call, SendMessage) and call.reply_markup:
                for row in call.reply_markup.inline_keyboard:
                    for button in row:
                        if button.text == label:
                            return button.callback_data
        raise AssertionError(f'Missing language button {label}')


@pytest.mark.parametrize('first_text', ['/start', 'Hello', '/tools', '/cancel', '/help', '/language'])
def test_first_private_contact_asks_for_language_before_account_or_handler(first_text):
    h = GateHarness()
    h.message(text=first_text, language='ru')
    assert not h.handled and not h.ready
    assert Account.objects.count() == 0
    conversation = BotConversation.objects.get(pk=42)
    assert conversation.locale == '' and conversation.language_selected_at is None
    assert chosen_locale(42) is None
    assert [row[0].text for row in h.session.calls[-1].reply_markup.inline_keyboard] == [
        'O‘zbekcha', 'English', 'Русский',
    ]


@pytest.mark.parametrize(('label', 'locale'), [('O‘zbekcha', 'uz'), ('English', 'en'), ('Русский', 'ru')])
def test_choice_persists_and_passes_real_callback_sender_to_ready(label, locale):
    h = GateHarness()
    h.message(text='/start', language='ru')
    h.click(h.button(label))
    assert not h.handled
    assert len(h.ready) == 1
    message, user, chosen, pending = h.ready[0]
    assert user.id == 42 and message.from_user.is_bot
    assert chosen == locale and pending == {}
    assert chosen_locale(42) == locale
    assert Account.objects.count() == 0
    assert BotConversation.objects.get(pk=42).pending == {}
    h.message(text='/tools', language='ru' if locale != 'ru' else 'uz')
    assert h.handled[0][1] == locale


def test_first_file_is_not_downloaded_and_must_be_resent_after_choice():
    h = GateHarness()
    h.message(document=Document(file_id='private', file_unique_id='private', file_name='sensitive.pdf'))
    assert not h.handled
    assert BotConversation.objects.get(pk=42).pending == {'resend_file': True}
    assert 'private' not in json.dumps(BotConversation.objects.get(pk=42).pending)
    h.click(h.button('English'))
    assert h.ready[0][3] == {'resend_file': True}
    assert Account.objects.count() == 0


def challenge(token, *, intent='link', expires=None, approved=False, consumed=False):
    account = Account.objects.create(email='existing@example.test', display_name='Existing customer')
    return AuthChallenge.objects.create(
        token_hash=hashlib.sha256(token.encode()).hexdigest(), verifier_hash=hashlib.sha256(b'fixture-verifier').hexdigest(),
        browser_hint='Chrome', expires_at=expires or timezone.now() + timedelta(minutes=5),
        link_account=account if intent == 'link' else None, intent=intent,
        approved_at=timezone.now() if approved else None,
        consumed_at=timezone.now() if consumed else None,
    )


@pytest.mark.parametrize('intent', ['login', 'link'])
def test_start_auth_preserves_only_challenge_id_without_creating_telegram_account(intent):
    token = 'private-challenge-token'
    c = challenge(token, intent=intent)
    h = GateHarness()
    h.message(text=f'/start login_{token}')
    state = BotConversation.objects.get(pk=42)
    assert state.pending == {'challenge_id': str(c.pk)}
    assert token not in json.dumps(state.pending)
    h.message(text='hello')  # A repeated greeting does not discard the pending link.
    h.click(h.button('O‘zbekcha'))
    assert h.ready[0][3] == {'challenge_id': str(c.pk)}
    assert Account.objects.count() == 1
    assert not Account.objects.filter(telegram_user_id=42).exists()
    c.refresh_from_db()
    assert c.approved_at is None and c.consumed_at is None


def test_upload_during_language_choice_does_not_discard_pending_account_link():
    c = challenge('link-token')
    h = GateHarness()
    h.message(text='/start login_link-token')
    h.message(document=Document(file_id='file', file_unique_id='file'))
    h.click(h.button('English'))
    assert h.ready[0][3] == {'challenge_id': str(c.pk), 'resend_file': True}
    assert Account.objects.count() == 1
    assert not Account.objects.filter(telegram_user_id=42).exists()


@pytest.mark.parametrize('flags', [
    {'expires': timezone.now() - timedelta(seconds=1)}, {'approved': True}, {'consumed': True},
])
def test_invalid_challenge_does_not_survive_language_choice(flags):
    c = challenge('expired-token', **flags)
    h = GateHarness()
    h.message(text='/start login_expired-token')
    h.click(h.button('English'))
    assert h.ready[0][3] == {'auth_error': 'challenge_expired'}
    assert str(c.pk) not in json.dumps(h.ready[0][3])
    assert Account.objects.count() == 1


@pytest.mark.parametrize(('payload', 'expected'), [
    ('ref_invite_ABC-123', {'referral_code': 'invite_ABC-123'}),
    ('ref_' + 'x' * 65, {}), ('ref_bad/code', {}), ('ref_bad code', {}),
])
def test_referral_pending_is_bounded(payload, expected):
    h = GateHarness()
    h.message(text='/start ' + payload)
    h.click(h.button('English'))
    assert h.ready[0][3] == expected


def test_language_change_updates_existing_identity_without_creating_another():
    account = Account.objects.create(telegram_user_id=42, email='linked@example.test', locale='en')
    BotConversation.objects.create(telegram_user_id=42, locale='en', language_selected_at=timezone.now())
    h = GateHarness()
    h.message(text='/language')
    assert not h.handled
    h.click(h.button('Русский'))
    account.refresh_from_db()
    assert account.locale == chosen_locale(42) == 'ru'
    assert account.email == 'linked@example.test' and Account.objects.count() == 1


def test_language_callbacks_bound_to_user_chat_nonce_and_single_use():
    h = GateHarness()
    h.message(text='/start')
    token = h.button('English')
    h.click(token, uid=43)
    h.click(token, uid=42, chat_id=43)
    h.click(token, uid=42, chat_id=-100, chat_type='group')
    assert not h.ready and chosen_locale(42) is None and chosen_locale(43) is None
    h.click(token)
    h.click(token)
    assert len(h.ready) == 1
    assert Account.objects.count() == 0


def test_language_menu_expiry_and_new_menu_invalidate_old_buttons():
    h = GateHarness()
    h.message(text='/start')
    old_token = h.button('English')
    BotConversation.objects.filter(pk=42).update(language_expires_at=timezone.now() - timedelta(seconds=1))
    h.click(old_token)
    assert not h.ready
    h.message(text='/language')
    h.click(old_token)
    assert not h.ready
    h.click(h.button('O‘zbekcha'))
    assert chosen_locale(42) == 'uz'


@pytest.mark.parametrize('token', ['lang:42:é:en', 'lang:42:bad:en', 'lang:42:abcdefghijklmnop:fr', 'lang:invalid'])
def test_malformed_language_buttons_are_safely_rejected(token):
    h = GateHarness()
    h.message(text='/start')
    h.click(token)
    assert not h.ready and chosen_locale(42) is None


def test_old_action_before_onboarding_is_not_executed_or_replayed_after_choice():
    h = GateHarness()
    h.click('old-destructive-confirm-button')
    assert not h.handled and Account.objects.count() == 0
    h.click(h.button('English'))
    assert not h.handled and h.ready[0][3] == {}


@pytest.mark.parametrize('chat_type', ['group', 'supergroup'])
def test_groups_cannot_create_customer_state_or_receive_files(chat_type):
    h = GateHarness()
    h.message(text='/start login_secret', chat_id=-100, chat_type=chat_type)
    h.message(document=Document(file_id='file', file_unique_id='file'), chat_id=-100, chat_type=chat_type)
    assert not h.handled and not h.ready
    assert Account.objects.count() == 0 and BotConversation.objects.count() == 0
    assert all('private chat' in call.text for call in h.session.calls)


def test_successful_payment_and_precheckout_bypass_language_gate():
    h = GateHarness()
    h.message(successful_payment={
        'currency': 'XTR', 'total_amount': 100, 'invoice_payload': 'invoice',
        'telegram_payment_charge_id': 'charge', 'provider_payment_charge_id': 'provider',
    })
    query = PreCheckoutQuery(id='checkout', from_user=h.user(), currency='XTR', total_amount=100, invoice_payload='invoice')
    asyncio.run(h.dispatcher.feed_update(h.bot, Update(update_id=999, pre_checkout_query=query)))
    assert len(h.handled) == 2 and not h.session.calls and not h.ready
    assert BotConversation.objects.count() == 0 and Account.objects.count() == 0


def link_button(challenge, uid=42):
    return BotCallback.objects.create(
        token='owner-bound-link-button', account=challenge.link_account, action='link_login',
        payload={'challenge_id': str(challenge.id), 'telegram_user_id': uid},
        expires_at=timezone.now() + timedelta(minutes=10),
    )


def test_linking_survives_language_and_start_before_and_after_approval_until_browser_exchange():
    c = challenge('linking-token')
    h = GateHarness()
    h.message(text='/start login_linking-token')
    h.click(h.button('English'))
    assert BotConversation.objects.get(pk=42).pending == {'challenge_id': str(c.id)}
    h.message(text='/start')
    h.message(text='/language')
    h.click(h.button('Русский'))
    h.message(document=Document(file_id='pending-file', file_unique_id='pending-file'))
    assert len(h.ready) == 4 and not h.handled
    assert all(row[3]['challenge_id'] == str(c.id) for row in h.ready)
    assert not Account.objects.filter(telegram_user_id=42).exists()

    control = link_button(c)
    h.click(control.token)
    assert len(h.handled) == 1  # Only the owned approval callback can run.
    approve_challenge_id(c.id, {'id': 42, 'first_name': 'Customer'})
    h.message(text='/start')
    h.message(text='ordinary message')
    h.click('old-unrelated-action')
    assert len(h.handled) == 1 and len(h.ready) == 4
    assert h.session.calls[-1].text == LINK_RETURN_TEXT['ru']
    h.message(text='/language')
    h.click(h.button('O‘zbekcha'))
    assert h.session.calls[-1].text == LINK_RETURN_TEXT['uz']
    assert len(h.ready) == 4 and not Account.objects.filter(telegram_user_id=42).exists()

    account = exchange_challenge(c.id, 'fixture-verifier', link_account=c.link_account)
    assert account.telegram_user_id == 42 and Account.objects.count() == 1
    h.message(text='/tools')
    assert len(h.handled) == 2 and h.handled[-1][1] == 'uz'
    assert BotConversation.objects.get(pk=42).pending == {}
    h.message(text='/language')
    h.click(h.button('English'))
    assert h.ready[-1][3] == {} and chosen_locale(42) == 'en'
    account.refresh_from_db()
    assert account.locale == 'en' and Account.objects.count() == 1


def test_already_onboarded_but_unlinked_customer_tracks_login_start_before_handlers():
    c = challenge('returning-link-token')
    BotConversation.objects.create(telegram_user_id=42, locale='en', language_selected_at=timezone.now())
    h = GateHarness()
    h.message(text='/start login_returning-link-token')
    h.message(text='/start')
    assert not h.handled and len(h.ready) == 2
    assert h.ready[-1][3] == {'challenge_id': str(c.id)}
    assert not Account.objects.filter(telegram_user_id=42).exists()


def test_pending_link_recovers_from_owner_bound_callback_after_state_loss():
    c = challenge('recovered-link-token')
    link_button(c)
    BotConversation.objects.create(telegram_user_id=42, locale='en', language_selected_at=timezone.now())
    h = GateHarness()
    h.message(text='/start')
    assert not h.handled and h.ready[-1][3] == {'challenge_id': str(c.id)}
    assert BotConversation.objects.get(pk=42).pending == {'challenge_id': str(c.id)}


def test_expired_link_releases_gate_and_clears_stale_pending_state():
    c = challenge('expires-link-token')
    h = GateHarness()
    h.message(text='/start login_expires-link-token')
    h.click(h.button('English'))
    link_button(c)
    AuthChallenge.objects.filter(pk=c.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    h.message(text='/start')
    assert len(h.handled) == 1
    assert BotConversation.objects.get(pk=42).pending == {}


def test_link_confirmation_for_another_user_does_not_bypass_linking_gate():
    c = challenge('blocked-callback-token')
    h = GateHarness()
    h.message(text='/start login_blocked-callback-token')
    h.click(h.button('English'))
    control = link_button(c, uid=43)
    h.click(control.token)
    assert not h.handled and len(h.ready) == 2
    assert h.ready[-1][3] == {'challenge_id': str(c.id)}


def test_link_expiring_during_first_language_choice_shows_error_instead_of_new_account_flow():
    c = challenge('expires-during-choice')
    h = GateHarness()
    h.message(text='/start login_expires-during-choice')
    AuthChallenge.objects.filter(pk=c.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    h.click(h.button('English'))
    assert h.ready[-1][3] == {'auth_error': 'challenge_expired'}
    assert Account.objects.count() == 1 and not h.handled


def test_real_bot_repeated_start_and_language_do_not_split_account_during_linking():
    from tests.test_bot_transport import Harness
    from tests.test_telegram_linking import challenge_for, email_account
    account = email_account()
    c, token, verifier = challenge_for(account)
    h = Harness(onboard=False)
    h.command('/start login_' + token)
    h.click(h.token('English'))
    h.command('/language')
    h.click(h.token('English'))
    h.command('/start')
    assert Account.objects.count() == 1 and not Account.objects.filter(telegram_user_id=42).exists()
    h.click(h.token('Confirm Telegram link'))
    h.command('/language')
    h.click(h.token('Русский'))
    h.command('/start')
    assert Account.objects.count() == 1 and not Account.objects.filter(telegram_user_id=42).exists()
    assert h.session.calls[-1].text == LINK_RETURN_TEXT['ru']
    exchange_challenge(c.id, verifier, link_account=account)
    h.command('/start')
    account.refresh_from_db()
    assert account.telegram_user_id == 42 and account.locale == 'ru'
    assert Account.objects.count() == 1 and BotConversation.objects.get(pk=42).pending == {}


def test_real_bot_repeated_expired_link_callbacks_never_create_telegram_account():
    from tests.test_bot_transport import Harness
    from tests.test_telegram_linking import challenge_for, email_account
    account = email_account()
    c, token, _ = challenge_for(account)
    h = Harness(onboard=False)
    h.command('/start login_' + token)
    h.click(h.token('English'))
    confirmation = h.token('Confirm Telegram link')
    AuthChallenge.objects.filter(pk=c.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    h.click(confirmation)
    h.click(confirmation)
    c.refresh_from_db()
    assert c.approved_at is None and c.consumed_at is None
    assert Account.objects.count() == 1 and not Account.objects.filter(telegram_user_id=42).exists()
