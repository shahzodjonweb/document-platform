"""Chart variants: each figure a shape in scale — pointed bars, a called-out peak, columns, circles, zebra rows."""
import math

from pptx.util import Inches

from . import variant
from ..slide_layouts import _text_lines
from ..slides import contrast_ratio
from .kit import (FOOT, LEFT, RIGHT, RULE, WIDTH, chevron_points, columns_of, disc, entries, eyebrow, figure,
                  header_band, header_center, header_compact, header_number, header_side, headline, height, hex_of,
                  inks, inscribed, line, numbers, oval, polygon, readable, rect, strong, text, tones)

# The classic drawer's word limits: a bar's label, its figure, the chart's unit.
LABEL, VALUE, UNIT = 6, 3, 6


# ---------------------------------------------------------------- measuring


def _plain(value, words=None):
    parts = str(value or '').split()
    return ' '.join(parts[:words] if words else parts)


def _need(ctx, value, width, size, *, bold=False, heading=False):
    """Inches a box `width` wide must be tall to hold `value` at `size` as kit.text sets it."""
    value = _plain(value, LABEL)
    if not value:
        return 0.0
    return height(ctx, value, width, size, bold=bold, heading=heading) + 4 / 72


def _whole(ctx, value, width, size, *, bold=False, heading=False):
    """Whether every word of `value` keeps to one line `width` wide (none broken across lines)."""
    bold = bold or (heading and ctx.heading_bold)
    return all(_text_lines(word, size, Inches(width), bold=bold) == 1 for word in _plain(value, LABEL).split())


def _floor(value):
    """The smallest size a label may take: running text (over 40 characters) never goes below 12 pt."""
    return 12 if len(_plain(value, LABEL)) > 40 else 10


def _label_size(ctx, labels, width, room, sizes, *, bold=True, heading=False):
    """The first size in `sizes` at which every label fits `width` x `room` with no word broken."""
    least = max([_floor(label) for label in labels] or [10])
    sizes = [size for size in sizes if size >= least] or [least]
    for size in sizes:
        if all(_need(ctx, label, width, size, bold=bold, heading=heading) <= room
               and _whole(ctx, label, width, size, bold=bold, heading=heading) for label in labels):
            return size
    return sizes[-1]


def _tallest(ctx, labels, width, size, *, bold=True, heading=False):
    return max([_need(ctx, label, width, size, bold=bold, heading=heading) for label in labels] or [0.0])


def _figure_size(ctx, values, width, start, floor=14):
    """The largest size up to `start` at which every figure keeps to one line `width` wide: one size a slide."""
    values = [_plain(value, VALUE) for value in values if _plain(value)]
    size = start
    while size > floor and any(_text_lines(value, size, Inches(width), bold=ctx.heading_bold) > 1
                               for value in values):
        size -= 2
    return size


def _figure_tall(size):
    """The height of a one-line figure's box at `size` points (kit.figure sets it at 1.1 leading)."""
    return size * 1.1 / 72 + 0.1


def _fits_tall(room):
    """The largest even size whose one-line figure fits a box `room` inches tall."""
    return int((room * 72 - 5) / 1.1) // 2 * 2


def _unit(section):
    """The chart's unit (its first column), as the classic drawer shows it."""
    unit = columns_of(section)[:1]
    return unit[0] if unit else ''


def _figure_width(ctx, values, size, least=0.8, most=3.0):
    """The narrowest width (inches) from `least` up to `most` that keeps every figure on one line at `size`."""
    values = [_plain(value, VALUE) for value in values if _plain(value)]
    width = least
    while width < most and any(_text_lines(value, size, Inches(width), bold=ctx.heading_bold) > 1
                               for value in values):
        width += 0.05
    return width


def _ranked(ctx, values):
    """A fill (as kit.tones gives them) for each value: the larger the value, the more it stands out on the slide."""
    fills = _vivid(ctx, len(values))
    order = sorted(range(len(values)), key=lambda k: (-values[k], k))
    ranked = [None] * len(values)
    for rank, k in enumerate(order):
        ranked[k] = fills[rank]
    return ranked


