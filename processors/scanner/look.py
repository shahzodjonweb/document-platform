"""Stage 5: the final look, a clean colour scan.

Input is the upscaled, shadow-free page with white paper (GC-Net +
whiten_paper). magic() divides out fold lines, whitens fingers holding the
page at its edges, sharpens lightness, makes strokes slightly bolder and
applies a tone curve: paper pure white, print near black. Colour (stamps,
blue ink, logos, coloured print and rulings) is kept: it gets a gentler curve
and a mild vibrance boost instead of being pushed to black.
"""
import cv2
import numpy as np

# Target look: near black-on-white with smooth edges. Measured on a folded form (lightness,
# 0-255, after GC-Net): paper ~246, fold crease ~160-222 (median 192), printed
# ink 10-150, handwriting 37-101.
BOLD = 0.35          # 0 = full one-pixel stroke thickening, 1 = none
# Tone curve: lightness at or below BLACK (share of 255) turns black, at or
# above WHITE turns white, GAMMA darkens the strokes in between; colour gets
# VIBRANCE more saturation.
BLACK, WHITE, GAMMA, VIBRANCE = .12, .90, 1.4, 1.15


def _smoothstep(x, lo, hi):
    t = np.clip((x - lo) / (hi - lo), 0, 1)
    return t * t * (3 - 2 * t)


# Fold lines. Measured on a folded form at 2x: printed rules and box borders
# are 3-5 px wide (darkest 138-178), the fold is 9-14 px wide (darkest
# 136-166). So a fold is a LONG and WIDE soft line; it is removed like a
# shadow (divided out), never erased, so ink crossing it stays.
FOLD_MIN_WIDTH, FOLD_MAX_WIDTH = 7, 25


def _wide_lines(lightness, vertical):
    """Map of long lines 7-25 px wide (folds); thin rules and short strokes drop out."""
    h, w = lightness.shape
    across = (lambda k: cv2.getStructuringElement(cv2.MORPH_RECT, (k, 1))) if vertical else \
             (lambda k: cv2.getStructuringElement(cv2.MORPH_RECT, (1, k)))
    narrow = cv2.morphologyEx(lightness, cv2.MORPH_BLACKHAT, across(FOLD_MIN_WIDTH))
    wide = cv2.morphologyEx(lightness, cv2.MORPH_BLACKHAT, across(FOLD_MAX_WIDTH))
    mask = ((wide - narrow) > 25).astype(np.uint8)
    along = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(15, h // 20)) if vertical else (max(15, w // 20), 1))
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, along) * 255


def remove_folds(lightness):
    """Divide out fold shadows along long, wide, near-straight lines."""
    h, w = lightness.shape
    out = lightness.copy()
    for vertical in (True, False):
        span = h if vertical else w
        found = cv2.HoughLinesP(_wide_lines(lightness, vertical), 1, np.pi / 360, threshold=round(span * .1),
                                minLineLength=round(span * .3), maxLineGap=round(span * .25))
        for x1, y1, x2, y2 in ([] if found is None else found.reshape(-1, 4)):
            along, across = (y2 - y1, x2 - x1) if vertical else (x2 - x1, y2 - y1)
            if along == 0 or abs(np.degrees(np.arctan2(abs(across), abs(along)))) > 8:
                continue  # folds are near-straight and near-axis on a flattened page
            a1, c1 = (y1, x1) if vertical else (x1, y1)
            at = lambda t, a1=a1, c1=c1, along=along, across=across: c1 + across * (t - a1) / along
            _divide_fold(out, lightness, at, vertical)
    return out


def _divide_fold(out, source, at, vertical, radius=30, step=16, window=120):
    """Walk along the line (extended edge to edge), estimate the fold's shadow
    profile from the paper on each side, and divide it out of the paper only:
    a pixel much darker than the fold's own shadow is ink and stays as dark.
    """
    view_out = out if vertical else out.T
    view_src = source if vertical else source.T
    h, w = view_src.shape
    for start in range(0, h, step):
        centre = int(round(at(start + step / 2)))
        lo, hi = max(0, start + step // 2 - window // 2), min(h, start + step // 2 + window // 2)
        x0, x1 = max(0, centre - radius), min(w, centre + radius + 1)
        if x1 - x0 < radius:
            continue
        strip = view_src[lo:hi, x0:x1]
        profile = cv2.GaussianBlur(np.percentile(strip, 90, axis=0)[None], (0, 0), 1.5)[0]
        paper = np.median(np.concatenate([profile[:8], profile[-8:]]))
        dip = int(np.argmin(profile))
        depth = paper - profile[dip]
        if paper < 200 or depth < 12 or profile[dip] < 90:
            continue  # no fold here, or solid ink
        half = profile[dip] + depth / 2
        if int(np.sum(profile < half)) < FOLD_MIN_WIDTH:
            continue  # a thin printed rule, not a fold
        ratio = np.clip(profile / paper, .3, 1)[None]
        rows = slice(start, min(h, start + step))
        block = view_out[rows, x0:x1]
        shadow = paper * ratio                       # what bare paper looks like on the fold
        inkness = _smoothstep(shadow - block, 30, 70)  # 1 = clearly darker than the fold: ink
        view_out[rows, x0:x1] = np.minimum(255, block / ratio * (1 - inkness) + block * inkness)


def ink_colour(lab):
    """0..1: how clearly a mark is coloured ink (red print, blue grid, stamps).

    Measured relative to the page's own black ink (a phone photo tints all
    ink the same way) and over a few pixels, so the camera's colour fringes
    at letter edges cancel out. On the test photos: red print ~0.10, blue
    grid ~0.08, black print 0.01-0.04, carbon handwriting ~0.02.
    """
    a = cv2.GaussianBlur(lab[:, :, 1] - 128, (0, 0), 2.5)
    b = cv2.GaussianBlur(lab[:, :, 2] - 128, (0, 0), 2.5)
    lightness = cv2.GaussianBlur(lab[:, :, 0], (0, 0), 2.5)
    dark = lab[:, :, 0] < 110
    cast_a, cast_b = (np.median(a[dark]), np.median(b[dark])) if dark.sum() > 500 else (0.0, 0.0)
    if np.hypot(cast_a, cast_b) > 12:
        cast_a = cast_b = 0.0  # the page's darkest ink is itself coloured (blue pen): not a camera tint
    darkness = np.clip((255 - lightness) / 255, 0, 1)
    colour = np.hypot(a - cast_a * darkness, b - cast_b * darkness) / (255 - lightness + 15)
    # Only marks can be coloured ink; tinted paper (folds, stains) cannot.
    return _smoothstep(colour, .06, .10) * _smoothstep(235 - lightness, 0, 25)


def ruled_lines(lightness, colour):
    """Mask of coloured ruled lines: notebook grids, coloured form rulings, margin lines.

    Found as long straight runs (41 px at 2x) of marks whose neighbourhood is
    coloured on average; single grid pixels often look grey, so colour is
    judged over 61x61. Handwriting, letters and stamps are not long straight runs.
    """
    background = cv2.GaussianBlur(cv2.dilate(lightness, np.ones((15, 15), np.uint8)), (0, 0), 3)
    marks = (background - lightness > 11).astype(np.float32)
    regional = cv2.blur(colour * marks, (61, 61)) / np.maximum(cv2.blur(marks, (61, 61)), 1e-3)
    runs = ((marks > 0) & (regional > .08)).astype(np.uint8)
    ruled = (cv2.morphologyEx(runs, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (41, 1)))
             | cv2.morphologyEx(runs, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 41))))
    return cv2.dilate(ruled, np.ones((3, 3), np.uint8)) > 0


