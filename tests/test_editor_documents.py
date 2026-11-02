"""How large an editor draft may be: one unit from the web's meter through saving, the quote and the sandbox."""
import io
import json
import re
import uuid
from datetime import timedelta
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image
from pypdf import PdfReader,PdfWriter
from apps.core.errors import DomainError
from apps.core.models import FileAsset,Job
from apps.core.policy import EDITOR_LIMITS,EDITOR_PARAMETER_BYTES,PARAMETER_BYTES,payload_bytes
from apps.core.services import cleanup_expired,create_quote,storage_path,upload_file
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


def test_new_kinds_save_but_the_old_worker_refuses_them_whole():
    a,asset,client,url=opened()
    commands=[NOTE,{'type':'rotate_page','page':1,'angle':90}]
    assert save(client,url,1,commands).status_code==200
    job=run(client,quote(client,url,2),'editor-new-kind-1')
    assert job.status=='failed' and job.error_code=='invalid_editor_command'


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


def test_a_refusal_of_the_whole_draft_names_no_change():
    a,asset,client,url=opened()
    answer=save(client,url,1,[{'type':'redact','page':1,'x':1,'y':1,'width':5,'height':5},NOTE])
    assert refused(answer)==(400,'redaction_requires_separate_export') and answer.json()['error']['message_params']=={}


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

