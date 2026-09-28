"""Content-free, per-attempt usage accounting. Never persist provider payloads."""
import hashlib
import re
import uuid
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import ProviderAttempt

TOKEN_FIELDS = ('input_tokens', 'output_tokens', 'total_tokens', 'cached_input_tokens',
                'cache_write_input_tokens', 'reasoning_output_tokens')
TERMINAL = {'succeeded', 'rejected', 'failed'}


def _metadata(value, limit):
    # Only provider identifiers, never arbitrary error strings or response text.
    return value if isinstance(value, str) and len(value) <= limit and re.fullmatch(r'[A-Za-z0-9_.:/-]+', value) else ''


def _count(value):
    return value if type(value) is int and 0 <= value <= 2**63 - 1 else None


def _subset(value, parent):
    value = _count(value)
    return value if parent is not None and value is not None and value <= parent else None


def _consistent(values):
    """Keep totals and subsets coherent when partial responses are combined."""
    values = dict(values)
    inp, out = values['input_tokens'], values['output_tokens']
    if inp is not None and out is not None:
        values['total_tokens'] = _count(inp + out)
    for field, parent in (('cached_input_tokens', inp), ('cache_write_input_tokens', inp),
                          ('reasoning_output_tokens', out)):
        values[field] = _subset(values[field], parent)
    cached, written = values['cached_input_tokens'], values['cache_write_input_tokens']
    if cached is not None and written is not None and cached + written > inp:
        values['cached_input_tokens'] = values['cache_write_input_tokens'] = None
    return values


def start_attempt(request_id, feature_id, model, *, stage='generate', span=None,
                  provider='openai', job=None, account=None, output_locale=None, origin_channel=None):
    """Call immediately before sending a provider request, after local checks.

    Passing the job is preferred. The UUID prefix fallback supports existing
    per-batch idempotency keys. Demographic metadata is a snapshot so deleting
    a job/account cannot erase or reclassify historical usage.
    """
    if job is None:
        from apps.core.models import Job
        try:
            job_id = uuid.UUID(str(request_id)[:36])
        except (ValueError, TypeError, AttributeError):
            job_id = None
        if job_id:
            job = Job.objects.select_related('account').filter(pk=job_id).first()
    if account is None and job is not None:
        account = job.account
    locale = output_locale or getattr(account, 'locale', '')
    channel = origin_channel or getattr(job, 'origin_channel', '') or getattr(account, 'first_verified_channel', '')
    first, last = span if span is not None else (None, None)
    return ProviderAttempt.objects.create(
        job=job, request_key=hashlib.sha256(str(request_id).encode()).hexdigest(),
        provider=_metadata(provider, 24) or 'unknown', feature_id=_metadata(feature_id, 100),
        requested_model=_metadata(model, 100), stage=_metadata(stage, 24) or 'generate',
        span_start=first, span_end=last,
        environment=('development' if account.is_test else 'production') if account is not None else 'unknown',
        locale=locale if locale in {'en', 'uz', 'ru'} else '',
        origin_channel=channel if channel in {'web', 'bot', 'mini_app'} else '',
    )


def _usage(result):
    usage = result.get('usage')
    usage = usage if isinstance(usage, dict) else {}
    inp, out = _count(usage.get('input_tokens')), _count(usage.get('output_tokens'))
    inputs, outputs = usage.get('input_tokens_details'), usage.get('output_tokens_details')
    inputs = inputs if isinstance(inputs, dict) else {}
    outputs = outputs if isinstance(outputs, dict) else {}
    cached = _subset(inputs.get('cached_tokens', usage.get('cache_read_input_tokens')), inp)
    written = _subset(inputs.get('cache_write_tokens', inputs.get('cache_creation_tokens', usage.get('cache_creation_input_tokens'))), inp)
    return _consistent(dict(input_tokens=inp, output_tokens=out, total_tokens=_count(usage.get('total_tokens')),
                            cached_input_tokens=cached, cache_write_input_tokens=written,
                            reasoning_output_tokens=_subset(outputs.get('reasoning_tokens'), out)))


@transaction.atomic
def received(attempt, result, elapsed_ms):
    """Record usage before checking completion, schema or application limits.

    Network attempts sharing a provider response ID are retained, but token
    totals count the response once. A unique key resolves concurrent replays.
    """
    current = ProviderAttempt.objects.select_for_update().get(pk=attempt.pk)
    if current.status in TERMINAL:
        return current
    result = result if isinstance(result, dict) else {}
    values = _usage(result)
    response_id = _metadata(result.get('id'), 255)
    current.response_id = response_id
    current.resolved_model = _metadata(result.get('model'), 100)
    current.provider_status = _metadata(result.get('status'), 24)
    current.latency_ms = _count(elapsed_ms)
    current.received_at = timezone.now()
    current.status = 'received'
    for field, value in values.items():
        setattr(current, field, value)
    if response_id:
        key = hashlib.sha256((current.provider + ':' + response_id).encode()).hexdigest()
        canonical = ProviderAttempt.objects.filter(response_key=key).exclude(pk=current.pk).first()
        if canonical is None:
            try:
                # Isolate a possible unique-key race from the outer transaction.
                with transaction.atomic():
                    current.response_key = key
                    current.save()
            except IntegrityError:
                canonical = ProviderAttempt.objects.get(response_key=key)
        if canonical is not None:
            current.response_key = None
            current.duplicate_response = True
            current.duplicate_of = canonical
            # A replay can include usage absent from the first response. Fill
            # gaps only; never replace an already-reported count with a guess.
            canonical = ProviderAttempt.objects.select_for_update().get(pk=canonical.pk)
            merged = _consistent({field: getattr(canonical, field) if getattr(canonical, field) is not None
                                  else values[field] for field in TOKEN_FIELDS})
            for field, value in merged.items():
                setattr(canonical, field, value)
            # A first response may omit the resolved model as well as usage.
            if not canonical.resolved_model:
                canonical.resolved_model = current.resolved_model
            canonical.save(update_fields=[*TOKEN_FIELDS, 'resolved_model'])
    current.save()
    return current


@transaction.atomic
def finish(attempt, status, *, elapsed_ms=None):
    if status not in TERMINAL:
        raise ValueError('Invalid provider attempt status')
    current = ProviderAttempt.objects.select_for_update().get(pk=attempt.pk)
    if current.status not in TERMINAL:
        current.status = status
        current.finished_at = timezone.now()
        if elapsed_ms is not None:
            current.latency_ms = _count(elapsed_ms)
        current.save(update_fields=['status', 'finished_at', 'latency_ms'])
    return current


def cleanup_attempts(*, retention_days=90, batch_size=1000):
    """Bound deletion work per cleanup tick; retain only metadata for 90 days."""
    if not 1 <= retention_days <= 366 or not 1 <= batch_size <= 10000:
        raise ValueError('Invalid provider usage retention bounds')
    ids = list(ProviderAttempt.objects.filter(created_at__lt=timezone.now() - timedelta(days=retention_days))
               .order_by('created_at').values_list('pk', flat=True)[:batch_size])
    ProviderAttempt.objects.filter(pk__in=ids).delete()
    return len(ids)
