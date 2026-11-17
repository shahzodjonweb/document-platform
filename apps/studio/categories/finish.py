"""What code does to a category document after the model and before it is drawn (architecture 3.6, 4 and 7).

The model was told the category's slots, its fixed words and never to invent;
this is where code holds it to that, because a prompt is a request and not a
guarantee. For a deck (`apply`, after title_lines.apply in the job):

- a new deck is dressed again (skeleton.dress): each fixed slot gets its
  heading in the document's language and a layout its slot allows, whatever
  the model wrote; a change is left as the customer may have rearranged it;
- a slot of source `customer` (results, conclusions, methods ...) is grounded
  (facts.ground): a number, a run of capitalised words, a quotation or a legal
  reference the customer did not give becomes ____ or goes;
- a slot of source `draft` (relevance, aim and tasks, object and subject) is
  guarded (facts.guard): it may be drafted from general knowledge of the topic,
  but never quotes or cites a law the customer did not give; one that also
  states the customer's own facts (a council's problems, proposals and
  resolution, a parents' meeting's requests) has its numbers, and where its
  slot says so its names, grounded too (the slot's `checks`);
- the cover keeps only lines that are the customer's: a title-page line whose
  names or numbers they did not give ("Toshkent — 2026" with no year said, a
  "F.I.Sh.: ____" stand-in) is taken off, as is a model author line on the
  closing slide; the lines they dictated, which title_lines placed, always stay;
- a sources slot keeps only the sources the customer named or attached, never
  a file name (facts.verify_items), and is an honest numbered form when none is
  left;
- everything ends tidied and in the document's alphabet (quality.tidy and
  scripts.enforce), so the read-back of the file cannot fail on what code put in.

Nothing here adds a fact: it only removes text, writes catalogue words and
writes ____ (and, for a paper, today's date where a clock field asks for it).
What it removed is said as codes (`ground:number`, `ground:name`,
`ground:quote`, `ground:law`, `cover:line`, `source:dropped`, a paper's
`fact:<field>`), logged without a value, and any of them raises the job
warning `facts_blanked`, on which the bot adds the entry's `blanks` notice.
For a deck `apply` never raises: a slide it cannot finish becomes an honest
form rather than costing the customer the deck or shipping what was not
checked. Only when the deck itself cannot be read (its slots, the customer's
words) is it returned as the model wrote it, logged, as title_lines.apply
does: that is a bug to fix, not a customer to fail. A paper differs there
(`_paper`).

`pins(data, content)` gives the first render of a category deck the calm
variants its slots name, and `exempt(data)` the slides quality.check must not
send back for repeating each other, which a deck of honest forms does by
design.

A category paper (`apply` before its template draws it, architecture 3.6, 4
and 5) is finished the same way, by part rather than by slot:

- the `facts` section keeps only the values the customer gave, each held to
  its field's kind (facts.supported; a signer's initials to the verified full
  name, facts.derived; in a fact-led paper a text fact, a letter's request or
  reason, also grounded as its parts are); an unknown field, a choice outside its list or a ____
  for a field that is not `if_needed` is simply not kept, since the template
  draws its own blank, and a clock field the customer left out (the year on a
  title page, the date a letter is made) gets today's Tashkent date from code,
  as does one the model filled with a date the customer never gave;
- a section of a part the model does not write (an ariza's addressee or
  signature, a test's head: drawn from facts and template labels) goes whole,
  counted as `finish:unwritten`, which raises no warning since nothing the
  document draws is blanked;
- a grounded part (a letter's, an official or business paper's written
  parts) is grounded, its people's names read strictly (`ground_paper`), and
  every other part guarded, the test's questions too;
  a sources part keeps only verified items, never a file name, and is left
  empty when none verifies, which the reference list draws as a ruled form;
- every part gets its layout and its fixed heading in the document's
  language, the title is the category's name where the entry says so, a
  table's computed cells are emptied for derive.apply to fill from verified
  numbers (a cell whose inputs are not all given keeps the customer's own
  figure, grounded), and the instances of a model-sized group the model left empty go;
- `only` re-finishes just the sections a top-up wrote, before the second draw.

`plain(data, content)` is the emergency fallback's content (6.7): what today's
renderer can draw when a template build fails. A paper's `exempt` holds the
parts that are empty, repeating or not prose by design.
"""
import copy
import logging
import re
from collections import Counter

from . import facts, numbers, skeleton
from .catalogue import LOCALES, SOURCES_CUE, of

log = logging.getLogger(__name__)

# The job warning that any blank or removal raises; the bot answers it with the entry's `blanks` notice.
FACTS_BLANKED = 'facts_blanked'
# A paper section of a part drawn from facts and labels, taken out whole: logged, but no blank the customer sees.
UNWRITTEN = 'finish:unwritten'
BLANK = facts.BLANK
# An honest form: as many ruled lines as a short slide holds, numbered on a sources slide.
FORM_LINES = 3
# A label before its colon on a title-page line ("Bajardi:", "Ilmiy rahbar:"): a few words and no digit.
LABELLED = re.compile(r"^(?P<label>[^:\d\n]{1,40}):[ \t]*(?P<value>.*)$")
# What numbers or marks an item of a list rather than saying anything: "1.", "2)", "-", "•".
ENUMERATOR = re.compile(r"^[ \t]*(?:\d{1,3}[.)]|[-–—•*·])[ \t]*")
# A value that only stands in for one: nothing but rules and dots, or "F.I.Sh.", "[Ismingiz]", "ФИО".
RULED = re.compile(r"[\s_.\-–—…*]*")


def _entry(data):
    """The draft's category, or None; never the error of an unknown id, which the job raised before the provider."""
    try:
        return of(data)
    except Exception:
        return None


def _locale(data):
    return data.get('output_locale') if data.get('output_locale') in LOCALES else 'en'


def _uses(entry, data):
    """{section id: Use} of a deck at the length its draft was seeded and quoted with."""
    return {use.section_id: use for use in
            skeleton.parts(entry, len(data['content']['sections']), skeleton.cues_of(data))}


