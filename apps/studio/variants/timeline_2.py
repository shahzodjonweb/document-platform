"""Timeline variants: dated events strung along tracks, lines, bands, stairs and cards."""
from ..slides import contrast_ratio
from . import variant
from .kit import (FOOT, LEFT, RIGHT, RULE, TOP, WIDTH, block, clip, disc, entries, eyebrow, figure, header,
                  header_band, header_number, headline, height, hex_of, inks, line, oval, polygon, rect, rounded, rule,
                  split, strong, tab_points, tones, triangle_points)

DATE, LABEL, TEXT = 4, 7, 16  # the classic drawer's word limits: a date, an event's name, its sentence


# ---------------------------------------------------------------- headings and colour
#
# kit.header_center and kit.header_compact set the rule 0.13 and 0.08 in under the heading's box: a descender
# touches it and, centred, it reads as an underline of the middle word. These two keep their arrangement with the
# rule set clear of the heading.


def _top_centred(ctx, section):
    """Eyebrow, heading and rule centred, the rule clear of the heading. Returns where the body starts (2.75)."""
    eyebrow(ctx, (LEFT, 0.62, WIDTH, 0.3), align='center')
    headline(ctx, section, (LEFT + 0.8, 0.98, WIDTH - 1.6, 1.12), size=32, align='center')
    rule(ctx, (LEFT + WIDTH / 2 - 0.55, 2.34, 1.1, RULE))
    return TOP


def _top_compact(ctx, section):
    """The short top (heading to 1.82, rule at 1.99), the rule clear of the heading. Returns 2.2."""
    eyebrow(ctx)
    headline(ctx, section, (LEFT, 0.92, WIDTH, 0.9), size=28, lines=2)
    rule(ctx, (LEFT, 1.99, 0.9, RULE))
    return 2.2


def _heading_size(ctx, section, width, size, lines, room):
    """(points, inches) the heading takes in a box `width` wide and `room` tall, as kit.headline shrinks it."""
    value = clip(ctx, section.get('heading'), 14)
    if not value:
        return size, 0.0

    def tall(points):
        return height(ctx, value, width, points, heading=True, spacing=1.08)

    while size > 18 and (tall(size) > lines * size * 1.08 / 72 + 1e-6 or tall(size) > room):
        size -= 2
    return size, tall(size)


def _ramp(ctx, n):
    """`n` tones of the accent, the one that stands out most from the surface last (the latest event)."""
    fills = tones(ctx, n)
    surface = hex_of(ctx, 'surface')
    if contrast_ratio(fills[0]['fill'], surface) > contrast_ratio(fills[-1]['fill'], surface):
        fills.reverse()
    return fills


# ---------------------------------------------------------------- measuring


def _clipped(value, words):
    parts = str(value or '').split()
    return ' '.join(parts[:words]) + ('…' if len(parts) > words else '')


def _story(item, *, label, body, ink='ink', muted='muted', align='left'):
    """An event's name and sentence, as `block` paragraphs."""
    return [dict(text=item.get('label'), words=LABEL, size=label, floor=13, colour=ink, bold=True, heading=True,
                 after=4, align=align),
            dict(text=item.get('text'), words=TEXT, size=body, floor=12, colour=muted, align=align)]


def _need(ctx, width, paragraphs):
    """Inches `paragraphs` take at their own sizes in a box `width` wide, measured as `block` measures them."""
    points = 3
    for paragraph in paragraphs:
        value = _clipped(paragraph.get('text'), paragraph.get('words', 99))
        if not value:
            continue
        points += height(ctx, value, width, paragraph['size'], bold=paragraph.get('bold', False),
                         heading=paragraph.get('heading', False), spacing=paragraph.get('spacing', 1.15)) * 72
        points += paragraph.get('before', 0) + paragraph.get('after', 0)
    return points / 72 + 0.04


def _tallest(ctx, width, stories):
    return max(_need(ctx, width, story) for story in stories)


def _whole_words(ctx, width, stories):
    """Whether every word of every story fits a line `width` wide (a longer one would be broken mid-word)."""
    for story in stories:
        for paragraph in story:
            size = paragraph['size']
            for word in set(_clipped(paragraph.get('text'), paragraph['words']).split()):
                if height(ctx, word, width, size, bold=paragraph.get('bold', False),
                          heading=paragraph.get('heading', False)) > size * 1.15 / 72 + 1e-6:
                    return False
    return True


