"""The finish of a category paper: its facts verified, its parts grounded or guarded, its shape and fixed words.

Architecture 3.6, 4, 5 and 6.7. Most cases run on an invented entry,
`pdf.xat.sinov`, built beside the real catalogue for the test only, so every
kind of part the paper categories use (a model-sized group, a grounded
letter part, a list, a table with a computed column, a sources list, clock
and derived fields) is covered before the entries that use them land. The
ariza and the test are the real entries. Every person, organisation, figure
and source here is invented.
"""
import copy
import datetime

import pytest

from apps.studio.categories import catalogue, derive, facts, finish, skeleton
from apps.studio.categories.catalogue import build, read
from apps.studio.scripts import violations

SINOV = 'pdf.xat.sinov'
DAY = datetime.date(2026, 11, 16)
PROMPT = ('Qodirova Malika Anvarovna nomidan Namuna davlat universitetiga xat. 2026-yil 3-noyabrda 12 ta kitob '
          'oldim, har biri 45 000 so‘m. Manbalar: Saidov B. Iqtisodiyot asoslari. Toshkent, 2021.')


def text3(uz, ru, en):
    return {'uz': uz, 'ru': ru, 'en': en}


def field(field_id, kind, missing='omit', **more):
    return {'id': field_id, 'label': text3(f'{field_id} uz', f'{field_id} ru', f'{field_id} en'),
            'example': text3('Namuna', 'Образец', 'Example'), 'kind': kind, 'need': 'optional', 'missing': missing,
            **more}


def part(part_id, kind, heading=None, mode='none', **more):
    return {'id': part_id, 'kind': kind, 'heading': heading, 'heading_mode': mode, 'need': 'required',
            'write': f'The {part_id}.', **more}


SINOV_FIELDS = [
    field('author', 'person', 'blank', max_chars=40),
    field('signer', 'person', 'blank', derived_from='author'),
    field('org', 'org'),
    field('year', 'date', 'blank', clock='year'),
    field('made_on', 'date', 'blank', clock='date'),
    field('city', 'place', 'if_needed'),
    field('level', 'choice', choices=['school', 'university']),
    field('handout', 'flag'),
    field('attached', 'file'),
    field('topics', 'list'),
    field('amount', 'money', 'blank'),
]
SINOV_PARTS = [
    part('kirish', 'prose', text3('Kirish', 'Введение', 'Introduction'), 'fixed', share=0.1, elastic=True),
    part('bob', 'prose', mode='model', group='boblar', share=0.4, elastic=True),
    part('bob_xulosa', 'prose', text3('Bob bo‘yicha xulosa', 'Выводы по главе', 'Chapter summary'), 'fixed',
         group='boblar', share=0.1),
    part('maktub', 'prose', grounded=True, share=0.1, words=[25, 90]),
    part('ilova', 'list', text3('Ilova:', 'Приложение:', 'Enclosure:'), 'fixed', need='optional', share=0.05,
         max_items=3, grounded=True),
    part('narxlar', 'table', text3('Narxlar', 'Цены', 'Prices'), 'fixed', share=0.1,
         columns=[text3('Nomi', 'Название', 'Item'), text3('Soni', 'Кол-во', 'Quantity'),
                  text3('Narxi', 'Цена', 'Price'), text3('Jami', 'Сумма', 'Amount')],
         computed=[{'column': 3, 'op': 'product', 'of': [1, 2]}], total=[3]),
    part('manbalar', 'sources', text3('Manbalar', 'Источники', 'Sources'), 'fixed', share=0.05),
    part('imzo', 'fixed', text3('Imzo', 'Подпись', 'Signature'), 'fixed', share=0.05, block='signature_row',
         fields=['signer', 'made_on']),
]


@pytest.fixture
def sinov(monkeypatch):
    """The catalogue with the invented paper entry in the letters group, and Tashkent's clock held at DAY."""
    entries, templates, index = read()
    raw = copy.deepcopy(entries['pdf.xat.ariza'])
    children = index['groups']['pdf.xat']['children']
    children.insert(children.index('other'), SINOV)
    raw.update(id=SINOV, order=children.index(SINOV) + 1, title='model', fields=SINOV_FIELDS, parts=SINOV_PARTS,
               groups={'boblar': {'min': 1, 'max': 4, 'sized': 'model'}}, templates=['official_sinov'],
               quality='repair',
               length={'unit': 'pages', 'mode': 'count', 'target': 'count', 'default': 5, 'min': 1, 'max': 20})
    entries[SINOV] = raw
    template = copy.deepcopy(templates['official_ariza'])
    template.update(id='official_sinov', entries=[SINOV], flow=[{'block': 'paragraph', 'part': 'kirish'}], labels={})
    templates['official_sinov'] = template
    built = build(entries, templates, index)
    monkeypatch.setattr(catalogue, '_catalogue', lambda: built)
    monkeypatch.setattr(finish, 'today', lambda: DAY)
    return built.entries[SINOV]


def draft(entry, prompt=PROMPT, locale='uz', length=5, **more):
    """Draft data as the job holds it: the entry's seed at `length` pages."""
    data = {'options': {'category': entry.id, 'length': length}, 'prompt': prompt, 'output_locale': locale,
            'output_format': 'pdf', 'excerpts': [], 'source_ids': [], **more}
    data['content'] = {'title': '', 'sections': skeleton.seed(entry, length, skeleton.cues_of(data)),
                       'questions': [], 'citations': []}
    return data


def answer(data, **sections):
    """The model's answer: every seeded section, empty unless given (a dict merged into the seed's section)."""
    made = []
    for seeded in data['content']['sections']:
        section = copy.deepcopy(seeded)
        section.update(sections.get(seeded['id'], {}))
        made.append(section)
    return {'title': sections.get('title', ''), 'sections': made, 'questions': sections.get('questions', []),
            'citations': []}


def facts_of(content):
    section = next(item for item in content['sections'] if item['id'] == 'facts')
    return {item['label']: item['text'] for item in section['items']}


def section_of(content, section_id):
    return next(item for item in content['sections'] if item['id'] == section_id)


def finished(data, content, **options):
    codes = []
    made, warnings = finish.apply(data, content, file_names=options.pop('file_names', []), codes=codes, **options)
    return made, warnings, codes


# ---------------------------------------------------------------- what is not a paper


def test_a_draft_without_a_category_is_left_as_it_is():
    data = {'options': {}, 'prompt': 'x', 'output_locale': 'uz', 'content': {'sections': []}}
    content = {'title': 'Toshkent', 'sections': [{'id': 's1', 'heading': 'Toshkent — 2026', 'body': '1990-yil'}]}
    assert finish.apply(data, content) == (content, [])
    assert finish.apply(data, content, only={'s1'})[0] is content
    assert finish.plain(data, content) is content
    assert finish.exempt(data) == set()


def test_an_unknown_paper_category_never_raises_here():
    data = {'options': {'category': 'pdf.gone', 'length': 1}, 'output_locale': 'uz', 'content': {'sections': []}}
    content = {'title': 'x', 'sections': []}
    assert finish.apply(data, content) == (content, [])
    assert finish.plain(data, content) is content
    assert finish.exempt(data) == set()


# ---------------------------------------------------------------- facts


def test_facts_keep_only_what_the_customer_gave_each_held_to_its_kind(sinov):
    data = draft(sinov)
    content = answer(data, facts={'items': [
        {'label': 'author', 'text': 'Qodirova Malika Anvarovna'},
        {'label': 'signer', 'text': 'M. A. Qodirova'},
        {'label': 'org', 'text': 'Yulduz Invest MChJ'},          # an organisation the customer never named
        {'label': 'city', 'text': '____'},                       # if_needed: the blank is kept
        {'label': 'amount', 'text': '____'},                     # blank policy: the template draws it, not kept
        {'label': 'level', 'text': 'University'},
        {'label': 'handout', 'text': 'yes'},
        {'label': 'attached', 'text': 'kitob.pdf'},
        {'label': 'topics', 'text': 'Iqtisodiyot'},
        {'label': 'topics', 'text': 'Kitoblar'},
        {'label': 'author', 'text': 'Saidova Nodira'},           # a second value for a field that holds one
        {'label': 'colour', 'text': 'qizil'},                    # no such field
    ]})
    made, warnings, codes = finished(data, content)
    assert facts_of(made) == {'author': 'Qodirova Malika Anvarovna', 'signer': 'M. A. Qodirova', 'year': '2026',
                              'made_on': '2026-yil 16-noyabr', 'city': '____', 'level': 'university',
                              'handout': 'true', 'topics': 'Iqtisodiyot\nKitoblar'}
    assert list(facts_of(made)) == [item['id'] for item in sinov.fields if item['id'] in facts_of(made)]
    assert codes == ['fact:org'] and warnings == [finish.FACTS_BLANKED]
    section = section_of(made, 'facts')
    assert (section['heading'], section['body'], section['layout']) == ('', '', 'list')


def test_a_derived_fact_is_held_to_the_verified_value_it_is_made_from(sinov):
    data = draft(sinov)
    content = answer(data, facts={'items': [{'label': 'author', 'text': 'Qodirova Malika'},
                                            {'label': 'signer', 'text': 'B. Qodirova'}]})
    made, _, codes = finished(data, content)
    assert 'signer' not in facts_of(made) and codes == ['fact:signer'], 'B. is no initial of Malika'
    # Without a verified base the signer is not kept, even when the prompt names that person.
    content = answer(data, facts={'items': [{'label': 'signer', 'text': 'M. A. Qodirova'}]})
    made, _, codes = finished(data, content)
    assert 'signer' not in facts_of(made) and codes == ['fact:signer']


def test_an_invented_person_date_or_sum_is_not_a_fact(sinov):
    data = draft(sinov)
    content = answer(data, facts={'items': [{'label': 'author', 'text': 'Rahimov Javlon'},
                                            {'label': 'amount', 'text': '99 000 so‘m'},
                                            {'label': 'made_on', 'text': '5-dekabr'}]})
    made, warnings, codes = finished(data, content)
    assert facts_of(made) == {'year': '2026', 'made_on': '2026-yil 16-noyabr'}
    # The invented date is replaced by today's, which leaves no blank to count.
    assert codes == ['fact:author', 'fact:amount'] and warnings == [finish.FACTS_BLANKED]


def test_the_customers_own_numbers_pass_however_they_are_written(sinov):
    data = draft(sinov)
    content = answer(data, facts={'items': [{'label': 'amount', 'text': '45000 so‘m'},
                                            {'label': 'made_on', 'text': '03.11.2026'}]})
    made, warnings, codes = finished(data, content)
    assert facts_of(made)['amount'] == '45000 so‘m' and facts_of(made)['made_on'] == '03.11.2026'
    assert (warnings, codes) == ([], [])


def test_a_long_value_is_cut_at_a_words_end(sinov):
    data = draft(sinov, prompt='Qodirova Malika Anvarovna Toshkentova Namunaxon qizi Kamolova Zuhra')
    long = 'Qodirova Malika Anvarovna Toshkentova Namunaxon qizi Kamolova Zuhra'
    made, _, _ = finished(data, answer(data, facts={'items': [{'label': 'author', 'text': long}]}))
    assert facts_of(made)['author'] == 'Qodirova Malika Anvarovna Toshkentova'
    assert len(facts_of(made)['author']) <= 40


