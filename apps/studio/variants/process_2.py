"""Process variants: steps along lines, paths and blocks: a staircase, a ring, a snake, a pipeline."""
import math

from . import variant
from .kit import (FOOT, LEFT, RIGHT, RULE, WIDTH, around, arrow_points, badge, block, diamond_points, disc, entries,
                  eyebrow, figure, header, header_band, header_center, header_compact, header_number, header_side,
                  headline, height, hues, inscribed, line, oval, polygon, rect, ring, rule, split, strong, text, tones,
                  triangle_points)

CEILING = 0.62                # the frame's top
LADDER = ((17, 14), (16, 13), (15, 12))     # (name, sentence) sizes, largest first
AFTER = 4                     # points between a step's name and its sentence


def _words(value, limit):
    return ' '.join(str(value or '').split()[:limit])


def _label_height(ctx, item, width, size):
    return height(ctx, _words(item.get('label'), 7), width, size, bold=True, heading=True)


def _text_height(ctx, item, width, size):
    return height(ctx, _words(item.get('text'), 22), width, size) if str(item.get('text') or '').strip() else 0


def _need(ctx, item, width, label, body):
    """Inches a step's name and sentence take, one over the other, at these sizes in a box `width` wide."""
    need = _label_height(ctx, item, width, label)
    if str(item.get('text') or '').strip():
        need += AFTER / 72 + _text_height(ctx, item, width, body)
    return need + 0.05        # block() keeps 3 pt in hand


def _sizes(ctx, steps, width, room, ladder=LADDER):
    """The largest sizes at which every step fits `room` inches: (label, body, the tallest step's height)."""
    for label, body in ladder:
        need = max(_need(ctx, item, width, label, body) for item in steps)
        if need <= room:
            break
    return label, body, need


def _step(ctx, box, item, label, body, *, ink='ink', muted='muted', align='left', anchor='top'):
    """A step's name over its sentence in `box`."""
    block(ctx, box, [
        dict(text=item.get('label'), words=7, size=label, floor=12, colour=ink, bold=True, heading=True,
             after=AFTER, align=align),
        dict(text=item.get('text'), words=22, size=body, floor=12, colour=muted, align=align),
    ], anchor=anchor)


def _rows(ctx, steps, width, mark, room, ladder=LADDER):
    """Sizes and row height for a stack of steps beside markers `mark` tall, centred on the name's first line.

    Returns (label, body, lead, row): `lead` is how far below a row's top
    its text starts, `row` the height every row takes.
    """
    for label, body in ladder:
        lead = max(0.0, mark / 2 - label * 1.15 / 144)
        row = max(mark, lead + max(_need(ctx, item, width, label, body) for item in steps))
        if row <= room:
            break
    return label, body, lead, row


def _stack(count, row, top, bottom, least=0.25, most=0.7):
    """Where each of `count` rows starts, evenly spaced and centred between `top` and `bottom`."""
    spare = bottom - top - count * row
    gap = max(least, min(most, spare / (count - 1))) if count > 1 else 0
    start = top + max(0.0, (bottom - top - count * row - gap * (count - 1)) / 2)
    return [start + k * (row + gap) for k in range(count)]