def _mark(ctx, ground='surface', least=2.2):
    """The accent for a data mark (a bar, a cap) on the fill role `ground`: a role or a hex colour.

    The accent itself where it shows against `ground` by `least`; otherwise the accent moved until it reads at
    3:1 — a pale yellow deepened to gold on a light deck, a navy lifted on a dark one — since a bar the ground
    swallows (navy on near-black, the classic drawer's case for an outline) no longer shows the figure.
    """
    if contrast_ratio(hex_of(ctx, 'accent'), hex_of(ctx, ground)) >= least:
        return 'accent'
    return readable(ctx, 'accent', ground, 3.0)


def _edge(ctx, ground='surface'):
    """The accent for a thin mark on `ground` (a leader line, a spine, a rule), which needs the full 3:1."""
    return _mark(ctx, ground, 3.0)


def _vivid(ctx, n):
    """kit.tones, the one that stands out most from the slide first: dark to light on a light deck, light to dark
    on a dark one, so the first column never sinks into the ground."""
    return sorted(tones(ctx, n), key=lambda fill: -contrast_ratio(fill['fill'], ctx.roles['surface']))


def _peak(values):
    return max([value for value in values if value > 0] or [1.0])


def _share(value, peak):
    return max(0.0, min(1.0, value / peak)) if peak else 0.0


# ---------------------------------------------------------------- side bars


@variant('chart', 'side_bars')
def side_bars(ctx, section, lines):
    """The heading in a column down the left with the unit as a legend at its foot; on the right each figure is
    an accent bar with a pointed tip, its label above the bar's flat end and its figure large just past the tip."""
    side = 3.55
    x0 = header_side(ctx, section, width=side, size=30, lines=5)
    bars = entries('chart', section)
    values = numbers(bars)
    peak = _peak(values)
    n = len(bars)
    mark = _mark(ctx)
    unit = _unit(section)
    if unit:
        polygon(ctx, chevron_points((LEFT, FOOT - 0.43, 0.26, 0.16), 0.08, notch=False), mark)
        text(ctx, (LEFT + 0.4, FOOT - 0.5, side - 0.4, 0.48), unit, size=12, colour='muted', words=UNIT)
    width = RIGHT - x0
    area_top, area_bottom = 0.95, FOOT - 0.05
    pitch = min(1.15, (area_bottom - area_top) / n)
    bar = max(0.2, min(0.44, pitch * 0.32))
    gap = 0.07
    space = max(0.1, min(0.28, pitch * 0.17))
    room = pitch - bar - gap - space
    labels = [item.get('label') for item in bars]
    # Nothing sits beside a label (each figure is level with its own bar), so a label may run the full width.
    size = _label_size(ctx, labels, width, room, (18, 17, 16, 15, 14, 13, 12))
    room = max(room, _tallest(ctx, labels, width, size))
    # Each figure is level with its bar, in a box no taller than the bar and its two gaps: it never reaches up
    # into the label above it.
    figures = [item.get('value') for item in bars]
    value_h = bar + 2 * gap - 0.02
    fsize = min(_figure_size(ctx, figures, 1.8, 28, floor=14), max(14, _fits_tall(value_h)))
    value_w = _figure_width(ctx, figures, fsize, least=0.6, most=1.8) + 0.05
    area = width - value_w - 0.14
    row = room + gap + bar
    total = n * row + (n - 1) * space
    y = area_top + max(0.0, (area_bottom - area_top - total) / 2)
    for item, value in zip(bars, values):
        text(ctx, (x0, y, width, room), item.get('label'), size=size, floor=_floor(item.get('label')),
             colour='ink', bold=True, anchor='bottom', words=LABEL)
        track = y + room + gap
        length = max(0.14, area * _share(value, peak))
        polygon(ctx, chevron_points((x0, track, length, bar), bar * 0.5, notch=False), mark)
        figure(ctx, (x0 + length + 0.14, track + bar / 2 - value_h / 2, value_w, value_h), item.get('value'),
               size=fsize, colour='accent_text', anchor='middle', words=VALUE, floor=fsize)
        y += row + space


