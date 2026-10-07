"""Physical quality checks for partial-page illumination and contrast cleanup.

Every image/ink mask is procedural and anonymous. No customer image or text is
loaded, and expected writing is established before any enhancement operation.
"""
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from processors.partial_scan_cleanup import cleanup_paper, enhance_paper


FONT = Path(__file__).resolve().parents[1] / 'processors/assets/fonts/NotoSans-Regular.ttf'


def _writing(size, text, position, *, font_size=34):
    mask = Image.new('L', size, 0)
    ImageDraw.Draw(mask).text(position, text,
        font=ImageFont.truetype(str(FONT), font_size), fill=255)
    return np.asarray(mask)


def _paint(pixels, mask, color):
    alpha = mask.astype(np.float32) / 255
    return np.rint(pixels * (1 - alpha[:, :, None])
                   + np.array(color) * alpha[:, :, None]).astype(np.uint8)


def _contrast(pixels, blank, ink):
    gray = cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY)
    return float(np.median(gray[blank])) - float(np.median(gray[ink]))


def test_faint_neutral_print_becomes_materially_clearer_without_losing_strokes():
    size = (900, 650)
    pixels = np.full((size[1], size[0], 3), (199, 205, 211), np.uint8)
    mask = _writing(size, 'FAINT SAMPLE 2741', (100, 200), font_size=42)
    pixels = _paint(pixels, mask, (179, 185, 191))
    output = np.asarray(enhance_paper(Image.fromarray(pixels),
                                     np.full(mask.shape, 255, np.uint8), cv2, np,
                                     feather=False))
    ink = mask >= 220
    blank = cv2.dilate((mask > 0).astype(np.uint8), np.ones((9, 9), np.uint8)) == 0
    assert int(ink.sum()) > 500
    before, after = _contrast(pixels, blank, ink), _contrast(output, blank, ink)
    assert after >= max(35, before * 2), 'Visible faint print must gain substantial contrast'
    gray = cv2.cvtColor(output, cv2.COLOR_RGB2GRAY)
    paper = float(np.median(gray[blank]))
    assert paper >= 245
    assert float(np.mean(gray[ink] < paper - 30)) >= .95, 'Do not erase opaque source glyph strokes'


def test_broad_blank_fold_is_normalized_without_extra_stroke_darkening():
    width, height = 1200, 720
    yy, xx = np.mgrid[:height, :width].astype(np.float32)
    light = 1 - .28 * np.exp(-((xx - 640) / 145) ** 2) - .08 * np.exp(-((yy - 320) / 170) ** 2)
    pixels = np.rint(np.array((200, 207, 215)) * light[:, :, None]).astype(np.uint8)
    image = Image.fromarray(pixels)
    region = np.full((height, width), 255, np.uint8)

    class IlluminationOnly:
        def __getattr__(self, name):
            return getattr(cv2, name)

        @staticmethod
        def morphologyEx(array, operation, kernel, *args, **kwargs):
            # Independent ablation removes only fine-stroke evidence. The
            # smooth blank fold should not be treated as printed writing.
            if operation == cv2.MORPH_CLOSE and kernel.shape == (31, 31):
                return array.copy()
            return cv2.morphologyEx(array, operation, kernel, *args, **kwargs)

    plain = np.asarray(enhance_paper(image, region, IlluminationOnly(), np, feather=False))
    cleaned = np.asarray(enhance_paper(image, region, cv2, np, feather=False))
    assert np.array_equal(cleaned, plain), 'Broad blank illumination changes need no extra text darkness'
    before = cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY)
    after = cv2.cvtColor(cleaned, cv2.COLOR_RGB2GRAY)
    assert float(np.percentile(after, 5)) >= 235
    assert float(np.percentile(after, 95) - np.percentile(after, 5)) < float(np.percentile(before, 95) - np.percentile(before, 5)) * .3


