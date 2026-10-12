"""How every model call's instructions and input are put together.

The instructions are built from separate blocks joined by newlines, always in
the same order: the stage's system text (writing, planning or revising), the
rules for a document or for a deck (for writing and repairing, never for
planning), the layout and design catalogues, the selected-section note, and the
language block last. Two things depend on that
order. The provider caches a request's prefix, so everything before the
language block must be byte-for-byte the same for every customer and every
language; and the language block, said once at the end, is what every stage —
outline, writing, change, selected change, top-up — is told about the
language, so they can never disagree.

The input carries the resolved language as fields (output_locale,
output_language, output_script) and the subtopics the customer listed, read
from the customer's own brief. No model is called here: these are the request
bodies the provider would be sent.
"""
import copy
import json
import os
import re

import pytest

from apps.studio import (deck_designs, doc_designs, filling, language, layouts, outlines, pages, prompting,
                         provider, topics)
from apps.studio.domain import DOCUMENT, SLIDES
from apps.studio.prompting import OUTLINE_SYSTEM, REVISION_SYSTEM, SELECTED_REVISION
from apps.studio.provider import DECK_RULES, DOCUMENT_RULES, SYSTEM, writing_guidance
from tests.test_provider_contract import CONFIG, draft

LOCALES = ('en', 'uz', 'ru')
STAGES = ('outline', 'final', 'revision', 'selected', 'repair', 'expand')
WIRE = {'en': ('en', 'English', 'latin'), 'uz': ('uz', 'Uzbek', 'latin'), 'ru': ('ru', 'Russian', 'cyrillic')}
CYRILLIC = re.compile('[Ѐ-ԯ]')


def revised(data, selected=None):
    """`data` as a change request against itself: whole, or for the `selected` section ids."""
    change = copy.deepcopy(data)
    change['revision'] = {'request': 'Make the second section clearer.', 'original_prompt': data['prompt']}
    if selected:
        change['revision'].update(selected_section_ids=selected, base_content=copy.deepcopy(data['content']))
    change['prompt'] = change['revision']['request']
    return change


def repairing(data, ids):
    """`data` as apps/studio/quality.repair hands it to the provider for the flagged `ids`."""
    fix = copy.deepcopy(data)
    fix['revision'] = {'request': f'Quality repair of the pages with these ids: {", ".join(ids)}.',
                       'selected_section_ids': ids, 'base_content': copy.deepcopy(data['content']),
                       'original_prompt': data.get('revision', {}).get('original_prompt') or data['prompt']}
    fix['_stage'] = 'repair'
    return fix


def bodies(locale, output_format='pptx', **options):
    """The request body of every stage, for one draft in one language."""
    feature = SLIDES if output_format == 'pptx' else DOCUMENT
    data = draft(5, output_format)
    data['output_locale'] = locale
    data['options'].update(options)
    return {
        'outline': provider.request_body(CONFIG, outlines._payload(data), 'ai.outline'),
        'final': provider.request_body(CONFIG, data, feature),
        'revision': provider.request_body(CONFIG, revised(data), feature),
        'selected': provider.request_body(CONFIG, revised(data, ['s2']), feature),
        'repair': provider.request_body(CONFIG, repairing(data, ['s2', 's4']), feature),
        'expand': filling.request_body(CONFIG, data, data['content'], 400),
    }


def sent(body):
    return json.loads(body['input'])


# --- The order of the blocks -------------------------------------------------------

@pytest.mark.parametrize('stage,output_format,options,expected', [
    ('final', 'pptx', {'image_cap': 6}, lambda block: [
        SYSTEM, DECK_RULES, layouts.reference(True), deck_designs.reference(True), block]),
    ('final', 'pptx', {}, lambda block: [
        SYSTEM, DECK_RULES, layouts.reference(False), deck_designs.reference(False), block]),
    # A design already chosen (by the outline or the customer) is not offered again.
    ('final', 'pptx', {'image_cap': 6, 'template_style': {'deck_design': 'gala'}}, lambda block: [
        SYSTEM, DECK_RULES, layouts.reference(True), block]),
    # An outline plans: it is not given the rules for writing the finished slides or pages.
    ('outline', 'pptx', {'image_cap': 6}, lambda block: [
        OUTLINE_SYSTEM, layouts.reference(True), deck_designs.reference(True), block]),
    ('outline', 'pptx', {'image_cap': 6, 'template_style': {'deck_design': 'gala'}}, lambda block: [
        OUTLINE_SYSTEM, layouts.reference(True), block]),
    ('final', 'pdf', {}, lambda block: [SYSTEM, DOCUMENT_RULES, block]),
    ('final', 'pdf', {'wants_layouts': True, 'wants_design': True}, lambda block: [
        SYSTEM, DOCUMENT_RULES, doc_designs.reference(True, True, 0), block]),
    ('outline', 'pdf', {'wants_layouts': True}, lambda block: [
        OUTLINE_SYSTEM, doc_designs.reference(True, False, 0), block]),
    # A change is told how a page or slide is written, and a deck's change the layouts it may use: told only
    # to keep things as they were, it added a page as a heading and a picture nowhere.
    ('revision', 'pptx', {'image_cap': 6}, lambda block: [
        REVISION_SYSTEM, DECK_RULES, layouts.reference(True), block]),
    ('selected', 'pptx', {'image_cap': 6}, lambda block: [
        REVISION_SYSTEM, DECK_RULES, layouts.reference(True), SELECTED_REVISION, block]),
    ('revision', 'pdf', {'wants_layouts': True}, lambda block: [
        REVISION_SYSTEM, DOCUMENT_RULES, doc_designs.reference(True, False, 0), block]),
    # A change keeps the document's design unless it asks for a new look, so it is not shown the designs.
    ('revision', 'pdf', {'wants_layouts': True, 'wants_design': True}, lambda block: [
        REVISION_SYSTEM, DOCUMENT_RULES, doc_designs.reference(True, False, 0), block]),
    ('selected', 'pdf', {'wants_layouts': True}, lambda block: [
        REVISION_SYSTEM, DOCUMENT_RULES, doc_designs.reference(True, False, 0), SELECTED_REVISION, block]),
    # A repair writes flagged sections again, often whole, so it is told how one is written.
    ('repair', 'pptx', {'image_cap': 6}, lambda block: [
        REVISION_SYSTEM, DECK_RULES, layouts.reference(True), SELECTED_REVISION, block]),
    ('repair', 'pptx', {}, lambda block: [
        REVISION_SYSTEM, DECK_RULES, layouts.reference(False), SELECTED_REVISION, block]),
    ('repair', 'pdf', {}, lambda block: [REVISION_SYSTEM, DOCUMENT_RULES, SELECTED_REVISION, block]),
    ('repair', 'pdf', {'wants_layouts': True}, lambda block: [
        REVISION_SYSTEM, DOCUMENT_RULES, doc_designs.reference(True, False, 0), SELECTED_REVISION, block]),
])
@pytest.mark.parametrize('locale', LOCALES)
def test_instructions_are_the_stage_rules_catalogues_and_the_language_block_in_that_order(
        stage, output_format, options, expected, locale):
    instructions = bodies(locale, output_format, **options)[stage]['instructions']
    assert instructions == '\n'.join(expected(language.instructions(locale)))


