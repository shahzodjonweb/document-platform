import hashlib
import hmac
import io
import json
import time
import uuid
from datetime import timedelta
from urllib.parse import urlencode
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone
from pypdf import PdfReader,PdfWriter
from apps.core.errors import DomainError
from apps.core.identity import resolve_account,validate_init_data,exchange_miniapp,create_challenge,approve_challenge,exchange_challenge
from apps.core.models import Account,UsageGrant,Job,UsageLedger,FileAsset,OutboxEvent,Artifact,Quote
from apps.core.policy import usage_snapshot
from apps.core.services import upload_file,create_quote,submit_job,execute_job,settle_job,cleanup_expired,storage_path

pytestmark=pytest.mark.django_db

def pdf_bytes(widths=(200,300)):
    output=io.BytesIO();writer=PdfWriter()
    for width in widths: writer.add_blank_page(width=width,height=400)
    writer.write(output)
    return output.getvalue()

def account(uid=42): return resolve_account({'id':uid,'first_name':'Test','language_code':'en'},is_test=True)
def upload(a,name='input.pdf',widths=(200,300)):
    return upload_file(a,SimpleUploadedFile(name,pdf_bytes(widths),'application/pdf'))
def quote(a,asset,feature='pdf.rotate',parameters=None): return create_quote(a,feature,[str(asset.id)],parameters or {})
def signed_init(token,user=None,age=0):
    data={'auth_date':str(int(time.time())-age),'query_id':'test-query','user':json.dumps(user or {'id':42,'first_name':'Test'},separators=(',',':'))}
    check='\n'.join(f'{key}={value}' for key,value in sorted(data.items()))
    key=hmac.new(b'WebAppData',token.encode(),hashlib.sha256).digest()
    data['hash']=hmac.new(key,check.encode(),hashlib.sha256).hexdigest()
    return urlencode(data)

def login_client(a,csrf=False):
    client=Client(enforce_csrf_checks=csrf)
    session=client.session;session['customer_account_id']=str(a.id);session.save()
    return client

def test_real_merge_end_to_end_idempotency_and_meters():
    a=account();first=upload(a,widths=(210,));second=upload(a,name='Второй.pdf',widths=(310,410))
    q=create_quote(a,'pdf.merge',[str(first.id),str(second.id)],{})
    job,created=submit_job(a,q.id,'meaningful-request-1')
    assert created and usage_snapshot(a)['meters']['file_tasks']['reserved']==1
    same,created=submit_job(a,q.id,'meaningful-request-1')
    assert same.id==job.id and not created
    done=execute_job(job.id)
    assert done.status=='succeeded',done.error_code
    result=done.artifacts.get().file
    reader=PdfReader(storage_path(result.object_key))
    assert [float(p.mediabox.width) for p in reader.pages]==[210,310,410]
    execute_job(job.id);settle_job(job.id,'succeeded',actual=job.meters)
    assert UsageLedger.objects.filter(job=job,kind='consume',meter='file_tasks').count()==1
    assert usage_snapshot(a)['meters']['file_tasks']['used']==1
    assert usage_snapshot(a)['meters']['file_page_units']['used']==3
    assert OutboxEvent.objects.get(job=job).delivered_at

def test_owner_isolation_for_assets_quotes_jobs_and_artifacts():
    owner=account();other=account(43);asset=upload(owner);q=quote(owner,asset)
    with pytest.raises(DomainError,match='file_unavailable'): create_quote(other,'pdf.rotate',[str(asset.id)],{})
    with pytest.raises(DomainError,match='not_found'): submit_job(other,q.id,'other-request-key')
    job,_=submit_job(owner,q.id,'owner-request-key');execute_job(job.id)
    client=login_client(other)
    for path in (f'files/{asset.id}',f'files/{asset.id}/download',f'jobs/{job.id}',f'artifacts/{job.artifacts.get().id}/download'):
        assert client.get(f'/api/v1/{path}').status_code==404,path
    assert client.get('/api/v1/jobs').json()['results']==[]

