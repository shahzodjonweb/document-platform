"""Encrypted recovery must save paid work without becoming a shared AI cache."""
import copy
import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.errors import DomainError
from apps.core.models import Job
from apps.core.services import submit_job
from apps.studio import checkpoints
from apps.studio.domain import create_draft, generation_quote, update_draft
from apps.studio.models import GenerationDraft, ProviderCheckpoint
from tests.test_platform import account, upload
from tests.test_studio import content

pytestmark = pytest.mark.django_db


@pytest.fixture
def recovery(settings):
    settings.DEBUG = True
    customer = account()
    draft = create_draft(customer, {'feature_id':'ai.pdf_topic', 'source_text':'A private source sentence.',
                                    'options':{'length':1}})
    quote = generation_quote(customer, draft.id, draft.version)
    job, _ = submit_job(customer, quote.id, 'checkpoint-original')
    body = {'model':'same-model', 'instructions':'Use the provided source.',
            'input':'A private source sentence.', 'text':{'format':{'schema':{'type':'object'}}}}
    result = {'sections':[{'id':'s1', 'body':'The confidential generated response.'}], 'citations':[]}
    calls = []
    def invoke():
        calls.append('network')
        return copy.deepcopy(result), {'input_tokens':100, 'output_tokens':50}
    def validate(value):
        if [section['id'] for section in value['sections']] != ['s1']:
            raise ValueError('invalid_sections')
        if value['citations']:
            raise ValueError('invalid_citations')
    return customer, draft, job, body, result, calls, invoke, validate


def run(fixture, **changes):
    _, draft, job, body, _, _, invoke, validate = fixture
    args = dict(job=job, draft=draft, body=body, stage='generate', span=(0, 1), invoke=invoke, validate=validate)
    args.update(changes)
    return checkpoints.call(**args)


def fail(job):
    Job.objects.filter(pk=job.pk).update(status='failed')
    job.refresh_from_db()


def test_completed_result_is_encrypted_and_only_explicit_retry_reuses_it(recovery):
    customer, draft, job, body, result, calls, _, _ = recovery
    assert run(recovery) == (result, {'input_tokens':100, 'output_tokens':50})
    row = ProviderCheckpoint.objects.get()
    assert b'confidential' not in bytes(row.encrypted_result)
    assert 'private' not in row.request_hash
    assert row.expires_at <= draft.expires_at
    fail(job)
    quote = checkpoints.retry_quote(customer, job.id)
    retried, _ = submit_job(customer, quote.id, 'explicit-retry-once')
    reused, usage = run(recovery, job=retried)
    assert reused == result and usage == {'input_tokens':0, 'output_tokens':0, 'checkpoint_reused':True}
    assert calls == ['network']
    fail(retried)
    fresh_quote = generation_quote(customer, draft.id, draft.version)
    fresh, _ = submit_job(customer, fresh_quote.id, 'brand-new-generation')
    run(recovery, job=fresh)
    assert calls == ['network', 'network']
    assert ProviderCheckpoint.objects.count() == 2


def test_same_job_crash_reentry_reuses_result_without_extending_retention(recovery):
    run(recovery)
    before = ProviderCheckpoint.objects.get().expires_at
    result, usage = run(recovery)
    result['sections'][0]['body'] = 'Changed only in memory.'
    assert run(recovery)[0]['sections'][0]['body'] == 'The confidential generated response.'
    assert usage['checkpoint_reused'] is True and recovery[5] == ['network']
    assert ProviderCheckpoint.objects.get().expires_at == before


@pytest.mark.parametrize('change', [
    {'model':'other-model'}, {'instructions':'New schema/prompt rules.'}, {'input':'Customer edited source.'},
    {'text':{'format':{'schema':{'type':'array'}}}},
])
def test_effective_request_change_never_reuses_old_result(recovery, change):
    run(recovery)
    run(recovery, body={**recovery[3], **change})
    assert recovery[5] == ['network', 'network']