def test_the_language_block_is_always_the_last_line():
    for locale in LOCALES:
        for output_format in ('pdf', 'pptx'):
            for stage, body in bodies(locale, output_format).items():
                last = body['instructions'].split('\n')[-1]
                assert last == language.instructions(locale), (locale, output_format, stage)


def test_the_selected_section_note_stands_on_its_own_line():
    """It used to be glued on with no space at all: "…standard Uzbek spelling.This is a selected-section…"."""
    for locale in LOCALES:
        for output_format in ('pdf', 'pptx'):
            stages = bodies(locale, output_format, wants_layouts=True)
            selected = stages['selected']['instructions']
            assert '\n' + SELECTED_REVISION + '\n' in selected
            assert selected.count(SELECTED_REVISION) == 1
            for stage in ('outline', 'final', 'revision', 'expand'):
                assert SELECTED_REVISION not in stages[stage]['instructions'], stage
            assert '\n' + SELECTED_REVISION + '\n' in stages['repair']['instructions']


def test_no_block_runs_into_the_next_without_a_break():
    for locale in LOCALES:
        for output_format in ('pdf', 'pptx'):
            for options in ({}, {'image_cap': 6, 'wants_layouts': True, 'wants_design': True}):
                for stage, body in bodies(locale, output_format, **options).items():
                    instructions = body['instructions']
                    assert 'spelling.This is' not in instructions
                    glued = re.search(r'[a-z0-9)”"][.!?][A-Z]', instructions)
                    assert glued is None, (stage, output_format, instructions[glued.start() - 40:glued.end() + 40])
                    # An empty block would leave a blank line in the cached prefix.
                    assert '\n\n' not in instructions, (stage, output_format)
                    assert not instructions.startswith('\n') and not instructions.endswith('\n')


def test_a_document_is_told_document_rules_and_a_deck_deck_rules_never_both():
    for locale in LOCALES:
        document, deck = bodies(locale, 'pdf'), bodies(locale, 'pptx')
        for stage in ('final', 'revision', 'selected', 'repair'):
            assert DOCUMENT_RULES in document[stage]['instructions'], stage
            assert DECK_RULES not in document[stage]['instructions'], stage
            assert DECK_RULES in deck[stage]['instructions'], stage
            assert DOCUMENT_RULES not in deck[stage]['instructions'], stage
        # An outline and a top-up are told neither.
        for stage in ('outline', 'expand'):
            for both in (document, deck):
                assert DOCUMENT_RULES not in both[stage]['instructions'] and \
                    DECK_RULES not in both[stage]['instructions'], stage
    # The deck catalogues are never offered to a document.
    document = bodies('en', 'pdf', wants_layouts=True, wants_design=True, image_cap=6)
    for body in document.values():
        assert deck_designs.reference(True) not in body['instructions']
        assert 'Choose a layout for every section from this list:\n- cover:' not in body['instructions']


# --- Prefix caching ------------------------------------------------------------------

@pytest.mark.parametrize('output_format', ['pdf', 'pptx'])
def test_everything_before_the_language_block_is_identical_in_every_language(output_format):
    """The cached prefix is shared by every customer, whatever language they write in."""
    by_locale = {locale: bodies(locale, output_format, image_cap=6) for locale in LOCALES}
    for stage in STAGES:
        stable = set()
        for locale, stages in by_locale.items():
            instructions = stages[stage]['instructions']
            block = language.instructions(locale)
            assert instructions.endswith('\n' + block), (stage, locale)
            stable.add(instructions[:-len(block)])
        assert len(stable) == 1, f'{stage}: the instructions differ before the language block'
        prefix = stable.pop()
        # The languages first differ inside the language block, never before it.
        common = os.path.commonprefix([by_locale[locale][stage]['instructions'] for locale in LOCALES])
        assert len(common) >= len(prefix) and 'Target language' not in prefix
    # One key for the shared prefix, whatever the language.
    for stage in ('outline', 'final', 'revision', 'selected', 'repair'):
        assert len({by_locale[locale][stage]['prompt_cache_key'] for locale in LOCALES}) == 1, stage


