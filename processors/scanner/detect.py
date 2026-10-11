"""Stage 1: find the page in a photo with DocAligner and tuned rules.

DocAligner (Apache-2.0, github.com/DocsaidLab/DocAligner) predicts a heatmap
per page corner. On top of it: the photo is padded to a square instead of
squashed, every convex outline from the corner hot spots is ranked by its
weakest corner, a margin view places corners the photo cut off, a zoomed
grid search finds small distant pages, a larger outline wins when it extends
onto the same paper (folds, cut-off corners), and a second, zoomed-in look
sharpens the corners. The networks run through aligner.py.
"""
import cv2
import numpy as np

from . import aligner

# The model looks at a 256x256 image; feeding it a ~1024 px copy gives the
# same corners as the full 12 MP photo at a fraction of the cost.
DETECT_SIDE = 1024
# Room around the photo, as a share of its long side, for cut-off corners.
MARGIN = 0.25
# Room around the page on the zoomed-in second pass, as a share of its size.
REFINE_MARGIN = 0.12
# Weakest-corner confidence needed to call it a page (tuned on a labelled benchmark).
MIN_CONFIDENCE = 0.5
# A larger outline around the chosen one wins (a fold, a cut-off corner) when
# it is at most this much less confident and the extra area is the same
# paper: median colour of the brighter half within this Lab distance. A
# receipt lying on a red sheet must not grow onto the sheet.
GROW_SLACK = 0.4
SAME_PAPER = 18
# Lightness counts this much in that distance: a shadow darkens part of the
# sheet without changing its colour (a hand-held page with a shaded third:
# that third is 32 L darker, same a/b, so the outline cut diagonally through
# the text). On the dev images where grow has a choice, 0.4 gives 82/95 good
# outlines instead of 72 (tune) and 59/83 instead of 51 (check).
PAPER_LIGHTNESS_WEIGHT = 0.4
# The margin view finds pages the plain view misses, but it also outlines
# ordinary photos with a dark or light band along their edges. It is used
# only when DocAligner's presence model (point model's has_obj, on the plain
# photo) says a document is likely: photos without one score a median 0.007.
# 0.3, not 0.5: real bent pages held in a hand score 0.3-0.5 (one such page
# 0.44, its JPEG re-saves and resizes 0.30-0.57). On the dev set's held-out
# half 0.3 gives +0.6 points of good outlines for 0.3% more false alarms;
# padding the photo to a square instead raised false alarms 50%.
MARGIN_PRESENCE = 0.3
# Last resort for a small, distant page: zoomed windows of this share of the
# photo, accepted only at this confidence (empty photos rarely reach it).
GRID_WINDOW = 0.55
GRID_CONFIDENCE = 0.85
# Shape limits for a photographed page. Labelled pages measured 64-141 deg
# corners and opposite sides within 0.51x; the limits leave a wide margin and
# only reject outlines whose corners collapsed onto each other.
ANGLE_RANGE = (50, 150)
MIN_SIDE_RATIO = 0.4
_MODEL = None


def model():
    """DocAligner's heatmap model (fastvit_sa24), loaded once."""
    global _MODEL
    if _MODEL is None:
        _MODEL = aligner.Model(aligner.HEATMAP)
    return _MODEL


