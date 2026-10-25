"""Bullets variants: each line a row of its own, led by a mark beside it — a numeral, a bar, a disc or a dot."""
from . import variant
from .kit import (FOOT, LEFT, RIGHT, SQUEEZE, WIDTH, badge, bullets, eyebrow, figure, header, header_band,
                  header_center, header_compact, headline, height, list_size, oval, polygon, rect, rounded, strong,
                  text)

SPACING = 1.22   # a list's leading, as kit.bullets sets it
FLOOR = 13       # the smallest a list goes (slides.FLOOR_BODY_SIZE)
SLACK = 0.05     # what a fitted box needs beyond its lines (3 pt, and a little)


# ---------------------------------------------------------------- measuring


def _tall(ctx, value, width, size):
    """Inches one line of the list takes at `size` in a box `width` wide."""
    return height(ctx, value, width, size, spacing=SPACING)


def _size(ctx, holds):
    """The largest list size, from the deck's own down by SQUEEZE, at which `holds(size)`.

    Rows set one by one shrink together, as kit.bullets would shrink one list:
    if none holds, the slide is marked squeezed (the variant is passed over)
    and the smallest is used.
    """
    low = max(FLOOR, ctx.size - SQUEEZE)
    size = ctx.size
    while size >= low:
        if holds(size):
            return size
        size -= 0.5
    ctx.squeezed = True
    return low


def _natural(ctx, value, size, limit):
    """The narrowest width, up to `limit`, that sets `value` on one line at `size`."""
    one = size * SPACING / 72 + 1e-6
    if _tall(ctx, value, limit, size) > one:
        return limit
    low, high = 0.4, limit
    while high - low > 0.04:
        middle = (low + high) / 2
        low, high = (middle, high) if _tall(ctx, value, middle, size) > one else (low, middle)
    return high


def _stack(ctx, lines, width, room, *, gap, least):
    """Size and gap for lines placed one under another in `room`: (size, heights, gap).

    The gap opens from `least` up to `gap` as the room allows.
    """
    n = len(lines)

    def heights(size):
        return [_tall(ctx, value, width, size) + SLACK for value in lines]
    size = _size(ctx, lambda size: sum(heights(size)) + least * (n - 1) <= room)
    rows = heights(size)
    spare = room - sum(rows)
    return size, rows, max(least, min(gap, spare / max(1, n - 1)))


def _tick(box):
    """A check mark filling the disc drawn at `box`, as a polygon (no glyph)."""
    x, y, w, h = box
    unit = [(0.24, 0.54), (0.43, 0.73), (0.78, 0.38), (0.70, 0.30), (0.43, 0.57), (0.32, 0.46)]
    return [(x + w * px, y + h * py) for px, py in unit]


# ---------------------------------------------------------------- variants


@variant('bullets', 'numbered_rows')
def numbered_rows(ctx, section, lines):
    """Full-width rows that share the height, each led by a large accent numeral and split by hairlines."""
    top = header_compact(ctx, section) + 0.06
    n = len(lines)
    gap = 0.22 if n <= 4 else 0.16
    room = FOOT - top
    row = min(1.25, (room - gap * (n - 1)) / n)
    numeral = min(48, int(row * 72 * 0.74))
    # Two figures in the heading face are about 1.2 em wide; the sentence starts a fixed step after them.
    gutter = 1.2 * numeral / 72 + 0.45
    x, width = LEFT + gutter, RIGHT - LEFT - gutter
    size = _size(ctx, lambda size: all(_tall(ctx, value, width, size) + SLACK <= row for value in lines))
    start = top + (room - (row * n + gap * (n - 1))) / 2
    for k, value in enumerate(lines):
        y = start + k * (row + gap)
        if k:
            rect(ctx, (LEFT, y - gap / 2 - 0.007, WIDTH, 0.014), 'accent_soft')
        figure(ctx, (LEFT, y, gutter - 0.2, row), f'{k + 1:02d}', size=numeral, colour='accent_text',
               anchor='middle')
        text(ctx, (x, y, width, row), value, size=size, floor=size, spacing=SPACING, anchor='middle')


@variant('bullets', 'card_stack', counts=(3, 5))
def card_stack(ctx, section, lines):
    """Each line on a full-width card of its own with a short accent bar at its left edge, stacked evenly."""
    top = header_compact(ctx, section) + 0.02
    n = len(lines)
    # Small gaps between the cards, so the room goes inside them: a card's words keep
    # at least `pad` of air above and below (six sentence-long lines cannot, so 3-5).
    gap = {3: 0.2, 4: 0.14}.get(n, 0.09)
    inset, right = 0.62, 0.42
    width = WIDTH - inset - right
    room = FOOT - top
    share = (room - gap * (n - 1)) / n
    pad = 0.1
    size = _size(ctx, lambda size: max(_tall(ctx, value, width, size) for value in lines) + SLACK + 2 * pad <= share)
    need = max(_tall(ctx, value, width, size) for value in lines) + SLACK
    card = min(share, max(need + 0.34, 0.92))
    start = top + (room - (card * n + gap * (n - 1))) / 2
    bar = min(0.46, card - 0.3)
    for k, value in enumerate(lines):
        y = start + k * (card + gap)
        rounded(ctx, (LEFT, y, WIDTH, card), 'card', radius=0.1)
        rect(ctx, (LEFT + 0.26, y + (card - bar) / 2, 0.07, bar), 'card_accent')
        text(ctx, (LEFT + inset, y + pad, width, card - 2 * pad), value, size=size, floor=size, colour='card_ink',
             spacing=SPACING, anchor='middle')


