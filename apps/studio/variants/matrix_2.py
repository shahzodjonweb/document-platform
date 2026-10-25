"""Matrix variants: the four quadrants set apart by shape rather than by the classic checker — tiles beside a title
column, outlines with corner tabs, numbered quads, coloured columns and a cross of arrows.
"""
import math

from pptx.util import Inches

from . import variant
from ..slide_layouts import _paragraph_height, _text_lines
from ..slides import _text_width
from .kit import (FOOT, LEFT, RIGHT, RULE, WIDTH, Z, block, clip, columns_of, disc, entries, eyebrow, figure,
                  header_band, header_compact, header_side, headline, hues, inks, inscribed, line, on, oval,
                  polygon, readable, rect, rounded, rule, split, strong, tab_points, text)

TOP_EDGE = 0.62
SHORT = 1.3           # outlined_cells: the least height a cell shrinks to round brief text
NUMERALS = ((60, 0.98), (46, 0.76), (32, 0.56))   # four_columns: a column's number (pt) and the height it takes
# The classic drawer's word limits: a quadrant's name, its sentence, an axis.
LABEL, BODY, AXIS = 6, 28, 5
AXIS_SIZE = 12
# The hub is narrow: a long one-word axis (Russian 'Внутренние') steps a little smaller to stay whole.
HUB_AXIS_SIZE = 10
# (name, sentence) sizes, largest first: a slide's quadrants all take the first pair every one of them holds.
LADDER = ((20, 15), (19, 15), (19, 14), (18, 14), (18, 13), (17, 13), (16, 12))


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
    return (total + 4) / 72 if total else 0.0


def _whole(ctx, width, paragraphs):
    """Whether every word of `paragraphs` keeps to one line of `width` (none broken across lines)."""
    for paragraph in paragraphs:
        if not paragraph:
            continue
        for word in _plain(paragraph.get('text'), paragraph.get('words')).split():
            if _text_lines(word, paragraph['size'], Inches(width), bold=_bold(ctx, paragraph)) > 1:
                return False
    return True


def _settle(ctx, items, make, width, room, ladder=LADDER):
    """The first sizes in `ladder` at which every item's paragraphs fit `width` x `room` (each may be a list)."""
    widths = list(width) if isinstance(width, (list, tuple)) else [width] * len(items)
    rooms = list(room) if isinstance(room, (list, tuple)) else [room] * len(items)
    for sizes in ladder:
        if all(_need(ctx, widths[k], make(k, item, *sizes)) <= rooms[k]
               and _whole(ctx, widths[k], make(k, item, *sizes)) for k, item in enumerate(items)):
            return sizes
    return ladder[-1]


def _word_size(ctx, value, width, size, floor=18):
    """The largest size up to `size` at which the heading's longest word keeps to one line of `width`."""
    words = _plain(value, 14).split() or ['']
    while size > floor and any(_text_lines(word, size, Inches(width), bold=ctx.heading_bold) > 1 for word in words):
        size -= 1
    return size


# ---------------------------------------------------------------- pieces


def _rows(ctx, cells, make, sizes, width, room):
    """Each 2x2 row's tallest block (inches, at most `room`), so both blocks of a row can start on one line."""
    needs = [min(room, _need(ctx, width, make(k, item, *sizes))) for k, item in enumerate(cells)]
    return [max(needs[k - k % 2:k - k % 2 + 2]) for k in range(len(cells))]


def _cells(section):
    return entries('matrix', section)[:4]


def _number(k):
    return f'{k + 1:02d}'


def _cell(item, label, body, *, ink, muted, align='left', gap=6):
    """A quadrant's paragraphs: its name and its sentence, at the classic word limits."""
    paragraphs = [dict(text=item['label'], words=LABEL, size=label, floor=min(label, 15), colour=ink, bold=True,
                       heading=True, after=gap, align=align, spacing=1.1)]
    if item.get('text'):
        paragraphs.append(dict(text=item['text'], words=BODY, size=body, floor=min(body, 12), colour=muted,
                               align=align, spacing=1.2))
    return paragraphs


def _axes(ctx, section):
    """The matrix's axis names, held to the classic five words each."""
    return [clip(ctx, axis, AXIS) for axis in columns_of(section)[:2] if _plain(axis)]


