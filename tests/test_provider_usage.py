"""Provider accounting retains known usage through failure without retaining content."""
import json
from datetime import datetime, timedelta, timezone as tz
from uuid import uuid4

import pytest
from django.test import Client, RequestFactory
from django.utils import timezone

from apps.core.models import Account, Job, Quote
from apps.studio.models import ProviderAttempt
from apps.studio.provider_usage import REJECTIONS, TOKEN_FIELDS, cleanup_attempts, finish, received, start_attempt
from operations.metrics import Filters
from operations.provider_usage import LABELS, usage_report
from tests.test_operations import staff_client

pytestmark = pytest.mark.django_db
PERIOD = {'date_from': '2026-09-01', 'date_to': '2026-10-01'}
CREATED = datetime(2026, 9, 10, tzinfo=tz.utc)


def attempt(*, environment='production', **kwargs):
    row = start_attempt(uuid4(), 'generate.presentation', 'gpt-test', **kwargs)
    ProviderAttempt.objects.filter(pk=row.pk).update(created_at=CREATED, environment=environment)
    return row


def report(**kwargs):
    filters = Filters.from_request(RequestFactory().get('/', PERIOD | kwargs))
    return usage_report(filters)


def response(identifier='resp_001', **usage):
    return {'id': identifier, 'model': 'gpt-test-resolved', 'status': 'completed',
            'usage': {'input_tokens': 100, 'output_tokens': 40,
                      'input_tokens_details': {'cached_tokens': 30, 'cache_write_tokens': 20},
                      'output_tokens_details': {'reasoning_tokens': 15}, **usage}}


def test_complete_usage_captures_subsets_requested_and_resolved_models():
    row = attempt(stage='outline', span=(5, 10))
    received(row, response(), 420)
    finish(row, 'succeeded')
    row.refresh_from_db()
    assert row.status == 'succeeded' and row.provider_status == 'completed'
    assert (row.input_tokens, row.output_tokens, row.total_tokens) == (100, 40, 140)
    assert (row.cached_input_tokens, row.cache_write_input_tokens, row.reasoning_output_tokens) == (30, 20, 15)
    assert (row.requested_model, row.resolved_model) == ('gpt-test', 'gpt-test-resolved')
    assert (row.stage, row.span_start, row.span_end, row.latency_ms) == ('outline', 5, 10, 420)
    assert row.received_at and row.finished_at and row.response_id == 'resp_001'
    assert row.response_key and not row.duplicate_response


@pytest.mark.parametrize('outcome', ['rejected', 'failed'])
def test_incomplete_or_rejected_response_still_records_reported_tokens(outcome):
    row = attempt()
    result = response()
    result.update(status='incomplete', output=[{'private': 'never persist this response'}])
    received(row, result, 50)
    finish(row, outcome)
    row.refresh_from_db()
    assert (row.input_tokens, row.output_tokens, row.provider_status) == (100, 40, 'incomplete')
    assert row.status == outcome
    assert report()['counts']['total_tokens'] == 140
    assert 'never persist' not in str(row.__dict__)


def test_transport_failure_is_unknown_not_zero_and_finish_is_idempotent():
    row = attempt()
    finish(row, 'failed', elapsed_ms=123)
    finish(row, 'succeeded')
    row.refresh_from_db()
    assert row.status == 'failed' and row.latency_ms == 123
    assert all(getattr(row, field) is None for field in TOKEN_FIELDS)
    assert report()['counts']['input_tokens'] is None
    assert report()['counts']['input_tokens_unknown'] == 1


@pytest.mark.parametrize('value', [-1, True, '100', 2**63, 1.5, None])
def test_invalid_counts_remain_unknown_while_other_counts_are_retained(value):
    row = attempt()
    received(row, response(input_tokens=value), 1)
    row.refresh_from_db()
    assert row.input_tokens is None and row.output_tokens == 40
    assert row.cached_input_tokens is None and row.cache_write_input_tokens is None
    assert row.total_tokens is None


def test_zero_usage_is_known_and_subsets_cannot_exceed_parent_counts():
    row = attempt()
    received(row, response(input_tokens=0, output_tokens=0), 0)
    row.refresh_from_db()
    assert (row.input_tokens, row.output_tokens, row.total_tokens) == (0, 0, 0)
    assert row.cached_input_tokens is None and row.reasoning_output_tokens is None
    second = attempt()
    received(second, response('resp_002', input_tokens_details={'cached_tokens': 90, 'cache_write_tokens': 20}), 1)
    second.refresh_from_db()
    assert second.input_tokens == 100
    assert second.cached_input_tokens is None and second.cache_write_input_tokens is None


