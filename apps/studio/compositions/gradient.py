"""Gradient: vivid full-bleed gradients lit by soft glows, as Pitch or Gamma set them.

Cover and closing slides are a gradient edge to edge, from the accent to a
vivid middle hue, with soft discs of light in the top corners and a large
centred white title. The second colour arrives as light: the glow over the
gradient's far end is a tint of it, and a hairline orbit with its satellite
runs through that light. Dividers keep the gradient and set a big section
numeral and the title on the left, beside a flat vivid orb of the design's
three colours on the same orbit. Content slides stay clean: the surface, a slim
bar of the three colours along the top edge (a band on a bold deck) and a small
chip of them above the eyebrow.

The middle hue is half-way round the colour wheel from the accent to the second
colour, by the shorter way (by the longer one when the short way is green and
the long way is close): a navy and an amber meet in magenta. Every gradient
text sits on runs between two neighbouring hues, the accent and that middle,
never the accent and its opposite, whose blend turns grey; both ends are
darkened until white reads on them. A pale accent (a yellow, a mint) would
darken to olive, so then the second colour is the ground and the accent the
light. A light deck takes the jewel-deep version of the gradient, a dark deck
starts it from the night, and a bold deck takes the electric version: as
saturated and as bright as white text allows.

Everything of three colours (the bar, the band, the chip, the orb) and every
glow is a picture, so every viewer draws it alike. A picture is never under
text: each one's rectangle clears every text box on its slide, and each glow
fades to nothing inside its own radius, so it never shows a seam.
"""
import io
import math

from ..slides import _darken_for, _from_hls, _hls, _luminance, contrast_ratio
from . import CONTENT_TEXT, FOOTER, NUMBER, SLIDE_H, SLIDE_W, Composition, Plan, Text, _emu, composition

ANGLE = 35        # the gradient's direction, degrees counter-clockwise: rising to the top right
GLOW_PPI = 40     # glows are soft: a coarse picture scales up smoothly
SHAPE_PPI = 160   # crisp pictures: the orb and the chip
GAP = 0.12        # space kept between a picture and any text box
DEPTH = 6.0       # how far a light deck's gradient is darkened: white on it reads at this
PALE = 2.2        # an accent white reads on at less than this is too pale to be a dark ground

# Cover and closing: a centred stack — title (bottom-anchored), a pill, subtitle —
# set a little low, so light can come in over it from the top corners. The
# strips either side of the stack, 2.28 in wide, hold the light.
TITLE = (2.4, 1.88, 8.533, 2.62)
PILL_Y = 4.76
SUBTITLE = (2.4, 5.04, 8.533, 0.95)
# The closing slide's title is short and larger, so its stack sits higher.
CLOSING_TITLE = (2.4, 1.75, 8.533, 2.3)
CLOSING_PILL_Y = 4.3
CLOSING_SUBTITLE = (2.4, 4.58, 8.533, 0.95)

# Photo cover: the title on the left, the picture as a floating card on the right.
PHOTO = (7.55, 0.95, 4.95, 5.2)
PHOTO_TITLE = (0.85, 0.85, 5.95, 3.45)
PHOTO_PILL_Y = 4.58
PHOTO_SUBTITLE = (0.85, 4.88, 5.95, 1.3)

# Dividers: numeral, title and kicker on the left; an orb on the right.
NUMERAL = (0.85, 0.5, 5.0, 2.45)
NUMERAL_PILL_Y = 3.06
DIVIDER_TITLE = (0.85, 3.32, 6.7, 2.45)
DIVIDER_TITLE_KICKER = (0.85, 3.32, 6.7, 1.6)
KICKER = (0.85, 5.02, 6.7, 0.95)
ORB = (10.45, 3.3, 1.45)   # centre x, centre y, radius

# Content slides: the header row above the eyebrow, and where photos start below it.
HEADER = 0.42
BAR = 0.09
SOLID = SLIDE_W * 0.2      # the bar's solid accent start
CHIP = (CONTENT_TEXT[0], 0.25, 0.56, 0.1)   # the chip above the eyebrow

CHROME = (FOOTER, NUMBER)
_PNGS = {}


# ---------------------------------------------------------------- colour


