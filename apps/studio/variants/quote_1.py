"""Quote variants: the words large in the heading face, set off by drawn quotation marks, discs, bars and panels."""
import math

from pptx.util import Inches

from . import variant
from ..slide_layouts import _paragraph_height, _text_lines
from ..slides import _luminance, contrast_ratio
from .kit import (FOOT, LEFT, RIGHT, RULE, WIDTH, Z, attribution, block, body_text, disc, eyebrow, figure,
                  header_side, headline, height, hex_of, hues, inks, items_of, line, on, oval, polygon,
                  readable, rect, ring, rounded, rule, strong, text)

TOP_EDGE = 0.62
WORDS = 45              # the quote's word limit, as the classic drawer holds it
NAME, ROLE = 8, 12      # who said it, and their role or source (kit.attribution's limits)
LEADING = 1.2           # the quote's line spacing, as the classic drawer sets it
SLACK = 5 / 72          # what a fitted box needs beyond its lines (3 pt, and a little)
LIFT = 0.42             # short content sits this share of the spare room down: a little above the middle


# ---------------------------------------------------------------- content and measuring


def _quote(section, lines):
    """The quotation itself: the body, as the classic drawer reads it."""
    return body_text(section) or ' '.join(' '.join(lines).split())


def _plain(value, limit):
    """`value` held to `limit` words, as kit.clip holds it (without marking the slide)."""
    parts = str(value or '').split()
    return ' '.join(parts) if len(parts) <= limit else ' '.join(parts[:limit]).rstrip(',;:.') + '…'


def _who(section):
    """(name, role) of whoever is quoted."""
    items = items_of(section)
    who = items[0] if items else {}
    return ' '.join(str(who.get('label') or '').split()), ' '.join(str(who.get('text') or '').split())


def _initials(section):
    """The first letters of up to two words of the speaker's name, in capitals ('' when there is none)."""
    name, _ = _who(section)
    letters = []
    for word in name.split():
        first = next((character for character in word if character.isalnum()), '')
        if first:
            letters.append(first.upper())
        if len(letters) == 2:
            break
    return ''.join(letters)


def _fit(ctx, value, width, room, top=32, low=18):
    """The largest size from `top` down to `low` at which the quote fits `width` x `room`; (size, height)."""
    sample = _plain(value, WORDS)
    size = top
    while size > low and height(ctx, sample, width, size, heading=True, spacing=LEADING) + SLACK > room:
        size -= 1
    return size, height(ctx, sample, width, size, heading=True, spacing=LEADING) + SLACK


def _say(ctx, box, value, size, colour='ink', align='left', anchor='middle'):
    """The quote, in the heading face, at the size `_fit` chose (its box is `_fit`'s height, so it fills it)."""
    return text(ctx, box, value, size=size, floor=min(size, 16), colour=colour, heading=True, words=WORDS,
                spacing=LEADING, align=align, anchor=anchor)


def _bold(ctx, paragraph):
    return bool(paragraph.get('bold')) or bool(paragraph.get('heading') and ctx.heading_bold)


def _need(ctx, width, paragraphs):
    """Inches `paragraphs` (as for kit.block) take in a box `width` wide, measured as block measures them."""
    zone = Z(0, 0, width, 10)
    total = 0.0
    for paragraph in paragraphs:
        value = _plain(paragraph.get('text'), paragraph.get('words') or 999)
        if not value:
            continue
        total += _paragraph_height(dict(text=value, size=paragraph['size'], bold=_bold(ctx, paragraph),
                                        before=paragraph.get('before', 0), after=paragraph.get('after', 0),
                                        spacing=paragraph.get('spacing', 1.15)), zone)
    return total / 72 + SLACK


def _credit(section, *, ink='ink', muted='muted', align='left', name=18, role=14):
    """Who said it in bold in the heading face, their role or source quieter below."""
    who, what = _who(section)
    return [dict(text=who, words=NAME, size=name, floor=min(name, 14), colour=ink, bold=True, heading=True,
                 align=align, after=2),
            dict(text=what, words=ROLE, size=role, floor=12, colour=muted, align=align)]


