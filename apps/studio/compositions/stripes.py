"""Stripes: retro supergraphics — fat bands with rounded ends, 70s optimism.

The cover is a poster: four bold bands (the accent, the second colour, the
soft tint and the deep tone) drop down the right edge, swing through a wide
quarter-turn together and sweep left across the lower part of the slide to
rounded ends set on a stagger. The title sits above them on the open ground.
With a photo, the picture fills the corner the bands turn around, so they frame
it on two sides; the turn tightens there so the gap stays even round its
square corner. The closing slide bends the same four bands into a rainbow
standing on round feet just above the footer row, its message centred over it.
Dividers hang the bands down the left third like pennants — a wide one carrying
a poster-sized section number, three slim ones stepping up beside it — with the
title on the ground, standing on the numeral's line.

Content slides carry the cover's bend in miniature: three slim bands drop down
the right margin, turn the bottom-right corner and run left under the footer
row to staggered round ends, and a short piece of the same run sits at the top
left above the eyebrow — all outside the text box. On a photo slide the picture
covers the drop and the bands come out from under its bottom edge.

Every band is held off its ground: a band too close to the ground in lightness
(a navy accent on a dark deck, a cream tint on paper) is pushed away from it
until it reads as a band. On a dark deck the deep tone would vanish, so the
innermost band is the light ink instead. On a bold deck the ground of the
cover, dividers and closing is the accent itself; the band that leads (and
carries the divider's numeral) is the paper or the deep tone, whichever stands
out more, followed by the second colour, the soft tint and a tone of the
accent, never two look-alikes side by side.
"""
import math

from ..slides import _reads_on, contrast_ratio
from . import SLIDE_H, SLIDE_W, Composition, Plan, Text, composition

BAND = 0.46       # one band's thickness
GAP = 0.12        # between bands
BASE = 6.55       # bands stop here, above the footer row, which stays on the ground
LEFT = 0.85       # the text margin every layout uses
STACK = 4 * BAND + 3 * GAP
# How far a band stands off its ground (contrast ratio); a dark ground swallows
# dim colours, so bands stand further off it.
LIFT, LIFT_DARK = 1.8, 2.6

# Content slides: the cover's bands in miniature, keeping its gap-to-band ratio.
SLIM, SLIM_GAP = 0.075, 0.02
SLIM_STACK = 3 * SLIM + 2 * SLIM_GAP
SLIM_TOP = 7.18   # the run along the bottom starts below the footer row (which ends at 7.14)
SLIM_MARGIN = SLIDE_H - SLIM_TOP - SLIM_STACK  # the same margin to the bottom and the right edge
SLIM_TURN = 0.35  # the innermost band's turn radius at the corner
# Ink roles a band's text may take; the one that reads best on the band is used.
INKS = ('on_accent', 'on_deep', 'on_secondary', 'ink', 'soft_ink', 'card_ink')


def _arc(centre, radius, start, end, steps=None):
    """Points along a circle from `start` to `end` degrees (y down, 0 = right, 90 = down)."""
    steps = steps or max(8, int(abs(end - start) / 90 * (10 + 10 * radius)))
    x, y = centre
    return [(x + radius * math.cos(math.radians(start + (end - start) * i / steps)),
             y + radius * math.sin(math.radians(start + (end - start) * i / steps))) for i in range(steps + 1)]


def _apart(one, other, distance=48):
    """Whether two hex colours look different side by side."""
    channels = [(int(one[i:i + 2], 16) - int(other[i:i + 2], 16)) for i in (0, 2, 4)]
    return math.sqrt(sum(value * value for value in channels)) >= distance


def _bands(canvas, candidates, ground, count):
    """`count` band colours (hex) from `candidates`, each lifted off `ground`, no look-alikes adjacent."""
    floor = canvas.colour(ground)
    lift = LIFT_DARK if contrast_ratio(floor, '000000') < 2.2 else LIFT
    pool = [_reads_on(canvas.colour(role), floor, lift) for role in candidates]
    bands = []
    while pool and len(bands) < count:
        pick = next((colour for colour in pool if not bands or _apart(colour, bands[-1])), pool[0])
        pool.remove(pick)
        bands.append(pick)
    return bands


def _ink(canvas, fill):
    """The ink role that reads best on `fill` (a hex colour)."""
    return max(INKS, key=lambda role: contrast_ratio(canvas.colour(role), fill))


