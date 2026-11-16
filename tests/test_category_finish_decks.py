"""The finish of a category deck: dressed, grounded, guarded, its cover and sources held to the customer, its pins.

Architecture 3.6, 4 and 7. The decks are made as a job makes them, with the
fixtures standing in for the model (tests/fixtures/categories/deck_*.json,
read by the deck sample tool's own `draft`). Every person, organisation and
figure in them is invented.
"""
import copy
import json
from pathlib import Path

import pytest

from apps.studio import title_lines
from apps.studio.categories import catalogue, facts, finish, sample, skeleton
from apps.studio.categories.catalogue import build, read
from apps.studio.scripts import violations

FIXTURES = Path(__file__).parent / 'fixtures' / 'categories'
HIMOYA = 'slides.himoya'


def fixture(case):
    return json.loads((FIXTURES / f'deck_himoya_{case}.json').read_text(encoding='utf-8'))


def made(case, locale='uz', length=10):
    """(data, content) of a new himoya deck as the job has it after title_lines.apply, before the finish."""
    data, content = sample.draft(catalogue.get(HIMOYA), fixture(case), locale, length)
    return data, title_lines.apply(data, content)


def section(content, slot_id, data, instance=1):
    """The slide of `content` that is the `instance`-th of slot `slot_id` in `data`'s deck."""
    uses = skeleton.parts(catalogue.get(HIMOYA), len(data['content']['sections']), skeleton.cues_of(data))
    wanted = next(use.section_id for use in uses if use.part['id'] == slot_id and use.instance == instance)
    return next(item for item in content['sections'] if item['id'] == wanted)


def lines(text):
    return [line for line in text.split('\n') if line.strip()]


def with_sources_slot(monkeypatch):
    """The catalogue with a sources slide on himoya, as the mavzu deck has one: only under cue:sources."""
    entries, templates, index = read()
    slides = entries[HIMOYA]['parts']
    closing = next(part for part in slides if part['id'] == 'rahmat')
    slides.insert(slides.index(closing), {
        'id': 'manbalar', 'kind': 'slide', 'heading': {'uz': 'Manbalar', 'ru': 'Источники', 'en': 'Sources'},
        'heading_mode': 'fixed', 'need': 'usual', 'layouts': ['bullets'], 'pins': ['bullets.classic'],
        'source': 'customer', 'write': 'One row per source the customer gave.', 'when': 'cue:sources', 'from': 5})
    built = build(entries, templates, index)
    monkeypatch.setattr(catalogue, '_catalogue', lambda: built)
    return built.entries[HIMOYA]


# ---------------------------------------------------------------- what is not a category deck


@pytest.mark.parametrize('options', [{}, {'category': 'pdf.xat.ariza'}])
def test_a_draft_without_a_deck_category_is_left_as_it_is(options):
    data = {'options': options, 'prompt': 'Toshkent haqida 2026-yil', 'output_locale': 'uz',
            'output_format': 'pptx', 'content': {'sections': [{'id': 's1'}]}}
    content = {'title': 'Toshkent', 'sections': [{'id': 's1', 'heading': 'Toshkent — 2026', 'body': '1990-yil'}]}
    kept = copy.deepcopy(content)
    assert finish.apply(data, content) == (content, [])
    assert finish.apply(data, content)[0] is content
    assert content == kept
    assert finish.pins(data, content) == {}
    assert finish.exempt(data) == set()


def test_an_unknown_category_never_raises_here():
    data = {'options': {'category': 'slides.gone'}, 'output_locale': 'uz', 'content': {'sections': []}}
    content = {'title': 'x', 'sections': []}
    assert finish.apply(data, content) == (content, [])
    assert finish.pins(data, content) == {} and finish.exempt(data) == set()


# ---------------------------------------------------------------- the customer's own figures


