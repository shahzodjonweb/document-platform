"""Card transfers to the owner's card, reviewed by hand.

The customer picks a plan, is shown the card and the price, transfers the money
in their own bank app and uploads the receipt. The owner checks their bank app
and approves or rejects. Nothing is granted until they approve.

Approval writes the same records a Telegram payment does — Invoice, Payment,
Subscription and SubscriptionPeriod — tagged `manual`. So the plan, its weekly
limits, "paid until" and a refund that takes it back all work through the code
every paid plan already uses.

A receipt is evidence for a person to look at, not proof: the owner approves
only after seeing the money arrive. What this module guarantees is narrower —
the receipt is safe to keep and show, a reused one is flagged, and it is kept
no longer than needed.
"""
import hashlib
import io
import secrets
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.errors import DomainError

PLANS = ('plus', 'premium')
RANK = {'free': 0, 'plus': 1, 'premium': 2}
PERIOD_DAYS = 30
AWAIT_HOURS = 48
RECEIPT_BYTES = 10 * 1024 * 1024
RECEIPT_PIXELS = 40_000_000
RECEIPT_EDGE = 2400
RECEIPT_PDF_PAGES = 10
RECEIPT_RETENTION_DAYS = 90
REMINDER_DAYS = 3
_REFERENCE = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def _config():
    from operations.integrations import manual_payment_config
    return manual_payment_config()


def offers():
    """{plan: pricing.plan_price(plan)} for every paid plan on sale by card transfer."""
    from .pricing import offers as priced
    return priced()


def prices():
    """{plan: so'm} the customer pays today for every paid plan on sale: the discount while one runs."""
    return {plan: offer['price'] for plan, offer in offers().items()}


def regular_prices():
    """{plan: so'm} for the same plans, before any discount."""
    return {plan: offer['regular'] for plan, offer in offers().items()}


def options():
    """What a customer may choose right now. Automatic payment is not built yet."""
    config = _config()
    offered = offers() if config['ready'] else {}
    return {'enabled': bool(offered), 'currency': 'UZS', 'period_days': PERIOD_DAYS,
            'plans': [{'plan': plan, 'price': offer['price'], 'regular_price': offer['regular'],
                       'discount': offer['discount']} for plan, offer in offered.items()],
            'automatic': {'available': False}}


def open_payment(account):
    from .models import ManualPayment
    return ManualPayment.objects.filter(account=account, status__in=ManualPayment.OPEN).first()


def latest_payment(account):
    """The open request, or the most recent decision for the customer to see."""
    from .models import ManualPayment
    return open_payment(account) or ManualPayment.objects.filter(account=account).order_by('-created_at').first()


def _reference():
    return 'PM-' + ''.join(secrets.choice(_REFERENCE) for _ in range(5))


@transaction.atomic
def create(account, plan, channel='web'):
    """A request to pay for `plan`, or the one already open for it."""
    from apps.core.customer_auth import auth_limit
    from apps.core.models import Account
    from .models import ManualPayment
    if plan not in PLANS:
        raise DomainError('invalid_plan')
    offered = offers() if _config()['ready'] else {}
    if plan not in offered:
        raise DomainError('checkout_disabled', 409)
    # Today's price, and the regular one it is set against: the request keeps
    # both, so a request opened at a discount is known as one later on.
    price, regular = offered[plan]['price'], offered[plan]['regular']
    account = Account.objects.select_for_update().get(pk=account.pk)
    existing = open_payment(account)
    if existing and existing.status == 'awaiting' and existing.expires_at <= timezone.now():
        existing.status = 'expired'
        existing.save(update_fields=['status'])
        existing = None
    if existing:
        # A request opened at another price, with nothing sent yet, is opened
        # again at today's: the customer has just read the price on the plans
        # page, and the card screen must not ask for a different one. That
        # covers a discount starting (down to it) and one ending (back up to
        # the regular price). A receipt already sent at the old price waits
        # for the owner (period_days).
        if existing.plan == plan and not (existing.status == 'awaiting' and existing.amount != price):
            return existing, False
        # A receipt already sent waits for the owner: one payment at a time.
        if existing.status == 'submitted':
            raise DomainError('manual_payment_pending', 409)
        existing.status = 'cancelled'
        existing.save(update_fields=['status'])
    auth_limit('manual-payment', str(account.pk), 10, 86400)
    config = _config()
    card = {'number': config['card_number'], 'holder': config['card_holder'], 'label': config['card_label']}
    for _ in range(5):
        try:
            with transaction.atomic():
                payment = ManualPayment.objects.create(
                    reference=_reference(), account=account, plan=plan, amount=price, regular_amount=regular,
                    card=card, channel=channel if channel in ('web', 'bot') else 'web',
                    expires_at=timezone.now() + timedelta(hours=AWAIT_HOURS))
            break
        except IntegrityError:
            continue
    else:
        raise DomainError('manual_payment_unavailable', 503, retryable=True)
    _action(account, None, 'manual_payment.created', payment, {'plan': plan, 'amount': payment.amount})
    return payment, True


