"""A category's Word and text sources, read in their own bounded child (extraction.read_source).

A customer who picks a category may attach a .docx, an old .doc or a .txt.
processors/source_reader.py reads one such file in a child with read_cv's
boundary and gives its text in the parts the model is shown: a Word body in
document order (links, tables, text boxes and content controls; no headers or
footers), a .txt decoded as its upload decoded it, an old .doc through
antiword. For a .txt and a .doc the parts are the page count the upload
stored, so the two source-page checks of a draft agree. A child that runs over
its time is killed with everything it started, a failure carries nothing of
the file, and a file too long for any draft is refused, never cut silently.

The people and organisations in these files are invented.
"""
import io
import json
import os
import subprocess
import time

import pytest

from apps.core.errors import DomainError
from apps.studio import extraction
from processors import source_text
from processors.engine import antiword_runtime, office_runtime
from tests.test_cv_sources import _hyperlink
from tests.test_upload_ai_source import ENGLISH, RUSSIAN, UZBEK, antiword, principal, upload, word_doc  # noqa: F401  (antiword is a fixture)

pytestmark = pytest.mark.django_db

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def _block(xml):
    from docx.oxml import parse_xml
    return parse_xml(
        f'<w:root xmlns:w="{W}" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
        'xmlns:v="urn:schemas-microsoft-com:vml" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        f'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">{xml}</w:root>')[0]


def thesis_docx():
    """A defence thesis: a header and footer, a link, a tracked change, a table, a text box and a content control."""
    from docx import Document
    document = Document()
    section = document.sections[0]
    section.header.paragraphs[0].text = 'Samarqand Iqtisodiyot Kolleji — 2026'
    section.footer.paragraphs[0].text = 'Sahifa 1'
    document.add_paragraph('Bitiruv malakaviy ishi: “Kichik biznesda raqamli marketing”.')
    linked = document.add_paragraph('Muallif: Nodira Ergasheva, ')
    _hyperlink(linked, 'mailto:nodira.ergasheva@example.com', 'nodira.ergasheva@example.com')
    body = document.element.body
    tail = len(body) - 1  # before the section properties
    body.insert(tail, _block(
        '<w:p><w:r><w:t xml:space="preserve">Tanlanma </w:t></w:r>'
        '<w:ins w:id="1" w:author="Ilmiy rahbar"><w:r><w:t>120 ta</w:t></w:r></w:ins>'
        '<w:del w:id="2" w:author="Ilmiy rahbar"><w:r><w:delText>90 ta</w:delText></w:r></w:del>'
        '<w:r><w:t xml:space="preserve"> do‘kondan iborat.</w:t></w:r></w:p>'))
    table = document.add_table(rows=3, cols=3)
    for row, values in enumerate((('Yil', 'Do‘konlar', 'Savdo'), ('2024', '48', '1 150 000')), 0):
        for column, value in enumerate(values):
            table.cell(row, column).text = value
    merged = table.cell(2, 0).merge(table.cell(2, 1))
    merged.text = 'Jami'
    table.cell(2, 2).text = '2 300 000'
    lines = '<w:p><w:r><w:t>Gipoteza: onlayn reklama savdoni oshiradi.</w:t></w:r></w:p>'
    body.insert(len(body) - 1, _block(
        '<w:p><w:r><mc:AlternateContent><mc:Choice Requires="wps"><w:drawing><wp:anchor><a:graphic><a:graphicData '
        'uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"><wps:wsp><wps:txbx><w:txbxContent>'
        f'{lines}</w:txbxContent></wps:txbx></wps:wsp></a:graphicData></a:graphic></wp:anchor></w:drawing></mc:Choice>'
        f'<mc:Fallback><w:pict><v:shape><v:textbox><w:txbxContent>{lines}</w:txbxContent></v:textbox></v:shape>'
        '</w:pict></mc:Fallback></mc:AlternateContent></w:r></w:p>'))
    body.insert(len(body) - 1, _block(
        '<w:sdt><w:sdtContent><w:p><w:r><w:t>Xulosa: raqamli kanallar samarali.</w:t></w:r></w:p></w:sdtContent></w:sdt>'))
    raw = io.BytesIO()
    document.save(raw)
    return raw.getvalue()


def read(tmp_path, name, raw, kind, **kwargs):
    path = tmp_path / name
    path.write_bytes(raw)
    return extraction.read_source(path, kind, **kwargs)


# ------------------------------------------------------------------ Word


def test_a_word_body_is_read_in_order_with_its_link_table_box_and_control(tmp_path):
    parts = read(tmp_path, 'thesis.docx', thesis_docx(), 'docx')
    assert parts == [(1, '\n'.join([
        'Bitiruv malakaviy ishi: “Kichik biznesda raqamli marketing”.',
        'Muallif: Nodira Ergasheva, nodira.ergasheva@example.com',
        'Tanlanma 120 ta do‘kondan iborat.',
        'Yil | Do‘konlar | Savdo',
        '2024 | 48 | 1 150 000',
        'Jami | 2 300 000',
        'Gipoteza: onlayn reklama savdoni oshiradi.',
        'Xulosa: raqamli kanallar samarali.']))]
    # The header and footer are not part of the work, and deleted text is not text.
    assert 'Kolleji' not in parts[0][1] and 'Sahifa' not in parts[0][1] and '90 ta' not in parts[0][1]


def test_a_long_word_file_is_cut_into_parts_that_lose_nothing(tmp_path):
    from docx import Document
    document = Document()
    paragraphs = [f'{number}-band. ' + 'Raqamli marketing kichik biznes uchun muhim vosita hisoblanadi. ' * 12
                  for number in range(1, 41)]
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    raw = io.BytesIO()
    document.save(raw)
    parts = read(tmp_path, 'long.docx', raw.getvalue(), 'docx')
    assert [number for number, _ in parts] == list(range(1, len(parts) + 1)) and len(parts) > 5
    assert all(len(text) <= source_text.PAGE_CHARS for _, text in parts)
    assert '\n'.join(text for _, text in parts) == '\n'.join(p.strip() for p in paragraphs)


def test_a_word_file_with_macros_or_without_a_body_is_a_failure(tmp_path):
    import zipfile
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, 'w') as archive:
        archive.writestr('word/document.xml', f'<w:document xmlns:w="{W}"><w:body/></w:document>')
        archive.writestr('word/vbaProject.bin', b'macros')
    for content in (raw.getvalue(), b'PK\x03\x04 not really a zip'):
        with pytest.raises(DomainError) as failed:
            read(tmp_path, 'bad.docx', content, 'docx')
        assert failed.value.code == 'source_extraction_failed' and not failed.value.params


