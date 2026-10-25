"""Bullets variants: the list given a structure of its own — a frame, rows, marks, halves, columns or stairs."""
from .. import slides as base
from . import variant
from .kit import (FOOT, LEFT, RIGHT, RULE, SQUEEZE, WIDTH, arrow_points, bullets, eyebrow, figure, header_compact,
                  headline, height, inks, line, polygon, rect, rule, strong, text)

TOP_EDGE = 0.62
LEAD = base.LINE_MULTIPLE
GAP = 0.55             # kit.bullets' space between items, in lines of the list's size


def _clean(lines):
    return [' '.join(str(value).split()) for value in lines if str(value).strip()]


def _tall(ctx, value, width, size, glyph=False):
    """Inches one item takes at `size` in a box `width` wide, measured as kit.bullets measures it."""
    hang = size * 0.95 / 72 if glyph else 0
    return height(ctx, value, width - hang, size, spacing=LEAD)


def _stack(ctx, lines, width, size, glyph=True, gap=GAP):
    """Inches a whole list takes in one box (kit.bullets' own spacing), with its small allowance."""
    if not lines:
        return 0
    return (sum(_tall(ctx, value, width, size, glyph) for value in lines)
            + (len(lines) - 1) * size * gap / 72 + 3 / 72)


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


def _side_heading(ctx, section, width, size=30, lines=5):
    """Inches the heading takes in a column `width` wide, set as kit.headline sets it (to `lines` lines)."""
    value = ' '.join(str(section.get('heading') or '').split()[:14])
    if not value:
        return 0
    while size > 18 and height(ctx, value, width, size, heading=True, spacing=1.08) > lines * size * 1.08 / 72 + 1e-6:
        size -= 2
    return height(ctx, value, width, size, heading=True, spacing=1.08)


def _one_line(ctx, value, size, widest):
    """The narrowest width (to 0.05 in, at most `widest`) that sets `value` on as few lines as `widest` does."""
    target = height(ctx, value, widest, size)
    low, high = 0.3, widest
    while high - low > 0.05:
        middle = (low + high) / 2
        if height(ctx, value, middle, size) <= target + 1e-6:
            high = middle
        else:
            low = middle
    return high


# ---------------------------------------------------------------- 1. outline frame


@variant('bullets', 'outline_frame')
def outline_frame(ctx, section, lines):
    """The heading centred above; the list in a thin accent outline with solid squares on two opposite corners."""
    lines = _clean(lines)
    eyebrow(ctx, (LEFT, TOP_EDGE, WIDTH, 0.3), align='center')
    headline(ctx, section, (LEFT + 0.8, 0.9, WIDTH - 1.6, 1.1), size=32, align='center')
    corner = 0.2
    pad_x, pad_y = 0.5, 0.32
    top, bottom = 2.32, FOOT - corner / 2
    widest = WIDTH - corner - 2 * pad_x
    size = _size(ctx, lambda points: _stack(ctx, lines, widest, points), bottom - top - 2 * pad_y)
    # Brief lists draw the frame round them, centred under the heading, rather than leave it empty.
    width = min(widest, max(6.2, max((_one_line(ctx, value, size, widest - size * 0.95 / 72) for value in lines),
                                     default=0) + size * 0.95 / 72 + 0.1))
    tall = _stack(ctx, lines, width, size)
    box_h = min(bottom - top, max(2.3, tall + 2 * pad_y))
    box_w = width + 2 * pad_x
    x = LEFT + (WIDTH - box_w) / 2
    # A short frame hangs a little above the middle of what is left, near its heading.
    y = top + (bottom - top - box_h) * 0.4
    rect(ctx, (x, y, box_w, box_h), None, line='accent', line_width=1.5)
    rect(ctx, (x - corner / 2, y - corner / 2, corner, corner), 'accent')
    rect(ctx, (x + box_w - corner / 2, y + box_h - corner / 2, corner, corner), 'accent')
    bullets(ctx, (x + pad_x, y + (box_h - tall) / 2, width, tall), lines, size=size)


# ---------------------------------------------------------------- 2. corner block


