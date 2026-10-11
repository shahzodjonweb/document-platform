"""Procedural photographs for the document scanner tests, and the model guard.

Every image is generated here from generic words, marks and geometry: no
customer photo, address, identity, signature or shipment information is
stored in the repository. The camera corners and paper masks belong to the
generators, independently of the scanner's own decisions.

Three kinds of photograph:

  documents      written pages that must be found, flattened and cleaned
  non-documents  appliances, panels, scenery, flat colours: never changed
  ambiguous      a page whose outline would lose writing (an inner table, a
                 short margin reference, two sheets): left as photographed

The curved gray, tinted and held dense documents live in
scripts/operations/service_checks_documents.py (the live audit uses them);
service_checks() loads that module.
"""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / 'processors/assets/fonts/NotoSans-Regular.ttf'
MANIFEST = ROOT / 'processors/scanner/models.json'
BUNDLED_MODELS = ROOT / 'processors/scanner/models'


# --- The real models -------------------------------------------------------

def model_files():
    """Where each pinned model file is expected, as the scanner looks for it."""
    folder = Path(os.environ['SCANNER_MODELS']) if os.environ.get('SCANNER_MODELS') else BUNDLED_MODELS
    files = json.loads(MANIFEST.read_text())['files']
    return {name: (folder / name if (folder / name).is_file() else BUNDLED_MODELS / name, entry)
            for name, entry in files.items()}


def missing_models():
    """Why the real scanner cannot run here, or None."""
    if not os.environ.get('SCANNER_MODELS'):
        return 'SCANNER_MODELS is not set: run scripts/fetch_scanner_models.py and point it at that folder'
    missing = sorted(name for name, (path, _) in model_files().items() if not path.is_file())
    return 'scanner model files missing: ' + ', '.join(missing) if missing else None


def require_models():
    """Skip without the model files, except in CI, where they are always fetched."""
    reason = missing_models()
    if reason:
        if os.environ.get('CI'):
            pytest.fail(reason + ' (CI fetches them in the verify job)', pytrace=False)
        pytest.skip(reason)


@pytest.fixture
def scanner_models():
    require_models()


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def service_checks():
    """scripts/operations/service_checks_documents.py, which needs Django set up."""
    spec = importlib.util.spec_from_file_location('scan_fixture_service_checks',
                                                  ROOT / 'scripts/operations/service_checks_documents.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- Shared helpers --------------------------------------------------------

def font(size=21):
    return ImageFont.truetype(str(FONT), size)


def scaled(image, scale):
    """The same photograph as a smaller or larger phone upload."""
    if scale == 1:
        return image
    return image.resize((round(image.width * scale), round(image.height * scale)),
                        Image.Resampling.LANCZOS)


def sharpened(image, threshold=3):
    """Camera-app sharpening leaves overshoot halos around every stroke and edge."""
    return image.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=threshold))


def jpeg_uploaded(image, quality=75):
    """A messenger upload: 4:2:0 chroma, block noise and ringing."""
    buffer = io.BytesIO()
    image.save(buffer, 'JPEG', quality=quality)
    uploaded = Image.open(io.BytesIO(buffer.getvalue()))
    uploaded.load()
    return uploaded.convert('RGB')


def blue_pixels(image):
    pixels = np.asarray(image).astype(np.int16)
    return (pixels[:, :, 2] > pixels[:, :, 0] + 35) & (pixels[:, :, 2] > pixels[:, :, 1] + 25)


def red_pixels(image):
    pixels = np.asarray(image).astype(np.int16)
    return (pixels[:, :, 0] > pixels[:, :, 1] + 65) & (pixels[:, :, 0] > pixels[:, :, 2] + 65)


