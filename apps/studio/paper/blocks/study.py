"""The study family's blocks (architecture 6.6, blocks.json, package R3b): the test sheet and the notes' formulas.

cell_strip, question_list, answer_key and formula_line. The test, the
konspekt, the lesson plan and its handout draw everything else with the core
blocks (core.py) and, for a title page or a plan, the academic ones.

What they share with the core blocks: every string goes through `ctx.text`,
a fixed word is a template label, nothing the customer or the model gave is
cut, a block draws nothing when it has nothing to draw, and its gaps are
`before_pt` and `after_pt` over its defaults. Their measures are the test
mock's (units/pdf.test/template.md 4.4): a 9 mm number gutter, options four in
a row up to 31.5 mm, two by two up to 70 mm, else one a line, written answer
boxes of dotted rows two to a mark, key cells of a 6.2 mm number row over an
8.2 mm letter row, ten to a row at most and balanced.

Two conventions of their own:

- A number a label prints is written `#` in it: "(# ball)", "Maksimal ball: #",
  "#-savollarga matn asosida javob bering.". A `{slot}` names a field, and a
  count of questions or marks is none, so the catalogue would refuse it.
- A `when` inside a block's parameters (an intro, a cell, the score tab) is
  the template's closed predicate, or a list of them that must all hold: a
  placement's own `when` holds one predicate, and an instruction that depends
  on the use, the answer sheet and the question mix needs several.

The key letter of a closed question is found from its answer the way the
content model says (architecture 5): the option whose text equals the answer
once both are normalised, else the one at least 0.8 alike, else the answer's
own text is printed in the cell, never a letter guessed.
"""
import difflib
import re
from xml.sax.saxutils import escape

from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Flowable, KeepTogether, Paragraph, Spacer, Table, TableStyle

from ..ctx import INK, holds
from ..registry import block
from ..text import MM
from .core import Hair, _finish, _has_label, _int, _num, _params, _resolve, _style, _tracked, _word

# The number gutter of a question: the number right-aligned at 7 mm, the stem from 9 mm.
GUTTER_MM, NUMBER_MM = 9.0, 7.0
# Options set in n columns when the widest fits a column less this much air (31.5 of 39.5 mm, 70 of 79 mm).
OPTION_AIR_MM = 8.0
# Statements (DTM) set in two columns, read downwards, from this many when each fits half the column.
STATEMENTS_TWO = 6
# Written answers: dotted rows this far apart, two a mark between these bounds.
ROW_MM, ROWS_PER_MARK, ROWS_MIN, ROWS_MAX = 7.4, 2, 2, 10
# The score tab under a written answer box.
TAB_MM = (36.0, 7.0)
# Key cells: rows of at most ten, a cell no wider than this.
PER_ROW, CELL_MAX_MM = 10, 30.0
NUMBER_ROW_MM, LETTER_ROW_MM = 6.2, 8.2
# How alike an answer and an option's text must be for the option's letter to stand for it.
ALIKE = 0.8
OPTION_LETTERS = 'ABCDEFGH'
CYRILLIC_LETTERS = 'АБВГДЕЖЗ'
# Cyrillic capitals drawn like a Latin option letter: a model typing "А) В) С)" may mean A, B, C.
LOOKALIKE = {'А': 'A', 'В': 'B', 'С': 'C', 'Е': 'E', 'Н': 'H'}
# A letter the model typed before an option ("B) Ribosoma", "в: Рибосома"), which the list draws itself. Never
# with a full stop: "А. Н. Толстой" and "A. Qodiriy" begin with an initial, not a letter of the list. A colon
# needs a space after it, so the ratios "A:B", "B:C" stay whole.
TYPED_LETTER = re.compile(r'^\s*([A-Za-zА-Яа-яЁё])\s*(?:\)\s*|:\s+)(?=\S)')
# An answer that is only a letter ("B", "B)").
LETTER_ONLY = re.compile(r'^\s*([A-Ha-h])\s*[).]?\s*$')
# The signs that tell two answers apart once other punctuation goes: −5 and 5, x > 2 and x < 2, a + b and a − b.
SIGNS = '-+<>≤≥≠/=×÷·*^%'
DASHES = str.maketrans({mark: '-' for mark in '−–—‒'})
WIDE_SIGNS = (('>=', '≥'), ('<=', '≤'), ('!=', '≠'))
# What is left of a text for the alike test to be trusted: its digits and signs must agree (1, 3, 4, 5 is not
# 1, 3, 4, 6), and it must hold a letter (a bare number or list is matched exactly or not at all).
SKELETON = re.compile(r'[\d' + re.escape(SIGNS) + r']')
# A formula's subscript and power markers: _{12}, ^{3}, and the short F_1 or x^2.
SCRIPT = re.compile(r'([_^])(?:\{([^{}]{1,16})\}|(\d{1,3}))')
NUMBER_MARK = '#'
APOSTROPHES = str.maketrans({mark: "'" for mark in '‘’ʻʼ`´'})


# ---------------------------------------------------------------- helpers


def _holds(ctx, place, when):
    """One predicate; `questions:both` counts the passage's questions as closed, as the paper numbers them.

    The engine's predicate counts choice questions alone, which leaves a test
    of passage and written questions without its Part I and II and with the
    written-only instruction over its closed questions.
    """
    if when == 'questions:both':
        return bool(closed_questions(ctx)) and bool(ctx.questions('open'))
    return holds(when, ctx, place)


def _all_hold(ctx, place, when):
    """Whether `when` holds: none, one predicate, or a list of predicates that must all hold."""
    if not when:
        return True
    if isinstance(when, str):
        return _holds(ctx, place, when)
    if isinstance(when, list):
        return all(isinstance(item, str) and _holds(ctx, place, item) for item in when)
    return False


def _counted(ctx, key, number, one=None):
    """A label whose `#` is a number; `one` names the label used when the number is 1 (en "1 point")."""
    if number == 1 and _has_label(ctx, one):
        key = one
    if not _has_label(ctx, key):
        return ''
    return ctx.label(key).replace(NUMBER_MARK, str(number))


def _normal(text):
    """A text with its punctuation gone: only for comparing a legend's start with its run-in word."""
    return ' '.join(re.sub(r'[^\w\s]', ' ', str(text or '').translate(APOSTROPHES).casefold()).split())


def _exact(text):
    """An answer or an option as compared first: case, spacing, apostrophes and a closing full stop aside."""
    return ' '.join(str(text or '').translate(APOSTROPHES).casefold().split()).rstrip('.').rstrip()


def _loose(text):
    """The looser form: other punctuation and the spaces around a sign go, the signs themselves stay."""
    text = _exact(text).translate(DASHES)
    for wide, sign in WIDE_SIGNS:
        text = text.replace(wide, sign)
    text = re.sub(r'[^\w\s' + re.escape(SIGNS) + r']', ' ', text)
    text = re.sub(r'\s*([' + re.escape(SIGNS) + r'])\s*', r'\1', text)
    return ' '.join(text.split())


def _typed(text):
    """(the option positions a typed letter can stand for, the rest), or None when the text starts with none."""
    found = TYPED_LETTER.match(str(text or ''))
    if not found:
        return None
    letter = found.group(1).upper()
    places = set()
    for alphabet in (OPTION_LETTERS, CYRILLIC_LETTERS):
        if letter in alphabet:
            places.add(alphabet.index(letter))
    if letter in LOOKALIKE:
        places.add(OPTION_LETTERS.index(LOOKALIKE[letter]))
    return (places, str(text)[found.end():].strip()) if places else None


def _options(question):
    """The options as the list prints them: a letter the model typed is taken off only when every option carries
    its own, in order (A), B), C)… or А), Б), В)…); otherwise every option is kept exactly as given."""
    options = [str(option).strip() for option in question.get('options') or [] if str(option or '').strip()]
    typed = [_typed(option) for option in options]
    if options and all(found and index in found[0] for index, found in enumerate(typed)):
        return [found[1] for found in typed]
    return options