@pytest.mark.parametrize('locale', ['uz', 'ru', 'en'])
@pytest.mark.parametrize('length', [3, 6, 10, 15])
def test_a_deck_made_of_the_customers_own_figures_loses_nothing(locale, length):
    data, content = made('figures', locale, length)
    before = copy.deepcopy(content)
    codes = []
    finished, warnings = finish.apply(data, content, file_names=[], codes=codes)
    assert (warnings, codes) == ([], [])
    assert content == before, 'the content handed in is never changed'
    assert len(finished['sections']) == length
    cover = lines(finished['sections'][0]['body'])
    assert len(cover) == 5 and cover == lines(before['sections'][0]['body']), 'every line the customer gave stays'
    if length >= 6:
        figures = section(finished, 'natija', data)
        assert [item['value'] for item in figures['items']] == ['28 %', '14 %']
        assert '11' in finished['sections'][-2]['body'] or '11' in section(finished, 'xulosa', data)['body']
    assert not violations(finished, locale)


def test_the_cover_keeps_the_dictated_lines_as_title_lines_placed_them():
    data, content = made('figures', 'ru')
    finished, _ = finish.apply(data, content, file_names=[])
    assert 'Выполнил: Юсупов Джасур, группа 412' in lines(finished['sections'][0]['body'])
    assert 'Ташкент — 2026' in lines(finished['sections'][0]['body'])


# ---------------------------------------------------------------- what the model added


@pytest.mark.parametrize('locale', ['uz', 'ru', 'en'])
def test_a_topic_only_deck_keeps_its_honest_forms_and_loses_what_the_model_made_up(locale):
    data, content = made('topic_only', locale)
    codes = []
    finished, warnings = finish.apply(data, content, file_names=[], codes=codes)
    assert warnings == [finish.FACTS_BLANKED]
    assert {'cover:line', 'ground:number', 'ground:law', 'ground:quote'} <= set(codes)
    assert all(':' in code and code.split(':')[0] in ('cover', 'ground', 'source', 'finish') for code in codes)
    cover = lines(finished['sections'][0]['body'])
    # The work type is the customer's own words; the city, the year and the stand-ins for names are not.
    assert len(cover) == 1 and '2026' not in cover[0]
    assert not any('2026' in text or 'Rahbar' in text for text in cover)
    result = section(finished, 'natija', data)
    assert '35' not in result['heading'] + result['body'] and facts.BLANK in result['heading']
    assert lines(section(finished, 'natija', data, 2)['body']) == lines(section(content, 'natija', data, 2)['body'])
    conclusions = section(finished, 'xulosa', data)['body']
    assert '81' not in conclusions and len(lines(conclusions)) == 2, 'the made-up law goes, the form stays'
    relevance = section(finished, 'dolzarblik', data)
    assert facts.BLANK in relevance['body'] and lines(relevance['body'])[0] == \
        lines(section(content, 'dolzarblik', data)['body'])[0]
    closing = lines(finished['sections'][-1]['body'])
    assert len(closing) == 1, 'a stand-in author line on the closing slide goes too'
    assert not violations(finished, locale)


def test_a_draft_slot_keeps_general_knowledge_a_customer_slot_does_not():
    data, content = made('topic_only')
    known = 'Kichik korxonalar 1991-yildan beri rivojlanmoqda'
    section(content, 'dolzarblik', data)['body'] = known
    section(content, 'natija', data, 2)['body'] = known
    finished, _ = finish.apply(data, content, file_names=[])
    assert section(finished, 'dolzarblik', data)['body'] == known
    assert section(finished, 'natija', data, 2)['body'] == known.replace('1991', facts.BLANK)


def test_the_notes_items_and_columns_of_a_customer_slot_are_grounded_too():
    data, content = made('figures')
    figures = section(content, 'natija', data)
    figures['items'].append({'label': '2024-yil', 'text': '', 'value': '21 %'})
    figures['notes'] += ' 2024-yilda 21 % edi.'
    figures['columns'] = ['Foiz, 2019-2025']
    finished, warnings = finish.apply(data, content, file_names=[])
    done = section(finished, 'natija', data)
    assert warnings == [finish.FACTS_BLANKED]
    assert done['items'][2]['value'] == f'{facts.BLANK} %' and '21' not in done['notes']
    assert '2019' not in done['columns'][0]


