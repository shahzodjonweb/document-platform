"""Bounded, synthetic production probes for PDF Master's background services.

Load this module inside the API container's Django shell. Call
``prepare_canaries(uuid_string)`` once, then ``poll_background(context)`` between
other checks. These functions never run cleanup or batch execution themselves.
The normal batch daemon polls every two seconds; cleanup runs every 300 seconds.

The batch fixture deliberately seeds a test-only parent with ordinary free-tier
child quotes. This verifies the daemon, processor and settlement path, without
inventing a paid subscription or claiming to verify paid HTTP eligibility.
No payment rows, customer identities, real Telegram messages or global settings
are changed. All created records belong to one explicitly marked test account.
"""
import hashlib
import io
import os
import re
import stat
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone

from apps.core.models import Account, Artifact, FileAsset
from apps.core.policy import POLICY_VERSION
from apps.core.services import create_quote, storage_path, upload_file
from apps.studio.batch_models import BatchItem, BatchQuote, BatchRun


PREFIX = 'Background service verification '
NAMESPACE = 'https://pdfmaster.orderdesk.live/background-service-check/'


def _error(exc):
    code = getattr(exc, 'code', '')
    return {'status': 'failed', 'error': type(exc).__name__,
            'code': code if isinstance(code, str) and re.fullmatch(r'[a-z0-9_]{1,80}', code) else 'probe_failed'}


def _account(context):
    audit_id = uuid.UUID(str(context['audit_id']))
    expected_id = uuid.uuid5(uuid.NAMESPACE_URL, NAMESPACE + str(audit_id))
    if uuid.UUID(str(context['account_id'])) != expected_id:
        raise ValueError('Unexpected canary account')
    account = Account.objects.get(pk=expected_id, is_test=True)
    if account.display_name != PREFIX + audit_id.hex:
        raise ValueError('Unexpected canary account marker')
    if account.email or account.telegram_user_id or account.google_sub or account.password_hash:
        raise ValueError('Canary must not have a login identity')
    return account


def _pdf():
    from pypdf import PdfWriter
    document = PdfWriter()
    document.add_blank_page(width=100, height=100)
    output = io.BytesIO()
    document.write(output)
    return output.getvalue()


def _prepare_cleanup(account):
    asset = upload_file(account, SimpleUploadedFile(
        'background-cleanup-canary.pdf', _pdf(), content_type='application/pdf'))
    path = storage_path(asset.object_key)
    if not path.is_file() or path.stat().st_size != asset.size_bytes:
        raise RuntimeError('Cleanup fixture was not stored')
    # Only this newly created synthetic asset is made eligible. The real cleanup
    # service must change its state and remove its bytes on the ordinary tick.
    FileAsset.objects.filter(pk=asset.pk, account=account).update(expires_at=timezone.now() - timedelta(seconds=1))
    return {'status': 'pending', 'asset_id': str(asset.pk), 'object_key': asset.object_key,
            'prepared_at': timezone.now().isoformat(), 'scheduler_interval_seconds': 300}


def _prepare_batch(account, audit_id):
    from PIL import Image
    key = 'background-canary-' + uuid.UUID(audit_id).hex
    if BatchRun.objects.filter(account=account, idempotency_key=key).exists():
        raise ValueError('Use a fresh audit UUID for each production check')
    child_quotes = []
    for index, color in enumerate(('#FA3331', '#0275FC')):
        output = io.BytesIO()
        Image.new('RGB', (24 + index, 32 + index), color).save(output, format='PNG')
        asset = upload_file(account, SimpleUploadedFile(
            f'background-batch-{index + 1}.png', output.getvalue(), content_type='image/png'))
        child_quotes.append(create_quote(account, 'pdf.images_to_pdf', [str(asset.pk)], {}))
    meters = {meter: sum(q.meters.get(meter, 0) for q in child_quotes)
              for meter in ('file_tasks', 'file_page_units', 'ai_credits')}
    if meters['ai_credits'] or meters['file_tasks'] != 2:
        raise RuntimeError('Unexpected batch fixture cost')
    # Publish the whole parent atomically, so runbatches cannot observe a parent
    # without its children. No execute_batch/drain_batches/execute_job call here.
    with transaction.atomic():
        parent_quote = BatchQuote.objects.create(
            account=account, feature_id='batch.image_sets',
            child_quote_ids=[str(q.pk) for q in child_quotes], meters=meters,
            policy={'plan': account.plan, 'version': POLICY_VERSION, 'max_children': 2,
                    'infrastructure_canary': True}, expires_at=min(q.expires_at for q in child_quotes))
        run = BatchRun.objects.create(account=account, quote=parent_quote, idempotency_key=key,
                                      request_hash=hashlib.sha256(str(parent_quote.pk).encode()).hexdigest())
        BatchItem.objects.bulk_create([BatchItem(run=run, index=index, quote=quote)
                                       for index, quote in enumerate(child_quotes)])
    return {'status': 'pending', 'run_id': str(run.pk), 'children_expected': 2,
            'prepared_at': timezone.now().isoformat(), 'scheduler_interval_seconds': 2,
            'scope': 'synthetic_parent_normal_daemon_not_paid_api_eligibility'}


