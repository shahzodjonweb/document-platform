"""Focused calibration of anonymous partial-page preservation properties."""
import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from processors.document_scan import prepare_image

from scripts.operations.partial_scan_fixtures import (
    FONT, VARIANTS, partial_document_fixture, reference_modes, source_roi,
    validate_partial_modes, validate_partial_output,
)


@pytest.mark.parametrize('variant', list(VARIANTS))
def test_guards_accept_independent_camera_ground_truth(variant):
    fixture = partial_document_fixture(**VARIANTS[variant])
    assert validate_partial_modes(fixture, reference_modes(fixture))['visible_marks_preserved']


@pytest.mark.parametrize('kind', ['secondary_note'])
def test_note_forbids_cropping_its_visible_writing(kind):
    fixture = partial_document_fixture(**{kind: True})
    modes = reference_modes(fixture)
    # Writing on a secondary sheet is document content and must survive.
    bad = fixture.image.crop((0, 186, fixture.image.width, fixture.image.height))
    modes[(True, False)] = (bad, {'cropped': True, 'enhanced': False})
    with pytest.raises(AssertionError, match='visible marks|proven paper'):
        validate_partial_modes(fixture, modes)


def test_homography_cannot_masquerade_as_partial_crop_only():
    fixture = partial_document_fixture()
    matrix = cv2.getRotationMatrix2D((fixture.image.width / 2, fixture.image.height / 2), 1., 1.)
    bad = Image.fromarray(cv2.warpAffine(np.asarray(fixture.image), matrix, fixture.image.size))
    with pytest.raises(AssertionError, match='exact source ROI'):
        source_roi(fixture.image, bad)


def test_effect_must_not_change_exterior_scene_pixels():
    fixture = partial_document_fixture(exterior_note=True)
    modes = reference_modes(fixture)
    pixels = np.array(modes[(False, True)][0])
    pixels[fixture.all_paper == 0] = 128
    modes[(False, True)] = (Image.fromarray(pixels), {'cropped': False, 'enhanced': True})
    with pytest.raises(AssertionError, match='Exterior scene'):
        validate_partial_modes(fixture, modes)


@pytest.mark.parametrize('label', ['blue_note', 'signature', 'secondary_note'])
def test_readability_effect_cannot_erase_visible_colored_writing(label):
    fixture = partial_document_fixture(secondary_note=label == 'secondary_note')
    modes = reference_modes(fixture)
    pixels = np.array(modes[(False, True)][0])
    pixels[fixture.marks[label] >= 200] = 245
    modes[(False, True)] = (Image.fromarray(pixels), {'cropped': False, 'enhanced': True})
    with pytest.raises(AssertionError, match='mark contrast|visible ink|colored ink'):
        validate_partial_modes(fixture, modes)


@pytest.mark.parametrize('variant', list(VARIANTS))
def test_partial_page_preserves_visible_camera_pixels_and_improves_readability(variant):
    fixture = partial_document_fixture(**VARIANTS[variant])
    modes = {
        mode: prepare_image(fixture.image, auto_crop=mode[0], enhance_text=mode[1])
        for mode in ((True, True), (True, False), (False, True), (False, False))
    }
    assert validate_partial_modes(fixture, modes)['visible_marks_preserved']
    default_image, default_flags = prepare_image(fixture.image)
    explicit_image, explicit_flags = modes[(True, True)]
    assert default_image.size == explicit_image.size
    assert default_image.tobytes() == explicit_image.tobytes()
    assert default_flags == explicit_flags


@pytest.mark.parametrize('variant', ['three_edges', 'exterior_note', 'secondary_note'])
def test_single_worker_output_guard_accepts_proven_roi_and_masked_cleanup(variant):
    fixture = partial_document_fixture(**VARIANTS[variant])
    modes = reference_modes(fixture)
    crop = validate_partial_output(fixture, modes[(True, False)][0], enhanced=False)
    effect = validate_partial_output(fixture, modes[(True, True)][0],
                                     enhanced=True, roi=crop['roi'])
    assert crop['crop_verified'] and not crop['effect_verified']
    assert effect['effect_verified'] and effect['visible_marks_preserved']
    assert effect['white_canvas_verified'] and effect['exterior_background_removed']
    assert effect['source_geometry_preserved']


def test_single_worker_effect_requires_independently_proven_source_roi():
    fixture = partial_document_fixture()
    with pytest.raises(AssertionError, match='proven crop-only source ROI'):
        validate_partial_output(fixture, reference_modes(fixture)[(True, True)][0],
                                enhanced=True)


def test_single_worker_guard_cannot_accept_different_or_invented_source_roi():
    fixture = partial_document_fixture()
    crop = reference_modes(fixture)[(True, False)][0]
    with pytest.raises(AssertionError, match='proven source ROI'):
        validate_partial_output(fixture, crop, enhanced=False, roi=(0, 0, 1, 1))
    with pytest.raises(AssertionError, match='cannot invent hidden content'):
        validate_partial_output(fixture, fixture.image, enhanced=True,
                                roi=(-1, 0, fixture.image.width, fixture.image.height))


