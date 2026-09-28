"""The slide layouts a deck can use, and when each one is allowed to be used.

This is the single source of truth: the model's schema enum, the guide it is
given, the validation of what it returns, and the fallback when it chose a
layout its content cannot fill all come from here. It is pure data and pure
functions — no pptx, no network — so the provider, the domain and the renderer
can all import it without cost.

The model chooses a layout; this module decides whether that choice holds. A
`stats` slide whose values are not numbers, a `chart` with one bar, a `quote`
nobody said — each falls back along a fixed chain to a layout that can carry the
content. That is never a customer warning: the model misusing a layout is our
problem, not theirs.
"""
import math
import re
import unicodedata

# A storage-only value: "draw it the way decks were drawn before layouts were
# chosen". Legacy drafts, locally authored ones, revision padding and appended
# question slides stay `auto`, so every deck that rendered before still does.
AUTO = 'auto'

MAX_ITEMS = 8
MAX_COLUMNS = 3
LIMITS = {'label': 160, 'text': 600, 'value': 160}
PRO = {'pro', '+', 'for', 'yes', 'plus', 'upside'}
CON = {'con', '-', '–', 'against', 'no', 'minus', 'downside'}


class Layout:
    __slots__ = ('id', 'group', 'needs_photo', 'fallback', 'guide')

    def __init__(self, id, group, fallback, guide, needs_photo=False):
        self.id, self.group, self.fallback = id, group, fallback
        self.guide, self.needs_photo = guide, needs_photo


# Order matters only for the guide the model reads. `fallback` names the next
# layout to try when this one cannot hold the content; every chain ends in
# `section`, which always accepts.
CATALOGUE = {layout.id: layout for layout in (
    Layout('cover', 'text', 'section',
           'title slide: heading is the deck title, body one subtitle line; image_query optional'),
    Layout('agenda', 'structure', 'bullets',
           "what's coming: 3-6 items, label = topic, text optional"),
    Layout('section', 'text', 'section',
           'divider between parts: heading only, body an optional one-line kicker'),
    Layout('bullets', 'text', 'section',
           'a list: body is 3-5 lines, one idea each'),
    Layout('two_column', 'text', 'bullets',
           'two ideas side by side: exactly 2 items, label = column title, text = up to 35 words'),
    Layout('statement', 'text', 'bullets',
           'one idea set large: body is a single sentence of at most 20 words'),
    Layout('quote', 'text', 'statement',
           'a real or sourced quotation: body = the quote, items[0] label = who said it, text = role or source'),
    Layout('big_number', 'data', 'statement',
           'one statistic: items[0] value = the figure (e.g. 118%), label = what it measures, text = context'),
    Layout('stats', 'data', 'bullets',
           '2-4 figures: items with value = figure, label = what it measures'),
    Layout('timeline', 'structure', 'bullets',
           '3-6 dated events: items with value = date or period, label = event, text optional'),
    Layout('process', 'structure', 'bullets',
           '3-5 steps in order: items with label = step, text = one line'),
    Layout('comparison', 'data', 'table',
           'A versus B: columns = [A, B], items with label = criterion, text = A, value = B'),
    Layout('pros_cons', 'structure', 'two_column',
           'for and against: items with label = the point, value exactly "pro" or "con"'),
    Layout('cards', 'structure', 'bullets',
           '3-6 features or options: items with label = name, text = one line, value optional tag'),
    Layout('matrix', 'structure', 'cards',
           'a 2x2 grid such as SWOT: exactly 4 items with label and text; columns optional axis names'),
    Layout('chart', 'data', 'table',
           'compare quantities: 2-8 items with label = category, value = a number; columns[0] optional unit'),
    Layout('table', 'data', 'bullets',
           'a small grid: columns = 2-3 headers, 2-6 items whose label, text, value are the cells'),
    Layout('image_split', 'photo', 'bullets',
           'a photo beside 2-4 points: body lines + image_query', needs_photo=True),
    Layout('image_full', 'photo', 'statement',
           'a full-width photo with a caption: body = caption + image_query', needs_photo=True),
    Layout('closing', 'text', 'section',
           'the last slide: thanks, next step or questions; heading + one line'),
)}
LAYOUT_IDS = list(CATALOGUE)
PHOTO_LAYOUTS = [layout.id for layout in CATALOGUE.values() if layout.needs_photo]


