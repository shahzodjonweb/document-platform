"""The fifteen core blocks every paper family draws with (architecture 6.6, blocks.json, package R1).

paragraph, line, heading, doc_title, list, table, kv_table, callout,
inline_blank, ruled_blank, signature_row, date_line, doc_head, party_block and
approval_block. A family module (academic, study, official, business,
regulations) adds only what is its own; an ariza is drawn by these alone.

How they are written, so every family's paper agrees with every other:

- Words. Every string goes through `ctx.text` (a Paragraph) or `ctx.plain` (a
  canvas string): the house apostrophes, the no-break glue and the inline
  blanks are text_rules', never a block's. A fixed word is a template label
  (`ctx.label`); only the few words the official forms share (the signature
  captions, a chapter word, a table caption, a blank date) have a built-in
  wording in uz, ru and en, used when the template carries no label of that
  name. A block never writes a fact: a value is the verified one, the clock's,
  or a blank where the field draws one.
- Nothing the customer gave is cut. A `max_items` or `max_lines` that the
  content runs past is warned (`<block>_over`), never truncated: the model is
  held to the bound, and a dropped enclosure or signer would be a lost fact.
- Space. A block's gap above it is the first flowable's spaceBefore, which a
  frame drops at the top of a page; its gap below is a `Gap`, which never
  pushes a page of its own. Every block reads `before_pt` and `after_pt`
  over its defaults, which are set to the official family's measures (the
  ariza mock): 30 pt over the title, 24 under it, a line's leading over an
  enclosure list and the signatures.
- Headings keep with what follows (keep-with-next through their gap), and a
  block whose text may end before a closing group ends with a Paragraph and a
  Gap, so fit.py's keep group can carry its last lines.
- A block draws nothing ([]) when it has nothing to draw: an empty part, a
  table without rows, a party without one line.

`SAMPLES` lists one placement per parameter variant, and `sample_paper(locale)`
makes the paper that draws them all, invented content in the three languages:
the block sheet and the tests draw it through `render_paper`. A sample is
{block, case, part?, fields?, params}; its part and fields are the sample
entry's (`SAMPLE_PARTS`, `SAMPLE_FIELDS`), its labels the sample template's.
"""
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Flowable, Paragraph, Spacer, Table, TableStyle
from reportlab.platypus.flowables import PageBreakIfNotEmpty

from ..ctx import INK
from ..registry import block
from ..text import MM

