import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime,timedelta,timezone as dt_timezone
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q,Sum
from django.utils import timezone
from apps.core.errors import DomainError
from apps.core.models import Account,UsageGrant,Job,SupportTicket
from apps.core.policy import SEED,METERS,cycle
from .models import OfferVersion,Invoice,Payment,Subscription,SubscriptionPeriod,PaymentGrant,Refund,BalanceAdjustment,CommerceAction,ReconciliationRun,ReconciliationIssue,ReferralCode,Referral,SupportMessage,BotDelivery
from .providers import provider_for

PERIOD=2592000
SANDBOX_OFFERS={
 'plus':{'kind':'subscription','plan':'plus','name':'Plus · local sandbox','price_xtr':50,'quantities':{m:SEED['plans']['plus'][m] for m in METERS},'period_seconds':PERIOD},
 'premium':{'kind':'subscription','plan':'premium','name':'Premium · local sandbox','price_xtr':150,'quantities':{m:SEED['plans']['premium'][m] for m in METERS},'period_seconds':PERIOD},
 'tasks100':{'kind':'task_pack','plan':'','name':'100 tasks + 1,000 page units · local sandbox','price_xtr':25,'quantities':{'file_tasks':100,'file_page_units':1000,'ai_credits':0},'period_seconds':None},
 'ai100':{'kind':'ai_pack','plan':'','name':'100 AI credits · local sandbox','price_xtr':30,'quantities':{'file_tasks':0,'file_page_units':0,'ai_credits':100},'period_seconds':None},
}


def sandbox_enabled(account):
    return bool(settings.DEBUG and getattr(settings,'COMMERCE_SANDBOX_ENABLED',False) and account.is_test)


def require_sandbox(account):
    if not sandbox_enabled(account): raise DomainError('sandbox_disabled',403)


def offer_data(offer):
    return {'id':offer.offer_id,'version':offer.version,'kind':offer.kind,'plan':offer.plan or None,'name':offer.name,'price_xtr':offer.price_xtr,'currency':'XTR','quantities':offer.quantities,'period_seconds':offer.period_seconds,'sandbox':offer.sandbox,'checkout_enabled':offer.enabled and offer.price_xtr is not None}


def available_offers(account):
    sandbox=sandbox_enabled(account)
    if account.is_test and not sandbox:return []
    if sandbox: definitions=SANDBOX_OFFERS;version='sandbox-v1'
    else:
        if not getattr(settings,'COMMERCE_LIVE_ENABLED',False): return []
        definitions=getattr(settings,'COMMERCE_LIVE_OFFERS',{})
        if not isinstance(definitions,dict): return []
        version=str(getattr(settings,'COMMERCE_OFFER_VERSION','live-v1'))
    offers=[]
    for code,value in definitions.items():
        if not isinstance(code,str) or not isinstance(value,dict) or not isinstance(value.get('name'),str):continue
        amount=value.get('price_xtr')
        if type(amount) is not int or not 1<=amount<=10000: continue
        if value.get('kind') not in ('subscription','task_pack','ai_pack'): continue
        if value['kind']=='subscription' and (value.get('plan') not in ('plus','premium') or value.get('period_seconds')!=PERIOD): continue
        quantities=value.get('quantities',{})
        if not isinstance(quantities,dict):continue
        if set(quantities)-set(METERS) or any(type(n)is not int or n<0 for n in quantities.values()): continue
        if value['kind']=='task_pack' and not (quantities.get('file_tasks',0)>0 and quantities.get('file_page_units',0)>0): continue
        defaults={'offer_id':code,'version':version,'kind':value['kind'],'plan':value.get('plan',''),'name':value['name'],'price_xtr':amount,'period_seconds':value.get('period_seconds'),'quantities':{m:quantities.get(m,0) for m in METERS},'sandbox':sandbox,'enabled':True}
        offer,created=OfferVersion.objects.get_or_create(id=f'{"sandbox" if sandbox else "live"}:{version}:{code}',defaults=defaults)
        # A published version cannot silently change price or quantity on deployment.
        if any(getattr(offer,key)!=defaults[key] for key in ('price_xtr','kind','plan','quantities','period_seconds')): raise DomainError('offer_version_conflict',409)
        if offer.enabled: offers.append(offer)
    return offers