# ------------------------------------------------------------------ text


@pytest.mark.parametrize('raw', [
    UZBEK.encode('utf-8'),
    b'\xff\xfe' + RUSSIAN.replace('\n', '\r\n').encode('utf-16-le'),
    RUSSIAN.replace('\n', '\r\n').encode('cp1251'),
], ids=['utf-8', 'utf-16-mark', 'windows-1251'])
def test_a_text_file_is_read_as_its_upload_decoded_it(tmp_path, raw):
    assert read(tmp_path, 'material.txt', raw, 'text') == list(enumerate(source_text.pages(source_text.decode(raw)), 1))


def test_a_text_files_parts_are_the_pages_its_upload_counted():
    account, _ = principal(89201)
    text = '\n'.join(['Konspekt bo‘limi. ' * 70] * 9)
    asset = upload(account, 'konspekt.txt', text.encode('utf-8'))
    from apps.core import storage
    parts = extraction.read_source(storage.local(asset.object_key), 'text')
    assert len(parts) == asset.page_count > 3
    assert all(len(part) <= source_text.PAGE_CHARS for _, part in parts)


def test_a_binary_file_named_text_is_a_failure(tmp_path):
    with pytest.raises(DomainError) as failed:
        read(tmp_path, 'setup.txt', b'MZ\x90\x00\x03\x00\x00\x00' * 50, 'text')
    assert failed.value.code == 'source_extraction_failed' and not failed.value.params


# ------------------------------------------------------------------ old Word


