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
from telegram.local import dispatch_local
from tests.test_manual_payments import CARD, configure, finance, png

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
    assert "💳 Plus · 49 000 so'm / 30 days" in labels(result)
    assert "💳 Premium · 99 000 so'm / 30 days" in labels(result)
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
    assert "99 000 so'm" in text and payment.reference in text and 'Shakhzod Uralov' in text
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
    assert chat == 1234567 and payment.reference in text and "99 000 so'm" in text and 'card 4421' in text
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
    assert "💳 Plus · 60 000 so'm / 30 days" in labels(result)
    assert "💳 Premium · 100 000 so'm / 30 days" in labels(result)


def test_plans_subscription_and_a_card_payment_replace_the_screen_they_were_opened_from(customer):
    from tests.test_bot_no_flood import Chat
    configure()
    chat = Chat(customer)
    assert chat.do(text='/plans') == 1, 'a typed command gets its own message'
    assert chat.tap('subscription') == 0
    assert chat.tap('plans') == 0
    assert chat.tap('commerce_manual_plan', plan='plus') == 0
    assert '49 000' in chat.last()
    assert chat.tap('commerce_manual_cancel') == 0
    assert chat.last() == COPY['en']['manual_cancelled']


def test_a_plan_given_by_the_team_is_named_rather_than_called_free(customer):
    from apps.core.models import Account
    Account.objects.filter(pk=customer.pk).update(staff_plan='premium')
    customer.refresh_from_db()
    text = dispatch_local(customer, text='/subscription')['messages'][-1]['text']
    assert 'Premium' in text and COPY['en']['no_subscription'] not in text
