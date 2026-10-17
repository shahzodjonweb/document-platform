"""What a paid plan costs today: its regular so'm price, or its discount while that runs.

The owner types a discounted price and the discount's last day in the admin
panel (operations.plans); nothing else is stored. Everything that shows or
charges a price reads it through `plan_price`, so the bot, the web app, the
card-transfer screens and the owner's review page can never disagree about
whether a discount is on.

A discount's last day is inclusive and ends at midnight in Asia/Tashkent, the
fixed zone the weekly limits already use: the owner announces "until 31 Oct"
and a customer paying late on 31 October in Tashkent still gets it. The
percentage is worked out from the two prices and rounded down, so what is
advertised never overstates what is taken off.
"""
from datetime import date, datetime, time, timedelta, timezone as dt_timezone

from django.utils import timezone

from apps.core.allowance import WEEK_ZONE

# Month names as a date is written in each language: '31 Oct', '31-oktabr',
# '31 октября' (the Russian genitive, as a date reads after a day number). The
# web app spells its dates from the same tables, so a discount's last day reads
# the same on every screen.
MONTHS = {
    'en': ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'),
    'uz': ('yanvar', 'fevral', 'mart', 'aprel', 'may', 'iyun', 'iyul', 'avgust', 'sentabr', 'oktabr', 'noyabr', 'dekabr'),
    'ru': ('января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'),
}


def parse_until(value):
    """The stored last day of a discount, 'YYYY-MM-DD', as a date; anything else is None.

    Never raises: a malformed override must switch the discount off, not take
    pricing down with it.
    """
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), '%Y-%m-%d').date()
    except ValueError:
        return None


def ends_at(until):
    """The instant a discount whose last day is `until` ends: 00:00 Tashkent the day after."""
    return datetime.combine(until + timedelta(days=1), time.min, tzinfo=WEEK_ZONE)


def today(now=None):
    """The calendar day in Tashkent, where the discount's last day is counted."""
    return (now or timezone.now()).astimezone(WEEK_ZONE).date()


def percent_off(regular, lower):
    """Whole per cent taken off, rounded down: 20 000 → 15 000 is 25, 20 000 → 19 900 is 0."""
    return (regular - lower) * 100 // regular


def day_label(value, locale):
    """A calendar day as this language writes it: '31 Oct', '31-oktabr', '31 октября'.

    `value` is a date, a 'YYYY-MM-DD' string (how a discount's last day is
    stored) or a datetime, which is read on the Tashkent clock the plans run
    on. The year is added only when it is not the current Tashkent year, each
    language its own way: '5 Jan 2027', '2027-yil 5-yanvar', '5 января 2027'.
    A discount that ends this month needs no year; one that runs into the
    next does. Uzbek "until" is the affix joined to the day: '31-oktabrgacha'.
    """
    if isinstance(value, datetime):
        value = (value if value.tzinfo else value.replace(tzinfo=dt_timezone.utc)).astimezone(WEEK_ZONE).date()
    elif isinstance(value, str):
        value = date.fromisoformat(value.strip()[:10])
    elif not isinstance(value, date):
        raise TypeError(f'not a day: {value!r}')
    month = MONTHS.get(locale, MONTHS['en'])[value.month - 1]
    with_year = value.year != today().year
    if locale == 'uz':
        return (f'{value.year}-yil ' if with_year else '') + f'{value.day}-{month}'
    return f'{value.day} {month}' + (f' {value.year}' if with_year else '')


def plan_price(plan, limits=None, now=None):
    """Today's price of `plan`, or None when it is not for sale.

    {'plan', 'regular', 'price', 'discount'}: `price` is what the customer pays
    today; `discount` is None, or {'price', 'regular', 'percent', 'until'} while
    one runs. The discount counts only when the stored values make sense as
    one: a whole-so'm price above zero and below the regular price, a last day
    that parses and has not passed, and at least one per cent off. Anything
    else is ignored rather than refused, since a stored value can predate the
    rule that would refuse it, and "−0%" must never render.
    """
    from apps.core.policy import limits_for_plan
    limits = limits_for_plan(plan) if limits is None else limits
    regular = limits.get('price_uzs')
    # Not `isinstance`: True would pass as 1.
    if type(regular) is not int or regular <= 0:
        return None
    offer = {'plan': plan, 'regular': regular, 'price': regular, 'discount': None}
    lower = limits.get('discount_price_uzs')
    until = parse_until(limits.get('discount_until'))
    if (type(lower) is int and 0 < lower < regular and until is not None
            and (now or timezone.now()) < ends_at(until) and percent_off(regular, lower) >= 1):
        offer['price'] = lower
        offer['discount'] = {'price': lower, 'regular': regular, 'percent': percent_off(regular, lower),
                             'until': until.isoformat()}
    return offer


def offers(now=None):
    """{plan: plan_price(plan)} for every paid plan on sale."""
    from .manual import PLANS
    priced = {}
    for plan in PLANS:
        offer = plan_price(plan, now=now)
        if offer:
            priced[plan] = offer
    return priced