def test_a_document_in_another_language_than_the_message_leaves_names_to_the_translation():
    data, content = made('figures', 'en')
    data['prompt'] = fixture('figures')['prompt']['ru']
    title_lines.apply(data, content)
    section(content, 'natija', data, 3)['body'] = 'Namuna State University staff were given a mentor'
    finished, _ = finish.apply(data, content, file_names=[])
    assert section(finished, 'natija', data, 3)['body'] == 'Namuna State University staff were given a mentor'


# ---------------------------------------------------------------- dressing, and a change


def test_a_new_deck_is_dressed_again_after_the_model():
    data, content = made('figures')
    for item in content['sections']:
        item['heading'] = item['heading'] or 'Model'
    section(content, 'xulosa', data)['heading'] = 'Yakun'
    section(content, 'xulosa', data)['layout'] = 'timeline'
    finished, _ = finish.apply(data, content, file_names=[])
    conclusions = section(finished, 'xulosa', data)
    assert conclusions['heading'] == catalogue.get(HIMOYA).part('xulosa')['heading']['uz']
    assert conclusions['layout'] == 'bullets'
    assert [item['id'] for item in finished['sections']] == [f's{number}' for number in range(1, 11)]


def change(data, content, request, *, selected=None):
    """The draft of a change to the deck `content`: the domain keeps the first message beside the request."""
    data = copy.deepcopy(data)
    data['revision'] = {'request': request, 'original_prompt': data['prompt'], 'before': content}
    if selected:
        data['revision']['selected_section_ids'] = selected
    data['prompt'] = request
    data['content'] = copy.deepcopy(content)
    return data


def test_a_change_keeps_headings_and_grounds_every_slide_it_cannot_place():
    data, content = made('figures')
    first, _ = finish.apply(data, content, file_names=[])
    data = change(data, first, 'Xulosani qisqartiring')
    revised = copy.deepcopy(first)
    section(revised, 'xulosa', data)['heading'] = 'Yakun'
    # The customer moved a slide: what stands where the relevance slide was is not believed to be a draft slot.
    section(revised, 'dolzarblik', data)['heading'] = 'Yangi slayd'
    section(revised, 'dolzarblik', data)['body'] = 'Korxona 1991-yilda ochilgan'
    section(revised, 'maqsad_vazifalar', data)['body'] += '\nKorxona 1991-yilda ochilgan'
    finished, _ = finish.apply(data, revised, file_names=[])
    assert section(finished, 'xulosa', data)['heading'] == 'Yakun', 'a change is never dressed'
    assert '1991' not in section(finished, 'dolzarblik', data)['body']
    assert '1991' in section(finished, 'maqsad_vazifalar', data)['body'], 'a draft slot still headed as one'
    assert '28 %' in section(finished, 'xulosa', data)['body'], 'the first message is still the customer’s'


def test_a_change_to_selected_slides_finishes_only_those():
    data, content = made('topic_only')
    data = change(data, content, '5-slaydni qayta yozing', selected=['s5'])
    finished, _ = finish.apply(data, content, file_names=[])
    for before, after in zip(content['sections'], finished['sections']):
        if after['id'] != 's5':
            assert after == before
    assert finished['title'] == content['title']
    assert '35' not in finished['sections'][4]['body']


# ---------------------------------------------------------------- the sources slide


