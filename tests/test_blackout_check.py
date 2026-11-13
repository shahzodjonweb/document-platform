"""Checking a draft's black-out before a send, so the send asks consent for exactly the pages that become pictures.

The pages are made up and drawn by the tests (tests/test_blackout.py). The tests
marked REQUIRES_PDFCRAFT run the real binary; the rest see a missing one, which
answers every page as a picture.
"""
import json
import os
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from apps.core.models import Job,Quote
from apps.core.services import upload_file
from apps.studio import editor_blackout
from apps.studio.domain import pack,unpack
from apps.studio.models import EditorDocument,EditorTask
from processors import ProcessorError
from tests.test_blackout import BORDER,DRAWN,FOUND,PHONE,REQUIRES_PDFCRAFT,box,sheet
from tests.test_editor_documents import refused,run,save,send
from tests.test_platform import account,login_client

pytestmark=pytest.mark.django_db


@pytest.fixture(autouse=True)
def local(settings):
    settings.DEBUG=True;settings.ENABLE_BETA_TOOLS=True;settings.LOCAL_SYNC_JOBS=True


@pytest.fixture
def switched(monkeypatch):
    monkeypatch.setenv('EDITOR_FLAG_PDFCRAFT','1');monkeypatch.setenv('EDITOR_FLAG_VECTOR_BLACKOUT','1')


def opened(tmp_path,pages=2,table=True,a=None):
    a=a or account();client=login_client(a)
    asset=upload_file(a,SimpleUploadedFile('sheet.pdf',sheet(tmp_path/'sheet.pdf',pages=pages,table=table).read_bytes(),'application/pdf'))
    created=client.post('/api/v1/editor/documents',{'file_id':str(asset.id)},content_type='application/json')
    assert created.status_code==201,created.content
    return a,asset,client,'/api/v1/editor/documents/'+created.json()['id']


def check(client,url,method='post'):
    answer=getattr(client,method)(url+'/blackout-check')
    assert answer.status_code in (200,202),answer.content
    return answer.json()


def outcomes(answer):
    return {row['page']:row['reason'] for row in answer['pages']}


def test_with_the_switch_off_every_page_with_a_box_becomes_a_picture_and_nothing_is_queued(tmp_path):
    a,asset,client,url=opened(tmp_path)
    assert save(client,url,1,[box(1,**FOUND),box(2,**BORDER)]).status_code==200
    answer=check(client,url)
    assert answer['status']=='done' and answer['pages']==[{'page':1,'keeps_text':False,'reason':'engine'},{'page':2,'keeps_text':False,'reason':'engine'}]
    assert not EditorTask.objects.exists()
    quoted=send(client,url,2)
    assert refused(quoted)==(400,'rasterization_consent_required') and quoted.json()['error']['message_params']=={'pages':[1,2]}


def test_a_check_without_pdfcraft_answers_every_page_as_a_picture(tmp_path,switched,monkeypatch):
    monkeypatch.delenv('DOCMASTER_PDFCRAFT_BIN',raising=False)
    a,asset,client,url=opened(tmp_path)
    assert save(client,url,1,[box(1,**FOUND)]).status_code==200
    assert check(client,url,'get')=={'status':'none','version':2,'pages':[],'error':None},'nothing asked yet'
    answer=check(client,url)
    assert answer['status']=='done' and outcomes(answer)=={1:'engine'}
    task=EditorTask.objects.get()
    assert task.kind=='text_check' and task.action=='blackout' and task.status=='done' and task.document_id is not None
    e=EditorDocument.objects.get()
    assert e.inspection_sha256==asset.sha256 and PHONE not in json.dumps(unpack(e.encrypted_inspection)),'kept by keyed hashes, never the words'
    assert check(client,url)['status']=='done' and EditorTask.objects.count()==1,'a page known is not checked again'


@REQUIRES_PDFCRAFT
def test_consent_is_asked_for_the_page_that_becomes_a_picture_and_no_other(tmp_path,switched):
    a,asset,client,url=opened(tmp_path)
    assert save(client,url,1,[box(1,**FOUND),box(2,**BORDER)]).status_code==200
    # Before a check nothing is known: every page with a box is asked for.
    assert send(client,url,2).json()['error']['message_params']=={'pages':[1,2]}
    answer=check(client,url)
    assert answer['status']=='done' and answer['pages']==[{'page':1,'keeps_text':True,'reason':'vector'},{'page':2,'keeps_text':False,'reason':'others'}]
    quoted=send(client,url,2)
    assert refused(quoted)==(400,'rasterization_consent_required') and quoted.json()['error']['message_params']=={'pages':[2]}
    quoted=send(client,url,2,accept_rasterization=True)
    assert quoted.status_code==201 and quoted.json()['summary']['raster_pages']==[2]
    assert Quote.objects.get(pk=quoted.json()['id']).parameters['raster_pages']==[2]
    job=run(client,quoted,'blackout-consent')
    assert job.status=='succeeded',job.error_code
    assert {'rasterized_pages':[2]} in job.warnings and {'per_command':[{'index':0,'status':'applied','engine':'pdfcraft'},{'index':1,'status':'applied','engine':'pdfium'}]} in job.warnings


