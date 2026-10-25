"""Stats variants: each figure on a shape or line of its own — rows, tiles, underlines, hexagons, cards, pills."""
from pptx.util import Inches

from . import variant
from ..slide_layouts import _paragraph_height, _text_lines
from ..slides import contrast_ratio
from .kit import (FOOT, LEFT, RIGHT, RULE, WIDTH, Z, block, entries, eyebrow, figure, header, header_band,
                  header_center, header_compact, header_side, headline, hex_of, hexagon_points, inks, line, polygon,
                  rect, rounded, split, strong)

TOP_EDGE = 0.62
# The stats guide's range (layouts.fits holds a stats slide to 2-4 figures); every variant is drawn for all of it.
COUNTS = (2, 4)
# (label, text) sizes, largest first: a slide's stats all take the first pair every one of them holds.
LADDER = ((20, 16), (19, 15), (18, 14), (17, 13), (16, 12), (15, 12))


# ---------------------------------------------------------------- measuring


def _plain(value, words=None):
    parts = str(value or '').split()
    return ' '.join(parts[:words] if words else parts)


def _bold(ctx, paragraph):
    return bool(paragraph.get('bold')) or bool(paragraph.get('heading') and ctx.heading_bold)


def _need(ctx, width, paragraphs):
    """Inches `paragraphs` (as for kit.block) take in a box `width` wide, measured as block measures them."""
    zone = Z(0, 0, width, 10)
    total = 0.0
    for paragraph in paragraphs:
        value = _plain(paragraph.get('text'), paragraph.get('words'))
        if not value:
            continue
        total += _paragraph_height(dict(text=value, size=paragraph['size'], bold=_bold(ctx, paragraph),
                                        before=paragraph.get('before', 0), after=paragraph.get('after', 0),
                                        spacing=paragraph.get('spacing', 1.15)), zone)
    return (total + 3) / 72


def _whole(ctx, width, paragraphs):
    """Whether every word of `paragraphs` keeps to one line of `width` (no word broken across lines)."""
    for paragraph in paragraphs:
        for word in _plain(paragraph.get('text'), paragraph.get('words')).split():
            if _text_lines(word, paragraph['size'], Inches(width), bold=_bold(ctx, paragraph)) > 1:
                return False
    return True


def _settle(ctx, stats, make, width, height, ladder=LADDER):
    """The first sizes in `ladder` at which every stat's paragraphs fit `width` x `height` whole."""
    for sizes in ladder:
        if all(_need(ctx, width, make(item, *sizes)) <= height and _whole(ctx, width, make(item, *sizes))
               for item in stats):
            return sizes
    return ladder[-1]


def _tallest(ctx, stats, make, width, sizes):
    return max(_need(ctx, width, make(item, *sizes)) for item in stats)


def _figure_size(ctx, stats, width, size, floor=28):
    """The largest size up to `size` at which every figure keeps to one line of `width`: one size for the slide."""
    values = [_plain(item.get('value'), 3) for item in stats if _plain(item.get('value'))]
    while size > floor and any(_text_lines(value, size, Inches(width), bold=ctx.heading_bold) > 1
                               for value in values):
        size -= 2
    return size


def _figure_height(size):
    """The height of a one-line figure box at `size` (figure sets it at 1.1 leading)."""
    return size * 1.1 / 72 + 0.08


def _words(item, label, body, *, ink='ink', muted='muted', align='left', gap=5):
    """A stat's label and sentence, at the classic word limits (8 and 20)."""
    paragraphs = [dict(text=item.get('label'), words=8, size=label, floor=min(label, 15), colour=ink, bold=True,
                       heading=True, after=gap, align=align)]
    if _plain(item.get('text')):
        paragraphs.append(dict(text=item.get('text'), words=20, size=body, floor=min(body, 12), colour=muted,
                               align=align))
    return paragraphs


def _second(ctx):
    """A strong fill to alternate with the accent that does not look like it.

    The deep panel, unless it is the accent's near twin — a navy or plum accent
    on a light deck, where deep is the same colour a shade darker and the
    alternation reads as a mistake — or is lost on a dark ground; then the
    design's second colour, if it shows on the slide and is a colour of its own.
    """
    surface, accent = hex_of(ctx, 'surface'), hex_of(ctx, 'accent')

    def shows(role):
        return contrast_ratio(hex_of(ctx, role), surface) >= 1.8

    if shows('deep') and contrast_ratio(hex_of(ctx, 'deep'), accent) >= 2.0:
        return 'deep'
    secondary = hex_of(ctx, 'secondary')
    if secondary != hex_of(ctx, 'accent_soft') and shows('secondary') and _apart(secondary, accent) >= 120:
        return 'secondary'
    chosen = strong(ctx)
    return strong(ctx, ('deep', 'secondary')) if chosen == 'accent' else chosen


