"""Physical quality checks for partial-page illumination and contrast cleanup.

Every image/ink mask is procedural and anonymous. No customer image or text is
loaded, and expected writing is established before any enhancement operation.
"""
import io
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from processors import partial_scan_cleanup
from processors.partial_scan_cleanup import BILATERAL, HALO, STEP, cleanup_paper, enhance_paper


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


@pytest.mark.parametrize('scale,key', ((1., 1), (2., 2)))
def test_rectified_cleanup_native_filters_match_independent_full_canvas_at_seams(scale, key):
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
    output = np.asarray(cleanup_paper(image, scale=scale, cv=cv2, np=np))
    # The tile geometry is read from the module so a retuned bilateral moves
    # the oracle with it; the budget it must respect is fixed here.
    step, halo = STEP[key], HALO[key]
    assert step + 2 * halo <= 1000
    smooth = cv2.bilateralFilter(pixels, *BILATERAL[key])
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
            left, top = max(0, column * step - halo), max(0, row * step - halo)
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
    reference = np.asarray(cleanup_paper(image, scale=scale, cv=oracle, np=np))
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


def _mottled(width, height, seed):
    # Phone grain after demosaicing and JPEG is correlated over a few pixels;
    # a three-level amplitude is what a dim indoor photo leaves on paper.
    rng = np.random.default_rng(seed)
    noise = cv2.GaussianBlur(rng.normal(0, 1, (height, width)).astype(np.float32), (0, 0), 3)
    noise *= 3 / noise.std()
    return np.rint(np.array((198, 204, 211)) + noise[:, :, None]).clip(0, 255).astype(np.uint8)


def test_rectified_cleanup_whitens_mottled_paper_by_its_own_noise_floor():
    pixels = _mottled(1100, 800, 7)
    output = np.asarray(cleanup_paper(Image.fromarray(pixels), cv=cv2, np=np))
    gray = cv2.cvtColor(output, cv2.COLOR_RGB2GRAY)
    assert float(np.mean(gray >= 250)) >= .99, 'Grain the page itself measures as noise must print white'


def test_rectified_cleanup_measures_clean_paper_at_the_historical_floors():
    # A clean render must measure nothing, so its tone curve is unchanged.
    # Dense print fills every cell, and must not pass for grain either.
    from processors.document_scan import prepare_image
    from scripts.operations.service_checks_documents import held_dense_document
    source, _, _ = held_dense_document()
    dense, _ = prepare_image(source, enhance_text=False)
    flat = Image.new('RGB', (900, 650), (199, 205, 211))
    for image in (flat, dense):
        rgb = np.asarray(image)
        small = image.copy()
        small.thumbnail((512, 512), Image.Resampling.LANCZOS)
        region = np.full((small.height, small.width), 255, np.uint8)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        floors = partial_scan_cleanup._noise_floor(rgb, np.asarray(small).copy(), region, kernel, cv2, np)
        assert floors == (partial_scan_cleanup.NOISE_FLOOR, partial_scan_cleanup.CHROMA_FLOOR)
    pixels = _mottled(1100, 800, 7)
    small = Image.fromarray(pixels)
    small.thumbnail((512, 512), Image.Resampling.LANCZOS)
    floor, _ = partial_scan_cleanup._noise_floor(pixels, np.asarray(small).copy(),
        np.full((small.height, small.width), 255, np.uint8),
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)), cv2, np)
    assert floor > partial_scan_cleanup.NOISE_FLOOR, 'Grainy paper must raise its own floor'


def _page_with_period_and_specks(size, font_size):
    width, height = size
    pixels = np.full((height, width, 3), (200, 205, 210), np.uint8)
    word = _writing(size, 'Total due', (100, 300), font_size=font_size)
    sentence = _writing(size, 'Total due.', (100, 300), font_size=font_size)
    period = (sentence >= 128) & (word == 0)
    pixels = _paint(pixels, sentence, (40, 40, 40))
    specks = np.zeros((height, width), bool)
    for x, y in ((500, 150), (700, 420), (250, 560), (820, 200), (130, 460)):
        specks[y:y + 2, x:x + 2] = True
    pixels[specks] = 60
    return pixels, sentence, period, specks


