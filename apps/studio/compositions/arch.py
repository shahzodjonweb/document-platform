"""Arch: soft organic modern — tall arches, balls and a pebble of ovals on a calm ground.

Arches, balls and pills stand on a fine shelf line, like objects on a shelf,
and a soft pebble peeks out from behind the main arch's shoulder. The cover
sets the title on the left, over a short pill, and a tall arch on the right
ringed by a fine line the same distance all round, with a shorter arch in the
second colour in front of it; with a photo, the arch becomes a frame with the
picture standing inside it and a sun in the second colour rising over its top
edge. Each divider is a tall arch window, ringed, standing on a sill with a
small arch and a ball beside it, the section number inside and the title
centred below. The closing slide is three nested arches — the second colour,
the ground, the accent — with the thanks in the innermost. Content slides keep
a small ringed arch window on a short shelf in the top-right corner, matching
the dividers, and a pebble rolling off the bottom-right corner, both outside
the text.

A bold deck turns it over: the accent fills the ground, the arches are cut
from the paper colour and the pebble is a deeper tone of the accent. A dark
deck keeps the lines and balls in the muted ink, which reads on the night
ground whatever the accent, and rings every accent arch so a dark accent
still has an edge.
"""
import math

from . import SLIDE_H, SLIDE_W, Composition, Plan, Text, composition

FLOOR = 6.45  # arches, pills and balls stand here; the footer row below stays on the ground
SHELF = 0.035  # the shelf line's thickness

# A pebble of overlapping ovals, as (left, top, width, height) around its
# centre, for a blob of unit size: a broad body, a lobe to its right and a
# softer one at its foot. It spans about -1.0 to 1.05 across, -0.7 to 0.75 down.
PEBBLE = (
    (-1.00, -0.70, 1.80, 1.40),
    (-0.40, -0.55, 1.45, 1.30),
    (-0.85, -0.10, 1.20, 0.85),
)


def _arch_points(box, steps=48):
    """The outline of an arch, from its bottom-left corner over the dome to its bottom-right."""
    left, top, span, height = box
    radius = span / 2
    centre = (left + radius, top + radius)
    points = [(left, top + height), (left, top + radius)]
    for step in range(1, steps):
        angle = math.pi - math.pi * step / steps
        points.append((centre[0] + radius * math.cos(angle), centre[1] - radius * math.sin(angle)))
    return points + [(left + span, top + radius), (left + span, top + height)]


def _arch(canvas, box, fill, first=False):
    """A rectangle topped with a half-circle, in one colour.

    Drawn as a dome (an oval) and a body under it, which PowerPoint renders with
    true curves; an arch shorter than it is wide, whose oval would hang below
    its foot, is drawn as one polygon instead.
    """
    left, top, width, height = box
    if height < width:
        if first:
            raise ValueError('The accent arch must be at least as tall as it is wide.')
        return canvas.polygon(_arch_points(box), fill)
    dome = (left, top, width, width)
    if first:
        canvas.accent(dome, 'oval')
    else:
        canvas.oval(dome, fill)
    canvas.rect((left, top + width / 2, width, height - width / 2), fill)


def _around(box, gap):
    """The box of a ring `gap` outside an arch on the same floor: wider, taller, same foot."""
    left, top, width, height = box
    return (left - gap, top - gap, width + 2 * gap, height + gap)


def _within(box, gap):
    """The box of an arch nested `gap` inside another on the same floor."""
    left, top, width, height = box
    return (left + gap, top + gap, width - 2 * gap, height - gap)


def _outline(canvas, box, colour, width=1.75):
    """The fine outline of an arch: one line around its dome, down its sides and along its foot."""
    return canvas.polygon(_arch_points(box), None, line=colour, line_width=width)


def _pill(canvas, box, fill):
    return canvas.rounded(box, fill, radius=min(box[2], box[3]) / 2)


def _ball(canvas, left, size, fill, floor=FLOOR):
    """A ball resting on the floor."""
    return canvas.oval((left, floor - size, size, size), fill)


