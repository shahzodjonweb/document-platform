"""Fit a photographed paper perimeter, then sample the original image once.

Only an independently qualified, complete single page reaches this module.
Geometry is estimated at at most 1280 pixels; full-resolution sampling uses
bounded strips. Gentle curl correction is confined to the page's outer margin
so a bowed blank edge does not bend otherwise straight printed table rows.
"""
import math

from PIL import Image

POSE_SIDE = 1280
MAX_PIXELS = 16_000_000
STRIP_PIXELS = 1_000_000
EDGE_INFLUENCE = .20


def _trace_side(gray, cv2, np):
    height, width = gray.shape
    limit = min(round(height * .13), max(30, round(width * .18)))
    positions = np.linspace(width * .045, width * .955, 65).astype(int)
    rows = []
    for x in positions:
        profile = np.median(gray[:limit + 25, max(0, x - 5):min(width, x + 6)],
                            axis=1).astype(np.float32)
        profile = cv2.GaussianBlur(profile[:, None], (1, 5), 0)[:, 0]
        derivative = np.gradient(profile)
        peaks = []
        for depth in range(2, limit):
            outside = profile[max(0, depth - 16):max(1, depth - 6)]
            inside = profile[depth + 6:depth + 16]
            contrast = float(np.median(inside) - np.median(outside))
            if (contrast < 2 or derivative[depth] < .25
                    or derivative[depth] < max(derivative[depth - 1], derivative[depth + 1])):
                continue
            score = min(contrast, 35) * max(.15, min(float(derivative[depth]), 6))
            peaks.append((depth, score, contrast, float(derivative[depth]),
                          float(np.median(outside))))
        rows.append(peaks)
    return positions, rows, limit


def _trace_material_side(material, cv2, np):
    """Trace a qualified matte sheet even when its desk is brighter.

    Lab differences retain both luminance polarities and a tinted sheet's
    chromatic edge. Prefer the observed outer boundary over strong printing
    farther into the page; the independent writing guard still applies.
    """
    height, width = material.shape[:2]
    limit = min(round(height * .13), max(30, round(width * .18)))
    positions = np.linspace(width * .045, width * .955, 65).astype(int)
    weights = np.array([1., 2., 2.], np.float32)
    rows = []
    for x in positions:
        profile = np.median(material[:limit + 25, max(0, x - 5):min(width, x + 6)],
                            axis=1).astype(np.float32)
        profile = cv2.GaussianBlur(profile, (1, 5), 0)
        derivative = np.linalg.norm(np.gradient(profile, axis=0) * weights, axis=1)
        # Compare with nearby interior material, rather than a global color
        # that changes under shade. A strong flower/desk seam in the context
        # strip must not impersonate the paper's weaker physical perimeter.
        reference_samples = profile[round(limit * .6):limit + 25]
        reference_samples = reference_samples[
            reference_samples[:, 0] >= np.percentile(reference_samples[:, 0], 60)]
        reference = np.median(reference_samples, axis=0)
        material_weights = np.array([.5, 2., 2.], np.float32)
        peaks = []
        for depth in range(2, limit):
            outside = profile[max(0, depth - 16):max(1, depth - 6)]
            inside = profile[depth + 6:depth + 16]
            contrast = float(np.linalg.norm((np.median(inside, axis=0)
                                            - np.median(outside, axis=0)) * weights))
            inside_distance = float(np.linalg.norm((np.median(inside, axis=0)
                                                     - reference) * material_weights))
            outside_distance = float(np.linalg.norm((np.median(outside, axis=0)
                                                      - reference) * material_weights))
            if (contrast < 4 or derivative[depth] < .5
                    or inside_distance > 12 or outside_distance < inside_distance + 2
                    or derivative[depth] < max(derivative[depth - 1], derivative[depth + 1])):
                continue
            score = (min(contrast, 35) * max(.15, min(float(derivative[depth]), 6))
                     / (1 + (depth / 12) ** 2))
            peaks.append((depth, score, contrast, float(derivative[depth]),
                          float(np.median(outside[:, 0]))))
        rows.append(peaks)
    return positions, rows, limit


