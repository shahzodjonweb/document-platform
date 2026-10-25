"""Big number variants: the one figure set huge — on a disc, ring, tile, band or bubble, over dots, or on its own."""
import math

from pptx.util import Inches

from . import variant
from ..slide_layouts import _paragraph_height, _text_lines
from ..slides import _luminance, _text_width, contrast_ratio
from .kit import (FOOT, LEFT, RIGHT, RULE, WIDTH, Z, arc_points, block, disc, entries, eyebrow, figure, header,
                  header_band, header_compact, headline, hex_of, inks, inscribed, line, on, oval, parse_number,
                  polygon, readable, rect, ring, rule, strong, text, triangle_points)

TOP_EDGE = 0.62
# The classic drawer's word limits: figure, label, sentence.
VALUE, LABEL, BODY = 3, 10, 40
# (label, sentence) sizes, largest first: a caption takes the first at which it fits its room.
LADDER = ((24, 16), (24, 15), (22, 15), (22, 14), (20, 14), (20, 13), (18, 13), (18, 12), (16, 12))
LABEL_SPACING, BODY_SPACING = 1.12, 1.22
HEAD_LEADING = 1.08


# ---------------------------------------------------------------- measuring


def _plain(value, words=None):
    parts = str(value or '').split()
    return ' '.join(parts[:words] if words else parts)


def _item(section):
    items = entries('big_number', section)
    return items[0] if items else {}


def _value(item):
    return _plain(item.get('value'), VALUE)


def _need(ctx, width, paragraph):
    """Inches one paragraph (as for kit.text) takes in a box `width` wide, with the fitter's own allowance."""
    value = _plain(paragraph.get('text'), paragraph.get('words'))
    if not value:
        return 0.0
    bold = bool(paragraph.get('bold')) or bool(paragraph.get('heading') and ctx.heading_bold)
    points = _paragraph_height(dict(text=value, size=paragraph['size'], bold=bold,
                                    spacing=paragraph.get('spacing', 1.15)), Z(0, 0, width, 1))
    return (points + 5) / 72


def _wide(ctx, value, size):
    """Inches a one-line figure takes at `size` in the heading face."""
    return _text_width(value, size) * (1.06 if ctx.heading_bold else 1) / 72


def _figure_size(ctx, value, width, start, floor=36, tall=None):
    """The largest size up to `start` at which the figure keeps to one line `width` wide (and `tall` high)."""
    size = start
    while size > floor and value and (_text_lines(value, size, Inches(width), bold=ctx.heading_bold) > 1
                                      or (tall and _figure_tall(size) > tall)):
        size -= 2
    return size


def _figure_tall(size):
    """The height of a one-line figure's box at `size` points."""
    return size * 1.1 / 72 + 0.1


def _lift(size):
    """How far a figure's box is raised so its digits, not its line, sit on the middle of a shape."""
    return size * 0.08 / 72


def _round_figure(ctx, value, cx, cy, radius, start, floor=36, margin=0.06):
    """(box, size): the widest box inside the circle at (cx, cy) a one-line figure fits, and its size.

    The box is raised by `_lift`, and its corners still lie on the circle.
    """
    size = start
    while True:
        tall = _figure_tall(size)
        half = max(0.0, (radius - margin) ** 2 - (tall / 2 + _lift(size)) ** 2) ** 0.5
        box = (cx - half, cy - tall / 2 - _lift(size), 2 * half, tall)
        if size <= floor or (half > 0 and _text_lines(value, size, Inches(2 * half), bold=ctx.heading_bold) <= 1):
            return box, size
        size -= 2


def _put_figure(ctx, box, value, size, colour, align='left', anchor='middle'):
    figure(ctx, box, value, size=size, floor=min(size, 36), colour=colour, align=align, anchor=anchor, words=VALUE)


