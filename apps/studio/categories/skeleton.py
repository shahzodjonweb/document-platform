"""The shape of a category draft: its cues, its length, its parts and slots, and how much each part is.

Everything here is a pure function of the catalogue entry, the length and the
cues read from the customer's message, so a draft's skeleton is never stored:
the domain seeds from it, the prompt names its rows from it, the provider
dresses the planned slides with it and the finish draws its fixed words from
it, and they all agree because they compute the same thing.

- `cues(entry, text, has_files)`: the entry's named stem lists found in the
  message, after `exclusive`, plus the computed `sources` cue;
- `length(entry, ...)`: how many pages or slides, by the entry's mode;
- `parts(entry, length, cues)`: every part that exists, a grouped part once per
  instance, each a `Use` that names the section it is written in (None for a
  part drawn from facts and labels, or from the questions);
- `seed(...)`: the blank sections a new draft starts with; `slots(...)` the
  slots of a deck, exactly `length` of them;
- `dress(data, sections)`: a deck's fixed headings and slot layouts put back;
- `words`, `pages`, `pages_in` and `spans`: how long each part is written and
  how a category paper is cut into calls.

`cues` is a required argument everywhere it is taken, never defaulted: `dress`,
`pages_in` and `spans` read `cues_of(data)` (the brief, the pasted source text
and whether files are attached), so a caller that seeds or sizes a draft must
pass `cues_of` of the same payload, or its skeleton differs from theirs.

A draft without a category never reaches this module.
"""
import math
import re
from collections import namedtuple

from apps.core.errors import DomainError

from .. import pages as paging
from ..language import normalised
from .catalogue import LOCALES, SOURCES_CUE, of

# The facts section: one item per field the customer gave (label = field id),
# always first in a category paper, holding no written part of its own.
FACTS = 'facts'
# The computed `sources` cue also holds when the message talks of a reference
# list. Phrases, never the bare nouns: "manba", "источник" and "sources" are
# everyday topic words ("Qayta tiklanuvchi energiya manbalari", "Источники
# права"), and "adabiyot" is a school subject, so a bare stem gave a deck a
# sources slide, an empty form, when the customer supplied no source at all.
# The bare "references" and "bibliography" go the same way ("Pop culture
# references", "Библиография как наука"): a customer who only asks for
# references gives none, and the AI invents none. "Список" is matched as both
# "список" and "списка/списком", and Uzbek "ro‘yxat" also as "ro‘yhat".
# A heading word counts only as a heading of a list: at the start of a line,
# then a colon and a new line, a colon and a numbered item, or a numbered or
# bulleted item on the next line ("Manbalar:\n…", "Sources: 1. …",
# "References\n- …"). "energy sources: solar, wind" is a topic, and a subject
# label ("Literature: Romeo and Juliet", "Adabiyotlar: 7-sinf") is no list.
# Read over folded text (apostrophes one, casefolded).
_NUMBERED = r"\d{1,3}[.)][ \t]*\S"
REFERENCES = re.compile(
    r"(?<!\w)(?:"
    r"(?:adabiyot|manba)\w*\s+r[ou]'?y[xh]at|foydalanilgan\s+(?:adabiyot|manba)"
    r"|(?:адабиёт|манба)\w*\s+р[ўу]йх?ат|фойдаланилган\s+(?:адабиёт|манба)"
    r"|спис(?:ок|к)\w*\s+(?:использованн\w*\s+)?(?:литератур|источник)|использованн\w*\s+(?:литератур|источник)"
    r"|библиографическ\w*\s+спис"
    r"|reference\s+list|works\s+cited|list\s+of\s+(?:sources|references|literature|works)"
    r")"
    r"|^[ \t]*(?:adabiyotlar|manbalar|адабиётлар|манбалар|литература|источники|библиография"
    r"|literature|sources|references|bibliography)"
    r"[ \t]*(?::[ \t]*\n\s*\S|:[ \t]*" + _NUMBERED + r"|\n[ \t]*(?:[-–—•*][ \t]*\S|" + _NUMBERED + r"))",
    re.MULTILINE)
