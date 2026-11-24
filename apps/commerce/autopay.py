"""Saved cards and monthly renewal through inPAY's Avto to'lov.

A customer saves a card once, on inPAY's own page (card number, SMS code,
and the most they agree to be charged at once). From then on the card can be
charged without a code: for the first month right away, every 30 days while
renewal is on, and in one tap when they pay again. What is trusted is narrow:

- The card number never reaches us. inPAY keeps it and gives us a card id
  and a mandate, its proof of the customer's consent.
- A plan is granted only from inPAY's answer that a charge succeeded, for
  exactly the charge's amount, through the same Invoice, Payment and
  SubscriptionPeriod as every paid plan (apps/commerce/periods.py), tagged
  `inpay`. Each charge's id is its idempotency key: one whose answer was lost
  is asked again under the same key, so money is never taken twice.
- Renewal is the customer's choice, made when buying («Pay and renew every
  month») or later from /subscription; they turn it off, or remove the card,
  whenever they like. The bot must offer «Remove card»: inPAY's contract says so.
- A renewal is tried on the day the paid period ends, then a day and three
  days later. Each failure tells the customer; after the last, renewal stops
  and the plan ends as any other would. The customer is reminded three days
  before every renewal and told after every charge; inPAY also texts them.
- Avto to'lov has no test mode, so it starts shown to the owner alone
  (`autopay_audience`), and is offered only where inPAY is the way to pay.

Each kassa has its own Avto to'lov and key, as each place has its own kassa
(apps/commerce/checkout.py): a card saved in the bot is saved through the
bot's kassa, one saved on the website through the website's, and inPAY's id
for it means something to that kassa alone. So a card is always charged and
removed through the kassa that saved it, and a place charges in one tap only
a card saved there. A customer has one card: the one saved last replaces the
other, wherever it was saved, and renewal goes on from it.

Asking inPAY is a network call: `begin_*`/`ask_*`/`apply_*` keep it apart
from the database work, as apps/commerce/checkout.py does, so the bot makes
the call off the thread its queries run on.
"""
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.core.errors import DomainError

from . import inpay
from .manual import PERIOD_DAYS, PLANS, REMINDER_DAYS

logger = logging.getLogger(__name__)

PROVIDER = 'inpay'
# The places a card is saved in, each through its own kassa's Avto to'lov.
CHANNELS = ('bot', 'web')
# Where the owner puts a kassa's Avto PAY key right, named in their alerts.
SECTION = {'bot': 'Automatic payments in the bot (inPAY)', 'web': 'Automatic payments on the website (inPAY)'}
# How long the website's return page waits between asking inPAY about one card.
LOOK_SECONDS = 5
# inPAY's page for saving a card stays open this long.
BIND_MINUTES = 30
# A renewal is first tried this long before the paid period ends: on its last day.
LEAD_HOURS = 6
# Days after the period ends when a declined renewal is tried again; the next decline stops it.
RETRY_DAYS = (1, 3)
MAX_ATTEMPTS = 1 + len(RETRY_DAYS)
# Pressing the same pay button twice within this long charges once.
DOUBLE_TAP_SECONDS = 120
# A charge whose answer keeps getting lost is given up on after this many tries, and the owner told.
MAX_TRIES = 8
# inPAY's codes for a charge refused because of the customer's card.
DECLINED = 'CHARGE_FAILED'
CARD_GONE = 'CARD_STATE'
CONSENT = 'CONSENT_LIMIT'
# What inPAY tells the customer in its SMS, and shows in its records.
REASON = {'en': 'DocMaster {plan}, 30 days', 'uz': 'DocMaster {plan}, 30 kun', 'ru': 'DocMaster {plan}, 30 дней'}


def _config(kassa='bot'):
    from operations.integrations import inpay_config
    return inpay_config(kassa if kassa in CHANNELS else 'bot')


def _owner():
    from operations.integrations import manual_payment_config
    return manual_payment_config()['alert_telegram_id']


def offers():
    from .pricing import offers as priced
    return priced()


def offered(account, channel='bot'):
    """Whether this customer may save a card and renew automatically now, in this place."""
    from .checkout import availability
    if channel not in CHANNELS:
        return False
    cfg = _config(channel)
    if account is None or not cfg['autopay_ready']:
        return False
    if cfg['autopay_audience'] != 'everyone':
        owner = _owner()
        if not (owner and account.telegram_user_id == owner):
            return False
    return bool(availability(account, channel)['available'])


def customer_ref(account):
    """Our name for the customer at inPAY: their cards are listed by it."""
    return f'dm-{account.pk.hex}'


