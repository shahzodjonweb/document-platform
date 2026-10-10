"""Glow: night and light — luminous orbs glowing on a deep ground.

Cover, dividers and closing slide are night: the deep version of the accent
edge to edge, with large orbs of light bleeding off the edges in the design's
two colours, made luminous — the hue kept, the colour saturated and lifted
until it reads as light on the night — the brighter one the largest. Each orb
is a crisp disc of that light in a soft glow (one picture that fades to
nothing at its rim), and where two orbs overlap their light mixes. A small
pale moon in its own glow keeps the big light company, and a few stars sit in
the dark. Text never touches the light: titles sit on the plain night in the
ink that reads there, and every glow's picture is checked clear of every text
box.

The cover sets its title on the left with the light gathered top right; with
a photo, the picture glows like a lit window on the right, an orb rising
behind its corner and the moon in the gutter above. A divider is an eclipse:
a dark disc holding the section number slides across a disc of light, leaving
a thin crescent and a corona around it. The closing slide centres its message
under light hanging from the top corner, a second orb rising on the left.
Content slides stay plain — the surface, and in the top-right corner, outside
the text, the eclipse again in small: a quarter disc of the accent with a thin
crescent of the light behind it, glowing.

On a bold deck the ground is the accent itself, the lights are the second
colour, lifted towards white, and the pale surface, and the moon and the
eclipse's disc are the deep night in a pale glow.

Every fill is opaque, pre-mixed with what lies under it (an orb over the
night, the overlap of two orbs), and every glow is a picture: PowerPoint, the
checker and the previews all draw the same colours.
"""
import io
import math

from ..slides import _from_hls, _hls, contrast_ratio
from . import FOOTER, NUMBER, SLIDE_H, SLIDE_W, Composition, Plan, Text, _emu, composition

GAP = 0.15        # the least room kept between a glow's picture (or any light) and a text box
GLOW_PPI = 40     # a glow is soft: a coarse picture scales up smoothly
CHROME = (FOOTER, NUMBER)
_PNGS = {}


# ---------------------------------------------------------------- colour


def _channels(value):
    value = value.lstrip('#')
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _hex(channels):
    return '%02X%02X%02X' % tuple(max(0, min(255, round(c))) for c in channels)


def _over(top, bottom, alpha):
    """`top` laid over `bottom` at `alpha`: the colour a translucent fill shows."""
    return _hex(t * alpha + b * (1 - alpha) for t, b in zip(_channels(top), _channels(bottom)))


def _screen(one, other):
    """Two lights added: each lets the other through where it is not already bright."""
    return _hex(255 - (255 - a) * (255 - b) / 255 for a, b in zip(_channels(one), _channels(other)))


def _tint(value, share):
    """`value` moved `share` of the way to white."""
    return _over('FFFFFF', value, share)


def _shade(value, share):
    """`value` made `share` darker."""
    return _over('000000', value, share)


def _luminous(value, ground, target=3.5):
    """`value` as light on `ground`: its hue, saturated, lifted until it stands 3.5:1 off the ground."""
    hue, lightness, saturation = _hls(value)
    if saturation >= 0.08:          # a grey has no colour to saturate; it is lifted only
        saturation = max(saturation, 0.7)
    lightness = max(lightness, 0.45)
    colour = _from_hls(hue, lightness, saturation)
    while contrast_ratio(colour, ground) < target and lightness < 0.85:
        lightness += 0.01
        colour = _from_hls(hue, lightness, saturation)
    return colour


def _visible_on(colour, surface, target=1.8):
    """`colour` darkened, keeping its hue, until it shows on a light `surface`; as it is on a dark one."""
    hue, lightness, saturation = _hls(colour)
    while contrast_ratio(colour, surface) < target and lightness > 0.2:
        lightness -= 0.02
        colour = _from_hls(hue, lightness, saturation)
    return colour


