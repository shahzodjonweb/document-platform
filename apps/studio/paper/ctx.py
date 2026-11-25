"""What a paper block is given: the context of one build (`Ctx`) and its placement (`Place`).

The block contract (architecture 6.2): a block reads only these two, returns
flowables, does no I/O and is deterministic. Everything a block needs to know
about the paper is asked here, so the blocks stay small and agree with each
other:

- `fact(id)` the verified value of a field (the facts section that finish
  checked), or the clock value of a `clock` field the customer left out;
  `blank(id)` whether a ruled blank is drawn in its place;
- `label(key, **slots)` a fixed word of the template in the paper's language,
  its `{field}` slots filled with facts or left as blanks;
- `text(value, style)` text_rules applied and escaped, ready for a Paragraph;
- `number(level)` the heading counter, `questions(kind)` the test's questions,
  `section` and `heading` the written parts, `warn(code)` a code for the log;
- `mark(level, text)` and `contents()` the table of contents: headings mark
  themselves while the story is made, a contents block reads them when it is
  laid out (wrap it in `Lazy`), with page numbers from the build before.

`places(ctx)` resolves a template's flow into Places: one per placement, and
the placements of a group's parts once per instance the content holds, in
order. `holds(when, ctx, place)` is the closed `when` predicate of 6.3.
"""
import datetime
import re
from dataclasses import dataclass, field as attribute

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Flowable
from reportlab.platypus.flowables import _Container, _listWrapOn

from ..categories.catalogue import LOCALES
from ..categories.skeleton import FACTS, WRITTEN, instances
from .text import MM, Rules, run_for

INK = colors.black
FAMILIES = {'serif': 'CVSerif', 'sans': 'CVSans'}
# What a value is when it only stands in for one: underscores, dots and dashes.
STAND_IN = re.compile(r'[\s_.\-–—…]*')
MONTHS_EN = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
             'November', 'December')
# The `when` predicate's kinds that read a field, a part, the questions, the cues or the quoted pages.
WHEN = re.compile(r'(?P<kind>fact|nofact|blank|part|nopart|questions|cue|nocue|pages_from):(?P<name>[a-z0-9_]+)'
                  r'(?:=(?P<value>[a-z0-9_]+))?')


def today():
    """The calendar day in Tashkent, where a clock field's year or date is read."""
    from zoneinfo import ZoneInfo
    return datetime.datetime.now(ZoneInfo('Asia/Tashkent')).date()


def clock_value(kind, day, locale):
    """A clock field's value: the year, or the date as the paper's language writes it."""
    if kind == 'year':
        return str(day.year)
    if locale == 'en':
        return f'{day.day} {MONTHS_EN[day.month - 1]} {day.year}'
    return day.strftime('%d.%m.%Y')


def styles(face, size, leading, align='left'):
    """The ten paragraph styles of one ladder step: body, small, italic, bold, caps, h1-h3, cell, caption.

    Pure black, no space around paragraphs (blocks set their own gaps), and no
    widow: a paragraph's last line never stands alone at the top of a page.
    `caps` is the bold face; a block upper-cases its own text.
    """
    family = FAMILIES.get(face, FAMILIES['serif'])
    bold, italic = f'{family}-Bold', f'{family}-Italic'
    body = ParagraphStyle('body', fontName=family, fontSize=size, leading=leading, textColor=INK,
                          alignment=TA_JUSTIFY if align == 'justify' else TA_LEFT, spaceBefore=0, spaceAfter=0,
                          allowWidows=0)
    small = round(size * 0.85 * 2) / 2

    def made(name, **changes):
        return ParagraphStyle(name, parent=body, **changes)
    return {
        'body': body,
        'small': made('small', fontSize=small, leading=round(leading * 0.85, 1)),
        'italic': made('italic', fontName=italic),
        'bold': made('bold', fontName=bold),
        'caps': made('caps', fontName=bold),
        'h1': made('h1', fontName=bold, fontSize=round(size * 1.3, 1), leading=round(leading * 1.25, 1),
                   alignment=TA_LEFT, keepWithNext=1),
        'h2': made('h2', fontName=bold, fontSize=round(size * 1.12, 1), leading=round(leading * 1.1, 1),
                   alignment=TA_LEFT, keepWithNext=1),
        'h3': made('h3', fontName=bold, alignment=TA_LEFT, keepWithNext=1),
        'cell': made('cell', fontSize=round(size * 0.9, 1), leading=round(leading * 0.82, 1), alignment=TA_LEFT),
        'caption': made('caption', fontName=italic, fontSize=max(6.5, round(size * 0.62, 1)),
                        leading=max(8, round(size * 0.62 * 1.25, 1)), alignment=TA_CENTER),
    }


