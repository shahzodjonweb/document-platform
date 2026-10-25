"""Comparison variants: the two columns as facing panels, split halves, a ruled table, row cards and a mirror."""
from pptx.util import Inches

from ..slide_layouts import _paragraph_height, _text_lines, _units
from ..slides import WIDTH_SAFETY, _luminance, contrast_ratio
from . import variant
from .kit import (FOOT, LEFT, RIGHT, RULE, WIDTH, Z, block, columns_of, diamond_points, entries, eyebrow,
                  header_band, header_center, header_compact, headline, hex_of, hues, inks, line, oval, polygon, rect,
                  rounded, rule, strong, tab_points, text, vs)

NAME, LABEL, CELL = 5, 6, 14          # the classic drawer's word limits: column names, criteria, cells
# (criterion, cell) point sizes, largest first: a slide takes the first at which every row fits.
SCALES = ((16, 16), (16, 15), (15, 15), (15, 14), (14, 14), (14, 13), (13, 13), (13, 12), (12, 12))
NAMES = (24, 23, 22, 21, 20, 19, 18, 17, 16)
HAIR = 0.75 / 72                       # a hairline's thickness
CELL_SPACING, LABEL_SPACING, NAME_SPACING = 1.18, 1.12, 1.08


# ---------------------------------------------------------------- measuring


def _clean(value, words=None):
    parts = str(value or '').split()
    return ' '.join(parts[:words] if words else parts)


def _need(ctx, width, paragraphs):
    """Inches `paragraphs` (as for kit.block) take in a box `width` wide, with block's own allowance."""
    zone = Z(0, 0, width, 1)
    total = 0.0
    for paragraph in paragraphs:
        if not paragraph:
            continue
        value = _clean(paragraph.get('text'), paragraph.get('words'))
        if not value:
            continue
        bold = bool(paragraph.get('bold')) or bool(paragraph.get('heading') and ctx.heading_bold)
        total += _paragraph_height(dict(text=value, size=paragraph['size'], bold=bold,
                                        before=paragraph.get('before', 0), after=paragraph.get('after', 0),
                                        spacing=paragraph.get('spacing', 1.15)), zone)
    return (total + 4) / 72 if total else 0.0


def _choose(fits, scales=SCALES):
    """The first sizes in `scales` at which `fits(sizes)` holds; the smallest if none does."""
    for sizes in scales:
        if fits(sizes):
            return sizes
    return scales[-1]


def _names(section):
    """The two column names, '' where the slide has none."""
    return (columns_of(section)[:2] + ['', ''])[:2]


def _name_fit(ctx, names, width, sizes=NAMES):
    """(size, height) for the two names: the largest size at which both take one line, else two lines."""
    def lines(value, size):
        value = _clean(value, NAME)
        return _text_lines(value, size, Inches(width), bold=True) if value else 1
    for size in sizes:
        if all(lines(value, size) <= 1 for value in names):
            return size, size * NAME_SPACING / 72 + 5 / 72
    size = sizes[-1]
    count = max(lines(value, size) for value in names)
    return size, count * size * NAME_SPACING / 72 + 5 / 72


def _criterion(item, size, colour, *, align='left', heading=True, after=0):
    return dict(text=item.get('label'), words=LABEL, size=size, floor=min(size, 12), colour=colour, bold=True,
                heading=heading, align=align, spacing=LABEL_SPACING, after=after)


def _cell(value, size, colour='ink', *, align='left'):
    return dict(text=value, words=CELL, size=size, floor=12, colour=colour, align=align, spacing=CELL_SPACING)


def _cells(ctx, rows, width, size):
    """The height the tallest of every row's two cells takes at `size` in a box `width` wide."""
    return max([_need(ctx, width, [_cell(item.get(key), size)]) for item in rows for key in ('text', 'value')]
               + [0.0])


def _labels(ctx, rows, width, size, *, heading=True):
    """The height the tallest criterion takes at `size` in a box `width` wide."""
    return max([_need(ctx, width, [_criterion(item, size, 'ink', heading=heading)]) for item in rows] + [0.0])


def _centred(top, room, used, bias=0.42):
    """Where content `used` inches tall starts in `room` inches below `top`: a little above the middle."""
    return top + max(0.0, (room - used) * bias)


