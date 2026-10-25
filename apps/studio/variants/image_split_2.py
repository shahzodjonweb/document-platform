"""Image split variants: the photo beside, behind or between the lines, set on a panel, a card or rows of their own."""
from . import variant
from ..slides import contrast_ratio
from .kit import (ANCHOR, FOOT, LEFT, RIGHT, RULE, SQUEEZE, WIDTH, badge, bullets, eyebrow, headline, height, hex_of,
                  inks, line, list_size, rect, strong, text)

TOPLINE = 0.62    # the frame's top
BAR = 0.18        # the classic composition's accent bar down the left edge: a bled photo starts after it
SPACING = 1.22    # a list's leading, as kit.bullets sets it (slides.LINE_MULTIPLE)
GAP = 0.55        # kit.bullets' space between items, in ems
FLOOR = 13        # the smallest a list goes (slides.FLOOR_BODY_SIZE)
SLACK = 0.06      # what a fitted box needs beyond its lines (3 pt, and a little)
LIFT = 0.44       # short content sits this share of the spare room down: a little above the middle
HEADING = 14      # the heading's word limit (kit.headline)


# ---------------------------------------------------------------- measuring


def _heading(ctx, section, width, size, lines, spill=1, whole=False):
    """(points, inches): the heading as kit.headline sets it in a box `width` wide, shrunk to `lines` lines.

    A heading still longer at 18 pt is given up to `spill` lines more rather than cut, as the classic header
    allows. `whole` adds a third value: whether it holds in those lines uncut.
    """
    value = ' '.join(str(section.get('heading') or '').split()[:HEADING])
    if not value:
        return (size, 0.0, True) if whole else (size, 0.0)

    def rows(points):
        return round(height(ctx, value, width, points, heading=True, spacing=1.0) * 72 / points)
    points = size
    while points > 18 and rows(points) > lines:
        points -= 2
    tall = min(rows(points), lines + spill) * points * 1.08 / 72 + SLACK
    return (points, tall, rows(points) <= lines + spill) if whole else (points, tall)


def _list_tall(ctx, lines, width, size, hang=True):
    """Inches kit.bullets takes to set `lines` at `size` in a box `width` wide."""
    indent = 0.95 * size / 72 if hang else 0
    rows = sum(height(ctx, value, width - indent, size, spacing=SPACING) for value in lines)
    return rows + GAP * size / 72 * max(0, len(lines) - 1)


def _list(ctx, lines, width, room):
    """(points, inches): the size kit.bullets sets `lines` at in a box `width` by `room` (0 if it must cut them),
    and the height they need there."""
    size = list_size(ctx, (0, 0, width, room), lines)
    if size is None:  # it will be cut: kit.bullets has the whole room, and marks the slide
        return 0, room
    return size, min(room, _list_tall(ctx, lines, width, size) + SLACK)


def _tall(ctx, value, width, size):
    """Inches one line of the list takes, set alone at `size` in a box `width` wide."""
    return height(ctx, value, width, size, spacing=SPACING) + SLACK


def _size(ctx, holds):
    """The largest list size, from the deck's own down by SQUEEZE, at which `holds(size)`.

    Lines set in boxes of their own shrink together, as one list would; if none
    holds, the slide is marked squeezed (the variant is passed over).
    """
    low = max(FLOOR, ctx.size - SQUEEZE)
    size = ctx.size
    while size >= low:
        if holds(size):
            return size
        size -= 0.5
    ctx.squeezed = True
    return low


def _settle(top, room, tall):
    """Where content `tall` inches high starts in `room` below `top`: a little above the middle."""
    return top + max(0.0, room - tall) * LIFT


def _mark(ctx, fill):
    """The accent, for a rule or marker on `fill`, if it shows there; else the fill's own ink."""
    if fill != 'accent' and contrast_ratio(hex_of(ctx, 'accent'), hex_of(ctx, fill)) >= 3.0:
        return 'accent'
    return inks(fill)['ink']


def _clean(lines):
    return [' '.join(str(value).split()) for value in lines if str(value).strip()]


