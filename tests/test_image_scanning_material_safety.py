"""A filled table is not a separate page when writing surrounds it.

These anonymous forms model shaded/colored printed regions on an already
framed photograph. The complete image contains required margin notes; a
material transition around its internal table must not discard those notes.
Recognized full-frame scans may receive the independent readability effect.
"""
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from processors.document_scan import prepare_image
from tests.test_image_scanning_safety import partial_page_with_table


def paper_with_filled_table(kind, *, colored_notes=False, rotation=None):
    """A generic page with a filled inner table and writing on all four sides."""
    image = Image.new('RGB', (600, 780), (238, 238, 235))
    font = ImageFont.truetype('processors/assets/fonts/NotoSans-Regular.ttf', 22)
    left, top, right, bottom = 70, 140, 530, 630
    if kind == 'warm':
        fill = Image.new('RGB', (right - left, bottom - top), (213, 194, 149))
    elif kind == 'neutral':
        fill = Image.new('RGB', (right - left, bottom - top), (156, 158, 160))
    elif kind == 'shaded':
        yy, xx = np.mgrid[:bottom - top, :right - left]
        tone = 166 + 18 * xx / (right - left) - 11 * yy / (bottom - top)
        fill = Image.fromarray(np.repeat(tone[:, :, None], 3, axis=2).astype(np.uint8))
    else:
        raise ValueError(kind)
    image.paste(fill, (left, top))
    draw = ImageDraw.Draw(image)
    draw.rectangle((left, top, right, bottom), outline=(45, 45, 45), width=2)
    for y in range(165, 610, 38):
        draw.text((90, y), 'Shaded table: sample entry 123', font=font, fill=(30, 30, 30))
    for x in (290, 420):
        draw.line((x, top, x, bottom), fill=(80, 80, 80), width=2)
    color = (15, 40, 135) if colored_notes else (25, 25, 25)
    draw.text((15, 8), 'Keep the top margin note', font=font, fill=color)
    draw.text((15, 736), 'Keep the bottom margin note', font=font, fill=color)
    draw.text((2, 365), 'L', font=font, fill=color)
    draw.text((576, 365), 'R', font=font, fill=color)
    return image if rotation is None else image.transpose(rotation)


@pytest.mark.parametrize('kind', ['warm', 'neutral', 'shaded'])
@pytest.mark.parametrize('rotation', [None, Image.Transpose.ROTATE_90],
                         ids=['portrait', 'quarter-turn'])
@pytest.mark.parametrize('enhance_text', [False, True], ids=['crop-only', 'defaults'])
def test_filled_internal_table_cannot_replace_page_or_remove_margin_writing(kind, rotation, enhance_text):
    source = paper_with_filled_table(kind, rotation=rotation)
    result, metadata = prepare_image(source, enhance_text=enhance_text)
    assert_full_frame_writing_preserved(source, result, metadata, enhance_text, rotation=rotation)


@pytest.mark.parametrize('kind', ['warm', 'shaded'])
@pytest.mark.parametrize('enhance_text', [False, True], ids=['crop-only', 'defaults'])
def test_colored_exterior_writing_also_disqualifies_an_internal_material_frame(kind, enhance_text):
    source = paper_with_filled_table(kind, colored_notes=True)
    result, metadata = prepare_image(source, enhance_text=enhance_text)
    assert_full_frame_writing_preserved(source, result, metadata, enhance_text)


SHORT_REFERENCES = [
    ('ZIP', (15, 8), (25, 25, 25)),
    ('ID27', (15, 8), (25, 25, 25)),
    ('ID', (15, 8), (25, 25, 25)),
    ('A', (2, 365), (25, 25, 25)),
    ('A', (15, 8), (25, 25, 25)),
    ('A', (15, 8), (15, 40, 135)),
]
SHORT_REFERENCE_IDS = ['three-letter-word', 'four-glyph-reference', 'two-letter-reference',
                       'single-side-glyph', 'single-corner-glyph', 'single-blue-corner-glyph']


def short_reference_page(reference, position, color):
    """A filled neutral block whose only margin content is one short reference."""
    source = paper_with_filled_table('neutral')
    draw = ImageDraw.Draw(source)
    # Leave exactly one known reference on the real page margin. A short code
    # or isolated handwritten initial is still content that must be retained.
    for box in ((0, 0, 599, 89), (0, 700, 599, 779),
                (0, 330, 49, 409), (550, 330, 599, 409)):
        draw.rectangle(box, fill=(238, 238, 235))
    font = ImageFont.truetype('processors/assets/fonts/NotoSans-Regular.ttf', 22)
    draw.text(position, reference, font=font, fill=color)
    return source