def _put_name(ctx, box, value, size, colour, *, align='left', anchor='middle'):
    text(ctx, box, value, size=size, floor=min(size, 15), colour=colour, bold=True, heading=True, align=align,
         anchor=anchor, words=NAME, spacing=NAME_SPACING)


def _put_cell(ctx, box, value, size, colour, *, align='left', anchor='middle'):
    text(ctx, box, value, size=size, colour=colour, align=align, anchor=anchor, words=CELL, spacing=CELL_SPACING)


def _pill(ctx, box, value, size, fill, ink):
    """A capsule at `box` with `value` centred on it, the text kept off its rounded ends."""
    x, y, w, h = box
    radius = min(h / 2, 0.26)
    rounded(ctx, box, fill, radius=radius)
    inset = PILL_INSET
    text(ctx, (x + inset, y + 0.04, w - 2 * inset, h - 0.08), value, size=size, floor=min(size, 12), colour=ink,
         bold=True, align='center', anchor='middle', words=LABEL, spacing=LABEL_SPACING)


PILL_INSET = 0.17      # the pill text's distance from either rounded end
PILL_PAD = 0.08 + 0.1  # a pill's height over its text's


def _mark(ctx, fill):
    """The colour for a rule or swatch on `fill`: the accent where it shows there, else the fill's own accent ink."""
    if contrast_ratio(hex_of(ctx, 'accent'), hex_of(ctx, fill)) >= 2.2:
        return 'accent'
    return inks(fill)['accent']


def _shows(ctx, colour, ground='surface'):
    """Whether `colour` (role or hex) stands out as a shape on `ground`.

    A pale, saturated accent (a yellow) still shows on a light ground at a low ratio, but a dark accent on a
    dark ground (navy, plum) all but vanishes, so a dark ground asks for more.
    """
    ground = hex_of(ctx, ground)
    return contrast_ratio(hex_of(ctx, colour), ground) >= (2.2 if _luminance(ground) < 0.2 else 1.3)


def _lit(ctx):
    """The fill and inks for an accent shape on the surface (a disc, a pill, a tab): the accent where it shows,
    else the design's strongest fill."""
    return inks('accent') if _shows(ctx, 'accent') else inks(strong(ctx))


def _trace(ctx):
    """The colour for an accent rule or mark on the surface: the accent where it shows, else its readable ink."""
    return 'accent' if _shows(ctx, 'accent') else 'accent_text'


def _span(value, size, *, bold=True):
    """Inches `value` takes on one line at `size`, measured as kit measures text (bold allowance included)."""
    return _units(value) * 0.001 * size * WIDTH_SAFETY * (1.06 if bold else 1) / 72 if value else 0.0


def _word_size(ctx, section, width, size, floor=20):
    """The largest heading size up to `size` at which no single word of the heading is wider than `width`.

    kit.headline counts a word too long for its box as broken in two and keeps the size; in a narrow column
    a long Russian word ('Региональные' at 30 pt) would then split mid-word or run out of the box.
    """
    words = _clean(section.get('heading'), 14).split()
    while size > floor and any(_text_lines(word, size, Inches(width), bold=ctx.heading_bold) > 1 for word in words):
        size -= 2
    return size


def _top_centred(ctx, section, size=28):
    """A centred top that leaves the body room: eyebrow, a two-line heading, the rule. Returns where the body starts."""
    eyebrow(ctx, (LEFT, 0.62, WIDTH, 0.3), align='center')
    headline(ctx, section, (LEFT + 1.0, 0.9, WIDTH - 2.0, 0.98), size=size, lines=2, align='center')
    rule(ctx, (LEFT + WIDTH / 2 - 0.45, 1.97, 0.9, RULE))
    return 2.2


# ---------------------------------------------------------------- 1. vs centre


