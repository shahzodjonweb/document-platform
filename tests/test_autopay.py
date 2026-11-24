"""Saved cards and monthly renewal through inPAY's Avto to'lov: what is charged, when, and what never is.

inPAY is a fake here (`FakeAvto`): the payments of tests/test_inpay_checkout.py,
plus Avto to'lov's signed card API, which it checks the way inPAY documents it.
"""
import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.commerce import autopay, inpay
from apps.commerce.models import AutoRenewal, CardCharge, CommerceAction, PaymentNotice, SavedCard, SubscriptionPeriod
from apps.commerce.services import effective_plan
from apps.core.errors import DomainError
from apps.core.models import StaffAlert
from operations.integrations import inpay_config, save_config
from tests.test_inpay_checkout import BOT_LIVE, FakeInpay, OWNER, switch_on
from tests.test_manual_payments import customer, signed_in, staff_client

pytestmark = pytest.mark.django_db
AP_KEY, AP_SECRET = 'ap_7c41d0e9b2', 'Avto-secret_9f2c41d0e9b27a65c3'
# The website's kassa has its own Avto to'lov key.
WEB_AP_KEY, WEB_AP_SECRET = 'ap_2e90b7c1f4', 'Avto-secret_web_3d7a1c95e0b24f68'
AP_KEYS = {AP_KEY: AP_SECRET, WEB_AP_KEY: WEB_AP_SECRET}


class FakeAvto(FakeInpay):
    """inPAY with Avto to'lov: cards saved on its page, charged by id, every request signed.

    Each kassa signs with its own key, and a card belongs to the kassa whose
    key saved it: through another kassa it is unknown (CARD_STATE), as inPAY's
    card ids mean something to one kassa alone.
    """

    def __init__(self):
        super().__init__()
        self.cards, self.charges, self.nonces, self.signed, self.keys = {}, {}, set(), [], []
        self.next_card, self.next_charge = 128, 4400
        self.decline = None  # an error code for the next charges
        self.lose = 0  # how many charge answers to lose after charging
        self.paid_amount = None  # an amount inPAY reports other than the one asked

    def save(self, card_id, consent_max=None, masked='860038******1234'):
        """The customer finishes inPAY's page: the card is saved."""
        self.cards[card_id].update(status='active', masked_pan=masked, expiry='09/29', mandate_id=f'MND-{card_id}',
                                   consent_max=consent_max)

    def cancel(self, card_id):
        """The customer takes the card away on inpay.uz/kartam."""
        self.cards[card_id]['status'] = 'removed'

    def __call__(self, method, path, *, headers=None, body=None, query=None, raw=None):
        if not path.startswith('/api/v1/cards/'):
            return super().__call__(method, path, headers=headers, body=body, query=query)
        self.calls.append((method, path))
        if self.down:
            raise inpay.Unavailable()
        headers, raw = headers or {}, raw or b''
        stamp, nonce = headers.get('X-Inpay-Timestamp', ''), headers.get('X-Inpay-Nonce', '')
        base = f'{method}\n{path}\n{stamp}\n{nonce}\n{hashlib.sha256(raw).hexdigest()}'
        key = headers.get('X-Inpay-Key')
        expected = hmac.new(AP_KEYS.get(key, '').encode(), base.encode(), hashlib.sha256).hexdigest()
        if key not in AP_KEYS or headers.get('X-Inpay-Signature') != expected:
            return 401, {'success': False, 'error_code': 'SIGNATURE'}
        if nonce in self.nonces:
            return 401, {'success': False, 'error_code': 'NONCE'}
        self.nonces.add(nonce)
        self.signed.append((method, path, query))
        body = json.loads(raw) if raw else {}
        action = path.rsplit('/', 1)[1]
        self.keys.append((action, key))
        if action == 'bind':
            card_id, self.next_card = self.next_card, self.next_card + 1
            self.cards[card_id] = {'id': card_id, 'customer_ref': body['customer_ref'], 'status': 'pending', 'masked_pan': '',
                                   'expiry': '', 'mandate_id': '', 'consent_max': None, 'return_url': body.get('return_url'),
                                   'key': key}
            return 200, {'success': True, 'data': {'card_id': card_id, 'bind_ref': 'b' * 32, 'need_code': True,
                                                   'form_url': f'https://inpay.uz/cards/bind/70518/{card_id:032d}'}}
        if action == 'list':
            mine = [{name: value for name, value in card.items() if name != 'key'} for card in self.cards.values()
                    if card['customer_ref'] == query['customer_ref'] and card['key'] == key]
            return 200, {'success': True, 'data': {'cards': mine}}
        if action == 'remove':
            if self.cards.get(body['card_id'], {}).get('key') != key:
                return 400, {'success': False, 'error_code': 'CARD_STATE'}
            self.cards[body['card_id']]['status'] = 'removed'
            return 200, {'success': True, 'data': {'card_id': body['card_id'], 'status': 'removed'}}
        if action == 'charge':
            assert len(body['reason']) >= 5 and body['idem_key'] and body['amount'] >= 1000
            if body['idem_key'] in self.charges:
                return 200, self.charges[body['idem_key']]
            card = self.cards.get(body['card_id'])
            if card is None or card['status'] != 'active' or card['key'] != key:
                return 400, {'success': False, 'error_code': 'CARD_STATE'}
            if card['consent_max'] and body['amount'] > card['consent_max']:
                return 400, {'success': False, 'error_code': 'CONSENT_LIMIT'}
            if self.decline:
                return (402 if self.decline == 'CHARGE_FAILED' else 400), {'success': False, 'error_code': self.decline}
            charge_id, self.next_charge = self.next_charge, self.next_charge + 1
            answer = {'success': True, 'data': {'charge_id': charge_id, 'status': 'success',
                                                'amount': self.paid_amount or body['amount'], 'provider_ref': f'PLM-{charge_id}',
                                                'mandate_id': card['mandate_id']}}
            self.charges[body['idem_key']] = answer
            if self.lose:
                self.lose -= 1
                raise inpay.Unavailable()
            return 200, answer
        raise AssertionError(f'Avto to\'lov was asked something this fake does not know: {method} {path}')

    def charged(self):
        return len(self.charges)