# Part kinds the model writes as a section of their own; fixed parts are drawn
# from facts and template labels, questions from content.questions.
WRITTEN = ('prose', 'list', 'table', 'sources')
# A call writes at most this many sections of a category paper (beside the
# PAGES_PER_CALL pages): a paper is many short parts, and one reply of more
# would outgrow what the provider's schema check lets an array hold well.
SECTIONS_PER_CALL = 40
# Words of a page of prose. A paper filling its count is asked for a page as a
# Boshqa document is (pages.target_words: the model writes about two thirds of
# what it is asked for, and the template's fit absorbs the rest); a ceiling is
# what a page holds, so a maximum never promises more than fits.
TARGET_WORDS = paging.target_words('pdf')
CAPACITY_WORDS = round(paging.CHARS_PER_PAGE / paging.CHARS_PER_WORD)
# The lowest word target a written part is given: told "0 words", a model
# writes nothing, and an empty part is only right when the customer gave
# nothing for it, which the model decides, not its share.
MIN_WORDS = 20
# The low end of a word target, as a share of the high end.
LOW_SHARE = 0.8
# The most words one part is asked for: what the stored body bound
# (pages.max_section_chars) holds. A body past it is cut mid-sentence by
# validate_content, and one long part of a long paper (a model-sized chapter
# of 35 pages) would otherwise be asked for more than that. It also bounds a
# single part's reply when spans gives it a call of its own. What the cap
# leaves short of the count, the top-up writes, as for any short paper.
# CHARS_PER_WORD is an average and Uzbek words run longer, so the cap keeps a
# quarter of the bound as headroom: a part written at its full target in long
# words still ends where the model ended it.
SECTION_HEADROOM = 0.75
SECTION_WORDS = int(SECTION_HEADROOM * paging.max_section_chars('pdf') / paging.CHARS_PER_WORD)

Use = namedtuple('Use', 'section_id part instance group')
Use.__doc__ = """One part as it exists in a draft: the section it is written in (None when it holds none),
its catalogue part, which instance of it this is (1 for an ungrouped part) and its group (None)."""


# ---------------------------------------------------------------- cues


def _folded(text):
    return normalised(text or '').casefold()


def stem_found(stem, text):
    """Whether a cue stem starts a word of `text`, which is already folded (normalised, casefolded).

    From the start of a word, so a short stem ("bmi", "вкр") is not found
    inside another word ("submit"), while a stem still takes any ending.
    """
    return re.search(r'(?<!\w)' + re.escape(_folded(stem)), text) is not None


def cues(entry, text, *, has_files):
    """The cues that hold for this message, as a frozenset of names.

    A cue holds when any of its stems, in any language, starts a word of the
    message (folded as language.normalised folds Uzbek apostrophes). Within
    each `exclusive` list only the first that holds, in list order, counts: a
    master's thesis about banking practice is a master's thesis. `sources`
    holds when files are attached or the message names a reference list
    (REFERENCES), so a deck without supplied sources has no sources slide.
    """
    folded = _folded(text)
    held = {name for name, stems in (entry.raw.get('cues') or {}).items()
            if any(stem_found(stem, folded) for words in stems.values() for stem in words)}
    if has_files or REFERENCES.search(folded):
        held.add(SOURCES_CUE)
    return effective(entry, held)


def effective(entry, held):
    """The cues of `held` that count, as a frozenset: within each `exclusive` list only the first, in list order."""
    held = set(held)
    for ordered in entry.raw.get('exclusive') or ():
        found = [name for name in ordered if name in held]
        held -= set(found[1:])
    return frozenset(held)