def test_stage_and_span_are_part_of_identity(recovery):
    run(recovery)
    run(recovery, stage='outline')
    run(recovery, span=(1, 2))
    assert len(recovery[5]) == 3


def test_partial_document_recovery_only_calls_missing_batch(recovery):
    customer, _, job, _, _, calls, *_ = recovery
    run(recovery, span=(0, 1))
    def unavailable():
        raise DomainError('provider_failed', 502, retryable=True)
    with pytest.raises(DomainError):
        run(recovery, span=(1, 2), invoke=unavailable)
    fail(job)
    quote = checkpoints.retry_quote(customer, job.id)
    second, _ = submit_job(customer, quote.id, 'recover-second-batch')
    assert run(recovery, job=second, span=(0, 1))[1]['checkpoint_reused'] is True
    assert run(recovery, job=second, span=(1, 2))[1]['output_tokens'] == 50
    assert calls == ['network', 'network']
    # Rendering may fail after both calls. A second explicit recovery reuses
    # the whole document, while keeping the original root and retention.
    fail(second)
    quote = checkpoints.retry_quote(customer, second.id)
    third, _ = submit_job(customer, quote.id, 'recover-render-failure')
    assert third.parameters[checkpoints.ROOT_FIELD] == str(job.id)
    assert run(recovery, job=third, span=(0, 1))[1]['checkpoint_reused'] is True
    assert run(recovery, job=third, span=(1, 2))[1]['checkpoint_reused'] is True
    assert calls == ['network', 'network']


@pytest.mark.parametrize('bad', [
    {'sections':[{'id':'wrong', 'body':'bad'}], 'citations':[]},
    {'sections':[{'id':'s1', 'body':'bad'}], 'citations':[{'quote':'invented'}]},
])
def test_invalid_response_is_not_persisted_and_next_retry_can_rebuild(recovery, bad):
    def invoke():
        return bad, {'input_tokens':100, 'output_tokens':30}
    with pytest.raises(ValueError):
        run(recovery, invoke=invoke)
    row = ProviderCheckpoint.objects.get()
    assert row.status == 'pending' and bytes(row.encrypted_result) == b'' and row.lease_token is None
    run(recovery)
    assert ProviderCheckpoint.objects.get().status == 'completed'


def test_failed_call_releases_claim_without_recording_private_result(recovery):
    def crash():
        raise DomainError('provider_failed', 502, retryable=True)
    with pytest.raises(DomainError):
        run(recovery, invoke=crash)
    row = ProviderCheckpoint.objects.get()
    assert row.lease_until is None and not bytes(row.encrypted_result)
    run(recovery)
    assert recovery[5] == ['network']


def test_competing_call_cannot_make_second_paid_request(recovery):
    def first_call():
        with pytest.raises(DomainError, match='provider_failed'):
            run(recovery)
        assert recovery[5] == []
        return recovery[4], {'input_tokens':100, 'output_tokens':50}
    run(recovery, invoke=first_call)
    assert ProviderCheckpoint.objects.get().status == 'completed'


def test_expired_lease_can_be_reclaimed(recovery):
    run(recovery)
    ProviderCheckpoint.objects.update(status='pending', encrypted_result=b'', lease_token=uuid.uuid4(),
                                       lease_until=timezone.now()-timedelta(seconds=1))
    run(recovery)
    assert len(recovery[5]) == 2


def test_lost_claim_cannot_overwrite_newer_worker_result(recovery):
    def superseded():
        ProviderCheckpoint.objects.update(lease_token=uuid.uuid4())
        return recovery[4], {'input_tokens':100, 'output_tokens':50}
    with pytest.raises(DomainError, match='provider_failed'):
        run(recovery, invoke=superseded)
    assert bytes(ProviderCheckpoint.objects.get().encrypted_result) == b''


def test_cache_read_revalidates_and_deletes_corrupt_checkpoint(recovery):
    run(recovery)
    ProviderCheckpoint.objects.update(encrypted_result=b'not-a-fernet-envelope')
    with pytest.raises(DomainError, match='provider_failed'):
        run(recovery)
    assert not ProviderCheckpoint.objects.exists()
    run(recovery)
    assert len(recovery[5]) == 2