@pytest.fixture
def bank(monkeypatch):
    fake = FakeAvto()
    monkeypatch.setattr(inpay, '_call', fake)
    return fake


def autopay_on(audience='everyone', card=True):
    """The bot's kassa with its payments and Avto to'lov switched on."""
    switch_on(kassa='bot', card=card)
    save_config('inpay_bot', {'enabled': 'true', 'autopay_enabled': 'true', 'autopay_key_id': AP_KEY,
                              'autopay_secret': AP_SECRET, 'autopay_audience': audience})


def web_autopay_on(audience='everyone'):
    """The website's kassa with its payments and its own Avto to'lov key switched on."""
    switch_on(kassa='web', card=True)
    save_config('inpay', {'enabled': 'true', 'autopay_enabled': 'true', 'autopay_key_id': WEB_AP_KEY,
                          'autopay_secret': WEB_AP_SECRET, 'autopay_audience': audience})


def saved_card(account, bank, plan='', consent_max=None, channel='bot'):
    """A card the customer saved on inPAY's page (no plan bought with it unless `plan`)."""
    card, request = autopay.begin_binding(account, plan, channel)
    answer, failure = autopay.ask_binding(request)
    card = autopay.complete_binding(card, answer, failure)
    bank.save(card.provider_card_id, consent_max=consent_max)
    cards, _ = autopay.ask_cards(autopay.look_cards(card))
    return autopay.apply_cards(card.pk, cards)


def renewing(account, bank, plan='plus'):
    """A customer who bought `plan` with «Pay and renew every month»."""
    card = saved_card(account, bank, plan)
    row = autopay.finish_saved(card)
    assert row.status == 'paid'
    return AutoRenewal.objects.get(account=account)


# ---------------------------------------------------------------- the API, as inPAY documents it


def test_every_card_request_is_signed_as_inpay_documents(bank, monkeypatch):
    autopay_on()
    seen = []
    monkeypatch.setattr(inpay, '_call', lambda *a, **k: (seen.append((a, k)), bank(*a, **k))[1])
    assert inpay.list_cards(inpay_config('bot'), customer_ref='dm-x') == []
    (method, path), call = seen[0]
    headers = call['headers']
    assert (method, path, call['query']) == ('GET', '/api/v1/cards/list', {'customer_ref': 'dm-x'})
    # HMAC-SHA256 of METHOD\nPATH\nTIMESTAMP\nNONCE\nsha256(body), the query left out; an empty body is hashed too.
    base = f"GET\n/api/v1/cards/list\n{headers['X-Inpay-Timestamp']}\n{headers['X-Inpay-Nonce']}\n{hashlib.sha256(b'').hexdigest()}"
    assert headers['X-Inpay-Signature'] == hmac.new(AP_SECRET.encode(), base.encode(), hashlib.sha256).hexdigest()
    assert headers['X-Inpay-Key'] == AP_KEY and len(headers['X-Inpay-Nonce']) == 24
    # The body sent is the body signed, byte for byte.
    autopay.ask_binding(autopay.begin_binding(customer(), '')[1])
    bind = next(call for (m, p), call in seen if p.endswith('/bind'))
    assert json.loads(bind['raw'])['customer_ref'].startswith('dm-')