def test_a_translated_paper_still_holds_its_organisations_names_and_never_a_person(sinov):
    # A paper's org, place, line and list facts are drawn in letterheads and signature rows, so translation never
    # switches their names off: a translated organisation that does not fold to the customer's words goes.
    data = draft(sinov, prompt='Письмо от Кодировой Малики в Образцовый государственный университет, 12 книг.',
                 locale='uz')
    content = answer(data, facts={'items': [{'label': 'org', 'text': 'Namunaviy davlat universiteti'},
                                            {'label': 'author', 'text': 'Qodirova Malika'},
                                            {'label': 'signer', 'text': 'M. Qodirova'}]})
    made, _, codes = finished(data, content)
    assert 'org' not in facts_of(made) and codes == ['fact:org'], 'a false blank, never an invention'
    assert facts_of(made)['author'] == 'Qodirova Malika' and facts_of(made)['signer'] == 'M. Qodirova'
    # An organisation the customer named in its own letters stays, its lower-case words translated.
    data = draft(sinov, prompt='Письмо от Кодировой Малики в государственный университет Namuna, 12 книг.',
                 locale='uz')
    made, _, codes = finished(data, answer(data, facts={'items': [
        {'label': 'org', 'text': 'Namuna davlat universiteti'}]}))
    assert facts_of(made)['org'] == 'Namuna davlat universiteti' and codes == []
    content = answer(data, facts={'items': [{'label': 'author', 'text': 'Rahimov Javlon'}]})
    assert finished(data, content)[2] == ['fact:author']


# ---------------------------------------------------------------- clock values


@pytest.mark.parametrize('locale, date', [('uz', '2026-yil 16-noyabr'), ('ru', '16 ноября 2026 г.'),
                                          ('en', '16 November 2026')])
def test_clock_fields_are_written_by_code_from_the_tashkent_date(sinov, locale, date):
    data = draft(sinov, locale=locale)
    made, warnings, codes = finished(data, answer(data))
    assert facts_of(made) == {'year': '2026', 'made_on': date}
    assert (warnings, codes) == ([], []), 'a clock value is code\'s, not a blank'
    assert not violations(made, locale)


def test_clock_values_follow_the_calendar():
    assert finish.clock_value('date', 'uz', datetime.date(2027, 1, 5)) == '2027-yil 5-yanvar'
    assert finish.clock_value('date', 'uz', datetime.date(2026, 9, 1)) == '2026-yil 1-sentabr'
    assert finish.clock_value('date', 'uz', datetime.date(2026, 10, 1)) == '2026-yil 1-oktabr'
    assert finish.clock_value('date', 'ru', datetime.date(2026, 3, 8)) == '8 марта 2026 г.'
    assert finish.clock_value('year', 'en', datetime.date(2027, 12, 31)) == '2027'


def test_finish_today_is_tashkents_calendar_day(monkeypatch):
    from django.utils import timezone
    late = datetime.datetime(2026, 11, 16, 20, 30, tzinfo=datetime.timezone.utc)
    monkeypatch.setattr(timezone, 'now', lambda: late)
    assert finish.today() == datetime.date(2026, 11, 17), '20:30 UTC is already the next day in Tashkent'


def test_a_clock_field_the_customer_filled_keeps_their_value(sinov):
    data = draft(sinov)
    made, _, codes = finished(data, answer(data, facts={'items': [{'label': 'year', 'text': '2021'}]}))
    assert facts_of(made)['year'] == '2021' and codes == []


def test_a_paper_without_a_facts_section_still_gets_its_clock_values(sinov):
    data = draft(sinov)
    content = answer(data, kirish={'body': 'Kirish matni.'})
    content['sections'] = [section for section in content['sections'] if section['id'] != 'facts']
    made, _, _ = finished(data, content)
    assert facts_of(made)['year'] == '2026'
    # The job trims sections past the quoted count by position: the facts go last, never pushing a part out.
    assert made['sections'][-1]['id'] == 'facts' and made['sections'][0]['id'] == 'kirish'


def test_a_clock_value_the_customer_never_gave_is_todays_without_a_blank(sinov):
    data = draft(sinov, prompt='Qodirova Malika nomidan Namuna davlat universitetiga xat.')
    content = answer(data, facts={'items': [{'label': 'year', 'text': '2026'},
                                            {'label': 'made_on', 'text': '2025-yil 1-mart'}]})
    made, warnings, codes = finished(data, content)
    assert facts_of(made) == {'year': '2026', 'made_on': '2026-yil 16-noyabr'}
    assert (warnings, codes) == ([], []), 'nothing is blank: code writes the value back'
    # A whole-document change re-finishes the value the first finish wrote, which the prompt does not hold either.
    data['revision'] = {'request': 'Qisqartiring', 'original_prompt': data['prompt']}
    again, warnings, codes = finished(data, made)
    assert facts_of(again) == facts_of(made) and (warnings, codes) == ([], [])


# ---------------------------------------------------------------- grounding and guarding by part


def test_a_grounded_part_loses_every_number_name_quotation_and_law_the_customer_did_not_give(sinov):
    data = draft(sinov)
    body = ('Men 12 ta kitob oldim, har biri 45 000 so‘m. Hisob-kitobni dekan Rahimov J. tasdiqladi. '
            'Jami 780 000 so‘m to‘landi. Rektor aytganidek: «Bilim — eng katta boylik bo‘ladi». '
            'Fuqarolik kodeksining 386-moddasiga muvofiq to‘lov qaytarilmaydi.')
    made, warnings, codes = finished(data, answer(data, maktub={'body': body}))
    text = section_of(made, 'maktub')['body']
    assert '12 ta kitob' in text and '45 000' in text
    assert 'Rahimov' not in text and ' J.' not in text, 'an invented name goes whole, its initials too'
    assert '780 000' not in text and '«' not in text and 'kodeks' not in text
    assert {'ground:name', 'ground:number', 'ground:quote', 'ground:law'} == set(codes)
    assert warnings == [finish.FACTS_BLANKED]


def test_a_guarded_part_keeps_general_knowledge_but_no_quotation_or_law(sinov):
    data = draft(sinov)
    body = ('Iqtisodiyot fani Adam Smit asarlari bilan 1776-yilda shakllana boshlagan. '
            'U shunday yozgan: «Mehnat taqsimoti boylikning asosiy manbaidir». '
            'Soliq kodeksining 12-moddasi bu sohani tartibga soladi.')
    made, _, codes = finished(data, answer(data, kirish={'body': body}))
    text = section_of(made, 'kirish')['body']
    assert 'Adam Smit' in text and '1776' in text
    assert '«' not in text and 'kodeks' not in text
    assert set(codes) == {'ground:quote', 'ground:law'}


def test_every_part_gets_its_layout_and_fixed_heading_in_the_documents_language(sinov):
    for locale, heading in (('uz', 'Kirish'), ('ru', 'Введение'), ('en', 'Introduction')):
        data = draft(sinov, locale=locale)
        content = answer(data, kirish={'heading': 'Muqaddima', 'layout': 'image', 'body': 'Matn.'},
                         maktub={'heading': 'Xat', 'layout': 'list', 'body': 'Matn.'},
                         bob={'heading': 'Iqtisodiyot asoslari', 'layout': 'table', 'body': 'Matn.'})
        made, _, _ = finished(data, content)
        assert (section_of(made, 'kirish')['heading'], section_of(made, 'kirish')['layout']) == (heading, 'text')
        assert (section_of(made, 'maktub')['heading'], section_of(made, 'maktub')['layout']) == ('', 'text')
        assert section_of(made, 'bob')['heading'] == 'Iqtisodiyot asoslari', 'a model heading stays the model\'s'
        assert section_of(made, 'bob')['layout'] == 'text'
        assert section_of(made, 'bob_xulosa')['heading'] == {'uz': 'Bob bo‘yicha xulosa', 'ru': 'Выводы по главе',
                                                             'en': 'Chapter summary'}[locale]


def test_a_model_heading_is_guarded_and_a_fixed_heading_is_never_checked(sinov):
    data = draft(sinov)
    content = answer(data, bob={'heading': '«Bozor o‘zini o‘zi boshqaradi va tartibga soladi»', 'body': 'Matn.'})
    made, _, codes = finished(data, content)
    assert section_of(made, 'bob')['heading'] == '____' and codes == ['ground:quote']


def test_the_title_is_guarded_or_the_categorys_name(sinov):
    data = draft(sinov)
    made, _, codes = finished(data, answer(data, title='Rahimov Javlon bilan hisob-kitob'))
    assert 'Rahimov' not in made['title'] and 'ground:name' in codes, 'a fact-led paper\'s title is grounded'
    ariza = catalogue.get('pdf.xat.ariza')
    data = draft(ariza, length=1)
    for locale, name in (('uz', 'Ariza'), ('ru', 'Заявление'), ('en', 'Official request')):
        data['output_locale'] = locale
        assert finished(data, answer(data, title='Dekanga ariza'))[0]['title'] == name


# ---------------------------------------------------------------- lists, tables, sources


def test_a_list_written_as_lines_becomes_items_held_to_its_maximum(sinov):
    data = draft(sinov)
    body = '1. Kitoblar ro‘yxati.\n2. To‘lov cheki.\n- Shartnoma nusxasi.\n4. Ma’lumotnoma.'
    made, _, _ = finished(data, answer(data, ilova={'body': body, 'layout': 'text'}))
    section = section_of(made, 'ilova')
    assert section['layout'] == 'list' and section['body'] == '' and section['heading'] == 'Ilova:'
    assert [item['text'] for item in section['items']] == ['Kitoblar ro‘yxati.', 'To‘lov cheki.',
                                                          'Shartnoma nusxasi.']


def test_a_tables_computed_cells_are_emptied_for_derive_and_its_columns_never_stored(sinov, monkeypatch):
    # What the finish empties, seen before derive fills it (tests/test_category_derive.py holds what derive makes).
    monkeypatch.setattr(derive, 'apply', lambda entry, content, trusted, **_: content)
    data = draft(sinov)
    rows = [{'label': 'Kitob', 'text': '12 | 45 000', 'value': '540 000'},
            {'label': 'Daftar', 'text': '12', 'value': '9 999'},
            {'label': 'Ruchka', 'text': '12 | 45 000 | 3 | 4', 'value': ''}]
    made, _, codes = finished(data, answer(data, narxlar={'items': rows, 'columns': ['A', 'B', 'C', 'D']}))
    section = section_of(made, 'narxlar')
    assert section['columns'] == [] and section['layout'] == 'table' and section['heading'] == 'Narxlar'
    # Daftar has no price, so derive has nothing to multiply: its amount is the customer's own line total, kept and
    # held as the part's other cells are (this test table is guarded; every business table is grounded).
    assert [finish.cells(item, 4) for item in section['items']] == [
        ['Kitob', '12', '45 000', ''], ['Daftar', '12', '', '9 999'], ['Ruchka', '12', '45 000 | 3 | 4', '']]
    assert codes == [], 'the model\'s own arithmetic is emptied, not counted as a blank'


def test_cells_pad_and_merge_a_row_to_its_columns():
    assert finish.cells({'label': 'a', 'text': 'b | c | d', 'value': 'e'}, 3) == ['a', 'b | c | d', 'e']
    assert finish.cells({'label': 'a', 'text': '', 'value': 'e'}, 4) == ['a', '', '', 'e']
    assert finish.cells({'label': 'a', 'text': 'b', 'value': 'e'}, 2) == ['a | b', 'e']
    assert finish.cells({'label': 'a', 'text': 'b', 'value': 'e'}, 1) == ['a | b | e'], 'one column keeps the value'
    assert finish.cells({'label': '', 'text': '', 'value': 'e'}, 1) == ['e']
    assert finish.cells({'label': 'a', 'text': 'b | c', 'value': 'e'}) == ['a', 'b', 'c', 'e']
    assert finish.cells({'label': 'a', 'text': '| c', 'value': 'e'}, 4) == ['a', '', 'c', 'e'], 'a tidied empty cell'
    assert finish.cells({'label': 'a', 'text': 'b |', 'value': 'e'}, 4) == ['a', 'b', '', 'e']


