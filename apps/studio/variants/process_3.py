"""Process variants: numbered steps on rails, blocks, chains, flags, bars and numerals, in reading order."""
from . import variant
from .kit import (FOOT, LEFT, RIGHT, RULE, TOP, WIDTH, badge, block, disc, entries, eyebrow, figure, header,
                  header_band, header_compact, header_number, headline, height, hexagon_points, hues, inks, line,
                  polygon, rect, rounded, rule, split, strong, text, tones)

LABEL, BODY = 7, 22   # the classic drawer's word limits for a step's name and sentence
CEILING = 0.62        # the frame's top
SLACK = 0.05          # what a measured box adds to its text (block keeps 3 pt spare)
BROKEN = 99.0         # added to a measure whose text has a word too wide for its line
# (name, sentence) sizes tried in turn, largest first: one pair for every step of a slide.
PAIRS = ((18, 15), (17, 15), (17, 14), (16, 14), (16, 13), (15, 13), (15, 12), (14, 12))


# ---------------------------------------------------------------- measuring and setting steps alike


def _held(value, limit):
    """`value` held to `limit` words, as kit.block will set it (for measuring)."""
    parts = str(value or '').split()
    return ' '.join(parts[:limit]) + ('…' if len(parts) > limit else '')


def _high(ctx, value, width, size, heading=False):
    """Inches `value` takes at `size` in a box `width` wide, plus BROKEN if a word of it is wider than the box.

    The measure counts such a word as broken over lines, and a viewer breaks it mid-word; no size that does
    that is chosen, and a slide that only fits so is marked (`_mark`) for the next variant.
    """
    if not value:
        return 0.0
    line_high = size * 1.15 / 72 + 1e-6
    broken = any(height(ctx, word, width, size, bold=heading, heading=heading) > line_high for word in value.split())
    return height(ctx, value, width, size, bold=heading, heading=heading) + (BROKEN if broken else 0.0)


def _name_high(ctx, item, width, size):
    """Inches a step's name takes at `size` in a box `width` wide."""
    return _high(ctx, _held(item.get('label'), LABEL), width, size, heading=True)


def _text_high(ctx, item, width, size):
    """Inches a step's sentence takes at `size` in a box `width` wide (0 when it has none)."""
    return _high(ctx, _held(item.get('text'), BODY), width, size)


def _mark(ctx, *measures):
    """Mark the slide when the smallest sizes still break a word: the next variant draws it instead."""
    if any(measure >= BROKEN for measure in measures):
        ctx.shortened = True


def _name(item, size, colour='ink', align='left'):
    return dict(text=item['label'], words=LABEL, size=size, floor=min(14, size), colour=colour, bold=True,
                heading=True, align=align)


def _sentence(item, size, colour='muted', align='left'):
    return dict(text=item.get('text'), words=BODY, size=size, floor=12, colour=colour, align=align)


def _pairs(label, body, ctx=None, steps=(), width=None):
    """The size pairs from (`label`, `body`) down; given the steps and their names' `width`, the names held to
    the largest size at which none of them breaks a word."""
    cap = label
    if steps:
        cap = next((size for size in range(label, 14, -1)
                    if all(_name_high(ctx, item, width, size) < BROKEN for item in steps)), 14)
    pairs = [(min(name, cap), text) for name, text in PAIRS if name <= label and text <= body] or [PAIRS[-1]]
    return list(dict.fromkeys(pairs))


def _lift(room, group, bias=0.45):
    """How far a group `group` tall moves down in `room`: a little above centre, never past the bottom."""
    return max(0.0, min((room - group) * bias, room - group - SLACK))


