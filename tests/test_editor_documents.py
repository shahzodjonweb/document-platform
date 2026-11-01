"""How large an editor draft may be: one unit from the web's meter through saving, the quote and the sandbox."""
import io
import json
import re
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from pypdf import PdfReader,PdfWriter
from apps.core.errors import DomainError
from apps.core.models import Job
from apps.core.policy import EDITOR_LIMITS,EDITOR_PARAMETER_BYTES,PARAMETER_BYTES,payload_bytes
from apps.core.services import create_quote,storage_path,upload_file
from tests.test_platform import account,login_client,upload

pytestmark=pytest.mark.django_db
CAP=EDITOR_LIMITS['bytes']


@pytest.fixture(autouse=True)
def local(settings):
    settings.DEBUG=True;settings.ENABLE_BETA_TOOLS=True;settings.LOCAL_SYNC_JOBS=True


def opened(a=None):
    a=a or account();asset=upload(a);client=login_client(a)
    created=client.post('/api/v1/editor/documents',{'file_id':str(asset.id)},content_type='application/json')
    assert created.status_code==201,created.content
    return a,asset,client,'/api/v1/editor/documents/'+created.json()['id']


def save(client,url,version,commands):
    # As a browser sends it: the test client's own encoder would escape every Cyrillic letter.
    return client.patch(url,json.dumps({'version':version,'commands':commands},ensure_ascii=False,separators=(',',':')).encode(),content_type='application/json')


def quote(client,url,version):
    return client.post(url+'/quote',{'version':version},content_type='application/json')


def run(client,quoted,key):
    job=client.post('/api/v1/jobs',{'quote_id':quoted.json()['id']},content_type='application/json',HTTP_IDEMPOTENCY_KEY=key)
    assert job.status_code==201,job.content
    return Job.objects.get(pk=job.json()['id'])


def refused(response):
    return response.status_code,response.json()['error']['code']


def marks(size,kind='note'):
    """A hundred marks of Cyrillic text that measure exactly `size` bytes as sent."""
    count=EDITOR_LIMITS['commands'];blank={'type':kind,'page':1,'x':10,'y':10,'text':''}
    letters,left=divmod(size-payload_bytes([blank]*count),2*count)
    commands=[{**blank,'text':'я'*letters} for _ in range(count)]
    commands[0]['text']+='x'*left
    assert payload_bytes(commands)==size
    return commands


def padded(size,**fields):
    """A JSON body of exactly `size` bytes; the routes read only the fields they know."""
    raw=json.dumps({**fields,'pad':''},separators=(',',':'))
    return raw[:-2]+'x'*(size-len(raw.encode()))+raw[-2:]


def test_payload_bytes_counts_what_a_browser_sends():
    assert payload_bytes({'a':'я'})==len('{"a":"я"}'.encode())==10,'a Cyrillic letter is 2 bytes, not a 6-character escape'
    assert payload_bytes(['o‘','😀',[1,2.5]])==len('["o‘","😀",[1,2.5]]'.encode()),'no spaces after separators'
    assert payload_bytes('"\n')==len(r'"\"\n"'),'escapes count as sent'
    with pytest.raises(ValueError):payload_bytes('\ud83d')


def test_a_long_cyrillic_draft_saves_quotes_and_runs():
    a,asset,client,url=opened()
    # 1 500 letters in lines that fit the page, so that the mark can be drawn too.
    mark={'type':'add_text','page':1,'x':5,'y':5,'text':'\n'.join(['я'*50]*30),'font_size':6,'color':'#000000'}
    # One such mark fitted the old caps, two saved and then failed at Review, ten did not save.
    for version,count in enumerate((1,2,10),1):
        commands=[mark]*count;saved=save(client,url,version,commands)
        assert saved.status_code==200,saved.content
        assert saved.json()['commands']==commands
        quoted=quote(client,url,version+1)
        assert quoted.status_code==201,quoted.content
        assert quoted.json()['normalized_parameters']['commands']==commands
    job=run(client,quoted,'long-cyrillic-draft')
    assert job.status=='succeeded',job.error_code
    assert job.parameters['commands']==commands
    assert 'я'*50 in PdfReader(storage_path(job.artifacts.get().file.object_key)).pages[0].extract_text()