def test_a_wrong_secret_is_refused_and_the_owner_told(bank):
    autopay_on()
    save_config('inpay_bot', {'enabled': 'true', 'autopay_enabled': 'true', 'autopay_key_id': AP_KEY,
                              'autopay_secret': 'Avto-secret_wrong_wrong_wrong', 'autopay_audience': 'everyone'})
    with pytest.raises(DomainError) as refused:
        card, request = autopay.begin_binding(customer(), 'plus')
        autopay.complete_binding(card, *autopay.ask_binding(request))
    assert refused.value.code == 'autopay_unavailable'
    assert StaffAlert.objects.get().kind == 'autopay_refused' and 'SIGNATURE' in StaffAlert.objects.get().text


# ---------------------------------------------------------------- saving a card, the first month


def test_a_saved_card_pays_the_first_month_and_turns_renewal_on(bank):
    autopay_on()
    account = customer()
    card, request = autopay.begin_binding(account, 'plus')
    card = autopay.complete_binding(card, *autopay.ask_binding(request))
    remote = bank.cards[card.provider_card_id]
    # Back to the chat afterwards; the card number is typed on inPAY's page, never here.
    assert card.bind_url.startswith('https://inpay.uz/cards/bind/') and remote['return_url'] == f'https://t.me/DocMasterTestBot?start=card_{card.id.hex}'
    assert card.status == 'binding' and effective_plan(account) == 'free'
    # Not saved yet: nothing is charged.
    autopay.housekeeping()
    assert not bank.charged()
    bank.save(card.provider_card_id)
    # The customer never came back: the periodic run finishes it, as they agreed to on the bot's screen.
    autopay.housekeeping(timezone.now() + timedelta(minutes=2))
    card.refresh_from_db()
    assert (card.status, card.masked_pan, card.last4, card.mandate_id) == ('active', '860038******1234', '1234', f'MND-{card.provider_card_id}')
    row = CardCharge.objects.get()
    assert (row.purpose, row.status, row.amount, row.plan) == ('first', 'paid', 20_000, 'plus')
    assert effective_plan(account) == 'plus' and row.payment.provider == 'inpay'
    assert row.payment.provider_charge_id == f'inpay-card:{row.provider_charge_id}'
    period = SubscriptionPeriod.objects.get(payment=row.payment)
    renewal = AutoRenewal.objects.get(account=account)
    assert (renewal.status, renewal.plan, renewal.card_id) == ('on', 'plus', card.id) and renewal.renews_at == period.ends_at
    assert list(PaymentNotice.objects.filter(charge=row).values_list('kind', flat=True)) == ['card_paid']
    assert StaffAlert.objects.get(kind='inpay_card_paid')
    # Asked again, nothing more is charged.
    autopay.housekeeping(timezone.now() + timedelta(minutes=4))
    assert bank.charged() == 1 and CardCharge.objects.count() == 1


def test_a_page_left_open_expires_and_nothing_is_charged(bank):
    autopay_on()
    card, request = autopay.begin_binding(customer(), 'plus')
    autopay.complete_binding(card, *autopay.ask_binding(request))
    SavedCard.objects.update(created_at=timezone.now() - timedelta(minutes=autopay.BIND_MINUTES + 11))
    autopay.housekeeping()
    assert SavedCard.objects.get().status == 'expired' and not bank.charged()


def test_a_card_limit_below_the_price_is_never_charged(bank):
    autopay_on()
    account = customer()
    card = saved_card(account, bank, 'plus', consent_max=10_000)
    row = autopay.finish_saved(card)
    assert (row.status, row.failure) == ('failed', 'CONSENT_LIMIT') and not bank.charged()
    assert effective_plan(account) == 'free' and not AutoRenewal.objects.exists()
    assert PaymentNotice.objects.get(charge=row).kind == 'card_failed'


def test_a_lost_answer_is_asked_again_under_the_same_key_and_charged_once(bank):
    autopay_on()
    account = customer()
    card = saved_card(account, bank, 'plus')
    bank.lose = 1
    row = autopay.finish_saved(card)
    assert row.status == 'unknown' and bank.charged() == 1 and effective_plan(account) == 'free'
    assert not PaymentNotice.objects.exists(), 'the next run says how it went'
    CardCharge.objects.update(created_at=timezone.now() - timedelta(minutes=2))
    autopay.housekeeping()
    row.refresh_from_db()
    assert row.status == 'paid' and bank.charged() == 1 and effective_plan(account) == 'plus'
    assert AutoRenewal.objects.get(account=account).status == 'on'
    assert PaymentNotice.objects.get(charge=row).kind == 'card_paid'