def _answer_text(question):
    """The answer as printed in a key cell when no letter stands for it: a typed letter taken off as for options."""
    answer = str(question.get('answer') or '').strip()
    found = _typed(answer)
    if found and found[1] and min(found[0]) < len(_options(question)):
        return found[1]
    return answer


def _find(answer, options, alike=True):
    """The position of the option `answer` names, or None when none or more than one does.

    Exactly first, then in the looser form, each taken only when it matches
    one option; two options that are one text once normalised give no
    letter and no guess. Only when neither matches does the 0.8 likeness
    count, and only between texts with the same digits and signs.
    """
    for form in (_exact, _loose):
        wanted = form(answer)
        hits = [index for index, option in enumerate(options) if form(option) == wanted]
        if len(hits) == 1:
            return hits[0]
        if hits:
            return None
    wanted = _loose(answer)
    if not alike or not re.search(r'[^\W\d_]', wanted):
        return None
    texts = [_loose(option) for option in options]
    scores = [difflib.SequenceMatcher(None, wanted, text).ratio() for text in texts]
    best = max(range(len(scores)), key=scores.__getitem__)
    if scores[best] < ALIKE or scores.count(scores[best]) != 1:
        return None
    return best if SKELETON.findall(wanted) == SKELETON.findall(texts[best]) else None


def key_letter(question):
    """The letter of a closed question's correct option, or None when its answer matches no option well enough."""
    options = _options(question)
    answer = str(question.get('answer') or '').strip()
    if not options or not answer:
        return None
    only = LETTER_ONLY.match(answer)
    if only and only.group(1).upper() in OPTION_LETTERS[:len(options)]:
        return only.group(1).upper()
    found = _find(answer, options, alike=False)
    if found is not None:
        return OPTION_LETTERS[found]
    typed = _typed(answer)
    if typed and typed[1]:
        # "C) Xloroplast": the letter and the text must name the same option, or the key prints the answer.
        found = _find(typed[1], options)
        return OPTION_LETTERS[found] if found is not None and found in typed[0] else None
    found = _find(answer, options)
    return OPTION_LETTERS[found] if found is not None else None


def _marks(question, default=0):
    try:
        marks = int(question.get('marks') or 0)
    except (TypeError, ValueError):
        marks = 0
    return marks if marks > 0 else default


def closed_questions(ctx):
    """The closed questions in the order the paper numbers them: choice, then those on the passage."""
    return ctx.questions('choice') + ctx.questions('passage')


def total_marks(ctx):
    """The paper's total: the customer's total points when given, else the questions' marks (a closed one is 1)."""
    given = ctx.fact('total_points')
    if given and re.fullmatch(r'\d{1,4}', given.strip()):
        return int(given)
    return sum(_marks(question, 1) for question in closed_questions(ctx)) + sum(
        _marks(question) for question in ctx.questions('open'))


def _scripted(ctx, text, style):
    """Text as markup with _{..} and ^{..} set as sub- and superscripts no smaller than 9 pt (blocks.json).

    text_rules run over the whole line first, so the spaces and the no-break
    glue around a marker are the line's: run over each piece alone, a piece
    starting with a space would lose it.
    """
    size = max(9.0, round(style.fontSize * 0.78, 1))
    rise = round(style.fontSize * 0.33, 1)
    text = ctx.plain(text)
    out, last = [], 0
    for found in SCRIPT.finditer(text):
        out.append(escape(text[last:found.start()]))
        tag = 'sub' if found.group(1) == '_' else 'super'
        out.append(f'<{tag} size="{size}" rise="{rise}">{escape(found.group(2) or found.group(3))}</{tag}>')
        last = found.end()
    out.append(escape(text[last:]))
    return ''.join(out).replace('\n', '<br/>')


def _number_style(ctx, style, number):
    """`style` with the question number hung in the gutter, right-aligned at 7 mm."""
    font = f'{ctx.face}-Bold'
    width = stringWidth(number, font, style.fontSize)
    return _style(ctx, style, leftIndent=GUTTER_MM * MM, bulletIndent=max(0.0, NUMBER_MM * MM - width),
                  bulletFontName=font, bulletFontSize=style.fontSize)


def _grid_table(rows, widths, commands=()):
    drawn = Table(rows, colWidths=widths, hAlign='LEFT')
    drawn.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0),
                               ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('TOPPADDING', (0, 0), (-1, -1), 0),
                               ('BOTTOMPADDING', (0, 0), (-1, -1), 0), *commands]))
    return drawn


# ---------------------------------------------------------------- cell_strip


class Cells(Flowable):
    """One row of ruled cells on the canvas: each a box with its label at the top left, its value under it.

    `cells` are dicts of x, width, label, value (markup Paragraph or None),
    total ("/ 22" set at the bottom right) and heavy; a cell with no box (a
    removed one keeps its place) has `box` False.
    """

    def __init__(self, cells, height, font, small, heavy=0.9, light=0.7):
        super().__init__()
        self.cells, self.minimum, self.font, self.small = cells, height, font, small
        self.heavy, self.light = heavy, light

    def wrap(self, width, height):
        self.width = width
        tallest = self.minimum
        for cell in self.cells:
            if cell.get('value') is not None:
                _, need = cell['value'].wrap(cell['width'] - 3.2 * MM, 10_000)
                tallest = max(tallest, need + self.small * 1.35 + 2.6 * MM)
        self.height = tallest
        return width, self.height

    def draw(self):
        canvas = self.canv
        canvas.saveState()
        canvas.setStrokeColor(INK)
        canvas.setFillColor(INK)
        for cell in self.cells:
            if not cell.get('box', True):
                continue
            canvas.setLineWidth(self.heavy if cell.get('heavy') else self.light)
            canvas.rect(cell['x'], 0, cell['width'], self.height, stroke=1, fill=0)
            if cell.get('label'):
                canvas.setFont(self.font, self.small)
                canvas.drawString(cell['x'] + 1.6 * MM, self.height - self.small - 1.1 * MM, cell['label'])
            if cell.get('total'):
                canvas.setFont(self.font, self.small)
                canvas.drawRightString(cell['x'] + cell['width'] - 1.6 * MM, 1.3 * MM, cell['total'])
            value = cell.get('value')
            if value is not None:
                _, need = value.wrap(cell['width'] - 3.2 * MM, 10_000)
                top = self.height - self.small * 1.35 - 1.6 * MM
                value.drawOn(canvas, cell['x'] + 1.6 * MM, top - need)
        canvas.restoreState()


def _cell_width(ctx, spec):
    if isinstance(spec.get('width_mm'), (int, float)):
        return min(ctx.width, max(5 * MM, spec['width_mm'] * MM))
    return ctx.width * _num(spec.get('share'), 1.0, 0.02, 1.0)


def _cell_value(ctx, spec):
    """A cell's value as printed: its fact through its `format` label, else None; '' for a blank to fill."""
    field_id = spec.get('fact')
    if not isinstance(field_id, str):
        return None
    value = ctx.fact(field_id)
    if value is None:
        return '' if ctx.blank(field_id) else None
    if _has_label(ctx, spec.get('format')):
        return ctx.label(spec['format'])
    return value


def _drops(ctx, spec):
    """Whether a cell is left out by its `drop_if`: {fact, pattern} matching the fact's value (a BSB's mark cell)."""
    rule = spec.get('drop_if')
    if not isinstance(rule, dict) or not isinstance(rule.get('fact'), str):
        return False
    value = ctx.fact(rule['fact'])
    try:
        return bool(value) and bool(re.search(str(rule.get('pattern') or '^$'), value, re.IGNORECASE))
    except re.error:
        return False


