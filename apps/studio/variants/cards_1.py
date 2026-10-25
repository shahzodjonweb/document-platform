"""Cards variants: the same tagged items as discs, rings, a hub, colour tiles, tabbed rows, bars and numerals."""
from pptx.util import Inches

from ..slide_layouts import _paragraph_height, _text_lines
from ..slides import _text_width
from . import variant
from .kit import (FOOT, LEFT, RIGHT, RULE, WIDTH, Z, badge, block, clip, disc, entries, eyebrow, figure, header_band,
                  header_compact, header_number, header_side, headline, hex_of, hues, inks, line, on, oval, polygon,
                  readable, rect, ring, rounded, rule, split, strong, text, tones, triangle_points)

# (label, text) point sizes, largest first: a slide takes the first at which every item fits.
SCALES = ((19, 14), (18, 14), (18, 13), (17, 13), (16, 13), (16, 12), (15, 12))
TAG = 11


# ---------------------------------------------------------------- measuring


def _words(n):
    """The classic drawer's word limit for a card's sentence: 28 in a single row of three, else 25."""
    return 28 if n <= 3 else 25


def _clean(value, words=None):
    parts = str(value or '').split()
    return ' '.join(parts[:words] if words else parts)


def _need(ctx, width, paragraphs):
    """Inches `paragraphs` (as for kit.block) take in a box `width` wide, with block's own allowance."""
    zone = Z(0, 0, width, 1)
    total = 0.0
    for paragraph in paragraphs:
        if not paragraph:
            continue
        value = _clean(paragraph.get('text'), paragraph.get('words'))
        if not value:
            continue
        if paragraph.get('upper'):
            value = value.upper()
        bold = bool(paragraph.get('bold')) or bool(paragraph.get('heading') and ctx.heading_bold)
        total += _paragraph_height(dict(text=value, size=paragraph['size'], bold=bold,
                                        before=paragraph.get('before', 0), after=paragraph.get('after', 0),
                                        spacing=paragraph.get('spacing', 1.15), bullet=paragraph.get('bullet')),
                                   zone)
    return (total + 4) / 72 if total else 0.0


def _whole(ctx, width, paragraphs):
    """Whether every word of `paragraphs` (as for kit.block) keeps to one line of a box `width` wide.

    A viewer breaks a word wider than its box between letters; a long Russian
    or Uzbek word ('Информационная') in a narrow column would be split in two.
    """
    for paragraph in paragraphs:
        if not paragraph:
            continue
        value = _clean(paragraph.get('text'), paragraph.get('words'))
        if paragraph.get('upper'):
            value = value.upper()
        bold = bool(paragraph.get('bold')) or bool(paragraph.get('heading') and ctx.heading_bold)
        if any(_text_lines(word, paragraph['size'], Inches(width), bold=bold) > 1 for word in value.split()):
            return False
    return True


def _put(ctx, box, paragraphs, anchor='top'):
    """kit.block, the slide marked when a word would break across lines, so the variant is passed over."""
    if not _whole(ctx, box[2], paragraphs):
        ctx.shortened = True
    return block(ctx, box, paragraphs, anchor=anchor)


def _tagged(ctx, box, value, *, size=10.5, colour, align='right'):
    """A card's tag in small capitals in `box`, held to the classic three words; marked like `_put` if a word breaks."""
    if not _whole(ctx, box[2], [dict(text=value, words=3, upper=True, size=9, bold=True)]):
        ctx.shortened = True
    return text(ctx, box, value, size=size, floor=9, colour=colour, bold=True, align=align, words=3, upper=True)


def _scales(ctx, items, width, scales=SCALES):
    """`scales` with each label size lowered (to 14) until every label's longest word fits one line of `width`."""
    labels = [_label(item, 0)[0] for item in items]

    def whole(size):
        return _whole(ctx, width, [{**label, 'size': size} for label in labels])
    kept = []
    for label, body in scales:
        while label > 14 and not whole(label):
            label -= 1
        if (label, body) not in kept:
            kept.append((label, body))
    return tuple(kept)


def _choose(fits, scales=SCALES):
    """The first (label, text) sizes at which `fits(sizes)` holds; the smallest if none does."""
    for sizes in scales:
        if fits(sizes):
            return sizes
    return scales[-1]


def _heading_size(ctx, section, width, size):
    """The largest size up to `size` (to 18) at which the heading's longest word keeps to one line of `width`."""
    words = _clean(section.get('heading'), 14).split()
    while size > 18 and any(_text_lines(word, size, Inches(width), bold=ctx.heading_bold) > 1 for word in words):
        size -= 1
    return size


def _tag(item):
    return _clean(item.get('value'), 3).upper()


