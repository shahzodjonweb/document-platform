"""A category draft's shape: cues, length, parts and slots, seeds, dressing, sizes, and the review question."""
import copy
import itertools
import math

import pytest

from apps.core.errors import DomainError
from apps.studio import pages as paging
from apps.studio.categories import asking, catalogue, skeleton
from apps.studio.categories.catalogue import SOURCES_CUE, build, read
from apps.studio.categories.skeleton import (FACTS, cues, dress, length, pages, pages_in, parts, seed, slots, spans,
                                             words)


# No cue holds: cues is a required argument, so a test says so.
NONE = frozenset()


def files():
    return copy.deepcopy(read())


def entry(entry_id):
    return catalogue.get(entry_id)


def ids(sections):
    return [section['id'] for section in sections]


def made(monkeypatch, change):
    """The catalogue with `change(entries)` applied, built (so it still holds together) and in force."""
    entries, templates, index = files()
    change(entries)
    built = build(entries, templates, index)
    monkeypatch.setattr(catalogue, '_catalogue', lambda: built)
    return built


def prose(part_id, **more):
    return {'id': part_id, 'kind': 'prose', 'heading': None, 'heading_mode': 'model', 'need': 'required',
            'write': 'Write this part from the brief.', 'block': 'paragraph', **more}


@pytest.fixture
def paper(monkeypatch):
    """A long paper that fills its count: the ariza turned into one with chapters and a sources part."""
    def change(entries):
        raw = entries['pdf.xat.ariza']
        raw['length'] = {'unit': 'pages', 'mode': 'count', 'target': 'count', 'default': 10, 'min': 2, 'max': 30,
                         'by_cue': [{'cue': 'long', 'default': 20}]}
        raw['cues'] = {'long': {'uz': ['batafsil'], 'ru': ['подробн'], 'en': ['detailed']}}
        raw['groups'] = {'chapter': {'min': 1, 'max': 3, 'sized': 'model'},
                         'note': {'min': 1, 'max': 4, 'sized': 'length'}}
        # The letter's own parts become a small front and back; the chapters are the paper.
        for part in raw['parts']:
            part['share'] = 0.05 if part['id'] == 'request' else 0.01 if part['id'] == 'title' else 0.02
        raw['parts'][7:7] = [
            prose('chapter_head', group='chapter', share=0.3, elastic=True),
            prose('chapter_body', group='chapter', share=0.3, elastic=True),
            {**prose('note', group='note', share=0.08), 'kind': 'list'},
            {**prose('sources', share=0.02, when='cue:sources'), 'kind': 'sources'},
            prose('old', retired=True, share=0.1),
        ]
    return made(monkeypatch, change).entries['pdf.xat.ariza']


# ---------------------------------------------------------------- the slot proof


def unfilled(deck):
    """Where a deck breaks the slot proof: (cues, length, slot ids) for every length and cue subset that fails.

    It must give exactly the length, the cover first, and every required slot
    that exists at that length and those cues. Below the entry's minimum, which
    only a plan ceiling makes, required slots may leave, but the length and the
    cover still hold.
    """
    names = sorted(set(deck.raw['cues']) | {SOURCES_CUE})
    required = [part for part in deck.parts if part['need'] == 'required']
    failed = []
    for size in range(len(names) + 1):
        for chosen in itertools.combinations(names, size):
            held = skeleton.effective(deck, chosen)
            for count in range(1, deck.length['max'] + 1):
                made_slots = slots(deck, count, held)
                present = {part['id'] for part in made_slots}
                if (len(made_slots) != count or made_slots[0]['layouts'][0] != 'cover'
                        or count >= deck.length['min'] and any(part['id'] not in present for part in required
                                                               if skeleton._exists(part, count, held))):
                    failed.append((sorted(held), count, [part['id'] for part in made_slots]))
    return failed


def test_every_deck_gives_exactly_its_length_under_every_cue_subset():
    decks = [item for item in catalogue._catalogue().entries.values() if item.service == 'slides']
    assert decks, 'the catalogue holds no deck to prove'
    for deck in decks:
        assert unfilled(deck) == [], deck.id


