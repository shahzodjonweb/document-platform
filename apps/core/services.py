"""Owner-scoped domain services shared by HTTP, bot and durable workers."""
import hashlib
import json
import os
import shutil
import stat
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from django.conf import settings
from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import F
from django.utils import timezone
from .models import Account, FileAsset, Quote, Job, UsageGrant, Reservation, UsageLedger, Artifact, OutboxEvent, AnalyticsEvent, SecretHandle
from .errors import DomainError
from .policy import plan_limits, require_feature, usage_snapshot, active_grants, ensure_grants, POLICY_VERSION

TERMINAL = ('succeeded', 'failed', 'canceled', 'no_op', 'expired')

def record_event(account, event_type, job=None, properties=None, channel='web'):
    return AnalyticsEvent.objects.create(account=account, event_type=event_type, feature_id=job.feature_id if job else '', job=job, channel=channel, locale=account.locale, plan_at_event=account.plan, environment='development' if settings.DEBUG or account.is_test else 'production', properties=properties or {})

def storage_path(key):
    root = settings.PRIVATE_STORAGE_ROOT.resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root): raise DomainError('invalid_file', 400)
    return path

def engine_inspect(path, password=None):
    from processors.sandbox import inspect_file_sandbox as inspect_file
    try: return inspect_file(path, password=password)
    except Exception as exc:
        from processors import ProcessorError
        if isinstance(exc, ProcessorError): raise DomainError(exc.code) from None
        raise

def upload_file(account, uploaded, channel='web', password=None):
    limit = plan_limits(account)['max_file_mib'] * 1024 * 1024
    if uploaded.size > limit: raise DomainError('file_too_large', 413, {'max_bytes':limit})
    suffix = Path(uploaded.name.replace('\\','/')).suffix.lower()
    if suffix not in ('.pdf','.png','.jpg','.jpeg','.webp','.tif','.tiff','.docx','.xlsx','.pptx','.txt','.odt','.ods','.odp'):
        raise DomainError('unsupported_file')
    key = f'inputs/{account.id}/{uuid.uuid4().hex}{suffix}'
    path = storage_path(key)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    hasher, size = hashlib.sha256(), 0
    try:
        with path.open('xb') as output:
            os.chmod(path, 0o600)
            for chunk in uploaded.chunks():
                size += len(chunk)
                if size > limit: raise DomainError('file_too_large', 413)
                hasher.update(chunk)
                output.write(chunk)
        metadata = engine_inspect(path, password=password)
        if metadata.get('password_required'): raise DomainError('password_required')
        if metadata.get('page_count') is None: raise DomainError('conversion_preflight_unavailable')
        pages = int(metadata['page_count'])
        if pages <= 0: raise DomainError('invalid_file')
        if pages > plan_limits(account)['max_pages_per_job']: raise DomainError('page_limit_exceeded', 413)
        name = Path(uploaded.name.replace('\\','/')).name[:255]
        name = ''.join(c for c in name if ord(c) >= 32) or f'document{suffix}'
        asset = FileAsset.objects.create(account=account, name=name, object_key=key, mime_type=metadata['mime_type'], sha256=hasher.hexdigest(), size_bytes=size, page_count=pages, metadata=metadata, expires_at=timezone.now()+timedelta(hours=24))
        if metadata.get('encrypted') and password:
            from .secrets import create_secret
            handle = create_secret(account,password,asset)
            asset.metadata['password_secret_id'] = str(handle.id)
            asset.save(update_fields=['metadata'])
        record_event(account, 'upload.accepted', properties={'bytes':size,'pages':pages}, channel=channel)
        return asset
    except Exception:
        path.unlink(missing_ok=True)
        raise

