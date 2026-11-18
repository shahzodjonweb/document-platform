"""The regulation block: numbered clauses (architecture 6.6, blocks.json `clauses`, package R5b).

A staff instruction, a job description and the decisions of a meeting are
all clauses: a number in a column of its own, the text hanging beside it,
and under a lead-in that ends with a colon the actions it names, one a line
behind a dash or a bullet. The number is the renderer's ("2.3." under the
second chapter), never the model's: a number the model typed anyway is
dropped, so a paper that loses a chapter is never numbered 1, 3, 4.

Where the clauses come from (the catalogue's write rule for these parts):
one item a clause; a lead-in in `label` with its actions in `text` joined
by " | " (or one a line); a single clause in `text` alone. A list part the
model wrote as lines of a body reaches here as items already, one clause a
line with its dash gone (finish._shape), so actions are written in `text`; the
body reading below (a line behind a dash an action of the clause before it)
serves only a part that is not a list.

params:
- `numbering` decimal ("2.3.", the chapter's number and the clause's) |
  arabic ("3.") | instance (the group instance's number, "2.") | none; or a
  map by language ({"ru": "decimal", "uz": "arabic"}: Russian minutes
  number their decisions by item, Uzbek and English ones restart at 1);
- `chapter` heading (the counter of the heading at `level`, which the chapter
  heading set) | instance (the group instance: an agenda item's decisions);
- `level` the heading level the chapter number is read at (the heading's);
- `heading` the chapter's heading, drawn by the core heading block with these
  params, and only when the part has clauses (or blanks) to follow it: an
  empty chapter never leaves a heading behind and the next one takes its
  number. `heading.labels` ({cue: label key}) names the heading a cue sets,
  as a safety instruction titles its chapters by the safety rules;
- `nested` dash | bullet, the marker of the actions; `punctuate` ends each
  action with a semicolon and the last with a full stop, as an official
  paper sets them;
- `lead` bold sets a lead-in (a clause with actions under it) in bold, and
  `number` bold its number, as the business form scans by them;
- `caution` sets a clause that opens with Diqqat! (Внимание!, Caution!) in a
  tinted box with a bar down its edge, its number inside and the word bold;
- `tail` italic sets a decision's closing bracket (mas’ul ...; muddat ...)
  in italics in the same paragraph;
- `blank_items` numbered rules to write on when the part has no clause (a
  meeting's decisions the customer did not give);
- `hang_mm` the number column (10), `gap_pt` the space between clauses,
  `max_items` warned past, never cut;
- `source` a part id read instead of the placement's part, and `pick`
  instance: only the clause at the group instance's place in it. Drawn with
  `style` bold and `from_instances` N (only when the group has at least N
  instances), it is a meeting's item heading: the n-th agenda line over the
  n-th item's report and decisions, so every item follows its agenda line
  (architecture 15: bayonnoma through groups).

Every string goes through ctx.text: the house apostrophes, the glue and the
blanks are text_rules'. Nothing is written that the content did not hold,
except the numbers, the markers and the punctuation of an action list.
"""
import re

from reportlab.lib.enums import TA_LEFT
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Paragraph, Table, TableStyle

from ...categories.catalogue import PAPER_BOUNDS
from ..ctx import INK, Place
from ..registry import block
from ..text import MM
from .core import (CELL, TINT, TYPED_MARKER, Ruled, _cap_size, _finish, _font, _int, _items, _lines, _num, _params,
                   _style, _warn_over, heading)

# A clause number the model typed in spite of the rule: "2.", "2.3.", "1)". A decimal such as "1.5 mln" at the
# start of a decision is the customer's figure and is kept: only numbers that end in a full stop or a bracket go.
TYPED_NUMBER = re.compile(r'^\s*(?:(?:\d{1,2}\.){1,3}|\d{1,2}\))\s+')
# A clause that must not be missed opens with the language's word for it.
CAUTION = re.compile(r'^\s*(Diqqat|Ehtiyot\s+bo[‘’\'`]?ling|Внимание|Осторожно|Caution|Warning)\s*[!:]\s*',
                     re.IGNORECASE)