def test_colored_print_preserves_hue_strength_and_visible_contrast():
    size = (1000, 750)
    pixels = np.full((size[1], size[0], 3), (195, 205, 218), np.uint8)
    marks = []
    for index, color in enumerate(((14, 43, 142), (146, 28, 22), (18, 133, 66), (14, 118, 171))):
        mask = _writing(size, 'COLOR NOTE %02d' % index, (110, 75 + index * 145), font_size=38)
        pixels = _paint(pixels, mask, color)
        marks.append(mask)
    output = np.asarray(enhance_paper(Image.fromarray(pixels),
        np.full((size[1], size[0]), 255, np.uint8), cv2, np, feather=False))
    blank = np.maximum.reduce(marks) == 0
    for mask in marks:
        ink = mask >= 220
        old, new = pixels[ink].astype(np.int16), output[ink].astype(np.int16)
        assert float(np.mean(old.argmax(axis=1) == new.argmax(axis=1))) >= .98, 'Colored writing must retain its hue'
        assert float(np.median(np.ptp(new, axis=1))) >= float(np.median(np.ptp(old, axis=1))) * .8
        assert _contrast(output, blank, ink) >= max(40, _contrast(pixels, blank, ink) * .9)


def test_identical_native_marks_are_consistent_across_horizontal_and_vertical_tile_seams():
    width = height = 2140
    pixels = np.full((height, width, 3), 210, np.uint8)
    patch = Image.new('RGB', (200, 200), (210, 210, 210))
    draw = ImageDraw.Draw(patch)
    draw.text((5, 5), 'EDGE2741', font=ImageFont.truetype(str(FONT), 32), fill=(186, 186, 186))
    # Broader marks force the complete closing footprint to cross940/1880.
    draw.rectangle((34, 90, 87, 137), fill=(186, 186, 186))
    draw.line(((15, 159), (35, 141), (45, 179), (77, 151), (108, 170)), fill=(186, 186, 186), width=7)
    positions = ((140, 140), (900, 140), (140, 900), (900, 900), (1840, 1840))
    for left, top in positions:
        pixels[top:top + 200, left:left + 200] = np.asarray(patch)
    output = np.asarray(enhance_paper(Image.fromarray(pixels),
        np.full((height, width), 255, np.uint8), cv2, np, feather=False))
    # A full-frame morphology oracle isolates native tile seams from legitimate
    # thumbnail resampling phase differences between repeated source features.
    gray = cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY)
    reference_close = cv2.morphologyEx(gray, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31)))

    class FullNativeClosing:
        def __init__(self):
            self.calls = 0

        def __getattr__(self, name):
            return getattr(cv2, name)

        def morphologyEx(self, array, operation, kernel, *args, **kwargs):
            if operation == cv2.MORPH_CLOSE and kernel.shape == (31, 31):
                # Three cores per axis. The oracle never derives expected ink
                # from a tiled closing; it slices one globally closed source.
                row, column = divmod(self.calls, 3)
                self.calls += 1
                left, top = max(0, column * 940 - 30), max(0, row * 940 - 30)
                height, width = array.shape
                assert np.array_equal(array, gray[top:top + height, left:left + width])
                return reference_close[top:top + height, left:left + width]
            return cv2.morphologyEx(array, operation, kernel, *args, **kwargs)

    oracle = FullNativeClosing()
    reference = np.asarray(enhance_paper(Image.fromarray(pixels),
        np.full((height, width), 255, np.uint8), oracle, np, feather=False))
    assert oracle.calls == 9
    assert np.array_equal(output, reference), 'Native tile seams must match a full-frame fine-stroke reference exactly'