def _line_credit(ctx, section, *, dash=True):
    """'— Name, role' on one paragraph (kit.attribution); without the dash where a drawn rule leads it.

    '' when nobody is named: kit.attribution needs an item, and a bare dash says nothing.
    """
    name, role = _who(section)
    if not (name or role):
        return ''
    value = attribution(ctx, section)
    return value if dash else value.lstrip('— ').strip()


def _heading(ctx, section, box, *, size=22, colour=None, align='left', lines=2, anchor='top'):
    if str(section.get('heading') or '').strip():
        headline(ctx, section, box, size=size, lines=lines, anchor=anchor, align=align, colour=colour)


def _heading_tall(ctx, section, width, size, most=3):
    """(inches, lines) the heading takes at `size` in `width` (0 when there is none), as kit.headline sets it."""
    value = _plain(section.get('heading'), 14)
    if not value:
        return 0.0, 0
    count = min(most, _text_lines(value, size, Inches(width), bold=ctx.heading_bold))
    return count * size * 1.08 / 72 + 0.06, count


def _settle(top, room, tall):
    """Where content `tall` inches high starts in `room` below `top`: a little above the middle."""
    return top + max(0.0, room - tall) * LIFT


def _reads(ctx, colour, fill, target=2.2):
    """`colour` (a role) if it stands out on `fill` (a role), else the fill's own accent ink."""
    if contrast_ratio(hex_of(ctx, colour), hex_of(ctx, fill)) >= target:
        return colour
    return inks(fill)['accent']


def _visible(ctx, role='accent'):
    """(fill, ink): `role` as a fill that stands out from the slide's surface, and the ink that reads on it.

    A pale accent on a light deck still shows as colour, but a dark one on a dark deck (navy on near-black)
    all but vanishes, so there it is lightened until it stands clear; the ink is then measured on the new fill.
    """
    target = 1.3 if _luminance(ctx.roles['surface']) > 0.4 else 2.4
    if contrast_ratio(hex_of(ctx, role), hex_of(ctx, 'surface')) >= target:
        return role, inks(role)['ink'] if role in ('accent', 'deep', 'secondary') else on(hex_of(ctx, role))
    fill = readable(ctx, role, 'surface', target)
    return fill, on(fill)


# ---------------------------------------------------------------- the drawn quotation mark


def _six(cx, cy, r, steps=26):
    """One opening mark: a ball of radius `r` at (cx, cy) whose tail rises from its left and hooks right."""
    big = 1.5 * r
    ox, oy = cx + big - r, cy
    outer, inner = [], []
    for k in range(steps + 1):
        share = k / steps
        angle = math.radians(180 + 105 * share)
        thick = 2 * r * (1 - share) ** 1.35
        outer.append((ox + big * math.cos(angle), oy + big * math.sin(angle)))
        inner.append((ox + (big - thick) * math.cos(angle), oy + (big - thick) * math.sin(angle)))
    return outer + inner[::-1][1:]


def mark_width(h):
    """The width of `marks` drawn `h` tall: two balls of 0.8 h and the gap between them."""
    return 4.4 * h / 2.5


def marks(ctx, x, y, h, fill):
    """A drawn opening quotation mark (“) in a box `h` tall from (x, y), font-free; returns its width."""
    r = h / 2.5
    for cx in (x + r, x + 3.4 * r):
        cy = y + 1.5 * r
        oval(ctx, disc(cx, cy, 2 * r), fill)
        polygon(ctx, _six(cx, cy, r), fill)
    return mark_width(h)


# ---------------------------------------------------------------- variants


