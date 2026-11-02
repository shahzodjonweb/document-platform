"""The editor's stored drafts: how large one may be, one draft per file, and one send of it: the pointer quote, the job, the count and the chat."""
import asyncio
import hashlib
import io
import json
import re
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock,Mock
import jsonschema
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image
from pypdf import PdfReader,PdfWriter
from apps.core.allowance import file_jobs_this_week,usage_snapshot
from apps.core.errors import DomainError
from apps.core.models import Account,AnalyticsEvent,FileAsset,Job,Quote
from apps.core.policy import EDITOR_LIMITS,EDITOR_PARAMETER_BYTES,PARAMETER_BYTES,payload_bytes
from apps.commerce.models import BotDelivery
from apps.core.models import BotJobNotice
from apps.core.services import cleanup_expired,create_quote,execute_job,storage_path,submit_job,upload_file
from operations import plans as plan_settings
from telegram.notifications import COPY,attempt_notice
from apps.studio.domain import pack,unpack
from apps.studio.editor_policy import stored_commands
from apps.studio.models import EditorDocument
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


def send(client,url,version,deliver='download',**fields):
    """A send of the stored draft: the new web's call. Today's web sends no `deliver`."""
    return client.post(url+'/quote',{'version':version,'deliver':deliver,**fields},content_type='application/json')


def run(client,quoted,key):
    job=client.post('/api/v1/jobs',{'quote_id':quoted.json()['id']},content_type='application/json',HTTP_IDEMPOTENCY_KEY=key.ljust(8,'-'))
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
        assert 'commands' not in quoted.json()['normalized_parameters'],'no client reads them back, and they are up to 100 KB'
        assert Quote.objects.get(pk=quoted.json()['id']).parameters['commands']==commands
    job=run(client,quoted,'long-cyrillic-draft')
    assert job.status=='succeeded',job.error_code
    assert job.parameters['commands']==commands
    assert 'commands' not in client.get(f'/api/v1/jobs/{job.id}').json()['parameters']
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


def test_a_file_the_editor_cannot_open_is_refused_and_says_why():
    """The web reads the code today, the same as ever; the reason is there for the new one."""
    a=account();client=login_client(a)
    image=io.BytesIO();Image.new('RGB',(8,8)).save(image,format='PNG')
    locked=io.BytesIO();writer=PdfWriter();writer.add_blank_page(width=200,height=200);writer.encrypt('secret');writer.write(locked)
    for asset,reason in ((upload_file(a,SimpleUploadedFile('a.png',image.getvalue(),'image/png')),'not_pdf'),(upload_file(a,SimpleUploadedFile('locked.pdf',locked.getvalue(),'application/pdf'),password='secret'),'password')):
        response=client.post('/api/v1/editor/documents',{'file_id':str(asset.id)},content_type='application/json')
        assert refused(response)==(400,'unsupported_file') and response.json()['error']['message_params']=={'reason':reason}
    deck=upload(a);FileAsset.objects.filter(pk=deck.pk).update(mime_type='application/vnd.openxmlformats-officedocument.presentationml.presentation',metadata={'kind':'pptx'})
    assert client.post('/api/v1/editor/documents',{'file_id':str(deck.id)},content_type='application/json').json()['error']['message_params']=={'reason':'pptx_upload'}


@pytest.mark.parametrize('locale,word',[('en','draft'),('uz','Qoralama'),('ru','Черновик')],ids=['en','uz','ru'])
def test_the_refusal_is_in_the_customers_language(settings,locale,word):
    a=account();a.locale=locale;a.save(update_fields=['locale'])
    a,asset,client,url=opened(a)
    message=save(client,url,1,marks(CAP+1)).json()['error']['message']
    messages=json.loads((settings.BASE_DIR/'i18n'/f'{locale}.json').read_text(encoding='utf-8'))
    assert message==messages['payload_too_large']!=messages['invalid_request'] and word.lower() in message.lower()
    assert not re.search(r'click|export|quote|rasteri|dpi|points?\b|encoding|экспорт|растр|кодировк|eksport|kodlash',message,re.I)
    if locale=='uz':assert 'o‘' in message and not re.search(r"[ʻʼ'`’]|[А-Яа-яЁё]",message)


NOTE={'type':'note','page':1,'x':10,'y':10,'text':'Запись'}


def test_a_file_has_one_draft_and_opening_it_again_comes_back_to_the_marks():
    a,asset,client,url=opened()
    assert save(client,url,1,[NOTE]).status_code==200
    again=client.post('/api/v1/editor/documents',{'file_id':str(asset.id)},content_type='application/json')
    assert again.status_code==200 and url.endswith(again.json()['id']) and again.json()['commands']==[NOTE] and again.json()['version']==2
    assert EditorDocument.objects.filter(account=a,file=asset).count()==1
    assert len(client.get('/api/v1/editor/documents').json()['results'])==1


def test_a_file_opened_many_times_before_the_rule_reopens_the_newest_draft_with_marks():
    a,asset,client,url=opened()
    assert save(client,url,1,[NOTE]).status_code==200
    marked=EditorDocument.objects.get(file=asset)
    EditorDocument.objects.create(account=a,file=asset,input_ids=[str(asset.id)])
    again=client.post('/api/v1/editor/documents',{'file_id':str(asset.id)},content_type='application/json')
    assert again.status_code==200 and again.json()['id']==str(marked.id) and again.json()['commands']==[NOTE]
    assert EditorDocument.objects.filter(account=a,file=asset).count()==2


def test_a_file_whose_drafts_are_all_empty_reopens_the_newest():
    a,asset,client,url=opened()
    newest=EditorDocument.objects.create(account=a,file=asset,input_ids=[str(asset.id)],created_at=timezone.now()+timedelta(seconds=1))
    again=client.post('/api/v1/editor/documents',{'file_id':str(asset.id)},content_type='application/json')
    assert again.status_code==200 and again.json()['id']==str(newest.id)


def test_two_accounts_cannot_share_a_draft_of_one_file():
    a,asset,client,url=opened()
    other=login_client(account(43))
    assert other.post('/api/v1/editor/documents',{'file_id':str(asset.id)},content_type='application/json').status_code>=400
    assert other.get(url).status_code==404


def test_marks_are_written_encrypted_and_in_the_clear_until_the_clear_column_goes():
    a,asset,client,url=opened()
    assert save(client,url,1,[NOTE]).status_code==200
    row=EditorDocument.objects.get(file=asset)
    assert row.commands==[NOTE] and unpack(row.encrypted_commands)=={'version':2,'commands':[NOTE]}
    assert 'Запись'.encode() not in bytes(row.encrypted_commands)


def test_marks_are_read_from_either_column():
    a,asset,client,url=opened()
    row=EditorDocument.objects.get(file=asset)
    # A row last written by the image before 0010 has only the clear column.
    EditorDocument.objects.filter(pk=row.pk).update(commands=[NOTE],encrypted_commands=None)
    assert client.get(url).json()['commands']==[NOTE]
    # After 0012 it has only the encrypted one.
    EditorDocument.objects.filter(pk=row.pk).update(commands=[],encrypted_commands=pack({'version':row.version,'commands':[NOTE]}))
    assert client.get(url).json()['commands']==[NOTE]


def test_marks_written_by_the_image_before_this_one_are_not_lost():
    """Mid-deploy or after a rollback that image writes only the clear column: what differs there is newer."""
    a,asset,client,url=opened()
    assert save(client,url,1,[NOTE]).status_code==200
    newer=[{**NOTE,'text':'Новее'}]
    EditorDocument.objects.filter(file=asset).update(commands=newer,version=3)
    assert client.get(url).json()['commands']==newer
    assert stored_commands(EditorDocument.objects.get(file=asset))==newer


