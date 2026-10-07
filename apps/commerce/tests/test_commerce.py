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
from apps.core.models import UsageGrant,UsageLedger,Account
from apps.core.policy import usage_snapshot,plan_limits
from apps.core.services import upload_file,create_quote,submit_job,execute_job
from apps.commerce import services
from apps.commerce.models import Invoice,Payment,Subscription,SubscriptionPeriod,PaymentGrant,Refund,BalanceAdjustment,CommerceAction,ReconciliationIssue,Referral

pytestmark=pytest.mark.django_db

def account(number=801): return resolve_account({'id':number,'first_name':'Commerce test'},is_test=True)
def client_for(a,csrf=False):
    c=Client(enforce_csrf_checks=csrf);session=c.session;session['customer_account_id']=str(a.id);session.save();return c

def purchase(a,offer='plus',key='test-invoice-key'):
    invoice,_=services.create_invoice(a,offer,key)
    payment,_=services.sandbox_pay(a,invoice.id)
    a.refresh_from_db();return invoice,payment

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
    assert PaymentGrant.objects.count()==3
    assert usage_snapshot(a)['meters']['file_tasks']['limit']==1500

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
    a=account();invoice,_=services.create_invoice(a,'tasks100','expiring-invoice-key')
    Invoice.objects.filter(pk=invoice.id).update(expires_at=timezone.now()-timedelta(seconds=1))
    with pytest.raises(DomainError,match='invoice_expired'): services.sandbox_pay(a,invoice.id)
    with pytest.raises(DomainError,match='payment_amount_mismatch'): services.record_payment(a.telegram_user_id,services.payload_for(invoice),'XTR',1,'bad-charge',sandbox=True)
    assert Payment.objects.count()==0

def test_grants_correct_across_tier_pack_expiry_and_shared_account():
    a=account();free=usage_snapshot(a);assert free['meters']['file_tasks']['remaining']==300
    invoice,payment=purchase(a)
    purchase(a,'tasks100','tasks-after-upgrade')
    paid=usage_snapshot(a);assert paid['meters']['file_tasks']['remaining']==1600
    assert plan_limits(a)['max_file_mib']==100
    SubscriptionPeriod.objects.filter(payment=payment).update(ends_at=timezone.now()-timedelta(seconds=1))
    free_again=usage_snapshot(a);assert free_again['plan']=='free' and free_again['meters']['file_tasks']['remaining']==400
    pack=UsageGrant.objects.filter(account=a,source='purchased',meter='file_tasks').get();assert pack.expires_at is None
    assert resolve_account({'id':a.telegram_user_id,'first_name':'Same from bot'},'bot').id==a.id

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

def test_renewal_duplicate_grants_and_canceled_race_flag():
    a=account();invoice,payment=purchase(a)
    renewal,_=services.sandbox_renew(a,'renewal-idempotency-key')
    same,created=services.sandbox_renew(a,'renewal-idempotency-key')
    assert not created and same.id==renewal.id
    assert Payment.objects.count()==2 and SubscriptionPeriod.objects.count()==2
    assert PaymentGrant.objects.count()==6
    assert usage_snapshot(a)['meters']['file_tasks']['limit']==1500
    sub=services.set_renewal(a,False)
    later=int((sub.current_period_end+timedelta(seconds=services.PERIOD)).timestamp())
    # Authoritative unexpected renewal is recorded and flagged, never invented or dropped.
    services.record_payment(a.telegram_user_id,services.payload_for(invoice),'XTR',50,'sandbox:late-renewal',expiration_date=later,is_recurring=True,sandbox=True,occurred_at=timezone.now()+timedelta(days=30))
    assert ReconciliationIssue.objects.filter(kind='renewal_after_cancel').count()==1

def test_refund_full_preserves_history_and_revokes_only_related_grants():
    a=account();invoice,payment=purchase(a)
    job=pdf_job(a);assert job.status=='succeeded'
    refund=services.refund_payment(payment,'Customer sandbox refund',sandbox_account=a)
    assert refund.status=='confirmed' and services.effective_plan(a)=='free'
    assert Payment.objects.count()==1 and UsageLedger.objects.filter(job=job,kind='consume').exists()
    adjustment=BalanceAdjustment.objects.filter(refund=refund,meter='file_tasks').get();assert adjustment.consumed_units==1
    services.refund_payment(payment,'Retry same confirmed refund',sandbox_account=a)
    assert Refund.objects.count()==1
    assert usage_snapshot(a)['meters']['file_tasks']['remaining']==300

def test_refund_old_period_does_not_revoke_later_valid_payment():
    a=account();invoice,_=services.create_invoice(a,'plus','old-period-invoice');now=timezone.now()
    old,_=services.record_payment(a.telegram_user_id,services.payload_for(invoice),'XTR',50,'sandbox:old',expiration_date=int((now-timedelta(seconds=2)).timestamp()),is_recurring=True,is_first_recurring=True,occurred_at=now-timedelta(days=30),sandbox=True)
    newer,_=services.record_payment(a.telegram_user_id,services.payload_for(invoice),'XTR',50,'sandbox:new',expiration_date=int((now+timedelta(days=30)).timestamp()),is_recurring=True,occurred_at=now,sandbox=True)
    services.refund_payment(old,'Refund previous period',sandbox_account=a)
    assert services.effective_plan(a)=='plus'
    assert SubscriptionPeriod.objects.get(payment=newer).revoked_at is None
    assert not PaymentGrant.objects.filter(payment=newer,revoked_at__isnull=False).exists()

