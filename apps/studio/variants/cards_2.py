"""Cards variants: the cards as shapes of their own — corners round a panel, comb cells, pillars, tickets, orbits."""
from pptx.util import Inches

from . import variant
from ..slide_layouts import _paragraph_height, _text_lines
from ..slides import contrast_ratio
from .kit import (FOOT, LEFT, RIGHT, RULE, WIDTH, Z, around, badge, block, disc, entries, eyebrow, figure, header_band,
                  header_compact, header_side, headline, hex_of, hexagon_points, hues, inks, inscribed, oval, polygon,
                  readable, rect, ring, rule, split, strong, tab_points, text, tones)

TOP_EDGE = 0.62
# (label, text) sizes, largest first: a slide's cards all take the first pair every one of them holds.
LADDER = ((20, 16), (19, 15), (18, 14), (17, 13), (16, 12), (15, 12))
ROWS = ((19, 15), (18, 14), (17, 13), (16, 12), (15, 12))
TAG = 0.27  # the height of a tag's line


# ---------------------------------------------------------------- measuring


def _plain(value, words=None):
    parts = str(value or '').split()
    return ' '.join(parts[:words] if words else parts)


def _bold(ctx, paragraph):
    return bool(paragraph.get('bold')) or bool(paragraph.get('heading') and ctx.heading_bold)


def _need(ctx, width, paragraphs):
    """Inches `paragraphs` (as for kit.block) take in a box `width` wide, measured as block measures them."""
    zone = Z(0, 0, width, 10)
    total = 0.0
    for paragraph in paragraphs:
        if not paragraph:
            continue
        value = _plain(paragraph.get('text'), paragraph.get('words'))
        if not value:
            continue
        if paragraph.get('upper'):
            value = value.upper()
        total += _paragraph_height(dict(text=value, size=paragraph['size'], bold=_bold(ctx, paragraph),
                                        before=paragraph.get('before', 0), after=paragraph.get('after', 0),
                                        spacing=paragraph.get('spacing', 1.15)), zone)
    return (total + 3) / 72 if total else 0.0


def _whole(ctx, width, paragraphs):
    """Whether every word of `paragraphs` fits on a line of `width` (no word broken across lines)."""
    for paragraph in paragraphs:
        if not paragraph:
            continue
        value = _plain(paragraph.get('text'), paragraph.get('words'))
        if paragraph.get('upper'):
            value = value.upper()
        for word in value.split():
            if _text_lines(word, paragraph['size'], Inches(width), bold=_bold(ctx, paragraph)) > 1:
                return False
    return True


def _holds(ctx, width, height, paragraphs):
    return _need(ctx, width, paragraphs) <= height and _whole(ctx, width, paragraphs)


def _settled(ctx, cards, make, width, height, ladder=LADDER):
    """The first sizes in `ladder` at which every card's paragraphs fit its box, or None (`width`, `height`: one
    or a list)."""
    widths = list(width) if isinstance(width, (list, tuple)) else [width] * len(cards)
    heights = list(height) if isinstance(height, (list, tuple)) else [height] * len(cards)
    for sizes in ladder:
        if all(_holds(ctx, widths[k], heights[k], make(k, item, *sizes)) for k, item in enumerate(cards)):
            return sizes
    return None


def _settle(ctx, cards, make, width, height, ladder=LADDER):
    """As `_settled`, falling back to the ladder's smallest sizes (which kit.block then shrinks or cuts)."""
    return _settled(ctx, cards, make, width, height, ladder) or ladder[-1]


def _word_size(ctx, value, width, size, floor=18):
    """The largest size up to `size` at which the heading's longest word keeps to one line of `width`."""
    words = _plain(value, 14).split() or ['']
    while size > floor and any(_text_lines(word, size, Inches(width), bold=ctx.heading_bold) > 1 for word in words):
        size -= 1
    return size


def _heading_fit(ctx, section, width, height, size, lines):
    """The size kit.headline sets the heading at in a box `width` x `height` inches, or None if it would cut it.

    It follows slides._headline: two points smaller at a time down to 18 while
    the heading runs over `lines` lines or the box's height, then cuts.
    """
    value, zone = _plain(section.get('heading'), 14), Inches(width)

    def tall(points):
        return _text_lines(value, points, zone, bold=ctx.heading_bold) * points * 1.08

    while size > 18 and (_text_lines(value, size, zone, bold=ctx.heading_bold) > lines or tall(size) > height * 72):
        size -= 2
    return size if tall(size) <= height * 72 else None


