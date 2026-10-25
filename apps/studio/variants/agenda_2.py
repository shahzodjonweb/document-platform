"""Agenda variants: each part of the talk on a mark of its place — folder tabs, route stops, tones, rules, circles."""
from pptx.util import Inches

from . import variant
from ..slide_layouts import _paragraph_height, _text_lines
from .kit import (FOOT, LEFT, RIGHT, RULE, WIDTH, Z, block, disc, entries, eyebrow, figure, grid, header_band,
                  header_center, header_compact, headline, hues, inks, inscribed, line, oval, polygon, rect, ring,
                  rounded, rule, split, tab_points, text, tones, triangle_points)

LABEL_WORDS, TEXT_WORDS = 8, 22  # the classic drawer's word limits
EDGE = 0.62                      # the frame's top
# (label, text) sizes, largest first: every item of a slide takes the first pair that all of them hold.
LADDER = ((20, 15), (19, 15), (19, 14), (18, 14), (17, 14), (17, 13), (16, 13), (16, 12), (15, 12))


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
        value = _plain(paragraph.get('text'), paragraph.get('words'))
        if not value:
            continue
        total += _paragraph_height(dict(text=value, size=paragraph['size'], bold=_bold(ctx, paragraph),
                                        before=paragraph.get('before', 0), after=paragraph.get('after', 0),
                                        spacing=paragraph.get('spacing', 1.15)), zone)
    return (total + 3.5) / 72  # block keeps 3 pt spare; the half point covers rounding to whole EMU


def _whole(ctx, width, paragraphs):
    """Whether every word of `paragraphs` keeps to one line `width` wide (none is broken mid-word)."""
    for paragraph in paragraphs:
        for word in _plain(paragraph.get('text'), paragraph.get('words')).split():
            if _text_lines(word, paragraph['size'], Inches(width), bold=_bold(ctx, paragraph)) > 1:
                return False
    return True


def _holds(ctx, width, room, paragraphs):
    return _need(ctx, width, paragraphs) <= room and _whole(ctx, width, paragraphs)


def _story(item, label, body, *, ink='ink', muted='muted', align='left', after=4):
    """An item's label over its sentence, at fixed sizes (chosen beforehand to fit)."""
    return [dict(text=item['label'], words=LABEL_WORDS, size=label, floor=label, colour=ink, bold=True,
                 heading=True, after=after, align=align),
            dict(text=item.get('text'), words=TEXT_WORDS, size=body, floor=body, colour=muted, align=align)]


def _settle(ctx, cases, ladder=LADDER, **options):
    """The first (label, text) sizes at which every (width, room, item) in `cases` holds its story whole."""
    for label, body in ladder:
        if all(_holds(ctx, width, room, _story(item, label, body, **options)) for width, room, item in cases):
            return label, body
    return ladder[-1]


def _tallest(ctx, width, items, label, body, **options):
    return max(_need(ctx, width, _story(item, label, body, **options)) for item in items)


def _one(ctx, value, width, size, *, words, bold=False, heading=False):
    """Inches one field takes at `size` in a box `width` wide, and whether no word of it is broken."""
    paragraph = dict(text=value, words=words, size=size, bold=bold, heading=heading)
    return _need(ctx, width, [paragraph]), _whole(ctx, width, [paragraph])


def _number(position):
    return f'{position + 1:02d}'


def _centre_top(ctx, section, size=28):
    """Eyebrow, heading and rule centred and compact. Returns where the body starts (2.25)."""
    eyebrow(ctx, (LEFT, EDGE, WIDTH, 0.3), align='center')
    headline(ctx, section, (LEFT + 1.0, 0.9, WIDTH - 2.0, 1.0), size=size, lines=2, align='center')
    rule(ctx, (LEFT + WIDTH / 2 - 0.45, 2.02, 0.9, RULE))
    return 2.25


# ---------------------------------------------------------------- folder tabs


