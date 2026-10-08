"""Local, conservative paper scanning. Called only by the bounded image worker.

Detection uses a thumbnail; uncertain or competing outlines retain the image.
Qualified clipped paper receives masked cleanup and verified empty-band trimming,
without inventing missing corners. No OCR, uploads or external services are used.
"""
from functools import lru_cache
import math
import os

from PIL import Image

DETECTION_SIDE = 1280
MAX_WARP_PIXELS = 16_000_000
SEGMENTATION_SIDE = 512
# Written evidence every candidate must show. Measured on the benchmark set:
# documents carry 73-207 hollow glyph boxes in 5-18 aligned rows, the gray
# appliance 3-8 boxes in 0-1 rows and tinted panels none, so the gate sits
# well below the documents and above the appliance.
GLYPHS_MIN = 8
GLYPH_ROWS_MIN = 1
RELAXED_GLYPHS = 20
# A glyph box must also carry credible ink. JPEG block noise around a dark
# panel feature measures 27-32 levels below its local paper, print 45-76.
GLYPH_INK = 40


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


def _matte_material(light, saturation, chroma):
    """A shaded/tinted sheet retains a coherent material color around its ink."""
    _, np = _numeric()
    if light.size < 100 or float(np.percentile(light, 75)) < 135:
        return None
    if float(np.median(saturation)) > 105 or float(np.mean(saturation > 140)) > .15:
        return None
    clean = light >= float(np.percentile(light, 75)) - 35
    if float(clean.mean()) < .55:
        return None
    colors = chroma[clean].astype(np.float32)
    material = np.median(colors, axis=0)
    distances = np.linalg.norm(colors - material, axis=1)
    if float(np.percentile(distances, 85)) > 12:
        return None
    return material


def _full_frame_document(rgb, gray, saturation, lab=None):
    """A scan already filling the frame must not be cropped to an inner table."""
    cv2, np = _numeric()
    height, width = gray.shape
    border = max(2, round(min(height, width) * .025))
    edges = [gray[:border], gray[-border:], gray[:, :border], gray[:, -border:]]
    colors = [saturation[:border], saturation[-border:], saturation[:, :border], saturation[:, -border:]]
    paper = float(np.percentile(gray, 90))
    conventional = (paper >= 165
        and all(float(np.median(e)) >= max(145, paper - 55) for e in edges)
        and all(float(np.percentile(s, 75)) <= 50 for s in colors)
        and float(np.mean(saturation > 75)) <= .12)
    if not conventional:
        if lab is None:
            return False
        material = _matte_material(gray.ravel(), saturation.ravel(), lab[:, :, 1:].reshape(-1, 2))
        if material is None or any(float(np.median(e)) < max(110, paper - 55) for e in edges):
            return False
        edge_materials = [lab[:border, :, 1:], lab[-border:, :, 1:],
                          lab[:, :border, 1:], lab[:, -border:, 1:]]
        if any(float(np.linalg.norm(np.median(e.reshape(-1, 2), axis=0) - material)) > 8
               for e in edge_materials):
            return False
    ink = ((gray < paper - 45) & (saturation < 100)).astype(np.uint8)
    fraction = float(ink.mean())
    if not .001 <= fraction <= .45:
        return False
    count, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    # Several small written marks, rather than one photograph or a lone frame.
    marks = sum(1 for x, y, w, h, area in stats[1:]
                if 3 <= area <= height * width * .015 and 2 <= h <= height * .12
                and w <= width * .75)
    compact_marks = sum(1 for x, y, w, h, area in stats[1:]
        if 3 <= area <= height * width * .015 and 3 <= h <= height * .12
        and 3 <= w <= min(width * .15, h * 4) and h <= w * 5)
    if not conventional:
        marks = compact_marks
    if fraction > .28:
        # Header bars, table rules and barcodes can occupy a third of a real
        # form. Dense pixels alone are not written evidence: require many
        # compact marks on a coherent matte material before treating it as a
        # full-frame scan rather than an ordinary photograph.
        glyphs = sum(1 for x, y, w, h, area in stats[1:]
            if 3 <= area <= height * width * .015 and 3 <= h <= height * .12
            and 3 <= w <= min(width * .15, h * 4) and h <= w * 5
            and area / (w * h) < .70)
        if lab is None or glyphs < 20 or _matte_material(
                gray.ravel(), saturation.ravel(), lab[:, :, 1:].reshape(-1, 2)) is None:
            return False
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


