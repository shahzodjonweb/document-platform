"""Where new people stop on their way to a first document.

193 people arrived from an ad in a day, 50 made something, and nothing said
where the rest stopped. Each step is recorded once a day per person, and the
admin shows how many reached it and the share who went on from the step before.
"""
import pytest
from django.core.cache import cache

from apps.core import funnel
from apps.core.models import AnalyticsEvent
from operations.integrations import save_config
from tests.test_bot_generation import customer, describe, tap  # noqa: F401

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]


@pytest.fixture(autouse=True)
def fresh_cache():
    cache.clear()


def steps():
    return list(AnalyticsEvent.objects.filter(channel='bot').order_by('occurred_at').values_list('event_type', flat=True))


def test_a_first_document_passes_every_step(customer):
    save_config('ai', {'mode': 'local_fixture'})
    from telegram.local import dispatch_local
    dispatch_local(customer, text='/menu')
    review = describe(customer, 'A 1 page note on tides.\n\n' + ' '.join(['tide'] * 300))
    tap(customer, review, 'Generate')
    reached = steps()
    for name in ('bot.home', 'service.chosen', 'ai.described', 'job.accepted', 'job.succeeded'):
        assert name in reached, (name, reached)
    assert AnalyticsEvent.objects.get(event_type='service.chosen').feature_id == 'ai.pdf_topic'
    # Each step once a day, however often it is passed.
    dispatch_local(customer, text='/menu')
    assert steps().count('bot.home') == 1


def test_before_an_account_a_person_is_only_a_hashed_visitor():
    funnel.step('bot.start', telegram_user_id=987654321)
    funnel.step('bot.start', telegram_user_id=987654321)
    funnel.step('bot.language', telegram_user_id=987654321)
    rows = AnalyticsEvent.objects.filter(event_type__in=('bot.start', 'bot.language'))
    assert rows.count() == 2 and all(row.account_id is None for row in rows)
    visitor = rows.first().properties['visitor']
    assert visitor == funnel.visitor(987654321) and '987654321' not in visitor


def test_the_admin_shows_how_many_reached_each_step(settings):
    from operations.analytics_extra import bot_funnel
    from operations.metrics import Filters
    for user in (1, 2, 3, 4):
        funnel.step('bot.start', telegram_user_id=user)
    for user in (1, 2, 3):
        funnel.step('bot.language', telegram_user_id=user)
    funnel.step('bot.verified', telegram_user_id=1)
    from django.utils import timezone
    from datetime import timedelta
    today = timezone.now().date()
    filters = Filters(str(today - timedelta(days=1)), str(today + timedelta(days=1)), 'UTC',
                      'development' if settings.DEBUG else 'production', '', '')
    rows = {row['event']: row for row in bot_funnel(filters)}
    assert (rows['bot.start']['count'], rows['bot.language']['count'], rows['bot.verified']['count']) == (4, 3, 1)
    assert rows['bot.language']['share'] == 75 and rows['bot.verified']['share'] == 33
    assert rows['bot.start']['label_uz'] == 'Botni ochdi'