def _flag_header(ctx, section):
    """Eyebrow and heading beside a tall accent bar, compactly. Returns where the body starts."""
    rect(ctx, (LEFT, 0.66, 0.09, 1.3), 'accent')
    eyebrow(ctx, (LEFT + 0.34, 0.62, 3.2, 0.3))
    headline(ctx, section, (LEFT + 0.34, 0.94, WIDTH - 0.34, 1.02), size=28, lines=2, anchor='middle')
    return 2.24


@variant('bullets', 'two_up', counts=(4, 6))
def two_up(ctx, section, lines):
    """The lines on cards two to a row, each numbered on a small disc at its left edge; an odd last card spans."""
    top = _flag_header(ctx, section)
    n = len(lines)
    gap, row_gap = 0.24, 0.16 if n > 4 else 0.22
    half = (WIDTH - gap) / 2
    pad, pad_y, dot = 0.2, 0.14 if n > 4 else 0.2, 0.42
    offset = pad + dot + 0.18
    rows = [list(range(k, min(n, k + 2))) for k in range(0, n, 2)]
    spans = {row[0]: WIDTH for row in rows if len(row) == 1}

    def width(k):
        return spans.get(k, half) - offset - pad

    def tall(k, size):
        return _tall(ctx, lines[k], width(k), size)

    def needs(size):
        return [max(max(tall(k, size) for k in row) + SLACK, dot) + 2 * pad_y for row in rows]
    room = FOOT - top
    room_cards = room - row_gap * (len(rows) - 1)
    size = _size(ctx, lambda size: sum(needs(size)) <= room_cards)
    heights = _level(needs(size), room_cards, 0.3)
    y = top + (room - sum(heights) - row_gap * (len(rows) - 1)) / 2
    for row, card in zip(rows, heights):
        # The sentence is centred in its card by the text frame itself and the disc on the
        # card's middle, so the two stay level however many lines the deck's font wraps to
        # (kit.height measures a little wide: a line it counts as two often sets as one).
        middle = y + card / 2
        for column, k in enumerate(row):
            x = LEFT + column * (half + gap)
            rounded(ctx, (x, y, spans.get(k, half), card), 'card', radius=0.12)
            badge(ctx, (x + pad, middle - dot / 2, dot, dot), str(k + 1), size=15, heading=True)
            text(ctx, (x + offset, y + pad_y, width(k), card - 2 * pad_y), lines[k], size=size, floor=size,
                 colour='card_ink', spacing=SPACING, anchor='middle')
        y += card + row_gap


def _level(needs, room, most):
    """Heights for rows that each need `needs`: the short ones raised to one level until `room` is used.

    The level stops `most` above the tallest need, so brief content is not spread over the whole frame.
    """
    low, high = 0.0, max(needs) + most
    for _ in range(40):
        level = (low + high) / 2
        low, high = (level, high) if sum(max(need, level) for need in needs) <= room else (low, level)
    return [max(need, low) for need in needs]


@variant('bullets', 'check_rows')
def check_rows(ctx, section, lines):
    """A centred column of lines, each ticked off by an accent disc with a drawn check mark."""
    top = header_center(ctx, section) - 0.12
    dot, step = 0.36, 0.26
    widest = 10.2 - dot - step
    room = FOOT - top
    # The gap opens to 0.28 at most, so a brief list is a centred block, not one that runs
    # from just under the rule to the foot.
    size, heights, gap = _stack(ctx, lines, widest, room, gap=0.28, least=0.12)
    width = max(_natural(ctx, value, size, widest) for value in lines)
    column = dot + step + width
    x = LEFT + (WIDTH - column) / 2
    y = top + (room - sum(heights) - gap * (len(lines) - 1)) / 2
    for value, tall in zip(lines, heights):
        # Each line centred in its measured box by the text frame, the tick on that centre:
        # kit.height measures a little wide, and a line it counts as three that sets as two
        # would, set from the top, leave all the spare height as a wide gap under it.
        middle = y + tall / 2
        oval(ctx, (x, middle - dot / 2, dot, dot), 'accent')
        polygon(ctx, _tick((x, middle - dot / 2, dot, dot)), 'on_accent')
        text(ctx, (x + dot + step, y, width + 0.02, tall), value, size=size, floor=size, spacing=SPACING,
             anchor='middle')
        y += tall + gap