def _pebble_outline(steps=180):
    """The outline of the pebble's ovals together, for a pebble of unit size around (0, 0).

    Every oval holds the centre, so each ray from it leaves the pebble once:
    where it leaves the last oval it crosses.
    """
    ovals = [(left + width / 2, top + height / 2, width / 2, height / 2) for left, top, width, height in PEBBLE]
    points = []
    for step in range(steps):
        angle = 2 * math.pi * step / steps
        dx, dy = math.cos(angle), math.sin(angle)
        reach = 0.0
        for cx, cy, rx, ry in ovals:
            # |(t·d - c) / r| = 1, solved for its positive root.
            a = (dx / rx) ** 2 + (dy / ry) ** 2
            b = -2 * (dx * cx / rx ** 2 + dy * cy / ry ** 2)
            c = (cx / rx) ** 2 + (cy / ry) ** 2 - 1
            reach = max(reach, (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a))
        points.append((reach * dx, reach * dy))
    return points


PEBBLE_OUTLINE = _pebble_outline()


def _pebble(canvas, centre, size, scheme):
    """The pebble, never under text: a soft tint on paper, a deeper tone of the accent on a bold ground.

    One shape, so a see-through pebble is one even tone rather than darker where its ovals overlap.
    """
    x, y = centre
    fill, alpha = scheme['pebble']
    canvas.polygon([(x + px * size, y + py * size) for px, py in PEBBLE_OUTLINE], fill, alpha=alpha)


def _shelf(canvas, left, right, colour, floor=FLOOR):
    """The fine shelf line the arches stand on."""
    return canvas.rect((left, floor, right - left, SHELF), colour)


def _scheme(canvas):
    """The fills and inks for this theme: arches on paper, or (bold) paper arches on the accent.

    On a dark ground a dark accent all but vanishes, so a dark deck draws its
    lines and balls in the muted ink and its pill in the second colour, and
    leaves the accent to the big arches, which a muted ring outlines.
    """
    theme = canvas.roles.get('theme')
    if theme == 'bold':
        return {'ground': 'accent', 'arch': 'surface', 'second': 'secondary', 'pebble': ('deep', 0.28),
                'ball': 'surface', 'line': 'surface', 'ink': 'on_accent', 'muted': 'on_accent',
                'quiet': 'on_accent', 'arch_ink': 'accent_text', 'mark': 'secondary'}
    if theme == 'dark':
        return {'ground': 'surface', 'arch': 'accent', 'second': 'secondary', 'pebble': ('accent_soft', None),
                'ball': 'muted', 'line': 'muted', 'ink': 'heading', 'muted': 'muted', 'quiet': 'muted',
                'arch_ink': 'on_accent', 'mark': 'secondary'}
    return {'ground': 'surface', 'arch': 'accent', 'second': 'secondary', 'pebble': ('accent_soft', None),
            'ball': 'accent', 'line': 'accent_text', 'ink': 'heading', 'muted': 'muted', 'quiet': 'muted',
            'arch_ink': 'on_accent', 'mark': 'accent'}


def _open(canvas, scheme, lead):
    """The ground, and the accent element under it all.

    On a bold deck that is the whole slide. On paper it is the body of the
    slide's main accent arch (`lead`), drawn first and covered again by that
    arch, so the pebble and the second colour can still stand behind the arch.
    """
    canvas.background(scheme['ground'])
    if scheme['ground'] == 'accent':
        canvas.accent((0, 0, SLIDE_W, SLIDE_H))
        return
    left, top, width, height = lead
    canvas.accent((left, top + width / 2, width, height - width / 2))


