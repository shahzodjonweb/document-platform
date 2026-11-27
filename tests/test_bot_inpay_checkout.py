"""Paying online in the bot: choosing how, the button to inPAY's page, checking, being told."""
import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from django.utils import timezone

from apps.commerce import checkout
from apps.commerce.models import Checkout, ManualPayment, PaymentNotice, SubscriptionPeriod
from apps.commerce.services import effective_plan
from apps.core.identity import resolve_account
from apps.core.models import BotCallback, BotConversation
from telegram.billing import COPY, PLAN_COPY
from telegram.local import dispatch_local
from tests.test_inpay_checkout import BOT_TEST, OWNER, FakeInpay, switch_on

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]


@pytest.fixture
def bank(monkeypatch):
    fake = FakeInpay()
    monkeypatch.setattr('apps.commerce.inpay._call', fake)
    return fake


def chat(uid=982001, locale='en'):
    account = resolve_account({'id': uid, 'first_name': 'Online payer', 'language_code': locale}, is_test=True)
    BotConversation.objects.create(telegram_user_id=account.telegram_user_id, locale=locale, language_selected_at=timezone.now())
    return account


@pytest.fixture
def customer(settings):
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    return chat()


def token(result, action, **payload):
    for message in reversed(result['messages']):
        for row in message['buttons']:
            for button in row:
                data = button.get('callback_data')
                ref = BotCallback.objects.filter(pk=data, action=action).first() if data else None
                if ref and all(ref.payload.get(k) == v for k, v in payload.items()):
                    return data
    raise AssertionError(f'No button for {action}')


def buttons(result):
    return [button for message in result['messages'] for row in message['buttons'] for button in row]


def texts(result):
    return [message['text'] for message in result['messages']]


def bot_mock():
    return Mock(send_message=AsyncMock(return_value=Mock(message_id=55)))


def run_notices(bot):
    from telegram.payment_notices import drain
    asyncio.run(drain(bot))


def test_with_only_inpay_a_plan_leads_straight_to_its_payment_page(customer, bank):
    switch_on(kassa='bot')
    plans = dispatch_local(customer, text='/plans')
    assert "💳 Plus · 20 000 so'm a month" in [button['label'] for button in buttons(plans)]
    last = plans['messages'][-1]['text']
    assert 'inPAY' in last and COPY['en']['automatic_soon'] not in last and 'receipt' not in last
    shown = dispatch_local(customer, callback_data=token(plans, 'commerce_checkout_plan', plan='plus'))
    row = Checkout.objects.get()
    assert (row.channel, row.status, row.amount) == ('bot', 'pending', 20_000)
    pay = next(button for button in buttons(shown) if button['url'])
    assert pay['label'] == "💳 Pay 20 000 so'm" and pay['url'] == f'https://inpay.uz/checkout/{row.provider_id}'
    assert any('Nothing renews by itself' in text for text in texts(shown))
    assert token(shown, 'commerce_checkout_check', checkout_id=str(row.id))
    # Nothing is asked of the customer here but to pay: no receipt prompt, no card request.
    assert not ManualPayment.objects.exists()
    assert BotConversation.objects.get(pk=customer.telegram_user_id).state == ''


def test_with_both_set_up_inpay_is_the_way_and_card_transfer_is_not_offered(customer, bank):
    switch_on(kassa='bot', card=True)
    plans = dispatch_local(customer, text='/plans')
    last = plans['messages'][-1]['text']
    assert PLAN_COPY['en']['how_auto'].split('\n')[2] in last
    assert PLAN_COPY['en']['how'].split('\n')[2] not in last and COPY['en']['automatic_soon'] not in last
    assert not BotCallback.objects.filter(account=customer, action='commerce_manual_plan').exists()
    shown = dispatch_local(customer, callback_data=token(plans, 'commerce_checkout_plan', plan='premium'))
    assert Checkout.objects.get().amount == 60_000
    assert any(button['url'] and button['url'].startswith('https://inpay.uz/checkout/') for button in buttons(shown))
    assert not ManualPayment.objects.exists()


