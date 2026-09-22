"""No network: exercise the actual image protocol, decoded artifacts and billing."""
import base64
import io
import json
import pytest
from PIL import Image
from apps.core.errors import DomainError
from apps.core.models import UsageLedger
from apps.core.services import submit_job,execute_job,storage_path
from apps.studio import illustrations
from apps.studio.domain import create_draft,generation_quote
from operations.integrations import save_config
from tests.test_platform import account
from tests.test_studio import paid

pytestmark=pytest.mark.django_db

@pytest.fixture(autouse=True)
def local(settings):
    settings.DEBUG=True;settings.ENABLE_BETA_TOOLS=True;settings.COMMERCE_SANDBOX_ENABLED=True


def configure():
    save_config('ai',{'mode':'openai','model':'test-text-model','image_model':'test-image-model','api_key':'sk-offline-test-key'})


def image_response(size=(1024,1024)):
    raw=io.BytesIO();Image.new('RGB',size,'#36ac92').save(raw,format='PNG')
    return {'data':[{'b64_json':base64.b64encode(raw.getvalue()).decode()}],'usage':{'input_tokens':30,'output_tokens':80}}


def mock_image(monkeypatch,payload):
    captured={}
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,limit):captured['read_limit']=limit;return json.dumps(payload).encode()
    class Opener:
        def open(self,req,timeout):captured.update(request=req,timeout=timeout);return Response()
    monkeypatch.setattr(illustrations.urllib.request,'build_opener',lambda handler:Opener())
    return captured


def test_image_provider_fixed_endpoint_boundaries_and_native_png(monkeypatch):
    captured=mock_image(monkeypatch,image_response())
    cfg={'mode':'openai','model':'text-model','image_model':'image-model','api_key':'never-return-this'}
    raw,usage=illustrations.generate_image(cfg,'Simple science illustration','test-key')
    assert Image.open(io.BytesIO(raw)).size==(1024,1024) and usage['output_tokens']==80
    request=captured['request'];body=json.loads(request.data)
    assert request.full_url=='https://api.openai.com/v1/images/generations'
    assert body=={'model':'image-model','prompt':'Simple science illustration','n':1,'size':'1024x1024','quality':'low','output_format':'png'}
    assert captured['read_limit']==12_000_001 and captured['timeout']==120


@pytest.mark.parametrize('payload',[{'data':[{'url':'https://untrusted.invalid/image.png'}]},image_response((2048,1024)),{'data':[{'b64_json':'bad encoding'}]},{'data':[{'b64_json':'eA=='}]}])
def test_image_provider_rejects_url_wrong_size_invalid_bytes(monkeypatch,payload):
    mock_image(monkeypatch,payload)
    with pytest.raises(DomainError,match='provider_failed'):
        illustrations.generate_image({'mode':'openai','image_model':'model','api_key':'key'},'Illustration','id')


def test_image_draft_requires_live_config_and_premium(settings):
    with pytest.raises(DomainError,match='feature_not_in_plan'):create_draft(account(),{'feature_id':'ai.images','prompt':'Illustration'})
    a=paid(settings,account(43))
    with pytest.raises(DomainError,match='image_provider_not_configured'):create_draft(a,{'feature_id':'ai.images','prompt':'Illustration'})


def test_image_generation_confirmed_quote_png_and_exactly_once_charge(settings,monkeypatch):
    a=paid(settings,account());configure();mock_image(monkeypatch,image_response())
    draft=create_draft(a,{'feature_id':'ai.images','prompt':'A simple science diagram','output_format':'png'})
    quote=generation_quote(a,draft.id,draft.version)
    assert quote.meters=={'file_tasks':0,'file_page_units':0,'ai_credits':20}
    assert quote.policy['provider_image_model']=='test-image-model'
    job,_=submit_job(a,quote.id,'image-once');job=execute_job(job.id);assert job.status=='succeeded',job.error_code
    asset=job.artifacts.get().file
    assert asset.mime_type=='image/png' and Image.open(storage_path(asset.object_key)).size==(1024,1024)
    assert asset.metadata['kind']=='image'
    execute_job(job.id)
    assert sum(UsageLedger.objects.filter(job=job,kind='consume',meter='ai_credits').values_list('amount',flat=True))==20


def test_image_failure_restores_credits_and_model_change_rejects(settings,monkeypatch):
    a=paid(settings,account());configure();mock_image(monkeypatch,{'data':[]})
    draft=create_draft(a,{'feature_id':'ai.images','prompt':'Example'});quote=generation_quote(a,draft.id,draft.version)
    job,_=submit_job(a,quote.id,'image-fail');job=execute_job(job.id)
    assert job.status=='failed' and not job.artifacts.exists() and not UsageLedger.objects.filter(job=job,kind='consume').exists()
    quote=generation_quote(a,draft.id,draft.version)
    save_config('ai',{'mode':'openai','model':'test-text-model','image_model':'other-model','api_key':''})
    with pytest.raises(DomainError,match='provider_changed'):submit_job(a,quote.id,'image-config-changed')


def test_image_boundary_blocks_redirects_and_scrubs_private_errors(monkeypatch):
    class FailedOpener:
        def open(self,*args,**kwargs):raise RuntimeError('sk-private-key and a private customer prompt')
    handlers=[]
    def opener(handler):handlers.append(handler);return FailedOpener()
    monkeypatch.setattr(illustrations.urllib.request,'build_opener',opener)
    with pytest.raises(DomainError) as failure:
        illustrations.generate_image({'mode':'openai','image_model':'test','api_key':'sk-private-key'},'A private customer prompt','id')
    assert failure.value.code=='provider_failed'
    assert 'private' not in str(failure.value)
    with pytest.raises(ValueError,match='provider_redirect_rejected'):
        handlers[0].redirect_request(None,None,302,'redirect',{},'https://another.invalid')
