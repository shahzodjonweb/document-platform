"""Native-pixel crop safety, independent of thumbnail detector decisions.

Every scene is generated anonymously. Ink truth comes from the source renderer;
no crop threshold, connected-component result or scanner mask defines it.
"""
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from processors.partial_document_scan import native_safe_crop_box


FONT = Path(__file__).resolve().parents[1] / 'processors/assets/fonts/NotoSans-Regular.ttf'
WIDTH, HEIGHT, BAND = 2048, 3072, 512
BACKGROUND = np.array((29, 34, 39), np.uint8)
INK_COLORS = {
    'dark': (8, 12, 16),
    'faint': (40, 45, 50),
    'blue': (14, 25, 66),
}


def _native_scene(side, *, ink=None, seam=False):
    pixels = np.full((HEIGHT, WIDTH, 3), 190, np.uint8)
    if side == 'top':
        pixels[:BAND] = BACKGROUND
        tentative = (0, BAND, WIDTH, HEIGHT)
    elif side == 'bottom':
        pixels[-BAND:] = BACKGROUND
        tentative = (0, 0, WIDTH, HEIGHT - BAND)
    elif side == 'left':
        pixels[:, :BAND] = BACKGROUND
        tentative = (BAND, 0, WIDTH, HEIGHT)
    else:
        pixels[:, -BAND:] = BACKGROUND
        tentative = (0, 0, WIDTH - BAND, HEIGHT)
    visible = np.zeros((HEIGHT, WIDTH), bool)
    if ink is not None:
        along = 958 if seam else 321
        position = {
            'top': (along, 203), 'bottom': (along, HEIGHT - 207),
            'left': (203, along), 'right': (WIDTH - 225, along),
        }[side]
        rendered = Image.new('L', (WIDTH, HEIGHT), 0)
        ImageDraw.Draw(rendered).text(position, 'ID27',
            font=ImageFont.truetype(str(FONT), 9), fill=255)
        alpha = np.asarray(rendered, np.float32) / 255
        before = pixels.copy()
        pixels = np.rint(pixels * (1 - alpha[:, :, None])
                         + np.array(INK_COLORS[ink]) * alpha[:, :, None]).astype(np.uint8)
        # All physically changed source glyph pixels, including antialias tails.
        visible = np.any(pixels != before, axis=2)
        assert int(visible.sum()) >= 20
    return Image.fromarray(pixels), tentative, visible


def _assert_visible_source_ink_retained(image, box, source_ink):
    left, top, right, bottom = box
    assert 0 <= left < right <= image.width and 0 <= top < bottom <= image.height
    retained = np.zeros(source_ink.shape, bool)
    retained[top:bottom, left:right] = True
    assert not np.any(source_ink & ~retained), 'Native crop must retain every visible source glyph pixel'
    # A safety adjustment is a literal source ROI, with no interpolation.
    crop = np.asarray(image.crop(box))
    assert np.array_equal(crop, np.asarray(image)[top:bottom, left:right])


@pytest.mark.parametrize('side', ['top', 'bottom', 'left', 'right'])
@pytest.mark.parametrize('color', list(INK_COLORS))
@pytest.mark.parametrize('seam', [False, True], ids=['within_tile', 'tile_seam'])
def test_tiny_native_references_veto_loss_in_every_exterior_band(side, color, seam):
    image, tentative, visible = _native_scene(side, ink=color, seam=seam)
    box = native_safe_crop_box(image, {'crop_box': tentative})
    _assert_visible_source_ink_retained(image, box, visible)


@pytest.mark.parametrize('side', ['top', 'bottom', 'left', 'right'])
def test_truly_blank_native_band_is_trimmed_meaningfully(side):
    image, tentative, visible = _native_scene(side)
    box = native_safe_crop_box(image, {'crop_box': tentative})
    index = {'left': 0, 'top': 1, 'right': 2, 'bottom': 3}[side]
    removed = box[index] if side in ('left', 'top') else (image.width if side == 'right' else image.height) - box[index]
    assert BAND * .90 <= removed <= BAND, 'Blank source bands should permit a meaningful trim without reaching paper'
    for unchanged in set(range(4)) - {index}:
        assert box[unchanged] == tentative[unchanged]
    _assert_visible_source_ink_retained(image, box, visible)


def test_native_safety_work_tiles_are_bounded_and_large_medians_use_uint8(monkeypatch):
    pixels = np.full((HEIGHT, WIDTH, 3), 190, np.uint8)
    pixels[:2048] = BACKGROUND
    image = Image.fromarray(pixels)
    original = cv2.medianBlur
    calls = []

    def bounded_median(array, kernel, *args, **kwargs):
        assert array.shape[0] * array.shape[1] <= 1_000_000, 'Native safety must not allocate a full-resolution work tile'
        if kernel > 5:
            assert array.dtype == np.uint8, 'Portable large-kernel OpenCV median input must be uint8'
        calls.append((array.shape, kernel))
        return original(array, kernel, *args, **kwargs)

    monkeypatch.setattr(cv2, 'medianBlur', bounded_median)
    box = native_safe_crop_box(image, {'crop_box': (0, 2048, WIDTH, HEIGHT)})
    assert box[0] == 0 and box[2:] == (WIDTH, HEIGHT)
    assert 2048 * .90 <= box[1] <= 2048
    assert len(calls) > 1 and any(kernel > 5 for _, kernel in calls)


