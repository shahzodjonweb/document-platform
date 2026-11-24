"""Saved cards and monthly renewal in the bot: the choice, saving a card, paying in a tap, the switches, the messages."""
import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from django.utils import timezone

from apps.commerce import autopay
from apps.commerce.models import AutoRenewal, CardCharge, PaymentNotice, SavedCard
from apps.commerce.services import effective_plan
from apps.core.identity import resolve_account
from apps.core.models import BotCallback, BotConversation
from telegram.billing import CARD_COPY, COPY
from telegram.local import dispatch_local
from tests.test_autopay import FakeAvto, autopay_on

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]


@pytest.fixture
def bank(monkeypatch):
    fake = FakeAvto()
    monkeypatch.setattr('apps.commerce.inpay._call', fake)
    return fake


def chat(uid=983001, locale='en'):
    account = resolve_account({'id': uid, 'first_name': 'Card payer', 'language_code': locale}, is_test=True)
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


def has(result, action):
    try:
        token(result, action)
        return True
    except AssertionError:
        return False


def buttons(result):
    return [button for message in result['messages'] for row in message['buttons'] for button in row]


def texts(result):
    return [message['text'] for message in result['messages']]


def run_notices():
    from telegram.payment_notices import drain
    bot = Mock(send_message=AsyncMock(return_value=Mock(message_id=77)))
    asyncio.run(drain(bot))
    return bot


def save_on_inpay(bank):
    card = SavedCard.objects.latest('created_at')
    bank.save(card.provider_card_id)
    return card


def test_a_plan_offers_once_or_every_month_and_saving_a_card_pays_and_renews(customer, bank):
    autopay_on()
    plans = dispatch_local(customer, text='/plans')
    choice = dispatch_local(customer, callback_data=token(plans, 'commerce_plan_choice', plan='plus'))
    assert any('Renew every month' in text for text in texts(choice))
    labels = [button['label'] for button in buttons(choice)]
    assert '🔁 Pay and renew every month' in labels and "💳 Pay once — 20 000 so'm" in labels
    bind = dispatch_local(customer, callback_data=token(choice, 'commerce_card_bind', plan='plus'))
    save = next(button for button in buttons(bind) if button.get('url'))
    card = SavedCard.objects.get()
    assert save['label'] == CARD_COPY['en']['save_card'] and save['url'] == card.bind_url
    assert any('first month right away' in text for text in texts(bind))
    # «I've saved it» before saving: still waiting, and the page stays offered.
    waiting = dispatch_local(customer, callback_data=token(bind, 'commerce_card_check', card_id=str(card.id)))
    assert CARD_COPY['en']['bind_waiting'] in texts(waiting) and not bank.charged()
    save_on_inpay(bank)
    # inPAY's return link brings the customer back with /start card_<id>.
    back = dispatch_local(customer, text=f'/start card_{card.id.hex}')
    told = ' '.join(texts(back))
    assert '✅ Payment received! Plus is active until' in told and "renews by itself" in told and '•••• 1234' in told
    assert effective_plan(customer) == 'plus' and AutoRenewal.objects.get(account=customer).status == 'on'
    # Said in the chat: the queued notice is not sent again.
    assert PaymentNotice.objects.get(charge=CardCharge.objects.get()).status == 'skipped'
    assert run_notices().send_message.await_count == 0
    # Coming back again charges nothing more.
    dispatch_local(customer, text=f'/start card_{card.id.hex}')
    assert bank.charged() == 1


def test_a_saved_card_pays_in_two_taps_and_a_double_tap_charges_once(customer, bank):
    autopay_on()
    card, request = autopay.begin_binding(customer, '')
    autopay.complete_binding(card, *autopay.ask_binding(request))
    save_on_inpay(bank)
    autopay.apply_cards(card.pk, autopay.ask_cards(autopay.look_cards(card))[0])
    choice = dispatch_local(customer, callback_data=token(dispatch_local(customer, text='/plans'), 'commerce_plan_choice', plan='premium'))
    labels = [button['label'] for button in buttons(choice)]
    assert "💳 Pay 60 000 so'm with •••• 1234" in labels and '🔁 Pay with •••• 1234 and renew monthly' in labels
    confirm = dispatch_local(customer, callback_data=token(choice, 'commerce_card_confirm', plan='premium', renew=False))
    assert any("<b>60 000 so'm</b> from card •••• 1234" in text for text in texts(confirm))
    assert not bank.charged(), 'nothing is charged before the confirm tap'
    pay = token(confirm, 'commerce_card_pay', plan='premium')
    paid = dispatch_local(customer, callback_data=pay)
    assert any(text.startswith('✅ Payment received! Premium is active until') for text in texts(paid))
    dispatch_local(customer, callback_data=pay)
    assert bank.charged() == 1 and effective_plan(customer) == 'premium'
    assert not AutoRenewal.objects.exists(), 'paid once: nothing renews'