def owned_assets(account, input_ids):
    if not isinstance(input_ids, list) or not input_ids or len(input_ids) > 50 or len(set(map(str,input_ids))) != len(input_ids):
        raise DomainError('invalid_inputs')
    try:
        ids = [str(uuid.UUID(str(v))) for v in input_ids]
        assets = {str(a.pk):a for a in FileAsset.objects.filter(account=account,id__in=ids,state='ready',expires_at__gt=timezone.now())}
    except (TypeError, ValueError): raise DomainError('invalid_inputs') from None
    if len(assets) != len(ids): raise DomainError('file_unavailable', 404)
    return [assets[v] for v in ids]

def verify_input_files(job, assets):
    """Verify quoted bytes with bounded reads before any engine/provider work.

    Database fingerprints alone cannot detect an accidentally replaced private
    object. Refuse non-regular files and size changes before reading; never hash
    an unbounded stream or trust mutable database metadata over the quote.
    """
    from .policy import SEED
    expected = job.quote.input_fingerprints
    if [{'id':str(a.pk),'sha256':a.sha256} for a in assets] != expected:
        raise DomainError('file_changed',409)
    if not assets: return []
    limits = job.policy.get('limits',{})
    caps = {}
    for key in ('max_file_mib','max_aggregate_input_mib'):
        value = limits.get(key)
        if type(value) is not int or value <= 0: raise DomainError('file_changed',409)
        caps[key] = min(value,max(plan[key] for plan in SEED['plans'].values()))*1024*1024
    if sum(a.size_bytes for a in assets) > caps['max_aggregate_input_mib']:
        raise DomainError('file_changed',409)
    paths = []
    for asset, fingerprint in zip(assets,expected):
        if not 0 < asset.size_bytes <= caps['max_file_mib']:
            raise DomainError('file_changed',409)
        path = storage_path(asset.object_key)
        try:
            flags = os.O_RDONLY | getattr(os,'O_NONBLOCK',0) | getattr(os,'O_NOFOLLOW',0)
            with os.fdopen(os.open(path,flags),'rb') as source:
                before = os.fstat(source.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size != asset.size_bytes:
                    raise DomainError('file_changed',409)
                digest, remaining = hashlib.sha256(), asset.size_bytes
                while remaining:
                    chunk = source.read(min(1024*1024,remaining))
                    if not chunk: raise DomainError('file_changed',409)
                    digest.update(chunk); remaining -= len(chunk)
                if source.read(1): raise DomainError('file_changed',409)
                after = os.fstat(source.fileno())
                current = path.stat()
                identity = lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)
                if identity(before) != identity(after) or identity(after) != identity(current) or digest.hexdigest() != fingerprint['sha256']:
                    raise DomainError('file_changed',409)
        except OSError:
            raise DomainError('file_changed',409) from None
        paths.append(path)
    return paths

def validate_inputs(account, feature_id, input_ids):
    require_feature(account, feature_id)
    assets = owned_assets(account, input_ids)
    limits = plan_limits(account)
    multi = feature_id in ('pdf.merge','pdf.images_to_pdf') or feature_id.startswith('editor.')
    cap = limits['max_merge_input_files'] if multi else 1
    if len(assets) > cap: raise DomainError('input_count_exceeded')
    if feature_id == 'pdf.merge' and len(assets) < 2: raise DomainError('merge_needs_two_files')
    if sum(a.size_bytes for a in assets) > limits['max_aggregate_input_mib']*1024*1024: raise DomainError('aggregate_size_exceeded', 413)
    if any(a.size_bytes > limits['max_file_mib']*1024*1024 for a in assets): raise DomainError('file_too_large', 413)
    if sum(a.page_count for a in assets) > limits['max_pages_per_job']: raise DomainError('page_limit_exceeded', 413)
    kinds = [a.metadata.get('kind') for a in assets]
    if feature_id.startswith('editor.') and (kinds[0]!='pdf' or any(k!='image' for k in kinds[1:])): raise DomainError('unsupported_file')
    if feature_id.startswith('ocr.') and any(k not in ('pdf','image') for k in kinds): raise DomainError('unsupported_file')
    if feature_id in ('convert.pdf_to_docx','convert.pdf_to_xlsx') and kinds != ['pdf']: raise DomainError('unsupported_file')
    if feature_id == 'convert.word_to_pdf' and kinds != ['docx']: raise DomainError('unsupported_file')
    if feature_id == 'convert.pptx_to_pdf' and kinds != ['pptx']: raise DomainError('unsupported_file')
    if feature_id == 'pdf.images_to_pdf' and any(k != 'image' for k in kinds): raise DomainError('unsupported_file')
    if feature_id.startswith('pdf.') and feature_id != 'pdf.images_to_pdf' and any(k != 'pdf' for k in kinds): raise DomainError('unsupported_file')
    return assets

