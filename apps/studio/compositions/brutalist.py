"""Brutalist: neo-brutalism — flat colour, thick ink outlines, hard offset shadows, stickers.

Every piece of the deck is a flat card with a heavy ink outline and a solid
slab of colour knocked out behind it, a little down and to the right, as if
cut from paper and stacked. Covers and closing slides set the title in
chunky capitals on a white card over a bright ground, with a starburst, a
round sticker and four-point sparkles stuck on; dividers are a bento of two
cards, a tall one holding the section number in huge figures and a wide one
holding the title; an outlined ribbon bleeds off the foot of each and carries
the brand name. Content slides sit on one outlined card with its slab, topped
by a window bar with three dots and a starburst sticker on its corner, on a
ground of the design's colour, so the layouts keep their places and pictures
stay inside the card, under the bar.
"""
import math

from . import SLIDE_H, SLIDE_W, Composition, Plan, Text, composition

STROKE = 3.0     # every outline, in points
EDGE = STROKE / 144  # half an outline, in inches: where a card's inside begins
OFFSET = 0.18    # the hard shadow, down and to the right, in inches
# The ribbon along the foot of covers, closings and dividers, around the brand
# name and number (6.82-7.14). It bleeds off the bottom edge.
TICKER, TICKER_END = 6.50, 7.6
MARKS_Y = 6.98
CARD_TOP, CARD_BOTTOM = 0.85, 6.0
# The content card: the whole text area (0.85-12.48 x 0.62-7.14) with room around it,
# and the window bar across its top, which ends above the eyebrow at 0.62.
PANEL = (0.45, 0.2, 12.43, 7.06)
PANEL_OFFSET = 0.15
BAR = (PANEL[0], PANEL[1], PANEL[2], 0.34)
# The starburst sticker on the content card's top right corner, right of the text (x <= 12.48).
STICKER, STICKER_R = (12.88, 0.37), 0.36

# The ink and the quieter ink for text on each fill.
INK = {'surface': ('ink', 'muted'), 'accent': ('on_accent', 'on_accent'),
       'secondary': ('on_secondary', 'on_secondary'), 'deep': ('on_deep', 'deep_muted'),
       'accent_soft': ('soft_ink', 'soft_muted')}

# Per theme and kind of slide: the ground, the solid shadow behind every card,
# the divider's number card, the starbursts, the ribbon at the foot and its
# marks, the content card's window bar. The accent element is always the
# first shape: the ground when it is the accent, else the ribbon (dark covers),
# else the first card's shadow.
SCHEMES = {
    'light': {
        'cover': dict(ground='secondary', shadow='accent', burst='accent', ticker='deep', marks='secondary'),
        'section': dict(ground='accent', shadow='deep', number='secondary', ticker='secondary', marks='deep'),
        'content': dict(ground='secondary', shadow='accent', bar='accent', sticker='surface', star='accent'),
    },
    'bold': {
        'cover': dict(ground='accent', shadow='secondary', burst='secondary', ticker='secondary', marks='deep'),
        'section': dict(ground='secondary', shadow='accent', number='deep', ticker='deep', marks='secondary'),
        'content': dict(ground='accent', shadow='secondary', bar='secondary', sticker='deep'),
    },
    'dark': {
        'cover': dict(ground='deep', shadow='secondary', burst='secondary', ticker='accent', marks='secondary'),
        'section': dict(ground='accent', shadow='deep', number='secondary', ticker='secondary', marks='deep'),
        'content': dict(ground='accent', shadow='secondary', bar='secondary', sticker='deep'),
    },
}