def _glyph_rows(boxes, shape):
    """Text lines: rows (or columns, for a quarter-turned page) of >= 3 glyph-like marks."""
    cv2, np = _numeric()
    if len(boxes) < 3:
        return 0
    height, width = shape
    best = 0
    for size, start, extent in ((height, 1, 3), (width, 0, 2)):
        support = np.zeros(size, np.int32)
        for box in boxes:
            support[box[start]:box[start] + box[extent]] += 1
        active = (support >= 3).astype(np.uint8)[:, None]
        active = cv2.dilate(active, np.ones((5, 1), np.uint8))[:, 0] > 0
        best = max(best, int((np.diff(np.r_[False, active, False].astype(np.int8)) == 1).sum()))
    return best


def _exterior_writing(quad, gray, saturation):
    """Compact exterior words mean the proposed block is not the whole page."""
    cv2, np = _numeric()
    mask = np.zeros(gray.shape, np.uint8)
    cv2.fillConvexPoly(mask, np.round(quad).astype(np.int32), 255)
    mask = cv2.dilate(mask, np.ones((13, 13), np.uint8))
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31)))
    # Margin writing is evidence of an internal printed block only when it
    # belongs to the matte surface surrounding that block. Background labels
    # on a separate surface, across a broad dark gap, must not veto a page.
    # Closing bridges ordinary thin printed rules without crossing that gap.
    surface = ((background >= 115) & (mask == 0)).astype(np.uint8)
    components, surface_labels = cv2.connectedComponents(surface, connectivity=8)
    side_support = np.zeros(components, np.uint8)
    gap = max(8, min(gray.shape) * .0125)
    for index in range(4):
        start, end = quad[index], quad[(index + 1) % 4]
        edge = end - start
        outward = np.array([edge[1], -edge[0]]) / np.linalg.norm(edge)
        middle = start + np.linspace(.15, .85, 40)[:, None] * edge
        points = np.concatenate([middle + outward * gap, middle + outward * gap * 2])
        points = np.round(points).astype(np.int32)
        valid = ((points[:, 0] >= 0) & (points[:, 0] < gray.shape[1])
                 & (points[:, 1] >= 0) & (points[:, 1] < gray.shape[0]))
        points = points[valid]
        if points.size == 0:
            continue
        counts = np.bincount(surface_labels[points[:, 1], points[:, 0]], minlength=components)
        supported = counts >= len(points) * .30
        supported[0] = False
        side_support[supported] += 1
    surrounding = side_support >= 1
    surrounding[0] = False
    if not np.any(surrounding):
        return False
    # Deep print and colored pen strokes avoid counting pale flowers, cast
    # shadows, long desk patterns or isolated decorations as missing words.
    ink = ((background.astype(np.int16) - gray.astype(np.int16) > 35)
           & ((saturation < 45) | ((saturation > 65) & (gray > 8)))
           & (background >= 115) & (mask == 0)
           & surrounding[surface_labels]).astype(np.uint8)
    _, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    limit = min(gray.shape) * .06
    # Camera sharpening halos hug every glyph; they belong to the glyph, not
    # to the surface whose uniformity establishes margin context.
    halo = cv2.dilate(ink, np.ones((7, 7), np.uint8))
    marks = []
    for x, y, w, h, area in stats[1:]:
        if not (area >= 5 and 3 <= w <= min(limit, h * 4)
                and 3 <= h <= min(limit, w * 5)):
            continue
        # A fragment of a leaf or cast shadow can resemble a short glyph.
        # Real margin print has a broad, locally uniform matte surface around
        # it; use original pixels rather than the closing filter's invented
        # light background to establish that context.
        padding = max(8, round(max(w, h) * .5))
        top, left = max(0, y - padding), max(0, x - padding)
        context = gray[top:y + h + padding, left:x + w + padding]
        context_ink = halo[top:y + h + padding, left:x + w + padding] > 0
        surface = context[~context_ink]
        if surface.size < 20:
            continue
        tone = float(np.median(surface))
        if tone < 115 or float(np.percentile(np.abs(surface.astype(np.float32) - tone), 85)) > 15:
            continue
        marks.append((int(x), int(y), int(w), int(h)))
        if len(marks) == 256:
            break
    if not marks:
        return False
    residual = background.astype(np.int16) - gray.astype(np.int16)
    for x, y, w, h in marks:
        pixels = ink[y:y + h, x:x + w] > 0
        context = gray[max(0, y - 4):y + h + 4, max(0, x - 4):x + w + 4]
        context_ink = halo[max(0, y - 4):y + h + 4, max(0, x - 4):x + w + 4] > 0
        surface = context[~context_ink]
        if (pixels.sum() >= 15 and float(pixels.mean()) <= .70
                and float(np.median(residual[y:y + h, x:x + w][pixels])) >= 60
                and surface.size >= 20
                and float(np.median(np.abs(surface.astype(np.float32) - np.median(surface)))) <= 4):
            return True  # A clear isolated margin glyph must also be retained.
    if len(marks) < 2:
        return False
    parents = list(range(len(marks)))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    # Nearby glyphs form words/lines; unrelated compact photographic details
    # distributed around a desk are insufficient evidence to veto the page.
    for index, (x, y, w, h) in enumerate(marks):
        for other in range(index):
            ox, oy, ow, oh = marks[other]
            row_overlap = min(y + h, oy + oh) - max(y, oy)
            column_overlap = min(x + w, ox + ow) - max(x, ox)
            row_gap = max(0, max(x, ox) - min(x + w, ox + ow))
            column_gap = max(0, max(y, oy) - min(y + h, oy + oh))
            same_row = (row_overlap >= min(h, oh) * .5 and row_gap <= max(h, oh)
                        and max(h, oh) <= min(h, oh) * 2.5)
            same_column = (column_overlap >= min(w, ow) * .5 and column_gap <= max(w, ow)
                           and max(w, ow) <= min(w, ow) * 2.5)
            if same_row or same_column:
                parents[root(index)] = root(other)
    groups = {}
    for index in range(len(marks)):
        identifier = root(index)
        groups[identifier] = groups.get(identifier, 0) + 1
    return max(groups.values()) >= 2


