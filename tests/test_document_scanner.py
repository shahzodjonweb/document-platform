"""The document scanner with its real models: what it changes and what it never does.

A written page is found, flattened onto a sheet's shape and cleaned to white
paper with its ink kept. Anything else (an appliance, a panel, scenery, a
flat colour, a page whose outline would cut writing away, two sheets) comes
back as the very same object, so the engine embeds the upload untouched.

These tests need the model files (scripts/fetch_scanner_models.py and
SCANNER_MODELS). Without them they skip locally and fail in CI, which always
fetches them.
"""
import json
import os
import subprocess
import sys
import time
import warnings

import cv2
import numpy as np
import pytest
from PIL import Image
from pypdf import PdfReader

from processors.scanner import scan_photo
from processors.scanner.pipeline import scan
from tests import scan_fixtures as fixtures
from tests.scan_fixtures import MANIFEST, model_files, require_models, sha256

SHEETS = {'A4': 297 / 210, 'Letter': 11 / 8.5, 'Legal': 14 / 8.5}


@pytest.fixture(scope='module', autouse=True)
def real_models():
    require_models()


@pytest.fixture(scope='module')
def checks():
    return fixtures.service_checks()


def bgr(image):
    return cv2.cvtColor(np.asarray(image.convert('RGB')), cv2.COLOR_RGB2BGR)


def page_of(result):
    return Image.fromarray(cv2.cvtColor(result['page'], cv2.COLOR_BGR2RGB))


def long_side(corners):
    return max(np.hypot(x2 - x1, y2 - y1) for (x1, y1), (x2, y2) in zip(corners, corners[1:] + corners[:1]))


def perspective_ink(page):
    # The blue note and all four red corner marks, including the bottom ones.
    assert fixtures.blue_pixels(page).sum() > 3000
    assert min(fixtures.quadrants(fixtures.red_pixels(page))) > 100


def form_ink(page):
    assert min(fixtures.form_corner_ink(page)) > 100, fixtures.form_corner_ink(page)
    assert fixtures.blue_pixels(page).sum() > 1500, 'The pen strokes stay blue'


def blue_ink(page):
    assert fixtures.blue_pixels(page).sum() > 1500


def no_colour(page):
    pass


DOCUMENTS = {
    'perspective-invoice': (lambda c: fixtures.perspective_paper(), 'Letter', fixtures.PAPER_CORNERS, perspective_ink),
    'shaded-invoice': (lambda c: fixtures.perspective_paper(shaded=True), 'Letter', fixtures.PAPER_CORNERS, perspective_ink),
    'one-written-line': (lambda c: fixtures.one_line_note('Total 42.00 paid'), 'Letter', fixtures.PAPER_CORNERS, no_colour),
    'underexposed-curled-form': (lambda c: fixtures.photographed_shipment_form(), 'A4', None, form_ink),
    'brighter-curled-form': (lambda c: fixtures.photographed_shipment_form(exposure=17), 'A4', None, form_ink),
    'form-on-light-desk': (lambda c: fixtures.photographed_shipment_form(light_desk=True), 'A4', None, form_ink),
    'curved-gray-document': (lambda c: c.curved_gray_document(), 'A4', None, form_ink),
    'held-dense-document': (lambda c: c.held_dense_document()[0], 'A4', 'dense', blue_ink),
    'yellow-paper': (lambda c: c.tinted_document_photo(), 'A4', None, blue_ink),
    'dark-gray-paper': (lambda c: c.tinted_document_photo(paper_kind='dark'), 'A4', None, blue_ink),
    'phone-jpeg-960x1280': (lambda c: fixtures.phone_document((960, 1280), quality=85), 'Letter', None, perspective_ink),
}


