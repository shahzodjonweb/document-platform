"""Document scan PDF layout: real A4, uniform fitting, complete visible content."""
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader
from pypdf.generic import ContentStream
from reportlab.lib.pagesizes import A4, letter

from processors import execute, normalize_parameters
from processors import document_scan


FONT = Path(__file__).resolve().parents[1] / 'processors/assets/fonts/NotoSans-Regular.ttf'
# A cropped and cleaned sheet sits inside a scanner app's white margin:
# 2.5% of the short A4 side, the same in portrait and landscape.
SCAN_MARGIN = .025 * min(A4)


def _picture(size):
    image = Image.new('RGB', size, (245, 247, 249))
    draw = ImageDraw.Draw(image)
    for position, color in (((0, 0), (164, 29, 37)),
                            ((size[0] - 20, 0), (15, 91, 150)),
                            ((0, size[1] - 20), (24, 134, 61)),
                            ((size[0] - 20, size[1] - 20), (125, 39, 134))):
        left, top = position
        draw.rectangle((left, top, left + 19, top + 19), fill=color)
    draw.line((25, 25, size[0] - 26, size[1] - 26), fill=(36, 48, 65), width=3)
    return image


def _convert(tmp_path, monkeypatch, sizes, parameters=None, detected=None):
    if detected is None:
        detected = [True] * len(sizes)
    calls = []
    images = [_picture(size) for size in sizes]
    paths = []
    for index, image in enumerate(images):
        path = tmp_path / ('source-%02d.png' % index)
        image.save(path)
        paths.append(path)

    def prepared(image, *, auto_crop=True, enhance_text=True, render_long_edge=None):
        is_document = detected[len(calls)]
        calls.append((auto_crop, enhance_text))
        # Layout tests receive an already scanned/rectified image; detector and
        # geometry quality have separate acceptance tests. All its pixels must
        # survive the PDF placement without another crop or a distorted scale.
        return image.copy(), {'document_detected': is_document,
            'cropped': is_document and auto_crop, 'enhanced': is_document and enhance_text,
            'rectified': is_document and auto_crop}

    monkeypatch.setattr(document_scan, 'prepare_image', prepared)
    result = execute('pdf.images_to_pdf', paths, parameters, tmp_path / 'out')
    return result, PdfReader(result['artifacts'][0]['path']), images, calls


def _placement(reader, page):
    matrices = [tuple(float(value) for value in values)
        for values, operator in ContentStream(page.get_contents(), reader).operations
        if operator == b'cm']
    return matrices[-1]


def _assert_uniform_complete_fit(reader, page, image, margin=0):
    width, height = float(page.mediabox.width), float(page.mediabox.height)
    placed_width, skew_y, skew_x, placed_height, left, bottom = _placement(reader, page)
    assert skew_y == skew_x == 0
    assert placed_width / image.width == pytest.approx(placed_height / image.height, rel=1e-6)
    assert left == pytest.approx((width - placed_width) / 2, abs=1e-4)
    assert bottom == pytest.approx((height - placed_height) / 2, abs=1e-4)
    assert left >= margin - 1e-4 and bottom >= margin - 1e-4
    assert left + placed_width <= width - margin + 1e-4
    assert bottom + placed_height <= height - margin + 1e-4
    assert (placed_width == pytest.approx(width - 2 * margin, abs=1e-4)
            or placed_height == pytest.approx(height - 2 * margin, abs=1e-4)), 'Only aspect-required paper padding is permitted'
    embedded = page.images[0].image.convert('RGB')
    assert embedded.size == image.size and embedded.tobytes() == image.tobytes(), 'Every visible source pixel must remain embedded'
    return [left, bottom, placed_width, placed_height]


