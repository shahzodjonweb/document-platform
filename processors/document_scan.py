"""Local, conservative paper scanning. Called only by the bounded image worker.

Detection uses a thumbnail; uncertain, partial or competing page outlines leave
the full image intact. No OCR, models, uploads or external services are involved.
"""
from functools import lru_cache
import math
import os

from PIL import Image

DETECTION_SIDE = 1280
MAX_WARP_PIXELS = 16_000_000


@lru_cache(maxsize=1)
def _numeric():
    os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    import cv2
    import numpy as np
    cv2.setNumThreads(1)
    cv2.ocl.setUseOpenCL(False)
    return cv2, np


def _thumbnail(image, side=DETECTION_SIDE):
    scale = min(1.0, side / max(image.size))
    if scale == 1:
        return image
    return image.resize((max(1, round(image.width * scale)),
                         max(1, round(image.height * scale))), Image.Resampling.LANCZOS)


def _order(points):
    _, np = _numeric()
    points = np.asarray(points, dtype=np.float32).reshape(4, 2)
    center = points.mean(axis=0)
    angles = np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0])
    points = points[np.argsort(angles)]
    return np.roll(points, -int(np.argmin(points.sum(axis=1))), axis=0)


def _full_frame_document(rgb, gray, saturation):
    """A scan already filling the frame must not be cropped to an inner table."""
    cv2, np = _numeric()
    height, width = gray.shape
    border = max(2, round(min(height, width) * .025))
    edges = [gray[:border], gray[-border:], gray[:, :border], gray[:, -border:]]
    colors = [saturation[:border], saturation[-border:], saturation[:, :border], saturation[:, -border:]]
    paper = float(np.percentile(gray, 90))
    if paper < 165 or any(float(np.median(e)) < max(145, paper - 55) for e in edges):
        return False
    if any(float(np.percentile(s, 75)) > 50 for s in colors):
        return False
    if float(np.mean(saturation > 75)) > .12:
        return False
    ink = ((gray < paper - 45) & (saturation < 100)).astype(np.uint8)
    fraction = float(ink.mean())
    if not .001 <= fraction <= .28:
        return False
    count, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    # Several small written marks, rather than one photograph or a lone frame.
    marks = sum(1 for x, y, w, h, area in stats[1:]
                if 3 <= area <= height * width * .015 and 2 <= h <= height * .12
                and w <= width * .75)
    return count > 5 and marks >= 5


def _geometry(quad, width, height):
    cv2, np = _numeric()
    area = abs(float(cv2.contourArea(quad)))
    # Smaller outlines are retained only to spot a competing second document.
    if not .04 <= area / (width * height) <= .97:
        return False
    # All four edges must be visible. Guessing hidden corners can remove text.
    gap = max(2, min(width, height) * .004)
    if (np.any(quad[:, 0] <= gap) or np.any(quad[:, 0] >= width - 1 - gap)
            or np.any(quad[:, 1] <= gap) or np.any(quad[:, 1] >= height - 1 - gap)):
        return False
    sides = [float(np.linalg.norm(quad[(i + 1) % 4] - quad[i])) for i in range(4)]
    if min(sides) < min(width, height) * .12 or max(sides) / min(sides) > 5:
        return False
    for i in range(4):
        a, b = quad[(i - 1) % 4] - quad[i], quad[(i + 1) % 4] - quad[i]
        cosine = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
        if not -0.82 < cosine < .82:
            return False
    return True


