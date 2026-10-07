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