def _head(ctx, section, width, size, lines):
    """(size, inches) the heading takes as kit.headline sets it in a box `width` wide."""
    value = _plain(section.get('heading'), 14)
    if not value:
        return size, 0.0
    count = _text_lines(value, size, Inches(width), bold=ctx.heading_bold)
    while size > 18 and count > lines:
        size -= 2
        count = _text_lines(value, size, Inches(width), bold=ctx.heading_bold)
    return size, max(1, count) * size * HEAD_LEADING / 72 + 0.08


def _share(section):
    """The figure as a share from 0 to 1 when it is a percentage from 0 to 100; else None."""
    value = str(_item(section).get('value') or '')
    if '%' not in value:
        return None
    number = parse_number(value)
    return number / 100 if number is not None and 0 <= number <= 100 else None


def _figured(section, lines):
    """Whether the slide has a figure to set: every variant here is built round one."""
    return bool(_value(_item(section)))


def _percentage(section, lines):
    return _figured(section, lines) and _share(section) is not None


def _mark(ctx, fill):
    """A small mark's colour on a panel of the role `fill`: the accent if it shows there, else the panel's ink."""
    if fill != 'accent' and contrast_ratio(hex_of(ctx, 'accent'), hex_of(ctx, fill)) >= 2.2:
        return 'accent'
    return inks(fill)['ink']


def _shade(ctx):
    """The accent for marks drawn on the surface (rings, bars, dots), moved just enough to show on it.

    A navy accent all but vanishes on a dark ground and a pale yellow one on a light ground; text keeps its own
    roles, but a mark that carries meaning (the share of a pictogram, a progress arc) must be seen.
    """
    return readable(ctx, 'accent', 'surface', 2.4)


def _solid(ctx):
    """(fill, ink): the accent for a shape that holds the figure, and the ink that reads on it.

    A dark accent on a dark ground (navy on near-black) all but disappears, so there it is lightened, keeping its
    hue, until the shape shows. A pale accent on a light ground keeps its colour: its hue carries it.
    """
    accent, surface = hex_of(ctx, 'accent'), hex_of(ctx, 'surface')
    if _luminance(surface) > 0.4 or contrast_ratio(accent, surface) >= 1.9:
        return 'accent', 'on_accent'
    fill = readable(ctx, 'accent', 'surface', 1.9)
    return fill, on(fill)


def _bubble_points(box, radius, spout, steps=8):
    """A rounded rectangle at `box` with a speech tail on its foot: `spout` is (right foot, tip, left foot)."""
    x, y, w, h = box

    def corner(cx, cy, start):
        return [(cx + radius * math.cos(math.radians(start + 90 * k / steps)),
                 cy + radius * math.sin(math.radians(start + 90 * k / steps))) for k in range(steps + 1)]
    return (corner(x + w - radius, y + radius, -90) + corner(x + w - radius, y + h - radius, 0) + list(spout)
            + corner(x + radius, y + h - radius, 90) + corner(x + radius, y + radius, 180))


# ---------------------------------------------------------------- the caption: label, rule, sentence


