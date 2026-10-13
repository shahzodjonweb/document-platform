import io
from datetime import timedelta
from unittest.mock import Mock
import pytest
from django.test import Client
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from pypdf import PdfWriter
from apps.core.identity import resolve_account
from apps.core.errors import DomainError
from apps.core.models import UsageGrant,Account
from apps.core.policy import usage_snapshot,plan_limits
from apps.core.services import upload_file,create_quote,submit_job,execute_job
from apps.commerce import services
from apps.commerce.models import OfferVersion,Invoice,Payment,Subscription,SubscriptionPeriod,PaymentGrant,Refund,BalanceAdjustment,CommerceAction,ReconciliationIssue,Referral

pytestmark=pytest.mark.django_db

def account(number=801): return resolve_account({'id':number,'first_name':'Commerce test'},is_test=True)
def client_for(a,csrf=False):
    c=Client(enforce_csrf_checks=csrf);session=c.session;session['customer_account_id']=str(a.id);session.save();return c

def purchase(a,offer='plus',key='test-invoice-key'):
    invoice,_=services.create_invoice(a,offer,key)
    payment,_=services.sandbox_pay(a,invoice.id)
    a.refresh_from_db();return invoice,payment

def weekly(a):
    usage=usage_snapshot(a);return usage['plan'],usage['ai_documents']['limit'],usage['file_jobs']['limit'],usage['edits_per_file']

def no_credits_written():
    return not UsageGrant.objects.exists() and not PaymentGrant.objects.exists() and not BalanceAdjustment.objects.exists()

def pdf_job(a,key='financial-job-key'):
    writer=PdfWriter();writer.add_blank_page(width=210,height=400);stream=io.BytesIO();writer.write(stream)
    asset=upload_file(a,SimpleUploadedFile('financial.pdf',stream.getvalue()))
    q=create_quote(a,'pdf.rotate',[str(asset.id)],{})
    job,_=submit_job(a,q.id,key);return execute_job(job.id)

def test_invoice_quote_prices_server_owned_and_confirmed_once():
    a=account();c=client_for(a)
    response=c.post('/api/v1/billing/invoices',{'offer_id':'plus','amount_xtr':1,'plan':'premium'},content_type='application/json',HTTP_IDEMPOTENCY_KEY='server-price-key')
    assert response.status_code==201,response.content
    invoice=response.json();assert invoice['amount_xtr']==50 and invoice['plan']=='plus'
    assert a.plan=='free' and Payment.objects.count()==0
    first=c.post(f'/api/v1/billing/invoices/{invoice["id"]}/sandbox-pay',{},content_type='application/json')
    assert first.status_code==200,first.content
    assert first.json()['plan']=='plus'
    second=c.post(f'/api/v1/billing/invoices/{invoice["id"]}/sandbox-pay',{},content_type='application/json')
    assert second.status_code==200 and second.json()['payment']['id']==first.json()['payment']['id']
    assert Payment.objects.count()==SubscriptionPeriod.objects.count()==1
    assert weekly(a)==('plus',20,None,10),'the plan is its weekly limits'
    assert no_credits_written()

def test_production_prices_null_and_sandbox_cannot_activate_real_account(settings):
    real=resolve_account({'id':802,'first_name':'Real user'},is_test=False)
    assert services.available_offers(real)==[]
    with pytest.raises(DomainError,match='checkout_disabled'): services.create_invoice(real,'plus','valid-production-request')
    a=account();invoice,_=services.create_invoice(a,'plus','sandbox-created-key')
    settings.DEBUG=False
    with pytest.raises(DomainError,match='sandbox_disabled'): services.sandbox_pay(a,invoice.id)
    assert Payment.objects.count()==0 and Subscription.objects.count()==0

def test_owner_amount_currency_payload_and_precheckout_validation():
    a=account();b=account(803);invoice,_=services.create_invoice(a,'plus','validated-invoice-key');payload=services.payload_for(invoice)
    for uid,currency,amount,submitted in ((b.telegram_user_id,'XTR',50,payload),(a.telegram_user_id,'USD',50,payload),(a.telegram_user_id,'XTR',1,payload),(a.telegram_user_id,'XTR',50,payload[:-1]+'x')):
        with pytest.raises(DomainError): services.validate_precheckout(uid,submitted,currency,amount,True)
    assert services.validate_precheckout(a.telegram_user_id,payload,'XTR',50,True).status=='pending'
    assert Payment.objects.count()==0
    assert client_for(b).get(f'/api/v1/billing/invoices/{invoice.id}').status_code==404
    assert client_for(b).post(f'/api/v1/billing/invoices/{invoice.id}/sandbox-pay',{},content_type='application/json').status_code==404

