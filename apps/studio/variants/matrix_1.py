"""Matrix variants: the four cells round a centre disc, as letter tiles, across two axes, in tones and as tabbed rows."""
from .. import slides as base
from ..slide_layouts import _paragraph_height
from ..slides import _text_width
from . import variant
from .kit import (FOOT, LEFT, RIGHT, RULE, WIDTH, Z, badge, block, clip, columns_of, disc, entries, eyebrow,
                  header_band, header_number, header_side, headline, hex_of, hues, inks, on, oval, polygon, readable,
                  rect, rule, split, strong, text, tones, triangle_points)

LABEL, BODY, AXIS = 6, 28, 5          # the classic drawer's word limits: a cell's name, its sentences, an axis
AFTER = 6                             # points between a cell's name and its text
# (name, text) point sizes, largest first: a slide takes the first at which every cell fits.
LADDER = ((20, 15), (19, 15), (19, 14), (18, 14), (17, 14), (17, 13), (16, 13), (16, 12), (15, 12))
FOUR = (4, 4)
DOT = '  •  '                         # between the two axis names on one line


# ---------------------------------------------------------------- measuring


def _clean(value, words=None):
    parts = str(value or '').split()
    return ' '.join(parts[:words] if words else parts)


def _paragraphs(item, label, body, *, ink, muted, align='left', after=AFTER):
    """A cell's name over its text, as kit.block paragraphs."""
    return [dict(text=item.get('label'), words=LABEL, size=label, floor=min(label, 12), colour=ink, bold=True,
                 heading=True, after=after, align=align),
            dict(text=item.get('text'), words=BODY, size=body, floor=12, colour=muted, align=align)]


def _need(ctx, width, paragraphs):
    """Inches `paragraphs` (as for kit.block) take in a box `width` wide, with block's own allowance."""
    zone = Z(0, 0, width, 1)
    total = 0.0
    for paragraph in paragraphs:
        value = _clean(paragraph.get('text'), paragraph.get('words'))
        if not value:
            continue
        bold = bool(paragraph.get('bold')) or bool(paragraph.get('heading') and ctx.heading_bold)
        total += _paragraph_height(dict(text=value, size=paragraph['size'], bold=bold,
                                        before=paragraph.get('before', 0), after=paragraph.get('after', 0),
                                        spacing=paragraph.get('spacing', 1.15)), zone)
    return (total + 4) / 72 if total else 0.0


def _sizes(ctx, cells, width, room, ladder=LADDER, after=AFTER):
    """The largest (name, text) sizes at which every cell fits `room` inches: (name, text, tallest cell)."""
    for label, body in ladder:
        need = max(_need(ctx, width, _paragraphs(item, label, body, ink='ink', muted='ink', after=after))
                   for item in cells)
        if need <= room:
            break
    return label, body, need


def _cell(ctx, box, item, label, body, *, ink, muted, align='left', anchor='top', after=AFTER):
    block(ctx, box, _paragraphs(item, label, body, ink=ink, muted=muted, align=align, after=after), anchor=anchor)


def _axes(ctx, section):
    """The matrix's axis names (columns), each held to the classic limit."""
    return [clip(ctx, axis, AXIS) for axis in columns_of(section)[:2]]


def _marks(cells):
    """Each cell's mark: the first letter of its name (SWOT's S, W, O, T), or 1-4 when two letters would repeat."""
    letters = []
    for item in cells:
        letter = next((character.upper() for character in str(item.get('label') or '') if character.isalnum()), '')
        letters.append(letter)
    if '' in letters or len(set(letters)) < len(letters):
        return [str(position + 1) for position in range(len(cells))]
    return letters


def _stack(count, row, top, bottom, least, most):
    """Where each of `count` rows starts, evenly spaced and centred between `top` and `bottom`."""
    spare = bottom - top - count * row
    gap = max(least, min(most, spare / (count - 1))) if count > 1 else 0
    start = top + max(0.0, (bottom - top - count * row - gap * (count - 1)) / 2)
    return [start + k * (row + gap) for k in range(count)]


def _width(value, size):
    """Inches `value` takes on one line at `size` points, bold."""
    return _text_width(value, size) * 1.06 / 72


