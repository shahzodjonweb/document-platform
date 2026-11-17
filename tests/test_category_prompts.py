"""What a category deck tells the model (architecture 3.1, 3.2, 3.4), built from the real catalogue.

A category deck is told what every deck is told, then DECK and its category's
block after the layout guide, and its slots as rows in the input. The block
is the same for every customer and every language, so the cached prefix is
shared as a Boshqa deck's is; the stacks stay inside the caps measured on
42a53d7 with the block at its 5,000-character budget. No model is called:
these are the bodies the provider would be sent. Drafts without a category
are pinned byte for byte by tests/test_prompt_golden.py.
"""
import copy
import dataclasses
import json
import re
from types import SimpleNamespace

import pytest

from apps.core.errors import DomainError
from apps.studio import deck_designs, language, layouts, prompting, provider
from apps.studio.categories import catalogue, skeleton
from apps.studio.categories import prompting as categories
from apps.studio.domain import DOCUMENT, SLIDES
from apps.studio.prompting import REVISION_SYSTEM, SELECTED_REVISION
from apps.studio.provider import DECK_RULES, SAFETY, SYSTEM
from tests.test_prompt_assembly import repairing, revised
from tests.test_provider_contract import CONFIG, draft

LOCALES = ('uz', 'ru', 'en')
PROMPT = {
    'uz': 'Bitiruv malakaviy ishi himoyasi uchun taqdimot: “Namuna Savdo” MChJda xodimlar almashinuvini kamaytirish yo‘llari',
    'ru': 'Презентация к защите ВКР: пути снижения текучести кадров в ООО «Намуна Савдо»',
    'en': 'A thesis defence deck: ways to reduce staff turnover at Namuna Savdo LLC',
}
# The caps of architecture 3.1, from SYSTEM, DECK_RULES, the layout guide with
# photos, the design guide and the largest language block as measured, with a
# category block at its budget.
CAPS = {'new': 15_000, 'part': 15_000, 'plan': 15_000, 'change': 15_500, 'selected': 15_500, 'repair': 15_500,
        'redesign': 24_000}


def decks():
    return [entry for entry in catalogue._catalogue().entries.values()
            if entry.service == 'slides' and entry.status != catalogue.RETIRED]


def deck(entry, slides=10, locale='uz', prompt=None, **options):
    """A new category deck's draft as the domain makes one: its slots seeded, the entry's look chosen."""
    prompt = prompt or PROMPT[locale]
    sections = skeleton.seed(entry, slides, skeleton.cues(entry, prompt, has_files=False))
    for number, section in enumerate(sections, 1):
        section.update(heading=f'Slide {number}', body=f'Point {number}.')
    return {'output_locale': locale, 'prompt': prompt, 'source_text': '', 'excerpts': [],
            'options': {'question_count': 0, 'length': slides, 'image_cap': 6, 'category': entry.id,
                        'template_style': {'deck_design': entry.look['designs'][0]}, **options},
            'output_format': 'pptx',
            'content': {'title': 'Defence', 'sections': sections, 'questions': [], 'citations': []}}


def redesigned(data):
    change = revised(data)
    change['revision']['edit'] = {'redesign': True}
    return change


def planned(data):
    plan = copy.deepcopy(data)
    plan['_stage'] = 'plan'
    return plan


def bodies(entry, locale='uz', slides=10, prompt=None):
    """The request body of every stage of one category deck, in one language."""
    data = deck(entry, slides, locale, prompt)
    return {
        'new': provider.request_body(CONFIG, data, SLIDES),
        'part': provider.request_body(CONFIG, data, SLIDES, (5, slides)),
        'plan': provider.request_body(CONFIG, planned(data), SLIDES),
        'change': provider.request_body(CONFIG, revised(data), SLIDES),
        'selected': provider.request_body(CONFIG, revised(data, ['s2']), SLIDES),
        'repair': provider.request_body(CONFIG, repairing(data, ['s2', 's4']), SLIDES),
        'redesign': provider.request_body(CONFIG, redesigned(data), SLIDES),
    }


def sent(body):
    return json.loads(body['input'])


def sentences(text):
    return [part for part in re.split(r'(?<=\.) (?=[A-Z])', text) if part]


# ---------------------------------------------------------------- safety


