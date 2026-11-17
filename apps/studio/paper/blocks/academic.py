"""The academic blocks: title_page, toc and reference_list (architecture 6.6, blocks.json, package R3a).

A mustaqil ish and a kurs ishi are judged first by three pages a teacher
looks at before reading a line: the title page, the plan with its page
numbers and the reference list. These are the blocks that draw them; the
prose between is the core blocks' (heading, paragraph, list). A business
plan's cover and contents and a lesson plan's cover are drawn by the same
two blocks.

- `title_page` is a whole first sheet, every line placed by its role: the
  ministry and the institution at the top, the subject, the kind of work in
  large tracked capitals and the topic in the middle, who wrote it and who
  checks it in a column right of the centre, the city and the year at the
  foot. A fact the customer did not give is a ruled line with a small caption
  saying what to write there, never a guess; the year is the clock's. It is
  one flowable as tall as the frame, so what follows starts the next page and
  the page is counted, never numbered.
- `toc` lists the headings the paper actually draws (each heading block
  marks itself), with dot leaders and the page each starts on. It is made
  when it is laid out (`ctx.Lazy`), after every heading has marked itself;
  the engine builds once more with the pages it found, so the numbers printed
  are the pages delivered. `style: strip` is the short plan without numbers.
- `reference_list` lists only the sources that finish verified against the
  customer's words or files, numbered with a hanging indent, grouped (laws,
  books and articles, online sources) only from six entries in two groups.
  With none it is a numbered form of ruled lines to fill in by hand: an
  honest empty list, never one the model made up.

Words follow core.py: every fixed word is a template label in the paper's
language (with a built-in wording for the few every paper shares: the
reference form's caption and the group names), every value the verified one,
the clock's, or a blank.
"""
import re

from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Flowable, Paragraph, Spacer, Table, TableStyle

from ..ctx import INK, Lazy
from ..registry import block
from ..text import MM
from .core import (SLOT, TYPED_MARKER, Gap, Tracked, _balanced, _cap_size, _finish, _font, _has_label, _int,
                   _item_text, _items, _lines, _params, _style, _word)

# The title page's zones, by a row's role: the head of the sheet, the middle (what the work is), the credit column
# (who wrote it, who checks it) and the foot (the city and the year).
TOP = frozenset(('ministry', 'institution', 'faculty', 'kafedra', 'direction', 'place', 'unit'))
MIDDLE = frozenset(('subject', 'kind', 'topic', 'title', 'subtitle'))
CREDIT = frozenset(('credit', 'credit_sub'))
# Each role's style when its row names none.
ROLE_STYLE = {'ministry': 'bold_caps', 'institution': 'bold_caps', 'kind': 'display', 'topic': 'topic',
              'title': 'topic', 'subtitle': 'italic', 'foot': 'bold'}
# The width of a blank where a fact is missing, by role, in mm (the credit column's blanks are its width).
BLANK_MM = {'ministry': 140, 'institution': 140, 'subject': 95, 'foot': 50, 'topic': 140, 'title': 140}
BLANK_LINES = {'institution': 2}
# A centred line is set inside this measure, so a long institution or topic wraps into a block, not a ribbon.
MEASURE_MM = 149
# The credit column: its labels start this far left of the centre axis and its values keep at least this width.
CREDIT_LEFT_MM, CREDIT_VALUE_MM = 22, 60
# The kind of work in large tracked capitals: this many times the body size, stepped down to the floor to fit.
DISPLAY, DISPLAY_FLOOR, TRACKING_PT = 2.45, 1.6, 5.0
# The topic: bold, stepped down while it runs past this many lines.
TOPIC_STEPS, TOPIC_LINES = (1.23, 1.12, 1.04, 1.0), 5
# Every size and gap of a sheet that does not fit is scaled by the next of these before it is given up.
SCALES = (1.0, 0.92, 0.85, 0.78, 0.7)
# A date to fill in by hand under a signature, its year the clock's.
SIGN_DATE = {'uz': '«___» ________ {year}-yil', 'ru': '«___» ________ {year} г.', 'en': '____ ________ {year}'}
SIGN_WORD = {'uz': '(imzo)', 'ru': '(подпись)', 'en': '(signature)'}
DASH = ' – '
QUOTES = '«»“”„"‘’\''
# The air over a row of the head or the middle, in lines of the body, when it is not the first of its zone.
GAPS = {'ministry': 0.2, 'institution': 0.3, 'subject': 0.6, 'kind': 1.1, 'topic': 0.9, 'title': 0.9,
        'subtitle': 0.35}

# The reference list's words when the template has no label of the name.
REF_CAPTION = {'uz': '(muallif, nomi, shahar: nashriyot, yil, sahifalar soni)',
               'ru': '(автор, название, город: издательство, год, количество страниц)',
               'en': '(author, title, city: publisher, year, pages)'}
GROUPS = ('normative', 'literature', 'online')
GROUP_WORDS = {
    'normative': {'uz': 'Normativ-huquqiy hujjatlar', 'ru': 'Нормативные правовые акты',
                  'en': 'Laws and regulations'},
    'literature': {'uz': 'Ilmiy va o‘quv adabiyotlar', 'ru': 'Научная и учебная литература',
                   'en': 'Books and articles'},
    'online': {'uz': 'Internet manbalari', 'ru': 'Интернет-источники', 'en': 'Online sources'},
}
# Group labels print only from this many entries in at least two groups: a short list reads better without them.
GROUP_FROM = 6
NORMATIVE = re.compile(r'(?<![^\W\d_])(qonun|farmon|qaror|kodeks|konstitutsiya|nizom|закон|указ|постановлени|'
                       r'кодекс|конституци|положени|law|decree|regulation|resolution|constitution|statute)', re.IGNORECASE)
ONLINE = re.compile(r'https?://|www\.|\[(elektron resurs|электронный ресурс|online|electronic resource)\]|URL:',
                    re.IGNORECASE)
# A heading's number as the heading block writes it: "2.", "2.1", "II.", "2-BOB.", "ГЛАВА 2.", "CHAPTER 2.".
NUMBER = re.compile(r'^(\d{1,2}(?:\.\d{1,2}){0,2}\.?|[IVXLC]{1,6}\.|\d{1,2}-BOB\.?|ГЛАВА \d{1,2}\.?|'
                    r'CHAPTER \d{1,2}\.?)\s+(\S.*)$', re.S)
