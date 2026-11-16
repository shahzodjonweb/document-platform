"""The admin's view of the categories (architecture 10): counted, seen and watched.

Counted: the tools page shows AI documents by category (the quote's
`Job.parameters.category`), with the tools' columns, beside how often the bot's
lists had each category picked (`category.chosen`), so chosen-versus-made can
be read from the first day; the same rows export as the CSV `categories`.
Seen: an AI request keeps its category, and the list, the request page and the
customer page name it; the list filters by it. Watched: the share of each
category's documents that left a fact blank, fell back to the plain PDF page,
drew a block plain or had a slide re-laid, beside its failure rate.

Only ids, counts and codes are shown: never a request or a person's name. A
document without a category has no row, and nothing is labelled Boshqa.

The people and organisations here are invented.
"""
import csv
import io
import uuid
from datetime import datetime, timezone as dt_timezone

import pytest
from django.test import Client
from django.utils import timezone

from apps.core.models import Account, AnalyticsEvent, Artifact, FileAsset, Job, Quote
from apps.core.services import submit_job
from apps.studio import categories
from apps.studio.domain import DOCUMENT, create_draft, generation_quote
from apps.studio.models import GenerationRecord
from apps.studio.review import request_data
from operations.i18n import CATALOGS
from operations.metrics import CATEGORY_CODES, category_report
from operations.middleware import COOKIE as ZONE_COOKIE
from operations.models import AuditLog
from tests.test_category_drafts import ARIZA, DEFENCE, HIMOYA, customer, drafted, ready, switch  # noqa: F401  (fixtures)
from tests.test_operations import staff_client
from tests.test_plans_view_analytics import filters_for

pytestmark = pytest.mark.django_db

TEST = 'pdf.test'
GONE = 'pdf.eski_ariza'     # an id a later catalogue no longer holds
UTC = dt_timezone.utc
PDF, PPTX = 'application/pdf', 'application/vnd.openxmlformats-officedocument.presentationml.presentation'


def at(day, hour=10):
    return datetime(2026, 11, day, hour, tzinfo=UTC)


def made(who, feature, category=None, status='succeeded', when=None, channel='bot', warnings=(), metadata=None,
         **parameters):
    """A generation job as settle_job leaves it: the quote's parameters, its warnings, and its file's metadata."""
    quote = Quote.objects.create(account=who, feature_id=feature, expires_at=timezone.now())
    job = Job.objects.create(account=who, quote=quote, feature_id=feature, status=status, origin_channel=channel,
                             parameters={'generation_draft_id': str(uuid.uuid4()),
                                         **({'category': category} if category else {}), **parameters},
                             warnings=list(warnings), created_at=when or at(10),
                             idempotency_key=str(quote.id), request_hash='x')
    if metadata is not None:
        asset = FileAsset.objects.create(account=who, name='document', object_key=f'test/{job.id}',
                                         mime_type=PPTX if feature == 'ai.pptx' else PDF, sha256='0' * 64,
                                         size_bytes=1, page_count=1, metadata=metadata, expires_at=timezone.now())
        Artifact.objects.create(account=who, job=job, file=asset)
    return job


def chose(who, category, when=None, channel='bot', environment='production'):
    return AnalyticsEvent.objects.create(account=who, event_type=categories.CHOSEN_EVENT, channel=channel,
                                         locale=who.locale, environment=environment, occurred_at=when or at(10),
                                         properties={'category': category})


@pytest.fixture
def november():
    """Three people in production who picked categories in the bot in November 2026, and what was made."""
    aziza, bekzod, dilnoza = (Account.objects.create(telegram_user_id=89100 + i, display_name=name, locale=locale)
                              for i, (name, locale) in enumerate((('Aziza', 'uz'), ('Bekzod', 'ru'), ('Dilnoza', 'en'))))
    chose(aziza, HIMOYA, at(3)), chose(aziza, HIMOYA, at(4)), chose(bekzod, HIMOYA, at(5))
    chose(dilnoza, TEST, at(6)), chose(bekzod, ARIZA, at(7))
    # A defence deck: one re-laid a slide, one went cleanly, one failed (made on the web).
    made(aziza, 'ai.pptx', HIMOYA, metadata={'repinned': ['s3'], 'warnings': []})
    made(aziza, 'ai.pptx', HIMOYA, metadata={'repinned': [], 'warnings': []})
    made(bekzod, 'ai.pptx', HIMOYA, status='failed', channel='web')
    # A test: one left a fact blank and drew its answer key plain, one fell back to the plain page.
    made(dilnoza, 'ai.pdf_topic', TEST, warnings=['facts_blanked', {'per_command': 1}],
         metadata={'warnings': ['block_fallback:answer_key']})
    made(dilnoza, 'ai.pdf_topic', TEST, metadata={'warnings': ['template_fallback']})
    # An id the catalogue no longer holds keeps its row, named by its id.
    made(dilnoza, 'ai.pdf_topic', GONE, metadata={})
    # Counted among every AI document, never as a category: a plain one (Boshqa, the web).
    made(aziza, 'ai.pdf_topic', metadata={'warnings': ['facts_blanked']})
    # Not counted at all: a change, an outline, a CV, another month, a test account.
    made(aziza, 'ai.pptx', HIMOYA, revision=True, root_draft_id=str(uuid.uuid4()))
    made(aziza, 'ai.pptx', HIMOYA, stage='outline')
    made(aziza, 'ai.cv')
    made(aziza, 'ai.pptx', HIMOYA, when=datetime(2026, 10, 20, tzinfo=UTC))
    tester = Account.objects.create(telegram_user_id=89199, is_test=True)
    made(tester, 'ai.pptx', HIMOYA)
    chose(tester, HIMOYA, environment='development')
    return aziza, bekzod, dilnoza


