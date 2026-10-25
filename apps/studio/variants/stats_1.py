"""Stats variants: each figure set large on a shape of its own — a disc, a ring, a tile, a bar, a panel or a band."""
from pptx.util import Inches

from . import variant
from ..slide_layouts import _paragraph_height, _text_lines
from ..slides import _luminance, contrast_ratio
from .kit import (FOOT, LEFT, RIGHT, RULE, WIDTH, Z, block, disc, entries, eyebrow, figure, header, header_number,
                  headline, hex_of, hues, inks, inscribed, line, oval, polygon, rect, ring, rule, split, strong,
                  tab_points, triangle_points)

TOP_EDGE = 0.62
# The classic drawer's word limits: figure, name, sentence.
VALUE, LABEL, BODY = 3, 8, 20
# (name, sentence) sizes, largest first: every figure of a slide is captioned at the first that holds them all.
LADDER = ((19, 15), (18, 15), (18, 14), (17, 14), (16, 14), (16, 13), (15, 13), (15, 12), (14, 12))
# The sizes a shape gives way to: a disc or ring shrinks before its captions go below these.
READABLE = LADDER[:5]


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


def _heights(ctx, width, items, make, sizes):
    """(name, gap, sentence) in inches: the tallest name and the tallest sentence of `items` at `sizes`.

    Every name of a row is set in a box as tall as the tallest, on its foot, so all the sentences start on one
    line however many lines each name takes.
    """
    name = sentence = gap = 0.0
    for k, item in enumerate(items):
        label, text = make(k, item, *sizes)
        name = max(name, _need(ctx, width, [{**label, 'after': 0}]))
        sentence = max(sentence, _need(ctx, width, [text]))
        gap = label.get('after', 0) / 72
    return name, gap if sentence else 0.0, sentence


def _name_lines(ctx, width, items, make, sizes):
    """The most lines any item's name takes at `sizes`."""
    most = 0
    for k, item in enumerate(items):
        label = make(k, item, *sizes)[0]
        value = _plain(label.get('text'), label.get('words'))
        if value:
            most = max(most, _text_lines(value, label['size'], Inches(width), bold=_bold(ctx, label)))
    return most


def _settle(ctx, items, make, width, room, ladder=LADDER):
    """The first sizes in `ladder` at which every item's caption fits `width` x `room`; None if none do.

    A name a step or two smaller that saves it a line is preferred: a name broken for one word reads worse
    than one set a point smaller.
    """
    def holds(sizes):
        return (sum(_heights(ctx, width, items, make, sizes)) <= room
                and all(_whole(ctx, width, make(k, item, *sizes)) for k, item in enumerate(items)))
    for index, sizes in enumerate(ladder):
        if not holds(sizes):
            continue
        lines = _name_lines(ctx, width, items, make, sizes)
        for smaller in ladder[index + 1:]:
            if smaller[0] < sizes[0] - 2:
                break
            if _name_lines(ctx, width, items, make, smaller) < lines and holds(smaller):
                return smaller
        return sizes
    return None


def _caption(ctx, box, paragraphs, heights):
    """A figure's name and sentence in `box`, the name on the foot of a box `heights[0]` tall (see _heights)."""
    x, y, w, h = box
    label, text = paragraphs
    name, gap, sentence = heights
    block(ctx, (x, y, w, name), [{**label, 'after': 0}], anchor='bottom')
    if sentence:
        block(ctx, (x, y + name + gap, w, max(0.3, h - name - gap)), [text])


def _figure_size(ctx, items, width, start, least):
    """The largest size up to `start` at which every figure keeps to one line `width` wide (heading face).

    The figures of a slide share it. Below `least` they no longer read as the slide's figures — a disc with a
    small line of type in it — so the slide is marked squeezed and this variant is passed over for it.
    """
    values = [_plain(item.get('value'), VALUE) for item in items]
    size = start
    while size > 12 and any(_text_lines(value, size, Inches(width), bold=ctx.heading_bold) > 1
                            for value in values if value):
        size -= 2
    if size < least:
        ctx.squeezed = True
    return size


def _figure_tall(size):
    """The height of a one-line figure's box at `size` points."""
    return size * 1.1 / 72 + 0.1


def _story(item, label, body, *, ink='ink', muted='muted', align='left', gap=6):
    """A figure's caption for kit.block: its name, then its sentence, at the classic word limits."""
    return [dict(text=item.get('label'), words=LABEL, size=label, floor=min(label, 14), colour=ink, bold=True,
                 heading=True, after=gap, align=align),
            dict(text=item.get('text'), words=BODY, size=body, floor=12, colour=muted, align=align)]


