"""A category's sources: a .txt or an old Word .doc, taken only as purpose 'ai_source'.

A customer who picks a category may send the material as a text file or an old
Word file as well as a PDF or a .docx. The bot uploads those as 'ai_source';
only then is a .txt read as text (UTF-8, UTF-16 with its mark, or the
Windows-1251 of Russian and Uzbek Cyrillic Windows) and a .doc taken, its macros
refused and its words read by antiword. Its "pages" are parts of at most 3,000
characters (processors/source_text.pages), the parts the model will be shown.

Every other upload is exactly as it was: a .txt is still refused for the tools,
a .doc is not even a suffix they know, and the public endpoint refuses the
purpose as it refuses any it does not publish.

The people and organisations in these files are invented.
"""
import os
import struct
import subprocess
import time
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.errors import DomainError
from apps.core.models import AnalyticsEvent, FileAsset
from apps.core.services import upload_file, validate_inputs
from processors import source_text
from processors.engine import antiword_runtime, office_runtime
from tests.test_adversarial import principal

pytestmark = pytest.mark.django_db

UZBEK = ('Yashilobod tumani “Kamalak” xususiy maktabi o‘qituvchisi Dilfuza Karimova.\n'
         'Mavzu: “Suvning tabiatdagi aylanishi”. Bolalar g‘ayrat bilan qatnashdi, ta’lim sifati oshdi.')
RUSSIAN = ('Отчёт о работе кружка «Юный эколог» за первое полугодие.\n'
           'Руководитель кружка: Сабина Юлдашева. Проведено 12 занятий, участвовали 18 учеников.')
ENGLISH = 'Minutes of the Green Valley Parents Council, held on Monday.\nChair: Jasur Tursunov.'
NUL = b'\x00'


def refused_codes(account):
    return [p['code'] for p in AnalyticsEvent.objects.filter(account=account, event_type='upload.refused')
            .order_by('occurred_at', 'id').values_list('properties', flat=True)]


def upload(account, name, raw, purpose='ai_source'):
    return upload_file(account, SimpleUploadedFile(name, raw), 'bot', purpose=purpose)


def refusal(account, name, raw, purpose='ai_source'):
    with pytest.raises(DomainError) as refused:
        upload(account, name, raw, purpose)
    return refused.value.code


# ------------------------------------------------------------------ an old Word file, made here