# ---------------------------------------------------------------- peak callout


@variant('chart', 'peak_callout')
def peak_callout(ctx, section, lines):
    """Pale bars with their figures at their ends and the largest bar in the accent, run out by a leader line to
    a callout beside the chart: its figure very large in the accent over its label, on an accent spine."""
    top = header_compact(ctx, section) + 0.1
    bars = entries('chart', section)
    values = numbers(bars)
    peak = _peak(values)
    lead = max(range(len(bars)), key=lambda k: (values[k], -k))
    n = len(bars)
    side = 3.3
    side_x = RIGHT - side
    label_w = 2.35
    bx = LEFT + label_w + 0.2
    value_w = 1.05
    area = side_x - 0.55 - bx - value_w
    area_top, area_bottom = top, FOOT - 0.05
    # Few bars get taller rows rather than a thin strip in the middle of the slide.
    pitch = min(1.0, (area_bottom - area_top) / n)
    labels = [item.get('label') for item in bars]
    size = _label_size(ctx, labels, label_w, pitch - 0.04, (16, 15, 14, 13, 12, 11))
    fsize = min(_figure_size(ctx, [item.get('value') for k, item in enumerate(bars) if k != lead], value_w, 18),
                max(12, _fits_tall(pitch - 0.08)))
    bar = max(0.16, min(0.46, pitch * 0.5))
    mark, edge = _mark(ctx), _edge(ctx)
    y0 = area_top + max(0.0, (area_bottom - area_top - n * pitch) / 2)
    for k, (item, value) in enumerate(zip(bars, values)):
        y = y0 + k * pitch
        text(ctx, (LEFT, y + 0.02, label_w, pitch - 0.04), item.get('label'), size=size,
             floor=_floor(item.get('label')), colour='ink' if k == lead else 'muted', bold=True, align='right',
             anchor='middle', words=LABEL)
        length = max(0.05, area * _share(value, peak))
        rect(ctx, (bx, y + (pitch - bar) / 2, length, bar), mark if k == lead else 'accent_soft')
        if k != lead:
            figure(ctx, (bx + length + 0.12, y + 0.04, value_w, pitch - 0.08), item.get('value'), size=fsize,
                   colour='ink', anchor='middle', words=VALUE, heading=False, bold=True)
    # The callout: the peak's figure, its label and the chart's unit, centred on the peak's row.
    item = bars[lead]
    inner = side - 0.32
    # As large as 72 pt; a three-word figure ('1200 млн руб') comes down until it is one line rather than cut,
    # which a floor of 36 pt did.
    big = _figure_size(ctx, [item.get('value')], inner, 72, floor=20)
    big_h = _figure_tall(big)
    name_size = _label_size(ctx, [item.get('label')], inner, 1.3, (20, 19, 18, 17, 16, 15), heading=True)
    name_h = _need(ctx, item.get('label'), inner, name_size, bold=True, heading=True)
    unit = _unit(section)
    unit_h = _need(ctx, unit, inner, 13) if unit else 0.0
    block_h = big_h + 0.08 + name_h + (0.12 + unit_h if unit else 0.0)
    cy = y0 + lead * pitch + pitch / 2
    by = min(max(cy - big_h / 2 - 0.02, area_top), FOOT - 0.02 - block_h)
    spine_top, spine_bottom = min(by, cy - 0.3), max(by + block_h, cy + 0.3)
    rect(ctx, (side_x, spine_top, 0.07, spine_bottom - spine_top), edge)
    end = bx + max(0.05, area * _share(values[lead], peak))
    line(ctx, (end + 0.1, cy), (side_x - 0.12, cy), edge, 1.5)
    oval(ctx, disc(side_x - 0.1, cy, 0.12), edge)
    figure(ctx, (side_x + 0.32, by, inner, big_h), item.get('value'), size=big, colour='accent_text',
           anchor='middle', words=VALUE, floor=big)
    text(ctx, (side_x + 0.32, by + big_h + 0.08, inner, name_h), item.get('label'), size=name_size,
         floor=min(name_size, 12), colour='ink', bold=True, heading=True, words=LABEL)
    if unit:
        text(ctx, (side_x + 0.32, by + big_h + 0.2 + name_h, inner, unit_h), unit, size=13, colour='muted',
             words=UNIT)