# The closing bracket of a decision that names who is responsible and by when.
# The last word of an action is an abbreviation whose own full stop stays: "h.k.", "т.д.", "i.e.", "etc.".
ABBREVIATION = re.compile(r'(?:^|\s)(?:(?:[^\W\d_]{1,3}\.){2,}|etc\.|др\.|пр\.)$', re.IGNORECASE)
TAIL = re.compile(r'\s*\((?:mas[‘’ʼ\'`]?ul|muddat|ответствен|срок|responsible|due)[^()]*\)[.;]?\s*$',
                  re.IGNORECASE)
MARKERS = {'dash': '–', 'bullet': '•'}
NUMBERINGS = ('decimal', 'arabic', 'instance', 'none')


def _clean(text):
    return ' '.join(str(text or '').split())


def clauses_of(section):
    """[(clause, [actions])] of a section, read as the module's docstring says; numbers and markers typed dropped."""
    found = []
    items = _items(section)
    if items:
        for item in items:
            label = _clean(item.get('label'))
            pieces = [_clean(piece) for piece in re.split(r'\n|' + CELL.pattern, str(item.get('text') or ''))]
            pieces = [piece for piece in pieces if piece]
            value = _clean(item.get('value'))
            if not label and not pieces:
                label, value = value, ''
            clause, actions = (label, pieces) if label else (pieces[0], pieces[1:])
            if value:
                actions.append(value)
            found.append((clause, actions))
    else:
        for line in _lines(section):
            if TYPED_MARKER.match(line) and not TYPED_NUMBER.match(line) and found:
                found[-1][1].append(line)
            else:
                found.append((line, []))
    tidy = []
    for clause, actions in found:
        # A clause the model opened with a dash or a bullet loses it too: the renderer's number stands there.
        clause = TYPED_MARKER.sub('', TYPED_NUMBER.sub('', clause, count=1), count=1).strip()
        actions = [TYPED_MARKER.sub('', action, count=1).strip() for action in actions]
        actions = [action for action in actions if action]
        if clause or actions:
            tidy.append((clause, actions))
    return tidy


def _choice(params, key, allowed, default, locale):
    value = params.get(key)
    if isinstance(value, dict):
        value = value.get(locale) or value.get('en')
    return value if value in allowed else default


def _group_size(ctx, place):
    """How many instances the place's group holds: the highest instance any of its parts has a section for."""
    if not place.group:
        return 1
    parts = [part['id'] for part in ctx.entry.parts if part.get('group') == place.group]
    found = 1
    for number in range(2, PAPER_BOUNDS.sections + 1):
        if any(ctx.section(part_id, number) is not None for part_id in parts):
            found = number
    return found


def _heading(ctx, place, spec):
    """The chapter's heading through the core heading block; its label by the first cue of `labels` that holds."""
    params = dict(spec) if isinstance(spec, dict) else {}
    by_cue = params.pop('labels', None)
    for cue, key in (by_cue.items() if isinstance(by_cue, dict) else ()):
        if cue in ctx.cues and isinstance(key, str):
            params['label'] = key
            break
    return heading(ctx, Place('heading', place.section, place.part, (), params, place.instance, place.index,
                              place.group))


def _punctuated(actions):
    """Actions ending in a semicolon each and a full stop at the last, whatever the model ended them with."""
    made = []
    for number, action in enumerate(actions):
        if action[-1:] in '?!':
            made.append(action)
            continue
        last = number == len(actions) - 1
        kept = action.rstrip(' ;,:')
        if ABBREVIATION.search(kept):
            made.append(kept if last else kept + ';')
            continue
        made.append(kept.rstrip(' ;,.:') + ('.' if last else ';'))
    return made