def _scheme(canvas):
    """The colours of the night slides, as hex, and the roles of the text set on them.

    `lead` is the brighter light (the big orb), `second` the other; `moon` the
    small companion disc and its glow; `disc` the eclipse's dark disc;
    `spark` the stars.
    """
    roles = canvas.roles
    if roles.get('theme') == 'bold':
        # The ground is the accent; light on it is the second colour lifted
        # towards white, and the pale surface. The moon is the night.
        ground = roles['accent']
        return {'ground': ground, 'lead': _tint(roles['secondary'], 0.18), 'second': roles['surface'],
                'moon': roles['deep'], 'moon_glow': roles['surface'], 'spark': roles['surface'],
                'disc': roles['deep'], 'sun': roles['surface'], 'corona': roles['surface'],
                'ink': 'on_accent', 'muted': 'on_accent', 'quiet': 'on_accent'}
    ground = roles['deep']
    lead, second = sorted((_luminous(roles['accent'], ground), _luminous(roles['secondary'], ground)),
                          key=lambda colour: -contrast_ratio(colour, ground))
    moon = _tint(roles['deep_muted'], 0.35)
    return {'ground': ground, 'lead': lead, 'second': second,
            'moon': moon, 'moon_glow': moon, 'spark': roles['on_deep'],
            'disc': _shade(ground, 0.45), 'sun': _tint(lead, 0.3), 'corona': _tint(lead, 0.15),
            'ink': 'on_deep', 'muted': 'deep_muted', 'quiet': 'deep_muted'}


# ---------------------------------------------------------------- geometry


def _box(centre, radius):
    return (centre[0] - radius, centre[1] - radius, 2 * radius, 2 * radius)


def _near(one, other, gap):
    return (one[0] < other[0] + other[2] + gap and other[0] < one[0] + one[2] + gap
            and one[1] < other[1] + other[3] + gap and other[1] < one[1] + one[3] + gap)


def _lens(one, r1, two, r2, steps=360):
    """The points (inches) of the overlap of two discs, in order round it; None if they do not meet."""
    (x1, y1), (x2, y2) = one, two
    apart = math.hypot(x2 - x1, y2 - y1)
    if apart >= r1 + r2 - 1e-6:
        return None
    points = []
    for step in range(steps):
        angle = 2 * math.pi * step / steps
        p = (x1 + r1 * math.cos(angle), y1 + r1 * math.sin(angle))
        if math.hypot(p[0] - x2, p[1] - y2) <= r2:
            points.append(p)
        q = (x2 + r2 * math.cos(angle), y2 + r2 * math.sin(angle))
        if math.hypot(q[0] - x1, q[1] - y1) <= r1:
            points.append(q)
    if apart > abs(r1 - r2):
        # The two crossing points, so the lens meets its own corners exactly.
        along = (r1 ** 2 - r2 ** 2 + apart ** 2) / (2 * apart)
        across = math.sqrt(max(0.0, r1 ** 2 - along ** 2))
        mx, my = x1 + along * (x2 - x1) / apart, y1 + along * (y2 - y1) / apart
        points += [(mx + across * (y2 - y1) / apart, my - across * (x2 - x1) / apart),
                   (mx - across * (y2 - y1) / apart, my + across * (x2 - x1) / apart)]
    if len(points) < 3:
        return None
    cx = sum(x for x, _ in points) / len(points)
    cy = sum(y for _, y in points) / len(points)
    return sorted(points, key=lambda point: math.atan2(point[1] - cy, point[0] - cx))


# ---------------------------------------------------------------- glow pictures


def _png(pixels):
    from PIL import Image
    buffer = io.BytesIO()
    Image.fromarray(pixels, 'RGBA').save(buffer, 'PNG', optimize=True)
    return buffer.getvalue()


def _glow_png(width, height, shape, colour, peak, power, core=None):
    """A soft glow `width` x `height` inches in `colour`: alpha `peak` at the light's edge,
    falling as (1 - t) ** power to nothing `reach` inches out.

    `shape` is ('disc', cx, cy, radius, reach) or ('frame', left, top, right, bottom, reach),
    in inches within the picture. Over the light itself the alpha stays `peak`
    or, with `core` (alpha, whiten), rises towards the centre of a disc to
    `alpha`, the colour paling `whiten` of the way to white: a lit core.
    """
    key = (round(width, 3), round(height, 3), shape, colour, peak, power, core)
    if key in _PNGS:
        return _PNGS[key]
    import numpy
    w, h = max(2, round(width * GLOW_PPI)), max(2, round(height * GLOW_PPI))
    xs, ys = numpy.meshgrid((numpy.arange(w) + 0.5) / GLOW_PPI, (numpy.arange(h) + 0.5) / GLOW_PPI)
    rgb = numpy.empty((h, w, 3))
    rgb[...] = numpy.array(_channels(colour), float)
    if shape[0] == 'disc':
        _, cx, cy, radius, reach = shape
        distance = numpy.hypot(xs - cx, ys - cy)
        outside = distance - radius
    else:
        _, left, top, right, bottom, reach = shape
        dx = numpy.maximum(numpy.maximum(left - xs, xs - right), 0)
        dy = numpy.maximum(numpy.maximum(top - ys, ys - bottom), 0)
        outside = numpy.hypot(dx, dy)
    t = numpy.clip(outside / max(reach, 1e-6), 0, 1)
    alpha = peak * (1 - t) ** power
    if core and shape[0] == 'disc':
        centre_alpha, whiten = core
        inner = numpy.clip(1 - (distance / max(radius, 1e-6)) ** 2, 0, 1) ** 1.3
        alpha = alpha + (centre_alpha - peak) * inner
        rgb = rgb + (255 - rgb) * (whiten * inner)[..., None]
    pixels = numpy.dstack([rgb, alpha * 255]).round().clip(0, 255).astype(numpy.uint8)
    _PNGS[key] = _png(pixels)
    return _PNGS[key]