def create_quote(account, feature_id, input_ids, parameters, secret_id=None):
    from processors import normalize_parameters, ProcessorError
    if not isinstance(parameters,dict) or len(json.dumps(parameters)) > 10000: raise DomainError('invalid_parameters')
    if any(k.lower() in ('password','owner_password','user_password') for k in parameters): raise DomainError('feature_unavailable',409)
    # A free account joins the owner's channels before using a service; asking
    # here tells them before they have set the task up, not after.
    from .channel_gate import require as require_channels
    require_channels(account)
    assets = validate_inputs(account,feature_id,input_ids)
    if feature_id.startswith('editor.'):
        from apps.studio.editor_policy import validate_commands_access
        validate_commands_access(account,parameters.get('commands',[]))
    if feature_id in ('pdf.protect','pdf.unlock_known'):
        from .secrets import get_secret
        if feature_id == 'pdf.unlock_known':
            if not assets[0].metadata.get('encrypted'): raise DomainError('not_encrypted')
            secret_id = secret_id or assets[0].metadata.get('password_secret_id')
        if not secret_id: raise DomainError('password_required')
        handle = get_secret(account,secret_id,asset=assets[0] if feature_id=='pdf.unlock_known' else None)
        secret_id = handle.id
    elif any(a.metadata.get('encrypted') for a in assets):
        raise DomainError('unlock_first')
    try: normalized = normalize_parameters(feature_id,parameters,[a.metadata for a in assets])
    except ProcessorError as exc: raise DomainError(exc.code) from None
    # Selection/removal can reduce output; split/merge/reorder preserve at most the input page total.
    pages = sum(a.page_count for a in assets)
    if feature_id == 'pdf.split' and normalized.get('ranges'):
        from processors.engine import parse_pages
        pages = max(pages, sum(len(parse_pages(r, assets[0].page_count)) for r in normalized['ranges']))
    if pages > plan_limits(account)['max_pages_per_job']: raise DomainError('page_limit_exceeded',413)
    credits = 1 if feature_id.startswith('ocr.') else 2 if feature_id in ('convert.pdf_to_docx','convert.pdf_to_xlsx') else 0
    meters = {'file_tasks':0 if credits else 1,'file_page_units':0 if credits else pages,'ai_credits':pages*credits}
    quote = Quote.objects.create(account=account,feature_id=feature_id,secret_id=secret_id,parameters=normalized,input_ids=[str(a.pk) for a in assets],input_fingerprints=[{'id':str(a.pk),'sha256':a.sha256} for a in assets],meters=meters,policy={'plan':account.plan,'version':POLICY_VERSION,'tariff_version':'file-v1','limits':plan_limits(account)},expires_at=timezone.now()+timedelta(minutes=10))
    record_event(account,'quote.created',properties={'pages':pages})
    return quote

def quote_affordable(account, quote):
    usage = usage_snapshot(account)
    affordable = all(usage['meters'][m]['remaining']>=v for m,v in quote.meters.items())
    daily = usage['daily']
    if daily['limit'] is not None and daily['remaining'] < quote.meters.get('file_tasks',0):
        purchased = active_grants(account).filter(meter='file_tasks').exclude(source='included')
        available = sum(g.quantity-g.consumed-g.reserved for g in purchased)
        affordable = affordable and available >= quote.meters.get('file_tasks',0)
    return affordable,usage