def _mark(ctx, fill):
    """A small mark's colour on a panel of the role `fill`: the accent if it shows there, else the panel's ink."""
    if contrast_ratio(hex_of(ctx, 'accent'), hex_of(ctx, fill)) >= 2.2:
        return 'accent'
    return inks(fill)['ink']


def _vivid(ctx):
    """The accent for a mark on the surface, or its readable form where a dark accent sinks into a dark ground."""
    surface = hex_of(ctx, 'surface')
    if _luminance(surface) < 0.2 and contrast_ratio(hex_of(ctx, 'accent'), surface) < 1.8:
        return 'accent_text'
    return 'accent'


def _centre_top(ctx, section, size=28):
    """Eyebrow, heading and rule centred and compact. Returns where the body starts (2.32)."""
    eyebrow(ctx, (LEFT, TOP_EDGE, WIDTH, 0.3), align='center')
    headline(ctx, section, (LEFT + 1.0, 0.9, WIDTH - 2.0, 1.0), size=size, lines=2, align='center')
    rule(ctx, (LEFT + WIDTH / 2 - 0.45, 2.04, 0.9, RULE), colour=_vivid(ctx))
    return 2.32


def _compact_top(ctx, section, size=28):
    """kit.header_compact with the rule clear of the heading's descenders. Returns where the body starts (2.26)."""
    eyebrow(ctx)
    headline(ctx, section, (LEFT, 0.9, WIDTH, 0.98), size=size, lines=2)
    rule(ctx, (LEFT, 2.03, 0.9, RULE), colour=_vivid(ctx))
    return 2.26


def _heading_fit(ctx, section, width, size, lines):
    """(size, height in inches) the slide's heading takes in `width` at most `lines` lines, as kit.headline sets it."""
    value = _plain(section.get('heading'), 14)
    count = _text_lines(value, size, Inches(width), bold=ctx.heading_bold)
    while size > 18 and count > lines:
        size -= 2
        count = _text_lines(value, size, Inches(width), bold=ctx.heading_bold)
    return size, max(1, count) * size * 1.08 / 72 + 0.08


def _columns(n, gap, widest):
    """`n` columns of at most `widest`, centred across the frame: [(x, width), ...]."""
    width = min(widest, (WIDTH - gap * (n - 1)) / n)
    start = LEFT + (WIDTH - n * width - (n - 1) * gap) / 2
    return [(start + k * (width + gap), width) for k in range(n)]


# ---------------------------------------------------------------- circles


@variant('stats', 'circles', counts=(2, 4))
def circles(ctx, section, lines):
    """Each figure on a large accent disc inside a thin outline, centred over its name and sentence, under a
    centred heading."""
    top = _centre_top(ctx, section)
    tiles = entries('stats', section)
    n = len(tiles)
    columns = _columns(n, 0.55 if n > 2 else 0.9, 4.2 if n == 2 else 3.5)
    width = columns[0][1]
    halo, gap = 0.15, 0.3

    def make(k, item, label, body):
        return _story(item, label, body, align='center')
    # A large disc whose captions stay readable; only then smaller captions, and last a smaller disc.
    chosen = None
    for ladder, diameters in ((READABLE, (1.95, 1.8, 1.65)), (LADDER, (1.95, 1.8, 1.65, 1.5, 1.35))):
        for diameter in diameters:
            room = FOOT - top - diameter - 2 * halo - gap
            sizes = _settle(ctx, tiles, make, width, room, ladder)
            if sizes:
                chosen = diameter, sizes
                break
        if chosen:
            break
    diameter, sizes = chosen or (1.35, LADDER[-1])
    outer = diameter + 2 * halo
    room = FOOT - top - outer - gap
    heights = _heights(ctx, width, tiles, make, sizes)
    y = top + max(0.0, (room - sum(heights)) / 2 - 0.1)
    size = _figure_size(ctx, tiles, inscribed(disc(0, 0, diameter))[2], 44 if n > 2 else 50, 24)
    for item, (x, w) in zip(tiles, columns):
        cx, cy = x + w / 2, y + outer / 2
        ring(ctx, disc(cx, cy, outer - 0.02), _vivid(ctx), width=1.5)
        oval(ctx, disc(cx, cy, diameter), 'accent')
        figure(ctx, inscribed(disc(cx, cy, diameter)), item.get('value'), size=size, colour='on_accent',
               align='center', anchor='middle', words=VALUE)
        _caption(ctx, (x, y + outer + gap, w, FOOT - y - outer - gap), make(0, item, *sizes), heights)