class Caption:
    """The figure's label and sentence, measured for a column, then drawn where the variant puts them."""

    def __init__(self, ctx, item, width, room, *, ink='ink', muted='muted', mark=None, align='left',
                 ladder=LADDER, gap=0.16, space=0.2, bar=0.7, label_heading=True, label_width=None,
                 label_anchor='bottom', body_anchor='top', cap=None):
        self.ctx, self.item, self.width, self.align = ctx, item, width, align
        if cap:
            # The label never outgrows the slide's heading: a long heading set small takes the label down too.
            ladder = tuple(dict.fromkeys((min(label, max(16, cap)), body) for label, body in ladder))
        self.ink, self.muted, self.mark, self.bar = ink, muted, mark or _shade(ctx), bar
        self.gap, self.space, self.label_heading = gap, space, label_heading
        # The label may run wider than the sentence (a centred caption); measured a line longer than a viewer
        # sets it, it keeps to the side of its box nearest the rule or sentence it belongs with.
        self.label_width, self.label_anchor = label_width or width, label_anchor
        self.body_anchor = body_anchor
        for sizes in ladder:
            self.sizes = sizes
            if self.tall <= room:
                break

    def _label(self):
        size = self.sizes[0]
        return dict(text=self.item.get('label'), words=LABEL, size=size, floor=min(size, 16), colour=self.ink,
                    heading=self.label_heading, bold=not self.label_heading, spacing=LABEL_SPACING,
                    align=self.align)

    def _body(self):
        return dict(text=self.item.get('text'), words=BODY, size=self.sizes[1], floor=12, colour=self.muted,
                    spacing=BODY_SPACING, align=self.align)

    @property
    def label_tall(self):
        return _need(self.ctx, self.label_width, self._label())

    @property
    def body_tall(self):
        return _need(self.ctx, self.width, self._body())

    @property
    def middle(self):
        """The rule and the space round it, when there is a label and a sentence to part."""
        return self.gap + RULE + self.space if self.label_tall and self.body_tall and self.bar else (
            0.12 if self.label_tall and self.body_tall else 0.0)

    @property
    def tall(self):
        return self.label_tall + self.middle + self.body_tall

    def draw(self, x, y):
        """Draw the caption with its top at `y`; returns where it ends."""
        label, body = self._label(), self._body()
        label_tall, body_tall = self.label_tall, self.body_tall
        if label_tall:
            left = {'left': x, 'center': x + (self.width - self.label_width) / 2,
                    'right': x + self.width - self.label_width}[self.align]
            _field(self.ctx, (left, y, self.label_width, label_tall), label, anchor=self.label_anchor)
            y += label_tall
        if label_tall and body_tall and self.bar:
            y += self.gap
            start = {'left': x, 'center': x + (self.width - self.bar) / 2,
                     'right': x + self.width - self.bar}[self.align]
            rect(self.ctx, (start, y, self.bar, RULE), self.mark)
            y += RULE + self.space
        elif label_tall and body_tall:
            y += 0.12
        if body_tall:
            _field(self.ctx, (x, y, self.width, body_tall), body, anchor=self.body_anchor)
            y += body_tall
        return y


def _field(ctx, box, paragraph, anchor='top'):
    text(ctx, box, paragraph['text'], size=paragraph['size'], floor=paragraph['floor'],
         colour=paragraph['colour'], bold=paragraph.get('bold', False), heading=paragraph.get('heading', False),
         align=paragraph.get('align', 'left'), spacing=paragraph.get('spacing', 1.15), words=paragraph.get('words'),
         anchor=anchor)


def _heading_box(ctx, section, box, size, lines, *, colour=None, align='left', anchor='bottom'):
    headline(ctx, section, box, size=size, lines=lines, anchor=anchor, align=align, colour=colour)


def _foot_caption(ctx, item, box, cap=24):
    """The label over the sentence in one box, set from its foot, so the last line ends where `box` does.

    Measured line counts run a line long; a caption that must end level with something (a figure's baseline,
    a stroke's foot) is anchored there by its own box rather than by arithmetic on those counts.
    """
    block(ctx, box, [
        dict(text=item.get('label'), words=LABEL, size=max(16, min(24, cap)), floor=16, colour='ink', heading=True,
             spacing=LABEL_SPACING, after=10 if item.get('text') else 0),
        dict(text=item.get('text'), words=BODY, size=16, floor=12, colour='muted', spacing=BODY_SPACING),
    ], anchor='bottom')


# ---------------------------------------------------------------- disc