def _picture(canvas, box, data):
    element = canvas.slide.shapes.add_picture(io.BytesIO(data), *_emu(box))
    canvas.drawn.append(element)
    return element


def _glow(canvas, bounds, shape, colour, peak, power, keep_clear, core=None):
    """A glow picture over `bounds` (inches, cut to the slide); raises if it would reach a text box."""
    left, top, right, bottom = bounds
    left, top = max(0.0, left), max(0.0, top)
    right, bottom = min(SLIDE_W, right), min(SLIDE_H, bottom)
    if right - left < 0.02 or bottom - top < 0.02:
        return None
    box = (left, top, right - left, bottom - top)
    for text in keep_clear:
        if _near(box, text, GAP):
            raise ValueError(f'A glow at {box} would reach the text at {text}.')
    if shape[0] == 'disc':
        local = ('disc', shape[1] - left, shape[2] - top) + shape[3:]
    else:
        local = ('frame', shape[1] - left, shape[2] - top, shape[3] - left, shape[4] - top, shape[5])
    return _picture(canvas, box, _glow_png(box[2], box[3], local, colour, peak, power, core))


def _disc_glow(canvas, centre, radius, reach, colour, peak, power=2.2, keep_clear=(), core=None):
    """Light round a disc: `peak` over the disc, fading to nothing `reach` inches beyond its rim."""
    cx, cy = centre
    outer = radius + reach
    return _glow(canvas, (cx - outer, cy - outer, cx + outer, cy + outer),
                 ('disc', cx, cy, round(radius, 4), round(reach, 4)), colour, peak, power, keep_clear, core)


# ---------------------------------------------------------------- the night


