"""Dense writing must not admit mechanical patterns or discard a lone margin.

All scenes are generic, procedural fixtures. The source paper, margin notes and
perforated speaker panel are known before detection; no customer pixels or
wording are stored in the repository.
"""
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from processors.document_scan import prepare_image
from tests.test_image_scanning_occluded import _generic_form, _writing_metrics


def perforated_panel(*, full_frame=False):
    """A matte speaker/vent grille contains many circles, with no written text."""
    image = Image.new('RGB', (720, 900), (24, 28, 32))
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 80, 620, 820), fill=(184, 187, 189), outline=(75, 77, 79), width=3)
    for y in range(122, 785, 33):
        for x in range(145, 585, 43):
            draw.ellipse((x - 13, y - 13, x + 13, y + 13), fill=(16, 17, 18))
    image = image.filter(ImageFilter.GaussianBlur(.5))
    return image.crop((100, 80, 621, 821)) if full_frame else image


@pytest.mark.parametrize('full_frame', [False, True], ids=['whole-object-photo', 'grille-closeup'])
@pytest.mark.parametrize('enhance_text', [False, True], ids=['crop-only', 'defaults'])
def test_perforated_panel_is_not_mistaken_for_dense_written_paper(full_frame, enhance_text):
    source = perforated_panel(full_frame=full_frame)
    result, metadata = prepare_image(source, enhance_text=enhance_text)
    assert metadata == {'document_detected': False, 'cropped': False, 'enhanced': False}
    assert result.size == source.size and result.tobytes() == source.tobytes()


@pytest.mark.parametrize('exposure', [0, -22], ids=['normal', 'shaded'])
@pytest.mark.parametrize('rotation', [None, Image.Transpose.ROTATE_90], ids=['portrait', 'quarter-turn'])
@pytest.mark.parametrize('enhance_text', [False, True], ids=['crop-only', 'defaults'])
def test_dense_full_frame_form_keeps_every_margin_and_colored_mark(exposure, rotation, enhance_text):
    # A one-pixel spread models a bold/carbon-copy print. It increases printed
    # coverage without replacing actual writing with artificial solid boxes.
    source = _generic_form(exposure=exposure).filter(ImageFilter.MinFilter(3))
    if rotation is not None:
        source = source.transpose(rotation)
    result, metadata = prepare_image(source, enhance_text=enhance_text)
    assert metadata == {'document_detected': True, 'cropped': False, 'enhanced': enhance_text}
    assert result.size == source.size
    if not enhance_text:
        assert result.tobytes() == source.tobytes()
    if rotation is not None:
        source = source.transpose(Image.Transpose.ROTATE_270)
        result = result.transpose(Image.Transpose.ROTATE_270)
    before, after = _writing_metrics(source), _writing_metrics(result)
    assert all(new >= old * .75 for old, new in zip(before['corner_counts'], after['corner_counts']))
    assert after['signature_pixels'] >= before['signature_pixels'] * .75
    # No rectification means the same pixel coordinates carry the small notes;
    # cleanup must retain their dark/colored strokes at all four actual edges.
    before_ink = np.asarray(source).astype(np.float32).mean(axis=2) < 120
    after_ink = np.asarray(result).astype(np.float32).mean(axis=2) < 120
    margin = np.ones(before_ink.shape, bool)
    margin[20:-20, 20:-20] = False
    old_ink = before_ink & margin
    assert int(old_ink.sum()) > 100
    assert int((old_ink & after_ink).sum()) >= int(old_ink.sum()) * .90


def one_sided_matte_parent(reference):
    """A filled printed block has narrow borders and one wide annotation gutter."""
    image = Image.new('RGB', (600, 780), (238, 238, 235))
    draw = ImageDraw.Draw(image)
    draw.rectangle((110, 6, 593, 773), fill=(156, 158, 160), outline=(42, 42, 42), width=2)
    font = ImageFont.truetype('processors/assets/fonts/NotoSans-Regular.ttf', 20)
    for y in range(30, 750, 34):
        draw.text((132, y), 'Sample table entry: retain the whole form', font=font, fill=(27, 27, 27))
    for y in (111, 349, 587):
        draw.rectangle((112, y, 591, y + 16), fill=(36, 36, 36))
    if reference == 'handwritten':
        # Generic disconnected pen initials, never a real person's signature.
        draw.line(((25, 371), (36, 338), (48, 371)), fill=(15, 40, 135), width=3)
        draw.line(((29, 358), (43, 358)), fill=(15, 40, 135), width=3)
        draw.line(((62, 371), (62, 340), (83, 340)), fill=(15, 40, 135), width=3)
    else:
        draw.text((15, 345), reference, font=font, fill=(25, 25, 25))
    return image


@pytest.mark.parametrize('reference', ['ZIP', 'ID', 'handwritten'])
@pytest.mark.parametrize('rotation', [None, Image.Transpose.ROTATE_90], ids=['portrait', 'quarter-turn'])
@pytest.mark.parametrize('enhance_text', [False, True], ids=['crop-only', 'defaults'])
def test_one_sided_parent_margin_is_not_discarded_for_its_filled_printed_block(reference, rotation, enhance_text):
    source = one_sided_matte_parent(reference)
    if rotation is not None:
        source = source.transpose(rotation)
    result, metadata = prepare_image(source, enhance_text=enhance_text)
    assert metadata['cropped'] is False
    assert result.size == source.size
    if not enhance_text or not metadata['enhanced']:
        assert result.tobytes() == source.tobytes()
    if rotation is not None:
        source = source.transpose(Image.Transpose.ROTATE_270)
        result = result.transpose(Image.Transpose.ROTATE_270)
    before = np.asarray(source).astype(np.float32).mean(axis=2)[320:390, :100] < 120
    after = np.asarray(result).astype(np.float32).mean(axis=2)[320:390, :100] < 120
    assert int(before.sum()) > 40
    assert int((before & after).sum()) >= int(before.sum()) * .90