@variant('big_number', 'disc', accepts=_figured)
def disc_(ctx, section, lines):
    """The figure large on an accent disc inside a thin accent halo at the left; the label, a short rule and the
    sentence centred beside it."""
    top = header_compact(ctx, section)
    item = _item(section)
    room = FOOT - top
    halo = 0.2
    shade = _shade(ctx)
    diameter = min(3.85, room - 2 * halo - 0.15)
    outer = diameter + 2 * halo
    cx, cy = LEFT + outer / 2 + 0.05, top + room / 2
    fill, ink = _solid(ctx)
    ring(ctx, disc(cx, cy, outer), shade, width=1.25)
    oval(ctx, disc(cx, cy, diameter), fill)
    value = _value(item)
    box, size = _round_figure(ctx, value, cx, cy, diameter / 2 - 0.2, 116)
    _put_figure(ctx, box, value, size, ink, align='center')
    x = cx + outer / 2 + 0.7
    width = min(6.3, RIGHT - x)
    caption = Caption(ctx, item, width, room - 0.2, cap=_head(ctx, section, WIDTH, 28, 2)[0] - 4)
    caption.draw(x, cy - caption.tall / 2)


# ---------------------------------------------------------------- ring


@variant('big_number', 'ring', accepts=_figured)
def ring_(ctx, section, lines):
    """The figure in the accent inside a thick ring at the left — an arc filled to the share on a pale track when
    the figure is a percentage — and the heading, label and sentence in a column beside it."""
    eyebrow(ctx)
    item = _item(section)
    outer, thick = 4.6, 0.46
    shade = _shade(ctx)
    radius, inner = outer / 2, outer / 2 - thick
    cx, cy = LEFT + radius + 0.1, (TOP_EDGE + 0.3 + FOOT) / 2
    share = _share(section)
    if share is None or share >= 1:
        polygon(ctx, arc_points(cx, cy, radius, inner, 0, 360, steps=120), shade)
    else:
        polygon(ctx, arc_points(cx, cy, radius, inner, 0, 360, steps=120), 'accent_soft')
        if share > 0:
            end = 360 * share
            polygon(ctx, arc_points(cx, cy, radius, inner, 0, end, steps=max(8, int(end / 3))), shade)
            if share > 0.03:
                middle = (radius + inner) / 2
                for x, y in ((cx, cy - middle), _at(cx, cy, middle, end)):
                    oval(ctx, disc(x, y, thick), shade)
    value = _value(item)
    box, size = _round_figure(ctx, value, cx, cy, inner - 0.15, 108)
    _put_figure(ctx, box, value, size, 'accent_text', align='center')

    x = cx + radius + 0.85
    width = RIGHT - x
    head_size, head_tall = _head(ctx, section, width, 30, 4)
    lead = head_tall + 0.22 + RULE + 0.4
    caption = Caption(ctx, item, width, FOOT - 1.0 - lead, bar=0, gap=0.12, cap=head_size - 4)
    group = lead + caption.tall
    y = 1.0 + max(0.0, (FOOT - 1.0 - group) / 2 - 0.05)
    _heading_box(ctx, section, (x, y, width, head_tall), head_size, 4)
    rule(ctx, (x, y + head_tall + 0.22, 0.9, RULE))
    caption.draw(x, y + lead)


def _at(cx, cy, radius, degrees):
    angle = math.radians(degrees - 90)
    return cx + radius * math.cos(angle), cy + radius * math.sin(angle)


# ---------------------------------------------------------------- centred