# What a contents prints in place of a page number before a build has placed the heading: two digits wide.
NO_PAGE = '00'


# ---------------------------------------------------------------- flowables


class Blank(Flowable):
    """A line to write on: a word before it, a rule, a word after it, a caption under the rule.

    The rule is `rule` points long. `align` places the whole run (prefix,
    rule, suffix) in the width: centre, or left at `x`. `lines` rules are
    drawn one under the other, the caption under the last; the clear room
    over each is about a line of the body, so a hand has space.
    """

    def __init__(self, *, rule, prefix='', suffix='', caption='', font, size, small, bold=False, lines=1,
                 align='centre', x=0.0, room=None):
        super().__init__()
        self.rule, self.prefix, self.suffix, self.caption = rule, prefix, suffix, caption
        self.font, self.size, self.small, self.bold = font, size, small, bold
        self.lines, self.align, self.x = max(1, lines), align, x
        self.room = room if room is not None else size * 1.15
        self.pitch = size * 1.9

    def _text_font(self):
        return f'{self.font}-Bold' if self.bold else self.font

    def wrap(self, width, height):
        self.width = width
        under = self.small * 1.35 + 1.5 if self.caption else 2.0
        self.height = self.room + self.pitch * (self.lines - 1) + under
        return width, self.height

    def draw(self):
        canvas = self.canv
        font = self._text_font()
        before = stringWidth(self.prefix + ' ', font, self.size) if self.prefix else 0.0
        after = stringWidth(' ' + self.suffix, font, self.size) if self.suffix else 0.0
        rule = min(self.rule, max(10.0, self.width - before - after - self.x))
        start = (self.width - before - rule - after) / 2 if self.align == 'centre' else self.x
        canvas.saveState()
        canvas.setFillColor(INK)
        canvas.setStrokeColor(INK)
        canvas.setLineWidth(0.5)
        canvas.setFont(font, self.size)
        top = self.height - self.room
        for number in range(self.lines):
            base = top - self.pitch * number
            canvas.line(start + before, base, start + before + rule, base)
        last = top - self.pitch * (self.lines - 1)
        if self.prefix:
            canvas.drawString(start, top + 1.5, self.prefix)
        if self.suffix:
            canvas.drawString(start + before + rule + stringWidth(' ', font, self.size), last + 1.5, self.suffix)
        if self.caption:
            canvas.setFont(f'{self.font}-Italic', self.small)
            canvas.drawCentredString(start + before + rule / 2, last - self.small * 1.1, self.caption)
        canvas.restoreState()


class Sheet(Flowable):
    """A title page: its zones placed on one frame-tall sheet, so the next placement starts a new page.

    `top` runs down from the top of the frame, `foot` sits on its bottom, the
    `credit` column stands `credit_gap` over the foot, and the `middle` is
    centred in the room between the top and the credit column, at least
    `gap` from each. A zone is a list of (flowable, x, space before);
    `needed()` is the height the zones take with their least gaps.
    """

    def __init__(self, zones, height, gap, credit_gap):
        super().__init__()
        self.zones, self.sheet_height, self.gap, self.credit_gap = zones, height, gap, credit_gap
        self._sizes = None

    def _measure(self, width):
        if self._sizes is None or self._sizes[0] != width:
            heights = {}
            for name, zone in self.zones.items():
                total = 0.0
                for flowable, x, before in zone:
                    _, tall = flowable.wrap(width - x, self.sheet_height)
                    total += before + tall
                heights[name] = total
            self._sizes = (width, heights)
        return self._sizes[1]

    def needed(self, width):
        heights = self._measure(width)
        gaps = self.gap * 2 if heights['middle'] else self.gap
        return heights['top'] + heights['middle'] + heights['credit'] + heights['foot'] + gaps + (
            self.credit_gap if heights['credit'] and heights['foot'] else 0.0)

    def wrap(self, width, height):
        self.width, self.height = width, self.sheet_height
        self._measure(width)
        return width, self.sheet_height

    def _place(self, zone, top):
        """Draw a zone downwards from `top` (points from the bottom of the sheet); returns where it ended."""
        y = top
        for flowable, x, before in zone:
            _, tall = flowable.wrap(self.width - x, self.sheet_height)
            y -= before + tall
            flowable.drawOn(self.canv, x, y)
        return y

    def draw(self):
        heights = self._measure(self.width)
        foot_top = heights['foot']
        self._place(self.zones['foot'], foot_top)
        credit_top = foot_top + (self.credit_gap if heights['foot'] and heights['credit'] else 0.0) + \
            heights['credit']
        self._place(self.zones['credit'], credit_top)
        top_end = self._place(self.zones['top'], self.sheet_height)
        room_top = top_end - (self.gap if heights['top'] else 0.0)
        room_bottom = credit_top + self.gap
        middle = heights['middle']
        start = room_bottom + middle + max(0.0, (room_top - room_bottom - middle) / 2)
        self._place(self.zones['middle'], min(room_top, start))