TINT = colors.Color(0.94, 0.94, 0.94)
ALIGN = {'left': TA_LEFT, 'centre': TA_CENTER, 'center': TA_CENTER, 'right': TA_RIGHT, 'justify': TA_JUSTIFY}
SLOT = re.compile(r'\{(\w+)\}')
# The cells of a row's text: ` | ` as the catalogue says, read loosely ("1|dona", a bare "|" of empty cells).
CELL = re.compile(r'\s*\|\s*')
# A marker the model typed at the start of an item, which the list draws itself.
TYPED_MARKER = re.compile(r'^\s*(?:[-–—•*·]|\d{1,2}[.)]|[a-zа-я]\))\s+', re.IGNORECASE)
# A parenthetical at the end of a field's label ("Ariza sanasi (ixtiyoriy)"): bot wording, not a paper's.
TRAILING_NOTE = re.compile(r'\s*\([^()]*\)\s*$')
LETTERS = {'ru': 'абвгдежзиклмнопрстуфхцчшщэюя', 'uz': 'abcdefghijklmnopqrstuvwxyz', 'en': 'abcdefghijklmnopqrstuvwxyz'}
# Fixed words the official forms share, used when a template has no label of the name.
WORDS = {
    'date': {'uz': 'Sana', 'ru': 'Дата', 'en': 'Date'},
    'sign': {'uz': 'Imzo', 'ru': 'Подпись', 'en': 'Signature'},
    'name': {'uz': 'F.I.Sh.', 'ru': 'Ф.И.О.', 'en': 'Name'},
    'post': {'uz': 'Lavozimi', 'ru': 'Должность', 'en': 'Position'},
}
CHAPTER = {'uz': '{n}-BOB', 'ru': 'ГЛАВА {n}', 'en': 'CHAPTER {n}'}
TABLE_CAPTION = {'uz': '{n}-jadval', 'ru': 'Таблица {n}', 'en': 'Table {n}'}
# A date to fill in by hand; {year} is the clock's year or a blank.
DATE_BLANK = {'uz': '«___» ________ {year}-yil', 'ru': '«___» ________ {year} г.', 'en': '___ ________ {year}'}
YEAR_BLANK = '20__'
ROMAN = ((1000, 'M'), (900, 'CM'), (500, 'D'), (400, 'CD'), (100, 'C'), (90, 'XC'), (50, 'L'), (40, 'XL'),
         (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I'))


# ---------------------------------------------------------------- flowables


class Gap(Spacer):
    """A gap under a block that never starts a page.

    Zero-size to the engine (not counted in a page's fill, not a printing
    flowable), measured whole inside a keep group, and at a page's foot it
    takes only the room left: a plain Spacer that does not fit moves to the
    next page and, at the end of a paper, adds a blank one.
    """

    _ZEROSIZE = 1

    def wrap(self, width, height):
        return self.width, max(0.0, min(self.height, height))


class Hair(Flowable):
    """A rule across `width` (the frame's when None), with `above` and `below` points of air."""

    def __init__(self, width=None, thickness=0.5, above=2.0, below=2.0, dash=None):
        super().__init__()
        self.rule, self.thickness, self.above, self.below, self.dash = width, thickness, above, below, dash

    def wrap(self, width, height):
        self.width = min(self.rule or width, width)
        self.height = self.above + self.thickness + self.below
        return self.width, self.height

    def draw(self):
        canvas = self.canv
        canvas.saveState()
        canvas.setStrokeColor(INK)
        canvas.setLineWidth(self.thickness)
        if self.dash:
            canvas.setDash(*self.dash)
        y = self.below + self.thickness / 2
        canvas.line(0, y, self.width, y)
        canvas.restoreState()


class Tracked(Flowable):
    """One line of capitals with letter spacing (ReportLab's Paragraph has none), aligned in the frame."""

    def __init__(self, text, font, size, leading, tracking, align='centre'):
        super().__init__()
        self.text, self.font, self.size, self.leading = text, font, size, leading
        self.tracking, self.align = tracking, align

    def letters(self):
        # The Uzbek o‘ and g‘ mark (and the tutuq belgisi) belongs to the letter before it: tracked apart, "YO‘RIQNOMA"
        # would read as Y O ‘ R.
        return re.findall(r'.[‘’ʼ]?', self.text, re.S)

    def measure(self):
        return stringWidth(self.text, self.font, self.size) + self.tracking * max(0, len(self.letters()) - 1)

    def wrap(self, width, height):
        self.width, self.height = width, self.leading
        return width, self.leading

    def draw(self):
        canvas = self.canv
        line = self.measure()
        x = {'left': 0.0, 'right': self.width - line}.get(self.align, (self.width - line) / 2)
        y = (self.leading - self.size) / 2 + self.size * 0.2
        text = canvas.beginText(x, y)
        text.setFont(self.font, self.size)
        text.setFillColor(INK)
        for letter in self.letters():
            text.setTextOrigin(x, y)
            text.textOut(letter)
            x += stringWidth(letter, self.font, self.size) + self.tracking
        canvas.drawText(text)


class BlankRow(Flowable):
    """A ruled line to write on in a party column: a word before it (Tel.:), a case ending after it (ga), a caption.

    `x` is where the column starts in the frame and `width` its width; `room`
    the clear space above the rule for the hand.
    """

    def __init__(self, x, width, prefix, suffix, caption, font, size, small, room):
        super().__init__()
        self.x, self.column, self.prefix, self.suffix, self.caption = x, width, prefix, suffix, caption
        self.font, self.size, self.small, self.room = font, size, small, room

    def wrap(self, width, height):
        self.width = width
        # Under the rule: the caption and a little air, so the next line does not touch it.
        self.height = self.room + (self.small * 1.35 + 2 if self.caption else 3)
        return width, self.height

    def draw(self):
        canvas = self.canv
        base = self.height - self.room
        canvas.saveState()
        canvas.setFillColor(INK)
        canvas.setStrokeColor(INK)
        canvas.setLineWidth(0.5)
        canvas.setFont(self.font, self.size)
        start = self.x
        if self.prefix:
            canvas.drawString(start, base + 1.5, self.prefix)
            start += stringWidth(self.prefix + ' ', self.font, self.size)
        end = self.x + self.column
        if self.suffix:
            end -= stringWidth(self.suffix, self.font, self.size) + 1
            canvas.drawString(end + 1, base + 1.5, self.suffix)
        canvas.line(start, base, max(start + 10, end), base)
        if self.caption:
            canvas.setFont(f'{self.font}-Italic', self.small)
            canvas.drawCentredString((start + end) / 2, base - self.small * 1.05, self.caption)
        canvas.restoreState()


class Ruled(Flowable):
    """Room to write by hand: `lines` rules `pitch` apart, the label before the first, a caption under the last.

    `style` rules | captioned | box | dashed_box; a box is one rectangle as
    tall as its lines, its label inside at the top. Rules split between lines
    across a page; a box or a single rule never splits.
    """

    def __init__(self, *, label, lines, caption, rule, style, pitch, indent, font, size, small):
        super().__init__()
        self.label, self.lines, self.caption, self.rule = label, max(1, lines), caption, rule
        self.style, self.pitch, self.indent = style, pitch, indent
        self.font, self.size, self.small = font, size, small

    def _caption_room(self):
        return self.small * 1.4 if self.caption else 0.0

    def _room(self):
        return self.pitch * 0.8

    def wrap(self, width, height):
        self.width = width
        if self.style in ('box', 'dashed_box'):
            self.height = self.lines * self.pitch + self._caption_room()
        else:
            self.height = self._caption_room() + 3 + self.pitch * (self.lines - 1) + self._room()
        return width, self.height

    def _copy(self, **changes):
        made = dict(label=self.label, lines=self.lines, caption=self.caption, rule=self.rule, style=self.style,
                    pitch=self.pitch, indent=self.indent, font=self.font, size=self.size, small=self.small)
        made.update(changes)
        return Ruled(**made)

    def split(self, width, height):
        if self.style != 'rules' or self.lines < 2:
            return []
        fit = int((height - 3 - self._room()) // self.pitch) + 1
        if fit < 1 or fit >= self.lines:
            return []
        return [self._copy(lines=fit, caption=None), self._copy(lines=self.lines - fit, label=None)]

    def draw(self):
        canvas = self.canv
        canvas.saveState()
        canvas.setFillColor(INK)
        canvas.setStrokeColor(INK)
        canvas.setLineWidth(0.5)
        right = min(self.width, self.rule) if self.rule else self.width
        bottom = self._caption_room()
        if self.style in ('box', 'dashed_box'):
            if self.style == 'dashed_box':
                canvas.setDash(3, 2)
            canvas.rect(self.indent, bottom, right - self.indent, self.lines * self.pitch, stroke=1, fill=0)
            if self.label:
                canvas.setFont(self.font, self.small)
                canvas.drawString(self.indent + 1.8 * MM, bottom + self.lines * self.pitch - self.small * 1.3,
                                  self.label)
            rule_start, last = self.indent, bottom
        else:
            last = rule_start = None
            for number in range(self.lines):
                base = bottom + 3 + self.pitch * (self.lines - 1 - number)
                start = self.indent if number == 0 else 0.0
                if number == 0 and self.label:
                    canvas.setFont(self.font, self.size)
                    canvas.drawString(start, base + 2, self.label)
                    start += stringWidth(self.label, self.font, self.size) + 2 * MM
                canvas.line(start, base, max(start + 10, right), base)
                last, rule_start = base, start
        if self.caption:
            canvas.setFont(f'{self.font}-Italic', self.small)
            canvas.drawCentredString((rule_start + right) / 2, last - self.small * 1.1, self.caption)
        canvas.restoreState()


# ---------------------------------------------------------------- helpers


def _params(place):
    return place.params if isinstance(place.params, dict) else {}


def _num(value, default, low=None, high=None):
    """A number parameter, else `default`; clamped to low..high when given."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:
        return default
    if low is not None:
        number = max(low, number)
    if high is not None:
        number = min(high, number)
    return number


def _int(value, default, low=None, high=None):
    return int(_num(value, default, low, high))


def _has_label(ctx, key):
    return isinstance(key, str) and key in (ctx.template.get('labels') or {})


def _word(ctx, key, **slots):
    """A fixed word: the template's label `key`, else the built-in word of that name, else ''."""
    if _has_label(ctx, key):
        return ctx.label(key, **slots)
    if isinstance(key, str) and key in WORDS:
        return WORDS[key][ctx.locale]
    return ''


def _style(ctx, base='body', **changes):
    """A style made from one of the step's ten (they are shared: never changed in place)."""
    parent = ctx.styles[base] if isinstance(base, str) else base
    return ParagraphStyle(f'{parent.name}+', parent=parent, **changes)


def _font(ctx, kind=''):
    return f'{ctx.face}-{kind}' if kind else ctx.face


def _bold(ctx, text, style):
    """`text` as markup in the bold face of the step, at `style`'s size."""
    return f'<font name="{_font(ctx, "Bold")}">{ctx.text(text, style)}</font>'


def _lines(section):
    """The non-empty lines of a section's body."""
    return [line.strip() for line in str((section or {}).get('body') or '').split('\n') if line.strip()]


def _items(section):
    return [item for item in (section or {}).get('items') or [] if isinstance(item, dict)
            and any(str(item.get(key) or '').strip() for key in ('label', 'text', 'value'))]


def _item_text(item):
    """A list item as one line: its label, then its text and value after a dash."""
    label, text, value = (str(item.get(key) or '').strip() for key in ('label', 'text', 'value'))
    rest = ' '.join(piece for piece in (text, value) if piece)
    return f'{label} — {rest}' if label and rest else label or rest


def _unmarked(text):
    return TYPED_MARKER.sub('', text, count=1)


def _shown(ctx, field_id):
    """A field as a paper prints it: the verified (or clock) value, an inline blank where one is drawn, else None."""
    value = ctx.fact(field_id)
    if value is not None:
        return value
    return ctx.blank_run(field_id) if ctx.blank(field_id) else None


def _field_word(ctx, field_id, labels=None):
    """The word a paper prints before a field: the placement's label for it, else its label without a note."""
    key = (labels or {}).get(field_id) if isinstance(labels, dict) else None
    if key and _has_label(ctx, key):
        return ctx.label(key)
    return TRAILING_NOTE.sub('', ctx.field_label(field_id))


def _part_text(ctx, place, part_id):
    """A part's written text in one line: the instance of the place when it repeats with it, else the first."""
    part = ctx.entry.part(part_id)
    if not part:
        return ''
    instance = place.instance if part.get('group') and part.get('group') == place.group else 1
    section = ctx.section(part['id'], instance)
    return ' '.join(_lines(section) + [_item_text(item) for item in _items(section)])


def _resolve(ctx, place, ref, *, drop_empty=False):
    """A text parameter: a template label (slots filled), else a field as printed, else a part's text; None: empty.

    With `drop_empty`, a label one of whose slots has no value is None: the
    clause is left out rather than drawn as a blank (only the counts given).
    """
    if not isinstance(ref, str) or not ref:
        return None
    labels = ctx.template.get('labels') or {}
    if ref in labels:
        if drop_empty:
            raw = labels[ref].get(ctx.locale) or labels[ref].get('en', '')
            if any(ctx.fact(slot) is None for slot in SLOT.findall(raw)):
                return None
        return ctx.label(ref) or None
    if ctx.entry.field(ref):
        return _shown(ctx, ref)
    if ctx.entry.part(ref):
        # A fixed part has no text of its own: its fixed heading is the line.
        return _part_text(ctx, place, ref) or ctx.heading(ctx.entry.part(ref)) or None
    return None


def _space_before(flowables, points):
    """Put `points` of space over the first flowable that prints (a frame drops it at the top of a page)."""
    for flowable in flowables:
        if getattr(flowable, '_ZEROSIZE', 0):
            continue
        content = getattr(flowable, '_content', None)
        if isinstance(content, list) and content:
            _space_before(content, points)
        elif isinstance(flowable, Paragraph):
            flowable.style = ParagraphStyle(f'{flowable.style.name}^', parent=flowable.style, spaceBefore=points)
        else:
            flowable.spaceBefore = points
        return


def _finish(place, flowables, *, before=0.0, after=0.0):
    """The block's flowables with its gaps: `before_pt` and `after_pt` over the block's defaults."""
    flowables = [flowable for flowable in flowables if flowable is not None]
    if not flowables:
        return []
    params = _params(place)
    before = _num(params.get('before_pt'), before, 0, 200)
    after = _num(params.get('after_pt'), after, 0, 200)
    if before:
        _space_before(flowables, before)
    if after:
        gap = Gap(1, after)
        if flowables[-1].getKeepWithNext():
            gap.keepWithNext = 1
        flowables.append(gap)
    return flowables


def _warn_over(ctx, name, count, limit):
    if limit and count > limit:
        ctx.warn(f'{name}_over')


def _balanced(markup, style, width):
    """The narrowest width at which `markup` keeps its number of lines, so no line ends with one word alone."""
    probe = Paragraph(markup, style)
    probe.wrap(width, 10_000)
    lines = len(getattr(probe.blPara, 'lines', ()) or ())
    if lines < 2:
        return width
    low, high = width * 0.45, width
    for _ in range(14):
        middle = (low + high) / 2
        trial = Paragraph(markup, style)
        trial.wrap(middle, 10_000)
        if len(getattr(trial.blPara, 'lines', ()) or ()) == lines:
            high = middle
        else:
            low = middle
    return min(width, high + 0.5)


def _cap_size(ctx):
    return max(7.0, round(ctx.size * 0.75 * 2) / 2)


def _caption_style(ctx):
    size = _cap_size(ctx)
    return _style(ctx, 'italic', fontSize=size, leading=size * 1.2, alignment=TA_CENTER)


def _roman(number):
    found = []
    for value, letters in ROMAN:
        while number >= value:
            found.append(letters)
            number -= value
    return ''.join(found)


def _date_blank(ctx, year):
    """The language's date to fill in by hand; the clock's year when `year` is clock."""
    return DATE_BLANK[ctx.locale].format(year=str(ctx.day.year) if year == 'clock' else YEAR_BLANK)


def _tracked(ctx, text, font, size, leading, tracking, align='centre'):
    """A line in tracked capitals when it fits the frame, else a wrapped Paragraph without the tracking."""
    line = Tracked(ctx.plain(text), font, size, leading, tracking, align)
    if line.measure() <= ctx.width:
        return line
    style = _style(ctx, 'body', fontName=font, fontSize=size, leading=leading, alignment=ALIGN.get(align, TA_CENTER))
    return Paragraph(ctx.text(text, style), style)


def _plain_line(ctx, text, base='body', **changes):
    style = _style(ctx, base, **changes)
    return Paragraph(ctx.text(text, style), style)


# ---------------------------------------------------------------- paragraph


@block('paragraph')
def paragraph(ctx, place):
    """Running prose: one paragraph per line of the body, then one per item of a list part (statements).

    params: style body | small | italic; align left | justify (the template's
    by default); indent_first_mm (the template's `indent_first_mm` by
    default); gap_pt between paragraphs; run_in_label: the text up to its
    first full stop or colon is set bold; label: a label key set bold before
    the first paragraph.
    """
    params = _params(place)
    section = place.section or {}
    texts = _lines(section) + [_unmarked(_item_text(item)) for item in _items(section)]
    if not texts:
        return []
    kind = ctx.template.get('type') or {}
    base = params.get('style') if params.get('style') in ('body', 'small', 'italic') else 'body'
    align = ALIGN.get(params.get('align') or kind.get('align'), TA_LEFT)
    indent = _num(params.get('indent_first_mm'), _num(kind.get('indent_first_mm'), 0.0), 0, 40) * MM
    gap = _num(params.get('gap_pt'), 0.0, 0, 60)
    label = _word(ctx, params.get('label')) if params.get('label') else ''
    made = []
    for number, text in enumerate(texts):
        style = _style(ctx, base, alignment=align, firstLineIndent=indent, spaceBefore=gap if number else 0)
        markup = ctx.text(text, style)
        if params.get('run_in_label'):
            found = re.match(r'(.+?[.:])(\s+|$)(.*)', text, re.S)
            if found and len(found.group(1)) <= 120:
                markup = _bold(ctx, found.group(1), style) + (' ' + ctx.text(found.group(3), style)
                                                               if found.group(3) else '')
        if number == 0 and label:
            markup = f'{_bold(ctx, label, style)} {markup}'
        made.append(Paragraph(markup, style))
    return _finish(place, made)


# ---------------------------------------------------------------- line


@block('line')
def line(ctx, place):
    """One short fixed line: a label formula with slots, a fact, a part's one line, or label sentences joined.

    params: text (a label key, a field id or a part id); sentences (label keys
    joined into one paragraph); label (a label key run in bold before it);
    drop_empty_slots (a sentence whose slot has no value is left out); align
    left | centre | right; style body | bold | italic | small | caps;
    balance (wrap at the narrowest width that keeps the line count);
    max_lines (the size steps down, to 85%, until the line fits that many).
    Without text or sentences: the part's own text, else the placement's facts.
    """
    params = _params(place)
    drop = bool(params.get('drop_empty_slots'))
    keys = params.get('sentences') if isinstance(params.get('sentences'), list) else (
        [params['text']] if params.get('text') else [])
    if keys:
        pieces = [_resolve(ctx, place, key, drop_empty=drop) for key in keys]
    elif place.part and place.section is not None:
        pieces = [_part_text(ctx, place, place.part['id'])]
    else:
        pieces = [_shown(ctx, field_id) for field_id in place.fields]
    text = ' '.join(piece.strip() for piece in pieces if piece and piece.strip())
    if not text:
        return []
    choice = params.get('style') if params.get('style') in ('body', 'bold', 'italic', 'small', 'caps') else 'body'
    if choice == 'caps':
        text = text.upper()
    align = ALIGN.get(params.get('align'), TA_LEFT)
    style = _style(ctx, choice, alignment=align)
    label = _word(ctx, params.get('label')) if params.get('label') else ''

    def made(chosen):
        markup = ctx.text(text, chosen)
        return f'{_bold(ctx, label, chosen)} {markup}' if label else markup
    limit = _int(params.get('max_lines'), 0, 0, 40)
    if limit:
        smallest = style.fontSize * 0.85
        while True:
            probe = Paragraph(made(style), style)
            probe.wrap(ctx.width, 10_000)
            if len(getattr(probe.blPara, 'lines', ()) or ()) <= limit or style.fontSize <= smallest:
                break
            style = _style(ctx, style, fontSize=style.fontSize - 0.5, leading=style.leading - 0.6)
        if len(getattr(probe.blPara, 'lines', ()) or ()) > limit:
            ctx.warn('line_over')
    if params.get('balance'):
        room = _balanced(made(style), style, ctx.width)
        if align == TA_CENTER:
            style = _style(ctx, style, leftIndent=(ctx.width - room) / 2, rightIndent=(ctx.width - room) / 2)
        elif align == TA_RIGHT:
            style = _style(ctx, style, leftIndent=ctx.width - room)
        else:
            style = _style(ctx, style, rightIndent=ctx.width - room)
    return _finish(place, [Paragraph(made(style), style)], before=ctx.leading * 0.25, after=ctx.leading * 0.25)


# ---------------------------------------------------------------- heading


def _instance_count(ctx, place):
    part = place.part
    if not part:
        return 1
    count = 0
    while ctx.section(part['id'], count + 1) is not None:
        count += 1
    return max(1, count)


def _numbered(ctx, numbering, level):
    if numbering not in ('arabic', 'decimal', 'roman', 'chapter_word'):
        return ''
    full = ctx.number(level)
    count = int(full.split('.')[-1])
    if numbering == 'decimal':
        return f'{full}.' if level == 1 else full
    if numbering == 'roman':
        return f'{_roman(count)}.'
    if numbering == 'chapter_word':
        return CHAPTER[ctx.locale].format(n=count) + '.'
    return f'{count}.'


@block('heading')
def heading(ctx, place):
    """A part's heading at level 1-3, numbered by the paper's counters from the headings it shows.

    params: level (the part's by default); numbering none | arabic ("2.") |
    decimal ("2.1") | roman ("II.") | chapter_word ("2-BOB.", "ГЛАВА 2.",
    "CHAPTER 2."); align left | centre; caps; rule none | under; label (a
    label key as its text, else the part's heading); right_label (a label key
    set flush right on its line: an appendix mark); in_toc (marked for the
    contents; levels 1 and 2 by default); style plain | badge (the number in a
    box); fold_number_below (fewer instances of the group than this: no
    number); page_break_before (a new page unless at the top of one).
    """
    params = _params(place)
    level = _int(params.get('level'), _int((place.part or {}).get('level'), 1), 1, 3)
    text = _word(ctx, params['label']) if params.get('label') else ctx.heading(place.part, place.section)
    text = ' '.join(str(text or '').split())
    if not text:
        return []
    numbering = params.get('numbering') or 'none'
    fold = _int(params.get('fold_number_below'), 0, 0, 100)
    if fold and _instance_count(ctx, place) < fold:
        numbering = 'none'
    number = _numbered(ctx, numbering, level)
    if params.get('caps'):
        text = text.upper()
    align = ALIGN.get(params.get('align'), TA_LEFT)
    style = _style(ctx, f'h{level}', alignment=align)
    made = []
    if params.get('page_break_before'):
        made.append(PageBreakIfNotEmpty())
    if params.get('in_toc', level <= 2):
        made.append(ctx.mark(level, f'{number} {text}'.strip()))
    if params.get('style') == 'badge' and number:
        badge = Paragraph(ctx.text(number.rstrip('.'), style), _style(ctx, style, alignment=TA_CENTER))
        size = style.leading + 4
        title = Paragraph(ctx.text(text, style), _style(ctx, style, alignment=TA_LEFT))
        drawn = Table([[badge, title]], colWidths=[size + 4, ctx.width - size - 4])
        drawn.setStyle(TableStyle([('BOX', (0, 0), (0, 0), 0.9, INK), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                                   ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                                   ('LEFTPADDING', (1, 0), (1, 0), 3 * MM), ('TOPPADDING', (0, 0), (-1, -1), 1.5),
                                   ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5)]))
        drawn.hAlign = 'LEFT'
    else:
        markup = ctx.text(f'{number} {text}' if number else text, style)
        drawn = Paragraph(markup, style)
        if params.get('right_label') and _has_label(ctx, params['right_label']):
            right = Paragraph(ctx.text(ctx.label(params['right_label']), 'italic'),
                              _style(ctx, 'italic', alignment=TA_RIGHT))
            drawn = Table([[drawn, right]], colWidths=[ctx.width * 0.7, ctx.width * 0.3])
            drawn.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
                                       ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                                       ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
            drawn.hAlign = 'LEFT'
    drawn.keepWithNext = 1
    made.append(drawn)
    if params.get('rule') == 'under':
        hair = Hair(thickness=0.5, above=1.3 * MM, below=0)
        hair.keepWithNext = 1
        made.append(hair)
    before = {1: ctx.leading * 1.1, 2: ctx.leading * 0.8, 3: ctx.leading * 0.5}[level]
    return _finish(place, made, before=before, after=ctx.leading * 0.3)


# ---------------------------------------------------------------- doc_title


def doc_title(ctx, place):
    """The document's own word in tracked capitals, centred, with up to three subject lines under it.

    params: label (a label key of the fixed word; "title" when the template
    has no such label is the paper's own title); subject (field ids, or a part
    id, printed as centred lines under it); tracking_pt (1.2 by default); caps
    (true for a label word, false for the paper's own title).
    """
    params = _params(place)
    key = params.get('label')
    own = False
    if _has_label(ctx, key):
        word = ctx.label(key)
    elif key == 'title' or not key:
        word, own = str(ctx.content.get('title') or '').strip(), True
    else:
        word = ''
    if not word:
        word, own = ctx.heading(place.part, place.section), False
    word = ' '.join(str(word or '').split())
    if not word:
        return []
    if params.get('caps', not own):
        word = word.upper()
    size = round(ctx.size * 1.17 * 2) / 2
    leading = size * 1.3
    made = [_tracked(ctx, word, _font(ctx, 'Bold'), size, leading, _num(params.get('tracking_pt'), 1.2, 0, 6))]
    subject = params.get('subject')
    lines = []
    if isinstance(subject, list):
        lines = [_shown(ctx, field_id) for field_id in subject[:3]]
    elif isinstance(subject, str):
        lines = [_part_text(ctx, place, subject)]
    for text in (text for text in lines if text):
        made.append(_plain_line(ctx, text, alignment=TA_CENTER, spaceBefore=2))
    return _finish(place, made, before=30.0, after=24.0)


def _doc_title_plain(ctx, place):
    params = _params(place)
    word = ctx.label(params['label']) if _has_label(ctx, params.get('label')) else (
        ctx.content.get('title') or ctx.heading(place.part, place.section))
    word = ' '.join(str(word or '').split())
    return [_plain_line(ctx, word.upper(), 'bold', alignment=TA_CENTER), Spacer(1, ctx.leading)] if word else []


block('doc_title', fallback=_doc_title_plain)(doc_title)


# ---------------------------------------------------------------- list


def _marker(kind, number, locale):
    if kind == 'dash':
        return '–'
    if kind == 'bullet':
        return '•'
    if kind == 'paren_number':
        return f'{number})'
    if kind == 'letter':
        letters = LETTERS.get(locale, LETTERS['en'])
        return f'{letters[(number - 1) % len(letters)]})'
    return f'{number}.'


def _list_texts(section):
    found = [_unmarked(_item_text(item)) for item in _items(section)]
    return found or [_unmarked(text) for text in _lines(section)]


@block('list')
def list_block(ctx, place):
    """A list from a part's items (else its body lines) with one marker and a hanging indent.

    params: marker dash | bullet | number | paren_number | letter (а) б) in
    Russian); gutter (the markers hang in the left margin, outside the frame);
    label (a label key set before the first item, the items hanging on its
    edge: "Ilova:"; a plural label is used for several items when the
    template has it as `label_many` or as the key with an s); max_items
    (warned, never cut); single_unnumbered (one item has no marker); columns
    1 | 2. A marker the model typed is dropped: the list draws its own.
    """
    params = _params(place)
    texts = _list_texts(place.section)
    if not texts:
        return []
    _warn_over(ctx, 'list', len(texts), _int(params.get('max_items'), 0, 0, 200))
    kind = params.get('marker') if params.get('marker') in ('dash', 'bullet', 'number', 'paren_number',
                                                             'letter') else 'bullet'
    marked = not (len(texts) == 1 and params.get('single_unnumbered'))
    style = _style(ctx, 'body', alignment=TA_LEFT)
    markers = [_marker(kind, number, ctx.locale) if marked else '' for number in range(1, len(texts) + 1)]
    widest = max((stringWidth(marker, style.fontName, style.fontSize) for marker in markers), default=0)
    # ReportLab sets the text at least 0.6 em past the end of the marker.
    hang = widest + style.fontSize * 0.65 if marked else 0.0
    label = ''
    if params.get('label'):
        many = params.get('label_many') or f"{params['label']}s"
        label = ctx.label(many) if len(texts) > 1 and _has_label(ctx, many) else _word(ctx, params['label'])
    if label or _int(params.get('columns'), 1, 1, 2) == 2:
        return _list_table(ctx, place, texts, markers, hang, label, style)
    made = []
    for number, (text, marker) in enumerate(zip(texts, markers)):
        offset = -hang if params.get('gutter') else 0.0
        chosen = _style(ctx, style, leftIndent=offset + hang, bulletIndent=offset, bulletFontName=style.fontName,
                        bulletFontSize=style.fontSize, spaceBefore=ctx.leading * 0.15 if number else 0)
        made.append(Paragraph(ctx.text(text, chosen), chosen, bulletText=marker or None))
    return _finish(place, made, before=ctx.leading * 0.35, after=ctx.leading * 0.35)


def _list_table(ctx, place, texts, markers, hang, label, style):
    """A labelled list (the label's column, then the items on its edge) or a list in two columns."""
    params = _params(place)
    two = _int(params.get('columns'), 1, 1, 2) == 2 and not label
    cells = []
    for text, marker in zip(texts, markers):
        chosen = _style(ctx, style, leftIndent=hang, bulletIndent=0, bulletFontName=style.fontName,
                        bulletFontSize=style.fontSize)
        cells.append(Paragraph(ctx.text(text, chosen), chosen, bulletText=marker or None))
    if two:
        half = (len(cells) + 1) // 2
        rows = [[cells[row], cells[row + half] if row + half < len(cells) else '']
                for row in range(half)]
        widths = [ctx.width / 2, ctx.width / 2]
    else:
        lead = stringWidth(ctx.plain(label), style.fontName, style.fontSize) + 3 * MM
        lead = min(lead, ctx.width * 0.35)
        rows = [[Paragraph(ctx.text(label, style), style) if number == 0 else '', cell]
                for number, cell in enumerate(cells)]
        widths = [lead, ctx.width - lead]
    table = Table(rows, colWidths=widths)
    table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0),
                               ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('TOPPADDING', (0, 0), (-1, -1), 0),
                               ('BOTTOMPADDING', (0, 0), (-1, -1), 2)]
                              + ([('RIGHTPADDING', (0, 0), (0, -1), 3 * MM)] if two else [])))
    table.hAlign = 'LEFT'
    return _finish(place, [table], before=ctx.leading * (1.0 if label else 0.35), after=ctx.leading * 0.35)


