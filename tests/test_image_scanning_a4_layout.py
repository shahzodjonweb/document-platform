"""Scanned-page PDF layout: the matched sheet, uniform fitting, complete visible content.

The scanner is replaced here by a stand-in that returns a page already
flattened to a known shape; what the scanner finds is tested in
test_document_scanner.py. Every pixel the scanner returns must reach the PDF
without another crop or a distorted scale.
"""
import numpy as np
import pytest
from PIL import Image, ImageDraw
from pypdf import PdfReader
from pypdf.generic import ContentStream
from reportlab.lib.pagesizes import A4, legal, letter

from processors import execute
import processors.scanner as scanner
from tests.scan_fixtures import photographed_shipment_form, scanner_models

SHEETS = {'A4': A4, 'Letter': letter, 'Legal': legal}


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


def _convert(tmp_path, monkeypatch, sizes, parameters=None, sheets=None):
    """Convert one picture per size; ``sheets`` holds the scanner's answer for each.

    A sheet name means the picture is a found document matched to that sheet,
    '' a document that matched no sheet, None a photo that is no document.
    """
    if sheets is None:
        sheets = ['A4'] * len(sizes)
    calls = []
    images = [_picture(size) for size in sizes]
    paths = []
    for index, image in enumerate(images):
        path = tmp_path / ('source-%02d.png' % index)
        image.save(path)
        paths.append(path)

    def scanned(image, paper='auto'):
        sheet = sheets[len(calls)]
        calls.append(paper)
        if sheet is None:
            return image, {'document_detected': False, 'sheet': None}
        return image.copy(), {'document_detected': True, 'sheet': sheet or None}

    monkeypatch.setattr(scanner, 'scan_photo', scanned)
    result = execute('pdf.images_to_pdf', paths, parameters, tmp_path / 'out')
    return result, PdfReader(result['artifacts'][0]['path']), images, calls


def _placement(reader, page):
    matrices = [tuple(float(value) for value in values)
        for values, operator in ContentStream(page.get_contents(), reader).operations
        if operator == b'cm']
    return matrices[-1]


def _assert_uniform_complete_fit(reader, page, image, margin=0, *, scanned=True):
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
    assert embedded.size == image.size, 'Every visible source pixel must remain embedded'
    if scanned:
        # A scanned page is stored as a JPEG stream (quality 88).
        difference = np.abs(np.asarray(embedded).astype(np.int16) - np.asarray(image))
        assert difference.mean() < 1.5 and np.percentile(difference, 99.9) < 40
    else:
        assert embedded.tobytes() == image.tobytes()
    return [left, bottom, placed_width, placed_height]


def _size(page):
    return float(page.mediabox.width), float(page.mediabox.height)


@pytest.mark.parametrize('sheet,size', [
    ('A4', (700, 990)), ('A4', (990, 700)),
    ('Letter', (850, 1100)), ('Letter', (1100, 850)),
    ('Legal', (850, 1400)),
])
def test_default_fit_prints_a_scanned_page_on_its_matched_sheet_without_margin(tmp_path, monkeypatch, sheet, size):
    result, reader, images, calls = _convert(tmp_path, monkeypatch, [size], sheets=[sheet])
    page = reader.pages[0]
    expected = SHEETS[sheet] if size[0] < size[1] else tuple(reversed(SHEETS[sheet]))
    assert _size(page) == pytest.approx(expected, abs=1e-4)
    placement = _assert_uniform_complete_fit(reader, page, images[0])
    assert placement[:2] == pytest.approx([0, 0], abs=.5), 'The page already has the sheet shape'
    assert calls == ['auto']
    processing = result['metadata']['image_processing']
    assert processing['pages'] == [{'document_detected': True, 'sheet': sheet}]
    layout = processing['layouts'][0]
    assert layout['requested_paper_size'] == 'fit' and layout['effective_paper_size'] == sheet
    assert layout['image_encoding'] == 'jpeg'
    assert layout['page_size_points'] == pytest.approx(expected)
    assert layout['image_placement_points'] == pytest.approx(placement, abs=1e-4)


@pytest.mark.parametrize('size', [(600, 1000), (1000, 600)])
def test_a_scanned_page_that_matched_no_sheet_keeps_the_fit_page(tmp_path, monkeypatch, size):
    result, reader, images, _ = _convert(tmp_path, monkeypatch, [size], sheets=[''])
    page = reader.pages[0]
    expected = (505.2, 842) if size[0] < size[1] else (842, 505.2)
    assert _size(page) == pytest.approx(expected, abs=1e-4)
    _assert_uniform_complete_fit(reader, page, images[0])
    layout = result['metadata']['image_processing']['layouts'][0]
    assert layout['effective_paper_size'] == 'fit' and layout['image_encoding'] == 'jpeg'


def test_ordinary_photo_default_keeps_native_aspect_and_all_pixels(tmp_path, monkeypatch):
    result, reader, images, calls = _convert(tmp_path, monkeypatch, [(1000, 600)], sheets=[None])
    page = reader.pages[0]
    assert _size(page) == pytest.approx((842, 505.2), abs=1e-4)
    _assert_uniform_complete_fit(reader, page, images[0], scanned=False)
    assert calls == ['auto']
    assert result['metadata']['image_processing']['layouts'][0]['effective_paper_size'] == 'fit'
    assert result['metadata']['image_processing']['document_pages'] == 0


