"""Short-lived encrypted provider results, scoped to one explicit retry chain.

These are recovery checkpoints, not a cache shared by unrelated generations.
Only hashes and lease metadata are plaintext. A provider request runs outside
the claim transaction; a competing worker cannot make the same paid call.
"""
import copy
import hashlib
import json
import uuid
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.errors import DomainError
from apps.core.models import Job
from .domain import pack, unpack
from .models import GenerationDraft, ProviderCheckpoint

ROOT_FIELD = '_provider_retry_root'
RETRY_FIELD = '_provider_retry_of'
VERSION = 'provider-checkpoint-v1'
LEASE_SECONDS = 360  # Longer than the provider's bounded 300-second call.


def _root_job(job, draft):
    """Reject foreign or malformed lineage even if invoked outside the worker."""
    if draft.account_id != job.account_id or str(draft.id) != str(job.parameters.get('generation_draft_id')):
        raise DomainError('not_found', 404)
    try:
        root_id = uuid.UUID(str(job.parameters.get(ROOT_FIELD, job.id)))
    except (TypeError, ValueError, AttributeError):
        raise DomainError('invalid_parameters') from None
    root = Job.objects.filter(pk=root_id, account_id=job.account_id).first()
    if not root or root.feature_id != job.feature_id:
        raise DomainError('not_found', 404)
    # Only the original confirmed draft can participate in this lineage. The
    # effective request hash below also covers every provider-visible change.
    for field in ('generation_draft_id', 'draft_version', 'snapshot', 'stage'):
        if root.parameters.get(field) != job.parameters.get(field):
            raise DomainError('version_conflict', 409)
    if root.id != job.id:
        try:
            parent = Job.objects.filter(pk=job.parameters.get(RETRY_FIELD), account_id=job.account_id,
                                        status='failed').first()
        except (ValidationError, ValueError, TypeError):
            parent = None
        if not parent or str(parent.parameters.get(ROOT_FIELD, parent.id)) != str(root.id):
            raise DomainError('invalid_parameters')
    return root


def retry_quote(account, failed_job_id):
    """Requote unchanged failed generation for explicit user confirmation.

    A retry does not bypass source ownership, retention, model pins, allowance
    checks, or the normal quote/submit reservation path. Editing the draft is a
    new generation intent and must use the ordinary quote route instead.
    """
    from .domain import GENERATION_IDS, generation_quote, validate_generation_quote
    with transaction.atomic():
        try:
            previous = Job.objects.select_for_update().select_related('quote').get(
                pk=failed_job_id, account=account, status='failed', feature_id__in=GENERATION_IDS)
        except (Job.DoesNotExist, ValidationError, ValueError, TypeError):
            raise DomainError('not_found', 404) from None
        draft = GenerationDraft.objects.select_for_update().filter(
            pk=previous.parameters.get('generation_draft_id'), account=account,
            expires_at__gt=timezone.now()).first()
        if not draft:
            raise DomainError('not_found', 404)
        assets = validate_generation_quote(account, previous.quote)
        if [{'id':str(a.pk), 'sha256':a.sha256} for a in assets] != previous.quote.input_fingerprints:
            raise DomainError('file_changed', 409)
        root = _root_job(previous, draft)
        if previous.parameters.get('stage') == 'outline':
            from .outlines import create_outline_quote
            quote = create_outline_quote(account, draft.id, draft.version)
        else:
            quote = generation_quote(account, draft.id, draft.version)
        quote.parameters = {**quote.parameters, ROOT_FIELD:str(root.id), RETRY_FIELD:str(previous.id)}
        quote.save(update_fields=['parameters'])
        return quote


def request_hash(body, stage, span):
    """Hash the credential-free effective request, including schema and model."""
    if any(key.lower() in ('api_key', 'authorization', 'headers') for key in body):
        raise ValueError('provider_credentials_not_allowed')
    value = {'version':VERSION, 'stage':stage, 'span':list(span), 'body':body}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def call(*, job, draft, body, stage, span, invoke, validate, on_reuse=None):
    """Return one validated result, reusing only a completed matching checkpoint.

    ``invoke`` returns (content, usage). ``validate`` must check the response's
    strict schema, section identities/count, and source citations; it may return
    a canonical content object, or None to retain the validated input. Validation
    runs before writing and after decrypting, so stale validation assumptions
    cannot turn a checkpoint into a provider-validation bypass.
    """
    root = _root_job(job, draft)
    now = timezone.now()
    expires = min(draft.expires_at, root.created_at + timedelta(hours=24))
    if draft.expires_at <= now:
        raise DomainError('version_conflict', 409)
    # A very old lineage still can be retried while its draft is valid, but its
    # old result must not outlive the original 24-hour retention window.
    if expires <= now:
        result, usage = invoke()
        canonical = validate(result)
        return (result if canonical is None else canonical), usage
    first, last = span
    if type(first) is not int or type(last) is not int or first < 0 or last <= first:
        raise ValueError('invalid_provider_span')
    digest = request_hash(body, stage, span)
    token = uuid.uuid4()
    with transaction.atomic():
        row, _ = ProviderCheckpoint.objects.select_for_update().get_or_create(
            account_id=job.account_id, root_job=root, request_hash=digest,
            defaults={'draft':draft, 'stage':stage, 'span_start':first, 'span_end':last,
                      'expires_at':expires})
        encrypted = bytes(row.encrypted_result) if row.status == 'completed' and row.expires_at > now else None
        if encrypted is None:
            if row.lease_until and row.lease_until > now:
                raise DomainError('provider_failed', 503, retryable=True)
            row.status, row.lease_token = 'pending', token
            row.lease_until = min(expires, now + timedelta(seconds=LEASE_SECONDS))
            row.encrypted_result, row.expires_at = b'', expires
            row.save(update_fields=['status', 'lease_token', 'lease_until', 'encrypted_result', 'expires_at'])
    if encrypted is not None:
        try:
            result = unpack(encrypted)
            canonical = validate(result)
            result = result if canonical is None else canonical
        except Exception:
            # Corrupt or newly invalid data is never reused. Release the entry
            # so an explicit retry can safely rebuild it on its next attempt.
            ProviderCheckpoint.objects.filter(pk=row.pk, encrypted_result=encrypted).delete()
            raise DomainError('provider_failed', 502, retryable=True) from None
        if on_reuse is not None:
            on_reuse(result)
        return copy.deepcopy(result), {'input_tokens':0, 'output_tokens':0, 'checkpoint_reused':True}
    try:
        result, usage = invoke()
        canonical = validate(result)
        result = result if canonical is None else canonical
        encrypted = pack(result)
        saved = ProviderCheckpoint.objects.filter(pk=row.pk, lease_token=token,
                                                  expires_at__gt=timezone.now()).update(
            status='completed', encrypted_result=encrypted, lease_token=None, lease_until=None)
        if not saved:
            raise DomainError('provider_failed', 503, retryable=True)
        return result, usage
    except BaseException:
        ProviderCheckpoint.objects.filter(pk=row.pk, lease_token=token).update(
            status='pending', lease_token=None, lease_until=None, encrypted_result=b'')
        raise


def cleanup_expired(now=None):
    ProviderCheckpoint.objects.filter(expires_at__lte=now or timezone.now()).delete()
