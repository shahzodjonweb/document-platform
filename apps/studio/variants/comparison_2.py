"""Comparison variants: each option named once, in its own colour or on its own shape; the criteria in rows below."""
from . import variant
from .kit import (FOOT, LEFT, RIGHT, RULE, WIDTH, arrow_points, badge, columns_of, disc, entries, eyebrow, figure,
                  header_compact, headline, height, hex_of, hues, inks, polygon, readable, rect, rule, strong, text,
                  triangle_points, vs)

LABEL, CELL, NAME = 6, 14, 5   # the classic drawer's word limits: a criterion, a cell, an option's name
SLACK = 4 / 72                 # what a fitted box needs beyond its lines (3 pt, and a little)
LIFT = 0.4                     # short content sits this share of the spare room down: a little above the middle
# Room round a row's text, roomiest first: the first at which the rows hold, at a size no smaller than its floor.
PADS = ((0.12, 14), (0.08, 13), (0.04, 12))


# ---------------------------------------------------------------- content and measuring


def _names(section):
    """The two options' names (blank where the slide gives none)."""
    return (columns_of(section)[:2] + ['', ''])[:2]


def _words(value, limit):
    """`value` held to `limit` words, as kit.clip holds it (without marking the slide)."""
    parts = str(value or '').split()
    return ' '.join(parts) if len(parts) <= limit else ' '.join(parts[:limit]).rstrip(',;:.') + '…'


def _label_tall(ctx, item, width, size):
    return height(ctx, _words(item.get('label'), LABEL), width, size, bold=True, heading=True) + SLACK


def _cell_tall(ctx, value, width, size):
    return height(ctx, _words(value, CELL), width, size) + SLACK


def _name_tall(ctx, name, width, size):
    return height(ctx, _words(name, NAME), width, size, bold=True, heading=True) + SLACK


def _cells_tall(ctx, item, width, size):
    return max(_cell_tall(ctx, item.get('text'), width, size), _cell_tall(ctx, item.get('value'), width, size))


def _fit(holds, cell=(15, 12), label=(17, 14), lead=2):
    """(label, cell, pad): the roomiest pad of PADS, then the largest sizes, at which `holds(label, cell, pad)`.

    The cells step down half a point at a time and the criterion follows them,
    `lead` points above, so every row of one slide shares its sizes.
    """
    for pad, floor in PADS:
        size = cell[0]
        while size >= max(floor, cell[1]):
            top = max(label[1], min(label[0], int(size + lead)))
            if holds(top, size, pad):
                return top, size, pad
            size -= 0.5
    return label[1], cell[1], PADS[-1][0]


def _settle(top, room, tall, lift=LIFT):
    """Where content `tall` inches high starts in `room` below `top`."""
    return top + max(0.0, (room - tall) * lift)


def _label(ctx, box, item, size, colour, **options):
    return text(ctx, box, item.get('label'), size=size, floor=12, colour=colour, bold=True, heading=True,
                words=LABEL, **{'anchor': 'middle', **options})


def _cell(ctx, box, value, size, colour, **options):
    return text(ctx, box, value, size=size, floor=12, colour=colour, words=CELL, **{'anchor': 'middle', **options})


def _name(ctx, box, name, size, colour, **options):
    return text(ctx, box, name, size=size, floor=min(13, size), colour=colour, bold=True, heading=True, words=NAME,
                **{'anchor': 'middle', **options})


def _name_size(ctx, names, width, room, sizes=(20, 13)):
    """The largest size at which both names fit `width` and `room` inches high."""
    size = sizes[0]
    while size > sizes[1] and max(_name_tall(ctx, name, width, size) for name in names) > room:
        size -= 1
    return size


def _apart(one, other, distance=30):
    """Whether two hex colours are visibly different colours (not one colour, or nearly)."""
    rgb = lambda value: [int(value[k:k + 2], 16) for k in (0, 2, 4)]
    return sum((a - b) ** 2 for a, b in zip(rgb(one), rgb(other))) ** 0.5 >= distance


def _hairline(ctx, x, y, width, ground='surface'):
    """A thin rule centred on `y`, in the gap between two rows."""
    rect(ctx, (x, y - 0.0075, width, 0.015), readable(ctx, 'accent_soft', ground, 1.4))


