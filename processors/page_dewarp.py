"""Straighten a rectified page's interior from its own rules and text lines.

A traced perimeter makes the sheet's edges straight, but a fold, a bow in the
middle of the sheet or a hand lifting one corner leaves the printed table
rules and text baselines tilted or kinked between those edges. The page
carries its own evidence: long horizontal rules and chained glyph rows ought
to be level and vertical rules upright. A smooth displacement field on a
coarse grid is fitted to that evidence, validated by re-rendering the bounded
preview, and otherwise discarded, so a page without usable structures or
with an uncertain fit comes out exactly as it did before.

Both families are fitted: rows move up and down, columns sideways. When the
two agree on a turn of the whole content (a form printed or photographed a
little askew within its traced edges) the field holds that turn right up to
the edges instead of pinning them; where rules kink together along one line,
as at a fold, a crease term under a tent lets the field bend sharply there.
Fields are tried from the most complete to the plain levelling of rows, and
the first that passes every check is used.

Every array here is at most the pose preview (<= 1280 px on the long side);
the renderer evaluates the field one output strip at a time.
"""
import math

NODES_LONG = 16
MAX_SHIFT = .03          # of the page dimension: a larger correction is not trusted
STRUCTURES_MIN = 3       # level structures that must span most of the width ...
STRUCTURE_SPAN = .60     # ... over a good part of the height before anything moves
STRUCTURE_EXTENT = .40
VERTICALS_MIN = 2
VERTICAL_SPAN = .30
VERTICAL_PIECE = .05     # shortest piece of a vertical rule, of the height
FOLLOW_BREAK = .02       # a followed rule ends at a longer break, of its side
SAMPLE_STEP = 4
TEXT_WEIGHT = .5
SMOOTHING = 1.           # second-difference weight against one unit-weight rule sample
ANCHOR = 4.              # pull of the border node rows/columns towards zero (or the page's turn)
VERTICAL_ANCHOR = 1.     # the same for vertical rules, which often run close to the edges
VERTICAL_SMOOTHING = .6  # second-difference weight of the sideways component
VERTICAL_SLACK = 1.5     # px a followed vertical rule's wander may grow by in measurement
ROTATION_MIN = .002      # rule slopes below this are not read as a turn of the page
ROTATION_AGREEMENT = .35  # horizontal rise and vertical lean must agree this closely
FOLD_WIDTH = .1          # half-width of a crease's tent, of the side along the rules
FOLD_STEP = 2.           # px between the positions a kink is read at
FOLD_KINK = .004         # a fold kinks a rule by at least this share of its side ...
FOLD_KINK_PX = 3.        # ... and at least this many pixels
FOLD_RIDGE = .5          # pull of crease values towards zero, and their smoothing
FOLDS_MAX = 2
HUBER_PASSES = 3
HUBER_K = 1.345
SOLVE_BLOCK = 4096
DETERMINANT = (.85, 1.18)
INK_FLOOR = 4            # residual darkness below this is paper grain
BAND_MARK = .01          # side, of the page's short side, of the least ink a border band can lose
EXTERIOR_CAP = .015      # of the short side: a darker run deeper than this is print
EXTERIOR_CHROMA = 25
PRINTED_TILT = .3        # a neighbour within this share of a rule's tilt shares it
SHARED_WANDER = .5       # correlation of two uprights' positions that marks the paper's own wander


def _basis(positions, count, np):
    """Catmull-Rom weights of unit positions over `count` uniform nodes.

    An interpolating cubic keeps the fitted node values readable as pixel
    shifts while staying C1 across the grid, and the same weights serve the
    solver and the renderer, so what was validated is what gets rendered.
    """
    scaled = np.clip(np.asarray(positions, np.float64).ravel(), 0, 1) * (count - 1)
    cell = np.minimum(np.floor(scaled).astype(int), count - 2)
    t = scaled - cell
    t2, t3 = t * t, t * t * t
    weights = np.stack([(-t + 2 * t2 - t3) / 2, (2 - 5 * t2 + 3 * t3) / 2,
                        (t + 4 * t2 - 3 * t3) / 2, (-t2 + t3) / 2], axis=1)
    indices = np.clip(cell[:, None] + np.arange(-1, 3)[None, :], 0, count - 1)
    return indices, weights


def _basis_matrix(positions, count, np):
    indices, weights = _basis(positions, count, np)
    matrix = np.zeros((len(indices), count), np.float64)
    np.add.at(matrix, (np.repeat(np.arange(len(indices)), 4), indices.ravel()), weights.ravel())
    return matrix


def _tent(offsets, width, np):
    return np.maximum(0., 1 - np.abs(offsets) / width)


class Field:
    """Grid shifts as fractions of the page, evaluated separably in numpy.

    ``creases`` add what a smooth grid cannot bend: a sheet folded flat
    kinks every rule that crosses the fold at one line. Each crease is
    ``(component, position, width, values)``: component 0 shifts u across a
    fold along the rows at v = position, by a tent of half-width ``width``
    in v times a cubic of ``values`` over u; component 1 is the same for v
    across a fold down the columns at u = position.
    """

    def __init__(self, dx, dy, np, creases=()):
        self.dx, self.dy, self.np, self.creases = dx, dy, np, tuple(creases)

    def __call__(self, u, v):
        np = self.np
        along = _basis_matrix(u.ravel(), self.dy.shape[1], np)
        down = _basis_matrix(v.ravel(), self.dy.shape[0], np)
        du = down @ self.dx @ along.T
        dv = down @ self.dy @ along.T
        for component, position, width, values in self.creases:
            if component == 0:
                du = du + _tent(v.ravel() - position, width, np)[:, None] * (along @ values)[None, :]
            else:
                dv = dv + (down @ values)[:, None] * _tent(u.ravel() - position, width, np)[None, :]
        return du.astype(np.float32), dv.astype(np.float32)


def displaced(position, shift, np):
    """Unit positions moved by a field.

    A shift may reach past the traced edge: where that edge cut into the
    sheet, or a rule runs close to it, straightening the rule needs the few
    pixels just outside, which the pose still holds. Clamping instead would
    stretch one edge pixel over the gap. The composite map is checked to
    stay on the pose and orientation-preserving before any of it is used.
    """
    return np.clip(position + shift, -MAX_SHIFT, 1 + MAX_SHIFT)


