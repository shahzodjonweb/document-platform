"""The bot's home screen leads with five full-width buttons for what people come for."""
import pytest
from django.utils import timezone

from apps.core.identity import resolve_account
from apps.core.models import BotConversation
from operations.integrations import save_config
from telegram.invites import COPY
from telegram.local import dispatch_local

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]

HOME = {
    'uz': ['✨ Mavzuga oid PDF · AI', '✨ Mavzuga oid Slayd · AI', '✨ CV (rezyume) · AI', '🖼 Rasmlardan PDF', '💎 Obuna bo‘lish'],
    'ru': ['✨ PDF по теме · ИИ', '✨ Слайды по теме · ИИ', '✨ Резюме · ИИ', '🖼 PDF из фото', '💎 Оформить подписку'],
    'en': ['✨ PDF on a topic · AI', '✨ Slides on a topic · AI', '✨ CV · AI', '🖼 PDF from images', '💎 Subscribe'],
}


def customer(locale):
    save_config('telegram', {'token': '', 'username': 'fixture_bot', 'webapp_url': 'https://pdfmaster.example/en/app'})
    account = resolve_account({'id': 980500 + len(locale), 'first_name': 'Menu'}, is_test=True)
    account.locale = locale
    account.save(update_fields=['locale'])
    BotConversation.objects.create(telegram_user_id=account.telegram_user_id, locale=locale,
                                   language_selected_at=timezone.now())
    return account


@pytest.mark.parametrize('locale', list(HOME))
def test_home_leads_with_five_full_width_buttons(settings, locale):
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    account = customer(locale)
    result = dispatch_local(account, text='/start')
    rows = result['messages'][-1]['buttons']
    assert [[button['label'] for button in row] for row in rows[:5]] == [[label] for label in HOME[locale]]
    # Free gift and My referrals come next; everything else is still reachable, two to a row underneath.
    assert [button['label'] for button in rows[5]] == [COPY[locale]['gift_button'], COPY[locale]['referrals_button']]
    assert all(len(row) == 2 for row in rows[5:]) and len(rows) == 9


@pytest.mark.parametrize('locale', list(HOME))
def test_free_gift_and_my_referrals_open_invite_friends(settings, locale):
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    account = customer(locale)
    for index in (0, 1):
        home = dispatch_local(account, text='/start')['messages'][-1]
        result = dispatch_local(account, callback_data=home['buttons'][5][index]['callback_data'])['messages']
        # The main menu becomes the invite screen in place.
        screen = next(message for message in result if message['id'] == home['id'])
        assert screen['text'].startswith(COPY[locale]['title']), screen['text'][:200]
        assert COPY[locale]['link'] in screen['text']
        assert [b['label'] for row in screen['buttons'] for b in row][0] == COPY[locale]['share']


def test_subscribe_opens_the_plans(settings):
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    account = customer('uz')
    result = dispatch_local(account, text='/start')
    button = result['messages'][-1]['buttons'][4][0]
    plans = dispatch_local(account, callback_data=button['callback_data'])
    text = '\n'.join(message['text'] for message in plans['messages'])
    assert 'Plus' in text and 'Premium' in text, text
