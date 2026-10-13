"""Card transfers the owner reviews: what a customer gets, and when."""
import io
from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from PIL import Image

from apps.commerce import manual
from apps.commerce.models import ManualPayment, Payment, PaymentGrant, PaymentNotice, SubscriptionPeriod
from apps.core.errors import DomainError
from apps.core.identity import resolve_account
from apps.core.models import UsageGrant
from apps.core.policy import limits_for_plan, usage_snapshot
from operations import plans as plan_settings
from operations.integrations import manual_payment_config, save_config

pytestmark = pytest.mark.django_db
PRICES = {'plus': 20_000, 'premium': 60_000}  # the owner's prices, a month


def card(prefix='860012345678901'):
    """A 16-digit card number with a correct checksum digit."""
    for digit in '0123456789':
        from operations.integrations import _luhn
        if _luhn(prefix + digit):
            return prefix + digit


CARD = card()


def configure(enabled=True, prices=PRICES):
    save_config('manual_payments', {'card_number': CARD, 'card_holder': 'Shakhzod Uralov', 'card_label': 'Uzcard',
                                    'alert_telegram_id': '1234567', 'enabled': 'true' if enabled else 'false'})
    for plan, price in (prices or {}).items():
        plan_settings.save(plan, {'price_uzs': price})


def customer(uid=7001):
    return resolve_account({'id': uid, 'first_name': 'Payer', 'language_code': 'en'}, is_test=True)


def finance(role='Finance', name='finance'):
    user = get_user_model().objects.create_user(username=name, password='long-staff-password', is_staff=True)
    user.groups.add(Group.objects.get_or_create(name=role)[0])
    return user


def png(with_exif=True):
    buffer = io.BytesIO()
    picture = Image.new('RGB', (900, 1600), (240, 240, 240))
    exif = Image.Exif()
    exif[0x8825] = {2: (41.0, 18.0, 0.0)}  # GPS
    exif[0x010F] = 'PhoneMaker'
    picture.save(buffer, 'JPEG', exif=exif.tobytes() if with_exif else b'')
    return buffer.getvalue()


def pdf(pages=1, encrypted=False):
    from pypdf import PdfWriter
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=300)
    if encrypted:
        writer.encrypt('secret')
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def submitted(account, plan='premium', raw=None):
    payment, _ = manual.create(account, plan)
    return manual.attach_receipt(account, payment.id, raw or png(), note='Card 4421, 14:05')


# ---------------------------------------------------------------- offered


def test_nothing_is_offered_until_a_card_and_a_price_are_set():
    config = manual_payment_config()
    assert config['enabled'] is True, 'switched on from the start, as the owner asked'
    assert config['ready'] is False and manual.options()['enabled'] is False
    configure(prices=None)
    for plan in ('plus', 'premium'):
        plan_settings.save(plan, {'price_uzs': ''})  # Plus and Premium are priced by default
    assert manual.options()['enabled'] is False, 'a card without a price sells nothing'
    plan_settings.save('premium', {'price_uzs': 65_000})
    offered = manual.options()
    assert offered['enabled'] and offered['plans'] == [{'plan': 'premium', 'price': 65_000}]
    assert offered['automatic'] == {'available': False}
    with pytest.raises(DomainError, match='checkout_disabled'):
        manual.create(customer(), 'plus')


def test_switching_off_hides_it_again():
    configure()
    configure(enabled=False)
    assert manual.options()['enabled'] is False


WRONG_DIGIT = CARD[:-1] + str((int(CARD[-1]) + 1) % 10)


@pytest.mark.parametrize('number', [WRONG_DIGIT, '1234', CARD + '3', 'abcd efgh ijkl mnop'])
def test_a_card_number_with_a_wrong_digit_is_refused(number):
    with pytest.raises(DomainError, match='invalid_card_number'):
        save_config('manual_payments', {'card_number': number, 'card_holder': 'A B'})


def test_card_payments_cannot_be_switched_on_without_a_card():
    with pytest.raises(DomainError, match='manual_payments_not_configured'):
        save_config('manual_payments', {'enabled': 'true'})