def test_derive_fills_the_computed_cells_after_grounding(sinov, monkeypatch):
    seen = []

    def fill(entry, content, trusted, **_):
        section = section_of(content, 'narxlar')
        seen.append([finish.cells(item, 4) for item in section['items']])
        for item in section['items']:
            item['value'] = '540 000'
        return content
    monkeypatch.setattr(derive, 'apply', fill)
    data = draft(sinov)
    made, _, codes = finished(data, answer(data, narxlar={'items': [{'label': 'Kitob', 'text': '12 | 45 000',
                                                                     'value': '1 000 000'}]}))
    assert seen == [[['Kitob', '12', '45 000', '']]]
    assert section_of(made, 'narxlar')['items'][0]['value'] == '540 000' and codes == []


def test_sources_keep_only_what_the_customer_named_never_a_file_name(sinov):
    data = draft(sinov)
    items = [{'label': '1', 'text': 'Saidov B. Iqtisodiyot asoslari. Toshkent, 2021.'},
             {'label': '2', 'text': 'Karimov A. Bozor iqtisodiyoti. Toshkent, 2019.'},
             {'label': '3', 'text': 'hisobot_2026.docx'}]
    made, warnings, codes = finished(data, answer(data, manbalar={'items': items}),
                                     file_names=['hisobot_2026.docx'])
    section = section_of(made, 'manbalar')
    assert [item['text'] for item in section['items']] == ['Saidov B. Iqtisodiyot asoslari. Toshkent, 2021.']
    assert section['heading'] == 'Manbalar' and section['layout'] == 'list'
    assert codes == ['source:dropped'] and warnings == [finish.FACTS_BLANKED]


def test_sources_with_none_verified_are_left_empty_for_the_ruled_form(sinov):
    data = draft(sinov, prompt='Kitob sotib olish haqida xat.')
    made, _, codes = finished(data, answer(data, manbalar={'body': '1. Karimov A. Bozor. Toshkent, 2019.'}))
    section = section_of(made, 'manbalar')
    assert section['items'] == [] and section['body'] == '' and codes == ['source:dropped']


def test_an_uzbek_paper_with_cyrillic_sources_reads_back_in_latin(sinov):
    data = draft(sinov, prompt='Xat. Manbalar ilova qilingan.',
                 excerpts=[{'asset_id': 'a1', 'page': 1, 'text': 'Саидов Б. Основы экономики. Ташкент, 2021.'}])
    items = [{'label': '1', 'text': 'Саидов Б. Основы экономики. Ташкент, 2021.'}]
    made, _, codes = finished(data, answer(data, manbalar={'items': items}), file_names=['Саидов_экономика.docx'])
    assert codes == []
    assert section_of(made, 'manbalar')['items'][0]['text'].startswith('Saidov B.')
    assert not violations(made, 'uz')


# ---------------------------------------------------------------- groups


def test_empty_instances_of_a_model_sized_group_are_dropped(sinov):
    data = draft(sinov)
    ids = [section['id'] for section in data['content']['sections']]
    assert {'bob', 'bob_2', 'bob_3', 'bob_4', 'bob_xulosa_4'} <= set(ids), 'seeded at the group\'s max'
    content = answer(data, bob={'heading': 'Birinchi bob', 'body': 'Matn.'},
                     bob_xulosa_2={'body': 'Xulosa.'}, bob_3={'heading': 'Faqat sarlavha'})
    made, _, _ = finished(data, content)
    kept = [section['id'] for section in made['sections']]
    assert [item for item in kept if item.startswith('bob')] == ['bob', 'bob_xulosa', 'bob_2', 'bob_xulosa_2']


def test_an_all_empty_group_keeps_its_minimum(sinov):
    data = draft(sinov)
    made, _, _ = finished(data, answer(data))
    assert [item['id'] for item in made['sections'] if item['id'].startswith('bob')] == ['bob', 'bob_xulosa']


def test_a_later_instance_filled_alone_is_kept_without_an_empty_first(sinov):
    data = draft(sinov)
    made, _, _ = finished(data, answer(data, bob_3={'body': 'Matn.'}))
    assert [item['id'] for item in made['sections'] if item['id'].startswith('bob')] == ['bob_3', 'bob_xulosa_3']


# ---------------------------------------------------------------- only, selections, failures


def test_only_finishes_the_sections_a_top_up_wrote_and_nothing_else(sinov):
    data = draft(sinov)
    content = answer(data, title='«Uch so‘zli iqtibos bu yerda»',
                     facts={'items': [{'label': 'org', 'text': 'Yulduz Invest MChJ'}]},
                     kirish={'body': 'U «bilim eng katta boylikdir» degan.'},
                     bob={'body': 'U «bilim eng katta boylikdir» degan.'})
    made, warnings, codes = finished(data, content, only={'kirish'})
    assert section_of(made, 'kirish')['body'] == 'U ____ degan.' and codes == ['ground:quote']
    assert section_of(made, 'bob') == section_of(content, 'bob')
    assert section_of(made, 'facts') == section_of(content, 'facts'), 'facts are finished once, not per top-up'
    assert made['title'] == content['title'] and len(made['sections']) == len(content['sections'])
    assert warnings == [finish.FACTS_BLANKED]


def test_a_selected_change_finishes_only_the_selected_sections(sinov):
    data = draft(sinov)
    data['revision'] = {'request': 'Kirishni qayta yozing', 'original_prompt': PROMPT,
                        'selected_section_ids': ['kirish']}
    content = answer(data, kirish={'body': '«Bilim eng katta boylikdir» deyiladi.'},
                     maktub={'body': 'Rahimov J. tasdiqladi.'})
    made, _, codes = finished(data, content)
    assert section_of(made, 'kirish')['body'] == '____ deyiladi.'
    assert section_of(made, 'maktub')['body'] == 'Rahimov J. tasdiqladi.'
    made, _, codes = finished(data, content, only={'maktub'})
    assert made == content and codes == [], 'a top-up outside the selection touches nothing'


def test_a_part_that_cannot_be_finished_is_left_empty(sinov, monkeypatch):
    real = finish._shape

    def broken(section, part, locale):
        if section['id'] == 'maktub':
            raise RuntimeError('bug')
        return real(section, part, locale)
    monkeypatch.setattr(finish, '_shape', broken)
    data = draft(sinov)
    made, warnings, codes = finished(data, answer(data, maktub={'body': 'Rahimov J. tasdiqladi.'},
                                                  kirish={'body': 'Matn.'}))
    assert section_of(made, 'maktub')['body'] == '' and section_of(made, 'kirish')['body'] == 'Matn.'
    assert codes == ['finish:form'] and warnings == [finish.FACTS_BLANKED]


def test_the_content_handed_in_is_never_changed(sinov):
    data = draft(sinov)
    content = answer(data, maktub={'body': 'Rahimov J. 780 000 so‘m to‘ladi.'}, bob_2={'body': ''})
    before = copy.deepcopy(content)
    finished(data, content)
    assert content == before


@pytest.mark.parametrize('locale', ['uz', 'ru', 'en'])
def test_a_paper_of_the_customers_own_words_loses_nothing_and_reads_back(sinov, locale):
    data = draft(sinov, locale=locale)
    content = answer(data, facts={'items': [{'label': 'author', 'text': 'Qodirova Malika Anvarovna'}]},
                     maktub={'body': 'Qodirova Malika 2026-yil 3-noyabrda 12 ta kitob oldi.'},
                     manbalar={'items': [{'label': '1', 'text': 'Saidov B. Iqtisodiyot asoslari. Toshkent, 2021.'}]})
    made, warnings, codes = finished(data, content)
    assert (warnings, codes) == ([], [])
    assert '12 ta kitob' in section_of(made, 'maktub')['body']
    assert not violations(made, locale)


# ---------------------------------------------------------------- the real entries


def test_an_ariza_is_held_to_the_customers_words():
    ariza = catalogue.get('pdf.xat.ariza')
    prompt = ('Namuna davlat universiteti rektori nomiga ariza. Men, Qodirova Malika Anvarovna, 2-kurs talabasiman. '
              '12.11.2026 dan 19.11.2026 gacha oilaviy sabab bilan ta’til so‘rayman.')
    data = draft(ariza, prompt=prompt, length=1)
    content = answer(data, facts={'items': [
        {'label': 'addressee_org', 'text': 'Namuna davlat universiteti'},
        {'label': 'addressee_position', 'text': 'rektori'},
        {'label': 'addressee_person', 'text': 'Saidov B. T.'},
        {'label': 'applicant_name', 'text': 'Qodirova Malika Anvarovna'},
        {'label': 'signer_name', 'text': 'M. A. Qodirova'},
        {'label': 'applicant_address', 'text': '____'},
        {'label': 'date_written', 'text': '____'}]},
        request={'heading': 'Ariza', 'body': (
            'Sizdan 2026-yil 12-noyabrdan 19-noyabrgacha oilaviy sabablarga ko‘ra menga ta’til berishingizni '
            'so‘rayman. Dekan Karimov A. bilan kelishilgan. Mehnat kodeksining 131-moddasiga muvofiq.')},
        enclosures={'body': '1. Ma’lumotnoma nusxasi.\n2. Pasport nusxasi.'})
    made, warnings, codes = finished(data, content)
    assert facts_of(made) == {'addressee_org': 'Namuna davlat universiteti', 'addressee_position': 'rektori',
                              'applicant_name': 'Qodirova Malika Anvarovna', 'applicant_address': '____',
                              'signer_name': 'M. A. Qodirova'}, 'the ariza date stays a blank: it has no clock'
    request = section_of(made, 'request')
    assert request['heading'] == '' and 'Karimov' not in request['body'] and 'kodeks' not in request['body']
    assert request['body'].startswith('Sizdan 2026-yil 12-noyabrdan 19-noyabrgacha')
    enclosures = section_of(made, 'enclosures')
    assert enclosures['heading'] == 'Ilova:' and [item['text'] for item in enclosures['items']] == [
        'Ma’lumotnoma nusxasi.', 'Pasport nusxasi.']
    assert set(codes) == {'fact:addressee_person', 'ground:name', 'ground:law'}
    assert warnings == [finish.FACTS_BLANKED] and made['title'] == 'Ariza'


@pytest.mark.parametrize('field_id, value, code', [
    ('reason', 'Dekan Karimov A. ruxsati bilan oilaviy sabab', 'ground:name'),
    ('request', 'Prorektor Tursunov B. bilan kelishilgan holda ta’til berishingizni so‘rayman', 'ground:name'),
    ('request', 'Mehnat kodeksiga muvofiq ta’til berishingizni so‘rayman', 'ground:law'),
    ('reason', '«Dam olish har bir talabaning haqqi» deganidek, oilaviy sabab', 'ground:quote'),
], ids=['dean', 'vice-rector', 'law', 'quotation'])
def test_a_letters_text_fact_naming_an_invented_person_law_or_quotation_is_not_kept(field_id, value, code):
    ariza = catalogue.get('pdf.xat.ariza')
    prompt = ('Namuna davlat universiteti rektori nomiga ariza. Men, Qodirova Malika Anvarovna, 2-kurs talabasiman. '
              'Oilaviy sabab bilan ta’til so‘rayman.')
    data = draft(ariza, prompt=prompt, length=1)
    content = answer(data, facts={'items': [{'label': 'applicant_name', 'text': 'Qodirova Malika Anvarovna'},
                                            {'label': field_id, 'text': value}]})
    made, warnings, codes = finished(data, content)
    assert field_id not in facts_of(made), 'the whole value goes, never a value with a hole in it'
    assert codes == [f'fact:{field_id}'] and warnings == [finish.FACTS_BLANKED], code
    flat = repr(finish.plain(data, made))
    assert 'Karimov' not in flat and 'Tursunov' not in flat and 'kodeks' not in flat and 'haqqi' not in flat
    # The customer's own reason and request stay, numbers and all.
    content = answer(data, facts={'items': [
        {'label': 'reason', 'text': 'Oilaviy sabab bilan'},
        {'label': 'request', 'text': '2-kurs talabasi sifatida ta’til berishingizni so‘rayman'}]})
    made, warnings, codes = finished(data, content)
    assert facts_of(made) == {'reason': 'Oilaviy sabab bilan',
                              'request': '2-kurs talabasi sifatida ta’til berishingizni so‘rayman'}
    assert codes == [] and warnings == []


