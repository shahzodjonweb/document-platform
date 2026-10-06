"""Anonymized photographs that cover underexposed, curved paper on a gray desk.

The form and photograph are generated here from generic words and marks. They
contain no customer image, address, identity, signature or shipment information.
Geometry, illumination, paper curl and camera noise are independent of detector
implementation details, so this remains a regression fixture across algorithms.
"""
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from processors.document_scan import prepare_image


SIZE = (720, 900)
PAGE_SIZE = (450, 680)
CORNERS = np.array([(140, 90), (601, 143), (561, 819), (88, 746)], np.float32)
CORNER_COLORS = [(110, 18, 21), (14, 88, 26), (17, 42, 119), (108, 21, 101)]


def _font(size):
    return ImageFont.truetype(str(Path(__file__).resolve().parents[1]
                                 / 'processors/assets/fonts/NotoSans-Regular.ttf'), size)


def _shipment_form(*, blank=False, exposure=0):
    """Paper with gradual poor lighting, generic print, a table and pen strokes."""
    width, height = PAGE_SIZE
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    x /= width - 1
    y /= height - 1
    broad_shadow = 13 * np.exp(-((x - .18) ** 2 / .10 + (y - .72) ** 2 / .18))
    light = 133 + 34 * x + 13 * y - broad_shadow
    noise = np.random.default_rng(1729).normal(0, 1.1, light.shape)
    light = np.clip(light + noise + exposure, 130 + exposure, 180 + exposure).astype(np.uint8)
    if blank:
        light = np.clip(light.astype(np.int16) + 75, 0, 255).astype(np.uint8)
    paper = Image.fromarray(np.repeat(light[:, :, None], 3, axis=2), 'RGB')
    if blank:
        return paper
    draw = ImageDraw.Draw(paper)
    draw.text((80, 38), 'SHIPMENT RECORD', font=_font(21), fill=(25, 25, 25))
    draw.text((30, 84), 'Reference: SAMPLE A12', font=_font(16), fill=(38, 38, 38))
    draw.text((30, 111), 'Route: Depot A to Depot B', font=_font(16), fill=(38, 38, 38))
    draw.text((30, 138), 'Date: sample entry', font=_font(16), fill=(38, 38, 38))
    draw.rectangle((29, 192, 419, 452), outline=(33, 33, 33), width=2)
    for top in [238, 292, 345, 399]:
        draw.line((29, top, 419, top), fill=(42, 42, 42), width=2)
    for left in [239, 320]:
        draw.line((left, 192, left, 452), fill=(42, 42, 42), width=2)
    for left, value in [(40, 'Item'), (251, 'Units'), (330, 'Weight')]:
        draw.text((left, 205), value, font=_font(15), fill=(25, 25, 25))
    for top, name, units, weight in [(250, 'Parcel A', '02', '1.5'),
                                    (304, 'Parcel B', '01', '2.0'),
                                    (357, 'Parcel C', '03', '0.8'),
                                    (410, 'Total', '06', '4.3')]:
        for left, value in [(40, name), (251, units), (334, weight)]:
            draw.text((left, top), value, font=_font(16), fill=(30, 30, 30))
    draw.text((31, 492), 'Received: sample acknowledgement', font=_font(16), fill=(32, 32, 32))
    # Generic pen strokes, not a person's signature.
    draw.line([(57, 558), (91, 531), (104, 560), (136, 538),
               (160, 556), (186, 540), (210, 553), (247, 546)],
              fill=(17, 42, 119), width=4)
    draw.text((30, 594), 'Inspect all items before accepting.', font=_font(16), fill=(30, 30, 30))
    # Colored writing close to every visible corner catches inward edge crops.
    for location, value, color in zip([(12, 10), (width - 53, 10),
                                       (12, height - 34), (width - 53, height - 34)],
                                      ['A1', 'B2', 'C3', 'D4'], CORNER_COLORS):
        draw.text(location, value, font=_font(21), fill=color)
    # Mid-edge labels catch a crop that keeps the corners but clips bowed sides.
    for location, value in zip([(4, height // 2 - 14), (width - 42, height // 2 - 14),
                                (width // 2 - 15, 2), (width // 2 - 15, height - 28)],
                               ['E5', 'F6', 'G7', 'H8']):
        draw.text(location, value, font=_font(21), fill=CORNER_COLORS[-1])
    return paper


def _curled(paper):
    """Gently bow the photographed edges without hiding any of the four corners."""
    margin = 26
    width, height = paper.size
    yy, xx = np.mgrid[0:height + 2 * margin, 0:width + 2 * margin].astype(np.float32)
    x = (xx - margin) / (width - 1)
    y = (yy - margin) / (height - 1)
    map_x = xx - margin - 17 * np.sin(np.pi * np.clip(y, 0, 1))
    map_y = yy - margin + 11 * np.sin(np.pi * np.clip(x, 0, 1))
    rgb = cv2.remap(np.asarray(paper), map_x, map_y, cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
    alpha = cv2.remap(np.full((height, width), 255, np.uint8), map_x, map_y,
                      cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return rgb, alpha, margin


def _desk(size, *, light=False):
    yy, xx = np.mgrid[0:size[1], 0:size[0]].astype(np.float32)
    desk = ((217 if light else 112) + 6 * np.sin((yy + .16 * xx) * np.pi / 12)
            + 4 * xx / size[0] + 2 * yy / size[1])
    return np.repeat(desk[:, :, None], 3, axis=2)


def _place_paper(paper, corners, background):
    """Place a bowed sheet on an existing desk so multiple sheets can coexist."""
    rgb, alpha, margin = _curled(paper)
    width, height = paper.size
    size = (background.shape[1], background.shape[0])
    source = np.array([(margin, margin), (width - 1 + margin, margin),
                       (width - 1 + margin, height - 1 + margin),
                       (margin, height - 1 + margin)], np.float32)
    transform = cv2.getPerspectiveTransform(source, np.asarray(corners, np.float32))
    warped = cv2.warpPerspective(rgb, transform, size, flags=cv2.INTER_LINEAR)
    mask = cv2.warpPerspective(alpha, transform, size, flags=cv2.INTER_LINEAR).astype(np.float32) / 255
    # A shallow cast shadow makes the paper's outer edge naturally uneven.
    shadow = cv2.GaussianBlur(mask, (0, 0), 5)
    background = np.clip(background - 9 * shadow[:, :, None] * (1 - mask[:, :, None]), 0, 255)
    photographed = background * (1 - mask[:, :, None]) + warped * mask[:, :, None]
    return photographed


def photographed_shipment_form(*, light_desk=False, blank_appliance=False, exposure=0, corners=CORNERS):
    """Perspective photograph with ribbed desk texture, curl, shade and mild blur."""
    paper = _shipment_form(blank=blank_appliance, exposure=exposure)
    photographed = _place_paper(paper, corners, _desk(SIZE, light=light_desk))
    photographed = cv2.GaussianBlur(np.clip(photographed, 0, 255).astype(np.uint8), (3, 3), .55)
    return Image.fromarray(photographed, 'RGB')


def two_unequal_gray_sheets():
    background = _desk((1100, 900))
    background = _place_paper(_shipment_form(exposure=17),
        [(60, 92), (602, 122), (582, 824), (34, 786)], background)
    background = _place_paper(_shipment_form(exposure=17),
        [(730, 206), (1029, 234), (1008, 704), (716, 677)], background)
    return Image.fromarray(np.clip(background, 0, 255).astype(np.uint8), 'RGB')


def ordinary_gray_photo():
    """Monochrome scenery has texture and dark marks, but no paper outline."""
    width, height = SIZE
    yy, _ = np.mgrid[0:height, 0:width].astype(np.float32)
    sky = np.clip(178 - 42 * yy / height, 0, 255).astype(np.uint8)
    image = Image.fromarray(np.repeat(sky[:, :, None], 3, axis=2), 'RGB')
    draw = ImageDraw.Draw(image)
    draw.ellipse((140, 140, 500, 230), fill=(205, 205, 205))
    draw.polygon([(0, 610), (125, 355), (300, 585), (510, 380), (720, 630), (720, 900), (0, 900)],
                 fill=(104, 104, 104))
    draw.ellipse((-140, 625, 920, 1070), fill=(72, 72, 72))
    draw.line((0, 730, 720, 793), fill=(44, 44, 44), width=24)
    draw.line((540, 372, 518, 746), fill=(48, 48, 48), width=18)
    for top, left, right in [(418, 426, 631), (477, 410, 640), (550, 388, 647)]:
        draw.line((left, top, 529, top - 39, right, top + 7), fill=(55, 55, 55), width=13)
    return image


def photographed_gray_appliance():
    """A gray curved device cover has vents and a knob, but no written content."""
    panel = _shipment_form(blank=True, exposure=-75)
    draw = ImageDraw.Draw(panel)
    for top in (230, 260, 290, 320):
        draw.rounded_rectangle((93, top, 355, top + 8), radius=4, fill=(63, 63, 63))
    draw.ellipse((178, 463, 272, 557), fill=(83, 83, 83), outline=(53, 53, 53), width=3)
    draw.line((225, 479, 225, 509), fill=(44, 44, 44), width=3)
    photographed = _place_paper(panel, CORNERS, _desk(SIZE))
    return Image.fromarray(np.clip(photographed, 0, 255).astype(np.uint8), 'RGB')


def _corner_ink_survives(image):
    rgb = np.asarray(image).astype(np.int16)
    regions = [rgb[:image.height // 4, :image.width // 4],
               rgb[:image.height // 4, 3 * image.width // 4:],
               rgb[3 * image.height // 4:, :image.width // 4],
               rgb[3 * image.height // 4:, 3 * image.width // 4:]]
    rules = [lambda p: (p[:, :, 0] > p[:, :, 1] + 35) & (p[:, :, 0] > p[:, :, 2] + 35),
             lambda p: (p[:, :, 1] > p[:, :, 0] + 25) & (p[:, :, 1] > p[:, :, 2] + 25),
             lambda p: (p[:, :, 2] > p[:, :, 0] + 35) & (p[:, :, 2] > p[:, :, 1] + 25),
             lambda p: (p[:, :, 0] > p[:, :, 1] + 35) & (p[:, :, 2] > p[:, :, 1] + 35)]
    return [int(rule(region).sum()) for rule, region in zip(rules, regions)]


def _mid_edge_ink(image):
    rgb = np.asarray(image).astype(np.int16)
    regions = [rgb[image.height // 3:2 * image.height // 3, :image.width // 4],
               rgb[image.height // 3:2 * image.height // 3, 3 * image.width // 4:],
               rgb[:image.height // 4, image.width // 3:2 * image.width // 3],
               rgb[3 * image.height // 4:, image.width // 3:2 * image.width // 3]]
    return [int(((p[:, :, 0] > p[:, :, 1] + 35) & (p[:, :, 2] > p[:, :, 1] + 35)).sum())
            for p in regions]


@pytest.mark.parametrize('exposure', [0, 17])
def test_default_scanning_recognizes_underexposed_curved_shipment_form(exposure):
    source = photographed_shipment_form(exposure=exposure)
    result, metadata = prepare_image(source)
    assert metadata == {'document_detected': True, 'cropped': True, 'enhanced': True}
    assert result.width * result.height < source.width * source.height * .80
    assert 1.15 < result.height / result.width < 1.8
    assert min(_corner_ink_survives(result)) > 25, 'Writing near every outer corner must survive'
    assert min(_mid_edge_ink(result)) > 45, 'Writing midway along bowed outer sides must survive'


def test_readability_brightens_gray_paper_and_retains_print_and_colored_writing():
    source = photographed_shipment_form()
    cropped, metadata = prepare_image(source, enhance_text=False)
    cleaned, cleaned_metadata = prepare_image(source)
    assert metadata['document_detected'] and metadata['cropped']
    assert metadata['enhanced'] is False
    assert cleaned_metadata['enhanced'] is True
    assert cropped.size == cleaned.size
    before, after = np.asarray(cropped).astype(np.int16), np.asarray(cleaned).astype(np.int16)
    gray_paper = ((before.min(axis=2) > 120) & (before.max(axis=2) < 190)
                  & (before.max(axis=2) - before.min(axis=2) < 8))
    assert gray_paper.mean() > .5
    assert np.median(after[gray_paper]) > np.median(before[gray_paper]) + 40
    printed_ink = (before.max(axis=2) < 65)
    assert printed_ink.sum() > 3000
    assert np.median(after[gray_paper]) - np.median(after[printed_ink]) > 110
    assert min(_corner_ink_survives(cleaned)) > 25
    assert min(_mid_edge_ink(cleaned)) > 45


@pytest.mark.parametrize('auto_crop,enhance_text', [(False, False), (True, False), (False, True)])
def test_switches_remain_independent_for_realistic_dark_paper(auto_crop, enhance_text):
    source = photographed_shipment_form()
    result, metadata = prepare_image(source, auto_crop=auto_crop, enhance_text=enhance_text)
    if not auto_crop and not enhance_text:
        assert metadata == {'document_detected': False, 'cropped': False, 'enhanced': False}
        assert result.size == source.size and result.tobytes() == source.tobytes()
    else:
        assert metadata['document_detected'] is True
        assert metadata['cropped'] is auto_crop
        assert metadata['enhanced'] is enhance_text
        if not auto_crop:
            assert result.size == source.size
            assert result.getpixel((35, 35)) == source.getpixel((35, 35)), 'The desk is outside the effect'
        else:
            assert result.width * result.height < source.width * source.height * .80
            assert min(_corner_ink_survives(result)) > 25
            assert all(after >= before * .75 for before, after in
                       zip(_mid_edge_ink(source), _mid_edge_ink(result))), 'Bowed-side writing must remain'


def test_bright_curved_surface_without_writing_is_not_a_document():
    source = photographed_shipment_form(blank_appliance=True)
    result, metadata = prepare_image(source)
    assert metadata == {'document_detected': False, 'cropped': False, 'enhanced': False}
    assert result.size == source.size and result.tobytes() == source.tobytes()


def test_gray_paper_on_light_desk_never_loses_corner_writing():
    source = photographed_shipment_form(light_desk=True)
    result, metadata = prepare_image(source)
    if metadata['cropped']:
        assert min(_corner_ink_survives(result)) > 25
        assert 1.15 < result.height / result.width < 1.8
    else:
        assert result.size == source.size
        if not metadata['enhanced']:
            assert result.tobytes() == source.tobytes()


@pytest.mark.parametrize('exposure', [0, 17])
def test_full_frame_gray_form_is_never_cropped_to_its_inner_table(exposure):
    source = _shipment_form(exposure=exposure)
    result, metadata = prepare_image(source, enhance_text=False)
    assert metadata['cropped'] is False
    assert result.size == source.size and result.tobytes() == source.tobytes()
    assert min(_corner_ink_survives(result)) > 25


@pytest.mark.parametrize('corners', [
    [(-34, 45), (590, 124), (553, 827), (-40, 740)],
    [(140, -25), (610, 120), (560, 800), (75, 745)],
])
def test_partial_gray_sheet_with_hidden_corner_is_preserved(corners):
    source = photographed_shipment_form(exposure=17, corners=corners)
    result, metadata = prepare_image(source)
    assert metadata['cropped'] is False
    assert metadata['enhanced'] is False
    assert result.size == source.size and result.tobytes() == source.tobytes()


def test_two_unequal_gray_sheets_are_both_preserved():
    source = two_unequal_gray_sheets()
    result, metadata = prepare_image(source)
    assert metadata['cropped'] is False, 'A smaller second document must not be discarded'
    assert metadata['enhanced'] is False
    assert result.size == source.size and result.tobytes() == source.tobytes()


def test_ordinary_grayscale_photo_is_preserved():
    source = ordinary_gray_photo()
    result, metadata = prepare_image(source)
    assert metadata == {'document_detected': False, 'cropped': False, 'enhanced': False}
    assert result.size == source.size and result.tobytes() == source.tobytes()


def test_gray_curved_appliance_with_vents_and_knob_is_preserved():
    source = photographed_gray_appliance()
    result, metadata = prepare_image(source)
    assert metadata == {'document_detected': False, 'cropped': False, 'enhanced': False}
    assert result.size == source.size and result.tobytes() == source.tobytes()