@variant('bullets', 'corner_block')
def corner_block(ctx, section, lines):
    """A solid accent square at the top left carries the slide number; the heading beside it, the list below
    hung from the heading's left edge, its square marks under the block's edge."""
    lines = _clean(lines)
    side, inset = 1.55, 0.4
    rect(ctx, (LEFT, TOP_EDGE, side, side), 'accent')
    figure(ctx, (LEFT + 0.2, TOP_EDGE + 0.14, side - 0.38, 0.95), f'{ctx.index + 1:02d}', size=54,
           colour='on_accent', anchor='middle')
    text(ctx, (LEFT + 0.2, TOP_EDGE + side - 0.44, side - 0.4, 0.28), f'/ {ctx.total:02d}', size=11,
         colour='on_accent', bold=True)
    headline(ctx, section, (LEFT + side + inset, TOP_EDGE + 0.05, WIDTH - side - inset, side - 0.1), size=32,
             anchor='middle')
    rect(ctx, (LEFT + side, TOP_EDGE + side - 1.25 / 72, WIDTH - side, 1.25 / 72), 'accent')
    top, bottom = TOP_EDGE + side + 0.36, FOOT - 0.02
    # The text keeps the heading's left edge: a shorter measure than the frame's, and one line down the page.
    x = LEFT + side + inset
    width = RIGHT - x

    def stack(points):
        return sum(_tall(ctx, value, width, points) + 3 / 72 for value in lines) + (len(lines) - 1) * points * GAP / 72

    size = _size(ctx, stack, bottom - top)
    y = top + max(0, (bottom - top - stack(size)) * 0.35)
    mark = 0.13
    for value in lines:
        tall = _tall(ctx, value, width, size) + 3 / 72
        middle = y + size * LEAD / 72 / 2 + 0.01
        # Marks in the accent made readable: a pale accent's own squares vanish on a light ground.
        rect(ctx, (LEFT + side - mark, middle - mark / 2, mark, mark), 'accent_text')
        bullets(ctx, (x, y, width, tall), [value], glyph=None, size=size)
        y += tall + size * GAP / 72


# ---------------------------------------------------------------- 3. zebra rows


@variant('bullets', 'zebra_rows')
def zebra_rows(ctx, section, lines):
    """Each point a numbered full-width row, every other row on a card band, like a table of one column."""
    lines = _clean(lines)
    # The table's own top rule underlines the heading, so the header draws no short rule of its own.
    eyebrow(ctx)
    headline(ctx, section, (LEFT, 0.92, WIDTH, 0.98), size=28, lines=2)
    top = 2.1
    bottom = FOOT
    number_w, pad = 0.95, 0.08
    width = WIDTH - number_w - 0.3

    def rows(points):
        return max((_tall(ctx, value, width, points) for value in lines), default=0) + 2 * pad + 3 / 72

    room = bottom - top - RULE - 1 / 72
    size = _size(ctx, lambda points: rows(points) * len(lines), room)
    row = min(max(rows(size), 0.9), room / max(1, len(lines)))
    rect(ctx, (LEFT, top, WIDTH, RULE), 'accent')
    for index, value in enumerate(lines):
        y = top + RULE + index * row
        fill = 'card' if index % 2 == 0 else 'surface'
        colours = inks(fill)
        if fill == 'card':
            rect(ctx, (LEFT, y, WIDTH, row), 'card')
        # A label, one size on every slide whatever the list's size.
        text(ctx, (LEFT + 0.25, y + 0.06, number_w - 0.3, row - 0.12), f'{index + 1:02d}', size=20,
             colour=colours['accent'], bold=True, heading=True, anchor='middle')
        # Centred in its band by the viewer, however the viewer's font wraps it.
        text(ctx, (LEFT + number_w, y + pad / 2, width, row - pad), value, size=size, floor=size,
             colour=colours['ink'], spacing=LEAD, anchor='middle')
    rect(ctx, (LEFT, top + RULE + len(lines) * row, WIDTH, 1 / 72), 'accent')


# ---------------------------------------------------------------- 4. arrow marks


@variant('bullets', 'arrow_marks')
def arrow_marks(ctx, section, lines):
    """The heading in a column at the left; each point beside a small accent block arrow in a gutter."""
    lines = _clean(lines)
    column = 3.6
    start = LEFT + column + 0.5
    gutter = 0.7
    x, width = start + gutter, RIGHT - start - gutter
    top, bottom = TOP_EDGE + 0.3, FOOT - 0.1
    level = 1.25          # where header_side sets the heading

    def stack(points):
        return sum(_tall(ctx, value, width, points) + 3 / 72 for value in lines) + (len(lines) - 1) * points * 0.8 / 72

    size = _size(ctx, stack, bottom - top)
    used = stack(size)
    # The heading and the list start on one line, which drops toward the middle when both are short, rather
    # than leave the lower half of both columns empty. A list that needs the height starts above the heading.
    block = max(used, _side_heading(ctx, section, column))
    head = level + max(0, (bottom - level - block) * 0.4)
    y = head if used <= bottom - head else max(top, bottom - used)
    eyebrow(ctx, (LEFT, TOP_EDGE, column, 0.3))
    rule(ctx, (LEFT, head - 0.23, 0.9, RULE))
    headline(ctx, section, (LEFT, head, column, min(3.4, FOOT - head)), size=30, lines=5, anchor='top')
    line(ctx, (start - 0.28, top), (start - 0.28, bottom), 'accent_soft', 1.0)
    for value in lines:
        tall = _tall(ctx, value, width, size) + 3 / 72
        middle = y + size * LEAD / 72 / 2 + 0.01
        polygon(ctx, arrow_points((start, middle - 0.13, 0.42, 0.26), head=0.17, shaft=0.46), 'accent')
        bullets(ctx, (x, y, width, tall), [value], glyph=None, size=size)
        y += tall + size * 0.8 / 72


# ---------------------------------------------------------------- 5. dual tone