def _sources_slot(part):
    return part.get('when') == f'cue:{SOURCES_CUE}'


def _translated(data):
    """Whether the document is written in another language than the message, so organisations and places are translated.

    Only a message long enough to tell counts (language.written_in); one that
    cannot be told is treated as the document's language, which checks names
    more strictly: a false blank at worst, never an invention let through.
    """
    from ..language import written_in
    revision = data.get('revision') or {}
    said = written_in(revision.get('original_prompt') or data.get('prompt') or '')
    return bool(said) and said != _locale(data)


def _key(line):
    return ' '.join(facts.FOLDED_WORD.findall(facts.fold(line)))


def _dictated(data):
    """The folded title-page lines that are the customer's own: dictated now, kept with their account, or placed."""
    from .. import title_lines
    revision = data.get('revision') or {}
    options = data.get('options') if isinstance(data.get('options'), dict) else {}
    lines = list(title_lines.dictated(revision.get('request') if revision else data.get('prompt')))
    lines += [line for line in options.get('title_lines') or [] if isinstance(line, str)]
    kept = data.get('_cover_lines') if isinstance(data.get('_cover_lines'), dict) else {}
    lines += [line for line in kept.get('lines') or [] if isinstance(line, str)]
    return {_key(line) for line in lines if _key(line)}


def _stand_in(value):
    from ..title_lines import PLACEHOLDER
    value = value.strip(' \t:-–—')
    return not value or RULED.fullmatch(value) is not None or PLACEHOLDER.fullmatch(value) is not None


def _split(line):
    """(label, value) of a title-page line; the label is '' when it has none."""
    found = LABELLED.match(line.strip())
    return (found.group('label'), found.group('value')) if found else ('', line)


def _line_known(line, trusted, translated, own):
    """Whether a title-page line says only what the customer said: its label's names and its value's names and numbers.

    The first word of a label is the label's own ("Bajardi", "Ilmiy"); its
    other capitalised words and every word of its value are held as a `line`
    fact. In a deck written in another language than the message a `line`
    leaves its names to the translation, so there a labelled line is held as a
    `person`: a cover's names are people ("Bajardi: …", "Ilmiy rahbar: …"),
    and an invented one must never ship. A translated school's or company's
    line may then go: a false blank, never an invention.

    A translated line with no label has its names read as guard's 'names'
    check reads them (facts.people_known): its opening word is capitalised by
    grammar ("Grocery shop", "Term paper") and is free unless it is shaped as
    a surname, stands before initials or before another word that is not the
    customer's. Held as a person's, every such line went and the customer was
    told of a blank where nothing was invented. A line of one word ("Botir",
    "Педсовет") is still held as a person's: nothing beside it says it is not
    a name.
    """
    if _key(line) in own:
        return True
    label, value = _split(line)
    if translated and not label and len([word for word in facts.WORD.findall(value) if len(word) >= 2]) > 1:
        return facts.supported(value, 'line', trusted, translated=True) \
            and facts.people_known(value, trusted, translated=True)
    kind = 'person' if translated else 'line'
    if not facts.supported(value, kind, trusted, translated=translated):
        return False
    return not label or facts.supported(' '.join(label.split()[1:]), kind, trusted, translated=translated)


def _title_page(text, trusted, translated, own, codes, *, first_free):
    """A cover's or a closing slide's lines, keeping only the customer's; the first kept as a subtitle when `first_free`.

    A cover of one line has a subtitle, not a title page (slide_layouts.title_lines):
    it is guarded, and goes when it holds a number the customer did not give
    ("Toshkent — 2026") or a name guard's 'names' check would take
    (facts.people_known): an author with no label ("Bajardi — Xolmirzayev
    Botir", "Prepared by Botir Xolmirzayev", a bare "Xolmirzayev Botir") would
    otherwise ship, since a guarded line checks only numbers. Its opening word
    stays free unless it is shaped as a surname or stands beside initials or
    an invented word, so a subtitle of general knowledge ("Toshkent davlat
    iqtisodiyot universiteti") is kept. The same
    holds for a closing slide's first line. A line that only stands in for one ("____",
    "F.I.Sh.: ____") is never kept. On a closing slide the first line is its own
    words ("Savollaringiz bormi?") and the lines after it are an author line
    copied from the cover, held as the cover's are.

    A first line with a label ("Bajardi: …", "Prepared by: …") is never a
    subtitle, alone or on a closing slide: it says who made the work, and a
    guarded line checks only numbers, so a model-written author would ship.
    It is held as every other title-page line is, as a person's in a translated
    deck.
    """
    lines = [line for line in str(text or '').split('\n') if line.strip()]
    if not lines:
        return text
    kept = []
    for number, line in enumerate(lines):
        if _key(line) not in own and _stand_in(_split(line)[1]):
            # A ruled line or a stand-in for a name ("F.I.Sh.: ____", "Bajardi: [Ismingiz]") says nothing of
            # anyone's: it goes, and as no fact was taken out the customer is not told of a blank to fill.
            continue
        if number == 0 and (first_free or len(lines) == 1) and not _split(line)[0]:
            line, found = facts.guard(line, trusted, translated=translated)
            codes.extend(found)
            if _key(line) in own or (all(numbers.known(value, trusted.values) for value in numbers.found(line))
                                     and facts.people_known(line, trusted, translated=translated)):
                if line.strip():
                    kept.append(line)
                continue
        elif _line_known(line, trusted, translated, own):
            kept.append(line)
            continue
        codes.append('cover:line')
    return '\n'.join(kept)


def _texts(section, check, heading, notes=True):
    """Run `check(text) -> text` over every field of a slide a reader sees; its heading only when `heading`."""
    keys = (('heading',) if heading else ()) + ('body',) + (('notes',) if notes else ())
    for key in keys:
        if isinstance(section.get(key), str):
            section[key] = check(section[key])
    for item in section.get('items') or []:
        if isinstance(item, dict):
            for key in ('label', 'text', 'value'):
                if isinstance(item.get(key), str):
                    item[key] = check(item[key])
    if isinstance(section.get('columns'), list):
        section['columns'] = [check(column) if isinstance(column, str) else column for column in section['columns']]


