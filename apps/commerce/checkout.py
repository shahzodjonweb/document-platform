"""Automatic payment through inPAY: from the customer's choice to the plan it buys.

The customer picks a plan, is sent to inPAY's page, pays there with Click,
Payme or a card, and the plan starts by itself. Nobody reviews anything, so
what is trusted is narrow and fixed:

- The plan and the amount are ours, written on the Checkout row before inPAY
  is asked. Nothing the customer's browser or a webhook says changes them.
- A plan is granted only from inPAY's own answer to our own question
  (`inpay.fetch`): the payment succeeded, for exactly the row's amount. A
  webhook, the page the customer returns to and the "I've paid" button are
  only reasons to ask.
- A payment inPAY reports as paid is honoured whatever the row said before
  (failed, expired): the money is already taken. One that does not match the
  row is granted nothing and put in front of the owner.
- A test key moves no money. With one, only the owner is offered automatic
  payment, and a paid test grants nothing: it proves the wiring end to end.

Granting writes the same Invoice, Payment, Subscription and SubscriptionPeriod
a card transfer does (apps/commerce/periods.py), tagged `inpay`.

The website and the bot each have their own inPAY kassa, with its own keys,
because inPAY approves a kassa for one website or one Telegram bot. A payment
is opened, checked and confirmed with the kassa of the place it began in (its
`channel`), and each place has its own way to pay: the bot can take payments
through its kassa while the website's is still waiting for approval.

Asking inPAY is a network call. `begin`/`ask`/`complete` and `due`/`look`/
`apply` keep it apart from the database work, so the bot can make the call off
the one thread its queries run on; `create` and `refresh` run all three.
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.core.errors import DomainError

from . import inpay
from .manual import PERIOD_DAYS, PLANS, REMINDER_DAYS

logger = logging.getLogger(__name__)

PROVIDER = 'inpay'
# How long a payment page is waited on before the row stops being offered.
OPEN_HOURS = 24
# Choosing the same plan again this soon returns to the page already open.
REUSE_MINUTES = 30
# A payment worth showing on the billing page: the open one, or one decided this lately.
SHOWN_DAYS = 7
# Payments the periodic check asks inPAY about in one run (every five minutes),
# by API: v1 shares 100 requests an hour with everything else.
RECONCILE_BATCH = {'v2': 10, 'v1': 3}
# A payment that failed, was cancelled or ran out of time is still looked at
# this long: the customer may pay on the same page after all.
REOPEN_HOURS = 48
# Card transfer stands in for inPAY this long after inPAY could not open a
# payment; the first customer after it tries inPAY again.
FALLBACK_MINUTES = 10
FINAL = ('paid', 'refunded')
DESCRIPTION = {'en': 'DocMaster {plan} — 30 days', 'uz': 'DocMaster {plan} — 30 kun', 'ru': 'DocMaster {plan} — 30 дней'}


# Where in the admin each kassa is set up, for the owner's alerts.
KASSA_SETTINGS = {'web': 'Admin → Integrations → Automatic payments on the website (inPAY)',
                  'bot': 'Admin → Integrations → Automatic payments in the bot (inPAY)'}


def kassa(channel):
    """The kassa a payment begun in `channel` belongs to: 'bot' or 'web'."""
    return 'bot' if channel == 'bot' else 'web'


def _config(channel='web'):
    from operations.integrations import inpay_config
    return inpay_config(kassa(channel))


def _owner():
    from operations.integrations import manual_payment_config
    return manual_payment_config()['alert_telegram_id']


def offers():
    from .pricing import offers as priced
    return priced()


def _card_ready():
    from operations.integrations import manual_payment_config
    return bool(manual_payment_config()['ready'])


def failing(live, channel='web', now=None):
    """Whether the last payment we tried to open with this kassa, a short while ago, could not be opened.

    inPAY refusing (a key, the kassa) or not answering both count; a row the
    server lost before asking (`never_opened`) says nothing about inPAY. Each
    kassa is judged by its own payments: the bot's failing says nothing about
    the website's.
    """
    from .models import Checkout
    now = now or timezone.now()
    opened = ~Q(provider_id='')
    refused = Q(status='failed', provider_id='') & ~Q(failure='never_opened')
    last = (Checkout.objects.filter(channel=kassa(channel), livemode=live,
                                    created_at__gt=now - timedelta(minutes=FALLBACK_MINUTES))
            .filter(opened | refused).order_by('-created_at').values_list('provider_id', flat=True).first())
    return last == ''


def _standing_in(live, channel='web'):
    """Whether card transfer takes this kassa's place for now: it just failed, and there is a card to pay to.

    Without card transfer set up there is nothing to fall back to, and every
    customer goes on trying inPAY.
    """
    return failing(live, channel) and _card_ready()


def _reachable(channel):
    """Whether inPAY has somewhere to return a customer of this kassa to.

    The website's kassa returns them to the website, so it needs its address;
    the bot's returns them to the chat, or leaves them on inPAY's own page
    when the bot's username is not saved.
    """
    from apps.core.links import web_origin
    return kassa(channel) == 'bot' or bool(web_origin())


def availability(account=None, channel='web'):
    """Whether this customer may pay automatically right now, where they are: {'available', 'provider', 'test'}.

    Available, it is the only way offered there: card transfer is the way to
    pay only while automatic payment is not (apps/commerce/manual.py `options`).
    """
    cfg = _config(channel)
    if not cfg['ready'] or not offers() or not _reachable(channel):
        return {'available': False}
    # A test key takes no money, so a payment made with it must reach nobody
    # but the owner trying it out: the Telegram ID saved for alerts.
    owner = _owner()
    if not cfg['live'] and not (account is not None and owner and account.telegram_user_id == owner):
        return {'available': False}
    if _standing_in(cfg['live'], channel):
        return {'available': False}
    return {'available': True, 'provider': PROVIDER, 'test': not cfg['live']}


def fallback(channel='web'):
    """Whether card transfer stands in right now for a kassa that is set up but could not open a payment."""
    cfg = _config(channel)
    return bool(cfg['ready']) and _standing_in(cfg['live'], channel)


def payment_way(channel='web'):
    """How customers pay right now in one place, for the admin: inpay, inpay_test, card, card_fallback or none."""
    cfg, priced = _config(channel), bool(offers())
    card = priced and _card_ready()
    if priced and cfg['ready'] and _reachable(channel):
        if card and failing(cfg['live'], channel):
            return 'card_fallback'
        return 'inpay' if cfg['live'] else 'inpay_test'
    return 'card' if card else 'none'


def on_sale():
    """What the public site may say about paying on it: {'automatic', 'card'}. A test key is not on sale.

    One way at a time, as customers are offered it: card transfer only while
    automatic payment is not on sale. The website's kassa decides it.
    """
    priced, cfg = bool(offers()), _config('web')
    automatic = bool(priced and cfg['ready'] and cfg['live'] and _reachable('web')) and not _standing_in(True, 'web')
    return {'automatic': automatic, 'card': bool(priced and _card_ready()) and not automatic}


def _urls(row, locale):
    """Where inPAY sends the customer back, and where it reports to, by the payment's kassa.

    The website's: both on the website's own domain, the one that kassa is
    registered for, so inPAY accepts them with nothing to whitelist; the
    website passes /api on to the API.

    The bot's is registered for the bot's t.me link: the customer is sent back
    to the chat, where `/start pay_<id>` shows how the payment stands
    (telegram/bot.py). No webhook address is sent, as none is on the kassa's
    domain: inPAY reports to the one the owner saves on the kassa in its cabinet.
    """
    if kassa(row.channel) == 'bot':
        from operations.integrations import telegram_config
        username = str(telegram_config().get('username') or '').strip().lstrip('@')
        back = f'https://t.me/{username}?start=pay_{row.id.hex}' if username else ''
        return {'return_url': back, 'webhook_url': ''}
    from apps.core.links import web_origin
    origin = web_origin()
    if not origin:
        return None
    locale = locale if locale in DESCRIPTION else 'en'
    return {'return_url': f'{origin}/{locale}/app/pay/{row.id}', 'webhook_url': f'{origin}/api/v1/webhooks/inpay'}


def begin(account, plan, channel='web'):
    """A row for a new payment, or the page already open for this plan and price.

    Returns (row, request): `request` is what to ask inPAY, or None when the
    row already has its page.
    """
    from apps.core.customer_auth import auth_limit
    from apps.core.models import Account
    from .models import Checkout
    if plan not in PLANS:
        raise DomainError('invalid_plan')
    channel = kassa(channel)
    offered = offers()
    if not availability(account, channel)['available'] or plan not in offered:
        raise DomainError('checkout_disabled', 409)
    cfg = _config(channel)
    price, regular = offered[plan]['price'], offered[plan]['regular']
    now = timezone.now()
    with transaction.atomic():
        account = Account.objects.select_for_update().get(pk=account.pk)
        # A page opened in the other place belongs to the other kassa: it is not reused here.
        open_ = Checkout.objects.filter(
            account=account, status='pending', plan=plan, amount=price, api=cfg['api'], livemode=cfg['live'],
            channel=channel, created_at__gt=now - timedelta(minutes=REUSE_MINUTES), expires_at__gt=now,
        ).exclude(checkout_url='').order_by('-created_at').first()
        if open_:
            return open_, None
        auth_limit('checkout', str(account.pk), 12, 3600)
        row = Checkout.objects.create(
            account=account, plan=plan, amount=price, regular_amount=regular, api=cfg['api'], livemode=cfg['live'],
            channel=channel, expires_at=now + timedelta(hours=OPEN_HOURS))
    urls = _urls(row, account.locale)
    if not urls:
        return row, {'failure': 'no_web_origin'}
    description = DESCRIPTION.get(account.locale, DESCRIPTION['en']).format(plan=plan.title())
    return row, {'cfg': cfg, 'reference': str(row.id), 'amount': price, 'description': description, **urls}


def ask(request):
    """Open the payment at inPAY: (opened, failure). No database is touched."""
    if request.get('failure'):
        return None, request['failure']
    try:
        return inpay.open_payment(request['cfg'], reference=request['reference'], amount=request['amount'],
                                  description=request['description'], return_url=request['return_url'],
                                  webhook_url=request['webhook_url']), ''
    except inpay.Refused as refused:
        return None, 'refused:' + refused.code
    except inpay.Unavailable as away:
        return None, 'provider_rate_limited' if away.reason == 'rate_limited' else 'provider_unavailable'
    except Exception:
        return None, 'provider_unavailable'


def complete(row, opened, failure):
    """Keep what inPAY answered. A payment that could not be opened is said so, to be tried again."""
    from .models import Checkout
    if opened and opened['live'] != row.livemode:
        # A key that is not what its name says: never send a customer to that page.
        opened, failure = None, 'mode_mismatch'
    if not opened:
        Checkout.objects.filter(pk=row.pk, status='created').update(status='failed', failure=failure[:64])
        # inPAY saying no is a setting only the owner can put right (a key, the
        # kassa, a domain); inPAY not answering passes by itself.
        place = kassa(row.channel)
        if failure == 'provider_rate_limited':
            _alert('inpay_rate_limited', '⚠️ inPAY\'s hourly request limit is spent: customers cannot open new payments '
                   'until the hour is over. With the classic API (v1) the limit is 100 requests an hour; API v2 keys avoid it.',
                   once_an_hour=True)
        elif failure != 'provider_unavailable':
            code = failure.removeprefix('refused:')
            where = 'in the bot' if place == 'bot' else 'on the website'
            hint = ''
            if 'whitelist' in code.lower() or 'domain' in code.lower():
                hint = ('\ninPAY did not accept the address customers return to (' + ('t.me, the bot’s link' if place == 'bot'
                        else 'the website') + '). Add that domain to the kassa’s allowed domains in the inPAY cabinet.')
            _alert('inpay_refused' + ('_bot' if place == 'bot' else ''), f'⚠️ inPAY could not open a payment {where}: {code}'
                   f'\nAutomatic payment {where} is not working. Check {KASSA_SETTINGS[place]} and that kassa in the inPAY cabinet.'
                   + hint, once_an_hour=True)
        raise DomainError('checkout_unavailable', 503, retryable=True)
    Checkout.objects.filter(pk=row.pk, status='created').update(
        status='pending', provider_id=opened['id'], checkout_url=opened['url'])
    row.refresh_from_db()
    _action(row, 'checkout.created', {})
    return row


def create(account, plan, channel='web'):
    """A payment for `plan` with its page at inPAY: (row, created)."""
    row, request = begin(account, plan, channel)
    if request is None:
        return row, False
    opened, failure = ask(request)
    return complete(row, opened, failure), True


def _gap(row, now):
    """Seconds to leave between two questions to inPAY about one payment.

    A customer waiting on the page asks every few seconds; inPAY is asked far
    less, and less still as the payment ages. v1 allows 100 requests an hour
    for everything, so it is asked three times less often.
    """
    age = (now - row.created_at).total_seconds()
    seconds = 10 if age < 120 else 30 if age < 600 else 120
    return seconds * (3 if row.api == 'v1' else 1)


def due(row, force=False, now=None):
    """Claim one question to inPAY about this payment: what to ask, or None when there is no need yet."""
    from .models import Checkout
    now = now or timezone.now()
    if row.status in FINAL or row.status == 'created' or not row.provider_id:
        return None
    # Long closed: nothing a page or an unsigned webhook says makes us ask again.
    # A signed webhook (force) still does.
    if not force and row.created_at < now - timedelta(hours=OPEN_HOURS + REOPEN_HOURS):
        return None
    claimed = Checkout.objects.filter(pk=row.pk)
    if not force:
        claimed = claimed.filter(Q(checked_at__isnull=True) | Q(checked_at__lte=now - timedelta(seconds=_gap(row, now))))
    # One caller wins the claim, so a webhook and a waiting page do not both ask.
    if not claimed.update(checked_at=now, checks=F('checks') + 1):
        return None
    # Asked with the kassa the payment was opened with: another kassa's key cannot see it.
    return {'cfg': _config(row.channel), 'api': row.api, 'id': row.provider_id, 'pk': row.pk}


def look(question):
    """Ask inPAY where the payment stands. No database is touched; raises inpay.Unavailable or inpay.Refused."""
    return inpay.fetch(question['cfg'], question['api'], question['id'])


def lookup_refused(refused, channel='web'):
    """inPAY understood a question about a payment and would not answer it: only the owner can put that right."""
    place = kassa(channel)
    _alert('inpay_lookup_refused' + ('_bot' if place == 'bot' else ''),
           f'⚠️ inPAY refused to say how a payment {"in the bot" if place == "bot" else "on the website"} stands ({refused.code}).'
           f'\nThose payments cannot be confirmed until this is fixed. Check the key in {KASSA_SETTINGS[place]} '
           '(press Test connection) and that the kassa is active in the inPAY cabinet.', once_an_hour=True)


def _mismatch(row, remote):
    if remote['amount'] != row.amount:
        return 'amount_mismatch'
    if remote['currency'] != row.currency:
        return 'currency_mismatch'
    if remote['live'] != row.livemode:
        return 'mode_mismatch'
    if remote['reference'] and remote['reference'] != str(row.id):
        return 'reference_mismatch'
    return ''


@transaction.atomic
def apply(pk, remote):
    """Act on inPAY's answer about one payment. Safe to repeat: a paid row is left as it is."""
    from apps.core.models import Account
    from .models import Checkout, OfferVersion
    from .periods import grant
    from .services import PERIOD
    row = Checkout.objects.select_for_update().get(pk=pk)
    if row.status in FINAL:
        return row
    now = timezone.now()
    if remote['state'] == 'paid':
        problem = _mismatch(row, remote)
        if problem:
            # Money was taken for something this row does not describe. Nothing
            # is granted on a guess: the owner looks at it.
            if row.status != 'review':
                from apps.core.links import admin_url
                row.status, row.failure = 'review', problem
                row.save(update_fields=['status', 'failure'])
                _action(row, 'checkout.review', {'problem': problem, 'reported_amount': remote['amount'],
                                                 'reported_currency': remote['currency'], 'reported_live': remote['live']})
                payer = Account.objects.filter(pk=row.account_id).first()
                reported = f"{_money(remote['amount'])} {remote['currency']}" if remote['amount'] is not None else 'no amount'
                link = admin_url(f'/ops/users/{row.account_id}')
                _alert('inpay_review', '⚠️ inPAY payment needs a look: ' + problem +
                       f"\n{row.plan.title()} · {_money(row.amount)} so'm expected, inPAY reports {reported}"
                       f"{'' if remote['live'] else ' (test mode)'} · inPAY id {row.provider_id}"
                       f"\nCustomer: {(payer.display_name if payer else '') or (payer.telegram_user_id if payer else '') or row.account_id}"
                       + (f'\n{link}' if link else '') +
                       '\nNo plan was granted. Compare it with the payment in the inPAY cabinet; if the money is right, '
                       'give the plan on the customer\'s page, or return the money in inPAY.')
            return row
        account = Account.objects.select_for_update().get(pk=row.account_id)
        period = None
        if row.livemode:
            # One offer per plan and price, as a card transfer has: a payment
            # buys the plan, and its limits are read from the plan as it stands.
            offer, _ = OfferVersion.objects.get_or_create(
                id=f'inpay:{row.plan}:{row.amount}',
                defaults={'offer_id': f'inpay_{row.plan}', 'version': 'inpay-v1', 'kind': 'subscription',
                          'plan': row.plan, 'name': f'{row.plan.title()} · inPAY', 'period_seconds': PERIOD,
                          'sandbox': False, 'enabled': False})
            regular = row.regular_amount
            snapshot = {'id': offer.id, 'offer_id': offer.offer_id, 'version': offer.version, 'kind': offer.kind,
                        'plan': row.plan, 'name': offer.name, 'currency': row.currency, 'price': row.amount,
                        'regular_price': regular, 'discounted': regular is not None and row.amount < regular,
                        'provider': PROVIDER, 'provider_payment': row.provider_id,
                        'period_seconds': PERIOD_DAYS * 86400, 'period_days': PERIOD_DAYS}
            row.payment, period = grant(account, row.plan, PERIOD_DAYS, provider=PROVIDER,
                                        charge=f'{PROVIDER}:{row.provider_id}', amount=row.amount,
                                        currency=row.currency, offer=offer, snapshot=snapshot, occurred_at=now, now=now)
        row.status, row.paid_at, row.failure = 'paid', now, ''
        row.receipt_url = remote.get('receipt') or ''
        row.save()
        _notice(row, 'paid' if row.livemode else 'paid_test')
        _action(row, 'checkout.paid', {'days': PERIOD_DAYS, 'ends_at': period.ends_at.isoformat()} if period else {})
        if row.livemode:
            from apps.core.links import admin_url
            link = admin_url(f'/ops/payments/{row.payment_id}')
            _alert('inpay_paid', "⚡ inPAY payment received\n"
                   f"{row.plan.title()} · {_money(row.amount)} so'm\n"
                   f"From: {account.display_name or account.telegram_user_id or account.pk}" + (f'\n{link}' if link else ''))
        return row
    if remote['state'] in ('failed', 'cancelled') and row.status == 'pending':
        row.status, row.failure = remote['state'], 'payment_' + remote['state']
        row.save(update_fields=['status', 'failure'])
    return row