def compound_file(streams, storages=()):
    """A minimal compound file (version 3, 512-byte sectors) holding these streams and empty storages.

    Each stream is padded to 4,096 bytes, so it lies in ordinary sectors as Word's
    own 'WordDocument' always does. Enough for the upload's checks; only a fake
    antiword reads it.
    """
    size, end, free, fat_mark, no = 512, 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFD, 0xFFFFFFFF
    entries = [('Root Entry', 5, end, 0)]
    body, next_sector = b'', 2  # sector 0 is the allocation table, 1 the directory
    chains = []
    for name, data in streams:
        data = data.ljust(max(4096, -(-len(data) // size) * size), b'\x00')
        count = len(data) // size
        entries.append((name, 2, next_sector, len(data)))
        chains.append((next_sector, count))
        body += data
        next_sector += count
    entries += [(name, 1, end, 0) for name in storages]
    assert len(entries) <= 4 and next_sector <= 128
    fat = [free] * 128
    fat[0], fat[1] = fat_mark, end
    for first, count in chains:
        for sector in range(first, first + count):
            fat[sector] = sector + 1 if sector < first + count - 1 else end
    directory = b''
    for index, (name, kind, start, length) in enumerate(entries):
        encoded = (name + '\x00').encode('utf-16-le')
        child = 1 if index == 0 and len(entries) > 1 else no
        sibling = index + 1 if 0 < index < len(entries) - 1 else no
        directory += (encoded.ljust(64, b'\x00') + struct.pack('<HBB', len(encoded), kind, 1)
                      + struct.pack('<III', no, sibling, child) + bytes(16 + 4 + 16) + struct.pack('<IQ', start, length))
    directory = directory.ljust(size, b'\x00')
    header = (source_text.OLE_MAGIC + bytes(16) + struct.pack('<HHHHH', 0x3E, 3, 0xFFFE, 9, 6) + bytes(6)
              + struct.pack('<IIIIIIIII', 0, 1, 1, 0, 4096, end, 0, end, 0) + struct.pack('<I', 0) + struct.pack('<108I', *[free] * 108))
    assert len(header) == size
    return header + struct.pack('<128I', *fat) + directory + body


def word_doc(*, macros=False):
    """An old binary Word file: a 'WordDocument' stream starting with Word's identifier, and Word's macro storage if asked."""
    return compound_file([('WordDocument', b'\xec\xa5' + bytes(30)), ('1Table', b'')], ('Macros',) if macros else ())


@pytest.fixture
def antiword(tmp_path, monkeypatch):
    """A stand-in antiword: prints `text.txt`, notes its arguments and HOME, and fails when `fail` exists."""
    folder = tmp_path / 'antiword'
    folder.mkdir()
    script = folder / 'antiword'
    script.write_text('#!/bin/sh\n'
                      f'printf "%s\\n" "$@" > "{folder}/args"\n'
                      f'printf "%s" "$HOME" > "{folder}/home"\n'
                      f'[ -e "{folder}/fail" ] && exit 1\n'
                      f'cat "{folder}/text.txt"\n')
    script.chmod(0o755)
    (folder / 'text.txt').write_text(f'{UZBEK}\n\n{RUSSIAN}\n', encoding='utf-8')
    monkeypatch.setenv('DOCMASTER_ANTIWORD_BIN', str(script))
    return folder


# ------------------------------------------------------------------ a .txt


@pytest.mark.parametrize('raw,text', [
    (UZBEK.encode('utf-8'), UZBEK),
    (b'\xef\xbb\xbf' + UZBEK.replace('\n', '\r\n').encode('utf-8'), UZBEK),
    (b'\xff\xfe' + RUSSIAN.encode('utf-16-le'), RUSSIAN),
    (b'\xfe\xff' + ENGLISH.encode('utf-16-be'), ENGLISH),
    (RUSSIAN.replace('\n', '\r\n').encode('cp1251'), RUSSIAN),
], ids=['utf-8', 'utf-8-mark', 'utf-16-mark', 'utf-16be-mark', 'windows-1251'])
def test_a_text_file_in_each_encoding_is_taken_as_a_category_source(raw, text):
    account, _ = principal(89101)
    asset = upload(account, 'material.txt', raw)
    assert source_text.decode(raw) == text
    assert (asset.mime_type, asset.metadata['kind'], asset.page_count) == ('text/plain', 'text', 1)
    assert asset.name == 'material.txt' and not refused_codes(account)


def test_a_text_file_is_still_refused_for_the_tools_and_a_cv():
    account, _ = principal(89102)
    for purpose in ('', 'cv_source'):
        assert refusal(account, 'notes.txt', UZBEK.encode('utf-8'), purpose) == 'unsupported_type'
        assert refusal(account, 'notes.txt', b'plain words', purpose) == 'unsupported_type'
    assert not FileAsset.objects.exists()
    assert refused_codes(account) == ['unsupported_type'] * 4


@pytest.mark.parametrize('raw', [
    b'Shartnoma\x00raqami 15',                          # a NUL
    bytes(range(256)) * 8,                               # a binary file named .txt
    b'\x01\x02\x03\x04 header \x05\x06\x07\x08' * 20,    # control characters, no NUL
    'Shartnoma raqami 15'.encode('utf-16-le'),           # UTF-16 without its mark
    'Café crème brûlée à la carte'.encode('latin-1'),    # neither UTF-8 nor Cyrillic
], ids=['nul', 'binary', 'controls', 'utf16-no-mark', 'latin-1'])
def test_a_txt_that_is_not_text_is_refused_and_counted(raw):
    account, _ = principal(89103)
    assert refusal(account, 'material.txt', raw) == 'unsupported_type'
    assert refused_codes(account) == ['unsupported_type'] and not FileAsset.objects.exists()


def test_a_long_text_counts_its_parts_and_a_plan_cap_still_holds():
    from operations import plans as plan_settings
    account, _ = principal(89104)
    paragraph = 'Biznes-reja bo‘limi. ' * 60  # 1,260 characters
    text = '\n'.join([paragraph.strip()] * 12)  # ~15,000 characters
    asset = upload(account, 'reja.txt', text.encode('utf-8'))
    assert asset.page_count == len(source_text.pages(text)) >= 6
    plan_settings.save(account.plan, {'max_pages_per_job': '2'})
    with pytest.raises(DomainError) as refused:
        upload(account, 'reja.txt', text.encode('utf-8'))
    assert (refused.value.code, refused.value.params) == ('page_limit', {'limit': 2})


def test_a_text_too_big_for_a_thousand_parts_is_refused_before_it_is_decoded(monkeypatch, tmp_path):
    from processors import ProcessorError, engine
    # No encoding takes more than four bytes a character, so past this size a file cannot fit the page limit.
    assert source_text.MAX_TEXT_BYTES == engine.MAX_PAGES * source_text.PAGE_CHARS * 4
    monkeypatch.setattr(source_text, 'MAX_TEXT_BYTES', 1000)
    monkeypatch.setattr(source_text, 'decode', lambda raw: pytest.fail('decoded'))
    path = tmp_path / 'katta.txt'
    path.write_bytes('Отчёт. '.encode('cp1251') * 200)
    with pytest.raises(ProcessorError) as refused:
        engine.inspect_file(path, sources=True)
    assert refused.value.code == 'page_limit'


def test_an_empty_text_file_is_one_page_whose_draft_will_say_it_had_nothing():
    account, _ = principal(89105)
    assert upload(account, 'empty.txt', b' \r\n\r\n ').page_count == 1


def test_text_and_word_files_never_reach_a_file_tool(monkeypatch, antiword):
    monkeypatch.setattr('apps.core.services.require_feature', lambda account, feature_id: None)
    account, _ = principal(89106)
    for asset in (upload(account, 'notes.txt', ENGLISH.encode('utf-8')), upload(account, 'old.doc', word_doc())):
        for feature in ('pdf.compress', 'convert.word_to_pdf', 'ocr.extract_text', 'pdf.images_to_pdf'):
            with pytest.raises(DomainError, match='unsupported_file'):
                validate_inputs(account, feature, [str(asset.id)])


# ------------------------------------------------------------------ an old .doc


def test_an_old_word_file_is_taken_and_counted_from_antiwords_text(antiword):
    account, _ = principal(89107)
    asset = upload(account, 'Ariza namuna.doc', word_doc())
    assert (asset.mime_type, asset.metadata['kind'], asset.page_count) == ('application/msword', 'doc', 1)
    assert set(asset.metadata) == {'size_bytes', 'encrypted', 'mime_type', 'page_count', 'kind'}
    # Run with the UTF-8 mapping, a paragraph a line, on the stored copy; in a HOME of its own that is gone afterwards.
    args = (antiword / 'args').read_text().split('\n')
    assert args[:4] == ['-m', 'UTF-8.txt', '-w', '0'] and args[4].endswith('.doc') and 'inputs' in args[4]
    home = (antiword / 'home').read_text()
    assert 'docmaster-antiword-' in home and not Path(home).exists()


def test_an_old_word_files_pages_are_the_parts_of_its_text(antiword):
    account, _ = principal(89108)
    words = '\n'.join(['Kurs ishi bobi. ' * 100] * 5)  # five paragraphs of 1,600 characters
    (antiword / 'text.txt').write_text(words + '\n[pic]\n', encoding='utf-8')
    asset = upload(account, 'kurs-ishi.doc', word_doc())
    assert asset.page_count == len(source_text.pages(source_text.doc_text(words.encode()))) == 5


def test_a_doc_is_refused_for_every_other_purpose_as_before(antiword):
    account, _ = principal(89109)
    for purpose in ('', 'cv_source'):
        assert refusal(account, 'old.doc', word_doc(), purpose) == 'unsupported_file'
    assert not (antiword / 'args').exists()


def test_a_word_file_with_macros_is_refused(antiword):
    account, _ = principal(89110)
    assert refusal(account, 'macros.doc', word_doc(macros=True)) == 'active_content_unsupported'
    assert refused_codes(account) == ['active_content_unsupported'] and not (antiword / 'args').exists()


@pytest.mark.parametrize('raw', [
    compound_file([('Workbook', b'\x09\x08' + bytes(30))]),          # an old Excel file named .doc
    compound_file([('WordDocument', b'not word' + bytes(30))]),      # a stream of that name that is not Word
    word_doc()[:700],                                                 # cut short
    b'{\\rtf1\\ansi Ariza}',                                          # Word's RTF saved as .doc
], ids=['excel', 'not-word', 'truncated', 'rtf'])
def test_a_doc_that_is_not_an_old_word_file_is_refused(raw, antiword):
    account, _ = principal(89111)
    assert refusal(account, 'old.doc', raw) == 'unsupported_type'
    assert not (antiword / 'args').exists()


def test_without_antiword_a_doc_is_refused_as_a_docx_is_without_libreoffice(antiword, monkeypatch):
    monkeypatch.setenv('DOCMASTER_ANTIWORD_BIN', str(antiword / 'missing'))
    account, _ = principal(89112)
    assert refusal(account, 'old.doc', word_doc()) == 'conversion_preflight_unavailable'


def test_a_doc_antiword_cannot_read_is_refused_and_nothing_of_it_is_kept(antiword):
    (antiword / 'fail').touch()
    account, _ = principal(89113)
    assert refusal(account, 'locked.doc', word_doc()) == 'invalid_file'
    assert refused_codes(account) == ['invalid_file'] and not FileAsset.objects.exists()


# ------------------------------------------------------------------ links and the public endpoint


@pytest.fixture
def office_pages(monkeypatch):
    """A Word file's page count without LibreOffice, which counts it on upload and which tests may not have."""
    from apps.core import services
    from processors.engine import inspect_file
    real = services.engine_inspect

    def inspect(path, password=None, allow_links=False, sources=False):
        from processors import ProcessorError
        if not str(path).endswith('.docx'):
            return real(path, password=password, allow_links=allow_links, sources=sources)
        try:
            return {**inspect_file(path, office_preflight=False, allow_links=allow_links, sources=sources), 'page_count': 1}
        except ProcessorError as exc:
            raise DomainError(exc.code) from None
    monkeypatch.setattr(services, 'engine_inspect', inspect)


def test_a_word_source_with_a_clickable_link_is_taken_but_never_by_the_tools(office_pages, monkeypatch):
    from tests.test_cv_sources import docx_with_links
    monkeypatch.setattr('apps.core.services.require_feature', lambda account, feature_id: None)
    account, _ = principal(89114)
    assert refusal(account, 'thesis.docx', docx_with_links(), '') == 'external_content_unsupported'
    asset = upload(account, 'thesis.docx', docx_with_links())
    assert asset.metadata['kind'] == 'docx' and asset.metadata['external_hyperlinks'] is True
    with pytest.raises(DomainError, match='external_content_unsupported'):
        validate_inputs(account, 'convert.word_to_pdf', [str(asset.id)])


def test_the_public_endpoint_refuses_the_purpose_as_any_unpublished_one():
    account, client = principal(89115)
    for purpose in ('ai_source', 'anything'):
        response = client.post('/api/v1/files/uploads', {'file': SimpleUploadedFile('notes.txt', ENGLISH.encode()),
                                                         'purpose': purpose})
        assert response.status_code == 400 and response.json()['error']['code'] == 'invalid_parameters'
    assert not FileAsset.objects.exists() and not refused_codes(account)


# ------------------------------------------------------------------ the pure functions


def test_decoding_follows_the_mark_then_utf8_then_cyrillic_windows():
    assert source_text.decode('Ўзбекистон, Қашқадарё'.encode('utf-8')) == 'Ўзбекистон, Қашқадарё'
    assert source_text.decode('Сабина Юлдашева, «Юный эколог»'.encode('cp1251')) == 'Сабина Юлдашева, «Юный эколог»'
    # Uzbek Latin saved by Notepad as "ANSI": its o‘ and g‘ are the same bytes in either Windows code page.
    assert source_text.decode('O‘g‘il bola ta’lim oldi'.encode('cp1252')) == 'O‘g‘il bola ta’lim oldi'
    assert source_text.decode(b'line one\r\nline two\rline three') == 'line one\nline two\nline three'
    # Latin words beside Cyrillic ones stay Cyrillic; accented letters inside Latin words are Western text.
    assert source_text.decode('Отчёт по проекту Green Valley, этап 2'.encode('cp1251')) == 'Отчёт по проекту Green Valley, этап 2'
    assert source_text.decode('Résumé: café, crème, déjà vu'.encode('cp1252')) is None
    # A mark promises an encoding: bytes that break it are not guessed at.
    assert source_text.decode(b'\xef\xbb\xbf\xff\xfe') is None
    assert source_text.decode(b'\xff\xfe\x00\xd8') is None  # a lone surrogate
    assert source_text.decode(b'\xff\xfe\x00\x00h\x00\x00\x00') is None  # UTF-32 comes out with NULs
    # UTF-8 cut in the middle of a character, or with one stray byte, is UTF-8 with U+FFFD there,
    # never Windows-1251 mojibake ("РўРѕС€..."); damaged far more than that, it is refused.
    cyrillic = 'Toshkent: Тошкент вилояти, Янгиобод тумани'
    assert source_text.decode(cyrillic.encode('utf-8') + b'\xd1') == cyrillic + '\ufffd'
    words = 'Ўзбекистон, Қашқадарё. ' * 100
    assert source_text.decode(words[:250].encode() + b'\xff' + words[250:].encode()) == words[:250] + '\ufffd' + words[250:]
    assert source_text.decode(b'\xff'.join(word.encode() for word in words.split())) is None


def test_parts_are_cut_at_paragraphs_then_sentences_then_spaces_and_lose_nothing():
    assert source_text.pages('') == [] and source_text.pages(' \n\n\t\n') == []
    assert source_text.pages('Bir.\n\nIkki.') == ['Bir.\n\nIkki.']
    paragraphs = [f'{n}-band. ' + 'Mazmun matni. ' * 120 for n in range(1, 6)]  # ~1,700 characters each
    text = '\n'.join(p.strip() for p in paragraphs)
    parts = source_text.pages(text)
    assert len(parts) == 5 and all(part.startswith(f'{n}-band.') for n, part in enumerate(parts, 1))
    long_paragraph = ' '.join(f'Gap {n} shu yerda tugaydi.' for n in range(400))  # one line of ~10,000 characters
    parts = source_text.pages(long_paragraph)
    assert all(len(part) <= 3000 for part in parts) and len(parts) == 4
    assert all(part.endswith('tugaydi.') for part in parts)
    assert ' '.join(parts) == long_paragraph
    word = 'x' * 7000
    assert [len(p) for p in source_text.pages(f'boshlanishi {word} oxiri')] == [11, 3000, 3000, 1006]
    assert [len(p) for p in source_text.pages('abc ' * 5000, size=100)] == [99] * 200
    # A sentence ends where a run of punctuation begins, with its closing quotes.
    assert source_text.pages('Birinchi gap?! “Ikkinchi!” Uchinchi... 3.14 son.', size=20) == [
        'Birinchi gap?!', '“Ikkinchi!”', 'Uchinchi...', '3.14 son.']


def test_cutting_a_long_run_of_punctuation_takes_linear_time():
    # A line of nothing but dots, or of "!?", once took seconds that grew with
    # the square of its length, in the upload's child and again in every excerpt.
    started = time.process_time()
    assert [len(p) for p in source_text.pages('.' * 200_000)] == [3000] * 66 + [2000]
    assert len(source_text.pages('!?' * 100_000)) == 67
    assert len(source_text.pages('Gap… ' + '…' * 100_000 + ' tamom.')) == 35
    assert time.process_time() - started < 0.5


def test_a_damaged_compound_file_is_never_a_crash():
    good = word_doc()
    assert source_text.is_word97(good) and not source_text.has_macros(good)
    assert source_text.has_macros(word_doc(macros=True))
    for raw in (b'', good[:511], good[:600], good[:1100], good[:1537],
                good[:0x4C] + b'\x05\x00\x00\x00' + good[0x50:],  # the table points past the end
                good[:0x30] + b'\x00\x00\x00\x00' + good[0x34:],  # the directory is the table itself
                good[:512] + struct.pack('<128I', *[1] * 128) + good[1024:]):  # every chain loops
        assert source_text.is_word97(raw) is False and source_text.has_macros(raw) is False


# ------------------------------------------------------------------ the real antiword (CI and the image)


@pytest.mark.skipif(not antiword_runtime() or not office_runtime()['available'],
                    reason='needs antiword and LibreOffice, which makes the old Word file')
def test_a_real_old_word_file_is_read_by_antiword_in_three_languages(tmp_path):
    from docx import Document
    from processors.engine import doc_text
    document = Document()
    for paragraph in (UZBEK + '\n' + RUSSIAN + '\n' + ENGLISH).split('\n'):
        document.add_paragraph(paragraph)
    source = tmp_path / 'ariza.docx'
    document.save(source)
    completed = subprocess.run([office_runtime()['executable'], f'-env:UserInstallation={(tmp_path / "profile").as_uri()}',
                                '--headless', '--nologo', '--nodefault', '--nofirststartwizard',
                                '--convert-to', 'doc:MS Word 97', '--outdir', str(tmp_path), str(source)],
                               stdin=subprocess.DEVNULL, capture_output=True, timeout=120, check=False,
                               env={'PATH': os.environ.get('PATH', ''), 'HOME': str(tmp_path)})
    raw = (tmp_path / 'ariza.doc').read_bytes()
    assert completed.returncode == 0 and source_text.is_word97(raw)
    text = doc_text(tmp_path / 'ariza.doc')
    for words in ('Dilfuza Karimova', 'o‘qituvchisi', 'g‘ayrat', 'ta’lim', 'Сабина Юлдашева', '«Юный эколог»', 'Jasur Tursunov'):
        assert words in text
    account, _ = principal(89116)
    asset = upload(account, 'ariza.doc', raw)
    assert (asset.metadata['kind'], asset.page_count) == ('doc', len(source_text.pages(text)))