def test_rectified_cleanup_removes_isolated_specks_but_keeps_a_period():
    pixels, sentence, period, specks = _page_with_period_and_specks((1000, 700), 14)
    assert 2 <= int(period.sum()) <= 10, 'The period must be speck-sized for this to mean anything'
    # Speck-sized print standing apart from other ink in its own window,
    # but in a row of print: a nil-value hyphen in its label's row, a
    # bullet before its item and a sparse dotted fill-in line.
    size = (1000, 700)
    label = _writing(size, 'Deferred tax', (100, 72), font_size=14)
    hyphen = _writing(size, '-', (380, 72), font_size=14)
    bullet = _writing(size, '\u2022', (100, 352), font_size=9)
    item = _writing(size, 'Bullet item', (130, 352), font_size=14)
    dotted = np.zeros(sentence.shape, np.uint8)
    for left in range(100, 900, 16):
        dotted[640:642, left:left + 2] = 255
    marks = {'hyphen': hyphen, 'bullet': bullet, 'dotted line': dotted}
    for mask in (label, item, *marks.values()):
        pixels = _paint(pixels, mask, (40, 40, 40))
    output = np.asarray(cleanup_paper(Image.fromarray(pixels), cv=cv2, np=np))
    gray = cv2.cvtColor(output, cv2.COLOR_RGB2GRAY)
    assert np.all(gray[specks] >= 250), 'Isolated dust must not print'
    assert float(np.max(gray[period])) < 120, 'A period beside its word is print, not dust'
    glyphs = (sentence >= 200) & ~period
    assert float(np.mean(gray[glyphs] < 120)) >= .95
    for name, mask in marks.items():
        assert float(np.min(gray[mask >= 128])) < 120, f'A {name} in a row of print is print'


def _fine_grain(width, height, seed, amplitude=1.):
    rng = np.random.default_rng(seed)
    noise = cv2.GaussianBlur(rng.normal(0, 1, (height, width)).astype(np.float32), (0, 0), 1)
    noise *= amplitude / noise.std()
    return np.rint(np.array((198, 204, 211)) + noise[:, :, None]).clip(0, 255).astype(np.uint8)


def _floor_of(pixels):
    small = Image.fromarray(pixels)
    small.thumbnail((512, 512), Image.Resampling.LANCZOS)
    return partial_scan_cleanup._noise_floor(
        pixels, np.asarray(small).copy(), np.full((small.height, small.width), 255, np.uint8),
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)), cv2, np)[0]


@pytest.mark.parametrize('contrast', (10, 14))
def test_rectified_cleanup_keeps_faint_pencil_that_fills_every_cell(contrast):
    # Wavy pencil lines every 34 px leave no blank sample cell. Measured as
    # grain they would lift the floor and erase the very strokes measured.
    width, height = 1100, 800
    canvas = Image.new('L', (width, height), 0)
    draw = ImageDraw.Draw(canvas)
    rng = np.random.default_rng(2)
    for top in range(40, height - 40, 34):
        draw.line([(x, top + 10 * np.sin(x / 7) * rng.uniform(.5, 1)) for x in range(30, width - 30, 3)],
                  fill=255, width=2)
    strokes = cv2.GaussianBlur(np.asarray(canvas), (0, 0), .8)
    paper = _fine_grain(width, height, 4)
    pixels = _paint(paper, strokes, tuple(level - contrast for level in (198, 204, 211)))
    assert _floor_of(pixels) <= _floor_of(paper), 'Pencil is not grain'
    gray = cv2.cvtColor(np.asarray(cleanup_paper(Image.fromarray(pixels), cv=cv2, np=np)), cv2.COLOR_RGB2GRAY)
    ink = strokes >= 200
    blank = cv2.dilate((strokes > 0).astype(np.uint8), np.ones((7, 7), np.uint8)) == 0
    assert float(np.mean(gray[ink] <= 245)) >= .95, 'Faint handwriting must still print'
    assert float(np.mean(gray[blank] >= 250)) >= .99


