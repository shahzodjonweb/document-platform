"""The bot answers once: no screen repeated, nothing extra after a refusal.

Each step counts the messages the bot sends. A button tap changes the screen
the customer is looking at; it does not add a new one.
"""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.commerce.models import LocalBotMessage
from apps.core import channel_gate
from apps.core.identity import resolve_account
from apps.core.models import BotCallback, BotConversation, ChannelMembership
from telegram.channels import COPY as GATE
from telegram.local import dispatch_local
from tests.test_channel_gate import Telegram, require_channels
from tests.test_manual_payments import pdf

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]


@pytest.fixture
def customer(settings, monkeypatch):
    import telegram.bot as bot
    monkeypatch.setattr(bot, 'ALBUM_SETTLE', 0)
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    settings.LOCAL_SYNC_JOBS = True
    account = resolve_account({'id': 984001, 'first_name': 'Calm chat'}, is_test=True)
    BotConversation.objects.create(telegram_user_id=account.telegram_user_id, locale='en', language_selected_at=timezone.now())
    return account


@pytest.fixture
def telegram(monkeypatch):
    fake = Telegram()
    monkeypatch.setattr(channel_gate, '_call', fake)
    monkeypatch.setattr(channel_gate, '_token', lambda: '1:TOKEN')
    return fake


class Chat:
    """Drives the local bot and counts what it sends at each step."""

    def __init__(self, account):
        self.account, self.result = account, None

    def sent(self):
        return LocalBotMessage.objects.filter(account=self.account, direction='outbound').count()

    def do(self, **kwargs):
        before = self.sent()
        self.result = dispatch_local(self.account, **kwargs)
        return self.sent() - before

    def tap(self, action, **payload):
        for message in reversed(self.result['messages']):
            for row in message['buttons']:
                for button in row:
                    data = button.get('callback_data')
                    ref = BotCallback.objects.filter(pk=data, action=action).first() if data else None
                    if ref and all(ref.payload.get(k) == v for k, v in payload.items()):
                        return self.do(callback_data=data)
        raise AssertionError(f'No {action} button')

    def last(self):
        """What the bot's newest message says now, after any edits."""
        return LocalBotMessage.objects.filter(account=self.account, direction='outbound').order_by('-created_at').first().text


def test_choosing_a_service_before_joining_turns_the_menu_into_the_channels(customer, telegram):
    require_channels()
    chat = Chat(customer)
    chat.do(text='/start')
    assert chat.tap('tool', feature_id='pdf.images_to_pdf') == 0, 'the menu changes; nothing is added'
    assert GATE['en']['gate_one'] in chat.last()
    telegram.statuses = {'@pdfmaster_news': 'member'}
    assert chat.tap('channels_check') == 1, 'thanks replaces the channels; the service is the one new screen'
    assert 'PDF from images' in chat.last() and 'Merge' not in chat.last()


def test_an_ai_service_asks_for_the_channels_before_the_description(customer, telegram):
    require_channels()
    chat = Chat(customer)
    chat.do(text='/start')
    assert chat.tap('ai_tool', feature_id='ai.pdf_topic') == 0
    assert GATE['en']['gate_one'] in chat.last()
    telegram.statuses = {'@pdfmaster_news': 'member'}
    chat.tap('channels_check')
    assert 'PDF on a topic' in chat.last()
    assert chat.do(text='A two page note about tides for students') == 1, '"Preparing…" becomes the priced draft'
    assert 'Ready to start' in chat.last()


def test_a_refusal_after_the_description_is_said_once_and_the_description_is_kept(customer, telegram):
    require_channels()
    telegram.statuses = {'@pdfmaster_news': 'member'}
    chat = Chat(customer)
    chat.do(text='/start')
    chat.tap('ai_tool', feature_id='ai.pdf_topic')
    # They leave the channel while writing.
    telegram.statuses = {}
    ChannelMembership.objects.all().delete()
    assert chat.do(text='A two page note about tides for students') == 1, 'the channels replace "Preparing…", the question is not asked again'
    assert GATE['en']['gate_one'] in chat.last()
    telegram.statuses = {'@pdfmaster_news': 'member'}
    chat.tap('channels_check')
    assert 'Ready to start' in chat.last() and 'tides' in chat.last(), 'what they wrote is priced, not asked for again'