@variant('process', 'staircase', counts=(3, 5))
def staircase(ctx, section, lines):
    """Numbered blocks rising left to right from the lightest tone to the darkest on one baseline, each step
    standing on its block, and the heading in the space the low steps leave."""
    steps = entries('process', section)
    n = len(steps)
    gap, lift, base, low = 0.16, 0.14, FOOT - 0.06, 1.0
    spans = split(LEFT, WIDTH, n, gap)
    width = spans[0][1]
    start = 1.22                  # where the heading starts, under the eyebrow and the rule
    clear = 0.3                   # the heading stops this short of the next column, whose step stands beside it
    heading = _words(section.get('heading'), 14)

    def plan(label, body, points, rows, share=1.0):
        """The staircase at these sizes, with the heading over as many of the first columns as it fits.

        `share` is how far the tallest block rises from the lowest a staircase may be (0) to the
        highest the steps allow (1).
        """
        need = max(_need(ctx, item, width, label, body) for item in steps)
        most, least = min(3.7, base - CEILING - lift - need), low + 0.3 * (n - 1)
        if most < least:
            return None
        tall = least + (most - least) * share
        rises = [low + (tall - low) * k / max(1, n - 1) for k in range(n)]
        tops = [base - rise - lift - need for rise in rises]
        for columns in range(n - 1, 0, -1):
            # Short of the next column: its step stands at the heading's height and must not read on from it.
            wide = spans[columns - 1][0] + width - LEFT - clear
            room = min(tops[:columns]) - 0.2 - start
            taken = height(ctx, heading, wide, points, heading=True, spacing=1.08)
            if taken <= min(room, rows * points * 1.08 / 72 + 0.01):
                return label, body, need, rises, tops, (LEFT, start, wide, room), rows
        return None

    # A heading of up to three lines at 26 pt, else of four at 20 or five at 18, before the steps take the
    # smallest sizes; only then do the blocks rise less, to leave a long heading the room it needs.
    fits = ((26, 3), (20, 4), (18, 5))
    tries = [(sizes, fit, 1.0) for fit in fits for sizes in LADDER]
    tries += [(sizes, fit, share) for share in (0.66, 0.33, 0.0) for fit in fits for sizes in LADDER]
    layout = next(filter(None, (plan(*sizes, *fit, share) for sizes, fit, share in tries)), None)
    if layout is None:            # the longest content: the smallest sizes and steps, the heading over one column
        label, body = LADDER[-1]
        need = max(_need(ctx, item, width, label, body) for item in steps)
        tall = low + 0.3 * (n - 1)
        rises = [low + (tall - low) * k / max(1, n - 1) for k in range(n)]
        tops = [base - rise - lift - need for rise in rises]
        layout = label, body, need, rises, tops, (LEFT, start, width - clear, max(0.6, tops[0] - 0.2 - start)), 5
    label, body, need, rises, tops, title, rows = layout

    eyebrow(ctx)
    rule(ctx, (LEFT, 1.02, 0.9, RULE))
    headline(ctx, section, title, size=30, lines=rows, anchor='top')
    paints = list(reversed(tones(ctx, n)))
    rect(ctx, (LEFT, base, WIDTH, 0.06), paints[-1]['fill'])
    for position, (item, (x, w), rise, paint) in enumerate(zip(steps, spans, rises, paints)):
        rect(ctx, (x, base - rise, w, rise), paint['fill'])
        figure(ctx, (x + 0.2, base - rise + 0.14, w - 0.4, 0.62), f'{position + 1:02d}', size=30,
               colour=paint['ink'], words=1)
        _step(ctx, (x, tops[position], w, need), item, label, body, anchor='bottom')


@variant('process', 'vertical_line', counts=(3, 5))
def vertical_line(ctx, section, lines):
    """The heading in a column at the left; the steps down a line of numbered discs beside it, each step's
    name and sentence to the right of its disc."""
    start = header_side(ctx, section, width=3.3, size=30)
    steps = entries('process', section)
    n = len(steps)
    mark, space = 0.56, 0.24
    centre, left = start + mark / 2, start + mark + 0.3
    width = RIGHT - left
    label, body, need = _sizes(ctx, steps, width, (FOOT - CEILING - space * (n - 1)) / n)
    row = max(mark + 0.1, need)
    places = _stack(n, row, CEILING, FOOT, least=space, most=0.75)
    # Each disc is centred on its step; the line runs from disc to disc in the gaps.
    middles = [y + row / 2 for y in places]
    for position, (item, y) in enumerate(zip(steps, places)):
        badge(ctx, disc(centre, middles[position], mark), str(position + 1), fill='accent', ink='on_accent',
              size=20, heading=True)
        if position < n - 1:
            line(ctx, (centre, middles[position] + mark / 2 + 0.08),
                 (centre, middles[position + 1] - mark / 2 - 0.08), 'accent_text', 1.75)
        _step(ctx, (left, y, width, row), item, label, body, anchor='middle')