def _candidate(quad, gray, saturation, edges):
    cv2, np = _numeric()
    height, width = gray.shape
    if not _geometry(quad, width, height):
        return None
    mask = np.zeros(gray.shape, dtype=np.uint8)
    cv2.fillConvexPoly(mask, np.round(quad).astype(np.int32), 255)
    interior = cv2.erode(mask, np.ones((7, 7), np.uint8)) > 0
    light = gray[interior]
    colors = saturation[interior]
    if light.size < 100 or float(np.percentile(light, 75)) < 160:
        return None
    if float(np.median(colors)) > 45 or float(np.mean(colors > 90)) > .18:
        return None
    paper = float(np.percentile(light, 85))
    if float(np.mean(light >= paper - 55)) < .55:
        return None
    # A bright rectangular appliance/panel alone is ambiguous. Require some
    # writing-like marks before changing the image, including colored ink.
    local_paper = cv2.morphologyEx(gray, cv2.MORPH_CLOSE,
                                 cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31)))
    ink = ((local_paper.astype(np.int16) - gray.astype(np.int16) > 25)
           & interior).astype(np.uint8)
    fraction = float(ink.sum()) / light.size
    if not .0005 <= fraction <= .25:
        return None
    _, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    marks = sum(1 for x, y, w, h, area in stats[1:]
                if 3 <= area <= light.size * .02 and 2 <= h <= height * .15
                and w <= width * .5)
    if marks < 5:
        return None
    # Look beyond a printed frame/table stroke. Its dark outline is not evidence
    # of a paper edge when the surrounding area is still the same sheet.
    gap = max(6, round(min(width, height) * .025))
    outer_gap = max(gap + 4, round(min(width, height) * .05))
    near = cv2.dilate(mask, np.ones((2 * gap + 1, 2 * gap + 1), np.uint8))
    far = cv2.dilate(mask, np.ones((2 * outer_gap + 1, 2 * outer_gap + 1), np.uint8))
    ring = (far > 0) & (near == 0)
    if int(ring.sum()) < 100:
        return None
    contrast = paper - float(np.median(gray[ring]))
    # Compare nearby paper and background along each edge, rather than allowing
    # a lighting gradient across the page to impersonate an internal boundary.
    for index in range(4):
        start, end = quad[index], quad[(index + 1) % 4]
        edge = end - start
        outward = np.array([edge[1], -edge[0]]) / np.linalg.norm(edge)
        positions = np.linspace(.2, .8, 25)[:, None]
        middle = start + positions * edge
        inside = np.round(middle - outward * gap).astype(np.int32)
        outside = np.round(middle + outward * (gap + 3)).astype(np.int32)
        valid = ((outside[:, 0] >= 0) & (outside[:, 0] < width)
                 & (outside[:, 1] >= 0) & (outside[:, 1] < height)
                 & (inside[:, 0] >= 0) & (inside[:, 0] < width)
                 & (inside[:, 1] >= 0) & (inside[:, 1] < height))
        if int(valid.sum()) < 8:
            return None
        inside, outside = inside[valid], outside[valid]
        if float(np.median(gray[inside[:, 1], inside[:, 0]])) - float(np.median(gray[outside[:, 1], outside[:, 0]])) < 6:
            return None
    boundary = (mask > 0) & ~interior
    supported = cv2.dilate(edges, np.ones((5, 5), np.uint8)) > 0
    support = float(np.mean(supported[boundary]))
    if contrast < 8 or support < .30:
        return None
    return {'quad': quad, 'mask': mask > 0, 'area': float(interior.sum()),
            'score': float(interior.sum()) * (1 + min(contrast, 100) / 300 + support / 5)}


