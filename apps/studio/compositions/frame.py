"""Frame: quiet luxury — a double rule around every slide and everything set on the centre line.

Every slide wears the same frame: an outer rule in the brand colour itself and,
a step inside it, a hairline whose corners are cut back in quarter circles, a
small lozenge in each cut corner — the border of an engraved invitation or a
private bank's letterhead. The cover centres its title between a flourish (a
lozenge and two dots on long hairlines) and a short rule, with a small subtitle
under it; with a photograph the text keeps the left of the frame and the
picture is mounted on the right inside a hairline mat. The closing slide is its
mirror: title, flourish, line. Dividers set the section number inside a double
ring, like a seal, over a centred title and a small lozenge. Content slides keep
the frame in the margins their text never reaches, with a small pendant hung
from the top of the inner hairline, and mount their photographs inside the text
column like plates in a book. No pattern art: the frame is the decoration.

On a bold deck the cover, dividers and closing slide are the accent, ruled in
the design's second colour where it shows there (navy and gold) and in the ink
on the accent where it does not; everywhere else the ground is the surface and
the rules are the accent — or, where the accent cannot show on the surface
(navy on a night ground), gilt in the second colour, so rules and ornaments
are one metal. Ornaments take the second colour wherever it shows against
their ground.
"""
import math

from . import SLIDE_H, SLIDE_W, Composition, Plan, Text, composition

OUTER = 0.15      # the outer rule's outside edge, from the slide edge
WEIGHT = 0.03     # the outer rule's thickness: the accent element itself
INNER = 0.25      # the inner hairline: 0.07 in inside the outer rule, 0.11 in under the footer row (7.14)
NOTCH = 0.28      # radius of the inner hairline's cut corners
MIDDLE = SLIDE_W / 2
HAIRLINE = 0.75   # points


def _lozenge(cx, cy, width, height):
    return [(cx, cy - height / 2), (cx + width / 2, cy), (cx, cy + height / 2), (cx - width / 2, cy)]


def _notched(left, top, right, bottom, radius, steps=10):
    """A rectangle whose corners are cut back in quarter circles centred on each corner."""
    corners = [((right, top), 180, 90), ((right, bottom), 270, 180),
               ((left, bottom), 0, -90), ((left, top), 90, 0)]
    points = []
    for (cx, cy), start, end in corners:
        for step in range(steps + 1):
            angle = math.radians(start + (end - start) * step / steps)
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return points