# ---------------------------------------------------------------- table


def _cells(item, count):
    """A table row as `count` cells: label first, value last, the text's ` | ` cells between, padded or merged."""
    label = str(item.get('label') or '').strip()
    text = str(item.get('text') or '').strip()
    value = str(item.get('value') or '').strip()
    if count <= 1:
        return [' — '.join(piece for piece in (label, text, value) if piece)]
    middle = CELL.split(text) if text else []
    if count == 2:
        return [label, ' — '.join(piece for piece in (*middle, value) if piece)]
    need = count - 2
    if len(middle) > need:
        middle = middle[:need - 1] + ['; '.join(cell for cell in middle[need - 1:] if cell)]
    middle += [''] * (need - len(middle))
    return [label, *middle, value]


def _natural(item):
    """How many cells a row holds as written: its label, its text's ` | ` cells, its value."""
    text = str(item.get('text') or '').strip()
    return 1 + (len(CELL.split(text)) if text else 0) + (1 if str(item.get('value') or '').strip() else 0)


def _question_rows(ctx):
    """The model answers of the open questions: number (after the closed ones), answer with its note, marks."""
    before = len(ctx.questions('choice')) + len(ctx.questions('passage'))
    rows = []
    for number, question in enumerate(ctx.questions('open'), start=before + 1):
        answer = ' '.join(str(question.get(key) or '').strip() for key in ('answer', 'explanation')
                          if str(question.get(key) or '').strip())
        marks = question.get('marks')
        rows.append({'cells': [str(number), answer, str(marks) if marks not in (None, '', 0) else ''],
                     'total': False})
    return rows


def _widths(ctx, specs, rows, headers, count):
    """Column widths in points: the template's mm and flex columns, else shared by how much each column holds."""
    width = ctx.width
    if specs:
        fixed = [(_num(spec.get('width_mm'), 0, 0, 400) * MM if spec.get('width_mm') != 'flex' else None)
                 if isinstance(spec, dict) else None for spec in specs]
        taken = sum(value for value in fixed if value)
        flex = [index for index, value in enumerate(fixed) if not value]
        # Fixed columns wider than the frame shrink in proportion; with flex columns they leave those a quarter.
        room = width * 0.75 if flex else width
        if taken and (taken > room or (not flex and taken < width)):
            fixed = [value * room / taken if value else None for value in fixed]
            taken = sum(value for value in fixed if value)
        share = (width - taken) / len(flex) if flex else 0
        return [value if value else share for value in fixed]
    weights = []
    for column in range(count):
        longest = max([len(headers[column]) if column < len(headers) else 0]
                      + [len(row['cells'][column]) for row in rows if column < len(row['cells'])] + [4])
        weights.append(min(60, max(6, longest)) ** 0.75)
    total = sum(weights)
    return [width * weight / total for weight in weights]