def test_every_opencv_native_work_array_is_bounded_to_one_million_pixels():
    calls = []

    class BoundedCv:
        def __getattr__(self, name):
            function = getattr(cv2, name)
            if not callable(function):
                return function

            def checked(*args, **kwargs):
                for value in args:
                    if isinstance(value, np.ndarray) and value.ndim >= 2:
                        assert value.shape[0] * value.shape[1] <= 1_000_000, name + ' input exceeds native tile bound'
                result = function(*args, **kwargs)
                for value in result if isinstance(result, tuple) else (result,):
                    if isinstance(value, np.ndarray) and value.ndim >= 2:
                        assert value.shape[0] * value.shape[1] <= 1_000_000, name + ' output exceeds native tile bound'
                if name == 'morphologyEx' and args[2].shape == (31, 31):
                    assert args[0].dtype == np.uint8
                    calls.append(args[0].shape)
                return result
            return checked

    # Input and returned image necessarily have their native canvas size;
    # every OpenCV intermediate must operate on thumbnails or bounded tiles.
    size = (2440, 2230)
    image = Image.new('RGB', size, (197, 205, 213))
    mask = np.full((512, 512), 255, np.uint8)
    output = enhance_paper(image, mask, BoundedCv(), np, feather=False)
    assert output.size == image.size
    assert len(calls) >= 4 and max(h * w for h, w in calls) <= 1_000_000


def test_enhancement_only_keeps_all_independent_exterior_scene_pixels_exact():
    size = (1280, 900)
    pixels = np.full((size[1], size[0], 3), (29, 35, 42), np.uint8)
    paper = np.zeros((size[1], size[0]), bool)
    paper[150:850, 200:1080] = True
    pixels[paper] = (187, 199, 211)
    # A neutral desk object touching the sheet remains exterior scene data.
    pixels[180:270, 30:200] = (145, 147, 149)
    mask = _writing(size, 'SAMPLE VISIBLE NOTE', (340, 340), font_size=40)
    pixels = _paint(pixels, mask, (22, 48, 139))
    conservative_region = np.zeros(paper.shape, np.uint8)
    conservative_region[165:835, 215:1065] = 255
    output = np.asarray(enhance_paper(Image.fromarray(pixels),
                                     conservative_region, cv2, np, feather=True))
    assert np.array_equal(output[~paper], pixels[~paper]), 'Enhancement alone cannot whiten or change any known exterior pixel'
    inside = conservative_region > 0
    assert np.any(output[inside] != pixels[inside]), 'The accepted paper must receive the configured effect'


@pytest.mark.parametrize('font_size,contrast', ((9, 8), (9, 20), (24, 8), (42, 20)))
def test_rectified_cleanup_retains_native_faint_print(font_size, contrast):
    size = (900, 650)
    pixels = np.full((size[1], size[0], 3), (199, 205, 211), np.uint8)
    mask = _writing(size, 'FAINT SAMPLE 2741 X 19', (100, 200), font_size=font_size)
    pixels = _paint(pixels, mask, tuple(v - contrast for v in (199, 205, 211)))
    output = np.asarray(cleanup_paper(Image.fromarray(pixels), cv=cv2, np=np))
    ink = mask >= 200
    blank = cv2.dilate((mask > 0).astype(np.uint8), np.ones((9, 9), np.uint8)) == 0
    assert ink.sum() >= 20
    before, after = _contrast(pixels, blank, ink), _contrast(output, blank, ink)
    assert after >= max(8, before), 'Cleanup cannot erase native faint print to whiten the paper'
    gray = cv2.cvtColor(output, cv2.COLOR_RGB2GRAY)
    assert float(np.mean(gray[ink] <= 251)) >= .95, 'Visible fine strokes must remain visible'
    assert float(np.mean(gray[blank] >= 250)) >= .99


