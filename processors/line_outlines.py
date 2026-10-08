"""Straight-edge proposer for a complete sheet that forms no closed contour.

A sheet filling most of a phone photograph, held by a hand and carrying a
printed border, often leaves the contour sources nothing: the bright mask
bleeds into the frame, the closed edges trace the printed border, and the
segmentation fallback is cut by its own initialisation rectangle. Its four
edges are still long straight boundaries between two different surfaces,
visible above and below a hand and outside the printed border.

Long segments (LSD and Hough) are clustered into lines; a line is kept only
when the surfaces on its two sides differ; the dominant horizontals and
verticals are assembled into quads. Every quad must have each edge observed
along most of its length, every corner witnessed by an observed line, another
surface beyond every edge along nearly its whole length, and the sheet's own
material in every corner. Each quad then passes the same ``_candidate``
qualification as every other proposal, so written evidence, edge contrast and
exterior-writing vetoes still apply.
"""
from processors import document_scan as ds

LINE_MIN_COVER = .12       # of the frame dimension a line must run across
LINE_EDGE_COVER = .45      # of a quad edge that observed segments must cover
LINE_MAX_PER_SIDE = 8
LINE_MAX_CANDIDATES = 6
LINE_SIDE_LIGHT = 15       # gray levels between a sheet and what lies beyond its edge
LINE_SIDE_CHROMA = 6       # or a Lab chroma distance (tinted sheet on a bright desk)
LINE_SIDE_FRACTION = .80   # of the positions along an edge that must show a different surface
LINE_NEAR_FRACTION = .65   # of the positions where the strip right outside the edge already differs
LINE_CORNER = .10          # of the edge length: observed segments must reach this close to a corner
LINE_CORNER_INSET = .04    # of the shorter side: the sheet itself must occupy each corner
LINE_CORNER_PATCH = .02
LINE_BEND_ANGLE = 6.       # degrees: a neighbouring piece of one gently bowed edge
LINE_BEND_OFFSET = .04     # of the shorter frame side: how far such a piece may sit from a corner
LINE_CORNER_SLACK = .01    # of the shorter side: a corner this close outside the frame is on it


def _line_segments(cv2, np, blurred, edges, weak):
    """Straight segments from LSD on the blurred lightness and Hough on two Canny maps."""
    height, width = blurred.shape
    minimum = min(height, width) * .04
    pieces = []
    detector = cv2.createLineSegmentDetector(cv2.LSD_REFINE_NONE)
    found = detector.detect(blurred)[0]
    if found is not None:
        pieces.append(found.reshape(-1, 4))
    for source in (edges, weak):
        found = cv2.HoughLinesP(source, 1, np.pi / 180, 40,
                                minLineLength=minimum, maxLineGap=6)
        if found is not None:
            pieces.append(found.reshape(-1, 4).astype(np.float32))
    if not pieces:
        return np.zeros((0, 4), np.float32)
    segments = np.concatenate(pieces).astype(np.float32)
    lengths = np.hypot(segments[:, 2] - segments[:, 0], segments[:, 3] - segments[:, 1])
    return segments[lengths >= minimum]


def _cluster_lines(np, segments, shape):
    """Merge collinear segments into lines with their covered extent and members."""
    height, width = shape
    if len(segments) == 0:
        return [], []
    dx, dy = segments[:, 2] - segments[:, 0], segments[:, 3] - segments[:, 1]
    lengths = np.hypot(dx, dy)
    theta = np.arctan2(dy, dx) % np.pi
    normal = np.stack([-np.sin(theta), np.cos(theta)], axis=1)
    rho = normal[:, 0] * segments[:, 0] + normal[:, 1] * segments[:, 1]
    order = np.argsort(-lengths)
    tolerance_rho = max(3., min(height, width) * .006)
    tolerance_theta = np.deg2rad(2.5)
    clusters = []
    for index in order:
        t, r, length = float(theta[index]), float(rho[index]), float(lengths[index])
        for cluster in clusters:
            dt = abs(cluster['theta'] - t)
            dt = min(dt, np.pi - dt)
            if dt > tolerance_theta:
                continue
            n = cluster['normal']
            r0 = float(n[0] * segments[index, 0] + n[1] * segments[index, 1])
            r1 = float(n[0] * segments[index, 2] + n[1] * segments[index, 3])
            if abs(r0 - cluster['rho']) > tolerance_rho or abs(r1 - cluster['rho']) > tolerance_rho:
                continue
            cluster['members'].append(index)
            break
        else:
            clusters.append({'theta': t, 'rho': r, 'normal': normal[index], 'members': [index]})
    lines = [_fit_line(np, segments, lengths, theta, np.asarray(cluster['members']))
             for cluster in clusters]
    horizontals, verticals = [], []
    for line in lines:
        direction, cover = line['direction'], line['cover']
        horizontal = abs(direction[0]) >= np.cos(np.deg2rad(35))
        vertical = abs(direction[1]) >= np.cos(np.deg2rad(35))
        if horizontal and cover >= width * LINE_MIN_COVER:
            horizontals.append(line)
        elif vertical and cover >= height * LINE_MIN_COVER:
            verticals.append(line)
    return horizontals, verticals