def test_invoice_idempotency_conflict_and_single_active_contract():
    a=account();invoice,_=services.create_invoice(a,'plus','same-invoice-key')
    same,created=services.create_invoice(a,'plus','same-invoice-key');assert not created and same.id==invoice.id
    with pytest.raises(DomainError,match='idempotency_conflict'): services.create_invoice(a,'premium','same-invoice-key')
    with pytest.raises(DomainError,match='subscription_invoice_pending'): services.create_invoice(a,'premium','second-invoice-key')
    services.sandbox_pay(a,invoice.id)
    with pytest.raises(DomainError,match='subscription_already_active'): services.create_invoice(a,'premium','second-invoice-key')

def test_expired_invoice_and_wrong_successful_charge_are_rejected():
    a=account();invoice,_=services.create_invoice(a,'plus','expiring-invoice-key')
    Invoice.objects.filter(pk=invoice.id).update(expires_at=timezone.now()-timedelta(seconds=1))
    with pytest.raises(DomainError,match='invoice_expired'): services.sandbox_pay(a,invoice.id)
    with pytest.raises(DomainError,match='payment_amount_mismatch'): services.record_payment(a.telegram_user_id,services.payload_for(invoice),'XTR',1,'bad-charge',sandbox=True)
    assert Payment.objects.count()==0

def test_weekly_limits_follow_the_paid_period_and_the_shared_account():
    a=account();assert weekly(a)==('free',5,15,3)
    invoice,payment=purchase(a)
    assert weekly(a)==('plus',20,None,10) and plan_limits(a)['max_file_mib']==100
    SubscriptionPeriod.objects.filter(payment=payment).update(ends_at=timezone.now()-timedelta(seconds=1))
    assert weekly(a)==('free',5,15,3),'a lapsed period leaves nothing behind'
    assert resolve_account({'id':a.telegram_user_id,'first_name':'Same from bot'},'bot').id==a.id

def test_only_plans_are_sold():
    a=account()
    offers={offer.offer_id:services.offer_data(offer) for offer in services.available_offers(a)}
    assert set(offers)=={'plus','premium'} and all(offer['kind']=='subscription' for offer in offers.values())
    assert not any('quantities' in offer for offer in offers.values())
    assert {offer['version'] for offer in offers.values()}=={'sandbox-v2'}
    for pack in ('tasks100','ai100'):
        with pytest.raises(DomainError,match='checkout_disabled'): services.create_invoice(a,pack,'pack-'+pack+'-key')

def test_an_old_v1_offer_does_not_block_the_plans():
    """v1 offers carried credits; a stored version may never change, so the plans moved to v2."""
    OfferVersion.objects.create(id='sandbox:sandbox-v1:plus',offer_id='plus',version='sandbox-v1',kind='subscription',plan='plus',name='Plus',price_xtr=50,period_seconds=services.PERIOD,quantities={'ai_credits':1050},sandbox=True,enabled=True)
    assert [offer.id for offer in services.available_offers(account())]==['sandbox:sandbox-v2:plus','sandbox:sandbox-v2:premium']

def test_a_pack_invoice_from_before_plans_cannot_be_paid():
    """It would buy nothing now, so it is refused at pre-checkout, before money moves."""
    a=account()
    pack=OfferVersion.objects.create(id='sandbox:sandbox-v1:tasks100',offer_id='tasks100',version='sandbox-v1',kind='task_pack',plan='',name='Tasks',price_xtr=25,quantities={'file_tasks':100},sandbox=True,enabled=True)
    invoice=Invoice(account=a,offer=pack,snapshot={},amount_xtr=25,idempotency_key='old-pack-invoice',request_hash='x',sandbox=True,expires_at=timezone.now()+timedelta(minutes=5))
    invoice.payload_hash='x';invoice.save()
    with pytest.raises(DomainError,match='checkout_disabled'): services.sandbox_pay(a,invoice.id)
    assert not Payment.objects.exists() and weekly(a)[0]=='free'

