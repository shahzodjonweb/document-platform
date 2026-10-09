"""Document scanning acceptance: real transforms, images, PDFs and sandbox.

These fixtures deliberately include photographs and ambiguous pages. Default
document cleanup must preserve them when a safe paper boundary is unavailable.
"""
from __future__ import annotations

import io
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


def one_line_note(text):
    """A mostly blank sheet whose only writing is one short line."""
    paper = Image.new('RGB', (440, 640), (246, 246, 244))
    ImageDraw.Draw(paper).text((40, 300), text, font=_font(24), fill=(30, 30, 30))
    return _project(paper, [(150, 100), (595, 145), (615, 820), (85, 740)])


@pytest.mark.parametrize('text,is_document', [
    ('Total 42.00 paid', True),  # about a dozen glyphs in one aligned line
    ('ABCDEFG', False),          # seven hollow glyphs: one short of the floor
    ('O C U N', False),          # four marks are a logo or a label, not writing
], ids=['one-line-note', 'seven-glyphs', 'four-glyphs'])
def test_one_written_line_is_evidence_of_a_page_but_a_few_marks_are_not(text, is_document):
    # The written-evidence floor is eight glyph-like marks in one aligned row:
    # a receipt total is a document, a vent or a panel label is not.
    source = one_line_note(text)
    result, metadata = prepare_image(source, enhance_text=False)
    assert metadata == {'document_detected': is_document, 'cropped': is_document, 'enhanced': False}
    if is_document:
        assert result.width * result.height < source.width * source.height * .85
        assert 1.1 < result.height / result.width < 1.8
    else:
        assert result.size == source.size and result.tobytes() == source.tobytes()


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
        assert metadata['enhanced'] is True, 'The effect runs on every page'
        crop_only, flags = prepare_image(source, enhance_text=False)
        assert flags == {'document_detected': False, 'cropped': False, 'enhanced': False}
        assert crop_only.tobytes() == source.tobytes()


def test_uncertain_partial_pose_fallback_keeps_every_visible_source_pixel(monkeypatch):
    from scripts.operations.partial_scan_fixtures import source_roi
    from processors import partial_scan_rectification
    monkeypatch.setattr(partial_scan_rectification, 'rectify_partial', lambda image, details: None)
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
    assert metadata['enhanced'] is True, 'The effect runs on every page'
    assert result.size == source.size
    assert result.tobytes() == source.tobytes(), 'A flat colour has no shadow to lift'


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
    # The cleaned sheet is rendered towards A4 at 200 dpi (at most 3x), so its
    # pixel count no longer shows the crop; its density and its own sheet
    # shape, rather than the photo's frame, do.
    assert 1600 <= max(first.size) <= 2339
    assert abs(first.height / first.width - 900 / 720) > .05
    assert second.size == (720, 900)
    metadata = result['metadata']['image_processing']
    assert metadata['cropped_pages'] == 1
    assert metadata['enhanced_pages'] == 2, 'The effect reaches the photo page too'
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


def test_untouched_jpeg_upload_is_embedded_as_its_own_pixels_without_metadata(tmp_path):
    rng = np.random.default_rng(7)
    photo = Image.fromarray(rng.integers(0, 255, (300, 400, 3), dtype=np.uint8))
    source = tmp_path / 'photo.jpg'
    photo.save(source, quality=85, comment=b'CAMERA SERIAL 12345', dpi=(300, 300))
    result = execute('pdf.images_to_pdf', [source], {'auto_crop': False, 'enhance_text': False}, tmp_path / 'out')
    pdf = Path(result['artifacts'][0]['path']).read_bytes()
    assert b'CAMERA SERIAL' not in pdf, 'Upload comments never reach the PDF'
    assert result['metadata']['image_processing']['layouts'][0]['image_encoding'] == 'jpeg'
    assert result['artifacts'][0]['size_bytes'] < source.stat().st_size * 1.1, 'Grainy photos are not inflated'
    # Compare the embedded DCT stream itself: pypdf's convenience decoder
    # applies its own colour handling, Pillow decodes both sides the same way.
    stream = PdfReader(result['artifacts'][0]['path']).pages[0].images[0].indirect_reference.get_object().get_data()
    with Image.open(source) as original, Image.open(io.BytesIO(stream)) as embedded:
        assert embedded.convert('RGB').tobytes() == original.convert('RGB').tobytes(), 'Both off keeps every pixel'
    assert b'\xff\xfe' not in stream[:4096], 'No COM segment survives in the stream header'