@variant('process', 'arrow_band', counts=(3, 5))
def arrow_band(ctx, section, lines):
    """One broad accent arrow across the slide carrying the step numbers on discs cut out of it; the steps
    in ruled columns beneath."""
    top = header_number(ctx, section)
    steps = entries('process', section)
    n = len(steps)
    tall, mark, gap = 0.86, 0.5, 0.34
    spans = split(LEFT + 0.3, WIDTH - 0.3 - 0.75, n, gap)
    label, body, need = _sizes(ctx, steps, spans[0][1], FOOT - top - 0.02 - tall - 0.3)
    # Brief steps: the arrow and its columns sit together in the middle of the space, a little high.
    band = top + 0.02 + max(0.0, (FOOT - top - 0.02 - tall - 0.3 - need) * 0.4)
    polygon(ctx, arrow_points((LEFT, band, WIDTH, tall), head=0.62, shaft=0.72), 'accent')
    middle = band + tall / 2
    below = band + tall + 0.3
    for position, (item, (x, w)) in enumerate(zip(steps, spans)):
        badge(ctx, disc(x + mark / 2, middle, mark), str(position + 1), fill='surface', ink='accent_text', size=18,
              heading=True)
        if position:
            line(ctx, (x - gap / 2, below + 0.04), (x - gap / 2, below + need - 0.04), 'accent_soft', 1.0)
        _step(ctx, (x, below, w, FOOT - below), item, label, body)


def _arrowhead(ctx, cx, cy, radius, degrees, colour):
    """A small arrowhead on a ring at `degrees` (clockwise from 12 o'clock), pointing clockwise."""
    angle = math.radians(degrees)
    px, py = cx + radius * math.sin(angle), cy - radius * math.cos(angle)
    tx, ty = math.cos(angle), math.sin(angle)          # clockwise along the ring
    nx, ny = math.sin(angle), -math.cos(angle)         # outward
    tip = (px + tx * 0.12, py + ty * 0.12)
    back = (px - tx * 0.08, py - ty * 0.08)
    polygon(ctx, [tip, (back[0] + nx * 0.1, back[1] + ny * 0.1), (back[0] - nx * 0.1, back[1] - ny * 0.1)], colour)


@variant('process', 'cycle_left', counts=(3, 5))
def cycle_left(ctx, section, lines):
    """A ring of numbered discs in several colours round the heading on a soft hub at the left; the steps
    listed beside it, each by a disc of its colour."""
    steps = entries('process', section)
    n = len(steps)
    eyebrow(ctx)
    radius, mark = 2.25, 0.62
    cx, cy = LEFT + mark / 2 + radius, CEILING + (FOOT - CEILING) / 2 + 0.1
    ring(ctx, disc(cx, cy, 2 * radius), 'accent_text', width=1.5)
    start = 0 if n % 2 else 180 / n
    for k in range(n):
        _arrowhead(ctx, cx, cy, radius, start + 360 * (k + 0.5) / n, 'accent_text')
    hub = radius - mark / 2 - 0.12
    oval(ctx, disc(cx, cy, 2 * hub), 'accent_soft')
    # The widest box that stays on the hub: its corners on a circle a little inside the hub's edge.
    headline(ctx, section, (cx - hub * 0.78, cy - hub * 0.6, 2 * hub * 0.78, 2 * hub * 0.6), size=26, lines=4,
             anchor='middle', align='center', colour='soft_ink')

    paints = hues(ctx, n)
    for position, (x, y) in enumerate(around(cx, cy, radius, n, start)):
        badge(ctx, disc(x, y, mark), str(position + 1), fill=paints[position]['fill'],
              ink=paints[position]['ink'], size=20, heading=True)

    small = 0.42
    left = cx + radius + mark / 2 + 0.55
    words_at = left + small + 0.24
    width = RIGHT - words_at
    label, body, lead, row = _rows(ctx, steps, width, small, (FOOT - CEILING - 0.18 * (n - 1)) / n)
    for position, (item, y) in enumerate(zip(steps, _stack(n, row, CEILING, FOOT, least=0.18, most=0.5))):
        badge(ctx, (left, y, small, small), str(position + 1), fill=paints[position]['fill'],
              ink=paints[position]['ink'], size=15, heading=True)
        _step(ctx, (words_at, y + lead, width, row - lead), item, label, body)


