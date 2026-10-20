"""A CV made from the customer's LinkedIn profile or old CV, not only from one message.

The customer chooses first how the CV is made (`options.cv_source`): 'text'
is the one message it always was; 'linkedin' is the profile saved with
LinkedIn's own "Save to PDF", or screenshots of it; 'file' is an old CV as a
PDF, a Word file, photos or a scan. These tests make each kind of file here
(ReportLab, python-docx, pypdfium2) and follow it from the bounded reader to
the delivered CV with the model mocked: the columns a sidebar is read in, the
name at the top, the contacts the fact check keeps because the file gives
them, the refusals, and a change made after the files are gone. Everyone in
them is fictional (example.com, example.org and example.net contacts).
"""
import copy
import functools
import io
import json
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.core.errors import DomainError, error_data
from apps.studio import extraction, language, provider
from apps.studio.cv import content as cv_content, templates as cv_templates
from apps.studio.domain import CV, DOCUMENT, create_draft, generation_quote, unpack, update_draft
from processors.advanced import tesseract_runtime
from telegram.errors import COPY
from tests.test_cv_content import customer, made, reply, sent  # noqa: F401  (customer is a fixture)
from tests.test_platform import account, login_client
from tests.test_provider_contract import CONFIG, cv_draft

NEW_CODES = ('cv_file_required', 'cv_file_unreadable', 'cv_file_kind', 'cv_linkedin_link')
needs_tesseract = pytest.mark.skipif(not tesseract_runtime()['available'], reason='tesseract is not installed')


# --- The files ------------------------------------------------------------------------------

def _pdf(draw, pages=1, size=None):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    raw = io.BytesIO()
    page = canvas.Canvas(raw, pagesize=size or A4)
    for number in range(pages):
        draw(page, number)
        page.showPage()
    page.save()
    return raw.getvalue()


def _lines(page, x, y, lines, colour=(0.1, 0.1, 0.1)):
    page.setFillColorRGB(*colour)
    for font, size, text, gap in lines:
        page.setFont(font, size)
        page.drawString(x, y, text)
        y -= gap


@functools.lru_cache(maxsize=None)
def linkedin_pdf():
    """A LinkedIn "Save to PDF" export as it is laid out: a grey left column, the main column, a footer on each page."""
    from reportlab.lib.pagesizes import letter

    def draw(page, number):
        width, height = letter
        if number == 0:
            page.setFillColorRGB(0.95, 0.95, 0.95)
            page.rect(0, 0, 200, height, stroke=0, fill=1)
            _lines(page, 28, 740, [
                ('Helvetica-Bold', 13, 'Contact', 20), ('Helvetica', 10, '+998 90 123 45 67 (Mobile)', 13),
                ('Helvetica', 10, 'dilnoza.karimova@example.com', 13),
                # The narrow column breaks the profile's address after a hyphen, as LinkedIn's does.
                ('Helvetica', 10, 'www.linkedin.com/in/dilnoza-', 13), ('Helvetica', 10, 'karimova-a1b2c3 (LinkedIn)', 26),
                ('Helvetica-Bold', 13, 'Top Skills', 20), ('Helvetica', 10, 'SQL', 13), ('Helvetica', 10, 'Power BI', 13),
                ('Helvetica', 10, 'Demand Forecasting', 26), ('Helvetica-Bold', 13, 'Languages', 20),
                ('Helvetica', 10, 'Uzbek (Native or Bilingual)', 13),
                ('Helvetica', 10, 'English (Professional Working)', 26), ('Helvetica-Bold', 13, 'Certifications', 20),
                ('Helvetica', 10, 'Google Data Analytics Certificate', 13)])
            _lines(page, 222, 735, [
                ('Helvetica', 26, 'Dilnoza Karimova', 22), ('Helvetica', 12, 'Senior Data Analyst at Example Retail', 16),
                ('Helvetica', 10, 'Tashkent, Uzbekistan', 30), ('Helvetica', 16, 'Summary', 20),
                ('Helvetica', 11, 'Data analyst with five years in retail and banking analytics.', 30),
                ('Helvetica', 16, 'Experience', 22), ('Helvetica-Bold', 12, 'Example Retail', 15),
                ('Helvetica', 11, 'Senior Data Analyst', 14),
                ('Helvetica', 10, 'March 2022 - Present (2 years 8 months)', 14),
                ('Helvetica', 10, 'Tashkent, Uzbekistan', 14),
                ('Helvetica', 11, 'Built weekly sales dashboards in Power BI for 40 stores.', 26),
                ('Helvetica-Bold', 12, 'Sample Bank', 15), ('Helvetica', 11, 'Data Analyst', 14),
                ('Helvetica', 10, 'July 2019 - February 2022 (2 years 8 months)', 14),
                ('Helvetica', 11, 'Wrote credit risk reports in SQL.', 14)])
        else:
            _lines(page, 222, 735, [
                ('Helvetica', 16, 'Education', 22), ('Helvetica-Bold', 12, 'National University of Uzbekistan', 15),
                ('Helvetica', 11, "Bachelor's degree, Applied Mathematics (2015 - 2019)", 14)])
        page.setFont('Helvetica', 9)
        page.setFillColorRGB(0.5, 0.5, 0.5)
        page.drawCentredString(400, 30, f'Page {number + 1} of 2')
    return _pdf(draw, 2, letter)