@pytest.mark.parametrize('name', list(DOCUMENTS))
def test_written_page_is_found_flattened_onto_its_sheet_and_cleaned(checks, name):
    make, sheet, corners, ink = DOCUMENTS[name]
    source = make(checks)
    result = scan(bgr(source))
    assert result['found'] is True and result['reason'] is None
    assert result['sheet'] == sheet
    if corners == 'dense':
        corners = checks.DENSE_PAGE_CORNERS
    if corners:
        # The camera's own corners, not the detector's: within 2% of the photo.
        error = max(np.hypot(x - u, y - v) for (x, y), (u, v) in zip(result['corners'], corners))
        assert error < .02 * np.hypot(*source.size), result['corners']
    page = page_of(result)
    height, width = page.height, page.width
    assert max(height, width) / min(height, width) == pytest.approx(SHEETS[sheet], rel=.005)
    # The print is rebuilt larger than it was photographed.
    assert max(page.size) >= 1.2 * long_side(result['corners'])
    gray = np.asarray(page.convert('L'))
    assert np.median(gray) > 240, 'The paper is made white'
    assert int((gray < 100).sum()) > 3000, 'The print stays dark'
    ink(page)


@pytest.mark.parametrize('paper,ratio', [('A4', SHEETS['A4']), ('Letter', SHEETS['Letter'])])
def test_forced_paper_shapes_the_page_to_that_sheet(paper, ratio):
    # Measured as Letter, but the customer chose the sheet.
    source = fixtures.perspective_paper()
    page, outcome = scan_photo(source, paper)
    assert outcome == {'document_detected': True, 'sheet': paper}
    assert page is not source and page.mode == 'RGB'
    assert page.height / page.width == pytest.approx(ratio, abs=.01)


def _engine_pdf(tmp_path, image):
    from processors import execute
    tmp_path.mkdir(exist_ok=True)
    source = tmp_path / 'photo.png'
    image.save(source)
    result = execute('pdf.images_to_pdf', [source], {}, tmp_path / 'out')
    with open(result['artifacts'][0]['path'], 'rb') as stream:
        return stream.read()


def test_real_scans_pass_the_live_audit_validators(checks, tmp_path):
    # The same checks verify-services runs against production.
    curved, curved_mask = checks.curved_gray_document(with_mask=True)
    flags = checks.validate_curved_scan(_engine_pdf(tmp_path / 'curved', curved), curved, true_paper_mask=curved_mask)
    assert flags['sheet_page_verified'] == 'A4' and flags['all_side_writing_preserved']
    held, paper_mask, finger_mask = checks.held_dense_document()
    flags = checks.validate_held_dense_scan(_engine_pdf(tmp_path / 'held', held), held, paper_mask, finger_mask,
                                            enhanced=True)
    assert flags['sheet_page_verified'] == 'A4'


def test_real_tinted_scan_passes_the_live_audit_validator(checks, tmp_path):
    # The scanned blue pen and stamp carry faint cyan fringes; the validator
    # measures each side label as its own cluster, so they cannot dilute it.
    source, mask = checks.tinted_document_photo(with_mask=True)
    flags = checks.validate_tinted_scan(_engine_pdf(tmp_path, source), source, mask, enhanced=True)
    assert flags['all_side_writing_preserved']


def _flattened(image):
    canvas = Image.new('RGBA', image.size, (255, 255, 255, 255))
    return Image.alpha_composite(canvas, image).convert('RGB')


NON_DOCUMENTS = {
    'ordinary-photo': fixtures.ordinary_photo,
    'gray-scenery': fixtures.ordinary_gray_photo,
    'solid-red': lambda: Image.new('RGB', (300, 150), 'red'),
    'solid-blue': lambda: Image.new('RGB', (300, 150), 'blue'),
    'solid-white': lambda: Image.new('RGB', (300, 150), 'white'),
    'solid-slate': lambda: Image.new('RGB', (500, 900), (47, 63, 81)),
    'camera-noise': fixtures.noise_photo,
    'transparent-ellipse': lambda: _flattened(fixtures.transparent_ellipse()),
    'refrigerator': fixtures.refrigerator_photo,
    'perforated-panel': fixtures.perforated_panel,
    'grille-close-up': lambda: fixtures.perforated_panel(full_frame=True),
    'blank-curved-surface': lambda: fixtures.photographed_shipment_form(blank_appliance=True),
    'blank-curved-surface-2x-sharpened': lambda: fixtures.sharpened(
        fixtures.scaled(fixtures.photographed_shipment_form(blank_appliance=True), 2)),
    'gray-appliance': fixtures.photographed_gray_appliance,
    'gray-appliance-2x-jpeg-q50': lambda: fixtures.jpeg_uploaded(
        fixtures.scaled(fixtures.photographed_gray_appliance(), 2), 50),
    'warm-panel': lambda: fixtures.tinted_appliance_panel(fixtures.WARM_PANEL),
    'gray-panel': lambda: fixtures.tinted_appliance_panel(fixtures.GRAY_PANEL),
    'gray-panel-2x': lambda: fixtures.scaled(fixtures.tinted_appliance_panel(fixtures.GRAY_PANEL), 2),
    'seven-glyphs': lambda: fixtures.one_line_note('ABCDEFG'),
    'four-marks': lambda: fixtures.one_line_note('O C U N'),
}