def _channels(value):
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _tint(value, share):
    """`value` moved `share` of the way to white."""
    return '%02X%02X%02X' % tuple(round(c + (255 - c) * share) for c in _channels(value))


def _arc_mid(h1, h2, longer=False):
    turn = ((h2 - h1 + 0.5) % 1.0) - 0.5
    if longer:
        turn = turn - 1.0 if turn > 0 else turn + 1.0
    return (h1 + turn / 2) % 1.0


def _green(hue):
    return 70 / 360 <= hue <= 160 / 360


def _middle(one, other):
    """The vivid hue half-way between two colours, the shorter way round the wheel.

    Its saturation is the stronger of the two's, kept between 0.55 and 0.72, so a
    navy and an amber meet in magenta rather than in grey-brown. Where the short
    way runs through green and the long way, through violet and magenta, stays
    close enough to the first colour to blend cleanly from it, it goes the long way.
    """
    h1, l1, s1 = _hls(one)
    h2, l2, s2 = _hls(other)
    lightness = min(0.58, max(0.45, (l1 + l2) / 2))
    if max(s1, s2) < 0.12:              # two greys: the middle is a grey too
        return _from_hls(h1, lightness, max(s1, s2))
    if s1 < 0.12:                       # a grey has no hue of its own: take the other's
        h1 = h2
    elif s2 < 0.12:
        h2 = h1
    hue = _arc_mid(h1, h2)
    if _green(hue):
        other_way = _arc_mid(h1, h2, longer=True)
        if not _green(other_way) and abs(((other_way - h1 + 0.5) % 1.0) - 0.5) <= 120 / 360:
            hue = other_way
    saturation = min(0.55 if _green(hue) else 0.72, max(s1, s2, 0.55))
    return _from_hls(hue, lightness, saturation)


def _electric(value, target=4.6):
    """`value` as saturated, and as light, as white text on it allows."""
    hue, _, saturation = _hls(value)
    if saturation < 0.12:
        # A grey has no colour to brighten: lightened, it only turns to fog. It stays deep.
        return _darken_for('FFFFFF', value, 12.0)
    saturation = max(saturation, 0.85)
    lightness = 0.6
    while contrast_ratio('FFFFFF', _from_hls(hue, lightness, saturation)) < target and lightness > 0.05:
        lightness -= 0.01
    return _from_hls(hue, lightness, saturation)


def _scheme(canvas):
    """The colours of every slide, from the palette's roles.

    `ground` is the cover's gradient: the end the footer sits on, then the far,
    vivid end. `run` is the three full-chroma colours of the bar, chip and orb;
    `near` and `far` the lights over each end of the ground.

    The ground starts from the accent, unless the accent is pale (a yellow, a
    mint) and the second colour is not: darkened for white text a pale colour
    turns olive or grey, so then the second colour is the ground and the
    accent is the light.
    """
    roles = canvas.roles
    accent, secondary = roles['accent'], roles['secondary']
    lead, other = accent, secondary
    if contrast_ratio('FFFFFF', accent) < PALE < contrast_ratio('FFFFFF', secondary):
        lead, other = secondary, accent
    middle = _middle(lead, other)
    theme = roles.get('theme')
    if theme == 'bold':
        ground = (_electric(lead), _electric(middle))
    elif theme == 'dark':
        # A dark deck starts from the night and warms up towards the far corner.
        ground = (roles['deep'] if lead == accent else _deep(lead), _darken_for('FFFFFF', middle, 4.6))
    else:
        # A light deck's cover is the jewel-deep version of the two.
        ground = (_darken_for('FFFFFF', lead, DEPTH), _darken_for('FFFFFF', middle, DEPTH))
    return {
        'ground': ground,
        'run': (accent, middle, secondary),
        'near': _tint(middle, 0.3),
        'far': _tint(other, 0.3),
    }


def _deep(value):
    """A near-black of `value`'s hue, as the palette makes `deep` for a dark deck."""
    hue, _, saturation = _hls(value)
    return _from_hls(hue, 0.07, min(saturation, 0.6))


# ---------------------------------------------------------------- pictures


def _picture(canvas, box, data):
    element = canvas.slide.shapes.add_picture(io.BytesIO(data), *_emu(box))
    canvas.drawn.append(element)
    return element


