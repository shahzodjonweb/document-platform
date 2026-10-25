"""Pros and cons variants: the two sides told apart by drawn plus and minus marks, panels, pills and a balance."""
from pptx.util import Inches

from ..layouts import PRO
from ..slide_layouts import _paragraph_height, _text_lines
from . import variant
from .kit import (FOOT, LEFT, RIGHT, RULE, WIDTH, Z, block, disc, eyebrow, header_band, header_compact, header_number,
                  header_side, headline, hex_of, hues, inks, line, on, oval, point_text, polygon, readable, rect, ring,
                  rule, rounded, sides, strong, text, triangle_points)

NAME, POINT = 5, 20                   # the classic drawer's word limits: a side's name and a point
SIZES = (18, 17, 16, 15, 14, 13, 12)  # a slide's points take the first of these at which every side fits
SPACING = 1.2                         # the points' leading, as the classic drawer sets them
SLACK = 4 / 72                        # what a fitted box needs beyond its lines
LIFT = 0.42                           # short content sits this share of the spare room down
# The longer side's share of the width, most even first: a 6-to-2 argument
# widens its column, as the classic drawer does, rather than drop to the floor.
SHARES = (0.5, 0.55, 0.6, 0.65, 0.7)


def _both(section, lines):
    """Whether the slide argues both sides (a column variant with one side empty would draw a bare column)."""
    values = [str(item.get('value') or '').strip().lower() for item in section.get('items') or []]
    return any(value in PRO for value in values) and any(value not in PRO for value in values)


# ---------------------------------------------------------------- measuring


def _need(ctx, width, paragraphs):
    """Inches `paragraphs` (as for kit.block) take in a box `width` wide, with block's own allowance."""
    zone = Z(0, 0, width, 1)
    total = 0.0
    for paragraph in paragraphs:
        value = ' '.join(str(paragraph.get('text') or '').split()[:paragraph.get('words') or None])
        if not value:
            continue
        bold = bool(paragraph.get('bold')) or bool(paragraph.get('heading') and ctx.heading_bold)
        spec = dict(text=value, size=paragraph['size'], bold=bold, before=paragraph.get('before', 0),
                    after=paragraph.get('after', 0), spacing=paragraph.get('spacing', 1.15))
        if paragraph.get('bullet'):
            spec['bullet'] = paragraph['bullet']
        total += _paragraph_height(spec, zone)
    return total / 72 + SLACK if total else 0.0


def _largest(holds, sizes=SIZES):
    """The first size in `sizes` at which `holds(size)`, or None if none does."""
    return next((size for size in sizes if holds(size)), None)


def _names(ctx, pairs, sizes, lines=2):
    """One size for both sides' names: (size, lines the longest takes, whether every word fits its line).

    The first of `sizes` at which each (name, width) in `pairs` takes at most
    `lines` lines, set bold, with no word wider than its box (a viewer would
    break it mid-word); else the last size, as it sets there.
    """
    def measure(size):
        rows, whole = 0, True
        for name, width in pairs:
            words = str(name or '').split()[:NAME]
            room = Inches(max(0.3, width))
            rows = max(rows, _text_lines(' '.join(words), size, room, bold=True))
            whole = whole and all(_text_lines(word, size, room, bold=True) == 1 for word in words)
        return rows, whole
    for size in sizes:
        rows, whole = measure(size)
        if rows <= lines and whole:
            return size, rows, True
    return (sizes[-1], *measure(sizes[-1]))


def _tall(rows, size, spacing=1.15):
    """The height a fitted box needs for `rows` lines at `size` points."""
    return (rows * size * spacing) / 72 + SLACK


def _divide(groups, total, gap, layout):
    """The two columns' widths and how `layout(widths)` sets them: (widths, size, details).

    `layout` returns (points' size or None if they do not fit, details). Even
    halves unless one side has two points or more over the other and a wider
    share gives it bigger type; then the most even share that sets the largest.
    """
    counts = [len(points) for points, _ in groups]
    heavy = 0 if counts[0] >= counts[1] else 1
    tried = []
    for share in SHARES if abs(counts[0] - counts[1]) > 1 else SHARES[:1]:
        shares = (share, 1 - share) if heavy == 0 else (1 - share, share)
        widths = [(total - gap) * part for part in shares]
        tried.append((widths, *layout(widths)))
    fitting = [size for _, size, _ in tried if size]
    if not fitting:
        widths, _, details = tried[-1]
        return widths, SIZES[-1], details
    best = max(fitting)
    return next(choice for choice in tried if choice[1] == best)


