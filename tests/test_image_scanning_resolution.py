"""Telegram-sized anonymous photos keep paper boundaries and incoming writing.

The pre-camera alpha and camera corners belong to fixture generation. Expected
ink/barcode quality is measured after resizing the incoming photograph; a
half-sized upload cannot be required to recreate its lost one-pixel stripes.
"""
import importlib.util
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from processors.document_scan import prepare_image
from tests.test_image_scanning_occluded import PAGE_CORNERS, _boundary_metrics


@pytest.fixture(scope='module')
def canary():
    path = Path(__file__).resolve().parents[1] / 'scripts/operations/service_checks_documents.py'
    spec = importlib.util.spec_from_file_location('resolution_scan_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _incoming_fixture(canary, family, scale):
    if family == 'dense':
        source, paper_mask, finger_mask = canary.held_dense_document()
        corners = PAGE_CORNERS
    else:
        source, paper_mask = canary.tinted_document_photo(with_mask=True)
        finger_mask = np.zeros(paper_mask.shape, np.uint8)
        corners = np.array(((140, 90), (601, 143), (561, 819), (88, 746)), np.float32)
    size = (round(source.width * scale), round(source.height * scale))
    incoming = source.resize(size, Image.Resampling.LANCZOS)
    paper = np.asarray(Image.fromarray(paper_mask).resize(size, Image.Resampling.BOX))
    finger = np.asarray(Image.fromarray(finger_mask).resize(size, Image.Resampling.BOX))
    factor = np.array((size[0] / source.width, size[1] / source.height), np.float32)
    return incoming, paper, finger, (corners + .5) * factor - .5


def _known_camera_reference(incoming, corners):
    """Undo only fixture camera geometry, without invoking scanner code."""
    tl, tr, br, bl = corners
    width = round((np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2)
    height = round((np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2)
    target = np.array(((0, 0), (width - 1, 0), (width - 1, height - 1), (0, height - 1)), np.float32)
    transform = cv2.getPerspectiveTransform(corners.astype(np.float32), target)
    return Image.fromarray(cv2.warpPerspective(np.asarray(incoming), transform, (width, height)))


def _margin_glyphs(image):
    rgb = np.asarray(image).astype(np.int16)
    height, width = rgb.shape[:2]
    # Chroma strength survives gray shadow and identifies only fixture writing.
    strength = np.clip(np.minimum(rgb[:, :, 1] - rgb[:, :, 0],
                                  rgb[:, :, 2] - rgb[:, :, 0]), 0, 255)
    strength[np.abs(rgb[:, :, 1] - rgb[:, :, 2]) >= 35] = 0  # Blue signature/stamp is not a cyan margin label.
    parts = (strength[height // 3:2 * height // 3, :width // 4],
             strength[height // 3:2 * height // 3, 3 * width // 4:],
             strength[:height // 4, width // 3:2 * width // 3],
             strength[3 * height // 4:, width // 3:2 * width // 3])
    glyphs = []
    for part in parts:
        y, x = np.where(part > 18)
        assert len(y) >= 6, 'Every visible margin label must remain in the output'
        box = part[y.min():y.max() + 1, x.min():x.max() + 1].astype(np.float32)
        glyphs.append((float(box.mean()), cv2.resize(box, (64, 64), interpolation=cv2.INTER_LINEAR) > 18))
    return glyphs


def _corner_ink(image):
    rgb = np.asarray(image).astype(np.int16)
    height, width = rgb.shape[:2]
    regions = (rgb[:height // 4, :width // 4], rgb[:height // 4, 3 * width // 4:],
               rgb[3 * height // 4:, :width // 4], rgb[3 * height // 4:, 3 * width // 4:])
    rules = (lambda p: (p[:, :, 0] > p[:, :, 1] + 30) & (p[:, :, 0] > p[:, :, 2] + 30),
             lambda p: (p[:, :, 1] > p[:, :, 0] + 25) & (p[:, :, 1] > p[:, :, 2] + 25),
             lambda p: (p[:, :, 0] > p[:, :, 1] + 30) & (p[:, :, 1] > p[:, :, 2] + 25),
             lambda p: (p[:, :, 0] > p[:, :, 1] + 30) & (p[:, :, 2] > p[:, :, 1] + 30))
    return [int(rule(region).sum()) for rule, region in zip(rules, regions)]


def _assert_margin_writing(reference, output):
    before, after = _corner_ink(reference), _corner_ink(output)
    assert min(before) >= 6, 'Incoming corner labels must be distinguishable'
    assert all(new >= max(6, old * .65) for old, new in zip(before, after)), 'Do not cut away incoming corner writing'
    for (old_mass, old_shape), (new_mass, new_shape) in zip(_margin_glyphs(reference), _margin_glyphs(output)):
        coverage = 0.
        for shear in np.linspace(-.2, .2, 17):
            transform = np.array(((1, 0, 0), (shear, 1, -31.5 * shear)), np.float32)
            aligned = cv2.warpAffine(new_shape.astype(np.uint8), transform, (64, 64), flags=cv2.INTER_NEAREST)
            supported = cv2.dilate(aligned, np.ones((3, 3), np.uint8)) > 0
            coverage = max(coverage, float((old_shape & supported).sum()) / int(old_shape.sum()))
        assert coverage >= .75 and new_mass >= old_mass * .70, 'Keep incoming margin glyph strokes'


@pytest.mark.parametrize('family', ['dense', 'tinted'])
@pytest.mark.parametrize('scale', [.5, .75], ids=['half-size', 'three-quarter-size'])
@pytest.mark.parametrize('rotation', [None, Image.Transpose.ROTATE_90], ids=['portrait', 'quarter-turn'])
def test_small_incoming_photos_keep_real_boundaries_and_all_margin_writing(canary, family, scale, rotation):
    incoming, paper_mask, finger_mask, corners = _incoming_fixture(canary, family, scale)
    reference = _known_camera_reference(incoming, corners)
    source = incoming if rotation is None else incoming.transpose(rotation)
    output, metadata = prepare_image(source, enhance_text=False)
    assert metadata['document_detected'] and metadata['cropped'] and not metadata['enhanced']
    if rotation is not None:
        output = output.transpose(Image.Transpose.ROTATE_270)
    if family == 'dense':
        boundary = _boundary_metrics(incoming, paper_mask, finger_mask, output)
        # Calibrate to visible incoming bars, rather than the pristine full-size
        # 68 transitions. The camera reference uses this exact resized input.
        before_rows, before_best = canary.held_document_barcode_scanlines(reference)
        after_rows, after_best = canary.held_document_barcode_scanlines(output)
        assert before_best > 8, 'Incoming stripe-code signal must be present'
        assert after_rows >= before_rows * .75 and after_best >= before_best * .85, 'Keep incoming barcode detail'
    else:
        boundary = canary.tinted_boundary_metrics(incoming, paper_mask, output)
    assert boundary['border_desk_fraction'] < .04, boundary
    assert max(boundary['corner_desk_fractions']) < .10, boundary
    _assert_margin_writing(reference, output)


@pytest.mark.parametrize('family', ['dense', 'tinted'])
@pytest.mark.parametrize('scale', [.5, .75])
def test_resolution_guard_rejects_a_crop_to_the_internal_printed_frame(canary, family, scale):
    incoming, _, _, corners = _incoming_fixture(canary, family, scale)
    reference = _known_camera_reference(incoming, corners)
    bad = reference.crop((round(reference.width * .06), round(reference.height * .06),
                          round(reference.width * .94), round(reference.height * .94)))
    with pytest.raises(AssertionError, match='writing|margin'):
        _assert_margin_writing(reference, bad)


@pytest.mark.parametrize('family', ['dense', 'tinted'])
def test_both_off_preserve_every_incoming_half_size_pixel(canary, family):
    incoming, _, _, _ = _incoming_fixture(canary, family, .5)
    output, metadata = prepare_image(incoming, auto_crop=False, enhance_text=False)
    assert metadata == {'document_detected': False, 'cropped': False, 'enhanced': False}
    assert output.size == incoming.size and output.tobytes() == incoming.tobytes()