def test_safety_is_systems_own_sentences_word_for_word():
    assert len(sentences(SAFETY)) == 5
    for sentence in sentences(SAFETY):
        assert sentence in SYSTEM, sentence


@pytest.mark.parametrize('entry', decks(), ids=lambda entry: entry.id)
def test_every_new_category_deck_body_keeps_safety_and_the_never_invent_line(entry):
    for locale in LOCALES:
        stages = bodies(entry, locale)
        for stage in ('new', 'part', 'plan'):
            for sentence in sentences(SAFETY):
                assert sentence in stages[stage]['instructions'], (stage, locale, sentence)
        # A change is told by DECK what more information means in a category deck.
        for stage, body in stages.items():
            assert 'Never write a person, organisation, date, number, price, law, quotation or source that is not in ' \
                   'the description or the sources' in body['instructions'], stage


# ---------------------------------------------------------------- the stacks


@pytest.mark.parametrize('entry', decks(), ids=lambda entry: entry.id)
def test_a_category_deck_is_told_its_stack_in_the_order_of_architecture_3_1(entry):
    block = categories.block(entry)
    reference = layouts.reference(True)
    for locale in LOCALES:
        stages = bodies(entry, locale)
        tail = language.instructions(locale)
        for stage in ('new', 'part', 'plan'):
            assert stages[stage]['instructions'] == '\n'.join(
                [SYSTEM, DECK_RULES, reference, categories.DECK, block, tail]), stage
        assert stages['change']['instructions'] == '\n'.join(
            [REVISION_SYSTEM, DECK_RULES, reference, categories.DECK, block, tail])
        assert stages['repair']['instructions'] == stages['selected']['instructions'] == '\n'.join(
            [REVISION_SYSTEM, DECK_RULES, reference, categories.DECK, block, SELECTED_REVISION, tail])
        assert stages['redesign']['instructions'] == '\n'.join(
            [REVISION_SYSTEM, DECK_RULES, reference, deck_designs.reference(True), categories.DECK, block, tail])


def test_a_new_category_deck_never_reads_the_design_guide_and_a_redesign_change_may_choose_one():
    entry = catalogue.get('slides.himoya')
    data = deck(entry)
    # Even with no design written yet (the domain writes the entry's look), a new category deck chooses none.
    data['options']['template_style'] = {}
    body = provider.request_body(CONFIG, data, SLIDES)
    assert deck_designs.reference(True) not in body['instructions']
    assert 'design' not in body['text']['format']['schema']['properties']
    change = provider.request_body(CONFIG, redesigned(deck(entry)), SLIDES)
    assert 'design' in change['text']['format']['schema']['properties']


def test_the_block_holds_the_tone_the_model_rules_and_the_field_table_and_nothing_else():
    for entry in catalogue._catalogue().entries.values():
        block = categories.block(entry)
        assert '\n\n' not in block and not block.endswith('\n')
        assert ' '.join(entry.raw['tone'].split()) in block
        for rule in entry.raw['rules']:
            text = ' '.join(rule['text'].split())
            assert (text in block) == (rule['to'] == 'model'), (entry.id, rule['to'], text[:60])
        for item in entry.raw['fields']:
            assert re.search(rf"^- {re.escape(item['id'])}: {re.escape(item['label']['en'])}, {item['kind']}",
                             block, re.M), (entry.id, item['id'])
            # English only: the block reads the same whatever language the document is in.
            assert item['label']['ru'] not in block or item['label']['ru'] == item['label']['en']
        for part in entry.raw['parts']:
            if part['kind'] == 'fixed' and not part.get('retired'):
                assert ' '.join(part['write'].split()) in block, (entry.id, part['id'])
            elif part['kind'] != 'fixed' and part.get('write'):
                # A written part's rules travel in its row, not in the cached prefix.
                assert ' '.join(part['write'].split()) not in block, (entry.id, part['id'])


