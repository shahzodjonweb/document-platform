"""Document scanning in images-to-PDF: real engine, real PDFs and the real sandbox.

Every photo is scanned; only a written page is changed. A scanned page is
printed on the sheet it matched; anything else is embedded as uploaded. The
scanner's own decisions are covered in test_document_scanner.py; the adapter
around it (size limits, fallbacks) is checked here without the models.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw
from pypdf import PdfReader
from reportlab.lib.pagesizes import letter

from processors import ProcessorError, execute, normalize_parameters
from processors.sandbox import execute_sandbox
from tests.scan_fixtures import (blue_pixels, full_frame_scan, noise_photo, ordinary_photo, perspective_paper,
                                 scanner_models)

DEFAULTS = {'paper_size': 'fit', 'orientation': 'auto', 'margin': 0}
LETTER_RATIO = 11 / 8.5


def _embedded_image(result, page=0):
    reader = PdfReader(result['artifacts'][0]['path'])
    image = reader.pages[page].images[0].image.convert('RGB')
    image.load()
    return image


def _page_size(result, page=0):
    box = PdfReader(result['artifacts'][0]['path']).pages[page].mediabox
    return float(box.width), float(box.height)


def test_defaults_have_only_the_layout_and_no_scan_switches():
    assert normalize_parameters('pdf.images_to_pdf', {}) == DEFAULTS


@pytest.mark.parametrize('legacy', [
    {'auto_crop': False}, {'enhance_text': False}, {'auto_crop': True, 'enhance_text': True},
    # Whatever an old client stored is dropped, never validated.
    {'auto_crop': 'false', 'enhance_text': None},
])
def test_retired_scan_switches_are_dropped_silently(legacy):
    assert normalize_parameters('pdf.images_to_pdf', legacy) == DEFAULTS
    assert normalize_parameters('pdf.images_to_pdf', {**legacy, 'paper_size': 'Letter'}) == {**DEFAULTS, 'paper_size': 'Letter'}


@pytest.mark.parametrize('feature,parameters', [
    ('pdf.images_to_pdf', {'auto_crop_page': True}),
    ('pdf.images_to_pdf', {'enhance': False}),
    ('pdf.images_to_pdf', {'paper_size': 'Legal'}),
    ('pdf.compress', {'auto_crop': False}),
])
def test_other_unknown_keys_and_values_are_still_rejected(feature, parameters):
    with pytest.raises(ProcessorError) as error:
        normalize_parameters(feature, parameters)
    assert error.value.code == 'invalid_parameters'


@pytest.mark.parametrize('parameters', [{}, {'auto_crop': False, 'enhance_text': False}])
def test_default_fitted_pdf_has_no_added_border_and_keeps_sensible_print_size(tmp_path, scanner_models, parameters):
    import pypdfium2 as pdfium
    from contextlib import closing
    source = tmp_path / 'photo.png'
    color = (47, 63, 81)
    Image.new('RGB', (500, 900), color).save(source)
    result = execute_sandbox('pdf.images_to_pdf', [source], parameters, tmp_path / 'out')
    page = PdfReader(result['artifacts'][0]['path']).pages[0]
    width, height = float(page.mediabox.width), float(page.mediabox.height)
    assert height == pytest.approx(842, abs=.001)
    assert width / height == pytest.approx(500 / 900, abs=.00001)
    assert page.images[0].image.size == (500, 900), 'Fit changes print dimensions, not image resolution'
    with pdfium.PdfDocument(result['artifacts'][0]['path']) as document, closing(document[0]) as rendered_page:
        bitmap = rendered_page.render(scale=.5)
        try:
            rendered = bitmap.to_pil().convert('RGB')
            for position in ((2, 2), (rendered.width - 3, 2), (2, rendered.height - 3),
                             (rendered.width - 3, rendered.height - 3)):
                assert rendered.getpixel(position) == color, 'No white canvas should surround the image'
        finally:
            bitmap.close()


@pytest.mark.parametrize('parameters,expected_size', [
    ({'paper_size': 'A4', 'orientation': 'auto', 'margin': 24}, (595.275590551, 841.88976378)),
    ({'paper_size': 'Letter', 'orientation': 'landscape', 'margin': 12}, (792, 612)),
    ({'paper_size': 'original', 'orientation': 'auto', 'margin': 18}, (536, 936)),
    ({'paper_size': 'fit', 'orientation': 'auto', 'margin': 12}, (500 / 900 * 842 + 24, 866)),
    ({'paper_size': 'fit', 'orientation': 'landscape', 'margin': 0}, (842, 500 / 900 * 842)),
])
def test_photo_keeps_every_explicit_layout_and_all_its_pixels(tmp_path, scanner_models, parameters, expected_size):
    source = tmp_path / 'photo.png'
    original = Image.new('RGB', (500, 900), (47, 63, 81))
    original.save(source)
    result = execute('pdf.images_to_pdf', [source], parameters, tmp_path / 'out')
    page = PdfReader(result['artifacts'][0]['path']).pages[0]
    assert (float(page.mediabox.width), float(page.mediabox.height)) == pytest.approx(expected_size, abs=.001)
    assert np.array_equal(np.asarray(page.images[0].image.convert('RGB')), np.asarray(original))
    normalized = normalize_parameters('pdf.images_to_pdf', parameters)
    assert all(normalized[key] == value for key, value in parameters.items())


def test_default_scan_prints_the_document_on_its_matched_sheet(tmp_path, scanner_models):
    source = tmp_path / 'invoice.png'
    perspective_paper().save(source)
    result = execute('pdf.images_to_pdf', [source], {}, tmp_path / 'out')
    # The invoice measures 1.26: Letter, in its own (portrait) orientation.
    assert _page_size(result) == pytest.approx(letter, abs=.001)
    embedded = _embedded_image(result)
    assert embedded.height / embedded.width == pytest.approx(LETTER_RATIO, rel=.005)
    assert embedded.height > 900, 'The print is rebuilt larger than it was photographed'
    assert blue_pixels(embedded).sum() > 3000
    layout = result['metadata']['image_processing']['layouts'][0]
    assert layout['requested_paper_size'] == 'fit' and layout['effective_paper_size'] == 'Letter'
    assert layout['image_encoding'] == 'jpeg', 'A scanned page is a JPEG stream, not a lossless photo of paper'
    assert result['metadata']['image_processing']['pages'] == [{'document_detected': True, 'sheet': 'Letter'}]


def test_original_paper_prints_a_scanned_page_on_its_sheet_not_one_point_per_pixel(tmp_path, scanner_models):
    source = tmp_path / 'invoice.png'
    perspective_paper().save(source)
    result = execute('pdf.images_to_pdf', [source], {'paper_size': 'original'}, tmp_path / 'out')
    # A 1358-pixel scan would otherwise become a page almost 19 inches long.
    assert _page_size(result) == pytest.approx(letter, abs=.001)
    assert result['metadata']['image_processing']['layouts'][0]['effective_paper_size'] == 'Letter'


def test_pdf_honors_exif_before_document_analysis_and_original_sizing(tmp_path, scanner_models):
    upright = full_frame_scan()
    stored = upright.transpose(Image.Transpose.ROTATE_90)
    exif = Image.Exif()
    exif[274] = 6
    source = tmp_path / 'rotated.jpg'
    stored.save(source, exif=exif, quality=98)
    result = execute('pdf.images_to_pdf', [source], {'paper_size': 'original', 'margin': 0}, tmp_path / 'out')
    # Its outline is the inner table, so the page is kept whole, as uploaded.
    assert result['metadata']['image_processing']['document_pages'] == 0
    embedded = _embedded_image(result)
    assert embedded.size == upright.size
    assert _page_size(result) == upright.size
    assert np.mean(np.abs(np.asarray(embedded).astype(np.int16) - np.asarray(upright))) < 2.5


def test_default_scan_uses_exif_upright_document_orientation(tmp_path, scanner_models):
    upright = perspective_paper()
    stored = upright.transpose(Image.Transpose.ROTATE_90)
    exif = Image.Exif()
    exif[274] = 6
    source = tmp_path / 'rotated-document.jpg'
    stored.save(source, exif=exif, quality=98)
    result = execute('pdf.images_to_pdf', [source], {}, tmp_path / 'out')
    embedded = _embedded_image(result)
    assert embedded.height > embedded.width
    assert _page_size(result) == pytest.approx(letter, abs=.001)
    assert result['metadata']['image_processing']['document_pages'] == 1
    assert blue_pixels(embedded).sum() > 3000


def test_pdf_flattens_transparency_to_white_before_scanning(tmp_path, scanner_models):
    source = tmp_path / 'transparent.png'
    image = Image.new('RGBA', (360, 240), (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((110, 70, 250, 170), fill=(20, 55, 145, 255))
    image.save(source)
    result = execute('pdf.images_to_pdf', [source], {'paper_size': 'original'}, tmp_path / 'out')
    embedded = _embedded_image(result)
    assert embedded.getpixel((5, 5)) == (255, 255, 255)
    assert embedded.getpixel((180, 120)) == (20, 55, 145)
    assert embedded.size == image.size


def test_real_sandbox_default_scan_preserves_page_order_and_reports_safe_metadata(tmp_path, scanner_models):
    paper, photo = tmp_path / 'paper.png', tmp_path / 'photo.png'
    perspective_paper(shaded=True).save(paper)
    ordinary_photo().save(photo)
    result = execute_sandbox('pdf.images_to_pdf', [paper, photo], {}, tmp_path / 'out')
    assert result['artifacts'][0]['page_count'] == 2
    assert result['actual_page_units'] == 2
    first, second = _embedded_image(result), _embedded_image(result, 1)
    assert first.height / first.width == pytest.approx(LETTER_RATIO, rel=.005)
    assert _page_size(result) == pytest.approx(letter, abs=.001)
    assert second.size == (720, 900)
    assert np.array_equal(np.asarray(second), np.asarray(ordinary_photo())), 'The photo is untouched'
    assert _page_size(result, 1) == pytest.approx((720 / 900 * 842, 842), abs=.001)
    metadata = result['metadata']['image_processing']
    assert set(metadata) == {'pages', 'layouts', 'document_pages', 'scan_failures'}
    assert metadata['scan_failures'] == 0
    assert metadata['document_pages'] == 1
    assert metadata['pages'] == [{'document_detected': True, 'sheet': 'Letter'},
                                 {'document_detected': False, 'sheet': None}]
    assert [layout['effective_paper_size'] for layout in metadata['layouts']] == ['Letter', 'fit']


def test_large_photo_is_reduced_before_scanning_and_completes_in_real_sandbox(tmp_path, scanner_models):
    # 33.8 MP is below the 40 MP input cap. The scanner sees it at 3000 px.
    source = tmp_path / 'large-paper.jpg'
    picture = perspective_paper(shaded=True).resize((5200, 6500), Image.Resampling.LANCZOS)
    picture.save(source, quality=93)
    picture.close()
    result = execute_sandbox('pdf.images_to_pdf', [source], {}, tmp_path / 'out')
    embedded = _embedded_image(result)
    assert result['metadata']['image_processing']['document_pages'] == 1
    assert embedded.height / embedded.width == pytest.approx(LETTER_RATIO, rel=.005)
    assert 2000 < max(embedded.size) <= 3000
    assert blue_pixels(embedded).sum() > 10_000


def test_untouched_jpeg_upload_is_embedded_as_its_own_pixels_without_metadata(tmp_path, scanner_models):
    rng = np.random.default_rng(7)
    photo = Image.fromarray(rng.integers(0, 255, (300, 400, 3), dtype=np.uint8))
    source = tmp_path / 'photo.jpg'
    photo.save(source, quality=85, comment=b'CAMERA SERIAL 12345', dpi=(300, 300))
    result = execute('pdf.images_to_pdf', [source], {}, tmp_path / 'out')
    assert result['metadata']['image_processing']['document_pages'] == 0
    pdf = Path(result['artifacts'][0]['path']).read_bytes()
    assert b'CAMERA SERIAL' not in pdf, 'Upload comments never reach the PDF'
    assert result['metadata']['image_processing']['layouts'][0]['image_encoding'] == 'jpeg'
    assert result['artifacts'][0]['size_bytes'] < source.stat().st_size * 1.1, 'Grainy photos are not inflated'
    # The embedded DCT stream is the upload's own, minus its metadata segments.
    stream = PdfReader(result['artifacts'][0]['path']).pages[0].images[0].indirect_reference.get_object().get_data()
    data = source.read_bytes()
    assert stream.endswith(data[data.index(b'\xff\xda'):]), "The upload's own entropy-coded scan"
    with Image.open(source) as original, Image.open(io.BytesIO(stream)) as embedded:
        assert embedded.convert('RGB').tobytes() == original.convert('RGB').tobytes(), 'Not a document: every pixel kept'
    assert b'\xff\xfe' not in stream[:4096], 'No COM segment survives in the stream header'


def test_grainy_png_photo_is_a_metadata_free_jpeg_stream(tmp_path, scanner_models):
    photo = noise_photo()
    source = tmp_path / 'photo.png'
    photo.save(source)
    result = execute('pdf.images_to_pdf', [source], {}, tmp_path / 'out')
    assert result['metadata']['image_processing']['layouts'][0]['image_encoding'] == 'jpeg'
    assert _embedded_image(result).size == photo.size


def test_original_paper_holds_an_oversize_panorama_to_the_page_limit(tmp_path, scanner_models):
    source = tmp_path / 'wide.png'
    Image.new('RGB', (15000, 300), (200, 200, 200)).save(source)
    result = execute('pdf.images_to_pdf', [source], {'paper_size': 'original', 'margin': 12}, tmp_path / 'out')
    page = PdfReader(result['artifacts'][0]['path']).pages[0]
    assert float(page.mediabox.width) == pytest.approx(14400, abs=.001)
    assert float(page.mediabox.height) == pytest.approx(300 * (14400 - 24) / 15000 + 24, abs=.01)


def test_sixteen_bit_png_keeps_its_tones(tmp_path, scanner_models):
    samples = np.linspace(0, 65535, 400, dtype=np.uint16)[None, :].repeat(300, 0)
    source = tmp_path / 'gray16.png'
    Image.fromarray(samples).save(source)
    result = execute('pdf.images_to_pdf', [source], {}, tmp_path / 'out')
    tones = np.asarray(_embedded_image(result).convert('L'))
    assert tones[:, :10].mean() < 20 and tones[:, -10:].mean() > 235
    assert 100 < tones.mean() < 150, 'A 16-bit gradient is rescaled, not clipped to white'


def test_missing_model_fails_the_job_as_a_deployment_fault(tmp_path, monkeypatch):
    # The child reads SCANNER_MODELS; text_sr_x3.onnx alone is in the package.
    # The job fails like any engine fault, instead of quietly skipping the scan.
    monkeypatch.setenv('SCANNER_MODELS', str(tmp_path / 'no-models'))
    source = tmp_path / 'photo.png'
    ordinary_photo().save(source)
    with pytest.raises(ProcessorError) as error:
        execute_sandbox('pdf.images_to_pdf', [source], {}, tmp_path / 'out')
    assert error.value.code == 'processing_failed'


# --- The adapter around the scanner, without the models ---------------------

class FakeScan:
    """Stands in for pipeline.scan(): records what it was given, returns ``result(bgr)``."""

    def __init__(self):
        self.calls, self.loads = [], 0
        self.result = lambda bgr: {'found': False, 'page': None, 'sheet': None}

    def __call__(self, bgr, paper):
        self.calls.append((bgr.copy(), paper))
        return self.result(bgr)


@pytest.fixture
def fake_scanner(monkeypatch):
    """processors.scanner with load_models() and scan() replaced."""
    import processors.scanner as scanner
    fake = FakeScan()

    def load():
        fake.loads += 1
    monkeypatch.setattr(scanner, 'load_models', load)
    monkeypatch.setattr(scanner, 'scan', fake)
    return scanner, fake


def test_tiny_images_are_never_scanned_and_never_load_the_models(fake_scanner):
    scanner, fake = fake_scanner
    for size in ((50, 30), (95, 400), (400, 95)):
        image = Image.new('RGB', size, 'blue')
        assert scanner.scan_photo(image) == (image, {'document_detected': False, 'sheet': None})
    assert fake.calls == [] and fake.loads == 0


@pytest.mark.parametrize('size,expected', [
    ((3000, 4000), (2250, 3000)),  # a 12 MP phone photo (width, height)
    ((4000, 3000), (3000, 2250)),
    ((3001, 1000), (3000, 1000)),
])
def test_photos_longer_than_3000_px_are_reduced_before_scanning(fake_scanner, size, expected):
    scanner, fake = fake_scanner
    image = noise_photo(size=size)
    result, outcome = scanner.scan_photo(image)
    assert result is image and outcome['document_detected'] is False and fake.loads == 1
    (seen, paper), = fake.calls
    assert seen.shape[1::-1] == expected and paper == 'auto'
    reduced = cv2.resize(np.asarray(image)[:, :, ::-1], expected, interpolation=cv2.INTER_AREA)
    assert np.array_equal(seen, reduced), 'Reduced with INTER_AREA'


@pytest.mark.parametrize('size', [(3000, 2000), (720, 900), (96, 96)])
def test_photos_up_to_3000_px_reach_the_scanner_unchanged_as_bgr(fake_scanner, size):
    scanner, fake = fake_scanner
    image = noise_photo(size=size)
    scanner.scan_photo(image, 'Letter')
    (seen, paper), = fake.calls
    assert paper == 'Letter'
    assert np.array_equal(seen, np.asarray(image)[:, :, ::-1])


def test_a_found_page_comes_back_as_rgb_with_its_sheet(fake_scanner):
    scanner, fake = fake_scanner
    page = np.zeros((40, 30, 3), np.uint8)
    page[:, :, 0] = 200  # blue in BGR
    fake.result = lambda bgr: {'found': True, 'page': page, 'sheet': 'Legal'}
    result, outcome = scanner.scan_photo(Image.new('RGB', (300, 400), 'white'))
    assert outcome == {'document_detected': True, 'sheet': 'Legal'}
    assert result.mode == 'RGB' and result.size == (30, 40) and result.getpixel((0, 0)) == (0, 0, 200)


@pytest.mark.parametrize('error,name', [('cv2', 'error'), ('value', 'ValueError'), ('onnxruntime', 'Fail'),
                                        ('memory', 'MemoryError')])
def test_a_fault_inside_the_scan_keeps_that_photo_as_uploaded(fake_scanner, caplog, error, name):
    from onnxruntime.capi.onnxruntime_pybind11_state import Fail
    scanner, fake = fake_scanner

    def broken(bgr):
        if error == 'cv2':
            cv2.resize(np.zeros((0, 0), np.uint8), (1, 1))
        if error == 'memory':
            raise MemoryError
        raise ValueError('bad page') if error == 'value' else Fail('allocation failed')
    fake.result = broken
    image = Image.new('RGB', (300, 400), 'white')
    with caplog.at_level(logging.WARNING, logger='processors.scanner'):
        assert scanner.scan_photo(image) == (image, {'document_detected': False, 'sheet': None, 'scan_error': name})
    assert 'Document scan failed' in caplog.text


def test_a_fault_while_preparing_the_photo_also_keeps_it_as_uploaded(fake_scanner, monkeypatch):
    scanner, fake = fake_scanner

    def no_memory(*args, **kwargs):
        raise MemoryError
    monkeypatch.setattr(scanner.cv2, 'resize', no_memory)
    image = noise_photo(size=(3200, 2400))
    assert scanner.scan_photo(image) == (image, {'document_detected': False, 'sheet': None,
                                                 'scan_error': 'MemoryError'})
    assert fake.calls == []


def test_failed_scans_are_counted_in_the_job_metadata(fake_scanner, tmp_path):
    from processors import engine
    scanner, fake = fake_scanner
    fake.result = lambda bgr: (_ for _ in ()).throw(MemoryError())
    sources = []
    for index in range(2):
        sources.append(tmp_path / f'{index}.png')
        noise_photo(size=(300, 400)).save(sources[-1])
    result = engine.execute('pdf.images_to_pdf', sources, {}, tmp_path / 'out')
    processing = result['metadata']['image_processing']
    assert processing['scan_failures'] == 2 and processing['document_pages'] == 0
    assert processing['pages'][0] == {'document_detected': False, 'sheet': None, 'scan_error': 'MemoryError'}


def test_a_missing_model_is_not_swallowed_by_the_fallback(monkeypatch):
    import processors.scanner as scanner

    def missing():
        raise FileNotFoundError('Scanner model uvdoc.onnx is missing')
    monkeypatch.setattr(scanner, 'load_models', missing)
    with pytest.raises(FileNotFoundError):
        scanner.scan_photo(Image.new('RGB', (300, 400), 'white'))



@pytest.mark.parametrize('kind', ['flat', 'screenshot'])
def test_unscanned_jpeg_that_deflates_well_is_still_embedded_as_its_own_stream(fake_scanner, tmp_path, kind):
    # Re-encoding such a JPEG losslessly kept its pixels at up to 5x its bytes.
    picture = Image.new('RGB', (600, 800), (238, 238, 238))
    if kind == 'screenshot':
        draw = ImageDraw.Draw(picture)
        for row in range(40, 760, 30):
            draw.rectangle((40, row, 560, row + 12), fill=(30, 60, 200) if row % 90 == 40 else (40, 40, 40))
    source = tmp_path / 'upload.jpg'
    picture.save(source, quality=90, comment=b'EDITOR NOTE')
    result = execute('pdf.images_to_pdf', [source], {}, tmp_path / 'out')
    assert result['metadata']['image_processing']['layouts'][0]['image_encoding'] == 'jpeg'
    image = PdfReader(result['artifacts'][0]['path']).pages[0].images[0].indirect_reference.get_object()
    assert image['/Filter'] == ['/DCTDecode']
    data = source.read_bytes()
    stream = image.get_data()
    assert stream.endswith(data[data.index(b'\xff\xda'):]), "The upload's own entropy-coded scan"
    assert b'EDITOR NOTE' not in stream
    assert result['artifacts'][0]['size_bytes'] < len(data) + 4096


def test_only_the_scanner_child_gets_the_larger_address_space_and_cpu_budget(monkeypatch):
    import importlib
    import resource
    from processors import sandbox
    child = importlib.import_module('processors.__main__')
    assert sandbox.child_limits('pdf.images_to_pdf', 130) == {'cpu_seconds': 250, 'address_space_mb': 3072}
    assert sandbox.child_limits('pdf.merge', 90) == {'cpu_seconds': 85, 'address_space_mb': 2048}
    applied = {}
    monkeypatch.setattr(child.sys, 'platform', 'linux')
    monkeypatch.setattr(resource, 'setrlimit', lambda name, value: applied.__setitem__(name, value))
    monkeypatch.setattr(child.os, 'umask', lambda mask: 0)
    for address_space, cpu, expected in (('3072', '250', (3 << 30, 250)), (None, None, (2 << 30, 85)),
                                         ('99999', '1', (3 << 30, 85)), ('1', 'many', (2 << 30, 85))):
        for name, value in (('PDFMASTER_ADDRESS_SPACE_MB', address_space), ('PDFMASTER_CPU_SECONDS', cpu)):
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        child.apply_limits()
        assert applied[resource.RLIMIT_AS] == (expected[0],) * 2
        assert applied[resource.RLIMIT_CPU] == (expected[1], expected[1] + 5)
