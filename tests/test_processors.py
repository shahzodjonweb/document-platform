"""Acceptance fixtures reopen actual serialized files; engines are never mocked."""
import io
from contextlib import closing
import json
import zipfile
from pathlib import Path
import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas
from processors import ProcessorError, execute, inspect_file, normalize_parameters, parse_pages
from processors.sandbox import execute_sandbox, inspect_file_sandbox


def pdf(path, labels=('first', 'second', 'third')):
    canvas = Canvas(str(path), pageCompression=0, invariant=1)
    for i, label in enumerate(labels):
        canvas.setPageSize((400 + i * 10, 600))
        canvas.setFont('Helvetica', 18)
        canvas.drawString(30, 550, label)
        canvas.showPage()
    canvas.save()
    return path


def result_reader(result, i=0):
    return PdfReader(result['artifacts'][i]['path'])


def test_merge_order_dimensions_meter(tmp_path):
    a, b = pdf(tmp_path / 'a.pdf', ('alpha', 'beta')), pdf(tmp_path / 'b.pdf', ('gamma',))
    result = execute('pdf.merge', [a, b], {}, tmp_path / 'out')
    pages = result_reader(result).pages
    assert [p.extract_text().strip() for p in pages] == ['alpha', 'beta', 'gamma']
    assert [float(p.mediabox.width) for p in pages] == [400, 410, 400]
    assert result['actual_page_units'] == 3
    assert result['artifacts'][0]['page_count'] == 3
    assert not result['no_op']


@pytest.mark.parametrize(('feature', 'parameters', 'labels'), [
    ('pdf.extract_pages', {'pages': '3,1'}, ['third', 'first']),
    ('pdf.delete_pages', {'pages': '2'}, ['first', 'third']),
    ('pdf.reorder', {'order': [3, 2, 1]}, ['third', 'second', 'first'])])
def test_page_edits(feature, parameters, labels, tmp_path):
    result = execute(feature, [pdf(tmp_path / 'source.pdf')], parameters, tmp_path / 'out')
    assert [p.extract_text().strip() for p in result_reader(result).pages] == labels
    assert result['actual_page_units'] == 3


def test_split_and_rotate(tmp_path):
    source = pdf(tmp_path / 'source.pdf')
    result = execute('pdf.split', [source], {'ranges': ['1-2', '3']}, tmp_path / 'split')
    assert [a['page_count'] for a in result['artifacts']] == [2, 1]
    assert result_reader(result, 1).pages[0].extract_text().strip() == 'third'
    result = execute('pdf.rotate', [source], {'pages': '1,3', 'angle': 90}, tmp_path / 'rotate')
    assert [p.rotation for p in result_reader(result).pages] == [90, 0, 90]


@pytest.mark.parametrize('value', ['0', '4', '2-1', '1,1', '1-4', '../1', '1,', '', 'all,1', True, [1]])
def test_invalid_page_ranges(value):
    with pytest.raises(ProcessorError):
        parse_pages(value, 3)


