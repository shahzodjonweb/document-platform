"""Which pages of a stored draft keep their words when blacked out, found before a send so it asks consent for exactly the others.

A check (POST …/blackout-check) is a `text_check` task of the editor lane with the
action `blackout` (tasks.py): in the bounded child it does what a send's black-out
stage does, on the draft's file, and says for each page with a box whether PdfCraft
blacked it out keeping its words, or why the page would become a picture
(processors/blackout.py). Each answer is kept in the draft's inspection, keyed by
what decides it: the file's bytes, the page, its boxes, and the rules and PdfCraft
of the day. So a box moved and moved back is not checked twice, and an answer
never stands for boxes it was not given.

The quote reads them: a page with a box becomes a picture unless its answer says it
keeps its words and no other change of the send is drawn over its boxes
(blackout.marked), which the send's own changes say without a check. The send
blacks out again and makes a page a picture only with consent to that page
(processors/editor._consented). An answer that never came, or has gone, only makes
the quote ask about more pages than the send needs.

With the `vector_blackout` or `pdfcraft` switch off every page with a box becomes a
picture, as before this check: nothing is queued for it.
"""
import hashlib
import json
import tempfile
from pathlib import Path
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac
from apps.core import storage
from apps.core.errors import DomainError
from apps.core.services import storage_path
from processors import ProcessorError
from .domain import pack,unpack
from .editor_policy import stored_commands
from .models import EditorDocument,EditorTask

ACTION='blackout'
# Answers a draft keeps, the newest: past this many boxes a draft has had, the oldest go.
KEPT=400
# One check's child: PdfCraft has blackout.BUDGET of it, the renders and reading the rest.
CHECK_SECONDS=60
# What the child says when it gave up on a file: its pages are answered as PdfCraft refused them, never tried again.
GIVEN_UP={'processor_timeout','processor_failed','processor_report_limit'}


def switched():
    from operations.integrations import editor_config
    config=editor_config()
    return config['pdfcraft'] and config['vector_blackout']


def _key(asset,page,rows):
    """What decides a page's answer, keyed: a box's words are the customer's, and a short number could be guessed back from a plain hash."""
    from processors.blackout import VERSION
    from processors.pdfcraft import version
    placed=sorted([round(c['x'],3),round(c['y'],3),round(c['width'],3),round(c['height'],3),c.get('text','')] for _,c in rows)
    return salted_hmac('editor.blackout',json.dumps([asset.sha256,page,placed,VERSION,version()],ensure_ascii=False),algorithm='sha256').hexdigest()


def _known(e):
    """The answers kept for the draft's file; none for a file it no longer points at."""
    if e.encrypted_inspection is None or e.inspection_sha256!=e.file.sha256:return {}
    return unpack(e.encrypted_inspection).get('blackout',{})


def outcomes(e,commands,asset):
    """{page: 'vector', the reason it becomes a picture, or None when it is not known yet} for each page with a box."""
    from processors.blackout import boxes,marked
    found=boxes(commands)
    if not found:return {}
    if not switched():return dict.fromkeys(found,'engine')
    known=_known(e);over=marked(commands)
    return {page:'mark' if page in over else known.get(_key(asset,page,rows)) for page,rows in found.items()}


def raster_pages(e,commands,asset):
    """The pages a send asks consent for: every page with a box not known to keep its words."""
    return sorted(page for page,outcome in outcomes(e,commands,asset).items() if outcome!='vector')


def _remember(e,answers):
    """Answers kept with the draft, under its lock, the newest last."""
    with transaction.atomic():
        row=EditorDocument.objects.select_for_update().select_related('file').filter(pk=e.pk).first()
        if row is None:return
        same=row.encrypted_inspection is not None and row.inspection_sha256==row.file.sha256
        data=unpack(row.encrypted_inspection) if same else {}
        known=data.get('blackout',{})
        for key,outcome in answers.items():
            known.pop(key,None);known[key]=outcome
        data['blackout']=dict(list(known.items())[-KEPT:])
        row.encrypted_inspection=pack(data);row.inspection_sha256=row.file.sha256
        row.save(update_fields=['encrypted_inspection','inspection_sha256'])