def _candidate(quad, gray, saturation, edges, *, compact_writing=False, lab=None, outline=None):
    cv2, np = _numeric()
    height, width = gray.shape
    if not _geometry(quad, width, height):
        return None
    mask = np.zeros(gray.shape, dtype=np.uint8)
    cv2.fillConvexPoly(mask, np.round(quad).astype(np.int32), 255)
    interior = cv2.erode(mask, np.ones((7, 7), np.uint8)) > 0
    light = gray[interior]
    colors = saturation[interior]
    if light.size < 100:
        return None
    conventional = (float(np.percentile(light, 75)) >= 160
                    and float(np.median(colors)) <= 45
                    and float(np.mean(colors > 90)) <= .18)
    material = None if lab is None else _matte_material(light, colors, lab[interior][:, 1:])
    if not conventional and material is None:
        return None
    paper = float(np.percentile(light, 85))
    if float(np.mean(light >= paper - 55)) < .55:
        return None
    # A bright rectangular appliance/panel alone is ambiguous. Require some
    # writing-like marks before changing the image, including colored ink.
    # Unsharp-mask overshoot halos must not become the paper reference: a 5-px
    # median removes them before the closing, while the ink test stays on the
    # raw pixels so genuine thin strokes are still counted.
    local_paper = cv2.morphologyEx(cv2.medianBlur(gray, 5), cv2.MORPH_CLOSE,
                                 cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31)))
    ink = ((local_paper.astype(np.int16) - gray.astype(np.int16) > 25)
           & interior).astype(np.uint8)
    fraction = float(ink.sum()) / light.size
    if not .0005 <= fraction <= .45:
        return None
    _, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    marks = sum(1 for x, y, w, h, area in stats[1:]
                if 3 <= area <= light.size * .02 and 2 <= h <= height * .15
                and w <= width * .5)
    if marks < 5:
        return None
    compact_marks = sum(1 for x, y, w, h, area in stats[1:]
        if 3 <= area <= light.size * .02 and 3 <= h <= height * .15
        and 3 <= w <= min(width * .15, h * 4) and h <= w * 5)
    residual = local_paper.astype(np.int16) - gray.astype(np.int16)
    glyph_boxes = []
    for label, (x, y, w, h, area) in enumerate(stats[1:], 1):
        if not (3 <= area <= light.size * .02 and 3 <= h <= height * .15
                and 3 <= w <= min(width * .15, h * 4) and h <= w * 5
                and area / (w * h) < .70):
            continue
        strokes = residual[y:y + h, x:x + w][labels[y:y + h, x:x + w] == label]
        if float(np.median(strokes)) >= GLYPH_INK:
            glyph_boxes.append((x, y, w, h))
    if len(glyph_boxes) < GLYPHS_MIN or _glyph_rows(glyph_boxes, gray.shape) < GLYPH_ROWS_MIN:
        return None  # Vents, knobs and lone dots are not written lines.
    dense_print = fraction > .25
    if dense_print:
        # Filled vent holes and repeated solid dots are compact too. Written
        # glyphs leave significant background inside their bounding boxes.
        glyphs = sum(1 for x, y, w, h, area in stats[1:]
            if 3 <= area <= light.size * .02 and 3 <= h <= height * .15
            and 3 <= w <= min(width * .15, h * 4) and h <= w * 5
            and area / (w * h) < .70)
        if material is None or glyphs < 20:
            return None
    if compact_writing or not conventional:
        # Weak-edge segmentation can also propose vented appliances. Border
        # fragments, long slots and a knob are not sufficient written evidence.
        if compact_marks < 5:
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
    conventional_edges = True
    material_edges = material is not None and compact_marks >= 5
    for index in range(4):
        start, end = quad[index], quad[(index + 1) % 4]
        edge = end - start
        outward = np.array([edge[1], -edge[0]]) / np.linalg.norm(edge)
        positions = np.linspace(.2, .8, 25)[:, None]
        middle = start + positions * edge
        inside = np.round(middle - outward * gap).astype(np.int32)
        # A sheet photographed close to the frame still shows a strip of
        # background beyond its edge. Sample that strip where the full gap
        # would leave the frame, never closer than 3 px to the edge itself.
        reach = np.full(len(middle), float(gap + 3), np.float32)
        for axis, size in ((0, width), (1, height)):
            step = float(outward[axis])
            if step > 1e-6:
                reach = np.minimum(reach, (size - 1 - middle[:, axis]) / step)
            elif step < -1e-6:
                reach = np.minimum(reach, -middle[:, axis] / step)
        reach = np.floor(reach)
        outside = np.round(middle + outward * np.maximum(reach, 3)[:, None]).astype(np.int32)
        valid = ((reach >= 3) & (outside[:, 0] >= 0) & (outside[:, 0] < width)
                 & (outside[:, 1] >= 0) & (outside[:, 1] < height)
                 & (inside[:, 0] >= 0) & (inside[:, 0] < width)
                 & (inside[:, 1] >= 0) & (inside[:, 1] < height))
        if int(valid.sum()) < 8:
            return None
        inside, outside = inside[valid], outside[valid]
        inside_light, outside_light = gray[inside[:, 1], inside[:, 0]], gray[outside[:, 1], outside[:, 0]]
        signed_contrast = float(np.median(inside_light)) - float(np.median(outside_light))
        if signed_contrast < 6:
            conventional_edges = False
            if material_edges:
                # Small robust patches prevent a letter, stamp or thin floral
                # stroke at one sample from impersonating the sheet material.
                def sample_colors(points):
                    return np.asarray([np.median(lab[max(0, y - 3):y + 4,
                        max(0, x - 3):x + 4, 1:].reshape(-1, 2), axis=0)
                        for x, y in points], np.float32)
                inside_color, outside_color = sample_colors(inside), sample_colors(outside)
                inside_distance = np.linalg.norm(inside_color - material, axis=1)
                transition = np.median(inside_color - outside_color, axis=0)
                separation = float(np.linalg.norm(transition))
                # Shading can change a warm sheet's chroma along its length;
                # require a coherent local material transition rather than
                # forcing the whole perimeter to match one exact global tint.
                direction = transition / max(1., separation)
                support_color = (inside_color - outside_color) @ direction
                chromatic_edge = (separation >= 5
                    and float(np.median(inside_distance)) <= 8
                    and float(np.mean(support_color >= 3)) >= .60)
                # Dark neutral paper needs coherent reversed contrast, not an
                # absolute contrast shortcut that could select a printed rule.
                reversed_edge = (signed_contrast <= -8
                    and float(np.mean(inside_light.astype(np.int16)
                                      - outside_light.astype(np.int16) <= -6)) >= .70
                    and float(np.median(inside_distance)) <= 8)
                if not chromatic_edge and not reversed_edge:
                    material_edges = False
            if not material_edges and not conventional_edges:
                return None
    conventional_edges = conventional and conventional_edges and contrast >= 8
    if material_edges:
        ring_color = np.median(lab[ring][:, 1:].astype(np.float32), axis=0)
        material_edges = (float(np.linalg.norm(ring_color - material)) >= 5 or abs(contrast) >= 8)
    boundary = (mask > 0) & ~interior
    envelope = None
    strict = (not conventional_edges and material_edges) or dense_print
    validate_outline = strict and outline is not None
    if not strict and outline is not None:
        straight_supported = cv2.dilate(edges, np.ones((5, 5), np.uint8)) > 0
        if (float(np.mean(straight_supported[boundary])) < .30
                and compact_marks >= 5 and len(glyph_boxes) >= RELAXED_GLYPHS):
            # A straight inscribed quad sits off a bowed sheet's real edge, so
            # its band finds no support; with strong written evidence validate
            # the observed proposing contour instead, under the same bounds.
            validate_outline = True
    if validate_outline:
        points = np.asarray(outline, np.float32).reshape(-1, 2)
        distances = []
        for index in range(4):
            start, end = quad[index], quad[(index + 1) % 4]
            side = end - start
            along = np.clip(((points - start) @ side) / float(side @ side), 0, 1)
            distances.append(np.linalg.norm(points - (start + along[:, None] * side), axis=1))
        shortest = min(np.linalg.norm(quad[(index + 1) % 4] - quad[index]) for index in range(4))
        if float(np.max(np.min(distances, axis=0))) > shortest * .06:
            return None
        envelope = _circumscribed_quad(quad, cv2.convexHull(points))
        if envelope is None or not _geometry(envelope, width, height):
            return None
        observed = np.zeros(gray.shape, np.uint8)
        cv2.polylines(observed, [np.round(points).astype(np.int32)], True, 255, thickness=6)
        boundary = observed > 0
    supported = cv2.dilate(edges, np.ones((5, 5), np.uint8)) > 0
    support = float(np.mean(supported[boundary]))
    if (not conventional_edges and not material_edges) or support < .30:
        return None
    candidate = {'quad': quad, 'mask': mask > 0, 'area': float(interior.sum()),
            'material_edges': not conventional_edges or dense_print,
            'outline': None if outline is None else np.asarray(outline, np.float32).reshape(-1, 2),
            'score': float(interior.sum()) * (1 + min(abs(contrast), 100) / 300 + support / 5)}
    if envelope is not None:
        candidate['warp_quad'] = envelope
    candidate['ambiguous'] = _exterior_writing(candidate.get('warp_quad', quad), gray, saturation)
    return candidate