def _tag_width(item, size=11):
    """Inches a card's tag takes on one line in bold capitals at `size` (0 when it has none)."""
    tag = _plain(item.get('value'), 3).upper()
    if not tag:
        return 0.0
    width = 0.3
    while width < 6 and _text_lines(tag, size, Inches(width), bold=True) > 1:
        width += 0.05
    return width + 0.05


# ---------------------------------------------------------------- pieces


def _card(item, label, body, *, ink='ink', muted='muted', accent='accent_text', align='left', tag=True, gap=4):
    """A card's paragraphs: its tag (unless drawn apart), label and text, at the classic word limits."""
    paragraphs = []
    if tag and item.get('value'):
        paragraphs.append(_tag(item, accent, align))
    paragraphs.append(dict(text=item['label'], words=7, size=label, floor=min(label, 15), colour=ink, bold=True,
                           heading=True, after=gap, align=align))
    if item.get('text'):
        paragraphs.append(dict(text=item['text'], words=28, size=body, floor=min(body, 12), colour=muted,
                               align=align))
    return paragraphs


def _tag(item, colour, align='left'):
    return dict(text=item.get('value'), words=3, upper=True, size=11, floor=10, colour=colour, bold=True, after=3,
                align=align)


def _tag_box(ctx, box, item, colour, align='left'):
    """A card's tag on a line of its own (nothing when it has none)."""
    if item.get('value'):
        text(ctx, box, item['value'], words=3, upper=True, size=11, floor=10, colour=colour, bold=True, align=align)


def _mark(ctx, fill, prefer=('accent', 'secondary', 'accent_soft')):
    """A fill role from `prefer` that shows on a panel of `fill`: a mark, a chip, a strip.

    The accent itself is preferred, but a dark accent all but vanishes on the
    deep panel of a light deck, so the first that stands 2.2:1 off the panel
    is taken, else the one that stands off it most.
    """
    ground = hex_of(ctx, fill)
    choices = [role for role in prefer if role != fill] or [inks(fill)['ink']]
    for role in choices:
        if contrast_ratio(hex_of(ctx, role), ground) >= 2.2:
            return role
    return max(choices, key=lambda role: contrast_ratio(hex_of(ctx, role), ground))


def _line(ctx, ground='surface'):
    """The accent for a thin mark (a rule, a ring, an edge) on `ground`: moved until it shows there, 3:1."""
    return readable(ctx, 'accent', ground, 3.0)


def _side(item, width):
    """The room a row's tag takes at the right of its label's line: as wide as the tag, at most 45% (0 without)."""
    return min(width * 0.45, _tag_width(item) + 0.2) if item.get('value') else 0.0


def _row_parts(item, label, body, width):
    """A row's label (narrowed by its tag's room, when it has one), and its text."""
    name = [dict(text=item['label'], words=7, size=label, floor=min(label, 15), colour='ink', bold=True,
                 heading=True, after=2)]
    words = [dict(text=item.get('text'), words=28, size=body, floor=min(body, 12), colour='muted')]
    return name, (words if item.get('text') else []), width - _side(item, width)


def _row_need(ctx, item, label, body, width):
    name, words, room = _row_parts(item, label, body, width)
    return _need(ctx, room, name), _need(ctx, width, words)


def _row_sizes(ctx, cards, width, most, ladder=None):
    """The first (label, text) sizes at which every row, label over text, holds `most` inches."""
    ladder = ladder or ROWS
    for label, body in ladder:
        if all(sum(_row_need(ctx, item, label, body, width)) <= most
               and _whole(ctx, _row_parts(item, label, body, width)[2], _row_parts(item, label, body, width)[0])
               for item in cards):
            return label, body
    return ladder[-1]


def _row(ctx, x, y, width, item, label, body):
    """A row at (x, y): the label with the tag at its right, the text under both. Returns its height."""
    name, words, room = _row_parts(item, label, body, width)
    top, under = _row_need(ctx, item, label, body, width)
    block(ctx, (x, y, room, top), name)
    if room < width:
        _tag_box(ctx, (x + room + 0.2, y + max(0.0, (label - 11) / 72 * 0.55), width - room - 0.2, TAG), item,
                 'accent_text', 'right')
    if under:
        block(ctx, (x, y + top, width, under + 0.02), words)
    return top + under


def _second(ctx):
    """A strong fill that is not the accent, to alternate with it."""
    chosen = strong(ctx)
    return strong(ctx, ('deep', 'secondary')) if chosen == 'accent' else chosen


