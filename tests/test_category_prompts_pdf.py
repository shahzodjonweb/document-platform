"""What a category paper tells the model (architecture 3.1 to 3.4), built from the real catalogue.

A category paper is told DOCUMENT in place of SYSTEM and DOCUMENT_RULES (a
change REVISION_SYSTEM and REVISION_NOTE), then its category's block, and
never the design guide: the template is the look. Its input names its parts
as rows with their words, its length as `pages` beside max_sections, and its
writing_guidance is the category's in all four of today's branches. Its calls
are cut by the pages their parts take and never written side by side. No
model is called: these are the bodies the provider would be sent. Drafts
without a category are pinned byte for byte by tests/test_prompt_golden.py.
"""
import copy
import json
import math
import re

import pytest

from apps.core.errors import DomainError
from apps.studio import doc_designs, language, pages as paging, prompting, provider
from apps.studio.categories import catalogue, skeleton
from apps.studio.categories import prompting as categories
from apps.studio.categories.catalogue import build, read
from apps.studio.domain import DOCUMENT, SLIDES
from apps.studio.prompting import REVISION_SYSTEM, SELECTED_REVISION
from apps.studio.provider import DOCUMENT_RULES, SAFETY, SYSTEM
from tests.test_category_prompts import deck
from tests.test_prompt_assembly import repairing, revised
from tests.test_provider_contract import CONFIG

LOCALES = ('uz', 'ru', 'en')
# Invented people and organisations only.
PROMPT = {
    'uz': 'Namuna litseyi direktoriga ariza: 12-noyabrdan 3 kunlik ta’til so‘rayman, oilaviy sabab bilan. '
          'Aziza Rahimova, ingliz tili o‘qituvchisi.',
    'ru': 'Заявление директору лицея «Намуна»: прошу отпуск на 3 дня с 12 ноября по семейным обстоятельствам. '
          'Азиза Рахимова, учитель английского языка.',
    'en': 'A request to the head of Example Lyceum: three days of leave from 12 November for family reasons. '
          'Aziza Rahimova, English teacher.',
}
# The caps of architecture 3.1 with the category block at its 5,000-character
# budget: DOCUMENT, the block and the largest language block for a new paper
# or a later part of one; REVISION_SYSTEM, REVISION_NOTE, the block,
# SELECTED_REVISION and the language block for a change or a repair. Measured
# again 2026-11-26, when DOCUMENT gained the specifics note and the language
# blocks longer stock-phrase lists (the new paper stack went from about 4,930
# to 5,420 characters).
CAPS = {'new': 10_500, 'part': 10_500, 'change': 12_000, 'selected': 12_000, 'repair': 12_000}


def papers():
    return [entry for entry in catalogue._catalogue().entries.values()
            if entry.service == 'pdf' and entry.status != catalogue.RETIRED]


def paper(entry, locale='uz', prompt=None, length=None, **options):
    """A new category paper's draft as the domain makes one: its length, its questions, its seeded parts."""
    prompt = prompt or PROMPT[locale]
    cues = skeleton.cues(entry, prompt, has_files=False)
    questions = min(entry.raw['questions']['default'], entry.raw['questions']['max'])
    if length is None:
        length = skeleton.length(entry, cues=cues, ceiling=35, questions=questions)
    return {'output_locale': locale, 'prompt': prompt, 'source_text': '', 'excerpts': [],
            'options': {'question_count': questions, 'length': length, 'requested_pages': None, 'image_cap': 0,
                        'category': entry.id, **options},
            'output_format': 'pdf',
            'content': {'title': 'Untitled document', 'sections': skeleton.seed(entry, length, cues), 'questions': [],
                        'citations': []}}