def test_grainy_processed_page_is_a_metadata_free_jpeg_stream(tmp_path):
    rng = np.random.default_rng(11)
    photo = Image.fromarray(rng.integers(40, 220, (300, 400, 3), dtype=np.uint8))
    source = tmp_path / 'photo.jpg'
    photo.save(source, quality=85, comment=b'CAMERA SERIAL 12345')
    result = execute('pdf.images_to_pdf', [source], {}, tmp_path / 'out')
    assert b'CAMERA SERIAL' not in Path(result['artifacts'][0]['path']).read_bytes()
    assert result['metadata']['image_processing']['layouts'][0]['image_encoding'] == 'jpeg'
    assert _embedded_image(result).size == photo.size


def test_scanner_jpeg_of_a_high_entropy_page_falls_back_from_optimized_tables(tmp_path):
    # Pillow gives an optimized JPEG save a buffer of one byte per pixel; a
    # page of near-random content needs more and must still encode.
    rng = np.random.default_rng(2)
    source = tmp_path / 'noise.png'
    Image.fromarray(rng.integers(0, 256, (1500, 1500, 3), dtype=np.uint8)).save(source)
    result = execute('pdf.images_to_pdf', [source], {}, tmp_path / 'out')
    assert result['metadata']['image_processing']['layouts'][0]['image_encoding'] == 'jpeg'
    assert _embedded_image(result).size == (1500, 1500)


def test_original_paper_holds_an_oversize_panorama_to_the_page_limit(tmp_path):
    source = tmp_path / 'wide.png'
    Image.new('RGB', (15000, 300), (200, 200, 200)).save(source)
    result = execute('pdf.images_to_pdf', [source], {
        'paper_size': 'original', 'margin': 12, 'auto_crop': False, 'enhance_text': False}, tmp_path / 'out')
    page = PdfReader(result['artifacts'][0]['path']).pages[0]
    assert float(page.mediabox.width) == pytest.approx(14400, abs=.001)
    assert float(page.mediabox.height) == pytest.approx(300 * (14400 - 24) / 15000 + 24, abs=.01)


def test_sixteen_bit_png_keeps_its_tones(tmp_path):
    samples = np.linspace(0, 65535, 400, dtype=np.uint16)[None, :].repeat(300, 0)
    source = tmp_path / 'gray16.png'
    Image.fromarray(samples).save(source)
    result = execute('pdf.images_to_pdf', [source], {'auto_crop': False, 'enhance_text': False}, tmp_path / 'out')
    tones = np.asarray(_embedded_image(result).convert('L'))
    assert tones[:, :10].mean() < 20 and tones[:, -10:].mean() > 235
    assert 100 < tones.mean() < 150, 'A 16-bit gradient is rescaled, not clipped to white'


def test_frame_guard_whitens_a_lid_strip_but_keeps_flush_print():
    from processors.partial_scan_cleanup import cleanup_paper

    def page(decorate):
        image = Image.new('RGB', (600, 800), (246, 246, 244))
        draw = ImageDraw.Draw(image)
        for row, y in enumerate(range(120, 760, 40)):
            draw.text((60, y), f'Line {row} of the scanned page', font=_font(22), fill=(30, 30, 30))
        decorate(draw)
        return image

    lid = page(lambda d: (d.rectangle((0, 0, 18, 800), fill=(58, 58, 60)),
                          d.rectangle((0, 782, 600, 800), fill=(58, 58, 60))))
    cleaned = np.asarray(cleanup_paper(lid, frame_guard=True).convert('L'))
    assert cleaned[:, :12].mean() > 240 and cleaned[-12:, :].mean() > 240, 'A neutral lid strip becomes white'
    tab = page(lambda d: (d.rectangle((0, 0, 220, 26), fill=(20, 20, 20)),
                          d.text((8, 0), 'ACME CORP', font=_font(22), fill='white')))
    kept = np.asarray(cleanup_paper(tab, frame_guard=True).convert('L'))
    before = (np.asarray(tab.convert('L'))[:26, :220] < 100).sum()
    assert (kept[:26, :220] < 100).sum() > before * .8, 'A title tab with white text is print'
    rule = page(lambda d: d.rectangle((0, 0, 599, 799), outline=(25, 25, 25), width=4))
    ruled = np.asarray(cleanup_paper(rule, frame_guard=True).convert('L'))
    assert (ruled[:5, :] < 100).mean() > .8, 'A border rule stays'
    assert np.array_equal(np.asarray(cleanup_paper(lid)), np.asarray(cleanup_paper(lid, frame_guard=False)))