def active_card(account, channel=None):
    """The customer's saved card, the one renewal charges; with `channel`, only one saved in that place."""
    from .models import SavedCard
    rows = SavedCard.objects.filter(account=account, status='active')
    if channel:
        rows = rows.filter(kassa=channel)
    return rows.order_by('-activated_at').first()


def renewal(account):
    from .models import AutoRenewal
    return AutoRenewal.objects.select_related('card').filter(account=account).first()


def paid_until(account, now=None):
    """When the customer's paid time ends, if it has not: the latest period they hold."""
    from .models import SubscriptionPeriod
    now = now or timezone.now()
    return (SubscriptionPeriod.objects.filter(account=account, ends_at__gt=now, revoked_at__isnull=True, sandbox=False)
            .order_by('-ends_at').values_list('ends_at', flat=True).first())


# ---- saving a card ----------------------------------------------------------------------------

def _return_url(card, locale='en'):
    """Where inPAY's page sends the customer back to, in the place they started, on its kassa's own domain.

    The bot's: the chat, where `/start card_<id>` shows how saving went
    (telegram/bot.py). The website's: its page for the card, which asks the
    same and pays for the plan (the website's /app/card/<id>).
    """
    if card.kassa == 'web':
        from apps.core.links import web_origin
        origin = web_origin()
        return f"{origin}/{locale if locale in REASON else 'en'}/app/card/{card.id}" if origin else ''
    from operations.integrations import telegram_config
    username = str(telegram_config().get('username') or '').strip().lstrip('@')
    return f'https://t.me/{username}?start=card_{card.id.hex}' if username else ''


def begin_binding(account, plan='', channel='bot'):
    """A card to save for this customer, in this place: (card, request); `request` is None when its page is already open.

    `plan`, when given, is paid for and renewed every month once the card is saved.
    """
    from apps.core.customer_auth import auth_limit
    from apps.core.models import Account
    from .models import SavedCard
    if not offered(account, channel):
        raise DomainError('autopay_unavailable', 409)
    if plan and (plan not in PLANS or plan not in offers()):
        raise DomainError('checkout_disabled', 409)
    now = timezone.now()
    with transaction.atomic():
        account = Account.objects.select_for_update().get(pk=account.pk)
        open_ = (SavedCard.objects.filter(account=account, kassa=channel, status='binding',
                                          bind_expires_at__gt=now + timedelta(minutes=5)).exclude(bind_url='')
                 .order_by('-created_at').first())
        if open_:
            if open_.intent != plan:
                open_.intent = plan
                open_.save(update_fields=['intent'])
            return open_, None
        auth_limit('card-bind', str(account.pk), 8, 3600)
        card = SavedCard.objects.create(account=account, kassa=channel, customer_ref=customer_ref(account), intent=plan)
    return card, {'cfg': _config(channel), 'customer_ref': card.customer_ref,
                  'return_url': _return_url(card, account.locale)}


def _failure(error):
    if isinstance(error, inpay.Unavailable):
        return 'provider_rate_limited' if error.reason == 'rate_limited' else 'provider_unavailable'
    if isinstance(error, inpay.Refused):
        return error.code
    return 'provider_unavailable'


def ask_binding(request):
    """Ask inPAY for the page to save a card on: (answer, failure). No database is touched."""
    try:
        return inpay.bind_card(request['cfg'], customer_ref=request['customer_ref'], return_url=request['return_url']), ''
    except Exception as error:  # noqa: BLE001 — every failure is a reason, never a crash
        return None, _failure(error)


def complete_binding(card, answer, failure):
    """Keep inPAY's page for the card, or say it could not be opened."""
    from .models import SavedCard
    if not answer:
        SavedCard.objects.filter(pk=card.pk, status='binding').update(status='expired')
        if failure not in ('provider_unavailable', 'provider_rate_limited'):
            _alert(_kind('autopay_refused', card.kassa), f'⚠️ inPAY could not open its page for saving a card: {failure}'
                   '\nSaved cards and auto-renewal are not working. Check the Avto PAY key in Admin → Integrations → '
                   f'{SECTION[card.kassa]}, and Avto PAY in the inPAY cabinet.', once_an_hour=True)
        raise DomainError('autopay_unavailable', 503, retryable=True)
    with transaction.atomic():
        # inPAY may give the same id again to a page it reopens: the old row lets go of it.
        SavedCard.objects.filter(kassa=card.kassa, provider_card_id=answer['card_id'], status__in=('binding', 'expired')).exclude(
            pk=card.pk).update(provider_card_id=None, status='expired')
        try:
            SavedCard.objects.filter(pk=card.pk).update(provider_card_id=answer['card_id'], bind_url=answer['url'],
                                                        bind_expires_at=timezone.now() + timedelta(minutes=BIND_MINUTES))
        except IntegrityError:
            raise DomainError('autopay_unavailable', 503, retryable=True) from None
    card.refresh_from_db()
    return card


