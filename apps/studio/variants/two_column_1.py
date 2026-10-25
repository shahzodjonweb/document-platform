"""Two-column variants: the two titled columns as split panels, joined cards, numerals, rows and staggered cards."""
from pptx.util import Inches

from ..slide_layouts import _paragraph_height, _text_lines
from . import titled, variant
from .kit import (FOOT, LEFT, RIGHT, RULE, WIDTH, Z, badge, block, eyebrow, figure, header_center, header_compact,
                  header_number, headline, hues, inks, line, on, oval, readable, rect, rule, strong, text)

ACCEPTS = lambda section, lines: titled(section) is not None  # noqa: E731

# (title, text) point sizes, largest first: a slide takes the first at which both columns fit.
SCALES = ((20, 16), (20, 15), (19, 15), (18, 14), (18, 13), (17, 13), (16, 12))
SPACING = 1.25    # the columns' leading
LABEL, BODY = 8, 60   # the classic drawer's word limits


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
    """The first (title, text) sizes at which `fits(sizes)` holds; the smallest if none does."""
    for sizes in scales:
        if fits(sizes):
            return sizes
    return scales[-1]


def _title(item, size, *, colour='accent_text', align='left', after=0):
    return dict(text=item['label'], words=LABEL, size=size, floor=min(size, 15), colour=colour, bold=True,
                heading=True, spacing=1.1, after=after, align=align)


def _body(item, size, *, colour='ink', align='left'):
    return dict(text=item['text'], words=BODY, size=size, floor=12, colour=colour, spacing=SPACING, align=align)


def _column(item, sizes, *, title='accent_text', body='ink', align='left', after=9):
    """A column's title and text as kit.block paragraphs."""
    return [_title(item, sizes[0], colour=title, align=align, after=after),
            _body(item, sizes[1], colour=body, align=align)]


def _centred(top, room, used, bias=0.42):
    """Where content `used` inches tall starts in `room` inches below `top`: a little above the middle."""
    return top + max(0.0, (room - used) * bias)


def _lines(text_value, size, width):
    """How many lines a column's text (held to its word limit) wraps to at `size` in `width` inches."""
    return _text_lines(_clean(text_value, BODY), size, Inches(width))


def _visible(ctx, colour, ground):
    """`colour` (a role or hex) moved until it stands out as a shape on `ground`.

    The deck's accent fills a mark that carries the slide (the join disc, the
    corner blocks); a navy accent on a dark deck, or a pale one on a light
    deck, all but vanishes into the ground, so it is lifted or deepened in its
    own hue until it shows.
    """
    return readable(ctx, colour, ground, 2.4)


def _plus(ctx, cx, cy, span, colour):
    """A plus sign of two crossed bars centred at (cx, cy), `span` inches across."""
    bar = span * 0.24
    rect(ctx, (cx - span / 2, cy - bar / 2, span, bar), colour)
    rect(ctx, (cx - bar / 2, cy - span / 2, bar, span), colour)


# ---------------------------------------------------------------- 1. split panels


@variant('two_column', 'split_panels', accepts=ACCEPTS)
def split_panels(ctx, section, lines):
    """One wide block split down the middle: the first column on a strong panel, the second on a card panel."""
    pair = titled(section)
    top = header_compact(ctx, section) + 0.1
    room = FOOT - top
    half = WIDTH / 2
    pad_x, pad_y, mark = 0.5, 0.42, 0.42
    inner = half - 2 * pad_x
    dark, light = inks(strong(ctx)), inks('card')
    styles = ((dark, dark['ink'], dark['muted']), (light, light['accent'], light['ink']))

    def column(k, sizes):
        return _column(pair[k], sizes, title=styles[k][1], body=styles[k][2])
    budget = room - 2 * pad_y - mark
    sizes = _choose(lambda s: all(_need(ctx, inner, column(k, s)) <= budget for k in range(2)))
    tallest = max(_need(ctx, inner, column(k, sizes)) for k in range(2))
    tall = min(room, max(3.1, tallest + 2 * pad_y + mark))
    y = _centred(top, room, tall, bias=0.5)
    # Brief columns sit in the middle of their panels, both at the same height.
    start = y + pad_y + max(0.0, (tall - 2 * pad_y - mark - tallest) / 2)
    for k in range(2):
        paint = styles[k][0]
        x = LEFT + k * half
        rect(ctx, (x, y, half, tall), paint['fill'])
        text(ctx, (x + pad_x, start - 0.06, 0.5, 0.3), f'{k + 1:02d}', size=12, colour=paint['muted'],
             bold=True, anchor='middle')
        rect(ctx, (x + pad_x + 0.55, start + 0.09 - RULE / 2, 0.7, RULE), paint['accent'])
        block(ctx, (x + pad_x, start + mark, inner, y + tall - pad_y - start - mark), column(k, sizes))


