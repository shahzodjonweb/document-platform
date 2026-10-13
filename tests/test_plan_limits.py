"""What each plan gives and costs, and how the deploy that replaced credits left the panel's changes.

Free: 5 AI documents and 15 file tasks a week, 3 edits per file. Plus, 20 000
so'm a month: 20 documents a week, 10 edits per file, file tools unlimited.
Premium, 60 000 so'm a month: everything unlimited. Blank (None) is unlimited.
"""
import importlib

import pytest
from django.apps import apps as django_apps
from django.test import Client

from apps.core.policy import POLICY_VERSION, SEED, limits_for_plan
from operations import plans as plan_settings
from operations.models import AuditLog, IntegrationConfig

pytestmark = pytest.mark.django_db
WEEKLY = ('weekly_ai_documents', 'weekly_file_jobs', 'edits_per_file')
RETIRED = ('file_tasks', 'file_page_units', 'ai_credits', 'daily_file_tasks', 'daily_ai_documents')
UNLIMITED = float('inf')


def test_the_seed_carries_the_owners_prices_and_weekly_limits():
    plans = SEED['plans']
    assert {plan: [plans[plan][key] for key in WEEKLY] for plan in plans} == {
        'free': [5, 15, 3], 'plus': [20, None, 10], 'premium': [None, None, None]}
    assert (plans['free']['price_uzs'], plans['plus']['price_uzs'], plans['premium']['price_uzs']) == (None, 20_000, 60_000)
    assert not any(key in plan for plan in plans.values() for key in RETIRED), 'no credits, tasks or daily caps'
    assert not {'tariff_v0_staging', 'purchased_pack_policy'} & set(SEED), 'nothing is sold in packs any more'
    assert POLICY_VERSION == 'weekly-v1', 'quotes priced under credits are refused, not submitted'


def test_free_never_gives_more_than_a_paid_plan():
    plans = SEED['plans']
    value = lambda plan, key: UNLIMITED if plans[plan][key] is None else plans[plan][key]
    for key, free in plans['free'].items():
        if key.startswith('price_') or not isinstance(free, (int, type(None))):
            continue
        for lower, higher in (('free', 'plus'), ('plus', 'premium')):
            assert value(higher, key) >= value(lower, key), (key, lower, higher)


def test_the_panel_edits_the_weekly_limits_and_nothing_retired():
    assert set(WEEKLY) <= set(plan_settings.FIELDS) and set(WEEKLY) <= plan_settings.NULLABLE
    assert not set(RETIRED) & set(plan_settings.FIELDS)
    assert set(plan_settings.FIELDS) <= set(SEED['plans']['free']), 'every editable field is a real plan field'
    with pytest.raises(plan_settings.PlanError, match='Nothing to change'):
        plan_settings.save('free', {'ai_credits': 3000})


def test_free_keeps_both_weekly_limits_and_paid_plans_may_lift_theirs():
    plans = SEED['plans']
    for field in ('weekly_ai_documents', 'weekly_file_jobs'):
        with pytest.raises(plan_settings.PlanError, match='weekly limits'):
            plan_settings.validate('free', {field: ''}, plans)
    assert plan_settings.validate('plus', {'weekly_ai_documents': ''}, plans) == {'weekly_ai_documents': None}
    assert plan_settings.validate('free', {'edits_per_file': '0'}, plans) == {'edits_per_file': 0}, 'zero edits is a real limit'
    with pytest.raises(plan_settings.PlanError, match='between'):
        plan_settings.validate('free', {'weekly_ai_documents': '0'}, plans)


def test_the_floor_rule_lets_free_rise_under_an_unlimited_paid_plan():
    """An unlimited paid value is above any free one; reading it as zero refused every free raise."""
    plans = SEED['plans']
    assert plan_settings.validate('free', {'weekly_file_jobs': '50'}, plans) == {'weekly_file_jobs': 50}
    with pytest.raises(plan_settings.PlanError, match='cannot exceed'):
        plan_settings.validate('free', {'weekly_ai_documents': '25'}, plans)
    with pytest.raises(plan_settings.PlanError, match='cannot exceed'):
        plan_settings.validate('free', {'edits_per_file': '11'}, plans)
    assert plan_settings.validate('free', {'weekly_ai_documents': '20', 'edits_per_file': '10'}, plans)


def test_free_keeps_a_limit_on_ai_edits_per_file():
    """Blank is unlimited: on Free that would be unlimited AI edits for anyone who signs up."""
    with pytest.raises(plan_settings.PlanError, match='edits per file'):
        plan_settings.validate('free', {'edits_per_file': ''}, SEED['plans'])
    assert plan_settings.validate('premium', {'edits_per_file': ''}, SEED['plans']) == {'edits_per_file': None}


@pytest.mark.parametrize('field,low,floor', [('weekly_ai_documents', '4', '5'), ('weekly_file_jobs', '14', '15'),
                                             ('edits_per_file', '2', '3')])
def test_no_paid_plan_gives_less_than_free(field, low, floor):
    plans = SEED['plans']
    for plan in ('plus', 'premium'):
        with pytest.raises(plan_settings.PlanError, match='cannot be below the free plan'):
            plan_settings.validate(plan, {field: low}, plans)
        assert plan_settings.validate(plan, {field: floor}, plans) == {field: int(floor)}, 'equal to Free is allowed'
        assert plan_settings.validate(plan, {field: ''}, plans) == {field: None}, 'unlimited is never below Free'
    # Free as it stands is the floor, panel changes included.
    plan_settings.save('free', {field: 1})
    assert plan_settings.validate('plus', {field: low}, plans) == {field: int(low)}