def test_an_amount_inpay_did_not_agree_to_goes_to_the_owner(bank):
    autopay_on()
    account = customer()
    card = saved_card(account, bank, 'plus')
    bank.paid_amount = 15_000
    row = autopay.finish_saved(card)
    assert (row.status, row.failure) == ('review', 'amount_mismatch') and effective_plan(account) == 'free'
    assert StaffAlert.objects.get(kind='autopay_review')


def test_a_double_tap_charges_once(bank):
    autopay_on()
    account = customer()
    card = saved_card(account, bank)
    first = autopay.charge(account, card, 'plus', 'one_tap')
    again = autopay.charge(account, card, 'plus', 'one_tap')
    assert first.pk == again.pk and bank.charged() == 1


# ---------------------------------------------------------------- renewing every month


def test_a_renewal_is_reminded_three_days_ahead_then_charged_on_the_last_day(bank):
    autopay_on()
    account = customer()
    renewal = renewing(account, bank)
    first_end = renewal.renews_at
    # Four days before: nothing yet.
    autopay.housekeeping(first_end - timedelta(days=4))
    assert not PaymentNotice.objects.filter(kind='renewal_upcoming').exists()
    # Three days before: reminded once, and the plain "your plan ends" reminder is not sent.
    from apps.commerce import checkout
    for _ in range(2):
        autopay.housekeeping(first_end - timedelta(days=2))
        checkout.housekeeping(first_end - timedelta(days=2))
    assert PaymentNotice.objects.filter(renewal=renewal, kind='renewal_upcoming').count() == 1
    assert not PaymentNotice.objects.filter(kind='renewal_reminder').exists()
    # Not yet on the last day's morning... then, within its last hours, charged.
    autopay.housekeeping(first_end - timedelta(hours=7))
    assert bank.charged() == 1
    autopay.housekeeping(first_end - timedelta(hours=3))
    assert bank.charged() == 2
    row = CardCharge.objects.get(purpose='renewal')
    assert (row.status, row.amount, row.attempt) == ('paid', 20_000, 1)
    period = SubscriptionPeriod.objects.get(payment=row.payment)
    # The new month follows the old one: nothing paid for is lost.
    assert period.starts_at == first_end and period.ends_at == first_end + timedelta(days=30)
    renewal.refresh_from_db()
    assert renewal.renews_at == period.ends_at and renewal.attempts == 0
    assert PaymentNotice.objects.get(charge=row).kind == 'renewed'
    # The next month is reminded again.
    autopay.housekeeping(period.ends_at - timedelta(days=2))
    assert PaymentNotice.objects.filter(renewal=renewal, kind='renewal_upcoming').count() == 2


def test_a_declined_renewal_is_tried_after_one_and_three_days_then_stops(bank):
    autopay_on()
    account = customer()
    renewal = renewing(account, bank)
    end = renewal.renews_at
    bank.decline = 'CHARGE_FAILED'
    autopay.housekeeping(end - timedelta(hours=3))
    renewal.refresh_from_db()
    assert (renewal.status, renewal.attempts, renewal.next_try_at) == ('on', 1, end + timedelta(days=1))
    assert PaymentNotice.objects.filter(kind='renewal_failed').count() == 1
    # Not before the day after.
    autopay.housekeeping(end + timedelta(hours=12))
    assert CardCharge.objects.filter(purpose='renewal').count() == 1
    autopay.housekeeping(end + timedelta(days=1, minutes=1))
    renewal.refresh_from_db()
    assert (renewal.attempts, renewal.next_try_at) == (2, end + timedelta(days=3))
    autopay.housekeeping(end + timedelta(days=3, minutes=1))
    renewal.refresh_from_db()
    assert (renewal.status, renewal.stopped_reason, renewal.attempts) == ('stopped', 'declined', 3)
    assert list(CardCharge.objects.filter(purpose='renewal').order_by('attempt').values_list('attempt', 'status')) == [
        (1, 'failed'), (2, 'failed'), (3, 'failed')]
    assert PaymentNotice.objects.filter(kind='renewal_failed').count() == 2
    assert PaymentNotice.objects.filter(renewal=renewal, kind='renewal_stopped').count() == 1
    # Stopped is stopped: no new month after the one first paid for.
    bank.decline = None
    autopay.housekeeping(end + timedelta(days=10))
    assert bank.charged() == 1 and SubscriptionPeriod.objects.filter(account=account).count() == 1