@block('table')
def table(ctx, place):
    """A grid from a table part: the header from the template (else the part's columns), never from the draft.

    params: columns [{label (a label key), width_mm (number or "flex"), align
    left | centre | right, type text | number | money}]; rules horizontal |
    grid; heading (the part's heading over it); caption (numbered: "1-jadval.
    <heading>"); note (a label key under it); zebra; blank_rows (rows to fill
    by hand); drop_empty_columns; from "questions:open" (the model answers:
    number, answer, marks). A row whose item carries `total` (derive.py's) is
    set bold under a rule. The header repeats on each page and rows never
    split; a section's body is printed under the table as a note, never lost.
    """
    params = _params(place)
    specs = [spec for spec in params.get('columns') or () if isinstance(spec, dict)]
    section = place.section or {}
    if params.get('from') == 'questions:open':
        rows = _question_rows(ctx)
        count = len(specs) or 3
    else:
        part_columns = ctx.columns(place.part)
        count = len(specs) or len(part_columns) or max([_natural(item) for item in _items(section)] + [1])
        rows = [{'cells': _cells(item, count), 'total': bool(item.get('total'))} for item in _items(section)]
    if specs:
        headers = [_word(ctx, spec.get('label')) if spec.get('label') else '' for spec in specs]
    else:
        headers = ctx.columns(place.part)[:count]
    headers = [re.sub(r'\s*:\s*$', '', header) for header in headers] + [''] * (count - len(headers))
    for row in rows:
        row['cells'] = (row['cells'] + [''] * count)[:count]
    blank_rows = _int(params.get('blank_rows'), 0, 0, 40)
    if not rows and not blank_rows:
        return []
    keep = list(range(count))
    if params.get('drop_empty_columns') and rows:
        keep = [column for column in keep if any(row['cells'][column] for row in rows)] or [0]
    widths = _widths(ctx, specs, rows, headers, count)
    total_width = sum(widths[column] for column in keep)
    widths = [widths[column] * ctx.width / total_width for column in keep]
    aligns = []
    for column in keep:
        spec = specs[column] if column < len(specs) else {}
        kind = spec.get('type') if spec.get('type') in ('number', 'money') else 'text'
        aligns.append(ALIGN.get(spec.get('align'), TA_RIGHT if kind != 'text' else TA_LEFT))
    cell, bold = ctx.styles['cell'], _style(ctx, 'cell', fontName=_font(ctx, 'Bold'))
    data = []
    has_header = any(headers[column] for column in keep)
    if has_header:
        data.append([Paragraph(ctx.text(headers[column], bold), _style(ctx, bold, alignment=align))
                     for column, align in zip(keep, aligns)])
    totals = []
    for row in rows:
        chosen = bold if row['total'] else cell
        if row['total']:
            totals.append(len(data))
        data.append([Paragraph(ctx.text(row['cells'][column], chosen), _style(ctx, chosen, alignment=align))
                     for column, align in zip(keep, aligns)])
    for _ in range(blank_rows):
        data.append([''] * len(keep))
    heights = [None] * (len(data) - blank_rows) + [cell.leading * 1.8] * blank_rows
    drawn = Table(data, colWidths=widths, rowHeights=heights, repeatRows=1 if has_header else 0, hAlign='LEFT')
    commands = [('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 1.7 * MM),
                ('RIGHTPADDING', (0, 0), (-1, -1), 1.7 * MM), ('TOPPADDING', (0, 0), (-1, -1), 1.3 * MM),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 1.3 * MM)]
    if params.get('rules') == 'grid':
        commands.append(('GRID', (0, 0), (-1, -1), 0.5, INK))
    else:
        commands += [('LINEABOVE', (0, 0), (-1, 0), 1.0, INK), ('LINEBELOW', (0, 0), (-1, -1), 0.5, INK),
                     ('LINEBELOW', (0, -1), (-1, -1), 1.0, INK)]
        if has_header:
            commands.append(('LINEBELOW', (0, 0), (-1, 0), 0.7, INK))
    if params.get('zebra'):
        start = 1 if has_header else 0
        commands.append(('ROWBACKGROUNDS', (0, start), (-1, -1), [colors.white, TINT]))
    for index in totals:
        commands.append(('LINEABOVE', (0, index), (-1, index), 0.7, INK))
    drawn.setStyle(TableStyle(commands))
    made = []
    title = ctx.heading(place.part, place.section)
    if params.get('caption'):
        counted = getattr(ctx, 'tables_drawn', 0) + 1
        ctx.tables_drawn = counted
        caption = TABLE_CAPTION[ctx.locale].format(n=counted) + (f'. {title}' if title else '')
        made.append(_plain_line(ctx, caption, 'italic', keepWithNext=1, spaceAfter=2))
    elif params.get('heading') and title:
        made.append(_plain_line(ctx, title, 'h3', spaceAfter=3))
    made.append(drawn)
    notes = []
    if params.get('note') and _has_label(ctx, params['note']):
        notes.append(ctx.label(params['note']))
    notes += _lines(section)
    for text in notes:
        made.append(_plain_line(ctx, text, 'small', spaceBefore=2))
    return _finish(place, made, before=ctx.leading * 0.5, after=ctx.leading * 0.5)


# ---------------------------------------------------------------- kv_table


@block('kv_table')
def kv_table(ctx, place):
    """Label and value rows, no header: from facts, or from a list part's items (label, text).

    params: rows (field ids, or a part id; the placement's fields by
    default); labels ({field id: label key}: the word before a value, else the
    field's label without its note); label_mm (45); rules none | under_rows |
    box; bold_labels (true). A missing value that draws a blank is a ruled
    cell to write in; one that does not is no row.
    """
    params = _params(place)
    source = params.get('rows')
    pairs = []
    if isinstance(source, str) or (source is None and place.section is not None):
        section = ctx.section(source, place.instance) if isinstance(source, str) else place.section
        for item in _items(section):
            label = str(item.get('label') or '').strip()
            value = ' '.join(str(item.get(key) or '').strip() for key in ('text', 'value')
                             if str(item.get(key) or '').strip())
            pairs.append((label, value, False))
    else:
        for field_id in source if isinstance(source, list) else place.fields:
            value = ctx.fact(field_id)
            if value is None and not ctx.blank(field_id):
                continue
            pairs.append((_field_word(ctx, field_id, params.get('labels')), value or '', value is None))
    if not pairs:
        return []
    label_width = min(_num(params.get('label_mm'), 45.0, 10, 120) * MM, ctx.width * 0.5)
    words = _style(ctx, 'bold' if params.get('bold_labels', True) else 'body')
    body = ctx.styles['body']
    data, blanks = [], []
    for row, (label, value, blank) in enumerate(pairs):
        data.append([Paragraph(ctx.text(label, words), words), Paragraph(ctx.text(value, body), body) if value
                     else ''])
        if blank:
            blanks.append(row)
    heights = [ctx.leading * 1.5 if row in blanks else None for row in range(len(data))]
    drawn = Table(data, colWidths=[label_width, ctx.width - label_width], rowHeights=heights, hAlign='LEFT')
    commands = [('VALIGN', (0, 0), (-1, -1), 'BOTTOM' if blanks else 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 2 * MM),
                ('TOPPADDING', (0, 0), (-1, -1), 1.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5)]
    rules = params.get('rules') or 'none'
    if rules == 'under_rows':
        commands.append(('LINEBELOW', (0, 0), (-1, -1), 0.3, INK))
    elif rules == 'box':
        commands += [('BOX', (0, 0), (-1, -1), 0.5, INK), ('INNERGRID', (0, 0), (-1, -1), 0.3, INK),
                     ('LEFTPADDING', (0, 0), (-1, -1), 1.7 * MM)]
    for row in blanks:
        if rules == 'none':
            commands.append(('LINEBELOW', (1, row), (1, row), 0.5, INK))
    drawn.setStyle(TableStyle(commands))
    return _finish(place, [drawn], before=ctx.leading * 0.35, after=ctx.leading * 0.35)


# ---------------------------------------------------------------- callout


@block('callout')
def callout(ctx, place):
    """A set-off passage: tinted, boxed, or with a rule down its left edge; one row per paragraph, so it splits.

    params: style tint | box | bar; label (a label key, else the part's
    heading, set bold on the first row); source (a part id whose text it
    holds; the placement's part by default).
    """
    params = _params(place)
    section = ctx.section(params['source'], place.instance) if isinstance(params.get('source'), str) \
        else place.section
    texts = _lines(section) + [_item_text(item) for item in _items(section)]
    if not texts:
        return []
    label = ''
    if params.get('label') and _has_label(ctx, params['label']):
        label = ctx.label(params['label'])
    heading = ctx.heading(place.part, section)
    rows = []
    if label or heading:
        rows.append([Paragraph(ctx.text(heading or label, 'bold'), ctx.styles['bold'])])
    rows += [[Paragraph(ctx.text(text, 'body'), ctx.styles['body'])] for text in texts]
    kind = params.get('style') if params.get('style') in ('tint', 'box', 'bar') else 'tint'
    drawn = Table(rows, colWidths=[ctx.width], hAlign='LEFT')
    pad = 3 * MM
    commands = [('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), pad),
                ('RIGHTPADDING', (0, 0), (-1, -1), pad), ('TOPPADDING', (0, 0), (-1, -1), 1.2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 1.2), ('TOPPADDING', (0, 0), (-1, 0), pad * 0.7),
                ('BOTTOMPADDING', (0, -1), (-1, -1), pad * 0.7)]
    if kind == 'tint':
        commands.append(('BACKGROUND', (0, 0), (-1, -1), TINT))
    elif kind == 'box':
        commands.append(('BOX', (0, 0), (-1, -1), 0.6, INK))
    else:
        commands.append(('LINEBEFORE', (0, 0), (0, -1), 1.6, INK))
    drawn.setStyle(TableStyle(commands))
    return _finish(place, [drawn], before=ctx.leading * 0.5, after=ctx.leading * 0.5)


# ---------------------------------------------------------------- inline_blank


@block('inline_blank')
def inline_blank(ctx, place):
    """Text with its blanks drawn as rules of three widths, never broken; or one blank on its own line.

    The widths are text_rules' (a day 9 mm, a number 28 mm, a name 55 mm,
    picked by the run's length), so a blank is the same everywhere in a paper.
    params: label (a label key with {field} slots or underscores; else the
    part's text, else the placement's fields as printed); width day | number |
    name | full (the blank drawn when there is no text).
    """
    params = _params(place)
    texts = []
    if params.get('label') and _has_label(ctx, params['label']):
        texts = [ctx.label(params['label'])]
    elif place.section is not None:
        texts = _lines(place.section) + [_item_text(item) for item in _items(place.section)]
    else:
        texts = [shown for shown in (_shown(ctx, field_id) for field_id in place.fields) if shown]
    if not texts:
        width = params.get('width') or 'name'
        if width == 'full':
            return _finish(place, [Hair(thickness=0.5, above=ctx.leading, below=2)], after=ctx.leading * 0.25)
        texts = [{'day': '___', 'number': '_' * 8}.get(width, '_' * 16)]
    made = [Paragraph(ctx.text(text, 'body'), ctx.styles['body']) for text in texts]
    return _finish(place, made, before=ctx.leading * 0.25, after=ctx.leading * 0.25)


# ---------------------------------------------------------------- ruled_blank


def ruled_blank(ctx, place):
    """Room to write by hand: N ruled lines after a label, one rule with a caption under it, or a box.

    params: label and caption (label keys); lines (2); style rules | captioned
    | box | dashed_box; width_mm (a number, or full); pitch_pt (the distance
    between the rules; 24 at 12 pt, scaled with the size); indent_mm (the
    template's first-line indent by default). When the placement's first field
    has a value, the label and the value are printed instead: nothing is left
    to fill in.
    """
    params = _params(place)
    label = _word(ctx, params.get('label')) if params.get('label') else ''
    caption = _word(ctx, params.get('caption')) if params.get('caption') else ''
    for field_id in place.fields[:1]:
        value = ctx.fact(field_id)
        if value is not None:
            style = ctx.styles['body']
            markup = ctx.text(value, style)
            return _finish(place, [Paragraph(f'{ctx.text(label, style)} {markup}' if label else markup, style)],
                           before=ctx.leading * 0.25, after=ctx.leading * 0.25)
    kind = params.get('style') if params.get('style') in ('rules', 'captioned', 'box', 'dashed_box') else 'rules'
    lines = 1 if kind == 'captioned' else _int(params.get('lines'), 2, 1, 40)
    rule = params.get('width_mm')
    rule = None if rule in (None, 'full') else _num(rule, 0.0, 10, 400) * MM or None
    indent = _num(params.get('indent_mm'), _num((ctx.template.get('type') or {}).get('indent_first_mm'), 0.0),
                  0, 40) * MM
    pitch = _num(params.get('pitch_pt'), max(16.0, ctx.size * 2), 10, 60)
    drawn = Ruled(label=ctx.plain(label), lines=lines, caption=ctx.plain(caption), rule=rule, style=kind,
                  pitch=pitch, indent=indent if kind in ('rules', 'captioned') else 0.0, font=ctx.face,
                  size=ctx.size, small=_cap_size(ctx))
    return _finish(place, [drawn], before=ctx.leading * 0.15, after=ctx.leading * 0.4)


def _ruled_plain(ctx, place):
    params = _params(place)
    label = _word(ctx, params.get('label')) if params.get('label') else ''
    lines = 1 if params.get('style') == 'captioned' else _int(params.get('lines'), 2, 1, 10)
    return [Paragraph(ctx.text(f'{label} {"_" * 16}'.strip(), 'body'), ctx.styles['body'])] + [
        Paragraph(ctx.text('_' * 16, 'body'), ctx.styles['body']) for _ in range(lines - 1)]


block('ruled_blank', fallback=_ruled_plain)(ruled_blank)


# ---------------------------------------------------------------- signature_row


def _typed(ctx, text, width, align=TA_CENTER):
    """A value typed on a signature rule: the body size, stepped down to 85% to keep one line, else wrapped."""
    style = _style(ctx, 'body', alignment=align)
    plain = ctx.plain(text)
    size = style.fontSize
    while size > style.fontSize * 0.85 and stringWidth(plain, style.fontName, size) > width - 2 * MM:
        size -= 0.5
    style = _style(ctx, style, fontSize=size, leading=size * 1.2)
    return Paragraph(ctx.text(text, style), style)


def _sign_cell(ctx, typed, caption, width, room, align=TA_CENTER):
    """One cell to sign in: clear room, the value typed on the rule (if any), the rule, its caption."""
    cell = []
    paragraph_ = _typed(ctx, typed, width, align) if typed else None
    height = paragraph_.wrap(width, 10_000)[1] if paragraph_ else 0.0
    cell.append(Spacer(1, max(2.0, room - height - 1.5)))
    if paragraph_:
        cell.append(paragraph_)
    cell.append(Hair(width, 0.5, above=1.5, below=1.0))
    if caption:
        cell.append(Paragraph(ctx.text(caption, _caption_style(ctx)), _caption_style(ctx)))
    return cell


def _sign_table(ctx, cells, widths, gaps):
    """One row of cells on one baseline: a Table that never splits, its cells bottom-aligned."""
    row, columns = [], []
    for index, (cell, width) in enumerate(zip(cells, widths)):
        if index:
            row.append('')
            columns.append(gaps)
        row.append(cell)
        columns.append(width)
    drawn = Table([row], colWidths=columns, hAlign='LEFT')
    drawn.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'BOTTOM'), ('LEFTPADDING', (0, 0), (-1, -1), 0),
                               ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('TOPPADDING', (0, 0), (-1, -1), 0),
                               ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
    return drawn


