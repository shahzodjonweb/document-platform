"""Agenda variants: numbered rows, tiles and columns, each item's number its own mark."""
from . import variant
from .kit import (FOOT, LEFT, RIGHT, RULE, WIDTH, badge, block, entries, eyebrow, figure, fits, header_band,
                  header_side, headline, height, hues, inks, line, oval, rect, ring, rounded, rule, split, strong,
                  text, tones)

LABEL_WORDS, TEXT_WORDS = 8, 22
# (label, text) sizes tried in turn; every item of a slide is set at the first pair that holds them all.
SIZES = ((18, 14), (17, 14), (17, 13), (16, 13), (16, 12), (15, 12))


def _number(position):
    return f'{position + 1:02d}'


def _limit(value, words):
    """`value` as a word limit leaves it, for measuring only: nothing is marked (drawing clips and marks)."""
    parts = str(value or '').split()
    return ' '.join(parts) if len(parts) <= words else ' '.join(parts[:words]).rstrip(',;:.') + '…'


def _held(item):
    """An item with its label and sentence as they will be set, so sizes are chosen for the words drawn."""
    return {**item, 'label': _limit(item.get('label'), LABEL_WORDS), 'text': _limit(item.get('text'), TEXT_WORDS)}


def _paragraphs(item, label, body, *, ink, muted, heading=True, after=4):
    """An item's label over its sentence, at fixed sizes (they were chosen to fit)."""
    return [dict(text=item['label'], words=LABEL_WORDS, size=label, floor=label, colour=ink, bold=True,
                 heading=heading, after=after),
            dict(text=item.get('text'), words=TEXT_WORDS, size=body, floor=body, colour=muted)]


def _sizes(ctx, cases, sizes=SIZES, **options):
    """The first (label, text) pair at which every (box, item) in `cases` holds whole; else the last pair."""
    for label, body in sizes:
        if all(fits(ctx, box, _paragraphs(_held(item), label, body, ink='ink', muted='muted', **options))
               for box, item in cases):
            return label, body
    return sizes[-1]


def _need(ctx, item, width, label, body, *, heading=True, after=4):
    """Inches an item's label and sentence take at these sizes in a box `width` wide."""
    item = _held(item)
    total = height(ctx, item['label'], width, label, bold=True, heading=heading) + after / 72
    if item.get('text'):
        total += height(ctx, item['text'], width, body)
    return total


def _heading(ctx, section, box, *, size, lines=2, align='left', colour=None):
    """The heading top-anchored in `box`, the box cut to the lines it takes; returns where its last line ends.

    The size and lines are worked out as kit.headline works them, so a rule set under the returned edge keeps
    the same clear gap under a one-line heading as under a two-line one, instead of touching its descenders.
    """
    x, y, width, _ = box
    value = _limit(section.get('heading'), 14)

    def count(points):
        return max(1, round(height(ctx, value, width, points, heading=True, spacing=1.0) * 72 / points))
    points = size
    while points > 18 and count(points) > lines:
        points -= 2
    tall = min(count(points), lines) * points * 1.08 / 72
    headline(ctx, section, (x, y, width, tall + 0.06), size=size, lines=lines, anchor='top', align=align,
             colour=colour)
    return y + tall


def _rows(top, bottom, n, most):
    """`n` equal rows between `top` and `bottom`, no taller than `most`, centred: (tops, pitch)."""
    room = bottom - top
    pitch = min(most, room / n)
    start = top + (room - pitch * n) / 2
    return [start + k * pitch for k in range(n)], pitch


# ---------------------------------------------------------------- side panel


@variant('agenda', 'side_panel')
def side_panel(ctx, section, lines):
    """The heading on a strong panel down the left third; the items beside it as rows on numbered accent discs."""
    items = entries('agenda', section)
    width, pad = 3.95, 0.42
    panel = inks(strong(ctx))
    rect(ctx, (LEFT, 0.62, width, FOOT - 0.62), panel['fill'])
    eyebrow(ctx, (LEFT + pad, 0.98, width - 2 * pad, 0.3), colour=panel['muted'])
    rule(ctx, (LEFT + pad, 1.4, 0.9, RULE), colour=panel['ink'])
    headline(ctx, section, (LEFT + pad, 1.62, width - 2 * pad, 3.75), size=30, lines=6, anchor='top',
             colour=panel['ink'])
    # One dot for each item at the foot of the panel, the first filled.
    for position in range(len(items)):
        dot = (LEFT + pad + position * 0.3, FOOT - 0.62, 0.15, 0.15)
        if position == 0:
            oval(ctx, dot, panel['ink'])
        else:
            ring(ctx, dot, panel['ink'], width=1.0)

    x = LEFT + width + 0.6
    size = 0.62
    left = x + size + 0.32
    column = RIGHT - left
    tops, pitch = _rows(0.82, FOOT - 0.2, len(items), 1.3)
    cases = [((left, top + 0.06, column, pitch - 0.12), item) for top, item in zip(tops, items)]
    label, body = _sizes(ctx, cases)
    for position, (item, top) in enumerate(zip(items, tops)):
        middle = top + pitch / 2
        badge(ctx, (x, middle - size / 2, size, size), _number(position), fill='accent', ink='on_accent', size=17,
              heading=True)
        block(ctx, (left, top + 0.06, column, pitch - 0.12),
              _paragraphs(item, label, body, ink='ink', muted='muted'), anchor='middle')
        if position < len(items) - 1:
            line(ctx, (x, top + pitch), (RIGHT, top + pitch), 'accent_soft', width=0.75)