@variant('bullets', 'dual_tone', counts=(2, 8))
def dual_tone(ctx, section, lines):
    """Below a compact heading the frame splits: the first half of the list on a strong panel, the rest beside it."""
    lines = _clean(lines)
    top = header_compact(ctx, section) + 0.1
    half = -(-len(lines) // 2)
    parts = (lines[:half], lines[half:])
    panel = inks(strong(ctx))
    column = 5.95
    pad_x, pad_y = 0.34, 0.3
    width = min(column - 2 * pad_x, RIGHT - LEFT - column - 0.45)
    room = FOOT - top - 2 * pad_y
    size = _size(ctx, lambda points: max(_stack(ctx, part, width, points) for part in parts), room)
    tall = max(_stack(ctx, part, width, size) for part in parts)
    deep = min(FOOT - top, max(3.1, tall + 1.1))
    rect(ctx, (LEFT, top, column, deep), panel['fill'])
    y = top + (deep - tall) / 2
    bullets(ctx, (LEFT + pad_x, y, width, tall), parts[0], colour=panel['ink'], marker=panel['ink'], size=size)
    if parts[1]:
        bullets(ctx, (RIGHT - width, y, width, tall), parts[1], size=size)


# ---------------------------------------------------------------- 6. editorial columns


@variant('bullets', 'editorial_columns', counts=(2, 8))
def editorial_columns(ctx, section, lines):
    """A compact heading with the number of points large at the right; the list flowed into two ruled columns."""
    lines = _clean(lines)
    eyebrow(ctx)
    headline(ctx, section, (LEFT, 0.92, WIDTH - 2.4, 0.98), size=28, lines=2)
    # One rule under the whole header: the short accent rule runs on as a hairline under the numeral, which
    # stands on it.
    figure(ctx, (RIGHT - 2.1, TOP_EDGE, 2.1, 1.3), f'{len(lines):02d}', size=72, colour='accent_text',
           align='right', anchor='bottom')
    rule(ctx, (LEFT, 1.98, 0.9, RULE))
    line(ctx, (LEFT + 0.9, 1.98 + RULE / 2), (RIGHT, 1.98 + RULE / 2), 'accent', 0.75)
    gutter = 0.9
    width = (WIDTH - gutter) / 2
    top, bottom = 2.35, FOOT - 0.05

    def split(points):
        # Newspaper flow: the left column fills first, as evenly as the points allow.
        best = None
        for cut in range(1, len(lines)):
            tall = max(_stack(ctx, lines[:cut], width, points, glyph='–'),
                       _stack(ctx, lines[cut:], width, points, glyph='–'))
            if best is None or tall < best[0] - 1e-6:
                best = (tall, cut)
        return best if best else (_stack(ctx, lines, width, points), len(lines))

    size = _size(ctx, lambda points: split(points)[0], bottom - top)
    tall, cut = split(size)
    # Short columns sit a little above the middle of the page below the rule, not stranded under it.
    top += max(0, (bottom - top - tall) * 0.3)
    middle = LEFT + width + gutter / 2
    line(ctx, (middle, top), (middle, top + tall), 'accent_soft', 0.75)
    bullets(ctx, (LEFT, top, width, tall), lines[:cut], glyph='–', size=size)
    if lines[cut:]:
        bullets(ctx, (LEFT + width + gutter, top, width, tall), lines[cut:], glyph='–', size=size)


# ---------------------------------------------------------------- 7. step ladder


@variant('bullets', 'step_ladder', counts=(3, 6))
def step_ladder(ctx, section, lines):
    """The points as a descending staircase: each row a step further right, on a thick accent tread with a riser."""
    lines = _clean(lines)
    top = header_compact(ctx, section) + 0.15
    bottom = FOOT - 0.05
    n = len(lines)
    # Each row's tread is exactly one step long, so the treads and risers draw one unbroken stair.
    tread = min(0.6, 2.1 / max(1, n - 1))
    lead_in, gap, thick = tread + 0.2, 0.7, 0.09
    widths = [WIDTH - index * tread - lead_in for index in range(n)]

    def stack(points):
        return (sum(_tall(ctx, value, width, points) + 3 / 72 for value, width in zip(lines, widths))
                + (n - 1) * points * gap / 72)

    size = _size(ctx, stack, bottom - top)
    y = top + max(0, (bottom - top - stack(size)) * 0.25)
    previous = None
    for index, (value, width) in enumerate(zip(lines, widths)):
        x = LEFT + index * tread
        tall = _tall(ctx, value, width, size) + 3 / 72
        middle = y + size * LEAD / 72 / 2 + 0.01
        if previous is not None:
            # The riser drops from the end of the tread above to the start of this one, left of both texts.
            rect(ctx, (x - 0.75 / 72, previous, 1.5 / 72, middle - previous), 'accent')
        rect(ctx, (x, middle - thick / 2, tread, thick), 'accent')
        bullets(ctx, (x + lead_in, y, width, tall), [value], glyph=None, size=size)
        previous = middle
        y += tall + size * gap / 72
