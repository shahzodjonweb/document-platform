"""The business family's own blocks (architecture 6.6, blocks.json, package R5a): letterhead, key_figures, card_grid.

An offer, a report, a business plan and a marketing plan are drawn with the
core blocks (their tables, headings and signatures) and the academic cover and
contents; what they add is theirs alone:

- `letterhead`: the seller at the top of an offer's first page, its name at
  the left and its contacts at the right over a rule. A name the customer did
  not give is a rule with a caption to write it on; a contact not given is
  left out, or a blank after its word when the field draws one.
- `key_figures`: one row of three or four boxed figures a banker or a head
  reads first, each a short label over a large figure. Only figures the
  customer gave or code computed: a field's value, a table's code-made total
  (never a partial one), or a table's rows (a report's indicators, a plan's
  goals) with the comparison figure the customer typed beside them. A table
  figure too wide for its box is left out, never shrunk; with fewer figures
  than the strip needs it draws nothing.
- `card_grid`: four titled cards in a two-by-two grid (SWOT). The list part's
  items name their card by a code (strengths, weaknesses, opportunities,
  threats) the template maps to its words; a card with no point keeps a rule
  to write one on.

Words follow core.py: every fixed word is a template label, every value the
verified one or a blank. Every block ends with a gap and draws nothing when it
has nothing to draw.
"""
import re

from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from ..ctx import INK
from ..registry import block
from ..text import MM
from .core import (TINT, Gap, Hair, _bold, _cells, _finish, _font, _has_label, _int, _items, _num, _params,
                   _shown, _sign_cell, _style, _word)

# A figure in a box: this many times the body size, bold; its unit after it in the small face.
FIGURE = 1.7
# The gap between two boxes of the strip, in mm.
BOX_GAP_MM = 4.0
# A figure as typed: the number (with its sign, its groups and a currency written before it: "$1,200", "UZS 36")
# and the words after it, set smaller ("420 mln so‘m").
FIGURE_SPLIT = re.compile(r'^\s*(?P<number>[+\-−]?(?:[$€£₽]|(?:UZS|USD|EUR|RUB)\s?)?\d[\d   .,]*%?)\s*(?P<rest>.*)$',
                          re.IGNORECASE)
# A total row the strip may read: derive's complete total, never one of only the items listed.
COMPLETE = True


# ---------------------------------------------------------------- letterhead


def _contact(ctx, field_id, labels):
    """A contact line: the value after its word ("Tel.: ..."), a blank after it when the field draws one, else None."""
    value = _shown(ctx, field_id)
    if value is None:
        return None
    key = labels.get(field_id) if isinstance(labels, dict) else None
    word = ctx.label(key) if key and _has_label(ctx, key) else ''
    return f'{word} {value}'.strip()


def letterhead(ctx, place):
    """The seller's name at the left and its contacts at the right of page 1, a rule under them.

    params: name (a field id; the placement's first field by default);
    contacts (field ids; the placement's other fields by default); labels
    ({field id: label key}: the word before a contact, "Tel.:"); captions
    ({field id: label key}: the caption under the name's rule when it is not
    given); rule (true: a rule across the frame under the head); name_mm (the
    name's column, 95 by default; the contacts take the rest, set flush right).
    """
    params = _params(place)
    fields = list(place.fields)
    name_id = params.get('name') if isinstance(params.get('name'), str) else (fields[0] if fields else None)
    contacts = params.get('contacts') if isinstance(params.get('contacts'), list) else [
        field_id for field_id in fields if field_id != name_id]
    labels = params.get('labels') if isinstance(params.get('labels'), dict) else {}
    captions = params.get('captions') if isinstance(params.get('captions'), dict) else {}
    name = ctx.fact(name_id) if name_id else None
    lines = [line for line in (_contact(ctx, field_id, labels) for field_id in contacts
                               if isinstance(field_id, str)) if line]
    blank = name is None and name_id is not None and ctx.blank(name_id)
    if name is None and not blank and not lines:
        return []
    left_width = min(_num(params.get('name_mm'), 95.0, 40, 160) * MM, ctx.width * 0.7) if lines else ctx.width
    right_width = ctx.width - left_width
    size = round(ctx.size * 1.3 * 2) / 2
    name_style = _style(ctx, 'bold', fontSize=size, leading=size * 1.22)
    if name is not None:
        left = [Paragraph(ctx.text(name, name_style), name_style)]
    elif blank:
        key = captions.get(name_id)
        caption = ctx.label(key) if key and _has_label(ctx, key) else ''
        left = _sign_cell(ctx, None, caption, min(left_width - 4 * MM, 80 * MM), ctx.leading * 1.2, TA_LEFT)
    else:
        left = ''
    small = _style(ctx, 'small', alignment=TA_RIGHT)
    right = [Paragraph(ctx.text(line, small), small) for line in lines]
    if right:
        drawn = Table([[left, right]], colWidths=[left_width, right_width], hAlign='LEFT')
    else:
        drawn = Table([[left]], colWidths=[ctx.width], hAlign='LEFT')
    drawn.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'BOTTOM'), ('LEFTPADDING', (0, 0), (-1, -1), 0),
                               ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (0, 0), 4 * MM),
                               ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
    made = [drawn]
    if params.get('rule', True):
        made.append(Hair(thickness=1.0, above=2.2 * MM, below=0))
    return _finish(place, made, after=ctx.leading * 1.2)