@REQUIRES_PDFCRAFT
def test_a_draft_whose_every_page_keeps_its_words_is_sent_without_asking(tmp_path,switched):
    a,asset,client,url=opened(tmp_path,table=False)
    assert save(client,url,1,[box(1,**FOUND),box(2,**DRAWN)]).status_code==200
    assert outcomes(check(client,url))=={1:'vector',2:'vector'}
    quoted=send(client,url,2)
    assert quoted.status_code==201 and quoted.json()['summary']['raster_pages']==[]
    job=run(client,quoted,'blackout-no-consent')
    assert job.status=='succeeded' and {'rasterized_pages':[]} in job.warnings


def test_a_box_moved_is_not_known_until_checked_again(tmp_path,switched,monkeypatch):
    monkeypatch.delenv('DOCMASTER_PDFCRAFT_BIN',raising=False)
    a,asset,client,url=opened(tmp_path)
    assert save(client,url,1,[box(1,**DRAWN)]).status_code==200
    assert check(client,url)['status']=='done'
    assert save(client,url,2,[box(1,**{**DRAWN,'x':DRAWN['x']+5})]).status_code==200
    assert check(client,url,'get')['status']=='none'
    assert check(client,url)['status']=='done' and EditorTask.objects.count()==2


def test_a_box_under_another_change_is_a_picture_without_a_check(tmp_path,switched):
    a,asset,client,url=opened(tmp_path)
    over={'type':'add_text','page':1,'x':110,'y':118,'text':'over it','font_size':12}
    assert save(client,url,1,[box(1,**DRAWN),over]).status_code==200
    assert check(client,url,'get')=={'status':'done','version':2,'pages':[{'page':1,'keeps_text':False,'reason':'mark'}],'error':None}
    assert not EditorTask.objects.exists()


def test_a_page_known_to_keep_its_words_that_does_not_at_the_send_fails_it_and_nothing_is_counted(tmp_path,switched,monkeypatch):
    monkeypatch.delenv('DOCMASTER_PDFCRAFT_BIN',raising=False)
    a,asset,client,url=opened(tmp_path)
    assert save(client,url,1,[box(1,**FOUND)]).status_code==200
    e=EditorDocument.objects.get()
    # As a check found it, and the send cannot: PdfCraft gone since.
    from apps.studio.editor_blackout import _key
    from processors.blackout import boxes
    commands=[box(1,**FOUND)]
    editor_blackout._remember(e,{_key(asset,1,boxes(commands)[1]):'vector'})
    quoted=send(client,url,2)
    assert quoted.status_code==201 and quoted.json()['summary']['raster_pages']==[]
    job=run(client,quoted,'blackout-late')
    assert job.status=='failed' and job.error_code=='rasterization_consent_required' and {'failed_command':0} in job.warnings
    from apps.core.allowance import file_jobs_this_week
    assert file_jobs_this_week(a)==0
    # Known now: the next quote asks about that page, and the send with consent goes.
    assert outcomes(check(client,url,'get'))=={1:'refused'}
    quoted=send(client,url,2)
    assert refused(quoted)==(400,'rasterization_consent_required') and quoted.json()['error']['message_params']=={'pages':[1]}
    assert run(client,send(client,url,2,accept_rasterization=True),'blackout-late-2').status=='succeeded'


def test_a_check_that_fails_says_so_until_the_draft_changes(tmp_path,switched,monkeypatch):
    def broken(*args,**kwargs):raise ProcessorError('invalid_pdf')
    monkeypatch.setattr('processors.sandbox.helper_sandbox',broken)
    a,asset,client,url=opened(tmp_path)
    assert save(client,url,1,[box(1,**DRAWN)]).status_code==200
    answer=check(client,url)
    assert answer['status']=='failed' and answer['error']=='invalid_pdf' and answer['pages']==[]
    assert save(client,url,2,[box(1,**FOUND)]).status_code==200
    assert check(client,url,'get')['status']=='none'


