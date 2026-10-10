"""Diagonal: dynamic angles — a ramp rising out of the lower right, a cut falling across the top right.

Two diagonals make the whole deck, both at one angle (a rise or fall of 0.30
per inch, about 16.7 degrees). The *ramp* rises from the left edge to the
right edge: on the cover it is a large wedge in the accent sweeping up across
the lower right, with a thin blade of the second colour riding above it. The
*cut* falls from the top edge to the right edge: on the cover a corner
triangle and a parallel slash, so the two diagonals converge on the right
edge like an arrowhead; on a divider it slices a triangle of surface off an
accent slide, and the section number and title sit on the accent. On the
closing slide the ramp has risen and carries the last words, right-aligned to
answer the cover's top-left title. Content slides keep both diagonals as
small marks outside the text box — a corner wedge under the slide number and a
pair of slashes in the top-right corner.

A design's pattern fills the open surface above a blade and stops at the
diagonal: the shapes are drawn again over it, with the strip between blade
and wedge in the ground colour, so no pattern shows through.

A bold deck turns the cover over: the slide is the accent, the ramp is the
second colour and the blade between them is the paper; the closing slide
answers it in the same colours.
"""
from . import SLIDE_H, SLIDE_W, Composition, Plan, Text, composition

W, H = SLIDE_W, SLIDE_H
RAMP = 0.30        # both diagonals' rise or fall per inch (about 16.7 degrees)
CUT = RAMP
COVER_RAMP = 6.62  # the cover ramp at the left edge: above the footer row, which rides on it
CLOSING_RAMP = 4.9
CUT_TOP = 3.0      # where a divider's cut leaves the top edge
GAP = 0.15         # the ground left between a wedge and the blade beside it
BLADE = 0.52       # the blade's width where it leaves the slide
PHOTO_LEFT = 9.0   # a cover photo's left edge: right of the footer box, which ends at 8.99


def _accent_polygon(canvas, points):
    """The accent element as a polygon: like Canvas.accent, the first shape on the slide."""
    if len(canvas.slide.shapes):
        raise RuntimeError('The accent element must be the first shape on the slide.')
    return canvas.polygon(points, 'accent')


def _cut(left, width=0.0):
    """A band falling from the top edge at the cut's angle, `width` wide along the top from `left`.

    With no width it is the corner triangle from `left` to the right edge.
    """
    if not width:
        return [(left, 0), (W, 0), (W, CUT * (W - left))]
    return [(left, 0), (left + width, 0), (W, CUT * (W - left - width)), (W, CUT * (W - left))]


def _marks(canvas):
    """The corner triangle's colour and the slash's beside it, on the surface.

    The triangle is the larger mark, so it takes whichever colour stands off the
    surface more: a navy accent on a near-black dark deck would turn to mud.
    """
    from ..slides import contrast_ratio
    roles = canvas.roles
    accent, second = (contrast_ratio(roles[name], roles['surface']) for name in ('accent', 'secondary'))
    if accent < 2.0 and second > accent:
        return 'secondary', 'accent'
    return 'accent', 'secondary'


class _Edge:
    """A straight diagonal edge, y = start + slope * x, with a blade riding on its open side."""

    def __init__(self, start, slope, tip):
        self.start, self.slope, self.tip = start, slope, tip

    def y(self, x):
        return self.start + self.slope * x

    def blade(self):
        """A long thin triangle from a point at `tip`, GAP above the edge, BLADE wide at the right."""
        return [(self.tip, self.y(self.tip) - GAP), (W, self.y(W) - GAP), (W, self.y(W) - GAP - BLADE)]

    def blade_top(self, x):
        (x0, y0), _, (x1, y1) = self.blade()
        return y0 + (y1 - y0) * (x - x0) / (x1 - x0)

    def gap(self):
        """The strip of ground between the edge and the blade."""
        tip, right = self.y(self.tip), self.y(W)
        return [(self.tip, tip - GAP), (W, right - GAP), (W, right), (self.tip, tip)]


def _layers(canvas, *, ground, mass, mass_fill, edge, blade='secondary', art=None):
    """The slide's ground, its mass (the wedge or the cut slide), the blade, and the pattern between.

    `ground` is the slide's colour and `mass` the big shape's points. The first
    shape is the accent: the mass when it is the accent, else a full-bleed accent
    ground. `art` is (box, fade, colour, strength) for the design's pattern,
    drawn above the blade and stopped at the diagonal.
    """
    canvas.background(ground)
    if mass_fill == 'accent':
        _accent_polygon(canvas, mass)
    else:
        canvas.accent((0, 0, W, H))
    pattern = bool(art) and bool(canvas.look.get('art'))
    if pattern:
        box, fade, colour, strength = art
        canvas.art(box, fade=fade, colour=colour, strength=strength)
    if pattern or mass_fill != 'accent':
        canvas.polygon(mass, mass_fill)
    if pattern:
        # Over the pattern: the strip between the mass and the blade, in the ground.
        canvas.polygon(edge.gap(), ground)
    canvas.polygon(edge.blade(), blade)


