from datetime import datetime, timedelta, timezone as tz
import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.http import HttpResponse
from django.test import Client, RequestFactory
from django.utils import timezone
from apps.core.models import Account, SupportTicket
from operations.auth import COOKIE, begin_session
from operations.i18n import CATALOGS, EN
from operations.metrics import Filters, report
from operations.models import AuditLog, StaffSession
pytestmark=pytest.mark.django_db

def staff_client(role='Administrator',csrf=False):
    u=get_user_model().objects.create_user(username=role.lower().replace(' ','-'),password='long-staff-password',is_staff=True)
    u.groups.add(Group.objects.get_or_create(name=role)[0])
    c=Client(enforce_csrf_checks=csrf);c.cookies[COOKIE]=begin_session(HttpResponse(),u).cookies[COOKIE].value
    return c,u

def filters(**kwargs):
    return Filters.from_request(RequestFactory().get('/',{'date_from':'2026-09-01','date_to':'2026-10-01',**kwargs}))

def test_customer_session_cannot_authorize_staff_even_with_django_superuser():
    a=Account.objects.create(telegram_user_id=101);c=Client();s=c.session;s['customer_account_id']=str(a.id);s.save()
    assert c.get('/ops/overview').status_code==302
    assert c.get('/ops/api/v1/summary').status_code==401
    u=get_user_model().objects.create_user('separate',is_staff=True,is_superuser=True);c.force_login(u)
    assert c.get('/ops/api/v1/summary').status_code==401

def test_analyst_cannot_inspect_identifiers_or_mutate():
    c,_=staff_client('Analyst')
    for p in ['users','support','payments','audit','export/users','export/jobs']:
        assert c.get('/ops/'+p).status_code==403,p
    assert c.get('/ops/overview').status_code==200
    assert c.get('/ops/export/features').status_code==200

def test_expired_and_disabled_staff_sessions_rejected():
    c,u=staff_client();StaffSession.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
    assert c.get('/ops/api/v1/summary').status_code==401
    c.cookies[COOKIE]=begin_session(HttpResponse(),u).cookies[COOKIE].value;u.is_active=False;u.save()
    assert c.get('/ops/api/v1/summary').status_code==401

def test_staff_sign_in_with_username_and_password_alone(settings):
    """No authenticator code: the password is the whole sign-in, for every role."""
    settings.DEBUG=False
    get_user_model().objects.create_user('protected',password='long-staff-password',is_staff=True,is_superuser=True)
    c=Client();r=c.post('/ops/login',{'username':'protected','password':'wrong-password'})
    assert r.status_code==200 and COOKIE not in c.cookies
    r=c.post('/ops/login',{'username':'protected','password':'long-staff-password'})
    assert r.status_code==302 and COOKIE in c.cookies
    assert AuditLog.objects.get(action='staff.login').reason=='Password verified'
    assert b'name="code"' not in Client().get('/ops/login').content
    customer=get_user_model().objects.create_user('not-staff',password='long-staff-password')
    r=Client().post('/ops/login',{'username':'not-staff','password':'long-staff-password'})
    assert r.status_code==200, 'a non-staff account still cannot sign in'
    assert Client().post('/ops/dev-login').status_code==403

def test_local_staff_login_needs_flag_loopback_and_csrf(settings):
    settings.DEBUG=True;settings.DEV_AUTH_ENABLED=True;c=Client(enforce_csrf_checks=True)
    assert c.post('/ops/dev-login',HTTP_HOST='localhost').status_code==403
    assert c.get('/ops/login',HTTP_HOST='localhost').status_code==200
    token=c.cookies['csrftoken'].value
    assert c.post('/ops/dev-login',HTTP_HOST='localhost',HTTP_X_CSRFTOKEN=token,REMOTE_ADDR='203.0.113.5').status_code==403
    r=c.post('/ops/dev-login',HTTP_HOST='localhost',HTTP_X_CSRFTOKEN=token)
    assert r.status_code==302 and r.cookies[COOKIE]['httponly'] and r.cookies[COOKIE]['path']=='/ops/'
    assert 'customer_account_id' not in c.session

def test_support_transition_needs_no_reason_and_audit_is_append_only():
    a=Account.objects.create(telegram_user_id=103,is_test=True);t=SupportTicket.objects.create(account=a,subject='Question',message='Please investigate.')
    c,u=staff_client('Support');url=f'/ops/support/{t.id}'
    assert c.post(url,{'status':'resolved'}).status_code==302
    t.refresh_from_db();assert t.status=='resolved'
    e=AuditLog.objects.get();assert e.actor==u and e.before=={'status':'open'} and e.after=={'status':'resolved'}
    assert e.reason=='Changed a support request status'
    e.reason='tampered'
    with pytest.raises(ValueError):e.save()

def test_counts_timezone_and_test_exclusion_are_consistent():
    Account.objects.create(telegram_user_id=201,created_at=datetime(2026,9,1,tzinfo=tz.utc))
    Account.objects.create(telegram_user_id=202,is_test=True,created_at=datetime(2026,9,1,tzinfo=tz.utc))
    Account.objects.create(telegram_user_id=203,created_at=datetime(2026,9,30,20,tzinfo=tz.utc))
    assert report(filters())['totals']['new_users']==2
    r=report(filters(timezone='Asia/Tashkent'));assert r['totals']['new_users']==1 and sum(x['count'] for x in r['daily'])==1
    assert report(filters(environment='development'))['totals']['new_users']==1
    assert report(filters())['totals']['success_rate'] is None

def test_export_matches_filter_and_neutralizes_formula_values():
    a=Account.objects.create(telegram_user_id=210,display_name='=HYPERLINK("evil")',locale='ru',created_at=datetime(2026,9,1,tzinfo=tz.utc))
    Account.objects.create(telegram_user_id=211,locale='en',created_at=datetime(2026,9,1,tzinfo=tz.utc))
    c,_=staff_client('Support');r=c.get('/ops/export/users?date_from=2026-09-01&date_to=2026-10-01&locale=ru')
    assert r.status_code==200
    body=r.content.decode();assert str(a.id) in body and "'=HYPERLINK" in body and ',211,' not in body
    assert 'definitions_version,1.0.0' in body and AuditLog.objects.get().action=='report.export'

def test_all_implemented_staff_routes_render_all_locales():
    from operations.views import PAGE_ROLES
    c,_=staff_client()
    for locale in CATALOGS:
        assert CATALOGS[locale].keys()==EN.keys()
        for p in PAGE_ROLES:
            r=c.get(f'/ops/{p}?lang={locale}')
            assert r.status_code==200,(p,locale,r.content[:300])
            assert r['Cache-Control']=='no-store' and f'lang="{locale}"'.encode() in r.content

def test_password_login_rate_limit():
    c=Client()
    for _ in range(5):assert c.post('/ops/login',{'username':'missing','password':'bad'}).status_code==200
    assert c.post('/ops/login',{'username':'missing','password':'bad'}).status_code==429

def test_support_default_entry_is_role_appropriate():
    c,_=staff_client('Support')
    assert c.get('/ops/').url=='/ops/today'
    assert c.get('/ops/login').url=='/ops/today'
