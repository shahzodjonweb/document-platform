"""The admin shows every time in the zone of the computer it is opened on."""
import csv
import io
from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

import pytest
from django.http import HttpResponse
from django.test import RequestFactory
from django.utils import timezone

from apps.core.models import Account
from operations.middleware import COOKIE, DeviceTimezoneMiddleware
from operations.views import audit_changes
from tests.test_operations import staff_client

pytestmark = pytest.mark.django_db

ZONE = 'America/New_York'  # UTC-4 in October
JOINED = datetime(2026, 10, 7, 20, 30, tzinfo=dt_timezone.utc)


def zone_seen(path, cookie):
    seen = {}

    def view(request):
        seen['zone'] = str(timezone.get_current_timezone())
        return HttpResponse()
    request = RequestFactory().get(path)
    request.COOKIES[COOKIE] = cookie
    DeviceTimezoneMiddleware(view)(request)
    return seen['zone']


def device_client(role='Administrator', zone=ZONE):
    client, user = staff_client(role)
    client.cookies[COOKIE] = zone
    return client, user


def test_middleware_activates_a_real_zone_for_staff_pages_only():
    assert zone_seen('/ops/today', ZONE) == ZONE
    assert zone_seen('/ops/users/1', 'Asia/Calcutta') == 'Asia/Calcutta'
    # The JSON APIs keep their UTC defaults whatever cookie the browser holds.
    assert zone_seen('/api/v1/me', ZONE) == 'UTC'
    assert zone_seen('/ops/api/v1/summary', ZONE) == 'UTC'
    # Nothing leaks into the next request on this thread.
    assert str(timezone.get_current_timezone()) == 'UTC'


@pytest.mark.parametrize('value', ['', 'Nope/Zone', 'America', '../etc/passwd', '/etc/localtime', 'x' * 300,
                                   'Asia/Tashkent\x00', 'zone.tab'])
def test_middleware_ignores_anything_that_is_not_a_zone(value):
    assert zone_seen('/ops/today', value) == 'UTC'


def test_pages_render_times_in_the_cookie_zone():
    account = Account.objects.create(telegram_user_id=93001, display_name='Dilnoza', created_at=JOINED)
    client, _ = device_client()
    page = client.get(f'/ops/users/{account.id}?lang=en').content.decode()
    assert '07 Oct 2026 · 16:30' in page and '20:30' not in page
    assert f'data-zone="{ZONE}"' in page
    # Without the cookie the page is written in UTC (no longer a fixed Tashkent).
    client.cookies.pop(COOKIE)
    page = client.get(f'/ops/users/{account.id}?lang=en').content.decode()
    assert '07 Oct 2026 · 20:30' in page and 'data-zone="UTC"' in page


def test_report_filters_default_to_the_cookie_zone():
    client, _ = device_client()
    response = client.get('/ops/overview?lang=en')
    assert response.context['filters']['timezone'] == ZONE  # the report hands its filters back as a dict
    page = response.content.decode()
    # Their own zone is offered, chosen, marked, and not reported as a narrowing filter.
    assert f'<option value="{ZONE}" selected>{ZONE} · this computer</option>' in page
    assert f'Filters · {ZONE}' not in page
    assert f'{ZONE} · Metric definitions' in page
    # A zone picked in the filter still wins, and shows as active.
    response = client.get('/ops/overview?lang=en&timezone=UTC')
    assert response.context['filters']['timezone'] == 'UTC' and 'Filters · UTC' in response.content.decode()
    # A directory or junk in the URL is a 400, not a crash.
    assert client.get('/ops/overview?timezone=America').status_code == 400


def test_today_starts_at_midnight_on_the_viewers_computer():
    client, _ = device_client(zone='Pacific/Kiritimati')  # UTC+14: often already tomorrow
    response = client.get('/ops/today?lang=en')
    today = timezone.now().astimezone(timezone.get_fixed_timezone(14 * 60)).date()
    assert response.context['today_filters'].timezone == 'Pacific/Kiritimati'
    assert response.context['today_filters'].date_from == str(today)


def test_audit_values_and_exports_use_the_viewer_zone():
    with timezone.override(ZONE):
        rows = audit_changes({'expires_at': ''}, {'expires_at': '2026-11-06T12:00:00+00:00', 'plan': 'plus'})
    assert {row['key']: row['after'] for row in rows} == {'expires_at': '06 Nov 2026 · 07:00', 'plan': 'plus'}

    Account.objects.create(telegram_user_id=93002, created_at=JOINED)
    client, _ = device_client('Support')
    response = client.get('/ops/export/users?date_from=2026-10-01&date_to=2026-10-08')
    lines = list(csv.reader(io.StringIO(response.content.decode().lstrip('﻿'))))
    meta = {line[0]: line[1] for line in lines if len(line) == 2}
    assert meta['times_timezone'] == ZONE and meta['timezone'] == ZONE and meta['generated_at'].endswith('-04:00')
    row = next(line for line in lines if '93002' in line)
    assert row[-1] == '2026-10-07 16:30:00-04:00'


def test_a_page_answering_a_form_is_marked_so_theme_js_never_reloads_it():
    from django.test import Client
    client = Client()
    page = client.get('/ops/login?lang=en').content.decode()
    assert 'data-zone="UTC"' in page and 'data-posted' not in page
    page = client.post('/ops/login?lang=en', {'username': 'nobody', 'password': 'wrong-password'}).content.decode()
    assert 'data-posted' in page


def test_detail_pages_and_labels_name_the_viewer_zone():
    from apps.commerce.models import ManualPayment
    account = Account.objects.create(telegram_user_id=93003, display_name='Bekzod')
    transfer = ManualPayment.objects.create(account=account, plan='plus', amount=60000, currency='UZS', status='submitted',
                                            reference='PM-TZ1', submitted_at=JOINED, expires_at=JOINED)
    client, _ = device_client()
    page = client.get(f'/ops/payments/manual/{transfer.id}?lang=en').content.decode()
    # Both the record and the "check the bank around …" hint, no longer Tashkent (01:30).
    assert '07 Oct 2026 · 16:30' in page and 'around 07 Oct 16:30' in page and '01:30' not in page
    page = client.get('/ops/analytics/ai-usage?lang=en').content.decode()
    assert f'({ZONE})</th>' in page and '(UTC)' not in page


def test_today_heading_names_the_day_being_counted():
    client, _ = device_client()
    page = client.get('/ops/today?lang=en').content.decode()
    assert timezone.localtime(timezone=ZoneInfo(ZONE)).strftime('%d.%m.%Y · ') in page
    # A report zone carried in from another page moves the day, and the heading with it.
    page = client.get('/ops/today?lang=en&timezone=Pacific/Kiritimati').content.decode()
    assert timezone.now().astimezone(timezone.get_fixed_timezone(14 * 60)).strftime('%d.%m.%Y · ') in page