def test_marks_removed_by_the_image_before_this_one_stay_removed():
    """A signature taken off there must not come back from the encrypted copy, nor reach the next file."""
    a,asset,client,url=opened()
    assert save(client,url,1,[NOTE]).status_code==200
    EditorDocument.objects.filter(file=asset).update(commands=[],version=3)
    assert client.get(url).json()['commands']==[]
    again=client.post('/api/v1/editor/documents',{'file_id':str(asset.id)},content_type='application/json')
    assert again.status_code==200 and again.json()['commands']==[] and again.json()['version']==3
    assert refused(quote(client,url,3))==(400,'invalid_editor_command')
    # And this image, saving again, takes over from there.
    assert save(client,url,3,[NOTE]).json()['commands']==[NOTE]
    assert stored_commands(EditorDocument.objects.get(file=asset))==[NOTE]


def test_a_quote_reads_the_encrypted_marks():
    a,asset,client,url=opened()
    EditorDocument.objects.filter(file=asset).update(commands=[],encrypted_commands=pack({'version':1,'commands':[NOTE]}))
    quoted=quote(client,url,1)
    assert quoted.status_code==201,quoted.content
    job=run(client,quoted,'editor-encrypted-1')
    assert job.status=='succeeded',job.error_code


def test_a_conflict_says_when_where_and_how_many_marks_each_side_holds():
    a,asset,client,url=opened()
    saved=client.patch(url,json.dumps({'version':1,'commands':[NOTE,NOTE],'device':'Telefon'}),content_type='application/json').json()
    late=client.patch(url,json.dumps({'version':1,'commands':[NOTE],'device':'Noutbuk'}),content_type='application/json')
    assert refused(late)==(409,'version_conflict')
    assert late.json()['error']['message_params']=={'updated_at':saved['updated_at'],'device':'Telefon','theirs':2,'mine':1}
    behind=quote(client,url,1)
    assert refused(behind)==(409,'version_conflict')
    # A quote carries no marks: the server cannot say how many the caller holds, so it does not.
    assert behind.json()['error']['message_params']=={'updated_at':saved['updated_at'],'device':'Telefon','theirs':2}
    assert EditorDocument.objects.get(file=asset).commands==[NOTE,NOTE]


def test_the_device_and_the_time_of_the_last_change_are_kept():
    a,asset,client,url=opened()
    fresh=client.get(url).json()
    assert fresh['updated_at'] is None and fresh['device']==''
    saved=client.patch(url,json.dumps({'version':1,'commands':[],'device':'x'*40}),content_type='application/json').json()
    assert saved['device']=='x'*40 and saved['updated_at'] and client.get(url).json()['updated_at']==saved['updated_at']
    # An editor that does not name its device: that is who changed it last, not the one before.
    assert save(client,url,2,[]).json()['device']==''
    for bad in ('x'*41,7,'a\x00b'):
        assert refused(client.patch(url,json.dumps({'version':3,'commands':[],'device':bad}),content_type='application/json'))==(400,'invalid_parameters')
    assert EditorDocument.objects.get(file=asset).version==3


def test_the_web_on_phones_today_keeps_working_on_the_new_document():
    """It sends no device and reads the fields it always read; the new ones are extra."""
    a,asset,client,url=opened()
    saved=save(client,url,1,[NOTE])
    assert saved.status_code==200
    assert {'id','version','file','pages','form_fields','image_counts','commands','input_ids','limits'}<=saved.json().keys()
    assert run(client,quote(client,url,2),'editor-old-web-1').status=='succeeded'
    assert client.delete(url).json()=={'deleted':True}


def test_a_kind_that_waits_for_its_step_saves_but_fails_the_job_whole():
    a,asset,client,url=opened()
    commands=[NOTE,{'type':'edit_text','page':1,'x':1,'y':1,'width':9,'height':9,'original':'a','text':'b'}]
    assert save(client,url,1,commands).status_code==200
    job=run(client,send(client,url,2),'editor-new-kind-1')
    assert job.status=='failed' and job.error_code=='invalid_editor_command'
    answer=client.get(f'/api/v1/jobs/{job.id}').json()
    assert answer['error']['message_params']=={'index':1} and answer['warnings']==[]


def test_a_nul_in_a_field_is_refused_rather_than_breaking_the_database():
    a,asset,client,url=opened()
    for command in ({'type':'fill_form','field':'name','value':'a\x00b'},{'type':'replace_text','page':1,'find':'a','replacement':'b\x00'}):
        assert refused(save(client,url,1,[command]))==(400,'invalid_editor_command')


def test_a_refused_save_says_which_change_and_why():
    a,asset,client,url=opened()
    good=dict(NOTE)
    for bad in ({**good,'page':99},{**good,'text':'a\x07b'},{'type':'nonsense'},'not a command'):
        answer=save(client,url,1,[good,good,bad,good])
        assert refused(answer)==(400,'invalid_editor_command')
        assert answer.json()['error']['message_params']=={'index':2,'code':'invalid_editor_command'}
    # Across the page operations, the one that broke the rule.
    answer=save(client,url,1,[good,{'type':'rotate_page','page':1,'angle':90},good,{'type':'rotate_page','page':1,'angle':180}])
    assert answer.json()['error']['message_params']=={'index':3,'code':'invalid_editor_command'}
    answer=save(client,url,1,[{'type':'signature','page':1,'x':1,'y':1,'width':5,'height':5,'input_index':1}])
    assert answer.json()['error']['message_params']=={'index':0,'code':'invalid_editor_command'}
    assert EditorDocument.objects.get(file=asset).version==1


def test_a_draft_may_mix_black_out_with_other_marks_but_todays_quote_still_refuses_the_mix():
    a,asset,client,url=opened()
    assert save(client,url,1,[{'type':'redact','page':1,'x':1,'y':1,'width':5,'height':5},NOTE]).status_code==200
    answer=client.post(url+'/quote',{'version':2,'accept_rasterization':True},content_type='application/json')
    assert refused(answer)==(400,'redaction_requires_separate_export') and answer.json()['error']['message_params']=={}
    assert send(client,url,2,accept_rasterization=True).status_code==201


def test_opening_a_file_that_ran_out_says_so_and_not_for_anyone_elses():
    a=account();asset=upload(a);client=login_client(a)
    FileAsset.objects.filter(pk=asset.pk).update(expires_at=timezone.now()-timedelta(hours=1))
    open_it=lambda who,fid:who.post('/api/v1/editor/documents',{'file_id':fid},content_type='application/json')
    assert refused(open_it(client,str(asset.id)))==(410,'file_expired')
    # Cleanup deleting the bytes changes nothing for the customer.
    FileAsset.objects.filter(pk=asset.pk).update(state='deleted')
    assert refused(open_it(client,str(asset.id)))==(410,'file_expired')
    assert refused(open_it(login_client(account(43)),str(asset.id)))==(404,'file_unavailable')
    assert refused(open_it(client,str(uuid.uuid4())))==(404,'file_unavailable')
    assert refused(open_it(client,'not-a-file'))==(400,'invalid_inputs')


def test_a_file_the_customer_deleted_did_not_run_out():
    a,asset,client,url=opened()
    open_it=lambda:client.post('/api/v1/editor/documents',{'file_id':str(asset.id)},content_type='application/json')
    assert client.delete(f'/api/v1/files/{asset.id}').status_code==200
    assert refused(open_it())==(404,'file_unavailable') and refused(client.get(url))==(404,'file_unavailable')
    # Cleanup makes it a row like any file that ran out, past its time and deleted; the answer stays.
    cleanup_expired()
    assert FileAsset.objects.get(pk=asset.pk).state=='deleted'
    assert refused(open_it())==(404,'file_unavailable')
    # The draft of a file that did run out keeps saying so.
    other,ran_out,other_client,other_url=opened(account(44))
    FileAsset.objects.filter(pk=ran_out.pk).update(expires_at=timezone.now()-timedelta(hours=1))
    assert refused(other_client.get(other_url))==(410,'file_expired')


def test_a_form_field_named_with_control_characters_still_saves():
    a,asset,client,url=opened()
    named={'type':'fill_form','field':'Ism\rFamiliya\x0b','value':'Ali\r\nVali'}
    answer=save(client,url,1,[named])
    assert answer.status_code==200,answer.content
    assert answer.json()['commands']==[named]