class _Night:
    """One night slide: the ground, its lights, then its stars.

    Every glow is placed clear of the slide's text boxes (`clear`) and raises
    if it would reach one, so no text ever sits on light.
    """

    def __init__(self, canvas, keep_clear):
        self.canvas, self.clear = canvas, tuple(keep_clear)
        self.scheme = _scheme(canvas)
        self.ground = self.scheme['ground']
        self.bright = []   # every light's centre and the reach of its glow, kept free of stars
        canvas.background(self.ground)
        # The accent element is the slide's base: on a bold deck it is the
        # ground; otherwise the night is laid over it edge to edge.
        canvas.accent((0, 0, SLIDE_W, SLIDE_H))
        if self.ground != canvas.roles['accent']:
            canvas.rect((0, 0, SLIDE_W, SLIDE_H), self.ground)

    def orbs(self, *orbs, peak=0.5, power=2.0, core=(0.85, 0.3)):
        """Discs of light, each (centre, radius, part, alpha, reach): `part` 'lead' or 'second',
        `alpha` how much of the light shows over the night, `reach` its glow beyond the rim (inches).

        The discs are opaque and pre-mixed with the night; where two cross, a
        lens shows their light added. Then each glow, a picture, lies over all
        of them: it lights its disc to a pale core and spills `reach` beyond
        the rim, across the other disc too, as light would.
        """
        drawn = []
        for centre, radius, part, alpha, reach in orbs:
            body = _over(self.scheme[part], self.ground, alpha)
            self.canvas.oval(_box(centre, radius), body)
            for other, other_radius, other_body in drawn:
                lens = _lens(other, other_radius, centre, radius)
                if lens:
                    self.canvas.polygon(lens, _screen(body, other_body))
            drawn.append((centre, radius, body))
        for centre, radius, part, alpha, reach in orbs:
            _disc_glow(self.canvas, centre, radius, reach, self.scheme[part], peak, power,
                       keep_clear=self.clear, core=core)
            self.bright.append((centre, radius + reach))

    def moon(self, centre, radius, reach=0.4, peak=0.55):
        """A small solid moon in its own glow."""
        _disc_glow(self.canvas, centre, radius, reach, self.scheme['moon_glow'], peak, power=2.4,
                   keep_clear=self.clear)
        self.canvas.oval(_box(centre, radius), self.scheme['moon'])
        self.bright.append((centre, radius + reach))

    def eclipse(self, centre, radius, offset=(0.08, 0.07), reach=1.0, peak=0.75):
        """A dark disc slid across a disc of light: a thin crescent, and the corona round it.

        `centre` is the dark disc's; the light behind it sits `offset` from
        it, towards the bottom right, so the crescent shows there.
        """
        scheme = self.scheme
        sun = (centre[0] + offset[0], centre[1] + offset[1])
        _disc_glow(self.canvas, sun, radius, reach, scheme['corona'], peak, power=2.2, keep_clear=self.clear)
        self.canvas.oval(_box(sun, radius), scheme['sun'])
        self.canvas.oval(_box(centre, radius), scheme['disc'])
        self.bright.append((sun, radius + reach))

    def window(self, box, reach=0.45, peak=0.3):
        """A picture's glow: light spilling softly from under its edges, as from a lit window."""
        left, top, width, height = box
        _glow(self.canvas, (left - reach, top - reach, left + width + reach, top + height + reach),
              ('frame', left, top, left + width, top + height, reach), self.scheme['moon_glow'], peak, 2.0,
              self.clear)

    def stars(self, region, count, seed, also_clear=()):
        """A sparse scatter of small stars in `region`, none near a text box or in any light."""
        left, top, width, height = region
        keep_clear = self.clear + tuple(also_clear)
        state, placed, tries = seed, 0, 0

        def draw():
            nonlocal state
            state = (state * 1103515245 + 12345) % 2147483648
            return (state >> 8) % 100000 / 100000

        while placed < count and tries < count * 60:
            tries += 1
            x, y = left + draw() * width, top + draw() * height
            size = 0.03 + draw() ** 2 * 0.05
            strength = 0.35 + draw() * 0.5
            star = (x - size / 2, y - size / 2, size, size)
            if x < 0.1 or y < 0.1 or x > SLIDE_W - 0.1 or y > SLIDE_H - 0.1:
                continue
            if any(_near(star, box, 0.12) for box in keep_clear):
                continue
            if any(math.hypot(x - cx, y - cy) < reach + 0.1 for (cx, cy), reach in self.bright):
                continue
            self.canvas.oval(star, _over(self.scheme['spark'], self.ground, strength))
            placed += 1

    def rule(self, x, y, width=0.9, height=0.07):
        """The short rule under a title, in the lead light."""
        self.canvas.rounded((x, y, width, height), self.scheme['lead'], radius=height / 2)


# Cover: the title on the left of the night, the light gathered top right.
TITLE = (0.85, 1.15, 6.35, 3.7)
RULE_Y = 5.1
SUBTITLE = (0.85, 5.38, 6.35, 1.0)

# Photo cover: the picture glows on the right, an orb rising behind its corner.
PHOTO = (7.65, 0.85, 4.83, 5.3)
PHOTO_TITLE = (0.85, 1.0, 5.9, 3.85)
PHOTO_SUBTITLE = (0.85, 5.38, 5.9, 1.0)

# Divider: the eclipse on the right, its dark disc holding the number; the title on the left.
ECLIPSE = ((9.55, 3.2), 1.95)
NUMERAL = (8.05, 2.1, 3.0, 2.2)
DIVIDER_TITLE = (0.85, 1.6, 5.6, 3.3)
DIVIDER_TITLE_KICKER = (0.85, 1.35, 5.6, 2.75)
KICKER = (0.85, 4.35, 5.6, 1.0)

# Closing: the message centred under light hanging from the top right.
CLOSING_TITLE = (2.4, 2.75, 8.533, 1.9)
CLOSING_RULE_Y = 4.85
CLOSING_SUBTITLE = (2.4, 5.1, 8.533, 0.8)

# Content slides: the accent as a quarter orb in the top-right corner, its glow
# kept right of the text (x 12.48) and of the eyebrow (from y 0.62).
CORNER = ((SLIDE_W, 0.0), 0.5)
CRESCENT = 0.05       # how far the light behind the corner disc is slid towards the slide
CORNER_REACH = 0.24