def _heading(ctx, section, *, align='left', size=28):
    """Eyebrow, a heading of up to two lines and the rule, the rule clear of the heading's descenders.

    Returns where the body starts (2.3 in).
    """
    centre = align == 'center'
    eyebrow(ctx, (LEFT, 0.62, WIDTH if centre else 3.2, 0.3), align=align)
    headline(ctx, section, (LEFT + 0.8, 0.9, WIDTH - 1.6, 0.94) if centre else (LEFT, 0.9, WIDTH, 0.94),
             size=size, lines=2, align=align)
    rule(ctx, (LEFT + WIDTH / 2 - 0.5, 2.0, 1.0, RULE) if centre else (LEFT, 2.0, 0.9, RULE))
    return 2.3


def _calm(fill):
    """A colour turned round the wheel, kept to a mid tone: no neon green or violet beside the deck's own colours."""
    hue, lightness, saturation = base._hls(fill)
    saturation, lightness = min(saturation, 0.58), min(lightness, 0.5)
    colour = base._from_hls(hue, lightness, saturation)
    while base._luminance(colour) > 0.2 and lightness > 0.28:
        lightness -= 0.02
        colour = base._from_hls(hue, lightness, saturation)
    return colour


def _palette(ctx, n):
    """`n` fills from kit.hues with the inks that read on them: the accent and second colour as they are, the
    wheel-turned ones calmed."""
    own = {hex_of(ctx, 'accent'), hex_of(ctx, 'secondary')}
    grey = base._hls(hex_of(ctx, 'accent'))[2] < 0.12      # kit.hues gives a grey accent its tones: kept as they are
    paints = []
    for paint in hues(ctx, n):
        fill = hex_of(ctx, paint['fill'])
        fill = fill if grey or fill in own else _calm(fill)
        paints.append({'fill': fill, 'ink': on(fill), 'muted': on(fill), 'text': readable(ctx, fill)})
    return paints


# ---------------------------------------------------------------- variants


@variant('matrix', 'centre_disc', counts=FOUR)
def centre_disc(ctx, section, lines):
    """Four cells in card and soft tint round a strong disc where the gutters cross, the slide's number in it, under a centred heading."""
    top = _heading(ctx, section, align='center')
    cells = entries('matrix', section)
    axes = _axes(ctx, section)
    bottom = FOOT - (0.4 if axes else 0.05)
    gap, halo, core, pad, rise, dash = 0.16, 1.5, 1.14, 0.45, 0.2, 0.22
    (x0, width), (x1, _) = split(LEFT, WIDTH, 2, gap)
    (y0, tall), (y1, _) = split(top, bottom - top, 2, gap)
    cx, cy = LEFT + WIDTH / 2, top + (bottom - top) / 2
    # The halo runs into each cell from its inner corner; text keeps clear of it on the inner side and
    # leans towards it, so the four cells read as one figure round the disc.
    clear = halo / 2 - gap / 2 + 0.2
    inner = width - pad - clear
    label, body, need = _sizes(ctx, cells, inner, tall - 2 * rise - dash)
    for position, item in enumerate(cells):
        row, column = divmod(position, 2)
        fill = 'accent_soft' if (row + column) % 2 else 'card'
        colours = inks(fill)
        x, y = (x0, x1)[column], (y0, y1)[row]
        rect(ctx, (x, y, width, tall), fill)
        left = x + (pad if column == 0 else clear)
        start = y + (tall - need - dash) / 2
        mark = left + inner - 0.5 if column == 0 else left
        rect(ctx, (mark, start, 0.5, RULE), colours['accent'])
        _cell(ctx, (left, start + dash, inner, need), item, label, body, ink=colours['ink'], muted=colours['muted'],
              align='right' if column == 0 else 'left')
    oval(ctx, disc(cx, cy, halo), 'surface')
    paint = inks(strong(ctx))
    badge(ctx, disc(cx, cy, core), f'{ctx.index + 1:02d}', fill=paint['fill'], ink=paint['ink'], size=30,
          heading=True)
    if axes:
        text(ctx, (LEFT, bottom + 0.08, WIDTH, 0.3), DOT.join(axes), size=12, colour='muted', bold=True,
             align='center', anchor='middle')