TRANSLATED_MINUTES = ('Составьте протокол собрания отдела продаж о плане работы на следующий квартал, подробно и '
                      'по делу.')


def test_a_translated_minutes_never_keeps_an_invented_chair_secretary_or_participant():
    # A Russian message, Uzbek minutes: the chair and secretary are line fields and the participants a list, and the
    # template draws them in the minutes' head and its signature rows, so translation must not let them through.
    minutes = catalogue.get('pdf.biz.bayonnoma')
    data = draft(minutes, prompt=TRANSLATED_MINUTES, length=2)
    assert finish._translated(data)
    invented = {'chair': 'Rais: Karimov Aziz Bahodirovich', 'secretary': 'Kotiba: Yo‘ldosheva Malika',
                'participants': 'Rahimov B.\nSaidova D.', 'organisation': 'Namuna Savdo MChJ',
                'meeting_place': 'Toshkent shahri, Navoiy ko‘chasi'}
    made, warnings, codes = finished(data, answer(data, facts={'items': [
        {'label': label, 'text': text} for label, text in invented.items()]}))
    assert not set(invented) & set(facts_of(made))
    assert set(codes) == {f'fact:{label}' for label in invented} and warnings == [finish.FACTS_BLANKED]
    # The people the customer named in Cyrillic stay in their Uzbek spelling.
    data = draft(minutes, prompt=TRANSLATED_MINUTES + ' Председатель Каримов Азиз Баходирович, секретарь Юлдашева '
                 'Малика, присутствовали Рахимов Б. и Саидова Д.', length=2)
    given = {'chair': 'Karimov Aziz Bahodirovich', 'secretary': 'Yo‘ldosheva Malika',
             'participants': 'Rahimov B.\nSaidova D.'}
    made, warnings, codes = finished(data, answer(data, facts={'items': [
        {'label': label, 'text': text} for label, text in given.items()]}))
    assert {label: facts_of(made)[label] for label in given} == given and codes == [] and warnings == []


def test_a_translated_cover_letter_never_keeps_an_invented_employer_or_recipient():
    letter = catalogue.get('pdf.xat.ishga_kirish')
    prompt = ('Menga ingliz tilida ishga kirish uchun xat yozib bering, sotuv menejeri lavozimiga, men Qodirova '
              'Malika, savdo sohasida ishlaganman va mijozlar bilan ishlashni yaxshi bilaman.')
    data = draft(letter, prompt=prompt, locale='en', length=1)
    assert finish._translated(data)
    invented = {'salutation': 'Dear Mr. Johnson,', 'employer_name': 'Bright Future Bank',
                'recipient_title': 'Recruitment Director, Bright Future Bank'}
    made, warnings, codes = finished(data, answer(data, facts={'items': [
        {'label': 'applicant_name', 'text': 'Malika Qodirova'},
        *({'label': label, 'text': text} for label, text in invented.items())]}))
    assert facts_of(made)['applicant_name'] == 'Malika Qodirova'
    assert not set(invented) & set(facts_of(made)) and set(codes) == {f'fact:{label}' for label in invented}
    # What the customer named in Latin stays, with the role and the formula words a letter capitalises.
    data = draft(letter, prompt=prompt + ' Xatni Namuna Bank kadrlar bo‘limiga yuboraman.', locale='en', length=1)
    given = {'salutation': 'Dear Hiring Manager,', 'employer_name': 'Namuna Bank'}
    made, _, codes = finished(data, answer(data, facts={'items': [
        {'label': label, 'text': text} for label, text in given.items()]}))
    assert {label: facts_of(made)[label] for label in given} == given and codes == []


@pytest.mark.parametrize('prompt', [
    'Please write a recommendation letter for my student Malika Qodirova, who studied economics with me for two '
    'years and was always careful and hard-working in class.',
    'Talabam Qodirova Malika uchun ingliz tilida tavsiyanoma yozib bering, u menda iqtisodiyot fanidan o‘qigan va '
    'darslarda doim tirishqoq va mas’uliyatli bo‘lgan.',
], ids=['english-message', 'uzbek-message'])
def test_a_recommendations_addressee_the_customer_never_gave_is_not_kept(prompt):
    letter = catalogue.get('pdf.xat.tavsiya')
    data = draft(letter, prompt=prompt, locale='en', length=1)
    made, warnings, codes = finished(data, answer(data, facts={'items': [
        {'label': 'candidate_name', 'text': 'Malika Qodirova'},
        {'label': 'addressee', 'text': 'Admissions Committee, Westbrook University'},
        {'label': 'second_signer', 'text': 'Dean | Robert Hale'}]}))
    assert facts_of(made)['candidate_name'] == 'Malika Qodirova'
    assert 'addressee' not in facts_of(made) and 'second_signer' not in facts_of(made)
    assert set(codes) == {'fact:addressee', 'fact:second_signer'} and warnings == [finish.FACTS_BLANKED]


def test_a_translated_course_papers_invented_university_is_not_kept():
    paper = catalogue.get('pdf.kurs_ishi')
    data = draft(paper, prompt='Напишите курсовую работу по экономике на тему развития малого бизнеса в регионах.',
                 length=10)
    made, _, codes = finished(data, answer(data, facts={'items': [
        {'label': 'university', 'text': 'Namuna iqtisodiyot universiteti'},
        {'label': 'kafedra', 'text': '«Moliya» kafedrasi'}]}))
    assert 'university' not in facts_of(made) and 'kafedra' not in facts_of(made)
    assert set(codes) == {'fact:university', 'fact:kafedra'}


COVER_EN = ('Please write a cover letter for the sales manager position for me, Malika Qodirova. I have worked in '
            'retail sales and I am good with customers.')
PLAN_UZ = ('Namuna Savdo MChJ uchun nonvoyxona ochish bo‘yicha biznes-reja yozib bering, mahalla aholisiga issiq non '
           'sotamiz, direktor Qodirova Malika.')


@pytest.mark.parametrize('entry_id, prompt, locale, part_id, text, left', [
    ('pdf.xat.ishga_kirish', COVER_EN, 'en', 'fit',
     'With over five years of experience in sales, I increased revenue by a third.',
     'With over ____ years of experience in sales, I increased revenue by ____.'),
    ('pdf.xat.ishga_kirish', COVER_EN, 'en', 'fit',
     'I led a team of twelve people and served two hundred clients a month.',
     'I led a team of ____ people and served ____ clients a month.'),
    ('pdf.xat.ishga_kirish', COVER_EN, 'en', 'fit', 'With over 5 years of experience, I grew sales by 30%.',
     'With over ____ years of experience, I grew sales by ____%.'),
    ('pdf.xat.ishga_kirish', 'Напишите сопроводительное письмо на должность менеджера по продажам, я Малика '
     'Кодирова, работала в рознице.', 'ru', 'fit', 'У меня более пяти лет опыта в продажах.',
     'У меня более ____ лет опыта в продажах.'),
    ('pdf.biz.biznes_reja', PLAN_UZ, 'uz', 'summary_lead',
     'Loyihaning umumiy qiymati besh yuz million so‘mni tashkil etadi.', 'Loyihaning umumiy qiymati ____ so‘mni '
     'tashkil etadi.'),
    ('pdf.biz.biznes_reja', PLAN_UZ, 'uz', 'summary_lead', 'Kredit yillik yigirma foiz stavkada olinadi.',
     'Kredit yillik ____ foiz stavkada olinadi.'),
    ('pdf.biz.biznes_reja', PLAN_UZ, 'uz', 'summary_lead', 'Loyiha uch yilda o‘zini qoplaydi.',
     'Loyiha ____ yilda o‘zini qoplaydi.'),
], ids=['five-years', 'twelve-people', 'digits', 'ru-five-years', 'project-cost', 'loan-rate', 'payback'])
def test_a_number_written_in_words_the_customer_never_gave_is_blanked(entry_id, prompt, locale, part_id, text, left):
    entry = catalogue.get(entry_id)
    data = draft(entry, prompt=prompt, locale=locale, length=1 if entry_id.startswith('pdf.xat') else 6)
    made, warnings, codes = finished(data, answer(data, **{part_id: {'body': text}}))
    assert section_of(made, part_id)['body'] == left
    assert 'ground:number' in codes and warnings == [finish.FACTS_BLANKED]


def test_a_number_in_words_the_customer_gave_is_kept_and_a_led_fact_in_words_is_held():
    letter = catalogue.get('pdf.xat.ishga_kirish')
    prompt = COVER_EN + ' I have 5 years of experience and led a team of 12.'
    data = draft(letter, prompt=prompt, locale='en', length=1)
    text = 'With five years of experience, I led a team of twelve people.'
    made, warnings, codes = finished(data, answer(data, fit={'body': text}, facts={'items': [
        {'label': 'experience_facts', 'text': 'Five years in retail sales, a team of twelve'}]}))
    assert section_of(made, 'fit')['body'] == text and codes == [] and warnings == []
    assert facts_of(made)['experience_facts'] == 'Five years in retail sales, a team of twelve'
    data = draft(letter, prompt=COVER_EN, locale='en', length=1)
    made, _, codes = finished(data, answer(data, facts={'items': [
        {'label': 'experience_facts', 'text': 'Over five years in retail sales'}]}))
    assert 'experience_facts' not in facts_of(made) and codes == ['fact:experience_facts']


def test_a_guarded_papers_text_fact_keeps_general_knowledge():
    # A test is not fact-led: its topic may name a figure of history the customer did not spell out.
    test = catalogue.get('pdf.test')
    data = draft(test, prompt='Tarix fanidan 7-sinf uchun test, mavzu: Temuriylar davri.', length=3)
    made, _, codes = finished(data, answer(data, facts={'items': [
        {'label': 'topic', 'text': 'Amir Temur va temuriylar davri'}]}))
    assert facts_of(made)['topic'] == 'Amir Temur va temuriylar davri' and codes == []


@pytest.mark.parametrize('locale, title, kept', [
    ('uz', '7-sinf tarix testi. Tuzuvchi: Karimov A.', '7-sinf tarix testi'),
    ('ru', 'Тест по истории для 7 класса. Составитель: Каримов А.', 'Тест по истории для 7 класса'),
    ('en', 'History test for year 7 — prepared by Anvar Karimov', 'History test for year 7'),
], ids=['uz', 'ru', 'en'])
def test_a_guarded_titles_invented_author_tail_goes(locale, title, kept):
    test = catalogue.get('pdf.test')
    data = draft(test, prompt='Tarix fanidan 7-sinf uchun test.', locale=locale, length=3)
    made, warnings, codes = finished(data, answer(data, title=title))
    assert made['title'] == kept and codes == ['ground:name'] and warnings == [finish.FACTS_BLANKED]