@variant('big_number', 'centred', accepts=_figured)
def centred(ctx, section, lines):
    """The figure centred and huge between two hairlines, under a centred heading; the label below it and the
    sentence centred in a narrow column."""
    item = _item(section)
    eyebrow(ctx, (LEFT, TOP_EDGE, WIDTH, 0.3), align='center')
    shade = _shade(ctx)
    head_width = WIDTH - 2.4
    head_size, head_tall = _head(ctx, section, head_width, 28, 2)
    _heading_box(ctx, section, (LEFT + 1.2, 0.95, head_width, head_tall), head_size, 2, align='center',
                 anchor='top')
    top = 0.95 + head_tall + 0.25
    room = FOOT - top
    value = _value(item)
    column, space = 7.4, 0.2
    caption = Caption(ctx, item, column, room - _figure_tall(88) - space, align='center', bar=0, gap=0.16,
                      label_width=9.6, label_anchor='top', cap=head_size - 4)
    size = _figure_size(ctx, value, WIDTH - 3.0, 144, floor=60, tall=room - caption.tall - space)
    tall = _figure_tall(size)
    group = tall + space + caption.tall
    y = top + max(0.0, (room - group) / 2 - 0.05)
    wide = min(WIDTH - 3.0, _wide(ctx, value, size) + 0.3)
    x = LEFT + (WIDTH - wide) / 2
    _put_figure(ctx, (x, y, wide, tall), value, size, 'accent_text', align='center')
    # Hairlines out to the frame at the figure's middle, clear of its box.
    level = y + tall * 0.54
    reach = min(2.2, x - LEFT - 0.35)
    if reach > 0.5:
        line(ctx, (x - 0.3 - reach, level), (x - 0.3, level), shade, 1.5)
        line(ctx, (x + wide + 0.3, level), (x + wide + 0.3 + reach, level), shade, 1.5)
    caption.draw(LEFT + (WIDTH - column) / 2, y + tall + space)


# ---------------------------------------------------------------- band


@variant('big_number', 'band', accepts=_figured)
def band(ctx, section, lines):
    """The left half of the body a strong band holding the figure in its ink over a short rule, a notch pointing
    to the label and sentence on the surface at the right."""
    top = header_compact(ctx, section) + 0.15
    item = _item(section)
    panel = inks(strong(ctx))
    width, notch = WIDTH * 0.5, 0.34
    room = FOOT - top
    rect(ctx, (LEFT, top, width, room), panel['fill'])
    cy = top + room / 2
    polygon(ctx, triangle_points((LEFT + width - 0.01, cy - 0.38, notch, 0.76), 'right'), panel['fill'])
    pad = 0.5
    value = _value(item)
    size = _figure_size(ctx, value, width - 2 * pad, 128, tall=room - 1.0)
    tall = _figure_tall(size)
    y = cy - (tall + 0.18 + RULE) / 2
    _put_figure(ctx, (LEFT + pad, y - _lift(size), width - 2 * pad, tall), value, size, panel['ink'], align='center')
    rect(ctx, (LEFT + width / 2 - 0.5, y + tall + 0.18, 1.0, RULE * 1.3), _mark(ctx, panel['fill']))
    x = LEFT + width + notch + 0.6
    caption = Caption(ctx, item, RIGHT - x, room - 0.2, cap=_head(ctx, section, WIDTH, 28, 2)[0] - 4)
    caption.draw(x, cy - caption.tall / 2)


# ---------------------------------------------------------------- tile


@variant('big_number', 'tile', accepts=_figured)
def tile(ctx, section, lines):
    """A square accent tile at the right, a pale square offset behind it, holding the figure at its top and the
    label at its foot; the heading and the sentence in a column beside it."""
    item = _item(section)
    side, offset = 4.55, 0.26
    tile_x = RIGHT - side
    tile_y = (TOP_EDGE + FOOT - offset) / 2 - side / 2
    fill, ink = _solid(ctx)
    rect(ctx, (tile_x - offset, tile_y + offset, side, side), 'accent_soft')
    rect(ctx, (tile_x, tile_y, side, side), fill)
    pad = 0.42
    inner = side - 2 * pad
    value = _value(item)
    width = tile_x - offset - 0.7 - LEFT
    head_size, head_tall = _head(ctx, section, width, 32, 4)
    label = Caption(ctx, {'label': item.get('label')}, inner, 1.6, ink=ink, label_anchor='top',
                    ladder=((24, 16), (22, 16), (20, 16), (18, 16)), cap=head_size - 4)
    size = _figure_size(ctx, value, inner, 124, tall=side - 2 * pad - label.tall - 0.5)
    _put_figure(ctx, (tile_x + pad, tile_y + pad - 0.08, inner, _figure_tall(size)), value, size, ink,
                anchor='top')
    if label.tall:
        label.draw(tile_x + pad, tile_y + side - pad - label.tall)
        rect(ctx, (tile_x + pad, tile_y + side - pad - label.tall - 0.18, 0.7, RULE), ink)

    eyebrow(ctx)
    lead = head_tall + 0.24 + RULE + 0.36
    body = Caption(ctx, {'text': item.get('text')}, width, FOOT - 1.0 - lead,
                   ladder=((16, 16), (16, 15), (16, 14), (16, 13), (16, 12)))
    group = lead + body.tall
    y = 1.0 + max(0.0, (FOOT - 1.0 - group) / 2 - 0.05)
    _heading_box(ctx, section, (LEFT, y, width, head_tall), head_size, 4)
    rule(ctx, (LEFT, y + head_tall + 0.24, 0.9, RULE))
    body.draw(LEFT, y + lead)


