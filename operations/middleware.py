"""Staff pages show times in the zone of the computer they are opened on.

ops/theme.js stores the browser's zone in a cookie; a value that is not a tz
database name leaves the page in UTC.
"""
from functools import cache
from zoneinfo import ZoneInfo, available_timezones

from django.utils import timezone

COOKIE = 'ops_tz'


@cache
def _known():
    return frozenset(available_timezones())


def known_zone(name):
    """True for a tz database name such as "Asia/Tashkent", False for anything else."""
    return isinstance(name, str) and name in _known()


def viewer_zone():
    """The zone this request renders times in, as a name."""
    return str(timezone.get_current_timezone())


class DeviceTimezoneMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Staff pages only: JSON (/api/, /ops/api/) keeps its UTC defaults whoever calls it.
        page = request.path.startswith('/ops/') and not request.path.startswith('/ops/api/')
        name = request.COOKIES.get(COOKIE, '') if page else ''
        if known_zone(name):
            timezone.activate(ZoneInfo(name))
        else:
            timezone.deactivate()
        try:
            return self.get_response(request)
        finally:
            timezone.deactivate()
