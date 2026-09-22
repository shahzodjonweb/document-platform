"""Offline vision protocol, actual input rasterization, and published layout QA."""
import base64
import io
import json
import zipfile
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from pypdf import PdfReader
from apps.core.errors import DomainError
from apps.core.models import UsageLedger
from apps.core.services import upload_file,submit_job,execute_job,storage_path,create_quote
from apps.studio import handwriting
from apps.studio.domain import create_draft,generation_quote,draft_data,update_draft
from apps.studio.rendering import render_pdf
from apps.studio.templates import style_for,published
from operations.integrations import save_config
from tests.test_platform import account,upload,login_client
from tests.test_studio import paid
pytestmark=pytest.mark.django_db

@pytest.fixture(autouse=True)
def local(settings):
    settings.DEBUG=True;settings.ENABLE_BETA_TOOLS=True;settings.COMMERCE_SANDBOX_ENABLED=True


def configure(model='gpt-4.1'):
    save_config('ai',{'mode':'openai','model':model,'api_key':'sk-offline-test'})


def source_image(a):
    raw=io.BytesIO();Image.new('RGB',(1800,1200),'white').save(raw,format='PNG')
    return upload_file(a,SimpleUploadedFile('notes.png',raw.getvalue(),'image/png'))


def mock_provider(monkeypatch,transcription=None,usage=None):
    payload={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(transcription or {'transcription':'Salom. Привет. Hello. [unclear]','uncertain_fragments':['Last word on line one.']})}]}],'usage':usage or {'input_tokens':800,'output_tokens':100}}
    captured={}
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,limit):captured['limit']=limit;return json.dumps(payload).encode()
    class Opener:
        def open(self,request,timeout):captured['request']=request;captured['calls']=captured.get('calls',0)+1;return Response()
    monkeypatch.setattr(handwriting.urllib.request,'build_opener',lambda handler:Opener())
    return captured


def test_handwriting_configuration_and_ownership_gate(settings):
    a=paid(settings,account());asset=source_image(a)
    with pytest.raises(DomainError,match='vision_provider_not_configured'):create_draft(a,{'feature_id':'study.handwriting','source_ids':[str(asset.id)]})
    assert next(f for f in login_client(a).get('/api/v1/studio/config').json()['features'] if f['id']=='study.handwriting')['requires_provider']
    configure('unknown-model')
    with pytest.raises(DomainError,match='vision_model_unqualified'):create_draft(a,{'feature_id':'study.handwriting','source_ids':[str(asset.id)]})
    configure();other=paid(settings,account(43))
    with pytest.raises(DomainError,match='file_unavailable'):create_draft(other,{'feature_id':'study.handwriting','source_ids':[str(asset.id)]})
    with pytest.raises(DomainError,match='handwriting_source_required'):create_draft(a,{'feature_id':'study.handwriting','source_ids':[str(upload(a).id)]})


@pytest.mark.parametrize('source_kind',['png','pdf'])
def test_actual_raster_input_vision_draft_uncertainty_and_once_billing(settings,monkeypatch,source_kind):
    a=paid(settings,account());configure();asset=source_image(a) if source_kind=='png' else upload(a,widths=(300,))
    captured=mock_provider(monkeypatch)
    d=create_draft(a,{'feature_id':'study.handwriting','source_ids':[str(asset.id)],'title':'My notes','output_locale':'ru'})
    assert 'request' not in captured
    quote=generation_quote(a,d.id,d.version);job,_=submit_job(a,quote.id,'handwriting-'+source_kind);job=execute_job(job.id)
    assert job.status=='succeeded',job.error_code
    assert 'handwriting_review_required' in job.warnings
    request=captured['request'];body=json.loads(request.data)
    assert request.full_url=='https://api.openai.com/v1/responses' and body['store'] is False and 'tools' not in body
    picture=body['input'][0]['content'][1]
    assert picture['detail']=='high' and picture['image_url'].startswith('data:image/jpeg;base64,')
    decoded=Image.open(io.BytesIO(base64.b64decode(picture['image_url'].split(',',1)[1])))
    assert max(decoded.size)<=1536 and captured['limit']==200_001
    text=''.join(p.extract_text() for p in PdfReader(storage_path(job.artifacts.get().file.object_key)).pages)
    assert 'Привет' in text and '[unclear]' in text
    d.refresh_from_db();data=draft_data(d)
    assert '[unclear]' in data['outline'][0]['body'] and d.version==2
    # The transcript is editable authoring content with optimistic versioning.
    updated=update_draft(a,d.id,{'version':2,'outline':[{'id':'transcription','title':'Reviewed','body':'Corrected transcription.'}]})
    assert draft_data(updated)['outline'][0]['body']=='Corrected transcription.'
    execute_job(job.id)
    assert UsageLedger.objects.filter(job=job,kind='consume',meter='ai_credits').count()==1