def _clean_receipt(raw):
    """Untrusted receipt bytes as something safe to keep: (bytes, mime, extension).

    A photo is decoded and re-encoded, which drops its location and every other
    piece of metadata; a PDF is kept as it is and is only ever offered to staff
    as a download.
    """
    if not raw or len(raw) > RECEIPT_BYTES:
        raise DomainError('receipt_too_large', 413)
    if raw[:5] == b'%PDF-':
        from pypdf import PdfReader
        try:
            reader = PdfReader(io.BytesIO(raw))
            if reader.is_encrypted or not 1 <= len(reader.pages) <= RECEIPT_PDF_PAGES:
                raise ValueError('pdf')
        except Exception:
            raise DomainError('invalid_receipt') from None
        return raw, 'application/pdf', 'pdf'
    from apps.core.images import clean_photo
    try:
        data = clean_photo(raw, max_bytes=RECEIPT_BYTES, max_pixels=RECEIPT_PIXELS, edge=RECEIPT_EDGE)
    except Exception:
        raise DomainError('invalid_receipt') from None
    return data, 'image/jpeg', 'jpg'


def _store(payment, data, extension):
    import os
    from apps.core.services import storage_path
    key = f'receipts/{payment.id}/{secrets.token_hex(8)}.{extension}'
    path = storage_path(key)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('xb') as output:
        os.chmod(path, 0o600)
        output.write(data)
    return key


def attach_receipt(account, payment_id, raw, note='', channel=None):
    """Keep the customer's receipt and put the payment in front of the owner."""
    from apps.core import storage
    from apps.core.customer_auth import auth_limit
    from .models import ManualPayment
    payment = ManualPayment.objects.filter(pk=payment_id, account=account).first()
    if not payment:
        raise DomainError('not_found', 404)
    if payment.status not in ManualPayment.OPEN:
        raise DomainError('manual_payment_closed', 409)
    if payment.status == 'awaiting' and payment.expires_at <= timezone.now():
        raise DomainError('manual_payment_expired', 409)
    auth_limit('manual-receipt', str(account.pk), 10, 3600)
    fingerprint = hashlib.sha256(raw or b'').hexdigest()
    data, mime, extension = _clean_receipt(raw)
    key = _store(payment, data, extension)
    note = ' '.join(str(note or '').split())[:120]
    with transaction.atomic():
        payment = ManualPayment.objects.select_for_update().get(pk=payment.pk)
        if payment.status not in ManualPayment.OPEN:
            storage.delete(key)
            raise DomainError('manual_payment_closed', 409)
        replaced = payment.receipt_key
        payment.receipt_key, payment.receipt_type, payment.receipt_size = key, mime, len(data)
        payment.receipt_sha256, payment.payer_note = fingerprint, note
        payment.status, payment.submitted_at = 'submitted', timezone.now()
        if channel in ('web', 'bot'):
            payment.channel = channel
        payment.save()
        storage.save(key, mime)
        _notice(payment, 'staff_new')
    if replaced:
        storage.delete(replaced)
    _action(account, None, 'manual_payment.submitted', payment, {'receipt_type': mime})
    return payment


