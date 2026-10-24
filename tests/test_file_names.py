"""What a result is called: after the customer's file, or its title, never the same twice."""
import asyncio
import io
import re
import uuid
import zipfile
from datetime import timedelta
from unittest.mock import AsyncMock, Mock
from urllib.parse import unquote

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone
from PIL import Image
from pypdf import PdfWriter

from apps.core.identity import resolve_account
from apps.core.models import Artifact, FileAsset, Job, Quote
from apps.core.naming import STEM_LIMIT, clean, preview_name, stock
from apps.core.services import create_quote, execute_job, settle_job, storage_path, submit_job, upload_file

pytestmark = pytest.mark.django_db

CODE = r'[0-9a-f]{6}'


def account(uid=5150, locale='en'):
    return resolve_account({'id': uid, 'first_name': 'Names', 'language_code': locale}, is_test=True)


def pdf_bytes(pages=3):
    stream = io.BytesIO()
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=300)
    writer.write(stream)
    return stream.getvalue()


def upload(owner, name, pages=3):
    return upload_file(owner, SimpleUploadedFile(name, pdf_bytes(pages), 'application/pdf'))


def given(owner, name, mime='application/pdf'):
    """A file the customer gave, as far as naming needs it."""
    return FileAsset.objects.create(account=owner, name=name, object_key=f'inputs/{owner.id}/{uuid.uuid4().hex}',
                                    mime_type=mime, sha256='0' * 64, size_bytes=1, page_count=1,
                                    expires_at=timezone.now() + timedelta(hours=1))


def settled(owner, feature, sources=(), files=(('result.pdf', 'application/pdf'),), parameters=None, **hints):
    """A job of `feature` settled with `files` written by its processor; its results' names."""
    quote = Quote.objects.create(account=owner, feature_id=feature, parameters=parameters or {},
                                 input_ids=[str(s.id) for s in sources], expires_at=timezone.now() + timedelta(hours=1))
    job = Job.objects.create(account=owner, quote=quote, feature_id=feature, parameters=parameters or {},
                             input_ids=quote.input_ids, idempotency_key=uuid.uuid4().hex, request_hash='0' * 64)
    folder = storage_path(f'outputs/{owner.id}/{job.id}')
    folder.mkdir(parents=True, exist_ok=True)
    outputs = []
    for name, mime in files:
        (folder / name).write_bytes(b'result')
        outputs.append({'path': str(folder / name), 'name': name, 'mime_type': mime, 'page_count': 0, **hints})
    settle_job(job.id, 'succeeded', outputs=outputs)
    return job, [a.file for a in job.artifacts.select_related('file').order_by('file__name')]


def names(owner, *args, **kwargs):
    return [asset.name for asset in settled(owner, *args, **kwargs)[1]]


# --- the name itself ---------------------------------------------------------

@pytest.mark.parametrize('text,expected', [
    ('Annual report 2025', 'Annual-report-2025'),
    ('../../etc/passwd', 'etc-passwd'),
    ('a\\b/c:d*e?f"g<h>i|j', 'a-b-c-d-e-f-g-h-i-j'),
    ('"quoted" \'single\'', 'quoted-single'),
    ('😀 Trip 🚀 notes 👨‍👩‍👧', 'Trip-notes'),
    ('invoice‮gpj.exe', 'invoice-gpj-exe'),
    ('line\nbreak\ttab\x00nul', 'line-break-tab-nul'),
    ('..hidden.', 'hidden'),
    ('O‘zbekiston tarixi: 1-qism', 'O‘zbekiston-tarixi-1-qism'),
    ("O'zbekiston va g'alaba, ma'no", 'O‘zbekiston-va-g‘alaba-maʼno'),
    ('Отчёт «за» 2025/26 год', 'Отчёт-за-2025-26-год'),
    ('Ne’matov', 'Ne’matov'),
    ('🙂', ''),
    ('', ''),
])
def test_a_name_keeps_letters_of_every_alphabet_and_nothing_unsafe(text, expected):
    assert clean(text) == expected


def test_a_long_name_is_cut_at_a_word():
    assert clean('Word ' * 40) == '-'.join(['Word'] * 12) and len(clean('Word ' * 40)) <= STEM_LIMIT
    assert clean('x' * 300) == 'x' * STEM_LIMIT
    assert len(clean('Ўзбекистон ' * 30)) <= STEM_LIMIT