def _sharpened(image):
    """Camera-app sharpening leaves overshoot halos around every stroke and edge."""
    return image.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))


@pytest.mark.parametrize('reference,position,color', SHORT_REFERENCES, ids=SHORT_REFERENCE_IDS)
@pytest.mark.parametrize('enhance_text', [False, True], ids=['crop-only', 'defaults'])
def test_short_exterior_reference_or_single_glyph_cannot_be_discarded(reference, position, color, enhance_text):
    source = short_reference_page(reference, position, color)
    result, metadata = prepare_image(source, enhance_text=enhance_text)
    assert_short_reference_retained(source, result, metadata, position, enhance_text)


@pytest.mark.parametrize('reference,position,color', SHORT_REFERENCES, ids=SHORT_REFERENCE_IDS)
@pytest.mark.parametrize('enhance_text', [False, True], ids=['crop-only', 'defaults'])
def test_sharpening_halos_do_not_make_a_short_reference_discardable(reference, position, color, enhance_text):
    # Sharpening rings the block outline and the reference with overshoot
    # halos; neither the halo nor the brighter ring is a paper edge.
    source = _sharpened(short_reference_page(reference, position, color))
    result, metadata = prepare_image(source, enhance_text=enhance_text)
    assert_short_reference_retained(source, result, metadata, position, enhance_text)


@pytest.mark.parametrize('enhance_text', [False, True], ids=['crop-only', 'defaults'])
def test_sharpened_clipped_page_with_thick_table_keeps_heading_and_footer(enhance_text):
    source = _sharpened(partial_page_with_table(18, shaded=True))
    result, metadata = prepare_image(source, enhance_text=enhance_text)
    assert metadata['cropped'] is False
    assert result.size == source.size
    if not enhance_text or not metadata['enhanced']:
        assert result.tobytes() == source.tobytes()
    before = np.asarray(source).astype(np.float32).mean(axis=2) < 120
    after = np.asarray(result).astype(np.float32).mean(axis=2) < 120
    heading, footer = (slice(35, 95), slice(85, 460)), (slice(820, 875), slice(85, 320))
    for region in (heading, footer):
        ink = before[region]
        assert int(ink.sum()) > 40, 'The fixture prints writing outside its table'
        assert int((ink & after[region]).sum()) >= int(ink.sum()) * .90, 'Writing outside the table remains'


def assert_short_reference_retained(source, result, metadata, position, enhance_text):
    assert metadata['cropped'] is False
    assert result.size == source.size
    if not enhance_text or not metadata['enhanced']:
        assert result.tobytes() == source.tobytes()
    x, y = position
    region = (slice(y, y + 40), slice(x, x + 90))
    before = np.asarray(source).astype(np.float32).mean(axis=2)[region] < 120
    after = np.asarray(result).astype(np.float32).mean(axis=2)[region] < 120
    assert int(before.sum()) > 40
    assert int((before & after).sum()) >= int(before.sum()) * .90, 'The entire short reference remains'


def assert_full_frame_writing_preserved(source, result, metadata, enhance_text, *, rotation=None):
    assert metadata['cropped'] is False
    assert result.size == source.size, 'All four actual page margins remain in the output'
    if not enhance_text:
        assert metadata['enhanced'] is False
        assert result.tobytes() == source.tobytes(), 'Crop-only must retain every original source pixel'
        return
    if not metadata['enhanced']:
        assert result.tobytes() == source.tobytes(), 'An uncertain photograph remains unchanged'
    if rotation is not None:
        source = source.transpose(Image.Transpose.ROTATE_270)
        result = result.transpose(Image.Transpose.ROTATE_270)
    before = np.asarray(source).astype(np.float32).mean(axis=2) < 120
    after = np.asarray(result).astype(np.float32).mean(axis=2) < 120
    regions = ((slice(0, 90), slice(None)), (slice(700, None), slice(None)),
               (slice(330, 410), slice(0, 50)), (slice(330, 410), slice(550, None)))
    for region in regions:
        ink = before[region]
        assert int(ink.sum()) > 40, 'The anonymous fixture contains real writing in this margin'
        assert int((ink & after[region]).sum()) >= int(ink.sum()) * .90, 'Margin writing remains readable'