def _signers(ctx, place):
    """(post, name) of each signer: a list part's items (label, text), else the fields taken in pairs."""
    params = _params(place)
    source = params.get('signers')
    if isinstance(source, str) or (source is None and place.section is not None):
        section = ctx.section(source, place.instance) if isinstance(source, str) else place.section
        return [(str(item.get('label') or '').strip(), str(item.get('text') or item.get('value') or '').strip())
                for item in _items(section)]
    fields = [field_id for field_id in (source if isinstance(source, list) else place.fields)
              if isinstance(field_id, str)]
    found = []
    # A list field holds one signer a line (or between semicolons), and a lone line field one signer, each as "post —
    # name" or "post A. B. Name" (the agreeing posts of a job description, the author of an instruction): split,
    # never retyped.
    whole = [field_id for field_id in fields if (ctx.entry.field(field_id) or {}).get('kind') == 'list'
             or (len(fields) == 1 and (ctx.entry.field(field_id) or {}).get('kind') == 'line')]
    for field_id in whole:
        # Split as facts.supported reads a list fact: a line or a semicolon ends one signer.
        for line in re.split(r'[\n;]+', ctx.fact(field_id) or ''):
            post, name, sure = _post_and_name(line)
            if post or name:
                # A split that is only a guess keeps the whole line in the name cell, as it was drawn before.
                found.append((post, name) if sure or not name else ('', ' '.join(line.split()).strip(' ,')))
    fields = [field_id for field_id in fields if field_id not in whole]
    for index in range(0, len(fields), 2):
        pair = fields[index:index + 2]
        post = (ctx.fact(pair[0]) or '') if len(pair) == 2 else ''
        name = ctx.fact(pair[-1]) or ''
        # A signer with nothing known but a blank to sign on still gets the row: the post and name are written by
        # hand, never guessed.
        if post or name or ctx.blank(pair[-1]):
            found.append((post, name))
    return found


# One initial: a capital with its full stop, an Uzbek digraph or o‘/g‘ counted as one letter ("Sh.", "Ch.", "O‘.",
# "Yu.").
SIGNER_INITIAL = r'(?:[A-ZА-ЯЁЎҚҒҲ](?:[hgHG]|[‘’])?|Y[oua])\.'
# A person's name with its initials, at the end of a signer's line: "A. B. Karimov", "Karimov A. B.".
SIGNER_NAME = re.compile(rf'(?:(?:{SIGNER_INITIAL}\s*){{1,3}}[^\W\d_][\w‘’ʼ\'-]+'
                         rf'|[^\W\d_][\w‘’ʼ\'-]+\s+{SIGNER_INITIAL}(?:\s*{SIGNER_INITIAL}){{0,2}})\s*$')
# A full name without initials, two to four capitalised words ("Rustamova Zarina Akmalovna"): a name only beside a
# side that is not one, since an English post is capitalised as well.
SIGNER_FULL_NAME = re.compile(r'[A-ZА-ЯЁЎҚҒҲ][^\W\d_A-ZА-ЯЁЎҚҒҲ][\w‘’ʼ\'-]*'
                              r'(?:\s+[A-ZА-ЯЁЎҚҒҲ][^\W\d_A-ZА-ЯЁЎҚҒҲ][\w‘’ʼ\'-]*){1,3}')
SIGNER_DASH = re.compile(r'\s+[—–-]\s+|\s*:\s+')


def _is_name(text):
    return bool(SIGNER_NAME.fullmatch(text) or SIGNER_FULL_NAME.fullmatch(text))


def _post_and_name(line):
    """(post, name, sure) of one signer's line: split at a dash or colon (the side that is a name is the name), else
    before a name with initials at its end; a line without one is a post to sign by hand. `sure` is False when the
    name side was guessed, so a caller can keep the line whole instead of printing a post as the name."""
    line = re.sub(r'\.{2,}$', '.', ' '.join(line.split()).strip(' ;,'))
    # A closing full stop goes, never the one of a final initial ("Rahimov B. S.", "Yo‘ldosheva G. O‘.").
    if not re.search(rf'(?:^|[\s.]){SIGNER_INITIAL}$', line):
        line = re.sub(r'[\s.;,]+$', '', line)
    pieces = SIGNER_DASH.split(line, maxsplit=1)
    if len(pieces) == 2:
        left, right = (piece.strip() for piece in pieces)
        if _is_name(left) and not _is_name(right):
            return right, left, True
        return left, right, _is_name(right) and not _is_name(left)
    found = SIGNER_NAME.search(line)
    if found and found.start() > 0:
        return line[:found.start()].strip(' ,'), found.group(0).strip(), True
    return ('', line, True) if found else (line, '', False)


def signature_row(ctx, place):
    """Cells to sign on one baseline, each a rule with a caption under it.

    params: variant date_sign_name (the date and the printed name are the
    placement's first and second fields, typed on their rules when given) |
    post_sign_name and label_sign_name (one row per signer: the post, or a
    label key `label`, then the signature and the name) | grid (two signers a
    row: a rule with the name under it); signers (a part id whose items are
    post and name, or field ids in pairs; the fields by default); captions
    (three label keys; date, sign, name or post, sign, name by default);
    sign_room_mm (14: the clear space above the rule for a hand); max_rows
    (warned, never cut).
    """
    params = _params(place)
    variant = params.get('variant') if params.get('variant') in ('date_sign_name', 'post_sign_name',
                                                                 'label_sign_name', 'grid') else 'date_sign_name'
    room = _num(params.get('sign_room_mm'), 14.0, 4, 40) * MM
    width = ctx.width
    gap = width * 0.045
    captions = params.get('captions') if isinstance(params.get('captions'), list) else None
    made = []
    if variant == 'date_sign_name':
        keys = captions or ['date', 'sign', 'name']
        fields = list(place.fields) + [None, None]
        date = ctx.fact(fields[0]) if fields[0] else None
        name = ctx.fact(fields[1]) if fields[1] else None
        widths = [width * 0.273, width * 0.303, width - width * 0.576 - 2 * gap]
        cells = [_sign_cell(ctx, value, _word(ctx, key), cell_width, room)
                 for value, key, cell_width in zip((date, None, name), keys + ['', '', ''], widths)]
        made.append(_sign_table(ctx, cells, widths, gap))
    elif variant == 'grid':
        signers = _signers(ctx, place)
        _warn_over(ctx, 'signature_row', len(signers), _int(params.get('max_rows'), 0, 0, 100))
        half = (width - gap) / 2
        for index in range(0, len(signers), 2):
            cells = [_sign_cell(ctx, None, ', '.join(piece for piece in (name, post) if piece) or
                                _word(ctx, 'name'), half, room * 0.75)
                     for post, name in signers[index:index + 2]]
            made.append(_sign_table(ctx, cells, [half] * len(cells), gap))
    else:
        keys = captions or [params.get('label') if variant == 'label_sign_name' else 'post', 'sign', 'name']
        if variant == 'post_sign_name':
            signers = _signers(ctx, place)
        else:
            signed = (ctx.fact(place.fields[-1]) if place.fields else None) or ''
            # A line field ("R. A. Aliyev — direktor") signs by its name, the label already saying the role; a line
            # whose name side is only a guess is typed whole, so a post never stands in the name cell.
            if signed and (ctx.entry.field(place.fields[-1]) or {}).get('kind') == 'line':
                post, name, sure = _post_and_name(signed)
                signed = name if sure and name else signed
            signers = [('', signed)]
        _warn_over(ctx, 'signature_row', len(signers), _int(params.get('max_rows'), 0, 0, 100))
        widths = [width * 0.38, width * 0.25, width - width * 0.63 - 2 * gap]
        for post, name in signers:
            if variant == 'label_sign_name':
                # The label stands on the rules' line, as a typed value does: set like one, with the room the
                # rule and a caption take under it.
                first = _typed(ctx, _word(ctx, params.get('label')), widths[0], TA_LEFT)
                below = Spacer(1, 3.0 + _caption_style(ctx).leading)
                cells = [[first, below], _sign_cell(ctx, None, _word(ctx, keys[1]), widths[1], room),
                         _sign_cell(ctx, name, _word(ctx, keys[2]), widths[2], room)]
            else:
                cells = [_sign_cell(ctx, post, _word(ctx, keys[0]), widths[0], room, TA_LEFT),
                         _sign_cell(ctx, None, _word(ctx, keys[1]), widths[1], room),
                         _sign_cell(ctx, name, _word(ctx, keys[2]), widths[2], room)]
            made.append(_sign_table(ctx, cells, widths, gap))
    if not made:
        return []
    return _finish(place, made, before=ctx.leading, after=ctx.leading * 0.25)


def _signature_plain(ctx, place):
    """One line with underscores: date, signature, name."""
    values = [ctx.fact(field_id) for field_id in place.fields[:2]] + [None, None]
    words = [_word(ctx, key) for key in ('date', 'sign', 'name')]
    text = '   '.join(f'{word}: {value or "_" * 8}' for word, value in zip(words, (values[0], None, values[1])))
    return [Spacer(1, ctx.leading), Paragraph(ctx.text(text, 'body'), ctx.styles['body'])]


block('signature_row', fallback=_signature_plain)(signature_row)


# ---------------------------------------------------------------- date_line


def date_line(ctx, place):
    """A date as the customer gave it; else the field's clock value; else the language's blank date.

    params: fact (a field id; the placement's first field by default); align
    left | right; pattern (a label key of the blank date, «___» ________
    20__-yil by default); year clock | blank (the blank date's year from the
    clock, or a blank); label (a label key run in before it).
    """
    params = _params(place)
    field_id = params.get('fact') if isinstance(params.get('fact'), str) else (place.fields[0] if place.fields
                                                                                 else None)
    value = ctx.fact(field_id) if field_id else None
    if value is None:
        if _has_label(ctx, params.get('pattern')):
            value = ctx.label(params['pattern'])
            if params.get('year') == 'clock':
                value = value.replace(YEAR_BLANK, str(ctx.day.year))
        else:
            value = _date_blank(ctx, params.get('year'))
    label = _word(ctx, params.get('label')) if params.get('label') else ''
    style = _style(ctx, 'body', alignment=ALIGN.get(params.get('align'), TA_LEFT))
    markup = ctx.text(value, style)
    if label:
        markup = f'{ctx.text(label, style)} {markup}'
    return _finish(place, [Paragraph(markup, style)], before=ctx.leading * 0.5, after=ctx.leading * 0.25)


def _date_plain(ctx, place):
    field_id = place.fields[0] if place.fields else None
    value = (ctx.fact(field_id) if field_id else None) or _date_blank(ctx, 'blank')
    return [Paragraph(ctx.text(value, 'body'), ctx.styles['body'])]


block('date_line', fallback=_date_plain)(date_line)


# ---------------------------------------------------------------- doc_head


def _formatted(ctx, field_id, formats):
    """A field as a head prints it: through its format label ("{class_level}-sinf") when the placement has one."""
    value = ctx.fact(field_id)
    if value is None:
        return None
    key = (formats or {}).get(field_id) if isinstance(formats, dict) else None
    return ctx.label(key) if key and _has_label(ctx, key) else value


def _ids(value):
    if isinstance(value, str):
        return [value]
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