def _centre_top(ctx, section, size=28):
    """Eyebrow, heading and rule centred, compact. Returns where the body starts (2.25)."""
    eyebrow(ctx, (LEFT, TOP_EDGE, WIDTH, 0.3), align='center')
    headline(ctx, section, (LEFT + 1.0, 0.9, WIDTH - 2.0, 1.0), size=size, lines=2, align='center')
    rule(ctx, (LEFT + WIDTH / 2 - 0.45, 2.02, 0.9, RULE))
    return 2.25


def _number(k):
    return f'{k + 1:02d}'


def _shrunk(box, share):
    x, y, w, h = box
    return (x + w * (1 - share) / 2, y + h * (1 - share) / 2, w * share, h * share)


# ---------------------------------------------------------------- variants


@variant('cards', 'quad_centre', counts=(4, 4))
def quad_centre(ctx, section, lines):
    """Four cards at the corners of a 2x2, mirrored round a square dark panel holding the heading and card numbers."""
    cards = entries('cards', section)[:4]
    gap, pad, pad_x, pad_y = 0.26, 0.36, 0.32, 0.26
    tall = (FOOT - TOP_EDGE - gap) / 2

    def make(k, item, label, body):
        return _card(item, label, body, ink='card_ink', muted='card_muted', accent='card_accent',
                     align='right' if k % 2 == 0 else 'left')

    def plan(side):
        width = (WIDTH - side - 2 * gap) / 2
        room = side - 2 * pad
        size = _word_size(ctx, section['heading'], room, 28)
        return (side, width, room, size, _heading_fit(ctx, section, room, room - 0.84, size, 6),
                _settled(ctx, cards, make, width - 2 * pad_x, tall - 2 * pad_y))
    # The panel grows a little for a long heading, while the cards beside it still hold theirs.
    plans = [plan(side) for side in (3.3, 3.55, 3.8)]
    side, width, room, size, _, sizes = next(
        (chosen for chosen in plans if chosen[4] and chosen[4] >= 20 and chosen[5]),
        next((chosen for chosen in plans if chosen[4] and chosen[5]), plans[0]))
    sizes = sizes or LADDER[-1]
    px, py = LEFT + width + gap, TOP_EDGE + (FOOT - TOP_EDGE - side) / 2
    panel = inks(strong(ctx))
    mark = _mark(ctx, panel['fill'])
    rect(ctx, (px, py, side, side), panel['fill'])
    eyebrow(ctx, (px + side / 2 - 0.75, py + pad, 1.5, 0.3), colour=panel['muted'], align='center')
    rule(ctx, (px + side / 2 - 0.45, py + pad + 0.42, 0.9, RULE), colour=mark)
    headline(ctx, section, (px + pad, py + pad + 0.62, room, room - 0.84), size=size, lines=6, anchor='middle',
             align='center', colour=panel['ink'])
    number_ink = readable(ctx, mark, panel['fill'])
    edge = _line(ctx, 'card')
    for k, item in enumerate(cards):
        row, column = divmod(k, 2)
        x = LEFT if column == 0 else px + side + gap
        y = TOP_EDGE + row * (tall + gap)
        rect(ctx, (x, y, width, tall), 'card')
        # An accent edge on the side that faces the panel, as long as the panel runs beside the card, and the
        # card's number in the panel's corner at the edge's end.
        edge_x = x + width - 0.07 if column == 0 else x
        top, bottom = (py, y + tall) if row == 0 else (y, py + side)
        rect(ctx, (edge_x, top, 0.07, bottom - top), edge)
        corner_x = px + 0.16 if column == 0 else px + side - 0.16 - 0.7
        corner_y = py + 0.12 if row == 0 else py + side - 0.12 - 0.36
        figure(ctx, (corner_x, corner_y, 0.7, 0.36), _number(k), size=18, colour=number_ink, bold=True,
               align='left' if column == 0 else 'right', anchor='middle')
        block(ctx, (x + pad_x, y + pad_y, width - 2 * pad_x, tall - 2 * pad_y), make(k, item, *sizes),
              anchor='bottom' if row == 0 else 'top')


