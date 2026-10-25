"""Table variants: the grid drawn in shapes — open rules, row cards, a dark first column, column cards, a ledger."""
import math
from types import SimpleNamespace

from pptx.util import Inches

from . import variant
from ..slide_layouts import _text_lines, _units
from ..slides import WIDTH_SAFETY
from .kit import (FOOT, LEFT, RIGHT, WIDTH, columns_of, eyebrow, header, header_band, header_center, header_compact,
                  header_number, header_side, headline, hues, inks, items_of, line, polygon, rect, rounded, strong,
                  text)

HEAD, CELL = 5, 12          # the classic drawer's word limits: a column's name, a cell
BASE = FOOT - 0.1           # where a table ends at the lowest
SLACK = 0.08                # what a cell's text box keeps over its text's measured height
# (column name, cell) sizes, largest first: a slide's cells all take the first pair that holds the whole table.
LADDER = ((17, 16), (16, 15), (15, 14), (14, 13), (13, 12), (12, 12))
CAPS = tuple((13, size) for size in (16, 15, 14, 13, 12))   # names set as small capitals over the rows


# ---------------------------------------------------------------- content


def _grid(section, lines=None):
    """Whether the slide is a table this module draws: two or three columns and some rows."""
    return 2 <= len(columns_of(section)[:3]) and bool(items_of(section))


def _content(section):
    """(column names, rows of cells) as the classic drawer reads them."""
    names = [' '.join(str(name).split()) for name in columns_of(section)[:3]]
    rows = []
    for item in items_of(section):
        values = [item.get('label', ''), item.get('text', ''), item.get('value', '')]
        if section.get('layout') == 'chart' and len(names) == 2:
            # A chart drawn as a table: its figure, then any context.
            values = [values[0], ' — '.join(part for part in (values[2], values[1]) if part)]
        rows.append([' '.join(str(value or '').split()) for value in values[:len(names)]])
    return names, rows


# ---------------------------------------------------------------- measuring


def _clip(value, words):
    return ' '.join(str(value or '').split()[:words])


def _bold(ctx, bold, heading):
    return bool(bold) or bool(heading and ctx.heading_bold)


def _span(ctx, value, size, bold=False, heading=False):
    """Inches `value` takes set on one line."""
    if not value:
        return 0.0
    factor = 1.06 if _bold(ctx, bold, heading) else 1.0
    return _units(value) * size / 1000 * WIDTH_SAFETY * factor / 72 + 0.03


def _word(ctx, value, size, bold=False, heading=False):
    """Inches the longest word of `value` takes."""
    return max((_span(ctx, word, size, bold, heading) for word in str(value or '').split()), default=0.0)


def _tall(ctx, value, width, size, bold=False, heading=False):
    """Inches `value` takes wrapped in `width`, at the leading kit.text sets it with."""
    if not value:
        return 0.0
    return _text_lines(value, size, Inches(max(0.1, width)), bold=_bold(ctx, bold, heading)) * size * 1.15 / 72