def test_the_slot_proof_finds_a_deck_that_cannot_fill_its_length(monkeypatch):
    def change(entries):
        for part in entries['slides.himoya']['parts']:
            if 'repeat' in part:
                part['repeat']['max'] = 2
    failed = unfilled(made(monkeypatch, change).entries['slides.himoya'])
    assert failed and all(len(slide_ids) < count for _, count, slide_ids in failed)
    assert ([], 30) in [(held, count) for held, count, _ in failed]


def test_the_himoya_slots_follow_the_defence_order():
    himoya = entry('slides.himoya')
    assert [part['id'] for part in slots(himoya, 3, NONE)] == ['cover', 'maqsad_vazifalar', 'natija_xulosa']
    assert [part['id'] for part in slots(himoya, 10, frozenset({'bmi'}))] == [
        'cover', 'dolzarblik', 'maqsad_vazifalar', 'obyekt_predmet_metodlar', 'natija', 'natija', 'natija',
        'ilmiy_amaliy', 'xulosa', 'rahmat']
    internship = [part['id'] for part in slots(himoya, 8, frozenset({'internship'}))]
    assert internship[:2] == ['cover', 'baza'] and 'natija' not in internship and 'natija_amaliyot' in internship
    assert [use.section_id for use in parts(himoya, 6, NONE)] == ['s1', 's2', 's3', 's4', 's5', 's6']
    repeated = [use.instance for use in parts(himoya, 10, frozenset({'bmi'})) if use.part['id'] == 'natija']
    assert repeated == [1, 2, 3]


# ---------------------------------------------------------------- cues


def test_cues_start_words_in_every_language_and_exclusive_keeps_the_first():
    himoya = entry('slides.himoya')
    assert cues(himoya, 'Bitiruv malakaviy ishimni himoya qilish', has_files=False) == {'bmi'}
    assert cues(himoya, 'Нужно 10 слайдов для защиты ВКР', has_files=False) == {'bmi'}
    assert cues(himoya, 'Slides for my course paper defence', has_files=False) == {'kurs'}
    # Typed apostrophes all fold to one, so the internship stem is found however o‘ was typed.
    assert cues(himoya, 'Amaliyotni o‘tash bo‘yicha himoya', has_files=False) == {'internship'}
    assert cues(himoya, 'Amaliyotni oʻtash', has_files=False) == {'internship'}
    # A master's dissertation about banking practice is a master's dissertation.
    assert cues(himoya, 'Magistrlik dissertatsiyasi, BMI va amaliyot hisoboti', has_files=False) == {'masters'}
    # A short stem is not found inside another word.
    assert cues(himoya, 'Please submit the deck', has_files=False) == frozenset()
    assert cues(entry('pdf.xat.ariza'), 'Ariza kerak', has_files=False) == frozenset()


def test_the_sources_cue_holds_with_files_or_a_word_for_references():
    ariza = entry('pdf.xat.ariza')
    assert cues(ariza, 'Ariza kerak', has_files=True) == {SOURCES_CUE}
    for text in ('Adabiyotlar ro‘yxati bilan', 'adabiyotlar royxati ham', 'Foydalanilgan manbalarni qo‘shing',
                 'со списком литературы', 'Список использованной литературы', 'с использованными источниками',
                 'with references', 'a bibliography too', 'a list of sources', 'Mavzu: suv\nManbalar: darslik',
                 'Topic: water\nSources:\n1. A textbook'):
        assert SOURCES_CUE in cues(ariza, text, has_files=False), text