def _letterhead_plain(ctx, place):
    """The name and the contact lines, one under the other."""
    params = _params(place)
    labels = params.get('labels') if isinstance(params.get('labels'), dict) else {}
    made = []
    for number, field_id in enumerate(place.fields):
        line = _contact(ctx, field_id, labels if number else {})
        if line:
            style = ctx.styles['bold'] if number == 0 else ctx.styles['small']
            made.append(Paragraph(ctx.text(line, style), style))
    return made + [Gap(1, ctx.leading)] if made else []


block('letterhead', fallback=_letterhead_plain)(letterhead)


# ---------------------------------------------------------------- key_figures


def _complete_word(ctx, item):
    """A total row known by its word alone (validate_content keeps no `total` mark): never the items-listed one."""
    from apps.studio.categories.derive import NAMED, TOTAL_ROW
    label = ' '.join(str(item.get('label') or '').split())
    named = {NAMED[ctx.locale]} | ({ctx.label('total_named')} if _has_label(ctx, 'total_named') else set())
    return bool(TOTAL_ROW.match(label)) and label not in named


def _total_cell(ctx, part_id, column):
    """A table's complete total in `column` (derive's row), or None: a total of only the items listed is no figure."""
    part = ctx.entry.part(part_id)
    if not part:
        return None
    count = len(part.get('columns') or ()) or None
    for item in _items(ctx.section(part_id)):
        if (item.get('total') is COMPLETE or ('total' not in item and _complete_word(ctx, item))) and count:
            cells = _cells(item, count)
            return cells[column] if 0 <= column < len(cells) and cells[column].strip() else None
    return None


def _row_figures(ctx, params):
    """The figures a table's rows give: (label, figure, unit, note) for each row whose figure cell holds one."""
    part_id = params.get('from')
    part = ctx.entry.part(part_id) if isinstance(part_id, str) else None
    if not part or part.get('kind') != 'table':
        return []
    count = len(part.get('columns') or ()) or 1
    rows = [item for item in _items(ctx.section(part['id'])) if not item.get('total')]
    if len(rows) < _int(params.get('min_rows'), 1, 1, 40):
        return []
    value_column = _int(params.get('value_column'), count - 1, 0, count - 1)
    unit_column = params.get('unit_column')
    compare_column = params.get('compare_column')
    found = []
    for item in rows:
        cells = _cells(item, count)
        figure = cells[value_column].strip()
        if not figure or '_' in figure or not re.search(r'\d', figure):
            continue
        unit = cells[unit_column].strip() if isinstance(unit_column, int) and unit_column < count else ''
        note = ''
        if isinstance(compare_column, int) and compare_column < count and cells[compare_column].strip() \
                and _has_label(ctx, params.get('compare_label')):
            note = f"{ctx.label(params['compare_label'])} {cells[compare_column].strip()}"
        label = cells[0].strip()
        if label and _has_label(ctx, params.get('label_suffix')):
            label = f"{label}, {ctx.label(params['label_suffix'])}"
        found.append((label, figure, unit, note, True))
    return found