def test_spaces_in_a_card_number_are_fine_and_the_free_plan_has_no_price():
    save_config('manual_payments', {'card_number': ' '.join(CARD[i:i + 4] for i in range(0, 16, 4)),
                                    'card_holder': 'A B', 'enabled': 'true'})
    assert manual_payment_config()['card_number'] == CARD
    with pytest.raises(plan_settings.PlanError):
        plan_settings.save('free', {'price_uzs': 10_000})


# ---------------------------------------------------------------- the request


def test_a_request_shows_the_card_and_the_price_and_is_reused():
    configure()
    account = customer()
    payment, created = manual.create(account, 'premium')
    assert created and payment.amount == 60_000 and payment.currency == 'UZS' and payment.status == 'awaiting'
    assert payment.reference.startswith('PM-') and len(payment.reference) == 8
    assert payment.card == {'number': CARD, 'holder': 'Shakhzod Uralov', 'label': 'Uzcard'}
    again, created = manual.create(account, 'premium')
    assert again.pk == payment.pk and not created


def test_choosing_another_plan_replaces_an_unpaid_request_but_not_one_sent_for_review():
    configure()
    account = customer()
    first, _ = manual.create(account, 'plus')
    second, _ = manual.create(account, 'premium')
    first.refresh_from_db()
    assert first.status == 'cancelled' and second.plan == 'premium'
    manual.attach_receipt(account, second.id, png())
    with pytest.raises(DomainError, match='manual_payment_pending'):
        manual.create(account, 'plus')