@dataclass(frozen=True)
class Place:
    """One flow entry, resolved: one per group instance.

    `section` is the content section of `part` (of this instance), or None for a
    part the template draws from facts, labels or questions; `part` the
    catalogue part, None for a placement without one; `fields` the placement's
    fields (else its part's); `params` its parameters. `index` is its position
    in the template's flow, and `when`, `keep` and `page_break_before` are as
    the flow declares them.
    """

    block: str
    section: dict | None
    part: dict | None
    fields: tuple
    params: dict
    instance: int = 1
    index: int = 0
    group: str | None = None
    when: str | None = None
    keep: str | None = None
    page_break_before: bool = False
    raw: dict = attribute(default_factory=dict, repr=False, compare=False)


class Anchor(Flowable):
    """A point in the story the engine notes the page of: a heading's place in the contents."""

    _ZEROSIZE = 1

    def __init__(self, key):
        super().__init__()
        self.key = key
        self.keepWithNext = 1

    def wrap(self, width, height):
        return 0, 0

    def draw(self):
        pass


class Lazy(Flowable):
    """Flowables made when they are first laid out, after every block has run: a contents built from the marks.

    `make()` returns the flowables; they are made once per build. When they
    fit where they are, the Lazy reports their real height and draws them
    itself, so a heading kept with it (keep-with-next) is measured truly and
    stays on its page. When they do not, the frame splits it: the first
    flowable is cut to the room left (ReportLab lays the first of a split out
    unsplit) and the rest flows on, or everything moves to the next page.
    Drawn this way, an Anchor or a Mark inside is not seen by the engine: a
    contents holds neither. Any flowable works, small Paragraphs or a Table.
    """

    def __init__(self, make):
        super().__init__()
        self.make, self.made, self.fits = make, None, False

    def _content(self):
        if self.made is None:
            self.made = list(self.make() or [])
        return self.made

    def wrap(self, width, height):
        _, need = _listWrapOn(self._content(), width, self.canv)
        self.width, self.height, self.fits = width, need, need <= height + 1e-6
        # Too tall for the room: a height no frame holds makes the frame split it.
        return (width, need) if self.fits else (width, 0xffffff)

    def split(self, width, height):
        content = self._content()
        if not content:
            return []
        first = content[0]
        _, need = first.wrapOn(self.canv, width, height)
        if need <= height + 1e-6:
            return list(content)
        parts = first.split(width, height) if height > 0 else []
        if len(parts) > 1:
            _, need = parts[0].wrapOn(self.canv, width, height)
            if need <= height + 1e-6:
                return [*parts, *content[1:]]
        return []

    def drawOn(self, canvas, x, y, _sW=0):
        _Container.drawOn(self, canvas, x, y, _sW, content=self._content(), aW=self.width)

    def draw(self):
        pass