AMBIGUOUS = {
    'full-frame-scan-inner-table': fixtures.full_frame_scan,
    'clipped-page-thin-table': lambda: fixtures.partial_page_with_table(8),
    'clipped-page-thick-shaded-table': lambda: fixtures.partial_page_with_table(18, shaded=True),
    'filled-warm-table': lambda: fixtures.paper_with_filled_table('warm'),
    'filled-neutral-table-quarter-turn': lambda: fixtures.paper_with_filled_table(
        'neutral', rotation=Image.Transpose.ROTATE_90),
    'filled-table-blue-notes': lambda: fixtures.paper_with_filled_table('warm', colored_notes=True),
    'short-reference-word': lambda: fixtures.sharpened(fixtures.short_reference_page('ZIP', (15, 8))),
    'single-corner-glyph': lambda: fixtures.short_reference_page('A', (15, 8)),
    'single-side-glyph': lambda: fixtures.short_reference_page('A', (2, 365)),
    'single-blue-glyph': lambda: fixtures.short_reference_page('A', (15, 8), (15, 40, 135)),
    'tinted-full-frame': fixtures.tinted_full_frame,
    'tinted-sheet-clipped': fixtures.partial_tinted_sheet,
    'two-papers': fixtures.two_papers,
    'large-and-small-page': lambda: fixtures.unequal_pages([(750, 350), (1000, 350), (1010, 730), (750, 760)]),
    'large-and-tall-small-page': lambda: fixtures.unequal_pages([(710, 180), (1040, 190), (1040, 720), (705, 720)]),
    'two-tinted-sheets': fixtures.two_tinted_sheets,
    'two-tinted-sheets-2x-sharpened': lambda: fixtures.sharpened(fixtures.scaled(fixtures.two_tinted_sheets(), 2), 2),
}


@pytest.mark.parametrize('name', list(NON_DOCUMENTS))
def test_photo_that_is_not_a_document_comes_back_untouched(name):
    source = NON_DOCUMENTS[name]()
    before = source.tobytes()
    result, outcome = scan_photo(source)
    assert result is source, 'The very same object: the engine then embeds the upload as it is'
    assert outcome == {'document_detected': False, 'sheet': None}
    assert source.tobytes() == before


@pytest.mark.parametrize('name', list(AMBIGUOUS))
def test_page_whose_outline_would_lose_writing_comes_back_untouched(name):
    # An inner table, a short margin reference or a second sheet: cropping to
    # the outline would lose writing, so the photo is kept whole instead.
    source = AMBIGUOUS[name]()
    result, outcome = scan_photo(source)
    assert result is source
    assert outcome == {'document_detected': False, 'sheet': None}


def test_importing_the_scanner_keeps_the_pixel_guard_and_loads_no_heif_plugin():
    # A fresh interpreter: this one has imported everything already.
    probe = ('import sys; from PIL import Image; import processors.engine; before = Image.MAX_IMAGE_PIXELS; '
             'import processors.scanner, processors.scanner.pipeline, processors.scanner.evidence; '
             'print(before, Image.MAX_IMAGE_PIXELS, "pillow_heif" in sys.modules)')
    output = subprocess.run([sys.executable, '-c', probe], capture_output=True, text=True, check=True,
                            cwd=fixtures.ROOT).stdout.split()
    assert output == ['40000000', '40000000', 'False']


def test_every_pinned_model_file_matches_its_manifest():
    manifest = json.loads(MANIFEST.read_text())
    assert manifest['version'] and set(manifest['files']) == set(model_files())
    for name, (path, entry) in model_files().items():
        assert path.stat().st_size == entry['bytes'], name
        assert sha256(path) == entry['sha256'], name