@pytest.mark.parametrize('variant', ['three_edges', 'quarter_turn', 'half_size'])
def test_known_empty_band_rejects_ignored_auto_crop_in_both_validation_apis(variant):
    fixture = partial_document_fixture(**VARIANTS[variant])
    modes = reference_modes(fixture)
    modes[(True, False)] = (fixture.image, {'cropped': False, 'enhanced': False})
    modes[(True, True)] = modes[(False, True)]
    with pytest.raises(AssertionError, match='meaningful proven empty exterior band'):
        validate_partial_modes(fixture, modes)
    with pytest.raises(AssertionError, match='meaningful proven empty exterior band'):
        validate_partial_output(fixture, fixture.image, enhanced=False)


@pytest.mark.parametrize('variant', ['secondary_note'])
def test_visible_note_can_safely_keep_full_source_geometry(variant):
    fixture = partial_document_fixture(**VARIANTS[variant])
    crop = reference_modes(fixture)[(True, False)][0]
    left, top, right, bottom = source_roi(fixture.image, crop, white_canvas=True)
    canvas = Image.new('RGB', fixture.image.size, 'white')
    canvas.paste(crop, (left, top))
    result = validate_partial_output(fixture, canvas, enhanced=False)
    assert result['roi'] == (0, 0, fixture.image.width, fixture.image.height)
    assert result['visible_marks_preserved']


@pytest.mark.parametrize('rectangle,color', [
    ((530, 120, 950, 280), (142, 144, 146)),
    ((300, 160, 700, 280), (155, 157, 159)),
    ((700, 150, 850, 280), (150, 152, 154)),
], ids=['broad_gray_desk', 'thin_gray_desk', 'small_gray_desk'])
def test_touching_gray_desk_patch_is_never_whitened_as_partial_paper(rectangle, color):
    fixture = partial_document_fixture()
    pixels = np.array(fixture.image)
    exterior = fixture.all_paper == 0
    left, top, right, bottom = rectangle
    patch = np.zeros(exterior.shape, bool)
    patch[top:bottom, left:right] = True
    patch &= exterior
    assert int(patch.sum()) > 5_000
    pixels[patch] = color
    original = Image.fromarray(pixels)

    effect, effect_flags = prepare_image(original, auto_crop=False, enhance_text=True)
    assert effect.size == original.size and not effect_flags['cropped']
    assert np.array_equal(np.asarray(effect)[exterior], pixels[exterior]), 'Exterior gray desk must stay pixel-exact'

    off, off_flags = prepare_image(original, auto_crop=False, enhance_text=False)
    assert off.size == original.size and off.tobytes() == original.tobytes()
    assert not off_flags['cropped'] and not off_flags['enhanced']

    crop, crop_flags = prepare_image(original, auto_crop=True, enhance_text=False)
    roi = source_roi(original, crop, white_canvas=True)
    assert not crop_flags['enhanced']
    retained = np.zeros(exterior.shape, bool)
    left, top, right, bottom = roi
    retained[top:bottom, left:right] = True
    assert not np.any((fixture.all_paper > 0) & ~retained), 'No visible source paper may be removed'
    for label, mask in fixture.marks.items():
        on_paper = (mask > 0) & (fixture.all_paper > 0)
        assert not np.any(on_paper & ~retained), 'No visible on-paper writing may be removed: ' + label
    known_paper = fixture.all_paper[top:bottom, left:right] > 0
    assert np.array_equal(np.asarray(crop)[known_paper], pixels[top:bottom, left:right][known_paper]), 'Crop-only keeps source paper RGB'
    if crop_flags['document_detected']:
        # Once an ambiguous desk extension is admitted as a document, the
        # same independently known exterior-removal contract still applies.
        fixture.image = original
        assert validate_partial_output(fixture, crop, enhanced=False)['white_canvas_verified']
    else:
        assert crop.size == original.size and crop.tobytes() == original.tobytes(), 'Uncertain scenes may safely remain unchanged'


@pytest.mark.parametrize('mode', [(True, False), (True, True)])
def test_white_canvas_oracle_rejects_unchanged_exterior_and_wide_halo(mode):
    fixture = partial_document_fixture()
    modes = reference_modes(fixture)
    canvas = np.array(modes[mode][0])
    roi = source_roi(fixture.image, modes[(True, False)][0], white_canvas=True)
    left, top, right, bottom = roi
    exterior = fixture.all_paper[top:bottom, left:right] == 0
    canvas[exterior] = np.asarray(fixture.image)[top:bottom, left:right][exterior]
    modes[mode] = (Image.fromarray(canvas), modes[mode][1])
    with pytest.raises(AssertionError, match='white canvas|narrow conservative edge halo'):
        validate_partial_modes(fixture, modes)