def _cleaned_sheet(size, *, mottled=False, ink=None):
    """A page as cleanup hands it over: text on white, or on paper still mottled.

    `ink` adds a thin pen signature in that colour at the lower right.
    """
    if mottled:
        # Soft blotches a few levels deep plus fine grain: what a phone photo's
        # paper keeps after cleanup, and what Flate pays most for.
        rng = np.random.default_rng(3)
        blotches = cv2.resize(rng.normal(0, 1, (30, 22)).astype(np.float32), size, interpolation=cv2.INTER_CUBIC)
        grain = rng.normal(0, 2.2, (size[1], size[0])).astype(np.float32)
        paper = np.clip(247 + 5 * blotches + grain, 0, 255).astype(np.uint8)
        image = Image.fromarray(np.repeat(paper[:, :, None], 3, axis=2), 'RGB')
    else:
        image = Image.new('RGB', size, 'white')
    draw = ImageDraw.Draw(image)
    for top in range(size[1] // 20, size[1] - size[1] // 20, max(40, size[1] // 36)):
        draw.text((size[0] // 15, top), 'Consignee 4417 / shipment line entry and totals 2741.50',
                  font=_font(max(14, size[0] // 48)), fill=(25, 25, 25))
    if ink is not None:
        width, height = size
        points = [(round(width * (.55 + .04 * i)), round(height * (.86 + (.02 if i % 2 else -.02))))
                  for i in range(9)]
        draw.line(points, fill=ink, width=max(2, width // 550))
    return image


def _scan_engine(monkeypatch, page):
    """Run the engine on a sheet that prepare_image reports as cropped and cleaned.

    The fake accepts the resolution keyword, so the engine passes it, and
    records it; the JPEG encoder is counted to prove a page is encoded once.
    """
    from processors import document_scan, engine
    calls, encoded = [], []

    def prepared(image, *, auto_crop=True, enhance_text=True, render_long_edge=None):
        calls.append(render_long_edge)
        return page.copy(), {'document_detected': True, 'cropped': auto_crop, 'enhanced': enhance_text}

    jpeg_stream = engine._jpeg_stream

    def counted(picture, *args, **kwargs):
        encoded.append(picture.size)
        return jpeg_stream(picture, *args, **kwargs)

    monkeypatch.setattr(document_scan, 'prepare_image', prepared)
    monkeypatch.setattr(engine, '_jpeg_stream', counted)
    return calls, encoded


def _first_stream(result):
    image = PdfReader(result['artifacts'][0]['path']).pages[0].images[0]
    return image.indirect_reference.get_object()


def _quantization(quality):
    """Pillow's quantization tables at a quality, to identify an embedded JPEG's."""
    buffer = io.BytesIO()
    Image.new('RGB', (16, 16), 'white').save(buffer, 'JPEG', quality=quality)
    with Image.open(buffer) as reference:
        return {index: list(table) for index, table in reference.quantization.items()}


def _scan_jpeg(result, page):
    """The embedded page's DCT stream, checked to be metadata-free and baseline."""
    stream = _first_stream(result)
    assert stream['/Filter'] in ('/DCTDecode', ['/DCTDecode'])
    data = stream.get_data()
    assert b'CAMERA SERIAL' not in data and b'\xff\xfe' not in data[:4096]
    embedded = Image.open(io.BytesIO(data))
    embedded.load()
    assert embedded.size == page.size
    assert not embedded.info.get('progressive') and b'\xff\xc0' in data, 'Baseline, as every PDF reader decodes'
    assert {index: list(table) for index, table in embedded.quantization.items()} == _quantization(78)
    return data, embedded


def test_cleaned_mottled_page_over_two_megapixels_is_one_scanner_jpeg(tmp_path, monkeypatch):
    import zlib
    from PIL import JpegImagePlugin
    page = _cleaned_sheet((1654, 2339), mottled=True)
    page.info['comment'] = b'CAMERA SERIAL 12345'
    calls, encoded = _scan_engine(monkeypatch, page)
    source = tmp_path / 'sheet.png'
    Image.new('RGB', (200, 280), 'white').save(source)
    result = execute('pdf.images_to_pdf', [source], {}, tmp_path / 'out')
    assert calls == [2339], 'A cleaned page is rendered for A4 at 200 dpi'
    assert encoded == [page.size], 'The JPEG chosen is the JPEG measured: encoded once'
    assert result['metadata']['image_processing']['layouts'][0]['image_encoding'] == 'jpeg'
    data, embedded = _scan_jpeg(result, page)
    assert JpegImagePlugin.get_sampling(embedded) == 2, 'A black-and-white sheet is 4:2:0, like a scanner app'
    difference = np.abs(np.asarray(embedded.convert('L'), np.int16) - np.asarray(page.convert('L'), np.int16))
    assert difference.mean() < 3, 'Quality 78 keeps the page'
    flate = len(zlib.compress(page.tobytes(), 6))
    assert result['artifacts'][0]['size_bytes'] < .8 * flate, 'The scan ships at a fraction of its Flate size'
    photo = io.BytesIO()
    page.save(photo, 'JPEG', quality=88, subsampling=0)
    assert len(data) < .85 * photo.tell(), 'Smaller than the quality 88 full-chroma photo encoding'


@pytest.mark.parametrize('ink,fringes,sampling', [
    ((60, 40, 140), 0, 0),
    ((185, 30, 40), 0, 0),
    (None, 300, 2),
])
def test_scan_jpeg_keeps_full_chroma_only_for_coloured_ink(tmp_path, monkeypatch, ink, fringes, sampling):
    from PIL import JpegImagePlugin
    page = _cleaned_sheet((1654, 2339), mottled=True, ink=ink)
    if fringes:
        # Stray tinted pixels along black print, as a phone lens leaves them:
        # far below a signature's share, so not a reason for full chroma.
        rng = np.random.default_rng(5)
        pixels = np.array(page)
        pixels[rng.integers(0, 2339, fringes), rng.integers(0, 1654, fringes)] = (90, 60, 140)
        page = Image.fromarray(pixels, 'RGB')
    _, encoded = _scan_engine(monkeypatch, page)
    source = tmp_path / 'sheet.png'
    Image.new('RGB', (200, 280), 'white').save(source)
    result = execute('pdf.images_to_pdf', [source], {}, tmp_path / 'out')
    assert encoded == [page.size]
    _, embedded = _scan_jpeg(result, page)
    assert JpegImagePlugin.get_sampling(embedded) == sampling
    if ink is not None:
        before = np.asarray(page).astype(np.int16)
        after = np.asarray(embedded.convert('RGB')).astype(np.int16)
        stroke = np.all(before == ink, axis=2)
        chroma = lambda rgb: (rgb.max(axis=2) - rgb.min(axis=2))[stroke].mean()
        assert chroma(after) > .9 * chroma(before), 'A thin coloured stroke keeps its colour'


def test_grainy_cleaned_page_over_two_megapixels_is_one_scanner_jpeg(tmp_path, monkeypatch):
    from PIL import JpegImagePlugin
    rng = np.random.default_rng(13)
    grain = rng.normal(235, 18, (1300, 1700)).clip(0, 255).astype(np.uint8)
    page = Image.fromarray(np.repeat(grain[:, :, None], 3, axis=2), 'RGB')
    _, encoded = _scan_engine(monkeypatch, page)
    source = tmp_path / 'sheet.png'
    Image.new('RGB', (200, 280), 'white').save(source)
    result = execute('pdf.images_to_pdf', [source], {}, tmp_path / 'out')
    assert result['metadata']['image_processing']['layouts'][0]['image_encoding'] == 'jpeg'
    assert encoded == [page.size], 'The grain gate takes the scanner JPEG already encoded'
    _, embedded = _scan_jpeg(result, page)
    assert JpegImagePlugin.get_sampling(embedded) == 2


@pytest.mark.parametrize('size,jpeg_tried', [((700, 990), False), ((1654, 2339), True)])
def test_cleaned_small_or_flat_page_stays_lossless_flate(tmp_path, monkeypatch, size, jpeg_tried):
    page = _cleaned_sheet(size)
    _, encoded = _scan_engine(monkeypatch, page)
    source = tmp_path / 'sheet.png'
    Image.new('RGB', (200, 280), 'white').save(source)
    result = execute('pdf.images_to_pdf', [source], {}, tmp_path / 'out')
    assert result['metadata']['image_processing']['layouts'][0]['image_encoding'] == 'flate'
    # Only a large cleaned page is worth a trial JPEG; a flat one loses to Flate.
    assert encoded == ([size] if jpeg_tried else [])
    assert _first_stream(result)['/Filter'] in ('/FlateDecode', ['/FlateDecode'])
    assert _embedded_image(result).tobytes() == page.tobytes(), 'Every cleaned pixel is kept'


@pytest.mark.parametrize('parameters,rendered,margin', [
    ({}, 2339, .025 * 595.2756),
    ({'enhance_text': False}, None, 0),
    ({'margin': 12}, 2339, 0),
    ({'paper_size': 'A4'}, 2339, 0),
    ({'paper_size': 'original'}, None, 0),
    ({'auto_crop': False}, 2339, 0),
])
def test_scan_margin_and_resolution_follow_the_cleaned_automatic_a4_page(tmp_path, monkeypatch, parameters, rendered, margin):
    calls, _ = _scan_engine(monkeypatch, _cleaned_sheet((700, 990)))
    source = tmp_path / 'sheet.png'
    Image.new('RGB', (200, 280), 'white').save(source)
    result = execute('pdf.images_to_pdf', [source], parameters, tmp_path / 'out')
    assert calls == [rendered]
    layout = result['metadata']['image_processing']['layouts'][0]
    assert layout['scan_margin_points'] == pytest.approx(margin, abs=1e-3)
    x, y, width, height = layout['image_placement_points']
    page_width, page_height = layout['page_size_points']
    inset = margin + parameters.get('margin', 0)
    assert min(x, y) == pytest.approx(inset, abs=1e-3)
    assert x + width <= page_width - inset + 1e-3 and y + height <= page_height - inset + 1e-3
