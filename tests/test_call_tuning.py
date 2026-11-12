"""Reasoning effort and processing tier, set in the admin, reach every provider call (apps/studio/tuning.py).

Nothing is sent that is not set, except the photo choice's low effort. A model
that refuses a setting answers 400; the call is sent once more without it and
the setting is dropped for the process, so a wrong choice never fails a job.
"""
import io
import json
import urllib.error

import pytest

from apps.core.services import execute_job, submit_job
from apps.studio import photo_choice, provider, tuning
from apps.studio.domain import create_draft, generation_quote
from apps.studio.models import ProviderAttempt
from operations.integrations import ai_config, read_config, save_config
from tests.test_generation_quality import model, reply
from tests.test_platform import account
from tests.test_provider_contract import CONFIG
from tests.test_studio import paid

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fresh():
    tuning.forget()
    yield
    tuning.forget()


def refusal(param, message=None):
    body = json.dumps({'error': {'message': message or f"Unsupported parameter: '{param}'.", 'type': 'invalid_request_error',
                                 'param': param, 'code': 'unsupported_parameter'}}).encode()
    return urllib.error.HTTPError('https://api.openai.com/v1/responses', 400, 'Bad Request', {}, io.BytesIO(body))


def test_nothing_is_added_to_a_writing_call_unless_the_admin_chose_it():
    assert tuning.settings(CONFIG, 'writing') == {}
    chosen = {**CONFIG, 'writing_effort': 'low', 'service_tier': 'priority'}
    assert tuning.settings(chosen, 'writing') == {'reasoning': {'effort': 'low'}, 'service_tier': 'priority'}
    # Anything not on the lists is never sent.
    assert tuning.settings({**CONFIG, 'writing_effort': 'turbo', 'service_tier': 'flex'}, 'writing') == {}


def test_the_photo_choice_thinks_little_unless_told_otherwise():
    slides = [{'id': 's2', 'text': 'Harbour cranes', 'photos': [b'\xff\xd8jpeg']}]
    assert photo_choice.request_body(CONFIG, 'Ports', slides)['reasoning'] == {'effort': 'low'}
    assert 'reasoning' not in photo_choice.request_body({**CONFIG, 'photo_effort': ''}, 'Ports', slides)
    assert photo_choice.request_body({**CONFIG, 'photo_effort': 'minimal'}, 'Ports', slides)['reasoning'] == {'effort': 'minimal'}


def test_a_refused_setting_is_dropped_and_the_call_sent_again():
    sent = []

    def post(body):
        sent.append(body)
        if 'reasoning' in body:
            raise refusal('reasoning.effort')
        return b'ok'

    body = {'model': 'm', 'max_output_tokens': 10, 'reasoning': {'effort': 'minimal'}, 'service_tier': 'priority'}
    assert tuning.send(post, body) == b'ok'
    assert [('reasoning' in b, 'service_tier' in b) for b in sent] == [(True, True), (False, True)]
    # Left out of later calls in this process; the tier still goes.
    assert tuning.settings({'writing_effort': 'low', 'service_tier': 'priority'}, 'writing') == {'service_tier': 'priority'}


def test_any_other_refusal_is_the_callers_as_before():
    def post(body):
        raise refusal('input', 'Invalid input.')
    with pytest.raises(urllib.error.HTTPError):
        tuning.send(post, {'model': 'm', 'reasoning': {'effort': 'low'}})
    # A body without tuning is never retried, whatever the 400 says.
    calls = []

    def bare(body):
        calls.append(body)
        raise refusal('reasoning.effort')
    with pytest.raises(urllib.error.HTTPError):
        tuning.send(bare, {'model': 'm'})
    assert len(calls) == 1 and tuning.settings({'writing_effort': 'low'}, 'writing') == {'reasoning': {'effort': 'low'}}


def test_the_settings_are_saved_checked_and_kept_when_the_form_leaves_them_out(settings):
    settings.DEBUG = True
    save_config('ai', {'mode': 'local_fixture', 'model': 'm'})
    assert (ai_config()['writing_effort'], ai_config()['photo_effort'], ai_config()['service_tier']) == ('', 'low', '')
    save_config('ai', {'mode': 'local_fixture', 'model': 'm', 'writing_effort': 'low', 'photo_effort': 'none', 'service_tier': 'priority'})
    save_config('ai', {'mode': 'local_fixture', 'model': 'm'})
    assert read_config('ai')[0]['writing_effort'] == 'low' and ai_config()['photo_effort'] == 'none'
    assert ai_config()['service_tier'] == 'priority'
    from apps.core.errors import DomainError
    with pytest.raises(DomainError):
        save_config('ai', {'mode': 'local_fixture', 'model': 'm', 'writing_effort': 'extreme'})
    with pytest.raises(DomainError):
        save_config('ai', {'mode': 'local_fixture', 'model': 'm', 'service_tier': 'flex'})


def test_a_job_whose_model_refuses_the_effort_is_written_all_the_same(settings, monkeypatch):
    settings.DEBUG = True
    customer = paid(settings, account())
    save_config('ai', {'mode': 'openai', 'model': CONFIG['model'], 'api_key': 'sk-offline-test-only', 'writing_effort': 'minimal'})
    seen = []

    def answer(body, number):
        seen.append(('reasoning' in body, body.get('reasoning')))
        written = {s['id']: {'heading': f'Heading {s["id"]}', 'body': f'Tides move twice a day near harbour {s["id"]}.'}
                   for s in json.loads(body['input'])['outline']['sections']}
        return reply(body, written)

    requests = model(monkeypatch, answer)

    class Refusing:
        def __init__(self, inner): self.inner = inner
        def open(self, request, timeout):
            if 'reasoning' in json.loads(request.data):
                assert request.get_header('Idempotency-key')
                raise refusal('reasoning.effort')
            assert request.get_header('Idempotency-key').endswith('-plain')
            return self.inner.open(request, timeout)
    inner = provider.urllib.request.build_opener(None)
    monkeypatch.setattr(provider.urllib.request, 'build_opener', lambda _: Refusing(inner))
    draft = create_draft(customer, {'feature_id': 'ai.pdf_topic', 'prompt': 'Ocean tides near harbours', 'output_locale': 'en',
                                    'options': {'pages': 2}})
    quote = generation_quote(customer, draft.id, draft.version)
    job, _ = submit_job(customer, quote.id, 'tuning-refused')
    job = execute_job(job.id)
    assert job.status == 'succeeded', job.error_code
    assert seen and all(not carried for carried, _ in seen)
    assert ProviderAttempt.objects.filter(job=job, status='succeeded').exists()