def _select_curve(positions, rows, width, limit, np, *, inward_of=None, tight_edge=False):
    selected = []
    for position, peaks in zip(positions, rows):
        if inward_of is not None:
            separation = max(8, limit * .075)
            peaks = [peak for peak in peaks
                     if peak[0] >= inward_of[int(position)] + separation and peak[4] >= 75]
        if peaks:
            selected.append((position, *max(peaks, key=lambda peak: peak[1])))
    required = .75 if inward_of is not None else .55
    if len(selected) < len(positions) * required:
        return None
    points = np.asarray(selected, dtype=float)
    keep = np.ones(len(points), bool)
    for _ in range(5):
        if keep.sum() < 8:
            return None
        coefficients = np.polyfit(points[keep, 0] / width, points[keep, 1], 4)
        error = points[:, 1] - np.polyval(coefficients, points[:, 0] / width)
        tolerance = max(3., float(np.median(np.abs(error[keep]))) * 3)
        keep = np.abs(error) < tolerance
    if (keep.sum() < len(positions) * (required - .05)
            or np.median(points[keep, 3]) < 4 or np.median(points[keep, 4]) < .5):
        return None
    values = np.polyval(coefficients, np.arange(width) / width)
    if np.any(values < -limit * .15) or np.any(values > limit * 1.15):
        return None
    # Account for small observed tear/blur variations around a matte edge's
    # smooth fit, bounded to three geometry pixels. Never add a desk border.
    padding = .8
    if tight_edge:
        residual = points[keep, 1] - np.polyval(coefficients, points[keep, 0] / width)
        padding += min(3., max(0., float(np.percentile(residual, 90))))
    return np.clip(values + padding, 0, limit).astype(np.float32)


def _retains_writing(rgb, outer, inner, side, cv2, np, *, paper_mask=None, material_color=None):
    """An inner shadow seam must never discard compact glyphs or colored ink."""
    oriented = np.rot90(rgb, side)
    gray = cv2.cvtColor(np.ascontiguousarray(oriented), cv2.COLOR_RGB2GRAY)
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE,
                                  cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31)))
    saturation = cv2.cvtColor(np.ascontiguousarray(oriented), cv2.COLOR_RGB2HSV)[:, :, 1]
    residual = background.astype(np.int16) - gray.astype(np.int16)
    chroma = oriented.max(axis=2).astype(np.int16) - oriented.min(axis=2).astype(np.int16)
    colored_ink = (saturation > 65) & (chroma > 25) & (residual > 12)
    if material_color is not None:
        # Warm paper and its camera-blended shadow have intrinsic saturation.
        # They are not colored pen strokes; actual colored ink must depart from
        # the independently qualified matte material as well as its luminance.
        lab = cv2.cvtColor(np.ascontiguousarray(oriented), cv2.COLOR_RGB2LAB)
        colored_ink &= np.linalg.norm(lab[:, :, 1:].astype(np.float32)
                                      - material_color, axis=2) >= 10
    ink = ((residual > 25) | colored_ink).astype(np.uint8)
    trusted = None if paper_mask is None else np.rot90(paper_mask, side) > 0
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    yy = np.arange(gray.shape[0])[:, None]
    removed = (yy > outer[None, :] + 2) & (yy < inner[None, :] - 1)
    if trusted is not None:
        # The initial envelope contains a few percent of bowed-edge context.
        # Guard a substantial inset (such as an internal frame); shallow initial
        # edge traces also include harmless camera-blended shadow fragments.
        # Every subsequent inner-seam replacement is checked without this limit.
        removed &= inner[None, :] > max(25, min(gray.shape) * .05)
    for label in range(1, count):
        x, y, width, height, area = stats[label]
        if (3 <= width <= min(gray.shape[1] * .15, height * 4)
                and 3 <= height <= width * 5 and area >= 5):
            pixels = labels[y:y + height, x:x + width] == label
            colored = bool(np.mean(colored_ink[y:y + height, x:x + width][pixels]) > .20)
            if trusted is not None and not colored:
                # Masking before connected-component analysis would fragment a
                # long paper/desk boundary into misleading glyph-sized pieces.
                if (x == 0 or y == 0 or x + width == gray.shape[1] or y + height == gray.shape[0]
                        or np.mean(trusted[y:y + height, x:x + width][pixels]) < .80
                        or np.median(residual[y:y + height, x:x + width][pixels]) < 45):
                    continue
            lost = int((pixels & removed[y:y + height, x:x + width]).sum())
            if lost > max(3, area * .10):
                return False
    return True