def test_failure_releases_original_grants():
    a=account();asset=upload(a);q=quote(a,asset);job,_=submit_job(a,q.id,'failure-request-key')
    storage_path(asset.object_key).unlink()
    done=execute_job(job.id)
    assert done.status=='failed'
    assert usage_snapshot(a)['meters']['file_tasks']=={'limit':300,'used':0,'reserved':0,'remaining':300}
    settle_job(job.id,'failed',error_code='again')
    assert UsageLedger.objects.filter(job=job,kind='release',meter='file_tasks').count()==1

def test_daily_boundary_and_purchased_task_exception():
    from apps.core.policy import plan_limits
    a=account();asset=upload(a);cap=plan_limits(a)['daily_file_tasks']
    for i in range(cap):
        q=quote(a,asset);job,_=submit_job(a,q.id,f'daily-request-{i}');execute_job(job.id)
    q=quote(a,asset)
    with pytest.raises(DomainError,match='quota_exceeded'): submit_job(a,q.id,'daily-over-limit')
    UsageGrant.objects.create(account=a,meter='file_tasks',source='purchased',source_id='test-pack-task',quantity=1,valid_from=timezone.now())
    UsageGrant.objects.create(account=a,meter='file_page_units',source='purchased',source_id='test-pack-page',quantity=10,valid_from=timezone.now())
    job,_=submit_job(a,q.id,'daily-purchased');execute_job(job.id)
    assert usage_snapshot(a)['daily']['used']==cap
    assert UsageLedger.objects.filter(job=job,meter='file_tasks',kind='consume').get().grant.source=='purchased'

def test_quota_and_concurrency_do_not_overspend():
    a=account();asset=upload(a);usage_snapshot(a)
    UsageGrant.objects.filter(account=a,meter='file_tasks').update(quantity=1)
    q=quote(a,asset);job,_=submit_job(a,q.id,'quota-request-1')
    q2=quote(a,asset)
    with pytest.raises(DomainError,match='concurrency_limit'): submit_job(a,q2.id,'quota-request-2')
    execute_job(job.id)
    with pytest.raises(DomainError,match='quota_exceeded'): submit_job(a,q2.id,'quota-request-2')
    grant=UsageGrant.objects.get(account=a,meter='file_tasks')
    assert grant.quantity==grant.consumed==1 and grant.reserved==0

def test_duplicate_quote_and_changed_idempotency_conflict():
    a=account();asset=upload(a);q=quote(a,asset);submit_job(a,q.id,'same-request-key')
    with pytest.raises(DomainError,match='quote_already_submitted'): submit_job(a,q.id,'different-request-key')
    q2=quote(a,asset)
    with pytest.raises(DomainError,match='idempotency_conflict'): submit_job(a,q2.id,'same-request-key')

def test_stale_quote_and_changed_file_fail():
    a=account();asset=upload(a);q=quote(a,asset)
    q.expires_at=timezone.now()-timedelta(seconds=1);q.save()
    with pytest.raises(DomainError,match='quote_expired'): submit_job(a,q.id,'expired-quote-key')
    q=quote(a,asset);asset.sha256='0'*64;asset.save()
    with pytest.raises(DomainError,match='file_changed'): submit_job(a,q.id,'changed-file-key')

def test_charge_cannot_exceed_confirmed_quote():
    a=account();asset=upload(a);q=quote(a,asset);job,_=submit_job(a,q.id,'quote-upper-bound')
    with pytest.raises(DomainError,match='quote_exceeded'): settle_job(job.id,'succeeded',actual={'file_tasks':2})
    assert usage_snapshot(a)['meters']['file_tasks']['reserved']==1

def test_retention_revokes_before_download_and_deletes():
    a=account();asset=upload(a);q=quote(a,asset);job,_=submit_job(a,q.id,'retention-request');execute_job(job.id)
    FileAsset.objects.filter(account=a).update(expires_at=timezone.now()-timedelta(seconds=1))
    client=login_client(a)
    assert client.get(f'/api/v1/artifacts/{job.artifacts.get().id}/download').status_code==410
    assert cleanup_expired()==2
    assert not storage_path(asset.object_key).exists()
    assert Job.objects.get(pk=job.id).status=='succeeded'

