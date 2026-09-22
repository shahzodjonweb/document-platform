"""The confirmed quote binds actual private bytes, including valid replacements."""
import os
import pytest
from pypdf import PdfReader
from apps.core.models import UsageLedger, OutboxEvent
from apps.core.policy import usage_snapshot
from apps.core.services import create_quote,submit_job,execute_job,storage_path
from tests.test_platform import account,upload,pdf_bytes

pytestmark=pytest.mark.django_db


@pytest.fixture(autouse=True)
def local(settings):
    settings.DEBUG=True


def pending_job():
    owner=account();asset=upload(owner)
    quote=create_quote(owner,'pdf.rotate',[str(asset.id)],{'angle':90})
    job,_=submit_job(owner,quote.id,'actual-byte-integrity')
    return owner,asset,job


def assert_uncharged_failure(owner,job):
    done=execute_job(job.id)
    assert done.status=='failed' and done.error_code=='file_changed'
    assert not done.artifacts.exists()
    assert not UsageLedger.objects.filter(job=job,kind='consume').exists()
    assert usage_snapshot(owner)['meters']['file_tasks']['reserved']==0
    assert OutboxEvent.objects.get(job=job).delivered_at
    execute_job(job.id)
    assert UsageLedger.objects.filter(job=job,kind='release',meter='file_tasks').count()==1


def test_different_valid_pdf_of_same_length_never_reaches_engine(monkeypatch):
    owner,asset,job=pending_job()
    replacement=pdf_bytes((201,300))
    assert len(replacement)==asset.size_bytes
    path=storage_path(asset.object_key);path.write_bytes(replacement)
    assert float(PdfReader(path).pages[0].mediabox.width)==201
    calls=[]
    monkeypatch.setattr('processors.sandbox.execute_sandbox',lambda *a,**kw:calls.append(a))
    assert_uncharged_failure(owner,job)
    assert calls==[]


def test_changed_database_fingerprint_cannot_replace_confirmed_quote():
    import hashlib
    owner,asset,job=pending_job();replacement=pdf_bytes((205,300))
    storage_path(asset.object_key).write_bytes(replacement)
    asset.sha256=hashlib.sha256(replacement).hexdigest();asset.save(update_fields=['sha256'])
    assert_uncharged_failure(owner,job)


def test_oversized_sparse_replacement_rejected_without_reading(monkeypatch):
    owner,asset,job=pending_job();path=storage_path(asset.object_key)
    with path.open('wb') as target:target.truncate(1024*1024*1024)
    original_fdopen=os.fdopen
    class NoRead:
        def __init__(self,*args,**kwargs):self.inner=original_fdopen(*args,**kwargs)
        def __enter__(self):return self
        def __exit__(self,*args):self.inner.close()
        def fileno(self):return self.inner.fileno()
        def read(self,*args):raise AssertionError('An oversized replacement must not be read')
    monkeypatch.setattr('apps.core.services.os.fdopen',NoRead)
    assert_uncharged_failure(owner,job)


@pytest.mark.skipif(not hasattr(os,'mkfifo'),reason='POSIX pipe fixture')
def test_replaced_pipe_fails_without_blocking_or_charging():
    owner,asset,job=pending_job();path=storage_path(asset.object_key)
    path.unlink();os.mkfifo(path,0o600)
    assert_uncharged_failure(owner,job)


def test_generation_source_change_fails_before_provider(settings,monkeypatch):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from apps.core.services import upload_file
    from apps.studio.domain import create_draft,generation_quote
    from apps.studio import provider
    from tests.test_studio import paid
    from operations.integrations import save_config
    from reportlab.pdfgen.canvas import Canvas
    import io
    owner=paid(settings,account());raw=io.BytesIO();canvas=Canvas(raw)
    canvas.drawString(20,750,'Source evidence');canvas.save()
    asset=upload_file(owner,SimpleUploadedFile('evidence.pdf',raw.getvalue(),'application/pdf'))
    save_config('ai',{'mode':'openai','model':'test-model','api_key':'offline-fixture'})
    draft=create_draft(owner,{'feature_id':'ai.pdf_text','source_ids':[str(asset.id)],'options':{'length':1}})
    quote=generation_quote(owner,draft.id,draft.version)
    job,_=submit_job(owner,quote.id,'source-mutation')
    storage_path(asset.object_key).write_bytes(pdf_bytes())
    calls=[];monkeypatch.setattr(provider,'generate',lambda *a,**kw:calls.append(a))
    done=execute_job(job.id)
    assert done.status=='failed' and done.error_code=='file_changed' and calls==[]
    assert not UsageLedger.objects.filter(job=job,kind='consume').exists()
    assert usage_snapshot(owner)['meters']['ai_credits']['reserved']==0