BLACK={'type':'redact','page':1,'x':10,'y':10,'width':50,'height':20}


def submit(client,quoted,key,**fields):
    return client.post('/api/v1/jobs',{'quote_id':quoted.json()['id'],**fields},content_type='application/json',HTTP_IDEMPOTENCY_KEY=key.ljust(8,'-'))


def sent(client,url,version,commands,key,deliver='download',**fields):
    """Saved and sent. Returns the job."""
    assert save(client,url,version,commands).status_code==200
    quoted=send(client,url,version+1,deliver,**fields)
    assert quoted.status_code==201,quoted.content
    return run(client,quoted,key)


def queued(settings):
    settings.LOCAL_SYNC_JOBS=False


def test_one_send_is_one_quote_one_job_one_file_task_and_holds_no_text(caplog):
    words='Секретные слова клиента'
    a,asset,client,url=opened()
    commands=[{'type':'add_text','page':1,'x':5,'y':5,'text':words,'font_size':8},{'type':'delete_page','page':2}]
    assert save(client,url,1,commands).status_code==200
    quoted=send(client,url,2)
    assert quoted.status_code==201,quoted.content
    body=quoted.json()
    assert body['feature_id']=='editor.visual' and body['affordable'] is True
    row=Quote.objects.get(pk=body['id'])
    assert row.parameters.keys()=={'editor_document_id','version','snapshot','content','deliver'}
    document=EditorDocument.objects.get(file=asset)
    assert row.parameters['editor_document_id']==str(document.id) and row.parameters['version']==2 and row.parameters['deliver']=='download'
    assert row.parameters['snapshot']==hashlib.sha256(bytes(document.encrypted_commands)).hexdigest()
    assert body['normalized_parameters']==row.parameters
    summary=body['summary']
    assert summary['changes_by_page']=={'1':1,'2':1} and summary['pages_before']==2 and summary['pages_after']==1 and summary['raster_pages']==[]
    assert summary['size_estimate']>0 and summary['cost']=={'kind':'file_task','left':usage_snapshot(a)['file_jobs']['remaining'],'limit':usage_snapshot(a)['file_jobs']['limit']}
    assert summary['kept_until']>timezone.now().isoformat()
    before=usage_snapshot(a)['file_jobs']['used']
    answer=submit(client,quoted,'pointer-one-send')
    assert answer.status_code==201,answer.content
    job=Job.objects.get(pk=answer.json()['id'])
    assert job.status=='succeeded',job.error_code
    assert usage_snapshot(a)['file_jobs']['used']==before+1 and Job.objects.filter(account=a).count()==1
    assert job.parameters==row.parameters and job.input_ids==[str(asset.id)]
    reader=PdfReader(storage_path(job.artifacts.get().file.object_key))
    assert len(reader.pages)==1 and words in reader.pages[0].extract_text()
    for stored in (json.dumps(row.parameters),json.dumps(row.policy),json.dumps(job.parameters),json.dumps(job.warnings),job.error_code,json.dumps(answer.json(),ensure_ascii=False),json.dumps(client.get('/api/v1/jobs').json(),ensure_ascii=False),caplog.text):
        assert words not in stored
    assert AnalyticsEvent.objects.get(account=a,event_type='quote.created').feature_id=='editor.visual'
    assert job.artifacts.get().file.metadata['editor_document_id']==str(document.id)


def test_a_generic_quote_says_which_feature_too():
    a=account();asset=upload(a)
    create_quote(a,'pdf.rotate',[str(asset.id)],{})
    assert AnalyticsEvent.objects.get(account=a,event_type='quote.created').feature_id=='pdf.rotate'


def test_the_summary_fits_the_contract():
    from apps.core.management.commands.export_contract import schema
    contract=schema()
    a,asset,client,url=opened()
    assert save(client,url,1,[NOTE,BLACK,{'type':'reorder','order':[2,1]}]).status_code==200
    answer=send(client,url,2,accept_rasterization=True).json()
    validator=jsonschema.Draft202012Validator({'$ref':'#/components/schemas/EditorQuoteSummary','components':contract['components']})
    validator.validate(answer['summary'])
    assert answer['summary']['raster_pages']==[1] and answer['summary']['changes_by_page']=={'1':2}
    job=run(client,send(client,url,2,accept_rasterization=True),'contract-job')
    answer=client.get(f'/api/v1/jobs/{job.id}').json()
    jsonschema.Draft202012Validator({'$ref':'#/components/schemas/Job','components':contract['components']}).validate(answer)


def test_1500_cyrillic_letters_save_quote_and_run_by_pointer():
    a,asset,client,url=opened()
    mark={'type':'add_text','page':1,'x':5,'y':5,'text':'\n'.join(['я'*50]*30),'font_size':6,'color':'#000000'}
    job=sent(client,url,1,[mark]*2,'pointer-cyrillic')
    assert job.status=='succeeded',job.error_code
    assert 'я'*50 in PdfReader(storage_path(job.artifacts.get().file.object_key)).pages[0].extract_text()
    assert 'я' not in json.dumps(job.parameters,ensure_ascii=False)


def test_the_fullest_draft_runs_by_pointer():
    a,asset,client,url=opened()
    job=sent(client,url,1,marks(CAP),'pointer-fullest')
    assert job.status=='succeeded',job.error_code


def test_todays_web_flow_is_as_it_was():
    """The calls the deployed web makes, with what it reads from each answer. It sends no `deliver` and gets no summary."""
    a,asset,client,url=opened()
    saved=save(client,url,1,[NOTE])
    assert saved.status_code==200 and {'id','version','file','pages','form_fields','image_counts','commands','input_ids','limits'}<=saved.json().keys()
    quoted=client.post(url+'/quote',{'version':2,'accept_rasterization':False},content_type='application/json')
    assert quoted.status_code==201 and 'summary' not in quoted.json() and quoted.json()['affordable'] is True and quoted.json()['id']
    assert Quote.objects.get(pk=quoted.json()['id']).parameters=={'commands':[NOTE],'accept_rasterization':False},'its quote still carries the marks'
    assert quoted.json()['normalized_parameters']=={'accept_rasterization':False}
    answer=submit(client,quoted,'today-web-1')
    assert answer.status_code==201 and answer.json()['status']=='succeeded' and answer.json()['origin_channel']=='web'
    assert answer.json()['warnings']==[] and answer.json()['artifacts'][0]['download_url']
    assert Job.objects.get(pk=answer.json()['id']).warnings==[],'the row too: the image before this one reads only codes there'
    assert not BotDelivery.objects.filter(account=a).exists()
    # Black-out alone, after the tick its screen asks for: every page a picture, as that screen says.
    version=saved.json()['version']
    assert save(client,url,version,[BLACK]).status_code==200
    answer=client.post(url+'/quote',{'version':version+1},content_type='application/json')
    assert refused(answer)==(400,'rasterization_consent_required') and answer.json()['error']['message_params']=={}
    job=run(client,client.post(url+'/quote',{'version':version+1,'accept_rasterization':True},content_type='application/json'),'today-web-2')
    assert job.status=='succeeded',job.error_code
    shown=client.get(f'/api/v1/jobs/{job.id}').json()
    assert 'all_pages_rasterized_text_and_forms_removed' in shown['warnings'] and all(isinstance(row,str) for row in shown['warnings']),'each becomes a banner, by its code'
    assert all(isinstance(row,str) for row in Job.objects.get(pk=job.pk).warnings)
    reader=PdfReader(storage_path(job.artifacts.get().file.object_key))
    assert len(reader.pages)==2 and not any(page.extract_text().strip() for page in reader.pages)
    # The generic route still takes an inline editor quote while the new editor is off.
    generic=client.post('/api/v1/quotes',{'feature_id':'editor.visual','input_ids':[str(asset.id)],'parameters':{'commands':[NOTE]}},content_type='application/json')
    assert generic.status_code==201,generic.content
    assert submit(client,generic,'today-web-3').status_code==201