def _columns(ctx, steps, spans, top, *, label=17, body=14, colours=None, align='left', gap=0.08, mark=True):
    """Each step's name over its sentence in its span (x, w) from `top`, names at one size and sentences at
    another, every sentence starting on one line under the tallest name.

    Returns (names, sentences, tall, size): (box, paragraph) jobs, the inches the group takes and the
    sentences' size. `mark` False only measures: the caller is trying a layout and may try another.
    """
    room = FOOT - top
    colours = colours or ['ink'] * len(steps)
    for name, size in _pairs(label, body, ctx, steps, min(w for _, w in spans)):
        names_high = max(_name_high(ctx, item, w, name) for item, (_, w) in zip(steps, spans)) + SLACK
        texts_high = max(_text_high(ctx, item, w, size) for item, (_, w) in zip(steps, spans)) + SLACK
        if names_high + gap + texts_high <= room:
            break
    # Past the smallest sizes the sentences keep what room is left, and kit.block cuts (the slide is marked).
    if mark:
        _mark(ctx, names_high, texts_high)
    names_high = min(names_high, room * 0.4)
    texts_high = max(0.3, min(texts_high, room - names_high - gap))
    names = [((x, top, w, names_high), _name(item, name, colour, align))
             for item, (x, w), colour in zip(steps, spans, colours)]
    sentences = [((x, top + names_high + gap, w, texts_high), _sentence(item, size, align=align))
                 for item, (x, w) in zip(steps, spans) if item.get('text')]
    return names, sentences, names_high + gap + texts_high, size


def _put(ctx, jobs, dy=0.0, anchor='top'):
    """Each (box, paragraph) job set `dy` lower; names sit on the bottom of their row, just over the sentence."""
    for (x, y, w, h), paragraph in jobs:
        block(ctx, (x, y + dy, w, h), [paragraph], anchor=anchor)


def _pill(ctx, box, value, fill, ink, size=13):
    """A short rounded bar with a number on it, the number's box clear of the round ends."""
    x, y, w, h = box
    rounded(ctx, box, fill, radius=h / 2)
    text(ctx, (x + h * 0.25, y + h * 0.18, w - h * 0.5, h * 0.64), value, size=size, colour=ink, bold=True,
         heading=True, align='center', anchor='middle', spacing=1.0)


# ---------------------------------------------------------------- variants


@variant('process', 'ladder', counts=(3, 5))
def ladder(ctx, section, lines):
    """A rail a third of the way across with a numbered rung per step: names right-aligned left of it, sentences
    to its right."""
    top = header_number(ctx, section) - 0.15
    steps = entries('process', section)
    n = len(steps)
    rail = LEFT + 3.55
    names_x, names_w = LEFT, rail - 0.55 - LEFT
    words_x = rail + 0.55
    words_w = RIGHT - words_x
    room = FOOT - top
    for label, body in _pairs(18, 15, ctx, steps, names_w):
        row = max(max(_name_high(ctx, item, names_w, label), _text_high(ctx, item, words_w, body))
                  for item in steps) + SLACK
        if n * row + (n - 1) * 0.15 <= room:
            break
    _mark(ctx, row)
    row = min(max(row, 0.42), (room - (n - 1) * 0.15) / n)
    space = min(0.5, (room - n * row) / (n - 1)) if n > 1 else 0
    group = n * row + (n - 1) * space
    start = top + _lift(room, group, 0.5)
    middles = [start + k * (row + space) + row / 2 for k in range(n)]
    rect(ctx, (rail - 0.03, max(top - 0.1, middles[0] - 0.5), 0.06,
               min(FOOT, middles[-1] + 0.5) - max(top - 0.1, middles[0] - 0.5)), 'accent_soft')
    for k, (item, middle) in enumerate(zip(steps, middles)):
        _pill(ctx, (rail - 0.4, middle - 0.19, 0.8, 0.38), f'{k + 1:02d}', 'accent', 'on_accent')
        block(ctx, (names_x, middle - row / 2, names_w, row), [_name(item, label, align='right')], anchor='middle')
        if item.get('text'):
            block(ctx, (words_x, middle - row / 2, words_w, row), [_sentence(item, body)], anchor='middle')


