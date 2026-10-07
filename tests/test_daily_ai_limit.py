"""Free accounts make at most a few AI documents a day; paid plans have no daily limit."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.errors import DomainError
from apps.core.models import Account, Job
from apps.core.services import submit_job
from apps.studio.domain import DOCUMENT, SLIDES, ai_documents_today, create_draft, generation_quote
from operations import plans as plan_settings
from tests.test_platform import account

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def local_ai(settings):
    settings.DEBUG = True  # local authoring stands in for the AI provider
    settings.ENABLE_BETA_TOOLS = True


def priced(customer, feature=DOCUMENT):
    draft = create_draft(customer, {'feature_id': feature, 'prompt': 'A two page note on tides.'})
    return generation_quote(customer, draft.id, draft.version)


def made(customer, n, feature=DOCUMENT):
    """n AI documents started and finished (free accounts run one job at a time)."""
    jobs = []
    for _ in range(n):
        job = submit_job(customer, priced(customer, feature).id, f'ai-day-{Job.objects.count()}-{customer.pk}')[0]
        Job.objects.filter(pk=job.pk).update(status='succeeded')
        jobs.append(job)
    return jobs


def test_a_free_account_makes_three_ai_documents_a_day_and_is_told_when():
    customer = account()
    made(customer, 2)
    made(customer, 1, SLIDES)
    assert ai_documents_today(customer) == 3, 'documents and decks count together'
    with pytest.raises(DomainError) as refused:
        priced(customer)
    assert refused.value.code == 'daily_ai_limit' and refused.value.status == 429
    assert refused.value.params['limit'] == 3
    tomorrow = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    assert refused.value.params['resets_at'] == tomorrow.isoformat()


def test_a_quote_taken_earlier_cannot_slip_past_the_limit():
    customer = account()
    early = [priced(customer) for _ in range(4)]
    for i, quote in enumerate(early[:3]):
        job, _ = submit_job(customer, quote.id, f'early-quote-{i}')
        Job.objects.filter(pk=job.pk).update(status='succeeded')
    with pytest.raises(DomainError, match='daily_ai_limit'):
        submit_job(customer, early[3].id, 'early-quote-3')


def test_what_produced_nothing_does_not_count():
    customer = account()
    jobs = made(customer, 3)
    Job.objects.filter(pk=jobs[0].pk).update(status='failed')
    Job.objects.filter(pk=jobs[1].pk).update(status='canceled')
    assert ai_documents_today(customer) == 1
    priced(customer)


def test_an_outline_is_not_a_document():
    customer = account()
    jobs = made(customer, 3)
    Job.objects.filter(pk=jobs[0].pk).update(parameters={**jobs[0].parameters, 'stage': 'outline'})
    assert ai_documents_today(customer) == 2


def test_yesterdays_documents_do_not_count_today():
    customer = account()
    made(customer, 3)
    Job.objects.filter(account=customer).update(created_at=timezone.now() - timedelta(days=1))
    assert ai_documents_today(customer) == 0
    priced(customer)


def test_a_paid_plan_has_no_daily_limit():
    customer = account()
    Account.objects.filter(pk=customer.pk).update(staff_plan='premium')
    customer.refresh_from_db()
    made(customer, 4)
    assert ai_documents_today(customer) == 4


def test_the_owner_can_change_or_lift_the_free_limit():
    customer = account()
    made(customer, 3)
    plan_settings.save('free', {'daily_ai_documents': 5})
    made(customer, 2)
    with pytest.raises(DomainError, match='daily_ai_limit'):
        priced(customer)
    plan_settings.save('free', {'daily_ai_documents': ''})
    priced(customer)


def test_a_retry_of_a_submission_already_accepted_is_not_a_new_document():
    customer = account()
    quote = priced(customer)
    job, _ = submit_job(customer, quote.id, 'same-request')
    Job.objects.filter(pk=job.pk).update(status='succeeded')
    made(customer, 2)
    again, created = submit_job(customer, quote.id, 'same-request')
    assert again.pk == job.pk and not created


def test_a_change_to_a_document_does_not_use_up_the_day(monkeypatch):
    """Free customers spent their day correcting what came back wrong.

    A change still costs its credits; it just is not one of the three
    documents a day.
    """
    from apps.studio import domain
    from apps.studio.domain import unpack
    customer = account()
    made(customer, 3)
    with pytest.raises(DomainError, match='daily_ai_limit'):
        priced(customer)
    original = create_draft(customer, {'feature_id': DOCUMENT, 'source_text': 'Tides rise twice a day.'})
    data = unpack(original.encrypted_data)
    monkeypatch.setattr(domain, 'revision_source', lambda account, identifier: (original, data))
    change = create_draft(customer, {'prompt': 'Use a friendlier tone.', 'options': {'revise_draft_id': str(original.id)}})
    quote = generation_quote(customer, change.id, change.version)
    assert quote.parameters['revision'] is True
    job, _ = submit_job(customer, quote.id, 'change-after-the-limit')
    Job.objects.filter(pk=job.pk).update(status='succeeded')
    assert ai_documents_today(customer) == 3, 'the change is not counted'
    with pytest.raises(DomainError, match='daily_ai_limit'):
        priced(customer)
