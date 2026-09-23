"""Admin security regression coverage; all provider/process effects are mocked."""
import json
import os
import signal
import time
import uuid
from datetime import datetime,timedelta,timezone as utc
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.http import HttpResponse
from django.test import Client,RequestFactory
from django.utils import timezone
from apps.core.errors import DomainError
from apps.core.models import Account,UsageGrant,SupportTicket,AnalyticsEvent
from apps.core.policy import usage_snapshot,plan_limits,require_feature
from apps.commerce.models import OfferVersion,Invoice,Payment,Refund,Subscription,SubscriptionPeriod,SupportMessage
from operations.auth import COOKIE,begin_session,secret_cipher,totp_code
from operations.models import AuditLog,StaffSession,StaffTOTP,IntegrationConfig
from operations.metrics import Filters
from operations.commerce_views import financial_report
from operations.analytics_extra import engagement
from operations.integrations import save_config,telegram_config
from tests.test_operations import staff_client

pytestmark=pytest.mark.django_db

@pytest.fixture(autouse=True)
def isolated_admin(settings,monkeypatch):
    settings.DEBUG=True;settings.COMMERCE_SANDBOX_ENABLED=True
    monkeypatch.delenv('INTEGRATION_ENCRYPTION_KEY',raising=False)
    import operations.integrations
    monkeypatch.setattr(operations.integrations,'_process',None)


def test_exceptional_grant_idempotency_keeps_feature_and_file_caps():
    account=Account.objects.create(telegram_user_id=717171,is_test=True)
    client,staff=staff_client();url=f'/ops/users/{account.id}/grants'
    body={'idempotency_key':str(uuid.uuid4()),'file_tasks':7,'file_page_units':300,'ai_credits':15,'reason':'Restore allowances after investigated service fault'}
    for _ in range(2):assert client.post(url,body).status_code==302
    assert UsageGrant.objects.filter(source='adjustment').count()==3
    assert AuditLog.objects.filter(action='quota.grant').count()==1
    assert usage_snapshot(account)['meters']['file_tasks']['limit']==97
    assert account.plan=='free' and plan_limits(account)['max_file_mib']==10
    with pytest.raises(DomainError,match='feature_not_in_plan'):require_feature(account,'editor.redact')
    assert client.post(url,{**body,'file_tasks':8}).status_code==400
    assert UsageGrant.objects.filter(source='adjustment',meter='file_tasks').get().quantity==7

@pytest.mark.parametrize('role',['Analyst','Support','Operations','Finance','Content manager'])
def test_sensitive_admin_actions_require_administrator(role):
    client,_=staff_client(role);a=Account.objects.create(telegram_user_id=991991)
    for url in ('/ops/staff','/ops/integrations',f'/ops/users/{a.id}/grants'):
        assert client.post(url,{'reason':'Attempt disallowed role change'}).status_code==403,url


def test_new_mutations_require_csrf_before_side_effects():
    client,staff=staff_client(csrf=True);a=Account.objects.create(telegram_user_id=991991)
    for url in ('/ops/staff','/ops/integrations',f'/ops/users/{a.id}/grants','/ops/jobs/'+str(uuid.uuid4())+'/cancel'):
        assert client.post(url,{'reason':'A sufficiently clear reason'}).status_code==403
    assert get_user_model().objects.count()==1 and not AuditLog.objects.exists() and not IntegrationConfig.objects.exists()