def test_compressed_anonymous_blank_band_still_allows_useful_trim():
    # Mild native camera noise plus sparse compression speckles is not writing.
    # JPEG is generated locally from anonymous pixels, never customer content.
    width, height, wanted = 640, 960, 256
    rng = np.random.default_rng(717)
    pixels = np.full((height, width, 3), 190, np.uint8)
    noise = rng.normal(0, 1.8, (wanted, width, 3))
    pixels[:wanted] = np.clip(BACKGROUND + noise, 0, 255).astype(np.uint8)
    for x, y in ((97, 51), (309, 93), (482, 153)):
        pixels[y, x] = np.clip(BACKGROUND.astype(np.int16) + 13, 0, 255)
    encoded = BytesIO()
    Image.fromarray(pixels).save(encoded, format='JPEG', quality=73)
    encoded.seek(0)
    image = Image.open(encoded).convert('RGB')
    box = native_safe_crop_box(image, {'crop_box': (0, wanted, width, height)})
    assert box[1] >= wanted * .75, 'Harmless compressed blank-band noise must not disable useful auto-crop'
    assert box[0] == 0 and box[2:] == (width, height)


def _weak_long_stroke_mask(size, kind, stroke_width=2):
    mask = Image.new('L', size, 0)
    draw = ImageDraw.Draw(mask)
    if kind == 'review_signature':
        # Preserve the original independent safety review geometry verbatim.
        # Wider strokes can occupy a majority of a tiny median window, so the
        # guard must protect complete components across varied pen thicknesses.
        draw.line(((45, 133), (76, 108), (86, 148), (116, 111),
                   (142, 144), (163, 112), (195, 141), (219, 113),
                   (257, 142)), fill=255, width=stroke_width)
    elif kind == 'signature':
        # One connected, anonymous214x42 handwritten reference; every point is
        # procedural. Its width deliberately exceeds a tiny-glyph bounding box.
        draw.line(((147, 128), (184, 107), (190, 149), (221, 112),
                   (249, 147), (285, 112), (318, 142), (361, 124)),
                  fill=255, width=2)
    else:
        draw.line((147, 128, 361, 128), fill=255, width=1)
    return mask


@pytest.mark.parametrize('side', ['top', 'bottom', 'left', 'right'])
@pytest.mark.parametrize('kind,stroke_width', [
    ('signature', 2), ('underline', 1), ('review_signature', 3),
    ('review_signature', 5), ('review_signature', 7),
])
def test_long_faint_native_strokes_survive_all_tentative_band_orientations(side, kind, stroke_width):
    pixels = np.full((HEIGHT, WIDTH, 3), 190, np.uint8)
    pixels[:BAND] = (25, 30, 35)
    mask = _weak_long_stroke_mask((WIDTH, HEIGHT), kind, stroke_width)
    pixels[np.asarray(mask) > 0] = (33, 38, 43)
    image = Image.fromarray(pixels)
    rotation = {'top': None, 'left': Image.Transpose.ROTATE_90,
                'bottom': Image.Transpose.ROTATE_180,
                'right': Image.Transpose.ROTATE_270}[side]
    if rotation is not None:
        image, mask = image.transpose(rotation), mask.transpose(rotation)
    width, height = image.size
    tentative = {'top': (0, BAND, width, height),
                 'left': (BAND, 0, width, height),
                 'bottom': (0, 0, width, height - BAND),
                 'right': (0, 0, width - BAND, height)}[side]
    box = native_safe_crop_box(image, {'crop_box': tentative})
    _assert_visible_source_ink_retained(image, box, np.asarray(mask) > 0)


@pytest.mark.parametrize('kind,stroke_width', [
    ('signature', 2), ('underline', 1), ('review_signature', 3),
    ('review_signature', 5), ('review_signature', 7),
])
def test_real_partial_crop_preserves_long_faint_exterior_stroke(kind, stroke_width):
    from processors.document_scan import prepare_image
    from scripts.operations.partial_scan_fixtures import partial_document_fixture, source_roi

    fixture = partial_document_fixture(scale=2)
    # Source-camera masks independently establish that these are exterior
    # scene pixels, before adding a generic note to that otherwise blank band.
    assert not np.any(fixture.all_paper[:200])
    pixels = np.array(fixture.image)
    pixels[:200] = (25, 30, 35)
    mask = np.asarray(_weak_long_stroke_mask(fixture.image.size, kind, stroke_width)) > 0
    pixels[mask] = (33, 38, 43)
    original = Image.fromarray(pixels)
    output, flags = prepare_image(original, auto_crop=True, enhance_text=False)
    roi = source_roi(original, output)
    assert not flags['enhanced']
    _assert_visible_source_ink_retained(original, roi, mask)