@pytest.mark.parametrize('stem', ['IMG_1234', 'photo_2026-10-20_10-11-12', 'WhatsApp Image 2026-10-20 at 10.11.12',
                                  'Screenshot 2026-10-20 at 10.11.12', 'PXL_20261020_101112345.MP', 'IMG-20261020-WA0001',
                                  '1000012345', 'DSC01234', 'Фото 12', 'photo', '5f3a2b1c-9d8e-4f00-a1b2-c3d4e5f6a7b8'])
def test_a_cameras_name_for_a_photo_says_nothing(stem):
    assert stock(stem)


@pytest.mark.parametrize('stem', ['passport', 'my photo', 'Pasport nusxasi', 'Диплом'])
def test_a_name_someone_chose_is_kept(stem):
    assert not stock(stem)


# --- every service ------------------------------------------------------------

@pytest.mark.parametrize('feature,files,expected', [
    ('pdf.compress', [('result.pdf', 'application/pdf')], [rf'Annual-report-2025-compressed-{CODE}\.pdf']),
    ('pdf.rotate', [('result.pdf', 'application/pdf')], [rf'Annual-report-2025-rotated-{CODE}\.pdf']),
    ('pdf.extract_pages', [('result.pdf', 'application/pdf')], [rf'Annual-report-2025-extracted-{CODE}\.pdf']),
    ('pdf.delete_pages', [('result.pdf', 'application/pdf')], [rf'Annual-report-2025-pages-removed-{CODE}\.pdf']),
    ('pdf.reorder', [('result.pdf', 'application/pdf')], [rf'Annual-report-2025-reordered-{CODE}\.pdf']),
    ('pdf.protect', [('result.pdf', 'application/pdf')], [rf'Annual-report-2025-protected-{CODE}\.pdf']),
    ('pdf.unlock_known', [('result.pdf', 'application/pdf')], [rf'Annual-report-2025-unlocked-{CODE}\.pdf']),
    ('pdf.to_images', [('pages.zip', 'application/zip')], [rf'Annual-report-2025-images-{CODE}\.zip']),
    ('pdf.split', [('part-001.pdf', 'application/pdf'), ('part-002.pdf', 'application/pdf')],
     [rf'Annual-report-2025-part-1-{CODE}\.pdf', rf'Annual-report-2025-part-2-{CODE}\.pdf']),
    ('convert.pdf_to_docx', [('editable-document.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')],
     [rf'Annual-report-2025-{CODE}\.docx']),
    ('convert.pdf_to_xlsx', [('extracted-tables.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')],
     [rf'Annual-report-2025-tables-{CODE}\.xlsx']),
    ('ocr.searchable_pdf', [('searchable.pdf', 'application/pdf')], [rf'Annual-report-2025-searchable-{CODE}\.pdf']),
    ('ocr.extract_text', [('recognized-text.txt', 'text/plain; charset=utf-8')], [rf'Annual-report-2025-text-{CODE}\.txt']),
    ('editor.add_text', [('edited.pdf', 'application/pdf')], [rf'Annual-report-2025-edited-{CODE}\.pdf']),
    ('editor.redact', [('redacted.pdf', 'application/pdf')], [rf'Annual-report-2025-redacted-{CODE}\.pdf']),
])
def test_a_tools_result_is_named_after_the_file_it_was_made_from(feature, files, expected):
    owner = account()
    found = names(owner, feature, [given(owner, 'Annual report 2025.pdf')], files)
    assert len(found) == len(expected) and all(re.fullmatch(p, n) for p, n in zip(expected, found)), found
    # The files of one task share their code.
    assert len({n.rsplit('-', 1)[1] for n in found}) == 1