def _markup(ctx, text, style, *, bold=False, tail=False, caution=False):
    """A clause as Paragraph markup: bold when asked, the caution word bold, a decision's tail in italics."""
    head, rest = '', text
    if caution:
        found = CAUTION.match(text)
        if found:
            head, rest = text[:found.end()].strip(), text[found.end():]
    closing = ''
    if tail:
        found = TAIL.search(rest)
        if found and found.start() > 0:
            rest, closing = rest[:found.start()], rest[found.start():].strip()
    markup = ctx.text(rest, style)
    if bold:
        markup = f'<font name="{_font(ctx, "Bold")}">{markup}</font>'
    if head:
        markup = f'<font name="{_font(ctx, "Bold")}">{ctx.text(head, style)}</font> {markup}'
    if closing:
        markup += f' <font name="{_font(ctx, "Italic")}">{ctx.text(closing, style)}</font>'
    return markup


def _number(numbering, chapter, count, instance):
    if numbering == 'none':
        return ''
    if numbering == 'instance':
        return f'{instance}.'
    if numbering == 'decimal' and chapter:
        return f'{chapter}.{count}.'
    return f'{count}.'


def clauses(ctx, place):
    """Numbered clauses with actions under them; see the module's docstring for every parameter."""
    params = _params(place)
    source = params.get('source')
    section = ctx.section(source, 1) if isinstance(source, str) else place.section
    found = clauses_of(section)
    picking = params.get('pick') == 'instance'
    if picking:
        if max(_group_size(ctx, place), len(found)) < _int(params.get('from_instances'), 1, 1, 60):
            return []
        found = found[place.instance - 1:place.instance]
    # Blanks stand in for decisions not given at all: a part with one clause is not padded with rules.
    blanks = 0 if picking or found else _int(params.get('blank_items'), 0, 0, 10)
    if not found and not blanks:
        return []
    _warn_over(ctx, 'clauses', len(found), _int(params.get('max_items'), 0, 0, 200))
    made = _heading(ctx, place, params['heading']) if params.get('heading') else []
    titled = bool(made)
    numbering = _choice(params, 'numbering', NUMBERINGS, 'instance' if picking else 'arabic', ctx.locale)
    spec = params.get('heading') if isinstance(params.get('heading'), dict) else {}
    level = _int(params.get('level'), _int(spec.get('level'), 1, 1, 3), 1, 3)
    chapter = place.instance if params.get('chapter') == 'instance' else ctx.count(level)
    total = len(found) + blanks
    base = _style(ctx, 'bold' if params.get('style') == 'bold' else 'body', alignment=TA_LEFT)
    numbers = [_number(numbering, chapter, count, place.instance) for count in range(1, total + 1)]
    number_font = _font(ctx, 'Bold') if params.get('number') == 'bold' or params.get('style') == 'bold' \
        else base.fontName
    widest = max((stringWidth(number, number_font, base.fontSize) for number in numbers), default=0)
    hang = 0.0 if numbering == 'none' else max(_num(params.get('hang_mm'), 10.0, 0, 40) * MM,
                                               widest + base.fontSize * 0.6)
    gap = _num(params.get('gap_pt'), ctx.leading * 0.25, 0, 40)
    marker = MARKERS.get(params.get('nested'), MARKERS['dash'])
    sub = max(base.fontSize * 1.1, stringWidth(marker, base.fontName, base.fontSize) + base.fontSize * 0.6)
    for index, (clause, actions) in enumerate(found):
        style = _style(ctx, base, leftIndent=hang, bulletIndent=0, bulletFontName=number_font,
                       bulletFontSize=base.fontSize, spaceBefore=gap if index else 0)
        caution = bool(params.get('caution')) and bool(CAUTION.match(clause))
        bold = params.get('lead') == 'bold' and bool(actions) and not caution
        markup = _markup(ctx, clause, style, bold=bold, tail=params.get('tail') == 'italic', caution=caution)
        drawn = Paragraph(markup, style, bulletText=numbers[index] or None) if clause else None
        if caution and drawn is not None:
            drawn = _boxed(ctx, drawn, style)
        if drawn is not None:
            if actions or picking:
                drawn.keepWithNext = 1
            made.append(drawn)
        if params.get('punctuate'):
            actions = _punctuated(actions)
        for number, action in enumerate(actions):
            chosen = _style(ctx, base, leftIndent=hang + sub, bulletIndent=hang, bulletFontName=base.fontName,
                            fontName=ctx.styles['body'].fontName,
                            spaceBefore=ctx.leading * 0.08 if number or clause else gap)
            item = Paragraph(ctx.text(action, chosen), chosen, bulletText=marker)
            # Three actions or fewer never part; a longer list parts with two on each side of the page.
            if number < len(actions) - 1 and (len(actions) <= 3 or number in (0, len(actions) - 2)):
                item.keepWithNext = 1
            made.append(item)
    for index in range(len(found), total):
        made.append(Ruled(label=numbers[index], lines=1, caption=None, rule=None, style='rules',
                          pitch=max(16.0, ctx.size * 2), indent=0.0, font=ctx.face, size=ctx.size,
                          small=_cap_size(ctx)))
    # A heading keeps its own space above; without one the clauses take a little.
    return _finish(place, made, before=0.0 if titled else ctx.leading * 0.2,
                   after=ctx.leading * (0.1 if picking else 0.3))