@composition
class Frame(Composition):
    name = 'frame'
    # Content photographs are mounted inside the text column, like plates in a book,
    # with the same air (0.6 in) to the top hairline as to the side one.
    content_box = (0.85, 0.85, SLIDE_W - 1.7, 5.77)

    def ground(self, canvas, kind, photo=False):
        bold = kind != 'content' and canvas.roles['theme'] == 'bold'
        look = self._frame(canvas, bold)
        if kind == 'cover':
            return self._cover(canvas, look, photo)
        if kind == 'closing':
            return self._closing(canvas, look)
        if kind == 'section':
            return self._divider(canvas, look)
        # Content slides wear the frame's signature too: a small pendant hung from the
        # top centre of the inner hairline, well above the eyebrow (0.62) and headline.
        self._flourish(canvas, look, MIDDLE, INNER + 0.1, reach=0, size=0.75)
        return None

    # ------------------------------------------------------------ the frame

    def _frame(self, canvas, bold):
        """The ground, the double rule and its corner lozenges; the colours text and ornament use here."""
        from ..slides import contrast_ratio
        roles = canvas.roles
        ground = 'accent' if bold else 'surface'
        # The design's second colour dresses the ornaments wherever it shows against the ground.
        second = contrast_ratio(roles['secondary'], roles[ground]) >= 3.0
        canvas.background(ground)
        if bold:
            # The slide is the accent; the rules are gilt in the second colour, or the ink on it.
            canvas.accent((0, 0, SLIDE_W, SLIDE_H))
            line = 'secondary' if second else 'on_accent'
            look = dict(title='on_accent', muted='on_accent', numeral='on_accent', quiet='on_accent')
            canvas.rect((OUTER, OUTER, SLIDE_W - 2 * OUTER, SLIDE_H - 2 * OUTER), None, line=line,
                        line_width=2.0)
        else:
            # The outer rule is the brand colour itself: an accent panel with the surface laid over
            # it. An accent too close to the ground to show (navy on a night ground, yellow on
            # paper) gets a hairline on its outer edge, so the rule still reads as a rule — gilt
            # in the second colour where that shows, so rules and ornaments are one metal.
            faint = contrast_ratio(roles['accent'], roles['surface']) < 2.0
            gilt = faint and second
            line = 'secondary' if gilt else 'accent_text'
            canvas.accent((OUTER, OUTER, SLIDE_W - 2 * OUTER, SLIDE_H - 2 * OUTER),
                          **(dict(line=line, line_width=HAIRLINE) if faint else {}))
            canvas.rect((OUTER + WEIGHT, OUTER + WEIGHT, SLIDE_W - 2 * (OUTER + WEIGHT),
                         SLIDE_H - 2 * (OUTER + WEIGHT)), 'surface')
            look = dict(title='heading', muted='muted', numeral='heading' if gilt else 'accent_text',
                        quiet='muted')
        look.update(line=line, ornament='secondary' if second else line)
        canvas.polygon(_notched(INNER, INNER, SLIDE_W - INNER, SLIDE_H - INNER, NOTCH), None,
                       line=line, line_width=HAIRLINE)
        # A lozenge in each cut corner, halfway between the outer rule and the arc.
        corner = INNER + 0.06
        for x, y in ((corner, corner), (SLIDE_W - corner, corner),
                     (corner, SLIDE_H - corner), (SLIDE_W - corner, SLIDE_H - corner)):
            canvas.polygon(_lozenge(x, y, 0.09, 0.09), look['ornament'])
        return look

    # ------------------------------------------------------------ ornaments

    def _flourish(self, canvas, look, cx, cy, reach=1.3, gap=0.3, size=1.0):
        """A lozenge on the centre line with a dot either side and, past the dots, a long hairline."""
        canvas.polygon(_lozenge(cx, cy, 0.13 * size, 0.19 * size), look['ornament'])
        for side in (-1, 1):
            dot = cx + side * (gap - 0.1) * size
            canvas.oval((dot - 0.025, cy - 0.025, 0.05, 0.05), look['ornament'])
            if reach:
                start, end = cx + side * gap, cx + side * (gap + reach)
                canvas.line((min(start, end), cy), (max(start, end), cy), look['line'], HAIRLINE)

    def _rule(self, canvas, look, cx, cy, width=0.9):
        canvas.line((cx - width / 2, cy), (cx + width / 2, cy), look['line'], HAIRLINE)

    # ------------------------------------------------------------ slides

    def _cover(self, canvas, look, photo):
        if photo:
            # The picture mounted on the right of the frame, a hairline mat around it.
            # The mat sits the same 0.5 in from the inner hairline on all three sides.
            picture, mat = (7.05, 0.85, 5.43, 5.8), 0.1
            canvas.rect((picture[0] - mat, picture[1] - mat, picture[2] + 2 * mat, picture[3] + 2 * mat), None,
                        line=look['line'], line_width=HAIRLINE)
            # The text stack (flourish to subtitle) is centred on the picture's mid-height;
            # 32 pt sets a long title on three even lines in this column.
            cx, width, size, lines, top, reach, title_height = 3.65, 5.6, 32, 3, 1.7, 1.0, 2.1
            subtitle, subtitle_size = width, 16
        else:
            # A measure of 8.2 in breaks a three-line title evenly rather than leaving a
            # word alone on the last line; the subtitle is a line, not a caption, and
            # runs a little wider so a sentence-long one stays on one line.
            picture = None
            cx, width, size, lines, top, reach, title_height = MIDDLE, 8.2, 44, 3, 1.5, 1.5, 2.5
            subtitle, subtitle_size = 8.9, 18
        # The title is centred between the flourish above and the short rule below,
        # so a two-line title leaves the same air on both sides as a three-line one.
        self._flourish(canvas, look, cx, top, reach=reach)
        title_top = top + 0.45
        self._rule(canvas, look, cx, title_top + title_height + 0.45)
        return Plan(
            title=Text((cx - width / 2, title_top, width, title_height), look['title'], size, align='center',
                       anchor='middle', lines=lines),
            subtitle=Text((cx - subtitle / 2, title_top + title_height + 0.7, subtitle, 0.85), look['muted'],
                          subtitle_size, align='center', anchor='top'),
            quiet=look['quiet'],
            photo=picture)

    def _closing(self, canvas, look):
        # The cover's mirror: the title first, then the flourish, then the line under it.
        # The stack sits a little above the middle, on the slide's optical centre.
        width, bottom = 8.6, 3.45
        self._flourish(canvas, look, MIDDLE, bottom + 0.45, reach=1.5)
        return Plan(
            title=Text((MIDDLE - width / 2, bottom - 2.2, width, 2.2), look['title'], 44, align='center',
                       anchor='bottom', lines=2),
            subtitle=Text((MIDDLE - 4.1, bottom + 0.75, 8.2, 0.85), look['muted'], 18, align='center', anchor='top'),
            quiet=look['quiet'])

    def _divider(self, canvas, look):
        # The section number inside a double ring, a seal that echoes the double frame, on
        # hairlines; the title centred between it and a lozenge; the kicker under the lozenge.
        seal_y, seal, width = 2.25, 0.92, 8.6
        for ring in (seal, 0.74):
            canvas.oval((MIDDLE - ring / 2, seal_y - ring / 2, ring, ring), None, line=look['line'],
                        line_width=HAIRLINE)
        for side in (-1, 1):
            near, far = MIDDLE + side * (seal / 2 + 0.18), MIDDLE + side * (seal / 2 + 1.35)
            canvas.line((min(near, far), seal_y), (max(near, far), seal_y), look['line'], HAIRLINE)
        title_top = seal_y + seal / 2 + 0.38
        self._flourish(canvas, look, MIDDLE, title_top + 1.5 + 0.46, reach=0, size=0.85)
        return Plan(
            # 0.56 x 0.34: its corners stay inside the inner ring (radius 0.37).
            eyebrow=Text((MIDDLE - 0.28, seal_y - 0.17, 0.56, 0.34), look['numeral'], 18, align='center',
                         anchor='middle', numeral=True),
            title=Text((MIDDLE - width / 2, title_top, width, 1.5), look['title'], 40, align='center',
                       anchor='middle', lines=2),
            title_with_kicker=Text((MIDDLE - width / 2, title_top, width, 1.5), look['title'], 38, align='center',
                                   anchor='middle', lines=2),
            kicker=Text((MIDDLE - 4.0, title_top + 1.5 + 0.75, 8.0, 0.5), look['muted'], 16, align='center',
                        anchor='top'),
            quiet=look['quiet'])