def look_cards(card):
    """What to ask inPAY about the customer's cards, or None when nothing is pending."""
    if card.provider_card_id is None:
        return None
    return {'cfg': _config(card.kassa), 'customer_ref': card.customer_ref}


def ask_cards(question):
    """inPAY's list of the customer's cards: (cards, failure). No database is touched."""
    try:
        return inpay.list_cards(question['cfg'], customer_ref=question['customer_ref']), ''
    except Exception as error:  # noqa: BLE001
        return None, _failure(error)


@transaction.atomic
def apply_cards(card_pk, cards, now=None):
    """Bring one saved card up to what inPAY says about it. Safe to repeat."""
    from .models import AutoRenewal, SavedCard
    now = now or timezone.now()
    card = SavedCard.objects.select_for_update().get(pk=card_pk)
    card.checked_at = now
    remote = next((item for item in cards or [] if item['card_id'] == card.provider_card_id), None)
    changed = ['checked_at']
    if remote is None:
        if card.status == 'binding' and card.created_at < now - timedelta(minutes=BIND_MINUTES + 10):
            card.status = 'expired'
            changed.append('status')
        card.save(update_fields=changed)
        return card
    for field, value in (('masked_pan', remote['masked']), ('expiry', remote['expiry']), ('mandate_id', remote['mandate']),
                         ('consent_max', remote['consent_max'])):
        if value and getattr(card, field) != value:
            setattr(card, field, value)
            changed.append(field)
    if remote['state'] == 'active' and card.status == 'binding':
        card.status, card.activated_at = 'active', now
        changed += ['status', 'activated_at']
        # One card at a time, wherever it was saved: the one saved last is the one charged,
        # and a renewal running on the one it replaces goes on from it.
        replaced = list(SavedCard.objects.filter(account_id=card.account_id, status='active').exclude(pk=card.pk)
                        .values_list('pk', flat=True))
        if replaced:
            SavedCard.objects.filter(pk__in=replaced).update(status='removing', removed_at=now, removed_by='replaced')
            AutoRenewal.objects.filter(card_id__in=replaced, status='on').update(card=card)
    elif remote['state'] == 'removed' and card.status in ('binding', 'active'):
        card.status, card.removed_at, card.removed_by = 'removed', now, 'inpay'
        changed += ['status', 'removed_at', 'removed_by']
        _card_gone(card, 'card_removed')
    card.save(update_fields=list(dict.fromkeys(changed)))
    return card


def claim_intent(card):
    """The plan to pay for now that the card is saved, claimed by one caller only; '' when there is none."""
    from .models import SavedCard
    if card.status != 'active' or not card.intent:
        return ''
    plan = card.intent
    return plan if SavedCard.objects.filter(pk=card.pk, intent=plan).update(intent='') else ''


# ---- charging a card ----------------------------------------------------------------------------

def begin_charge(account, card, plan, purpose, renewal=None, attempt=1, channel=None):
    """A charge of `plan` at today's price: (row, request); `request` is None for a double tap's row.

    `channel` is the place a customer pressed «Pay» in: it charges only a card
    saved there, and only while saved cards are offered there.
    """
    from apps.core.models import Account
    from .models import CardCharge, SavedCard
    if plan not in PLANS:
        raise DomainError('invalid_plan')
    if channel and not offered(account, channel):
        raise DomainError('autopay_unavailable', 409)
    offered_now = offers()
    if plan not in offered_now:
        raise DomainError('checkout_disabled', 409)
    price, regular = offered_now[plan]['price'], offered_now[plan]['regular']
    now = timezone.now()
    with transaction.atomic():
        account = Account.objects.select_for_update().get(pk=account.pk)
        card = SavedCard.objects.filter(pk=card.pk, account=account).first()
        if card is None or card.status != 'active' or card.provider_card_id is None or (channel and card.kassa != channel):
            raise DomainError('card_unavailable', 409)
        if purpose != 'renewal':
            recent = CardCharge.objects.filter(account=account, plan=plan, purpose__in=('first', 'one_tap'),
                                               status__in=('created', 'unknown', 'paid'),
                                               created_at__gt=now - timedelta(seconds=DOUBLE_TAP_SECONDS)).first()
            if recent:
                return recent, None
        row = CardCharge.objects.create(account=account, card=card, renewal=renewal, plan=plan, amount=price,
                                        regular_amount=regular, purpose=purpose, attempt=attempt)
    if card.consent_max and price > card.consent_max:
        # Above what the customer agreed to on inPAY's page: inPAY would refuse it.
        return row, {'failure': CONSENT}
    return row, _request(row, card, account)