def _points(items, size, colour, marker, glyph='•', gap=0.5):
    """A side's points as kit.block paragraphs, one bullet each."""
    return [dict(text=point_text(item), words=POINT, size=size, floor=min(12, size), colour=colour, spacing=SPACING,
                 before=round(size * gap) if index else 0, bullet=glyph, bullet_colour=marker)
            for index, item in enumerate(items)]


def _settle(top, room, used, lift=LIFT):
    """Where content `used` inches tall starts in `room` inches below `top`."""
    return top + max(0.0, room - used) * lift


# ---------------------------------------------------------------- marks and colours


def _mark(ctx, cx, cy, span, colour, pro):
    """A plus (pro) or a minus centred at (cx, cy), `span` inches across, drawn as bars."""
    bar = span * 0.2
    rect(ctx, (cx - span / 2, cy - bar / 2, span, bar), colour)
    if pro:
        rect(ctx, (cx - bar / 2, cy - span / 2, bar, span), colour)


def _sign(ctx, box, fill, colour, pro, share=0.44):
    """A disc at `box` in `fill` carrying a plus or minus in `colour`."""
    oval(ctx, box, fill)
    x, y, w, h = box
    _mark(ctx, x + w / 2, y + h / 2, w * share, colour, pro)


def _seen(ctx, role, target=1.8):
    """`role`'s colour, moved just enough to show as a shape on the slide's ground; with the ink for a mark on it.

    A navy accent is almost the ground of a dark deck: a disc or fulcrum in it
    would all but vanish. A colour that already shows is left as it is.
    """
    fill = readable(ctx, role, 'surface', target)
    return fill, (inks(role)['ink'] if fill == hex_of(ctx, role) else on(fill))


def _rgb(ctx, role):
    value = hex_of(ctx, role)
    return tuple(int(value[k:k + 2], 16) for k in (0, 2, 4))


def _apart(ctx, one, other):
    """How far apart two roles' colours are (0 to 441)."""
    return sum((a - b) ** 2 for a, b in zip(_rgb(ctx, one), _rgb(ctx, other))) ** 0.5


def _against(ctx, fallback='card'):
    """The cons side's fill: deep or secondary, whichever stands out yet differs from the accent, else `fallback`."""
    first = strong(ctx, ('deep', 'secondary'))
    for role in (first, 'secondary' if first == 'deep' else 'deep'):
        if _apart(ctx, role, 'accent') > 110 and _apart(ctx, role, 'surface') > 110:
            return role
    return fallback


# ---------------------------------------------------------------- 1. split panels


@variant('pros_cons', 'split_panels', accepts=_both)
def split_panels(ctx, section, lines):
    """Two tall panels side by side, pros on the accent and cons on a strong or card fill, each under a sign disc."""
    top = header_compact(ctx, section) + 0.05
    room = FOOT - top
    gap, pad_x, pad_y, mark, after = 0.2, 0.4, 0.36, 0.66, 0.22
    groups = sides(ctx, section)
    paints = (inks('accent'), inks(_against(ctx)))

    def column(k, size):
        return _points(groups[k][0], size, paints[k]['ink'], paints[k]['ink'])

    def layout(widths):
        # The name beside the disc, one size for both, on two lines if it must.
        size, rows, whole = _names(ctx, [(name, w - 2 * pad_x - mark - after)
                                         for (_, name), w in zip(groups, widths)], (24, 22, 20, 18, 16))
        name = max(mark, _tall(rows, size))
        head = name + 0.36   # the name, the hairline under it, then the points
        budget = room - 2 * pad_y - head
        points = _largest(lambda s: all(_need(ctx, w - 2 * pad_x, column(k, s)) <= budget
                                        for k, w in enumerate(widths)))
        return points if whole else None, (size, name, head)
    widths, size, (name_size, name, head) = _divide(groups, WIDTH, gap, layout)
    tallest = max(_need(ctx, w - 2 * pad_x, column(k, size)) for k, w in enumerate(widths))
    start = _settle(top + pad_y, room - 2 * pad_y, tallest + head)
    x = LEFT
    for k, ((points, label), width) in enumerate(zip(groups, widths)):
        paint = paints[k]
        inner = width - 2 * pad_x
        rect(ctx, (x, top, width, room), paint['fill'])
        _sign(ctx, (x + pad_x, start + (name - mark) / 2, mark, mark), paint['ink'], paint['fill'], k == 0)
        text(ctx, (x + pad_x + mark + after, start, inner - mark - after, name), label, words=NAME, size=name_size,
             floor=min(12, name_size), colour=paint['ink'], bold=True, heading=True, anchor='middle')
        line(ctx, (x + pad_x, start + name + 0.18), (x + width - pad_x, start + name + 0.18), paint['muted'], 0.75)
        block(ctx, (x + pad_x, start + head, inner, top + room - pad_y - start - head), column(k, size))
        x += width + gap