def test_a_guarded_titles_author_the_customer_gave_stays():
    test = catalogue.get('pdf.test')
    data = draft(test, prompt='Tarix fanidan 7-sinf uchun test. Tuzuvchi: Rahimova Dilnoza.', length=3)
    title = '7-sinf tarix testi. Tuzuvchi: Rahimova Dilnoza'
    made, _, codes = finished(data, answer(data, title=title))
    assert made['title'] == title and codes == []
    made, _, codes = finished(data, answer(data, title='Tuzuvchi: Karimov A.'))
    assert made['title'] == test.name('uz'), 'a title that was only an author is the category\'s name'


def test_an_empty_scope_leaves_the_paper_as_it_is(sinov):
    data = draft(sinov)
    content = answer(data, title='«Uch so‘zli iqtibos bu yerda»', kirish={'body': 'U  «bilim»  degan .'})
    made, warnings, codes = finished(data, content, only=set())
    assert made == content and warnings == [] and codes == [], 'no tidy or enforce over the whole paper'


def test_a_cut_ends_at_any_whitespace():
    assert finish._cut('Iqtisodiyot\nKitoblar\nMoliya', 15) == 'Iqtisodiyot'
    assert finish._cut('Iqtisodiyot asoslari', 15) == 'Iqtisodiyot'


def test_a_section_of_a_part_the_model_does_not_write_goes_whole_and_never_reaches_the_fallback():
    ariza = catalogue.get('pdf.xat.ariza')
    data = draft(ariza, prompt='Namuna davlat universiteti rektori nomiga ariza: ta’til so‘rayman.', length=1)
    content = answer(data, request={'body': 'Menga ta’til berishingizni so‘rayman.'})
    content['sections'] += [
        {'id': 'addressee', 'heading': '', 'body': 'Yulduz shahar 7-maktab direktori Rahimov Javlon Erkinovichga'},
        {'id': 'signature', 'heading': '', 'body': 'Imzo: Saidov B. T., 2026-yil 20-noyabr'}]
    made, warnings, codes = finished(data, content)
    ids = [section['id'] for section in made['sections']]
    assert 'addressee' not in ids and 'signature' not in ids and 'request' in ids
    assert codes == [finish.UNWRITTEN] and warnings == [], 'nothing the template draws was blanked'
    flat = finish.plain(data, content)
    text = repr(flat)
    assert 'Rahimov' not in text and 'Saidov' not in text and '7-maktab' not in text and '20-noyabr' not in text
    assert 'Menga ta’til' in text
    # A test's head and its questions part are drawn from facts and content.questions, never from a section.
    test = catalogue.get('pdf.test')
    data = draft(test, prompt='Iqtisodiyot fanidan 7-sinf uchun test.', length=3)
    content = answer(data)
    content['sections'] += [{'id': 'head', 'heading': '', 'body': 'Yulduz maktabi, 2-chorak, 3-ish'},
                            {'id': 'part_choice', 'heading': 'Savollar', 'body': '1. Nima?'}]
    made, _, codes = finished(data, content)
    assert {'head', 'part_choice'}.isdisjoint(section['id'] for section in made['sections'])
    assert codes == [finish.UNWRITTEN]


def test_a_tests_questions_are_guarded_and_a_broken_question_goes():
    test = catalogue.get('pdf.test')
    data = draft(test, prompt='Iqtisodiyot fanidan 7-sinf uchun test.', length=3)
    questions = [
        {'stem': 'Bozor iqtisodiyotining asosiy belgisi nima?', 'options': ['Raqobat', 'Reja', 'Monopoliya', 'Soliq'],
         'answer': 'Raqobat', 'explanation': '', 'marks': 1, 'topic': ''},
        {'stem': 'Prezidentning 2019-yil 17-iyuldagi PF-5775-son farmoni nimaga bag‘ishlangan?',
         'options': ['Soliqqa', 'Bankka', 'Savdoga', 'Ta’limga'], 'answer': 'Bankka', 'explanation': '',
         'marks': 1, 'topic': ''},
        {'stem': 'Kim aytgan?', 'options': ['«Bilim eng katta boylikdir»', 'Boshqa', 'Hech kim', 'Bilmayman'],
         'answer': '«Bilim eng katta boylikdir»', 'explanation': '', 'marks': 1, 'topic': ''}]
    made, warnings, codes = finished(data, answer(data, questions=questions))
    # A question a law emptied and one whose correct option lost its quotation to ____ both go: neither can be
    # answered, nor keyed.
    assert [question['stem'] for question in made['questions']] == [questions[0]['stem']]
    assert set(codes) == {'ground:law', 'ground:quote'} and warnings == [finish.FACTS_BLANKED]


# ---------------------------------------------------------------- quality exemptions


def test_a_papers_exemptions_are_the_parts_empty_repeating_or_not_prose_by_design(sinov):
    data = draft(sinov)
    exempt = finish.exempt(data)
    groups = {f'{name}{suffix}' for name in ('bob', 'bob_xulosa') for suffix in ('', '_2', '_3', '_4')}
    assert exempt == {'facts', 'ilova', 'narxlar', 'manbalar'} | groups
    assert 'kirish' not in exempt and 'maktub' not in exempt
    ariza = catalogue.get('pdf.xat.ariza')
    assert finish.exempt(draft(ariza, length=1)) == {'facts', 'statements', 'enclosures'}


# ---------------------------------------------------------------- the emergency fallback


def test_the_plain_fallback_keeps_its_contract(sinov):
    data = draft(sinov)
    content = answer(data, title='Kitoblar uchun to‘lov',
                     facts={'items': [{'label': 'author', 'text': 'Qodirova Malika'},
                                      {'label': 'topics', 'text': 'Iqtisodiyot'},
                                      {'label': 'topics', 'text': 'Kitoblar'},
                                      {'label': 'level', 'text': 'school'}]},
                     kirish={'body': 'Kirish matni.'},
                     bob={'heading': 'Birinchi bob', 'body': 'Bob matni.'},
                     narxlar={'items': [{'label': 'Kitob', 'text': '12 | 45 000', 'value': ''}]},
                     manbalar={'items': [{'label': '1', 'text': 'Saidov B. Iqtisodiyot asoslari. Toshkent, 2021.'}]},
                     questions=[{'stem': 'Savol?', 'options': [], 'answer': '', 'explanation': '', 'marks': 1,
                                 'topic': ''}])
    made, _, _ = finished(data, content)
    flat = finish.plain(data, made)
    assert flat['title'] == 'Kitoblar uchun to‘lov' and flat['questions'] == made['questions']
    facts = flat['sections'][0]
    assert (facts['id'], facts['heading'], facts['layout']) == ('facts', 'Ma’lumotlar', 'list')
    assert [(item['label'], item['text']) for item in facts['items']] == [
        ('author uz', 'Qodirova Malika'), ('signer uz', '____'), ('year uz', '2026'),
        ('made_on uz', '2026-yil 16-noyabr'), ('topics uz', 'Iqtisodiyot; Kitoblar'), ('amount uz', '____')]
    assert [section['id'] for section in flat['sections']] == ['facts', 'kirish', 'bob', 'narxlar', 'manbalar']
    assert [section['heading'] for section in flat['sections'][1:]] == ['Kirish', 'Birinchi bob', 'Narxlar',
                                                                       'Manbalar']
    table = flat['sections'][3]
    assert table['layout'] == 'list' and table['body'] == 'Nomi — Soni — Narxi — Jami'
    # derive multiplied the quantity by the price; one row has no total row.
    assert [item['text'] for item in table['items']] == ['Kitob — 12 — 45 000 — 540 000'], 'each value under its column'
    sources = flat['sections'][4]
    assert sources['layout'] == 'list' and len(sources['items']) == 1
    assert sources['items'][0]['label'] == '', 'the model\'s "1" is no label in a numbered list'
    assert all(section['layout'] in ('text', 'list') for section in flat['sections'])
    assert not violations(flat, 'uz')


def test_the_plain_fallback_names_an_untitled_paper_and_never_raises(sinov):
    data = draft(sinov, locale='ru')
    flat = finish.plain(data, {'title': '', 'sections': [], 'questions': []})
    assert flat['title'] == catalogue.get(SINOV).name('ru')
    assert flat['sections'][0]['heading'] == 'Сведения'
    odd = {'title': 'x', 'sections': [{'id': 'narxlar', 'items': 'not a list'}], 'questions': []}
    assert [section['id'] for section in finish.plain(data, odd)['sections']] == ['facts']
    broken = {'title': 'x', 'sections': ['not a section'], 'questions': []}
    assert finish.plain(data, broken) is broken


def test_the_plain_fallback_of_an_ariza_draws_every_blank_its_policy_asks():
    ariza = catalogue.get('pdf.xat.ariza')
    data = draft(ariza, length=1, locale='en')
    flat = finish.plain(data, {'title': '', 'sections': [
        {'id': 'facts', 'items': [{'label': 'applicant_name', 'text': 'Malika Qodirova'}]},
        {'id': 'request', 'heading': '', 'body': 'I ask for leave.'}], 'questions': []})
    labels = [item['label'] for item in flat['sections'][0]['items']]
    assert 'Addressee: organisation' in labels and not any(label.startswith('Phone') for label in labels)
    assert not any(label.startswith('What you ask') for label in labels), 'the request is drawn as its part'
    assert 'Date of writing' in labels and not any('(' in label for label in labels), 'no review-form hint'
    lines = {item['label']: item['text'] for item in flat['sections'][0]['items']}
    assert lines['Your full name'] == 'Malika Qodirova' and lines['Addressee: organisation'] == '____'
    assert flat['title'] == 'Official request' and flat['sections'][1]['body'] == 'I ask for leave.'


# ---------------------------------------------------------------- stage-2 re-audit: figures in words


COVER_RU = ('Напишите сопроводительное письмо на должность менеджера по продажам, я Малика Кодирова, работала '
            'в рознице.')
REPORT_UZ = 'Namuna Savdo MChJ uchun 2025-yil faoliyati bo‘yicha hisobot yozib bering, savdo bo‘limi.'


@pytest.mark.parametrize('entry_id, prompt, locale, part_id, text, left', [
    ('pdf.xat.ishga_kirish', COVER_RU, 'ru', 'fit', 'У меня более чем пятилетний опыт работы в продажах.',
     'У меня более чем ____ опыт работы в продажах.'),
    ('pdf.xat.ishga_kirish', COVER_RU, 'ru', 'fit', 'Оборот моего отдела превысил полмиллиона долларов.',
     'Оборот моего отдела превысил ____ долларов.'),
    ('pdf.xat.ishga_kirish', COVER_EN, 'en', 'fit', 'I doubled sales in my first year.',
     'I ____ sales in my first year.'),
    ('pdf.biz.biznes_reja', PLAN_UZ, 'uz', 'summary_lead', 'Loyihaning umumiy qiymati yarim milliard so‘m.',
     'Loyihaning umumiy qiymati ____ so‘m.'),
    ('pdf.biz.biznes_reja', PLAN_UZ, 'uz', 'summary_lead', 'Nonvoyxona yiliga ming tonna non ishlab chiqaradi.',
     'Nonvoyxona yiliga ____ tonna non ishlab chiqaradi.'),
    ('pdf.biz.biznes_reja', PLAN_UZ, 'uz', 'summary_lead', 'Kuniga mingta non sotiladi.', 'Kuniga ____ non sotiladi.'),
    ('pdf.biz.biznes_reja', PLAN_UZ, 'uz', 'summary_lead', 'Loyiha doirasida ellikdan ortiq ish o‘rni yaratiladi.',
     'Loyiha doirasida ____ ortiq ish o‘rni yaratiladi.'),
    ('pdf.biz.biznes_reja', PLAN_UZ, 'uz', 'summary_lead', 'Mijozlar soni yigirmaga yetadi.',
     'Mijozlar soni ____ yetadi.'),
    ('pdf.biz.biznes_reja', PLAN_UZ, 'uz', 'summary_lead', 'Loyiha yuz ish o‘rnini yaratadi.',
     'Loyiha ____ ish o‘rnini yaratadi.'),
    ('pdf.biz.hisobot', REPORT_UZ, 'uz', 'summary', 'Hisobot davrida o‘ttizdan ortiq yangi mijoz jalb qilindi.',
     'Hisobot davrida ____ ortiq yangi mijoz jalb qilindi.'),
], ids=['ru-fused', 'ru-half-million', 'en-doubled', 'uz-half-billion', 'uz-bare-ming', 'uz-mingta', 'uz-dan',
        'uz-ga', 'uz-bare-yuz', 'uz-report-dan'])
