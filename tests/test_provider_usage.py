"""Provider accounting retains known usage through failure without retaining content."""
from datetime import datetime, timedelta, timezone as tz
from uuid import uuid4

import pytest
from django.test import Client, RequestFactory
from django.utils import timezone

from apps.core.models import Account, Job, Quote
from apps.studio.models import ProviderAttempt
from apps.studio.provider_usage import TOKEN_FIELDS, cleanup_attempts, finish, received, start_attempt
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
    row.refresh_from_db()
    assert row.response_id == row.resolved_model == row.provider_status == ''
    assert private not in str(row.__dict__)


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_admin_usage_page_localized_read_only_and_unknown_labeled(locale):
    row = attempt(stage='outline')
    finish(row, 'failed')
    client, _ = staff_client('Analyst')
    response = client.get('/ops/analytics/ai-usage', PERIOD | {'lang': locale})
    assert response.status_code == 200
    body = response.content.decode()
    assert LABELS[locale]['unknown'] in body and LABELS[locale]['retention'] in body
    assert LABELS[locale]['outline'] in body
    assert 'no-store' in response['Cache-Control']
    assert str(row.id) not in body and row.request_key not in body
    assert client.post('/ops/analytics/ai-usage').status_code == 405
    assert LABELS[locale].keys() == LABELS['en'].keys()


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