@transaction.atomic
def submit_job(account, quote_id, idempotency_key, origin='web'):
    if not isinstance(idempotency_key,str) or not 8<=len(idempotency_key)<=128: raise DomainError('idempotency_key_required')
    # The channel rule is checked before the row lock (it may ask Telegram), and
    # never against a retry of a submission that already became a job.
    if not Job.objects.filter(account=account,idempotency_key=idempotency_key).exists():
        from .channel_gate import require as require_channels
        require_channels(account)
    # Row lock serializes quota and concurrency decisions per canonical account.
    account = Account.objects.select_for_update().get(pk=account.pk)
    request_hash = hashlib.sha256(json.dumps({'quote_id':str(quote_id)},sort_keys=True).encode()).hexdigest()
    existing = Job.objects.filter(account=account,idempotency_key=idempotency_key).first()
    if existing:
        if existing.request_hash != request_hash: raise DomainError('idempotency_conflict',409)
        return existing,False
    try: quote = Quote.objects.select_for_update().get(pk=quote_id,account=account)
    except (Quote.DoesNotExist,ValueError,ValidationError): raise DomainError('not_found',404) from None
    if Job.objects.filter(quote=quote).exists(): raise DomainError('quote_already_submitted',409)
    if quote.expires_at <= timezone.now(): raise DomainError('quote_expired',409)
    from apps.studio.domain import GENERATION_IDS, validate_generation_quote
    assets = validate_generation_quote(account,quote) if quote.feature_id in GENERATION_IDS else validate_inputs(account,quote.feature_id,quote.input_ids)
    if quote.feature_id.startswith('editor.'):
        from apps.studio.editor_policy import validate_commands_access
        validate_commands_access(account,quote.parameters.get('commands',[]))
    if quote.policy['plan'] != account.plan or quote.policy['version'] != POLICY_VERSION: raise DomainError('quote_policy_changed',409)
    if [{'id':str(a.pk),'sha256':a.sha256} for a in assets] != quote.input_fingerprints: raise DomainError('file_changed',409)
    if Job.objects.filter(account=account,status__in=('queued','running','finalizing')).count() >= plan_limits(account)['concurrent_jobs']: raise DomainError('concurrency_limit',409,retryable=True)
    ensure_grants(account)
    affordable, usage = quote_affordable(account,quote)
    if not affordable: raise DomainError('quota_exceeded',409)
    job = Job.objects.create(account=account,quote=quote,feature_id=quote.feature_id,parameters=quote.parameters,input_ids=quote.input_ids,policy=quote.policy,meters=quote.meters,idempotency_key=idempotency_key,request_hash=request_hash,origin_channel=origin)
    for meter, amount in quote.meters.items():
        remaining = amount
        # Eligibility includes an optional payment join. Lock the grant rows
        # themselves; PostgreSQL cannot lock the nullable side of that join.
        grants = list(active_grants(account).filter(meter=meter).select_for_update(of=('self',)))
        rank = {'included':0,'referral':1,'purchased':2}
        grants.sort(key=lambda g:(rank.get(g.source,9),g.expires_at or timezone.now()+timedelta(days=100000),str(g.pk)))
        for grant in grants:
            if meter == 'file_tasks' and grant.source == 'included' and usage['daily']['limit'] is not None and usage['daily']['remaining'] < amount: continue
            take = min(remaining, grant.quantity-grant.consumed-grant.reserved)
            if take <= 0: continue
            grant.reserved += take
            grant.save(update_fields=['reserved'])
            Reservation.objects.create(job=job,grant=grant,meter=meter,amount=take)
            UsageLedger.objects.create(account=account,job=job,grant=grant,meter=meter,kind='reserve',amount=take)
            remaining -= take
            if not remaining: break
        if remaining: raise DomainError('quota_exceeded',409)
    if quote.secret_id:
        from .secrets import get_secret
        handle=get_secret(account,quote.secret_id)
        handle.job=job
        handle.save(update_fields=['job'])
    OutboxEvent.objects.create(job=job)
    record_event(account,'job.accepted',job=job,channel=origin)
    return job,True