def test_an_ariza_block_puts_each_field_under_the_fixed_part_that_draws_it():
    block = categories.block(catalogue.get('pdf.xat.ariza')).split('\n')
    addressee = next(n for n, line in enumerate(block) if line.startswith('Part addressee,'))
    assert [line.split(':')[0] for line in block[addressee + 1:addressee + 4]] == \
        ['- addressee_org', '- addressee_position', '- addressee_person']
    # C2c draws six ruled lines for a message naming no request, so request sits under that blank, not with the rest.
    blank = next(n for n, line in enumerate(block) if line.startswith('Part request_blank,'))
    other = block.index('Other fields:')
    assert block[blank + 1].startswith('- request: What you ask for, text') and blank < other
    assert all(not line.startswith('- request:') for line in block[other:])


# ---------------------------------------------------------------- the same prefix for everyone


@pytest.mark.parametrize('entry', decks(), ids=lambda entry: entry.id)
def test_category_instructions_are_equal_across_languages_and_hold_no_customer_text(entry):
    by_locale = {locale: bodies(entry, locale) for locale in LOCALES}
    other = bodies(entry, 'uz', prompt='Kurs ishi himoyasi: “Yashil Vodiy” fermer xo‘jaligida suv tejash, 6 ta slayd')
    for stage in CAPS:
        prefixes = {by_locale[locale][stage]['instructions'][:-len(language.instructions(locale))]
                    for locale in LOCALES}
        assert len(prefixes) == 1, stage
        assert other[stage]['instructions'] == by_locale['uz'][stage]['instructions'], stage
        for words in ('Namuna', 'Намуна', 'Yashil', 'turnover', 'almashinuv'):
            assert words not in by_locale['uz'][stage]['instructions'], (stage, words)
        # One cache key for the category's prefix, whatever the language.
        assert len({by_locale[locale][stage]['prompt_cache_key'] for locale in LOCALES}) == 1, stage


# ---------------------------------------------------------------- the rows


def test_rows_name_each_slot_with_its_heading_in_the_documents_language():
    entry = catalogue.get('slides.himoya')
    for locale in LOCALES:
        data = deck(entry, 10, locale)
        blueprint = skeleton.slots(entry, 10, skeleton.cues_of(data))
        user = sent(provider.request_body(CONFIG, data, SLIDES))
        assert user['category'] == 'slides.himoya'
        rows = user['parts']
        assert [row['id'] for row in rows] == [f's{n}' for n in range(1, 11)]
        assert [row['slot'] for row in rows] == [slot['id'] for slot in blueprint]
        for row, slot in zip(rows, blueprint):
            assert set(row) == {'id', 'slot', 'heading', 'layouts', 'source', 'holds'}
            assert row['layouts'] == slot['layouts'] and row['source'] == slot['source']
            assert row['heading'] == (slot['heading'][locale] if slot['heading_mode'] == 'fixed' else '')
        assert rows[0]['slot'] == 'cover' and rows[0]['heading'] == ''
        assert rows[-1]['heading'] == {'uz': 'E’tiboringiz uchun rahmat!', 'ru': 'Спасибо за внимание!',
                                       'en': 'Thank you for your attention!'}[locale]
        assert 'Each section is the slot its row in parts names' in user['writing_guidance']


def test_a_slot_without_a_heading_is_null_and_one_the_model_names_is_empty(monkeypatch):
    entry = catalogue.get('slides.himoya')
    raw = copy.deepcopy(entry.raw)
    for part in raw['parts']:
        if part['id'] == 'maqsad_vazifalar':
            part['heading_mode'] = 'none'
    edited = dataclasses.replace(entry, raw=raw)
    monkeypatch.setattr(categories, 'of', lambda data: edited)
    data = deck(entry, 10, 'en')
    made = {row['slot']: row['heading'] for row in categories.rows(data, data['content']['sections'])}
    assert made['maqsad_vazifalar'] is None and made['cover'] == ''
    assert made['rahmat'] == 'Thank you for your attention!'
    assert 'leave it empty where it is null' in categories.DECK


def test_a_slot_met_again_in_one_call_points_at_its_first_row():
    entry = catalogue.get('slides.himoya')
    rows = sent(provider.request_body(CONFIG, deck(entry, 15, 'en'), SLIDES))['parts']
    results = [row for row in rows if row['slot'] == 'natija']
    assert len(results) > 1
    assert results[0]['holds'] == ' '.join(entry.part('natija')['write'].split())
    assert all(row['holds'] == f"another slide of the slot of {results[0]['id']}, written as that row says"
               for row in results[1:])