@block('doc_head')
def doc_head(ctx, place):
    """The compact top of page 1 of a paper without a title page, between two rules.

    In order: the overline (a label key or a field id: the school, in small
    tracked capitals); the kind line (`kind_line` a field id, else
    `kind_default` a label key: TEST, NAZORAT ISHI); the term (`term`, a field
    id, italic); the organisation (`org`); the title (`title`: field ids
    joined with commas, or "title" for the paper's own title, which it also
    is when none of them has a value); the subtitle (`subtitle`: field ids,
    italic); the meta lines (`meta`: field ids as "Label: value", `labels`
    giving the word). params also: formats ({field id: label key} printing a
    value through a label's slot, "{class_level}-sinf"); rules none | above |
    below | both; align left | centre.
    """
    params = _params(place)
    formats = params.get('formats')
    align_name = params.get('align') if params.get('align') in ('left', 'centre') else 'centre'
    align = ALIGN[align_name]
    rules = params.get('rules') or 'none'
    made = []
    if rules in ('above', 'both'):
        made.append(Hair(thickness=1.4, above=0, below=5 * MM * 0.8))
    small = round(ctx.size * 0.82 * 2) / 2
    overline = params.get('overline')
    over = ctx.label(overline) if _has_label(ctx, overline) else (
        _formatted(ctx, overline, formats) if isinstance(overline, str) else None)
    if over:
        made.append(_tracked(ctx, over.upper(), _font(ctx, 'Bold'), small, small * 1.35, 0.9, align_name))
    kind = _formatted(ctx, params['kind_line'], formats) if isinstance(params.get('kind_line'), str) else None
    if not kind and _has_label(ctx, params.get('kind_default')):
        kind = ctx.label(params['kind_default'])
    if kind:
        size = round(ctx.size * 0.92 * 2) / 2
        line_ = _tracked(ctx, kind.upper(), _font(ctx, 'Bold'), size, size * 1.4, 1.6, align_name)
        if over:
            _space_before([line_], 2 * MM)
        made.append(line_)
    term = _formatted(ctx, params['term'], formats) if isinstance(params.get('term'), str) else None
    if term:
        made.append(_plain_line(ctx, term, 'italic', alignment=align, fontSize=small, leading=small * 1.3))
    org = _formatted(ctx, params['org'], formats) if isinstance(params.get('org'), str) else None
    if org:
        made.append(_plain_line(ctx, org, 'body', alignment=align, spaceBefore=2))
    title_ids = _ids(params.get('title'))
    pieces = [_formatted(ctx, field_id, formats) for field_id in title_ids if field_id != 'title']
    title = ', '.join(piece for piece in pieces if piece)
    if not title:
        title = str(ctx.content.get('title') or '').strip()
    if title:
        size = round(ctx.size * 1.55 * 2) / 2
        inset = 12 * MM if align == TA_CENTER else 0
        made.append(_plain_line(ctx, title, 'bold', alignment=align, fontSize=size, leading=size * 1.24,
                                leftIndent=inset, rightIndent=inset, spaceBefore=2.2 * MM))
    subtitle = ', '.join(piece for piece in (_formatted(ctx, field_id, formats)
                                             for field_id in _ids(params.get('subtitle'))) if piece)
    if subtitle:
        size = round(ctx.size * 1.14 * 2) / 2
        inset = 12 * MM if align == TA_CENTER else 0
        made.append(_plain_line(ctx, subtitle, 'italic', alignment=align, fontSize=size, leading=size * 1.32,
                                leftIndent=inset, rightIndent=inset, spaceBefore=2))
    for field_id in _ids(params.get('meta')):
        value = _shown(ctx, field_id)
        if value:
            made.append(_plain_line(ctx, f'{_field_word(ctx, field_id, params.get("labels"))}: {value}', 'small',
                                    alignment=align, spaceBefore=1))
    if not made or all(isinstance(flowable, Hair) for flowable in made):
        return []
    if rules in ('below', 'both'):
        made.append(Hair(thickness=0.5, above=3.4 * MM, below=0))
    return _finish(place, made, after=4 * MM)


# ---------------------------------------------------------------- party_block


def party_block(ctx, place):
    """A column of lines naming a party from facts: the addressee, the applicant, the issuing organisation.

    Values are printed as the model wrote them (the addressee already in the
    dative), flush left in the column, each wrapped at the narrowest width
    that keeps its line count; a line of several values is one per line of
    the value. A field that draws a blank is a ruled row with its caption.
    params: anchor left | right_half; groups ([[field ids]]; the placement's
    fields as one group by default); captions, labels, suffixes ({field id:
    label key}: the caption under a blank, the word before a value or a blank
    ("Tel.:"), the case ending after a blank ("ga")); name_style body |
    bold_large (the first line of each group); max_lines (per group, warned);
    gap_pt (between groups, and over the block: the gap from the column above).
    """
    params = _params(place)
    groups = [_ids(group) for group in params['groups']] if isinstance(params.get('groups'), list) else [
        list(place.fields)]
    captions, labels, suffixes = (params.get(key) if isinstance(params.get(key), dict) else {}
                                  for key in ('captions', 'labels', 'suffixes'))
    right = params.get('anchor') == 'right_half'
    offset = ctx.width / 2 if right else 0.0
    column = ctx.width - offset
    size = ctx.size
    style = _style(ctx, 'body', alignment=TA_LEFT, leading=round(size * 1.25, 1), leftIndent=offset)
    large = _style(ctx, style, fontName=_font(ctx, 'Bold'), fontSize=size * 1.15, leading=size * 1.4)
    gap = _num(params.get('gap_pt'), 12.0, 0, 60)
    limit = _int(params.get('max_lines'), 0, 0, 40)
    made = []
    for group in groups:
        rows = []
        for field_id in group:
            word = _word(ctx, labels.get(field_id)) if labels.get(field_id) else ''
            value = ctx.fact(field_id)
            if value is None:
                if ctx.blank(field_id):
                    caption = _word(ctx, captions.get(field_id)) if captions.get(field_id) else ''
                    suffix = _word(ctx, suffixes.get(field_id)) if suffixes.get(field_id) else ''
                    rows.append(BlankRow(offset, column, ctx.plain(word), ctx.plain(suffix), ctx.plain(caption),
                                         ctx.face, size, _cap_size(ctx),
                                         size * 1.67 if caption else size * 1.5))
                continue
            for number, text in enumerate(piece.strip() for piece in value.split('\n') if piece.strip()):
                chosen = large if params.get('name_style') == 'bold_large' and not rows else style
                full = f'{word} {text}' if word and number == 0 else text
                markup = ctx.text(full, chosen)
                room = _balanced(markup, _style(ctx, chosen, leftIndent=0), column)
                rows.append(Paragraph(markup, _style(ctx, chosen, rightIndent=column - room)))
        if not rows:
            continue
        if limit:
            lines = 0
            for row in rows:
                if isinstance(row, Paragraph):
                    row.wrap(ctx.width, 10_000)
                    lines += len(getattr(row.blPara, 'lines', ()) or ())
                else:
                    lines += 1
            _warn_over(ctx, 'party_block', lines, limit)
        if made:
            _space_before(rows, gap)
        made += rows
    return _finish(place, made, before=_num(params.get('gap_pt'), 0.0, 0, 60) if params.get('gap_pt') else 0.0)


def _party_plain(ctx, place):
    """The lines, flush left: values, and a blank for each field that draws one."""
    made = []
    for field_id in place.fields:
        shown = _shown(ctx, field_id)
        if shown:
            made.append(Paragraph(ctx.text(shown, 'body'), ctx.styles['body']))
    return made + [Spacer(1, ctx.leading * 0.5)] if made else []


block('party_block', fallback=_party_plain)(party_block)


# ---------------------------------------------------------------- approval_block


def _approval_cell(ctx, spec, width):
    """One approval group: order lines, the word in capitals, its rows, a signature rule with the name, a date."""
    cell = []
    small = _style(ctx, 'small', alignment=TA_LEFT)
    for field_id in _ids(spec.get('order_lines')):
        value = ctx.fact(field_id)
        if value:
            cell.append(Paragraph(ctx.text(value, small), small))
    word = _word(ctx, spec.get('word')) if spec.get('word') else ''
    if word:
        cell.append(Tracked(ctx.plain(word.upper()), _font(ctx, 'Bold'), ctx.size, ctx.leading, 1.0, 'left')
                    if stringWidth(word.upper(), _font(ctx, 'Bold'), ctx.size) + len(word) < width
                    else Paragraph(ctx.text(word.upper(), 'bold'), ctx.styles['bold']))
    body = _style(ctx, 'body', alignment=TA_LEFT, leading=round(ctx.size * 1.3, 1))
    for field_id in _ids(spec.get('rows')):
        shown = _shown(ctx, field_id)
        if shown:
            cell.append(Paragraph(ctx.text(shown, body), body))
    name = spec.get('name')
    signed = ctx.fact(name) if isinstance(name, str) else None
    line = '_' * 12 + (f' {signed}' if signed else '')
    cell.append(Paragraph(ctx.text(line, body), _style(ctx, body, spaceBefore=ctx.leading * 0.6)))
    date = spec.get('date', True)
    if date:
        value = ctx.fact(date) if isinstance(date, str) else None
        cell.append(Paragraph(ctx.text(value or _date_blank(ctx, spec.get('year')), body),
                              _style(ctx, body, spaceBefore=3)))
    return cell


def approval_block(ctx, place):
    """The approval or agreement stamp: a fixed word in capitals, the post, a signature with the name, a date.

    params: word (a label key: TASDIQLAYMAN, KELISHILDI); rows (field ids:
    the post, the organisation; the placement's fields by default); name (a
    field id typed after the signature rule); date (a field id, true for a
    blank date, false for none); year clock | blank; order_lines (field ids
    printed small over the word: the annex-to-order variant); side right |
    left | pair; groups (for pair: two {word, rows, name, date} side by side).
    """
    params = _params(place)
    side = params.get('side') if params.get('side') in ('right', 'left', 'pair') else 'right'
    if side == 'pair':
        specs = [spec for spec in params.get('groups') or () if isinstance(spec, dict)][:2]
        if not specs:
            return []
        half = (ctx.width - 8 * MM) / 2
        cells = [_approval_cell(ctx, spec, half) for spec in specs]
        if len(cells) == 1:
            cells.append('')
        widths = [half, 8 * MM, half]
        row = [cells[0], '', cells[1]]
    else:
        spec = dict(params)
        spec.setdefault('rows', list(place.fields))
        width = ctx.width * 0.48
        cell = _approval_cell(ctx, spec, width)
        widths = [ctx.width - width, width]
        row = ['', cell] if side == 'right' else [cell, '']
        if side == 'left':
            widths.reverse()
    drawn = Table([row], colWidths=widths, hAlign='LEFT')
    drawn.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0),
                               ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('TOPPADDING', (0, 0), (-1, -1), 0),
                               ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
    return _finish(place, [drawn], after=ctx.leading)


def _approval_plain(ctx, place):
    """The word and "Label: ____" lines."""
    params = _params(place)
    made = []
    word = _word(ctx, params.get('word')) if params.get('word') else ''
    if word:
        made.append(Paragraph(ctx.text(word.upper(), 'bold'), ctx.styles['bold']))
    for field_id in _ids(params.get('rows')) or list(place.fields):
        shown = ctx.fact(field_id) or '_' * 8
        made.append(Paragraph(ctx.text(f'{_field_word(ctx, field_id)}: {shown}', 'body'), ctx.styles['body']))
    return made + [Spacer(1, ctx.leading * 0.5)] if made else []


block('approval_block', fallback=_approval_plain)(approval_block)


# ---------------------------------------------------------------- samples


def _text3(uz, ru, en):
    return {'uz': uz, 'ru': ru, 'en': en}


SAMPLE_FIELDS = (
    {'id': 'org', 'kind': 'org', 'missing': 'blank', 'label': _text3('Tashkilot', 'Организация', 'Organisation')},
    {'id': 'head', 'kind': 'line', 'missing': 'blank', 'label': _text3('Rahbar', 'Руководитель', 'Head')},
    {'id': 'person', 'kind': 'person', 'missing': 'blank',
     'label': _text3('F.I.Sh. (ixtiyoriy)', 'Ф.И.О. (по желанию)', 'Full name (optional)')},
    {'id': 'phone', 'kind': 'phone', 'missing': 'if_needed', 'label': _text3('Telefon', 'Телефон', 'Phone')},
    {'id': 'org_blank', 'kind': 'org', 'missing': 'blank', 'label': _text3('Tashkilot', 'Организация',
                                                                            'Organisation')},
    {'id': 'name_blank', 'kind': 'person', 'missing': 'blank', 'label': _text3('F.I.Sh.', 'Ф.И.О.', 'Full name')},
    {'id': 'phone_blank', 'kind': 'phone', 'missing': 'if_needed', 'label': _text3('Telefon', 'Телефон', 'Phone')},
    {'id': 'date_given', 'kind': 'date', 'missing': 'blank', 'label': _text3('Sana', 'Дата', 'Date')},
    {'id': 'date_blank', 'kind': 'date', 'missing': 'blank', 'label': _text3('Sana', 'Дата', 'Date')},
    {'id': 'date_clock', 'kind': 'date', 'missing': 'omit', 'clock': 'date', 'label': _text3('Sana', 'Дата', 'Date')},
    {'id': 'signer', 'kind': 'person', 'missing': 'blank', 'label': _text3('Imzo yonidagi ism', 'Расшифровка',
                                                                           'Printed name')},
    {'id': 'post', 'kind': 'line', 'missing': 'blank', 'label': _text3('Lavozim', 'Должность', 'Position')},
    {'id': 'post_two', 'kind': 'line', 'missing': 'blank', 'label': _text3('Lavozim', 'Должность', 'Position')},
    {'id': 'signer_two', 'kind': 'person', 'missing': 'blank', 'label': _text3('Ism', 'Имя', 'Name')},
    {'id': 'school', 'kind': 'org', 'missing': 'omit', 'label': _text3('Maktab', 'Школа', 'School')},
    {'id': 'subject', 'kind': 'text', 'missing': 'omit', 'label': _text3('Fan', 'Предмет', 'Subject')},
    {'id': 'class_level', 'kind': 'number', 'missing': 'omit', 'label': _text3('Sinf', 'Класс', 'Class')},
    {'id': 'topic', 'kind': 'text', 'missing': 'omit', 'label': _text3('Mavzu', 'Тема', 'Topic')},
    {'id': 'time_min', 'kind': 'number', 'missing': 'omit', 'label': _text3('Vaqt', 'Время', 'Time')},
    {'id': 'time_none', 'kind': 'number', 'missing': 'omit', 'label': _text3('Vaqt', 'Время', 'Time')},
    {'id': 'reason', 'kind': 'text', 'missing': 'blank', 'label': _text3('Sabab', 'Причина', 'Reason')},
)

