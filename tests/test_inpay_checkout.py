"""Automatic payment through inPAY: what a customer gets, when, and what never grants a plan.

inPAY itself is always a fake here (`FakeInpay` stands in for `inpay._call`):
it keeps the payments opened with it and answers the way inPAY's two APIs do.
"""
import hashlib
import hmac
import json
import secrets
import time
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.commerce import checkout, inpay
from apps.commerce.models import Checkout, CommerceAction, Payment, PaymentNotice, Subscription, SubscriptionPeriod
from apps.commerce.services import effective_plan
from apps.core.errors import DomainError
from apps.core.models import StaffAlert
from operations import plans as plan_settings
from operations.integrations import inpay_config, save_config, test_inpay as check_inpay
from tests.test_manual_payments import PRICES, configure as configure_card, customer, finance, paid, signed_in, staff_client

pytestmark = pytest.mark.django_db
LIVE, TEST, SIGNING = 'sk_live_4f1c0b7e2a9d55aa', 'sk_test_4f1c0b7e2a9d55aa', 'whsec_b82e6d10c4f771ac'
MERCHANT, MERCHANT_TOKEN = '1353', '6a7bf375b302cfcda6692e6f60402cb3'
OWNER = 1234567  # the Telegram ID tests save for alerts (tests.test_manual_payments.configure)
# The real request function: the suite replaces inpay._call with a refusal before every test (tests/conftest.py).
REAL_CALL = inpay._call


class FakeInpay:
    """inPAY as far as this code speaks to it: both APIs, one set of payments."""

    def __init__(self):
        self.payments, self.by_key, self.calls = {}, {}, []
        self.down = False
        self.refuse = None
        self.live_key = True

    def count(self, method, prefix):
        return sum(1 for seen_method, path in self.calls if seen_method == method and path.startswith(prefix))

    def pay(self, identifier, **changes):
        self.payments[identifier].update(status='succeeded', **changes)

    def __call__(self, method, path, *, headers=None, body=None, query=None):
        self.calls.append((method, path))
        if self.down:
            raise inpay.Unavailable()
        headers, v2 = headers or {}, path.startswith('/api/v2/')
        if v2 and headers.get('Authorization') not in (f'Bearer {LIVE}', f'Bearer {TEST}'):
            return 401, {'success': False, 'error': {'code': 'invalid_api_key'}}
        live = headers.get('Authorization') == f'Bearer {LIVE}'
        if path == '/api/v2/payments/' and method == 'POST':
            if self.refuse:
                return 403, {'success': False, 'error': {'code': self.refuse}}
            identifier = self.by_key.setdefault(headers['Idempotency-Key'], secrets.token_hex(8))
            self.payments.setdefault(identifier, {
                'id': identifier, 'object': 'payment', 'amount': body['amount'], 'currency': 'UZS',
                'status': 'requires_payment_method', 'checkout_url': f'https://inpay.uz/checkout/{identifier}',
                'return_url': body['return_url'], 'webhook_url': body['webhook_url'], 'livemode': live,
                'metadata': body['metadata'], 'description': body['description']})
            return 200, {'success': True, 'data': self.payments[identifier]}
        if path.startswith('/api/v2/payments/') and method == 'GET':
            payment = self.payments.get(path.rsplit('/', 1)[1])
            if not payment:
                return 404, {'success': False, 'error': {'code': 'resource_missing'}}
            return 200, {'success': True, 'data': payment}
        if path == '/api/v2/balance/':
            return 200, {'success': True, 'data': {'object': 'balance', 'livemode': live}}
        if path == '/api/v2/webhooks/secret/':
            if not live:
                return 403, {'success': False, 'error': {'code': 'live_key_required'}}
            return 200, {'success': True, 'data': {'object': 'webhook_secret', 'secret': SIGNING}}
        if path == '/api/v1/authorization/':
            if (query or {}).get('merchant_token') != MERCHANT_TOKEN:
                return 401, {'success': False, 'error_code': 'INVALID_TOKEN'}
            return 200, {'success': True, 'bearer_token': 'bearer-of-the-day'}
        if path == '/api/v1/create/' and method == 'POST':
            if headers.get('Authorization') != 'Bearer bearer-of-the-day':
                return 401, {'success': False, 'error_code': 'INVALID_TOKEN'}
            identifier = secrets.token_hex(8)
            self.payments[identifier] = {'order_id': identifier, 'amount': body['amount'], 'status': 'pending',
                                         'callback_url': body['callback_url'], 'return_url': body['return_url']}
            return 200, {'success': True, 'order_id': identifier, 'pay_url': f'https://inpay.uz/checkout/{identifier}'}
        if path == '/api/v1/transactions/':
            payment = self.payments.get((query or {}).get('order_id'))
            if not payment:
                return 404, {'success': False, 'error_code': 'MERCHANT_NOT_FOUND'}
            status = {'succeeded': 'success'}.get(payment['status'], payment['status'])
            return 200, {'success': True, 'order_id': payment['order_id'], 'status': status, 'amount': payment['amount']}
        raise AssertionError(f'inPAY was asked something this fake does not know: {method} {path}')