def _rows(section):
    """How many rows a slide shows: its items with any words, else the lines of its body."""
    items = [item for item in section.get('items') or [] if isinstance(item, dict)
             and any(isinstance(item.get(key), str) and item[key].strip() for key in ('label', 'text', 'value'))]
    if items:
        return len(items)
    return len([line for line in str(section.get('body') or '').split('\n') if line.strip()])


def _form(section, *, numbered=False):
    """The slide as an honest form: its heading kept, ruled lines to fill in, nothing the customer did not give."""
    section.update(body='\n'.join(f'{number}. {BLANK}' if numbered else BLANK
                                  for number in range(1, FORM_LINES + 1)), items=[])
    if isinstance(section.get('columns'), list):
        section['columns'] = []


def _sources(section, trusted, translated, names, codes):
    """A sources slide's lines and items, only those the customer named or a file's own text gives; else a form."""
    lines = [line for line in str(section.get('body') or '').split('\n') if line.strip()]
    kept = []
    for line in lines:
        verified, found = facts.verify_items([ENUMERATOR.sub('', line)], trusted, file_names=names,
                                             translated=translated)
        codes.extend(found)
        if verified:
            kept.append(line)
    items, found = facts.verify_items([item for item in section.get('items') or [] if isinstance(item, dict)],
                                      trusted, file_names=names, translated=translated)
    codes.extend(found)
    section.update(body='\n'.join(kept), items=items)
    if isinstance(section.get('notes'), str):
        section['notes'], found = facts.ground(section['notes'], trusted, translated=translated)
        codes.extend(found)
    if not kept and not items:
        _form(section, numbered=True)


def _role(index, section, use, revision, locale):
    """How a slide is finished: 'cover', 'template', 'sources', 'draft' or 'customer'.

    A new deck's slide is its slot's. After a change the customer may have
    moved, added or removed slides, so a slot is believed only on evidence: a
    draft slot whose fixed heading the slide still carries, a template slot
    still drawn as a closing slide. Every other slide of a changed deck is
    grounded, the strict reading: at worst a false blank, never an invention.
    """
    if index == 0:
        return 'cover'
    part = use.part if use is not None else None
    if part is None:
        return 'customer'
    if not revision:
        if _sources_slot(part):
            return 'sources'
        return {'template': 'template', 'draft': 'draft'}.get(part.get('source'), 'customer')
    if part.get('source') == 'draft' and part.get('heading_mode') == 'fixed' \
            and section.get('heading') == (part.get('heading') or {}).get(locale):
        return 'draft'
    if part.get('source') == 'template' and section.get('layout') == 'closing' and 'closing' in part['layouts']:
        return 'template'
    return 'customer'


def _file_names(data):
    """The names of the draft's attached files, which a sources slide must never show as a source."""
    ids = [str(item) for item in data.get('source_ids') or []]
    if not ids:
        return []
    try:
        from apps.core.models import FileAsset
        return list(FileAsset.objects.filter(pk__in=ids).values_list('name', flat=True))
    except Exception:
        log.exception('Category finish: the attached files could not be named')
        return []


def _finish_slide(index, section, use, *, revision, locale, trusted, translated, own, names, codes):
    role = _role(index, section, use, revision, locale)
    fixed = use is not None and use.part.get('heading_mode') == 'fixed' and not revision

    def grounded(text):
        text, found = facts.ground(text, trusted, translated=translated)
        codes.extend(found)
        return text

    def guarded(text, checks=(), held=trusted):
        text, found = facts.guard(text, held, translated=translated, checks=checks)
        codes.extend(found)
        return text
    if role == 'cover':
        for key in ('heading', 'notes'):
            if isinstance(section.get(key), str):
                section[key] = guarded(section[key])
        section['body'] = _title_page(section.get('body'), trusted, translated, own, codes, first_free=False)
    elif role == 'template':
        if isinstance(section.get('notes'), str):
            section['notes'] = guarded(section['notes'])
        section['body'] = _title_page(section.get('body'), trusted, translated, own, codes, first_free=True)
    elif role == 'sources':
        _sources(section, trusted, translated, names, codes)
    elif role == 'draft':
        # A draft slot that states the customer's own facts names the checks it also takes (catalogue `checks`).
        checks = tuple(use.part.get('checks') or ())
        _texts(section, lambda text: guarded(text, checks), heading=not fixed, notes=False)
        if isinstance(section.get('notes'), str):
            # The notes may say how many rows the slide has ("Bugun 5 ta masala", as the agenda's write text asks):
            # that count is the slide's own, not a figure of the school's, so it alone is let through, and only in
            # the notes. Any other number there is held as the slide's are.
            counted = facts.counting(trusted, _rows(section)) if 'numbers' in checks else trusted
            section['notes'] = guarded(section['notes'], checks, counted)
    else:
        _texts(section, grounded, heading=not fixed)