def test_a_later_part_has_its_own_rows_and_a_plan_keeps_the_slot_headings():
    entry = catalogue.get('slides.himoya')
    data = deck(entry, 12, 'ru', prompt=PROMPT['ru'])
    blueprint = skeleton.slots(entry, 12, skeleton.cues_of(data))
    later = sent(provider.request_body(CONFIG, data, SLIDES, (5, 12)))
    assert [row['id'] for row in later['parts']] == [f's{n}' for n in range(6, 13)]
    assert [row['slot'] for row in later['parts']] == [slot['id'] for slot in blueprint[5:]]
    assert 'Continue from already_written' in later['writing_guidance']
    plan = sent(provider.request_body(CONFIG, planned(data), SLIDES))
    assert len(plan['parts']) == 12
    assert plan['writing_guidance'].startswith('Plan 12 slides only')
    assert plan['writing_guidance'].endswith(categories.PLAN_GUIDANCE)


def test_a_change_names_its_category_but_sends_no_rows_and_keeps_todays_guidance():
    entry = catalogue.get('slides.himoya')
    data = deck(entry, 10, 'en')
    for change in (revised(data), revised(data, ['s3']), repairing(data, ['s2'])):
        user = sent(provider.request_body(CONFIG, change, SLIDES))
        assert user['category'] == 'slides.himoya' and 'parts' not in user
        plain = copy.deepcopy(change)
        del plain['options']['category']
        assert user['writing_guidance'] == sent(provider.request_body(CONFIG, plain, SLIDES))['writing_guidance']


def test_an_outline_of_a_category_deck_is_told_nothing_of_the_category():
    """An outline of a category deck is planned as any deck's; a paper's prompts are tests/test_category_prompts_pdf.py's."""
    from apps.studio import outlines
    entry = catalogue.get('slides.himoya')
    data = deck(entry, 10, 'en')
    plain = copy.deepcopy(data)
    del plain['options']['category']
    outline = provider.request_body(CONFIG, outlines._payload(data), 'ai.outline')
    assert outline['instructions'] == provider.request_body(CONFIG, outlines._payload(plain), 'ai.outline')['instructions']
    assert 'parts' not in sent(outline) and 'category' not in sent(outline)


# ---------------------------------------------------------------- budgets


@pytest.mark.parametrize('entry', decks(), ids=lambda entry: entry.id)
def test_every_deck_stage_meets_its_cap_with_the_block_at_its_budget(entry):
    """The stack around the block is measured; a draft entry's block is held to its budget by readiness."""
    block = len(categories.block(entry))
    for locale in LOCALES:
        for stage, body in bodies(entry, locale).items():
            size = len(body['instructions'])
            assert size - block + catalogue.BLOCK_BUDGET <= CAPS[stage], (stage, locale, size - block)
            if entry.status == catalogue.READY:
                assert size <= CAPS[stage], (stage, locale, size)
    assert len(categories.DECK) <= 1_200 and len(categories.REVISION_NOTE) <= 700


def test_a_ready_block_within_budget_keeps_every_stage_under_its_cap(monkeypatch):
    entry = catalogue.get('slides.himoya')
    monkeypatch.setattr(categories, 'block', lambda entry: 'x' * catalogue.BLOCK_BUDGET)
    for locale in LOCALES:
        for stage, body in bodies(entry, locale).items():
            assert len(body['instructions']) <= CAPS[stage], (stage, locale, len(body['instructions']))


# ---------------------------------------------------------------- the cache key


def test_the_cache_key_carries_the_category_and_its_digest():
    entry = catalogue.get('slides.himoya')
    data = deck(entry, 10, 'en')
    assert categories.cache_tag(data) == f':slides.himoya@{entry.digest}'
    assert re.fullmatch(r'[0-9a-f]{8}', entry.digest)
    assert prompting.categories_of(draft(5, 'pptx')) is None
    plain = copy.deepcopy(data)
    del plain['options']['category']
    key = provider.request_body(CONFIG, data, SLIDES)['prompt_cache_key']
    assert key.startswith('docmaster:') and key != provider.request_body(CONFIG, plain, SLIDES)['prompt_cache_key']
    assert prompting.VERSION == 'studio-efficient-v7'