def _fit_line(np, segments, lengths, theta, members):
    """Length-weighted straight fit through member segments, with their covered extent."""
    weights = lengths[members]
    directions = np.stack([np.cos(theta[members]), np.sin(theta[members])], axis=1)
    reference = directions[np.argmax(weights)]
    directions[(directions @ reference) < 0] *= -1
    direction = (directions * weights[:, None]).sum(axis=0)
    direction /= max(1e-6, float(np.linalg.norm(direction)))
    n = np.array([-direction[1], direction[0]], np.float32)
    points = np.concatenate([segments[members, :2], segments[members, 2:]])
    offset = float(np.average(points @ n, weights=np.repeat(weights, 2)))
    starts = segments[members, :2] @ direction
    ends = segments[members, 2:] @ direction
    intervals = np.stack([np.minimum(starts, ends), np.maximum(starts, ends)], axis=1)
    intervals = intervals[np.argsort(intervals[:, 0])]
    merged = []
    for a, b in intervals:
        if merged and a <= merged[-1][1] + 2:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([float(a), float(b)])
    cover = float(sum(b - a for a, b in merged))
    return {'direction': direction.astype(np.float32), 'normal': n, 'offset': offset,
            'intervals': np.asarray(merged, np.float32), 'cover': cover,
            'segments': segments[members], 'members': members}


def _side_values(np, gray, lab, points, normal, near, far):
    """Robust brightness/chroma of the surface on one side of a line: medians
    over a band of offsets along the normal, so a printed rule, a desk stripe
    or a shadow line at one offset does not stand in for the surface. `near`
    and `far` are per-point offsets; None when the band leaves the frame."""
    height, width = gray.shape
    light, chroma = [], []
    for step in np.linspace(0, 1, 8):
        distance = near + (far - near) * step
        sample = np.round(points + normal * distance[:, None]).astype(np.int32)
        valid = ((sample[:, 0] >= 0) & (sample[:, 0] < width)
                 & (sample[:, 1] >= 0) & (sample[:, 1] < height) & (far >= near))
        if int(valid.sum()) < 8:
            continue
        sample = sample[valid]
        light.append(gray[sample[:, 1], sample[:, 0]])
        chroma.append(lab[sample[:, 1], sample[:, 0], 1:])
    if len(light) < 4:
        return None
    light = np.concatenate(light).astype(np.float32)
    chroma = np.concatenate(chroma).astype(np.float32)
    return float(np.median(light)), np.median(chroma, axis=0)


def _frame_reach(np, points, outward, limit, width, height):
    """How far each point can move along `outward` and stay inside the frame."""
    reach = np.full(len(points), float(limit), np.float32)
    for axis, size in ((0, width), (1, height)):
        step = float(outward[axis])
        if step > 1e-6:
            reach = np.minimum(reach, (size - 1 - points[:, axis]) / step)
        elif step < -1e-6:
            reach = np.minimum(reach, -points[:, axis] / step)
    return np.floor(reach)


def _side_band(np, points, direction, gap, width, height):
    """Band offsets on one side: gap..2*gap, shrunk towards the frame edge but
    never starting closer than 3 px to the line."""
    far = np.minimum(float(2 * gap), _frame_reach(np, points, direction, 2 * gap, width, height))
    near = np.minimum(float(gap), np.maximum(3., far / 2))
    return near, far


def _distinct_sides(np, gray, lab, points, normal, gap, width, height):
    """True when the surfaces on the two sides of a line differ."""
    a = _side_values(np, gray, lab, points, normal, *_side_band(np, points, normal, gap, width, height))
    b = _side_values(np, gray, lab, points, -normal, *_side_band(np, points, -normal, gap, width, height))
    if a is None or b is None:
        return False
    return (abs(a[0] - b[0]) >= LINE_SIDE_LIGHT
            or float(np.linalg.norm(a[1] - b[1])) >= LINE_SIDE_CHROMA)