# slides.mavzu's own bot example, in its three languages: a seminar topic with a survey, no source supplied.
SEMINAR = {
    'uz': 'Ekologiya fanidan seminar uchun slayd kerak: “Qayta tiklanuvchi energiya manbalari”. 2-kurs, 8 ta '
          'slayd, oddiy tilda. Guruhdagi so‘rovnoma: 30 kishidan 17 tasi quyoshni, 8 tasi shamolni, 5 tasi suvni '
          'istiqbolli deb tanladi.\nBirinchi slaydga:\nNamuna davlat universiteti\nFan: Ekologiya\n'
          'Bajardi: Karimova Dilnoza, 205-guruh\nQabul qildi: dotsent Rahimov B.\nToshkent, 2026',
    'ru': 'Нужна презентация для семинара по экологии: «Возобновляемые источники энергии». 2 курс, 8 слайдов, '
          'простым языком. Опрос в группе: из 30 человек 17 выбрали солнце, 8 ветер, 5 воду как самое '
          'перспективное.\nНа первом слайде:\nОбразцовый государственный университет\nПредмет: Экология\n'
          'Выполнила: Каримова Дилноза, группа 205\nПроверил: доцент Рахимов Б.\nТашкент, 2026',
    'en': 'I need slides for an ecology seminar: “Renewable energy sources”. Year 2, 8 slides, plain language. A '
          'survey in my group: of 30 people, 17 chose solar, 8 wind and 5 water as the most promising.\n'
          'On the first slide:\nExample State University\nSubject: Ecology\nPrepared by: Dilnoza Karimova, '
          'group 205\nChecked by: Assoc. Prof. B. Rahimov\nTashkent, 2026',
}


def test_a_topic_that_names_sources_or_literature_is_not_a_reference_list():
    # A deck without supplied sources has no sources slide: these are topics, in every language alike.
    ariza = entry('pdf.xat.ariza')
    for text in ('Qayta tiklanuvchi energiya manbalari', 'Возобновляемые источники энергии', 'Renewable energy sources',
                 'O‘zbek adabiyoti darsi uchun', 'Источники права', 'Suv manbalarini muhofaza qilish',
                 'Renewable energy sources: solar, wind and water', 'Русская литература: Пушкин',
                 'Energiya manbalari: quyosh va shamol', *SEMINAR.values()):
        assert SOURCES_CUE not in cues(ariza, text, has_files=False), text
    assert all(cues(ariza, text, has_files=True) == {SOURCES_CUE} for text in SEMINAR.values())


def test_the_cues_of_a_draft_are_read_from_its_brief_and_files():
    data = {'options': {'category': 'slides.himoya'}, 'prompt': 'Himoya uchun slayd', 'source_text': 'Kurs ishi',
            'source_ids': []}
    assert skeleton.cues_of(data) == {'kurs'}
    assert skeleton.cues_of({**data, 'excerpts': [{'asset_id': 'a', 'page': 1, 'text': 'x'}]}) == {'kurs', 'sources'}
    change = {**data, 'prompt': 'Rangini o‘zgartir', 'source_text': '',
              'revision': {'original_prompt': 'Magistrlik dissertatsiyasi himoyasi'}}
    assert skeleton.cues_of(change) == {'masters'}
    assert skeleton.cues_of({'options': {}, 'prompt': 'Kurs ishi'}) == frozenset()


# ---------------------------------------------------------------- length


def test_a_count_takes_the_pick_then_the_brief_then_a_cue_then_the_default_within_its_bounds():
    himoya = entry('slides.himoya')
    assert length(himoya) == 10
    assert length(himoya, cues=frozenset({'kurs'})) == 6
    assert length(himoya, cues=frozenset({'kurs', 'masters'})) == 15, 'by_cue is read in its own order'
    assert length(himoya, asked=12, cues=frozenset({'kurs'})) == 12
    assert length(himoya, chosen=7, asked=12, cues=frozenset({'kurs'})) == 7
    assert length(himoya, asked=2) == 3 and length(himoya, asked=90) == 30
    assert length(himoya, asked=25, ceiling=20) == 20


def test_the_plan_ceiling_wins_even_over_an_entrys_minimum():
    assert length(entry('slides.himoya'), ceiling=2) == 2
    assert length(entry('pdf.xat.ariza'), ceiling=1) == 1


def test_a_deck_below_its_minimum_still_has_exactly_the_slides_quoted():
    himoya = entry('slides.himoya')
    assert himoya.length['min'] == 3
    # The quote says what length() says; the seed must hold that many slides, the cover first.
    for ceiling in (1, 2):
        count = length(himoya, ceiling=ceiling)
        assert len(seed(himoya, count, NONE)) == count == ceiling
    assert [part['id'] for part in slots(himoya, 2, NONE)] == ['cover', 'maqsad_vazifalar']
    assert [part['id'] for part in slots(himoya, 1, frozenset({'bmi'}))] == ['cover']


