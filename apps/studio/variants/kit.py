"""What a variant draws with: shapes in inches with colours by role, and text that fits.

A variant is drawn on a slide whose ground, photo and chrome are in place, like
a classic drawer (apps/studio/slide_layouts.py), and keeps the same rules:

* **Inside the frame.** Every shape and text box stays in `FRAME`: x from 0.85
  to 12.483 in, y from 0.62 to 6.65 in. Compositions decorate outside it, and
  the footer, slide number and logo sit below it. A photo layout's picture is
  the one exception: it goes where the variant's `photo` box says.
* **Text on a known fill.** Text is set in the ink that reads on the fill
  under its whole box: `inks(fill)` names it for each fill role, and `tones`
  and `hues` carry their own. A text box inside a disc is the disc's
  `inscribed` box, never the disc's square, whose corners are off it.
* **Nothing across text.** No line, edge or other fill runs under a text box;
  connectors and rules go between boxes, not through them.
* **Every field is fitted.** Text goes through `text`, `block` or `bullets`,
  which shrink to a readable floor and only then cut, marking the slide; a
  variant that cuts is not used for that slide (variants.choose). Running text
  never goes below 12 pt, and each field keeps the word limit the classic
  drawer gives it, so a variant never cuts what the classic one keeps.
"""
import math

from pptx.util import Inches, Pt

from .. import slides as base
from ..compositions import Canvas
from ..layouts import PRO, parse_number
from ..slide_layouts import (ALIGN, ANCHOR, BOTTOM, LABELS, LEFT, TOP, WIDTH, Z, _paragraph_height, _put_paragraphs,
                             _text_lines, _units, body_text, clip, columns_of, fit_headline, fitted, items_of, put)
from ..slide_layouts import header as classic_header

__all__ = ['ALIGN', 'ANCHOR', 'BOTTOM', 'LABELS', 'LEFT', 'TOP', 'WIDTH', 'Z', 'body_text', 'clip', 'columns_of',
           'items_of', 'parse_number', 'PRO']

RIGHT = LEFT + WIDTH          # 12.483
FOOT = 6.65                   # nothing a variant draws goes lower: footer, number and logo are below
FRAME = (LEFT, 0.62, WIDTH, FOOT - 0.62)
SQUEEZE = 2                   # how many points below the deck's list size a variant's list may go
RULE = 3 / 72                 # the accent rule's thickness

# A fill role and the roles that read on it: ink, quieter ink, and an accent for marks and labels.
PAIRS = {
    'surface': ('ink', 'muted', 'accent_text'),
    'card': ('card_ink', 'card_muted', 'card_accent'),
    'surface_alt': ('card_ink', 'card_muted', 'card_accent'),
    'accent_soft': ('soft_ink', 'soft_muted', 'soft_ink'),
    'accent': ('on_accent', 'on_accent', 'on_accent'),
    'deep': ('on_deep', 'deep_muted', 'on_deep'),
    'secondary': ('on_secondary', 'on_secondary', 'on_secondary'),
}


def inks(fill):
    """{'ink', 'muted', 'accent'}: the roles that read on the fill role `fill`."""
    ink, muted, accent = PAIRS[fill]
    return {'fill': fill, 'ink': ink, 'muted': muted, 'accent': accent}


def strong(ctx, prefer=('deep', 'accent', 'secondary')):
    """The fill role in `prefer` that stands out most from the slide's surface.

    'deep' is a near-black panel on a light deck but nearly the ground itself on
    a dark one; a panel meant to be seen asks for this instead of naming one.
    """
    surface = base._luminance(ctx.roles['surface'])
    return max(prefer, key=lambda role: (abs(base._luminance(ctx.roles[role]) - surface), -prefer.index(role)))


def hex_of(ctx, value):
    """A role's colour ('accent', 'card_ink' ...) or a hex colour, as upper-case hex."""
    value = ctx.roles.get(value, value)
    return str(value).lstrip('#').upper()


# ---------------------------------------------------------------- colour series


def _paint(ctx, fill):
    ink = base.ink_on(fill, 4.5)
    return {'fill': fill, 'ink': ink, 'muted': ink,
            # The fill's own colour made to read on the slide, for a number or label in it.
            'text': base._reads_on(fill, ctx.roles['surface'], 4.5)}