@block('cell_strip', fallback=lambda ctx, place: _strip_plain(ctx, place))
def cell_strip(ctx, place):
    """A boxed row or two of labelled cells, empty to write in or filled from facts (a pupil strip, a head box).

    params: rows [[{label (a label key), fact (a field id: its value under the
    label; a field that draws a blank leaves the cell empty, one that does not
    leaves the cell out and the others in the row share its width), format (a
    label key printing the fact through a slot), share (of the frame) or
    width_mm, gap_mm (air before the cell), heavy (a heavier box: the teacher's
    cells), total (true or a field id: "/ N" at the bottom right, N the total
    points, else the questions' marks), when (a predicate or a list that must
    all hold: else the cell is left out but keeps its place, so the teacher's
    cells stay at the right), drop_if ({fact, pattern}: the same, by a fact's
    wording), style (the value's: body | bold | title, else the
    placement's)}]]; height_mm (10: the room to write in); overline (a label
    key in tracked capitals over the strip, under a heavy rule); value_style
    body | bold | title; row_gap_mm (2: 0 joins the rows into one box, a head box).
    """
    params = _params(place)
    rows = [row for row in params.get('rows') or () if isinstance(row, list)]
    small = max(7.5, round(ctx.size * 0.82 * 2) / 2)
    height = _num(params.get('height_mm'), 10.0, 5, 40) * MM
    between = _num(params.get('row_gap_mm'), 2.0, 0, 20) * MM
    chosen = params.get('value_style') if params.get('value_style') in ('body', 'bold', 'title') else 'bold'
    made = []
    for row in rows:
        specs = [spec for spec in row if isinstance(spec, dict)]
        kept, x, drawn = [], 0.0, False
        values = [_cell_value(ctx, spec) for spec in specs]
        # Cells whose fact the paper leaves out give their width to the others in the row.
        gone = sum(_cell_width(ctx, spec) for spec, value in zip(specs, values)
                   if isinstance(spec.get('fact'), str) and value is None)
        stay = sum(_cell_width(ctx, spec) for spec, value in zip(specs, values)
                   if not (isinstance(spec.get('fact'), str) and value is None))
        stretch = (stay + gone) / stay if stay and gone else 1.0
        for spec, value in zip(specs, values):
            if isinstance(spec.get('fact'), str) and value is None:
                continue
            width = _cell_width(ctx, spec) * stretch
            x += _num(spec.get('gap_mm'), 0.0, 0, 60) * MM
            width = min(width, ctx.width - x)
            if width <= 2 * MM:
                break
            cell = {'x': x, 'width': width, 'heavy': bool(spec.get('heavy'))}
            if not _all_hold(ctx, place, spec.get('when')) or _drops(ctx, spec):
                cell['box'] = False
            else:
                drawn = True
                cell['label'] = ctx.plain(_word(ctx, spec.get('label'))) if spec.get('label') else ''
                if spec.get('total'):
                    cell['total'] = f'/ {total_marks(ctx)}' if total_marks(ctx) else ''
                if value:
                    own = spec.get('style') if spec.get('style') in ('body', 'bold', 'title') else chosen
                    style = _style(ctx, 'bold' if own != 'body' else 'body', alignment=TA_LEFT)
                    if own == 'title':
                        size = round(ctx.size * 1.3 * 2) / 2
                        style = _style(ctx, style, fontSize=size, leading=size * 1.22)
                    cell['value'] = Paragraph(ctx.text(value, style), style)
            kept.append(cell)
            x += width
        if drawn:
            made.append(Cells(kept, height, ctx.face, small))
            made.append(Spacer(1, between))
    if not made:
        return []
    made.pop()
    overline = params.get('overline')
    if _has_label(ctx, overline):
        made[:0] = [Hair(thickness=1.4, above=0, below=1.6 * MM),
                    _tracked(ctx, ctx.label(overline).upper(), f'{ctx.face}-Bold', small, small * 1.5, 0.9),
                    Spacer(1, 1.2 * MM)]
    return _finish(place, made, after=ctx.leading * 0.6)


def _strip_plain(ctx, place):
    """"Label: ____" on one line, the cells' values where they have one."""
    pieces = []
    for row in _params(place).get('rows') or ():
        for spec in row if isinstance(row, list) else ():
            if not isinstance(spec, dict) or not _all_hold(ctx, place, spec.get('when')) or _drops(ctx, spec):
                continue
            value = _cell_value(ctx, spec)
            if isinstance(spec.get('fact'), str) and value is None:
                continue
            word = _word(ctx, spec.get('label')) if spec.get('label') else ''
            pieces.append(f"{word} {value or '_' * 8}".strip())
    return [Paragraph(ctx.text('   '.join(pieces), 'body'), ctx.styles['body']), Spacer(1, ctx.leading * 0.5)] \
        if pieces else []


# ---------------------------------------------------------------- question_list


class AnswerBox(Flowable):
    """Room for a written answer: a box with its label, dotted rows, and a score tab under its right edge."""

    def __init__(self, width, rows, label, tab, font, small):
        super().__init__()
        self.box_width, self.rows, self.label, self.tab = width, rows, label, tab
        self.font, self.small = font, small

    def wrap(self, width, height):
        self.width = width
        self.box = self.small * 1.6 + self.rows * ROW_MM * MM
        self.height = self.box + (TAB_MM[1] * MM if self.tab else 0)
        return width, self.height

    def draw(self):
        canvas = self.canv
        canvas.saveState()
        canvas.setStrokeColor(INK)
        canvas.setFillColor(INK)
        x, bottom = self.width - self.box_width, self.height - self.box
        canvas.setLineWidth(0.7)
        canvas.rect(x, bottom, self.box_width, self.box, stroke=1, fill=0)
        canvas.setFont(f'{self.font}-Bold', self.small)
        if self.label:
            canvas.drawString(x + 1.8 * MM, self.height - self.small * 1.25, self.label)
        canvas.setLineWidth(0.7)
        canvas.setDash(0.7, 1.6)
        for row in range(1, self.rows):
            y = bottom + row * ROW_MM * MM
            canvas.line(x + 1.8 * MM, y, x + self.box_width - 1.8 * MM, y)
        canvas.setDash()
        if self.tab:
            word, total = self.tab
            width, height = TAB_MM[0] * MM, TAB_MM[1] * MM
            left = x + self.box_width - width
            canvas.rect(left, bottom - height, width, height, stroke=1, fill=0)
            canvas.setFont(f'{self.font}-Bold', self.small)
            canvas.drawString(left + 1.6 * MM, bottom - height + 2.0 * MM, word)
            canvas.setFont(self.font, self.small)
            canvas.drawRightString(left + width - 1.6 * MM, bottom - height + 2.0 * MM, total)
        canvas.restoreState()


def _numbers(ctx, kind, start=None):
    """The number of the first question of `kind`, numbered through the paper: choice, passage, open."""
    if isinstance(start, int) and start > 0:
        return start
    if kind == 'passage':
        return len(ctx.questions('choice')) + 1
    if kind == 'open':
        return len(ctx.questions('choice')) + len(ctx.questions('passage')) + 1
    return 1


def _stem_lines(question):
    return [line.strip() for line in str(question.get('stem') or '').split('\n') if line.strip()]


