"""Pros and cons variants: the two sides parted by a bar, carded, on tinted panels, under arrows or a centred head."""
from pptx.util import Inches

from ..slide_layouts import _paragraph_height, _text_lines, _units
from ..slides import WIDTH_SAFETY, _luminance, contrast_ratio
from . import variant
from .kit import (FOOT, LEFT, PRO, RIGHT, RULE, WIDTH, Z, arrow_points, badge, block, disc, eyebrow, figure,
                  header_band, header_center, header_compact, headline, hex_of, hues, inks, line, on, oval, point_text,
                  polygon, readable, rect, rule, sides, strong, triangle_points, vs)

NAME, POINT = 5, 20          # the classic drawer's word limits: a side's name, one point
SPACING = 1.2                # the points' leading
# (name, point) sizes, largest first: a slide takes the first at which both sides fit.
SCALES = ((24, 18), (24, 17), (22, 16), (22, 15), (21, 14), (20, 13), (20, 12))
GLYPHS = ('+', '–')


def _both(section, lines):
    """Whether the slide has points on both sides: a side with none leaves these layouts half empty."""
    pro = [str(item.get('value', '')).strip().lower() in PRO for item in section.get('items') or []
           if str(point_text(item)).strip()]
    return any(pro) and not all(pro)


# ---------------------------------------------------------------- measuring


def _clean(value, words=None):
    parts = str(value or '').split()
    return ' '.join(parts[:words] if words else parts)


def _need(ctx, width, paragraphs):
    """Inches `paragraphs` (as for kit.block) take in a box `width` wide, with block's own allowance."""
    zone = Z(0, 0, width, 1)
    total = 0.0
    for paragraph in paragraphs:
        if not paragraph:
            continue
        value = _clean(paragraph.get('text'), paragraph.get('words'))
        if not value:
            continue
        bold = bool(paragraph.get('bold')) or bool(paragraph.get('heading') and ctx.heading_bold)
        spec = dict(text=value, size=paragraph['size'], bold=bold, before=paragraph.get('before', 0),
                    after=paragraph.get('after', 0), spacing=paragraph.get('spacing', 1.15))
        if paragraph.get('bullet'):
            spec['bullet'] = paragraph['bullet']
        total += _paragraph_height(spec, zone)
    return (total + 4) / 72 if total else 0.0


def _natural(value, size):
    """Inches `value` takes on one line at `size` points, as the fitter measures it."""
    return 0.001 * size * _units(_clean(value, POINT)) * WIDTH_SAFETY / 72


def _pick(ctx, fits, scales=SCALES):
    """The first (name, point) sizes at which `fits(sizes)` holds, or None.

    Points are list items, so they are set no larger than the deck's own list
    size, except that they may reach 16 pt in a deck that sets its lists
    smaller.
    """
    cap = max(16, ctx.size)
    capped = []
    for name, point in scales:
        if (name, min(point, cap)) not in capped:
            capped.append((name, min(point, cap)))
    return next((sizes for sizes in capped if fits(sizes)), None)


def _choose(ctx, fits, scales=SCALES):
    """`_pick`'s sizes; when even the smallest do not fit, the slide is marked shortened.

    The variant cannot hold this content then, and variants.choose passes it over.
    """
    sizes = _pick(ctx, fits, scales)
    if sizes is None:
        ctx.shortened = True
        return scales[-1]
    return sizes


def _groups(ctx, section):
    """[(points, name), (points, name)]: each side's point texts and its name, the pros first."""
    return [([point_text(item) for item in items if str(point_text(item)).strip()], name)
            for items, name in sides(ctx, section)]


def _name(value, size, colour, *, align='left', after=0):
    return dict(text=value, words=NAME, size=size, floor=min(size, 16), colour=colour, bold=True, heading=True,
                spacing=1.1, align=align, after=after)


def _point(value, size, colour, *, align='left', bullet=None, marker=None, before=0):
    spec = dict(text=value, words=POINT, size=size, floor=12, colour=colour, spacing=SPACING, align=align,
                before=before)
    if bullet:
        spec.update(bullet=bullet, bullet_colour=marker or colour)
    return spec


