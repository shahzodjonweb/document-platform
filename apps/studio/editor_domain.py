"""Sending a stored draft: one quote, one job and one file task, all pointing at the draft.

A pointer quote and its job hold the draft's id, its version and a hash of its
encrypted marks, as a generation quote does (domain.py), and never the marks.
The marks are read from the draft where they are needed: at the quote, at
submission and when the job runs, each time held to that hash. The encrypted
copy differs on every save, so a keyed hash of what they say (`content`) tells
when a file already made still answers them.
"""
import hashlib
import json
from datetime import timedelta
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.crypto import salted_hmac
from apps.core.allowance import IN_FLIGHT,draft_pointer,quote_cost,require_quote,same_result
from apps.core.errors import DomainError
from apps.core.models import FileAsset,Job,Quote
from apps.core.policy import POLICY_VERSION,plan_limits
from apps.core.services import TELEGRAM_ORIGINS,record_event,validate_inputs
from .domain import GENERATION_IDS,RENDER_IDS,pack,unpack
from .editor_policy import require_text_edit,stored_commands,validate_commands_access
from .models import EditorDocument,GenerationDraft

DELIVERIES=('chat','download')
# Counting once takes away the only weekly cap on a free account, on one sequential worker. These hold whatever that flag says.
SENDS_PER_DRAFT_PER_DAY=10
EDITOR_JOBS_PER_ACCOUNT_PER_HOUR=20
# About what one page comes to as a picture, until a later step has it measured.
PICTURE_PAGE_BYTES=400_000

def version_conflict(e,**mine):
    """The draft moved on elsewhere: when, on which device, how many marks it holds, and how many the caller sent if it sent any."""
    return DomainError('version_conflict',409,{'updated_at':e.updated_at,'device':e.device,'theirs':len(stored_commands(e)),**mine})

def file_gone(a):
    """A file the customer deleted did not run out: telling them it did, and to send it again, would be false."""
    return DomainError('file_unavailable',404) if a.metadata.get('deleted_by_customer') else DomainError('file_expired',410)

def normalized_commands(commands,assets):
    """A draft's marks as they are stored, or the refusal naming the one at fault."""
    from processors import normalize_parameters,ProcessorError
    try:return normalize_parameters('editor.visual',{'commands':commands,'accept_rasterization':True,'combined':True},[a.metadata for a in assets])['commands']
    except ProcessorError as error:
        if error.index is None:raise DomainError(error.code) from None
        raise DomainError('invalid_editor_command',params={'index':error.index,'code':error.code}) from None

def _snapshot(e):
    return hashlib.sha256(bytes(e.encrypted_commands)).hexdigest()

def _content(e,commands):
    """What a draft holds, whichever save wrote it. Keyed, as a short text could otherwise be guessed from a job's row."""
    return salted_hmac('editor.content',json.dumps([str(e.id),e.input_ids,commands],ensure_ascii=False,sort_keys=True),algorithm='sha256').hexdigest()

def _sealed(e):
    """The draft's marks, with their encrypted copy made current: a draft last saved before 0010, or by the image before it, has none to hash."""
    commands=stored_commands(e)
    if e.encrypted_commands is None or unpack(e.encrypted_commands)['version']!=e.version:
        e.encrypted_commands=pack({'version':e.version,'commands':commands})
        e.save(update_fields=['encrypted_commands'])
    return commands

def _pointed_marks(account,parameters):
    """The marks a quote points at, under the draft's lock, or version_conflict if they are no longer the ones it hashed."""
    e=EditorDocument.objects.select_for_update().filter(account=account,id=parameters['editor_document_id']).first()
    if not e or e.version!=parameters.get('version') or e.encrypted_commands is None or _snapshot(e)!=parameters.get('snapshot'):raise DomainError('version_conflict',409)
    return stored_commands(e)