@variant('quote', 'marks_centre')
def marks_centre(ctx, section, lines):
    """Everything centred: an accent disc holding an opening mark between two hairlines, the quote large below it,
    a short rule and the attribution under it."""
    eyebrow(ctx, (LEFT, TOP_EDGE, WIDTH, 0.3), align='center')
    _heading(ctx, section, (LEFT + 1.2, 0.98, WIDTH - 2.4, 0.66), size=20, colour='muted', align='center')
    value = _quote(section, lines)
    width = 9.4
    x = LEFT + (WIDTH - width) / 2
    credit = _line_credit(ctx, section)
    credit_h = _need(ctx, width, [dict(text=credit, size=16)]) if credit else 0.0
    top, bottom = 1.8, FOOT - 0.02
    # The quote's line box carries its leading above the letters, so the gap under it is set wider than the
    # one over it for the two to look alike; the rule sits nearer the attribution it leads.
    size_disc, before, after = 1.05, 0.3, (0.46 if credit else 0.3)
    size, quote_h = _fit(ctx, value, width, bottom - top - size_disc - before - after - credit_h, top=34)
    tall = size_disc + before + quote_h + after + credit_h
    y = _settle(top, bottom - top, tall)
    centre = LEFT + WIDTH / 2
    fill, ink = _visible(ctx)
    oval(ctx, disc(centre, y + size_disc / 2, size_disc), fill)
    mark_h = size_disc * 0.4
    marks(ctx, centre - mark_width(mark_h) / 2, y + (size_disc - mark_h) / 2, mark_h, ink)
    hair = y + size_disc / 2
    line(ctx, (centre - 3.2, hair), (centre - size_disc / 2 - 0.25, hair), fill, 1.0)
    line(ctx, (centre + size_disc / 2 + 0.25, hair), (centre + 3.2, hair), fill, 1.0)
    y += size_disc + before
    _say(ctx, (x, y, width, quote_h), value, size, align='center')
    y += quote_h
    if credit:
        rule(ctx, (centre - 0.3, y + after * 0.55 - RULE / 2, 0.6, RULE), fill)
        text(ctx, (x, y + after, width, credit_h), credit, size=16, colour='muted', align='center')


@variant('quote', 'dark_panel')
def dark_panel(ctx, section, lines):
    """A strong panel fills the frame: a large opening mark in its accent at the left, the heading, the quote and
    the speaker in its own inks to the right."""
    panel = inks(strong(ctx))
    rounded(ctx, (LEFT, TOP_EDGE, WIDTH, FOOT - TOP_EDGE), panel['fill'], radius=0.16)
    mark_colour = _reads(ctx, 'accent', panel['fill'], 2.4) if panel['fill'] != 'accent' else panel['accent']
    pad = 0.6
    eyebrow(ctx, (LEFT + pad, TOP_EDGE + 0.32, 3.0, 0.3), colour=panel['muted'])
    column = 2.7
    x = LEFT + pad + column
    width = RIGHT - pad - x
    # The heading is kept well under the quote: on an accent or second-colour panel its quieter ink is the
    # same as the quote's, so size alone has to tell them apart.
    heading_h, heading_lines = _heading_tall(ctx, section, width, 17)
    has_heading = heading_h > 0
    paragraphs = _credit(section, ink=panel['ink'], muted=panel['muted'])
    credit_h = _need(ctx, width, paragraphs)
    top, bottom = TOP_EDGE + 0.75, FOOT - 0.5
    # Under the heading, and the wider gap under the quote (its leading sits above its letters) holding the rule.
    lead = 0.3 if has_heading else 0.0
    after = 0.5
    value = _quote(section, lines)
    size, quote_h = _fit(ctx, value, width, bottom - top - heading_h - lead - after - credit_h, top=32)
    tall = heading_h + lead + quote_h + after + credit_h
    y = _settle(top, bottom - top, tall)
    if has_heading:
        _heading(ctx, section, (x, y, width, heading_h), size=17, colour=panel['muted'], lines=heading_lines)
        y += heading_h + lead
    mark_h = 1.15
    marks(ctx, LEFT + pad + 0.1, y + 0.08, mark_h, mark_colour)
    _say(ctx, (x, y, width, quote_h), value, size, colour=panel['ink'])
    y += quote_h
    rect(ctx, (x, y + 0.29, 0.7, RULE), mark_colour)
    block(ctx, (x, y + after, width, credit_h), paragraphs)