def quadrants(mask):
    """A mask's count in each corner quarter: TL, TR, BL, BR."""
    height, width = mask.shape
    return [int(mask[:height // 4, :width // 4].sum()), int(mask[:height // 4, 3 * width // 4:].sum()),
            int(mask[3 * height // 4:, :width // 4].sum()), int(mask[3 * height // 4:, 3 * width // 4:].sum())]


def form_corner_ink(image):
    """The shipment form's A1 (red), B2 (green), C3 (blue) and D4 (purple) corner labels."""
    p = np.asarray(image).astype(np.int16)
    rules = [lambda p: (p[:, :, 0] > p[:, :, 1] + 35) & (p[:, :, 0] > p[:, :, 2] + 35),
             lambda p: (p[:, :, 1] > p[:, :, 0] + 25) & (p[:, :, 1] > p[:, :, 2] + 25),
             lambda p: (p[:, :, 2] > p[:, :, 0] + 35) & (p[:, :, 2] > p[:, :, 1] + 25),
             lambda p: (p[:, :, 0] > p[:, :, 1] + 35) & (p[:, :, 2] > p[:, :, 1] + 35)]
    return [quadrants(rule(p))[index] for index, rule in enumerate(rules)]


# --- A flat invoice photographed in perspective ----------------------------

PAPER_CORNERS = ((150, 100), (595, 145), (615, 820), (85, 740))
DESK = (46, 64, 54)


def paper(*, shaded=False):
    width, height = 440, 640
    if shaded:
        # A broad, gradual lighting change, not an artificial binary page mask.
        lighting = np.broadcast_to(np.linspace(184, 247, width, dtype=np.uint8), (height, width))
        image = Image.fromarray(np.repeat(lighting[:, :, None], 3, axis=2), 'RGB')
    else:
        image = Image.new('RGB', (width, height), (246, 246, 244))
    draw = ImageDraw.Draw(image)
    draw.text((28, 36), 'Invoice / Hisob / Счёт', font=font(24), fill=(30, 30, 30))
    for number, top in enumerate(range(100, 465, 42), 1):
        draw.text((30, top), f'{number}. Original text and totals 123', font=font(), fill=(40, 40, 40))
    draw.line([(38, 550), (95, 516), (145, 548), (208, 520), (276, 545)], fill=(20, 55, 145), width=5)
    draw.text((40, 580), 'Blue handwritten note', font=font(20), fill=(20, 55, 145))
    # Coloured marks near every corner detect accidental inward crops.
    for x, y in ((14, 14), (width - 26, 14), (14, height - 26), (width - 26, height - 26)):
        draw.rectangle((x, y, x + 11, y + 11), fill=(155, 25, 25))
    return image


def project(sheet, corners, *, size=(720, 900), background=DESK):
    """Photograph a sheet using an actual projective image transform."""
    rgb = np.asarray(sheet)
    source = np.array([[0, 0], [sheet.width - 1, 0],
                       [sheet.width - 1, sheet.height - 1], [0, sheet.height - 1]], np.float32)
    matrix = cv2.getPerspectiveTransform(source, np.asarray(corners, np.float32))
    warped = cv2.warpPerspective(rgb, matrix, size, flags=cv2.INTER_LINEAR)
    mask = cv2.warpPerspective(np.full(rgb.shape[:2], 255, np.uint8), matrix, size,
                               flags=cv2.INTER_NEAREST)
    result = np.empty((size[1], size[0], 3), np.uint8)
    result[:] = background
    result[mask > 0] = warped[mask > 0]
    return Image.fromarray(result, 'RGB')


def perspective_paper(*, shaded=False):
    return project(paper(shaded=shaded), PAPER_CORNERS)


def phone_document(size, *, shaded=True, quality=None, zoom=1.):
    """perspective_paper as a phone of another resolution takes it (``size`` = w, h).

    ``zoom`` below 1 moves the camera back: the page fills less of the photo.
    """
    sx, sy = size[0] / 720, size[1] / 900
    corners = [(size[0] / 2 + (x * sx - size[0] / 2) * zoom, size[1] / 2 + (y * sy - size[1] / 2) * zoom)
               for x, y in PAPER_CORNERS]
    sheet = paper(shaded=shaded).resize((round(440 * min(sx, sy) * zoom), round(640 * min(sx, sy) * zoom)),
                                        Image.Resampling.LANCZOS)
    image = project(sheet, corners, size=size)
    return image if quality is None else jpeg_uploaded(image, quality)


def one_line_note(text):
    """A mostly blank sheet whose only writing is one short line."""
    sheet = Image.new('RGB', (440, 640), (246, 246, 244))
    ImageDraw.Draw(sheet).text((40, 300), text, font=font(24), fill=(30, 30, 30))
    return project(sheet, PAPER_CORNERS)


def two_papers():
    size = (900, 900)
    array = np.array(Image.new('RGB', size, (50, 67, 55)))
    for corners in ([(55, 80), (408, 100), (396, 800), (45, 780)],
                    [(494, 110), (848, 80), (862, 780), (508, 804)]):
        projected = np.asarray(project(paper(), corners, size=size))
        foreground = np.any(projected != np.array(DESK), axis=2)
        array[foreground] = projected[foreground]
    return Image.fromarray(array, 'RGB')


def unequal_pages(small_corners):
    """A large sheet beside a smaller one on the same desk."""
    size = (1100, 1000)
    pixels = np.empty((size[1], size[0], 3), np.uint8)
    pixels[:] = DESK
    for corners in ([(55, 65), (610, 85), (600, 945), (35, 920)], small_corners):
        projected = np.asarray(project(paper(), corners, size=size))
        foreground = np.any(projected != np.asarray(DESK), axis=2)
        pixels[foreground] = projected[foreground]
    return Image.fromarray(pixels)


def full_frame_scan():
    """A flat scan whose inner table is page-shaped; the heading and footer lie outside it."""
    image = Image.new('RGB', (700, 950), (247, 247, 244))
    draw = ImageDraw.Draw(image)
    draw.text((35, 40), 'Whole page: keep this heading', font=font(28), fill=(30, 30, 30))
    draw.text((35, 110), 'Text above the table', font=font(), fill=(40, 40, 40))
    draw.rectangle((100, 210, 600, 735), outline=(25, 25, 25), width=4)
    for y in range(285, 735, 75):
        draw.line((100, y, 600, y), fill=(25, 25, 25), width=3)
    for x in (267, 434):
        draw.line((x, 210, x, 735), fill=(25, 25, 25), width=3)
    draw.text((35, 825), 'Keep this footer too', font=font(25), fill=(20, 55, 145))
    return image


def partial_page_with_table(border, *, shaded=False):
    """full_frame_scan with a thick table, clipped by the desk on its left."""
    image = full_frame_scan()
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 210, 600, 735), outline=(25, 25, 25), width=border)
    if shaded:
        pixels = np.array(image)
        lighting = np.linspace(.77, 1, image.width, dtype=np.float32)
        pixels = np.clip(pixels.astype(np.float32) * lighting[None, :, None], 0, 255).astype(np.uint8)
        image = Image.fromarray(pixels)
        draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 85, image.height), fill=(75, 80, 65))
    return image


# --- Things that are not documents ------------------------------------------

def ordinary_photo():
    image = Image.new('RGB', (720, 900), (75, 130, 183))
    draw = ImageDraw.Draw(image)
    draw.ellipse((-130, 430, 620, 1180), fill=(48, 99, 56))
    draw.ellipse((330, 300, 1190, 1190), fill=(70, 122, 65))
    draw.ellipse((160, 110, 430, 180), fill=(195, 209, 215))
    draw.line((0, 680, 720, 730), fill=(109, 74, 49), width=21)
    return image


def noise_photo(seed=11, size=(400, 300)):
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(40, 220, (size[1], size[0], 3), dtype=np.uint8))