def test_rectified_cleanup_whitens_blank_creasing_and_camera_grain():
    width, height = 1100, 740
    yy, xx = np.mgrid[:height, :width].astype(np.float32)
    light = (1 - .25 * np.exp(-((xx - 450) / 100) ** 2)
             - .08 * np.exp(-((yy - 360) / 150) ** 2))
    rng = np.random.default_rng(94)
    grain = rng.normal(0, 1.2, (height, width))
    texture = cv2.GaussianBlur(rng.normal(0, 1, (height, width)).astype(np.float32),
                              (11, 11), 2) * 10
    pixels = np.rint(np.array((190, 200, 211)) * light[:, :, None]
                     + (grain + texture)[:, :, None]).clip(0, 255).astype(np.uint8)
    output = np.asarray(cleanup_paper(Image.fromarray(pixels), cv=cv2, np=np))
    gray = cv2.cvtColor(output, cv2.COLOR_RGB2GRAY)
    assert float(np.mean(gray >= 248)) >= .99, 'Blank crease texture must look like clean white paper'
    assert float(np.std(gray)) <= 2, 'Do not amplify camera grain into false print'


def test_rectified_cleanup_keeps_faint_print_and_pen_crossing_a_noisy_fold():
    width, height = 1100, 740
    yy, xx = np.mgrid[:height, :width].astype(np.float32)
    light = 1 - .22 * np.exp(-((xx - 480) / 90) ** 2)
    rng = np.random.default_rng(326)
    pixels = np.rint(np.array((193, 202, 212)) * light[:, :, None]
        + rng.normal(0, .8, (height, width, 1))).clip(0, 255).astype(np.uint8)
    mask = _writing((width, height), 'FAINT PRINT ACROSS THE FOLD 2741',
                    (200, 310), font_size=18)
    # Preserve the independent local exposure of the ink under the fold.
    alpha = mask.astype(np.float32) / 255
    pixels = np.rint(pixels.astype(np.float32) - 14 * alpha[:, :, None]).clip(0, 255).astype(np.uint8)
    pen = Image.new('L', (width, height), 0)
    ImageDraw.Draw(pen).line(((340, 465), (380, 430), (430, 500),
                             (470, 455), (520, 480), (570, 445)), fill=255, width=2)
    pen = np.asarray(pen)
    pixels = _paint(pixels, pen, (24, 49, 141))
    output = np.asarray(cleanup_paper(Image.fromarray(pixels), cv=cv2, np=np))
    ink = mask >= 200
    blank = cv2.dilate(((mask > 0) | (pen > 0)).astype(np.uint8),
                       np.ones((11, 11), np.uint8)) == 0
    assert _contrast(output, blank, ink) >= 25
    gray = cv2.cvtColor(output, cv2.COLOR_RGB2GRAY)
    assert float(np.mean(gray[ink] < 245)) >= .98
    ink = pen >= 220
    old, new = pixels[ink].astype(np.int16), output[ink].astype(np.int16)
    assert float(np.mean(old.argmax(axis=1) == new.argmax(axis=1))) >= .99
    assert float(np.median(np.ptp(new, axis=1))) >= float(np.median(np.ptp(old, axis=1))) * .9


def test_rectified_cleanup_preserves_colored_print_and_handwriting_hues():
    size = (1000, 750)
    pixels = np.full((size[1], size[0], 3), (195, 205, 218), np.uint8)
    marks = []
    for index, color in enumerate(((14, 43, 142), (146, 28, 22), (18, 133, 66), (14, 118, 171))):
        mask = _writing(size, 'COLOR NOTE %02d' % index, (110, 75 + index * 145), font_size=38)
        pixels = _paint(pixels, mask, color)
        marks.append(mask)
    output = np.asarray(cleanup_paper(Image.fromarray(pixels), cv=cv2, np=np))
    blank = np.maximum.reduce(marks) == 0
    for mask in marks:
        ink = mask >= 220
        old, new = pixels[ink].astype(np.int16), output[ink].astype(np.int16)
        assert float(np.mean(old.argmax(axis=1) == new.argmax(axis=1))) >= .98
        assert float(np.median(np.ptp(new, axis=1))) >= float(np.median(np.ptp(old, axis=1))) * .8
        assert _contrast(output, blank, ink) >= max(40, _contrast(pixels, blank, ink) * .9)