@variant('agenda', 'folder_tabs', counts=(3, 5))
def folder_tabs(ctx, section, lines):
    """A row of folders, each opening on a cut-corner tab in its own colour with its number; the words on the folder."""
    items = entries('agenda', section)
    n = len(items)
    top = _centre_top(ctx, section) + 0.1
    gap = 0.26 if n < 5 else 0.2
    spans = split(LEFT, WIDTH, n, gap)
    width = spans[0][1]
    tab_h, strip, pad = 0.62, 0.08, (0.24 if n < 5 else 0.2)
    head = tab_h + strip
    inner = width - 2 * pad
    room = FOOT - top - head
    label, body = _settle(ctx, [(inner, room - 2 * pad, item) for item in items])
    need = _tallest(ctx, inner, items, label, body)
    # A folder is never much shorter than the room, so brief words still sit on a folder, not a ribbon, and the
    # row stands in the middle of the space under the heading.
    tall = min(room, max(need + 2 * pad + 0.2, room * 0.66))
    y = top + (room - tall) * 0.5
    tab_w = min(width * 0.6, 1.55)
    for position, (item, (x, _), paint) in enumerate(zip(items, spans, hues(ctx, n))):
        polygon(ctx, tab_points((x, y, tab_w, tab_h + 0.02), cut=0.28, corner='top_right'), paint['fill'])
        rect(ctx, (x, y + tab_h, width, strip), paint['fill'])
        rect(ctx, (x, y + head, width, tall), 'card')
        text(ctx, (x + 0.2, y + 0.08, tab_w - 0.2 - 0.34, tab_h - 0.12), _number(position), size=20,
             colour=paint['ink'], bold=True, heading=True, anchor='middle')
        block(ctx, (x + pad, y + head + pad, inner, tall - 2 * pad),
              _story(item, label, body, ink='card_ink', muted='card_muted'))


# ---------------------------------------------------------------- route


@variant('agenda', 'route')
def route(ctx, section, lines):
    """The talk as a route: a thick accent line from a starting dot to an arrowhead, a ringed stop for each item."""
    items = entries('agenda', section)
    n = len(items)
    # Centred over a route that spans the slide. (header_number's big slide number read as one more stop.)
    top = header_center(ctx, section)
    gap = 0.34 if n < 5 else 0.24
    spans = split(LEFT, WIDTH, n, gap)
    width = spans[0][1]
    stop = {3: 0.9, 4: 0.82, 5: 0.7}.get(n, 0.64)
    lead = stop + 0.26
    room = FOOT - 0.05 - top - lead
    label, body = _settle(ctx, [(width, room, item) for item in items], align='center')
    need = _tallest(ctx, width, items, label, body, align='center')
    y = top + max(0.0, room - need) * 0.4
    cy = y + stop / 2
    centres = [x + width / 2 for x, _ in spans]
    # The road: a starting dot, a segment between each pair of stops, an arrowhead at the far end.
    dot = 0.2
    oval(ctx, (LEFT, cy - dot / 2, dot, dot), 'accent_text')
    ends = [LEFT + dot] + [c for centre in centres for c in (centre - stop / 2, centre + stop / 2)] + [RIGHT - 0.26]
    for start, end in zip(ends[::2], ends[1::2]):
        if end - start > 0.05:
            line(ctx, (start, cy), (end, cy), 'accent_text', width=4.5)
    polygon(ctx, triangle_points((RIGHT - 0.3, cy - 0.17, 0.3, 0.34), 'right'), 'accent_text')
    for position, (item, (x, _), centre) in enumerate(zip(items, spans, centres)):
        box = disc(centre, cy, stop)
        oval(ctx, box, 'surface', line='accent_text', line_width=4)
        text(ctx, inscribed(box, 0.6), _number(position), size={3: 22, 4: 20, 5: 18}.get(n, 16),
             colour='accent_text', bold=True, heading=True, align='center', anchor='middle')
        block(ctx, (x, y + lead, width, FOOT - 0.05 - y - lead), _story(item, label, body, align='center'))


# ---------------------------------------------------------------- tone cards