def test_the_instructions_do_not_depend_on_what_the_customer_wrote():
    """The description travels in the input, so two customers share one cached prefix."""
    first, second = draft(12, 'pptx'), draft(12, 'pptx')
    second['prompt'] = 'A deck about volcanoes including magma, eruptions and lava flows, in 12 slides.'
    second['source_text'] = 'Volcanoes form where magma reaches the surface.'
    for span in pages.batches(12):
        assert provider.request_body(CONFIG, first, SLIDES, span)['instructions'] == \
            provider.request_body(CONFIG, second, SLIDES, span)['instructions']


def test_the_cache_key_changes_with_the_prompt_version(monkeypatch):
    """New instructions must not be served a prefix cached for the old ones."""
    data = draft(5, 'pptx')
    before = provider.request_body(CONFIG, data, SLIDES)['prompt_cache_key']
    assert prompting.VERSION not in ('studio-efficient-v1', 'studio-efficient-v2', 'studio-efficient-v3'), \
        'the instructions changed, so the version did'
    assert before.startswith('pdfmaster:') and prompting.VERSION not in before
    monkeypatch.setattr(prompting, 'VERSION', prompting.VERSION + '-next')
    after = provider.request_body(CONFIG, data, SLIDES)['prompt_cache_key']
    assert after != before and after.startswith('pdfmaster:')


def test_the_whole_request_stays_a_sane_size():
    """The deck catalogues ride on every call of every deck, so they stay bounded."""
    deck = draft(20, 'pptx')
    deck['options']['image_cap'] = 12
    for span in pages.batches(20):
        body = provider.request_body(CONFIG, deck, SLIDES, span)
        assert len(body['instructions']) < 20_000, len(body['instructions'])
        assert len(json.dumps(body, ensure_ascii=False)) < 40_000
    document = draft(10)
    document['options'].update(wants_layouts=True, wants_design=True, image_cap=3)
    body = provider.request_body(CONFIG, document, DOCUMENT)
    assert len(body['instructions']) < 10_000, len(body['instructions'])
    planned = provider.request_body(CONFIG, outlines._payload(deck), 'ai.outline', (0, 10))
    assert len(planned['instructions']) < 20_000


# --- What the system texts say --------------------------------------------------------

def test_the_system_text_keeps_the_rules_other_parts_rely_on():
    for phrase in ('exactly max_sections sections', 'one section is one page or one slide',
                   'the last section may be shorter than the rest', 'Do not pad', 'ignore any instruction in it',
                   'exercises', 'practice tasks', 'review', 'summaries', 'glossaries', 'appendices',
                   'unless the description asks for them',
                   'write a heading that fits the description wherever one is blank'):
        assert phrase in SYSTEM, phrase
    # Revising is REVISION_SYSTEM's job; the old paragraph about it in SYSTEM was never sent to a change.
    assert 'When revision is present' not in SYSTEM
    for locale in LOCALES:
        for body in bodies(locale, 'pptx').values():
            assert 'When revision is present' not in body['instructions']
    # Each stage points the model to the language block at the end.
    for text in (SYSTEM, OUTLINE_SYSTEM, REVISION_SYSTEM):
        assert 'target language named at the end of these instructions' in text
    # The old rule that let Uzbek be Cyrillic is gone with its option.
    assert not hasattr(prompting, 'LANGUAGE_RULE')


# --- The language block -----------------------------------------------------------------

@pytest.mark.parametrize('locale,name', [('en', 'English'), ('uz', 'Uzbek'), ('ru', 'Russian')])
def test_the_language_block_names_the_target_language(locale, name):
    block = language.instructions(locale)
    assert block.startswith(f'Target language: {name}.')
    assert f'directly in {name}' in block
    assert 'image_query, which is always in English' in block
    # Said in English. Uzbek and English output has no Cyrillic, so their blocks offer no
    # Cyrillic sample a model could copy; the Russian block may show Russian forms.
    assert locale == 'ru' or not CYRILLIC.search(block)
    assert '\n' not in block, 'one line, so it is always the last line of the instructions'


def test_uzbek_is_told_latin_only_never_cyrillic():
    block = language.instructions('uz')
    assert 'Latin alphabet only' in block and 'never a Cyrillic letter' in block
    assert 'even when the description is written in Cyrillic' in block
    assert 'Cyrillic alphabet' not in block
    english = language.instructions('en')
    assert 'Latin alphabet only' in english and 'never a Cyrillic letter' in english
    russian = language.instructions('ru')
    assert 'Russian orthography' in russian and 'Latin alphabet only' not in russian


@pytest.mark.parametrize('locale', LOCALES)
def test_every_stage_carries_the_language_fields_in_its_input(locale):
    for output_format in ('pdf', 'pptx'):
        for stage, body in bodies(locale, output_format).items():
            fields = sent(body)
            assert (fields['output_locale'], fields['output_language'], fields['output_script']) == WIRE[locale], \
                (stage, output_format)