def refresh(row, force=False, strict=False):
    """Ask inPAY about this payment if it is time to, and act on the answer; returns the row as it now stands.

    `strict` lets inPAY's silence through as an exception, for the webhook,
    which answers inPAY with an error so that it tries again.
    """
    question = due(row, force)
    if question is None:
        return row
    try:
        remote = look(question)
    except inpay.Refused as refused:
        lookup_refused(refused, row.channel)
        if strict:
            raise
        return row
    except inpay.Unavailable:
        if strict:
            raise
        return row
    return apply(row.pk, remote)


def latest(account):
    """The automatic payment the billing page should show, if any: the open one, else a recent result."""
    from .models import Checkout
    now = timezone.now()
    rows = Checkout.objects.filter(account=account).exclude(status='created')
    return (rows.filter(status__in=('pending', 'review'), expires_at__gt=now).order_by('-created_at').first()
            or rows.filter(created_at__gt=now - timedelta(days=SHOWN_DAYS)).order_by('-created_at').first())


def _reconcile_due(row, now):
    """Whether the periodic check should ask about a payment nobody is watching."""
    age = now - row.created_at
    if age < timedelta(minutes=2):
        return False
    if row.status != 'pending':
        # Closed on our side, still payable on inPAY's page for a while: looked at now and then.
        wait = timedelta(minutes=30)
    else:
        wait = timedelta(minutes=5) if age < timedelta(hours=1) else timedelta(minutes=30) if age < timedelta(hours=6) else timedelta(hours=2)
    return row.checked_at is None or now - row.checked_at >= wait