def _tag_width(value, size=TAG):
    """Inches a tag takes on one line, bold."""
    return _text_width(value, size) * 1.08 / 72


def _story(item, n, sizes, *, ink='ink', muted='muted', accent='accent_text', align='left', tag=True,
           spacing=1.15):
    """A card's tag (small capitals), label and sentence as kit.block paragraphs."""
    label, body = sizes
    paragraphs = []
    if tag and _tag(item):
        paragraphs.append(dict(text=item['value'], words=3, upper=True, size=TAG, floor=10, colour=accent,
                               bold=True, after=4, align=align))
    paragraphs.append(dict(text=item['label'], words=7, size=label, floor=min(label, 14), colour=ink, bold=True,
                           heading=True, spacing=1.1, after=5 if item.get('text') else 0, align=align))
    if item.get('text'):
        paragraphs.append(dict(text=item['text'], words=_words(n), size=body, floor=12, colour=muted,
                               align=align, spacing=spacing))
    return paragraphs


def _drop(items, k):
    """How far an untagged item's block starts below a tagged one's, so a row's labels line up."""
    if _tag(items[k]) or not any(_tag(item) for item in items):
        return 0.0
    return (TAG * 1.15 + 4) / 72


def _label(item, size, *, ink='ink', align='left'):
    return [dict(text=item['label'], words=7, size=size, floor=min(size, 14), colour=ink, bold=True, heading=True,
                 spacing=1.1, align=align)]


def _sentence(item, n, size, *, muted='muted', align='left', spacing=1.15):
    if not item.get('text'):
        return []
    return [dict(text=item['text'], words=_words(n), size=size, floor=12, colour=muted, align=align,
                 spacing=spacing)]


def _initial(label):
    for character in str(label or ''):
        if character.isalnum():
            return character.upper()
    return ''


def _top(ctx, section, *, align='left', size=26):
    """A short top: the eyebrow, a heading of up to two lines and the rule. Returns where the body starts (2.08)."""
    centre = align == 'center'
    inset = 1.0 if centre else 0.0
    eyebrow(ctx, (LEFT, 0.62, WIDTH, 0.3), align=align)
    headline(ctx, section, (LEFT + inset, 0.9, WIDTH - 2 * inset, 0.82), size=size, lines=2, align=align)
    rule(ctx, (LEFT + WIDTH / 2 - 0.5 if centre else LEFT, 1.88, 1.0 if centre else 0.9, RULE))
    return 2.08


def _chip(ctx, x, y, value, *, fill, ink, size=10, height=0.28, most=3.0):
    """A tag on a pill of its own, its left edge at x and no wider than `most`; returns its width."""
    value = clip(ctx, value, 3).upper()
    if not value:
        return 0.0
    width = min(most, _tag_width(value, size) + 0.3)
    rounded(ctx, (x, y, width, height), fill, radius=height / 2)
    if not _whole(ctx, width - 0.2, [dict(text=value, size=9, bold=True)]):
        ctx.shortened = True
    text(ctx, (x + 0.1, y + 0.03, width - 0.2, height - 0.06), value, size=size, floor=9, colour=ink, bold=True,
         align='center', anchor='middle')
    return width


def _centred(top, room, used, bias=0.42):
    """Where content `used` inches tall starts in `room` inches below `top`: a little above the middle."""
    return top + max(0.0, (room - used) * bias)


# ---------------------------------------------------------------- 1. numbered discs


@variant('cards', 'numbered_discs')
def numbered_discs(ctx, section, lines):
    """A haloed, numbered disc in its own colour over each item, the item centred beneath; no panels."""
    items = entries('cards', section)
    n = len(items)
    fills = hues(ctx, n)
    top = _top(ctx, section, align='center')
    if n > 4:
        _discs_grid(ctx, items, fills, top)
        return
    gap = 0.6 if n == 3 else 0.42
    inset = 0.35 if n == 3 else 0.0
    columns = split(LEFT + inset, WIDTH - 2 * inset, n, gap)
    width = columns[0][1]
    size = 1.0 if n <= 3 else 0.9
    halo = size + 0.3
    under = 0.24
    room = FOOT - top - 0.1 - halo - under

    def story(k, sizes):
        return _story(items[k], n, sizes, accent=fills[k]['text'], align='center')
    sizes = _choose(lambda s: all(_drop(items, k) + _need(ctx, width, story(k, s)) <= room for k in range(n)),
                    _scales(ctx, items, width))
    tallest = max(_drop(items, k) + _need(ctx, width, story(k, sizes)) for k in range(n))
    y = _centred(top + 0.1, room, tallest)
    for k, (x, w) in enumerate(columns):
        cx, cy = x + w / 2, y + halo / 2
        ring(ctx, disc(cx, cy, halo), fills[k]['fill'], width=1.25)
        badge(ctx, disc(cx, cy, size), f'{k + 1:02d}', fill=fills[k]['fill'], ink=fills[k]['ink'], size=24,
              heading=True)
        start = y + halo + under + _drop(items, k)
        _put(ctx, (x, start, w, FOOT - start), story(k, sizes))