@transaction.atomic
def settle_job(job_id, status, actual=None, error_code='', outputs=None, warnings=None, engine=''):
    job = Job.objects.select_for_update().select_related('account').get(pk=job_id)
    if job.status in TERMINAL: return job
    actual = actual or {}
    if any(not isinstance(v,int) or v<0 or v>job.meters.get(m,0) for m,v in actual.items()): raise DomainError('quote_exceeded',409)
    left = dict(actual) if status=='succeeded' else {}
    for reservation in job.reservations.select_for_update().select_related('grant').order_by('id'):
        if reservation.settled: continue
        grant = UsageGrant.objects.select_for_update().get(pk=reservation.grant_id)
        consume = min(reservation.amount,left.get(reservation.meter,0))
        release = reservation.amount-consume
        grant.reserved -= reservation.amount
        grant.consumed += consume
        grant.save(update_fields=['reserved','consumed'])
        for kind,amount in (('consume',consume),('release',release)):
            if amount: UsageLedger.objects.create(account=job.account,job=job,grant=grant,meter=reservation.meter,kind=kind,amount=amount)
        left[reservation.meter] = left.get(reservation.meter,0)-consume
        reservation.settled=True
        reservation.save(update_fields=['settled'])
    if any(v>0 for v in left.values()): raise DomainError('quote_exceeded',409)
    deadline = timezone.now()+timedelta(hours=24)
    for output in outputs or []:
        path = Path(output['path'])
        key = str(path.relative_to(settings.PRIVATE_STORAGE_ROOT.resolve()))
        asset = FileAsset.objects.create(account=job.account,name=output['name'],object_key=key,mime_type=output['mime_type'],sha256=hashlib.sha256(path.read_bytes()).hexdigest(),size_bytes=path.stat().st_size,page_count=output.get('page_count',0),metadata={**output.get('metadata',{}),'kind':{'application/pdf':'pdf','application/zip':'archive','application/vnd.openxmlformats-officedocument.wordprocessingml.document':'docx','application/vnd.openxmlformats-officedocument.presentationml.presentation':'pptx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':'xlsx','text/plain':'text','application/json':'text'}.get(output['mime_type'],'image'),'mime_type':output['mime_type'],'page_count':output.get('page_count',0),'encrypted':job.feature_id=='pdf.protect'},expires_at=deadline)
        artifact = Artifact.objects.create(account=job.account,job=job,file=asset,role=output.get("role","user_document"))
        if status == 'succeeded' and job.origin_channel == 'bot' and job.account.telegram_user_id is not None:
            # Persist delivery in the settlement transaction: a worker can finish
            # after the initiating bot update returns, or while the bot restarts.
            # This only writes an outbox row; Telegram is contacted by the bot.
            from telegram.delivery import enqueue
            enqueue(artifact, f'job:{job.id}:{artifact.id}')
    FileAsset.objects.filter(account=job.account,id__in=job.input_ids).update(expires_at=deadline)
    job.status,job.error_code,job.completed_at,job.settled_meters = status,error_code,timezone.now(),actual if status=='succeeded' else {m:0 for m in job.meters}
    job.warnings,job.engine,job.lease_expires_at = warnings or [],engine,None
    job.save(update_fields=['status','error_code','completed_at','settled_meters','warnings','engine','lease_expires_at'])
    if not settings.LOCAL_SYNC_JOBS:
        from telegram.notifications import enqueue_notice
        enqueue_notice(job)
    record_event(job.account,f'job.{status}',job=job,properties={'pages':actual.get('file_page_units',0)},channel=job.origin_channel)
    OutboxEvent.objects.filter(job=job,topic='job.execute').update(delivered_at=timezone.now())
    SecretHandle.objects.filter(job=job).delete()
    return job