def _spec_figures(ctx, params):
    """The figures the placement names one by one: a field's value, or a table's complete total."""
    found = []
    for spec in params.get('figures') or ():
        if not isinstance(spec, dict):
            continue
        label = _word(ctx, spec.get('label')) if spec.get('label') else ''
        if isinstance(spec.get('field'), str):
            value = ctx.fact(spec['field'])
            if value:
                if not label:
                    label = re.sub(r'\s*\([^()]*\)\s*$', '', ctx.field_label(spec['field']))
                found.append((label, value, '', _word(ctx, spec.get('note')) if spec.get('note') else '', False))
        elif isinstance(spec.get('total'), str):
            value = _total_cell(ctx, spec['total'], _int(spec.get('column'), 1, 0, 40))
            if value:
                found.append((label, value, '', _word(ctx, spec.get('note')) if spec.get('note') else '', True))
    return found


def _figure_markup(ctx, figure, unit, style, small):
    """A figure's markup: the number large and bold, the words after it (its unit) small; None when it has no number."""
    found = FIGURE_SPLIT.match(figure)
    if not found:
        return None
    rest = ' '.join(piece for piece in (found.group('rest').strip(), unit) if piece)
    markup = ctx.text(found.group('number').strip(), style)
    if rest:
        markup += f' <font name="{small.fontName}" size="{small.fontSize}">{ctx.text(rest, small)}</font>'
    return markup


def _fits(ctx, figure, unit, style, small, width):
    found = FIGURE_SPLIT.match(figure)
    if not found:
        return False
    rest = ' '.join(piece for piece in (found.group('rest').strip(), unit) if piece)
    needed = stringWidth(ctx.plain(found.group('number').strip()), style.fontName, style.fontSize)
    if rest:
        needed += stringWidth(' ' + ctx.plain(rest), small.fontName, small.fontSize)
    return needed <= width


def key_figures(ctx, place):
    """A row of boxed figures: a rule on top, a short label, the figure large, a small note under it.

    params: figures ([{label: label key, field: field id} or {label, total:
    a table part id, column}]: a field's value, or the table's complete
    total in that column); from (a table part id: one figure per row, label
    the first cell, the figure from `value_column`, its unit from
    `unit_column`, a note from `compare_column` after the word
    `compare_label`, "reja 480"; `label_suffix` a word after the row's name,
    "Oylik buyurtmalar, maqsad"); min_rows (the table needs this many
    rows before it gives figures); boxes (4: the most figures, the named
    ones first); min (2: fewer figures draw nothing).
    """
    params = _params(place)
    figures = _spec_figures(ctx, params) + _row_figures(ctx, params)
    boxes = _int(params.get('boxes'), 4, 1, 4)
    gap = BOX_GAP_MM * MM
    count = min(boxes, len(figures))
    if count < _int(params.get('min'), 2, 1, 4):
        return []
    width = (ctx.width - gap * (count - 1)) / count
    size = round(ctx.size * FIGURE * 2) / 2
    figure_style = _style(ctx, 'bold', fontSize=size, leading=size * 1.15)
    unit_style = _style(ctx, 'small', fontSize=round(ctx.size * 0.8 * 2) / 2)
    label_style = _style(ctx, 'bold', fontSize=round(ctx.size * 0.85 * 2) / 2, leading=round(ctx.size * 1.1, 1))
    note_style = _style(ctx, 'small', fontSize=round(ctx.size * 0.8 * 2) / 2, leading=round(ctx.size * 1.05, 1))
    cells = []
    for label, figure, unit, note, from_table in figures:
        if len(cells) == count:
            break
        if from_table and not _fits(ctx, figure, unit, figure_style, unit_style, width):
            # A figure that does not fit its box is left out, never shrunk: a smaller figure reads as a smaller one.
            continue
        markup = _figure_markup(ctx, figure, unit, figure_style, unit_style) if _fits(
            ctx, figure, unit, figure_style, unit_style, width) else None
        cell = [Hair(width, 1.6, above=0, below=1.6 * MM)]
        if label:
            cell.append(Paragraph(ctx.text(label, label_style), label_style))
        if markup:
            cell.append(Paragraph(markup, _style(ctx, figure_style, spaceBefore=1)))
        else:
            # A field's value with no figure to set large (a text, or too wide) is never dropped: it wraps in bold.
            cell.append(Paragraph(ctx.text(' '.join(piece for piece in (figure, unit) if piece), 'bold'),
                                  _style(ctx, 'bold', spaceBefore=1)))
        if note:
            cell.append(Paragraph(ctx.text(note, note_style), note_style))
        cells.append(cell)
    if len(cells) < _int(params.get('min'), 2, 1, 4):
        return []
    width = (ctx.width - gap * (len(cells) - 1)) / len(cells)
    row, columns = [], []
    for index, cell in enumerate(cells):
        if index:
            row.append('')
            columns.append(gap)
        for flowable in cell:
            if isinstance(flowable, Hair):
                flowable.width = width
        row.append(cell)
        columns.append(width)
    drawn = Table([row], colWidths=columns, hAlign='LEFT')
    drawn.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0),
                               ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('TOPPADDING', (0, 0), (-1, -1), 0),
                               ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
    return _finish(place, [drawn], before=ctx.leading * 0.6, after=ctx.leading * 0.8)