def test_cancel_resume_boundary_change_preserves_access():
    a=account();invoice,payment=purchase(a)
    subscription=services.set_renewal(a,False)
    assert not subscription.renewal_enabled and subscription.status=='cancel_at_period_end'
    assert services.effective_plan(a)=='plus'
    subscription=services.set_renewal(a,True);assert subscription.renewal_enabled
    scheduled=services.schedule_plan_change(a,'premium')
    assert scheduled.scheduled_plan=='premium' and not scheduled.renewal_enabled
    assert scheduled.scheduled_at==scheduled.current_period_end
    assert services.effective_plan(a)=='plus' and Payment.objects.count()==1
    assert services.set_renewal(a,True).scheduled_plan==''

def test_renewal_is_idempotent_and_a_renewal_after_cancel_is_flagged():
    a=account();invoice,payment=purchase(a)
    renewal,_=services.sandbox_renew(a,'renewal-idempotency-key')
    same,created=services.sandbox_renew(a,'renewal-idempotency-key')
    assert not created and same.id==renewal.id
    assert Payment.objects.count()==2 and SubscriptionPeriod.objects.count()==2
    assert weekly(a)==('plus',20,None,10),'a second period is the same plan, not twice the limits'
    assert no_credits_written()
    sub=services.set_renewal(a,False)
    later=int((sub.current_period_end+timedelta(seconds=services.PERIOD)).timestamp())
    # Authoritative unexpected renewal is recorded and flagged, never invented or dropped.
    services.record_payment(a.telegram_user_id,services.payload_for(invoice),'XTR',50,'sandbox:late-renewal',expiration_date=later,is_recurring=True,sandbox=True,occurred_at=timezone.now()+timedelta(days=30))
    assert ReconciliationIssue.objects.filter(kind='renewal_after_cancel').count()==1

def test_refund_takes_the_plan_back_and_keeps_the_week_counted():
    a=account();invoice,payment=purchase(a)
    job=pdf_job(a);assert job.status=='succeeded'
    refund=services.refund_payment(payment,'Customer sandbox refund',sandbox_account=a)
    assert refund.status=='confirmed' and services.effective_plan(a)=='free'
    assert SubscriptionPeriod.objects.get(payment=payment).revoked_at is not None
    services.refund_payment(payment,'Retry same confirmed refund',sandbox_account=a)
    assert Payment.objects.count()==Refund.objects.count()==1
    usage=usage_snapshot(a)
    assert usage['plan']=='free' and usage['file_jobs']['used']==1,'the task run while paid still counts this week'
    assert no_credits_written()

def test_refund_old_period_does_not_revoke_later_valid_payment():
    a=account();invoice,_=services.create_invoice(a,'plus','old-period-invoice');now=timezone.now()
    old,_=services.record_payment(a.telegram_user_id,services.payload_for(invoice),'XTR',50,'sandbox:old',expiration_date=int((now-timedelta(seconds=2)).timestamp()),is_recurring=True,is_first_recurring=True,occurred_at=now-timedelta(days=30),sandbox=True)
    newer,_=services.record_payment(a.telegram_user_id,services.payload_for(invoice),'XTR',50,'sandbox:new',expiration_date=int((now+timedelta(days=30)).timestamp()),is_recurring=True,occurred_at=now,sandbox=True)
    services.refund_payment(old,'Refund previous period',sandbox_account=a)
    assert services.effective_plan(a)=='plus'
    assert SubscriptionPeriod.objects.get(payment=newer).revoked_at is None
    assert SubscriptionPeriod.objects.get(payment=old).revoked_at is not None

def test_refund_unknown_provider_result_stays_pending(monkeypatch):
    a=account();invoice,payment=purchase(a)
    provider=Mock();provider.refund.side_effect=DomainError('payment_provider_unavailable',503)
    monkeypatch.setattr(services,'provider_for',lambda _:provider)
    with pytest.raises(DomainError): services.refund_payment(payment,'Unknown refund response',sandbox_account=a)
    refund=Refund.objects.get(payment=payment);assert refund.status=='pending' and refund.error_code=='provider_result_unknown'
    assert weekly(a)[0]=='plus','the plan stays until the refund is confirmed'

