"""AI requests and the documents they produced, kept for staff review.

Customers' files expire after 24 hours, and so do their drafts. The team needs
longer to see what people ask the AI for and whether what it made was any
good, so each generation that becomes a task leaves a record: the request as it
was submitted (encrypted, like the draft) and, once the task succeeds, a copy of
the document. Both are deleted after REVIEW_DAYS.

Recording never stands in a customer's way: if it fails, the task goes ahead
and the failure is logged.
"""
import logging
import shutil
from datetime import timedelta
from pathlib import Path

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

REVIEW_DAYS = 30
PREFIX = 'review'
SUFFIXES = {'application/pdf': '.pdf',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx'}


def _folder(record):
    return f'{PREFIX}/{record.account_id}/{record.id}'


def record_request(job):
    """Keep what was asked, when a generation (not an outline) becomes a task."""
    from apps.core.models import FileAsset
    from .domain import GENERATION_IDS, unpack, pack
    from .models import GenerationDraft, GenerationRecord
    if job.feature_id not in GENERATION_IDS or job.parameters.get('stage') == 'outline':
        return None
    try:
        draft = GenerationDraft.objects.filter(pk=job.parameters.get('generation_draft_id'), account=job.account).first()
        data = unpack(draft.encrypted_data) if draft else {}
        content = data.get('content') or {}
        sources = list(FileAsset.objects.filter(account=job.account, pk__in=data.get('source_ids') or [])
                       .values_list('name', flat=True))
        request = {
            'prompt': data.get('prompt', ''),
            'title': content.get('title') or data.get('title', ''),
            'output_locale': data.get('output_locale', ''),
            'output_format': data.get('output_format', ''),
            'sections': [{'heading': s.get('heading', ''), 'body': s.get('body', '')} for s in content.get('sections', [])],
            'questions': len(content.get('questions') or []),
            'sources': sources,
        }
        revision = data.get('revision') or {}
        if revision:
            request['revision'] = {'request': revision.get('request', ''),
                                   'original_prompt': revision.get('original_prompt', '')}
        # Its own savepoint: a failure here must not poison the job's transaction.
        with transaction.atomic():
            return GenerationRecord.objects.create(
                account=job.account, job=job, feature_id=job.feature_id, channel=job.origin_channel,
                encrypted_request=pack(request), expires_at=timezone.now() + timedelta(days=REVIEW_DAYS))
    except Exception:
        logger.exception('Could not record AI request for job %s', job.pk)
        return None


def keep_output(job):
    """Copy the document a recorded generation produced, out of the 24-hour files."""
    from apps.core.services import storage_path
    from .models import GenerationRecord
    record = GenerationRecord.objects.filter(job=job).first()
    if not record:
        return None
    try:
        artifacts = job.artifacts.select_related('file')
        artifact = artifacts.filter(role='user_document').first() or artifacts.first()
        if not artifact:
            return record
        asset = artifact.file
        source = storage_path(asset.object_key)
        suffix = SUFFIXES.get(asset.mime_type) or Path(asset.name).suffix[:8]
        key = f'{_folder(record)}/document{suffix}'
        target = storage_path(key)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copyfile(source, target)
        target.chmod(0o600)
        record.output_key, record.output_name, record.output_mime = key, asset.name[:255], asset.mime_type
        record.output_size, record.output_pages = target.stat().st_size, asset.page_count or 0
        with transaction.atomic():
            record.save(update_fields=['output_key', 'output_name', 'output_mime', 'output_size', 'output_pages'])
        return record
    except Exception:
        logger.exception('Could not keep the AI document of job %s for review', job.pk)
        return record


def request_data(record):
    from .domain import unpack
    try:
        return unpack(record.encrypted_request)
    except Exception:
        logger.exception('Could not read AI request record %s', record.pk)
        return {}


def output_path(record):
    """The kept document, if it is still there."""
    from apps.core.services import storage_path
    if not record.output_key:
        return None
    path = storage_path(record.output_key)
    return path if path.is_file() else None


def page_image(record, page):
    """One page of a kept PDF as a PNG, rendered once and cached beside it."""
    import tempfile
    from apps.core.services import storage_path
    from processors.sandbox import execute_sandbox
    source = output_path(record)
    if not source or record.output_mime != 'application/pdf' or not 1 <= page <= max(record.output_pages, 1):
        return None
    cached = storage_path(f'{_folder(record)}/pages/{page}.png')
    if cached.is_file():
        return cached
    scratch_root = storage_path('scratch')
    scratch_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix='review-', dir=scratch_root) as scratch:
        result = execute_sandbox('pdf.to_images', [source], {'pages': str(page), 'format': 'png', 'dpi': 96},
                                 Path(scratch) / 'render')
        produced = Path(result['artifacts'][0]['path'])
        if result['artifacts'][0]['mime_type'] == 'application/zip':
            import zipfile
            with zipfile.ZipFile(produced) as archive:
                payload = archive.read(f'page-{page:04d}.png')
        else:
            payload = produced.read_bytes()
    cached.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    cached.write_bytes(payload)
    cached.chmod(0o600)
    return cached


def cleanup(now=None):
    """Delete records past their review period, and folders no record owns."""
    from apps.core.services import storage_path
    from .models import GenerationRecord
    now = now or timezone.now()
    for record in GenerationRecord.objects.filter(expires_at__lte=now).iterator():
        shutil.rmtree(storage_path(_folder(record)), ignore_errors=True)
        record.delete()
    root = storage_path(PREFIX)
    if not root.is_dir():
        return
    # A deleted account takes its records with it; its folders go here.
    known = {str(pk) for pk in GenerationRecord.objects.values_list('pk', flat=True)}
    for account_dir in root.iterdir():
        if not account_dir.is_dir() or account_dir.is_symlink():
            continue
        for record_dir in account_dir.iterdir():
            if record_dir.is_dir() and not record_dir.is_symlink() and record_dir.name not in known:
                shutil.rmtree(record_dir, ignore_errors=True)