class Leader(Paragraph):
    """A contents row: the heading's text, dot leaders on a common pitch, the page number flush right.

    The text ends with an onDraw mark, so the leaders start where the last
    line really ends, however it wrapped. The page number column is the
    style's right indent; `page` None draws the row without leaders or number.
    A row split across pages keeps the mark, and so its leaders, on its last
    part: the parts carry the row's page and callback.
    """

    count = 0

    def __init__(self, text, style=None, *args, page=None, dots=True, number_font=None, callback=None, **options):
        if callback is None and page is not None:
            Leader.count += 1
            callback = f'paperLeader{Leader.count}'
            text += f'<onDraw name="{callback}" label="leader"/>'
        self.page, self.dots, self.number_font, self.callback = page, dots, number_font, callback
        super().__init__(text, style, *args, **options)

    def wrap(self, width, height):
        self.avail = width
        return super().wrap(width, height)

    def split(self, width, height):
        parts = super().split(width, height)
        for part in parts:
            part.page, part.dots, part.number_font, part.callback = (self.page, self.dots, self.number_font,
                                                                     self.callback)
        return parts

    def _leader(self, canvas, kind, label):
        if self.page is None:
            return
        info = canvas._curr_tx_info
        x, y = info['cur_x'], info['cur_y']
        size = self.style.fontSize
        font = self.number_font or self.style.fontName
        right = getattr(self, 'avail', self.width)
        canvas.saveState()
        canvas.setFillColor(INK)
        canvas.setFont(font, size)
        canvas.drawRightString(right, y, str(self.page))
        if self.dots:
            pitch = stringWidth('.', font, size) + size * 0.25
            end = right - stringWidth(NO_PAGE, font, size) - 2.5 * MM
            start = x + 1.5 * MM
            for step in range(max(0, int((end - start) // pitch))):
                canvas.drawString(end - (step + 1) * pitch, y, '.')
        canvas.restoreState()

    def drawOn(self, canvas, x, y, _sW=0):
        if self.callback:
            canvas.setNamedCB(self.callback, self._leader)
        super().drawOn(canvas, x, y, _sW)


class FormEntry(Flowable):
    """One numbered entry of the blank reference form: its number, then `lines` rules to the right edge."""

    def __init__(self, number, lines, caption, *, hang, pitch, font, size, small):
        super().__init__()
        self.number, self.lines, self.caption = number, max(1, lines), caption
        self.hang, self.pitch, self.font, self.size, self.small = hang, pitch, font, size, small

    def wrap(self, width, height):
        self.width = width
        self.height = self.pitch * self.lines + (self.small * 1.3 if self.caption else 0.0)
        return width, self.height

    def draw(self):
        canvas = self.canv
        canvas.saveState()
        canvas.setFillColor(INK)
        canvas.setStrokeColor(INK)
        canvas.setLineWidth(0.5)
        top = self.height
        for line in range(self.lines):
            base = top - self.pitch * (line + 1) + self.size * 0.25
            if line == 0:
                canvas.setFont(self.font, self.size)
                canvas.drawString(0, base + 1.5, f'{self.number}.')
            canvas.line(self.hang, base, self.width, base)
            if line == 0 and self.caption:
                canvas.setFont(f'{self.font}-Italic', self.small)
                canvas.drawString(self.hang, base - self.small * 1.15, self.caption)
                top -= self.small * 1.3
        canvas.restoreState()


# ---------------------------------------------------------------- title_page: reading the rows


def _choice_label(ctx, row):
    """The label key of a row whose wording a choice fact picks (Qabul qildi or Tekshirdi), else its own."""
    key = row.get('label')
    labels = row.get('labels') if isinstance(row.get('labels'), dict) else {}
    choice = row.get('choice')
    if isinstance(choice, str):
        value = ctx.fact(choice)
        picked = labels.get(str(value).strip().casefold()) if value else None
        if _has_label(ctx, picked):
            return picked
    return key if _has_label(ctx, key) else None


def _year(ctx, place, params):
    """The year a title page prints at its foot: the year field's (its fact, else its clock), the clock's, or none."""
    mode = params.get('year')
    if mode in (None, 'none'):
        return None
    for field_id in place.fields:
        field = ctx.entry.field(field_id) or {}
        if field.get('clock') == 'year' or field_id == 'year':
            value = ctx.fact(field_id)
            if value:
                return value
    return str(ctx.day.year) if mode == 'clock' else None


def _business_rows(ctx, place, params):
    """The rows of the cover form a business template declares (label, title, labels, foot) instead of rows.

    The fixed word is the kind, the paper's title (or a field) the title, each
    field the `labels` map names a credit row, the `foot` fields one foot line,
    and every other printable field of the placement a line under the title.
    """
    rows = []
    if _has_label(ctx, params.get('label')):
        rows.append({'role': 'kind', 'label': params['label'], 'style': 'display'})
    title = params.get('title')
    if isinstance(title, str) and ctx.entry.field(title):
        rows.append({'role': 'title', 'fact': title})
    else:
        rows.append({'role': 'title', 'own_title': True})
    labels = params.get('labels') if isinstance(params.get('labels'), dict) else {}
    foot = [field_id for field_id in params.get('foot') or () if isinstance(field_id, str)]
    for field_id in place.fields:
        field = ctx.entry.field(field_id) or {}
        if field_id in labels or field_id in foot or field_id == title or field.get('kind') in ('choice', 'flag',
                                                                                               'file', 'list'):
            continue
        rows.append({'role': 'subtitle', 'fact': field_id})
    for field_id, key in labels.items():
        rows.append({'role': 'credit', 'fact': field_id, 'label': key, 'colon': True})
    if foot:
        rows.append({'role': 'foot', 'facts': foot})
    return rows


def _resolved(ctx, place, row):
    """What one row prints: {text} or {blank} pieces, with its label; None when it prints nothing.

    A label with a {field} slot is the line itself ("«{subject}» fanidan"):
    filled when the fact is known, else drawn around a blank. A label without
    a slot is the word before the value (Bajardi:, Mavzu:). A missing fact
    that draws no blank leaves the row out; one that draws one is a rule
    with the row's caption.
    """
    role = row.get('role') or 'unit'
    key = _choice_label(ctx, row)
    facts = [row['fact']] if isinstance(row.get('fact'), str) else [
        field_id for field_id in row.get('facts') or () if isinstance(field_id, str)]
    caption = ctx.label(row['blank_caption']) if _has_label(ctx, row.get('blank_caption')) else ''
    found = {'role': role, 'style': row.get('style') or ROLE_STYLE.get(role, 'body'), 'caption': caption,
             'lines': _int(row.get('blank_lines'), BLANK_LINES.get(role, 1), 1, 4), 'sign': bool(row.get('sign')),
             'label': '', 'text': None, 'blank': False, 'prefix': '', 'suffix': ''}
    raw = ''
    if key:
        raw = ctx.template['labels'][key].get(ctx.locale) or ctx.template['labels'][key].get('en', '')
    if row.get('own_title'):
        title = ' '.join(str(ctx.content.get('title') or '').split())
        return dict(found, text=title) if title else None
    if not facts:
        return dict(found, text=ctx.label(key)) if key else None
    values = [ctx.fact(field_id) for field_id in facts]
    if role == 'foot':
        shown = [value for value in values if value]
        blanks = [field_id for field_id, value in zip(facts, values) if not value and ctx.blank(field_id)]
        if not shown and not blanks:
            return None
        if blanks and not shown:
            return dict(found, blank=True)
        return dict(found, text=DASH.join(shown))
    field_id, value = facts[0], values[0]
    if value is None and role in ('topic', 'title'):
        # The topic is asked for before the paper is written and the paper's title is made from it.
        value = ' '.join(str(ctx.content.get('title') or '').split()) or None
    slot = SLOT.search(raw) if raw else None
    if slot:
        if value is not None:
            return dict(found, text=ctx.label(key))
        if not ctx.blank(field_id):
            return None
        before, after = raw[:slot.start()], raw[slot.end():]
        # A blank needs no quotation marks around it: «____» fanidan reads as ____ fanidan.
        return dict(found, blank=True, prefix=SLOT.sub('', before).strip().rstrip(QUOTES).strip(),
                    suffix=SLOT.sub('', after).strip().lstrip(QUOTES).strip())
    label = ctx.label(key) if key else ''
    if label and row.get('colon') and not label.rstrip().endswith((':', '.')):
        label = label.rstrip() + ':'
    if value is not None:
        return dict(found, label=label, text=value)
    if ctx.blank(field_id):
        return dict(found, label=label, blank=True)
    return None


# ---------------------------------------------------------------- title_page: drawing


def _centred(ctx, text, style, width, inset=True):
    """A centred paragraph wrapped inside the measure at the narrowest width that keeps its lines."""
    markup = ctx.text(text, style)
    measure = min(width, MEASURE_MM * MM) if inset else width
    room = _balanced(markup, style, measure)
    side = (width - room) / 2
    return Paragraph(markup, _style(ctx, style, alignment=TA_CENTER, leftIndent=side, rightIndent=side))


def _display(ctx, text, scale, width):
    """The kind of work in large tracked capitals, stepped down to fit; on two lines (by words) when one cannot."""
    text = ctx.plain(text).upper()
    font = _font(ctx, 'Bold')
    tracking = TRACKING_PT * scale

    def wide(line, size):
        return stringWidth(line, font, size) + tracking * max(0, len(line) - 1)

    def tracked(line, size):
        return Tracked(line, font, size, size * 1.15, tracking)
    start, floor = ctx.size * DISPLAY * scale, ctx.size * DISPLAY_FLOOR * scale
    size = start
    while size > floor and wide(text, size) > width:
        size -= 0.5
    if wide(text, size) <= width:
        return [tracked(text, size)]
    words = text.split(' ')
    if len(words) > 1:
        cut = min(range(1, len(words)), key=lambda at: abs(len(' '.join(words[:at])) - len(' '.join(words[at:]))))
        lines = [' '.join(words[:cut]), ' '.join(words[cut:])]
        size = start
        while size > ctx.size and max(wide(line, size) for line in lines) > width:
            size -= 0.5
        if max(wide(line, size) for line in lines) <= width:
            return [tracked(line, size) for line in lines]
    size = floor
    while size > 6 and wide(text, size) > width:
        size -= 0.5
    return [tracked(text, size)]


def _topic(ctx, text, scale, width):
    """The topic in bold, a step smaller for each line past five."""
    for step in TOPIC_STEPS:
        size = ctx.size * step * scale
        style = _style(ctx, 'bold', fontSize=size, leading=size * 1.42)
        made = _centred(ctx, text, style, width)
        made.wrap(width, 10_000)
        if len(getattr(made.blPara, 'lines', ()) or ()) <= TOPIC_LINES:
            break
    return made


def _line_style(ctx, kind, scale):
    """The paragraph style of a centred row: body, bold, bold_caps, italic, small, at the sheet's scale."""
    base = {'bold': 'bold', 'bold_caps': 'bold', 'italic': 'italic', 'small': 'small'}.get(kind, 'body')
    size = ctx.styles[base].fontSize * (0.94 if kind == 'bold_caps' else 1.0) * scale
    return _style(ctx, base, fontSize=size, leading=size * 1.36)


def _blank(ctx, found, scale, *, rule_mm=None, x=0.0, width=None, bold=False, align='centre'):
    size = ctx.size * scale
    rule = (rule_mm or BLANK_MM.get(found['role'], 95)) * MM * scale if width is None else width
    return Blank(rule=rule, prefix=ctx.plain(found['prefix']), suffix=ctx.plain(found['suffix']),
                 caption=ctx.plain(found['caption']), font=ctx.face, size=size, small=max(7.0, _cap_size(ctx) * scale),
                 bold=bold, lines=found['lines'], align=align, x=x)


def _credit_table(ctx, group, scale, label_width, value_width):
    """One credit group (a credit row and its sub rows): the bold label, then the values or blanks in a column."""
    size = ctx.size * scale
    body = _style(ctx, 'body', fontSize=size, leading=size * 1.32, alignment=TA_LEFT)
    small = _style(ctx, body, fontSize=size * 0.92, leading=size * 1.22)
    bold = _style(ctx, 'bold', fontSize=size, leading=size * 1.32, alignment=TA_LEFT)
    cell = []
    label = ''
    for found in group:
        style = body if found['role'] == 'credit' else small
        label = label or found['label']
        if found['blank']:
            cell.append(Blank(rule=value_width, caption=ctx.plain(found['caption']), font=ctx.face, size=style.fontSize,
                              small=max(7.0, _cap_size(ctx) * scale), lines=found['lines'], align='left',
                              room=style.fontSize * 1.05))
        else:
            for piece in str(found['text']).split('\n'):
                if piece.strip():
                    cell.append(Paragraph(ctx.text(piece.strip(), style), style))
    if any(found['sign'] for found in group):
        # The signature and its date close the group, under the name and the sub rows.
        date = SIGN_DATE[ctx.locale].format(year=ctx.day.year)
        cell.append(Spacer(1, size * 0.4))
        cell.append(Blank(rule=min(30 * MM, value_width * 0.4), suffix=ctx.plain(date), caption=SIGN_WORD[ctx.locale],
                          font=ctx.face, size=small.fontSize, small=max(7.0, _cap_size(ctx) * scale), align='left',
                          room=small.fontSize * 1.6))
    rows = [[Paragraph(ctx.text(label, bold), bold) if label else '', cell]]
    table = Table(rows, colWidths=[label_width, value_width])
    table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0),
                               ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('TOPPADDING', (0, 0), (-1, -1), 0),
                               ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
    return table


def _sheet(ctx, rows, scale, height, year):
    """The Sheet of resolved `rows` at `scale`."""
    width = ctx.width
    zones = {'top': [], 'middle': [], 'credit': [], 'foot': []}
    lead = ctx.leading * scale
    groups, middle_seen = [], False
    for found in rows:
        role = found['role']
        if role in CREDIT:
            if role == 'credit_sub' and groups:
                groups[-1].append(found)
            else:
                groups.append([found])
            continue
        if role == 'foot':
            continue
        zone = 'middle' if role in MIDDLE or (middle_seen and role not in TOP) else 'top'
        middle_seen = middle_seen or zone == 'middle'
        made = []
        if found['blank']:
            made.append(_blank(ctx, found, scale))
            if found['label']:
                made.insert(0, _centred(ctx, found['label'], _line_style(ctx, 'italic', scale), width))
        elif role == 'kind' or found['style'] == 'display':
            made += _display(ctx, found['text'], scale, width)
        elif role in ('topic', 'title') or found['style'] == 'topic':
            # The topic stands under its word (Mavzu:) in bold, in capitals when the row says bold_caps.
            if found['label']:
                made.append(_centred(ctx, found['label'], _line_style(ctx, 'italic', scale), width))
            text = found['text'].upper() if found['style'] == 'bold_caps' else found['text']
            made.append(_topic(ctx, text, scale, width))
        else:
            kind = found['style']
            text = found['text'] if not found['label'] else f"{found['label']} {found['text']}"
            made.append(_centred(ctx, text.upper() if kind == 'bold_caps' else text, _line_style(ctx, kind, scale),
                                 width))
        gap = 0.0 if not zones[zone] else lead * GAPS.get(role, 0.2)
        for number, flowable in enumerate(made):
            zones[zone].append((flowable, 0.0, gap if number == 0 else lead * 0.25))
    if groups:
        bold = _style(ctx, 'bold', fontSize=ctx.size * scale)
        widest = max(stringWidth(ctx.plain(found['label']), bold.fontName, bold.fontSize)
                     for group in groups for found in group[:1]) if any(group[0]['label'] for group in groups) else 0
        label_width = widest + 3 * MM if widest else 0.0
        x_label = min(width / 2 - CREDIT_LEFT_MM * MM, width - CREDIT_VALUE_MM * MM - label_width)
        x_label = max(0.0, x_label)
        value_width = width - x_label - label_width
        for number, group in enumerate(groups):
            zones['credit'].append((_credit_table(ctx, group, scale, label_width, value_width), x_label,
                                    lead * 0.6 if number else 0.0))
    foot = next((found for found in rows if found['role'] == 'foot'), None)
    if foot is not None or year:
        style = _style(ctx, 'bold', fontSize=ctx.size * scale, leading=ctx.size * scale * 1.3, alignment=TA_CENTER)
        if foot is not None and foot['blank']:
            zones['foot'].append((_blank(ctx, dict(foot, suffix=f'– {year}' if year else ''), scale, bold=True),
                                  0.0, 0.0))
        else:
            text = DASH.join(piece for piece in ((foot or {}).get('text'), year) if piece)
            zones['foot'].append((Paragraph(ctx.text(text, style), style), 0.0, 0.0))
    return Sheet(zones, height, gap=10 * MM * scale, credit_gap=14 * MM * scale)


def title_page(ctx, place):
    """A whole first sheet, every line placed by its role; see the module's docstring.

    params: rows ([{role, fact | facts, label, style, blank_caption,
    blank_lines, choice, labels, sign}]: role ministry | institution | faculty
    | kafedra | direction | place | unit (the head) | subject | kind | topic
    (the middle) | credit | credit_sub (the column: who wrote, who checks;
    sub rows stand under the credit before them) | foot (the city); `choice`
    a choice field whose value picks the label key from `labels`; `sign` a
    signature rule and a date to fill in under the credit); year clock |
    fact | none (at the foot after the city, the year field's value or the
    clock's). The cover form of the business templates is read too: label
    (the fixed word), title (content_title, or a field id), labels ({field
    id: label key}: credit rows), foot (field ids joined at the foot).
    """
    params = _params(place)
    raw = params.get('rows') if isinstance(params.get('rows'), list) else _business_rows(ctx, place, params)
    rows = [found for found in (_resolved(ctx, place, row) for row in raw if isinstance(row, dict)) if found]
    year = _year(ctx, place, params)
    if not rows and not year:
        return []
    height = ctx.frame_height - 1
    for scale in SCALES:
        sheet = _sheet(ctx, rows, scale, height, year)
        if sheet.needed(ctx.width) <= height:
            return [sheet]
    # Not even the smallest sheet holds it: the rows flow, on as many pages as they need.
    ctx.warn('title_page_over')
    flowing = []
    for zone in ('top', 'middle', 'credit', 'foot'):
        for flowable, x, before in sheet.zones[zone]:
            flowing.append(Spacer(1, before) if before else None)
            flowing.append(flowable)
    return [flowable for flowable in flowing if flowable is not None] + [Gap(1, ctx.leading)]


def _title_plain(ctx, place):
    """Up to eight short centred lines, as today's title page: each row's text, or a blank where it draws one."""
    params = _params(place)
    raw = params.get('rows') if isinstance(params.get('rows'), list) else _business_rows(ctx, place, params)
    lines = []
    for row in raw:
        found = _resolved(ctx, place, row) if isinstance(row, dict) else None
        if not found:
            continue
        text = found['text'] if not found['blank'] else '_' * 16
        lines.append(' '.join(piece for piece in (found['label'], text) if piece))
    year = _year(ctx, place, params)
    if year:
        lines.append(year)
    style = _style(ctx, 'body', alignment=TA_CENTER)
    return [Paragraph(ctx.text(line, style), style) for line in lines[:8]] + [Gap(1, ctx.leading)]


block('title_page', fallback=_title_plain)(title_page)


# ---------------------------------------------------------------- toc


def _split_number(text):
    found = NUMBER.match(text)
    return (found.group(1), found.group(2)) if found else ('', text)


def _toc_rows(ctx, entries, *, numbers, leaders, strip):
    """The rows of a contents: (level, text, page) entries as Leader paragraphs in three aligned columns."""
    if not entries:
        return []
    split = [(level, *_split_number(' '.join(text.split())), page) for level, text, page in entries]
    body = ctx.styles['body']
    bold = _font(ctx, 'Bold')
    first = [stringWidth(number, bold, body.fontSize) for level, number, _, _ in split if level == 1 and number]
    second = [stringWidth(number, body.fontName, body.fontSize) for level, number, _, _ in split
              if level > 1 and number]
    column = max([12.5 * MM] + [width + 2.5 * MM for width in first]) if first else 0.0
    inner = max([12.5 * MM] + [width + 2.5 * MM for width in second]) if second else 12.5 * MM
    page_room = (stringWidth('000', body.fontName, body.fontSize) + 3 * MM) if numbers else 0.0
    rows = []
    for level, number, text, page in split:
        heavy = level == 1 and not strip
        face = bold if heavy else body.fontName
        number_at = 0.0 if level == 1 else column
        text_at = (number_at + (column if level == 1 else inner)) if number else (0.0 if level == 1 else column)
        style = _style(ctx, 'bold' if heavy else 'body', alignment=TA_LEFT, leftIndent=text_at,
                       rightIndent=page_room + (8 * MM if numbers else 0.0), bulletIndent=number_at,
                       bulletFontName=face, bulletFontSize=body.fontSize,
                       spaceBefore=ctx.leading * (0.1 if strip else 0.15) if rows and level == 1 else 0.0)
        shown = (page if page is not None else NO_PAGE) if numbers else None
        rows.append(Leader(ctx.text(text, style), style, page=shown, dots=leaders, number_font=body.fontName,
                           bulletText=number or None))
    return rows


def toc(ctx, place):
    """The contents: the headings drawn, with dot leaders and their pages; or the short plan strip.

    params: label (a label key; else the part's heading); levels 1 | 2 (|3);
    page_numbers (true; false for a strip); leaders (true); style page |
    strip (a compact plan: the label in bold on the left and the headings
    without numbers of pages, as a lecture's notes open). The headings are
    those the heading blocks marked (`in_toc`), read when the contents is laid
    out: wherever it stands in the flow, it lists the whole paper.
    """
    params = _params(place)
    strip = params.get('style') == 'strip'
    numbers = bool(params.get('page_numbers', not strip)) and not strip
    leaders = bool(params.get('leaders', True)) and numbers
    levels = _int(params.get('levels'), 2, 1, 3)
    label = _word(ctx, params.get('label')) if params.get('label') else ctx.heading(place.part, place.section)
    made = []
    if label:
        if strip:
            style = _style(ctx, 'bold', alignment=TA_LEFT, keepWithNext=1)
        else:
            style = _style(ctx, 'h1', alignment=TA_CENTER, keepWithNext=1)
        made.append(Paragraph(ctx.text(label, style), style))
        made.append(Gap(1, ctx.leading * (0.3 if strip else 0.8)))
        made[-1].keepWithNext = 1

    def make():
        # A strip prints no page, so it reads the marks without asking the engine for one more build.
        entries = ctx.contents() if numbers else [(level, text, None) for level, text in ctx.marks]
        return _toc_rows(ctx, [entry for entry in entries if entry[0] <= levels], numbers=numbers, leaders=leaders,
                         strip=strip)
    made.append(Lazy(make))
    return _finish(place, made, before=0.0, after=ctx.leading * (0.5 if strip else 0.0))


def _toc_plain(ctx, place):
    """The label and the headings as plain lines, numbered as they are drawn."""
    params = _params(place)
    label = _word(ctx, params.get('label')) if params.get('label') else ctx.heading(place.part, place.section)
    levels = _int(params.get('levels'), 2, 1, 3)
    made = [Paragraph(ctx.text(label, 'bold'), ctx.styles['bold'])] if label else []

    def make():
        return [Paragraph(ctx.text(text, 'body'), _style(ctx, 'body', leftIndent=(level - 1) * 12.5 * MM))
                for level, text in ctx.marks if level <= levels]
    return made + [Lazy(make), Gap(1, ctx.leading * 0.5)]


block('toc', fallback=_toc_plain)(toc)


# ---------------------------------------------------------------- reference_list


def _entry_text(item):
    """A source item as one entry: its label and text, as the model split them, without a typed number."""
    label = str(item.get('label') or '').strip()
    text = ' '.join(str(item.get(key) or '').strip() for key in ('text', 'value') if str(item.get(key) or '').strip())
    if label and text:
        joined = f'{label} {text}' if label.endswith(('.', ',', ':', ';')) else _item_text(item)
    else:
        joined = label or text
    return TYPED_MARKER.sub('', ' '.join(joined.split()), count=1)


def _entries(section):
    """The verified sources of a section: its items, then the lines of its body, each once."""
    found = [_entry_text(item) for item in _items(section)]
    found += [TYPED_MARKER.sub('', line, count=1) for line in _lines(section)]
    seen, kept = set(), []
    for text in found:
        key = ' '.join(text.casefold().split())
        if text and key not in seen:
            seen.add(key)
            kept.append(text)
    return kept


def _group(text):
    if NORMATIVE.search(text):
        return 'normative'
    if ONLINE.search(text):
        return 'online'
    return 'literature'


def _group_word(ctx, name):
    key = f'group_{name}'
    return ctx.label(key) if _has_label(ctx, key) else GROUP_WORDS[name][ctx.locale]


def _form_caption(ctx, params):
    key = params.get('caption') or 'cap_reference'
    return ctx.label(key) if _has_label(ctx, key) else REF_CAPTION[ctx.locale]


def reference_list(ctx, place):
    """The verified sources, numbered and hanging; with none, a numbered form of ruled lines to fill in.

    params: label (a label key: the heading, centred, in the contents
    unless in_toc is false; else the part's heading); blank_entries (10: the
    entries of the empty form); blank_lines (2: rules per empty entry);
    groups (group labels, laws first, then books and articles, then online
    sources, when there are six entries or more in two groups or more; the
    template's group_normative, group_literature and group_online labels,
    else the built-in words); caption (a label key under the form's first
    rule; cap_reference, else the built-in words).
    """
    params = _params(place)
    label = _word(ctx, params.get('label')) if params.get('label') else ctx.heading(place.part, place.section)
    made = []
    if label:
        style = _style(ctx, 'h1', alignment=TA_CENTER, keepWithNext=1)
        if params.get('in_toc', True):
            made.append(ctx.mark(1, ' '.join(label.split())))
        made.append(Paragraph(ctx.text(label, style), style))
        gap = Gap(1, ctx.leading * 0.8)
        gap.keepWithNext = 1
        made.append(gap)
    entries = _entries(place.section)
    body = ctx.styles['body']
    hang = max(10 * MM, stringWidth(f'{max(len(entries), _int(params.get("blank_entries"), 10, 1, 60))}.',
                                    body.fontName, body.fontSize) + 2.5 * MM)
    if entries:
        ordered = [(None, text) for text in entries]
        if params.get('groups'):
            grouped = {name: [text for text in entries if _group(text) == name] for name in GROUPS}
            present = [name for name in GROUPS if grouped[name]]
            if len(entries) >= GROUP_FROM and len(present) > 1:
                ordered = [(name if index == 0 else None, text) for name in present
                           for index, text in enumerate(grouped[name])]
        _over(ctx, params, len(entries))
        number = 0
        for group, text in ordered:
            if group:
                heading = _style(ctx, 'italic', alignment=TA_LEFT, leftIndent=hang, keepWithNext=1,
                                 spaceBefore=ctx.leading * (0.6 if number else 0.0))
                made.append(Paragraph(ctx.text(_group_word(ctx, group), heading), heading))
            number += 1
            style = _style(ctx, 'body', alignment=TA_LEFT, leftIndent=hang, bulletIndent=0,
                           bulletFontName=body.fontName, bulletFontSize=body.fontSize,
                           spaceBefore=ctx.leading * 0.25 if number > 1 and not group else ctx.leading * 0.1)
            made.append(Paragraph(ctx.text(text, style), style, bulletText=f'{number}.'))
    else:
        count = _int(params.get('blank_entries'), 10, 1, 60)
        lines = _int(params.get('blank_lines'), 2, 1, 4)
        caption = ctx.plain(_form_caption(ctx, params))
        pitch = max(16.0, ctx.size * 1.75)
        for number in range(1, count + 1):
            entry = FormEntry(number, lines, caption if number == 1 else '', hang=hang, pitch=pitch, font=ctx.face,
                              size=ctx.size, small=max(7.0, _cap_size(ctx)))
            if number > 1:
                entry.spaceBefore = ctx.size * 0.45 if lines > 1 else 0.0
            made.append(entry)
    return _finish(place, made, after=ctx.leading * 0.25)


def _over(ctx, params, count):
    limit = _int(params.get('max_items'), 0, 0, 200)
    if limit and count > limit:
        ctx.warn('reference_list_over')


def _references_plain(ctx, place):
    """Numbered lines of the sources, or numbered underscore lines to fill in."""
    params = _params(place)
    label = _word(ctx, params.get('label')) if params.get('label') else ctx.heading(place.part, place.section)
    made = [Paragraph(ctx.text(label, 'bold'), ctx.styles['bold'])] if label else []
    entries = _entries(place.section) or ['_' * 40] * _int(params.get('blank_entries'), 10, 1, 60)
    made += [Paragraph(ctx.text(f'{number}. {text}', 'body'), ctx.styles['body'])
             for number, text in enumerate(entries, 1)]
    return made + [Gap(1, ctx.leading * 0.5)]


block('reference_list', fallback=_references_plain)(reference_list)


# ---------------------------------------------------------------- samples


def _text3(uz, ru, en):
    return {'uz': uz, 'ru': ru, 'en': en}


# Invented facts of a mustaqil ish: no real person or institution.
SAMPLE_FACTS = {
    'topic': _text3('Maktabda raqamli o‘quv resurslaridan foydalanish', 'Цифровые учебные ресурсы в школе',
                    'Digital learning resources at school'),
    'work_kind': _text3('mustaqil_ish', 'referat', 'referat'),
    'ministry': _text3('Namuna viloyati ta’lim boshqarmasi', 'Управление образования Образцовой области',
                       'Example Regional Education Board'),
    'institution': _text3('Gulzorobod davlat pedagogika instituti', 'Гулзорабадский педагогический институт',
                          'Gulzorobod Pedagogical Institute'),
    'faculty_department': _text3('Boshlang‘ich ta’lim fakulteti', 'Факультет начального образования',
                                 'Faculty of Primary Education'),
    'subject': _text3('Pedagogika', 'Педагогика', 'Pedagogy'),
    'student_name': _text3('Qodirova Malika Anvar qizi', 'Кадырова Малика Анваровна', 'Malika Qodirova'),
    'student_group': _text3('2-kurs, 204-guruh', '2 курс, группа 204', 'Year 2, group 204'),
    'teacher': _text3('dotsent Hamidov Sardor', 'доцент Хамидов Сардор', 'Associate Professor Sardor Hamidov'),
    'city': _text3('Gulzorobod', 'Гулзорабад', 'Gulzorobod'),
}

SAMPLE_SECTIONS = {
    'introduction': _text3('Raqamli texnologiyalar maktab hayotiga tobora chuqurroq kirib bormoqda.',
                           'Цифровые технологии всё глубже входят в школьную жизнь.',
                           'Digital technologies are entering school life ever more deeply.'),
    'chapter': (_text3('Raqamli resurslarning nazariy asoslari', 'Теоретические основы цифровых ресурсов',
                       'The theoretical foundations of digital resources'),
                _text3('Bobda asosiy tushunchalar ko‘rib chiqiladi.', 'В главе рассматриваются основные понятия.',
                       'The chapter examines the main concepts.')),
    'section_a': (_text3('Tushuncha va mohiyati', 'Понятие и сущность', 'Concept and essence'),
                  _text3('Raqamli o‘quv resursi deganda o‘quv materialini elektron shaklda taqdim etuvchi vosita '
                         'tushuniladi.', 'Цифровой учебный ресурс — средство, представляющее учебный материал в '
                         'электронной форме.', 'A digital learning resource presents learning material in electronic '
                         'form.')),
    'references': [
        _text3('Namuna viloyati ta’lim boshqarmasining «Raqamli maktab» nizomi. – Gulzorobod, 2024.',
               'Положение «Цифровая школа» Образцовой области. – Гулзорабад, 2024.',
               'Example Regional Education Board. Regulation on the Digital School. – Gulzorobod, 2024.'),
        _text3('Rahimova D. B. Raqamli pedagogika asoslari. – Gulzorobod: Ilm, 2022. – 184 b.',
               'Рахимова Д. Б. Основы цифровой педагогики. – Гулзорабад: Илм, 2022. – 184 с.',
               'Rahimova D. B. Foundations of Digital Pedagogy. – Gulzorobod: Ilm, 2022. – 184 p.'),
        _text3('Sobirov A. K. Maktabda axborot texnologiyalari. – Gulzorobod, 2021. – 212 b.',
               'Собиров А. К. Информационные технологии в школе. – Гулзорабад, 2021. – 212 с.',
               'Sobirov A. K. Information Technology at School. – Gulzorobod, 2021. – 212 p.'),
        _text3('Tursunov B. Interaktiv dars usullari // Pedagogik izlanishlar. – 2023. – № 4.',
               'Турсунов Б. Интерактивные методы урока // Педагогические поиски. – 2023. – № 4.',
               'Tursunov B. Interactive lesson methods // Pedagogical Studies. – 2023. – No. 4.'),
        _text3('Karimova L. Elektron resurslar. – Gulzorobod, 2020. – 96 b.',
               'Каримова Л. Электронные ресурсы. – Гулзорабад, 2020. – 96 с.',
               'Karimova L. Electronic Resources. – Gulzorobod, 2020. – 96 p.'),
        _text3('Resurslar katalogi [Elektron resurs]. – URL: https://example.com/katalog/boshlangich-sinflar',
               'Каталог ресурсов [Электронный ресурс]. – URL: https://example.com/katalog/boshlangich-sinflar',
               'Catalogue of resources [online]. – URL: https://example.com/katalog/boshlangich-sinflar'),
    ],
}

SAMPLES = (
    {'block': 'title_page', 'case': 'rows, every fact, ministry, the choice of word', 'part': 'title_page',
     'params': 'template'},
    {'block': 'title_page', 'case': 'rows, every fact a blank with its caption', 'part': 'title_page',
     'params': 'template', 'blank': True},
    {'block': 'title_page', 'case': 'cover form: kind, title, labelled rows, foot', 'part': 'title_page',
     'fields': ['subject', 'student_name', 'teacher', 'city', 'year'],
     'params': {'label': 'kind_referat', 'title': 'content_title', 'labels': {'student_name': 'done_by',
                                                                              'teacher': 'accepted_by'},
                'foot': ['city', 'year']}},
    {'block': 'toc', 'case': 'page numbers and leaders, two levels', 'part': 'plan',
     'params': {'label': 'plan', 'levels': 2, 'page_numbers': True, 'leaders': True, 'style': 'page'}},
    {'block': 'toc', 'case': 'strip, one level, no page numbers', 'part': 'plan',
     'params': {'label': 'plan', 'levels': 1, 'page_numbers': False, 'style': 'strip'}},
    {'block': 'reference_list', 'case': 'verified sources in groups', 'part': 'references',
     'params': {'label': 'references', 'groups': True}},
    {'block': 'reference_list', 'case': 'no source: the ruled form', 'part': 'references', 'empty': True,
     'params': {'label': 'references', 'blank_entries': 5, 'blank_lines': 2}},
)


def _sample_sections(locale, facts=True, sources=True):
    sections = []
    if facts:
        sections.append({'id': 'facts', 'heading': '', 'body': '', 'layout': 'list',
                         'items': [{'label': key, 'text': value[locale]} for key, value in SAMPLE_FACTS.items()]})
    sections.append({'id': 'introduction', 'heading': '', 'body': SAMPLE_SECTIONS['introduction'][locale],
                     'layout': 'text', 'items': []})
    for part_id in ('chapter', 'section_a'):
        heading, body = SAMPLE_SECTIONS[part_id]
        sections.append({'id': part_id, 'heading': heading[locale], 'body': body[locale], 'layout': 'text',
                         'items': []})
    sections.append({'id': 'references', 'heading': '', 'body': '', 'layout': 'list',
                     'items': [{'label': '', 'text': text[locale]} for text in SAMPLE_SECTIONS['references']]
                     if sources else []})
    return sections


def sample_paper(locale='uz', samples=None):
    """(entry, template, content) of a mustaqil ish that draws `samples` (all of SAMPLES by default), one each.

    The entry and the page are the real mustaqil ish's; a sample whose params
    are 'template' takes the template's own title page rows. A contents
    sample is followed by three headings for it to list. Facts are left out
    when every sample drawn is a blank one, the sources when every reference
    sample is the empty form.
    """
    import copy

    from ...categories import catalogue
    chosen = SAMPLES if samples is None else tuple(samples)
    entry = catalogue.get('pdf.mustaqil_ish')
    template = copy.deepcopy(catalogue.template('academic_mustaqil_ish'))
    rows = template['flow'][0]['params']
    flow = []
    for sample in chosen:
        params = copy.deepcopy(rows) if sample.get('params') == 'template' else dict(sample.get('params') or {})
        placement = {'block': sample['block'], 'part': sample['part'], 'params': params}
        fields = sample.get('fields') or (template['flow'][0]['fields'] if sample['block'] == 'title_page' else None)
        if fields:
            placement['fields'] = list(fields)
        flow.append(placement)
    if any(sample['block'] == 'toc' for sample in chosen):
        flow += [{'block': 'heading', 'part': 'introduction', 'params': {'level': 1, 'align': 'centre', 'caps': True}},
                 {'block': 'heading', 'part': 'chapter', 'params': {'level': 1, 'numbering': 'arabic'}},
                 {'block': 'heading', 'part': 'section_a', 'params': {'level': 2, 'numbering': 'decimal'}}]
    template.update(flow=flow, page_rule={'kind': 'flow'})
    facts = not all(sample.get('blank') for sample in chosen)
    references = [sample for sample in chosen if sample['block'] == 'reference_list']
    sources = not references or not all(sample.get('empty') for sample in references)
    content = {'title': SAMPLE_FACTS['topic'][locale], 'sections': _sample_sections(locale, facts, sources),
               'questions': []}
    return entry, template, content
