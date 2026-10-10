"""Sidebar: a corporate report, a sheet of paper set into a deep binding.

The cover is a deep column down the left two-fifths, a report's spine, with a
halftone screen bleeding off its top left corner and the subtitle low in it.
The sheet beside it is set into the deep on every side: an edge in the rule
colour binds it to the column, a margin of deep runs above and to its right,
and the footer row is the frame's bottom. The title sits on the sheet, large
and low, over a short rule. A cover photo fills the sheet instead; the column
then widens a little and carries the title and the subtitle itself.

Each divider widens the column to two-thirds, its number at the top over a
hairline and its title and kicker at the foot, and leaves a narrow strip of the
sheet beside it holding only the halftone, bled off the sheet's corner. The
closing slide is the column grown across the whole slide, the back cover, with
the halftone off its top right corner and the edge down its right side.

Content slides keep a slim column on the left with an index tab in the rule
colour standing out of it level with the eyebrow, and a page-head hairline
over the text column.

The edge, the rules and the tab share one colour: the accent where it shows
on the column, else the design's second colour. A dark deck lifts the sheet a
step above its ground so the frame still reads, and gives content slides a
column in the accent, since its deep would vanish into the dark surface; a
bold deck makes the column the accent itself.
"""
import math

from . import SLIDE_H, SLIDE_W, Composition, Plan, Text, composition

COVER = 5.3        # the cover's column, two-fifths of the slide
COVER_PHOTO = 6.2  # a photo cover's column, wide enough to hold the title
DIVIDER = 8.9      # a divider's column, two-thirds
BASE = 6.62        # the sheet ends here; the deep under the footer row is the frame's bottom
INSET = 0.3        # the frame's margin above and to the right of the sheet
EDGE = 0.07        # the edge between the column and the sheet
LEFT = 0.85        # text in the column lines up with the brand name below it
SPINE = 0.42       # content slides' column
TAB = (0.57, 0.4)  # the index tab, centred on the eyebrow line
TAB_OUT = 0.2      # how far it stands out of the column (it ends at x 0.62)


def _contrast(roles, one, other):
    from ..slides import contrast_ratio
    return contrast_ratio(roles[one], roles[other])


def _rule(roles, fill, fallback):
    """The colour of the edge and the rules on `fill`: the accent where it shows
    there, else the second colour, else `fallback` (the ink that reads on it)."""
    return next((role for role in ('accent', 'secondary') if _contrast(roles, role, fill) >= 2.2), fallback)


def _tab(roles, fill, ink):
    """The index tab's colour: the rule colour, as long as it also shows on the
    surface it stands out onto; else whichever ink shows on both."""
    for role in ('accent', 'secondary', ink, 'ink'):
        if _contrast(roles, role, fill) >= 2.2 and _contrast(roles, role, 'surface') >= 1.3:
            return role
    return _rule(roles, fill, ink)


def _inks(canvas):
    """The column's fill, the inks that read on it, the sheet's, and the rule colours."""
    roles = canvas.roles
    theme = roles.get('theme')
    if theme == 'bold':
        inks = {'fill': 'accent', 'ink': 'on_accent', 'muted': 'on_accent'}
    else:
        inks = {'fill': 'deep', 'ink': 'on_deep', 'muted': 'deep_muted'}
    # The sheet set into the frame: the surface, or on a dark deck a step
    # lighter than it, so the deep frame still reads around it.
    if theme == 'dark':
        inks['page'], inks['page_ink'], inks['page_muted'] = 'card', 'card_ink', 'card_muted'
    else:
        inks['page'], inks['page_ink'], inks['page_muted'] = 'surface', 'ink', 'muted'
    inks['rule'] = _rule(roles, inks['fill'], inks['ink'])
    # The rule under a title on the sheet: the same colour where it shows on
    # the sheet, else the accent darkened until it reads there.
    inks['page_rule'] = inks['rule'] if _contrast(roles, inks['rule'], inks['page']) >= 1.8 else 'accent_text'
    # The halftone on the column: its quiet ink, softened on the accent of a
    # bold deck, where full-strength white dots would shout.
    inks['screen'] = {'colour': inks['muted'], 'alpha': 0.55 if theme == 'bold' else None}
    return inks


def _ground(canvas, inks, accent_box):
    """The column's fill over the slide, with the accent element first: the whole
    slide when the column is the accent, else the edge, overdrawn in the rule colour."""
    canvas.background(inks['fill'])
    if inks['fill'] == 'accent':
        canvas.accent((0, 0, SLIDE_W, SLIDE_H))
        canvas.rect(accent_box, inks['rule'])
    else:
        canvas.accent(accent_box)
        if inks['rule'] != 'accent':
            canvas.rect(accent_box, inks['rule'])