def test_replayed_response_is_retained_but_tokens_are_counted_once():
    first, second = attempt(), attempt()
    received(first, response(), 400)
    finish(first, 'rejected')
    received(second, response(), 40)
    finish(second, 'succeeded')
    second.refresh_from_db()
    assert second.duplicate_response and second.duplicate_of_id == first.pk and second.response_key is None
    totals = report()
    assert totals['totals'] == {'attempts': 2, 'duplicates': 1, 'failed': 1, 'responses': 1}
    assert totals['counts']['input_tokens'] == 100 and totals['counts']['output_tokens'] == 40
    assert len(list(totals['model_rows'])) == 1


def test_replay_can_supply_previously_unknown_counts():
    first, second = attempt(), attempt()
    received(first, {'id': 'resp_001', 'status': 'completed'}, 1)
    finish(first, 'rejected')
    received(second, response(), 1)
    assert report()['counts']['total_tokens'] == 140
    assert report()['counts']['input_tokens_unknown'] == 0
    first.refresh_from_db()
    assert first.resolved_model == 'gpt-test-resolved'


def test_replay_partial_usage_merge_keeps_total_and_subset_invariants():
    first, second = attempt(), attempt()
    received(first, response(output_tokens=None, total_tokens=None,
                             input_tokens_details={'cached_tokens': 90}), 1)
    received(second, response(input_tokens_details={'cache_write_tokens': 20}), 1)
    first.refresh_from_db()
    assert (first.input_tokens, first.output_tokens, first.total_tokens) == (100, 40, 140)
    assert first.cached_input_tokens is None and first.cache_write_input_tokens is None
    assert report()['counts']['total_tokens'] == 140


def test_no_attempts_means_zero_known_usage_not_unknown():
    values = report()
    assert values['totals']['attempts'] == 0
    assert all(values['counts'][field] == 0 and values['counts'][field + '_unknown'] == 0 for field in TOKEN_FIELDS)


def test_missing_response_ids_are_not_falsely_deduplicated():
    for _ in range(2):
        row = attempt()
        received(row, response(identifier=None), 1)
    assert report()['counts']['input_tokens'] == 200
    assert report()['totals']['duplicates'] == 0


def test_unknown_environment_visible_without_guessing_production():
    row = attempt(environment='unknown')
    received(row, response(), 1)
    values = report()
    assert values['unknown_environment'] == 1
    assert values['totals']['attempts'] == 0


def test_job_lookup_snapshots_filters_and_usage_survives_job_deletion():
    account = Account.objects.create(locale='uz', is_test=True)
    quote = Quote.objects.create(account=account, feature_id='generate.presentation', expires_at=timezone.now() + timedelta(days=1))
    job = Job.objects.create(account=account, quote=quote, feature_id='generate.presentation', origin_channel='bot',
                             idempotency_key='usage-ledger-test', request_hash='0' * 64)
    row = start_attempt(f'{job.id}-2', job.feature_id, 'gpt-test', span=(10, 15))
    assert row.job_id == job.pk and row.environment == 'development'
    assert row.locale == 'uz' and row.origin_channel == 'bot'
    received(row, response(), 1)
    job.delete()
    row.refresh_from_db()
    assert row.job_id is None and row.input_tokens == 100
    assert row.environment == 'development' and row.origin_channel == 'bot'


def test_filters_apply_attempt_date_environment_locale_and_origin_channel():
    for env, locale, channel in [('production', 'uz', 'bot'), ('production', 'en', 'web'), ('development', 'uz', 'bot')]:
        row = attempt(environment=env, output_locale=locale, origin_channel=channel)
        received(row, response(str(uuid4())), 1)
    outside = attempt(output_locale='uz', origin_channel='bot')
    ProviderAttempt.objects.filter(pk=outside.pk).update(created_at=CREATED - timedelta(days=60))
    assert report()['totals']['attempts'] == 2
    assert report(locale='uz', channel='bot')['totals']['attempts'] == 1
    assert report(environment='development')['totals']['attempts'] == 1


def test_retention_is_bounded_and_does_not_make_replays_billable():
    first, replay = attempt(), attempt()
    received(first, response(), 1)
    received(replay, response(), 1)
    ProviderAttempt.objects.filter(pk=first.pk).update(created_at=timezone.now() - timedelta(days=91))
    ProviderAttempt.objects.filter(pk=replay.pk).update(created_at=timezone.now())
    old = attempt()
    ProviderAttempt.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=92))
    assert cleanup_attempts(batch_size=1) == 1
    assert cleanup_attempts(batch_size=1) == 1
    replay.refresh_from_db()
    assert replay.duplicate_response and replay.duplicate_of_id is None
    assert not ProviderAttempt.objects.filter(duplicate_response=False).exists()