@functools.lru_cache(maxsize=None)
def one_column_pdf():
    """An old CV in one column, each role's dates set to the right of its line."""
    def draw(page, _):
        _lines(page, 60, 790, [('Helvetica-Bold', 20, 'Timur Rakhimov', 22),
                               ('Helvetica', 10, 'Mechanical engineer · Samarkand · +998 91 765 43 21 · '
                                                 'timur.rakhimov@example.org', 30)])
        y = 738
        for heading, rows in (('Experience', (('Lead engineer, Example Motors', '04.2020 - present'),
                                              ('Design engineer, Sample Works', '09.2016 - 03.2020'))),
                              ('Education', (('MSc Mechanical Engineering, Example Technical University',
                                              '2014 - 2016'),))):
            page.setFont('Helvetica-Bold', 13)
            page.drawString(60, y, heading)
            y -= 18
            for role, dates in rows:
                page.setFont('Helvetica-Bold', 10.5)
                page.drawString(60, y, role)
                page.setFont('Helvetica', 10)
                page.drawRightString(535, y, dates)
                page.drawString(70, y - 14, 'Led a team of four on gearbox redesign.')
                y -= 34
    return _pdf(draw)


@functools.lru_cache(maxsize=None)
def sidebar_pdf():
    """An old CV with a dark sidebar (contact, skills, languages) beside the main column."""
    def draw(page, _):
        from reportlab.lib.pagesizes import A4
        page.setFillColorRGB(0.15, 0.25, 0.4)
        page.rect(0, 0, 185, A4[1], stroke=0, fill=1)
        _lines(page, 22, 780, [
            ('Helvetica-Bold', 12, 'CONTACT', 18), ('Helvetica', 9, '+998 93 222 11 00', 12),
            ('Helvetica', 9, 'malika.yusupova@example.net', 12), ('Helvetica', 9, 'Bukhara, Uzbekistan', 24),
            ('Helvetica-Bold', 12, 'SKILLS', 18), ('Helvetica', 9, 'Adobe Illustrator', 12), ('Helvetica', 9, 'Figma', 12),
            ('Helvetica', 9, 'Brand identity', 24), ('Helvetica-Bold', 12, 'LANGUAGES', 18),
            ('Helvetica', 9, 'Uzbek - native', 12), ('Helvetica', 9, 'Russian - fluent', 12)], colour=(1, 1, 1))
        _lines(page, 210, 770, [
            ('Helvetica-Bold', 24, 'Malika Yusupova', 26), ('Helvetica', 12, 'Graphic designer', 34),
            ('Helvetica-Bold', 13, 'Experience', 19),
            ('Helvetica-Bold', 10.5, 'Senior designer, Example Studio (2021 - 2024)', 15),
            ('Helvetica', 10, 'Designed packaging for twelve product lines.', 15),
            ('Helvetica', 10, 'Mentored two junior designers.', 26), ('Helvetica-Bold', 13, 'Education', 19),
            ('Helvetica-Bold', 10.5, 'BA Graphic Design, Example Art Institute (2017 - 2021)', 15)])
    return _pdf(draw)


@functools.lru_cache(maxsize=None)
def docx_cv():
    """An old CV in Word: the name in large type, a line of contacts, the roles in a table."""
    from docx import Document
    from docx.shared import Pt
    document = Document()
    run = document.add_paragraph().add_run('Javlon Ergashev')
    run.font.size, run.bold = Pt(22), True
    document.add_paragraph('Accountant · Namangan · javlon.ergashev@example.com · +998 94 555 66 77')
    document.add_paragraph('Experience')
    table = document.add_table(rows=2, cols=3)
    for row, cells in zip(table.rows, (('2019 - 2024', 'Chief accountant', 'Example Trade LLC'),
                                       ('2015 - 2019', 'Accountant', 'Sample Foods'))):
        for cell, text in zip(row.cells, cells):
            cell.text = text
    document.add_paragraph('Skills: 1C, Excel, IFRS reporting')
    raw = io.BytesIO()
    document.save(raw)
    return raw.getvalue()


def picture(pdf, scale=2.0, fmt='PNG'):
    """The first page of `pdf` as an image, as a phone photographs or screenshots it."""
    import pypdfium2 as pdfium
    document = pdfium.PdfDocument(pdf)
    page = document[0]
    bitmap = page.render(scale=scale)
    image = bitmap.to_pil().convert('RGB')
    raw = io.BytesIO()
    image.save(raw, fmt)
    bitmap.close()
    page.close()
    document.close()
    return raw.getvalue()


@functools.lru_cache(maxsize=None)
def scanned_pdf():
    """The one-column CV printed and scanned: a PDF of one picture and no text."""
    from reportlab.lib.utils import ImageReader

    def draw(page, _):
        from reportlab.lib.pagesizes import A4
        page.drawImage(ImageReader(io.BytesIO(picture(one_column_pdf()))), 0, 0, *A4)
    return _pdf(draw)


@functools.lru_cache(maxsize=None)
def blank_pdf():
    return _pdf(lambda page, _: None)


@functools.lru_cache(maxsize=None)
def encrypted_pdf():
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter()
    for page in PdfReader(io.BytesIO(one_column_pdf())).pages:
        writer.add_page(page)
    writer.encrypt('fictional-password')
    raw = io.BytesIO()
    writer.write(raw)
    return raw.getvalue()


def uploaded(owner, name, raw, password=None):
    """`raw` uploaded as the customer uploads a file."""
    from apps.core.services import upload_file
    return upload_file(owner, SimpleUploadedFile(name, raw), password=password)