def execute_job(job_id):
    from processors.sandbox import execute_sandbox as execute
    from processors import ProcessorError
    with transaction.atomic():
        job = Job.objects.select_for_update().select_related('account').get(pk=job_id)
        if job.status!='queued': return job
        job.status,job.started_at = 'running',timezone.now()
        # Ten minutes suits a file task. Work that knows it needs longer — a
        # document written in several provider calls — says so on its quote, and
        # the bounds keep a bad value from parking a worker or losing a job.
        requested = job.quote.policy.get('lease_seconds') if job.quote_id else None
        lease = min(2400,max(600,int(requested))) if isinstance(requested,(int,float)) else 600
        job.lease_expires_at = timezone.now()+timedelta(seconds=lease)
        job.attempt_count += 1
        job.save(update_fields=['status','started_at','lease_expires_at','attempt_count'])
    output_dir = storage_path(f'outputs/{job.account_id}/{job.id}')
    output_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    try:
        assets = owned_assets(job.account,job.input_ids) if job.input_ids else []
        input_paths = verify_input_files(job,assets)
        secret=None
        if job.quote.secret_id:
            from .secrets import get_secret,decrypt
            secret=decrypt(get_secret(job.account,job.quote.secret_id,job=job))
        from apps.studio.domain import GENERATION_IDS
        if job.feature_id in GENERATION_IDS:
            from apps.studio.execution import execute_generation
            result = execute_generation(job,output_dir)
        else:
            result = execute(job.feature_id,input_paths,job.parameters,output_dir,secret=secret)
        secret=None
        no_op = result.get('no_op',False)
        outputs = result.get('artifacts',[]) if not no_op else []
        if not outputs and not no_op: raise DomainError('invalid_output')
        for output in outputs:
            path = Path(output['path']).resolve()
            if not path.is_relative_to(output_dir) or not path.is_file() or path.stat().st_size == 0: raise DomainError('invalid_output')
            if output['mime_type']=='application/pdf' and job.feature_id!='pdf.protect':
                checked=engine_inspect(path)
                if checked['page_count']!=output.get('page_count'):raise DomainError('invalid_output')
                output['metadata']=checked
        credits = 1 if job.feature_id.startswith('ocr.') else 2 if job.feature_id in ('convert.pdf_to_docx','convert.pdf_to_xlsx') else 0
        actual = result.get('actual_meters',{'file_tasks':0 if credits else 1,'file_page_units':0 if credits else max(sum(a.page_count for a in assets),int(result.get('actual_page_units',0))),'ai_credits':sum(a.page_count for a in assets)*credits})
        job = settle_job(job.id,'no_op' if no_op else 'succeeded',actual=actual,outputs=outputs,warnings=result.get('metadata',{}).get('warnings',[]),engine=result.get('metadata',{}).get('engine','pypdf'))
        if no_op: shutil.rmtree(output_dir,ignore_errors=True)
        return job
    except (DomainError,ProcessorError) as exc:
        shutil.rmtree(output_dir,ignore_errors=True)
        return settle_job(job.id,'failed',error_code=exc.code)
    except Exception:
        # No exception text: engine errors may contain private paths or document data.
        shutil.rmtree(output_dir,ignore_errors=True)
        return settle_job(job.id,'failed',error_code='processing_failed')

@transaction.atomic
def cancel_job(account, job_id):
    try: job = Job.objects.select_for_update().get(account=account,pk=job_id)
    except Job.DoesNotExist: raise DomainError('not_found',404)
    if job.status=='queued': return settle_job(job.id,'canceled')
    if job.status in TERMINAL: return job
    raise DomainError('job_already_running',409)