def november_filters(**values):
    return filters_for(**{'date_from': '2026-11-01', 'date_to': '2026-12-01', **values})


def by_id(report):
    return {row['id']: row for row in report['rows']}


# ---------------------------------------------------------------- counted


def test_documents_are_counted_by_category_beside_how_often_each_was_picked(november):
    report = category_report(november_filters(), CATALOGS['en'])
    assert [row['id'] for row in report['rows']] == [TEST, ARIZA, HIMOYA, GONE], "the lists' order, then unknown ids"
    rows = by_id(report)
    assert {name: rows[HIMOYA][name] for name in ('chosen', 'choosers', 'attempts', 'succeeded', 'failed', 'users')} == {
        'chosen': 3, 'choosers': 2, 'attempts': 3, 'succeeded': 2, 'failed': 1, 'users': 2}
    assert (rows[TEST]['chosen'], rows[TEST]['attempts'], rows[TEST]['succeeded']) == (1, 2, 2)
    assert (rows[ARIZA]['chosen'], rows[ARIZA]['attempts'], rows[ARIZA]['failure_rate']) == (1, 0, None), \
        'picked and never made is a row too'
    assert (rows[GONE]['chosen'], rows[GONE]['attempts']) == (0, 1)
    assert (report['chosen'], report['made'], report['succeeded'], report['every'], report['share']) == (5, 6, 5, 7, 85.7)
    assert report['of_all'] == '6 of 7 AI documents in this period had a category.'


def test_labels_come_from_the_catalogue_an_unknown_id_has_none_and_nothing_is_boshqa(november):
    for lang in ('uz', 'ru', 'en'):
        rows = by_id(category_report(november_filters(), CATALOGS[lang], lang))
        assert rows[HIMOYA]['label'] == categories.get(HIMOYA).label(lang)
        assert rows[HIMOYA]['service'] == CATALOGS[lang]['categories_service_slides']
        assert rows[TEST]['service'] == CATALOGS[lang]['categories_service_pdf']
        assert (rows[GONE]['label'], rows[GONE]['service']) == ('', '')
        assert 'other' not in rows and not any('Boshqa' in row['label'] for row in rows.values())


def test_the_report_keeps_to_the_period_environment_channel_and_language(november):
    def counted(**values):
        rows = by_id(category_report(november_filters(**values), CATALOGS['en']))
        return {category: (row['chosen'], row['attempts']) for category, row in rows.items()}
    assert counted(date_from='2026-11-06') == {TEST: (1, 2), ARIZA: (1, 0), HIMOYA: (0, 3), GONE: (0, 1)}
    assert counted(channel='web') == {HIMOYA: (0, 1)}
    assert counted(locale='ru') == {ARIZA: (1, 0), HIMOYA: (1, 1)}
    assert counted(environment='development') == {HIMOYA: (1, 1)}
    assert category_report(november_filters(date_from='2026-12-01', date_to='2026-12-31'), CATALOGS['en'])['rows'] == []


def test_a_pick_recorded_without_a_category_is_shown_as_unknown_never_as_a_category(november):
    AnalyticsEvent.objects.create(account=november[0], event_type=categories.CHOSEN_EVENT, channel='bot',
                                  environment='production', occurred_at=at(8), properties={})
    rows = by_id(category_report(november_filters(), CATALOGS['en']))
    assert (rows['unknown']['chosen'], rows['unknown']['label']) == (1, '')


