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
  but never quotes or cites a law the customer did not give;
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
writes ____. What it removed is said as codes (`ground:number`, `ground:name`,
`ground:quote`, `ground:law`, `cover:line`, `source:dropped`), logged without
a value, and any of them raises the job warning `facts_blanked`, on which the
bot adds the entry's `blanks` notice. `apply` never raises: a slide it cannot
finish becomes an honest form rather than costing the customer the deck or
shipping what was not checked. Only when the deck itself cannot be read (its
slots, the customer's words) is it returned as the model wrote it, logged, as
title_lines.apply does: that is a bug to fix, not a customer to fail.

`pins(data, content)` gives the first render of a category deck the calm
variants its slots name, and `exempt(data)` the slides quality.check must not
send back for repeating each other, which a deck of honest forms does by
design. A category paper is F2's: until then these leave it as it is.
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
    fact.
    """
    if _key(line) in own:
        return True
    label, value = _split(line)
    if not facts.supported(value, 'line', trusted, translated=translated):
        return False
    return not label or facts.supported(' '.join(label.split()[1:]), 'line', trusted, translated=translated)


def _title_page(text, trusted, translated, own, codes, *, first_free):
    """A cover's or a closing slide's lines, keeping only the customer's; the first kept as a subtitle when `first_free`.

    A cover of one line has a subtitle, not a title page (slide_layouts.title_lines):
    it is guarded, and goes only when it holds a number the customer did not
    give ("Toshkent — 2026"). A line that only stands in for one ("____",
    "F.I.Sh.: ____") is never kept. On a closing slide the first line is its own
    words ("Savollaringiz bormi?") and the lines after it are an author line
    copied from the cover, held as the cover's are.
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
        if number == 0 and (first_free or len(lines) == 1):
            line, found = facts.guard(line, trusted, translated=translated)
            codes.extend(found)
            if _key(line) in own or all(numbers.known(value, trusted.values) for value in numbers.found(line)):
                if line.strip():
                    kept.append(line)
                continue
        elif _line_known(line, trusted, translated, own):
            kept.append(line)
            continue
        codes.append('cover:line')
    return '\n'.join(kept)


def _texts(section, check, heading):
    """Run `check(text) -> text` over every field of a slide a reader sees; its heading only when `heading`."""
    keys = ('heading', 'body', 'notes') if heading else ('body', 'notes')
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

    def guarded(text):
        text, found = facts.guard(text, trusted, translated=translated)
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
        _texts(section, guarded, heading=not fixed)
    else:
        _texts(section, grounded, heading=not fixed)


def apply(data, content, *, file_names=None, codes=None):
    """(content, warnings): a category deck's answer held to the customer's words; anything else as it is.

    `file_names` are the attached files' names (looked up from the draft's
    `source_ids` when not given); `codes`, a list, receives what was blanked
    or removed, for the caller's log. `content` is never changed in place.
    Never raises (see the module's docstring).
    """
    entry = _entry(data)
    if entry is None or entry.service != 'slides':
        return content, []
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
    asked to make them differ could only invent). A paper's are F2's.
    """
    entry = _entry(data)
    if entry is None or entry.service != 'slides':
        return set()
    try:
        uses = list(_uses(entry, data).values())
        taken = Counter(use.part['id'] for use in uses)
        return {use.section_id for use in uses if taken[use.part['id']] > 1
                and (use.part.get('heading_mode') == 'fixed' or use.part.get('source') == 'customer')}
    except Exception:
        log.exception('Category %s: no quality exemptions', entry.id)
        return set()