def _apart(one, other):
    """How far apart two hex colours are (RGB distance, 0-441): hue counts, not only lightness."""
    return sum((int(one[i:i + 2], 16) - int(other[i:i + 2], 16)) ** 2 for i in (0, 2, 4)) ** 0.5


# ---------------------------------------------------------------- variants


@variant('stats', 'rows', counts=COUNTS)
def rows(ctx, section, lines):
    """The stats stacked as rows like a ledger: each figure large in the accent at the left, a short accent bar,
    the label and then the sentence in columns of their own; hairlines between the rows."""
    top = header(ctx, section)
    stats = entries('stats', section)
    n = len(stats)
    fig_w = 2.75
    bar_x = LEFT + fig_w + 0.2
    lx = bar_x + 0.36
    lw = 3.0
    tx = lx + lw + 0.4
    tw = RIGHT - tx
    room = FOOT - top
    pad = 0.12 if n >= 4 else 0.2
    pitch = room / n

    def label(item, size):
        return [dict(text=item.get('label'), words=8, size=size, floor=min(size, 15), colour='ink', bold=True,
                     heading=True)]

    def sentence(item, size):
        return [dict(text=item.get('text'), words=20, size=size, floor=min(size, 12), colour='muted')]
    # The label and the sentence sit side by side, so each only has to fit the row's height in its own column.
    sizes = LADDER[-1]
    for pair in LADDER:
        if all(_need(ctx, lw, label(item, pair[0])) <= pitch - 2 * pad and _whole(ctx, lw, label(item, pair[0]))
               and _need(ctx, tw, sentence(item, pair[1])) <= pitch - 2 * pad for item in stats):
            sizes = pair
            break
    need = max(max(_need(ctx, lw, label(item, sizes[0])), _need(ctx, tw, sentence(item, sizes[1])))
               for item in stats)
    size = _figure_size(ctx, stats, fig_w, 56 if n <= 3 else 50)
    row = min(pitch, max(need, _figure_height(size)) + 2 * pad + (0.3 if n <= 3 else 0.1))
    start = top + max(0.0, (room - row * n) / 2) * 0.8
    for k, item in enumerate(stats):
        y = start + k * row
        if k:
            line(ctx, (LEFT, y), (RIGHT, y), 'accent_soft', 1.0)
        figure(ctx, (LEFT, y + pad / 2, fig_w, row - pad), item.get('value'), size=size, colour='accent_text',
               anchor='middle', floor=size)
        bar = min(row - 2 * pad, 0.8)
        rect(ctx, (bar_x, y + (row - bar) / 2, 0.06, bar), 'accent')
        block(ctx, (lx, y + pad / 2, lw, row - pad), label(item, sizes[0]), anchor='middle')
        if _plain(item.get('text')):
            block(ctx, (tx, y + pad / 2, tw, row - pad), sentence(item, sizes[1]), anchor='middle')


