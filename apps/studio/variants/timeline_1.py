"""Timeline variants: dated events strung along a line, a ribbon, an arrow or a spine, in order."""
from . import variant
from .kit import (FOOT, LEFT, RIGHT, WIDTH, arrow_points, block, chevron_points, clip, diamond_points, disc, entries,
                  eyebrow, header_band, header_center, header_compact, headline, height, hues, inks, line, oval,
                  polygon, rect, rule, split, strong, text, triangle_points)

# The classic drawer's word limits: date, event name, sentence.
DATE, LABEL, BODY = 4, 7, 16
# (name, sentence) sizes, largest first: every event of a slide is set at the first that holds them all.
SCALES = ((17, 14), (16, 14), (16, 13), (15, 13), (15, 12), (14, 12))
MARGIN = 4 / 72  # what a text box needs beyond its lines (kit.fits keeps 3 pt spare)


def _plain(value, words=None):
    parts = str(value or '').split()
    return ' '.join(parts[:words] if words else parts)


def _story(item, label, body, *, date=None, align='left', ink='ink', muted='muted', accent='accent_text', gap=5):
    """An event's paragraphs for kit.block: its date (when `date` is a size), its name and its sentence."""
    return [
        date and dict(text=item.get('value'), words=DATE, size=date, floor=date, colour=accent, bold=True,
                      heading=True, after=gap, align=align),
        dict(text=item.get('label'), words=LABEL, size=label, floor=min(label, 13), colour=ink, bold=True,
             heading=True, after=gap, align=align),
        dict(text=item.get('text'), words=BODY, size=body, floor=12, colour=muted, align=align),
    ]


def _clipped(paragraphs):
    return [{**p, 'text': _plain(p.get('text'), p.get('words'))} for p in paragraphs if p]


def _tall(ctx, width, paragraphs):
    """Inches `paragraphs` take in a box `width` wide, at their sizes, with the box's spare."""
    total = 0
    for p in _clipped(paragraphs):
        if not p['text']:
            continue
        total += height(ctx, p['text'], width, p['size'], bold=p.get('bold', False), heading=p.get('heading', False),
                        spacing=p.get('spacing', 1.15)) + (p.get('before', 0) + p.get('after', 0)) / 72
    return total + MARGIN if total else 0


def _broken(ctx, value, width, size, *, bold=False, heading=False):
    """Whether a word of `value` is wider than `width` at `size`: a viewer would break it mid-word."""
    single = height(ctx, 'x', width, size, bold=bold, heading=heading)
    return any(height(ctx, word, width, size, bold=bold, heading=heading) > single + 1e-6
               for word in str(value or '').split())


def _whole(ctx, width, paragraphs):
    """Whether every word of `paragraphs` sets on a line `width` wide at its paragraph's size."""
    return not any(_broken(ctx, p['text'], width, p['size'], bold=p.get('bold', False),
                           heading=p.get('heading', False)) for p in _clipped(paragraphs))


def _hold(ctx, width, room, stories):
    """Whether every story sets `width` wide within `room` inches with no word broken."""
    return all(_whole(ctx, width, story) and _tall(ctx, width, story) <= room for story in stories)


def _pick(ctx, test):
    """The largest (name, sentence) sizes `test` accepts.

    When even the smallest is refused, a word would be broken or the text cut:
    the slide is marked, so this variant is passed over for it (variants.choose).
    """
    for label, body in SCALES:
        if test(label, body):
            return label, body
    ctx.shortened = True
    return SCALES[-1]


def _one_line(ctx, values, width, sizes):
    """The largest size in `sizes` at which every value sets on one line `width` wide (heading face, bold);
    None when none does."""
    for size in sizes:
        single = height(ctx, 'x', width, size, bold=True, heading=True)
        if all(height(ctx, value, width, size, bold=True, heading=True) <= single + 1e-6 for value in values if value):
            return size
    return None