# ---------------------------------------------------------------- 2. sign discs


@variant('pros_cons', 'sign_discs', accepts=_both)
def sign_discs(ctx, section, lines):
    """No panels: a large plus disc in the accent and a minus disc in a strong fill head the two columns of bullets."""
    top = header_band(ctx, section, fill='accent_soft', height=1.55)
    room = FOOT - top
    gap, mark, after = 0.8, 1.0, 0.3
    groups = sides(ctx, section)
    fills = ('accent', _against(ctx, strong(ctx, ('deep', 'secondary'))))
    signs = [_seen(ctx, fill) for fill in fills]

    def column(k, size):
        return _points(groups[k][0], size, 'ink', readable(ctx, fills[k]))

    def layout(widths):
        size, rows, whole = _names(ctx, [(name, w - mark - after) for (_, name), w in zip(groups, widths)],
                                   (28, 26, 24, 22, 20, 18))
        name = max(mark, _tall(rows, size))
        head = name + 0.32
        points = _largest(lambda s: all(_need(ctx, w, column(k, s)) <= room - head for k, w in enumerate(widths)))
        return points if whole else None, (size, name, head)
    widths, size, (name_size, name, head) = _divide(groups, WIDTH, gap, layout)
    tallest = max(_need(ctx, w, column(k, size)) for k, w in enumerate(widths))
    start = _settle(top, room, tallest + head)
    x = LEFT
    for k, ((points, label), width) in enumerate(zip(groups, widths)):
        fill, ink = signs[k]
        _sign(ctx, (x, start + (name - mark) / 2, mark, mark), fill, ink, k == 0)
        text(ctx, (x + mark + after, start, width - mark - after, name), label, words=NAME, size=name_size,
             floor=min(12, name_size), colour=readable(ctx, fills[k]), bold=True, heading=True, anchor='middle')
        block(ctx, (x, start + head, width, FOOT - start - head), column(k, size))
        x += width + gap
    middle = LEFT + widths[0] + gap / 2
    line(ctx, (middle, start + 0.1), (middle, min(FOOT, start + head + tallest)), 'muted', 0.75)


# ---------------------------------------------------------------- 3. marked rows