def brief(data):
    """The message the cues of a draft are read from: what the domain reads as its brief.

    The original description for a change (whose own prompt is the request),
    with the pasted source text after it; an answer to the review question is
    already part of the prompt.
    """
    revision = data.get('revision') or {}
    prompt = revision.get('original_prompt') or data.get('prompt') or ''
    return f"{prompt}\n{data.get('source_text') or ''}"


def cues_of(data):
    """The cues of a draft: `cues` over its brief, with its attached files."""
    entry = of(data)
    if entry is None:
        return frozenset()
    return cues(entry, brief(data), has_files=bool(data.get('source_ids') or data.get('excerpts')))


# ---------------------------------------------------------------- length


def length(entry, *, asked=None, chosen=None, cues=frozenset(), ceiling=None, questions=0):
    """How many pages (or slides) this draft is, by the entry's `length.mode`.

    - count: the number chosen on the review (`chosen`), else the one read from
      the brief (`asked`, pages.requested_pages), else the default of the first
      `by_cue` whose cue holds, else the default; held within min..max and the
      plan's `ceiling`. The domain keeps `asked` beside it, so a clamp is shown.
    - fixed: always the default (an ariza is one page); no stepper.
    - derived: from the question count (`questions`, else the entry's default),
      ceil((questions + first_page_fewer) / questions_per_page) + extra_pages;
      a page count in the brief is read only when no question count is.

    The plan's ceiling always wins, even over an entry's minimum: it is the
    most this account may be given.
    """
    rule = entry.length
    top = min(rule['max'], ceiling) if ceiling else rule['max']
    top = max(1, top)
    bottom = min(rule['min'], top)

    def held(value):
        return max(bottom, min(int(value), top))
    if rule['mode'] == 'fixed':
        return held(rule['default'])
    if rule['mode'] == 'derived':
        if not questions and asked:
            return held(asked)
        count = min(questions or entry.raw['questions']['default'], entry.raw['questions']['max'])
        per = rule['per']
        return held(math.ceil((count + per['first_page_fewer']) / per['questions_per_page']) + per['extra_pages'])
    for value in (chosen, asked):
        if value:
            return held(value)
    for item in rule.get('by_cue', ()):
        if item['cue'] in cues:
            return held(item['default'])
    return held(rule['default'])


# ---------------------------------------------------------------- parts and slots


def _exists(part, length, cues):
    if part.get('retired'):
        return False
    when = part.get('when')
    if when:
        kind, name = when.split(':', 1)
        if (name in cues) != (kind == 'cue'):
            return False
    return part.get('from', 1) <= length <= part.get('until', 10 ** 6)


def instances(entry, group, length):
    """How many times a group repeats in a paper of this length.

    `sized: model` is seeded at its max: the model fills as many as the brief,
    its plan or its files need and finish drops the empty ones. `sized: length`
    grows with the paper, from its min at the entry's shortest length to its
    max at the longest, in even steps.
    """
    size = (entry.raw.get('groups') or {})[group]
    if size['sized'] == 'model' or size['min'] == size['max']:
        return size['max']
    shortest, longest = entry.length['min'], entry.length['max']
    if longest <= shortest:
        return size['max']
    step = (min(max(length, shortest), longest) - shortest) / (longest - shortest)
    return max(size['min'], min(size['max'], size['min'] + round((size['max'] - size['min']) * step)))


