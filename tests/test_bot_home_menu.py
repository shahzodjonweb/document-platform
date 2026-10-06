"""The bot's home screen leads with four full-width buttons for what people come for."""
import pytest
from django.utils import timezone

from apps.core.identity import resolve_account
from apps.core.models import BotConversation
from operations.integrations import save_config
from telegram.local import dispatch_local

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]

HOME = {
    'uz': ['✨ Mavzuga oid PDF · AI', '✨ Mavzuga oid Slayd · AI', '🖼 Rasmlardan PDF', '💎 Obuna bo‘lish'],
    'ru': ['✨ PDF по теме · ИИ', '✨ Слайды по теме · ИИ', '🖼 PDF из фото', '💎 Оформить подписку'],
    'en': ['✨ PDF on a topic · AI', '✨ Slides on a topic · AI', '🖼 PDF from images', '💎 Subscribe'],
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
def test_home_leads_with_four_full_width_buttons(settings, locale):
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    account = customer(locale)
    result = dispatch_local(account, text='/start')
    rows = result['messages'][-1]['buttons']
    assert [[button['label'] for button in row] for row in rows[:4]] == [[label] for label in HOME[locale]]
    # Everything else is still reachable, two to a row underneath.
    assert all(len(row) == 2 for row in rows[4:]) and len(rows) == 7


def test_subscribe_opens_the_plans(settings):
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    account = customer('uz')
    result = dispatch_local(account, text='/start')
    button = result['messages'][-1]['buttons'][3][0]
    plans = dispatch_local(account, callback_data=button['callback_data'])
    text = '\n'.join(message['text'] for message in plans['messages'])
    assert 'Plus' in text and 'Premium' in text, text