@variant('bullets', 'rail_dots')
def rail_dots(ctx, section, lines):
    """A thin accent rail down the left of the list, with a ringed dot level with the start of each line."""
    top = header(ctx, section) - 0.08
    rail, ring = LEFT + 0.18, 0.3
    x = LEFT + 0.7
    width = RIGHT - x
    room = FOOT - top
    size, heights, gap = _stack(ctx, lines, width, room, gap=0.36, least=0.12)
    y = top + (room - sum(heights) - gap * (len(lines) - 1)) / 2
    first = size * SPACING / 72
    centres = []
    for tall in heights:
        centres.append(y + 0.02 + first / 2)
        y += tall + gap
    start, end = max(top + 0.05, centres[0] - 0.3), min(FOOT, centres[-1] + 0.3)
    rect(ctx, (rail - 0.0175, start, 0.035, end - start), 'accent')
    y = top + (room - sum(heights) - gap * (len(lines) - 1)) / 2
    for value, tall, centre in zip(lines, heights, centres):
        oval(ctx, (rail - ring / 2, centre - ring / 2, ring, ring), 'surface', line='accent_text', line_width=2)
        oval(ctx, (rail - 0.07, centre - 0.07, 0.14, 0.14), 'accent_text')
        text(ctx, (x, y, width, tall), value, size=size, floor=size, spacing=SPACING)
        y += tall + gap


def _list_height(ctx, lines, width, size, gap=0.55):
    """Inches kit.bullets takes for `lines` at `size` in a box `width` wide (marker hang included)."""
    hang = size * 0.95 / 72
    return (sum(_tall(ctx, value, width - hang, size) for value in lines)
            + gap * size * (len(lines) - 1) / 72)


@variant('bullets', 'lead_line', counts=(3, 6))
def lead_line(ctx, section, lines):
    """The first line as a lead sentence on a soft band across the frame; the rest as a list beneath it."""
    top = header_compact(ctx, section) + 0.04
    lead, rest = lines[0], lines[1:]
    inner = WIDTH - 0.55 - 0.4
    width = WIDTH - 0.4
    pad, gap = 0.2, 0.28
    # The lead as large as 24 pt in three lines at most; it gives way (to 20) before the list
    # beneath goes below the deck's size, so the list keeps the size of the deck's other lists
    # (to half a point: the largest lead whose list is within that of the best).
    options = []
    for size in range(24, 19, -1):
        tall = height(ctx, lead, inner, size, heading=True, spacing=1.18)
        if tall > 3 * size * 1.18 / 72 + 1e-6 and size > 20:
            continue
        band = tall + SLACK + 2 * pad
        below = FOOT - top - band - gap
        options.append((list_size(ctx, (LEFT + 0.3, 0, width, below), rest) or 0, size, tall, band, below))
    best = max(option[0] for option in options)
    listed, size, tall, band, below = next(option for option in options if option[0] >= best - 0.5)
    listed = listed or max(FLOOR, ctx.size - SQUEEZE)
    used = min(below, _list_height(ctx, rest, width, listed) + 0.08)
    spare = max(0.0, below - used)
    # Band and list as one group, a little above the middle of the room: brief content
    # is not left at the top with the lower half of the slide empty.
    opened = min(spare * 0.15, 0.2)
    y = top + (spare - opened) * 0.42
    rect(ctx, (LEFT, y, WIDTH, band), 'accent_soft')
    rect(ctx, (LEFT, y, 0.1, band), 'accent')
    text(ctx, (LEFT + 0.55, y + pad, inner, band - 2 * pad), lead, size=size, floor=20, colour='soft_ink',
         heading=True, spacing=1.18, anchor='middle')
    y += band + gap + opened
    hang = listed * 0.95 / 72
    bullets(ctx, (LEFT + 0.55 - hang, y, width, min(FOOT - y, max(used, 0.5))), rest)


@variant('bullets', 'band_top')
def band_top(ctx, section, lines):
    """The heading on a strong band across the top; the list below it, inset, with a thin accent rule beside it."""
    top = header_band(ctx, section, fill=strong(ctx))
    # The rule stands under the band's text edge (header_band insets it 0.4 in); the list
    # keeps the band's right inset too.
    edge = LEFT + 0.4
    x = edge + 0.55
    width = RIGHT - 0.4 - x
    room = FOOT - top
    size = list_size(ctx, (x, top, width, room), lines) or max(FLOOR, ctx.size - SQUEEZE)
    used = min(room, _list_height(ctx, lines, width, size) + 0.1)
    y = top + (room - used) * 0.45
    rect(ctx, (edge, y + 0.04, 0.035, used - 0.08), 'accent')
    bullets(ctx, (x, y, width, used), lines)