def _circumscribed_quad(quad, hull):
    """Enclose bowed paper sides instead of cutting them with an inscribed quad."""
    cv2, np = _numeric()
    points = hull.reshape(-1, 2).astype(np.float32)
    normals, constants, shifts = [], [], []
    for index in range(4):
        start, end = quad[index], quad[(index + 1) % 4]
        edge = end - start
        outward = np.array([edge[1], -edge[0]]) / np.linalg.norm(edge)
        constant = float(np.max(points @ outward))
        shifts.append(max(0., constant - float(start @ outward)))
        normals.append(outward)
        constants.append(constant)
    shortest = min(np.linalg.norm(quad[(i + 1) % 4] - quad[i]) for i in range(4))
    if max(shifts) > shortest * .06:
        return None  # Large irregular foreground is not a gently bowed sheet.
    result = []
    for index in range(4):
        previous = (index - 1) % 4
        matrix = np.array([normals[previous], normals[index]])
        if abs(np.linalg.det(matrix)) < .2:
            return None
        result.append(np.linalg.solve(matrix, [constants[previous], constants[index]]))
    result = np.asarray(result, np.float32)
    if abs(cv2.contourArea(result)) > abs(cv2.contourArea(quad)) * 1.15:
        return None
    return result


def _segmented_candidates(image, gray, saturation, lab=None):
    """Bounded fallback for faint curved edges that cannot form closed contours.

    Segmentation only proposes outlines. Each still needs the same independent
    geometry, writing, paper/background contrast and observed-edge validation.
    The initialization rectangle must never impersonate a visible paper edge.
    """
    cv2, np = _numeric()
    scale = min(1., SEGMENTATION_SIDE / max(image.size))
    width, height = max(2, round(image.width * scale)), max(2, round(image.height * scale))
    rgb = cv2.resize(np.asarray(image), (width, height), interpolation=cv2.INTER_AREA)
    x, y = max(2, int(width * .025)), max(2, int(height * .025))
    rect_width, rect_height = int(width * .95), int(height * .95)
    mask = np.zeros((height, width), np.uint8)
    cv2.setRNGSeed(0)
    try:
        cv2.grabCut(rgb, mask, (x, y, rect_width, rect_height),
                    np.zeros((1, 65)), np.zeros((1, 65)), 3, cv2.GC_INIT_WITH_RECT)
    except cv2.error:
        return []  # Solid/degenerate inputs may not support a foreground model.
    foreground = ((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)).astype(np.uint8) * 255
    # Remove single-pixel desk/shadow spurs before fitting the outline. The
    # enclosing crop and its safety padding preserve bowed sides and edge ink.
    foreground = cv2.morphologyEx(foreground, cv2.MORPH_OPEN,
                                 cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    contours, _ = cv2.findContours(foreground, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    weak_edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 5, 15)
    validation_scale = np.array([gray.shape[1] / width, gray.shape[0] / height], np.float32)
    candidates = []
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:10]:
        if cv2.contourArea(contour) < width * height * .04:
            break
        points = contour.reshape(-1, 2)
        touching = (np.any(points[:, 0] <= x + 1)
                    or np.any(points[:, 0] >= x + rect_width - 2)
                    or np.any(points[:, 1] <= y + 1)
                    or np.any(points[:, 1] >= y + rect_height - 2))
        if touching:
            return []  # A partial sheet must not be discarded beside another.
        hull = cv2.convexHull(contour)
        if cv2.contourArea(contour) / max(1, cv2.contourArea(hull)) < .94:
            continue
        perimeter = cv2.arcLength(hull, True)
        for epsilon in (.015, .025, .035):
            polygon = cv2.approxPolyDP(hull, epsilon * perimeter, True)
            if len(polygon) != 4 or not cv2.isContourConvex(polygon):
                continue
            quad = _order(polygon)
            candidate = _candidate(quad * validation_scale, gray, saturation, weak_edges,
                                   compact_writing=True, lab=lab,
                                   outline=points.astype(np.float32) * validation_scale)
            if candidate is None:
                continue
            envelope = _circumscribed_quad(quad, hull)
            if envelope is None or not _geometry(envelope, width, height):
                continue
            candidate['warp_quad'] = envelope * validation_scale
            candidates.append(candidate)
            break
    return candidates