def _png(pixels):
    from PIL import Image
    buffer = io.BytesIO()
    Image.fromarray(pixels, 'RGBA').save(buffer, 'PNG', optimize=True)
    return buffer.getvalue()


def _glow_png(width, height, blobs):
    """A translucent picture of soft discs: (cx, cy, rx, ry, hex, strength) in inches within it.

    Alpha falls smoothly from each disc's centre to nothing at its rim.
    """
    key = ('glow', round(width, 3), round(height, 3), blobs)
    if key in _PNGS:
        return _PNGS[key]
    import numpy
    w, h = max(2, round(width * GLOW_PPI)), max(2, round(height * GLOW_PPI))
    xs, ys = numpy.meshgrid((numpy.arange(w) + 0.5) / GLOW_PPI, (numpy.arange(h) + 0.5) / GLOW_PPI)
    clear = numpy.ones((h, w))
    colour = numpy.zeros((h, w, 3))
    weight = numpy.zeros((h, w))
    for cx, cy, rx, ry, value, strength in blobs:
        d2 = ((xs - cx) / rx) ** 2 + ((ys - cy) / ry) ** 2
        alpha = strength * numpy.clip(1 - d2, 0, 1) ** 1.6
        clear *= 1 - alpha
        colour += alpha[..., None] * numpy.array(_channels(value), float)
        weight += alpha
    alpha = 1 - clear
    colour = colour / numpy.maximum(weight, 1e-6)[..., None]
    pixels = numpy.dstack([colour.round().clip(0, 255), (alpha * 255).round().clip(0, 255)]).astype(numpy.uint8)
    _PNGS[key] = _png(pixels)
    return _PNGS[key]


def _overlaps(one, other, gap=0.0):
    return (one[0] < other[0] + other[2] + gap and other[0] < one[0] + one[2] + gap
            and one[1] < other[1] + other[3] + gap and other[1] < one[1] + one[3] + gap)


def _glow(canvas, blobs, keep_clear):
    """Soft light: discs in slide inches as (cx, cy, rx, ry, hex, strength).

    The picture is the discs' own bounds, cut to the slide, and each disc has
    faded to nothing at its rim, so no edge shows. Raises if the picture would
    sit under any of the `keep_clear` text boxes.
    """
    left = max(0.0, min(cx - rx for cx, _, rx, _, _, _ in blobs))
    top = max(0.0, min(cy - ry for _, cy, _, ry, _, _ in blobs))
    right = min(SLIDE_W, max(cx + rx for cx, _, rx, _, _, _ in blobs))
    bottom = min(SLIDE_H, max(cy + ry for _, cy, _, ry, _, _ in blobs))
    box = (left, top, right - left, bottom - top)
    for text in keep_clear:
        if _overlaps(box, text, GAP - 0.01):
            raise ValueError(f'A glow at {box} would sit under the text at {text}.')
    local = tuple((cx - left, cy - top, rx, ry, value, strength) for cx, cy, rx, ry, value, strength in blobs)
    return _picture(canvas, box, _glow_png(box[2], box[3], local))


def _run_png(width, height, stops, angle, shape, positions=None):
    """A crisp picture of a `shape` ('rect', 'disc' or 'pill') filling width x height inches,
    painted with a linear gradient through `stops` (hex, evenly spaced) rising at `angle`."""
    key = ('run', round(width, 3), round(height, 3), stops, angle, shape, positions)
    if key in _PNGS:
        return _PNGS[key]
    import numpy
    w, h = max(2, round(width * SHAPE_PPI)), max(2, round(height * SHAPE_PPI))
    xs, ys = numpy.meshgrid((numpy.arange(w) + 0.5) / SHAPE_PPI - width / 2,
                            (numpy.arange(h) + 0.5) / SHAPE_PPI - height / 2)
    radians = math.radians(angle)
    reach = width * abs(math.cos(radians)) + height * abs(math.sin(radians))
    t = numpy.clip((xs * math.cos(radians) - ys * math.sin(radians)) / reach + 0.5, 0, 1)
    positions = numpy.linspace(0, 1, len(stops)) if positions is None else positions
    rgb = [numpy.interp(t, positions, [_channels(stop)[i] for stop in stops]) for i in range(3)]
    if shape == 'rect':
        inside = numpy.full(xs.shape, 1.0)
    elif shape == 'disc':
        inside = min(width, height) / 2 - numpy.hypot(xs, ys)
    else:  # a pill: a rounded bar with half-circle ends
        radius = min(width, height) / 2
        run = max(0.0, abs(width - height) / 2)
        along, across = (numpy.abs(xs), numpy.abs(ys)) if width >= height else (numpy.abs(ys), numpy.abs(xs))
        inside = radius - numpy.hypot(numpy.maximum(along - run, 0), across)
    alpha = numpy.clip(inside * SHAPE_PPI + 0.5, 0, 1)   # a pixel of anti-aliasing at the rim
    pixels = numpy.dstack(rgb + [alpha * 255]).round().clip(0, 255).astype(numpy.uint8)
    _PNGS[key] = _png(pixels)
    return _PNGS[key]