def test_crop_canvas_oracle_rejects_paper_pixels_painted_white():
    fixture = partial_document_fixture()
    modes = reference_modes(fixture)
    pixels = np.array(modes[(True, False)][0])
    left, top, right, bottom = source_roi(fixture.image, modes[(True, False)][0], white_canvas=True)
    mask = fixture.marks['blue_note'][top:bottom, left:right] > 0
    pixels[mask] = 255
    modes[(True, False)] = (Image.fromarray(pixels), modes[(True, False)][1])
    with pytest.raises(AssertionError, match='visible paper and reference RGB'):
        validate_partial_modes(fixture, modes)


@pytest.mark.parametrize('kind', ['tiny_faint', 'tiny_blue', 'single_faint', 'short_blue'])
def test_partial_white_canvas_removes_off_paper_references_and_keeps_scene_when_off(kind):
    fixture = partial_document_fixture(exterior_note=True, exterior_note_kind=kind)
    modes = {mode: prepare_image(fixture.image, auto_crop=mode[0], enhance_text=mode[1])
             for mode in ((True, True), (True, False), (False, True), (False, False))}
    assert validate_partial_modes(fixture, modes)['white_canvas_verified']


@pytest.mark.parametrize('kind', ['tiny_faint', 'tiny_blue', 'single_faint', 'short_blue'])
def test_white_canvas_oracle_rejects_retaining_unrelated_scene_reference(kind):
    fixture = partial_document_fixture(exterior_note=True, exterior_note_kind=kind)
    modes = reference_modes(fixture)
    canvas = np.array(modes[(True, False)][0])
    left, top, right, bottom = source_roi(fixture.image, modes[(True, False)][0], white_canvas=True)
    # Restore a source annotation on the canvas at its original camera position.
    # A full-size canvas allows the annotation to be tested even when the
    # independent document crop would correctly remove its entire top band.
    full = Image.new('RGB', fixture.image.size, 'white')
    full.paste(Image.fromarray(canvas), (left, top))
    pixels = np.array(full)
    visible = fixture.marks['exterior_note'] > 0
    pixels[visible] = np.asarray(fixture.image)[visible]
    modes[(True, False)] = (Image.fromarray(pixels), modes[(True, False)][1])
    modes[(True, True)] = (Image.fromarray(pixels), modes[(True, True)][1])
    with pytest.raises(AssertionError, match='meaningful proven empty exterior band|white canvas|off-paper references'):
        validate_partial_modes(fixture, modes)


def _on_paper_reference(fixture, kind):
    """Render a tiny native glyph on independently known opaque paper."""
    width, height = fixture.image.size
    x = round(width * .15)
    ys = np.flatnonzero(fixture.main_paper[:, x] >= 248)
    assert ys.size > 30
    y = int(ys[0]) + 15
    mask_image = Image.new('L', fixture.image.size, 0)
    value = 'X' if kind == 'single_faint' else 'ID'
    ImageDraw.Draw(mask_image).text((x, y), value,
                                  font=ImageFont.truetype(str(FONT), 9), fill=255)
    mask = np.asarray(mask_image)
    visible = mask > 0
    assert int(visible.sum()) >= 10 and np.all(fixture.main_paper[visible] >= 248)
    pixels = np.asarray(fixture.image).astype(np.float32)
    color = np.maximum(pixels - 8, 0) if kind == 'single_faint' else np.array((13, 44, 142))
    weight = mask.astype(np.float32) / 255
    pixels = np.clip(pixels * (1 - weight[:, :, None]) + color * weight[:, :, None], 0, 255).astype(np.uint8)
    fixture.image = Image.fromarray(pixels)
    fixture.marks['on_paper_reference'] = mask
    return visible


@pytest.mark.parametrize('kind', ['single_faint', 'short_blue'])
def test_white_canvas_preserves_every_tiny_on_paper_reference_rgb_pixel(kind):
    fixture = partial_document_fixture()
    visible = _on_paper_reference(fixture, kind)
    output, flags = prepare_image(fixture.image, auto_crop=True, enhance_text=False)
    proof = validate_partial_output(fixture, output, enhanced=False)
    left, top, right, bottom = proof['roi']
    kept = visible[top:bottom, left:right]
    assert int(kept.sum()) == int(visible.sum()), 'Do not crop a one-character paper reference'
    assert np.array_equal(np.asarray(output)[kept], np.asarray(fixture.image)[top:bottom, left:right][kept])
    assert not flags['enhanced']


@pytest.mark.parametrize('kind', ['single_faint', 'short_blue'])
def test_white_canvas_oracle_cannot_hide_a_tiny_on_paper_reference(kind):
    fixture = partial_document_fixture()
    visible = _on_paper_reference(fixture, kind)
    modes = reference_modes(fixture)
    canvas = np.array(modes[(True, False)][0])
    left, top, right, bottom = source_roi(fixture.image, modes[(True, False)][0], white_canvas=True)
    canvas[visible[top:bottom, left:right]] = 255
    modes[(True, False)] = (Image.fromarray(canvas), modes[(True, False)][1])
    with pytest.raises(AssertionError, match='visible paper and reference RGB'):
        validate_partial_output(fixture, modes[(True, False)][0], enhanced=False)