@pytest.fixture
def bank(monkeypatch):
    fake = FakeInpay()
    monkeypatch.setattr(inpay, '_call', fake)
    return fake


def switch_on(key=LIVE, signing=SIGNING, prices=PRICES, card=False):
    """inPAY switched on with a v2 key; card transfer off unless asked for. The owner's Telegram ID is saved either way."""
    configure_card(enabled=card, prices=prices)
    # The website inPAY returns customers to, as the owner saves it with the bot's settings.
    save_config('telegram', {'webapp_url': 'https://docmaster.live/en/app'})
    values = {'secret_key': key, 'enabled': 'true'}
    if signing:
        values['webhook_secret'] = signing
    save_config('inpay', values)


def event(identifier, kind='payment.succeeded', status='succeeded', amount=20_000):
    return json.dumps({'id': 'evt_' + secrets.token_hex(16), 'object': 'event', 'type': kind, 'created': int(time.time()),
                       'livemode': True, 'data': {'object': {'id': identifier, 'amount': amount, 'currency': 'UZS',
                                                             'status': status}}}).encode()


def signature(raw, secret=SIGNING, at=None):
    stamp = str(int(at if at is not None else time.time()))
    return f't={stamp},v1=' + hmac.new(secret.encode(), stamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()


def post_webhook(raw, **headers):
    from django.test import Client
    return Client().post('/api/v1/webhooks/inpay', data=raw, content_type='application/json', **headers)


def signed_webhook(identifier, **details):
    raw = event(identifier, **details)
    return post_webhook(raw, HTTP_X_INPAY_SIGNATURE=signature(raw))


# ---------------------------------------------------------------- the main path


def test_nothing_is_offered_until_inpay_is_switched_on(bank):
    configure_card()
    account = customer()
    client = signed_in(account)
    offered = client.get('/api/v1/billing/manual').json()
    assert offered['automatic'] == {'available': False} and offered['enabled'] is True and offered['checkout'] is None
    refused = client.post('/api/v1/billing/checkout', {'plan': 'plus'}, content_type='application/json')
    assert refused.status_code == 409 and refused.json()['error']['code'] == 'checkout_disabled'
    assert not Checkout.objects.exists() and not bank.calls
    assert client.get('/api/v1/plans').json()['checkout'] == {'automatic': False, 'card': True}


def test_a_customer_pays_and_the_plan_starts_by_itself(bank):
    switch_on()
    account = customer()
    client = signed_in(account)
    offered = client.get('/api/v1/billing/manual').json()
    assert offered['automatic'] == {'available': True, 'provider': 'inpay', 'test': False}
    # Card transfer is off, yet the plans are listed: there is a way to pay for them.
    assert offered['enabled'] is False and [plan['plan'] for plan in offered['plans']] == ['plus', 'premium']

    created = client.post('/api/v1/billing/checkout', {'plan': 'plus'}, content_type='application/json')
    assert created.status_code == 201
    opened = created.json()
    row = Checkout.objects.get()
    assert opened['status'] == 'pending' and opened['amount'] == 20_000 and opened['test'] is False
    assert opened['checkout_url'] == f'https://inpay.uz/checkout/{row.provider_id}'
    remote = bank.payments[row.provider_id]
    # inPAY is told the price, and to come back to the customer website's own domain.
    assert remote['amount'] == 20_000 and remote['metadata'] == {'checkout': str(row.id)}
    assert remote['return_url'] == f'https://docmaster.live/en/app/pay/{row.id}'
    assert remote['webhook_url'] == 'https://docmaster.live/api/v1/webhooks/inpay'
    # Opening a payment grants nothing.
    assert effective_plan(account) == 'free' and not Payment.objects.exists()
    assert client.get('/api/v1/billing/manual').json()['checkout']['id'] == opened['id']

    bank.pay(row.provider_id, fiscal_url='https://ofd.soliq.uz/epi?t=EP000000000678&r=235283914')
    assert signed_webhook(row.provider_id).status_code == 200

    account.refresh_from_db()
    assert effective_plan(account) == 'plus' and account.plan == 'plus'
    payment = Payment.objects.get()
    assert (payment.provider, payment.amount_xtr, payment.currency, payment.plan, payment.sandbox) == ('inpay', 20_000, 'UZS', 'plus', False)
    assert payment.provider_charge_id == f'inpay:{row.provider_id}'
    period = SubscriptionPeriod.objects.get()
    assert period.ends_at - period.starts_at == timedelta(days=30)
    assert Subscription.objects.get().provider == 'inpay'
    shown = client.get(f'/api/v1/billing/checkout/{row.id}').json()
    assert shown['status'] == 'paid' and shown['checkout_url'] is None and shown['paid_at']
    assert shown['receipt_url'].startswith('https://ofd.soliq.uz/')
    assert shown['active_until'][:19] == period.ends_at.isoformat()[:19]
    # The customer is told in the bot, and the owner hears of the money.
    assert list(PaymentNotice.objects.values_list('kind', 'checkout_id')) == [('paid', row.id)]
    assert StaffAlert.objects.get().kind == 'inpay_paid' and "20 000 so'm" in StaffAlert.objects.get().text
    assert CommerceAction.objects.filter(action='checkout.paid', target=str(row.id)).count() == 1
    assert client.get('/api/v1/billing/transactions').json()['results'][0]['provider'] == 'inpay'

    # The same news again changes nothing.
    assert signed_webhook(row.provider_id).status_code == 200
    assert Payment.objects.count() == 1 and SubscriptionPeriod.objects.count() == 1 and PaymentNotice.objects.count() == 1


def test_the_page_the_customer_returns_to_finds_the_payment_without_a_webhook(bank):
    switch_on()
    account = customer()
    row, _ = checkout.create(account, 'premium', 'web')
    bank.pay(row.provider_id)
    from django.test import Client
    # Signed out, as a customer coming back from the bot's link is.
    shown = Client().get(f'/api/v1/billing/checkout/{row.id}').json()
    assert shown['status'] == 'paid' and shown['plan'] == 'premium' and shown['checkout_url'] is None
    assert effective_plan(account) == 'premium'


def test_choosing_the_same_plan_again_returns_to_the_page_already_open(bank):
    switch_on()
    account = customer()
    client = signed_in(account)
    first = client.post('/api/v1/billing/checkout', {'plan': 'plus'}, content_type='application/json')
    again = client.post('/api/v1/billing/checkout', {'plan': 'plus'}, content_type='application/json')
    assert (first.status_code, again.status_code) == (201, 200) and first.json()['id'] == again.json()['id']
    assert bank.count('POST', '/api/v2/payments/') == 1
    # Another plan, or another price, is another payment.
    other = client.post('/api/v1/billing/checkout', {'plan': 'premium'}, content_type='application/json')
    assert other.status_code == 201 and other.json()['amount'] == 60_000
    plan_settings.save('plus', {'price_uzs': 25_000})
    repriced = client.post('/api/v1/billing/checkout', {'plan': 'plus'}, content_type='application/json')
    assert repriced.status_code == 201 and repriced.json()['amount'] == 25_000 and Checkout.objects.count() == 3


def test_a_discount_is_what_inpay_is_asked_for_and_buys_thirty_days(bank):
    switch_on()
    until = timezone.localdate() + timedelta(days=3)
    plan_settings.save('plus', {'price_uzs': 20_000, 'discount_price_uzs': 15_000, 'discount_until': until.isoformat()})
    account = customer()
    row, _ = checkout.create(account, 'plus', 'web')
    assert (row.amount, row.regular_amount) == (15_000, 20_000) and bank.payments[row.provider_id]['amount'] == 15_000
    bank.pay(row.provider_id)
    checkout.refresh(row, force=True)
    period = SubscriptionPeriod.objects.get()
    assert period.ends_at - period.starts_at == timedelta(days=30)
    assert Payment.objects.get().invoice.snapshot['discounted'] is True


def test_a_plan_bought_while_one_runs_follows_it_and_a_higher_one_starts_at_once(bank):
    switch_on(card=True)
    account = customer()
    paid(account, 'plus')  # by card transfer
    held = SubscriptionPeriod.objects.get()
    row, _ = checkout.create(account, 'plus', 'web')
    bank.pay(row.provider_id)
    checkout.refresh(row, force=True)
    follow = SubscriptionPeriod.objects.exclude(pk=held.pk).get()
    assert follow.starts_at == held.ends_at and Payment.objects.get(provider='inpay').is_renewal is True
    # The subscription runs to the end of the last period, whoever was paid.
    assert Subscription.objects.get().current_period_end == follow.ends_at
    higher, _ = checkout.create(account, 'premium', 'web')
    bank.pay(higher.provider_id)
    checkout.refresh(higher, force=True)
    assert effective_plan(account) == 'premium'


# ---------------------------------------------------------------- what never grants a plan


def test_a_webhook_alone_grants_nothing(bank):
    """Anyone can post "paid" to a public address. Only inPAY's own answer counts."""
    switch_on(signing='')  # no signing secret saved: unsigned webhooks are listened to
    account = customer()
    row, _ = checkout.create(account, 'plus', 'web')
    # inPAY still says the payment is waiting.
    assert post_webhook(event(row.provider_id)).status_code == 200
    row.refresh_from_db()
    assert row.status == 'pending' and effective_plan(account) == 'free' and not Payment.objects.exists()
    # About a payment that is not ours: taken, nothing asked.
    asked = bank.count('GET', '/api/v2/payments/')
    assert post_webhook(event('f' * 16)).status_code == 200
    assert bank.count('GET', '/api/v2/payments/') == asked


def test_an_unsigned_webhook_still_gets_a_real_payment_through(bank):
    switch_on(signing='')
    account = customer()
    row, _ = checkout.create(account, 'plus', 'web')
    bank.pay(row.provider_id)
    assert post_webhook(event(row.provider_id)).status_code == 200
    assert effective_plan(account) == 'plus'


def test_an_unsigned_webhook_cannot_make_us_ask_inpay_without_end(bank):
    switch_on(signing='')
    row, _ = checkout.create(customer(), 'plus', 'web')
    assert post_webhook(event(row.provider_id)).status_code == 200
    asked = bank.count('GET', '/api/v2/payments/')
    # Asked a moment ago: "again later", and inPAY is left alone.
    assert post_webhook(event(row.provider_id)).status_code == 503
    assert bank.count('GET', '/api/v2/payments/') == asked


def test_a_wrong_or_old_signature_is_turned_away(bank):
    switch_on()
    account = customer()
    row, _ = checkout.create(account, 'plus', 'web')
    bank.pay(row.provider_id)
    asked = len(bank.calls)
    raw = event(row.provider_id)
    assert post_webhook(raw).status_code == 401
    assert post_webhook(raw, HTTP_X_INPAY_SIGNATURE=signature(raw, secret='whsec_someone_elses')).status_code == 401
    assert post_webhook(raw, HTTP_X_INPAY_SIGNATURE=signature(raw, at=time.time() - 3600)).status_code == 401
    # Signed for another body.
    assert post_webhook(raw + b' ', HTTP_X_INPAY_SIGNATURE=signature(raw)).status_code == 401
    assert len(bank.calls) == asked and effective_plan(account) == 'free'
    assert post_webhook(raw, HTTP_X_INPAY_SIGNATURE=signature(raw)).status_code == 200
    assert effective_plan(account) == 'plus'


@pytest.mark.parametrize('change,problem', [({'amount': 1_000}, 'amount_mismatch'), ({'currency': 'USD'}, 'currency_mismatch'),
                                             ({'livemode': False}, 'mode_mismatch'),
                                             ({'metadata': {'checkout': 'someone-elses'}}, 'reference_mismatch')])
def test_a_payment_that_does_not_match_grants_nothing_and_goes_to_the_owner(bank, change, problem):
    switch_on()
    account = customer()
    row, _ = checkout.create(account, 'premium', 'web')
    bank.pay(row.provider_id, **change)
    assert signed_webhook(row.provider_id).status_code == 200
    row.refresh_from_db()
    assert (row.status, row.failure) == ('review', problem)
    assert effective_plan(account) == 'free' and not Payment.objects.exists() and not PaymentNotice.objects.exists()
    alert = StaffAlert.objects.get()
    assert alert.kind == 'inpay_review' and problem in alert.text
    # The customer is not told of a failure: it is the owner's to look at.
    assert signed_in(account).get(f'/api/v1/billing/checkout/{row.id}').json()['status'] == 'pending'
    signed_webhook(row.provider_id)
    assert StaffAlert.objects.count() == 1


def test_a_test_key_is_for_the_owner_alone_and_grants_nothing(bank):
    switch_on(key=TEST, signing='')
    stranger, owner = customer(7002), customer(OWNER)
    assert checkout.availability(stranger) == {'available': False} and checkout.availability() == {'available': False}
    assert signed_in(stranger).get('/api/v1/billing/manual').json()['automatic'] == {'available': False}
    with pytest.raises(DomainError) as refused:
        checkout.create(stranger, 'plus', 'web')
    assert refused.value.code == 'checkout_disabled'
    # The public pricing page does not announce a way to pay that customers do not have.
    assert signed_in(stranger).get('/api/v1/plans').json()['checkout']['automatic'] is False

    client = signed_in(owner)
    assert client.get('/api/v1/billing/manual').json()['automatic'] == {'available': True, 'provider': 'inpay', 'test': True}
    opened = client.post('/api/v1/billing/checkout', {'plan': 'premium'}, content_type='application/json').json()
    assert opened['test'] is True
    row = Checkout.objects.get()
    assert row.livemode is False
    bank.pay(row.provider_id)
    assert post_webhook(event(row.provider_id)).status_code == 200
    row.refresh_from_db()
    # Paid, as far as the wiring goes; no money moved, so no plan, no revenue.
    assert row.status == 'paid' and row.payment_id is None
    assert effective_plan(owner) == 'free' and not Payment.objects.exists() and not StaffAlert.objects.exists()
    assert list(PaymentNotice.objects.values_list('kind', flat=True)) == ['paid_test']


def test_a_live_answer_to_a_test_payment_and_the_other_way_round_are_never_paid_out(bank):
    """A key that is not what its name says: the customer is never sent to that page."""
    switch_on()
    bank_answer = bank.__call__

    def lying(method, path, **request):
        status, parsed = bank_answer(method, path, **request)
        if path == '/api/v2/payments/' and method == 'POST':
            parsed = {**parsed, 'data': {**parsed['data'], 'livemode': False}}
        return status, parsed
    inpay._call = lying
    with pytest.raises(DomainError) as refused:
        checkout.create(customer(), 'plus', 'web')
    assert refused.value.code == 'checkout_unavailable'
    assert Checkout.objects.get().failure == 'mode_mismatch'


# ---------------------------------------------------------------- when inPAY is away, or late


def test_inpay_not_answering_is_said_so_and_can_be_tried_again(bank):
    switch_on()
    account = customer()
    client = signed_in(account)
    bank.down = True
    failed = client.post('/api/v1/billing/checkout', {'plan': 'plus'}, content_type='application/json')
    assert failed.status_code == 503 and failed.json()['error']['code'] == 'checkout_unavailable'
    assert failed.json()['error']['retryable'] is True
    assert Checkout.objects.get().status == 'failed' and not StaffAlert.objects.exists()
    assert client.get('/api/v1/billing/manual').json()['checkout']['status'] == 'failed'
    bank.down = False
    assert client.post('/api/v1/billing/checkout', {'plan': 'plus'}, content_type='application/json').status_code == 201


def test_inpay_refusing_tells_the_owner_once(bank):
    switch_on()
    bank.refuse = 'domain_not_whitelisted'
    for uid in (7001, 7002):
        with pytest.raises(DomainError) as refused:
            checkout.create(customer(uid), 'plus', 'web')
        assert refused.value.code == 'checkout_unavailable'
    alert = StaffAlert.objects.get()
    assert alert.kind == 'inpay_refused' and 'domain_not_whitelisted' in alert.text
    assert set(Checkout.objects.values_list('failure', flat=True)) == {'refused:domain_not_whitelisted'}


def test_a_webhook_we_cannot_check_is_asked_for_again(bank):
    switch_on()
    account = customer()
    row, _ = checkout.create(account, 'plus', 'web')
    bank.pay(row.provider_id)
    bank.down = True
    assert signed_webhook(row.provider_id).status_code == 503
    assert effective_plan(account) == 'free'
    bank.down = False
    assert signed_webhook(row.provider_id).status_code == 200
    assert effective_plan(account) == 'plus'


def test_the_periodic_check_finds_a_payment_whose_webhook_never_came(bank):
    switch_on()
    account = customer()
    row, _ = checkout.create(account, 'plus', 'web')
    bank.pay(row.provider_id)
    now = timezone.now()
    # Too fresh to bother inPAY about: the webhook is on its way.
    assert checkout.housekeeping(now + timedelta(seconds=30))['asked'] == 0
    assert checkout.housekeeping(now + timedelta(minutes=3))['asked'] == 1
    assert effective_plan(account) == 'plus'
    assert checkout.housekeeping(now + timedelta(minutes=10))['asked'] == 0


def test_the_periodic_check_asks_about_a_few_payments_a_run_and_backs_off(bank):
    switch_on()
    rows = [checkout.create(customer(7100 + i), 'plus', 'web')[0] for i in range(5)]
    now = timezone.now()
    assert checkout.housekeeping(now + timedelta(minutes=3))['asked'] == checkout.RECONCILE_BATCH
    assert checkout.housekeeping(now + timedelta(minutes=4))['asked'] == 2
    Checkout.objects.update(checked_at=now + timedelta(minutes=4))
    # Asked lately: left alone until the wait has passed, which grows with the payment's age.
    assert checkout.housekeeping(now + timedelta(minutes=6))['asked'] == 0
    assert checkout.housekeeping(now + timedelta(minutes=10))['asked'] == checkout.RECONCILE_BATCH
    Checkout.objects.update(checked_at=now + timedelta(hours=2))
    assert checkout.housekeeping(now + timedelta(hours=2, minutes=10))['asked'] == 0
    closed = checkout.housekeeping(now + timedelta(hours=25))
    assert closed['expired'] == 5 and {row.status for row in Checkout.objects.all()} == {'expired'}
    assert len(rows) == 5


def test_money_taken_after_we_stopped_waiting_still_buys_the_plan(bank):
    switch_on()
    account = customer()
    row, _ = checkout.create(account, 'plus', 'web')
    bank.payments[row.provider_id]['status'] = 'failed'
    checkout.refresh(row, force=True)
    row.refresh_from_db()
    assert (row.status, row.failure) == ('failed', 'payment_failed')
    # The customer tried another card on the same page, and it went through.
    bank.pay(row.provider_id)
    assert signed_webhook(row.provider_id).status_code == 200
    assert effective_plan(account) == 'plus'

    late, _ = checkout.create(customer(7002), 'premium', 'web')
    Checkout.objects.filter(pk=late.pk).update(status='expired')
    bank.pay(late.provider_id)
    assert signed_webhook(late.provider_id).status_code == 200
    late.refresh_from_db()
    assert late.status == 'paid' and effective_plan(late.account) == 'premium'


def test_a_waiting_page_asks_inpay_far_less_often_than_it_asks_us(bank):
    switch_on()
    account = customer()
    row, _ = checkout.create(account, 'plus', 'web')
    client = signed_in(account)
    for _ in range(5):
        assert client.get(f'/api/v1/billing/checkout/{row.id}').json()['status'] == 'pending'
    assert bank.count('GET', '/api/v2/payments/') == 1
    Checkout.objects.filter(pk=row.pk).update(checked_at=timezone.now() - timedelta(seconds=11))
    client.get(f'/api/v1/billing/checkout/{row.id}')
    assert bank.count('GET', '/api/v2/payments/') == 2


# ---------------------------------------------------------------- who may see what


def test_the_payment_page_is_given_only_to_the_customer_who_opened_it(bank):
    switch_on()
    account = customer()
    row, _ = checkout.create(account, 'plus', 'web')
    from django.test import Client
    assert signed_in(account).get(f'/api/v1/billing/checkout/{row.id}').json()['checkout_url'].startswith('https://inpay.uz/')
    for stranger in (Client(), signed_in(customer(7002))):
        shown = stranger.get(f'/api/v1/billing/checkout/{row.id}').json()
        assert shown['checkout_url'] is None and shown['status'] == 'pending'
    missing = Client().get(f'/api/v1/billing/checkout/{secrets.token_hex(4)}-0000-4000-8000-000000000000')
    assert missing.status_code == 404
    assert Client().post('/api/v1/billing/checkout', {'plan': 'plus'}, content_type='application/json').status_code == 401


def test_a_payment_from_the_bot_points_back_to_the_bot(bank):
    switch_on()
    save_config('telegram', {'username': 'docmaster_bot', 'webapp_url': 'https://docmaster.live/en/app'})
    row, _ = checkout.create(customer(), 'plus', 'bot')
    from django.test import Client
    shown = Client().get(f'/api/v1/billing/checkout/{row.id}').json()
    assert shown['channel'] == 'bot' and shown['bot_url'] == 'https://t.me/docmaster_bot'
    remote = bank.payments[row.provider_id]
    assert remote['return_url'] == f'https://docmaster.live/en/app/pay/{row.id}'
    assert remote['webhook_url'] == 'https://docmaster.live/api/v1/webhooks/inpay'


def test_invalid_plans_and_get_on_the_webhook_are_refused(bank):
    switch_on()
    client = signed_in(customer())
    assert client.post('/api/v1/billing/checkout', {'plan': 'free'}, content_type='application/json').status_code == 400
    from django.test import Client
    assert Client().get('/api/v1/webhooks/inpay').status_code == 405
    assert post_webhook(b'not json', HTTP_X_INPAY_SIGNATURE=signature(b'not json')).status_code == 400


# ---------------------------------------------------------------- money, refunds, reminders


def test_a_refund_recorded_by_the_owner_takes_the_plan_back(bank):
    switch_on()
    account = customer()
    row, _ = checkout.create(account, 'plus', 'web')
    bank.pay(row.provider_id)
    checkout.refresh(row, force=True)
    client, _ = staff_client('Finance')
    payment = Payment.objects.get()
    page = client.get(f'/ops/payments/{payment.id}?lang=en').content.decode()
    assert 'inPAY' in page and row.provider_id in page and 'data-testid="inpay-refund"' in page
    assert client.post(f'/ops/payments/{payment.id}?lang=en', {'action': 'refund'}).status_code == 302
    row.refresh_from_db()
    assert row.status == 'refunded' and effective_plan(account) == 'free'
    assert 'data-testid="inpay-refund"' not in client.get(f'/ops/payments/{payment.id}?lang=en').content.decode()
    # A refunded payment stays refunded whatever inPAY repeats.
    assert signed_webhook(row.provider_id).status_code == 200
    assert effective_plan(account) == 'free' and Payment.objects.count() == 1


def test_inpay_money_is_in_the_finance_totals(bank):
    from django.test import RequestFactory
    from apps.core.identity import resolve_account
    from operations.commerce_views import financial_report
    from operations.metrics import Filters
    switch_on(card=True)
    # Real accounts: the finance pages leave test accounts out of production's money.
    by_card = resolve_account({'id': 7101, 'first_name': 'Card', 'language_code': 'en'}, is_test=False)
    online = resolve_account({'id': 7102, 'first_name': 'Online', 'language_code': 'en'}, is_test=False)
    paid(by_card, 'premium')
    row, _ = checkout.create(online, 'plus', 'web')
    bank.pay(row.provider_id)
    checkout.refresh(row, force=True)
    totals = financial_report(Filters.from_request(RequestFactory().get('/ops/payments')))['totals']
    assert (totals['uzs_gross'], totals['payers'], totals['paid'], totals['first']) == (80_000, 2, 2, 2)
    client, _ = staff_client('Finance')
    page = client.get('/ops/payments?lang=en').content.decode()
    assert "So&#x27;m received" in page and 'card transfers)' not in page
    assert f'/ops/payments/{Payment.objects.get(provider="inpay").id}' in page


def test_a_plan_bought_through_inpay_is_reminded_before_it_ends(bank):
    switch_on()
    account = customer()
    row, _ = checkout.create(account, 'plus', 'web')
    bank.pay(row.provider_id)
    checkout.refresh(row, force=True)
    end = SubscriptionPeriod.objects.get().ends_at
    checkout.housekeeping(end - timedelta(days=10))
    assert not PaymentNotice.objects.filter(kind='renewal_reminder').exists()
    checkout.housekeeping(end - timedelta(days=2))
    checkout.housekeeping(end - timedelta(days=1))
    assert PaymentNotice.objects.filter(kind='renewal_reminder', checkout=row).count() == 1


def test_the_cleanup_run_looks_after_inpay_payments_and_survives_inpay_being_away(bank):
    from apps.core.services import cleanup_expired
    switch_on()
    account = customer()
    row, _ = checkout.create(account, 'plus', 'web')
    Checkout.objects.filter(pk=row.pk).update(created_at=timezone.now() - timedelta(minutes=5))
    bank.down = True
    cleanup_expired()
    bank.down = False
    bank.pay(row.provider_id)
    Checkout.objects.filter(pk=row.pk).update(checked_at=timezone.now() - timedelta(minutes=6))
    cleanup_expired()
    assert effective_plan(account) == 'plus'


# ---------------------------------------------------------------- the classic API


def switch_on_v1():
    configure_card(enabled=False)
    save_config('telegram', {'webapp_url': 'https://docmaster.live/en/app'})
    save_config('inpay', {'merchant_id': MERCHANT, 'merchant_token': MERCHANT_TOKEN, 'enabled': 'true'})


def test_the_classic_api_takes_a_payment_the_same_way(bank):
    switch_on_v1()
    cfg = inpay_config()
    assert (cfg['api'], cfg['live'], cfg['ready']) == ('v1', True, True)
    account = customer()
    client = signed_in(account)
    opened = client.post('/api/v1/billing/checkout', {'plan': 'plus'}, content_type='application/json').json()
    row = Checkout.objects.get()
    assert row.api == 'v1' and opened['checkout_url'] == f'https://inpay.uz/checkout/{row.provider_id}'
    assert bank.payments[row.provider_id]['callback_url'] == 'https://docmaster.live/api/v1/webhooks/inpay'
    # Its webhook carries no signature and its own word for the status: still only a reason to ask.
    v1_event = json.dumps({'amount': '20000.00', 'status': 'success', 'order_id': row.provider_id, 'transaction_id': 149}).encode()
    assert post_webhook(v1_event).status_code == 200
    assert effective_plan(account) == 'free'
    bank.pay(row.provider_id)
    Checkout.objects.filter(pk=row.pk).update(checked_at=None)
    assert post_webhook(v1_event).status_code == 200
    assert effective_plan(account) == 'plus' and Payment.objects.get().provider_charge_id == f'inpay:{row.provider_id}'
    # One bearer token serves every call of the day.
    assert bank.count('GET', '/api/v1/authorization/') == 1


def test_a_bearer_token_inpay_no_longer_takes_is_fetched_again(bank):
    from django.core.cache import caches
    switch_on_v1()
    caches['limits'].set(inpay._bearer_key(inpay_config()), 'yesterdays-token', 60)
    row, _ = checkout.create(customer(), 'plus', 'web')
    assert row.status == 'pending' and bank.count('GET', '/api/v1/authorization/') == 1


def test_the_classic_api_is_asked_three_times_less_often(bank):
    switch_on_v1()
    row, _ = checkout.create(customer(), 'plus', 'web')
    now = timezone.now()
    assert checkout._gap(row, now) == 30
    row.api = 'v2'
    assert checkout._gap(row, now) == 10 and checkout._gap(row, now + timedelta(minutes=5)) == 30


# ---------------------------------------------------------------- the provider's words


def test_signatures_and_webhook_shapes():
    raw = b'{"a":1}'
    assert inpay.signature_ok(SIGNING, signature(raw), raw)
    assert not inpay.signature_ok(SIGNING, signature(raw), raw + b'x')
    assert not inpay.signature_ok('', signature(raw), raw)
    assert not inpay.signature_ok(SIGNING, 'garbage', raw) and not inpay.signature_ok(SIGNING, '', raw)
    assert not inpay.signature_ok(SIGNING, signature(raw, at=time.time() + 3600), raw)
    v2 = {'object': 'event', 'type': 'payment.succeeded', 'data': {'object': {'id': '47907909afd21a28'}}}
    assert inpay.webhook_payment(v2) == '47907909afd21a28'
    assert inpay.webhook_payment({**v2, 'type': 'subscription.created'}) is None
    assert inpay.webhook_payment({'order_id': '1ff2f5a6d66f6e9c', 'status': 'success'}) == '1ff2f5a6d66f6e9c'
    assert inpay.webhook_payment({'order_id': '../../etc'}) is None and inpay.webhook_payment([]) is None


def test_only_inpays_own_https_page_is_ever_handed_to_a_customer(bank):
    switch_on()
    answer = bank.__call__
    for page in ('http://inpay.uz/checkout/x', 'https://inpay.uz.evil.example/checkout/x', 'https://user@inpay.uz/x', ''):
        def elsewhere(method, path, page=page, **request):
            status, parsed = answer(method, path, **request)
            if method == 'POST':
                parsed = {**parsed, 'data': {**parsed['data'], 'checkout_url': page}}
            return status, parsed
        inpay._call = elsewhere
        with pytest.raises(DomainError):
            checkout.create(customer(), 'plus', 'web')
    assert not Checkout.objects.exclude(checkout_url='').exists()
    assert inpay._secure_page('https://pay.inpay.uz/checkout/1') and inpay._whole('15000.00') == 15000
    assert inpay._whole('15000.50') is None and inpay._whole(None) is None


# ---------------------------------------------------------------- the admin's settings


def test_keys_are_checked_when_saved_and_never_shown(bank):
    configure_card()
    for bad, code in (({'secret_key': 'pk_live_nope'}, 'invalid_inpay_key'), ({'secret_key': MERCHANT_TOKEN}, 'invalid_inpay_key'),
                      ({'secret_key': LIVE, 'webhook_secret': 'nope'}, 'invalid_inpay_webhook_secret'),
                      ({'merchant_id': 'abc'}, 'invalid_inpay_merchant'), ({'enabled': 'true'}, 'inpay_not_configured')):
        with pytest.raises(DomainError) as refused:
            save_config('inpay', bad)
        assert refused.value.code == code
    save_config('telegram', {'webapp_url': 'https://docmaster.live/en/app'})
    client, _ = staff_client('Administrator')
    saved = client.post('/ops/integrations?lang=en', {'integration': 'inpay', 'action': 'save', 'secret_key': TEST,
                                                      'enabled': 'true'})
    assert saved.status_code == 302
    page = client.get('/ops/integrations?lang=en').content.decode()
    assert TEST not in page and 'Test: only you see it' in page and 'https://docmaster.live/api/v1/webhooks/inpay' in page
    # A blank field keeps the key; another key drops the signing secret that belonged to the old one.
    save_config('inpay', {'webhook_secret': SIGNING, 'enabled': 'true'})
    assert inpay_config()['secret_key'] == TEST and inpay_config()['webhook_secret'] == SIGNING
    save_config('inpay', {'secret_key': LIVE, 'enabled': 'true'})
    assert inpay_config()['live'] is True and inpay_config()['webhook_secret'] == ''
    # Test connection proves the key and, with a live one, fetches the signing secret.
    tested = client.post('/ops/integrations?lang=en', {'integration': 'inpay', 'action': 'test'})
    assert tested.status_code == 302 and 'inpay_connected' in tested['Location']
    assert inpay_config()['webhook_secret'] == SIGNING
    page = client.get('/ops/integrations?lang=en').content.decode()
    assert LIVE not in page and SIGNING not in page and 'Live: real payments' in page
    save_config('inpay', {'remove_secret_key': 'true', 'enabled': 'false'})
    assert inpay_config()['configured'] is False


def test_a_key_inpay_does_not_take_fails_the_connection_test(bank):
    save_config('inpay', {'secret_key': 'sk_live_not_the_right_one'})
    with pytest.raises(DomainError) as refused:
        check_inpay()
    assert refused.value.code == 'inpay_connection_failed'
    assert finance  # the staff helpers above are what the admin tests sign in with


def test_a_webhook_signed_with_another_secret_tells_the_owner_once(bank):
    switch_on()
    row, _ = checkout.create(customer(), 'plus', 'web')
    raw = event(row.provider_id)
    for _ in range(3):
        assert post_webhook(raw, HTTP_X_INPAY_SIGNATURE=signature(raw, secret='whsec_rotated_elsewhere')).status_code == 401
    assert StaffAlert.objects.get().kind == 'inpay_signature'
    # No signature at all is the internet knocking, not news.
    StaffAlert.objects.all().delete()
    assert post_webhook(raw).status_code == 401 and not StaffAlert.objects.exists()


def test_inpay_is_never_followed_to_another_address(monkeypatch):
    """The key is in a header: a redirect is an answer to refuse, not somewhere to send it."""
    import io
    import urllib.error
    from urllib.request import Request
    handler = inpay._NoRedirect()
    assert handler.redirect_request(Request('https://inpay.uz/api/v2/balance/'), None, 302, 'Found', {}, 'https://elsewhere.example/') is None

    class Redirected:
        def open(self, request, timeout):
            raise urllib.error.HTTPError(request.full_url, 302, 'Found', {}, io.BytesIO(b'{}'))
    monkeypatch.setattr(inpay, '_opener', Redirected())
    with pytest.raises(inpay.Refused) as refused:
        inpay._answer(*REAL_CALL('GET', '/api/v2/balance/', headers={'Authorization': 'Bearer ' + LIVE}))
    assert refused.value.code == 'http_302'


def test_a_gateway_page_or_a_dead_line_is_inpay_being_away(monkeypatch):
    import io

    class Answers:
        def __init__(self, body=None, error=None):
            self.body, self.error = body, error

        def open(self, request, timeout):
            if self.error:
                raise self.error
            response = io.BytesIO(self.body)
            response.status = 200
            response.__enter__ = lambda *a: response
            response.__exit__ = lambda *a: False
            return response
    for opener in (Answers(b'<html>502 Bad Gateway</html>'), Answers(b'[1, 2]'), Answers(error=TimeoutError())):
        monkeypatch.setattr(inpay, '_opener', opener)
        with pytest.raises(inpay.Unavailable):
            REAL_CALL('GET', '/api/v2/balance/')
    for status, parsed in ((429, {'success': False, 'error': {'code': 'rate_limited'}}), (500, {'success': False}),
                           (400, {'success': False, 'error_code': 'RATE_LIMIT_EXCEEDED'})):
        with pytest.raises(inpay.Unavailable):
            inpay._answer(status, parsed)
    with pytest.raises(inpay.Refused) as refused:
        inpay._answer(403, {'success': False, 'error': {'code': 'merchant_inactive'}})
    assert refused.value.code == 'merchant_inactive'