def test_cache_read_revalidates_citations(recovery):
    run(recovery)
    def stricter(value):
        raise ValueError('new_validation_rules')
    with pytest.raises(DomainError, match='provider_failed'):
        run(recovery, validate=stricter)
    assert not ProviderCheckpoint.objects.exists()


def test_expiry_prevents_reuse_and_cleanup_removes_encrypted_content(recovery):
    run(recovery)
    ProviderCheckpoint.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
    checkpoints.cleanup_expired()
    assert not ProviderCheckpoint.objects.exists()
    run(recovery)
    assert len(recovery[5]) == 2


def test_expired_draft_never_invokes_or_reuses(recovery):
    run(recovery)
    draft = recovery[1]
    draft.expires_at = timezone.now()-timedelta(seconds=1)
    draft.save(update_fields=['expires_at'])
    with pytest.raises(DomainError, match='version_conflict'):
        run(recovery)
    assert len(recovery[5]) == 1


def test_old_lineage_does_not_extend_checkpoint_retention(recovery):
    Job.objects.filter(pk=recovery[2].pk).update(created_at=timezone.now()-timedelta(hours=25))
    run(recovery)
    run(recovery)
    assert len(recovery[5]) == 2 and not ProviderCheckpoint.objects.exists()


@pytest.mark.parametrize('status', ['queued', 'running', 'canceled', 'succeeded', 'expired'])
def test_retry_quote_only_accepts_failed_jobs(recovery, status):
    customer, _, job, *_ = recovery
    Job.objects.filter(pk=job.pk).update(status=status)
    with pytest.raises(DomainError, match='not_found'):
        checkpoints.retry_quote(customer, job.id)


def test_retry_quote_is_owner_scoped_and_rejects_changed_draft(recovery):
    customer, draft, job, *_ = recovery
    fail(job)
    with pytest.raises(DomainError, match='not_found'):
        checkpoints.retry_quote(account(43), job.id)
    update_draft(customer, draft.id, {'version':draft.version, 'content':content()})
    with pytest.raises(DomainError, match='version_conflict'):
        checkpoints.retry_quote(customer, job.id)


def test_retry_quote_revalidates_uploaded_source_retention(recovery):
    customer, _, original, *_ = recovery
    fail(original)
    asset = upload(customer)
    draft = create_draft(customer, {'feature_id':'ai.pdf_topic', 'prompt':'Summarize',
                                    'source_ids':[str(asset.id)], 'options':{'length':1}})
    quote = generation_quote(customer, draft.id, draft.version)
    job, _ = submit_job(customer, quote.id, 'source-retention-checkpoint')
    fail(job)
    asset.expires_at = timezone.now()-timedelta(seconds=1)
    asset.save(update_fields=['expires_at'])
    with pytest.raises(DomainError, match='file_unavailable'):
        checkpoints.retry_quote(customer, job.id)


def test_retry_chain_cannot_reference_foreign_root_or_draft(recovery):
    run(recovery)
    _, draft, job, *_ = recovery
    forged = copy.copy(job)
    forged.parameters = {**job.parameters, checkpoints.ROOT_FIELD:str(uuid.uuid4())}
    with pytest.raises(DomainError, match='not_found'):
        run(recovery, job=forged)
    draft.account = account(43)
    with pytest.raises(DomainError, match='not_found'):
        run(recovery, draft=draft)
    assert len(recovery[5]) == 1


def test_request_fingerprint_never_accepts_credentials(recovery):
    with pytest.raises(ValueError, match='credentials'):
        run(recovery, body={**recovery[3], 'api_key':'never-record-this'})
    assert not ProviderCheckpoint.objects.exists()


def test_deleting_draft_cascades_private_checkpoints(recovery):
    run(recovery)
    GenerationDraft.objects.filter(pk=recovery[1].pk).delete()
    assert not ProviderCheckpoint.objects.exists()