def test_whatever_saves_at_the_cap_quotes_and_one_byte_more_is_told_so():
    a,asset,client,url=opened()
    over=save(client,url,1,marks(CAP+1))
    assert refused(over)==(413,'payload_too_large')
    assert over.json()['error']['message_key']=='errors.payload_too_large'
    kept=client.get(url).json();assert kept['version']==1 and kept['commands']==[],'nothing of a refused draft is kept'
    full=marks(CAP);saved=save(client,url,1,full)
    assert saved.status_code==200,saved.content
    assert saved.json()['commands']==full and payload_bytes(saved.json()['commands'])==CAP
    assert quote(client,url,2).status_code==201
    for accept in (True,False):
        q=create_quote(a,'editor.visual',[str(asset.id)],{'commands':full,'accept_rasterization':accept})
        assert q.parameters['commands']==full
    assert client.get(url).json()['commands']==full


def test_the_defaults_a_save_fills_in_count_towards_the_cap():
    """A draft is measured as it is stored and quoted, so saving can never make it too large to save again."""
    a,asset,client,url=opened()
    # Normalizing adds a size and a colour to each add_text.
    plain={'type':'add_text','page':1,'x':1,'y':1,'text':'a'}
    fills=(payload_bytes(save(client,url,1,[plain]).json()['commands'])-payload_bytes([plain]))*EDITOR_LIMITS['commands']
    assert fills>0
    assert refused(save(client,url,2,marks(CAP-fills+1,'add_text')))==(413,'payload_too_large')
    assert client.get(url).json()['version']==2
    saved=save(client,url,2,marks(CAP-fills,'add_text'))
    assert saved.status_code==200,saved.content
    stored=saved.json()['commands'];assert payload_bytes(stored)==CAP
    again=save(client,url,3,stored)
    assert again.status_code==200 and again.json()['commands']==stored,'the server\'s own answer can be saved back'
    assert quote(client,url,4).status_code==201


def test_the_fullest_drafts_fit_the_sandbox_and_run():
    a,asset,client,url=opened()
    # Short coordinates are the most punctuation for their bytes, and the sandbox's
    # request has spaces after its separators: this is the draft that grows the most.
    points=0
    while payload_bytes([{'type':'draw','page':1,'points':[[1,1]]*(points+1),'color':'#000000','stroke_width':2}]*100)<=CAP:points+=1
    assert points<=200,'the cap on bytes is reached before the cap on points'
    for version,(key,commands) in enumerate((('fullest-notes',marks(CAP)),('fullest-lines',[{'type':'draw','page':1,'points':[[1,1]]*points,'color':'#000000','stroke_width':2}]*100)),1):
        assert save(client,url,version,commands).status_code==200
        job=run(client,quote(client,url,version+1),key)
        assert job.status=='succeeded',job.error_code
    assert len(PdfReader(storage_path(job.artifacts.get().file.object_key)).pages)==2


def test_a_body_over_128_kib_is_refused():
    a,asset,client,url=opened()
    limit=131072
    assert client.patch(url,padded(limit,version=1,commands=[]),content_type='application/json').status_code==200
    too_long=client.patch(url,padded(limit+1,version=2,commands=[]),content_type='application/json')
    assert refused(too_long)==(413,'payload_too_large')
    assert client.get(url).json()['version']==2
    assert client.patch(url,padded(limit+1,version=2,commands=[]),content_type='text/plain').status_code==415


def test_only_the_size_being_wrong_is_called_too_large():
    a,asset,client,url=opened()
    many=[{'type':'note','page':1,'x':1,'y':1,'text':'a'}]*(EDITOR_LIMITS['commands']+1)
    assert refused(save(client,url,1,many))==(400,'invalid_parameters')
    assert refused(save(client,url,1,[*marks(CAP+1),many[0]]))==(400,'invalid_parameters')
    assert refused(save(client,url,1,{'type':'note'}))==(400,'invalid_parameters')
    bad=marks(CAP+1);bad[50]={**bad[50],'page':0}
    assert refused(save(client,url,1,bad))==(400,'invalid_editor_command')


def test_other_routes_keep_the_32_kib_body():
    a,asset,client,url=opened();limit=32768
    fields={'feature_id':'pdf.rotate','input_ids':[str(asset.id)],'parameters':{'angle':90}}
    assert client.post('/api/v1/quotes',padded(limit,**fields),content_type='application/json').status_code==201
    assert refused(client.post('/api/v1/quotes',padded(limit+1,**fields),content_type='application/json'))==(413,'invalid_request')
    assert refused(client.post('/api/v1/editor/documents',padded(limit+1,file_id=str(asset.id)),content_type='application/json'))==(413,'invalid_request')
    assert refused(client.post(url+'/quote',padded(limit+1,version=1),content_type='application/json'))==(413,'invalid_request')


