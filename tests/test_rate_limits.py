"""The limiters count on a store every process shares, per customer, and a Redis outage refuses nobody it should not."""
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
import pytest
from django.core.cache import caches
from django.core.cache.backends.locmem import LocMemCache
from django.core.cache.backends.redis import RedisCache
from apps.core.errors import DomainError
from apps.core.models import AuthRateLimit
from apps.core import views
from tests.test_platform import account,login_client,upload

pytestmark=pytest.mark.django_db
ROOT=Path(__file__).resolve().parent.parent


class Broken:
    """A cache whose every call fails as a Redis outage does."""
    def add(self,*args):raise ConnectionError('Connection refused')
    incr=touch=add
    def close(self):pass


class Shared:
    """What two processes see of one store: a counter neither holds, and a note of who asked."""
    def __init__(self):self.values={};self.calls=[]
    def add(self,key,value,timeout):
        self.calls.append(('add',timeout));return self.values.setdefault(key,value)==value
    def incr(self,key):
        self.values[key]+=1;return self.values[key]
    def touch(self,key,timeout):
        self.calls.append(('touch',timeout));return True
    def close(self):pass


@pytest.fixture
def store(monkeypatch):
    """Puts a stand-in behind the `limits` alias, which is what every limiter asks for."""
    def use(value):
        real=caches.__getitem__
        monkeypatch.setattr(type(caches),'__getitem__',lambda self,alias:value if alias=='limits' else real(alias))
        return value
    return use


class Request:
    def __init__(self,account=None,session=None):self.account=account;self.session=session if session is not None else {};self.META={'REMOTE_ADDR':'10.0.0.1'}


def refused(call):
    with pytest.raises(DomainError) as caught:call()
    assert caught.value.code=='rate_limited' and caught.value.status==429 and caught.value.retryable
    return caught.value


def test_one_customer_cannot_use_up_anothers_limit_through_the_shared_gateway():
    first,second=Request(account()),Request(account(43))
    views.throttle(first,'uploads',2);views.throttle(first,'uploads',2)
    refused(lambda:views.throttle(first,'uploads',2))
    views.throttle(second,'uploads',2)


def test_the_routes_count_per_account_over_http(monkeypatch):
    monkeypatch.setattr(views,'throttle',lambda request,key,limit=20,real=views.throttle:real(request,key,1))
    first,second=login_client(account()),login_client(account(43))
    assert first.post('/api/v1/quotes',{},content_type='application/json').status_code!=429
    assert first.post('/api/v1/quotes',{},content_type='application/json').status_code==429
    assert second.post('/api/v1/quotes',{},content_type='application/json').status_code!=429
    assert first.post('/api/v1/jobs',{'quote_id':'x'},content_type='application/json').status_code!=429
    assert first.post('/api/v1/jobs',{'quote_id':'x'},content_type='application/json').status_code==429
    assert first.post('/api/v1/files/uploads').status_code!=429
    assert first.post('/api/v1/files/uploads').status_code==429
    assert second.post('/api/v1/files/uploads').status_code!=429
    asset=upload(account());owner=login_client(account())
    assert owner.get(f'/api/v1/files/{asset.id}/preview').status_code!=429
    assert owner.get(f'/api/v1/files/{asset.id}/preview').status_code==429
    assert second.get(f'/api/v1/files/{asset.id}/preview').status_code!=429


def test_a_shared_link_is_limited_with_no_cookie_and_leaves_no_session_behind():
    """A session made per caller would limit a script with no cookie not at all, and add a row per request."""
    from django.contrib.sessions.models import Session
    from django.test import Client
    for _ in range(30):
        answer=Client().get('/api/v1/shared/a-link-nobody-has')
        assert answer.status_code==404 and 'pdfmaster_session' not in answer.cookies
    assert Client().get('/api/v1/shared/a-link-nobody-has').status_code==429
    assert Client().get('/api/v1/shared/another-link').status_code==404
    assert Session.objects.count()==0


def test_anonymous_visitors_each_get_a_bucket_in_their_session():
    one,two=Request(),Request()
    views.throttle(one,'anonymous',1)
    refused(lambda:views.throttle(one,'anonymous',1))
    views.throttle(two,'anonymous',1)
    assert one.session['rate_identity']!=two.session['rate_identity']


def test_the_auth_routes_keep_their_own_limiter(store):
    shared=store(Shared())
    request=Request()
    for key in ('miniapp','challenge','exchange'):views.throttle(request,key,1)
    assert not shared.calls and AuthRateLimit.objects.count()==3


def test_the_window_runs_from_the_first_request_and_is_not_moved_by_the_rest(store):
    shared=store(Shared())
    customer=account()
    views.account_limit(customer,'cv_reads',5);views.account_limit(customer,'cv_reads',5)
    assert [call for call in shared.calls if call[0]=='touch']==[('touch',60)],'only the request that began the minute sets it'
    assert all(timeout==60 for _,timeout in shared.calls)


