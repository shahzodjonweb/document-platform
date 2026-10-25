"""Two-column variants: the two titled columns side by side or stacked, each title set off by a tint, tab or rule."""
from .. import slides as base
from . import titled, variant
from .kit import (FOOT, LEFT, RIGHT, RULE, TOP, WIDTH, badge, block, disc, eyebrow, figure, header, header_band,
                  header_number, header_side, headline, height, hues, inks, on, polygon, readable, rect, ring, rule,
                  strong, tab_points)

SPACING = 1.22         # running text's leading (slides.LINE_MULTIPLE), as the classic drawer sets it
LABEL, WORDS = 8, 60   # the classic drawer's word limits: a column's title and its text
SLACK = 4 / 72         # what a fitted box needs beyond its lines (3 pt, and a little)
LIFT = 0.42            # short content sits this share of the spare room down: a little above the middle


def _accepts(section, lines):
    return titled(section) is not None


# ---------------------------------------------------------------- measuring


def _words(value, limit):
    """`value` held to `limit` words, as kit.clip holds it (without marking the slide)."""
    parts = str(value or '').split()
    return ' '.join(parts) if len(parts) <= limit else ' '.join(parts[:limit]).rstrip(',;:.') + '…'


def _title_tall(ctx, item, width, size):
    return height(ctx, _words(item['label'], LABEL), width, size, bold=True, heading=True) + SLACK


def _text_tall(ctx, item, width, size):
    return height(ctx, _words(item['text'], WORDS), width, size, spacing=SPACING) + SLACK


def _sizes(ctx, holds, title=(20, 16), body=(16, 12)):
    """The largest (title, text) sizes, in points, at which `holds(title, text)`.

    The text steps down half a point at a time; at each step the title tries
    four points above it, then less, but never under two points above, so a
    title that would wrap gives way before the text does. Both columns of one
    slide always share their sizes.
    """
    size = body[0]
    while size >= body[1]:
        top = max(title[1], min(title[0], int(size + 4)))
        while top >= max(title[1], size + 2):
            if holds(top, size):
                return top, size
            top -= 1
        size -= 0.5
    return title[1], body[1]


def _title(item, size, colour, **extra):
    return dict(text=item['label'], words=LABEL, size=size, floor=size, colour=colour, bold=True, heading=True,
                **extra)


def _text(item, size, colour, **extra):
    return dict(text=item['text'], words=WORDS, size=size, floor=min(12, size), colour=colour, spacing=SPACING,
                **extra)


def _headline_lines(ctx, section, width, size, fewest=3, most=5):
    """(lines, inches) for kit.headline in a box `width` wide: the fewest lines from `fewest` to `most` that the
    heading keeps to at `size` or smaller (to 18 pt), and the height it then takes."""
    value = _words(section.get('heading'), 14)

    def lines(points):
        return round(height(ctx, value, width, points, heading=True, spacing=1.08) / (points * 1.08 / 72))
    for allowed in range(fewest, most + 1):
        points = size
        while points > 18 and lines(points) > allowed:
            points -= 2
        if lines(points) <= allowed or allowed == most:
            return allowed, min(allowed, lines(points)) * points * 1.08 / 72


def _settle(top, room, tall):
    """Where content `tall` inches high starts in `room` below `top`: a little above the middle."""
    return top + max(0.0, (room - tall) * LIFT)


def _mark(ctx, ground, target=2.2):
    """The accent made to stand out on `ground` (a role), for a rule or a line beside text."""
    return readable(ctx, 'accent', ground, target)


def _soft(ctx, target=1.5):
    """The soft accent made just visible on the surface, for a hairline or an outline."""
    return readable(ctx, 'accent_soft', 'surface', target)


