"""Whether a detected outline is a written page that is safe to crop.

DocAligner outlines anything page-shaped: appliance panels, signs, the inner
table of a form, one sheet of two. Cropping those loses the photo or the
writing around the outline, so a page is cropped only when all of these hold:

  writing      letter-like marks in rows inside the outline (either direction)
  evidence     DocAligner's presence model on the flattened page, or plenty
               of writing
  margin       no ink on a paper margin that continues past the outline (the
               outline is an inner table or frame of a larger sheet)
  second sheet no lines of text on a separate light surface (another page)
  desk band    no strip of the surroundings running across the outline (two
               sheets outlined as one)

Measured on the DocCorner dev set (7,706 labelled photos, half used to choose
the thresholds, half to check them): 81% of documents cropped against 31% by
the previous detector, 19 of 3,879 photos without a document cropped against
its 21. The old detector's synthetic safety fixtures (tests/scan_fixtures.py)
are all left untouched.
"""
import cv2
import numpy as np

from .detect import flatten, paper_colour, presence

# Writing: marks in rows needed inside the page, and the amount that counts
# as evidence on its own when the presence model is unsure.
MIN_WRITING = 8
PLENTY_OF_WRITING = 60
MIN_PRESENCE = 0.1
# A mark is ink when its median black-hat contrast reaches this (JPEG and
# sharpening halos around real pages measure below 50).
INK = 50
# Writing on a margin past the outline must be clearly inked: pen and print
# measure 126-255, while specks on a white wall or an overexposed trailer
# behind a held page measure 51-64.
MARGIN_INK = 100
# Lab distance with lightness counted at 0.4, as in detect.same_paper.
WEIGHT = np.float32([0.4, 1, 1])
PAGE_SIDE = 1000
PHOTO_SIDE = 1400


def marks(gray, contrast=False):
    """Letter-like dark marks: centres x, y, sizes w, h (and median contrast)."""
    hat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15)))
    _, labels, stats, _ = cv2.connectedComponentsWithStats((hat > 30).astype(np.uint8), connectivity=8)
    x, y, w, h, area = (stats[1:, i].astype(np.float32) for i in range(5))
    fill = area / np.maximum(w * h, 1)
    big, small = np.maximum(w, h), np.minimum(w, h)
    keep = (big >= 6) & (big <= 60) & (small >= 2) & (fill > .12) & (fill < .95) & (big <= 4 * small + 6)
    found = (x + w / 2)[keep], (y + h / 2)[keep], w[keep], h[keep]
    if not contrast:
        return found
    ids = np.nonzero(keep)[0] + 1
    medians = np.zeros(len(ids), np.float32)
    if len(ids):
        flat_labels = labels.ravel()
        chosen = np.isin(flat_labels, ids)
        owners, values = flat_labels[chosen], hat.ravel()[chosen].astype(np.float32)
        order = np.argsort(owners, kind='stable')
        owners, values = owners[order], values[order]
        starts, ends = np.searchsorted(owners, ids), np.searchsorted(owners, ids, side='right')
        medians = np.array([np.median(values[a:b]) for a, b in zip(starts, ends)], np.float32)
    return (*found, medians)


def rowed(x, y, size):
    """How many marks have two neighbours of similar size on the same line."""
    count = 0
    for i in range(len(x)):
        near = ((np.abs(y - y[i]) < .35 * size[i]) & (np.abs(x - x[i]) < 2.5 * size[i])
                & (np.abs(size - size[i]) < .5 * size[i]))
        count += near.sum() >= 3
    return int(count)


def writing(gray):
    """Marks in rows, read along lines or down columns (a page turned sideways)."""
    x, y, w, h = marks(gray)
    return max(rowed(x, y, h), rowed(y, x, w))