def test_other_features_keep_the_10000_byte_parameters():
    a=account();asset=upload(a);ids=[str(asset.id)]
    def code(feature,parameters):
        with pytest.raises(DomainError) as error:create_quote(a,feature,ids,parameters)
        return error.value.code
    rotate=lambda pages:{'angle':90,'pages':pages}
    blank=payload_bytes(rotate(''))
    # The size is checked first: `invalid_pages` says these got past it.
    assert code('pdf.rotate',rotate('x'*(PARAMETER_BYTES-blank)))=='invalid_pages'
    assert code('pdf.rotate',rotate('x'*(PARAMETER_BYTES-blank+1)))=='invalid_parameters'
    # Bytes, not escaped characters: a Cyrillic letter once counted as six.
    assert code('pdf.rotate',rotate('я'*(PARAMETER_BYTES//6)))=='invalid_pages'
    assert code('pdf.rotate',rotate('я'*((PARAMETER_BYTES-blank)//2+1)))=='invalid_parameters'
    # An editor tool's draft may be larger, up to its own cap.
    assert create_quote(a,'editor.annotate',ids,{'commands':marks(CAP)}).feature_id=='editor.annotate'
    assert code('editor.annotate',{'commands':marks(EDITOR_PARAMETER_BYTES)})=='invalid_parameters'
    assert code('pdf.rotate',{'angle':90,'commands':marks(CAP)})=='invalid_parameters'


@pytest.mark.parametrize('feature',[None,5,True,['editor.visual'],{'a':1}])
def test_a_feature_id_that_is_not_a_string_is_still_refused_cleanly(feature):
    a,asset,client,url=opened()
    response=client.post('/api/v1/quotes',{'feature_id':feature,'input_ids':[str(asset.id)],'parameters':{}},content_type='application/json')
    assert response.status_code in (400,409),response.content


def test_text_that_cannot_be_stored_is_refused_and_not_a_crash():
    a,asset,client,url=opened()
    raw='{"version":1,"commands":[{"type":"note","page":1,"x":1,"y":1,"text":"\\ud83d"}]}'
    assert refused(client.patch(url,raw,content_type='application/json'))==(400,'invalid_request')
    assert client.get(url).json()['commands']==[]


def test_every_answer_with_a_document_says_its_limits():
    a,asset,client,url=opened();limits={'commands':100,'bytes':100000}
    created=client.post('/api/v1/editor/documents',{'file_id':str(asset.id)},content_type='application/json')
    assert created.json()['limits']==limits
    assert client.get(url).json()['limits']==limits
    assert all(row['limits']==limits for row in client.get('/api/v1/editor/documents').json()['results'])
    assert save(client,url,1,[]).json()['limits']==limits


def test_a_file_the_editor_cannot_open_is_refused_as_before():
    """The web reads this answer today; a later step adds the reason to it."""
    a=account();client=login_client(a)
    image=io.BytesIO();Image.new('RGB',(8,8)).save(image,format='PNG')
    locked=io.BytesIO();writer=PdfWriter();writer.add_blank_page(width=200,height=200);writer.encrypt('secret');writer.write(locked)
    for asset in (upload_file(a,SimpleUploadedFile('a.png',image.getvalue(),'image/png')),upload_file(a,SimpleUploadedFile('locked.pdf',locked.getvalue(),'application/pdf'),password='secret')):
        response=client.post('/api/v1/editor/documents',{'file_id':str(asset.id)},content_type='application/json')
        assert refused(response)==(400,'unsupported_file') and response.json()['error']['message_params']=={}


@pytest.mark.parametrize('locale,word',[('en','draft'),('uz','Qoralama'),('ru','Черновик')],ids=['en','uz','ru'])
def test_the_refusal_is_in_the_customers_language(settings,locale,word):
    a=account();a.locale=locale;a.save(update_fields=['locale'])
    a,asset,client,url=opened(a)
    message=save(client,url,1,marks(CAP+1)).json()['error']['message']
    messages=json.loads((settings.BASE_DIR/'i18n'/f'{locale}.json').read_text(encoding='utf-8'))
    assert message==messages['payload_too_large']!=messages['invalid_request'] and word.lower() in message.lower()
    assert not re.search(r'click|export|quote|rasteri|dpi|points?\b|encoding|экспорт|растр|кодировк|eksport|kodlash',message,re.I)
    if locale=='uz':assert 'o‘' in message and not re.search(r"[ʻʼ'`’]|[А-Яа-яЁё]",message)