# ---------------------------------------------------------------- variants


@variant('comparison', 'hue_headers')
def hue_headers(ctx, section, lines):
    """Each option's name on a solid block of its own colour over its column; the criteria in zebra rows of card
    and surface."""
    top = header_compact(ctx, section)
    names, rows, colours = _names(section), entries('comparison', section), hues(ctx, 2)
    n = max(1, len(rows))
    side, gap, pad = 3.05, 0.14, 0.22
    width = (WIDTH - side - gap) / 2
    xs = (LEFT + side, LEFT + side + width + gap)
    head, under, close = 0.62, 0.1, 0.16          # the name blocks, the gap under them, the closing strips
    label_w, cell_w = side - pad - 0.15, width - 2 * pad
    room = FOOT - top - head - under - close

    def tallest(label, size, vpad):
        return max(max(_label_tall(ctx, item, label_w, label), _cells_tall(ctx, item, cell_w, size))
                   for item in rows) + 2 * vpad
    label, size, vpad = _fit(lambda label, size, vpad: n * tallest(label, size, vpad) <= room)
    row = min(room / n, max(tallest(label, size, vpad), 0.9))
    y = _settle(top + 0.02, FOOT - top - 0.02, head + under + n * row + close, lift=0.3)
    name = _name_size(ctx, names, width - 2 * pad, head - 0.1)
    for x, value, colour in zip(xs, names, colours):
        rect(ctx, (x, y, width, head), colour['fill'])
        _name(ctx, (x + pad, y + 0.05, width - 2 * pad, head - 0.1), value, name, colour['ink'], align='center')
    for k, item in enumerate(rows):
        ry = y + head + under + k * row
        ground = 'card' if k % 2 == 0 else 'surface'
        colour = inks(ground)
        if ground == 'card':
            rect(ctx, (LEFT, ry, WIDTH, row), 'card')
        inner = (ry + 0.04, row - 0.08)
        _label(ctx, (LEFT + pad, inner[0], label_w, inner[1]), item, label, colour['accent'])
        for x, key in zip(xs, ('text', 'value')):
            _cell(ctx, (x + pad, inner[0], cell_w, inner[1]), item.get(key), size, colour['ink'])
    end = y + head + under + n * row
    for x, colour in zip(xs, colours):
        rect(ctx, (x, end + close - 0.06, width, 0.06), colour['fill'])


def _heading_tall(ctx, section, width, size, lines, room):
    """How tall kit.headline sets the heading in a box `width` x `room` (it steps down from `size` as it does)."""
    value = _words(section.get('heading'), 14)

    def tall(points):
        return height(ctx, value, width, points, heading=True, spacing=1.08)
    while size > 18 and (tall(size) > lines * size * 1.08 / 72 + 1e-6 or tall(size) > room):
        size -= 2
    return min(room, tall(size))


def _side_heading(ctx, section, y, width, size=30):
    """header_side's title column (eyebrow, rule, heading), its top at `y` rather than at the frame's top."""
    eyebrow(ctx, (LEFT, y, width, 0.3))
    rule(ctx, (LEFT, y + 0.4, 0.9, RULE))
    headline(ctx, section, (LEFT, y + 0.63, width, min(3.4, FOOT - y - 0.63)), size=size, lines=5, anchor='top')


