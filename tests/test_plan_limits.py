"""What each plan gives and costs, and how the deploys that changed plans left the panel's changes.

Free: 5 AI documents and 15 file tasks a week, 3 edits per file. Plus, 20 000
so'm a month: 20 documents a week, 10 edits per file, file tools unlimited.
Premium, 60 000 so'm a month: everything unlimited. Blank (None) is unlimited.
Those, the prices and Premium's exemption from the channel gate are the only
differences: every other limit and every tool is the same on every plan, at
Premium's figures.
"""
import importlib

import pytest
from django.apps import apps as django_apps
from django.test import Client

from apps.core.policy import FEATURES, POLICY_VERSION, SEED, limits_for_plan
from apps.studio.domain import MAX_QUESTIONS
from operations import plans as plan_settings
from operations.models import AuditLog, IntegrationConfig

pytestmark = pytest.mark.django_db
WEEKLY = ('weekly_ai_documents', 'weekly_file_jobs', 'edits_per_file')
RETIRED = ('file_tasks', 'file_page_units', 'ai_credits', 'daily_file_tasks', 'daily_ai_documents')
UNLIMITED = float('inf')
# What still differs by plan; every other limit is shared.
PER_PLAN = ('price_xtr', 'price_uzs', *WEEKLY)
SHARED = [key for key in SEED['plans']['premium'] if key not in PER_PLAN]


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


def test_every_other_limit_is_premiums_on_every_plan():
    """The owner's decision: Free and Plus get Premium's file size, pages, batch,
    sources, photos and every other cap; only the weekly limits, edits and price differ."""
    plans = SEED['plans']
    assert set(plans['free']) == set(plans['plus']) == set(plans['premium'])
    assert SHARED and all(plans['free'][key] == plans['plus'][key] == plans['premium'][key] for key in SHARED), \
        {key: [plans[plan][key] for plan in plans] for key in SHARED}
    assert [plans['free'][key] for key in ('max_file_mib', 'max_pages_per_job', 'batch_files', 'max_generated_pdf_pages',
                                           'max_generated_slides')] == [200, 1000, 25, 35, 60]


def test_every_tool_is_on_every_plan():
    """No tool is a sample, limited or missing on Free or Plus any more."""
    differing = {fid: feature['plans'] for fid, feature in FEATURES.items() if len(set(feature['plans'].values())) > 1}
    assert not differing


def test_a_free_account_may_use_every_released_tool(settings):
    """The plan gate reads the catalog: a Free account is eligible for everything a paid one is."""
    from apps.core import policy
    from tests.test_platform import account
    settings.ENABLE_BETA_TOOLS = True
    free = account(77001)
    assert free.plan == 'free'
    listed = policy.catalog(free)
    assert listed and all(row['eligible'] for row in listed)
    for feature_id in policy.enabled_capabilities():
        assert policy.require_feature(free, feature_id)['id'] == feature_id


def test_the_plans_page_lists_the_same_tools_and_limits_on_every_plan(settings):
    settings.ENABLE_BETA_TOOLS = True
    plans = {plan['id']: plan for plan in Client().get('/api/v1/plans').json()['plans']}
    assert plans['free']['features'] and plans['free']['features'] == plans['plus']['features'] == plans['premium']['features']
    shared = lambda plan: {key: plans[plan]['limits'][key] for key in SHARED}
    assert shared('free') == shared('plus') == shared('premium')


# ---------------------------------------------------------------- code that once named a plan
# These three checked the plan by name rather than reading the catalog or the
# seed, so they kept Free (and Plus) out after both had given them the feature.

WORKFLOW = {'name': 'Turn and keep page one', 'steps': [
    {'feature_id': 'pdf.rotate', 'parameters': {'angle': 90}},
    {'feature_id': 'pdf.extract_pages', 'parameters': {'pages': '1'}}]}


