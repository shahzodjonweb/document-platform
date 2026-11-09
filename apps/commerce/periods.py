"""A stretch of a plan, written the one way every plan is held.

A card transfer the owner approved and the Plus months earned by inviting
friends both become the same records: an Invoice, a Payment, the account's
Subscription and a SubscriptionPeriod. So the plan, its weekly limits, "until
when", and what follows what all come from the code every plan already uses.
Only `provider` tells them apart: 'manual' for a card transfer, 'referral' for
an invitation reward (which costs nothing and is never money).
"""
import hashlib
from datetime import timedelta

from django.utils import timezone

RANK = {'free': 0, 'plus': 1, 'premium': 2}
# Subscriptions this deployment writes itself, and never renews: their periods
# are laid end to end, so the subscription runs to the end of the last one.
OWN = ('manual', 'referral')


def start_for(account, plan, now):
    """When a new period of `plan` starts, and whether it extends one already held.

    The same plan or a lower one granted while a period runs follows it, so
    nothing already held is cut short and nothing granted is swallowed by a
    higher plan. A higher plan starts at once.
    """
    from .models import SubscriptionPeriod
    latest = SubscriptionPeriod.objects.filter(account=account, ends_at__gt=now, revoked_at__isnull=True,
                                               sandbox=False).order_by('-ends_at').first()
    if latest and RANK.get(plan, 0) <= RANK.get(latest.plan, 0):
        return latest.ends_at, True
    return now, False


def grant(account, plan, days, *, provider, charge, amount, currency, offer, snapshot, occurred_at, now=None):
    """Write one period of `plan` lasting `days`; returns (payment, period).

    The caller holds the account's row lock and has checked that this grant is
    due; `charge` is unique per grant, so a repeat fails rather than doubling.
    """
    from .models import Invoice, Payment, Subscription, SubscriptionPeriod
    from .services import active_period, refresh_account_entitlement
    now = now or timezone.now()
    invoice = Invoice.objects.create(
        account=account, offer=offer, snapshot=snapshot, amount_xtr=amount, currency=currency,
        status='paid', idempotency_key=charge, request_hash=hashlib.sha256(charge.encode()).hexdigest(),
        payload_hash='', sandbox=False, provider=provider, expires_at=now, paid_at=now)
    start, extension = start_for(account, plan, now)
    end = start + timedelta(days=days)
    paid = Payment.objects.create(
        account=account, invoice=invoice, provider_charge_id=charge, amount_xtr=amount,
        currency=currency, kind='subscription', plan=plan, is_renewal=extension,
        sandbox=False, provider=provider, occurred_at=occurred_at or now)
    subscription = Subscription.objects.select_for_update().filter(account=account).first()
    own = subscription is not None and subscription.provider in OWN
    if subscription is None:
        subscription = Subscription.objects.create(
            account=account, invoice=invoice, offer=offer, plan=plan, status='active',
            renewal_enabled=False, first_charge_id=charge, current_period_end=end, sandbox=False,
            provider=provider)
    period = SubscriptionPeriod.objects.create(subscription=subscription, payment=paid, account=account,
                                               plan=plan, starts_at=start, ends_at=end, sandbox=False)
    current = active_period(account) or period
    # An earlier period of ours may still run past this one's start; a lapsed
    # Telegram subscription's dates mean nothing to it.
    subscription.current_period_end = max(subscription.current_period_end, end) if own else end
    if not own:
        subscription.first_charge_id = charge
    subscription.invoice, subscription.offer = invoice, offer
    subscription.plan, subscription.status = current.plan, 'active'
    subscription.renewal_enabled, subscription.sandbox = False, False
    # Paying by card makes it a card subscription; a reward only names it when
    # nothing was ever paid by card, so "manual" keeps meaning someone paid.
    if provider == 'manual' or subscription.provider != 'manual':
        subscription.provider = provider
    subscription.scheduled_plan, subscription.scheduled_at = '', None
    subscription.save()
    refresh_account_entitlement(account)
    return paid, period