def test_a_fixed_length_is_always_its_default():
    ariza = entry('pdf.xat.ariza')
    assert length(ariza) == 1
    assert length(ariza, asked=5, chosen=3, questions=10) == 1


def test_a_derived_length_follows_the_questions_and_reads_pages_only_without_a_count():
    test = entry('pdf.test')
    # 20 questions: 7 on the first page, 10 on the second, 3 on the third, and a page of key.
    assert length(test) == 4 and length(test, questions=20) == 4
    assert length(test, questions=10) == 3
    assert length(test, questions=40) == 6
    assert length(test, questions=400) == 6, 'never more questions than the entry allows'
    assert length(test, asked=2) == 2
    assert length(test, asked=2, questions=30) == 5
    assert length(test, chosen=9) == 4, 'no stepper for a derived length'
    assert length(test, questions=40, ceiling=3) == 3


# ---------------------------------------------------------------- parts and seeds


def test_a_paper_seeds_its_facts_then_one_blank_section_per_written_part():
    sections = seed(entry('pdf.xat.ariza'), 1, NONE)
    assert ids(sections) == [FACTS, 'request', 'statements', 'enclosures']
    assert [section['layout'] for section in sections] == ['list', 'text', 'list', 'list']
    for section in sections:
        assert (section['heading'], section['body'], section['notes'], section['items']) == ('', '', '', [])
    test = seed(entry('pdf.test'), 4, NONE)
    assert ids(test) == [FACTS, 'passage'] and test[1]['layout'] == 'callout'
    listed = [(use.section_id, use.part['id']) for use in parts(entry('pdf.xat.ariza'), 1, NONE)]
    assert listed[:4] == [(None, 'addressee'), (None, 'applicant'), (None, 'title'), ('request', 'request')]


def test_a_model_sized_group_is_seeded_at_its_max_and_repeats_together(paper):
    found = ids(seed(paper, 10, NONE))
    assert found == [FACTS, 'request', 'statements', 'enclosures', 'chapter_head', 'chapter_body', 'chapter_head_2',
                     'chapter_body_2', 'chapter_head_3', 'chapter_body_3', 'note', 'note_2']
    instances = [(use.section_id, use.instance, use.group) for use in parts(paper, 10, NONE) if use.group == 'chapter']
    assert instances[2] == ('chapter_head_2', 2, 'chapter')
    assert paper.part('chapter_body_3')['id'] == 'chapter_body'


def test_a_length_sized_group_grows_with_the_pages(paper):
    def notes(count):
        return [section for section in ids(seed(paper, count, NONE)) if section.startswith('note')]
    assert notes(2) == ['note']
    assert notes(16) == ['note', 'note_2', 'note_3']
    assert notes(30) == ['note', 'note_2', 'note_3', 'note_4']
    assert [len(notes(count)) for count in range(2, 31)] == sorted(len(notes(count)) for count in range(2, 31))


def test_parts_follow_their_cues_and_retired_parts_are_never_seeded(paper):
    assert 'sources' not in ids(seed(paper, 10, NONE))
    assert 'sources' in ids(seed(paper, 10, frozenset({SOURCES_CUE})))
    assert seed(paper, 10, frozenset({SOURCES_CUE}))[-1]['layout'] == 'list'
    assert all(not section.startswith('old') for section in ids(seed(paper, 30, frozenset({SOURCES_CUE}))))


def test_a_deck_seeds_each_slide_with_its_slots_first_layout():
    himoya = entry('slides.himoya')
    sections = seed(himoya, 10, frozenset({'bmi'}))
    assert ids(sections) == [f's{number}' for number in range(1, 11)]
    assert [section['layout'] for section in sections] == [
        'cover', 'bullets', 'bullets', 'bullets', 'chart', 'chart', 'chart', 'bullets', 'bullets', 'closing']
    assert sections[0] == {'id': 's1', 'heading': '', 'body': '', 'notes': '', 'layout': 'cover', 'items': [],
                           'columns': [], 'image_query': ''}


