"""Tinted/darker paper must retain writing, without treating panels as scans.

Procedural material colors and a pre-camera alpha supply the ground truth;
these checks neither import detection constants nor trust engine status alone.
"""
import importlib.util
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from processors.document_scan import prepare_image


@pytest.fixture(scope='module')
def canary():
    path = Path(__file__).resolve().parents[1] / 'scripts/operations/service_checks_documents.py'
    spec = importlib.util.spec_from_file_location('tinted_scan_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('paper_kind,desk_kind', [('yellow', 'bright'), ('dark', 'bright'), ('yellow', 'dark')])
@pytest.mark.parametrize('curved', [False, True], ids=['flat', 'bowed'])
@pytest.mark.parametrize('rotation', [None, Image.Transpose.ROTATE_90], ids=['portrait', 'quarter-turn'])
def test_tinted_and_reverse_contrast_pages_remove_desk_keep_edge_ink(canary, paper_kind, desk_kind, curved, rotation):
    source, mask = canary.tinted_document_photo(paper_kind=paper_kind, desk_kind=desk_kind,
                                               curved=curved, rotation=rotation, with_mask=True)
    result, metadata = prepare_image(source, enhance_text=False)
    assert metadata['document_detected'] and metadata['cropped'] and not metadata['enhanced']
    metrics = canary.tinted_boundary_metrics(source, mask, result)
    assert metrics['border_desk_fraction'] < .04, metrics
    assert max(metrics['corner_desk_fractions']) < .10, metrics
    assert result.width * result.height < source.width * source.height * .8
    if rotation is not None:
        source = source.transpose(Image.Transpose.ROTATE_270)
        result = result.transpose(Image.Transpose.ROTATE_270)
    assert canary.validate_tinted_writing(source, result)['blue_stamp_and_handwriting_preserved']


@pytest.mark.parametrize('paper_kind,desk_kind', [('yellow', 'bright'), ('dark', 'bright'), ('yellow', 'dark')])
def test_default_effect_improves_readability_without_losing_colored_writing(canary, paper_kind, desk_kind):
    source, mask = canary.tinted_document_photo(paper_kind=paper_kind, desk_kind=desk_kind, with_mask=True)
    result, metadata = prepare_image(source)
    assert metadata == {'document_detected': True, 'cropped': True, 'enhanced': True}
    assert canary.validate_tinted_writing(source, result)['all_side_writing_preserved']
    gray = cv2.cvtColor(np.asarray(result), cv2.COLOR_RGB2GRAY)
    before = cv2.cvtColor(np.asarray(source), cv2.COLOR_RGB2GRAY)[mask > 248]
    assert np.percentile(gray, 75) > np.percentile(before, 75) + 20
    print_pixels = gray[gray < 100]
    assert print_pixels.size > 3000
    assert np.percentile(gray, 75) - np.median(print_pixels) > 110


@pytest.mark.parametrize('auto_crop,enhance_text', [(False, False), (False, True), (True, False)])
def test_tinted_switches_are_independent(canary, auto_crop, enhance_text):
    source = canary.tinted_document_photo()
    result, metadata = prepare_image(source, auto_crop=auto_crop, enhance_text=enhance_text)
    assert metadata['cropped'] is auto_crop
    assert metadata['enhanced'] is enhance_text
    if not auto_crop:
        assert result.size == source.size
        assert result.getpixel((30, 30)) == source.getpixel((30, 30))
    if not auto_crop and not enhance_text:
        assert result.tobytes() == source.tobytes()


def _tinted_full_frame():
    image = Image.new('RGB', (600, 780), (213, 194, 149))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype('processors/assets/fonts/NotoSans-Regular.ttf', 22)
    draw.text((10, 8), 'Upper edge note', font=font, fill=(25, 25, 25))
    draw.text((10, 740), 'Lower edge note', font=font, fill=(25, 25, 25))
    draw.rectangle((70, 140, 530, 630), outline=(30, 30, 30), width=12)
    for top in range(165, 610, 38):
        draw.text((90, top), 'Sample table row: retain the whole page', font=font, fill=(30, 30, 30))
    draw.text((2, 375), 'LEFT', font=font, fill=(15, 40, 135))
    draw.text((541, 375), 'RIGHT', font=font, fill=(15, 40, 135))
    return image


def test_full_frame_tinted_scan_does_not_crop_its_internal_table():
    source = _tinted_full_frame()
    result, metadata = prepare_image(source, enhance_text=False)
    assert metadata['cropped'] is False
    assert result.size == source.size and result.tobytes() == source.tobytes()


def test_partial_tinted_sheet_cannot_be_replaced_by_its_internal_frame():
    source = Image.new('RGB', (720, 900), (237, 238, 235))
    page = _tinted_full_frame().resize((660, 858))
    source.paste(page, (140, 26))  # Its actual right edge is outside the photograph.
    result, metadata = prepare_image(source, enhance_text=False)
    assert metadata['cropped'] is False
    assert result.size == source.size and result.tobytes() == source.tobytes()


def two_tinted_sheets():
    """A warm sheet beside a smaller gray copy on one bright desk."""
    source = Image.new('RGB', (900, 900), (238, 239, 236))
    source.paste(_tinted_full_frame().resize((350, 520)), (50, 140))
    second = _tinted_full_frame().convert('L').convert('RGB').resize((230, 345))
    source.paste(second, (575, 280))
    return source


def tinted_appliance_panel(panel_color):
    """A tinted curved panel with vent slots and a knob, but no writing."""
    source = Image.new('RGB', (720, 900), (237, 238, 235))
    draw = ImageDraw.Draw(source)
    draw.polygon(((140, 90), (601, 143), (561, 819), (88, 746)), fill=panel_color)
    for top in range(280, 470, 23):
        draw.line((190, top, 489, top + 31), fill=(74, 76, 73), width=5)
    draw.ellipse((350, 550, 435, 635), fill=(83, 84, 80), outline=(40, 40, 40), width=5)
    return source


def _scaled(image, scale):
    """The same photograph as a smaller or larger phone upload."""
    if scale == 1:
        return image
    return image.resize((round(image.width * scale), round(image.height * scale)),
                        Image.Resampling.LANCZOS)


def test_two_tinted_sheets_do_not_silently_discard_the_smaller_page():
    source = two_tinted_sheets()
    result, metadata = prepare_image(source)
    assert metadata == {'document_detected': False, 'cropped': False, 'enhanced': True}
    assert result.size == source.size
    crop_only, flags = prepare_image(source, enhance_text=False)
    assert flags == {'document_detected': False, 'cropped': False, 'enhanced': False}
    assert crop_only.tobytes() == source.tobytes()


@pytest.mark.parametrize('panel_color', [(213, 194, 149), (154, 155, 157)], ids=['warm', 'gray'])
def test_tinted_appliance_panel_without_writing_is_not_a_document(panel_color):
    source = tinted_appliance_panel(panel_color)
    result, metadata = prepare_image(source)
    assert metadata == {'document_detected': False, 'cropped': False, 'enhanced': True}
    assert result.size == source.size
    crop_only, flags = prepare_image(source, enhance_text=False)
    assert flags == {'document_detected': False, 'cropped': False, 'enhanced': False}
    assert crop_only.tobytes() == source.tobytes()


@pytest.mark.parametrize('panel_color', [(213, 194, 149), (154, 155, 157)], ids=['warm', 'gray'])
@pytest.mark.parametrize('scale,soft_focus', [(.5, False), (1.5, False), (2, False), (3, False), (1, True)],
                         ids=['half', '1.5x', '2x', '3x', 'soft-focus'])
def test_tinted_appliance_panel_is_never_cropped_at_other_resolutions(panel_color, scale, soft_focus):
    source = _scaled(tinted_appliance_panel(panel_color), scale)
    if soft_focus:
        source = source.filter(ImageFilter.GaussianBlur(1.2))
    crop_only, flags = prepare_image(source, enhance_text=False)
    assert flags == {'document_detected': False, 'cropped': False, 'enhanced': False}
    assert crop_only.size == source.size and crop_only.tobytes() == source.tobytes()


@pytest.mark.parametrize('scale,threshold', [
    (1, 3),
    (2, 2),
    # At exactly this sharpening threshold the larger sheet's straight contour
    # qualifies on the contour path; segmentation must still reveal the second.
    (2, 3),
], ids=['full-size', 'double-size', 'double-size-threshold-3'])
def test_sharpened_two_tinted_sheets_are_not_one_document(scale, threshold):
    source = _scaled(two_tinted_sheets(), scale)
    source = source.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=threshold))
    crop_only, flags = prepare_image(source, enhance_text=False)
    assert flags == {'document_detected': False, 'cropped': False, 'enhanced': False}
    assert crop_only.size == source.size and crop_only.tobytes() == source.tobytes()
