"""Image split variants: the picture given a place of its own — a bleed, a banner, an inset, a strip, a base."""
from .. import slides as base
from . import variant
from .kit import (FOOT, LEFT, RIGHT, RULE, SQUEEZE, WIDTH, badge, bullets, eyebrow, headline, height, hues, inks,
                  line, readable, rect, rule, strong, text)

TOP_EDGE = 0.62
LEAD = base.LINE_MULTIPLE   # a list's leading, as kit.bullets sets it
GAP = 0.55                  # kit.bullets' space between items, in lines of the list's size
SLACK = 0.05                # what a fitted box needs beyond its lines (3 pt, and a little)
HEAD_WORDS = 14             # kit.headline's word limit
COUNTS = (1, 6)             # lines a variant is tried with: any the slide can have but none
LIFT = 0.42                 # short content under a banner sits this share of the spare room down


# ---------------------------------------------------------------- measuring


def _clean(lines):
    return [' '.join(str(value).split()) for value in lines if str(value).strip()]


def _tall(ctx, value, width, size, glyph=False):
    """Inches one line takes at `size` in a box `width` wide, measured as kit.bullets measures it."""
    hang = size * 0.95 / 72 if glyph else 0
    return height(ctx, value, width - hang, size, spacing=LEAD)


def _stack(ctx, lines, width, size, glyph=True):
    """Inches a whole kit.bullets list takes in one box, with its small allowance."""
    if not lines:
        return 0
    return (sum(_tall(ctx, value, width, size, glyph) for value in lines)
            + (len(lines) - 1) * size * GAP / 72 + 3 / 72)


def _size(ctx, need, room):
    """The list's size: the deck's own, or down to SQUEEZE below it, until need(size) fits `room`.

    Still too tall at that, the slide is marked squeezed — this variant does not hold it and is passed over.
    """
    size, floor = ctx.size, max(base.FLOOR_BODY_SIZE, ctx.size - SQUEEZE)
    while size > floor and need(size) > room:
        size -= 0.5
    if need(size) > room:
        ctx.squeezed = True
    return size


def _largest(ctx, need, room):
    """The size `_size` would choose, without marking the slide: 0 when the list would be squeezed."""
    size, floor = ctx.size, max(base.FLOOR_BODY_SIZE, ctx.size - SQUEEZE)
    while size >= floor:
        if need(size) <= room:
            return size
        size -= 0.5
    return 0


def _heading(ctx, section, width, size, lines, least=18):
    """(size, lines, inches): how kit.headline sets the heading in a box `width` wide, keeping to `lines` lines.

    It steps down by 2 pt to 18 pt, as slides._headline does; a heading still longer at 18 pt takes
    more lines rather than being cut, and the box is made as tall as that. With `least` above 18, a
    heading still longer than `lines` at `least` points is given one line more before it goes smaller.
    """
    value = ' '.join(str(section.get('heading') or '').split()[:HEAD_WORDS])

    def rows(points):
        # kit.height at a leading of 1 is the line count kit.headline wraps to, times the size.
        return round(height(ctx, value, width, points, heading=True, spacing=1.0) * 72 / points)
    while size > least and rows(size) > lines:
        size -= 2
    if rows(size) > lines and least > 18:
        lines += 1
        while size > 18 and rows(size) > lines:
            size -= 2
    return size, max(lines, rows(size)), rows(size) * size * 1.08 / 72 + 0.04


def _headings(ctx, section, width, size, lines, room, need):
    """The heading `_heading` sets, given a line more when it is long if the list beneath keeps its size.

    `room(inches)` is the room the list has under a heading that tall; `need(size)` the list's height.
    """
    options = [_heading(ctx, section, width, size, lines, least=24), _heading(ctx, section, width, size, lines)]
    sizes = [_largest(ctx, need, room(option[2])) for option in options]
    return next(option for option, fitted in zip(options, sizes) if fitted >= max(sizes))


def _say(ctx, box, value, size, colour='ink'):
    """One line of the list in its own box, at the slide's common size (never shrunk alone)."""
    text(ctx, box, value, size=size, floor=size, colour=colour, spacing=LEAD)