def slots(entry, length, cues):
    """The `length` slots of a deck in blueprint order, a repeating slot once per slide it takes.

    Required and usual slots that exist at this length (`from`, `until`,
    `when`) come first; optional ones join by `join`; the remainder goes to the
    repeating slots in turn; with too many, the latest joiners leave, never a
    required one. Below the entry's minimum, which only a plan ceiling makes
    (`length` lets it win), required slots leave too, the last first and never
    the cover, so the deck still has exactly the slides quoted. That order is
    blind to meaning: slides.himoya held to two slides keeps its aims slide and
    drops results and conclusion; an entry wanting another order needs an
    explicit keep order, which no entry has yet. Every deck
    entry's parts are proven to give exactly `length` for every length from 1
    to its maximum and every cue subset (tests/test_category_skeleton.py).

    `cues` has no default: the domain, the prompt and `dress` must all read the
    same cues, `cues_of(data)`, or their slots disagree.
    """
    live = [part for part in entry.parts if _exists(part, length, cues)]
    count = {part['id']: ((part.get('repeat') or {}).get('min', 1) if part['need'] != 'optional' or 'join' in part
                          else 0) for part in live}
    leaving = sorted(live, key=lambda part: (part['need'] == 'required', -part.get('join', 0)))
    while sum(count.values()) > length:
        part = next((part for part in leaving if count[part['id']] and part['need'] != 'required'), None)
        if part is None:
            break
        count[part['id']] -= 1
    for part in reversed(live[1:]):
        while sum(count.values()) > length and count[part['id']]:
            count[part['id']] -= 1
    growing = sorted((part for part in live if (part.get('repeat') or {}).get('max', 1) > 1),
                     key=lambda part: part.get('join', 0))
    while sum(count.values()) < length and any(count[part['id']] < part['repeat']['max'] for part in growing):
        for part in growing:
            if sum(count.values()) < length and count[part['id']] < part['repeat']['max']:
                count[part['id']] += 1
    return [part for part in live for _ in range(count[part['id']])]


def parts(entry, length, cues):
    """Every part of a draft of this length, in order, as `Use`s.

    A deck: its slots, the slide ids s1..sN. A paper: every part that exists
    (`when`, `from`, `until`; retired parts never), consecutive parts of one
    group repeated together once per instance, a later instance's section id
    the part id with `_2`, `_3`. Fixed and question parts are listed with no
    section, because the template draws them; they still take their share.
    """
    if entry.service == 'slides':
        seen = {}
        made = []
        for number, part in enumerate(slots(entry, length, cues), 1):
            seen[part['id']] = seen.get(part['id'], 0) + 1
            made.append(Use(f's{number}', part, seen[part['id']], None))
        return made
    live = [part for part in entry.parts if _exists(part, length, cues)]
    made, position = [], 0
    while position < len(live):
        group = live[position].get('group')
        if group is None:
            made.append(_use(live[position], 1, None))
            position += 1
            continue
        run = []
        while position < len(live) and live[position].get('group') == group:
            run.append(live[position])
            position += 1
        for instance in range(1, instances(entry, group, length) + 1):
            made += [_use(part, instance, group) for part in run]
    return made


def _use(part, instance, group):
    section = None
    if part['kind'] in WRITTEN:
        section = part['id'] if instance == 1 else f"{part['id']}_{instance}"
    return Use(section, part, instance, group)


def _layout(part):
    if part['kind'] == 'prose':
        return 'callout' if part.get('block') == 'callout' else 'text'
    return 'table' if part['kind'] == 'table' else 'list'