def apply(data, content, *, only=None, file_names=None, codes=None):
    """(content, warnings): a category document's answer held to the customer's words; anything else as it is.

    `file_names` are the attached files' names (looked up from the draft's
    `source_ids` when not given); `codes`, a list, receives what was blanked
    or removed, for the caller's log. `content` is never changed in place.
    `only` (section ids) is for a paper: the sections a top-up wrote, which
    alone are finished again. A deck never raises (see the module's
    docstring); a paper raises only when the draft itself cannot be read
    (`_paper`).
    """
    entry = _entry(data)
    if entry is None:
        return content, []
    if entry.service == 'pdf':
        return _paper(entry, data, content, only=only, file_names=file_names, codes=codes)
    found = []
    try:
        content = copy.deepcopy(content)
        revision = data.get('revision') or {}
        selected = set(revision.get('selected_section_ids') or ())
        locale = _locale(data)
        if not revision:
            skeleton.dress(data, content['sections'])
        uses = _uses(entry, data)
        trusted = facts.trusted(data)
        translated = _translated(data)
        own = _dictated(data)
        names = _file_names(data) if file_names is None else list(file_names)
        if not selected and isinstance(content.get('title'), str):
            content['title'], title_codes = facts.guard(content['title'], trusted, translated=translated)
            found.extend(title_codes)
        for index, section in enumerate(content['sections']):
            if selected and section.get('id') not in selected:
                continue
            try:
                _finish_slide(index, section, uses.get(section.get('id')), revision=bool(revision), locale=locale,
                              trusted=trusted, translated=translated, own=own, names=names, codes=found)
            except Exception:
                log.exception('Category %s: slide %s could not be finished and is left a form', entry.id, index + 1)
                _form(section)
                found.append('finish:form')
        from .. import quality
        content, _ = quality.tidy(content, selected or None)
        content, _ = quality.enforce(content, locale, selected or None)
    except Exception:
        log.exception('Category %s: the deck could not be finished', entry.id)
        return content, []
    found = list(dict.fromkeys(found))
    if codes is not None:
        codes.extend(found)
    if found:
        log.info('Category %s: finish took out %s', entry.id, ', '.join(found))
    return content, [FACTS_BLANKED] if found else []


def pins(data, content):
    """The variant pins for the first render of a new category deck: {'variants': {section id: 'kind.name'}}, or {}.

    Each slide takes the first of its slot's `pins` drawn in the layout the
    slide will resolve to (slides.prepare_slides, without photos), else its
    entry's `look.variants` for that layout; the instances of a repeating slot
    take them in turn. A pin is only a first try: render_pptx tries it on a
    scratch slide and lists one that does not hold in metadata['repinned'].
    A change keeps the deck's own pins (execution._deck_pins), so it gets none.
    """
    entry = _entry(data)
    if entry is None or entry.service != 'slides' or data.get('revision'):
        return {}
    try:
        from .. import variants
        from ..slides import prepare_slides
        uses = _uses(entry, data)
        prepared, _ = prepare_slides(content, _locale(data), {})
        offered = entry.look.get('variants') or {}
        chosen = {}
        for kind, _, section in prepared:
            use = uses.get(section.get('id'))
            if use is None or kind not in variants.KINDS:
                continue
            names = [pin for pin in use.part.get('pins') or () if pin.split('.', 1)[0] == kind]
            names = [pin for pin in names or (f'{kind}.{name}' for name in offered.get(kind, ())) if _registered(pin)]
            if names:
                chosen[section['id']] = names[(use.instance - 1) % len(names)]
        return {'variants': chosen} if chosen else {}
    except Exception:
        log.exception('Category %s: no pins for the first render', entry.id)
        return {}


def _registered(variant_id):
    from .. import variants
    try:
        variants.get(variant_id)
    except KeyError:
        return False
    return True


def exempt(data):
    """The section ids quality.check must not send back for repeating another, being empty or its language.

    For a deck: every slide of a slot that takes several slides and either
    has a fixed heading (the same heading on each, by design) or is of source
    `customer` (with nothing given, each is the same honest form, and a repair
    asked to make them differ could only invent). For a paper, `_paper_exempt`.
    """
    entry = _entry(data)
    if entry is None:
        return set()
    if entry.service == 'pdf':
        return _paper_exempt(entry, data)
    try:
        uses = list(_uses(entry, data).values())
        taken = Counter(use.part['id'] for use in uses)
        return {use.section_id for use in uses if taken[use.part['id']] > 1
                and (use.part.get('heading_mode') == 'fixed' or use.part.get('source') == 'customer')}
    except Exception:
        log.exception('Category %s: no quality exemptions', entry.id)
        return set()


# ---------------------------------------------------------------- papers


FACTS = skeleton.FACTS
# A value that is only a blank: rules, dots and dashes ("____", "…", "—"). The model returns ____ for an `if_needed`
# field the paper needs; for any other field the template draws its own blank, so such a value is not kept.
EMPTY_VALUE = re.compile(r'[\s_.\-–—…]*')
# How a flag field's value may be written; anything else is not kept.
FLAGS = {'true': 'true', 'yes': 'true', '1': 'true', 'false': 'false', 'no': 'false', '0': 'false'}
# Month names as a date is written in each language after its day: '2026-yil 16-noyabr', '16 ноября 2026 г.',
# '16 November 2026' (the research specs' date patterns). Uzbek "sentabr" and "oktabr", never the Russian spellings.
MONTHS = {
    'uz': ('yanvar', 'fevral', 'mart', 'aprel', 'may', 'iyun', 'iyul', 'avgust', 'sentabr', 'oktabr', 'noyabr',
           'dekabr'),
    'ru': ('января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября',
           'декабря'),
    'en': ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
           'November', 'December'),
}
# The heading of the facts in the emergency fallback, the one fixed word of a paper not in the catalogue.
PLAIN_FACTS = {'uz': 'Ma’lumotlar', 'ru': 'Сведения', 'en': 'Details'}
# What joins a table row's cells in the emergency fallback, which draws a table as a list (6.7).
PLAIN_CELLS = ' — '
# A review-form label's trailing hint in brackets, which the fallback's line of the document leaves off.
HINT = re.compile(r'\s*\([^()]*\)\s*$')
CELL = ' | '
CELLS = re.compile(r'\s*\|\s*')
# An author line at the end of a title, in each language: a label and its colon, or "Prepared by".
AUTHOR_TAIL = re.compile(
    r"[\s.,;—–-]*\b(?:(?:tuzuvchi|tuzdi|muallif|tayyorladi|bajardi|o‘qituvchi|составитель|составила?|автор|"
    r"подготовила?|учитель|author|teacher)\s*:|(?:prepared|compiled|written|made)\s+by\b\s*:?)"
    r"(?P<value>[^:\n]*)$", re.IGNORECASE)


