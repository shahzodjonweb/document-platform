"""Statement variants: the one sentence set large in the heading face, carried by a single strong mark."""
import math

from . import variant
from ..slides import contrast_ratio
from .kit import (FOOT, LEFT, RIGHT, RULE, WIDTH, body_text, disc, eyebrow, figure, headline, height, hex_of, inks,
                  inscribed, on, oval, parallelogram_points, polygon, rect, ring, rounded, rule, strong, text, tones)

SPACING = 1.14    # the statement's leading, as the classic drawer sets it
LEADING = 1.08    # a headline's leading (slides._headline)
SLACK = 0.06      # what a fitted box needs beyond its lines (3 pt, and a little)
TOP = 0.95        # below the eyebrow
SIZES = (44, 40, 36, 32, 30, 28)


# ---------------------------------------------------------------- measuring


def _line(section, lines):
    """The statement: the slide's first line, or its body."""
    return lines[0] if lines else body_text(section)


def _size(ctx, value, width, room, *, sizes=SIZES, most=4, least=32):
    """(size, inches): the largest statement size that keeps to `most` lines and `room` inches.

    A statement that would need less than `least` points to keep to `most` lines takes one line more (at any of
    `sizes`), then as many as fit: a long Russian line set at 28 pt to save a line read as body text, smaller
    than the classic drawer's 32.
    """
    for limit in (most, most + 1, 99):
        for size in sizes:
            if limit == most and size < least:
                continue
            tall = height(ctx, value, width, size, heading=True, spacing=SPACING)
            if tall + SLACK <= room and tall <= limit * size * SPACING / 72 + 1e-6:
                return size, tall + SLACK
    size = sizes[-1]
    return size, min(room, height(ctx, value, width, size, heading=True, spacing=SPACING) + SLACK)


def _shows(ctx, colour, ground):
    """Whether `colour` stands out from `ground` (roles or hex): by lightness, or by hue where they are alike in it.

    Orange beside blue is plain to see at a contrast ratio near 1; navy on near-black is not.
    """
    one, other = hex_of(ctx, colour), hex_of(ctx, ground)
    if contrast_ratio(one, other) >= 1.8:
        return True
    channels = lambda value: [int(value[k:k + 2], 16) for k in (0, 2, 4)]
    return math.dist(channels(one), channels(other)) >= 150


def _mark(ctx, ground='surface'):
    """The colour of a rule, bar or disc on `ground`: the accent, or its readable form where it fades into the ground.

    A dark accent on a dark deck (navy on near-black) is nearly the ground itself.
    """
    if _shows(ctx, 'accent', ground):
        return 'accent'
    return 'accent_text' if ground == 'surface' else inks(ground)['accent']


def _say(ctx, box, value, size, *, colour='ink', align='left', anchor='top'):
    text(ctx, box, value, size=size, floor=24, colour=colour, heading=True, spacing=SPACING, align=align,
         anchor=anchor)


def _heading(section, upper=False):
    value = ' '.join(str(section.get('heading') or '').split()[:14])
    return value.upper() if upper else value


def _head(ctx, section, width, size, lines=2, *, upper=False):
    """(size, inches) the heading takes as kit.headline sets it in a box `width` wide."""
    value = _heading(section, upper)
    if not value:
        return size, 0.0
    while size > 18 and height(ctx, value, width, size, heading=True, spacing=1) > lines * size / 72 + 1e-6:
        size -= 2
    return size, height(ctx, value, width, size, heading=True, spacing=LEADING) + SLACK


def _kicker(ctx, section, box, size, *, colour='accent_text', align='left', anchor='top', lines=3, upper=False):
    """The heading, small, as a kicker over (or under) the statement."""
    if not box[3]:
        return
    # Capitals are set before kit.headline clips, so a heading cut to its 14 words still marks the slide.
    source = {**section, 'heading': str(section.get('heading') or '').upper()} if upper else section
    headline(ctx, source, box, size=size, lines=lines, anchor=anchor, align=align, colour=colour)


# ---------------------------------------------------------------- variants