def _pill_size(value, room):
    """(width, height) of a pill holding `value`: one line if it fits in `room`, else two lines `room` wide."""
    one = _text_width(value, AXIS_SIZE) * 1.06 / 72 + 0.44
    return (one, 0.36) if one <= room else (room, 0.6)


def _pill(ctx, box, value, fill='accent_soft'):
    """An axis name on a soft pill (cut, and the slide marked, only past two lines)."""
    x, y, w, h = box
    rounded(ctx, box, fill, radius=min(h / 2, 0.18))
    text(ctx, (x + 0.16, y + 0.04, w - 0.32, h - 0.08), value, size=AXIS_SIZE, floor=AXIS_SIZE,
         colour=inks(fill)['ink'], bold=True, align='center', anchor='middle', spacing=1.05)


def _pills(ctx, axes, room):
    """The axes' pills, measured: [(value, width, height)] and their total width with gaps."""
    pills = [(axis, *_pill_size(axis, room)) for axis in axes]
    return pills, sum(p[1] for p in pills) + 0.12 * max(0, len(pills) - 1)


def _caption(ctx, box, axes, colour):
    """The axes on one line, '·' between them (as the classic drawer joins them), on the eyebrow's line at right."""
    text(ctx, box, '  ·  '.join(axes), size=AXIS_SIZE, floor=AXIS_SIZE, colour=colour, bold=True, align='right',
         anchor='top')


# ---------------------------------------------------------------- variants


@variant('matrix', 'side_grid', counts=(4, 4))
def side_grid(ctx, section, lines):
    """The heading in a column down the left over the axes as pills; the quadrants as four numbered tiles beside it,
    parted by two crossing accent hairlines.
    """
    side = 3.05
    x0 = header_side(ctx, section, width=side, size=_word_size(ctx, section['heading'], side, 30))
    axes = _axes(ctx, section)
    if axes:
        pills, _ = _pills(ctx, axes, side)
        y = FOOT - sum(h for _, _, h in pills) - 0.12 * (len(pills) - 1)
        for value, w, h in pills:
            _pill(ctx, (LEFT, y, w, h), value)
            y += h + 0.12
    cells = _cells(section)
    gap = 0.24
    w = (RIGHT - x0 - gap) / 2
    tall = (FOOT - TOP_EDGE - gap) / 2
    pad, num = 0.28, 0.52
    inner, room = w - 2 * pad, tall - 2 * pad - num

    def make(k, item, label, body):
        return _cell(item, label, body, ink='card_ink', muted='card_muted')
    sizes = _settle(ctx, cells, make, inner, room)
    rows = _rows(ctx, cells, make, sizes, inner, room)
    for k, item in enumerate(cells):
        row, column = divmod(k, 2)
        x, y = x0 + column * (w + gap), TOP_EDGE + row * (tall + gap)
        rect(ctx, (x, y, w, tall), 'card')
        rect(ctx, (x + pad, y + pad, 0.5, RULE), 'accent')
        figure(ctx, (x + pad, y + pad + 0.08, 1.4, 0.42), _number(k), size=22, colour='card_accent', anchor='top')
        block(ctx, (x + pad, y + tall - pad - rows[k], inner, rows[k]), make(k, item, *sizes))
    # The matrix's two axes as hairlines down the gaps between the tiles, a disc where they cross.
    cx, cy = x0 + w + gap / 2, TOP_EDGE + tall + gap / 2
    axis = readable(ctx, 'accent', 'surface', 2.2)
    line(ctx, (cx, TOP_EDGE + 0.2), (cx, FOOT - 0.2), axis, 1.25)
    line(ctx, (x0 + 0.2, cy), (RIGHT - 0.2, cy), axis, 1.25)
    oval(ctx, disc(cx, cy, 0.2), axis)