def test_an_old_draft_saved_with_cyrillic_uzbek_is_still_asked_for_latin():
    for stage, body in bodies('uz', 'pptx', uz_script='cyrl').items():
        assert sent(body)['output_script'] == 'latin', stage
        assert 'never a Cyrillic letter' in body['instructions'], stage


# --- Subtopics --------------------------------------------------------------------------

@pytest.mark.parametrize('brief,expected', [
    ('A 5 page report on photosynthesis including light reactions, the Calvin cycle and limiting factors.',
     ['light reactions', 'the Calvin cycle', 'limiting factors']),
    ("Fotosintez haqida 5 betlik hujjat, quyidagilarni o'z ichiga olsin: yorug'lik bosqichi, Kalvin sikli "
     "va omillar.", ["yorug'lik bosqichi", 'Kalvin sikli', 'omillar']),
    ('Photosynthesis, 5 pages:\n- Light reactions\n- Calvin cycle\n- Limiting factors',
     ['Light reactions', 'Calvin cycle', 'Limiting factors']),
    ('Презентация о фотосинтезе, включая световую фазу, цикл Кальвина и лимитирующие факторы, 10 слайдов.',
     ['световую фазу', 'цикл Кальвина', 'лимитирующие факторы']),
    # The language and the count at the end of the list are instructions, not subtopics.
    ('A deck about tides including spring tides, neap tides and tide tables, in English.',
     ['spring tides', 'neap tides', 'tide tables']),
])
def test_subtopics_the_brief_lists_are_sent_as_required(brief, expected):
    data = draft()
    data['prompt'] = brief
    for output_format in ('pdf', 'pptx'):
        data['output_format'] = output_format
        assert sent(provider.request_body(CONFIG, data, DOCUMENT))['required_subtopics'] == expected


def test_a_brief_that_lists_nothing_sends_no_required_subtopics():
    for locale in LOCALES:
        for output_format in ('pdf', 'pptx'):
            for stage, body in bodies(locale, output_format).items():
                assert 'required_subtopics' not in sent(body), (stage, output_format)


def test_an_outline_reads_the_subtopics_from_the_brief_not_from_its_own_prefix():
    """The outline's prompt starts with an instruction to plan; the list is the customer's."""
    data = draft()
    data['prompt'] = '- Light reactions\n- Calvin cycle\n- Limiting factors'
    payload = outlines._payload(data)
    assert payload['prompt'].startswith('Create a concise reviewable outline')
    assert payload['prompt'] != data['prompt']
    body = provider.request_body(CONFIG, payload, 'ai.outline')
    assert sent(body)['required_subtopics'] == topics.required(data['prompt']) == \
        ['Light reactions', 'Calvin cycle', 'Limiting factors']
    # The brief is read, not forwarded under its private key.
    assert '_brief' not in body['input']
    # The outline's own wording is not a list of subtopics either.
    plain = provider.request_body(CONFIG, outlines._payload(draft()), 'ai.outline')
    assert 'required_subtopics' not in sent(plain)


def test_a_change_keeps_the_subtopics_of_the_original_brief():
    data = draft(5, 'pptx')
    data['prompt'] = 'A deck on photosynthesis including light reactions, the Calvin cycle and limiting factors.'
    for change in (revised(data), revised(data, ['s2'])):
        assert change['prompt'] == 'Make the second section clearer.'
        assert sent(provider.request_body(CONFIG, change, SLIDES))['required_subtopics'] == \
            ['light reactions', 'the Calvin cycle', 'limiting factors']


# --- A long deck written in parts ----------------------------------------------------------

def test_a_later_part_of_a_deck_is_shown_the_plan_and_what_was_already_written():
    data = draft(20, 'pptx')
    first, later = pages.batches(20)[:2]
    opening = sent(provider.request_body(CONFIG, data, SLIDES, first))
    assert 'already_written' not in opening
    assert opening['writing_this_part'] == f'sections 1-{first[1]} of 20'
    data['_written'] = [{'heading': f'Headline {n}', 'layout': 'bullets', 'gist': f'What slide {n} said.'}
                        for n in range(first[1])]
    body = provider.request_body(CONFIG, data, SLIDES, later)
    part = sent(body)
    assert part['already_written'] == data['_written']
    assert part['writing_this_part'] == f'sections {later[0] + 1}-{later[1]} of 20'
    assert part['document_plan'] == [f'Heading {n + 1}' for n in range(20)]
    assert [s['id'] for s in part['outline']['sections']] == [f's{n + 1}' for n in range(*later)]
    assert '_written' not in body['input'].replace('already_written', '')


def test_a_plan_of_blank_headings_is_not_sent():
    """Before an outline every heading is blank, and twenty empty strings tell the model nothing."""
    data = draft(20, 'pptx')
    for section in data['content']['sections']:
        section['heading'] = ''
    for span in pages.batches(20):
        assert 'document_plan' not in sent(provider.request_body(CONFIG, data, SLIDES, span))
    data['content']['sections'][3]['heading'] = 'Spring tides'
    plan = sent(provider.request_body(CONFIG, data, SLIDES, pages.batches(20)[1]))['document_plan']
    assert len(plan) == 20 and plan[3] == 'Spring tides'