@variant('comparison', 'side_title')
def side_title(ctx, section, lines):
    """The heading in a column down the left; on the right a grid of the criteria on tinted tiles, each option
    named over a rule of its colour."""
    column = 2.75
    x0 = LEFT + column + 0.5         # where header_side starts the body
    names, rows, colours = _names(section), entries('comparison', section), hues(ctx, 2)
    n = max(1, len(rows))
    tile, gap, inset, between = 2.6, 0.24, 0.14, 0.07
    width = (RIGHT - x0 - tile - 2 * gap) / 2
    xs = (x0 + tile + gap, x0 + tile + 2 * gap + width)
    label_w = tile - 2 * inset
    name = _name_size(ctx, names, width, 0.62, sizes=(18, 13))
    head = max(_name_tall(ctx, value, width, name) for value in names)
    head_block = head + 0.07 + 0.05 + 0.14       # the names, their rules and the gap under them
    room_all = FOOT - 0.62
    room = room_all - head_block

    def tallest(label, size, vpad):
        return max(max(_label_tall(ctx, item, label_w, label), _cells_tall(ctx, item, width, size))
                   for item in rows) + 2 * vpad + between
    label, size, vpad = _fit(lambda label, size, vpad: n * tallest(label, size, vpad) <= room, label=(16, 14))
    row = min(room / n, max(tallest(label, size, vpad), 0.95))
    # The title column and the grid start level (one-line names put their rules level with the heading's rule),
    # and short content takes both down together, so a brief slide is not left in the top half of the frame.
    title = 0.63 + _heading_tall(ctx, section, column, 30, 5, 3.4)
    y = _settle(0.62, room_all, max(head_block + n * row, title))
    _side_heading(ctx, section, y, column)
    for x, value, colour in zip(xs, names, colours):
        _name(ctx, (x, y, width, head), value, name, colour['text'], anchor='bottom')
        rect(ctx, (x, y + head + 0.07, width, 0.05), colour['fill'])
    tiles = inks('accent_soft')
    start = y + head_block
    for k, item in enumerate(rows):
        ry, box = start + k * row, row - between
        rect(ctx, (x0, ry, tile, box), 'accent_soft')
        _label(ctx, (x0 + inset, ry + 0.04, label_w, box - 0.08), item, label, tiles['ink'])
        for x, key in zip(xs, ('text', 'value')):
            _cell(ctx, (x, ry + 0.04, width, box - 0.08), item.get(key), size, 'ink')
        if k:
            _hairline(ctx, xs[0], ry - between / 2, RIGHT - xs[0])


