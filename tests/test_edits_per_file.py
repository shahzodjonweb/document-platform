"""AI edits are counted per generated file: Free has 3, Plus 10 and Premium as many as it likes.

An edit of an edit is still an edit of the first file, so a chain cannot start
the count again. When a file's edits are used up the next one is refused and
the next plan offered; edits never count against the week's documents.
"""
import pytest

from apps.core.allowance import ai_documents_this_week, edits_of, usage_snapshot
from apps.core.errors import DomainError
from apps.core.models import Account, Job
from apps.core.services import submit_job
from apps.studio.domain import create_draft, generation_quote, unpack
from tests.test_platform import account
from tests.test_revisions import generated

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def local_ai(settings):
    settings.DEBUG = True  # local authoring stands in for the AI provider
    settings.ENABLE_BETA_TOOLS = True


def on_plan(customer, plan):
    Account.objects.filter(pk=customer.pk).update(staff_plan=plan)
    customer.refresh_from_db()
    return customer


def asked(customer, draft, prompt='Use a friendlier tone.'):
    """A change asked for on a draft and priced; raises when the file has no edits left."""
    change = create_draft(customer, {'prompt': prompt, 'options': {'revise_draft_id': str(draft.id)}})
    return change, generation_quote(customer, change.id, change.version)


def edited(customer, draft, status='succeeded'):
    """One edit of `draft`, submitted and finished."""
    change, quote = asked(customer, draft)
    job, _ = submit_job(customer, quote.id, f'edit-{change.id}')
    Job.objects.filter(pk=job.pk).update(status=status)
    job.refresh_from_db()
    return change, job


def test_a_free_file_takes_three_edits_and_the_fourth_is_refused():
    customer = account()
    original = generated(customer)
    for _ in range(3):
        edited(customer, original)
    assert edits_of(customer, original.id) == 3
    with pytest.raises(DomainError) as refused:
        asked(customer, original)
    assert refused.value.code == 'edit_limit' and refused.value.status == 429
    assert refused.value.params == {'limit': 3, 'used': 3}
    assert usage_snapshot(customer)['edits_per_file'] == 3


def test_the_quote_names_the_first_file_through_a_chain_of_edits():
    customer = account()
    a = generated(customer)
    b, first = edited(customer, a)
    c, second = edited(customer, b)
    assert first.quote.parameters['root_draft_id'] == second.quote.parameters['root_draft_id'] == str(a.id)
    assert unpack(c.encrypted_data)['revision']['root_draft_id'] == str(a.id)
    assert unpack(c.encrypted_data)['revision']['source_draft_id'] == str(b.id), 'the change still applies to B'
    assert edits_of(customer, a.id) == 2 and edits_of(customer, b.id) == 0
    edited(customer, c)
    with pytest.raises(DomainError, match='edit_limit'):
        asked(customer, c)
    with pytest.raises(DomainError, match='edit_limit'):
        asked(customer, a)


def test_each_generated_file_has_its_own_edits():
    customer = account()
    first, second = generated(customer), generated(customer, 'A 3 page guide to river deltas.')
    for _ in range(3):
        edited(customer, first)
    edited(customer, second)
    assert (edits_of(customer, first.id), edits_of(customer, second.id)) == (3, 1)


def test_a_failed_edit_gives_its_place_back_and_a_retry_counts_once():
    from apps.studio.checkpoints import retry_quote
    customer = account()
    original = generated(customer)
    edited(customer, original)
    _, failed = edited(customer, original, status='failed')
    assert edits_of(customer, original.id) == 1
    retry = retry_quote(customer, failed.id)
    assert retry.parameters['root_draft_id'] == str(original.id)
    job, _ = submit_job(customer, retry.id, 'retry-of-the-edit')
    Job.objects.filter(pk=job.pk).update(status='succeeded')
    assert edits_of(customer, original.id) == 2
    edited(customer, original)
    with pytest.raises(DomainError, match='edit_limit'):
        asked(customer, original)