# ---------------------------------------------------------------- rings


@variant('stats', 'rings', counts=(2, 4))
def rings(ctx, section, lines):
    """Each figure in the accent inside a thick accent ring, the rings linked by a thin line across the slide, and
    each name and sentence ranged left under its ring."""
    top = _compact_top(ctx, section)
    tiles = entries('stats', section)
    n = len(tiles)
    gap = 0.5
    spans = split(LEFT, WIDTH, n, gap)
    width = min(spans[0][1], 4.2)
    weight, space = 7.5, 0.32
    # The figure's box keeps inside the stroke's inner edge (0.667 of the ring for a 7.5 pt stroke).
    share = 0.64
    colour = _vivid(ctx)
    # Three rings or fewer have room for larger ones and still a link between each.
    largest = (2.1, 1.95, 1.85) if n < 4 else (1.85,)

    def make(k, item, label, body):
        return _story(item, label, body)
    chosen = None
    for ladder, diameters in ((READABLE, largest + (1.7, 1.55)), (LADDER, largest + (1.7, 1.55, 1.4, 1.3))):
        for diameter in diameters:
            sizes = _settle(ctx, tiles, make, width, FOOT - top - diameter - space, ladder)
            if sizes:
                chosen = diameter, sizes
                break
        if chosen:
            break
    diameter, sizes = chosen or (1.3, LADDER[-1])
    room = FOOT - top - diameter - space
    heights = _heights(ctx, width, tiles, make, sizes)
    y = top + max(0.0, (room - sum(heights)) / 2 - 0.1)
    cy = y + diameter / 2
    size = _figure_size(ctx, tiles, inscribed(disc(0, 0, diameter), share)[2], 44, 22)
    reach = weight / 72 / 2 + 0.14
    for k, (item, (x, w)) in enumerate(zip(tiles, spans)):
        box = (x, y, diameter, diameter)
        ring(ctx, box, colour, width=weight)
        figure(ctx, inscribed(box, share), item.get('value'), size=size, colour='accent_text', align='center',
               anchor='middle', words=VALUE)
        # The link runs from this ring to the next, or to the frame's edge after the last.
        end = spans[k + 1][0] - reach if k + 1 < n else RIGHT
        start = x + diameter + reach
        # A link after the last ring only when it has room to read as one, not a stub.
        if end - start > (1.0 if k + 1 == n else 0.3):
            line(ctx, (start + 0.05, cy), (end - 0.05, cy), colour, 1.25)
            for tip in (start, end - 0.06 if k + 1 == n else end):
                oval(ctx, disc(tip, cy, 0.11), colour)
        _caption(ctx, (x, y + diameter + space, width, FOOT - y - diameter - space), make(k, item, *sizes),
                 heights)


# ---------------------------------------------------------------- colour tiles


@variant('stats', 'colour_tiles', counts=(2, 4))
def colour_tiles(ctx, section, lines):
    """A tall tile in its own colour per figure, a corner cut off, with the figure large at the top and its name and
    sentence at the foot, under the slide's number and heading."""
    header_number(ctx, section)
    tiles = entries('stats', section)
    n = len(tiles)
    top, gap, pad, cut = 2.55, 0.24 if n > 2 else 0.4, 0.3, 0.42
    spans = split(LEFT, WIDTH, n, gap)
    inner = spans[0][1] - 2 * pad
    paints = hues(ctx, n)
    # Wide tiles carry a larger figure, so two of them are not two broad fields of colour.
    size = _figure_size(ctx, tiles, inner - 0.25, {2: 72, 3: 60}.get(n, 48), 28)
    figure_tall = _figure_tall(size)
    room = FOOT - top - 2 * pad - figure_tall - 0.3

    def make(k, item, label, body):
        return _story(item, label, body, ink=paints[k]['ink'], muted=paints[k]['ink'])
    sizes = _settle(ctx, tiles, make, inner, room) or LADDER[-1]
    # Every caption starts on the same line, as low as the longest lets it.
    heights = _heights(ctx, inner, tiles, make, sizes)
    tall = min(room, sum(heights))
    for k, (item, (x, w)) in enumerate(zip(tiles, spans)):
        paint = paints[k]
        polygon(ctx, tab_points((x, top, w, FOOT - top), cut=cut, corner='top_right'), paint['fill'])
        figure(ctx, (x + pad, top + pad, inner - 0.25, figure_tall), item.get('value'), size=size,
               colour=paint['ink'], anchor='top', words=VALUE)
        rect(ctx, (x + pad, top + pad + figure_tall + 0.1, 0.5, 0.05), paint['ink'])
        _caption(ctx, (x + pad, FOOT - pad - tall, inner, tall), make(k, item, *sizes), heights)