@variant('pros_cons', 'marked_rows')
def marked_rows(ctx, section, lines):
    """One list of rows, each point behind a plus or minus badge, pros first; the heading and a key down the left."""
    groups = sides(ctx, section)
    rows = [(item, True) for item in groups[0][0]] + [(item, False) for item in groups[1][0]]
    columns = 2 if len(rows) > 5 else 1
    side = 3.6 if columns == 1 else 3.05
    body = header_side(ctx, section, width=side, lines=5)
    against = _against(ctx)
    # The key: what each badge stands for, at the foot of the heading's column.
    small, beside = 0.38, 0.18
    key_size, key_rows, _ = _names(ctx, [(name, side - small - beside) for _, name in groups], (16, 15, 14, 13, 12))
    key = max(0.44, _tall(key_rows, key_size))
    for k, (points, name) in enumerate(groups):
        y = FOOT - (2 - k) * key - (1 - k) * 0.1
        _badge(ctx, (LEFT, y + (key - small) / 2, small, small), k == 0, against)
        text(ctx, (LEFT + small + beside, y, side - small - beside, key), name, words=NAME, size=key_size,
             floor=min(12, key_size), colour='ink', bold=True, heading=True, anchor='middle')
    per = -(-len(rows) // columns)
    gap = 0.4
    width = (RIGHT - body - gap * (columns - 1)) / columns
    badge, indent = 0.5, 0.7
    inner = width - indent
    pad = 0.13
    sizes = SIZES if columns == 1 else SIZES[2:]

    def tall(size):
        heights = [_need(ctx, inner, [_row(item, size)]) for item, _ in rows]
        return [max(heights[c * per + r] for c in range(columns) if c * per + r < len(rows)) for r in range(per)]

    def fitting(top):
        return _largest(lambda s: sum(max(h, badge) + 2 * pad for h in tall(s)) <= FOOT - top, sizes)
    # The list's top lines up with the heading's rule, unless it needs the inch above.
    top = 1.02 if fitting(1.02) and fitting(1.02) == fitting(0.72) else 0.72
    room = FOOT - top
    size = fitting(top) or sizes[-1]
    heights = [max(h, badge) + 2 * pad for h in tall(size)]
    # Spare room opens the rows a little, evenly; the rest centres the list.
    extra = max(0.0, min(0.4, (room - sum(heights)) / per))
    heights = [h + extra for h in heights]
    y0 = _settle(top, room, sum(heights), lift=0.5)
    for index, (item, pro) in enumerate(rows):
        column, row = divmod(index, per)
        x = body + column * (width + gap)
        y = y0 + sum(heights[:row])
        h = heights[row]
        _badge(ctx, (x, y + (h - badge) / 2, badge, badge), pro, against)
        block(ctx, (x + indent, y + pad, inner, h - 2 * pad), [_row(item, size)], anchor='middle')
        if row:
            line(ctx, (x, y), (x + width, y), 'muted', 0.5)


def _row(item, size):
    return dict(text=point_text(item), words=POINT, size=size, floor=min(12, size), colour='ink', spacing=SPACING)


def _badge(ctx, box, pro, against):
    """A pro's accent disc with a plus; a con's disc in `against` with a minus, or a ring if it has no fill."""
    if pro:
        fill, ink = _seen(ctx, 'accent')
        _sign(ctx, box, fill, ink, True, share=0.48)
    elif against == 'card':
        ring(ctx, box, 'muted', 2.25)
        _mark(ctx, box[0] + box[2] / 2, box[1] + box[3] / 2, box[2] * 0.44, 'muted', False)
    else:
        _sign(ctx, box, against, inks(against)['ink'], False, share=0.48)


# ---------------------------------------------------------------- 4. balance


@variant('pros_cons', 'balance', accepts=_both)
def balance(ctx, section, lines):
    """Two columns stand on a beam over a fulcrum, its ends weighted with the plus and minus: a scale that tips."""
    eyebrow(ctx, (LEFT, 0.62, WIDTH, 0.3), align='center')
    headline(ctx, section, (LEFT + 0.8, 0.9, WIDTH - 1.6, 1.0), size=30, align='center')
    rule(ctx, (LEFT + WIDTH / 2 - 0.55, 2.02, 1.1, RULE))
    groups = sides(ctx, section)
    fills = ('accent', _against(ctx, strong(ctx, ('deep', 'secondary'))))
    colours = [readable(ctx, fill) for fill in fills]
    top, gap = 2.4, 1.2
    weight, clear, below = 0.5, 0.16, 0.62   # the end discs, the room above them, the fulcrum under the beam
    # The beam dips toward the side with more points, by at most `tilt` inches.
    counts = [len(points) for points, _ in groups]
    tilt = 0.14 * (counts[0] - counts[1]) / max(1, max(counts))
    dips = (tilt, -tilt)          # each end's drop below the beam's middle
    lowest = FOOT - below         # the beam's middle at its lowest

    def column(k, size):
        return _points(groups[k][0], size, 'ink', colours[k])

    def layout(widths):
        size, rows, whole = _names(ctx, [(name, w) for (_, name), w in zip(groups, widths)], (24, 22, 20, 18))
        name = _tall(rows, size)
        head = name + 0.34        # the name, its short bar, then the points
        budget = [lowest + dips[k] - weight / 2 - clear - top - head for k in range(2)]
        points = _largest(lambda s: all(_need(ctx, w, column(k, s)) <= budget[k] for k, w in enumerate(widths)))
        return points if whole else None, (size, name, head)
    widths, size, (name_size, name, head) = _divide(groups, WIDTH, gap, layout)
    needs = [_need(ctx, w, column(k, size)) for k, w in enumerate(widths)]
    # The scale's height from the names to the fulcrum's foot; short content lifts it whole, centred.
    beam = max(head + needs[k] + clear + weight / 2 - dips[k] for k in range(2))
    start = _settle(top, FOOT - top, beam + below, lift=0.45)
    beam = min(lowest, start + beam)
    x = LEFT
    for k, ((points, label), width) in enumerate(zip(groups, widths)):
        text(ctx, (x, start, width, name), label, words=NAME, size=name_size, floor=min(12, name_size),
             colour=colours[k], bold=True, heading=True, anchor='bottom')
        rect(ctx, (x, start + name + 0.1, 0.7, 0.06), colours[k])
        block(ctx, (x, start + head, width, beam + dips[k] - weight / 2 - clear - start - head), column(k, size))
        x += width + gap
    # The scale itself is neutral, so only its two weights carry the sides' colours.
    cx, thick, reach = LEFT + WIDTH / 2, 0.07, WIDTH / 2 - weight / 2
    polygon(ctx, triangle_points((cx - 0.48, beam + 0.04, 0.96, below - 0.04)), 'muted')
    polygon(ctx, [(cx - reach, beam + tilt - thick / 2), (cx + reach, beam - tilt - thick / 2),
                  (cx + reach, beam - tilt + thick / 2), (cx - reach, beam + tilt + thick / 2)], 'muted')
    oval(ctx, disc(cx, beam, 0.24), 'muted')
    for k in range(2):
        fill, ink = _seen(ctx, fills[k])
        _sign(ctx, disc(cx + (-reach if k == 0 else reach), beam + dips[k], weight), fill, ink, k == 0, share=0.48)


# ---------------------------------------------------------------- 5. header pills


@variant('pros_cons', 'header_pills', accepts=_both)
def header_pills(ctx, section, lines):
    """Each side's name in a big rounded pill of its own colour, heading a card panel that holds its points."""
    top = header_number(ctx, section) - 0.1
    room = FOOT - top
    groups = sides(ctx, section)
    paints = hues(ctx, 2)
    gap, pad, inset, cap = 0.35, 0.32, 0.3, 0.75   # cap: the pill's left end, where its sign sits
    under = 0.28           # from the pill's foot to the first point
    card = inks('card')

    def column(k, size):
        return _points(groups[k][0], size, card['ink'], readable(ctx, paints[k]['fill'], 'card'))

    def layout(widths):
        # The name is centred between the caps: on one line if it can be, else two in a taller pill.
        pairs = [(name, w - 2 * inset - 2 * cap) for (_, name), w in zip(groups, widths)]
        size, rows, whole = _names(ctx, pairs, (24, 22, 20, 18), lines=1)
        if rows > 1 or not whole:
            size, rows, whole = _names(ctx, pairs, (20, 18, 16, 14))
        pill = max(0.7, _tall(rows, size) + 0.16)
        budget = room - pill - under - pad
        points = _largest(lambda s: all(_need(ctx, w - 2 * pad, column(k, s)) <= budget for k, w in enumerate(widths)))
        return points if whole else None, (size, pill)
    widths, size, (name_size, pill) = _divide(groups, WIDTH, gap, layout)
    tallest = max(_need(ctx, w - 2 * pad, column(k, size)) for k, w in enumerate(widths))
    used = min(room, max(2.3, pill + under + tallest + pad))
    y = _settle(top, room, used, lift=0.4)
    x = LEFT
    for k, ((points, name), width) in enumerate(zip(groups, widths)):
        paint = paints[k]
        rounded(ctx, (x, y + pill / 2, width, used - pill / 2), 'card', radius=0.16)
        rounded(ctx, (x + inset, y, width - 2 * inset, pill), paint['fill'], radius=pill / 2)
        _mark(ctx, x + inset + 0.43, y + pill / 2, 0.26, paint['ink'], k == 0)
        text(ctx, (x + inset + cap, y + 0.08, width - 2 * inset - 2 * cap, pill - 0.16), name, words=NAME,
             size=name_size, floor=min(12, name_size), colour=paint['ink'], bold=True, heading=True, align='center',
             anchor='middle')
        block(ctx, (x + pad, y + pill + under, width - 2 * pad, used - pill - under - pad), column(k, size))
        x += width + gap