def _clipped(points, clip):
    """A convex polygon cut to a box (Sutherland-Hodgman)."""
    left, top, width, height = clip
    edges = [(lambda p: p[0] >= left, lambda a, b: _cross_x(a, b, left)),
             (lambda p: p[0] <= left + width, lambda a, b: _cross_x(a, b, left + width)),
             (lambda p: p[1] >= top, lambda a, b: _cross_y(a, b, top)),
             (lambda p: p[1] <= top + height, lambda a, b: _cross_y(a, b, top + height))]
    for inside, cross in edges:
        if not points:
            break
        kept = []
        for index, point in enumerate(points):
            previous = points[index - 1]
            if inside(point):
                if not inside(previous):
                    kept.append(cross(previous, point))
                kept.append(point)
            elif inside(previous):
                kept.append(cross(previous, point))
        points = kept
    return points


def _cross_x(a, b, x):
    t = (x - a[0]) / ((b[0] - a[0]) or 1e-9)
    return (x, a[1] + (b[1] - a[1]) * t)


def _cross_y(a, b, y):
    t = (y - a[1]) / ((b[1] - a[1]) or 1e-9)
    return (a[0] + (b[0] - a[0]) * t, y)


def _dot(canvas, centre, size, colour, clip, alpha=None):
    """A dot of `size` at `centre`, cut by the edges of `clip` where it crosses them."""
    x, y = centre
    radius = size / 2
    left, top, width, height = clip
    if x - radius >= left and x + radius <= left + width and y - radius >= top and y + radius <= top + height:
        canvas.oval((x - radius, y - radius, size, size), colour, alpha=alpha)
        return
    ring = [(x + radius * math.cos(2 * math.pi * step / 40), y + radius * math.sin(2 * math.pi * step / 40))
            for step in range(40)]
    cut = _clipped(ring, clip)
    if len(cut) >= 3:
        canvas.polygon(cut, colour, alpha=alpha)


def _halftone(canvas, area, corner, colour, columns=14, rows=10, step=0.22, biggest=0.2, alpha=None):
    """A printed halftone screen bled off one corner of `area` ('top left' or 'top right').

    The biggest dot sits on the corner itself, so the area's edges cut the
    first row and column the way a trimmed page cuts a screen printed past it;
    the dots shrink away from the corner and run out.
    """
    left, top, width, _ = area
    origin_x = left if corner == 'top left' else left + width
    direction = 1 if corner == 'top left' else -1
    for row in range(rows):
        for column in range(columns):
            distance = math.hypot(column / (columns - 1), row / (rows - 1)) / math.sqrt(2)
            size = biggest * (1 - distance) ** 1.4
            if size < 0.035:
                continue
            _dot(canvas, (origin_x + direction * column * step, top + row * step), size, colour, area, alpha)


def _texture(canvas, area, corner, colour, sheet=False, **screen):
    """The design's own pattern in `area`'s corner if it has one, else the halftone.

    On the sheet a pattern keeps the design's own colour; on the column it takes `colour`.
    """
    art = canvas.look.get('art')
    if not art:
        _halftone(canvas, area, corner, colour, **screen)
        return
    step = screen.get('step', 0.22)
    left, top, width, height = area
    box_h = min(height, step * screen.get('rows', 10) + 0.3)
    if corner == 'top left':
        # Across the column's head, fading down; the column's edge trims it.
        canvas.art((left, top, width, box_h), fade='down', colour=colour)
        return
    box_w = min(width, step * screen.get('columns', 14) + 0.3)
    canvas.art((left + width - box_w, top, box_w, box_h), fade='corner',
               colour=art.get('colour', 'accent') if sheet else colour)