def _statements(ctx, lines, style):
    """DTM statements, the stem's lines after its first: one a line, or two columns read downwards from six."""
    if not lines:
        return []
    column = ctx.width - GUTTER_MM * MM
    half = column / 2
    widest = max(stringWidth(ctx.plain(line), style.fontName, style.fontSize) for line in lines)
    paragraphs = [Paragraph(ctx.text(line, style), style) for line in lines]
    if len(lines) >= STATEMENTS_TWO and widest <= half - OPTION_AIR_MM * MM:
        down = (len(lines) + 1) // 2
        rows = [[paragraphs[row], paragraphs[row + down] if row + down < len(paragraphs) else '']
                for row in range(down)]
        table = _grid_table(rows, [half, half], [('BOTTOMPADDING', (0, 0), (-1, -1), 1)])
        return [_indented(table, GUTTER_MM * MM, ctx.width)]
    indented = _style(ctx, style, leftIndent=GUTTER_MM * MM + 2 * MM, spaceBefore=1)
    return [Paragraph(ctx.text(line, indented), indented) for line in lines]


def _indented(flowable, indent, width):
    """`flowable` set `indent` points in from the frame's left edge."""
    return _grid_table([['', flowable]], [indent, width - indent])


def _option_columns(ctx, options, style, choice):
    """How many columns a question's options take: 4, 2 or 1 by the widest, as the mock measured; or as asked.

    The mock measured the option's text, its letter set in the air: 31.5 mm
    of text in a 39.5 mm column, 70 in 79.
    """
    if choice in (1, 2, 4):
        return choice
    column = ctx.width - GUTTER_MM * MM
    widest = max(stringWidth(ctx.plain(text), style.fontName, style.fontSize) for text in options)
    for count in (4, 2):
        if len(options) >= count and widest <= column / count - OPTION_AIR_MM * MM:
            return count
    return 1


def _option_grid(ctx, options, use_letters, style, choice):
    letters = [f'{OPTION_LETTERS[index]})' if use_letters else f'{index + 1})' for index in range(len(options))]
    columns = _option_columns(ctx, options, style, choice)
    column = (ctx.width - GUTTER_MM * MM) / columns
    bold = f'{ctx.face}-Bold'
    cells = []
    for letter, text in zip(letters, options):
        hang = stringWidth(f'{letter} ', bold, style.fontSize)
        chosen = _style(ctx, style, leftIndent=hang, firstLineIndent=-hang)
        cells.append(Paragraph(f'<font name="{bold}">{ctx.text(letter, chosen)}</font> {ctx.text(text, chosen)}',
                               chosen))
    rows = [cells[start:start + columns] for start in range(0, len(cells), columns)]
    rows = [row + [''] * (columns - len(row)) for row in rows]
    table = _grid_table(rows, [column] * columns, [('RIGHTPADDING', (0, 0), (-1, -1), 2 * MM),
                                                   ('BOTTOMPADDING', (0, 0), (-1, -1), 1.2)])
    return _indented(table, GUTTER_MM * MM, ctx.width)


def _closed_item(ctx, place, question, number):
    params = _params(place)
    body = ctx.styles['body']
    lines = _stem_lines(question)
    first = lines[0] if lines else ''
    label = f'{number}.'
    style = _number_style(ctx, body, label)
    made = [Paragraph(ctx.text(first, style), style, bulletText=label)]
    made += _statements(ctx, lines[1:], body)
    options = _options(question)
    if options:
        choice = _int(params.get('option_columns'), 0, 0, 4) if params.get('option_columns') != 'auto' else 0
        made.append(Spacer(1, 1.5))
        made.append(_option_grid(ctx, options, params.get('letters', True) is not False, body, choice))
    return made


def _open_item(ctx, place, question, number):
    params = _params(place)
    body = ctx.styles['body']
    lines = _stem_lines(question) or ['']
    label = f'{number}.'
    style = _number_style(ctx, body, label)
    marks = _marks(question)
    stem = Paragraph(ctx.text(lines[0], style), style, bulletText=label)
    made = []
    if params.get('marks', True) and marks:
        right = Paragraph(ctx.text(_counted(ctx, 'marks', marks, 'marks_one'), body),
                          _style(ctx, body, alignment=TA_RIGHT))
        made.append(_grid_table([[stem, right]], [ctx.width - 24 * MM, 24 * MM]))
    else:
        made.append(stem)
    made += _statements(ctx, lines[1:], body)
    rows = _int(params.get('answer_rows'), 0, 0, ROWS_MAX)
    if marks:
        rows = max(ROWS_MIN, min(ROWS_MAX, marks * ROWS_PER_MARK))
    rows = rows or ROWS_MIN
    score = params.get('score') if isinstance(params.get('score'), dict) else None
    tab = None
    if score and marks and _has_label(ctx, score.get('label')) and _all_hold(ctx, place, score.get('when')):
        tab = (ctx.plain(ctx.label(score['label'])), f'/ {marks}')
    small = max(7.5, round(ctx.size * 0.82 * 2) / 2)
    answer = ctx.plain(_word(ctx, params.get('answer_label'))) if params.get('answer_label') else ''
    made.append(Spacer(1, 1.5 * MM))
    made.append(AnswerBox(ctx.width - GUTTER_MM * MM, rows, answer, tab, ctx.face, small))
    return made


class Barred(Flowable):
    """A paragraph inset from a rule down its left edge, `indent` from the frame; it splits between its lines.

    Consecutive ones touch, so the rule runs unbroken down a passage of
    several paragraphs, and a passage longer than a page goes on over the
    next with its rule.
    """

    RULE, INSET, PAD = 0.8, 8.0, 1.5

    def __init__(self, paragraph, indent):
        super().__init__()
        self.paragraph, self.indent = paragraph, indent

    def wrap(self, width, height):
        self.width = width
        _, need = self.paragraph.wrap(width - self.indent - self.INSET, height)
        self.height = need + self.PAD
        return width, self.height

    def split(self, width, height):
        parts = self.paragraph.split(width - self.indent - self.INSET, height - self.PAD)
        return [Barred(part, self.indent) for part in parts] if len(parts) > 1 else []

    def draw(self):
        canvas = self.canv
        canvas.saveState()
        canvas.setStrokeColor(INK)
        canvas.setLineWidth(self.RULE)
        canvas.line(self.indent, 0, self.indent, self.height)
        canvas.restoreState()
        self.paragraph.drawOn(canvas, self.indent + self.INSET, self.PAD)


def _bar(ctx, section, part):
    """A passage set off by a rule down its left edge (konspekt's note line): its title bold, its text inset 8 pt."""
    heading = ctx.heading(part, section) if part else str((section or {}).get('heading') or '').strip()
    texts = [line.strip() for line in str((section or {}).get('body') or '').split('\n') if line.strip()]
    texts += [' '.join(str(item.get(key) or '').strip() for key in ('label', 'text') if item.get(key))
              for item in (section or {}).get('items') or [] if isinstance(item, dict)]
    texts = [text for text in texts if text]
    if not texts:
        return []
    made = [Barred(Paragraph(ctx.text(heading, 'bold'), ctx.styles['bold']), GUTTER_MM * MM)] if heading else []
    for flowable in made:
        # The title never stands alone at a page's foot: it goes on with the passage's first lines.
        flowable.keepWithNext = 1
    made += [Barred(Paragraph(ctx.text(text, 'body'), ctx.styles['body']), GUTTER_MM * MM) for text in texts]
    return made


def _intro(ctx, place):
    """The instruction over a paper's first questions: the first alternative whose `when` holds, as one paragraph."""
    for alternative in _params(place).get('intro') or ():
        if not isinstance(alternative, dict) or not _all_hold(ctx, place, alternative.get('when')):
            continue
        sentences = [_resolve(ctx, place, key, drop_empty=True) for key in alternative.get('sentences') or ()]
        text = ' '.join(sentence.strip() for sentence in sentences if sentence and sentence.strip())
        if not text:
            return []
        size = max(8.5, round(ctx.size * 0.86 * 2) / 2)
        style = _style(ctx, 'body', fontSize=size, leading=round(size * 1.35, 1), alignment=TA_LEFT,
                       spaceAfter=ctx.leading * 0.5)
        label = _word(ctx, alternative.get('label')) if alternative.get('label') else ''
        markup = ctx.text(text, style)
        if label:
            markup = f'<font name="{ctx.face}-Bold">{ctx.text(label, style)}</font> {markup}'
        return [Paragraph(markup, style)]
    return []


