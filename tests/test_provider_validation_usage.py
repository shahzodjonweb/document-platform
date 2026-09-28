"""Provider recovery only persists usable results; absent billing is not failure."""
import copy
import json

import pytest

from apps.core.errors import DomainError
from apps.core.models import Job
from apps.core.services import submit_job
from apps.studio import checkpoints, provider
from apps.studio.domain import create_draft, generation_quote, unpack
from apps.studio.models import ProviderAttempt, ProviderCheckpoint
from tests.test_platform import account

pytestmark = pytest.mark.django_db
CONFIG = {'model':'test-model', 'api_key':'test-only-never-a-live-key'}


def question(identifier='q1'):
    return {'id':identifier, 'stem':'A useful question?', 'options':['Yes', 'No'],
            'answer':'Yes', 'explanation':'A clear explanation.', 'topic':'Example', 'marks':1}


@pytest.fixture
def request_case(settings, monkeypatch):
    settings.DEBUG = True
    customer = account()
    draft = create_draft(customer, {'feature_id':'ai.pdf_topic',
                                    'prompt':'Write one page and two questions.',
                                    'source_text':'A supplied fact.'})
    quote = generation_quote(customer, draft.id, draft.version)
    job, _ = submit_job(customer, quote.id, 'validation-first-job')
    data = unpack(draft.encrypted_data)
    # The compact wire schema omits unused PDF notes and source citations.
    wire = {'title':'Example', 'answer_supported':True,
            'sections':[{'id':'s1', 'heading':'A fact', 'body':'A supplied fact, explained.'}],
            'questions':[question()]}
    state = {'wire':wire, 'usage':{'input_tokens':100, 'output_tokens':50}, 'calls':[]}

    class Response:
        def __init__(self, payload):self.payload=payload
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self, limit):return json.dumps(self.payload).encode()

    class Opener:
        def open(self, request, timeout):
            state['calls'].append(json.loads(request.data))
            payload = {'id':f'resp_validation_{len(state["calls"])}', 'status':'completed',
                       'model':CONFIG['model'],
                       'output':[{'type':'message', 'content':[{'type':'output_text',
                                                              'text':json.dumps(state['wire'])}]}]}
            if state['usage'] != 'missing':payload['usage']=state['usage']
            return Response(payload)

    monkeypatch.setattr(provider.urllib.request, 'build_opener', lambda handler:Opener())
    return customer, draft, job, data, state


def generate(case, job=None):
    return provider.generate(CONFIG, case[3], 'ai.pdf_topic', (job or case[2]).id, token_limit=20000)


@pytest.mark.parametrize('invalid', ['marks', 'options', 'duplicate_ids', 'truncated_duplicate_ids'])
def test_domain_invalid_response_is_not_checkpointed_and_retry_can_regenerate(request_case, invalid):
    customer, _, job, _, state = request_case
    valid = copy.deepcopy(state['wire'])
    if invalid == 'marks':state['wire']['questions'][0]['marks']=0
    elif invalid == 'options':state['wire']['questions'][0]['options']=[str(i) for i in range(9)]
    elif invalid == 'duplicate_ids':state['wire']['questions'].append(question())
    else:state['wire']['questions']=[question('q'*40+'a'), question('q'*40+'b')]
    with pytest.raises(DomainError, match='provider_failed'):
        generate(request_case)
    checkpoint = ProviderCheckpoint.objects.get()
    assert checkpoint.status == 'pending' and not bytes(checkpoint.encrypted_result)
    assert checkpoint.lease_token is None
    rejected = ProviderAttempt.objects.get()
    assert rejected.status == 'rejected' and rejected.input_tokens == 100 and rejected.output_tokens == 50
    Job.objects.filter(pk=job.pk).update(status='failed')
    retry_quote = checkpoints.retry_quote(customer, job.id)
    retried, _ = submit_job(customer, retry_quote.id, 'validation-retry-job')
    state['wire'] = valid
    result, usage = generate(request_case, job=retried)
    assert result['questions'] == valid['questions'] and usage['output_tokens'] == 50
    assert len(state['calls']) == 2
    assert ProviderCheckpoint.objects.get().status == 'completed'
    assert list(ProviderAttempt.objects.order_by('created_at').values_list('status', flat=True)) == ['rejected', 'succeeded']


@pytest.mark.parametrize('usage,expected,recorded', [
    ('missing', {'input_tokens':0, 'output_tokens':0}, (None, None)),
    (None, {'input_tokens':0, 'output_tokens':0}, (None, None)),
    ({}, {'input_tokens':0, 'output_tokens':0}, (None, None)),
    ({'input_tokens':None, 'output_tokens':25}, {'input_tokens':0, 'output_tokens':25}, (None, 25)),
    ({'input_tokens':100, 'output_tokens':None}, {'input_tokens':100, 'output_tokens':0}, (100, None)),
])
def test_null_or_missing_usage_keeps_valid_output_and_unknown_ledger(request_case, usage, expected, recorded):
    state = request_case[4]
    state['usage'] = usage
    result, compatibility_usage = generate(request_case)
    assert result['sections'][0]['body'] == state['wire']['sections'][0]['body']
    assert compatibility_usage == expected
    attempt = ProviderAttempt.objects.get()
    assert attempt.status == 'succeeded'
    assert (attempt.input_tokens, attempt.output_tokens) == recorded
    assert attempt.total_tokens is None
    # Recovery requires no further provider attempt; zero here is actual reuse.
    assert generate(request_case)[1] == {'input_tokens':0, 'output_tokens':0}
    assert ProviderAttempt.objects.count() == 1 and len(state['calls']) == 1


@pytest.mark.parametrize('usage', [
    {'input_tokens':20001, 'output_tokens':50},
    {'input_tokens':100, 'output_tokens':2000},
    {'input_tokens':20001, 'output_tokens':None},
    {'input_tokens':None, 'output_tokens':2000},
])
def test_known_reported_counts_still_enforce_request_budgets(request_case, usage):
    request_case[4]['usage'] = usage
    with pytest.raises(DomainError, match='provider_failed'):
        generate(request_case)
    attempt = ProviderAttempt.objects.get()
    assert attempt.status == 'rejected'
    assert (attempt.input_tokens, attempt.output_tokens) == (usage['input_tokens'], usage['output_tokens'])
    assert ProviderCheckpoint.objects.get().status == 'pending'


@pytest.mark.parametrize('invalid', [True, -1, '100', 1.5])
def test_malformed_nonnull_usage_still_rejected_and_recorded_unknown(request_case, invalid):
    request_case[4]['usage'] = {'input_tokens':invalid, 'output_tokens':50}
    with pytest.raises(DomainError, match='provider_failed'):
        generate(request_case)
    attempt = ProviderAttempt.objects.get()
    assert attempt.input_tokens is None and attempt.output_tokens == 50 and attempt.status == 'rejected'
    assert ProviderCheckpoint.objects.get().status == 'pending'