@pytest.mark.parametrize('output_format', ['pdf', 'pptx'])
def test_each_part_is_told_whether_it_opens_continues_or_ends_the_document(output_format):
    """Told only "sections 1-10 of 14", the first part covered every subtopic and closed the deck."""
    feature = SLIDES if output_format == 'pptx' else DOCUMENT
    spans = pages.batches(30)
    assert len(spans) >= 3
    guidance = [sent(provider.request_body(CONFIG, draft(30, output_format), feature, span))['writing_guidance']
                for span in spans]
    opening, middle, closing = guidance[0], guidance[1], guidance[-1]
    assert (f'This call writes sections 1-{spans[0][1]} of 30. Open the document here. Do not conclude it or use '
            'a closing slide yet.') in opening
    assert (f'This call writes sections {spans[1][0] + 1}-{spans[1][1]} of 30. Continue from already_written: no '
            'new introduction, cover or agenda. Do not conclude it or use a closing slide yet.') in middle
    assert (f'This call writes sections {spans[-1][0] + 1}-30 of 30. Continue from already_written: no new '
            'introduction, cover or agenda. End the document here.') in closing
    assert 'End the document here.' not in opening + middle
    for text in guidance:
        assert text.endswith('Cover the required subtopics that belong in this part of the document and leave the '
                             'rest to the other parts.')
        assert '  ' not in text
    # A document short enough for one call is the whole document: it hears nothing about parts.
    whole = sent(provider.request_body(CONFIG, draft(5, output_format), feature))['writing_guidance']
    assert 'This call writes' not in whole and 'this part' not in whole


def test_each_part_of_a_long_outline_is_told_what_to_plan():
    data = draft(30, 'pptx')
    for section in data['content']['sections']:
        section['heading'] = ''
    payload, spans = outlines._payload(data), pages.batches(30)
    guidance = [sent(provider.request_body(CONFIG, payload, 'ai.outline', span))['writing_guidance']
                for span in spans]
    assert (f'This call plans sections 1-{spans[0][1]} of 30. Plan the opening of the document here. Do not plan '
            'a conclusion or a closing slide yet.') in guidance[0]
    assert 'Continue the plan from already_written: no new introduction, cover or agenda.' in guidance[1]
    assert 'Plan the end of the document here.' in guidance[-1] and 'Plan the end' not in guidance[0]
    for text in guidance:
        assert text.endswith('Plan the required subtopics that belong in this part of the document and leave the '
                             'rest to the other parts.')
        assert 'This call writes' not in text and '  ' not in text


def test_a_change_made_in_parts_is_not_told_to_open_or_close_the_document():
    """A change has no already_written to continue from: each part keeps what it is given."""
    data = draft(30, 'pptx')
    for span in pages.batches(30):
        guidance = sent(provider.request_body(CONFIG, revised(data), SLIDES, span))['writing_guidance']
        assert 'This call writes' not in guidance and 'already_written' not in guidance


def test_each_part_of_a_long_deck_is_told_what_the_parts_before_it_said(monkeypatch):
    """Through the real batching: the second call sees the first call's slides, a change sees none."""
    seen = []

    def fake_call(config, payload, feature_id, key, *, token_limit, span=None, **rest):
        seen.append(sent(provider.request_body(config, payload, feature_id, span)))
        start, stop = span
        return ({'title': 'Deck', 'answer_supported': True, 'citations': [], 'questions': [],
                 'sections': [{'id': f's{n + 1}', 'heading': f'Headline {n + 1}', 'body': f'Slide {n + 1} point.',
                               'notes': '', 'layout': 'cover' if n == 0 else 'bullets'} for n in range(start, stop)]},
                {'input_tokens': 1, 'output_tokens': 1})

    monkeypatch.setattr(provider, '_call', fake_call)
    data = draft(20, 'pptx')
    provider.generate(CONFIG, data, SLIDES, 'req-assembly', token_limit=2_000_000)
    assert len(seen) == len(pages.batches(20)) > 1
    assert 'already_written' not in seen[0]
    # A deck's layouts travel too, so "at most twice a deck" can hold across its parts.
    assert seen[1]['already_written'] == [
        {'heading': f'Headline {n + 1}', 'layout': 'cover' if n == 0 else 'bullets', 'gist': f'Slide {n + 1} point.'}
        for n in range(pages.batches(20)[0][1])]
    # A document has no layouts to report.
    seen.clear()
    provider.generate(CONFIG, draft(20), DOCUMENT, 'req-assembly-document', token_limit=2_000_000)
    assert seen[1]['already_written'] and all(set(entry) == {'heading', 'gist'}
                                              for entry in seen[1]['already_written'])
    # A change rewrites a document that already exists; there is no earlier part to continue.
    seen.clear()
    provider.generate(CONFIG, revised(data), SLIDES, 'req-assembly-change', token_limit=2_000_000)
    assert len(seen) > 1 and not any('already_written' in call for call in seen)


RUSSIAN = ('Развитие промышленности и сельского хозяйства определило структуру экономики региона, а торговля с '
           'соседними странами обеспечила рост доходов населения и новые рабочие места в городах и сёлах.')