def test_arbitrary_payloads_and_metadata_are_not_stored():
    private = 'PRIVATE CUSTOMER SOURCE has spaces and text'
    row = attempt()
    received(row, {'id': private, 'model': private, 'status': private, 'output': private, 'usage': None}, 10)
    finish(row, 'rejected', reason=private)
    row.refresh_from_db()
    assert row.response_id == row.resolved_model == row.provider_status == row.rejection == ''
    assert private not in str(row.__dict__)


@pytest.mark.parametrize('status,reason,kept', [
    ('rejected', 'section_count', 'section_count'),
    ('rejected', 'schema', 'schema'),
    ('rejected', 'section_count; DROP TABLE', ''),
    ('rejected', ['schema'], ''),
    ('failed', 'schema', ''),
    ('succeeded', 'schema', ''),
])
def test_only_a_known_rejection_code_is_kept_and_only_on_a_rejected_reply(status, reason, kept):
    row = attempt()
    finish(row, status, reason=reason)
    row.refresh_from_db()
    assert row.status == status and row.rejection == kept


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_admin_usage_page_localized_read_only_and_unknown_labeled(locale):
    row = attempt(stage='outline')
    finish(row, 'failed')
    rejected = attempt()
    received(rejected, response(), 1)
    finish(rejected, 'rejected', reason='section_count')
    client, _ = staff_client('Analyst')
    page = client.get('/ops/analytics/ai-usage', PERIOD | {'lang': locale})
    assert page.status_code == 200
    body = page.content.decode()
    assert LABELS[locale]['unknown'] in body and LABELS[locale]['retention'] in body
    assert LABELS[locale]['outline'] in body
    # Why the reply was refused, beside "Response rejected" and counted by reason.
    assert f"{LABELS[locale]['rejected']}<small>{LABELS[locale]['rejection_section_count']}</small>" in body
    assert LABELS[locale]['reasons'] in body
    assert 'no-store' in page['Cache-Control']
    assert str(row.id) not in body and row.request_key not in body
    assert client.post('/ops/analytics/ai-usage').status_code == 405
    assert LABELS[locale].keys() == LABELS['en'].keys()


def test_every_code_a_reply_is_refused_with_is_one_that_is_kept():
    import re
    from pathlib import Path
    from apps.studio import provider
    raised = {'cut_off', 'unreadable'}
    for name in ('provider.py', 'photo_choice.py', 'filling.py'):
        source = (Path(provider.__file__).parent / name).read_text()
        raised |= set(re.findall(r"_Rejected\('(\w+)'", source))
    assert raised == REJECTIONS, 'a code not in REJECTIONS is saved as no reason at all'


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_every_rejection_code_has_a_label(locale):
    assert {'rejection_' + code for code in REJECTIONS} <= set(LABELS[locale])
    assert all(LABELS[locale]['rejection_' + code] != LABELS['en']['rejection_' + code] for code in REJECTIONS
               if locale != 'en'), 'translated, not copied'


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_a_failed_document_says_why_its_reply_was_rejected(settings, locale):
    from apps.core.services import execute_job, submit_job
    from apps.studio.domain import create_draft, generation_quote
    from apps.studio.models import GenerationRecord
    from tests.test_platform import account as customer_account
    from tests.test_studio import paid
    settings.DEBUG = True
    customer = paid(settings, customer_account())
    draft = create_draft(customer, {'prompt': 'A 2 page guide to tides for sailors.'})
    job, _ = submit_job(customer, generation_quote(customer, draft.id, draft.version).id, 'rejected-reason')
    job = execute_job(job.id)
    Job.objects.filter(pk=job.pk).update(status='failed', error_code='provider_failed')
    GenerationRecord.objects.filter(job=job).update(output_key='')
    for reason in ('schema', 'section_count'):
        row = start_attempt(job.id, job.feature_id, 'gpt-test', job=job)
        received(row, response(str(uuid4())), 1)
        finish(row, 'rejected', reason=reason)
    client, _ = staff_client('Operations')
    page = client.get(f'/ops/jobs/{job.id}', {'lang': locale}).content.decode()
    # The reply that ended the job, in the page's language rather than as its code.
    assert f'provider_failed · {LABELS[locale]["rejection_section_count"]}</dd>' in page
    assert 'provider_failed · <span' not in page and (locale == 'en' or 'Wrong number of sections' not in page)
    record = GenerationRecord.objects.get(job=job)
    detail = client.get(f'/ops/generations/{record.id}', {'lang': locale}).content.decode()
    assert f'provider_failed · {LABELS[locale]["rejection_section_count"]}' in detail