@composition
class Diagonal(Composition):
    name = 'diagonal'

    def ground(self, canvas, kind, photo=False):
        if kind == 'cover':
            return self._cover(canvas, photo)
        if kind == 'closing':
            return self._closing(canvas)
        if kind == 'section':
            return self._divider(canvas)
        return self._content(canvas)

    @staticmethod
    def _turned(canvas):
        """Ground, mass, blade, the corner marks and the inks on each; a bold deck turns the slide over."""
        if canvas.roles.get('theme') == 'bold':
            # The slide is the accent; the ramp is the second colour, and the paper
            # runs between them as the blade.
            return {'ground': 'accent', 'mass': 'secondary', 'blade': 'surface', 'marks': ('secondary', 'surface'),
                    'open_ink': 'on_accent', 'open_soft': 'on_accent', 'mass_ink': 'on_secondary',
                    'mass_soft': 'on_secondary', 'pattern': 'on_accent', 'strength': 0.2}
        return {'ground': 'surface', 'mass': 'accent', 'blade': 'secondary', 'marks': _marks(canvas),
                'open_ink': 'heading', 'open_soft': 'muted', 'mass_ink': 'on_accent', 'mass_soft': 'on_accent',
                'pattern': None, 'strength': None}

    # ------------------------------------------------------------ cover

    def _cover(self, canvas, photo):
        look = self._turned(canvas)
        edge = _Edge(COVER_RAMP, -RAMP, tip=2.2)
        # The pattern fills the open right, clear of the title, down to the blade.
        art = None if photo else ((8.4, 0, W - 8.4, edge.blade_top(8.4) + 0.05), 'left', look['pattern'],
                                  look['strength'])
        _layers(canvas, ground=look['ground'], mass=[(0, edge.y(0)), (W, edge.y(W)), (W, H), (0, H)],
                mass_fill=look['mass'], edge=edge, blade=look['blade'], art=art)
        if not photo:
            # The cut falls from the top edge toward the rising ramp: the content
            # slides' corner mark at half as large again, so the two diagonals
            # converge on the right edge like an arrowhead.
            big, small = look['marks']
            canvas.polygon(_cut(10.3), big)
            canvas.polygon(_cut(9.4, 0.6), small)
        # A photo is a full-height panel on the right: the ramp and the blade run
        # straight into its left edge.
        width = PHOTO_LEFT - 0.85 - 0.4 if photo else 7.4
        # Room for four lines at 44 pt: the size is chosen for three by an estimate that
        # does not count word breaks, so a real title can run a line longer.
        return Plan(
            title=Text((0.85, 0.6, width, 2.75), look['open_ink'], 44, anchor='bottom', lines=3),
            subtitle=Text((0.85, 3.6, 4.8, 0.8), look['open_soft'], 17, anchor='top'),
            quiet=look['mass_soft'],
            photo=(PHOTO_LEFT, 0, W - PHOTO_LEFT, H) if photo else None)

    # ------------------------------------------------------------ closing

    def _closing(self, canvas):
        """The ramp has risen: the last words ride on it, low on the right, in the cover's colours."""
        look = self._turned(canvas)
        edge = _Edge(CLOSING_RAMP, -RAMP, tip=0.9)
        # The pattern hangs from the top edge and fades out above the words.
        art = ((0, 0, W, 3.3), 'down', look['pattern'], look['strength'])
        _layers(canvas, ground=look['ground'], mass=[(0, edge.y(0)), (W, edge.y(W)), (W, H), (0, H)],
                mass_fill=look['mass'], edge=edge, blade=look['blade'], art=art)
        left = 6.5
        return Plan(
            title=Text((left, 3.35, 12.48 - left, 2.05), look['mass_ink'], 56, anchor='bottom', lines=2,
                       align='right'),
            subtitle=Text((left, 5.55, 12.48 - left, 0.9), look['mass_soft'], 20, anchor='top', align='right'),
            quiet=look['mass_soft'])

    # ------------------------------------------------------------ divider

    def _divider(self, canvas):
        edge = _Edge(-CUT * CUT_TOP, CUT, tip=CUT_TOP + 2.0)
        mass = [(0, 0), (CUT_TOP, 0), (W, edge.y(W)), (W, H), (0, H)]
        # The pattern fills the surface corner the cut leaves, down to the blade.
        art = ((6.0, 0, W - 6.0, edge.blade_top(W) + 0.05), 'left', None, None)
        _layers(canvas, ground='surface', mass=mass, mass_fill='accent', edge=edge, art=art)
        # The section number is the hero, set large in the corner the cut leaves.
        return Plan(
            eyebrow=Text((0.85, 0.4, 3.2, 2.15), 'on_accent', 130, anchor='top', numeral=True),
            title=Text((0.85, 2.95, 8.4, 2.6), 'on_accent', 40, anchor='bottom', lines=3),
            title_with_kicker=Text((0.85, 2.95, 8.4, 1.85), 'on_accent', 38, anchor='bottom', lines=2),
            kicker=Text((0.85, 5.0, 8.4, 0.7), 'on_accent', 17, anchor='top'),
            quiet='on_accent')

    # ------------------------------------------------------------ content

    def _content(self, canvas):
        canvas.background('surface')
        # A corner wedge under the slide number, rising at the ramp's angle; its edge
        # passes 0.15 in under the number box.
        _accent_polygon(canvas, [(11.8, H), (W, H), (W, H - RAMP * (W - 11.8))])
        # A triangle and a slash in the top-right corner, falling at the cut's angle and
        # above the eyebrow: with the wedge below they converge on the right edge.
        big, small = _marks(canvas)
        canvas.polygon(_cut(11.45), big)
        canvas.polygon(_cut(10.75, 0.45), small)
        return None