def test_an_old_word_file_is_read_by_antiword_as_its_upload_counted_it(antiword):
    words = '\n'.join(['Kurs ishi bobi. ' * 100] * 5)
    (antiword / 'text.txt').write_text(words + '\n[pic]\n', encoding='utf-8')
    account, _ = principal(89202)
    asset = upload(account, 'kurs-ishi.doc', word_doc())
    from apps.core import storage
    parts = extraction.read_source(storage.local(asset.object_key), 'doc')
    assert [text for _, text in parts] == source_text.pages(source_text.doc_text(words.encode()))
    assert len(parts) == asset.page_count == 5 and '[pic]' not in ''.join(text for _, text in parts)
    # The same arguments as the upload's, in a HOME of its own that is gone afterwards.
    args = (antiword / 'args').read_text().split('\n')
    assert args[:4] == ['-m', 'UTF-8.txt', '-w', '0'] and args[4].endswith('.doc')
    home = (antiword / 'home').read_text()
    assert 'docmaster-antiword-' in home and not os.path.exists(home)


def test_an_old_word_file_antiword_cannot_read_is_a_failure_with_nothing_of_it(tmp_path, antiword):
    (antiword / 'fail').touch()
    with pytest.raises(DomainError) as failed:
        read(tmp_path, 'locked.doc', word_doc(), 'doc')
    assert failed.value.code == 'source_extraction_failed' and not failed.value.params


def test_without_antiword_an_old_word_file_is_unavailable_as_at_upload(tmp_path, antiword, monkeypatch):
    monkeypatch.setenv('DOCMASTER_ANTIWORD_BIN', str(antiword / 'missing'))
    with pytest.raises(DomainError) as failed:
        read(tmp_path, 'old.doc', word_doc(), 'doc')
    assert failed.value.code == 'conversion_preflight_unavailable'


@pytest.mark.skipif(not antiword_runtime() or not office_runtime()['available'],
                    reason='needs antiword and LibreOffice, which makes the old Word file')
def test_a_real_old_word_file_is_read_in_three_languages(tmp_path):
    from docx import Document
    document = Document()
    for paragraph in (UZBEK + '\n' + RUSSIAN + '\n' + ENGLISH).split('\n'):
        document.add_paragraph(paragraph)
    document.save(tmp_path / 'ariza.docx')
    subprocess.run([office_runtime()['executable'], f'-env:UserInstallation={(tmp_path / "profile").as_uri()}',
                    '--headless', '--nologo', '--nodefault', '--nofirststartwizard',
                    '--convert-to', 'doc:MS Word 97', '--outdir', str(tmp_path), str(tmp_path / 'ariza.docx')],
                   stdin=subprocess.DEVNULL, capture_output=True, timeout=120, check=True,
                   env={'PATH': os.environ.get('PATH', ''), 'HOME': str(tmp_path)})
    text = '\n'.join(part for _, part in extraction.read_source(tmp_path / 'ariza.doc', 'doc'))
    for words in ('Dilfuza Karimova', 'o‘qituvchisi', 'g‘ayrat', 'ta’lim', 'Сабина Юлдашева', '«Юный эколог»', 'Jasur Tursunov'):
        assert words in text


# ------------------------------------------------------------------ the boundary


def stub(tmp_path, monkeypatch, program):
    reader = tmp_path / 'stub_reader.py'
    reader.write_text(program)
    monkeypatch.setattr(extraction, 'SOURCE_READER', reader)
    return reader


def test_a_reader_that_runs_over_its_time_is_killed_with_everything_it_started(tmp_path, monkeypatch):
    started = tmp_path / 'started'
    stub(tmp_path, monkeypatch, 'import subprocess, time\n'
                                f'child = subprocess.Popen(["sleep", "60"])\nopen({str(started)!r}, "w").write(str(child.pid))\n'
                                'time.sleep(60)\n')
    monkeypatch.setattr(extraction, 'SOURCE_GRACE_SECONDS', 0)
    begun = time.monotonic()
    with pytest.raises(DomainError) as failed:
        extraction.read_source(tmp_path / 'any.docx', 'docx', seconds=1)
    assert failed.value.code == 'source_extraction_failed' and not failed.value.params
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