def _failed_job(error_code):
    account = Account.objects.create(locale='en')
    quote = Quote.objects.create(account=account, feature_id='ai.document', expires_at=timezone.now() + timedelta(days=1))
    return Job.objects.create(account=account, quote=quote, feature_id='ai.document', status='failed',
                              error_code=error_code, idempotency_key=str(uuid4()), request_hash='0' * 64)


def _job_attempts(job, rows):
    """Attempts for `job`, one second apart in the order given: (stage, status, reason)."""
    for number, (stage, status, reason) in enumerate(rows):
        row = start_attempt(f'{job.id}-{number}', job.feature_id, 'gpt-test', stage=stage, job=job)
        if status != 'failed':
            received(row, response(str(uuid4())), 1)
        finish(row, status, reason=reason)
        ProviderAttempt.objects.filter(pk=row.pk).update(created_at=CREATED + timedelta(seconds=number))


@pytest.mark.parametrize('rows,shown', [
    # Part 1 of a long document was put right; part 2 then timed out twice.
    ([('generate', 'rejected', 'section_count'), ('generate', 'succeeded', ''),
      ('generate', 'failed', ''), ('generate', 'failed', '')], ''),
    # The corrected try itself timed out: the job ended on the timeout.
    ([('generate', 'rejected', 'section_count'), ('generate', 'failed', '')], ''),
    # The last part was refused twice: that is what ended it.
    ([('generate', 'succeeded', ''), ('generate', 'rejected', 'schema'), ('generate', 'rejected', 'section_count')],
     'section_count'),
    # A photo choice never ends a job, so its refusal is never the reason.
    ([('generate', 'rejected', 'section_count'), ('photo_pick', 'rejected', 'not_json')], 'section_count'),
    ([('generate', 'succeeded', ''), ('expand', 'rejected', 'not_json'), ('repair', 'rejected', 'schema')], ''),
    ([('outline', 'rejected', 'cut_off'), ('outline', 'rejected', 'cut_off')], 'cut_off'),
    ([], ''),
])
def test_ops_names_a_rejection_only_when_it_ended_the_job(rows, shown):
    job = _failed_job('provider_failed')
    _job_attempts(job, rows)
    assert job.provider_attempts.final_rejection() == shown
    client, _ = staff_client('Operations')
    page = client.get(f'/ops/jobs/{job.id}', {'lang': 'en'}).content.decode()
    assert (f'provider_failed · {LABELS["en"]["rejection_" + shown]}</dd>' if shown else 'provider_failed</dd>') in page


def test_a_reason_is_shown_only_beside_a_provider_failure():
    job = _failed_job('render_failed')
    _job_attempts(job, [('generate', 'rejected', 'section_count')])
    client, _ = staff_client('Operations')
    page = client.get(f'/ops/jobs/{job.id}', {'lang': 'en'}).content.decode()
    assert 'render_failed</dd>' in page and LABELS['en']['rejection_section_count'] not in page


# Outside a transaction: SQLite cannot collect a table rebuild's SQL inside one.
@pytest.mark.django_db(transaction=True)
def test_the_rejection_column_keeps_its_database_default():
    """Code from before the column (a deploy mid-migration, or a rollback) can still record attempts."""
    import io
    from django.core.management import call_command
    from django.db import connection
    sql = io.StringIO()
    call_command('sqlmigrate', 'studio', '0008_providerattempt_rejection', stdout=sql)
    added = sql.getvalue()
    assert '"rejection" varchar(24) DEFAULT \'\' NOT NULL' in added and 'DROP DEFAULT' not in added
    # An insert that names every column but this one, as the model before it does.
    row = ProviderAttempt(request_key='0' * 64, feature_id='ai.document', requested_model='gpt-test')
    fields = [field for field in ProviderAttempt._meta.concrete_fields if field.name != 'rejection']
    values = [field.get_db_prep_save(field.pre_save(row, True), connection) for field in fields]
    with connection.cursor() as cursor:
        cursor.execute(f'INSERT INTO {connection.ops.quote_name(ProviderAttempt._meta.db_table)} '
                       f'({", ".join(connection.ops.quote_name(field.column) for field in fields)}) '
                       f'VALUES ({", ".join(["%s"] * len(fields))})', values)
    assert ProviderAttempt.objects.get(pk=row.pk).rejection == ''


@pytest.mark.parametrize('role', ['Analyst', 'Operations', 'Finance'])
def test_usage_report_allowed_roles(role):
    client, _ = staff_client(role)
    assert client.get('/ops/analytics/ai-usage').status_code == 200


