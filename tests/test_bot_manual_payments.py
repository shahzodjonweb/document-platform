"""Card transfers in the bot: choosing, paying, sending the receipt, being told."""
import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.commerce import manual
from apps.commerce.models import ManualPayment, PaymentNotice
from apps.core.identity import resolve_account
from apps.core.models import BotCallback, BotConversation, FileAsset
from telegram.billing import COPY
from telegram.clock import day_label
from telegram.local import dispatch_local
from tests.test_bot_plans_overview import discount, ended_discount
from tests.test_manual_payments import CARD, configure, finance, paid, png

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]


@pytest.fixture
def customer(settings):
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    account = resolve_account({'id': 981001, 'first_name': 'Card payer'}, is_test=True)
    BotConversation.objects.create(telegram_user_id=account.telegram_user_id, locale='en', language_selected_at=timezone.now())
    return account


def token(result, action, **payload):
    for message in reversed(result['messages']):
        for row in message['buttons']:
            for button in row:
                data = button.get('callback_data')
                ref = BotCallback.objects.filter(pk=data, action=action).first() if data else None
                if ref and all(ref.payload.get(k) == v for k, v in payload.items()):
                    return data
    raise AssertionError(f'No button for {action}')


def labels(result):
    return [button['label'] for message in result['messages'] for row in message['buttons'] for button in row]


def test_plans_offer_card_payment_and_say_automatic_is_coming(customer):
    configure()
    result = dispatch_local(customer, text='/plans')
    assert "💳 Plus · 20 000 so'm / 30 days" in labels(result)
    assert "💳 Premium · 60 000 so'm / 30 days" in labels(result)
    assert COPY['en']['automatic_soon'] in result['messages'][-1]['text']


def test_without_a_card_there_is_no_card_payment_to_choose(customer):
    result = dispatch_local(customer, text='/plans')
    assert not any("so'm" in label for label in labels(result))
    assert COPY['en']['card_intro'] not in result['messages'][-1]['text']


def test_choosing_a_plan_shows_the_card_the_price_and_the_code(customer):
    configure()
    result = dispatch_local(customer, callback_data=token(dispatch_local(customer, text='/plans'),
                                                          'commerce_manual_plan', plan='premium'))
    # The payment screen takes the place of the plans screen it was chosen from.
    text = next(m['text'] for m in reversed(result['messages']) if 'so\'m' in m['text'] and 'PM-' in m['text'])
    payment = ManualPayment.objects.get()
    assert ' '.join(CARD[i:i + 4] for i in range(0, 16, 4)) in text
    assert "60 000 so'm" in text and payment.reference in text and 'Shakhzod Uralov' in text
    assert payment.channel == 'bot' and payment.status == 'awaiting'


def test_a_receipt_photo_goes_to_the_payment_not_to_the_pdf_tools(customer):
    configure()
    plans = dispatch_local(customer, text='/plans')
    shown = dispatch_local(customer, callback_data=token(plans, 'commerce_manual_plan', plan='plus'))
    asked = dispatch_local(customer, callback_data=token(shown, 'commerce_manual_receipt'))
    assert COPY['en']['manual_send_receipt'] in asked['messages'][-1]['text']
    assert BotConversation.objects.get(pk=customer.telegram_user_id).state == 'payment_receipt'
    before = FileAsset.objects.count()
    done = dispatch_local(customer, uploaded=SimpleUploadedFile('receipt.jpg', png(), 'image/jpeg'))
    payment = ManualPayment.objects.get()
    assert payment.status == 'submitted' and payment.channel == 'bot' and payment.receipt_key
    assert FileAsset.objects.count() == before, 'a receipt never becomes a document to process'
    assert COPY['en']['manual_received'] in done['messages'][-1]['text']
    assert BotConversation.objects.get(pk=customer.telegram_user_id).state == ''
    assert PaymentNotice.objects.filter(manual=payment, kind='staff_new').exists()


def test_a_file_sent_without_tapping_ive_paid_is_an_ordinary_document(customer):
    configure()
    dispatch_local(customer, callback_data=token(dispatch_local(customer, text='/plans'), 'commerce_manual_plan', plan='plus'))
    from tests.test_manual_payments import pdf
    dispatch_local(customer, uploaded=SimpleUploadedFile('notes.pdf', pdf(), 'application/pdf'))
    assert ManualPayment.objects.get().status == 'awaiting'


def test_cancelling_from_the_bot(customer):
    configure()
    shown = dispatch_local(customer, callback_data=token(dispatch_local(customer, text='/plans'), 'commerce_manual_plan', plan='plus'))
    result = dispatch_local(customer, callback_data=token(shown, 'commerce_manual_cancel'))
    assert ManualPayment.objects.get().status == 'cancelled'
    assert any(COPY['en']['manual_cancelled'] in message['text'] for message in result['messages'])