def detect(bgr):
    """The page's four corners in full-resolution pixels (float32, 4x2), or None."""
    detector = model()
    height, width = bgr.shape[:2]
    scale = min(1.0, DETECT_SIDE / max(height, width))
    small = cv2.resize(bgr, (max(1, round(width * scale)), max(1, round(height * scale))),
                       interpolation=cv2.INTER_AREA) if scale < 1 else bgr
    # The model sees a square 256x256 input. Squashing a tall phone photo into
    # it distorts the page enough to miss it, so pad to a square instead. The
    # plain view leads; the margin view, which can place a corner the photo
    # cut off, backs it up only when a document is likely.
    h, w = small.shape[:2]
    plain = window_quads(detector, small, w / 2, h / 2, max(h, w))
    margin = (window_quads(detector, small, w / 2, h / 2, max(h, w) * (1 + 2 * MARGIN))
              if presence(small) >= MARGIN_PRESENCE else [])
    for options in (plain, margin):
        if options and options[0][1] >= MIN_CONFIDENCE:
            points = grow(small, options[0][0], options[0][1], plain + margin)
            break
    else:
        options = grid_search(detector, small)
        if not options:
            return None
        points = options[0][0]
    # Second look, zoomed onto the page, so it fills the model's view and
    # the corners land within a few pixels instead of a few dozen.
    low, high = points.min(axis=0), points.max(axis=0)
    center = (low + high) / 2
    options = window_quads(detector, small, *center, max(high - low) * (1 + 2 * REFINE_MARGIN))
    limit = max(high - low) * .15
    moves = [np.linalg.norm(quad - points, axis=1).max() for quad, _ in options]
    # When the top outline jumps away (a cut-off corner snapping to where
    # the page edge leaves the photo), the nearest confident one still
    # sharpens the corners. Dev set: 11 of 13 changed outlines better.
    close = [i for i, (_, confidence) in enumerate(options) if moves[i] < limit
             and (i == 0 or confidence >= MIN_CONFIDENCE)]
    if close:
        points = options[0][0] if close[0] == 0 else options[min(close, key=lambda i: moves[i])][0]
    return points / scale


_PRESENCE = None


def presence_model():
    """DocAligner's point model (its has_obj output scores presence), loaded once."""
    global _PRESENCE
    if _PRESENCE is None:
        _PRESENCE = aligner.Model(aligner.POINT)
    return _PRESENCE


def presence(image):
    """DocAligner's own document-present probability for the whole photo, 0..1."""
    detector = presence_model()
    inputs = aligner.preprocess(image, detector.img_size_infer)['input']
    return float(np.asarray(detector.model(**inputs)['has_obj']).ravel()[0])


def grow(image, quad, confidence, options):
    """The largest outline around ``quad`` that extends it onto the same paper."""
    area = cv2.contourArea(quad)
    larger = sorted((q for q, c in options if c >= confidence - GROW_SLACK
                     and cv2.contourArea(q) > area * 1.1 and contains(q, quad)),
                    key=lambda q: -cv2.contourArea(q))
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32) if larger else None
    for candidate in larger:
        if same_paper(lab, quad, candidate):
            return candidate
    return quad


def contains(outer, inner):
    inside, _ = cv2.intersectConvexConvex(np.float32(outer), np.float32(inner))
    return inside >= cv2.contourArea(inner) * .95


def same_paper(lab, inner, outer):
    h, w = lab.shape[:2]
    inner_mask = np.zeros((h, w), np.uint8)
    cv2.fillPoly(inner_mask, [np.int32(np.round(inner))], 1)
    extra_mask = np.zeros((h, w), np.uint8)
    cv2.fillPoly(extra_mask, [np.int32(np.round(outer))], 1)
    extra_mask[inner_mask > 0] = 0
    paper, extra = paper_colour(lab, inner_mask), paper_colour(lab, extra_mask)
    if paper is None:
        return False
    if extra is None:
        return True  # the extra area lies outside the photo: a cut-off corner
    return float(np.linalg.norm((paper - extra) * [PAPER_LIGHTNESS_WEIGHT, 1, 1])) <= SAME_PAPER


def paper_colour(lab, mask):
    pixels = lab[mask > 0]
    if len(pixels) < 50:
        return None
    # The brighter half is paper rather than print.
    return np.median(pixels[pixels[:, 0] >= np.percentile(pixels[:, 0], 50)], axis=0)


def grid_search(model, image):
    """Look for a small, distant page in overlapping zoomed windows.

    Seen whole, a receipt covering a tenth of the photo barely registers;
    framed by a window it scores above 0.9. A window's page must sit fully
    inside it, so a page cut by the window's edge is not taken for a whole one.
    """
    h, w = image.shape[:2]
    side = max(h, w) * GRID_WINDOW
    found = []
    for fy in (0, .5, 1):
        for fx in (0, .5, 1):
            cx = side / 2 + (w - side) * fx if w > side else w / 2
            cy = side / 2 + (h - side) * fy if h > side else h / 2
            options = window_quads(model, image, cx, cy, side)
            if not options or options[0][1] < GRID_CONFIDENCE:
                continue
            inset = side * .03
            low, high = np.array([cx - side / 2, cy - side / 2]) + inset, np.array([cx + side / 2, cy + side / 2]) - inset
            quad = options[0][0]
            if (quad >= low).all() and (quad <= high).all() and (not found or options[0][1] > found[0][1]):
                found = options
    return found