def prepare_canaries(audit_id):
    """Create independent canaries; one preparation failure does not hide another."""
    if settings.LOCAL_SYNC_JOBS:
        raise RuntimeError('Daemon verification requires asynchronous production jobs')
    audit_id = str(uuid.UUID(str(audit_id)))
    identifier = uuid.uuid5(uuid.NAMESPACE_URL, NAMESPACE + audit_id)
    account, created = Account.objects.get_or_create(pk=identifier, defaults={
        'display_name': PREFIX + uuid.UUID(audit_id).hex, 'is_test': True, 'locale': 'en'})
    context = {'audit_id': audit_id, 'account_id': str(account.pk), 'created_at': timezone.now().isoformat()}
    _account(context)
    if not created:
        raise ValueError('Use a fresh audit UUID; retain returned context to poll existing checks')
    # Cleanup starts first because its normal interval is longer than the batch.
    for name, prepare in (('cleanup', lambda: _prepare_cleanup(account)),
                          ('batches', lambda: _prepare_batch(account, audit_id))):
        try:
            context[name] = prepare()
        except Exception as exc:
            context[name] = _error(exc)
    return context


def _poll_cleanup(account, spec):
    asset = FileAsset.objects.get(pk=spec['asset_id'], account=account)
    if asset.object_key != spec['object_key']:
        raise ValueError('Cleanup fixture changed')
    exists = storage_path(asset.object_key).exists()
    if asset.state == 'deleted':
        if exists:
            raise RuntimeError('Cleanup marked deleted but retained bytes')
        return {'status': 'passed', 'file_state': asset.state, 'bytes_removed': True,
                'normal_scheduler': True}
    if asset.state not in ('ready', 'expired'):
        raise RuntimeError('Unexpected cleanup state')
    return {'status': 'pending', 'file_state': asset.state, 'bytes_present': exists,
            'scheduler_interval_seconds': 300}


def _poll_batch(account, spec):
    from pypdf import PdfReader
    run = BatchRun.objects.get(pk=spec['run_id'], account=account)
    if not run.quote.policy.get('infrastructure_canary'):
        raise ValueError('Unexpected batch parent')
    children = list(run.children.select_related('job', 'quote').order_by('index'))
    if len(children) != spec['children_expected']:
        raise RuntimeError('Missing batch children')
    if run.status in ('queued', 'running'):
        return {'status': 'pending', 'parent_status': run.status,
                'child_statuses': [child.status for child in children]}
    if run.status != 'succeeded' or not run.completed_at:
        return {'status': 'failed', 'parent_status': run.status,
                'child_statuses': [child.status for child in children],
                'child_errors': [child.error_code or 'none' for child in children]}
    pages = []
    for child in children:
        job = child.job
        if (child.status != 'succeeded' or not job or job.status != 'succeeded'
                or job.account_id != account.pk or job.attempt_count < 1
                or job.settled_meters != child.quote.meters or job.settled_meters.get('ai_credits')):
            raise RuntimeError('Batch child execution or settlement failed')
        artifacts = list(Artifact.objects.select_related('file').filter(job=job))
        if len(artifacts) != 1:
            raise RuntimeError('Expected one output per batch child')
        asset = artifacts[0].file
        if asset.account_id != account.pk or asset.mime_type != 'application/pdf' or asset.size_bytes > 1024 * 1024:
            raise RuntimeError('Unexpected canary output')
        path = storage_path(asset.object_key)
        if not path.is_file() or path.stat().st_size != asset.size_bytes:
            raise RuntimeError('Batch output missing')
        page_count = len(PdfReader(path).pages)
        if page_count != 1:
            raise RuntimeError('Batch output page count failed')
        pages.append(page_count)
    return {'status': 'passed', 'parent_status': run.status, 'children_succeeded': len(children),
            'output_pages': pages, 'ai_credits': 0, 'normal_daemon': True,
            'scope': spec['scope']}


def poll_background(context):
    """Read only owned fixtures once; the caller chooses its bounded polling loop."""
    account = _account(context)
    results = {}
    for name, poll in (('batches', _poll_batch), ('cleanup', _poll_cleanup)):
        spec = context[name]
        if spec.get('status') == 'failed':
            results[name] = spec
            continue
        try:
            results[name] = poll(account, spec)
        except Exception as exc:
            results[name] = _error(exc)
    return results


def polling_process_lock():
    """Check the existing process lock without writing it or consuming updates.

    This proves a polling process holds its project lock, not that Telegram has
    delivered an update recently. There is no polling heartbeat in this release.
    Pair this result with container process state and read-only Bot API metadata.
    """
    import fcntl
    path = settings.PRIVATE_STORAGE_ROOT / 'runbot.lock'
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    except FileNotFoundError:
        return {'status': 'failed', 'lock_held': False, 'reason': 'no_polling_lock', 'heartbeat_available': False}
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise RuntimeError('Polling lock must be a regular file')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'passed', 'lock_held': True, 'heartbeat_available': False,
                    'scope': 'process_lock_not_update_delivery'}
        fcntl.flock(fd, fcntl.LOCK_UN)
        return {'status': 'failed', 'lock_held': False, 'reason': 'polling_process_not_holding_lock',
                'heartbeat_available': False}
    finally:
        os.close(fd)


def retire_canaries(context):
    """Expire only this audit's terminal-job fixtures for the normal cleanup tick."""
    account = _account(context)
    if account.jobs.filter(status__in=('queued', 'running', 'finalizing')).exists():
        return {'status': 'pending', 'reason': 'own_canary_jobs_still_active'}
    count = FileAsset.objects.filter(account=account).exclude(state='deleted').update(expires_at=timezone.now())
    return {'status': 'passed', 'synthetic_files_expired': count, 'normal_scheduler_removes_bytes': True}