def bodies(entry, locale='uz', prompt=None):
    """The request body of every stage of one category paper, in one language."""
    data = paper(entry, locale, prompt)
    ids = [section['id'] for section in data['content']['sections']]
    count = len(ids)
    return {
        'new': provider.request_body(CONFIG, data, DOCUMENT),
        'part': provider.request_body(CONFIG, data, DOCUMENT, (min(1, count - 1), count)),
        'change': provider.request_body(CONFIG, revised(data), DOCUMENT),
        'selected': provider.request_body(CONFIG, revised(data, ids[-1:]), DOCUMENT),
        'repair': provider.request_body(CONFIG, repairing(data, ids[-1:]), DOCUMENT),
    }


def sent(body):
    return json.loads(body['input'])


def sentences(text):
    return [part for part in re.split(r'(?<=\.) (?=[A-Z])', text) if part]


def files():
    return copy.deepcopy(read())


def prose(part_id, **more):
    return {'id': part_id, 'kind': 'prose', 'heading': None, 'heading_mode': 'model', 'need': 'required',
            'write': f'Write the {part_id} from the brief.', 'block': 'paragraph', **more}


@pytest.fixture
def long_paper(monkeypatch):
    """A paper that fills its count, made of the ariza: an introduction, chapters, notes, a price table, sources.

    The ariza's own parts stay (its template draws them) at a small share
    each; what follows them is the paper.
    """
    entries, templates, index = files()
    raw = entries['pdf.xat.ariza']
    raw['length'] = {'unit': 'pages', 'mode': 'count', 'target': 'count', 'default': 10, 'min': 2, 'max': 30}
    raw['quality'], raw['fill'], raw['title'] = 'repair', True, 'model'
    raw['groups'] = {'chapter': {'min': 1, 'max': 3, 'sized': 'model'},
                     'note': {'min': 1, 'max': 4, 'sized': 'length'}}
    for part in raw['parts']:
        part['share'] = 0.01
    raw['parts'] += [
        prose('intro', heading={'uz': 'Kirish', 'ru': 'Введение', 'en': 'Introduction'}, heading_mode='fixed',
              share=0.1, elastic=True),
        prose('chapter_head', group='chapter', share=0.3, elastic=True),
        prose('chapter_body', group='chapter', heading_mode='none', share=0.3, elastic=True),
        {**prose('note', group='note', share=0.08), 'kind': 'list', 'max_items': 5},
        {**prose('prices', share=0.05, grounded=True, heading_mode='none'), 'kind': 'table',
         'columns': [{'uz': 'Nomi', 'ru': 'Название', 'en': 'Item'}, {'uz': 'Soni', 'ru': 'Количество', 'en': 'Qty'},
                     {'uz': 'Narxi', 'ru': 'Цена', 'en': 'Price'}, {'uz': 'Jami', 'ru': 'Сумма', 'en': 'Total'}],
         'computed': [{'column': 3, 'op': 'product', 'of': [1, 2]}], 'total': [3]},
        {**prose('sources', share=0.02, when='cue:sources', heading_mode='fixed',
                 heading={'uz': 'Foydalanilgan adabiyotlar', 'ru': 'Список литературы', 'en': 'References'}),
         'kind': 'sources'},
    ]
    built = build(entries, templates, index)
    monkeypatch.setattr(catalogue, '_catalogue', lambda: built)
    return built.entries['pdf.xat.ariza']


# ---------------------------------------------------------------- safety and the stacks


@pytest.mark.parametrize('entry', papers(), ids=lambda entry: entry.id)
def test_every_new_category_paper_body_says_safety_word_for_word(entry):
    for locale in LOCALES:
        stages = bodies(entry, locale)
        for stage in ('new', 'part'):
            for sentence in sentences(SAFETY):
                assert sentence in stages[stage]['instructions'], (stage, locale, sentence)
                assert sentence in SYSTEM
        # A change is told REVISION_SYSTEM's own never-invent rule, narrowed by REVISION_NOTE.
        for stage in ('change', 'selected', 'repair'):
            assert 'Do not invent facts or citations' in stages[stage]['instructions']
            assert 'never new names, numbers, dates or sources' in stages[stage]['instructions']


