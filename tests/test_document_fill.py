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


def page(chars, n):
    """`chars` of prose that no other page repeats, as a model's pages are."""
    words = body_of(chars, 'long').split()
    return ' '.join(word + 'abcdefghij'[n % 10] for word in words)[:chars]


def written(chars):
    """A model's answer: every section of the outline holds `chars` of prose."""
    def answer(body):
        sent = json.loads(body['input'])
        return {'title': 'Tides', 'answer_supported': True, 'sections': [
            {'id': s['id'], 'heading': 'Tides' if n == 0 else '', 'body': page(chars, n)}
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


# --- A longer document is extended in parts side by side ------------------------------------

def test_a_longer_document_is_extended_in_parts_side_by_side(settings, monkeypatch):
    # A call takes about as long as the words it writes: a third of them each, at once.
    import threading
    import time as clock
    lock, state, sent = threading.Lock(), {'now': 0, 'peak': 0}, []

    def extend(body):
        with lock:
            state['now'] += 1
            state['peak'] = max(state['peak'], state['now'])
        clock.sleep(0.2)
        with lock:
            state['now'] -= 1
            sent.append(json.loads(body['input']))
        return additions(1600)(body)

    job, calls = run(settings, monkeypatch, written(1500), extend, prompt='A 9 page guide to tides.')
    assert calls == ['write', 'expand', 'expand', 'expand']
    assert state['peak'] == 3, 'the three parts ran at once'
    covered = sorted(s['id'] for part in sent for s in part['sections'])
    assert covered == sorted(f's{n}' for n in range(1, 10)), 'every section in exactly one part'
    assert all(len(part['sections']) == 3 and len(part['other_sections']) == 6 for part in sent)
    attempts = ProviderAttempt.objects.filter(stage='expand').order_by('span_start')
    assert [(a.span_start, a.span_end, a.status) for a in attempts] == [(0, 3, 'succeeded'), (3, 6, 'succeeded'), (6, 9, 'succeeded')]
    assert job.artifacts.get().file.page_count == 9


def test_a_part_that_fails_leaves_only_its_own_sections_as_they_were(settings, monkeypatch):
    seen = []

    def extend(body):
        part = json.loads(body['input'])
        seen.append([s['id'] for s in part['sections']])
        if part['sections'][0]['id'] == 's4':
            raise TimeoutError('offline')
        return additions(1600)(body)

    job, calls = run(settings, monkeypatch, written(1500), extend, prompt='A 9 page guide to tides.')
    assert calls.count('expand') == 3
    statuses = dict(ProviderAttempt.objects.filter(stage='expand').values_list('span_start', 'status'))
    assert statuses == {0: 'succeeded', 3: 'failed', 6: 'succeeded'}
    from apps.studio.domain import unpack
    from apps.studio.models import GenerationDraft
    sections = unpack(GenerationDraft.objects.get().encrypted_data)['content']['sections']
    lengths = [len(s['body']) for s in sections]
    assert all(lengths[n] > 1500 for n in (0, 1, 2, 6, 7, 8)) and all(lengths[n] <= 1500 for n in (3, 4, 5))


def test_the_parts_of_a_document():
    assert filling.parts(list(range(5))) == [(0, 5)], 'below six sections, one call as before'
    assert filling.parts(list(range(7))) == [(0, 3), (3, 5), (5, 7)]
    assert filling.parts(list(range(35))) == [(0, 9), (9, 18), (18, 27), (27, 35)], 'never more than four calls'
