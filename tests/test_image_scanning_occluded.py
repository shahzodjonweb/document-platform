"""Anonymous held-paper photos: tight crop despite a small blank-edge occlusion.

Paper and occluder alpha are rendered before the camera, independently of the
detector. No customer photo, wording, signature or barcode appears in fixtures.
"""
import io
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader

from processors.document_scan import prepare_image
from processors.sandbox import execute_sandbox


PAGE_SIZE = (450, 680)
PHOTO_SIZE = (720, 1280)
PAGE_CORNERS = np.array(((35, 157), (623, 163), (653, 950), (76, 978)), np.float32)


def _font(size):
    return ImageFont.truetype(str(Path(__file__).resolve().parents[1]
                                 / 'processors/assets/fonts/NotoSans-Regular.ttf'), size)


def _generic_form(*, exposure=0, strong_shadow=False):
    width, height = PAGE_SIZE
    yy, xx = np.mgrid[:height, :width].astype(np.float32)
    x, y = xx / (width - 1), yy / (height - 1)
    gradient = 179 + 26 * x + 15 * y + exposure
    shadow = (24 if strong_shadow else 12) * np.exp(-((x - .25)**2 / .14 + (y - .35)**2 / .35))
    gray = np.clip(gradient - shadow, 0, 255)
    gray += np.random.default_rng(3481).normal(0, .8, gray.shape)
    paper = Image.fromarray(np.repeat(np.clip(gray, 0, 255).astype(np.uint8)[:, :, None], 3, axis=2))
    draw = ImageDraw.Draw(paper)
    draw.text((113, 18), 'DOCUMENT CHECK', font=_font(19), fill=(20, 20, 20))
    draw.rectangle((18, 50, 431, 635), outline=(31, 31, 31), width=2)
    for left, right, top, bottom in ((18, 431, 51, 67), (18, 431, 163, 180),
                                    (18, 431, 284, 300), (18, 431, 407, 423)):
        draw.rectangle((left, top, right, bottom), fill=(40, 40, 40))
    for top, value in ((71, 'Sample reference A27'), (102, 'Review: generic entry'),
                       (132, 'Type: document sample'), (189, 'Route: location A to B'),
                       (218, 'Inspection: complete'), (247, 'Keep all written marks')):
        draw.text((25, top), value, font=_font(14), fill=(25, 25, 25))
    draw.line((226, 67, 226, 284), fill=(35, 35, 35), width=2)
    # A deterministic, anonymous stripe code; never copied from a shipment.
    cursor = 252
    for number, bar_width in enumerate((2, 1, 3, 2, 1, 2, 4, 1, 3, 1, 2, 3,
                                        1, 4, 2, 1, 3, 2, 1, 2, 3, 1, 4, 2,
                                        1, 3, 2, 1, 2, 4, 1, 3, 2, 1)):
        draw.rectangle((cursor, 82, cursor + bar_width - 1, 118), fill=(22, 22, 22))
        cursor += bar_width + (1 if number % 3 == 0 else 2)
    draw.text((258, 126), 'SAMPLE 2741', font=_font(13), fill=(22, 22, 22))
    for top, value in zip(range(154, 280, 15), (
            'Entry type: sample form', 'Operator: generic example',
            'Reference: sample only', 'Checked: all rows below',
            'Quantity: see the table', 'Keep the original writing',
            'No customer details here', 'This is generated print', 'Review before acceptance')):
        draw.text((233, top), value, font=_font(11), fill=(24, 24, 24))
    for left in (130, 218, 298, 365):
        draw.line((left, 301, left, 407), fill=(35, 35, 35), width=1)
    for top in (323, 344, 365, 386):
        draw.line((18, top, 431, top), fill=(35, 35, 35), width=1)
    for top, label in zip((306, 327, 348, 369, 390), ('Item   Qty   Weight', 'A01     2     1.25',
                                                             'B02     1     2.50', 'C03     4     0.75', 'Total   7     4.50')):
        draw.text((25, top), label, font=_font(12), fill=(23, 23, 23))
        for left, value in ((236, '12.50'), (309, 'GENERIC'), (375, '02.00')):
            draw.text((left, top), value, font=_font(10), fill=(23, 23, 23))
    draw.line((226, 423, 226, 635), fill=(35, 35, 35), width=2)
    for top in (465, 507):
        draw.line((18, top, 431, top), fill=(35, 35, 35), width=1)
    for top, label in ((430, 'Handling: keep dry'), (472, 'Review: all sample items'),
                       (515, 'Generic acknowledgement')):
        draw.text((25, top), label, font=_font(13), fill=(27, 27, 27))
    for top, value in zip(range(431, 628, 15), (
            'Generated form for testing', 'All quantities are examples',
            'Keep every field legible', 'Review the printed details',
            'The table must remain whole', 'Edges show margin labels',
            'The stripe code stays clear', 'All blue pen strokes remain',
            'Do not remove small notes', 'Preserve generic footer text',
            'No identity or address used', 'Camera shadows vary gently',
            'Page boundaries stay visible', 'End of the generic checklist')):
        draw.text((234, top), value, font=_font(10), fill=(25, 25, 25))
    draw.text((25, 613), 'END OF SAMPLE', font=_font(13), fill=(24, 24, 24))
    draw.line(((32, 590), (55, 564), (61, 595), (86, 574), (106, 589),
               (134, 567), (143, 595), (183, 579), (205, 588)), fill=(14, 42, 144), width=3)
    for position, value, color in zip(((7, 4), (width - 45, 4), (7, height - 29), (width - 45, height - 29)),
                                     ('A1', 'B2', 'C3', 'D4'),
                                     ((130, 14, 19), (12, 105, 24), (158, 74, 10), (127, 18, 116))):
        draw.text(position, value, font=_font(18), fill=color)
    for position, value in zip(((3, height // 2 - 12), (width - 34, height // 2 - 12),
                                (width // 2 - 13, 1), (width // 2 - 13, height - 25)), ('E5', 'F6', 'G7', 'H8')):
        draw.text(position, value, font=_font(18), fill=(12, 100, 100))
    return paper


def occluded_document_photo(*, exposure=0, strong_shadow=False, curved=True,
                            finger_x=.42, rotation=None, occlusion='blank_edge'):
    """Render a complete held page, independent material/occlusion masks included."""
    width, height = PAGE_SIZE
    paper = _generic_form(exposure=exposure, strong_shadow=strong_shadow)
    margin = 22 if curved else 0
    if curved:
        yy, xx = np.mgrid[:height + 2 * margin, :width + 2 * margin].astype(np.float32)
        map_x = xx - margin - 10 * np.sin(np.pi * np.clip((yy - margin) / (height - 1), 0, 1))
        map_y = yy - margin + 7 * np.sin(np.pi * np.clip((xx - margin) / (width - 1), 0, 1))
        rgb = cv2.remap(np.asarray(paper), map_x, map_y, cv2.INTER_LINEAR,
                        borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
        alpha = cv2.remap(np.full((height, width), 255, np.uint8), map_x, map_y,
                          cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    else:
        rgb, alpha = np.asarray(paper), np.full((height, width), 255, np.uint8)
    source = np.array(((margin, margin), (width - 1 + margin, margin),
                       (width - 1 + margin, height - 1 + margin), (margin, height - 1 + margin)), np.float32)
    transform = cv2.getPerspectiveTransform(source, PAGE_CORNERS)
    warped = cv2.warpPerspective(rgb, transform, PHOTO_SIZE, flags=cv2.INTER_LINEAR)
    paper_alpha = cv2.warpPerspective(alpha, transform, PHOTO_SIZE, flags=cv2.INTER_LINEAR)
    coverage = paper_alpha.astype(np.float32) / 255
    yy, xx = np.mgrid[:PHOTO_SIZE[1], :PHOTO_SIZE[0]].astype(np.float32)
    texture = 3 * np.sin(xx * .7) * np.sin(yy * .47)
    radius = np.sqrt(((xx - 360) / .93)**2 + ((yy - 621) / 1.10)**2)
    rim = np.abs(radius - 472) < 52
    desk = 24 + texture + 14 * rim + 9 * xx / PHOTO_SIZE[0]
    desk[:115] += 36  # A generic dashboard, still distinct from the held paper.
    background = np.stack((desk, desk + 4, desk + 8), axis=2)
    photographed = background * (1 - coverage[:, :, None]) + warped * coverage[:, :, None]
    image = Image.fromarray(np.clip(photographed, 0, 255).astype(np.uint8))
    occluder = Image.new('L', PHOTO_SIZE, 0)
    marks = ImageDraw.Draw(occluder)
    point = cv2.perspectiveTransform(np.array([[[finger_x * (width - 1) + margin,
                                                height - 1 + margin]]], np.float32), transform)[0, 0]
    x, y = map(float, point)
    if occlusion == 'blank_edge':
        # Only six original paper pixels are covered; all annotations above
        # this physical blank margin remain visible. The fingertip is generic.
        marks.ellipse((x - 20, y - 9, x + 21, y + 94), fill=255)
    elif occlusion == 'writing':
        marks.ellipse((x - 38, y - 103, x + 37, y + 96), fill=255)
    elif occlusion == 'corner':
        x, y = map(float, PAGE_CORNERS[3])
        marks.ellipse((x - 45, y - 78, x + 49, y + 92), fill=255)
    elif occlusion != 'none':
        raise ValueError('Unknown synthetic occlusion')
    finger_alpha = np.asarray(occluder).astype(np.float32) / 255
    skin = np.stack((154 + 9 * np.sin(yy / 21), 101 + 6 * np.sin(yy / 21),
                     74 + 5 * np.sin(yy / 21)), axis=2)
    photographed = np.asarray(image).astype(np.float32) * (1 - finger_alpha[:, :, None]) + skin * finger_alpha[:, :, None]
    photographed = cv2.GaussianBlur(np.clip(photographed, 0, 255).astype(np.uint8), (3, 3), .5)
    image, paper_mask, finger_mask = Image.fromarray(photographed), Image.fromarray(paper_alpha), occluder
    if rotation is not None:
        image, paper_mask, finger_mask = (item.transpose(rotation) for item in (image, paper_mask, finger_mask))
    return image, np.asarray(paper_mask), np.asarray(finger_mask)


def _boundary_metrics(source, paper_mask, finger_mask, result):
    # Skin occludes a small blank edge and must not be mistaken for dark desk.
    source_gray = cv2.cvtColor(np.asarray(source), cv2.COLOR_RGB2GRAY)
    desk = source_gray[(paper_mask < 8) & (finger_mask < 8)]
    paper = source_gray[(paper_mask > 248) & (finger_mask < 8)]
    desk_top, paper_light = np.percentile(desk, 98), np.percentile(paper, 65)
    assert paper_light - desk_top > 30, 'Fixture materials are independently distinguishable'
    threshold = (desk_top + paper_light) / 2
    rgb = np.asarray(result).astype(np.int16)
    gray = cv2.cvtColor(np.asarray(result), cv2.COLOR_RGB2GRAY)
    desk_like = (gray < threshold) & (rgb.max(axis=2) - rgb.min(axis=2) < 28)
    band = max(2, round(min(result.size) * .025))
    border = np.ones(gray.shape, bool); border[band:-band, band:-band] = False
    corners = (desk_like[:band, :band], desk_like[:band, -band:],
               desk_like[-band:, :band], desk_like[-band:, -band:])
    return {'border_desk_fraction': float(desk_like[border].mean()),
            'corner_desk_fractions': [float(part.mean()) for part in corners]}


def _barcode_scanline_metrics(image):
    """Read narrow skewed stripes along rows, rather than blurring rows together."""
    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    height, width = gray.shape
    # Leave the neighboring printed table frame outside the stripe-code region.
    barcode = gray[round(height * .125):round(height * .173), round(width * .55):round(width * .92)]
    low, high = np.percentile(barcode, 15, axis=1), np.percentile(barcode, 90, axis=1)
    counts = []
    for fraction in (.35, .45, .55, .65):
        threshold = low + fraction * (high - low)
        binary = barcode < threshold[:, None]
        counts.append(np.count_nonzero(np.diff(binary.astype(np.int8), axis=1), axis=1))
    transitions = np.max(counts, axis=0)
    transitions[high - low < 50] = 0  # Plain paper/noise is not a readable stripe code.
    return int(np.median(transitions)), int(transitions.max())


def _writing_metrics(image):
    rgb = np.asarray(image).astype(np.int16)
    height, width = rgb.shape[:2]
    regions = (rgb[:height // 4, :width // 4], rgb[:height // 4, 3 * width // 4:],
               rgb[3 * height // 4:, :width // 4], rgb[3 * height // 4:, 3 * width // 4:])
    rules = (lambda p: (p[:, :, 0] > p[:, :, 1] + 45) & (p[:, :, 0] > p[:, :, 2] + 45),
             lambda p: (p[:, :, 1] > p[:, :, 0] + 35) & (p[:, :, 1] > p[:, :, 2] + 35),
             lambda p: (p[:, :, 0] > p[:, :, 1] + 45) & (p[:, :, 1] > p[:, :, 2] + 35),
             lambda p: (p[:, :, 0] > p[:, :, 1] + 45) & (p[:, :, 2] > p[:, :, 1] + 45))
    corner_counts = [int(rule(region).sum()) for region, rule in zip(regions, rules)]
    cyan = (rgb[:, :, 1] > rgb[:, :, 0] + 25) & (rgb[:, :, 2] > rgb[:, :, 0] + 25)
    parts = (cyan[height // 3:2 * height // 3, :width // 4],
             cyan[height // 3:2 * height // 3, 3 * width // 4:],
             cyan[:height // 4, width // 3:2 * width // 3],
             cyan[3 * height // 4:, width // 3:2 * width // 3])
    coordinates = [np.where(part) for part in parts]
    assert all(len(y) > 25 for y, x in coordinates), 'Each margin annotation must remain'
    gaps = (coordinates[0][1].min() / width,
            (width - 1 - (3 * width // 4 + coordinates[1][1].max())) / width,
            coordinates[2][0].min() / height,
            (height - 1 - (3 * height // 4 + coordinates[3][0].max())) / height)
    blue = (rgb[:, :, 2] > rgb[:, :, 0] + 50) & (rgb[:, :, 2] > rgb[:, :, 1] + 45)
    signature = blue[3 * height // 4:15 * height // 16, :width // 2]
    transitions, best_line = _barcode_scanline_metrics(image)
    return {'corner_counts': corner_counts, 'side_gaps': gaps,
            'signature_pixels': int(signature.sum()), 'barcode_transitions': transitions,
            'barcode_complete_line': best_line}


def _assert_print_and_ink(result):
    metrics = _writing_metrics(result)
    assert min(metrics['corner_counts']) > 20, metrics
    assert metrics['signature_pixels'] > 200, metrics
    assert metrics['barcode_transitions'] >= 48 and metrics['barcode_complete_line'] >= 68, 'Barcode must keep complete readable scanlines'
    assert all(gap < limit for gap, limit in zip(metrics['side_gaps'], (.04, .06, .04, .035))), metrics
    gray = cv2.cvtColor(np.asarray(result), cv2.COLOR_RGB2GRAY)
    assert int((gray < 100).sum()) > 5000, 'Dense printed table must stay readable'


@pytest.mark.parametrize('variant', [
    {}, {'curved': False}, {'exposure': -18, 'strong_shadow': True},
    {'exposure': 25}, {'finger_x': .28}, {'finger_x': .72},
    {'rotation': Image.Transpose.ROTATE_90},
    {'rotation': Image.Transpose.ROTATE_90, 'strong_shadow': True, 'finger_x': .68},
], ids=['bowed', 'flat', 'low-light', 'bright', 'left-finger', 'right-finger', 'quarter-turn', 'rotated-shadow'])
def test_small_blank_edge_occlusion_keeps_tight_page_boundary_and_all_writing(variant):
    source, paper_mask, finger_mask = occluded_document_photo(**variant)
    result, metadata = prepare_image(source, enhance_text=False)
    assert metadata['document_detected'] and metadata['cropped'] and not metadata['enhanced']
    metrics = _boundary_metrics(source, paper_mask, finger_mask, result)
    assert metrics['border_desk_fraction'] < .04, metrics
    assert max(metrics['corner_desk_fractions']) < .10, metrics
    assert result.width * result.height < source.width * source.height * .8
    if variant.get('rotation') is not None:
        result = result.transpose(Image.Transpose.ROTATE_270)
    _assert_print_and_ink(result)


def test_default_effect_keeps_signature_barcode_and_dense_table():
    source, _, _ = occluded_document_photo(strong_shadow=True)
    result, metadata = prepare_image(source)
    assert metadata == {'document_detected': True, 'cropped': True, 'enhanced': True}
    _assert_print_and_ink(result)
    gray = cv2.cvtColor(np.asarray(result), cv2.COLOR_RGB2GRAY)
    assert np.percentile(gray, 75) > 215


@pytest.mark.parametrize('auto_crop,enhance_text', [(False, False), (False, True), (True, False)])
def test_held_document_switches_are_independent(auto_crop, enhance_text):
    source, _, _ = occluded_document_photo()
    result, metadata = prepare_image(source, auto_crop=auto_crop, enhance_text=enhance_text)
    assert metadata['cropped'] is auto_crop and metadata['enhanced'] is enhance_text
    if not auto_crop:
        assert result.size == source.size
        assert result.getpixel((10, 30)) == source.getpixel((10, 30))
    if not auto_crop and not enhance_text:
        assert result.tobytes() == source.tobytes()


def test_hidden_corner_remains_a_conservative_full_photo():
    source, _, _ = occluded_document_photo(occlusion='corner')
    result, metadata = prepare_image(source, enhance_text=False)
    assert metadata['cropped'] is False
    assert result.size == source.size and result.tobytes() == source.tobytes()


def test_barcode_rows_survive_independently_known_curved_camera_geometry():
    source, _, _ = occluded_document_photo()
    tl, tr, br, bl = PAGE_CORNERS
    width = round((np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2)
    height = round((np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2)
    destination = np.array(((0, 0), (width - 1, 0), (width - 1, height - 1), (0, height - 1)), np.float32)
    transform = cv2.getPerspectiveTransform(PAGE_CORNERS, destination)
    # This camera-only inverse uses no detector, fitted curve or worker code.
    camera_crop = Image.fromarray(cv2.warpPerspective(np.asarray(source), transform, (width, height)))
    median_rows, complete_line = _barcode_scanline_metrics(camera_crop)
    assert median_rows >= 48 and complete_line >= 68


@pytest.mark.parametrize('left', [252, 330], ids=['erased-code', 'missing-last-stripes'])
def test_barcode_scanline_check_rejects_erased_or_narrowed_codes(left):
    pixels = np.array(_generic_form())
    pixels[81:120, left:407] = (196, 196, 196)
    with pytest.raises(AssertionError, match='Barcode'):
        _assert_print_and_ink(Image.fromarray(pixels))


@pytest.mark.parametrize('parameters', [{}, {'auto_crop': True, 'enhance_text': False}])
def test_anonymous_held_document_in_actual_bounded_worker_pdf(tmp_path, parameters):
    source, paper_mask, finger_mask = occluded_document_photo()
    path = tmp_path / 'generic-held-page.png'; source.save(path)
    result = execute_sandbox('pdf.images_to_pdf', [path], parameters, tmp_path / 'out')
    reader = PdfReader(result['artifacts'][0]['path'])
    assert len(reader.pages) == 1 and len(reader.pages[0].images) == 1
    page = reader.pages[0]
    image = page.images[0].image.convert('RGB')
    width, height = float(page.mediabox.width), float(page.mediabox.height)
    from reportlab.lib.pagesizes import A4
    from scripts.operations.service_checks_documents import validate_fit_canvas
    assert (width, height) == pytest.approx(A4, abs=.001)
    assert validate_fit_canvas(reader, image)['a4_page_verified']
    _assert_print_and_ink(image)
    if parameters:
        metrics = _boundary_metrics(source, paper_mask, finger_mask, image)
        assert metrics['border_desk_fraction'] < .04, metrics
        assert max(metrics['corner_desk_fractions']) < .10, metrics
    else:
        gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
        assert np.percentile(gray, 75) > 215