def test_nobody_can_ask_for_the_combined_job_by_hand():
    a,asset,client,url=opened()
    answer=client.post('/api/v1/quotes',{'feature_id':'editor.visual','input_ids':[str(asset.id)],'parameters':{'commands':[BLACK,NOTE],'accept_rasterization':True,'combined':True}},content_type='application/json')
    assert refused(answer)==(400,'invalid_parameters')


def test_a_job_row_reports_in_numbers_and_the_answer_keeps_warnings_to_codes():
    a,asset,client,url=opened()
    job=sent(client,url,1,[NOTE,BLACK,{'type':'delete_page','page':2}],'pointer-numbers',accept_rasterization=True)
    assert job.status=='succeeded',job.error_code
    rows=[{'index':0,'status':'applied','engine':'pypdf'},{'index':1,'status':'applied','engine':'pdfium'},{'index':2,'status':'applied','engine':'pypdf'}]
    assert job.warnings==[{'per_command':rows},{'rasterized_pages':[1]}]
    answer=client.get(f'/api/v1/jobs/{job.id}').json()
    assert answer['warnings']==[] and answer['per_command']==rows and answer['rasterized_pages']==[1]
    assert job.artifacts.get().file.metadata['rasterized_pages']==[1] and job.artifacts.get().file.metadata['page_count']==1


def test_a_refused_send_says_why(monkeypatch):
    a,asset,client,url=opened()
    assert save(client,url,1,[NOTE]).status_code==200
    answer=send(client,url,1)
    assert refused(answer)==(409,'version_conflict') and answer.json()['error']['message_params']['theirs']==1
    assert refused(send(client,url,2,'somewhere'))==(400,'invalid_parameters')
    assert refused(send(client,url,2,accept_rasterization='yes'))==(400,'invalid_parameters')
    assert refused(client.post('/api/v1/editor/documents/'+str(uuid.uuid4())+'/quote',{'version':1,'deliver':'chat'},content_type='application/json'))==(404,'not_found')
    def closed(_):raise DomainError('channels_required',403)
    monkeypatch.setattr('apps.core.channel_gate.require',closed)
    assert refused(send(client,url,2))==(403,'channels_required')
    assert not Quote.objects.filter(account=a).exists()


def test_another_accounts_draft_cannot_be_sent():
    a,asset,client,url=opened()
    assert save(client,url,1,[NOTE]).status_code==200
    other=login_client(account(77))
    assert refused(send(other,url,2))==(404,'not_found')


def test_consent_is_asked_for_pages_that_will_really_be_drawn():
    a,asset,client,url=opened()
    assert save(client,url,1,[BLACK]).status_code==200
    answer=send(client,url,2)
    assert refused(answer)==(400,'rasterization_consent_required') and answer.json()['error']['message_params']=={'pages':[1]}
    assert send(client,url,2,accept_rasterization=True).status_code==201
    assert save(client,url,2,[BLACK,{'type':'delete_page','page':1}]).status_code==200
    quoted=send(client,url,3)
    assert quoted.status_code==201 and quoted.json()['summary']['raster_pages']==[]
    job=run(client,quoted,'consent-deleted')
    assert job.status=='succeeded',job.error_code


def test_a_text_too_wide_for_its_page_is_refused_before_it_is_sent():
    a,asset,client,url=opened()
    wide={'type':'add_text','page':1,'x':5,'y':5,'text':'я'*300,'font_size':16}
    assert save(client,url,1,[NOTE,wide]).status_code==200
    answer=send(client,url,2)
    assert refused(answer)==(400,'editor_text_overflow') and answer.json()['error']['message_params']=={'index':1}
    assert answer.json()['error']['message']=='The text does not fit. Shorten it or reduce the font size.'
    assert not Quote.objects.filter(account=a).exists()


def test_the_loaded_marks_are_what_access_is_checked_on_at_all_three_moments(settings,monkeypatch):
    queued(settings)
    a,asset,client,url=opened()
    assert save(client,url,1,[NOTE]).status_code==200
    seen=[]
    from apps.studio import editor_domain
    real=editor_domain.validate_commands_access
    monkeypatch.setattr(editor_domain,'validate_commands_access',lambda account,commands:seen.append(commands) or real(account,commands))
    quoted=send(client,url,2)
    assert seen==[[NOTE]],'at the quote'
    job=Job.objects.get(pk=submit(client,quoted,'access-submit').json()['id'])
    assert seen==[[NOTE],[NOTE]],'at submission'
    assert execute_job(job.id).status=='succeeded'
    assert seen==[[NOTE],[NOTE],[NOTE]],'and when it runs'
    def downgraded(account,commands):raise DomainError('feature_not_in_plan',403)
    assert save(client,url,2,[NOTE,NOTE]).status_code==200
    second=send(client,url,3)
    monkeypatch.setattr(editor_domain,'validate_commands_access',downgraded)
    assert refused(submit(client,second,'access-submit-2'))==(403,'feature_not_in_plan')
    monkeypatch.setattr(editor_domain,'validate_commands_access',real)
    job=Job.objects.get(pk=submit(client,second,'access-submit-3').json()['id'])
    monkeypatch.setattr(editor_domain,'validate_commands_access',downgraded)
    job=execute_job(job.id)
    assert job.status=='failed' and job.error_code=='feature_not_in_plan'


def test_marks_changed_after_the_quote_are_refused_and_nothing_is_counted():
    a,asset,client,url=opened()
    assert save(client,url,1,[NOTE]).status_code==200
    quoted=send(client,url,2)
    assert save(client,url,2,[NOTE,NOTE]).status_code==200
    assert refused(submit(client,quoted,'stale-send'))==(409,'version_conflict')
    assert not Job.objects.filter(account=a).exists() and usage_snapshot(a)['file_jobs']['used']==0
    # The same version with other bytes under it is no more the draft that was quoted.
    fresh=send(client,url,3)
    EditorDocument.objects.filter(file=asset).update(encrypted_commands=pack({'version':3,'commands':[NOTE]}))
    assert refused(submit(client,fresh,'tampered-send'))==(409,'version_conflict')


def test_a_draft_changed_while_its_job_waits_fails_it_and_nothing_is_counted(settings):
    queued(settings)
    a,asset,client,url=opened()
    assert save(client,url,1,[NOTE]).status_code==200
    job=Job.objects.get(pk=submit(client,send(client,url,2),'waiting-send').json()['id'])
    assert job.status=='queued' and usage_snapshot(a)['file_jobs']['used']==1
    assert save(client,url,2,[NOTE,NOTE]).status_code==200,'a queued send never blocks autosave'
    job=execute_job(job.id)
    assert job.status=='failed' and job.error_code=='version_conflict' and not job.artifacts.exists()
    assert usage_snapshot(a)['file_jobs']['used']==0


def test_a_draft_deleted_while_its_job_waits_fails_it(settings):
    queued(settings)
    a,asset,client,url=opened()
    assert save(client,url,1,[NOTE]).status_code==200
    job=Job.objects.get(pk=submit(client,send(client,url,2),'deleted-send').json()['id'])
    assert client.delete(url).status_code==200
    job=execute_job(job.id)
    assert job.status=='failed' and job.error_code=='version_conflict'


def test_a_draft_saved_before_encryption_can_be_sent():
    a,asset,client,url=opened()
    EditorDocument.objects.filter(file=asset).update(commands=[NOTE],encrypted_commands=None)
    job=run(client,send(client,url,1),'old-row-send')
    assert job.status=='succeeded',job.error_code
    # And one last written by the image before this one, whose encrypted copy is behind.
    EditorDocument.objects.filter(file=asset).update(version=5,commands=[NOTE,NOTE],encrypted_commands=pack({'version':2,'commands':[NOTE]}))
    job=run(client,send(client,url,5),'old-image-send')
    assert job.status=='succeeded',job.error_code
    assert len(PdfReader(storage_path(job.artifacts.get().file.object_key)).pages[0]['/Annots'])==2