@pytest.mark.parametrize('entry', papers(), ids=lambda entry: entry.id)
def test_a_category_paper_is_told_its_stack_in_the_order_of_architecture_3_1(entry):
    block = categories.block(entry)
    for locale in LOCALES:
        stages = bodies(entry, locale)
        tail = language.instructions(locale)
        assert stages['new']['instructions'] == stages['part']['instructions'] == '\n'.join(
            [categories.DOCUMENT, block, tail])
        assert stages['change']['instructions'] == '\n'.join([REVISION_SYSTEM, categories.REVISION_NOTE, block, tail])
        assert stages['selected']['instructions'] == stages['repair']['instructions'] == '\n'.join(
            [REVISION_SYSTEM, categories.REVISION_NOTE, block, SELECTED_REVISION, tail])


def test_a_paper_never_reads_system_document_rules_or_the_design_guide_whatever_its_brief_asks():
    entry = catalogue.get('pdf.xat.ariza')
    data = paper(entry, 'en', wants_layouts=True, wants_design=True)
    change = revised(data)
    change['revision']['edit'] = {'redesign': True}
    for body in (provider.request_body(CONFIG, data, DOCUMENT), provider.request_body(CONFIG, change, DOCUMENT)):
        instructions = body['instructions']
        assert SYSTEM not in instructions and DOCUMENT_RULES not in instructions
        for layouts, design in ((True, True), (True, False), (False, True)):
            guide = doc_designs.reference(layouts, design, 0)
            assert not guide or guide not in instructions
        assert 'design' not in body['text']['format']['schema']['properties']


@pytest.mark.parametrize('entry', papers(), ids=lambda entry: entry.id)
def test_paper_instructions_are_equal_across_languages_and_hold_no_customer_text(entry):
    by_locale = {locale: bodies(entry, locale) for locale in LOCALES}
    other = bodies(entry, 'uz', prompt='“Yashil Vodiy” fermer xo‘jaligi raisiga ariza: suv tejash bo‘yicha taklif.')
    for stage in CAPS:
        prefixes = {by_locale[locale][stage]['instructions'][:-len(language.instructions(locale))]
                    for locale in LOCALES}
        assert len(prefixes) == 1, stage
        assert other[stage]['instructions'] == by_locale['uz'][stage]['instructions'], stage
        for words in ('Namuna', 'Намуна', 'Example Lyceum', 'Rahimova', 'Yashil'):
            assert words not in by_locale['uz'][stage]['instructions'], (stage, words)
        assert len({by_locale[locale][stage]['prompt_cache_key'] for locale in LOCALES}) == 1, stage


def test_a_papers_field_table_marks_the_fields_that_may_be_left_blank_and_a_decks_is_unchanged():
    ariza = catalogue.get('pdf.xat.ariza')
    block = categories.block(ariza)
    for item in ariza.fields:
        line = next(line for line in block.split('\n') if line.startswith(f"- {item['id']}: "))
        assert line.endswith(', if needed') == (item.get('missing') == 'if_needed'), item['id']
    assert 'if needed' in categories.DOCUMENT
    for entry in catalogue._catalogue().entries.values():
        if entry.service == 'slides':
            assert ', if needed' not in categories.block(entry), entry.id


# ---------------------------------------------------------------- the input


def test_a_paper_says_its_pages_beside_its_parts_and_no_photographs_or_subtopics():
    entry = catalogue.get('pdf.xat.ariza')
    data = paper(entry, 'en', prompt=PROMPT['en'] + '\n1. Dates\n2. Reason\n3. Contact')
    data['options']['image_cap'] = 3
    user = sent(provider.request_body(CONFIG, data, DOCUMENT))
    assert user['options'] == {'pages': 1, 'question_count': 0}
    assert user['max_sections'] == len(data['content']['sections'])
    assert user['category'] == 'pdf.xat.ariza'
    assert 'required_subtopics' not in user
    plain = copy.deepcopy(data)
    del plain['options']['category']
    assert 'required_subtopics' in sent(provider.request_body(CONFIG, plain, DOCUMENT))


