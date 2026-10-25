"""Bullets variants: each line given a mark or a place of its own — card, rings, halves, stripes, hexagons, pills."""
from .. import slides as base
from ..slides import FLOOR_BODY_SIZE, LINE_MULTIPLE, WIDTH_SAFETY
from . import variant
from .kit import (ANCHOR, FOOT, LEFT, RIGHT, RULE, SQUEEZE, WIDTH, badge, bullets, eyebrow, figure, header,
                  header_center, header_compact, header_number, header_side, headline, height, hex_of, hues, inks,
                  inscribed, line, list_size, oval, readable, rect, ring, rounded, rule, strong, text, tones)

SLACK = 3 / 72          # what kit.bullets wants spare under a box's text, in inches


# ---------------------------------------------------------------- measuring


def _clean(lines):
    return [' '.join(str(value).split()) for value in lines if str(value).strip()]


def _lead(size):
    """One line's height at `size`, as kit.bullets sets it (inches)."""
    return size * LINE_MULTIPLE / 72


def _row(ctx, value, width, size):
    """Inches one line takes in a box of its own `width` wide at `size`."""
    return height(ctx, value, width, size, spacing=LINE_MULTIPLE) + SLACK


def _heights(ctx, group, size):
    """A group's row heights at `size`, and how far its first mark rises above its first row.

    A `mark` (a badge `mark` tall) hangs level with its row's first line, so a mark taller than a line
    rises into the gap above; a row is never shorter than `least` (a mark centred on the row).
    """
    mark, least, extra = group.get('mark', 0), group.get('least', 0), group.get('extra', 0)
    lead = _lead(size)
    rows = [max(_row(ctx, value, group['width'], size) + extra, least, lead / 2 + mark / 2)
            for value in group['lines']]
    return rows, max(0.0, mark / 2 - lead / 2)


def _size(ctx, groups, *, equal=False):
    """The largest size, from the deck's own down, at which every group of rows fits its room.

    A group is dict(lines, width, room, gap, mark=0, least=0, extra=0); `equal` makes every row of a
    group as tall as its tallest. Like kit.bullets, the slide is marked squeezed when the size has to
    go more than SQUEEZE points below the deck's.
    """
    def fits(size):
        for group in groups:
            if not group['lines']:
                continue
            rows, rise = _heights(ctx, group, size)
            total = max(rows) * len(rows) if equal else sum(rows)
            if rise + total + group['gap'] * (len(rows) - 1) > group['room'] + 1e-6:
                return False
        return True
    size = ctx.size
    while size > FLOOR_BODY_SIZE and not fits(size):
        size -= 0.5
    if size < ctx.size - SQUEEZE:
        ctx.squeezed = True
    return size


def _stack(heights, top, room, gap, most=None, lift=0.5):
    """Tops for rows of `heights` in `room` below `top`, `gap` apart (up to `most` when there is room).

    What room is left goes `lift` above the block and the rest below it (0.5 centres it).
    """
    count = len(heights)
    total = sum(heights)
    if total and total + gap * (count - 1) > room:
        # It does not fit even at the floor: kit.bullets cuts it and marks the slide.
        scale = max(0.1, (room - gap * (count - 1)) / total)
        heights = [value * scale for value in heights]
        total = sum(heights)
    if most and count > 1:
        gap = min(most, max(gap, (room - total) / (count - 1)))
    y = top + max(0.0, (room - total - gap * (count - 1)) * lift)
    tops = []
    for value in heights:
        tops.append(y)
        y += value + gap
    return tops, heights, gap


def _list_height(ctx, lines, width, size, gap=0.55):
    """Inches a kit.bullets list with markers takes at `size` in a box `width` wide."""
    total = sum(height(ctx, value, width - size * 0.95 / 72, size, spacing=LINE_MULTIPLE) for value in lines)
    return total + size * gap * max(0, len(lines) - 1) / 72 + SLACK


def _middle(ctx):
    """Centre the text box just drawn on its box's height, so it sits level with its mark however it wraps."""
    ctx.slide.shapes[-1].text_frame.vertical_anchor = ANCHOR['middle']


def _say(ctx, box, value, size, colour='ink', middle=False):
    """One line in its own box at the slide's common size, without a marker."""
    bullets(ctx, box, [value], colour=colour, glyph=None, size=size)
    if middle:
        _middle(ctx)