def test_a_sources_slide_keeps_only_sources_the_customer_gave_and_never_a_file_name(monkeypatch):
    entry = with_sources_slot(monkeypatch)
    data, content = made('figures')
    data['prompt'] += '\nAdabiyotlar ro‘yxati:\n1. Karimov A. Kadrlar boshqaruvi. Toshkent, 2021.'
    data['source_ids'] = ['f1']
    data['excerpts'] = [{'asset_id': 'f1', 'page': 1, 'text': 'Rahimova N. Xodimlarni saqlash. Samarqand, 2019.'}]
    blueprint = [use.part['id'] for use in skeleton.parts(entry, 10, skeleton.cues_of(data))]
    assert 'manbalar' in blueprint
    sources = content['sections'][blueprint.index('manbalar')]
    sources['body'] = ('1. Karimov A. Kadrlar boshqaruvi. Toshkent, 2021.\n2. Rahimova N. Xodimlarni saqlash. '
                       'Samarqand, 2019.\n3. Armstrong M. Human Resource Management. London, 2014.\n4. tezis.docx')
    codes = []
    finished, warnings = finish.apply(data, content, file_names=['tezis.docx'], codes=codes)
    kept = lines(finished['sections'][blueprint.index('manbalar')]['body'])
    assert kept == ['1. Karimov A. Kadrlar boshqaruvi. Toshkent, 2021.',
                    '2. Rahimova N. Xodimlarni saqlash. Samarqand, 2019.']
    assert 'source:dropped' in codes and warnings == [finish.FACTS_BLANKED]
    assert finished['sections'][blueprint.index('manbalar')]['heading'] == 'Manbalar'


def test_a_sources_slide_with_nothing_left_is_a_numbered_form(monkeypatch):
    entry = with_sources_slot(monkeypatch)
    data, content = made('topic_only')
    data['source_ids'] = ['f1']
    blueprint = [use.part['id'] for use in skeleton.parts(entry, 10, skeleton.cues_of(data))]
    sources = content['sections'][blueprint.index('manbalar')]
    sources.update(body='', items=[{'label': '1', 'text': 'Armstrong M. Human Resource Management, 2014', 'value': ''}])
    finished, _ = finish.apply(data, content, file_names=[])
    done = finished['sections'][blueprint.index('manbalar')]
    assert done['items'] == [] and lines(done['body']) == [f'{number}. {facts.BLANK}' for number in (1, 2, 3)]


# ---------------------------------------------------------------- never raises


def test_a_slide_that_cannot_be_finished_becomes_a_form(monkeypatch):
    data, content = made('figures')

    def broken(*args, **kwargs):
        raise RuntimeError('boom')
    monkeypatch.setattr(facts, 'ground', broken)
    codes = []
    finished, warnings = finish.apply(data, content, file_names=[], codes=codes)
    figures = section(finished, 'natija', data)
    assert figures['items'] == [] and set(lines(figures['body'])) == {facts.BLANK}
    assert 'finish:form' in codes and warnings == [finish.FACTS_BLANKED]
    assert lines(finished['sections'][0]['body']) == lines(content['sections'][0]['body'])


def test_a_deck_that_cannot_be_finished_at_all_is_not_a_failed_job(monkeypatch):
    data, content = made('figures')
    monkeypatch.setattr(skeleton, 'parts', lambda *args, **kwargs: 1 / 0)
    finished, warnings = finish.apply(data, content, file_names=[])
    assert warnings == [] and len(finished['sections']) == 10
    assert finish.pins(data, content) == {} and finish.exempt(data) == set()


# ---------------------------------------------------------------- pins and exemptions


def test_pins_are_the_slots_own_in_the_layout_each_slide_will_be_drawn_with():
    from apps.studio import variants
    from apps.studio.slides import prepare_slides
    data, content = made('figures', length=15)
    finished, _ = finish.apply(data, content, file_names=[])
    pinned = finish.pins(data, finished)['variants']
    kinds = {item['id']: kind for kind, _, item in prepare_slides(finished, 'uz', {})[0]}
    entry = catalogue.get(HIMOYA)
    uses = {use.section_id: use for use in skeleton.parts(entry, 15, skeleton.cues_of(data))}
    assert 's1' not in pinned and 's15' not in pinned, 'a cover and a closing slide have no variants'
    for section_id, pin in pinned.items():
        variants.get(pin)
        assert pin.split('.')[0] == kinds[section_id]
        offered = [item for item in uses[section_id].part['pins'] if item.startswith(kinds[section_id] + '.')]
        assert pin in (offered or [f'{kinds[section_id]}.{name}' for name in entry.look['variants'][kinds[section_id]]])
    assert pinned[section(finished, 'natija', data)['id']] == 'stats.rows'
    assert pinned[section(finished, 'natija', data, 2)['id']] == 'big_number.classic'


