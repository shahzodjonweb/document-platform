"""Card transfers the owner reviews: what a customer gets, and when."""
import io
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from PIL import Image

from apps.commerce import manual, pricing
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


def paid(account, plan='premium'):
    """`account` on `plan`, paid for by card and approved: how a test puts
    someone on a paid plan, the only way a customer can.

    The card settings are put in place when a test never configured them, and
    the Finance reviewer is made once.
    """
    if not manual_payment_config()['ready'] or plan not in manual.prices():
        configure()
    payment = submitted(account, plan)
    reviewer = get_user_model().objects.filter(username='finance').first() or finance()
    manual.approve(payment.id, reviewer)
    account.refresh_from_db()
    return account


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
    assert offered['enabled'] and offered['plans'] == [{'plan': 'premium', 'price': 65_000, 'regular_price': 65_000, 'discount': None}]
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


def test_a_refund_takes_the_plan_back_without_asking_telegram():
    configure()
    # The owner returns the money by bank transfer and records it here; there
    # is no payment provider left to ask, so a refund is only a record.
    account = customer()
    payment = manual.approve(submitted(account).id, finance())
    manual.refund(payment.id, finance('Finance', 'f2'), 'Returned by bank transfer')
    account.refresh_from_db()
    payment.refresh_from_db()
    assert account.plan == 'free' and payment.status == 'refunded'
    assert SubscriptionPeriod.objects.get().revoked_at is not None
    assert not account.subscription.renewal_enabled, 'a card plan never renews by itself'


# ---------------------------------------------------------------- discounts


def on_discount(plan='plus', price=15_000, until=None):
    """The owner puts `plan` on discount at `price` until `until` (a fortnight away by default)."""
    until = until or (pricing.today() + timedelta(days=14)).isoformat()
    plan_settings.save(plan, {'discount_price_uzs': price, 'discount_until': until})
    return until


def discount_over(plan='plus'):
    """The discount's last day has passed; the panel still holds it, as an owner who forgot it would."""
    from operations.models import IntegrationConfig
    stored = plan_settings.overrides()
    stored[plan] = {**stored.get(plan, {}), 'discount_until': (pricing.today() - timedelta(days=1)).isoformat()}
    IntegrationConfig.objects.update_or_create(pk=plan_settings.KEY, defaults={'configuration': stored})
    assert pricing.plan_price(plan)['discount'] is None


def test_a_discount_is_todays_price_and_never_changes_the_days():
    configure()
    until = on_discount()
    assert manual.prices() == {'plus': 15_000, 'premium': 60_000}
    assert manual.regular_prices() == {'plus': 20_000, 'premium': 60_000}
    assert manual.options()['plans'] == [
        {'plan': 'plus', 'price': 15_000, 'regular_price': 20_000,
         'discount': {'price': 15_000, 'regular': 20_000, 'percent': 25, 'until': until}},
        {'plan': 'premium', 'price': 60_000, 'regular_price': 60_000, 'discount': None}]
    account = customer()
    payment = submitted(account, 'plus')
    assert payment.amount == 15_000 and manual.period_days(payment) == 30
    manual.approve(payment.id, finance())
    period = SubscriptionPeriod.objects.get()
    assert period.ends_at - period.starts_at == timedelta(days=30)
    paid = Payment.objects.get()
    assert paid.amount_xtr == 15_000 and paid.invoice.offer_id == 'manual:plus:15000'
    snapshot = paid.invoice.snapshot
    assert (snapshot['price'], snapshot['regular_price'], snapshot['discounted'], snapshot['period_days']) == (15_000, 20_000, True, 30)


def test_the_full_price_sent_during_a_discount_buys_thirty_days_not_forty():
    """A discount is a lower price for the same 30 days, not a cheaper day."""
    configure()
    account = customer()
    payment = submitted(account, 'plus')
    on_discount()
    assert payment.amount == 20_000 and manual.period_days(payment) == 30
    manual.approve(payment.id, finance())
    period = SubscriptionPeriod.objects.get()
    assert period.ends_at - period.starts_at == timedelta(days=30)
    assert Payment.objects.get().invoice.snapshot['discounted'] is False