@variant('process', 'tone_blocks', counts=(3, 5))
def tone_blocks(ctx, section, lines):
    """Full-width blocks stacked in the accent's tones, darkest first, each holding its number, name and
    sentence."""
    steps = entries('process', section)
    n = len(steps)
    gap, pad = 0.07, 0.05
    name_x, name_w = LEFT + 1.25, 2.6
    body_x = name_x + name_w + 0.35
    body_w = RIGHT - 0.3 - body_x

    def sizes(top):
        """Block height and the largest sizes every block holds with the body from `top`."""
        # Blocks fill the body (to an inch each).
        tall = min(1.05, (FOOT - top - gap * (n - 1)) / n)
        for label, body in _pairs(17, 15, ctx, steps, name_w):
            need = max(max(_name_high(ctx, item, name_w, label), _text_high(ctx, item, body_w, body))
                       for item in steps) + SLACK + 2 * pad
            if need <= tall:
                break
        return tall, label, body, need
    # The classic top while it leaves the sentences 14 pt; a long five-step slide takes the compact one.
    tall, label, body, need = sizes(TOP)
    top = header(ctx, section) if body >= 14 else header_compact(ctx, section)
    if top != TOP:
        tall, label, body, need = sizes(top)
    _mark(ctx, need)
    room = FOOT - top
    group = n * tall + gap * (n - 1)
    start = top + _lift(room, group, 0.4)
    for k, (item, fill) in enumerate(zip(steps, tones(ctx, n))):
        y = start + k * (tall + gap)
        rect(ctx, (LEFT, y, WIDTH, tall), fill['fill'])
        # The number's box ends well short of the hairline after it.
        text(ctx, (LEFT + 0.3, y + pad, 0.62, tall - 2 * pad), f'{k + 1:02d}', size=26, colour=fill['ink'],
             bold=True, heading=True, anchor='middle')
        line(ctx, (name_x - 0.22, y + tall * 0.26), (name_x - 0.22, y + tall * 0.74), fill['ink'], 1.0)
        line(ctx, (body_x - 0.2, y + tall * 0.26), (body_x - 0.2, y + tall * 0.74), fill['ink'], 0.5)
        block(ctx, (name_x, y + pad, name_w, tall - 2 * pad), [_name(item, label, fill['ink'])], anchor='middle')
        if item.get('text'):
            block(ctx, (body_x, y + pad, body_w, tall - 2 * pad), [_sentence(item, body, fill['ink'])],
                  anchor='middle')


@variant('process', 'side_flow', counts=(3, 5))
def side_flow(ctx, section, lines):
    """The heading on a strong panel down the left; the steps run down the right on numbered discs joined by
    short links."""
    fill = strong(ctx)
    colours = inks(fill)
    panel_w, pad = 3.95, 0.36
    rect(ctx, (LEFT, CEILING, panel_w, FOOT - CEILING), fill)
    eyebrow(ctx, (LEFT + pad, CEILING + pad, panel_w - 2 * pad, 0.3), colour=colours['muted'])
    rule(ctx, (LEFT + pad, CEILING + pad + 0.42, 0.9, RULE), colour=colours['ink'])
    # A narrow column: the heading comes down until its longest word sets on one line.
    heading = _held(section.get('heading'), 14)
    size = next((size for size in (30, 28, 26, 24, 22)
                 if _high(ctx, heading, panel_w - 2 * pad, size, heading=True) < BROKEN), 20)
    headline(ctx, section, (LEFT + pad, CEILING + pad + 0.7, panel_w - 2 * pad, FOOT - CEILING - 2 * pad - 0.7),
             size=size, lines=6, anchor='top', colour=colours['ink'])
    steps = entries('process', section)
    n = len(steps)
    d, least = 0.58, 0.18
    x0 = LEFT + panel_w + 0.5
    body_x = x0 + d + 0.28
    body_w = RIGHT - body_x
    for label, body in _pairs(18, 15, ctx, steps, body_w):
        # The first disc's top stays in the frame: it rises above its name's first line, on which it centres.
        line_high = label * 1.15 / 72
        ceiling = CEILING + max(0.0, (d - line_high) / 2) + 0.01
        room = FOOT - ceiling
        need = max(_name_high(ctx, item, body_w, label) + 0.04 + _text_high(ctx, item, body_w, body)
                   for item in steps) + SLACK
        if n * need + (n - 1) * least <= room:
            break
    _mark(ctx, need)
    need = min(need, (room - (n - 1) * least) / n)
    # Steps a fixed pitch apart (1.3 in), closer only when long ones need it: brief steps keep links long
    # enough to read as a path instead of closing up into a stack of touching discs.
    pitch = max(need + least, min(1.3, (room - need) / (n - 1))) if n > 1 else need
    group = need + (n - 1) * pitch
    start = ceiling + _lift(room, group, 0.5)
    for k, item in enumerate(steps):
        y = start + k * pitch
        centre = y + line_high / 2
        badge(ctx, disc(x0 + d / 2, centre, d), f'{k + 1:02d}', fill='accent', ink='on_accent', size=17,
              heading=True)
        if k < n - 1:
            following = centre + pitch
            line(ctx, (x0 + d / 2, centre + d / 2 + 0.08), (x0 + d / 2, following - d / 2 - 0.08), 'accent_text',
                 1.5)
        block(ctx, (body_x, y, body_w, need), [dict(_name(item, label), after=3), _sentence(item, body)])