def test_the_report_is_a_few_queries_however_many_documents(november, django_assert_max_num_queries):
    people = [Account.objects.create(telegram_user_id=89300 + n) for n in range(30)]
    for number, person in enumerate(people):
        category = (HIMOYA, TEST, ARIZA)[number % 3]
        chose(person, category, at(10 + number % 10))
        made(person, categories.get(category).feature_id, category, metadata={'warnings': ['facts_blanked']})
    with django_assert_max_num_queries(6):
        report = category_report(november_filters(), CATALOGS['en'])
    assert (report['chosen'], report['made']) == (35, 36)


# ---------------------------------------------------------------- watched


def test_each_categorys_warnings_are_shares_of_its_finished_documents_beside_its_failure_rate(november):
    rows = by_id(category_report(november_filters(), CATALOGS['en']))
    assert {code: rows[HIMOYA][code] for code in CATEGORY_CODES} == {
        'facts_blanked': 0.0, 'template_fallback': 0.0, 'block_fallback': 0.0, 'repinned': 50.0}
    assert rows[HIMOYA]['failure_rate'] == 33.3
    assert {code: rows[TEST][code] for code in CATEGORY_CODES} == {
        'facts_blanked': 50.0, 'template_fallback': 50.0, 'block_fallback': 50.0, 'repinned': 0.0}
    assert rows[TEST]['failure_rate'] == 0.0
    assert rows[ARIZA]['shares'] == [None] * len(CATEGORY_CODES), 'nothing finished, nothing to share'
    assert rows[TEST]['shares'] == [rows[TEST][code] for code in CATEGORY_CODES]


def test_a_code_counts_wherever_the_worker_puts_it_and_once_per_document(november):
    dilnoza = november[2]
    # In the job's warnings rather than the file's, a fallback flag, and a code both places.
    made(dilnoza, 'ai.pdf_topic', ARIZA, warnings=['template_fallback', 'block_fallback:signature_row'], metadata={})
    made(dilnoza, 'ai.pdf_topic', ARIZA, metadata={'template_fallback': True})
    made(dilnoza, 'ai.pdf_topic', ARIZA, warnings=['facts_blanked'], metadata={'warnings': ['facts_blanked']})
    made(dilnoza, 'ai.pdf_topic', ARIZA)
    row = by_id(category_report(november_filters(), CATALOGS['en']))[ARIZA]
    assert (row['facts_blanked'], row['template_fallback'], row['block_fallback'], row['repinned']) == (
        25.0, 50.0, 25.0, 0.0)


# ---------------------------------------------------------------- the tools page and the CSV


PAGE = '/ops/analytics/features?date_from=2026-11-01&date_to=2026-12-01'


@pytest.mark.parametrize('lang', ['en', 'uz', 'ru'])
def test_the_tools_page_shows_documents_by_category_in_each_language(november, lang):
    client, _ = staff_client()
    client.cookies[ZONE_COOKIE] = 'Asia/Tashkent'
    response = client.get(f'{PAGE}&lang={lang}')
    assert response.status_code == 200
    page = response.content.decode()
    t = CATALOGS[lang]
    for key in ('catreport', 'catreport_desc', 'catreport_chosen', 'catreport_choosers', 'catreport_made',
                'catreport_failure', 'catreport_share_note', 'catreport_unknown', 'catreport_export',
                *(f'catreport_{code}' for code in CATEGORY_CODES), *(f'catreport_{code}_def' for code in CATEGORY_CODES)):
        assert t[key] in page, key
    assert categories.get(HIMOYA).label(lang) in page and categories.get(TEST).label(lang) in page
    assert t['catreport_of_all'].format(n=6, total=7) in page
    for category in (TEST, ARIZA, HIMOYA, GONE):
        assert f'data-category="{category}"' in page
    assert '33.3%' in page and '50.0%' in page and 'data-testid="category-report"' in page
    assert '/ops/export/categories?' in page
    for name in ('Aziza', 'Bekzod', 'Dilnoza'):
        assert name not in page, 'counts only, never who'


def test_the_tools_page_says_when_no_category_document_was_made():
    client, _ = staff_client()
    page = client.get(f'{PAGE}&lang=uz').content.decode()
    assert CATALOGS['uz']['catreport_none'] in page and 'data-category=' not in page