@variant('process', 'snake', counts=(3, 5))
def snake(ctx, section, lines):
    """Numbered discs strung on one line across the slide, the steps taking turns above and below it on short stems."""
    top = header(ctx, section)
    steps = entries('process', section)
    n = len(steps)
    gap = 0.5                      # between two steps on the same side, so their sentences never read as one
    pitch = (WIDTH + gap) / (n + 1)
    # A step may spread under its neighbours, which sit on the other side, but not into a line too long to read.
    width = min(4.4, 2 * pitch - gap)
    mark, stem = 0.56, 0.3
    label, body, _ = _sizes(ctx, steps, width, (FOOT - top - mark - 2 * stem) / 2)
    up = max(_need(ctx, item, width, label, body) for item in steps[0::2])
    down = max([_need(ctx, item, width, label, body) for item in steps[1::2]] or [0])
    total = up + stem + mark + stem + down
    y = top + max(0.0, (FOOT - top - total) / 2)
    level = y + up + stem + mark / 2
    rect(ctx, (LEFT, level - 0.025, WIDTH, 0.05), 'accent_soft')
    for position, item in enumerate(steps):
        centre = LEFT + pitch - gap / 2 + position * pitch
        box = disc(centre, level, mark)
        if position % 2 == 0:
            badge(ctx, box, str(position + 1), fill='accent', ink='on_accent', size=18, heading=True)
            line(ctx, (centre, level - mark / 2 - 0.04), (centre, y + up + 0.06), 'accent_text', 1.5)
            _step(ctx, (centre - width / 2, y, width, up), item, label, body, align='center', anchor='bottom')
        else:
            oval(ctx, box, 'surface', line='accent_text', line_width=2.25)
            text(ctx, inscribed(box), str(position + 1), size=18, colour='accent_text', bold=True, heading=True,
                 align='center', anchor='middle')
            line(ctx, (centre, level + mark / 2 + 0.04), (centre, level + mark / 2 + stem - 0.06), 'accent_text', 1.5)
            _step(ctx, (centre - width / 2, level + mark / 2 + stem, width, down), item, label, body,
                  align='center')


@variant('process', 'diamond_line', counts=(3, 5))
def diamond_line(ctx, section, lines):
    """Diamonds in the deck's colours, each in a fine outline of its own, on one baseline with the step numbers
    inside; each step centred under its diamond."""
    top = header_center(ctx, section)
    steps = entries('process', section)
    n = len(steps)
    spans = split(LEFT, WIDTH, n, 0.3)
    solid, outline = 0.84, 1.16
    label, body, need = _sizes(ctx, steps, spans[0][1], FOOT - top - outline - 0.26)
    total = outline + 0.22 + need
    middle = top + max(0.0, (FOOT - top - total) / 2) + outline / 2
    below = middle + outline / 2 + 0.22
    centres = [x + w / 2 for x, w in spans]
    reach = outline / 2 + 0.08     # the baseline stops short of each outline
    edges = [LEFT] + [edge for centre in centres for edge in (centre - reach, centre + reach)]
    edges.append(RIGHT)
    for one, other in zip(edges[0::2], edges[1::2]):
        if other - one > 0.1:
            line(ctx, (one, middle), (other, middle), 'accent_text', 1.0)
    # The first diamond is the accent itself; the rest step round the wheel from it (kit.hues).
    paints = hues(ctx, n)
    for position, (item, (x, w), centre, paint) in enumerate(zip(steps, spans, centres, paints)):
        polygon(ctx, diamond_points(disc(centre, middle, outline)), None, line=paint['text'], line_width=1.25)
        badge(ctx, disc(centre, middle, solid), f'{position + 1:02d}', fill=paint['fill'], ink=paint['ink'],
              shape='diamond', size=18, heading=True)
        _step(ctx, (x, below, w, need), item, label, body, align='center')