# ---------------------------------------------------------------- underline


@variant('big_number', 'underline', accepts=_figured)
def underline(ctx, section, lines):
    """Under a heading band, the figure huge with a thick accent bar beneath it and the label beside the bar; the
    sentence in a column at the right past a hairline."""
    panel = strong(ctx)
    top = header_band(ctx, section, fill=panel, height=1.55, size=28)
    shade = _shade(ctx)
    item = _item(section)
    room = FOOT - top
    left = 6.3
    value = _value(item)
    bar_w, bar_h = 1.5, 0.16
    # The label is centred on the bar, whatever number of lines a viewer sets it in.
    label = Caption(ctx, {'label': item.get('label')}, left - bar_w - 0.35, 1.3, label_anchor='middle',
                    cap=_head(ctx, section, WIDTH - 0.8, 28, 2)[0] - 4,
                    ladder=((22, 16), (20, 16), (18, 16), (16, 16)))
    size = _figure_size(ctx, value, left, 150, tall=room - max(bar_h, label.tall) - 0.3)
    tall = _figure_tall(size)
    row = max(bar_h, label.tall)
    x = LEFT + left + 0.9
    body = Caption(ctx, {'text': item.get('text')}, RIGHT - x, room - 0.2, body_anchor='bottom',
                   ladder=((16, 16), (16, 15), (16, 14), (16, 13), (16, 12)))
    # The figure's digits start about a fifth of its box down; a long sentence may reach above them.
    crown = tall * 0.2
    group = max(tall + 0.1 + row, body.tall + crown)
    # What shows (the digits or the sentence's top, down to the label) sits midway between the band and the
    # frame's foot; the figure's box never rises onto the band.
    band_foot = top - 0.3
    lead = max(0.3, (FOOT - band_foot - (group - crown)) / 2)
    y = max(band_foot + 0.05, band_foot + lead - crown) + group - (tall + 0.1 + row)
    _put_figure(ctx, (LEFT, y, left, tall), value, size, 'accent_text', anchor='bottom')
    bar_y = y + tall + 0.1 + row / 2 - bar_h / 2
    rect(ctx, (LEFT + 0.04, bar_y, bar_w, bar_h), shade)
    label.draw(LEFT + bar_w + 0.35, y + tall + 0.1 + (row - label.tall) / 2)
    # The sentence ends level with the label, a hairline down its side as tall as it is: a one-line sentence
    # does not hang at the foot of a tall empty rule.
    end = y + tall + 0.1 + row
    start = end - body.tall
    if body.tall:
        line(ctx, (x - 0.45, start + 0.05), (x - 0.45, end - 0.05), shade, 1.25)
        body.draw(x, start)


# ---------------------------------------------------------------- bubble