# ---------------------------------------------------------------- 1. photo left


LEFT_PHOTO = (0.18, 0.0, 6.0, 6.55)


@variant('image_split', 'photo_left', counts=COUNTS, photo=LEFT_PHOTO)
def photo_left(ctx, section, lines):
    """The picture bleeding off the left edge with a strong numbered block on its edge; heading and list beside."""
    lines = _clean(lines)
    edge = LEFT_PHOTO[0] + LEFT_PHOTO[2]
    block = 1.0
    x = edge + block / 2 + 0.32
    width = RIGHT - x
    bottom = LEFT_PHOTO[3]

    def need(points):
        return _stack(ctx, lines, width, points)
    size_h, lines_h, tall_h = _headings(ctx, section, width, 32, 3, lambda tall: bottom - TOP_EDGE - tall - 0.36,
                                        need)
    above = tall_h + 0.36
    room = bottom - TOP_EDGE - above
    size = _size(ctx, need, room)
    tall = min(room, _stack(ctx, lines, width, size))
    top = TOP_EDGE + max(0.0, (bottom - TOP_EDGE - above - tall) / 2)
    panel = inks(strong(ctx))
    badge(ctx, (edge - block / 2, top, block, block), f'{ctx.index + 1:02d}', fill=panel['fill'], ink=panel['ink'],
          shape='rect', size=30, heading=True)
    headline(ctx, section, (x, top, width, tall_h), size=size_h, lines=lines_h, anchor='top')
    bullets(ctx, (x, top + above, width, tall), lines, size=size)


# ---------------------------------------------------------------- 2. photo top


TOP_PHOTO = (LEFT, TOP_EDGE, WIDTH, 2.28)