def _request(row, card, account):
    reason = REASON.get(account.locale, REASON['en']).format(plan=row.plan.title())
    return {'cfg': _config(card.kassa), 'card_id': card.provider_card_id, 'amount': row.amount, 'idem_key': str(row.id),
            'reason': reason, 'order_ref': str(row.id)}


def again(row):
    """The question for a charge whose answer was lost: the same card, amount and key."""
    return _request(row, row.card, row.account)


def ask_charge(request):
    """Charge the card at inPAY: (answer, failure). No database is touched."""
    if request.get('failure'):
        return None, request['failure']
    try:
        return inpay.charge_card(request['cfg'], card_id=request['card_id'], amount=request['amount'],
                                 idem_key=request['idem_key'], reason=request['reason'], order_ref=request['order_ref']), ''
    except Exception as error:  # noqa: BLE001
        return None, _failure(error)


def _customer_side(failure):
    return failure in (DECLINED, CARD_GONE, CONSENT)


@transaction.atomic
def apply_charge(row_pk, answer, failure, now=None):
    """Act on inPAY's answer about one charge. Safe to repeat: a decided row is left as it is."""
    from apps.core.models import Account
    from .models import CardCharge, OfferVersion, SavedCard
    from .periods import grant
    from .services import PERIOD
    now = now or timezone.now()
    row = CardCharge.objects.select_for_update().select_related('card').get(pk=row_pk)
    if row.status in ('paid', 'refunded', 'review', 'failed'):
        return row
    row.tries += 1
    if answer is None:
        if failure in ('provider_unavailable', 'provider_rate_limited'):
            # Asked, and the answer lost: asked again under the same key, never charged twice.
            row.status, row.failure = 'unknown', failure
            if row.tries >= MAX_TRIES:
                row.status, row.decided_at = 'failed', now
                _alert(_kind('autopay_unconfirmed', row.card.kassa), f'⚠️ inPAY did not answer about a card charge after {row.tries} tries.'
                       f"\n{row.plan.title()} · {_money(row.amount)} so'm · charge {row.id}"
                       '\nNo plan was granted. Look the charge up in the inPAY cabinet (Avto PAY); if the money was '
                       'taken, give the plan on the customer\'s page, or return it in inPAY.')
            row.save(update_fields=['status', 'failure', 'tries', 'decided_at'])
            return row
        row.status, row.failure, row.decided_at = 'failed', failure[:64], now
        row.save(update_fields=['status', 'failure', 'tries', 'decided_at'])
        if failure == CARD_GONE:
            card = SavedCard.objects.select_for_update().get(pk=row.card_id)
            if card.status == 'active':
                card.status, card.removed_at, card.removed_by = 'removed', now, 'inpay'
                card.save(update_fields=['status', 'removed_at', 'removed_by'])
        elif not _customer_side(failure):
            # The key, a limit of the owner's at inPAY, or inPAY refusing: only the owner can put it right.
            _alert(_kind('autopay_refused', row.card.kassa), f'⚠️ inPAY refused to charge a saved card: {failure}'
                   '\nAuto-renewal and saved-card payments are not working. Check the Avto PAY key in Admin → '
                   f'Integrations → {SECTION[row.card.kassa]}, and Avto PAY (limits) in the inPAY cabinet.',
                   once_an_hour=True)
        return row
    row.provider_charge_id, row.provider_ref = answer['charge_id'], answer['provider_ref']
    row.mandate_id = answer['mandate'] or row.card.mandate_id
    if answer['state'] != 'paid':
        row.status = 'unknown'
        row.save(update_fields=['status', 'tries', 'provider_charge_id', 'provider_ref', 'mandate_id'])
        return row
    if answer['amount'] is not None and answer['amount'] != row.amount:
        # Money was taken for something this row does not describe: nothing is granted on a guess.
        row.status, row.failure, row.decided_at = 'review', 'amount_mismatch', now
        row.save(update_fields=['status', 'failure', 'decided_at', 'tries', 'provider_charge_id', 'provider_ref', 'mandate_id'])
        _alert(_kind('autopay_review', row.card.kassa), '⚠️ A saved-card charge needs a look: amount_mismatch'
               f"\n{row.plan.title()} · {_money(row.amount)} so'm expected, inPAY reports {_money(answer['amount'])} so'm"
               f' · inPAY charge {row.provider_charge_id}\nNo plan was granted.')
        return row
    account = Account.objects.select_for_update().get(pk=row.account_id)
    offer, _ = OfferVersion.objects.get_or_create(
        id=f'inpay:{row.plan}:{row.amount}',
        defaults={'offer_id': f'inpay_{row.plan}', 'version': 'inpay-v1', 'kind': 'subscription', 'plan': row.plan,
                  'name': f'{row.plan.title()} · inPAY', 'period_seconds': PERIOD, 'sandbox': False, 'enabled': False})
    regular = row.regular_amount
    snapshot = {'id': offer.id, 'offer_id': offer.offer_id, 'version': offer.version, 'kind': offer.kind, 'plan': row.plan,
                'name': offer.name, 'currency': row.currency, 'price': row.amount, 'regular_price': regular,
                'discounted': regular is not None and row.amount < regular, 'provider': PROVIDER,
                'provider_payment': f'card:{row.provider_charge_id}', 'saved_card': row.card.masked_pan,
                'purpose': row.purpose, 'period_seconds': PERIOD_DAYS * 86400, 'period_days': PERIOD_DAYS}
    row.payment, _ = grant(account, row.plan, PERIOD_DAYS, provider=PROVIDER, charge=f'inpay-card:{row.provider_charge_id}',
                           amount=row.amount, currency=row.currency, offer=offer, snapshot=snapshot, occurred_at=now, now=now)
    row.status, row.failure, row.decided_at = 'paid', '', now
    row.save()
    SavedCard.objects.filter(pk=row.card_id).update(last_used_at=now, mandate_id=row.mandate_id or F('mandate_id'))
    _action(row, 'card_charge.paid', {})
    from apps.core.links import admin_url
    link = admin_url(f'/ops/payments/{row.payment_id}')
    _alert(_kind('inpay_card_paid', row.card.kassa),
           ('🔁 Auto-renewal charged' if row.purpose == 'renewal' else '⚡ Saved-card payment received') +
           f"\n{row.plan.title()} · {_money(row.amount)} so'm · card {row.card.masked_pan} · "
           + ('website' if row.card.kassa == 'web' else 'bot') +
           f"\nFrom: {account.display_name or account.telegram_user_id or account.pk}" + (f'\n{link}' if link else ''))
    return row