def _detect(image):
    cv2, np = _numeric()
    small = _thumbnail(image)
    rgb = np.asarray(small, dtype=np.uint8)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    saturation = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)[:, :, 1]
    if _full_frame_document(rgb, gray, saturation):
        return None, True
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 35, 110)
    connected = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=2)
    _, bright = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bright[saturation > 90] = 0
    bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    candidates = []
    for source in (connected, bright):
        contours, _ = cv2.findContours(source, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:40]:
            if cv2.contourArea(contour) < gray.size * .04:
                break
            perimeter = cv2.arcLength(contour, True)
            for epsilon in (.015, .025, .035):
                polygon = cv2.approxPolyDP(contour, epsilon * perimeter, True)
                if len(polygon) != 4 or not cv2.isContourConvex(polygon):
                    continue
                candidate = _candidate(_order(polygon), gray, saturation, edges)
                if candidate is None:
                    continue
                # Canny produces inside/outside outlines of the same paper.
                duplicate = next((old for old in candidates
                    if float(np.sum(old['mask'] & candidate['mask'])) /
                    float(np.sum(old['mask'] | candidate['mask'])) > .85), None)
                if duplicate is None:
                    candidates.append(candidate)
                elif candidate['area'] > duplicate['area']:
                    duplicate.update(candidate)
                break
    if not candidates:
        return None, False
    candidates.sort(key=lambda item: item['score'], reverse=True)
    best = candidates[0]
    if best['area'] < gray.size * .18:
        return None, False  # Too little evidence for a main page crop.
    for other in candidates[1:]:
        overlap = float(np.sum(best['mask'] & other['mask'])) / min(best['area'], other['area'])
        if other['area'] >= gray.size * .04 and overlap < .20:
            return None, False  # More than one plausible page: retain both.
    quad = best['quad'].copy()
    quad[:, 0] *= image.width / small.width
    quad[:, 1] *= image.height / small.height
    return quad, True


def _warp(image, quad):
    cv2, np = _numeric()
    # Include a small safety border so edge writing is never deliberately cut.
    center = quad.mean(axis=0)
    padded = center + (quad - center) * 1.012
    padded[:, 0] = np.clip(padded[:, 0], 0, image.width - 1)
    padded[:, 1] = np.clip(padded[:, 1], 0, image.height - 1)
    tl, tr, br, bl = padded
    width = max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))
    height = max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))
    scale = min(1.0, math.sqrt(MAX_WARP_PIXELS / max(1, width * height)))
    width, height = max(2, round(width * scale)), max(2, round(height * scale))
    destination = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], np.float32)
    matrix = cv2.getPerspectiveTransform(padded.astype(np.float32), destination)
    result = cv2.warpPerspective(np.asarray(image), matrix, (width, height),
                                 flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return Image.fromarray(result)


def _enhance(image, quad=None):
    """Normalize broad shadows in bounded strips while retaining colored ink."""
    cv2, np = _numeric()
    rgb = np.asarray(image, dtype=np.uint8)
    small = _thumbnail(image, 512)
    small_gray = cv2.cvtColor(np.asarray(small), cv2.COLOR_RGB2GRAY)
    background = cv2.morphologyEx(small_gray, cv2.MORPH_CLOSE,
                                  cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17)))
    background = cv2.GaussianBlur(background, (0, 0), 7)
    background = cv2.resize(background, image.size, interpolation=cv2.INTER_LINEAR)
    background = np.maximum(background, 75)
    result = np.empty_like(rgb)
    values = np.arange(256, dtype=np.float32)
    table = np.clip((values - 25) * (255 / 220), 0, 255).astype(np.uint8)
    mask = None
    if quad is not None:
        mask = np.zeros((image.height, image.width), np.uint8)
        cv2.fillConvexPoly(mask, np.round(quad).astype(np.int32), 255)
    rows = max(1, 1_000_000 // image.width)
    for first in range(0, image.height, rows):
        last = min(image.height, first + rows)
        for channel in range(3):
            normalized = cv2.divide(rgb[first:last, :, channel], background[first:last], scale=245)
            adjusted = cv2.LUT(normalized, table)
            if mask is not None:
                adjusted = np.where(mask[first:last] > 0, adjusted, rgb[first:last, :, channel])
            result[first:last, :, channel] = adjusted
    return Image.fromarray(result)


def prepare_image(image, *, auto_crop=True, enhance_text=True):
    """Return a new image and content-free outcome flags. Input is already RGB."""
    metadata = {'document_detected': False, 'cropped': False, 'enhanced': False}
    if not auto_crop and not enhance_text or min(image.size) < 96:
        return image, metadata
    quad, detected = _detect(image)
    metadata['document_detected'] = detected
    if not detected:
        return image, metadata
    if auto_crop and quad is not None:
        image = _warp(image, quad)
        metadata['cropped'] = True
        quad = None
    if enhance_text:
        image = _enhance(image, quad)
        metadata['enhanced'] = True
    return image, metadata