def stored_docx(owner, raw, name='old-cv.docx'):
    """A Word file as an upload stores it. Its page count comes from LibreOffice, which tests may not have."""
    import hashlib
    import uuid
    from apps.core import storage
    from apps.core.models import FileAsset
    from apps.core.services import storage_path
    from processors.engine import inspect_file
    key = f'inputs/{owner.id}/{uuid.uuid4().hex}.docx'
    path = storage_path(key)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_bytes(raw)
    metadata = {**inspect_file(path, office_preflight=False), 'page_count': 1}
    asset = FileAsset.objects.create(account=owner, name=name, object_key=key, mime_type=metadata['mime_type'],
                                     sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw), page_count=1,
                                     metadata=metadata, expires_at=timezone.now() + timedelta(hours=24))
    storage.save(key, metadata['mime_type'])
    return asset


def read(raw, kind, suffix):
    """What the bounded reader makes of `raw`."""
    from django.conf import settings
    folder = settings.PRIVATE_STORAGE_ROOT / 'test-cv-sources'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'source{suffix}'
    path.write_bytes(raw)
    return extraction.read_cv(path, kind, ocr_pages=10, seconds=60)


def fact_check_kept(content, trusted):
    """The labels of the profile's contacts the fact check keeps."""
    checked, _ = cv_content.fact_check(content, trusted)
    return [item['label'] for item in checked['sections'][0]['items']]


def lines_of(text):
    return [line for line in text.split('\n') if line.strip()]


# --- Reading the files ------------------------------------------------------------------------

def test_a_linkedin_export_is_read_column_by_column_never_line_by_line():
    import pdfplumber
    # Read line by line across the page, the sidebar and the main column run together.
    with pdfplumber.open(io.BytesIO(linkedin_pdf())) as pdf:
        plain = pdf.pages[0].extract_text()
    assert any(line.startswith(('www.linkedin.com', 'Power BI', 'Uzbek (Native', 'English (Professional'))
               and any(word in line for word in ('Tashkent', 'Experience', 'March 2022', 'Summary'))
               for line in plain.split('\n'))
    result = read(linkedin_pdf(), 'pdf', '.pdf')
    first, second = result['pages']
    lines = lines_of(first['text'])
    sidebar = lines[:lines.index('Google Data Analytics Certificate') + 1]
    main = lines[len(sidebar):]
    assert sidebar[0] == 'Contact' and 'Top Skills' in sidebar and 'English (Professional Working)' in sidebar
    assert main[:3] == ['Dilnoza Karimova', 'Senior Data Analyst at Example Retail', 'Tashkent, Uzbekistan']
    assert main.index('Summary') < main.index('Experience') < main.index('Sample Bank')
    assert 'March 2022 - Present (2 years 8 months)' in main
    # Not a word of the main column on a sidebar line, nor the other way round.
    assert not any(word in line for line in sidebar for word in ('Summary', 'Experience', 'Example Retail'))
    assert not any(word in line for line in main for word in ('Top Skills', 'Contact', 'Demand Forecasting',
                                                              'Certifications'))
    # The page footers are LinkedIn's, not the person's; OCR read nothing.
    assert 'Page 1 of 2' not in first['text'] and 'Page 2 of 2' not in second['text']
    assert 'National University of Uzbekistan' in second['text']
    assert not any(page.get('ocr') for page in result['pages']) and result['ocr_pages'] == 0
    # The largest line at the top of the first page: the person's name.
    assert result['names'][0] == 'Dilnoza Karimova'


def test_a_sidebar_stays_whole_and_a_roles_dates_stay_beside_it():
    sidebar = lines_of(read(sidebar_pdf(), 'pdf', '.pdf')['pages'][0]['text'])
    assert sidebar[:4] == ['CONTACT', '+998 93 222 11 00', 'malika.yusupova@example.net', 'Bukhara, Uzbekistan']
    assert sidebar.index('Russian - fluent') + 1 == sidebar.index('Malika Yusupova')
    # A role's dates on the right of its line leave a gap too, but they are part of the line.
    one = read(one_column_pdf(), 'pdf', '.pdf')
    text = one['pages'][0]['text']
    assert 'Lead engineer, Example Motors 04.2020 - present' in text
    assert 'Design engineer, Sample Works 09.2016 - 03.2020' in text
    assert one['names'][0] == 'Timur Rakhimov'


def test_a_word_cv_is_read_in_order_with_its_table():
    result = read(docx_cv(), 'docx', '.docx')
    lines = lines_of(result['pages'][0]['text'])
    assert lines[0] == 'Javlon Ergashev' and lines[2] == 'Experience'
    assert lines[3:5] == ['2019 - 2024 | Chief accountant | Example Trade LLC', '2015 - 2019 | Accountant | Sample Foods']
    assert lines[-1] == 'Skills: 1C, Excel, IFRS reporting'
    assert result['names'] == ['Javlon Ergashev']


def test_a_file_the_reader_cannot_parse_is_a_failure_with_nothing_of_the_file_in_it():
    with pytest.raises(DomainError) as failed:
        read(b'%PDF-1.7 not really a pdf', 'docx', '.docx')
    assert failed.value.code == 'source_extraction_failed' and not failed.value.params