def _part_heading(ctx, place):
    """The part heading, once a paper: the passage's list names Part I only when no choice list did."""
    spec = _params(place).get('heading')
    if not isinstance(spec, dict) or not _has_label(ctx, spec.get('label')):
        return []
    drawn = getattr(ctx, 'study_headings', set())
    if spec['label'] in drawn or not _all_hold(ctx, place, spec.get('when', 'questions:both')):
        return []
    ctx.study_headings = drawn | {spec['label']}
    size = round(ctx.size * 1.05 * 2) / 2
    style = _style(ctx, 'h3', fontSize=size, leading=size * 1.3, spaceBefore=ctx.leading * 0.7, keepWithNext=1)
    hair = Hair(thickness=0.5, above=1.0 * MM, below=2.0 * MM)
    hair.keepWithNext = 1
    return [Paragraph(ctx.text(ctx.label(spec['label']), style), style), hair]


@block('question_list', fallback=lambda ctx, place: _questions_plain(ctx, place))
def question_list(ctx, place):
    """Numbered questions from content.questions, each kept on one page.

    params: filter choice | open | passage | all (choice leaves out the
    passage's); letters (Latin A-D in every language, true); option_columns
    auto | 1 | 2 | 4; answer_rows (the dotted rows of a written answer whose
    marks are not known; else two a mark, 2-10); marks (a written question's
    "(2 ball)" at the right of its first line); answer_label (a label key in
    the answer box); score ({label, when}: the "Ball: / 2" tab under the
    box); start (the first number; else numbered through the paper, choice,
    passage, open); heading ({label, when}: the part heading, by default only
    when both parts are drawn); intro ([{when, label, sentences}]: the
    instruction over the paper's first questions, the first alternative that
    holds, a sentence whose slot has no value left out); passage ({part,
    label, label_one}: for filter passage, the reference line, `#` the
    questions' numbers, then the passage with a rule down its left edge, kept
    with the first question).
    """
    params = _params(place)
    kind = params.get('filter') if params.get('filter') in ('choice', 'open', 'passage', 'all') else 'all'
    found = ctx.questions(kind)
    if not found:
        return []
    number = _numbers(ctx, kind if kind != 'all' else 'choice', params.get('start'))
    made = []
    if not getattr(ctx, 'study_intro_drawn', False):
        intro = _intro(ctx, place)
        if intro:
            ctx.study_intro_drawn = True
            made += intro
    made += _part_heading(ctx, place)
    lead = []
    spec = params.get('passage') if isinstance(params.get('passage'), dict) else None
    if kind == 'passage' and spec:
        last = number + len(found) - 1
        key = spec.get('label_one') if last == number and _has_label(ctx, spec.get('label_one')) else spec.get('label')
        part = ctx.entry.part(spec['part']) if isinstance(spec.get('part'), str) else None
        section = ctx.section(part['id'], place.instance) if part else None
        bar = _bar(ctx, section, part)
        if not bar:
            # Questions on a text the model never wrote: no line sends the pupil to a passage that is not there.
            ctx.warn('passage_missing')
        elif _has_label(ctx, key):
            # An Uzbek range takes the bare hyphen of its ordinal suffix ("9-11-savollarga"), as the mock does.
            dash = '-' if ctx.locale == 'uz' else '–'
            span = str(number) if last == number else f'{number}{dash}{last}'
            style = _style(ctx, 'bold', spaceBefore=ctx.leading * 0.4, spaceAfter=2, keepWithNext=1)
            lead.append(Paragraph(ctx.text(ctx.label(key).replace(NUMBER_MARK, span), style), style))
        if bar:
            lead += [*bar, Spacer(1, ctx.leading * 0.4)]
    gap = _num(params.get('gap_pt'), 10.0, 0, 40)
    for index, question in enumerate(found):
        item = (_closed_item if question.get('options') else _open_item)(ctx, place, question, number + index)
        if index or made or lead:
            first = item[0]
            if isinstance(first, Paragraph):
                first.style = _style(ctx, first.style, spaceBefore=gap)
            else:
                item.insert(0, Spacer(1, gap))
        if index == 0 and lead:
            # A passage of a usual length stays with its first question; a longer one flows on from where it
            # starts, so it never pushes a page of white before it.
            tall = sum(flowable.wrap(ctx.width, ctx.frame_height)[1] for flowable in lead)
            if tall > ctx.frame_height * 0.6:
                made += lead
            else:
                item = lead + item
        made.append(KeepTogether(item))
    return _finish(place, made, before=ctx.leading * 0.3, after=ctx.leading * 0.5)


def _questions_plain(ctx, place):
    """Today's question list: "1. stem", the options under it, a written question's marks."""
    params = _params(place)
    kind = params.get('filter') if params.get('filter') in ('choice', 'open', 'passage', 'all') else 'all'
    number = _numbers(ctx, kind if kind != 'all' else 'choice', params.get('start'))
    made = []
    for index, question in enumerate(ctx.questions(kind)):
        stem = ' '.join(_stem_lines(question))
        marks = _marks(question)
        made.append(Paragraph(ctx.text(f'{number + index}. {stem}' + (f' ({marks})' if marks and not
                                                                    question.get('options') else ''), 'body'),
                              ctx.styles['body']))
        for letter, option in zip(OPTION_LETTERS, _options(question)):
            made.append(Paragraph(ctx.text(f'    {letter}) {option}', 'body'), ctx.styles['body']))
    return made + [Spacer(1, ctx.leading * 0.5)] if made else []


# ---------------------------------------------------------------- answer_key


def _key_head(ctx, place):
    """The key's own head: a heavy rule, the word in tracked capitals, an italic note, the subject line, a hairline.

    With `head` plain it is the word alone, bold, as an answer sheet's heading.
    """
    params = _params(place)
    word = _word(ctx, params.get('label')) if params.get('label') else ''
    if params.get('head') == 'plain':
        if not word:
            return []
        style = _style(ctx, 'h3', spaceBefore=ctx.leading * 0.6, spaceAfter=3, keepWithNext=1)
        return [Paragraph(ctx.text(word, style), style)]
    made = [Hair(thickness=1.4, above=0, below=3.5 * MM)]
    if word:
        size = round(ctx.size * 1.18 * 2) / 2
        made.append(_tracked(ctx, word.upper(), f'{ctx.face}-Bold', size, size * 1.35, 2.4))
    note = _word(ctx, params.get('note')) if params.get('note') else ''
    small = max(8.5, round(ctx.size * 0.86 * 2) / 2)
    if note:
        style = _style(ctx, 'italic', fontSize=small, leading=small * 1.3, alignment=TA_CENTER)
        made.append(Paragraph(ctx.text(note, style), style))
    pieces = [ctx.fact(field_id) for field_id in params.get('subtitle') or () if isinstance(field_id, str)]
    formats = params.get('formats') if isinstance(params.get('formats'), dict) else {}
    pieces = [ctx.label(formats[field_id]) if value and _has_label(ctx, formats.get(field_id)) else value
              for field_id, value in zip(params.get('subtitle') or (), pieces)]
    subtitle = ', '.join(piece for piece in pieces if piece)
    if subtitle:
        style = _style(ctx, 'body', alignment=TA_CENTER, spaceBefore=1)
        made.append(Paragraph(ctx.text(subtitle, style), style))
    made.append(Hair(thickness=0.5, above=3.0 * MM, below=3.5 * MM))
    for flowable in made:
        flowable.keepWithNext = 1
    return made


