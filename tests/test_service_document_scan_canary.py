"""The service audit must reject padded images and misleading PDF viewports."""
import importlib.util
import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from pypdf import PdfReader
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas


@pytest.fixture(scope='module')
def canary():
    path = Path(__file__).resolve().parents[1] / 'scripts/operations/service_checks_documents.py'
    spec = importlib.util.spec_from_file_location('document_canary_guards', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fitted_pdf(*, padding=0, translation=0):
    image = Image.new('RGB', (450, 680), (150, 150, 150))
    width, height = 450 / 680 * 842, 842
    stream = io.BytesIO()
    canvas = Canvas(stream, pagesize=(width, height), invariant=1)
    if translation:
        canvas.translate(translation, 0)
    canvas.drawImage(ImageReader(image), padding, padding,
                     width - 2 * padding, height - 2 * padding)
    canvas.showPage(); canvas.save()
    return PdfReader(io.BytesIO(stream.getvalue())), image


def test_canvas_guard_accepts_an_actual_borderless_fitted_page(canary):
    reader, image = fitted_pdf()
    assert canary.validate_fit_canvas(reader, image, expected_a4=False) == {
        'borderless_page_verified': True, 'a4_page_verified': False, 'uniform_image_fit_verified': True}


@pytest.mark.parametrize('padding', [1, 24])
def test_canvas_guard_rejects_padding_even_when_page_and_image_aspects_match(canary, padding):
    reader, image = fitted_pdf(padding=padding)
    with pytest.raises(canary.ProbeFailure) as error:
        canary.validate_fit_canvas(reader, image, expected_a4=False)
    assert error.value.code == 'curved_document_borderless_image_placement'


def test_canvas_guard_composes_a_preceding_translation_instead_of_trusting_last_matrix(canary):
    reader, image = fitted_pdf(translation=4)
    with pytest.raises(canary.ProbeFailure) as error:
        canary.validate_fit_canvas(reader, image, expected_a4=False)
    assert error.value.code == 'curved_document_borderless_image_placement'


@pytest.mark.parametrize('viewport', ['rotation', 'crop', 'origin'])
def test_canvas_guard_rejects_a_viewport_that_changes_the_visible_page(canary, viewport):
    reader, image = fitted_pdf()
    page = reader.pages[0]
    if viewport == 'rotation':
        page.rotate(90)
    elif viewport == 'crop':
        page.cropbox.lower_left = (12, 12)
    else:
        page.mediabox.lower_left = (12, 12)
        page.mediabox.upper_right = (float(page.mediabox.right) + 12, float(page.mediabox.top) + 12)
        page.cropbox = page.mediabox
    with pytest.raises(canary.ProbeFailure) as error:
        canary.validate_fit_canvas(reader, image, expected_a4=False)
    assert error.value.code == 'curved_document_page_viewport'


def test_boundary_guard_rejects_a_full_photo_with_its_photographed_desk(canary):
    source, paper_mask = canary.curved_gray_document(with_mask=True)
    with pytest.raises(canary.ProbeFailure) as error:
        canary.validate_paper_boundary(source, paper_mask, source)
    assert error.value.code == 'curved_document_photographed_desk_removed'


def a4_pdf(*, landscape=False, source_aspect=None, padding=0, stretch=False, translation=0):
    from reportlab.lib.pagesizes import A4
    image = Image.new('RGB', source_aspect or ((680, 450) if landscape else (450, 680)), (150, 150, 150))
    width, height = A4[::-1] if landscape else A4
    scale = min(width / image.width, height / image.height)
    placed_width, placed_height = image.width * scale, image.height * scale
    if stretch:
        placed_width, placed_height = width, height
    stream = io.BytesIO()
    canvas = Canvas(stream, pagesize=(width, height), invariant=1)
    canvas.translate(translation, 0)
    canvas.drawImage(ImageReader(image), (width - placed_width) / 2 + padding,
                     (height - placed_height) / 2 + padding,
                     placed_width - 2 * padding, placed_height - 2 * padding)
    canvas.showPage(); canvas.save()
    return PdfReader(io.BytesIO(stream.getvalue())), image


@pytest.mark.parametrize('landscape', [False, True])
def test_canvas_guard_accepts_precise_a4_uniform_fit_and_reports_real_padding(canary, landscape):
    reader, image = a4_pdf(landscape=landscape)
    assert canary.validate_fit_canvas(reader, image) == {
        'a4_page_verified': True, 'uniform_image_fit_verified': True, 'borderless_page_verified': False}


def test_canvas_guard_requires_a4_for_detected_default_documents(canary):
    reader, image = fitted_pdf()
    with pytest.raises(canary.ProbeFailure) as error:
        canary.validate_fit_canvas(reader, image)
    assert error.value.code == 'curved_document_a4_page'


@pytest.mark.parametrize('kwargs', [{'padding': 1}, {'padding': 24}, {'stretch': True}, {'translation': 4}])
def test_a4_guard_rejects_extra_margins_stretching_and_clipping(canary, kwargs):
    reader, image = a4_pdf(**kwargs)
    with pytest.raises(canary.ProbeFailure) as error:
        canary.validate_fit_canvas(reader, image)
    assert error.value.code == 'curved_document_uniform_image_placement'


@pytest.mark.parametrize('viewport', ['rotation', 'crop', 'origin'])
def test_a4_guard_rejects_a_misleading_visible_viewport(canary, viewport):
    reader, image = a4_pdf()
    page = reader.pages[0]
    if viewport == 'rotation':
        page.rotate(90)
    elif viewport == 'crop':
        page.cropbox.lower_left = (12, 12)
    else:
        page.mediabox.lower_left = (12, 12)
        page.mediabox.upper_right = (float(page.mediabox.right) + 12, float(page.mediabox.top) + 12)
        page.cropbox = page.mediabox
    with pytest.raises(canary.ProbeFailure) as error:
        canary.validate_fit_canvas(reader, image)
    assert error.value.code == 'curved_document_page_viewport'


def sheet_pdf(image, sheet_size):
    stream = io.BytesIO()
    width, height = sheet_size
    scale = min(width / image.width, height / image.height)
    canvas = Canvas(stream, pagesize=(width, height), invariant=1)
    canvas.drawImage(ImageReader(image), (width - image.width * scale) / 2, (height - image.height * scale) / 2,
                     image.width * scale, image.height * scale)
    canvas.showPage(); canvas.save()
    return PdfReader(io.BytesIO(stream.getvalue()))


@pytest.mark.parametrize('sheet', ['A4', 'Letter', 'Legal'])
def test_scanned_page_guard_accepts_every_sheet_the_scanner_matches(canary, sheet):
    from reportlab.lib.pagesizes import A4, legal, letter
    size = {'A4': A4, 'Letter': letter, 'Legal': legal}[sheet]
    image = Image.new('RGB', (1000, round(1000 * size[1] / size[0])), (250, 250, 250))
    flags = canary.validate_scanned_page(sheet_pdf(image, size), image, canary.SCAN_PAGE_CORNERS)
    assert flags['sheet_page_verified'] == sheet and flags['uniform_image_fit_verified']
    assert flags['sheet_aspect_verified'] and flags['upscaled_page_verified'] and flags['white_paper_verified']


@pytest.mark.parametrize('image,page,code', [
    (Image.new('RGB', (1000, 1414), 'white'), (500, 707), 'scanned_document_sheet_page'),
    (Image.new('RGB', (1000, 1250), 'white'), None, 'scanned_document_sheet_aspect'),
    (Image.new('RGB', (560, 792), 'white'), None, 'scanned_document_resolution'),
    (Image.new('RGB', (1000, 1414), (200, 190, 150)), None, 'scanned_document_white_paper'),
], ids=['not-a-sheet', 'photo-shape', 'not-rebuilt-larger', 'paper-not-white'])
def test_scanned_page_guard_rejects_what_the_scanner_never_returns(canary, image, page, code):
    from reportlab.lib.pagesizes import A4
    with pytest.raises(canary.ProbeFailure) as error:
        canary.validate_scanned_page(sheet_pdf(image, page or A4), image, canary.SCAN_PAGE_CORNERS)
    assert error.value.code == code


def untouched_pdf(photo, *, jpeg=True):
    from processors.engine import _stripped_jpeg
    stream = io.BytesIO()
    width, height = (photo.width / photo.height * 842, 842)
    canvas = Canvas(stream, pagesize=(width, height), invariant=1)
    data = io.BytesIO()
    photo.save(data, 'JPEG' if jpeg else 'PNG', quality=90)
    source = ImageReader(io.BytesIO(_stripped_jpeg(data.getvalue()))) if jpeg else ImageReader(photo)
    canvas.drawImage(source, 0, 0, width, height)
    canvas.showPage(); canvas.save()
    data.seek(0)
    return PdfReader(io.BytesIO(stream.getvalue())), Image.open(data).convert('RGB')


def test_untouched_photo_guard_accepts_the_upload_embedded_as_it_is(canary):
    reader, original = untouched_pdf(canary.ordinary_photo())
    assert canary.validate_untouched_photo(reader, original) == {
        'borderless_page_verified': True, 'a4_page_verified': False, 'uniform_image_fit_verified': True,
        'original_pixels_preserved': True}


def test_untouched_photo_guard_rejects_a_changed_photo(canary):
    reader, original = untouched_pdf(canary.ordinary_photo())
    pixels = np.array(original)
    pixels[100:110, 100:110] = 255
    with pytest.raises(canary.ProbeFailure) as error:
        canary.validate_untouched_photo(reader, Image.fromarray(pixels))
    assert error.value.code == 'ordinary_photo_pixels_preserved'


def test_live_audit_scans_a_document_and_an_ordinary_photo_with_defaults_only(canary):
    cases = [(inputs, parameters) for feature, inputs, parameters in canary.cases() if feature == 'pdf.images_to_pdf']
    assert cases == [(['red', 'blue'], {}), (['scan'], {}), (['photo'], {}), (['curved_scan'], {}),
                     (['tinted_scan'], {}), (['held_dense_scan'], {})]