def test_invalid_parameters_and_empty_outputs(tmp_path):
    for params in ({'output': '/tmp/escape.pdf'}, {'password': 'secret'}, {'angle': True}):
        with pytest.raises(ProcessorError):
            normalize_parameters('pdf.rotate', params)
    source = pdf(tmp_path / 'source.pdf')
    for feature, params in [('pdf.delete_pages', {'pages': 'all'}), ('pdf.reorder', {'order': [1, 1, 2]})]:
        with pytest.raises(ProcessorError):
            execute(feature, [source], params, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_magic_corrupt_and_active_pdf(tmp_path):
    assert inspect_file(pdf(tmp_path / 'data.jpg'))['mime_type'] == 'application/pdf'
    bad = tmp_path / 'bad.pdf'
    bad.write_bytes(b'%PDF-1.7\ncorrupt')
    with pytest.raises(ProcessorError) as error:
        inspect_file_sandbox(bad)
    assert error.value.code == 'invalid_pdf'
    writer = PdfWriter()
    writer.add_blank_page(width=400, height=600)
    writer.add_js('app.alert("unsafe")')
    writer.write(bad)
    with pytest.raises(ProcessorError) as error:
        inspect_file(bad)
    assert error.value.code == 'active_content_unsupported'


def test_compression_and_no_op(tmp_path):
    source = tmp_path / 'large.pdf'
    canvas = Canvas(str(source), pageCompression=0, invariant=1)
    for line in range(100):
        canvas.drawString(20, 20 + line * 7, 'A repeated line stays text after compression.')
    canvas.showPage()
    canvas.save()
    first = execute('pdf.compress', [source], {}, tmp_path / 'first')
    assert not first['no_op'] and first['metadata']['saved_bytes'] > 0
    assert 'A repeated line stays text' in result_reader(first).pages[0].extract_text()
    second = execute('pdf.compress', [first['artifacts'][0]['path']], {}, tmp_path / 'second')
    assert second['no_op'] and second['metadata']['saved_bytes'] == 0
    assert Path(second['artifacts'][0]['path']).read_bytes() == Path(first['artifacts'][0]['path']).read_bytes()


def test_images_pdf_layout_and_pixel_order(tmp_path):
    sources = []
    for i, color in enumerate(('red', 'blue')):
        path = tmp_path / f'{i}.png'
        Image.new('RGBA', (300, 150), color).save(path)
        sources.append(path)
    result = execute('pdf.images_to_pdf', sources, {'paper_size': 'A4', 'margin': 24}, tmp_path / 'out')
    pages = result_reader(result).pages
    assert len(pages) == 2 and float(pages[0].mediabox.width) > float(pages[0].mediabox.height)
    import pypdfium2 as pdfium
    with pdfium.PdfDocument(result['artifacts'][0]['path']) as doc:
        for i, expected in enumerate(((255, 0, 0), (0, 0, 255))):
            with closing(doc[i]) as page:
                bitmap = page.render(scale=0.5)
                try:
                    image = bitmap.to_pil().convert('RGB')
                    center = image.getpixel((image.width // 2, image.height // 2))
                    assert all(abs(a-b) <= 3 for a, b in zip(center, expected))
                finally:
                    bitmap.close()


@pytest.mark.parametrize('fmt', ['png', 'jpg'])
def test_pdf_images_reopenable_archive(tmp_path, fmt):
    result = execute('pdf.to_images', [pdf(tmp_path / 'source.pdf')], {'format': fmt, 'pages': '3,1', 'dpi': 72}, tmp_path / 'out')
    artifact = result['artifacts'][0]
    assert artifact['page_count'] == 2
    with zipfile.ZipFile(artifact['path']) as archive:
        assert archive.namelist() == [f'page-0003.{fmt}', f'page-0001.{fmt}']
        with Image.open(io.BytesIO(archive.read(archive.namelist()[0]))) as image:
            assert image.size == (420, 600)
            image.verify()


def test_password_roundtrip(tmp_path):
    pytest.importorskip('cryptography')
    secret = 'correct horse 2026'
    protected = execute('pdf.protect', [pdf(tmp_path / 'source.pdf')], {}, tmp_path / 'protected', secret=secret)
    path = protected['artifacts'][0]['path']
    assert inspect_file(path)['password_required']
    assert secret not in json.dumps(protected)
    with pytest.raises(ProcessorError) as error:
        execute('pdf.unlock_known', [path], {}, tmp_path / 'wrong', secret='incorrect')
    assert error.value.code == 'password_invalid'
    unlocked = execute_sandbox('pdf.unlock_known', [path], {}, tmp_path / 'unlocked', secret=secret)
    assert not result_reader(unlocked).is_encrypted
    assert result_reader(unlocked).pages[0].extract_text().strip() == 'first'


@pytest.mark.parametrize('member', ['../escape.xml', 'word/vbaProject.bin'])
def test_archive_path_and_macro_rejection(tmp_path, member):
    path = tmp_path / 'bad.docx'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('word/document.xml', '<document/>')
        archive.writestr(member, 'unsafe')
    with pytest.raises(ProcessorError) as error:
        inspect_file(path)
    assert error.value.code in ('unsafe_archive', 'active_content_unsupported')


def test_archive_expansion_bomb(tmp_path):
    path = tmp_path / 'bomb.docx'
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('word/document.xml', 'A' * 2_000_000)
    with pytest.raises(ProcessorError) as error:
        inspect_file(path)
    assert error.value.code == 'archive_limit'


def test_pixel_caps(tmp_path, monkeypatch):
    import processors.engine as engine
    source = tmp_path / 'huge.png'
    Image.new('RGB', (100, 100)).save(source)
    monkeypatch.setattr(engine, 'MAX_PIXELS', 5000)
    with pytest.raises(ProcessorError) as error:
        inspect_file(source)
    assert error.value.code == 'image_pixel_limit'


def test_child_process_artifact(tmp_path):
    source = pdf(tmp_path / 'source.pdf')
    assert inspect_file_sandbox(source)['page_count'] == 3
    result = execute_sandbox('pdf.extract_pages', [source], {'pages': '2-3'}, tmp_path / 'out')
    assert len(result_reader(result).pages) == 2
    assert result_reader(result).pages[0].extract_text().strip() == 'second'


def test_existing_output_and_input_symlink_protection(tmp_path):
    source = pdf(tmp_path / 'source.pdf')
    out = tmp_path / 'out'
    out.mkdir()
    sentinel = out / 'existing.txt'
    sentinel.write_text('keep')
    with pytest.raises(ProcessorError):
        execute('pdf.rotate', [source], {}, out)
    assert sentinel.read_text() == 'keep'
    link = tmp_path / 'link.pdf'
    link.symlink_to(source)
    with pytest.raises(ProcessorError):
        inspect_file(link)


def test_interactive_forms_fail_explicitly_instead_of_orphaning_fields(tmp_path):
    source = tmp_path / 'form.pdf'
    canvas = Canvas(str(source), pagesize=(400, 600))
    canvas.acroForm.textfield(name='customer', x=40, y=500, width=200, height=20)
    canvas.showPage()
    canvas.save()
    assert inspect_file(source)['has_forms'] is True
    with pytest.raises(ProcessorError) as error:
        execute('pdf.rotate',[source],{},tmp_path/'rotated')
    assert error.value.code == 'interactive_pdf_unsupported'