def test_a_card_transfer_button_from_before_inpay_leads_to_inpay(customer, bank):
    from tests.test_manual_payments import configure as configure_card
    configure_card()
    before = dispatch_local(customer, text='/plans')
    old = token(before, 'commerce_manual_plan', plan='plus')
    switch_on(kassa='bot', card=True)
    shown = dispatch_local(customer, callback_data=old)
    assert any(button['url'] and button['url'].startswith('https://inpay.uz/checkout/') for button in buttons(shown))
    assert Checkout.objects.get().plan == 'plus' and not ManualPayment.objects.exists()


def test_a_card_transfer_begun_before_inpay_is_finished_in_the_chat(customer, bank):
    from tests.test_manual_payments import configure as configure_card
    configure_card()
    before = dispatch_local(customer, text='/plans')
    old = token(before, 'commerce_manual_plan', plan='plus')
    begun = dispatch_local(customer, callback_data=old)
    reference = ManualPayment.objects.get().reference
    assert any(reference in text for text in texts(begun))
    switch_on(kassa='bot', card=True)
    again = dispatch_local(customer, callback_data=old)
    assert any(reference in text for text in texts(again)) and not Checkout.objects.exists()
    assert token(again, 'commerce_manual_receipt', payment_id=str(ManualPayment.objects.get().id))


def test_when_inpay_cannot_open_the_payment_the_customer_pays_by_card_transfer(customer, bank):
    switch_on(kassa='bot', card=True)
    plans = dispatch_local(customer, text='/plans')
    bank.down = True
    failed = dispatch_local(customer, callback_data=token(plans, 'commerce_checkout_plan', plan='plus'))
    bank.down = False
    assert Checkout.objects.get().status == 'failed'
    said = texts(failed)
    assert COPY['en']['checkout_fallback'] in said
    reference = ManualPayment.objects.get().reference
    # The card screen comes after the words that explain it.
    assert said.index(COPY['en']['checkout_fallback']) < next(i for i, text in enumerate(said) if reference in text)
    # The plans screen offers card transfer meanwhile, with no "coming soon" for what is already set up.
    meanwhile = dispatch_local(customer, text='/plans')
    last = meanwhile['messages'][-1]['text']
    assert PLAN_COPY['en']['how'].split('\n')[2] in last and COPY['en']['automatic_soon'] not in last
    assert token(meanwhile, 'commerce_manual_plan', plan='plus')
    # The inPAY button shown before the failure leads to card transfer too, not to an error.
    tapped = dispatch_local(customer, callback_data=token(plans, 'commerce_checkout_plan', plan='plus'))
    assert any(reference in text for text in texts(tapped)) and Checkout.objects.count() == 1
    # Ten minutes on, inPAY is the way again.
    Checkout.objects.update(created_at=timezone.now() - timedelta(minutes=checkout.FALLBACK_MINUTES, seconds=5))
    later = dispatch_local(customer, text='/plans')
    assert token(later, 'commerce_checkout_plan', plan='premium')


def test_checking_says_it_is_still_waiting_then_that_it_is_paid_once(customer, bank):
    switch_on(kassa='bot')
    shown = dispatch_local(customer, callback_data=token(dispatch_local(customer, text='/plans'), 'commerce_checkout_plan', plan='plus'))
    row = Checkout.objects.get()
    check = token(shown, 'commerce_checkout_check', checkout_id=str(row.id))
    waiting = dispatch_local(customer, callback_data=check)
    assert COPY['en']['checkout_waiting'] in texts(waiting)
    assert effective_plan(customer) == 'free'

    bank.pay(row.provider_id)
    Checkout.objects.filter(pk=row.pk).update(checked_at=None)
    told = dispatch_local(customer, callback_data=check)
    end = SubscriptionPeriod.objects.get().ends_at
    assert any(text.startswith('✅ Payment received! Plus is active until ') and end.strftime('%Y') in text for text in texts(told))
    assert effective_plan(customer) == 'plus'
    # Said in the chat already: the queued notice does not say it again.
    notice = PaymentNotice.objects.get(checkout=row, kind='paid')
    assert (notice.status, notice.error_code) == ('skipped', 'shown_in_chat')
    bot = bot_mock()
    run_notices(bot)
    assert bot.send_message.await_count == 0