def test_a_failed_black_out_check_counts_nothing_and_names_the_change(monkeypatch):
    a,asset,client,url=opened()
    from processors.engine import ProcessorError
    assert save(client,url,1,[NOTE,BLACK]).status_code==200
    def failing(*args,**kwargs):raise ProcessorError('editor_check_failed',index=1)
    monkeypatch.setattr('processors.sandbox.execute_sandbox',failing)
    job=run(client,send(client,url,2,accept_rasterization=True),'failed-check')
    assert job.status=='failed' and job.error_code=='editor_check_failed' and usage_snapshot(a)['file_jobs']['used']==0
    answer=client.get(f'/api/v1/jobs/{job.id}').json()
    assert answer['error']['code']=='editor_check_failed' and answer['error']['message_params']=={'index':1} and answer['warnings']==[]
    assert answer['error']['message']=='We could not confirm that a blacked-out area is fully covered, so no file was made. Please try again.'


def test_a_draft_sent_again_counts_once_behind_the_flag(monkeypatch):
    monkeypatch.setenv('EDITOR_FLAG_COUNT_ONCE','1')
    a,asset,client,url=opened()
    assert sent(client,url,1,[NOTE],'once-1').status=='succeeded'
    assert usage_snapshot(a)['file_jobs']['used']==1
    assert save(client,url,2,[NOTE,NOTE]).status_code==200
    quoted=send(client,url,3)
    assert quoted.json()['summary']['cost']['kind']=='none'
    assert run(client,quoted,'once-2').status=='succeeded'
    assert usage_snapshot(a)['file_jobs']['used']==1 and Job.objects.filter(account=a).count()==2
    # Another draft is another task, and a tool that is no draft is one each time.
    other=upload(a,name='other.pdf');second=client.post('/api/v1/editor/documents',{'file_id':str(other.id)},content_type='application/json').json()['id']
    assert sent(client,'/api/v1/editor/documents/'+second,1,[NOTE],'once-3').status=='succeeded'
    assert usage_snapshot(a)['file_jobs']['used']==2
    for key in ('once-rotate-4','once-rotate-5'):
        job,_=submit_job(a,create_quote(a,'pdf.rotate',[str(asset.id)],{}).id,key)
        execute_job(job.id)
    assert usage_snapshot(a)['file_jobs']['used']==4
    # Today's inline quote carries no pointer, so it counts as it does today.
    job=run(client,client.post(url+'/quote',{'version':3},content_type='application/json'),'once-6')
    assert job.status=='succeeded' and usage_snapshot(a)['file_jobs']['used']==5


def test_with_the_flag_off_each_change_sent_is_a_task(monkeypatch):
    a,asset,client,url=opened()
    assert sent(client,url,1,[NOTE],'each-1').status=='succeeded'
    assert save(client,url,2,[NOTE,NOTE]).status_code==200
    quoted=send(client,url,3)
    assert quoted.json()['summary']['cost']['kind']=='file_task'
    assert run(client,quoted,'each-2').status=='succeeded' and usage_snapshot(a)['file_jobs']['used']==2


def test_the_week_starts_a_draft_over(monkeypatch):
    monkeypatch.setenv('EDITOR_FLAG_COUNT_ONCE','1')
    a,asset,client,url=opened()
    job=sent(client,url,1,[NOTE],'week-1')
    assert save(client,url,2,[NOTE,NOTE]).status_code==200
    assert send(client,url,3).json()['summary']['cost']['kind']=='none'
    Job.objects.filter(pk=job.pk).update(created_at=timezone.now()-timedelta(days=8))
    assert send(client,url,3).json()['summary']['cost']['kind']=='file_task'
    assert file_jobs_this_week(a)==0


def test_a_failed_send_counts_nothing_and_leaves_the_next_one_to_be_counted(monkeypatch,settings):
    monkeypatch.setenv('EDITOR_FLAG_COUNT_ONCE','1')
    queued(settings)
    a,asset,client,url=opened()
    assert save(client,url,1,[NOTE]).status_code==200
    job=Job.objects.get(pk=submit(client,send(client,url,2),'gave-back-1').json()['id'])
    assert save(client,url,2,[NOTE,NOTE]).status_code==200
    assert execute_job(job.id).status=='failed'
    assert send(client,url,3).json()['summary']['cost']['kind']=='file_task'


def test_the_week_limit_refuses_a_new_draft_not_one_already_counted(monkeypatch):
    plan_settings.save('free',{'weekly_file_jobs':1})
    a,asset,client,url=opened()
    assert sent(client,url,1,[NOTE],'limit-1').status=='succeeded'
    assert save(client,url,2,[NOTE,NOTE]).status_code==200
    answer=send(client,url,3)
    assert refused(answer)==(429,'weekly_file_limit')
    monkeypatch.setenv('EDITOR_FLAG_COUNT_ONCE','1')
    quoted=send(client,url,3)
    assert quoted.status_code==201 and quoted.json()['affordable'] is True and quoted.json()['summary']['cost']=={'kind':'none','left':0,'limit':1}
    assert run(client,quoted,'limit-2').status=='succeeded'
    other=upload(a,name='other.pdf');second='/api/v1/editor/documents/'+client.post('/api/v1/editor/documents',{'file_id':str(other.id)},content_type='application/json').json()['id']
    assert save(client,second,1,[NOTE]).status_code==200
    assert refused(send(client,second,2))==(429,'weekly_file_limit')


def test_a_plan_with_no_limit_is_told_it_is_included():
    a,asset,client,url=opened()
    Account.objects.filter(pk=a.pk).update(staff_plan='premium')
    assert save(client,url,1,[NOTE]).status_code==200
    assert send(client,url,2).json()['summary']['cost']=={'kind':'included','left':None,'limit':None}


def test_the_same_marks_sent_again_return_the_same_file():
    plan_settings.save('free',{'weekly_file_jobs':1})
    a,asset,client,url=opened()
    job=sent(client,url,1,[NOTE],'same-1')
    assert job.status=='succeeded' and usage_snapshot(a)['file_jobs']['used']==1
    # Free of the week whatever the flag says, as nothing is made.
    quoted=send(client,url,2)
    assert quoted.status_code==201 and quoted.json()['summary']['cost']['kind']=='none' and quoted.json()['affordable'] is True
    answer=submit(client,quoted,'same-2')
    assert answer.status_code==200 and answer.json()['id']==str(job.id)
    assert Job.objects.filter(account=a).count()==1 and usage_snapshot(a)['file_jobs']['used']==1
    # A file that has gone is made again.
    job.artifacts.get().file.__class__.objects.filter(pk=job.artifacts.get().file_id).update(expires_at=timezone.now()-timedelta(minutes=1))
    plan_settings.save('free',{'weekly_file_jobs':5})
    quoted=send(client,url,2)
    assert quoted.json()['summary']['cost']['kind']=='file_task'
    answer=submit(client,quoted,'same-3')
    assert answer.status_code==201 and answer.json()['id']!=str(job.id)


def test_the_last_good_job_is_the_only_one_compared():
    a,asset,client,url=opened()
    first=sent(client,url,1,[NOTE],'last-1')
    second=sent(client,url,2,[NOTE,NOTE],'last-2')
    assert first.status==second.status=='succeeded'
    # Nothing is the same as a file made before the last: there is no way back to those bytes.
    quoted=send(client,url,3)
    assert submit(client,quoted,'last-3').json()['id']==str(second.id)