def test_rectified_cleanup_retains_large_solid_printed_cells():
    pixels = np.full((650, 900, 3), 200, np.uint8)
    pixels[170:270, 140:340] = 35
    output = np.asarray(cleanup_paper(Image.fromarray(pixels), cv=cv2, np=np))
    assert float(np.mean(output[175:265, 145:335] <= 70)) >= .99, 'Solid source print must not become blank paper'


def test_rectified_cleanup_keeps_faint_blue_ink_distinct_from_neutral_paper():
    size = (900, 650)
    paper_color, ink_color = np.array((199, 205, 211)), np.array((185, 195, 207))
    pixels = np.full((size[1], size[0], 3), paper_color, np.uint8)
    mask = _writing(size, 'FAINT BLUE SAMPLE', (100, 200), font_size=24)
    pixels = _paint(pixels, mask, ink_color)
    output = np.asarray(cleanup_paper(Image.fromarray(pixels), cv=cv2, np=np))
    ink = mask >= 220
    new = output[ink].astype(np.int16)
    # Compare the true ink color after subtracting the independently specified
    # blue paper cast, rather than requiring that cast remain on clean paper.
    expected_color = np.rint(255 * ink_color / paper_color)
    assert float(np.mean(new.argmax(axis=1) == 2)) >= .98, 'Faint blue handwriting must stay blue'
    assert float(np.median(np.ptp(new, axis=1))) >= float(np.ptp(expected_color)) * .8


def test_rectified_cleanup_obeys_bounded_mask_and_white_unphotographed_canvas():
    pixels = np.full((700, 1000, 3), (27, 32, 40), np.uint8)
    pixels[100:600, 150:900] = (189, 201, 213)
    mask = np.zeros((140, 200), np.uint8)
    mask[20:120, 30:180] = 255
    output = np.asarray(cleanup_paper(Image.fromarray(pixels), paper_mask=mask, cv=cv2, np=np))
    assert np.all(output[:100] == 255) and np.all(output[600:] == 255)
    assert np.all(output[:, :150] == 255) and np.all(output[:, 900:] == 255)
    assert float(np.mean(output[120:580, 170:880] >= 250)) >= .99


def test_rectified_cleanup_bounds_all_native_work_arrays_and_guards_oversized_sources():
    calls = []

    class BoundedCv:
        def __getattr__(self, name):
            function = getattr(cv2, name)
            if not callable(function):
                return function

            def checked(*args, **kwargs):
                for value in args:
                    if isinstance(value, np.ndarray) and value.ndim >= 2:
                        assert value.shape[0] * value.shape[1] <= 1_000_000, name
                result = function(*args, **kwargs)
                for value in result if isinstance(result, tuple) else (result,):
                    if isinstance(value, np.ndarray) and value.ndim >= 2:
                        assert value.shape[0] * value.shape[1] <= 1_000_000, name
                if name == 'bilateralFilter':
                    calls.append(args[0].shape)
                return result
            return checked

    image = Image.new('RGB', (2440, 2230), (197, 205, 213))
    native_mask = np.full((image.height, image.width), 255, np.uint8)
    output = cleanup_paper(image, paper_mask=native_mask, cv=BoundedCv(), np=np)
    assert output.size == image.size and len(calls) == 9
    oversized = Image.new('RGB', (8001, 5000), 'white')
    assert cleanup_paper(oversized, cv=BoundedCv(), np=np) is oversized