def test_an_edit_to_the_entry_moves_the_key(monkeypatch):
    entry = catalogue.get('slides.himoya')
    data = deck(entry, 10, 'en')
    before = provider.request_body(CONFIG, data, SLIDES)['prompt_cache_key']
    edited = dataclasses.replace(entry, digest='0badc0de')
    monkeypatch.setattr(categories, 'of', lambda data: edited)
    assert provider.request_body(CONFIG, data, SLIDES)['prompt_cache_key'] != before


# ---------------------------------------------------------------- the provider


def test_an_unknown_category_fails_before_any_call(monkeypatch):
    def opener(_):
        raise AssertionError('no request may be sent')
    monkeypatch.setattr(provider.urllib.request, 'build_opener', opener)
    data = deck(catalogue.get('slides.himoya'))
    data['options']['category'] = 'slides.gone'
    with pytest.raises(DomainError) as raised:
        provider.request_body(CONFIG, data, SLIDES)
    assert raised.value.code == 'category_unknown'
    with pytest.raises(DomainError) as raised:
        provider._call(CONFIG, data, SLIDES, 'key', token_limit=120_000)
    assert raised.value.code == 'category_unknown'


def test_a_planned_category_deck_is_dressed_before_its_parts_are_written(monkeypatch):
    entry = catalogue.get('slides.himoya')
    data = deck(entry, 10, 'uz')
    blueprint = skeleton.slots(entry, 10, skeleton.cues_of(data))
    # The plan renames every slide and gives each a layout of its own choosing.
    monkeypatch.setattr(provider, '_plan', lambda config, effective, *args, **kwargs: [
        {'id': section['id'], 'heading': f'Planned {number}', 'layout': 'image_split', 'image_query': ''}
        for number, section in enumerate(effective['content']['sections'], 1)])
    written, shown = [], []

    def call(config, effective, feature, key, *, token_limit, span=None, **rest):
        written.append((span, copy.deepcopy(effective['content']['sections'])))
        sections = effective['content']['sections'][span[0]:span[1]]
        return ({'title': 'Defence', 'sections': copy.deepcopy(sections), 'citations': [], 'questions': [],
                 'answer_supported': True, 'design': ''}, {'input_tokens': 1, 'output_tokens': 1})
    monkeypatch.setattr(provider, '_call', call)
    provider.generate({**CONFIG, 'parallel_parts': True}, data, SLIDES, 'not-a-job', token_limit=120_000,
                      on_plan=shown.append)
    assert len(written) == len(provider.parallel_spans(10, 'pptx'))
    for sections in [shown[0]] + [sections for _, sections in written]:
        for section, slot in zip(sections, blueprint):
            assert section['layout'] in slot['layouts'], section['id']
            if slot['heading_mode'] == 'fixed':
                assert section['heading'] == slot['heading']['uz'], section['id']
            else:
                assert section['heading'].startswith('Planned'), section['id']


def test_a_category_paper_is_held_to_its_own_bounds_at_the_checkpoint(monkeypatch):
    """provider.py:720: validate_content is given categories.bounds(data); a deck and a Boshqa draft keep today's."""
    from apps.studio import domain, provider_usage
    from tests.test_generation_quality import model, reply
    seen = []
    monkeypatch.setattr(domain, 'validate_content', lambda *args, **kwargs: seen.append(kwargs) or args[1])
    for name in ('start_attempt', 'received', 'finish'):
        monkeypatch.setattr(provider_usage, name, lambda *args, **kwargs: None)
    model(monkeypatch, lambda body, number: reply(body, {
        s['id']: {'heading': 'H', 'body': 'B.'} for s in sent(body)['outline']['sections']}))
    job = SimpleNamespace(account=None)
    paper = draft(3)
    paper['options']['category'] = 'pdf.xat.ariza'
    deck_data = deck(catalogue.get('slides.himoya'), 5, 'en')
    for data, feature in ((paper, DOCUMENT), (deck_data, SLIDES), (draft(3), DOCUMENT)):
        provider._call(CONFIG, data, feature, f'key-{feature}', token_limit=120_000, job=job)
    assert [kwargs.get('category') for kwargs in seen] == [catalogue.PAPER_BOUNDS, None, None]
    assert 'category' not in seen[1] and 'category' not in seen[2]