def today():
    """The calendar day in Tashkent, where every customer's papers are dated (the weekly limits' zone)."""
    from django.utils import timezone

    from apps.core.allowance import WEEK_ZONE
    return timezone.now().astimezone(WEEK_ZONE).date()


def clock_value(kind, locale, day=None):
    """A clock field's value written by code: the year ('2026') or the date in the document's language."""
    day = day or today()
    if kind == 'year':
        return str(day.year)
    month = MONTHS.get(locale, MONTHS['en'])[day.month - 1]
    if locale == 'uz':
        return f'{day.year}-yil {day.day}-{month}'
    if locale == 'ru':
        return f'{day.day} {month} {day.year} г.'
    return f'{day.day} {month} {day.year}'


def ground_paper(text, trusted, *, translated=False):
    """(text, codes): a paper's grounded part held to the customer's words, its people's names read strictly.

    facts.ground's checks (laws, quotations, e-mails and links, numbers, runs
    of capitalised words), with the names read as a slot that names people
    reads them (guard's 'names'): a letter or a form names its people just
    where ground leaves a name's first word free, after a colon ("Ma’sul:
    Karimov A."), before initials or beside another invented word, and there
    an invented name goes whole with its initials instead of leaving
    "Dekan ____ A.". A grammar word before an invented name may go with it: a
    false blank, never an invention.
    """
    return facts.guard(text, trusted, translated=translated, checks=('numbers', 'names'))


def _led(entry):
    """Whether a paper is fact-led: any part grounded (a letter, an official paper), so its people are facts."""
    return any(part.get('grounded') for part in entry.parts)


def _guarded_title(title, trusted, translated, codes):
    """A guarded paper's title, without a labelled author tail ("Tuzuvchi: …") whose name the customer never gave.

    A guarded title keeps general knowledge ("Amir Temur davri"), so it is not
    read for names; but a labelled author is a person, and a model-written one
    ("7-sinf testi. Tuzuvchi: Karimov A.") would ship on the template's title.
    The tail goes whole when its value is not the customer's person; the
    template draws authors from facts, so nothing the document needs is lost.
    """
    found = AUTHOR_TAIL.search(title)
    if found is None:
        return title
    value = found.group('value')
    if value.strip() and not _stand_in(value) and facts.supported(value, 'person', trusted, translated=translated):
        return title
    if not _stand_in(value):
        codes.append('ground:name')
    return title[:found.start()].rstrip(' \t.,;:—–-')


def _instance(section_id, part):
    """Which instance of its part a section is: `chapter` is 1, `chapter_3` is 3."""
    rest = str(section_id)[len(part['id']):]
    return int(rest[1:]) if re.fullmatch(r'_\d+', rest) else 1


def cells(item, count=None):
    """A table row's cells: the first in `label`, the last in `value`, those between in `text` joined by ' | '.

    With `count` (the part's columns) the row is held to that many cells: a
    middle cell that itself holds ' | ' merges into the last middle cell, and
    a short row is padded with empty cells, so a cell never moves column.
    """
    text = str(item.get('text') or '')
    # Split on the bar with any spaces around it: tidying may have taken the space off an empty first or last cell.
    middle = [cell.strip() for cell in CELLS.split(text)] if text.strip() else []
    first, last = str(item.get('label') or '').strip(), str(item.get('value') or '').strip()
    if count is None:
        return [first, *middle, last]
    if count <= 1:
        return [CELL.join(cell for cell in (first, *middle, last) if cell)]
    if count == 2:
        return [CELL.join(cell for cell in (first, *middle) if cell), last]
    wanted = count - 2
    if len(middle) > wanted:
        middle = middle[:wanted - 1] + [CELL.join(middle[wanted - 1:])]
    return [first, *middle, *[''] * (wanted - len(middle)), last]


def _row(values):
    """A row's cells as an item; empty middle cells at the end are left out, since `cells` pads them back."""
    middle = list(values[1:-1])
    while middle and not middle[-1]:
        middle.pop()
    return {'label': values[0], 'text': CELL.join(middle), 'value': values[-1] if len(values) > 1 else ''}


def _words(section):
    """Whether a section holds anything to read: a body or an item with words (a heading alone is no part)."""
    return bool(str(section.get('body') or '').strip()) or any(
        isinstance(item, dict) and any(str(item.get(key) or '').strip() for key in ('label', 'text', 'value'))
        for item in section.get('items') or [])


def _value(item):
    text = item.get('text') if str(item.get('text') or '').strip() else item.get('value')
    return str(text or '').strip()


def _cut(value, size):
    """`value` held to a field's max_chars, at a word's end: a cut only shortens, it never changes a word."""
    if not size or len(value) <= size:
        return value
    # Any whitespace ends a word: a list field's lines are joined with new lines, not spaces.
    head = value[:size + 1]
    return (head.rsplit(None, 1)[0] if re.search(r'\s', head) else value[:size]).rstrip(' ,;:\n')


def _fact(field, value, trusted, translated, verified, *, led=False):
    """(value to keep or None, whether it was taken out as not the customer's) for one field the model filled.

    A `text` fact is checked for numbers only, which leaves a guarded paper's
    topic its general knowledge. In a fact-led paper (`led`: any part grounded,
    a letter or an official paper) a text fact is the customer's request or
    reason, which the template and the fallback print as they are, so it is
    also held as a grounded part is (`ground_paper`): an invented dean, law or
    quotation takes the whole value out, since half a reason is no reason.
    """
    if EMPTY_VALUE.fullmatch(value):
        return (BLANK if field['missing'] == 'if_needed' else None), False
    kind = field['kind']
    if kind == 'choice':
        chosen = value.casefold().strip(' .')
        return (chosen if chosen in field.get('choices', ()) else None), False
    if kind == 'flag':
        return FLAGS.get(value.casefold().strip(' .')), False
    if field.get('derived_from'):
        # A signer's "D. R. Karimova" is held to the verified full name it is made from, whatever the prompt says.
        base = verified.get(field['derived_from'])
        if base and base != BLANK and facts.derived(value, base):
            return _cut(value, field.get('max_chars')), False
        return None, True
    if not facts.supported(value, kind, trusted, translated=translated):
        return None, True
    if led and kind == 'text' and ground_paper(value, trusted, translated=translated)[1]:
        return None, True
    return _cut(value, field.get('max_chars')), False


