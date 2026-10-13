"""The plans screen says what each plan gives before it asks anyone to pay."""
import pytest
from django.utils import timezone

from apps.core.identity import resolve_account
from apps.core.models import Account, BotConversation
from operations import plans as plan_settings
from telegram.billing import PLAN_COPY
from telegram.local import dispatch_local
from tests.test_manual_payments import configure

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]


@pytest.fixture
def customer(settings):
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    account = resolve_account({'id': 984001, 'first_name': 'Chooser'}, is_test=True)
    BotConversation.objects.create(telegram_user_id=account.telegram_user_id, locale='uz', language_selected_at=timezone.now())
    Account.objects.filter(pk=account.pk).update(locale='uz')
    account.refresh_from_db()
    return account


def screen(account):
    return dispatch_local(account, text='/plans')['messages'][-1]['text']


def test_every_plan_says_what_it_includes_and_its_price(customer):
    configure(prices=None)  # the default prices: 20 000 and 60 000 so'm
    text = screen(customer)
    free, plus, premium = (text[text.index(head):] for head in ('Bepul</b>', 'Plus</b>', 'Premium</b>'))
    plus, free = plus[:plus.index('Premium</b>')], free[:free.index('Plus</b>')]
    for line in ("Bepul</b> — 0 so'm", 'AI hujjat va taqdimotlar: haftasiga 5 ta', 'AI tahrirlar: har bir faylga 3 ta',
                 'Fayl vositalari, Rasmlardan PDF ham: haftasiga 15 ta vazifa'):
        assert line in free, line
    for line in ("Plus</b> — 30 kun uchun 20 000 so'm", 'AI hujjat va taqdimotlar: haftasiga 20 ta',
                 'AI tahrirlar: har bir faylga 10 ta', 'Fayl vositalari: cheksiz', '5 ta saqlangan jarayon'):
        assert line in plus, line
    for line in ("Premium</b> — 30 kun uchun 60 000 so'm", 'AI hujjat va taqdimotlar: cheksiz', 'AI tahrirlar: cheksiz',
                 'Fayl vositalari: cheksiz', 'Kanallarga obuna bo‘lish shart emas',
                 'AI hujjat 35 sahifagacha, taqdimot 60 slaydgacha', 'Fayl 200 MB gacha, bitta vazifada 1 000 sahifagacha'):
        assert line in premium, line
    assert 'Kanallarga' not in free + plus, 'only Premium skips the channels'
    assert 'kredit' not in text.lower() and 'paket' not in text.lower()
    assert text.index('Bepul</b>') < text.index('Plus</b>') < text.index('Premium</b>') < text.index('Qanday to‘lanadi')
    assert 'Hozirgi tarifingiz: <b>Bepul</b>' in text and "Bepul</b> — 0 so'm · ✅ sizniki" in text


def test_an_admin_change_is_what_customers_read(customer):
    configure(prices=None)
    plan_settings.save('plus', {'weekly_ai_documents': 25, 'weekly_file_jobs': 1500, 'price_uzs': 25000})
    text = screen(customer)
    assert 'haftasiga 25 ta' in text and 'haftasiga 1 500 ta vazifa' in text and "25 000 so'm" in text


def test_a_plan_not_on_sale_is_not_described(customer):
    configure(prices=None)
    plan_settings.save('premium', {'price_uzs': ''})
    assert 'Premium</b>' not in screen(customer)


def test_the_customers_own_plan_is_marked(customer):
    configure(prices=None)
    Account.objects.filter(pk=customer.pk).update(staff_plan='premium')
    customer.refresh_from_db()
    text = screen(customer)
    assert 'Hozirgi tarifingiz: <b>Premium</b>' in text and 'Premium</b> — 30 kun uchun 60 000 so\'m · ✅ sizniki' in text


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_each_language_gets_the_comparison_and_how_to_pay(customer, locale):
    configure(prices=None)
    Account.objects.filter(pk=customer.pk).update(locale=locale)
    BotConversation.objects.filter(pk=customer.telegram_user_id).update(locale=locale)
    customer.refresh_from_db()
    text = screen(customer)
    words = PLAN_COPY[locale]
    assert text.startswith(words['title']) and words['how'] in text
    assert len(text) < 4096, 'one Telegram message'


def test_an_old_pack_button_or_pack_name_opens_the_plans(customer):
    """Packs are retired, but their buttons stay in chats and people still type
    /buy ai100. They were told payments are unavailable, which is not so."""
    from datetime import timedelta
    from apps.commerce.models import Invoice
    from apps.core.models import BotCallback
    configure(prices=None)
    BotCallback.objects.create(token='old-pack-button', account=customer, action='commerce_offer',
                               payload={'offer_id': 'tasks100'}, expires_at=timezone.now() + timedelta(minutes=20))
    for shown in (dispatch_local(customer, callback_data='old-pack-button'),
                  dispatch_local(customer, text='/buy ai100')):
        text = shown['messages'][-1]['text']
        assert text.startswith(PLAN_COPY['uz']['title']), text
        assert 'Plus</b>' in text and 'Premium</b>' in text
    assert not Invoice.objects.filter(account=customer).exists()
    # A plan on sale still goes straight to its checkout.
    checkout = dispatch_local(customer, text='/buy plus')['messages'][-1]['text']
    assert not checkout.startswith(PLAN_COPY['uz']['title'])
    assert Invoice.objects.filter(account=customer).count() == 1


def test_russian_plan_cards_say_ii_like_every_other_russian_screen(customer):
    configure(prices=None)
    words = PLAN_COPY['ru']
    assert not [key for key, value in words.items() if 'AI' in value]
    Account.objects.filter(pk=customer.pk).update(locale='ru')
    BotConversation.objects.filter(pk=customer.telegram_user_id).update(locale='ru')
    customer.refresh_from_db()
    text = screen(customer)
    assert 'ИИ-документы и презентации: 5 в неделю' in text and 'ИИ-правки: 3 на каждый файл' in text
    assert 'AI-' not in text