RULED_LIGHTNESS = 205  # grids and coloured rulings render as an even light tint
RULED_MAX_INK = 160    # grid lines measure 189-225 after shadow removal; pen and print are darker


def remove_thumbs(lab, lightness, band=.06, along=.03):
    """Whiten skin-coloured strips along the page edges (fingers holding the page).

    Measured on the test photos after shadow removal: thumbs are warm
    (a* +5..+9, b* -2..+22) and form a strip narrower than 6% of the page
    along an edge; handwriting at the edge (purple pen, b* about -15) and
    cut-off text (no colour) are never touched.
    """
    h, w = lightness.shape
    a, b = lab[:, :, 1] - 128, lab[:, :, 2] - 128
    count, labels, stats, _ = cv2.connectedComponentsWithStats((lightness < 235).astype(np.uint8), connectivity=8)
    out = lightness.copy()
    for label in range(1, count):
        x, y, bw, bh, area = stats[label]
        side = (x == 0 or x + bw >= w) and bw <= band * w and bh >= along * h
        top = (y == 0 or y + bh >= h) and bh <= band * h and bw >= along * w
        if not (side or top):
            continue
        blob = labels == label
        ma, mb = float(np.median(a[blob])), float(np.median(b[blob]))
        if ma > 4 and mb > -1 and np.hypot(ma, mb) > 7:
            out[blob] = 255
            lab[:, :, 1][blob] = 128
            lab[:, :, 2][blob] = 128
    return out


def magic(clean_white):
    """Final colour look from the GC-Net shadow-free, whitened page.

    Built on the blind-judged winner (clean paper + clarity) and adds only what
    held up on the test photos: folds divided out, skin-coloured thumb strips
    at the edges whitened, slightly bolder strokes, and a tone curve that makes
    paper white and print near black. Coloured lines and print (notebook
    grids, red print, stamps) skip the bolding and get a gentler curve, so a
    grid stays light and even instead of turning grey where the photo was
    darker. Rejected after blind judging: a hard black/white curve; evening
    grey fills (smeared grey banners with text, logos); clearing every blob at
    the edges (erased handwriting and cut-off text touching the edge). Tried
    and left out: strengthening faint strokes (it darkened faint notebook-grid
    pieces into black marks and could not complete the faintest carbon-copy
    strokes).
    """
    lab = cv2.cvtColor(clean_white, cv2.COLOR_BGR2LAB).astype(np.float32)
    lightness = lab[:, :, 0]
    colour = ink_colour(lab)
    lightness = remove_folds(lightness)
    lightness = remove_thumbs(lab, lightness)
    lightness = lightness + 0.6 * (lightness - cv2.GaussianBlur(lightness, (0, 0), 1.3))  # clarity
    lightness = np.clip(lightness, 0, 255)
    bold = np.minimum(lightness, cv2.erode(lightness, np.ones((2, 2), np.uint8)) * (1 - BOLD) + lightness * BOLD)
    level = np.clip((bold - 255 * BLACK) / (255 * (WHITE - BLACK)), 0, 1)
    strong = 255 * level ** GAMMA
    gentle = np.clip((lightness - 255 * .06) / (255 * (.93 - .06)), 0, 1) * 255
    out = strong * (1 - colour) + gentle * colour
    # Notebook grids and coloured rulings: an even light tint everywhere, not
    # darker grey where the photo was more shaded.
    # Only the light grid pixels themselves: handwriting or letters crossing a
    # grid line (and tall letter stems) are dark ink and keep their darkness.
    ruled = ruled_lines(lightness, colour) & (lightness > RULED_MAX_INK)
    out[ruled] = np.maximum(out[ruled], RULED_LIGHTNESS)
    lab[:, :, 0] = out
    lab[:, :, 1:] = 128 + (lab[:, :, 1:] - 128) * VIBRANCE
    return cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)