# ---------------------------------------------------------------- values


def parse_number(value):
    """The first number in a figure such as "1,200", "3.5k", "$4.2m" or "18%".

    A comma followed by exactly three digits is a thousands separator; any other
    comma is a decimal point, which is how Russian and Uzbek write them.
    """
    text = unicodedata.normalize('NFKC', str(value or '')).replace(' ', ' ').replace('\xa0', ' ')
    match = re.search(r'(-?\d[\d ,.]*)\s*([kKmMbB]|тыс|млн|млрд|ming|mln|mlrd)?', text)
    if not match:
        return None
    raw, suffix = match.group(1).strip(' ,.'), (match.group(2) or '').lower()
    raw = re.sub(r'(?<=\d)[ ,](?=\d{3}(?!\d))', '', raw).replace(' ', '')
    raw = raw.replace(',', '.')
    if raw.count('.') > 1:
        head, _, tail = raw.rpartition('.')
        raw = head.replace('.', '') + '.' + tail
    try:
        number = float(raw)
    except ValueError:
        return None
    number *= {'k': 1e3, 'тыс': 1e3, 'ming': 1e3, 'm': 1e6, 'млн': 1e6, 'mln': 1e6,
               'b': 1e9, 'млрд': 1e9, 'mlrd': 1e9}.get(suffix, 1)
    return number if math.isfinite(number) else None


def has_digit(value):
    return bool(re.search(r'\d', str(value or '')))


def clean_query(text):
    """A stock-photo search: a few lower-case English words and nothing else.

    What leaves the platform for the photo provider is this, never the
    customer's own wording — so it is reduced to plain words, capped, and
    anything that is not a word is dropped.
    """
    folded = unicodedata.normalize('NFKC', str(text or '')).lower()
    words = re.sub(r"[^a-z0-9 '\-]", ' ', folded).split()
    return ' '.join(words[:5])[:100]


def _item(value):
    if not isinstance(value, dict):
        raise ValueError('item')
    return {key: str(value.get(key, '') or '').strip()[:limit] for key, limit in LIMITS.items()}


def clean_slide_fields(section):
    """Layout, items, columns and photo subject of a slide, bounded.

    Raises ValueError on a shape no model can produce under the schema, so a
    malformed client request is refused rather than quietly repaired.
    """
    layout = str(section.get('layout') or AUTO)
    if layout != AUTO and layout not in CATALOGUE:
        raise ValueError('layout')
    items = section.get('items') or []
    columns = section.get('columns') or []
    if not isinstance(items, list) or not isinstance(columns, list):
        raise ValueError('shape')
    items = [item for item in (_item(value) for value in items) if any(item.values())][:MAX_ITEMS]
    columns = [str(column or '').strip()[:80] for column in columns[:MAX_COLUMNS]]
    columns = columns if any(columns) else []
    return {'layout': layout, 'items': items, 'columns': columns,
            'image_query': clean_query(section.get('image_query', ''))}


def as_lines(section):
    """A layout's items as plain lines, for when it falls back to a list."""
    lines = []
    for item in section.get('items') or []:
        label, text, value = item.get('label', ''), item.get('text', ''), item.get('value', '')
        head = ' — '.join(part for part in (value, label) if part)
        lines.append(f'{head}: {text}' if head and text else head or text)
    return [line for line in lines if line]


# ---------------------------------------------------------------- choice


def _labelled(items):
    return [item for item in items if item.get('label')]