def _facts(entry, section, trusted, translated, locale, codes):
    """The facts section: one item per field the customer gave, verified by kind, and the clock fields' values.

    Items are written {label: field id, text: value} in the entry's field order.
    A list field's several items join with new lines; any other field keeps
    its first. A field whose value is not the customer's is counted as
    `fact:<field id>`; the template then draws its blank, as for a field the
    customer never gave. A clock field is the exception: a value the customer
    did not give is replaced by today's, silently, since nothing is left blank.
    The model writes today's year unasked, and a change re-finishes the value
    the first finish wrote, which the prompt does not hold either.
    """
    given = {}
    for item in section.get('items') or []:
        if not isinstance(item, dict):
            continue
        field = entry.field(str(item.get('label') or '').strip())
        value = _value(item)
        if field is None or field['kind'] == 'file' or not value:
            continue
        if field['id'] in given:
            if field['kind'] == 'list':
                given[field['id']] += '\n' + value
            continue
        given[field['id']] = value
    verified = {}
    led = _led(entry)
    fields = sorted(entry.fields, key=lambda field: bool(field.get('derived_from')))
    for field in fields:
        if field['id'] not in given:
            continue
        value, invented = _fact(field, given[field['id']], trusted, translated, verified, led=led)
        if invented and not field.get('clock'):
            codes.append(f"fact:{field['id']}")
        if value is not None:
            verified[field['id']] = value
    for field in entry.fields:
        if field.get('clock') and verified.get(field['id'], BLANK) == BLANK:
            verified[field['id']] = clock_value(field['clock'], locale)
    section.update(heading='', body='', notes='', layout='list',
                   items=[{'label': field['id'], 'text': verified[field['id']], 'value': ''}
                          for field in entry.fields if field['id'] in verified])
    if isinstance(section.get('columns'), list):
        section['columns'] = []


def _shape(section, part, locale):
    """A part's section in the shape its kind takes: its layout, its fixed heading, a list's items, a table's cells.

    A list or sources part written as lines of a body has them as items, since
    its template block reads items; a list longer than its `max_items` is cut
    there. A table's computed cell is emptied when every cell its rule reads
    holds a number, so that the figure is derive.apply's from verified numbers
    and never the model's arithmetic. When one of them is missing derive has
    nothing to compute from, and a figure there is the customer's own (a line
    of an offer or a plan given only as its amount): it is kept and grounded
    as any other cell, since emptying it would lose the figure silently.
    Columns are never stored for a paper: the catalogue draws the header.
    """
    kind = part['kind']
    if kind in skeleton.WRITTEN:
        # The layout the seed gave the part (skeleton._layout, the package's one reading of a part's layout).
        section['layout'] = skeleton._layout(part)
    mode = part.get('heading_mode')
    if mode == 'fixed' and isinstance(part.get('heading'), dict):
        section['heading'] = part['heading'].get(locale) or part['heading']['en']
    elif mode == 'none':
        section['heading'] = ''
    if isinstance(section.get('columns'), list):
        section['columns'] = []
    items = [item for item in section.get('items') or [] if isinstance(item, dict)]
    if kind in ('list', 'sources') and not any(_words({'items': [item]}) for item in items):
        lines = [ENUMERATOR.sub('', line).strip() for line in str(section.get('body') or '').split('\n')]
        items = [{'label': '', 'text': line, 'value': ''} for line in lines if line]
        if items:
            section['body'] = ''
    if kind == 'list' and part.get('max_items'):
        items = items[:part['max_items']]
    if kind == 'table':
        count = len(part.get('columns') or ()) or None
        rules = part.get('computed') or ()
        computed = {rule['column'] for rule in rules}
        made = []
        for item in items:
            values = cells(item, count)
            for rule in rules:
                inputs = [values[column] if column < len(values) else '' for column in rule['of']]
                if rule['column'] < len(values) and all(re.search(r'\d', value) for value in inputs):
                    values[rule['column']] = ''
            made.append(_row(values) if computed or count else item)
        items = made
    section['items'] = items


def _questions(questions, trusted, translated, codes):
    """The test's questions guarded: no quotation or law the customer did not give; a question left broken goes.

    The answer is guarded as its option is, so it still equals the option's
    text. A question whose stem or one of whose options a removed legal
    sentence emptied is taken out whole: half a question is no question.
    """
    kept = []
    for question in questions or []:
        if not isinstance(question, dict):
            continue
        question = dict(question)
        broken = False
        for key in ('stem', 'answer', 'explanation'):
            if isinstance(question.get(key), str) and question[key].strip():
                question[key], found = facts.guard(question[key], trusted, translated=translated)
                codes.extend(found)
                broken = broken or (key == 'stem' and not question[key].strip())
        options = []
        for option in question.get('options') or []:
            if isinstance(option, str) and option.strip():
                option, found = facts.guard(option, trusted, translated=translated)
                codes.extend(found)
                broken = broken or not option.strip()
            options.append(option)
        if isinstance(question.get('options'), list):
            question['options'] = options
        if broken:
            # Guard's own codes (a law or a quotation) already say what emptied it.
            continue
        kept.append(question)
    return kept


def _paper_sources(section, trusted, translated, names, codes):
    """A sources part's items, only those the customer named or a file's own text gives, never a file name.

    With none left the part is empty, which the reference list draws as a
    numbered form of ruled lines for the customer to fill in.
    """
    items, found = facts.verify_items([item for item in section.get('items') or [] if isinstance(item, dict)],
                                      trusted, file_names=names, translated=translated)
    codes.extend(found)
    lines = [line for line in str(section.get('body') or '').split('\n') if line.strip()]
    kept = []
    for line in lines:
        verified, found = facts.verify_items([ENUMERATOR.sub('', line)], trusted, file_names=names,
                                             translated=translated)
        codes.extend(found)
        if verified:
            kept.append(line)
    section.update(body='\n'.join(kept), items=items)
    if isinstance(section.get('notes'), str):
        section['notes'], found = facts.ground(section['notes'], trusted, translated=translated)
        codes.extend(found)