@variant('process', 'hex_chain', counts=(3, 5))
def hex_chain(ctx, section, lines):
    """Numbered hexagons linked in a zigzag chain, filled and outlined in turn; each step's name and sentence
    below, the sentences on one line."""
    # A compact centred top: the chain and five columns of centred text need the height, and it keeps this
    # slide from being header_center over a row of marks, like the classic drawer and diamond_line.
    eyebrow(ctx, (LEFT, CEILING, WIDTH, 0.3), align='center')
    # The rule a clear step below the heading's last line: centred, closer, it reads as an underline.
    headline(ctx, section, (LEFT + 0.8, 0.92, WIDTH - 1.6, 0.92), size=28, lines=2, align='center')
    rule(ctx, (LEFT + WIDTH / 2 - 0.45, 2.0, 0.9, RULE))
    top = 2.3
    steps = entries('process', section)
    n = len(steps)
    slots = split(LEFT, WIDTH, n, 0)
    hw = min({3: 1.25, 4: 1.1}.get(n, 0.9), slots[0][1] * 0.45)
    hh = hw * 0.87
    # Every other hexagon drops by a third of its height: the bonds between them zigzag visibly.
    lift = round(hh * 0.34, 2)
    chain = hh + lift + 0.28
    # Centred columns need a clear gutter; five columns keep a little less so their sentences stay 14 pt.
    inset = 0.17 if n < 5 else 0.11
    names, sentences, tall, _ = _columns(ctx, steps, [(x + inset, w - 2 * inset) for x, w in slots], top + chain,
                                         body=15 if n < 4 else 14, align='center')
    shift = _lift(FOOT - top, chain + tall, 0.4)
    boxes = [(x + w / 2 - hw / 2, top + shift + (0 if k % 2 == 0 else lift), hw, hh)
             for k, (x, w) in enumerate(slots)]
    for k in range(n - 1):
        (x1, y1, w1, h1), (x2, y2, _, h2) = boxes[k], boxes[k + 1]
        line(ctx, (x1 + w1 + 0.07, y1 + h1 / 2), (x2 - 0.07, y2 + h2 / 2), 'accent_text', 2.0)
    for k, box in enumerate(boxes):
        number = f'{k + 1:02d}'
        if k % 2 == 0:
            badge(ctx, box, number, fill='accent', ink='on_accent', shape='hexagon', size=22, heading=True)
        else:
            polygon(ctx, hexagon_points(box), None, line='accent_text', line_width=2.25)
            x, y, w, h = box
            text(ctx, (x + w * 0.19, y + h * 0.19, w * 0.62, h * 0.62), number, size=22, colour='accent_text',
                 bold=True, heading=True, align='center', anchor='middle')
    _put(ctx, names, shift, anchor='bottom')
    _put(ctx, sentences, shift)


@variant('process', 'flags', counts=(3, 5))
def flags(ctx, section, lines):
    """Numbered flags on poles that rise step by step from a baseline; each step's name and sentence under it."""
    top = header_compact(ctx, section)
    steps = entries('process', section)
    n = len(steps)
    spans = split(LEFT, WIDTH, n, 0.25)
    flag_w, flag_h, notch, pole = min(1.2, spans[0][1] * 0.55), 0.5, 0.16, 0.045
    body = 15 if n < 4 else 14
    # The tallest poles that leave the sentences their size; long five-step slides take shorter ones.
    for low, high in ((0.75, 1.35), (0.68, 1.18), (0.6, 1.02)):
        mast = 0.12 + high
        names, sentences, tall, size = _columns(ctx, steps, spans, top + mast + 0.3, body=body, mark=False)
        if size >= 14:
            break
    names, sentences, tall, size = _columns(ctx, steps, spans, top + mast + 0.3, body=body)
    shift = _lift(FOOT - top, mast + 0.3 + tall, 0.4)
    base = top + mast + shift
    rect(ctx, (LEFT, base, WIDTH, 0.035), 'muted')
    for k, (x, w) in enumerate(spans):
        rise = low + (high - low) * (k / (n - 1) if n > 1 else 1)
        peak = base - rise
        px = x + 0.035
        rect(ctx, (px, peak, pole, rise), 'muted')
        rect(ctx, (x, base - 0.035, pole + 0.07, 0.105), 'muted')
        fx = px + pole
        polygon(ctx, [(fx, peak), (fx + flag_w, peak), (fx + flag_w - notch, peak + flag_h / 2),
                      (fx + flag_w, peak + flag_h), (fx, peak + flag_h)], 'accent')
        text(ctx, (fx + 0.14, peak + 0.06, flag_w - notch - 0.24, flag_h - 0.12), f'{k + 1:02d}', size=18,
             colour='on_accent', bold=True, heading=True, anchor='middle')
    _put(ctx, names, shift, anchor='bottom')
    _put(ctx, sentences, shift)