def _key_figures_plain(ctx, place):
    """The figures as "label — figure" lines."""
    params = _params(place)
    made = []
    for label, figure, unit, note, _ in _spec_figures(ctx, params) + _row_figures(ctx, params):
        text = ' — '.join(piece for piece in (label, ' '.join(p for p in (figure, unit) if p), note) if piece)
        made.append(Paragraph(ctx.text(text, 'body'), ctx.styles['body']))
    return made + [Gap(1, ctx.leading * 0.5)] if made else []


block('key_figures', fallback=_key_figures_plain)(key_figures)


# ---------------------------------------------------------------- card_grid


def _folded(text):
    return ' '.join(str(text or '').casefold().replace('’', "'").replace('‘', "'").split()).rstrip(':.')


def _cards(ctx, place):
    """[(code, title, tag, [points])] in the template's card order, the part's items under the card they name.

    An item names its card by its code, or by the card's own word in the
    paper's language (a model that wrote "Kuchli tomonlar"); an item that
    names no card is left out and warned (`card_grid_unknown`).
    """
    params = _params(place)
    labels = params.get('labels') if isinstance(params.get('labels'), dict) else {}
    tags = params.get('tags') if isinstance(params.get('tags'), dict) else {}
    cards = [(code, ctx.label(key) if _has_label(ctx, key) else code, ctx.label(tags[code])
              if _has_label(ctx, tags.get(code)) else '', []) for code, key in labels.items()]
    by_name = {}
    for code, title, _, points in cards:
        by_name[_folded(code)] = points
        by_name[_folded(title)] = points
    for item in _items(place.section):
        label = _folded(item.get('label'))
        text = ' '.join(piece for piece in (str(item.get(key) or '').strip() for key in ('text', 'value')) if piece)
        points = by_name.get(label)
        if points is None:
            ctx.warn('card_grid_unknown')
            continue
        points += [line.strip(' •-–—*') for line in text.split('\n') if line.strip(' •-–—*')]
    return cards