def test_an_unpaid_request_follows_the_discount_in_and_out():
    """The plans page says 15 000 while the discount runs; the card screen must ask for the same."""
    configure()
    account = customer()
    before, _ = manual.create(account, 'plus')
    on_discount()
    during, created = manual.create(account, 'plus')
    before.refresh_from_db()
    assert created and during.amount == 15_000 and before.status == 'cancelled'
    assert manual.create(account, 'plus')[0].pk == during.pk, 'reused while the price holds'
    plan_settings.save('plus', {'discount_price_uzs': '', 'discount_until': ''})
    after, created = manual.create(account, 'plus')
    during.refresh_from_db()
    assert created and after.amount == 20_000 and during.status == 'cancelled'


def test_a_discounted_receipt_approved_after_the_discount_ended_still_gives_thirty_days():
    configure()
    on_discount()
    account = customer()
    payment = submitted(account, 'plus')
    discount_over()
    assert manual.prices()['plus'] == 20_000 and manual.period_days(payment) == 30
    manual.approve(payment.id, finance())
    period = SubscriptionPeriod.objects.get()
    assert period.ends_at - period.starts_at == timedelta(days=30)
    assert Payment.objects.get().invoice.snapshot['discounted'] is True, 'what was bought, not what it costs now'


@pytest.mark.parametrize('lang,today,regular,now,over', [
    ('en', "15 000 so'm (regular 20 000 so'm)", 'opened at the regular price', 'on discount today at 15 000', 'opened during a discount'),
    ('uz', "15 000 so'm (odatdagi narx 20 000 so'm)", 'odatdagi narxda ochilgan', 'chegirma bilan 15 000', 'chegirma paytida ochilgan'),
    ('ru', "15 000 so'm (обычная цена 20 000 so'm)", 'по обычной цене', 'со скидкой стоит 15 000', 'во время скидки'),
])
def test_the_review_page_names_the_discount(lang, today, regular, now, over):
    configure()
    client, _ = staff_client('Finance')
    page = lambda payment: client.get(f'/ops/payments/manual/{payment.id}?lang={lang}').content.decode().replace('&#x27;', "'")
    # Sent at the regular price, reviewed while the discount runs: 30 days, and the page says why.
    full = submitted(customer(7401), 'plus')
    on_discount()
    review = page(full)
    assert today in review and regular in review and now in review and '30' in review, lang
    # Sent at the discounted price while it runs: nothing to explain.
    cut = submitted(customer(7402), 'plus')
    review = page(cut)
    assert today in review and 'price-note' not in review, lang
    # Reviewed once the discount is over: the page says it was opened during one.
    discount_over()
    review = page(cut)
    assert "20 000 so'm" in review and '(' not in review.split('price-note')[0].split('</h1>')[-1][:0] and over in review, lang
    assert 'odatdagi narx 20 000' not in review and 'regular 20 000' not in review and 'обычная цена 20 000' not in review


def test_a_request_keeps_the_regular_price_it_was_opened_against():
    """A discounted request stays one however the prices move afterwards, and
    a full-price one never becomes one: the invoice says what was bought."""
    import re
    configure()
    staff = finance()
    full = submitted(customer(7411), 'plus')
    assert (full.amount, full.regular_amount) == (20_000, 20_000)
    on_discount()
    cut = submitted(customer(7412), 'plus')
    assert (cut.amount, cut.regular_amount) == (15_000, 20_000)
    # The regular price rises: the full-price receipt was still a full-price one.
    plan_settings.save('plus', {'price_uzs': 25_000, 'discount_price_uzs': '', 'discount_until': ''})
    snapshot = manual.approve(full.id, staff).payment.invoice.snapshot
    assert (snapshot['price'], snapshot['regular_price'], snapshot['discounted']) == (20_000, 20_000, False)
    # The plan goes off sale: the discounted receipt was still a discounted one.
    plan_settings.save('plus', {'price_uzs': ''})
    snapshot = manual.approve(cut.id, staff).payment.invoice.snapshot
    assert (snapshot['price'], snapshot['regular_price'], snapshot['discounted']) == (15_000, 20_000, True)
    # A request from before discounts has no regular price of its own, and was not one.
    old = submitted(customer(7413), 'premium')
    ManualPayment.objects.filter(pk=old.pk).update(regular_amount=None)
    snapshot = manual.approve(old.id, staff).payment.invoice.snapshot
    assert (snapshot['price'], snapshot['regular_price'], snapshot['discounted']) == (60_000, None, False)
    assert re.fullmatch(r'manual:\w+:\d+', snapshot['id'])