@variant('cards', 'honeycomb', counts=(3, 4))
def honeycomb(ctx, section, lines):
    """A honeycomb strip across the slide whose numbered cells, accent and dark in turn, head the columns of text."""
    top = _centre_top(ctx, section)
    cards = entries('cards', section)
    n = len(cards)
    gap = 0.42
    spans = split(LEFT, WIDTH, n, gap)
    width = spans[0][1]
    pitch = spans[1][0] - spans[0][0]
    # Cells of the comb sit 0.75 of a cell apart; an even number of them between columns keeps every
    # numbered cell on the strip's lower row, over the middle of its column.
    between = min((4, 6, 8), key=lambda count: abs(pitch / (0.75 * count) - 0.95))
    cell = pitch / (0.75 * between)
    tall = cell * 0.866
    band = 1.5 * tall
    tagged = any(item.get('value') for item in cards)

    def make(k, item, label, body):
        return _card(item, label, body, align='center', gap=5, tag=False)
    room = FOOT - top - 0.15 - band - 0.22 - (TAG if tagged else 0)
    sizes = _settle(ctx, cards, make, width, room)
    need = max(_need(ctx, width, make(k, item, *sizes)) for k, item in enumerate(cards))
    start = top + 0.15 + max(0.0, (room - need) / 2)
    first = spans[0][0] + width / 2
    low = -int((first - LEFT - cell / 2) / (0.75 * cell))
    high = int((RIGHT - cell / 2 - first) / (0.75 * cell))
    fills = ('accent', _second(ctx))
    for step in range(low, high + 1):
        cx = first + step * 0.75 * cell
        y = start + (tall / 2 if step % 2 == 0 else 0)
        box = _shrunk((cx - cell / 2, y, cell, tall), 0.92)
        k = step // between if step % between == 0 else None
        if k is not None and 0 <= k < n:
            fill = fills[k % 2]
            badge(ctx, box, _number(k), fill=fill, ink=inks(fill)['ink'], shape='hexagon', size=20, heading=True)
        else:
            polygon(ctx, hexagon_points(box), 'accent_soft')
    below = start + band + 0.22
    for k, (item, (x, w)) in enumerate(zip(cards, spans)):
        _tag_box(ctx, (x, below, w, TAG), item, 'accent_text', 'center')
        block(ctx, (x, below + (TAG if tagged else 0), w, need + 0.02), make(k, item, *sizes))


@variant('cards', 'pillars', counts=(3, 4))
def pillars(ctx, section, lines):
    """Pillars in the accent's tones, darkest first, stepping down from full height; the heading in the notch left."""
    cards = entries('cards', section)
    n = len(cards)
    gap, slim = 0.2, 0.8
    regular = (WIDTH - gap * (n - 1)) / (n - 1 + slim)
    widths = [regular * slim] + [regular] * (n - 1)
    lefts = [LEFT + sum(widths[:k]) + gap * k for k in range(n)]
    fills = tones(ctx, n)
    pad, head = 0.24, 0.7
    # The heading stands in the notch the staircase leaves, over the third pillar on; a long one takes a deeper
    # notch.
    x2 = lefts[2]
    size = _word_size(ctx, section['heading'], RIGHT - x2, 30)
    deep = next((depth for depth in (1.14, 1.42, 1.7) if _heading_fit(ctx, section, RIGHT - x2, depth, size, 2)),
                1.14)
    eyebrow(ctx, (x2, TOP_EDGE, 3.0, 0.3))
    rule(ctx, (x2, 1.02, 0.9, RULE))
    headline(ctx, section, (x2, 1.16, RIGHT - x2, deep), size=size, lines=2, anchor='top')
    full, cap = FOOT - TOP_EDGE, FOOT - (1.16 + deep + 0.2)
    step = (full - cap) / 2
    heights = [full - step * k if k < 2 else cap for k in range(n)]

    def make(k, item, label, body):
        colour = fills[k]['ink']
        return _card(item, label, body, ink=colour, muted=colour, accent=colour)
    inner = [w - 2 * pad for w in widths]

    def settled(tall):
        return _settled(ctx, cards, make, inner, [h - 2 * pad - head for h in tall])
    # Even steps down from the full height. A fourth pillar takes a full step below the third when every card
    # still holds its text at 16 pt labels; else it steps as far as its own card allows (half a step at least)
    # or stands as tall as the third.
    stepped = heights[:3] + [max(cap - step, 2.3)] if n > 3 else heights
    sizes = settled(stepped)
    if sizes and sizes[0] >= 16:
        heights = stepped
    else:
        sizes = settled(heights) or LADDER[-1]
        if n > 3:
            own = _need(ctx, inner[3], make(3, cards[3], *sizes)) + 2 * pad + head
            lower = max(cap - step, own, 2.3)
            heights[3] = lower if cap - lower >= step / 2 else cap
    for k, (item, x, w, tall, paint) in enumerate(zip(cards, lefts, widths, heights, fills)):
        y = FOOT - tall
        rect(ctx, (x, y, w, tall), paint['fill'])
        figure(ctx, (x + pad, y + pad, inner[k], 0.6), _number(k), size=32, colour=paint['ink'])
        block(ctx, (x + pad, y + pad + head, inner[k], tall - 2 * pad - head), make(k, item, *sizes),
              anchor='bottom')