def charge(account, card, plan, purpose, renewal=None, attempt=1):
    """Charge the saved card for `plan` and act on the answer; returns the row as it stands."""
    row, request = begin_charge(account, card, plan, purpose, renewal, attempt)
    if request is None:
        return row
    answer, failure = ask_charge(request)
    return apply_charge(row.pk, answer, failure)


def period_of(row):
    from .models import SubscriptionPeriod
    return SubscriptionPeriod.objects.filter(payment_id=row.payment_id).first() if row.payment_id else None


def after_first(row):
    """A first charge that went through turns renewal on, from the end of the period it bought."""
    if row.status != 'paid' or row.purpose != 'first':
        return None
    period = period_of(row)
    return enable(row.account, row.card, row.plan, period.ends_at if period else paid_until(row.account))


# ---- renewal ------------------------------------------------------------------------------------

def enable(account, card, plan, renews_at):
    """Renew `plan` every month from `card`, the first time at `renews_at`."""
    from .models import AutoRenewal
    renewal, _ = AutoRenewal.objects.update_or_create(account=account, defaults={
        'card': card, 'plan': plan, 'status': 'on', 'renews_at': renews_at, 'attempts': 0, 'next_try_at': None,
        'failure': '', 'stopped_reason': ''})
    _action_renewal(renewal, 'renewal.on')
    return renewal


def _renewable(account, card):
    """The plan renewal could be turned on for from `card`, and from when: (plan, until), or ('', None)."""
    from .services import effective_plan
    until = paid_until(account)
    plan = effective_plan(account)
    if until is None or plan not in PLANS or plan not in offers() or not offered(account, card.kassa):
        return '', None
    return plan, until


def turn_on(account):
    """Renewal on again, for the plan the customer pays for now, from their saved card (through its own kassa)."""
    card = active_card(account)
    if card is None:
        raise DomainError('card_unavailable', 409)
    plan, until = _renewable(account, card)
    if not plan:
        raise DomainError('renewal_unavailable', 409)
    return enable(account, card, plan, until)


def turn_off(account, by='customer'):
    from .models import AutoRenewal
    renewal = AutoRenewal.objects.filter(account=account, status='on').first()
    if renewal:
        AutoRenewal.objects.filter(pk=renewal.pk).update(status='off', stopped_reason=by, next_try_at=None)
        renewal.refresh_from_db()
        _action_renewal(renewal, 'renewal.off', {'by': by})
    return renewal


def _stop(renewal, reason):
    from .models import AutoRenewal
    if AutoRenewal.objects.filter(pk=renewal.pk, status='on').update(status='stopped', stopped_reason=reason, next_try_at=None):
        renewal.refresh_from_db()
        _notice_renewal(renewal, 'renewal_stopped')
        _action_renewal(renewal, 'renewal.stopped', {'reason': reason})


def _card_gone(card, reason):
    from .models import AutoRenewal
    for renewal in AutoRenewal.objects.filter(card=card, status='on'):
        _stop(renewal, reason)