def note_on(client, payment, lang='en'):
    """The price note on the review page, as text, or ''."""
    import re
    page = client.get(f'/ops/payments/manual/{payment.id}?lang={lang}').content.decode().replace('&#x27;', "'")
    if 'price-note' not in page:
        return ''
    inside = page.split('price-note', 1)[1].split('>', 1)[1].split('</div>', 1)[0]
    return ' '.join(re.sub(r'<[^>]+>', ' ', inside).split())


def test_the_review_page_says_what_the_request_was_opened_against():
    """The note is read from the request's own regular price, not from what the
    panel holds today: an earlier discount, deepened or withdrawn since, is
    still "opened during a discount", and an overpayment quotes the regular
    price the extra days are worked out on."""
    configure()
    client, _ = staff_client('Finance')
    on_discount()
    cut = submitted(customer(7421), 'plus')
    assert note_on(client, cut) == ''
    # Deepened since: it was opened during a discount, not at the regular price.
    on_discount(price=10_000)
    note = note_on(client, cut)
    assert note.startswith('This request was opened during a discount') and "10 000 so'm today" in note, note
    # Withdrawn since: the price did not rise, the discount ended.
    plan_settings.save('plus', {'discount_price_uzs': '', 'discount_until': ''})
    note = note_on(client, cut)
    assert note.startswith('This request was opened during a discount') and "20 000 so'm today" in note, note
    # An overpayment quotes the regular price, which the extra days are worked out on, in every language.
    plan_settings.save('plus', {'price_uzs': 25_000})
    over = submitted(customer(7422), 'plus')
    plan_settings.save('plus', {'price_uzs': 20_000})
    on_discount()
    assert manual.period_days(over) == 37
    for lang, words in (('en', 'the regular price is 20 000 so\'m today'), ('uz', 'odatdagi narxi esa bugun 20 000 so\'m'),
                        ('ru', 'обычная цена тарифа сегодня — 20 000 so\'m')):
        note = note_on(client, over, lang)
        assert words in note and '37' in note and '15 000' not in note, (lang, note)
    # Opened at the regular price, which rose since: before the price rose.
    plan_settings.save('plus', {'discount_price_uzs': '', 'discount_until': ''})
    full = submitted(customer(7423), 'plus')
    plan_settings.save('plus', {'price_uzs': 30_000})
    assert note_on(client, full).startswith('This request was opened before the price rose')
    # The same request with the plan on discount today: opened at the regular price.
    plan_settings.save('plus', {'price_uzs': 20_000})
    on_discount()
    assert note_on(client, full).startswith('This request was opened at the regular price')
    # A request from before discounts was opened at the regular price, as they all were.
    ManualPayment.objects.filter(pk=full.pk).update(regular_amount=None)
    assert note_on(client, full).startswith('This request was opened at the regular price')
    ManualPayment.objects.filter(pk=cut.pk).update(regular_amount=None)
    assert note_on(client, cut) == '', 'asked for today\'s price: nothing to say'


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
    # A payment's amounts are so'm in `currency`, and are not named after Stars.
    payment = contract['components']['schemas']['Payment']
    assert {'amount', 'refunded'} <= set(payment['properties']) and {'amount', 'refunded'} <= set(payment['required'])
    assert not {'amount_xtr', 'refunded_xtr'} & set(payment['properties'])


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


def test_the_money_report_counts_card_payments_in_som_and_nothing_else():
    from operations.commerce_views import financial_report, money_cards, LABELS
    from operations.metrics import Filters
    from django.test import RequestFactory
    configure()
    # A real customer: the production report leaves test accounts out.
    real = resolve_account({'id': 7101, 'first_name': 'Real', 'language_code': 'en'}, is_test=False)
    manual.approve(submitted(real).id, finance())
    request = RequestFactory().get('/ops/payments', {'environment': 'production'})
    totals = financial_report(Filters.from_request(request))['totals']
    assert totals == {'uzs_gross': 60_000, 'uzs_refunds': 0, 'uzs_net': 60_000, 'payers': 1, 'paid': 1, 'first': 1, 'manual_pending': 0}
    assert [card['key'] for card in money_cards(totals, LABELS['en'])] == ['uzs_gross', 'uzs_refunds', 'uzs_net', 'payers', 'paid', 'first']
    assert not {'gross', 'run_rate', 'reconcile', 'issues', 'failed', 'initial', 'pending'} & set(LABELS['en']), 'no Stars-era labels'
    assert LABELS['en'].keys() == LABELS['uz'].keys() == LABELS['ru'].keys()


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