@variant('cards', 'tickets', counts=(3, 4))
def tickets(ctx, section, lines):
    """Tickets stacked beside the heading: a stub with a cut corner, tag and number, a perforation, then the card."""
    side = 3.1
    x0 = header_side(ctx, section, width=side, size=_word_size(ctx, section['heading'], side, 30))
    cards = entries('cards', section)
    n = len(cards)
    tagged = any(item.get('value') for item in cards)
    # The stub widens for a long tag, so the tag keeps to its line under the cut.
    stub = min(2.0, max([1.05] + [_tag_width(item) + 0.22 for item in cards]))
    width, gap, notch = RIGHT - x0, 0.16, 0.1
    area_top, area_bottom = TOP_EDGE + notch, FOOT - notch
    most = (area_bottom - area_top - gap * (n - 1)) / n
    inner = width - stub - 0.32 - 0.28
    pad = 0.12

    def make(k, item, label, body):
        return _card(item, label, body, ink='card_ink', muted='card_muted', accent='card_accent', tag=False, gap=3)
    sizes = _settle(ctx, cards, make, inner, most - 2 * pad)
    need = max(_need(ctx, inner, make(k, item, *sizes)) for k, item in enumerate(cards))
    tall = min(most, max(need + 0.5, 1.3))
    y0 = area_top + (area_bottom - area_top - n * tall - (n - 1) * gap) / 2
    for k, item in enumerate(cards):
        y = y0 + k * (tall + gap)
        polygon(ctx, tab_points((x0, y, width, tall), cut=0.3, corner='top_left'), 'card')
        px = x0 + stub
        dash = 0.07
        steps = int((tall - 0.3) / (2 * dash))
        first = y + (tall - (2 * steps - 1) * dash) / 2
        for step in range(steps):
            rect(ctx, (px - 0.008, first + 2 * step * dash, 0.016, dash), 'card_muted')
        for edge in (y, y + tall):
            oval(ctx, disc(px, edge, 2 * notch), 'surface')
        _tag_box(ctx, (x0 + 0.1, y + 0.3, stub - 0.2, 0.26), item, 'card_accent', 'center')
        # The number sits under the tag's line; with no tags on the slide, in the middle of the stub.
        number_y = y + tall - 0.12 - 0.6 if tagged else y + (tall - 0.6) / 2
        figure(ctx, (x0 + 0.1, number_y, stub - 0.2, 0.6), _number(k), size=30, colour='card_accent',
               align='center', anchor='middle')
        block(ctx, (px + 0.32, y + pad, inner, tall - 2 * pad), make(k, item, *sizes), anchor='middle')


@variant('cards', 'feature_split', counts=(3, 6))
def feature_split(ctx, section, lines):
    """The first card as a large dark feature panel under the heading at left, the rest as numbered rows at right."""
    cards = entries('cards', section)
    lead, rest = cards[0], cards[1:]
    left_w = 4.5
    size = _word_size(ctx, section['heading'], left_w, 28)
    # A long heading pushes the panel down rather than lose its words.
    deep = next((depth for depth, most in ((1.3, 3), (1.62, 4), (1.94, 5))
                 if _heading_fit(ctx, section, left_w, depth, size, most)), 1.3)
    eyebrow(ctx, (LEFT, TOP_EDGE, left_w, 0.3))
    headline(ctx, section, (LEFT, 0.92, left_w, deep), size=size, lines=3 if deep < 1.6 else 5, anchor='top')
    ptop = 0.92 + deep + 0.2
    panel = inks(strong(ctx))
    rect(ctx, (LEFT, ptop, left_w, FOOT - ptop), panel['fill'])
    rect(ctx, (LEFT, ptop, left_w, 0.08), _mark(ctx, panel['fill']))
    pad = 0.38
    # The numeral steps down with the panel, so the card keeps its room.
    numeral = 1.3 - (ptop - 2.42) / 2
    figure(ctx, (LEFT + pad, ptop + 0.3, 2.0, numeral - 0.4), '01', size=54, colour=panel['ink'], anchor='middle')
    feature_box = (LEFT + pad, ptop + numeral, left_w - 2 * pad, FOOT - ptop - numeral - pad)

    def lead_make(k, item, label, body):
        return _card(item, label, body, ink=panel['ink'], muted=panel['muted'], accent=panel['muted'], gap=6)
    lead_sizes = _settle(ctx, [lead], lead_make, feature_box[2], feature_box[3],
                         ((24, 17), (22, 16), (21, 15), (20, 14), (19, 13), (18, 12), (16, 12)))
    block(ctx, feature_box, lead_make(0, lead, *lead_sizes), anchor='bottom')

    rx = LEFT + left_w + 0.5
    dot = 0.5
    bx, bw = rx + dot + 0.28, RIGHT - rx - dot - 0.28
    m = len(rest)
    room = (FOOT - TOP_EDGE) / m
    label, body = _row_sizes(ctx, rest, bw, room - 0.3)
    tallest = max(sum(_row_need(ctx, item, label, body, bw)) for item in rest)
    pitch = min(room, tallest + 0.7)
    # Rows that fit beside the panel are centred on it; more of them take the frame's height.
    top = ptop if m * pitch <= FOOT - ptop else TOP_EDGE
    y0 = top + (FOOT - top - m * pitch) / 2
    for k, item in enumerate(rest):
        y = y0 + k * pitch
        if k:
            rect(ctx, (rx, y - 0.006, RIGHT - rx, 0.012), 'accent_soft')
        # Every row starts the same distance below its rule, so the discs keep an even beat.
        by = y + (pitch - tallest) / 2
        badge(ctx, (rx, by, dot, dot), _number(k + 1), size=14, heading=True)
        _row(ctx, bx, by, bw, item, label, body)


