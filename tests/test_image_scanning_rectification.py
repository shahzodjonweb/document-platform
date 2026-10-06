"""A detected page must fill its rectangular output without photographed desk.

These are procedural, anonymous fixtures. Their paper alpha is known before
rendering, so desk/paper luminance ranges are measured from true source regions,
independently of the detector or its choice of rectification algorithm.
"""
import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw

from processors.document_scan import prepare_image
from tests.test_image_scanning_realistic import (
    CORNERS, PAGE_SIZE, SIZE, _corner_ink_survives, _curled, _desk,
    _mid_edge_ink, _shipment_form, photographed_gray_appliance,
)


def source_and_paper_mask(*, curved=True, rotation=None, paper=None):
    """Return an anonymous photograph and its independently known paper alpha."""
    paper = _shipment_form(exposure=17) if paper is None else paper
    if curved:
        rgb, alpha, margin = _curled(paper)
    else:
        rgb = np.asarray(paper)
        alpha = np.full((paper.height, paper.width), 255, np.uint8)
        margin = 0
    width, height = PAGE_SIZE
    source = np.array([(margin, margin), (width - 1 + margin, margin),
                       (width - 1 + margin, height - 1 + margin),
                       (margin, height - 1 + margin)], np.float32)
    transform = cv2.getPerspectiveTransform(source, CORNERS)
    warped = cv2.warpPerspective(rgb, transform, SIZE, flags=cv2.INTER_LINEAR)
    mask = cv2.warpPerspective(alpha, transform, SIZE, flags=cv2.INTER_LINEAR)
    coverage = mask.astype(np.float32) / 255
    shadow = cv2.GaussianBlur(coverage, (0, 0), 5)
    background = np.clip(_desk(SIZE) - 9 * shadow[:, :, None] * (1 - coverage[:, :, None]), 0, 255)
    photograph = background * (1 - coverage[:, :, None]) + warped * coverage[:, :, None]
    photograph = cv2.GaussianBlur(np.clip(photograph, 0, 255).astype(np.uint8), (3, 3), .55)
    image = Image.fromarray(photograph, 'RGB')
    mask_image = Image.fromarray(mask, 'L')
    if rotation is not None:
        image = image.transpose(rotation)
        mask_image = mask_image.transpose(rotation)
    return image, np.asarray(mask_image)


def background_metrics(source, true_paper_mask, output):
    """Recognize neutral desk pixels while excluding dark print and colored ink."""
    source_rgb = np.asarray(source).astype(np.int16)
    source_gray = cv2.cvtColor(np.asarray(source), cv2.COLOR_RGB2GRAY)
    neutral = source_rgb.max(axis=2) - source_rgb.min(axis=2) < 6
    desk_values = source_gray[(true_paper_mask < 8) & neutral]
    paper_values = source_gray[(true_paper_mask > 248) & neutral & (source_gray > 125)]
    # The fixture's neutral desk is darker than its sheet. Use measured source
    # ranges rather than hard-coding the application's brightness thresholds.
    desk_top = float(np.percentile(desk_values, 98))
    paper_low = float(np.percentile(paper_values, 2))
    assert paper_low > desk_top + 8, 'The fixture has a distinguishable physical paper edge'
    threshold = (desk_top + paper_low) / 2
    desk_bottom = float(np.percentile(desk_values, 2)) - 12
    rgb = np.asarray(output).astype(np.int16)
    gray = cv2.cvtColor(np.asarray(output), cv2.COLOR_RGB2GRAY)
    desk = ((rgb.max(axis=2) - rgb.min(axis=2) < 6)
            & (gray >= desk_bottom) & (gray < threshold))
    band = max(2, round(min(output.size) * .025))
    border = np.ones(gray.shape, dtype=bool)
    border[band:-band, band:-band] = False
    corners = [desk[:band, :band], desk[:band, -band:],
               desk[-band:, :band], desk[-band:, -band:]]
    return {'border_desk_fraction': float(desk[border].mean()),
            'corner_desk_fractions': [float(corner.mean()) for corner in corners],
            'desk_threshold': threshold, 'border_width': band}