def seed(entry, length, cues, *, text=''):
    """The blank sections a new category draft starts with.

    A paper: the facts section, then one section per written part instance,
    each with the layout its kind takes. A deck: s1..sN, each with its slot's
    first layout. Nothing else: no headings, which the prompt's rows and the
    finish write in the document's language, and no guidance in a body, so the
    source seed never blanks anything and the admin record shows no catalogue
    text. `text` is for local authoring only, which has no model: the
    customer's words go into the first elastic prose part (a deck's slides
    take its paragraphs in turn, as today's seed does), so a file can still be
    made.
    """
    uses = [use for use in parts(entry, length, cues) if use.section_id]
    if entry.service == 'slides':
        sections = [{'id': use.section_id, 'heading': '', 'body': '', 'notes': '', 'layout': use.part['layouts'][0],
                     'items': [], 'columns': [], 'image_query': ''} for use in uses]
        chunks = [chunk.strip() for chunk in (text or '').split('\n\n') if chunk.strip()]
        for position, section in enumerate(sections):
            if position < len(chunks):
                section['body'] = '\n\n'.join(chunks[position:]) if position == len(sections) - 1 else chunks[position]
        return sections
    sections = [{'id': FACTS, 'heading': '', 'body': '', 'notes': '', 'layout': 'list', 'items': []}]
    sections += [{'id': use.section_id, 'heading': '', 'body': '', 'notes': '', 'layout': _layout(use.part),
                  'items': []} for use in uses]
    if text.strip():
        prose = [section for section, use in zip(sections[1:], uses) if use.part['kind'] == 'prose']
        elastic = [section for section, use in zip(sections[1:], uses)
                   if use.part['kind'] == 'prose' and use.part.get('elastic')]
        if elastic or prose:
            (elastic or prose)[0]['body'] = text.strip()
    return sections


def dress(data, sections):
    """A category deck's sections with each slot's fixed heading and an allowed layout; returns `sections`.

    Run after the plan call and after the model: a fixed slot gets its heading
    in the document's language, a slot without a heading of its own loses any
    the model gave, and a layout outside the slot's list goes back to the
    slot's first. Ids and the count are never touched. The slot of `s{i}` is
    the i-th of the deck's slots at its length, the length being the draft's
    section count, which the domain seeds from them. A change is left alone:
    the customer may have edited slides since, so the slots may no longer map.
    Anything that is not a category deck is returned unchanged.
    """
    entry = of(data)
    if entry is None or entry.service != 'slides' or data.get('revision'):
        return sections
    locale = data.get('output_locale') if data.get('output_locale') in LOCALES else 'en'
    blueprint = slots(entry, len(data['content']['sections']), cues_of(data))
    for section in sections:
        match = re.fullmatch(r's([0-9]{1,4})', str(section.get('id', '')))
        if not match or not 1 <= int(match.group(1)) <= len(blueprint):
            continue
        slot = blueprint[int(match.group(1)) - 1]
        if slot['heading_mode'] == 'fixed':
            section['heading'] = slot['heading'][locale]
        elif slot['heading_mode'] == 'none':
            section['heading'] = ''
        if section.get('layout') not in slot['layouts']:
            section['layout'] = slot['layouts'][0]
    return sections


# ---------------------------------------------------------------- sizes


def _shares(entry, length, cues):
    """Each written section's share of the paper's pages, and its Use: {section id: (share, use)}.

    A part's share is of the whole paper; a grouped part's is split between its
    instances. When the present parts share more than all the pages they are
    scaled down to fit. A paper that fills its count gives the pages the
    present parts leave to its elastic parts, in proportion to their shares;
    a ceiling leaves them unclaimed, since nothing pads a ceiling paper.
    """
    uses = parts(entry, length, cues)
    counted = {}
    for use in uses:
        counted.setdefault(use.part['id'], (use.part, 0))
        counted[use.part['id']] = (use.part, counted[use.part['id']][1] + 1)
    total = sum(part.get('share', 0) for part, _ in counted.values())
    scale = 1 / total if total > 1 else 1
    left = max(0.0, 1 - total * scale)
    elastic = sum(part.get('share', 0) for part, _ in counted.values()
                  if part.get('elastic') and part['kind'] in WRITTEN)
    found = {}
    for use in uses:
        if not use.section_id:
            continue
        part, times = counted[use.part['id']]
        share = part.get('share', 0) * scale
        if entry.length['target'] == 'count' and part.get('elastic') and elastic:
            share += left * part.get('share', 0) / elastic
        found[use.section_id] = (share / times, use)
    return found


