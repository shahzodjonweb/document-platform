"""The tap under a post: the only way a bot can tell a post was seen."""
import uuid

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageReplyMarkup, EditMessageText, SendMessage

from apps.core import posts
from apps.core.models import Account, BotConversation, PostRecipient
from telegram.bot import COPY
from tests.test_bot_transport import Harness

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def delivered(monkeypatch):
    # The anti-bot check is on and the reader never chose a language: neither
    # may stand between a tap and its count.
    monkeypatch.setattr('telegram.verification.enabled', lambda: True)
    Account.objects.create(telegram_user_id=42, locale='ru', display_name='Reader')
    post = posts.create(None, text='News', audience_kind='everyone')
    posts.start(post.pk)
    row = PostRecipient.objects.get(post=post)
    PostRecipient.objects.filter(pk=row.pk).update(status='delivered')
    return row


def calls(harness, kind):
    return [call for call in harness.session.calls if isinstance(call, kind)]


def test_a_tap_is_counted_once_thanked_and_its_button_taken_away(delivered):
    harness = Harness(onboard=False)
    harness.click(f'post:{delivered.id.hex}', uid=42)
    delivered.refresh_from_db()
    seen = delivered.viewed_at
    assert seen
    [answer] = calls(harness, AnswerCallbackQuery)
    assert answer.text == 'Спасибо!' and not answer.show_alert
    [edit] = calls(harness, EditMessageReplyMarkup)
    assert edit.reply_markup is None
    assert not calls(harness, SendMessage) and not calls(harness, EditMessageText), 'no menu, no language question'
    assert not BotConversation.objects.filter(pk=42).exists()
    harness.click(f'post:{delivered.id.hex}', uid=42)
    delivered.refresh_from_db()
    assert delivered.viewed_at == seen and len(calls(harness, AnswerCallbackQuery)) == 2


@pytest.mark.parametrize('token', ['mine', f'post:{uuid.uuid4().hex}', 'post:not-a-row'])
def test_a_tap_that_is_not_the_tappers_own_is_refused(delivered, token):
    harness = Harness(onboard=False)
    harness.click(f'post:{delivered.id.hex}' if token == 'mine' else token, uid=43)
    delivered.refresh_from_db()
    assert delivered.viewed_at is None
    [answer] = calls(harness, AnswerCallbackQuery)
    assert answer.show_alert and answer.text == COPY['en']['controls_expired']
    assert not calls(harness, EditMessageReplyMarkup)