@variant('statement', 'band')
def band(ctx, section, lines):
    """The statement in the heading face on a full-width strong band across the middle; the heading small above it."""
    value = _line(section, lines)
    panel = inks(strong(ctx))
    eyebrow(ctx)
    pad_x, pad_y = 0.75, 0.5
    width = WIDTH - 2 * pad_x
    size, tall = _size(ctx, value, width, 3.4, sizes=(40, 36, 32, 30, 28), most=3)
    inner = RULE + 0.3 + tall
    deep = max(2.2, inner + 2 * pad_y)
    head_size, head_tall = _head(ctx, section, WIDTH - 2.5, 20)
    gap = 0.28 if head_tall else 0
    group = head_tall + gap + deep
    top = TOP + max(0.0, (FOOT - TOP - group) / 2 - 0.1)
    _kicker(ctx, section, (LEFT, top, WIDTH - 2.5, head_tall), head_size, anchor='bottom')
    y = top + head_tall + gap
    rect(ctx, (LEFT, y, WIDTH, deep), panel['fill'])
    edge = _edge(ctx, panel['fill'])
    if edge:
        rect(ctx, (LEFT, y, 0.16, deep), edge)
    y += (deep - inner) / 2
    rect(ctx, (LEFT + pad_x, y, 0.7, RULE), panel['ink'])
    # Centred in its box: a line the estimate wrapped and the viewer did not leaves even space, not a gap below.
    _say(ctx, (LEFT + pad_x, y + RULE + 0.3, width, tall), value, size, colour=panel['ink'], anchor='middle')


def _edge(ctx, fill):
    """The band's coloured edge: the accent, else the second colour, whichever shows on the band; else none."""
    for role in ('accent', 'secondary'):
        if role != fill and _shows(ctx, role, fill):
            return role
    return None


@variant('statement', 'centred')
def centred(ctx, section, lines):
    """The statement centred and large under a short accent rule; the heading small and muted below it."""
    value = _line(section, lines)
    eyebrow(ctx, (LEFT, 0.62, WIDTH, 0.3), align='center')
    width = 9.8
    x = LEFT + (WIDTH - width) / 2
    size, tall = _size(ctx, value, width, 3.8)
    head_width = 8.0
    head_size, head_tall = _head(ctx, section, head_width, 18)
    gap = 0.38 if head_tall else 0
    group = RULE + 0.42 + tall + gap + head_tall
    top = TOP + (FOOT - TOP - group) / 2
    rule(ctx, (LEFT + WIDTH / 2 - 0.5, top, 1.0, RULE * 1.5), colour=_mark(ctx))
    y = top + RULE + 0.42
    _say(ctx, (x, y, width, tall), value, size, align='center', anchor='middle')
    _kicker(ctx, section, (LEFT + (WIDTH - head_width) / 2, y + tall + gap, head_width, head_tall), head_size,
            colour='muted', align='center')


@variant('statement', 'left_bar')
def left_bar(ctx, section, lines):
    """A thick accent bar down the left; the statement large beside it under the heading as a capitals kicker."""
    value = _line(section, lines)
    eyebrow(ctx)
    x = LEFT + 0.62
    width = 9.9
    size, tall = _size(ctx, value, width, 4.0)
    head_size, head_tall = _head(ctx, section, width, 16, upper=True)
    gap = 0.3 if head_tall else 0
    group = head_tall + gap + tall
    top = TOP + (FOOT - TOP - group) / 2
    rect(ctx, (LEFT, top - 0.08, 0.2, group + 0.16), _mark(ctx))
    _kicker(ctx, section, (x, top, width, head_tall), head_size, upper=True)
    _say(ctx, (x, top + head_tall + gap, width, tall), value, size)


@variant('statement', 'split')
def split(ctx, section, lines):
    """The heading muted in a narrow left column with the eyebrow; the statement large across the right two thirds."""
    value = _line(section, lines)
    column = 3.15
    divider = LEFT + column + 0.42
    x = divider + 0.5
    width = RIGHT - x
    size, tall = _size(ctx, value, width, 4.8, sizes=(40, 36, 32, 30, 28))
    head_size, head_tall = _head(ctx, section, column, 22, lines=5)
    left = 0.3 + 0.18 + RULE + 0.22 + head_tall
    group = max(left, tall)
    top = TOP + (FOOT - TOP - group) / 2
    mark = _mark(ctx)
    eyebrow(ctx, (LEFT, top, column, 0.3))
    rule(ctx, (LEFT, top + 0.48, 0.7, RULE), colour=mark)
    _kicker(ctx, section, (LEFT, top + 0.48 + RULE + 0.22, column, head_tall), head_size, colour='muted', lines=5)
    rect(ctx, (divider, top - 0.2, 0.03, group + 0.4), mark)
    _say(ctx, (x, top + (group - tall) / 2, width, tall), value, size, anchor='middle')