def test_myid_tells_the_owner_their_telegram_id(customer):
    result = dispatch_local(customer, text='/myid')
    assert str(customer.telegram_user_id) in result['messages'][-1]['text']


# ---------------------------------------------------------------- messages


def run_notices(bot):
    from telegram.payment_notices import drain
    asyncio.run(drain(bot))


def bot_mock():
    return Mock(send_message=AsyncMock(return_value=Mock(message_id=55)))


def test_the_owner_is_alerted_once_with_a_link_to_the_review_page(customer, settings):
    settings.CSRF_TRUSTED_ORIGINS = ['https://pdfmaster-admin.example.live', 'https://pdfmaster.example.live']
    configure()
    payment = manual.attach_receipt(customer, manual.create(customer, 'premium')[0].id, png(), note='card 4421')
    bot = bot_mock()
    run_notices(bot)
    run_notices(bot)
    assert bot.send_message.await_count == 1
    chat, text = bot.send_message.await_args.args
    assert chat == 1234567 and payment.reference in text and "60 000 so'm" in text and 'card 4421' in text
    assert f'https://pdfmaster-admin.example.live/ops/payments/manual/{payment.id}' in text
    assert PaymentNotice.objects.get(kind='staff_new').status == 'delivered'


def test_no_alert_id_means_the_alert_is_skipped_not_retried(customer):
    from operations.integrations import save_config
    configure()
    save_config('manual_payments', {'alert_telegram_id': '', 'enabled': 'true'})
    manual.attach_receipt(customer, manual.create(customer, 'plus')[0].id, png())
    bot = bot_mock()
    run_notices(bot)
    assert not bot.send_message.called and PaymentNotice.objects.get().status == 'skipped'


def test_the_customer_hears_the_decision_in_their_language(customer):
    configure()
    customer.locale = 'ru'
    customer.save(update_fields=['locale'])
    payment = manual.attach_receipt(customer, manual.create(customer, 'plus')[0].id, png())
    PaymentNotice.objects.all().delete()
    manual.reject(payment.id, finance(), 'Перевод не поступил <b>совсем</b>')
    bot = bot_mock()
    run_notices(bot)
    chat, text = bot.send_message.await_args.args
    assert chat == customer.telegram_user_id
    assert 'Перевод не поступил <b>совсем</b>' in text and payment.reference in text
    assert 'parse_mode' not in bot.send_message.await_args.kwargs, "the owner's words are sent as plain text"


def test_an_approval_message_says_until_when(customer):
    configure()
    payment = manual.attach_receipt(customer, manual.create(customer, 'premium')[0].id, png())
    PaymentNotice.objects.all().delete()
    manual.approve(payment.id, finance())
    bot = bot_mock()
    run_notices(bot)
    text = bot.send_message.await_args.args[1]
    ends = timezone.localtime(payment.__class__.objects.get(pk=payment.pk).payment.period.ends_at)
    assert 'Premium' in text and ends.strftime('%d.%m.%Y') in text


def test_a_telegram_failure_is_retried_not_lost(customer):
    configure()
    manual.attach_receipt(customer, manual.create(customer, 'plus')[0].id, png())
    bot = Mock(send_message=AsyncMock(side_effect=RuntimeError('network')))
    run_notices(bot)
    notice = PaymentNotice.objects.get()
    assert notice.status == 'retrying' and notice.attempts == 1 and notice.next_attempt_at > timezone.now()


def test_the_delivery_loop_drains_payment_messages_too(customer):
    from telegram.delivery import drain
    configure()
    manual.attach_receipt(customer, manual.create(customer, 'plus')[0].id, png())
    bot = bot_mock()
    asyncio.run(drain(bot))
    assert PaymentNotice.objects.get().status == 'delivered'


def test_the_default_prices_are_offered_as_soon_as_a_card_is_saved(customer):
    configure(prices=None)
    result = dispatch_local(customer, text='/plans')
    assert "💳 Plus · 20 000 so'm / 30 days" in labels(result)
    assert "💳 Premium · 60 000 so'm / 30 days" in labels(result)


def test_plans_subscription_and_a_card_payment_replace_the_screen_they_were_opened_from(customer):
    from tests.test_bot_no_flood import Chat
    configure()
    chat = Chat(customer)
    assert chat.do(text='/plans') == 1, 'a typed command gets its own message'
    assert chat.tap('subscription') == 0
    assert chat.tap('plans') == 0
    assert chat.tap('commerce_manual_plan', plan='plus') == 0
    assert '20 000' in chat.last()
    assert chat.tap('commerce_manual_cancel') == 0
    assert chat.last() == COPY['en']['manual_cancelled']