def _date_size(ctx, events, width, start, floor=14):
    """One size for every date of the slide: the largest from `start` to `floor` that keeps each on one line.

    Below that a date may wrap, at `floor`, but a word of it that would break marks the slide.
    """
    values = [_plain(item.get('value'), DATE) for item in events]
    size = _one_line(ctx, values, width, range(start, floor - 1, -1))
    if size is None:
        size = floor
        if any(_broken(ctx, value, width, size, bold=True, heading=True) for value in values):
            ctx.shortened = True
    return size


def _date_tall(ctx, events, width, size):
    """Inches the tallest date of the slide takes `width` wide at `size` (heading face, bold), with the spare."""
    return max([height(ctx, _plain(item.get('value'), DATE), width, size, bold=True, heading=True)
                for item in events if _plain(item.get('value'), DATE)] or [0]) + MARGIN


def _span(ctx, values, size, most):
    """The narrowest width up to `most` that sets every value on one line at `size` (heading face, bold);
    `most` when one of them wraps there anyway."""
    if _one_line(ctx, values, most, (size,)) is None:
        return most
    low, high = 0.2, most
    while high - low > 0.02:
        middle = (low + high) / 2
        if _one_line(ctx, values, middle, (size,)) is None:
            low = middle
        else:
            high = middle
    return min(most, high + 0.04)


def _side_heading(ctx, section, x, width, centre, paint):
    """The eyebrow at the top of a panel; the rule and heading, in the panel's inks, centred on `centre`."""
    eyebrow(ctx, (x, 0.92, width, 0.3), colour=paint['muted'])
    value = _plain(section.get('heading'), 14)
    size = 30

    def poor(points):
        # Too tall, or a word wider than the panel: a viewer would break it mid-word.
        return (height(ctx, value, width, points, heading=True, spacing=1.08) > min(6 * points * 1.08 / 72, 4.2)
                or _broken(ctx, value, width, points, heading=True))
    while size > 18 and poor(size):
        size -= 2
    if _broken(ctx, value, width, size, heading=True):
        ctx.shortened = True
    tall = min(4.2, height(ctx, value, width, size, heading=True, spacing=1.08) + 0.1)
    y = min(max(1.62, centre - tall / 2), FOOT - 0.3 - tall)
    rule(ctx, (x, y - 0.3, 0.9, 3 / 72), paint['accent'])
    headline(ctx, section, (x, y, width, tall), size=size, lines=6, anchor='middle', colour=paint['ink'])


# ---------------------------------------------------------------- diamonds


@variant('timeline', 'diamonds')
def diamonds(ctx, section, lines):
    """Diamonds on a thin line, the last one larger in the strong colour, each date above its diamond and the
    event's name and sentence below, ranged left."""
    top = header_center(ctx, section)
    events = entries('timeline', section)
    n = len(events)
    columns = split(LEFT, WIDTH, n, 0.3 if n > 4 else 0.6)
    width = columns[0][1]
    small, big, date_h = 0.34, 0.62, 0.5
    date = _date_size(ctx, events, width, 20)
    room = FOOT - top - date_h - 0.18 - big - 0.28
    label, body = _pick(ctx, lambda l, b: _hold(ctx, width, room, [_story(e, l, b) for e in events]))
    tall = max(_tall(ctx, width, _story(e, label, body)) for e in events)
    group = date_h + 0.18 + big + 0.28 + tall
    y = top + max(0.0, (FOOT - top - group) / 2 - 0.15)
    mid = y + date_h + 0.18 + big / 2
    last = columns[-1][0] + big / 2
    rect(ctx, (LEFT, mid - 0.018, last - LEFT, 0.036), 'accent_soft')
    fill = strong(ctx)
    for position, (item, (x, w)) in enumerate(zip(events, columns)):
        final = position == n - 1
        size = big if final else small
        polygon(ctx, diamond_points((x, mid - size / 2, size, size)), fill if final else 'accent')
        if final:
            inner = 0.2
            polygon(ctx, diamond_points((x + (big - inner) / 2, mid - inner / 2, inner, inner)), 'surface')
        text(ctx, (x, y, w, date_h), item.get('value'), size=date, floor=date,
             colour='ink' if final else 'accent_text', bold=True, heading=True, anchor='bottom', words=DATE)
        block(ctx, (x, mid + big / 2 + 0.28, w, tall), _story(item, label, body))