@composition
class Arch(Composition):
    name = 'arch'

    def ground(self, canvas, kind, photo=False):
        if kind == 'cover':
            return self._cover(canvas, photo)
        if kind == 'closing':
            return self._closing(canvas)
        if kind == 'section':
            return self._divider(canvas)
        return self._content(canvas)

    def _content(self, canvas):
        """A small ringed arch window on a short shelf top right, and a pebble off the bottom-right corner."""
        canvas.background('surface')
        dark = canvas.roles.get('theme') == 'dark'
        window, foot = (12.725, 0.70, 0.36, 0.77), 0.70 + 0.77
        _arch(canvas, window, 'accent', first=True)
        # The ring's top lines up with the eyebrow's top line.
        _outline(canvas, _around(window, 0.07), 'muted' if dark else 'accent_text', width=1.0)
        _shelf(canvas, 12.60, 13.21, 'secondary', floor=foot)
        _pebble(canvas, (13.45, 7.55), 0.85, {'pebble': ('accent_soft', None)})
        return None

    def _cover(self, canvas, photo):
        scheme = _scheme(canvas)
        if photo:
            # The arch becomes a frame with an even border, the picture standing
            # in it, and a sun in the second colour rising over its top edge:
            # the picture, placed after, covers the sun's lower half.
            frame = (8.40, 0.55, 3.80, FLOOR - 0.55)
            border, top = 0.24, 1.85
            _open(canvas, scheme, frame)
            _pill(canvas, (0.85, 4.98, 0.85, 0.14), scheme['mark'])
            _shelf(canvas, 7.90, SLIDE_W, scheme['line'])
            _pebble(canvas, (8.95, 1.45), 1.25, scheme)
            _outline(canvas, _around(frame, 0.20), scheme['line'])
            _arch(canvas, frame, scheme['arch'])
            canvas.oval((frame[0] + frame[2] / 2 - 0.60, top - 0.60, 1.20, 1.20), scheme['second'])
            _ball(canvas, 12.58, 0.48, scheme['second'])
            picture = (frame[0] + border, top, frame[2] - 2 * border, FLOOR - border - top)
        else:
            main = (8.90, 0.90, 3.20, FLOOR - 0.90)
            _open(canvas, scheme, main)
            _pill(canvas, (0.85, 4.98, 0.85, 0.14), scheme['mark'])
            _shelf(canvas, 7.65, SLIDE_W, scheme['line'])
            _pebble(canvas, (9.10, 1.75), 1.45, scheme)
            _outline(canvas, _around(main, 0.22), scheme['line'])
            _arch(canvas, main, scheme['arch'])
            _arch(canvas, (7.85, 3.55, 1.80, FLOOR - 3.55), scheme['second'])
            _ball(canvas, 12.50, 0.50, scheme['second'])
            picture = None
        return Plan(
            title=Text((0.85, 1.25, 6.75, 3.50), scheme['ink'], 44, anchor='bottom', lines=4),
            subtitle=Text((0.85, 5.30, 6.40, 1.10), scheme['muted'], 17, anchor='top'),
            quiet=scheme['quiet'],
            photo=picture)

    def _closing(self, canvas):
        scheme = _scheme(canvas)
        # Three nested arches on the shelf — the second colour, the ground, the
        # arch colour — ringed by a fine line, with the thanks in the innermost.
        outer = (SLIDE_W / 2 - 3.10, 0.45, 6.20, FLOOR - 0.45)
        inner = _within(outer, 1.00)
        _open(canvas, scheme, inner)
        _shelf(canvas, 2.70, 11.20, scheme['line'])
        _pebble(canvas, (3.75, 1.40), 1.30, scheme)
        _outline(canvas, _around(outer, 0.18), scheme['line'])
        _arch(canvas, outer, scheme['second'])
        _arch(canvas, _within(outer, 0.50), scheme['ground'])
        _arch(canvas, inner, scheme['arch'])
        _ball(canvas, 10.15, 0.60, scheme['ball'])
        return Plan(
            title=Text((4.97, 2.70, 3.40, 1.95), scheme['arch_ink'], 40, align='center', anchor='bottom',
                       lines=3),
            subtitle=Text((4.97, 4.80, 3.40, 1.10), scheme['arch_ink'], 17, align='center', anchor='top'),
            quiet=scheme['quiet'])

    def _divider(self, canvas):
        scheme = _scheme(canvas)
        # The window: a tall arch ringed by a fine line, standing on a sill with
        # a small arch and a ball beside it, and the pebble behind its shoulder.
        inner, top, sill = 2.80, 0.60, 3.90
        left = (SLIDE_W - inner) / 2
        window = (left, top, inner, sill - top)
        _open(canvas, scheme, window)
        _shelf(canvas, 4.10, 10.20, scheme['line'], floor=sill)
        _pebble(canvas, (4.95, 1.10), 1.15, scheme)
        _outline(canvas, _around(window, 0.26), scheme['line'])
        _arch(canvas, window, scheme['arch'])
        _arch(canvas, (8.63, sill - 1.30, 0.62, 1.30), scheme['second'])
        _ball(canvas, 9.40, 0.42, scheme['ball'], floor=sill)
        return Plan(
            eyebrow=Text((left + 0.15, top + 1.45, inner - 0.30, 1.50), scheme['arch_ink'], 60, align='center',
                         anchor='middle', numeral=True),
            title=Text((2.15, sill + 0.35, 9.03, 1.85), scheme['ink'], 40, align='center', anchor='top', lines=3),
            title_with_kicker=Text((2.15, sill + 0.35, 9.03, 1.25), scheme['ink'], 38, align='center',
                                   anchor='top', lines=2),
            kicker=Text((2.15, sill + 1.85, 9.03, 0.60), scheme['muted'], 17, align='center', anchor='top'),
            quiet=scheme['quiet'])
