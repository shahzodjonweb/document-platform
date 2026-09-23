import io
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas
from apps.core.errors import DomainError
from apps.core.models import Quote,Job,UsageLedger
from apps.core.services import upload_file,storage_path
from apps.studio.models import SavedDefinition,BatchQuote,BatchRun
from apps.studio.batches import create_batch_quote,submit_batch,execute_batch,quote_data,validate_form_template
from tests.test_platform import account,login_client
from tests.test_batches import paid

pytestmark=pytest.mark.django_db

@pytest.fixture(autouse=True)
def local_forms(settings):
    settings.DEBUG=True;settings.COMMERCE_SANDBOX_ENABLED=True


def form_pdf(a,field='customer',checkbox=False,name='form.pdf',width=320):
    stream=io.BytesIO();canvas=Canvas(stream,pagesize=(400,500));canvas.drawString(40,460,'Reusable customer form')
    if checkbox:canvas.acroForm.checkbox(name=field,x=40,y=390,buttonStyle='check')
    else:canvas.acroForm.textfield(name=field,x=40,y=390,width=width,height=40,fontSize=12)
    canvas.showPage();canvas.save()
    return upload_file(a,SimpleUploadedFile(name,stream.getvalue()))


def template(a,value='Павел O‘zbekcha'):
    return SavedDefinition.objects.create(account=a,kind='form',name='Customer data',definition={'content':{'commands':[{'type':'fill_form','field':'customer','value':value}]},'output_locale':'ru'})


def form_quote(a,saved,files,version=None):
    return create_batch_quote(a,'editor.batch_forms',template_id=str(saved.id),template_version=saved.version if version is None else version,input_ids=[str(f.id) for f in files])


def test_real_form_batch_produces_one_filled_pdf_per_input_exactly_once():
    a=paid(account(),'premium');saved=template(a);files=[form_pdf(a,name=f'form-{i}.pdf') for i in range(2)]
    q=form_quote(a,saved,files);value=quote_data(q)
    assert value['template']=={'id':str(saved.id),'name':'Customer data','version':1}
    assert len(value['groups'])==2 and q.meters=={'file_tasks':2,'file_page_units':2,'ai_credits':0}
    assert all(g['feature_id']=='editor.fill_forms' for g in value['groups'])
    run,_=submit_batch(a,q.id,'two-form-batch-once');run=execute_batch(run.id)
    assert run.status=='succeeded'
    for child in run.children.select_related('job'):
        assert child.job.artifacts.count()==1
        artifact=child.job.artifacts.get();reader=PdfReader(storage_path(artifact.file.object_key))
        assert reader.get_fields()['customer']['/V']=='Павел O‘zbekcha'
        widget=reader.pages[0]['/Annots'][0].get_object();assert widget['/AP']['/N'].get_object().get_data()
    for source in files:assert PdfReader(storage_path(source.object_key)).get_fields()['customer']['/V']==''
    repeated,created=submit_batch(a,q.id,'two-form-batch-once');execute_batch(repeated.id)
    assert not created and Job.objects.count()==2
    assert UsageLedger.objects.filter(kind='consume',meter='file_tasks').count()==2

@pytest.mark.parametrize('plan',['free','plus'])
def test_batch_forms_require_premium_even_though_individual_form_filling_is_free(plan):
    a=account()
    if plan=='plus':a=paid(a,'plus')
    saved=template(a);source=form_pdf(a)
    with pytest.raises(DomainError,match='feature_not_in_plan'):form_quote(a,saved,[source])
    assert not BatchQuote.objects.exists() and not Quote.objects.exists()


def test_form_template_and_all_inputs_are_owner_scoped_and_fail_atomically():
    a=paid(account(),'premium');other=paid(account(43),'premium');saved=template(a);foreign=template(other)
    source=form_pdf(a);other_source=form_pdf(other)
    for form,files in ((foreign,[source]),(saved,[source,other_source])):
        with pytest.raises(DomainError):form_quote(a,form,files)
    assert not Quote.objects.exists() and not BatchQuote.objects.exists()
    with pytest.raises(DomainError,match='invalid_inputs'):form_quote(a,saved,[source,source])