@variant('process', 'progress_segments', counts=(3, 5))
def progress_segments(ctx, section, lines):
    """The heading on a band, then a progress bar of rounded segments, one hue and number each; the text under
    each segment."""
    top = header_band(ctx, section, fill=strong(ctx), height=1.55)
    steps = entries('process', section)
    n = len(steps)
    spans = split(LEFT, WIDTH, n, 0.1)
    fills = hues(ctx, n)
    seg_h = 0.56
    names, sentences, tall, _ = _columns(ctx, steps, [(x + 0.04, w - 0.12) for x, w in spans], top + seg_h + 0.32,
                                         body=15 if n < 4 else 14, colours=[fill['text'] for fill in fills])
    # Brief steps sit nearer the middle of the body rather than hanging under the band.
    shift = _lift(FOOT - top, seg_h + 0.32 + tall, 0.42)
    for k, ((x, w), fill) in enumerate(zip(spans, fills)):
        _pill(ctx, (x, top + shift, w, seg_h), f'{k + 1:02d}', fill['fill'], fill['ink'], size=18)
    _put(ctx, names, shift, anchor='bottom')
    _put(ctx, sentences, shift)


@variant('process', 'big_numerals', counts=(3, 4))
def big_numerals(ctx, section, lines):
    """Giant accent numerals with each step's name beside and its sentence below, columns parted by hairlines."""
    rect(ctx, (LEFT, 0.98, 0.08, 1.22), 'accent')
    eyebrow(ctx, (LEFT + 0.34, CEILING, 3.2, 0.3))
    headline(ctx, section, (LEFT + 0.34, 0.96, WIDTH - 0.34, 1.26), size=32, lines=2, anchor='middle')
    top = 2.62
    steps = entries('process', section)
    n = len(steps)
    # Four columns close up and take a smaller numeral, so a long name keeps its words whole beside it.
    gap, numeral, numeral_w = (0.6, 72, 0.74) if n < 4 else (0.42, 64, 0.64)
    numeral_h = 1.12
    spans = split(LEFT, WIDTH, n, gap)
    name_w = spans[0][1] - numeral_w - 0.08
    under = numeral_h + 0.2
    label = next((size for size in range(17, 13, -1)
                  if max(_name_high(ctx, item, name_w, size) for item in steps) + SLACK <= numeral_h), 14)
    names_high = max(_name_high(ctx, item, name_w, label) for item in steps) + SLACK
    # The sentences no larger than the names, and as large as the room allows.
    for body in range(min(15, label), 11, -1):
        texts_high = max(_text_high(ctx, item, spans[0][1], body) for item in steps) + SLACK
        if under + texts_high <= FOOT - top:
            break
    _mark(ctx, names_high, texts_high)
    texts_high = min(texts_high, FOOT - top - under)
    needed = under + texts_high
    shift = _lift(FOOT - top, needed, 0.5)
    for k, (item, (x, w)) in enumerate(zip(steps, spans)):
        figure(ctx, (x, top + shift, numeral_w, numeral_h), str(k + 1), size=numeral, colour='accent_text',
               anchor='middle')
        if k:
            mid = x - gap / 2
            line(ctx, (mid, top + shift + 0.05), (mid, top + shift + needed), 'muted', 0.75)
        block(ctx, (x + numeral_w + 0.08, top + shift, name_w, numeral_h), [_name(item, label)], anchor='middle')
        if item.get('text'):
            block(ctx, (x, top + shift + under, w, texts_high), [_sentence(item, body)])