def _finish_part(section, part, *, locale, trusted, translated, names, codes):
    """One written part of a paper: shaped, then grounded, guarded or verified by its kind.

    A section no part of the entry names (none should reach here) is grounded,
    the strict reading: at worst a false blank, never an invention.
    """
    if part is not None:
        _shape(section, part, locale)
    if part is not None and part['kind'] == 'sources':
        _paper_sources(section, trusted, translated, names, codes)
        return
    strict = part is None or part.get('grounded')

    def checked(text):
        text, found = (ground_paper if strict else facts.guard)(text, trusted, translated=translated)
        codes.extend(found)
        return text
    _texts(section, checked, heading=part is None or part.get('heading_mode') == 'model')


def _drop_empty(entry, content):
    """The sections of `content` without the instances of a model-sized group that hold nothing.

    Such a group is seeded at its max and the model fills as many instances as
    the customer's plan or files need. An instance is empty when none of its
    sections holds a body or an item with words (a heading alone is no
    chapter). Empty instances are kept only to reach the group's min, the
    first of them first; their ids are left as they are.
    """
    groups = entry.raw.get('groups') or {}
    instances = {}
    for section in content['sections']:
        part = entry.part(section.get('id'))
        if part is None or not part.get('group') or (groups.get(part['group']) or {}).get('sized') != 'model':
            continue
        instances.setdefault(part['group'], {}).setdefault(_instance(section['id'], part), []).append(section)
    dropped = set()
    for group, found in instances.items():
        empty = [number for number in sorted(found) if not any(_words(section) for section in found[number])]
        keep = max(0, groups[group]['min'] - (len(found) - len(empty)))
        for number in empty[keep:]:
            dropped |= {id(section) for section in found[number]}
    if dropped:
        content['sections'] = [section for section in content['sections'] if id(section) not in dropped]


def _paper(entry, data, content, *, only, file_names, codes):
    """(content, warnings): a category paper held to the customer's words and shaped by its parts.

    A part that cannot be finished is left empty ('finish:form') rather than
    shipped unchecked or costing the customer the paper. Unlike a deck, a
    paper whose draft cannot be read at all (what the customer said, its
    entry) raises: its grounded parts are a letter's or a form's facts, and a
    job that fails is not counted, while an unchecked one could ship an
    invented name.
    """
    content = copy.deepcopy(content)
    revision = data.get('revision') or {}
    scope = set(revision.get('selected_section_ids') or ()) or None
    if only is not None:
        scope = set(only) if scope is None else scope & set(only)
    if scope is not None and not scope:
        # Nothing to finish (a top-up that wrote nothing, a change whose selection it did not meet): an empty scope
        # must not reach quality's tidy and enforce, where a falsy selection means the whole document.
        return content, []
    locale = _locale(data)
    trusted = facts.trusted(data)
    translated = _translated(data)
    names = _file_names(data) if file_names is None else list(file_names)
    found = []
    # A part the model does not write (a fixed part, drawn from facts and template labels, or the questions) is never
    # seeded, so a section of one is the model's own: an ariza's "addressee" naming a head the customer never named.
    # The template never draws it and plain() would print it, so it goes whole, whatever the scope.
    sections = []
    for section in content.get('sections') or []:
        part = entry.part(section.get('id')) if isinstance(section, dict) else None
        if part is not None and part['kind'] not in skeleton.WRITTEN:
            found.append(UNWRITTEN)
            continue
        sections.append(section)
    content['sections'] = sections
    whole = scope is None
    if whole and not any(section.get('id') == FACTS for section in sections) \
            and any(field.get('clock') for field in entry.fields):
        # Appended, not put first: the job trims sections past the quoted count by position, and a facts section put
        # first would push the model's last written part out (the template finds facts by id, wherever they are).
        sections.append({'id': FACTS, 'heading': '', 'body': '', 'notes': '', 'layout': 'list', 'items': []})
    tables = False
    for section in sections:
        if scope is not None and section.get('id') not in scope:
            continue
        part = None if section.get('id') == FACTS else entry.part(section.get('id'))
        try:
            if section.get('id') == FACTS:
                _facts(entry, section, trusted, translated, locale, found)
            else:
                _finish_part(section, part, locale=locale, trusted=trusted, translated=translated, names=names,
                             codes=found)
                tables = tables or (part is not None and part['kind'] == 'table')
        except Exception as error:
            # The type only, as the codes are: an exception's message may carry the customer's words.
            log.warning('Category %s: part %s could not be finished and is left empty (%s)', entry.id,
                        section.get('id'), type(error).__name__)
            section.update(body='', items=[])
            found.append('finish:form')
    if whole:
        if entry.raw.get('title') == 'label':
            content['title'] = entry.name(locale)
        elif isinstance(content.get('title'), str):
            # A fact-led paper's title may name its people, so it is held as its grounded parts are.
            led = _led(entry)
            check = ground_paper if led else facts.guard
            title, title_codes = check(content['title'], trusted, translated=translated)
            found.extend(title_codes)
            if not led:
                title = _guarded_title(title, trusted, translated, found)
            content['title'] = title if title.strip() or not content['title'].strip() else entry.name(locale)
        if content.get('questions'):
            content['questions'] = _questions(content['questions'], trusted, translated, found)
        _drop_empty(entry, content)
    if whole or tables:
        from . import derive
        content = derive.apply(entry, content, trusted)
    from .. import quality
    content, _ = quality.tidy(content, scope)
    content, _ = quality.enforce(content, locale, scope)
    found = list(dict.fromkeys(found))
    if codes is not None:
        codes.extend(found)
    if found:
        log.info('Category %s: finish took out %s', entry.id, ', '.join(found))
    return content, [FACTS_BLANKED] if any(code != UNWRITTEN for code in found) else []