def test_a_free_account_saves_and_runs_a_workflow(settings, hold_back):
    from apps.studio.models import WorkflowRun
    from tests.test_platform import account, upload, login_client
    settings.ENABLE_BETA_TOOLS = settings.LOCAL_SYNC_JOBS = True
    free = account(77002)
    asset, client = upload(free), login_client(free)
    listed = client.get('/api/v1/workflows').json()
    assert listed['limit'] == SEED['plans']['premium']['saved_workflows']
    saved = client.post('/api/v1/workflows', WORKFLOW, content_type='application/json')
    assert saved.status_code == 201, saved.content
    url = f"/api/v1/workflows/{saved.json()['id']}"
    quote = client.post(url + '/quote', {'input_ids': [str(asset.id)]}, content_type='application/json')
    assert quote.status_code == 200, quote.content
    body = {'version': quote.json()['version'], 'input_ids': quote.json()['input_ids'], 'confirmed': True,
            'confirmation_token': quote.json()['confirmation_token']}
    ran = client.post(url + '/run', body, content_type='application/json', HTTP_IDEMPOTENCY_KEY='free-workflow-run')
    assert ran.status_code == 200, ran.content
    assert WorkflowRun.objects.get(account=free).status == 'succeeded'
    # A plan the catalog leaves saved workflows out of is still refused.
    hold_back('workflow.saved', 'free')
    refused = client.post(url + '/quote', {'input_ids': [str(asset.id)]}, content_type='application/json')
    assert refused.status_code == 403 and refused.json()['error']['code'] == 'feature_not_in_plan'


@pytest.mark.parametrize('plan', ['free', 'plus'])
def test_every_plan_saves_form_templates(settings, plan, hold_back):
    from apps.commerce.services import create_invoice, sandbox_pay
    from apps.studio.models import SavedDefinition
    from tests.test_platform import account, login_client
    settings.DEBUG = settings.COMMERCE_SANDBOX_ENABLED = True
    customer = account(77003)
    if plan == 'plus':
        invoice, _ = create_invoice(customer, 'plus', 'form-templates-plus')
        sandbox_pay(customer, invoice.id)
        customer.refresh_from_db()
    client = login_client(customer)
    template = {'name': 'Customer data', 'content': {'commands': [{'type': 'fill_form', 'field': 'customer', 'value': 'Ali'}]}}
    assert client.get('/api/v1/editor/form-templates').json()['limit'] == 30
    saved = client.post('/api/v1/editor/form-templates', template, content_type='application/json')
    assert saved.status_code == 201, saved.content
    # Left out of the plan in the catalog, the plan keeps none and saves none.
    hold_back('editor.form_templates', plan)
    assert client.get('/api/v1/editor/form-templates').json()['limit'] == 0
    refused = client.post('/api/v1/editor/form-templates', template, content_type='application/json')
    assert refused.status_code == 403 and refused.json()['error']['code'] == 'saved_limit'
    assert SavedDefinition.objects.filter(account=customer, kind='form').count() == 1


def test_a_free_document_may_carry_as_many_questions_as_premium(settings):
    from apps.commerce.services import create_invoice, sandbox_pay
    from apps.studio.domain import limits
    from tests.test_platform import account
    settings.DEBUG = settings.COMMERCE_SANDBOX_ENABLED = True
    free, premium = account(77004), account(77005)
    invoice, _ = create_invoice(premium, 'premium', 'questions-premium')
    sandbox_pay(premium, invoice.id)
    premium.refresh_from_db()
    assert premium.plan == 'premium'
    assert limits(free)['questions'] == limits(premium)['questions'] == MAX_QUESTIONS


def _reply(schema, questions):
    """A reply that is valid but for its questions: every other field empty."""
    blank = {'string': '', 'array': [], 'boolean': True, 'integer': 0}
    body = {key: (definition.get('enum') or [blank[definition['type']]])[0]
            for key, definition in schema['properties'].items()}
    question = {'id': 'q', 'stem': 'A question?', 'options': ['Yes', 'No'], 'answer': 'Yes',
                'explanation': 'Because.', 'topic': 'Topic', 'marks': 1}
    return {**body, 'questions': [dict(question, id=f'q{n}') for n in range(questions)]}