def test_a_figure_in_the_common_spoken_forms_the_customer_never_gave_is_blanked(entry_id, prompt, locale, part_id,
                                                                                text, left):
    entry = catalogue.get(entry_id)
    data = draft(entry, prompt=prompt, locale=locale, length=1 if entry_id.startswith('pdf.xat') else 6)
    made, warnings, codes = finished(data, answer(data, **{part_id: {'body': text}}))
    assert section_of(made, part_id)['body'] == left
    assert 'ground:number' in codes and warnings == [finish.FACTS_BLANKED]


@pytest.mark.parametrize('text', ['Более чем пятилетний опыт в розничных продажах', 'Двухлетний опыт работы кассиром'],
                         ids=['five-years', 'two-years'])
def test_a_led_fact_with_a_fused_russian_count_the_customer_never_gave_is_not_kept(text):
    letter = catalogue.get('pdf.xat.ishga_kirish')
    data = draft(letter, prompt=COVER_RU, locale='ru', length=1)
    made, _, codes = finished(data, answer(data, facts={'items': [{'label': 'experience_facts', 'text': text}]}))
    assert 'experience_facts' not in facts_of(made) and codes == ['fact:experience_facts']
    data = draft(letter, prompt=COVER_RU + ' Опыт в продажах 5 лет, кассиром 2 года.', locale='ru', length=1)
    made, _, codes = finished(data, answer(data, facts={'items': [{'label': 'experience_facts', 'text': text}]}))
    assert facts_of(made)['experience_facts'] == text and codes == []


def test_a_compound_split_on_figures_the_customer_gave_is_still_blanked():
    plan = catalogue.get('pdf.biz.biznes_reja')
    data = draft(plan, prompt=PLAN_UZ + ' Ustav kapitali 1 000 000 so‘m, aylanma mablag‘ 150 000 so‘m.', length=6)
    made, _, codes = finished(data, answer(data, summary_lead={
        'body': 'Jami mablag‘ bir million bir yuz ellik ming so‘m.'}))
    assert section_of(made, 'summary_lead')['body'] == 'Jami mablag‘ ____ so‘m.' and 'ground:number' in codes


def test_a_reports_date_moved_to_another_year_the_brief_names_is_not_kept():
    report = catalogue.get('pdf.biz.hisobot')
    data = draft(report, prompt=REPORT_UZ + ' Hisobot sanasi 15.01.2026.', length=6)
    made, _, codes = finished(data, answer(data, facts={'items': [{'label': 'report_date', 'text': '15.01.2025'}]}))
    assert 'report_date' not in facts_of(made) and codes == ['fact:report_date']
    made, _, codes = finished(data, answer(data, facts={'items': [{'label': 'report_date', 'text': '15.01.2026'}]}))
    assert facts_of(made)['report_date'] == '15.01.2026' and codes == []


# ---------------------------------------------------------------- stage-2 re-audit: laws


LESSON_UZ = '7-sinf matematika fanidan dars ishlanmasi yozib bering, mavzu: kasrlarni qo‘shish.'


def test_a_lessons_invented_ministry_order_goes_whole():
    lesson = catalogue.get('pdf.dars_ishlanmasi')
    data = draft(lesson, prompt=LESSON_UZ, length=2)
    order = 'Dars Xalq ta’limi vazirligining 2017-yil 6-apreldagi 187-sonli buyrug‘i asosida tashkil etiladi.'
    made, warnings, codes = finished(data, answer(data, stage_new={'body': f'Yangi mavzu tushuntiriladi. {order}'}))
    assert section_of(made, 'stage_new')['body'] == 'Yangi mavzu tushuntiriladi.'
    assert codes == ['ground:law'] and warnings == [finish.FACTS_BLANKED]


def test_a_job_descriptions_list_items_never_cite_a_code_the_customer_did_not_name():
    job = catalogue.get('pdf.biz.lavozim_yoriqnomasi')
    data = draft(job, prompt='Bosh buxgalter uchun lavozim yo‘riqnomasi yozing, Mehnat kodeksiga muvofiq.', length=2)
    items = ['Mehnat kodeksi talablariga amal qiladi.', 'Soliq kodeksi va Mehnat kodeksi talablariga amal qiladi.',
             'Fuqarolik kodeksining talablariga rioya qiladi.', 'Jinoyat kodeksiga muvofiq javobgar bo‘ladi.']
    made, warnings, codes = finished(data, answer(data, responsibility={
        'items': [{'label': '', 'text': item, 'value': ''} for item in items]}))
    kept = [item['text'] for item in section_of(made, 'responsibility')['items'] if item['text'].strip()]
    assert kept == ['Mehnat kodeksi talablariga amal qiladi.']
    assert 'ground:law' in codes and warnings == [finish.FACTS_BLANKED]


# ---------------------------------------------------------------- stage-2 re-audit: contacts


def test_a_cover_letters_invented_handle_and_site_are_not_kept_or_written():
    letter = catalogue.get('pdf.xat.ishga_kirish')
    prompt = ('Sotuv menejeri lavozimiga ishga kirish xati yozib bering. Men Aziz Karimov, savdoda ishlaganman, '
              'telefon +998 90 123 45 67.')
    data = draft(letter, prompt=prompt, length=1)
    made, warnings, codes = finished(data, answer(data, facts={'items': [
        {'label': 'phone', 'text': '+998 90 123 45 67'}, {'label': 'other_contact', 'text': '@aziz_karimov'}]},
        closing={'body': 'Men bilan @aziz_karimov yoki aziz-karimov.kz orqali bog‘lanishingiz mumkin.'}))
    assert 'other_contact' not in facts_of(made) and facts_of(made)['phone'] == '+998 90 123 45 67'
    assert section_of(made, 'closing')['body'] == 'Men bilan ____ yoki ____ orqali bog‘lanishingiz mumkin.'
    assert {'fact:other_contact', 'ground:number'} <= set(codes) and warnings == [finish.FACTS_BLANKED]


def test_an_offers_invented_website_is_not_kept_and_the_customers_is():
    offer = catalogue.get('pdf.biz.tijorat_taklifi')
    prompt = ('Oqtosh Mebel MChJ nomidan ofis mebeli bo‘yicha tijorat taklifi yozing, Instagram: @oqtosh_mebel, '
              'telefon +998 90 123 45 67.')
    data = draft(offer, prompt=prompt, length=1)
    made, _, codes = finished(data, answer(data, facts={'items': [
        {'label': 'seller_website', 'text': 'oqtoshmebel.shop'}]},
        cta={'body': 'Buyurtma uchun: @oqtosh_mebel yoki @oqtoshmebel.'}))
    assert 'seller_website' not in facts_of(made) and 'fact:seller_website' in codes
    assert section_of(made, 'cta')['body'] == 'Buyurtma uchun: @oqtosh_mebel yoki ____.'


# ---------------------------------------------------------------- stage-2 re-audit: class letters


def test_a_lessons_invented_class_letter_goes_and_the_customers_class_stays():
    lesson = catalogue.get('pdf.dars_ishlanmasi')
    data = draft(lesson, prompt=LESSON_UZ, length=2)
    made, warnings, codes = finished(data, answer(data, facts={'items': [
        {'label': 'grade', 'text': '7-«B» sinf'}, {'label': 'subject', 'text': 'Matematika'}]}))
    assert facts_of(made)['grade'] == '7-sinf' and codes == ['fact:grade'] and warnings == [finish.FACTS_BLANKED]
    data = draft(lesson, prompt='7 «Б» класс, математика, урок на тему сложение дробей.', locale='uz', length=2)
    made, _, codes = finished(data, answer(data, facts={'items': [{'label': 'grade', 'text': '7-«B» sinf'}]}))
    assert facts_of(made)['grade'] == '7-«B» sinf' and codes == []


# ---------------------------------------------------------------- stage-2 re-audit: a guarded title's author


@pytest.mark.parametrize('entry_id, locale, title, kept', [
    ('pdf.mustaqil_ish', 'ru', 'Инфляция и её последствия. Выполнила: Каримова Д.', 'Инфляция и её последствия'),
    ('pdf.konspekt', 'uz', 'Inflyatsiya. Ma’ruzachi: dotsent Rahimov B.', 'Inflyatsiya'),
    ('pdf.mustaqil_ish', 'uz', 'Inflyatsiya va uning oqibatlari. Talaba: Karimova D.',
     'Inflyatsiya va uning oqibatlari'),
    ('pdf.mustaqil_ish', 'uz', 'Inflyatsiya. Ilmiy rahbar: dotsent Rahimov B.', 'Inflyatsiya'),
    ('pdf.kurs_ishi', 'en', 'Inflation and its effects. Student: Karimova D.', 'Inflation and its effects'),
    ('pdf.kurs_ishi', 'en', 'Inflation and its effects. Supervised by Prof. Rahimov', 'Inflation and its effects'),
], ids=['ru-vypolnila', 'uz-maruzachi', 'uz-talaba', 'uz-ilmiy-rahbar', 'en-student', 'en-supervised-by'])
def test_a_guarded_titles_author_under_any_title_page_label_goes(entry_id, locale, title, kept):
    paper = catalogue.get(entry_id)
    data = draft(paper, prompt='Inflyatsiya va uning oqibatlari mavzusida ish yozib bering.', locale=locale,
                 length=paper.length['default'])
    made, warnings, codes = finished(data, answer(data, title=title))
    assert made['title'] == kept and 'ground:name' in codes and warnings == [finish.FACTS_BLANKED]


@pytest.mark.parametrize('locale, title', [('ru', 'Руководитель: роль и функции'), ('uz', 'Talaba: hayot va o‘qish')],
                         ids=['ru-topic', 'uz-topic'])
def test_a_topic_that_only_starts_with_a_label_word_stays(locale, title):
    test = catalogue.get('pdf.mustaqil_ish')
    data = draft(test, prompt='Mustaqil ish yozib bering: ' + title, locale=locale, length=test.length['default'])
    made, _, codes = finished(data, answer(data, title=title))
    assert made['title'] == title and 'ground:name' not in codes


# ---------------------------------------------------------------- stage-2 re-audit: names beside figures