def test_ariza_rows_name_each_written_part_with_its_most_words_and_its_heading_in_the_documents_language():
    entry = catalogue.get('pdf.xat.ariza')
    for locale in LOCALES:
        data = paper(entry, locale)
        rows = sent(provider.request_body(CONFIG, data, DOCUMENT))['parts']
        assert [row['id'] for row in rows] == [section['id'] for section in data['content']['sections']]
        assert rows[0] == {'id': 'facts', 'part': 'facts', 'kind': 'facts', 'heading': None,
                           'holds': categories.FACTS_HOLDS, 'layout': 'list'}
        cues = skeleton.cues_of(data)
        uses = {use.section_id: use for use in skeleton.parts(entry, 1, cues)}
        for row in rows[1:]:
            part = entry.part(row['id'])
            assert part['kind'] != 'fixed', 'a part the template draws has no row'
            assert row['part'] == part['id'] and row['kind'] == part['kind']
            assert row['holds'].startswith(' '.join(part['write'].split()))
            # An ariza is a ceiling paper: a most, never a target.
            assert 'words' not in row and row['max_words'] == skeleton.words(entry, uses[row['id']], 1, cues)[1]
            assert row['layout'] == skeleton._layout(part)
            assert row.get('grounded', False) == bool(part.get('grounded'))
            assert row['heading'] == (part['heading'][locale] if part['heading_mode'] == 'fixed' else
                                      None if part['heading_mode'] == 'none' else '')
            if part.get('max_items'):
                assert row['max_items'] == part['max_items']


def test_a_count_papers_rows_give_word_targets_instances_columns_and_computed_cells(long_paper):
    data = paper(long_paper, 'ru', length=12)
    rows = {row['id']: row for row in sent(provider.request_body(CONFIG, data, DOCUMENT))['parts']}
    cues = skeleton.cues_of(data)
    for use in skeleton.parts(long_paper, 12, cues):
        if use.section_id:
            assert rows[use.section_id]['words'] == list(skeleton.words(long_paper, use, 12, cues))
            assert 'max_words' not in rows[use.section_id]
    assert rows['intro']['heading'] == 'Введение' and rows['chapter_head']['heading'] == ''
    assert rows['chapter_body']['heading'] is None
    # A model-sized group: the first instance is always written, later ones only as the plan or material goes.
    assert 'always written' in rows['chapter_head']['holds']
    assert 'Instance 3 of up to 3 of the chapter group: written only when' in rows['chapter_head_3']['holds']
    # A later instance in the same call points at the first instead of repeating its holds.
    assert rows['chapter_head_2']['holds'].startswith('another instance of the part of chapter_head')
    assert rows['note']['holds'].startswith('Write the note from the brief.')
    assert 'Instance 1 of 2 of the note group' in rows['note']['holds'] and rows['note']['max_items'] == 5
    prices = rows['prices']
    assert prices['columns'] == ['Название', 'Количество', 'Цена', 'Сумма'] and prices['computed'] == ['Сумма']
    assert prices['layout'] == 'table' and prices['grounded'] is True
    assert prices['holds'].endswith('Code adds the total row.')
    assert 'sources' not in rows, 'no reference list unless sources were attached or named'
    with_files = paper(long_paper, 'uz', length=12)
    with_files['source_ids'] = ['an-attached-file']
    with_files['content']['sections'] = skeleton.seed(long_paper, 12, skeleton.cues_of(with_files))
    rows = {row['id']: row for row in sent(provider.request_body(CONFIG, with_files, DOCUMENT))['parts']}
    assert rows['sources']['heading'] == 'Foydalanilgan adabiyotlar' and rows['sources']['kind'] == 'sources'