@variant('comparison', 'vs_centre', counts=(2, 6))
def vs_centre(ctx, section, lines):
    """Two tall facing panels, strong and card, with the criteria down the surface between them and a vs disc on top."""
    top = _top_centred(ctx, section)
    rows = entries('comparison', section)
    names = _names(section)
    n = max(1, len(rows))
    centre = 2.7
    panel = (WIDTH - centre) / 2
    pad = 0.36
    inner = panel - 2 * pad
    middle = centre - 0.3
    dark, light = inks(strong(ctx)), inks('card')
    room = FOOT - top
    name_size, name_h = _name_fit(ctx, names, inner, (22, 21, 20, 19, 18, 17, 16))
    above, below, foot = 0.26, 0.3, 0.14
    head = above + name_h + below
    budget = room - head - foot

    def tallest(sizes):
        return max(_cells(ctx, rows, inner, sizes[1]), _labels(ctx, rows, middle, sizes[0]))

    sizes = _choose(lambda s: n * (tallest(s) + 0.08) <= budget)
    need = tallest(sizes)
    pitch = min(budget / n, max(need + 0.3, 0.86))
    tall = head + n * pitch + foot
    y = _centred(top, room, tall, bias=0.4)
    for paint, x in ((dark, LEFT), (light, RIGHT - panel)):
        rect(ctx, (x, y, panel, tall), paint['fill'])
        _put_name(ctx, (x + pad, y + above, inner, name_h), names[0 if x == LEFT else 1], name_size, paint['ink'],
                  align='center')
        rect(ctx, (x + pad, y + above + name_h + 0.13, inner, 2 / 72), _mark(ctx, paint['fill']))
    # The vs disc between the names, tied to both panels by a rule. A navy or plum accent all but
    # vanishes on a dark ground, so the disc, its rules and the row ticks take a fill that shows there.
    disc = _lit(ctx)
    cx, cy = LEFT + WIDTH / 2, y + above + name_h / 2
    size = 0.84
    line(ctx, (LEFT + panel, cy), (cx - size / 2, cy), disc['fill'], 1.5)
    line(ctx, (cx + size / 2, cy), (RIGHT - panel, cy), disc['fill'], 1.5)
    oval(ctx, (cx - size / 2, cy - size / 2, size, size), disc['fill'])
    text(ctx, (cx - size * 0.35, cy - size * 0.35, size * 0.7, size * 0.7), vs(ctx), size=20, floor=12,
         colour=disc['ink'], bold=True, heading=True, align='center', anchor='middle')
    start = y + head
    criterion, cell = sizes
    inset = min(0.06, max(0.0, (pitch - need) / 2))
    for k, item in enumerate(rows):
        row = start + k * pitch
        if k:
            for paint, x in ((dark, LEFT), (light, RIGHT - panel)):
                rect(ctx, (x + pad, row - HAIR / 2, inner, HAIR), paint['muted'])
            rect(ctx, (cx - 0.2, row - 0.015, 0.4, 0.03), disc['fill'])
        y_box, h_box = row + inset, pitch - 2 * inset
        _put_cell(ctx, (LEFT + pad, y_box, inner, h_box), item.get('text'), cell, dark['ink'])
        _put_cell(ctx, (RIGHT - panel + pad, y_box, inner, h_box), item.get('value'), cell, light['ink'])
        text(ctx, (cx - middle / 2, y_box, middle, h_box), item.get('label'), size=criterion, colour='ink',
             bold=True, heading=True, align='center', anchor='middle', words=LABEL, spacing=LABEL_SPACING)


# ---------------------------------------------------------------- 2. split halves


@variant('comparison', 'split_halves', counts=(2, 4))
def split_halves(ctx, section, lines):
    """The body cut into two touching halves, strong and card; every cell under its criterion, small, in each half."""
    top = header_compact(ctx, section)
    rows = entries('comparison', section)
    names = _names(section)
    n = max(1, len(rows))
    half = WIDTH / 2
    pad = 0.45
    inner = half - 2 * pad
    room = FOOT - top
    dark, light = inks(strong(ctx)), inks('card')
    mark = 0.7                                   # the numeral before each name
    name_size, name_h = _name_fit(ctx, names, inner - mark, (24, 23, 22, 21, 20, 19, 18))
    above, below, foot, least = 0.28, 0.34, 0.22, 0.14
    head = above + name_h + below
    budget = room - head - foot

    def paragraphs(item, key, sizes, paint):
        label, cell = sizes
        return [_criterion(item, label, paint['accent'], heading=False, after=3),
                _cell(item.get(key), cell, paint['ink'])]

    def tallest(sizes):
        return max(_need(ctx, inner, paragraphs(item, key, sizes, paint))
                   for item in rows for key, paint in (('text', dark), ('value', light)))

    sizes = _choose(lambda s: n * tallest(s) + (n - 1) * least <= budget,
                    scales=((14, 16), (14, 15), (13, 15), (13, 14), (12, 14), (12, 13), (12, 12)))
    need = min(tallest(sizes), (budget - (n - 1) * least) / n)
    gap = min(0.46, max(least, (budget - n * need) / max(1, n - 1))) if n > 1 else 0
    used = n * need + (n - 1) * gap
    tall = min(room, max(3.3, head + used + foot))
    y = _centred(top, room, tall, bias=0.45)
    start = y + head + max(0.0, (tall - head - foot - used) * 0.4)
    for k, (paint, key) in enumerate(((dark, 'text'), (light, 'value'))):
        x = LEFT + k * half
        rect(ctx, (x, y, half, tall), paint['fill'])
        text(ctx, (x + pad, y + above, mark - 0.1, name_h), f'{k + 1:02d}', size=14, floor=12,
             colour=paint['muted'], bold=True, anchor='middle')
        _put_name(ctx, (x + pad + mark, y + above, inner - mark, name_h), names[k], name_size, paint['ink'])
        rect(ctx, (x + pad, y + above + name_h + 0.15, 0.55, RULE), _mark(ctx, paint['fill']))
        for row, item in enumerate(rows):
            at = start + row * (need + gap)
            if row:
                rect(ctx, (x + pad, at - gap / 2 - HAIR / 2, inner, HAIR), paint['muted'])
            block(ctx, (x + pad, at, inner, need), paragraphs(item, key, sizes, paint))