def active_period(account,at=None):
    now=at or timezone.now()
    query=SubscriptionPeriod.objects.filter(account=account,starts_at__lte=now,ends_at__gt=now,revoked_at__isnull=True)
    if not sandbox_enabled(account): query=query.filter(sandbox=False)
    return query.order_by('-ends_at').first()


def effective_plan(account,at=None):
    period=active_period(account,at)
    return period.plan if period else 'free'


def refresh_account_entitlement(account):
    plan=effective_plan(account)
    if account.plan!=plan:
        Account.objects.filter(pk=account.pk).update(plan=plan);account.plan=plan
    return plan


def ensure_account_grants(account):
    period=active_period(account)
    refresh_account_entitlement(account)
    if period: return period.ends_at
    start,end=cycle(account)
    for meter in METERS:
        UsageGrant.objects.get_or_create(source_id=f'included:{account.id}:{start.isoformat()}:{meter}',defaults={'account':account,'meter':meter,'quantity':SEED['plans']['free'][meter],'valid_from':start,'expires_at':end})
    return end


def eligible_grants(account,queryset):
    if not sandbox_enabled(account):queryset=queryset.exclude(payment_source__payment__sandbox=True)
    period=active_period(account)
    # Included grants from the inactive tier cannot add a second allowance.
    if period:
        eligible=PaymentGrant.objects.filter(payment=period.payment,revoked_at__isnull=True).values('grant_id')
        return queryset.filter(~Q(source='included')|Q(id__in=eligible)).exclude(payment_source__revoked_at__isnull=False)
    return queryset.exclude(source_id__startswith='payment:').exclude(payment_source__revoked_at__isnull=False)|queryset.filter(source='purchased',payment_source__revoked_at__isnull=True)


def payload_for(invoice):
    content=f'{invoice.id.hex}:{invoice.account_id}:{invoice.offer_id}'
    signature=hmac.new(settings.SECRET_KEY.encode(),content.encode(),hashlib.sha256).hexdigest()[:32]
    return f'pm:{invoice.id.hex}:{signature}'


def invoice_for_payload(payload):
    try:
        prefix,identifier,_=payload.split(':')
        if prefix!='pm': raise ValueError()
        invoice=Invoice.objects.select_related('account','offer').get(pk=uuid.UUID(identifier))
    except (ValueError,AttributeError,Invoice.DoesNotExist): raise DomainError('invalid_invoice',400) from None
    if not hmac.compare_digest(payload,payload_for(invoice)): raise DomainError('invalid_invoice',400)
    return invoice


@transaction.atomic
def create_invoice(account,offer_id,idempotency_key):
    if account.telegram_user_id is None: raise DomainError('telegram_link_required',409)
    if not available_offers(account): raise DomainError('checkout_disabled',409)
    if not isinstance(idempotency_key,str) or not 8<=len(idempotency_key)<=128: raise DomainError('idempotency_key_required')
    account=Account.objects.select_for_update().get(pk=account.pk)
    request_hash=hashlib.sha256(json.dumps({'offer_id':offer_id},sort_keys=True).encode()).hexdigest()
    existing=Invoice.objects.filter(account=account,idempotency_key=idempotency_key).first()
    if existing:
        if existing.request_hash!=request_hash: raise DomainError('idempotency_conflict',409)
        return existing,False
    offers={offer.offer_id:offer for offer in available_offers(account)}
    offer=offers.get(offer_id)
    if not offer: raise DomainError('checkout_disabled',409)
    if offer.kind=='subscription':
        if active_period(account): raise DomainError('subscription_already_active',409)
        if Invoice.objects.filter(account=account,offer__kind='subscription',expires_at__gt=timezone.now(),status__in=('created','presented','pending')).exists(): raise DomainError('subscription_invoice_pending',409)
    invoice=Invoice(account=account,offer=offer,snapshot=offer_data(offer),amount_xtr=offer.price_xtr,idempotency_key=idempotency_key,request_hash=request_hash,sandbox=offer.sandbox,expires_at=timezone.now()+timedelta(minutes=10))
    invoice.payload_hash=hashlib.sha256(payload_for(invoice).encode()).hexdigest();invoice.save()
    CommerceAction.objects.create(account=account,action='invoice.created',target=str(invoice.id),metadata={'sandbox':invoice.sandbox,'amount_xtr':invoice.amount_xtr})
    return invoice,True