def _boundary_geometry(curves, width, height, np):
    top, right, bottom, left = curves

    def top_y(x):
        return np.interp(x, np.arange(width), top)

    def bottom_y(x):
        return height - 1 - np.interp(width - 1 - x, np.arange(width), bottom)

    def left_x(y):
        return np.interp(height - 1 - y, np.arange(height), left)

    def right_x(y):
        return width - 1 - np.interp(y, np.arange(height), right)

    corners = []
    for initial, horizontal, vertical in [
            ((0, 0), left_x, top_y), ((width - 1, 0), right_x, top_y),
            ((width - 1, height - 1), right_x, bottom_y),
            ((0, height - 1), left_x, bottom_y)]:
        x, y = initial
        for _ in range(15):
            x, y = horizontal(y), vertical(x)
        corners.append((x, y))
    corners = np.asarray(corners, np.float32)

    def donor(u, v):
        tl, tr, br, bl = corners
        top_x = tl[0] + u * (tr[0] - tl[0])
        bottom_x = bl[0] + u * (br[0] - bl[0])
        left_y = tl[1] + v * (bl[1] - tl[1])
        right_y = tr[1] + v * (br[1] - tr[1])
        boundaries = [(top_x, bottom_x, left_x(left_y), right_x(right_y)),
                      (top_y(top_x), bottom_y(bottom_x), left_y, right_y)]
        influence = 1.
        for distance in (u, 1 - u, v, 1 - v):
            influence = influence * (1 - np.maximum(0, 1 - distance / EDGE_INFLUENCE) ** 2)
        influence = 1 - influence
        maps = []
        for axis, (top_edge, bottom_edge, left_edge, right_edge) in enumerate(boundaries):
            bilinear = ((1 - u) * (1 - v) * tl[axis] + u * (1 - v) * tr[axis]
                        + (1 - u) * v * bl[axis] + u * v * br[axis])
            curved = ((1 - v) * top_edge + v * bottom_edge
                      + (1 - u) * left_edge + u * right_edge - bilinear)
            low = min(tl[axis], bl[axis]) if axis == 0 else min(tl[axis], tr[axis])
            high = max(tr[axis], br[axis]) if axis == 0 else max(bl[axis], br[axis])
            baseline = low + (u if axis == 0 else v) * (high - low)
            maps.append((baseline + influence * (curved - baseline)).astype(np.float32))
        return maps

    # Check topology on a bounded grid, not a multi-megapixel Jacobian array.
    u = np.linspace(0, 1, 97, dtype=np.float32)[None, :]
    v = np.linspace(0, 1, 97, dtype=np.float32)[:, None]
    x, y = donor(u, v)
    jacobian = (np.diff(x, axis=1)[:-1] * np.diff(y, axis=0)[:, :-1]
                - np.diff(x, axis=0)[:, :-1] * np.diff(y, axis=1)[:-1])
    expected = max(1., (width - 1) * (height - 1) / 96 ** 2)
    if (not np.isfinite(jacobian).all() or float(jacobian.min()) < expected * .25
            or x.min() < 0 or y.min() < 0 or x.max() > width - 1 or y.max() > height - 1):
        return None
    return corners, donor