SAMPLE_FACTS = {
    'org': _text3('Namuna davlat universiteti', 'Образцовый государственный университет', 'Example State University'),
    'head': _text3('rektori B. A. Sobirovga', 'ректору Б. А. Собирову', 'Rector B. A. Sobirov'),
    'person': _text3('Toshmatova Nilufar Akmal qizidan', 'от Тошматовой Нилуфар Акмаловны', 'Nilufar Toshmatova'),
    'phone': _text3('+998 90 123 45 67', '+998 90 123 45 67', '+998 90 123 45 67'),
    'phone_blank': _text3('____', '____', '____'),
    'date_given': _text3('14.11.2026', '14.11.2026', '14 November 2026'),
    'signer': _text3('N. A. Toshmatova', 'Н. А. Тошматова', 'N. Toshmatova'),
    'post': _text3('Kafedra mudiri', 'Заведующий кафедрой', 'Head of department'),
    'post_two': _text3('Bosh hisobchi', 'Главный бухгалтер', 'Chief accountant'),
    'signer_two': _text3('D. K. Yusupova', 'Д. К. Юсупова', 'D. Yusupova'),
    'school': _text3('Namuna tumanidagi 99-sonli maktab', 'Школа № 99 Образцового района',
                     'School No. 99, Namuna district'),
    'subject': _text3('Biologiya', 'Биология', 'Biology'),
    'class_level': _text3('7', '7', '7'),
    'topic': _text3('Hujayra tuzilishi va organoidlar', 'Строение клетки и органоиды', 'Cell structure and organelles'),
    'time_min': _text3('35', '35', '35'),
}

SAMPLE_PARTS = (
    {'id': 'request', 'kind': 'prose', 'heading': None, 'heading_mode': 'none', 'need': 'required', 'write': '-'},
    {'id': 'statements', 'kind': 'list', 'heading': None, 'heading_mode': 'none', 'need': 'optional', 'write': '-'},
    {'id': 'chapter', 'kind': 'prose', 'heading': None, 'heading_mode': 'model', 'need': 'required', 'write': '-',
     'level': 1},
    {'id': 'enclosures', 'kind': 'list', 'heading': _text3('Ilova:', 'Приложение:', 'Enclosure:'),
     'heading_mode': 'fixed', 'need': 'optional', 'write': '-'},
    {'id': 'tasks', 'kind': 'list', 'heading': _text3('Vazifalar', 'Задачи', 'Tasks'), 'heading_mode': 'fixed',
     'need': 'usual', 'write': '-', 'level': 2},
    {'id': 'prices', 'kind': 'table', 'heading': _text3('Narxlar', 'Цены', 'Prices'), 'heading_mode': 'fixed',
     'need': 'required', 'write': '-',
     'columns': [_text3('Xizmat', 'Услуга', 'Service'), _text3('Miqdori', 'Количество', 'Quantity'),
                 _text3('Narxi, so‘m', 'Цена, сум', 'Price, UZS')]},
    {'id': 'roster', 'kind': 'list', 'heading': None, 'heading_mode': 'none', 'need': 'optional', 'write': '-'},
    {'id': 'passage', 'kind': 'prose', 'heading': None, 'heading_mode': 'model', 'need': 'optional', 'write': '-'},
    {'id': 'members', 'kind': 'list', 'heading': None, 'heading_mode': 'none', 'need': 'optional', 'write': '-'},
)

SAMPLE_SECTIONS = {
    'uz': {
        'request': 'Men 2026-yil 3-noyabrdan 12-noyabrgacha bo‘lgan davrda kasallik sababli darslarga qatnasha '
                   'olmadim. Shu kunlardagi dars qoldirishlarimni uzrli deb hisoblashingizni so‘rayman.\n'
                   'Kurs ishi topshiriqlari: ___ ta.',
        'statements': ['Nizom bilan tanishdim va roziman.', 'Taqdim etilgan ma’lumotlar to‘g‘ri.'],
        'chapter': ('Hujayra nazariyasining asoslari', 'Hujayra — tirik organizmning eng kichik tuzilish birligi.'),
        'enclosures': ['Shifokor ma’lumotnomasi.', 'Pasport nusxasi, 2 dona.'],
        'tasks': ['1. Mavzu bo‘yicha manbalarni o‘rganish.', 'Reja tuzish.', 'Xulosa yozish.'],
        'prices': [('Veb-sayt yaratish', '1 dona', '12 000 000'), ('Texnik qo‘llab-quvvatlash', '12 oy', '6 000 000')],
        'roster': [('Rais', 'B. A. Karimov'), ('Kotib', 'D. R. Aliyeva')],
        'passage': ('Fotosintez', 'Fotosintez — o‘simlik hujayralarining xloroplastlarida yorug‘lik ta’sirida '
                                  'kechadigan jarayon. Bunda o‘simlik havodan karbonat angidridni yutadi.'),
        'members': [('Rais', 'B. A. Karimov'), ('A’zo', 'D. R. Aliyeva'), ('A’zo', 'G‘. O‘. Rahimov')],
    },
    'ru': {
        'request': 'Прошу считать уважительными мои пропуски занятий с 3 по 12 ноября 2026 года в связи с '
                   'болезнью.\nЗаданий курсовой работы: ___ шт.',
        'statements': ['С положением ознакомлена и согласна.', 'Представленные сведения верны.'],
        'chapter': ('Основы клеточной теории', 'Клетка — наименьшая структурная единица живого организма.'),
        'enclosures': ['Справка от врача.', 'Копия паспорта, 2 шт.'],
        'tasks': ['1. Изучить источники по теме.', 'Составить план.', 'Написать вывод.'],
        'prices': [('Создание веб-сайта', '1 шт.', '12 000 000'), ('Техническая поддержка', '12 мес.', '6 000 000')],
        'roster': [('Председатель', 'Б. А. Каримов'), ('Секретарь', 'Д. Р. Алиева')],
        'passage': ('Фотосинтез', 'Фотосинтез — процесс, который идёт в хлоропластах растительных клеток под '
                                  'действием света. Растение поглощает углекислый газ из воздуха.'),
        'members': [('Председатель', 'Б. А. Каримов'), ('Член', 'Д. Р. Алиева'), ('Член', 'Г. О. Рахимов')],
    },
    'en': {
        'request': 'I was unable to attend classes from 3 to 12 November 2026 because of illness. I ask that '
                   'these absences be counted as excused.\nCourse work tasks: ___.',
        'statements': ['I have read the regulation and agree to it.', 'The information given is true.'],
        'chapter': ('Foundations of cell theory', 'The cell is the smallest structural unit of a living organism.'),
        'enclosures': ['Doctor’s certificate.', 'Copy of passport, 2 copies.'],
        'tasks': ['1. Study the sources on the topic.', 'Draw up a plan.', 'Write the conclusion.'],
        'prices': [('Website development', '1 piece', '12 000 000'), ('Technical support', '12 months', '6 000 000')],
        'roster': [('Chair', 'B. A. Karimov'), ('Secretary', 'D. R. Aliyeva')],
        'passage': ('Photosynthesis', 'Photosynthesis is the process that runs in the chloroplasts of plant '
                                      'cells under light. The plant takes carbon dioxide from the air.'),
        'members': [('Chair', 'B. A. Karimov'), ('Member', 'D. R. Aliyeva'), ('Member', 'G. O. Rahimov')],
    },
}

SAMPLE_QUESTIONS = {
    'uz': [{'stem': 'Hujayraning irsiy axborotini nima saqlaydi?', 'options': ['Yadro', 'Ribosoma'],
            'answer': 'Yadro', 'explanation': '', 'marks': 1, 'topic': ''},
           {'stem': 'Fotosintez qayerda kechadi?', 'options': [], 'answer': 'Xloroplastlarda.',
            'explanation': 'Yorug‘lik ta’sirida — 2 ball.', 'marks': 2, 'topic': ''}],
    'ru': [{'stem': 'Что хранит наследственную информацию клетки?', 'options': ['Ядро', 'Рибосома'],
            'answer': 'Ядро', 'explanation': '', 'marks': 1, 'topic': ''},
           {'stem': 'Где идёт фотосинтез?', 'options': [], 'answer': 'В хлоропластах.',
            'explanation': 'Под действием света — 2 балла.', 'marks': 2, 'topic': ''}],
    'en': [{'stem': 'What stores the hereditary information of a cell?', 'options': ['Nucleus', 'Ribosome'],
            'answer': 'Nucleus', 'explanation': '', 'marks': 1, 'topic': ''},
           {'stem': 'Where does photosynthesis take place?', 'options': [], 'answer': 'In the chloroplasts.',
            'explanation': 'Under light — 2 points.', 'marks': 2, 'topic': ''}],
}

SAMPLE_LABELS = {
    'title': _text3('ARIZA', 'ЗАЯВЛЕНИЕ', 'APPLICATION'),
    'reason': _text3('Sababi:', 'Причина:', 'Reason:'),
    'enclosure': _text3('Ilova:', 'Приложение:', 'Enclosure:'),
    'enclosures': _text3('Ilova:', 'Приложение:', 'Enclosures:'),
    'date': _text3('Sana', 'Дата', 'Date'),
    'sign': _text3('Imzo', 'Подпись', 'Signature'),
    'name': _text3('F.I.Sh.', 'Расшифровка', 'Printed name'),
    'post': _text3('Lavozimi', 'Должность', 'Position'),
    'done_by': _text3('Bajardi:', 'Выполнил(а):', 'Prepared by:'),
    'tel': _text3('Tel.:', 'Тел.:', 'Tel.:'),
    'ga': _text3('ga', '', ''),
    'cap_org': _text3('(tashkilot nomi)', '(наименование организации)', '(name of the organisation)'),
    'cap_name': _text3('(F.I.Sh.)', '(Ф.И.О.)', '(full name)'),
    'instruction': _text3('Ko‘rsatma:', 'Инструкция:', 'Instructions:'),
    'one_answer': _text3('Har bir savolda bitta to‘g‘ri javob bor.', 'В каждом вопросе один правильный ответ.',
                         'Each question has one correct answer.'),
    'time': _text3('Vaqt: {time_min} daqiqa.', 'Время: {time_min} мин.', 'Time: {time_min} minutes.'),
    'time_none': _text3('Vaqt: {time_none} daqiqa.', 'Время: {time_none} мин.', 'Time: {time_none} minutes.'),
    'greeting': _text3('Hurmatli hamkasblar!', 'Уважаемые коллеги!', 'Dear colleagues,'),
    'part_one': _text3('I qism. To‘g‘ri javobni tanlang', 'Часть I. Выберите правильный ответ',
                       'Part I. Choose the correct answer'),
    'annex': _text3('1-ilova', 'Приложение 1', 'Annex 1'),
    'kind_test': _text3('TEST', 'ТЕСТ', 'TEST'),
    'class_n': _text3('{class_level}-sinf', '{class_level} класс', 'grade {class_level}'),
    'no': _text3('№', '№', 'No.'),
    'model_answer': _text3('Namunaviy javob', 'Образец ответа', 'Model answer'),
    'score': _text3('Ball:', 'Балл:', 'Score:'),
    'service': _text3('Xizmat', 'Услуга', 'Service'),
    'quantity': _text3('Miqdori', 'Кол-во', 'Qty'),
    'price': _text3('Narxi, so‘m', 'Цена, сум', 'Price, UZS'),
    'vat_note': _text3('Narxlar QQS bilan.', 'Цены указаны с НДС.', 'Prices include VAT.'),
    'passage': _text3('Matn', 'Текст', 'Text'),
    'pattern': _text3('«___» ____________ 20__-yil', '«___» ____________ 20__ г.', '____ ____________ 20__'),
    'approve': _text3('TASDIQLAYMAN', 'УТВЕРЖДАЮ', 'APPROVED'),
    'agree': _text3('KELISHILDI', 'СОГЛАСОВАНО', 'AGREED'),
    'blank_line': _text3('Men, __________________, ___ kun ta’til so‘rayman.',
                         'Я, __________________, прошу отпуск на ___ дней.',
                         'I, __________________, ask for ___ days of leave.'),
    'drawing': _text3('Rasm uchun joy', 'Место для рисунка', 'Room for a drawing'),
}

