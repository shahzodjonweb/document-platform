"""Image_full variants: one large photo, its heading and caption set on a solid ground of their own beside or over it."""
import colorsys

from . import variant
from ..slides import contrast_ratio
from .kit import (FOOT, FRAME, LEFT, RIGHT, RULE, WIDTH, badge, eyebrow, headline, height, hex_of, inks, line, rect,
                  readable, strong, text)

LEADING = 1.08       # a headline's leading (slides._headline)
SPACING = 1.15       # a caption's leading
SLACK = 0.06         # what a fitted box needs beyond its lines (3 pt, and a little)
HEAD_WORDS = 12      # the classic drawer's limits
CAPTION_WORDS = 24
EYEBROW = 0.26       # the '03 / 12' marker's box

# Where each variant's picture goes (inches). Text stays off all of it.
CAPTION_PANEL = (LEFT, FRAME[1], WIDTH, 5.48)
FRAMED = (LEFT + 0.3, FRAME[1], 7.15, 5.75)
TALL_LEFT = (0.18, 0.0, 7.22, 6.55)
BAND_CAPTION = (LEFT, FRAME[1], WIDTH, 4.2)


# ---------------------------------------------------------------- measuring


def _clipped(value, words):
    parts = str(value or '').split()
    return ' '.join(parts[:words]) + ('…' if len(parts) > words else '')


def _caption(lines):
    """The caption as the classic drawer takes it: the slide's first line."""
    return lines[0] if lines else ''


def _head(ctx, section, width, size, lines, room=99.0):
    """(size, inches) the heading takes as kit.headline sets it in a box `width` wide, within `room` if it can."""
    value = _clipped(section.get('heading'), HEAD_WORDS)
    if not value:
        return size, 0.0
    while size > 18 and (height(ctx, value, width, size, heading=True, spacing=1) > lines * size / 72 + 1e-6
                         or height(ctx, value, width, size, heading=True, spacing=LEADING) + SLACK > room):
        size -= 2
    return size, height(ctx, value, width, size, heading=True, spacing=LEADING) + SLACK


def _cap(ctx, value, width, sizes, room=99.0):
    """(size, inches): the largest caption size in `sizes` whose lines fit `room`."""
    value = _clipped(value, CAPTION_WORDS)
    if not value:
        return sizes[0], 0.0
    for size in sizes:
        tall = height(ctx, value, width, size, spacing=SPACING) + SLACK
        if tall <= room:
            return size, tall
    return sizes[-1], height(ctx, value, width, sizes[-1], spacing=SPACING) + SLACK


def _say(ctx, box, lines, size, colour, anchor='top'):
    text(ctx, box, _caption(lines), size=size, floor=12, colour=colour, words=CAPTION_WORDS, spacing=SPACING,
         anchor=anchor)


def _title(ctx, section, box, size, lines, colour=None, anchor='top'):
    headline(ctx, section, box, size=size, lines=lines, anchor=anchor, colour=colour, words=HEAD_WORDS)


# ---------------------------------------------------------------- colour


def _saturation(colour):
    red, green, blue = (int(colour[k:k + 2], 16) / 255 for k in (0, 2, 4))
    return colorsys.rgb_to_hls(red, green, blue)[2]


def _distinct(one, other):
    """Whether two hex colours tell apart at a glance: by lightness, or by hue (coral beside blue)."""
    if contrast_ratio(one, other) >= 1.8:
        return True
    pairs = zip((int(one[k:k + 2], 16) for k in (0, 2, 4)), (int(other[k:k + 2], 16) for k in (0, 2, 4)))
    return sum((a - b) ** 2 for a, b in pairs) ** 0.5 >= 150


def _edge(ctx, fill):
    """A colour that shows against the `fill` panel: the accent, else the second colour, else the panel's ink."""
    for role in ('accent', 'secondary'):
        if role != fill and _distinct(hex_of(ctx, role), hex_of(ctx, fill)):
            return role
    return inks(fill)['ink']


def _band(ctx):
    """The accent for a band under the photo, unless it is too close to the ground to show as one.

    A saturated pale accent (a yellow on white) still reads as a band by its colour; a grey one near the ground
    gives way to the second colour, then to the strongest fill.
    """
    surface, accent = hex_of(ctx, 'surface'), hex_of(ctx, 'accent')
    ratio = contrast_ratio(accent, surface)
    if ratio >= 1.6 or (ratio >= 1.2 and _saturation(accent) >= 0.35):
        return 'accent'
    if contrast_ratio(hex_of(ctx, 'secondary'), surface) >= 1.6:
        return 'secondary'
    return strong(ctx, prefer=('accent', 'secondary', 'deep'))


