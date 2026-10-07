"""Clipped-page geometry is explicitly allowed to change camera coordinates.

These tests retain the old fallback/source-pixel tests and exercise the new
rectangular path with anonymous photographed paper, not customer documents.
"""
from functools import lru_cache
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from processors.document_scan import _detect, prepare_image
from processors.partial_scan_rectification import rectify_partial
from scripts.operations.partial_scan_fixtures import FONT, partial_document_fixture, source_roi, VARIANTS


@lru_cache(maxsize=10)
def _case(name):
    fixture = partial_document_fixture(**VARIANTS[name])
    details, detected = _detect(fixture.image, details=True)
    assert detected and details is not None and details.get('kind') == 'partial'
    return fixture, details


def _color_ink(rgb, kind):
    rgb = rgb.astype(np.int16)
    red, green, blue = np.moveaxis(rgb, -1, 0)
    if kind == 'blue':
        return (blue > red + 25) & (blue > green + 15) & (red < 100)
    if kind == 'red':
        return (red > green + 25) & (red > blue + 20) & (green < 100)
    if kind == 'magenta':
        return (red > green + 25) & (blue > green + 25) & (green < 100)
    return (green > red + 25) & (green > blue + 15) & (red < 100)


@pytest.mark.parametrize('name', ['three_edges', 'left_edge_flat', 'top_edge',
    'right_bottom', 'top_left_right', 'quarter_turn', 'half_size', 'exterior_note'])
def test_clipped_page_has_rectangular_geometry_and_retains_visible_colored_writing(name):
    fixture, details = _case(name)
    rectified = rectify_partial(fixture.image, details)
    assert rectified is not None
    output, geometry = rectified
    assert geometry['rectified'] is True
    assert geometry['source_size'] == fixture.image.size
    assert geometry['output_size'] == output.size
    assert any(geometry['clipping'].values())
    assert output.width * output.height <= 16_000_000
    assert geometry['paper_mask'].dtype == np.uint8
    assert max(geometry['paper_mask'].shape) <= 512
    assert output.mode == 'RGB'
    original, result = np.asarray(fixture.image), np.asarray(output)
    # Distinct ink colors independently exercise visible margin notes/signature.
    # Perspective changes area; a generous bound still rejects a discarded
    # side or a crop to the interior printed table.
    area_ratio = output.width * output.height / max(1, int((fixture.main_paper > 0).sum()))
    for color in ('blue', 'red', 'magenta', 'green'):
        before = int(_color_ink(original, color).sum())
        if before >= 12:
            after = int(_color_ink(result, color).sum())
            assert after >= before * min(.55, area_ratio * .55), (name, color, before, after)
    # A photographed dark desk must not remain as a rim of the selected page.
    gray = cv2.cvtColor(result, cv2.COLOR_RGB2GRAY)
    border = np.r_[gray[:2].ravel(), gray[-2:].ravel(),
                    gray[:, :2].ravel(), gray[:, -2:].ravel()]
    assert float((border < 60).mean()) < .025


@pytest.mark.parametrize('name', ['three_edges', 'left_edge_flat', 'top_edge',
    'right_bottom', 'top_left_right', 'quarter_turn', 'half_size', 'exterior_note'])
def test_real_default_path_rectifies_but_geometry_off_keeps_the_photo(name):
    fixture, _ = _case(name)
    cropped, metadata = prepare_image(fixture.image, auto_crop=True, enhance_text=False)
    assert metadata['rectified'] is True and metadata['cropped'] is True
    assert metadata['enhanced'] is False
    assert cropped.size != fixture.image.size
    cleaned, default = prepare_image(fixture.image)
    assert default['rectified'] is True and default['enhanced'] is True
    assert cleaned.size == cropped.size
    original, result = np.asarray(fixture.image), np.asarray(cleaned)
    area_ratio = cleaned.width * cleaned.height / max(1, int((fixture.main_paper > 0).sum()))
    for color in ('blue', 'red', 'magenta', 'green'):
        before = int(_color_ink(original, color).sum())
        if before >= 12:
            assert int(_color_ink(result, color).sum()) >= before * min(.55, area_ratio * .55)
    untouched, off = prepare_image(fixture.image, auto_crop=False, enhance_text=False)
    assert untouched.size == fixture.image.size
    assert np.array_equal(np.asarray(untouched), np.asarray(fixture.image))
    assert not any(off.values())