@variant('matrix', 'letter_tiles', counts=FOUR)
def letter_tiles(ctx, section, lines):
    """Each quadrant led by a large colour tile holding its name's first letter, SWOT style, the name and text beside it."""
    top = _heading(ctx, section) + 0.1
    cells = entries('matrix', section)
    axes = _axes(ctx, section)
    bottom = FOOT - (0.45 if axes else 0.1)
    tile, beside, row_gap = 1.06, 0.32, 0.4
    spans = split(LEFT, WIDTH, 2, 0.55)
    inner = spans[0][1] - tile - beside
    label, body, need = _sizes(ctx, cells, inner, (bottom - top - row_gap) / 2)
    row = max(tile, need)
    places = _stack(2, row, top, bottom, least=row_gap, most=0.6)
    paints = _palette(ctx, 4)
    for position, (item, mark, paint) in enumerate(zip(cells, _marks(cells), paints)):
        line_, column = divmod(position, 2)
        x, y = spans[column][0], places[line_]
        badge(ctx, (x, y, tile, tile), mark, fill=paint['fill'], ink=paint['ink'], shape='rounded', size=44,
              heading=True)
        _cell(ctx, (x + tile + beside, y, inner, row), item, label, body, ink='ink', muted='muted',
              anchor='middle' if need < tile else 'top')
    if axes:
        text(ctx, (LEFT, FOOT - 0.36, WIDTH, 0.3), '  /  '.join(axes), size=12, colour='muted', bold=True,
             align='right', anchor='middle', upper=True)


@variant('matrix', 'cross_axes', counts=FOUR)
def cross_axes(ctx, section, lines):
    """The heading in a column at the left; two thin accent bars cross beside it, arrowed like a chart's axes, with a numbered name and text in each quadrant."""
    start = header_side(ctx, section, width=3.4, size=30)
    cells = entries('matrix', section)
    axes = _axes(ctx, section)
    bar, head, pad = 0.05, 0.16, 0.3
    ceiling = 0.62 + (0.42 if len(axes) > 1 else 0.05)
    floor = FOOT - 0.05
    end = RIGHT - 0.05
    cx = start + (end - start) / 2
    cy = ceiling + (floor - ceiling) / 2
    # The horizontal axis's name, if any, sits at the bar's right end in the gap between the rows.
    name = axes[0] if axes else ''
    name_width = min(2.0, max(0.6, _width(name, 12) + 0.15)) if name else 0.0
    reach = end - name_width - (0.12 if name else 0)
    figure_h = 0.5
    width = (end - start - bar) / 2 - 2 * pad
    room = (floor - ceiling - 0.7) / 2 - figure_h
    label, body, need = _sizes(ctx, cells, width, room)
    paint = 'accent_text'
    rect(ctx, (start, cy - bar / 2, reach - start - head * 0.6, bar), paint)
    polygon(ctx, triangle_points((reach - head, cy - head / 2, head, head), 'right'), paint)
    rect(ctx, (cx - bar / 2, ceiling + head * 0.6, bar, floor - ceiling - head * 0.6), paint)
    polygon(ctx, triangle_points((cx - head / 2, ceiling, head, head), 'up'), paint)
    if name:
        text(ctx, (end - name_width, cy - 0.22, name_width, 0.44), name, size=12, colour='accent_text', bold=True,
             align='right', anchor='middle')
    if len(axes) > 1:
        text(ctx, (cx - 1.6, 0.62, 3.2, 0.34), axes[1], size=12, colour='accent_text', bold=True, align='center',
             anchor='middle')
    half = (floor - ceiling) / 2
    for position, item in enumerate(cells):
        row, column = divmod(position, 2)
        x = start + pad if column == 0 else cx + bar / 2 + pad
        block_h = figure_h + need
        y = ceiling + row * half + (half - block_h) / 2 + (0.12 if row else -0.12)
        text(ctx, (x, y, 1.2, figure_h - 0.06), f'{position + 1:02d}', size=24, colour='accent_text', bold=True,
             heading=True, anchor='bottom')
        _cell(ctx, (x, y + figure_h, width, need), item, label, body, ink='ink', muted='muted')


