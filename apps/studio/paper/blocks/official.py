"""The official and letter family's own block (architecture 6.6, blocks.json, package R4): split_row.

Everything else the ariza, the explanatory note, the character reference, the
recommendation (official form and English letter), the cover letter and the
motivation letter print is a core block. What the letters add is the row under
a letterhead that holds two small blocks side by side: the addressee on the
left and the date on the right (a letter), or the date and the outgoing number
on the left and the addressee in the right half (an official letter).

    {"block": "split_row", "fields": [...every field either side prints...],
     "params": {"left": <flow entry or [entries]>, "right": <...>, "left_mm": 104}}

A side is a flow entry as a template writes one: `block`, optional `fields`,
`part`, `when` and `params`; any other key is a parameter of that block, so
`{"block": "date_line", "fact": "letter_date", "align": "right"}` reads as the
template's own date_line. A list stacks its entries in the cell, each kept
only when its `when` holds (the outgoing number under the date, only when
there is one).

Each side is drawn by its own block at the cell's width, so a party column
wraps in its cell and a right-aligned date sits flush with the frame's right
edge; a right_half anchor means the right cell itself, which already starts
there. A side that has nothing to print leaves its cell empty; with both empty
the row draws nothing.
"""
from reportlab.platypus import Table, TableStyle

from ..ctx import Place, holds
from ..registry import block, draw
from ..text import MM
from .core import Gap, _finish, _num, _params, _space_before

# The air kept clear at the right of the left cell, so its longest line never touches the right one.
GUTTER_MM = 4.0
# How narrow either cell may be, as a share of the frame: a template's left_mm is clamped to this.
NARROWEST = 0.25
# The keys of a side that are not its block's parameters.
ENTRY_KEYS = ('block', 'fields', 'part', 'when', 'params')


def _entries(spec):
    """A side as a list of flow entries: one entry, or a list of them; anything else is nothing."""
    if isinstance(spec, dict):
        return [spec]
    if isinstance(spec, list):
        return [item for item in spec if isinstance(item, dict)]
    return []


def _sub_place(ctx, place, entry, index):
    """A side's entry as the Place its block is given: its own fields, part and parameters."""
    params = dict(entry['params']) if isinstance(entry.get('params'), dict) else {}
    params.update({key: value for key, value in entry.items() if key not in ENTRY_KEYS})
    if params.get('anchor') == 'right_half':
        # The right cell already starts at the half: anchoring again would push the column off its cell.
        params['anchor'] = 'left'
    part = ctx.entry.part(entry['part']) if isinstance(entry.get('part'), str) else None
    section = ctx.section(part['id'], place.instance) if part else None
    fields = tuple(field_id for field_id in entry.get('fields') or () if isinstance(field_id, str))
    return Place(str(entry.get('block') or ''), section, part, fields, params, place.instance,
                 place.index * 100 + index, place.group, entry.get('when'))


def _trimmed(flowables):
    """A cell's flowables without the gaps a block puts around itself: a table cell keeps every point of them."""
    made = [flowable for flowable in flowables if flowable is not None]
    while made and isinstance(made[-1], Gap):
        made.pop()
    while made and isinstance(made[0], Gap):
        made.pop(0)
    if made:
        _space_before(made, 0.0)
    return made


def _side(ctx, place, spec, width):
    """The flowables of one side drawn at `width` points: each entry whose `when` holds, stacked."""
    made = []
    kept = ctx.width
    try:
        ctx.width = width
        for index, entry in enumerate(_entries(spec)):
            sub = _sub_place(ctx, place, entry, index)
            if not sub.block or not holds(sub.when, ctx, sub):
                continue
            made += _trimmed(draw(ctx, sub))
    finally:
        ctx.width = kept
    return made


def widths(ctx, params):
    """(left, right) cell widths in points: left_mm clamped so neither cell is narrower than a quarter."""
    left = _num(params.get('left_mm'), 0.0, 0, 400) * MM or ctx.width / 2
    left = min(max(left, ctx.width * NARROWEST), ctx.width * (1 - NARROWEST))
    return left, ctx.width - left


def split_plain(ctx, place):
    """The two sides one after the other at the frame's width (blocks.json's plain fallback)."""
    params = _params(place)
    return _side(ctx, place, params.get('left'), ctx.width) + _side(ctx, place, params.get('right'), ctx.width)


def split_row(ctx, place):
    """Two small blocks on one row: `left` flush left in its cell, `right` in the cell after `left_mm`.

    params: left, right (a flow entry or a list of them, see the module's
    docstring); left_mm (the left cell's width; half the frame by default).
    """
    params = _params(place)
    left_width, right_width = widths(ctx, params)
    gutter = min(GUTTER_MM * MM, left_width * 0.1)
    left = _side(ctx, place, params.get('left'), left_width - gutter)
    right = _side(ctx, place, params.get('right'), right_width)
    if not left and not right:
        return []
    drawn = Table([[left or '', right or '']], colWidths=[left_width, right_width], hAlign='LEFT')
    drawn.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0),
                               ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (0, 0), gutter),
                               ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
    return _finish(place, [drawn], before=ctx.leading * 0.5, after=ctx.leading * 0.5)


block('split_row', fallback=split_plain)(split_row)


# ---------------------------------------------------------------- samples


def _text3(uz, ru, en):
    return {'uz': uz, 'ru': ru, 'en': en}


DATE = _text3('14.11.2026', '14.11.2026', '14 November 2026')
ADDRESSEE = _text3('Misol Texnologiya Universiteti magistratura qabul komissiyasiga',
                   'В приёмную комиссию магистратуры Университета «Мисол»',
                   'Master’s admissions committee, Misol University of Technology')

# One placement per variant, each on the template it is written for (its page, type and labels).
SAMPLES = [
    {'block': 'split_row', 'name': 'addressee left, date right (letter)', 'template': 'letter_tavsiya',
     'fields': ['addressee', 'letter_date'],
     'facts': {'addressee': ADDRESSEE, 'letter_date': DATE},
     'params': {'left': {'block': 'party_block', 'fields': ['addressee'], 'anchor': 'left', 'max_lines': 4},
                'right': {'block': 'date_line', 'fact': 'letter_date', 'align': 'right'}, 'left_mm': 104}},
    {'block': 'split_row', 'name': 'date and number left, addressee right (official)', 'template': 'tavsiya_rasmiy',
     'fields': ['letter_date', 'outgoing_number', 'addressee'],
     'facts': {'addressee': ADDRESSEE, 'letter_date': DATE, 'outgoing_number': _text3('118', '118', '118')},
     'params': {'left': [{'block': 'date_line', 'fact': 'letter_date', 'pattern': 'date_blank'},
                         {'block': 'line', 'text': 'number', 'when': 'fact:outgoing_number'}],
                'right': {'block': 'party_block', 'fields': ['addressee'], 'anchor': 'right_half', 'max_lines': 4},
                'left_mm': 82.5}},
    {'block': 'split_row', 'name': 'date alone, flush right (no addressee)', 'template': 'letter_cover',
     'fields': ['recipient_person', 'employer_name', 'date_written'],
     'facts': {'date_written': DATE},
     'params': {'left': {'block': 'party_block', 'fields': ['recipient_person', 'employer_name'], 'anchor': 'left'},
                'right': {'block': 'date_line', 'fact': 'date_written', 'align': 'right'}, 'left_mm': 104}},
]