# ---------------------------------------------------------------- histogram


@variant('chart', 'histogram')
def histogram(ctx, section, lines):
    """Columns standing shoulder to shoulder with no gaps, in the accent's tones from the boldest to the palest,
    each figure above its column and each label centred under the baseline; a centred heading with the unit under
    its rule."""
    top = header_center(ctx, section)
    bars = entries('chart', section)
    values = numbers(bars)
    peak = _peak(values)
    n = len(bars)
    unit = _unit(section)
    if unit:
        text(ctx, (LEFT + 1.5, 2.48, WIDTH - 3.0, 0.27), unit, size=12, colour='muted', align='center',
             anchor='middle', words=UNIT)
        top += 0.08
    width = min(1.9, WIDTH / n)
    x0 = LEFT + (WIDTH - n * width) / 2
    labels = [item.get('label') for item in bars]
    label_w = width - 0.14
    size = _label_size(ctx, labels, label_w, 0.82, (16, 15, 14, 13, 12, 11))
    label_h = _tallest(ctx, labels, label_w, size)
    base = FOOT - label_h - 0.14
    fsize = _figure_size(ctx, [item.get('value') for item in bars], width - 0.12, 30 if n <= 5 else 26)
    value_h = _figure_tall(fsize)
    tallest = base - top - value_h - 0.06
    fills = _vivid(ctx, n)
    for k, (item, value, fill) in enumerate(zip(bars, values, fills)):
        x = x0 + k * width
        h = max(0.06, tallest * _share(value, peak))
        rect(ctx, (x, base - h, width, h), fill['fill'])
        figure(ctx, (x + 0.06, base - h - value_h - 0.04, width - 0.12, value_h), item.get('value'), size=fsize,
               colour=fill['text'], align='center', anchor='bottom', words=VALUE, floor=fsize)
        text(ctx, (x + 0.07, base + 0.14, label_w, label_h), item.get('label'), size=size,
             floor=_floor(item.get('label')), colour='ink', bold=True, align='center', words=LABEL)
    start, end = max(LEFT, x0 - 0.2), min(RIGHT, x0 + n * width + 0.2)
    rect(ctx, (start, base, end - start, 0.03), 'ink')


# ---------------------------------------------------------------- scaled circles