def _summary(account,quote,commands,assets):
    from processors.editor import raster_pages
    changes={}
    for command in commands:
        if 'page' in command:changes[str(command['page'])]=changes.get(str(command['page']),0)+1
    before=assets[0].page_count;after=before-sum(c['type']=='delete_page' for c in commands);raster=raster_pages(commands)
    size=round(assets[0].size_bytes*after/max(before,1))+sum(a.size_bytes for a in assets[1:])+PICTURE_PAGE_BYTES*len(raster)
    return {'changes_by_page':changes,'pages_before':before,'pages_after':after,'raster_pages':raster,'size_estimate':size,'kept_until':timezone.now()+timedelta(hours=24),'cost':quote_cost(account,quote)}

def quote_draft(account,pk,data):
    """One send of a stored draft: the Quote, and the summary a customer reviews before it goes.

    The summary comes from the draft and the file's own record; nothing is run to make it.
    """
    from processors.editor import overflowing,raster_pages
    from apps.core.channel_gate import require as require_channels
    deliver=data.get('deliver');accepted=data.get('accept_rasterization',False)
    if deliver not in DELIVERIES or type(accepted) is not bool:raise DomainError('invalid_parameters')
    # May ask Telegram, so before any lock.
    require_channels(account)
    with transaction.atomic():
        e=EditorDocument.objects.select_for_update().select_related('file').filter(account=account,id=pk).first()
        if not e:raise DomainError('not_found',404)
        if e.file.state!='ready' or e.file.expires_at<=timezone.now():raise file_gone(e.file)
        if data.get('version')!=e.version:raise version_conflict(e)
        if deliver=='chat' and account.telegram_user_id is None:raise DomainError('telegram_link_required',409)
        assets=validate_inputs(account,'editor.visual',e.input_ids)
        if any(a.metadata.get('encrypted') for a in assets):raise DomainError('unlock_first')
        commands=normalized_commands(_sealed(e),assets)
        validate_commands_access(account,commands)
        require_text_edit(commands)
        overflow=overflowing(commands,assets[0].metadata.get('page_sizes',[]))
        if overflow is not None:raise DomainError('editor_text_overflow',params={'index':overflow})
        raster=raster_pages(commands)
        if raster and not accepted:raise DomainError('rasterization_consent_required',params={'pages':raster})
        quote=Quote(account=account,feature_id='editor.visual',parameters={'editor_document_id':str(e.id),'version':e.version,'snapshot':_snapshot(e),'content':_content(e,commands),'deliver':deliver,**({'accept_rasterization':True} if accepted else {})},input_ids=[str(a.pk) for a in assets],input_fingerprints=[{'id':str(a.pk),'sha256':a.sha256} for a in assets],policy={'plan':account.plan,'version':POLICY_VERSION,'tariff_version':'file-v1','limits':plan_limits(account)},expires_at=timezone.now()+timedelta(minutes=10))
        if not same_result(account,quote):
            require_send_room(account,('editor_document_id',str(e.id)))
            require_quote(account,quote)
        quote.save()
        record_event(account,'quote.created',properties={'pages':sum(a.page_count for a in assets)},feature_id=quote.feature_id)
    return quote,_summary(account,quote,commands,assets)

def _still_quoted(account,parameters):
    """That the draft a quote points at is still what was quoted; a draft of marks is held to what its plan allows as well."""
    name,draft_id=draft_pointer(parameters)
    if name=='editor_document_id':return validate_commands_access(account,_pointed_marks(account,parameters))
    d=GenerationDraft.objects.filter(account=account,id=draft_id,expires_at__gt=timezone.now()).first()
    if not d or d.version!=parameters.get('version') or hashlib.sha256(bytes(d.encrypted_data)).hexdigest()!=parameters.get('snapshot'):raise DomainError('version_conflict',409)