def housekeeping(now=None):
    """Close what was never paid, ask inPAY about payments still open, and queue renewal reminders.

    The webhook is how a payment is normally learned of; this is for the one
    that never arrived. It asks about a few payments a run, so inPAY's request
    limit is never spent on waiting.
    """
    from .models import Checkout, SubscriptionPeriod
    now = now or timezone.now()
    # A row inPAY was never asked about is nothing to wait for.
    Checkout.objects.filter(status='created', created_at__lte=now - timedelta(minutes=10)).update(
        status='failed', failure='never_opened')
    # Newest first: a payment just made is the one most likely paid, and old
    # abandoned ones must not stand in its way. Every row still open is looked
    # at (a day's worth, plus the closed ones of the last two), so none is
    # skipped for sitting behind others.
    asked = {'v1': 0, 'v2': 0}
    candidates = Checkout.objects.filter(
        Q(status='pending') | Q(status__in=('failed', 'cancelled', 'expired'), created_at__gt=now - timedelta(hours=REOPEN_HOURS)),
    ).exclude(provider_id='').order_by('-created_at')
    for row in candidates.iterator():
        batch = RECONCILE_BATCH.get(row.api, 3)
        if asked.get(row.api, 0) >= batch:
            if all(asked.get(api, 0) >= limit for api, limit in RECONCILE_BATCH.items()):
                break
            continue
        if not _reconcile_due(row, now):
            continue
        asked[row.api] = asked.get(row.api, 0) + 1
        try:
            refresh(row, force=True)
        except Exception:
            logger.exception('inPAY payment %s could not be checked', row.pk)
    # After the last look: a payment made in its final minutes is still found,
    # and one made later still arrives by webhook and is honoured.
    expired = Checkout.objects.filter(status='pending', expires_at__lte=now).update(status='expired')
    ending = SubscriptionPeriod.objects.filter(
        payment__provider=PROVIDER, revoked_at__isnull=True, ends_at__gt=now,
        ends_at__lte=now + timedelta(days=REMINDER_DAYS)).select_related('payment')
    for period in ending:
        later = SubscriptionPeriod.objects.filter(account_id=period.account_id, revoked_at__isnull=True,
                                                  ends_at__gt=period.ends_at).exists()
        row = Checkout.objects.filter(payment=period.payment).first()
        if row and not later:
            _notice(row, 'renewal_reminder')
    return {'asked': sum(asked.values()), 'expired': expired}