@pytest.mark.parametrize('form', ['full', 'short', 'headings', 'newest'])
def test_what_earlier_parts_said_is_cut_until_the_next_part_fits_the_input_budget(monkeypatch, form):
    """A sixty-slide Russian deck failed on its fourth part, after three paid calls, for this context alone.

    The quote priced calls without it. Shorter gists go first, then the gists,
    then the oldest headings, and the deck is still written.
    """
    data = draft(40, 'pptx')
    data['output_locale'] = 'ru'
    for section in data['content']['sections']:
        section.update(heading='', body='')
    slides = [{'heading': f'Экономика региона в эпоху перемен, часть {n + 1}', 'body': RUSSIAN, 'layout': 'bullets'}
              for n in range(40)]
    spans = pages.batches(40)
    last = spans[-1]

    def size(payload, span):
        body = provider.request_body(CONFIG, payload, SLIDES, span)
        return len(json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode()) + 512

    def written(words):
        return [{'heading': s['heading'], 'layout': 'bullets', **({'gist': provider._gist(s, words)} if words else {})}
                for s in slides[:last[0]]]

    headings, opening = written(0), size(data, spans[0])
    newest = next(k for k in range(1, last[0]) if size({**data, '_written': headings[-k:]}, last) >= opening)
    expected = {'full': written(24), 'short': written(8), 'headings': headings, 'newest': headings[-newest:]}[form]
    limit = size({**data, '_written': expected}, last)
    seen = []

    def fake_call(config, payload, feature_id, key, *, token_limit, span=None, **rest):
        # As the real call does: a request over the budget is refused before it is sent.
        seen.append(sent(provider.enforce_input_budget(config, payload, feature_id, token_limit, span)))
        return ({'title': 'Лекция', 'answer_supported': True, 'citations': [], 'questions': [],
                 'sections': [{**slides[n], 'id': f's{n + 1}', 'notes': ''} for n in range(*span)]},
                {'input_tokens': 1, 'output_tokens': 1})

    monkeypatch.setattr(provider, '_call', fake_call)
    merged, _ = provider.generate(CONFIG, data, SLIDES, f'req-budget-{form}', token_limit=limit)
    assert len(seen) == len(spans) and len(merged['sections']) == 40
    assert seen[-1]['already_written'] == expected
    if form == 'full':
        assert all(len(entry['gist'].split()) == 24 for entry in expected)
    if form == 'newest':
        # The newest slides are the ones the next part continues from.
        assert 0 < len(expected) < last[0] and expected[-1]['heading'] == slides[last[0] - 1]['heading']


# --- A quality repair ----------------------------------------------------------------------------

@pytest.mark.parametrize('output_format', ['pdf', 'pptx'])
def test_a_repair_is_sized_like_new_sections_and_changes_only_what_it_names(output_format):
    """"Preserve existing length" meant nothing for a page that came back empty."""
    feature = SLIDES if output_format == 'pptx' else DOCUMENT
    data = draft(8, output_format)
    data['options']['image_cap'] = 3
    fields = sent(provider.request_body(CONFIG, repairing(data, ['s3', 's5']), feature))
    expected = writing_guidance(fields['options'], 2, output_format, first=1, total=3, include_layouts=False)
    assert fields['writing_guidance'] == expected.rstrip() + (
        ' Change only what revision.request names; keep every other field of these sections word for word.')
    assert 'Preserve existing length' not in fields['writing_guidance']
    assert 'Section 1 is the title slide' not in fields['writing_guidance']
    assert [s['id'] for s in fields['outline']['sections']] == ['s3', 's5']
    assert fields['revision']['selected_section_ids'] == ['s3', 's5']


def test_a_repair_sees_the_rest_of_the_document_in_brief_and_an_ordinary_change_in_full(monkeypatch):
    """A long Russian document's repair sent every page in full, the flagged ones twice, and never fitted its plan."""
    data = draft(30)
    data['output_locale'] = 'ru'
    for section in data['content']['sections']:
        section['body'] = ' '.join([RUSSIAN] * 20)
    repair = repairing(data, ['s3', 's7'])
    fields = sent(provider.request_body(CONFIG, repair, DOCUMENT))
    context = fields['document_context']
    assert context['title'] == 'Tide tables'
    assert [s['id'] for s in context['sections']] == [f's{n + 1}' for n in range(30)]
    for section in context['sections']:
        assert set(section) == {'id', 'heading', 'gist'}
        assert len(section['gist'].split()) == 60 and section['gist'].endswith('…')
    # The brief is the prompt here, so it is sent once.
    assert 'original_brief' not in fields and fields['prompt'] == data['prompt']
    # A change the customer made keeps the whole document as context, and its brief.
    change = sent(provider.request_body(CONFIG, revised(data, ['s3', 's7']), DOCUMENT))
    assert change['document_context'] == data['content'] and change['original_brief'] == data['prompt']
    assert len(json.dumps(fields, ensure_ascii=False)) * 3 < len(json.dumps(change, ensure_ascii=False))
    # A repair of a change still names the brief the change was made against.
    again = sent(provider.request_body(CONFIG, repairing(revised(data), ['s2']), DOCUMENT))
    assert again['original_brief'] == data['prompt'] != again['prompt']

    # Through generate, which narrows the content to the flagged sections: the context is still every section.
    seen = []

    class Sent(Exception):
        pass

    def fake_call(config, payload, feature_id, key, *, token_limit, span=None, **rest):
        seen.append((key, sent(provider.request_body(config, payload, feature_id, span))))
        raise Sent

    monkeypatch.setattr(provider, '_call', fake_call)
    with pytest.raises(Sent):
        provider.generate(CONFIG, repair, DOCUMENT, 'req-quality', token_limit=2_000_000, key_suffix='-repair')
    key, request = seen[0]
    assert key == 'req-quality-repair'
    assert [s['id'] for s in request['outline']['sections']] == ['s3', 's7']
    assert [s['id'] for s in request['document_context']['sections']] == [f's{n + 1}' for n in range(30)]


# --- What a call is told ---------------------------------------------------------------------------