def test_a_section_the_present_cues_no_longer_give_still_has_its_row(long_paper):
    data = paper(long_paper, 'en', length=12)
    data['content']['sections'].append({'id': 'sources', 'heading': '', 'body': '', 'notes': '', 'layout': 'list',
                                        'items': []})
    data['content']['sections'].append({'id': 'note_4', 'heading': '', 'body': '', 'notes': '', 'layout': 'list',
                                        'items': []})
    rows = {row['id']: row for row in sent(provider.request_body(CONFIG, data, DOCUMENT))['parts']}
    assert rows['sources']['heading'] == 'References' and rows['sources']['kind'] == 'sources'
    assert rows['note_4']['part'] == 'note' and 'Instance 4 of 2 of the note group' in rows['note_4']['holds']


def test_a_change_and_a_repair_keep_the_rows_a_decks_change_drops():
    entry = catalogue.get('pdf.xat.ariza')
    data = paper(entry, 'en')
    new = sent(provider.request_body(CONFIG, data, DOCUMENT))['parts']
    assert sent(provider.request_body(CONFIG, revised(data), DOCUMENT))['parts'] == new
    assert sent(provider.request_body(CONFIG, revised(data, ['request']), DOCUMENT))['parts'] == \
        [row for row in new if row['id'] == 'request']
    assert sent(provider.request_body(CONFIG, repairing(data, ['request']), DOCUMENT))['parts'] == \
        [row for row in new if row['id'] == 'request']
    assert 'parts' not in sent(provider.request_body(CONFIG, revised(deck(catalogue.get('slides.himoya'))), SLIDES))


def test_a_structural_change_on_a_paper_moves_nothing():
    entry = catalogue.get('pdf.xat.ariza')
    data = paper(entry, 'en')
    change = revised(data)
    change['revision'].update(before=copy.deepcopy(data['content']),
                              edit={'parts': ['conclusion'], 'delta': 1, 'structural': True})
    user = sent(provider.request_body(CONFIG, change, DOCUMENT))
    assert 'document_as_it_stands' not in user and 'slot_plan' not in user
    assert 'merging' not in user['writing_guidance'] and 'its own with real content' not in user['writing_guidance']


# ---------------------------------------------------------------- the four guidance branches


def test_a_new_count_paper_is_told_its_rows_sizes_and_title_not_todays_page_guidance(long_paper):
    count = paper(long_paper, 'en', length=12)
    said = sent(provider.request_body(CONFIG, count, DOCUMENT))['writing_guidance']
    assert said.startswith(f"Write the {len(count['content']['sections'])} sections of this call, each as its row")
    assert '12-page paper' in said and categories.COUNT_SIZES in said and categories.CEILING_SIZES not in said
    assert "title is the paper's title" in said
    for today in ('Each section is one page', 'paragraphs of varied length', 'paragraphs of 5 to 6 sentences',
                  'This call writes sections'):
        assert today not in said


def test_a_ceiling_paper_is_told_its_most_and_a_test_its_questions():
    ariza = sent(provider.request_body(CONFIG, paper(catalogue.get('pdf.xat.ariza'), 'en'), DOCUMENT))
    assert categories.CEILING_SIZES in ariza['writing_guidance']
    assert "Return the outline's title unchanged." in ariza['writing_guidance']
    assert 'questions field' not in ariza['writing_guidance']
    test = catalogue.get('pdf.test')
    user = sent(provider.request_body(CONFIG, paper(test, 'en', prompt='A 7th grade biology test on the cell'),
                                      DOCUMENT))
    assert user['max_questions'] == 20 and 'Return 20 questions in the questions field' in user['writing_guidance']
    assert 'its answer copies the correct option word for word' in user['writing_guidance']
    # A test's pages follow its questions: nothing to fill and no most to keep under.
    assert categories.COUNT_SIZES not in user['writing_guidance']
    assert categories.CEILING_SIZES not in user['writing_guidance']


