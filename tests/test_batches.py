import io
from datetime import timedelta
from unittest.mock import Mock
import pytest
from django.core.management import call_command
from django.utils import timezone
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from apps.core.errors import DomainError
from apps.core.models import Job,UsageLedger,Quote,FileAsset
from apps.core.services import upload_file,submit_job,execute_job
from apps.commerce.services import create_invoice,sandbox_pay
from apps.studio.batches import create_batch_quote,submit_batch,execute_batch,quote_data,run_data
from apps.studio.models import BatchRun,BatchItem,BatchQuote
from tests.test_platform import account,upload,login_client

pytestmark=pytest.mark.django_db

@pytest.fixture(autouse=True)
def batch_local(settings):
    settings.DEBUG=True;settings.COMMERCE_SANDBOX_ENABLED=True

def paid(a,plan='plus'):
    inv,_=create_invoice(a,plan,'batch-plan-'+str(a.id));sandbox_pay(a,inv.id);a.refresh_from_db();return a

def groups(a,count=2):
    return [{'feature_id':'pdf.to_images','input_ids':[str(upload(a).id)],'parameters':{'dpi':72}} for _ in range(count)]

def test_quote_is_atomic_owner_scoped_and_paid_caps():
    a=account();g=groups(a)
    with pytest.raises(DomainError,match='feature_not_in_plan'):create_batch_quote(a,'batch.convert',g)
    a=paid(a)
    with pytest.raises(DomainError,match='batch_limit'):create_batch_quote(a,'batch.convert',g*3)
    other=paid(account(43));bad=[g[0],{'feature_id':'pdf.to_images','input_ids':[str(upload(other).id)]}]
    before=Quote.objects.count()
    with pytest.raises(DomainError,match='file_unavailable'):create_batch_quote(a,'batch.convert',bad)
    assert Quote.objects.count()==before and BatchQuote.objects.count()==0
    q=create_batch_quote(a,'batch.convert',g)
    data=quote_data(q)
    assert data['affordable'] and data['max_children']==5
    assert q.meters=={'file_tasks':2,'file_page_units':4,'ai_credits':0}
    assert len(data['groups'])==2 and not UsageLedger.objects.exists()

def test_submit_and_resume_are_idempotent_and_real_jobs_charge_once():
    a=paid(account());q=create_batch_quote(a,'batch.convert',groups(a))
    run,created=submit_batch(a,q.id,'batch-once-key');assert created
    run=execute_batch(run.id)
    assert run.status=='succeeded'
    assert all(i.job.artifacts.exists() for i in run.children.select_related('job'))
    repeated,is_new=submit_batch(a,q.id,'batch-once-key');assert not is_new and repeated.id==run.id
    execute_batch(run.id)
    assert Job.objects.count()==2 and UsageLedger.objects.filter(kind='consume',meter='file_tasks').count()==2
    assert run_data(run)['settled_meters']==q.meters
    with pytest.raises(DomainError,match='quote_already_submitted'):submit_batch(a,q.id,'different-batch-key')
    q2=create_batch_quote(a,'batch.convert',groups(a,1))
    with pytest.raises(DomainError,match='idempotency_conflict'):submit_batch(a,q2.id,'batch-once-key')

def test_partial_batch_only_successful_children_charge(monkeypatch):
    from processors import ProcessorError
    import processors.sandbox
    a=paid(account());g=groups(a,3);q=create_batch_quote(a,'batch.convert',g)
    failing=FileAsset.objects.get(id=g[1]['input_ids'][0]).object_key
    execute=processors.sandbox.execute_sandbox
    def one_bad(feature,paths,*args,**kwargs):
        if str(paths[0]).endswith(failing):raise ProcessorError('invalid_file','Synthetic damaged child')
        return execute(feature,paths,*args,**kwargs)
    monkeypatch.setattr(processors.sandbox,'execute_sandbox',one_bad)
    run,_=submit_batch(a,q.id,'partial-batch-key');run=execute_batch(run.id)
    assert run.status=='partial'
    assert list(run.children.values_list('status',flat=True))==['succeeded','failed','succeeded']
    assert run_data(run)['settled_meters']['file_tasks']==2
    assert UsageLedger.objects.filter(kind='consume',meter='file_tasks').count()==2
    assert not run.children.get(index=1).job.reservations.filter(settled=False).exists()
    execute_batch(run.id);assert Job.objects.count()==3