# ---------------------------------------------------------------- shared parts


def _backdrop(canvas, scheme, angle):
    """The full-bleed gradient. The accent element lies beneath it, the slide's base."""
    canvas.background(scheme['ground'][0])
    canvas.accent((0, 0, SLIDE_W, SLIDE_H))
    canvas.rect((0, 0, SLIDE_W, SLIDE_H), None, gradient=scheme['ground'], angle=angle)


def _pill(canvas, x, y, width=0.9, height=0.08, fill='on_gradient'):
    canvas.rounded((x, y, width, height), fill, radius=height / 2)


def _dot(canvas, cx, cy, size, fill='on_gradient'):
    canvas.oval((cx - size / 2, cy - size / 2, size, size), fill)


def _orbit(canvas, cx, cy, radius, degrees, dot, fill='on_gradient'):
    """A hairline orbit and its satellite, `degrees` counter-clockwise from the right."""
    canvas.oval((cx - radius, cy - radius, 2 * radius, 2 * radius), None, line='on_gradient', line_width=0.75)
    angle = math.radians(degrees)
    _dot(canvas, cx + radius * math.cos(angle), cy - radius * math.sin(angle), dot, fill)


def _run(canvas, box, run):
    """The three colours across `box`, left to right, as a picture: it has no seams.

    The first fifth is the accent alone, then it turns through the middle hue to the
    second colour.
    """
    stops = (run[0],) * 2 + run[1:]
    return _picture(canvas, box, _run_png(box[2], box[3], stops, 0, 'rect', (0, 0.2, 0.6, 1)))