# ---------------------------------------------------------------- 3. clean table


@variant('comparison', 'clean_table', counts=(2, 6))
def clean_table(ctx, section, lines):
    """A ruled table beside the heading: names in the accent over a thick rule, hairlines between the rows."""
    side = 3.05
    x0 = LEFT + side + 0.4
    rows = entries('comparison', section)
    names = _names(section)
    n = max(1, len(rows))
    width = RIGHT - x0
    gap = 0.28
    label_w = 1.85
    cell_w = (width - label_w - 2 * gap) / 2
    a_x, b_x = x0 + label_w + gap, x0 + label_w + gap + cell_w + gap
    name_size, name_h = _name_fit(ctx, names, cell_w, (20, 19, 18, 17, 16, 15))
    first = 0.92
    thick = 0.08
    head = name_h + 0.1 + thick + 0.08
    budget = FOOT - 0.04 - first - head

    def tallest(sizes):
        return max(_cells(ctx, rows, cell_w, sizes[1]), _labels(ctx, rows, label_w, sizes[0], heading=False))

    sizes = _choose(lambda s: n * (tallest(s) + 0.14) <= budget)
    need = tallest(sizes)
    pitch = min(budget / n, max(need + 0.34, 0.8))
    pad = min(0.15, max(0.0, (pitch - need) / 2))
    criterion, cell = sizes
    # A short table sits a little above the middle, and the heading beside it starts level with its names.
    top = _centred(first, FOOT - 0.04 - first, head + n * pitch, bias=0.38)
    # The accent rules take the accent's readable ink where the accent would vanish (navy on a dark ground).
    mark = _trace(ctx)
    eyebrow(ctx, (LEFT, 0.62, side, 0.3))
    rule(ctx, (LEFT, top + 0.1, 0.9, RULE), colour=mark)
    headline(ctx, section, (LEFT, top + 0.33, side, min(3.4, FOOT - top - 0.45)),
             size=_word_size(ctx, section, side, 30), lines=5, anchor='top')
    for value, x in ((names[0], a_x), (names[1], b_x)):
        _put_name(ctx, (x, top, cell_w, name_h), value, name_size, 'accent_text', anchor='bottom')
    rect(ctx, (x0, top + name_h + 0.1, width, thick), mark)
    start = top + head
    for k, item in enumerate(rows):
        row = start + k * pitch
        if k:
            rect(ctx, (x0, row - HAIR / 2, width, HAIR), 'muted')
        y, h = row + pad, pitch - 2 * pad
        text(ctx, (x0, y, label_w, h), item.get('label'), size=criterion, colour='muted', bold=True, words=LABEL,
             spacing=LABEL_SPACING)
        _put_cell(ctx, (a_x, y, cell_w, h), item.get('text'), cell, 'ink', anchor='top')
        _put_cell(ctx, (b_x, y, cell_w, h), item.get('value'), cell, 'ink', anchor='top')
    rect(ctx, (x0, start + n * pitch - 0.01, width, 0.02), 'ink')


# ---------------------------------------------------------------- 4. criterion cards