def test_reconciliation_flags_orphans_and_deduplicates_without_fabricating_period():
    a=account();invoice,payment=purchase(a)
    provider=Mock(sandbox=True)
    provider.transactions.return_value=[{'id':payment.provider_charge_id,'amount':50,'source':{'user':{'id':a.telegram_user_id}}},{'id':'orphan-charge','amount':50,'source':{'user':{'id':a.telegram_user_id},'invoice_payload':services.payload_for(invoice)}}]
    first=services.reconcile_transactions(provider);second=services.reconcile_transactions(provider)
    assert first.checked==second.checked==2 and first.matched==1
    assert ReconciliationIssue.objects.filter(charge_id='orphan-charge').count()==1
    assert Payment.objects.count()==SubscriptionPeriod.objects.count()==1

def test_referrals_are_unique_and_qualified_without_a_reward():
    inviter=account();invitee=account(804);code=services.referral_code(inviter).code
    with pytest.raises(DomainError,match='invalid_referral'): services.claim_referral(inviter,code)
    referral=services.claim_referral(invitee,code);assert services.claim_referral(invitee,code).id==referral.id
    assert services.qualify_referrals(inviter)==0
    assert pdf_job(invitee).status=='succeeded'
    assert services.qualify_referrals(inviter)==1 and services.qualify_referrals(inviter)==0
    referral.refresh_from_db();assert referral.status=='qualified' and referral.qualified_at and referral.grant is None
    assert weekly(inviter)==('free',5,15,3) and no_credits_written(),'counted, rewarded with nothing for now'
    response=client_for(inviter).get('/api/v1/referrals').json()
    assert response['rewards_count']==1 and 'awarded_credits' not in response

def test_support_tickets_are_retired():
    """Customers reach a person on Telegram now; the ticket endpoints are gone."""
    a=account()
    assert client_for(a).get('/api/v1/support/00000000-0000-0000-0000-000000000000/messages').status_code==404
    assert client_for(a).post('/api/v1/billing/payments/00000000-0000-0000-0000-000000000000/refund-request',{'reason':'Please'},content_type='application/json').status_code in (403,404)

def test_commerce_api_csrf_and_closed_live_configuration(settings):
    a=account();client=client_for(a,True)
    assert client.post('/api/v1/billing/invoices',{'offer_id':'plus'},content_type='application/json',HTTP_IDEMPOTENCY_KEY='csrf-required-key').status_code==403
    settings.COMMERCE_SANDBOX_ENABLED=False;settings.COMMERCE_LIVE_ENABLED=True
    settings.COMMERCE_LIVE_OFFERS={'plus':{'kind':'subscription','plan':'plus','name':'Plus','price_xtr':None,'period_seconds':services.PERIOD}}
    assert services.available_offers(a)==[]
    real=resolve_account({'id':805,'first_name':'Live buyer'},is_test=False)
    settings.COMMERCE_LIVE_OFFERS={'tasks100':{'kind':'task_pack','name':'Tasks','price_xtr':25,'quantities':{'file_tasks':100}},
                                   'plus':{'kind':'subscription','plan':'plus','name':'Plus','price_xtr':200,'period_seconds':services.PERIOD}}
    assert [offer.offer_id for offer in services.available_offers(real)]==['plus'],'a pack left in the live list is skipped'

def test_sandbox_entitlements_never_escape_enabled_development(settings):
    from apps.commerce.services import available_offers,refresh_account_entitlement
    a=resolve_account({'id':918181,'first_name':'Sandbox isolation'},is_test=True)
    invoice,_=services.create_invoice(a,'premium','isolation-premium-payment');services.sandbox_pay(a,invoice.id)
    assert weekly(a)==('premium',None,None,None)
    settings.DEBUG=False
    settings.COMMERCE_LIVE_ENABLED=True
    assert available_offers(a)==[]
    assert refresh_account_entitlement(a)=='free'
    assert weekly(a)==('free',5,15,3)

def test_reconciliation_confirms_external_refund_and_checks_owner():
    a=account();invoice,payment=purchase(a)
    provider=Mock(sandbox=True)
    provider.transactions.return_value=[{'id':payment.provider_charge_id,'amount':50,'source':{'user':{'id':a.telegram_user_id+1}}}]
    result=services.reconcile_transactions(provider);assert result.matched==0 and result.issues==1
    assert not Refund.objects.exists()
    provider.transactions.return_value=[{'id':payment.provider_charge_id,'amount':-50,'receiver':{'user':{'id':a.telegram_user_id}}}]
    result=services.reconcile_transactions(provider);assert result.matched==1
    assert Refund.objects.get(payment=payment).status=='confirmed' and services.effective_plan(a)=='free'