def accepts(kind, section, lines, index, total, has_photo):
    """Whether this layout can carry this slide's content."""
    items = section.get('items') or []
    columns = [column for column in section.get('columns') or [] if column]
    if kind == 'cover':
        return index == 0 and total >= 2
    if kind in ('section', 'closing'):
        return True
    if kind == 'bullets':
        return bool(lines or items)
    if kind == 'agenda':
        return 3 <= len(_labelled(items)) <= 6
    if kind == 'two_column':
        titled = [item for item in items if item.get('label') and item.get('text')]
        return len(titled) == 2 or len(lines) >= 2
    if kind == 'statement':
        return len(lines) == 1 and len(lines[0]) <= 120
    if kind == 'quote':
        body = ' '.join(lines)
        return bool(body) and len(body.split()) <= 45 and bool(items and items[0].get('label'))
    if kind == 'big_number':
        return bool(items) and has_digit(items[0].get('value')) and len(items[0]['value']) <= 12
    if kind == 'stats':
        return 2 <= len(items) <= 4 and all(has_digit(item.get('value')) for item in items)
    if kind == 'timeline':
        return 3 <= len(items) <= 6 and all(item.get('value') and item.get('label') for item in items)
    if kind == 'process':
        return 3 <= len(_labelled(items)) <= 5
    if kind == 'comparison':
        return len(columns) >= 2 and len(_labelled(items)) >= 2
    if kind == 'pros_cons':
        values = [item.get('value', '').strip().lower() for item in items]
        return any(value in PRO for value in values) and any(value in CON for value in values)
    if kind == 'cards':
        return 3 <= len(_labelled(items)) <= 6
    if kind == 'matrix':
        return len(_labelled(items)) == 4
    if kind == 'chart':
        numbers = [parse_number(item.get('value')) for item in items]
        return (2 <= len(items) <= 8 and all(n is not None and n >= 0 for n in numbers)
                and max(numbers) > 0)
    if kind == 'table':
        return 2 <= len(columns) <= 3 and 2 <= len(items) <= 6
    if kind in PHOTO_LAYOUTS:
        return has_photo and (kind == 'image_full' or bool(lines or items))
    return False


def legacy(index, lines, total):
    """How a slide was laid out before the model chose: what `auto` still means."""
    if index == 0 and total >= 2:
        return 'cover'
    if not lines:
        return 'section'
    if len(lines) == 1 and len(lines[0]) <= 90:
        return 'statement'
    if len(lines) >= 5:
        return 'two_column'
    return 'bullets'


def resolve(section, lines, index, total, has_photo=False):
    """The layout this slide is drawn with: its own choice if it holds, else a fallback.

    The first slide of a multi-slide deck is always its cover, whatever was
    chosen, because the count the customer asked for includes it.
    """
    if index == 0 and total >= 2:
        return 'cover'
    wanted = section.get('layout') or AUTO
    if wanted == AUTO or wanted not in CATALOGUE:
        return legacy(index, lines, total)
    kind, seen = wanted, set()
    while kind not in seen:
        seen.add(kind)
        if accepts(kind, section, lines, index, total, has_photo):
            return kind
        kind = CATALOGUE[kind].fallback
    return 'section'


def guide(photos=0):
    """What the model is told about layouts. Kept short: it is sent on every call."""
    lines = [f'- {layout.id}: {layout.guide}' for layout in CATALOGUE.values()
             if photos or not layout.needs_photo]
    photo_rule = (f'Use {photos} photo layout{"s" if photos != 1 else ""} in this part: image_split or '
                  f'image_full on slides a picture supports, and the cover counts when it has an '
                  f'image_query. Use fewer only if the description asks for fewer or no photos. '
                  f'image_query is 2-4 generic words in English, even when the deck is in another '
                  f'language, for a stock photo; never a person, brand or company name. '
                  if photos else
                  'Do not use image_split or image_full, and leave image_query empty. ')
    return ('Choose a layout for every section from this list:\n' + '\n'.join(lines) + '\n'
            'Vary the layouts to suit the content: never the same one more than twice in a row, and '
            'bullets on at most a third of the slides. Fill only the fields the layout uses and leave '
            'the others empty ("" or []). Never invent figures, dates or quotations: use numbers only '
            'when the description or the sources give them, and quote only a real or sourced '
            'quotation. ' + photo_rule)