PILL_SCALES = ((15, 16), (15, 15), (14, 15), (14, 14), (13, 14), (13, 13), (12, 13), (12, 12))
PILL_WIDTHS = (2.2, 2.5, 2.8, 3.1, 3.4)


def _one_line(ctx, rows, width, size):
    return all(_text_lines(_clean(item.get('label'), LABEL), size, Inches(width), bold=True) <= 1
               for item in rows if _clean(item.get('label')))


def _pill_layout(ctx, rows, cell_width, fits):
    """(sizes, pill width): the largest sizes at which `fits(sizes, pill, cell)` holds for some pill width.

    Of those widths, the narrowest that keeps every criterion on one line — at its size or up to 2 pt
    smaller — else the widest: a wider pill keeps a long criterion on one line and costs the cells beside
    it a little width.
    """
    for sizes in PILL_SCALES:
        held = [pill for pill in PILL_WIDTHS if fits(sizes, pill, cell_width(pill))]
        if not held:
            continue
        for label in range(sizes[0], max(12, sizes[0] - 2) - 1, -1):
            single = [pill for pill in held if _one_line(ctx, rows, pill - 2 * PILL_INSET, label)]
            if single:
                return (label, sizes[1]), single[0]
        return sizes, held[-1]
    return PILL_SCALES[-1], PILL_WIDTHS[-1]


@variant('comparison', 'criterion_cards', counts=(2, 5))
def criterion_cards(ctx, section, lines):
    """Two-tone row cards with a coloured edge, the names on folder tabs over the halves, the criteria on pills."""
    band = inks(strong(ctx))
    top = header_band(ctx, section, fill=band['fill'], height=1.3, size=28) - 0.08
    rows = entries('comparison', section)
    names = _names(section)
    n = max(1, len(rows))
    room = FOOT - top
    cx = LEFT + WIDTH / 2
    tab, pad, clear = 0.1, 0.32, 0.22
    left, soft = inks('card'), inks('accent_soft')
    # The pills and the cards' edges: the accent, or a fill that shows where it would not (navy on dark).
    lit = _lit(ctx)
    least = 0.08

    def cell_width(pill):
        return WIDTH / 2 - pill / 2 - clear - pad - tab

    name_size, name_h = _name_fit(ctx, names, cell_width(PILL_WIDTHS[-1]), (19, 18, 17, 16, 15))
    lift = 0.09                      # a name tab's padding above and below its name
    head = name_h + 2 * lift
    budget = room - head

    def tallest(sizes, pill, cell_w):
        return max(_cells(ctx, rows, cell_w, sizes[1]) + 0.08,
                   _labels(ctx, rows, pill - 2 * PILL_INSET, sizes[0], heading=False) + PILL_PAD + 0.06)

    sizes, pill_w = _pill_layout(ctx, rows, cell_width,
                                 lambda s, p, w: n * tallest(s, p, w) + (n - 1) * least <= budget)
    cell_w = cell_width(pill_w)
    need = tallest(sizes, pill_w, cell_w)
    gap = min(0.16, max(least, (budget - n * need) / max(1, n - 1)))
    card = min((budget - (n - 1) * gap) / n, max(need + 0.2, 0.8))
    used = head + n * card + (n - 1) * gap
    y = _centred(top, room, used, bias=0.35)
    criterion, cell = sizes
    a_x, b_x = LEFT + tab + pad, cx + pill_w / 2 + clear
    start = y + head
    # Each name on a folder tab in its half's own colour, standing on the first card: the tab is the key
    # to the halves below. The tab is as wide as its name; its cut corner stays clear of the text.
    cut = min(0.22, head * 0.5)
    for value, paint, x, edge in ((names[0], left, a_x, LEFT), (names[1], soft, b_x, b_x - 0.24)):
        value = _clean(value, NAME)
        if not value:
            continue
        width = min(cell_w, _span(value, name_size) + 0.06)
        right = min(RIGHT, x + width + 0.22 + cut)
        width = min(width, right - cut - 0.05 - x)
        polygon(ctx, tab_points((edge, y, right - edge, head), cut=cut, corner='top_right'), paint['fill'])
        if edge == LEFT:
            rect(ctx, (LEFT, y, tab, head), lit['fill'])
        _put_name(ctx, (x, y + lift, width, name_h), value, name_size, paint['ink'])
    pill_h = min(card - 0.12, _labels(ctx, rows, pill_w - 2 * PILL_INSET, criterion, heading=False) + PILL_PAD)
    inset = min(0.06, max(0.0, (card - need + 0.08) / 2))
    for k, item in enumerate(rows):
        row = start + k * (card + gap)
        rect(ctx, (LEFT, row, WIDTH / 2, card), 'card')
        rect(ctx, (cx, row, WIDTH / 2, card), 'accent_soft')
        rect(ctx, (LEFT, row, tab, card), lit['fill'])
        _put_cell(ctx, (a_x, row + inset, cell_w, card - 2 * inset), item.get('text'), cell, left['ink'])
        _put_cell(ctx, (b_x, row + inset, cell_w, card - 2 * inset), item.get('value'), cell, soft['ink'])
        _pill(ctx, (cx - pill_w / 2, row + (card - pill_h) / 2, pill_w, pill_h), item.get('label'), criterion,
              lit['fill'], lit['ink'])