def test_the_rows_export_as_the_categories_csv_for_the_staff_who_see_the_tools(november):
    url = '/ops/export/categories?date_from=2026-11-01&date_to=2026-12-01&timezone=UTC'
    assert Client().get(url).status_code == 302
    support, _ = staff_client('Support')
    assert support.get(url).status_code == 403
    analyst, _ = staff_client('Analyst')
    response = analyst.get(url)
    assert response.status_code == 200 and 'docmaster-categories.csv' in response['Content-Disposition']
    lines = list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))))
    header = lines.index(['category', 'chosen', 'choosers', 'attempts', 'succeeded', 'failed', 'canceled', 'no_op',
                          'users', 'failure_rate', *CATEGORY_CODES])
    rows = {line[0]: line for line in lines[header + 1:]}
    assert list(rows) == [TEST, ARIZA, HIMOYA, GONE]
    assert rows[HIMOYA] == [HIMOYA, '3', '2', '3', '2', '1', '0', '0', '2', '33.3', '0.0', '0.0', '0.0', '50.0']
    assert rows[ARIZA][-5:] == [''] * 5, 'no rate where nothing finished'
    assert AuditLog.objects.filter(action='report.export', target='categories').exists()
    operations, _ = staff_client('Operations')
    assert operations.get(url).status_code == 200


# ---------------------------------------------------------------- seen


def test_an_ai_request_keeps_its_category_and_one_without_has_no_key(customer, switch):
    draft, _ = drafted(customer, HIMOYA, DEFENCE)
    quote = generation_quote(customer, draft.id, draft.version)
    job, _ = submit_job(customer, quote.id, f'admin-{draft.id}', 'bot')
    assert request_data(GenerationRecord.objects.get(job=job))['category'] == HIMOYA
    plain = create_draft(customer, {'feature_id': DOCUMENT, 'prompt': 'Suvning aylanishi haqida 3 betlik referat'})
    quote = generation_quote(customer, plain.id, plain.version)
    job, _ = submit_job(customer, quote.id, f'admin-{plain.id}', 'bot')
    assert 'category' not in request_data(GenerationRecord.objects.get(job=job))


def test_the_requests_list_the_request_and_the_customer_page_name_the_category_and_the_list_filters_by_it(
        customer, switch):
    draft, _ = drafted(customer, HIMOYA, DEFENCE)
    quote = generation_quote(customer, draft.id, draft.version)
    deck, _ = submit_job(customer, quote.id, f'admin-{draft.id}', 'bot')
    plain = create_draft(customer, {'feature_id': DOCUMENT, 'prompt': 'Suvning aylanishi haqida 3 betlik referat'})
    quote = generation_quote(customer, plain.id, plain.version)
    paper, _ = submit_job(customer, quote.id, f'admin-{plain.id}', 'bot')
    deck_record, paper_record = (GenerationRecord.objects.get(job=job) for job in (deck, paper))
    client, _ = staff_client('Support')
    for lang in ('uz', 'ru', 'en'):
        label = categories.get(HIMOYA).label(lang)
        listing = client.get(f'/ops/generations?lang={lang}').content.decode()
        assert label in listing and CATALOGS[lang]['gen_all_categories'] in listing
        assert listing.count('data-testid="request-category"') == 1, 'only the request with a category names one'
        assert label in client.get(f'/ops/generations/{deck_record.id}?lang={lang}').content.decode()
        assert label in client.get(f'/ops/users/{customer.id}?lang={lang}').content.decode()
    plain_page = client.get(f'/ops/generations/{paper_record.id}').content.decode()
    assert 'data-testid="request-category"' not in plain_page
    found = client.get(f'/ops/generations?category={HIMOYA}').content.decode()
    assert f'/ops/generations/{deck_record.id}' in found and f'/ops/generations/{paper_record.id}' not in found
    assert f'<option value="{HIMOYA}" selected>' in found
    nothing = client.get(f'/ops/generations?category={ARIZA}').content.decode()
    assert f'/ops/generations/{deck_record.id}' not in nothing
    # Anything that is not a category id is no filter at all.
    every = client.get('/ops/generations?category=%27%20OR%201%3D1').content.decode()
    assert f'/ops/generations/{deck_record.id}' in every and f'/ops/generations/{paper_record.id}' in every


def test_a_request_whose_category_the_catalogue_no_longer_holds_shows_its_id(customer, switch):
    draft, _ = drafted(customer, HIMOYA, DEFENCE)
    quote = generation_quote(customer, draft.id, draft.version)
    job, _ = submit_job(customer, quote.id, f'admin-{draft.id}', 'bot')
    Job.objects.filter(pk=job.pk).update(parameters={**job.parameters, 'category': GONE})
    client, _ = staff_client('Support')
    listing = client.get('/ops/generations').content.decode()
    assert GONE in listing
    assert f'/ops/generations/{GenerationRecord.objects.get(job=job).id}' in client.get(
        f'/ops/generations?category={GONE}').content.decode()
