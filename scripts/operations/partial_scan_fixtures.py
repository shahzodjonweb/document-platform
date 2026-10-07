"""Anonymous procedural partial-page fixtures; no customer image is loaded.

All geometry/ink masks are generated before the simulated camera. Validation
knows visible source pixels, not detector thresholds, selected edges or poses.
This module supplies only synthetic audit/test fixtures and validation oracles.
"""
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


FONT = Path(__file__).resolve().parents[2] / 'processors/assets/fonts/NotoSans-Regular.ttf'
PAGE_SIZE = (700, 1080)
PHOTO_SIZE = (960, 1280)


@dataclass
class PartialFixture:
    image: Image.Image
    main_paper: np.ndarray
    all_paper: np.ndarray
    blank_paper_rgb: np.ndarray
    marks: dict[str, np.ndarray]
    family: str


def _font(size):
    return ImageFont.truetype(str(FONT), size)


def _paper(*, shadow=True):
    width, height = PAGE_SIZE
    yy, xx = np.mgrid[:height, :width].astype(np.float32)
    x, y = xx / (width - 1), yy / (height - 1)
    light = .96 + .035 * x + .025 * y
    if shadow:
        light -= .28 * np.exp(-((x - .34) ** 2 / .045 + (y - .49) ** 2 / .15))
        light -= .13 * np.exp(-((x - .16) ** 2 / .06 + (y - .24) ** 2 / .10))
    background = np.array((218, 224, 229), np.float32) * light[:, :, None]
    flat = Image.fromarray(np.clip(background, 0, 255).astype(np.uint8))
    ink = Image.new('RGB', PAGE_SIZE, (0, 0, 0))
    canvas = ImageDraw.Draw(ink)
    marks = {}

    def text(label, position, value, size=24, color=(58, 61, 64)):
        mask = Image.new('L', PAGE_SIZE, 0)
        ImageDraw.Draw(mask).text(position, value, font=_font(size), fill=255)
        canvas.text(position, value, font=_font(size), fill=color)
        marks[label] = np.asarray(mask)

    text('title', (130, 54), 'GENERIC INSPECTION FORM', 27)
    text('reference', (28, 117), 'Reference: SAMPLE A27', 25)
    text('blue_note', (240, 153), 'NOTE 2741', 28, (13, 44, 142))
    for index, top in enumerate((208, 292, 376, 460, 544, 628, 712, 796)):
        text('field_' + str(index), (30, top), 'Sample field %02d: retain this visible entry' % index, 24)
    text('footer', (31, 891), 'Generic footer: preserve all visible writing', 23)
    text('left_margin', (3, 430), 'L1', 23, (13, 94, 103))
    text('right_margin', (width - 49, 590), 'R2', 23, (127, 17, 115))
    text('top_margin', (width // 2 - 17, 3), 'T3', 22, (128, 14, 18))
    text('bottom_margin', (width // 2 - 26, height - 34), 'B4', 22, (14, 101, 25))
    lines = Image.new('L', PAGE_SIZE, 0)
    grid = ImageDraw.Draw(lines)
    grid.rectangle((24, 196, width - 25, 858), outline=255, width=2)
    for top in (278, 362, 446, 530, 614, 698, 782):
        grid.line((24, top, width - 25, top), fill=255, width=2)
    for left in (172, 513):
        grid.line((left, 196, left, 858), fill=255, width=2)
    canvas.bitmap((0, 0), lines, fill=(67, 70, 74))
    marks['table_lines'] = np.asarray(lines)
    signature = Image.new('L', PAGE_SIZE, 0)
    ImageDraw.Draw(signature).line(((295, 883), (330, 842), (340, 890), (371, 851),
                                    (405, 878), (442, 849), (468, 891), (537, 867)), fill=255, width=4)
    canvas.bitmap((0, 0), signature, fill=(13, 44, 142))
    marks['signature'] = np.asarray(signature)
    # An anonymous graphic stripe code; never derived from a real identifier.
    code = Image.new('L', PAGE_SIZE, 0)
    bars = ImageDraw.Draw(code)
    cursor = 408
    for width_value in (2, 4, 2, 3, 1, 3, 4, 1, 2, 4, 2, 1, 3, 2, 4, 1, 3, 2):
        bars.rectangle((cursor, 90, cursor + width_value - 1, 127), fill=255)
        cursor += width_value + 3
    canvas.bitmap((0, 0), code, fill=(54, 57, 62))
    marks['stripe_code'] = np.asarray(code)
    union = np.maximum.reduce(list(marks.values())).astype(np.float32) / 255
    painted = np.asarray(ink).astype(np.float32) * light[:, :, None]
    pixels = background * (1 - union[:, :, None]) + painted * union[:, :, None]
    return np.clip(pixels, 0, 255).astype(np.uint8), np.clip(background, 0, 255).astype(np.uint8), marks


def partial_document_fixture(*, clipped='left_right_bottom', bowed=True, shadow=True,
                             exterior_note=False, secondary_note=False, rotation=None, scale=1.,
                             exterior_note_kind='bright'):
    """A written matte page partly outside the camera, with exact visible masks."""
    camera_corners = {
        'left_right_bottom': ((-45, 181), (1008, 191), (1035, 1430), (-68, 1441)),
        'left': ((-75, 72), (809, 112), (830, 1190), (-56, 1220)),
        'top': ((104, -145), (885, -104), (932, 1118), (54, 1158)),
        'right_bottom': ((66, 154), (1060, 144), (1090, 1414), (51, 1391)),
        'top_left_right': ((-65, -122), (1020, -142), (991, 1214), (-45, 1240)),
    }
    rgb, blank, marks = _paper(shadow=shadow)
    width, height = PAGE_SIZE
    margin = 46 if bowed else 0
    if bowed:
        yy, xx = np.mgrid[:height + 2 * margin, :width + 2 * margin].astype(np.float32)
        map_x = xx - margin - 12 * np.sin(np.pi * np.clip((yy - margin) / (height - 1), 0, 1))
        map_y = yy - margin - 34 * np.sin(np.pi * np.clip((xx - margin) / (width - 1), 0, 1))

        def bend(array):
            return cv2.remap(array, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        rgb, blank = bend(rgb), bend(blank)
        alpha = bend(np.full((height, width), 255, np.uint8))
        marks = {name: bend(mask) for name, mask in marks.items()}
    else:
        alpha = np.full((height, width), 255, np.uint8)
    source = np.array(((margin, margin), (width - 1 + margin, margin),
                       (width - 1 + margin, height - 1 + margin), (margin, height - 1 + margin)), np.float32)
    transform = cv2.getPerspectiveTransform(source, np.array(camera_corners[clipped], np.float32))
    project = lambda array: cv2.warpPerspective(array, transform, PHOTO_SIZE, flags=cv2.INTER_LINEAR)
    warped, blank, main_alpha = project(rgb), project(blank), project(alpha)
    main = main_alpha.astype(np.float32) / 255
    projected_marks = {name: project(mask) for name, mask in marks.items()}
    yy, xx = np.mgrid[:PHOTO_SIZE[1], :PHOTO_SIZE[0]].astype(np.float32)
    tone = 29 + 6 * np.sin(xx / 9) * np.sin(yy / 13) + 8 * xx / PHOTO_SIZE[0]
    background = np.stack((tone, tone + 5, tone + 10), axis=2)
    background += np.random.default_rng(8127).normal(0, .65, background.shape)
    background = np.clip(background, 0, 255).astype(np.uint8)
    all_alpha = main_alpha.copy()
    visible_secondary = None
    if secondary_note:
        # The second sheet is itself clipped by the right camera edge. Its
        # generic note is visible above the larger foreground sheet.
        secondary = Image.new('RGB', PHOTO_SIZE, (0, 0, 0))
        secondary_alpha = Image.new('L', PHOTO_SIZE, 0)
        polygon = ((777, 36), (1035, 68), (1050, 411), (750, 360))
        ImageDraw.Draw(secondary).polygon(polygon, fill=(207, 215, 221))
        ImageDraw.Draw(secondary_alpha).polygon(polygon, fill=255)
        note = Image.new('L', PHOTO_SIZE, 0)
        ImageDraw.Draw(note).text((790, 80), 'EXTRA NOTE S1', font=_font(23), fill=255)
        ImageDraw.Draw(secondary).text((790, 80), 'EXTRA NOTE S1', font=_font(23), fill=(20, 45, 140))
        secondary_coverage = np.asarray(secondary_alpha).astype(np.float32) / 255
        background = np.clip(background * (1 - secondary_coverage[:, :, None])
                             + np.asarray(secondary) * secondary_coverage[:, :, None], 0, 255).astype(np.uint8)
        visible_secondary = np.round(secondary_coverage * (1 - main) * 255).astype(np.uint8)
        projected_marks['secondary_note'] = np.round(np.asarray(note) * (1 - main)).astype(np.uint8)
        all_alpha = np.maximum(main_alpha, visible_secondary)
    if exterior_note:
        note = Image.new('L', PHOTO_SIZE, 0)
        # This annotation belongs to the scene. Auto-crop selects the document
        # and removes it; enhancement-only keeps every scene pixel unchanged.
        if exterior_note_kind not in ('bright', 'tiny_faint', 'tiny_blue', 'single_faint', 'short_blue'):
            raise ValueError('Unknown anonymous exterior reference kind')
        size = 25 if exterior_note_kind == 'bright' else 9
        value = {'bright': 'KEEP OUTSIDE NOTE', 'tiny_faint': 'ID27',
                 'tiny_blue': 'ID27', 'single_faint': 'X', 'short_blue': 'ID'}[exterior_note_kind]
        ImageDraw.Draw(note).text((45, 16), value, font=_font(size), fill=255)
        note_array = np.asarray(note).astype(np.float32) / 255
        if exterior_note_kind == 'bright':
            note_color = np.array((231, 196, 142))
        else:
            increase = (0, 5, 22) if exterior_note_kind in ('tiny_blue', 'short_blue') else 8
            note_color = np.minimum(background.astype(np.int16) + increase, 255)
        background = np.clip(background * (1 - note_array[:, :, None])
                             + note_color * note_array[:, :, None], 0, 255).astype(np.uint8)
        projected_marks['exterior_note'] = np.round(np.asarray(note) * (1 - main)).astype(np.uint8)
    photo = background * (1 - main[:, :, None]) + warped * main[:, :, None]
    image = Image.fromarray(cv2.GaussianBlur(np.clip(photo, 0, 255).astype(np.uint8), (3, 3), .5))
    # Camera blur affects alpha/mark visibility too. Exact exterior means zero
    # photographed paper coverage, including this independent blending halo.
    main_alpha = cv2.GaussianBlur(main_alpha, (3, 3), .5)
    all_alpha = cv2.GaussianBlur(all_alpha, (3, 3), .5)
    projected_marks = {name: cv2.GaussianBlur(mask, (3, 3), .5) for name, mask in projected_marks.items()}
    blank = cv2.GaussianBlur(blank, (3, 3), .5)
    arrays = {'main': main_alpha, 'all': all_alpha, 'blank': blank, **projected_marks}
    if scale != 1:
        size = (round(image.width * scale), round(image.height * scale))
        image = image.resize(size, Image.Resampling.LANCZOS)
        arrays = {name: np.asarray(Image.fromarray(array).resize(size, Image.Resampling.BOX)) for name, array in arrays.items()}
    if rotation is not None:
        image = image.transpose(rotation)
        arrays = {name: np.asarray(Image.fromarray(array).transpose(rotation)) for name, array in arrays.items()}
    main_alpha, all_alpha, blank = (arrays.pop(name) for name in ('main', 'all', 'blank'))
    family = clipped + ('_exterior_note' if exterior_note else '') + ('_secondary_note' if secondary_note else '')
    return PartialFixture(image, main_alpha, all_alpha, blank, arrays, family)


def source_roi(original, cropped, *, white_canvas=False):
    """Verify original-coordinate translation; optionally permit pure-white matte.

    White replacement alone cannot prove paper/note preservation. Callers that
    permit a canvas must independently assert every known visible paper/mark
    pixel, as the camera-ground-truth validators below do.
    """
    source, target = np.asarray(original), np.asarray(cropped)
    height, width = target.shape[:2]
    assert height <= source.shape[0] and width <= source.shape[1], 'No new canvas or invented hidden content'
    retained = np.any(target != 255, axis=2)
    assert retained.any(), 'An empty white canvas cannot prove an exact source ROI'
    mask = retained.astype(np.uint8) * 255 if white_canvas else None
    scores = cv2.matchTemplate(source, target, cv2.TM_SQDIFF, mask=mask)
    candidates = np.argsort(scores.ravel())[:min(8, scores.size)]
    for index in candidates:
        y, x = np.unravel_index(index, scores.shape)
        expected = source[y:y + height, x:x + width]
        if np.array_equal(expected[retained] if white_canvas else expected,
                          target[retained] if white_canvas else target):
            return int(x), int(y), int(x + width), int(y + height)
    raise AssertionError('Crop-only must be an exact source ROI translation, without a homography')


def _assert_document_pixels_exact(fixture, output, roi):
    x0, y0, x1, y1 = roi
    before, after = np.asarray(fixture.image)[y0:y1, x0:x1], np.asarray(output)
    assert after.shape == before.shape, 'Partial crop preserves original camera geometry'
    retained = fixture.all_paper[y0:y1, x0:x1] > 0
    assert np.array_equal(after[retained], before[retained]), 'Crop-only must preserve every visible paper and reference RGB pixel'


def _assert_white_exterior(fixture, output, roi):
    """Require useful scene removal, measured from independent camera alpha."""
    x0, y0, x1, y1 = roi
    paper = fixture.all_paper[y0:y1, x0:x1] > 0
    after = np.asarray(output)
    white = np.all(after >= 250, axis=2)
    guard = max(8, round(min(fixture.image.size) * .01))
    protected = cv2.dilate(paper.astype(np.uint8),
                          np.ones((guard * 2 + 1, guard * 2 + 1), np.uint8)) > 0
    clear = ~protected
    assert int(clear.sum()) > 100, 'Camera fixture needs a known exterior region'
    assert float(white[clear].mean()) >= .995, 'Auto-crop must remove known exterior to a white canvas'
    exterior = ~paper
    boundary = paper & (cv2.erode(paper.astype(np.uint8), np.ones((3, 3), np.uint8)) == 0)
    # Equivalent residual halo thickness counts even irregular wedges, rather
    # than allowing a large black corner to hide behind a global white average.
    halo = float((exterior & ~white).sum()) / max(1, int(boundary.sum()))
    assert halo <= max(6., min(fixture.image.size) * .008), 'Auto-crop must leave only a narrow conservative edge halo'
    off_paper_ink = np.zeros(paper.shape, bool)
    for mask in fixture.marks.values():
        off_paper_ink |= mask[y0:y1, x0:x1] > 0
    off_paper_ink &= clear
    assert np.all(white[off_paper_ink]), 'Auto-crop removes unrelated off-paper references with the scene'


def _assert_all_marks_retained(fixture, roi):
    x0, y0, x1, y1 = roi
    retained = np.zeros(fixture.main_paper.shape, bool)
    retained[y0:y1, x0:x1] = True
    assert not np.any((fixture.all_paper > 0) & ~retained), 'Only bands without proven paper may be removed'
    for name, mask in fixture.marks.items():
        on_paper = (mask > 0) & (fixture.all_paper > 0)
        assert not np.any(on_paper & ~retained), 'All visible on-paper marks must survive: ' + name



def _assert_proven_empty_band_trimmed(fixture, roi):
    # Only the unambiguous primary scene has a large known blank exterior band.
    # Off-paper notes are scene content; secondary sheets remain documents.
    if fixture.family not in ('left_right_bottom', 'left_right_bottom_exterior_note'):
        return
    protected = fixture.all_paper > 0
    for mask in fixture.marks.values():
        protected |= (mask > 0) & (fixture.all_paper > 0)
    yy, xx = np.where(protected)
    original_area = fixture.image.width * fixture.image.height
    protected_bounds_area = (int(xx.max()) - int(xx.min()) + 1) * (int(yy.max()) - int(yy.min()) + 1)
    empty_band_area = original_area - protected_bounds_area
    assert empty_band_area > 0, 'Primary camera fixture must contain proven empty exterior bands'
    x0, y0, x1, y1 = roi
    removed_area = original_area - (x1 - x0) * (y1 - y0)
    # Permit a conservative boundary allowance, while distinguishing an actual
    # useful crop from ignored auto_crop or a token one-pixel size reduction.
    assert removed_area >= empty_band_area * .25, 'Auto-crop must remove a meaningful proven empty exterior band'


def _assert_effect_quality(fixture, output, roi, *, white_canvas=False):
    x0, y0, x1, y1 = roi
    original = np.asarray(fixture.image)[y0:y1, x0:x1]
    after = np.asarray(output)
    assert after.shape == original.shape, 'Partial cleanup must not invent or stretch hidden page geometry'
    outside = fixture.all_paper[y0:y1, x0:x1] == 0
    if white_canvas:
        _assert_white_exterior(fixture, output, roi)
    else:
        assert np.array_equal(after[outside], original[outside]), 'Exterior scene and exterior notes remain exact'
    old_gray = cv2.cvtColor(original, cv2.COLOR_RGB2GRAY)
    new_gray = cv2.cvtColor(after, cv2.COLOR_RGB2GRAY)
    ink = np.maximum.reduce(list(fixture.marks.values()))[y0:y1, x0:x1]
    ink_neighborhood = cv2.dilate((ink > 16).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    clean = (fixture.main_paper[y0:y1, x0:x1] >= 248) & ~ink_neighborhood
    assert int(clean.sum()) > 500, 'There must be visible blank main-paper samples'
    old_paper, new_paper = float(np.median(old_gray[clean])), float(np.median(new_gray[clean]))
    assert new_paper >= old_paper + 15, 'Default must visibly brighten photographed paper'
    assert float(np.percentile(new_gray[clean], 25)) > float(np.percentile(old_gray[clean], 25)) + 15, 'Shaded paper must improve too'
    for name, mask in fixture.marks.items():
        visible = mask[y0:y1, x0:x1] >= 200
        # Outside notes stay exact; main and secondary paper may be brightened,
        # but every visible stroke and its ink color still need to survive.
        visible &= fixture.all_paper[y0:y1, x0:x1] >= 240
        if int(visible.sum()) >= 6:
            old_contrast = old_paper - float(np.median(old_gray[visible]))
            new_contrast = new_paper - float(np.median(new_gray[visible]))
            assert new_contrast >= max(35, old_contrast * .9), 'Retain mark contrast: ' + name
            assert float(np.mean(new_gray[visible] < new_paper - 30)) >= .90, 'Do not erase visible ink: ' + name
            before_colors, after_colors = original[visible].astype(np.int16), after[visible].astype(np.int16)
            color_strength = before_colors.max(axis=1) - before_colors.min(axis=1)
            colored = color_strength > 45
            if int(colored.sum()) >= 6:
                new_strength = after_colors[colored].max(axis=1) - after_colors[colored].min(axis=1)
                assert float(np.median(new_strength)) >= float(np.median(color_strength[colored])) * .7, 'Keep colored ink: ' + name
                assert float(np.mean(after_colors[colored].argmax(axis=1) == before_colors[colored].argmax(axis=1))) >= .90, 'Keep ink hue: ' + name



def validate_partial_output(fixture, image, *, enhanced, roi=None, auto_crop=True):
    """Check one worker output against anonymous camera ground truth.

    Enhanced output needs the independently proven crop-only source rectangle,
    since changed paper pixels cannot establish an exact template translation.
    """
    if not enhanced:
        actual_roi = source_roi(fixture.image, image, white_canvas=auto_crop)
        if roi is not None:
            assert tuple(roi) == actual_roi, 'Crop-only must use the proven source ROI'
        roi = actual_roi
    else:
        assert roi is not None, 'Enhanced output requires a proven crop-only source ROI'
        roi = tuple(roi)
    assert len(roi) == 4 and all(isinstance(value, (int, np.integer)) for value in roi), 'A source ROI has four integer coordinates'
    x0, y0, x1, y1 = roi
    assert 0 <= x0 < x1 <= fixture.image.width and 0 <= y0 < y1 <= fixture.image.height, 'Source ROI cannot invent hidden content'
    _assert_all_marks_retained(fixture, roi)
    if not enhanced:
        if auto_crop:
            _assert_proven_empty_band_trimmed(fixture, roi)
        _assert_document_pixels_exact(fixture, image, roi)
        if auto_crop:
            _assert_white_exterior(fixture, image, roi)
    if enhanced:
        _assert_effect_quality(fixture, image, roi, white_canvas=auto_crop)
    return {'roi': tuple(int(value) for value in roi),
            'crop_verified': not enhanced, 'effect_verified': bool(enhanced),
            'source_geometry_preserved': True, 'visible_marks_preserved': True,
            'exterior_pixels_preserved': not auto_crop,
            'exterior_background_removed': bool(auto_crop),
            'white_canvas_verified': bool(auto_crop)}


def validate_partial_modes(fixture, results):
    """Independent preservation contract for all four switch combinations."""
    original = fixture.image
    off, off_flags = results[(False, False)]
    assert off.size == original.size and off.tobytes() == original.tobytes(), 'Both off preserve every source pixel'
    assert not off_flags['cropped'] and not off_flags['enhanced']
    crop, crop_flags = results[(True, False)]
    roi = source_roi(original, crop, white_canvas=True)
    _assert_all_marks_retained(fixture, roi)
    _assert_proven_empty_band_trimmed(fixture, roi)
    _assert_document_pixels_exact(fixture, crop, roi)
    _assert_white_exterior(fixture, crop, roi)
    assert not crop_flags['enhanced'], 'Crop-only has no readability effect'
    effect, effect_flags = results[(False, True)]
    assert effect.size == original.size and not effect_flags['cropped'], 'Effect-only preserves source geometry'
    _assert_effect_quality(fixture, effect, (0, 0, original.width, original.height))
    default, default_flags = results[(True, True)]
    assert default.size == crop.size, 'Default and crop-only use the same proven source ROI'
    _assert_effect_quality(fixture, default, roi, white_canvas=True)
    assert default_flags['enhanced'] and effect_flags['enhanced'], 'Configured default cleanup must be applied'
    return {'roi': roi, 'visible_marks_preserved': True, 'exterior_pixels_preserved': False,
            'exterior_background_removed': True, 'white_canvas_verified': True,
            'masked_readability_improved': True, 'source_geometry_preserved': True}


def reference_modes(fixture):
    """Camera-ground-truth oracle used only to calibrate validation guards."""
    protected = fixture.all_paper > 0
    for mask in fixture.marks.values():
        protected |= (mask > 0) & (fixture.all_paper > 0)
    y, x = np.where(protected)
    roi = (int(x.min()), int(y.min()), int(x.max()) + 1, int(y.max()) + 1)
    source = np.asarray(fixture.image).astype(np.float32)
    blank = np.maximum(fixture.blank_paper_rgb.astype(np.float32), 40)
    adjusted = np.clip(source / blank * 245, 0, 255).astype(np.uint8)
    adjusted = np.where((fixture.main_paper > 0)[:, :, None], adjusted, source.astype(np.uint8))
    effect = Image.fromarray(adjusted)
    retained = fixture.all_paper > 0
    canvas = np.full(source.shape, 255, np.uint8)
    canvas[retained] = np.asarray(fixture.image)[retained]
    adjusted_canvas = np.full(source.shape, 255, np.uint8)
    adjusted_canvas[retained] = adjusted[retained]
    crop = Image.fromarray(canvas).crop(roi)
    cropped = crop.size != fixture.image.size
    return {(False, False): (fixture.image, {'cropped': False, 'enhanced': False}),
            (True, False): (crop, {'cropped': cropped, 'enhanced': False}),
            (False, True): (effect, {'cropped': False, 'enhanced': True}),
            (True, True): (Image.fromarray(adjusted_canvas).crop(roi), {'cropped': cropped, 'enhanced': True})}


VARIANTS = {
    'three_edges': {},
    'left_edge_flat': {'clipped': 'left', 'bowed': False},
    'top_edge': {'clipped': 'top'},
    'right_bottom': {'clipped': 'right_bottom'},
    'top_left_right': {'clipped': 'top_left_right'},
    'quarter_turn': {'rotation': Image.Transpose.ROTATE_90},
    'half_size': {'scale': .5},
    'exterior_note': {'exterior_note': True},
    'secondary_note': {'secondary_note': True},
}