@variant('agenda', 'tone_cards')
def tone_cards(ctx, section, lines):
    """Cards shaded from the accent's darkest tone to its lightest, each numbered in the tone's own ink."""
    items = entries('agenda', section)
    n = len(items)
    top = header_compact(ctx, section) + (0.05 if n <= 4 else 0)
    per_row = n if n <= 4 else 3
    rows = -(-n // per_row)
    gap = 0.22 if rows == 1 else 0.18
    pad = 0.26 if rows == 1 else 0.22
    room = FOOT - top
    card_w = (WIDTH - gap * (per_row - 1)) / per_row
    inner = card_w - 2 * pad
    each = (room - gap * (rows - 1)) / rows
    paints = tones(ctx, n)
    if rows == 1:
        # One row: the number large at the top of each card, the words under it.
        number = 0.8
        label, body = _settle(ctx, [(inner, each - 2 * pad - number, item) for item in items])
        need = _tallest(ctx, inner, items, label, body) + number
        tall = min(each, max(need + 2 * pad + 0.3, 2.5))
        y = top + (room - tall) * 0.45
        for position, (item, (x, _), paint) in enumerate(zip(items, split(LEFT, WIDTH, n, gap), paints)):
            rounded(ctx, (x, y, card_w, tall), paint['fill'], radius=0.12)
            figure(ctx, (x + pad - 0.02, y + pad - 0.1, inner, number), _number(position), size=44,
                   colour=paint['ink'])
            block(ctx, (x + pad, y + pad + number, inner, tall - 2 * pad - number),
                  _story(item, label, body, ink=paint['ink'], muted=paint['muted']))
        return
    # Two rows: as in one row, the number on a line of its own over the label and sentence, only smaller. (A
    # number beside the label made the sentence's place hang on how the label was measured to wrap, leaving a
    # gap above it whenever the label set on fewer lines.) Each row is as tall as its fullest card needs, and the
    # rows sit together in the middle of the room.
    number, pad, pad_y = 0.42, 0.2, 0.16
    inner = card_w - 2 * pad
    label, body = _settle(ctx, [(inner, each - 2 * pad_y - number, item) for item in items], ladder=LADDER[3:])
    needs = [number + _need(ctx, inner, _story(item, label, body)) for item in items]
    heights = [min(each, max(max(needs[r * per_row:(r + 1) * per_row]) + 2 * pad_y + 0.1, 1.5)) for r in range(rows)]
    y = top + (room - sum(heights) - gap * (rows - 1)) * 0.45
    for position, (item, paint) in enumerate(zip(items, paints)):
        row, column = divmod(position, per_row)
        in_row = min(per_row, n - row * per_row)
        x = LEFT + (WIDTH - in_row * card_w - (in_row - 1) * gap) / 2 + column * (card_w + gap)
        by = y + sum(heights[:row]) + gap * row
        rounded(ctx, (x, by, card_w, heights[row]), paint['fill'], radius=0.12)
        figure(ctx, (x + pad - 0.01, by + pad_y - 0.02, inner, number), _number(position), size=24,
               colour=paint['ink'])
        block(ctx, (x + pad, by + pad_y + number, inner, heights[row] - 2 * pad_y - number),
              _story(item, label, body, ink=paint['ink'], muted=paint['muted']))


# ---------------------------------------------------------------- divided columns


def _mark(size):
    """The height of an item's number row (its number with a hairline running on from it) at `size` points."""
    return (size * 1.1 + 3.5) / 72 + 0.06


def _marked(ctx, item, position, box, label, body, size):
    """An item opening on its number and a hairline, its label and sentence under them at the box's full width."""
    x, y, w, h = box
    mark = _mark(size)
    tall = mark - 0.06
    figure(ctx, (x - 0.01, y, size / 72 * 1.6, tall), _number(position), size=size, colour='accent_text',
           bold=True, anchor='middle')
    # Level with the middle of the digits, which sit a little below the middle of their line.
    middle = y + tall / 2 + size / 72 * 0.06
    line(ctx, (x + size / 72 * 1.6 + 0.08, middle), (x + w, middle), 'accent_soft', width=1.25)
    block(ctx, (x, y + mark, w, h - mark), _story(item, label, body))


@variant('agenda', 'divided_columns')
def divided_columns(ctx, section, lines):
    """The heading in a column behind a full-height accent rule; the items beside it, each opening on its number
    and a hairline, in two columns past three."""
    items = entries('agenda', section)
    n = len(items)
    side = 3.2
    eyebrow(ctx, (LEFT, EDGE, side, 0.3))
    headline(ctx, section, (LEFT, 1.05, side, 5.2), size=32, lines=6, anchor='middle')
    bar = LEFT + side + 0.4
    rect(ctx, (bar, EDGE, 0.07, FOOT - EDGE), 'accent')
    x0 = bar + 0.07 + 0.5
    columns = 1 if n <= 3 else 2
    gutter = 0.45
    col_w = (RIGHT - x0 - gutter * (columns - 1)) / columns
    per = -(-n // columns)
    room = FOOT - EDGE
    space = 0.32 if columns == 1 else 0.2  # left under each item
    size = 28 if columns == 1 else 22
    each = room / per
    label, body = _settle(ctx, [(col_w, each - _mark(size) - space, item) for item in items])
    need = _mark(size) + _tallest(ctx, col_w, items, label, body)
    # Every row as tall as the fullest item, a little looser when there is room; the rows centred on the bar.
    pitch = min(each, need + space + (0.3 if columns == 1 else 0.15))
    y0 = EDGE + (room - pitch * per) / 2
    for position, item in enumerate(items):
        column, row = divmod(position, per)
        _marked(ctx, item, position, (x0 + column * (col_w + gutter), y0 + row * pitch, col_w, pitch - space),
                label, body, size)


# ---------------------------------------------------------------- circle grid


@variant('agenda', 'circle_grid')
def circle_grid(ctx, section, lines):
    """Each item on a numbered disc in its own colour inside a thin ring, its words beside it, in up to two rows."""
    items = entries('agenda', section)
    n = len(items)
    top = header_band(ctx, section, fill='accent_soft', height=1.45, size=28)
    per_row = 2 if n == 4 else 3
    rows = -(-n // per_row)
    gap, row_gap = 0.4, 0.32
    size = 0.84
    halo = size + 0.22
    room = FOOT - top
    cell_w = (WIDTH - gap * (per_row - 1)) / per_row
    words_w = cell_w - halo - 0.24
    each = (room - row_gap * (rows - 1)) / rows
    paints = hues(ctx, n)
    cases = [(words_w, each, item) for item in items]
    label, body = _settle(ctx, cases)
    need = max(halo, _tallest(ctx, words_w, items, label, body))
    tall = min(each, need + 0.1)
    block_h = tall * rows + row_gap * (rows - 1)
    y = top + (room - block_h) * 0.45
    boxes = grid((LEFT, y, WIDTH, block_h), n, per_row, gap=gap, row_gap=row_gap)
    for position, (item, (x, by, w, h), paint) in enumerate(zip(items, boxes, paints)):
        own = _need(ctx, words_w, _story(item, label, body))
        # The circle sits level with the first line; short words sit level with the circle's middle.
        words_y = by + max(0.0, (halo - own) / 2)
        cx, cy = x + halo / 2, by + halo / 2
        ring(ctx, disc(cx, cy, halo), paint['fill'], width=1.25)
        box = disc(cx, cy, size)
        oval(ctx, box, paint['fill'])
        text(ctx, inscribed(box), _number(position), size=20, colour=paint['ink'], bold=True, heading=True,
             align='center', anchor='middle')
        block(ctx, (x + halo + 0.24, words_y, words_w, h - (words_y - by)),
              _story(item, label, body, ink=paint['text']))


# ---------------------------------------------------------------- current first


@variant('agenda', 'current_first')
def current_first(ctx, section, lines):
    """The first item on a full-width accent row marked as where the talk is now; the rest as quieter rows below."""
    items = entries('agenda', section)
    top = header_compact(ctx, section)
    marker_w, number_w = 0.52, 0.76
    label_x = LEFT + marker_w + number_w
    label_w = 3.6
    text_x = label_x + label_w + 0.35
    text_w = RIGHT - 0.3 - text_x
    room = FOOT - top
    lead, rest = items[0], items[1:]
    gap = 0.14

    def need(item, label, body):
        """Inches a row's label and sentence take side by side, or None if a word would break."""
        a, whole_a = _one(ctx, item['label'], label_w, label, words=LABEL_WORDS, bold=True, heading=True)
        b, whole_b = _one(ctx, item.get('text'), text_w, body, words=TEXT_WORDS)
        return max(a, b) if whole_a and whole_b else None

    # The first row is set a little larger than the rest; all the rest share one pair of sizes. A row keeps a
    # tenth of an inch clear above and below its words, so they never crowd its hairlines; a full agenda gives
    # some of that up rather than set its words smaller than 17/13.
    chosen = None
    for clear, ladder in ((0.2, LADDER[3:6]), (0.12, LADDER[3:])):
        for label, body in ladder:
            sizes = (label, body), (label + 2, body + 1)
            first = need(lead, *sizes[1])
            others = [need(item, *sizes[0]) for item in rest]
            if first is None or None in others:
                continue
            lead_h = max(0.9, first + clear + 0.08)
            least = max(others, default=0) + clear
            if lead_h + gap + least * len(rest) <= room:
                chosen = sizes, lead_h, least
                break
        if chosen:
            break
    if chosen is None:
        sizes = LADDER[-1], (LADDER[-1][0] + 2, LADDER[-1][1] + 1)
        chosen = sizes, 0.9, (room - 0.9 - gap) / max(1, len(rest))
    ((label, body), (first_label, first_body)), lead_h, least = chosen
    # The rows open up to an inch each when the room allows, so a short agenda is not huddled under the heading.
    pitch = max(least, min(1.0, (room - lead_h - gap) / max(1, len(rest)))) if rest else 0
    block_h = lead_h + gap + pitch * len(rest)
    y = top + max(0.0, room - block_h) * 0.45

    roles = inks('accent')
    rounded(ctx, (LEFT, y, WIDTH, lead_h), 'accent', radius=0.1)
    polygon(ctx, triangle_points((LEFT + 0.22, y + lead_h / 2 - 0.12, 0.17, 0.24), 'right'), roles['ink'])
    figure(ctx, (LEFT + marker_w, y + 0.1, number_w - 0.1, lead_h - 0.2), _number(0), size=30,
           colour=roles['ink'], anchor='middle')
    text(ctx, (label_x, y + 0.08, label_w, lead_h - 0.16), lead['label'], words=LABEL_WORDS, size=first_label,
         floor=first_label, colour=roles['ink'], bold=True, heading=True, anchor='middle')
    text(ctx, (text_x, y + 0.08, text_w, lead_h - 0.16), lead.get('text'), words=TEXT_WORDS, size=first_body,
         floor=first_body, colour=roles['ink'], anchor='middle')

    y += lead_h + gap
    for position, item in enumerate(rest, 1):
        row = y + (position - 1) * pitch
        figure(ctx, (LEFT + marker_w, row + 0.06, number_w - 0.1, pitch - 0.12), _number(position), size=22,
               colour='accent_text', anchor='middle')
        text(ctx, (label_x, row + 0.05, label_w, pitch - 0.1), item['label'], words=LABEL_WORDS, size=label,
             floor=label, colour='ink', bold=True, heading=True, anchor='middle')
        text(ctx, (text_x, row + 0.05, text_w, pitch - 0.1), item.get('text'), words=TEXT_WORDS, size=body,
             floor=body, colour='muted', anchor='middle')
        if position < len(rest):
            line(ctx, (LEFT + marker_w, row + pitch), (RIGHT, row + pitch), 'accent_soft', width=0.75)