def test_competing_written_secondary_surface_does_not_get_discarded():
    fixture, details = _case('secondary_note')
    result = rectify_partial(fixture.image, details)
    # The independently qualified secondary writing is outside the dominant
    # page pose. An ambiguous crop must retain the existing safe fallback.
    assert result is None


def test_real_default_keeps_secondary_writing_when_rectification_falls_back():
    fixture, _ = _case('secondary_note')
    crop_only, crop_flags = prepare_image(fixture.image, auto_crop=True, enhance_text=False)
    assert not crop_flags.get('rectified', False)
    roi = source_roi(fixture.image, crop_only, white_canvas=True)
    enhanced, flags = prepare_image(fixture.image)
    assert flags['document_detected'] and flags['enhanced']
    assert not flags.get('rectified', False)
    assert enhanced.size == crop_only.size
    left, top, right, bottom = roi
    note = fixture.marks['secondary_note'] > 0
    assert not note[:top].any() and not note[bottom:].any()
    assert not note[:, :left].any() and not note[:, right:].any()
    visible = note[top:bottom, left:right]
    before = np.asarray(fixture.image)[top:bottom, left:right]
    after = np.asarray(enhanced)
    assert int((_color_ink(after, 'blue') & visible).sum()) >= int((_color_ink(before, 'blue') & visible).sum()) * .90


@pytest.mark.parametrize('font_size', [9, 23])
def test_a_single_black_secondary_reference_is_not_discarded(font_size):
    fixture = partial_document_fixture(secondary_note=True)
    image = fixture.image.copy()
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((785, 70, 959, 126), fill=(207, 215, 221))
    font = ImageFont.truetype(str(FONT), font_size)
    drawing.text((815, 80), 'A', font=font, fill=(25, 25, 25))
    note = Image.new('L', image.size)
    ImageDraw.Draw(note).text((815, 80), 'A', font=font, fill=255)
    details, detected = _detect(image, details=True)
    assert detected and details['kind'] == 'partial'
    # A single square glyph supplies no aligned word/group. Its source stroke
    # must still prevent a primary-page crop from losing a written spare sheet.
    assert rectify_partial(image, details) is None
    output, metadata = prepare_image(image, auto_crop=True, enhance_text=False)
    assert not metadata.get('rectified', False)
    left, top, right, bottom = source_roi(image, output, white_canvas=True)
    required = np.asarray(note) > 0
    assert not required[:top].any() and not required[bottom:].any()
    assert not required[:, :left].any() and not required[:, right:].any()
    source = np.asarray(image)[top:bottom, left:right]
    assert np.array_equal(np.asarray(output)[required[top:bottom, left:right]],
                          source[required[top:bottom, left:right]])


def test_a_faint_single_reference_with_trusted_evidence_is_not_a_glint():
    fixture = partial_document_fixture(secondary_note=True)
    image = fixture.image.copy()
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((785, 70, 959, 126), fill=(207, 215, 221))
    font = ImageFont.truetype(str(FONT), 9)
    drawing.text((815, 80), 'A', font=font, fill=(25, 25, 25))
    details, detected = _detect(image, details=True)
    assert detected and details['kind'] == 'partial'
    # Preserve the independently qualified reference mask while lowering its
    # raster contrast: the geometry stage cannot reinterpret faint known ink
    # as a smooth reflected-light fragment simply because it is one letter.
    drawing.rectangle((815, 80, 824, 92), fill=(207, 215, 221))
    drawing.text((815, 80), 'A', font=font, fill=(199, 207, 213))
    assert rectify_partial(image, details) is None