# ---------------------------------------------------------------- number tiles


def _tile_cells(n):
    """The heading's cell and the items' cells as (column, row, span) on a grid of (columns, rows)."""
    if n == 3:
        return (2, 2), (0, 0, 1), [(1, 0, 1), (0, 1, 1), (1, 1, 1)]
    if n == 4:
        return (3, 2), (0, 0, 2), [(2, 0, 1), (0, 1, 1), (1, 1, 1), (2, 1, 1)]
    # Five: a full three by two. Six do not fit three a row at the guide's length, so the variant stops at five.
    return (3, 2), (0, 0, 1), [(1, 0, 1), (2, 0, 1), (0, 1, 1), (1, 1, 1), (2, 1, 1)]


@variant('agenda', 'number_tiles', counts=(3, 5))
def number_tiles(ctx, section, lines):
    """A grid of tiles: the heading on a strong one, each item on its own under a huge accent number."""
    items = entries('agenda', section)
    (columns, rows), head, cells = _tile_cells(len(items))
    gap = 0.2
    spans = split(LEFT, WIDTH, columns, gap)
    tall = (FOOT - 0.62 - gap * (rows - 1)) / rows

    def box(column, row, span):
        x = spans[column][0]
        width = spans[column + span - 1][0] + spans[column + span - 1][1] - x
        return x, 0.62 + row * (tall + gap), width, tall

    pad = 0.26
    panel = inks(strong(ctx))
    x, y, w, h = box(*head)
    rounded(ctx, (x, y, w, h), panel['fill'], radius=0.14)
    eyebrow(ctx, (x + pad, y + pad, w - 2 * pad, 0.3), colour=panel['muted'])
    rule(ctx, (x + pad, y + h - pad - RULE, 0.9, RULE), colour=panel['ink'])
    # A wide heading tile takes a larger heading, so it does not sit as one thin line under an empty tile.
    headline(ctx, section, (x + pad, y + pad + 0.4, w - 2 * pad, h - 2 * pad - 0.62), size=36 if w > 5 else 30,
             lines=4 if w > 5 else 5, anchor='bottom', colour=panel['ink'])

    tile = inks('card')
    number = 0.8
    cases = [((b[0] + pad, b[1] + pad + number, b[2] - 2 * pad, b[3] - 2 * pad - number), item)
             for b, item in zip((box(*cell) for cell in cells), items)]
    label, body = _sizes(ctx, cases)
    # Every tile's words start on one line, as low as the fullest tile allows: the number at top, the words below.
    room = cases[0][0][3]
    need = min(room, max(_need(ctx, item, b[2], label, body) for b, item in cases) + 0.1)
    for position, (item, cell) in enumerate(zip(items, cells)):
        x, y, w, h = box(*cell)
        rounded(ctx, (x, y, w, h), tile['fill'], radius=0.14)
        # The figure's box is a little taller than the band it heads, so the 54 pt number is not shrunk to fit it.
        figure(ctx, (x + pad - 0.03, y + pad - 0.12, w - 2 * pad, number + 0.1), _number(position), size=54,
               colour=tile['accent'])
        block(ctx, (x + pad, y + h - pad - need, w - 2 * pad, need),
              _paragraphs(item, label, body, ink=tile['ink'], muted=tile['muted']))


# ---------------------------------------------------------------- ring list