def check_send(account,quote,key,origin):
    """At submission, under the account's lock: that the draft is still what was quoted, and the job this send need not repeat, if there is one.

    A file made from these very marks is sent again rather than made again, and
    one being made answers this send too. The quote records which job answered
    it, so that a retry gets the same answer and one quote stays one send.
    """
    _still_quoted(account,quote.parameters)
    job=same_result(account,quote)
    if not job:return None
    chat=origin in TELEGRAM_ORIGINS
    if job.status!='succeeded':
        if chat and job.origin_channel not in TELEGRAM_ORIGINS and not _send_when_made(job):return None
    else:
        if chat:_send_again(account,job,quote)
        _keep(job)
    quote.policy={**quote.policy,'reused':{'job':str(job.id),'key':key}}
    quote.save(update_fields=['policy'])
    return job

def _send_when_made(job):
    """Asks a job still to finish for the chat as well: settle_job reads it under this lock. False when it is being settled this very moment, and it is too late.

    This holds the account's lock, which settle_job takes after the job's, so it must not wait here.
    """
    row=Job.objects.select_for_update(skip_locked=True).filter(pk=job.pk,status__in=IN_FLIGHT).first()
    if not row:return False
    row.origin_channel='mini_app';row.save(update_fields=['origin_channel'])
    job.origin_channel=row.origin_channel
    return True

def _keep(job):
    """A file sent again lasts as long as one just made, and so do the files it came from, as settle_job has it."""
    deadline=timezone.now()+timedelta(hours=24)
    FileAsset.objects.filter(account=job.account,state='ready',id__in=[*job.input_ids,*job.artifacts.values_list('file_id',flat=True)]).update(expires_at=deadline)
    # A deck's draft and all it draws go with its file, or the file would outlive what changes it.
    if job.feature_id in RENDER_IDS:
        from apps.core.services import _extend_draft
        _extend_draft(job,deadline)

def _send_again(account,job,quote):
    from telegram.delivery import enqueue
    require_send_room(account,draft_pointer(quote.parameters))
    for artifact in job.artifacts.select_related('file','account'):enqueue(artifact,f'resend:{quote.id}:{artifact.id}')

def require_send_room(account,pointer):
    """The brake on sends of one draft and on an account's editor jobs. A file sent again is a send too; a batch's or workflow's children are not, nor is an AI run on a deck's draft."""
    from apps.commerce.models import BotDelivery
    name,draft_id=pointer
    now=timezone.now();day=now-timedelta(days=1);jobs=Job.objects.filter(account=account).exclude(status='canceled')
    sends=(jobs.filter(created_at__gte=day,**{f'parameters__{name}':draft_id}).exclude(feature_id__in=GENERATION_IDS).count()
           +BotDelivery.objects.filter(account=account,idempotency_key__startswith='resend:',created_at__gte=day,**{f'artifact__job__parameters__{name}':draft_id}).count())
    if sends>=SENDS_PER_DRAFT_PER_DAY:raise DomainError('send_limit',429,{'limit':SENDS_PER_DRAFT_PER_DAY,'per':'day'},retryable=True)
    hourly=(jobs.filter(Q(feature_id__startswith='editor.')|Q(feature_id__startswith='export.'),created_at__gte=now-timedelta(hours=1))
            .exclude(Q(idempotency_key__startswith='batch:')|Q(idempotency_key__startswith='workflow:')).count())
    if hourly>=EDITOR_JOBS_PER_ACCOUNT_PER_HOUR:raise DomainError('send_limit',429,{'limit':EDITOR_JOBS_PER_ACCOUNT_PER_HOUR,'per':'hour'},retryable=True)

def parameters_to_run(job,assets):
    """What a pointer job gives the processor, read from the draft now. The lock is held only to read: autosave never waits on a job."""
    with transaction.atomic():
        commands=_pointed_marks(job.account,job.parameters)
    validate_commands_access(job.account,commands)
    require_text_edit(commands)
    return {'commands':normalized_commands(commands,assets),'accept_rasterization':job.parameters.get('accept_rasterization') is True,'combined':True}