def _strips(ctx, questions, first, per_row, empty):
    """Rows of number cells over letter cells: at most `per_row`, balanced (7 + 7 for 14)."""
    count = len(questions)
    rows = -(-count // per_row)
    across = -(-count // rows)
    cell = min(CELL_MAX_MM * MM, ctx.width / across)
    small = max(7.5, round(ctx.size * 0.82 * 2) / 2)
    number_style = _style(ctx, 'body', fontSize=small, leading=small * 1.2, alignment=TA_CENTER)
    letter_style = _style(ctx, 'bold', alignment=TA_CENTER)
    answer_style = _style(ctx, 'cell', alignment=TA_CENTER, fontSize=small, leading=small * 1.15)
    made = []
    for start in range(0, count, across):
        chunk = questions[start:start + across]
        numbers = [Paragraph(ctx.text(str(first + start + index), number_style), number_style)
                   for index in range(len(chunk))]
        letters = []
        for question in chunk:
            if empty:
                letters.append('')
                continue
            letter = key_letter(question)
            if letter:
                letters.append(Paragraph(ctx.text(letter, letter_style), letter_style))
            else:
                # No option matches the answer well enough: its own words, never a guessed letter.
                letters.append(Paragraph(ctx.text(_answer_text(question), answer_style),
                                         answer_style))
        table = Table([numbers, letters], colWidths=[cell] * len(chunk),
                      rowHeights=[NUMBER_ROW_MM * MM, None if not empty else LETTER_ROW_MM * MM], hAlign='LEFT')
        table.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 0.5, INK), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                                   ('TOPPADDING', (0, 0), (-1, -1), 1), ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5),
                                   ('LEFTPADDING', (0, 0), (-1, -1), 1), ('RIGHTPADDING', (0, 0), (-1, -1), 1),
                                   ('TOPPADDING', (0, 1), (-1, 1), 2.2), ('BOTTOMPADDING', (0, 1), (-1, 1), 2.2)]))
        if made:
            made.append(Spacer(1, 2 * MM))
        made.append(table)
    return made


def _explained(ctx, place, questions, first):
    """No | Answer | Explanation: the letter (or the answer's words) and the one-line explanation."""
    params = _params(place)
    columns = params.get('columns') if isinstance(params.get('columns'), list) else ['no', 'answer', 'explanation']
    heads = [_word(ctx, key) if isinstance(key, str) else '' for key in columns[:3]] + ['', '', '']
    cell, bold = ctx.styles['cell'], _style(ctx, 'cell', fontName=f'{ctx.face}-Bold')
    data = [[Paragraph(ctx.text(text, bold), bold) for text in heads[:3]]]
    for index, question in enumerate(questions):
        letter = key_letter(question) if question.get('options') else None
        answer = letter or _answer_text(question)
        data.append([Paragraph(ctx.text(str(first + index), cell), _style(ctx, cell, alignment=TA_CENTER)),
                     Paragraph(ctx.text(answer, bold if letter else cell), bold if letter else cell),
                     Paragraph(ctx.text(str(question.get('explanation') or '').strip(), cell), cell)])
    answer_width = 20 * MM if all(key_letter(question) for question in questions) else ctx.width * 0.3
    table = Table(data, colWidths=[12 * MM, answer_width, ctx.width - 12 * MM - answer_width], repeatRows=1,
                  hAlign='LEFT')
    table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 1.7 * MM),
                               ('RIGHTPADDING', (0, 0), (-1, -1), 1.7 * MM), ('TOPPADDING', (0, 0), (-1, -1), 1.3 * MM),
                               ('BOTTOMPADDING', (0, 0), (-1, -1), 1.3 * MM),
                               ('LINEABOVE', (0, 0), (-1, 0), 1.0, INK), ('LINEBELOW', (0, 0), (-1, 0), 0.7, INK),
                               ('LINEBELOW', (0, 1), (-1, -1), 0.5, INK), ('LINEBELOW', (0, -1), (-1, -1), 1.0, INK)]))
    return [table]


@block('answer_key', fallback=lambda ctx, place: _key_plain(ctx, place))
def answer_key(ctx, place):
    """The key from the closed questions' answers, the same grid empty as an answer sheet, or a table with reasons.

    params: style grid | sheet | explained; per_row (10 at most, balanced);
    label (a label key: the heading, KALITLAR or Javoblar varaqasi); head
    display (a heavy rule, the word tracked, centred) | plain (the word bold:
    an answer sheet); note (a label key under it: Faqat o‘qituvchi uchun);
    subtitle (field ids under the note, joined by commas) and formats ({field
    id: label key}: "7-sinf"); section (a label key over the grid: Test
    savollari); total (a label key, `#` the closed questions' marks, at the
    right under the grid); explain_when (a predicate or a list: when it holds,
    a grid is followed by the explanation table); columns (three label keys
    of the explanation table: No, Answer, Explanation); head_when_open (a
    paper of written questions only still gets the head, so its page break
    holds and the model answers under it start their own page). Style overall
    is the paper's maximum alone, `total` with the closed and the written
    marks: "Maksimal ball: 22 (14 + 8)", drawn under the model answers. Draws
    nothing for a paper without closed questions.
    """
    params = _params(place)
    style = params.get('style') if params.get('style') in ('grid', 'sheet', 'explained', 'overall') else 'grid'
    if style == 'overall':
        line = _overall(ctx, params)
        return _finish(place, line, before=ctx.leading * 0.2, after=ctx.leading * 0.6) if line else []
    questions = closed_questions(ctx)
    if style == 'explained' and params.get('include_open'):
        questions = questions + ctx.questions('open')
    if not questions:
        if params.get('head_when_open') and style != 'sheet' and ctx.questions('open'):
            return _finish(place, _key_head(ctx, place), before=ctx.leading * 0.2, after=ctx.leading * 0.2)
        return []
    per_row = _int(params.get('per_row'), PER_ROW, 1, PER_ROW)
    made = _key_head(ctx, place)
    section = _word(ctx, params.get('section')) if params.get('section') else ''
    if section and style != 'sheet':
        heading = _style(ctx, 'bold', spaceAfter=3, keepWithNext=1)
        made.append(Paragraph(ctx.text(section, heading), heading))
    if style == 'explained':
        made += _explained(ctx, place, questions, 1)
    else:
        made.append(KeepTogether(_strips(ctx, questions, 1, per_row, style == 'sheet')))
        total = sum(_marks(question, 1) for question in questions)
        line = _counted(ctx, params.get('total'), total) if params.get('total') and style == 'grid' else ''
        if line:
            small = max(8.5, round(ctx.size * 0.86 * 2) / 2)
            right = _style(ctx, 'body', fontSize=small, leading=small * 1.3, alignment=TA_RIGHT, spaceBefore=2)
            made.append(Paragraph(ctx.text(line, right), right))
        if style == 'grid' and params.get('explain_when') and _all_hold(ctx, place, params['explain_when']):
            made.append(Spacer(1, ctx.leading * 0.6))
            made += _explained(ctx, place, questions, 1)
    return _finish(place, made, before=ctx.leading * 0.2, after=ctx.leading * 0.6)


def _overall(ctx, params):
    """The paper's maximum under its model answers, the closed and the written marks in brackets when both count.

    The customer's total points stand alone unless the marks add up to them:
    the key never prints a sum that disagrees with the pupil strip's "/ N".
    """
    opened = ctx.questions('open')
    if not opened or not params.get('total'):
        return []
    closed = sum(_marks(question, 1) for question in closed_questions(ctx))
    written = sum(_marks(question) for question in opened)
    total = total_marks(ctx)
    if not total:
        return []
    number = f'{total} ({closed} + {written})' if closed and written and closed + written == total else str(total)
    line = _counted(ctx, params['total'], number)
    if not line:
        return []
    small = max(8.5, round(ctx.size * 0.86 * 2) / 2)
    right = _style(ctx, 'bold', fontSize=small, leading=small * 1.3, alignment=TA_RIGHT, spaceBefore=2)
    return [Paragraph(ctx.text(line, right), right)]


