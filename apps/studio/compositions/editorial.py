"""Editorial: a magazine page — oversized type, hairline rules and a great deal of paper.

Every slide carries the same running head: a hairline across the top margin
with a short, thin accent tab sitting on its right-hand end, like the folio
rule of a monthly, and every page stands on a foot rule above the folio line.
The cover hangs its title very large and tight from the masthead down across
the top of the page and leaves the subtitle small at the foot, on one line
where it can; a cover photograph stands in the right-hand column, its top on
the title's cap line. Dividers set the section number enormous in the accent
beside a column rule that runs from head to foot, with the title at the foot
of the narrow column on the numeral's baseline. The closing slide sets its
line large in the accent at the foot of the page, with the subtitle in a note
column behind the same kind of rule. Content photographs are plates inside
the type area, between the head and foot rules. In the bold theme the cover,
dividers and closing slide are printed on the accent itself.
"""
from . import SLIDE_H, SLIDE_W, Composition, Plan, Text, composition

LEFT, RIGHT = 0.85, 12.483        # the type area every layout writes between
WIDTH = RIGHT - LEFT
HAIR = 0.012                      # a hairline, about 0.9 pt
HEAD = 0.42                       # the running head's hairline, above every slide's text
TAB = (1.1, 0.055)                # the accent tab on the head rule's right end, about 4 pt thick
FOOT = 6.58                       # the foot rule, above the folio line (6.82)
COLUMN = 7.75                     # where a divider's title column (and a cover photo) starts
NOTE = 9.7                        # where the closing slide's note column starts


@composition
class Editorial(Composition):
    name = 'editorial'
    # Content photographs are plates inside the type area, about 0.2 in under the
    # head rule and 0.2 in above the foot rule, never bled off the page.
    content_box = (LEFT, 0.62, WIDTH, 5.76)

    def ground(self, canvas, kind, photo=False):
        if kind == 'cover':
            return self._cover(canvas, photo)
        if kind == 'closing':
            return self._closing(canvas)
        if kind == 'section':
            return self._divider(canvas)
        canvas.background('surface')
        rule = _rule(canvas)
        self._running_head(canvas, rule, 'accent_text')
        # The foot rule frames the page as on every other slide. A photo slide
        # skips it: image_full's caption box runs 6.1-6.7, across the rule.
        if not photo:
            canvas.rect((LEFT, FOOT, WIDTH, HAIR), rule)
        return None

    # ------------------------------------------------------------ pieces

    def _page(self, canvas):
        """The ground of a feature page; returns its colour scheme."""
        scheme = _scheme(canvas)
        canvas.background(scheme['ground'])
        if scheme['ground'] == 'accent':
            canvas.accent((0, 0, SLIDE_W, SLIDE_H))
        self._running_head(canvas, scheme['rule'], scheme['tab'])
        canvas.rect((LEFT, FOOT, WIDTH, HAIR), scheme['rule'])
        return scheme

    def _running_head(self, canvas, rule, tab):
        """The hairline across the top margin with the accent tab on its right end.

        On paper the accent element is the tab itself, then painted over in
        accent_text — the accent corrected to read on the paper — so a navy
        accent on a night ground or a pale yellow on white never vanishes, and
        the tab matches the divider numerals.
        """
        width, height = TAB
        box = (RIGHT - width, HEAD + HAIR - height, width, height)
        if not canvas.drawn:
            canvas.accent(box)
        canvas.rect((LEFT, HEAD, WIDTH, HAIR), rule)
        canvas.rect(box, tab)

    # ------------------------------------------------------------ slides

    def _cover(self, canvas, photo):
        scheme = self._page(canvas)
        # The title hangs from the masthead. Its box holds one line more than
        # the fit allows: a title fitted to three lines by its width can wrap
        # to four at word breaks, and that line falls into white space.
        # The subtitle is a small dek on the foot rule: on one line across a
        # plain cover, in a narrow column (about 50 characters) beside a photo,
        # where a line as wide as the title column would leave a word or two behind.
        if photo:
            # The picture takes the divider's title column, so the grid holds;
            # its top is level with the 60 pt cap line, its foot 0.2 in above the rule.
            width, size, lines, measure = COLUMN - 0.45 - LEFT, 60, 4, 4.6
            picture = (COLUMN, 1.0, RIGHT - COLUMN, 5.38)
        else:
            width, size, lines, measure = WIDTH, 76, 3, 7.6
            picture = None
        return Plan(
            title=Text((LEFT, 0.7, width, 4.56), scheme['ink'], size, anchor='top', lines=lines),
            subtitle=Text((LEFT, 5.46, measure, 1.0), scheme['muted'], 14, anchor='bottom'),
            quiet=scheme['muted'],
            photo=picture)

    def _closing(self, canvas):
        scheme = self._page(canvas)
        # The last line set large in the accent at the foot of the page, like
        # the divider numerals; the subtitle in a narrow column beside it on
        # the same baseline, behind the same column rule as a divider.
        _column_rule(canvas, NOTE - 0.4, scheme['rule'])
        return Plan(
            title=Text((LEFT, 0.9, NOTE - 0.75 - LEFT, 5.35), scheme['figure'], 110, anchor='bottom', lines=2),
            subtitle=Text((NOTE, 4.79, RIGHT - NOTE, 1.3), scheme['muted'], 15, anchor='bottom'),
            quiet=scheme['muted'])

    def _divider(self, canvas):
        scheme = self._page(canvas)
        # A column rule between the numeral and the title, from head to foot.
        _column_rule(canvas, COLUMN - 0.45, scheme['rule'])
        width = RIGHT - COLUMN
        # The title's last line, or the kicker's, sits on the numeral's baseline (about 6.1).
        return Plan(
            eyebrow=Text((LEFT, 0.55, COLUMN - 0.65 - LEFT, 5.95), scheme['figure'], 360, anchor='bottom',
                         numeral=True),
            title=Text((COLUMN, 1.0, width, 5.2), scheme['ink'], 40, anchor='bottom', lines=4),
            title_with_kicker=Text((COLUMN, 1.0, width, 4.35), scheme['ink'], 40, anchor='bottom', lines=4),
            kicker=Text((COLUMN, 5.5, width, 0.7), scheme['muted'], 16, anchor='bottom'),
            quiet=scheme['muted'])


def _scheme(canvas):
    """The colours of a feature page: on the paper, or on the accent in the bold theme."""
    if canvas.roles.get('theme') == 'bold':
        return {'ground': 'accent', 'ink': 'on_accent', 'muted': 'on_accent', 'figure': 'on_accent',
                'rule': 'on_accent', 'tab': 'on_accent'}
    return {'ground': 'surface', 'ink': 'heading', 'muted': 'muted', 'figure': 'accent_text',
            'rule': _rule(canvas), 'tab': 'accent_text'}


def _column_rule(canvas, left, colour):
    """A vertical hairline joining the running head to the foot rule."""
    canvas.rect((left, HEAD + HAIR, HAIR, FOOT - HEAD - HAIR), colour)


def _rule(canvas):
    """Hairlines in the ink on paper; softer on a dark page, where full ink glares."""
    return 'muted' if canvas.roles.get('theme') == 'dark' else 'ink'