@pytest.mark.parametrize('feature,source,mime', [
    ('convert.word_to_pdf', 'Shartnoma №12 (yakuniy).docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
    ('convert.pptx_to_pdf', 'Shartnoma №12 (yakuniy).pptx', 'application/vnd.openxmlformats-officedocument.presentationml.presentation'),
])
def test_a_conversion_keeps_the_name_and_changes_the_extension(feature, source, mime):
    owner = account()
    [name] = names(owner, feature, [given(owner, source, mime)], [('converted.pdf', 'application/pdf')])
    assert re.fullmatch(rf'Shartnoma-12-yakuniy-{CODE}\.pdf', name), name


def test_a_browsers_escapes_in_an_uploaded_name_are_read_back():
    owner = account()
    [name] = names(owner, 'pdf.rotate', [given(owner, 'Yillik hisobot %222025%22 100%.pdf')])
    assert re.fullmatch(rf'Yillik-hisobot-2025-100-rotated-{CODE}\.pdf', name), name


def test_a_merge_takes_the_first_files_name():
    owner = account()
    [name] = names(owner, 'pdf.merge', [given(owner, 'Отчёт за май.pdf'), given(owner, 'appendix.pdf')])
    assert re.fullmatch(rf'Отчёт-за-май-merged-{CODE}\.pdf', name), name


def test_photos_with_cameras_names_make_photos_and_chosen_names_stay():
    owner = account()
    photos = [given(owner, 'IMG_1234.jpg', 'image/jpeg'), given(owner, 'photo.jpg', 'image/jpeg')]
    [name] = names(owner, 'pdf.images_to_pdf', photos, [('images.pdf', 'application/pdf')])
    assert re.fullmatch(rf'photos-{CODE}\.pdf', name), name
    [name] = names(owner, 'pdf.images_to_pdf', [given(owner, 'Pasport nusxasi.jpg', 'image/jpeg')], [('images.pdf', 'application/pdf')])
    assert re.fullmatch(rf'Pasport-nusxasi-{CODE}\.pdf', name), name
    [name] = names(owner, 'ocr.extract_text', [given(owner, 'IMG_20261020_101112.jpg', 'image/jpeg')], [('recognized-text.txt', 'text/plain')])
    assert re.fullmatch(rf'text-{CODE}\.txt', name), name


@pytest.mark.parametrize('feature,files,hints,expected', [
    ('ai.pdf_topic', [('document.pdf', 'application/pdf')], {'title': 'Fotosintez: o‘simliklar qanday oziqlanadi'},
     rf'Fotosintez-o‘simliklar-qanday-oziqlanadi-{CODE}\.pdf'),
    ('ai.pdf_topic', [('document.pdf', 'application/pdf')], {'title': 'Untitled document'}, rf'document-{CODE}\.pdf'),
    ('ai.pdf_topic', [('document.pdf', 'application/pdf')], {'title': '', 'source_name': 'Lecture 3.pdf'}, rf'Lecture-3-{CODE}\.pdf'),
    ('ai.pptx', [('document.pptx', 'application/vnd.openxmlformats-officedocument.presentationml.presentation')],
     {'title': 'Цифровая экономика'}, rf'Цифровая-экономика-{CODE}\.pptx'),
    ('ai.pptx', [('document.pptx', 'application/vnd.openxmlformats-officedocument.presentationml.presentation')], {}, rf'slides-{CODE}\.pptx'),
    ('ai.cv', [('cv.pdf', 'application/pdf')], {'title': 'Dilnoza Karimova', 'source_name': 'old-cv.pdf'}, rf'Dilnoza-Karimova-CV-{CODE}\.pdf'),
    ('ai.cv', [('cv.pdf', 'application/pdf')], {'title': '', 'source_name': 'Profile.pdf'}, rf'Profile-CV-{CODE}\.pdf'),
    ('ai.cv', [('cv.pdf', 'application/pdf')], {'title': '', 'source_name': 'IMG_0042.jpg'}, rf'CV-{CODE}\.pdf'),
    ('ai.cv', [('cv.pdf', 'application/pdf')], {'title': 'Timur Rakhimov CV'}, rf'Timur-Rakhimov-CV-{CODE}\.pdf'),
])
def test_a_made_document_is_named_after_its_title_the_person_or_the_service(feature, files, hints, expected):
    [name] = names(account(), feature, (), files, parameters={'generation_draft_id': str(uuid.uuid4())}, **hints)
    assert re.fullmatch(expected, name), name


def test_an_outline_says_so():
    [name] = names(account(), 'ai.pdf_topic', (), [('outline.json', 'application/json')],
                   parameters={'stage': 'outline'}, title='Suv aylanishi')
    assert re.fullmatch(rf'Suv-aylanishi-outline-{CODE}\.json', name), name


# --- never the same twice --------------------------------------------------------

def test_the_same_file_done_twice_gives_two_names_and_a_taken_name_grows_its_code():
    owner = account()
    source = given(owner, 'report.pdf')
    first, second = (names(owner, 'pdf.compress', [source])[0] for _ in range(2))
    assert first != second
    job, [asset] = settled(owner, 'pdf.compress', [source])
    # Named again, as another job whose id starts the same would be: the name is taken.
    from apps.core.naming import result_name
    longer = result_name(job, {'path': 'result.pdf', 'mime_type': 'application/pdf'})
    assert longer != asset.name and re.fullmatch(r'report-compressed-[0-9a-f]{10}\.pdf', longer), longer
    clash = job
    for size in (10, 32):
        given(owner, f'report-compressed-{clash.pk.hex[:size]}.pdf')
    assert result_name(clash, {'path': 'result.pdf'}) == f'report-compressed-{clash.pk.hex}-2.pdf'


def test_a_result_of_a_result_carries_one_code_and_says_each_step_once():
    owner = account()
    _, [rotated] = settled(owner, 'pdf.rotate', [given(owner, 'Hisobot.pdf')])
    _, [compressed] = settled(owner, 'pdf.compress', [rotated])
    assert re.fullmatch(rf'Hisobot-rotated-compressed-{CODE}\.pdf', compressed.name), compressed.name
    _, [again] = settled(owner, 'pdf.compress', [compressed])
    assert re.fullmatch(rf'Hisobot-rotated-compressed-{CODE}\.pdf', again.name) and again.name != compressed.name
    # A customer's own name that looks like a code is theirs, not ours.
    [own] = names(owner, 'pdf.rotate', [given(owner, 'scan-abcdef12.pdf')])
    assert re.fullmatch(rf'scan-abcdef12-rotated-{CODE}\.pdf', own), own


def test_the_storage_key_keeps_the_processors_name_not_the_customers():
    owner = account()
    _, [asset] = settled(owner, 'ai.cv', (), [('cv.pdf', 'application/pdf')], title='Dilnoza Karimova')
    assert asset.object_key.endswith('/cv.pdf') and 'Dilnoza' not in asset.object_key
    _, [asset] = settled(owner, 'pdf.rotate', [given(owner, 'Maxfiy shartnoma.pdf')])
    assert asset.object_key.endswith('/result.pdf') and 'shartnoma' not in asset.object_key


# --- real tasks -------------------------------------------------------------------

def run(owner, feature, assets, parameters=None):
    quote = create_quote(owner, feature, [str(a.id) for a in assets], parameters or {})
    job, _ = submit_job(owner, quote.id, uuid.uuid4().hex)
    job = execute_job(job.id)
    assert job.status == 'succeeded', job.error_code
    return [a.file.name for a in job.artifacts.select_related('file').order_by('file__name')]


def test_real_pdf_tasks_name_their_results_after_the_upload():
    owner = account()
    source = upload(owner, 'Yillik hisobot "2025".pdf')
    assert re.fullmatch(rf'Yillik-hisobot-2025-rotated-{CODE}\.pdf', run(owner, 'pdf.rotate', [source], {'angle': 90})[0])
    merged = run(owner, 'pdf.merge', [upload(owner, 'Глава 1.pdf'), source])
    assert re.fullmatch(rf'Глава-1-merged-{CODE}\.pdf', merged[0]), merged
    parts = run(owner, 'pdf.split', [source], {'ranges': ['1', '2-3']})
    assert [p.rsplit('-', 1)[0] for p in parts] == ['Yillik-hisobot-2025-part-1', 'Yillik-hisobot-2025-part-2'], parts
    for feature, parameters, done in (('pdf.extract_pages', {'pages': '1'}, 'extracted'),
                                      ('pdf.delete_pages', {'pages': '1'}, 'pages-removed'),
                                      ('pdf.reorder', {'order': [3, 2, 1]}, 'reordered')):
        [name] = run(owner, feature, [source], parameters)
        assert re.fullmatch(rf'Yillik-hisobot-2025-{done}-{CODE}\.pdf', name), name
    [images] = run(owner, 'pdf.to_images', [source], {'pages': '1-2', 'format': 'png', 'dpi': 72})
    assert re.fullmatch(rf'Yillik-hisobot-2025-images-{CODE}\.zip', images), images


def test_real_photos_to_pdf_from_the_bot_are_named_photos():
    owner = account()
    stream = io.BytesIO()
    Image.new('RGB', (60, 80), 'white').save(stream, 'JPEG')
    photo = upload_file(owner, SimpleUploadedFile('photo.jpg', stream.getvalue(), 'image/jpeg'))
    [name] = run(owner, 'pdf.images_to_pdf', [photo])
    assert re.fullmatch(rf'photos-{CODE}\.pdf', name), name


# --- where the name reaches the customer --------------------------------------------

def login(owner):
    client = Client()
    session = client.session
    session['customer_account_id'] = str(owner.id)
    session.save()
    return client


@pytest.mark.parametrize('source,header', [
    ('Annual report.pdf', re.compile(rf'attachment; filename="Annual-report-rotated-{CODE}\.pdf"')),
    ('Ўзбекистон тарихи.pdf', re.compile(rf"attachment; filename\*=utf-8''(.+)")),
], ids=['ascii', 'cyrillic'])
def test_the_web_download_sends_the_name(source, header):
    owner = account()
    _, [asset] = settled(owner, 'pdf.rotate', [given(owner, source)])
    artifact = Artifact.objects.get(file=asset)
    response = login(owner).get(f'/api/v1/artifacts/{artifact.id}/download')
    assert response.status_code == 200
    disposition = response['Content-Disposition']
    found = header.fullmatch(disposition)
    assert found, disposition
    if found.groups():
        assert unquote(found.group(1)) == asset.name and re.fullmatch(rf'Ўзбекистон-тарихи-rotated-{CODE}\.pdf', asset.name)
    listed = login(owner).get(f'/api/v1/jobs/{artifact.job_id}').json()
    assert [a['name'] for a in listed['artifacts']] == [asset.name]


@pytest.mark.django_db(transaction=True)
def test_the_telegram_document_carries_the_name_as_utf8():
    from aiogram import Bot
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.methods import SendDocument
    from aiogram.types import BufferedInputFile
    from apps.commerce.models import BotDelivery
    from telegram.delivery import attempt
    owner = account(5151, 'uz')
    source = upload(owner, 'O‘quv reja "2026".pdf')
    quote = create_quote(owner, 'pdf.rotate', [str(source.id)], {'angle': 90})
    job, _ = submit_job(owner, quote.id, 'names-bot-delivery', origin='bot')
    job = execute_job(job.id)
    asset = job.artifacts.get().file
    assert re.fullmatch(rf'O‘quv-reja-2026-rotated-{CODE}\.pdf', asset.name), asset.name
    bot = Mock(send_document=AsyncMock(return_value=Mock(message_id=77)))
    asyncio.run(attempt(BotDelivery.objects.get(artifact__file=asset).id, bot))
    sent = bot.send_document.await_args.args[1]
    assert sent.filename == asset.name
    # What aiogram puts on the wire: the name in UTF-8, nothing escaped or lost.
    form = AiohttpSession().build_form_data(Bot('42:TEST'), SendDocument(chat_id=1, document=BufferedInputFile(b'%PDF', filename=asset.name)))

    class Sink:
        body = b''

        async def write(self, data):
            self.body += data
    sink = Sink()
    asyncio.run(form().write(sink))
    assert f'filename="{asset.name}"'.encode() in sink.body


def test_a_page_picture_is_named_after_its_file_and_page():
    owner = account()
    asset = given(owner, 'Diplom ilovasi.pdf')
    assert preview_name(asset, 2) == f'Diplom-ilovasi-page-2-{asset.pk.hex[:6]}.png'
    assert preview_name(given(owner, '🙂.pdf'), 1).startswith('page-1-')


def test_page_pictures_of_a_split_archive_keep_their_inner_names():
    """The archive is renamed, never what is inside it: page-0001.png and so on."""
    owner = account()
    source = upload(owner, 'Scan.pdf', pages=2)
    run(owner, 'pdf.to_images', [source], {'pages': '1-2', 'format': 'png', 'dpi': 72})
    asset = FileAsset.objects.filter(account=owner, mime_type='application/zip').get()
    with zipfile.ZipFile(storage_path(asset.object_key)) as archive:
        assert archive.namelist() == ['page-0001.png', 'page-0002.png']