class Ctx:
    """One build of one paper at one ladder step. See the module's docstring for what a block may ask."""

    def __init__(self, *, content, entry, template, locale, step, pages, width, frame_height, cues=frozenset(),
                 day=None, style=None, known_pages=None):
        self.content, self.entry, self.template = content, entry, template
        self.locale = locale if locale in LOCALES else 'en'
        self.step, self.pages, self.cues = step, pages, frozenset(cues)
        self.width, self.frame_height = width, frame_height
        self.style = style or {}
        self.day = day or today()
        kind = template['type']
        ladder = kind['ladder']
        self.size, self.leading = ladder[min(step, len(ladder) - 1)]
        self.face = FAMILIES.get(kind.get('face'), FAMILIES['serif'])
        self.styles = styles(kind.get('face'), self.size, self.leading, kind.get('align', 'left'))
        self.rules = Rules(self.face, self.locale)
        self.warnings = []
        # Headings marked for the contents in this build: [(level, text)], and their pages from the build before.
        self.marks, self.known_pages = [], dict(known_pages or {})
        self.wants_contents = False
        self._counters = [0, 0, 0]
        self._facts = self._read_facts()
        self._sections = {str(section.get('id')): section for section in content.get('sections') or []
                          if isinstance(section, dict)}

    # -- facts

    def _read_facts(self):
        found = {}
        for section in self.content.get('sections') or []:
            if isinstance(section, dict) and section.get('id') == FACTS:
                for item in section.get('items') or []:
                    if isinstance(item, dict) and isinstance(item.get('label'), str):
                        value = item.get('text') if item.get('text') not in (None, '') else item.get('value')
                        found.setdefault(item['label'], '' if value is None else str(value).strip())
        return found

    def fact(self, field_id):
        """The verified value of a field, else its clock value when it has a clock, else None."""
        value = self._facts.get(field_id)
        if value and not STAND_IN.fullmatch(value):
            return value
        field = self.entry.field(field_id)
        if field and field.get('clock') and not value:
            return clock_value(field['clock'], self.day, self.locale)
        return None

    def given(self, field_id):
        """Whether a field holds a verified value of its own, not its clock's and not a stand-in."""
        value = self._facts.get(field_id)
        return bool(value) and not STAND_IN.fullmatch(value)

    def blank(self, field_id):
        """Whether a blank is drawn for a field: the model asked for one, or the field draws one when missing."""
        if self.fact(field_id) is not None:
            return False
        value = self._facts.get(field_id)
        if value is not None and STAND_IN.fullmatch(value) and '_' in value:
            return True
        field = self.entry.field(field_id)
        return bool(field) and field.get('missing') in ('blank', 'ask')

    def blank_run(self, field_id):
        """The underscores a missing field draws inline, as wide as its kind needs."""
        field = self.entry.field(field_id) or {}
        return run_for(field.get('kind'))

    def field_label(self, field_id):
        """A field's catalogue label in the paper's language ('' for an unknown field)."""
        field = self.entry.field(field_id)
        return field['label'].get(self.locale) or field['label']['en'] if field else ''

    # -- words

    def label(self, key, **slots):
        """A template label in the paper's language, its {field} slots filled with facts or drawn as blanks.

        A slot named in `slots` takes that value; otherwise the field's verified
        (or clock) value; otherwise an inline blank as wide as the field's kind.
        A key the template does not hold is '' and is warned, never raised.
        """
        labels = self.template.get('labels') or {}
        if key not in labels:
            self.warn(f'label_missing:{key}')
            return ''
        text = labels[key].get(self.locale) or labels[key].get('en', '')

        def fill(found):
            name = found.group(1)
            if name in slots and slots[name] not in (None, ''):
                return str(slots[name])
            value = self.fact(name)
            return value if value is not None else self.blank_run(name)
        return re.sub(r'\{(\w+)\}', fill, text)

    def text(self, value, style='body', room=None):
        """`value` with text_rules applied, as Paragraph markup in `style`; blanks no wider than `room` points."""
        chosen = self.styles[style] if isinstance(style, str) else style
        return self.rules.markup(value, font=chosen.fontName, size=chosen.fontSize, room=room or self.width)

    def plain(self, value):
        """`value` with text_rules applied, unescaped: for measuring, or for a canvas string."""
        return self.rules.plain(value)

    # -- the paper's parts

    def section(self, part_id, instance=1):
        """The content section of a part's instance, or None."""
        return self._sections.get(part_id if instance == 1 else f'{part_id}_{instance}')

    def heading(self, part, section=None):
        """A part's heading: its fixed heading in the paper's language, else the section's own ('' for none)."""
        if not part or part.get('heading_mode') == 'none':
            return ''
        if part.get('heading_mode') == 'fixed' and part.get('heading'):
            return part['heading'].get(self.locale) or part['heading']['en']
        return str((section or {}).get('heading') or '').strip()

    def columns(self, part):
        """A table part's header cells in the paper's language: the catalogue's, never the draft's."""
        return [column.get(self.locale) or column['en'] for column in (part or {}).get('columns') or ()]

    def number(self, level):
        """The next heading number at `level` (1-3), as "2" or "2.1" or "2.1.3"; deeper counters restart."""
        level = max(1, min(3, int(level)))
        self._counters[level - 1] += 1
        for deeper in range(level, 3):
            self._counters[deeper] = 0
        return '.'.join(str(max(1, count)) for count in self._counters[:level])

    def count(self, level):
        """The current counter at `level`, for a heading numbered another way (roman, a chapter word)."""
        return self._counters[max(1, min(3, int(level))) - 1]

    def questions(self, kind='all'):
        """The test's questions: choice (closed, not on a passage), open, passage, or all, in their order."""
        found = [question for question in self.content.get('questions') or [] if isinstance(question, dict)]
        closed = [question for question in found if question.get('options')]
        if kind == 'choice':
            return [question for question in closed if question.get('topic') != 'passage']
        if kind == 'passage':
            return [question for question in closed if question.get('topic') == 'passage']
        if kind == 'open':
            return [question for question in found if not question.get('options')]
        return found

    def warn(self, code):
        if code not in self.warnings:
            self.warnings.append(code)

    # -- contents

    def mark(self, level, text):
        """An anchor to put just before a heading: the heading joins the contents with the page it lands on."""
        self.marks.append((int(level), str(text)))
        return Anchor(len(self.marks) - 1)

    def contents(self):
        """[(level, text, page)] of every heading marked so far; page is None until a build has placed it.

        Read it inside `Lazy`, when the story is complete. Asking for it makes
        the engine build once more at the chosen step with the pages it found,
        so the numbers printed are the pages of the paper delivered.
        """
        self.wants_contents = True
        return [(level, text, self.known_pages.get(key)) for key, (level, text) in enumerate(self.marks)]

    @property
    def mm(self):
        return MM


