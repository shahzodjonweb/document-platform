"""Each plan makes a number of AI documents a week; a week starts on Monday at 00:00 in Tashkent.

Free makes 5, Plus 20 and Premium as many as it likes. Documents and decks
count together; an outline, an edit and anything that produced nothing do not.
"""
from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

import pytest

from apps.core.allowance import LIMIT_CODES, ai_documents_this_week, usage_snapshot, week_bounds
from apps.core.errors import DomainError, error_data
from apps.core.models import Account, Job
from apps.core.services import submit_job
from apps.studio.domain import DOCUMENT, SLIDES, create_draft, generation_quote
from apps.studio.outlines import create_outline_quote
from operations import plans as plan_settings
from tests.test_platform import account

pytestmark = pytest.mark.django_db
UTC = dt_timezone.utc
TASHKENT = ZoneInfo('Asia/Tashkent')
# Monday 19 October 2026 starts at 00:00 in Tashkent, which is 19:00 on Sunday in UTC.
MONDAY = datetime(2026, 10, 19, tzinfo=TASHKENT)


@pytest.fixture(autouse=True)
def local_ai(settings):
    settings.DEBUG = True  # local authoring stands in for the AI provider
    settings.ENABLE_BETA_TOOLS = True


def on_plan(customer, plan):
    """A plan assigned by staff, the way support comps one."""
    Account.objects.filter(pk=customer.pk).update(staff_plan=plan)
    customer.refresh_from_db()
    return customer


def priced(customer, feature=DOCUMENT):
    draft = create_draft(customer, {'feature_id': feature, 'prompt': 'A two page note on tides.'})
    return generation_quote(customer, draft.id, draft.version)


def made(customer, n, feature=DOCUMENT):
    """n AI documents started and finished (free accounts run one job at a time)."""
    jobs = []
    for _ in range(n):
        job = submit_job(customer, priced(customer, feature).id, f'ai-week-{Job.objects.count()}-{customer.pk}')[0]
        Job.objects.filter(pk=job.pk).update(status='succeeded')
        jobs.append(job)
    return jobs


def started_at(jobs, when):
    Job.objects.filter(pk__in=[job.pk for job in jobs]).update(created_at=when)


def test_a_free_account_makes_five_ai_documents_a_week_and_is_told_when():
    customer = account()
    made(customer, 3)
    made(customer, 2, SLIDES)
    assert ai_documents_this_week(customer) == 5, 'documents and decks count together'
    assert usage_snapshot(customer)['ai_documents'] == {'limit': 5, 'used': 5, 'remaining': 0}
    with pytest.raises(DomainError) as refused:
        priced(customer)
    assert refused.value.code == 'weekly_ai_limit' and refused.value.status == 429
    resets_at = week_bounds()[1]
    assert refused.value.params == {'limit': 5, 'used': 5, 'resets_at': resets_at.isoformat()}
    assert resets_at.astimezone(TASHKENT).weekday() == 0 and resets_at.astimezone(TASHKENT).time().isoformat() == '00:00:00'


def test_a_quote_taken_earlier_cannot_slip_past_the_limit():
    """Quotes are free to take; the count that matters is the one under the account lock."""
    customer = account()
    early = [priced(customer) for _ in range(6)]
    for i, quote in enumerate(early[:5]):
        job, _ = submit_job(customer, quote.id, f'early-quote-{i}')
        Job.objects.filter(pk=job.pk).update(status='succeeded')
    with pytest.raises(DomainError, match='weekly_ai_limit'):
        submit_job(customer, early[5].id, 'early-quote-5')
    assert Job.objects.filter(account=customer).count() == 5


def test_what_produced_nothing_does_not_count():
    customer = account()
    jobs = made(customer, 5)
    for job, status in zip(jobs, ('failed', 'canceled', 'expired', 'no_op')):
        Job.objects.filter(pk=job.pk).update(status=status)
    assert ai_documents_this_week(customer) == 1
    made(customer, 4)
    with pytest.raises(DomainError, match='weekly_ai_limit'):
        priced(customer)


def test_a_document_still_being_made_counts():
    customer = account()
    made(customer, 4)
    job = submit_job(customer, priced(customer).id, 'still-running')[0]
    assert job.status == 'queued' and ai_documents_this_week(customer) == 5