def present_invoice(invoice):
    if invoice.account.telegram_user_id is None: raise DomainError('telegram_link_required',409)
    if invoice.invoice_url or invoice.sandbox: return invoice
    if invoice.expires_at<=timezone.now(): raise DomainError('invoice_expired',409)
    url=provider_for(False).invoice_link(invoice,payload_for(invoice))
    Invoice.objects.filter(pk=invoice.pk,status='created').update(invoice_url=url,status='presented')
    invoice.refresh_from_db();return invoice


@transaction.atomic
def validate_precheckout(telegram_user_id,payload,currency,amount,sandbox=False):
    if type(telegram_user_id) is not int or telegram_user_id<=0: raise DomainError('invalid_invoice',403)
    invoice=invoice_for_payload(payload)
    Account.objects.select_for_update().get(pk=invoice.account_id)
    invoice=Invoice.objects.select_for_update().select_related('account','offer').get(pk=invoice.pk)
    if invoice.account.telegram_user_id!=telegram_user_id or invoice.sandbox!=sandbox: raise DomainError('invalid_invoice',403)
    if currency!='XTR' or type(amount)is not int or amount!=invoice.amount_xtr: raise DomainError('payment_amount_mismatch')
    if invoice.status not in ('created','presented','pending') or invoice.expires_at<=timezone.now(): raise DomainError('invoice_expired',409)
    if invoice.offer.kind=='subscription' and active_period(invoice.account): raise DomainError('subscription_already_active',409)
    invoice.status='pending';invoice.save(update_fields=['status'])
    return invoice


def _issue(charge,kind,amount,invoice=None,occurred=None):
    fingerprint=hashlib.sha256(f'{charge}:{kind}'.encode()).hexdigest()
    return ReconciliationIssue.objects.get_or_create(fingerprint=fingerprint,defaults={'charge_id':charge,'kind':kind,'amount_xtr':max(0,amount),'invoice':invoice,'occurred_at':occurred or timezone.now()})[0]


