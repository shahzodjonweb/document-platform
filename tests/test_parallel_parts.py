"""Long new documents planned in one short call, then written in parts side by side (provider.generate).

Off unless the admin switches it on (Admin → Integrations). A call takes about
as long as the words it writes, so parts written one after another wait for
each other's words; planned first, they are written at once. A plan that
cannot be had leaves the job written one part after another, as before.
"""
import json
import time
import urllib.error

import pytest

from apps.core.services import execute_job, submit_job
from apps.studio import execution, photos, provider
from apps.studio.domain import create_draft, generation_quote, unpack
from apps.studio.models import GenerationDraft, ProviderAttempt
from operations.integrations import ai_config, save_config
from tests.test_generation_quality import model, reply, sent
from tests.test_platform import account
from tests.test_provider_contract import CONFIG
from tests.test_studio import paid

pytestmark = pytest.mark.django_db

TOPICS = ['Harbour cranes lift containers', 'Tides decide when ships arrive', 'Pilots guide ships through channels',
          'Customs checks every container', 'Rail links carry boxes inland', 'Night shifts keep the port moving',
          'Storms close the harbour', 'Automation changes dock work', 'Ports compete for shipping lines',
          'The harbour plans its next decade', 'Fishing boats share the water', 'Cruise ships bring visitors']


def written(sid, deck=True):
    n = int(sid[1:]) - 1
    body = (f'{TOPICS[n]} because schedules depend on it every single day.\n'
            f'Port number {n + 1} measures its results each month carefully.\n'
            f'Workers at berth {n + 1} train for new equipment regularly.')
    return {'heading': TOPICS[n], 'body': body if deck else (body + ' ') * 6, 'notes': f'Explain point {n + 1}.'}


def planned(body):
    """A plan as the strict schema asks: each section's heading, and a deck's layout and photo subject."""
    fields = body['text']['format']['schema']['properties']['sections']['items']['properties']
    rows = []
    for n, section in enumerate(sent(body)['outline']['sections']):
        row = {'id': section['id'], 'heading': TOPICS[n]}
        if 'layout' in fields:
            row['layout'] = 'bullets'
        if 'image_query' in fields:
            row['image_query'] = ''
        if 'body' in fields:
            row['body'] = f'Covers {TOPICS[n].lower()}.'
        rows.append(row)
    return {'title': 'Harbours at work', 'sections': rows}


def run(settings, monkeypatch, *, pages, fmt='pptx', parallel=True, plan=planned, prompt=None):
    settings.DEBUG = True
    customer = paid(settings, account())
    save_config('ai', {'mode': 'openai', 'model': CONFIG['model'], 'api_key': 'sk-offline-test-only',
                       'parallel_parts': 'true' if parallel else 'false'})
    calls = []

    def answer(body, number):
        name = body['text']['format']['name']
        calls.append((name, body))
        if name == 'plan':
            return plan(body)
        if name == 'additions':
            return {'sections': [{'id': s['id'], 'addition': ''} for s in sent(body)['sections']]}
        return reply(body, {s['id']: written(s['id'], fmt == 'pptx') for s in sent(body)['outline']['sections']},
                     title='Harbours at work')
    model(monkeypatch, answer)
    feature = 'ai.pptx' if fmt == 'pptx' else 'ai.pdf_topic'
    draft = create_draft(customer, {'feature_id': feature, 'prompt': prompt or 'How a modern harbour works', 'output_locale': 'en',
                                    'options': {'pages': pages}})
    quote = generation_quote(customer, draft.id, draft.version)
    job, _ = submit_job(customer, quote.id, f'parallel-{fmt}-{pages}-{parallel}')
    job = execute_job(job.id)
    return job, calls


def stages(job):
    return list(ProviderAttempt.objects.filter(job=job).exclude(stage__in=['expand', 'repair', 'photo_pick'])
                .order_by('created_at', 'span_start').values_list('stage', 'span_start', 'span_end', 'status'))


def test_it_is_off_unless_the_admin_switches_it_on(settings, monkeypatch):
    settings.DEBUG = True
    save_config('ai', {'mode': 'local_fixture', 'model': 'm'})
    assert ai_config()['parallel_parts'] is False
    job, calls = run(settings, monkeypatch, pages=10, parallel=False)
    assert job.status == 'succeeded', job.error_code
    assert [name for name, _ in calls] == ['document']
    assert [stage for stage, *_ in stages(job)] == ['generate']