def test_a_change_priced_earlier_cannot_slip_past_the_limit():
    customer = account()
    original = generated(customer)
    early = [asked(customer, original, f'Change number {n}: use a friendlier tone.') for n in range(4)]
    for change, quote in early[:3]:
        job, _ = submit_job(customer, quote.id, f'early-edit-{change.id}')
        Job.objects.filter(pk=job.pk).update(status='succeeded')
    with pytest.raises(DomainError) as refused:
        submit_job(customer, early[3][1].id, 'early-edit-last')
    assert refused.value.code == 'edit_limit'
    assert edits_of(customer, original.id) == 3


def test_edits_never_count_as_documents_of_the_week():
    customer = account()
    original = generated(customer)
    for _ in range(3):
        edited(customer, original)
    assert ai_documents_this_week(customer) == 1


def test_plus_gets_ten_edits_a_file():
    customer = on_plan(account(), 'plus')
    original = generated(customer)
    for _ in range(10):
        edited(customer, original)
    with pytest.raises(DomainError) as refused:
        asked(customer, original)
    assert refused.value.params == {'limit': 10, 'used': 10}
    assert usage_snapshot(customer)['edits_per_file'] == 10


def test_premium_edits_without_a_limit():
    customer = on_plan(account(), 'premium')
    original = generated(customer)
    for _ in range(11):
        edited(customer, original)
    asked(customer, original)
    assert edits_of(customer, original.id) == 11
    assert usage_snapshot(customer)['edits_per_file'] is None


def test_the_owner_can_change_edits_per_file():
    from operations import plans as plan_settings
    customer = account()
    original = generated(customer)
    edited(customer, original)
    plan_settings.save('free', {'edits_per_file': 1})
    with pytest.raises(DomainError) as refused:
        asked(customer, original)
    assert refused.value.params == {'limit': 1, 'used': 1}


def test_an_edit_priced_before_the_deploy_is_refused():
    """A quote from the credit days names no first file; it must not reach a job."""
    customer = account()
    original = generated(customer)
    change, quote = asked(customer, original)
    quote.parameters = {key: value for key, value in quote.parameters.items() if key != 'root_draft_id'}
    quote.policy = {**quote.policy, 'version': 'credits-v1'}
    quote.save(update_fields=['parameters', 'policy'])
    with pytest.raises(DomainError) as refused:
        submit_job(customer, quote.id, f'old-edit-{change.id}')
    assert refused.value.code == 'quote_policy_changed' and refused.value.status == 409
    assert not Job.objects.filter(parameters__revision=True).exists()


# ---------------------------------------------------------------- only a made file can be edited


def unmade(customer, title='Seed'):
    """A draft with text in every section, never generated: a new draft holds its source text."""
    words = '\n\n'.join(' '.join(['word'] * 60) for _ in range(3))
    return create_draft(customer, {'title': title, 'source_text': words})


def test_a_draft_that_was_never_generated_cannot_be_edited():
    """Edits are counted per file, not per week, so an 'edit' of a draft never
    made would be a new document outside the week's limit, again and again."""
    customer = account()
    seed = unmade(customer)
    with pytest.raises(DomainError) as refused:
        asked(customer, seed, 'Write a 3 page essay about volcanoes.')
    assert refused.value.code == 'revision_not_ready'
    assert not Job.objects.exists() and ai_documents_this_week(customer) == 0


def test_an_outline_does_not_make_a_file_that_can_be_edited():
    from apps.studio.outlines import create_outline_quote
    customer = account()
    seed = unmade(customer)
    outline = create_outline_quote(customer, seed.id, seed.version)
    job, _ = submit_job(customer, outline.id, 'outline-only')
    Job.objects.filter(pk=job.pk).update(status='succeeded')
    with pytest.raises(DomainError, match='revision_not_ready'):
        asked(customer, seed)


