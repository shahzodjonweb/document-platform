"""Bounded paper illumination and neutral-stroke cleanup for clipped scans."""
from PIL import Image

# Bilateral (d, sigma colour, sigma space) and the tile geometry that keeps
# its context inside one million pixels, keyed by the nominal source scale.
# A 2x upsample spreads camera grain over twice the pixels, so the
# neighbourhood grows with it. The halo holds the bilateral, the paper
# closing and its smoothing plus the longest context read after them, the
# straight-line rule evidence (RULED_SPAN), and step + 2 * halo = 1000.
UPSAMPLED = 1.5
BILATERAL = {1: (5, 11, 2), 2: (9, 13, 4)}
STEP = {1: 896, 2: 888}
HALO = {1: 52, 2: 56}
# Residual and chroma that a clean render leaves on blank paper. A grainy
# photo measures above these and raises its own floors.
NOISE_FLOOR = 2.25
CHROMA_FLOOR = 4.
# Where the grain lifts the floor above a clean render's, contrast just over
# the floor is as likely grain as print: it ramps in over KNEE times that
# excess (quadratically), and anything further above keeps its full gain. A
# clean render has no excess and is untouched.
KNEE = 2.
# Colour on a pixel that prints as paper must stand TINT levels above the
# chroma floor before it is kept: a faint cast left by the lighting or the
# compression goes, a highlighter or a pen is far above it.
TINT = 4.
# Despeckle and sharpening frames: cv.integral adds a row and a column, so
# the frame itself stays two pixels under the million-pixel budget. Speck
# geometry grows with the page up to FINISH_EDGE pixels on the long side,
# where its halo still fits a third of the frame.
FINISH_BUDGET = 998
FINISH_EDGE = 20000
# Despeckle marks are runs of pixels darker than near-white. Row evidence:
# columns pooled into 8-px cells, searched out to a third of the page's long
# edge on either side of a mark.
MARK_LEVEL = 245
ROW_POOL = 8
ROW_REACH = .3
# Punctuation prints as dark as its words: a speck no darker than this is
# judged by a faint mark's shorter row reach (STRAY_ROW_REACH).
SPECK_DARK = 128
# Ink in a straight run longer than this share of the long edge is a rule,
# not a text row's evidence (longer than a heading's strokes at 200 dpi).
RULE_RUN = .02
RULE_RIM = 2
# Stray faint marks: up to this share of the long edge across and pieces
# this share apart joined, measured on a page of at most STRAY_EDGE pixels
# (A4 at 200 dpi), so a larger page keeps the finishing frames' halo inside
# their budget and only ever removes relatively smaller marks. A mark with
# any pixel as strong as STRAY_SHARE of the page's print is print. Below
# that, a mark goes only when it is barely above the camera grain (mean
# contrast under STRAY_GRAIN noise floors), up to the wider share, or when
# it prints too little ink to be read (less than a speck's area of solid
# black), up to the narrower one: a grey page number, a pencil tick or a
# margin note prints a legible amount of ink and stays.
STRAY_BOX = .012
STRAY_FAINT_BOX = .03
STRAY_GAP = .002
STRAY_EDGE = 2339
STRAY_SHARE = .4
STRAY_GRAIN = 4.
STRAY_LEVEL = 200
# A faint mark is punctuation only beside print in its own row; dust in
# a table row a column away from the row's label is still dust.
STRAY_ROW_REACH = .08
STRAY_FAINT_ROW_REACH = .02
# Radius, in nominal pixels, of the ring beside strong print where camera
# glow and JPEG ringing must not be amplified as faint ink.
RING = 8
# Half-width, in nominal pixels, of the cross-section over which a stroke's
# peak contrast is read.
STROKE = 2
# A pixel whose own stroke peaks under RING_SHARE of the strongest print
# within RING is ringing and keeps its exposure tone; full gain returns by
# RING_SHARE + RING_SOFT.
RING_SHARE = .3
RING_SOFT = .2
# Contrast a straight line keeps along RULED_SPAN nominal pixels, above
# twice the grain floor plus RULED_LEVEL, marks a rule rather than glow;
# it counts in full RULED_SOFT levels higher.
RULED_SPAN = 15
RULED_LEVEL = 12
RULED_SOFT = 10
# Darkness the stroke curve takes to solid black, and the coverage ramp of
# print strong enough to reach it: under the low share a pixel is blur,
# over the high one it is the stroke's body.
SOLID = 160
CRISP = (.25, .65)
# The coarse field adds darkness only where it sees this much more print
# contrast than the native closing does (inside print wider than it).
COARSE_MARGIN = 20


def _tiling(scale):
    key = 2 if scale >= UPSAMPLED else 1
    return BILATERAL[key], STEP[key], HALO[key]