@transaction.atomic
def record_payment(telegram_user_id,payload,currency,amount,charge_id,*,provider_charge_id='',expiration_date=None,is_recurring=False,is_first_recurring=False,occurred_at=None,sandbox=False):
    if type(telegram_user_id) is not int or telegram_user_id<=0: raise DomainError('invalid_invoice',403)
    invoice=invoice_for_payload(payload)
    account=Account.objects.select_for_update().get(pk=invoice.account_id)
    invoice=Invoice.objects.select_for_update().select_related('offer').get(pk=invoice.pk)
    if account.telegram_user_id!=telegram_user_id or invoice.sandbox!=sandbox: raise DomainError('invalid_invoice',403)
    if sandbox: require_sandbox(account)
    if currency!='XTR' or type(amount)is not int or amount!=invoice.amount_xtr: raise DomainError('payment_amount_mismatch')
    if not isinstance(charge_id,str) or not 1<=len(charge_id)<=200: raise DomainError('invalid_charge')
    existing=Payment.objects.filter(provider_charge_id=charge_id).first()
    if existing:
        if existing.invoice_id!=invoice.id or existing.account_id!=account.id or existing.amount_xtr!=amount: raise DomainError('charge_conflict',409)
        return existing,False
    kind=invoice.offer.kind
    renewal=bool(is_recurring and not is_first_recurring)
    occurred=occurred_at or timezone.now()
    if kind=='subscription':
        if not is_recurring or expiration_date is None: raise DomainError('subscription_period_required')
        end=datetime.fromtimestamp(int(expiration_date),tz=dt_timezone.utc)
        start=end-timedelta(seconds=PERIOD)
        if end<=occurred or start>occurred+timedelta(days=31): raise DomainError('invalid_subscription_period')
        subscription=Subscription.objects.select_for_update().filter(account=account).first()
        if renewal:
            if not subscription or subscription.invoice_id!=invoice.id or subscription.offer_id!=invoice.offer_id: raise DomainError('renewal_contract_mismatch',409)
            if end<=subscription.current_period_end: raise DomainError('duplicate_subscription_period',409)
        elif active_period(account): raise DomainError('subscription_already_active',409)
    elif renewal or is_recurring: raise DomainError('invalid_recurring_purchase')
    elif Payment.objects.filter(invoice=invoice).exists(): raise DomainError('invoice_already_paid',409)
    payment=Payment.objects.create(account=account,invoice=invoice,provider_charge_id=charge_id,provider_payment_charge_id=provider_charge_id,amount_xtr=amount,kind=kind,plan=invoice.offer.plan,is_renewal=renewal,sandbox=sandbox,occurred_at=occurred)
    if kind=='subscription':
        if not renewal:
            subscription,_=Subscription.objects.update_or_create(account=account,defaults={'invoice':invoice,'offer':invoice.offer,'plan':invoice.offer.plan,'status':'active','renewal_enabled':True,'first_charge_id':charge_id,'current_period_end':end,'scheduled_plan':'','scheduled_at':None,'sandbox':sandbox})
        else:
            if not subscription.renewal_enabled or subscription.scheduled_plan: _issue(charge_id,'renewal_after_cancel',amount,invoice,occurred)
            subscription.current_period_end=end
            subscription.status='active' if subscription.renewal_enabled else 'cancel_at_period_end'
            subscription.save(update_fields=['current_period_end','status','updated_at'])
        period=SubscriptionPeriod.objects.create(subscription=subscription,payment=payment,account=account,plan=invoice.offer.plan,starts_at=start,ends_at=end,sandbox=sandbox)
        valid_from,expires_at,source=start,end,'included'
    else: valid_from,expires_at,source=occurred,None,'purchased'
    for meter,quantity in invoice.snapshot['quantities'].items():
        if not quantity: continue
        grant=UsageGrant.objects.create(account=account,meter=meter,source=source,source_id=f'payment:{charge_id}:{meter}',quantity=quantity,valid_from=valid_from,expires_at=expires_at)
        PaymentGrant.objects.create(payment=payment,grant=grant)
    invoice.status='paid';invoice.paid_at=invoice.paid_at or occurred;invoice.save(update_fields=['status','paid_at'])
    refresh_account_entitlement(account)
    CommerceAction.objects.create(account=account,action='payment.confirmed',target=str(payment.id),metadata={'amount_xtr':amount,'sandbox':sandbox,'renewal':renewal})
    return payment,True


def sandbox_pay(account,invoice_id):
    require_sandbox(account)
    try: invoice=Invoice.objects.select_related('offer').get(pk=invoice_id,account=account,sandbox=True)
    except Invoice.DoesNotExist: raise DomainError('not_found',404)
    existing=Payment.objects.filter(invoice=invoice,is_renewal=False).first()
    if existing: return existing,False
    validate_precheckout(account.telegram_user_id,payload_for(invoice),'XTR',invoice.amount_xtr,True)
    subscription=invoice.offer.kind=='subscription'
    return record_payment(account.telegram_user_id,payload_for(invoice),'XTR',invoice.amount_xtr,f'sandbox:{invoice.id}',expiration_date=int((timezone.now()+timedelta(seconds=PERIOD)).timestamp()) if subscription else None,is_recurring=subscription,is_first_recurring=subscription,sandbox=True)


