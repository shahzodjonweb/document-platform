"""Circles: Bauhaus and Swiss geometry — discs, a half-disc, a cut-out lens.

The cover is a poster: one big accent disc bleeding off the top right inside a
hairline orbit, a smaller disc in the second colour overlapping it with their
shared lens cut out to the ground, so the overlap reads as two crescents, a
half-disc in a third, softer value rising from the bottom edge, and the title
set large on the open ground beside them, over a row of three dots in the same
colours. With a photo, the picture is a wide window bleeding off the right
edge and the big disc rises from its top edge like a sun from the horizon, its
lower half behind the picture.

Dividers set the section number inside a big disc that bleeds a clear inch off
the left edge, centred on the part of the disc that shows, with the title large
beside it and the cover's half-disc rising from the bottom edge. The closing
slide centres its message inside one disc, with the small disc at its upper
left and the half-disc at its lower right: the cover's diagonal again. Content
slides keep the motif in miniature — a solid quarter-disc in the top-right
corner with a small disc overlapping it and the lens cut out — and the cover's
three dots stacked in the left margin beside the brand name, all outside the
text box.

On a bold deck the ground of the cover, dividers and closing is the accent
itself: the big disc takes the second colour, the small disc the ink that
reads on the accent, the half-disc the soft tint, and the lens is cut out of
both discs. The bottom-right corner of the cover stays clear for a logo.
"""
import math

from . import SLIDE_H, SLIDE_W, Composition, Plan, Text, composition

STEPS = 120       # segments in a full turn of a drawn arc
OVERSHOOT = 0.02  # how far a cut-out lens runs past each disc, so no fringe shows
# The soft half-disc rising from the bottom edge on the cover, the dividers and
# the closing slide, in the same place on each: between the brand name (to
# x 8.99) and the slide number (from x 11.48), clear of a logo in the corner.
HALF = ((10.3, SLIDE_H), 0.9)


def _arc(centre, radius, start, end, steps=None):
    """Points along a circle from angle `start` to `end` (radians, y down)."""
    steps = steps or max(12, int(abs(end - start) / (2 * math.pi) * STEPS))
    x, y = centre
    return [(x + radius * math.cos(start + (end - start) * i / steps),
             y + radius * math.sin(start + (end - start) * i / steps)) for i in range(steps + 1)]


def _lens(one, r1, two, r2):
    """The shape two overlapping discs share, as a polygon."""
    (x1, y1), (x2, y2) = one, two
    d = math.hypot(x2 - x1, y2 - y1)
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    base1 = math.atan2(y2 - y1, x2 - x1)
    half1 = math.acos(max(-1.0, min(1.0, a / r1)))
    base2 = base1 + math.pi
    half2 = math.acos(max(-1.0, min(1.0, (d - a) / r2)))
    # A hair outside each circle, so no sliver of either disc shows along its edge.
    return (_arc(one, r1 + OVERSHOOT, base1 - half1, base1 + half1, 90)
            + _arc(two, r2 + OVERSHOOT, base2 - half2, base2 + half2, 90)[1:-1])


def _box(centre, radius):
    return (centre[0] - radius, centre[1] - radius, 2 * radius, 2 * radius)


def _half(canvas, centre, radius, facing, fill):
    """A half-disc whose round side faces `facing` ('up', 'down', 'left', 'right')."""
    start = {'down': 0, 'left': math.pi / 2, 'up': math.pi, 'right': -math.pi / 2}[facing]
    canvas.polygon(_arc(centre, radius, start, start + math.pi), fill)


def _scheme(canvas, filled=True):
    """Which role each part takes: the ground, the discs and the text on each.

    `filled` is False for content slides, which stay on the surface in every
    theme, bold included.
    """
    theme = canvas.roles.get('theme')
    if theme == 'bold' and filled:
        return {'ground': 'accent', 'hero': 'secondary', 'hero_ink': 'on_secondary',
                'second': 'on_accent', 'half': 'accent_soft', 'ring': 'on_accent',
                'ink': 'on_accent', 'muted': 'on_accent', 'quiet': 'on_accent'}
    dark = theme == 'dark'
    # The half-disc is a third, quieter value: never a fourth navy, and in the
    # dark theme never brighter than the title.
    return {'ground': 'surface', 'hero': 'accent', 'hero_ink': 'on_accent', 'second': 'secondary',
            'half': 'muted' if dark else 'accent_soft',
            'ring': 'muted', 'ink': 'heading', 'muted': 'muted', 'quiet': 'muted'}