def refund(payment, actor, reason):
    """The owner returned the money through inPAY: the plan is taken back.

    inPAY refunds nothing through its API, so this only records what the owner
    has already done in the inPAY cabinet.
    """
    from .models import Checkout
    from .services import refund_payment
    row = Checkout.objects.filter(payment=payment).first()
    if not row or row.status != 'paid':
        raise DomainError('manual_payment_not_refundable', 409)
    return refund_payment(payment, reason, actor=actor)


def signature_refused(channel='web'):
    """A webhook arrived signed with something other than the kassa's saved secret: tell the owner, at most hourly."""
    place = kassa(channel)
    _alert('inpay_signature' + ('_bot' if place == 'bot' else ''),
           '⚠️ An inPAY webhook did not match the saved signing secret and was turned away.'
           '\nPayments are still confirmed, a few minutes later, by asking inPAY directly. If the kassa\'s secret was '
           f'changed, save the new one in {KASSA_SETTINGS[place]} (or clear it and press Test connection).',
           once_an_hour=True)


def _money(amount):
    return f'{amount:,}'.replace(',', ' ')


def _notice(row, kind):
    from .models import PaymentNotice
    PaymentNotice.objects.get_or_create(checkout=row, kind=kind)


def _alert(kind, text, once_an_hour=False):
    """A Telegram message to the owner (telegram/staff_alerts.py), never raising into a payment."""
    from apps.core.models import StaffAlert
    try:
        # Its own savepoint: a failure here is undone alone, inside whatever transaction the payment holds.
        with transaction.atomic():
            if once_an_hour and StaffAlert.objects.filter(kind=kind, created_at__gt=timezone.now() - timedelta(hours=1)).exists():
                return
            StaffAlert.objects.create(kind=kind, text=text)
    except Exception:
        logger.exception('inPAY alert %s could not be queued', kind)


def _action(row, action, metadata):
    from .models import CommerceAction
    CommerceAction.objects.create(account_id=row.account_id, actor=None, action=action, target=str(row.id),
                                  metadata={'plan': row.plan, 'amount': row.amount, 'currency': row.currency,
                                            'provider_id': row.provider_id, 'live': row.livemode, **metadata})
