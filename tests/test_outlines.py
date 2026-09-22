import json
import pytest
from apps.core.errors import DomainError
from apps.core.models import UsageLedger
from apps.core.services import submit_job,execute_job,storage_path
from apps.studio.domain import create_draft,draft_data,generation_quote
from apps.studio.outlines import create_outline_quote
from apps.studio import provider
from operations.integrations import save_config
from tests.test_platform import account,login_client
from tests.test_studio import paid

pytestmark=pytest.mark.django_db

@pytest.fixture(autouse=True)
def local(settings):
    settings.DEBUG=True;settings.COMMERCE_SANDBOX_ENABLED=True;settings.ENABLE_BETA_TOOLS=True


def test_local_outline_stage_creates_real_outline_and_updates_draft_without_ai_cost():
    a=account();d=create_draft(a,{'source_text':'A supplied paragraph about safe document processing.','options':{'length':1}})
    q=create_outline_quote(a,d.id,1);assert q.meters['ai_credits']==0 and q.parameters['stage']=='outline'
    job,_=submit_job(a,q.id,'outline-local');job=execute_job(job.id);assert job.status=='succeeded',job.error_code
    result=json.loads(storage_path(job.artifacts.get().file.object_key).read_text())
    assert result['sections'][0]['body']=='A supplied paragraph about safe document processing.'
    d.refresh_from_db();assert d.version==2 and draft_data(d)['content']['sections']==result['sections']
    assert not UsageLedger.objects.filter(job=job,kind='consume').exists()
    # The reviewed outline can proceed to ordinary full export with a new quote.
    full=generation_quote(a,d.id,d.version);assert full.parameters.get('stage') is None


def test_live_outline_separate_cost_source_integrity_and_version(settings,monkeypatch):
    a=paid(settings,account());save_config('ai',{'mode':'openai','model':'test-model','api_key':'sk-offline-test'})
    d=create_draft(a,{'source_text':'Safe processing','options':{'length':1,'question_count':0}})
    raw={'title':'Outline','answer_supported':True,'citations':[],'sections':[{'id':'s1','heading':'Introduction','body':'Cover safe document processing.','notes':''}],'questions':[]}
    calls=[]
    def generated(*args,**kwargs):calls.append(args[2]);return raw,{'input_tokens':1000,'output_tokens':100}
    monkeypatch.setattr(provider,'generate',generated)
    q=create_outline_quote(a,d.id,1);assert q.meters['ai_credits']==2
    job,_=submit_job(a,q.id,'outline-paid');job=execute_job(job.id);assert job.status=='succeeded',job.error_code
    assert calls==['ai.outline'] and sum(UsageLedger.objects.filter(job=job,kind='consume').values_list('amount',flat=True))==2
    d.refresh_from_db();assert draft_data(d)['content']['sections'][0]['heading']=='Introduction'
    execute_job(job.id);assert calls==['ai.outline']


def test_outline_stage_api_and_oversized_output_release(settings,monkeypatch):
    a=paid(settings,account());save_config('ai',{'mode':'openai','model':'test-model','api_key':'sk-offline-test'})
    d=create_draft(a,{'source_text':'Topic','options':{'length':1}});client=login_client(a)
    q=client.post(f'/api/v1/generation/drafts/{d.id}/quote',{'version':1,'stage':'outline'},content_type='application/json')
    assert q.status_code==201 and next(m['amount'] for m in q.json()['meters'] if m['meter']=='ai_credits')==2
    raw={'title':'Overrun','sections':[{'id':'s1','heading':'Intro','body':'x'*501,'notes':''}],'questions':[]}
    monkeypatch.setattr(provider,'generate',lambda *args,**kwargs:(raw,{'input_tokens':100,'output_tokens':100}))
    job,_=submit_job(a,q.json()['id'],'outline-overrun');job=execute_job(job.id)
    assert job.status=='failed' and not job.artifacts.exists() and not UsageLedger.objects.filter(job=job,kind='consume').exists()
    assert client.post(f'/api/v1/generation/drafts/{d.id}/quote',{'version':1,'stage':'unknown'},content_type='application/json').status_code==400


@pytest.mark.parametrize('section_ids',[['unconfirmed'],['s2','s1'],['s1']])
def test_outline_cannot_replace_or_drop_confirmed_section_identity(settings,monkeypatch,section_ids):
    a=paid(settings,account());save_config('ai',{'mode':'openai','model':'test-model','api_key':'offline-fixture'})
    d=create_draft(a,{'source_text':'First\n\nSecond','options':{'length':2}})
    before=draft_data(d)['content']
    raw={'title':'Outline','sections':[{'id':identifier,'heading':'Outline','body':'Summary','notes':''} for identifier in section_ids],'questions':[],'citations':[]}
    monkeypatch.setattr(provider,'generate',lambda *args,**kwargs:(raw,{'input_tokens':100,'output_tokens':100}))
    quote=create_outline_quote(a,d.id,d.version)
    job,_=submit_job(a,quote.id,'outline-identity');done=execute_job(job.id)
    assert done.status=='failed' and done.error_code=='invalid_parameters'
    d.refresh_from_db();assert d.version==1 and draft_data(d)['content']==before
    assert not done.artifacts.exists() and not UsageLedger.objects.filter(job=job,kind='consume').exists()


def test_outline_quote_is_owner_version_and_expiry_bound(settings):
    from datetime import timedelta
    from django.utils import timezone
    a=paid(settings,account());other=paid(settings,account(43))
    d=create_draft(a,{'source_text':'Private draft','options':{'length':1}})
    with pytest.raises(DomainError,match='not_found'):create_outline_quote(other,d.id,d.version)
    with pytest.raises(DomainError,match='version_conflict'):create_outline_quote(a,d.id,d.version+1)
    d.expires_at=timezone.now()-timedelta(seconds=1);d.save(update_fields=['expires_at'])
    with pytest.raises(DomainError,match='not_found'):create_outline_quote(a,d.id,d.version)