@variant('big_number', 'bubble', accepts=_figured)
def bubble(ctx, section, lines):
    """The figure in a rounded speech bubble at the right, its tail pointing down to the label and sentence at the
    left."""
    top = header(ctx, section, size=30)
    item = _item(section)
    tail = 0.55
    width, tall = 5.0, min(3.0, FOOT - top - tail - 0.25)
    x, y = RIGHT - width - 0.16, top + 0.15
    shadow = 0.16
    # One outline, the tail part of it: the tail leaves the bubble's foot near its left corner and leans out
    # towards the caption. The card fill is all but the ground's colour, so the outline draws the bubble.
    spout = [(x + 1.52, y + tall), (x + 0.22, y + tall + tail), (x + 0.72, y + tall)]
    outline = _bubble_points((x, y, width, tall), 0.5, spout)
    polygon(ctx, [(px + shadow, py + shadow) for px, py in outline], 'accent_soft')
    polygon(ctx, outline, 'card', line=_shade(ctx), line_width=1.5)
    pad = 0.45
    value = _value(item)
    box = (x + pad, y + pad * 0.6, width - 2 * pad, tall - pad * 1.2)
    size = _figure_size(ctx, value, box[2], 120, tall=box[3])
    _put_figure(ctx, (box[0], box[1] - _lift(size), box[2], box[3]), value, size, 'card_accent', align='center')
    column = x - 0.95 - LEFT
    room = FOOT - top
    caption = Caption(ctx, item, column, room - 0.1, cap=_head(ctx, section, WIDTH, 30, 2)[0] - 4)
    caption.draw(LEFT, top + max(0.0, (room - caption.tall) / 2 - 0.05))


# ---------------------------------------------------------------- split vertical


@variant('big_number', 'split_vertical', accepts=_figured)
def split_vertical(ctx, section, lines):
    """The left 45% of the frame a pale full-height panel with the figure huge at its foot; the heading at the top
    of the right column and the label and sentence at its foot, level with the figure."""
    item = _item(section)
    soft = inks('accent_soft')
    width = WIDTH * 0.45
    rect(ctx, (LEFT, TOP_EDGE, width, FOOT - TOP_EDGE), 'accent_soft')
    pad = 0.5
    eyebrow(ctx, (LEFT + pad, TOP_EDGE + 0.32, width - 2 * pad, 0.3), colour=soft['muted'])
    rect(ctx, (LEFT + pad, TOP_EDGE + 0.78, 0.9, RULE), soft['ink'])
    value = _value(item)
    size = _figure_size(ctx, value, width - 2 * pad, 150, tall=3.0)
    tall = _figure_tall(size)
    bottom = FOOT - pad
    _put_figure(ctx, (LEFT + pad, bottom - tall, width - 2 * pad, tall), value, size, soft['ink'], anchor='bottom')

    x = LEFT + width + 0.65
    column = RIGHT - x
    head_size, head_tall = _head(ctx, section, column, 32, 4)
    y = TOP_EDGE + 0.32
    _heading_box(ctx, section, (x, y, column, head_tall), head_size, 4)
    rule(ctx, (x, y + head_tall + 0.22, 0.9, RULE))
    start = y + head_tall + 0.22 + RULE + 0.4
    # The caption's last line sits on the figure's baseline: both are set from the foot of boxes ending at the
    # panel's padding.
    _foot_caption(ctx, item, (x, start, column, bottom - 0.06 - start), cap=head_size - 4)


# ---------------------------------------------------------------- pictogram