def _detect(image, *, details=False):
    cv2, np = _numeric()
    small = _thumbnail(image)
    rgb = np.asarray(small, dtype=np.uint8)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    saturation = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)[:, :, 1]
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    frame_document = _full_frame_document(rgb, gray, saturation, lab)
    # Bright outer borders can also belong to a desk around one or several
    # darker sheets. Evaluate complete outlines before accepting a full-frame
    # scan; same-material internal tables fail independent candidate checks.
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 35, 110)
    connected = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=2)
    _, bright = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bright[saturation > 90] = 0
    bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    candidates = []
    partial_result = []
    def partial_document():
        # A clipped surface needs independent writing/material/contact evidence
        # before using the clipped-page fallback's bounded mask initialization.
        if partial_result:
            return partial_result[0]
        from processors.partial_document_scan import prequalify, refine
        hint = prequalify(image)
        if hint is None:
            result = None, False
        else:
            refined = refine(hint)
            result = (None if refined is None else {**refined, 'kind': 'partial'}), True
        partial_result.append(result)
        return result
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
                candidate = _candidate(_order(polygon), gray, saturation, edges, lab=lab,
                                       outline=contour)
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
    # Segmentation proposes outlines the contour sources missed. Without a
    # contour-qualified page it is the established complete-page fallback,
    # tried before a clipped surface: a bright desk can touch the frame around
    # a complete faint-edged page and must not impersonate its clipped edge.
    # Beside a qualified page it may only reveal a separate second sheet,
    # which makes the photograph ambiguous rather than being silently
    # discarded; a merged blob spanning several sheets never replaces one.
    if not candidates:
        # Straight sheet edges remain visible above and below a hand and
        # outside a printed border even when no closed contour forms.
        from processors.line_outlines import line_candidates
        candidates = line_candidates(gray, saturation, edges, lab)
    segmented = _segmented_candidates(image, gray, saturation, lab)
    if not candidates:
        candidates = segmented
    else:
        for candidate in segmented:
            if all(float(np.sum(old['mask'] & candidate['mask']))
                   / min(old['area'], candidate['area']) < .20 for old in candidates):
                candidates.append(candidate)
    if not candidates:
        partial, segmented = partial_document()
        if partial is not None:
            return (partial if details else None), True
        if segmented:
            return None, False  # Never retry a failed clipped-page model.
        return None, frame_document
    candidates.sort(key=lambda item: item['score'], reverse=True)
    qualified = [candidate for candidate in candidates if not candidate.get('ambiguous', False)]
    for candidate in candidates:
        if candidate.get('ambiguous', False):
            # A safely qualified larger page may enclose its printed filled
            # table. Otherwise exterior words make the photograph ambiguous.
            enclosed = any(other['area'] > candidate['area'] * 1.20
                and float(np.sum(other['mask'] & candidate['mask'])) /
                    float(candidate['mask'].sum()) >= .95 for other in qualified)
            if not enclosed:
                partial, _ = partial_document()
                if partial is not None:
                    return (partial if details else None), True
                return None, False
    candidates = qualified
    best = candidates[0]
    if best['area'] < gray.size * .18:
        return None, frame_document  # Too little evidence for a main page crop.
    for other in candidates[1:]:
        overlap = float(np.sum(best['mask'] & other['mask'])) / min(best['area'], other['area'])
        if other['area'] >= gray.size * .04 and overlap < .20:
            return None, False  # More than one plausible page: retain both.
    quad = best.get('warp_quad', best['quad']).copy()
    quad[:, 0] *= image.width / small.width
    quad[:, 1] *= image.height / small.height
    if details:
        scale = np.array([image.width / small.width, image.height / small.height], np.float32)
        outline = best.get('outline')
        return {'quad': best['quad'] * scale, 'envelope': quad,
                'outline': None if outline is None else outline * scale,
                'material_edges': best.get('material_edges', False)}, True
    return quad, True