# ---------------------------------------------------------------- vertical


@variant('timeline', 'vertical')
def vertical(ctx, section, lines):
    """A full-height panel in the strong colour holds the heading; beside it a vertical line with a ring per event,
    each date beside its ring and the event's name and sentence to the right."""
    events = entries('timeline', section)
    n = len(events)
    # The deep colour on a light deck, the accent on a dark one, beside rings and dates in the accent's text colour.
    fill = strong(ctx, ('deep', 'accent'))
    paint = inks(fill)
    panel = 3.8
    rect(ctx, (LEFT, 0.62, panel, FOOT - 0.62), fill)
    spine = LEFT + panel + 0.6
    date_x, date_w = spine + 0.42, 1.5
    # A long date ('Early spring 2021') wraps at 16 pt rather than shrink to 14 pt under its 17 pt event name.
    date = _date_size(ctx, events, date_w, 18, floor=16)
    # The date column is as wide as its widest date, so a plain year does not leave an inch of air before its
    # event; a date that wraps keeps the whole column.
    date_w = _span(ctx, [_plain(item.get('value'), DATE) for item in events], date, date_w)
    dates = _date_tall(ctx, events, date_w, date)
    story_x = date_x + date_w + 0.32
    story_w = RIGHT - story_x
    gap, room = 0.2, FOOT - 0.62 - 0.1

    def tallest(l, b):
        return max([_tall(ctx, story_w, _story(e, l, b)) for e in events] + [dates])
    label, body = _pick(ctx, lambda l, b: (_hold(ctx, story_w, room, [_story(e, l, b) for e in events])
                                           and n * (tallest(l, b) + gap) - gap <= room))
    row = max(tallest(label, body) + gap, min(1.25, (room + gap) / n))
    used = n * row - gap
    y0 = 0.62 + (FOOT - 0.62 - used) / 2
    _side_heading(ctx, section, LEFT + 0.38, panel - 0.76, (0.62 + FOOT) / 2, paint)
    dot = 0.26
    first, final = y0 + 0.17, y0 + (n - 1) * row + 0.17
    line(ctx, (spine, first), (spine, final), 'accent_soft', 2.25)
    for position, item in enumerate(events):
        y = y0 + position * row
        last = position == n - 1
        # In the dates' colour: a pale accent's thin ring all but vanished on a light ground.
        oval(ctx, disc(spine, y + 0.17, dot), 'accent_text' if last else 'surface', line='accent_text',
             line_width=2.25)
        text(ctx, (date_x, y, date_w, row - gap), item.get('value'), size=date, floor=date, colour='accent_text',
             bold=True, heading=True, words=DATE)
        block(ctx, (story_x, y + 0.01, story_w, row - gap), _story(item, label, body))


# ---------------------------------------------------------------- alternating