def test_local_authoring_puts_the_customers_words_where_a_file_can_still_be_made(paper):
    assert seed(entry('pdf.xat.ariza'), 1, NONE, text='Ta’til so‘rayman.')[1]['body'] == 'Ta’til so‘rayman.'
    assert seed(paper, 10, NONE, text='Matn')[1]['body'] == 'Matn', 'the first elastic prose part'
    deck = seed(entry('slides.himoya'), 3, NONE, text='Birinchi\n\nIkkinchi\n\nUchinchi\n\nTo‘rtinchi')
    assert [section['body'] for section in deck] == ['Birinchi', 'Ikkinchi', 'Uchinchi\n\nTo‘rtinchi']


# ---------------------------------------------------------------- dressing


def deck_data(**more):
    sections = seed(entry('slides.himoya'), 10, frozenset({'bmi'}))
    return {'options': {'category': 'slides.himoya'}, 'prompt': 'BMI himoyasi uchun slayd', 'source_text': '',
            'output_locale': 'uz', 'content': {'sections': sections}, **more}


def test_dress_puts_back_the_fixed_headings_and_the_slot_layouts():
    data = deck_data()
    planned = copy.deepcopy(data['content']['sections'])
    for section in planned:
        section.update(heading='Modelning sarlavhasi', layout='timeline')
    planned[4]['layout'] = 'stats'
    dressed = dress(data, planned)
    assert dressed is planned
    assert [section['id'] for section in dressed] == [f's{number}' for number in range(1, 11)]
    assert dressed[1]['heading'] == entry('slides.himoya').part('dolzarblik')['heading']['uz']
    assert dressed[0]['heading'] == 'Modelning sarlavhasi', 'a model heading is the model’s'
    assert dressed[4]['heading'] == 'Modelning sarlavhasi' and dressed[4]['layout'] == 'stats'
    assert dressed[0]['layout'] == 'cover' and dressed[1]['layout'] == 'bullets' and dressed[9]['layout'] == 'closing'
    english = dress(deck_data(output_locale='en'), copy.deepcopy(planned))
    assert english[8]['heading'] == 'Conclusions and recommendations'
    assert dress(deck_data(output_locale='ru'), copy.deepcopy(planned))[8]['heading'] == \
        entry('slides.himoya').part('xulosa')['heading']['ru']


def test_dress_dresses_a_part_of_the_deck_by_its_ids():
    data = deck_data()
    part = [{'id': 's9', 'heading': 'x', 'layout': 'auto'}, {'id': 'q1', 'heading': 'y', 'layout': 'auto'}]
    dress(data, part)
    assert part == [{'id': 's9', 'heading': entry('slides.himoya').part('xulosa')['heading']['uz'],
                     'layout': 'bullets'}, {'id': 'q1', 'heading': 'y', 'layout': 'auto'}]


def test_dress_clears_a_headless_slot_and_reads_the_cues_its_seed_was_made_with_files_included(monkeypatch):
    def change(entries):
        slides = entries['slides.himoya']['parts']
        closing = next(part for part in slides if part['id'] == 'rahmat')
        closing.update(heading=None, heading_mode='none')
        slides.insert(slides.index(closing), {
            'id': 'manbalar', 'kind': 'slide', 'heading': {'uz': 'Manbalar', 'ru': 'Источники', 'en': 'Sources'},
            'heading_mode': 'fixed', 'need': 'usual', 'layouts': ['bullets'], 'pins': [], 'source': 'customer',
            'write': 'One row per source the customer gave.', 'when': 'cue:sources', 'from': 5})
    himoya = made(monkeypatch, change).entries['slides.himoya']
    # The sources cue comes from the attached file, not the prompt: dress must read it as the seed did.
    data = {'options': {'category': 'slides.himoya'}, 'prompt': 'BMI himoyasi uchun slayd', 'source_text': '',
            'output_locale': 'en', 'source_ids': ['a1']}
    held = skeleton.cues_of(data)
    assert held == {'bmi', SOURCES_CUE}
    data['content'] = {'sections': seed(himoya, 10, held)}
    blueprint = slots(himoya, 10, held)
    assert 'manbalar' in [part['id'] for part in blueprint]
    assert 'manbalar' not in [part['id'] for part in slots(himoya, 10, skeleton.cues_of({**data, 'source_ids': []}))]
    planned = [{'id': section['id'], 'heading': 'Model', 'layout': 'auto'} for section in data['content']['sections']]
    dress(data, planned)
    for section, slot in zip(planned, blueprint):
        wanted = {'fixed': (slot['heading'] or {}).get('en'), 'none': '', 'model': 'Model'}[slot['heading_mode']]
        assert (section['heading'], section['layout']) == (wanted, slot['layouts'][0]), slot['id']
    assert planned[-1]['heading'] == '' and blueprint[-1]['id'] == 'rahmat'