@variant('cards', 'dotted_path', counts=(3, 5))
def dotted_path(ctx, section, lines):
    """A dotted path across the slide, a numbered dot per card: the label stands on the path, the text hangs below."""
    top = header_compact(ctx, section)
    cards = entries('cards', section)
    n = len(cards)
    gap = 0.36 if n <= 4 else 0.28
    spans = split(LEFT, WIDTH, n, gap)
    width = spans[0][1]
    band = 0.72  # the path and its dots, between the labels and the texts
    room = FOOT - top - 0.2 - band

    def above(item, label):
        return _card(item, label, 12, gap=0)[:-1] if item.get('text') else _card(item, label, 12, gap=0)

    def below(item, body):
        return [dict(text=item.get('text'), words=28, size=body, floor=min(body, 12), colour='muted')]
    chosen = LADDER[-1]
    for label, body in LADDER:
        ups = [_need(ctx, width, above(item, label)) for item in cards]
        downs = [_need(ctx, width, below(item, body)) for item in cards]
        if max(ups) + max(downs) <= room and all(_whole(ctx, width, above(item, label)) for item in cards):
            chosen = (label, body)
            break
    label, body = chosen
    up = max(_need(ctx, width, above(item, label)) for item in cards)
    down = max(_need(ctx, width, below(item, body)) for item in cards)
    y0 = top + 0.2 + max(0.0, (room - up - down) / 2)
    path = y0 + up + band / 2
    dot = 0.44
    step, small, clear = 0.17, 0.07, 0.12
    line_colour = _line(ctx)
    # The path runs from each numbered dot to the next (the last to the frame's edge), its small dots spaced
    # evenly in each stretch with the same clearance at both ends.
    ends = [x + dot for x, _ in spans]
    starts = [x for x, _ in spans[1:]] + [RIGHT + clear]
    for start, end in zip(ends, starts):
        first, last = start + clear + small / 2, end - clear - small / 2
        count = max(1, round((last - first) / step) + 1)
        for index in range(count):
            oval(ctx, disc(first + (last - first) * index / max(1, count - 1), path, small), line_colour)
    for k, (item, (x, w)) in enumerate(zip(cards, spans)):
        block(ctx, (x, y0, w, up), above(item, label), anchor='bottom')
        badge(ctx, disc(x + dot / 2, path, dot), _number(k), size=12, heading=True)
        if item.get('text'):
            block(ctx, (x, path + band / 2, w, down), below(item, body))