@variant('timeline', 'alternating')
def alternating(ctx, section, lines):
    """A line across the middle of the body with events alternating above and below it, each a pole up or down
    from its dot with the date, name and sentence beside it, the events above in the accent and those below in
    the second colour."""
    top = header_compact(ctx, section)
    events = entries('timeline', section)
    n = len(events)
    gap, dot = 0.3, 0.22
    pad = dot / 2 + 0.2
    width = min(3.9, 2 * (WIDTH + gap) / (n + 1) - gap) if n > 1 else WIDTH
    step = (WIDTH - width) / (n - 1) if n > 1 else 0
    middle = (top + FOOT) / 2 + 0.02
    stem = 0.3
    room = min(middle - stem - top - 0.08, FOOT - middle - stem)
    inner = width - pad
    label, body = _pick(ctx, lambda l, b: _hold(ctx, inner, room, [_story(e, l, b, date=19) for e in events]))
    # Two colours, one a side: a hue per event made six-event slides a rainbow. The pole, dot and date take the
    # colour made to read on the slide, so a pale accent still draws a visible pole.
    pair = hues(ctx, 2)
    rect(ctx, (LEFT, middle - 0.025, WIDTH, 0.05), 'accent_soft')
    for position, item in enumerate(events):
        x = LEFT + position * step
        above = position % 2 == 0
        colour = pair[0 if above else 1]['text']
        story = _story(item, label, body, date=19, accent=colour)
        tall = _tall(ctx, inner, story)
        y = middle - stem - tall if above else middle + stem
        pole = x + dot / 2
        line(ctx, (pole, middle), (pole, y if above else y + tall), colour, 2.5)
        oval(ctx, disc(pole, middle, dot), colour)
        block(ctx, (x + pad, y, inner, tall), story, anchor='bottom' if above else 'top')


# ---------------------------------------------------------------- year blocks


@variant('timeline', 'year_blocks')
def year_blocks(ctx, section, lines):
    """The dates set large on a tall continuous ribbon of blocks in the deck's two colours, ending in a point, and
    under each block a rule in its colour beside the event's name and sentence."""
    # The compact top, not the number header: timeline_2's pill_dates already pairs that with a row of dates.
    top = header_compact(ctx, section)
    events = entries('timeline', section)
    n = len(events)
    spans = split(LEFT, WIDTH, n, 0)
    pad, tip = 0.2, 0.4
    # Two colours taking turns: six hues round the wheel made every ribbon a rainbow, whatever the deck.
    pair = hues(ctx, 2)
    paints = [pair[position % 2] for position in range(n)]
    inner = spans[0][1] - pad - 0.14
    date = _date_size(ctx, events, spans[-1][1] - pad - tip - 0.08, 30)
    # The ribbon is as tall as its dates need, with even air above and below them: a date set small (six
    # columns, 'Q3 2021') does not float in a band cut for one set large.
    band = max(0.68, date * 1.15 / 72 + 0.4)
    room = FOOT - top - 0.2 - band - 0.28
    label, body = _pick(ctx, lambda l, b: _hold(ctx, inner, room, [_story(e, l, b) for e in events]))
    tall = max(_tall(ctx, inner, _story(e, label, body)) for e in events)
    group = band + 0.28 + tall
    y = top + 0.2 + max(0.0, (FOOT - top - 0.2 - group) * 0.4)
    for position, (item, paint, (x, w)) in enumerate(zip(events, paints, spans)):
        last = position == n - 1
        if last:
            polygon(ctx, chevron_points((x, y, w, band), tip, notch=False), paint['fill'])
        else:
            rect(ctx, (x, y, w + 0.01, band), paint['fill'])
        text(ctx, (x + pad, y + 0.08, w - pad - (tip + 0.08 if last else 0.12), band - 0.16), item.get('value'),
             size=date, floor=date, colour=paint['ink'], bold=True, heading=True, anchor='middle', words=DATE)
        # Every rule runs to the tallest story's foot, so the columns end on one line.
        rect(ctx, (x, y + band, 0.05, 0.28 + tall), paint['fill'])
        block(ctx, (x + pad, y + band + 0.28, inner, tall), _story(item, label, body))


# ---------------------------------------------------------------- road arrow


