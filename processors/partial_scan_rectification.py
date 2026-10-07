"""Straighten an independently qualified clipped page without synthesizing ink.

Observed free edges establish the paper pose. Boundary-connected line evidence
extends a clipped side, while unphotographed donors remain white. Geometry is
bounded to1280 pixels; the original RGB raster is sampled once in <=1M strips.
"""
import math

from PIL import Image

POSE_SIDE = 1280
MAX_PIXELS = 16_000_000
STRIP_PIXELS = 1_000_000


def _fit_edge(mask, np):
    height, width = mask.shape
    present = mask > 0
    depths = np.argmax(present, axis=0)
    coordinates = np.flatnonzero(present.any(axis=0) & (depths > 2)
        & (depths < height * .65))
    if coordinates.size < width * .35:
        return None
    indices = np.linspace(0, coordinates.size - 1,
        min(180, coordinates.size)).astype(int)
    x = coordinates[indices].astype(float)
    y = depths[coordinates[indices]].astype(float)
    tolerance = max(3., min(height, width) * .006)
    rng = np.random.default_rng(0)
    best = None
    for _ in range(192):
        sample = rng.choice(len(x), 5, replace=False)
        if np.ptp(x[sample]) < width * .35:
            continue
        coefficients = np.polyfit(x[sample] / width, y[sample], 4)
        fit = np.polyval(coefficients, x / width)
        good = np.abs(fit - y) <= tolerance
        if good.sum() < max(12, len(x) * .55):
            continue
        slope = np.polyval(np.polyder(coefficients), x[good] / width) / width
        if np.max(np.abs(slope)) > 1.:
            continue
        if best is None or good.sum() > best[0].sum():
            best = good, coefficients
    if best is None:
        return None
    good, coefficients = best
    for _ in range(2):
        coefficients = np.polyfit(x[good] / width, y[good], 4)
        good = np.abs(np.polyval(coefficients, x / width) - y) <= tolerance
    if good.sum() < max(12, len(x) * .55) or np.ptp(x[good]) < width * .40:
        return None
    return {'coefficients': coefficients, 'first': float(x[good].min()),
            'last': float(x[good].max()), 'support': float(good.mean()),
            'width': width, 'height': height}


def _edge_depth(edge, x, np):
    if 'trace' in edge:
        return np.interp(x, np.arange(edge['width']), edge['trace'])
    return np.polyval(edge['coefficients'], np.asarray(x) / edge['width'])


def _refine_top(rgb, edge, cv, np):
    """Align a segmentation proposal with the photographed material transition."""
    gray = cv.cvtColor(rgb, cv.COLOR_RGB2GRAY)
    lab = cv.cvtColor(rgb, cv.COLOR_RGB2LAB)
    material = cv.GaussianBlur(lab.astype(np.float32), (5, 5), 0)
    points = []
    radius = max(5, round(max(rgb.shape[:2]) / 512 * 3))
    for x in np.linspace(edge['first'], edge['last'], 97).astype(int):
        estimated = float(_edge_depth(edge, x, np))
        lo, hi = max(2, round(estimated) - radius), min(rgb.shape[0] - 3, round(estimated) + radius)
        if hi <= lo:
            continue
        profile = np.median(material[max(0, lo - 3):hi + 4,
            max(0, x - 3):min(rgb.shape[1], x + 4)], axis=1)
        gradient = np.linalg.norm(np.gradient(profile, axis=0), axis=1)
        choices = np.arange(lo, hi + 1)
        values = gradient[choices - max(0, lo - 3)]
        # Proximity distinguishes the observed outer edge from nearby writing.
        scores = values / (1 + np.abs(choices - estimated) / 3)
        selected = int(choices[np.argmax(scores)])
        if float(values[np.argmax(scores)]) >= 2:
            points.append((x, selected))
    if len(points) >= 50:
        points = np.asarray(points, float)
        coefficients = np.polyfit(points[:, 0] / edge['width'], points[:, 1], 4)
        errors = np.abs(np.polyval(coefficients, points[:, 0] / edge['width']) - points[:, 1])
        good = errors <= max(3., min(rgb.shape[:2]) * .006)
        if good.mean() >= .75:
            edge = dict(edge, coefficients=np.polyfit(points[good, 0]
                / edge['width'], points[good, 1], 4))
            # A gently curled page can have a shallow crease that no single
            # polynomial fits pixel-tightly. Use the independently supported
            # observations for the actual boundary, not a padded photo hull.
            trace = np.polyval(edge['coefficients'], np.arange(edge['width']) / edge['width'])
            first, last = round(points[good, 0].min()), round(points[good, 0].max())
            trace[first:last + 1] = np.interp(np.arange(first, last + 1),
                points[good, 0], points[good, 1])
            edge['trace'] = cv.GaussianBlur(trace.astype(np.float32)[None], (11, 1), 0)[0]
    return edge