def _whole(ctx, value, width, height, sizes):
    """The largest of `sizes` at which a name keeps every word on one line and fits `height` inches."""
    value = _clean(value, NAME)
    for size in sizes:
        if (all(_text_lines(word, size, Inches(width), bold=True) == 1 for word in value.split())
                and _need(ctx, width, [_name(value, size, 'ink')]) <= height):
            return size
    return sizes[-1]


def _gap(size):
    """The space between two points set at `size`, in inches."""
    return size * 0.75 / 72 + 0.08


def _shown(ctx, fill):
    """(fill, ink) for a large shape on the slide's ground: `fill` (role or hex), lifted off a dark ground.

    A dark accent on a dark deck (navy on near-black) all but vanishes; there
    the shape is lightened until it stands 2:1 from the ground. A light deck
    keeps its colours as they are: a pale fill on white still reads as a shape.
    """
    value, surface = hex_of(ctx, fill), hex_of(ctx, 'surface')
    if _luminance(surface) < 0.18 and contrast_ratio(value, surface) < 2.0:
        value = readable(ctx, value, 'surface', 2.0)
    return value, on(value)


def _sign(ctx, cx, cy, span, colour, plus):
    """A plus (two crossed bars) or a minus (one bar) centred at (cx, cy), `span` inches across."""
    bar = span * 0.26
    rect(ctx, (cx - span / 2, cy - bar / 2, span, bar), colour)
    if plus:
        rect(ctx, (cx - bar / 2, cy - span / 2, bar, span), colour)


# ---------------------------------------------------------------- 1. centre divider


@variant('pros_cons', 'centre_divider', accepts=_both)
def centre_divider(ctx, section, lines):
    """The two sides mirrored about a thick accent bar with a vs disc on its middle, each leaning in towards it."""
    groups = _groups(ctx, section)
    top = header_compact(ctx, section) + 0.2
    room = FOOT - top
    mid = LEFT + WIDTH / 2
    bar, clear = 0.16, 0.8
    width = WIDTH / 2 - clear
    lead = 0.36                     # the rule under each name
    paints = hues(ctx, 2)

    def heads(sizes):
        return max(_need(ctx, width, [_name(name, sizes[0], 'ink')]) for _, name in groups)

    def points(k, sizes):
        return [_need(ctx, width, [_point(value, sizes[1], 'ink')]) for value in groups[k][0]]

    def total(k, sizes):
        rows = points(k, sizes)
        return heads(sizes) + lead + sum(rows) + _gap(sizes[1]) * max(0, len(rows) - 1)
    sizes = _choose(ctx, lambda s: all(total(k, s) <= room - 0.1 for k in range(2)))
    tall = max(total(k, sizes) for k in range(2))
    head = heads(sizes)
    y0 = top + max(0.0, (room - tall) / 2)
    gap = _gap(sizes[1])
    rect(ctx, (mid - bar / 2, top, bar, room), _shown(ctx, 'accent')[0])
    for k in range(2):
        values, name = groups[k]
        paint = paints[k]
        align = 'right' if k == 0 else 'left'
        x = mid - clear - width if k == 0 else mid + clear
        edge = x + width if k == 0 else x            # the side nearest the bar
        toward = -1 if k == 0 else 1                 # from the bar, outwards
        block(ctx, (x, y0, width, head), [_name(name, sizes[0], paint['text'], align=align)], anchor='bottom')
        mark = 0.9
        rect(ctx, (edge - mark if k == 0 else edge, y0 + head + 0.12, mark, RULE), paint['fill'])
        y = y0 + head + lead
        for index, (value, h) in enumerate(zip(values, points(k, sizes))):
            if index:
                tick = y - gap / 2
                line(ctx, (edge, tick), (edge + toward * 0.45, tick), 'muted', 0.75)
            block(ctx, (x, y, width, h), [_point(value, sizes[1], 'ink', align=align)])
            y += h + gap
    size = 1.04
    cy = top + room / 2
    oval(ctx, disc(mid, cy, size + 0.3), 'surface')
    paint = inks(strong(ctx))
    badge(ctx, disc(mid, cy, size), vs(ctx), fill=paint['fill'], ink=paint['ink'], size=22, heading=True)


# ---------------------------------------------------------------- 2. point cards