# ---------------------------------------------------------------- the flow


def _group_of(entry, placement):
    part = entry.part(placement['part']) if placement.get('part') else None
    return part.get('group') if part else None


def _instances(ctx, run, group):
    """The instance numbers of a group run: those the content holds for any written part of it."""
    written = [ctx.entry.part(item['part']) for item in run if item.get('part')]
    written = [part for part in written if part and part['kind'] in WRITTEN]
    if not written:
        return list(range(1, instances(ctx.entry, group, ctx.pages or ctx.entry.length['default']) + 1))
    found = set()
    for part in written:
        for section_id in ctx._sections:
            if section_id == part['id']:
                found.add(1)
            else:
                match = re.fullmatch(re.escape(part['id']) + r'_(\d{1,3})', section_id)
                if match:
                    found.add(int(match.group(1)))
    return sorted(found)


def localised(value, locale):
    """A placement's parameters with every per-language map resolved to the paper's language.

    A map whose keys are all languages ({"en": "to"}, {"uz": {...}}) is a
    word or setting only those languages have: it becomes its value in
    `locale`, and is left out where `locale` has none, so an English-only
    "To:" prints nothing in an Uzbek note rather than falling back to English.
    """
    if isinstance(value, dict) and value and set(value) <= set(LOCALES):
        return localised(value[locale], locale) if locale in value else None
    if isinstance(value, dict):
        made = {key: localised(item, locale) for key, item in value.items()}
        return {key: item for key, item in made.items() if item is not None}
    if isinstance(value, list):
        return [item for item in (localised(item, locale) for item in value) if item is not None]
    return value