def test_a_renewal_that_goes_through_on_a_retry_starts_the_plan_again(bank):
    autopay_on()
    account = customer()
    renewal = renewing(account, bank)
    end = renewal.renews_at
    bank.decline = 'CHARGE_FAILED'
    autopay.housekeeping(end - timedelta(hours=3))
    bank.decline = None
    later = end + timedelta(days=1, minutes=5)
    autopay.housekeeping(later)
    row = CardCharge.objects.get(purpose='renewal', status='paid')
    assert row.attempt == 2
    period = SubscriptionPeriod.objects.get(payment=row.payment)
    assert period.starts_at == later and period.ends_at == later + timedelta(days=30)
    renewal.refresh_from_db()
    assert (renewal.status, renewal.attempts, renewal.renews_at) == ('on', 0, period.ends_at)


def test_a_card_cancelled_at_inpay_stops_renewal_at_once(bank):
    autopay_on()
    account = customer()
    renewal = renewing(account, bank)
    bank.cancel(renewal.card.provider_card_id)
    autopay.housekeeping(renewal.renews_at - timedelta(hours=3))
    renewal.refresh_from_db()
    assert (renewal.status, renewal.stopped_reason) == ('stopped', 'card_removed')
    assert SavedCard.objects.get().status == 'removed'
    assert PaymentNotice.objects.filter(renewal=renewal, kind='renewal_stopped').exists()


def test_inpay_refusing_the_key_is_the_owners_to_fix_and_no_try_is_counted(bank):
    autopay_on()
    account = customer()
    renewal = renewing(account, bank)
    bank.decline = 'LIMIT_MONTH'
    autopay.housekeeping(renewal.renews_at - timedelta(hours=3))
    renewal.refresh_from_db()
    assert (renewal.status, renewal.attempts, renewal.failure) == ('on', 0, 'LIMIT_MONTH')
    assert StaffAlert.objects.filter(kind='autopay_refused').exists()
    assert not PaymentNotice.objects.filter(kind='renewal_failed').exists()


def test_time_paid_for_meanwhile_moves_the_renewal(bank):
    autopay_on()
    account = customer()
    renewal = renewing(account, bank)
    card = renewal.card
    # A month paid in one tap, without renewal: the renewal waits for its end.
    autopay.charge(account, card, 'plus', 'one_tap')
    autopay.housekeeping(renewal.renews_at - timedelta(hours=3))
    renewal.refresh_from_db()
    assert renewal.renews_at == autopay.paid_until(account) and bank.charged() == 2


def test_a_plan_no_longer_sold_is_not_renewed(bank):
    from operations import plans as plan_settings
    autopay_on()
    account = customer()
    renewal = renewing(account, bank)
    plan_settings.save('plus', {'price_uzs': ''})
    autopay.housekeeping(renewal.renews_at - timedelta(hours=3))
    renewal.refresh_from_db()
    assert (renewal.status, renewal.stopped_reason) == ('stopped', 'not_on_sale') and bank.charged() == 1


# ---------------------------------------------------------------- the customer's switches


def test_turning_renewal_off_and_on_and_removing_the_card(bank):
    autopay_on()
    account = customer()
    renewal = renewing(account, bank)
    autopay.turn_off(account)
    autopay.housekeeping(renewal.renews_at - timedelta(hours=3))
    assert bank.charged() == 1 and AutoRenewal.objects.get().status == 'off'
    autopay.turn_on(account)
    assert AutoRenewal.objects.get().status == 'on'
    card = autopay.remove(account, renewal.card_id)
    assert card.status == 'removed' and bank.cards[card.provider_card_id]['status'] == 'removed'
    assert ('POST', '/api/v1/cards/remove', None) in bank.signed
    assert AutoRenewal.objects.get().status == 'stopped'
    autopay.housekeeping(renewal.renews_at - timedelta(hours=3))
    assert bank.charged() == 1
    with pytest.raises(DomainError):
        autopay.turn_on(account)
    assert set(CommerceAction.objects.values_list('action', flat=True)) >= {'card_charge.paid', 'renewal.on', 'renewal.off', 'card.removed'}


def test_a_card_removed_while_inpay_is_away_is_never_charged_and_told_to_inpay_later(bank):
    autopay_on()
    account = customer()
    renewal = renewing(account, bank)
    bank.down = True
    card = autopay.remove(account, renewal.card_id)
    assert card.status == 'removing'
    bank.down = False
    autopay.housekeeping()
    card.refresh_from_db()
    assert card.status == 'removed' and bank.cards[card.provider_card_id]['status'] == 'removed'