def test_a_long_deck_is_planned_then_written_in_parts_at_once(settings, monkeypatch):
    job, calls = run(settings, monkeypatch, pages=10)
    assert job.status == 'succeeded', job.error_code
    assert [name for name, _ in calls] == ['plan', 'document', 'document']
    assert stages(job) == [('plan', 0, 10, 'succeeded'), ('generate', 0, 5, 'succeeded'), ('generate', 5, 10, 'succeeded')]
    plan_body = calls[0][1]
    fields = plan_body['text']['format']['schema']['properties']['sections']['items']['properties']
    assert set(fields) == {'id', 'heading', 'layout', 'image_query'}, 'a plan writes no slide text'
    assert 'Plan 10 slides only' in sent(plan_body)['writing_guidance']
    assert plan_body['max_output_tokens'] < 6000
    first, second = (json.loads(body['input']) for _, body in calls[1:])
    # Each part sees the whole plan, writes its own slides on the planned points, and continues nothing.
    assert first['document_plan'] == second['document_plan'] == TOPICS[:10]
    assert [s['heading'] for s in second['outline']['sections']] == TOPICS[5:10]
    assert 'at the same time as other calls' in second['writing_guidance'] and 'already_written' not in second
    assert 'Open the document here' in first['writing_guidance'] and 'End the document here' in second['writing_guidance']
    # Only the first part chooses the deck's design, as before.
    assert 'design' in calls[1][1]['text']['format']['schema']['properties']
    assert 'design' not in calls[2][1]['text']['format']['schema']['properties']
    sections = unpack(GenerationDraft.objects.get().encrypted_data)['content']['sections']
    assert [s['id'] for s in sections] == [f's{n}' for n in range(1, 11)]
    assert [s['heading'] for s in sections] == TOPICS[:10]


def test_a_short_deck_is_written_as_before(settings, monkeypatch):
    job, calls = run(settings, monkeypatch, pages=provider.PARALLEL_FROM - 1)
    assert job.status == 'succeeded' and [name for name, _ in calls] == ['document']


@pytest.mark.parametrize('failure', ['ids', 'http'])
def test_a_plan_that_cannot_be_had_leaves_the_parts_written_one_after_another(settings, monkeypatch, failure):
    def plan(body):
        if failure == 'http':
            raise urllib.error.HTTPError('https://api.openai.com/v1/responses', 500, 'error', {}, None)
        return {'title': 'x', 'sections': [{'id': 'zz', 'heading': 'h', 'layout': 'bullets', 'image_query': ''}]}
    job, calls = run(settings, monkeypatch, pages=12, plan=plan)
    assert job.status == 'succeeded', job.error_code
    assert [name for name, _ in calls] == ['plan', 'document', 'document']
    assert [(stage, status) for stage, _, _, status in stages(job)] == [('plan', 'failed' if failure == 'http' else 'rejected'),
                                                                     ('generate', 'succeeded'), ('generate', 'succeeded')]
    # Written in the old way: the second part continues from what the first wrote.
    assert 'already_written' in json.loads(calls[2][1]['input'])
    assert job.error_code == ''


def test_a_long_document_is_planned_with_a_note_per_section(settings, monkeypatch):
    def plan(body):
        assert 'Plan 9 sections only' in sent(body)['writing_guidance']
        fields = body['text']['format']['schema']['properties']['sections']['items']['properties']
        assert set(fields) == {'id', 'heading', 'body'} and fields['body']['maxLength'] <= 200
        return {'title': 'Harbours', 'sections': [{'id': s['id'], 'heading': TOPICS[n], 'body': f'Covers {TOPICS[n].lower()}.'}
                                                  for n, s in enumerate(sent(body)['outline']['sections'])]}
    job, calls = run(settings, monkeypatch, pages=9, fmt='pdf', plan=plan, prompt='A 9 page guide to how a harbour works')
    assert job.status == 'succeeded', job.error_code
    names = [name for name, _ in calls if name != 'additions']
    assert names == ['plan', 'document', 'document', 'document']
    parts = [json.loads(body['input']) for name, body in calls if name == 'document']
    assert [s['body'] for s in parts[1]['outline']['sections']] == [f'Covers {TOPICS[n].lower()}.' for n in (3, 4, 5)]


def test_a_change_is_never_planned():
    data = {'revision': {'request': 'shorter'}, 'content': {'sections': [{'id': f's{n}'} for n in range(20)]}}
    assert not provider.parallel_wanted({'parallel_parts': True}, data, 'ai.pptx')
    assert provider.parallel_wanted({'parallel_parts': True}, {**data, 'revision': None}, 'ai.pptx')
    assert not provider.parallel_wanted({'parallel_parts': True}, {**data, 'revision': None}, 'ai.cv')
    assert not provider.parallel_wanted({}, {**data, 'revision': None}, 'ai.pptx')


