"""Exercise optimized prompts through the real provider boundary, without paid calls."""
import copy
import json

import pytest

from apps.core.errors import DomainError
from apps.core.models import Job
from apps.core.services import submit_job
from apps.studio import provider, checkpoints
from apps.studio.domain import create_draft, generation_quote, unpack
from apps.studio.models import ProviderAttempt, ProviderCheckpoint
from apps.studio.revisions import source_seed
from operations.integrations import save_config
from tests.test_platform import account, login_client
from tests.test_studio import paid
from tests.test_provider_contract import CONFIG, draft

pytestmark = pytest.mark.django_db


def transport(monkeypatch, handler):
    requests = []
    class Response:
        def __init__(self, result): self.result = result
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return json.dumps(self.result).encode()
    class Opener:
        def open(self, request, timeout):
            body = json.loads(request.data)
            requests.append(body)
            raw = handler(body, len(requests))
            return Response({'id': f'resp_offline_{len(requests)}', 'model': CONFIG['model'],
                             'status': 'completed', 'output': [{'type': 'message', 'content': [
                                 {'type': 'output_text', 'text': json.dumps(raw)}]}],
                             'usage': {'input_tokens': 120, 'output_tokens': 80,
                                       'input_tokens_details': {'cached_tokens': 40},
                                       'output_tokens_details': {'reasoning_tokens': 10}}})
    monkeypatch.setattr(provider.urllib.request, 'build_opener', lambda _: Opener())
    return requests


def pdf_answer(body):
    sent = json.loads(body['input'])
    return {'title': 'Generated', 'answer_supported': True,
            'sections': [{'id': s['id'], 'heading': s['heading'], 'body': 'Reviewed content.'}
                         for s in sent['outline']['sections']]}


@pytest.mark.parametrize('locale,text', [('en', 'Exact  source.\nSecond line.'),
                                       ('uz', 'O‘zbekcha  manba.\nIkkinchi satr.'),
                                       ('ru', 'Точный  источник.\nВторая строка.')])
def test_compaction_keeps_source_bytes_and_authored_content(locale, text):
    data = draft(1)
    data['output_locale'], data['source_text'] = locale, text
    data['content']['sections'][0]['body'] = text
    data['_source_seed'] = source_seed(data)
    data['options'].update(template_style={'accent': '#123456'}, font_family='Private Font', branding_id='internal')
    body = provider.request_body(CONFIG, data, 'ai.pdf_topic')
    sent = json.loads(body['input'])
    assert sent['source_text'] == text
    assert sent['outline']['sections'][0]['body'] == ''
    assert set(sent['options']) == {'length', 'question_count'}
    assert data['content']['sections'][0]['body'] == text
    data['content']['sections'][0]['body'] += ' Authored addition.'
    assert json.loads(provider.request_body(CONFIG, data, 'ai.pdf_topic')['input'])['outline']['sections'][0]['body'] == text + ' Authored addition.'


def test_outline_uses_a_bounded_coverage_contract_and_keeps_final_slide_notes():
    data = draft(5, 'pptx')
    planned = provider.request_body(CONFIG, data, 'ai.outline')
    final = provider.request_body(CONFIG, data, 'ai.pptx')
    schema = planned['text']['format']['schema']['properties']
    assert 'notes' not in schema['sections']['items']['properties'] and 'questions' not in schema
    assert schema['sections']['items']['properties']['body']['maxLength'] == 500
    assert 'notes' in final['text']['format']['schema']['properties']['sections']['items']['properties']
    assert planned['max_output_tokens'] < final['max_output_tokens']
    assert '392 words' not in planned['input'] and 'No final prose or notes' in planned['input']
    assert final['max_output_tokens'] == provider.request_body(CONFIG, draft(5), 'ai.pdf_topic')['max_output_tokens']


def test_prefix_is_stable_across_batches_and_scoped_by_account():
    data = draft(20, 'pptx')
    data['_cache_scope'] = 'private-account-one'
    first = provider.request_body(CONFIG, data, 'ai.pptx', (0, 8))
    later = provider.request_body(CONFIG, data, 'ai.pptx', (8, 16))
    assert first['instructions'] == later['instructions']
    assert first['prompt_cache_key'] == later['prompt_cache_key']
    assert 'private-account-one' not in json.dumps(first)
    data['_cache_scope'] = 'private-account-two'
    assert first['prompt_cache_key'] != provider.request_body(CONFIG, data, 'ai.pptx', (0, 8))['prompt_cache_key']


