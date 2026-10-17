"""Times in the bot, on the clock of the person reading them.

Telegram does not say where someone is. The web app keeps account.time_zone in
step with the device it is opened on, so that is the person's own zone; anyone
who has never opened it stays on UTC.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def account_zone(account):
    try:
        return ZoneInfo(getattr(account, 'time_zone', '') or 'UTC')
    except (KeyError, ValueError, OSError):
        return timezone.utc


def local_time(account, value):
    """An aware datetime (or ISO string) moved onto the account's clock; naive means UTC."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(account_zone(account))


def offset_label(moment):
    """'UTC', 'UTC+5', 'UTC-3:30': short, and the same in every language."""
    minutes = round(moment.utcoffset().total_seconds() / 60)
    if not minutes:
        return 'UTC'
    hours, rest = divmod(abs(minutes), 60)
    return f"UTC{'+' if minutes > 0 else '-'}{hours}" + (f':{rest:02d}' if rest else '')


def stamp(account, value, fmt='%Y-%m-%d %H:%M'):
    """A time as the person should read it, with its zone: '2026-10-07 17:30 UTC+5'."""
    moment = local_time(account, value)
    return f'{moment:{fmt}} {offset_label(moment)}'


def day_label(value, locale):
    """A calendar day as this language writes it: '31 Oct', '31-oktabr', '31 октября'.

    Spelt by apps.commerce.pricing, where the plans' dates live, so the bot,
    the admin panel and the web app write a discount's last day the same way.
    """
    from apps.commerce.pricing import day_label as spell
    return spell(value, locale)


def zone_known(account):
    """Whether the account's clock is really its owner's.

    Every account starts on UTC and only the web app moves it to the device's
    zone, so UTC (or a name that cannot be read) says nothing about where a
    Telegram-only customer is.
    """
    name = getattr(account, 'time_zone', '') or ''
    if name in ('', 'UTC'):
        return False
    try:
        ZoneInfo(name)
    except (KeyError, ValueError, OSError):
        return False
    return True


def week_reset(account, value, locale=None):
    """When the week's limits come back, as this person should read it.

    On a known clock, the moment itself ('2026-10-19 00:00 UTC+5'). Otherwise
    the rule as the owner states it, Monday 00:00 in Tashkent: the same moment
    stamped in UTC reads '2026-10-18 19:00 UTC', a Sunday evening.
    """
    from .errors import WEEK_START
    if value and zone_known(account):
        try:
            return stamp(account, value)
        except (TypeError, ValueError):
            pass
    locale = locale or getattr(account, 'locale', 'en')
    return WEEK_START.get(locale, WEEK_START['en'])