@composition
class Circles(Composition):
    name = 'circles'

    def ground(self, canvas, kind, photo=False):
        if kind == 'cover':
            return self._photo_cover(canvas) if photo else self._cover(canvas)
        if kind == 'closing':
            return self._closing(canvas)
        if kind == 'section':
            return self._divider(canvas)
        return self._content(canvas)

    def _hero(self, canvas, scheme, centre, radius):
        """The slide's ground and its big disc; one of them is the accent element."""
        canvas.background(scheme['ground'])
        if scheme['ground'] == 'accent':
            canvas.accent((0, 0, SLIDE_W, SLIDE_H))
            canvas.oval(_box(centre, radius), scheme['hero'])
        else:
            canvas.accent(_box(centre, radius), 'oval')

    def _pair(self, canvas, scheme, big, big_r, small, small_r):
        """The small disc over the big one, their shared lens cut out to the ground."""
        canvas.oval(_box(small, small_r), scheme['second'])
        canvas.polygon(_lens(big, big_r, small, small_r), scheme['ground'])

    # ------------------------------------------------------------------ cover

    def _cover(self, canvas):
        scheme = _scheme(canvas)
        big, big_r = (10.95, 2.45), 3.5
        small, small_r = (8.3, 5.0), 1.3
        self._hero(canvas, scheme, big, big_r)
        self._orbit(canvas, scheme, big, big_r + 0.25)
        self._pair(canvas, scheme, big, big_r, small, small_r)
        _half(canvas, *HALF, 'up', scheme['half'])
        self._dots(canvas, (0.85, 4.95), scheme)
        return Plan(
            title=Text((0.85, 0.8, 6.05, 3.8), scheme['ink'], 52, anchor='bottom', lines=4, bold=True),
            subtitle=Text((0.85, 5.4, 5.6, 0.95), scheme['muted'], 17, anchor='top', lines=2),
            quiet=scheme['quiet'])

    def _photo_cover(self, canvas):
        scheme = _scheme(canvas)
        # The picture: a wide window bleeding off the right edge, above the
        # footer row. The big disc is centred on its top edge, so exactly its
        # upper half shows — a sun on the picture's horizon.
        frame = (6.95, 2.85, SLIDE_W - 6.95, 3.7)
        sun, sun_r = (10.55, frame[1]), 2.15
        small, small_r = (8.45, 1.2), 0.82
        self._hero(canvas, scheme, sun, sun_r)
        self._orbit(canvas, scheme, sun, sun_r + 0.25)
        self._pair(canvas, scheme, sun, sun_r, small, small_r)
        self._dots(canvas, (0.85, 4.95), scheme)
        return Plan(
            title=Text((0.85, 0.8, 5.6, 3.8), scheme['ink'], 48, anchor='bottom', lines=4, bold=True),
            subtitle=Text((0.85, 5.4, 5.6, 0.95), scheme['muted'], 17, anchor='top', lines=2),
            quiet=scheme['quiet'], photo=frame)

    # ---------------------------------------------------------------- closing

    def _closing(self, canvas):
        scheme = _scheme(canvas)
        centre, radius = (SLIDE_W / 2, 3.35), 2.85
        # The cover's diagonal: the small disc high on the left, the half-disc
        # low on the right.
        small, small_r = (3.9, 0.9), 1.1
        self._hero(canvas, scheme, centre, radius)
        self._orbit(canvas, scheme, centre, radius + 0.28)
        self._pair(canvas, scheme, centre, radius, small, small_r)
        _half(canvas, *HALF, 'up', scheme['half'])
        ink = scheme['hero_ink']
        return Plan(
            title=Text((centre[0] - 2.1, 2.05, 4.2, 1.7), ink, 44, align='center', anchor='bottom', lines=2,
                       bold=True),
            subtitle=Text((centre[0] - 1.85, 3.95, 3.7, 0.8), ink, 16, align='center', anchor='top', lines=2),
            quiet=scheme['quiet'])

    # ---------------------------------------------------------------- divider

    def _divider(self, canvas):
        scheme = _scheme(canvas)
        # A clear inch off the left edge; the orbit stays above the footer row.
        centre, radius = (1.9, 3.55), 2.9
        small, small_r = (3.9, 1.2), 0.85
        self._hero(canvas, scheme, centre, radius)
        self._orbit(canvas, scheme, centre, radius + 0.28)
        self._pair(canvas, scheme, centre, radius, small, small_r)
        _half(canvas, *HALF, 'up', scheme['half'])
        left = 5.9
        width = 12.48 - left
        # Centred on the part of the disc that shows, not on its centre.
        visible = (centre[0] + radius) / 2
        numeral = (visible - 1.8, centre[1] - 1.05, 3.6, 2.1)
        return Plan(
            eyebrow=Text(numeral, scheme['hero_ink'], 120, align='center', anchor='middle', numeral=True,
                         bold=True),
            title=Text((left, centre[1] - 1.5, width, 3.0), scheme['ink'], 50, anchor='middle', lines=3,
                       bold=True),
            title_with_kicker=Text((left, 1.2, width, 2.8), scheme['ink'], 44, anchor='bottom', lines=3,
                                   bold=True),
            kicker=Text((left, 4.25, width, 1.0), scheme['muted'], 18, anchor='top', lines=2),
            quiet=scheme['quiet'])

    # ---------------------------------------------------------------- content

    def _content(self, canvas):
        scheme = _scheme(canvas, filled=False)
        canvas.background('surface')
        # The cover in miniature, in the top-right corner: a solid quarter-disc
        # and a small disc on the top edge overlapping it, the lens cut out.
        corner, corner_r = (SLIDE_W, 0.0), 1.0
        canvas.accent(_box(corner, corner_r), 'oval')
        self._pair(canvas, scheme, corner, corner_r, (12.25, 0.0), 0.34)
        # The cover's three dots, stacked in the left margin, the last one on
        # the footer's midline.
        size, gap = 0.12, 0.08
        top = 6.98 - size / 2 - 2 * (size + gap)
        self._dots(canvas, (0.42 - size / 2, top), scheme, size, gap, vertical=True)
        return None

    # ------------------------------------------------------------------ marks

    def _orbit(self, canvas, scheme, centre, radius):
        """A hairline ring around a disc, drawn under the shapes that overlap it."""
        canvas.oval(_box(centre, radius), None, line=scheme['ring'], line_width=1.0)

    def _dots(self, canvas, start, scheme, size=0.2, gap=0.12, vertical=False):
        """Three dots from `start` (the first one's corner): the big disc, the small one, the half-disc."""
        x, y = start
        for index, part in enumerate(('hero', 'second', 'half')):
            step = index * (size + gap)
            canvas.oval((x, y + step, size, size) if vertical else (x + step, y, size, size), scheme[part])