def test_a_decks_photos_are_fetched_from_its_plan_before_its_slides_are_written(settings, monkeypatch):
    order = []
    real = execution._photos

    def fetching(job, sections, warnings, style='photo', candidates=None):
        order.append(('photos', [s.get('heading') for s in sections][:2]))
        return real(job, sections, warnings, style, candidates)
    monkeypatch.setattr(execution, '_photos', fetching)
    job, calls = run(settings, monkeypatch, pages=10)
    assert job.status == 'succeeded', job.error_code
    assert stages(job)[0] == ('plan', 0, 10, 'succeeded')
    # Once, from the plan, before any slide was written: not again after writing.
    assert order == [('photos', TOPICS[:2])]
    assert [name for name, _ in calls] == ['plan', 'document', 'document']


def test_parts_run_at_once_outside_the_test_database(settings):
    settings.LOCAL_SYNC_JOBS = False
    started = time.monotonic()
    results = provider.side_by_side([lambda n=n: (time.sleep(0.3), n)[1] for n in range(4)])
    assert results == [0, 1, 2, 3] and time.monotonic() - started < 0.9


def test_the_parts_of_a_document_written_side_by_side():
    assert provider.parallel_spans(10, 'pptx') == [(0, 5), (5, 10)]
    assert provider.parallel_spans(10, 'pdf') == [(0, 3), (3, 6), (6, 8), (8, 10)]
    assert len(provider.parallel_spans(60, 'pptx')) == provider.MAX_PARALLEL_PARTS


def test_the_switch_is_saved_from_the_admin_form(settings):
    settings.DEBUG = True
    save_config('ai', {'mode': 'local_fixture', 'model': 'm', 'parallel_parts': 'true'})
    assert ai_config()['parallel_parts'] is True
    save_config('ai', {'mode': 'local_fixture', 'model': 'm'})
    assert ai_config()['parallel_parts'] is True, 'kept when the form did not send it'
    save_config('ai', {'mode': 'local_fixture', 'model': 'm', 'parallel_parts': 'false'})
    assert ai_config()['parallel_parts'] is False


@pytest.mark.django_db(transaction=True)
def test_on_postgres_the_parts_and_the_photos_run_at_once(settings, monkeypatch):
    # Production's path: real threads, each with its own database connection.
    import threading
    from django.db import connection
    if connection.vendor != 'postgresql':
        pytest.skip('the threads need a database they can share: run on PostgreSQL')
    settings.LOCAL_SYNC_JOBS = False
    lock, state, threads = threading.Lock(), {'now': 0, 'peak': 0}, set()
    real = execution._photos

    def fetching(job, sections, warnings, style='photo', candidates=None):
        threads.add(('photos', threading.get_ident()))
        return real(job, sections, warnings, style, candidates)
    monkeypatch.setattr(execution, '_photos', fetching)

    def slow_part(body):
        with lock:
            state['now'] += 1
            state['peak'] = max(state['peak'], state['now'])
            threads.add(('part', threading.get_ident()))
        time.sleep(0.3)
        with lock:
            state['now'] -= 1
        return reply(body, {s['id']: written(s['id']) for s in sent(body)['outline']['sections']}, title='Harbours at work')

    settings.DEBUG = True
    customer = paid(settings, account())
    save_config('ai', {'mode': 'openai', 'model': CONFIG['model'], 'api_key': 'sk-offline-test-only', 'parallel_parts': 'true'})
    model(monkeypatch, lambda body, number: planned(body) if body['text']['format']['name'] == 'plan' else slow_part(body))
    draft = create_draft(customer, {'feature_id': 'ai.pptx', 'prompt': 'How a modern harbour works', 'output_locale': 'en',
                                    'options': {'pages': 12}})
    quote = generation_quote(customer, draft.id, draft.version)
    job, _ = submit_job(customer, quote.id, 'parallel-postgres-12')
    job = execute_job(job.id)
    assert job.status == 'succeeded', job.error_code
    assert state['peak'] == 3, 'the three parts ran at once'
    main = threading.get_ident()
    assert all(ident != main for _, ident in threads), 'parts and photos ran off the job thread'
    assert [stage for stage, *_ in stages(job)] == ['plan', 'generate', 'generate', 'generate']
