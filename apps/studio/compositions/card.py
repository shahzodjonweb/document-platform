"""Card: every slide is a rounded card floating over a soft tinted ground, product style.

The ground is a quiet tint (the accent's deep night in a dark design, the
accent itself in a bold one) and everything that carries text sits on a
rounded card in the surface colour, lifted by a soft layered shadow (a faint
light rim and an accent glow on a dark ground).

On the cover, the closing slide and the dividers a second card of the same size
lies behind the front one, nudged up and right and tilted a few degrees, so its
corners slip out at the top-left and the bottom-right: the composition's
signature. It is the accent element (on a bold deck the accent is the ground,
and the tilted card is the second colour). Content slides, where the gutters
are narrow, keep a straight stack instead: two cards peek out above the
content card, narrower and narrower, the one at the back in the accent.

The cover is a centred card with the title centred on it, three window dots in
its corner, a switch floating on its top edge and a progress chip on its
bottom-left corner; with a photo the card holds the picture as an inset tile on
its right. The chip fills up across the deck: a fifth on the cover, about half
on a divider, full on the closing slide. Dividers are a smaller card with the
section number in a pill; content slides put the whole content area on one
large card, and their photos sit inside it with a margin.

Brand name and slide number stay on the ground on covers, dividers and the
closing slide, in the ink that reads there; on content slides they are on the card.
"""
import math

from . import SLIDE_H, SLIDE_W, Composition, Plan, Text, composition

RADIUS = 0.32          # every card's corner
TILT = 3.5             # degrees, clockwise: the back card's top-left and bottom-right corners slip out
SHIFT = (0.17, -0.1)   # the back card's offset from the front one: its left edge stays hidden

# The content card holds every content layout's text box (x 0.85-12.48, y 0.62-7.14)
# with 0.55 in of padding at the sides, more than the 0.3 in gutter outside it.
CONTENT_CARD = (0.3, 0.36, SLIDE_W - 0.6, 6.96)
CONTENT_STEP, CONTENT_PEEK = 0.7, 0.1   # how much narrower each card of the stack is, and how far it peeks out

# Shadow layers under a card, (spread, drop, alpha): each wider and fainter, faking a blur below it.
SHADOW = ((0.22, 0.14, 0.022), (0.15, 0.11, 0.028), (0.09, 0.08, 0.036), (0.04, 0.05, 0.05))


def _tones(roles):
    """Per theme: the ground and the ink that reads on it, the cards behind, shadow, rim, dots, knob."""
    theme = roles.get('theme')
    if theme == 'dark':
        # A shadow cannot darken a near-black ground: a light rim and an accent glow lift the card.
        return {'ground': 'deep', 'quiet': 'deep_muted', 'back': 'accent', 'middle': ('surface', 0.5),
                'shadow': ('accent', 3.0), 'rim': ('ink', 0.13), 'dot': ('deep_muted', 0.45),
                'knob': 'ink', 'faint': 0.8}
    if theme == 'bold':
        return {'ground': 'accent', 'quiet': 'on_accent', 'back': 'secondary', 'middle': ('surface_alt', None),
                'shadow': ('deep', 1.6), 'rim': None, 'dot': ('on_accent', 0.55), 'knob': 'surface',
                'faint': 0.35}
    return {'ground': 'accent_soft', 'quiet': 'soft_muted', 'back': 'accent', 'middle': ('surface_alt', None),
            'shadow': ('deep', 1.0), 'rim': None, 'dot': ('accent', 0.4), 'knob': 'surface', 'faint': 0.35}


def _rounded_points(box, radius, angle=0.0, segments=8):
    """The outline of a rounded rectangle, turned `angle` degrees clockwise about its centre."""
    x, y, w, h = box
    r = min(radius, w / 2, h / 2)
    centre_x, centre_y = x + w / 2, y + h / 2
    points = []
    # Clockwise from the top-right corner; y grows downward.
    for corner_x, corner_y, start in ((x + w - r, y + r, -90), (x + w - r, y + h - r, 0),
                                      (x + r, y + h - r, 90), (x + r, y + r, 180)):
        for step in range(segments + 1):
            theta = math.radians(start + 90 * step / segments)
            points.append((corner_x + r * math.cos(theta), corner_y + r * math.sin(theta)))
    turn = math.radians(angle)
    cos, sin = math.cos(turn), math.sin(turn)
    return [(centre_x + (px - centre_x) * cos - (py - centre_y) * sin,
             centre_y + (px - centre_x) * sin + (py - centre_y) * cos) for px, py in points]