def cancel(account, payment_id):
    from .models import ManualPayment
    with transaction.atomic():
        payment = ManualPayment.objects.select_for_update().filter(pk=payment_id, account=account).first()
        if not payment:
            raise DomainError('not_found', 404)
        if payment.status not in ManualPayment.OPEN:
            raise DomainError('manual_payment_closed', 409)
        payment.status = 'cancelled'
        payment.save(update_fields=['status'])
    _action(account, None, 'manual_payment.cancelled', payment, {})
    return payment


def duplicates(payment):
    """Other payments that sent exactly the same receipt file."""
    from .models import ManualPayment
    if not payment.receipt_sha256:
        return ManualPayment.objects.none()
    return ManualPayment.objects.filter(receipt_sha256=payment.receipt_sha256).exclude(pk=payment.pk)


def _require_finance(actor):
    if not actor or not actor.is_staff or not (
            actor.is_superuser or actor.groups.filter(name__in=('Finance', 'Administrator')).exists()):
        raise DomainError('permission_denied', 403)


def period_days(payment):
    """Whole days of the plan that approving this transfer gives: 30, or more.

    A request opened before a price fell asked for the old amount, and the
    customer may well have sent it. That money buys time at today's price
    rather than one ordinary period, so an overpayment becomes a longer one.
    A price that rose since, or a plan no longer on sale, never gives less
    than the 30 days the customer was promised.

    "Today's price" here is the regular one, never a discount: a discount is
    a lower price for the same 30 days, so the full price sent while one runs
    buys 30 days, not 40, and a discounted receipt buys its 30.
    """
    price = regular_prices().get(payment.plan)
    if not price or payment.amount <= price:
        return PERIOD_DAYS
    return max(PERIOD_DAYS, PERIOD_DAYS * payment.amount // price)


def _period_start(account, plan, now):
    """When a newly paid period starts.

    The same plan or a lower one bought while a paid period runs follows it,
    so nothing already paid for is cut short. A higher plan starts at once.
    """
    from .models import SubscriptionPeriod
    latest = SubscriptionPeriod.objects.filter(account=account, ends_at__gt=now, revoked_at__isnull=True,
                                               sandbox=False).order_by('-ends_at').first()
    if latest and RANK.get(plan, 0) <= RANK.get(latest.plan, 0):
        return latest.ends_at, True
    return now, False


@transaction.atomic
def approve(payment_id, actor, note=''):
    """The owner saw the money arrive: the plan starts, with its weekly limits."""
    from apps.core.models import Account
    from .models import Invoice, ManualPayment, OfferVersion, Payment, Subscription, SubscriptionPeriod
    from .services import PERIOD, active_period, refresh_account_entitlement
    _require_finance(actor)
    payment = ManualPayment.objects.select_for_update().filter(pk=payment_id).first()
    if not payment:
        raise DomainError('not_found', 404)
    if payment.status == 'approved':
        return payment
    if payment.status not in ManualPayment.OPEN:
        raise DomainError('manual_payment_closed', 409)
    account = Account.objects.select_for_update().get(pk=payment.account_id)
    now = timezone.now()
    # A payment buys the plan, not a copy of its numbers: the weekly limits are
    # read from the plan as it stands, so one offer per plan and price is enough.
    # A discounted purchase and a full-price one are two offers, by the amount.
    offer, _ = OfferVersion.objects.get_or_create(
        id=f'manual:{payment.plan}:{payment.amount}',
        defaults={'offer_id': f'manual_{payment.plan}', 'version': 'manual-v2', 'kind': 'subscription',
                  'plan': payment.plan, 'name': f'{payment.plan.title()} · card transfer',
                  'period_seconds': PERIOD, 'sandbox': False, 'enabled': False})
    days = period_days(payment)
    # What was bought, as it stood when the request was opened: the invoice
    # keeps it after the prices and the discount have moved on. A request from
    # before discounts carries no regular price of its own, and was not one.
    regular = payment.regular_amount
    snapshot = {'id': offer.id, 'offer_id': offer.offer_id, 'version': offer.version, 'kind': offer.kind,
                'plan': payment.plan, 'name': offer.name, 'currency': payment.currency, 'price': payment.amount,
                'regular_price': regular, 'discounted': regular is not None and payment.amount < regular,
                'provider': 'manual', 'period_seconds': days * 86400, 'period_days': days}
    charge = f'manual:{payment.id}'
    invoice = Invoice.objects.create(
        account=account, offer=offer, snapshot=snapshot, amount_xtr=payment.amount, currency=payment.currency,
        status='paid', idempotency_key=charge, request_hash=hashlib.sha256(charge.encode()).hexdigest(),
        payload_hash='', sandbox=False, provider='manual', expires_at=now, paid_at=now)
    start, extension = _period_start(account, payment.plan, now)
    end = start + timedelta(days=days)
    paid = Payment.objects.create(
        account=account, invoice=invoice, provider_charge_id=charge, amount_xtr=payment.amount,
        currency=payment.currency, kind='subscription', plan=payment.plan, is_renewal=extension,
        sandbox=False, provider='manual', occurred_at=payment.submitted_at or now)
    subscription = Subscription.objects.select_for_update().filter(account=account).first()
    was_manual = subscription is not None and subscription.provider == 'manual'
    if subscription is None:
        subscription = Subscription.objects.create(
            account=account, invoice=invoice, offer=offer, plan=payment.plan, status='active',
            renewal_enabled=False, first_charge_id=charge, current_period_end=end, sandbox=False,
            provider='manual')
    period = SubscriptionPeriod.objects.create(subscription=subscription, payment=paid, account=account,
                                               plan=payment.plan, starts_at=start, ends_at=end, sandbox=False)
    current = active_period(account) or period
    # An earlier manual period may still run past this one's start; a lapsed
    # Telegram subscription's dates mean nothing to it.
    subscription.current_period_end = max(subscription.current_period_end, end) if was_manual else end
    if not was_manual:
        subscription.first_charge_id = charge
    subscription.invoice, subscription.offer = invoice, offer
    subscription.plan, subscription.status = current.plan, 'active'
    subscription.renewal_enabled, subscription.provider, subscription.sandbox = False, 'manual', False
    subscription.scheduled_plan, subscription.scheduled_at = '', None
    subscription.save()
    payment.status, payment.decided_at, payment.decided_by = 'approved', now, actor
    payment.decision_note, payment.payment = str(note or '').strip()[:500], paid
    payment.save()
    refresh_account_entitlement(account)
    _notice(payment, 'approved')
    _action(account, actor, 'manual_payment.approved', payment,
            {'plan': payment.plan, 'amount': payment.amount, 'currency': payment.currency, 'days': days,
             'starts_at': start.isoformat(), 'ends_at': end.isoformat()}, reason=note)
    return payment


# Ready-made messages for a rejected transfer, sent in the customer's language.
REJECTIONS = {
    'not_received': {'en': "We didn't receive the transfer.",
                     'uz': 'O‘tkazma bizga kelib tushmadi.',
                     'ru': 'Перевод к нам не поступил.'},
    'amount_mismatch': {'en': "The amount we received doesn't match the plan price.",
                        'uz': 'Kelib tushgan summa tarif narxiga mos emas.',
                        'ru': 'Полученная сумма не совпадает с ценой тарифа.'},
    'unreadable': {'en': "We couldn't read the receipt. Please send a clearer one.",
                   'uz': 'Kvitansiyani o‘qib bo‘lmadi. Aniqroq rasmini yuboring.',
                   'ru': 'Не удалось прочитать квитанцию. Пришлите, пожалуйста, более чёткую.'},
}


def rejection_message(payment, choice='', custom=''):
    """The owner's own words, or a ready-made message in the customer's language."""
    custom = ' '.join(str(custom or '').split())
    if custom:
        return custom
    texts = REJECTIONS.get(choice)
    if not texts:
        return ''
    return texts.get(payment.account.locale, texts['en'])


@transaction.atomic
def reject(payment_id, actor, reason):
    """The money did not arrive, or not as described. The customer sees why."""
    from .models import ManualPayment
    _require_finance(actor)
    reason = ' '.join(str(reason or '').split())
    if not 5 <= len(reason) <= 500:
        raise DomainError('audit_reason_required')
    payment = ManualPayment.objects.select_for_update().filter(pk=payment_id).first()
    if not payment:
        raise DomainError('not_found', 404)
    if payment.status == 'rejected':
        return payment
    if payment.status not in ManualPayment.OPEN:
        raise DomainError('manual_payment_closed', 409)
    payment.status, payment.decided_at, payment.decided_by = 'rejected', timezone.now(), actor
    payment.decision_note = reason
    payment.save(update_fields=['status', 'decided_at', 'decided_by', 'decision_note'])
    _notice(payment, 'rejected')
    _action(payment.account, actor, 'manual_payment.rejected', payment, {'plan': payment.plan}, reason=reason)
    return payment


def refund(payment_id, actor, reason):
    """The owner returned the money: the plan is taken back."""
    from .models import ManualPayment
    from .services import refund_payment
    payment = ManualPayment.objects.select_related('payment').filter(pk=payment_id).first()
    if not payment:
        raise DomainError('not_found', 404)
    if payment.status != 'approved' or payment.payment is None:
        raise DomainError('manual_payment_not_refundable', 409)
    return refund_payment(payment.payment, reason, actor=actor)


def _notice(payment, kind):
    from .models import PaymentNotice
    PaymentNotice.objects.get_or_create(manual=payment, kind=kind)


def _action(account, actor, action, payment, metadata, reason=''):
    from .models import CommerceAction
    CommerceAction.objects.create(account=account, actor=actor, action=action, target=str(payment.id),
                                  reason=str(reason or '')[:500],
                                  metadata={'reference': payment.reference, **metadata})


def housekeeping(now=None):
    """Expire stale requests, queue renewal reminders, delete old receipts."""
    from apps.core import storage
    from .models import ManualPayment, SubscriptionPeriod
    now = now or timezone.now()
    expired = ManualPayment.objects.filter(status='awaiting', expires_at__lte=now).update(status='expired')
    # A paid period that ends within a few days, with nothing paid after it.
    ending = SubscriptionPeriod.objects.filter(
        payment__provider='manual', revoked_at__isnull=True, ends_at__gt=now,
        ends_at__lte=now + timedelta(days=REMINDER_DAYS)).select_related('payment')
    for period in ending:
        later = SubscriptionPeriod.objects.filter(account_id=period.account_id, revoked_at__isnull=True,
                                                  ends_at__gt=period.ends_at).exists()
        manual = ManualPayment.objects.filter(payment=period.payment).first()
        if manual and not later:
            _notice(manual, 'renewal_reminder')
    cutoff = now - timedelta(days=RECEIPT_RETENTION_DAYS)
    stale = ManualPayment.objects.filter(decided_at__lte=cutoff, receipt_deleted_at__isnull=True).exclude(receipt_key='')
    purged = 0
    for payment in stale.iterator():
        storage.delete(payment.receipt_key)
        ManualPayment.objects.filter(pk=payment.pk).update(receipt_key='', receipt_deleted_at=now)
        purged += 1
    return {'expired': expired, 'purged': purged}