def _lifted(ctx, paint, target=1.8):
    """A kit.hues fill that stands off a dark ground: a deep accent on a dark deck is lightened until it shows.

    On a light ground a pale hue still shows by its colour, so it is kept.
    """
    surface = ctx.roles['surface']
    if base._luminance(surface) > 0.18 or base.contrast_ratio(paint['fill'], surface) >= target:
        return paint
    fill = readable(ctx, paint['fill'], 'surface', target)
    ink = on(fill)
    return {'fill': fill, 'ink': ink, 'muted': ink, 'text': readable(ctx, fill, 'surface', 4.5)}


# ---------------------------------------------------------------- variants


@variant('two_column', 'tinted_halves', accepts=_accepts)
def tinted_halves(ctx, section, lines):
    """The frame split down the middle: the heading and first column on a full-height tint, the second beside it."""
    pair = titled(section)
    half, pad = WIDTH / 2, 0.5
    width = half - 2 * pad
    soft = inks('accent_soft')
    rect(ctx, (LEFT, 0.62, half, FOOT - 0.62), 'accent_soft')
    eyebrow(ctx, (LEFT + pad, 0.9, width, 0.3), colour=soft['muted'])
    # Three lines at most for a usual heading; a long one takes more lines rather than losing words.
    count, tall = _headline_lines(ctx, section, width, 30)
    headline(ctx, section, (LEFT + pad, 1.22, width, tall + 0.1), size=30, lines=count, anchor='top',
             colour=soft['ink'])
    # Both columns start level, under the heading however many lines it takes.
    top = max(2.45, 1.22 + tall + 0.42)
    room = FOOT - 0.4 - top
    rise = 0.1 + RULE + 0.2   # title to rule to text

    def holds(title, size):
        return (max(_title_tall(ctx, item, width, title) for item in pair)
                + rise + max(_text_tall(ctx, item, width, size) for item in pair)) <= room
    title, size = _sizes(ctx, holds)
    head = max(_title_tall(ctx, item, width, title) for item in pair)
    body = max(_text_tall(ctx, item, width, size) for item in pair)
    y = _settle(top, room, head + rise + body)
    for k, item in enumerate(pair):
        ground = 'accent_soft' if k == 0 else 'surface'
        colours = inks(ground)
        x = LEFT + k * half + pad
        block(ctx, (x, y, width, head), [_title(item, title, colours['ink'])], anchor='bottom')
        rect(ctx, (x, y + head + 0.1, 0.9, RULE), _mark(ctx, ground))
        block(ctx, (x, y + head + rise, width, body), [_text(item, size, colours['ink'])])


@variant('two_column', 'title_tabs', accepts=_accepts)
def title_tabs(ctx, section, lines):
    """Each column a card whose title sits in a solid coloured tab on its top edge, the text on the card below."""
    pair = titled(section)
    eyebrow(ctx, (LEFT, 0.62, WIDTH, 0.3), align='center')
    headline(ctx, section, (LEFT + 0.8, 0.92, WIDTH - 1.6, 0.98), size=30, lines=2, align='center')
    rule(ctx, (LEFT + WIDTH / 2 - 0.5, 2.06, 1.0, RULE), _mark(ctx, 'surface'))
    top = 2.4
    gap, strip, pad = 0.5, 0.07, 0.3
    width = (WIDTH - gap) / 2
    tab = width * 0.8
    cut = 0.34
    inner = tab - 0.3 - cut           # the title stops short of the tab's cut corner
    room = FOOT - top

    def need(title, size):
        head = max(_title_tall(ctx, item, inner, title) for item in pair) + 0.3
        body = max(_text_tall(ctx, item, width - 2 * pad, size) for item in pair) + 2 * pad
        return head, body
    title, size = _sizes(ctx, lambda title, size: sum(need(title, size)) + strip <= room)
    head, body = need(title, size)
    card = max(body, min(room - head - strip, 1.5))
    y = _settle(top, room, head + strip + card)
    colours = [_lifted(ctx, paint) for paint in hues(ctx, 2)]
    for item, colour, x in zip(pair, colours, (LEFT, LEFT + width + gap)):
        polygon(ctx, tab_points((x, y, tab, head + 0.02), cut=cut, corner='top_right'), colour['fill'])
        rect(ctx, (x, y + head, width, strip), colour['fill'])
        rect(ctx, (x, y + head + strip, width, card), 'card')
        block(ctx, (x + 0.3, y + 0.15, inner, head - 0.3), [_title(item, title, colour['ink'])], anchor='middle')
        block(ctx, (x + pad, y + head + strip + pad, width - 2 * pad, card - 2 * pad),
              [_text(item, size, 'card_ink')])