def test_rectified_cleanup_native_filters_match_independent_full_canvas_at_seams():
    width = height = 2140
    pixels = np.full((height, width, 3), (193, 203, 214), np.uint8)
    patch = Image.new('RGB', (190, 190), (193, 203, 214))
    draw = ImageDraw.Draw(patch)
    draw.text((4, 4), 'EDGE 2741', font=ImageFont.truetype(str(FONT), 20),
              fill=(181, 191, 202))
    draw.line(((13, 127), (42, 94), (64, 144), (95, 105), (135, 137)),
              fill=(24, 45, 140), width=2)
    for left, top in ((140, 140), (890, 140), (140, 890), (890, 890), (1830, 1830)):
        pixels[top:top + 190, left:left + 190] = np.asarray(patch)
    image = Image.fromarray(pixels)
    output = np.asarray(cleanup_paper(image, cv=cv2, np=np))
    smooth = cv2.bilateralFilter(pixels, 5, 11, 2)
    gray = cv2.cvtColor(smooth, cv2.COLOR_RGB2GRAY)
    closed = cv2.morphologyEx(gray, cv2.MORPH_CLOSE,
                             cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21)))
    paper = cv2.GaussianBlur(closed, (5, 5), .8)

    class FullNativeReference:
        def __init__(self):
            self.calls = 0
            self.bounds = None

        def __getattr__(self, name):
            return getattr(cv2, name)

        def bilateralFilter(self, array, *args, **kwargs):
            row, column = divmod(self.calls, 3)
            self.calls += 1
            left, top = max(0, column * 928 - 36), max(0, row * 928 - 36)
            h, w = array.shape[:2]
            self.bounds = (slice(top, top + h), slice(left, left + w))
            assert np.array_equal(array, pixels[self.bounds])
            return smooth[self.bounds]

        def morphologyEx(self, array, operation, kernel, *args, **kwargs):
            if operation == cv2.MORPH_CLOSE and kernel.shape == (21, 21):
                assert np.array_equal(array, gray[self.bounds])
                return closed[self.bounds]
            return cv2.morphologyEx(array, operation, kernel, *args, **kwargs)

        def GaussianBlur(self, array, kernel, sigma, *args, **kwargs):
            if kernel == (5, 5):
                assert np.array_equal(array, closed[self.bounds])
                return paper[self.bounds]
            return cv2.GaussianBlur(array, kernel, sigma, *args, **kwargs)

    oracle = FullNativeReference()
    reference = np.asarray(cleanup_paper(image, cv=oracle, np=np))
    assert oracle.calls == 9
    assert np.array_equal(output, reference), 'Tile borders must not alter fine print or pen strokes'


def test_rectified_cleanup_does_not_invent_a_dark_frame_beside_unknown_canvas():
    width, height = 960, 1200
    yy, xx = np.mgrid[:height, :width]
    paper = xx >= np.maximum((yy - 480) * .14, 0)
    pixels = np.full((height, width, 3), 255, np.uint8)
    pixels[paper] = (135, 148, 166)
    # Geometry's bounded observed mask is independent of the cleanup function.
    mask = cv2.resize(paper.astype(np.uint8) * 255, (410, 512),
                      interpolation=cv2.INTER_LINEAR)
    output = np.asarray(cleanup_paper(Image.fromarray(pixels),
                                     paper_mask=mask, cv=cv2, np=np))
    distance = cv2.distanceTransform(paper.astype(np.uint8), cv2.DIST_L2, 5)
    boundary = paper & (distance <= 10)
    assert float(np.mean(output[boundary] >= 250)) >= .995, 'Unknown white padding must not become a false paper outline'
    assert np.all(output[~paper] == 255), 'Unphotographed canvas remains white'


def test_rectified_cleanup_preserves_all_dense_camera_barcode_stripes():
    from processors.document_scan import prepare_image
    from scripts.operations.service_checks_documents import held_dense_document, held_document_barcode_scanlines
    source, _, _ = held_dense_document()
    cropped, flags = prepare_image(source, enhance_text=False)
    assert flags['cropped']
    output = cleanup_paper(cropped, cv=cv2, np=np)
    median_rows, complete_line = held_document_barcode_scanlines(output)
    assert median_rows >= 48 and complete_line >= 68, 'Do not merge narrow spaces between any of the34 anonymous stripes'
