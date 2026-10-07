"""A short last batch has room to think, and a reply cut off is asked for once more.

A ten-slide deck failed in production because its last call (slides 9-10) was
given 3000 output tokens: a reasoning model spent them thinking, the answer was
cut off mid-JSON, and the whole paid deck was thrown away for want of two slides.
"""
import json

import pytest

from apps.core.errors import DomainError
from apps.core.services import submit_job
from apps.studio import pages, provider
from apps.studio.domain import create_draft, generation_quote, unpack
from apps.studio.models import ProviderAttempt
from operations.integrations import save_config
from tests.test_platform import account
from tests.test_provider_contract import CONFIG, draft
from tests.test_provider_optimization import pdf_answer
from tests.test_studio import paid

pytestmark = pytest.mark.django_db


def test_a_small_last_batch_still_has_room_to_think():
    data = draft(10, 'pptx')
    last = provider.request_body(CONFIG, data, 'ai.pptx', (8, 10))
    assert last['max_output_tokens'] >= pages.MIN_CALL_TOKENS
    # The questions are written in the last call, and its budget grows with them.
    data['options']['question_count'] = 10
    asking = provider.request_body(CONFIG, data, 'ai.pptx', (8, 10))
    assert asking['max_output_tokens'] > last['max_output_tokens']
    assert asking['max_output_tokens'] <= pages.RESPONSE_CEILING


def opener(monkeypatch, replies):
    """Hand back the given provider replies in order; record what was asked."""
    sent = []

    class Response:
        def __init__(self, payload): self.payload = payload
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return json.dumps(self.payload).encode()

    class Opener:
        def open(self, request, timeout):
            body = json.loads(request.data)
            sent.append(body)
            reply = replies[len(sent) - 1](body)
            if isinstance(reply, Exception):
                raise reply
            return Response(reply)

    monkeypatch.setattr(provider.urllib.request, 'build_opener', lambda _: Opener())
    return sent


def completed(body):
    return {'id': 'resp_ok', 'model': CONFIG['model'], 'status': 'completed',
            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(pdf_answer(body))}]}],
            'usage': {'input_tokens': 100, 'output_tokens': 80}}


def cut_off(body):
    text = json.dumps(pdf_answer(body))
    return {'id': 'resp_cut', 'model': CONFIG['model'], 'status': 'incomplete',
            'incomplete_details': {'reason': 'max_output_tokens'},
            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': text[:len(text) // 2]}]}],
            'usage': {'input_tokens': 100, 'output_tokens': body['max_output_tokens']}}


@pytest.fixture
def twelve_pages(settings):
    settings.DEBUG = True
    customer = paid(settings, account())
    save_config('ai', {'mode': 'openai', 'model': CONFIG['model'], 'api_key': 'offline-only'})
    authored = create_draft(customer, {'prompt': 'A 12 page guide to tides.'})
    quote = generation_quote(customer, authored.id, authored.version)
    job, _ = submit_job(customer, quote.id, 'retry-offline')
    return unpack(authored.encrypted_data), job


def test_a_reply_cut_off_at_its_limit_is_asked_again_with_more_room(monkeypatch, twelve_pages):
    data, job = twelve_pages
    sent = opener(monkeypatch, [completed, cut_off, completed])
    result, _ = provider.generate(CONFIG, data, job.feature_id, job.id, token_limit=100_000)
    assert len(result['sections']) == 12
    assert len(sent) == 3
    assert sent[2]['max_output_tokens'] == min(pages.RESPONSE_CEILING, 2 * sent[1]['max_output_tokens'])
    assert list(ProviderAttempt.objects.order_by('created_at').values_list('status', flat=True)) == [
        'succeeded', 'rejected', 'succeeded']


def test_a_dropped_connection_is_tried_once_more(monkeypatch, twelve_pages):
    data, job = twelve_pages
    sent = opener(monkeypatch, [completed, lambda body: TimeoutError('offline'), completed])
    result, _ = provider.generate(CONFIG, data, job.feature_id, job.id, token_limit=100_000)
    assert len(result['sections']) == 12 and len(sent) == 3
    assert sent[2]['max_output_tokens'] == sent[1]['max_output_tokens'], 'the same request, not a bigger one'


def test_a_whole_but_wrong_answer_is_not_asked_again(monkeypatch, twelve_pages):
    """A reply that arrived complete and invalid would only arrive invalid again."""
    data, job = twelve_pages

    def wrong(body):
        reply = completed(body)
        reply['usage']['output_tokens'] = pages.RESPONSE_CEILING + 1
        return reply

    sent = opener(monkeypatch, [completed, wrong, completed])
    with pytest.raises(DomainError, match='provider_failed'):
        provider.generate(CONFIG, data, job.feature_id, job.id, token_limit=100_000)
    assert len(sent) == 2


def test_no_second_try_when_the_lease_is_nearly_up(monkeypatch, twelve_pages):
    import time
    data, job = twelve_pages
    sent = opener(monkeypatch, [cut_off, completed])
    with pytest.raises(DomainError, match='provider_failed'):
        provider.generate(CONFIG, data, job.feature_id, job.id, token_limit=100_000,
                          deadline=time.monotonic() + 10)
    assert len(sent) == 1