def _discs_grid(ctx, items, fills, top):
    """Five or six items: two rows of three, each disc beside its tag and label, the sentence below."""
    n = len(items)
    gap, row_gap, size, under = 0.45, 0.34, 0.66, 0.14
    width = (WIDTH - 2 * gap) / 3
    lead = width - size - 0.2
    rows = [list(range(0, 3)), list(range(3, n))]

    def head(k, sizes):
        paragraphs = _story(items[k], n, sizes, accent=fills[k]['text'])
        return paragraphs[:-1] if items[k].get('text') else paragraphs

    level = [True]

    def drop(k):
        """An untagged item sits a tag lower than a tagged one in its row, so the row's labels line up."""
        row = next(row for row in rows if k in row)
        return _drop([items[k]] + [items[j] for j in row if j != k], 0) if level[0] else 0.0

    def shape(sizes):
        """Each row's (lead height, sentence height)."""
        return [(max(max(size, drop(k) + _need(ctx, lead, head(k, sizes))) for k in row),
                 max(_need(ctx, width, _sentence(items[k], n, sizes[1])) for k in row)) for row in rows]

    def used(heights):
        return sum(leads + under + body for leads, body in heights) + row_gap
    room = FOOT - top - 0.05
    scales = _scales(ctx, items, lead, SCALES[2:])
    sizes = _choose(lambda s: used(shape(s)) <= room, scales)
    if used(shape(sizes)) > room:
        # Levelled labels cost a tag's height in a row whose untagged label runs longer; when the
        # slide cannot spare it, each item's tag and label are centred on its disc instead.
        level[0] = False
        sizes = _choose(lambda s: used(shape(s)) <= room, scales)
    heights = shape(sizes)
    if used(heights) > room:  # it cannot hold this slide: cut (and be passed over) rather than overrun
        spare = (room - row_gap - sum(leads + under for leads, _ in heights)) / max(0.01, sum(b for _, b in heights))
        heights = [(leads, body * max(0.0, spare)) for leads, body in heights]
    y = _centred(top + 0.05, room, used(heights))
    for row, (leads, body) in zip(rows, heights):
        # The row's tags and labels are one block high, centred on the discs; each label starts level.
        heads = max(drop(k) + _need(ctx, lead, head(k, sizes)) for k in row)
        for column, k in enumerate(row):
            x = LEFT + (WIDTH - len(row) * width - (len(row) - 1) * gap) / 2 + column * (width + gap)
            badge(ctx, (x, y + (leads - size) / 2, size, size), f'{k + 1:02d}', fill=fills[k]['fill'],
                  ink=fills[k]['ink'], size=18, heading=True)
            own = heads if level[0] else _need(ctx, lead, head(k, sizes))
            start = y + max(0.0, leads - own) / 2 + drop(k)
            _put(ctx, (x + size + 0.2, start, lead, y + leads - start), head(k, sizes))
            _put(ctx, (x, y + leads + under, width, body), _sentence(items[k], n, sizes[1]))
        y += leads + under + body + row_gap


# ---------------------------------------------------------------- 2. ring tabs