@composition
class Glow(Composition):
    name = 'glow'

    def ground(self, canvas, kind, photo=False):
        if kind == 'cover':
            return self._photo_cover(canvas) if photo else self._cover(canvas)
        if kind == 'closing':
            return self._closing(canvas)
        if kind == 'section':
            return self._divider(canvas)
        return self._content(canvas)

    # ------------------------------------------------------------------ cover

    def _cover(self, canvas):
        night = _Night(canvas, (TITLE, SUBTITLE) + CHROME)
        night.orbs(((11.6, 2.0), 2.75, 'lead', 0.8, 1.45), ((9.5, 4.55), 1.35, 'second', 0.65, 0.75))
        night.moon((8.5, 0.9), 0.34)
        night.stars((7.0, 0.15, 6.2, 6.5), 12, 7)
        night.stars((0.3, 0.12, 6.9, 0.9), 4, 19)
        night.rule(TITLE[0] + 0.02, RULE_Y)
        scheme = night.scheme
        return Plan(
            title=Text(TITLE, scheme['ink'], 48, anchor='bottom', lines=4),
            subtitle=Text(SUBTITLE, scheme['muted'], 17, anchor='top', lines=2),
            quiet=scheme['quiet'])

    def _photo_cover(self, canvas):
        night = _Night(canvas, (PHOTO_TITLE, PHOTO_SUBTITLE) + CHROME)
        left, top, width, height = PHOTO
        night.orbs(((left + width - 0.15, top + 0.35), 1.9, 'lead', 0.8, 1.2))
        night.window(PHOTO)
        night.moon((7.15, 0.43), 0.22, reach=0.18)
        night.stars((6.9, 0.1, 6.4, 7.0), 10, 11, ((left - 0.5, top - 0.5, width + 1.0, height + 1.0),))
        night.rule(PHOTO_TITLE[0] + 0.02, RULE_Y)
        scheme = night.scheme
        return Plan(
            title=Text(PHOTO_TITLE, scheme['ink'], 42, anchor='bottom', lines=4),
            subtitle=Text(PHOTO_SUBTITLE, scheme['muted'], 17, anchor='top', lines=2),
            quiet=scheme['quiet'], photo=PHOTO)

    # ---------------------------------------------------------------- divider

    def _divider(self, canvas):
        night = _Night(canvas, (DIVIDER_TITLE, DIVIDER_TITLE_KICKER, KICKER) + CHROME)
        night.orbs(((12.75, 0.65), 1.3, 'lead', 0.8, 0.8))
        centre, radius = ECLIPSE
        night.eclipse(centre, radius)
        night.stars((6.9, 0.1, 6.4, 6.6), 12, 3)
        scheme = night.scheme
        # The number sits on the dark disc alone, in the ink that reads on the night.
        return Plan(
            eyebrow=Text(NUMERAL, 'on_deep', 130, align='center', anchor='middle', numeral=True),
            title=Text(DIVIDER_TITLE, scheme['ink'], 44, anchor='middle', lines=3),
            title_with_kicker=Text(DIVIDER_TITLE_KICKER, scheme['ink'], 40, anchor='bottom', lines=3),
            kicker=Text(KICKER, scheme['muted'], 18, anchor='top', lines=2),
            quiet=scheme['quiet'])

    # ---------------------------------------------------------------- closing

    def _closing(self, canvas):
        night = _Night(canvas, (CLOSING_TITLE, CLOSING_SUBTITLE) + CHROME)
        night.orbs(((11.6, -0.8), 2.2, 'lead', 0.8, 1.15), ((-0.3, 3.9), 1.5, 'second', 0.65, 1.0))
        night.moon((9.3, 1.55), 0.32)
        night.stars((0.15, 0.1, 13.0, 6.6), 18, 5)
        night.rule((SLIDE_W - 0.9) / 2, CLOSING_RULE_Y)
        scheme = night.scheme
        return Plan(
            title=Text(CLOSING_TITLE, scheme['ink'], 54, align='center', anchor='bottom', lines=2),
            subtitle=Text(CLOSING_SUBTITLE, scheme['muted'], 18, align='center', anchor='top', lines=2),
            quiet=scheme['quiet'])

    # ---------------------------------------------------------------- content

    def _content(self, canvas):
        # The accent as a small eclipse bleeding off the top-right corner: a
        # quarter disc of the accent slid across the lead light, a thin crescent
        # of it showing and a glow round both. The same on every theme, all of
        # it right of the text (x 12.53) — outside the content box.
        canvas.background('surface')
        surface = canvas.roles['surface']
        light = _visible_on(_scheme(canvas)['lead'], surface)
        (cx, cy), radius = CORNER
        canvas.accent(_box((cx, cy), radius), 'oval')
        _disc_glow(canvas, (cx, cy), radius + CRESCENT, CORNER_REACH, light, 0.5, power=1.8)
        canvas.oval(_box((cx - CRESCENT, cy + CRESCENT), radius), light)
        canvas.oval(_box((cx, cy), radius), 'accent')
        return None