def test_a_test_at_the_question_cap_passes_the_provider_schema():
    # The schema check refuses any array of more than 100 items, and a reply
    # refused for its shape is refused again: a cap above it can never be met.
    from apps.studio.provider import SCHEMA, SLIDE_SCHEMA, _Rejected, _validate
    for schema in (SCHEMA, SLIDE_SCHEMA):
        _validate(_reply(schema, MAX_QUESTIONS), schema)
        with pytest.raises(_Rejected):
            _validate(_reply(schema, 101), schema)


def test_a_test_at_the_question_cap_fits_beside_the_fullest_last_call():
    # Every question is written by the last call, beside its pages. What that
    # call needs has to fit one reply: a cut-off reply is retried at the same
    # ceiling and fails the same way, so the document is never made.
    from apps.studio import pages
    assert pages.batches(pages.DEFAULT_PAGES) == [(0, pages.DEFAULT_PAGES)]
    for count in range(1, 201):
        first, last = pages.batches(count)[-1]
        need = (max(pages.MIN_CALL_TOKENS, pages.response_tokens(last - first))
                + pages.QUESTION_TOKENS * MAX_QUESTIONS)
        assert need <= pages.RESPONSE_CEILING, (count, need)


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
    plan_settings.save('plus', {**form(limits_for_plan('plus')), 'max_file_mib': '120'})
    assert [limits_for_plan(plan)['max_file_mib'] for plan in ('free', 'plus', 'premium')] == [120, 120, 120]
    assert limits_for_plan('plus')['weekly_ai_documents'] == 2, 'the step Plus was left out of is its own'
    with pytest.raises(plan_settings.PlanError, match='cannot be below the free plan'):
        plan_settings.save('plus', {**form(plus), 'weekly_ai_documents': '3'})
    with pytest.raises(plan_settings.PlanError, match='cannot exceed a paid plan'):
        plan_settings.save('free', {**form(free), 'weekly_ai_documents': '6'})


def test_a_shared_limit_edited_on_one_plan_is_written_to_every_plan():
    """Only prices and the weekly limits differ by plan, so a page ceiling raised
    on Premium's form is every plan's ceiling, and Free may go first."""
    changes = plan_settings.save('premium', {'max_generated_pdf_pages': '45'})
    assert [limits_for_plan(plan)['max_generated_pdf_pages'] for plan in ('free', 'plus', 'premium')] == [45, 45, 45]
    seeded = SEED['plans']['premium']['max_generated_pdf_pages']
    assert changes == {plan: ({'max_generated_pdf_pages': seeded}, {'max_generated_pdf_pages': 45})
                       for plan in ('free', 'plus', 'premium')}, 'one change for each plan, so one audit row each'
    plan_settings.save('free', {'max_deck_images': '20', 'max_file_mib': '300'})
    assert all((limits_for_plan(plan)['max_deck_images'], limits_for_plan(plan)['max_file_mib']) == (20, 300)
               for plan in ('free', 'plus', 'premium'))
    assert shared_limits('free') == shared_limits('plus') == shared_limits('premium')
    from apps.studio.pages import ceiling
    from tests.test_platform import account
    assert ceiling(account(77010), 'pdf') == 45, 'what Free is given follows'
    with pytest.raises(plan_settings.PlanError, match='cannot exceed a paid plan'):
        plan_settings.validate('free', {'edits_per_file': '11'}, SEED['plans'])


def test_weekly_limits_edits_and_prices_stay_each_plans_own():
    weekly = {'weekly_ai_documents': [5, 20, None], 'weekly_file_jobs': [15, None, None], 'edits_per_file': [3, 10, None]}
    changes = plan_settings.save('plus', {'weekly_ai_documents': '25', 'weekly_file_jobs': '400', 'edits_per_file': '12',
                                          'price_uzs': '25000'})
    assert set(changes) == {'plus'}, 'no other plan changed'
    plan_settings.save('free', {'weekly_file_jobs': '16'})
    plan_settings.save('premium', {'edits_per_file': '50', 'price_uzs': '65000'})
    assert {plan: [limits_for_plan(plan)[key] for key in weekly] for plan in ('free', 'plus', 'premium')} == {
        'free': [5, 16, 3], 'plus': [25, 400, 12], 'premium': [None, None, 50]}
    assert [limits_for_plan(plan)['price_uzs'] for plan in ('free', 'plus', 'premium')] == [None, 25_000, 65_000]