def test_the_child_is_isolated_and_inherits_no_credentials(tmp_path, monkeypatch):
    seen = tmp_path / 'seen.json'
    monkeypatch.setenv('DATABASE_URL', 'postgres://secret')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', '123:secret')
    monkeypatch.setenv('OPENAI_API_KEY', 'secret')
    stub(tmp_path, monkeypatch, 'import json, os, sys\n'
                                f'open({str(seen)!r}, "w").write(json.dumps({{"env": sorted(os.environ), "isolated": sys.flags.isolated, '
                                '"cwd": os.getcwd(), "argv": sys.argv[1:]}))\n'
                                'print(json.dumps({"parts": ["Kirish."], "truncated": False}))\n')
    assert extraction.read_source(tmp_path / 'thesis.docx', 'docx') == [(1, 'Kirish.')]
    report = json.loads(seen.read_text())
    assert not {'DATABASE_URL', 'TELEGRAM_BOT_TOKEN', 'OPENAI_API_KEY'} & set(report['env'])
    # Beside the whitelist only what the platform adds to every process: Python's
    # C-locale coercion sets LC_CTYPE, and macOS its text encoding variable.
    assert set(report['env']) <= {'PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'SYSTEMROOT', 'PYTHONDONTWRITEBYTECODE', 'MALLOC_ARENA_MAX',
                                  'LC_CTYPE', '__CF_USER_TEXT_ENCODING'}
    assert report['isolated'] == 1 and os.path.realpath(report['cwd']) != os.path.realpath(os.getcwd())
    assert report['argv'] == ['docx', str(tmp_path / 'thesis.docx'), '', '30']


@pytest.mark.parametrize('printed', [
    'print("not json")',
    'print(json.dumps({"parts": [1, 2], "truncated": False}))',
    'print(json.dumps({"parts": ["a"]}))',
    'print(json.dumps({"parts": ["a"], "truncated": False})); sys.exit(3)',
    'print(json.dumps({"parts": ["' + 'x' * 400 + '"], "truncated": False}))',
], ids=['not-json', 'not-text', 'no-flag', 'exit-code', 'over-the-cap'])
def test_any_failure_of_the_child_is_one_code_with_nothing_of_the_file(tmp_path, monkeypatch, printed):
    stub(tmp_path, monkeypatch, f'import json, sys\n{printed}\n')
    monkeypatch.setattr(extraction, 'SOURCE_REPORT_LIMIT', 300)
    with pytest.raises(DomainError) as failed:
        extraction.read_source(tmp_path / 'any.txt', 'text')
    assert failed.value.code == 'source_extraction_failed' and not failed.value.params


def test_a_file_too_long_for_any_draft_is_refused_and_never_cut_silently(tmp_path, monkeypatch):
    stub(tmp_path, monkeypatch, 'import json\nprint(json.dumps({"parts": [], "truncated": True}))\n')
    with pytest.raises(DomainError) as refused:
        extraction.read_source(tmp_path / 'thesis.docx', 'docx')
    assert refused.value.code == 'generation_limit'


def test_the_reader_stops_at_its_cap_and_says_so(tmp_path, monkeypatch):
    # The reader's own functions, its cap brought down to a few paragraphs (its main is never run here: it sets limits).
    from processors import source_reader
    path = tmp_path / 'long.docx'
    path.write_bytes(thesis_docx())
    whole = source_reader.read_docx(path)
    assert not whole.truncated and len(whole.blocks) == 8
    monkeypatch.setattr(source_reader, 'READ_CHARS', len(whole.blocks[0]) + len(whole.blocks[1]) + 2)
    cut = source_reader.read_docx(path)
    assert cut.truncated and cut.blocks == whole.blocks[:2]
    text = tmp_path / 'long.txt'
    text.write_bytes(b'Bir. ' * 100)
    monkeypatch.setattr(source_reader.source_text, 'MAX_TEXT_BYTES', 100)
    assert source_reader.read_text(text).truncated


def test_an_unknown_kind_is_never_read(tmp_path, monkeypatch):
    stub(tmp_path, monkeypatch, 'raise SystemExit("must not run")\n')
    for kind in ('pdf', 'image', 'pptx', ''):
        with pytest.raises(DomainError) as failed:
            extraction.read_source(tmp_path / 'any', kind)
        assert failed.value.code == 'source_extraction_failed' and not failed.value.params