@variant('agenda', 'ring_list')
def ring_list(ctx, section, lines):
    """The heading in a column behind a thin accent divider; rows of a ring-outlined number, label and sentence."""
    items = entries('agenda', section)
    start = header_side(ctx, section, width=3.05, size=28, lines=6)
    divider = start - 0.22
    line(ctx, (divider, 0.62), (divider, FOOT), 'accent_text', width=1.25)
    x = start + 0.25
    size = 0.6
    label_x = x + size + 0.3
    label_w = 2.9
    text_x = label_x + label_w + 0.3
    text_w = RIGHT - text_x
    tops, pitch = _rows(0.62, FOOT, len(items), 1.2)
    label, body = SIZES[-1]
    for trial in SIZES:
        if all(fits(ctx, (label_x, row + 0.05, label_w, pitch - 0.1),
                    [dict(text=item['label'], size=trial[0], bold=True, heading=True)])
               and fits(ctx, (text_x, row + 0.05, text_w, pitch - 0.1), [dict(text=item.get('text'), size=trial[1])])
               for row, item in zip(tops, map(_held, items))):
            label, body = trial
            break
    for position, (item, top) in enumerate(zip(items, tops)):
        middle = top + pitch / 2
        badge(ctx, (x, middle - size / 2, size, size), _number(position), fill='accent_text', ink='accent_text',
              shape='ring', size=16, heading=True)
        text(ctx, (label_x, top + 0.05, label_w, pitch - 0.1), item['label'], words=LABEL_WORDS, size=label,
             floor=label, colour='ink', bold=True, heading=True, anchor='middle')
        text(ctx, (text_x, top + 0.05, text_w, pitch - 0.1), item.get('text'), words=TEXT_WORDS, size=body,
             floor=body, colour='muted', anchor='middle')


# ---------------------------------------------------------------- columns


@variant('agenda', 'columns', counts=(3, 5))
def columns(ctx, section, lines):
    """A centred heading over columns, each a disc in its own colour, a short rule, the label and its sentence."""
    items = entries('agenda', section)
    # A centred top of its own: header_center's rule sits so close under a one-line heading that, centred, it
    # reads as an underline of the middle word.
    eyebrow(ctx, (LEFT, 0.62, WIDTH, 0.3), align='center')
    end = _heading(ctx, section, (LEFT + 0.8, 1.02, WIDTH - 1.6, 1.1), size=32, align='center')
    rule(ctx, (LEFT + WIDTH / 2 - 0.55, end + 0.24, 1.1, RULE))
    top = end + 0.24 + RULE + 0.5
    n = len(items)
    gap = 0.5 if n < 5 else 0.38
    spans = split(LEFT, WIDTH, n, gap)
    width = spans[0][1]
    size = 0.78 if n < 5 else 0.7
    lead = size + 0.42  # disc, then the rule, then the words
    room = FOOT - 0.05 - top - lead
    cases = [((x, top + lead, width, room), item) for item, (x, _) in zip(items, spans)]
    label, body = _sizes(ctx, cases)
    need = max(_need(ctx, item, width, label, body) for item in items)
    # Brief content sits in the middle of the room under the heading, not stranded at its top.
    y = top + max(0.0, (room - need) / 2) * 0.8
    paints = hues(ctx, n)
    for position, (item, (x, _), paint) in enumerate(zip(items, spans, paints)):
        badge(ctx, (x, y, size, size), _number(position), fill=paint['fill'], ink=paint['ink'], size=18,
              heading=True)
        rect(ctx, (x, y + size + 0.2, 0.55, RULE), paint['fill'])
        block(ctx, (x, y + lead, width, FOOT - 0.05 - y - lead),
              _paragraphs(item, label, body, ink='ink', muted='muted'))
        if position:
            middle = x - gap / 2
            line(ctx, (middle, y + 0.1), (middle, min(FOOT - 0.05, y + lead + need + 0.1)), 'accent_soft',
                 width=0.75)


# ---------------------------------------------------------------- tone pills