def test_refund_unknown_provider_result_stays_pending(monkeypatch):
    a=account();invoice,payment=purchase(a,'tasks100')
    provider=Mock();provider.refund.side_effect=DomainError('payment_provider_unavailable',503)
    monkeypatch.setattr(services,'provider_for',lambda _:provider)
    with pytest.raises(DomainError): services.refund_payment(payment,'Unknown refund response',sandbox_account=a)
    refund=Refund.objects.get(payment=payment);assert refund.status=='pending' and refund.error_code=='provider_result_unknown'
    assert usage_snapshot(a)['meters']['file_tasks']['remaining']==400

def test_reconciliation_flags_orphans_and_deduplicates_without_fabricating_period():
    a=account();invoice,payment=purchase(a)
    provider=Mock(sandbox=True)
    provider.transactions.return_value=[{'id':payment.provider_charge_id,'amount':50,'source':{'user':{'id':a.telegram_user_id}}},{'id':'orphan-charge','amount':50,'source':{'user':{'id':a.telegram_user_id},'invoice_payload':services.payload_for(invoice)}}]
    first=services.reconcile_transactions(provider);second=services.reconcile_transactions(provider)
    assert first.checked==second.checked==2 and first.matched==1
    assert ReconciliationIssue.objects.filter(charge_id='orphan-charge').count()==1
    assert Payment.objects.count()==SubscriptionPeriod.objects.count()==1

def test_referrals_are_unique_qualified_and_expire():
    inviter=account();invitee=account(804);code=services.referral_code(inviter).code
    with pytest.raises(DomainError,match='invalid_referral'): services.claim_referral(inviter,code)
    referral=services.claim_referral(invitee,code);assert services.claim_referral(invitee,code).id==referral.id
    assert services.qualify_referrals(inviter)==0
    assert pdf_job(invitee).status=='succeeded'
    assert services.qualify_referrals(inviter)==1 and services.qualify_referrals(inviter)==0
    referral.refresh_from_db();assert referral.grant.quantity==10
    assert timedelta(days=29)<referral.grant.expires_at-timezone.now()<timedelta(days=31)
    from apps.core.policy import plan_limits
    assert usage_snapshot(inviter)['meters']['ai_credits']['remaining']==plan_limits(inviter)['ai_credits']+referral.grant.quantity

def test_support_tickets_are_retired():
    """Customers reach a person on Telegram now; the ticket endpoints are gone."""
    a=account()
    assert client_for(a).get('/api/v1/support/00000000-0000-0000-0000-000000000000/messages').status_code==404
    assert client_for(a).post('/api/v1/billing/payments/00000000-0000-0000-0000-000000000000/refund-request',{'reason':'Please'},content_type='application/json').status_code in (403,404)

def test_commerce_api_csrf_and_closed_live_configuration(settings):
    a=account();client=client_for(a,True)
    assert client.post('/api/v1/billing/invoices',{'offer_id':'plus'},content_type='application/json',HTTP_IDEMPOTENCY_KEY='csrf-required-key').status_code==403
    settings.COMMERCE_SANDBOX_ENABLED=False;settings.COMMERCE_LIVE_ENABLED=True
    settings.COMMERCE_LIVE_OFFERS={'plus':{'kind':'subscription','plan':'plus','name':'Plus','price_xtr':None,'quantities':{'file_tasks':500},'period_seconds':services.PERIOD}}
    assert services.available_offers(a)==[]

def test_sandbox_entitlements_and_packs_never_escape_enabled_development(settings):
    from apps.core.policy import usage_snapshot
    from apps.commerce.services import available_offers,refresh_account_entitlement
    a=resolve_account({'id':918181,'first_name':'Sandbox isolation'},is_test=True)
    invoice,_=services.create_invoice(a,'plus','isolation-plus-payment');services.sandbox_pay(a,invoice.id)
    invoice,_=services.create_invoice(a,'tasks100','isolation-pack-payment');services.sandbox_pay(a,invoice.id)
    assert usage_snapshot(a)['meters']['file_tasks']['limit']==1600
    settings.DEBUG=False
    settings.COMMERCE_LIVE_ENABLED=True
    assert available_offers(a)==[]
    assert refresh_account_entitlement(a)=='free'
    assert usage_snapshot(a)['meters']['file_tasks']['limit']==300

def test_reconciliation_confirms_external_refund_and_checks_owner():
    a=account();invoice,payment=purchase(a)
    provider=Mock(sandbox=True)
    provider.transactions.return_value=[{'id':payment.provider_charge_id,'amount':50,'source':{'user':{'id':a.telegram_user_id+1}}}]
    result=services.reconcile_transactions(provider);assert result.matched==0 and result.issues==1
    assert not Refund.objects.exists()
    provider.transactions.return_value=[{'id':payment.provider_charge_id,'amount':-50,'receiver':{'user':{'id':a.telegram_user_id}}}]
    result=services.reconcile_transactions(provider);assert result.matched==1
    assert Refund.objects.get(payment=payment).status=='confirmed' and services.effective_plan(a)=='free'
