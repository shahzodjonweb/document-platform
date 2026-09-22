import io
from datetime import timedelta
from pathlib import Path
import pytest
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone
from pypdf import PdfReader,PdfWriter
from apps.core.identity import resolve_account
from apps.core.models import FileAsset,Job,PagePreview,SecretHandle,UsageLedger
from apps.core.services import storage_path,cleanup_expired
from processors.engine import office_runtime

pytestmark=pytest.mark.django_db

def principal(uid=110001):
    a=resolve_account({'id':uid,'first_name':'Preview fixture'},is_test=True)
    c=Client();session=c.session;session['customer_account_id']=str(a.id);session.save();return a,c

def pdf(password=None):
    writer=PdfWriter();writer.add_blank_page(width=210,height=420);writer.add_blank_page(width=420,height=210)
    if password: writer.encrypt(password,algorithm='AES-256')
    stream=io.BytesIO();writer.write(stream);return stream.getvalue()

def upload(client,data=None,password=None,name='preview.pdf'):
    values={'file':SimpleUploadedFile(name,data or pdf())}
    if password: values['password']=password
    response=client.post('/api/v1/files/uploads',values)
    assert response.status_code==201,response.content
    return response.json()

def content(response): return b''.join(response.streaming_content)

def test_preview_is_real_png_cached_owner_scoped_and_free():
    owner,c=principal();asset=upload(c)
    for _ in range(2):
        response=c.get(f'/api/v1/files/{asset["id"]}/preview?page=2')
        assert response.status_code==200
        assert response['Content-Type']=='image/png'
        image=Image.open(io.BytesIO(content(response)));assert image.width>image.height
    assert PagePreview.objects.count()==1
    assert UsageLedger.objects.count()==Job.objects.count()==0
    _,other=principal(110002)
    assert other.get(f'/api/v1/files/{asset["id"]}/preview').status_code==404
    assert c.get(f'/api/v1/files/{asset["id"]}/preview?page=0').status_code==400
    assert c.get(f'/api/v1/files/{asset["id"]}/preview?page=3').status_code==400
    assert c.get(f'/api/v1/files/{asset["id"]}/preview?page=../../etc/passwd').status_code==400


def test_source_deletion_revokes_and_removes_cached_preview():
    a,c=principal();asset=upload(c)
    content(c.get(f'/api/v1/files/{asset["id"]}/preview'))
    preview=PagePreview.objects.get().file
    assert storage_path(preview.object_key).exists()
    assert c.delete(f'/api/v1/files/{asset["id"]}').status_code==200
    assert not storage_path(preview.object_key).exists()
    assert c.get(f'/api/v1/files/{asset["id"]}/preview').status_code==410


def test_encrypted_preview_requires_live_handle_even_after_cache():
    a,c=principal();password='private-preview-secret'
    asset=upload(c,pdf(password),password)
    response=c.get(f'/api/v1/files/{asset["id"]}/preview')
    assert response.status_code==200,response.content if not response.streaming else ''
    Image.open(io.BytesIO(content(response))).verify()
    preview=PagePreview.objects.get().file;handle=SecretHandle.objects.get()
    assert preview.expires_at<=handle.expires_at
    SecretHandle.objects.filter(pk=handle.id).update(expires_at=timezone.now()-timedelta(seconds=1))
    assert c.get(f'/api/v1/files/{asset["id"]}/preview').status_code==409
    assert UsageLedger.objects.count()==0


def test_expired_preview_not_recoverable_and_cleanup_removes_binary():
    a,c=principal();asset=upload(c);content(c.get(f'/api/v1/files/{asset["id"]}/preview'))
    preview=PagePreview.objects.get().file
    FileAsset.objects.filter(account=a).update(expires_at=timezone.now()-timedelta(seconds=1))
    assert c.get(f'/api/v1/files/{asset["id"]}/preview').status_code==410
    cleanup_expired();assert not storage_path(preview.object_key).exists()


@pytest.mark.skipif(not office_runtime()['available'],reason='Qualified local LibreOffice runtime unavailable')
@pytest.mark.parametrize(('extension','feature'),[('docx','convert.word_to_pdf'),('pptx','convert.pptx_to_pdf')])
def test_office_upload_exact_preflight_quote_execute_and_download(extension,feature):
    a,c=principal()
    fixture=Path(__file__).resolve().parents[1]/'processors'/'fixtures'/f'office-multilingual.{extension}'
    asset=upload(c,fixture.read_bytes(),name=fixture.name)
    assert asset['page_count']==3
    model=FileAsset.objects.get(pk=asset['id'])
    assert model.metadata['preflight_kind']=='libreoffice_pdf'
    response=c.post('/api/v1/quotes',{'feature_id':feature,'input_ids':[asset['id']]},content_type='application/json')
    assert response.status_code==201,response.content
    quote=response.json();assert {v['meter']:v['amount'] for v in quote['meters']}=={'file_tasks':1,'file_page_units':3}
    result=c.post('/api/v1/jobs',{'quote_id':quote['id']},content_type='application/json',HTTP_IDEMPOTENCY_KEY=f'office-api-{extension}')
    assert result.status_code==201,result.content
    job=result.json();assert job['status']=='succeeded',job
    output=c.get(job['artifacts'][0]['download_url']);reader=PdfReader(io.BytesIO(content(output)))
    assert len(reader.pages)==3
    extracted='\n'.join(page.extract_text() or '' for page in reader.pages)
    assert 'Document pages remain readable' in extracted and 'Hujjat sahifalari aniq ko‘rinadi' in extracted and 'Страницы документа остаются читаемыми' in extracted
    assert UsageLedger.objects.filter(job_id=job['id'],kind='consume',meter='file_page_units').get().amount==3


def test_office_quote_rejects_incorrect_input_kind_before_reserving():
    _,c=principal();asset=upload(c)
    response=c.post('/api/v1/quotes',{'feature_id':'convert.word_to_pdf','input_ids':[asset['id']]},content_type='application/json')
    assert response.status_code==400,response.content
    assert response.json()['error']['code']=='unsupported_file'
    assert UsageLedger.objects.count()==0
