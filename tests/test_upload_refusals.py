"""Files refused at upload: counted by reason, and shown beside the tools.

A refused upload blocks every file tool, and nothing measured how often it
happened. Each refusal is now kept as an 'upload.refused' event with its reason
code alone (never the file's name or contents), and the tools page in the admin
shows how many were refused, why, and what share of all uploads that is.
"""
import io
from datetime import datetime, timezone as dt_timezone

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, NameObject

from apps.core.errors import DomainError
from apps.core.models import Account, AnalyticsEvent, FileAsset
from apps.core.services import upload_file
from operations.analytics_extra import REFUSALS_SINCE, upload_refusals
from operations.i18n import CATALOGS
from operations.middleware import COOKIE as ZONE_COOKIE
from tests.test_adversarial import pdf_data, principal
from tests.test_operations import staff_client
from tests.test_plans_view_analytics import filters_for

pytestmark = pytest.mark.django_db


def opens_at_first_page():
    """A one-page PDF that asks the viewer to open it at page 1, fitted: what LibreOffice, fpdf2 and jsPDF write."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=300)
    writer._root_object[NameObject('/OpenAction')] = ArrayObject([page.indirect_reference, NameObject('/Fit')])
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def refusals(account):
    return list(AnalyticsEvent.objects.filter(account=account, event_type='upload.refused')
                .values_list('channel', 'properties'))


# ---------------------------------------------------------------- an upload refused


def test_a_refused_upload_is_kept_with_its_reason_and_nothing_of_the_file():
    account, client = principal(88001)
    response = client.post('/api/v1/files/uploads', {'file': SimpleUploadedFile('Payslip October.pdf', opens_at_first_page())})
    assert response.status_code == 400 and response.json()['error']['code'] == 'active_content_unsupported'
    assert refusals(account) == [('web', {'code': 'active_content_unsupported'})]
    event = AnalyticsEvent.objects.get(event_type='upload.refused')
    assert event.environment == 'development' and event.plan_at_event == account.plan
    assert 'Payslip' not in str(event.properties) and not FileAsset.objects.exists()


def test_every_reason_an_upload_is_refused_for_is_counted():
    account, client = principal(88002)
    client.post('/api/v1/files/uploads', {'file': SimpleUploadedFile('setup.exe', b'MZ')})
    client.post('/api/v1/files/uploads', {'file': SimpleUploadedFile('broken.pdf', b'%PDF-1.7\ncorrupt')})
    client.post('/api/v1/files/uploads', {'file': SimpleUploadedFile('notes.txt', b'plain words')})
    assert [properties['code'] for _, properties in refusals(account)] == [
        'unsupported_file', 'invalid_pdf', 'unsupported_type']


def test_a_file_longer_than_the_plan_allows_is_counted_and_still_says_the_limit():
    from operations import plans as plan_settings
    account, _ = principal(88003)
    plan_settings.save(account.plan, {'max_pages_per_job': '2'})
    with pytest.raises(DomainError) as refused:
        upload_file(account, SimpleUploadedFile('long.pdf', pdf_data(widths=(200,) * 3)))
    assert (refused.value.code, refused.value.params) == ('page_limit', {'limit': 2})
    assert refusals(account) == [('web', {'code': 'page_limit'})]


def test_the_bot_counts_its_refusals_as_the_bot():
    account, _ = principal(88004)
    with pytest.raises(DomainError):
        upload_file(account, SimpleUploadedFile('document.pdf', opens_at_first_page()), 'bot')
    assert refusals(account) == [('bot', {'code': 'active_content_unsupported'})]


def test_an_accepted_upload_is_not_a_refusal_and_a_bad_request_is_not_a_file():
    account, client = principal(88005)
    assert client.post('/api/v1/files/uploads', {'file': SimpleUploadedFile('fine.pdf', pdf_data())}).status_code == 201
    with pytest.raises(DomainError) as wrong:
        upload_file(account, SimpleUploadedFile('fine.pdf', pdf_data()), purpose='anything')
    assert wrong.value.code == 'invalid_parameters'
    uploads = AnalyticsEvent.objects.filter(account=account, event_type__startswith='upload.')
    assert list(uploads.values_list('event_type', flat=True)) == ['upload.accepted']


# ---------------------------------------------------------------- the admin shows


UTC = dt_timezone.utc


def at(day, hour=10):
    return datetime(2026, 11, day, hour, tzinfo=UTC)


def event(account, kind, when, code=None, channel='web', environment='production', locale='en'):
    return AnalyticsEvent.objects.create(account=account, event_type=kind, channel=channel, locale=locale,
                                         environment=environment, occurred_at=when,
                                         properties={'code': code} if code else {'bytes': 1000, 'pages': 1})


@pytest.fixture
def november():
    """Three people in production who uploaded in November 2026; some files were refused."""
    aziza, bekzod, dilnoza = (Account.objects.create(telegram_user_id=88100 + i, display_name=name)
                              for i, name in enumerate(('Aziza', 'Bekzod', 'Dilnoza')))
    for day in (2, 3, 4, 5, 6, 7):
        event(aziza, 'upload.accepted', at(day))
    event(bekzod, 'upload.accepted', at(8), channel='bot')
    event(aziza, 'upload.refused', at(3), 'active_content_unsupported')
    event(bekzod, 'upload.refused', at(4), 'active_content_unsupported', channel='bot', locale='uz')
    event(bekzod, 'upload.refused', at(5), 'active_content_unsupported', channel='bot', locale='uz')
    event(dilnoza, 'upload.refused', at(6), 'file_too_large')
    # A test account's refusal, which production never counts.
    tester = Account.objects.create(telegram_user_id=88199, is_test=True)
    event(tester, 'upload.refused', at(7), 'invalid_pdf', environment='development')
    return aziza, bekzod, dilnoza


def november_filters(**values):
    return filters_for(**{'date_from': '2026-11-01', 'date_to': '2026-12-01', **values})


def test_the_report_counts_refusals_by_reason_people_and_share_of_all_uploads(november):
    report = upload_refusals(november_filters(), CATALOGS['en'])
    assert (report['tried'], report['refused'], report['people'], report['share']) == (11, 4, 3, 36.4)
    assert [(row['code'], row['refusals'], row['people'], row['share']) for row in report['rows']] == [
        ('active_content_unsupported', 3, 2, 27.3), ('file_too_large', 1, 1, 9.1)]
    assert report['rows'][1]['label'] == 'Larger than the plan’s file size limit'
    assert (report['people_note'], report['tried_note']) == ('People: 3', 'Uploads tried: 11')
    assert report['since'] is None, 'the whole period is after refusals began to be kept'


def test_the_report_keeps_to_the_period_environment_channel_and_language(november):
    def counted(**values):
        report = upload_refusals(november_filters(**values), CATALOGS['en'])
        return report['refused'], report['tried']
    assert counted(date_from='2026-11-05') == (2, 6)
    assert counted(channel='bot') == (2, 3)
    assert counted(locale='uz') == (2, 2)
    development = upload_refusals(november_filters(environment='development'), CATALOGS['en'])
    assert [(row['code'], row['refusals']) for row in development['rows']] == [('invalid_pdf', 1)]


def test_uploads_from_before_refusals_were_kept_do_not_shrink_the_share(november):
    aziza = november[0]
    event(aziza, 'upload.accepted', datetime(2026, 10, 20, tzinfo=UTC))
    report = upload_refusals(filters_for(date_from='2026-10-01', date_to='2026-12-01'), CATALOGS['en'])
    assert (report['tried'], report['refused']) == (11, 4), 'the October upload came before refusals were counted'
    assert report['since'] == REFUSALS_SINCE


def test_a_reason_without_a_label_is_shown_as_its_code(november):
    event(november[0], 'upload.refused', at(9), 'archive_limit')
    rows = {row['code']: row['label'] for row in upload_refusals(november_filters(), CATALOGS['en'])['rows']}
    assert rows['archive_limit'] == ''


def test_the_report_is_a_few_queries_however_many_uploads(november, django_assert_max_num_queries):
    people = [Account.objects.create(telegram_user_id=88300 + n) for n in range(40)]
    for number, person in enumerate(people):
        event(person, 'upload.refused', at(10 + number % 10), ('invalid_pdf', 'page_limit', 'file_too_large')[number % 3])
    with django_assert_max_num_queries(4):
        report = upload_refusals(november_filters(), CATALOGS['en'])
    assert report['refused'] == 44


PAGE = '/ops/analytics/features?date_from=2026-11-01&date_to=2026-12-01'


@pytest.mark.parametrize('lang', ['en', 'uz', 'ru'])
def test_the_tools_page_shows_refused_uploads_in_each_language(november, lang):
    client, _ = staff_client()
    client.cookies[ZONE_COOKIE] = 'Asia/Tashkent'
    response = client.get(f'{PAGE}&lang={lang}')
    assert response.status_code == 200
    page = response.content.decode()
    t = CATALOGS[lang]
    for key in ('refusals', 'refusals_desc', 'refusals_count', 'refusals_share', 'refusals_reason',
                'refused_active_content_unsupported', 'refused_file_too_large'):
        assert t[key] in page, key
    assert t['refusals_people'].format(n=3) in page and '36.4%' in page
    assert 'data-code="active_content_unsupported"' in page and 'data-testid="upload-refusals"' in page
    for name in ('Aziza', 'Bekzod', 'Dilnoza'):
        assert name not in page, 'counts only, never who'


def test_the_tools_page_says_when_nothing_was_refused_and_when_counting_began(november):
    client, _ = staff_client()
    client.cookies[ZONE_COOKIE] = 'Asia/Tashkent'
    page = client.get('/ops/analytics/features?date_from=2026-10-01&date_to=2026-10-20&lang=ru').content.decode()
    assert CATALOGS['ru']['refusals_none'] in page
    assert f"{CATALOGS['ru']['refusals_since']} 28.10.2026." in page, 'midnight in Tashkent, the zone it is read in'


def test_refused_uploads_are_for_the_staff_who_see_the_tools(november):
    assert Client().get(PAGE).status_code == 302
    support, _ = staff_client('Support')
    assert support.get(PAGE).status_code == 403
    for role in ('Analyst', 'Operations'):
        client, _ = staff_client(role)
        response = client.get(PAGE)
        assert response.status_code == 200 and response.context['upload_refusals']['refused'] == 4, role