def due(now=None):
    from .models import AutoRenewal
    now = now or timezone.now()
    return (AutoRenewal.objects.select_related('card', 'account')
            .filter(status='on', renews_at__lte=now + timedelta(hours=LEAD_HOURS))
            .filter(Q(next_try_at__isnull=True) | Q(next_try_at__lte=now)).order_by('renews_at'))


def renew(renewal, now=None):
    """Try one renewal that is due: 'paid', 'moved', 'retry', 'stopped', 'waiting' or 'paused'."""
    from .models import AutoRenewal, CardCharge
    now = now or timezone.now()
    account = renewal.account
    # Paid time bought meanwhile (by hand, or invite months) moves the renewal to its end.
    until = paid_until(account, now)
    if until and until > renewal.renews_at + timedelta(minutes=1):
        AutoRenewal.objects.filter(pk=renewal.pk).update(renews_at=until, attempts=0, next_try_at=None, failure='')
        return 'moved'
    if not _config(renewal.card.kassa)['autopay_ready']:
        return 'paused'
    if renewal.card.status != 'active':
        _stop(renewal, 'card_removed')
        return 'stopped'
    if renewal.plan not in offers():
        _stop(renewal, 'not_on_sale')
        return 'stopped'
    open_ = CardCharge.objects.filter(renewal=renewal, status__in=('created', 'unknown')).order_by('-created_at').first()
    if open_:
        answer, failure = ask_charge(again(open_))
        row = apply_charge(open_.pk, answer, failure, now)
    else:
        try:
            row, request = begin_charge(account, renewal.card, renewal.plan, 'renewal', renewal, renewal.attempts + 1)
        except DomainError as error:
            _stop(renewal, error.code[:32])
            return 'stopped'
        answer, failure = ask_charge(request)
        row = apply_charge(row.pk, answer, failure, now)
    if row.status == 'paid':
        period = period_of(row)
        AutoRenewal.objects.filter(pk=renewal.pk).update(renews_at=period.ends_at if period else paid_until(account, now),
                                                          attempts=0, next_try_at=None, failure='')
        _notice_charge(row, 'renewed')
        return 'paid'
    if row.status in ('unknown', 'created'):
        AutoRenewal.objects.filter(pk=renewal.pk).update(next_try_at=now + timedelta(minutes=15))
        return 'waiting'
    if row.status == 'review':
        _stop(renewal, 'review')
        return 'stopped'
    if row.failure == CARD_GONE:
        _stop(renewal, 'card_removed')
        return 'stopped'
    if row.failure == CONSENT:
        _stop(renewal, 'consent_limit')
        return 'stopped'
    if row.failure == DECLINED:
        attempts = renewal.attempts + 1
        if attempts >= MAX_ATTEMPTS:
            AutoRenewal.objects.filter(pk=renewal.pk).update(attempts=attempts, failure=row.failure)
            _stop(renewal, 'declined')
            return 'stopped'
        AutoRenewal.objects.filter(pk=renewal.pk).update(
            attempts=attempts, failure=row.failure, next_try_at=renewal.renews_at + timedelta(days=RETRY_DAYS[attempts - 1]))
        _notice_charge(row, 'renewal_failed')
        return 'retry'
    # Not the customer's card: the owner is told (apply_charge); the renewal waits an hour, uncounted.
    AutoRenewal.objects.filter(pk=renewal.pk).update(failure=row.failure, next_try_at=now + timedelta(hours=1))
    return 'retry'


def next_try(renewal):
    """When a renewal that just failed is tried again, for the customer's message."""
    return renewal.next_try_at


# ---- removing a card ----------------------------------------------------------------------------

def begin_removal(account, card_id):
    """Take a saved card away here at once (it is never charged again): (card, request) to tell inPAY."""
    from .models import SavedCard
    now = timezone.now()
    with transaction.atomic():
        card = SavedCard.objects.select_for_update().filter(pk=card_id, account=account).first()
        if card is None:
            raise DomainError('not_found', 404)
        if card.status in ('active', 'binding'):
            card.status, card.removed_at, card.removed_by = 'removing', now, 'customer'
            card.intent = ''
            card.save(update_fields=['status', 'removed_at', 'removed_by', 'intent'])
            _card_gone(card, 'card_removed')
            _action_card(card, 'card.removed', {'by': 'customer'})
    if card.status != 'removing' or card.provider_card_id is None:
        return card, None
    return card, {'cfg': _config(card.kassa), 'card_id': card.provider_card_id}


def ask_removal(request):
    """Tell inPAY the card is gone: (done, failure). No database is touched."""
    if request is None:
        return True, ''
    try:
        inpay.remove_card(request['cfg'], card_id=request['card_id'])
        return True, ''
    except inpay.Refused as refused:
        # inPAY no longer holding it is as good as removed.
        return True, refused.code
    except Exception as error:  # noqa: BLE001
        return False, _failure(error)


