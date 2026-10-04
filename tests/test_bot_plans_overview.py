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
    configure(prices=None)  # the default prices: 60 000 and 100 000 so'm
    text = screen(customer)
    for line in ("Bepul</b> — 0 so'm", "Plus</b> — 30 kun uchun 60 000 so'm", "Premium</b> — 30 kun uchun 100 000 so'm",
                 '30 kunda 300 ta fayl vazifasi (kuniga 20 tagacha)', 'Kuniga 3 tagacha AI hujjat yoki taqdimot',
                 '30 kunda 1 500 ta fayl vazifasi', 'AI hujjat va taqdimotlar — kunlik cheklovsiz',
                 'AI hujjat 15 sahifagacha, taqdimot 30 slaydgacha', 'Fayl 200 MB gacha, bitta vazifada 1 000 sahifagacha',
                 '5 ta saqlangan jarayon'):
        assert line in text, line
    assert text.index('Bepul</b>') < text.index('Plus</b>') < text.index('Premium</b>') < text.index('Qanday to‘lanadi')
    assert 'Hozirgi tarifingiz: <b>Bepul</b>' in text and "Bepul</b> — 0 so'm · ✅ sizniki" in text


def test_an_admin_change_is_what_customers_read(customer):
    configure(prices=None)
    plan_settings.save('plus', {'file_tasks': 1800, 'price_uzs': 65000})
    text = screen(customer)
    assert '30 kunda 1 800 ta fayl vazifasi' in text and "65 000 so'm" in text


def test_a_plan_not_on_sale_is_not_described(customer):
    configure(prices=None)
    plan_settings.save('premium', {'price_uzs': ''})
    assert 'Premium</b>' not in screen(customer)


def test_the_customers_own_plan_is_marked(customer):
    configure(prices=None)
    Account.objects.filter(pk=customer.pk).update(staff_plan='premium')
    customer.refresh_from_db()
    text = screen(customer)
    assert 'Hozirgi tarifingiz: <b>Premium</b>' in text and 'Premium</b> — 30 kun uchun 100 000 so\'m · ✅ sizniki' in text


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