def _scheme(canvas):
    """The ground, the four band colours (outside in), and the text roles on the ground."""
    roles = canvas.roles
    if roles.get('theme') == 'bold':
        # The paper or the deep tone, whichever stands out more on the accent, leads.
        paper = contrast_ratio(roles['surface'], roles['accent']) >= contrast_ratio(roles['deep'], roles['accent'])
        lead, other = ('surface', 'deep') if paper else ('deep', 'surface')
        # 'accent' lifted off the accent ground is a tone of it: rust on orange, mustard on yellow.
        candidates = (lead, 'secondary', 'accent_soft', 'accent', other)
        scheme = {'ground': 'accent', 'title': 'on_accent', 'muted': 'on_accent', 'quiet': 'on_accent'}
    else:
        # The deep tone all but vanishes on a dark ground; the light ink takes its place.
        last = 'ink' if roles.get('theme') == 'dark' else 'deep'
        candidates = ('accent', 'secondary', 'accent_soft', last)
        scheme = {'ground': 'surface', 'title': 'heading', 'muted': 'muted', 'quiet': 'muted'}
    scheme['bands'] = _bands(canvas, candidates, scheme['ground'], 4)
    return scheme


def _ground(canvas, scheme):
    """The slide's ground; on a bold deck the accent element is the ground itself."""
    canvas.background(scheme['ground'])
    if scheme['ground'] == 'accent':
        canvas.accent((0, 0, SLIDE_W, SLIDE_H))
        return True
    return False


def _bend(centre, inner, outer, end):
    """A band dropping from the top edge, turning about `centre` and running left to a round end at `end`."""
    cx, cy = centre
    middle, cap = cy + (inner + outer) / 2, (outer - inner) / 2
    return ([(cx + inner, 0), (cx + outer, 0)]
            + _arc(centre, outer, 0, 90)
            + _arc((end + cap, middle), cap, 90, 270)
            + _arc(centre, inner, 90, 0))


def _pill(left, top, width, height):
    """A horizontal band with round ends."""
    cap = height / 2
    return (_arc((left + width - cap, top + cap), cap, -90, 90)
            + _arc((left + cap, top + cap), cap, 90, 270))


def _hang(left, width, bottom):
    """A vertical band hanging from the top edge to a round end at y `bottom`."""
    cap = width / 2
    return [(left, 0), (left + width, 0)] + _arc((left + cap, bottom - cap), cap, 0, 180)


def _ring(centre, inner, outer):
    """One band of a rainbow: half an annulus over `centre`, its feet rounded like a band's end."""
    cx, cy = centre
    cap = (outer - inner) / 2
    return (_arc(centre, outer, 180, 360)
            + _arc((cx + inner + cap, cy), cap, 0, 180)
            + _arc(centre, inner, 360, 180)
            + _arc((cx - inner - cap, cy), cap, 0, 180))


