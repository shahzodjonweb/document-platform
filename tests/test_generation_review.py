"""AI requests kept for staff review: what was asked, what was made, who looked."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.models import FileAsset
from apps.core.services import cleanup_expired, execute_job, storage_path, submit_job
from apps.studio.domain import DOCUMENT, SLIDES, create_draft, generation_quote
from apps.studio.models import GenerationRecord
from apps.studio.review import REVIEW_DAYS, output_path, request_data
from operations.models import AuditLog
from tests.test_manual_payments import staff_client
from tests.test_platform import account
from tests.test_studio import paid

pytestmark = pytest.mark.django_db
ASKED = 'A 3 page guide to tide tables for sailors.'


@pytest.fixture
def premium(settings):
    settings.DEBUG = True
    return paid(settings, account())


def make(customer, prompt=ASKED, feature=DOCUMENT, fmt='pdf'):
    """An AI document made the way a customer makes one."""
    words = 12 if fmt == 'pptx' else 120
    text = '\n\n'.join(' '.join(['measurement'] * words) for _ in range(3))
    draft = create_draft(customer, {'feature_id': feature, 'output_format': fmt, 'title': 'Tide tables',
                                    'prompt': prompt, 'source_text': text})
    quote = generation_quote(customer, draft.id, draft.version)
    job, _ = submit_job(customer, quote.id, f'review-{draft.id}')
    job = execute_job(job.id)
    assert job.status == 'succeeded', job.error_code
    return job


def test_an_ai_document_leaves_its_request_and_a_copy_for_review(premium):
    record = GenerationRecord.objects.get(job=make(premium))
    asked = request_data(record)
    assert asked['prompt'] == ASKED and asked['title'] == 'Tide tables' and asked['output_format'] == 'pdf'
    assert asked['sections'] and all('body' in s for s in asked['sections'])
    assert record.output_mime == 'application/pdf' and output_path(record).read_bytes()[:4] == b'%PDF'
    assert record.output_key.startswith('review/'), 'outside the customer files the 24-hour backstop sweeps'
    assert (record.expires_at - record.created_at) >= timedelta(days=REVIEW_DAYS) - timedelta(minutes=1)


def test_the_copy_outlives_the_customers_files_and_goes_when_the_review_period_ends(premium):
    record = GenerationRecord.objects.get(job=make(premium))
    FileAsset.objects.filter(account=premium).update(expires_at=timezone.now() - timedelta(seconds=1))
    cleanup_expired()
    assert output_path(record) is not None, "the customer's copy is gone; the review copy stays"
    GenerationRecord.objects.filter(pk=record.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    cleanup_expired()
    assert not GenerationRecord.objects.filter(pk=record.pk).exists()
    assert not storage_path(record.output_key).exists()


def test_recording_never_stands_in_the_customers_way(premium, monkeypatch):
    def refuse(*args, **kwargs):
        raise RuntimeError('storage unavailable')
    monkeypatch.setattr(GenerationRecord.objects, 'create', refuse)
    job = make(premium)
    assert job.status == 'succeeded' and not GenerationRecord.objects.filter(job=job).exists()


def test_slides_are_kept_too_without_a_page_preview(premium):
    record = GenerationRecord.objects.get(job=make(premium, prompt='8 slides on tide tables.', feature=SLIDES, fmt='pptx'))
    assert record.output_mime.endswith('presentationml.presentation') and output_path(record)
    client, _ = staff_client('Support')
    assert client.get(f'/ops/generations/{record.id}/pages/1').status_code == 404
    assert 'gen_no_preview' not in client.get(f'/ops/generations/{record.id}').content.decode()


def test_support_and_operations_review_requests_and_every_opening_is_audited(premium):
    record = GenerationRecord.objects.get(job=make(premium))
    for role in ('Finance', 'Analyst', 'Content manager'):
        client, _ = staff_client(role)
        assert client.get('/ops/generations').status_code == 403, role
        assert client.get(f'/ops/generations/{record.id}').status_code == 403, role
    clients = {role: staff_client(role)[0] for role in ('Support', 'Operations')}
    for client in clients.values():
        listing = client.get('/ops/generations').content.decode()
        assert f'/ops/generations/{record.id}' in listing and 'A 3 page guide to tide tables' in listing
    client = clients['Support']
    assert not AuditLog.objects.filter(action='generation.view').exists(), 'the list alone opens nothing'
    detail = client.get(f'/ops/generations/{record.id}').content.decode()
    assert ASKED in detail and 'Tide tables' in detail
    assert AuditLog.objects.filter(action='generation.view', target=str(record.id)).exists()
    document = client.get(f'/ops/generations/{record.id}/file')
    assert document.status_code == 200 and b''.join(document.streaming_content)[:4] == b'%PDF'
    assert AuditLog.objects.filter(action='generation.file', target=str(record.id)).exists()
    image = client.get(f'/ops/generations/{record.id}/pages/1')
    assert image.status_code == 200 and b''.join(image.streaming_content)[:8] == b'\x89PNG\r\n\x1a\n'


def test_words_in_a_request_find_it(premium):
    make(premium, prompt='Safety notes about volcanoes for hikers, 3 pages.')
    make(premium)
    client, _ = staff_client('Operations')
    found = client.get('/ops/generations?text=VOLCANOES').content.decode()
    assert 'volcanoes' in found and 'tide tables for sailors' not in found


def test_the_customer_page_lists_their_ai_requests(premium):
    record = GenerationRecord.objects.get(job=make(premium))
    client, _ = staff_client('Support')
    page = client.get(f'/ops/users/{premium.id}').content.decode()
    assert f'/ops/generations/{record.id}' in page
