"""Card transfers are the only way to pay; Telegram Stars is gone.

What is left to check here: the paid period and the weekly limits that come
with it, a refund taking the plan back, a sandbox period never leaving
development, referrals, and the API surface the Stars checkout left behind.
"""
import io
import uuid
from datetime import timedelta
import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from pypdf import PdfWriter
from apps.core.identity import resolve_account
from apps.core.models import UsageGrant
from apps.core.policy import usage_snapshot,plan_limits
from apps.core.services import upload_file,create_quote,submit_job,execute_job
from apps.commerce import manual,services
from apps.commerce.models import Payment,Subscription,SubscriptionPeriod,PaymentGrant,Refund,BalanceAdjustment,ManualPayment,OfferVersion,Invoice
from tests.test_manual_payments import finance,paid

pytestmark=pytest.mark.django_db

def account(number=801): return resolve_account({'id':number,'first_name':'Commerce test'},is_test=True)
def client_for(a,csrf=False):
    c=Client(enforce_csrf_checks=csrf);session=c.session;session['customer_account_id']=str(a.id);session.save();return c

def reviewer():
    # paid() makes the Finance reviewer once; a refund is signed by the same person.
    return get_user_model().objects.filter(username='finance').first() or finance()

def weekly(a):
    usage=usage_snapshot(a);return usage['plan'],usage['ai_documents']['limit'],usage['file_jobs']['limit'],usage['edits_per_file']

def no_credits_written():
    return not UsageGrant.objects.exists() and not PaymentGrant.objects.exists() and not BalanceAdjustment.objects.exists()

def pdf_job(a,key='financial-job-key'):
    writer=PdfWriter();writer.add_blank_page(width=210,height=400);stream=io.BytesIO();writer.write(stream)
    asset=upload_file(a,SimpleUploadedFile('financial.pdf',stream.getvalue()))
    q=create_quote(a,'pdf.rotate',[str(asset.id)],{})
    job,_=submit_job(a,q.id,key);return execute_job(job.id)

def test_weekly_limits_follow_the_paid_period_and_the_shared_account():
    a=account();assert weekly(a)==('free',5,15,3)
    paid(a,'plus');payment=Payment.objects.get()
    assert payment.provider=='manual' and not payment.sandbox
    # Only the weekly limits come with the payment: the file size is the same on every plan.
    assert weekly(a)==('plus',20,None,10) and plan_limits(a)['max_file_mib']==200
    SubscriptionPeriod.objects.filter(payment=payment).update(ends_at=timezone.now()-timedelta(seconds=1))
    assert weekly(a)==('free',5,15,3),'a lapsed period leaves nothing behind'
    assert resolve_account({'id':a.telegram_user_id,'first_name':'Same from bot'},'bot').id==a.id
    assert no_credits_written()

def test_refund_takes_the_plan_back_and_keeps_the_week_counted():
    a=account();paid(a,'plus');request=ManualPayment.objects.get()
    job=pdf_job(a);assert job.status=='succeeded'
    manual.refund(request.id,reviewer(),'Returned by bank transfer')
    refund=Refund.objects.get(payment=request.payment)
    assert refund.status=='confirmed' and services.effective_plan(a)=='free'
    assert SubscriptionPeriod.objects.get(payment=request.payment).revoked_at is not None
    assert services.refund_payment(request.payment,'Retry same confirmed refund',actor=reviewer()).id==refund.id
    assert Payment.objects.count()==Refund.objects.count()==1
    usage=usage_snapshot(a)
    assert usage['plan']=='free' and usage['file_jobs']['used']==1,'the task run while paid still counts this week'
    assert no_credits_written()

def test_refund_old_period_does_not_revoke_later_valid_payment():
    a=account();now=timezone.now()
    paid(a,'plus');old=ManualPayment.objects.get()
    # The first month was paid for and is over; the second was paid for today.
    SubscriptionPeriod.objects.filter(payment=old.payment).update(starts_at=now-timedelta(days=32),ends_at=now-timedelta(days=2))
    paid(a,'plus');newer=ManualPayment.objects.exclude(pk=old.pk).get()
    manual.refund(old.id,reviewer(),'Refund previous period')
    assert services.effective_plan(a)=='plus'
    assert SubscriptionPeriod.objects.get(payment=newer.payment).revoked_at is None
    assert SubscriptionPeriod.objects.get(payment=old.payment).revoked_at is not None

def test_a_refund_asks_no_provider_and_needs_finance():
    a=account();paid(a,'plus');payment=Payment.objects.get()
    customer=get_user_model().objects.create_user(username='not-staff',password='long-staff-password')
    with pytest.raises(services.DomainError,match='permission_denied'): services.refund_payment(payment,'Returned by bank transfer',actor=customer)
    with pytest.raises(services.DomainError,match='audit_reason_required'): services.refund_payment(payment,'no',actor=reviewer())
    assert not Refund.objects.exists() and services.effective_plan(a)=='plus'
    # Nothing is asked of Telegram: there is no provider left to ask.
    assert not hasattr(services,'provider_for')
    refund=services.refund_payment(payment,'Returned by bank transfer',actor=reviewer())
    assert refund.status=='confirmed' and refund.error_code=='' and services.effective_plan(a)=='free'
    assert ManualPayment.objects.get().status=='refunded'