@variant('pros_cons', 'point_cards', accepts=_both)
def point_cards(ctx, section, lines):
    """Every point on a card of its own with a coloured tab bearing a plus or a minus; the pros' cards tinted."""
    groups = _groups(ctx, section)
    gap, between = 0.35, 0.12
    width = (WIDTH - gap) / 2
    tab, pad_x, pad_y = 0.5, 0.22, 0.1
    inner = width - tab - 2 * pad_x
    styles = (inks('accent_soft'), inks('card'))
    paints = hues(ctx, 2)
    most = max(1, max(len(values) for values, _ in groups))

    def head(sizes):
        return max(_need(ctx, width, [_name(name, sizes[0], 'ink')]) for _, name in groups) + 0.14

    def card(sizes):
        return max([_need(ctx, inner, [_point(value, sizes[1], 'ink')]) for values, _ in groups for value in values]
                   or [0.4]) + 2 * pad_y

    def total(sizes, tall=None):
        return head(sizes) + most * (tall or card(sizes)) + between * (most - 1)

    def below(band):
        """Where the cards start under a band `band` inches tall."""
        return 0.62 + band + 0.3 - 0.08
    # A slim band for a heading of one line. One that takes two gets a deeper band to keep its size, unless
    # that would set the points smaller than the slim band lets them be.
    heading = _clean(section.get('heading'), 14)
    band = 1.25
    if _text_lines(heading, 24, Inches(WIDTH - 0.8), bold=ctx.heading_bold) > 1:
        slim = _pick(ctx, lambda s: total(s) <= FOOT - below(1.25) - 0.05)
        deep = _pick(ctx, lambda s: total(s) <= FOOT - below(1.55) - 0.05)
        band = 1.55 if deep is not None and (slim is None or deep[1] >= slim[1]) else 1.25
    top = header_band(ctx, section, fill=strong(ctx), height=band) - 0.08
    room = FOOT - top
    sizes = _choose(ctx, lambda s: total(s) <= room - 0.05)
    tall = card(sizes)
    # Brief points get roomier cards, up to a point, before the block is centred.
    spare = room - 0.05 - total(sizes)
    if spare > 0:
        tall = min(max(tall, 1.1 if most <= 2 else 0.9), tall + spare / most)
    used = total(sizes, tall)
    y0 = top + max(0.0, (room - used) * 0.45)
    name_h = head(sizes)
    for k in range(2):
        values, name = groups[k]
        style, paint = styles[k], paints[k]
        x = LEFT + k * (width + gap)
        block(ctx, (x, y0, width, name_h - 0.14), [_name(name, sizes[0], paint['text'])], anchor='bottom')
        y = y0 + name_h
        for value in values:
            rect(ctx, (x, y, width, tall), style['fill'])
            rect(ctx, (x, y, tab, tall), paint['fill'])
            _sign(ctx, x + tab / 2, y + tall / 2, 0.2, paint['ink'], k == 0)
            block(ctx, (x + tab + pad_x, y + pad_y, inner, tall - 2 * pad_y),
                  [_point(value, sizes[1], style['ink'])], anchor='middle')
            y += tall + between


# ---------------------------------------------------------------- 3. tone columns