@variant('big_number', 'pictogram', accepts=_percentage)
def pictogram(ctx, section, lines):
    """Ten discs in a row, the share filled in the accent (the last one in part) and the rest as rings, with the
    percentage large above and the label and sentence side by side below."""
    top = header_compact(ctx, section)
    item = _item(section)
    share = _share(section)
    shade = _shade(ctx)
    n, gap = 10, 0.34
    diameter = (WIDTH - gap * (n - 1)) / n
    diameter = min(diameter, 0.86)
    gap = (WIDTH - diameter * n) / (n - 1)
    room = FOOT - top
    label_w = 3.9
    body_w = WIDTH - label_w - 0.6
    # Side by side, the label and the sentence both hang from the same line.
    label = Caption(ctx, {'label': item.get('label')}, label_w, 1.4, label_anchor='top',
                    cap=_head(ctx, section, WIDTH, 28, 2)[0] - 4,
                    ladder=((24, 16), (22, 16), (20, 16), (18, 16)))
    body = Caption(ctx, {'text': item.get('text')}, body_w, 1.6,
                   ladder=((16, 16), (16, 15), (16, 14), (16, 13), (16, 12)))
    below = max(label.tall, body.tall)
    value = _value(item)
    size = _figure_size(ctx, value, 6.0, 96, floor=48, tall=room - diameter - below - 0.7)
    tall = _figure_tall(size)
    group = tall + 0.18 + diameter + 0.42 + below
    y = top + max(0.0, (room - group) / 2 - 0.05)
    _put_figure(ctx, (LEFT, y, 6.0, tall), value, size, 'accent_text', anchor='bottom')
    row = y + tall + 0.18
    filled = share * n
    for k in range(n):
        cx = LEFT + diameter / 2 + k * (diameter + gap)
        box = disc(cx, row + diameter / 2, diameter)
        portion = min(1.0, max(0.0, filled - k))
        if portion >= 0.999:
            oval(ctx, box, shade)
            continue
        ring(ctx, inscribed(box, 0.96), shade, width=2.0)
        if portion > 0.04:
            polygon(ctx, _segment(cx, row + diameter / 2, diameter * 0.48, portion), shade)
    y = row + diameter + 0.42
    label.draw(LEFT, y)
    body.draw(LEFT + label_w + 0.6, y)


def _segment(cx, cy, radius, portion, steps=28):
    """The part of a disc left of a vertical cut at `portion` of its width, as polygon points."""
    cut = -radius + 2 * radius * portion
    reach = math.acos(max(-1.0, min(1.0, cut / radius)))
    points = []
    for step in range(steps + 1):
        angle = reach + (2 * math.pi - 2 * reach) * step / steps
        points.append((cx + radius * math.cos(angle), cy - radius * math.sin(angle)))
    return points


# ---------------------------------------------------------------- corner


@variant('big_number', 'corner', accepts=_figured)
def corner(ctx, section, lines):
    """The figure huge in the top right corner and the label and sentence at the bottom left, under the heading,
    with a thin diagonal accent stroke rising from one to the other."""
    item = _item(section)
    eyebrow(ctx)
    left = 6.2
    shade = _shade(ctx)
    head_size, head_tall = _head(ctx, section, left, 30, 4)
    _heading_box(ctx, section, (LEFT, 0.95, left, head_tall), head_size, 4)
    rule(ctx, (LEFT, 0.95 + head_tall + 0.2, 0.9, RULE))
    value = _value(item)
    wide = WIDTH - left - 0.5
    size = _figure_size(ctx, value, wide, 168, tall=2.9)
    tall = _figure_tall(size)
    _put_figure(ctx, (RIGHT - wide, TOP_EDGE, wide, tall), value, size, 'accent_text', align='right',
                anchor='top')
    start = 0.95 + head_tall + 0.2 + RULE + 0.4
    _foot_caption(ctx, item, (LEFT, start, left - 0.2, FOOT - 0.04 - start), cap=head_size - 4)
    # The stroke runs from beside the caption's foot up to below the figure.
    bottom, peak = FOOT - 0.08, TOP_EDGE + tall + 0.25
    x0 = LEFT + left + 0.35
    x1 = x0 + (bottom - peak) * 0.55
    polygon(ctx, [(x0, bottom), (x0 + 0.1, bottom), (x1 + 0.1, peak), (x1, peak)], shade)