# ---------------------------------------------------------------- 2. plus join


@variant('two_column', 'plus_join', accepts=ACCEPTS)
def plus_join(ctx, section, lines):
    """Two card panels side by side, joined by an accent disc holding a plus sign that bridges the gap."""
    pair = titled(section)
    header_number(ctx, section)
    top = 2.5
    room = FOOT - top
    gap, size, halo = 0.5, 0.92, 1.1
    width = (WIDTH - gap) / 2
    pad, near = 0.42, 0.55          # the side nearest the disc keeps clear of it
    inner = width - pad - near
    card = inks('card')

    def column(k, sizes):
        return _column(pair[k], sizes, title=card['accent'], body=card['ink'])
    budget = room - 2 * pad
    sizes = _choose(lambda s: all(_need(ctx, inner, column(k, s)) <= budget for k in range(2)))
    tallest = max(_need(ctx, inner, column(k, sizes)) for k in range(2))
    tall = min(room, max(2.6, tallest + 2 * pad))
    y = _centred(top, room, tall)
    start = y + pad + max(0.0, (tall - 2 * pad - tallest) / 2)
    for k in range(2):
        x = LEFT + k * (width + gap)
        rect(ctx, (x, y, width, tall), card['fill'])
        left = x + (pad if k == 0 else near)
        block(ctx, (left, start, inner, y + tall - pad - start), column(k, sizes))
    cx, cy = LEFT + WIDTH / 2, y + tall / 2
    fill = _visible(ctx, 'accent', 'surface')
    oval(ctx, (cx - halo / 2, cy - halo / 2, halo, halo), 'surface')
    oval(ctx, (cx - size / 2, cy - size / 2, size, size), fill)
    _plus(ctx, cx, cy, size * 0.44, on(fill))


# ---------------------------------------------------------------- 3. numbered


@variant('two_column', 'numbered', accepts=ACCEPTS)
def numbered(ctx, section, lines):
    """Large accent numerals 01 and 02 over the columns, each with a short rule, its title and text; no panels."""
    pair = titled(section)
    eyebrow(ctx)
    headline(ctx, section, (LEFT, 0.92, WIDTH, 0.98), size=28, lines=2)
    top = 2.1
    gap = 0.9
    width = (WIDTH - gap) / 2
    numeral, under = 0.9, 0.5
    room = FOOT - top - numeral - under

    def column(k, sizes):
        return _column(pair[k], sizes, title='ink', body='muted')
    sizes = _choose(lambda s: all(_need(ctx, width, column(k, s)) <= room for k in range(2)))
    tallest = max(_need(ctx, width, column(k, sizes)) for k in range(2))
    y = _centred(top, room, tallest)
    for k in range(2):
        x = LEFT + k * (width + gap)
        figure(ctx, (x, y, 2.2, numeral), f'{k + 1:02d}', size=60, colour='accent_text', anchor='bottom')
        rule(ctx, (x, y + numeral + 0.24, 0.7, RULE))
        start = y + numeral + under
        block(ctx, (x, start, width, FOOT - start), column(k, sizes))
    middle = LEFT + width + gap / 2
    line(ctx, (middle, y + 0.15), (middle, y + numeral + under + tallest), 'accent_soft', 1.0)


# ---------------------------------------------------------------- 4. stacked rows


@variant('two_column', 'stacked_rows', accepts=ACCEPTS)
def stacked_rows(ctx, section, lines):
    """The columns as two full-width rows: numeral and title in the left third, text in the rest, a hairline between."""
    pair = titled(section)
    top = header_compact(ctx, section) + 0.2
    room = FOOT - top
    third = WIDTH / 3
    mark = 0.7                      # the numeral's own column
    lead = third - mark - 0.3       # the title's width
    width = WIDTH - third
    gap = 0.5

    def heights(sizes):
        return [max(0.5, _need(ctx, lead, [_title(item, sizes[0], colour='ink')]),
                    _need(ctx, width, [_body(item, sizes[1])])) for item in pair]
    sizes = _choose(lambda s: sum(heights(s)) + gap <= room)
    rows = heights(sizes)
    share = (room - gap) / 2
    even = max(rows) <= share       # each row in the middle of its half of the room
    y = top if even else top + max(0.0, (room - sum(rows) - gap) / 2)
    for k, item in enumerate(pair):
        h = rows[k]
        start = y + (share - h) / 2 if even else y
        text(ctx, (LEFT, start - 0.05, mark, 0.5), f'{k + 1:02d}', size=24, colour='accent_text', bold=True,
             heading=True)
        block(ctx, (LEFT + mark, start, lead, h), [_title(item, sizes[0], colour='ink')])
        block(ctx, (LEFT + third, start, width, h), [_body(item, sizes[1])])
        y = y + share if even else start + h
        if k == 0:
            line(ctx, (LEFT, y + gap / 2), (RIGHT, y + gap / 2), 'muted', 0.75)
            y += gap