def test_created_staff_requires_totp_and_secret_is_shown_once():
    client,_=staff_client();password='a-unique-initial-password-929'
    response=client.post('/ops/staff',{'action':'create','username':'new-support','password':password,'role':'Support','reason':'Onboard authorized customer support colleague'})
    assert response.status_code==200
    user=get_user_model().objects.get(username='new-support');device=StaffTOTP.objects.get(user=user)
    secret=secret_cipher().decrypt(device.encrypted_secret.encode()).decode()
    assert secret.encode() in response.content and password.encode() not in response.content
    assert secret not in device.encrypted_secret and user.check_password(password)
    assert not user.is_superuser and list(user.groups.values_list('name',flat=True))==['Support']
    assert secret.encode() not in client.get('/ops/staff').content
    assert secret not in json.dumps(list(AuditLog.objects.values('before','after','reason')))
    outsider=Client();assert outsider.post('/ops/login',{'username':user.username,'password':password,'code':''}).status_code==200
    assert COOKIE not in outsider.cookies
    code=totp_code(secret,int(time.time())//30)
    assert outsider.post('/ops/login',{'username':user.username,'password':password,'code':code}).status_code==302
    assert COOKIE in outsider.cookies


def test_role_change_revokes_sessions_and_clears_legacy_superuser():
    admin,actor=staff_client();old_client,user=staff_client('Finance')
    user.is_superuser=True;user.save(update_fields=['is_superuser'])
    assert old_client.get('/ops/integrations').status_code==200
    response=admin.post('/ops/staff',{'action':'update','user_id':user.id,'role':'Support','active':'on','reason':'Remove elevated access after role reassignment'})
    assert response.status_code==200
    user.refresh_from_db();assert not user.is_superuser and user.is_active
    assert not StaffSession.objects.filter(user=user).exists()
    assert old_client.get('/ops/integrations').status_code==302
    renewed=Client();renewed.cookies[COOKIE]=begin_session(HttpResponse(),user).cookies[COOKIE].value
    assert renewed.get('/ops/integrations').status_code==403 and renewed.get('/ops/support').status_code==200
    event=AuditLog.objects.get(action='staff.access_changed');assert event.before['superuser'] and event.after['superuser'] is False
    before=StaffSession.objects.filter(user=actor).count()
    response=admin.post('/ops/staff',{'action':'update','user_id':actor.id,'role':'Support','reason':'Self demotion must be blocked'})
    actor.refresh_from_db();assert actor.is_active and actor.groups.filter(name='Administrator').exists()
    assert StaffSession.objects.filter(user=actor).count()==before and AuditLog.objects.filter(action='staff.access_changed').count()==1


def test_invalid_staff_identifier_and_support_reply_fail_safely():
    admin,_=staff_client()
    assert admin.post('/ops/staff',{'action':'update','user_id':'not-an-integer','role':'Support','reason':'Reject malformed user identifier'}).status_code==200
    account=Account.objects.create(telegram_user_id=981717)
    ticket=SupportTicket.objects.create(account=account,subject='Question',message='Investigate')
    response=admin.post(f'/ops/support/{ticket.id}',{'reply':'x'*4001,'reason':'Attempt oversized support response'})
    assert response.status_code==400
    ticket.refresh_from_db();assert ticket.status=='open' and not SupportMessage.objects.exists() and not AuditLog.objects.exists()


def test_credentials_are_encrypted_never_rendered_or_audited(settings,monkeypatch):
    client,_=staff_client();token='123456789:'+('A'*32);apikey='sk-unit-test-fixture-never-network'
    response=client.post('/ops/integrations',{'integration':'telegram','action':'save','token':token,'username':'fixture_bot','webapp_url':'http://localhost:3000/en/app','reason':'Configure isolated test fixture without external calls'})
    assert response.status_code==302
    assert telegram_config()['token']==token
    client.post('/ops/integrations',{'integration':'ai','action':'save','api_key':apikey,'mode':'openai','model':'fixture-model','reason':'Configure provider fixture for encryption regression'})
    html=client.get('/ops/integrations').content.decode()
    assert token not in html and apikey not in html
    for row in IntegrationConfig.objects.all():
        assert token.encode() not in bytes(row.encrypted_secrets) and apikey.encode() not in bytes(row.encrypted_secrets)
        assert token not in json.dumps(row.configuration) and apikey not in json.dumps(row.configuration)
    audit=json.dumps(list(AuditLog.objects.values('before','after','reason')))
    assert token not in audit and apikey not in audit
    assert (settings.PRIVATE_STORAGE_ROOT/'integration.key').stat().st_mode&0o777==0o600
    save_config('telegram',{'token':'','username':'fixture_bot','webapp_url':'http://localhost:3000/en/app'})
    assert telegram_config()['token']==token
    def no_network(*args,**kwargs):raise RuntimeError('Provider failure URL contains '+token)
    monkeypatch.setattr('operations.integrations.urllib.request.urlopen',no_network)
    response=client.post('/ops/integrations',{'integration':'telegram','action':'test','reason':'Simulate provider failure response'})
    assert response.status_code==200 and token.encode() not in response.content
    assert b'bot_connection_failed' in response.content

@pytest.mark.parametrize('url',['https:///no-host','https://login:password@example.com','http://localhost:bad','https://exa\nmple.com','javascript:alert(1)'])
def test_invalid_or_credential_bearing_workspace_urls_rejected(url):
    with pytest.raises(DomainError,match='invalid_webapp_url'):save_config('telegram',{'webapp_url':url})
    assert not IntegrationConfig.objects.exists()


def test_ai_action_cannot_trigger_telegram_connection_test(monkeypatch):
    client,_=staff_client();request=Mock(side_effect=AssertionError('Unexpected provider call'))
    monkeypatch.setattr('operations.integration_views.test_telegram',request)
    response=client.post('/ops/integrations',{'integration':'ai','action':'test','reason':'Reject action with wrong integration target'})
    assert response.status_code==200 and b'invalid_parameters' in response.content and not request.called


def test_production_bot_status_does_not_inspect_the_api_pid_namespace(settings,monkeypatch):
    client,_=staff_client()
    settings.DEBUG=False
    status=Mock(side_effect=AssertionError('A service-managed bot has a separate PID namespace'))
    monkeypatch.setattr('operations.integration_views.runner_status',status)
    response=client.get('/ops/integrations')
    assert response.status_code==200
    assert b'Waiting for credentials' in response.content
    assert b'The server starts the bot automatically' in response.content
    assert b'Start local bot' not in response.content
    save_config('telegram',{'token':'123456789:'+('A'*32),'username':'fixture_bot',
                            'webapp_url':'https://pdfmaster.orderdesk.live/en/app'})
    assert b'Managed by server' in client.get('/ops/integrations').content
    assert not status.called


def test_runner_status_requires_held_lock_and_current_project_command(settings,monkeypatch):
    import operations.integrations as integrations
    from telegram.locking import polling_lock
    settings.PRIVATE_STORAGE_ROOT.mkdir(parents=True,exist_ok=True)
    lock=settings.PRIVATE_STORAGE_ROOT/'runbot.lock';lock.write_text(str(os.getpid()))
    process=Mock(return_value=SimpleNamespace(returncode=0,stdout=f'{os.sys.executable} {settings.BASE_DIR}/manage.py runbot'))
    monkeypatch.setattr(integrations.subprocess,'run',process)
    assert integrations.runner_status()=='stopped' and not process.called
    with polling_lock():
        assert integrations.runner_status()=='running'
        process.return_value.stdout=f'{os.sys.executable} /another/project/manage.py runbot'
        assert integrations.runner_status()=='stopped'
        process.return_value.stdout=f'{os.sys.executable} manage.py runbot'
        assert integrations.runner_status()=='stopped'
        process.return_value.stdout=f'{os.sys.executable} {settings.BASE_DIR}/manage.py runbot'
        killed=Mock();monkeypatch.setattr(integrations.os,'kill',killed)
        integrations.control_runner('stop');killed.assert_called_once_with(os.getpid(),signal.SIGTERM)
    assert integrations.runner_status()=='stopped'


def payment_fixture(account,amount,occurred,*,sandbox=False):
    key=uuid.uuid4().hex
    offer=OfferVersion.objects.create(id=key,offer_id='fixture',version='fixture-v1',kind='subscription',plan='plus',name='Fixture only',price_xtr=amount,period_seconds=2592000,sandbox=sandbox)
    invoice=Invoice.objects.create(account=account,offer=offer,amount_xtr=amount,idempotency_key=key,request_hash=key,payload_hash=key,expires_at=occurred+timedelta(minutes=10),sandbox=sandbox)
    return Payment.objects.create(account=account,invoice=invoice,provider_charge_id='fixture:'+key,amount_xtr=amount,kind='subscription',plan='plus',occurred_at=occurred,sandbox=sandbox)


def filter_for(start,end,**extra):return Filters.from_request(RequestFactory().get('/',{'date_from':start,'date_to':end,**extra}))


def test_finance_refunds_use_own_period_and_production_excludes_every_test_dimension(monkeypatch):
    now=datetime(2026,9,23,tzinfo=utc.utc);monkeypatch.setattr('operations.commerce_views.timezone.now',lambda:now)
    account=Account.objects.create(telegram_user_id=819191,display_name='SECRET-FINANCE-IDENTITY',created_at=datetime(2026,8,1,tzinfo=utc.utc))
    old=payment_fixture(account,50,datetime(2026,8,25,tzinfo=utc.utc))
    current=payment_fixture(account,75,datetime(2026,9,5,tzinfo=utc.utc))
    Refund.objects.create(payment=old,amount_xtr=50,status='confirmed',reason='Fixture refund',confirmed_at=datetime(2026,9,6,tzinfo=utc.utc))
    payment_fixture(account,900,now,sandbox=True)
    test=Account.objects.create(telegram_user_id=819192,is_test=True,created_at=datetime(2026,8,1,tzinfo=utc.utc))
    payment_fixture(test,800,now,sandbox=False);payment_fixture(test,700,now,sandbox=True)
    sub=Subscription.objects.create(account=account,invoice=current.invoice,offer=current.invoice.offer,plan='plus',first_charge_id=current.provider_charge_id,current_period_end=datetime(2026,10,5,tzinfo=utc.utc),sandbox=False)
    SubscriptionPeriod.objects.create(subscription=sub,payment=current,account=account,plan='plus',starts_at=current.occurred_at,ends_at=sub.current_period_end,revoked_at=datetime(2026,9,18,tzinfo=utc.utc),sandbox=False)
    report=financial_report(filter_for('2026-09-01','2026-10-01'))
    assert report['totals']=={'gross':75,'refunds':50,'net':25,'payers':1,'paid':0,'renewals':0,'first':0,'run_rate':0}
    assert financial_report(filter_for('2026-09-01','2026-09-15'))['totals']['paid']==1
    assert financial_report(filter_for('2026-08-01','2026-09-01'))['totals']['gross']==50
    assert financial_report(filter_for('2026-08-01','2026-09-01'))['totals']['refunds']==0
    assert financial_report(filter_for('2026-09-01','2026-10-01',environment='development'))['totals']['gross']==700
    analyst,_=staff_client('Analyst');url='/ops/analytics/revenue?date_from=2026-09-01&date_to=2026-10-01'
    response=analyst.get(url);assert response.status_code==200
    assert account.display_name.encode() not in response.content and str(account.id).encode() not in response.content and str(current.id).encode() not in response.content
    assert analyst.get('/ops/payments').status_code==403 and analyst.post('/ops/payments/'+str(current.id),{'reason':'Attempt disallowed refund'}).status_code==403
    finance,_=staff_client('Finance');assert account.display_name.encode() in finance.get(url).content


def test_activity_uses_actual_event_channel_and_does_not_mark_immature_retention_zero(monkeypatch):
    now=datetime(2026,9,23,12,tzinfo=utc.utc);monkeypatch.setattr('operations.analytics_extra.timezone.now',lambda:now)
    a=Account.objects.create(telegram_user_id=71122,first_verified_channel='web',created_at=now-timedelta(days=5))
    newcomer=Account.objects.create(telegram_user_id=71123,first_verified_channel='bot',created_at=now-timedelta(hours=1))
    AnalyticsEvent.objects.create(account=a,event_type='job.accepted',channel='bot',environment='production',occurred_at=now-timedelta(minutes=30))
    report=engagement(filter_for('2026-09-01','2026-10-01',channel='bot'))
    assert report['activity'][0]['users']==1
    assert all(v['eligible']==0 and v['percent'] is None for v in report['retention'])