def _stroke(ctx):
    """The accent for a rule or outline on the slide, darkened (or lightened) until a hairline of it shows."""
    accent = hex_of(ctx, 'accent')
    return accent if contrast_ratio(accent, hex_of(ctx, 'surface')) >= 2.2 else readable(ctx, 'accent', 'surface', 2.2)


def _stand_in(ctx, box):
    """A quiet tint where the photo goes, should the picture fail to place."""
    if ctx.photo:
        return
    left, top = max(box[0], FRAME[0]), max(box[1], FRAME[1])
    right, bottom = min(box[0] + box[2], RIGHT), min(box[1] + box[3], FOOT)
    rect(ctx, (left, top, right - left, bottom - top), 'accent_soft')


def _placed(ctx, box):
    """Where the picture meant for `box` lands: a composition other than the classic one keeps it inside its
    content box (slides.render_pptx), so the frame's top can come down to 0.85 in."""
    if ctx.plan is not None and getattr(ctx.plan, 'photo', None):
        return tuple(ctx.plan.photo)
    from ..compositions import compose
    from ..deck_designs import look
    arrangement = compose(look(ctx.style).get('composition', 'classic'))
    if arrangement.name == 'classic':
        return box
    x, y, w, h = arrangement.content_box
    left, top = max(box[0], x), max(box[1], y)
    right, bottom = min(box[0] + box[2], x + w), min(box[1] + box[3], y + h)
    return (left, top, right - left, bottom - top)


# ---------------------------------------------------------------- variants


@variant('image_full', 'caption_panel', photo=CAPTION_PANEL)
def caption_panel(ctx, section, lines):
    """The photo across the frame; the heading and caption on a strong panel over its bottom-left corner."""
    _stand_in(ctx, CAPTION_PANEL)
    panel = inks(strong(ctx))
    x, width, strip = LEFT + 0.45, 6.4, 0.14
    pad, top_pad, bottom_pad = 0.48, 0.42, 0.42
    inner = width - strip - 2 * pad
    lead = EYEBROW + 0.16
    # The panel may rise to 1.4 in under the photo's top, no further: the photo stays the slide.
    room = FOOT - FRAME[1] - 1.4 - top_pad - bottom_pad - lead
    cap_size, cap_tall = _cap(ctx, _caption(lines), inner, (15, 14, 13, 12), room=room / 2)
    gap = 0.2 if cap_tall else 0.0
    head_size, head_tall = _head(ctx, section, inner, 30, 4, room=room - cap_tall - gap)
    tall = max(2.1, top_pad + lead + head_tall + gap + cap_tall + bottom_pad)
    y = FOOT - tall
    rect(ctx, (x, y, width, tall), panel['fill'])
    rect(ctx, (x, y, strip, tall), _edge(ctx, panel['fill']))
    left = x + strip + pad
    eyebrow(ctx, (left, y + top_pad, inner, EYEBROW), colour=panel['muted'])
    # The heading sits on the caption's box, so a heading line fewer than measured opens room under the eyebrow,
    # not between the two; the caption is centred in its box, so a line fewer of it splits between the gap above
    # and the panel's foot.
    cap_top = FOOT - bottom_pad - cap_tall
    head_top = y + top_pad + lead
    _title(ctx, section, (left, head_top, inner, cap_top - gap - head_top), head_size, 4, colour=panel['ink'],
           anchor='bottom')
    if cap_tall:
        _say(ctx, (left, cap_top, inner, cap_tall), lines, cap_size, panel['muted'], anchor='middle')


@variant('image_full', 'framed', photo=FRAMED)
def framed(ctx, section, lines):
    """The photo inset at the left inside an offset accent outline; the heading and a caption card to its right."""
    _stand_in(ctx, FRAMED)
    # The outline follows the picture where it lands: a composition's content box can lower its top.
    px, py, pw, ph = _placed(ctx, FRAMED)
    offset = 0.28
    # The outline runs behind the photo: only the parts outside it are drawn.
    fx, fy, fr, fb = px - offset, py + offset, px + pw - offset, min(py + ph + offset, FOOT - 0.02)
    stroke = _stroke(ctx)
    line(ctx, (fx, fy), (px, fy), stroke, 2.0)
    line(ctx, (fx, fy), (fx, fb), stroke, 2.0)
    line(ctx, (fx, fb), (fr, fb), stroke, 2.0)
    line(ctx, (fr, py + ph), (fr, fb), stroke, 2.0)
    left = FRAMED[0] + FRAMED[2] + 0.45
    width = RIGHT - left
    top, bottom = py, py + ph
    lead = 0.68                      # the eyebrow and rule above the heading
    card = inks('card')
    # A line's leading sits above its letters, so the text starts a little nearer the tab than the card's foot
    # is to its last line: the two margins then look the same.
    pad, tab, under = 0.28, 0.08, 0.22
    cap_size, cap_tall = _cap(ctx, _caption(lines), width - 2 * pad, (14, 13, 12), room=2.4)
    card_tall = tab + under + cap_tall + pad if cap_tall else 0.0
    card_top = bottom - card_tall
    room = (card_top - 0.3 if card_tall else bottom) - top - lead
    head_size, head_tall = _head(ctx, section, width, 34, 6, room=room)
    if not card_tall:
        # A heading alone is centred on the picture rather than left at its top over an empty column.
        top += max(0.0, (bottom - top - lead - head_tall) / 2)
    eyebrow(ctx, (left, top, width, EYEBROW))
    rect(ctx, (left, top + 0.42, 0.9, RULE), stroke)
    _title(ctx, section, (left, top + lead, width, min(head_tall, room)), head_size, 6)
    if card_tall:
        rect(ctx, (left, card_top, width, card_tall), card['fill'])
        # The card's tab repeats the rule over the heading: the same length and colour.
        rect(ctx, (left, card_top, 0.9, tab), stroke)
        _say(ctx, (left + pad, card_top + tab + under, width - 2 * pad, cap_tall), lines, cap_size, card['ink'],
             anchor='middle')