def test_saving_a_card_is_offered_to_the_owner_alone_until_switched_to_everyone(bank):
    autopay_on(audience='owner')
    assert autopay.offered(customer(OWNER)) and not autopay.offered(customer(7002))
    with pytest.raises(DomainError):
        autopay.begin_binding(customer(7002), 'plus')
    save_config('inpay_bot', {'enabled': 'true', 'autopay_enabled': 'true', 'autopay_audience': 'everyone'})
    assert autopay.offered(customer(7002))
    # Switched off, nobody is offered it, and renewals wait.
    save_config('inpay_bot', {'enabled': 'true', 'autopay_enabled': 'false'})
    assert not autopay.offered(customer(OWNER))


# ---------------------------------------------------------------- the website, the admin, refunds


def test_the_website_shows_renewal_turns_it_off_and_removes_the_card(bank):
    autopay_on()
    account = customer()
    renewal = renewing(account, bank)
    client = signed_in(account)
    shown = client.get('/api/v1/billing/renewal').json()
    # Saved in the bot: shown and switchable on the website, never charged from it in one tap.
    assert shown['offered'] is False and shown['card']['last4'] == '1234' and shown['card']['here'] is False
    assert shown['renewal']['status'] == 'on' and shown['renewal']['amount'] == 20_000 and shown['can_turn_on'] is False
    off = client.delete('/api/v1/billing/renewal').json()
    assert off['renewal']['status'] == 'off' and off['card'] is not None and off['can_turn_on'] is True
    on = client.post('/api/v1/billing/renewal').json()
    assert on['renewal']['status'] == 'on' and on['can_turn_on'] is False
    client.delete('/api/v1/billing/renewal')
    gone = client.delete(f'/api/v1/billing/cards/{renewal.card_id}').json()
    assert gone['card'] is None and bank.cards[renewal.card.provider_card_id]['status'] == 'removed'
    # Another customer's card is not theirs to remove.
    other = customer(7002)
    theirs = saved_card(other, bank)
    assert client.delete(f'/api/v1/billing/cards/{theirs.id}').status_code == 404
    from django.test import Client
    assert Client().get('/api/v1/billing/renewal').status_code == 401


def test_a_card_saved_on_the_website_pays_for_its_plan_once_and_renews_through_the_websites_kassa(bank):
    autopay_on()
    web_autopay_on()
    account = customer()
    client = signed_in(account)
    assert client.get('/api/v1/billing/renewal').json()['offered'] is True
    opened = client.post('/api/v1/billing/cards', {'plan': 'plus'}, content_type='application/json')
    assert opened.status_code == 201
    state = opened.json()
    card = SavedCard.objects.get()
    assert (card.kassa, state['status'], state['plan'], state['charge']) == ('web', 'binding', 'plus', None)
    assert state['bind_url'].startswith('https://inpay.uz/') and bank.keys == [('bind', WEB_AP_KEY)]
    # inPAY sends the customer back to the website, on the website kassa's own domain.
    assert bank.cards[card.provider_card_id]['return_url'] == f'https://docmaster.live/en/app/card/{card.id}'
    # Back before finishing inPAY's page: still being saved, nothing charged.
    waiting = client.get(f'/api/v1/billing/cards/{card.id}').json()
    assert waiting['status'] == 'binding' and waiting['charge'] is None and bank.charged() == 0
    # Asked again a moment later, inPAY is not asked again.
    asked = len(bank.keys)
    client.get(f'/api/v1/billing/cards/{card.id}')
    assert len(bank.keys) == asked
    bank.save(card.provider_card_id)
    SavedCard.objects.filter(pk=card.pk).update(checked_at=None)
    done = client.get(f'/api/v1/billing/cards/{card.id}').json()
    assert done['status'] == 'active' and done['last4'] == '1234'
    assert done['charge']['status'] == 'paid' and done['charge']['amount'] == 20_000 and done['charge']['renews_at']
    assert effective_plan(account) == 'plus' and ('charge', WEB_AP_KEY) in bank.keys
    # The page asking again, or the periodic run, never charges twice.
    again = client.get(f'/api/v1/billing/cards/{card.id}').json()
    autopay.housekeeping()
    assert again['charge']['id'] == done['charge']['id'] and bank.charged() == 1
    # A receipt in Telegram, as after every charge.
    assert PaymentNotice.objects.filter(charge_id=done['charge']['id'], kind='card_paid').exists()
    shown = client.get('/api/v1/billing/renewal').json()
    assert shown['card']['here'] is True and shown['renewal']['status'] == 'on'
    # The month renews from the website's card, through the website's kassa.
    renewal = AutoRenewal.objects.get()
    assert renewal.card_id == card.id
    autopay.housekeeping(renewal.renews_at - timedelta(hours=3))
    assert bank.charged() == 2 and bank.keys[-1] == ('charge', WEB_AP_KEY)
    # Someone else's card is not theirs to look at.
    assert signed_in(customer(7002)).get(f'/api/v1/billing/cards/{card.id}').status_code == 404