def card_grid(ctx, place):
    """Four titled cards in a two-by-two grid, each a tinted title row and its points, a rule where none is given.

    params: labels ({code: label key}: the cards in order and their titles);
    tags ({code: label key}: a small word flush right on the title row,
    "ichki omil"); columns (2); max_points (3 a card: warned, never cut).
    """
    params = _params(place)
    cards = _cards(ctx, place)
    if not cards or not any(points for _, _, _, points in cards):
        return []
    columns = _int(params.get('columns'), 2, 1, 2)
    most = _int(params.get('max_points'), 3, 1, 12)
    if any(len(points) > most for _, _, _, points in cards):
        ctx.warn('card_grid_over')
    gap = 3 * MM
    width = (ctx.width - gap * (columns - 1)) / columns
    pad = 2.2 * MM
    inner = width - 2 * pad
    title_style = _style(ctx, 'bold', fontSize=round(ctx.size * 0.92 * 2) / 2)
    tag_style = _style(ctx, 'small', alignment=TA_RIGHT, fontSize=round(ctx.size * 0.75 * 2) / 2)
    body = _style(ctx, 'small', alignment=TA_LEFT)
    point_style = _style(ctx, body, leftIndent=body.fontSize * 0.9, bulletIndent=0, bulletFontName=body.fontName,
                         bulletFontSize=body.fontSize, spaceBefore=1.5)
    drawn_cards = []
    for code, title, tag, points in cards:
        head = [Paragraph(ctx.text(title, title_style), title_style)]
        if tag:
            head = Table([[head[0], Paragraph(ctx.text(tag, tag_style), tag_style)]],
                         colWidths=[inner * 0.68, inner * 0.32])
            head.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('LEFTPADDING', (0, 0), (-1, -1), 0),
                                      ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('TOPPADDING', (0, 0), (-1, -1), 0),
                                      ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
            head = [head]
        lines = [Paragraph(ctx.text(point, point_style), point_style, bulletText='•') for point in points]
        if not lines:
            lines = [Spacer(1, ctx.leading * 0.9), Hair(inner, 0.5, above=0, below=0)]
        card = Table([[head], [lines]], colWidths=[width])
        card.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), 0.6, INK), ('BACKGROUND', (0, 0), (-1, 0), TINT),
                                  ('LINEBELOW', (0, 0), (-1, 0), 0.4, INK), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                  ('LEFTPADDING', (0, 0), (-1, -1), pad), ('RIGHTPADDING', (0, 0), (-1, -1), pad),
                                  ('TOPPADDING', (0, 0), (-1, -1), 1.6 * MM),
                                  ('BOTTOMPADDING', (0, 0), (-1, -1), 1.8 * MM)]))
        drawn_cards.append(card)
    rows = []
    for start in range(0, len(drawn_cards), columns):
        chunk = drawn_cards[start:start + columns]
        row = []
        for index, card in enumerate(chunk):
            if index:
                row.append('')
            row.append(card)
        while len(row) < columns * 2 - 1:
            row.append('')
        rows.append(row)
    widths = []
    for index in range(columns):
        if index:
            widths.append(gap)
        widths.append(width)
    grid = Table(rows, colWidths=widths, hAlign='LEFT')
    grid.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0),
                              ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('TOPPADDING', (0, 0), (-1, -1), 0),
                              ('BOTTOMPADDING', (0, 0), (-1, -1), gap)]))
    return _finish(place, [grid], before=ctx.leading * 0.4, after=ctx.leading * 0.2)


def _card_grid_plain(ctx, place):
    """Four headed lists: each card's title in bold, its points under it."""
    made = []
    for _, title, _, points in _cards(ctx, place):
        if not points:
            continue
        made.append(Paragraph(_bold(ctx, title, ctx.styles['body']), ctx.styles['body']))
        style = _style(ctx, 'body', leftIndent=ctx.size, bulletIndent=0, bulletFontName=_font(ctx))
        made += [Paragraph(ctx.text(point, style), style, bulletText='•') for point in points]
    return made + [Gap(1, ctx.leading * 0.5)] if made else []


block('card_grid', fallback=_card_grid_plain)(card_grid)


# ---------------------------------------------------------------- samples


def _text3(uz, ru, en):
    return {'uz': uz, 'ru': ru, 'en': en}


SELLER = _text3('Misol Mebel MChJ', 'ООО «Мисол Мебель»', 'Misol Furniture LLC')
INDICATORS = {'id': 'indicators', 'heading': '', 'body': '', 'layout': 'table', 'items': [
    {'label': _text3('Sotuv hajmi', 'Объём продаж', 'Sales'),
     'text': _text3('mln so‘m | 1 920 | 2 046 | +126 | 106,6%', 'млн сум | 1 920 | 2 046 | +126 | 106,6%',
                    'mln UZS | 1,920 | 2,046 | +126 | 106.6%'), 'value': ''},
    {'label': _text3('Yalpi foyda', 'Валовая прибыль', 'Gross profit'),
     'text': _text3('mln so‘m | 400 | 418 | +18 | 104,5%', 'млн сум | 400 | 418 | +18 | 104,5%',
                    'mln UZS | 400 | 418 | +18 | 104.5%'), 'value': ''},
    {'label': _text3('Faol mijozlar', 'Активные клиенты', 'Active clients'),
     'text': _text3('ta | 280 | 312 | +32 | 111,4%', 'шт. | 280 | 312 | +32 | 111,4%',
                    'clients | 280 | 312 | +32 | 111.4%'), 'value': ''},
    {'label': _text3('Xodimlar soni', 'Численность', 'Staff'),
     'text': _text3('nafar | 44 | 41 | −3 | 93,2%', 'чел. | 44 | 41 | −3 | 93,2%', 'people | 44 | 41 | −3 | 93.2%'),
     'value': ''},
    {'label': _text3('Yangi hududlar', 'Новые регионы', 'New regions'),
     'text': _text3('ta | 3 | 4 | +1 | 133,3%', 'шт. | 3 | 4 | +1 | 133,3%', 'regions | 3 | 4 | +1 | 133.3%'),
     'value': ''}]}