@variant('cards', 'ring_tabs', counts=(3, 5))
def ring_tabs(ctx, section, lines):
    """An outlined ring holding each item's initial, a small filled number badge on its upper-right edge."""
    items = entries('cards', section)
    n = len(items)
    fills = hues(ctx, n)
    top = header_compact(ctx, section) if n <= 4 else _top(ctx, section)
    gap = {3: 0.6, 4: 0.45}.get(n, 0.34)
    columns = split(LEFT, WIDTH, n, gap)
    width = columns[0][1]
    size = {3: 1.15, 4: 1.0}.get(n, 0.8)
    knob = 0.42 if n <= 4 else 0.36
    lift, under = 0.14, (0.3 if n <= 4 else 0.22)
    room = FOOT - top - lift - size - under

    def story(k, sizes):
        return _story(items[k], n, sizes, accent=fills[k]['text'])
    sizes = _choose(lambda s: all(_drop(items, k) + _need(ctx, width, story(k, s)) <= room for k in range(n)),
                    _scales(ctx, items, width))
    tallest = max(_drop(items, k) + _need(ctx, width, story(k, sizes)) for k in range(n))
    y = _centred(top + lift, room, tallest)
    letter = _letter_box(size, knob)
    for k, (x, w) in enumerate(columns):
        cx, cy = x + size / 2, y + size / 2
        # The outline in the colour made to read on the slide: a pale hue's own line all but vanishes there.
        ring(ctx, (x, y, size, size), fills[k]['text'], width=2.25)
        initial = _initial(items[k]['label'])
        if initial:
            a, b, d = letter
            text(ctx, (cx - a, cy + d - b, 2 * a, 2 * b), initial, size=min(32, int(2 * b * 72 / 1.2)),
                 floor=12, colour=fills[k]['text'], bold=True, heading=True, align='center', anchor='middle',
                 spacing=1.0)
        badge(ctx, disc(cx + 0.3536 * size, cy - 0.3536 * size, knob), str(k + 1), fill=fills[k]['fill'],
              ink=fills[k]['ink'], size=13)
        start = y + size + under + _drop(items, k)
        _put(ctx, (x, start, w, FOOT - start), story(k, sizes))


def _letter_box(size, knob):
    """(half width, half height, drop) of the largest box in a ring of `size` that keeps off its shoulder badge.

    The box is set a little low in the ring; its corners stay inside the ring's line and clear of the badge
    (of diameter `knob`) whose centre sits on the ring at 45 degrees up and to the right.
    """
    radius, corner, clear = size / 2 - 0.07, 0.3536 * size, knob / 2 + 0.03
    best = (0.18 * size, 0.12 * size, 0.0)
    for step in range(40):
        b = size * (0.12 + step * 0.0035)
        a, d = 1.3 * b, 0.25 * b
        inside = (a * a + (d + b) ** 2) ** 0.5 <= radius
        apart = ((corner - a) ** 2 + (d - b + corner) ** 2) ** 0.5 >= clear or d - b >= -corner + clear
        if inside and apart:
            best = (a, b, d)
    return best


# ---------------------------------------------------------------- 3. hub