@variant('matrix', 'outlined_cells', counts=(4, 4))
def outlined_cells(ctx, section, lines):
    """Four quadrants drawn as accent outlines as tall as their text, each with a solid tab at its outer corner holding
    its number; the text beside the tab, mirrored round the centre.
    """
    # The axes as pills at the top right, on the eyebrow's line; a pill of two lines takes room from the heading.
    axes = _axes(ctx, section)
    pills, span = _pills(ctx, axes, 2.8) if axes else ([], 0)
    tall_pill = any(h > 0.4 for _, _, h in pills)
    eyebrow(ctx)
    headline(ctx, section, (LEFT, 1.0, WIDTH - (span + 0.4 if tall_pill else 0), 1.25), size=32, lines=2)
    rule(ctx)
    top = 2.75
    x = RIGHT - span
    for value, w, h in pills:
        _pill(ctx, (x, TOP_EDGE, w, h), value)
        x += w + 0.12
    cells = _cells(section)
    gap, tab = 0.3, 0.66
    w = (WIDTH - gap) / 2
    space = FOOT - top
    tall = (space - gap) / 2
    pad, beside = 0.2, 0.26
    inner, room = w - tab - beside - 0.3, tall - 2 * pad
    # The outline and its tabs in one colour: the accent, deepened where it would not read on the surface.
    outline = readable(ctx, 'accent', 'surface', 2.2)

    def make(k, item, label, body):
        return _cell(item, label, body, ink='ink', muted='muted')
    sizes = _settle(ctx, cells, make, inner, room)
    rows = _rows(ctx, cells, make, sizes, inner, room)
    # Cells only as tall as their tallest text needs (never squatter than SHORT), the grid set a little above the
    # middle of its room, so brief quadrants are not four empty frames with their text pushed out to the corners.
    tall = min(tall, max(SHORT, max(rows) + 2 * pad))
    top += (space - 2 * tall - gap) * 0.4
    cuts = ('bottom_right', 'bottom_left', 'top_right', 'top_left')
    for k, item in enumerate(cells):
        row, column = divmod(k, 2)
        x, y = LEFT + column * (w + gap), top + row * (tall + gap)
        rect(ctx, (x, y, w, tall), None, line=outline, line_width=1.5)
        tx = x if column == 0 else x + w - tab
        ty = y if row == 0 else y + tall - tab
        polygon(ctx, tab_points((tx, ty, tab, tab), cut=0.16, corner=cuts[k]), outline)
        text(ctx, inscribed((tx, ty, tab, tab), 0.68), _number(k), size=18, colour=on(outline), bold=True,
             heading=True, align='center', anchor='middle')
        bx = x + tab + beside if column == 0 else x + 0.3
        by = y + pad - 0.06 if row == 0 else y + tall - pad + 0.06 - rows[k]
        block(ctx, (bx, by, inner, rows[k]), make(k, item, *sizes))


@variant('matrix', 'numbered_quads', counts=(4, 4))
def numbered_quads(ctx, section, lines):
    """Four quads numbered 01 to 04 in large numerals beside a short rule and their text, the first on a strong panel
    and the rest on cards.
    """
    top = header_compact(ctx, section)
    axes = _axes(ctx, section)
    if axes:
        _caption(ctx, (RIGHT - 6.6, TOP_EDGE, 6.6, 0.3), axes, 'accent_text')
    cells = _cells(section)
    gap = 0.2
    w = (WIDTH - gap) / 2
    tall = (FOOT - top - gap) / 2
    pad, numeral, sep = 0.36, 1.08, 0.36
    inner, room = w - 2 * pad - numeral - sep, tall - 0.44
    panel = strong(ctx)
    fills = [panel, 'card', 'card', 'card']

    def make(k, item, label, body):
        colours = inks(fills[k])
        return _cell(item, label, body, ink=colours['ink'], muted=colours['muted'])
    sizes = _settle(ctx, cells, make, inner, room)
    needs = [_need(ctx, inner, make(k, item, *sizes)) for k, item in enumerate(cells)]
    for k, (item, need) in enumerate(zip(cells, needs)):
        row, column = divmod(k, 2)
        x, y = LEFT + column * (w + gap), top + row * (tall + gap)
        fill = fills[k]
        colours = inks(fill)
        rect(ctx, (x, y, w, tall), fill)
        figure(ctx, (x + pad, y + 0.2, numeral, tall - 0.4), _number(k), size=54,
               colour=colours['ink'] if k == 0 else 'card_accent', anchor='middle')
        mark = max(0.9, min(need, room))
        rect(ctx, (x + pad + numeral + sep / 2 - 0.02, y + (tall - mark) / 2, 0.04, mark),
             readable(ctx, 'accent', fill, 2.2))
        block(ctx, (x + pad + numeral + sep, y + 0.22, inner, room), make(k, item, *sizes), anchor='middle')