def refrigerator_photo():
    image = Image.new('RGB', (720, 900), (98, 87, 80))
    draw = ImageDraw.Draw(image)
    draw.rectangle((190, 150, 585, 800), fill=(240, 241, 238), outline=(66, 70, 64), width=4)
    draw.rectangle((225, 280, 239, 600), fill=(67, 69, 62))
    draw.rectangle((0, 795, 720, 900), fill=(89, 65, 39))
    return image


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


def transparent_ellipse():
    """A transparent PNG's content as the engine sees it: flattened onto white."""
    image = Image.new('RGBA', (360, 240), (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((110, 70, 250, 170), fill=(20, 55, 145, 255))
    return image


# --- Curled gray paper on a ribbed desk (and look-alike appliances) --------

CAMERA_SIZE = (720, 900)
FORM_SIZE = (450, 680)
FORM_CORNERS = np.array([(140, 90), (601, 143), (561, 819), (88, 746)], np.float32)
FORM_CORNER_COLORS = [(110, 18, 21), (14, 88, 26), (17, 42, 119), (108, 21, 101)]


def shipment_form(*, blank=False, exposure=0):
    """Paper with gradual poor lighting, generic print, a table and pen strokes."""
    width, height = FORM_SIZE
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    x /= width - 1
    y /= height - 1
    broad_shadow = 13 * np.exp(-((x - .18) ** 2 / .10 + (y - .72) ** 2 / .18))
    light = 133 + 34 * x + 13 * y - broad_shadow
    noise = np.random.default_rng(1729).normal(0, 1.1, light.shape)
    light = np.clip(light + noise + exposure, 130 + exposure, 180 + exposure).astype(np.uint8)
    if blank:
        light = np.clip(light.astype(np.int16) + 75, 0, 255).astype(np.uint8)
    sheet = Image.fromarray(np.repeat(light[:, :, None], 3, axis=2), 'RGB')
    if blank:
        return sheet
    draw = ImageDraw.Draw(sheet)
    draw.text((80, 38), 'SHIPMENT RECORD', font=font(21), fill=(25, 25, 25))
    draw.text((30, 84), 'Reference: SAMPLE A12', font=font(16), fill=(38, 38, 38))
    draw.text((30, 111), 'Route: Depot A to Depot B', font=font(16), fill=(38, 38, 38))
    draw.text((30, 138), 'Date: sample entry', font=font(16), fill=(38, 38, 38))
    draw.rectangle((29, 192, 419, 452), outline=(33, 33, 33), width=2)
    for top in [238, 292, 345, 399]:
        draw.line((29, top, 419, top), fill=(42, 42, 42), width=2)
    for left in [239, 320]:
        draw.line((left, 192, left, 452), fill=(42, 42, 42), width=2)
    for left, value in [(40, 'Item'), (251, 'Units'), (330, 'Weight')]:
        draw.text((left, 205), value, font=font(15), fill=(25, 25, 25))
    for top, name, units, weight in [(250, 'Parcel A', '02', '1.5'),
                                    (304, 'Parcel B', '01', '2.0'),
                                    (357, 'Parcel C', '03', '0.8'),
                                    (410, 'Total', '06', '4.3')]:
        for left, value in [(40, name), (251, units), (334, weight)]:
            draw.text((left, top), value, font=font(16), fill=(30, 30, 30))
    draw.text((31, 492), 'Received: sample acknowledgement', font=font(16), fill=(32, 32, 32))
    # Generic pen strokes, not a person's signature.
    draw.line([(57, 558), (91, 531), (104, 560), (136, 538),
               (160, 556), (186, 540), (210, 553), (247, 546)],
              fill=(17, 42, 119), width=4)
    draw.text((30, 594), 'Inspect all items before accepting.', font=font(16), fill=(30, 30, 30))
    # Coloured writing close to every visible corner catches inward edge crops.
    for location, value, color in zip([(12, 10), (width - 53, 10),
                                       (12, height - 34), (width - 53, height - 34)],
                                      ['A1', 'B2', 'C3', 'D4'], FORM_CORNER_COLORS):
        draw.text(location, value, font=font(21), fill=color)
    # Mid-edge labels catch a crop that keeps the corners but clips bowed sides.
    for location, value in zip([(4, height // 2 - 14), (width - 42, height // 2 - 14),
                                (width // 2 - 15, 2), (width // 2 - 15, height - 28)],
                               ['E5', 'F6', 'G7', 'H8']):
        draw.text(location, value, font=font(21), fill=FORM_CORNER_COLORS[-1])
    return sheet


def _curled(sheet):
    """Gently bow the photographed edges without hiding any of the four corners."""
    margin = 26
    width, height = sheet.size
    yy, xx = np.mgrid[0:height + 2 * margin, 0:width + 2 * margin].astype(np.float32)
    x = (xx - margin) / (width - 1)
    y = (yy - margin) / (height - 1)
    map_x = xx - margin - 17 * np.sin(np.pi * np.clip(y, 0, 1))
    map_y = yy - margin + 11 * np.sin(np.pi * np.clip(x, 0, 1))
    rgb = cv2.remap(np.asarray(sheet), map_x, map_y, cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
    alpha = cv2.remap(np.full((height, width), 255, np.uint8), map_x, map_y,
                      cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return rgb, alpha, margin


def _desk(size, *, light=False):
    yy, xx = np.mgrid[0:size[1], 0:size[0]].astype(np.float32)
    desk = ((217 if light else 112) + 6 * np.sin((yy + .16 * xx) * np.pi / 12)
            + 4 * xx / size[0] + 2 * yy / size[1])
    return np.repeat(desk[:, :, None], 3, axis=2)


def _place(sheet, corners, background):
    """Place a bowed sheet on an existing desk so several sheets can coexist."""
    rgb, alpha, margin = _curled(sheet)
    width, height = sheet.size
    size = (background.shape[1], background.shape[0])
    source = np.array([(margin, margin), (width - 1 + margin, margin),
                       (width - 1 + margin, height - 1 + margin),
                       (margin, height - 1 + margin)], np.float32)
    transform = cv2.getPerspectiveTransform(source, np.asarray(corners, np.float32))
    warped = cv2.warpPerspective(rgb, transform, size, flags=cv2.INTER_LINEAR)
    mask = cv2.warpPerspective(alpha, transform, size, flags=cv2.INTER_LINEAR).astype(np.float32) / 255
    # A shallow cast shadow makes the paper's outer edge naturally uneven.
    shadow = cv2.GaussianBlur(mask, (0, 0), 5)
    background = np.clip(background - 9 * shadow[:, :, None] * (1 - mask[:, :, None]), 0, 255)
    return background * (1 - mask[:, :, None]) + warped * mask[:, :, None]


def photographed_shipment_form(*, light_desk=False, blank_appliance=False, exposure=0):
    """Perspective photograph with ribbed desk texture, curl, shade and mild blur.

    With ``blank_appliance`` the 'paper' is a bright curved surface with no
    writing at all.
    """
    sheet = shipment_form(blank=blank_appliance, exposure=exposure)
    photographed = _place(sheet, FORM_CORNERS, _desk(CAMERA_SIZE, light=light_desk))
    photographed = cv2.GaussianBlur(np.clip(photographed, 0, 255).astype(np.uint8), (3, 3), .55)
    return Image.fromarray(photographed, 'RGB')


def photographed_gray_appliance():
    """A gray curved device cover has vents and a knob, but no written content."""
    panel = shipment_form(blank=True, exposure=-75)
    draw = ImageDraw.Draw(panel)
    for top in (230, 260, 290, 320):
        draw.rounded_rectangle((93, top, 355, top + 8), radius=4, fill=(63, 63, 63))
    draw.ellipse((178, 463, 272, 557), fill=(83, 83, 83), outline=(53, 53, 53), width=3)
    draw.line((225, 479, 225, 509), fill=(44, 44, 44), width=3)
    photographed = _place(panel, FORM_CORNERS, _desk(CAMERA_SIZE))
    return Image.fromarray(np.clip(photographed, 0, 255).astype(np.uint8), 'RGB')


def ordinary_gray_photo():
    """Monochrome scenery has texture and dark marks, but no paper outline."""
    width, height = CAMERA_SIZE
    yy, _ = np.mgrid[0:height, 0:width].astype(np.float32)
    sky = np.clip(178 - 42 * yy / height, 0, 255).astype(np.uint8)
    image = Image.fromarray(np.repeat(sky[:, :, None], 3, axis=2), 'RGB')
    draw = ImageDraw.Draw(image)
    draw.ellipse((140, 140, 500, 230), fill=(205, 205, 205))
    draw.polygon([(0, 610), (125, 355), (300, 585), (510, 380), (720, 630), (720, 900), (0, 900)],
                 fill=(104, 104, 104))
    draw.ellipse((-140, 625, 920, 1070), fill=(72, 72, 72))
    draw.line((0, 730, 720, 793), fill=(44, 44, 44), width=24)
    draw.line((540, 372, 518, 746), fill=(48, 48, 48), width=18)
    for top, left, right in [(418, 426, 631), (477, 410, 640), (550, 388, 647)]:
        draw.line((left, top, 529, top - 39, right, top + 7), fill=(55, 55, 55), width=13)
    return image


# --- Tinted paper and tinted panels ----------------------------------------

def tinted_full_frame():
    """A warm sheet filling the photo: an inner frame, writing on every side."""
    image = Image.new('RGB', (600, 780), (213, 194, 149))
    draw = ImageDraw.Draw(image)
    draw.text((10, 8), 'Upper edge note', font=font(22), fill=(25, 25, 25))
    draw.text((10, 740), 'Lower edge note', font=font(22), fill=(25, 25, 25))
    draw.rectangle((70, 140, 530, 630), outline=(30, 30, 30), width=12)
    for top in range(165, 610, 38):
        draw.text((90, top), 'Sample table row: retain the whole page', font=font(22), fill=(30, 30, 30))
    draw.text((2, 375), 'LEFT', font=font(22), fill=(15, 40, 135))
    draw.text((541, 375), 'RIGHT', font=font(22), fill=(15, 40, 135))
    return image


def partial_tinted_sheet():
    """tinted_full_frame on a bright desk, its right edge outside the photograph."""
    source = Image.new('RGB', (720, 900), (237, 238, 235))
    source.paste(tinted_full_frame().resize((660, 858)), (140, 26))
    return source


def two_tinted_sheets():
    """A warm sheet beside a smaller gray copy on one bright desk."""
    source = Image.new('RGB', (900, 900), (238, 239, 236))
    source.paste(tinted_full_frame().resize((350, 520)), (50, 140))
    second = tinted_full_frame().convert('L').convert('RGB').resize((230, 345))
    source.paste(second, (575, 280))
    return source


WARM_PANEL, GRAY_PANEL = (213, 194, 149), (154, 155, 157)


def tinted_appliance_panel(panel_color):
    """A tinted curved panel with vent slots and a knob, but no writing."""
    source = Image.new('RGB', (720, 900), (237, 238, 235))
    draw = ImageDraw.Draw(source)
    draw.polygon(((140, 90), (601, 143), (561, 819), (88, 746)), fill=panel_color)
    for top in range(280, 470, 23):
        draw.line((190, top, 489, top + 31), fill=(74, 76, 73), width=5)
    draw.ellipse((350, 550, 435, 635), fill=(83, 84, 80), outline=(40, 40, 40), width=5)
    return source


# --- Inner tables and short margin references ------------------------------

def paper_with_filled_table(kind, *, colored_notes=False, rotation=None):
    """A generic page with a filled inner table and writing on all four sides."""
    image = Image.new('RGB', (600, 780), (238, 238, 235))
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
        draw.text((90, y), 'Shaded table: sample entry 123', font=font(22), fill=(30, 30, 30))
    for x in (290, 420):
        draw.line((x, top, x, bottom), fill=(80, 80, 80), width=2)
    color = (15, 40, 135) if colored_notes else (25, 25, 25)
    draw.text((15, 8), 'Keep the top margin note', font=font(22), fill=color)
    draw.text((15, 736), 'Keep the bottom margin note', font=font(22), fill=color)
    draw.text((2, 365), 'L', font=font(22), fill=color)
    draw.text((576, 365), 'R', font=font(22), fill=color)
    return image if rotation is None else image.transpose(rotation)


def short_reference_page(reference, position, color=(25, 25, 25)):
    """A filled neutral block whose only margin content is one short reference."""
    source = paper_with_filled_table('neutral')
    draw = ImageDraw.Draw(source)
    # Leave exactly one known reference on the real page margin. A short code
    # or an isolated handwritten initial is still content that must be kept.
    for box in ((0, 0, 599, 89), (0, 700, 599, 779),
                (0, 330, 49, 409), (550, 330, 599, 409)):
        draw.rectangle(box, fill=(238, 238, 235))
    draw.text(position, reference, font=font(22), fill=color)
    return source