def _running_median(values, window, np):
    window = max(1, int(window)) | 1
    if len(values) < 3 or window < 3:
        return np.asarray(values, np.float64).copy()
    padded = np.pad(np.asarray(values, np.float64), window // 2, mode='edge')
    return np.median(np.lib.stride_tricks.sliding_window_view(padded, window), axis=1)


def _ink(gray, cv2, np):
    """Print and pen as pixels well below their local paper, with a noise floor."""
    background = cv2.morphologyEx(cv2.medianBlur(gray, 5), cv2.MORPH_CLOSE,
                                  cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))
    residual = background.astype(np.int16) - gray.astype(np.int16)
    sigma = 1.4826 * float(np.median(np.abs(residual - np.median(residual))))
    return (residual > max(14., 3 * sigma)).astype(np.uint8), residual


def _follow(thin, along, across, np):
    """Extend a rule found by opening along the thin ink it continues as.

    A straight opening loses a rule where it bends, at a fold for instance,
    which is exactly where the correction matters. From each end the rule is
    followed one step at a time within two pixels of where it was, moving at
    most a pixel per step; a step where the ink there is thicker than a rule
    (a crossing rule, a touching glyph) or missing keeps the last position,
    and the rule ends after a break of FOLLOW_BREAK of the side.
    """
    height, width = thin.shape
    limit = max(3, round(width * FOLLOW_BREAK))
    order = np.argsort(along, kind='stable')
    along, across = along[order], across[order]
    found_along, found_across = [along], [across]
    for direction, column, level in ((1, along[-1], np.median(across[-5:])),
                                     (-1, along[0], np.median(across[:5]))):
        misses, steps, levels = 0, [], []
        column = int(column)
        while misses <= limit:
            column += direction
            if not 0 <= column < width:
                break
            centre = int(round(level))
            low, high = max(0, centre - 2), min(height, centre + 3)
            core = thin[low:high, column]
            if core.any() and int(thin[max(0, centre - 4):centre + 5, column].sum()) <= 4:
                position = float((core * np.arange(low, high)).sum() / core.sum())
                level += float(np.clip(position - level, -1, 1))
                steps.append(column)
                levels.append(level)
                misses = 0
            else:
                misses += 1
        found_along.append(np.asarray(steps, np.float64))
        found_across.append(np.asarray(levels, np.float64))
    along = np.concatenate(found_along)
    across = np.concatenate(found_across)
    order = np.argsort(along, kind='stable')
    return along[order], across[order]


def _inside(along, across, exterior, np):
    """Samples clear of the outermost pixels and of the desk exterior."""
    height = exterior.shape[0] if exterior is not None else None
    rows = np.round(across).astype(int)
    inside = rows >= 2
    if height is not None:
        inside &= rows <= height - 3
        clipped = np.clip(rows, 0, height - 1)
        inside &= exterior[clipped, np.round(along).astype(int)] == 0
    return inside


def _merge_followed(lines, width, np):
    """Join followed rules that turned out to be one: they overlap or nearly
    meet and agree on their position where they do."""
    lines = sorted(lines, key=lambda line: line[0][0])
    merged = []
    for along, across in lines:
        for index, (other_along, other_across) in enumerate(merged):
            if along[0] > other_along[-1] + width * FOLLOW_BREAK:
                continue
            start, stop = max(along[0], other_along[0]), min(along[-1], other_along[-1])
            if stop >= start:
                columns = np.arange(start, stop + 1)
                difference = np.abs(np.interp(columns, along, across)
                                    - np.interp(columns, other_along, other_across))
                agree = float(np.median(difference)) <= 1.5
            else:
                agree = abs(across[0] - other_across[-1]) <= 3
            if agree:
                columns = np.concatenate([other_along, along])
                levels = np.concatenate([other_across, across])
                unique, inverse = np.unique(columns, return_inverse=True)
                merged[index] = (unique.astype(np.float64),
                                 np.bincount(inverse, levels) / np.bincount(inverse))
                break
        else:
            merged.append((along, across))
    return merged