def test_the_subscription_shows_renewal_and_turns_it_off_and_removes_the_card(customer, bank):
    autopay_on()
    card, request = autopay.begin_binding(customer, 'plus')
    autopay.complete_binding(card, *autopay.ask_binding(request))
    save_on_inpay(bank)
    autopay.finish_saved(autopay.apply_cards(card.pk, autopay.ask_cards(autopay.look_cards(card))[0]))
    shown = dispatch_local(customer, text='/subscription')
    told = ' '.join(texts(shown))
    assert "Auto-renewal: on. Next charge" in told and "20 000 so'm from card •••• 1234" in told
    # The remove-card button inPAY requires is always there with a saved card.
    assert has(shown, 'commerce_card_remove') and has(shown, 'commerce_renew_off')
    off = dispatch_local(customer, callback_data=token(shown, 'commerce_renew_off'))
    assert any(text.startswith('Auto-renewal is off.') for text in texts(off))
    assert AutoRenewal.objects.get().status == 'off' and has(off, 'commerce_renew_on')
    on = dispatch_local(customer, callback_data=token(off, 'commerce_renew_on'))
    assert AutoRenewal.objects.get().status == 'on' and any('Auto-renewal is on' in text for text in texts(on))
    confirm = dispatch_local(customer, callback_data=token(on, 'commerce_card_remove'))
    assert any(text.startswith('Remove card •••• 1234?') for text in texts(confirm))
    removed = dispatch_local(customer, callback_data=token(confirm, 'commerce_card_remove_yes'))
    assert CARD_COPY['en']['card_removed'] in texts(removed)
    card.refresh_from_db()
    assert card.status == 'removed' and bank.cards[card.provider_card_id]['status'] == 'removed'
    assert AutoRenewal.objects.get().status == 'stopped'
    # The simulator answers with the whole chat: only the newest screen counts.
    after = dispatch_local(customer, text='/subscription')
    assert not has({'messages': after['messages'][-1:]}, 'commerce_card_remove')


def test_the_customer_is_told_before_after_and_when_a_renewal_fails(customer, bank):
    autopay_on()
    card, request = autopay.begin_binding(customer, 'plus')
    autopay.complete_binding(card, *autopay.ask_binding(request))
    save_on_inpay(bank)
    autopay.finish_saved(autopay.apply_cards(card.pk, autopay.ask_cards(autopay.look_cards(card))[0]))
    PaymentNotice.objects.update(status='delivered')
    renewal = AutoRenewal.objects.get()
    autopay.housekeeping(renewal.renews_at - timedelta(days=2))
    bot = run_notices()
    target, text = bot.send_message.await_args.args
    assert target == customer.telegram_user_id and text.startswith('🔁 Your Plus renews on ')
    assert "20 000 so'm will be charged from card •••• 1234" in text
    assert bot.send_message.await_args.kwargs['reply_markup'] is not None
    bank.decline = 'CHARGE_FAILED'
    autopay.housekeeping(renewal.renews_at - timedelta(hours=3))
    _, failed = run_notices().send_message.await_args.args
    assert failed.startswith("⚠️ We couldn't charge 20 000 so'm from card •••• 1234 to renew Plus")
    assert 'not enough money' in failed and 'try again on' in failed
    bank.decline = None
    autopay.housekeeping(renewal.renews_at + timedelta(days=1, minutes=1))
    _, renewed = run_notices().send_message.await_args.args
    assert renewed.startswith('🔁 Plus renewed until ')


def test_without_avto_pay_a_plan_still_leads_straight_to_inpays_page(customer, bank):
    from tests.test_inpay_checkout import switch_on
    switch_on(kassa='bot')
    plans = dispatch_local(customer, text='/plans')
    assert has(plans, 'commerce_checkout_plan') and not has(plans, 'commerce_plan_choice')
    assert not has(dispatch_local(customer, text='/subscription'), 'commerce_card_remove')


@pytest.mark.parametrize('locale', ['uz', 'ru'])
def test_the_card_screens_speak_the_customers_language(settings, bank, locale):
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    autopay_on()
    account = chat(983010, locale)
    choice = dispatch_local(account, callback_data=token(dispatch_local(account, text='/plans'), 'commerce_plan_choice', plan='plus'))
    assert CARD_COPY[locale]['pay_renew'] in [button['label'] for button in buttons(choice)]
    bind = dispatch_local(account, callback_data=token(choice, 'commerce_card_bind', plan='plus'))
    assert CARD_COPY[locale]['save_card'] in [button['label'] for button in buttons(bind)]
    card = save_on_inpay(bank)
    back = dispatch_local(account, text=f'/start card_{card.id.hex}')
    assert any(text.startswith(CARD_COPY[locale]['card_paid'].split('{')[0]) for text in texts(back))
    assert COPY[locale]['plans'] in [button['label'] for button in buttons(back)]