def check(bgr, quad):
    """(True, None) when the outline is a written page safe to crop, else (False, reason)."""
    page = flatten(bgr, quad)
    scale = PAGE_SIDE / max(page.shape[:2])
    page = cv2.resize(page, (max(8, round(page.shape[1] * scale)), max(8, round(page.shape[0] * scale))),
                      interpolation=cv2.INTER_AREA)
    text = writing(cv2.cvtColor(page, cv2.COLOR_BGR2GRAY))
    if text < MIN_WRITING:
        return False, 'no_writing'
    if text < PLENTY_OF_WRITING and presence(page) < MIN_PRESENCE:
        return False, 'weak_evidence'

    height, width = bgr.shape[:2]
    scale = min(1.0, PHOTO_SIDE / max(height, width))
    photo = (cv2.resize(bgr, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
             if scale < 1 else bgr)
    h, w = photo.shape[:2]
    lab = cv2.cvtColor(photo, cv2.COLOR_BGR2LAB).astype(np.float32)
    gray = cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY)
    outline = np.int32(np.round(quad * scale))
    inside = np.zeros((h, w), np.uint8)
    cv2.fillPoly(inside, [outline], 1)
    band = max(3, round(.015 * max(h, w)))
    near = cv2.dilate(inside, _disc(band))

    x, y, mw, mh, contrast = marks(gray, contrast=True)
    xi, yi = np.clip(x.round().astype(int), 0, w - 1), np.clip(y.round().astype(int), 0, h - 1)
    # Marks outside the outline, clear of the page edge and the photo frame.
    away = (near[yi, xi] == 0) & (xi > 3) & (yi > 3) & (xi < w - 4) & (yi < h - 4) & (contrast >= INK)

    if _margin_ink(lab, inside, band, away & (contrast >= MARGIN_INK), xi, yi, mw, mh):
        return False, 'writing_beyond_outline'
    if _second_sheet(gray, inside, near, away, x, y, mw, mh, xi, yi):
        return False, 'second_sheet'
    if _desk_band(lab, inside, near, band, outline):
        return False, 'desk_band'
    return True, None


def _disc(radius):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))


def _margin_ink(lab, inside, band, away, xi, yi, mw, mh):
    """Ink on a uniform light margin around the outline: the page goes on past it.

    The margin is the light, neutral material of a rim just outside the
    outline, followed as far as it reaches. A mark counts only when that
    material surrounds it: a wall or desk meeting a hand at the photo's edge
    is not a paper margin.
    """
    rim = (cv2.dilate(inside, _disc(3 * band)) > 0) & (cv2.dilate(inside, _disc(band)) == 0)
    if rim.sum() <= 200 or not away.any():
        return False
    rim_lab = lab[rim]
    neutral = (rim_lab[:, 0] > 150) & (np.hypot(rim_lab[:, 1] - 128, rim_lab[:, 2] - 128) < 25)
    if neutral.mean() <= .3:
        return False
    material = np.median(rim_lab[neutral], axis=0)
    same = (np.linalg.norm((lab - material) * WEIGHT, axis=2) <= 10).astype(np.uint8)
    same = cv2.morphologyEx(same, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9)))
    count, labels = cv2.connectedComponents(same, connectivity=8)
    on_rim = np.bincount(labels[rim & (same > 0)].ravel(), minlength=count)
    margin = np.isin(labels, [i for i in range(1, count) if on_rim[i] >= .1 * rim.sum()])
    if not margin.any():
        return False
    reach = cv2.dilate(margin.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)))
    h, w = margin.shape
    for i in np.nonzero(away & (reach[yi, xi] > 0))[0]:
        r = int(max(mw[i], mh[i]) * 1.5) + 2
        box = margin[max(0, yi[i] - r):min(h, yi[i] + r + 1), max(0, xi[i] - r):min(w, xi[i] + r + 1)]
        if box.mean() >= .5:
            return True
    return False


def _second_sheet(gray, inside, near, away, x, y, mw, mh, xi, yi):
    """Lines of text on a light surface that does not touch the outline: another page."""
    light = (cv2.morphologyEx(gray, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25)))
             > 120).astype(np.uint8)
    _, labels = cv2.connectedComponents(light, connectivity=8)
    ring = (near > 0) & (inside == 0)
    touching = np.isin(labels, np.unique(labels[ring & (light > 0)]))
    separate = away & (light[yi, xi] > 0) & ~touching[yi, xi]
    if not separate.any():
        return False
    return max(rowed(x[separate], y[separate], mh[separate]),
               rowed(y[separate], x[separate], mw[separate])) >= MIN_WRITING


def _desk_band(lab, inside, near, band, outline):
    """A strip of the surroundings crossing the outline from side to side."""
    ring = (cv2.dilate(inside, _disc(2 * band)) > 0) & (near == 0)
    paper = paper_colour(lab, inside)
    if ring.sum() <= 200 or paper is None:
        return False
    desk = np.median(lab[ring], axis=0)
    if np.linalg.norm((desk - paper) * WEIGHT) <= 30:
        return False
    like = (np.linalg.norm((lab - desk) * WEIGHT, axis=2) < 10).astype(np.uint8) & inside
    like = cv2.morphologyEx(like, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9)))
    edge = inside - cv2.erode(inside, _disc(band))
    _, labels = cv2.connectedComponents(like, connectivity=8)
    span_x = outline[:, 0].max() - outline[:, 0].min()
    span_y = outline[:, 1].max() - outline[:, 1].min()
    for label in np.unique(labels[(edge > 0) & (like > 0)]):
        if label == 0:
            continue
        ys, xs = np.nonzero((labels == label) & (edge > 0))
        if xs.max() - xs.min() > .6 * span_x or ys.max() - ys.min() > .6 * span_y:
            return True
    return False
