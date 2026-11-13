"""The new editors' switches: all off until the owner turns them on, and off means today's service."""
import json
import pytest
from operations.editor_settings import EditorSettingsError,save,validate
from operations.integrations import EDITOR_BUDGETS,EDITOR_FLAGS,editor_config,editor_flags
from operations.models import AuditLog,IntegrationConfig
from apps.core.errors import DomainError
from apps.core.models import Job
from apps.core.services import create_quote,execute_job
from tests.test_editor_documents import NOTE,opened,quote,run,save as save_draft,send
from tests.test_operations import staff_client
from tests.test_platform import account,login_client

pytestmark=pytest.mark.django_db
OFF={name:False for name in EDITOR_FLAGS}
DEFAULTS={'inspect':120,'text_check':90,'preview':120,'render_deck':300,'photos':600,'paid_multiplier':3}


def studio_limits(client):
    return client.get('/api/v1/studio/config').json()['limits']


def test_everything_is_off_and_the_budgets_are_the_plans_by_default():
    assert editor_flags()==OFF and EDITOR_BUDGETS==DEFAULTS
    assert editor_config()=={**OFF,**DEFAULTS}


def test_editor_v2_off_leaves_everything_as_today(settings):
    settings.DEBUG=True;settings.ENABLE_BETA_TOOLS=True;settings.LOCAL_SYNC_JOBS=True
    a=account();client=login_client(a)
    limits=studio_limits(client)
    assert limits.pop('editor')==OFF
    assert limits.keys()=={'sections','slides','questions','source_chars'},'what the web reads today is unchanged'
    # The whole road the deployed web takes: open, save, quote, run.
    a,asset,client,url=opened(a)
    assert save_draft(client,url,1,[NOTE]).status_code==200
    job=run(client,quote(client,url,2),'editor-flags-off-1')
    assert job.status=='succeeded' and job.feature_id=='editor.visual'


def test_the_generic_route_refuses_an_inline_editor_quote_once_editor_v2_is_on(settings):
    settings.DEBUG=True;settings.ENABLE_BETA_TOOLS=True;settings.LOCAL_SYNC_JOBS=True
    a,asset,client,url=opened()
    inline={'feature_id':'editor.visual','input_ids':[str(asset.id)],'parameters':{'commands':[NOTE]}}
    assert client.post('/api/v1/quotes',inline,content_type='application/json').status_code==201
    save({'editor_v2':'true'})
    answer=client.post('/api/v1/quotes',inline,content_type='application/json')
    assert answer.status_code==409 and answer.json()['error']['code']=='feature_unavailable'
    assert client.post('/api/v1/quotes',{'feature_id':'pdf.rotate','input_ids':[str(asset.id)]},content_type='application/json').status_code==201
    assert create_quote(a,'editor.visual',[str(asset.id)],{'commands':[NOTE]}),'batches of forms call it themselves'
    assert save_draft(client,url,1,[NOTE]).status_code==200
    assert client.post(url+'/quote',{'version':2,'deliver':'chat'},content_type='application/json').status_code==201,'a pointer is the way in'


EDIT={'type':'edit_text','page':1,'x':1,'y':1,'width':9,'height':9,'original':'Eski','text':'Yangi'}


def test_text_edit_off_refuses_a_change_to_the_documents_words_at_the_quote_naming_it(settings):
    settings.DEBUG=True;settings.ENABLE_BETA_TOOLS=True;settings.LOCAL_SYNC_JOBS=True
    a,asset,client,url=opened()
    assert save_draft(client,url,1,[NOTE,EDIT]).status_code==200,'a save never waits for the switch'
    answer=quote(client,url,2)
    assert answer.status_code==409 and answer.json()['error']['code']=='editor_text_edit_unavailable' and answer.json()['error']['message_params']=={'index':1}
    answer=send(client,url,2)
    assert answer.status_code==409 and answer.json()['error']['message_params']=={'index':1}
    with pytest.raises(DomainError) as caught:create_quote(a,'editor.visual',[str(asset.id)],{'commands':[EDIT]})
    assert caught.value.code=='editor_text_edit_unavailable' and caught.value.params=={'index':0}