def _key_plain(ctx, place):
    """"1 — B" lines under the heading; the answer's words where no letter matches."""
    params = _params(place)
    if params.get('style') == 'overall':
        return _overall(ctx, params)
    questions = closed_questions(ctx)
    if not questions:
        return []
    made = []
    word = _word(ctx, params.get('label')) if params.get('label') else ''
    if word:
        made.append(Paragraph(ctx.text(word, 'bold'), ctx.styles['bold']))
    empty = params.get('style') == 'sheet'
    for number, question in enumerate(questions, 1):
        answer = '____' if empty else (key_letter(question) or _answer_text(question))
        made.append(Paragraph(ctx.text(f'{number} — {answer}', 'body'), ctx.styles['body']))
    return made + [Spacer(1, ctx.leading * 0.5)]


# ---------------------------------------------------------------- formula_line


@block('formula_line', fallback=lambda ctx, place: _formula_plain(ctx, place))
def formula_line(ctx, place):
    """Each formula centred with its number at the right margin, its legend under it, kept with it.

    The part's items: label the formula in plain symbols (_{12} a subscript,
    ^{3} a power), text its legend, value its number when the model gave one.
    params: numbering section ("(3.1)": the section's number, then the
    formula's in it) | plain ("(1)", through the paper) | none; legend (a
    label key run in before a legend that does not start with it: "bu
    yerda:").
    """
    params = _params(place)
    items = [item for item in (place.section or {}).get('items') or [] if isinstance(item, dict)
             and str(item.get('label') or '').strip()]
    if not items:
        return []
    numbering = params.get('numbering') if params.get('numbering') in ('section', 'plain', 'none') else 'section'
    size = round(ctx.size * 1.12 * 2) / 2
    formula = _style(ctx, 'body', fontSize=size, leading=size * 1.45, alignment=TA_CENTER)
    number = _style(ctx, 'body', alignment=TA_RIGHT, leading=size * 1.45)
    legend_style = _style(ctx, 'italic', alignment=TA_LEFT, spaceBefore=1)
    word = _word(ctx, params.get('legend')) if params.get('legend') else ''
    side = 18 * MM
    made = []
    for index, item in enumerate(items, 1):
        label = str(item.get('value') or '').strip()
        if not label and numbering != 'none':
            section = ctx.count(1) if numbering == 'section' else 0
            counted = getattr(ctx, 'study_formulas', 0) + 1
            ctx.study_formulas = counted
            label = f'({section}.{index})' if section else f'({counted})'
        elif label and not label.startswith('('):
            label = f'({label})'
        row = [['', Paragraph(_scripted(ctx, str(item['label']).strip(), formula), formula),
                Paragraph(ctx.text(label, number), number) if label else '']]
        table = _grid_table(row, [side, ctx.width - 2 * side, side],
                            [('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('TOPPADDING', (0, 0), (-1, -1), 2),
                             ('BOTTOMPADDING', (0, 0), (-1, -1), 2)])
        group = [table]
        legend = str(item.get('text') or '').strip()
        if legend:
            markup = _scripted(ctx, legend, legend_style)
            if word and not _normal(legend).startswith(_normal(word)):
                markup = f'{ctx.text(word, legend_style)} {markup}'
            group.append(Paragraph(markup, legend_style))
        if made:
            group.insert(0, Spacer(1, ctx.leading * 0.3))
        made.append(KeepTogether(group))
    return _finish(place, made, before=ctx.leading * 0.4, after=ctx.leading * 0.5)


def _formula_plain(ctx, place):
    """Each formula and its legend as a body line."""
    made = []
    for item in (place.section or {}).get('items') or []:
        if isinstance(item, dict) and str(item.get('label') or '').strip():
            text = ' — '.join(str(item.get(key) or '').strip() for key in ('label', 'text')
                              if str(item.get(key) or '').strip())
            made.append(Paragraph(ctx.text(text, 'body'), ctx.styles['body']))
    return made + [Spacer(1, ctx.leading * 0.5)] if made else []


# ---------------------------------------------------------------- samples


def _text3(uz, ru, en):
    return {'uz': uz, 'ru': ru, 'en': en}


def _question(stem, options, answer, explanation='', marks=1, topic=''):
    return {'stem': stem, 'options': options, 'answer': answer, 'explanation': explanation, 'marks': marks,
            'topic': topic}


# Invented questions in the three languages: two closed, one with statements, one on a passage, one written.
SAMPLE_QUESTIONS = _text3(
    [_question('Hujayraning irsiy axborotini saqlaydigan qism qaysi?', ['Yadro', 'Ribosoma', 'Vakuola', 'Lizosoma'],
               'Yadro', 'Irsiy axborot yadroda saqlanadi.'),
     _question('Prokariot hujayralar eukariotlardan nimasi bilan farq qiladi?',
               ['Ularda shakllangan yadro bo‘lmaydi', 'Ularda sitoplazma bo‘lmaydi',
                'Ularda ribosoma bo‘lmaydi', 'Ularda hujayra membranasi bo‘lmaydi'],
               'Ularda shakllangan yadro bo‘lmaydi', 'Prokariotlarda yadro qobig‘i yo‘q.'),
     _question('Qaysilari membranali organoid?\n1) yadro\n2) ribosoma\n3) mitoxondriya\n4) xloroplast\n'
               '5) hujayra markazi\n6) lizosoma', ['1, 2, 3', '1, 3, 4, 6', '2, 5', '4, 5, 6'], '1, 3, 4, 6'),
     _question('Matnga ko‘ra, o‘simlik qaysi gazni yutadi?', ['Kislorod', 'Karbonat angidrid', 'Azot', 'Vodorod'],
               'Karbonat angidrid', 'Matnning ikkinchi gapida.', topic='passage'),
     _question('Mitoxondriyaning vazifasini tushuntiring.', [], 'Hujayra uchun energiya hosil qiladi.',
               'Energiya — 1 ball, jarayon — 1 ball.', 2)],
    [_question('Какая часть клетки хранит наследственную информацию?', ['Ядро', 'Рибосома', 'Вакуоль',
                                                                        'Лизосома'], 'Ядро',
               'Наследственная информация хранится в ядре.'),
     _question('Чем прокариоты отличаются от эукариот?',
               ['У них нет оформленного ядра', 'У них нет цитоплазмы', 'У них нет рибосом',
                'У них нет клеточной мембраны'], 'У них нет оформленного ядра', 'У прокариот нет ядерной оболочки.'),
     _question('Какие органоиды мембранные?\n1) ядро\n2) рибосома\n3) митохондрия\n4) хлоропласт\n'
               '5) клеточный центр\n6) лизосома', ['1, 2, 3', '1, 3, 4, 6', '2, 5', '4, 5, 6'], '1, 3, 4, 6'),
     _question('Какой газ, согласно тексту, поглощает растение?', ['Кислород', 'Углекислый газ', 'Азот',
                                                                   'Водород'], 'Углекислый газ',
               'Во втором предложении текста.', topic='passage'),
     _question('Объясните функцию митохондрии.', [], 'Она производит энергию для клетки.',
               'Энергия — 1 балл, процесс — 1 балл.', 2)],
    [_question('Which part of the cell stores hereditary information?', ['Nucleus', 'Ribosome', 'Vacuole',
                                                                         'Lysosome'], 'Nucleus',
               'Hereditary information is kept in the nucleus.'),
     _question('How do prokaryotes differ from eukaryotes?',
               ['They have no true nucleus', 'They have no cytoplasm', 'They have no ribosomes',
                'They have no cell membrane'], 'They have no true nucleus', 'Prokaryotes have no nuclear envelope.'),
     _question('Which organelles have a membrane?\n1) nucleus\n2) ribosome\n3) mitochondrion\n4) chloroplast\n'
               '5) centrosome\n6) lysosome', ['1, 2, 3', '1, 3, 4, 6', '2, 5', '4, 5, 6'], '1, 3, 4, 6'),
     _question('According to the text, which gas does the plant take in?', ['Oxygen', 'Carbon dioxide', 'Nitrogen',
                                                                            'Hydrogen'], 'Carbon dioxide',
               'In the second sentence of the text.', topic='passage'),
     _question('Explain the function of the mitochondrion.', [], 'It produces energy for the cell.',
               'Energy — 1 point, the process — 1 point.', 2)])
SAMPLE_PASSAGE = {'id': 'passage', 'layout': 'text', 'items': [],
                  'heading': _text3('Fotosintez', 'Фотосинтез', 'Photosynthesis'),
                  'body': _text3('Fotosintez xloroplastlarda yorug‘lik ta’sirida kechadi. O‘simlik havodan karbonat '
                                 'angidridni yutadi va kislorod ajratadi.',
                                 'Фотосинтез идёт в хлоропластах под действием света. Растение поглощает углекислый '
                                 'газ и выделяет кислород.',
                                 'Photosynthesis runs in the chloroplasts under light. The plant takes in carbon '
                                 'dioxide and gives off oxygen.')}
SAMPLE_FORMULAS = {'id': 'formulas', 'heading': '', 'body': '', 'layout': 'list', 'items': [
    {'label': 'F = m · a', 'value': '',
     'text': _text3('bu yerda: F — kuch, m — massa, a — tezlanish.', 'где: F — сила, m — масса, a — ускорение.',
                    'where: F is the force, m the mass, a the acceleration.')},
    {'label': 'E_{k} = m · v^{2} / 2', 'value': '3.4',
     'text': _text3('E_{k} — kinetik energiya.', 'E_{k} — кинетическая энергия.', 'E_{k} is the kinetic energy.')}]}
PUPIL_ROWS = [[{'label': 'name', 'width_mm': 167, 'when': 'nofact:pupil_identity=false'}],
              [{'label': 'class', 'width_mm': 43, 'when': 'nofact:pupil_identity=false'},
               {'label': 'date', 'width_mm': 66, 'when': 'nofact:pupil_identity=false'},
               {'label': 'score', 'width_mm': 30, 'gap_mm': 4, 'heavy': True, 'total': True,
                'when': 'nofact:teacher_score=false'},
               {'label': 'mark', 'width_mm': 24, 'heavy': True, 'when': 'nofact:teacher_score=false',
                'drop_if': {'fact': 'kind', 'pattern': 'bsb|chsb|бсб|чсб'}}]]
TEST = {'template': 'study_test', 'entry': 'pdf.test', 'questions': SAMPLE_QUESTIONS}
KEY = {'label': 'key', 'note': 'key_note', 'subtitle': ['subject', 'class_level'], 'formats': {'class_level': 'class_n'},
       'section': 'key_choice', 'total': 'max_score', 'columns': ['no', 'answer_col', 'explanation']}
SUBJECT = {'subject': _text3('Biologiya', 'Биология', 'Biology'), 'class_level': '7'}

SAMPLES = (
    {**TEST, 'block': 'cell_strip', 'name': 'pupil strip, score out of the marks', 'part': 'pupil_line',
     'params': {'rows': PUPIL_ROWS, 'height_mm': 10}},
    {**TEST, 'block': 'cell_strip', 'name': 'no name line: the teacher’s cells stay at the right',
     'part': 'pupil_line', 'facts': {'pupil_identity': 'false', 'total_points': '20'},
     'params': {'rows': PUPIL_ROWS}},
    {**TEST, 'block': 'cell_strip', 'name': 'a BSB: the score cell without the mark', 'part': 'pupil_line',
     'facts': {'kind': '2-BSB'}, 'params': {'rows': PUPIL_ROWS}},
    {'block': 'cell_strip', 'name': 'a head box of facts, one left out, one blank, joined rows',
     'template': 'study_dars_ishlanmasi', 'entry': 'pdf.dars_ishlanmasi', 'part': 'head',
     'facts': {'grade': _text3('5-«A»', '5 «А»', '5A'), 'subject': _text3('Matematika', 'Математика', 'Mathematics'),
               'topic': _text3('Kasrlarni qo‘shish', 'Сложение дробей', 'Adding fractions'), 'duration': '45'},
     'params': {'overline': 'overline', 'row_gap_mm': 0, 'rows': [
         [{'label': 'date_l', 'fact': 'date', 'share': 0.3}, {'label': 'grade_l', 'fact': 'grade', 'share': 0.2},
          {'label': 'subject_l', 'fact': 'subject', 'share': 0.5}],
         [{'label': 'topic_l', 'fact': 'topic', 'share': 1, 'style': 'title'}],
         [{'label': 'school_l', 'fact': 'school', 'share': 0.5},
          {'label': 'duration_l', 'fact': 'duration', 'format': 'minutes', 'share': 0.5}]]}},
    {**TEST, 'block': 'question_list', 'name': 'choice: four, two by two, one a line, statements, intro, heading',
     'part': 'part_choice', 'facts': {'time_min': '20'},
     'params': {'filter': 'choice', 'option_columns': 'auto', 'heading': {'label': 'part_choice'},
                'intro': [{'label': 'instruction', 'sentences': ['one_answer', 'time', 'point_each']}]}},
    {**TEST, 'block': 'question_list', 'name': 'choice, one option a line, numbered options', 'part': 'part_choice',
     'params': {'filter': 'choice', 'option_columns': 1, 'letters': False}},
    {**TEST, 'block': 'question_list', 'name': 'the passage, its reference line and its question',
     'part': 'passage', 'section': SAMPLE_PASSAGE,
     'params': {'filter': 'passage', 'passage': {'part': 'passage', 'label': 'passage_lead',
                                                 'label_one': 'passage_lead_one'}}},
    {**TEST, 'block': 'question_list', 'name': 'written: marks, answer box, score tab', 'part': 'part_open',
     'params': {'filter': 'open', 'marks': True, 'answer_label': 'answer', 'score': {'label': 'score'},
                'heading': {'label': 'part_open', 'when': 'questions:open'}}},
    {**TEST, 'block': 'answer_key', 'name': 'the key grid, its head and the maximum', 'part': 'answer_key',
     'facts': SUBJECT, 'params': {'style': 'grid', **KEY}},
    {**TEST, 'block': 'answer_key', 'name': 'the key grid with its explanations', 'part': 'answer_key',
     'facts': {**SUBJECT, 'answer_extras': 'explained'},
     'params': {'style': 'grid', 'explain_when': 'fact:answer_extras=explained', 'per_row': 3, **KEY}},
    {**TEST, 'block': 'answer_key', 'name': 'the answer sheet, empty', 'part': 'answer_sheet',
     'params': {'style': 'sheet', 'head': 'plain', 'label': 'sheet'}},
    {**TEST, 'block': 'answer_key', 'name': 'self-study answers with explanations', 'part': 'answer_key',
     'params': {'style': 'explained', 'label': 'answers_self', 'note': 'self_note',
                'columns': ['no', 'answer_col', 'explanation']}},
    {**TEST, 'block': 'answer_key', 'name': 'the paper’s maximum under the model answers', 'part': 'model_answers',
     'params': {'style': 'overall', 'total': 'max_score'}},
    {'block': 'formula_line', 'name': 'formulas: numbered through, a given number, legends, scripts',
     'template': 'study_konspekt', 'entry': 'pdf.konspekt', 'part': 'formulas', 'section': SAMPLE_FORMULAS,
     'params': {'numbering': 'section', 'legend': 'legend'}},
)