def _side_line(rgb, mask, anchor, right, cv, np):
    """Use long physical edges that meet an independently observed free corner."""
    height, width = mask.shape
    ax, ay = anchor
    gray = cv.cvtColor(rgb, cv.COLOR_RGB2GRAY)
    edges = cv.Canny(cv.GaussianBlur(gray, (5, 5), 0), 8, 24)
    lines = cv.HoughLinesP(edges, 1, np.pi / 180, threshold=max(35, round(min(height, width) * .055)),
        minLineLength=max(40, round(min(height, width) * .16)), maxLineGap=max(10, round(min(height, width) * .03)))
    candidates = []
    allowance = max(12., width * .04)
    present = mask > 0
    depth = np.argmax(present[:, ::-1] if right else present, axis=1)
    observed_x = width - 1 - depth if right else depth
    observed_rows = np.flatnonzero(present.any(axis=1) & (depth > 2)
        & (depth < width * .25) & (np.arange(height) > ay + 12))
    reliable_profile = False
    if observed_rows.size >= height * .20:
        profile_line = np.polyfit(observed_rows, observed_x[observed_rows], 1)
        reliable_profile = abs(float(np.polyval(profile_line, ay)) - ax) <= allowance
    for row in ([] if lines is None else lines[:, 0]):
        x1, y1, x2, y2 = map(float, row)
        if abs(y2 - y1) < max(40, height * .12):
            continue
        slope = (x2 - x1) / (y2 - y1)
        if abs(slope) > .7:
            continue
        intercept = x1 - slope * y1
        distance = abs(intercept + slope * ay - ax)
        if distance > allowance or max(y1, y2) < ay + height * .10:
            continue
        if right and min(x1, x2) < width * .55 or not right and max(x1, x2) > width * .45:
            continue
        if reliable_profile:
            supported = np.abs(slope * observed_rows + intercept
                - observed_x[observed_rows]) <= max(8., width * .015)
            if float(supported.mean()) < .55:
                continue  # An internal column is not the physical paper side.
        # A boundary-connected secondary/printed line cannot displace the
        # already qualified corner by an entire document margin.
        length = math.hypot(x2 - x1, y2 - y1)
        candidates.append((length / (1 + distance / 4), slope, intercept))
    if candidates:
        score, slope, intercept = max(candidates)
        return float(slope), float(intercept), True
    # A genuinely clipped side may have no visible physical line. Camera-frame
    # continuation is an explicitly unknown geometric limit, never missing ink.
    pixels = (mask > 0).T if not right else (mask[:, ::-1] > 0).T
    depths = np.argmax(pixels, axis=0)
    values = width - 1 - depths if right else depths
    coordinates = np.flatnonzero(pixels.any(axis=0) & (depths > 2)
        & (np.arange(height) >= ay + 8))
    if coordinates.size >= height * .12:
        nearby = coordinates[np.abs(values[coordinates] - ax) < width * .30]
        if nearby.size >= height * .12:
            coefficients = np.polyfit(nearby, values[nearby], 1)
            if (abs(coefficients[0]) <= .7
                    and abs(float(np.polyval(coefficients, ay)) - ax) <= allowance):
                return float(coefficients[0]), float(coefficients[1]), True
    return 0., float(ax), False


def _orientation_matrix(side, width, height, np):
    if side == 0:
        return np.eye(3, dtype=np.float64)
    if side == 1:
        return np.array([[0, 1, 0], [-1, 0, width - 1], [0, 0, 1]], float)
    if side == 2:
        return np.array([[-1, 0, width - 1], [0, -1, height - 1], [0, 0, 1]], float)
    return np.array([[0, -1, height - 1], [1, 0, 0], [0, 0, 1]], float)