@variant('matrix', 'four_columns', counts=(4, 4))
def four_columns(ctx, section, lines):
    """The heading on a soft band; the quadrants as four tall columns, each with a coloured head holding its name and a
    pointer down to its text on a card, its number set large at the foot.
    """
    band = 'accent_soft'
    top = header_band(ctx, section, fill=band, height=1.45, size=28)
    axes = _axes(ctx, section)
    if axes:
        _caption(ctx, (RIGHT - 0.4 - 6.4, 0.78, 6.4, 0.3), axes, inks(band)['muted'])
    cells = _cells(section)
    paints = hues(ctx, 4)
    gap = 0.18
    spans = split(LEFT, WIDTH, 4, gap)
    width = spans[0][1]
    pad = 0.22
    inner = width - 2 * pad
    pointer, numeral, foot = 0.16, 0.56, 0.16

    def head(k, item, label):
        return [dict(text=item['label'], words=LABEL, size=label, floor=min(label, 15), colour=paints[k]['ink'],
                     bold=True, heading=True, align='left', spacing=1.1)]
    label = next((size for size in (20, 19, 18, 17, 16, 15)
                  if all(_need(ctx, inner, head(k, item, size)) <= 1.0 and _whole(ctx, inner, head(k, item, size))
                         for k, item in enumerate(cells))), 15)
    head_h = max(0.9, max(_need(ctx, inner, head(k, item, label)) for k, item in enumerate(cells)) + 0.36)
    body_top = top + head_h + pointer + 0.12
    room = FOOT - foot - numeral - body_top

    def make(k, item, label_size, body):
        if not item.get('text'):
            return []
        return [dict(text=item['text'], words=BODY, size=body, floor=12, colour='card_muted', spacing=1.2)]
    body = next((size for size in (15, 14, 13, 12)
                 if all(_need(ctx, inner, make(k, item, 0, size)) <= room
                        and _whole(ctx, inner, make(k, item, 0, size)) for k, item in enumerate(cells))), 12)
    # The numbers grow into whatever the texts leave free, so brief columns are anchored by a large figure at
    # their foot rather than standing two-thirds empty; at the guide's longest they keep to 32 pt.
    tallest = max(_need(ctx, inner, make(k, item, 0, body)) for k, item in enumerate(cells))
    size, numeral = next(((size, tall) for size, tall in NUMERALS if tall - NUMERALS[-1][1] + 0.3 <= room - tallest),
                         NUMERALS[-1])
    room = FOOT - foot - numeral - body_top
    for k, (item, (x, _)) in enumerate(zip(cells, spans)):
        paint = paints[k]
        rect(ctx, (x, top + head_h, width, FOOT - top - head_h), 'card')
        rect(ctx, (x, top, width, head_h), paint['fill'])
        polygon(ctx, [(x + pad, top + head_h - 0.01), (x + pad + 2 * pointer, top + head_h - 0.01),
                      (x + pad + pointer, top + head_h + pointer)], paint['fill'])
        block(ctx, (x + pad, top + 0.18, inner, head_h - 0.36), head(k, item, label), anchor='middle')
        if item.get('text'):
            block(ctx, (x + pad, body_top, inner, room), make(k, item, 0, body))
        figure(ctx, (x + pad, FOOT - foot - numeral, inner, numeral), _number(k), size=size,
               colour=readable(ctx, paint['fill'], 'card'), anchor='bottom')