def test_text_edit_on_quotes_and_runs_and_off_again_fails_the_waiting_job_naming_the_change(settings):
    settings.DEBUG=True;settings.ENABLE_BETA_TOOLS=True;settings.LOCAL_SYNC_JOBS=True
    save({'text_edit':'true'})
    a,asset,client,url=opened()
    assert save_draft(client,url,1,[NOTE,EDIT]).status_code==200
    job=run(client,send(client,url,2),'editor-text-edit-on')
    assert job.status=='succeeded' and client.get(f'/api/v1/jobs/{job.id}').json()['per_command'][1]=={'index':1,'status':'applied','engine':'covered'}
    # Quoted while on, run after it was turned off: the job fails whole and says which change.
    assert save_draft(client,url,2,[EDIT,NOTE]).status_code==200
    quoted=send(client,url,3)
    assert quoted.status_code==201,quoted.content
    settings.LOCAL_SYNC_JOBS=False
    pending=client.post('/api/v1/jobs',{'quote_id':quoted.json()['id']},content_type='application/json',HTTP_IDEMPOTENCY_KEY='editor-text-edit-off')
    save({'text_edit':'false'})
    failed=execute_job(pending.json()['id'])
    assert failed.status=='failed' and failed.error_code=='editor_text_edit_unavailable'
    assert client.get(f'/api/v1/jobs/{failed.id}').json()['error']['message_params']=={'index':0}


def test_a_job_that_carries_its_own_changes_waits_for_text_edit_when_it_runs_too(settings):
    settings.DEBUG=True;settings.ENABLE_BETA_TOOLS=True;settings.LOCAL_SYNC_JOBS=False
    save({'text_edit':'true'})
    a,asset,client,url=opened()
    assert save_draft(client,url,1,[NOTE,EDIT]).status_code==200
    # Today's web: a quote with no `deliver` puts the changes in the job itself, with no stored draft to point at.
    quoted=quote(client,url,2)
    assert quoted.status_code==201,quoted.content
    pending=client.post('/api/v1/jobs',{'quote_id':quoted.json()['id']},content_type='application/json',HTTP_IDEMPOTENCY_KEY='editor-inline-text-edit')
    assert pending.status_code==201 and 'editor_document_id' not in Job.objects.get(pk=pending.json()['id']).parameters
    save({'text_edit':'false'})
    failed=execute_job(pending.json()['id'])
    assert failed.status=='failed' and failed.error_code=='editor_text_edit_unavailable'


def test_the_pdfcraft_switch_reaches_the_processor_and_nothing_else_does(settings,monkeypatch):
    settings.DEBUG=True;settings.ENABLE_BETA_TOOLS=True;settings.LOCAL_SYNC_JOBS=True
    from processors import sandbox
    seen=[];real=sandbox.execute_sandbox
    monkeypatch.setattr(sandbox,'execute_sandbox',lambda *args,**kwargs:seen.append(kwargs['pdfcraft']) or real(*args,**kwargs))
    a,asset,client,url=opened()
    assert save_draft(client,url,1,[NOTE]).status_code==200
    assert run(client,quote(client,url,2),'editor-pdfcraft-off').status=='succeeded'
    save({'pdfcraft':'true'})
    assert save_draft(client,url,2,[NOTE,NOTE]).status_code==200
    assert run(client,quote(client,url,3),'editor-pdfcraft-on').status=='succeeded'
    assert run(client,client.post('/api/v1/quotes',{'feature_id':'pdf.rotate','input_ids':[str(asset.id)]},content_type='application/json'),'pdf-rotate-pdfcraft').status=='succeeded'
    assert seen==[False,True,False],'only an editor job is told, and only what the switch says'