@variant('quote', 'initials')
def initials(ctx, section, lines):
    """A big accent disc at the left with the speaker's initials inside a pale ring, a small mark disc sitting on
    the ring; the heading, quote and speaker in a column to its right."""
    size_disc = 3.0
    centre_x, centre_y = LEFT + 0.55 + size_disc / 2, (TOP_EDGE + FOOT) / 2 + 0.05
    outer = size_disc + 0.55
    fill, ink = _visible(ctx)
    ring(ctx, disc(centre_x, centre_y, outer), 'accent_soft', 2.5)
    oval(ctx, disc(centre_x, centre_y, size_disc), fill)
    letters = _initials(section)
    if letters:
        # A box wide and short enough that all of it is on the disc, clear of the small disc below right.
        figure(ctx, (centre_x - 1.05, centre_y - 0.72, 2.1, 1.44), letters, size=96, colour=ink,
               align='center', anchor='middle', words=2, floor=40, bold=True)
    else:
        mark_h = size_disc * 0.36
        marks(ctx, centre_x - mark_width(mark_h) / 2, centre_y - mark_h / 2, mark_h, ink)
    # A small disc on the ring, at half past four, holds an opening mark in the second colour.
    second = hues(ctx, 2)[1]
    small = 0.92
    sx = sy = outer / 2 * math.cos(math.radians(45))
    sx, sy = centre_x + sx, centre_y + sy
    oval(ctx, disc(sx, sy, small + 0.14), 'surface')
    oval(ctx, disc(sx, sy, small), second['fill'])
    mark_h = small * 0.38
    marks(ctx, sx - mark_width(mark_h) / 2, sy - mark_h / 2, mark_h, second['ink'])

    x = LEFT + 4.3
    width = RIGHT - x
    eyebrow(ctx, (x, TOP_EDGE, 3.0, 0.3))
    heading_h, heading_lines = _heading_tall(ctx, section, width, 20)
    has_heading = heading_h > 0
    paragraphs = _credit(section)
    credit_h = _need(ctx, width, paragraphs)
    top, bottom = 1.05, FOOT - 0.05
    lead, after = (0.3 if has_heading else 0.0), 0.46
    value = _quote(section, lines)
    size, quote_h = _fit(ctx, value, width, bottom - top - heading_h - lead - after - credit_h, top=32)
    tall = heading_h + lead + quote_h + after + credit_h
    y = _settle(top, bottom - top, tall)
    if has_heading:
        _heading(ctx, section, (x, y, width, heading_h), size=20, colour='accent_text', lines=heading_lines)
        y += heading_h + lead
    _say(ctx, (x, y, width, quote_h), value, size)
    y += quote_h
    rule(ctx, (x, y + 0.26, 0.8, RULE), fill)
    block(ctx, (x, y + after, width, credit_h), paragraphs)


@variant('quote', 'bar_left')
def bar_left(ctx, section, lines):
    """A thick accent bar down the left of the quote, set large in the heading face; the speaker after a short
    rule beneath it, and a pale mark in the top right."""
    eyebrow(ctx)
    heading_h, heading_lines = _heading_tall(ctx, section, WIDTH - 3.2, 22)
    _heading(ctx, section, (LEFT, 0.98, WIDTH - 3.2, max(heading_h, 0.7)), size=22, lines=max(heading_lines, 2))
    mark_h = 1.1
    marks(ctx, RIGHT - mark_width(mark_h) - 0.05, 0.78, mark_h, 'accent_soft')
    bar_w, inset = 0.16, 0.55
    x = LEFT + inset
    width = WIDTH - inset - 0.6
    credit = _line_credit(ctx, section, dash=False)
    credit_x = x + 0.95
    credit_h = _need(ctx, RIGHT - credit_x, [dict(text=credit, size=17, bold=True)])
    top, bottom = max(2.05, 0.98 + heading_h + 0.35), FOOT - 0.05
    gap = 0.42
    value = _quote(section, lines)
    size, quote_h = _fit(ctx, value, width, bottom - top - gap - credit_h, top=34)
    tall = quote_h + gap + credit_h
    y = _settle(top, bottom - top, tall)
    fill, _ = _visible(ctx)
    rect(ctx, (LEFT, y + 0.04, bar_w, quote_h - 0.04), fill)
    rect(ctx, (LEFT + bar_w + 0.08, y + 0.04, 0.04, quote_h - 0.04), 'accent_soft')
    _say(ctx, (x, y, width, quote_h), value, size)
    y += quote_h + gap
    if credit:
        first = min(credit_h, 17 * 1.15 / 72 + SLACK)
        rect(ctx, (x, y + first / 2 - RULE / 2, 0.7, RULE), fill)
        text(ctx, (credit_x, y, RIGHT - credit_x, credit_h), credit, size=17, colour='muted', bold=True)