@variant('cards', 'big_circles', counts=(3, 4))
def big_circles(ctx, section, lines):
    """Large pale discs haloed in the accent holding number and label, a tag pill on the rim, the text below."""
    top = header_compact(ctx, section)
    cards = entries('cards', section)
    n = len(cards)
    spans = split(LEFT, WIDTH, n, 0.4 if n == 3 else 0.32)
    width = spans[0][1]
    halo, under = 0.13, 0.3
    room = FOOT - top - 0.15

    def inside(k, item, label):
        return [dict(text=_number(k), size=14, floor=14, colour='soft_muted', bold=True, align='center', after=2),
                dict(text=item['label'], words=7, size=label, floor=min(label, 15), colour='soft_ink', bold=True,
                     heading=True, align='center')]

    def below(item, body):
        return [dict(text=item.get('text'), words=28, size=body, floor=min(body, 12), colour='muted',
                     align='center')] if item.get('text') else []
    plan = None
    for label, body in LADDER:
        down = max(_need(ctx, width, below(item, body)) for item in cards)
        size = min(width - 2 * halo - 0.04, 2.75, room - down - under - 2 * halo)
        if size < 1.9:
            continue
        inner = inscribed((0, 0, size, size))[2]
        if all(_holds(ctx, inner, inner, inside(k, item, label)) for k, item in enumerate(cards)):
            plan = (label, body, size, down)
            break
    if plan is None:
        label, body = LADDER[-1]
        down = max(_need(ctx, width, below(item, body)) for item in cards)
        plan = (label, body, max(1.9, min(width - 2 * halo - 0.04, room - down - under - 2 * halo)), down)
    label, body, size, down = plan
    y0 = top + 0.15 + max(0.0, (room - size - 2 * halo - under - down) / 2)
    cy = y0 + halo + size / 2
    for k, (item, (x, w)) in enumerate(zip(cards, spans)):
        cx = x + w / 2
        ring(ctx, disc(cx, cy, size + 2 * halo), _line(ctx), width=1.25)
        box = disc(cx, cy, size)
        oval(ctx, box, 'accent_soft')
        block(ctx, inscribed(box), inside(k, item, label), anchor='middle')
        if item.get('value'):
            tag = _plain(item['value'], 3).upper()
            # As wide as the tag needs inside the pill's inscribed box, never narrower than a short word's.
            pill = min(size * 0.8, max(0.78, (_tag_width(item, 10) + 0.06) / 0.84))
            badge(ctx, (cx - pill / 2, cy + size / 2 - 0.15, pill, 0.32), tag, shape='rounded', size=10)
        paragraphs = below(item, body)
        if paragraphs:
            block(ctx, (x, cy + size / 2 + halo + under, w, down), paragraphs)


