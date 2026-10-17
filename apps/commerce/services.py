import secrets
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from apps.core.errors import DomainError
from apps.core.models import Account,Job
from .models import Subscription,SubscriptionPeriod,Refund,CommerceAction,ReferralCode,Referral,ManualPayment

# One paid period: 30 days. A card transfer (apps/commerce/manual.py) is the
# only way to pay; Telegram Stars was removed, and its rows stay as history.
PERIOD=2592000


def sandbox_enabled(account):
    # The local bot simulator and test accounts, not a payment sandbox.
    return bool(settings.DEBUG and getattr(settings,'COMMERCE_SANDBOX_ENABLED',False) and account.is_test)


def require_sandbox(account):
    if not sandbox_enabled(account): raise DomainError('sandbox_disabled',403)


def active_period(account,at=None):
    now=at or timezone.now()
    query=SubscriptionPeriod.objects.filter(account=account,starts_at__lte=now,ends_at__gt=now,revoked_at__isnull=True)
    if not sandbox_enabled(account): query=query.filter(sandbox=False)
    return query.order_by('-ends_at').first()


def staff_plan(account,at=None):
    """A plan assigned by staff, while it is still in force."""
    if not account.staff_plan:return ''
    expiry=account.staff_plan_expires_at
    return '' if expiry and expiry<=(at or timezone.now()) else account.staff_plan


def effective_plan(account,at=None):
    # A staff assignment wins outright: it is how support comps a plan and how
    # abuse is contained, and both must work regardless of what was paid. The
    # paid period is left untouched underneath and returns when it lapses.
    assigned=staff_plan(account,at)
    if assigned:return assigned
    period=active_period(account,at)
    return period.plan if period else 'free'


def refresh_account_entitlement(account):
    plan=effective_plan(account)
    if account.plan!=plan:
        Account.objects.filter(pk=account.pk).update(plan=plan);account.plan=plan
    return plan


@transaction.atomic
def confirm_refund(refund):
    refund=Refund.objects.select_for_update().select_related('payment__account').get(pk=refund.pk)
    if refund.status=='confirmed': return refund
    payment=refund.payment;now=timezone.now()
    # Revoking the period takes the plan back; there is no balance to claw back.
    SubscriptionPeriod.objects.filter(payment=payment,revoked_at__isnull=True).update(revoked_at=now)
    refund.status='confirmed';refund.confirmed_at=now;refund.error_code='';refund.save(update_fields=['status','confirmed_at','error_code'])
    ManualPayment.objects.filter(payment=payment).update(status='refunded')
    refresh_account_entitlement(payment.account)
    subscription=Subscription.objects.filter(account=payment.account).first()
    if subscription and not subscription.periods.filter(revoked_at__isnull=True,ends_at__gt=now).exists():
        subscription.status='refunded';subscription.renewal_enabled=False;subscription.save(update_fields=['status','renewal_enabled','updated_at'])
    CommerceAction.objects.create(account=payment.account,actor=refund.requested_by,action='refund.confirmed',target=str(refund.id),reason=refund.reason,metadata={'amount_xtr':refund.amount_xtr,'sandbox':payment.sandbox})
    return refund


def refund_payment(payment,reason,actor=None,sandbox_account=None):
    if not isinstance(reason,str) or not 3<=len(reason.strip())<=500: raise DomainError('audit_reason_required')
    if payment.sandbox:
        require_sandbox(payment.account)
        if sandbox_account and sandbox_account.id!=payment.account_id: raise DomainError('not_found',404)
    elif not actor or not actor.is_staff or not (actor.is_superuser or actor.groups.filter(name__in=('Finance','Administrator')).exists()): raise DomainError('permission_denied',403)
    refund,created=Refund.objects.get_or_create(payment=payment,defaults={'amount_xtr':payment.amount_xtr,'reason':reason.strip(),'requested_by':actor})
    if refund.status=='confirmed': return refund
    # A card transfer is returned by the owner from their own bank app; this
    # records that it was, and takes the plan back. No provider is asked.
    return confirm_refund(refund)


def expire_subscriptions():
    count=0
    for subscription in Subscription.objects.filter(current_period_end__lte=timezone.now()).exclude(status__in=('expired','refunded')):
        subscription.status='expired';subscription.renewal_enabled=False;subscription.save(update_fields=['status','renewal_enabled','updated_at'])
        refresh_account_entitlement(subscription.account);count+=1
    return count


def referral_code(account):
    value,_=ReferralCode.objects.get_or_create(account=account,defaults={'code':secrets.token_urlsafe(8)})
    return value


@transaction.atomic
def claim_referral(account,code):
    Account.objects.select_for_update().get(pk=account.pk)
    value=ReferralCode.objects.select_related('account').filter(code=code).first()
    if not value or value.account_id==account.id: raise DomainError('invalid_referral')
    if value.account.is_test!=account.is_test: raise DomainError('invalid_referral')
    if timezone.now()-account.created_at>timedelta(days=7): raise DomainError('referral_window_closed',409)
    existing=Referral.objects.filter(invitee=account).first()
    if existing:
        if existing.inviter_id!=value.account_id: raise DomainError('referral_already_claimed',409)
        return existing
    return Referral.objects.create(inviter=value.account,invitee=account)


@transaction.atomic
def qualify_referrals(account=None):
    pending=Referral.objects.filter(status='pending').select_related('inviter','invitee')
    if account: pending=pending.filter(inviter=account)
    count=0
    for referral in pending.select_for_update():
        if not Job.objects.filter(account=referral.invitee,status='succeeded').exists(): continue
        Account.objects.select_for_update().get(pk=referral.inviter_id)
        start=timezone.now().replace(day=1,hour=0,minute=0,second=0,microsecond=0)
        if Referral.objects.filter(inviter=referral.inviter,status='qualified',qualified_at__gte=start).count()>=5: continue
        # Counted, not rewarded: there are no credits to give, and the reward
        # that replaces them is still to come.
        referral.status='qualified';referral.qualified_at=timezone.now();referral.save(update_fields=['status','qualified_at']);count+=1
    return count