def _nudge(size):
    """How far below a line's box centre its letters' centre falls (inches): marks hang level with that."""
    return size * 0.06 / 72


def _number(ctx, box, position, colour, size=16):
    """A row's two-digit number, centred in `box` (a shape's inscribed box)."""
    text(ctx, box, f'{position + 1:02d}', size=size, floor=9, colour=colour, bold=True, heading=True,
         align='center', anchor='middle')


def _natural(ctx, lines, size, widest):
    """The narrowest list width (marker hang included) that wraps `lines` no more than `widest` does."""
    goal = _list_height(ctx, lines, widest, size)
    low, high = min(widest, 1.0), widest
    while high - low > 0.05:
        middle = (low + high) / 2
        if _list_height(ctx, lines, middle, size) <= goal + 1e-6:
            high = middle
        else:
            low = middle
    return high


def _partner(ctx):
    """The fill that alternates with the accent: of the second colour and deep, the one that differs from the
    accent most while still standing off the slide's ground; kit.strong when neither does."""
    def rgb(role):
        value = hex_of(ctx, role)
        return [int(value[index:index + 2], 16) for index in (0, 2, 4)]

    def apart(role):
        return sum((one - other) ** 2 for one, other in zip(rgb(role), rgb('accent'))) ** 0.5

    seen = [role for role in ('secondary', 'deep')
            if ctx.roles.get(role) and base.contrast_ratio(hex_of(ctx, role), hex_of(ctx, 'surface')) >= 1.6
            and apart(role) >= 70]
    if seen:
        return max(seen, key=apart)
    other = strong(ctx)
    return strong(ctx, ('deep', 'secondary')) if other == 'accent' else other


# ---------------------------------------------------------------- variants


@variant('bullets', 'centre_card')
def centre_card(ctx, section, lines):
    """The heading centred; the whole list on one large rounded card centred beneath it, an accent edge on top."""
    # Clear of the centred rule (2.38-2.42) by a third of an inch, as the card's sides are clear of the frame.
    top = header_center(ctx, section) - 0.03
    lines = _clean(lines)
    edge, pad_x, pad_y, least = 0.08, 0.45, 0.26, 5.6
    room = FOOT - top - edge - 2 * pad_y
    widest = WIDTH - 2 * pad_x
    size = list_size(ctx, (0, 0, widest, room), lines) or FLOOR_BODY_SIZE
    if size < ctx.size - SQUEEZE:
        ctx.squeezed = True
    # The card hugs the list: the narrowest box that wraps it no more than the full frame does. Measures run
    # wide of what viewers set (WIDTH_SAFETY), so the box is centred on the text as set, not on the box.
    inner = _natural(ctx, lines, size, widest)
    hang = size * 0.95 / 72
    # A line that wraps can run to the box's edge; only one-line points leave the measure's margin unused.
    single = all(height(ctx, value, inner - hang, size, spacing=1) <= size / 72 + 1e-6 for value in lines)
    shown = hang + (inner - hang) / WIDTH_SAFETY if single else inner
    width = min(WIDTH, max(least, shown + 2 * pad_x, 2 * inner - shown + 2 * 0.15))
    if width >= WIDTH - 0.01:
        inner, shown = widest, widest
    need = min(room, _list_height(ctx, lines, inner, size))
    tall = max(need, 1.3)
    card = tall + 2 * pad_y
    y = top + (FOOT - top - edge - card) / 2
    x = LEFT + (WIDTH - width) / 2
    # The card laid over an accent one of the same size a little higher: an accent edge along its top.
    rounded(ctx, (x, y, width, card), 'accent', radius=0.22)
    rounded(ctx, (x, y + edge, width, card), 'card', radius=0.22)
    bullets(ctx, (x + (width - shown) / 2, y + edge + pad_y, inner, tall), lines, colour='card_ink',
            marker='card_accent', size=size)
    _middle(ctx)