@variant('chart', 'scaled_circles', counts=(2, 6))
def scaled_circles(ctx, section, lines):
    """A row of circles standing on a baseline, their areas in scale with their figures and the larger the deeper
    in the accent's tones; the figure inside a circle large enough to hold it, above a smaller one, and the label
    under the line."""
    top = header_number(ctx, section)
    bars = entries('chart', section)
    values = numbers(bars)
    peak = _peak(values)
    n = len(bars)
    unit = _unit(section)
    if unit:
        text(ctx, (LEFT + WIDTH / 2, 2.42, WIDTH / 2, 0.28), unit, size=12, colour='muted', align='right',
             anchor='middle', words=UNIT)
        top += 0.05
    slot = 1.6
    labels = [item.get('label') for item in bars]
    size = _label_size(ctx, labels, slot, 0.62, (16, 15, 14, 13, 12))
    label_h = _tallest(ctx, labels, slot, size)
    under = 0.18
    room = FOOT - top - under - label_h
    figures = [item.get('value') for item in bars]
    fsize = _figure_size(ctx, figures, slot - 0.1, 36 if n <= 3 else 32 if n <= 4 else 28, floor=16)
    value_h = _figure_tall(fsize)
    ratios = [math.sqrt(_share(value, peak)) for value in values]

    def inside(d, value):
        box = inscribed(disc(0, 0, d))
        return (box[3] >= value_h and
                _text_lines(_plain(value, VALUE), fsize, Inches(box[2]), bold=ctx.heading_bold) <= 1)

    def lay(largest):
        sizes = [max(0.2, largest * ratio) for ratio in ratios]
        inner = [inside(d, value) for d, value in zip(sizes, figures)]
        reach = max(d if fits else d + 0.08 + value_h for d, fits in zip(sizes, inner))
        slots = [max(d, slot) for d in sizes]
        return sizes, inner, reach, slots

    largest = min(3.2, room)
    while True:
        sizes, inner, reach, slots = lay(largest)
        if (reach <= room and sum(slots) + 0.3 * (n - 1) <= WIDTH) or largest <= 0.8:
            break
        largest -= 0.05
    # The row and its labels, centred in the room under the heading.
    base = top + max(0.0, (room - reach) / 2) + reach
    gap = min(0.9, (WIDTH - sum(slots)) / max(1, n - 1)) if n > 1 else 0.0
    total = sum(slots) + gap * (n - 1)
    x = LEFT + (WIDTH - total) / 2
    line(ctx, (max(LEFT, x - 0.3), base), (min(RIGHT, x + total + 0.3), base), 'muted', 1.25)
    for item, d, fits, width, fill in zip(bars, sizes, inner, slots, _ranked(ctx, values)):
        cx = x + width / 2
        box = (cx - d / 2, base - d, d, d)
        oval(ctx, box, fill['fill'])
        if fits:
            figure(ctx, inscribed(box), item.get('value'), size=fsize, colour=fill['ink'], align='center',
                   anchor='middle', words=VALUE, floor=fsize)
        else:
            figure(ctx, (x, base - d - 0.08 - value_h, width, value_h), item.get('value'), size=fsize,
                   colour=fill['text'], align='center', anchor='bottom', words=VALUE, floor=fsize)
        text(ctx, (x, base + under, width, label_h), item.get('label'), size=size, floor=_floor(item.get('label')),
             colour='ink', bold=True, align='center', words=LABEL)
        x += width + gap


# ---------------------------------------------------------------- stepped rows


@variant('chart', 'stepped_rows')
def stepped_rows(ctx, section, lines):
    """Zebra rows like a ledger under a full-width accent rule: each row's figure large in the accent at the left,
    its label beside it and an accent bar in scale running on to the right."""
    eyebrow(ctx)
    unit = _unit(section)
    # The heading's last line keeps clear of the full-width rule: its descenders touched it at 0.12 in.
    headline(ctx, section, (LEFT, 0.9, WIDTH - (3.6 if unit else 0.0), 1.02), size=28, lines=2)
    if unit:
        text(ctx, (RIGHT - 3.3, 1.44, 3.3, 0.48), unit, size=12, colour='muted', align='right', anchor='bottom',
             words=UNIT)
    rect(ctx, (LEFT, 2.1, WIDTH, RULE), _edge(ctx))
    top = 2.28
    bars = entries('chart', section)
    values = numbers(bars)
    peak = _peak(values)
    n = len(bars)
    pitch = min(1.2, (FOOT - top) / n)
    figures = [item.get('value') for item in bars]
    fsize = min(_figure_size(ctx, figures, 2.4, 44, floor=18), max(18, _fits_tall(pitch - 0.08)))
    value_w = _figure_width(ctx, figures, fsize, least=1.0, most=2.4)
    label_x = LEFT + 0.28 + value_w + 0.35
    label_w = 3.1
    bar_x = label_x + label_w + 0.3
    area = RIGHT - 0.3 - bar_x
    labels = [item.get('label') for item in bars]
    size = _label_size(ctx, labels, label_w, pitch - 0.08, (17, 16, 15, 14, 13, 12, 11))
    bar = max(0.14, min(0.3, pitch * 0.32))
    # One bar colour for both stripes, held to whichever of them the accent shows on least.
    ground = min(('card', 'surface'), key=lambda role: contrast_ratio(hex_of(ctx, 'accent'), hex_of(ctx, role)))
    mark = _mark(ctx, ground)
    # Few rows are centred in the room under the rule rather than left at its top.
    y0 = top + max(0.0, (FOOT - top - n * pitch) / 2)
    for k, (item, value) in enumerate(zip(bars, values)):
        y = y0 + k * pitch
        colours = inks('card') if k % 2 == 0 else inks('surface')
        if k % 2 == 0:
            rect(ctx, (LEFT, y, WIDTH, pitch), 'card')
        figure(ctx, (LEFT + 0.28, y + 0.04, value_w, pitch - 0.08), item.get('value'), size=fsize,
               colour=colours['accent'], anchor='middle', words=VALUE, floor=fsize)
        text(ctx, (label_x, y + 0.04, label_w, pitch - 0.08), item.get('label'), size=size,
             floor=_floor(item.get('label')), colour=colours['ink'], bold=True, anchor='middle', words=LABEL)
        rect(ctx, (bar_x, y + (pitch - bar) / 2, max(0.05, area * _share(value, peak)), bar), mark)
    # The bars' common start, over the stripes.
    line(ctx, (bar_x, y0), (bar_x, y0 + n * pitch), 'muted', 1.0)