def _boxed(ctx, paragraph, style):
    """A caution clause in a tinted box with a bar down its left edge; one row, so it never splits.

    A clause taller than a page cannot stand in one row (ReportLab raises), so
    it stays an unboxed paragraph with its bold word: the chapter keeps its
    numbers instead of falling back to plain lines."""
    pad = 2.5 * MM
    if paragraph.wrap(ctx.width - 2 * pad, ctx.frame_height)[1] + 1.5 * pad > ctx.frame_height * 0.9:
        return paragraph
    paragraph.style = _style(ctx, style, spaceBefore=0)
    drawn = Table([[paragraph]], colWidths=[ctx.width], hAlign='LEFT')
    drawn.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), TINT), ('LINEBEFORE', (0, 0), (0, -1), 1.6, INK),
                               ('LEFTPADDING', (0, 0), (-1, -1), pad), ('RIGHTPADDING', (0, 0), (-1, -1), pad),
                               ('TOPPADDING', (0, 0), (-1, -1), pad * 0.7),
                               ('BOTTOMPADDING', (0, 0), (-1, -1), pad * 0.8)]))
    drawn.spaceBefore = style.spaceBefore
    return drawn


def _clauses_plain(ctx, place):
    """Numbered body lines, an action a line behind a dash."""
    params = _params(place)
    source = params.get('source')
    section = ctx.section(source, 1) if isinstance(source, str) else place.section
    found = clauses_of(section)
    if params.get('pick') == 'instance':
        found = found[place.instance - 1:place.instance]
    made = []
    for count, (clause, actions) in enumerate(found, 1):
        if clause:
            made.append(Paragraph(ctx.text(f'{count}. {clause}'), ctx.styles['body']))
        made += [Paragraph(ctx.text(f'– {action}'), ctx.styles['body']) for action in actions]
    return made


block('clauses', fallback=_clauses_plain)(clauses)


# ---------------------------------------------------------------- samples


def _text3(uz, ru, en):
    return {'uz': uz, 'ru': ru, 'en': en}


DUTIES = {'id': 'duties', 'heading': '', 'body': '', 'layout': 'list', 'items': [
    {'label': _text3('O‘qituvchi quyidagi vazifalarni bajaradi:', 'Учитель выполняет следующие обязанности:',
                     'The Teacher performs the following duties:'),
     'text': _text3('dars rejasini tuzadi | sinf jurnalini yuritadi | o‘quvchilar bilimini baholaydi',
                    'составляет план урока | ведёт классный журнал | оценивает знания учащихся',
                    'draws up the lesson plan | keeps the class register | assesses the pupils’ knowledge'),
     'value': ''},
    {'label': '', 'text': _text3('2. O‘qituvchi ota-onalar yig‘ilishida qatnashadi.',
                                 '2. Учитель участвует в родительских собраниях.',
                                 '2. The Teacher takes part in parents’ meetings.'), 'value': ''}]}
