"""The tap under a post: the only way a bot can tell a post was seen."""
import uuid

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageReplyMarkup, EditMessageText, SendMessage

from apps.core import posts
from apps.core.models import Account, BotConversation, Post, PostRecipient
from telegram.bot import COPY
from telegram.invites import COPY as INVITES
from operations.integrations import save_config
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


def test_a_tap_on_an_invite_post_opens_invite_friends_and_keeps_its_button(delivered):
    save_config('telegram', {'token': '', 'username': 'fixture_bot', 'webapp_url': 'https://pdfmaster.example/en/app'})
    Post.objects.filter(pk=delivered.post_id).update(button_action='invite')
    BotConversation.objects.create(telegram_user_id=42, state='cv_wait_check', prompt={'asked': True})
    harness = Harness(onboard=False)
    harness.click(f'post:{delivered.id.hex}', uid=42)
    delivered.refresh_from_db()
    seen = delivered.viewed_at
    assert seen, 'the tap is still the view'
    [answer] = calls(harness, AnswerCallbackQuery)
    assert not answer.text and not answer.show_alert
    assert not calls(harness, EditMessageReplyMarkup), 'the post stays a way in'
    [screen] = calls(harness, SendMessage)
    assert screen.chat_id == 42 and screen.parse_mode == 'HTML'
    assert INVITES['ru']['title'] in screen.text and 'https://t.me/fixture_bot?start=ref_' in screen.text
    keyboard = screen.reply_markup.inline_keyboard
    assert keyboard[0][0].text == INVITES['ru']['share'] and keyboard[0][0].url.startswith('https://t.me/share/url?')
    assert [button.text for button in keyboard[-1]] == [COPY['ru']['account'], COPY['ru']['home']]
    conversation = BotConversation.objects.get(pk=42)
    assert (conversation.state, conversation.prompt) == ('', {}), 'an old question is not answered by what comes next'
    harness.click(f'post:{delivered.id.hex}', uid=42)
    delivered.refresh_from_db()
    assert delivered.viewed_at == seen and len(calls(harness, SendMessage)) == 2


@pytest.mark.parametrize('token', ['mine', f'post:{uuid.uuid4().hex}', 'post:not-a-row'])
def test_a_tap_that_is_not_the_tappers_own_is_refused(delivered, token):
    harness = Harness(onboard=False)
    harness.click(f'post:{delivered.id.hex}' if token == 'mine' else token, uid=43)
    delivered.refresh_from_db()
    assert delivered.viewed_at is None
    [answer] = calls(harness, AnswerCallbackQuery)
    assert answer.show_alert and answer.text == COPY['en']['controls_expired']
    assert not calls(harness, EditMessageReplyMarkup)