def _stories(ctx, events, width, holds, **options):
    """Every event's story at one pair of sizes, so a slide's stories match: the largest that `holds(stories)`.

    Wide columns start larger; the sizes step down together to 13 and 12 pt, and never leave a word wider than
    its column.
    """
    label, body = (18, 15) if width >= 3.2 else (17, 14) if width >= 2.5 else (16, 13)
    step = 0
    while True:
        sizes = max(13, label - step), max(12, body - step / 2)
        stories = [_story(item, label=sizes[0], body=sizes[1], **options) for item in events]
        if (holds(stories) and _whole_words(ctx, width, stories)) or sizes == (13, 12):
            return stories
        step += 1


def _span(ctx, value, size):
    """Inches a date takes on one line at `size` in the heading face (0 for none)."""
    if not value:
        return 0.0
    one, width = size * 1.15 / 72 + 1e-6, 0.3
    while width < 6 and height(ctx, value, width, size, heading=True) > one:
        width += 0.05
    return width + 0.05


def _date_size(ctx, events, width, size, floor=14):
    """One size for every date of the slide: the largest up to `size` at which each stays on a line `width` wide."""
    values = [_clipped(item.get('value'), DATE) for item in events]
    while size > floor and any(_span(ctx, value, size) > width for value in values):
        size -= 1
    return size


def _settle(top, bottom, group, bias=0.45):
    """Where a group `group` inches tall starts between `top` and `bottom`: a little above centre when short."""
    return top + max(0.0, (bottom - top - group) * bias)


# ---------------------------------------------------------------- variants


@variant('timeline', 'progress_dots')
def progress_dots(ctx, section, lines):
    """A thick rounded track across the slide with a dot per event and the latest a ring; dates above, stories below."""
    top = _top_centred(ctx, section)
    events = entries('timeline', section)
    n = len(events)
    slot = WIDTH / n
    width = slot - 0.2
    date_h, dot, track, drop = 0.46, 0.5, 0.32, 0.28
    head = date_h + 0.1 + dot + drop
    room = FOOT - top - 0.1 - head
    stories = _stories(ctx, events, width, lambda stories: _tallest(ctx, width, stories) <= room, align='center')
    size = _date_size(ctx, events, slot - 0.2, 22)
    y = _settle(top + 0.1, FOOT, head + min(room, _tallest(ctx, width, stories)))
    cy = y + date_h + 0.1 + dot / 2
    centres = [LEFT + slot * (position + 0.5) for position in range(n)]
    rounded(ctx, (LEFT, cy - track / 2, WIDTH, track), 'card', radius=track / 2)
    # The distance covered so far: a thin accent bar inside the track, up to the current event.
    rounded(ctx, (LEFT + 0.1, cy - 0.05, centres[-1] - LEFT - 0.1, 0.1), 'accent', radius=0.05)
    for position, (item, centre) in enumerate(zip(events, centres)):
        current = position == n - 1
        if current:
            oval(ctx, disc(centre, cy, dot + 0.04), 'surface', line='accent', line_width=3.5)
        else:
            oval(ctx, disc(centre, cy, dot), 'accent')
        figure(ctx, (centre - slot / 2 + 0.1, y, slot - 0.2, date_h), item.get('value'), size=size,
               colour='ink' if current else 'accent_text', words=DATE, align='center', anchor='bottom')
        below = cy + dot / 2 + drop
        block(ctx, (centre - width / 2, below, width, FOOT - below), stories[position])