@variant('process', 'connected_cards', counts=(3, 5))
def connected_cards(ctx, section, lines):
    """Step cards side by side under an accent cap, each with a large number at its top left and its step at
    its foot, small arrowheads between them."""
    top = header_compact(ctx, section)
    steps = entries('process', section)
    n = len(steps)
    gap, pad, number = 0.4, 0.2, 0.76
    spans = split(LEFT, WIDTH, n, gap)
    inner = spans[0][1] - 2 * pad
    full = FOOT - top - 0.1
    label, body, need = _sizes(ctx, steps, inner, full - 2 * pad - number - 0.25)
    tall = min(full, max(3.3, 2 * pad + number + 0.45 + need))
    y = top + 0.1 + (full - tall) / 2
    for position, (item, (x, w)) in enumerate(zip(steps, spans)):
        rect(ctx, (x, y, w, tall), 'card')
        rect(ctx, (x, y, w, 0.08), 'accent')
        figure(ctx, (x + pad, y + pad, inner, number), f'{position + 1:02d}', size=44, colour='card_accent', words=1)
        # Every card's step starts at the same height: as low as the longest one allows.
        _step(ctx, (x + pad, y + tall - pad - need, inner, need), item, label, body, ink='card_ink',
              muted='card_muted')
        if position < n - 1:
            polygon(ctx, triangle_points((x + w + (gap - 0.16) / 2, y + tall / 2 - 0.15, 0.16, 0.3), 'right'),
                    'accent_text')


ROWS = ((17, 14), (16, 14), (16, 13), (15, 13), (15, 12))


@variant('process', 'pipeline_rows', counts=(3, 5))
def pipeline_rows(ctx, section, lines):
    """The heading on a strong band; the steps as full-width rows down the slide, each with a coloured number
    tab and its name and sentence side by side, small arrowheads pointing down between them."""
    top = header_band(ctx, section, fill=strong(ctx), height=1.3, size=28)
    steps = entries('process', section)
    n = len(steps)
    tab, space, pad = 0.8, 0.18, 0.1
    name_at = LEFT + tab + 0.25
    name_width = 2.4
    text_at = name_at + name_width + 0.28
    text_width = RIGHT - 0.22 - text_at
    room = (FOOT - top - space * (n - 1)) / n - 2 * pad
    for label, body in ROWS:
        need = max(max(_label_height(ctx, item, name_width, label), _text_height(ctx, item, text_width, body))
                   for item in steps) + 0.05
        if need <= room:
            break
    # Rows grow to an inch when there is room, so three steps fill the slide as five do.
    row = max(0.62, need + 2 * pad, min(1.0, (FOOT - top - 0.3 * (n - 1)) / n))
    places = _stack(n, row, top, FOOT, least=space, most=0.34)
    paints = hues(ctx, n)
    for position, (item, y) in enumerate(zip(steps, places)):
        paint = paints[position]
        rect(ctx, (LEFT + tab, y, WIDTH - tab, row), 'card')
        rect(ctx, (LEFT, y, tab, row), paint['fill'])
        figure(ctx, (LEFT + 0.08, y + pad, tab - 0.16, row - 2 * pad), f'{position + 1:02d}', size=24,
               colour=paint['ink'], words=1, align='center', anchor='middle')
        text(ctx, (name_at, y + pad, name_width, row - 2 * pad), item.get('label'), words=7, size=label, floor=12,
             colour='card_ink', bold=True, heading=True, anchor='middle')
        text(ctx, (text_at, y + pad, text_width, row - 2 * pad), item.get('text'), words=22, size=body, floor=12,
             colour='card_muted', anchor='middle')
        if position < n - 1:
            following = places[position + 1]
            depth = min(0.14, following - y - row - 0.06)
            polygon(ctx, triangle_points((LEFT + tab / 2 - 0.15, y + row + (following - y - row - depth) / 2, 0.3,
                                          depth), 'down'), paint['fill'])