@variant('pros_cons', 'tone_columns', accepts=_both)
def tone_columns(ctx, section, lines):
    """The heading down the left; the pros on a tinted panel, the cons on a card one, each headed by its count."""
    groups = _groups(ctx, section)
    gap, pad, count_w = 0.25, 0.36, 0.75
    full = FOOT - 0.62
    under = 0.3                     # from the head to the points: the rule sits in it
    fills = ('accent_soft', 'card')
    styles = [inks(fill) for fill in fills]
    # Each side's count, rule and markers in its own hue, made to read on its panel.
    marks = [readable(ctx, paint['fill'], fill) for paint, fill in zip(hues(ctx, 2), fills)]
    heading = _clean(section.get('heading'), 14)

    def paragraphs(k, size, colour='ink', marker='ink'):
        return [_point(value, size, colour, bullet=GLYPHS[k], marker=marker, before=size * 0.7 if index else 0)
                for index, value in enumerate(groups[k][0])]

    def plan(side):
        """The panels beside a heading column `side` inches wide: (inner, label, head_h, sizes or None)."""
        inner = (RIGHT - LEFT - side - 0.5 - gap) / 2 - 2 * pad
        # Both names at one size: the largest at which each word keeps to a line beside the count.
        label = min(_whole(ctx, name, inner - count_w, 1.3, (22, 20, 18, 16)) for _, name in groups)
        head_h = max([0.86] + [_need(ctx, inner - count_w, [_name(name, label, 'ink')]) for _, name in groups])
        room = full - 2 * pad - head_h - under
        sizes = _pick(ctx, lambda s: all(_need(ctx, inner, paragraphs(k, s[1])) <= room for k in range(2)))
        return inner, label, head_h, sizes
    # A long heading gets a wider column to keep its size, unless that would set the points smaller.
    side, layout = 2.9, plan(2.9)
    if _text_lines(heading, 26, Inches(2.9), bold=ctx.heading_bold) > 6:
        wide = plan(3.4)
        if wide[3] is not None and (layout[3] is None or wide[3][1] >= layout[3][1]):
            side, layout = 3.4, wide
    inner, label, head_h, sizes = layout
    if sizes is None:
        sizes = _choose(ctx, lambda s: False)
    x0 = LEFT + side + 0.5
    width = inner + 2 * pad
    used = max(_need(ctx, inner, paragraphs(k, sizes[1])) for k in range(2))
    # Short content: the panels close up round it and the whole page sits mid-frame, the heading level with
    # them. They stay as tall as the heading beside them (six lines at most: kit.headline shrinks it to that).
    wrapped = _text_lines(heading, 30, Inches(side), bold=ctx.heading_bold)
    beside = 0.63 + min(6, wrapped) * 30 * 1.08 / 72 + 0.15
    tall = min(full, max(3.2, beside, 2 * pad + head_h + under + used))
    y = 0.62 + (full - tall) / 2
    eyebrow(ctx, (LEFT, y, side, 0.3))
    rule(ctx, (LEFT, y + 0.4, 0.9, RULE))
    headline(ctx, section, (LEFT, y + 0.63, side, min(3.6, tall - 0.63)), size=30, lines=6, anchor='top')
    start = y + pad + head_h + under
    for k in range(2):
        values, name = groups[k]
        style, mark = styles[k], marks[k]
        x = x0 + k * (width + gap)
        rect(ctx, (x, y, width, tall), style['fill'])
        figure(ctx, (x + pad - 0.04, y + pad, count_w, head_h), str(len(values)), size=60, colour=mark,
               anchor='middle', words=1)
        block(ctx, (x + pad + count_w, y + pad, inner - count_w, head_h), [_name(name, label, style['ink'])],
              anchor='middle')
        rect(ctx, (x + pad, y + pad + head_h + 0.12, inner, 0.03), mark)
        block(ctx, (x + pad, start, inner, y + tall - pad - start), paragraphs(k, sizes[1], style['ink'], mark))


# ---------------------------------------------------------------- 4. arrow heads


