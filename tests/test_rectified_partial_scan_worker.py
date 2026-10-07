"""Anonymous partial paper traverses the real processor into a verifiable A4 PDF."""
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
import pytest

from processors import execute
from scripts.operations.rectified_partial_scan_fixtures import (
    rectified_partial_fixture, validate_rectified_partial_output,
)
from scripts.operations.service_checks_documents import validate_fit_canvas


def test_worker_rectifies_and_cleans_visible_partial_document_onto_actual_a4(tmp_path):
    fixture = rectified_partial_fixture()
    source = tmp_path / 'anonymous-curved-clipped-form.png'
    fixture.image.save(source)
    crop_only = None
    for name, parameters in (('crop-only', {'auto_crop': True, 'enhance_text': False}),
                             ('defaults', {})):
        result = execute('pdf.images_to_pdf', [source], parameters, tmp_path / name)
        page_flags = result['metadata']['image_processing']['pages'][0]
        assert page_flags['document_detected'] is True and page_flags['cropped'] is True
        assert page_flags['rectified'] is True and page_flags['background_removed'] is True
        assert page_flags['enhanced'] is (name == 'defaults')
        layout = result['metadata']['image_processing']['layouts'][0]
        assert layout['requested_paper_size'] == 'fit' and layout['effective_paper_size'] == 'A4'
        assert layout['automatic_a4'] is True
        reader = PdfReader(result['artifacts'][0]['path'])
        assert len(reader.pages) == 1 and len(reader.pages[0].images) == 1
        page = reader.pages[0]
        assert (float(page.mediabox.width), float(page.mediabox.height)) == pytest.approx(A4, abs=.001)
        image = page.images[0].image.convert('RGB')
        canvas_flags = validate_fit_canvas(reader, image)
        assert canvas_flags['a4_page_verified'] and canvas_flags['uniform_image_fit_verified']
        proof = validate_rectified_partial_output(fixture, image, enhanced=name == 'defaults', crop_only=crop_only)
        assert proof['rectified_page_verified'] and proof['visible_marks_preserved']
        assert proof['complete_stripe_code_verified'] and proof['rectangular_paper_edges_verified']
        if name == 'crop-only':
            crop_only = image.copy()
        else:
            assert proof['effect_verified']