# ---------------------------------------------------------------- 5. centred header


@variant('two_column', 'centred_header', accepts=ACCEPTS)
def centred_header(ctx, section, lines):
    """A centred heading over two columns whose titles are centred under a short rule; the text set left below."""
    pair = titled(section)
    # The columns' rules start well below the heading's own, not stacked just under it.
    top = header_center(ctx, section) + 0.07
    room = FOOT - top
    gap = 0.9
    width = (WIDTH - gap) / 2
    lead = 0.3                      # the rule over each title

    def column(k, sizes, align='left'):
        return [_title(pair[k], sizes[0], colour='ink', align='center', after=11),
                _body(pair[k], sizes[1], align=align)]
    budget = room - lead
    sizes = _choose(lambda s: all(_need(ctx, width, column(k, s)) <= budget for k in range(2)))
    tallest = max(_need(ctx, width, column(k, sizes)) for k in range(2))
    # A line or two of text is centred under its title; a paragraph is set left, where it reads.
    align = 'center' if all(_lines(item['text'], sizes[1], width) <= 2 for item in pair) else 'left'
    y = _centred(top, budget, tallest)
    for k in range(2):
        x = LEFT + k * (width + gap)
        rect(ctx, (x + width / 2 - 0.3, y, 0.6, RULE), 'accent')
        block(ctx, (x, y + lead, width, FOOT - y - lead), column(k, sizes, align))


# ---------------------------------------------------------------- 6. offset cards


@variant('two_column', 'offset_cards', accepts=ACCEPTS)
def offset_cards(ctx, section, lines):
    """Two cards, the second set lower, each with a numbered colour block on its top-left corner beside its title."""
    pair = titled(section)
    top = header_compact(ctx, section) + 0.12     # the first block's top, clear of the heading's rule
    card = inks('card')
    hang, square = 0.16, 0.8        # the corner block overhangs the card by `hang`
    gap, drop = 0.42, 0.38
    width = (WIDTH - hang - gap) / 2
    head = square - hang            # the block's part on the card: the title row beside it
    # Title and text share one left edge, right of the block, so the text runs on under the title
    # however tall the block is.
    indent, pad = head + 0.24, 0.38
    inner = width - indent - pad
    under = 0.12                    # between the title and the text
    room = FOOT - top - hang - drop

    def title(k, sizes):
        return _title(pair[k], sizes[0], colour=card['accent'])

    def body(k, sizes):
        return _body(pair[k], sizes[1], colour=card['ink'])

    def lift(k, sizes):
        """The title's top below the card's: level with the numeral when it is one line, else near the edge."""
        return max(0.06, head / 2 - 0.04 - _need(ctx, inner, [title(k, sizes)]) / 2)

    def need(k, sizes):
        return (lift(k, sizes) + _need(ctx, inner, [title(k, sizes)]) + under
                + _need(ctx, inner, [body(k, sizes)]) + pad)
    sizes = _choose(lambda s: all(need(k, s) <= room for k in range(2)))
    tall = min(room, max(1.8, max(need(k, sizes) for k in range(2))))
    y = _centred(top + hang, room, tall)
    fills = [_visible(ctx, paint['fill'], 'card') for paint in hues(ctx, 2)]
    for k in range(2):
        x = LEFT + hang + k * (width + gap)
        cy = y + k * drop
        rect(ctx, (x, cy, width, tall), card['fill'])
        badge(ctx, (x - hang, cy - hang, square, square), f'{k + 1:02d}', fill=fills[k], ink=on(fills[k]),
              shape='rect', size=20, heading=True)
        tall_title = _need(ctx, inner, [title(k, sizes)])
        title_top = cy + lift(k, sizes)
        block(ctx, (x + indent, title_top, inner, tall_title), [title(k, sizes)])
        start = title_top + tall_title + under
        block(ctx, (x + indent, start, inner, cy + tall - start - 0.1), [body(k, sizes)])