@pytest.mark.parametrize('transcription,usage',[
 ({'transcription':'Uncertain text','uncertain_fragments':['Unclear last word']},None),
 ({'transcription':'','uncertain_fragments':[]},None),
 ({'transcription':'x'*6001,'uncertain_fragments':[]},None),
 (None,{'input_tokens':999999,'output_tokens':10}),
])
def test_invalid_vision_response_releases_credits(settings,monkeypatch,transcription,usage):
    a=paid(settings,account());configure();asset=source_image(a);mock_provider(monkeypatch,transcription,usage)
    d=create_draft(a,{'feature_id':'study.handwriting','source_ids':[str(asset.id)]});q=generation_quote(a,d.id,1)
    job,_=submit_job(a,q.id,'invalid-transcription');job=execute_job(job.id)
    assert job.status=='failed' and job.error_code=='provider_failed'
    assert not job.artifacts.exists() and not UsageLedger.objects.filter(job=job,kind='consume').exists()


def test_image_budget_uses_model_specific_bound():
    assert handwriting.image_token_bound('gpt-4.1-2025-04-14')==1105
    assert handwriting.image_token_bound('gpt-4.1-mini')==3733
    cfg={'mode':'openai','model':'gpt-4o-mini','api_key':'test'}
    with pytest.raises(DomainError,match='generation_limit'):handwriting.enforce_input_budget(cfg,{'prompt':'Transcribe','output_locale':'en'},24000)


def test_professional_presets_require_plan_and_change_real_layout(settings,tmp_path):
    a=account()
    assert not next(t for t in published(a) if t['id']=='executive_report')['eligible']
    with pytest.raises(DomainError,match='feature_not_in_plan'):create_draft(a,{'source_text':'Example','options':{'template_id':'executive_report'}})
    a=paid(settings,a)
    content={'title':'Preset example','sections':[{'heading':'Section','body':'The same paragraph demonstrates different typography and margins.'}],'questions':[]}
    streams=[]
    for preset in ('executive_report','compact_brief','study_notes'):
        path=tmp_path/(preset+'.pdf');render_pdf(content,path,style=style_for(a,preset))
        page=PdfReader(path).pages[0];stream=page.get_contents().get_data();streams.append(stream)
        assert 'same paragraph' in page.extract_text()
        assert style_for(a,preset)['layout'].encode() not in stream # Actual drawing/metrics, no metadata-only marker.
    assert len(set(streams))==3


def test_generated_pptx_reupload_and_convert_with_strict_office_validation(settings):
    a=paid(settings,account());d=create_draft(a,{'feature_id':'ai.pptx','source_text':'O‘zbekcha. Русский. English.','options':{'length':1}})
    q=generation_quote(a,d.id,1);job,_=submit_job(a,q.id,'pptx-roundtrip');job=execute_job(job.id)
    assert job.status=='succeeded',job.error_code
    path=storage_path(job.artifacts.get().file.object_key)
    with zipfile.ZipFile(path) as package:assert not any(name.endswith('.bin') for name in package.namelist())
    asset=upload_file(a,SimpleUploadedFile('generated.pptx',path.read_bytes()))
    quote=create_quote(a,'convert.pptx_to_pdf',[str(asset.id)],{});converted,_=submit_job(a,quote.id,'generated-convert');converted=execute_job(converted.id)
    assert converted.status=='succeeded',converted.error_code
    text=''.join(p.extract_text() for p in PdfReader(storage_path(converted.artifacts.get().file.object_key)).pages)
    assert 'Русский' in text and 'English' in text