def _document(account,pk):
    from .editor_domain import file_gone,normalized_commands
    from apps.core.services import validate_inputs
    e=EditorDocument.objects.select_related('file').filter(account=account,id=pk).first()
    if not e:raise DomainError('not_found',404)
    if e.file.state!='ready' or e.file.expires_at<=timezone.now():raise file_gone(e.file)
    assets=validate_inputs(account,'editor.visual',e.input_ids)
    if any(a.metadata.get('encrypted') for a in assets):raise DomainError('unlock_first')
    commands=stored_commands(e)
    return e,normalized_commands(commands,assets) if commands else [],assets[0]


def _state(e,commands,asset):
    from .tasks import FAILED,HISTORY,WAITING
    found=outcomes(e,commands,asset)
    pages=[{'page':page,'keeps_text':outcome=='vector','reason':outcome} for page,outcome in sorted(found.items()) if outcome is not None]
    answer={'status':'done','version':e.version,'pages':pages,'error':None}
    if all(outcome is not None for outcome in found.values()):return answer
    rows=list(EditorTask.objects.filter(document=e,kind='text_check',action=ACTION).order_by('-created_at')[:HISTORY])
    waiting=next((row for row in rows if row.status in WAITING),None)
    if waiting is not None:return {**answer,'status':waiting.status}
    # A check that failed since the draft last changed says so; one before it is not about these boxes.
    failed=rows[0] if rows and rows[0].status==FAILED and (e.updated_at is None or rows[0].created_at>=e.updated_at) else None
    if failed is not None:return {**answer,'status':'failed','error':failed.error or 'editor_task_failed'}
    return {**answer,'status':'none'}


def state(account,pk):
    """How the draft's pages stand, as GET …/blackout-check says: `done` when every page with a box has its answer."""
    e,commands,asset=_document(account,pk)
    return _state(e,commands,asset)


def ask(account,pk):
    """POST …/blackout-check: the answers when all are known, else a check queued for the pages not known (or the one already waiting)."""
    from .tasks import TEXT_CHECK,WAITING,enqueue
    e,commands,asset=_document(account,pk)
    answer=_state(e,commands,asset)
    if answer['status'] in ('done',*WAITING):return answer
    enqueue(account,TEXT_CHECK,{'version':e.version},document=e,action=ACTION)
    e.refresh_from_db()
    return _state(e,commands,asset)


def run(row):
    """The task: the draft's pages with a box not known yet, checked in the bounded child as they stand now, and their answers kept."""
    from processors.blackout import boxes
    from processors.sandbox import helper_sandbox
    e=EditorDocument.objects.select_related('file').filter(pk=row.document_id,account=row.account).first()
    if e is None:raise DomainError('not_found',404)
    e,commands,asset=_document(row.account,e.pk)
    if not switched():return {'checked':0}
    known=_known(e);todo={page:rows for page,rows in boxes(commands).items() if _key(asset,page,rows) not in known}
    if not todo:return {'checked':0}
    path=storage.local(asset.object_key)
    if not path.is_file():raise DomainError('file_unavailable',404)
    # The answer is kept for these bytes: a file that is not them is not checked.
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1<<20),b''):digest.update(block)
    if digest.hexdigest()!=asset.sha256:raise DomainError('file_unavailable',404)
    scratch=storage_path('scratch');scratch.mkdir(parents=True,exist_ok=True,mode=0o700)
    with tempfile.TemporaryDirectory(prefix='blackout-',dir=scratch) as folder:
        try:
            said=helper_sandbox('editor.blackout',[path],{'commands':[command for rows in todo.values() for _,command in rows]},Path(folder)/'out',timeout=CHECK_SECONDS,pdfcraft=True)['pages']
        except ProcessorError as error:
            if error.code not in GIVEN_UP:raise DomainError(error.code) from None
            said={str(page):'refused' for page in todo}
    answers={_key(asset,page,rows):said[str(page)] for page,rows in todo.items() if isinstance(said.get(str(page)),str)}
    _remember(e,answers)
    return {'checked':len(answers)}