def test_a_plan_given_by_the_team_is_named_rather_than_called_free(customer):
    from apps.core.models import Account
    Account.objects.filter(pk=customer.pk).update(staff_plan='premium')
    customer.refresh_from_db()
    text = dispatch_local(customer, text='/subscription')['messages'][-1]['text']
    assert 'Premium' in text and COPY['en']['no_subscription'] not in text


def test_the_subscription_screen_says_until_when_and_has_no_renewal_to_switch(customer):
    """A card transfer covers 30 days and never renews by itself. The screen
    used to offer "Turn renewal on", which the service answered with an error."""
    paid(customer, 'plus')
    result = dispatch_local(customer, text='/subscription')
    text = result['messages'][-1]['text']
    assert text.startswith('<b>Plus</b>') and f"{COPY['en']['active_until']}: " in text
    assert 'renew' not in text.lower() and not any('renew' in label.lower() for label in labels(result))
    assert COPY['en']['plans'] in labels(result)
    assert not BotCallback.objects.filter(account=customer, action__in=('commerce_cancel', 'commerce_resume')).exists()


# ---------------------------------------------------------------- discounts


def payment_screen(customer, plan):
    shown = dispatch_local(customer, callback_data=token(dispatch_local(customer, text='/plans'),
                                                         'commerce_manual_plan', plan=plan))
    return next(m['text'] for m in reversed(shown['messages']) if 'PM-' in m['text'])


def test_a_discounted_plan_is_offered_at_its_price_with_how_much_off(customer):
    configure()
    discount('plus')
    result = dispatch_local(customer, text='/plans')
    # The percentage leads: a narrow phone cuts a long button's tail, and what
    # it must not cut is the discount.
    assert "💳 Plus −25% · 15 000 so'm / 30 days" in labels(result)
    assert "💳 Premium · 60 000 so'm / 30 days" in labels(result)


def test_the_payment_screen_asks_for_the_discounted_amount_and_shows_the_regular_price(customer):
    configure()
    until = discount('plus')
    text = payment_screen(customer, 'plus')
    assert "Plus — 15 000 so'm for 30 days</b>" in text and "Send exactly <b>15 000 so'm</b>" in text
    assert f"<s>20 000 so'm</s> · −25% until {day_label(until, 'en')}" in text
    assert text.splitlines()[1].startswith('Regular price'), 'right under the title'
    assert ManualPayment.objects.get().amount == 15000


def test_a_plan_at_its_regular_price_has_nothing_to_strike_through(customer):
    configure()
    discount('plus')
    text = payment_screen(customer, 'premium')
    assert "Send exactly <b>60 000 so'm</b>" in text and '<s>' not in text and 'Regular price' not in text


@pytest.mark.parametrize('locale,note', [
    ('uz', "Odatdagi narx <s>20 000 so'm</s> · −25% chegirma, {until}gacha"),
    ('ru', 'Обычная цена <s>20 000 сум</s> · −25% до {until}'),
])
def test_the_regular_price_note_is_in_the_customers_language(customer, locale, note):
    configure()
    until = discount('plus')
    customer.locale = locale
    customer.save(update_fields=['locale'])
    BotConversation.objects.filter(pk=customer.telegram_user_id).update(locale=locale)
    text = payment_screen(customer, 'plus')
    assert note.format(until=day_label(until, locale)) in text and '15 000' in text


def test_a_request_opened_during_a_discount_is_asked_at_the_regular_price_after_its_last_day(customer):
    """Nothing sent yet, the discount over: the plans page shows the regular
    price again, and the card screen must not ask for an amount it no longer
    shows, nor strike a price through."""
    configure()
    discount('plus')
    assert "15 000" in payment_screen(customer, 'plus')
    ended_discount('plus')
    text = payment_screen(customer, 'plus')
    assert "Send exactly <b>20 000 so'm</b>" in text and '<s>' not in text and 'Regular price' not in text
    assert ManualPayment.objects.get(status='awaiting').amount == 20000


@pytest.mark.parametrize('locale,label', [('uz', "💳 Plus −25% · 15 000 so'm / 30 kun"), ('ru', '💳 Plus −25% · 15 000 сум / 30 дней')])
def test_the_discount_button_leads_with_the_percentage_in_each_language(customer, locale, label):
    configure()
    discount('plus')
    customer.locale = locale
    customer.save(update_fields=['locale'])
    BotConversation.objects.filter(pk=customer.telegram_user_id).update(locale=locale)
    assert label in labels(dispatch_local(customer, text='/plans'))


def test_uzbek_spells_pullik_one_way():
    """'pullik' (pul + -lik), as the same screen's other line already had it:
    'Pulli tarif' was a slip, and the subscription screen is now these two lines."""
    assert COPY['uz']['active_until'] == 'Pullik tarif muddati' and 'Pullik obunangiz' in COPY['uz']['no_subscription']
    assert 'pulli ' not in ' '.join(COPY['uz'].values()).lower()
