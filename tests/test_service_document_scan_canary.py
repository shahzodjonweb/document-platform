"""The service audit must reject padded images and misleading PDF viewports."""
import importlib.util
import io
from pathlib import Path

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
    assert canary.validate_fit_canvas(reader, image) == {'borderless_page_verified': True}


@pytest.mark.parametrize('padding', [1, 24])
def test_canvas_guard_rejects_padding_even_when_page_and_image_aspects_match(canary, padding):
    reader, image = fitted_pdf(padding=padding)
    with pytest.raises(canary.ProbeFailure) as error:
        canary.validate_fit_canvas(reader, image)
    assert error.value.code == 'curved_document_borderless_image_placement'


def test_canvas_guard_composes_a_preceding_translation_instead_of_trusting_last_matrix(canary):
    reader, image = fitted_pdf(translation=4)
    with pytest.raises(canary.ProbeFailure) as error:
        canary.validate_fit_canvas(reader, image)
    assert error.value.code == 'curved_document_borderless_image_placement'


@pytest.mark.parametrize('viewport', ['rotation', 'crop'])
def test_canvas_guard_rejects_a_viewport_that_changes_the_visible_page(canary, viewport):
    reader, image = fitted_pdf()
    page = reader.pages[0]
    if viewport == 'rotation':
        page.rotate(90)
    else:
        page.cropbox.lower_left = (12, 12)
    with pytest.raises(canary.ProbeFailure) as error:
        canary.validate_fit_canvas(reader, image)
    assert error.value.code == 'curved_document_page_viewport'


def test_boundary_guard_rejects_a_full_photo_with_its_photographed_desk(canary):
    source, paper_mask = canary.curved_gray_document(with_mask=True)
    with pytest.raises(canary.ProbeFailure) as error:
        canary.validate_paper_boundary(source, paper_mask, source)
    assert error.value.code == 'curved_document_photographed_desk_removed'