def test_miniapp_tamper_stale_future_duplicate_and_canonical(settings):
    settings.TELEGRAM_BOT_TOKEN='123:secure-test-token'
    raw=signed_init(settings.TELEGRAM_BOT_TOKEN)
    a=exchange_miniapp(raw)
    assert resolve_account({'id':42,'first_name':'Changed'},'bot').id==a.id
    assert Account.objects.count()==1
    for value in (raw.replace('Test','Other'),signed_init(settings.TELEGRAM_BOT_TOKEN,age=301),signed_init(settings.TELEGRAM_BOT_TOKEN,age=-31),raw+'&user=bad'):
        with pytest.raises(DomainError,match='invalid_telegram_data'): validate_init_data(value)
    with pytest.raises(DomainError,match='auth_replayed'): exchange_miniapp(raw)

def test_browser_challenge_bound_and_one_use(settings):
    settings.TELEGRAM_BOT_USERNAME='testbot'
    challenge,token,verifier=create_challenge('Test browser')
    approve_challenge(token,{'id':42,'first_name':'Test'})
    with pytest.raises(DomainError,match='not_found'): exchange_challenge(challenge.id,'wrong-browser')
    assert exchange_challenge(challenge.id,verifier).telegram_user_id==42
    with pytest.raises(DomainError,match='auth_replayed'): exchange_challenge(challenge.id,verifier)

def test_csrf_and_customer_cannot_grant_staff_or_plan(settings):
    settings.DEVELOPMENT_LOGIN_ENABLED=True;settings.DEBUG=True
    client=Client(enforce_csrf_checks=True)
    assert client.post('/api/v1/auth/dev-login',{},content_type='application/json').status_code==403
    token=client.get('/api/v1/auth/session').json()['csrf_token']
    response=client.post('/api/v1/auth/dev-login',{},content_type='application/json',HTTP_X_CSRFTOKEN=token)
    assert response.status_code==200,response.content
    token=response.json()['csrf_token']
    for values in ({'is_staff':True},{'plan':'premium'},{'telegram_user_id':42}):
        response=client.patch('/api/v1/me',values,content_type='application/json',HTTP_X_CSRFTOKEN=token)
        assert response.status_code==400
    assert client.get('/api/v1/me').json()['plan']=='free'
    assert '_auth_user_id' not in client.session

def test_dev_login_and_features_fail_closed(settings):
    settings.DEBUG=False;settings.DEVELOPMENT_LOGIN_ENABLED=False;settings.ENABLE_BETA_TOOLS=False
    client=Client()
    assert client.post('/api/v1/auth/dev-login',{},content_type='application/json').status_code==404
    assert client.get('/api/v1/catalog').json()['features']==[]
    assert client.get('/api/v1/plans').json()['checkout_enabled'] is False

def test_bad_pages_unsafe_parameters_and_invalid_files_rejected():
    a=account();asset=upload(a)
    for params in ({'pages':'1-9000'},{'pages':'0'},{'pages':'1,1'},{'pages':'all','password':'secret'}):
        with pytest.raises(DomainError): create_quote(a,'pdf.extract_pages',[str(asset.id)],params)
    for value in (b'not a PDF',b'%PDF-1.7\nmalformed'):
        with pytest.raises(DomainError): upload_file(a,SimpleUploadedFile('../../evil.pdf',value))
    assert UsageLedger.objects.count()==0

def test_localized_errors_have_identical_codes():
    from apps.core.errors import error_data
    for locale in ('en','uz','ru'):
        data=error_data(DomainError('quota_exceeded'),locale)
        assert data['code']=='quota_exceeded' and data['message_key']=='errors.quota_exceeded'
        assert data['message']