def test_a_draft_sent_too_often_is_told_to_wait(monkeypatch):
    from apps.studio import editor_domain
    assert (editor_domain.SENDS_PER_DRAFT_PER_DAY,editor_domain.EDITOR_JOBS_PER_ACCOUNT_PER_HOUR)==(10,20)
    monkeypatch.setattr(editor_domain,'SENDS_PER_DRAFT_PER_DAY',2)
    a,asset,client,url=opened()
    held=[sent(client,url,1,[NOTE],'brake-1'),sent(client,url,2,[NOTE,NOTE],'brake-2')]
    assert save(client,url,3,[NOTE]).status_code==200
    answer=send(client,url,4)
    assert refused(answer)==(429,'send_limit') and answer.json()['error']['retryable'] is True and answer.json()['error']['message_params']=={'limit':2,'per':'day'}
    # A quote made before the brake is refused at submission, under the account's lock.
    monkeypatch.setattr(editor_domain,'SENDS_PER_DRAFT_PER_DAY',3)
    quoted=send(client,url,4)
    monkeypatch.setattr(editor_domain,'SENDS_PER_DRAFT_PER_DAY',2)
    assert refused(submit(client,quoted,'brake-3'))==(429,'send_limit')
    assert Job.objects.filter(account=a).count()==2
    # A day later there is room again.
    Job.objects.filter(pk__in=[job.pk for job in held]).update(created_at=timezone.now()-timedelta(days=1,minutes=1))
    assert send(client,url,4).status_code==201


def test_an_account_is_held_to_its_editor_jobs_an_hour_across_its_drafts(monkeypatch):
    from apps.studio import editor_domain
    monkeypatch.setattr(editor_domain,'EDITOR_JOBS_PER_ACCOUNT_PER_HOUR',2)
    a,asset,client,url=opened()
    sent(client,url,1,[NOTE],'hour-1');sent(client,url,2,[NOTE,NOTE],'hour-2')
    other=upload(a,name='other.pdf');second='/api/v1/editor/documents/'+client.post('/api/v1/editor/documents',{'file_id':str(other.id)},content_type='application/json').json()['id']
    assert save(client,second,1,[NOTE]).status_code==200
    answer=send(client,second,2)
    assert refused(answer)==(429,'send_limit') and answer.json()['error']['message_params']=={'limit':2,'per':'hour'}
    # Another tool is not an editor job, and neither is today's route held back.
    job,_=submit_job(a,create_quote(a,'pdf.rotate',[str(asset.id)],{}).id,'hour-rotate')
    assert execute_job(job.id).status=='succeeded'
    assert run(client,client.post(second+'/quote',{'version':2},content_type='application/json'),'hour-inline').status=='succeeded'
    Job.objects.filter(account=a).update(created_at=timezone.now()-timedelta(hours=1,minutes=1))
    assert send(client,second,2).status_code==201


def test_a_batch_of_forms_is_not_held_to_the_brake(monkeypatch):
    from apps.studio import editor_domain
    monkeypatch.setattr(editor_domain,'EDITOR_JOBS_PER_ACCOUNT_PER_HOUR',1)
    a,asset,client,url=opened()
    for index in range(3):
        job,_=submit_job(a,create_quote(a,'editor.visual',[str(asset.id)],{'commands':[NOTE]}).id,f'batch:run:{index}')
        assert execute_job(job.id).status=='succeeded'
    assert save(client,url,1,[NOTE]).status_code==200
    assert send(client,url,2).status_code==201


def test_a_result_goes_back_to_the_chat():
    a,asset,client,url=opened()
    assert save(client,url,1,[NOTE]).status_code==200
    answer=submit(client,send(client,url,2),'chat-1',deliver_to_chat=True)
    assert answer.status_code==201 and answer.json()['origin_channel']=='mini_app'
    job=Job.objects.get(pk=answer.json()['id'])
    delivery=BotDelivery.objects.get(account=a)
    assert delivery.artifact==job.artifacts.get() and delivery.status=='pending' and delivery.idempotency_key==f'job:{job.id}:{delivery.artifact_id}'
    # Sent again unchanged: the same file, to the chat again, once for each quote.
    again=send(client,url,2,'chat')
    answer=submit(client,again,'chat-2')
    assert answer.status_code==200 and answer.json()['id']==str(job.id) and BotDelivery.objects.filter(account=a).count()==2
    assert submit(client,again,'chat-2',deliver_to_chat=True).status_code==200 and BotDelivery.objects.filter(account=a).count()==2
    assert BotDelivery.objects.filter(account=a).latest('created_at').idempotency_key==f'resend:{again.json()["id"]}:{delivery.artifact_id}'
    # Straight to the file: no chat.
    answer=submit(client,send(client,url,2),'chat-3')
    assert answer.status_code==200 and BotDelivery.objects.filter(account=a).count()==2


def test_a_quote_for_the_chat_goes_to_the_chat_without_being_asked_twice():
    a,asset,client,url=opened()
    assert save(client,url,1,[NOTE]).status_code==200
    answer=submit(client,send(client,url,2,'chat'),'chat-quote')
    assert answer.json()['origin_channel']=='mini_app' and BotDelivery.objects.filter(account=a).count()==1


def test_the_bot_keeps_its_own_deliveries_and_a_web_job_sends_nothing():
    a=account();asset=upload(a)
    job,_=submit_job(a,create_quote(a,'pdf.rotate',[str(asset.id)],{}).id,'origin-web')
    assert execute_job(job.id).status=='succeeded' and not BotDelivery.objects.filter(account=a).exists()
    job,_=submit_job(a,create_quote(a,'pdf.rotate',[str(asset.id)],{}).id,'origin-bot','bot')
    assert execute_job(job.id).status=='succeeded' and BotDelivery.objects.filter(account=a).count()==1


def test_the_chat_needs_a_linked_telegram():
    a,asset,client,url=opened()
    assert save(client,url,1,[NOTE]).status_code==200
    quoted=send(client,url,2)
    Account.objects.filter(pk=a.pk).update(telegram_user_id=None)
    assert refused(submit(client,quoted,'unlinked-1',deliver_to_chat=True))==(409,'telegram_link_required')
    assert refused(send(client,url,2,'chat'))==(409,'telegram_link_required')
    assert not Job.objects.filter(account=a).exists()
    assert submit(client,quoted,'unlinked-2').status_code==201,'the download path does not need it'


def test_deliver_to_chat_is_a_yes_or_a_no():
    a,asset,client,url=opened()
    assert save(client,url,1,[NOTE]).status_code==200
    assert refused(submit(client,send(client,url,2),'odd-chat',deliver_to_chat='yes'))==(400,'invalid_request')


def test_a_retry_of_the_same_submission_is_the_same_job():
    a,asset,client,url=opened()
    assert save(client,url,1,[NOTE]).status_code==200
    quoted=send(client,url,2)
    first=submit(client,quoted,'retry-1');second=submit(client,quoted,'retry-1')
    assert first.status_code==201 and second.status_code==200 and first.json()['id']==second.json()['id']
    assert Job.objects.filter(account=a).count()==1 and usage_snapshot(a)['file_jobs']['used']==1


@pytest.mark.django_db(transaction=True)
def test_a_send_that_fails_tells_the_chat(settings):
    settings.LOCAL_SYNC_JOBS=False
    a,asset,client,url=opened()
    assert save(client,url,1,[NOTE]).status_code==200
    job=Job.objects.get(pk=submit(client,send(client,url,2),'notice-1',deliver_to_chat=True).json()['id'])
    assert save(client,url,2,[NOTE,NOTE]).status_code==200
    job=execute_job(job.id)
    assert job.status=='failed' and job.origin_channel=='mini_app'
    notice=BotJobNotice.objects.get(job=job)
    bot=Mock(send_message=AsyncMock(return_value=Mock(message_id=9)))
    asyncio.run(attempt_notice(notice.id,bot))
    notice.refresh_from_db()
    assert notice.status=='delivered' and bot.send_message.await_count==1
    words=bot.send_message.await_args.args[1]
    assert COPY['en']['draft_changed'] in words and 'buttons' not in words
    assert not BotDelivery.objects.filter(account=a).exists()


def test_every_command_kind_and_the_editor_have_a_name_in_the_bot():
    from telegram.ux_copy import LOCALES,TOOL_NAMES
    assert set(TOOL_NAMES['editor.visual'])==set(LOCALES) and all(TOOL_NAMES['editor.visual'].values())


