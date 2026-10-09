"""Measure how close an image-to-PDF page is to a scanner app's output.

A phone photo of a sheet that our pipeline cleans should come out like a
scanner app renders it: white paper, no mottling, no dust, a clean rim,
straight rules, dark text at a printable resolution. This script turns those
qualities into numbers with one shared definition, so a reference PDF, our
current output and the processor run on the same photo can be compared
honestly, and the targets in the plan can be checked before and after each
change.

    python scripts/operations/scan_quality_metrics.py reference.pdf ours.pdf
    python scripts/operations/scan_quality_metrics.py --photo photo.jpg
    python scripts/operations/scan_quality_metrics.py --fixtures --json out.json

Inputs are PDFs (every page's first image is decoded straight from its
stream, so JPEG pages are measured as the bytes shipped, not re-encoded) or
plain images. --photo runs the processor with default parameters on a file
and measures the PDF it writes; --fixtures does the same on the procedural
pages the test-suite and the service audit already draw. Metrics and
targets:

    white share     gray >= 250 in the interior (3 % inset)          >= .85
    mid-grey share  120 <= gray <= 220 in the interior (mottling)    <= .025
    speckle / MP    isolated specks per megapixel of interior        <= 1.1
    speckle         the same specks per 1000 dark components         report
    halo            specks within .65 % of a glyph, per 1000          report
    border dark     gray < 120 in the outer 1.5 % band                <= .02
    rule wander     (max - min y) / width, median of 5 longest rules  <= 2 %
    rule gaps       share of a bridged rule's length with no ink,     <= .02
                    median over long horizontal and vertical rules
    rule solid      share of a rule's length darker than mid-grey     report
    vertical lean   |angle| in degrees of a line fitted to each long  <= .3
                    vertical rule, median over them
    ink p50         median gray of ink pixels                         report
    long edge       pixels of the embedded page image                 >= 1600
    bytes/encoding  of the PDF and its page stream                    report

The speckle target is per megapixel because the per-1000 figure divides by
the page's own component count, so a cleaner that frays text into more
components looks less speckled. Calibrated on the bill-of-lading photo
(2026-10-09): CamScanner's page has 2 isolated specks in 3.71 MP of interior
(.54 per MP, 1.3 per 1000), our round-1 page 23 in 3.47 MP (6.6 per MP, 10.4
per 1000); the target is about twice CamScanner's rate, so roughly four
specks on an A4 page rendered at 200 dpi. Per-megapixel figures compare pages
at similar resolution, which every scanner page here is (long edge ~2340).

Rule gaps, rule solid and vertical lean share one rule finder (_rules): the
ink is closed along the rule so breaks up to 4 % of the page side are
bridged, anything thicker than .4 % of the long edge across (text lines the
closing turned into bands, glyph stems) is dropped, and what is left and
spans 20 % of the page side is a rule. The gap share of a rule is the part
of its length where the unbridged ink is absent from its own rows, so a
faint rule the cleaner breaks into dashes scores high even where the breaks
are pale grey rather than white. Solid is the part darker than the mid-grey
band, as a scanner app's rules are along their whole length. Lean is the
angle of a line fitted to each vertical rule; a kinked rule (a fold bump)
can fit a small angle, so every row also carries the median vertical bend
in pixels and a per-rule list (rule_detail) in the JSON. The gaps and lean
columns show the rule count in brackets; a page with no long rule reads
n/a. A rule that fades wholly above the ink level, or to dots on white
paper, is not found at all, so a falling count means rules are vanishing
rather than mending. The finder expects a page near the long-edge target:
at ~100 dpi text lines are as thin as rules and some pass for broken ones
(our page from before round 1, 820x1140, reads .125 over 26 rules).

Calibrated on the same photo: CamScanner's page has 19 rules with a median
gap share of 0 and solid share of 1.00, and its 4 vertical rules lean .09
degrees (the steepest .38); our round-1 page has 20 rules with gaps .039 and
solid .82, and its 5 vertical rules lean .78 degrees, the left border kinked
by 52 px. The gap target of .02 and the lean target of .3 degrees leave
CamScanner a clear margin while failing what is visibly wrong today.

Only numpy, OpenCV, Pillow and pypdf are needed; --fixtures additionally
sets Django up because the audit fixtures live in a module that imports the
core models.
"""
import argparse
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]