def test_one_tap_on_the_website_charges_only_a_card_saved_there(bank):
    autopay_on()
    web_autopay_on()
    account = customer()
    client = signed_in(account)
    in_bot = saved_card(account, bank)
    refused = client.post(f'/api/v1/billing/cards/{in_bot.id}/charge', {'plan': 'plus'}, content_type='application/json')
    assert refused.status_code == 409 and refused.json()['error']['code'] == 'card_unavailable' and bank.charged() == 0
    # Nor does the bot charge the website's card in one tap.
    on_web = saved_card(account, bank, channel='web')
    assert autopay.active_card(account, 'bot') is None and autopay.active_card(account, 'web') == on_web
    with pytest.raises(DomainError):
        autopay.begin_charge(account, on_web, 'plus', 'one_tap', channel='bot')
    # Saving it replaced the bot's card, which inPAY is told about through the bot's kassa.
    autopay.housekeeping()
    in_bot.refresh_from_db()
    assert in_bot.status == 'removed' and ('remove', AP_KEY) in bank.keys
    paid = client.post(f'/api/v1/billing/cards/{on_web.id}/charge', {'plan': 'plus'}, content_type='application/json').json()
    assert paid['status'] == 'paid' and paid['renews_at'] is None and paid['active_until']
    # A second tap is the first charge.
    twice = client.post(f'/api/v1/billing/cards/{on_web.id}/charge', {'plan': 'plus'}, content_type='application/json').json()
    assert twice['id'] == paid['id'] and bank.charged() == 1 and not AutoRenewal.objects.exists()
    renewed = client.post(f'/api/v1/billing/cards/{on_web.id}/charge', {'plan': 'premium', 'renew': True},
                          content_type='application/json').json()
    assert renewed['status'] == 'paid' and renewed['renews_at'] and AutoRenewal.objects.get().plan == 'premium'
    # A declined charge says why, and the plan stays as it was.
    bank.decline = 'CHARGE_FAILED'
    CardCharge.objects.update(created_at=timezone.now() - timedelta(minutes=5))
    failed = client.post(f'/api/v1/billing/cards/{on_web.id}/charge', {'plan': 'plus'}, content_type='application/json').json()
    assert (failed['status'], failed['reason']) == ('failed', 'declined')
    assert PaymentNotice.objects.filter(charge_id=failed['id'], kind='card_failed').exists()


def test_a_card_saved_in_one_place_replaces_the_other_and_renewal_goes_on_from_it(bank):
    autopay_on()
    web_autopay_on()
    account = customer()
    renewal = renewing(account, bank)
    old = renewal.card
    new = saved_card(account, bank, channel='web')
    renewal.refresh_from_db()
    old.refresh_from_db()
    assert renewal.status == 'on' and renewal.card_id == new.id and old.status == 'removing'
    autopay.housekeeping(renewal.renews_at - timedelta(hours=3))
    old.refresh_from_db()
    assert old.status == 'removed' and bank.charged() == 2 and bank.keys[-1] == ('charge', WEB_AP_KEY)


def test_saving_a_card_on_the_website_needs_the_websites_own_avto_pay(bank):
    autopay_on()
    switch_on(kassa='web', card=True)
    client = signed_in(customer())
    assert client.get('/api/v1/billing/renewal').json()['offered'] is False
    refused = client.post('/api/v1/billing/cards', {'plan': 'plus'}, content_type='application/json')
    assert refused.status_code == 409 and refused.json()['error']['code'] == 'autopay_unavailable'
    assert client.post('/api/v1/billing/cards', {'plan': 'gold'}, content_type='application/json').status_code == 400
    # Shown to the owner alone at first, like the bot's.
    web_autopay_on(audience='owner')
    assert autopay.offered(customer(OWNER), 'web') and not autopay.offered(customer(7003), 'web')
    # Without a saved card there is nothing to renew from.
    without = client.post('/api/v1/billing/renewal')
    assert without.status_code == 409 and without.json()['error']['code'] == 'card_unavailable'
    assert not bank.keys