def _placed(ctx, box):
    """(x, y, w, h): where the photo declared at `box` lands on this slide.

    slides.render_pptx keeps a content photo inside its composition's
    `content_box` (a framing card, an editorial plate), so a panel meant to
    line up with the photo asks for the same box. The deck's style is known on
    the trial slide as on the real one, so both are drawn alike.
    """
    try:
        from ..compositions import compose
        from ..deck_designs import look
        arrangement = compose(look(ctx.style).get('composition', 'classic'))
    except Exception:
        return box
    if arrangement.name == 'classic':
        return box
    x, y, w, h = box
    cx, cy, cw, ch = arrangement.content_box
    left, top = max(x, cx), max(y, cy)
    right, bottom = min(x + w, cx + cw), min(y + h, cy + ch)
    return (left, top, right - left, bottom - top) if right > left and bottom > top else box


def _middle(ctx):
    """Centre the text of the box just drawn in its height (measured lines run a little long, on either side)."""
    ctx.slide.shapes[-1].text_frame.vertical_anchor = ANCHOR['middle']


def _snap(y, tall, top=TOPLINE, bottom=FOOT, near=0.14):
    """A panel's (y, height), grown onto `top` and `bottom` when its edges stop within `near` of them.

    A card ending a few hundredths short of a photo's foot leaves a sliver of
    the picture showing under it; flush, the two share one edge. A panel only
    grows here, never shrinks, so what it holds still fits.
    """
    if 0 < y - top < near:
        tall, y = tall + (y - top), top
    if 0 < bottom - (y + tall) < near:
        tall = bottom - y
    return y, tall


# ---------------------------------------------------------------- variants

SEAM = 6.28   # text_panel: where the photo meets the panel
# The band keeps the frame's margins on both sides: the panel cannot bleed, so the photo does not either.
BAND = (LEFT, TOPLINE, SEAM - LEFT, FOOT - TOPLINE)


@variant('image_split', 'text_panel', photo=BAND)
def text_panel(ctx, section, lines):
    """One band across the slide: the photo in its left half and a strong panel holding the heading and lines."""
    lines = _clean(lines)
    panel = inks(strong(ctx))
    mark = _mark(ctx, panel['fill'])
    # The panel shares the photo's top and foot wherever the composition keeps the photo (a frame, a plate).
    _, band_top, _, band_tall = _placed(ctx, BAND)
    band_top, band_foot = max(TOPLINE, band_top), min(FOOT, band_top + band_tall)
    rect(ctx, (SEAM, band_top, RIGHT - SEAM, band_foot - band_top), panel['fill'])
    inner = SEAM + 0.52
    width = RIGHT - 0.45 - inner
    points, head = _heading(ctx, section, width, 28, 2, spill=2)
    above = 0.3 + 0.14 + head + 0.3                      # the eyebrow row, the heading and the gap to the list
    # The panel's margins give a little before its list goes smaller than the deck's.
    for pad in (0.42, 0.3):
        top, bottom = band_top + pad, band_foot - pad
        size, tall = _list(ctx, lines, width, bottom - top - above)
        if size >= ctx.size - SQUEEZE:
            break
    y = _settle(top, bottom - top, above + tall)
    # A short rule leads the eyebrow on its row.
    rect(ctx, (inner, y + 0.15 - RULE / 2, 0.5, RULE), mark)
    eyebrow(ctx, (inner + 0.66, y, width - 0.66, 0.3), colour=panel['muted'])
    y += 0.3 + 0.14
    headline(ctx, section, (inner, y, width, head), size=points, lines=2, anchor='top', colour=panel['ink'])
    y += head + 0.3
    bullets(ctx, (inner, y, width, tall), lines, colour=panel['ink'], marker=mark)


CENTRE = (LEFT + WIDTH / 2 - 1.75, LEFT + WIDTH / 2 + 1.75)   # centre_photo: the photo's column, on the frame's axis
CENTRE_TOP = 2.5          # where the photo and the lines begin, under the heading


# A single line would leave one side of the photo bare.
@variant('image_split', 'centre_photo', counts=(2, 6),
         photo=(CENTRE[0], CENTRE_TOP, CENTRE[1] - CENTRE[0], FOOT - CENTRE_TOP))