# Levels shared by every metric so the columns describe one page the same way.
WHITE_LEVEL = 250        # paper that prints as pure white
MID_GREY = (120, 220)    # the mottling band: too dark for paper, too light for ink
INK_LEVEL = 160          # anything darker is treated as ink for components and rules
BORDER_DARK_LEVEL = 120  # desk fringe and shadow at the rim
INTERIOR_INSET = .03     # the rim is judged separately, so interior metrics skip it
BORDER_BAND = .015       # width of the rim band as a share of the short side
# Speck size follows the despeckle pass in partial_scan_cleanup so the metric
# and the cleaner agree on what dust is. The isolation window is half the
# cleaner's: that pass is deliberately cautious so it never lifts a period off
# a word, whereas the metric must still see dust that lies in clusters, as it
# does on a noisy page, and a half-window spans the gap to the previous glyph.
SPECK_BOX = .004
SPECK_ISOLATION = .004
NEAR_TEXT = .0065         # how close to a glyph a speck counts as hugging it
RULE_KERNEL_SHARE = 1 / 25  # the horizontal opening that keeps rules and drops glyphs
RULE_MIN_WIDTH = .2
RULE_MAX_HEIGHT = .03
RULE_COUNT = 5
# The rule finder behind rule gaps and vertical lean (see _rules). Shares of
# "along" and "across" are of the page side the rule runs along or across.
RULE_BRIDGE = .04       # closing along a rule: bridges every break seen on a cleaned page
RULE_THICKNESS = .004   # thicker cross-sections, as a share of the long edge, are not rules
RULE_COLLAR = .001      # clearance dropped around them, as a share of the long edge
RULE_MAX_BEND = .06     # how far the centre line may stray across its fitted line, share across
RULE_SEED = .1          # a rule runs this share along somewhere with every break
RULE_SEED_BREAK = .005  # shorter than this share along; stacked glyph stems never do
RULE_PIECE = .05        # a rule ends at its last stretch this long; shorter tails are glyphs

TARGETS = (
    ('white_share', '>=', .85),
    ('mid_grey_share', '<=', .025),
    ('speckle_per_mp', '<=', 1.1),
    ('border_dark', '<=', .02),
    ('rule_wander', '<=', .02),
    ('rule_gaps', '<=', .02),
    ('vertical_lean', '<=', .3),
    ('long_edge', '>=', 1600),
)


def _gray(picture):
    rgb = np.asarray(picture.convert('RGB'))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)


def _interior(gray):
    height, width = gray.shape
    dy, dx = round(height * INTERIOR_INSET), round(width * INTERIOR_INSET)
    return gray[dy:height - dy, dx:width - dx]


def _border_dark(gray):
    height, width = gray.shape
    band = max(1, round(min(width, height) * BORDER_BAND))
    rim = np.ones(gray.shape, bool)
    rim[band:height - band, band:width - band] = False
    return float((gray[rim] < BORDER_DARK_LEVEL).mean())


def _speckle(interior):
    """Specks per 1000 ink components, the component count and the speck count.

    A speck is a component small enough to be dust whose surrounding window
    holds no other ink; a period after a word fails the isolation test and
    stays a glyph. The integral image answers "any other ink nearby" for all
    candidates at once.
    """
    ink = (interior < INK_LEVEL).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    components = count - 1
    if components == 0:
        return 0., 0, 0
    stats = stats[1:]
    long_edge = max(interior.shape)
    box = max(2, round(long_edge * SPECK_BOX))
    area_limit = max(4, 10 * (long_edge / 1000) ** 2)
    small = ((stats[:, cv2.CC_STAT_WIDTH] <= box) & (stats[:, cv2.CC_STAT_HEIGHT] <= box)
             & (stats[:, cv2.CC_STAT_AREA] <= area_limit))
    if not small.any():
        return 0., components, 0
    integral = cv2.integral(ink)  # (H+1, W+1); int32 holds any page we render
    reach = max(1, round(long_edge * SPECK_ISOLATION))
    height, width = interior.shape
    x0 = np.clip(stats[small, cv2.CC_STAT_LEFT] - reach, 0, width)
    y0 = np.clip(stats[small, cv2.CC_STAT_TOP] - reach, 0, height)
    x1 = np.clip(stats[small, cv2.CC_STAT_LEFT] + stats[small, cv2.CC_STAT_WIDTH] + reach, 0, width)
    y1 = np.clip(stats[small, cv2.CC_STAT_TOP] + stats[small, cv2.CC_STAT_HEIGHT] + reach, 0, height)
    nearby = integral[y1, x1] - integral[y0, x1] - integral[y1, x0] + integral[y0, x0]
    isolated = int((nearby == stats[small, cv2.CC_STAT_AREA]).sum())
    return 1000 * isolated / components, components, isolated