def test_a_key_that_expires_between_add_and_incr_begins_the_next_minute(store):
    class Expiring(Shared):
        missed=False
        def incr(self,key):
            if not self.missed:
                self.missed=True;self.values.pop(key,None);raise ValueError('expired')
            return super().incr(key)
    store(Expiring())
    views.count_request('thing','account:1',5)


def test_the_shared_path_is_the_only_one_taken_while_the_store_answers(store):
    shared=store(Shared())
    request=Request(account())
    views.throttle(request,'quotes',2);views.throttle(request,'quotes',2)
    refused(lambda:views.throttle(request,'quotes',2))
    assert shared.values=={f'rate:quotes:account:{request.account.pk}':3}
    assert not AuthRateLimit.objects.exists()


def test_with_the_store_away_the_limit_is_counted_in_the_database(store,caplog):
    store(Broken())
    request,other=Request(account()),Request(account(43))
    views.throttle(request,'quotes',2);views.throttle(request,'quotes',2)
    refused(lambda:views.throttle(request,'quotes',2))
    views.throttle(other,'quotes',2)
    assert AuthRateLimit.objects.count()==2
    assert str(request.account.pk) not in caplog.text


def test_with_the_store_and_the_database_away_the_request_still_goes_through(store,monkeypatch):
    from django.db import OperationalError
    store(Broken())
    def down(*args):raise OperationalError('database is down')
    monkeypatch.setattr('apps.core.customer_auth.auth_limit',down)
    views.throttle(Request(account()),'quotes',1)
    views.throttle(Request(account()),'quotes',1)


def test_an_outage_never_shows_as_an_error_on_a_route(store):
    store(Broken())
    client=login_client(account())
    assert client.post('/api/v1/quotes',{},content_type='application/json').status_code<500
    assert client.post('/api/v1/generation/drafts',{},content_type='application/json').status_code<500


def test_every_other_cache_stays_in_the_process():
    assert isinstance(caches['default'],LocMemCache)


def test_settings_put_the_limiters_on_redis_when_there_is_one():
    code=("import django;django.setup();from django.core.cache import caches;"
          "print(type(caches['limits']).__name__,type(caches['default']).__name__)")
    env={**os.environ,'DJANGO_SETTINGS_MODULE':'config.settings','DEBUG':'1'}
    env.pop('REDIS_URL',None)
    local=subprocess.run([sys.executable,'-c',code],cwd=ROOT,env=env,capture_output=True,text=True,check=True).stdout.split()
    assert local==['LocMemCache','LocMemCache']
    remote=subprocess.run([sys.executable,'-c',code],cwd=ROOT,env={**env,'REDIS_URL':'redis://127.0.0.1:1/0'},capture_output=True,text=True,check=True).stdout.split()
    assert remote==['RedisCache','LocMemCache']
    assert RedisCache.__name__==remote[0]


COUNT_IN_A_PROCESS="""
import django;django.setup()
from apps.core.errors import DomainError
from apps.core.views import count_request
allowed=0
for _ in range({times}):
    try:count_request('two_processes','account:1',{limit});allowed+=1
    except DomainError as error:assert error.code=='rate_limited'
print(allowed)
"""


@pytest.fixture
def redis_url(tmp_path):
    """A real server on a free port, when this machine has one. CI has the client but no server: the stand-ins above cover it there."""
    pytest.importorskip('redis')
    binary=shutil.which('redis-server')
    if not binary:pytest.skip('no redis-server here')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    server=subprocess.Popen([binary,'--port',str(port),'--bind','127.0.0.1','--save','','--appendonly','no','--dir',str(tmp_path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:socket.create_connection(('127.0.0.1',port),.1).close();break
            except OSError:time.sleep(.05)
        yield f'redis://127.0.0.1:{port}/0'
    finally:
        server.kill();server.wait()


def in_process(url,times,limit):
    env={**os.environ,'DJANGO_SETTINGS_MODULE':'config.settings','DEBUG':'1','REDIS_URL':url}
    return subprocess.run([sys.executable,'-c',COUNT_IN_A_PROCESS.format(times=times,limit=limit)],cwd=ROOT,env=env,capture_output=True,text=True,check=True)


def test_two_processes_share_one_counter(redis_url):
    first=in_process(redis_url,6,10);second=in_process(redis_url,6,10)
    assert (int(first.stdout),int(second.stdout))==(6,4),(first.stderr,second.stderr)


def test_the_counter_on_redis_expires(redis_url,settings):
    import redis
    in_process(redis_url,1,10)
    client=redis.Redis.from_url(redis_url)
    keys=client.keys('*two_processes*')
    assert len(keys)==1 and 0<client.ttl(keys[0])<=60