# ---------------------------------------------------------------- 5. mirrored


@variant('comparison', 'mirrored', counts=(2, 5))
def mirrored(ctx, section, lines):
    """A mirror about a centre spine: the first column set right, the second left, each criterion a pill on it."""
    top = header_center(ctx, section) - 0.12
    rows = entries('comparison', section)
    names = _names(section)
    n = max(1, len(rows))
    room = FOOT - top
    cx = LEFT + WIDTH / 2
    clear = 0.3

    def cell_width(pill):
        return WIDTH / 2 - pill / 2 - clear

    pair = hues(ctx, 2)
    name_size, name_h = _name_fit(ctx, names, cell_width(PILL_WIDTHS[-1]),
                                  (28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18))
    bar = 0.07
    head = name_h + 0.1 + bar + 0.16
    budget = room - head

    def tallest(sizes, pill, cell_w):
        return max(_cells(ctx, rows, cell_w, sizes[1]),
                   _labels(ctx, rows, pill - 2 * PILL_INSET, sizes[0], heading=False) + PILL_PAD)

    sizes, pill_w = _pill_layout(ctx, rows, cell_width, lambda s, p, w: n * (tallest(s, p, w) + 0.08) <= budget)
    cell_w = cell_width(pill_w)
    a_x, b_x = LEFT, cx + pill_w / 2 + clear
    need = tallest(sizes, pill_w, cell_w)
    pitch = min(budget / n, max(need + 0.3, 0.8))
    used = head + n * pitch
    y = _centred(top, room, used, bias=0.35)
    criterion, cell = sizes
    long = 1.1
    for k, (value, x, align) in enumerate(((names[0], a_x, 'right'), (names[1], b_x, 'left'))):
        if not _clean(value):
            continue
        _put_name(ctx, (x, y, cell_w, name_h), value, name_size, pair[k]['text'], align=align, anchor='bottom')
        # A hue that vanishes on the ground (the navy accent on a dark deck) draws its bar in its readable tone.
        hue = pair[k]['fill'] if _shows(ctx, pair[k]['fill']) else pair[k]['text']
        rect(ctx, (x + cell_w - long if k == 0 else x, y + name_h + 0.1, long, bar), hue)
    # The spine: a diamond between the names' bars, then a line from pill to pill.
    mark = 0.3
    my = y + name_h + 0.1 + bar / 2
    polygon(ctx, diamond_points((cx - mark / 2, my - mark / 2, mark, mark)), _trace(ctx))
    start = y + head
    pill_h = min(pitch - 0.1, _labels(ctx, rows, pill_w - 2 * PILL_INSET, criterion, heading=False) + PILL_PAD)
    last = my + mark / 2
    inset = min(0.06, max(0.0, (pitch - need) / 2))
    for k, item in enumerate(rows):
        row = start + k * pitch
        py = row + (pitch - pill_h) / 2
        if py - last > 0.22:                     # too short a stub reads as a speck
            line(ctx, (cx, last + 0.05), (cx, py - 0.05), 'muted', 1.0)
        last = py + pill_h
        _put_cell(ctx, (a_x, row + inset, cell_w, pitch - 2 * inset), item.get('text'), cell, 'ink', align='right')
        _put_cell(ctx, (b_x, row + inset, cell_w, pitch - 2 * inset), item.get('value'), cell, 'ink')
        _pill(ctx, (cx - pill_w / 2, py, pill_w, pill_h), item.get('label'), criterion, 'accent_soft', 'soft_ink')