def test_reviewed_transcription_exports_exact_edits_without_provider_or_credits(settings,monkeypatch):
    from apps.studio.models import ProviderUsage
    a=paid(settings,account());configure();asset=source_image(a);captured=mock_provider(monkeypatch)
    d=create_draft(a,{'feature_id':'study.handwriting','source_ids':[str(asset.id)]})
    q=generation_quote(a,d.id,1);job,_=submit_job(a,q.id,'first-transcribe');job=execute_job(job.id)
    assert job.status=='succeeded',job.error_code
    d.refresh_from_db();value=draft_data(d)
    assert value['transcription_ready'] and not value['transcription_reviewed'] and '_transcription' not in value
    corrected='Exactly reviewed words. To‘g‘ri matn. Исправленный текст.'
    d=update_draft(a,d.id,{'version':d.version,'outline':[{'id':'transcription','title':'Reviewed notes','body':corrected}]})
    assert draft_data(d)['transcription_reviewed']
    # Export remains possible when the provider is disabled: no provider work.
    save_config('ai',{'mode':'disabled','model':'','api_key':''})
    quote=generation_quote(a,d.id,d.version)
    assert quote.parameters['stage']=='export' and not any(quote.meters.values())
    exported,_=submit_job(a,quote.id,'corrected-export');exported=execute_job(exported.id)
    assert exported.status=='succeeded',exported.error_code
    text=''.join(p.extract_text() for p in PdfReader(storage_path(exported.artifacts.get().file.object_key)).pages)
    assert corrected in text and '[unclear]' not in text and captured['calls']==1
    assert not UsageLedger.objects.filter(job=exported,kind='consume').exists()
    assert not ProviderUsage.objects.filter(job=exported).exists()
    assert exported.warnings==['handwriting_reviewed_export']
    # A different input resets provenance and requires a new charged transcription.
    configure();d.refresh_from_db();replacement=source_image(a)
    d=update_draft(a,d.id,{'version':d.version,'source_ids':[str(replacement.id)]})
    assert not draft_data(d)['transcription_ready'] and not draft_data(d)['transcription_reviewed']
    assert generation_quote(a,d.id,d.version).meters['ai_credits']>0


def test_client_cannot_forge_transcription_state_or_free_export(settings):
    a=paid(settings,account());configure();asset=source_image(a)
    base={'feature_id':'study.handwriting','source_ids':[str(asset.id)]}
    for key in ('_transcription','transcription_ready','transcription_reviewed'):
        with pytest.raises(DomainError,match='invalid_parameters'):create_draft(a,{**base,key:True})
        with pytest.raises(DomainError,match='invalid_parameters'):create_draft(a,{**base,'options':{key:True}})
    d=create_draft(a,base)
    with pytest.raises(DomainError,match='invalid_parameters'):update_draft(a,d.id,{'version':1,'transcription_reviewed':True})
    d=update_draft(a,d.id,{'version':1,'outline':[{'title':'Fake','body':'Never transcribed'}]})
    assert not draft_data(d)['transcription_reviewed']
    q=generation_quote(a,d.id,d.version);q.parameters['stage']='export';q.meters={k:0 for k in q.meters};q.save()
    with pytest.raises(DomainError,match='invalid_parameters'):submit_job(a,q.id,'forged-export')


@pytest.mark.parametrize('size',[(1,3000),(3000,1),(900,1500)])
def test_vision_raster_pads_extreme_aspect_ratio_without_cropping(tmp_path,size):
    from PIL import ImageChops
    source=tmp_path/'thin.png';Image.new('RGB',size,'black').save(source)
    raster=Image.open(io.BytesIO(handwriting.raster_source(source,'image/png')))
    assert raster.width==raster.height and raster.width<=1536
    difference=ImageChops.difference(raster,Image.new('RGB',raster.size,'white'))
    assert difference.getbbox() is not None
    center=raster.width//2
    assert min(max(raster.getpixel((x,y))) for x in range(center-1,center+1) for y in range(center-1,center+1))<250