def test_a_check_the_child_gave_up_on_answers_its_pages_as_pictures(tmp_path,switched,monkeypatch):
    def slow(*args,**kwargs):raise ProcessorError('processor_timeout')
    monkeypatch.setattr('processors.sandbox.helper_sandbox',slow)
    a,asset,client,url=opened(tmp_path)
    assert save(client,url,1,[box(1,**DRAWN),box(2,**DRAWN)]).status_code==200
    assert outcomes(check(client,url))=={1:'refused',2:'refused'}
    assert check(client,url)['status']=='done' and EditorTask.objects.count()==1,'not tried again'


def test_another_accounts_draft_cannot_be_checked(tmp_path,switched):
    a,asset,client,url=opened(tmp_path)
    other=login_client(account(77))
    assert other.post(url+'/blackout-check').status_code==404 and other.get(url+'/blackout-check').status_code==404


def test_answers_for_another_file_are_not_read(tmp_path,switched,monkeypatch):
    monkeypatch.delenv('DOCMASTER_PDFCRAFT_BIN',raising=False)
    a,asset,client,url=opened(tmp_path)
    assert save(client,url,1,[box(1,**DRAWN)]).status_code==200
    assert check(client,url)['status']=='done'
    EditorDocument.objects.update(inspection_sha256='0'*64)
    assert check(client,url,'get')['status']=='none'


def test_a_draft_keeps_its_newest_answers(tmp_path,switched,monkeypatch):
    monkeypatch.setattr(editor_blackout,'KEPT',3)
    a,asset,client,url=opened(tmp_path)
    e=EditorDocument.objects.get()
    for number in range(5):editor_blackout._remember(e,{f'key-{number}':'vector'})
    e.refresh_from_db()
    assert list(unpack(e.encrypted_inspection)['blackout'])==['key-2','key-3','key-4']


@REQUIRES_PDFCRAFT
def test_with_pdfcraft_on_and_its_own_switch_off_a_send_makes_the_quoted_pages_pictures(tmp_path,monkeypatch):
    monkeypatch.setenv('EDITOR_FLAG_PDFCRAFT','1')
    a,asset,client,url=opened(tmp_path,table=False)
    assert save(client,url,1,[box(1,**FOUND)]).status_code==200
    assert send(client,url,2).json()['error']['message_params']=={'pages':[1]}
    job=run(client,send(client,url,2,accept_rasterization=True),'blackout-switch-off')
    assert job.status=='succeeded' and {'rasterized_pages':[1]} in job.warnings,'as the quote said: a picture'
    assert {'per_command':[{'index':0,'status':'applied','engine':'pdfium'}]} in job.warnings


def test_a_page_refused_at_a_send_has_the_others_checked_again_with_it(tmp_path,switched,monkeypatch):
    monkeypatch.delenv('DOCMASTER_PDFCRAFT_BIN',raising=False)
    a,asset,client,url=opened(tmp_path)
    commands=[box(1,**FOUND),box(2,**DRAWN)]
    assert save(client,url,1,commands).status_code==200
    from apps.studio.editor_blackout import _key
    from processors.blackout import boxes
    e=EditorDocument.objects.get();found=boxes(commands)
    editor_blackout._remember(e,{_key(asset,page,rows):'vector' for page,rows in found.items()})
    job=run(client,send(client,url,2),'blackout-refused-both')
    assert job.status=='failed' and job.error_code=='rasterization_consent_required'
    answer=check(client,url,'get')
    assert answer['status']=='none' and outcomes(answer)=={1:'refused'},'the other page is not known any more'
    assert send(client,url,2).json()['error']['message_params']=={'pages':[1,2]}


def test_one_page_not_known_has_every_page_with_a_box_checked_with_it(tmp_path,switched,monkeypatch):
    monkeypatch.delenv('DOCMASTER_PDFCRAFT_BIN',raising=False)
    asked=[]
    from processors import sandbox
    real=sandbox.helper_sandbox
    monkeypatch.setattr(sandbox,'helper_sandbox',lambda name,paths,parameters,out,**kwargs:asked.append(sorted({c['page'] for c in parameters['commands']})) or real(name,paths,parameters,out,**kwargs))
    a,asset,client,url=opened(tmp_path)
    assert save(client,url,1,[box(1,**DRAWN)]).status_code==200
    assert check(client,url)['status']=='done'
    assert save(client,url,2,[box(1,**DRAWN),box(2,**DRAWN)]).status_code==200
    assert check(client,url)['status']=='done'
    assert asked==[[1],[1,2]],'page 1 again, beside page 2, as a send runs them'