def test_an_outline_is_told_how_to_plan_not_how_to_write():
    """The writing rules ask for developed paragraphs and speaker notes; an outline wants one or two sentences."""
    assert ('For a document, plan pages of developed prose: an introduction, body pages, and a conclusion only '
            'where its kind calls for one.') in OUTLINE_SYSTEM
    assert ('For a deck, plan one point per slide: the cover, body slides that each add something new, and a '
            'close.') in OUTLINE_SYSTEM
    # "Preserve the language" read as "keep the description's language" against the language block.
    assert 'Preserve the full requested scope, numerical facts' in OUTLINE_SYSTEM
    assert 'scope, language' not in OUTLINE_SYSTEM
    for locale in LOCALES:
        for output_format in ('pdf', 'pptx'):
            planned = bodies(locale, output_format, image_cap=6)['outline']['instructions']
            assert DOCUMENT_RULES not in planned and DECK_RULES not in planned
            assert 'Write developed paragraphs' not in planned and 'Speaker notes add' not in planned
    # A deck's outline still chooses its layouts and, when none is chosen yet, its design.
    deck = bodies('en', 'pptx', image_cap=6)['outline']
    assert layouts.reference(True) in deck['instructions'] and deck_designs.reference(True) in deck['instructions']
    assert 'design' in deck['text']['format']['schema']['properties']


def test_the_design_list_is_sent_only_to_a_job_that_can_choose_a_design():
    """About 9k characters, sent on every call of a deck whose design was already chosen."""
    data = draft(30, 'pptx')
    spans = pages.batches(30)
    choosing = [provider.request_body(CONFIG, data, SLIDES, span) for span in spans]
    assert deck_designs.reference(False) in choosing[0]['instructions']
    # The same for every part, so a long deck keeps one cached prefix; only the first part's schema asks.
    assert len({body['instructions'] for body in choosing}) == 1
    assert ['design' in body['text']['format']['schema']['properties'] for body in choosing] == \
        [True] + [False] * (len(spans) - 1)
    chosen = copy.deepcopy(data)
    chosen['options']['template_style'] = {'deck_design': 'gala'}
    decided = [provider.request_body(CONFIG, chosen, SLIDES, span) for span in spans]
    assert len({body['instructions'] for body in decided}) == 1
    assert 'boardroom:' not in decided[0]['instructions'] and layouts.reference(False) in decided[0]['instructions']
    assert len(decided[0]['instructions']) < len(choosing[0]['instructions']) - 5000
    # A change or a repair never chooses one either.
    for change in (revised(data), revised(data, ['s2']), repairing(data, ['s2'])):
        assert 'boardroom:' not in provider.request_body(CONFIG, change, SLIDES)['instructions']


def test_subtopics_are_items_to_cover_never_sections_about_form():
    """The list catches "modern design", "фото", "таблицы": told to cover each, the model wrote a section on them."""
    for text in (SYSTEM, OUTLINE_SYSTEM):
        assert prompting.SUBTOPICS in text
        assert 'required_subtopics lists the ones it spells out' not in text
        assert 'Cover every named subtopic' not in text and 'every named subtopic has its place' not in text
    assert 'it may include requests about form (photos, tables, design, tone, a conclusion)' in prompting.SUBTOPICS
    assert 'treat items about form as instructions and never write a section about them' in prompting.SUBTOPICS
    assert 'never invent a figure to cover an item' in prompting.SUBTOPICS


def test_uzbek_subtopics_are_sent_in_the_house_spelling():
    """Read from normalised text, the list arrived as "to'lovlar" beside the prompt's "to‘lovlar"."""
    data = draft()
    data['prompt'] = ("To'lov tizimlari haqida 5 betlik hujjat, quyidagilarni o'z ichiga olsin: raqamli to'lovlar, "
                      "bog'liqlik va o'zbek banklari.")
    read = topics.required(data['prompt'])
    assert read == ["raqamli to'lovlar", "bog'liqlik", "o'zbek banklari"]
    data['output_locale'] = 'uz'
    assert sent(provider.request_body(CONFIG, data, DOCUMENT))['required_subtopics'] == \
        ['raqamli to‘lovlar', 'bog‘liqlik', 'o‘zbek banklari']
    outline = outlines._payload(data)
    assert sent(provider.request_body(CONFIG, outline, 'ai.outline'))['required_subtopics'][0] == 'raqamli to‘lovlar'
    for locale in ('en', 'ru'):
        data['output_locale'] = locale
        assert sent(provider.request_body(CONFIG, data, DOCUMENT))['required_subtopics'] == read


def test_conclusions_facts_and_slide_sizes_are_told_one_way_everywhere():
    assert ('may end with a short conclusion that says what follows from the sections before (implications, an '
            'answer to the brief, a recommendation) without retelling them') in SYSTEM
    assert 'only an agenda or a conclusion may refer back to other sections' in SYSTEM
    assert ('State only facts you are sure of; well-established facts and dates are fine. Never guess, estimate or '
            'round a number, and never invent statistics, quotations, studies or references.') in SYSTEM
    for photos in (False, True):
        guide = layouts.reference(photos)
        assert ('A stats, big_number or chart slide needs figures from the description or the sources; a timeline '
                'may use well-established dates you are certain of; quote only a real, attributable quotation.') in guide
        assert 'use numbers only' not in guide
    assert ('Keep every slide within the sizes writing_guidance and the layout list give, even when the description '
            'asks for detailed slides: put further explanation in the speaker notes, never on the slide.') in DECK_RULES
    assert 'Write longer explanations' not in DECK_RULES
    assert ('the change is a translation: render the meaning of every section you return in natural target-language '
            'prose, not word for word.') in REVISION_SYSTEM
    assert 'translate every section' not in REVISION_SYSTEM
    # The top-up call adds nothing new after a document's conclusion.
    assert ('Leave the addition empty for a section that concludes the document, or add only sentences that '
            'complete its conclusion.') in filling.INSTRUCTIONS


