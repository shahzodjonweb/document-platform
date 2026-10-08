"""Independent safety fixtures: automatic cropping must not discard writing."""
import numpy as np
import pytest
from PIL import Image, ImageDraw

from processors.document_scan import prepare_image
from tests.test_image_scanning import _blue_pixels, _font, _paper, _project, full_frame_scan


def partial_page_with_table(border, *, shaded=False):
    image = full_frame_scan()
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 210, 600, 735), outline=(25, 25, 25), width=border)
    if shaded:
        pixels = np.array(image)
        lighting = np.linspace(.77, 1, image.width, dtype=np.float32)
        pixels = np.clip(pixels.astype(np.float32) * lighting[None, :, None], 0, 255).astype(np.uint8)
        image = Image.fromarray(pixels)
        draw = ImageDraw.Draw(image)
    # The paper continues past the right edge of the photograph. Its whole
    # boundary cannot be known. The heading and footer remain outside the table.
    draw.rectangle((0, 0, 85, image.height), fill=(75, 80, 65))
    return image


@pytest.mark.parametrize('border', [8, 12, 18])
@pytest.mark.parametrize('shaded', [False, True])
def test_partial_paper_with_thick_inner_table_keeps_heading_and_footer(border, shaded):
    source = partial_page_with_table(border, shaded=shaded)
    result, metadata = prepare_image(source, enhance_text=False)
    assert metadata['cropped'] is False
    assert result.size == source.size
    assert result.tobytes() == source.tobytes()


def unequal_pages(small_corners):
    size = (1100, 1000)
    background = (46, 64, 54)
    pixels = np.empty((size[1], size[0], 3), np.uint8)
    pixels[:] = background
    for corners in ([(55, 65), (610, 85), (600, 945), (35, 920)], small_corners):
        projected = np.asarray(_project(_paper(), corners, size=size, background=background))
        foreground = np.any(projected != np.asarray(background), axis=2)
        pixels[foreground] = projected[foreground]
    return Image.fromarray(pixels)


@pytest.mark.parametrize('small_corners', [
    [(750, 350), (1000, 350), (1010, 730), (750, 760)],
    [(710, 180), (1040, 190), (1040, 720), (705, 720)],
])
def test_smaller_second_page_is_kept_when_a_large_page_is_detected(small_corners):
    source = unequal_pages(small_corners)
    result, metadata = prepare_image(source, enhance_text=False)
    assert metadata['cropped'] is False
    assert result.size == source.size
    assert result.tobytes() == source.tobytes()


def refrigerator_photo():
    image = Image.new('RGB', (720, 900), (98, 87, 80))
    draw = ImageDraw.Draw(image)
    draw.rectangle((190, 150, 585, 800), fill=(240, 241, 238), outline=(66, 70, 64), width=4)
    draw.rectangle((225, 280, 239, 600), fill=(67, 69, 62))
    draw.rectangle((0, 795, 720, 900), fill=(89, 65, 39))
    return image


def test_white_rectangular_appliance_does_not_count_as_written_paper():
    source = refrigerator_photo()
    result, metadata = prepare_image(source)
    assert metadata['document_detected'] is False
    assert metadata['cropped'] is False
    assert metadata['enhanced'] is True, 'The effect runs on every page'
    assert result.size == source.size
    crop_only, flags = prepare_image(source, enhance_text=False)
    assert flags == {'document_detected': False, 'cropped': False, 'enhanced': False}
    assert crop_only.tobytes() == source.tobytes()


def test_page_written_only_in_blue_is_detected_cropped_and_preserved():
    paper = Image.new('RGB', (440, 640), (246, 246, 244))
    draw = ImageDraw.Draw(paper)
    draw.text((28, 40), 'Notes / Yozuvlar / Записи', font=_font(23), fill=(20, 55, 145))
    for top in range(110, 540, 55):
        draw.text((32, top), 'Blue ink: totals 12345', font=_font(23), fill=(20, 55, 145))
    source = _project(paper, [(150, 100), (595, 145), (615, 820), (85, 740)])
    result, metadata = prepare_image(source)
    assert metadata['document_detected'] is True
    assert metadata['cropped'] is True
    assert metadata['enhanced'] is True
    assert result.width * result.height < source.width * source.height * .85
    assert _blue_pixels(result).sum() > 500