def test_rectified_cleanup_does_not_turn_compression_rings_beside_bold_print_into_dots():
    width, height = 1200, 500
    mask = _writing((width, height), '43144 LBS', (100, 150), font_size=110)
    rng = np.random.default_rng(3)
    ringing = cv2.GaussianBlur(rng.normal(0, 1, (height, width)).astype(np.float32), (0, 0), 1.2)
    ringing = np.clip(ringing / ringing.std(), 0, None) * 9
    band = (cv2.dilate((mask > 0).astype(np.uint8), np.ones((15, 15), np.uint8)) > 0) & (mask == 0)
    pixels = np.full((height, width, 3), (200, 204, 208), np.float32) - (ringing * band)[:, :, None]
    pixels = _paint(np.rint(pixels).astype(np.uint8), mask, (30, 30, 30))
    gray = cv2.cvtColor(np.asarray(cleanup_paper(Image.fromarray(pixels), scale=2., cv=cv2, np=np)),
                        cv2.COLOR_RGB2GRAY)
    beside = band & ~(cv2.dilate((mask > 128).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0)
    assert int((gray[beside] < 160).sum()) == 0, 'Ringing beside bold print must not print as dots'
    assert float(np.mean(gray[mask > 200] < 80)) >= .99, 'The print itself stays bold'


def test_despeckle_never_punches_the_dark_core_out_of_a_faint_glyph():
    frame = np.full((200, 200, 3), 255, np.uint8)
    frame[90:93, 60:140] = 222              # a light grey stroke ...
    frame[90:92, 99:101] = 190              # ... whose darkest core is speck-sized
    before = frame.copy()
    partial_scan_cleanup._despeckle(frame, 1000, cv2, np)
    assert np.array_equal(frame, before), 'A core inside its stroke is not isolated'
    frame[150:152, 40:42] = 60              # real dust on blank paper still goes
    partial_scan_cleanup._despeckle(frame, 1000, cv2, np)
    assert np.all(frame[150:152, 40:42] == 255) and np.array_equal(frame[:140], before[:140])


def test_mid_grey_dust_in_a_row_of_print_goes_where_a_dark_hyphen_stays():
    # A nil-value hyphen a column away from its row's label prints as dark
    # as the label and stays; a speck no darker than mid-grey there is dust.
    frame = np.full((400, 1000, 3), 255, np.uint8)
    label = _writing((1000, 400), 'Weight', (40, 180), font_size=28) >= 128
    frame[label] = 20
    frame[198:201, 390:397] = 30            # the dark hyphen, 250 px along the row
    frame[195:198, 420:423] = 150           # mid-grey dust beside it, in the same row
    rows, ruled = partial_scan_cleanup._row_ink(frame, np)
    partial_scan_cleanup._despeckle(frame, 1000, cv2, np, rows, ruled=ruled)
    assert np.all(frame[198:201, 390:397] == 30), 'A dark mark in a row of print is print'
    assert np.all(frame[195:198, 420:423] == 255), 'Mid-grey dust is not punctuation'
    assert np.all(frame[label] == 20)


def test_dust_just_under_a_table_rule_is_alone():
    # A rule is no word for a speck to punctuate: dust a few pixels under it
    # goes, while the period ending a word above the rule stays.
    frame = np.full((400, 1000, 3), 255, np.uint8)
    frame[250:253, 50:950] = 25                                    # the rule
    sentence = _writing((1000, 400), 'Total due.', (100, 190), font_size=28) >= 128
    frame[sentence] = 20
    frame[258:261, 600:603] = 40                                   # dust 5 px under the rule
    rows, ruled = partial_scan_cleanup._row_ink(frame, np)
    partial_scan_cleanup._despeckle(frame, 1000, cv2, np, rows, ruled=ruled)
    assert np.all(frame[258:261, 600:603] == 255), 'Dust under a rule is removed'
    assert np.all(frame[sentence] == 20) and np.all(frame[250:253, 50:950] == 25)


def test_rectified_cleanup_darkens_thin_grey_text_by_the_stroke_curve(monkeypatch):
    size = (1000, 700)
    pixels = np.full((size[1], size[0], 3), 205, np.uint8)
    mask = _writing(size, 'thin grey line of print 2741', (100, 300), font_size=16)
    pixels = _paint(pixels, mask, (140, 140, 140))
    ink = mask >= 200
    curved = cv2.cvtColor(np.asarray(cleanup_paper(Image.fromarray(pixels), cv=cv2, np=np)),
                          cv2.COLOR_RGB2GRAY)
    # The same cleanup without the curve and the finishing pass is the
    # tone the page had before them.
    monkeypatch.setattr(partial_scan_cleanup, '_stroke_curve', lambda np: np.zeros(256, np.float32))
    monkeypatch.setattr(partial_scan_cleanup, '_finish', lambda *args: None)
    linear = cv2.cvtColor(np.asarray(cleanup_paper(Image.fromarray(pixels), cv=cv2, np=np)),
                          cv2.COLOR_RGB2GRAY)
    assert float(np.median(linear[ink]) - np.median(curved[ink])) >= 40, 'Thin grey print must come out bold'
    assert np.all(curved[ink] <= linear[ink] + 8), 'The curve never lightens a stroke'
    blank = cv2.dilate((mask > 0).astype(np.uint8), np.ones((9, 9), np.uint8)) == 0
    assert np.array_equal(curved[blank], linear[blank]), 'White paper is untouched'


def test_rectified_cleanup_curve_is_monotone_and_never_lightens():
    extra = partial_scan_cleanup._stroke_curve(np)
    level = np.arange(256, dtype=np.float32)
    toned = level - extra
    assert np.all(extra >= 0) and np.all(extra[215:] == 0), 'Identity through 40 levels of darkness'
    assert np.all(np.diff(toned) >= 0), 'Tone order is kept'
    assert toned[95] <= .5, 'Darkness 160 is solid black'


def test_despeckle_and_sharpening_are_identical_across_finish_frame_seams(monkeypatch):
    width, height = 2100, 1500
    page = np.full((height, width, 3), 255, np.uint8)
    step, halo = partial_scan_cleanup._finish_tiling(max(width, height), 1.)
    assert step < width and step < height
    seams = (step, 2 * step)
    marks = Image.new('L', (width, height), 0)
    draw = ImageDraw.Draw(marks)
    font = ImageFont.truetype(str(FONT), 14)
    specks = []
    for seam in seams:
        for index, offset in enumerate(range(-24, 25, 6)):
            # Words whose period falls on the far side of a seam, and dust on
            # and around each seam, spaced wider than the isolation window.
            # Dust shares no text row with print within the despeckle's row
            # reach (a third of the page), or it would rightly count as print.
            draw.text((seam + offset - 60, 100 + 8 * (offset + 24)), 'word.', font=font, fill=255)
            draw.text((100 + 10 * (offset + 24), seam + offset - 8), 'end.', font=font, fill=255)
            specks.append((seam + offset, 1230 + 30 * index))
            if seam < height:
                specks.append((1400 + 45 * index, seam + offset))
    for x, y in specks:
        draw.rectangle((x, y, x + 1, y + 1), fill=255)
    # A dotted fill-in line across both vertical seams: each dot is alone
    # in its window, but its row is print, judged the same in every frame.
    dots = [(x, 1100) for x in range(200, 2000, 24)]
    for x, y in dots:
        draw.rectangle((x, y, x + 1, y + 1), fill=255)
    tone = np.asarray(marks, np.float32) / 255
    page = np.rint(page * (1 - tone[:, :, None]) + 30 * tone[:, :, None]).astype(np.uint8)
    tiled = page.copy()
    partial_scan_cleanup._finish(tiled, 1., cv2, np)
    monkeypatch.setattr(partial_scan_cleanup, 'FINISH_BUDGET', 10 ** 5)
    whole = page.copy()
    partial_scan_cleanup._finish(whole, 1., cv2, np)
    assert np.array_equal(tiled, whole), 'Frame seams must not change which marks are dust'
    gray = cv2.cvtColor(whole, cv2.COLOR_RGB2GRAY)
    assert all(np.all(gray[y:y + 2, x:x + 2] >= 250) for x, y in specks), 'Dust on a seam is still dust'
    assert all(np.all(gray[y:y + 2, x:x + 2] < 120) for x, y in dots), 'A dotted line is print'
    assert int((gray < 120).sum()) >= int((tone > .9).sum()) - 4 * len(specks) - 50, 'Words stay'


def test_rectified_cleanup_whitens_the_traced_exterior_without_touching_print():
    width, height = 900, 650
    clean = np.full((height, width, 3), (199, 205, 211), np.uint8)
    mask = _writing((width, height), 'INTERIOR PRINT 2741', (120, 260), font_size=40)
    clean = _paint(clean, mask, (40, 40, 40))
    rimmed = clean.copy()
    exterior = np.zeros((height, width), np.uint8)
    exterior[:6], exterior[-6:], exterior[:, :6], exterior[:, -6:] = 255, 255, 255, 255
    rimmed[exterior > 0] = (52, 50, 47)
    plain = np.asarray(cleanup_paper(Image.fromarray(rimmed), cv=cv2, np=np))
    assert float(np.mean(cv2.cvtColor(plain, cv2.COLOR_RGB2GRAY)[exterior > 0] < 120)) > .5, \
        'Without the mask the desk rim prints dark'
    output = np.asarray(cleanup_paper(Image.fromarray(rimmed), exterior=exterior > 0, cv=cv2, np=np))
    assert np.all(output[exterior > 0] == 255), 'The desk fringe outside the traced edge is not paper'
    reference = np.asarray(cleanup_paper(Image.fromarray(clean), cv=cv2, np=np))
    interior = np.zeros((height, width), bool)
    interior[40:-40, 40:-40] = True
    assert np.array_equal(output[interior], reference[interior]), 'Print inside the page is untouched'


def _camera_page(width, height, seed, paper=(196, 201, 207)):
    # Correlated grain at a level a phone leaves on paper after JPEG.
    rng = np.random.default_rng(seed)
    noise = cv2.GaussianBlur(rng.normal(0, 1, (height, width)).astype(np.float32), (0, 0), 1)
    noise *= 1.5 / noise.std()
    return np.array(paper, np.float32) + noise[:, :, None]


def _darken(pixels, coverage, depth):
    # Ink removes ``depth`` levels where it fully covers the paper.
    return pixels - (coverage * depth)[:, :, None]


@pytest.mark.parametrize('scale', (1., 2.))
def test_rectified_cleanup_draws_a_faint_rule_as_one_continuous_solid_line(scale):
    # A faint table rule photographed at about 200 dpi: three pixels wide,
    # softened by the lens, its contrast wandering between 40 and 80 along
    # its length, and bold print passing a little below part of it. Every
    # column of the rule must print, at one solid tone, never as dashes.
    width, height = 1600, 700
    pixels = _camera_page(width, height, 11)
    rule = np.zeros((height, width), np.float32)
    rule[299:302, 100:1500] = 1
    rule[100:600, 799:802] = 1
    rule = cv2.GaussianBlur(rule, (0, 0), .8 * scale)
    xx = np.arange(width, dtype=np.float32)
    depth = 60 + 20 * np.sin(xx / 37) * np.cos(xx / 113)
    pixels = _darken(pixels, rule, np.broadcast_to(depth, (height, width)))
    bold = cv2.GaussianBlur(_writing((width, height), 'TOTAL WEIGHT 43144', (180, 312),
                                     font_size=40).astype(np.float32) / 255, (0, 0), .8)
    pixels = _darken(pixels, bold, 160)
    pixels = np.rint(pixels).clip(0, 255).astype(np.uint8)
    gray = cv2.cvtColor(np.asarray(cleanup_paper(Image.fromarray(pixels), scale=scale, cv=cv2, np=np)),
                        cv2.COLOR_RGB2GRAY)
    across = gray[293:308, 100:1500].min(axis=0).astype(np.float32)
    assert float(np.mean(across >= 128)) <= .01, 'A faint rule must not break into dashes'
    assert float(np.median(across)) <= 40 and float(np.std(across)) <= 25, 'One solid tone along the rule'
    down = gray[110:590, 793:808].min(axis=1).astype(np.float32)
    assert float(np.mean(down >= 128)) <= .01 and float(np.median(down)) <= 40
    blank = cv2.dilate(((rule > .05) | (bold > .05)).astype(np.uint8), np.ones((15, 15), np.uint8)) == 0
    assert float(np.mean(gray[blank] >= 250)) >= .99


def test_rectified_cleanup_prints_grey_camera_text_solid_without_fattening_it():
    # Body text a camera renders grey and soft: stroke bodies come out near
    # solid black like a scanner app's, edges keep a few anti-aliased
    # levels, and the strokes are not thickened by the lens blur.
    size = (1000, 400)
    mask = _writing(size, 'Each carrier of, and any party at any time 2741', (60, 160), font_size=22)
    coverage = cv2.GaussianBlur(mask.astype(np.float32) / 255, (0, 0), 1)
    pixels = np.rint(_darken(_camera_page(*size, 5), coverage, 90)).clip(0, 255).astype(np.uint8)
    gray = cv2.cvtColor(np.asarray(cleanup_paper(Image.fromarray(pixels), scale=2., cv=cv2, np=np)),
                        cv2.COLOR_RGB2GRAY)
    body = mask >= 230
    assert float(np.median(gray[body])) <= 20, 'Stroke bodies print solid'
    assert float(np.mean(gray[body] < 100)) >= .95
    printed = int((gray < 128).sum())
    assert .8 <= printed / int((mask >= 128).sum()) <= 1.5, 'Strokes keep their weight'
    edges = (cv2.dilate((mask >= 128).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0) & (mask < 128)
    assert float(np.mean((gray[edges] > 40) & (gray[edges] < 230))) >= .1, 'Edges stay anti-aliased'


def test_rectified_cleanup_removes_a_stray_faint_mark_but_keeps_print_and_its_period():
    # A page of firm print with a faint dust mark and a faint, broken
    # bracket-like smudge on blank paper, well away from any row of print,
    # barely above the page's grain (the cleanup alone still prints them).
    # Both go; the period ending the sentence, no larger than the dust,
    # stays with its word.
    size = (1600, 1100)
    pixels = _camera_page(*size, 8)
    sentence = _writing(size, 'Total due on delivery.', (120, 300), font_size=28)
    words = _writing(size, 'Total due on delivery', (120, 300), font_size=28)
    period = (sentence >= 128) & (words == 0)
    pixels = _darken(pixels, cv2.GaussianBlur(sentence.astype(np.float32) / 255, (0, 0), .8), 150)
    stray = np.zeros(size[::-1], np.float32)
    cv2.circle(stray, (1200, 700), 2, 1, -1)
    cv2.line(stray, (900, 760), (897, 772), 1, 2)
    cv2.line(stray, (897, 780), (900, 792), 1, 2)
    stray = cv2.GaussianBlur(stray, (0, 0), .8)
    pixels = np.rint(_darken(pixels, stray, 22)).clip(0, 255).astype(np.uint8)
    gray = cv2.cvtColor(np.asarray(cleanup_paper(Image.fromarray(pixels), scale=2., cv=cv2, np=np)),
                        cv2.COLOR_RGB2GRAY)
    assert int((gray[stray > .2] < 245).sum()) == 0, 'Stray faint marks on blank paper do not print'
    assert float(np.min(gray[period])) < 120, 'A period beside its word is print'
    assert float(np.mean(gray[words >= 200] < 120)) >= .95


def test_stray_faint_marks_are_judged_alike_across_finish_frame_seams(monkeypatch):
    width, height = 2100, 1500
    step, halo = partial_scan_cleanup._finish_tiling(max(width, height), 1., True)
    seams = (step, 2 * step)
    marks = Image.new('L', (width, height), 0)
    draw = ImageDraw.Draw(marks)
    font = ImageFont.truetype(str(FONT), 14)
    faint = Image.new('L', (width, height), 0)
    faint_draw = ImageDraw.Draw(faint)
    strays = []
    for seam in seams:
        for index, offset in enumerate(range(-30, 31, 10)):
            draw.text((seam + offset - 60, 100 + 9 * (offset + 30)), 'word.', font=font, fill=255)
            # Faint smudges, larger than a speck, on and around each seam,
            # and one beside a word of print, which stays.
            box = (seam + offset, 1200 + 40 * index, seam + offset + 5, 1200 + 40 * index + 14)
            faint_draw.rectangle(box, fill=255)
            strays.append(box)
            if seam < height:
                box = (200 + 60 * index, seam + offset, 214 + 60 * index, seam + offset + 4)
                faint_draw.rectangle(box, fill=255)
                strays.append(box)
    draw.text((1300, 636), 'kept words', font=font, fill=255)
    tone = np.maximum(np.asarray(marks, np.float32), np.asarray(faint, np.float32)) / 255
    tone[640:653, 1400:1405] = 1
    page = np.full((height, width, 3), 255, np.uint8)
    page = np.rint(page * (1 - tone[:, :, None]) + 30 * tone[:, :, None]).astype(np.uint8)
    # The source contrast behind the page: firm print, smudges barely above
    # a grain floor of 6 and a faint mark in a row of print.
    evidence = np.where(np.asarray(faint) > 0, 20, np.where(np.asarray(marks) > 0, 150, 0)).astype(np.uint8)
    evidence[640:653, 1400:1405] = 40
    tiled = page.copy()
    partial_scan_cleanup._finish(tiled, 1., cv2, np, evidence, 60., 6.)
    monkeypatch.setattr(partial_scan_cleanup, 'FINISH_BUDGET', 10 ** 5)
    whole = page.copy()
    partial_scan_cleanup._finish(whole, 1., cv2, np, evidence, 60., 6.)
    assert np.array_equal(tiled, whole), 'Frame seams must not change which marks are stray'
    gray = cv2.cvtColor(whole, cv2.COLOR_RGB2GRAY)
    assert all(np.all(gray[y0:y1 + 1, x0:x1 + 1] >= 250) for x0, y0, x1, y1 in strays), 'Stray marks go'
    assert float(np.min(gray[640:653, 1400:1405])) < 120, 'A faint mark in a row of print stays'
    assert int((gray < 120).sum()) >= int((np.asarray(marks) > 200).sum()) * .9, 'Words stay'


@pytest.mark.parametrize('long_edge', (5712, 7680))
def test_finishing_frames_fit_and_run_on_a_large_photo(long_edge):
    # A 24 MP phone page (5712 px) or a long receipt (7680 px): the stray
    # pass widens the finishing halo, which must still fit inside the frame
    # with room for the rows carried between bands, and every frame runs.
    for edge in (2339, 4984, long_edge, partial_scan_cleanup.FINISH_EDGE):
        step, halo = partial_scan_cleanup._finish_tiling(edge, 1., True)
        assert halo <= step and step + 2 * halo <= partial_scan_cleanup.FINISH_BUDGET
    width = 1200
    pixels = np.full((long_edge, width, 3), (196, 201, 207), np.float32)
    text = _writing((width, long_edge), 'Received in good order', (100, 400), font_size=60)
    pixels = np.rint(_darken(pixels, text.astype(np.float32) / 255, 160)).clip(0, 255).astype(np.uint8)
    pixels[3000:3014, 600:614] = 40
    gray = cv2.cvtColor(np.asarray(cleanup_paper(Image.fromarray(pixels), cv=cv2, np=np)), cv2.COLOR_RGB2GRAY)
    assert int((gray[3000:3014, 600:614] < 245).sum()) == 0, 'Despeckle runs on a large page'
    assert float(np.mean(gray[text >= 200] < 120)) >= .95


def _grey_marks_page(scale):
    # A camera-like page of black body text with legible marks in grey
    # print or pencil that a scanner app must keep: a page number, a margin
    # note, a tick and a cross inside ruled cells, a form label with its
    # dotted fill-in line.
    width, height = 1654, 2339
    paper = np.full((height, width, 3), (203, 203, 198), np.float32)
    paper *= (.93 + .07 * np.arange(width, dtype=np.float32) / width)[None, :, None]
    layers = {name: Image.new('L', (width, height), 0) for name in
              ('body', 'rules', 'tick', 'cross', 'page', 'note', 'label', 'dots')}
    draw = {name: ImageDraw.Draw(layer) for name, layer in layers.items()}
    font = lambda size: ImageFont.truetype(str(FONT), size)
    for index in range(6):
        draw['body'].text((150, 150 + 50 * index), 'Carrier shall deliver within the agreed window',
                          font=font(28), fill=255)
    for y in (800, 900, 1000):
        draw['rules'].line([(150, y), (1500, y)], fill=255, width=3)
    for x in (150, 500, 850, 1200, 1500):
        draw['rules'].line([(x, 800), (x, 1000)], fill=255, width=3)
    draw['body'].text((170, 830), 'Item A', font=font(28), fill=255)
    draw['tick'].line([(1015, 855), (1022, 865), (1036, 840)], fill=255, width=3)
    draw['cross'].line([(665, 940), (685, 960)], fill=255, width=2)
    draw['cross'].line([(685, 940), (665, 960)], fill=255, width=2)
    draw['page'].text((820, 2230), '7', font=font(26), fill=255)
    draw['note'].text((1540, 380), 'ok', font=font(22), fill=255)
    draw['label'].text((150, 2130), 'Sign', font=font(28), fill=255)
    for x in range(240, 1500, 14):
        draw['dots'].rectangle([(x, 2155), (x + 2, 2157)], fill=255)
    tones = {'body': 35, 'rules': 40, 'tick': 155, 'cross': 150, 'page': 140, 'note': 152,
             'label': 150, 'dots': 150}
    masks = {name: np.asarray(layer) for name, layer in layers.items()}
    for name, tone in tones.items():
        alpha = (masks[name].astype(np.float32) / 255)[:, :, None]
        paper = paper * (1 - alpha) + tone * alpha
    noise = np.random.default_rng(0).normal(0, 2, paper.shape)
    pixels = cv2.GaussianBlur(np.clip(paper + noise, 0, 255).astype(np.uint8), (0, 0), 1.)
    if scale > 1:
        pixels = cv2.resize(pixels, (width // 2, height // 2), interpolation=cv2.INTER_AREA)
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, 'JPEG', quality=82)
    pixels = np.asarray(Image.open(buffer).convert('RGB'))
    if scale > 1:
        pixels = cv2.resize(pixels, (width, height), interpolation=cv2.INTER_CUBIC)
    return pixels, masks


@pytest.mark.parametrize('scale', (1., 2.))
def test_stray_pass_keeps_legible_grey_marks(scale):
    pixels, masks = _grey_marks_page(scale)
    gray = cv2.cvtColor(np.asarray(cleanup_paper(Image.fromarray(pixels), scale=scale, cv=cv2, np=np)),
                        cv2.COLOR_RGB2GRAY)
    for name in ('tick', 'cross', 'page', 'note', 'label', 'dots'):
        printed = float(np.mean(gray[masks[name] >= 128] < 200))
        assert printed >= .9, f'The grey {name} is print and stays ({printed:.2f})'