def test_coming_back_from_inpays_page_says_the_plan_is_on(customer, bank):
    """inPAY's return link opens the chat with /start pay_<id>: the payment is looked up at once."""
    switch_on(kassa='bot')
    dispatch_local(customer, callback_data=token(dispatch_local(customer, text='/plans'), 'commerce_checkout_plan', plan='plus'))
    row = Checkout.objects.get()
    assert bank.payments[row.provider_id]['return_url'].endswith(f'?start=pay_{row.id.hex}')
    bank.pay(row.provider_id)
    Checkout.objects.filter(pk=row.pk).update(checked_at=None)
    back = dispatch_local(customer, text=f'/start pay_{row.id.hex}')
    assert any(text.startswith('✅ Payment received! Plus is active until ') for text in texts(back))
    assert effective_plan(customer) == 'plus'
    assert PaymentNotice.objects.get(checkout=row, kind='paid').status == 'skipped', 'said in the chat already'


def test_coming_back_before_the_money_arrives_shows_the_payment_again(customer, bank):
    switch_on(kassa='bot')
    dispatch_local(customer, callback_data=token(dispatch_local(customer, text='/plans'), 'commerce_checkout_plan', plan='plus'))
    row = Checkout.objects.get()
    Checkout.objects.filter(pk=row.pk).update(checked_at=None)
    back = dispatch_local(customer, text=f'/start pay_{row.id.hex}')
    assert COPY['en']['checkout_waiting'] in texts(back)
    assert any(button['url'] == row.checkout_url for button in buttons(back))
    assert token(back, 'commerce_checkout_check', checkout_id=str(row.id))
    assert effective_plan(customer) == 'free'


def test_a_return_link_that_is_not_the_customers_payment_leads_to_the_plans(customer, bank):
    switch_on(kassa='bot')
    other = chat(982003)
    row, _ = checkout.create(other, 'plus', 'bot')
    for link in (f'/start pay_{row.id.hex}', '/start pay_not-a-payment'):
        back = dispatch_local(customer, text=link)
        assert "💳 Plus · 20 000 so'm a month" in [button['label'] for button in buttons(back)]
    assert not bank.count('GET', '/api/v2/payments/'), 'someone else’s payment is not looked up'


def test_a_payment_learned_of_by_webhook_is_announced_in_the_chat_once(customer, bank, settings):
    switch_on(kassa='bot')
    row, _ = checkout.create(customer, 'premium', 'bot')
    bank.pay(row.provider_id)
    checkout.refresh(row, force=True)
    bot = bot_mock()
    run_notices(bot)
    run_notices(bot)
    assert bot.send_message.await_count == 1
    target, text = bot.send_message.await_args.args
    assert target == customer.telegram_user_id and text.startswith('✅ Payment received! Premium is active until ')
    assert PaymentNotice.objects.get(checkout=row).status == 'delivered'


def test_someone_who_paid_on_the_website_and_never_met_the_bot_is_not_messaged(bank, customer):
    from apps.core.models import Account
    switch_on()
    web_only = Account.objects.create(display_name='Web only', locale='en', is_test=True)
    row, _ = checkout.create(web_only, 'plus', 'web')
    bank.pay(row.provider_id)
    checkout.refresh(row, force=True)
    bot = bot_mock()
    run_notices(bot)
    assert bot.send_message.await_count == 0
    notice = PaymentNotice.objects.get(checkout=row)
    assert (notice.status, notice.error_code) == ('skipped', 'telegram_link_required')


def test_the_reminder_before_an_inpay_plan_ends_leads_back_to_the_plans(customer, bank):
    switch_on(kassa='bot')
    row, _ = checkout.create(customer, 'plus', 'bot')
    bank.pay(row.provider_id)
    checkout.refresh(row, force=True)
    PaymentNotice.objects.filter(kind='paid').update(status='delivered')
    checkout.housekeeping(SubscriptionPeriod.objects.get().ends_at - timedelta(days=2))
    bot = bot_mock()
    run_notices(bot)
    assert bot.send_message.await_count == 1
    _, text = bot.send_message.await_args.args
    assert text.startswith('⏰ Your Plus plan ends on ') and '/plans' in text
    assert bot.send_message.await_args.kwargs['reply_markup'] is not None