@pytest.mark.parametrize('size,expected', [((700, 990), A4), ((990, 700), tuple(reversed(A4)))])
def test_default_detected_scan_has_exact_iso_a4_and_only_the_scan_margin(tmp_path, monkeypatch, size, expected):
    result, reader, images, calls = _convert(tmp_path, monkeypatch, [size])
    page = reader.pages[0]
    assert (float(page.mediabox.width), float(page.mediabox.height)) == pytest.approx(expected, abs=1e-4)
    placement = _assert_uniform_complete_fit(reader, page, images[0], SCAN_MARGIN)
    # 700x990 is A4-shaped: the margin is exact on the short side, and the long
    # side only gains what an equal inset takes from the aspect ratio.
    assert min(placement[:2]) == pytest.approx(SCAN_MARGIN, abs=1e-4)
    assert max(placement[:2]) < 1.5 * SCAN_MARGIN
    assert calls == [(True, True)]
    processing = result['metadata']['image_processing']
    assert processing['pages'][0]['rectified'] is True
    layout = processing['layouts'][0]
    assert layout['requested_paper_size'] == 'fit' and layout['effective_paper_size'] == 'A4'
    assert layout['automatic_a4'] is True
    assert layout['scan_margin_points'] == pytest.approx(SCAN_MARGIN)
    assert layout['page_size_points'] == pytest.approx(expected)
    assert layout['image_placement_points'] == pytest.approx(placement, abs=1e-4)


def test_crop_without_cleanup_keeps_the_exact_a4_fit(tmp_path, monkeypatch):
    # The margin belongs to a cleaned scan; a crop-only page stays edge to edge.
    result, reader, images, calls = _convert(tmp_path, monkeypatch, [(700, 990)], {'enhance_text': False})
    page = reader.pages[0]
    assert (float(page.mediabox.width), float(page.mediabox.height)) == pytest.approx(A4, abs=1e-4)
    placement = _assert_uniform_complete_fit(reader, page, images[0])
    assert min(placement[:2]) == pytest.approx(0, abs=1e-4)
    assert calls == [(True, False)]
    layout = result['metadata']['image_processing']['layouts'][0]
    assert layout['automatic_a4'] is True and layout['scan_margin_points'] == 0


@pytest.mark.parametrize('size', [(600, 1000), (1000, 600)])
def test_a4_scan_fits_an_observed_non_a4_rectangle_without_stretching_or_clipping(tmp_path, monkeypatch, size):
    _, reader, images, _ = _convert(tmp_path, monkeypatch, [size])
    page = reader.pages[0]
    expected = A4 if size[0] < size[1] else tuple(reversed(A4))
    assert (float(page.mediabox.width), float(page.mediabox.height)) == pytest.approx(expected, abs=1e-4)
    placement = _assert_uniform_complete_fit(reader, page, images[0], SCAN_MARGIN)
    assert min(placement[:2]) == pytest.approx(SCAN_MARGIN, abs=1e-4)
    assert max(placement[:2]) > SCAN_MARGIN + 1, 'A4 aspect padding preserves the whole observed document'


def test_auto_crop_off_keeps_detected_document_photo_fit_behavior(tmp_path, monkeypatch):
    result, reader, images, calls = _convert(tmp_path, monkeypatch, [(600, 1000)], {'auto_crop': False})
    page = reader.pages[0]
    assert (float(page.mediabox.width), float(page.mediabox.height)) == pytest.approx((505.2, 842), abs=1e-4)
    _assert_uniform_complete_fit(reader, page, images[0])
    assert calls == [(False, True)]
    assert result['metadata']['image_processing']['layouts'][0]['effective_paper_size'] == 'fit'
    assert result['metadata']['image_processing']['layouts'][0]['automatic_a4'] is False


def test_ordinary_photo_default_keeps_native_aspect_and_all_pixels(tmp_path, monkeypatch):
    result, reader, images, calls = _convert(tmp_path, monkeypatch, [(1000, 600)], detected=[False])
    page = reader.pages[0]
    assert (float(page.mediabox.width), float(page.mediabox.height)) == pytest.approx((842, 505.2), abs=1e-4)
    _assert_uniform_complete_fit(reader, page, images[0])
    assert calls == [(True, True)]
    assert result['metadata']['image_processing']['layouts'][0]['effective_paper_size'] == 'fit'