@composition
class Sidebar(Composition):
    name = 'sidebar'
    # Content photos butt against the column rather than covering it.
    content_box = (SPINE, 0.0, SLIDE_W - SPINE, SLIDE_H)

    def ground(self, canvas, kind, photo=False):
        if kind == 'cover':
            return self._cover(canvas, photo)
        if kind == 'closing':
            return self._closing(canvas)
        if kind == 'section':
            return self._divider(canvas)
        return self._content(canvas)

    def _frame(self, canvas, column, under_photo=False):
        """The deep ground with a sheet set into it right of `column`: the edge
        binds it to the column and a margin of the ground runs above and right of it."""
        inks = _inks(canvas)
        _ground(canvas, inks, (column, INSET, EDGE, BASE - INSET))
        sheet = (column + EDGE, INSET, SLIDE_W - INSET - column - EDGE, BASE - INSET)
        # Under a photo the sheet stays a hair inside it, so no sliver shows at its edges.
        trim = 0.03 if under_photo else 0
        canvas.rect((sheet[0] + trim, sheet[1] + trim, sheet[2] - 2 * trim, sheet[3] - 2 * trim), inks['page'])
        return inks, sheet

    def _cover(self, canvas, photo):
        if photo:
            inks, sheet = self._frame(canvas, COVER_PHOTO, under_photo=True)
            width = COVER_PHOTO - LEFT - 0.5
            # The screen stops short of the title, which climbs higher here.
            _texture(canvas, (0, 0, COVER_PHOTO, 2.0), 'top left', inks['screen']['colour'],
                     alpha=inks['screen']['alpha'], rows=9)
            return Plan(
                title=Text((LEFT, 2.1, width, 2.4), inks['ink'], 36, anchor='bottom', lines=4),
                rule=((LEFT, 4.74, 0.9, 0.06), inks['rule']),
                subtitle=Text((LEFT, 5.0, width, 1.35), inks['muted'], 16, anchor='top'),
                quiet=inks['muted'],
                photo=sheet)
        inks, sheet = self._frame(canvas, COVER)
        _texture(canvas, (0, 0, COVER, BASE), 'top left', inks['screen']['colour'], alpha=inks['screen']['alpha'])
        page = sheet[0] + 0.75
        return Plan(
            title=Text((page, 1.5, sheet[0] + sheet[2] - 0.4 - page, 3.7), inks['page_ink'], 46,
                       anchor='bottom', lines=3),
            rule=((page, 5.5, 1.1, 0.06), inks['page_rule']),
            subtitle=Text((LEFT, 3.3, COVER - LEFT - 0.6, 1.9), inks['muted'], 17, anchor='bottom'),
            quiet=inks['muted'])

    def _divider(self, canvas):
        inks, sheet = self._frame(canvas, DIVIDER)
        # On the sheet the screen is printed in the brand's ink; on a dark
        # deck's lifted sheet in its quiet ink, as the cover's is on the column.
        _texture(canvas, sheet, 'top right', inks['page_muted'] if inks['page'] == 'card' else 'accent_text',
                 sheet=True, rows=12)
        width = DIVIDER - LEFT - 0.7
        canvas.line((LEFT, 2.25), (DIVIDER - 0.7, 2.25), inks['muted'], 0.75)
        return Plan(
            eyebrow=Text((LEFT, 0.55, 3.0, 1.5), inks['muted'], 80, anchor='bottom', numeral=True),
            title=Text((LEFT, 2.55, width, 2.7), inks['ink'], 40, anchor='bottom', lines=4),
            title_with_kicker=Text((LEFT, 2.55, width, 2.0), inks['ink'], 40, anchor='bottom', lines=2),
            kicker=Text((LEFT, 4.75, width, 0.9), inks['muted'], 18, anchor='top', lines=2),
            quiet=inks['muted'])

    def _closing(self, canvas):
        inks = _inks(canvas)
        _ground(canvas, inks, (SLIDE_W - EDGE, 0, EDGE, SLIDE_H))
        # The cover's halftone again, bled off the back cover's top right corner.
        _texture(canvas, (0, 0, SLIDE_W - EDGE, SLIDE_H), 'top right', inks['screen']['colour'],
                 alpha=inks['screen']['alpha'])
        return Plan(
            title=Text((LEFT, 1.85, 8.2, 3.4), inks['ink'], 54, anchor='bottom', lines=3),
            rule=((LEFT, 5.52, 1.1, 0.06), inks['rule']),
            subtitle=Text((LEFT, 5.76, 7.4, 0.8), inks['muted'], 18, anchor='top'),
            quiet=inks['muted'])

    def _content(self, canvas):
        roles = canvas.roles
        theme = roles.get('theme')
        # The column: the deep, the accent on a bold deck, and on a dark deck
        # the accent too (the deep would vanish into the dark surface), or the
        # accent lifted until it shows there.
        if theme == 'light':
            fill, ink = 'deep', 'on_deep'
        elif theme == 'bold' or _contrast(roles, 'accent', 'surface') >= 1.45:
            fill, ink = 'accent', 'on_accent'
        else:
            fill, ink = 'accent_text', 'surface'
        rule = _tab(roles, fill, ink)
        canvas.background('surface')
        top, height = TAB
        tab = (0, top, SPINE + TAB_OUT, height)
        if fill == 'accent':
            canvas.accent((0, 0, SPINE, SLIDE_H))
            canvas.rect(tab, rule)
        else:
            canvas.accent(tab)
            canvas.rect((0, 0, SPINE, top), fill)
            canvas.rect((0, top + height, SPINE, SLIDE_H - top - height), fill)
            if rule != 'accent':
                canvas.rect(tab, rule)
        canvas.line((LEFT, 0.34), (SLIDE_W - LEFT, 0.34), 'muted', 0.5)
        return None