def test_dress_leaves_a_change_a_paper_and_a_boshqa_deck_alone():
    planned = [{'id': 's2', 'heading': 'Mine', 'layout': 'timeline'}]
    for data in (deck_data(revision={'request': 'x'}), {'options': {}, 'content': {'sections': planned}},
                 {'options': {'category': 'pdf.xat.ariza'}, 'content': {'sections': planned}}):
        assert dress(data, copy.deepcopy(planned)) == planned


# ---------------------------------------------------------------- sizes


def test_a_ceiling_paper_gets_word_maximums_only():
    ariza = entry('pdf.xat.ariza')
    found = {use.part['id']: words(ariza, use, 1, NONE) for use in parts(ariza, 1, NONE)}
    assert found['request'] == (0, 90), 'a ceiling keeps the top of its own words'
    assert found['addressee'] == (0, 0), 'a fixed part is drawn, not written'
    assert found['enclosures'] == (0, round(0.1 * skeleton.CAPACITY_WORDS)), 'what its share of a page holds'
    assert words(entry('pdf.test'), parts(entry('pdf.test'), 4, NONE)[4], 4, NONE) == (60, 120)


def test_a_count_paper_gets_word_targets_and_its_elastic_parts_take_what_is_left(paper):
    uses = {use.section_id: use for use in parts(paper, 10, NONE) if use.section_id}
    low, high = words(paper, uses['chapter_head'], 10, NONE)
    assert 0 < low < high
    # The chapters split their share between three instances and take up what the absent parts leave.
    assert high > round(0.3 / 3 * 10 * skeleton.TARGET_WORDS)
    assert words(paper, uses['chapter_head_2'], 10, NONE) == (low, high)
    # The notes are not elastic: two at ten pages, each half of their own share.
    assert skeleton.instances(paper, 'note', 10) == 2
    note = round(0.08 / 2 * 10 * skeleton.TARGET_WORDS)
    assert words(paper, uses['note'], 10, NONE) == (round(note * skeleton.LOW_SHARE), note)
    assert words(paper, uses['request'], 10, NONE) == (25, 90)


def test_no_part_is_asked_for_more_than_its_stored_body_holds(paper):
    # validate_content cuts a body at pages.max_section_chars, mid-sentence; a word target must stay under it.
    assert skeleton.SECTION_WORDS * paging.CHARS_PER_WORD <= paging.max_section_chars('pdf')
    uses = {use.section_id: use for use in parts(paper, 30, NONE) if use.section_id}
    uncapped = round(skeleton._shares(paper, 30, NONE)['chapter_head'][0] * 30 * skeleton.TARGET_WORDS)
    assert uncapped > skeleton.SECTION_WORDS, 'a long chapter of a long paper reaches the cap'
    assert words(paper, uses['chapter_head'], 30, NONE)[1] == skeleton.SECTION_WORDS
    # A part spans gives a call of its own is so bounded too: its reply fits one call's budget.
    assert paging.response_tokens(skeleton.SECTION_WORDS * paging.CHARS_PER_WORD / paging.CHARS_PER_PAGE) \
        < paging.RESPONSE_CEILING


def test_every_paper_entry_asks_each_part_for_what_a_body_holds_at_its_longest():
    papers = [item for item in catalogue._catalogue().entries.values() if item.service == 'pdf']
    assert papers, 'the catalogue holds no paper to prove'
    for paper in papers:
        names = sorted(set(paper.raw.get('cues') or {}) | {SOURCES_CUE})
        longest = min(paper.length['max'], 35)
        for size in range(len(names) + 1):
            for chosen in itertools.combinations(names, size):
                held = skeleton.effective(paper, chosen)
                for use in parts(paper, longest, held):
                    low, high = words(paper, use, longest, held)
                    assert 0 <= low <= high <= skeleton.SECTION_WORDS, (paper.id, use.section_id, sorted(held))