def _warp(image, quad, *, with_mask=False, outline=None):
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
    if width * height > MAX_WARP_PIXELS:
        height = max(2, MAX_WARP_PIXELS // width)
    destination = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], np.float32)
    matrix = cv2.getPerspectiveTransform(padded.astype(np.float32), destination)
    result = cv2.warpPerspective(np.asarray(image), matrix, (width, height),
                                 flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    if with_mask:
        # Where the observed sheet lands in the output, at cleanup-mask scale,
        # so the safety border of desk is whitened rather than printed black.
        mask_scale = min(1., 512 / max(width, height))
        mask = np.zeros((max(2, round(height * mask_scale)),
                         max(2, round(width * mask_scale))), np.uint8)
        if outline is not None and len(outline) >= 4:
            points = cv2.perspectiveTransform(
                np.asarray(outline, np.float32).reshape(1, -1, 2), matrix)[0] * mask_scale
            # The proposing contour can detour inward around dark content
            # flush with the sheet edge; its hull still encloses the sheet.
            hull = cv2.convexHull(np.round(points).astype(np.int32))
            cv2.fillConvexPoly(mask, hull.reshape(-1, 2), 255)
            # The outline runs along the antialiased physical edge; step inside it.
            mask = cv2.erode(mask, np.ones((3, 3), np.uint8))
        else:
            inner = cv2.perspectiveTransform(quad.astype(np.float32)[None], matrix)[0] * mask_scale
            cv2.fillConvexPoly(mask, np.round(inner).astype(np.int32), 255)
        return Image.fromarray(result), mask
    return Image.fromarray(result)


def _paper_region(image, details):
    """Mask of the observed sheet, at detection scale, for enhancement in place."""
    cv2, np = _numeric()
    ratio = min(1., DETECTION_SIDE / max(image.size))
    width, height = max(1, round(image.width * ratio)), max(1, round(image.height * ratio))
    scale = np.array([width / image.width, height / image.height], np.float32)
    mask = np.zeros((height, width), np.uint8)
    outline = details.get('outline')
    if outline is not None and len(outline) >= 4:
        hull = cv2.convexHull(np.round(outline * scale).astype(np.int32))
        cv2.fillConvexPoly(mask, hull.reshape(-1, 2), 255)
    else:
        cv2.fillConvexPoly(mask, np.round(details['quad'] * scale).astype(np.int32), 255)
    # Cover the antialiased physical edge without reaching the desk beyond it.
    radius = max(1, round(min(width, height) * .004))
    return cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                                      (2 * radius + 1, 2 * radius + 1)))


