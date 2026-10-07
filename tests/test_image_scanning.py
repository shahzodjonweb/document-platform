"""Document scanning acceptance: real transforms, images, PDFs and sandbox.

These fixtures deliberately include photographs and ambiguous pages. Default
document cleanup must preserve them when a safe paper boundary is unavailable.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader

from processors import ProcessorError, execute, normalize_parameters
from processors.document_scan import prepare_image
from processors.sandbox import execute_sandbox


def _font(size=21):
    font = Path(__file__).resolve().parents[1] / 'processors/assets/fonts/NotoSans-Regular.ttf'
    return ImageFont.truetype(str(font), size)


def _paper(*, shaded=False):
    width, height = 440, 640
    if shaded:
        # A broad, gradual lighting change, not an artificial binary page mask.
        lighting = np.broadcast_to(np.linspace(184, 247, width, dtype=np.uint8), (height, width))
        image = Image.fromarray(np.repeat(lighting[:, :, None], 3, axis=2), 'RGB')
    else:
        image = Image.new('RGB', (width, height), (246, 246, 244))
    draw = ImageDraw.Draw(image)
    draw.text((28, 36), 'Invoice / Hisob / Счёт', font=_font(24), fill=(30, 30, 30))
    for number, top in enumerate(range(100, 465, 42), 1):
        draw.text((30, top), f'{number}. Original text and totals 123', font=_font(), fill=(40, 40, 40))
    draw.line([(38, 550), (95, 516), (145, 548), (208, 520), (276, 545)], fill=(20, 55, 145), width=5)
    draw.text((40, 580), 'Blue handwritten note', font=_font(20), fill=(20, 55, 145))
    # Colored marks near every corner detect accidental inward crops.
    for x, y in ((14, 14), (width - 26, 14), (14, height - 26), (width - 26, height - 26)):
        draw.rectangle((x, y, x + 11, y + 11), fill=(155, 25, 25))
    return image


def _project(paper, corners, *, size=(720, 900), background=(46, 64, 54)):
    """Photograph a paper using an actual projective image transform."""
    rgb = np.asarray(paper)
    source = np.array([[0, 0], [paper.width - 1, 0],
                       [paper.width - 1, paper.height - 1], [0, paper.height - 1]], np.float32)
    matrix = cv2.getPerspectiveTransform(source, np.asarray(corners, np.float32))
    warped = cv2.warpPerspective(rgb, matrix, size, flags=cv2.INTER_LINEAR)
    mask = cv2.warpPerspective(np.full(rgb.shape[:2], 255, np.uint8), matrix, size,
                               flags=cv2.INTER_NEAREST)
    result = np.empty((size[1], size[0], 3), np.uint8)
    result[:] = background
    result[mask > 0] = warped[mask > 0]
    return Image.fromarray(result, 'RGB')


def perspective_paper(*, shaded=False):
    return _project(_paper(shaded=shaded), [(150, 100), (595, 145), (615, 820), (85, 740)])


def ordinary_photo():
    image = Image.new('RGB', (720, 900), (75, 130, 183))
    draw = ImageDraw.Draw(image)
    draw.ellipse((-130, 430, 620, 1180), fill=(48, 99, 56))
    draw.ellipse((330, 300, 1190, 1190), fill=(70, 122, 65))
    draw.ellipse((160, 110, 430, 180), fill=(195, 209, 215))
    draw.line((0, 680, 720, 730), fill=(109, 74, 49), width=21)
    return image


def incomplete_paper():
    return _project(_paper(), [(-35, 80), (610, 110), (620, 865), (-25, 885)])


def two_papers():
    size = (900, 900)
    background = Image.new('RGB', size, (50, 67, 55))
    array = np.array(background)
    for corners in ([(55, 80), (408, 100), (396, 800), (45, 780)],
                    [(494, 110), (848, 80), (862, 780), (508, 804)]):
        projected = np.asarray(_project(_paper(), corners, size=size))
        foreground = np.any(projected != np.array((46, 64, 54)), axis=2)
        array[foreground] = projected[foreground]
    return Image.fromarray(array, 'RGB')


def full_frame_scan():
    image = Image.new('RGB', (700, 950), (247, 247, 244))
    draw = ImageDraw.Draw(image)
    draw.text((35, 40), 'Whole page: keep this heading', font=_font(28), fill=(30, 30, 30))
    draw.text((35, 110), 'Text above the table', font=_font(), fill=(40, 40, 40))
    draw.rectangle((100, 210, 600, 735), outline=(25, 25, 25), width=4)
    for y in range(285, 735, 75):
        draw.line((100, y, 600, y), fill=(25, 25, 25), width=3)
    for x in (267, 434):
        draw.line((x, 210, x, 735), fill=(25, 25, 25), width=3)
    draw.text((35, 825), 'Keep this footer too', font=_font(25), fill=(20, 55, 145))
    return image


def _blue_pixels(image):
    pixels = np.asarray(image).astype(np.int16)
    return (pixels[:, :, 2] > pixels[:, :, 0] + 35) & (pixels[:, :, 2] > pixels[:, :, 1] + 25)


def _embedded_image(result, page=0):
    reader = PdfReader(result['artifacts'][0]['path'])
    image = reader.pages[page].images[0].image.convert('RGB')
    image.load()
    return image


def test_defaults_enable_both_independent_document_options():
    normalized = normalize_parameters('pdf.images_to_pdf', {})
    assert normalized['paper_size'] == 'fit'
    assert normalized['orientation'] == 'auto'
    assert normalized['margin'] == 0
    assert normalized['auto_crop'] is True
    assert normalized['enhance_text'] is True
    assert normalize_parameters('pdf.images_to_pdf', {'auto_crop': False})['enhance_text'] is True
    assert normalize_parameters('pdf.images_to_pdf', {'enhance_text': False})['auto_crop'] is True


@pytest.mark.parametrize('parameters', [{}, {'auto_crop': False, 'enhance_text': False}])
def test_default_fitted_pdf_has_no_added_border_and_keeps_sensible_print_size(tmp_path, parameters):
    import pypdfium2 as pdfium
    from contextlib import closing
    source = tmp_path / 'photo.png'
    color = (47, 63, 81)
    Image.new('RGB', (500, 900), color).save(source)
    result = execute_sandbox('pdf.images_to_pdf', [source], parameters, tmp_path / 'out')
    page = PdfReader(result['artifacts'][0]['path']).pages[0]
    width, height = float(page.mediabox.width), float(page.mediabox.height)
    assert height == pytest.approx(842, abs=.001)
    assert width / height == pytest.approx(500 / 900, abs=.00001)
    assert page.images[0].image.size == (500, 900), 'Fit changes print dimensions, not image resolution'
    with pdfium.PdfDocument(result['artifacts'][0]['path']) as document, closing(document[0]) as rendered_page:
        bitmap = rendered_page.render(scale=.5)
        try:
            rendered = bitmap.to_pil().convert('RGB')
            for position in ((2, 2), (rendered.width - 3, 2), (2, rendered.height - 3),
                             (rendered.width - 3, rendered.height - 3)):
                assert rendered.getpixel(position) == color, 'No white canvas should surround the image'
        finally:
            bitmap.close()


@pytest.mark.parametrize('parameters,expected_size', [
    ({'paper_size': 'A4', 'orientation': 'auto', 'margin': 24}, (595.275590551, 841.88976378)),
    ({'paper_size': 'Letter', 'orientation': 'landscape', 'margin': 12}, (792, 612)),
    ({'paper_size': 'original', 'orientation': 'auto', 'margin': 18}, (536, 936)),
    ({'paper_size': 'fit', 'orientation': 'auto', 'margin': 12}, (500 / 900 * 842 + 24, 866)),
    ({'paper_size': 'fit', 'orientation': 'landscape', 'margin': 0}, (842, 500 / 900 * 842)),
])
def test_fitted_default_preserves_explicit_and_legacy_layouts(tmp_path, parameters, expected_size):
    source = tmp_path / 'photo.png'
    original = Image.new('RGB', (500, 900), (47, 63, 81))
    original.save(source)
    result = execute('pdf.images_to_pdf', [source], parameters, tmp_path / 'out')
    page = PdfReader(result['artifacts'][0]['path']).pages[0]
    assert (float(page.mediabox.width), float(page.mediabox.height)) == pytest.approx(expected_size, abs=.001)
    assert np.array_equal(np.asarray(page.images[0].image.convert('RGB')), np.asarray(original))
    normalized = normalize_parameters('pdf.images_to_pdf', parameters)
    assert all(normalized[key] == value for key, value in parameters.items())


@pytest.mark.parametrize('field', ['auto_crop', 'enhance_text'])
@pytest.mark.parametrize('value', [None, 0, 1, 'true', 'false', [], {}])
def test_document_options_reject_non_boolean_values(field, value):
    with pytest.raises(ProcessorError) as error:
        normalize_parameters('pdf.images_to_pdf', {field: value})
    assert error.value.code == 'invalid_parameters'


def test_perspective_document_is_rectangular_and_preserves_writing():
    source = perspective_paper()
    result, metadata = prepare_image(source, enhance_text=False)
    assert metadata['document_detected'] is True
    assert metadata['cropped'] is True
    assert metadata['enhanced'] is False
    assert result.mode == 'RGB'
    assert result.width * result.height < source.width * source.height * 0.85
    assert 1.1 < result.height / result.width < 1.8
    pixels = np.asarray(result).astype(np.int16)
    # The original dark tabletop occupies nearly half of the source image.
    dark_background = (pixels[:, :, 0] < 85) & (pixels[:, :, 1] > pixels[:, :, 0] + 10)
    assert dark_background.mean() < 0.035
    assert _blue_pixels(result).sum() > 600
    red = (pixels[:, :, 0] > pixels[:, :, 1] + 65) & (pixels[:, :, 0] > pixels[:, :, 2] + 65)
    # All four corner marks should survive, including the extreme bottom ones.
    assert all(red[y0:y1, x0:x1].sum() > 12 for x0, y0, x1, y1 in (
        (0, 0, result.width // 4, result.height // 4),
        (3 * result.width // 4, 0, result.width, result.height // 4),
        (0, 3 * result.height // 4, result.width // 4, result.height),
        (3 * result.width // 4, 3 * result.height // 4, result.width, result.height)))


def test_readability_effect_reduces_shadow_and_keeps_colored_ink():
    source = perspective_paper(shaded=True)
    baseline, baseline_metadata = prepare_image(source, enhance_text=False)
    enhanced, metadata = prepare_image(source)
    assert baseline_metadata['cropped'] and metadata['cropped']
    assert metadata['enhanced'] is True
    assert enhanced.size == baseline.size
    before, after = np.asarray(baseline), np.asarray(enhanced)
    paper = (before.min(axis=2) > 150) & (before.max(axis=2) - before.min(axis=2) < 15)
    assert np.median(after[paper]) > np.median(before[paper]) + 4
    assert np.std(after[paper].mean(axis=1)) < np.std(before[paper].mean(axis=1))
    assert _blue_pixels(enhanced).sum() > _blue_pixels(baseline).sum() * 0.7


@pytest.mark.parametrize('factory', [ordinary_photo, two_papers])
def test_ambiguous_document_is_not_cropped(factory):
    source = factory()
    result, metadata = prepare_image(source)
    assert metadata['cropped'] is False
    assert result.size == source.size
    if factory is ordinary_photo:
        assert metadata['enhanced'] is False
        assert result.tobytes() == source.tobytes()


def test_clipped_page_can_trim_only_empty_source_bands_and_keeps_visible_writing():
    from scripts.operations.partial_scan_fixtures import source_roi
    source = incomplete_paper()
    crop, metadata = prepare_image(source, enhance_text=False)
    left, top, right, bottom = source_roi(source, crop, white_canvas=True)
    # This anonymous camera has an exactly known background. Every pixel of
    # visible paper, text, signature and edge marker must remain in the crop.
    written_page = np.any(np.asarray(source) != (46, 64, 54), axis=2)
    retained = np.zeros(written_page.shape, bool)
    retained[top:bottom, left:right] = True
    assert not np.any(written_page & ~retained)
    region = written_page[top:bottom, left:right]
    assert np.array_equal(np.asarray(crop)[region],
                          np.asarray(source)[top:bottom, left:right][region])
    assert metadata['enhanced'] is False
    result, _ = prepare_image(source)
    assert result.size == crop.size
    assert _blue_pixels(result).sum() >= _blue_pixels(crop).sum() * .7


@pytest.mark.parametrize('color', ['red', 'blue', 'white'])
def test_solid_images_remain_unchanged_under_defaults(color):
    source = Image.new('RGB', (300, 150), color)
    result, metadata = prepare_image(source)
    assert metadata['cropped'] is False
    assert metadata['enhanced'] is False
    assert result.size == source.size
    assert result.tobytes() == source.tobytes()


def test_full_frame_scan_does_not_crop_to_internal_table():
    source = full_frame_scan()
    result, metadata = prepare_image(source, enhance_text=False)
    assert metadata['cropped'] is False
    assert result.size == source.size
    assert result.tobytes() == source.tobytes()


def test_effect_can_be_enabled_without_cropping_document():
    source = perspective_paper(shaded=True)
    result, metadata = prepare_image(source, auto_crop=False)
    assert metadata['document_detected'] is True
    assert metadata['cropped'] is False
    assert metadata['enhanced'] is True
    assert result.size == source.size
    assert result.tobytes() != source.tobytes()
    assert result.getpixel((40, 40)) == source.getpixel((40, 40))


def test_both_switches_off_preserve_the_image_exactly():
    source = perspective_paper(shaded=True)
    result, metadata = prepare_image(source, auto_crop=False, enhance_text=False)
    assert metadata['cropped'] is False
    assert metadata['enhanced'] is False
    assert result.size == source.size
    assert result.tobytes() == source.tobytes()


def test_pdf_honors_exif_before_document_analysis_and_original_sizing(tmp_path):
    upright = full_frame_scan()
    stored = upright.transpose(Image.Transpose.ROTATE_90)
    exif = Image.Exif()
    exif[274] = 6
    source = tmp_path / 'rotated.jpg'
    stored.save(source, exif=exif, quality=98)
    result = execute('pdf.images_to_pdf', [source], {
        'paper_size': 'original', 'margin': 0, 'auto_crop': False, 'enhance_text': False}, tmp_path / 'out')
    embedded = _embedded_image(result)
    assert embedded.size == upright.size
    page = PdfReader(result['artifacts'][0]['path']).pages[0]
    assert (float(page.mediabox.width), float(page.mediabox.height)) == upright.size
    assert np.mean(np.abs(np.asarray(embedded).astype(np.int16) - np.asarray(upright))) < 2.5


def test_default_scan_uses_exif_upright_document_orientation(tmp_path):
    upright = perspective_paper()
    stored = upright.transpose(Image.Transpose.ROTATE_90)
    exif = Image.Exif()
    exif[274] = 6
    source = tmp_path / 'rotated-document.jpg'
    stored.save(source, exif=exif, quality=98)
    result = execute('pdf.images_to_pdf', [source], {}, tmp_path / 'out')
    embedded = _embedded_image(result)
    assert embedded.height > embedded.width
    assert result['metadata']['image_processing']['cropped_pages'] == 1
    assert result['metadata']['image_processing']['enhanced_pages'] == 1
    assert _blue_pixels(embedded).sum() > 600


def test_pdf_flattens_transparency_to_white_before_scanning(tmp_path):
    source = tmp_path / 'transparent.png'
    image = Image.new('RGBA', (360, 240), (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((110, 70, 250, 170), fill=(20, 55, 145, 255))
    image.save(source)
    result = execute('pdf.images_to_pdf', [source], {'paper_size': 'original'}, tmp_path / 'out')
    embedded = _embedded_image(result)
    assert embedded.getpixel((5, 5)) == (255, 255, 255)
    assert embedded.getpixel((180, 120)) == (20, 55, 145)
    assert embedded.size == image.size


def test_real_sandbox_default_cleanup_preserves_page_order_and_reports_safe_metadata(tmp_path):
    paper, photo = tmp_path / 'paper.png', tmp_path / 'photo.png'
    perspective_paper(shaded=True).save(paper)
    ordinary_photo().save(photo)
    result = execute_sandbox('pdf.images_to_pdf', [paper, photo], {}, tmp_path / 'out')
    assert result['artifacts'][0]['page_count'] == 2
    assert result['actual_page_units'] == 2
    first, second = _embedded_image(result), _embedded_image(result, 1)
    assert first.width * first.height < 720 * 900 * 0.85
    assert second.size == (720, 900)
    assert second.getpixel((40, 40)) == ordinary_photo().getpixel((40, 40))
    metadata = result['metadata']['image_processing']
    assert metadata['cropped_pages'] == 1
    assert metadata['enhanced_pages'] == 1
    assert metadata['document_pages'] == 1
    assert len(metadata['pages']) == 2
    for page in metadata['pages']:
        assert set(page) == {'document_detected', 'cropped', 'enhanced'}
        assert all(type(value) is bool for value in page.values())
    assert metadata['pages'][0]['cropped'] is True
    assert metadata['pages'][1]['cropped'] is False


def test_large_document_uses_bounded_warp_and_completes_in_real_sandbox(tmp_path):
    # 33.8 MP is below the established 40 MP input cap. Its warped page would
    # exceed the scan output cap unless the processor bounds the destination.
    source = tmp_path / 'large-paper.jpg'
    picture = perspective_paper(shaded=True).resize((5200, 6500), Image.Resampling.LANCZOS)
    picture.save(source, quality=93)
    picture.close()
    result = execute_sandbox('pdf.images_to_pdf', [source], {}, tmp_path / 'out')
    embedded = _embedded_image(result)
    assert embedded.width * embedded.height <= 16_010_000
    assert embedded.width > 2500 and embedded.height > 3500
    assert result['metadata']['image_processing']['cropped_pages'] == 1
    assert result['metadata']['image_processing']['enhanced_pages'] == 1
    assert _blue_pixels(embedded).sum() > 10_000