@variant('bullets', 'margin_rings')
def margin_rings(ctx, section, lines):
    """The slide's number large beside the heading; each line numbered in a ring in the left margin, the rings
    strung on a thin spine and the rows evenly spaced."""
    header_number(ctx, section)
    lines = _clean(lines)
    if not lines:
        return
    top = 2.62
    room, gap = FOOT - top, 0.16
    mark = min(0.62, max(0.46, (room - gap * (len(lines) - 1)) / len(lines)))
    x = LEFT + 0.05
    left = x + mark + 0.42
    width = RIGHT - left
    group = dict(lines=lines, width=width, room=room, gap=gap, least=mark)
    size = _size(ctx, [group])
    tall, _ = _heights(ctx, group, size)
    slot = min(1.1, room / len(lines))
    if max(tall) + 0.2 <= slot:
        # Every row in a slot of the same height: the rings fall at an even beat.
        start = top + (room - slot * len(lines)) * 0.4
        centres = [start + k * slot + slot / 2 for k in range(len(lines))]
        spans = [slot - 0.12] * len(lines)
    else:
        tops, tall, _ = _stack(tall, top, room, gap, most=0.4)
        centres = [y + value / 2 for y, value in zip(tops, tall)]
        spans = tall
    for position, (value, centre, span) in enumerate(zip(lines, centres, spans)):
        box = (x, centre - mark / 2, mark, mark)
        ring(ctx, box, 'accent_text', width=2.0)
        _number(ctx, inscribed(box, 0.62), position, 'accent_text', size=16)
        if position:
            above = centres[position - 1] + mark / 2 + 0.06
            if box[1] - 0.06 - above > 0.06:
                line(ctx, (x + mark / 2, above), (x + mark / 2, box[1] - 0.06), 'accent_text', 1.0)
        own = max(span, _row(ctx, value, width, size))
        _say(ctx, (left, centre - own / 2, width, own), value, size, middle=True)