def test_usage_report_rejects_customer_support_and_invalid_filters():
    assert Client().get('/ops/analytics/ai-usage').status_code == 302
    client, _ = staff_client('Support')
    assert client.get('/ops/analytics/ai-usage').status_code == 403
    admin, _ = staff_client('Administrator')
    assert admin.get('/ops/analytics/ai-usage?date_from=bad').status_code == 400


def _reply(**fields):
    reply = {'id': f'resp_{uuid4().hex}', 'model': 'gpt-test', 'status': 'completed',
             'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{}'}]}],
             'usage': {'input_tokens': 10, 'output_tokens': 5}}
    return {**reply, **fields}


def _text(text):
    return [{'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}]


# Every way a best-effort call's reply can be refused, and the reason its row keeps.
BEST_EFFORT_REPLIES = [
    (_reply(output=_text('not json')), ('rejected', 'not_json')),
    (_reply(output=_text('{"unexpected": []}')), ('rejected', 'schema')),
    (_reply(status='failed'), ('rejected', 'not_completed')),
    (_reply(status='incomplete'), ('rejected', 'cut_off')),
    (_reply(output=[{'type': 'message', 'content': [{'type': 'refusal', 'refusal': 'No.'}]}]), ('rejected', 'refusal')),
    (_reply(output=[]), ('rejected', 'no_output')),
    (b' ' * 2_000_001, ('rejected', 'oversized')),
    (TimeoutError('offline'), ('failed', '')),
]
BEST_EFFORT_IDS = [reason or status for _, (status, reason) in BEST_EFFORT_REPLIES]


class _Reply:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, limit):
        return (self.payload if isinstance(self.payload, bytes) else json.dumps(self.payload).encode())[:limit]


def _answer(payload):
    if isinstance(payload, Exception):
        raise payload
    return _Reply(payload)


@pytest.mark.parametrize('payload,kept', BEST_EFFORT_REPLIES, ids=BEST_EFFORT_IDS)
def test_a_photo_choice_that_is_refused_keeps_its_reason(monkeypatch, payload, kept):
    from apps.studio import photo_choice
    job = _failed_job('')
    monkeypatch.setattr(photo_choice, '_post', lambda request, timeout: _answer(payload))
    with pytest.raises(Exception):
        photo_choice.choose({'model': 'gpt-test', 'api_key': 'offline-only'}, 'Tides',
                            [{'id': 's1', 'text': 'Tides', 'photos': [b'\xff\xd8\xff']}], timeout=10, job=job)
    row = ProviderAttempt.objects.get(stage='photo_pick')
    assert (row.status, row.rejection) == kept


@pytest.mark.parametrize('payload,kept', BEST_EFFORT_REPLIES, ids=BEST_EFFORT_IDS)
def test_an_expand_call_that_is_refused_keeps_its_reason(monkeypatch, payload, kept):
    import urllib.request
    from apps.studio import filling
    job = _failed_job('')
    content = {'title': 'Tides', 'sections': [{'id': 's1', 'heading': 'Tides', 'body': 'Tides rise.'},
                                               {'id': 's2', 'heading': 'Currents', 'body': 'Currents flow.'}]}
    data = {'output_locale': 'en', 'prompt': 'A 5 page guide to tides for sailors.', 'options': {'requested_pages': 5}}

    class Opener:
        def open(self, request, timeout): return _answer(payload)
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *handlers: Opener())
    assert filling.top_up({'model': 'gpt-test', 'api_key': 'offline-only'}, data, content, 5, 1, job=job) is content
    row = ProviderAttempt.objects.get(stage='expand')
    assert (row.status, row.rejection) == kept


def test_a_refused_photo_choice_is_counted_under_its_reason_not_as_unrecorded(monkeypatch):
    from apps.studio import photo_choice
    job = _failed_job('')
    monkeypatch.setattr(photo_choice, '_post', lambda request, timeout: _answer(_reply(output=_text('nope'))))
    with pytest.raises(Exception):
        photo_choice.choose({'model': 'gpt-test', 'api_key': 'offline-only'}, 'Tides',
                            [{'id': 's1', 'text': 'Tides', 'photos': [b'\xff\xd8\xff']}], timeout=10, job=job)
    ProviderAttempt.objects.update(created_at=CREATED, environment='production')
    assert [(row['rejection'], row['responses']) for row in report()['reason_rows']] == [('not_json', 1)]
    client, _ = staff_client('Analyst')
    body = client.get('/ops/analytics/ai-usage', PERIOD | {'lang': 'en'}).content.decode()
    assert LABELS['en']['rejection_not_json'] in body and LABELS['en']['rejection_'] not in body