def test_a_paid_number_under_an_unlimited_free_value_is_refused():
    """Free can no longer be left unlimited, but a value stored before that rule must not let a paid plan under it."""
    IntegrationConfig.objects.update_or_create(pk=plan_settings.KEY, defaults={'configuration': {'free': {'edits_per_file': None}}})
    with pytest.raises(plan_settings.PlanError, match='cannot be below the free plan'):
        plan_settings.validate('plus', {'edits_per_file': '50'}, SEED['plans'])
    assert plan_settings.validate('plus', {'edits_per_file': ''}, SEED['plans']) == {'edits_per_file': None}


def test_only_values_an_edit_changes_are_held_to_the_floor():
    """The panel's form sends every field. Plans left out of step earlier must
    not stop an unrelated change to either of them, but a changed value is held."""
    IntegrationConfig.objects.update_or_create(pk=plan_settings.KEY, defaults={'configuration': {
        'plus': {'weekly_ai_documents': 2}}})
    free, plus = limits_for_plan('free'), limits_for_plan('plus')
    form = lambda limits: {field: '' if limits[field] is None else str(limits[field]) for field in plan_settings.FIELDS}
    plan_settings.save('free', {**form(free), 'max_file_mib': '30'})
    plan_settings.save('plus', {**form(plus), 'max_file_mib': '120'})
    assert (limits_for_plan('free')['max_file_mib'], limits_for_plan('plus')['max_file_mib']) == (30, 120)
    with pytest.raises(plan_settings.PlanError, match='cannot be below the free plan'):
        plan_settings.save('plus', {**form(plus), 'weekly_ai_documents': '3'})
    with pytest.raises(plan_settings.PlanError, match='cannot exceed a paid plan'):
        plan_settings.save('free', {**form(free), 'weekly_ai_documents': '6'})


def test_the_plans_page_advertises_the_weekly_limits_and_prices():
    plan_settings.save('free', {'weekly_file_jobs': 20})
    listed = {plan['id']: plan['limits'] for plan in Client().get('/api/v1/plans').json()['plans']}
    assert listed['free']['weekly_file_jobs'] == 20, 'the panel\'s figure is the one advertised'
    assert (listed['plus']['price_uzs'], listed['premium']['price_uzs']) == (20_000, 60_000)
    assert listed['premium']['weekly_ai_documents'] is None and listed['plus']['edits_per_file'] == 10


# ---------------------------------------------------------------- the deploy (migration 0019)


def deploy():
    importlib.import_module('apps.core.migrations.0019_weekly_limits').weekly(django_apps, None)


def overridden(configuration):
    IntegrationConfig.objects.update_or_create(pk=plan_settings.KEY, defaults={'configuration': configuration})


def test_the_deploy_strips_retired_overrides_and_old_prices_and_audits_each_plan():
    overridden({'free': {'ai_credits': 300, 'daily_file_tasks': 10, 'max_file_mib': 30},
                'plus': {'price_uzs': 15_000, 'file_tasks': 500},
                'premium': {'price_uzs': 90_000, 'max_pages_per_job': 900}})
    deploy()
    assert plan_settings.overrides() == {'free': {'max_file_mib': 30}, 'premium': {'max_pages_per_job': 900}}
    assert (limits_for_plan('plus')['price_uzs'], limits_for_plan('premium')['price_uzs']) == (20_000, 60_000)
    assert limits_for_plan('free')['max_file_mib'] == 30, 'every other change the panel made stays'
    entries = {entry.target: entry for entry in AuditLog.objects.filter(action='plan.limits')}
    assert {plan: entry.before for plan, entry in entries.items()} == {
        'free': {'ai_credits': 300, 'daily_file_tasks': 10},
        'plus': {'price_uzs': 15_000, 'file_tasks': 500},
        'premium': {'price_uzs': 90_000}}
    assert all(entry.after == {} and entry.actor is None and 'Weekly limits' in entry.reason for entry in entries.values())
    deploy()
    assert AuditLog.objects.count() == 3, 'running it again changes nothing'


def test_the_deploy_leaves_current_overrides_alone():
    overridden({'free': {'weekly_ai_documents': 4, 'max_file_mib': 30}})
    deploy()
    assert plan_settings.overrides() == {'free': {'weekly_ai_documents': 4, 'max_file_mib': 30}}
    assert not AuditLog.objects.exists()


def test_the_deploy_without_overrides_does_nothing():
    deploy()
    assert not IntegrationConfig.objects.filter(pk=plan_settings.KEY).exists() and not AuditLog.objects.exists()


def test_the_deploy_keeps_a_plan_the_owner_took_off_sale():
    """A blank price is the owner withdrawing a plan, not an old price: the deploy keeps it."""
    from apps.commerce import manual
    overridden({'premium': {'price_uzs': None, 'max_pages_per_job': 900}, 'plus': {'price_uzs': 45_000, 'ai_credits': 1}})
    assert 'premium' not in manual.prices()
    deploy()
    assert plan_settings.overrides() == {'premium': {'price_uzs': None, 'max_pages_per_job': 900}}
    assert manual.prices() == {'plus': 20_000}, 'Premium stays off sale; Plus loses only its old price'
    entries = {entry.target: entry.before for entry in AuditLog.objects.filter(action='plan.limits')}
    assert entries == {'plus': {'price_uzs': 45_000, 'ai_credits': 1}}
    deploy()
    assert plan_settings.overrides()['premium'] == {'price_uzs': None, 'max_pages_per_job': 900}
    assert AuditLog.objects.count() == 1, 'running it again changes nothing'