@variant('timeline', 'pill_dates')
def pill_dates(ctx, section, lines):
    """Each date in a rounded accent pill strung on a line that ends in an arrowhead; the story under each pill."""
    top = header_number(ctx, section)
    events = entries('timeline', section)
    n = len(events)
    # Six columns close up a little, so a long Russian name still sets at 15 pt.
    gap, arrow = (0.3 if n <= 5 else 0.2), 0.3
    slot = (WIDTH - arrow + gap) / n
    width = slot - gap
    pill_h, drop = 0.52, 0.32
    size = _date_size(ctx, events, width - pill_h * 0.6, 18)
    longest = max(_span(ctx, _clipped(item.get('value'), DATE), size) for item in events)
    pill_w = min(width, max(1.2, longest + pill_h * 0.6 + 0.12))
    room = FOOT - top - 0.1 - pill_h - drop
    stories = _stories(ctx, events, width, lambda stories: _tallest(ctx, width, stories) <= room)
    y = _settle(top + 0.1, FOOT, pill_h + drop + min(room, _tallest(ctx, width, stories)))
    cy = y + pill_h / 2
    rect(ctx, (LEFT, cy - 0.02, WIDTH - 0.2, 0.04), 'accent')
    polygon(ctx, triangle_points((RIGHT - 0.24, cy - 0.13, 0.24, 0.26), 'right'), 'accent')
    for position, item in enumerate(events):
        x = LEFT + position * slot
        rounded(ctx, (x, y, pill_w, pill_h), 'accent', radius=pill_h / 2)
        figure(ctx, (x + pill_h * 0.3, y + 0.07, pill_w - pill_h * 0.6, pill_h - 0.14), item.get('value'),
               size=size, colour='on_accent', words=DATE, align='center', anchor='middle')
        below = y + pill_h + drop
        block(ctx, (x, below, width, FOOT - below), stories[position])


@variant('timeline', 'side_header')
def side_header(ctx, section, lines):
    """The heading in a column at the left, level with the events; they run down a vertical line at the right, each
    date set large beside its dot."""
    column = 3.6
    events = entries('timeline', section)
    n = len(events)
    date_w, dot, least = 1.45, 0.24, 0.12
    size = _date_size(ctx, events, date_w, 24)
    axis = LEFT + column + 0.45 + date_w + 0.32
    left = axis + 0.36
    width = RIGHT - left
    top, room = 0.72, FOOT - 0.72

    def heights(stories):
        return [max(_need(ctx, width, story), 0.42) for story in stories]
    stories = _stories(ctx, events, width, lambda stories: sum(heights(stories)) + least * (n - 1) <= room)
    needs = heights(stories)
    if max(needs) * n + least * (n - 1) <= room:
        needs = [max(needs)] * n
    elif sum(needs) + least * (n - 1) > room:
        needs = [need * (room - least * (n - 1)) / sum(needs) for need in needs]
    gap = max(least, min(0.6, (room - sum(needs)) / max(1, n - 1)))
    y = top + max(0.0, (room - sum(needs) - gap * (n - 1)) / 2)
    rows = []
    for need in needs:
        rows.append(y)
        y += need + gap
    # The heading: the eyebrow at the top of its column, the rule and heading centred on the events beside it.
    eyebrow(ctx, (LEFT, 0.62, column, 0.3))
    points, tall = _heading_size(ctx, section, column, 30, 5, 3.6)
    middle = (rows[0] + rows[-1] + needs[-1]) / 2
    head = min(max(1.05, middle - (0.24 + tall) / 2), FOOT - 0.3 - tall)
    rule(ctx, (LEFT, head, 0.9, RULE))
    headline(ctx, section, (LEFT, head + 0.24, column, tall + 0.06), size=points, lines=5, anchor='top')
    first = stories[0][0]['size'] * 1.15 / 72 / 2  # the middle of a label's first line
    rect(ctx, (axis - 0.015, rows[0] + first, 0.03, rows[-1] - rows[0]), 'accent_soft')
    for position, (item, row, need) in enumerate(zip(events, rows, needs)):
        oval(ctx, disc(axis, row + first, dot + 0.14), 'surface')
        oval(ctx, disc(axis, row + first, dot), 'accent')
        figure(ctx, (axis - 0.32 - date_w, row + first - 0.22, date_w, 0.44), item.get('value'), size=size,
               colour='accent_text', words=DATE, align='right', anchor='middle')
        block(ctx, (left, row, width, need), stories[position])


