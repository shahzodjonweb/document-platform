"""What a plan costs today: the regular price, or the discount while it runs.

The owner types a discounted price and its last day; the last day is inclusive
and ends at midnight in Tashkent. Everything that prices a plan reads it from
one place, so these are the rules every screen shares.
"""
from datetime import date, datetime, timedelta, timezone as dt_timezone

import pytest

from apps.commerce import pricing
from apps.core.allowance import WEEK_ZONE
from operations import plans as plan_settings

pytestmark = pytest.mark.django_db
PLUS = {'price_uzs': 20_000, 'discount_price_uzs': 15_000, 'discount_until': '2026-10-31'}
TASHKENT, UTC = WEEK_ZONE, dt_timezone.utc


def test_a_discount_is_a_lower_price_with_its_percent_and_last_day():
    now = datetime(2026, 10, 20, 12, tzinfo=TASHKENT)
    assert pricing.plan_price('plus', PLUS, now) == {
        'plan': 'plus', 'regular': 20_000, 'price': 15_000,
        'discount': {'price': 15_000, 'regular': 20_000, 'percent': 25, 'until': '2026-10-31'}}
    assert pricing.plan_price('plus', {'price_uzs': 20_000}, now) == {'plan': 'plus', 'regular': 20_000, 'price': 20_000, 'discount': None}
    assert pricing.plan_price('free', {'price_uzs': None, 'discount_price_uzs': 1_000, 'discount_until': '2099-01-01'}, now) is None
    assert pricing.plan_price('plus', {'price_uzs': True}, now) is None, 'a bool is not a price'


@pytest.mark.parametrize('now,on', [
    (datetime(2026, 10, 31, 23, 59, 59, tzinfo=TASHKENT), True),
    (datetime(2026, 11, 1, 0, 0, 0, tzinfo=TASHKENT), False),
    # The same two instants written in UTC: Tashkent is five hours ahead.
    (datetime(2026, 10, 31, 18, 59, 59, tzinfo=UTC), True),
    (datetime(2026, 10, 31, 19, 0, 0, tzinfo=UTC), False),
])
def test_the_last_day_is_inclusive_and_ends_at_midnight_in_tashkent(now, on):
    offer = pricing.plan_price('plus', PLUS, now)
    assert (offer['price'], offer['discount'] is not None) == ((15_000, True) if on else (20_000, False))
    assert pricing.ends_at(date(2026, 10, 31)) == datetime(2026, 10, 31, 19, 0, tzinfo=UTC)
    assert pricing.today(datetime(2026, 10, 31, 19, 0, tzinfo=UTC)) == date(2026, 11, 1)


@pytest.mark.parametrize('bad', ['', '31/10/2026', '2026-13-01', '2026-10-31T00:00', '20261031', None, 7, ['2026-10-31']])
def test_a_last_day_that_is_not_a_date_switches_the_discount_off_without_raising(bad):
    assert pricing.parse_until(bad) is None
    offer = pricing.plan_price('plus', {**PLUS, 'discount_until': bad}, datetime(2026, 10, 20, tzinfo=UTC))
    assert offer['price'] == 20_000 and offer['discount'] is None


@pytest.mark.parametrize('lower,percent', [(15_000, 25), (19_800, 1), (19_900, None), (19_999, None), (20_000, None),
                                           (25_000, None), (0, None), (-5, None), ('15000', None), (None, None)])
def test_the_percent_is_rounded_down_and_anything_short_of_one_is_no_discount(lower, percent):
    offer = pricing.plan_price('plus', {**PLUS, 'discount_price_uzs': lower}, datetime(2026, 10, 20, tzinfo=UTC))
    assert (offer['discount'] or {}).get('percent') == percent
    assert offer['price'] == (lower if percent else 20_000)
    assert pricing.percent_off(20_000, 15_000) == 25 and pricing.percent_off(20_000, 19_900) == 0


def test_offers_read_the_panel_and_list_only_plans_on_sale():
    until = (pricing.today() + timedelta(days=14)).isoformat()
    plan_settings.save('plus', {'discount_price_uzs': 15_000, 'discount_until': until})
    plan_settings.save('premium', {'price_uzs': ''})
    offered = pricing.offers()
    assert list(offered) == ['plus'] and offered['plus']['price'] == 15_000
    assert offered['plus']['discount'] == {'price': 15_000, 'regular': 20_000, 'percent': 25, 'until': until}
    assert pricing.plan_price('plus')['price'] == 15_000, 'with no limits given, the panel is read'
    assert pricing.plan_price('premium') is None
    # Gone once the last day has passed, without anyone touching the panel.
    assert pricing.offers(datetime.combine(date.fromisoformat(until) + timedelta(days=1), datetime.min.time(), tzinfo=TASHKENT))['plus']['discount'] is None