def test_an_outline_is_checked_but_not_counted():
    """Planning the week's last document is allowed; planning a sixth is not."""
    customer = account()
    made(customer, 4)
    draft = create_draft(customer, {'feature_id': DOCUMENT, 'prompt': 'A two page note on tides.'})
    outline = create_outline_quote(customer, draft.id, draft.version)
    job, _ = submit_job(customer, outline.id, 'outline-of-the-fifth')
    Job.objects.filter(pk=job.pk).update(status='succeeded')
    assert ai_documents_this_week(customer) == 4
    made(customer, 1)
    late = create_draft(customer, {'feature_id': DOCUMENT, 'prompt': 'A two page note on waves.'})
    with pytest.raises(DomainError, match='weekly_ai_limit'):
        create_outline_quote(customer, late.id, late.version)


def test_a_replayed_submission_counts_once():
    customer = account()
    quote = priced(customer)
    job, _ = submit_job(customer, quote.id, 'same-request')
    Job.objects.filter(pk=job.pk).update(status='succeeded')
    made(customer, 4)
    again, created = submit_job(customer, quote.id, 'same-request')
    assert again.pk == job.pk and not created, 'a retry at the limit returns the job already made'
    assert ai_documents_this_week(customer) == 5


# ---------------------------------------------------------------- the week


def test_the_week_starts_on_monday_at_midnight_in_tashkent():
    sunday_late = MONDAY - timedelta(minutes=30)       # Sunday 23:30 in Tashkent
    monday_early = MONDAY + timedelta(minutes=10)      # Monday 00:10 in Tashkent
    assert week_bounds(sunday_late) == (MONDAY - timedelta(days=7), MONDAY)
    assert week_bounds(monday_early) == (MONDAY, MONDAY + timedelta(days=7))
    # Monday 00:00 in Tashkent is 19:00 on Sunday in UTC, not UTC's midnight.
    edge = datetime(2026, 10, 18, 19, 0, tzinfo=UTC)
    assert week_bounds(edge)[0] == edge == MONDAY
    assert week_bounds(edge - timedelta(seconds=1))[1] == edge
    assert week_bounds(datetime(2026, 10, 19, 1, 0, tzinfo=UTC))[0] == edge, 'a UTC Monday is already Tashkent\'s'
    assert week_bounds(datetime(2026, 10, 25, 18, 59, tzinfo=UTC))[0] == edge, 'the week runs to Sunday 23:59 in Tashkent'


def test_documents_either_side_of_the_reset():
    customer = account()
    before, after = made(customer, 3), made(customer, 2)
    started_at(before, MONDAY - timedelta(minutes=30))                 # Sunday 23:30 in Tashkent
    started_at(after, MONDAY + timedelta(minutes=10))                  # Monday 00:10 in Tashkent
    assert ai_documents_this_week(customer, now=MONDAY - timedelta(minutes=1)) == 3
    assert ai_documents_this_week(customer, now=MONDAY + timedelta(hours=1)) == 2
    # The 19:00 UTC edge: one second either side of it is a different week.
    started_at(before[:1], datetime(2026, 10, 18, 18, 59, 59, tzinfo=UTC))
    started_at(before[1:], datetime(2026, 10, 18, 19, 0, tzinfo=UTC))
    assert ai_documents_this_week(customer, now=MONDAY + timedelta(hours=1)) == 4
    snapshot = usage_snapshot(customer, now=MONDAY + timedelta(hours=1))
    assert snapshot['week'] == {'starts_at': MONDAY, 'resets_at': MONDAY + timedelta(days=7), 'time_zone': 'Asia/Tashkent'}
    assert snapshot['ai_documents'] == {'limit': 5, 'used': 4, 'remaining': 1}


def test_the_account_time_zone_does_not_move_the_week():
    """A week that followed the profile's zone could be started again by changing it."""
    customer = account()
    jobs = made(customer, 5)
    Account.objects.filter(pk=customer.pk).update(time_zone='America/Los_Angeles')
    customer.refresh_from_db()
    started_at(jobs, MONDAY - timedelta(minutes=30))
    # Both moments are one Sunday in Los Angeles, but a new week has begun in Tashkent.
    assert ai_documents_this_week(customer, now=MONDAY + timedelta(hours=2)) == 0
    assert usage_snapshot(customer, now=MONDAY + timedelta(hours=2))['week']['starts_at'] == MONDAY


def test_last_weeks_documents_do_not_count_this_week():
    customer = account()
    jobs = made(customer, 5)
    started_at(jobs, week_bounds()[0] - timedelta(seconds=1))
    assert ai_documents_this_week(customer) == 0
    priced(customer)


# ---------------------------------------------------------------- plans