@variant('comparison', 'stacked_pairs', counts=(2, 4))
def stacked_pairs(ctx, section, lines):
    """The heading with a colour key beside it; each criterion a block, its name over two small cards, one per
    option, each edged in its option's colour."""
    names, rows, colours = _names(section), entries('comparison', section), hues(ctx, 2)
    n = max(1, len(rows))
    key_w = 3.5
    eyebrow(ctx)
    headline(ctx, section, (LEFT, 0.92, WIDTH - key_w - 0.7, 1.0), size=28, lines=2)
    rule(ctx, (LEFT, 1.98, 0.9, RULE))
    # The key: a swatch and each option's name, stacked at the right of the heading, its foot level with the
    # heading's rule. A name of five words takes two lines, and the key grows upward to hold it.
    chip, key_x, key_gap, key_foot = 0.22, RIGHT - key_w, 0.06, 2.0
    key_text = key_w - chip - 0.16

    def key_rows(size):
        return [max(0.4, _name_tall(ctx, value, key_text, size)) for value in names]
    key_name = 15
    while key_name > 12 and sum(key_rows(key_name)) + key_gap > key_foot - 0.92:
        key_name -= 1
    tall = key_rows(key_name)
    ky = key_foot - sum(tall) - key_gap
    rect(ctx, (key_x - 0.3, ky - 0.02, 0.02, sum(tall) + key_gap + 0.04), 'accent_soft')
    for value, colour, row_h in zip(names, colours, tall):
        rect(ctx, (key_x, ky + (row_h - chip) / 2, chip, chip), colour['fill'])
        _name(ctx, (key_x + chip + 0.16, ky, key_text, row_h), value, key_name, 'ink')
        ky += row_h + key_gap
    top = 2.3
    per_row, lines_of = 2, -(-n // 2)
    column_gap, row_gap, card_gap, strip, pad = 0.4, 0.3, 0.12, 0.07, 0.15
    block_w = (WIDTH - column_gap) / 2
    card_w = (block_w - card_gap) / 2
    inner = card_w - 2 * pad
    number = 0.6
    room = FOOT - top

    def parts(label, size, vpad):
        head = max(_label_tall(ctx, item, block_w - number, label) for item in rows)
        card = max(_cells_tall(ctx, item, inner, size) for item in rows) + 2 * vpad + strip
        return head, card

    def holds(label, size, vpad):
        return lines_of * (sum(parts(label, size, vpad)) + 0.08) + (lines_of - 1) * row_gap <= room
    label, size, vpad = _fit(holds, label=(17, 15))
    head, card = parts(label, size, vpad)
    card = max(card, min(0.9, (room - (lines_of - 1) * row_gap) / lines_of - head - 0.08))
    tall = lines_of * (head + 0.08 + card) + (lines_of - 1) * row_gap
    y = _settle(top, room, tall, lift=0.3)
    for k, item in enumerate(rows):
        line_no, column = divmod(k, per_row)
        in_row = min(per_row, n - line_no * per_row)
        x = LEFT + (WIDTH - in_row * block_w - (in_row - 1) * column_gap) / 2 + column * (block_w + column_gap)
        by = y + line_no * (head + 0.08 + card + row_gap)
        figure(ctx, (x, by, number - 0.05, head), f'{k + 1:02d}', size=label, colour='accent_text', anchor='middle',
               bold=True)
        _label(ctx, (x + number, by, block_w - number, head), item, label, 'ink')
        cy = by + head + 0.08
        for c, (key, colour) in enumerate(zip(('text', 'value'), colours)):
            cx = x + c * (card_w + card_gap)
            rect(ctx, (cx, cy, card_w, strip), colour['fill'])
            rect(ctx, (cx, cy + strip, card_w, card - strip), 'card')
            _cell(ctx, (cx + pad, cy + strip + vpad - 0.04, inner, card - strip - 2 * vpad + 0.08), item.get(key),
                  size, 'card_ink', anchor='top')


@variant('comparison', 'scoreboard')
def scoreboard(ctx, section, lines):
    """A strong band reading 'A vs B' in large type, each half underlined in its option's colour; under it the
    criteria down the middle on tinted pills, each option's answer on its own side."""
    names, rows, colours = _names(section), entries('comparison', section), hues(ctx, 2)
    n = max(1, len(rows))
    eyebrow(ctx, (LEFT, 0.62, WIDTH, 0.3), align='center')
    headline(ctx, section, (LEFT + 0.8, 0.88, WIDTH - 1.6, 0.86), size=28, lines=2, align='center')
    top = 2.0
    pill, gap = 3.0, 0.32
    width = (WIDTH - pill - 2 * gap) / 2
    middle = LEFT + WIDTH / 2
    band_h = 1.0 if n <= 4 else 0.76
    strip, under, between = 0.06, 0.12, 0.05
    room = FOOT - top - band_h - 0.05 - strip - under
    pill_w = pill - 0.36

    def tallest(label, size, vpad):
        return max(max(_label_tall(ctx, item, pill_w, label), _cells_tall(ctx, item, width, size))
                   for item in rows) + 2 * vpad + between
    label, size, vpad = _fit(lambda label, size, vpad: n * tallest(label, size, vpad) <= room, label=(16, 14))
    row = min(room / n, max(tallest(label, size, vpad), 0.9))
    y = _settle(top, FOOT - top, band_h + 0.05 + strip + under + n * row, lift=0.35)
    band = inks(strong(ctx))
    rect(ctx, (LEFT, y, WIDTH, band_h), band['fill'])
    name_w = width
    size_name = _name_size(ctx, names, name_w - 0.3, band_h - 0.2, sizes=(30, 16))
    _name(ctx, (LEFT + 0.3, y + 0.1, name_w - 0.3, band_h - 0.2), names[0], size_name, band['ink'], align='right')
    _name(ctx, (RIGHT - name_w, y + 0.1, name_w - 0.3, band_h - 0.2), names[1], size_name, band['ink'])
    mark = min(0.72, band_h - 0.22)
    badge(ctx, disc(middle, y + band_h / 2, mark), vs(ctx), fill=band['ink'], ink=band['ink'], shape='ring',
          size=16, heading=True)
    # Each side's colour, under its half of the band. On a dark deck the strong band is the accent or the second
    # colour itself; a strip of that colour would tie the whole band to one side, so there the band stands alone.
    if all(_apart(hex_of(ctx, band['fill']), hex_of(ctx, colour['fill'])) for colour in colours):
        for x, colour in ((LEFT, colours[0]), (RIGHT - width, colours[1])):
            rect(ctx, (x, y + band_h + 0.05, width, strip), colour['fill'])
    soft = inks('accent_soft')
    start = y + band_h + 0.05 + strip + under
    for k, item in enumerate(rows):
        ry, box = start + k * row, row - between
        rect(ctx, (middle - pill / 2, ry, pill, box), 'accent_soft')
        inset = max(0.03, vpad - 0.02)
        _label(ctx, (middle - pill_w / 2, ry + inset, pill_w, box - 2 * inset), item, label, soft['ink'],
               align='center')
        _cell(ctx, (LEFT, ry + 0.02, width, box - 0.04), item.get('text'), size, 'ink', align='right')
        _cell(ctx, (RIGHT - width, ry + 0.02, width, box - 0.04), item.get('value'), size, 'ink')
        if k:
            for x in (LEFT, RIGHT - width):
                _hairline(ctx, x, ry - between / 2, width)


def _number_header(ctx, section):
    """The slide's number large at the left, a bar, and the heading beside it: a compact header_number."""
    figure(ctx, (LEFT, 0.7, 1.45, 1.25), f'{ctx.index + 1:02d}', size=60, colour='accent_text', anchor='middle')
    rect(ctx, (LEFT + 1.58, 0.85, 0.04, 0.95), 'accent_soft')
    text(ctx, (LEFT + 1.85, 0.62, 3.0, 0.3), f'/ {ctx.total:02d}', size=10, colour='muted', bold=True)
    headline(ctx, section, (LEFT + 1.85, 0.92, WIDTH - 1.85, 0.9), size=28, lines=2, anchor='middle')
    return 2.15


@variant('comparison', 'facing_arrows')
def facing_arrows(ctx, section, lines):
    """The two options named on block arrows that point at each other across the top; the criteria in rows
    under them, each option's lane edged in its colour."""
    top = _number_header(ctx, section)
    names, rows, colours = _names(section), entries('comparison', section), hues(ctx, 2)
    n = max(1, len(rows))
    side, gap, lane = 2.95, 0.34, 0.2
    width = (WIDTH - side - gap) / 2
    xs = (LEFT + side, LEFT + side + width + gap)
    arrow_h, shaft, point, meet = 0.8, 0.7, 0.44, 0.1
    under = 0.2
    label_w, cell_w = side - 0.3, width - lane
    room = FOOT - top - arrow_h - under

    def tallest(label, size, vpad):
        return max(max(_label_tall(ctx, item, label_w, label), _cells_tall(ctx, item, cell_w, size))
                   for item in rows) + 2 * vpad
    label, size, vpad = _fit(lambda label, size, vpad: n * tallest(label, size, vpad) <= room, label=(16, 14))
    row = min(room / n, max(tallest(label, size, vpad), 0.9))
    y = _settle(top, FOOT - top, arrow_h + under + n * row, lift=0.3)
    middle = xs[0] + width + gap / 2
    shaft_h = arrow_h * shaft
    room_name = shaft_h - 0.08
    length = middle - meet / 2 - xs[0]
    name_w = length - point - 0.4
    name = _name_size(ctx, names, name_w, room_name, sizes=(19, 13))
    a, b = colours
    polygon(ctx, arrow_points((xs[0], y, length, arrow_h), head=point, shaft=shaft), a['fill'])
    polygon(ctx, arrow_points((RIGHT - length, y, length, arrow_h), head=point, shaft=shaft, direction='left'),
            b['fill'])
    sy = y + (arrow_h - shaft_h) / 2 + 0.04
    _name(ctx, (xs[0] + 0.2, sy, name_w, room_name), names[0], name, a['ink'], align='center')
    _name(ctx, (RIGHT - 0.2 - name_w, sy, name_w, room_name), names[1], name, b['ink'], align='center')
    start = y + arrow_h + under
    for x, colour in zip(xs, colours):
        rect(ctx, (x, start, 0.05, n * row), colour['fill'])
    for k, item in enumerate(rows):
        ry = start + k * row
        polygon(ctx, triangle_points((LEFT, ry + row / 2 - 0.09, 0.14, 0.18), 'right'), 'accent_text')
        _label(ctx, (LEFT + 0.3, ry + 0.04, label_w, row - 0.08), item, label, 'ink')
        for x, key in zip(xs, ('text', 'value')):
            _cell(ctx, (x + lane, ry + 0.04, cell_w, row - 0.08), item.get(key), size, 'ink')
        if k:
            _hairline(ctx, LEFT, ry, WIDTH)