def _enhance(image, quad=None, *, region_mask=None, neutralize_paper=False, feather=True):
    """Normalize broad shadows in bounded strips while retaining colored ink."""
    cv2, np = _numeric()
    if neutralize_paper:
        from processors.partial_scan_cleanup import enhance_paper
        return enhance_paper(image, region_mask, cv2, np, feather=feather)
    rgb = np.asarray(image, dtype=np.uint8)
    small = _thumbnail(image, 512)
    small_gray = cv2.cvtColor(np.asarray(small), cv2.COLOR_RGB2GRAY)
    background = cv2.morphologyEx(small_gray, cv2.MORPH_CLOSE,
                                  cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17)))
    background = cv2.GaussianBlur(background, (0, 0), 7)
    # Without a qualified sheet, lift only paper-like surfaces. A dark
    # photograph, screenshot or desk keeps its own tones instead of being
    # multiplied up to a washed-out grey by the shadow floor below.
    paper_weight = np.clip((background.astype(np.float32) - 96) * (255 / 64),
                           0, 255).astype(np.uint8)
    background = cv2.resize(background, image.size, interpolation=cv2.INTER_LINEAR)
    background = np.maximum(background, 75)
    result = np.empty_like(rgb)
    mask = None
    if region_mask is not None:
        mask = cv2.resize(np.asarray(region_mask, np.uint8), image.size,
                          interpolation=cv2.INTER_NEAREST)
    elif quad is not None:
        mask = np.zeros((image.height, image.width), np.uint8)
        cv2.fillConvexPoly(mask, np.round(quad).astype(np.int32), 255)
    weight = None if mask is not None else cv2.resize(
        paper_weight, image.size, interpolation=cv2.INTER_LINEAR)
    rows = max(1, 1_000_000 // image.width)
    for first in range(0, image.height, rows):
        last = min(image.height, first + rows)
        pixels = rgb[first:last].astype(np.float32)
        # One gain for all three channels, capped so no channel passes the
        # 245 that the contrast stretch maps to white: shadows lift without
        # clipping the hue out of skin, sky or coloured ink.
        gain = 245. / background[first:last].astype(np.float32)
        gain = np.minimum(gain, 245. / np.maximum(pixels.max(axis=2), 1.))
        adjusted = np.clip((pixels * gain[:, :, None] - 25) * (255 / 220), 0, 255)
        if mask is not None:
            outside = mask[first:last] == 0
            adjusted[outside] = pixels[outside]
        else:
            blend = weight[first:last].astype(np.float32) / 255
            # Saturated colour is a shirt or a sky, not shaded paper.
            chroma = pixels.max(axis=2) - pixels.min(axis=2)
            blend = blend * np.clip((40 - chroma) / 20, 0, 1)
            adjusted = adjusted * blend[:, :, None] + pixels * (1 - blend[:, :, None])
        result[first:last] = np.clip(adjusted + .5, 0, 255).astype(np.uint8)
    return Image.fromarray(result)


def prepare_image(image, *, auto_crop=True, enhance_text=True):
    """Return a new image and content-free outcome flags. Input is already RGB."""
    metadata = {'document_detected': False, 'cropped': False, 'enhanced': False}
    if not auto_crop and not enhance_text or min(image.size) < 96:
        return image, metadata
    details, detected = _detect(image, details=True)
    metadata['document_detected'] = detected
    if not detected:
        if enhance_text:
            # The effect is a promise for every page, like a scanner app's
            # filter: lift shadows and sharpen contrast across the whole frame.
            image = _enhance(image)
            metadata['enhanced'] = True
        return image, metadata
    if details is not None and details.get('kind') == 'partial':
        if auto_crop:
            from processors.partial_scan_rectification import rectify_partial
            rectified = rectify_partial(image, details)
            if rectified is not None:
                image, geometry = rectified
                metadata.update(cropped=True, rectified=True, background_removed=True)
                if enhance_text:
                    from processors.partial_scan_cleanup import cleanup_paper
                    image = cleanup_paper(image, paper_mask=geometry.get('paper_mask'))
                    metadata['enhanced'] = True
                return image, metadata
        from processors.partial_document_scan import native_safe_crop_box
        box = native_safe_crop_box(image, details) if auto_crop else None
        removed = False
        if auto_crop:
            from processors.partial_scan_matte import remove_exterior
            image, removed = remove_exterior(image, details)
            metadata['background_removed'] = removed
            if removed:
                matte_box = details.get('matte_crop_box')
                if matte_box is not None:
                    box = (max(box[0], matte_box[0]), max(box[1], matte_box[1]),
                           min(box[2], matte_box[2]), min(box[3], matte_box[3]))
        if enhance_text:
            region = details.get('cleanup_foreground', details['partial_mask']) if removed else details['partial_mask']
            image = _enhance(image, region_mask=region, neutralize_paper=True,
                             feather=not removed)
            metadata['enhanced'] = True
        if box is not None and box != (0, 0, image.width, image.height):
            image = image.crop(box)
            if image.width * image.height > MAX_WARP_PIXELS:
                scale = math.sqrt(MAX_WARP_PIXELS / (image.width * image.height))
                width, height = max(2, int(image.width * scale)), max(2, int(image.height * scale))
                image = image.resize((width, height), Image.Resampling.LANCZOS)
            metadata['cropped'] = True
        return image, metadata
    quad = None if details is None else details['envelope']
    paper_mask = None
    if auto_crop and quad is not None:
        from processors.page_rectification import rectify_page
        cv2, np = _numeric()
        rectified = rectify_page(image, quad, cv2, np, qualified_quad=details['quad'],
                                 material_edges=details.get('material_edges', False))
        if rectified is None:
            # If an edge cannot be traced reliably, retain the enclosing crop's
            # conservative behavior rather than guessing through possible
            # writing. Its safety border of desk is whitened, never printed.
            image, paper_mask = _warp(image, quad, with_mask=True,
                                      outline=details.get('outline'))
        else:
            image = rectified
        metadata['cropped'] = True
    if enhance_text:
        if auto_crop:
            from processors.partial_scan_cleanup import cleanup_paper
            # Only a full-frame page can still show the scanner lid or desk
            # along the canvas edge; a rectified sheet's edge is its own.
            image = cleanup_paper(image, paper_mask=paper_mask,
                                  frame_guard=not metadata['cropped'])
        elif quad is not None:
            # Lift shadows on the observed sheet only; its straight envelope
            # would also whiten the desk beside a bowed edge.
            image = _enhance(image, region_mask=_paper_region(image, details))
        else:
            image = _enhance(image)
        metadata['enhanced'] = True
    return image, metadata