def _near_text_specks(interior):
    """Speck-sized ink components lying beside larger ones, per 1000 components.

    Compression ringing around bold print, once darkened, prints as dots
    hugging the glyphs. Those are not isolated, so the speckle column never
    sees them; this one counts them. A period beside its word counts too, so
    it is a report, not a target.
    """
    ink = (interior < INK_LEVEL).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    if count < 2:
        return 0.
    long_edge = max(interior.shape)
    box = max(2, round(long_edge * SPECK_BOX))
    area_limit = max(4, 10 * (long_edge / 1000) ** 2)
    area = stats[:, cv2.CC_STAT_AREA]
    small = ((stats[:, cv2.CC_STAT_WIDTH] <= box) & (stats[:, cv2.CC_STAT_HEIGHT] <= box) & (area <= area_limit))
    large = area > area_limit
    small[0] = large[0] = False
    reach = max(1, round(long_edge * NEAR_TEXT))
    near = cv2.dilate(large[labels].astype(np.uint8), np.ones((2 * reach + 1, 2 * reach + 1), np.uint8)) > 0
    beside = np.zeros(count, bool)
    beside[np.unique(labels[near])] = True
    return 1000 * int((small & beside).sum()) / (count - 1)


def _rule_wander(gray):
    """Median vertical wander of the longest horizontal rules, or None.

    A short vertical dilation first lets a tilted or kinked rule survive the
    long horizontal opening, which otherwise only keeps rules that are
    already straight. The dilation is symmetric so column centroids are
    unchanged. Wander is measured against each rule's own width.
    """
    height, width = gray.shape
    ink = (gray < INK_LEVEL).astype(np.uint8)
    thick = cv2.dilate(ink, np.ones((3, 1), np.uint8))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(9, round(width * RULE_KERNEL_SHARE)), 1))
    rules = cv2.morphologyEx(thick, cv2.MORPH_OPEN, kernel)
    rules = cv2.morphologyEx(rules, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 1)))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(rules, connectivity=8)
    candidates = [index for index in range(1, count)
                  if stats[index, cv2.CC_STAT_WIDTH] >= RULE_MIN_WIDTH * width
                  and stats[index, cv2.CC_STAT_HEIGHT] <= RULE_MAX_HEIGHT * height]
    candidates.sort(key=lambda index: -int(stats[index, cv2.CC_STAT_WIDTH]))
    wanders = []
    for index in candidates[:RULE_COUNT]:
        left, top, w, h = (int(stats[index, field]) for field in (
            cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
        ys, xs = np.nonzero(labels[top:top + h, left:left + w] == index)
        columns = np.bincount(xs, minlength=w)
        centroid = np.bincount(xs, weights=ys, minlength=w)[columns > 0] / columns[columns > 0]
        wanders.append(float(centroid.max() - centroid.min()) / w)
    return float(np.median(wanders)) if wanders else None, len(candidates)


def _stretches(present, bridge):
    """(starts, ends) of the runs of present once breaks shorter than bridge are joined."""
    edges = np.flatnonzero(np.diff(np.r_[0, present.astype(np.int8), 0]))
    starts, ends = edges[::2], edges[1::2]
    if not len(starts):
        return starts, ends
    first = np.flatnonzero(np.r_[True, starts[1:] - ends[:-1] >= bridge])
    last = np.r_[first[1:], len(starts)] - 1
    return starts[first], ends[last]


def _line_kernel(length, along_rows):
    """A 1-D kernel of odd length: OpenCV anchors an even one off centre, so a
    closing or opening with it shifts the result by a pixel."""
    length |= 1
    return cv2.getStructuringElement(cv2.MORPH_RECT, (length, 1) if along_rows else (1, length))


def _rules(gray, long_edge):
    """The long horizontal rules of gray, each with its gap share and angle.

    Vertical rules are found by passing the transposed page. Crossing rules
    (ink in runs of RULE_KERNEL_SHARE across) are taken out first, so a
    closing cannot anchor on them and bridge to a stack of glyphs beyond.
    Closing the rest along the rows bridges a broken rule but also turns
    every text line into a solid band, so cross-sections thicker than
    RULE_THICKNESS (those bands and glyph stems) are dropped with a small
    collar; without the collar the frayed top and bottom rows of a band
    chain into fake rules that are mostly gap. A second closing re-joins a
    rule where a touching glyph cut it.

    Each remainder is then read along its length as stretches of visible
    mark (darker than the top of the mid-grey band, so the pale trace a
    cleaner leaves between the dashes of a faint rule counts) joined over
    breaks shorter than RULE_SEED_BREAK. Stacked labels, the same word in
    each row of a table, bridge stem to stem across the rows, but every
    stem is short and the paper between them white, so a remainder needs one
    stretch of RULE_SEED, and it is cut back to its first and last stretch
    of RULE_PIECE, which drops glyph tails a rule picked up at its ends. What
    is left is a rule if it still spans RULE_MIN_WIDTH of the page, is not a
    line along the image edge (the rim, which border dark judges), and its
    centre line stays within RULE_MAX_BEND of its fitted line, so a leaning
    or kinked rule is kept while a staircase of unrelated pieces is not. A
    rule wiped to dots on white paper fails the stretch test and drops out
    of the count, which is why the count is printed.

    The gap share is the part of the rule's length where the unbridged ink
    is absent from the rule's own rows; the solid share is the part where
    those rows hold a pixel darker than the mid-grey band, as every column
    of a scanner app's rule does. The angle, in degrees, comes from a line
    fitted through the column centroids, refitted once without outliers so
    a fold bump does not tilt it; the bend is how far, in pixels, the
    centre line strays across that line from one side to the other.
    """
    height, width = gray.shape
    ink = (gray < INK_LEVEL).astype(np.uint8)
    crossing = cv2.morphologyEx(ink, cv2.MORPH_OPEN, _line_kernel(max(9, round(height * RULE_KERNEL_SHARE)), False))
    bridge = _line_kernel(max(9, round(width * RULE_BRIDGE)), True)
    bridged = cv2.morphologyEx(ink & (1 - crossing), cv2.MORPH_CLOSE, bridge)
    thickness = max(3, round(long_edge * RULE_THICKNESS))
    thick = cv2.morphologyEx(bridged, cv2.MORPH_OPEN, _line_kernel(thickness + 1, False))
    collar = max(1, round(long_edge * RULE_COLLAR))
    thick = cv2.dilate(thick, _line_kernel(2 * collar + 1, False))
    rules = cv2.morphologyEx(bridged & (1 - thick), cv2.MORPH_CLOSE, bridge)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(rules, connectivity=8)
    found = []
    for index in np.flatnonzero(stats[1:, cv2.CC_STAT_WIDTH] >= RULE_MIN_WIDTH * width) + 1:
        left, top, w, h = (int(stats[index, field]) for field in (
            cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
        if top + h <= thickness or top >= height - thickness:
            continue
        mask = labels[top:top + h, left:left + w] == index
        window = gray[top:top + h, left:left + w]
        starts, ends = _stretches((mask & (window < MID_GREY[1])).any(0), max(1, round(width * RULE_SEED_BREAK)))
        pieces = ends - starts >= RULE_PIECE * width
        if not pieces.any() or (ends - starts).max() < RULE_SEED * width:
            continue
        first, last = int(starts[pieces][0]), int(ends[pieces][-1])
        if last - first < RULE_MIN_WIDTH * width:
            continue
        mask, window = mask[:, first:last], window[:, first:last]
        # An 8-connected component has pixels in every column it spans.
        centroid = (mask * np.arange(h)[:, None]).sum(0) / mask.sum(0)
        columns = np.arange(last - first)
        slope, offset = np.polyfit(columns, centroid, 1)
        residual = centroid - (offset + slope * columns)
        if residual.max() - residual.min() > RULE_MAX_BEND * height:
            continue
        inliers = np.abs(residual) <= max(1.5, 3 * float(np.median(np.abs(residual))))
        slope, offset = np.polyfit(columns[inliers], centroid[inliers], 1)
        residual = centroid - (offset + slope * columns)
        present = (mask & (window < INK_LEVEL)).any(0)
        solid = (mask & (window < MID_GREY[0])).any(0)
        found.append({'start': left + first, 'end': left + last,
                      'at': round(top + offset + slope * (last - first - 1) / 2),
                      'gap': float(1 - present.mean()), 'solid': float(solid.mean()),
                      'angle': float(np.degrees(np.arctan(slope))),
                      'bend': float(residual.max() - residual.min())})
    return found


def _rule_quality(gray):
    """Medians over the long rules of a page, and the rules themselves.

    Gap and solid shares are medians over every rule; lean (|degrees|) and
    bend (pixels) over the vertical ones. Each rule is reported with its
    orientation, its position across ('at', the row of a horizontal rule or
    the column of a vertical one), its extent along ('start', 'end'), gap
    and solid shares, angle and bend.
    """
    long_edge = max(gray.shape)
    horizontal = [{'orientation': 'h', **rule} for rule in _rules(gray, long_edge)]
    vertical = [{'orientation': 'v', **rule} for rule in _rules(np.ascontiguousarray(gray.T), long_edge)]
    found = horizontal + vertical
    gaps = float(np.median([rule['gap'] for rule in found])) if found else None
    solid = float(np.median([rule['solid'] for rule in found])) if found else None
    lean = float(np.median([abs(rule['angle']) for rule in vertical])) if vertical else None
    bend = float(np.median([rule['bend'] for rule in vertical])) if vertical else None
    detail = [{**rule, 'gap': round(rule['gap'], 4), 'solid': round(rule['solid'], 4),
               'angle': round(rule['angle'], 3), 'bend': round(rule['bend'], 1)} for rule in found]
    return {'rule_gaps': gaps, 'rule_solid': solid, 'gap_rules': len(found),
            'vertical_lean': lean, 'vertical_bend': bend, 'vertical_rules': len(vertical), 'rule_detail': detail}


def measure(picture):
    """All page metrics for one decoded page image."""
    gray = _gray(picture)
    interior = _interior(gray)
    speckle, components, specks = _speckle(interior)
    wander, rules = _rule_wander(gray)
    ink = interior[interior < INK_LEVEL]
    return {
        'width': int(gray.shape[1]), 'height': int(gray.shape[0]),
        'long_edge': int(max(gray.shape)),
        'white_share': float((interior >= WHITE_LEVEL).mean()),
        'mid_grey_share': float(((interior >= MID_GREY[0]) & (interior <= MID_GREY[1])).mean()),
        'speckle_permille': float(speckle), 'dark_components': int(components),
        'specks': int(specks), 'speckle_per_mp': specks / (interior.size / 1e6),
        'near_text_permille': _near_text_specks(interior),
        'border_dark': _border_dark(gray),
        'rule_wander': wander, 'rules_found': int(rules),
        **_rule_quality(gray),
        'ink_p50': float(np.median(ink)) if ink.size else None, 'ink_share': float(ink.size / interior.size),
    }


def _stream_encoding(stream):
    filters = stream.get('/Filter')
    names = [str(f) for f in (filters if isinstance(filters, list) else [filters] if filters else [])]
    if '/DCTDecode' in names:
        return 'jpeg'
    if '/FlateDecode' in names:
        return 'flate'
    return ','.join(name.strip('/') for name in names) or 'raw'


def _page_pictures(path):
    """Yield (label, PIL image, encoding, stream bytes) for every PDF page.

    A JPEG page is decoded from its own DCT stream so the measurement sees
    the bytes a reader shows; pypdf's generic decoder is only used for the
    lossless streams, where it is exact.
    """
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    for number, page in enumerate(reader.pages, 1):
        images = list(page.images)
        if not images:
            yield number, None, None, None
            continue
        stream = images[0].indirect_reference.get_object()
        encoding = _stream_encoding(stream)
        if encoding == 'jpeg':
            data = stream.get_data()
            picture = Image.open(io.BytesIO(data))
            picture.load()
        else:
            picture = images[0].image
            data = stream.get_data()
        yield number, picture, encoding, len(data)


def measure_pdf(path, label=None, extra=None):
    path = Path(path)
    rows = []
    for number, picture, encoding, stream_bytes in _page_pictures(path):
        row = {'name': f'{label or path.name}' + (f'#{number}' if number > 1 else ''),
               'source': str(path), 'page': number, 'pdf_bytes': path.stat().st_size,
               'encoding': encoding, 'stream_bytes': stream_bytes}
        if picture is None:
            row['error'] = 'page has no image'
        else:
            row.update(measure(picture))
        row.update(extra or {})
        rows.append(row)
    return rows


def measure_image(path):
    path = Path(path)
    with Image.open(path) as picture:
        row = {'name': path.name, 'source': str(path), 'page': None, 'pdf_bytes': None,
               'encoding': (picture.format or 'image').lower(), 'stream_bytes': path.stat().st_size}
        row.update(measure(picture))
    return [row]


def run_processor(path, label, keep=None):
    """Run images_to_pdf with default parameters and measure its page."""
    sys.path.insert(0, str(ROOT))
    from processors import execute
    if keep:
        out = Path(keep) / label
        out.mkdir(parents=True, exist_ok=True)
        if any(out.iterdir()):
            raise SystemExit(f'{out} is not empty; the processor needs a fresh directory')
        holder = None
    else:
        holder = tempfile.TemporaryDirectory()
        out = Path(holder.name) / 'out'
    try:
        started = time.perf_counter()
        result = execute('pdf.images_to_pdf', [str(path)], {}, out)
        seconds = time.perf_counter() - started
        processing = result['metadata'].get('image_processing', {})
        extra = {'seconds': round(seconds, 2), 'outcome': (processing.get('pages') or [None])[0],
                 'layout': (processing.get('layouts') or [None])[0], 'input': str(path)}
        return measure_pdf(result['artifacts'][0]['path'], label, extra)
    finally:
        if holder is not None:
            holder.cleanup()


def fixture_pages(workdir):
    """The procedural photos the tests and the service audit already draw.

    They are rendered to PNG files because the processor takes paths, and the
    audit module needs Django because it imports the core models. The font
    paths inside the fixtures are relative to the repository root.
    """
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()
    from scripts.operations.service_checks_documents import held_dense_document, tinted_document_photo
    from tests.test_image_scanning import perspective_paper
    from tests.test_image_scanning_realistic import photographed_shipment_form
    pages = (
        ('shipment_form', lambda: photographed_shipment_form()),
        ('perspective_paper_shaded', lambda: perspective_paper(shaded=True)),
        ('tinted_document', lambda: tinted_document_photo()),
        ('held_dense_document', lambda: held_dense_document()[0]),
    )
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    for label, build in pages:
        path = workdir / f'{label}.png'
        build().save(path, 'PNG')
        yield label, path


def _verdict(row, key, relation, target):
    value = row.get(key)
    if value is None:
        return 'n/a'
    return 'PASS' if (value >= target if relation == '>=' else value <= target) else 'FAIL'


def _format(row):
    def number(key, digits):
        value = row.get(key)
        return '-' if value is None else f'{value:.{digits}f}'

    def counted(key, digits, count):
        return number(key, digits) + (f'({row[count]})' if row.get(count) is not None else '')
    size = f"{row['width']}x{row['height']}" if 'width' in row else '-'
    pdf_bytes = row.get('pdf_bytes')
    return {
        'white': number('white_share', 3), 'midgrey': number('mid_grey_share', 3),
        'speck/MP': number('speckle_per_mp', 2), 'speck': number('speckle_permille', 1),
        'halo': number('near_text_permille', 0),
        'border': number('border_dark', 3),
        'rule': counted('rule_wander', 4, 'rules_found'), 'gaps': counted('rule_gaps', 3, 'gap_rules'),
        'solid': number('rule_solid', 2), 'lean': counted('vertical_lean', 2, 'vertical_rules'),
        'ink': number('ink_p50', 0), 'size': size,
        'bytes': '-' if pdf_bytes is None else f'{pdf_bytes:,}', 'enc': row.get('encoding') or '-',
        'sec': number('seconds', 2) if 'seconds' in row else '',
    }


def print_table(rows):
    columns = (('white', 'white_share'), ('midgrey', 'mid_grey_share'), ('speck/MP', 'speckle_per_mp'),
               ('speck', None), ('halo', None), ('border', 'border_dark'), ('rule', 'rule_wander'),
               ('gaps', 'rule_gaps'), ('solid', None), ('lean', 'vertical_lean'), ('ink', None),
               ('size', 'long_edge'), ('bytes', None), ('enc', None), ('sec', None))
    targets = {key: (relation, target) for key, relation, target in TARGETS}
    formatted = [_format(row) for row in rows]
    widths = {name: max([len(name)] + [len(cells[name]) for cells in formatted]) for name, _ in columns}
    widths = {name: max(width, 4) for name, width in widths.items()}
    name_width = max([4] + [len(row['name']) for row in rows])
    header = f"{'name':<{name_width}}  " + '  '.join(f'{name:>{widths[name]}}' for name, _ in columns)
    target_line = f"{'target':<{name_width}}  " + '  '.join(
        f"{(targets[key][0] + ('%g' % targets[key][1])) if key in targets else '':>{widths[name]}}"
        for name, key in columns)
    print(header)
    print(target_line)
    print('-' * len(header))
    for row, cells in zip(rows, formatted):
        print(f"{row['name']:<{name_width}}  " + '  '.join(f'{cells[name]:>{widths[name]}}' for name, _ in columns))
        verdicts = []
        for name, key in columns:
            mark = _verdict(row, key, *targets[key]) if key in targets and 'error' not in row else ''
            verdicts.append(f'{mark:>{widths[name]}}')
        print(f"{row.get('error', ''):<{name_width}}  " + '  '.join(verdicts))
    print('speck/MP: isolated specks per megapixel of interior; speck and halo (specks hugging glyphs) are per '
          '1000 ink components, report only')
    print('rule: wander(rules found); gaps: median share of long rules with no ink(rules); solid: median share '
          'darker than mid-grey, report; lean: median |degrees| of vertical rules(rules); ink: median gray of ink')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('inputs', nargs='*', help='PDF or image files to measure as they are')
    parser.add_argument('--photo', action='append', default=[], metavar='FILE',
                        help='run the processor with defaults on this photo and measure the PDF')
    parser.add_argument('--fixtures', action='store_true', help='run the processor on the procedural fixture set')
    parser.add_argument('--keep', metavar='DIR', help='keep processor outputs and fixture PNGs under DIR')
    parser.add_argument('--json', metavar='FILE', help="write all rows as JSON ('-' for stdout)")
    args = parser.parse_args(argv)
    if not (args.inputs or args.photo or args.fixtures):
        parser.error('nothing to measure')
    rows = []
    for item in args.inputs:
        path = Path(item)
        rows.extend(measure_pdf(path) if path.suffix.lower() == '.pdf' else measure_image(path))
    for item in args.photo:
        path = Path(item)
        rows.extend(run_processor(path, f'photo:{path.stem}', args.keep))
    if args.fixtures:
        holder = None if args.keep else tempfile.TemporaryDirectory()
        workdir = Path(args.keep) / 'fixtures' if args.keep else Path(holder.name)
        try:
            for label, path in fixture_pages(workdir):
                rows.extend(run_processor(path, f'fixture:{label}', args.keep))
        finally:
            if holder is not None:
                holder.cleanup()
    print_table(rows)
    if args.json:
        payload = {'targets': [{'metric': key, 'relation': relation, 'target': target} for key, relation, target in TARGETS],
                   'definitions': {'white_level': WHITE_LEVEL, 'mid_grey': MID_GREY, 'ink_level': INK_LEVEL,
                                   'border_dark_level': BORDER_DARK_LEVEL, 'interior_inset': INTERIOR_INSET,
                                   'border_band': BORDER_BAND, 'speck_box': SPECK_BOX,
                                   'speck_isolation': SPECK_ISOLATION, 'near_text': NEAR_TEXT,
                                   'rule_kernel_share': RULE_KERNEL_SHARE, 'rule_min_width': RULE_MIN_WIDTH,
                                   'rule_max_height': RULE_MAX_HEIGHT, 'rule_bridge': RULE_BRIDGE,
                                   'rule_max_bend': RULE_MAX_BEND, 'rule_seed': RULE_SEED,
                                   'rule_seed_break': RULE_SEED_BREAK, 'rule_piece': RULE_PIECE,
                                   'rule_thickness': RULE_THICKNESS, 'rule_collar': RULE_COLLAR},
                   'rows': [{**row, 'verdicts': {key: _verdict(row, key, relation, target)
                                                 for key, relation, target in TARGETS}} for row in rows]}
        text = json.dumps(payload, indent=1, default=str)
        if args.json == '-':
            print(text)
        else:
            Path(args.json).write_text(text)
    failed = any(_verdict(row, key, relation, target) == 'FAIL'
                 for row in rows for key, relation, target in TARGETS)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
