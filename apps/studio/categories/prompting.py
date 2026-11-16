"""What a category draft tells the model, beside what every draft is told (architecture 3.1, 3.2).

apps/studio/prompting.request_body builds every request. For a draft with a
category it adds what is here, and only then: a draft without one never
imports this module, so its request stays byte for byte today's
(tests/test_prompt_golden.py).

- `DECK`: how a category deck follows its slot list, said once for every deck
  category and language, after the layout guide;
- `REVISION_NOTE`: what "more information" means in a category paper's change;
- `block(entry)`: the category's tone, its model rules and its field table,
  with each fixed part's write text, the same in every language and holding
  no customer text, so the cached prefix is shared by every customer of the
  category;
- `rows(data, mine, first)`: one row per section of this call, built from the
  catalogue at request time with headings in the document's language, so
  nothing the model reads about a slot is stored in the draft;
- `guidance(...)`: writing_guidance for a category deck's new and plan calls;
- `cache_tag(data)`: what a category adds to the prompt cache key, so a
  catalogue edit is never served a prefix cached for the old wording.

PDF categories reach the model through P2's stacks; until then a paper is
told nothing here.
"""
import re

from .catalogue import LOCALES, of
from .skeleton import cues_of, slots

# About a thousand characters, one text for every deck category and language.
# The category's own rules and a slot's holds win over the general slide sizes
# (a himoya cover's heading is the topic in full, never 8 words), and nothing
# on a slide comes from the model's general knowledge where the slot says it
# is the customer's.
DECK = (
    'This deck is of a category, whose rules follow. When parts is given, it lists the slots of this call, one row '
    'per section in order: keep the row\'s heading word for word where it gives one, write one where it is empty '
    'and leave it empty where it is null; '
    'choose one of its layouts, and write what its holds says. The variety limits of the layout guide do not apply '
    'to slots the list fixes, and the category\'s rules and a slot\'s holds win over the general sizes wherever '
    'they differ. A slot of source customer holds only what the description or the sources say; with no such '
    'material it is an honest form, its heading and lines that end in a ruled blank (____), never filled from '
    'general knowledge. A slot of source draft may be drafted from the topic\'s own words only. A sources slot '
    'holds only sources the customer named or attached, never a file name. Never write a person, organisation, '
    'date, number, price, law, quotation or source that is not in the description or the sources; in a change, '
    'more or fuller information means more of what they say, never new names, numbers or sources.'
)
# Narrows REVISION_SYSTEM's "more information means facts, dates, names" for a
# category paper's change; P2 sends it after REVISION_SYSTEM.
REVISION_NOTE = (
    'This document is a category paper. In a change, more or fuller information means more of what the '
    'description, the change requests and the sources say, never new names, numbers, dates or sources. Its parts '
    'keep their ids and kinds, and none is added or removed. Never write a heading the part list marks fixed: the '
    'template draws it.'
)
# What a category deck's new and plan calls add to today's guidance; DECK says the rest.
SLOT_GUIDANCE = 'Each section is the slot its row in parts names: write it as the row says.'
PLAN_GUIDANCE = 'Each section is the slot its row in parts names: keep its heading and choose one of its layouts.'


def _line(text):
    # A blank line inside the instructions would split the cached prefix's blocks.
    return re.sub(r'\s+', ' ', str(text or '')).strip()


def _field(item):
    choices = f", {'|'.join(item['choices'])}" if item.get('choices') else ''
    return f"- {item['id']}: {_line(item['label']['en'])}, {item['kind']}{choices}"