def _side_curve(rgb, slope, intercept, right, cv, np):
    """Refine a boundary-connected side; clipped portions keep its continuation."""
    height, width = rgb.shape[:2]
    baseline = slope * np.arange(height, dtype=np.float32) + intercept
    lab = cv.GaussianBlur(cv.cvtColor(rgb, cv.COLOR_RGB2LAB).astype(np.float32), (5, 5), 0)
    points = []
    radius = max(7, round(min(height, width) * .024))
    for y in np.linspace(0, height - 1, 97).astype(int):
        estimated = float(baseline[y])
        if not radius + 3 < estimated < width - 4 - radius:
            continue
        lo, hi = round(estimated) - radius, round(estimated) + radius
        profile = np.median(lab[max(0, y - 3):min(height, y + 4), lo - 2:hi + 3], axis=0)
        if profile.shape[0] < 2:
            continue
        gradient = np.linalg.norm(np.gradient(profile, axis=0), axis=1)
        choices = np.arange(lo, hi + 1)
        values = gradient[choices - (lo - 2)]
        score = values / (1 + np.abs(choices - estimated) / 4) ** 2
        index = int(np.argmax(score))
        if float(values[index]) >= 2:
            points.append((y, int(choices[index])))
    if len(points) < 12:
        return baseline
    points = np.asarray(points, float)
    coefficients = np.polyfit(points[:, 0] / height, points[:, 1], 3)
    good = np.abs(np.polyval(coefficients, points[:, 0] / height) - points[:, 1]) <= max(4., width * .008)
    if good.mean() < .70:
        return baseline
    values = baseline.copy()
    first, last = round(points[good, 0].min()), round(points[good, 0].max())
    values[first:last + 1] = np.interp(np.arange(first, last + 1), points[good, 0], points[good, 1])
    values = cv.GaussianBlur(values[None], (11, 1), 0)[0]
    return np.clip(values, baseline - width * .04, baseline + width * .04)


def _corroborated_stroke(rgb, x, y, width, height, component, cv, np):
    """Distinguish native ink from a quantized coarse-mask shading fragment.

    The upstream mask already qualifies writing. A lone reference still needs
    protection when its original raster contains a dark stroke; coarse gray
    glints alone must not veto the independently supported page geometry.
    """
    margin = max(5, min(24, max(width, height)))
    left, top = max(0, x - margin), max(0, y - margin)
    right, bottom = min(rgb.shape[1], x + width + margin), min(rgb.shape[0], y + height + margin)
    gray = cv.cvtColor(rgb[top:bottom, left:right], cv.COLOR_RGB2GRAY)
    kernel_size = min(31, max(9, 2 * min(width, height) + 1))
    background = cv.morphologyEx(gray, cv.MORPH_CLOSE,
        cv.getStructuringElement(cv.MORPH_ELLIPSE, (kernel_size, kernel_size)))
    residual = background.astype(np.int16) - gray.astype(np.int16)
    local_y, local_x = y - top, x - left
    strokes = residual[local_y:local_y + height, local_x:local_x + width][component]
    minimum = max(3, math.ceil(int(component.sum()) * .025))
    if int((strokes >= 40).sum()) >= minimum:
        return True
    # Faint references on a uniform matte surface can be only a few levels
    # darker. Compare the surrounding source material as well as the mark;
    # an edge/shadow fragment has varying context rather than this substrate.
    context = np.ones(gray.shape, bool)
    context[local_y:local_y + height, local_x:local_x + width] = False
    surrounding = gray[context]
    if surrounding.size < 20 or float(np.percentile(surrounding, 75)
        - np.percentile(surrounding, 25)) > 8:
        return False
    surrounding_residual = residual[context]
    noise = float(np.percentile(surrounding_residual, 90))
    return int((strokes >= max(5., noise + 4.)).sum()) >= minimum


