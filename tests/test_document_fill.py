"""A document asked for in N pages is delivered in N pages, even when the model writes short.

In production seven sections, each asked for a page, came back as five pages:
the model wrote about two thirds of what it was asked for. A document that
renders short gets one more call that only adds text to its sections.
"""
import json

import pytest

from apps.core.services import execute_job, submit_job
from apps.studio import filling
from apps.studio.domain import create_draft, generation_quote
from apps.studio.models import ProviderAttempt
from operations.integrations import save_config
from tests.test_page_fill import body_of
from tests.test_platform import account
from tests.test_provider_contract import CONFIG
from tests.test_provider_optimization import transport
from tests.test_studio import paid

pytestmark = pytest.mark.django_db


def written(chars):
    """A model's answer: every section of the outline holds `chars` of prose."""
    def answer(body):
        sent = json.loads(body['input'])
        return {'title': 'Tides', 'answer_supported': True, 'sections': [
            {'id': s['id'], 'heading': 'Tides' if n == 0 else '', 'body': body_of(chars, 'long')}
            for n, s in enumerate(sent['outline']['sections'])]}
    return answer


def additions(chars):
    def answer(body):
        sent = json.loads(body['input'])
        assert sent['words_to_add'] > 0
        return {'sections': [{'id': s['id'], 'addition': body_of(chars, 'long')} for s in sent['sections']]}
    return answer


def run(settings, monkeypatch, write, extend=None, prompt='A 5 page guide to tides.'):
    settings.DEBUG = True
    customer = paid(settings, account())
    save_config('ai', {'mode': 'openai', 'model': CONFIG['model'], 'api_key': 'offline-only'})
    calls = []

    def handler(body, number):
        if body['text']['format']['name'] == 'additions':
            calls.append('expand')
            if isinstance(extend, Exception):
                raise extend
            return extend(body)
        calls.append('write')
        return write(body)

    transport(monkeypatch, handler)
    draft = create_draft(customer, {'prompt': prompt})
    quote = generation_quote(customer, draft.id, draft.version)
    job, _ = submit_job(customer, quote.id, f'fill-{draft.id}')
    job = execute_job(job.id)
    assert job.status == 'succeeded', job.error_code
    return job, calls


def test_a_document_written_short_is_written_further_to_its_pages(settings, monkeypatch):
    job, calls = run(settings, monkeypatch, written(1500), additions(1600))
    assert calls == ['write', 'expand']
    assert job.artifacts.get().file.page_count == 5
    assert set(ProviderAttempt.objects.values_list('stage', flat=True)) == {'generate', 'expand'}


def test_a_full_document_is_not_extended(settings, monkeypatch):
    job, calls = run(settings, monkeypatch, written(3000), additions(1600))
    assert calls == ['write']
    assert job.artifacts.get().file.page_count == 5


def test_a_failed_extension_still_delivers_the_document(settings, monkeypatch):
    job, calls = run(settings, monkeypatch, written(1500), TimeoutError('offline'))
    assert calls == ['write', 'expand']
    assert 0 < job.artifacts.get().file.page_count < 5
    assert ProviderAttempt.objects.get(stage='expand').status == 'failed'


def test_a_document_asked_to_be_short_is_left_short(settings, monkeypatch):
    job, calls = run(settings, monkeypatch, written(1500), additions(1600),
                     prompt='Jinoyat va jazo asarini qisqa qilib PDF qilib bering')
    assert calls == ['write']


def test_how_much_is_missing():
    content = {'sections': [{'id': 's1', 'body': 'x' * 6000}]}
    assert filling.shortfall(content, 3, 3) == 0, 'nothing is missing from a full document'
    assert filling.shortfall(content, 3, 2) > 0
    # A page short is at least most of a page missing, whatever the characters say.
    assert filling.shortfall({'sections': [{'id': 's1', 'body': 'x' * 8400}]}, 3, 2) == 2400