@pytest.mark.parametrize('quarter_turns', [0, 1, 2, 3])
def test_native_camera_edge_writing_is_sampled_at_every_orientation(quarter_turns):
    fixture, details = _case('three_edges')
    native = fixture.image.resize((1920, 2560), Image.Resampling.LANCZOS)
    # A final-row visible stroke exercises native endpoints rather than merely
    # a thumbnail map range. It previously disappeared at scale two.
    ImageDraw.Draw(native).line((600, native.height - 1, 1300, native.height - 1),
        fill=(210, 10, 10), width=1)
    native = Image.fromarray(np.ascontiguousarray(np.rot90(np.asarray(native), quarter_turns)))
    contract = dict(details, source_size=native.size)
    for key in ('paper_foreground', 'surface_envelope', 'protected_evidence'):
        contract[key] = np.ascontiguousarray(np.rot90(details[key], quarter_turns))
    output, geometry = rectify_partial(native, contract)
    assert geometry['rectified'] is True
    def endpoint_ink(rgb):
        return (rgb[..., 0] > 180) & (rgb[..., 1] < 60) & (rgb[..., 2] < 60)

    original_red = int(endpoint_ink(np.asarray(native)).sum())
    result = np.asarray(output)
    # The only saturated red source is the new camera-boundary stroke. An
    # endpoint omission cannot be hidden by interpolation of interior text.
    assert int(endpoint_ink(result).sum()) >= original_red * .45
    expected_edge = (result[-3:] if quarter_turns == 0 else result[:, -3:]
        if quarter_turns == 1 else result[:3] if quarter_turns == 2 else result[:, :3])
    assert int(endpoint_ink(expected_edge).sum()) >= original_red * .45


@pytest.mark.parametrize('change', ['not_partial', 'wrong_source', 'wrong_envelope', 'oversized_mask'])
def test_rectification_requires_the_detectors_bounded_partial_contract(change):
    fixture, details = _case('three_edges')
    details = dict(details)
    if change == 'not_partial':
        details['kind'] = 'ordinary_photo'
    elif change == 'wrong_source':
        details['source_size'] = (1, 1)
    elif change == 'wrong_envelope':
        details['surface_envelope'] = np.zeros((3, 4), np.uint8)
    else:
        details['paper_foreground'] = np.zeros((513, 400), np.uint8)
        details['surface_envelope'] = details['paper_foreground'].copy()
    assert rectify_partial(fixture.image, details) is None


def test_large_page_samples_original_once_with_bounded_strip_maps(monkeypatch):
    fixture, details = _case('three_edges')
    native = fixture.image.resize((4608, 6144), Image.Resampling.LANCZOS)
    details = dict(details, source_size=native.size)
    calls = []
    original_remap = cv2.remap

    def bounded_remap(source, map_x, map_y, *args, **kwargs):
        assert map_x.size <= 1_000_000
        assert map_y.size <= 1_000_000
        if source.ndim == 3:
            assert source.shape[:2] == (native.height, native.width)
            assert map_x.dtype == np.float32 and map_y.dtype == np.float32
            calls.append(map_x.size)
        return original_remap(source, map_x, map_y, *args, **kwargs)

    monkeypatch.setattr(cv2, 'remap', bounded_remap)
    output, geometry = rectify_partial(native, details)
    assert output.width * output.height <= 16_000_000
    assert len(calls) >= 2
    assert sum(calls) == output.width * output.height
    assert max(geometry['paper_mask'].shape) <= 512


@pytest.mark.parametrize('size', [(8000, 8000), (32767, 128), (128, 32767)])
def test_unsafe_native_size_is_rejected_before_allocating_a_geometry_raster(size):
    fixture, details = _case('three_edges')
    # The early size guard needs only image dimensions; no enormous raster is
    # allocated in this regression. Any resize/read past that guard would fail.
    unavailable_raster = SimpleNamespace(size=size, width=size[0], height=size[1])
    assert rectify_partial(unavailable_raster, dict(details, source_size=size)) is None