WORK = {'id': 'during_work', 'heading': '', 'body': '', 'layout': 'list', 'items': [
    {'label': _text3('Buyurtma olishda Ofitsiant:', 'При приёме заказа официант:', 'When taking an order the Waiter:'),
     'text': _text3('buyurtmani yozib oladi | buyurtmani takrorlaydi', 'записывает заказ | повторяет заказ',
                    'writes the order down | repeats the order'), 'value': ''},
    {'label': '', 'text': _text3('Diqqat! Mijoz allergiya haqida aytsa, Ofitsiant buni oshxonaga yetkazadi.',
                                 'Внимание! Если гость говорит об аллергии, официант сообщает об этом на кухню.',
                                 'Caution! If a guest mentions an allergy, the Waiter tells the kitchen.'),
     'value': ''}]}
DECISIONS = {'id': 'item_decisions', 'heading': '', 'body': '', 'layout': 'list', 'items': [
    {'label': '', 'text': _text3('Hisobot tasdiqlansin.', 'Утвердить отчёт.', 'The report is approved.'),
     'value': ''},
    {'label': '', 'text': _text3('Ombor ijarasi bo‘yicha taklif tayyorlansin (mas’ul: B. A. Karimov; muddat: '
                                 '1-dekabr).', 'Подготовить предложение по аренде склада (ответственный: Б. А. '
                                 'Каримов; срок: 1 декабря).', 'A proposal on renting the warehouse is prepared '
                                 '(responsible: B. A. Karimov; due: 1 December).'), 'value': ''}]}
AGENDA = {'id': 'agenda', 'heading': '', 'body': '', 'layout': 'list', 'items': [
    {'label': '', 'text': _text3('3-chorak hisoboti haqida', 'Об отчёте за 3 квартал', 'The Q3 report'),
     'value': ''},
    {'label': '', 'text': _text3('Yangi ombor ijarasi to‘g‘risida', 'Об аренде нового склада',
                                 'Renting a new warehouse'), 'value': ''}]}
LAVOZIM = {'template': 'official_lavozim_yoriqnomasi', 'entry': 'pdf.biz.lavozim_yoriqnomasi'}
YORIQNOMA = {'template': 'business_yoriqnoma', 'entry': 'pdf.biz.yoriqnoma'}
MINUTES = {'template': 'official_bayonnoma', 'entry': 'pdf.biz.bayonnoma'}

SAMPLES = (
    {'block': 'clauses', 'name': 'official: chapter heading, decimal, dash actions punctuated', **LAVOZIM,
     'part': 'duties', 'section': DUTIES,
     'params': {'heading': {'level': 2, 'numbering': 'roman', 'align': 'centre', 'in_toc': False},
                'numbering': 'decimal', 'nested': 'dash', 'punctuate': True, 'hang_mm': 12.5}},
    {'block': 'clauses', 'name': 'business: bold lead-ins and numbers, bullets, a caution box', **YORIQNOMA,
     'part': 'during_work', 'section': WORK,
     'params': {'heading': {'level': 1, 'numbering': 'arabic', 'rule': 'under', 'in_toc': False},
                'numbering': 'decimal', 'nested': 'bullet', 'lead': 'bold', 'number': 'bold', 'caution': True}},
    {'block': 'clauses', 'name': 'minutes: decisions by item in Russian, the tail in italics', **MINUTES,
     'part': 'item_decisions', 'section': DECISIONS,
     'params': {'heading': {'level': 3, 'in_toc': False}, 'numbering': {'ru': 'decimal', 'uz': 'arabic',
                                                                        'en': 'arabic'},
                'chapter': 'instance', 'tail': 'italic', 'hang_mm': 8}},
    {'block': 'clauses', 'name': 'minutes: no decision given, two numbered blanks', **MINUTES,
     'part': 'item_decisions', 'section': {'id': 'item_decisions', 'heading': '', 'body': '', 'layout': 'list',
                                           'items': []},
     'params': {'heading': {'level': 3, 'in_toc': False}, 'blank_items': 2, 'hang_mm': 8}},
    {'block': 'clauses', 'name': 'minutes: the item heading picked from the agenda', **MINUTES,
     'part': 'item_report', 'section': AGENDA,
     'params': {'source': 'agenda', 'pick': 'instance', 'style': 'bold', 'from_instances': 2, 'hang_mm': 8}},
)