def test_mixed_batch_resolves_each_page_independently(tmp_path, monkeypatch):
    result, reader, images, _ = _convert(tmp_path, monkeypatch, [(700, 990), (1000, 600), (850, 1100)],
                                         sheets=['A4', None, 'Letter'])
    assert len(reader.pages) == 3
    assert _size(reader.pages[0]) == pytest.approx(A4, abs=1e-4)
    assert _size(reader.pages[1]) == pytest.approx((842, 505.2), abs=1e-4)
    assert _size(reader.pages[2]) == pytest.approx(letter, abs=1e-4)
    for page, image, scanned in zip(reader.pages, images, (True, False, True)):
        _assert_uniform_complete_fit(reader, page, image, scanned=scanned)
    layouts = result['metadata']['image_processing']['layouts']
    assert [layout['effective_paper_size'] for layout in layouts] == ['A4', 'fit', 'Letter']
    assert result['metadata']['image_processing']['document_pages'] == 2


@pytest.mark.parametrize('parameters,expected', [
    ({'paper_size': 'Letter', 'orientation': 'landscape', 'margin': 12}, tuple(reversed(letter))),
    ({'paper_size': 'A4', 'orientation': 'landscape', 'margin': 24}, tuple(reversed(A4))),
    ({'paper_size': 'A4', 'orientation': 'auto', 'margin': 0}, A4),
])
def test_explicit_paper_is_passed_to_the_scanner_and_honored(tmp_path, monkeypatch, parameters, expected):
    # The scanner shapes a document to the chosen sheet; that is its answer.
    result, reader, images, calls = _convert(tmp_path, monkeypatch, [(700, 990)], parameters,
                                             sheets=[parameters['paper_size']])
    assert calls == [parameters['paper_size']]
    page = reader.pages[0]
    assert _size(page) == pytest.approx(expected, abs=1e-4)
    _assert_uniform_complete_fit(reader, page, images[0], parameters['margin'])
    assert result['metadata']['image_processing']['layouts'][0]['effective_paper_size'] == parameters['paper_size']


def test_explicit_paper_still_lays_out_a_photo_that_is_not_a_document(tmp_path, monkeypatch):
    result, reader, images, calls = _convert(tmp_path, monkeypatch, [(600, 1000)],
                                             {'paper_size': 'Letter', 'margin': 12}, sheets=[None])
    assert calls == ['Letter']
    assert _size(reader.pages[0]) == pytest.approx(letter, abs=1e-4)
    _assert_uniform_complete_fit(reader, reader.pages[0], images[0], 12, scanned=False)


@pytest.mark.parametrize('sheet,expected', [('Letter', letter), ('Legal', legal), (None, (600, 1000))])
def test_original_paper_uses_the_matched_sheet_only_for_a_scanned_page(tmp_path, monkeypatch, sheet, expected):
    result, reader, images, calls = _convert(tmp_path, monkeypatch, [(600, 1000)],
                                             {'paper_size': 'original'}, sheets=[sheet])
    assert calls == ['auto']
    assert _size(reader.pages[0]) == pytest.approx(expected, abs=1e-4)
    _assert_uniform_complete_fit(reader, reader.pages[0], images[0], scanned=sheet is not None)
    layout = result['metadata']['image_processing']['layouts'][0]
    assert layout['requested_paper_size'] == 'original'
    assert layout['effective_paper_size'] == (sheet or 'original')


def test_original_paper_fits_a_scanned_page_that_matched_no_sheet(tmp_path, monkeypatch):
    # One point per scanner pixel would print a 2200 px scan 30 inches long.
    result, reader, images, _ = _convert(tmp_path, monkeypatch, [(1200, 2000)],
                                         {'paper_size': 'original'}, sheets=[''])
    assert _size(reader.pages[0]) == pytest.approx((1200 * 842 / 2000, 842), abs=1e-4)
    _assert_uniform_complete_fit(reader, reader.pages[0], images[0])
    assert result['metadata']['image_processing']['layouts'][0]['effective_paper_size'] == 'fit'


def test_explicit_fit_orientation_and_margin_are_preserved_on_the_matched_sheet(tmp_path, monkeypatch):
    result, reader, images, _ = _convert(tmp_path, monkeypatch, [(850, 1100)],
                                         {'orientation': 'landscape', 'margin': 12}, sheets=['Letter'])
    page = reader.pages[0]
    assert _size(page) == pytest.approx(tuple(reversed(letter)), abs=1e-4)
    _assert_uniform_complete_fit(reader, page, images[0], margin=12)
    assert result['metadata']['image_processing']['layouts'][0]['effective_paper_size'] == 'Letter'


def test_real_photographed_form_default_is_printed_on_its_matched_sheet(tmp_path, scanner_models):
    source = tmp_path / 'form.png'
    photographed_shipment_form().save(source)
    result = execute('pdf.images_to_pdf', [source], {}, tmp_path / 'out')
    reader = PdfReader(result['artifacts'][0]['path'])
    page = reader.pages[0]
    assert _size(page) == pytest.approx(A4, abs=1e-4)
    processing = result['metadata']['image_processing']
    assert processing['pages'] == [{'document_detected': True, 'sheet': 'A4'}]
    assert processing['layouts'][0]['effective_paper_size'] == 'A4'
    # The page has A4's shape, so it fills the sheet edge to edge.
    placement = _placement(reader, page)
    assert placement[4:] == pytest.approx((0, 0), abs=.5)
    assert placement[0] == pytest.approx(A4[0], abs=.5) and placement[3] == pytest.approx(A4[1], abs=.5)
