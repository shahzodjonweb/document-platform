"""What a category draft tells the model, beside what every draft is told (architecture 3.1, 3.2).

apps/studio/prompting.request_body builds every request. For a draft with a
category it adds what is here, and only then: a draft without one never
imports this module, so its request stays byte for byte today's
(tests/test_prompt_golden.py).

- `DECK`: how a category deck follows its slot list, said once for every deck
  category and language, after the layout guide;
- `DOCUMENT`: what a category paper is told in place of SYSTEM and
  DOCUMENT_RULES, said once for every paper category and language;
- `REVISION_NOTE`: what "more information" means in a category paper's change;
- `block(entry)`: the category's tone, its model rules and its field table,
  with each fixed part's write text, the same in every language and holding
  no customer text, so the cached prefix is shared by every customer of the
  category;
- `rows(data, mine, first)`: one row per section of this call, built from the
  catalogue at request time with headings in the document's language, so
  nothing the model reads about a slot or a part is stored in the draft;
- `guidance(...)`: writing_guidance for a category deck's new and plan calls,
  and for every call of a category paper (new, a later part, a change, a
  repair);
- `cache_tag(data)`: what a category adds to the prompt cache key, so a
  catalogue edit is never served a prefix cached for the old wording.
"""
import re

from ..provider import SAFETY
from . import skeleton
from .catalogue import LOCALES, of
from .skeleton import FACTS, cues_of, slots

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
# About 3,050 characters, one text for every paper category and language, sent
# in place of SYSTEM and DOCUMENT_RULES (architecture 3.1). Those say one
# section is one page and ask for developed paragraphs that open by introducing
# the topic, which is wrong for a form, a letter or a list part; so this says
# how a paper of parts is written, and opens with SAFETY, SYSTEM's own safety
# sentences word for word, so a paper is told them exactly as every other
# document is.
DOCUMENT = (
    'You write one paper of a fixed kind (a form, a letter, a study or a business paper) from a description '
    'written by the customer, directly in the target language named at the end of these instructions. Return '
    'structured JSON only.\n'
    + SAFETY + '\n'
    'The outline\'s sections are the parts of this one paper under fixed ids; parts gives one row per section of '
    'this call. Return every section, in order, with exactly its id, written as its row says: holds is what it '
    'holds; words is its length in words, lowest and highest, or max_words its most, never a page; layout is its '
    'shape. A heading the row gives is drawn by the template: leave the section\'s heading empty. Write a heading '
    'where the row\'s is empty, and none where it is null. A part whose holds says it is written only in some cases '
    'stays empty, heading and body, when this paper is not one. A part the rules say the template draws has no '
    'section: never write its words into another.\n'
    'When the description or the sources give a plan (Reja, План, Contents), its items are the chapter and '
    'subsection headings, word for word and in order: use as many instances of a repeating part as it lists, and '
    'leave the rest empty.\n'
    'The facts section holds one item per field of the field table that the description or the sources give: '
    'label is the field id, text the value copied from their words, in the form the field table or the part that '
    'draws it asks for. ____ is written only for a field marked if needed that this paper needs and they did not '
    'give; a field they did not give has no item otherwise.\n'
    'Never write a person, organisation, date, number, price, law, quotation or source that is not in the '
    'description or the sources; where a sentence needs a missing fact, write ____ in its place. A part whose row '
    'is grounded holds only what they say: where they say nothing for it, it keeps its formula with ____ for each '
    'missing fact, never filled from general knowledge.\n'
    'A table row is one item: the first cell in label, the last in value, the cells between in text joined by '
    '" | "; leave empty a cell of a column the row names computed, and write no header or total row. A list item is '
    'one entry in text, with a short name in label only where holds asks for one. The sources part holds one item '
    'per source the customer named or attached, described only from their words or the file\'s own text (author, '
    'title, place, year), never a file name; with none, it stays empty.\n'
    'Write only what the parts ask for: no other section, note or advice, and never a word on how the paper was '
    'made. Plain text: no markdown, and no bullet or dash at the start of a line, since items make a list.'
)
# Narrows REVISION_SYSTEM's "more information means facts, dates, names" for a
# category paper's change; it is sent after REVISION_SYSTEM.
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


def _field(item, paper=False):
    choices = f", {'|'.join(item['choices'])}" if item.get('choices') else ''
    # A paper's facts section carries ____ for these alone (DOCUMENT); no deck
    # field is if_needed, and a deck's block is left as it was reviewed.
    needed = ', if needed' if paper and item.get('missing') == 'if_needed' else ''
    return f"- {item['id']}: {_line(item['label']['en'])}, {item['kind']}{choices}{needed}"


