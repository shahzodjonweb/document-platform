"""Plus and Premium bought for a year at once, beside the month.

The owner's prices: a month stays 20 000 (Plus) and 60 000 (Premium) so'm; a
year is 11 000 × 12 = 132 000 and 33 000 × 12 = 396 000 so'm, paid once, for
365 days. A discount lowers the month only; a year never renews by itself.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.commerce import checkout, manual, pricing
from apps.commerce.models import Checkout, ManualPayment, Payment, SubscriptionPeriod
from apps.commerce.services import effective_plan
from apps.core.errors import DomainError
from operations import plans as plan_settings
from tests.test_inpay_checkout import FakeInpay, signed_webhook, switch_on
from tests.test_manual_payments import configure, customer, finance, png, signed_in, staff_client

pytestmark = pytest.mark.django_db
PLUS_YEAR = {'price': 132_000, 'per_month': 11_000, 'regular': 240_000, 'percent': 45, 'days': 365}
PREMIUM_YEAR = {'price': 396_000, 'per_month': 33_000, 'regular': 720_000, 'percent': 45, 'days': 365}


@pytest.fixture
def bank(monkeypatch):
    from apps.commerce import inpay
    fake = FakeInpay()
    monkeypatch.setattr(inpay, '_call', fake)
    return fake


def on_discount(plan='plus', price=15_000):
    until = (pricing.today() + timedelta(days=14)).isoformat()
    plan_settings.save(plan, {'discount_price_uzs': price, 'discount_until': until})
    return until


# ---------------------------------------------------------------- the price


def test_a_year_is_the_owners_price_spread_over_twelve_months_with_its_saving():
    assert pricing.plan_price('plus')['yearly'] == PLUS_YEAR
    assert pricing.plan_price('premium')['yearly'] == PREMIUM_YEAR
    assert pricing.plan_price('free') is None
    assert pricing.charge_for(pricing.plan_price('plus'), 'year') == (132_000, 132_000)
    assert pricing.charge_for(pricing.plan_price('plus'), 'month') == (20_000, 20_000)
    assert pricing.days_for('year') == 365 and pricing.days_for('month') == 30
    assert [pricing.term_of(value) for value in (None, '', 'month', 'year', 'week', 12)] == ['month', 'month', 'month', 'year', None, None]


def test_a_discount_lowers_the_month_and_leaves_the_year_as_it_is():
    on_discount('plus', 15_000)
    offer = pricing.plan_price('plus')
    assert offer['price'] == 15_000 and offer['yearly'] == PLUS_YEAR, 'saving still against the regular month'
    assert pricing.charge_for(offer, 'month') == (15_000, 20_000)
    assert pricing.charge_for(offer, 'year') == (132_000, 132_000)


@pytest.mark.parametrize('year,shown', [
    (132_000, 45), (237_600, 1), (237_601, None), (240_000, None), (300_000, None),
    (0, None), (-1, None), ('132000', None), (True, None), (None, None),
])
def test_a_year_that_saves_less_than_one_per_cent_is_not_offered(year, shown):
    offer = pricing.plan_price('plus', {'price_uzs': 20_000, 'yearly_price_uzs': year})
    assert (offer['yearly'] or {}).get('percent') == shown
    assert (pricing.charge_for(offer, 'year') is None) == (shown is None)


def test_the_per_month_figure_is_rounded_to_the_nearest_som():
    offer = pricing.plan_price('plus', {'price_uzs': 20_000, 'yearly_price_uzs': 131_995})
    assert offer['yearly']['per_month'] == 11_000  # 10 999.58…
    offer = pricing.plan_price('plus', {'price_uzs': 20_000, 'yearly_price_uzs': 131_993})
    assert offer['yearly']['per_month'] == 10_999  # 10 999.41…


# ---------------------------------------------------------------- the admin panel


def test_the_owner_sets_the_yearly_price_beside_the_monthly_one():
    plan_settings.save('plus', {'yearly_price_uzs': '120000'})
    assert pricing.plan_price('plus')['yearly']['per_month'] == 10_000
    plan_settings.save('plus', {'yearly_price_uzs': ''})
    assert pricing.plan_price('plus')['yearly'] is None, 'blank: sold by the month only'
    with pytest.raises(plan_settings.PlanError, match='free plan has no yearly price'):
        plan_settings.save('free', {'yearly_price_uzs': '50000'})
    with pytest.raises(plan_settings.PlanError, match='at least 1% below 12 months'):
        plan_settings.save('premium', {'yearly_price_uzs': '720000'})


def test_a_monthly_price_lowered_under_the_year_is_refused_from_its_side():
    with pytest.raises(plan_settings.PlanError, match='Lower or clear the yearly price first'):
        plan_settings.save('plus', {'price_uzs': '11000'})
    # Both in one edit is fine.
    plan_settings.save('plus', {'price_uzs': '11000', 'yearly_price_uzs': '120000'})
    assert pricing.plan_price('plus')['yearly']['percent'] == 9


def test_a_plan_taken_off_sale_is_off_sale_by_the_year_too():
    plan_settings.save('premium', {'price_uzs': ''})
    assert pricing.plan_price('premium') is None and 'premium' not in pricing.offers()
    with pytest.raises(plan_settings.PlanError, match='needs a monthly price'):
        plan_settings.save('premium', {'yearly_price_uzs': '300000'})
    plan_settings.save('premium', {'price_uzs': '60000'})
    assert pricing.plan_price('premium')['yearly'] == PREMIUM_YEAR, 'back on sale with the year it had'


def test_the_plans_page_shows_the_year_and_its_field():
    client, _ = staff_client('Finance')
    page = client.get('/ops/plans?lang=en').content.decode().replace('&#x27;', "'").replace(' ', ' ')
    assert "Yearly: 132 000 so'm · 11 000 so'm a month · −45%" in page
    assert "Yearly: 396 000 so'm · 33 000 so'm a month · −45%" in page
    assert 'name="yearly_price_uzs"' in page and 'Monthly only' in page


# ---------------------------------------------------------------- the website: inPAY


def test_the_plans_api_carries_the_year():
    from django.test import Client
    plans = {plan['id']: plan for plan in Client().get('/api/v1/plans').json()['plans']}
    assert plans['plus']['yearly'] == PLUS_YEAR and plans['premium']['yearly'] == PREMIUM_YEAR
    assert plans['free']['yearly'] is None
    assert 'yearly_price_uzs' not in plans['plus']['limits'], 'the year is told once, worked out'


def test_a_year_paid_on_inpay_gives_365_days_and_is_said_to_be_a_year(bank):
    switch_on()
    account = customer()
    client = signed_in(account)
    offered = client.get('/api/v1/billing/manual').json()['plans']
    assert [item['yearly'] for item in offered] == [PLUS_YEAR, PREMIUM_YEAR]

    created = client.post('/api/v1/billing/checkout', {'plan': 'plus', 'term': 'year'}, content_type='application/json')
    assert created.status_code == 201
    opened, row = created.json(), Checkout.objects.get()
    assert (opened['term'], opened['amount'], row.term, row.amount, row.regular_amount) == ('year', 132_000, 'year', 132_000, 132_000)
    remote = bank.payments[row.provider_id]
    assert remote['amount'] == 132_000 and remote['description'] == 'DocMaster Plus — 1 year'

    bank.pay(row.provider_id)
    assert signed_webhook(row.provider_id, amount=132_000).status_code == 200
    account.refresh_from_db()
    assert effective_plan(account) == 'plus'
    period = SubscriptionPeriod.objects.get()
    assert period.ends_at - period.starts_at == timedelta(days=365)
    payment = Payment.objects.get()
    assert payment.amount_xtr == 132_000 and payment.invoice.offer_id == 'inpay:plus:year:132000'
    snapshot = payment.invoice.snapshot
    assert (snapshot['term'], snapshot['period_days'], snapshot['discounted']) == ('year', 365, False)
    assert client.get('/api/v1/billing/transactions').json()['results'][0]['term'] == 'year'
    shown = client.get(f'/api/v1/billing/checkout/{row.id}').json()
    assert shown['term'] == 'year' and shown['active_until'][:19] == period.ends_at.isoformat()[:19]


def test_a_month_and_a_year_are_two_payment_pages(bank):
    switch_on()
    account = customer()
    month, _ = checkout.create(account, 'plus')
    year, created = checkout.create(account, 'plus', term='year')
    assert created and year.pk != month.pk and (month.amount, year.amount) == (20_000, 132_000)
    again, created = checkout.create(account, 'plus', term='year')
    assert again.pk == year.pk and not created, 'the year already open is returned to'


def test_a_term_that_is_not_sold_is_refused(bank):
    switch_on()
    client = signed_in(customer())
    bad = client.post('/api/v1/billing/checkout', {'plan': 'plus', 'term': 'week'}, content_type='application/json')
    assert bad.status_code == 400 and bad.json()['error']['code'] == 'invalid_plan'
    plan_settings.save('plus', {'yearly_price_uzs': ''})
    off = client.post('/api/v1/billing/checkout', {'plan': 'plus', 'term': 'year'}, content_type='application/json')
    assert off.status_code == 409 and off.json()['error']['code'] == 'checkout_disabled'
    assert not Checkout.objects.exists()


def test_a_year_follows_the_month_already_held_and_a_higher_plan_starts_at_once(bank):
    switch_on()
    account = customer()

    def pay(plan, term):
        row, _ = checkout.create(account, plan, term=term)
        bank.pay(row.provider_id)
        checkout.refresh(row, force=True)
        return SubscriptionPeriod.objects.get(payment__checkout=row)

    month = pay('plus', 'month')
    year = pay('plus', 'year')
    assert year.starts_at == month.ends_at and year.ends_at - year.starts_at == timedelta(days=365)
    premium = pay('premium', 'month')
    assert premium.starts_at < month.ends_at, 'a higher plan does not wait'
    account.refresh_from_db()
    assert effective_plan(account) == 'premium'


# ---------------------------------------------------------------- card transfer


def test_a_year_by_card_transfer_is_asked_for_and_approved_as_365_days():
    configure()
    account = customer()
    month, _ = manual.create(account, 'plus')
    year, created = manual.create(account, 'plus', term='year')
    assert created and (year.term, year.amount, year.regular_amount) == ('year', 132_000, 132_000)
    month.refresh_from_db()
    assert month.status == 'cancelled', 'the unpaid month gives way to the year'
    assert manual.create(account, 'plus', term='year') == (year, False)
    manual.attach_receipt(account, year.id, png())
    manual.approve(year.id, finance())
    period = SubscriptionPeriod.objects.get()
    assert period.ends_at - period.starts_at == timedelta(days=365)
    paid = Payment.objects.get()
    assert paid.invoice.offer_id == 'manual:plus:year:132000' and paid.invoice.snapshot['term'] == 'year'
    assert signed_in(account).get(f'/api/v1/billing/manual/{year.id}').json()['term'] == 'year'


def test_a_year_sent_at_an_older_higher_price_buys_more_days():
    configure()
    account = customer()
    payment, _ = manual.create(account, 'plus', term='year')
    ManualPayment.objects.filter(pk=payment.pk).update(amount=144_000, regular_amount=144_000)
    payment.refresh_from_db()
    assert manual.period_days(payment) == 365 * 144_000 // 132_000
    plan_settings.save('plus', {'yearly_price_uzs': ''})
    assert manual.period_days(payment) == 365, 'a year no longer sold still gives the year promised'


def test_a_discount_note_never_sits_on_a_year():
    from telegram.billing import discount_note
    configure()
    on_discount('plus', 15_000)
    account = customer()
    payment, _ = manual.create(account, 'plus', term='year')
    assert payment.amount == 132_000 and discount_note(account, payment) == ''


# ---------------------------------------------------------------- the admin's payment pages


def test_the_admin_shows_a_yearly_transfer_and_what_approving_gives():
    configure()
    account = customer()
    payment, _ = manual.create(account, 'premium', term='year')
    manual.attach_receipt(account, payment.id, png())
    client, _ = staff_client('Finance')
    page = client.get(f'/ops/payments/manual/{payment.id}?lang=en').content.decode()
    assert 'Premium · 1 year' in page and 'data-testid="manual-term"' in page
    assert '365 days of Premium' in page and "396 000 so'm" in page.replace('&#x27;', "'")
    admin, _ = staff_client('Administrator')
    user = admin.get(f'/ops/users/{account.id}?lang=en').content.decode()
    assert 'badge info">1 year' in user


def test_the_admin_shows_a_yearly_inpay_payment_with_its_period(bank):
    from apps.core.identity import resolve_account
    switch_on()
    # A real customer: the payments report leaves test accounts out.
    account = resolve_account({'id': 7101, 'first_name': 'Yearly payer', 'language_code': 'ru'}, is_test=False)
    row, _ = checkout.create(account, 'plus', term='year')
    bank.pay(row.provider_id)
    checkout.refresh(row, force=True)
    row.refresh_from_db()
    period = SubscriptionPeriod.objects.get()
    client, _ = staff_client('Finance')
    detail = client.get(f'/ops/payments/{row.payment_id}?lang=uz').content.decode()
    assert 'data-testid="payment-term"' in detail and '1 yil' in detail
    assert period.ends_at.strftime('%d') in detail and str(period.ends_at.year) in detail
    listed = client.get('/ops/payments?lang=ru').content.decode()
    assert 'Plus · 1 год' in listed