@variant('quote', 'bubble')
def bubble(ctx, section, lines):
    """The quote in a tinted speech bubble with a mark inside its top left and a tail pointing down-left; the
    speaker sits beside the tail."""
    eyebrow(ctx)
    rule(ctx, (LEFT, 0.98, 0.9, RULE))
    _heading(ctx, section, (LEFT, 1.12, WIDTH, 0.7), size=22, lines=2)
    fill = 'accent_soft'
    colours = inks(fill)
    mark_colour = readable(ctx, 'accent', fill, 3.0)
    pad, mark_h = 0.5, 0.66
    x = LEFT + pad + mark_width(mark_h) + 0.42
    width = RIGHT - pad - x
    tail_h = 0.62
    # The speaker lines up with the quote above; the tail, slanting left, is well clear of them.
    credit_x = x
    paragraphs = _credit(section)
    credit_h = _need(ctx, RIGHT - credit_x, paragraphs)
    below = max(tail_h, 0.14 + credit_h)
    top, bottom = 2.05, FOOT - 0.02
    value = _quote(section, lines)
    size, quote_h = _fit(ctx, value, width, bottom - top - 2 * pad - below, top=32)
    card_h = max(quote_h, mark_h + 0.1) + 2 * pad
    y = _settle(top, bottom - top, card_h + below)
    rounded(ctx, (LEFT, y, WIDTH, card_h), fill, radius=0.28)
    polygon(ctx, [(LEFT + 0.95, y + card_h - 0.02), (LEFT + 1.95, y + card_h - 0.02),
                  (LEFT + 0.75, y + card_h + tail_h)], fill)
    marks(ctx, LEFT + pad, y + pad + 0.04, mark_h, mark_colour)
    _say(ctx, (x, y + (card_h - quote_h) / 2, width, quote_h), value, size, colour=colours['ink'])
    block(ctx, (credit_x, y + card_h + 0.14, RIGHT - credit_x, credit_h), paragraphs)


@variant('quote', 'side_heading', accepts=lambda section, lines: bool(str(section.get('heading') or '').strip()))
def side_heading(ctx, section, lines):
    """The heading in a column down the left beside a hairline; a mark, the quote in the heading face and the
    speaker after a short rule on the right."""
    x = header_side(ctx, section, width=3.5, size=30, lines=5) + 0.2
    line(ctx, (LEFT + 3.5 + 0.35, 1.02), (LEFT + 3.5 + 0.35, FOOT - 0.25), 'accent_soft', 1.25)
    width = RIGHT - x
    paragraphs = _credit(section)
    credit_h = _need(ctx, width, paragraphs)
    mark_h, after = 0.72, 0.46
    top, bottom = TOP_EDGE + 0.4, FOOT - 0.05
    value = _quote(section, lines)
    size, quote_h = _fit(ctx, value, width, bottom - top - mark_h - 0.3 - after - credit_h, top=32)
    tall = mark_h + 0.3 + quote_h + after + credit_h
    y = _settle(top, bottom - top, tall)
    marks(ctx, x, y, mark_h, 'accent_text')
    y += mark_h + 0.3
    _say(ctx, (x, y, width, quote_h), value, size)
    y += quote_h
    rule(ctx, (x, y + 0.26, 0.8, RULE))
    block(ctx, (x, y + after, width, credit_h), paragraphs)