def block(entry):
    """The category's block of the instructions: its tone, its model rules and its field table.

    The fields are grouped under each fixed part's write text: a fixed part has
    no section and no row, so this is the only place its rules (an ariza's
    dative addressee) reach the model. English, as the rest of the
    instructions are; the field labels too, since the block must read the same
    whatever language the document is in. Retired parts are left out.
    """
    raw = entry.raw
    paper = entry.service == 'pdf'
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
                lines.append(_field(fields[name], paper))
                placed.add(name)
    rest = [item for item in raw['fields'] if item['id'] not in placed]
    if rest:
        lines.append('Fields the customer may give (id: label, kind):' if not fixed else 'Other fields:')
        lines += [_field(item, paper) for item in rest]
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
    in the draft; a deck reads the slot from the id, and a paper its part (see
    paper_rows). Anything that is neither has no rows.
    """
    entry = of(data)
    if entry is None:
        return []
    if entry.service == 'pdf':
        return paper_rows(data, entry, mine)
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


def _instance(entry, use, length):
    """What a row says of a grouped part's instance: which it is, and whether it is always written."""
    if use.group is None:
        return ''
    size = (entry.raw.get('groups') or {}).get(use.group) or {}
    count = skeleton.instances(entry, use.group, length)
    if size.get('sized') != 'model':
        return f' Instance {use.instance} of {count} of the {use.group} group, on ground of its own.'
    if use.instance <= size.get('min', 1):
        return (f' Instance {use.instance} of up to {count} of the {use.group} group, always written; the plan or the '
                'material decides how many more are.')
    return (f' Instance {use.instance} of up to {count} of the {use.group} group: written only when the plan or the '
            'material has this many, else its heading and body stay empty.')


def _stale(entry, section_id):
    """The Use of a section the present cues no longer give (a draft seeded before a cue changed), or None."""
    part = entry.part(section_id)
    if part is None or part['kind'] not in skeleton.WRITTEN:
        return None
    instance = 1 if section_id == part['id'] else int(section_id.rsplit('_', 1)[1])
    return skeleton.Use(section_id, part, instance, part.get('group'))


# The layouts a paper's part may take on the wire: the ones its kinds are seeded
# with (skeleton._layout). The template places no photographs.
PAPER_LAYOUTS = ('text', 'list', 'table', 'callout')
# What the facts row holds; DOCUMENT says how it is written.
FACTS_HOLDS = 'The facts: one item per field of the field table the description or the sources give.'


def paper_rows(data, entry, mine):
    """The `parts` rows of a category paper's call: {id, part, kind, heading, holds, words | max_words, layout}.

    A section's part is found by its id (a later instance of a grouped part
    is `chapter_2`), so a later call, a change and a selected change are told
    the same rows for the same sections. The heading is the template's in the
    document's language where it draws one (the model leaves it unwritten),
    empty where the model writes it and null where there is none. `words` are
    a count paper's lowest and highest, `max_words` a ceiling paper's most
    (skeleton.words, from the paper's pages). A table row gives its column
    headers and those code computes, a list its most items, a grounded part
    says so. A part met again in the same call points at its first row instead
    of carrying its holds twice. The facts section has a row of its own.
    """
    locale = _locale(data)
    length = skeleton.pages(data)
    cues = cues_of(data)
    ceiling = entry.length['target'] == 'ceiling'
    uses = {use.section_id: use for use in skeleton.parts(entry, length, cues) if use.section_id}
    made, seen = [], {}
    for section in mine:
        section_id = str(section.get('id', ''))
        if section_id == FACTS:
            made.append({'id': FACTS, 'part': FACTS, 'kind': 'facts', 'heading': None, 'holds': FACTS_HOLDS,
                         'layout': 'list'})
            continue
        use = uses.get(section_id) or _stale(entry, section_id)
        if use is None:
            continue
        part = use.part
        mode = part['heading_mode']
        holds = _line(part.get('write'))
        if part['id'] in seen:
            holds = f"another instance of the part of {seen[part['id']]}, written as that row says."
        else:
            seen[part['id']] = section_id
        holds += _instance(entry, use, length)
        if part.get('total'):
            holds += ' Code adds the total row.'
        row = {'id': section_id, 'part': part['id'], 'kind': part['kind'],
               'heading': part['heading'][locale] if mode == 'fixed' else None if mode == 'none' else '',
               'holds': holds}
        low, high = skeleton.words(entry, use, length, cues)
        if ceiling:
            row['max_words'] = high
        else:
            row['words'] = [low, high]
        row['layout'] = skeleton._layout(part)
        if part.get('grounded'):
            row['grounded'] = True
        if part['kind'] == 'table' and part.get('columns'):
            names = [column[locale] for column in part['columns']]
            row['columns'] = names
            computed = sorted({rule['column'] for rule in part.get('computed', ()) if rule['column'] < len(names)})
            if computed:
                row['computed'] = [names[number] for number in computed]
        if part.get('max_items'):
            row['max_items'] = part['max_items']
        made.append(row)
    return made