def _place(ctx, placement, index, instance, group):
    part = ctx.entry.part(placement['part']) if placement.get('part') else None
    section = ctx.section(part['id'], instance) if part and part['kind'] in WRITTEN else None
    fields = tuple(placement.get('fields') or (part or {}).get('fields') or ())
    # A params object made only of language keys resolves to None in a language it does not name: still a dict.
    params = localised(dict(placement.get('params') or {}), ctx.locale) or {}
    return Place(placement['block'], section, part, fields, params, instance, index, group, placement.get('when'),
                 placement.get('keep'), bool(placement.get('page_break_before')), placement)


def places(ctx):
    """The template's flow as Places, in drawing order: a group's consecutive placements once per instance."""
    flow = ctx.template['flow']
    made, position = [], 0
    while position < len(flow):
        group = _group_of(ctx.entry, flow[position])
        if group is None:
            made.append(_place(ctx, flow[position], position, 1, None))
            position += 1
            continue
        run = []
        while position < len(flow) and _group_of(ctx.entry, flow[position]) == group:
            run.append((position, flow[position]))
            position += 1
        for instance in _instances(ctx, [item for _, item in run], group):
            made += [_place(ctx, item, index, instance, group) for index, item in run]
    return made


def _has_text(section):
    if not section:
        return False
    if str(section.get('body') or '').strip():
        return True
    return any(isinstance(item, dict) and any(str(item.get(key) or '').strip() for key in ('label', 'text', 'value'))
               for item in section.get('items') or [])


def any_part_holds(ctx, params):
    """Whether a placement's `any_part` lets it draw: no such list, or one of its parts has text.

    A chapter word over several optional parts (which a single `when` cannot
    say) is drawn only then; the heading block and the checker both ask here,
    so what is drawn and what is looked for never part ways.
    """
    any_part = (params or {}).get('any_part')
    return not isinstance(any_part, list) or any(_has_text(ctx.section(part_id)) for part_id in any_part
                                                 if isinstance(part_id, str))


def holds(when, ctx, place=None):
    """Whether a placement's `when` holds (architecture 6.3); a placement without one always does.

    `part:id` reads the instance the place is drawn for when the part repeats
    in the same group, else the part's first section. An unreadable predicate
    does not hold: the catalogue check refuses one, so it can only be a
    template this worker does not know.
    """
    if not when:
        return True
    found = WHEN.fullmatch(when)
    if not found:
        ctx.warn('when_unknown')
        return False
    kind, name, value = found.group('kind'), found.group('name'), found.group('value')
    if kind in ('fact', 'nofact'):
        fact = ctx.fact(name)
        present = fact is not None and (value is None or fact.strip().casefold() == value)
        return present if kind == 'fact' else not present
    if kind == 'blank':
        return ctx.blank(name)
    if kind in ('part', 'nopart'):
        part = ctx.entry.part(name)
        instance = place.instance if place is not None and part and part.get('group') == place.group else 1
        present = _has_text(ctx.section(name, instance))
        return present if kind == 'part' else not present
    if kind == 'questions':
        choice, opened = bool(ctx.questions('choice')), bool(ctx.questions('open'))
        return {'choice': choice, 'open': opened, 'both': choice and opened,
                'passage': bool(ctx.questions('passage'))}.get(name, False)
    if kind in ('cue', 'nocue'):
        return (name in ctx.cues) == (kind == 'cue')
    if kind == 'pages_from':
        return (ctx.pages or 0) >= int(name)
    return False