@variant('image_split', 'photo_top', counts=COUNTS, photo=TOP_PHOTO)
def photo_top(ctx, section, lines):
    """A wide banner picture across the top with a tag on its edge; the heading beneath, the lines in ringed columns."""
    lines = _clean(lines)
    n = len(lines)
    base_y = TOP_PHOTO[1] + TOP_PHOTO[3]
    panel = inks(strong(ctx))
    tag = (LEFT, base_y - 0.42, 1.45, 0.42)
    rect(ctx, tag, panel['fill'])
    eyebrow(ctx, (tag[0] + 0.1, tag[1] + 0.08, tag[2] - 0.2, 0.28), colour=panel['muted'], align='center')
    size_h, lines_h, tall_h = _heading(ctx, section, WIDTH, 28, 2)
    start = base_y + 0.28
    after = 0.34
    room = FOOT - start - tall_h - after
    per_row = n if n <= 3 else 2
    rows = -(-n // per_row)
    gutter, row_gap = 0.45, 0.26
    width = (WIDTH - gutter * (per_row - 1)) / per_row
    dot = 0.44
    inset = dot + 0.2
    words = width - inset

    def heights(points):
        return [_tall(ctx, value, words, points) + SLACK for value in lines]

    def need(points):
        tall = heights(points)
        return sum(max(tall[k:k + per_row]) for k in range(0, n, per_row)) + row_gap * (rows - 1)
    size = _size(ctx, need, room)
    tall = heights(size)
    row_heights = [max(tall[k:k + per_row]) for k in range(0, n, per_row)]
    # Heading and columns together sit a little above the middle of the space under the picture. The
    # heading keeps to the foot of its box, so a line measured but not needed opens above it, not
    # between it and the columns.
    head_y = start + max(0.0, room - need(size)) * LIFT
    headline(ctx, section, (LEFT, head_y, WIDTH, tall_h), size=size_h, lines=lines_h, anchor='bottom')
    y = head_y + tall_h + after
    first = size * LEAD / 72
    for row in range(rows):
        for column in range(per_row):
            k = row * per_row + column
            if k >= n:
                break
            x = LEFT + column * (width + gutter)
            # The ring level with the first line of its text.
            badge(ctx, (x, y + first / 2 - dot / 2 + 0.02, dot, dot), f'{k + 1}', fill='accent_text',
                  ink='accent_text', shape='ring', size=15, heading=True)
            _say(ctx, (x + inset, y, words, tall[k]), lines[k], size)
        y += row_heights[row] + row_gap


# ---------------------------------------------------------------- 3. inset frame


INSET_PHOTO = (7.25, 0.95, RIGHT - 7.25, 5.35)


@variant('image_split', 'inset_frame', counts=COUNTS, photo=INSET_PHOTO)
def inset_frame(ctx, section, lines):
    """The picture inset at the right with a thin accent frame offset behind it, a hairline from the heading's
    rule running to the frame; the heading and list at the left."""
    lines = _clean(lines)
    px, py, pw, ph = INSET_PHOTO
    shift = 0.24
    fx, fy = px - shift, py + shift
    # Only the frame's edges that show beside the picture: it reads as lying behind it.
    for start, end in (((fx, fy), (fx, fy + ph)), ((fx, fy + ph), (fx + pw, fy + ph)), ((fx, fy), (px, fy)),
                       ((fx + pw, py + ph), (fx + pw, fy + ph))):
        line(ctx, start, end, 'accent_text', 1.25)
    rect(ctx, (fx - 0.08, fy + ph - 0.08, 0.16, 0.16), 'accent_text')
    width = fx - 0.45 - LEFT
    lead = 0.36

    def need(points):
        return _stack(ctx, lines, width, points)
    size_h, lines_h, tall_h = _headings(ctx, section, width, 30, 3,
                                        lambda tall: fy + ph - py - (lead + tall + 0.2 + RULE + 0.32), need)
    above = lead + tall_h + 0.2 + RULE + 0.32
    room = fy + ph - py - above
    size = _size(ctx, need, room)
    tall = min(room, _stack(ctx, lines, width, size))
    top = py + max(0.0, (room - tall) / 2)
    eyebrow(ctx, (LEFT, top, 3.2, 0.3))
    headline(ctx, section, (LEFT, top + lead, width, tall_h), size=size_h, lines=lines_h, anchor='bottom')
    mark = top + lead + tall_h + 0.2
    rule(ctx, (LEFT, mark, 0.9, RULE))
    line(ctx, (LEFT + 0.9, mark + RULE / 2), (fx, mark + RULE / 2), 'accent_text', 0.75)
    bullets(ctx, (LEFT, top + above, width, tall), lines, size=size)


# ---------------------------------------------------------------- 4. narrow strip


STRIP_PHOTO = (10.0, 0.0, 13.333 - 10.0, 6.55)


@variant('image_split', 'narrow_strip', counts=COUNTS, photo=STRIP_PHOTO)
def narrow_strip(ctx, section, lines):
    """A narrow picture strip down the right edge; the wide text area holds the lines as tabbed, numbered rows."""
    lines = _clean(lines)
    n = len(lines)
    width = STRIP_PHOTO[0] - 0.5 - LEFT
    tab, pad = 0.78, 0.12
    words = width - tab - 0.3 - 0.25
    gap = 0.14 if n > 3 else 0.2

    def need(points):
        return sum(_tall(ctx, value, words, points) + SLACK + 2 * pad for value in lines) + gap * (n - 1)
    size_h, lines_h, tall_h = _headings(ctx, section, width, 30, 2,
                                        lambda tall: FOOT - 0.05 - TOP_EDGE - (0.36 + tall + 0.2 + RULE + 0.3), need)
    above = 0.36 + tall_h + 0.2 + RULE + 0.3
    room = FOOT - 0.05 - TOP_EDGE - above
    size = _size(ctx, need, room)
    heights = [max(0.74, _tall(ctx, value, words, size) + SLACK + 2 * pad) for value in lines]
    # Rows of one height, so the tabs fall at an even beat: closer together if that is what it takes.
    even = next((option for option in (gap, 0.1) if max(heights) * n + option * (n - 1) <= room), None)
    if even is not None:
        heights, gap = [max(heights)] * n, even
    else:
        # Too tall for that: the room left over goes to the shortest rows, evening them out.
        spare = room - sum(heights) - gap * (n - 1)
        level = min(heights)
        while spare > 1e-3 and level < max(heights):
            low = [k for k, value in enumerate(heights) if value <= level + 1e-6]
            nxt = min([value for value in heights if value > level + 1e-6], default=max(heights))
            step = min(nxt - level, spare / len(low))
            for k in low:
                heights[k] = level + step
            spare -= step * len(low)
            level += step
    tall = sum(heights) + gap * (n - 1)
    top = TOP_EDGE + max(0.0, (room - tall) / 2)
    eyebrow(ctx, (LEFT, top, 3.2, 0.3))
    headline(ctx, section, (LEFT, top + 0.36, width, tall_h), size=size_h, lines=lines_h, anchor='bottom')
    rule(ctx, (LEFT, top + 0.36 + tall_h + 0.2, 0.9, RULE))
    y = top + above
    for k, (value, tall, colour) in enumerate(zip(lines, heights, hues(ctx, n))):
        rect(ctx, (LEFT, y, width, tall), 'card')
        rect(ctx, (LEFT, y, tab, tall), colour['fill'])
        text(ctx, (LEFT + 0.06, y + (tall - 0.5) / 2, tab - 0.12, 0.5), f'{k + 1:02d}', size=20, colour=colour['ink'],
             bold=True, heading=True, align='center', anchor='middle')
        text(ctx, (LEFT + tab + 0.3, y + pad, words, tall - 2 * pad), value, size=size, floor=size,
             colour='card_ink', spacing=LEAD, anchor='middle')
        y += tall + gap


# ---------------------------------------------------------------- 5. photo bottom


BOTTOM_PHOTO = (0.18, 4.15, 13.333 - 0.18, 6.55 - 4.15)


@variant('image_split', 'photo_bottom', counts=COUNTS, photo=BOTTOM_PHOTO)
def photo_bottom(ctx, section, lines):
    """A wide picture across the foot of the slide; the heading on a strong panel that drops over the picture's
    edge, the lines in two ruled columns beside it."""
    lines = _clean(lines)
    photo_y = BOTTOM_PHOTO[1]
    bottom = photo_y - 0.3
    panel = inks(strong(ctx))
    side, pad = 3.75, 0.3
    rect(ctx, (LEFT, TOP_EDGE, side, photo_y + 0.5 - TOP_EDGE), panel['fill'])
    inner = side - 2 * pad
    size_h, lines_h, tall_h = _heading(ctx, section, inner, 30, 5)
    eyebrow(ctx, (LEFT + pad, TOP_EDGE + 0.3, inner, 0.3), colour=panel['muted'])
    rule(ctx, (LEFT + pad, TOP_EDGE + 0.7, 0.9, RULE), colour=panel['ink'])
    headline(ctx, section, (LEFT + pad, TOP_EDGE + 0.9, inner, tall_h), size=size_h, lines=lines_h, anchor='top',
             colour=panel['ink'])
    x = LEFT + side + 0.5
    gutter = 0.6
    # A single line runs across both columns rather than leaving the right one bare.
    width = (RIGHT - x - gutter) / 2 if len(lines) > 1 else RIGHT - x
    room = bottom - TOP_EDGE

    def split(points):
        # Newspaper flow: the left column fills first, as evenly as the lines allow; on a tie the left
        # column takes the extra line (three lines run two and one, not one and two).
        best = None
        for cut in range(len(lines) - 1, 0, -1):
            tall = max(_stack(ctx, lines[:cut], width, points), _stack(ctx, lines[cut:], width, points))
            if best is None or tall < best[0] - 1e-6:
                best = (tall, cut)
        return best if best else (_stack(ctx, lines, width, points), len(lines))
    size = _size(ctx, lambda points: split(points)[0], room)
    tall, cut = split(size)
    tall = min(tall, room)
    y = TOP_EDGE + (room - tall) / 2
    bullets(ctx, (x, y, width, tall), lines[:cut], glyph='–', size=size)
    if lines[cut:]:
        middle = x + width + gutter / 2
        line(ctx, (middle, y), (middle, y + tall), readable(ctx, 'accent_soft', 'surface', 1.6), 1.0)
        bullets(ctx, (x + width + gutter, y, width, tall), lines[cut:], glyph='–', size=size)