def test_a_document_still_being_made_cannot_be_edited_yet():
    from apps.studio.domain import DOCUMENT
    customer = account()
    seed = create_draft(customer, {'feature_id': DOCUMENT, 'prompt': 'A two page note on tides.'})
    quote = generation_quote(customer, seed.id, seed.version)
    job, _ = submit_job(customer, quote.id, 'still-running')
    for status in ('queued', 'running', 'failed'):
        Job.objects.filter(pk=job.pk).update(status=status)
        with pytest.raises(DomainError, match='revision_not_ready'):
            asked(customer, seed)


def test_a_generated_file_still_takes_its_three_edits_on_free():
    customer = account()
    original = generated(customer)
    for _ in range(3):
        edited(customer, original)
    assert edits_of(customer, original.id) == 3 and ai_documents_this_week(customer) == 1


def test_an_edit_drafted_before_the_check_is_refused_when_it_is_submitted():
    """The check is asked again under the account lock, so a draft or quote that
    was made before it existed cannot reach a job."""
    from apps.core.allowance import require_quote
    from apps.core.models import Quote
    from apps.studio.domain import DOCUMENT
    customer = account()
    seed = unmade(customer)
    old = Quote(account=customer, feature_id=DOCUMENT,
                parameters={'generation_draft_id': str(seed.id), 'revision': True, 'root_draft_id': str(seed.id)})
    with pytest.raises(DomainError, match='revision_not_ready'):
        require_quote(customer, old)
    # The same edit drafted and priced while the plan did not limit the week,
    # then submitted on Free, is refused at submission.
    on_plan(customer, 'premium')
    change, quote = asked(customer, seed, 'Write a 3 page essay about volcanoes.')
    from apps.commerce.services import refresh_account_entitlement
    assert refresh_account_entitlement(on_plan(customer, '')) == 'free'
    with pytest.raises(DomainError, match='revision_not_ready'):
        submit_job(customer, quote.id, f'late-{change.id}')
    assert not Job.objects.filter(parameters__revision=True).exists()


def test_without_a_weekly_limit_an_unmade_draft_gains_nothing_and_is_let_through():
    """Premium makes as many documents as it likes; an edit of a draft is no way around a limit it does not have."""
    customer = on_plan(account(), 'premium')
    seed = unmade(customer)
    change, quote = asked(customer, seed)
    assert quote.parameters['root_draft_id'] == str(seed.id)


def test_an_edit_made_before_roots_were_recorded_counts_as_made():
    """A chain from before the deploy roots at the edit it changed, and that
    edit, once finished, is a made file."""
    from apps.studio.domain import pack
    from apps.studio.models import GenerationDraft
    customer = on_plan(account(), 'plus')
    a = generated(customer)
    b, _ = edited(customer, a)
    c, _ = edited(customer, b)
    data = unpack(c.encrypted_data)
    data['revision'].pop('root_draft_id')
    GenerationDraft.objects.filter(pk=c.pk).update(encrypted_data=pack(data))
    d, quote = asked(customer, c)
    assert quote.parameters['root_draft_id'] == str(b.id)


def test_the_api_refuses_an_edit_of_a_draft_never_generated_after_the_week_is_used_up():
    """The reviewer's probe: with the week's five documents made, an 'edit' of a
    fresh draft used to make a sixth."""
    from tests.test_platform import login_client
    from tests.test_weekly_limits import made
    customer = account(77)
    made(customer, 5)
    client = login_client(customer)
    words = '\n\n'.join(' '.join(['word'] * 60) for _ in range(3))
    seed = client.post('/api/v1/generation/drafts', {'title': 'Seed', 'source_text': words},
                       content_type='application/json')
    assert seed.status_code == 201, seed.content
    change = client.post('/api/v1/generation/drafts', {'prompt': 'Write a 3 page essay about volcanoes.',
                                                       'options': {'revise_draft_id': seed.json()['id']}},
                         content_type='application/json')
    assert change.status_code == 400 and change.json()['error']['code'] == 'revision_not_ready', change.content
    assert 'Generate it first' in change.json()['error']['message']
    assert ai_documents_this_week(customer) == 5 and Job.objects.filter(account=customer).count() == 5