def test_contacts_are_public_tickets_are_gone_and_paid_checkout_disabled():
    from operations.integrations import save_config
    a=account();client=login_client(a)
    assert client.post('/api/v1/support',{'subject':'Help','message':'A task failed.'},content_type='application/json').status_code==404
    assert Client().get('/api/v1/contacts').json()=={'support':{'username':'','url':''},'ads':{'username':'','url':''}}
    save_config('contacts',{'support':'@pdfmaster_help','ads':'https://t.me/pdfmaster_ads'})
    assert Client().get('/api/v1/contacts').json()=={'support':{'username':'pdfmaster_help','url':'https://t.me/pdfmaster_help'},
                                                   'ads':{'username':'pdfmaster_ads','url':'https://t.me/pdfmaster_ads'}}
    response=client.post('/api/v1/billing/invoices',{'plan':'premium','price_xtr':1},content_type='application/json')
    assert response.status_code==409 and response.json()['error']['code']=='checkout_disabled'

def test_webhook_secret_and_update_deduplication(settings):
    from apps.core.models import WebhookReceipt
    settings.TELEGRAM_WEBHOOK_SECRET='secret-header'
    client=Client(enforce_csrf_checks=True)
    data={'update_id':999,'message':{'text':'hi'}}
    assert client.post('/api/v1/webhooks/telegram',data,content_type='application/json').status_code==401
    for _ in range(2): assert client.post('/api/v1/webhooks/telegram',data,content_type='application/json',HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='secret-header').status_code==200
    assert WebhookReceipt.objects.count()==1

def test_password_handles_roundtrip_and_no_plaintext_persistence():
    from apps.core.secrets import create_secret
    from apps.core.models import SecretHandle
    a=account();asset=upload(a);password='test-pässw0rd-42'
    handle=create_secret(a,password)
    assert password.encode() not in bytes(handle.ciphertext)
    q=create_quote(a,'pdf.protect',[str(asset.id)],{},handle.id)
    job,_=submit_job(a,q.id,'protect-secret-key');job=execute_job(job.id)
    assert job.status=='succeeded',job.error_code
    assert SecretHandle.objects.filter(pk=handle.id).count()==0
    assert password not in json.dumps(job.parameters) and password not in json.dumps(q.parameters)
    encrypted=storage_path(job.artifacts.get().file.object_key).read_bytes()
    locked=PdfReader(io.BytesIO(encrypted));assert locked.is_encrypted
    assert locked.decrypt(password)
    asset2=upload_file(a,SimpleUploadedFile('locked.pdf',encrypted),password=password)
    q2=create_quote(a,'pdf.unlock_known',[str(asset2.id)],{})
    job2,_=submit_job(a,q2.id,'unlock-secret-key');job2=execute_job(job2.id)
    assert job2.status=='succeeded',job2.error_code
    assert not PdfReader(storage_path(job2.artifacts.get().file.object_key)).is_encrypted
    assert SecretHandle.objects.count()==0

def test_password_handle_owner_expiry_and_wrong_password():
    from apps.core.secrets import create_secret
    from apps.core.models import SecretHandle
    a=account();b=account(44);asset=upload(a);handle=create_secret(b,'other-owner-password')
    with pytest.raises(DomainError,match='password_expired'): create_quote(a,'pdf.protect',[str(asset.id)],{},handle.id)
    handle=create_secret(a,'expires')
    SecretHandle.objects.filter(pk=handle.id).update(expires_at=timezone.now()-timedelta(seconds=1))
    with pytest.raises(DomainError,match='password_expired'): create_quote(a,'pdf.protect',[str(asset.id)],{},handle.id)

def test_split_overlapping_output_quoted_and_charged_accurately():
    a=account();asset=upload(a)
    q=create_quote(a,'pdf.split',[str(asset.id)],{'ranges':['1-2','1-2']})
    assert q.meters['file_page_units']==4
    job,_=submit_job(a,q.id,'split-overlap-key');job=execute_job(job.id)
    assert job.status=='succeeded'
    assert usage_snapshot(a)['meters']['file_page_units']['used']==4

def test_bot_transport_registration_and_locale_parity():
    from telegram.bot import build_dispatcher,COPY,TOOL_NAMES
    dispatcher=build_dispatcher()
    assert len(dispatcher.message.handlers)>=10
    assert set(COPY['en'])==set(COPY['uz'])==set(COPY['ru'])
    assert all(set(translations)=={'en','uz','ru'} for translations in TOOL_NAMES.values())