def _side_profile(np, gray, lab, points, normal, near, far):
    """Per-position band medians (brightness, chroma) on one side; None where
    the band leaves the frame."""
    height, width = gray.shape
    light = np.full((len(points), 8), np.nan, np.float32)
    chroma = np.full((len(points), 8, 2), np.nan, np.float32)
    for column, step in enumerate(np.linspace(0, 1, 8)):
        distance = near + (far - near) * step
        sample = np.round(points + normal * distance[:, None]).astype(np.int32)
        valid = ((sample[:, 0] >= 0) & (sample[:, 0] < width)
                 & (sample[:, 1] >= 0) & (sample[:, 1] < height) & (far >= near))
        sample = sample[valid]
        light[valid, column] = gray[sample[:, 1], sample[:, 0]]
        chroma[valid, column] = lab[sample[:, 1], sample[:, 0], 1:]
    usable = np.sum(~np.isnan(light), axis=1) >= 4
    return usable, np.nanmedian(light, axis=1), np.nanmedian(chroma, axis=1)


def _distinct_edge(np, gray, lab, points, outward, gap, width, height):
    """True when nearly every position along an edge shows a different surface
    beyond it: a printed border flush with the frame, or a sheet continuing
    past a rule, fails along part of its length. The strip right outside the
    edge must already differ at most positions: a printed block border a
    narrow margin inside the paper edge still has paper just beyond it."""
    inside = _side_profile(np, gray, lab, points, -outward,
                           *_side_band(np, points, -outward, gap, width, height))
    for near_band in (False, True):
        if near_band:
            far = np.minimum(float(gap), _frame_reach(np, points, outward, gap, width, height))
            near = np.minimum(3., far)
            outside = _side_profile(np, gray, lab, points, outward, near, far)
        else:
            outside = _side_profile(np, gray, lab, points, outward,
                                    *_side_band(np, points, outward, gap, width, height))
        usable = inside[0] & outside[0]
        if int(usable.sum()) < len(points) * .5:
            return False
        light = np.abs(inside[1] - outside[1]) >= LINE_SIDE_LIGHT
        chroma = np.linalg.norm(inside[2] - outside[2], axis=1) >= LINE_SIDE_CHROMA
        distinct = (light | chroma) & usable
        fraction = float(distinct.sum()) / float(usable.sum())
        if fraction < (LINE_NEAR_FRACTION if near_band else LINE_SIDE_FRACTION):
            return False
        # Taken as a whole, the strip is another surface, not more paper.
        inside_light = float(np.median(inside[1][usable]))
        outside_light = float(np.median(outside[1][usable]))
        inside_chroma = np.median(inside[2][usable], axis=0)
        outside_chroma = np.median(outside[2][usable], axis=0)
        if (abs(inside_light - outside_light) < LINE_SIDE_LIGHT
                and float(np.linalg.norm(inside_chroma - outside_chroma)) < LINE_SIDE_CHROMA):
            return False
    return True


def _corner_material(np, cv2, gray, lab, quad, interior, width, height):
    """The sheet's own surface occupies every corner of the quad.

    Observed edges may stop short of a corner because the background there
    is faint; a finger or another object over the corner occupies it instead,
    and guessing that corner could remove text under it."""
    inset = min(width, height) * LINE_CORNER_INSET
    half = max(3, int(min(width, height) * LINE_CORNER_PATCH))
    reach = max(half + 2, int(min(width, height) * .10))
    centre = quad.mean(axis=0)
    for corner in quad:
        towards = centre - corner
        point = corner + towards / max(1e-6, float(np.linalg.norm(towards))) * inset
        x, y = int(round(point[0])), int(round(point[1]))
        patch = (slice(max(0, y - half), min(height, y + half + 1)),
                 slice(max(0, x - half), min(width, x + half + 1)))
        region = gray[patch]
        if region.size < 9:
            return False
        # The sheet nearby, inside the quad: shading varies across a page,
        # so the corner is compared with its own neighbourhood.
        window = (slice(max(0, y - reach), min(height, y + reach + 1)),
                  slice(max(0, x - reach), min(width, x + reach + 1)))
        nearby = interior[window]
        if int(nearby.sum()) < 100:
            return False
        paper = float(np.percentile(gray[window][nearby], 75))
        material = np.median(lab[window][nearby][:, 1:].astype(np.float32), axis=0)
        if float(np.median(region)) < paper - 35:
            return False
        chroma = np.median(lab[patch][:, :, 1:].reshape(-1, 2).astype(np.float32), axis=0)
        if float(np.linalg.norm(chroma - material)) > 10:
            return False
    return True