@variant('pros_cons', 'arrow_heads', accepts=_both)
def arrow_heads(ctx, section, lines):
    """Two rows: the pros' name on an up block arrow, the cons' on a down one; each side's points in a grid by it."""
    groups = _groups(ctx, section)
    top = header_compact(ctx, section) + 0.15
    room = FOOT - top - 0.05
    wide, shaft = 2.95, 0.68
    stem = wide * shaft
    between = 0.3
    x1 = LEFT + wide + 0.5
    span = RIGHT - x1
    column_gap, row_gap = 0.45, 0.2
    mark, indent = 0.2, 0.36
    paints = hues(ctx, 2)
    # Both names at one size: the largest at which every word of either keeps to a line in the stem.
    label = min(_whole(ctx, name, stem - 0.2, 9.0, (22, 20, 18, 16, 15)) for _, name in groups)
    name_h = max(_need(ctx, stem - 0.2, [_name(name, label, 'ink', align='center')]) for _, name in groups)

    def head(high):
        return min(1.15, high * 0.5)

    def arrow(need):
        """The shortest arrow, 1.9 in at least, whose row holds `need` inches of points and whose stem the names."""
        high = max(1.9, need)
        while high - head(high) - 0.16 < name_h:
            high += 0.05
        return high

    def grid(k, size):
        values = groups[k][0]
        per = 1 if len(values) <= 1 else 2
        width = (span - column_gap * (per - 1)) / per
        rows = [values[index:index + per] for index in range(0, len(values), per)]
        heights = [max(_need(ctx, width - indent, [_point(value, size, 'ink')]) for value in row) for row in rows]
        return width, rows, heights

    def used(k, size):
        heights = grid(k, size)[2]
        return sum(heights) + row_gap * max(0, len(heights) - 1)

    def rows(size):
        """The two rows' heights: alike when they fit so, else each its own (a five-to-one split)."""
        own = [arrow(used(k, size)) for k in range(2)]
        even = max(own)
        return [even, even] if 2 * even + between <= room else own
    sizes = _choose(ctx, lambda s: sum(rows(s[1])) + between <= room)
    size = sizes[1]
    highs = rows(size)
    y = top + max(0.0, (room - sum(highs) - between) / 2)
    line_h = size * SPACING / 72
    for k in range(2):
        values, name = groups[k]
        paint, high = paints[k], highs[k]
        fill, ink = _shown(ctx, paint['fill'])
        tip = head(high)
        direction = 'up' if k == 0 else 'down'
        polygon(ctx, arrow_points((LEFT, y, wide, high), head=tip, shaft=shaft, direction=direction), fill)
        box = (LEFT + (wide - stem) / 2 + 0.1, y + (tip if k == 0 else 0) + 0.08, stem - 0.2, high - tip - 0.16)
        block(ctx, box, [_name(name, label, ink, align='center')], anchor='middle')
        width, cells, heights = grid(k, size)
        cy = y + (high - used(k, size)) / 2
        for row, row_h in zip(cells, heights):
            for column, value in enumerate(row):
                x = x1 + column * (width + column_gap)
                middle = cy + line_h / 2 + 0.02
                polygon(ctx, triangle_points((x, middle - mark * 0.42, mark, mark * 0.84), direction), paint['text'])
                block(ctx, (x + indent, cy, width - indent, row_h), [_point(value, size, 'ink')])
            cy += row_h + row_gap
        if k == 0:
            rule_y = y + high + between / 2
            line(ctx, (x1, rule_y), (RIGHT, rule_y), 'muted', 0.5)
        y += high + between


# ---------------------------------------------------------------- 5. centred header


@variant('pros_cons', 'centred_header', accepts=_both)
def centred_header(ctx, section, lines):
    """A centred heading over two columns whose names are centred on short rules; the points as + and – bullets."""
    groups = _groups(ctx, section)
    top = header_center(ctx, section) - 0.05
    room = FOOT - top
    gap = 1.2
    width = (WIDTH - gap) / 2
    after = 0.52                     # from the name to the list: the short rule sits in it
    paints = hues(ctx, 2)

    def points(k, size, marker='ink'):
        return [_point(value, size, 'ink', bullet=GLYPHS[k], marker=marker, before=size * 0.7 if index else 0)
                for index, value in enumerate(groups[k][0])]

    def heads(sizes):
        return max(_need(ctx, width, [_name(name, sizes[0], 'ink', align='center')]) for _, name in groups)

    def tallest(sizes):
        return heads(sizes) + after + max(_need(ctx, width, points(k, sizes[1])) for k in range(2))
    sizes = _choose(ctx, lambda s: tallest(s) <= room)
    head = heads(sizes)
    used = tallest(sizes)
    y = top + max(0.0, (room - used) * 0.42)
    for k in range(2):
        x = LEFT + k * (width + gap)
        values, name = groups[k]
        block(ctx, (x, y, width, head), [_name(name, sizes[0], 'ink', align='center')], anchor='bottom')
        rect(ctx, (x + width / 2 - 0.35, y + head + 0.17, 0.7, RULE), paints[k]['fill'])
        # Short points sit as a block under the name rather than at the column's left edge.
        hang = sizes[1] * 0.95 / 72
        natural = max(_natural(value, sizes[1]) for value in values) + hang + 0.12
        span = min(width, natural)
        list_h = _need(ctx, span, points(k, sizes[1]))
        block(ctx, (x + (width - span) / 2, y + head + after, span, max(list_h, used - head - after)),
              points(k, sizes[1], paints[k]['text']))
    middle = LEFT + width + gap / 2
    line(ctx, (middle, y + 0.05), (middle, y + used), 'muted', 0.75)