@variant('statement', 'disc_mark')
def disc_mark(ctx, section, lines):
    """A large accent disc at the left holding the slide's number in a ring; the statement beside it."""
    value = _line(section, lines)
    diameter = 3.0
    cx, cy = LEFT + 0.3 + diameter / 2, TOP + (FOOT - TOP) / 2 + 0.05
    fill = _mark(ctx)
    ink = 'on_accent' if fill == 'accent' else on(hex_of(ctx, fill))
    ring(ctx, disc(cx, cy, diameter + 0.5), fill, width=1.25)
    shape = disc(cx, cy, diameter)
    oval(ctx, shape, fill)
    # The number and its '/ 12' as one group centred on the disc, with air between them.
    inner = inscribed(shape, 0.64)
    figure(ctx, (inner[0], cy - 0.86, inner[2], 1.2), f'{ctx.index + 1:02d}', size=72, colour=ink, align='center',
           anchor='bottom')
    text(ctx, (inner[0], cy + 0.42, inner[2], 0.32), f'/ {ctx.total:02d}', size=14, colour=ink, bold=True,
         align='center')
    x = cx + diameter / 2 + 0.25 + 0.65
    width = RIGHT - x
    size, tall = _size(ctx, value, width, 4.6, sizes=(40, 36, 32, 30, 28))
    head_size, head_tall = _head(ctx, section, width, 20)
    gap = 0.3 if head_tall else 0
    group = head_tall + gap + tall
    top = cy - group / 2
    _kicker(ctx, section, (x, top, width, head_tall), head_size)
    _say(ctx, (x, top + head_tall + gap, width, tall), value, size)


@variant('statement', 'framed')
def framed(ctx, section, lines):
    """The statement centred inside an outlined frame, with solid accent squares on two of its corners."""
    value = _line(section, lines)
    square = 0.34
    x0, y0 = LEFT + square / 2 + 0.02, 0.62 + square / 2 + 0.04
    w, h = RIGHT - square / 2 - 0.02 - x0, FOOT - square / 2 - 0.02 - y0
    rect(ctx, (x0, y0, w, h), None, line='accent_text', line_width=1.25)
    rect(ctx, (x0 - square / 2, y0 - square / 2, square, square), _mark(ctx))
    rect(ctx, (x0 + w - square / 2, y0 + h - square / 2, square, square), _mark(ctx))
    width = w - 2.0
    x = x0 + (w - width) / 2
    size, tall = _size(ctx, value, width, 3.4, sizes=(40, 36, 32, 30, 28))
    head_size, head_tall = _head(ctx, section, width - 1.0, 18)
    group = 0.3 + 0.3 + head_tall + (0.22 + RULE + 0.32 if head_tall else 0.1) + tall
    top = y0 + (h - group) / 2
    eyebrow(ctx, (x, top, width, 0.3), align='center')
    y = top + 0.6
    if head_tall:
        _kicker(ctx, section, (x + 0.5, y, width - 1.0, head_tall), head_size, align='center')
        y += head_tall + 0.22
        rule(ctx, (x + width / 2 - 0.4, y, 0.8, RULE), colour=_mark(ctx))
        y += RULE + 0.32
    else:
        y += 0.1
    _say(ctx, (x, y, width, tall), value, size, align='center')


@variant('statement', 'underlined')
def underlined(ctx, section, lines):
    """The heading at the top; the statement large below with a long accent bar just under its last line."""
    value = _line(section, lines)
    eyebrow(ctx)
    head_size, head_tall = _head(ctx, section, WIDTH - 1.5, 26)
    headline(ctx, section, (LEFT, 0.95, WIDTH - 1.5, max(head_tall, 0.5)), size=head_size, lines=2, anchor='top')
    start = 0.95 + head_tall + 0.3
    width = 10.4
    size, tall = _size(ctx, value, width, FOOT - start - 0.5)
    group = tall + 0.12 + 0.12
    top = start + max(0.0, (FOOT - start - group) / 2 - 0.15)
    # Set to the foot of its box, so the last line sits on the bar even when the viewer wraps a line fewer than
    # the (deliberately wide) estimate counted.
    _say(ctx, (LEFT, top, width, tall), value, size, anchor='bottom')
    y = top + tall + 0.12
    rect(ctx, (LEFT, y, 4.6, 0.12), _mark(ctx))
    rect(ctx, (LEFT + 4.75, y + 0.05, RIGHT - LEFT - 4.75, 0.02), 'accent_soft')