@variant('timeline', 'two_rows', counts=(4, 6))
def two_rows(ctx, section, lines):
    """The events on two lines, the first half above and the rest below and half a step in; each date sits on the
    line beside its dot, the line running on between them to an arrowhead."""
    top = _top_compact(ctx, section)
    events = entries('timeline', section)
    n = len(events)
    half = -(-n // 2)
    slot = WIDTH / (half + 0.5)
    width = slot - 0.3
    dot, lane, drop, between = 0.24, 0.42, 0.14, 0.34
    room = (FOOT - top - 0.05 - between) / 2 - lane - drop
    stories = _stories(ctx, events, width, lambda stories: _tallest(ctx, width, stories) <= room)
    need = min(room, _tallest(ctx, width, stories))
    size = _date_size(ctx, events, width - dot - 0.6, 20)
    row_h = lane + drop + need
    y = _settle(top + 0.05, FOOT, 2 * row_h + between)
    for row, (offset, group) in enumerate(((0.0, events[:half]), (slot / 2, events[half:]))):
        row_top = y + row * (row_h + between)
        level = row_top + lane / 2
        start = LEFT if row else None  # where the next stretch of line begins
        for position, item in enumerate(group):
            x = LEFT + offset + position * slot
            if start is not None and x - 0.08 - start > 0.1:
                rect(ctx, (start, level - 0.015, x - 0.08 - start, 0.03), 'accent_soft')
            oval(ctx, disc(x + dot / 2, level, dot), 'accent')
            span = min(_span(ctx, _clipped(item.get('value'), DATE), size), width - dot - 0.12)
            figure(ctx, (x + dot + 0.12, row_top, span, lane), item.get('value'), size=size, colour='accent_text',
                   words=DATE, anchor='middle')
            start = x + dot + 0.12 + span + 0.1
            block(ctx, (x, row_top + lane + drop, width, need), stories[row * half + position])
        if RIGHT - 0.2 - start > 0.1:
            rect(ctx, (start, level - 0.015, RIGHT - 0.2 - start, 0.03), 'accent_soft')
        polygon(ctx, triangle_points((RIGHT - 0.2, level - 0.1, 0.2, 0.2), 'right'), 'accent_soft')


@variant('timeline', 'deep_band')
def deep_band(ctx, section, lines):
    """A full-width band in the deck's strongest fill carries the line, dots and dates; a pointer under each dot leads
    to its story."""
    top = header(ctx, section)
    events = entries('timeline', section)
    n = len(events)
    band = inks(strong(ctx))
    pad, gap = (0.35, 0.25) if n <= 4 else (0.28, 0.2) if n == 5 else (0.22, 0.16)
    slot = (WIDTH - 2 * pad + gap) / n
    width = slot - gap
    band_h, tip, drop = 1.1, 0.17, 0.36
    room = FOOT - top - 0.05 - band_h - drop
    stories = _stories(ctx, events, width, lambda stories: _tallest(ctx, width, stories) <= room)
    size = _date_size(ctx, events, width, 24)
    y = _settle(top + 0.05, FOOT, band_h + drop + min(room, _tallest(ctx, width, stories)))
    rect(ctx, (LEFT, y, WIDTH, band_h), band['fill'])
    level = y + band_h - 0.3
    rect(ctx, (LEFT + pad, level - 0.0125, WIDTH - 2 * pad, 0.025), band['muted'])
    for position, item in enumerate(events):
        x = LEFT + pad + position * slot
        oval(ctx, disc(x + 0.11, level, 0.22), band['ink'])
        figure(ctx, (x, y + 0.16, width, 0.5), item.get('value'), size=size, colour=band['ink'], words=DATE,
               anchor='middle')
        polygon(ctx, triangle_points((x + 0.11 - 0.17, y + band_h - 0.01, 0.34, tip + 0.01), 'down'), band['fill'])
        below = y + band_h + drop
        block(ctx, (x, below, width, FOOT - below), stories[position])


@variant('timeline', 'stairs', counts=(2, 6))
def stairs(ctx, section, lines):
    """Dated blocks climbing from the lower left to the upper right, each story hanging under its block beside a rule
    in the block's tone; the heading in the corner the climb leaves free."""
    events = entries('timeline', section)
    n = len(events)
    gap, step_h, drop, inset = (0.16, 0.62, 0.16, 0.16) if n <= 5 else (0.12, 0.62, 0.16, 0.12)
    slot = (WIDTH + gap) / n
    width = slot - gap
    starts = [LEFT + position * slot for position in range(n)]
    clear, summit = 2.55, 0.8  # the columns under the heading start below `clear`; the last block's top
    heading_w = [starts[under] - LEFT - 0.35 for under in range(n)]
    # The heading takes the corner over the first `under` columns: never less than 3.4 in, nor more than 7.6.
    candidates = [under for under in range(1, n) if 3.4 <= heading_w[under] <= 7.6] or [n - 1]

    def climb(under):
        """The blocks' tops when the first `under` columns stay below the heading and the last reaches the summit."""
        share = (under - 1) / max(1, n - 1)
        low = (clear - summit * share) / (1 - share) if share < 1 else clear
        rise = (low - summit) / max(1, n - 1)
        return [low - position * rise for position in range(n)]

    def bottoms(tops, stories):
        return [top + step_h + drop + _need(ctx, width - inset, story) for top, story in zip(tops, stories)]

    def plan(under):
        tops = climb(under)
        stories = _stories(ctx, events, width - inset, lambda stories: max(bottoms(tops, stories)) <= FOOT)
        label = stories[0][0]['size']
        # Whole first, then names of 16 pt or more, then the widest heading.
        return (max(bottoms(tops, stories)) <= FOOT, min(label, 16), under), under, tops, stories
    _, under, tops, stories = max((plan(under) for under in candidates), key=lambda option: option[0])
    ends = bottoms(tops, stories)
    shift = max(0.0, (FOOT - max(ends)) * 0.5)
    tops = [top + shift for top in tops]
    base = min(FOOT, max(ends) + shift)
    eyebrow(ctx)
    headline(ctx, section, (LEFT, 0.95, heading_w[under], clear - 0.2 - 0.95 - 0.12), size=30, lines=3,
             anchor='bottom')
    rule(ctx, (LEFT, clear - 0.2, 0.9, RULE))
    fills = _ramp(ctx, n)  # the summit stands out most, on a dark slide as on a light one
    size = _date_size(ctx, events, width - 0.32, 22)
    for position, (item, x, y) in enumerate(zip(events, starts, tops)):
        paint = fills[position]
        rect(ctx, (x, y, width, step_h), paint['fill'])
        figure(ctx, (x + 0.16, y + 0.08, width - 0.32, step_h - 0.16), item.get('value'), size=size,
               colour=paint['ink'], words=DATE, anchor='middle')
        rect(ctx, (x, y + step_h, 0.03, base - y - step_h), paint['fill'])
        below = y + step_h + drop
        block(ctx, (x + inset, below, width - inset, FOOT - below), stories[position])


@variant('timeline', 'cards_dated')
def cards_dated(ctx, section, lines):
    """The heading on a tinted band; each event a card under a date tab in its own tone, its corner cut, the tabs
    linked by a line across the gaps."""
    top = header_band(ctx, section, fill='accent_soft', height=1.45, size=28)
    events = entries('timeline', section)
    n = len(events)
    # Six cards close up a little, so a long Russian name still sets at 14 pt.
    gap, pad = (0.32, 0.18) if n <= 4 else (0.2, 0.12) if n == 5 else (0.16, 0.1)
    bar, cut = 0.62, 0.2
    spans = split(LEFT, WIDTH, n, gap)
    width = spans[0][1] - 2 * pad
    room = FOOT - top - bar - 2 * pad
    stories = _stories(ctx, events, width, lambda stories: _tallest(ctx, width, stories) <= room,
                       ink='card_ink', muted='card_muted')
    card_h = min(FOOT - top, max(1.8, bar + 2 * pad + _tallest(ctx, width, stories)))
    y = _settle(top, FOOT, card_h)
    fills = _ramp(ctx, n)
    # The date's box stops short of the cut corner, so every point under it is the tab.
    room_date = min(width, width + pad - cut + 0.04)
    size = _date_size(ctx, events, room_date, 20)
    for position, (item, (x, span)) in enumerate(zip(events, spans)):
        paint = fills[position]
        polygon(ctx, tab_points((x, y, span, bar), cut=cut), paint['fill'])
        rect(ctx, (x, y + bar, span, card_h - bar), 'card')
        figure(ctx, (x + pad, y + 0.08, room_date, bar - 0.16), item.get('value'), size=size, colour=paint['ink'],
               words=DATE, anchor='middle')
        block(ctx, (x + pad, y + bar + pad, width, card_h - bar - 2 * pad), stories[position])
        if position:
            line(ctx, (x - gap, y + bar / 2), (x, y + bar / 2), 'muted', 1.75)