def _corner_observed(np, lines, corner, other_corner, limit):
    """Some observed boundary line along this edge reaches close to the corner.

    The edge may bend at a crease, so a neighbouring line within `limit` of
    the corner, nearly parallel to the edge, counts; its observed extent must
    still come within a few percent of the edge length of the corner."""
    edge = other_corner - corner
    length = float(np.linalg.norm(edge))
    if length < 1:
        return False
    direction = edge / length
    tolerance = max(6., length * LINE_CORNER)
    parallel = np.cos(np.deg2rad(LINE_BEND_ANGLE))
    for line in lines:
        if abs(float(line['direction'] @ direction)) < parallel:
            continue
        if abs(float(corner @ line['normal']) - line['offset']) > limit:
            continue
        along = float(corner @ line['direction'])
        if any(s - tolerance <= along <= e + tolerance for s, e in line['intervals']):
            return True
    return False


def _boundary_lines(np, lines, gray, lab, gap):
    """Keep lines whose two sides differ: a surface boundary, not a printed rule."""
    height, width = gray.shape
    kept = []
    for line in lines:
        total = float(sum(e - s for s, e in line['intervals']))
        samples = []
        for s, e in line['intervals']:
            count = max(2, int(round(40 * (e - s) / max(1., total))))
            samples.append(np.linspace(s, e, count))
        along = np.concatenate(samples)
        points = along[:, None] * line['direction'][None] + line['offset'] * line['normal'][None]
        if _distinct_sides(np, gray, lab, points, line['normal'], gap, width, height):
            kept.append(line)
    kept.sort(key=lambda line: -line['cover'])
    return kept


def _intersect(np, a, b):
    matrix = np.array([a['normal'], b['normal']], np.float64)
    if abs(np.linalg.det(matrix)) < .3:
        return None
    return np.linalg.solve(matrix, [a['offset'], b['offset']]).astype(np.float32)


def _edge_cover(np, line, start, end):
    """Fraction of the edge between two corners covered by observed segments."""
    a, b = float(start @ line['direction']), float(end @ line['direction'])
    low, high = min(a, b), max(a, b)
    if high - low < 1:
        return 0.
    covered = 0.
    for s, e in line['intervals']:
        covered += max(0., min(e, high) - max(s, low))
    return covered / (high - low)


