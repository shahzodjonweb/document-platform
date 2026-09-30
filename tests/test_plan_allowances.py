"""What each plan gives, and that the allowance granted is the one advertised."""
import pytest
from django.test import Client

from apps.core.identity import resolve_account
from apps.core.models import UsageGrant
from apps.core.policy import SEED, limits_for_plan, usage_snapshot
from operations import plans as plan_settings

pytestmark = pytest.mark.django_db

# A typical AI document — an 8 or 9 slide deck, or a 10 page document with a
# source — is about 35 credits. The free plan is meant for daily work.
DOCUMENT_CREDITS = 35


def account(uid=4242):
    return resolve_account({'id': uid, 'first_name': 'Free', 'language_code': 'en'}, is_test=True)


def credits(customer):
    return usage_snapshot(customer)['meters']['ai_credits']


def test_the_free_plan_covers_an_ai_document_every_day():
    assert SEED['plans']['free']['ai_credits'] >= 30 * DOCUMENT_CREDITS
    assert SEED['plans']['free']['daily_file_tasks'] * 30 >= SEED['plans']['free']['file_tasks']


def test_every_paid_plan_gives_at_least_what_free_does():
    plans = SEED['plans']
    for key, free in plans['free'].items():
        if key == 'price_xtr' or not isinstance(free, int):
            continue
        for lower, higher in (('free', 'plus'), ('plus', 'premium')):
            value = plans[higher][key]
            assert value is None or value >= plans[lower][key], (key, lower, higher)


def test_a_new_free_account_gets_the_advertised_allowance():
    customer = account()
    assert credits(customer)['limit'] == SEED['plans']['free']['ai_credits']
    assert usage_snapshot(customer)['meters']['file_tasks']['limit'] == SEED['plans']['free']['file_tasks']


def test_an_administrators_change_is_what_free_accounts_are_given():
    """The pricing page shows the edited figure, so that has to be what is granted."""
    plan_settings.save('free', {'ai_credits': 2000})
    customer = account()
    assert credits(customer)['limit'] == 2000 == limits_for_plan('free')['ai_credits']
    listed = {plan['id']: plan for plan in Client().get('/api/v1/plans').json()['plans']}
    assert listed['free']['limits']['ai_credits'] == 2000


def test_a_raise_reaches_a_period_already_under_way():
    customer = account()
    usage_snapshot(customer)
    UsageGrant.objects.filter(account=customer, meter='ai_credits', source='included').update(consumed=100)
    plan_settings.save('free', {'ai_credits': 2000})
    after = credits(customer)
    assert after['limit'] == 2000 and after['remaining'] == 1900, 'what was used stays used'
    assert UsageGrant.objects.filter(account=customer, meter='ai_credits').count() == 1


def test_going_back_to_the_defaults_is_a_raise_too():
    """How production gets the new figure: its 300-credit override is removed."""
    plan_settings.save('free', {'ai_credits': 300})
    customer = account()
    assert credits(customer)['limit'] == 300
    plan_settings.reset('free')
    assert credits(customer)['limit'] == SEED['plans']['free']['ai_credits']


def test_only_free_allowances_are_raised_never_paid_or_granted_credit():
    from datetime import timedelta
    from django.utils import timezone
    from apps.commerce.services import raise_current_free_allowances
    customer = account()
    usage_snapshot(customer)
    soon = timezone.now() + timedelta(days=5)
    for source_id, source in (('payment:x:ai_credits', 'included'), ('admin:y:ai_credits', 'adjustment')):
        UsageGrant.objects.create(account=customer, meter='ai_credits', source=source, source_id=source_id,
                                  quantity=5, valid_from=timezone.now(), expires_at=soon)
    raise_current_free_allowances({'ai_credits': 5000})
    assert set(UsageGrant.objects.filter(source_id__startswith=('payment:')).values_list('quantity', flat=True)) == {5}
    assert UsageGrant.objects.get(source_id='admin:y:ai_credits').quantity == 5
    assert UsageGrant.objects.get(source_id__startswith='included:', meter='ai_credits').quantity == 5000


def test_the_deploy_raises_periods_under_way_and_respects_an_override():
    import importlib
    from django.apps import apps as django_apps
    migration = importlib.import_module('apps.core.migrations.0012_raise_free_allowances')
    old, overridden = account(), account(uid=4444)
    usage_snapshot(old), usage_snapshot(overridden)
    UsageGrant.objects.filter(source_id__startswith='included:').update(quantity=90)
    UsageGrant.objects.filter(source_id__startswith='included:', meter='file_tasks',
                              account=old).update(consumed=40)
    migration.raise_allowances(django_apps, None)
    tasks = UsageGrant.objects.get(account=old, meter='file_tasks')
    assert (tasks.quantity, tasks.consumed) == (300, 40)
    assert UsageGrant.objects.get(account=old, meter='ai_credits').quantity == 1050
    plan_settings.save('free', {'ai_credits': 300})
    UsageGrant.objects.filter(account=overridden, meter='ai_credits').update(quantity=90)
    migration.raise_allowances(django_apps, None)
    assert UsageGrant.objects.get(account=overridden, meter='ai_credits').quantity == 300


def test_a_cut_never_takes_back_what_a_period_was_given():
    customer = account()
    granted = credits(customer)['limit']
    plan_settings.save('free', {'ai_credits': 200})
    assert credits(customer)['limit'] == granted, 'the current period keeps its allowance'
    assert credits(account(uid=4343))['limit'] == 200, 'a period that starts after the cut gets the new figure'


def test_the_file_size_limit_can_be_changed_by_an_administrator():
    plan_settings.save('free', {'max_file_mib': 30})
    assert limits_for_plan('free')['max_file_mib'] == 30
    assert 'max_file_mb' not in plan_settings.FIELDS
    assert set(plan_settings.FIELDS) <= set(SEED['plans']['free']), 'every editable field is a real plan field'