def rectify_page(image, envelope, cv2, np, *, qualified_quad=None, material_edges=False):
    """Return a boundary-fitted image, or None when refinement is uncertain."""
    center = envelope.mean(axis=0)
    pose_quad = center + (envelope - center) * 1.012
    pose_quad[:, 0] = np.clip(pose_quad[:, 0], 0, image.width - 1)
    pose_quad[:, 1] = np.clip(pose_quad[:, 1], 0, image.height - 1)
    tl, tr, br, bl = pose_quad
    pose_width = max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))
    pose_height = max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))
    ratio = min(1., POSE_SIDE / max(pose_width, pose_height))
    width, height = max(2, round(pose_width * ratio)), max(2, round(pose_height * ratio))
    destination = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1],
                            [0, height - 1]], np.float32)
    transform = cv2.getPerspectiveTransform(pose_quad.astype(np.float32), destination)
    # Use a bounded source thumbnail for geometry as well as a bounded pose.
    source_scale = min(1., POSE_SIDE / max(image.size))
    if source_scale == 1:
        small = image
    else:
        small = image.resize((max(2, round(image.width * source_scale)),
                              max(2, round(image.height * source_scale))), Image.Resampling.LANCZOS)
    sx, sy = image.width / small.width, image.height / small.height
    small_transform = transform @ np.diag([sx, sy, 1.])
    pose = cv2.warpPerspective(np.asarray(small), small_transform, (width, height),
                               flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    gray = cv2.cvtColor(pose, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(cv2.medianBlur(gray, 7), (5, 5), 0)
    material = None
    if material_edges:
        # This path is reserved for independently qualified, uniformly matte
        # paper. Keep geometry and all three color channels on the bounded pose.
        material = cv2.cvtColor(pose, cv2.COLOR_RGB2LAB).astype(np.float32)
        for channel in range(3):
            material[:, :, channel] = cv2.GaussianBlur(
                cv2.medianBlur(material[:, :, channel], 7), (5, 5), 0)
    paper_mask = None
    if qualified_quad is not None:
        # The validated four-corner interior distinguishes margin glyphs from
        # compact desk/shadow fragments in the enclosing geometry thumbnail.
        paper_mask = np.zeros(gray.shape, np.uint8)
        qualified = cv2.perspectiveTransform(qualified_quad[None].astype(np.float32), transform)[0]
        cv2.fillConvexPoly(paper_mask, np.round(qualified).astype(np.int32), 255)
    material_color = None
    if material is not None:
        interior = material if paper_mask is None else material[paper_mask > 0]
        clean = interior[:, :, 0] if paper_mask is None else interior[:, 0]
        colors = interior[:, :, 1:] if paper_mask is None else interior[:, 1:]
        material_color = np.median(colors[clean >= np.percentile(clean, 75) - 35], axis=0)
    curves = []
    for side in range(4):
        oriented = np.rot90(gray, side)
        if material is None:
            positions, rows, limit = _trace_side(oriented, cv2, np)
        else:
            positions, rows, limit = _trace_material_side(np.rot90(material, side), cv2, np)
        outer = _select_curve(positions, rows, oriented.shape[1], limit, np)
        if outer is None:
            return None
        if material is not None:
            tightened = _select_curve(positions, rows, oriented.shape[1], limit, np, tight_edge=True)
            if tightened is not None and _retains_writing(pose, outer, tightened, side, cv2, np,
                                                         material_color=material_color):
                outer = tightened
        if not _retains_writing(pose, np.zeros_like(outer), outer, side, cv2, np,
                                paper_mask=paper_mask, material_color=material_color):
            return None  # A strong printed frame must not become the paper edge.
        inner = _select_curve(positions, rows, oriented.shape[1], limit, np, inward_of=outer)
        if inner is not None and _retains_writing(pose, outer, inner, side, cv2, np,
                                                 material_color=material_color):
            outer = inner
        curves.append(outer)
    geometry = _boundary_geometry(curves, width, height, np)
    if geometry is None:
        return None
    corners, donor = geometry
    inverse = np.linalg.inv(transform)
    original_corners = cv2.perspectiveTransform(corners[None], inverse)[0]
    tl, tr, br, bl = original_corners
    output_width = (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2
    output_height = (np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2
    scale = min(1., math.sqrt(MAX_PIXELS / max(1., output_width * output_height)))
    output_width = max(2, round(output_width * scale))
    output_height = max(2, round(output_height * scale))
    if output_width * output_height > MAX_PIXELS:
        output_height = max(2, MAX_PIXELS // output_width)
    # remap has a 32767 dimension limit for its source too. A source ROI keeps
    # sampling single-pass and bounded for an unusually long original image.
    low = np.maximum(0, np.floor(pose_quad.min(axis=0) - 4)).astype(int)
    high = np.minimum(image.size, np.ceil(pose_quad.max(axis=0) + 5)).astype(int)
    if max(high - low) >= 32767 or max(output_width, output_height) >= 32767:
        return None
    source = np.asarray(image.crop((int(low[0]), int(low[1]), int(high[0]), int(high[1]))))
    result = np.empty((output_height, output_width, 3), np.uint8)
    u = np.linspace(0, 1, output_width, dtype=np.float32)[None, :]
    strip_rows = max(1, STRIP_PIXELS // output_width)
    for first in range(0, output_height, strip_rows):
        last = min(output_height, first + strip_rows)
        v = (np.arange(first, last, dtype=np.float32) / (output_height - 1))[:, None]
        x, y = donor(u, v)
        denominator = inverse[2, 0] * x + inverse[2, 1] * y + inverse[2, 2]
        map_x = ((inverse[0, 0] * x + inverse[0, 1] * y + inverse[0, 2]) / denominator - low[0]).astype(np.float32)
        map_y = ((inverse[1, 0] * x + inverse[1, 1] * y + inverse[1, 2]) / denominator - low[1]).astype(np.float32)
        result[first:last] = cv2.remap(source, map_x, map_y, cv2.INTER_CUBIC,
                                       borderMode=cv2.BORDER_REPLICATE)
    return Image.fromarray(result)