def enhance_paper(image, region_mask, cv, np, *, feather=True):
    rgb = np.asarray(image, np.uint8)
    small = image.copy()
    small.thumbnail((512, 512), Image.Resampling.LANCZOS)
    source = np.asarray(small, np.uint8).copy()
    region = cv.resize(np.asarray(region_mask, np.uint8), small.size,
                       interpolation=cv.INTER_NEAREST)
    if not (region > 0).any():
        return image
    # Replicate observed paper into the field's exterior before estimating
    # illumination. A dark desk must not bias the paper's edge exposure.
    outside = (region == 0).astype(np.uint8)
    _, labels = cv.distanceTransformWithLabels(outside, cv.DIST_L2, 5,
                                               labelType=cv.DIST_LABEL_PIXEL)
    paper_pixels = source[region > 0]
    source[outside > 0] = paper_pixels[labels[outside > 0] - 1]
    kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE, (17, 17))
    field = np.empty_like(source)
    for channel in range(3):
        closed = cv.morphologyEx(source[:, :, channel], cv.MORPH_CLOSE, kernel)
        field[:, :, channel] = cv.GaussianBlur(closed, (0, 0), 7)
    if feather:
        distance = cv.distanceTransform((region > 0).astype(np.uint8), cv.DIST_L2, 3)
        region = np.clip(distance * (255 / 3), 0, 255).astype(np.uint8)
    table = np.clip((np.arange(256, dtype=np.float32) - 25) * (255 / 220),
                    0, 255).astype(np.uint8)
    result = np.empty_like(rgb)
    width, height = image.size
    # Closing31px needs a30px halo (dilation followed by erosion).940px cores
    # keep each working tile at most one million
    # pixels. Fields/masks remain thumbnail-sized; no full-resolution float
    # illumination field or alpha mask is allocated.
    step, halo = 940, 30
    ink_kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE, (31, 31))
    for top in range(0, height, step):
        bottom = min(height, top + step)
        for left in range(0, width, step):
            right = min(width, left + step)
            shape = (bottom - top, right - left)
            columns = ((np.arange(left, right, dtype=np.float32) + .5)
                       * small.width / width - .5)
            rows = ((np.arange(top, bottom, dtype=np.float32) + .5)
                    * small.height / height - .5)
            map_x = np.broadcast_to(columns, shape)
            map_y = np.broadcast_to(rows[:, None], shape)
            illumination = cv.remap(field, map_x, map_y, cv.INTER_LINEAR,
                                   borderMode=cv.BORDER_REPLICATE)
            pixels = rgb[top:bottom, left:right]
            adjusted = np.empty_like(pixels)
            for channel in range(3):
                normalized = cv.divide(pixels[:, :, channel],
                    np.maximum(illumination[:, :, channel], 75), scale=245)
                adjusted[:, :, channel] = cv.LUT(normalized, table)
            l, t = max(0, left - halo), max(0, top - halo)
            r, b = min(width, right + halo), min(height, bottom + halo)
            gray = cv.cvtColor(rgb[t:b, l:r], cv.COLOR_RGB2GRAY)
            local_paper = cv.morphologyEx(gray, cv.MORPH_CLOSE, ink_kernel)
            residual = (local_paper.astype(np.int16) - gray.astype(np.int16))[
                top - t:bottom - t, left - l:right - l]
            neutral = cv.cvtColor(adjusted, cv.COLOR_RGB2GRAY).astype(np.float32)
            chroma = np.ptp(adjusted.astype(np.int16), axis=2)
            weight = np.clip((40 - chroma) / 20, 0, 1)
            # Strongly colored ink receives no extra gain. Native fine-stroke
            # evidence gates the gain so blank, broad folds are not darkened.
            illumination_gray = cv.cvtColor(illumination, cv.COLOR_RGB2GRAY)
            stroke = (1.6 * np.maximum(residual.astype(np.float32) - 1, 0)
                      * 245 / np.maximum(illumination_gray, 75))
            deficit = np.minimum(np.minimum(.9 * (255 - neutral), 90), stroke) * weight
            adjusted = np.clip(adjusted.astype(np.float32) - deficit[:, :, None],
                               0, 255).astype(np.uint8)
            alpha = cv.remap(region, map_x, map_y, cv.INTER_LINEAR,
                             borderMode=cv.BORDER_REPLICATE).astype(np.uint16)
            result[top:bottom, left:right] = ((adjusted.astype(np.uint16)
                * alpha[:, :, None] + pixels.astype(np.uint16)
                * (255 - alpha[:, :, None]) + 127) // 255).astype(np.uint8)
    return Image.fromarray(result)


def _frame_shadow(source, cv, np):
    """Dark strips hugging the canvas frame of a full-frame page are desk or lid.

    Cleanup would otherwise print them as a ragged black border. A strip
    qualifies only when it is solid, neutral, at least a little thick, runs
    along most of a frame edge and stays within a few percent of it. A title
    tab, a coloured side band, a border rule or a header bar with white text
    fails one of those tests and keeps its contrast.
    """
    gray = cv.cvtColor(source, cv.COLOR_RGB2GRAY)
    saturation = cv.cvtColor(source, cv.COLOR_RGB2HSV)[:, :, 1]
    height, width = gray.shape
    paper = float(np.percentile(gray, 75))
    # Any strip noticeably darker than the paper counts: a scanner lid is
    # black, but the shading left by an earlier crop is only a little grey.
    dark = (gray.astype(np.int16) < paper - 18).astype(np.uint8)
    count, labels, stats, _ = cv.connectedComponentsWithStats(dark, connectivity=8)
    short = min(height, width)
    limit = max(2, round(short * .035))
    yy, xx = np.mgrid[0:height, 0:width]
    near_frame = (yy < limit) | (yy >= height - limit) | (xx < limit) | (xx >= width - limit)
    shadow = np.zeros(gray.shape, bool)
    for label in range(1, count):
        x, y, w, h, area = stats[label]
        if not (x == 0 or y == 0 or x + w == width or y + h == height):
            continue
        if area < short * .25 or area / max(w, h) < short * .012:
            continue  # Specks, and rules thinner than a lid shadow.
        component = labels == label
        if int((component & ~near_frame).sum()) > area * .02:
            continue
        spans = (component[0].mean() if y == 0 else 0, component[-1].mean() if y + h == height else 0,
                 component[:, 0].mean() if x == 0 else 0, component[:, -1].mean() if x + w == width else 0)
        if max(spans) < .5:
            continue  # A tab or a corner mark, not a lid along the whole edge.
        if float(np.median(saturation[component])) >= 60:
            continue  # A coloured band is print.
        contours, hierarchy = cv.findContours(component.astype(np.uint8), cv.RETR_CCOMP,
                                              cv.CHAIN_APPROX_SIMPLE)
        holes = 0. if hierarchy is None else sum(cv.contourArea(contour)
            for contour, link in zip(contours, hierarchy[0]) if link[3] != -1)
        if holes > area * .01:
            continue  # White text or a pattern inside the band is print.
        shadow |= component
    if shadow.any():
        shadow = cv.dilate(shadow.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    return shadow


def _noise_floor(rgb, source, region, ink_kernel, cv, np, scale=1.):
    """Residual and chroma that camera grain leaves on this page's blank paper.

    Amplitude alone cannot tell faint print from grain, so the page sets its
    own bar: up to eight native 128-px crops from the brightest, flattest
    thumbnail cells go through a stand-in for the tile pipeline (a Gaussian
    for the bilateral, an explicit dilate/erode for the closing, so the
    structural oracles count only the tile calls) and, once print is set
    aside, the 97th percentile of what is left is the floor. A clean render
    measures nothing and keeps the historical floors, so its output does
    not move.
    """
    height, width = rgb.shape[:2]
    crop = 128
    if width < crop or height < crop:
        return NOISE_FLOOR, CHROMA_FLOOR
    small_height, small_width = region.shape
    sx, sy = small_width / width, small_height / height
    cell = (max(1, round(crop * sx)), max(1, round(crop * sy)))
    gray = cv.cvtColor(source, cv.COLOR_RGB2GRAY).astype(np.float32)
    mean = cv.blur(gray, cell)
    spread = np.sqrt(np.maximum(cv.blur(gray * gray, cell) - mean * mean, 0))
    observed = cv.erode(region, np.ones((cell[1], cell[0]), np.uint8))
    xs = np.arange(0, width - crop + 1, crop)
    ys = np.arange(0, height - crop + 1, crop)
    cx = np.clip(np.rint((xs + crop / 2) * sx).astype(int), 0, small_width - 1)
    cy = np.clip(np.rint((ys + crop / 2) * sy).astype(int), 0, small_height - 1)
    grid = np.ix_(cy, cx)
    usable = observed[grid] > 0
    if not usable.any():
        return NOISE_FLOOR, CHROMA_FLOOR
    cell_mean, cell_spread = mean[grid], spread[grid]
    # Shadowed paper carries different grain; judge the noise where the
    # exposure is best, then prefer the cells with the least structure.
    bright = usable & (cell_mean >= np.percentile(cell_mean[usable], 50))
    rows, columns = np.nonzero(bright)
    order = np.lexsort((-cell_mean[bright], cell_spread[bright]))[:8]
    residuals, chromas = [], []
    for row, column in zip(rows[order], columns[order]):
        y0, x0 = int(ys[row]), int(xs[column])
        blurred = cv.GaussianBlur(rgb[y0:y0 + crop, x0:x0 + crop], (0, 0), 1)
        level = cv.cvtColor(blurred, cv.COLOR_RGB2GRAY)
        paper = cv.erode(cv.dilate(level, ink_kernel), ink_kernel)
        residual = paper.astype(np.float32) - level
        reference = np.maximum(np.percentile(blurred.reshape(-1, 3), 75, axis=0), 1)
        normalized = blurred.astype(np.float32) * (255 / reference).astype(np.float32)
        chroma = np.ptp(normalized, axis=2)
        # On a dense form no cell is blank, and its print would pass for
        # grain and raise the floor to the cap. Grain is a tight, low
        # population, so anything well above the crop's median, plus its
        # anti-aliased rim, is print and leaves the sample.
        ink = ((residual > max(12, 4 * float(np.median(residual))))
               | (chroma > max(12, 3 * float(np.median(chroma)))))
        # Faint pencil in every cell sits under that bar and would lift the
        # floor until the strokes it measured were erased. Strokes stand
        # out from the crop's own grain (a robust sigma) as long, thin runs
        # that a 5-px erosion removes; grain over the same bar is short
        # and, on smooth mottling, made of wide blobs, so it stays in the
        # sample. Runs are grown from the 3-sigma cores down to 2 sigma.
        centre = float(np.median(residual))
        spread = 1.4826 * float(np.median(np.abs(residual - centre)))
        low = (residual > centre + max(2 * spread, 1)).astype(np.uint8)
        count, labels, stats, _ = cv.connectedComponentsWithStats(low, connectivity=8)
        seeded = np.zeros(count, bool)
        seeded[np.unique(labels[residual > centre + max(3 * spread, 2)])] = True
        length = stats[:, cv.CC_STAT_WIDTH:cv.CC_STAT_HEIGHT + 1].max(axis=1)
        side = 2 * max(1, round(2 * scale)) + 1
        core = np.bincount(labels[cv.erode(low, np.ones((side, side), np.uint8)) > 0], minlength=count)
        strokes = seeded & (length >= 16 * scale) & (core <= .2 * stats[:, cv.CC_STAT_AREA])
        strokes[0] = False
        ink |= strokes[labels]
        ink = cv.dilate(ink.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        if ink.mean() > .5:
            continue
        residuals.append(residual[~ink])
        chromas.append(chroma[~ink])
    if not residuals:
        return NOISE_FLOOR, CHROMA_FLOOR
    # Residuals are whole levels and one level over the floor already prints
    # at 249 after the stroke gain, so the floor sits a level above the
    # measured grain.
    floor = float(np.clip(np.percentile(np.concatenate(residuals), 97) + 1, NOISE_FLOOR, 12))
    chroma = float(np.clip(np.percentile(np.concatenate(chromas), 97), CHROMA_FLOOR, 12))
    return floor, chroma


def _stroke_curve(np):
    """Extra darkness per cleaned neutral level, as a float LUT.

    Scanner apps print text bold. Up to 40 levels of darkness nothing moves,
    so faint print and anti-aliased edges keep their tone; beyond it a cubic
    Hermite segment (slope 1 at 40, slope 0 at 160) rises to solid black at
    160. The table holds only the increase, so a stroke is never lighter
    than before and the pre-curve arithmetic stays exact where it is zero.
    """
    darkness = 255 - np.arange(256, dtype=np.float32)
    t = np.clip((darkness - 40) / 120, 0, 1)
    curved = np.minimum(40 + 120 * t + t * t * (405 - 310 * t), 255)
    return np.where(darkness > 40, curved - darkness, 0).astype(np.float32)


def _finish_tiling(long_edge, scale, stray=False):
    """Core step and halo of the despeckle/sharpen frames for a page size.

    The halo must hold a core speck's whole isolation window, and the
    sharpening may only read halo pixels whose despeckle decision was
    complete, so a mark comes out the same wherever a seam falls. Twenty
    pixels cover both up to a 1200-px page; a larger page widens the halo
    and the core shrinks to keep the frame inside the budget.

    With the stray faint-mark pass (``stray``) a mark the frame cuts counts
    as print, so the halo also holds two of the largest stray marks: a mark
    reaching from a candidate's window to the frame's edge is then larger
    than any stray mark, print in every frame alike. The stray geometry is
    capped (STRAY_EDGE), so that halo fits the frame at any page size; the
    rows carried from one band to the next need the halo within the step.
    """
    box = max(2, round(long_edge * .004))
    reach = max(1, round(long_edge * .008))
    sigma = .8 * scale
    radius = (int(round(6 * sigma + 1)) | 1) // 2
    halo = max(20, box + reach + radius)
    if stray:
        _, wide, gap = _stray_geometry(long_edge)
        halo = max(halo, 2 * wide + gap + box + radius)
    step = FINISH_BUDGET - 2 * halo
    if step < halo:
        raise ValueError(f'finishing halo {halo} does not fit a {long_edge}-px page')
    return step, halo


def _stray_geometry(long_edge):
    """Largest faint and near-grain stray marks, and the gap joining pieces."""
    long_edge = min(long_edge, STRAY_EDGE)
    return (max(4, round(long_edge * STRAY_BOX)), max(4, round(long_edge * STRAY_FAINT_BOX)),
            max(1, round(long_edge * STRAY_GAP)))


def _rule_runs(dark, run, np):
    """Pixels of ``dark`` in runs of at least ``run`` down the first axis.

    A leaning rule drifts across the second axis, so a pixel of slack either
    side keeps its run whole, and the run is spread back over that slack so
    the rule's own pixels are all covered.
    """
    count, across = dark.shape
    if count < run:
        return np.zeros(dark.shape, bool)
    slack = dark.copy()
    slack[:, 1:] |= dark[:, :-1]
    slack[:, :-1] |= dark[:, 1:]
    sums = np.zeros((count + 1, across), np.int32)
    np.cumsum(slack, axis=0, out=sums[1:])
    full = (sums[run:] - sums[:-run]) == run
    starts = np.zeros((count + 1, across), np.int32)
    np.cumsum(np.pad(full, ((0, run - 1), (0, 0))), axis=0, out=starts[1:])
    covered = np.zeros(dark.shape, bool)
    covered[run - 1:] = (starts[run:] - starts[:-run]) > 0
    covered[:run - 1] = starts[1:run] > 0
    covered[:, 1:] |= covered[:, :-1].copy()
    covered[:, :-1] |= covered[:, 1:].copy()
    return covered & dark


def _row_ink(result, np):
    """Integral of dark ink per row in 8-px column cells, for the whole page.

    Print sits in text rows; dust does not care where it lands. Whether a
    small mark shares its row with other print is a page-wide question, too
    wide for a despeckle frame's halo, so it is answered once here from the
    page before any frame changes it, and every frame reads the same answer
    wherever its seams fall. Rows are kept exact and columns pooled, which
    keeps the table at an eighth of the page; it is built a band of rows at
    a time in numpy, so no OpenCV array exceeds the budget.

    Rules say nothing about text: a vertical rule crosses every row it
    spans, and a horizontal one runs past every speck beside it. Ink in a
    straight run longer than any glyph stroke does not count, or dust
    anywhere in a ruled table would share a "row" with its borders. Those
    rules, with their rim, also come back as a page mask, so a speck is not
    kept merely for lying beside one either (see _despeckle).
    """
    height, width = result.shape[:2]
    cells = -(-width // ROW_POOL)
    pooled = np.zeros((height, cells), np.int32)
    ruled = np.zeros((height, width), bool)
    weights = np.array([299, 587, 114], np.int32)
    run = max(3, round(max(height, width) * RULE_RUN))
    for top in range(0, height, 256):
        first, last = max(0, top - run + 1), min(height, top + 256 + run - 1)
        dark = (result[first:last].astype(np.int32) @ weights) < 200 * 1000
        rules = _rule_runs(dark, run, np) | _rule_runs(dark.T, run, np).T
        # The rules with their anti-aliased rim, RULE_RIM pixels either side.
        rim = rules.copy()
        for _ in range(RULE_RIM):
            rim[1:] |= rim[:-1].copy()
            rim[:-1] |= rim[1:].copy()
            rim[:, 1:] |= rim[:, :-1].copy()
            rim[:, :-1] |= rim[:, 1:].copy()
        ruled[top:top + 256] = rim[top - first:top - first + 256]
        dark = (dark & ~rules)[top - first:top - first + 256]
        padded = np.zeros((len(dark), cells * ROW_POOL), bool)
        padded[:, :width] = dark
        pooled[top:top + 256] = padded.reshape(len(dark), cells, ROW_POOL).any(axis=2)
    integral = np.zeros((height + 1, cells + 1), np.int32)
    np.cumsum(np.cumsum(pooled, axis=0), axis=1, out=integral[1:, 1:])
    return integral, ruled


def _in_print_row(np, rows, origin, long_edge, x, y, w, h, box, reach, area_limit, row_reach=ROW_REACH):
    """Whether each mark shares its text row with other print (see _row_ink).

    Ink in the mark's text row, a glyph height above and below, out to
    ``row_reach`` of the page either side, less the mark's own window. Counted in
    pooled cells, so another speck or two cannot reach the bar while one
    word passes it.
    """
    top, left = origin
    last_row, last_cell = rows.shape[0] - 1, rows.shape[1] - 1
    band_top = np.clip(top + y - box, 0, last_row)
    band_bottom = np.clip(top + y + h + box, 0, last_row)
    span = round(long_edge * row_reach)

    def cells(first, last):
        first = np.clip((left + first) // ROW_POOL, 0, last_cell)
        last = np.clip(-(-(left + last) // ROW_POOL), 0, last_cell)
        return (rows[band_bottom, last] - rows[band_top, last]
                - rows[band_bottom, first] + rows[band_top, first])

    own = cells(x - reach, x + w + reach)
    whole = cells(x - span, x + w + span)
    return whole - own > area_limit


def _despeckle(frame, long_edge, cv, np, rows=None, origin=(0, 0), evidence=None, faint=None,
               floor=NOISE_FLOOR, ruled=None):
    """Whiten isolated neutral specks and stray faint marks in a frame, in place.

    Dust is small, neutral and alone: a period after a word has the word's
    last glyph inside its window and stays. A window that leaves the frame
    cannot be judged here, and the frame whose core holds that speck has
    it in full, so skipping it changes nothing.

    A mark is the whole run of pixels darker than near-white, so the dark
    core of a faint grey glyph belongs to its glyph and is never a speck of
    its own. A mark that shares its row with print within a third of the
    page (``rows``, from ``_row_ink``; ``origin`` places the frame on the
    page) is print too: a nil-value hyphen, a bullet before its item, a
    comma, the dots of a fill-in line.

    ``evidence`` is the source contrast behind the frame, ``faint`` the
    contrast from which a mark is print for this page and ``floor`` the
    page's grain floor (see ``cleanup_paper``). A faint mark may be larger
    than a speck, up to a smudged bracket, and its pieces a few pixels apart
    count as one mark; alone on blank paper, outside any row of print, it
    goes when it is barely above the grain or too slight to be read (see
    STRAY_GRAIN). Anything that prints a legible amount of ink stays.
    """
    box = max(2, round(long_edge * .004))
    area_limit = max(4, 10 * (long_edge / 1000) ** 2)
    reach = max(1, round(long_edge * .008))
    gray = cv.cvtColor(frame, cv.COLOR_RGB2GRAY)
    marks = (gray < MARK_LEVEL).astype(np.uint8)
    count, labels, stats, _ = cv.connectedComponentsWithStats(marks, connectivity=8)
    if count < 2:
        return
    height, width = marks.shape
    # Dust beside a table rule (``ruled``, from _row_ink) is as alone as on
    # blank paper: the rule is no word for it to punctuate.
    integral = cv.integral(marks if ruled is None else (marks & ~ruled).astype(np.uint8))
    chroma = np.ptp(frame.astype(np.int16), axis=2)
    x, y = stats[:, cv.CC_STAT_LEFT], stats[:, cv.CC_STAT_TOP]
    w, h, area = stats[:, cv.CC_STAT_WIDTH], stats[:, cv.CC_STAT_HEIGHT], stats[:, cv.CC_STAT_AREA]
    small = (w <= box) & (h <= box) & (area <= area_limit)
    small[0] = False
    inside = (x >= reach) & (y >= reach) & (x + w + reach <= width) & (y + h + reach <= height)
    candidates = np.flatnonzero(small & inside)
    # Only a mark with a dark core is visible dust; a faint smudge is left
    # to the faint pass, which judges it by its source contrast.
    dark_core = np.bincount(labels[gray < 200], minlength=count) > 0
    candidates = candidates[dark_core[candidates]]
    if candidates.size:
        x0, y0 = x[candidates] - reach, y[candidates] - reach
        x1, y1 = x[candidates] + w[candidates] + reach, y[candidates] + h[candidates] + reach
        nearby = integral[y1, x1] - integral[y0, x1] - integral[y1, x0] + integral[y0, x0]
        isolated = candidates[nearby == area[candidates]]
        if rows is not None and isolated.size:
            # A mid-grey speck needs print closer by in its row (SPECK_DARK).
            darkest = np.full(count, 255, np.int32)
            np.minimum.at(darkest, labels.ravel(), gray.ravel())
            keep = np.zeros(isolated.size, bool)
            reaches = np.where(darkest[isolated] < SPECK_DARK, ROW_REACH, STRAY_ROW_REACH)
            for row_reach in np.unique(reaches):
                chosen = reaches == row_reach
                keep[chosen] = _in_print_row(np, rows, origin, long_edge, x[isolated[chosen]], y[isolated[chosen]],
                                             w[isolated[chosen]], h[isolated[chosen]], box, reach, area_limit,
                                             float(row_reach))
            isolated = isolated[~keep]
        tint = np.bincount(labels.ravel(), weights=chroma.ravel(), minlength=count)[isolated]
        specks = isolated[tint < 20 * area[isolated]]
        if specks.size:
            remove = np.zeros(count, bool)
            remove[specks] = True
            frame[remove[labels]] = 255
            marks[remove[labels]] = 0
    if evidence is None or faint is None:
        return
    stray, wide, gap = _stray_geometry(long_edge)
    # Light mottle would chain a mark to everything near it, so marks here
    # are what stands out of it. A mark is print when it is as strong as
    # the page's print or larger than any stray mark, and so is one the
    # frame cuts: the halo is wide enough that such a mark is larger than
    # any stray mark wherever it reaches a candidate's window, so every
    # frame classifies it alike.
    visible = marks & (gray < STRAY_LEVEL).astype(np.uint8)
    count, labels, stats, _ = cv.connectedComponentsWithStats(visible, connectivity=8)
    if count < 2:
        return
    ink = visible > 0
    firm = np.bincount(labels[ink & (evidence >= faint)], minlength=count) > 0
    x, y = stats[:, cv.CC_STAT_LEFT], stats[:, cv.CC_STAT_TOP]
    w, h = stats[:, cv.CC_STAT_WIDTH], stats[:, cv.CC_STAT_HEIGHT]
    printed = (firm | (np.maximum(w, h) > wide)
               | (x == 0) | (y == 0) | (x + w == width) | (y + h == height))
    printed[0] = False
    faint_ink = ink & ~printed[labels]
    if not faint_ink.any():
        return
    # Pieces of one faint mark (a smudged bracket) a few pixels apart are
    # judged together.
    grouped = cv.dilate(faint_ink.astype(np.uint8), np.ones((2 * gap + 1, 2 * gap + 1), np.uint8))
    count, groups, stats, _ = cv.connectedComponentsWithStats(grouped, connectivity=8)
    # The dilation grows every bounding box by exactly the gap, except
    # where the frame clips it, and those groups fail the window test.
    x, y = stats[:, cv.CC_STAT_LEFT] + gap, stats[:, cv.CC_STAT_TOP] + gap
    w, h = stats[:, cv.CC_STAT_WIDTH] - 2 * gap, stats[:, cv.CC_STAT_HEIGHT] - 2 * gap
    inside = (x >= box) & (y >= box) & (x + w + box <= width) & (y + h + box <= height)
    area = np.bincount(groups[faint_ink], minlength=count)
    # Every piece is under the page's bar at its peak; how faint the mark
    # is overall is its mean, which one dark pixel does not decide.
    contrast = (np.bincount(groups[faint_ink], weights=evidence[faint_ink], minlength=count)
                / np.maximum(area, 1))
    # Ink a mark prints, in pixels of solid black: a glyph, a tick or a
    # cross prints more than a speck's area of it.
    mass = np.bincount(groups[faint_ink], weights=(255. - gray[faint_ink]) / 255, minlength=count)
    # A mark barely above the grain may be as large as a crease's short
    # streak or show-through; a firmer one goes only when it is too slight
    # to be read.
    size = np.maximum(w, h)
    very_faint = contrast < STRAY_GRAIN * floor
    candidates = inside & (area > 0) & (((size <= stray) & (mass < area_limit))
                                        | ((size <= wide) & very_faint))
    candidates[0] = False
    candidates = np.flatnonzero(candidates)
    if not candidates.size:
        return
    # Alone means no print within a speck's width; other faint marks
    # there are dust of the same kind and are judged on their own.
    strong = cv.integral((ink & printed[labels]).astype(np.uint8))
    x0, y0 = x[candidates] - box, y[candidates] - box
    x1, y1 = x[candidates] + w[candidates] + box, y[candidates] + h[candidates] + box
    nearby = strong[y1, x1] - strong[y0, x1] - strong[y1, x0] + strong[y0, x0]
    isolated = candidates[nearby == 0]
    if rows is not None and isolated.size:
        # The fainter the mark, the closer its row's print must be.
        reaches = np.where(very_faint[isolated], STRAY_FAINT_ROW_REACH, STRAY_ROW_REACH)
        keep = np.zeros(isolated.size, bool)
        for row_reach in np.unique(reaches):
            chosen = reaches == row_reach
            keep[chosen] = _in_print_row(np, rows, origin, long_edge, x[isolated[chosen]], y[isolated[chosen]],
                                         w[isolated[chosen]], h[isolated[chosen]], box, box, area_limit,
                                         float(row_reach))
        isolated = isolated[~keep]
    if not isolated.size:
        return
    tint = np.bincount(groups[faint_ink], weights=chroma[faint_ink], minlength=count)[isolated]
    stray_marks = isolated[tint < 20 * area[isolated]]
    if stray_marks.size:
        remove = np.zeros(count, bool)
        remove[stray_marks] = True
        # The light rim and pale pieces around the mark go with it. They
        # lie inside its isolation window, where there is no print.
        rim = cv.dilate((faint_ink & remove[groups]).astype(np.uint8),
                        np.ones((2 * box + 1, 2 * box + 1), np.uint8))
        frame[rim > 0] = 255


def _finish(result, scale, cv, np, evidence=None, faint=None, floor=NOISE_FLOOR):
    """Despeckle and sharpen the cleaned page in place, frame by frame.

    Each frame is a core plus a halo; the core is written back, the halo
    only read. Writing in place would let a later frame read its left and
    upper neighbours already sharpened, so a copy of the current band of
    rows serves the whole row, and its bottom halo rows are kept for the
    next band. Sharpening works on luminance, lifted equally in every
    channel so hue is untouched, and leaves white paper alone.
    ``evidence`` and ``faint`` enable the stray faint-mark pass, which
    reads the page's grain ``floor``.
    """
    height, width = result.shape[:2]
    long_edge = min(max(width, height), FINISH_EDGE)
    step, halo = _finish_tiling(long_edge, scale, evidence is not None and faint is not None)
    sigma = .8 * scale
    rows, ruled = _row_ink(result, np)
    above = None
    for top in range(0, height, step):
        bottom = min(height, top + step)
        t, b = max(0, top - halo), min(height, bottom + halo)
        band = result[t:b].copy()
        if above is not None:
            band[:top - t] = above
        above = band[bottom - halo - t:bottom - t].copy() if bottom < height else None
        for left in range(0, width, step):
            right = min(width, left + step)
            l, r = max(0, left - halo), min(width, right + halo)
            frame = band[:, l:r].copy()
            _despeckle(frame, long_edge, cv, np, rows, (t, l),
                       None if evidence is None else evidence[t:b, l:r], faint, floor, ruled[t:b, l:r])
            gray = cv.cvtColor(frame, cv.COLOR_RGB2GRAY)
            blurred = cv.GaussianBlur(gray, (0, 0), sigma)
            lift = .4 * (gray.astype(np.float32) - blurred.astype(np.float32))
            lift[gray >= 250] = 0
            ys, xs = slice(top - t, bottom - t), slice(left - l, right - l)
            result[top:bottom, left:right] = np.clip(np.rint(
                frame[ys, xs] + lift[ys, xs, None]), 0, 255).astype(np.uint8)


def cleanup_paper(image, *, paper_mask=None, frame_guard=False, exterior=None,
                  scale=1.0, cv=None, np=None):
    """Clean a selected rectangular document without recreating its writing.

    Broad illumination and fine neutral paper texture become white. Dark and
    colored source strokes receive a monotonic contrast adjustment. This API
    is for a rectified document canvas; enhancement-only photos keep using
    ``enhance_paper`` so their surrounding scene remains unchanged.

    Tone follows strokes, not pixels: faint print is gained (on a grainy
    page, contrast barely above the grain ramps in), print strong
    enough to reach black is drawn crisp from its own peak, glow beside
    bold print keeps its exposure tone, and every switch between those is
    a smooth weight, so a faint rule prints as one solid line. Small faint
    marks alone on blank paper and outside any row of print are removed in
    the finishing pass when they are barely above the grain or too slight
    to read; legible grey print and pencil stay.

    ``exterior`` marks desk left outside the traced page edge and is
    whitened like a lid strip; ``scale`` is the factor the page was
    upsampled by, which widens the grain neighbourhood and the sharpening.
    """
    if cv is None or np is None:
        from processors.document_scan import _numeric
        cv, np = _numeric()
    if image.width * image.height > 40_000_000:
        return image
    rgb = np.asarray(image, np.uint8)
    small = image.copy()
    small.thumbnail((512, 512), Image.Resampling.LANCZOS)
    source = np.asarray(small, np.uint8).copy()
    if paper_mask is None:
        region = np.full((small.height, small.width), 255, np.uint8)
        if frame_guard:
            region[_frame_shadow(source, cv, np)] = 0
    else:
        # Accept a native caller mask without passing its full canvas to an
        # OpenCV operation. Only the bounded selection is needed below.
        region = np.asarray(Image.fromarray(np.asarray(paper_mask, np.uint8))
                            .resize(small.size, Image.Resampling.NEAREST)).copy()
    if exterior is not None:
        # The fringe takes the lid-strip route, not the paper mask's: a
        # paper mask switches the colour field and the solid-print logic.
        # Any coverage counts, so a rim thinner than a thumbnail pixel is
        # still zeroed rather than averaged away; a 0/1 or boolean mask is
        # lifted to 255 first so its box average cannot round down to zero.
        fringe = np.asarray(Image.fromarray((np.asarray(exterior) > 0).astype(np.uint8) * 255)
                            .resize(small.size, Image.Resampling.BOX))
        region[fringe > 0] = 0
    if not (region > 0).any():
        return Image.new('RGB', image.size, 'white')
    outside = (region == 0).astype(np.uint8)
    _, labels = cv.distanceTransformWithLabels(outside, cv.DIST_L2, 5,
                                               labelType=cv.DIST_LABEL_PIXEL)
    source[outside > 0] = source[region > 0][labels[outside > 0] - 1]
    # A printed solid cell can cover the illumination footprint completely.
    # Keep independently dark source ink rather than letting that cell become
    # its own "paper" reference and normalize to white.
    paper_reference = np.percentile(source[region > 0], 75, axis=0)
    neutral_reference = float(np.dot(paper_reference, (.299, .587, .114)))
    illumination = np.empty_like(source)
    field_kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE, (17, 17))
    for channel in range(3):
        closed = cv.morphologyEx(source[:, :, channel], cv.MORPH_CLOSE, field_kernel)
        illumination[:, :, channel] = cv.GaussianBlur(closed, (0, 0), 5)
    result = np.empty_like(rgb)
    width, height = image.size
    # Bilateral radius + closing radius + smoothing radius + the widest
    # read of the contrast after them (the ring, or the straight-line rule
    # evidence) fit the halo, and step + 2 * halo = 1000, so every native
    # OpenCV array remains <= 1M pixels.
    bilateral, step, halo = _tiling(scale)
    # The smaller field follows crease texture instead of amplifying it as ink.
    # Its footprint scales with the document canvas, so high-resolution source
    # glyphs are not lost merely because their strokes span more pixels.
    footprint = max(9, min(31, round(min(width, height) / 100) | 1))
    ink_kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE, (footprint, footprint))
    floor, chroma_floor = _noise_floor(rgb, source, region, ink_kernel, cv, np, scale)
    knee = KNEE * (floor - NOISE_FLOOR)
    # Those reads stay inside the halo at any scale (a 3x page, or a closing
    # footprint at its cap, shortens them), so seams stay exact.
    budget = halo - bilateral[0] // 2 - footprint // 2 - 3
    reach = min(round(RING * scale), budget)
    span = min(2 * round(RULED_SPAN * scale) + 1, budget)
    curve = _stroke_curve(np)
    # Source contrast behind every pixel, and how strongly the page's own
    # print stands out (the stroke peaks of what prints as ink), for the
    # stray faint-mark pass.
    evidence = np.zeros((height, width), np.uint8)
    print_peaks = np.zeros(256, np.int64)
    for top in range(0, height, step):
        bottom = min(height, top + step)
        for left in range(0, width, step):
            right = min(width, left + step)
            l, t = max(0, left - halo), max(0, top - halo)
            r, b = min(width, right + halo), min(height, bottom + halo)
            native_shape = (b - t, r - l)
            native_columns = ((np.arange(l, r, dtype=np.float32) + .5)
                              * small.width / width - .5)
            native_rows = ((np.arange(t, b, dtype=np.float32) + .5)
                           * small.height / height - .5)
            native_maps = (np.broadcast_to(native_columns, native_shape),
                           np.broadcast_to(native_rows[:, None], native_shape))
            observed = cv.remap(region, *native_maps, cv.INTER_NEAREST,
                                borderMode=cv.BORDER_REPLICATE) > 0
            if not observed.any():
                result[top:bottom, left:right] = 255
                continue
            working = rgb[t:b, l:r]
            if not observed.all():
                # Unknown white canvas is not an illumination measurement.
                # Replicating nearest photographed paper before native closing
                # prevents a paper/frame transition from becoming a fake ink
                # outline; the same pixels are made white again on output.
                exterior_cells = (~observed).astype(np.uint8)
                # A bounded mask cell may overlap a few already-white donor
                # pixels at a missing-source boundary. Those pixels provide no
                # photographic illumination either. Limit this correction to
                # pure white right beside independently unknown canvas.
                beside_unknown = cv.dilate(exterior_cells, np.ones((7, 7), np.uint8)) > 0
                pure_white = np.all(working == 255, axis=2)
                field_region = observed & ~(beside_unknown & pure_white)
                if not field_region.any():
                    result[top:bottom, left:right] = 255
                    continue
                exterior_cells = (~field_region).astype(np.uint8)
                _, nearest = cv.distanceTransformWithLabels(exterior_cells, cv.DIST_L2,
                    5, labelType=cv.DIST_LABEL_PIXEL)
                working = working.copy()
                working[~field_region] = working[field_region][nearest[~field_region] - 1]
            # Small edge-preserving color neighborhoods reduce camera grain.
            # No opening/erosion/connected-component removal is applied to ink.
            smooth = cv.bilateralFilter(working, *bilateral)
            gray = cv.cvtColor(smooth, cv.COLOR_RGB2GRAY)
            reference = smooth
            if paper_mask is not None and not observed.all():
                # Color/gray fields need the same observed-material donors.
                # Remove only a2px boundary band from the reference, never
                # from the source strokes being rendered.
                core = cv.erode(field_region.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
                if core.any():
                    _, nearest = cv.distanceTransformWithLabels((~core).astype(np.uint8),
                        cv.DIST_L2, 5, labelType=cv.DIST_LABEL_PIXEL)
                    reference = smooth.copy()
                    reference[~core] = reference[core][nearest[~core] - 1]
            reference_gray = cv.cvtColor(reference, cv.COLOR_RGB2GRAY)
            local_paper = cv.morphologyEx(reference_gray, cv.MORPH_CLOSE, ink_kernel)
            local_paper = cv.GaussianBlur(local_paper, (5, 5), .8)
            native_color_field = None
            if paper_mask is not None:
                native_color_field = np.empty_like(reference)
                for channel in range(3):
                    closed = cv.morphologyEx(reference[:, :, channel], cv.MORPH_CLOSE, ink_kernel)
                    native_color_field[:, :, channel] = cv.GaussianBlur(closed, (5, 5), .8)
            contrast = local_paper.astype(np.float32) - gray.astype(np.float32)
            strong_core = ((contrast >= 60) | (gray < neutral_reference * .45)).astype(np.uint8)
            strong_support = cv.dilate(strong_core, np.ones((5, 5), np.uint8)) > 0
            # Every tone decision follows the stroke a pixel belongs to, not
            # the pixel alone, so one stroke never switches between two
            # mappings along its length. ``near`` is the peak contrast across
            # the stroke's own cross-section and ``far`` the strongest print
            # a ring's width away (compression rings mottle the paper there).
            # Bold print wider than the closing footprint has no contrast
            # against its own local paper; its darkness against the page's
            # paper stands in, as it does for the solid ramp below.
            solid = np.clip((neutral_reference * .45 - gray.astype(np.float32))
                            / max(neutral_reference * .2, 1), 0, 1)
            peak = np.maximum(contrast, solid * (neutral_reference - gray.astype(np.float32)))
            near = cv.dilate(peak, cv.getStructuringElement(
                cv.MORPH_ELLIPSE, (2 * max(1, round(STROKE * scale)) + 1,) * 2))
            far = cv.dilate(peak, cv.getStructuringElement(cv.MORPH_ELLIPSE, (2 * reach + 1,) * 2))
            ridge = cv.dilate(peak, np.ones((3, 3), np.uint8))
            # The weakest contrast along a straight run (an opening along
            # the line, after a pixel of slack across it for a leaning rule).
            line = np.maximum(
                cv.morphologyEx(cv.dilate(contrast, np.ones((3, 1), np.uint8)), cv.MORPH_OPEN,
                                np.ones((1, span), np.uint8)),
                cv.morphologyEx(cv.dilate(contrast, np.ones((1, 3), np.uint8)), cv.MORPH_OPEN,
                                np.ones((span, 1), np.uint8)))
            # Repeated parallel high-contrast edges (for example barcodes) need
            # their original narrow light spaces. This generic source-pattern
            # evidence is independent of decoded text or any document layout.
            gx = cv.Sobel(gray, cv.CV_32F, 1, 0, ksize=3)
            gy = cv.Sobel(gray, cv.CV_32F, 0, 1, ksize=3)
            a = cv.boxFilter(gx * gx, -1, (21, 21))
            b = cv.boxFilter(gy * gy, -1, (21, 21))
            cross = cv.boxFilter(gx * gy, -1, (21, 21))
            coherence = np.sqrt((a - b) ** 2 + 4 * cross ** 2) / (a + b + 1)
            dark = (gray < neutral_reference * .65).astype(np.int8)
            transitions = np.zeros(gray.shape, np.float32)
            transitions[:, 1:] += np.abs(np.diff(dark, axis=1))
            transitions[1:] += np.abs(np.diff(dark, axis=0))
            stripes = ((coherence > .86)
                       & (cv.boxFilter(transitions, -1, (21, 21)) > .20))
            stripes &= strong_support
            ys, xs = slice(top - t, bottom - t), slice(left - l, right - l)
            pixels = smooth[ys, xs]
            gray = gray[ys, xs]
            local_paper = local_paper[ys, xs]
            contrast, near, far, solid = contrast[ys, xs], near[ys, xs], far[ys, xs], solid[ys, xs]
            ridge = ridge[ys, xs]
            line = line[ys, xs]
            evidence[top:bottom, left:right] = np.clip(peak[ys, xs], 0, 255)
            shape = (bottom - top, right - left)
            columns = ((np.arange(left, right, dtype=np.float32) + .5)
                       * small.width / width - .5)
            rows = ((np.arange(top, bottom, dtype=np.float32) + .5)
                    * small.height / height - .5)
            maps = (np.broadcast_to(columns, shape), np.broadcast_to(rows[:, None], shape))
            field = cv.remap(illumination, *maps, cv.INTER_LINEAR,
                             borderMode=cv.BORDER_REPLICATE)
            color_field = field if native_color_field is None else native_color_field[ys, xs]
            normalized = np.empty_like(pixels)
            for channel in range(3):
                normalized[:, :, channel] = cv.divide(pixels[:, :, channel],
                    np.maximum(color_field[:, :, channel], max(75, round(paper_reference[channel] * .5))), scale=255)
            normalized_gray = cv.cvtColor(normalized, cv.COLOR_RGB2GRAY).astype(np.float32)
            # The native paper field follows broad smooth folds rather than
            # treating their shading as a written character. The page's own
            # grain sets the noise floor; genuine faint strokes remain a
            # continuous luminance residual, not a binary/OCR replacement.
            residual = np.maximum(contrast - floor, 0)
            if knee > 0:
                # Barely over a grainy page's floor is as likely grain (KNEE).
                residual = residual * np.minimum(1, residual / knee)
            gain = 4.5 * 245 / np.maximum(local_paper, 75)
            darkness = residual * gain
            # Faint print takes the gain whole. Print whose peak the gain
            # takes past black is drawn crisp from its own peak instead: the
            # share of that peak a pixel reaches (coverage) is ramped through
            # half, so the core prints solid, the camera's blur around it
            # does not fatten it, and a faint rule whose contrast wanders
            # along its length stays one solid line. The two blend smoothly
            # with the peak's strength, so no stroke flips between mappings.
            coverage = residual / np.maximum(near - floor, 1)
            crisp = SOLID * np.clip((coverage - CRISP[0]) / (CRISP[1] - CRISP[0]), 0, 1)
            strength = np.clip((near - floor) * gain / SOLID - 1, 0, 1)
            darkness = darkness + strength * (np.minimum(crisp, darkness) - darkness)
            # Mottle much fainter than print a few pixels away is camera
            # glow or compression ringing: it keeps no more than its
            # exposure contrast. The weight runs smoothly with the share of
            # the neighbour's strength, so print beside print (a faint rule
            # passing bold text) is not cut where it passes a glyph.
            exposure = residual * 255 / np.maximum(local_paper, 75)
            ringing = np.clip((ridge / np.maximum(far, 1) - RING_SHARE) / RING_SOFT, 0, 1)
            # A rule is print wherever it runs, even past bold text: glow
            # never holds its contrast along a straight line that long.
            ringing = np.maximum(ringing, np.clip((line - 2 * floor - RULED_LEVEL) / RULED_SOFT, 0, 1))
            darkness = np.where(darkness > exposure, exposure + ringing * (darkness - exposure), darkness)
            coarse_gray = cv.cvtColor(color_field, cv.COLOR_RGB2GRAY).astype(np.float32)
            coarse_dark = np.maximum(coarse_gray - gray.astype(np.float32), 0)
            # Large dark logos/filled printed cells can exceed the native
            # closing footprint; retain their independently strong contrast.
            # Only there: where the native contrast already sees the print
            # (every stroke narrower than the footprint), the coarse field
            # would only fatten it past its own anti-aliased edge.
            strong = (np.clip((coarse_dark - 35) / 25, 0, 1)
                      * np.clip((coarse_dark - contrast - COARSE_MARGIN) / COARSE_MARGIN, 0, 1))
            darkness = np.maximum(darkness, coarse_dark * 245
                                  / np.maximum(coarse_gray, 75) * strong * 2)
            # Barcode stripes need their narrow light spaces: they keep the
            # original exposure contrast, neither gained nor drawn crisp.
            darkness = np.where(stripes[ys, xs], 255 - normalized_gray, darkness)
            darkness = np.maximum(darkness, solid * 255)
            neutral = np.clip(255 - darkness, 0, 255)
            # Barcode bars keep their exposure contrast: bolder bars would
            # close the narrow spaces the curve is meant to leave alone.
            extra = cv.LUT(neutral.astype(np.uint8), curve)
            extra[stripes[ys, xs]] = 0
            neutral = neutral - extra
            print_peaks += np.bincount(np.clip(near[neutral < 128], 0, 255).astype(np.uint8),
                                       minlength=256)
            chroma = np.ptp(normalized.astype(np.int16), axis=2)
            # Neutral camera grain needs no residual paper tint. A color
            # difference credible against the page's own chroma noise still
            # protects faint colored pen ink.
            # On what prints as paper colour must stand out further (TINT).
            lift = TINT * np.clip((neutral - 235) / 15, 0, 1)
            color_weight = np.clip((chroma.astype(np.float32) - chroma_floor - lift) / 8, 0, 1)
            # Move color brightness toward the cleaned paper/ink luminance,
            # bounded by its available RGB headroom. A shared offset preserves
            # hue and channel span without letting a slight paper tint retain
            # broad gray folds or make neutral printed strokes pale.
            shift = np.clip(neutral - normalized_gray,
                            -normalized.min(axis=2).astype(np.float32),
                            255 - normalized.max(axis=2).astype(np.float32))
            colored = normalized.astype(np.float32) + shift[:, :, None]
            cleaned = np.clip(colored * color_weight[:, :, None]
                + neutral[:, :, None] * (1 - color_weight[:, :, None]), 0, 255).astype(np.uint8)
            alpha = cv.remap(region, *maps, cv.INTER_NEAREST,
                             borderMode=cv.BORDER_REPLICATE) > 0
            cleaned[~alpha] = 255
            cleaned[np.all(rgb[top:bottom, left:right] == 255, axis=2)] = 255
            result[top:bottom, left:right] = cleaned
    # A mark with a pixel at STRAY_SHARE of the median stroke peak of the
    # page's printed ink is print.
    faint = None
    if print_peaks.sum():
        typical = int(np.searchsorted(np.cumsum(print_peaks), print_peaks.sum() / 2))
        faint = STRAY_SHARE * typical
    _finish(result, scale, cv, np, evidence, faint, floor)
    return Image.fromarray(result)