def test_an_offers_requisites_and_phone_never_carry_an_invented_bank_or_person():
    offer = catalogue.get('pdf.biz.tijorat_taklifi')
    prompt = ('Oqtosh Mebel MChJ nomidan ofis mebeli bo‘yicha tijorat taklifi yozing. Rekvizitlar: h/r '
              '20208000900123456001, MFO 00440, STIR 301234567. Telefon +998 90 123 45 67.')
    data = draft(offer, prompt=prompt, length=1)
    made, warnings, codes = finished(data, answer(data, facts={'items': [
        {'label': 'seller_requisites',
         'text': 'h/r 20208000900123456001, «Kapitalbank» ATB Toshkent filiali, MFO 00440, STIR 301234567'},
        {'label': 'seller_phone', 'text': '+998 90 123 45 67 (Aziz Karimov)'}]}))
    assert 'seller_requisites' not in facts_of(made) and 'seller_phone' not in facts_of(made)
    assert set(codes) == {'fact:seller_requisites', 'fact:seller_phone'} and warnings == [finish.FACTS_BLANKED]
    made, _, codes = finished(data, answer(data, facts={'items': [
        {'label': 'seller_requisites', 'text': 'h/r 20208000900123456001, MFO 00440, STIR 301234567'},
        {'label': 'seller_phone', 'text': '+998 90 123 45 67'}]}))
    assert facts_of(made)['seller_phone'] == '+998 90 123 45 67' and codes == []


def test_a_plans_external_funding_never_names_an_invented_lender():
    plan = catalogue.get('pdf.biz.biznes_reja')
    data = draft(plan, prompt=PLAN_UZ + ' Kredit 200 mln so‘m olinadi.', length=6)
    made, _, codes = finished(data, answer(data, facts={'items': [
        {'label': 'external_funding', 'text': '200 mln so‘m (Hamkorbank krediti)'}]}))
    assert 'external_funding' not in facts_of(made) and codes == ['fact:external_funding']


# ---------------------------------------------------------------- stage-2 re-audit: names opening a sentence


BAKERY_UZ = ('Toshkentda nonvoyxona ochish bo‘yicha biznes-reja yozib bering. Mahalla aholisiga issiq non va somsa '
             'sotamiz. Direktor Qodirova Malika. O‘z mablag‘imiz 120 mln so‘m, bankdan 200 mln so‘m kredit '
             'olmoqchimiz.')


def test_a_plans_rejected_bank_and_project_never_open_its_title_cells_or_sentences():
    plan = catalogue.get('pdf.biz.biznes_reja')
    data = draft(plan, prompt=BAKERY_UZ, length=8)
    made, warnings, codes = finished(data, answer(
        data, title='«Baraka» nonvoyxonasi biznes-rejasi',
        summary_lead={'body': 'Baraka nonvoyxonasi issiq non sotadi. Hamkorbank 200 mln so‘m kredit beradi.'},
        finance_sources={'items': [{'label': 'Hamkorbank krediti', 'text': '200 mln so‘m', 'value': ''},
                                   {'label': 'Kapitalbank', 'text': '200 mln so‘m', 'value': ''}]},
        facts={'items': [{'label': 'director', 'text': 'Qodirova Malika'}, {'label': 'loan_bank', 'text': 'Hamkorbank'},
                         {'label': 'project_name', 'text': '«Baraka» nonvoyxonasi'}]}))
    assert {'fact:loan_bank', 'fact:project_name', 'ground:name'} <= set(codes) and warnings == [finish.FACTS_BLANKED]
    assert made['title'] == '«____» nonvoyxonasi biznes-rejasi'
    assert section_of(made, 'summary_lead')['body'] == ('____ nonvoyxonasi issiq non sotadi. ____ 200 mln so‘m kredit '
                                                        'beradi.')
    labels = [item['label'] for item in section_of(made, 'finance_sources')['items']]
    assert labels[:2] == ['____ krediti', '____']


def test_a_plans_bank_the_customer_named_opens_a_sentence_and_a_cell():
    plan = catalogue.get('pdf.biz.biznes_reja')
    data = draft(plan, prompt=BAKERY_UZ + ' Kreditni Hamkorbank beradi, loyiha nomi «Baraka» nonvoyxonasi.', length=8)
    made, _, codes = finished(data, answer(
        data, title='«Baraka» nonvoyxonasi biznes-rejasi',
        summary_lead={'body': 'Hamkorbank 200 mln so‘m kredit beradi.'},
        finance_sources={'items': [{'label': 'Hamkorbank krediti', 'text': '200 mln so‘m', 'value': ''}]},
        facts={'items': [{'label': 'loan_bank', 'text': 'Hamkorbank'},
                         {'label': 'project_name', 'text': '«Baraka» nonvoyxonasi'}]}))
    assert made['title'] == '«Baraka» nonvoyxonasi biznes-rejasi' and 'ground:name' not in codes
    assert section_of(made, 'summary_lead')['body'] == 'Hamkorbank 200 mln so‘m kredit beradi.'
    assert section_of(made, 'finance_sources')['items'][0]['label'] == 'Hamkorbank krediti'


def test_a_letters_rejected_employer_or_institution_never_opens_its_sentences():
    cover = catalogue.get('pdf.xat.ishga_kirish')
    data = draft(cover, prompt=('Sotuv menejeri lavozimiga ishga kirish uchun xat yozib bering. Men Qodirova Malika, '
                                'savdo sohasida ishlaganman.'), length=1)
    made, _, codes = finished(data, answer(
        data, opening={'body': 'Artel kompaniyasidagi sotuv menejeri lavozimiga ariza bermoqchiman.'},
        facts={'items': [{'label': 'applicant_name', 'text': 'Qodirova Malika'},
                         {'label': 'employer_name', 'text': 'Artel'}]}))
    assert section_of(made, 'opening')['body'] == '____ kompaniyasidagi sotuv menejeri lavozimiga ariza bermoqchiman.'
    assert {'fact:employer_name', 'ground:name'} <= set(codes)
    letter = catalogue.get('pdf.xat.motivatsion')
    data = draft(letter, prompt=('Menga ingliz tilida motivatsion xat yozib bering, chet eldagi universitetga '
                                 'magistraturaga kirmoqchiman. Ismim Qodirova Malika.'), locale='en', length=1)
    made, _, codes = finished(data, answer(
        data, opening={'body': 'Westminster University has long been the place where I hope to study.'},
        evidence={'body': 'UNICEF later hired me as a volunteer.'},
        facts={'items': [{'label': 'applicant_name', 'text': 'Malika Qodirova'},
                         {'label': 'target_institution', 'text': 'Westminster University'}]}))
    assert section_of(made, 'opening')['body'].startswith('____ ')
    assert section_of(made, 'evidence')['body'] == '____ later hired me as a volunteer.'


@pytest.mark.parametrize('locale, prompt, organisation, text, left', [
    ('uz', 'Kompaniyamizning 2025-yil uchun yillik hisobotini yozing: sotuv 1,2 mlrd so‘m.', '«Baraka» MChJ',
     '«Baraka» MChJ 2025-yil davomida sotuvni 1,2 mlrd so‘mga yetkazdi.',
     '«____» MChJ 2025-yil davomida sotuvni 1,2 mlrd so‘mga yetkazdi.'),
    ('en', 'Напишите отчёт о работе отдела продаж за 2025 год на английском: продажи 1,2 млрд сумов.', 'Acme LLC',
     'Acme LLC increased sales to 1.2 billion soums in 2025.',
     '____ LLC increased sales to 1.2 billion soums in 2025.'),
], ids=['uz', 'en-from-ru'])
def test_a_reports_rejected_organisation_never_opens_its_summary(locale, prompt, organisation, text, left):
    report = catalogue.get('pdf.biz.hisobot')
    data = draft(report, prompt=prompt, locale=locale, length=3)
    made, _, codes = finished(data, answer(data, summary={'body': text}, facts={'items': [
        {'label': 'organization', 'text': organisation}]}))
    assert section_of(made, 'summary')['body'] == left and {'fact:organization', 'ground:name'} <= set(codes)


def test_a_lessons_rejected_teacher_is_not_named_in_its_guarded_stages_or_title():
    lesson = catalogue.get('pdf.dars_ishlanmasi')
    data = draft(lesson, prompt=LESSON_UZ, length=2)
    made, warnings, codes = finished(data, answer(
        data, title='Kasrlarni qo‘shish. Karimova Dilnoza Bahodirovna',
        stage_opening={'body': 'O‘qituvchi Karimova Dilnoza Bahodirovna o‘quvchilar bilan salomlashadi. Amir Temur '
                               'haqida qisqa suhbat.'},
        facts={'items': [{'label': 'teacher', 'text': 'Karimova Dilnoza Bahodirovna'}]}))
    assert section_of(made, 'stage_opening')['body'] == ('O‘qituvchi ____ o‘quvchilar bilan salomlashadi. Amir Temur '
                                                         'haqida qisqa suhbat.')
    assert made['title'] == 'Kasrlarni qo‘shish. ____'
    assert {'fact:teacher', 'ground:name'} <= set(codes) and warnings == [finish.FACTS_BLANKED]


# ---------------------------------------------------------------- stage-2 re-audit: a change reads back


def test_a_translated_course_papers_invented_publisher_never_becomes_its_university_after_a_change():
    paper = catalogue.get('pdf.kurs_ishi')
    prompt = 'Напишите курсовую работу на узбекском о малом бизнесе в регионах.'
    data = draft(paper, prompt=prompt, length=10)
    first, _, codes = finished(data, answer(data, references={'items': [
        {'label': '1', 'text': 'Kichik biznes iqtisodiyoti. Westminster University Press.', 'value': ''}]},
        facts={'items': [{'label': 'university', 'text': 'Westminster University'}]}))
    assert 'university' not in facts_of(first) and 'fact:university' in codes
    data = draft(paper, prompt=prompt, length=10)
    data['revision'] = {'request': 'Сделайте введение подробнее.', 'original_prompt': prompt, 'before': first}
    made, _, codes = finished(data, answer(data, facts={'items': [
        {'label': 'university', 'text': 'Westminster University'}]}))
    assert 'university' not in facts_of(made) and 'fact:university' in codes


# ---------------------------------------------------------------- stage-2 re-audit: what the guard leaves of a test


@pytest.mark.parametrize('stem, options, correct', [
    ('«Farhod va Shirin» dostoni kimning qalamiga mansub?', ['Navoiy', 'Bobur', 'Qodiriy', 'Cho‘lpon'], 'Navoiy'),
    ('Qaysi asar Navoiyniki?', ['«Layli va Majnun»', '«O‘tkan kunlar»', '«Kecha va kunduz»', '«Boburnoma»'],
     '«Layli va Majnun»'),
], ids=['quoted-stem', 'quoted-options'])
def test_a_question_a_quotation_blank_left_unanswerable_goes(stem, options, correct):
    test = catalogue.get('pdf.test')
    data = draft(test, prompt='Adabiyot fanidan 9-sinf uchun test.', length=3)
    kept = {'stem': 'Alisher Navoiy qaysi asrda yashagan?', 'options': ['XIV', 'XV', 'XVI', 'XVII'], 'answer': 'XV',
            'explanation': '', 'marks': 1, 'topic': ''}
    broken = {'stem': stem, 'options': options, 'answer': correct, 'explanation': '', 'marks': 1, 'topic': ''}
    made, warnings, codes = finished(data, answer(data, questions=[kept, broken]))
    assert made['questions'] == [kept] and codes == ['ground:quote'] and warnings == [finish.FACTS_BLANKED]


def test_a_lessons_own_phrases_in_quotation_marks_stay():
    lesson = catalogue.get('pdf.dars_ishlanmasi')
    data = draft(lesson, prompt=LESSON_UZ, length=2)
    body = ('5 daqiqa. «Bugun nimani bildim?» savoliga javob beriladi. «Darslikdagi shu mavzuga oid mashqlar '
            'bajariladi».')
    made, _, codes = finished(data, answer(data, stage_close={'body': body}))
    assert section_of(made, 'stage_close')['body'] == body and 'ground:quote' not in codes
    voice = next(rule['text'] for rule in lesson.raw['rules'] if rule['text'].startswith('Voice of the plan'))
    assert 'never quoted in « »' in voice, 'the teacher\'s words are reported, not quoted'