def test_the_environment_answers_until_something_is_saved(monkeypatch):
    monkeypatch.setenv('EDITOR_FLAG_TEXT_EDIT','1');monkeypatch.setenv('EDITOR_BUDGET_PREVIEW','200');monkeypatch.setenv('EDITOR_BUDGET_INSPECT','many')
    config=editor_config()
    assert config['text_edit'] is True and config['editor_v2'] is False and config['preview']==200 and config['inspect']==120,'a figure that is no number is no setting'
    save({'text_edit':'false','preview':'50'})
    config=editor_config()
    assert config['text_edit'] is False and config['preview']==50


def test_what_is_saved_shows_in_the_studio_config():
    client=login_client(account())
    save({'editor_v2':'true','edit_buttons':'true'})
    assert studio_limits(client)['editor']=={**OFF,'editor_v2':True,'edit_buttons':True}


@pytest.mark.parametrize('values',[{'editor_v3':'true'},{'editor_v2':'maybe'},{'inspect':'x'},{'inspect':'-1'},{'inspect':'86401'},{'paid_multiplier':'0'},{'paid_multiplier':'21'},{}])
def test_only_known_names_and_sane_values_are_kept(values):
    with pytest.raises(EditorSettingsError):validate(values)
    assert not IntegrationConfig.objects.filter(pk='editor').exists() or values


def test_the_form_saves_audits_and_shows_it():
    client,user=staff_client('Operations')
    page=client.get('/ops/editor')
    assert page.status_code==200 and b'name="editor_v2"' in page.content and b'name="render_deck"' in page.content and b'value="300"' in page.content
    form={**{name:'false' for name in EDITOR_FLAGS},**{name:str(value) for name,value in DEFAULTS.items()},'editor_v2':'true','inspect':'200'}
    saved=client.post('/ops/editor/settings',form)
    assert saved.status_code==302 and saved['Location']=='/ops/editor?saved=1'
    config=editor_config()
    assert config['editor_v2'] is True and config['inspect']==200 and config['pdfcraft'] is False
    row=AuditLog.objects.get(action='editor.settings')
    assert row.actor==user and row.before=={'editor_v2':False,'inspect':120} and row.after=={'editor_v2':True,'inspect':200}
    # Unchanged, it leaves no audit row.
    client.post('/ops/editor/settings',{**form})
    assert AuditLog.objects.filter(action='editor.settings').count()==1
    shown=client.get('/ops/editor?saved=1').content.decode()
    assert 'name="editor_v2" value="true" checked' in shown and 'value="200"' in shown


def test_a_bad_form_is_refused_with_nothing_saved():
    client,_=staff_client('Operations')
    assert client.post('/ops/editor/settings',{'editor_v2':'true','inspect':'nope'}).status_code==400
    assert client.post('/ops/editor/settings',{'somebody_elses':'true'}).status_code==400
    assert editor_flags()==OFF and not AuditLog.objects.filter(action='editor.settings').exists()


def test_only_operations_may_change_it():
    client,_=staff_client('Analyst')
    assert client.get('/ops/editor').status_code==403
    assert client.post('/ops/editor/settings',{'editor_v2':'true'}).status_code==403
    assert editor_flags()==OFF


def test_a_customer_cannot_reach_the_form():
    client=login_client(account())
    assert client.post('/ops/editor/settings',{'editor_v2':'true'}).status_code in (302,401,403)
    assert editor_flags()==OFF


@pytest.mark.parametrize('lang',['en','uz','ru'])
def test_the_page_is_in_every_language(lang):
    client,_=staff_client('Operations')
    from operations.i18n import CATALOGS
    page=client.get(f'/ops/editor?lang={lang}')
    assert page.status_code==200
    for label in ('editor_desc','editor_flag_editor_v2','editor_budget_render_deck','save_changes'):
        assert CATALOGS[lang][label] in page.content.decode(),label


def test_the_flags_stay_out_of_a_stored_secret():
    save({'editor_v2':'true'})
    row=IntegrationConfig.objects.get(pk='editor')
    assert json.dumps(row.configuration) and row.configuration['editor_v2'] is True and not row.encrypted_secrets