def test_a_count_papers_written_shares_fill_its_pages(paper):
    shares = skeleton._shares(paper, 10, frozenset())
    fixed = sum(part.get('share', 0) for part in paper.parts if part['kind'] == 'fixed' and not part.get('retired'))
    assert sum(share for share, _ in shares.values()) + fixed == pytest.approx(1)


def paper_data(**options):
    return {'options': {'category': 'pdf.xat.ariza', **options}, 'prompt': 'Batafsil', 'source_text': '',
            'content': {'sections': seed(catalogue.get('pdf.xat.ariza'), options.get('length', 10),
                                         frozenset({'long'}))}}


def test_pages_is_a_papers_length_and_none_for_anything_else(paper):
    assert pages(paper_data(length=25)) == 25
    # The domain always writes the length, held to the plan; a recomputed default would skip that clamp.
    for stored in ({}, {'length': 0}, {'length': '10'}, {'length': True}):
        missing = paper_data()
        missing['options'].update(stored)
        with pytest.raises(DomainError) as refused:
            pages(missing)
        assert refused.value.code == 'invalid_parameters'
    assert pages({'options': {'category': 'pdf.test', 'length': 4}}) == 4
    assert pages({'options': {'category': 'slides.himoya', 'length': 10}}) is None
    assert pages({'options': {'length': 10}}) is None


def test_pages_in_counts_a_spans_share_of_the_pages_and_one_a_section_otherwise(paper):
    data = paper_data(length=10)
    fixed = sum(part.get('share', 0) for part in paper.parts if part['kind'] == 'fixed')
    assert pages_in(data, 0, len(data['content']['sections'])) == math.ceil((1 - fixed) * 10), \
        'the written parts take what the fixed parts leave of ten pages'
    assert pages_in(data, 0, 1) == 1, 'the facts are no pages, but a call is at least one'
    plain = {'options': {}, 'content': {'sections': [{'id': f's{n}'} for n in range(1, 8)]}}
    assert pages_in(plain, 2, 7) == 5
    assert pages_in({**plain, 'options': {'category': 'slides.himoya'}}, 0, 3) == 3


def test_a_leftover_instance_counts_its_share_of_its_group_not_the_whole_part(paper):
    # Seeded at 30 pages (four notes), then shortened to 10: a new total keeps the sections, and notes 3 and 4
    # are left over. Each still counts as one of the two notes ten pages have, never as all of them.
    data = paper_data(length=30)
    data['options']['length'] = 10
    sizes = dict(skeleton._section_pages(data))
    assert {'note_3', 'note_4'} <= set(sizes)
    assert sizes['note_3'] == sizes['note_4'] == pytest.approx(0.08 / 2 * 10) == pytest.approx(sizes['note'])


def test_spans_cut_a_long_paper_by_pages_and_sections(paper):
    short = paper_data(length=10)
    assert spans(short) == [(0, len(short['content']['sections']))]
    long = paper_data(length=30)
    cut = spans(long)
    assert cut[0][0] == 0 and cut[-1][1] == len(long['content']['sections'])
    assert all(left[1] == right[0] for left, right in zip(cut, cut[1:]))
    assert len(cut) >= 3
    for start, end in cut:
        assert pages_in(long, start, end) <= paging.PAGES_PER_CALL or end - start == 1
        assert end - start <= skeleton.SECTIONS_PER_CALL
    plain = {'options': {}, 'content': {'sections': [{'id': f's{n}'} for n in range(1, 26)]}}
    assert spans(plain) == paging.batches(25)


# ---------------------------------------------------------------- the review question


def asked(monkeypatch, ask, fields=None):
    def change(entries):
        raw = entries['pdf.xat.ariza']
        raw['ask'] = {'fields': ['request'], 'review': raw['bot']['prompt'], 'prompt': raw['bot']['prompt'], **ask}
        for field in fields or ():
            next(item for item in raw['fields'] if item['id'] == field['id']).update(field)
    return made(monkeypatch, change).entries['pdf.xat.ariza']