def test_a_later_part_continues_and_only_the_last_one_ends_the_paper(long_paper):
    data = paper(long_paper, 'en', length=30)
    spans = skeleton.spans(data)
    assert len(spans) >= 3
    said = [sent(provider.request_body(CONFIG, data, DOCUMENT, span))['writing_guidance'] for span in spans]
    total = len(data['content']['sections'])
    assert f'This call writes sections 1-{spans[0][1]} of {total}. Later calls write the rest' in said[0]
    assert 'already_written' not in said[0]
    for text, (first, last) in zip(said[1:], spans[1:]):
        assert f'This call writes sections {first + 1}-{last} of {total}. Continue from already_written' in text
        assert "Return the outline's title unchanged." in text
    assert said[-1].count('The paper ends with this call.') == 1 and 'Later calls' not in said[-1]
    # Not today's part guidance, which speaks of covers, closing slides and subtopics.
    assert not any('closing slide' in text or 'required subtopics' in text for text in said)


def test_a_change_is_told_its_parts_keep_their_sizes_and_more_means_more_of_the_customers_material():
    entry = catalogue.get('pdf.xat.ariza')
    change = revised(paper(entry, 'en'))
    change['revision']['edit'] = {'expand': True, 'format': 'docx'}
    said = sent(provider.request_body(CONFIG, change, DOCUMENT))['writing_guidance']
    assert said.startswith('Revise these 4 supplied sections, keeping their ids, order and kinds')
    assert 'never new names, numbers, dates or sources' in said and 'handled outside this change' in said
    assert "Return the outline's title unchanged." in said and categories.CEILING_SIZES in said
    for today in ('paragraphs of 5 to 6 sentences', 'specific facts, dates, names', 'pictures'):
        assert today not in said
    test = catalogue.get('pdf.test')
    data = paper(test, 'en', prompt='A 7th grade biology test on the cell')
    asked = revised(data)
    assert 'Keep the existing questions among them' in sent(provider.request_body(CONFIG, asked, DOCUMENT))[
        'writing_guidance']
    data['content']['questions'] = [{'id': f'q{n}', 'stem': 'S', 'options': ['A', 'B'], 'answer': 'A',
                                     'explanation': '', 'topic': '', 'marks': 1} for n in range(20)]
    assert 'questions field' not in sent(provider.request_body(CONFIG, revised(data), DOCUMENT))['writing_guidance']


def test_a_repair_writes_the_flagged_parts_again_at_their_sizes():
    entry = catalogue.get('pdf.xat.ariza')
    said = sent(provider.request_body(CONFIG, repairing(paper(entry, 'en'), ['request']), DOCUMENT))[
        'writing_guidance']
    assert said == ('Write the 1 flagged section again as their rows in parts say, at their words or max_words. '
                    'Change only what revision.request names; keep every other field of these sections word for '
                    'word.')


# ---------------------------------------------------------------- the wire schema


def test_a_papers_wire_schema_has_layouts_and_items_but_no_columns_photos_or_design():
    ariza = catalogue.get('pdf.xat.ariza')
    for data in (paper(ariza, 'en'), paper(ariza, 'en', wants_layouts=True, wants_design=True)):
        for body in (provider.request_body(CONFIG, data, DOCUMENT), provider.request_body(CONFIG, revised(data),
                                                                                          DOCUMENT)):
            properties = body['text']['format']['schema']['properties']
            section = properties['sections']['items']['properties']
            # A new paper lists each part's concrete material before its body (tests/test_section_specifics.py).
            assert set(section) == {'id', 'heading', 'body', 'layout', 'items'} | (
                {'specifics'} if 'revision' not in json.loads(body['input']) else set())
            assert section['layout']['enum'] == list(categories.PAPER_LAYOUTS)
            assert set(section['items']['items']['properties']) == {'label', 'text', 'value'}
            assert 'design' not in properties and 'questions' not in properties
    test = paper(catalogue.get('pdf.test'), 'en', prompt='A 7th grade biology test on the cell')
    assert 'questions' in provider.request_body(CONFIG, test, DOCUMENT)['text']['format']['schema']['properties']
    # Every layout a paper is seeded with may come back, and each is a document layout.
    assert {skeleton._layout({'kind': kind, 'block': block}) for kind, block in (
        ('prose', 'paragraph'), ('prose', 'callout'), ('list', 'list'), ('table', 'table'), ('sources', 'list'))} \
        == set(categories.PAPER_LAYOUTS) <= set(doc_designs.LAYOUT_IDS)