def test_restoring_a_plan_puts_the_shared_limits_back_on_every_plan():
    plan_settings.save('plus', {'max_file_mib': '300', 'weekly_ai_documents': '25'})
    plan_settings.save('premium', {'price_uzs': '65000'})
    changes = plan_settings.reset('plus')
    seeded = SEED['plans']['plus']['max_file_mib']
    assert [limits_for_plan(plan)['max_file_mib'] for plan in ('free', 'plus', 'premium')] == [seeded] * 3
    assert limits_for_plan('plus')['weekly_ai_documents'] == 20
    assert limits_for_plan('premium')['price_uzs'] == 65_000, 'another plan keeps its own'
    assert set(changes) == {'free', 'plus', 'premium'}
    assert plan_settings.overrides() == {'premium': {'price_uzs': 65_000}}


def test_saving_each_plan_as_seeded_passes_and_stores_nothing():
    """The panel's whole form, unchanged, must save on every plan now Free carries Premium's caps."""
    for plan, limits in SEED['plans'].items():
        form = {field: '' if limits[field] is None else str(limits[field]) for field in plan_settings.FIELDS}
        assert plan_settings.save(plan, form) == {}, plan
    assert plan_settings.overrides() == {}


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


# ---------------------------------------------------------------- the deploy (migration 0020)


def equal_deploy():
    importlib.import_module('apps.core.migrations.0020_equal_plan_limits').equalize(django_apps, None)


def shared_limits(plan):
    limits = limits_for_plan(plan)
    return {key: limits[key] for key in SHARED}


def test_the_equal_limits_deploy_gives_free_and_plus_premiums_limits_and_audits_each_plan():
    """A Free or Plus override would keep an old cap past the seed; a Premium one would leave them behind."""
    overridden({'free': {'max_file_mib': 30, 'max_generated_pdf_pages': 9, 'weekly_ai_documents': 4, 'edits_per_file': 2},
                'plus': {'max_deck_images': 6, 'max_generated_slides': 77, 'price_uzs': 25_000, 'weekly_file_jobs': 40},
                'premium': {'max_pages_per_job': 1500, 'max_generated_slides': 77, 'price_uzs': 70_000,
                            'weekly_ai_documents': 100}})
    equal_deploy()
    copied = {'max_pages_per_job': 1500, 'max_generated_slides': 77}
    assert plan_settings.overrides() == {
        'free': {'weekly_ai_documents': 4, 'edits_per_file': 2, **copied},
        'plus': {'price_uzs': 25_000, 'weekly_file_jobs': 40, **copied},
        'premium': {**copied, 'price_uzs': 70_000, 'weekly_ai_documents': 100}}
    assert shared_limits('free') == shared_limits('plus') == shared_limits('premium')
    assert (shared_limits('free')['max_file_mib'], shared_limits('free')['max_pages_per_job']) == (200, 1500)
    # Weekly limits, edits and prices stay each plan's own.
    assert [limits_for_plan('free')[key] for key in WEEKLY] == [4, 15, 2]
    assert (limits_for_plan('plus')['price_uzs'], limits_for_plan('plus')['weekly_file_jobs']) == (25_000, 40)
    assert (limits_for_plan('premium')['price_uzs'], limits_for_plan('premium')['weekly_ai_documents']) == (70_000, 100)
    entries = {entry.target: entry for entry in AuditLog.objects.filter(action='plan.limits')}
    assert {plan: (entry.before, entry.after) for plan, entry in entries.items()} == {
        'free': ({'max_file_mib': 30, 'max_generated_pdf_pages': 9}, copied),
        'plus': ({'max_deck_images': 6}, {'max_pages_per_job': 1500})}, 'a value already equal is not a change'
    assert all(entry.actor is None and 'same on every plan' in entry.reason for entry in entries.values())
    equal_deploy()
    assert AuditLog.objects.count() == 2, 'running it again changes nothing'