def _paper_exempt(entry, data):
    """The sections of a paper quality.check must not send back for being empty, repeating or not prose.

    The facts section; list, table and sources parts, which hold names and
    figures rather than prose; optional parts, empty unless the customer's
    words call for them; every instance of a model-sized group, which stands
    empty where the customer's plan has fewer chapters; and the instances of a
    grouped part whose heading is fixed or none, the same on each by design.
    Sent back, a repair could only invent to fill or vary them.
    """
    try:
        groups = entry.raw.get('groups') or {}
        found = set()
        for section in (data.get('content') or {}).get('sections') or []:
            section_id = section.get('id')
            if section_id == FACTS:
                found.add(section_id)
                continue
            part = entry.part(section_id)
            if part is None:
                continue
            group = groups.get(part['group']) if part.get('group') else None
            if part['kind'] in ('list', 'table', 'sources') or part.get('need') == 'optional' or (
                    group is not None and (group['sized'] == 'model' or part.get('heading_mode') != 'model')):
                found.add(section_id)
        return found
    except Exception:
        log.exception('Category %s: no quality exemptions', entry.id)
        return set()


def plain(data, content):
    """The emergency fallback's content of a finished category paper, for today's renderer (architecture 6.7).

    Only for a failed template build or a template this worker lacks; no
    category is ever ticked onto it. The contract:
    - the title is the content's title (the category's name when it has none);
    - the facts are one list section of label and value lines in the field
      order, ____ for a field whose policy draws a blank; choices, flags and
      files are settings, not lines. Each is an item {label, text}, which
      today's renderer draws as "Label — value": a label of its own may hold
      a colon ("Kimga: tashkilot"), and "Label: value" would read as two;
      a label's trailing hint in brackets ("(ixtiyoriy)") is left off;
    - each written part with words is a section under its heading; a section
      of a fixed part or of an id the entry does not name is not drawn;
    - a table's rows are list items whose cells are joined by " — ", under a
      line of its column names, so nothing is cut at three columns; an empty
      cell is ____, so every value stays under its column;
    - the verified sources are a list section, without the model's numbers;
    - the questions stay in content.questions.
    Anything else is returned as it is. Never raises: on a failure the
    content is returned as given, which today's renderer can still draw.
    """
    entry = _entry(data)
    if entry is None or entry.service != 'pdf':
        return content
    try:
        locale = _locale(data)
        values = {}
        for section in content.get('sections') or []:
            if section.get('id') == FACTS:
                values = {str(item.get('label')): _value(item) for item in section.get('items') or []
                          if isinstance(item, dict) and _value(item)}
        # A field the paper also writes as a part of the same id (an ariza's request) is drawn there, not as a blank.
        written = {section.get('id') for section in content.get('sections') or [] if _words(section)}
        lines = []
        for field in entry.fields:
            if field['kind'] in ('choice', 'flag', 'file'):
                continue
            value = values.get(field['id'])
            if not value and (field['missing'] not in ('blank', 'ask') or field['id'] in written):
                continue
            value = '; '.join(line.strip() for line in (value or BLANK).split('\n') if line.strip())
            label = (field['label'].get(locale) or field['label']['en']).strip().rstrip(':').strip()
            # A field's label is the review form's: its hint for the customer ("(ixtiyoriy)", "(if writing to a
            # state body)") is no word of the document.
            label = HINT.sub('', label).rstrip(' :') or label
            lines.append({'label': label, 'text': value, 'value': ''})
        sections = []
        if lines:
            sections.append({'id': FACTS, 'heading': PLAIN_FACTS[locale], 'body': '', 'notes': '', 'layout': 'list',
                             'items': lines})
        for section in content.get('sections') or []:
            if section.get('id') == FACTS or not _words(section):
                continue
            part = entry.part(section.get('id'))
            # Only a written part is drawn, as the template would: a fixed part's or an unknown id's section is
            # the model's own and was never checked as the facts it would print were.
            if part is None or part['kind'] not in skeleton.WRITTEN:
                continue
            made = {'id': section.get('id'), 'heading': str(section.get('heading') or ''),
                    'body': str(section.get('body') or ''), 'notes': '', 'layout': 'text', 'items': []}
            items = [item for item in section.get('items') or []
                     if isinstance(item, dict) and _words({'items': [item]})]
            kind = part['kind']
            if kind == 'table':
                columns = [column.get(locale) or column['en'] for column in part.get('columns') or ()]
                count = len(columns) or None
                header = PLAIN_CELLS.join(columns)
                made['body'] = '\n'.join(text for text in (made['body'], header) if text.strip())
                # An empty cell (a computed one before derive fills it, a quantity not given) stays a blank, so each
                # value keeps its column under the header and a price never reads as the quantity.
                made['items'] = [{'label': '', 'text': PLAIN_CELLS.join(cell or BLANK for cell in cells(item, count)),
                                  'value': ''} for item in items]
                made['layout'] = 'list'
            elif kind in ('list', 'sources') or items:
                made['items'] = [{key: str(item.get(key) or '') for key in ('label', 'text', 'value')}
                                 for item in items]
                if kind == 'sources':
                    # The model's "1" beside a source would read "1 — Saidov B. …" in a list already numbered.
                    for item in made['items']:
                        if re.fullmatch(r'[\s\d.)\[\]]*', item['label']):
                            item['label'] = ''
                made['layout'] = 'list'
            sections.append(made)
        title = str(content.get('title') or '').strip() or entry.name(locale)
        return {**content, 'title': title, 'sections': sections, 'questions': list(content.get('questions') or [])}
    except Exception as error:
        # The type only: an exception's message may carry the customer's words.
        log.warning('Category %s: no plain projection; the content goes to the fallback as it is (%s)', entry.id,
                    type(error).__name__)
        return content
