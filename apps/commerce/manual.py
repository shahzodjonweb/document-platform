"""Card transfers to the owner's card, reviewed by hand.

The customer picks a plan, is shown the card and the price, transfers the money
in their own bank app and uploads the receipt. The owner checks their bank app
and approves or rejects. Nothing is granted until they approve.

Approval writes the same records a Telegram payment does — Invoice, Payment,
Subscription, SubscriptionPeriod and one grant per meter — tagged `manual`. So
the plan, its full allowance, "paid until" and a refund that takes it back all
work through the code every paid plan already uses.

A receipt is evidence for a person to look at, not proof: the owner approves
only after seeing the money arrive. What this module guarantees is narrower —
the receipt is safe to keep and show, a reused one is flagged, and it is kept
no longer than needed.
"""
import hashlib
import io
import secrets
import warnings
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.errors import DomainError

PLANS = ('plus', 'premium')
RANK = {'free': 0, 'plus': 1, 'premium': 2}
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


def prices():
    """{plan: so'm} for every paid plan on sale by card transfer."""
    from apps.core.policy import limits_for_plan
    offered = {}
    for plan in PLANS:
        price = limits_for_plan(plan).get('price_uzs')
        if type(price) is int and price > 0:
            offered[plan] = price
    return offered


def options():
    """What a customer may choose right now. Automatic payment is not built yet."""
    config = _config()
    offered = prices() if config['ready'] else {}
    return {'enabled': bool(offered), 'currency': 'UZS', 'period_days': 30,
            'plans': [{'plan': plan, 'price': price} for plan, price in offered.items()],
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
    from .models import ManualPayment, Subscription
    from .services import active_period
    if plan not in PLANS:
        raise DomainError('invalid_plan')
    offered = prices() if _config()['ready'] else {}
    if plan not in offered:
        raise DomainError('checkout_disabled', 409)
    account = Account.objects.select_for_update().get(pk=account.pk)
    existing = open_payment(account)
    if existing and existing.status == 'awaiting' and existing.expires_at <= timezone.now():
        existing.status = 'expired'
        existing.save(update_fields=['status'])
        existing = None
    if existing:
        if existing.plan == plan:
            return existing, False
        # A receipt already sent waits for the owner: one payment at a time.
        if existing.status == 'submitted':
            raise DomainError('manual_payment_pending', 409)
        existing.status = 'cancelled'
        existing.save(update_fields=['status'])
    # Telegram Stars is off in production, but a Stars subscription that renews
    # by itself must not be paid for twice.
    stars = Subscription.objects.filter(account=account, provider='telegram_stars', renewal_enabled=True).first()
    if stars and active_period(account):
        raise DomainError('subscription_already_active', 409)
    auth_limit('manual-payment', str(account.pk), 10, 86400)
    config = _config()
    card = {'number': config['card_number'], 'holder': config['card_holder'], 'label': config['card_label']}
    for _ in range(5):
        try:
            with transaction.atomic():
                payment = ManualPayment.objects.create(
                    reference=_reference(), account=account, plan=plan, amount=offered[plan], card=card,
                    channel=channel if channel in ('web', 'bot') else 'web',
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
    from PIL import Image, ImageOps
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw), formats=['JPEG', 'PNG', 'WEBP']) as picture:
                if picture.width * picture.height > RECEIPT_PIXELS:
                    raise ValueError('pixels')
                picture.load()
                clean = ImageOps.exif_transpose(picture).convert('RGB')
    except Exception:
        raise DomainError('invalid_receipt') from None
    clean.thumbnail((RECEIPT_EDGE, RECEIPT_EDGE))
    out = io.BytesIO()
    # No `exif=`: nothing from the customer's file survives but the pixels.
    clean.save(out, 'JPEG', quality=85, optimize=True)
    return out.getvalue(), 'image/jpeg', 'jpg'


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
    from apps.core.customer_auth import auth_limit
    from apps.core.services import storage_path
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
            storage_path(key).unlink(missing_ok=True)
            raise DomainError('manual_payment_closed', 409)
        replaced = payment.receipt_key
        payment.receipt_key, payment.receipt_type, payment.receipt_size = key, mime, len(data)
        payment.receipt_sha256, payment.payer_note = fingerprint, note
        payment.status, payment.submitted_at = 'submitted', timezone.now()
        if channel in ('web', 'bot'):
            payment.channel = channel
        payment.save()
        _notice(payment, 'staff_new')
    if replaced:
        storage_path(replaced).unlink(missing_ok=True)
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
    """The owner saw the money arrive: the plan starts, with its full allowance."""
    from apps.core.models import Account, UsageGrant
    from apps.core.policy import METERS, limits_for_plan
    from .models import (Invoice, ManualPayment, OfferVersion, Payment, PaymentGrant, Subscription,
                         SubscriptionPeriod)
    from .services import PERIOD, active_period, offer_data, refresh_account_entitlement
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
    # The plan as the owner has set it today is what this payment buys, and
    # it is frozen here: a later change to the plan does not reach back.
    allowance = limits_for_plan(payment.plan)
    quantities = {meter: int(allowance.get(meter) or 0) for meter in METERS}
    signature = hashlib.sha256(repr(sorted(quantities.items())).encode()).hexdigest()[:10]
    offer, _ = OfferVersion.objects.get_or_create(
        id=f'manual:{payment.plan}:{payment.amount}:{signature}',
        defaults={'offer_id': f'manual_{payment.plan}', 'version': 'manual-v1', 'kind': 'subscription',
                  'plan': payment.plan, 'name': f'{payment.plan.title()} · card transfer', 'price_xtr': None,
                  'period_seconds': PERIOD, 'quantities': quantities, 'sandbox': False, 'enabled': False})
    snapshot = {**offer_data(offer), 'currency': payment.currency, 'price': payment.amount, 'provider': 'manual'}
    charge = f'manual:{payment.id}'
    invoice = Invoice.objects.create(
        account=account, offer=offer, snapshot=snapshot, amount_xtr=payment.amount, currency=payment.currency,
        status='paid', idempotency_key=charge, request_hash=hashlib.sha256(charge.encode()).hexdigest(),
        payload_hash='', sandbox=False, provider='manual', expires_at=now, paid_at=now)
    start, extension = _period_start(account, payment.plan, now)
    end = start + timedelta(seconds=PERIOD)
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
    for meter, quantity in quantities.items():
        if not quantity:
            continue
        grant = UsageGrant.objects.create(account=account, meter=meter, source='included',
                                          source_id=f'payment:{charge}:{meter}', quantity=quantity,
                                          valid_from=start, expires_at=end)
        PaymentGrant.objects.create(payment=paid, grant=grant)
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
            {'plan': payment.plan, 'amount': payment.amount, 'currency': payment.currency,
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
    """The owner returned the money: the plan and its allowance are taken back."""
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
    from apps.core.services import storage_path
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
        storage_path(payment.receipt_key).unlink(missing_ok=True)
        ManualPayment.objects.filter(pk=payment.pk).update(receipt_key='', receipt_deleted_at=now)
        purged += 1
    return {'expired': expired, 'purged': purged}