def test_a_sandbox_period_never_leaves_enabled_development(settings):
    a=resolve_account({'id':918181,'first_name':'Sandbox isolation'},is_test=True);now=timezone.now()
    offer=OfferVersion.objects.create(id='sandbox:history:premium',offer_id='premium',version='history',kind='subscription',plan='premium',name='Premium',price_xtr=150,period_seconds=services.PERIOD,sandbox=True,enabled=False)
    invoice=Invoice.objects.create(account=a,offer=offer,snapshot={},amount_xtr=150,status='paid',idempotency_key='sandbox-history',request_hash='x',payload_hash='x',sandbox=True,expires_at=now,paid_at=now)
    payment=Payment.objects.create(account=a,invoice=invoice,provider_charge_id='sandbox:history',amount_xtr=150,kind='subscription',plan='premium',sandbox=True,occurred_at=now)
    subscription=Subscription.objects.create(account=a,invoice=invoice,offer=offer,plan='premium',status='active',renewal_enabled=False,first_charge_id='sandbox:history',current_period_end=now+timedelta(days=30),sandbox=True)
    SubscriptionPeriod.objects.create(subscription=subscription,payment=payment,account=a,plan='premium',starts_at=now-timedelta(minutes=1),ends_at=now+timedelta(days=30),sandbox=True)
    assert services.refresh_account_entitlement(a)=='premium' and weekly(a)==('premium',None,None,None)
    settings.DEBUG=False
    assert services.refresh_account_entitlement(a)=='free' and weekly(a)==('free',5,15,3)

def test_the_stars_checkout_is_gone_from_the_api():
    a=account();c=client_for(a);nil=uuid.UUID(int=0)
    for method,url in (('get','/api/v1/billing/offers'),('get',f'/api/v1/billing/invoices/{nil}'),('post',f'/api/v1/billing/invoices/{nil}/sandbox-pay'),
                       ('post','/api/v1/billing/subscription/cancel-renewal'),('post','/api/v1/billing/subscription/resume-renewal'),
                       ('post','/api/v1/billing/subscription/schedule-plan-change'),('post','/api/v1/billing/subscription/sandbox-renew'),
                       ('post',f'/api/v1/billing/payments/{nil}/sandbox-refund')):
        assert getattr(c,method)(url,{},content_type='application/json').status_code==404,url
    state=c.get('/api/v1/billing/subscription').json()
    assert state['plan']=='free' and state['subscription'] is None and 'checkout_enabled' not in state
    paid(a,'plus')
    state=c.get('/api/v1/billing/subscription').json()
    assert state['plan']=='plus' and state['subscription']['provider']=='manual' and not state['subscription']['renewal_enabled']
    rows=c.get('/api/v1/billing/transactions').json()['results']
    assert [(row['provider'],row['plan'],row['currency'],row['amount'],row['refunded']) for row in rows]==[('manual','plus','UZS',20000,0)]
    assert not {'amount_xtr','refunded_xtr'}&set(rows[0]),"so'm are not named after Stars"
    for name in ('create_invoice','record_payment','validate_precheckout','sandbox_pay','set_renewal','schedule_plan_change'):
        assert not hasattr(services,name),name

def test_the_feature_report_retires_the_stars_checkout():
    """docs/feature-status.json is generated (scripts/coverage_report.py): the
    Stars checkout keeps its ID and ticket, so the catalog stays whole, but
    claims no implementation, since every Stars function is gone."""
    import json
    from django.conf import settings
    report=json.loads((settings.BASE_DIR/'docs/feature-status.json').read_text())
    stars=next(f for f in report['features'] if f['id']=='billing.stars')
    assert stars['status']=='retired' and stars['evidence']==[] and 'card transfer is the only checkout' in stars['gate']
    assert len(report['features'])==128 and '`retired`' in (settings.BASE_DIR/'docs/feature-coverage.md').read_text()

def test_commerce_api_requires_csrf():
    a=account();client=client_for(a,True)
    assert client.post('/api/v1/billing/manual',{'plan':'plus'},content_type='application/json').status_code==403
    assert client.post('/api/v1/referrals',{'code':'x'},content_type='application/json').status_code==403
    assert not ManualPayment.objects.exists()

def test_the_reconcile_command_only_expires_and_qualifies():
    a=account();paid(a,'plus')
    Subscription.objects.update(current_period_end=timezone.now()-timedelta(seconds=1))
    SubscriptionPeriod.objects.update(ends_at=timezone.now()-timedelta(seconds=1))
    out=io.StringIO();call_command('reconcilepayments',stdout=out)
    assert 'Expired subscriptions: 1; qualified referrals: 0.' in out.getvalue() and 'Checked' not in out.getvalue()
    a.refresh_from_db();assert a.plan=='free'
    # The Stars-era flag went with the provider it chose between.
    with pytest.raises(CommandError): call_command('reconcilepayments','--local-only',stdout=out)

def test_referrals_are_unique_and_qualified_without_a_reward():
    inviter=account();invitee=account(804);code=services.referral_code(inviter).code
    with pytest.raises(services.DomainError,match='invalid_referral'): services.claim_referral(inviter,code)
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