def test_a_reader_that_runs_over_its_time_is_killed_with_everything_it_started(tmp_path, monkeypatch):
    import os
    import time
    started = tmp_path / 'started'
    stuck = tmp_path / 'stuck.py'
    stuck.write_text('import subprocess, sys, time\n'
                     f'child = subprocess.Popen(["sleep", "60"])\nopen({str(started)!r}, "w").write(str(child.pid))\n'
                     'time.sleep(60)\n')
    monkeypatch.setattr(extraction, 'CV_READER', stuck)
    monkeypatch.setattr(extraction, 'CV_GRACE_SECONDS', 0)
    begun = time.monotonic()
    with pytest.raises(DomainError, match='source_extraction_failed'):
        extraction.read_cv(tmp_path / 'any.pdf', 'pdf', ocr_pages=0, seconds=1)
    assert time.monotonic() - begun < 15
    grandchild = int(started.read_text())
    for _ in range(40):
        try:
            os.kill(grandchild, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail('what the reader started outlived it')


@needs_tesseract
def test_a_photo_and_a_scan_are_read_by_ocr():
    photo = read(picture(sidebar_pdf()), 'image', '.png')
    page = photo['pages'][0]
    assert page['ocr'] is True and photo['ocr_pages'] == 1
    for given in ('Malika Yusupova', 'malika.yusupova@example.net', '+998 93 222 11 00', 'Example Studio'):
        assert given in page['text'], given
    assert photo['names'][0] == 'Malika Yusupova'
    # A LinkedIn profile photographed: what OCR read is trusted like the export's text.
    shot = read(picture(linkedin_pdf(), 3.0, 'JPEG'), 'image', '.jpg')
    assert shot['pages'][0]['ocr'] is True and shot['names'][0] == 'Dilnoza Karimova'
    written = cv_content.seed('Dilnoza Karimova')
    written['sections'][0]['items'] = [{'label': 'email', 'text': 'dilnoza.karimova@example.com', 'value': ''},
                                       {'label': 'linkedin', 'text': 'linkedin.com/in/dilnoza-karimova-a1b2c3',
                                        'value': ''}]
    trusted = cv_content.trusted_text({'excerpts': [{'asset_id': 'a1', **shot['pages'][0]}]})
    assert fact_check_kept(written, trusted) == ['email', 'linkedin']
    scan = read(scanned_pdf(), 'pdf', '.pdf')
    assert scan['pages'][0]['ocr'] is True
    for given in ('Timur Rakhimov', 'timur.rakhimov@example.org', '+998 91 765 43 21', '04.2020'):
        assert given in scan['pages'][0]['text'], given
    assert scan['names'][0] == 'Timur Rakhimov'
    # OCR is held to the pages it is allowed: none left, nothing is read.
    from django.conf import settings
    path = settings.PRIVATE_STORAGE_ROOT / 'test-cv-sources' / 'scan.pdf'
    path.write_bytes(scanned_pdf())
    held = extraction.read_cv(path, 'pdf', ocr_pages=0, seconds=30)
    assert held['ocr_pages'] == 0 and held['ocr_skipped'] == 1 and not held['pages'][0]['text']


# --- The mode, the files it takes, and its refusals ----------------------------------------------

@pytest.mark.django_db
def test_each_mode_takes_its_own_files_and_says_what_is_wrong(customer):
    def refused(data):
        with pytest.raises(DomainError) as error:
            create_draft(customer, {'feature_id': CV, **data})
        return error.value.code
    pdf = uploaded(customer, 'old-cv.pdf', one_column_pdf())
    word = stored_docx(customer, docx_cv())
    webp = uploaded(customer, 'old-cv.webp', picture(one_column_pdf(), 1.0, 'WEBP'))
    link = 'https://www.linkedin.com/in/dilnoza-karimova-a1b2c3'
    assert refused({'prompt': 'Timur Rakhimov', 'options': {'cv_source': 'resume'}}) == 'invalid_parameters'
    # One message takes no file, as before.
    assert refused({'prompt': 'Timur Rakhimov, engineer', 'source_ids': [str(pdf.id)]}) == 'invalid_parameters'
    assert refused({'prompt': 'Timur Rakhimov, engineer', 'source_ids': [str(pdf.id)],
                    'options': {'cv_source': 'text'}}) == 'invalid_parameters'
    # A file is the point of the other two.
    assert refused({'prompt': 'I want a job as a lead engineer', 'options': {'cv_source': 'file'}}) == 'cv_file_required'
    assert refused({'options': {'cv_source': 'linkedin'}}) == 'cv_file_required'
    # A LinkedIn link is never opened: in any mode, alone, it is answered with the Save to PDF steps.
    assert refused({'prompt': link}) == 'cv_linkedin_link'
    assert refused({'prompt': f'Make my CV from my LinkedIn: {link}', 'options': {'cv_source': 'linkedin'}}) == \
        'cv_linkedin_link'
    assert refused({'prompt': 'linkedin.com/in/dilnoza-k', 'options': {'cv_source': 'file'}}) == 'cv_linkedin_link'
    # Beside a CV's worth of facts it is only a contact detail.
    full = create_draft(customer, {'feature_id': CV, 'prompt': (
        'Dilnoza Karimova, data analyst in Tashkent, ' + link + '. Senior data analyst at Example Retail since '
        '03.2022, data analyst at Sample Bank 2019 - 2022. SQL, Python, Power BI.')})
    assert unpack(full.encrypted_data)['title'] == 'Dilnoza Karimova'
    # A LinkedIn profile is its PDF or screenshots, never a Word file; WEBP is neither mode's.
    assert refused({'source_ids': [str(word.id)], 'options': {'cv_source': 'linkedin'}}) == 'cv_file_kind'
    assert refused({'source_ids': [str(webp.id)], 'options': {'cv_source': 'file'}}) == 'cv_file_kind'
    made_from_word = create_draft(customer, {'feature_id': CV, 'source_ids': [str(word.id)],
                                             'options': {'cv_source': 'file'}})
    assert unpack(made_from_word.encrypted_data)['title'] == 'Javlon Ergashev'
    # Ten files at most, and only the customer's own.
    many = [str(uploaded(customer, f'page-{number}.pdf', one_column_pdf()).id) for number in range(11)]
    assert refused({'source_ids': many, 'options': {'cv_source': 'file'}}) == 'generation_limit'
    stranger = uploaded(account(77), 'theirs.pdf', one_column_pdf())
    assert refused({'source_ids': [str(stranger.id)], 'options': {'cv_source': 'file'}}) == 'file_unavailable'
    # Only a CV has a source mode.
    with pytest.raises(DomainError, match='invalid_parameters'):
        create_draft(customer, {'feature_id': DOCUMENT, 'prompt': 'The water cycle', 'options': {'cv_source': 'file'}})


@pytest.mark.django_db
def test_a_blank_or_protected_pdf_is_unreadable(customer):
    for upload in (uploaded(customer, 'blank.pdf', blank_pdf()),
                   uploaded(customer, 'locked.pdf', encrypted_pdf(), password='fictional-password')):
        with pytest.raises(DomainError) as refused:
            create_draft(customer, {'feature_id': CV, 'prompt': 'Timur Rakhimov', 'source_ids': [str(upload.id)],
                                    'options': {'cv_source': 'file'}})
        assert refused.value.code == 'cv_file_unreadable' and refused.value.status == 400


@pytest.mark.django_db
def test_every_new_refusal_is_said_in_every_language(settings, customer):
    from telegram.errors import bot_error
    response = login_client(customer).post('/api/v1/generation/drafts', data=json.dumps(
        {'feature_id': CV, 'prompt': 'https://linkedin.com/in/dilnoza-karimova'}), content_type='application/json')
    assert response.status_code == 400 and response.json()['error']['code'] == 'cv_linkedin_link'
    assert response.json()['error']['message'] == error_data(DomainError('cv_linkedin_link'), customer.locale)['message']
    fallback = {locale: error_data(DomainError('invalid_request'), locale)['message'] for locale in ('en', 'uz', 'ru')}
    for code in NEW_CODES:
        for locale in ('en', 'uz', 'ru'):
            message = error_data(DomainError(code), locale)['message']
            assert message and message != fallback[locale], (code, locale)
            assert bot_error(DomainError(code), locale) == COPY[locale][code] and len(COPY[locale][code]) < 260
            if locale == 'uz':
                # Latin only, with the house o‘ and g‘ and the tutuq.
                assert not any('Ѐ' <= char <= 'ӿ' for char in message + COPY[locale][code]), code
                assert "'" not in message and '’' not in message, code
            if locale == 'ru':
                assert 'AI' not in message and 'AI' not in COPY[locale][code]
    for locale, steps in (('en', 'Save to PDF'), ('uz', 'Save to PDF'), ('ru', 'Сохранить в формате PDF')):
        assert steps in error_data(DomainError('cv_linkedin_link'), locale)['message']
        assert steps in COPY[locale]['cv_linkedin_link']


@pytest.mark.django_db
def test_the_studio_says_how_a_cv_can_be_made(settings):
    settings.DEBUG = True
    features = {f['id']: f for f in login_client(account()).get('/api/v1/studio/config').json()['features']}
    cv = features[CV]
    assert cv['source_modes'] == ['text', 'linkedin', 'file']
    assert cv['source_kinds'] == {'linkedin': ['pdf', 'image'], 'file': ['pdf', 'docx', 'image']}
    assert cv['max_source_files'] == 10
    assert not {'source_modes', 'source_kinds', 'max_source_files'} & set(features[DOCUMENT])


# --- The name, the facts and the request ------------------------------------------------------------

@pytest.mark.parametrize('hint,name', [
    ('Dilnoza Karimova', 'Dilnoza Karimova'), ('DILNOZA KARIMOVA', 'Dilnoza Karimova'),
    ('O‘TKIR KAMOLOV', 'O‘tkir Kamolov'), ('Kamolov Farrux Shavkat o‘g‘li', 'Kamolov Farrux Shavkat o‘g‘li'),
    ('Top Skills', ''), ('Curriculum Vitae', ''), ('Tashkent Uzbekistan', ''), ('Summary', ''),
    ('Senior Data Analyst', ''), ('Page 1 of 2', ''), ('Dilnoza', ''),
])
def test_the_largest_line_is_the_name_only_when_it_reads_as_one(hint, name):
    assert cv_content.hinted(hint) == name


@pytest.mark.django_db
def test_the_name_comes_from_the_file_and_without_one_the_customer_is_asked(customer):
    profile = uploaded(customer, 'Profile.pdf', linkedin_pdf())
    draft = create_draft(customer, {'feature_id': CV, 'prompt': 'I want a job as a lead data analyst',
                                    'source_ids': [str(profile.id)], 'options': {'cv_source': 'linkedin'}})
    data = unpack(draft.encrypted_data)
    assert data['title'] == data['content']['title'] == 'Dilnoza Karimova'
    assert data['options']['cv_source'] == 'linkedin' and data['source_ids'] == [str(profile.id)]
    assert [(e['page'], e['asset_id']) for e in data['excerpts']] == [(1, str(profile.id)), (2, str(profile.id))]
    assert data['excerpts'][0]['names'][0] == 'Dilnoza Karimova' and 'names' not in data['excerpts'][1]
    # The notes may be left out: the file is the CV.
    alone = unpack(create_draft(customer, {'feature_id': CV, 'source_ids': [str(profile.id)],
                                           'options': {'cv_source': 'linkedin'}}).encrypted_data)
    assert alone['prompt'] == '' and alone['title'] == 'Dilnoza Karimova'
    # The GET of a draft says how it is made and from which files.
    shown = login_client(customer).get(f'/api/v1/generation/drafts/{draft.id}').json()
    assert shown['options']['cv_source'] == 'linkedin' and shown['source_ids'] == [str(profile.id)]
    # A file that names nobody, with notes that do not either, is asked for the name.
    nameless = uploaded(customer, 'nameless.pdf', _pdf(lambda page, _: _lines(page, 60, 780, [
        ('Helvetica', 11, 'Experience: accountant at Example Trade LLC, 2019 - 2024.', 16),
        ('Helvetica', 11, 'Skills: 1C, Excel, IFRS reporting, payroll, tax returns.', 16)])))
    with pytest.raises(DomainError, match='cv_name_required'):
        create_draft(customer, {'feature_id': CV, 'prompt': 'make it shorter', 'source_ids': [str(nameless.id)],
                                'options': {'cv_source': 'file'}})
    named = create_draft(customer, {'feature_id': CV, 'prompt': 'Ismim Javlon Ergashev',
                                    'source_ids': [str(nameless.id)], 'options': {'cv_source': 'file'}})
    assert unpack(named.encrypted_data)['title'] == 'Javlon Ergashev'


@pytest.mark.parametrize('excerpts,name', [
    # A name with what LinkedIn may print after it, in the largest type.
    ([{'text': 'Contact\nPower BI', 'names': ['Dilnoza Karimova (She/Her)', 'Summary']}], 'Dilnoza Karimova'),
    # No line stands out: a name the file labels, or the line it starts with.
    ([{'text': 'Curriculum vitae\nF.I.Sh.: Kamolov Farrux Shavkat o‘g‘li\nTel: +998 90 000 00 00'}],
     'Kamolov Farrux Shavkat o‘g‘li'),
    ([{'text': 'Timur Rakhimov\nMechanical engineer, Samarkand'}], 'Timur Rakhimov'),
    # A sidebar's skills and products are no one's name.
    ([{'text': 'CONTACT\n+998 93 222 11 00\nSKILLS\nAdobe Illustrator\nDemand Forecasting\nPower BI'}], ''),
])
def test_the_name_is_read_from_a_file_where_it_stands_never_from_its_skills(excerpts, name):
    payload = {'prompt': 'For a job in Dubai', 'source_text': '', 'title': 'Untitled document',
               'content': cv_content.seed('Untitled document'),
               'excerpts': [{'asset_id': 'a1', 'page': 1, **excerpt} for excerpt in excerpts]}
    if not name:
        with pytest.raises(DomainError, match='cv_name_required'):
            cv_content.require_name({}, CV, payload)
        return
    cv_content.require_name({}, CV, payload)
    assert payload['title'] == payload['content']['title'] == name


def test_contacts_and_dates_the_file_gives_survive_the_fact_check():
    pages = read(linkedin_pdf(), 'pdf', '.pdf')['pages']
    data = {'prompt': 'I want a job as a lead data analyst', 'source_text': '',
            'excerpts': [{'asset_id': 'a1', **page} for page in pages]}
    written = cv_content.seed('Dilnoza Karimova')
    written['sections'][0]['items'] = [
        {'label': 'phone', 'text': '+998 90 123 45 67', 'value': ''},
        {'label': 'email', 'text': 'dilnoza.karimova@example.com', 'value': ''},
        # Put back on one line, as the model writes it.
        {'label': 'linkedin', 'text': 'linkedin.com/in/dilnoza-karimova-a1b2c3', 'value': ''},
        {'label': 'website', 'text': 'dilnoza.example.dev', 'value': ''}]
    written['sections'][1]['items'] = [{'label': 'Senior data analyst', 'text': 'Example Retail',
                                        'value': '03.2022 – present'},
                                       {'label': 'Data analyst', 'text': 'Sample Bank', 'value': '07.2019 – 02.2022'},
                                       {'label': 'Analyst', 'text': 'Invented Ltd', 'value': '2011 – 2013'}]
    checked, dropped = cv_content.fact_check(written, cv_content.trusted_text(data))
    assert [item['label'] for item in checked['sections'][0]['items']] == ['phone', 'email', 'linkedin']
    assert [item['value'] for item in checked['sections'][1]['items']] == ['03.2022 – present', '07.2019 – 02.2022', '']
    assert dropped == ['contact:website', 'dates:experience']
    # Without the file nothing of it is trusted.
    bare, _ = cv_content.fact_check(written, cv_content.trusted_text({**data, 'excerpts': []}))
    assert bare['sections'][0]['items'] == []


def test_an_address_ocr_read_with_a_space_in_it_is_still_the_customers():
    written = cv_content.seed('Dilnoza Karimova')
    written['sections'][0]['items'] = [{'label': 'linkedin', 'text': 'linkedin.com/in/dilnoza-karimova-a1b2c3',
                                        'value': ''},
                                       {'label': 'email', 'text': 'dilnoza.karimova@example.com', 'value': ''}]
    page = {'asset_id': 'a1', 'page': 1, 'text': 'www .linkedin.com/in/dilnoza-\nkarimova-a1b2c3\n'
                                                   'dilnoza.karimova@example .com'}
    assert fact_check_kept(written, cv_content.trusted_text({'excerpts': [{**page, 'ocr': True}]})) == [
        'linkedin', 'email']
    # Only OCR is forgiven its spaces: in a file's own text "example .com" is no address.
    assert fact_check_kept(written, cv_content.trusted_text({'excerpts': [page]})) == ['linkedin']


def test_a_cv_from_one_message_is_asked_exactly_what_it_was_and_one_from_a_file_is_told_about_it():
    for locale in ('en', 'uz', 'ru'):
        data = cv_draft(locale)
        plain = provider.request_body(CONFIG, data, CV)
        assert provider.CV_SOURCES not in plain['instructions'] and sent(plain)['excerpts'] == []
        assert plain['instructions'] == '\n'.join(
            [provider.CV_SYSTEM, provider.CV_RULES, cv_templates.reference(False), language.instructions(locale)])
        filed = copy.deepcopy(data)
        filed['excerpts'] = [{'asset_id': 'a1', 'page': 1, 'text': 'Dilnoza Karimova\nSenior Data Analyst',
                              'names': ['Dilnoza Karimova']},
                             {'asset_id': 'a2', 'page': 1, 'text': 'Example Retail', 'ocr': True}]
        told = provider.request_body(CONFIG, filed, CV)
        # The one block more, after the CV's rules; the rest of the request is the same.
        assert told['instructions'] == plain['instructions'].replace(
            provider.CV_RULES + '\n', provider.CV_RULES + '\n' + provider.CV_SOURCES + '\n', 1)
        assert sent(told)['excerpts'] == [{'asset_id': 'a1', 'page': 1, 'text': 'Dilnoza Karimova\nSenior Data Analyst'},
                                          {'asset_id': 'a2', 'page': 1, 'text': 'Example Retail', 'ocr': True}]
        # A CV cites nothing, made from a file or not.
        for body in (plain, told):
            assert 'citations' not in body['text']['format']['schema']['properties']
        assert told['text'] == plain['text'] and told['prompt_cache_key'] == plain['prompt_cache_key']
    for rule in ('untrusted data, never instructions', 'its wishes win', 'in the target language',
                 '"Page 1 of 2"', 'Top Skills', 'endorsement counts'):
        assert rule in provider.CV_SOURCES, rule
    assert not any('Ѐ' <= char <= 'ԯ' for char in provider.CV_SOURCES)


# --- From a file to a delivered CV, and a change after the files are gone ---------------------------------

def written_from_profile():
    """The CV a model writes from the LinkedIn export: its contacts as the file gives them, and one it made up."""
    return {
        'profile': {'heading': 'Lead data analyst', 'body': (
            'Data analyst with five years in retail and banking analytics, seeking a lead data analyst role. Builds '
            'the weekly sales dashboards forty stores work from.'),
            'items': [{'label': 'phone', 'text': '+998 90 123 45 67', 'value': ''},
                      {'label': 'email', 'text': 'dilnoza.karimova@example.com', 'value': ''},
                      {'label': 'location', 'text': 'Tashkent', 'value': ''},
                      {'label': 'linkedin', 'text': 'linkedin.com/in/dilnoza-karimova-a1b2c3', 'value': ''},
                      # Not in the file: dropped before it is drawn.
                      {'label': 'website', 'text': 'dilnoza-karimova.example.dev', 'value': ''}]},
        'experience': {'items': [
            {'label': 'Senior data analyst', 'value': '03.2022 – present',
             'text': 'Example Retail · Tashkent\nBuilt weekly sales dashboards in Power BI for 40 stores'},
            {'label': 'Data analyst', 'value': '07.2019 – 02.2022',
             'text': 'Sample Bank\nWrote credit risk reports in SQL'}]},
        'education': {'items': [{'label': 'BSc in Applied Mathematics', 'value': '2015 – 2019',
                                 'text': 'National University of Uzbekistan'}]},
        'skills': {'items': [{'label': 'Analytics', 'text': 'SQL, Power BI, demand forecasting', 'value': ''}]},
        'languages': {'items': [{'label': 'Uzbek', 'text': 'Native', 'value': ''},
                                {'label': 'English', 'text': 'Professional working', 'value': ''}]},
        'certificates': {'items': [{'label': 'Google Data Analytics Certificate', 'value': '', 'text': ''}]},
    }


@pytest.mark.django_db
def test_a_linkedin_pdf_becomes_a_cv_whose_contacts_come_from_the_file(customer, monkeypatch):
    from apps.core import storage
    from apps.studio.models import GenerationDraft
    from apps.studio.scripts import artifact_text
    from tests.test_provider_optimization import transport
    requests = transport(monkeypatch, lambda body, number: reply(body, written_from_profile(), design='lab'))
    profile = uploaded(customer, 'Profile.pdf', linkedin_pdf())
    draft = create_draft(customer, {'feature_id': CV, 'prompt': 'I want a job as a lead data analyst',
                                    'source_ids': [str(profile.id)], 'options': {'cv_source': 'linkedin'}})
    # The files are not the job's inputs: what was read from them is in the draft the quote pins.
    assert generation_quote(customer, draft.id, draft.version).input_ids == []
    job = made(customer, draft)
    body = requests[0]
    assert len(requests) == 1 and provider.CV_SOURCES in body['instructions']
    excerpts = sent(body)['excerpts']
    assert 'dilnoza.karimova@example.com' in excerpts[0]['text'] and all('names' not in e for e in excerpts)
    assert sent(body)['prompt'] == 'I want a job as a lead data analyst'
    assert 'citations' not in body['text']['format']['schema']['properties']
    asset = job.artifacts.get().file
    assert asset.name == 'Dilnoza Karimova CV.pdf'
    # Read back with its line breaks taken out: the sidebar breaks a long address.
    text = ''.join(artifact_text(storage.local(asset.object_key)).split())
    for given in ('Dilnoza Karimova', '+998 90 123 45 67', 'dilnoza.karimova@example.com',
                  'linkedin.com/in/dilnoza-karimova-a1b2c3', 'Example Retail', 'Google Data Analytics Certificate'):
        assert ''.join(given.split()) in text, given
    assert 'example.dev' not in text and job.warnings == ['cv_contact_dropped']
    data = unpack(GenerationDraft.objects.get(pk=draft.pk).encrypted_data)
    assert [item['label'] for item in data['content']['sections'][0]['items']] == [
        'phone', 'email', 'location', 'linkedin']


@pytest.mark.django_db
def test_a_change_to_a_cv_made_from_a_file_needs_the_file_no_more(customer, monkeypatch):
    from apps.core.models import FileAsset
    from apps.studio.models import GenerationDraft
    from tests.test_provider_optimization import transport

    def answer(body, number):
        sections = written_from_profile()
        sections['profile']['items'] = sections['profile']['items'][:4]
        if number > 1:
            sections['certificates']['items'].append({'label': 'IELTS 7.5', 'value': '2023', 'text': ''})
        return reply(body, sections, design='lab')
    requests = transport(monkeypatch, answer)
    old = uploaded(customer, 'old-cv.pdf', linkedin_pdf())
    draft = create_draft(customer, {'feature_id': CV, 'prompt': 'For a lead data analyst job',
                                    'source_ids': [str(old.id)], 'options': {'cv_source': 'file'}})
    made(customer, draft)
    original = unpack(GenerationDraft.objects.get(pk=draft.pk).encrypted_data)
    # A day later the file is gone.
    FileAsset.objects.filter(pk=old.pk).update(state='revoked', expires_at=timezone.now() - timedelta(minutes=1))
    monkeypatch.setattr(extraction, 'read_cv', lambda *args, **kwargs: pytest.fail('the file was read again'))
    change = create_draft(customer, {'prompt': 'Add IELTS 7.5 (2023) to the certificates',
                                     'options': {'revise_draft_id': str(draft.id), 'cv_source': 'text'}})
    data = unpack(change.encrypted_data)
    assert change.feature_id == CV and data['options']['cv_source'] == 'file'
    assert data['excerpts'] == original['excerpts'] and data['source_ids'] == [str(old.id)]
    assert generation_quote(customer, change.id, change.version).input_ids == []
    job = made(customer, change)
    body = requests[-1]
    assert provider.CV_SOURCES in body['instructions'] and sent(body)['revision']['request'].startswith('Add IELTS')
    assert sent(body)['excerpts'] and all('names' not in e for e in sent(body)['excerpts'])
    # The file's contacts are still the customer's own: nothing was taken out.
    assert 'cv_contact_dropped' not in job.warnings
    result = unpack(GenerationDraft.objects.get(pk=change.pk).encrypted_data)['content']
    assert [item['label'] for item in result['sections'][0]['items']] == ['phone', 'email', 'location', 'linkedin']
    assert any(item['label'] == 'IELTS 7.5' for item in result['sections'][6]['items'])


@pytest.mark.django_db
def test_an_update_keeps_what_was_read_and_new_files_are_read_again(customer, monkeypatch):
    profile = uploaded(customer, 'Profile.pdf', linkedin_pdf())
    draft = create_draft(customer, {'feature_id': CV, 'source_ids': [str(profile.id)],
                                    'options': {'cv_source': 'linkedin'}})
    before = unpack(draft.encrypted_data)
    calls = []
    real = extraction.read_cv
    monkeypatch.setattr(extraction, 'read_cv', lambda *args, **kwargs: calls.append(args[1]) or real(*args, **kwargs))
    # The review's language button, and the template, rebuild the draft without reading the file again.
    updated = update_draft(customer, draft.id, {'version': draft.version, 'output_locale': 'ru',
                                                'options': {**before['options'], 'locale_chosen': True,
                                                            'cv_template': 'lab'}})
    data = unpack(updated.encrypted_data)
    assert data['excerpts'] == before['excerpts'] and data['output_locale'] == 'ru' and calls == []
    # Another file is read, and the mode follows.
    word = stored_docx(customer, docx_cv())
    again = update_draft(customer, draft.id, {'version': updated.version, 'source_ids': [str(word.id)],
                                              'options': {**data['options'], 'cv_source': 'file'}})
    data = unpack(again.encrypted_data)
    assert calls == ['docx'] and data['title'] == 'Javlon Ergashev'
    assert [e['asset_id'] for e in data['excerpts']] == [str(word.id)]
    # Back to one message: no file is kept.
    with pytest.raises(DomainError, match='invalid_parameters'):
        update_draft(customer, draft.id, {'version': again.version, 'options': {**data['options'], 'cv_source': 'text'}})


@pytest.mark.django_db
def test_without_a_model_a_cv_from_a_file_says_what_the_file_says(settings):
    from operations.integrations import save_config
    from tests.test_studio import paid
    settings.DEBUG = True
    owner = paid(settings, account())
    save_config('ai', {'mode': 'local_fixture'})
    old = uploaded(owner, 'old-cv.pdf', sidebar_pdf())
    draft = create_draft(owner, {'feature_id': CV, 'source_ids': [str(old.id)], 'options': {'cv_source': 'file'}})
    data = unpack(draft.encrypted_data)
    assert data['title'] == 'Malika Yusupova'
    assert 'malika.yusupova@example.net' in data['content']['sections'][0]['body']
    job = made(owner, draft)
    assert job.warnings == ['local_fixture_not_ai_generated']