def centre_photo(ctx, section, lines):
    """The heading centred across the top; a tall photo in the middle column, the lines split to its left and right."""
    lines = _clean(lines)
    eyebrow(ctx, (LEFT, TOPLINE, WIDTH, 0.3), align='center')
    headline(ctx, section, (LEFT + 0.6, 0.9, WIDTH - 1.2, 1.04), size=30, lines=2, align='center')
    rect(ctx, (LEFT + WIDTH / 2 - 0.5, 2.18, 1.0, RULE), 'accent')
    width = CENTRE[0] - 0.42 - LEFT
    half = -(-len(lines) // 2)
    columns = [(LEFT, lines[:half]), (RIGHT - width, lines[half:])]
    room, bar, under, least, most = FOOT - CENTRE_TOP, 0.07, 0.16, 0.3, 0.62

    # The two columns' rows are level when they have as many; a lone line opposite two is centred.
    level = len(columns[0][1]) == len(columns[1][1])

    def rows(values, size):
        if level:  # each row as tall as the taller of its pair, on both sides
            return [max(bar + under + _tall(ctx, value, width, size) for value in pair)
                    for pair in zip(columns[0][1], columns[1][1])]
        return [bar + under + _tall(ctx, value, width, size) for value in values]
    size = _size(ctx, lambda size: all(sum(rows(values, size)) + least * (len(values) - 1) <= room
                                       for _, values in columns if values))
    for x, values in columns:
        if not values:
            continue
        heights = rows(values, size)
        gap = max(least, min(most, (room - sum(heights)) / max(1, len(values) - 1))) if len(values) > 1 else 0
        y = _settle(CENTRE_TOP, room, sum(heights) + gap * (len(values) - 1))
        for value, row in zip(values, heights):
            rect(ctx, (x, y, 0.5, bar), 'accent')
            text(ctx, (x, y + bar + under, width, _tall(ctx, value, width, size)), value, size=size, floor=size,
                 spacing=SPACING)
            y += row + gap


OVERLAP = 5.4             # overlap_card: the photo's left edge
OVERLAP_PHOTO = (OVERLAP, 0, 13.333 - OVERLAP, FOOT)


@variant('image_split', 'overlap_card', photo=OVERLAP_PHOTO)
def overlap_card(ctx, section, lines):
    """A large photo at the right; the heading on the ground and the lines on a card laid over the photo's edge."""
    lines = _clean(lines)
    head_width = OVERLAP - 0.38 - LEFT
    card_w = 7.55 - LEFT
    pad_x, pad_y, strip = 0.55, 0.42, 0.09
    width = card_w - pad_x - 0.45
    top, bottom = TOPLINE, FOOT
    points, head = _heading(ctx, section, head_width, 30, 3, spill=2)
    above = 0.3 + 0.08 + head + 0.34                      # eyebrow, heading and the gap to the card
    size, tall = _list(ctx, lines, width, bottom - top - above - 2 * pad_y)
    card_h = max(tall + 2 * pad_y, 1.5)
    y = _settle(top, bottom - top, above + card_h)
    eyebrow(ctx, (LEFT, y, head_width, 0.3))
    y += 0.3 + 0.08
    headline(ctx, section, (LEFT, y, head_width, head), size=points, lines=3, anchor='top')
    y += head + 0.34
    # A card that ends just short of the photo's foot is made flush with it.
    placed = _placed(ctx, OVERLAP_PHOTO)
    y, card_h = _snap(y, card_h, top=y, bottom=min(FOOT, placed[1] + placed[3]))
    rect(ctx, (LEFT, y, card_w, card_h), 'card')
    rect(ctx, (LEFT, y, strip, card_h), 'accent')
    bullets(ctx, (LEFT + pad_x, y + (card_h - tall) / 2, width, tall), lines, colour='card_ink',
            marker='card_accent')
    _middle(ctx)


NUMBERED = 7.2            # numbered: the photo's left edge, a little right of the classic one


@variant('image_split', 'numbered', photo=(NUMBERED, 0, 13.333 - NUMBERED, 6.55))
def numbered(ctx, section, lines):
    """The photo at the right; each line a row led by an accent number disc, the discs linked by a spine."""
    lines = _clean(lines)
    column = NUMBERED - 0.4 - LEFT
    flag = 0.34                                           # the heading's accent flag and the step after it
    points, head = _heading(ctx, section, column - flag, 30, 2)
    above = 0.3 + 0.06 + head + 0.36                      # eyebrow, heading and the gap to the rows
    dot, step = 0.46, 0.26
    x, width = LEFT + dot + step, column - dot - step
    room, least, most = FOOT - TOPLINE - above, 0.16, 0.5

    def offset(size):
        # The first line of a row sits level with the middle of its disc.
        return max(0.0, (dot - size * SPACING / 72) / 2)

    def rows(size):
        return [max(dot, offset(size) + _tall(ctx, value, width, size)) for value in lines]

    def even(size):
        # Every row but the last as tall as the tallest of them: the discs fall evenly down the spine,
        # however each line happens to wrap.
        heights = rows(size)
        return [max(heights[:-1])] * (len(heights) - 1) + heights[-1:] if len(heights) > 1 else heights

    def holds(heights):
        return sum(heights) + least * (len(heights) - 1) <= room
    size = _size(ctx, lambda size: holds(rows(size)))
    heights = rows(size)
    # Even discs are worth half a point or a point of type, never more, nor below the deck's floor.
    points_tried = size
    while points_tried >= max(FLOOR, ctx.size - SQUEEZE, size - 1):
        if holds(even(points_tried)):
            size, heights = points_tried, even(points_tried)
            break
        points_tried -= 0.5
    gap = max(least, min(most, (room - sum(heights)) / max(1, len(lines) - 1)))
    y = _settle(TOPLINE, FOOT - TOPLINE, above + sum(heights) + gap * (len(lines) - 1))
    eyebrow(ctx, (LEFT + flag, y, column - flag, 0.3))
    y += 0.3 + 0.06
    if head:
        rect(ctx, (LEFT, y + 0.04, 0.09, head - 0.08), 'accent')
    headline(ctx, section, (LEFT + flag, y, column - flag, head), size=points, lines=2, anchor='middle')
    y += head + 0.36
    for k, (value, row) in enumerate(zip(lines, heights)):
        if k:
            # The spine runs between the discs, never through one; a hairline in a pale accent would vanish
            # on the ground, so it takes the accent made to read there.
            line(ctx, (LEFT + dot / 2, y - gap - (heights[k - 1] - dot) + 0.06), (LEFT + dot / 2, y - 0.06),
                 'accent_text', 1.25)
        badge(ctx, (LEFT, y, dot, dot), f'{k + 1:02d}', size=14, heading=True)
        text(ctx, (x, y + offset(size), width, _tall(ctx, value, width, size)), value, size=size, floor=size,
             spacing=SPACING)
        y += row + gap


CAPTION = 8.9                     # caption_card: the photo's right edge, two thirds across
CAPTION_WIDTHS = (4.3, 4.6, 4.9, 5.25)   # the card's text widths, narrowest first: it widens for longer lines
CAPTION_PHOTO = (BAR, 0, CAPTION - BAR, FOOT)


@variant('image_split', 'caption_card', photo=CAPTION_PHOTO)
def caption_card(ctx, section, lines):
    """A photo across two thirds; the heading and lines on a card over its right edge, under a thin accent bar."""
    lines = _clean(lines)
    pad_x, pad_y, bar = 0.45, 0.34, 0.1
    top, bottom = TOPLINE, FOOT

    def layout(width):
        points, head, whole = _heading(ctx, section, width, 26, 3, spill=2, whole=True)
        above = bar + pad_y + 0.3 + 0.1 + head + 0.26     # bar, eyebrow, heading and the gap to the list
        size, tall = _list(ctx, lines, width, bottom - top - above - pad_y)
        return size if whole else 0, width, points, head, above, tall
    # The narrowest card that sets the heading whole and the list within a point of the largest any card would.
    options = [layout(width) for width in CAPTION_WIDTHS]
    best = max(option[0] for option in options)
    size, width, points, head, above, tall = next(option for option in options if option[0] >= best - 1)
    card_w = width + 2 * pad_x
    x = RIGHT - card_w
    card_h = above + tall + pad_y
    y = _settle(top, bottom - top, card_h)
    # A full card meets the frame's top and the photo's foot rather than stopping a hair short of them.
    placed = _placed(ctx, CAPTION_PHOTO)
    y, card_h = _snap(y, card_h, bottom=min(FOOT, placed[1] + placed[3]))
    rect(ctx, (x, y, card_w, card_h), 'card')
    rect(ctx, (x, y, card_w, bar), 'accent')
    inner = x + pad_x
    y += bar + pad_y
    eyebrow(ctx, (inner, y, width, 0.3), colour='card_muted')
    y += 0.3 + 0.1
    headline(ctx, section, (inner, y, width, head), size=points, lines=3, anchor='top', colour='card_ink')
    y += head + 0.26
    bullets(ctx, (inner, y, width, tall), lines, colour='card_ink', marker='card_accent')