def test_pins_take_the_entrys_look_when_the_slot_names_none_and_skip_what_is_not_registered(monkeypatch):
    entries, templates, index = read()
    slot = next(part for part in entries[HIMOYA]['parts'] if part['id'] == 'xulosa')
    slot['pins'] = []
    built = build(entries, templates, index)
    monkeypatch.setattr(catalogue, '_catalogue', lambda: built)
    data, content = made('figures')
    finished, _ = finish.apply(data, content, file_names=[])
    assert finish.pins(data, finished)['variants'][section(finished, 'xulosa', data)['id']] == 'bullets.lead_line'
    assert not finish._registered('bullets.no_such_variant')


def test_a_change_gets_no_new_pins():
    data, content = made('figures')
    assert finish.pins(change(data, content, 'Rangini o‘zgartiring'), content) == {}


def test_the_finished_deck_draws_with_its_pins(tmp_path):
    from apps.studio.slides import render_pptx
    data, content = made('figures', 'en', 6)
    finished, _ = finish.apply(data, content, file_names=[])
    pinned = finish.pins(data, finished)
    deck = render_pptx(finished, tmp_path / 'deck.pptx', 'en', 'user_document', style={'deck_design': 'boardroom'},
                       pins=pinned)
    assert deck['page_count'] == 6
    held = {item['id']: variant for item, variant in zip(finished['sections'], deck['metadata']['variants'])}
    for section_id, pin in pinned['variants'].items():
        assert held[section_id] == pin or section_id in deck['metadata']['repinned']


def test_repeating_slots_of_honest_forms_are_exempt_from_being_sent_back_as_duplicates(monkeypatch):
    data, _ = made('topic_only', length=10)
    results = [use.section_id for use in skeleton.parts(catalogue.get(HIMOYA), 10, skeleton.cues_of(data))
               if use.part['id'] == 'natija']
    assert len(results) == 3 and finish.exempt(data) == set(results)
    entries, templates, index = read()
    slot = next(part for part in entries[HIMOYA]['parts'] if part['id'] == 'natija')
    slot.update(source='draft', heading_mode='fixed', heading={'uz': 'Natija', 'ru': 'Результат', 'en': 'Result'})
    built = build(entries, templates, index)
    monkeypatch.setattr(catalogue, '_catalogue', lambda: built)
    assert finish.exempt(data) == set(results), 'a fixed heading that repeats is exempt too'
    slot.update(heading_mode='model', heading=None)
    built = build(entries, templates, index)
    monkeypatch.setattr(catalogue, '_catalogue', lambda: built)
    assert finish.exempt(data) == set(), 'a drafted slide that repeats another is still sent back'


# ---------------------------------------------------------------- the sample tool


def test_the_sample_tool_draws_every_case_through_the_finish(tmp_path, capsys):
    assert sample.main(['--deck', HIMOYA, '--lengths', '3,6', '--locale', 'uz,en', '--case', 'figures,topic_only',
                        '--out', str(tmp_path)]) == 0
    printed = capsys.readouterr().out
    for case in ('figures', 'topic_only'):
        for locale in ('uz', 'en'):
            for length in (3, 6):
                stem = f'{HIMOYA}-{case}-{locale}-{length}'
                assert (tmp_path / f'{stem}.pptx').is_file() and (tmp_path / f'{stem}.png').is_file()
                assert f'ok   {stem}: {length} slides' in printed
    assert 'took out cover:line' in printed


def test_the_sample_tool_draws_blank_forms_for_an_entry_without_samples(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(sample, 'sample_path', lambda *args: None)
    assert sample.main(['--deck', HIMOYA, '--lengths', '4', '--case', 'figures', '--out', str(tmp_path)]) == 0
    assert 'has no figures sample' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        sample.main(['--deck', 'pdf.xat.ariza', '--out', str(tmp_path)])