def finish_removal(card, done):
    from .models import SavedCard
    if done:
        SavedCard.objects.filter(pk=card.pk, status='removing').update(status='removed')
    card.refresh_from_db()
    return card


def remove(account, card_id):
    card, request = begin_removal(account, card_id)
    done, _ = ask_removal(request)
    return finish_removal(card, done)


# ---- what the customer sees ---------------------------------------------------------------------

def status(account, channel='bot'):
    """The customer's saved card and renewal, as the bot or the website (`channel`) shows them.

    `offered` is whether a card can be saved here now; a card's `here` whether
    it was saved here, so this place can charge it in one tap; `can_turn_on`
    whether renewal, now off, can be turned on again from it.
    """
    card, plan = active_card(account), renewal(account)
    renewing = bool(plan and plan.status == 'on')
    return {'offered': offered(account, channel),
            'card': {'id': str(card.id), 'masked': card.masked_pan, 'last4': card.last4, 'expiry': card.expiry,
                     'consent_max': card.consent_max, 'here': card.kassa == channel} if card else None,
            'renewal': {'status': plan.status, 'plan': plan.plan, 'renews_at': plan.renews_at,
                        'amount': (offers().get(plan.plan) or {}).get('price'), 'attempts': plan.attempts,
                        'next_try_at': plan.next_try_at, 'stopped_reason': plan.stopped_reason,
                        'card_last4': plan.card.last4} if plan else None,
            'can_turn_on': bool(card and not renewing and _renewable(account, card)[0])}


def charge_state(row):
    """One charge of a saved card, as the website shows how paying went."""
    if row is None:
        return None
    period = period_of(row) if row.status in ('paid', 'refunded') else None
    current = renewal(row.account) if row.purpose == 'first' and row.status == 'paid' else None
    reason = {DECLINED: 'declined', CONSENT: 'consent_limit', CARD_GONE: 'card_removed'}.get(row.failure, 'unavailable')
    return {'id': str(row.id), 'status': 'pending' if row.status in ('created', 'unknown') else row.status,
            'plan': row.plan, 'amount': row.amount, 'currency': row.currency, 'last4': row.card.last4,
            'reason': reason if row.status == 'failed' else None, 'active_until': period.ends_at if period else None,
            'renews_at': current.renews_at if current and current.status == 'on' and current.card_id == row.card_id else None}


def card_state(card, row=None):
    """A card the website is saving, and the first charge made once it was saved."""
    from .models import CardCharge
    row = row or CardCharge.objects.select_related('card', 'account').filter(card=card, purpose='first').order_by('-created_at').first()
    return {'id': str(card.id), 'status': card.status, 'plan': card.intent or (row.plan if row else None),
            'last4': card.last4, 'bind_url': card.bind_url if card.status == 'binding' and card.bind_url else None,
            'charge': charge_state(row)}


def look_again(card, now=None):
    """The website's page for a card the customer came back from saving: ask inPAY, then pay for its plan.

    inPAY is asked about one card at most every few seconds however often
    the page asks, and the plan is paid for once, here or by the periodic run.
    """
    now = now or timezone.now()
    if card.status == 'binding' and not (card.checked_at and card.checked_at > now - timedelta(seconds=LOOK_SECONDS)):
        question = look_cards(card)
        if question is not None:
            cards, _ = ask_cards(question)
            if cards is not None:
                card = apply_cards(card.pk, cards, now)
    row = finish_saved(card) if card.status == 'active' else None
    return card_state(card, row)


def receipt(row):
    """Tell the customer in Telegram how a charge they started on the website went, as after every charge."""
    if row.status in ('paid', 'failed'):
        _notice_charge(row, 'card_paid' if row.status == 'paid' else 'card_failed')


# ---- the periodic run (cleanupfiles, every five minutes) ----------------------------------------