def _rule_structures(ink, cv2, np, *, upright=False, exterior=None):
    """Long horizontal rules as per-column centroids, chained across gaps.

    Horizontal rules keep the long pieces (a fifth of the width each) they
    were tuned with. A vertical rule (``upright``, read on the transposed
    page) is thinner in a photo, leans one pixel sideways every few dozen
    and is crossed by every row of its table, so it is opened with a pixel
    of slack on either side, accepted as shorter pieces, followed through
    its bends and kept when it spans a fifth of the height. Along the image
    edge the desk left beside the paper looks like a rule; samples on that
    ``exterior`` or on the outermost pixels are not evidence.
    """
    height, width = ink.shape
    thin = ink
    piece = VERTICAL_PIECE if upright else .2
    if upright:
        ink = cv2.dilate(ink, np.ones((3, 1), np.uint8))
    opened = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((1, max(3, width // 25)), np.uint8))
    closed = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, np.ones((1, 9), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)
    pieces = []
    for label in range(1, count):
        x, y, w, h, _ = stats[label]
        if w < width * piece or (h > height * .03 and not upright):
            continue
        component = labels[y:y + h, x:x + w] == label
        support = component.sum(axis=0)
        # A long leaning or kinked vertical rule spans more than its own
        # thickness across; how thick it is shows column by column.
        if upright and float(np.median(support[support > 0])) > max(8., height * .015):
            continue
        columns = np.flatnonzero(support)
        rows = (component * np.arange(h)[:, None]).sum(axis=0)[columns] / support[columns] + y
        pieces.append((x + columns, rows))
    pieces.sort(key=lambda part: part[0][0])
    chains = []
    for columns, rows in pieces:
        for chain in chains:
            gap = columns[0] - chain[-1][0][-1]
            if -width * .01 <= gap <= width * .04 and abs(rows[0] - chain[-1][1][-1]) <= height * .006:
                chain.append((columns, rows))
                break
        else:
            chains.append([(columns, rows)])
    lines = []
    for chain in chains:
        along = np.concatenate([part[0] for part in chain]).astype(np.float64)
        across = np.concatenate([part[1] for part in chain]).astype(np.float64)
        order = np.argsort(along, kind='stable')
        lines.append((along[order], across[order]))
    if upright:
        lines = _merge_followed([_follow(thin, along, across, np) for along, across in lines], width, np)
        lines = [(along[inside], across[inside]) for along, across in lines
                 for inside in [_inside(along, across, exterior, np)] if inside.sum() >= 2]
    structures = []
    for along, across in lines:
        if along.max() - along.min() < width * .2:
            continue
        structures.append({'along': along[::SAMPLE_STEP], 'across': across[::SAMPLE_STEP], 'weight': 1.})
    return structures


def _text_structures(ink, residual, cv2, np):
    """Text lines as glyph baselines, chained left to right."""
    from processors.document_scan import GLYPH_INK
    height, width = ink.shape
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    if count < 2:
        return []
    x, y, w, h, area = (stats[1:, index] for index in range(5))
    plausible = ((3 <= area) & (area <= ink.size * .02) & (3 <= h) & (h <= height * .15)
                 & (3 <= w) & (w <= np.minimum(width * .15, h * 4)) & (h <= w * 5)
                 & (area / (w * h) < .70))
    boxes = []
    for label in np.flatnonzero(plausible) + 1:
        x, y, w, h, _ = stats[label]
        strokes = residual[y:y + h, x:x + w][labels[y:y + h, x:x + w] == label]
        if float(np.median(strokes)) >= GLYPH_INK:
            boxes.append((int(x), int(y), int(w), int(h)))
    boxes.sort()
    open_chains, chains = [], []
    reach = height * .15 * 1.5
    for box in boxes:
        x, y, w, h = box
        center = y + h / 2
        still_open = []
        for chain in open_chains:
            lx, ly, lw, lh = chain[-1]
            if lx + lw < x - reach:
                chains.append(chain)
            else:
                still_open.append(chain)
        open_chains = still_open
        for chain in open_chains:
            lx, ly, lw, lh = chain[-1]
            reference = max(h, lh)
            gap = x - (lx + lw)
            if -reference * .3 <= gap <= 1.5 * reference and abs(center - (ly + lh / 2)) <= .4 * reference:
                chain.append(box)
                break
        else:
            open_chains.append([box])
    chains.extend(open_chains)
    structures = []
    for chain in chains:
        if len(chain) < 6:
            continue
        boxes = np.asarray(chain, np.float64)
        if boxes[:, 0].max() + boxes[-1, 2] - boxes[:, 0].min() < width * .2:
            continue
        bottoms = boxes[:, 1] + boxes[:, 3]
        centers = boxes[:, 0] + boxes[:, 2] / 2
        # Descenders hang below the line; a running median of the bottoms
        # finds the baseline the other glyphs share.
        level = _running_median(bottoms, 7, np)
        keep = np.abs(bottoms - level) <= .3 * float(np.median(boxes[:, 3]))
        if keep.sum() < 6:
            continue
        structures.append({'along': centers[keep], 'across': bottoms[keep], 'weight': TEXT_WEIGHT,
                           'height': float(np.median(boxes[:, 3]))})
    return structures


def _structures(preview, cv2, np):
    """Horizontal and vertical level structures of a page preview."""
    gray = cv2.cvtColor(preview, cv2.COLOR_RGB2GRAY)
    ink, residual = _ink(gray, cv2, np)
    horizontals = _rule_structures(ink, cv2, np) + _text_structures(ink, residual, cv2, np)
    # The desk sliver along a traced edge is whitened by the cleanup, never
    # printed: it is neither a vertical rule nor ink a field may not move.
    exterior = edge_exterior(preview, cv2, np)
    if exterior is None:
        exterior = np.zeros(gray.shape, np.uint8)
    exterior = cv2.dilate(exterior, np.ones((5, 5), np.uint8))
    residual = np.where(exterior > 0, 0, residual)
    verticals = _rule_structures(np.ascontiguousarray(ink.T), cv2, np, upright=True,
                                 exterior=np.ascontiguousarray(exterior.T))
    # Ink is weighed by darkness, not counted in pixels: a tilted rule
    # rasterizes into more anti-aliased pixels than the same rule level, so a
    # pixel count drops by a few percent when a page is straightened, whereas
    # the darkness it carries is conserved by resampling.
    return horizontals, verticals, np.where(residual > INK_FLOOR, residual, 0).astype(np.float64)


def _span(structure):
    return float(structure['along'].max() - structure['along'].min())


def _level(structure, np):
    return float(np.median(structure['across']))


def _deviation(structure, np):
    """How far a structure wanders from one level, ignoring a few outliers."""
    if len(structure['across']) < 3:
        return 0.
    smooth = _running_median(structure['across'], 5, np)
    return float(np.percentile(smooth, 95) - np.percentile(smooth, 5))


def _grid(shape):
    height, width = shape
    long_side = max(height, width)
    rows = max(4, round(NODES_LONG * height / long_side))
    columns = max(4, round(NODES_LONG * width / long_side))
    return rows, columns


def _regularizer(nodes, anchor_axis, np, anchor=ANCHOR, smoothing=SMOOTHING):
    """Second differences along both grid axes and soft anchors on the two
    border lines across `anchor_axis`, as a dense normal-equation block, and
    the mask of anchored nodes."""
    rows, columns = nodes
    index = np.arange(rows * columns).reshape(rows, columns)
    block = np.zeros((rows * columns, rows * columns), np.float64)
    stencils = []
    if columns >= 3:
        stencils.append(np.stack([index[:, :-2], index[:, 1:-1], index[:, 2:]], axis=-1).reshape(-1, 3))
    if rows >= 3:
        stencils.append(np.stack([index[:-2], index[1:-1], index[2:]], axis=-1).reshape(-1, 3))
    pattern = np.array([1., -2., 1.]) * smoothing
    for stencil in stencils:
        contributions = np.broadcast_to(np.outer(pattern, pattern), (len(stencil), 3, 3))
        np.add.at(block, (stencil[:, :, None], stencil[:, None, :]), contributions)
    anchored = np.zeros((rows, columns), bool)
    if anchor_axis == 0:
        anchored[0], anchored[-1] = True, True
    else:
        anchored[:, 0], anchored[:, -1] = True, True
    block[np.diag_indices_from(block)] += anchor ** 2 * anchored.ravel()
    return block, anchored


def _solve(structures, shape, nodes, np, *, vertical=False, anchor=ANCHOR, prior=None, creases=(),
           smoothing=SMOOTHING):
    """Node shifts (px) so every structure meets one level: B(x, y) d + c_i = t.

    Normal equations are accumulated with bincount from each sample's 16
    basis weights and its structure's level; three Huber passes let a crossing
    stroke or a descender stop pulling. The basis is re-read at the fitted
    level after the first pass, since the output row c_i is what samples the
    source at t, not the observed row itself.

    The border anchors pull towards ``prior`` (node shifts in px, zero by
    default). A prior that is affine across the page has no second
    differences, so it only decides what the evidence leaves open.

    Each crease (a position in px along the structures) adds one cubic of
    values across them, under a tent along them: smooth and pulled to zero
    like the grid, so it only bends where rules kink together. Returns the
    node shifts and, per crease, its values (px).
    """
    height, width = shape
    rows, columns = nodes
    node_count = rows * columns
    spread = columns if vertical else rows
    reach = FOLD_WIDTH * (height if vertical else width)
    extra = spread * len(creases)
    unknowns = node_count + extra + len(structures)
    along = np.concatenate([structure['along'] for structure in structures])
    target = np.concatenate([structure['across'] for structure in structures])
    member = np.concatenate([np.full(len(structure['along']), index)
                             for index, structure in enumerate(structures)])
    base_weight = np.concatenate([np.full(len(structure['along']), structure['weight'])
                                  for structure in structures])
    across = target.copy()
    regular = np.zeros((unknowns, unknowns), np.float64)
    regular[:node_count, :node_count], anchored = _regularizer(nodes, 1 if vertical else 0, np, anchor, smoothing)
    for fold in range(len(creases)):
        block = slice(node_count + fold * spread, node_count + (fold + 1) * spread)
        regular[block, block] = _regularizer((1, spread), 0, np, FOLD_RIDGE)[0]
        regular[block, block] += FOLD_RIDGE ** 2 * np.eye(spread)
    regular[np.diag_indices_from(regular)] += 1e-6
    pulled = np.zeros(unknowns, np.float64)
    if prior is not None:
        pulled[:node_count] = anchor ** 2 * anchored.ravel() * np.asarray(prior, np.float64).ravel()
    weight = base_weight.copy()
    for step in range(HUBER_PASSES):
        x, y = (across, along) if vertical else (along, across)
        column_index, column_weight = _basis(x / (width - 1), columns, np)
        row_index, row_weight = _basis(y / (height - 1), rows, np)
        index = (row_index[:, :, None] * columns + column_index[:, None, :]).reshape(-1, 16)
        value = (row_weight[:, :, None] * column_weight[:, None, :]).reshape(-1, 16)
        if creases:
            cross_index, cross_weight = _basis(x / (width - 1) if vertical else y / (height - 1), spread, np)
            for fold, position in enumerate(creases):
                index = np.concatenate([index, node_count + fold * spread + cross_index], axis=1)
                value = np.concatenate([value, cross_weight * _tent(along - position, reach, np)[:, None]], axis=1)
        index = np.concatenate([index, node_count + extra + member[:, None]], axis=1)
        value = np.concatenate([value, np.ones((len(value), 1))], axis=1)
        # Each sample touches 17 x 17 entries (four more per crease); blocks keep the outer
        # products a few megabytes however many rules a dense form carries.
        normal = regular.copy()
        for first in range(0, len(index), SOLVE_BLOCK):
            block = slice(first, first + SOLVE_BLOCK)
            pair = (index[block, :, None] * unknowns + index[block, None, :]).ravel()
            product = (weight[block, None, None] * value[block, :, None] * value[block, None, :]).ravel()
            normal += np.bincount(pair, weights=product,
                                  minlength=unknowns * unknowns).reshape(unknowns, unknowns)
        rhs = np.bincount(index.ravel(), weights=(weight[:, None] * value * target[:, None]).ravel(),
                          minlength=unknowns) + pulled
        solution = np.linalg.solve(normal, rhs)
        residual = (value * solution[index]).sum(axis=1) - target
        scale = max(.5, 1.4826 * float(np.median(np.abs(residual - np.median(residual)))))
        weight = base_weight * np.minimum(1., HUBER_K * scale / np.maximum(np.abs(residual), 1e-6))
        levels = solution[node_count + extra:]
        across = np.clip(levels[member], 0, (width if vertical else height) - 1)
    return (solution[:node_count].reshape(rows, columns),
            [solution[node_count + fold * spread:node_count + (fold + 1) * spread] for fold in range(len(creases))])


def _geometry_holds(field, shape, donor, pose_shape, np):
    """The field stays small, locally orientation-preserving and, composed
    with the Coons map, as well-behaved as the perimeter fit alone, landing
    on the pose or within the field's own reach around it."""
    height, width = shape
    u = np.linspace(0, 1, 97, dtype=np.float32)[None, :]
    v = np.linspace(0, 1, 97, dtype=np.float32)[:, None]
    du, dv = field(u, v)
    if not np.isfinite(du).all() or not np.isfinite(dv).all():
        return False
    if float(np.abs(du).max()) > MAX_SHIFT or float(np.abs(dv).max()) > MAX_SHIFT:
        return False
    shift_x, shift_y = du * (width - 1), dv * (height - 1)
    step_x, step_y = (width - 1) / 96, (height - 1) / 96
    j11 = 1 + np.diff(shift_x, axis=1)[:-1] / step_x
    j12 = np.diff(shift_x, axis=0)[:, :-1] / step_y
    j21 = np.diff(shift_y, axis=1)[:-1] / step_x
    j22 = 1 + np.diff(shift_y, axis=0)[:, :-1] / step_y
    determinant = j11 * j22 - j12 * j21
    if float(determinant.min()) < DETERMINANT[0] or float(determinant.max()) > DETERMINANT[1]:
        return False
    x, y = donor(displaced(u, du, np), displaced(v, dv, np))
    jacobian = (np.diff(x, axis=1)[:-1] * np.diff(y, axis=0)[:, :-1]
                - np.diff(x, axis=0)[:, :-1] * np.diff(y, axis=1)[:-1])
    pose_height, pose_width = pose_shape
    expected = max(1., (pose_width - 1) * (pose_height - 1) / 96 ** 2)
    # Straightening a rule near the traced edge may sample just past the
    # pose's own margin; the renderer reads that from the original photo.
    beyond = MAX_SHIFT * max(pose_height, pose_width)
    return bool(np.isfinite(jacobian).all() and float(jacobian.min()) >= expected * .25
                and x.min() >= -beyond and y.min() >= -beyond
                and x.max() <= pose_width - 1 + beyond and y.max() <= pose_height - 1 + beyond)


def _matched_deviations(before, after, shape, np):
    """(before, after, tolerance, long) for structures found again at the same
    level and extent; unmatched structures are simply not compared."""
    height, width = shape
    tolerance = max(4., .01 * height)
    pairs = []
    for structure in before:
        level, low, high = _level(structure, np), structure['along'].min(), structure['along'].max()
        best = None
        for candidate in after:
            overlap = (min(high, candidate['along'].max()) - max(low, candidate['along'].min()))
            distance = abs(_level(candidate, np) - level)
            if distance <= tolerance and overlap >= .5 * (high - low) and (best is None or distance < best[0]):
                best = (distance, candidate)
        if best is not None:
            # Glyph bottoms are quantized and a few samples long, so a text
            # line's measured wander jitters by a fraction of its glyph height
            # even when nothing moved; a rule is measured to the pixel.
            slack = max(1., .25 * structure['height']) if 'height' in structure else 1.
            pairs.append((_deviation(structure, np), _deviation(best[1], np), slack,
                          _span(structure) >= STRUCTURE_SPAN * width and not structure.get('printed')))
    return pairs


def _point_shifts(field, along, across, shape, np):
    """The field's shift (px) at each sample point, not on their grid."""
    height, width = shape
    du, dv = field((along / (width - 1)).astype(np.float32), (across / (height - 1)).astype(np.float32))
    return np.diagonal(du) * (width - 1), np.diagonal(dv) * (height - 1)


def _bends_text(field, after, shape, np):
    """Whether the field bends a text line it renders beyond its slack.

    Text found only after the warp has no partner to compare with, so each
    line is read back where the field took it from: its samples moved by
    the field's own shift at them. A line the field merely carried along
    reads as straight there as it does after; a level line the field
    tilted or waved reads straighter before, by the bend it was given.
    """
    for structure in after:
        if 'height' not in structure or len(structure['along']) < 3:
            continue
        along, across = structure['along'], structure['across']
        du, dv = _point_shifts(field, along, across, shape, np)
        source = {'along': along + du, 'across': across + dv}
        order = np.argsort(source['along'], kind='stable')
        source = {key: values[order] for key, values in source.items()}
        if _deviation(structure, np) - _deviation(source, np) > max(1., .25 * structure['height']):
            return True
    return False


def _improves(field, structures, render, shape, cv2, np, *, upright=False, levelling=True):
    """Re-render the preview and demand straighter structures with no lost ink.

    The median and 90th-percentile targets are read on the long structures
    that justified the run; every matched structure, long or short, must not
    get worse beyond its measurement slack; rows that were level already
    (not ``levelling``) only have to stay so. A field that also moves
    sideways (``upright``) must leave the long vertical rules found again
    straighter than they were, or as straight where they already were, and
    none of them worse. No text line may come out bent by the field,
    including lines only found after it (``_bends_text``).
    """
    horizontals, verticals, ink = structures
    rendered = render(field)
    after, after_verticals, ink_after = _structures(rendered, cv2, np)
    pairs = _matched_deviations(horizontals, after, shape, np)
    long_pairs = [pair for pair in pairs if pair[3]]
    if len(long_pairs) < STRUCTURES_MIN or len(pairs) < round(.75 * len(horizontals)):
        return None
    before_values = np.array([pair[0] for pair in long_pairs])
    after_values = np.array([pair[1] for pair in long_pairs])
    height = shape[0]
    if ((levelling and float(np.median(after_values)) > .6 * float(np.median(before_values)))
            or float(np.percentile(after_values, 90)) > max(1.5, .003 * height)
            or any(after_value - before_value > slack for before_value, after_value, slack, _ in pairs)):
        return None
    if _bends_text(field, after, shape, np):
        return None
    if upright:
        long_verticals = [structure for structure in verticals
                          if not structure.get('printed') and _span(structure) >= VERTICAL_SPAN * height]
        pairs = _matched_deviations(long_verticals, after_verticals, shape[::-1], np)
        before_median = float(np.median([pair[0] for pair in pairs])) if pairs else 0.
        straight = max(1.5, .002 * shape[1])
        if (len(pairs) < VERTICALS_MIN
                or float(np.median([pair[1] for pair in pairs])) > (
                    max(before_median, straight) if before_median < straight else .6 * before_median)
                or any(after_value - before_value > VERTICAL_SLACK for before_value, after_value, _, _ in pairs)):
            return None
    total_before, total_after = float(ink.sum()), float(ink_after.sum())
    if total_before == 0 or not .97 <= total_after / total_before <= 1.03:
        return None
    # Ink must not be pushed off the page. A text line merely crossing the
    # inner side of a border band is not a loss, so the band read after the
    # warp is widened by the largest shift the field makes.
    u = np.linspace(0, 1, 97, dtype=np.float32)[None, :]
    du, dv = field(u, u.T)
    reach = int(math.ceil(max(float(np.abs(du).max()) * (shape[1] - 1),
                              float(np.abs(dv).max()) * (height - 1)))) + 1
    band_y, band_x = max(1, round(.04 * height)), max(1, round(.04 * shape[1]))
    # Less than about one faint glyph of difference is speckle, not a loss.
    mark = (BAND_MARK * min(shape)) ** 2 * 40
    for side, band in enumerate((band_y, band_x, band_y, band_x)):
        before_band = _band_ink(np.rot90(ink, side), band, cv2, np)
        if _band_ink(np.rot90(ink_after, side), band + reach, cv2, np) < before_band - max(.03 * before_band, mark):
            return None
    return rendered


def _band_ink(ink, depth, cv2, np):
    """Ink in the first ``depth`` rows, leaving out marks on the outermost row.

    What touches the image edge is the traced rim or the desk beside it, not
    print the page could lose; a mark that a field pushes onto the edge stops
    counting, so it reads as lost, as it should.
    """
    strip = np.ascontiguousarray(ink[:depth])
    count, labels = cv2.connectedComponents((strip > 0).astype(np.uint8), connectivity=8)
    rim = np.unique(labels[0])
    return float(np.where(np.isin(labels, rim[rim > 0]), 0, strip).sum())


def _slope(structure, low, high, np):
    inside = (structure['along'] >= low) & (structure['along'] <= high)
    if inside.sum() < 3:
        return None
    across = _running_median(structure['across'][inside], 5, np)
    return float(np.polyfit(structure['along'][inside], across, 1)[0])


def _mark_printed_tilts(structures, shape, np):
    """Flag rules whose tilt is printed, so the field never levels them.

    Paper cannot turn a band of itself in-plane: a fold or bow tilts a rule
    together with the rules beside it over the same columns, and the tilt
    ramps from one rule to the next. A chart series or a slanted signature
    line is tilted on its own, with level rules directly above and below it
    across the columns it covers; so is a table pasted or ruled askew
    between lines of level text. Such a rule (or a run of rules sharing its
    tilt) is print. Only rules are judged, since glyph bottoms are too
    coarse to read a small slope from, but a text line long enough to
    cover half the rule shows whether it is level beside a clearly tilted
    rule, so text brackets as rules do. A flagged rule is left out of the
    fit and of the straightness targets, but is still checked for not
    getting worse.
    """
    height = shape[0]
    rules = [structure for structure in structures if 'height' not in structure
             and len(structure['along']) >= 3]
    # Rules first, so a rule's index is the same in both lists.
    neighbours_all = rules + [structure for structure in structures if 'height' in structure
                              and len(structure['along']) >= 6]
    levels = [_level(structure, np) for structure in neighbours_all]
    for index, structure in enumerate(rules):
        low, high = structure['along'].min(), structure['along'].max()
        span = high - low
        tilt = _slope(structure, low, high, np)
        if tilt is None or abs(tilt) * span < max(1.5, .002 * height, .5 * _deviation(structure, np)):
            continue
        bracketed = []
        for direction in (-1, 1):
            neighbours = sorted((other for other in range(len(neighbours_all))
                                 if direction * (levels[other] - levels[index]) > 0),
                                key=lambda other: abs(levels[other] - levels[index]))
            level = False
            for other in neighbours:
                first = max(low, neighbours_all[other]['along'].min())
                last = min(high, neighbours_all[other]['along'].max())
                if last - first < .5 * span:
                    continue
                mine, theirs = _slope(structure, first, last, np), _slope(neighbours_all[other], first, last, np)
                if mine is None or theirs is None or abs(theirs - mine) <= PRINTED_TILT * abs(mine):
                    continue
                level = abs(theirs) <= PRINTED_TILT * abs(mine)
                break
            bracketed.append(level)
        if all(bracketed):
            structure['printed'] = True
    return structures


def _support(horizontals, shape, np):
    """How many level structures span most of the width, or 0 when they do
    not cover enough of the height to justify a page-wide field."""
    height, width = shape
    qualifying = [structure for structure in horizontals
                  if not structure.get('printed') and _span(structure) >= STRUCTURE_SPAN * width]
    if len(qualifying) < STRUCTURES_MIN:
        return 0
    levels = [_level(structure, np) for structure in qualifying]
    if max(levels) - min(levels) < STRUCTURE_EXTENT * height:
        return 0
    return len(qualifying)


def _median_slope(structures, np):
    slopes = [_slope(structure, structure['along'].min(), structure['along'].max(), np)
              for structure in structures if 'height' not in structure]
    slopes = [slope for slope in slopes if slope is not None]
    return float(np.median(slopes)) if len(slopes) >= 2 else None


def _text_slope(texts, np):
    """Median slope of the text baselines, or None without two of them."""
    slopes = [_slope(text, text['along'].min(), text['along'].max(), np)
              for text in texts if 'height' in text]
    slopes = [slope for slope in slopes if slope is not None]
    return float(np.median(slopes)) if len(slopes) >= 2 else None


def _rotation_prior(levels, uprights, shape, nodes, np, texts=()):
    """Node shifts (px) that turn the page content back by the angle its
    rules agree on, as ``(dy, dx)``, or None.

    A form printed or copied askew on its sheet, or a sheet photographed a
    little turned within its traced edges, has every horizontal rule rising
    by the slope at which every vertical rule leans the other way. Only that
    agreement is read as a turn: a shear or a bow tilts the two families
    differently and is the grid's to straighten between pinned edges. For a
    turn the border anchors hold to the turned position instead, so the
    rules come out level and upright right up to the edges.

    The page's text lines (``texts``) must rise with the rules too: a table
    pasted or ruled askew on a page of level text is turned on its own, and
    turning the whole page for it would tilt every line of the text.
    """
    rising, leaning = _median_slope(levels, np), _median_slope(uprights, np)
    if rising is None or leaning is None:
        return None
    if (min(abs(rising), abs(leaning)) < ROTATION_MIN
            or abs(rising + leaning) > ROTATION_AGREEMENT * max(abs(rising), abs(leaning))):
        return None
    text = _text_slope(texts, np)
    if text is not None and abs(text - rising) > max(ROTATION_AGREEMENT * abs(rising), ROTATION_MIN):
        return None
    angle = (rising - leaning) / 2
    height, width = shape
    rows, columns = nodes
    across = np.linspace(0, width - 1, columns) - (width - 1) / 2
    down = np.linspace(0, height - 1, rows) - (height - 1) / 2
    return (np.repeat((angle * across)[None, :], rows, axis=0),
            np.repeat((-angle * down)[:, None], columns, axis=1))


def _shared_wander(uprights, least, np):
    """Whether two uprights that wander by ``least`` or more wander alike.

    A fold, a bow or a turn of the sheet moves the columns beside each
    other together, so their positions along a shared stretch rise and
    fall together. A hand-drawn divider or margin line wobbles on its own,
    and straightening it would only push the print beside it sideways.
    """
    wandering = [structure for structure in uprights if _deviation(structure, np) >= least]
    for index, first in enumerate(wandering):
        for second in wandering[index + 1:]:
            low = max(first['along'].min(), second['along'].min())
            high = min(first['along'].max(), second['along'].max())
            shorter = min(_span(first), _span(second))
            if high - low < .5 * shorter:
                continue
            grid = np.arange(low, high, SAMPLE_STEP, dtype=np.float64)
            if len(grid) < 5:
                continue
            a = np.interp(grid, first['along'], _running_median(first['across'], 5, np))
            b = np.interp(grid, second['along'], _running_median(second['across'], 5, np))
            if a.std() > 0 and b.std() > 0 and float(np.corrcoef(a, b)[0, 1]) > SHARED_WANDER:
                return True
    return False


def _creases(structures, length, np):
    """Positions (px along) where long rules kink together, as a fold does.

    The kink is read as the second difference of each rule's position over
    the crease tent's half-width. A fold makes it peak on one line, sharply
    above the rule's own level of bending; a bow bends a rule evenly and has
    no such peak, and is left to the smooth grid.
    """
    reach = FOLD_WIDTH * length
    half = max(2, int(round(reach / 2 / FOLD_STEP)))
    peaks = []
    for structure in structures:
        if 'height' in structure or _span(structure) < VERTICAL_SPAN * length:
            continue
        along = structure['along']
        grid = np.arange(along.min(), along.max(), FOLD_STEP)
        if len(grid) <= 2 * half + 2:
            continue
        across = np.interp(grid, along, _running_median(structure['across'], 5, np))
        kink = np.abs(across[:-2 * half] + across[2 * half:] - 2 * across[half:-half])
        best = int(np.argmax(kink))
        if kink[best] >= max(FOLD_KINK_PX, FOLD_KINK * length) and kink[best] >= 3 * float(np.median(kink)):
            peaks.append((float(kink[best]), float(grid[half + best])))
    found = []
    for _, position in sorted(peaks, reverse=True):
        if all(abs(position - other) >= 2 * reach for other in found):
            found.append(position)
    return found[:FOLDS_MAX]


def _candidates(fitted, levels, verticals, uprights, shape, nodes, np, *, levelling=True):
    """Fields to try in turn, most complete first, as (dx, dy, creases, upright).

    With enough vertical rules both shift components are fitted, first with
    the shared turn when the rules agree on one and with the folds the rules
    kink at, then between pinned edges, then without folds; the last resort
    levels the horizontal structures alone, as it always did, so a vertical
    fit that fails validation costs nothing but its check. A page whose rows
    are already level (not ``levelling``) has no last resort.
    """
    height, width = shape
    down, across = _creases(uprights, height, np), _creases(levels, width, np)
    # Every fold found, then only the sharpest of each direction, then none:
    # a kink read off one rule alone may be no fold at all.
    folds = [(down, across)]
    if len(down) > 1 or len(across) > 1:
        folds.append((down[:1], across[:1]))
    if down or across:
        folds.append(((), ()))
    options = []
    if len(uprights) >= VERTICALS_MIN:
        turn = _rotation_prior(levels, uprights, shape, nodes, np, fitted)
        for prior in ((turn,) if turn is not None else ()) + (None,):
            options.extend((prior, crease_set) for crease_set in folds)
    level_only = None
    for prior, (down, across) in options:
        dx, dx_creases = _solve(verticals, shape, nodes, np, vertical=True, anchor=VERTICAL_ANCHOR,
                                prior=None if prior is None else prior[1], creases=down,
                                smoothing=VERTICAL_SMOOTHING)
        dy, dy_creases = _solve(fitted, shape, nodes, np, prior=None if prior is None else prior[0],
                                creases=across)
        creases = ([(0, position / (height - 1), FOLD_WIDTH, values / (width - 1))
                    for position, values in zip(down, dx_creases)]
                   + [(1, position / (width - 1), FOLD_WIDTH, values / (height - 1))
                      for position, values in zip(across, dy_creases)])
        if prior is None and not across:
            level_only = dy
        yield dx, dy, creases, True
    if not levelling:
        return
    if level_only is None:
        level_only = _solve(fitted, shape, nodes, np)[0]
    yield np.zeros(nodes, np.float64), level_only, [], False


def _estimate(preview, structures, cv2, np, *, render, donor, pose_shape):
    shape = preview.shape[:2]
    height, width = shape
    horizontals, verticals, ink = structures
    if not _support(horizontals, shape, np):
        return None, None
    fitted = [structure for structure in horizontals if not structure.get('printed')]
    qualifying = [structure for structure in fitted if _span(structure) >= STRUCTURE_SPAN * width]
    deviations = [_deviation(structure, np) for structure in qualifying]
    levelling = float(np.percentile(deviations, 75)) >= max(1.5, .002 * height)
    verticals = [structure for structure in verticals if not structure.get('printed')]
    uprights = [structure for structure in verticals if _span(structure) >= VERTICAL_SPAN * height]
    # Level rows with leaning or kinked columns (a fold across the sheet
    # moves the columns sideways and leaves the rows level) need the
    # sideways component alone.
    # The wander must be the paper's, shared by neighbouring columns.
    straightening = (len(uprights) >= VERTICALS_MIN and float(np.percentile(
        [_deviation(structure, np) for structure in uprights], 75)) >= max(1.5, .002 * width)
        and _shared_wander(uprights, max(1.5, .002 * width), np))
    if not levelling and not straightening:
        return None, None
    nodes = _grid(shape)
    candidates = _candidates(fitted, qualifying, verticals, uprights, shape, nodes, np, levelling=levelling)
    while True:
        try:
            dx, dy, creases, upright = next(candidates)
        except (StopIteration, np.linalg.LinAlgError):
            return None, None
        field = Field(dx / (width - 1), dy / (height - 1), np, creases)
        if not _geometry_holds(field, shape, donor, pose_shape, np):
            continue
        rendered = _improves(field, structures, render, shape, cv2, np, upright=upright, levelling=levelling)
        if rendered is not None:
            return field, rendered


def _turned(field, np):
    """The same field with the page's axes swapped."""
    return Field(field.dy.T.copy(), field.dx.T.copy(), np,
                 [(1 - component, position, width, values) for component, position, width, values in field.creases])


def estimate_field(preview, cv2, np, *, render, donor, pose_shape):
    """Fit and validate an interior dewarp of a page preview.

    Returns ``(field, rendered_preview)``, or ``(None, None)`` whenever the
    page offers too little level structure, is already straight, or the fitted
    field fails any geometric or photometric check; the caller then renders
    the page exactly as the perimeter fit alone would.

    Nothing upstream turns a page shot sideways upright, and then its rules
    and text lines run down the preview. When the upright reading fails and
    the page carries more of that evidence sideways, the same fit runs on the
    transposed preview and its field is transposed back.
    """
    shape = preview.shape[:2]
    upright = _structures(preview, cv2, np)
    _mark_printed_tilts(upright[0], shape, np)
    _mark_printed_tilts(upright[1], shape[::-1], np)
    field, rendered = _estimate(preview, upright, cv2, np, render=render, donor=donor,
                                pose_shape=pose_shape)
    if field is not None:
        return field, rendered
    turned = np.ascontiguousarray(preview.transpose(1, 0, 2))
    sideways = _structures(turned, cv2, np)
    _mark_printed_tilts(sideways[0], turned.shape[:2], np)
    _mark_printed_tilts(sideways[1], shape, np)
    if _support(sideways[0], turned.shape[:2], np) <= _support(upright[0], shape, np):
        return None, None

    def render_turned(candidate):
        return np.ascontiguousarray(render(_turned(candidate, np)).transpose(1, 0, 2))

    def donor_turned(u, v):
        # Swapping both the inputs and the outputs keeps the composite map
        # orientation-preserving, so its Jacobian test reads the same.
        x, y = donor(v, u)
        return y, x

    field, rendered = _estimate(turned, sideways, cv2, np, render=render_turned, donor=donor_turned,
                                pose_shape=tuple(pose_shape)[::-1])
    if field is None:
        return None, None
    return _turned(field, np), np.ascontiguousarray(rendered.transpose(1, 0, 2))


def _deep_runs(depth, cap, np):
    """(first, last) column spans whose fringe reaches the cap."""
    deep = np.concatenate([[False], depth >= cap, [False]])
    edges = np.flatnonzero(np.diff(deep.astype(np.int8)))
    return zip(edges[::2], edges[1::2] - 1)


def edge_exterior(preview, cv2, np):
    """A mask of the desk sliver left along the traced perimeter, or None.

    Per side, the run of neutral pixels from the border that are clearly
    darker than the paper just inside counts as fringe. Where that run
    reaches the cap it is either a printed bar touching the edge or the
    deepest part of a desk wedge left by a bowed sheet edge, and only shape
    tells them apart: a wedge ramps out of a fringe of more than half the
    cap on the columns beside it and ends within twice the cap, whereas a
    bar rises sharply out of clean paper or runs deeper. A bar is left
    alone; a wedge keeps its depth, and every masked column keeps at least
    the depth it shows itself, so the running median cannot average the
    deepest part of a bulge away. One extra pixel covers the blended edge.
    The result is at preview size, for the caller to scale.
    """
    gray = cv2.cvtColor(preview, cv2.COLOR_RGB2GRAY)
    chroma = preview.max(axis=2).astype(np.int16) - preview.min(axis=2).astype(np.int16)
    height, width = gray.shape
    cap = max(2, round(min(height, width) * EXTERIOR_CAP))
    if 3 * cap >= min(height, width):
        return None
    reach = 2 * cap
    mask = np.zeros((height, width), np.uint8)
    for side in range(4):
        light = np.rot90(gray, side)
        color = np.rot90(chroma, side)
        paper = np.percentile(light[cap:3 * cap].astype(np.float32), 75, axis=0)
        threshold = paper - np.maximum(18., .1 * paper)
        fringe = ((light[:reach + 1].astype(np.float32) < threshold[None, :])
                  & (color[:reach + 1] < EXTERIOR_CHROMA))
        ends = ~fringe
        depth = np.where(ends.any(axis=0), ends.argmax(axis=0), reach + 1)
        observed = depth.copy()
        for first, last in _deep_runs(observed, cap, np):
            beside = observed[[index for index in (first - 1, last + 1) if 0 <= index < len(observed)]]
            wedge = (int(observed[first:last + 1].max()) <= reach
                     and beside.size and int(beside.max()) * 2 > cap)
            if not wedge:
                depth[first:last + 1] = 0
        smooth = np.round(_running_median(depth, round(light.shape[1] * .06), np)).astype(int)
        depth = np.where(smooth > 0, np.maximum(smooth, depth), 0)
        band = np.arange(reach + 1)[:, None] < (depth + 1)[None, :]
        band &= (depth > 0)[None, :]
        oriented = np.zeros(light.shape, np.uint8)
        oriented[:reach + 1] = band * 255
        mask |= np.rot90(oriented, -side)
    return mask if mask.any() else None


def exposed_exterior(preview, field, cv2, np):
    """A mask of desk the field brings in from beyond the traced edge, or None.

    Straightening a rule close to the edge may sample a few pixels past the
    traced perimeter, where the trace cut into the sheet or the desk shows.
    There a run from the border of pixels unlike the paper just inside, in
    tone or in colour, is desk: unlike ``edge_exterior`` a coloured run
    counts too, because it lies outside the traced sheet and cannot be a
    printed bar. Paper beyond the trace, and print on it, stays. The result
    is at preview size, for the caller to scale.
    """
    height, width = preview.shape[:2]
    u = np.linspace(0, 1, width, dtype=np.float32)[None, :]
    v = np.linspace(0, 1, height, dtype=np.float32)[:, None]
    du, dv = field(u, v)
    exposed = (u + du < 0) | (u + du > 1) | (v + dv < 0) | (v + dv > 1)
    if not exposed.any():
        return None
    gray = cv2.cvtColor(preview, cv2.COLOR_RGB2GRAY)
    cap = max(2, round(min(height, width) * EXTERIOR_CAP))
    if 3 * cap >= min(height, width):
        return None
    mask = np.zeros((height, width), np.uint8)
    for side in range(4):
        light = np.rot90(gray, side).astype(np.float32)
        color = np.rot90(preview, side).astype(np.float32)
        outside = np.rot90(exposed, side)
        reach = min(int(outside.sum(axis=0).max()), light.shape[0] - 1)
        if reach == 0:
            continue
        paper = np.percentile(light[cap:3 * cap], 75, axis=0)
        tone = np.percentile(color[cap:3 * cap], 75, axis=0)
        unlike = ((light[:reach + 1] < (paper - np.maximum(18., .1 * paper))[None, :])
                  | (np.abs(color[:reach + 1] - tone[None, :, :]).max(axis=2) >= EXTERIOR_CHROMA))
        fringe = unlike & outside[:reach + 1]
        ends = ~fringe
        depth = np.where(ends.any(axis=0), ends.argmax(axis=0), reach + 1)
        band = np.arange(reach + 1)[:, None] < (depth + 1)[None, :]
        band &= (depth > 0)[None, :]
        oriented = np.zeros(light.shape, np.uint8)
        oriented[:reach + 1] = band * 255
        mask |= np.rot90(oriented, -side)
    return mask if mask.any() else None