@variant('quote', 'corners')
def corners(ctx, section, lines):
    """Heading, quote and attribution framed by solid accent L-shaped corners, one at the top left by the heading
    and one at the bottom right by the right-aligned attribution."""
    eyebrow(ctx)
    pad_x, pad_y = 0.62, 0.52
    fx, box_w = LEFT, WIDTH
    width = box_w - 2 * pad_x
    x = fx + pad_x
    heading_h, heading_lines = _heading_tall(ctx, section, width, 20)
    after_heading = 0.26 if heading_h else 0.0
    credit = _line_credit(ctx, section)
    credit_h = _need(ctx, width, [dict(text=credit, size=16)])
    top, bottom = 1.05, FOOT - 0.02
    gap = 0.3
    value = _quote(section, lines)
    size, quote_h = _fit(ctx, value, width, bottom - top - 2 * pad_y - heading_h - after_heading - gap - credit_h,
                         top=36)
    box_h = 2 * pad_y + heading_h + after_heading + quote_h + gap + credit_h
    fy = _settle(top, bottom - top, box_h)
    thick, arm_x, arm_y = 0.09, 1.3, 0.95
    fill, _ = _visible(ctx)
    rect(ctx, (fx, fy, arm_x, thick), fill)
    rect(ctx, (fx, fy, thick, arm_y), fill)
    rect(ctx, (fx + box_w - arm_x, fy + box_h - thick, arm_x, thick), fill)
    rect(ctx, (fx + box_w - thick, fy + box_h - arm_y, thick, arm_y), fill)
    y = fy + pad_y
    if heading_h:
        _heading(ctx, section, (x, y, width, heading_h), size=20, colour='accent_text', lines=heading_lines)
        y += heading_h + after_heading
    _say(ctx, (x, y, width, quote_h), value, size)
    y += quote_h + gap
    text(ctx, (x, y, width, credit_h), credit, size=16, colour='muted', align='right')


@variant('quote', 'accent_band')
def accent_band(ctx, section, lines):
    """A full-width accent band holds the quote across its whole width in its own ink, a second-colour disc
    with an opening mark breaking its top edge at the left; the speaker below it on the surface."""
    eyebrow(ctx)
    heading_h, heading_lines = _heading_tall(ctx, section, WIDTH, 22, most=2)
    if heading_h:
        _heading(ctx, section, (LEFT, 0.98, WIDTH, heading_h), size=22, lines=heading_lines)
    fill, ink = _visible(ctx)
    second = hues(ctx, 2)[1]
    size_disc, halo = 1.0, 0.1
    pad_x, pad_bottom = 0.6, 0.48
    # The quote starts under the disc's lower half (and the ring of surface round it), at the band's full width.
    pad_top = size_disc / 2 + halo + 0.16
    x, width = LEFT + pad_x, WIDTH - 2 * pad_x
    paragraphs = _credit(section)
    credit_h = _need(ctx, width, paragraphs)
    # The band's top edge: the disc rising above it stays clear of the heading.
    top = (0.98 + heading_h + 0.18 if heading_h else 1.0) + size_disc / 2 + halo
    bottom = FOOT - 0.02
    gap = 0.3
    value = _quote(section, lines)
    size, quote_h = _fit(ctx, value, width, bottom - top - pad_top - pad_bottom - gap - credit_h, top=34)
    band_h = pad_top + quote_h + pad_bottom
    y = _settle(top, bottom - top, band_h + gap + credit_h)
    rect(ctx, (LEFT, y, WIDTH, band_h), fill)
    centre = x + size_disc / 2
    oval(ctx, disc(centre, y, size_disc + 2 * halo), 'surface')
    oval(ctx, disc(centre, y, size_disc), second['fill'])
    mark_h = size_disc * 0.38
    marks(ctx, centre - mark_width(mark_h) / 2, y - mark_h / 2, mark_h, second['ink'])
    _say(ctx, (x, y + pad_top, width, quote_h), value, size, colour=ink)
    block(ctx, (x, y + band_h + gap, width, credit_h), paragraphs)