@composition
class Brutalist(Composition):
    name = 'brutalist'
    # Pictures sit inside the content card's outline, under the window bar.
    content_box = (PANEL[0] + EDGE, BAR[1] + BAR[3] + EDGE, PANEL[2] - 2 * EDGE,
                   PANEL[3] - BAR[3] - 2 * EDGE)

    def ground(self, canvas, kind, photo=False):
        schemes = SCHEMES.get(canvas.roles.get('theme'), SCHEMES['light'])
        if kind == 'cover':
            return self._cover(canvas, schemes['cover'], photo)
        if kind == 'closing':
            return self._closing(canvas, schemes['cover'])
        if kind == 'section':
            return self._divider(canvas, schemes['section'])
        scheme = schemes['content']
        _ground(canvas, scheme)
        _card(canvas, PANEL, 'surface', scheme['shadow'], offset=PANEL_OFFSET)
        # A window bar across the card's top edge, three dots at its left,
        # and a starburst stuck on its right end.
        canvas.rect(BAR, scheme['bar'], line='ink', line_width=STROKE)
        middle = BAR[1] + BAR[3] / 2
        for step in range(3):
            centre = PANEL[0] + 0.3 + step * 0.24
            canvas.oval((centre - 0.08, middle - 0.08, 0.16, 0.16), 'surface', line='ink',
                        line_width=STROKE * 0.5)
        _burst(canvas, STICKER, STICKER_R, scheme['sticker'])
        _sparkle(canvas, STICKER, 0.17, scheme.get('star', _pop(canvas)))
        return None

    # ------------------------------------------------------------ cover

    def _cover(self, canvas, scheme, photo):
        _ground(canvas, scheme)
        right = 7.55 if photo else 9.05
        card = (0.85, CARD_TOP, right - 0.85, CARD_BOTTOM - CARD_TOP)
        _card(canvas, card, 'surface', scheme['shadow'])
        picture = None
        if photo:
            frame = (right + 0.45, CARD_TOP, 12.48 - right - 0.45, CARD_BOTTOM - CARD_TOP)
            _card(canvas, frame, 'surface', scheme['shadow'])
            picture = (frame[0] + EDGE, frame[1] + EDGE, frame[2] - 2 * EDGE, frame[3] - 2 * EDGE)
            # A starburst on the title card's lower left corner, clear of the subtitle (x >= 1.4).
            _burst(canvas, (0.85, 5.95), 0.5, scheme['burst'])
            _sparkle(canvas, (0.85, 5.95), 0.26, 'surface')
        else:
            # A starburst stuck over the card's edge and a round sticker below it.
            _burst(canvas, (10.25, 2.3), 1.55, scheme['burst'])
            _sparkle(canvas, (10.25, 2.3), 0.82, 'surface')
            _badge(canvas, (11.45, 4.8), 0.72, scheme['shadow'], scheme['burst'])
        _sparkle(canvas, (card[0], card[1]), 0.42, _pop(canvas))
        ink, muted = INK['surface']
        width = right - 0.85 - 1.05
        _ticker(canvas, scheme, numbered=False)
        return Plan(
            title=Text((1.4, 1.3, width, 3.1), ink, 40, anchor='bottom', lines=4, upper=True, bold=True),
            rule=((1.4, 4.66, 1.5, 0.14), 'accent_text'),
            subtitle=Text((1.4, 4.98, width, 0.72), muted, 17, anchor='top'),
            quiet=INK[scheme['ticker']][0],
            photo=picture)

    # ------------------------------------------------------------ closing

    def _closing(self, canvas, scheme):
        _ground(canvas, scheme)
        card = (2.2, 1.05, SLIDE_W - 4.4, 4.6)
        corner = (card[0] + card[2] - 0.1, card[1] + 0.05)
        _card(canvas, card, 'surface', scheme['shadow'])
        _burst(canvas, corner, 0.95, scheme['burst'])
        _sparkle(canvas, corner, 0.5, 'surface')
        _sparkle(canvas, (card[0] + 0.02, card[1] + card[3] - 0.02), 0.5, _pop(canvas))
        ink, muted = INK['surface']
        _ticker(canvas, scheme)
        # The text stays well clear of the starburst on the card's corner.
        left, width = card[0] + 1.2, card[2] - 2.4
        return Plan(
            title=Text((left, 1.45, width, 2.05), ink, 60, align='center', anchor='bottom', lines=2,
                       upper=True, bold=True),
            rule=((SLIDE_W / 2 - 0.75, 3.72, 1.5, 0.14), 'accent_text'),
            subtitle=Text((left, 4.04, width, 0.8), muted, 18, align='center', anchor='top'),
            quiet=INK[scheme['ticker']][0])

    # ------------------------------------------------------------ divider

    def _divider(self, canvas, scheme):
        _ground(canvas, scheme)
        height = CARD_BOTTOM - CARD_TOP
        number = (0.85, CARD_TOP, 3.6, height)
        title = (4.95, CARD_TOP, 12.48 - 4.95, height)
        _card(canvas, number, scheme['number'], scheme['shadow'])
        _card(canvas, title, 'surface', scheme['shadow'])
        _sparkle(canvas, (title[0] + title[2], title[1]), 0.42, scheme['number'])
        on_number = INK[scheme['number']][0]
        ink, muted = INK['surface']
        _ticker(canvas, scheme)
        left, width = title[0] + 0.6, title[2] - 1.2
        return Plan(
            eyebrow=Text((number[0] + 0.2, 1.3, number[2] - 0.4, 4.25), on_number, 150, align='center',
                         anchor='middle', numeral=True, bold=True),
            title=Text((left, 1.4, width, 4.05), ink, 40, anchor='middle', lines=3, upper=True, bold=True),
            title_with_kicker=Text((left, 1.4, width, 2.55), ink, 36, anchor='bottom', lines=3, upper=True,
                                   bold=True),
            kicker=Text((left, 4.2, width, 1.25), muted, 18, anchor='top'),
            quiet=INK[scheme['ticker']][0])