def housekeeping(now=None):
    """Finish cards being saved, tell inPAY about removed ones, retry lost answers, renew, remind."""
    from .models import AutoRenewal, CardCharge, SavedCard
    now = now or timezone.now()
    done = {'cards': 0, 'removed': 0, 'charges': 0, 'renewals': 0, 'reminded': 0}
    # Pages left open past their time are not waited on.
    SavedCard.objects.filter(status='binding', created_at__lte=now - timedelta(minutes=BIND_MINUTES + 10)).update(status='expired')
    pending = (SavedCard.objects.filter(status='binding', provider_card_id__isnull=False)
               .filter(Q(checked_at__isnull=True) | Q(checked_at__lte=now - timedelta(minutes=1))).order_by('-created_at')[:10])
    for card in pending:
        try:
            question = look_cards(card)
            cards, failure = ask_cards(question) if question else (None, 'nothing')
            if cards is not None:
                card = apply_cards(card.pk, cards, now)
                finish_saved(card)
                done['cards'] += 1
        except Exception:
            logger.exception('Saved card %s could not be checked', card.pk)
    for card in SavedCard.objects.filter(status='removing').order_by('removed_at')[:5]:
        try:
            ok, _ = ask_removal({'cfg': _config(card.kassa), 'card_id': card.provider_card_id} if card.provider_card_id else None)
            finish_removal(card, ok)
            done['removed'] += int(ok)
        except Exception:
            logger.exception('Saved card %s could not be removed at inPAY', card.pk)
    # First months and one-tap payments whose answer was lost (renewals are retried below).
    for row in CardCharge.objects.filter(status__in=('created', 'unknown'), renewal__isnull=True,
                                         created_at__lte=now - timedelta(minutes=1)).select_related('card', 'account')[:5]:
        try:
            answer, failure = ask_charge(again(row))
            row = apply_charge(row.pk, answer, failure, now)
            after_first(row)
            if row.status == 'paid':
                _notice_charge(row, 'card_paid')
            done['charges'] += 1
        except Exception:
            logger.exception('Card charge %s could not be checked', row.pk)
    for renewal in due(now)[:10]:
        try:
            renew(renewal, now)
            done['renewals'] += 1
        except Exception:
            logger.exception('Renewal %s could not be charged', renewal.pk)
    # Three days ahead, once per renewal.
    coming = AutoRenewal.objects.filter(status='on', renews_at__gt=now, renews_at__lte=now + timedelta(days=REMINDER_DAYS)).exclude(
        reminded_for=F('renews_at'))
    for renewal in coming:
        if _config(renewal.card.kassa)['autopay_ready'] and renewal.card.status == 'active':
            _notice_renewal(renewal, 'renewal_upcoming')
            AutoRenewal.objects.filter(pk=renewal.pk).update(reminded_for=renewal.renews_at)
            done['reminded'] += 1
    return done


def finish_saved(card):
    """A card just saved with a plan to buy: charge the first month, and turn renewal on when it goes through."""
    plan = claim_intent(card)
    if not plan:
        return None
    try:
        row = charge(card.account, card, plan, 'first')
    except DomainError:
        return None
    after_first(row)
    # A lost answer is asked again by the next run, which says how it went then.
    if row.status in ('paid', 'failed'):
        _notice_charge(row, 'card_paid' if row.status == 'paid' else 'card_failed')
    return row


def renewing(account_ids=None):
    """Accounts whose plan renews by itself: the plain "your plan ends" reminder is not for them."""
    from .models import AutoRenewal
    rows = AutoRenewal.objects.filter(status='on')
    if account_ids is not None:
        rows = rows.filter(account_id__in=account_ids)
    return set(rows.values_list('account_id', flat=True))


# ---- notices, alerts, the audit trail -----------------------------------------------------------

def _notice_charge(row, kind):
    from .models import PaymentNotice
    PaymentNotice.objects.get_or_create(charge=row, kind=kind)


def _notice_renewal(renewal, kind):
    from .models import PaymentNotice
    PaymentNotice.objects.get_or_create(renewal=renewal, kind=kind, due_for=renewal.renews_at)


def _money(amount):
    return f'{amount:,}'.replace(',', ' ')


def _kind(kind, kassa):
    """An alert's kind for one kassa: the website's are told apart, so one kassa's alert never quiets the other's."""
    return kind if kassa == 'bot' else f'{kind}_web'


def _alert(kind, text, once_an_hour=False):
    from .checkout import _alert as alert
    alert(kind, text, once_an_hour)


def _action(row, action, metadata):
    from .models import CommerceAction
    CommerceAction.objects.create(account_id=row.account_id, actor=None, action=action, target=str(row.id),
                                  metadata={'plan': row.plan, 'amount': row.amount, 'currency': row.currency,
                                            'purpose': row.purpose, 'provider_id': row.provider_charge_id,
                                            'card': row.card.masked_pan, **metadata})


def _action_renewal(renewal, action, metadata=None):
    from .models import CommerceAction
    CommerceAction.objects.create(account_id=renewal.account_id, actor=None, action=action, target=str(renewal.pk),
                                  metadata={'plan': renewal.plan, 'renews_at': renewal.renews_at.isoformat(),
                                            'card': renewal.card.masked_pan, **(metadata or {})})


def _action_card(card, action, metadata=None):
    from .models import CommerceAction
    CommerceAction.objects.create(account_id=card.account_id, actor=None, action=action, target=str(card.id),
                                  metadata={'card': card.masked_pan, **(metadata or {})})