def test_a_test_key_shows_online_payment_to_the_owner_alone(settings, bank):
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    switch_on(kassa='bot', key=BOT_TEST, signing='')
    stranger, owner = chat(982002), chat(OWNER)
    assert not any("so'm" in button['label'] for button in buttons(dispatch_local(stranger, text='/plans')))
    plans = dispatch_local(owner, text='/plans')
    shown = dispatch_local(owner, callback_data=token(plans, 'commerce_checkout_plan', plan='plus'))
    assert any(COPY['en']['checkout_test_note'].strip() in text for text in texts(shown))
    row = Checkout.objects.get()
    bank.pay(row.provider_id)
    Checkout.objects.filter(pk=row.pk).update(checked_at=None)
    told = dispatch_local(owner, callback_data=token(shown, 'commerce_checkout_check', checkout_id=str(row.id)))
    assert COPY['en']['checkout_paid_test'] in texts(told)
    assert effective_plan(owner) == 'free'


def test_inpay_not_answering_leaves_the_customer_with_a_way_on(customer, bank):
    switch_on(kassa='bot')
    plans = dispatch_local(customer, text='/plans')
    bank.down = True
    before = len(plans['messages'])
    failed = dispatch_local(customer, callback_data=token(plans, 'commerce_checkout_plan', plan='plus'))
    assert Checkout.objects.get().status == 'failed'
    assert len(failed['messages']) > before and not any(button['url'] for button in buttons(failed) if button['url'] and 'inpay.uz' in button['url'])
    bank.down = False
    again = dispatch_local(customer, callback_data=token(plans, 'commerce_checkout_plan', plan='plus'))
    assert any(button['url'] and 'inpay.uz/checkout/' in button['url'] for button in buttons(again))


@pytest.mark.parametrize('locale', ['uz', 'ru'])
def test_the_screens_speak_the_customers_language(settings, bank, locale):
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    switch_on(kassa='bot', card=True)
    account = chat(982010, locale)
    plans = dispatch_local(account, text='/plans')
    assert PLAN_COPY[locale]['how_auto'].split('\n')[2] in plans['messages'][-1]['text']
    shown = dispatch_local(account, callback_data=token(plans, 'commerce_checkout_plan', plan='plus'))
    pay = next(button for button in buttons(shown) if button['url'])
    assert pay['label'] == COPY[locale]['checkout_pay'].format(price='20 000')
    # inPAY shows the customer what they are paying for in their own language.
    assert bank.payments[Checkout.objects.get().provider_id]['description'] in ('DocMaster Plus — 30 kun', 'DocMaster Plus — 30 дней')
    bank.down = True
    failed = dispatch_local(account, callback_data=token(plans, 'commerce_checkout_plan', plan='premium'))
    assert COPY[locale]['checkout_fallback'] in texts(failed)


def test_checking_a_failed_payment_soon_after_does_not_say_nothing_was_charged(customer, bank):
    """The customer may have paid on the same page since we last asked: "not received yet", not "failed"."""
    switch_on(kassa='bot')
    shown = dispatch_local(customer, callback_data=token(dispatch_local(customer, text='/plans'), 'commerce_checkout_plan', plan='plus'))
    row = Checkout.objects.get()
    bank.payments[row.provider_id]['status'] = 'failed'
    checkout.refresh(row, force=True)
    told = dispatch_local(customer, callback_data=token(shown, 'commerce_checkout_check', checkout_id=str(row.id)))
    assert COPY['en']['checkout_waiting'] in texts(told) and COPY['en']['checkout_failed'] not in texts(told)
    Checkout.objects.filter(pk=row.pk).update(checked_at=None)
    told = dispatch_local(customer, callback_data=token(shown, 'commerce_checkout_check', checkout_id=str(row.id)))
    assert COPY['en']['checkout_failed'] in texts(told)