def test_result_assets_say_which_draft_made_them(monkeypatch):
    from processors.sandbox import execute_sandbox
    a=account();asset=upload(a)
    job,_=submit_job(a,create_quote(a,'pdf.rotate',[str(asset.id)],{}).id,'source-of-result')
    assert 'editor_document_id' not in execute_job(job.id).artifacts.get().file.metadata
    job,_=submit_job(a,create_quote(a,'pdf.rotate',[str(asset.id)],{}).id,'source-of-deck')
    Job.objects.filter(pk=job.pk).update(parameters={**job.parameters,'generation_draft_id':'some-draft'})
    monkeypatch.setattr('processors.sandbox.execute_sandbox',lambda feature,paths,parameters,out,**fields:execute_sandbox(feature,paths,{},out,**fields))
    assert execute_job(job.id).artifacts.get().file.metadata['generation_draft_id']=='some-draft'


def test_a_warning_row_in_numbers_never_reaches_the_bots_notes():
    from apps.core.serializers import job_notes,warning_codes
    job=Job(warnings=['a_code',{'per_command':[]},{'rasterized_pages':[2]}])
    assert warning_codes(job)==['a_code'] and job_notes(job)=={'per_command':[],'rasterized_pages':[2]}


def test_a_file_sent_again_lasts_as_long_as_one_just_made():
    a,asset,client,url=opened()
    job=sent(client,url,1,[NOTE],'kept-1')
    made=job.artifacts.get().file
    soon=timezone.now()+timedelta(minutes=5)
    FileAsset.objects.filter(pk__in=[made.pk,asset.pk]).update(expires_at=soon)
    quoted=send(client,url,2)
    assert quoted.json()['summary']['cost']['kind']=='none' and quoted.json()['summary']['kept_until']>(soon+timedelta(hours=23)).isoformat()
    assert FileAsset.objects.get(pk=made.pk).expires_at==soon,'a look at the cost moves nothing'
    assert submit(client,quoted,'kept-2').json()['id']==str(job.id)
    for row in FileAsset.objects.filter(pk__in=[made.pk,asset.pk]):assert row.expires_at>timezone.now()+timedelta(hours=23)
    # A chat's turn may come late: it finds the file too.
    FileAsset.objects.filter(pk=made.pk).update(expires_at=soon)
    assert submit(client,send(client,url,2,'chat'),'kept-3').status_code==200
    assert FileAsset.objects.get(pk=made.pk).expires_at>timezone.now()+timedelta(hours=23)


def test_one_quote_answered_with_a_file_already_made_is_one_send(monkeypatch):
    a,asset,client,url=opened()
    job=sent(client,url,1,[NOTE],'one-send-1')
    quoted=send(client,url,2,'chat')
    assert submit(client,quoted,'one-send-2').json()['id']==str(job.id) and BotDelivery.objects.filter(account=a).count()==1
    # The second tap, as a real job's quote would answer it.
    assert refused(submit(client,quoted,'one-send-3'))==(409,'quote_already_submitted') and BotDelivery.objects.filter(account=a).count()==1
    # The same request asked again, late: its answer was lost, not its send.
    Quote.objects.filter(pk=quoted.json()['id']).update(expires_at=timezone.now()-timedelta(hours=1))
    assert save(client,url,2,[NOTE,NOTE]).status_code==200
    def closed(_):raise DomainError('channels_required',403)
    monkeypatch.setattr('apps.core.channel_gate.require',closed)
    answer=submit(client,quoted,'one-send-2')
    assert answer.status_code==200 and answer.json()['id']==str(job.id) and BotDelivery.objects.filter(account=a).count()==1
    monkeypatch.undo()
    # That key is spent on that quote.
    other=send(client,url,3)
    assert refused(submit(client,other,'one-send-2'))==(409,'idempotency_conflict')


def test_a_download_answered_with_a_file_already_made_answers_the_same_again():
    a,asset,client,url=opened()
    job=sent(client,url,1,[NOTE],'late-1')
    quoted=send(client,url,2)
    assert submit(client,quoted,'late-2').status_code==200
    Quote.objects.filter(pk=quoted.json()['id']).update(expires_at=timezone.now()-timedelta(hours=1))
    answer=submit(client,quoted,'late-2')
    assert answer.status_code==200 and answer.json()['id']==str(job.id)
    assert refused(submit(client,quoted,'late-3'))==(409,'quote_already_submitted')


def test_a_second_tap_while_the_first_waits_is_the_same_job(settings):
    queued(settings)
    plan_settings.save('free',{'weekly_file_jobs':1})
    a,asset,client,url=opened()
    assert save(client,url,1,[NOTE]).status_code==200
    first=submit(client,send(client,url,2),'waiting-1')
    assert first.status_code==201
    again=send(client,url,2)
    assert again.status_code==201 and again.json()['summary']['cost']['kind']=='none' and again.json()['affordable'] is True
    second=submit(client,again,'waiting-2')
    assert second.status_code==200 and second.json()['id']==first.json()['id']
    assert Job.objects.filter(account=a).count()==1 and usage_snapshot(a)['file_jobs']['used']==1
    # The one that asks for the chat is heard: the job goes there when it is made, once.
    third=submit(client,send(client,url,2,'chat'),'waiting-3')
    assert third.status_code==200 and third.json()['id']==first.json()['id'] and third.json()['origin_channel']=='mini_app'
    assert not BotDelivery.objects.filter(account=a).exists()
    assert submit(client,send(client,url,2,'chat'),'waiting-4').json()['id']==first.json()['id']
    job=execute_job(first.json()['id'])
    assert job.status=='succeeded' and BotDelivery.objects.filter(account=a).count()==1
    assert BotDelivery.objects.get(account=a).idempotency_key==f'job:{job.id}:{job.artifacts.get().id}'


def test_a_job_being_settled_this_instant_is_not_asked_for_the_chat(settings,monkeypatch):
    from apps.studio import editor_domain
    queued(settings)
    a,asset,client,url=opened()
    assert save(client,url,1,[NOTE]).status_code==200
    first=submit(client,send(client,url,2),'settling-1')
    monkeypatch.setattr(editor_domain,'_send_when_made',lambda job:False)
    second=submit(client,send(client,url,2,'chat'),'settling-2')
    assert second.status_code==201 and second.json()['id']!=first.json()['id'] and second.json()['origin_channel']=='mini_app'


def test_a_job_of_an_older_save_cannot_answer_for_a_newer_one(settings):
    queued(settings)
    a,asset,client,url=opened()
    assert save(client,url,1,[NOTE]).status_code==200
    first=submit(client,send(client,url,2),'older-1')
    # The same marks, saved again: the waiting job will fail on the new version, so it answers nothing.
    assert save(client,url,2,[NOTE]).status_code==200
    second=submit(client,send(client,url,3),'older-2')
    assert second.status_code==201 and second.json()['id']!=first.json()['id']
    assert execute_job(first.json()['id']).error_code=='version_conflict' and execute_job(second.json()['id']).status=='succeeded'


def test_the_same_marks_saved_again_still_return_the_same_file():
    plan_settings.save('free',{'weekly_file_jobs':1})
    a,asset,client,url=opened()
    job=sent(client,url,1,[NOTE],'resave-1')
    # A mark added and taken back: the version moves and the encrypted copy differs, and what the draft holds does not.
    assert save(client,url,2,[NOTE,NOTE]).status_code==200 and save(client,url,3,[NOTE]).status_code==200
    quoted=send(client,url,4)
    assert quoted.json()['summary']['cost']['kind']=='none'
    assert quoted.json()['normalized_parameters']['snapshot']!=job.parameters['snapshot']
    assert submit(client,quoted,'resave-2').json()['id']==str(job.id) and Job.objects.filter(account=a).count()==1
    # Another word is another file, and the week has no room for it.
    assert save(client,url,4,[{**NOTE,'text':'Другая'}]).status_code==200
    assert refused(send(client,url,5))==(429,'weekly_file_limit')