def test_the_sandbox_runs_the_scanner_on_two_threads_with_its_models(monkeypatch, tmp_path):
    from processors import sandbox
    from processors.scanner import shadows
    seen = {}

    class Captured(Exception):
        pass

    def popen(*args, env, **kwargs):
        seen.update(env)
        raise Captured
    monkeypatch.setattr(sandbox.subprocess, 'Popen', popen)
    with pytest.raises(Captured):
        sandbox.execute_sandbox('pdf.images_to_pdf', [tmp_path / 'photo.jpg'], {}, tmp_path / 'out')
    assert seen['SCANNER_MODELS'] == os.environ['SCANNER_MODELS']
    assert seen['MALLOC_ARENA_MAX'] == '2'
    # Two threads: twice the CPU seconds of the 90 s wall budget, and 3 GiB.
    assert (seen['PDFMASTER_CPU_SECONDS'], seen['PDFMASTER_ADDRESS_SPACE_MB']) == ('170', '3072')
    monkeypatch.setenv('SCANNER_THREADS', seen['SCANNER_THREADS'])
    assert shadows.threads() == 2
    assert shadows.options().intra_op_num_threads == 2


def test_seven_phone_photos_fit_the_real_sandbox_memory_and_time_budget(tmp_path):
    """Six messenger-sized photos and one 12 MP photo in one job, in the real child.

    On Linux the child runs under RLIMIT_AS 3 GiB (processors.sandbox.child_limits)
    inside a worker limited to 3 GiB, so this is the proof that a multi-photo
    scan fits them: on Linux its peak resident memory must stay under 2 GiB.
    macOS returns little freed memory and has no address-space limit; its peak
    is reported only. The 12 MP page is framed so it comes out just under the
    size where text upscaling stops: the most memory one page needs.
    """
    from processors.sandbox import execution_timeout
    paths = []
    for index in range(6):
        path = tmp_path / f'photo-{index}.jpg'
        fixtures.phone_document((960, 1280), shaded=index % 2 == 0).save(path, quality=85)
        paths.append(path)
    large = tmp_path / 'photo-large.jpg'
    fixtures.phone_document((3000, 4000), zoom=.9).save(large, quality=90)
    paths.insert(3, large)
    budget = execution_timeout('pdf.images_to_pdf', len(paths))
    # The worker's own budget for this job (apps/core/services.py), run from a
    # fresh process: its children are then this job's sandbox child alone.
    job = ('import json, resource, sys, time; from processors.sandbox import execute_sandbox; '
           'started = time.monotonic(); '
           'result = execute_sandbox("pdf.images_to_pdf", sys.argv[3:], {}, sys.argv[1], timeout=int(sys.argv[2])); '
           'print(json.dumps({"result": result, "seconds": time.monotonic() - started, '
           '"peak": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss}))')
    output = subprocess.run([sys.executable, '-c', job, str(tmp_path / 'out'), str(budget), *map(str, paths)],
                            capture_output=True, text=True, check=True, cwd=fixtures.ROOT).stdout
    report = json.loads(output)
    result, elapsed = report['result'], report['seconds']
    # ru_maxrss is in KiB on Linux and in bytes on macOS.
    peak = report['peak'] * (1 if sys.platform == 'darwin' else 1024)
    # Shown in the warnings summary, so CI's log keeps the Linux numbers.
    warnings.warn(f'Seven-photo scan job on {sys.platform}: {elapsed:.1f} s of {budget} s, '
                  f'peak child RSS {peak / 2 ** 20:.0f} MiB', ScanBudget)
    assert elapsed < budget
    processing = result['metadata']['image_processing']
    assert processing['scan_failures'] == 0
    assert processing['document_pages'] == 7, 'Every page was scanned, the large one included'
    if sys.platform.startswith('linux'):
        assert peak < 2 * 2 ** 30, f'Peak child RSS {peak / 2 ** 20:.0f} MiB'
    reader = PdfReader(result['artifacts'][0]['path'])
    assert len(reader.pages) == 7
    assert all(layout['effective_paper_size'] == 'Letter' and layout['image_encoding'] == 'jpeg'
               for layout in processing['layouts'])
    assert max(reader.pages[3].images[0].image.size) == 2200


class ScanBudget(UserWarning):
    """The measured time and memory of the scanner job test."""