def test_plus_makes_twenty_a_week(settings):
    from apps.commerce.services import create_invoice, sandbox_pay
    settings.COMMERCE_SANDBOX_ENABLED = True
    customer = account()
    invoice, _ = create_invoice(customer, 'plus', 'weekly-plus')
    sandbox_pay(customer, invoice.id)
    customer.refresh_from_db()
    assert customer.plan == 'plus'
    made(customer, 20)
    with pytest.raises(DomainError) as refused:
        priced(customer)
    assert refused.value.code == 'weekly_ai_limit' and refused.value.params['limit'] == 20


def test_premium_has_no_weekly_limit():
    customer = on_plan(account(), 'premium')
    made(customer, 21)
    assert usage_snapshot(customer)['ai_documents'] == {'limit': None, 'used': 21, 'remaining': None}
    priced(customer)


def test_a_staff_assigned_plan_brings_its_own_limit():
    customer = account()
    made(customer, 5)
    with pytest.raises(DomainError, match='weekly_ai_limit'):
        priced(customer)
    on_plan(customer, 'plus')
    priced(customer)
    assert usage_snapshot(customer)['ai_documents'] == {'limit': 20, 'used': 5, 'remaining': 15}


def test_the_owner_can_change_the_limit_from_the_panel():
    customer = account()
    made(customer, 2)
    plan_settings.save('free', {'weekly_ai_documents': 2})
    with pytest.raises(DomainError) as refused:
        priced(customer)
    assert refused.value.params['limit'] == 2
    plan_settings.save('free', {'weekly_ai_documents': 3})
    made(customer, 1)
    with pytest.raises(DomainError, match='weekly_ai_limit'):
        priced(customer)
    plan_settings.save('plus', {'weekly_ai_documents': ''})
    plus = on_plan(account(43), 'plus')
    assert usage_snapshot(plus)['ai_documents']['limit'] is None, 'blank lifts a paid plan\'s limit'


def test_an_edit_does_not_use_up_the_week():
    """Customers spent their allowance correcting what came back wrong.

    An edit draws on the file's own edits (tests/test_edits_per_file.py), never
    on the week's documents, and goes ahead after the week's last document.
    """
    from tests.test_revisions import generated
    customer = account()
    original = generated(customer)
    made(customer, 4)
    with pytest.raises(DomainError, match='weekly_ai_limit'):
        priced(customer)
    change = create_draft(customer, {'prompt': 'Use a friendlier tone.', 'options': {'revise_draft_id': str(original.id)}})
    quote = generation_quote(customer, change.id, change.version)
    assert quote.parameters['revision'] is True
    job, _ = submit_job(customer, quote.id, 'change-after-the-limit')
    Job.objects.filter(pk=job.pk).update(status='succeeded')
    assert ai_documents_this_week(customer) == 5, 'the edit is not counted'
    with pytest.raises(DomainError, match='weekly_ai_limit'):
        priced(customer)


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_every_limit_is_explained_in_every_language(locale):
    fallback = error_data(DomainError('invalid_request'), locale)['message']
    messages = [error_data(DomainError(code, 429), locale)['message'] for code in LIMIT_CODES]
    assert all(message and message != fallback for message in messages), 'each limit has its own words'
    assert len(set(messages)) == len(LIMIT_CODES)


# Words from the credit days: nothing is charged, estimated or kept in a balance any more.
CREDIT_WORDS = {'en': ('credit', 'balance', 'charge', 'estimate', 'quote', 'cost', 'allowance'),
                'uz': ('kredit', 'balans', 'sarf', 'hisob-kitob', 'narx', 'paket'),
                'ru': ('кредит', 'баланс', 'списан', 'стоимост', 'оценк', 'расчёт', 'пакет')}


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_no_customer_message_speaks_of_credits(locale):
    import json
    from django.conf import settings
    messages = json.loads((settings.BASE_DIR / 'i18n' / f'{locale}.json').read_text())
    left = {code: text for code, text in messages.items() if any(word in text.lower() for word in CREDIT_WORDS[locale])}
    assert not left, left


@pytest.mark.parametrize('locale,plans', [('en', 'The Free and Plus plans'), ('uz', 'Free va Plus tariflari'),
                                          ('ru', 'Тарифы Free и Plus')])
def test_the_channel_rule_does_not_tell_plus_customers_the_product_is_free(locale, plans):
    """Plus is asked to join as well, and it has paid."""
    message = error_data(DomainError('channels_required', 403), locale)['message']
    assert message.startswith(plans) and 'Premium' in message
    assert not any(word in message for word in ('is free', 'bepul', 'бесплат'))