def test_an_expired_request_does_not_block_a_new_one():
    configure()
    account = customer()
    old, _ = manual.create(account, 'plus')
    ManualPayment.objects.filter(pk=old.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    fresh, created = manual.create(account, 'plus')
    assert created and fresh.pk != old.pk
    with pytest.raises(DomainError, match='manual_payment_closed'):
        manual.attach_receipt(account, old.id, png())


def opened_at(account, plan, old_price, today):
    """A request opened while the plan cost `old_price`; the price is `today` now (a deploy, or the panel)."""
    plan_settings.save(plan, {'price_uzs': old_price})
    payment, _ = manual.create(account, plan)
    plan_settings.save(plan, {'price_uzs': today})
    assert payment.amount == old_price and manual.prices()[plan] == today
    return payment


def test_an_unpaid_request_at_an_old_price_is_opened_again_at_todays_price():
    """The plans page says 20 000; the card screen must not ask for the 60 000 of before."""
    configure()
    account = customer()
    old = opened_at(account, 'plus', 60_000, 20_000)
    fresh, created = manual.create(account, 'plus')
    old.refresh_from_db()
    assert created and fresh.pk != old.pk and fresh.amount == 20_000 and old.status == 'cancelled'
    again, created = manual.create(account, 'plus')
    assert again.pk == fresh.pk and not created, 'a request at today\'s price is still reused'


def test_a_receipt_already_sent_at_an_old_price_waits_for_the_owner():
    configure()
    account = customer()
    old = opened_at(account, 'plus', 60_000, 20_000)
    manual.attach_receipt(account, old.id, png())
    kept, created = manual.create(account, 'plus')
    assert kept.pk == old.pk and not created and kept.amount == 60_000 and kept.status == 'submitted'


# ---------------------------------------------------------------- the receipt


def test_a_photo_receipt_is_kept_without_its_metadata_and_the_owner_is_told():
    from apps.core.services import storage_path
    configure()
    account = customer()
    payment = submitted(account)
    assert payment.status == 'submitted' and payment.receipt_type == 'image/jpeg'
    assert payment.payer_note == 'Card 4421, 14:05' and payment.submitted_at
    path = storage_path(payment.receipt_key)
    assert payment.receipt_key.startswith('receipts/') and oct(path.stat().st_mode)[-3:] == '600'
    with Image.open(path) as kept:
        assert not kept.getexif(), 'no location or device data survives'
    assert PaymentNotice.objects.filter(manual=payment, kind='staff_new').count() == 1


def test_a_pdf_receipt_is_kept_as_it_is():
    configure()
    payment = submitted(customer(), raw=pdf())
    assert payment.receipt_type == 'application/pdf'


@pytest.mark.parametrize('raw,code', [
    (b'not a receipt at all', 'invalid_receipt'),
    (b'%PDF-1.7 broken', 'invalid_receipt'),
    (pdf(encrypted=True), 'invalid_receipt'),
    (pdf(pages=11), 'invalid_receipt'),
    (b'', 'receipt_too_large'),
    (b'x' * (10 * 1024 * 1024 + 1), 'receipt_too_large'),
])
def test_anything_but_a_plain_photo_or_pdf_is_refused(raw, code):
    configure()
    account = customer()
    payment, _ = manual.create(account, 'plus')
    with pytest.raises(DomainError, match=code):
        manual.attach_receipt(account, payment.id, raw)
    payment.refresh_from_db()
    assert payment.status == 'awaiting' and not payment.receipt_key


def test_the_same_receipt_file_sent_twice_is_flagged():
    configure()
    raw = png()
    first = submitted(customer(7001), raw=raw)
    second = submitted(customer(7002), raw=raw)
    assert list(manual.duplicates(second)) == [first]


def test_someone_elses_request_cannot_be_touched():
    configure()
    payment, _ = manual.create(customer(7001), 'plus')
    with pytest.raises(DomainError, match='not_found'):
        manual.attach_receipt(customer(7002), payment.id, png())
    with pytest.raises(DomainError, match='not_found'):
        manual.cancel(customer(7002), payment.id)


# ---------------------------------------------------------------- the decision


def test_approval_gives_the_plan_and_its_weekly_limits_for_thirty_days():
    configure()
    account = customer()
    payment = manual.approve(submitted(account).id, finance(), 'Seen in bank app')
    account.refresh_from_db()
    assert account.plan == 'premium' and payment.status == 'approved'
    usage = usage_snapshot(account)
    assert usage['plan'] == 'premium', 'the plan bought, not Free'
    assert usage['ai_documents']['limit'] is usage['file_jobs']['limit'] is usage['edits_per_file'] is None
    assert not UsageGrant.objects.exists() and not PaymentGrant.objects.exists(), 'there are no credits to grant'
    paid = Payment.objects.get()
    assert (paid.provider, paid.currency, paid.amount_xtr, paid.sandbox) == ('manual', 'UZS', 60_000, False)
    assert 'quantities' not in paid.invoice.snapshot and paid.invoice.offer_id == 'manual:premium:60000'
    period = SubscriptionPeriod.objects.get()
    assert period.ends_at - period.starts_at == timedelta(days=30)
    assert account.subscription.provider == 'manual' and not account.subscription.renewal_enabled
    assert PaymentNotice.objects.filter(manual=payment, kind='approved').count() == 1
    assert manual.approve(payment.id, finance('Finance', 'second')).pk == payment.pk
    assert Payment.objects.count() == 1, 'approving twice changes nothing'


def test_a_paid_plan_follows_the_owners_changes_to_its_limits():
    """A payment buys the plan, not a copy of its numbers taken at approval."""
    configure()
    account = customer()
    manual.approve(submitted(account, 'plus').id, finance())
    assert usage_snapshot(account)['ai_documents']['limit'] == limits_for_plan('plus')['weekly_ai_documents'] == 20
    plan_settings.save('plus', {'weekly_ai_documents': 30})
    assert usage_snapshot(account)['ai_documents']['limit'] == 30


def test_only_finance_staff_decide():
    configure()
    payment = submitted(customer())
    for actor in (None, finance('Support', 'support')):
        with pytest.raises(DomainError, match='permission_denied'):
            manual.approve(payment.id, actor)
        with pytest.raises(DomainError, match='permission_denied'):
            manual.reject(payment.id, actor, 'Not received')


def test_paying_again_adds_thirty_days_and_a_higher_plan_starts_at_once():
    configure()
    account = customer()
    staff = finance()
    manual.approve(submitted(account, 'plus').id, staff)
    first = SubscriptionPeriod.objects.get()
    manual.approve(submitted(account, 'plus').id, staff)
    second = SubscriptionPeriod.objects.exclude(pk=first.pk).get()
    assert second.starts_at == first.ends_at, 'nothing already paid for is cut short'
    assert account.subscription.__class__.objects.get(account=account).current_period_end == second.ends_at
    manual.approve(submitted(account, 'premium').id, staff)
    account.refresh_from_db()
    assert account.plan == 'premium'
    assert usage_snapshot(account)['ai_documents']['limit'] is None, 'Premium is unlimited from the moment it starts'


@pytest.mark.parametrize('old_price,days', [(60_000, 90), (50_000, 75), (25_000, 37), (20_000, 30), (15_000, 30)])
def test_a_transfer_at_an_old_price_buys_time_at_todays(old_price, days):
    """An overpayment becomes a longer period, in whole days; a price that rose
    since never gives less than the 30 days the customer was promised."""
    configure()
    account = customer()
    payment = opened_at(account, 'plus', old_price, 20_000)
    payment = manual.attach_receipt(account, payment.id, png())
    assert manual.period_days(payment) == days
    manual.approve(payment.id, finance())
    period = SubscriptionPeriod.objects.get()
    assert period.ends_at - period.starts_at == timedelta(days=days)
    assert Payment.objects.get().invoice.snapshot['period_days'] == days
    from apps.commerce.models import CommerceAction
    assert CommerceAction.objects.get(action='manual_payment.approved').metadata['days'] == days


def test_a_plan_taken_off_sale_still_gives_the_promised_thirty_days():
    configure()
    account = customer()
    payment = manual.attach_receipt(account, manual.create(account, 'premium')[0].id, png())
    plan_settings.save('premium', {'price_uzs': ''})
    assert 'premium' not in manual.prices() and manual.period_days(payment) == 30


def test_a_rejection_needs_a_reason_and_gives_nothing():
    configure()
    account = customer()
    payment = submitted(account)
    with pytest.raises(DomainError, match='audit_reason_required'):
        manual.reject(payment.id, finance(), 'no')
    payment = manual.reject(payment.id, finance('Finance', 'f2'), 'No transfer of 60 000 arrived')
    account.refresh_from_db()
    assert payment.status == 'rejected' and account.plan == 'free' and not Payment.objects.exists()
    assert PaymentNotice.objects.filter(manual=payment, kind='rejected').count() == 1
    with pytest.raises(DomainError, match='manual_payment_closed'):
        manual.approve(payment.id, finance('Finance', 'f3'))


def test_a_refund_takes_the_plan_back_without_asking_telegram(monkeypatch):
    configure()
    monkeypatch.setattr('apps.commerce.services.provider_for', Mock(side_effect=AssertionError('no provider')))
    account = customer()
    payment = manual.approve(submitted(account).id, finance())
    manual.refund(payment.id, finance('Finance', 'f2'), 'Returned by bank transfer')
    account.refresh_from_db()
    payment.refresh_from_db()
    assert account.plan == 'free' and payment.status == 'refunded'
    assert SubscriptionPeriod.objects.get().revoked_at is not None


def test_a_manual_subscription_has_no_renewal_to_switch(monkeypatch):
    from apps.commerce.services import schedule_plan_change, set_renewal
    configure()
    account = customer()
    manual.approve(submitted(account).id, finance())
    for action in (lambda: set_renewal(account, True), lambda: set_renewal(account, False),
                   lambda: schedule_plan_change(account, 'plus')):
        with pytest.raises(DomainError, match='manual_subscription_not_renewable'):
            action()


def test_a_manual_invoice_can_never_be_paid_through_telegram():
    from apps.commerce.models import Invoice
    from apps.commerce.services import payload_for, validate_precheckout
    configure()
    account = customer()
    manual.approve(submitted(account).id, finance())
    invoice = Invoice.objects.get()
    with pytest.raises(DomainError, match='invalid_invoice'):
        validate_precheckout(account.telegram_user_id, payload_for(invoice), 'XTR', invoice.amount_xtr)


# ---------------------------------------------------------------- housekeeping


def test_an_unpaid_request_expires_after_two_days():
    configure()
    payment, _ = manual.create(customer(), 'plus')
    manual.housekeeping(timezone.now() + timedelta(hours=manual.AWAIT_HOURS, seconds=1))
    payment.refresh_from_db()
    assert payment.status == 'expired'


def test_a_reminder_is_queued_once_a_few_days_before_the_period_ends():
    configure()
    account = customer()
    payment = manual.approve(submitted(account).id, finance())
    manual.housekeeping(timezone.now() + timedelta(days=10))
    assert not PaymentNotice.objects.filter(kind='renewal_reminder').exists()
    near = timezone.now() + timedelta(days=28)
    manual.housekeeping(near)
    manual.housekeeping(near)
    assert PaymentNotice.objects.filter(manual=payment, kind='renewal_reminder').count() == 1


def test_no_reminder_when_the_next_period_is_already_paid():
    configure()
    account = customer()
    staff = finance()
    manual.approve(submitted(account, 'plus').id, staff)
    manual.approve(submitted(account, 'plus').id, staff)
    manual.housekeeping(timezone.now() + timedelta(days=28))
    assert not PaymentNotice.objects.filter(kind='renewal_reminder').exists()


def test_a_receipt_is_deleted_ninety_days_after_the_decision_and_not_before():
    from apps.core.services import cleanup_expired, storage_path
    configure()
    payment = manual.approve(submitted(customer()).id, finance())
    path = storage_path(payment.receipt_key)
    cleanup_expired()
    assert path.exists(), 'the file sweep leaves receipts alone'
    manual.housekeeping(timezone.now() + timedelta(days=manual.RECEIPT_RETENTION_DAYS, seconds=1))
    payment.refresh_from_db()
    assert not path.exists() and payment.receipt_key == '' and payment.receipt_deleted_at
    assert payment.status == 'approved', 'the record of the payment stays'


# ---------------------------------------------------------------- customer API


def signed_in(account):
    from django.test import Client
    client = Client()
    session = client.session
    session['customer_account_id'] = str(account.id)
    session['customer_auth_version'] = account.auth_version
    session.save()
    return client


def test_the_api_offers_card_payment_and_walks_a_payment_to_review():
    from django.core.files.uploadedfile import SimpleUploadedFile
    configure()
    account = customer()
    client = signed_in(account)
    offered = client.get('/api/v1/billing/manual').json()
    assert offered['enabled'] and offered['payment'] is None and offered['automatic'] == {'available': False}
    assert {plan['plan']: plan['price'] for plan in offered['plans']} == PRICES
    created = client.post('/api/v1/billing/manual', {'plan': 'plus'}, content_type='application/json')
    assert created.status_code == 201
    payment = created.json()
    assert payment['card']['number'] == CARD and payment['amount'] == 20_000 and payment['status'] == 'awaiting'
    sent = client.post(f'/api/v1/billing/manual/{payment["id"]}/receipt',
                       {'file': SimpleUploadedFile('r.jpg', png(), 'image/jpeg'), 'note': 'card 4421'})
    assert sent.status_code == 200 and sent.json()['status'] == 'submitted' and sent.json()['receipt_received']
    assert client.get('/api/v1/billing/manual').json()['payment']['id'] == payment['id']


def test_the_card_number_is_shown_only_while_a_payment_is_open():
    configure()
    account = customer()
    client = signed_in(account)
    payment = manual.reject(submitted(account).id, finance(), 'No transfer arrived at all')
    shown = client.get(f'/api/v1/billing/manual/{payment.id}').json()
    assert shown['card']['number'] is None and shown['card']['last4'] == CARD[-4:]
    assert shown['rejection_reason'] == 'No transfer arrived at all'


def test_the_api_needs_a_signed_in_owner():
    from django.test import Client
    configure()
    assert Client().get('/api/v1/billing/manual').status_code == 401
    payment, _ = manual.create(customer(7001), 'plus')
    stranger = signed_in(customer(7002))
    assert stranger.get(f'/api/v1/billing/manual/{payment.id}').status_code == 404
    assert stranger.delete(f'/api/v1/billing/manual/{payment.id}').status_code == 404


def test_a_bad_receipt_gets_a_message_the_customer_can_act_on():
    from django.core.files.uploadedfile import SimpleUploadedFile
    configure()
    account = customer()
    client = signed_in(account)
    payment, _ = manual.create(account, 'plus')
    response = client.post(f'/api/v1/billing/manual/{payment.id}/receipt',
                           {'file': SimpleUploadedFile('r.heic', b'not an image', 'image/heic')})
    assert response.status_code == 400
    assert 'JPG or PNG' in response.json()['error']['message']


def test_the_contract_describes_card_payments():
    import json
    from django.conf import settings
    contract = json.loads((settings.BASE_DIR / 'contracts' / 'public.openapi.json').read_text())
    for path in ('/billing/manual', '/billing/manual/{id}', '/billing/manual/{id}/receipt'):
        assert path in contract['paths']
    assert 'multipart/form-data' in contract['paths']['/billing/manual/{id}/receipt']['post']['requestBody']['content']


# ---------------------------------------------------------------- admin


def staff_client(role):
    from django.http import HttpResponse
    from django.test import Client
    from operations.auth import COOKIE, begin_session
    user = finance(role, f'staff-{role.lower().replace(" ", "-")}')
    client = Client()
    client.cookies[COOKIE] = begin_session(HttpResponse(), user).cookies[COOKIE].value
    return client, user


def test_only_administrators_set_the_card_and_every_change_is_audited():
    from operations.models import AuditLog
    for role in ('Finance', 'Support', 'Operations'):
        client, _ = staff_client(role)
        response = client.post('/ops/integrations', {'integration': 'manual_payments', 'card_number': CARD,
                                                     'card_holder': 'X Y', 'enabled': 'true', 'reason': 'Set the card'})
        assert response.status_code in (302, 403) and manual_payment_config()['configured'] is False, role
    client, _ = staff_client('Administrator')
    response = client.post('/ops/integrations', {'integration': 'manual_payments', 'card_number': CARD,
                                                 'card_holder': 'Shakhzod Uralov', 'card_label': 'Humo',
                                                 'enabled': 'true', 'reason': 'Set the business card'})
    assert response.status_code == 302 and manual_payment_config()['ready']
    entry = AuditLog.objects.get(action='integration.save', target='manual_payments')
    assert entry.after == {'configured': True, 'card_last4': CARD[-4:], 'enabled': True}
    page = client.get('/ops/integrations').content.decode()
    assert 'manual-payment-settings' in page and CARD[-4:] in page


def test_finance_reviews_and_approves_from_the_payments_page():
    from operations.models import AuditLog
    configure()
    account = customer()
    payment = submitted(account)
    client, _ = staff_client('Finance')
    page = client.get('/ops/payments').content.decode()
    assert payment.reference in page and 'nav-badge' in page
    review = client.get(f'/ops/payments/manual/{payment.id}').content.decode()
    assert '60 000 so&#x27;m' in review or "60 000 so'm" in review
    assert 'bank app' in review
    response = client.post(f'/ops/payments/manual/{payment.id}', {'action': 'approve'})
    assert response.status_code == 302
    account.refresh_from_db()
    assert account.plan == 'premium'
    assert AuditLog.objects.filter(action='payment.manual_approve', target=str(payment.id)).exists()
    report = client.get('/ops/payments').content.decode()
    assert "So&#x27;m received" in report or "So'm received" in report


@pytest.mark.parametrize('lang,paid,today,note,days', [
    ('en', "60 000 so", "20 000 so", 'opened at an older, higher price', '90 days of Plus'),
    ('uz', "60 000 so", "20 000 so", 'avvalgi, qimmatroq narxda ochilgan', 'Plus tarifi, 90 kun'),
    ('ru', "60 000 so", "20 000 so", 'по старой, более высокой цене', 'Plus на 90 дн.'),
])
def test_the_review_page_shows_an_old_price_beside_todays_and_the_days_approval_gives(lang, paid, today, note, days):
    configure()
    account = customer()
    payment = opened_at(account, 'plus', 60_000, 20_000)
    manual.attach_receipt(account, payment.id, png())
    client, _ = staff_client('Finance')
    review = client.get(f'/ops/payments/manual/{payment.id}?lang={lang}').content.decode().replace('&#x27;', "'")
    assert paid in review and today in review and note in review and days in review, lang
    assert client.post(f'/ops/payments/manual/{payment.id}', {'action': 'approve'}).status_code == 302
    period = SubscriptionPeriod.objects.get()
    assert period.ends_at - period.starts_at == timedelta(days=90), 'what the page said is what approval gave'


def test_the_review_page_says_nothing_extra_when_the_price_is_unchanged():
    configure()
    payment = submitted(customer(), 'plus')
    client, _ = staff_client('Finance')
    review = client.get(f'/ops/payments/manual/{payment.id}?lang=en').content.decode()
    assert '30 days of Plus' in review and 'price-note' not in review


def test_a_receipt_is_opened_only_by_finance_and_the_view_is_audited():
    from operations.models import AuditLog
    configure()
    payment = submitted(customer())
    support, _ = staff_client('Support')
    assert support.get(f'/ops/payments/manual/{payment.id}/receipt').status_code in (302, 403)
    assert not AuditLog.objects.filter(action='payment.receipt_view').exists()
    client, _ = staff_client('Finance')
    response = client.get(f'/ops/payments/manual/{payment.id}/receipt')
    assert response.status_code == 200 and response['Content-Type'] == 'image/jpeg'
    assert response['X-Content-Type-Options'] == 'nosniff' and 'no-store' in response['Cache-Control']
    assert AuditLog.objects.filter(action='payment.receipt_view', target=str(payment.id)).count() == 1


def test_a_pdf_receipt_is_only_ever_a_download():
    configure()
    payment = submitted(customer(), raw=pdf())
    client, _ = staff_client('Finance')
    response = client.get(f'/ops/payments/manual/{payment.id}/receipt')
    assert response['Content-Disposition'].startswith('attachment')


def test_rejecting_from_the_panel_tells_the_customer_why():
    configure()
    payment = submitted(customer())
    client, _ = staff_client('Finance')
    client.post(f'/ops/payments/manual/{payment.id}', {'action': 'reject', 'message': 'Amount did not arrive'})
    payment.refresh_from_db()
    assert payment.status == 'rejected' and payment.decision_note == 'Amount did not arrive'


def test_a_ready_made_rejection_reaches_the_customer_in_their_language():
    configure()
    account = customer(7301)
    account.locale = 'uz'
    account.save(update_fields=['locale'])
    payment = submitted(account)
    client, _ = staff_client('Finance')
    page = client.get(f'/ops/payments/manual/{payment.id}').content.decode()
    assert 'name="reason"' not in page and 'value="not_received"' in page
    client.post(f'/ops/payments/manual/{payment.id}', {'action': 'reject', 'choice': 'not_received'})
    payment.refresh_from_db()
    assert payment.decision_note == manual.REJECTIONS['not_received']['uz']


def test_a_rejection_needs_a_message_for_the_customer():
    configure()
    payment = submitted(customer(7302))
    client, _ = staff_client('Finance')
    client.post(f'/ops/payments/manual/{payment.id}', {'action': 'reject'})
    payment.refresh_from_db()
    assert payment.status == 'submitted'


def test_stars_totals_no_longer_count_card_payments():
    from operations.commerce_views import financial_report
    from operations.metrics import Filters
    from django.test import RequestFactory
    configure()
    # A real customer: the production report leaves test accounts out.
    real = resolve_account({'id': 7101, 'first_name': 'Real', 'language_code': 'en'}, is_test=False)
    manual.approve(submitted(real).id, finance())
    request = RequestFactory().get('/ops/payments', {'environment': 'production'})
    totals = financial_report(Filters.from_request(request))['totals']
    assert totals['gross'] == 0 and totals['uzs_gross'] == 60_000 and totals['uzs_net'] == 60_000


def test_the_card_is_not_called_active_while_no_plan_has_a_price():
    """A saved card alone offers nothing: customers see card payment only for a priced plan."""
    configure(prices=None)
    client, _ = staff_client('Administrator')
    page = client.get('/ops/integrations').content.decode()
    assert 'manual-no-prices' not in page, 'the default prices are on sale'
    for plan in ('plus', 'premium'):
        plan_settings.save(plan, {'price_uzs': ''})
    page = client.get('/ops/integrations').content.decode()
    assert 'manual-no-prices' in page and '/ops/plans' in page


def test_plus_and_premium_are_on_sale_at_their_default_prices():
    assert manual.prices() == {'plus': 20_000, 'premium': 60_000}
