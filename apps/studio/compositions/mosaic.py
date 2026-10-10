"""Mosaic: a wall of square tiles, Memphis shapes on a Swiss grid.

Every tile is a block of one colour that may carry one figure — a quarter
disc swung from a corner, a half disc on a side, a triangle, an arch or a
disc — in the accent, the second colour, the soft tint or the deep ink; a
tile may span a square of four. A thin gap in the page colour runs between
all tiles, so each reads as a laid tile and no two figures run together
across a seam; the gap stays off the edges that run off the slide.

Cover and closing are bookends: a 4 x 5 wall of 1.32 in tiles fills one side
(the right on the cover, mirrored on the left of the closing) and the title
sits on the open page beside it, over a square, a circle and a triangle that
stand in for a rule. With a photo the picture takes the cover wall's
top-right 3 x 3 and the tiles wrap it. A divider is a slice of that wall: two
columns of the same tiles down the right edge, the section number set large
in a 2 x 2 block. Content slides keep a 2 x 2 cluster of small tiles in the
top-right corner and a strip of tiles along the bottom edge under the cover
wall's footprint, both outside the content text box.

Tile colours are picked as they are laid: each block keeps its pattern colour
unless that would match the page, a neighbouring block or a figure meeting it
across a seam, and then takes the next tone that stands apart, so a wall
never shows holes or runs two tiles together whatever the accent. On a bold
deck the accent tiles turn paper; where the deep ink is all but the page (a
dark accent, a dark deck) its figures become cut-outs in the page colour.

The walls stop at 6.6 in so the footer row always sits on the open page. A
bold deck sets covers, dividers and closing on the accent, which is then the
accent element; otherwise an accent tile is.
"""
import math

from . import SLIDE_H, SLIDE_W, Composition, Plan, Text, composition

TILE = 1.32                     # the grid: cover, closing and divider tiles
WALL_H = 5 * TILE               # 6.6: the footer row stays on the page
WALL_W = 4 * TILE               # 5.28: about 40% of the slide
SMALL = 0.42                    # the content slide's corner cluster
STRIP = TILE / 6                # 0.22: the content slide's bottom strip
GAP = 0.05                      # page colour between tiles
EDGE = 1e-3
NEAR = 20                       # two colours closer than this read as one
PAGE_NEAR = 10                  # a block this close to the page reads as a hole


# ---------------------------------------------------------------- colour