def window_quads(model, image, center_x, center_y, side):
    """Run the model on a square window of the image; outlines in image coordinates.

    Outside the photo the window repeats the photo's edge pixels. A black
    fill would frame the photo like a bright sheet on a dark desk, and the
    model would outline the photo itself even when it holds no document.
    """
    side = max(32, round(side))
    left, top = round(center_x - side / 2), round(center_y - side / 2)
    h, w = image.shape[:2]
    x0, y0, x1, y1 = max(0, left), max(0, top), min(w, left + side), min(h, top + side)
    if x1 <= x0 or y1 <= y0:
        return []
    square = cv2.copyMakeBorder(image[y0:y1, x0:x1], y0 - top, top + side - y1,
                                x0 - left, left + side - x1, cv2.BORDER_REPLICATE)
    return [(np.float32(quad + [left, top]), confidence) for quad, confidence in quad_options(model, square)]


def corner_candidates(heatmap, side, threshold=0.2, keep=3):
    """Every separate hot spot in one corner's heatmap as (score, point), strongest first."""
    mask = (heatmap >= threshold).astype(np.uint8)
    count, labels = cv2.connectedComponents(mask)
    spots = []
    for label in range(1, count):
        ys, xs = np.nonzero(labels == label)
        weight = heatmap[ys, xs]
        point = np.array([(xs * weight).sum(), (ys * weight).sum()]) / weight.sum()
        spots.append((float(weight.max()), (point + .5) * side / heatmap.shape[0]))
    spots.sort(key=lambda spot: -spot[0])
    return spots[:keep]


def quad_options(model, square):
    """Every convex outline from one candidate per corner, most confident first.

    DocAligner itself keeps only the largest hot spot per corner, which can
    be a fold, or the neighbouring page of a notebook. Confidence is the
    weakest corner's score.
    """
    from itertools import product

    inputs = aligner.preprocess(square, model.img_size_infer)['input']
    heatmaps = model.model(**inputs)['heatmap'][0][:4]
    side = square.shape[0]
    candidates = [corner_candidates(heatmap, side) for heatmap in heatmaps]
    if not all(candidates):
        return []
    options = []
    for combo in sorted(product(*candidates), key=lambda combo: -sum(score for score, _ in combo)):
        quad = np.float32([point for _, point in combo])  # channel order is TL, TR, BR, BL
        if (cv2.isContourConvex(quad) and cv2.contourArea(quad) > side * side * .01
                and plausible(quad)):
            options.append((quad, min(score for score, _ in combo)))
    return options


def plausible(quad):
    """Whether the outline could be a photographed sheet, not collapsed corners."""
    angles, sides = [], []
    for i in range(4):
        before, corner, after = quad[i - 1], quad[i], quad[(i + 1) % 4]
        a, b = before - corner, after - corner
        cosine = float(a @ b) / max(float(np.linalg.norm(a) * np.linalg.norm(b)), 1e-6)
        angles.append(np.degrees(np.arccos(np.clip(cosine, -1, 1))))
        sides.append(float(np.linalg.norm(after - corner)))
    ratio = min(sides[0] / max(sides[2], 1e-6), sides[2] / max(sides[0], 1e-6),
                sides[1] / max(sides[3], 1e-6), sides[3] / max(sides[1], 1e-6))
    return ANGLE_RANGE[0] <= min(angles) and max(angles) <= ANGLE_RANGE[1] and ratio >= MIN_SIDE_RATIO


def order(points):
    # Top-left, top-right, bottom-right, bottom-left regardless of model order.
    center = points.mean(axis=0)
    angles = np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0])
    points = points[np.argsort(angles)]
    start = np.argmin(points.sum(axis=1))
    return np.roll(points, -start, axis=0)


def flatten(bgr, quad):
    """Perspective-only page between the four corners (no dewarping)."""
    tl, tr, br, bl = quad
    width = round(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    height = round(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    target = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
    matrix = cv2.getPerspectiveTransform(quad.astype(np.float32), target)
    # Any part of the page the photo cut off comes out as plain white paper.
    return cv2.warpPerspective(bgr, matrix, (width, height), flags=cv2.INTER_CUBIC,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))

