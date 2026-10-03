"""Buttons on old messages: a screen still opens; what must be fresh opens the menu instead."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.commerce.models import LocalBotMessage
from apps.core.identity import resolve_account
from apps.core.models import BotCallback, BotConversation, Job
from telegram.bot import COPY
from telegram.local import dispatch_local
from tests.test_bot_no_flood import Chat

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]
EN = COPY['en']


@pytest.fixture
def customer(settings):
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    account = resolve_account({'id': 983001, 'first_name': 'Scroller'}, is_test=True)
    BotConversation.objects.create(telegram_user_id=account.telegram_user_id, locale='en', language_selected_at=timezone.now())
    return account


def age_every_button(days=3):
    BotCallback.objects.update(expires_at=timezone.now() - timedelta(days=days))


def outbound_texts(account):
    return list(LocalBotMessage.objects.filter(account=account, direction='outbound').values_list('text', flat=True))


def test_a_days_old_screen_button_still_opens_its_screen_in_place(customer):
    chat = Chat(customer)
    chat.do(text='/plans')
    age_every_button()
    assert chat.tap('subscription') == 0, 'the old message changes; nothing new is sent'
    assert EN['controls_expired'] not in outbound_texts(customer)
    assert 'Free' in chat.last()
    age_every_button()
    assert chat.tap('home') == 0
    assert EN['stale_button'] not in chat.last(), 'a screen button is not stale, it just works'


def test_an_old_button_that_must_be_fresh_opens_the_menu_and_does_nothing_else(customer):
    old = BotCallback.objects.create(token='old-run-button', account=customer, action='run',
                                     payload={'quote_id': 'x', 'draft_id': 'y'},
                                     expires_at=timezone.now() - timedelta(days=2))
    dispatch_local(customer, callback_data=old.pk)
    texts = outbound_texts(customer)
    assert any(EN['stale_button'] in text for text in texts)
    assert EN['controls_expired'] not in texts, 'no dead-end alert'
    assert Job.objects.count() == 0


def test_a_button_the_bot_no_longer_knows_opens_the_menu(customer):
    dispatch_local(customer, callback_data='long-gone-token')
    assert any(EN['stale_button'] in text for text in outbound_texts(customer))


def test_someone_elses_button_is_still_refused(customer):
    other = resolve_account({'id': 983002, 'first_name': 'Forwarded'}, is_test=True)
    BotConversation.objects.create(telegram_user_id=other.telegram_user_id, locale='en', language_selected_at=timezone.now())
    theirs = BotCallback.objects.create(token='someone-elses-home', account=customer, action='home', payload={},
                                        expires_at=timezone.now() + timedelta(minutes=10))
    dispatch_local(other, callback_data=theirs.pk)
    assert outbound_texts(other) == [EN['controls_expired']]


def test_a_typed_message_after_a_pause_is_only_called_late_when_a_question_was_pending(customer):
    BotConversation.objects.filter(pk=customer.telegram_user_id).update(updated_at=timezone.now() - timedelta(hours=2))
    dispatch_local(customer, text='hello again')
    assert not any(EN['stale_reply'] in text for text in outbound_texts(customer))
    BotConversation.objects.filter(pk=customer.telegram_user_id).update(
        state='input', prompt={'kind': 'pages'}, updated_at=timezone.now() - timedelta(hours=2))
    dispatch_local(customer, text='1-3')
    assert any(EN['stale_reply'] in text for text in outbound_texts(customer))
    assert BotConversation.objects.get(pk=customer.telegram_user_id).state == ''