def tones(ctx, n):
    """`n` fills in the accent's own hue, darkest first, each with the inks that read on it.

    Each is a dict: 'fill', 'ink' and 'muted' (text on the fill), and 'text'
    (the fill's colour made to read on the slide's surface).
    """
    hue, _, saturation = base._hls(ctx.roles['accent'])
    saturation = max(saturation, 0.3) if saturation > 0.08 else saturation
    lightness = [0.24 + 0.46 * step / max(1, n - 1) for step in range(n)]
    return [_paint(ctx, base._from_hls(hue, value, saturation)) for value in lightness]


def hues(ctx, n):
    """`n` distinct fills that start from the design's accent and second colour.

    The rest are spaced round the colour wheel from the accent, at a calm
    strength, so a three-part slide can give each part its own colour and
    still belong to the deck. Turned at a saturated accent's full strength the
    greens and violets came out neon, so they are held to a middle strength,
    and yellows and greens a step darker, where they glare most. A grey
    accent has no hue to turn; it gets tones.
    """
    accent = ctx.roles['accent']
    hue, lightness, saturation = base._hls(accent)
    if saturation < 0.12:
        return tones(ctx, n)
    lightness, saturation = min(0.5, max(0.36, lightness)), min(0.58, max(saturation, 0.4))
    fills = [accent]
    secondary = ctx.roles.get('secondary')
    if secondary and secondary != ctx.roles.get('accent_soft') and _distance(hue, base._hls(secondary)[0]) > 0.06:
        fills.append(secondary)
    taken = [base._hls(fill)[0] for fill in fills]
    step = 0
    while len(fills) < n and step < 64:
        step += 1
        # Halves, then quarters, then eighths of the wheel: as far from the rest as can be.
        denominator = 2 ** math.ceil(math.log2(step + 1))
        numerator = 2 * (step - denominator // 2) + 1
        turned = (hue + numerator / denominator) % 1.0
        if all(_distance(turned, other) > 0.07 for other in taken):
            glaring = 0.1 < turned < 0.48
            fills.append(base._from_hls(turned, lightness - (0.08 if glaring else 0), saturation))
            taken.append(turned)
    while len(fills) < n:
        fills.append(fills[len(fills) % max(1, len(taken))])
    return [_paint(ctx, fill) for fill in fills[:n]]


def _distance(one, other):
    gap = abs(one - other) % 1.0
    return min(gap, 1 - gap)


def on(fill, target=4.5):
    """The ink that reads on any hex `fill`."""
    return base.ink_on(fill, target)


def readable(ctx, colour, background='surface', target=4.5):
    """`colour` (role or hex) moved until it reads on `background` (role or hex)."""
    return base._reads_on(hex_of(ctx, colour), hex_of(ctx, background), target)


# ---------------------------------------------------------------- shapes


def _canvas(ctx):
    return Canvas(ctx.slide, ctx.roles, {}, 'content')


def rect(ctx, box, fill, **options):
    """A rectangle at `box` (x, y, w, h in inches); `fill` a role, a hex colour, or None with `line`."""
    return _canvas(ctx).rect(box, fill, **options)


def rounded(ctx, box, fill, radius=0.12, **options):
    return _canvas(ctx).rounded(box, fill, radius=radius, **options)


def oval(ctx, box, fill, **options):
    return _canvas(ctx).oval(box, fill, **options)


def ring(ctx, box, colour, width=1.5):
    """A circle's outline only. Text may sit inside its `inscribed` box."""
    return _canvas(ctx).oval(box, None, line=colour, line_width=width)


def polygon(ctx, points, fill, **options):
    """A filled polygon through `points` (inches). The checker and previewer read its true outline."""
    return _canvas(ctx).polygon(points, fill, **options)


def line(ctx, start, end, colour, width=1.0):
    """A straight line (inches, `width` in points). Never across a text box."""
    return _canvas(ctx).line(start, end, colour, width)


def chevron_points(box, point=None, notch=True):
    """A chevron pointing right; `point` is the depth of its tip (inches)."""
    x, y, w, h = box
    point = min(w * 0.45, h * 0.5 if point is None else point)
    points = [(x, y), (x + w - point, y), (x + w, y + h / 2), (x + w - point, y + h), (x, y + h)]
    if notch:
        points.append((x + point, y + h / 2))
    return points


def arrow_points(box, head=None, shaft=0.52, direction='right'):
    """A block arrow filling `box`; `head` its length, `shaft` the share of the height the shaft takes."""
    x, y, w, h = box
    if direction in ('right', 'left'):
        head = min(w * 0.5, h * 0.6 if head is None else head)
        top, bottom = y + h * (1 - shaft) / 2, y + h * (1 + shaft) / 2
        points = [(x, top), (x + w - head, top), (x + w - head, y), (x + w, y + h / 2),
                  (x + w - head, y + h), (x + w - head, bottom), (x, bottom)]
        return [(2 * x + w - px, py) for px, py in points] if direction == 'left' else points
    head = min(h * 0.5, w * 0.6 if head is None else head)
    left, right = x + w * (1 - shaft) / 2, x + w * (1 + shaft) / 2
    points = [(left, y), (right, y), (right, y + h - head), (x + w, y + h - head), (x + w / 2, y + h),
              (x, y + h - head), (left, y + h - head)]
    return [(px, 2 * y + h - py) for px, py in points] if direction == 'up' else points


def hexagon_points(box, pointy=False):
    """A hexagon filling `box`: flat top and bottom, or pointed top and bottom."""
    x, y, w, h = box
    if pointy:
        d = h * 0.25
        return [(x + w / 2, y), (x + w, y + d), (x + w, y + h - d), (x + w / 2, y + h), (x, y + h - d), (x, y + d)]
    d = w * 0.25
    return [(x + d, y), (x + w - d, y), (x + w, y + h / 2), (x + w - d, y + h), (x + d, y + h), (x, y + h / 2)]


def diamond_points(box):
    x, y, w, h = box
    return [(x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2)]


def triangle_points(box, direction='up'):
    x, y, w, h = box
    return {'up': [(x + w / 2, y), (x + w, y + h), (x, y + h)],
            'down': [(x, y), (x + w, y), (x + w / 2, y + h)],
            'right': [(x, y), (x + w, y + h / 2), (x, y + h)],
            'left': [(x + w, y), (x + w, y + h), (x, y + h / 2)]}[direction]


def parallelogram_points(box, slant=None):
    x, y, w, h = box
    slant = h * 0.35 if slant is None else slant
    return [(x + slant, y), (x + w, y), (x + w - slant, y + h), (x, y + h)]


def trapezoid_points(box, inset=None):
    """Wider at the bottom by `inset` on each side (a pyramid's band)."""
    x, y, w, h = box
    inset = w * 0.12 if inset is None else inset
    return [(x + inset, y), (x + w - inset, y), (x + w, y + h), (x, y + h)]


def tab_points(box, cut=None, corner='top_right'):
    """A rectangle with one corner cut off at 45 degrees (a folder tab, a ticket)."""
    x, y, w, h = box
    cut = min(w, h) * 0.3 if cut is None else cut
    return {'top_right': [(x, y), (x + w - cut, y), (x + w, y + cut), (x + w, y + h), (x, y + h)],
            'top_left': [(x + cut, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y + cut)],
            'bottom_right': [(x, y), (x + w, y), (x + w, y + h - cut), (x + w - cut, y + h), (x, y + h)],
            'bottom_left': [(x, y), (x + w, y), (x + w, y + h), (x + cut, y + h), (x, y + h - cut)]}[corner]


def arc_points(cx, cy, outer, inner, start, end, steps=None):
    """A slice of a ring (inner 0: of a disc) from `start` to `end` degrees, clockwise from 12 o'clock."""
    steps = steps or max(6, int(abs(end - start) / 4))

    def at(radius, degrees):
        angle = math.radians(degrees - 90)
        return cx + radius * math.cos(angle), cy + radius * math.sin(angle)
    points = [at(outer, start + (end - start) * step / steps) for step in range(steps + 1)]
    if inner > 0:
        points += [at(inner, end - (end - start) * step / steps) for step in range(steps + 1)]
    else:
        points.append((cx, cy))
    return points


def around(cx, cy, radius, n, start=0):
    """`n` points evenly round a circle, the first at `start` degrees clockwise from 12 o'clock."""
    return [(cx + radius * math.cos(math.radians(start + 360 * k / n - 90)),
             cy + radius * math.sin(math.radians(start + 360 * k / n - 90))) for k in range(n)]


def inscribed(box, share=0.7):
    """The box that fits inside the disc (or other rounded shape) drawn at `box`."""
    x, y, w, h = box
    return (x + w * (1 - share) / 2, y + h * (1 - share) / 2, w * share, h * share)


def disc(cx, cy, diameter):
    """The box of a circle centred at (cx, cy)."""
    return (cx - diameter / 2, cy - diameter / 2, diameter, diameter)


# ---------------------------------------------------------------- layout arithmetic


def split(start, length, n, gap):
    """`n` equal spans of `length` from `start` with `gap` between: [(start, size), ...]."""
    size = (length - gap * (n - 1)) / n
    return [(start + k * (size + gap), size) for k in range(n)]


def grid(box, n, per_row, gap=0.2, row_gap=None):
    """`n` boxes in rows of `per_row` filling `box`; a short last row is centred."""
    x, y, w, h = box
    rows = -(-n // per_row)
    row_gap = gap if row_gap is None else row_gap
    width = (w - gap * (per_row - 1)) / per_row
    height = (h - row_gap * (rows - 1)) / rows
    boxes = []
    for k in range(n):
        row, column = divmod(k, per_row)
        in_row = min(per_row, n - row * per_row)
        offset = (w - (in_row * width + (in_row - 1) * gap)) / 2
        boxes.append((x + offset + column * (width + gap), y + row * (height + row_gap), width, height))
    return boxes


def height(ctx, text, width, size, *, bold=False, heading=False, spacing=1.15):
    """Inches `text` takes at `size` points in a box `width` inches wide."""
    bold = bold or (heading and ctx.heading_bold)
    return _text_lines(text, size, Inches(width), bold=bold) * size * spacing / 72


# ---------------------------------------------------------------- text


def _font(heading):
    return base.HEADING_FONT if heading else base.BODY_FONT


def _whole_words(ctx, value, width, size, floor, bold):
    """The largest size up to `size` at which `value`'s longest word fits a line `width` (EMU) wide.

    The line counter wraps a word too long for its box letter by letter, as a
    viewer does, so a long Russian or Uzbek word in a narrow box was set broken
    in two. Below `floor` the slide is marked shortened instead, and the
    variant is passed over for it.
    """
    words = str(value or '').split()
    if not words:
        return size
    available = max(1, width / 12700) / (1.06 if bold else 1)
    longest = max(_units(word) for word in words)
    while size > floor and 0.001 * size * longest * base.WIDTH_SAFETY > available:
        size -= 0.5
    if 0.001 * size * longest * base.WIDTH_SAFETY > available:
        ctx.shortened = True
    return size


def text(ctx, box, value, *, size, colour='ink', floor=12, bold=False, heading=False, align='left', anchor='top',
         spacing=1.15, words=None, upper=False):
    """One field in `box`, shrunk to fit down to `floor`, then cut (and the slide marked).

    `words` is the field's word limit (the classic drawer's); `upper` sets it
    in capitals after clipping.
    """
    value = clip(ctx, value, words) if words else ' '.join(str(value or '').split())
    if not value:
        return None
    if upper:
        value = value.upper()
    floor = min(floor, size)
    size = _whole_words(ctx, value, Inches(box[2]), size, floor, bold or (heading and ctx.heading_bold))
    return fitted(ctx, Z(*box), value, size=size, colour=hex_of(ctx, colour), floor=floor, bold=bold,
                  font=_font(heading), align=ALIGN[align], spacing=spacing, anchor=ANCHOR[anchor])


def block(ctx, box, paragraphs, anchor='top'):
    """Several paragraphs in one box that shrink together: a card's tag, title and text.

    Each paragraph is a dict: text, size, and optionally floor (12, or the
    size if smaller), colour (role or hex), bold, heading (the heading face),
    words (its word limit), upper, align, before/after (points), spacing, and
    bullet/bullet_colour for a hanging glyph. Empty paragraphs are left out.
    """
    specs = []
    for paragraph in paragraphs:
        if not paragraph:
            continue
        value = paragraph.get('text')
        value = clip(ctx, value, paragraph['words']) if paragraph.get('words') else ' '.join(str(value or '').split())
        if not value:
            continue
        if paragraph.get('upper'):
            value = value.upper()
        floor = min(paragraph.get('floor', min(12, paragraph['size'])), paragraph['size'])
        width = Inches(box[2]) - (Pt(paragraph['size'] * 0.95) if paragraph.get('bullet') else 0)
        size = _whole_words(ctx, value, width, paragraph['size'], floor,
                            paragraph.get('bold', False) or (paragraph.get('heading') and ctx.heading_bold))
        spec = dict(text=value, size=size, floor=floor,
                    colour=hex_of(ctx, paragraph.get('colour', 'ink')), bold=paragraph.get('bold', False),
                    font=_font(paragraph.get('heading')), after=paragraph.get('after', 0),
                    before=paragraph.get('before', 0), spacing=paragraph.get('spacing', 1.15),
                    align=ALIGN[paragraph.get('align', 'left')])
        if paragraph.get('bullet'):
            spec['bullet'] = paragraph['bullet']
            spec['bullet_colour'] = hex_of(ctx, paragraph.get('bullet_colour', 'accent_text'))
        specs.append(spec)
    if not specs:
        return None
    return _put_paragraphs(ctx, Z(*box), specs, ANCHOR[anchor])


def fits(ctx, box, paragraphs):
    """Whether `paragraphs` (as for `block`) fit `box` at their sizes, without shrinking or cutting."""
    zone = Z(*box)
    specs = [dict(text=' '.join(str(p.get('text') or '').split()), size=p['size'],
                  bold=p.get('bold', False) or (p.get('heading') and ctx.heading_bold),
                  before=p.get('before', 0), after=p.get('after', 0), spacing=p.get('spacing', 1.15))
             for p in paragraphs if p and str(p.get('text') or '').strip()]
    return sum(_paragraph_height(spec, zone) for spec in specs) <= zone.height / 12700 - 3


def figure(ctx, box, value, *, size, colour='accent_text', floor=None, words=3, align='left', anchor='top',
           heading=True, bold=False):
    """A figure (118%, 4 200, Q3) on one line: as large as `size`, smaller until it is one line."""
    value = clip(ctx, value, words)
    if not value:
        return None
    zone = Z(*box)
    points = size
    floor = floor or max(12, size // 2)
    while points > floor and _text_lines(value, points, zone.width, bold=bold or (heading and ctx.heading_bold)) > 1:
        points -= 2
    return fitted(ctx, zone, value, size=points, colour=hex_of(ctx, colour), floor=min(floor, points), bold=bold,
                  font=_font(heading), align=ALIGN[align], spacing=1.1, anchor=ANCHOR[anchor])


def badge(ctx, box, value, *, fill='accent', ink='on_accent', shape='oval', size=18, bold=True, heading=False,
          line=None):
    """A number or short figure on its own shape: 'oval', 'rounded', 'rect', 'hexagon', 'diamond' or 'ring'.

    The text box is the shape's inscribed box, so every point under it is the fill.
    """
    if shape == 'oval':
        oval(ctx, box, fill, **({'line': line} if line else {}))
        inner = inscribed(box)
    elif shape == 'ring':
        ring(ctx, box, line or fill)
        inner = inscribed(box, 0.62)
    elif shape == 'rounded':
        rounded(ctx, box, fill, radius=min(box[2], box[3]) * 0.22)
        inner = inscribed(box, 0.84)
    elif shape == 'rect':
        rect(ctx, box, fill)
        inner = inscribed(box, 0.9)
    elif shape == 'hexagon':
        polygon(ctx, hexagon_points(box), fill)
        inner = inscribed(box, 0.62)
    elif shape == 'diamond':
        polygon(ctx, diamond_points(box), fill)
        inner = inscribed(box, 0.48)
    else:
        raise ValueError(shape)
    value = ' '.join(str(value or '').split())
    if value:
        zone = Z(*inner)
        points = size
        while points > 9 and _text_lines(value, points, zone.width, bold=bold) > 1:
            points -= 1
        fitted(ctx, zone, value, size=points, colour=hex_of(ctx, ink), floor=min(9, points), bold=bold,
               font=_font(heading), align=ALIGN['center'], spacing=1.0, anchor=ANCHOR['middle'])
    return inner


def _list_fits(lines, size, zone, gap, hang):
    total = 0
    for index, value in enumerate(lines):
        rows = _text_lines(value, size, zone.width - (Pt(size * 0.95) if hang else 0))
        total += rows * size * base.LINE_MULTIPLE + (0 if index == 0 else size * gap)
    return total <= zone.height / 12700 - 2


def bullets(ctx, box, lines, *, colour='ink', marker='accent_text', glyph='•', gap=0.55, size=None):
    """A list at the deck's body size if it fits, a little smaller if not, cut only at the floor.

    `glyph` None sets the lines without markers (a variant that numbers them
    itself). Returns (lines kept, size). A list more than `SQUEEZE` points
    below the deck's own size marks the slide `squeezed` — whatever `size`
    it started from — and the variant is then passed over rather than set the
    slide in smaller type than its neighbours.
    """
    zone = Z(*box)
    lines = [' '.join(str(value).split()) for value in lines if str(value).strip()]
    size = size or ctx.size
    while size > base.FLOOR_BODY_SIZE and not _list_fits(lines, size, zone, gap, bool(glyph)):
        size -= 0.5
    while lines and not _list_fits(lines, size, zone, gap, bool(glyph)):
        longest = max(range(len(lines)), key=lambda index: len(lines[index]))
        words = lines[longest].rstrip('…').split()
        if len(words) > 6:
            lines[longest] = ' '.join(words[:-2]).rstrip(',;:.') + '…'
        else:
            lines.pop(longest)
        ctx.shortened = True
    if size < ctx.size - SQUEEZE:
        ctx.squeezed = True
    frame = base._frame(ctx.slide.shapes.add_textbox(*zone.box()))
    for index, value in enumerate(lines):
        paragraph = base._write(base._paragraph(frame, index), value, font=base.BODY_FONT, size=size,
                                colour=hex_of(ctx, colour), spacing=base.LINE_MULTIPLE,
                                before=0 if index == 0 else size * gap)
        paragraph.line_spacing = Pt(size * base.LINE_MULTIPLE)
        if glyph:
            base._bullet(paragraph, hex_of(ctx, marker), size, glyph)
        else:
            base._no_bullet(paragraph)
    return lines, size


def list_size(ctx, box, lines, *, gap=0.55, glyph=True):
    """The size `bullets` would set `lines` at in `box` (no drawing), or None if they would be cut."""
    zone = Z(*box)
    lines = [' '.join(str(value).split()) for value in lines if str(value).strip()]
    size = ctx.size
    while size > base.FLOOR_BODY_SIZE and not _list_fits(lines, size, zone, gap, glyph):
        size -= 0.5
    return size if _list_fits(lines, size, zone, gap, glyph) else None


# ---------------------------------------------------------------- headers


def eyebrow(ctx, box=None, *, colour='muted', align='left'):
    """The slide's '03 / 12' marker."""
    box = box or (LEFT, 0.62, 3.2, 0.3)
    put(ctx, Z(*box), f'{ctx.index + 1:02d} / {ctx.total:02d}', size=10, colour=hex_of(ctx, colour), bold=True,
        align=ALIGN[align])


def headline(ctx, section, box, *, size=32, lines=2, anchor='bottom', align='left', colour=None, words=14):
    """The slide's heading in `box`, shrunk to `lines` lines (to 18 pt), then cut and the slide marked."""
    value = clip(ctx, section['heading'], words)
    size = _whole_words(ctx, value, Inches(box[2]), size, min(18, size), bool(ctx.heading_bold))
    fit_headline(ctx, Z(*box), value, size=size,
                 colour=hex_of(ctx, colour) if colour else None, anchor=ANCHOR[anchor], lines=lines,
                 align=ALIGN[align])


def rule(ctx, box=None, colour='accent'):
    """The short accent rule under (or over) a heading."""
    return rect(ctx, box or (LEFT, 2.38, 1.1, RULE), colour)


def header(ctx, section, *, width=WIDTH, size=32):
    """The classic top: eyebrow, heading to 2.25 in and the rule. Returns where the body starts (2.75)."""
    classic_header(ctx, section, width=width, size=size)
    return TOP


def header_compact(ctx, section, *, size=28):
    """A shorter top that gives the body half an inch more. Returns where the body starts (2.2)."""
    eyebrow(ctx)
    # The rule stands clear of the heading's descenders, as the classic one does.
    headline(ctx, section, (LEFT, 0.9, WIDTH, 0.96), size=size, lines=2)
    rule(ctx, (LEFT, 2.0, 0.9, RULE))
    return 2.2


def header_center(ctx, section, *, size=32):
    """Eyebrow, heading and rule centred. Returns where the body starts (2.75)."""
    eyebrow(ctx, (LEFT, 0.62, WIDTH, 0.3), align='center')
    headline(ctx, section, (LEFT + 0.8, 1.0, WIDTH - 1.6, 1.25), size=size, align='center')
    # Lower and shorter than the classic rule: centred close under one line, it read as an underline.
    rule(ctx, (LEFT + WIDTH / 2 - 0.45, 2.46, 0.9, RULE))
    return TOP


def header_side(ctx, section, *, width=3.7, size=30, lines=5):
    """The heading in a column down the left. Returns the x where the body starts beside it."""
    eyebrow(ctx, (LEFT, 0.62, width, 0.3))
    rule(ctx, (LEFT, 1.02, 0.9, RULE))
    headline(ctx, section, (LEFT, 1.25, width, 3.4), size=size, lines=lines, anchor='top')
    return LEFT + width + 0.5


def header_band(ctx, section, *, fill='deep', height=1.7, size=30):
    """The heading on a filled band across the top of the frame. Returns where the body starts."""
    colours = inks(fill)
    rect(ctx, (LEFT, 0.62, WIDTH, height), fill)
    eyebrow(ctx, (LEFT + 0.4, 0.78, 3.0, 0.3), colour=colours['muted'])
    headline(ctx, section, (LEFT + 0.4, 1.08, WIDTH - 0.8, height - 0.6), size=size, lines=2, anchor='middle',
             colour=colours['ink'])
    return 0.62 + height + 0.3


def header_number(ctx, section, *, size=30):
    """The slide's number large in the accent, the heading beside it. Returns where the body starts (2.75)."""
    figure(ctx, (LEFT, 0.85, 1.6, 1.4), f'{ctx.index + 1:02d}', size=66, colour='accent_text', anchor='middle')
    # The divider is the soft tint where it shows; on a dark deck the tint is nearly the ground.
    rect(ctx, (LEFT + 1.75, 1.0, 0.04, 1.25), readable(ctx, 'accent_soft', 'surface', 1.8))
    headline(ctx, section, (LEFT + 2.05, 1.0, WIDTH - 2.05, 1.25), size=size, lines=2, anchor='middle')
    return TOP


# ---------------------------------------------------------------- content, as the classic drawers read it


def entries(kind, section):
    """The items a layout draws, exactly as its classic drawer takes them."""
    items = items_of(section)
    if kind in ('agenda', 'cards'):
        return [item for item in items if item.get('label')][:6]
    if kind == 'process':
        return [item for item in items if item.get('label')][:5]
    if kind == 'matrix':
        return [item for item in items if item.get('label')][:4]
    if kind == 'timeline':
        return items[:6]
    return items


def sides(ctx, section):
    """A pros_cons slide's two sides: [(points, name), (points, name)], for first."""
    names = columns_of(section)
    pros = [item for item in items_of(section) if item.get('value', '').strip().lower() in PRO]
    cons = [item for item in items_of(section) if item.get('value', '').strip().lower() not in PRO]
    return [(pros, names[0] if len(names) > 0 else LABELS['pros'][ctx.locale]),
            (cons, names[1] if len(names) > 1 else LABELS['cons'][ctx.locale])]


def point_text(item):
    """What a pros_cons point says: its label, or its text when it has none."""
    return item.get('label') or item.get('text') or ''


def attribution(ctx, section):
    """A quote's '— Name, role', with the classic word limits."""
    who = items_of(section)[0]
    return '— ' + ', '.join(part for part in (clip(ctx, who.get('label'), 8), clip(ctx, who.get('text'), 12))
                            if part)


def numbers(items):
    """Each item's value as a number (0 when it has none)."""
    return [parse_number(item.get('value')) or 0 for item in items]


def vs(ctx):
    return LABELS['vs'][ctx.locale]