# Six slots between the notch and the head leave 1.45 in of story each: a long Russian name
# ('Региональные') is wider than that even at 14 pt bold, so five is the most it draws.
@variant('timeline', 'road_arrow', counts=(3, 5))
def road_arrow(ctx, section, lines):
    """Under a centred heading, a thick notched arrow along the foot of the body in the strong colour, the dates in
    its shaft between road dashes, and a pointer up from each to the event's name and sentence standing above it."""
    # Centred, like its stories: timeline_2's deep_band already sets a strong band of dates under the classic top.
    top = header_center(ctx, section)
    events = entries('timeline', section)
    n = len(events)
    fill = strong(ctx)
    paint = inks(fill)
    tall_arrow, shaft = 1.12, 0.62
    head = 0.82 if n < 5 else 0.7
    lane = tall_arrow * shaft
    notch, link = 0.24, 0.2
    slots = split(LEFT + notch + 0.06, WIDTH - head - notch - 0.16, n, 0)
    inner = slots[0][1] - 0.3
    room = FOOT - top - tall_arrow - link
    date = _date_size(ctx, events, slots[0][1] - 0.28, 19)

    def story(item, l, b):
        return _story(item, l, b, align='center')
    label, body = _pick(ctx, lambda l, b: _hold(ctx, inner, room, [story(e, l, b) for e in events]))
    tall = max(_tall(ctx, inner, story(e, label, body)) for e in events)
    group = tall + link + tall_arrow
    y = top + max(0.0, (FOOT - top - group) / 2)
    road = y + tall + link
    polygon(ctx, arrow_points((LEFT, road, WIDTH, tall_arrow), head=head, shaft=shaft)
            + [(LEFT + notch, road + tall_arrow / 2)], fill)
    lane_top = road + tall_arrow * (1 - shaft) / 2
    lane_mid = lane_top + lane / 2
    for position, (item, (x, w)) in enumerate(zip(events, slots)):
        centre = x + w / 2
        if position:
            rect(ctx, (x - 0.13, lane_mid - 0.025, 0.26, 0.05), paint['muted'])
        text(ctx, (x + 0.14, lane_top + 0.08, w - 0.28, lane - 0.16), item.get('value'), size=date, floor=date,
             colour=paint['ink'], bold=True, heading=True, align='center', anchor='middle', words=DATE)
        polygon(ctx, triangle_points((centre - 0.17, lane_top - 0.19, 0.34, 0.2), 'up'), fill)
        block(ctx, (x + 0.15, y, inner, tall), story(item, label, body), anchor='bottom')


# ---------------------------------------------------------------- big years


def _kicker(value):
    """A date's leading words and its last ('Q3', '2021'); ('', date) for a one-word date."""
    words = value.split()
    return (' '.join(words[:-1]), words[-1]) if len(words) > 1 else ('', value)