@variant('cards', 'accent_border_grid', counts=(3, 4))
def accent_border_grid(ctx, section, lines):
    """Cards in two columns under a soft heading band, a thick accent bar down each left edge; three make a bento."""
    top = header_band(ctx, section, fill='accent_soft', height=1.36, size=28) - 0.06
    cards = entries('cards', section)
    n = len(cards)
    gap, bar, pad, pad_y, head = 0.24, 0.13, 0.3, 0.22, 0.5
    column = (WIDTH - gap) / 2
    full = FOOT - top
    half = (full - gap) / 2
    if n == 3:
        boxes = [(LEFT, top, column, full), (LEFT + column + gap, top, column, half),
                 (LEFT + column + gap, top + half + gap, column, half)]
    else:
        boxes = [(LEFT + (k % 2) * (column + gap), top + (k // 2) * (half + gap), column, half) for k in range(n)]
    inner = column - bar - 2 * pad
    # Three make a bento: the first card the full height on the strong fill (the band above is the soft tint),
    # the other two stacked beside it.
    paints = [inks(strong(ctx)) if n == 3 and k == 0 else inks('card') for k in range(n)]

    def make(k, item, label, body):
        paint = paints[k]
        return _card(item, label, body, ink=paint['ink'], muted=paint['muted'], accent=paint['accent'], tag=False)
    rooms = [box[3] - 2 * pad_y - head for box in boxes]
    sizes = _settle(ctx, cards, make, inner, rooms)
    every = [sizes] * n
    if n == 3:
        # The bento's tall card is the feature: a step larger than the two beside it, if it holds that.
        larger = tuple(pair for pair in ((24, 17), (22, 16), (21, 15)) if pair > sizes) + (sizes,)
        every[0] = _settle(ctx, cards[:1], make, inner, rooms[0], larger)
    for k, (item, (x, y, w, h)) in enumerate(zip(cards, boxes)):
        paint, sizes = paints[k], every[k]
        rect(ctx, (x, y, w, h), paint['fill'])
        rect(ctx, (x, y, bar, h), _line(ctx, paint['fill']))
        left = x + bar + pad
        figure(ctx, (left, y + pad_y, 1.2, head - 0.06), _number(k), size=26, colour=paint['accent'],
               anchor='middle')
        _tag_box(ctx, (left + 1.3, y + pad_y + (head - 0.06 - TAG) / 2, inner - 1.3, TAG), item, paint['accent'],
                 'right')
        block(ctx, (left, y + pad_y + head, inner, h - 2 * pad_y - head), make(k, item, *sizes),
              anchor='bottom' if n == 3 and k == 0 else 'top')


@variant('cards', 'dark_cards', counts=(3, 4))
def dark_cards(ctx, section, lines):
    """A row of dark cards under a centred heading, an accent number chip on each top edge and the tag at right."""
    top = _centre_top(ctx, section)
    cards = entries('cards', section)
    n = len(cards)
    spans = split(LEFT, WIDTH, n, 0.3)
    width = spans[0][1]
    panel = inks(strong(ctx))
    chip_fill = _mark(ctx, panel['fill'], ('accent', 'secondary', 'accent_soft', 'surface'))
    tag_ink = panel['accent'] if panel['fill'] == 'accent' else readable(ctx, 'accent', panel['fill'])
    pad, chip_h, chip_w = 0.26, 0.46, 0.8
    lift = chip_h / 2
    room = FOOT - (top + 0.2 + lift)
    inner = width - 2 * pad
    # The tags stand at top right beside the chips; one too long for that goes, with every card's, on a line
    # of its own between the chip and the label.
    beside = inner - chip_w - 0.15
    inline = all(_tag_width(item) <= beside for item in cards)
    body_top = lift + 0.3 if inline else lift + 0.08 + TAG

    def make(k, item, label, body):
        return _card(item, label, body, ink=panel['ink'], muted=panel['muted'], accent=tag_ink, tag=False)
    sizes = _settle(ctx, cards, make, inner, room - body_top - pad)
    need = max(_need(ctx, inner, make(k, item, *sizes)) for k, item in enumerate(cards))
    tall = min(room, max(need + body_top + pad, 2.2))
    y = top + 0.2 + lift + (room - tall) / 2
    for k, (item, (x, w)) in enumerate(zip(cards, spans)):
        rect(ctx, (x, y, w, tall), panel['fill'])
        badge(ctx, (x + pad, y - lift, chip_w, chip_h), _number(k), fill=chip_fill, ink=inks(chip_fill)['ink'],
              shape='rounded', size=16, heading=True)
        if inline:
            _tag_box(ctx, (x + pad + chip_w + 0.15, y + 0.1, beside, 0.26), item, tag_ink, 'right')
        else:
            _tag_box(ctx, (x + pad, y + lift + 0.08, inner, TAG), item, tag_ink)
        block(ctx, (x + pad, y + body_top, inner, tall - body_top - pad), make(k, item, *sizes))


@variant('cards', 'orbit', counts=(3, 5))
def orbit(ctx, section, lines):
    """A ring at left, the heading at its centre and a numbered disc per card on it; the cards listed at right."""
    cards = entries('cards', section)
    n = len(cards)
    radius = 2.0
    cx, cy = LEFT + 0.34 + radius, TOP_EDGE + (FOOT - TOP_EDGE) / 2
    fills = hues(ctx, n)
    ring(ctx, disc(cx, cy, 2 * radius), _line(ctx), width=1.5)
    core = disc(cx, cy, 2 * radius - 0.5)
    oval(ctx, core, 'accent_soft')
    room = inscribed(core)
    size = _word_size(ctx, section['heading'], room[2], 26)
    # The eyebrow heads the core; a heading that needs the whole core sends it to the frame's top left.
    if _heading_fit(ctx, section, room[2], room[3] - 0.36, size, 6):
        eyebrow(ctx, (room[0], room[1], room[2], 0.3), colour='soft_muted', align='center')
        room = (room[0], room[1] + 0.36, room[2], room[3] - 0.36)
    else:
        eyebrow(ctx)
    headline(ctx, section, room, size=size, lines=6, anchor='middle', align='center', colour='soft_ink')
    small = 0.62
    for k, (x, y) in enumerate(around(cx, cy, radius, n)):
        badge(ctx, disc(x, y, small), _number(k), fill=fills[k]['fill'], ink=fills[k]['ink'], size=15, heading=True)
    rx = cx + radius + small / 2 + 0.45
    dot = 0.5
    bx, bw = rx + dot + 0.28, RIGHT - rx - dot - 0.28
    gap = 0.1 if n >= 5 else 0.2
    most = (FOOT - TOP_EDGE - gap * (n - 1)) / n
    label, body = _row_sizes(ctx, cards, bw, most)
    tallest = max(sum(_row_need(ctx, item, label, body, bw)) for item in cards)
    pitch = min(most + gap, tallest + 0.42)
    span = (n - 1) * pitch + tallest
    y0 = max(TOP_EDGE, min(cy - span / 2, FOOT - span))
    for k, item in enumerate(cards):
        y = y0 + k * pitch
        badge(ctx, (rx, y, dot, dot), _number(k), fill=fills[k]['fill'], ink=fills[k]['ink'], size=13, heading=True)
        _row(ctx, bx, y, bw, item, label, body)