@variant('stats', 'side_grid', counts=COUNTS)
def side_grid(ctx, section, lines):
    """The heading in a column down the left; the stats as tiles in a grid beside it — two tall posters for two, a
    tall lead tile with the larger figure for three, two by two for four — the lead tiles in a strong fill."""
    x0 = header_side(ctx, section, width=3.0, size=28) - 0.1
    stats = entries('stats', section)
    n = len(stats)
    gap = 0.18
    area_w, area_h = RIGHT - x0, FOOT - TOP_EDGE
    cw = (area_w - gap) / 2
    rh = (area_h - gap) / 2
    if n >= 4:
        boxes = [(x0 + (k % 2) * (cw + gap), TOP_EDGE + (k // 2) * (rh + gap), cw, rh) for k in range(4)]
        lead = (0, 3)
    elif n == 3:
        boxes = [(x0, TOP_EDGE, cw, area_h), (x0 + cw + gap, TOP_EDGE, cw, rh),
                 (x0 + cw + gap, TOP_EDGE + rh + gap, cw, rh)]
        lead = (0,)
    else:
        boxes = [(x0 + k * (cw + gap), TOP_EDGE, cw, area_h) for k in range(n)]
        lead = (0,)
    # The mark, the figure under it, and the words at the tile's foot.
    pad, mark_gap, words_gap = 0.24, 0.08, 0.1
    inner = cw - 2 * pad
    size = _figure_size(ctx, stats, inner, 72 if n == 2 else 44)
    # Three: the tall lead tile is the slide's hero, its figure as large as two tiles' figures get.
    figures = [_figure_size(ctx, stats[:1], inner, 72) if n == 3 and k == 0 else size for k in range(n)]
    # Every tile holds its words below its figure; the tightest tile sets the room.
    room = min(h - 2 * pad - mark_gap - _figure_height(points) - words_gap
               for (_, _, _, h), points in zip(boxes, figures))

    def make(item, label, body, ink='card_ink', muted='card_muted'):
        return _words(item, label, body, ink=ink, muted=muted)
    sizes = _settle(ctx, stats, make, inner, room)
    panel = inks(strong(ctx))
    for k, (item, (x, y, w, h)) in enumerate(zip(stats, boxes)):
        colours = panel if k in lead else inks('card')
        rect(ctx, (x, y, w, h), colours['fill'])
        mark = colours['ink'] if k in lead else 'accent'
        rect(ctx, (x + pad, y + pad, 0.55, RULE), mark)
        fig_h = _figure_height(figures[k])
        figure(ctx, (x + pad, y + pad + mark_gap, inner, fig_h), item.get('value'), size=figures[k],
               colour=colours['ink'] if k in lead else colours['accent'], floor=figures[k])
        words_top = y + pad + mark_gap + fig_h + words_gap
        block(ctx, (x + pad, words_top, inner, y + h - pad - words_top),
              make(item, *sizes, ink=colours['ink'], muted=colours['muted']), anchor='bottom')


@variant('stats', 'underlined', counts=COUNTS)
def underlined(ctx, section, lines):
    """Centred columns: each figure large over a long accent underline, its label and sentence centred beneath."""
    top = header_center(ctx, section)
    stats = entries('stats', section)
    n = len(stats)
    gap = 0.55 if n <= 3 else 0.42
    spans = split(LEFT, WIDTH, n, gap)
    width = spans[0][1]
    words_w = min(width, 4.2)
    size = _figure_size(ctx, stats, width, 64 if n <= 3 else 56)
    fig_h = _figure_height(size)
    under = 0.12 + 0.07 + 0.26

    def make(item, label, body):
        return _words(item, label, body, align='center')
    room = FOOT - top - fig_h - under
    sizes = _settle(ctx, stats, make, words_w, room)
    need = _tallest(ctx, stats, make, words_w, sizes)
    group = fig_h + under + need
    y0 = top + max(0.0, (FOOT - top - group) / 2) * 0.7
    for item, (x, w) in zip(stats, spans):
        cx = x + w / 2
        figure(ctx, (x, y0, w, fig_h), item.get('value'), size=size, colour='accent_text', align='center',
               anchor='bottom', floor=size)
        length = min(w * 0.72, 3.0)
        rect(ctx, (cx - length / 2, y0 + fig_h + 0.12, length, 0.07), 'accent')
        block(ctx, (cx - words_w / 2, y0 + fig_h + under, words_w, FOOT - y0 - fig_h - under),
              make(item, *sizes))


def _hexagon_text(box):
    """The widest box that lies inside the flat-topped hexagon drawn at `box`.

    kit.inscribed's square share is the disc's; a flat hexagon is wide, so a
    box of 72% of its width and 48% of its height still clears the slanted
    sides (a share of width w may take 1 - h/2 of the height).
    """
    x, y, w, h = box
    return (x + w * 0.14, y + h * 0.26, w * 0.72, h * 0.48)


@variant('stats', 'hexagons', counts=COUNTS)
def hexagons(ctx, section, lines):
    """Each figure inside a large hexagon, the accent and a strong second colour in turn, over a pale offset
    hexagon; label and sentence centred below."""
    top = header_compact(ctx, section) + 0.15
    stats = entries('stats', section)
    n = len(stats)
    gap = 0.6 if n <= 3 else 0.4
    spans = split(LEFT, WIDTH, n, gap)
    width = spans[0][1]
    hex_w = min(2.5, width * 0.8)
    hex_h = hex_w * 0.866
    words_w = min(width, 4.0)
    under = 0.28
    size = _figure_size(ctx, stats, hex_w * 0.72, 48)

    def make(item, label, body):
        return _words(item, label, body, align='center')
    room = FOOT - top - hex_h - under
    sizes = _settle(ctx, stats, make, words_w, room)
    need = _tallest(ctx, stats, make, words_w, sizes)
    group = hex_h + under + need
    y0 = top + max(0.0, (FOOT - top - group) / 2) * 0.7
    fills = ('accent', _second(ctx))
    shift = 0.13
    for k, (item, (x, w)) in enumerate(zip(stats, spans)):
        cx = x + w / 2
        box = (cx - hex_w / 2, y0, hex_w, hex_h)
        polygon(ctx, hexagon_points((box[0] + shift, box[1] + shift * 0.6, hex_w, hex_h)), 'accent_soft')
        fill = fills[k % 2]
        polygon(ctx, hexagon_points(box), fill)
        figure(ctx, _hexagon_text(box), item.get('value'), size=size, colour=inks(fill)['ink'], align='center',
               anchor='middle', floor=size)
        block(ctx, (cx - words_w / 2, y0 + hex_h + under, words_w, FOOT - y0 - hex_h - under), make(item, *sizes))


@variant('stats', 'split_cards', counts=COUNTS)
def split_cards(ctx, section, lines):
    """Each stat a card in two parts: an accent top holding the figure, a pointer into the card below that holds
    its label and sentence."""
    pad = 0.26
    eyebrow(ctx)
    rect(ctx, (LEFT, 0.98, 0.08, 0.98), 'accent')
    # The heading starts where the cards' words do.
    headline(ctx, section, (LEFT + pad, 0.95, WIDTH - pad, 1.04), size=30, lines=2, anchor='middle')
    top = 2.3
    stats = entries('stats', section)
    n = len(stats)
    gap = 0.26 if n >= 4 else 0.4
    spans = split(LEFT, WIDTH, n, gap)
    width = spans[0][1]
    inner = width - 2 * pad
    size = _figure_size(ctx, stats, inner, 52 if n <= 3 else 44)
    rise = 0.2                       # above and below the figure, in the accent top
    head = _figure_height(size) + 2 * rise
    under = 0.28                     # the accent top to the words (the pointer sits in it), and the words to the foot

    def make(item, label, body):
        return _words(item, label, body, ink='card_ink', muted='card_muted')
    room = FOOT - top - head - 2 * under
    sizes = _settle(ctx, stats, make, inner, room)
    need = _tallest(ctx, stats, make, inner, sizes)
    tall = min(FOOT - top, head + need + 2 * under)
    y0 = top + (FOOT - top - tall) / 2 * 0.6
    for item, (x, w) in zip(stats, spans):
        rect(ctx, (x, y0, w, tall), 'card')
        rect(ctx, (x, y0, w, head), 'accent')
        polygon(ctx, [(x + pad, y0 + head), (x + pad + 0.34, y0 + head), (x + pad + 0.17, y0 + head + 0.16)],
                'accent')
        figure(ctx, (x + pad, y0 + rise, inner, head - 2 * rise), item.get('value'), size=size, colour='on_accent',
               anchor='middle', floor=size)
        block(ctx, (x + pad, y0 + head + under, inner, tall - head - 2 * under), make(item, *sizes))


def _pill_text(box):
    """The box inside a pill (radius half its height) clear of its round ends."""
    x, y, w, h = box
    radius = h / 2
    return (x + radius * 0.4, y + h * 0.18, w - radius * 0.8, h * 0.64)


@variant('stats', 'pill_values', counts=COUNTS)
def pill_values(ctx, section, lines):
    """The heading on a strong band; under it each figure in a big pale pill heading its column, the label and
    sentence beneath."""
    top = header_band(ctx, section, fill=strong(ctx), height=1.62)
    stats = entries('stats', section)
    n = len(stats)
    gap = 0.5 if n <= 3 else 0.38
    spans = split(LEFT, WIDTH, n, gap)
    width = spans[0][1]
    pill_h = 1.12
    pill_w = min(width, 3.6)
    size = _figure_size(ctx, stats, _pill_text((0, 0, pill_w, pill_h))[2], 44)
    size = min(size, int((pill_h * 0.64 - 3 / 72) * 72 / 1.1))
    words_w = min(width, 4.2)

    def make(item, label, body):
        return _words(item, label, body)
    room = FOOT - top - pill_h - 0.28
    sizes = _settle(ctx, stats, make, words_w, room)
    need = _tallest(ctx, stats, make, words_w, sizes)
    group = pill_h + 0.28 + need
    y0 = top + max(0.0, (FOOT - top - group) / 2) * 0.6
    for item, (x, w) in zip(stats, spans):
        box = (x, y0, pill_w, pill_h)
        rounded(ctx, box, 'accent_soft', radius=pill_h / 2)
        figure(ctx, _pill_text(box), item.get('value'), size=size, colour='soft_ink', align='center',
               anchor='middle', floor=size)
        block(ctx, (x, y0 + pill_h + 0.28, words_w, FOOT - y0 - pill_h - 0.28), make(item, *sizes))