@variant('agenda', 'tone_pills')
def tone_pills(ctx, section, lines):
    """Rows that open on a pill in a tone of the accent holding the number and label; the sentence beside it."""
    items = entries('agenda', section)
    n = len(items)
    # Six rows take a slimmer band, so each pill keeps air round a two-line label.
    top = header_band(ctx, section, fill='accent_soft', height=1.5 if n < 6 else 1.32, size=28)
    top -= 0 if n < 6 else 0.1
    pill_w = 4.85
    pad = 0.3
    number_w = 0.5
    label_x = LEFT + pad + number_w + 0.1
    label_w = LEFT + pill_w - pad - label_x
    text_x = LEFT + pill_w + 0.4
    text_w = RIGHT - text_x
    tops, pitch = _rows(top, FOOT, n, 0.95)
    gap = 0.12 if pitch > 0.8 else 0.08
    inner = pitch - gap

    def holds(trial, air):
        return all(fits(ctx, (label_x, row, label_w, inner - air),
                        [dict(text=item['label'], size=trial[0], bold=True, heading=True)])
                   and fits(ctx, (text_x, row, text_w, inner), [dict(text=item.get('text'), size=trial[1])])
                   for row, item in zip(tops, map(_held, items)))
    # The largest sizes that leave the label clear of the pill's edges; failing that, ones that only fit it.
    trials = ((17, 14), (16, 14), (16, 13), (15, 13), (15, 12))
    label, body = next((trial for air in (0.16, 0.12, 0.08) for trial in trials if holds(trial, air)), trials[-1])
    paints = tones(ctx, max(3, len(items)))
    for position, (item, top, paint) in enumerate(zip(items, tops, paints)):
        y = top + gap / 2
        rounded(ctx, (LEFT, y, pill_w, inner), paint['fill'], radius=inner / 2)
        text(ctx, (LEFT + pad, y + 0.04, number_w, inner - 0.08), _number(position), size=label, colour=paint['ink'],
             bold=True, heading=True, anchor='middle')
        text(ctx, (label_x, y + 0.04, label_w, inner - 0.08), item['label'], words=LABEL_WORDS, size=label,
             floor=label, colour=paint['ink'], bold=True, heading=True, anchor='middle')
        text(ctx, (text_x, y, text_w, inner), item.get('text'), words=TEXT_WORDS, size=body, floor=body,
             colour='ink', anchor='middle')


# ---------------------------------------------------------------- contents page


CONTENTS_SIZES = ((19, 14), (18, 14), (18, 13), (17, 13), (17, 12), (16, 12), (15, 12))


def _contents_grid(n, top, columns):
    """The contents page's rows in `columns` columns: (spans, rows per column, pitch, number width, measure)."""
    per = -(-n // columns)
    spans = split(LEFT, WIDTH, columns, 0.8)
    pitch = min(1.3 if columns == 1 else 1.5, (FOOT - top) / per)
    number_w = 1.2 if columns == 1 else 0.9
    # The sentences keep a reading measure; the gap between them and the numbers is the page's own.
    return spans, per, pitch, number_w, min(8.6, spans[0][1] - number_w - (0.6 if columns == 1 else 0.35))


def _contents_sizes(ctx, items, top, columns, air):
    """The largest (label, text) pair that sets every row with `air` above and below its words, or None."""
    _, per, pitch, _, measure = _contents_grid(len(items), top, columns)
    for pair in CONTENTS_SIZES:
        if all(fits(ctx, (LEFT, top + air, measure, pitch - 2 * air),
                    _paragraphs(_held(item), *pair, ink='ink', muted='muted', after=2)) for item in items):
            return pair
    return None


@variant('agenda', 'contents_page')
def contents_page(ctx, section, lines):
    """A book's contents page: each label over its sentence, its number large at right, a hairline under each row."""
    items = entries('agenda', section)
    eyebrow(ctx)
    # The heavy rule keeps one clear gap under the heading's last line, however many lines it takes.
    end = _heading(ctx, section, (LEFT, 0.95, WIDTH - 2.0, 1.0), size=32)
    rule_y = end + 0.17
    line(ctx, (LEFT, rule_y), (RIGHT, rule_y), 'ink', width=1.75)
    top = rule_y + 0.04
    n = len(items)
    # One column, as in a book; a full page of long entries takes two columns rather than rows packed against
    # their hairlines, and only if neither leaves air are the rows set tight.
    columns, sizes = 1, _contents_sizes(ctx, items, top, 1, 0.08)
    if sizes is None and n > 4:
        columns, sizes = 2, _contents_sizes(ctx, items, top, 2, 0.1)
    if sizes is None:
        columns, sizes = 1, _contents_sizes(ctx, items, top, 1, 0.02) or CONTENTS_SIZES[-1]
    label, body = sizes
    spans, per, pitch, number_w, measure = _contents_grid(n, top, columns)
    figure_size = 40 if pitch > 0.85 else 34
    bottom = top + per * pitch
    for position, item in enumerate(items):
        column, row = divmod(position, per)
        x, width = spans[column]
        y = top + row * pitch
        block(ctx, (x, y + 0.02, measure, pitch - 0.04),
              _paragraphs(item, label, body, ink='ink', muted='muted', after=2), anchor='middle')
        figure(ctx, (x + width - number_w, y + 0.06, number_w, pitch - 0.14), _number(position), size=figure_size,
               colour='accent_text', align='right', anchor='middle')
        if y + pitch < bottom - 0.01:
            line(ctx, (x, y + pitch), (x + width, y + pitch), 'accent_soft', width=0.75)
    line(ctx, (LEFT, bottom - 0.01), (RIGHT, bottom - 0.01), 'ink', width=0.75)