def test_a_reply_to_a_paper_is_hydrated_without_columns_or_photos():
    entry = catalogue.get('pdf.xat.ariza')
    data = paper(entry, 'en')
    raw = {'title': 'T', 'answer_supported': True, 'sections': [
        {'id': 'request', 'heading': '', 'body': 'I ask.', 'layout': 'text', 'items': []}]}
    section = prompting.canonical(raw, data)['sections'][0]
    assert section['columns'] == [] and section['image_query'] == '' and section['layout'] == 'text'


# ---------------------------------------------------------------- calls and budgets


def test_a_paper_is_never_written_side_by_side_and_is_cut_by_its_pages(long_paper, monkeypatch):
    data = paper(long_paper, 'uz', length=30)
    config = {**CONFIG, 'parallel_parts': True}
    assert len(data['content']['sections']) >= provider.PARALLEL_FROM
    assert not provider.parallel_wanted(config, data, DOCUMENT)
    plain = copy.deepcopy(data)
    del plain['options']['category']
    assert provider.parallel_wanted(config, plain, DOCUMENT)
    monkeypatch.setattr(provider, '_plan', lambda *args, **kwargs: pytest.fail('a paper is never planned'))
    calls = []

    def call(config, effective, feature, key, *, token_limit, span=None, **rest):
        calls.append(span)
        first, last = span or (0, len(effective['content']['sections']))
        return ({'title': 'T', 'sections': copy.deepcopy(effective['content']['sections'][first:last]), 'citations': [],
                 'questions': [], 'answer_supported': True, 'design': ''}, {'input_tokens': 1, 'output_tokens': 1})
    monkeypatch.setattr(provider, '_call', call)
    merged, _ = provider.generate(config, data, DOCUMENT, 'not-a-job', token_limit=120_000)
    assert calls == skeleton.spans(data) and calls != paging.batches(len(data['content']['sections']))
    assert [section['id'] for section in merged['sections']] == [s['id'] for s in data['content']['sections']]


def test_each_call_of_a_paper_is_given_the_tokens_of_the_pages_its_parts_take(long_paper):
    data = paper(long_paper, 'en', length=30)
    for first, last in skeleton.spans(data):
        body = provider.request_body(CONFIG, data, DOCUMENT, (first, last))
        assert body['max_output_tokens'] == paging.call_tokens(skeleton.pages_in(data, first, last))
    test = paper(catalogue.get('pdf.test'), 'en', prompt='A 7th grade biology test on the cell')
    assert provider.request_body(CONFIG, test, DOCUMENT)['max_output_tokens'] == paging.call_tokens(
        skeleton.pages_in(test, 0, len(test['content']['sections'])), 20)
    # A selected change is sized by the pages of the parts it rewrites.
    chosen = ('chapter_head', 'chapter_body')
    selected = revised(data, list(chosen))
    taken = sum(size for section_id, size in skeleton._section_pages(data) if section_id in chosen)
    assert provider.request_body(CONFIG, selected, DOCUMENT)['max_output_tokens'] == paging.call_tokens(
        max(1, math.ceil(taken - 1e-9)))