def test_what_a_draft_holds_cannot_be_guessed_from_a_job_row():
    a,asset,client,url=opened()
    job=sent(client,url,1,[NOTE],'keyed-1')
    b,_,other_client,other_url=opened(account())
    other=sent(other_client,other_url,1,[NOTE],'keyed-2')
    assert job.parameters['content']!=other.parameters['content'],'tied to its draft'
    document=EditorDocument.objects.get(pk=job.parameters['editor_document_id'])
    plain=json.dumps([str(document.id),document.input_ids,document.commands],ensure_ascii=False,sort_keys=True)
    assert job.parameters['content']!=hashlib.sha256(plain.encode()).hexdigest()


def pointed_at_a_deck(monkeypatch):
    """A send of a generated deck: a file task pointing at its draft. Today's tools stand in for the export of the deck that follows them."""
    from apps.core.policy import POLICY_VERSION,plan_limits
    from apps.studio.domain import create_draft
    from processors.sandbox import execute_sandbox
    a=account();asset=upload(a)
    draft=create_draft(a,{'feature_id':'ai.pptx','source_text':'Something to say\n\nAnd more','output_format':'pptx','options':{'length':2}})
    monkeypatch.setattr('processors.sandbox.execute_sandbox',lambda feature,paths,parameters,out,**fields:execute_sandbox(feature,paths,{},out,**fields))
    def quoted(fmt='pptx'):
        return Quote.objects.create(account=a,feature_id='pdf.rotate',parameters={'generation_draft_id':str(draft.id),'version':draft.version,'snapshot':hashlib.sha256(bytes(draft.encrypted_data)).hexdigest(),'format':fmt,'deliver':'download'},input_ids=[str(asset.id)],input_fingerprints=[{'id':str(asset.id),'sha256':asset.sha256}],policy={'plan':a.plan,'version':POLICY_VERSION,'tariff_version':'file-v1','limits':plan_limits(a)},expires_at=timezone.now()+timedelta(minutes=10))
    return a,draft,quoted


def test_a_deck_sent_again_is_reused_and_braked_as_a_draft_of_marks_is(monkeypatch):
    from apps.core.allowance import require_quote
    from apps.studio import editor_domain
    from apps.studio.models import GenerationDraft
    plan_settings.save('free',{'weekly_file_jobs':1})
    a,draft,quoted=pointed_at_a_deck(monkeypatch)
    job,created=submit_job(a,quoted().id,'deck-send-1')
    assert created and execute_job(job.id).status=='succeeded' and usage_snapshot(a)['file_jobs']['used']==1
    # At the week's limit, the same deck again: nothing is made and nothing refused.
    again=quoted();require_quote(a,again)
    same,created=submit_job(a,again.id,'deck-send-2')
    assert same.id==job.id and not created and Job.objects.filter(account=a).count()==1
    # Sent to the chat it is a send, and held to the brake.
    plan_settings.save('free',{'weekly_file_jobs':5})
    monkeypatch.setattr(editor_domain,'SENDS_PER_DRAFT_PER_DAY',1)
    with pytest.raises(DomainError) as caught:submit_job(a,quoted().id,'deck-send-3','mini_app')
    assert caught.value.code=='send_limit' and not BotDelivery.objects.filter(account=a).exists()
    # So is one that would make a new file.
    with pytest.raises(DomainError) as caught:submit_job(a,quoted('pdf').id,'deck-send-4')
    assert caught.value.code=='send_limit'
    # A deck changed since the quote is not answered with the old file.
    stale=quoted()
    GenerationDraft.objects.filter(pk=draft.pk).update(version=draft.version+1)
    with pytest.raises(DomainError) as caught:submit_job(a,stale.id,'deck-send-5')
    assert caught.value.code=='version_conflict'


def test_an_ai_run_on_a_draft_is_not_a_send_of_it(monkeypatch):
    from apps.core.allowance import same_result
    from apps.studio import editor_domain
    a,draft,quoted=pointed_at_a_deck(monkeypatch)
    written,_=submit_job(a,quoted().id,'written-1')
    Job.objects.filter(pk=written.pk).update(feature_id='ai.pptx',status='succeeded')
    assert same_result(a,quoted()) is None,'what the AI wrote is not this file'
    monkeypatch.setattr(editor_domain,'SENDS_PER_DRAFT_PER_DAY',1)
    editor_domain.require_send_room(a,('generation_draft_id',str(draft.id)))


def test_a_list_of_drafts_holds_no_marks(monkeypatch):
    from apps.core.management.commands.export_contract import schema
    a,asset,client,url=opened()
    assert save(client,url,1,[NOTE]).status_code==200
    monkeypatch.setattr('apps.studio.views.stored_commands',lambda e:pytest.fail('a list decrypts nothing'))
    rows=client.get('/api/v1/editor/documents').json()['results']
    assert len(rows)==1 and 'commands' not in rows[0] and rows[0]['id']==url.rsplit('/',1)[1] and rows[0]['file']['id']==str(asset.id)
    contract=schema()
    jsonschema.Draft202012Validator({'$ref':'#/components/schemas/EditorDocumentRow','components':contract['components']}).validate(rows[0])
    monkeypatch.undo()
    assert client.get(url).json()['commands']==[NOTE],'the draft itself says'


def changed_while_waiting(settings,monkeypatch,telegram_id,**fields):
    """A linked account's send of a stored draft, which changed before its turn came. Returns the job, and what the bot says on opening it from /myfiles."""
    from apps.core.identity import resolve_account
    from apps.core.models import BotCallback,BotConversation
    from telegram.local import dispatch_local
    monkeypatch.setattr('telegram.verification.enabled',lambda:False)
    settings.LOCAL_SYNC_JOBS=False;settings.COMMERCE_SANDBOX_ENABLED=True
    a,asset,client,url=opened(resolve_account({'id':telegram_id,'first_name':'Details test'},is_test=True))
    BotConversation.objects.create(telegram_user_id=a.telegram_user_id,locale='en',language_selected_at=timezone.now())
    assert save(client,url,1,[NOTE]).status_code==200
    job=Job.objects.get(pk=submit(client,send(client,url,2),'details-1',**fields).json()['id'])
    assert save(client,url,2,[NOTE,NOTE]).status_code==200
    job=execute_job(job.id)
    listing=dispatch_local(a,text='/myfiles')
    token=next(button['callback_data'] for message in listing['messages'] for row in message['buttons'] for button in row if button.get('callback_data') and BotCallback.objects.filter(pk=button['callback_data'],action='job').exists())
    return job,json.dumps(dispatch_local(a,callback_data=token),ensure_ascii=False,default=str)


@pytest.mark.django_db(transaction=True)
def test_the_details_of_a_send_that_changed_say_what_its_notice_said(settings,monkeypatch):
    from telegram.errors import bot_error
    from telegram.notifications import failure_line
    job,said=changed_while_waiting(settings,monkeypatch,980477,deliver_to_chat=True)
    assert job.error_code=='version_conflict' and failure_line(job,'en')==COPY['en']['draft_changed'] and failure_line(job,'de')==COPY['en']['draft_changed']
    assert COPY['en']['draft_changed'] in said and bot_error(DomainError('version_conflict'),'en') not in said
    # A job the bot made holds no draft and keeps the bot's own wording, and other failures theirs.
    Job.objects.filter(pk=job.pk).update(parameters={key:value for key,value in job.parameters.items() if key!='editor_document_id'});job.refresh_from_db()
    assert failure_line(job,'en')==bot_error(DomainError('version_conflict'),'en')
    Job.objects.filter(pk=job.pk).update(parameters={'editor_document_id':'x'},error_code='processing_failed');job.refresh_from_db()
    assert failure_line(job,'en')==bot_error(DomainError('processing_failed'),'en')


@pytest.mark.django_db(transaction=True)
def test_the_details_of_a_download_that_changed_say_the_file_changed_too(settings,monkeypatch):
    from telegram.errors import bot_error
    job,said=changed_while_waiting(settings,monkeypatch,980478)
    assert job.origin_channel=='web' and job.error_code=='version_conflict'
    assert COPY['en']['draft_changed'] in said and bot_error(DomainError('version_conflict'),'en') not in said