@composition
class Card(Composition):
    name = 'card'
    # Content photos sit inside the card with a margin, as an inset tile.
    content_box = (CONTENT_CARD[0] + 0.2, CONTENT_CARD[1] + 0.2, CONTENT_CARD[2] - 0.4, CONTENT_CARD[3] - 0.4)

    def ground(self, canvas, kind, photo=False):
        tones = _tones(canvas.roles)
        canvas.background(tones['ground'])
        if kind == 'cover':
            return self._cover(canvas, tones, photo)
        if kind == 'closing':
            return self._closing(canvas, tones)
        if kind == 'section':
            return self._divider(canvas, tones)
        self._stack(canvas, tones, CONTENT_CARD)
        self._card(canvas, tones, CONTENT_CARD)
        return None

    # ------------------------------------------------------------ pieces

    def _accent_ground(self, canvas, tones):
        """On a bold deck the ground is the accent itself: the accent element fills the slide."""
        if tones['back'] != 'accent':
            canvas.accent((0, 0, SLIDE_W, SLIDE_H))

    def _tilted(self, canvas, tones, box):
        """The accent element: a card as big as the front one at `box`, nudged and tilted behind it."""
        self._accent_ground(canvas, tones)
        back = (box[0] + SHIFT[0], box[1] + SHIFT[1], box[2], box[3])
        points = _rounded_points(back, RADIUS, TILT)
        if tones['back'] == 'accent' and len(canvas.slide.shapes):
            raise RuntimeError('The accent element must be the first shape on the slide.')
        canvas.polygon(points, tones['back'])

    def _stack(self, canvas, tones, box):
        """The accent element and a straight stack peeking out above the content card at `box`."""
        x, y, w, h = box
        step, peek = CONTENT_STEP, CONTENT_PEEK
        back = (x + 2 * step, y - 2 * peek, w - 4 * step, h)
        middle = (x + step, y - peek, w - 2 * step, h)
        if tones['back'] == 'accent':
            canvas.accent(back, 'rounded', radius=RADIUS)
        else:
            self._accent_ground(canvas, tones)
            canvas.rounded(back, tones['back'], radius=RADIUS)
        fill, alpha = tones['middle']
        self._rim(canvas, tones, middle)
        canvas.rounded(middle, fill, radius=RADIUS, alpha=alpha)

    def _rim(self, canvas, tones, box, radius=RADIUS):
        """On a dark ground, a faint light edge just outside the card at `box`."""
        if tones['rim']:
            colour, alpha = tones['rim']
            x, y, w, h = box
            canvas.rounded((x - 0.02, y - 0.02, w + 0.04, h + 0.04), colour, radius=radius + 0.02, alpha=alpha)

    def _card(self, canvas, tones, box, radius=RADIUS, fill='surface', line=None, line_width=0.75, lift=1.0):
        """A rounded card with a soft shadow under it (a rim and a glow on a dark ground).

        `lift` scales the shadow: small floating pieces cast a smaller one.
        """
        x, y, w, h = box
        if tones['shadow']:
            colour, strength = tones['shadow']
            for spread, drop, alpha in SHADOW:
                spread, drop = spread * lift, drop * lift
                canvas.rounded((x - spread, y + drop - spread * 0.2, w + 2 * spread, h + spread * 1.2),
                               colour, radius=radius + spread, alpha=min(0.4, alpha * strength))
        self._rim(canvas, tones, box, radius)
        canvas.rounded(box, fill, radius=radius, line=line, line_width=line_width)

    def _dots(self, canvas, tones, left, top, columns, rows, gap=0.24, size=0.06):
        colour, alpha = tones['dot']
        for row in range(rows):
            for column in range(columns):
                canvas.oval((left + column * gap, top + row * gap, size, size), colour, alpha=alpha)

    def _window(self, canvas, tones, left, top):
        """Three small dots in the card's corner, like an app window's controls."""
        for index, (colour, alpha) in enumerate((('accent_text', None), ('secondary', None), ('muted', tones['faint']))):
            canvas.oval((left + index * 0.22, top, 0.13, 0.13), colour, alpha=alpha)

    def _chip(self, canvas, tones, box, fill):
        """A small floating pill holding a progress bar, `fill` of the way along."""
        x, y, w, h = box
        self._card(canvas, tones, box, radius=h / 2, lift=0.5)
        track = (x + 0.22, y + h / 2 - 0.06, w - 0.44, 0.12)
        canvas.rounded(track, 'surface_alt', radius=0.06)
        canvas.rounded((track[0], track[1], max(track[3], track[2] * fill), track[3]), 'accent_text', radius=0.06)

    def _toggle(self, canvas, tones, box):
        """A floating switch: an accent pill with a round knob."""
        x, y, w, h = box
        # On a bold deck's accent ground a ring keeps the switch from melting into it.
        ring = 'surface' if tones['ground'] == 'accent' else None
        self._card(canvas, tones, box, radius=h / 2, fill='accent', line=ring, line_width=2.25, lift=0.5)
        canvas.oval((x + w - h + 0.07, y + 0.07, h - 0.14, h - 0.14), tones['knob'])

    # ------------------------------------------------------------ slides

    def _cover(self, canvas, tones, photo):
        if photo:
            card = (0.75, 1.0, SLIDE_W - 1.5, 5.3)
            self._tilted(canvas, tones, card)
            self._card(canvas, tones, card)
            self._window(canvas, tones, card[0] + 0.38, card[1] + 0.34)
            split, inset = 7.5, 0.2  # where the photo tile starts, and its margin in the card
            picture = (split, card[1] + inset, card[0] + card[2] - inset - split, card[3] - 2 * inset)
            left, width = card[0] + 0.55, split - card[0] - 1.05
            return Plan(
                title=Text((left, 1.9, width, 2.25), 'heading', 34, align='center', anchor='bottom', lines=3),
                rule=((left + width / 2 - 0.45, 4.38, 0.9, 0.06), 'accent_text'),
                subtitle=Text((left + 0.3, 4.62, width - 0.6, 1.2), 'muted', 16, align='center', anchor='top'),
                quiet=tones['quiet'],
                photo=picture)
        card = (1.45, 1.0, SLIDE_W - 2.9, 5.3)
        self._tilted(canvas, tones, card)
        self._card(canvas, tones, card)
        self._window(canvas, tones, card[0] + 0.38, card[1] + 0.34)
        # The chip straddles the card's bottom-left corner, the switch its top edge on the right.
        self._chip(canvas, tones, (0.95, 6.0, 1.62, 0.6), fill=0.2)
        self._toggle(canvas, tones, (10.1, 0.72, 1.12, 0.56))
        return Plan(
            title=Text((2.45, 1.6, SLIDE_W - 4.9, 2.45), 'heading', 44, align='center', anchor='bottom', lines=3),
            rule=((SLIDE_W / 2 - 0.45, 4.32, 0.9, 0.06), 'accent_text'),
            subtitle=Text((3.2, 4.6, SLIDE_W - 6.4, 1.2), 'muted', 17, align='center', anchor='top'),
            quiet=tones['quiet'])

    def _closing(self, canvas, tones):
        card = (2.4, 1.3, SLIDE_W - 4.8, 4.6)
        self._tilted(canvas, tones, card)
        self._dots(canvas, tones, 11.55, 5.7, 5, 3)
        self._card(canvas, tones, card)
        self._window(canvas, tones, card[0] + 0.38, card[1] + 0.34)
        self._chip(canvas, tones, (1.9, 5.6, 1.62, 0.6), fill=1.0)
        self._toggle(canvas, tones, (9.2, 1.02, 1.12, 0.56))
        return Plan(
            title=Text((3.2, 1.9, SLIDE_W - 6.4, 1.85), 'heading', 44, align='center', anchor='bottom', lines=2),
            rule=((SLIDE_W / 2 - 0.45, 3.98, 0.9, 0.06), 'accent_text'),
            subtitle=Text((3.6, 4.25, SLIDE_W - 7.2, 1.0), 'muted', 17, align='center', anchor='top'),
            quiet=tones['quiet'])

    def _divider(self, canvas, tones):
        card = (2.92, 1.75, SLIDE_W - 5.84, 4.2)
        self._tilted(canvas, tones, card)
        self._dots(canvas, tones, 10.95, 4.1, 5, 3)
        self._card(canvas, tones, card)
        self._chip(canvas, tones, (card[0] - 0.5, card[1] + card[3] - 0.28, 1.6, 0.56), fill=0.55)
        pill = (SLIDE_W / 2 - 0.7, card[1] + 0.45, 1.4, 0.62)
        canvas.rounded(pill, 'accent', radius=0.31)
        # Kept clear of the pill's round ends, so the whole box sits on the accent.
        inner = (pill[0] + 0.24, pill[1] + 0.06, pill[2] - 0.48, pill[3] - 0.12)
        left, width = card[0] + 0.6, card[2] - 1.2
        return Plan(
            eyebrow=Text(inner, 'on_accent', 20, align='center', anchor='middle', bold=True, numeral=True),
            title=Text((left, 2.95, width, 2.55), 'heading', 36, align='center', anchor='middle', lines=3),
            title_with_kicker=Text((left, 2.9, width, 1.5), 'heading', 34, align='center', anchor='bottom', lines=2),
            kicker=Text((left + 0.3, 4.65, width - 0.6, 0.9), 'muted', 16, align='center', anchor='top'),
            quiet=tones['quiet'])