def test_the_lease_covers_every_span_of_a_paper_and_one_more(long_paper):
    data = paper(long_paper, 'en', length=30)
    spans = skeleton.spans(data)
    times = [min(provider.CALL_TIMEOUT_CEILING, 60 + paging.call_tokens(skeleton.pages_in(data, first, last))
                 // provider.TOKENS_PER_SECOND) for first, last in spans]
    assert provider.call_budget(30, data) == sum(times) + max(times)
    assert provider.call_budget(30, data) >= len(spans) * 60
    # A Boshqa document and a deck are budgeted as ever, whatever data says.
    plain = copy.deepcopy(data)
    del plain['options']['category']
    assert provider.call_budget(30, plain) == provider.call_budget(30)
    himoya = deck(catalogue.get('slides.himoya'))
    assert provider.call_budget(10, himoya) == provider.call_budget(10)


def test_a_one_call_paper_is_one_call_and_a_tests_questions_count():
    ariza = paper(catalogue.get('pdf.xat.ariza'), 'en')
    assert provider.call_budget(1, ariza) == provider.call_budget(1)
    test = paper(catalogue.get('pdf.test'), 'en', prompt='A 7th grade biology test on the cell')
    pages = test['options']['length']
    assert provider.call_budget(pages, test) == min(provider.CALL_TIMEOUT_CEILING, 60 + paging.call_tokens(
        skeleton.pages_in(test, 0, len(test['content']['sections'])), 20) // provider.TOKENS_PER_SECOND)


def test_the_largest_body_of_a_paper_is_one_of_its_spans(long_paper):
    data = paper(long_paper, 'ru', length=30)
    change = revised(data)
    spans = provider.spans_of(change)
    assert spans == skeleton.spans(data) and len(spans) > 1
    sent_bodies = [provider.request_body(CONFIG, change, DOCUMENT, span) for span in spans]
    assert provider.largest_body(CONFIG, change, DOCUMENT) == max(sent_bodies, key=provider.body_tokens)
    selected = revised(data, ['intro'])
    assert provider.spans_of(selected) == [(0, 1)]
    assert provider.largest_body(CONFIG, selected, DOCUMENT) == provider.request_body(CONFIG, selected, DOCUMENT)


def test_an_unknown_paper_category_fails_before_any_call(monkeypatch):
    monkeypatch.setattr(provider.urllib.request, 'build_opener', lambda _: pytest.fail('no request may be sent'))
    data = paper(catalogue.get('pdf.xat.ariza'), 'en')
    data['options']['category'] = 'pdf.gone'
    for attempt in (lambda: provider.request_body(CONFIG, data, DOCUMENT), lambda: provider.call_budget(1, data),
                    lambda: provider._call(CONFIG, data, DOCUMENT, 'key', token_limit=120_000)):
        with pytest.raises(DomainError) as raised:
            attempt()
        assert raised.value.code == 'category_unknown'


@pytest.mark.parametrize('entry', papers(), ids=lambda entry: entry.id)
def test_every_paper_stage_meets_its_cap_with_the_block_at_its_budget(entry):
    """The stack around the block is measured; a draft entry's block is held to its budget by readiness."""
    block = len(categories.block(entry))
    for locale in LOCALES:
        for stage, body in bodies(entry, locale).items():
            size = len(body['instructions'])
            assert size - block + catalogue.BLOCK_BUDGET <= CAPS[stage], (stage, locale, size - block)
            if entry.status == catalogue.READY:
                assert size <= CAPS[stage], (stage, locale, size)
    assert len(categories.DOCUMENT) <= 3_600


def test_a_ready_paper_block_within_budget_keeps_every_stage_under_its_cap(monkeypatch):
    entry = catalogue.get('pdf.xat.ariza')
    monkeypatch.setattr(categories, 'block', lambda entry: 'x' * catalogue.BLOCK_BUDGET)
    for locale in LOCALES:
        for stage, body in bodies(entry, locale).items():
            assert len(body['instructions']) <= CAPS[stage], (stage, locale, len(body['instructions']))
