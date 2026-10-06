"""The worker canary must reject desk, missing ink and a disabled effect."""
import importlib.util
import io
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas


@pytest.fixture(scope='module')
def canary():
    path = Path(__file__).resolve().parents[1] / 'scripts/operations/service_checks_documents.py'
    spec = importlib.util.spec_from_file_location('tinted_document_canary_guards', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def known_flat_crop(source):
    # Ground-truth corners belong to the procedural camera, not the detector.
    source_corners = np.array(((140, 90), (601, 143), (561, 819), (88, 746)), np.float32)
    destination = np.array(((0, 0), (449, 0), (449, 679), (0, 679)), np.float32)
    transform = cv2.getPerspectiveTransform(source_corners, destination)
    return Image.fromarray(cv2.warpPerspective(np.asarray(source), transform, (450, 680)))


def fitted_pdf(image):
    width, height = image.width / max(image.size) * 842, image.height / max(image.size) * 842
    stream = io.BytesIO()
    canvas = Canvas(stream, pagesize=(width, height), invariant=1)
    canvas.drawImage(ImageReader(image), 0, 0, width, height)
    canvas.showPage(); canvas.save()
    return stream.getvalue()


@pytest.mark.parametrize('paper_kind,desk_kind', [('yellow', 'bright'), ('dark', 'bright'), ('yellow', 'dark')])
def test_true_material_boundary_guard_accepts_ground_truth_crop(canary, paper_kind, desk_kind):
    source, mask = canary.tinted_document_photo(paper_kind=paper_kind, desk_kind=desk_kind,
                                               curved=False, with_mask=True)
    image = known_flat_crop(source)
    metrics = canary.tinted_boundary_metrics(source, mask, image)
    assert metrics['border_desk_fraction'] < .04, metrics
    assert max(metrics['corner_desk_fractions']) < .10, metrics
    flags = canary.validate_tinted_scan(fitted_pdf(image), source, mask, enhanced=False)
    assert flags['paper_boundary_verified'] and flags['blue_stamp_and_handwriting_preserved']


@pytest.mark.parametrize('paper_kind,desk_kind', [('yellow', 'bright'), ('dark', 'bright'), ('yellow', 'dark')])
def test_material_boundary_guard_rejects_real_desk_at_output_edges(canary, paper_kind, desk_kind):
    source, mask = canary.tinted_document_photo(paper_kind=paper_kind, desk_kind=desk_kind,
                                               curved=False, with_mask=True)
    metrics = canary.tinted_boundary_metrics(source, mask, source)
    assert metrics['border_desk_fraction'] > .8
    assert min(metrics['corner_desk_fractions']) > .8


def test_worker_canary_rejects_a_fitted_pdf_that_still_contains_the_full_photo(canary):
    source, mask = canary.tinted_document_photo(curved=False, with_mask=True)
    with pytest.raises(canary.ProbeFailure) as error:
        canary.validate_tinted_scan(fitted_pdf(source), source, mask, enhanced=False)
    assert error.value.code == 'tinted_document_crop'


def test_worker_canary_rejects_erased_blue_stamp_even_if_other_writing_survives(canary):
    source = canary.tinted_document_photo(curved=False)
    image = known_flat_crop(source)
    pixels = np.array(image)
    pixels[500:620, 272:412] = (213, 194, 149)
    with pytest.raises(canary.ProbeFailure) as error:
        canary.validate_tinted_writing(source, Image.fromarray(pixels))
    assert error.value.code == 'tinted_document_blue_stamp_and_handwriting'


def test_stamp_outline_alone_cannot_pass_as_a_complete_written_stamp(canary):
    source = canary.tinted_document_photo(curved=False)
    image = known_flat_crop(source)
    pixels = np.array(image)
    pixels[541:574, 304:372] = (213, 194, 149)  # Keep the ellipse, remove TEST.
    with pytest.raises(canary.ProbeFailure) as error:
        canary.validate_tinted_writing(source, Image.fromarray(pixels))
    assert error.value.code == 'tinted_document_blue_stamp_and_handwriting'


def test_worker_canary_rejects_erased_side_label(canary):
    source = canary.tinted_document_photo(curved=False)
    image = known_flat_crop(source)
    pixels = np.array(image)
    pixels[322:373, :50] = (213, 194, 149)
    with pytest.raises(canary.ProbeFailure) as error:
        canary.validate_tinted_writing(source, Image.fromarray(pixels))
    assert error.value.code == 'tinted_document_all_side_writing'


def test_small_camera_shear_tolerance_cannot_hide_a_missing_margin_letter(canary):
    source = canary.tinted_document_photo(curved=False)
    image = known_flat_crop(source)
    pixels = np.array(image)
    pixels[331:359, 2:17] = (213, 194, 149)  # Remove E; leave the adjacent 5.
    with pytest.raises(canary.ProbeFailure) as error:
        canary.validate_tinted_writing(source, Image.fromarray(pixels))
    assert error.value.code == 'tinted_document_side_writing_preserved'


def test_worker_canary_rejects_a_missing_default_readability_effect(canary):
    source, mask = canary.tinted_document_photo(curved=False, with_mask=True)
    image = known_flat_crop(source)
    with pytest.raises(canary.ProbeFailure) as error:
        canary.validate_tinted_scan(fitted_pdf(image), source, mask, enhanced=True)
    assert error.value.code == 'tinted_document_readability_effect'


def test_live_audit_exercises_defaults_and_independent_crop_only_switch(canary):
    cases = [(feature, parameters) for feature, inputs, parameters in canary.cases() if inputs == ['tinted_scan']]
    assert cases == [('pdf.images_to_pdf', {}),
                     ('pdf.images_to_pdf', {'auto_crop': True, 'enhance_text': False})]