# ---------------------------------------------------------------- stage-2 re-audit, round 2: an organisation's kind


@pytest.mark.parametrize('text, left', [
    ('Asaka banki 200 mln so‘m kredit beradi.', '____ banki 200 mln so‘m kredit beradi.'),
    ('Artel kompaniyasidagi sotuv menejeri lavozimiga ariza bermoqchiman.',
     '____ kompaniyasidagi sotuv menejeri lavozimiga ariza bermoqchiman.'),
    ('Korzinka supermarketlar tarmog‘ida ishlaganman.', '____ supermarketlar tarmog‘ida ishlaganman.'),
    ('Westminster universitetida o‘qishni xohlayman.', '____ universitetida o‘qishni xohlayman.'),
    ('«Baraka» kompaniyasi yangi filial ochdi.', '«____» kompaniyasi yangi filial ochdi.'),
], ids=['bank', 'company', 'chain', 'university', 'quoted'])
def test_an_uzbek_organisation_opening_a_sentence_before_its_kind_in_lower_case_is_held(text, left):
    known = facts.trusting(BAKERY_UZ)
    assert finish.ground_paper(text, known) == (left, ['ground:name'])
    assert finish.ground_paper(text, facts.trusting(BAKERY_UZ + ' ' + text)) == (text, []), 'the customer\'s own stays'


@pytest.mark.parametrize('text', [
    'Tijorat banki 200 mln so‘m kredit beradi.', 'Davlat universitetida o‘qiyman.',
    'Bizning kompaniyamiz issiq non sotadi.', 'Markaziy bank stavkasi o‘zgarmaydi.',
    'Mahalliy supermarketlar issiq non sotmaydi.', 'Qurilish kompaniyasi bilan shartnoma tuziladi.',
])
def test_a_kind_of_organisation_opening_a_sentence_is_no_ones_name(text):
    assert finish.ground_paper(text, facts.trusting(BAKERY_UZ)) == (text, [])


def test_a_reports_legal_form_with_an_ending_is_no_name():
    report = catalogue.get('pdf.biz.hisobot')
    data = draft(report, prompt='«Baraka Savdo» MChJ uchun 2025-yil faoliyati bo‘yicha hisobot yozing.', length=3)
    made, _, codes = finished(data, answer(
        data, title='«Baraka Savdo» MChJning 2025-yil faoliyati to‘g‘risida hisobot',
        summary={'body': 'Hisobot davrida «Baraka Savdo» MChJga yangi xodimlar qabul qilindi.'}))
    assert made['title'] == '«Baraka Savdo» MChJning 2025-yil faoliyati to‘g‘risida hisobot'
    assert section_of(made, 'summary')['body'] == 'Hisobot davrida «Baraka Savdo» MChJga yangi xodimlar qabul qilindi.'
    assert 'ground:name' not in codes


# ---------------------------------------------------------------- stage-2 re-audit, round 2: what a finish holds again


def test_a_blanked_run_of_common_words_never_blanks_them_opening_other_sentences_or_cells():
    plan = catalogue.get('pdf.biz.biznes_reja')
    data = draft(plan, prompt=BAKERY_UZ, length=8)
    made, _, codes = finished(data, answer(
        data, operations={'body': 'Korxona Davlat Soliq Qo‘mitasi orqali ro‘yxatdan o‘tadi. Davlat ro‘yxatidan o‘tish '
                                  'bir hafta oladi.'},
        finance_costs={'items': [{'label': 'Davlat boji', 'text': '', 'value': ''}]}))
    body = section_of(made, 'operations')['body']
    assert body.endswith('o‘tadi. Davlat ro‘yxatidan o‘tish bir hafta oladi.') and '____' in body
    assert section_of(made, 'finance_costs')['items'][0]['label'] == 'Davlat boji' and 'ground:name' in codes


def test_a_rejected_bank_named_by_a_common_word_holds_the_bank_never_the_word():
    plan = catalogue.get('pdf.biz.biznes_reja')
    data = draft(plan, prompt=BAKERY_UZ, length=8)
    made, _, codes = finished(data, answer(
        data, summary_lead={'body': 'Xalq banki 200 mln so‘m kredit beradi.'},
        marketing={'items': [{'label': '', 'text': 'Xalqaro ko‘rgazmalarda ishtirok etish', 'value': ''},
                             {'label': '', 'text': 'Xalq sayllarida stend', 'value': ''}]},
        conclusion={'body': 'Xalqaro tajriba shuni ko‘rsatadiki, issiq non talab yuqori.'},
        facts={'items': [{'label': 'loan_bank', 'text': 'Xalq banki'}]}))
    assert section_of(made, 'summary_lead')['body'] == '____ banki 200 mln so‘m kredit beradi.'
    assert [item['text'] for item in section_of(made, 'marketing')['items']] == [
        'Xalqaro ko‘rgazmalarda ishtirok etish', 'Xalq sayllarida stend']
    assert section_of(made, 'conclusion')['body'] == 'Xalqaro tajriba shuni ko‘rsatadiki, issiq non talab yuqori.'
    assert {'fact:loan_bank', 'ground:name'} <= set(codes)


def test_a_rejected_authors_role_words_stay_and_the_person_is_held_in_any_case():
    report = catalogue.get('pdf.biz.hisobot')
    data = draft(report, prompt='Nonvoyxonamizning 2025-yil faoliyati bo‘yicha hisobot yozib bering. Sotuv 1,2 mlrd '
                                'so‘m bo‘ldi.', length=4)
    made, _, codes = finished(data, answer(
        data, summary={'body': 'Bosh ofis ta’mirlandi. Dilnozaga yangi lavozim berildi. Sotuv 1,2 mlrd so‘mga yetdi.'},
        problems={'items': [{'label': '', 'text': 'Bosh hisobchi lavozimi bo‘sh qoldi.', 'value': ''},
                            {'label': '', 'text': 'Moliyaviy resurslar yetishmadi.', 'value': ''}]},
        work_done={'body': 'Kompaniya Moliya Vazirligi bilan hamkorlik qildi. Moliya bo‘limi kengaytirildi.'},
        facts={'items': [{'label': 'author', 'text': 'Bosh hisobchi Karimova Dilnoza'}]}))
    assert section_of(made, 'summary')['body'] == ('Bosh ofis ta’mirlandi. ____ yangi lavozim berildi. Sotuv 1,2 mlrd '
                                                   'so‘mga yetdi.')
    assert [item['text'] for item in section_of(made, 'problems')['items']] == [
        'Bosh hisobchi lavozimi bo‘sh qoldi.', 'Moliyaviy resurslar yetishmadi.']
    assert section_of(made, 'work_done')['body'].endswith('bilan hamkorlik qildi. Moliya bo‘limi kengaytirildi.')
    assert {'fact:author', 'ground:name'} <= set(codes)


# ---------------------------------------------------------------- stage-2 re-audit, round 2: a law's name in full


@pytest.mark.parametrize('prompt, locale, items, kept', [
    ('Bosh buxgalter uchun lavozim yo‘riqnomasi yozing, Mehnat kodeksiga muvofiq.', 'uz',
     ['Ma’muriy javobgarlik to‘g‘risidagi kodeksga muvofiq javobgar bo‘ladi.',
      'Fuqarolik protsessual kodeksi talablariga rioya qiladi.', 'Jinoyat-protsessual kodeksiga muvofiq javob beradi.',
      'O‘zbekiston Respublikasi Mehnat kodeksiga muvofiq ish yuritadi.'],
     ['O‘zbekiston Respublikasi Mehnat kodeksiga muvofiq ish yuritadi.']),
    ('Составьте должностную инструкцию главного бухгалтера на узбекском, в соответствии с Трудовым кодексом.', 'uz',
     ['Ma’muriy javobgarlik to‘g‘risidagi kodeksga muvofiq javobgar bo‘ladi.',
      'U Ma’muriy javobgarlik to‘g‘risidagi kodeksga ko‘ra javob beradi.', 'Jinoyat kodeksiga ko‘ra javobgar bo‘ladi.',
      'Mehnat kodeksi talablariga amal qiladi.'],
     ['Mehnat kodeksi talablariga amal qiladi.']),
    ('Составьте должностную инструкцию главного бухгалтера, в соответствии с Трудовым кодексом.', 'ru',
     ['Несёт ответственность по Кодексу об административных правонарушениях.',
      'Руководствуется Кодексом Республики Узбекистан об административной ответственности.',
      'Соблюдает требования Трудового кодекса Республики Узбекистан.'],
     ['Соблюдает требования Трудового кодекса Республики Узбекистан.']),
    ('Write a job description for a chief accountant in line with the Labour Code.', 'en',
     ['Complies with the Code of Administrative Offences.', 'Follows the Labour Code and the Tax Code.',
      'Complies with the Labour Code of the Republic of Uzbekistan.'],
     ['Complies with the Labour Code of the Republic of Uzbekistan.']),
], ids=['uz', 'uz-from-ru', 'ru', 'en'])
def test_a_code_named_by_words_apart_from_its_stem_or_after_it_is_the_customers_or_goes(prompt, locale, items, kept):
    job = catalogue.get('pdf.biz.lavozim_yoriqnomasi')
    data = draft(job, prompt=prompt, locale=locale, length=2)
    made, _, codes = finished(data, answer(data, responsibility={
        'items': [{'label': '', 'text': item, 'value': ''} for item in items]}))
    assert [item['text'] for item in section_of(made, 'responsibility')['items'] if item['text'].strip()] == kept
    assert 'ground:law' in codes


# ---------------------------------------------------------------- stage-2 re-audit, round 2: no class letter


@pytest.mark.parametrize('prompt, locale, position', [
    ('Программист 1С, нужно сопроводительное письмо на узбекском. Меня зовут Каримов Азиз.', 'uz', '1C dasturchisi'),
    ('Программист 1С, нужно сопроводительное письмо на английском. Меня зовут Каримов Азиз.', 'en', '1C Programmer'),
    ('1С dasturchisi lavozimiga ishga kirish xati yozing. Men Karimov Aziz.', 'uz', '1C dasturchisi'),
], ids=['uz-from-ru', 'en-from-ru', 'uz-cyrillic-letter'])
def test_a_cover_letters_1c_position_is_kept_whole(prompt, locale, position):
    cover = catalogue.get('pdf.xat.ishga_kirish')
    data = draft(cover, prompt=prompt, locale=locale, length=1)
    made, _, codes = finished(data, answer(data, facts={'items': [{'label': 'position', 'text': position}]}))
    assert facts_of(made)['position'] == position and 'fact:position' not in codes


# ---------------------------------------------------------------- stage-2 re-audit, round 2: a figure's own labels


def test_a_translated_offers_bank_details_and_phone_are_kept_with_their_labels():
    offer = catalogue.get('pdf.biz.tijorat_taklifi')
    prompt = ('Коммерческое предложение на английском от ООО «Октош Мебель» на офисную мебель. Реквизиты: р/с '
              '20208000900123456001, АКБ «Капиталбанк», МФО 00440, ИНН 301234567. Телефон +998 90 123 45 67.')
    data = draft(offer, prompt=prompt, locale='en', length=1)
    requisites = 'Account 20208000900123456001, Kapitalbank JSCB, MFO 00440, TIN 301234567'
    made, _, codes = finished(data, answer(data, facts={'items': [
        {'label': 'seller_requisites', 'text': requisites},
        {'label': 'seller_phone', 'text': '+998 90 123 45 67 (mobile, Telegram)'}]}))
    assert facts_of(made)['seller_requisites'] == requisites
    assert facts_of(made)['seller_phone'] == '+998 90 123 45 67 (mobile, Telegram)' and codes == []