def test_whole_revision_preserves_questions_and_does_not_reassign_layouts():
    data = draft(5, 'pptx')
    data['content']['questions'] = [{'id':'q1', 'stem':'Keep me', 'options':[], 'answer':'Yes',
                                     'explanation':'', 'topic':'Tides', 'marks':1}]
    data['revision'] = {'request':'Fix spelling.', 'original_prompt':'A lesson with one question.'}
    body = provider.request_body(CONFIG, data, 'ai.pptx')
    sent = json.loads(body['input'])
    assert 'Existing questions remain' in body['instructions']
    assert sent['max_questions'] == 1
    assert 'questions' in body['text']['format']['schema']['properties']
    assert 'Section 1 is the title slide' not in sent['writing_guidance']
    assert 'notes: 2 to 4 sentences' not in sent['writing_guidance']
    assert 'Do not add unrequested content' in body['instructions']


def test_selected_middle_slides_keep_context_and_untouched_output_exact(monkeypatch):
    data = draft(5, 'pptx')
    for section in data['content']['sections']:
        section.update(layout='stats', items=[{'label':'Growth', 'text':'Yearly', 'value':'4%'}],
                       columns=[], image_query='', notes='Keep this presenter note.')
    data['revision'] = {'request': 'Fix one typo.', 'original_prompt': 'A five-slide briefing.',
                        'selected_section_ids': ['s3', 's5'], 'base_content': copy.deepcopy(data['content'])}
    data['prompt'] = data['revision']['request']
    original = copy.deepcopy(data)
    def answer(body, _):
        sent = json.loads(body['input'])
        assert [s['id'] for s in sent['outline']['sections']] == ['s3', 's5']
        assert sent['document_context'] == original['content']
        assert 'Section 1 is the title slide' not in sent['writing_guidance']
        assert 'Use 1 photo layout' not in sent['writing_guidance']
        assert 'title' not in body['text']['format']['schema']['properties']
        return {'answer_supported': True, 'sections': [
            {**s, 'body': 'Corrected content.'} for s in sent['outline']['sections']]}
    calls = transport(monkeypatch, answer)
    result, usage = provider.generate(CONFIG, data, 'ai.pptx', 'selected-offline', token_limit=100_000)
    assert len(calls) == 1 and usage == {'input_tokens':120, 'output_tokens':80}
    for index in (0, 1, 3): assert result['sections'][index] == original['content']['sections'][index]
    assert result['title'] == original['content']['title'] and result['questions'] == []
    assert result['sections'][2]['notes'] == 'Keep this presenter note.'
    assert data == original


def test_failed_multi_batch_job_retries_only_missing_calls_through_api(settings, monkeypatch):
    settings.DEBUG = True
    customer = paid(settings, account())
    save_config('ai', {'mode':'openai', 'model':CONFIG['model'], 'api_key':'offline-only'})
    authored = create_draft(customer, {'prompt':'A 12 page guide to tides.', 'options':{'length':12}})
    data = unpack(authored.encrypted_data)
    assert len(data['content']['sections']) == 12
    quote = generation_quote(customer, authored.id, authored.version)
    job, _ = submit_job(customer, quote.id, 'initial-offline-generation')
    def answer(body, number):
        if number == 2: raise TimeoutError('offline simulated timeout')
        return pdf_answer(body)
    calls = transport(monkeypatch, answer)
    with pytest.raises(DomainError, match='provider_failed'):
        provider.generate(CONFIG, data, job.feature_id, job.id, token_limit=100_000)
    assert ProviderCheckpoint.objects.filter(status='completed').count() == 1
    assert list(ProviderAttempt.objects.order_by('created_at').values_list('status', flat=True)) == ['succeeded','failed']
    Job.objects.filter(pk=job.id).update(status='failed')
    client = login_client(customer)
    url = f'/api/v1/generation/jobs/{job.id}/retry-quote'
    reply = client.post(url, {}, content_type='application/json')
    assert reply.status_code == 201, reply.content
    assert Job.objects.count() == 1, 'Reviewing cost cannot run the provider'
    retried, _ = submit_job(customer, reply.json()['id'], 'confirmed-offline-retry')
    result, usage = provider.generate(CONFIG, data, retried.feature_id, retried.id, token_limit=100_000)
    assert len(calls) == 3, 'Retry should only call the missing second batch'
    assert [s['id'] for s in result['sections']] == [s['id'] for s in data['content']['sections']]
    assert usage == {'input_tokens':120, 'output_tokens':80}
    assert ProviderAttempt.objects.count() == 3
    assert ProviderCheckpoint.objects.filter(status='completed').count() == 2
    other = login_client(account(43))
    assert other.post(url, {}, content_type='application/json').status_code == 404