# ---------------------------------------------------------------- capped columns


@variant('chart', 'capped_columns')
def capped_columns(ctx, section, lines):
    """The heading on a strong band; pale accent columns each topped with a thick accent cap and its figure,
    standing on a solid baseline with the labels centred beneath."""
    top = header_band(ctx, section, fill=strong(ctx, ('deep', 'accent')), height=1.5, size=28)
    bars = entries('chart', section)
    values = numbers(bars)
    peak = _peak(values)
    n = len(bars)
    slot = min(2.5, WIDTH / n)
    x0 = LEFT + (WIDTH - n * slot) / 2
    reach = max(LEFT, x0 - 0.3)
    unit = _unit(section)
    if unit:
        text(ctx, (reach, top, WIDTH / 2, 0.3), unit, size=12, colour='muted', anchor='middle', words=UNIT)
        top += 0.3
    width = min(1.3, slot * 0.54)
    labels = [item.get('label') for item in bars]
    label_w = slot - 0.16
    size = _label_size(ctx, labels, label_w, 0.82, (16, 15, 14, 13, 12, 11))
    label_h = _tallest(ctx, labels, label_w, size)
    base = FOOT - label_h - 0.16
    fsize = _figure_size(ctx, [item.get('value') for item in bars], slot - 0.12, 30 if n <= 5 else 26)
    value_h = _figure_tall(fsize)
    cap, lift = 0.16, 0.1
    tallest = base - 0.05 - top - value_h - lift - cap
    mark = _mark(ctx)
    for k, (item, value) in enumerate(zip(bars, values)):
        cx = x0 + (k + 0.5) * slot
        h = tallest * _share(value, peak)
        if h > 0.01:
            rect(ctx, (cx - width / 2, base - h, width, h), 'accent_soft')
        rect(ctx, (cx - width / 2, base - h - cap, width, cap), mark)
        figure(ctx, (cx - slot / 2 + 0.06, base - h - cap - lift - value_h, slot - 0.12, value_h), item.get('value'),
               size=fsize, colour='ink', align='center', anchor='bottom', words=VALUE, floor=fsize)
        text(ctx, (cx - label_w / 2, base + 0.16, label_w, label_h), item.get('label'), size=size,
             floor=_floor(item.get('label')), colour='ink', bold=True, align='center', words=LABEL)
    rect(ctx, (reach, base, min(RIGHT, x0 + n * slot + 0.3) - reach, 0.05), 'ink')