@variant('image_full', 'tall_left', photo=TALL_LEFT)
def tall_left(ctx, section, lines):
    """A tall photo bleeding off the top left, the slide's number on an accent square across its edge; the heading
    large on the right, an accent rule, then the caption."""
    _stand_in(ctx, TALL_LEFT)
    px, py, pw, ph = TALL_LEFT
    side = 1.1
    square = (px + pw - side * 0.55, py + ph - 0.35 - side, side, side)
    badge(ctx, square, f'{ctx.index + 1:02d}', fill='accent', ink=inks('accent')['ink'], shape='rect', size=30,
          heading=True)
    left = square[0] + side + 0.45
    width = RIGHT - left
    top, bottom = FRAME[1], py + ph
    cap_size, cap_tall = _cap(ctx, _caption(lines), width, (16, 15, 14, 13, 12), room=2.0)
    rule_gap = (0.3 + RULE + 0.3) if cap_tall else 0.0
    head_size, head_tall = _head(ctx, section, width, 40, 6, room=bottom - top - rule_gap - cap_tall)
    group = head_tall + rule_gap + cap_tall
    y = top + max(0.0, (bottom - top - group) / 2)
    # The heading sits on the rule and the caption hangs from it, whatever lines either takes.
    _title(ctx, section, (left, y, width, head_tall), head_size, 6, anchor='bottom' if cap_tall else 'middle')
    if cap_tall:
        y += head_tall + 0.3
        rect(ctx, (left, y, 1.1, RULE), _stroke(ctx))
        _say(ctx, (left, y + RULE + 0.3, width, cap_tall), lines, cap_size, 'muted')


@variant('image_full', 'band_caption', photo=BAND_CAPTION)
def band_caption(ctx, section, lines):
    """The photo across the top of the frame over an accent band; the heading at the band's left, the caption at
    its right past a thin divider."""
    _stand_in(ctx, BAND_CAPTION)
    px, py, pw, ph = BAND_CAPTION
    fill = _band(ctx)
    band = inks(fill)
    y, tall = py + ph, FOOT - py - ph
    rect(ctx, (px, y, pw, tall), fill)
    pad_x, pad_y = 0.5, 0.26
    room = tall - 2 * pad_y
    left = px + pad_x
    # A short tab in a second colour where the band meets the photo, over the heading's edge.
    rect(ctx, (left, y, 1.3, 0.09), _edge(ctx, fill))
    if not _caption(lines):
        width = pw - 2 * pad_x - 2.0
        head_size, _ = _head(ctx, section, width, 30, 2, room=room)
        _title(ctx, section, (left, y + pad_y, width, room), head_size, 2, colour=band['ink'], anchor='middle')
        return
    head_width = 5.3
    head_size, head_tall = _head(ctx, section, head_width, 28, 3, room=room)
    _title(ctx, section, (left, y + pad_y, head_width, room), head_size, 3, colour=band['ink'], anchor='middle')
    divider = left + head_width + 0.4
    right = divider + 0.4
    width = px + pw - pad_x - right
    cap_size, cap_tall = _cap(ctx, _caption(lines), width, (15, 14, 13, 12), room=room)
    # The divider as tall as the taller of the two texts, centred on them as they are on the band.
    span = min(room - 0.16, max(0.6, head_tall, cap_tall))
    middle = y + tall / 2
    line(ctx, (divider, middle - span / 2), (divider, middle + span / 2), band['ink'], 1.0)
    _say(ctx, (right, y + pad_y, width, room), lines, cap_size, band['ink'], anchor='middle')