def sandbox_renew(account,idempotency_key):
    require_sandbox(account)
    if not isinstance(idempotency_key,str) or not 8<=len(idempotency_key)<=128: raise DomainError('idempotency_key_required')
    subscription=Subscription.objects.select_related('invoice').filter(account=account,sandbox=True).first()
    if not subscription or not subscription.renewal_enabled: raise DomainError('renewal_disabled',409)
    charge='sandbox:renew:'+hashlib.sha256(f'{subscription.id}:{idempotency_key}'.encode()).hexdigest()
    existing=Payment.objects.filter(provider_charge_id=charge).first()
    if existing: return existing,False
    return record_payment(account.telegram_user_id,payload_for(subscription.invoice),'XTR',subscription.invoice.amount_xtr,charge,expiration_date=int((subscription.current_period_end+timedelta(seconds=PERIOD)).timestamp()),is_recurring=True,sandbox=True)


def set_renewal(account,enabled):
    subscription=Subscription.objects.select_related('account').filter(account=account).first()
    if not subscription or not active_period(account): raise DomainError('subscription_not_active',409)
    if subscription.sandbox: require_sandbox(account)
    if subscription.renewal_enabled==enabled and (not enabled or not subscription.scheduled_plan): return subscription
    if not provider_for(subscription.sandbox).set_renewal(subscription,enabled): raise DomainError('payment_provider_unavailable',503)
    with transaction.atomic():
        subscription=Subscription.objects.select_for_update().get(pk=subscription.pk)
        subscription.renewal_enabled=enabled;subscription.status='active' if enabled else 'cancel_at_period_end'
        if enabled: subscription.scheduled_plan='';subscription.scheduled_at=None
        subscription.save(update_fields=['renewal_enabled','status','scheduled_plan','scheduled_at','updated_at'])
        CommerceAction.objects.create(account=account,action='subscription.resume' if enabled else 'subscription.cancel',target=str(subscription.id),metadata={'access_until':subscription.current_period_end.isoformat()})
    return subscription


def schedule_plan_change(account,plan):
    if plan not in ('free','plus','premium'): raise DomainError('invalid_plan')
    subscription=Subscription.objects.filter(account=account).first()
    if not subscription or subscription.plan==plan: raise DomainError('invalid_plan_change',409)
    subscription=set_renewal(account,False)
    subscription.scheduled_plan=plan;subscription.scheduled_at=subscription.current_period_end
    subscription.save(update_fields=['scheduled_plan','scheduled_at','updated_at'])
    CommerceAction.objects.create(account=account,action='subscription.plan_scheduled',target=str(subscription.id),metadata={'plan':plan,'effective_at':subscription.current_period_end.isoformat(),'requires_new_checkout':plan!='free'})
    return subscription


@transaction.atomic
def confirm_refund(refund):
    refund=Refund.objects.select_for_update().select_related('payment__account').get(pk=refund.pk)
    if refund.status=='confirmed': return refund
    payment=refund.payment;now=timezone.now()
    for link in payment.grant_links.select_related('grant').all():
        grant=UsageGrant.objects.select_for_update().get(pk=link.grant_id)
        if grant.consumed or grant.reserved:
            BalanceAdjustment.objects.get_or_create(account=payment.account,refund=refund,meter=grant.meter,defaults={'consumed_units':grant.consumed,'reserved_units':grant.reserved})
        # Keep ledger history and reservation math intact; revoke future spendability.
        grant.expires_at=now;grant.save(update_fields=['expires_at'])
        link.revoked_at=now;link.save(update_fields=['revoked_at'])
    SubscriptionPeriod.objects.filter(payment=payment,revoked_at__isnull=True).update(revoked_at=now)
    refund.status='confirmed';refund.confirmed_at=now;refund.error_code='';refund.save(update_fields=['status','confirmed_at','error_code'])
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
    try:
        if not provider_for(payment.sandbox).refund(payment): raise DomainError('payment_provider_unavailable',503)
    except DomainError:
        refund.error_code='provider_result_unknown';refund.save(update_fields=['error_code'])
        raise
    return confirm_refund(refund)