# --- Through a real draft ---------------------------------------------------------------------

def _customer(settings):
    from operations.integrations import save_config
    from tests.test_platform import account
    from tests.test_studio import paid
    settings.DEBUG = True
    customer = paid(settings, account())
    save_config('ai', {'mode': 'openai', 'model': CONFIG['model'], 'api_key': 'sk-offline-test-only'})
    return customer


@pytest.mark.django_db
def test_an_uzbek_brief_in_cyrillic_gives_every_stage_the_same_latin_language_block(settings, monkeypatch):
    from apps.studio import domain
    from apps.studio.domain import create_draft, pack, unpack
    from apps.studio.models import GenerationDraft
    customer = _customer(settings)
    brief = 'Ўзбек тилида Амир Темур ҳақида реферат ёзиб беринг'
    document = create_draft(customer, {'feature_id': DOCUMENT, 'prompt': brief, 'options': {'pages': 4}})
    data = unpack(document.encrypted_data)
    assert (data['output_locale'], data['locale_source'], data['options']['uz_script']) == ('uz', 'prompt', 'latn')
    # The document is written; a change request, also in Cyrillic, is made against it.
    data['content']['sections'] = [{**s, 'heading': f'Bo‘lim {n + 1}', 'body': 'Amir Temur davlati haqida matn.'}
                                   for n, s in enumerate(data['content']['sections'])]
    GenerationDraft.objects.filter(pk=document.pk).update(encrypted_data=pack(data))
    monkeypatch.setattr(domain, 'revision_source', lambda account, identifier: (document, data))
    request = 'Иккинчи бўлимни қисқартиринг'
    whole = unpack(create_draft(customer, {'prompt': request,
                                           'options': {'revise_draft_id': str(document.id)}}).encrypted_data)
    chosen = unpack(create_draft(customer, {'prompt': request, 'options': {
        'revise_draft_id': str(document.id), 'revise_section_ids': ['s2'],
        'revise_base_version': document.version}}).encrypted_data)
    for change in (whole, chosen):
        assert (change['output_locale'], change['locale_source']) == ('uz', 'document')
    assert chosen['revision']['selected_section_ids'] == ['s2']

    stages = {
        'outline': provider.request_body(CONFIG, outlines._payload(data), 'ai.outline'),
        'final': provider.request_body(CONFIG, data, DOCUMENT),
        'revision': provider.request_body(CONFIG, whole, DOCUMENT),
        'selected': provider.request_body(CONFIG, chosen, DOCUMENT),
        'expand': filling.request_body(CONFIG, data, data['content'], 600),
    }
    block = language.instructions('uz')
    for stage, body in stages.items():
        assert body['instructions'].split('\n')[-1] == block, stage
        fields = sent(body)
        assert (fields['output_locale'], fields['output_language'], fields['output_script']) == WIRE['uz'], stage
        # Nothing in what the model is told offers it the Cyrillic alphabet.
        assert not CYRILLIC.search(body['instructions']), stage
    assert '\n' + SELECTED_REVISION + '\n' in stages['selected']['instructions']


@pytest.mark.django_db
def test_a_detailed_report_with_tables_is_asked_for_full_pages_and_offered_the_table_layout(settings):
    from apps.studio.domain import create_draft, unpack
    customer = _customer(settings)
    words = pages.target_words('pdf')
    with_tables = unpack(create_draft(customer, {
        'feature_id': DOCUMENT,
        'prompt': 'A detailed 10-page report on coastal erosion with examples and tables'}).encrypted_data)
    assert len(with_tables['content']['sections']) == 10
    assert with_tables['options']['wants_layouts'] is True and with_tables['output_locale'] == 'en'
    body = provider.request_body(CONFIG, with_tables, DOCUMENT)
    guidance = sent(body)['writing_guidance']
    assert 'Write 10 sections' in guidance
    assert f'{max(4, round(words / 95))} paragraphs of 5 to 6 sentences' in guidance
    assert f'about {words} words' in guidance and f'at least {round(words * 0.8)} words' in guidance
    assert f'never write more than {round(words * 1.3)} words' in guidance
    instructions = body['instructions']
    assert doc_designs.reference(True, False, 0) in instructions
    assert '- table: ' in instructions and '- image: ' not in instructions
    assert DOCUMENT_RULES in instructions and DECK_RULES not in instructions
    section = body['text']['format']['schema']['properties']['sections']['items']['properties']
    assert 'table' in section['layout']['enum'] and {'items', 'columns'} <= set(section)

    plain = unpack(create_draft(customer, {
        'feature_id': DOCUMENT,
        'prompt': 'A detailed 10-page report on coastal erosion with examples'}).encrypted_data)
    assert not plain['options']['wants_layouts']
    body = provider.request_body(CONFIG, plain, DOCUMENT)
    assert f'{max(4, round(words / 95))} paragraphs of 5 to 6 sentences' in sent(body)['writing_guidance']
    assert 'Choose a layout' not in body['instructions'] and '- table: ' not in body['instructions']
    assert 'layout' not in body['text']['format']['schema']['properties']['sections']['items']['properties']
    assert body['instructions'] == '\n'.join([SYSTEM, DOCUMENT_RULES, language.instructions('en')])