@variant('matrix', 'tone_grid', counts=FOUR)
def tone_grid(ctx, section, lines):
    """Four cells joined edge to edge in the accent's tones, darkest at the top left to lightest at the bottom right, under the slide's number large."""
    # header_number's number and heading end at 2.25 in; the grid starts a little under them.
    top = header_number(ctx, section) - 0.2
    cells = entries('matrix', section)
    axes = _axes(ctx, section)
    bottom = FOOT - (0.4 if axes else 0.05)
    pad, rise, dash = 0.42, 0.2, 0.22
    (x0, width), (x1, _) = split(LEFT, WIDTH, 2, 0)
    (y0, tall), (y1, _) = split(top, bottom - top, 2, 0)
    inner = width - 2 * pad
    label, body, need = _sizes(ctx, cells, inner, tall - 2 * rise - dash)
    paints = tones(ctx, 4)
    for position, (item, paint) in enumerate(zip(cells, paints)):
        row, column = divmod(position, 2)
        x, y = (x0, x1)[column], (y0, y1)[row]
        rect(ctx, (x, y, width, tall), paint['fill'])
        start = y + (tall - need - dash) / 2
        rect(ctx, (x + pad, start, 0.5, RULE), paint['ink'])
        _cell(ctx, (x + pad, start + dash, inner, need), item, label, body, ink=paint['ink'], muted=paint['muted'])
    if axes:
        text(ctx, (LEFT, bottom + 0.08, WIDTH, 0.3), DOT.join(axes), size=12, colour='muted', bold=True,
             align='right', anchor='middle')


@variant('matrix', 'rows_four', counts=FOUR)
def rows_four(ctx, section, lines):
    """The heading on a band across the top; four full-width card rows below, each led by a coloured chevron tab holding its name, the text beside it."""
    # A near-black band on a light deck. On a dark one strong() would pick the bright accent or second colour,
    # loud beside four coloured tabs; the soft tint keeps the band quiet there and leaves the colour to the tabs.
    band = 'deep' if strong(ctx) == 'deep' else 'accent_soft'
    top = header_band(ctx, section, fill=band, height=1.5)
    cells = entries('matrix', section)
    axes = _axes(ctx, section)
    bottom = FOOT - (0.4 if axes else 0)
    gap, tab, point, pad = 0.14, 3.0, 0.3, 0.3
    label_w = tab - point - 2 * 0.25
    left = LEFT + tab + pad
    inner = RIGHT - pad - left
    most = (bottom - top - 3 * gap) / 4
    for name, body in ((19, 16), (18, 15), (18, 14), (17, 14), (16, 13), (15, 12)):
        name_need = max(_need(ctx, label_w, _paragraphs(item, name, body, ink='ink', muted='ink')[:1])
                        for item in cells)
        text_need = max(_need(ctx, inner, _paragraphs(item, name, body, ink='ink', muted='ink')[1:])
                        for item in cells)
        if max(name_need, text_need) <= most - 0.16:
            break
    row = min(most, max(0.86, max(name_need, text_need) + 0.3))
    places = _stack(4, row, top, bottom, least=gap, most=0.24)
    paints = _palette(ctx, 4)
    for item, paint, y in zip(cells, paints, places):
        rect(ctx, (LEFT, y, WIDTH, row), 'card')
        polygon(ctx, [(LEFT, y), (LEFT + tab - point, y), (LEFT + tab, y + row / 2), (LEFT + tab - point, y + row),
                      (LEFT, y + row)], paint['fill'])
        text(ctx, (LEFT + 0.25, y + 0.06, label_w, row - 0.12), item.get('label'), words=LABEL, size=name,
             floor=12, colour=paint['ink'], bold=True, heading=True, anchor='middle')
        text(ctx, (left, y + 0.06, inner, row - 0.12), item.get('text'), words=BODY, size=body, floor=12,
             colour='card_ink', anchor='middle')
    if axes:
        text(ctx, (LEFT, bottom + 0.08, WIDTH, 0.3), DOT.join(axes), size=12, colour='muted', bold=True,
             align='right', anchor='middle')