@composition
class Stripes(Composition):
    name = 'stripes'

    def ground(self, canvas, kind, photo=False):
        if kind == 'cover':
            return self._cover(canvas, _scheme(canvas), photo)
        if kind == 'closing':
            return self._closing(canvas, _scheme(canvas))
        if kind == 'section':
            return self._divider(canvas, _scheme(canvas))
        return self._content(canvas)

    # ------------------------------------------------------------ cover

    def _cover(self, canvas, scheme, photo):
        bold = _ground(canvas, scheme)
        # The turn: the outermost band reaches the base line and the right margin.
        # A wide turn gives the 70s swoop; round a photo's square corner it
        # tightens, so the gap to the picture stays even all the way round.
        inner = 0.3 if photo else 0.8
        outer = inner + STACK
        centre = (SLIDE_W - 0.45 - outer, BASE - outer)
        cx, cy = centre
        for index, colour in enumerate(scheme['bands']):
            r_out = outer - index * (BAND + GAP)
            # Inner bands reach further left: the round ends step out to the margin.
            end = LEFT + 0.42 * (3 - index)
            if index == 0 and not bold:
                # The accent element, wholly inside the outer band's drop.
                canvas.accent((cx + r_out - BAND + 0.03, 0, BAND - 0.06, cy), 'rect')
            canvas.polygon(_bend(centre, r_out - BAND, r_out, end), colour)
        if photo:
            # The picture fills the corner the bands turn around, the same gap on both sides.
            gap = 0.22
            left, right, bottom = 6.4, cx + inner - gap, cy + inner - gap
            width = left - 0.45 - LEFT
            return Plan(
                title=Text((LEFT, 0.7, width, 2.4), scheme['title'], 36, anchor='bottom', lines=4),
                subtitle=Text((LEFT, 3.25, width, 0.62), scheme['muted'], 16, anchor='top'),
                quiet=scheme['quiet'],
                photo=(left, 0, right - left, bottom))
        width = cx + inner - 0.7 - LEFT
        return Plan(
            title=Text((LEFT, 0.7, width, 2.3), scheme['title'], 44, anchor='bottom', lines=3),
            subtitle=Text((LEFT, 3.18, width, 0.62), scheme['muted'], 17, anchor='top'),
            quiet=scheme['quiet'])

    # ------------------------------------------------------------ closing

    def _closing(self, canvas, scheme):
        bold = _ground(canvas, scheme)
        outer = 3.3
        # The round feet stand on the base line.
        centre = (SLIDE_W / 2, BASE - BAND / 2)
        for index, colour in enumerate(scheme['bands']):
            r_out = outer - index * (BAND + GAP)
            if index == 0 and not bold:
                # A leg of the outer arch, wholly inside it.
                canvas.accent((centre[0] - r_out + 0.06, centre[1] - 0.3, BAND - 0.12, 0.3), 'rect')
            canvas.polygon(_ring(centre, r_out - BAND, r_out), colour)
        # The message stands clear above the arch rather than pressed onto it.
        return Plan(
            title=Text((1.2, 0.3, SLIDE_W - 2.4, 1.7), scheme['title'], 44, align='center', anchor='bottom',
                       lines=2),
            subtitle=Text((1.8, 2.08, SLIDE_W - 3.6, 0.5), scheme['muted'], 17, align='center', anchor='top'),
            quiet=scheme['quiet'])

    # ------------------------------------------------------------ divider

    def _divider(self, canvas, scheme):
        bold = _ground(canvas, scheme)
        wide, wide_left, wide_bottom = 2.3, 0.6, 6.0
        colours = scheme['bands']
        if not bold:
            canvas.accent((wide_left + 0.03, 0, wide - 0.06, wide_bottom - wide / 2), 'rect')
        canvas.polygon(_hang(wide_left, wide, wide_bottom), colours[0])
        left = wide_left + wide + GAP
        for index, colour in enumerate(colours[1:]):
            canvas.polygon(_hang(left, BAND, wide_bottom - 0.6 * (index + 1)), colour)
            left += BAND + GAP
        text_left = 5.35
        width = SLIDE_W - 0.85 - text_left
        number_bottom = wide_bottom - wide / 2 - 0.1
        return Plan(
            # A poster numeral filling the pennant, its foot on the title's line.
            eyebrow=Text((wide_left + 0.1, number_bottom - 1.75, wide - 0.2, 1.75), _ink(canvas, colours[0]), 110,
                         align='center', anchor='bottom', numeral=True),
            title=Text((text_left, 1.55, width, number_bottom - 1.55), scheme['title'], 40, anchor='bottom', lines=3),
            title_with_kicker=Text((text_left, 1.55, width, number_bottom - 1.55), scheme['title'], 38,
                                   anchor='bottom', lines=3),
            kicker=Text((text_left, number_bottom + 0.2, width, 0.9), scheme['muted'], 17, anchor='top'),
            quiet=scheme['quiet'])

    # ------------------------------------------------------------ content

    def _content(self, canvas):
        canvas.background('surface')
        third = 'accent_soft' if canvas.roles.get('theme') == 'dark' else 'deep'
        # Outside in, as on the cover: the accent outermost.
        trio = _bands(canvas, ('accent', 'secondary', third), 'surface', 3)
        # The cover's bend in miniature: down the right margin, round the corner,
        # left under the footer row to round ends stepping out to the margin.
        outer, right = SLIM_TURN + SLIM_STACK, SLIDE_W - SLIM_MARGIN
        centre = (right - outer, SLIM_TOP + SLIM_STACK - outer)
        canvas.accent((right - SLIM + 0.015, 0, SLIM - 0.03, centre[1]), 'rect')
        for index, colour in enumerate(trio):
            r_out = outer - index * (SLIM + SLIM_GAP)
            canvas.polygon(_bend(centre, r_out - SLIM, r_out, LEFT + 0.3 * (2 - index)), colour)
        # A short piece of the same run at the top left, above the eyebrow:
        # right ends together, round left ends stepping in as on the cover.
        right = 2.25
        for row, colour in enumerate(reversed(trio)):
            start = LEFT + 0.25 * row
            canvas.polygon(_pill(start, 0.16 + row * (SLIM + SLIM_GAP), right - start, SLIM), colour)
        return None