def side_writing_gaps(image):
    """Distances of known mid-side labels from each physical output edge."""
    rgb = np.asarray(image).astype(np.int16)
    ink = (rgb[:, :, 0] > rgb[:, :, 1] + 35) & (rgb[:, :, 2] > rgb[:, :, 1] + 35)
    height, width = ink.shape
    regions = [ink[height // 3:2 * height // 3, :width // 4],
               ink[height // 3:2 * height // 3, 3 * width // 4:],
               ink[:height // 4, width // 3:2 * width // 3],
               ink[3 * height // 4:, width // 3:2 * width // 3]]
    coordinates = [np.where(region) for region in regions]
    assert all(len(y) > 45 for y, x in coordinates), 'All four side labels must remain readable'
    pixels = [int(coordinates[0][1].min()),
              int(width - 1 - (3 * width // 4 + coordinates[1][1].max())),
              int(coordinates[2][0].min()),
              int(height - 1 - (3 * height // 4 + coordinates[3][0].max()))]
    return [pixels[0] / width, pixels[1] / width, pixels[2] / height, pixels[3] / height]


@pytest.mark.parametrize('curved', [False, True], ids=['flat', 'bowed'])
@pytest.mark.parametrize('rotation', [None, Image.Transpose.ROTATE_90], ids=['portrait', 'quarter-turn'])
def test_crop_rectifies_paper_boundary_without_desk_strips(curved, rotation):
    source, mask = source_and_paper_mask(curved=curved, rotation=rotation)
    result, metadata = prepare_image(source, enhance_text=False)
    assert metadata['document_detected'] and metadata['cropped']
    assert metadata['enhanced'] is False
    metrics = background_metrics(source, mask, result)
    assert metrics['border_desk_fraction'] < .03, metrics
    assert max(metrics['corner_desk_fractions']) < .08, metrics
    assert result.width * result.height < source.width * source.height * .75


def test_clean_boundary_crop_preserves_corner_and_bowed_side_writing():
    source, mask = source_and_paper_mask()
    result, metadata = prepare_image(source, enhance_text=False)
    assert metadata['cropped'] is True
    assert min(_corner_ink_survives(result)) > 25
    assert all(after >= before * .75 for before, after in
               zip(_mid_edge_ink(source), _mid_edge_ink(result))), 'Rectification must retain side writing'
    metrics = background_metrics(source, mask, result)
    assert metrics['border_desk_fraction'] < .03, metrics


def test_default_cleanup_retains_edge_writing_and_readability():
    source, _ = source_and_paper_mask()
    result, metadata = prepare_image(source)
    assert metadata == {'document_detected': True, 'cropped': True, 'enhanced': True}
    assert min(_corner_ink_survives(result)) > 25
    assert min(_mid_edge_ink(result)) > 45
    neutral = np.asarray(result).max(axis=2) - np.asarray(result).min(axis=2) < 6
    light = cv2.cvtColor(np.asarray(result), cv2.COLOR_RGB2GRAY)
    assert np.median(light[neutral]) > 215


@pytest.mark.parametrize('enhance_text', [False, True])
def test_rectification_does_not_replace_desk_with_unnecessary_white_margins(enhance_text):
    source, _ = source_and_paper_mask()
    result, metadata = prepare_image(source, enhance_text=enhance_text)
    assert metadata['cropped'] is True
    gaps = side_writing_gaps(result)
    # Labels are drawn within a few millimeters of the real sheet edges. Merely
    # whitening an oversized crop still moves them unnecessarily far inward.
    assert gaps[0] < .03, gaps
    assert gaps[1] < .06, gaps
    assert gaps[2] < .025, gaps
    assert gaps[3] < .022, gaps


def test_no_crop_means_no_rectification_even_when_effect_is_enabled():
    source, _ = source_and_paper_mask()
    result, metadata = prepare_image(source, auto_crop=False)
    assert metadata['cropped'] is False
    assert result.size == source.size
    assert result.getpixel((30, 30)) == source.getpixel((30, 30)), 'Desk outside the page is untouched'


def test_both_switches_off_preserve_source_pixels_and_layout():
    source, _ = source_and_paper_mask()
    result, metadata = prepare_image(source, auto_crop=False, enhance_text=False)
    assert metadata == {'document_detected': False, 'cropped': False, 'enhanced': False}
    assert result.size == source.size and result.tobytes() == source.tobytes()


def test_rectification_does_not_activate_for_a_gray_appliance():
    source = photographed_gray_appliance()
    result, metadata = prepare_image(source)
    assert metadata == {'document_detected': False, 'cropped': False, 'enhanced': False}
    assert result.size == source.size and result.tobytes() == source.tobytes()


@pytest.mark.parametrize('border', [8, 14])
@pytest.mark.parametrize('rotation', [None, Image.Transpose.ROTATE_90])
def test_strong_printed_frame_cannot_replace_paper_edge_and_discard_margin_writing(border, rotation):
    # Its rising dark-to-paper edge is stronger than the poorly lit sheet's
    # real border. Every corner and all four side labels lie outside the frame.
    paper = _shipment_form()
    ImageDraw.Draw(paper).rectangle((45, 45, paper.width - 46, paper.height - 46),
                                    outline=(25, 25, 25), width=border)
    source, _ = source_and_paper_mask(paper=paper, rotation=rotation)
    result, metadata = prepare_image(source, enhance_text=False)
    assert metadata['document_detected'] and metadata['cropped']
    assert metadata['enhanced'] is False
    if rotation is not None:
        source = source.transpose(Image.Transpose.ROTATE_270)
        result = result.transpose(Image.Transpose.ROTATE_270)
    assert min(_corner_ink_survives(result)) > 25
    # Perspective removal changes glyph pixel area and the sampling grid. Check
    # complete strokes and ink density after normalizing each label's own box,
    # rather than treating fewer camera pixels as proof that writing was cut.
    for (before_mass, before_shape), (after_mass, after_shape) in zip(
            _mid_side_ink_shapes(source), _mid_side_ink_shapes(result)):
        assert after_mass >= before_mass * .75, 'Margin ink contrast must remain'
        coverage = _glyph_shape_coverage(before_shape, after_shape)
        assert coverage >= .75, 'The frame must not cut away margin glyph strokes'


def _mid_side_ink_shapes(image):
    rgb = np.asarray(image).astype(np.int16)
    strength = np.clip(np.minimum(rgb[:, :, 0] - rgb[:, :, 1],
                                  rgb[:, :, 2] - rgb[:, :, 1]), 0, 255)
    height, width = strength.shape
    regions = (strength[height // 3:2 * height // 3, :width // 4],
               strength[height // 3:2 * height // 3, 3 * width // 4:],
               strength[:height // 4, width // 3:2 * width // 3],
               strength[3 * height // 4:, width // 3:2 * width // 3])
    shapes = []
    for region in regions:
        y, x = np.where(region > 20)
        assert len(y) > 45, 'All four margin labels must remain'
        glyph = region[y.min():y.max() + 1, x.min():x.max() + 1].astype(np.float32)
        normalized = np.asarray(Image.fromarray(glyph).resize((64, 64), Image.Resampling.BILINEAR))
        shapes.append((float(glyph.mean()), normalized > 20))
    return shapes


def _glyph_shape_coverage(before, after):
    # One pixel in the 64px normalized box allows subpixel camera/interpolation
    # alignment; it cannot restore a missing letter or a clipped long stroke.
    supported = cv2.dilate(after.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    return float((before & supported).sum()) / int(before.sum())


def test_framed_glyph_shape_check_rejects_a_missing_letter():
    source, _ = source_and_paper_mask()
    pixels = np.array(source)
    top_middle = pixels[:source.height // 4, source.width // 3:2 * source.width // 3]
    rgb = top_middle.astype(np.int16)
    ink = (rgb[:, :, 0] > rgb[:, :, 1] + 20) & (rgb[:, :, 2] > rgb[:, :, 1] + 20)
    y, x = np.where(ink)
    cutoff = (int(x.min()) + int(x.max())) // 2
    removed = ink & (np.arange(top_middle.shape[1])[None, :] <= cutoff)
    top_middle[removed] = (150, 150, 150)
    before_shape = _mid_side_ink_shapes(source)[2][1]
    after_shape = _mid_side_ink_shapes(Image.fromarray(pixels))[2][1]
    coverage = _glyph_shape_coverage(before_shape, after_shape)
    assert coverage < .75, 'Normalization must not hide a letter lost to an inward crop'