# How a paper's parts are sized (architecture 3.3): a count the customer chose
# is filled, a ceiling never is. A fixed or derived length (an ariza, a test)
# is the form's own, and its rows' words say all there is to say.
COUNT_SIZES = ('Write each part to its words: together they fill the pages the customer asked for, and a part '
               'written short leaves the paper short.')
CEILING_SIZES = ('max_words is the most a part may hold, not a target: write what its holds and the customer\'s '
                 'material need, and nothing to fill the page.')


def _sizes(entry):
    if entry.length['target'] == 'ceiling':
        return [CEILING_SIZES]
    return [COUNT_SIZES] if entry.length['mode'] == 'count' else []


def _questions(count):
    return (f'Return {count} questions in the questions field, never in a section, as the category\'s rules say. A '
            'closed question has its options, and its answer copies the correct option word for word; an open '
            'question has no options, and its answer is the model answer. A question on a passage has the topic '
            'passage, and these come last among the closed questions. explanation is one sentence.')


def paper_guidance(data, entry, mine, first, total, stage, questions=0):
    """writing_guidance for every call of a category paper, in place of today's four branches.

    `stage` is 'new' (a new paper, or a later part of one when `first` is
    past its start), 'change' (a whole or selected change) or 'repair'.
    Today's say "one section is one page", "paragraphs of 5 to 6 sentences"
    and, for a change, how pages move and pictures are added; a paper's parts
    have their own sizes in their rows and never move. `questions` is the
    call's max_questions.
    """
    from ..prompting import edit_of
    count = len(mine)
    plural = 's' if count != 1 else ''
    last = first + count
    named = entry.raw.get('title') == 'label'
    if stage == 'repair':
        return (f'Write the {count} flagged section{plural} again as their rows in parts say, at their words or '
                'max_words. Change only what revision.request names; keep every other field of these sections word '
                'for word.')
    sizes = _sizes(entry)
    if stage == 'change':
        existing = len(data['content'].get('questions') or [])
        edit = edit_of(data)
        said = [f'Revise these {count} supplied section{plural}, keeping their ids, order and kinds: each is the part '
                'its row in parts names. Carry out every instruction of revision.request on the parts it affects and '
                'keep everything it does not touch word for word. A part the request changes is written at its row\'s '
                'size; no part is added or removed, and a heading the row gives stays unwritten. The facts section '
                'changes only where the request gives or corrects a fact.', *sizes]
        if count != total:
            said.append(f'This call revises sections {first + 1}-{last} of {total} only.')
        if edit.get('expand'):
            said.append('revision.request asks for more, fuller information: write more of what the description, the '
                        'change requests and the sources say on every part it affects, up to its words, never new '
                        'names, numbers, dates or sources.')
        if questions > existing:
            said.append(f'revision.request asks for questions. {_questions(questions)} Keep the existing questions '
                        'among them.')
        if edit.get('format'):
            said.append('The file format the request names is handled outside this change: change nothing for it.')
        said.append('Return the outline\'s title unchanged.' if named else
                    'Keep the title unless revision.request changes it.')
        return ' '.join(said)
    said = [f'Write the {count} section{plural} of this call, each as its row in parts says: the parts of a '
            f"{skeleton.pages(data)}-page paper, each at its own size, never a page each.", *sizes]
    if count != total:
        said.append(f'This call writes sections {first + 1}-{last} of {total}.'
                    + (' Continue from already_written: do not open the paper again or repeat what it covers.'
                       if first else '')
                    + (' Later calls write the rest, so do not conclude the paper here.' if last < total else
                       ' The paper ends with this call.'))
    if named or first:
        said.append('Return the outline\'s title unchanged.')
    else:
        said.append('title is the paper\'s title: its topic as the customer worded it, never the kind of paper or a '
                    'page count.')
    if questions:
        said.append(_questions(questions))
    return ' '.join(said)


def guidance(data, mine, first, total, stage, *, questions=0):
    """writing_guidance for a category draft's call.

    A paper's every call is paper_guidance's. A deck's new and plan calls are
    today's sizes and pictures, then its slots: `stage` is 'new' (a new deck
    or a later part of one) or 'plan' (the short call that plans a deck
    written side by side). A change and a repair of a category deck keep
    today's guidance: the customer may have edited slides since, so its slots
    may no longer map, and the change is read as any deck's is (architecture
    3.7).
    """
    entry = of(data)
    if entry is not None and entry.service == 'pdf':
        return paper_guidance(data, entry, mine, first, total, stage, questions)
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