SWOT = {'id': 'swot', 'heading': '', 'body': '', 'layout': 'list', 'items': [
    {'label': 'strengths', 'text': _text3('7 kun ichida almashtirish', 'Обмен в течение 7 дней',
                                          'Exchange within 7 days')},
    {'label': 'strengths', 'text': _text3('Mavjud baza: 4 000 obunachi', 'Своя база: 4 000 подписчиков',
                                          'An audience of 4,000 followers')},
    {'label': 'weaknesses', 'text': _text3('Raqobatchilarda narx pastroq', 'У конкурентов цены ниже',
                                           'Competitors charge less')},
    {'label': 'opportunities', 'text': _text3('Telegram — qo‘shimcha aloqa kanali',
                                              'Telegram — дополнительный канал связи',
                                              'Telegram as a second channel')}]}

# One placement per variant, each on the template it is written for (its page, type and labels).
SAMPLES = [
    {'block': 'letterhead', 'name': 'name and contacts over a rule', 'template': 'business_taklif',
     'part': 'letterhead', 'fields': ['seller_name', 'seller_address', 'seller_phone', 'seller_email'],
     'facts': {'seller_name': SELLER, 'seller_address': _text3('Toshkent sh., Chilonzor t., 12-uy',
                                                               'г. Ташкент, Чиланзарский р-н, д. 12',
                                                               '12 Chilonzor district, Tashkent'),
               'seller_phone': _text3('+998 90 123 45 67', '+998 90 123 45 67', '+998 90 123 45 67'),
               'seller_email': _text3('savdo@misolmebel.example', 'savdo@misolmebel.example', 'savdo@misolmebel.example')},
     'params': {'labels': {'seller_phone': 'tel'}, 'captions': {'seller_name': 'cap_company'}}},
    {'block': 'letterhead', 'name': 'no name: a captioned rule', 'template': 'business_taklif',
     'part': 'letterhead', 'fields': ['seller_name', 'seller_phone'],
     'facts': {'seller_phone': _text3('+998 90 123 45 67', '+998 90 123 45 67', '+998 90 123 45 67')},
     'params': {'labels': {'seller_phone': 'tel'}, 'captions': {'seller_name': 'cap_company'}}},
    {'block': 'key_figures', 'name': 'from the indicators, with the plan typed', 'template': 'business_hisobot',
     'part': 'figures', 'section': INDICATORS,
     'params': {'from': 'indicators', 'value_column': 3, 'unit_column': 1, 'compare_column': 2,
                'compare_label': 'kf_plan', 'min_rows': 5, 'boxes': 4}},
    {'block': 'key_figures', 'name': 'fields', 'template': 'business_biznes_reja', 'part': 'summary_figures',
     'fields': ['own_funds', 'external_funding'],
     'facts': {'own_funds': _text3('120 mln so‘m', '120 млн сум', 'UZS 120 mln'),
               'external_funding': _text3('300 mln so‘m', '300 млн сум', 'UZS 300 mln')},
     'params': {'figures': [{'field': 'own_funds', 'label': 'kf_own'},
                            {'field': 'external_funding', 'label': 'kf_external'}]}},
    {'block': 'card_grid', 'name': 'SWOT, an empty card ruled', 'template': 'business_marketing_reja',
     'part': 'swot', 'section': SWOT,
     'params': {'labels': {'strengths': 'sw_s', 'weaknesses': 'sw_w', 'opportunities': 'sw_o', 'threats': 'sw_t'},
                'tags': {'strengths': 'tag_inner', 'weaknesses': 'tag_inner', 'opportunities': 'tag_outer',
                         'threats': 'tag_outer'}}},
]