def test_mixed_batch_resolves_scan_a4_and_photo_fit_independently(tmp_path, monkeypatch):
    result, reader, images, _ = _convert(tmp_path, monkeypatch, [(700, 990), (1000, 600)], detected=[True, False])
    assert len(reader.pages) == 2
    assert (float(reader.pages[0].mediabox.width), float(reader.pages[0].mediabox.height)) == pytest.approx(A4, abs=1e-4)
    assert (float(reader.pages[1].mediabox.width), float(reader.pages[1].mediabox.height)) == pytest.approx((842, 505.2), abs=1e-4)
    for page, image, margin in zip(reader.pages, images, (SCAN_MARGIN, 0)):
        _assert_uniform_complete_fit(reader, page, image, margin)
    layouts = result['metadata']['image_processing']['layouts']
    assert [layout['effective_paper_size'] for layout in layouts] == ['A4', 'fit']
    assert [layout['scan_margin_points'] for layout in layouts] == pytest.approx([SCAN_MARGIN, 0])
    assert result['metadata']['image_processing']['document_pages'] == 1


@pytest.mark.parametrize('parameters,expected', [
    ({'paper_size': 'Letter', 'orientation': 'landscape', 'margin': 12}, tuple(reversed(letter))),
    ({'paper_size': 'original', 'margin': 18}, (636, 1036)),
    ({'paper_size': 'A4', 'orientation': 'landscape', 'margin': 24}, tuple(reversed(A4))),
])
def test_explicit_paper_and_layout_choices_remain_honored_for_detected_documents(tmp_path, monkeypatch, parameters, expected):
    result, reader, images, _ = _convert(tmp_path, monkeypatch, [(600, 1000)], parameters)
    page = reader.pages[0]
    assert (float(page.mediabox.width), float(page.mediabox.height)) == pytest.approx(expected, abs=1e-4)
    _assert_uniform_complete_fit(reader, page, images[0], parameters['margin'])
    layout = result['metadata']['image_processing']['layouts'][0]
    assert layout['effective_paper_size'] == parameters['paper_size']
    assert layout['automatic_a4'] is False and layout['scan_margin_points'] == 0


def test_explicit_fit_orientation_and_margin_are_preserved_on_automatic_a4(tmp_path, monkeypatch):
    result, reader, images, _ = _convert(tmp_path, monkeypatch, [(600, 1000)], {'orientation': 'landscape', 'margin': 12})
    page = reader.pages[0]
    assert (float(page.mediabox.width), float(page.mediabox.height)) == pytest.approx(tuple(reversed(A4)), abs=1e-4)
    _assert_uniform_complete_fit(reader, page, images[0], margin=12)
    layout = result['metadata']['image_processing']['layouts'][0]
    assert layout['automatic_a4'] is True
    assert layout['scan_margin_points'] == 0, 'A chosen margin replaces the scan margin, never adds to it'


def test_real_written_full_frame_document_default_converts_to_a4(tmp_path):
    parameters = normalize_parameters('pdf.images_to_pdf', {})
    assert parameters['auto_crop'] is parameters['enhance_text'] is True
    image = Image.new('RGB', (700, 990), (247, 247, 244))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(FONT), 28)
    draw.text((38, 35), 'GENERIC DOCUMENT SAMPLE', font=font, fill=(30, 30, 30))
    for row, top in enumerate(range(150, 850, 100)):
        draw.text((40, top), 'Sample row %02d: visible printed entry 2741' % row,
                  font=font, fill=(38, 38, 38))
    draw.text((40, 900), 'BLUE NOTE: retain this writing', font=font, fill=(20, 55, 145))
    source = tmp_path / 'document.png'
    image.save(source)
    result = execute('pdf.images_to_pdf', [source], {}, tmp_path / 'out')
    reader = PdfReader(result['artifacts'][0]['path'])
    page = reader.pages[0]
    assert (float(page.mediabox.width), float(page.mediabox.height)) == pytest.approx(A4, abs=1e-4)
    processing = result['metadata']['image_processing']
    assert processing['pages'][0]['document_detected'] is True
    assert processing['pages'][0]['enhanced'] is True
    assert processing['layouts'][0]['effective_paper_size'] == 'A4'
    placement = _placement(reader, page)
    assert placement[4:] == pytest.approx((0, 0), abs=1e-4)