def test_changed_template_rejects_confirmation_but_accepted_snapshot_survives_edit_and_deletion(settings):
    a=paid(account(),'premium');saved=template(a,'Original value');source=form_pdf(a)
    q=form_quote(a,saved,[source]);saved.definition['content']['commands'][0]['value']='Tampered same version';saved.save(update_fields=['definition'])
    with pytest.raises(DomainError,match='version_conflict'):submit_batch(a,q.id,'reject-changed-template')
    saved.version=2;saved.save(update_fields=['version'])
    with pytest.raises(DomainError,match='version_conflict'):form_quote(a,saved,[source],version=1)
    saved.definition['content']['commands'][0]['value']='Confirmed snapshot';saved.save(update_fields=['definition'])
    q=form_quote(a,saved,[source]);run,_=submit_batch(a,q.id,'accepted-form-snapshot')
    saved.delete();run=execute_batch(run.id)
    assert run.status=='succeeded'
    output=run.children.get().job.artifacts.get().file
    assert PdfReader(storage_path(output.object_key)).get_fields()['customer']['/V']=='Confirmed snapshot'

@pytest.mark.parametrize('content',[
    {'commands':[]},
    {'commands':[{'type':'redact','page':1,'x':0,'y':0,'width':10,'height':10}]},
    {'commands':[{'type':'fill_form','field':'customer','value':{'unexpected':'object'}}]},
    {'commands':[{'type':'fill_form','field':'customer','value':'a'},{'type':'fill_form','field':'customer','value':'b'}]},
    {'commands':[{'type':'fill_form','field':'customer','value':'hidden\x01value'}]},
])
def test_malformed_or_mixed_saved_commands_are_rejected(content):
    with pytest.raises(DomainError):validate_form_template(content)
    a=paid(account(),'premium');saved=template(a);saved.definition['content']=content;saved.save(update_fields=['definition'])
    with pytest.raises(DomainError):form_quote(a,saved,[form_pdf(a)])
    assert not Quote.objects.exists() and not BatchRun.objects.exists()


def test_null_character_is_rejected_before_json_storage():
    # PostgreSQL jsonb cannot store NUL. Exercise the public boundary instead
    # of seeding an impossible database row; other controls are tested above.
    content={'commands':[{'type':'fill_form','field':'customer','value':'hidden\x00value'}]}
    with pytest.raises(DomainError):validate_form_template(content)
    a=paid(account(),'premium')
    response=login_client(a).post('/api/v1/editor/form-templates',
        {'name':'Invalid control character','content':content},content_type='application/json')
    assert response.status_code==400
    assert not SavedDefinition.objects.exists() and not Quote.objects.exists()


def test_missing_fields_and_unqualified_control_types_rejected_before_reservation():
    a=paid(account(),'premium');saved=template(a);source=form_pdf(a)
    for bad,code in ((form_pdf(a,field='different'),'form_field_not_found'),(form_pdf(a,checkbox=True),'unsupported_form_field')):
        with pytest.raises(DomainError,match=code):form_quote(a,saved,[source,bad])
    assert not Quote.objects.exists() and not UsageLedger.objects.exists()


def test_batch_form_http_contract_ignores_client_replacement_on_submit():
    a=paid(account(),'premium');saved=template(a,'Immutable API value');source=form_pdf(a);client=login_client(a)
    response=client.post('/api/v1/batches/quotes',{'feature_id':'editor.batch_forms','template_id':str(saved.id),'template_version':1,'input_ids':[str(source.id)]},content_type='application/json')
    assert response.status_code==201,response.content
    response=client.post('/api/v1/batches',{'quote_id':response.json()['id'],'template_version':999,'commands':[{'type':'fill_form','field':'customer','value':'Client substitution'}]},content_type='application/json',HTTP_IDEMPOTENCY_KEY='http-form-batch-key')
    assert response.status_code==201,response.content
    assert response.json()['status']=='succeeded'
    output=Job.objects.get().artifacts.get().file
    assert PdfReader(storage_path(output.object_key)).get_fields()['customer']['/V']=='Immutable API value'


def test_real_field_overflow_is_partial_uncharged_failure_and_results_can_be_reused():
    a=paid(account(),'premium');saved=template(a,'A medium length customer name')
    q=form_quote(a,saved,[form_pdf(a),form_pdf(a,width=20)])
    run,_=submit_batch(a,q.id,'overflow-form-batch');run=execute_batch(run.id)
    assert run.status=='partial'
    success,failed=list(run.children.select_related('job').order_by('index'))
    assert success.status=='succeeded' and failed.error_code=='form_value_overflow'
    assert not UsageLedger.objects.filter(job=failed.job,kind='consume').exists()
    assert UsageLedger.objects.filter(kind='consume',meter='file_tasks').count()==1
    previous=success.job.artifacts.get().file
    saved.definition['content']['commands'][0]['value']='Updated result';saved.version+=1;saved.save()
    q=form_quote(a,saved,[previous]);run,_=submit_batch(a,q.id,'refill-previous-result');run=execute_batch(run.id)
    assert run.status=='succeeded'
    output=run.children.get().job.artifacts.get().file
    assert PdfReader(storage_path(output.object_key)).get_fields()['customer']['/V']=='Updated result'