@variant('cards', 'hub', counts=(4, 6))
def hub(ctx, section, lines):
    """A strong central disc holding the number of items, the items in two columns facing it, each on a spoke."""
    items = entries('cards', section)
    n = len(items)
    top = _top(ctx, section, align='center')
    halo = 2.1 if n == 4 else 1.95
    core = halo - 0.36
    width = 4.25 if n > 4 else 4.15
    cx, cy = LEFT + WIDTH / 2, (top + FOOT) / 2
    left, right = items[:(n + 1) // 2], items[(n + 1) // 2:]
    per = len(left)
    slot_gap = 0.06 if per > 2 else 0.3
    slot = (FOOT - top - slot_gap * (per - 1)) / per

    def story(item, sizes, align):
        return _story(item, n, sizes, align=align, spacing=1.1)
    sizes = _choose(lambda s: all(_need(ctx, width, story(item, s, 'right')) <= slot for item in items),
                    _scales(ctx, items, width))
    tallest = max(_need(ctx, width, story(item, sizes, 'right')) for item in items)
    box = min(slot, tallest + 0.35)
    # Spokes, dots and halo in the accent made to read on the slide (a pale accent's own would barely show).
    ring(ctx, disc(cx, cy, halo), 'accent_text', width=1.25)
    panel = inks(strong(ctx))
    oval(ctx, disc(cx, cy, core), panel['fill'])
    figure(ctx, (cx - core * 0.36, cy - core * 0.3, core * 0.72, core * 0.6), str(n), size=60, colour=panel['ink'],
           align='center', anchor='middle')
    for side, group in ((0, left), (1, right)):
        x = LEFT if side == 0 else RIGHT - width
        for j, item in enumerate(group):
            middle = cy + (j - (len(group) - 1) / 2) * (box + slot_gap)
            _put(ctx, (x, middle - box / 2, width, box), story(item, sizes, 'right' if side == 0 else 'left'),
                 anchor='middle')
            start = (x + width + 0.14, middle) if side == 0 else (x - 0.14, middle)
            dx, dy = start[0] - cx, start[1] - cy
            length = (dx * dx + dy * dy) ** 0.5
            reach = halo / 2 + 0.08
            line(ctx, start, (cx + dx / length * reach, cy + dy / length * reach), 'accent_text', 1.25)
            oval(ctx, disc(start[0], start[1], 0.13), 'accent_text')


# ---------------------------------------------------------------- 4. colour tiles


@variant('cards', 'colour_tiles')
def colour_tiles(ctx, section, lines):
    """Each card a solid tile in its own colour: number and tag across the top, the label and sentence at its foot."""
    items = entries('cards', section)
    n = len(items)
    fills = hues(ctx, n)
    top = _top(ctx, section)
    if n > 4:
        _wide_tiles(ctx, items, fills, top)
        return
    top += 0.05
    gap, pad = (0.24, 0.28) if n == 3 else (0.2, 0.24)
    columns = split(LEFT, WIDTH, n, gap)
    width = columns[0][1]
    height = FOOT - top
    head = 0.62
    room = height - 2 * pad - head - 0.15

    def story(k, sizes):
        return _story(items[k], n, sizes, ink=fills[k]['ink'], muted=fills[k]['ink'], tag=False)
    sizes = _choose(lambda s: all(_need(ctx, width - 2 * pad, story(k, s)) <= room for k in range(n)),
                    _scales(ctx, items, width - 2 * pad))
    for k, (x, w) in enumerate(columns):
        paint = fills[k]
        rect(ctx, (x, top, w, height), paint['fill'])
        text(ctx, (x + pad, top + pad - 0.04, 0.9, head), f'{k + 1:02d}', size=30, colour=paint['ink'], bold=True,
             heading=True, spacing=1.0)
        if _tag(items[k]):
            _tagged(ctx, (x + pad + 0.95, top + pad + 0.04, w - 2 * pad - 0.95, head - 0.04), items[k]['value'],
                    colour=paint['ink'])
        rule(ctx, (x + pad, top + pad + head, 0.5, RULE), paint['ink'])
        start = top + pad + head + 0.15
        _put(ctx, (x + pad, start, w - 2 * pad, top + height - pad - start), story(k, sizes), anchor='bottom')


def _wide_tiles(ctx, items, fills, top):
    """Five or six tiles: two columns of wide tiles, the tag at the label's right.

    A fifth tile spans both columns as a feature row: its label in the left
    column's place and its sentence under the right column, so no line of it
    runs the full width of the slide.
    """
    n = len(items)
    gap, pad, inset, between = 0.14, 0.24, 0.15, 0.03
    height = (FOOT - top - gap * 2) / 3
    width = (WIDTH - gap) / 2
    span = n - 1 if n % 2 else None
    boxes = []
    for k in range(n):
        row, column = divmod(k, 2)
        boxes.append((LEFT + column * (width + gap), top + row * (height + gap), width, height))
    inner = width - 2 * pad
    reserve = [(_tag_width(_tag(item), 10.5) + 0.2) if _tag(item) else 0.0 for item in items]

    def parts(k, sizes):
        return (_need(ctx, inner - reserve[k], _label(items[k], sizes[0])),
                _need(ctx, inner, _sentence(items[k], n, sizes[1], spacing=1.1)))

    def holds(k, sizes):
        label, words = parts(k, sizes)
        return (max(label, words) if k == span else label + between + words) <= height - 2 * inset
    narrowest = inner - max(reserve)
    sizes = _choose(lambda s: all(holds(k, s) for k in range(n)), _scales(ctx, items, narrowest, SCALES[3:]))
    rows = [k for k in range(n) if k != span]
    labels = max(parts(k, sizes)[0] for k in rows)
    words = max(parts(k, sizes)[1] for k in rows)
    y_off = max(0.0, (height - 2 * inset - labels - between - words) / 2)
    for k, (item, (x, y, w, h)) in enumerate(zip(items, boxes)):
        paint = fills[k]
        sentence = _sentence(item, n, sizes[1], muted=paint['ink'], spacing=1.1)
        if k == span:
            rect(ctx, (x, y, WIDTH, h), paint['fill'])
            label, said = parts(k, sizes)
            # Label and sentence each centred in one band, the band centred in the tile, like a row.
            band = max(label, said)
            first = y + inset + max(0.0, (h - 2 * inset - band) / 2)
            _put(ctx, (x + pad, first, inner - reserve[k], band), _label(item, sizes[0], ink=paint['ink']),
                 anchor='middle')
            if said:
                _put(ctx, (x + width + gap + pad, first, inner, band), sentence, anchor='middle')
            first += max(0.0, band - label) / 2  # the tag beside the label's first line
        else:
            rect(ctx, (x, y, w, h), paint['fill'])
            first = y + inset + y_off
            _put(ctx, (x + pad, first, inner - reserve[k], labels), _label(item, sizes[0], ink=paint['ink']))
            start = first + labels + between
            _put(ctx, (x + pad, start, inner, max(0.2, y + h - inset - start)), sentence)
        if reserve[k]:
            # No taller than the label's line, so it stays clear of the sentence's box below.
            tall = 0.32 if k == span else min(labels, 0.32)
            _tagged(ctx, (x + w - pad - reserve[k] + 0.1, first + 0.03, reserve[k] - 0.1, tall), item['value'],
                    colour=paint['ink'])


# ---------------------------------------------------------------- 5. tab rows


@variant('cards', 'tab_rows')
def tab_rows(ctx, section, lines):
    """Each item a row: a coloured tab holding its number and tag, then the label and the sentence on a card."""
    items = entries('cards', section)
    n = len(items)
    paints = tones(ctx, n)
    top = header_compact(ctx, section) + 0.02
    gap = 0.08 if n > 4 else 0.16
    longest = max([_tag_width(_tag(item), 10) for item in items if _tag(item)], default=0)
    tab, pad = min(1.45, max(1.0, longest + 0.26)), 0.28
    labels = 2.75 if n > 4 else 3.1
    words_x = LEFT + tab + pad + labels + 0.35
    words_w = RIGHT - pad - words_x
    cap = (FOOT - top - gap * (n - 1)) / n
    scales = ((18, 14), (17, 14), (17, 13), (16, 13), (16, 12), (15, 12))

    def need(item, sizes):
        return max(_need(ctx, labels, _label(item, sizes[0], ink='card_ink')),
                   _need(ctx, words_w, _sentence(item, n, sizes[1], muted='card_muted', spacing=1.1))) + 0.06
    sizes = _choose(lambda s: all(need(item, s) <= cap for item in items), _scales(ctx, items, labels, scales))
    height = min(cap, max(0.95 if n <= 4 else 0.6, max(need(item, sizes) for item in items) + 0.3))
    total = n * height + (n - 1) * gap
    y0 = _centred(top, FOOT - top, total, 0.35)
    for k, item in enumerate(items):
        y = y0 + k * (height + gap)
        paint = paints[k]
        rect(ctx, (LEFT, y, tab, height), paint['fill'])
        rect(ctx, (LEFT + tab, y, WIDTH - tab, height), 'card')
        polygon(ctx, triangle_points((LEFT + tab, y + height / 2 - 0.13, 0.13, 0.26), 'right'), paint['fill'])
        mark = [dict(text=f'{k + 1:02d}', size=20 if n <= 4 else 18, floor=14, colour=paint['ink'], bold=True,
                     heading=True, align='center', spacing=1.0)]
        if _tag(item):
            mark.append(dict(text=item['value'], words=3, upper=True, size=10, floor=9, colour=paint['ink'],
                             bold=True, align='center', before=2, spacing=1.0))
        _put(ctx, (LEFT + 0.06, y + 0.04, tab - 0.12, height - 0.08), mark, anchor='middle')
        _put(ctx, (LEFT + tab + pad, y + 0.03, labels, height - 0.06), _label(item, sizes[0], ink='card_ink'),
             anchor='middle')
        if item.get('text'):
            _put(ctx, (words_x, y + 0.03, words_w, height - 0.06),
                 _sentence(item, n, sizes[1], muted='card_muted', spacing=1.1), anchor='middle')


# ---------------------------------------------------------------- 6. side grid


@variant('cards', 'side_grid', counts=(3, 4))
def side_grid(ctx, section, lines):
    """The heading in a column at the left; the cards in a two-column grid beside it, tinted like a chequerboard."""
    items = entries('cards', section)
    n = len(items)
    # A narrow column: the heading steps down until its longest word keeps to one line.
    x0 = header_side(ctx, section, width=3.3, size=_heading_size(ctx, section, 3.3, 30))
    top, gap, pad, head = 0.62, 0.22, 0.24, 0.34
    width = (RIGHT - x0 - gap) / 2
    height = (FOOT - top - gap) / 2
    if n == 3:
        boxes = [(x0, top, width, FOOT - top), (x0 + width + gap, top, width, height),
                 (x0 + width + gap, top + height + gap, width, height)]
        fills = ['accent_soft', 'card', 'card']
    else:
        boxes = [(x0 + column * (width + gap), top + row * (height + gap), width, height)
                 for row in range(2) for column in range(2)]
        fills = ['accent_soft', 'card', 'card', 'accent_soft']

    def story(k, sizes):
        colours = inks(fills[k])
        return _story(items[k], n, sizes, ink=colours['ink'], muted=colours['muted'], tag=False)
    sizes = _choose(lambda s: all(_need(ctx, boxes[k][2] - 2 * pad, story(k, s))
                                  <= boxes[k][3] - 2 * pad - head - 0.08 for k in range(n)),
                    _scales(ctx, items, width - 2 * pad))
    for k, (x, y, w, h) in enumerate(boxes):
        colours = inks(fills[k])
        rect(ctx, (x, y, w, h), fills[k])
        text(ctx, (x + pad, y + pad - 0.04, 0.8, head), f'{k + 1:02d}', size=18, colour=colours['accent'],
             bold=True, heading=True, spacing=1.0)
        if _tag(items[k]):
            _tagged(ctx, (x + pad + 0.85, y + pad, w - 2 * pad - 0.85, head - 0.04), items[k]['value'],
                    colour=colours['accent'])
        start = y + pad + head + 0.08
        _put(ctx, (x + pad, start, w - 2 * pad, y + h - pad - start), story(k, sizes), anchor='bottom')


# ---------------------------------------------------------------- 7. zigzag


@variant('cards', 'zigzag', counts=(3, 4))
def zigzag(ctx, section, lines):
    """Cards set alternately high and low, a line through the gaps between them meeting each card at a dot."""
    items = entries('cards', section)
    n = len(items)
    top = header_compact(ctx, section) + 0.05
    gap, pad = (0.7, 0.25) if n == 3 else (0.4, 0.22)
    columns = split(LEFT, WIDTH, n, gap)
    width = columns[0][1]
    space = FOOT - top
    least = 0.75

    def story(item, sizes, fill='card'):
        colours = inks(fill)
        return _story(item, n, sizes, ink=colours['ink'], muted=colours['muted'], accent=colours['accent'])
    drop = max(_drop(items, k) for k in range(n))
    sizes = _choose(lambda s: all(_need(ctx, width - 2 * pad, story(item, s)) + drop + 2 * pad <= space - least
                                  for item in items), _scales(ctx, items, width - 2 * pad))
    need = max(_need(ctx, width - 2 * pad, story(item, sizes)) for item in items) + drop + 2 * pad
    # Cards as tall as the longest needs (never under 1.7 in), stepped by about half their height: a brief
    # slide gets short cards in a tight zigzag, centred, rather than tall empty ones spread over the frame.
    height = min(space - least, max(need, 1.7))
    free = min(space - height, max(0.85, height * 0.45))
    y0 = _centred(top, space, height + free, 0.42)
    middle = y0 + (height + free) / 2
    for k, (item, (x, w)) in enumerate(zip(items, columns)):
        high = k % 2 == 0
        y = y0 if high else y0 + free
        fill = 'card' if high else 'accent_soft'
        rect(ctx, (x, y, w, height), fill)
        lower = _drop(items, k) if high else 0.0
        _put(ctx, (x + pad, y + pad + lower, w - 2 * pad, height - 2 * pad - lower), story(item, sizes, fill),
             anchor='top' if high else 'bottom')
        box = (x + pad, y + height + 0.1, w - 2 * pad, free - 0.1) if high else (x + pad, y0, w - 2 * pad,
                                                                                 free - 0.1)
        figure(ctx, box, f'{k + 1:02d}', size=40 if free >= 0.85 else 32, colour='accent_text',
               anchor='top' if high else 'bottom')
    # The path in the accent made to read on the slide: a pale accent's own would all but vanish.
    for k in range(n - 1):
        start, end = columns[k][0] + columns[k][1], columns[k + 1][0]
        line(ctx, (start, middle), (end, middle), 'accent_text', 1.5)
        for edge in (start, end):
            oval(ctx, disc(edge, middle, 0.16), 'accent_text')


# ---------------------------------------------------------------- 8. top bars


@variant('cards', 'top_bars', counts=(3, 4))
def top_bars(ctx, section, lines):
    """Card panels under thick coloured bars carrying 01, 02; the tag a chip, the heading on a strong band above."""
    items = entries('cards', section)
    n = len(items)
    fills = hues(ctx, n)
    top = header_band(ctx, section, fill=strong(ctx), height=1.5) - 0.05
    gap, pad, bar = (0.3, 0.26, 0.62) if n == 3 else (0.24, 0.22, 0.58)
    columns = split(LEFT, WIDTH, n, gap)
    width = columns[0][1]
    chip_room = 0.42 if any(_tag(item) for item in items) else 0.0
    space = FOOT - top - bar

    def story(item, sizes):
        return _story(item, n, sizes, ink='card_ink', muted='card_muted', tag=False)
    sizes = _choose(lambda s: all(_need(ctx, width - 2 * pad, story(item, s)) + chip_room + 2 * pad <= space
                                  for item in items), _scales(ctx, items, width - 2 * pad))
    need = max(_need(ctx, width - 2 * pad, story(item, sizes)) for item in items) + chip_room + 2 * pad
    # Panels as tall as the fullest needs, but never under 60% of the room; a brief slide's are centred below
    # the band rather than standing the full height with their lower half empty.
    height = min(space, max(need + 0.2, space * 0.6))
    top = _centred(top, space + bar, height + bar, 0.4)
    chip_fill = hex_of(ctx, 'card_accent')
    for k, (item, (x, w)) in enumerate(zip(items, columns)):
        paint = fills[k]
        rect(ctx, (x, top, w, bar), paint['fill'])
        text(ctx, (x + pad, top + 0.06, w - 2 * pad, bar - 0.12), f'{k + 1:02d}', size=22, colour=paint['ink'],
             bold=True, heading=True, anchor='middle', spacing=1.0)
        rect(ctx, (x, top + bar, w, height), 'card')
        y = top + bar + pad
        if _tag(item):
            _chip(ctx, x + pad, y, item['value'], fill=chip_fill, ink=on(chip_fill), most=w - 2 * pad)
        _put(ctx, (x + pad, y + chip_room, w - 2 * pad, top + bar + height - pad - y - chip_room),
             story(item, sizes))


# ---------------------------------------------------------------- 9. outlined


@variant('cards', 'outlined', counts=(3, 4))
def outlined(ctx, section, lines):
    """Line-only cards in the accent, each tag a small filled chip sitting on the card's top edge."""
    items = entries('cards', section)
    n = len(items)
    top = header_number(ctx, section) + 0.12
    gap, pad = (0.35, 0.3) if n == 3 else (0.26, 0.26)
    columns = split(LEFT, WIDTH, n, gap)
    width = columns[0][1]
    space = FOOT - top
    lead = 0.56

    def story(item, sizes):
        return _story(item, n, sizes, tag=False)
    sizes = _choose(lambda s: all(_need(ctx, width - 2 * pad, story(item, s)) + lead + pad <= space
                                  for item in items), _scales(ctx, items, width - 2 * pad))
    need = max(_need(ctx, width - 2 * pad, story(item, sizes)) for item in items) + lead + pad
    height = min(space, max(need + 0.15, space * 0.55))
    y = _centred(top, space, height, 0.4)
    edge = hex_of(ctx, 'accent_text')
    for k, (item, (x, w)) in enumerate(zip(items, columns)):
        rect(ctx, (x, y, w, height), None, line='accent_text', line_width=1.25)
        if _tag(item):
            _chip(ctx, x + pad, y - 0.14, item['value'], fill=edge, ink=on(edge), most=w - 2 * pad)
        text(ctx, (x + w - pad - 0.8, y + 0.18, 0.8, 0.3), f'{k + 1:02d}', size=13, colour='accent_text', bold=True,
             align='right')
        _put(ctx, (x + pad, y + lead, w - 2 * pad, height - lead - pad), story(item, sizes))


# ---------------------------------------------------------------- 10. numeral columns


@variant('cards', 'numeral_columns', counts=(3, 4))
def numeral_columns(ctx, section, lines):
    """Airy columns without panels, each headed by a large accent numeral and a short rule, hairlines between them."""
    items = entries('cards', section)
    n = len(items)
    eyebrow(ctx, (LEFT, 0.62, WIDTH, 0.3))
    headline(ctx, section, (LEFT, 0.95, WIDTH * 0.72, 1.3), size=32, lines=2)
    # Hairlines in the soft tint, deepened just enough to show on the slide (a pale tint vanishes on white).
    hair = readable(ctx, 'accent_soft', 'surface', 1.6)
    line(ctx, (LEFT, 2.42), (RIGHT, 2.42), hair, 1.0)
    top = 2.68
    gap = 0.75 if n == 3 else 0.55
    columns = split(LEFT, WIDTH, n, gap)
    width = columns[0][1]
    lead = 1.12
    room = FOOT - top - lead

    def story(item, sizes):
        return _story(item, n, sizes)
    sizes = _choose(lambda s: all(_drop(items, k) + _need(ctx, width, story(item, s)) <= room
                                  for k, item in enumerate(items)), _scales(ctx, items, width))
    tallest = max(_drop(items, k) + _need(ctx, width, story(item, sizes)) for k, item in enumerate(items))
    y = _centred(top, room, tallest, 0.4)
    for k, (item, (x, w)) in enumerate(zip(items, columns)):
        figure(ctx, (x, y, w, 0.85), f'{k + 1:02d}', size=48, colour='accent_text', anchor='bottom')
        rule(ctx, (x, y + 0.92, 0.55, RULE), colour='accent_text')
        start = y + lead + _drop(items, k)
        _put(ctx, (x, start, w, FOOT - start), story(item, sizes))
        if k:
            seam = x - gap / 2
            line(ctx, (seam, y + 0.15), (seam, min(FOOT, y + lead + tallest)), hair, 1.0)
