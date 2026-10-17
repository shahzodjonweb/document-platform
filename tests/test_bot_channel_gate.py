"""The channel rule in the bot: shown the channels, "I've joined", back to the file."""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.core import channel_gate
from apps.core.identity import resolve_account
from apps.core.models import BotCallback, BotConversation, BotDraft
from telegram.channels import COPY
from telegram.local import dispatch_local
from tests.test_channel_gate import Telegram, require_channels
from tests.test_manual_payments import paid, pdf

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]


@pytest.fixture
def customer(settings, monkeypatch):
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    account = resolve_account({'id': 982001, 'first_name': 'Channel reader'}, is_test=True)
    BotConversation.objects.create(telegram_user_id=account.telegram_user_id, locale='en', language_selected_at=timezone.now())
    return account


@pytest.fixture
def telegram(monkeypatch):
    fake = Telegram()
    monkeypatch.setattr(channel_gate, '_call', fake)
    monkeypatch.setattr(channel_gate, '_token', lambda: '123456:TOKEN')
    return fake


def buttons(result):
    return [button for message in result['messages'] for row in message['buttons'] for button in row]


def token(result, action):
    for button in reversed(buttons(result)):
        data = button.get('callback_data')
        if data and BotCallback.objects.filter(pk=data, action=action).exists():
            return data
    raise AssertionError(f'No button for {action}')


def test_a_file_sent_before_joining_is_kept_and_the_channels_are_shown(customer, telegram):
    require_channels('@pdfmaster_news\n@pdfmaster_tips')
    result = dispatch_local(customer, uploaded=SimpleUploadedFile('notes.pdf', pdf(), 'application/pdf'))
    text = result['messages'][-1]['text']
    assert COPY['en']['gate_many'] in text
    links = [button.get('url') for button in buttons(result) if button.get('url')]
    assert links == ['https://t.me/pdfmaster_news', 'https://t.me/pdfmaster_tips']
    assert token(result, 'channels_check') and token(result, 'plans')
    assert BotDraft.objects.filter(account=customer).exists(), 'the file waits for its tool'


def test_ive_joined_checks_again_and_goes_back_to_the_file(customer, telegram):
    require_channels()
    gate = dispatch_local(customer, uploaded=SimpleUploadedFile('notes.pdf', pdf(), 'application/pdf'))
    telegram.statuses = {'@pdfmaster_news': 'member'}
    result = dispatch_local(customer, callback_data=token(gate, 'channels_check'))
    texts = [message['text'] for message in result['messages']]
    assert any(COPY['en']['welcome'] in text for text in texts)
    assert len(buttons(result)) > 2, 'the tool controls for the waiting file are shown'


def test_ive_joined_without_joining_says_which_channel_is_missing(customer, telegram):
    require_channels()
    gate = dispatch_local(customer, uploaded=SimpleUploadedFile('notes.pdf', pdf(), 'application/pdf'))
    dispatch_local(customer, callback_data=token(gate, 'channels_check'))
    # The channel screen itself changes; nothing new is sent.
    from apps.commerce.models import LocalBotMessage
    screen = LocalBotMessage.objects.filter(account=customer, direction='outbound').order_by('-created_at').first()
    assert "You haven't joined pdfmaster_news yet" in screen.text


def test_members_go_straight_to_the_tools(customer, telegram):
    require_channels()
    telegram.statuses = {'@pdfmaster_news': 'member'}
    result = dispatch_local(customer, uploaded=SimpleUploadedFile('notes.pdf', pdf(), 'application/pdf'))
    assert COPY['en']['gate_one'] not in result['messages'][-1]['text']


def test_plus_is_asked_to_join_and_offered_premium_as_the_way_round(customer, telegram):
    require_channels()
    paid(customer, 'plus')
    result = dispatch_local(customer, uploaded=SimpleUploadedFile('notes.pdf', pdf(), 'application/pdf'))
    assert COPY['en']['gate_plus_one'] in result['messages'][-1]['text']
    assert COPY['en']['plans'] in [button['label'] for button in buttons(result)]
    assert 'Premium' in COPY['en']['plans'] and 'Premium' in COPY['uz']['plans'] and 'Premium' in COPY['ru']['plans']


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_plus_is_never_told_the_product_is_free(customer, telegram, locale):
    """Someone who has just paid for Plus was told "PDF Master is free for
    members". Plus is told its plan works for members instead."""
    require_channels('@pdfmaster_news\n@pdfmaster_tips')
    paid(customer, 'plus')
    customer.locale = locale
    customer.save(update_fields=['locale'])
    BotConversation.objects.filter(pk=customer.telegram_user_id).update(locale=locale)
    text = dispatch_local(customer, uploaded=SimpleUploadedFile('notes.pdf', pdf(), 'application/pdf'))['messages'][-1]['text']
    assert COPY[locale]['gate_plus_many'] in text
    free = {'en': 'free', 'uz': 'bepul', 'ru': 'бесплатен'}[locale]
    assert free not in text.lower()
    for key in ('gate_plus_one', 'gate_plus_many'):
        assert 'Plus' in COPY[locale][key] and free not in COPY[locale][key].lower()
    assert free in COPY[locale]['gate_one'].lower(), 'Free is still told it is free'


def test_the_premium_way_round_is_offered_only_while_premium_is_on_sale(customer, telegram):
    """Premium is on sale exactly while it has a card price in the panel."""
    from operations import plans as plan_settings
    require_channels()
    plan_settings.save('premium', {'price_uzs': ''})

    def gate_buttons(name):
        sent = dispatch_local(customer, uploaded=SimpleUploadedFile(name, pdf(), 'application/pdf'))
        return [button['label'] for row in sent['messages'][-1]['buttons'] for button in row]

    labels = gate_buttons('notes.pdf')
    assert COPY['en']['plans'] not in labels, 'the plans screen it opens has no Premium to choose'
    assert COPY['en']['plans_neutral'] in labels
    # Priced again, the way round is offered again.
    plan_settings.save('premium', {'price_uzs': 60000})
    assert COPY['en']['plans'] in gate_buttons('other.pdf')


def test_premium_is_never_asked(customer, telegram):
    require_channels()
    paid(customer, 'premium')
    result = dispatch_local(customer, uploaded=SimpleUploadedFile('notes.pdf', pdf(), 'application/pdf'))
    assert COPY['en']['gate_one'] not in result['messages'][-1]['text']
    assert not BotCallback.objects.filter(account=customer, action='channels_check').exists()