def block(entry):
    """The category's block of the instructions: its tone, its model rules and its field table.

    The fields are grouped under each fixed part's write text: a fixed part has
    no section and no row, so this is the only place its rules (an ariza's
    dative addressee) reach the model. English, as the rest of the
    instructions are; the field labels too, since the block must read the same
    whatever language the document is in. Retired parts are left out.
    """
    raw = entry.raw
    lines = [f'Category {entry.id}.', f"Tone: {_line(raw['tone'])}"]
    rules = [_line(rule['text']) for rule in raw['rules'] if rule['to'] == 'model']
    if rules:
        lines.append('Rules:')
        lines += [f'- {rule}' for rule in rules]
    fields = {item['id']: item for item in raw['fields']}
    placed = set()
    fixed = [part for part in raw['parts'] if part['kind'] == 'fixed' and not part.get('retired')]
    for part in fixed:
        lines.append(f"Part {part['id']}, drawn by the template, never written as a section: {_line(part.get('write'))}")
        for name in part.get('fields', ()):
            if name in fields and name not in placed:
                lines.append(_field(fields[name]))
                placed.add(name)
    rest = [item for item in raw['fields'] if item['id'] not in placed]
    if rest:
        lines.append('Fields the customer may give (id: label, kind):' if not fixed else 'Other fields:')
        lines += [_field(item) for item in rest]
    return '\n'.join(lines)


def _locale(data):
    return data.get('output_locale') if data.get('output_locale') in LOCALES else 'en'


def rows(data, mine, first=0):
    """The `parts` rows of a category deck's call: {id, slot, heading, layouts, source, holds} per section.

    The slot of `s{i}` is the i-th of the deck's slots at its length (the
    draft's section count) and the cues of its brief, as skeleton.dress reads
    it. A fixed heading is given in the document's language; an empty one is
    the model's to write; null is a slide without one, which skeleton.dress
    would empty anyway, so the model is not asked for words thrown away. A slot met again in the same call says which row it
    repeats instead of carrying its holds twice. `first` is where `mine` starts
    in the draft, kept for the PDF rows; a deck reads the slot from the id.
    Anything that is not a category deck has no rows.
    """
    entry = of(data)
    if entry is None or entry.service != 'slides':
        return []
    locale = _locale(data)
    blueprint = slots(entry, len(data['content']['sections']), cues_of(data))
    made, seen = [], {}
    for section in mine:
        match = re.fullmatch(r's([0-9]{1,4})', str(section.get('id', '')))
        if not match or not 1 <= int(match.group(1)) <= len(blueprint):
            continue
        slot = blueprint[int(match.group(1)) - 1]
        holds = _line(slot.get('write'))
        if slot.get('notes'):
            holds += f" Speaker notes: {_line(slot['notes'])}"
        if slot['id'] in seen:
            holds = f"another slide of the slot of {seen[slot['id']]}, written as that row says"
        else:
            seen[slot['id']] = section['id']
        mode = slot['heading_mode']
        made.append({'id': section['id'], 'slot': slot['id'],
                     'heading': slot['heading'][locale] if mode == 'fixed' else None if mode == 'none' else '',
                     'layouts': list(slot['layouts']), 'source': slot.get('source', 'draft'), 'holds': holds})
    return made


def guidance(data, mine, first, total, stage):
    """writing_guidance for a category deck's call: today's sizes and pictures, then its slots.

    `stage` is 'new' (a new deck or a later part of one) or 'plan' (the short
    call that plans a deck written side by side). A change and a repair of a
    category deck keep today's guidance: the customer may have edited slides
    since, so its slots may no longer map, and the change is read as any
    deck's is (architecture 3.7). P2 adds the four branches of a paper.
    """
    from ..prompting import plan_guidance
    from ..provider import writing_guidance
    options = data.get('options') or {}
    if stage == 'plan':
        return plan_guidance('pptx', len(mine), options, total) + ' ' + PLAN_GUIDANCE
    return (writing_guidance(options, len(mine), 'pptx', first, total, include_layouts=False).rstrip()
            + ' ' + SLOT_GUIDANCE)


def cache_tag(data):
    """What a draft's category adds to its prompt cache key: ':<id>@<8 hex of the entry and its templates>', or ''.

    Every customer of one category version shares a prefix; an edit to the
    entry or a template moves the key, while VERSION stays as it is.
    """
    entry = of(data)
    return f':{entry.id}@{entry.digest}' if entry is not None else ''