SAMPLES = (
    {'block': 'paragraph', 'case': 'indented, template indent', 'part': 'request', 'params': {}},
    {'block': 'paragraph', 'case': 'justified, gap, label', 'part': 'request',
     'params': {'align': 'justify', 'gap_pt': 6, 'label': 'reason', 'indent_first_mm': 0}},
    {'block': 'paragraph', 'case': 'list part as paragraphs, run-in label, small', 'part': 'statements',
     'params': {'run_in_label': True, 'style': 'small'}},
    {'block': 'paragraph', 'case': 'italic', 'part': 'request', 'params': {'style': 'italic'}},
    {'block': 'line', 'case': 'label with sentences, empty slot dropped', 'fields': ['time_min'],
     'params': {'label': 'instruction', 'sentences': ['one_answer', 'time', 'time_none'], 'drop_empty_slots': True,
                'style': 'small'}},
    {'block': 'line', 'case': 'greeting, centred, bold', 'params': {'text': 'greeting', 'align': 'centre',
                                                                     'style': 'bold'}},
    {'block': 'line', 'case': 'a fact, right, caps', 'params': {'text': 'org', 'align': 'right', 'style': 'caps'}},
    {'block': 'line', 'case': 'a part, balanced, max lines', 'part': 'request',
     'params': {'balance': True, 'max_lines': 3, 'style': 'italic'}},
    {'block': 'heading', 'case': 'level 1, chapter word, centre, caps', 'part': 'chapter',
     'params': {'level': 1, 'numbering': 'chapter_word', 'align': 'centre', 'caps': True}},
    {'block': 'heading', 'case': 'level 2, decimal, rule under', 'part': 'tasks',
     'params': {'level': 2, 'numbering': 'decimal', 'rule': 'under'}},
    {'block': 'heading', 'case': 'level 3, arabic', 'part': 'tasks', 'params': {'level': 3, 'numbering': 'arabic'}},
    {'block': 'heading', 'case': 'roman, label text, right label', 'part': 'tasks',
     'params': {'level': 2, 'numbering': 'roman', 'label': 'part_one', 'right_label': 'annex', 'in_toc': False}},
    {'block': 'heading', 'case': 'badge', 'part': 'tasks', 'params': {'level': 3, 'numbering': 'arabic',
                                                                       'style': 'badge'}},
    {'block': 'heading', 'case': 'folded number', 'part': 'tasks',
     'params': {'level': 3, 'numbering': 'arabic', 'fold_number_below': 2}},
    {'block': 'doc_title', 'case': 'label word, subject facts', 'params': {'label': 'title', 'tracking_pt': 1.2,
                                                                         'subject': ['org']}},
    {'block': 'doc_title', 'case': 'part heading, subject part', 'part': 'tasks',
     'params': {'label': 'no_such_word', 'subject': 'chapter'}},
    {'block': 'list', 'case': 'labelled, numbered, plural', 'part': 'enclosures',
     'params': {'marker': 'number', 'label': 'enclosure', 'max_items': 6, 'single_unnumbered': True}},
    {'block': 'list', 'case': 'dash', 'part': 'tasks', 'params': {'marker': 'dash'}},
    {'block': 'list', 'case': 'bullet', 'part': 'tasks', 'params': {'marker': 'bullet'}},
    {'block': 'list', 'case': 'paren number, gutter', 'part': 'tasks', 'params': {'marker': 'paren_number',
                                                                                  'gutter': True}},
    {'block': 'list', 'case': 'letter, two columns', 'part': 'tasks', 'params': {'marker': 'letter', 'columns': 2}},
    {'block': 'table', 'case': 'part columns, horizontal rules, caption, note', 'part': 'prices',
     'params': {'caption': True, 'note': 'vat_note'}},
    {'block': 'table', 'case': 'template columns, grid, zebra, blank rows', 'part': 'prices',
     'params': {'columns': [{'label': 'service', 'width_mm': 'flex'},
                            {'label': 'quantity', 'width_mm': 22, 'align': 'centre'},
                            {'label': 'price', 'width_mm': 35, 'type': 'money'}],
                'rules': 'grid', 'zebra': True, 'blank_rows': 2, 'heading': True}},
    {'block': 'table', 'case': 'model answers of the open questions', 'part': 'prices',
     'params': {'from': 'questions:open', 'rules': 'horizontal',
                'columns': [{'label': 'no', 'width_mm': 11, 'align': 'centre'},
                            {'label': 'model_answer', 'width_mm': 'flex'},
                            {'label': 'score', 'width_mm': 17, 'align': 'centre'}]}},
    {'block': 'table', 'case': 'empty columns dropped', 'part': 'roster', 'params': {'drop_empty_columns': True,
                                                                                    'rules': 'grid'}},
    {'block': 'kv_table', 'case': 'facts, blank rows, under rows', 'fields': ['org', 'head', 'name_blank'],
     'params': {'rules': 'under_rows', 'label_mm': 40}},
    {'block': 'kv_table', 'case': 'a part, box, plain labels', 'part': 'roster',
     'params': {'rows': 'roster', 'rules': 'box', 'bold_labels': False}},
    {'block': 'callout', 'case': 'bar, model heading', 'part': 'passage', 'params': {'style': 'bar'}},
    {'block': 'callout', 'case': 'tint, label', 'part': 'statements', 'params': {'style': 'tint',
                                                                                'label': 'passage'}},
    {'block': 'callout', 'case': 'box, source part', 'params': {'style': 'box', 'source': 'passage'}},
    {'block': 'inline_blank', 'case': 'label with blanks', 'params': {'label': 'blank_line'}},
    {'block': 'inline_blank', 'case': 'part text with a blank', 'part': 'request', 'params': {}},
    {'block': 'inline_blank', 'case': 'a full-width blank', 'params': {'width': 'full'}},
    {'block': 'ruled_blank', 'case': 'label and two rules', 'fields': ['reason'],
     'params': {'label': 'reason', 'lines': 2}},
    {'block': 'ruled_blank', 'case': 'captioned', 'params': {'label': 'tel', 'caption': 'cap_name',
                                                             'style': 'captioned', 'width_mm': 90}},
    {'block': 'ruled_blank', 'case': 'box', 'params': {'label': 'drawing', 'lines': 3, 'style': 'box'}},
    {'block': 'ruled_blank', 'case': 'dashed box, pitch', 'params': {'lines': 2, 'style': 'dashed_box',
                                                                     'pitch_pt': 20}},
    {'block': 'ruled_blank', 'case': 'a value given', 'fields': ['org'], 'params': {'label': 'reason'}},
    {'block': 'signature_row', 'case': 'date, signature, name typed', 'fields': ['date_given', 'signer'],
     'params': {'variant': 'date_sign_name', 'sign_room_mm': 14}},
    {'block': 'signature_row', 'case': 'date and name blank', 'fields': ['date_blank', 'name_blank'],
     'params': {'variant': 'date_sign_name'}},
    {'block': 'signature_row', 'case': 'post, signature, name for two', 'fields': ['post', 'signer', 'post_two',
                                                                                    'signer_two'],
     'params': {'variant': 'post_sign_name'}},
    {'block': 'signature_row', 'case': 'label, signature, name', 'fields': ['signer'],
     'params': {'variant': 'label_sign_name', 'label': 'done_by'}},
    {'block': 'signature_row', 'case': 'grid of members', 'part': 'members',
     'params': {'variant': 'grid', 'signers': 'members', 'max_rows': 8}},
    {'block': 'date_line', 'case': 'a given date, right', 'params': {'fact': 'date_given', 'align': 'right'}},
    {'block': 'date_line', 'case': 'the clock', 'params': {'fact': 'date_clock', 'label': 'date'}},
    {'block': 'date_line', 'case': 'blank pattern, year from the clock', 'params': {'fact': 'date_blank',
                                                                                   'year': 'clock'}},
    {'block': 'date_line', 'case': 'template pattern', 'params': {'fact': 'date_blank', 'pattern': 'pattern'}},
    {'block': 'doc_head', 'case': 'a test head, both rules, centred',
     'fields': ['school', 'subject', 'class_level', 'topic'],
     'params': {'overline': 'school', 'kind_default': 'kind_test', 'title': ['subject', 'class_level'],
                'subtitle': ['topic'], 'formats': {'class_level': 'class_n'}, 'rules': 'both', 'align': 'centre'}},
    {'block': 'doc_head', 'case': 'left, organisation, meta, rule below',
     'params': {'org': 'org', 'title': 'title', 'meta': ['date_given', 'person'], 'rules': 'below',
                'align': 'left'}},
    {'block': 'party_block', 'case': 'right half, facts', 'fields': ['org', 'head'],
     'params': {'anchor': 'right_half', 'max_lines': 4}},
    {'block': 'party_block', 'case': 'blanks with captions, Tel., case ending',
     'fields': ['org_blank', 'name_blank', 'phone_blank'],
     'params': {'anchor': 'right_half', 'gap_pt': 12, 'captions': {'org_blank': 'cap_org', 'name_blank': 'cap_name'},
                'labels': {'phone_blank': 'tel'}, 'suffixes': {'name_blank': 'ga'}}},
    {'block': 'party_block', 'case': 'left, two groups, bold large name',
     'params': {'groups': [['org'], ['person', 'phone']], 'name_style': 'bold_large', 'labels': {'phone': 'tel'}}},
    {'block': 'approval_block', 'case': 'right, word, rows, name, blank date',
     'fields': ['post', 'org'], 'params': {'word': 'approve', 'name': 'signer', 'side': 'right'}},
    {'block': 'approval_block', 'case': 'left, date from the clock year', 'fields': ['post'],
     'params': {'word': 'agree', 'side': 'left', 'year': 'clock', 'order_lines': ['head']}},
    {'block': 'approval_block', 'case': 'a pair', 'params': {
        'side': 'pair', 'groups': [{'word': 'agree', 'rows': ['post_two'], 'name': 'signer_two', 'date': False},
                                   {'word': 'approve', 'rows': ['post'], 'name': 'signer'}]}},
)


def _sample_sections(locale):
    texts = SAMPLE_SECTIONS[locale]
    sections = [{'id': 'facts', 'heading': '', 'body': '', 'layout': 'list',
                 'items': [{'label': key, 'text': value[locale]} for key, value in SAMPLE_FACTS.items()]},
                {'id': 'request', 'heading': '', 'body': texts['request'], 'layout': 'text', 'items': []}]
    for part_id in ('statements', 'enclosures', 'tasks'):
        sections.append({'id': part_id, 'heading': '', 'body': '', 'layout': 'list',
                         'items': [{'label': '', 'text': text} for text in texts[part_id]]})
    heading, body = texts['chapter']
    sections.append({'id': 'chapter', 'heading': heading, 'body': body, 'layout': 'text', 'items': []})
    heading, body = texts['passage']
    sections.append({'id': 'passage', 'heading': heading, 'body': body, 'layout': 'text', 'items': []})
    sections.append({'id': 'prices', 'heading': '', 'body': '', 'layout': 'table',
                     'items': [{'label': label, 'text': text, 'value': value}
                               for label, text, value in texts['prices']]})
    for part_id in ('roster', 'members'):
        sections.append({'id': part_id, 'heading': '', 'body': '', 'layout': 'list',
                         'items': [{'label': label, 'text': text} for label, text in texts[part_id]]})
    return sections


def sample_paper(locale='uz', samples=None):
    """(entry, template, content) of a paper that draws `samples` (all of SAMPLES by default), one placement each.

    Draw it with `paper.render_paper(content, path, locale, entry=entry,
    template=template, pages=1)`: the template's page rule is `flow`, so it
    runs to as many pages as the samples need, numbered at the foot.
    """
    from ...categories.catalogue import Entry
    chosen = SAMPLES if samples is None else tuple(samples)
    raw = {'id': 'pdf.sample', 'labels': _text3('📄 Namuna', '📄 Образец', '📄 Sample'),
           'fields': [dict(field, example=field['label'], need='optional') for field in SAMPLE_FIELDS],
           'parts': list(SAMPLE_PARTS), 'templates': ['core_blocks'], 'length': {'default': 1}}
    entry = Entry('pdf.sample', 'pdf', 'ai.pdf_topic', 'draft', raw=raw)
    flow = []
    for sample in chosen:
        placement = {'block': sample['block'], 'params': dict(sample.get('params') or {})}
        if sample.get('part'):
            placement['part'] = sample['part']
        if sample.get('fields'):
            placement['fields'] = list(sample['fields'])
        flow.append(placement)
    template = {'schema': 2, 'id': 'core_blocks', 'entries': ['pdf.sample'],
                'name': _text3('Asosiy bloklar', 'Основные блоки', 'Core blocks'), 'family': 'official',
                'page': {'margins_mm': {'left': 25, 'right': 18, 'top': 20, 'bottom': 20}},
                'type': {'face': 'serif', 'ladder': [[12, 18], [11.5, 17], [11, 16]], 'align': 'left',
                         'indent_first_mm': 12.5},
                'page_rule': {'kind': 'flow'}, 'furniture': {'first': 'number', 'later': 'number_bottom',
                                                             'format': 'n_of_N'},
                'flow': flow, 'labels': SAMPLE_LABELS}
    content = {'title': _text3('Namuna hujjat', 'Образец документа', 'Sample document')[locale],
               'sections': _sample_sections(locale), 'questions': [dict(question) for question in
                                                                   SAMPLE_QUESTIONS[locale]]}
    return entry, template, content