def rectify_partial(image, details):
    """Return rectangular visible paper and bounded cleanup/audit metadata.

    ``None`` leaves uncertain/multiple documents with the existing safe path.
    Only the detector's independently qualified ``kind=partial`` can enter.
    """
    from processors.document_scan import _numeric
    cv, np = _numeric()
    foreground = details.get('paper_foreground')
    envelope = details.get('surface_envelope')
    if (details.get('kind') != 'partial' or details.get('source_size') != image.size
            or foreground is None or envelope is None
            or image.width * image.height > 40_000_000 or max(image.size) >= 32767):
        return None
    foreground = np.asarray(foreground, np.uint8)
    envelope = np.asarray(envelope, np.uint8)
    if (foreground.ndim != 2 or foreground.shape != envelope.shape
            or min(foreground.shape) < 2 or max(foreground.shape) > 512):
        return None
    scale = min(1., POSE_SIDE / max(image.size))
    small = image if scale == 1 else image.resize((max(2, round(image.width * scale)),
        max(2, round(image.height * scale))), Image.Resampling.LANCZOS)
    rgb = np.asarray(small, np.uint8)
    mask = cv.resize(cv.bitwise_and(foreground, envelope), small.size, interpolation=cv.INTER_NEAREST)
    models = []
    for side in range(4):
        edge = _fit_edge(np.rot90(mask, side), np)
        if edge is not None:
            span = (edge['last'] - edge['first']) / edge['width']
            models.append((span * edge['support'], side, edge))
    if not models:
        return None
    # Favor a horizontal free edge to preserve the photographed reading pose.
    horizontal = [model for model in models if model[1] in (0, 2)]
    score, side, top = max(horizontal or models)
    oriented_rgb = np.ascontiguousarray(np.rot90(rgb, side))
    oriented_mask = np.ascontiguousarray(np.rot90(mask, side))
    height, width = oriented_mask.shape
    top = _refine_top(oriented_rgb, top, cv, np)
    left_x, right_x = top['first'], top['last']
    top_left = (left_x, float(_edge_depth(top, left_x, np)))
    top_right = (right_x, float(_edge_depth(top, right_x, np)))
    left_slope, left_intercept, left_observed = _side_line(oriented_rgb, oriented_mask,
        top_left, False, cv, np)
    right_slope, right_intercept, right_observed = _side_line(oriented_rgb, oriented_mask,
        top_right, True, cv, np)
    # Intersect actual side evidence with the observed free-edge model. The
    # first/last RANSAC sample may be several pixels inside a blurred corner.
    for right, slope, intercept in ((False, left_slope, left_intercept),
                                   (True, right_slope, right_intercept)):
        x, y = top_right if right else top_left
        for _ in range(12):
            x = slope * y + intercept
            y = float(_edge_depth(top, x, np))
        if abs(x - (right_x if right else left_x)) <= width * .08:
            if right:
                right_x, top_right = float(x), (float(x), float(y))
            else:
                left_x, top_left = float(x), (float(x), float(y))
    # A second free edge, when genuinely observed, removes its exterior too.
    opposite = _fit_edge(np.rot90(oriented_mask, 2), np)
    bottom_y = height - 1.
    if opposite is not None:
        opposite = _refine_top(np.ascontiguousarray(np.rot90(oriented_rgb, 2)), opposite, cv, np)
        bottom_y = height - 1 - float(_edge_depth(opposite, width / 2, np))
    top_y = (top_left[1] + top_right[1]) / 2
    if bottom_y - top_y < height * .30:
        return None
    bottom_left = left_slope * bottom_y + left_intercept
    bottom_right = right_slope * bottom_y + right_intercept
    if (right_x - left_x < width * .35 or bottom_right - bottom_left < width * .35
            or bottom_right - bottom_left > width * 1.75
            or abs(bottom_left - left_x) > width * .55
            or abs(bottom_right - right_x) > width * .55):
        return None
    quad = np.array([top_left, top_right, (bottom_right, bottom_y),
        (bottom_left, bottom_y)], np.float32)
    natural_width = ((right_x - left_x) + (bottom_right - bottom_left)) / 2
    natural_height = bottom_y - top_y
    native_scale = image.width / small.width if side % 2 == 0 else image.height / small.height
    out_width = max(2, round(natural_width * native_scale))
    out_height = max(2, round(natural_height * native_scale))
    cap = min(1., math.sqrt(MAX_PIXELS / max(1, out_width * out_height)))
    out_width, out_height = max(2, round(out_width * cap)), max(2, round(out_height * cap))
    if out_width * out_height > MAX_PIXELS:
        out_height = max(2, MAX_PIXELS // out_width)
    destination = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32)
    inverse_pose = cv.getPerspectiveTransform(destination, quad)
    rotation_inverse = np.linalg.inv(_orientation_matrix(side, small.width, small.height, np))
    # Pixel centers share both photographed endpoints. A width ratio would
    # map the final bounded pixel to W-scale and omit the last native rows or
    # columns, including visible writing clipped by the camera frame.
    sx, sy = ((image.width - 1) / (small.width - 1),
              (image.height - 1) / (small.height - 1))
    left_curve = _side_curve(oriented_rgb, left_slope, left_intercept, False, cv, np)
    right_curve = _side_curve(oriented_rgb, right_slope, right_intercept, True, cv, np)

    def donor(u, v):
        denominator = inverse_pose[2, 0] * u + inverse_pose[2, 1] * v + inverse_pose[2, 2]
        x = (inverse_pose[0, 0] * u + inverse_pose[0, 1] * v + inverse_pose[0, 2]) / denominator
        y = (inverse_pose[1, 0] * u + inverse_pose[1, 1] * v + inverse_pose[1, 2]) / denominator
        # Fade observed curl corrections smoothly into the photographed body.
        straight_top = top_left[1] + u * (top_right[1] - top_left[1])
        top_x = left_x + u * (right_x - left_x)
        displacement = _edge_depth(top, top_x, np) - straight_top
        y = y + displacement * (1 - v) ** 2 + 1.2 * (1 - v)
        if opposite is not None:
            bottom_x = bottom_left + u * (bottom_right - bottom_left)
            curved_bottom = height - 1 - _edge_depth(opposite, width - 1 - bottom_x, np)
            y += (curved_bottom - bottom_y) * v ** 2 - 1.2 * v
        left_delta = np.interp(y, np.arange(height), left_curve) - (left_slope * y + left_intercept)
        right_delta = np.interp(y, np.arange(height), right_curve) - (right_slope * y + right_intercept)
        x += (left_delta + .8) * (1 - u) ** 2 + (right_delta - .8) * u ** 2
        return x.astype(np.float32), y.astype(np.float32)

    grid = np.linspace(0, 1, 97, dtype=np.float32)
    grid_x, grid_y = donor(grid[None], grid[:, None])
    jacobian = (np.diff(grid_x, axis=1)[:-1] * np.diff(grid_y, axis=0)[:, :-1]
                - np.diff(grid_x, axis=0)[:, :-1] * np.diff(grid_y, axis=1)[:-1])
    expected = max(1., natural_width * natural_height / 96 ** 2)
    if not np.isfinite(jacobian).all() or float(jacobian.min()) < expected * .20:
        return None
    # An internal frame or competing written spare sheet must not become the
    # dominant crop. Check the upstream independently qualified writing against
    # the actual observed boundary model, not only the inferred corner polygon.
    evidence = details.get('protected_evidence')
    if evidence is not None:
        evidence = np.asarray(evidence, np.uint8)
        if evidence.shape != foreground.shape:
            return None
        required = cv.resize(evidence, small.size, interpolation=cv.INTER_NEAREST) > 0
        required = np.rot90(required, side)
        yy, xx = np.nonzero(required)
        if yy.size:
            inside = ((xx >= np.interp(yy, np.arange(height), left_curve) - 2)
                & (xx <= np.interp(yy, np.arange(height), right_curve) + 2)
                & (yy >= _edge_depth(top, xx, np) - 2)
                & (yy <= bottom_y + 2))
            # A global percentage can discard an entire small reference or
            # written spare page beside a much denser dominant form. Apply
            # the retention allowance independently to every trusted mark.
            accounted = np.zeros(required.shape, np.uint8)
            accounted[yy[inside], xx[inside]] = 1
            _, components, stats, _ = cv.connectedComponentsWithStats(
                required.astype(np.uint8), connectivity=8)
            affected = []
            for label, (x, y, cw, ch, area) in enumerate(stats[1:], 1):
                if area < 5:
                    continue
                component = components[y:y + ch, x:x + cw] == label
                lost = int((component & (accounted[y:y + ch, x:x + cw] == 0)).sum())
                if lost > max(3, area * .10):
                    pixels = oriented_rgb[y:y + ch, x:x + cw][component]
                    saturation = cv.cvtColor(pixels.reshape(-1, 1, 3), cv.COLOR_RGB2HSV)[:, 0, 1]
                    colored = float((saturation > 85).mean()) >= .20
                    # Downsampling a tiny glint can produce a filled glyph-
                    # sized blob. A colored stroke, compound word/signature,
                    # or aligned reference group supplies independent writing
                    # evidence; isolated coarse gray flecks do not.
                    compound = max(cw, ch) >= 1.8 * min(cw, ch) and area >= 20
                    stroke = _corroborated_stroke(oriented_rgb, int(x), int(y),
                        int(cw), int(ch), component, cv, np)
                    affected.append((int(x), int(y), int(cw), int(ch), colored, compound, stroke))
            for index, (x, y, cw, ch, colored, compound, stroke) in enumerate(affected):
                if colored or compound or stroke:
                    return None
                for ox, oy, ow, oh, _, _, _ in affected[index + 1:]:
                    row = (abs(y + ch / 2 - oy - oh / 2) <= max(ch, oh) * .5
                        and abs(x + cw / 2 - ox - ow / 2) <= max(ch, oh) * 6
                        and .5 <= ch / oh <= 2.)
                    column = (abs(x + cw / 2 - ox - ow / 2) <= max(cw, ow) * .5
                        and abs(y + ch / 2 - oy - oh / 2) <= max(cw, ow) * 6
                        and .5 <= cw / ow <= 2.)
                    if row or column:
                        return None
            del accounted, components, stats
    source = np.asarray(image, np.uint8)
    if max(image.size) >= 32767 or max(out_width, out_height) >= 32767:
        return None
    result = np.empty((out_height, out_width, 3), np.uint8)
    u = np.linspace(0, 1, out_width, dtype=np.float32)[None, :]
    strip_rows = max(1, STRIP_PIXELS // out_width)
    for first in range(0, out_height, strip_rows):
        last = min(out_height, first + strip_rows)
        v = (np.arange(first, last, dtype=np.float32) / (out_height - 1))[:, None]
        x, y = donor(u, v)
        original_x = rotation_inverse[0, 0] * x + rotation_inverse[0, 1] * y + rotation_inverse[0, 2]
        original_y = rotation_inverse[1, 0] * x + rotation_inverse[1, 1] * y + rotation_inverse[1, 2]
        map_x, map_y = (original_x * sx).astype(np.float32), (original_y * sy).astype(np.float32)
        # Cubic interpolation against white outside the camera can undershoot
        # gray paper and invent a dark dotted frame-edge seam. Replicate for
        # filtering only, then explicitly leave all unphotographed donors white.
        sampled = cv.remap(source, map_x, map_y, cv.INTER_CUBIC,
            borderMode=cv.BORDER_REPLICATE)
        visible = ((map_x >= 0) & (map_x <= image.width - 1)
                   & (map_y >= 0) & (map_y <= image.height - 1))
        sampled[~visible] = 255
        result[first:last] = sampled
    result = np.ascontiguousarray(np.rot90(result, -side))
    output = Image.fromarray(result)
    # Bound the cleanup region by independently observed photographed material.
    # A white inferred continuation never becomes generated page content.
    mask_scale = min(1., 512 / max(out_width, out_height))
    mw, mh = max(2, round(out_width * mask_scale)), max(2, round(out_height * mask_scale))
    mx, my = donor(np.linspace(0, 1, mw, dtype=np.float32)[None],
                   np.linspace(0, 1, mh, dtype=np.float32)[:, None])
    paper_mask = cv.remap(oriented_mask, mx, my, cv.INTER_LINEAR,
        borderMode=cv.BORDER_CONSTANT, borderValue=0)
    paper_mask[(mx < 0) | (mx > width - 1) | (my < 0) | (my > height - 1)] = 0
    paper_mask = np.ascontiguousarray(np.rot90(paper_mask, -side))
    clipping = {'top': bool((mask[:2] > 0).mean() >= .20),
        'right': bool((mask[:, -2:] > 0).mean() >= .20),
        'bottom': bool((mask[-2:] > 0).mean() >= .20),
        'left': bool((mask[:, :2] > 0).mean() >= .20)}
    return output, {'rectified': True, 'source_size': image.size,
        'output_size': output.size, 'clipping': clipping, 'paper_mask': paper_mask,
        'observed_sides': (bool(left_observed), bool(right_observed))}