@variant('two_column', 'side_heading', accepts=_accepts)
def side_heading(ctx, section, lines):
    """The heading in a column down the left; the two columns stacked beside it, each under a hairline and numeral."""
    pair = titled(section)
    x = header_side(ctx, section, width=3.6, size=30)
    numeral = 0.95
    width = RIGHT - x - numeral
    # The first hairline is level with header_side's rule, so full content hangs from the heading's top line.
    top, drop, between = 1.02, 0.22, 0.36   # `drop`: hairline to title; `between`: a text to the next hairline
    room = FOOT - top

    def row_tall(item, title, size):
        return drop + _title_tall(ctx, item, width, title) + 0.08 + _text_tall(ctx, item, width, size)
    # Each row as tall as its own column. Every row hangs from its own hairline, so the room the
    # estimate leaves under a text reads as the gap before the next row, not as a rule off centre.
    title, size = _sizes(ctx, lambda title, size: sum(row_tall(item, title, size) for item in pair)
                         + between <= room)
    rows = [row_tall(item, title, size) for item in pair]
    # Near-full rows hang exactly from the heading's line (a near miss would look like a slip);
    # only short ones are lifted toward the middle.
    spare = room - sum(rows) - between
    y = top if spare < 1.0 else _settle(top, room, sum(rows) + between)
    hairline = _soft(ctx, 1.7)
    for k, (item, row) in enumerate(zip(pair, rows)):
        y_k = y + k * (rows[0] + between)
        rect(ctx, (x, y_k, RIGHT - x, 0.02), hairline)
        figure(ctx, (x, y_k + drop - 0.06, numeral - 0.1, 0.7), f'{k + 1:02d}', size=30, colour='accent_text')
        block(ctx, (x + numeral, y_k + drop, width, row - drop), [
            _title(item, title, 'ink', after=0.08 * 72),
            _text(item, size, 'ink'),
        ])


@variant('two_column', 'disc_icons', accepts=_accepts)
def disc_icons(ctx, section, lines):
    """Each column led by a large numbered disc in a ring of its colour, the title and text beside it."""
    pair = titled(section)
    header(ctx, section)
    gap, ring_size, beside, after = 0.7, 1.22, 0.28, 0.1
    width = (WIDTH - gap) / 2
    inner = width - ring_size - beside
    room = FOOT - TOP - 0.1

    def need(title, size):
        return (max(_title_tall(ctx, item, inner, title) for item in pair),
                max(_text_tall(ctx, item, inner, size) for item in pair))
    title, size = _sizes(ctx, lambda title, size: sum(need(title, size)) + after <= room)
    # One title height for both columns, so the two texts start on one line.
    head, body = need(title, size)
    content = head + after + body
    group = max(content, ring_size)
    y = _settle(TOP + 0.05, room, group)
    start = y + (group - content) / 2   # text shorter than the disc is centred on it
    divider = LEFT + width + gap / 2
    rect(ctx, (divider - 0.01, y, 0.02, group), _soft(ctx))
    for k, (item, paint) in enumerate(zip(pair, hues(ctx, 2))):
        colour = _lifted(ctx, paint)
        x = LEFT + k * (width + gap)
        cx, cy = x + ring_size / 2, y + ring_size / 2
        # The ring in the disc's hue, deepened where a pale hue would vanish on the ground.
        ring(ctx, disc(cx, cy, ring_size), readable(ctx, colour['fill'], 'surface', 2.0), width=1.5)
        badge(ctx, disc(cx, cy, ring_size - 0.24), f'{k + 1:02d}', fill=colour['fill'], ink=colour['ink'], size=26,
              heading=True)
        left = x + ring_size + beside
        block(ctx, (left, start, inner, head), [_title(item, title, colour['text'])], anchor='bottom')
        block(ctx, (left, start + head + after, inner, body), [_text(item, size, 'ink')])