@composition
class Gradient(Composition):
    name = 'gradient'
    # Content photos start below the header row, which stays on every content slide.
    content_box = (0.0, HEADER, SLIDE_W, SLIDE_H - HEADER)

    def ground(self, canvas, kind, photo=False):
        scheme = _scheme(canvas)
        if kind == 'cover':
            return self._photo_cover(canvas, scheme) if photo else self._cover(canvas, scheme, mirrored=False)
        if kind == 'closing':
            return self._cover(canvas, scheme, mirrored=True)
        if kind == 'section':
            return self._divider(canvas, scheme)
        return self._content(canvas, scheme)

    def _cover(self, canvas, scheme, mirrored):
        # The closing slide mirrors the cover: its gradient and its light come from the other side.
        _backdrop(canvas, scheme, 180 - ANGLE if mirrored else ANGLE)
        title, pill, subtitle = ((CLOSING_TITLE, CLOSING_PILL_Y, CLOSING_SUBTITLE) if mirrored
                                 else (TITLE, PILL_Y, SUBTITLE))
        clear = (title, subtitle) + CHROME
        flip = (lambda x: SLIDE_W - x) if mirrored else (lambda x: x)
        strength = 0.7 if canvas.roles.get('theme') == 'bold' else 0.6
        # Light pours in from above the far corner: a large disc of the second colour
        # hanging over the top edge and a brighter one in the corner, both clear above
        # and beside the title; a smaller disc of the middle hue lights the near corner.
        _glow(canvas, ((flip(12.3), -0.95, 2.55, 2.55, scheme['far'], strength * 0.8),), clear)
        _glow(canvas, ((flip(13.25), -0.1, 1.95, 1.95, scheme['far'], strength),), clear)
        _glow(canvas, ((flip(-0.1), 0.3, 1.5, 1.5, scheme['near'], strength - 0.05),), clear)
        # A thin orbit through the far light, and its satellite: the dividers' motif.
        _orbit(canvas, flip(12.85), 0.25, 1.5, 180 + 62 if not mirrored else -62, 0.18)
        _pill(canvas, SLIDE_W / 2 - 0.45, pill)
        size = 60 if mirrored else 48
        return Plan(
            title=Text(title, 'on_gradient', size, align='center', anchor='bottom', lines=2 if mirrored else 3),
            subtitle=Text(subtitle, 'on_gradient', 20, align='center', anchor='top'),
            quiet='on_gradient')

    def _photo_cover(self, canvas, scheme):
        _backdrop(canvas, scheme, ANGLE)
        clear = (PHOTO_TITLE, PHOTO_SUBTITLE) + CHROME
        left, top, width, height = PHOTO
        strength = 0.7 if canvas.roles.get('theme') == 'bold' else 0.6
        # Light behind the picture, so it floats in a glow: the far light over its top
        # right, and a paler one in the middle hue rising from behind its lower right.
        _glow(canvas, ((left + width - 0.2, top + 0.4, 2.6, 2.6, scheme['far'], strength),), clear)
        _glow(canvas, ((SLIDE_W - 0.2, top + height - 1.15, 1.6, 1.6, _tint(scheme['near'], 0.25), 0.5),), clear)
        # A hairline frame a step outside the picture, square like it.
        canvas.rect((left - 0.16, top - 0.16, width + 0.32, height + 0.32), None,
                    line='on_gradient', line_width=0.75)
        _pill(canvas, PHOTO_TITLE[0] + 0.04, PHOTO_PILL_Y)
        return Plan(
            title=Text(PHOTO_TITLE, 'on_gradient', 44, anchor='bottom', lines=4),
            subtitle=Text(PHOTO_SUBTITLE, 'on_gradient', 18, anchor='top'),
            quiet='on_gradient',
            photo=PHOTO)

    def _divider(self, canvas, scheme):
        _backdrop(canvas, scheme, ANGLE)
        clear = (NUMERAL, DIVIDER_TITLE, KICKER) + CHROME
        cx, cy, radius = ORB
        # A halo of the middle hue round the orb, brightest towards the light at the top right.
        halo = radius * 1.75
        _glow(canvas, ((cx + 0.3, cy - 0.3, halo, halo, scheme['near'], 0.5),), clear)
        # The orb: a flat disc of the design's three colours, lit from the top right, on a
        # hairline orbit with a satellite.
        diameter = 2 * radius
        run = scheme['run']
        if _luminance(run[0]) > _luminance(run[2]):
            run = run[::-1]                 # the paler colour takes the light
        _picture(canvas, (cx - radius, cy - radius, diameter, diameter),
                 _run_png(diameter, diameter, run, ANGLE + 20, 'disc'))
        _orbit(canvas, cx, cy, radius * 1.5, 38, 0.26)
        _pill(canvas, NUMERAL[0] + 0.08, NUMERAL_PILL_Y, width=0.6)
        return Plan(
            eyebrow=Text(NUMERAL, 'on_gradient', 132, anchor='bottom', numeral=True),
            title=Text(DIVIDER_TITLE, 'on_gradient', 42, anchor='top', lines=3),
            title_with_kicker=Text(DIVIDER_TITLE_KICKER, 'on_gradient', 40, anchor='top', lines=2),
            kicker=Text(KICKER, 'on_gradient', 18, anchor='top'),
            quiet='on_gradient')

    def _content(self, canvas, scheme):
        canvas.background('surface')
        run = scheme['run']
        # A bar of the three colours along the top edge — a band on a bold deck — starting in
        # the accent, over the accent element; below it, above the eyebrow, a chip of them.
        height = HEADER if canvas.roles.get('theme') == 'bold' else BAR
        canvas.accent((0, 0, SOLID, height - 0.03))
        _run(canvas, (0, 0, SLIDE_W, height), run)
        if height < HEADER:
            _picture(canvas, CHIP, _run_png(CHIP[2], CHIP[3], run, 0, 'pill'))
        return None