def test_the_daily_ai_limit_is_said_once(customer, telegram, settings):
    from operations import plans as plan_settings
    settings.ENABLE_BETA_TOOLS = True
    plan_settings.save('free', {'daily_ai_documents': 1})
    chat = Chat(customer)
    chat.do(text='/start')
    chat.tap('ai_tool', feature_id='ai.pdf_topic')
    chat.do(text='A two page note about tides for students')
    chat.tap('ai_run')
    chat.do(text='/start')
    chat.tap('ai_tool', feature_id='ai.pdf_topic')
    assert chat.do(text='Another two page note about the moon') == 1, 'one message: the limit, not the question again'
    assert 'free plan' in chat.last()
    assert BotConversation.objects.get(pk=customer.telegram_user_id).state == ''


def test_an_album_gets_one_screen(customer, telegram):
    chat = Chat(customer)
    sent = [chat.do(uploaded=SimpleUploadedFile(f'p{i}.pdf', pdf(), 'application/pdf'), media_group_id='g1') for i in range(3)]
    assert sent == [1, 0, 0], 'the first file shows the screen; the rest update it'
    assert 'Merge PDFs' in chat.last() and 'p2.pdf' in chat.last()


def test_an_album_before_joining_gets_one_channel_screen_and_then_one_merge(customer, telegram):
    require_channels()
    chat = Chat(customer)
    sent = [chat.do(uploaded=SimpleUploadedFile(f'p{i}.pdf', pdf(), 'application/pdf'), media_group_id='g2') for i in range(3)]
    assert sent == [1, 0, 0] and GATE['en']['gate_one'] in chat.last()
    telegram.statuses = {'@pdfmaster_news': 'member'}
    assert chat.tap('channels_check') == 1
    assert 'Merge PDFs' in chat.last() and all(f'p{i}.pdf' in chat.last() for i in range(3))


def test_files_for_an_ai_description_answer_once(customer, telegram):
    chat = Chat(customer)
    chat.do(text='/start')
    chat.tap('ai_tool', feature_id='ai.pdf_topic')
    sent = [chat.do(uploaded=SimpleUploadedFile(f's{i}.pdf', pdf(), 'application/pdf'), media_group_id='g3') for i in range(2)]
    assert sent == [1, 0]


def test_ive_joined_before_joining_changes_the_same_message(customer, telegram):
    require_channels()
    chat = Chat(customer)
    chat.do(text='/start')
    chat.tap('tool', feature_id='pdf.images_to_pdf')
    assert chat.tap('channels_check') == 0 and chat.tap('channels_check') == 0
    assert "You haven't joined" in chat.last()


def test_choosing_options_never_adds_messages(customer, telegram):
    chat = Chat(customer)
    chat.do(uploaded=SimpleUploadedFile('one.pdf', pdf(), 'application/pdf'))
    assert chat.tap('tool', feature_id='pdf.rotate') == 0
    assert chat.tap('settings') == 0
    assert chat.tap('controls') == 0


def test_album_files_arriving_together_draw_one_screen():
    """With updates handled side by side, only the newest file of an album answers."""
    import asyncio
    from types import SimpleNamespace
    import telegram.bot as bot
    bot._albums.clear()
    messages = [SimpleNamespace(media_group_id='g9', message_id=n, chat=SimpleNamespace(id=7)) for n in (11, 12, 13)]

    async def arrive():
        return await asyncio.gather(*(bot.album_target(m) for m in messages))
    results = asyncio.run(arrive())
    answering = [target for target, _ in results if target is not None]
    assert [m.message_id for m in answering] == [13]


def test_an_error_after_a_tap_replaces_that_screen_but_an_error_after_typing_is_a_reply():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from apps.core.errors import DomainError
    from telegram.bot import safe_error
    account = SimpleNamespace(locale='en', telegram_user_id=None)
    tapped = SimpleNamespace(from_user=SimpleNamespace(is_bot=True), edit_text=AsyncMock(), answer=AsyncMock())
    asyncio.run(safe_error(tapped, account, DomainError('quota_exceeded')))
    assert tapped.edit_text.await_count == 1 and not tapped.answer.called
    typed = SimpleNamespace(from_user=SimpleNamespace(is_bot=False), edit_text=AsyncMock(), answer=AsyncMock())
    asyncio.run(safe_error(typed, account, DomainError('quota_exceeded')))
    assert typed.answer.await_count == 1 and not typed.edit_text.called