def _lab(value):
    value = value.lstrip('#')
    channels = []
    for index in (0, 2, 4):
        c = int(value[index:index + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def _distance(one, other):
    """How far apart two colours look (CIE76): under ~20 they read as one."""
    return math.dist(_lab(one), _lab(other))


def _tones(canvas, page):
    """The tile colours by letter — accent, second colour, soft tint, deep — and G, the page."""
    roles = canvas.roles
    theme = roles.get('theme', 'light')
    tones = {'A': 'accent', 'S': 'secondary', 'P': 'accent_soft', 'D': 'deep', 'G': page}
    if theme == 'dark':
        # Deep is all but the dark surface, so a deep figure is a cut-out (the
        # light ink would glare brighter than the title); the soft tint turns
        # muddy there, and the lightened accent takes its place.
        tones['D'] = 'surface'
        if _distance(roles['accent_text'], roles['accent']) > 20:
            tones['P'] = 'accent_text'
    elif _distance(roles['accent'], roles['deep']) < 24:
        # A dark accent and its deep ink read as one colour: the paper takes its
        # place (on a light page a figure in it is a cut-out).
        tones['D'] = 'surface'
    return tones


# Text that reads on a block of each role.
ON = {'accent': 'on_accent', 'secondary': 'on_secondary', 'deep': 'on_deep', 'surface': 'ink',
      'accent_soft': 'soft_ink'}


# ---------------------------------------------------------------- figures


def _arc(cx, cy, rx, ry, start, end, steps=18):
    return [(cx + rx * math.cos(math.radians(start + (end - start) * i / steps)),
             cy + ry * math.sin(math.radians(start + (end - start) * i / steps))) for i in range(steps + 1)]


def _figure(kind, at, x, y, w, h):
    """The points of a figure in the box (x, y, w, h); `at` is a corner or a side.

    A tile on a slide edge is a hair larger than the others (no gap there), so
    the figures stretch with the box rather than spill out of it.
    """
    if kind == 'quarter':
        # A quarter disc filling the tile, swung from corner `at`.
        cx, cy, start = {'tl': (x, y, 0), 'tr': (x + w, y, 90),
                         'br': (x + w, y + h, 180), 'bl': (x, y + h, 270)}[at]
        return [(cx, cy)] + _arc(cx, cy, w, h, start, start + 90, 24)
    if kind == 'half':
        # A half disc whose diameter is side `at`.
        if at in ('top', 'bottom'):
            cy = y if at == 'top' else y + h
            start = 0 if at == 'top' else 180
            return _arc(x + w / 2, cy, w / 2, h / 2, start, start + 180, 32)
        cx = x if at == 'left' else x + w
        start = -90 if at == 'left' else 90
        return _arc(cx, y + h / 2, w / 2, h / 2, start, start + 180, 32)
    if kind == 'tri':
        # Half the tile, with its right angle at corner `at`.
        corners = {'tl': (x, y), 'tr': (x + w, y), 'br': (x + w, y + h), 'bl': (x, y + h)}
        order = ['tl', 'tr', 'br', 'bl']
        keep = order.index(at)
        return [corners[order[(keep + step) % 4]] for step in (-1, 0, 1)]
    if kind == 'arch':
        # A doorway: a half disc on a rectangle, standing on the bottom edge.
        r = w / 2
        return [(x, y + h)] + _arc(x + r, y + r, r, r, 180, 360, 32) + [(x + w, y + h)]
    raise ValueError(kind)


def _sides(kind, at):
    """The sides of its tile a figure runs along (meeting a corner at a point does not count)."""
    if kind in ('quarter', 'tri'):
        return {'tl': {'top', 'left'}, 'tr': {'top', 'right'},
                'br': {'bottom', 'right'}, 'bl': {'bottom', 'left'}}[at]
    if kind == 'half':
        return {at}
    if kind == 'arch':
        return {'bottom', 'left', 'right'}
    return set()


def _inset(box):
    """The box less half the gap on every side that does not run off the slide."""
    x, y, w, h = box
    left = 0 if x <= EDGE else GAP / 2
    top = 0 if y <= EDGE else GAP / 2
    right = 0 if x + w >= SLIDE_W - EDGE else GAP / 2
    bottom = 0 if y + h >= SLIDE_H - EDGE else GAP / 2
    return (x + left, y + top, w - left - right, h - top - bottom)


def _shared(one, other, side):
    """How long an edge `other` shares with `one`'s `side`."""
    x, y, w, h = one
    X, Y, W, H = other
    if side in ('top', 'bottom'):
        edge, facing = (y, Y + H) if side == 'top' else (y + h, Y)
        across = min(x + w, X + W) - max(x, X)
    else:
        edge, facing = (x, X + W) if side == 'left' else (x + w, X)
        across = min(y + h, Y + H) - max(y, Y)
    return across if abs(edge - facing) < EDGE and across > EDGE else 0


OPPOSITE = {'top': 'bottom', 'bottom': 'top', 'left': 'right', 'right': 'left'}


class _Tiles:
    """The tiles on one slide, laid one by one.

    Each block keeps its pattern colour unless that is the page's, a
    neighbour's, or that of a figure meeting it across a seam; then it takes
    the next tone that stands apart. Each figure likewise avoids its block and
    whatever it runs into across the seam it lies on.
    """

    def __init__(self, canvas, page):
        self.canvas = canvas
        self.page = page
        self.tones = _tones(canvas, page)
        # Blocks this far apart read as two tiles. On a bold deck the gap is a
        # dark line between light tiles, so paper and the soft tint already do.
        self.apart = 12 if page == 'accent' else NEAR
        self.placed = []
        self.occupied = []

    def near(self, one, other, limit=NEAR):
        return _distance(self.canvas.colour(one), self.canvas.colour(other)) < limit

    def occupy(self, boxes):
        """Boxes that will hold tiles or a picture: a side facing one is not open to the page."""
        self.occupied += list(boxes)

    def facing(self, box):
        """What lies across each side of `box`: the blocks laid there, the figures that run
        along that seam, and whether part of the side is open to the page."""
        found = {'blocks': {}, 'figures': {}, 'open': {}}
        x, y, w, h = box
        for side in OPPOSITE:
            blocks, figures = [], []
            for tile in self.placed:
                if _shared(box, tile['box'], side):
                    blocks.append(tile['ground'])
                    if OPPOSITE[side] in tile['sides']:
                        figures.append(tile['colour'])
            bleeds = {'top': y <= EDGE, 'left': x <= EDGE, 'right': x + w >= SLIDE_W - EDGE,
                      'bottom': y + h >= SLIDE_H - EDGE}[side]
            covered = sum(_shared(box, other, side) for other in self.occupied if other != box)
            found['blocks'][side], found['figures'][side] = blocks, figures
            found['open'][side] = not bleeds and covered < (w if side in ('top', 'bottom') else h) - EDGE
        return found

    def _clear(self, role, against, limit=NEAR):
        return not any(self.near(role, other, PAGE_NEAR if other == self.page else limit) for other in against)

    def ground(self, wanted, figure, facing):
        """The block's colour: `wanted` (a letter) unless it would vanish or run into a neighbour."""
        # On an accent page an accent tile turns paper.
        tones = dict(self.tones, A='surface') if self.tones['A'] == self.page else self.tones
        candidates = [tones[wanted]] + [tones[key] for key in 'PSAD']
        roles = list(dict.fromkeys(candidates))
        blocks = [colour for colours in facing['blocks'].values() for colour in colours]
        figures = [colour for colours in facing['figures'].values() for colour in colours]

        def cost(index, role):
            # Worst first: a hole, a block like its neighbour's, a figure run
            # into from across a seam, then (for a stand-in) its own figure
            # lost, then closeness. The pattern's own colour keeps its block and
            # lets the figure change instead.
            near = [_distance(self.canvas.colour(role), self.canvas.colour(other)) for other in blocks]
            return (self.near(role, self.page, PAGE_NEAR), min(near or [99]) < self.apart,
                    not self._clear(role, figures, self.apart), bool(index and figure) and self.near(role, figure),
                    -min(near or [99]))

        costs = [cost(index, role) for index, role in enumerate(roles)]
        clean = [index for index, flags in enumerate(costs) if not any(flags[:4])]
        best = clean[0] if clean else min(range(len(roles)), key=lambda index: (costs[index], index))
        return roles[best]

    def figure(self, wanted, ground, sides, facing):
        """The figure's colour: `wanted` unless it would vanish into its block or run into a neighbour.

        A figure in the page's own colour is a cut-out: it opens onto the gap
        whatever lies beyond, so only an edge open to the page rules it out.
        """
        tones = self.tones
        role = tones[wanted]
        opens = [self.page for side in sides if facing['open'][side]]
        across = [colour for side in sides for colour in facing['blocks'][side] + facing['figures'][side]]
        order = [role] + sorted(dict.fromkeys(tone for tone in tones.values() if tone != role),
                                key=lambda tone: -_distance(self.canvas.colour(tone), self.canvas.colour(ground)))
        for tone in order:
            cut = self.near(tone, self.page, PAGE_NEAR)
            if self._clear(tone, [ground] + opens) and (cut or self._clear(tone, across, self.apart)):
                role = tone
                break
        else:
            role = max(order, key=lambda tone: _distance(self.canvas.colour(tone), self.canvas.colour(ground)))
        return role

    def tile(self, box, ground, kind=None, colour=None, at=None, lead=False, fill=None):
        """Lay one tile; `lead` makes its block the accent element, `fill` fixes its block's role."""
        sides = _sides(kind, at) if kind else set()
        facing = self.facing(box)
        if lead:
            block = 'accent'
        else:
            block = fill or self.ground(ground, self.tones.get(colour) if kind else None, facing)
        figure = self.figure(colour, block, sides, facing) if kind else None
        inner = _inset(box)
        if lead:
            self.canvas.accent(inner)
        else:
            self.canvas.rect(inner, block)
        if kind == 'disc':
            self.canvas.oval(inner, figure)
        elif kind:
            self.canvas.polygon(_figure(kind, at, *inner), figure)
        self.placed.append({'box': box, 'ground': block, 'colour': figure, 'sides': sides})
        return block

    def wall(self, left, top, size, pattern, lead=False):
        """A wall of tiles from a pattern: rows of (ground, figure, colour, at[, span]).

        None leaves a cell open to the page; '-' marks a cell something larger
        covers. Letters name tones (see _tones). With `lead`, the first accent
        tile is laid first, as the accent element.
        """
        cells = []
        for row, specs in enumerate(pattern):
            for column, spec in enumerate(specs):
                if spec is None or spec == '-':
                    continue
                ground, kind, colour, at, *span = spec
                span = span[0] if span else 1
                box = (left + column * size, top + row * size, size * span, size * span)
                cells.append((box, ground, kind, colour, at))
        self.occupy(cell[0] for cell in cells)
        if lead:
            first = next(index for index, cell in enumerate(cells) if cell[1] == 'A')
            cells.insert(0, cells.pop(first))
        for index, (box, ground, kind, colour, at) in enumerate(cells):
            self.tile(box, ground, kind, colour, at, lead=lead and index == 0)


# ---------------------------------------------------------------- patterns

# The cover wall, 4 columns by 5 rows: a big disc top right, a big half disc
# rising from the foot of the wall below it, small tiles between, and one open
# cell at the bottom corner by the title. The colours alternate so no block
# meets its own colour, and no figure runs along a seam into its own colour.
# (A disc or a quarter's arc may graze a seam: across the gap that reads as a
# touch, not a join.)
COVER = [
    [('A', 'quarter', 'S', 'tl'), ('S', 'quarter', 'P', 'bl'), ('P', 'disc', 'A', None, 2), '-'],
    [('P', 'arch', 'S', 'bottom'), ('A', 'tri', 'S', 'br'), '-', '-'],
    [('A', 'quarter', 'P', 'bl'), ('P', 'tri', 'S', 'bl'), ('S', 'half', 'P', 'right'), ('A', 'tri', 'D', 'tl')],
    [('S', 'quarter', 'P', 'br'), ('A', 'half', 'S', 'bottom', 2), '-', ('S', 'half', 'P', 'top')],
    [None, '-', '-', ('P', 'half', 'A', 'right')],
]
# With a photo the picture takes the top-right 3 x 3; the tiles wrap it.
COVER_PHOTO = [[spec if column == 0 or row > 2 else '-' for column, spec in enumerate(specs)]
               for row, specs in enumerate(COVER)]


def _mirror(pattern):
    """The pattern flipped left to right: spans re-anchored, figures turned to face the other way."""
    turn = {'tl': 'tr', 'tr': 'tl', 'bl': 'br', 'br': 'bl', 'left': 'right', 'right': 'left'}
    width = len(pattern[0])
    flipped = [[None] * width for _ in pattern]
    for row, specs in enumerate(pattern):
        for column, spec in enumerate(specs):
            if spec is None or spec == '-':
                continue
            ground, kind, colour, at, *span = spec
            span = span[0] if span else 1
            target = width - column - span
            flipped[row][target] = (ground, kind, colour, turn.get(at, at), *([span] if span > 1 else []))
            for down in range(span):
                for across in range(span):
                    if down or across:
                        flipped[row + down][target + across] = '-'
    return flipped


CLOSING = _mirror(COVER)
# The divider column, 2 tiles wide: a row of tiles, the number's 2 x 2 block,
# two rows of tiles. Figures sit on outer edges or away from the block.
COLUMN = [
    [('P', 'half', 'A', 'top'), ('S', 'quarter', 'P', 'tr')],
    ['-', '-'],
    ['-', '-'],
    [('S', 'half', 'A', 'bottom'), ('P', 'quarter', 'S', 'br')],
    [('P', 'quarter', 'S', 'bl'), ('A', 'tri', 'P', 'br')],
]
# The content slide's corner cluster: figures sit only on its outer edges.
CLUSTER = [[('S', 'quarter', 'P', 'tl'), ('A', None, None, None)],
           [('P', 'half', 'A', 'left'), ('D', 'half', 'A', 'bottom')]]
# The bottom strip repeats seven of the wall's tiles.
STRIP_RUN = [('A', None, None, None), ('P', 'quarter', 'S', 'bl'), ('S', 'half', 'P', 'top'),
             ('P', 'tri', 'A', 'tl'), ('A', 'disc', 'D', None), ('S', None, None, None),
             ('P', 'quarter', 'A', 'bl')]


def _mark(canvas, left, top, tones, size=0.3, gap=0.16):
    """A square, a circle and a triangle in a row: the rule under a title.

    Each takes the first tile colour that stands out on the page and from the
    one before it, ending with the ink that reads on the page.
    """
    page = canvas.colour(tones['G'])
    last = 'on_accent' if tones['G'] == 'accent' else 'ink'
    chosen = []
    # Three tones well apart if the palette has them, else three that still
    # differ (paper and the soft tint on a bold page), else the page's ink.
    for apart in (24, 12):
        for tone in [tones[key] for key in 'ASDP'] + [last]:
            value = canvas.colour(tone)
            if (len(chosen) < 3 and _distance(value, page) > 36
                    and all(_distance(value, canvas.colour(o)) > apart for o in chosen)):
                chosen.append(tone)
    chosen = (chosen + [last] * 3)[:3]
    step = size + gap
    canvas.rect((left, top, size, size), chosen[0])
    canvas.oval((left + step, top, size, size), chosen[1])
    x = left + 2 * step
    canvas.polygon([(x, top + size), (x + size / 2, top), (x + size, top + size)], chosen[2])


@composition
class Mosaic(Composition):
    name = 'mosaic'

    def ground(self, canvas, kind, photo=False):
        if kind == 'cover':
            return self._cover(canvas, photo)
        if kind == 'closing':
            return self._closing(canvas)
        if kind == 'section':
            return self._divider(canvas)
        return self._content(canvas)

    def _lead(self, canvas, page):
        """Whether a tile leads as the accent element; on an accent page the page itself does."""
        if page == 'accent':
            canvas.accent((0, 0, SLIDE_W, SLIDE_H))
            return False
        return True

    def _page(self, canvas):
        """The page's fill and the text roles that read on it: title, subtitle, footer."""
        if canvas.roles.get('theme') == 'bold':
            return 'accent', 'on_accent', 'on_accent', 'on_accent'
        return 'surface', 'heading', 'muted', 'muted'

    # ------------------------------------------------------------ cover and closing

    def _cover(self, canvas, photo):
        page, ink, muted, quiet = self._page(canvas)
        canvas.background(page)
        left = SLIDE_W - WALL_W
        tiles = _Tiles(canvas, page)
        picture = (left + TILE, 0, 3 * TILE, 3 * TILE)
        if photo:
            tiles.occupy([picture])
        lead = self._lead(canvas, page)
        tiles.wall(left, 0, TILE, COVER_PHOTO if photo else COVER, lead=lead)
        text_w = left - 0.85 - 0.75
        _mark(canvas, 0.85, 4.78, tiles.tones)
        return Plan(
            title=Text((0.85, 0.9, text_w, 3.55), ink, 46, anchor='bottom', lines=4),
            subtitle=Text((0.85, 5.4, text_w, 1.1), muted, 18, anchor='top'),
            quiet=quiet,
            photo=_inset(picture) if photo else None)

    def _closing(self, canvas):
        page, ink, muted, quiet = self._page(canvas)
        canvas.background(page)
        tiles = _Tiles(canvas, page)
        tiles.wall(0, 0, TILE, CLOSING, lead=self._lead(canvas, page))
        text_left = WALL_W + 0.95
        text_w = 12.48 - text_left
        # Short words beside a full-height wall: the group centres on the wall.
        _mark(canvas, text_left, 3.98, tiles.tones)
        return Plan(
            title=Text((text_left, 0.9, text_w, 2.75), ink, 56, anchor='bottom', lines=3),
            subtitle=Text((text_left, 4.6, text_w, 1.1), muted, 18, anchor='top'),
            quiet=quiet)

    # ------------------------------------------------------------ divider

    def _divider(self, canvas):
        page, ink, muted, quiet = self._page(canvas)
        canvas.background(page)
        left = SLIDE_W - 2 * TILE
        tiles = _Tiles(canvas, page)
        block = (left, TILE, 2 * TILE, 2 * TILE)
        tiles.occupy([block])
        # The number's block is the accent element; on a bold deck the whole
        # page is, and the block takes the deep ink, the paper or a tile colour.
        if self._lead(canvas, page):
            fill = tiles.tile(block, 'A', lead=True)
        else:
            fill = tiles.tile(block, 'D', fill=self._numeral_block(canvas, tiles))
        tiles.wall(left, 0, TILE, COLUMN)
        text_w = left - 0.85 - 0.9
        inner = _inset(block)
        inset = 0.25
        # The title's last line sits level with the foot of the number's block.
        _mark(canvas, 0.85, 4.29, tiles.tones)
        return Plan(
            eyebrow=Text((inner[0] + inset, inner[1] + inset, inner[2] - 2 * inset, inner[3] - 2 * inset),
                         ON[fill], 72, align='center', anchor='middle', numeral=True, bold=True),
            title=Text((0.85, 0.48, text_w, 3.48), ink, 58, anchor='bottom', lines=4),
            title_with_kicker=Text((0.85, 1.35, text_w, 2.61), ink, 58, anchor='bottom', lines=3),
            kicker=Text((0.85, 4.92, text_w, 1.0), muted, 20, anchor='top'),
            quiet=quiet)

    def _numeral_block(self, canvas, tiles):
        """On an accent page: the first of deep, paper, second colour and soft tint that stands off it."""
        for role in (tiles.tones['D'], 'surface', 'secondary', 'accent_soft'):
            if role in ON and not tiles.near(role, tiles.page, NEAR):
                return role
        return 'surface'

    # ------------------------------------------------------------ content

    def _content(self, canvas):
        canvas.background('surface')
        # The corner cluster's accent tile is the accent element. Its left edge
        # keeps clear of the content text, which ends at 12.48.
        cluster = _Tiles(canvas, 'surface')
        cluster.wall(12.53 - GAP / 2, 0, SMALL, CLUSTER, lead=True)
        # The strip runs under the cover wall's footprint and off the right edge.
        strip = _Tiles(canvas, 'surface')
        left = SLIDE_W - WALL_W
        count = round(WALL_W / STRIP)
        boxes = [(left + index * STRIP, SLIDE_H - STRIP, STRIP, STRIP) for index in range(count)]
        strip.occupy(boxes)
        for index, box in enumerate(boxes):
            ground, kind, colour, at = STRIP_RUN[index % len(STRIP_RUN)]
            strip.tile(box, ground, kind, colour, at)
        return None
