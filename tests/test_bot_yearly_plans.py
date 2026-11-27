"""A year bought in the bot: shown beside the month, paid once on inPAY's page (or by card transfer)."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.commerce import checkout
from apps.commerce.models import Checkout, ManualPayment, SubscriptionPeriod
from apps.commerce.services import effective_plan
from apps.core.identity import resolve_account
from apps.core.models import Account, BotCallback, BotConversation
from telegram.local import dispatch_local
from tests.test_inpay_checkout import FakeInpay, switch_on
from tests.test_manual_payments import configure

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]


@pytest.fixture
def bank(monkeypatch):
    fake = FakeInpay()
    monkeypatch.setattr('apps.commerce.inpay._call', fake)
    return fake


def chat(locale, uid=985001):
    account = resolve_account({'id': uid, 'first_name': 'Yearly', 'language_code': locale}, is_test=True)
    BotConversation.objects.create(telegram_user_id=account.telegram_user_id, locale=locale, language_selected_at=timezone.now())
    Account.objects.filter(pk=account.pk).update(locale=locale)
    account.refresh_from_db()
    return account


@pytest.fixture
def local_bot(settings):
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True


def buttons(result):
    return [button for message in result['messages'] for row in message['buttons'] for button in row]


def token(result, action, **payload):
    for button in reversed(buttons(result)):
        data = button.get('callback_data')
        ref = BotCallback.objects.filter(pk=data, action=action).first() if data else None
        if ref and all(ref.payload.get(k) == v for k, v in payload.items()):
            return data
    raise AssertionError(f'No button for {action} {payload}')


@pytest.mark.parametrize('locale,line,label,title,pay', [
    ('en', "📅 Or yearly: <b>11 000</b> so'm a month, billed 132 000 so'm once a year (−45%)",
     "📅 Plus · 11 000 so'm a month −45%, paid yearly", "<b>⚡ Plus — 132 000 so'm for 1 year</b>", "💳 Pay 132 000 so'm"),
    ('uz', "📅 Yoki yillik: oyiga <b>11 000</b> so'm, yiliga bir yo‘la 132 000 so'm to‘lanadi (−45%)",
     "📅 Plus · oyiga 11 000 so'm −45%, yillik to‘lanadi", "<b>⚡ Plus — 1 yil uchun 132 000 so'm</b>", "💳 132 000 so'm to‘lash"),
    ('ru', '📅 Или на год: <b>11 000</b> сум в месяц, оплата 132 000 сум сразу за год (−45%)',
     '📅 Plus · 11 000 сум в месяц −45%, оплата за год', '<b>⚡ Plus — 132 000 сум за 1 год</b>', '💳 Оплатить 132 000 сум'),
], ids=['en', 'uz', 'ru'])
def test_the_year_is_shown_beside_the_month_and_paid_once_on_inpay(local_bot, bank, locale, line, label, title, pay):
    switch_on(kassa='bot')
    customer = chat(locale)
    plans = dispatch_local(customer, text='/plans')
    text = plans['messages'][-1]['text']
    assert line in text and '<b>33 000</b>' in text, 'Premium has its year too'
    labels = [button['label'] for button in buttons(plans)]
    assert label in labels and labels.index(label) == labels.index(next(l for l in labels if l.startswith('💳 Plus'))) + 1
    shown = dispatch_local(customer, callback_data=token(plans, 'commerce_checkout_plan', plan='plus', term='year'))
    row = Checkout.objects.get()
    assert (row.channel, row.term, row.amount) == ('bot', 'year', 132_000)
    assert bank.payments[row.provider_id]['amount'] == 132_000
    assert any(title in message['text'] for message in shown['messages'])
    link = next(button for button in buttons(shown) if button.get('url'))
    assert link['label'] == pay and link['url'] == f'https://inpay.uz/checkout/{row.provider_id}'

    bank.pay(row.provider_id)
    checkout.refresh(row, force=True)
    customer.refresh_from_db()
    period = SubscriptionPeriod.objects.get()
    assert effective_plan(customer) == 'plus' and period.ends_at - period.starts_at == timedelta(days=365)


def test_with_saved_cards_on_the_year_still_goes_straight_to_its_page(local_bot, bank, monkeypatch):
    """Saved cards renew monthly; a year is paid once, so it skips the «once or every month» choice."""
    switch_on(kassa='bot')
    monkeypatch.setattr('apps.commerce.autopay.offered', lambda account, channel='bot': True)
    customer = chat('en')
    plans = dispatch_local(customer, text='/plans')
    assert token(plans, 'commerce_plan_choice', plan='plus')
    assert token(plans, 'commerce_checkout_plan', plan='premium', term='year')


def test_by_card_transfer_the_year_asks_for_its_own_amount(local_bot):
    configure()
    customer = chat('uz')
    plans = dispatch_local(customer, text='/plans')
    shown = dispatch_local(customer, callback_data=token(plans, 'commerce_manual_plan', plan='premium', term='year'))
    payment = ManualPayment.objects.get()
    assert (payment.term, payment.amount, payment.channel) == ('year', 396_000, 'bot')
    text = next(message['text'] for message in shown['messages'] if payment.reference in message['text'])
    assert "<b>💳 Premium — 1 yil uchun 396 000 so'm</b>" in text and "aynan <b>396 000 so'm</b>" in text