def test_a_website_card_inpay_could_not_open_alerts_the_owner_under_the_websites_section(bank):
    autopay_on()
    switch_on(kassa='web', card=True)
    save_config('inpay', {'enabled': 'true', 'autopay_enabled': 'true', 'autopay_key_id': 'ap_00000wrong',
                          'autopay_secret': 'Avto-secret_wrong_00000000000', 'autopay_audience': 'everyone'})
    client = signed_in(customer())
    failed = client.post('/api/v1/billing/cards', {'plan': 'plus'}, content_type='application/json')
    assert failed.status_code == 503 and failed.json()['error']['code'] == 'autopay_unavailable'
    alert = StaffAlert.objects.get()
    assert alert.kind == 'autopay_refused_web' and 'Automatic payments on the website (inPAY)' in alert.text


def test_the_admin_saves_the_avto_pay_key_tests_it_and_never_shows_the_secret(bank):
    switch_on(kassa='bot', card=True)
    admin, _ = staff_client('Administrator')
    page = admin.get('/ops/integrations?lang=en').content.decode()
    # One Avto PAY section on each kassa's card.
    assert page.count('data-testid="autopay-settings"') == 2
    assert 'Let website customers save a card' in page and 'Let bot customers save a card' in page
    refused = admin.post('/ops/integrations', {'integration': 'inpay_bot', 'action': 'save', 'enabled': 'true',
                                               'autopay_enabled': 'true', 'autopay_key_id': '', 'autopay_audience': 'owner'})
    assert refused.status_code == 200 and 'Save the Avto PAY key ID and secret' in refused.content.decode()
    saved = admin.post('/ops/integrations', {'integration': 'inpay_bot', 'action': 'save', 'enabled': 'true',
                                             'autopay_enabled': 'true', 'autopay_key_id': AP_KEY, 'autopay_secret': AP_SECRET,
                                             'autopay_audience': 'owner'})
    assert saved.status_code == 302
    cfg = inpay_config('bot')
    assert cfg['autopay_ready'] and cfg['autopay_audience'] == 'owner' and cfg['secret_key'] == BOT_LIVE
    tested = admin.post('/ops/integrations', {'integration': 'inpay_bot', 'action': 'test_autopay'})
    assert tested.status_code == 302 and 'autopay_connected' in tested['Location']
    page = admin.get('/ops/integrations?lang=en').content.decode()
    assert AP_SECRET not in page and 'shown only to you' in page
    # The website's card is left without it, and saving that card keeps the bot's.
    admin.post('/ops/integrations', {'integration': 'inpay', 'action': 'save', 'enabled': 'false'})
    assert inpay_config('bot')['autopay_secret'] == AP_SECRET
    for lang in ('uz', 'ru'):
        assert admin.get(f'/ops/integrations?lang={lang}').status_code == 200
    from operations.models import AuditLog
    entry = AuditLog.objects.filter(target='inpay_bot', action='integration.save').latest('created_at')
    assert entry.after['autopay'] is True and AP_SECRET not in json.dumps(entry.after)
    # The website's kassa takes its own key, tested with it.
    saved = admin.post('/ops/integrations', {'integration': 'inpay', 'action': 'save', 'enabled': 'false',
                                             'autopay_enabled': 'true', 'autopay_key_id': WEB_AP_KEY,
                                             'autopay_secret': WEB_AP_SECRET, 'autopay_audience': 'owner'})
    assert saved.status_code == 302
    assert inpay_config('web')['autopay_key_id'] == WEB_AP_KEY and inpay_config('bot')['autopay_key_id'] == AP_KEY
    tested = admin.post('/ops/integrations', {'integration': 'inpay', 'action': 'test_autopay'})
    assert tested.status_code == 302 and 'autopay_connected' in tested['Location']
    assert bank.keys[-1] == ('list', WEB_AP_KEY)
    assert WEB_AP_SECRET not in admin.get('/ops/integrations?lang=en').content.decode()


def test_a_refunded_card_charge_takes_the_plan_back_and_turns_renewal_off(bank):
    from apps.commerce import checkout
    autopay_on()
    account = customer()
    renewal = renewing(account, bank)
    row = CardCharge.objects.get()
    admin, user = staff_client('Administrator')
    page = admin.get(f'/ops/payments/{row.payment_id}?lang=en')
    assert page.status_code == 200 and f'card {row.provider_charge_id}' in page.content.decode()
    checkout.refund(row.payment, user, 'Customer asked')
    row.refresh_from_db()
    renewal.refresh_from_db()
    assert row.status == 'refunded' and effective_plan(account) == 'free'
    assert (renewal.status, renewal.stopped_reason) == ('off', 'refund')