# ---------------------------------------------------------------- drawing


def _ground(canvas, scheme):
    """The slide's ground. When the ground is the accent it is the accent element;
    when the ribbon is, the ribbon goes down first."""
    canvas.background(scheme['ground'])
    if scheme['ground'] == 'accent':
        canvas.accent((0, 0, SLIDE_W, SLIDE_H))
    elif scheme.get('ticker') == 'accent':
        _ribbon(canvas, scheme)


def _dark(canvas):
    return canvas.roles.get('theme') == 'dark'


def _pop(canvas):
    """A sparkle's fill over the ground: white, or the second colour where white
    would read as a hollow outline (dark decks, whose ink is white)."""
    return 'secondary' if _dark(canvas) else 'surface'


def _slab(canvas, box, fill, shape='rect'):
    """A hard shadow: outlined like the card in light decks, a solid slab in dark ones,
    whose white ink would make it a second frame. The first accent fill is the accent element."""
    line = None if _dark(canvas) else 'ink'
    if fill == 'accent' and not len(canvas.slide.shapes):
        return canvas.accent(box, shape, line=line, line_width=STROKE)
    return canvas.shape(shape, box, fill, line=line, line_width=STROKE)


def _card(canvas, box, fill, shadow, offset=OFFSET):
    """A flat card with a heavy outline and a solid shadow knocked out behind it."""
    left, top, width, height = box
    _slab(canvas, (left + offset, top + offset, width, height), shadow)
    canvas.rect(box, fill, line='ink', line_width=STROKE)


def _badge(canvas, centre, radius, shadow, star):
    """A round sticker: an outlined disc with its own slab, an inner ring and a sparkle."""
    cx, cy = centre
    box = (cx - radius, cy - radius, 2 * radius, 2 * radius)
    _slab(canvas, (box[0] + 0.12, box[1] + 0.12, box[2], box[3]), shadow, 'oval')
    canvas.oval(box, 'surface', line='ink', line_width=STROKE)
    inner = radius - 0.11
    canvas.oval((cx - inner, cy - inner, 2 * inner, 2 * inner), None, line='ink', line_width=STROKE * 0.4)
    _sparkle(canvas, centre, 0.32, star)


def _ribbon(canvas, scheme):
    """The outlined ribbon across the foot, bleeding off the bottom and both sides."""
    box = (-0.1, TICKER, SLIDE_W + 0.2, TICKER_END - TICKER)
    if scheme['ticker'] == 'accent' and not len(canvas.slide.shapes):
        return canvas.accent(box, line='ink', line_width=STROKE)
    return canvas.rect(box, scheme['ticker'], line='ink', line_width=STROKE)


def _ticker(canvas, scheme, numbered=True):
    """The ribbon (unless it went down first, as the accent element) and its row of small sparkles."""
    if scheme['ticker'] != 'accent' or scheme['ground'] == 'accent':
        _ribbon(canvas, scheme)
    count = 4 if numbered else 6
    for step in range(count):
        _sparkle(canvas, ((11.15 if numbered else 12.35) - (count - 1 - step) * 0.5, MARKS_Y), 0.13,
                 scheme['marks'], line=None)


def _sparkle(canvas, centre, radius, fill, line='ink'):
    """A four-point star with curved sides."""
    cx, cy = centre
    points = []
    for step in range(64):
        angle = 2 * math.pi * step / 64
        c, s = math.cos(angle), math.sin(angle)
        points.append((cx + radius * math.copysign(abs(c) ** 2.6, c),
                       cy + radius * math.copysign(abs(s) ** 2.6, s)))
    return canvas.polygon(points, fill, line=line, line_width=STROKE * 0.7 if line else 1.0)


def _burst(canvas, centre, radius, fill, spikes=16, depth=0.8):
    """A starburst sticker."""
    cx, cy = centre
    points = []
    for step in range(spikes * 2):
        angle = math.pi * step / spikes - math.pi / 2
        reach = radius if step % 2 == 0 else radius * depth
        points.append((cx + reach * math.cos(angle), cy + reach * math.sin(angle)))
    return canvas.polygon(points, fill, line='ink', line_width=STROKE)