@variant('timeline', 'big_years')
def big_years(ctx, section, lines):
    """The heading on a soft band and, with no line, each date set large in the accent as a column head over a
    thin rule, the event's name and sentence beneath."""
    top = header_band(ctx, section, fill='accent_soft', height=1.55, size=30)
    events = entries('timeline', section)
    n = len(events)
    columns = split(LEFT, WIDTH, n, 0.4 if n > 4 else 0.6)
    width = columns[0][1]
    values = [clip(ctx, item.get('value'), DATE) for item in events]
    sizes = range(66, 23, -2)
    whole = _one_line(ctx, values, width, sizes)
    parts = [_kicker(value) for value in values]
    kick = 15
    # 'Q3 2021' on one line held every date to about 26 pt at six columns: its leading words go small above the
    # year instead, so the years stay large, when that is what keeps them large.
    split_size = None
    if any(lead for lead, _ in parts) and (whole is None or whole < 44):
        split_size = _one_line(ctx, [last for _, last in parts], width, sizes)
        if split_size is not None and (_one_line(ctx, [lead for lead, _ in parts], width, (kick,)) is None
                                       or split_size < (whole or 0) + 10):
            split_size = None
    if split_size is not None:
        size, heads, kick_h = split_size, parts, kick * 1.15 / 72 + MARGIN + 0.03
    else:
        size, heads, kick_h = whole or sizes[-1], [('', value) for value in values], 0
        if whole is None and any(_broken(ctx, value, width, size, bold=True, heading=True) for value in values):
            ctx.shortened = True
    year_h = max(height(ctx, last or 'x', width, size, heading=True, spacing=1.1) for _, last in heads) + MARGIN
    head_h = kick_h + year_h
    room = FOOT - top - head_h - 0.42
    label, body = _pick(ctx, lambda l, b: _hold(ctx, width, room, [_story(e, l, b) for e in events]))
    tall = max(_tall(ctx, width, _story(e, label, body)) for e in events)
    group = head_h + 0.42 + tall
    y = top + max(0.0, (FOOT - top - group) * 0.4)
    for item, (lead, last), (x, w) in zip(events, heads, columns):
        if lead:
            text(ctx, (x, y, w, kick_h), lead, size=kick, floor=kick, colour='muted', bold=True, heading=True,
                 anchor='bottom')
        text(ctx, (x, y + kick_h, w, year_h), last, size=size, floor=size, colour='accent_text', heading=True,
             anchor='bottom', spacing=1.1)
        rect(ctx, (x, y + head_h + 0.12, w, 0.025), 'muted')
        block(ctx, (x, y + head_h + 0.42, w, tall), _story(item, label, body))


# ---------------------------------------------------------------- centre spine


@variant('timeline', 'centre_spine')
def centre_spine(ctx, section, lines):
    """A spine down the centre with a ring per event and the events alternating left and right of it, joined by
    short ticks, each with its date, name and sentence."""
    eyebrow(ctx, (LEFT, 0.62, WIDTH, 0.3), align='center')
    headline(ctx, section, (LEFT + 1.0, 0.9, WIDTH - 2.0, 0.98), size=28, lines=2, align='center')
    events = entries('timeline', section)
    n = len(events)
    centre = LEFT + WIDTH / 2
    reach = 0.5
    width = WIDTH / 2 - reach
    top, bottom, gap = 2.22, FOOT - 0.04, 0.16

    def story(position, item, l, b):
        return _story(item, l, b, date=17, align='right' if position % 2 == 0 else 'left', gap=3)

    def tallest(l, b):
        return max(_tall(ctx, width, story(k, e, l, b)) for k, e in enumerate(events))

    def span(tall):
        return (n - 1) * (tall + gap) / 2 + tall if n > 1 else tall
    label, body = _pick(ctx, lambda l, b: (_hold(ctx, width, bottom - top,
                                                 [story(k, e, l, b) for k, e in enumerate(events)])
                                           and span(tallest(l, b)) <= bottom - top))
    tall = tallest(label, body)
    step = max((tall + gap) / 2, min(1.0, (bottom - top - tall) / max(1, n - 1)))
    used = (n - 1) * step + tall
    y0 = top + max(0.0, (bottom - top - used) / 2)
    first, final = y0 + 0.15, y0 + (n - 1) * step + 0.15
    # The spine starts at the first ring, clear of the heading above it, and runs on a little past the last.
    start, end = first, min(bottom, final + 0.3)
    rect(ctx, (centre - 0.02, start, 0.04, end - start), 'accent_soft')
    for position, item in enumerate(events):
        y = y0 + position * step
        left = position % 2 == 0
        # Rings and ticks in the dates' colour: a pale accent's thin outline all but vanished on a light ground.
        oval(ctx, disc(centre, y + 0.15, 0.24), 'surface', line='accent_text', line_width=2.5)
        tick = (centre - reach + 0.1, centre - 0.18) if left else (centre + 0.18, centre + reach - 0.1)
        line(ctx, (tick[0], y + 0.15), (tick[1], y + 0.15), 'accent_text', 1.5)
        x = LEFT if left else centre + reach
        block(ctx, (x, y, width, tall), story(position, item, label, body))