def _widths(ctx, columns, room, inset, lead=0.0, least=0.2, steps=80):
    """Column widths summing to `room` that set the table as short as it can be.

    `columns` is, per column, its texts as (text, size, bold, heading), its
    name first. A column is never narrower than its longest word nor than
    `least` of the room. The start is how a browser shares a table out: every
    column its longest text on one line and the rest evenly, or, when that is
    too wide, its least and a share of the rest in proportion to what more it
    could use. Then widths in steps of the room are tried for the fewest
    lines down the table, the start winning ties and the nearest to it after
    that, so a column that nearly fits on one line is given it rather than
    every column wrapping a word. `lead` is room the first column's text
    starts after.
    """
    n = len(columns)
    extra = [2 * inset + (lead if k == 0 else 0) for k in range(n)]
    floor = [max(max(_word(ctx, *cell) for cell in column) + extra[k], room * least)
             for k, column in enumerate(columns)]
    most = [max(max(_span(ctx, *cell) for cell in column) + extra[k], floor[k]) for k, column in enumerate(columns)]
    if sum(most) <= room:
        spare = (room - sum(most)) / n
        return [value + spare for value in most]
    if sum(floor) >= room:
        return [value * room / sum(floor) for value in floor]
    share = (room - sum(floor)) / (sum(most) - sum(floor))
    start = [floor[k] + (most[k] - floor[k]) * share for k in range(n)]
    cache = {}

    def column_heights(k, width):
        key = (k, round(width, 3))
        if key not in cache:
            cache[key] = [_tall(ctx, value, width - extra[k], size, bold, heading) * 72
                          for value, size, bold, heading in columns[k]]
        return cache[key]

    def tall(widths):
        heights = [column_heights(k, width) for k, width in enumerate(widths)]
        return round(sum(max(column[r] for column in heights) for r in range(len(heights[0]))), 1)

    unit = room / steps
    candidates = [start]
    first = [int(-(-floor[k] // unit)) for k in range(n)]
    if n == 2:
        candidates += [[a * unit, room - a * unit] for a in range(first[0], steps)
                       if room - a * unit >= floor[1] - 1e-9]
    elif n == 3:
        candidates += [[a * unit, b * unit, room - (a + b) * unit] for a in range(first[0], steps)
                       for b in range(first[1], steps - a) if room - (a + b) * unit >= floor[2] - 1e-9]
    return min(candidates, key=lambda widths: (tall(widths), sum(abs(w - s) for w, s in zip(widths, start))))


def _plan(ctx, names, rows, *, width, room, gap=0.0, inset=0.0, lead=0.0, pad=0.1, head_pad=None, head_min=0.5,
          row_min=0.52, row_max=0.85, upper=False, head_heading=True, first_heading=False, ladder=LADDER,
          head_inset=None, bolds=None, mark=True):
    """The sizes, column widths and row heights of a table `width` wide in `room` inches of height.

    Every cell of a slide takes one size, the largest in `ladder` at which the
    whole table fits; rows are as tall as the tallest, grown toward `row_max`
    when there is room, so a short table is not a cramped one. `plan.loose`
    says the rows kept their least height; a table that does not fit even at
    the ladder's foot marks the slide shortened, so the variant is passed over
    rather than run the table into the footer.
    """
    n = len(names)
    bolds = list(bolds) if bolds else [k == 0 for k in range(n)]
    head_pad = pad if head_pad is None else head_pad
    head_inset = inset if head_inset is None else head_inset
    shown = [_clip(name, HEAD).upper() if upper else _clip(name, HEAD) for name in names]
    cells = [[_clip(value, CELL) for value in row] for row in rows]
    top_head, top_cell = ladder[0]
    columns = [[(shown[k], top_head, True, head_heading)]
               + [(row[k], top_cell, bolds[k], k == 0 and first_heading) for row in cells] for k in range(n)]
    widths = _widths(ctx, columns, width - gap * (n - 1), max(inset, head_inset), lead)
    room_x = [widths[k] - 2 * inset - (lead if k == 0 else 0) for k in range(n)]
    head_x = [widths[k] - 2 * head_inset - (lead if k == 0 else 0) for k in range(n)]
    plan = None
    for head, size in ladder:
        head_need = max(_tall(ctx, shown[k], head_x[k], head, True, head_heading) for k in range(n)) + SLACK
        needs = [max(_tall(ctx, row[k], room_x[k], size, bolds[k], k == 0 and first_heading) for k in range(n)) + SLACK
                 for row in cells]
        fitted = False
        # Rows at their least height first; then only as tall as their text and padding, before the type shrinks.
        for least, padding in ((row_min, pad), (0.0, pad), (0.0, min(pad, 0.06))):
            plan = SimpleNamespace(head=head, size=size, widths=widths, pad=padding, loose=bool(least),
                                   head_h=max(head_min if least else 0.0, head_need + 2 * head_pad),
                                   heights=[max(least, need + 2 * padding) for need in needs])
            if plan.head_h + sum(plan.heights) <= room + 1e-6:
                fitted = True
                break
        if fitted:
            break
    plan.fits = fitted
    if mark and not fitted:
        # Even the ladder's foot runs past the room: this table is not this variant's to draw.
        ctx.shortened = True
    count = max(1, len(rows))
    even = max(max(plan.heights, default=row_min), min(row_max, (room - plan.head_h) / count))
    if plan.head_h + even * count <= room + 1e-6:
        plan.heights = [even] * len(rows)
    plan.total = plan.head_h + sum(plan.heights)
    plan.xs = []
    x = 0.0
    for value in widths:
        plan.xs.append(x)
        x += value + gap
    plan.first_heading, plan.head_heading, plan.upper, plan.bolds = first_heading, head_heading, upper, bolds
    plan.wraps = any(_text_lines(row[k], plan.size, Inches(max(0.1, room_x[k])),
                                 bold=_bold(ctx, bolds[k], k == 0 and first_heading)) > 1
                     for row in cells for k in range(n) if row[k])
    return plan


def _start(top, bottom, tall, bias=0.42):
    """Where a block `tall` inches starts between `top` and `bottom`: a little above the middle of what is left."""
    return top + max(0.0, (bottom - top - tall) * bias)


def _cell(ctx, box, value, *, size, colour, bold=False, heading=False, align='left', anchor='middle', words=CELL,
          upper=False):
    x, y, w, h = box
    text(ctx, (x, y, max(0.1, w), max(0.1, h)), value, size=size, colour=colour, floor=min(12, size), bold=bold,
         heading=heading, align=align, anchor=anchor, words=words, upper=upper)


def _names(ctx, plan, names, x0, y, *, colours, inset=0.0, lead=0.0, align='left', anchor='middle', pad=0.1,
           aligns=None):
    """The column names along the header row at (`x0`, `y`)."""
    for k, name in enumerate(names):
        x = x0 + plan.xs[k] + inset + (lead if k == 0 else 0)
        w = plan.widths[k] - 2 * inset - (lead if k == 0 else 0)
        colour = colours[k] if isinstance(colours, (list, tuple)) else colours
        _cell(ctx, (x, y + pad, w, plan.head_h - 2 * pad), name, size=plan.head, colour=colour, bold=True,
              heading=plan.head_heading, align=(aligns[k] if aligns else align), anchor=anchor, words=HEAD,
              upper=plan.upper)


def _row(ctx, plan, row, x0, y, h, *, colours, inset=0.0, lead=0.0, align='left', aligns=None):
    """One row's cells at (`x0`, `y`), `h` tall, bold where the plan says (the first column, by default)."""
    for k, value in enumerate(row):
        x = x0 + plan.xs[k] + inset + (lead if k == 0 else 0)
        w = plan.widths[k] - 2 * inset - (lead if k == 0 else 0)
        colour = colours[k] if isinstance(colours, (list, tuple)) else colours
        bold = plan.bolds[k]
        _cell(ctx, (x, y + plan.pad, w, h - 2 * plan.pad), value, size=plan.size, colour=colour, bold=bold,
              heading=k == 0 and plan.first_heading, align=(aligns[k] if aligns else align))


# ---------------------------------------------------------------- clean lines


@variant('table', 'clean_lines', counts=(2, 6), accepts=_grid)
def clean_lines(ctx, section, lines):
    """An open table on the slide's ground under a centred heading: the column names in the accent over a thick
    accent rule, a hairline under every row and the first column bold."""
    top = header_center(ctx, section)
    names, rows = _content(section)
    bar, gap = 0.06, 0.45
    plan = _plan(ctx, names, rows, width=WIDTH, room=BASE - top - bar, gap=gap, pad=0.1, head_pad=0.08,
                 head_min=0.5, row_min=0.55, row_max=0.82)
    y = _start(top, BASE, plan.total + bar)
    _names(ctx, plan, names, LEFT, y, colours='accent_text', anchor='bottom', pad=0.08)
    y += plan.head_h
    rect(ctx, (LEFT, y, WIDTH, bar), 'accent')
    y += bar
    for r, row in enumerate(rows):
        h = plan.heights[r]
        _row(ctx, plan, row, LEFT, y, h, colours='ink')
        y += h
        line(ctx, (LEFT, y), (RIGHT, y), 'muted', 0.75)


# ---------------------------------------------------------------- row cards


def _tab(x, y, h, width, radius, steps=8):
    """The left `width` of a card rounded by `radius` at (`x`, `y`), `h` tall: its corners' arcs outside, straight
    inside, so the tab is the card's own edge in another colour."""
    width = min(width, radius)
    reach = math.acos(1 - width / radius)
    top, foot = y + radius, y + h - radius
    arc = [reach * step / steps for step in range(steps + 1)]
    return ([(x + radius - radius * math.cos(angle), top - radius * math.sin(angle)) for angle in reversed(arc)]
            + [(x + radius - radius * math.cos(angle), foot + radius * math.sin(angle)) for angle in arc])


@variant('table', 'row_cards', counts=(2, 6), accepts=_grid)
def row_cards(ctx, section, lines):
    """Each row a rounded card with an accent tab along its left edge and its cells laid out across it; the column
    names in small capitals above the cards."""
    top = header_compact(ctx, section) + 0.05
    names, rows = _content(section)
    space, tab, inset, gap = 0.14, 0.09, 0.32, 0.4
    plan = _plan(ctx, names, rows, width=WIDTH - tab - 2 * inset, room=BASE - top - space * (len(rows) - 1),
                 gap=gap, pad=0.13, head_pad=0.05, head_min=0.42, row_min=0.62, row_max=0.85, upper=True,
                 head_heading=False, first_heading=True, ladder=CAPS)
    total = plan.total + space * (len(rows) - 1)
    y = _start(top, BASE, total, 0.4)
    x0 = LEFT + tab + inset
    _names(ctx, plan, names, x0, y, colours='accent_text', anchor='bottom', pad=0.05)
    y += plan.head_h
    for r, row in enumerate(rows):
        h = plan.heights[r]
        rounded(ctx, (LEFT, y, WIDTH, h), 'card', radius=0.12)
        polygon(ctx, _tab(LEFT, y, h, tab, 0.12), 'accent')
        _row(ctx, plan, row, x0, y, h, colours='card_ink')
        y += h + space


# ---------------------------------------------------------------- dark first column


@variant('table', 'dark_first_column', counts=(2, 6), accepts=_grid)
def dark_first_column(ctx, section, lines):
    """The first column one strong panel the height of the table, its cells in the panel's ink; the other cells in
    bands that turn from card to the slide's ground row by row, under the column names in the accent."""
    top = header(ctx, section)
    names, rows = _content(section)
    panel = inks(strong(ctx))
    inset, bar = 0.28, 0.05
    plan = _plan(ctx, names, rows, width=WIDTH, room=BASE - top, inset=inset, pad=0.1, head_pad=0.1, head_min=0.58,
                 row_min=0.56, row_max=0.82)
    y = _start(top, BASE, plan.total, 0.35)
    first = plan.widths[0]
    rect(ctx, (LEFT, y, first, plan.total), panel['fill'])
    _names(ctx, plan, names, LEFT, y, colours=[panel['muted']] + ['accent_text'] * (len(names) - 1), inset=inset,
           anchor='middle')
    # One header rule across: the panel's own under its name, the accent's under the rest.
    rect(ctx, (LEFT + inset, y + plan.head_h - bar, first - 2 * inset, bar), panel['muted'])
    rect(ctx, (LEFT + first, y + plan.head_h - bar, WIDTH - first, bar), 'accent')
    y += plan.head_h
    for r, row in enumerate(rows):
        h = plan.heights[r]
        band = 'card' if r % 2 == 0 else 'surface'
        if band == 'card':
            rect(ctx, (LEFT + first, y, WIDTH - first, h), 'card')
        if r:
            line(ctx, (LEFT + inset, y), (LEFT + first - inset, y), panel['muted'], 0.75)
        ink = inks(band)['ink']
        _row(ctx, plan, row, LEFT, y, h, colours=[panel['ink']] + [ink] * (len(row) - 1), inset=inset)
        y += h
    # The cells' side closes level with the panel's foot.
    line(ctx, (LEFT + first, y), (RIGHT, y), 'muted', 0.75)


# ---------------------------------------------------------------- band header


@variant('table', 'band_header', counts=(2, 6), accepts=_grid)
def band_header(ctx, section, lines):
    """The heading on a strong band across the top; under it each column name on its own tinted cell, and a tinted
    track of the same width under every cell of its column."""
    fill = strong(ctx)
    top = header_band(ctx, section, fill=fill, height=1.5, size=30)
    names, rows = _content(section)
    gap, inset, track = 0.16, 0.2, 0.035
    plan = _plan(ctx, names, rows, width=WIDTH, room=BASE - top, gap=gap, inset=inset, pad=0.1, head_pad=0.1,
                 head_min=0.58, row_min=0.56, row_max=0.82)
    y = _start(top, BASE, plan.total, 0.3)
    for k in range(len(names)):
        rect(ctx, (LEFT + plan.xs[k], y, plan.widths[k], plan.head_h), 'accent_soft')
    _names(ctx, plan, names, LEFT, y, colours='soft_ink', inset=inset)
    y += plan.head_h
    for r, row in enumerate(rows):
        h = plan.heights[r]
        _row(ctx, plan, row, LEFT, y, h, colours='ink', inset=inset)
        y += h
        for k in range(len(names)):
            rect(ctx, (LEFT + plan.xs[k], y - track, plan.widths[k], track), 'accent_soft')


# ---------------------------------------------------------------- side title


@variant('table', 'side_title', counts=(2, 6), accepts=_grid)
def side_title(ctx, section, lines):
    """The heading in a column down the left; the table beside it, its names in the accent's ink on an accent band,
    its first column in the accent and a hairline under every row."""
    x0 = header_side(ctx, section, width=3.5, size=30, lines=6)
    names, rows = _content(section)
    width, inset = RIGHT - x0, 0.22
    options = dict(width=width, inset=inset, pad=0.1, head_pad=0.1, head_min=0.6, row_min=0.56, row_max=0.85)
    # The table's top level with the heading's; one that would need tighter rows or smaller type there starts
    # level with the eyebrow instead, the top of the frame.
    y, plan = 0.62, _plan(ctx, names, rows, room=BASE - 0.62, **options)
    level = _plan(ctx, names, rows, room=BASE - 1.25, mark=False, **options)
    if level.fits and level.loose and (level.head, level.size) == (plan.head, plan.size):
        y, plan = 1.25, level
    line(ctx, (x0 - 0.26, 0.62), (x0 - 0.26, FOOT - 0.05), 'muted', 0.75)
    rect(ctx, (x0, y, width, plan.head_h), 'accent')
    _names(ctx, plan, names, x0, y, colours='on_accent', inset=inset)
    y += plan.head_h
    for r, row in enumerate(rows):
        h = plan.heights[r]
        _row(ctx, plan, row, x0, y, h, colours=['accent_text'] + ['ink'] * (len(row) - 1), inset=inset)
        y += h
        line(ctx, (x0, y), (RIGHT, y), 'muted', 0.75)


# ---------------------------------------------------------------- column cards


@variant('table', 'column_cards', counts=(2, 6), accepts=_grid)
def column_cards(ctx, section, lines):
    """Each column a tall card under a cap of its own colour that holds its name; its cells down the card, lined up
    with the other cards' row by row, beside the slide's number."""
    top = header_number(ctx, section)
    names, rows = _content(section)
    gap, inset, foot = 0.3, 0.28, 0.14
    colours = hues(ctx, len(names))
    plan = _plan(ctx, names, rows, width=WIDTH, room=BASE - top - foot, gap=gap, inset=inset, pad=0.1,
                 head_pad=0.14, head_min=0.72, row_min=0.52, row_max=0.78, first_heading=True)
    tall = plan.total + foot
    y = _start(top, BASE, tall, 0.3)
    for k, name in enumerate(names):
        x, w = LEFT + plan.xs[k], plan.widths[k]
        # The cap reaches only a little under the card's top edge, so none of its colour shows round the foot.
        rounded(ctx, (x, y, w, plan.head_h + 0.3), colours[k]['fill'], radius=0.14)
        rounded(ctx, (x, y + plan.head_h, w, tall - plan.head_h), 'card', radius=0.14)
        rect(ctx, (x, y + plan.head_h, w, 0.32), 'card')
    _names(ctx, plan, names, LEFT, y, colours=[colour['ink'] for colour in colours], inset=inset, align='center',
           pad=0.14)
    y += plan.head_h
    for r, row in enumerate(rows):
        h = plan.heights[r]
        if r:
            for k in range(len(names)):
                x = LEFT + plan.xs[k]
                line(ctx, (x + inset, y), (x + plan.widths[k] - inset, y), 'card_muted', 0.6)
        _row(ctx, plan, row, LEFT, y, h, colours=['card_ink'] * len(row), inset=inset)
        y += h


# ---------------------------------------------------------------- hue pills


def _flag_top(ctx, section):
    """Eyebrow and heading beside a tall accent bar. Returns where the body starts (2.3)."""
    rect(ctx, (LEFT, 0.68, 0.1, 1.36), 'accent')
    eyebrow(ctx, (LEFT + 0.34, 0.62, 3.2, 0.3))
    headline(ctx, section, (LEFT + 0.34, 0.94, WIDTH - 0.34, 1.1), size=30, lines=2, anchor='middle')
    return 2.3


@variant('table', 'hue_pills', counts=(2, 6), accepts=_grid)
def hue_pills(ctx, section, lines):
    """Each column name on a rounded pill of its own colour; the rows in bands that turn from card to the slide's
    ground, their cells centred under the pills (ranged left with them once a cell wraps), beside an accent bar at
    the heading."""
    top = _flag_top(ctx, section)
    names, rows = _content(section)
    gap, inset = 0.22, 0.26
    colours = hues(ctx, len(names))
    plan = _plan(ctx, names, rows, width=WIDTH, room=BASE - top, gap=gap, inset=inset, pad=0.1, head_pad=0.14,
                 head_min=0.7, row_min=0.56, row_max=0.82)
    # Short cells sit centred under their pills; a paragraph centred reads ragged on both sides, so cells that wrap
    # range left, and their names with them.
    align = 'left' if plan.wraps else 'center'
    y = _start(top, BASE, plan.total, 0.35)
    pill = plan.head_h - 0.14
    for k in range(len(names)):
        rounded(ctx, (LEFT + plan.xs[k], y, plan.widths[k], pill), colours[k]['fill'], radius=pill / 2)
    _names(ctx, plan, names, LEFT, y - 0.07, colours=[colour['ink'] for colour in colours], inset=inset,
           align=align, pad=0.14)
    y += plan.head_h
    for r, row in enumerate(rows):
        h = plan.heights[r]
        band = 'card' if r % 2 == 0 else 'surface'
        if band == 'card':
            rounded(ctx, (LEFT, y, WIDTH, h), 'card', radius=0.1)
        _row(ctx, plan, row, LEFT, y, h, colours=inks(band)['ink'], inset=inset, align=align)
        y += h


# ---------------------------------------------------------------- ledger


def _ledger_top(ctx, section):
    """The heading at the left, the eyebrow at the right, a hairline across under both. Returns where the body
    starts (2.36)."""
    eyebrow(ctx, (RIGHT - 3.0, 0.62, 3.0, 0.3), align='right')
    headline(ctx, section, (LEFT, 0.66, WIDTH - 3.3, 1.28), size=30, lines=2, anchor='bottom')
    line(ctx, (LEFT, 2.16), (RIGHT, 2.16), 'muted', 0.75)
    return 2.36


@variant('table', 'ledger', counts=(2, 6), accepts=_grid)
def ledger(ctx, section, lines):
    """A ledger: a thick accent bar at the left of the header row, the rows in bands that turn from card to the
    slide's ground, the last column set right and bold in the accent when it holds short figures, and a closing rule
    under the last row."""
    top = _ledger_top(ctx, section)
    names, rows = _content(section)
    inset, bar = 0.26, 0.14
    lead = bar + 0.06
    last = len(names) - 1
    # Short last cells read as the ledger's figures, set right and bold; sentences there stay plain and ranged left
    # like the rest, and the first column leads instead.
    figures = all(len(_clip(row[last], CELL).split()) <= 4 for row in rows)
    aligns = ['left'] * last + ['right' if figures else 'left']
    bolds = [False] * last + [True] if figures else [True] + [False] * last
    plan = _plan(ctx, names, rows, width=WIDTH, room=BASE - top - 0.06, inset=inset, lead=lead, pad=0.1,
                 head_pad=0.1, head_min=0.6, row_min=0.56, row_max=0.82, bolds=bolds)
    y = _start(top, BASE, plan.total + 0.06, 0.35)
    rect(ctx, (LEFT, y, bar, plan.head_h), 'accent')
    _names(ctx, plan, names, LEFT, y, colours='ink', inset=inset, lead=lead, aligns=aligns)
    y += plan.head_h
    for r, row in enumerate(rows):
        h = plan.heights[r]
        band = 'card' if r % 2 == 0 else 'surface'
        if band == 'card':
            rect(ctx, (LEFT, y, WIDTH, h), 'card')
        colours = inks(band)
        _row(ctx, plan, row, LEFT, y, h, colours=[colours['ink']] * last + [colours['accent' if figures else 'ink']],
             inset=inset, lead=lead, aligns=aligns)
        y += h
    rect(ctx, (LEFT, y + 0.03, WIDTH, 0.03), 'ink')