def cancel_invoice(account,invoice_id):
    invoice=Invoice.objects.filter(pk=invoice_id,account=account).first()
    if not invoice: raise DomainError('not_found',404)
    if invoice.status=='paid': raise DomainError('invoice_already_paid',409)
    invoice.status='canceled';invoice.save(update_fields=['status']);return invoice


def expire_subscriptions():
    count=0
    for subscription in Subscription.objects.filter(current_period_end__lte=timezone.now()).exclude(status__in=('expired','refunded')):
        subscription.status='expired';subscription.renewal_enabled=False;subscription.save(update_fields=['status','renewal_enabled','updated_at'])
        refresh_account_entitlement(subscription.account);count+=1
    return count


def reconcile_transactions(provider=None,max_pages=10):
    provider=provider or provider_for(False)
    run=ReconciliationRun.objects.create(sandbox=provider.sandbox)
    offset=0
    for _ in range(max_pages):
        rows=provider.transactions(offset,100)
        for row in rows:
            run.checked+=1
            charge=str(row.get('id',''));amount=abs(int(row.get('amount',0)))
            payment=Payment.objects.filter(provider_charge_id=charge,sandbox=provider.sandbox).first()
            if payment:
                if amount!=payment.amount_xtr:
                    _issue(charge,'reconciliation_amount_mismatch',amount,payment.invoice);run.issues+=1
                elif row.get('receiver'):
                    receiver=row['receiver'];uid=(receiver.get('user') or {}).get('id')
                    if uid==payment.account.telegram_user_id:
                        refund,_=Refund.objects.get_or_create(payment=payment,defaults={'amount_xtr':payment.amount_xtr,'reason':'Provider reconciliation confirmed refund'})
                        confirm_refund(refund);run.matched+=1
                    else: _issue(charge,'refund_owner_mismatch',amount,payment.invoice);run.issues+=1
                elif (row.get('source') or {}).get('user',{}).get('id')==payment.account.telegram_user_id:run.matched+=1
                else:_issue(charge,'payment_owner_mismatch',amount,payment.invoice);run.issues+=1
            else:
                source=row.get('source') or {};payload=source.get('invoice_payload')
                try: invoice=invoice_for_payload(payload) if payload else None
                except DomainError: invoice=None
                _issue(charge,'missing_successful_payment_receipt' if invoice else 'orphan_provider_transaction',amount,invoice,row.get('date'));run.issues+=1
        offset+=len(rows)
        if len(rows)<100: break
    run.next_offset=offset;run.completed_at=timezone.now();run.save(update_fields=['checked','matched','issues','next_offset','completed_at']);return run


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
        grant,_=UsageGrant.objects.get_or_create(source_id=f'referral:{referral.id}',defaults={'account':referral.inviter,'meter':'ai_credits','source':'referral','quantity':10,'valid_from':timezone.now(),'expires_at':timezone.now()+timedelta(days=30)})
        referral.grant=grant;referral.status='qualified';referral.qualified_at=timezone.now();referral.save(update_fields=['grant','status','qualified_at']);count+=1
    return count


def add_support_message(account,ticket_id,body,staff=None):
    ticket=SupportTicket.objects.filter(pk=ticket_id).first()
    if not ticket or (not staff and ticket.account_id!=account.id): raise DomainError('not_found',404)
    if staff and not(staff.is_staff and (staff.is_superuser or staff.groups.filter(name__in=('Support','Administrator')).exists())): raise DomainError('permission_denied',403)
    if not isinstance(body,str) or not 1<=len(body.strip())<=4000: raise DomainError('invalid_support_ticket')
    message=SupportMessage.objects.create(ticket=ticket,body=body.strip(),sender_account=None if staff else account,sender_staff=staff)
    ticket.status='waiting_customer' if staff else 'open';ticket.save(update_fields=['status','updated_at']);return message