@variant('statement', 'soft_panel')
def soft_panel(ctx, section, lines):
    """The heading over a large rounded panel in the soft accent; the statement centred on the panel."""
    value = _line(section, lines)
    eyebrow(ctx)
    head_size, head_tall = _head(ctx, section, WIDTH - 2.0, 28)
    headline(ctx, section, (LEFT, 0.95, WIDTH - 2.0, max(head_tall, 0.5)), size=head_size, lines=2, anchor='top')
    y = 0.95 + max(head_tall, 0.5) + 0.25
    deep = FOOT - y
    rounded(ctx, (LEFT, y, WIDTH, deep), 'accent_soft', radius=0.3)
    width = WIDTH - 2.2
    x = LEFT + (WIDTH - width) / 2
    size, tall = _size(ctx, value, width, deep - 1.4, sizes=(40, 36, 32, 30, 28))
    group = RULE * 1.5 + 0.4 + tall
    top = y + (deep - group) / 2
    rule(ctx, (LEFT + WIDTH / 2 - 0.45, top, 0.9, RULE * 1.5), colour=_mark(ctx, 'accent_soft'))
    _say(ctx, (x, top + RULE * 1.5 + 0.4, width, tall), value, size, colour='soft_ink', align='center')


@variant('statement', 'stripes')
def stripes(ctx, section, lines):
    """A block of slanted stripes in the accent's tones down the left third; the statement on the right."""
    value = _line(section, lines)
    block = 3.4
    n, gap = 6, 0.14
    top, bottom = 0.8, FOOT - 0.2
    tall_stripe = (bottom - top - gap * (n - 1)) / n
    slant = 0.42
    for k, tone in enumerate(tones(ctx, n)):
        y = top + k * (tall_stripe + gap)
        polygon(ctx, parallelogram_points((LEFT, y, block, tall_stripe), slant), tone['fill'])
    x = LEFT + block + 0.75
    width = RIGHT - x
    size, tall = _size(ctx, value, width, 4.3, sizes=(40, 36, 32, 30, 28))
    head_size, head_tall = _head(ctx, section, width, 20)
    group = 0.3 + 0.2 + head_tall + (0.2 + RULE + 0.34 if head_tall else 0) + tall
    y = TOP - 0.2 + (FOOT - TOP + 0.2 - group) / 2
    eyebrow(ctx, (x, y, 3.2, 0.3))
    y += 0.5
    if head_tall:
        _kicker(ctx, section, (x, y, width, head_tall), head_size, colour='muted')
        y += head_tall + 0.2
        rule(ctx, (x, y, 0.9, RULE), colour=_mark(ctx))
        y += RULE + 0.34
    _say(ctx, (x, y, width, tall), value, size)


@variant('statement', 'numeral')
def numeral(ctx, section, lines):
    """The slide's number huge in the accent at the top left, the heading beside it; the statement large below."""
    value = _line(section, lines)
    figure(ctx, (LEFT, 0.66, 1.9, 1.3), f'{ctx.index + 1:02d}', size=72, colour='accent_text', anchor='middle')
    middle = 0.66 + 1.3 / 2
    x = LEFT + 2.35
    head_size, head_tall = _head(ctx, section, RIGHT - x, 22)
    total = f'/ {ctx.total:02d}'
    if head_tall:
        # The '/ 12' over the heading, the pair centred on the numeral and the bar between them.
        rect(ctx, (LEFT + 2.0, middle - 0.45, 0.04, 0.9), _mark(ctx))
        y = middle - (0.28 + head_tall) / 2
        text(ctx, (x, y, 3.0, 0.24), total, size=10, colour='muted', bold=True)
        _kicker(ctx, section, (x, y + 0.28, RIGHT - x, head_tall), head_size, colour='muted', lines=2)
    else:
        text(ctx, (x, middle - 0.12, 3.0, 0.24), total, size=10, colour='muted', bold=True)
    rect(ctx, (LEFT, 2.16, WIDTH, 0.014), 'accent_soft')
    start = 2.16
    width = 10.6
    room = FOOT - start - 0.5
    size, _ = _size(ctx, value, width, room)
    # The whole room, the line centred in it: exact whatever the viewer's wrapping.
    _say(ctx, (LEFT, start + 0.25, width, room), value, size, anchor='middle')