@variant('bullets', 'split_halves', counts=(2, 8))
def split_halves(ctx, section, lines):
    """The list split in two: the first half on a tinted panel, the rest on a card panel, each line numbered on a
    small disc, the rows of each panel an even beat apart."""
    top = header_compact(ctx, section) + 0.06
    lines = _clean(lines)
    half = -(-len(lines) // 2)
    parts = (lines[:half], lines[half:])
    gutter, pad_x, pad_y, mark, gap, most = 0.25, 0.32, 0.27, 0.4, 0.18, 0.42
    beside = mark + 0.2
    room = FOOT - top - 2 * pad_y
    even = (WIDTH - gutter) / 2

    def rise(size):
        # The first disc hangs level with its line's first line, so a disc taller than the line rises above it.
        return max(0.0, mark / 2 - _lead(size) / 2)

    def plan(first, size):
        """Text widths, each panel's row height and the height its rows need, with the left panel `first` wide."""
        widths = (first - 2 * pad_x - beside, WIDTH - gutter - first - 2 * pad_x - beside)
        least = rise(size) + _lead(size) / 2 + mark / 2
        slots = [max([_row(ctx, value, width, size) for value in part] + [least])
                 for part, width in zip(parts, widths)]
        common = max(slots)
        # One grid for both panels when it fits (always with as many lines a side), so the rows run level.
        if len(parts[0]) == len(parts[1]) or rise(size) + half * common + gap * (half - 1) <= room + 1e-6:
            slots = [common, common]
        need = max(rise(size) + len(part) * slot + gap * (len(part) - 1) for part, slot in zip(parts, slots) if part)
        return widths, slots, need

    def largest(first):
        size = ctx.size
        while size > FLOOR_BODY_SIZE and plan(first, size)[2] > room + 1e-6:
            size -= 0.5
        return size

    # Even halves; an odd count's fuller left panel widens, as little as it can, only when even halves would
    # set the list more than SQUEEZE below the deck's size.
    options = [even + step * 0.1 for step in range(1 if len(parts[0]) == len(parts[1]) else 14)]
    sizes = [largest(option) for option in options]
    goal = min(max(sizes), ctx.size - SQUEEZE)
    first, size = next((option, value) for option, value in zip(options, sizes) if value >= goal - 1e-6)
    widths, slots, need = plan(first, size)
    if size < ctx.size - SQUEEZE or need > room + 1e-6:
        # Too small, or too long even at the floor: passed over for this slide; the rows still stay in the frame.
        ctx.squeezed = True
        slots = [min(slot, (room - rise(size) - gap * (half - 1)) / half) for slot in slots]
        need = room
    if half > 1:
        # The rows open out a little when there is room, as one beat for both panels.
        gap = min(most, max(gap, gap + (room - need) / (half - 1)))
        need = max(rise(size) + len(part) * slot + gap * (len(part) - 1) for part, slot in zip(parts, slots) if part)
    # Short lists get panels that hug them (never squat), set a little above the middle of the room.
    tall = min(FOOT - top, max(2.5, need + 2 * pad_y))
    y0 = top + (FOOT - top - tall) * 0.4
    start = y0 + (tall - need) / 2 + rise(size)
    fills = (('accent_soft', 'accent'), ('card', strong(ctx)))
    x = LEFT
    for side, (part, width, slot, (fill, disc_fill)) in enumerate(zip(parts, widths, slots, fills)):
        panel = width + 2 * pad_x + beside
        rounded(ctx, (x, y0, panel, tall), fill, radius=0.16)
        for position, value in enumerate(part):
            y = start + position * (slot + gap)
            badge(ctx, (x + pad_x, y + (_lead(size) - mark) / 2 + _nudge(size), mark, mark),
                  f'{side * half + position + 1}', fill=disc_fill, ink=inks(disc_fill)['ink'], size=15, heading=True)
            _say(ctx, (x + pad_x + beside, y, width, min(slot, _row(ctx, value, width, size))), value, size,
                 inks(fill)['ink'])
        x += panel + gutter


@variant('bullets', 'index_strip')
def index_strip(ctx, section, lines):
    """The heading and list over the left of the frame; a tall tinted strip at the right holds the slide's marker
    and, large, how many points the slide makes, counted out in dots."""
    lines = _clean(lines)
    strip = 2.1
    sx = RIGHT - strip
    width = sx - 0.5 - LEFT
    colours = inks('accent_soft')
    # The accent as it shows on the strip: a pale accent beside a pale tint would all but vanish.
    mark = readable(ctx, 'accent', 'accent_soft', 3.0)
    rect(ctx, (sx, 0.62, strip, FOOT - 0.62), 'accent_soft')
    eyebrow(ctx, (sx + 0.3, 0.9, strip - 0.6, 0.3), colour=colours['muted'])
    rule(ctx, (sx + 0.3, 4.6, 0.7, RULE), colour=mark)
    figure(ctx, (sx + 0.3, 4.72, strip - 0.6, 1.18), f'{len(lines):02d}', size=72, colour=colours['ink'],
           anchor='bottom')
    dot = 0.14
    step = min(0.25, (strip - 0.64 - dot) / max(1, len(lines) - 1))
    for k in range(len(lines)):
        oval(ctx, (sx + 0.32 + k * step, 6.12, dot, dot), mark)
    # A compact top (the strip has the marker), so the list has the height a narrower column needs.
    headline(ctx, section, (LEFT, 0.82, width, 1.08), size=30, lines=2)
    rule(ctx, (LEFT, 2.02, 1.1, RULE))
    top, room = 2.32, FOOT - 2.32
    # The list opens out when it is short, then sits a little above the middle of what is left.
    for gap in (1.0, 0.8, 0.65, 0.55):
        if list_size(ctx, (0, 0, width, room), lines, gap=gap) == ctx.size:
            break
    size = list_size(ctx, (0, 0, width, room), lines, gap=gap) or FLOOR_BODY_SIZE
    tall = min(room, _list_height(ctx, lines, width, size, gap))
    bullets(ctx, (LEFT, top + (room - tall) * 0.35, width, tall), lines, marker='accent_text', glyph='–', gap=gap)
    _middle(ctx)


@variant('bullets', 'tone_stripes')
def tone_stripes(ctx, section, lines):
    """Each line on a stripe across the frame, the stripes stepping from the accent's darkest tone to its palest,
    numbered at the left."""
    top = header_compact(ctx, section) + 0.08
    lines = _clean(lines)
    if not lines:
        return
    gap, least_pad = 0.07, 0.07
    lead_x, number = 0.24, 0.5
    rule_x = LEFT + lead_x + number + 0.12
    left = rule_x + 0.16
    width = RIGHT - 0.24 - left
    room = FOOT - top
    size = _size(ctx, [dict(lines=lines, width=width, room=room, gap=gap, extra=2 * least_pad)], equal=True)
    tallest = max(_row(ctx, value, width, size) for value in lines)
    share = (room - gap * (len(lines) - 1)) / len(lines)
    stripe = min(share, max(tallest + 0.34, 0.86))
    used = stripe * len(lines) + gap * (len(lines) - 1)
    y = top + max(0.0, (room - used) * 0.35)
    for position, (value, tone) in enumerate(zip(lines, tones(ctx, len(lines)))):
        rect(ctx, (LEFT, y, WIDTH, stripe), tone['fill'])
        text(ctx, (LEFT + lead_x, y + (stripe - 0.4) / 2, number, 0.4), f'{position + 1:02d}', size=20, floor=14,
             colour=tone['ink'], bold=True, heading=True, anchor='middle')
        line(ctx, (rule_x, y + 0.14), (rule_x, y + stripe - 0.14), tone['ink'], 0.75)
        inset = min(0.06, max(0.0, (stripe - _row(ctx, value, width, size)) / 2))
        _say(ctx, (left, y + inset, width, stripe - 2 * inset), value, size, tone['ink'], middle=True)
        y += stripe + gap


@variant('bullets', 'hex_markers')
def hex_markers(ctx, section, lines):
    """Each line numbered on a small hexagon in the margin, the hexagons alternating the accent and a second fill
    that differs from it, hairlines between the rows."""
    header(ctx, section)
    lines = _clean(lines)
    if not lines:
        return
    top = 2.7
    gap = 0.16
    room = FOOT - top
    # A flat-topped hexagon as wide as it should be for its height; smaller when many rows share the room, so
    # the marks never decide the list's size.
    mark = min(0.54, max(0.42, (room - gap * (len(lines) - 1)) / len(lines) - 0.02))
    wide = mark * 1.15
    left = LEFT + 0.62 + 0.38
    width = RIGHT - left
    group = dict(lines=lines, width=width, room=room, gap=gap, least=mark + 0.02)
    size = _size(ctx, [group])
    rows, _ = _heights(ctx, group, size)
    tops, rows, gap = _stack(rows, top, room, gap, most=0.45, lift=0.4)
    other = _partner(ctx)
    for position, (value, y, row) in enumerate(zip(lines, tops, rows)):
        fill = 'accent' if position % 2 == 0 else other
        # Mark and text both centred on the row, so they stay level however the line wraps.
        badge(ctx, (LEFT + (0.62 - wide) / 2, y + (row - mark) / 2, wide, mark), f'{position + 1:02d}', fill=fill,
              ink=inks(fill)['ink'], shape='hexagon', size=15, heading=True)
        _say(ctx, (left, y, width, row), value, size, middle=True)
        if position:
            between = y - gap / 2
            line(ctx, (left, between), (RIGHT, between), 'muted', 0.5)


@variant('bullets', 'pill_tags')
def pill_tags(ctx, section, lines):
    """The heading in a column at the left; the list beside it as rows, each led by a rounded tag in its own
    colour holding its number."""
    left = header_side(ctx, section, width=3.0)
    lines = _clean(lines)
    if not lines:
        return
    line(ctx, (left - 0.25, 1.02), (left - 0.25, FOOT - 0.25), 'accent_soft', 1.0)
    pill_w, pill_h, gap = 0.8, 0.4, 0.2
    start = left + 0.05
    body = start + pill_w + 0.28
    width = RIGHT - body
    top, room = 0.95, FOOT - 0.95 - 0.1
    group = dict(lines=lines, width=width, room=room, gap=gap, least=pill_h + 0.06)
    size = _size(ctx, [group])
    rows, _ = _heights(ctx, group, size)
    tops, rows, gap = _stack(rows, top, room, gap, most=0.5, lift=0.4)
    for position, (value, y, row, hue) in enumerate(zip(lines, tops, rows, hues(ctx, len(lines)))):
        pill_y = y + (row - pill_h) / 2
        rounded(ctx, (start, pill_y, pill_w, pill_h), hue['fill'], radius=pill_h / 2)
        _number(ctx, (start + pill_h * 0.3, pill_y + pill_h * 0.16, pill_w - pill_h * 0.6, pill_h * 0.68),
                position, hue['ink'], size=15)
        _say(ctx, (body, y, width, row), value, size, middle=True)
        if position:
            between = y - gap / 2
            line(ctx, (body, between), (RIGHT, between), 'accent_soft', 1.0)