@variant('matrix', 'chevron_cross', counts=(4, 4))
def chevron_cross(ctx, section, lines):
    """Four chevrons in four colours spreading from a soft hub out to the corners, each holding its quadrant's initial;
    the names and texts in the corners around them.
    """
    eyebrow(ctx, (LEFT, TOP_EDGE, WIDTH, 0.3), align='center')
    headline(ctx, section, (LEFT + 1.2, 0.9, WIDTH - 2.4, 1.0), size=28, lines=2, align='center')
    rule(ctx, (LEFT + WIDTH / 2 - 0.45, 2.02, 0.9, RULE))
    top = 2.25
    cells = _cells(section)
    paints = hues(ctx, 4)
    cx, cy = LEFT + WIDTH / 2, top + (FOOT - top) / 2
    # Each chevron points out to its corner: a square tip `arm` wide whose sides run in at 45 degrees and end
    # on an arc round the hub, `half_gap` off each axis.
    arm, half_gap = 0.98, 0.09
    notch = arm + half_gap
    tip = notch + arm + 0.03
    radius = math.hypot(half_gap, notch)
    start, end = math.atan2(notch, half_gap), math.atan2(half_gap, notch)
    angles = [start + (end - start) * step / 16 for step in range(17)]
    arc = [(radius * math.cos(angle), radius * math.sin(angle)) for angle in angles]
    signs = ((-1, -1), (1, -1), (-1, 1), (1, 1))
    for k, (item, (su, sv)) in enumerate(zip(cells, signs)):
        local = [(tip, tip), (tip - arm, tip)] + arc + [(tip, tip - arm)]
        polygon(ctx, [(cx + su * u, cy + sv * v) for u, v in local], paints[k]['fill'])
        mid = tip - arm / 2
        box = (cx + su * mid - arm / 2, cy + sv * mid - arm / 2, arm, arm)
        text(ctx, inscribed(box, 0.78), _initial(item, k), size=36, colour=paints[k]['ink'], bold=True,
             heading=True, align='center', anchor='middle')
    # The hub the chevrons spread from: a soft disc naming the axes when there are any, and otherwise holding
    # a small 2x2 in the quadrants' colours.
    hub = disc(cx, cy, 2 * (radius - 0.13))
    oval(ctx, hub, 'accent_soft')
    axes = _axes(ctx, section)
    if len(axes) == 1:
        text(ctx, inscribed(hub, 0.7), axes[0], size=13, floor=HUB_AXIS_SIZE, colour='soft_ink', bold=True,
             heading=True, align='center', anchor='middle', spacing=1.05)
    elif axes:
        # One axis over a short accent rule, the other under it; each may take three lines of the hub.
        # A line set at the foot of its box sits nearer the rule than one set at the top of its box, so the rule
        # is a little below the middle of the gap between the two boxes, to look centred between the words.
        ix, iy, iw, ih = inscribed(hub, 0.7)
        above, below = 0.09, 0.07
        text(ctx, (ix, iy, iw, ih / 2 - above), axes[0], size=13, floor=HUB_AXIS_SIZE, colour='soft_ink',
             bold=True, heading=True, align='center', anchor='bottom', spacing=1.05)
        rect(ctx, (cx - 0.22, cy + 0.02 - RULE / 2, 0.44, RULE), readable(ctx, 'accent', 'accent_soft', 2.2))
        text(ctx, (ix, cy + below, iw, ih / 2 - below), axes[1], size=13, floor=HUB_AXIS_SIZE, colour='soft_ink',
             bold=True, heading=True, align='center', anchor='top', spacing=1.05)
    else:
        square, between = 0.3, 0.06
        for k, (su, sv) in enumerate(signs):
            rect(ctx, (cx + (between / 2 if su > 0 else -between / 2 - square),
                       cy + (between / 2 if sv > 0 else -between / 2 - square), square, square), paints[k]['fill'])
    side = cx - tip - 0.4 - LEFT
    room = tip - 0.16

    def make(k, item, label, body):
        # Left of the cross the text is set flush right, towards it.
        return _cell(item, label, body, ink=paints[k]['text'], muted='muted',
                     align='right' if k % 2 == 0 else 'left')
    sizes = _settle(ctx, cells, make, side, room)
    rows = _rows(ctx, cells, make, sizes, side, room)
    for k, item in enumerate(cells):
        row, column = divmod(k, 2)
        x = LEFT if column == 0 else RIGHT - side
        y = cy - tip if row == 0 else cy + tip - rows[k]
        block(ctx, (x, y, side, rows[k]), make(k, item, *sizes))


def _initial(item, k):
    """The first letter of a quadrant's name (SWOT's S, W, O, T), or its number."""
    return next((ch.upper() for ch in str(item.get('label') or '') if ch.isalnum()), str(k + 1))
