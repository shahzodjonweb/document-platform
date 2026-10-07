"""Physical quality checks for partial-page illumination and contrast cleanup.

Every image/ink mask is procedural and anonymous. No customer image or text is
loaded, and expected writing is established before any enhancement operation.
"""
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from processors.partial_scan_cleanup import enhance_paper


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