def cleanup_expired():
    now = timezone.now()
    count = 0
    for asset in FileAsset.objects.filter(expires_at__lte=now).exclude(state='deleted').iterator():
        if any(str(asset.pk) in j.input_ids for j in Job.objects.filter(account=asset.account,status__in=('running','queued','finalizing'))):
            continue
        asset.state = 'expired'
        asset.save(update_fields=['state'])
        storage_path(asset.object_key).unlink(missing_ok=True)
        asset.state = 'deleted'
        asset.save(update_fields=['state'])
        count += 1
    SecretHandle.objects.filter(expires_at__lte=now).delete()
    from .models import EmailChallenge, GoogleChallenge, AuthRateLimit, AuthChallenge, BotCallback, BotConversation, AuthReceipt
    from apps.studio.models import PhotoSearch
    PhotoSearch.objects.filter(expires_at__lte=now).delete()
    from apps.studio.checkpoints import cleanup_expired as cleanup_provider_checkpoints
    cleanup_provider_checkpoints(now)
    from apps.studio.provider_usage import cleanup_attempts
    cleanup_attempts()
    for model in (EmailChallenge, GoogleChallenge, AuthRateLimit, AuthChallenge, BotCallback):
        model.objects.filter(expires_at__lte=now).delete()
    # Both Telegram and Turnstile proofs expire after five minutes. Keep receipt
    # hashes for a day, then discard them so failed verification spam cannot grow
    # the replay table indefinitely.
    AuthReceipt.objects.filter(created_at__lte=now-timedelta(days=1)).delete()
    from telegram.verification import cleanup_expired_pending
    cleanup_expired_pending(now)
    BotConversation.objects.filter(updated_at__lte=now-timedelta(minutes=30)).exclude(state='').update(state='',prompt={})
    expired_uploads = BotConversation.objects.filter(language_expires_at__lte=now, pending__has_key='uploads')
    for conversation_id in expired_uploads.values_list('pk', flat=True).iterator():
        # Recheck under the same row lock as language choice: cleanup must not
        # overwrite newly selected language state or a freshly opened picker.
        with transaction.atomic():
            conversation = BotConversation.objects.select_for_update().filter(
                pk=conversation_id, language_expires_at__lte=now, pending__has_key='uploads',
            ).first()
            if conversation is None:
                continue
            pending = dict(conversation.pending)
            pending.pop('uploads')
            pending['resend_file'] = True
            conversation.pending = pending
            conversation.save(update_fields=['pending'])
    from apps.studio.models import GenerationDraft, EducationProject, EditorDocument, ShareGrant
    GenerationDraft.objects.filter(expires_at__lte=now).delete()
    EducationProject.objects.filter(expires_at__lte=now).delete()
    EditorDocument.objects.filter(file__expires_at__lte=now).delete()
    ShareGrant.objects.filter(expires_at__lte=now).delete()
    # Crash backstop: delete unregistered private binaries older than retention.
    registered=set(FileAsset.objects.values_list('object_key',flat=True))
    cutoff=(now-timedelta(hours=24)).timestamp()
    for prefix in ('inputs','outputs','previews','scratch'):
        root=storage_path(prefix)
        if root.exists():
            for path in root.rglob('*'):
                if path.is_symlink() or not path.is_file() or path.stat().st_mtime>cutoff: continue
                key=str(path.relative_to(settings.PRIVATE_STORAGE_ROOT.resolve()))
                if key not in registered: path.unlink(missing_ok=True)
    for job in Job.objects.filter(status__in=('failed','canceled','no_op','expired')):
        shutil.rmtree(storage_path(f'outputs/{job.account_id}/{job.id}'),ignore_errors=True)
    # Card transfers: stale requests expire, renewals are reminded, and a
    # receipt is deleted once its decision is old enough. Receipts live under
    # their own prefix, outside the backstop above.
    from apps.commerce.manual import housekeeping
    housekeeping(now)
    return count