# ---------------------------------------------------------------- side bars


@variant('stats', 'side_bars', counts=(2, 4))
def side_bars(ctx, section, lines):
    """The heading in a column down the left; beside it each figure stands against a thick bar, accent where the
    figure is and pale below, with its name and sentence — in one row, or two by two for four."""
    tiles = entries('stats', section)
    n = len(tiles)
    # Three columns beside the heading take some of its width, so none of them is a narrow strip.
    side = 2.9 if n == 3 else 3.3
    x0 = LEFT + side + (0.5 if n == 3 else 0.6)
    per_row = 2 if n == 4 else n
    rows = -(-n // per_row)
    gap, row_gap, bar, pad = 0.4 if n == 3 else 0.45, 0.5, 0.11, 0.26
    spans = split(x0, RIGHT - x0, per_row, gap)
    inner = spans[0][1] - bar - pad
    size = _figure_size(ctx, tiles, inner, 54 if n < 4 else 48, 28)
    figure_tall = _figure_tall(size)
    space = (FOOT - 1.2 - (rows - 1) * row_gap) / rows

    def make(k, item, label, body):
        return _story(item, label, body)
    room = space - figure_tall - 0.12
    sizes = _settle(ctx, tiles, make, inner, room) or LADDER[-1]
    marks = [_heights(ctx, inner, tiles[r * per_row:][:per_row], make, sizes) for r in range(rows)]
    heights = [figure_tall + 0.12 + sum(mark) for mark in marks]
    used = sum(heights) + (rows - 1) * row_gap
    y0 = max(1.2, TOP_EDGE + (FOOT - TOP_EDGE - used) / 2)
    eyebrow(ctx, (LEFT, TOP_EDGE, side, 0.3))
    rule(ctx, (LEFT, y0, 0.9, RULE), colour=_vivid(ctx))
    headline(ctx, section, (LEFT, y0 + 0.22, side, min(4.6, FOOT - y0 - 0.22)), size=30, lines=6, anchor='top')
    y = y0
    for r in range(rows):
        for k in range(r * per_row, min(n, (r + 1) * per_row)):
            item, (x, w) = tiles[k], spans[k - r * per_row]
            rect(ctx, (x, y, bar, heights[r]), 'accent_soft')
            rect(ctx, (x, y, bar, figure_tall), _vivid(ctx))
            figure(ctx, (x + bar + pad, y - 0.04, inner, figure_tall), item.get('value'), size=size,
                   colour='accent_text', anchor='middle', words=VALUE)
            _caption(ctx, (x + bar + pad, y + figure_tall + 0.12, inner, heights[r] - figure_tall - 0.12),
                     make(k, item, *sizes), marks[r])
        y += heights[r] + row_gap


# ---------------------------------------------------------------- feature first


@variant('stats', 'feature_first', counts=(2, 4))
def feature_first(ctx, section, lines):
    """The first figure huge on a strong panel filling the left of the frame; the heading and the other figures as
    rows beside it, each figure in the accent beside its name and sentence."""
    tiles = entries('stats', section)
    first, rest = tiles[0], tiles[1:]
    panel = inks(strong(ctx))
    width, pad = 5.3, 0.5
    rect(ctx, (LEFT, TOP_EDGE, width, FOOT - TOP_EDGE), panel['fill'])
    eyebrow(ctx, (LEFT + pad, TOP_EDGE + 0.4, width - 2 * pad, 0.3), colour=panel['muted'])
    inner = width - 2 * pad
    # A hero figure, as large as the classic big_number sets its one.
    big = _figure_size(ctx, [first], inner, 110, 48)
    big_tall = _figure_tall(big) + 0.1
    feature_room = FOOT - TOP_EDGE - 1.3 - big_tall - 0.4 - pad

    def lead(k, item, label, body):
        return _story(item, label, body, ink=panel['ink'], muted=panel['muted'], gap=8)
    # The feature's name is a step above the rows' (as big_number's is); its sentence stays running text.
    ladder = ((24, 16), (22, 16), (22, 15), (20, 15), (20, 14), (18, 14), (18, 13), (16, 12))
    lead_sizes = _settle(ctx, [first], lead, inner, feature_room, ladder) or ladder[-1]
    lead_heights = _heights(ctx, inner, [first], lead, lead_sizes)
    group = big_tall + 0.4 + sum(lead_heights)
    y = TOP_EDGE + 0.9 + max(0.0, (FOOT - TOP_EDGE - 0.9 - pad - group) / 2)
    figure(ctx, (LEFT + pad, y, inner, big_tall), first.get('value'), size=big, colour=panel['ink'],
           anchor='bottom', words=VALUE)
    rule(ctx, (LEFT + pad, y + big_tall + 0.16, 1.0, 4 / 72), colour=_mark(ctx, panel['fill']))
    _caption(ctx, (LEFT + pad, y + big_tall + 0.4, inner, FOOT - pad - y - big_tall - 0.4),
             lead(0, first, *lead_sizes), lead_heights)

    x = LEFT + width + 0.6
    right = RIGHT - x
    m = len(rest)
    heading_size, heading_tall = _heading_fit(ctx, section, right, 28, 3)
    lead_in = heading_tall + 0.2 + RULE + 0.25
    figure_w, space = 1.75, 0.3
    story_w = right - figure_w - space
    size = _figure_size(ctx, rest, figure_w, 40 if m > 1 else 48, 22)

    def make(k, item, label, body):
        return _story(item, label, body, gap=4)
    most = (FOOT - TOP_EDGE - 0.15 - lead_in) / m
    sizes = _settle(ctx, rest, make, story_w, most - 0.3, LADDER[1:]) or LADDER[-1]
    tall = max(_need(ctx, story_w, make(k, item, *sizes)) for k, item in enumerate(rest))
    # Short rows keep together with the heading, the whole column centred beside the panel.
    row = min(most, max(tall + 0.5, 1.3))
    group = lead_in + row * m
    top = TOP_EDGE + 0.15 + max(0.0, (FOOT - TOP_EDGE - 0.15 - group) / 2 - 0.1)
    headline(ctx, section, (x, top, right, heading_tall), size=heading_size, lines=3, anchor='top')
    rule(ctx, (x, top + heading_tall + 0.2, 0.9, RULE), colour=_vivid(ctx))
    y = top + lead_in
    for k, item in enumerate(rest):
        if k:
            line(ctx, (x, y), (RIGHT, y), 'accent_soft', 1.25)
        figure(ctx, (x, y + 0.1, figure_w, row - 0.2), item.get('value'), size=size, colour='accent_text',
               anchor='middle', words=VALUE)
        block(ctx, (x + figure_w + space, y + 0.12, story_w, row - 0.24), make(k, item, *sizes), anchor='middle')
        y += row


# ---------------------------------------------------------------- dark band


@variant('stats', 'dark_band', counts=(2, 4))
def dark_band(ctx, section, lines):
    """A full-width strong band across the body carries the figures, parted by thin rules, each with a notch
    pointing down to its name and sentence below the band."""
    top = header(ctx, section)
    tiles = entries('stats', section)
    n = len(tiles)
    band = inks(strong(ctx))
    spans = split(LEFT, WIDTH, n, 0)
    pad = 0.42
    inner = spans[0][1] - 2 * pad
    size = _figure_size(ctx, tiles, inner, 54 if n > 2 else 60, 28)
    tall_band = max(1.35, _figure_tall(size) + 0.55)
    notch, space = 0.17, 0.4

    def make(k, item, label, body):
        return _story(item, label, body)
    room = FOOT - top - tall_band - space
    sizes = _settle(ctx, tiles, make, inner + 0.15, room) or LADDER[-1]
    heights = _heights(ctx, inner + 0.15, tiles, make, sizes)
    y = top + max(0.0, (room - sum(heights)) / 2 - 0.1)
    rect(ctx, (LEFT, y, WIDTH, tall_band), band['fill'])
    for k, (item, (x, w)) in enumerate(zip(tiles, spans)):
        if k:
            line(ctx, (x, y + 0.3), (x, y + tall_band - 0.3), band['muted'], 1.0)
        figure(ctx, (x + pad, y + 0.15, inner, tall_band - 0.3), item.get('value'), size=size, colour=band['ink'],
               anchor='middle', words=VALUE)
        polygon(ctx, triangle_points((x + pad, y + tall_band - 0.01, 0.34, notch), 'down'), band['fill'])
        _caption(ctx, (x + pad, y + tall_band + space, inner + 0.15, FOOT - y - tall_band - space),
                 make(k, item, *sizes), heights)