def words(entry, use, length, cues):
    """How many words the model writes in one part: (lowest, highest), or (0, most) for a ceiling paper.

    A part with its own `words` keeps them, elastic or not: the research that
    set them (a 60-120 word passage, a 25-90 word request) knows the form
    better than a share does, and elasticity only lets the fit trim it or a
    top-up extend it later. Otherwise its share of the pages sets them (the
    elastic parts of a count paper with the pages the others leave), at a
    page's target for a count paper and at what a page holds for a ceiling. A
    part that holds no section is written in no words. Nothing is asked for
    more than SECTION_WORDS.
    """
    if not use.section_id:
        return 0, 0
    ceiling = entry.length['target'] == 'ceiling'
    fixed = use.part.get('words')
    if fixed:
        high = min(fixed[1], SECTION_WORDS)
        return (0, high) if ceiling else (min(fixed[0], high), high)
    share = _shares(entry, length, cues).get(use.section_id, (0, use))[0]
    if ceiling:
        return 0, min(SECTION_WORDS, max(MIN_WORDS, round(share * length * CAPACITY_WORDS)))
    high = min(SECTION_WORDS, max(MIN_WORDS, round(share * length * TARGET_WORDS)))
    return round(high * LOW_SHARE), high


def pages(data):
    """How many pages a category paper is: its `options.length`, which the domain writes from `length`.

    The one reader of the number for the quote cap, the lease, the call budgets,
    the top-up and the render. None for anything that is not a category paper,
    whose sections are its pages as today. A category paper without a stored
    length is refused (invalid_parameters): the domain always writes one, held
    to the plan's ceiling, and a recomputed default would skip that clamp.

    `data` is draft data (its `options`), never a job's parameters: unlike
    catalogue.of, this reads no `parameters` fallback, so a job passed here is
    refused as having no stored length.
    """
    entry = of(data)
    if entry is None or entry.service != 'pdf':
        return None
    stored = (data.get('options') or {}).get('length')
    if type(stored) is not int or stored < 1:
        raise DomainError('invalid_parameters')
    return stored


def _section_pages(data):
    """[(section id, pages it is written in)] for a category paper, in the draft's order."""
    entry, total = of(data), pages(data)
    shares = _shares(entry, total, cues_of(data))
    found = []
    for section in data['content']['sections']:
        share = shares.get(section['id'])
        if share is None:
            # A section the present cues no longer give (a draft seeded before a
            # cue changed) still counts as its part's share of the pages, split
            # between the instances its group has at this length, as _shares splits it.
            part = entry.part(section['id'])
            size = part.get('share', 0) if part and part['kind'] in WRITTEN else 0
            if size and part.get('group'):
                size /= instances(entry, part['group'], total)
            share = (size, None)
        found.append((section['id'], share[0] * total))
    return found


def pages_in(data, first, last):
    """The pages that sections first..last (end excluded) of a draft are written in, as a whole number.

    A category paper's sections are parts of unequal size, so a span is its
    sections' shares of the pages, rounded up and at least one; anything else
    is one page (or slide) a section, as today.
    """
    if pages(data) is None:
        return last - first
    covered = sum(size for _, size in _section_pages(data)[first:last])
    return max(1, math.ceil(covered - 1e-9))


def spans(data):
    """The (start, end) section ranges a category paper is written in, one provider call each.

    Consecutive sections whose pages add up to at most PAGES_PER_CALL and that
    are at most SECTIONS_PER_CALL in number; a single larger part is a call of
    its own, whose reply stays small because no part is asked for more than
    SECTION_WORDS. Anything else is cut as today (pages.batches).
    """
    if pages(data) is None:
        return paging.batches(len(data['content']['sections']))
    made, start, held = [], 0, 0.0
    sizes = _section_pages(data)
    for position, (_, size) in enumerate(sizes):
        if position > start and (held + size > paging.PAGES_PER_CALL + 1e-9
                                 or position - start >= SECTIONS_PER_CALL):
            made.append((start, position))
            start, held = position, 0.0
        held += size
    made.append((start, len(sizes)))
    return made