@variant('two_column', 'underline_titles', accepts=_accepts)
def underline_titles(ctx, section, lines):
    """The heading on a strong band; under it two columns with a wide gutter, each title on a column-wide underline."""
    pair = titled(section)
    band = strong(ctx)
    top = header_band(ctx, section, fill=band, height=1.62, size=28) + 0.05
    # On a dark deck the band may be the second colour; the underlines and numerals then take it too,
    # so the slide keeps to one colour instead of a second-colour band over accent rules.
    hue = 'secondary' if band == 'secondary' else 'accent'
    underline = readable(ctx, hue, 'surface', 2.2)
    numeral = 'accent_text' if hue == 'accent' else readable(ctx, hue, 'surface', 4.5)
    gap, mark = 1.2, 0.62
    width = (WIDTH - gap) / 2
    inner = width - mark                # the title leaves room for its numeral at the right
    rise = 0.12 + RULE + 0.22
    room = FOOT - top

    def holds(title, size):
        return (max(_title_tall(ctx, item, inner, title) for item in pair) + rise
                + max(_text_tall(ctx, item, width, size) for item in pair)) <= room
    title, size = _sizes(ctx, holds)
    head = max(_title_tall(ctx, item, inner, title) for item in pair)
    body = max(_text_tall(ctx, item, width, size) for item in pair)
    y = _settle(top, room, head + rise + body)
    for k, item in enumerate(pair):
        x = LEFT + k * (width + gap)
        block(ctx, (x, y, inner, head), [_title(item, title, 'ink')], anchor='bottom')
        figure(ctx, (x + inner, y, mark, head), f'{k + 1:02d}', size=min(title, 18), colour=numeral,
               align='right', anchor='bottom', bold=True)
        rect(ctx, (x, y + head + 0.12, width, RULE), underline)
        block(ctx, (x, y + head + rise, width, body), [_text(item, size, 'ink')])


@variant('two_column', 'framed_pair', accepts=_accepts)
def framed_pair(ctx, section, lines):
    """Both columns inside one outlined frame under a numbered heading, split by a vertical accent line."""
    pair = titled(section)
    header_number(ctx, section)
    top = TOP - 0.15                      # header_number's heading ends at 2.25
    pad, inset, gap, after = 0.45, 0.4, 0.9, 0.12   # `pad` beside the columns, `inset` above and below them
    width = (WIDTH - 2 * pad - gap) / 2
    room = FOOT - top - 2 * inset

    def need(title, size):
        return (max(_title_tall(ctx, item, width, title) for item in pair),
                max(_text_tall(ctx, item, width, size) for item in pair))
    title, size = _sizes(ctx, lambda title, size: sum(need(title, size)) + after <= room)
    # One title height for both columns, so the two texts start on one line.
    head, body = need(title, size)
    inside = head + after + body
    frame = min(FOOT - top, max(inside + 2 * inset, 1.9))
    y = _settle(top, FOOT - top, frame)
    rect(ctx, (LEFT, y, WIDTH, frame), None, line=_soft(ctx), line_width=1.25)
    middle = LEFT + WIDTH / 2
    rect(ctx, (middle - 0.0145, y + 0.3, 0.029, frame - 0.6), _mark(ctx, 'surface'))
    start = y + (frame - inside) / 2
    for k, item in enumerate(pair):
        x = LEFT + pad + k * (width + gap)
        block(ctx, (x, start, width, head), [_title(item, title, 'accent_text')], anchor='bottom')
        block(ctx, (x, start + head + after, width, body), [_text(item, size, 'ink')])