def test_himoya_asks_only_when_the_message_holds_no_figure_and_no_file():
    himoya = entry('slides.himoya')
    assert asking.wanted(himoya, 'Kurs ishi himoyasi: “Kutubxona dasturi”', has_files=False)
    assert not asking.wanted(himoya, 'Kurs ishi himoyasi: 120 ta kitob sinaldi', has_files=False)
    assert not asking.wanted(himoya, 'Kurs ishi himoyasi', has_files=True)
    thesis, *with_figures = himoya.raw['bot']['examples']
    for example in with_figures:
        assert not any(asking.wanted(himoya, text, has_files=False) for text in example.values())
    # The first example gives a count, a group and a year, and attaches the work: its file is what it gives.
    assert all(asking.wanted(himoya, text, has_files=False) for text in thesis.values())
    assert not any(asking.wanted(himoya, text, has_files=True) for text in thesis.values())


def test_a_count_a_course_a_group_or_a_year_is_not_a_figure():
    # The bot's prompt asks for the count, so the typical message states one and holds no result.
    himoya = entry('slides.himoya')
    for text in ('Kurs ishim himoyasi uchun 6 ta slayd kerak: “Python yordamida kutubxona dasturi”',
                 '3-kurs talabasiman, kurs ishi himoyasi kerak', 'Kurs ishi himoyasi, 2026-yil',
                 'BMI himoyasi, 10 ta chiroyli slayd, 412-guruh, 7-maktab bitiruvchisi',
                 'Нужно 10 слайдов на защиту курсовой, 3 курс, группа 212, Ташкент — 2026',
                 'Слайды на защиту, 3-го курса, 9 класс, школа № 7, количество слайдов: 8',
                 'Slides for my term paper defence: 8 slides, year 2, group 205, grade 11, 12.05.2026',
                 'Kurs ishi himoyasi. Slaydlar soni 7 ta. Toshkent — 2026'):
        assert asking.wanted(himoya, text, has_files=False), text
        assert not asking.wanted(himoya, text, has_files=True), text
    for text in ('Kurs ishi himoyasi: 120 ta kitob sinaldi', '6 ta slayd, 3-kurs: qidiruv 1 soniyadan kam',
                 'Защита, 8 слайдов: точность 94%', 'Year 2 defence: 35 patients observed', 'Narxi 1500 so‘m'):
        assert not asking.wanted(himoya, text, has_files=False), text


def test_an_entry_without_a_question_never_asks():
    assert not asking.wanted(entry('pdf.xat.ariza'), '', has_files=False)
    assert not asking.wanted(entry('pdf.test'), 'Test', has_files=False)


def test_the_other_rules_of_the_question(monkeypatch):
    assert asking.wanted(asked(monkeypatch, {'when': 'always'}), 'Hammasi yozilgan: 12', has_files=True)
    few = asked(monkeypatch, {'when': 'few_words', 'threshold': 5})
    assert asking.wanted(few, 'Ta’til uchun ariza kerak', has_files=False)
    assert not asking.wanted(few, 'Direktorga o‘n kunlik ta’til uchun ariza kerak', has_files=False)
    assert asking.wanted(asked(monkeypatch, {'when': 'few_words'}), 'Ariza kerak', has_files=True), \
        'twelve words by default, files or not'
    stems = {'id': 'reason', 'cues': {'uz': ['sabab'], 'ru': ['причин'], 'en': ['because']}}
    missing = asked(monkeypatch, {'when': 'cues_missing', 'fields': ['reason']}, [stems])
    assert asking.wanted(missing, 'Ta’til uchun ariza', has_files=False)
    assert not asking.wanted(missing, 'Sababi: oilaviy holat', has_files=False)
    assert not asking.wanted(missing, 'Заявление по причине болезни', has_files=False)
    files_field = asked(monkeypatch, {'when': 'cues_missing', 'fields': ['enclosures']}, [{'id': 'enclosures',
                                                                                             'kind': 'file'}])
    assert asking.wanted(files_field, 'Ariza', has_files=False)
    assert not asking.wanted(files_field, 'Ariza', has_files=True)