def _edge_outline(np, line, start, end):
    """Observed points along one edge: the member segments between its corners,
    ordered from start to end, so the outline follows a gently bowed edge."""
    direction = line['direction']
    a, b = float(start @ direction), float(end @ direction)
    low, high = min(a, b), max(a, b)
    points = []
    for x1, y1, x2, y2 in line['segments']:
        p, q = np.array([x1, y1], np.float32), np.array([x2, y2], np.float32)
        if float(p @ direction) > float(q @ direction):
            p, q = q, p
        s, e = float(p @ direction), float(q @ direction)
        if e < low - 2 or s > high + 2:
            continue
        count = max(2, int((e - s) // 6) + 1)
        for t in np.linspace(0, 1, count):
            point = p + (q - p) * t
            along = float(point @ direction)
            if low - 2 <= along <= high + 2:
                points.append((along, point))
    points.sort(key=lambda item: item[0])
    ordered = [point for _, point in points]
    if a > b:
        ordered.reverse()
    return ordered


def line_candidates(gray, saturation, edges, lab):
    """Assemble quads from dominant straight boundary lines; each still passes _candidate."""
    cv2, np = ds._numeric()
    height, width = gray.shape
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    weak = cv2.Canny(blurred, 10, 40)
    segments = _line_segments(cv2, np, blurred, edges, weak)
    horizontals, verticals = _cluster_lines(np, segments, gray.shape)
    gap = max(6, round(min(width, height) * .025))
    # Every boundary line can witness a corner; only the longest assemble quads.
    all_horizontals = _boundary_lines(np, horizontals, gray, lab, gap)
    all_verticals = _boundary_lines(np, verticals, gray, lab, gap)
    horizontals = all_horizontals[:LINE_MAX_PER_SIDE]
    verticals = all_verticals[:LINE_MAX_PER_SIDE]
    if len(horizontals) < 2 or len(verticals) < 2:
        return []
    corner_limit = min(width, height) * LINE_BEND_OFFSET
    slack = min(width, height) * LINE_CORNER_SLACK
    inset = max(2, min(width, height) * .004) + 1
    proposals = []
    for top in horizontals:
        yt = (top['offset'] - top['normal'][0] * width / 2) / top['normal'][1]
        for bottom in horizontals:
            if bottom is top:
                continue
            yb = (bottom['offset'] - bottom['normal'][0] * width / 2) / bottom['normal'][1]
            if yt >= yb:
                continue
            for left in verticals:
                xl = (left['offset'] - left['normal'][1] * height / 2) / left['normal'][0]
                for right in verticals:
                    if right is left:
                        continue
                    xr = (right['offset'] - right['normal'][1] * height / 2) / right['normal'][0]
                    if xl >= xr:
                        continue
                    corners = [_intersect(np, top, left), _intersect(np, top, right),
                               _intersect(np, bottom, right), _intersect(np, bottom, left)]
                    if any(c is None for c in corners):
                        continue
                    quad = np.asarray(corners, np.float32)
                    # A corner lying on the frame boundary (a sheet filling the
                    # photograph) is pulled just inside it; the enclosing pose
                    # is clipped to the frame downstream anyway. A corner any
                    # further out means a clipped sheet, left to the partial path.
                    for axis, size in ((0, width), (1, height)):
                        low = (quad[:, axis] < inset) & (quad[:, axis] > -slack)
                        high = (quad[:, axis] > size - 1 - inset) & (quad[:, axis] < size - 1 + slack)
                        quad[low, axis] = inset
                        quad[high, axis] = size - 1 - inset
                    if not cv2.isContourConvex(np.round(quad).astype(np.int32)):
                        continue
                    if not ds._geometry(quad, width, height):
                        continue
                    sides = (top, right, bottom, left)
                    covers = [_edge_cover(np, line, quad[idx], quad[(idx + 1) % 4])
                              for idx, line in enumerate(sides)]
                    if min(covers) < LINE_EDGE_COVER:
                        continue
                    # Every corner must be observed: both of its edges are seen
                    # right up to it. A finger over a corner hides where the
                    # edges end, and guessing that corner could remove text.
                    observed = True
                    for idx in range(4):
                        corner = quad[idx]
                        if (not _corner_observed(np, all_horizontals if idx in (0, 2) else all_verticals,
                                                 corner, quad[(idx + 1) % 4], corner_limit)
                                or not _corner_observed(np, all_verticals if idx in (0, 2) else all_horizontals,
                                                        corner, quad[(idx - 1) % 4], corner_limit)):
                            observed = False
                            break
                    if not observed:
                        continue
                    # Beyond every edge, along nearly its whole length, lies
                    # something other than the sheet.
                    distinct = True
                    for idx in range(4):
                        start, end = quad[idx], quad[(idx + 1) % 4]
                        edge = end - start
                        outward = (np.array([edge[1], -edge[0]]) / np.linalg.norm(edge)).astype(np.float32)
                        middle = start + np.linspace(.05, .95, 37)[:, None] * edge
                        if not _distinct_edge(np, gray, lab, middle, outward, gap, width, height):
                            distinct = False
                            break
                    if not distinct:
                        continue
                    interior = np.zeros(gray.shape, np.uint8)
                    cv2.fillConvexPoly(interior, np.round(quad).astype(np.int32), 255)
                    interior = cv2.erode(interior, np.ones((7, 7), np.uint8)) > 0
                    if int(interior.sum()) < 100 or not _corner_material(
                            np, cv2, gray, lab, quad, interior, width, height):
                        continue
                    area = float(abs(cv2.contourArea(quad)))
                    proposals.append((area * float(np.mean(covers)), quad, sides))
    proposals.sort(key=lambda item: -item[0])
    results = []
    for _, quad, sides in proposals[:LINE_MAX_CANDIDATES]:
        outline = []
        for idx, line in enumerate(sides):
            outline.extend(_edge_outline(np, line, quad[idx], quad[(idx + 1) % 4]))
        if len(outline) >= 8:
            # Observed edge points on the frame boundary are held just inside
            # it, like the corners, so the enclosing envelope stays in frame.
            outline = np.asarray(outline, np.float32).reshape(-1, 2)
            outline[:, 0] = np.clip(outline[:, 0], inset, width - 1 - inset)
            outline[:, 1] = np.clip(outline[:, 1], inset, height - 1 - inset)
        else:
            outline = None
        found = ds._candidate(ds._order(quad), gray, saturation, edges, lab=lab, outline=outline)
        if found is None or found.get('ambiguous', False):
            continue  # Exterior writing means the lines enclosed an internal block.
        duplicate = next((old for old in results
            if float(np.sum(old['mask'] & found['mask'])) /
            float(np.sum(old['mask'] | found['mask'])) > .85), None)
        if duplicate is None:
            results.append(found)
        elif found['area'] > duplicate['area']:
            duplicate.update(found)
    return results