def test_a_premium_change_made_in_the_panel_reaches_free_and_plus():
    # Made before this release, when the panel still edited these per plan.
    overridden({'premium': {'max_file_mib': 300}})
    equal_deploy()
    assert [limits_for_plan(plan)['max_file_mib'] for plan in ('free', 'plus', 'premium')] == [300, 300, 300]
    entries = {entry.target: (entry.before, entry.after) for entry in AuditLog.objects.filter(action='plan.limits')}
    assert entries == {'free': ({}, {'max_file_mib': 300}), 'plus': ({}, {'max_file_mib': 300})}


def test_the_equal_limits_deploy_leaves_weekly_limits_prices_and_a_plan_off_sale_alone():
    from apps.commerce import manual
    overridden({'free': {'weekly_file_jobs': 20}, 'plus': {'price_uzs': None, 'edits_per_file': 12},
                'premium': {'price_uzs': 65_000, 'weekly_ai_documents': 50}})
    equal_deploy()
    assert plan_settings.overrides() == {'free': {'weekly_file_jobs': 20}, 'plus': {'price_uzs': None, 'edits_per_file': 12},
                                         'premium': {'price_uzs': 65_000, 'weekly_ai_documents': 50}}
    assert manual.prices() == {'premium': 65_000}, 'Plus stays off sale'
    assert not AuditLog.objects.exists()


def test_the_equal_limits_deploy_drops_a_plan_left_with_nothing_of_its_own():
    """Free overridden only in shared limits has nothing left to store once they go;
    a broken Premium entry, which pricing ignores, is nothing to copy."""
    overridden({'free': {'max_file_mib': 30}, 'premium': 'not-a-dict'})
    equal_deploy()
    assert plan_settings.overrides() == {'premium': 'not-a-dict'}
    assert AuditLog.objects.get(target='free').before == {'max_file_mib': 30}


@pytest.mark.parametrize('broken', [None, ['x'], 'not-a-dict', 7])
def test_the_equal_limits_deploy_replaces_a_free_or_plus_entry_that_is_not_a_set_of_limits(broken):
    """Pricing ignores such an entry and runs the plan on the seed, so left in place
    it would keep the plan off Premium's figures: it is replaced, and audited."""
    overridden({'free': broken, 'plus': broken, 'premium': {'max_generated_pdf_pages': 40, 'price_uzs': 65_000}})
    assert limits_for_plan('free')['max_generated_pdf_pages'] != 40
    equal_deploy()
    assert plan_settings.overrides() == {'free': {'max_generated_pdf_pages': 40}, 'plus': {'max_generated_pdf_pages': 40},
                                         'premium': {'max_generated_pdf_pages': 40, 'price_uzs': 65_000}}
    assert shared_limits('free') == shared_limits('plus') == shared_limits('premium')
    entries = {entry.target: entry for entry in AuditLog.objects.filter(action='plan.limits')}
    assert {plan: (entry.before, entry.after) for plan, entry in entries.items()} == {
        plan: ({'entry': broken}, {'max_generated_pdf_pages': 40}) for plan in ('free', 'plus')}
    assert all(entry.actor is None and 'could not be read' in entry.reason and len(entry.reason) < 1000
               for entry in entries.values())
    equal_deploy()
    assert AuditLog.objects.count() == 2, 'running it again changes nothing'


def test_the_equal_limits_deploy_removes_a_broken_entry_when_premium_has_nothing_to_copy():
    overridden({'free': None, 'plus': {'weekly_file_jobs': 40}})
    equal_deploy()
    assert plan_settings.overrides() == {'plus': {'weekly_file_jobs': 40}}
    assert AuditLog.objects.get(action='plan.limits').target == 'free'
    equal_deploy()
    assert AuditLog.objects.count() == 1


def test_the_equal_limits_deploy_without_overrides_does_nothing():
    equal_deploy()
    assert not IntegrationConfig.objects.filter(pk=plan_settings.KEY).exists() and not AuditLog.objects.exists()