def test_worker_recovers_completed_unlinked_child_without_duplicate(settings):
    settings.LOCAL_SYNC_JOBS=False
    a=paid(account());q=create_batch_quote(a,'batch.convert',groups(a));run,_=submit_batch(a,q.id,'batch-crash-test')
    item=run.children.first()
    # Crash immediately after the authoritative child was created/settled, before parent linkage.
    job,_=submit_job(a,item.quote_id,f'batch:{run.id}:{item.index}');execute_job(job.id)
    BatchRun.objects.filter(pk=run.id).update(status='running',lease_until=timezone.now()-timedelta(seconds=1))
    call_command('runbatches',once=True);call_command('runbatches',once=True)
    run.refresh_from_db();assert run.status=='succeeded'
    assert Job.objects.count()==2 and run.children.first().job_id==job.id
    assert UsageLedger.objects.filter(kind='consume',meter='file_tasks').count()==2

def test_noop_compression_zero_charge_and_image_sets_independent_pdfs(monkeypatch):
    import processors.sandbox
    original=processors.sandbox.execute_sandbox
    def compression_noop(feature,*args,**kwargs):
        if feature=='pdf.compress':return {'no_op':True,'artifacts':[],'actual_page_units':0,'metadata':{}}
        return original(feature,*args,**kwargs)
    monkeypatch.setattr(processors.sandbox,'execute_sandbox',compression_noop)
    a=paid(account());q=create_batch_quote(a,'batch.compress',[{'input_ids':[str(upload(a).id)]}])
    run,_=submit_batch(a,q.id,'batch-compress-key');run=execute_batch(run.id)
    assert run.status=='succeeded' and run.children.get().status=='no_op'
    assert not UsageLedger.objects.filter(kind='consume').exists()
    imgs=[]
    for color in ('red','blue'):
        buf=io.BytesIO();Image.new('RGB',(50,80),color).save(buf,format='PNG')
        imgs.append(upload_file(a,SimpleUploadedFile(color+'.png',buf.getvalue())))
    q=create_batch_quote(a,'batch.image_sets',[{'input_ids':[str(i.id)]} for i in imgs])
    run,_=submit_batch(a,q.id,'batch-images-key');run=execute_batch(run.id)
    assert run.status=='succeeded' and len(run_data(run)['jobs'])==2
    assert all(i.job.artifacts.get().file.mime_type=='application/pdf' for i in run.children.select_related('job'))

def test_api_owner_expiry_aggregate_caps_immutable_confirmation(settings):
    a=paid(account());b=paid(account(43));g=groups(a)
    c=login_client(a);other=login_client(b)
    response=c.post('/api/v1/batches/quotes',{'feature_id':'batch.convert','groups':g},content_type='application/json')
    assert response.status_code==201,response.content
    q=BatchQuote.objects.get(pk=response.json()['id'])
    assert other.post('/api/v1/batches',{'quote_id':str(q.id)},content_type='application/json',HTTP_IDEMPOTENCY_KEY='cross-owner-batch').status_code==404
    settings.LOCAL_SYNC_JOBS=False
    response=c.post('/api/v1/batches',{'quote_id':str(q.id),'groups':[],'meters':{'file_tasks':0}},content_type='application/json',HTTP_IDEMPOTENCY_KEY='api-batch-confirm')
    assert response.status_code==201,response.content
    run=BatchRun.objects.get(pk=response.json()['id']);assert run.status=='queued' and run.children.count()==2 and Job.objects.count()==0
    assert other.get('/api/v1/batches/'+str(run.id)).status_code==404
    assert other.post('/api/v1/batches/'+str(run.id)+'/resume').status_code==404
    FileAsset.objects.filter(pk=g[0]['input_ids'][0]).update(size_bytes=101*1024*1024)
    with pytest.raises(DomainError,match='aggregate_size_exceeded'):create_batch_quote(a,'batch.convert',g)
    FileAsset.objects.filter(pk=g[0]['input_ids'][0]).update(size_bytes=1000,page_count=201)
    with pytest.raises(DomainError,match='page_limit_exceeded'):create_batch_quote(a,'batch.convert',g)
    BatchQuote.objects.filter(pk=q.id).update(expires_at=timezone.now()-timedelta(seconds=1))
    execute_batch(run.id);run.refresh_from_db()
    assert run.status=='partial'  # first child invalid; the independently valid second child succeeds.


def test_expired_quote_changed_plan_and_production_fail_closed(settings):
    a=paid(account());q=create_batch_quote(a,'batch.convert',groups(a,1))
    BatchQuote.objects.filter(pk=q.id).update(expires_at=timezone.now()-timedelta(seconds=1))
    with pytest.raises(DomainError,match='quote_expired'):submit_batch(a,q.id,'batch-expired-key')
    settings.DEBUG=False
    with pytest.raises(DomainError,match='feature_unavailable'):create_batch_quote(a,'batch.convert',groups(a,1))
