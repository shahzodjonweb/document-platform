"""The academic templates (R3a): title_page, toc and reference_list, and the mustaqil ish and kurs ishi they draw.

Papers are drawn through the engine (render_paper) and read back with
pdfplumber, so each block is held to what the page shows: the words, the
page they land on, the rules to write on. People and organisations are
invented.
"""
import copy
import datetime
import random
import re

import pdfplumber
import pytest

from apps.studio import paper
from apps.studio.categories import catalogue, skeleton
from apps.studio.paper import check, fit, registry
from apps.studio.paper.blocks import academic
from apps.studio.paper.ctx import Ctx, Place
from apps.studio.paper.sample import CASES
from tests import paper_family

DAY = datetime.date(2026, 11, 17)
TEMPLATES = ('academic_mustaqil_ish', 'academic_kurs_ishi')
ACADEMIC = ('title_page', 'toc', 'reference_list')


# ---------------------------------------------------------------- helpers


def mustaqil():
    return catalogue.get('pdf.mustaqil_ish')


def kurs():
    return catalogue.get('pdf.kurs_ishi')


def facts(**values):
    return {'id': 'facts', 'heading': '', 'body': '', 'layout': 'list',
            'items': [{'label': key, 'text': value} for key, value in values.items()]}


def section(section_id, body='', heading='', items=()):
    return {'id': section_id, 'heading': heading, 'body': body, 'layout': 'list' if items else 'text',
            'items': [{'label': '', 'text': text} for text in items]}


FULL = dict(topic='Maktabda raqamli o‘quv resurslaridan foydalanish', work_kind='mustaqil_ish',
            institution='Gulzorobod davlat pedagogika instituti', faculty_department='Boshlang‘ich ta’lim fakulteti',
            subject='Pedagogika', student_name='Qodirova Malika Anvar qizi', student_group='2-kurs, 204-guruh',
            teacher='dotsent Hamidov Sardor', city='Gulzorobod')
PROSE = ('Raqamli texnologiyalar maktab hayotiga tobora chuqurroq kirib bormoqda. O‘qituvchi resursni dars maqsadiga '
         'qarab tanlaydi va uni darsning aniq bosqichiga joylashtiradi.')


def content(*sections, title='Maktabda raqamli o‘quv resurslaridan foydalanish', **given):
    return {'title': title, 'sections': [facts(**given), *sections], 'questions': []}


def template_with(template_id, flow, **changes):
    """A copy of a real template drawing `flow` (placements, or indexes of its own flow)."""
    made = copy.deepcopy(catalogue.template(template_id))
    made['flow'] = [copy.deepcopy(made['flow'][item]) if isinstance(item, int) else item for item in flow]
    made.update(changes)
    return made


def draw(tmp_path, page_content, *, entry=None, template='academic_mustaqil_ish', pages=8, locale='uz',
         name='paper.pdf', cues=()):
    return paper.render_paper(page_content, tmp_path / name, locale, entry=entry or mustaqil(), template=template,
                              pages=pages, day=DAY, cues=frozenset(cues))


def pages_text(result):
    with pdfplumber.open(result['path']) as document:
        return [(page_.extract_text() or '').replace('\xa0', ' ') for page_ in document.pages]


def flat(text):
    return ' '.join(text.split())


def rules(result, page_number=0):
    """The horizontal rules a page draws (to write on), as (x0, x1, top)."""
    with pdfplumber.open(result['path']) as document:
        page_ = document.pages[page_number]
        found = [(line['x0'], line['x1'], line['top']) for line in page_.lines if abs(line['top'] - line['bottom']) < 1]
        found += [(rect['x0'], rect['x1'], rect['top']) for rect in page_.rects if rect['height'] < 1]
    return found


def problems(result, page_content, *, entry=None, template='academic_mustaqil_ish', pages=8, locale='uz'):
    raw = catalogue.template(template) if isinstance(template, str) else template
    expect = check.expect_for(result, page_content, entry=entry or mustaqil(), template=raw, locale=locale,
                              pages=pages, day=DAY)
    return check.problems(result['path'], expect)


def ctx_for(page_content, *, entry=None, template='academic_mustaqil_ish', locale='uz'):
    raw = catalogue.template(template) if isinstance(template, str) else template
    return Ctx(content=page_content, entry=entry or mustaqil(), template=raw, locale=locale, step=0, pages=8,
               width=400, frame_height=700, day=DAY)


# ---------------------------------------------------------------- registry and readiness


def test_the_academic_blocks_are_registered_with_their_plain_fallbacks():
    for name in ACADEMIC:
        assert name in registry.BLOCKS and registry.BLOCKS[name].fallback is not None


@pytest.mark.parametrize('category', ['pdf.mustaqil_ish', 'pdf.kurs_ishi'])
def test_the_academic_papers_are_drawn_by_their_own_templates(category):
    data = {'options': {'category': category}, 'output_locale': 'uz'}
    assert paper.ready(data)
    assert paper.template_for(data) == {'pdf.mustaqil_ish': 'academic_mustaqil_ish',
                                        'pdf.kurs_ishi': 'academic_kurs_ishi'}[category]


def test_every_template_has_its_samples():
    paper_family.assert_has_samples(list(TEMPLATES))


@paper_family.each(list(TEMPLATES))
def test_every_template_reads_well(template_id, locale, case, tmp_path):
    drawn = paper_family.assert_reads_well(template_id, locale, case, tmp_path)
    metadata = drawn.artifact['metadata']
    if case == 'long':
        # More prose than the count holds: the paper says so, never cuts a fixed part, never passes the plan cap.
        assert fit.LONGER in metadata['warnings'] or fit.SHORTENED in metadata['warnings']
    else:
        assert drawn.artifact['page_count'] <= drawn.pages and fit.LONGER not in metadata['warnings']


def test_the_cases_are_the_three_the_architecture_names():
    assert CASES == ('full', 'blank', 'long')


# (entry, pages, cues, chapters written, parts left empty): C2a's sizing cases, drawn here by the real blocks.
SIZED = [('pdf.mustaqil_ish', 8, 2, ('section_c',)), ('pdf.mustaqil_ish', 8, 3, ('section_c',)),
         ('pdf.mustaqil_ish', 10, 2, ()), ('pdf.mustaqil_ish', 11, 3, ()), ('pdf.kurs_ishi', 12, 2, ()),
         ('pdf.kurs_ishi', 12, 3, ()), ('pdf.kurs_ishi', 25, 2, ()), ('pdf.kurs_ishi', 25, 3, ())]


@pytest.mark.parametrize('entry_id, length, written, empty', SIZED,
                         ids=[f'{case[0]}-{case[1]}-{case[2]}' for case in SIZED])
def test_the_shortest_and_default_lengths_end_on_their_page_with_the_real_blocks(entry_id, length, written, empty,
                                                                                tmp_path):
    # C2a sized the parts with stand-in blocks; the title page, the contents and the reference form take a page
    # each here too, so a paper written at 0.9 of its targets still ends within its count, barely cut.
    from tests.test_category_study_entries import _content
    entry = catalogue.get(entry_id)
    held = skeleton.effective(entry, set())
    made = paper.render_paper(_content(entry, length, held, written, empty, random.Random(7)), tmp_path / 'p.pdf',
                              'uz', entry=entry, template=paper.pick(entry, 'uz', held), pages=length, cues=held)
    metadata = made['metadata']
    assert made['page_count'] <= length and fit.LONGER not in metadata['warnings'], (made['page_count'], metadata)
    assert metadata['trim_ratio'] is None or metadata['trim_ratio'] >= 0.7
    assert not [code for code in metadata['warnings'] if code.startswith(('block_fallback', 'template_fallback'))]


# ---------------------------------------------------------------- title_page


def test_a_title_page_is_one_whole_page_with_every_fact_by_its_role(tmp_path):
    flow = [0, 1]
    page_content = content(**FULL)
    result = draw(tmp_path, page_content, template=template_with('academic_mustaqil_ish', flow))
    first, second = pages_text(result)[:2]
    for value in FULL.values():
        if value != 'mustaqil_ish':
            assert flat(value).casefold() in flat(first).casefold(), value
    assert 'M U S T A Q I L' in first or 'MUSTAQIL' in first.replace(' ', '')
    assert '«Pedagogika» fanidan' in first and 'Mavzu:' in first and 'Gulzorobod – 2026' in first
    assert 'Bajardi:' in first and 'Qabul qildi:' in first
    # The title page is a sheet of its own: the plan starts page 2, and page 1 carries no number.
    assert 'REJA' in second and 'REJA' not in first
    assert not re.search(r'^\s*1\s*$', first, re.M)


def test_the_kind_and_the_checkers_word_come_from_choice_facts_never_printed_as_codes(tmp_path):
    given = dict(FULL, work_kind='referat', checker_word='checked')
    result = draw(tmp_path, content(**given), template=template_with('academic_mustaqil_ish', [0]))
    text = pages_text(result)[0]
    assert 'REFERAT' in text.replace(' ', '') and 'Tekshirdi:' in text and 'Qabul qildi' not in text
    assert 'referat' not in text and 'checked' not in text
    # No kind given: the template's default word.
    plain = dict(FULL)
    plain.pop('work_kind')
    result = draw(tmp_path, content(**plain), template=template_with('academic_mustaqil_ish', [0]), name='p2.pdf')
    assert 'REFERAT' in pages_text(result)[0].replace(' ', '')


def test_a_blank_title_page_draws_rules_with_captions_and_the_clock_year(tmp_path):
    result = draw(tmp_path, content(), template=template_with('academic_mustaqil_ish', [0]))
    text = pages_text(result)[0]
    for caption in ('(ta’lim muassasasining nomi)', '(fan nomi)', '(F.I.Sh.)', '(kurs, guruh)', '(shahar)'):
        assert caption in text, caption
    assert 'fanidan' in text and '«' not in text.split('fanidan')[0][-20:]
    assert '– 2026' in text and '____' not in text
    # Two rules for the institution, one for the subject, two credit groups (2 + 2 rules), one for the city.
    assert len(rules(result)) >= 8
    # The topic is the paper's own title when the fact is missing: it was asked for before the paper was written.
    assert 'Maktabda raqamli' in text
    assert problems(result, content(), template=template_with('academic_mustaqil_ish', [0])) == []


def test_a_fact_left_out_draws_no_row_and_a_given_ministry_prints(tmp_path):
    template = template_with('academic_mustaqil_ish', [0])
    result = draw(tmp_path, content(**FULL), template=template)
    assert 'VAZIRLIGI' not in pages_text(result)[0]
    given = dict(FULL, ministry='Namuna viloyati ta’lim boshqarmasi')
    result = draw(tmp_path, content(**given), template=template, name='ministry.pdf')
    assert 'NAMUNA VILOYATI TA’LIM BOSHQARMASI' in pages_text(result)[0]


def test_a_long_topic_and_long_names_stay_on_the_sheet(tmp_path):
    given = dict(FULL, topic=' '.join(['Zamonaviy ta’lim jarayonida axborot-kommunikatsiya texnologiyalaridan '
                                       'foydalanishning pedagogik asoslari'] * 3),
                 institution='Gulzorobod viloyati xalq ta’limi boshqarmasiga qarashli davlat pedagogika instituti '
                             'qoshidagi pedagog kadrlarni qayta tayyorlash markazi',
                 teacher='pedagogika fanlari bo‘yicha falsafa doktori, dotsent Hamidov Sardor Karimovich')
    template = template_with('academic_mustaqil_ish', [0])
    page_content = content(**given)
    result = draw(tmp_path, page_content, template=template)
    assert result['page_count'] == 1
    assert problems(result, page_content, template=template) == []


def test_a_kurs_ishi_title_page_has_its_lines_signatures_and_dates(tmp_path):
    given = dict(topic='Kichik korxonalarda xodimlarni rag‘batlantirish', subject='Menejment',
                 university='Gulzorobod iqtisodiyot universiteti', kafedra='Korxona iqtisodiyoti',
                 direction='Menejment', course_group='3-kurs 312-guruh', student_name='Ergasheva Dilnoza',
                 supervisor='katta o‘qituvchi Yo‘ldoshev Bekzod', city='Gulzorobod')
    template = template_with('academic_kurs_ishi', [0])
    page_content = content(**given)
    result = draw(tmp_path, page_content, entry=kurs(), template=template, pages=12)
    text = pages_text(result)[0]
    assert '«Korxona iqtisodiyoti» kafedrasi' in text and 'Menejment ta’lim yo‘nalishi' in text
    assert 'KICHIK KORXONALARDA XODIMLARNI RAG‘BATLANTIRISH' in flat(text) and 'KURSISHI' in text.replace(' ', '')
    assert '3-kurs 312-guruh talabasi' in text and 'Ilmiy rahbar:' in text
    assert text.count('(imzo)') == 2 and text.count('2026-yil') == 2
    assert problems(result, page_content, entry=kurs(), template=template, pages=12) == []


@pytest.mark.parametrize('locale, words', [('ru', ('Выполнил(а):', 'Принял(а):', 'по дисциплине', 'Тема:')),
                                           ('en', ('Prepared by:', 'Accepted by:', 'Subject:', 'Topic:'))])
def test_a_title_page_in_russian_and_english_has_its_words(tmp_path, locale, words):
    given = dict(FULL, institution='Example State Institute', faculty_department='Faculty', subject='Pedagogy',
                 student_name='Malika Qodirova', student_group='Year 2', teacher='Sardor Hamidov', city='Example')
    result = draw(tmp_path, content(**given), template=template_with('academic_mustaqil_ish', [0]), locale=locale)
    text = pages_text(result)[0]
    assert all(word in text for word in words)


def test_a_cover_form_of_a_business_template_draws_kind_title_rows_and_foot(tmp_path):
    placement = {'block': 'title_page', 'part': 'title_page', 'fields': ['subject', 'student_name', 'teacher', 'city',
                                                                         'year', 'work_kind'],
                 'params': {'label': 'kind_referat', 'title': 'content_title',
                            'labels': {'student_name': 'done_by', 'teacher': 'accepted_by'}, 'foot': ['city', 'year']}}
    template = template_with('academic_mustaqil_ish', [placement])
    result = draw(tmp_path, content(**FULL), template=template)
    text = pages_text(result)[0]
    assert 'REFERAT' in text.replace(' ', '') and 'Maktabda raqamli o‘quv resurslaridan foydalanish' in text
    assert 'Pedagogika' in text and 'Bajardi:' in text and 'Gulzorobod – 2026' in text
    # A choice is a code, never a line.
    assert 'mustaqil_ish' not in text


def test_a_cover_with_no_year_and_a_credit_without_a_value_or_blank(tmp_path):
    placement = {'block': 'title_page', 'part': 'title_page', 'fields': ['institution', 'topic', 'ministry'],
                 'params': {'rows': [{'role': 'institution', 'fact': 'institution'},
                                     {'role': 'topic', 'fact': 'topic', 'style': 'bold'},
                                     {'role': 'credit', 'fact': 'ministry', 'label': 'done_by'}], 'year': 'none'}}
    result = draw(tmp_path, content(**FULL), template=template_with('academic_mustaqil_ish', [placement]))
    text = pages_text(result)[0]
    assert '2026' not in text and 'Bajardi' not in text and 'GULZOROBOD' in text


def test_a_title_page_too_tall_for_one_sheet_flows_and_says_so():
    rows = [{'role': 'unit', 'fact': 'topic'}] * 60
    place = Place('title_page', None, mustaqil().part('title_page'), ('topic',), {'rows': rows, 'year': 'clock'})
    ctx = ctx_for(content(**FULL))
    made = academic.title_page(ctx, place)
    assert 'title_page_over' in ctx.warnings and len(made) > 60


# ---------------------------------------------------------------- toc


def chapters():
    return [section('introduction', PROSE), section('chapter', 'Bob haqida.', 'Raqamli resurslar asoslari'),
            section('section_a', PROSE + '\n' + PROSE, 'Tushuncha va mohiyati'),
            section('section_b', PROSE, 'Resurslarning turlari'),
            section('chapter_2', 'Ikkinchi bob haqida.', 'Darsda qo‘llash yo‘llari'),
            section('section_a_2', PROSE, 'O‘qituvchi tayyorgarligi'), section('section_b_2', PROSE, 'Baholash'),
            section('conclusion', PROSE)]


def test_the_contents_lists_each_heading_with_the_page_it_lands_on(tmp_path):
    result = draw(tmp_path, content(*chapters(), **FULL))
    pages = pages_text(result)
    plan = pages[1]
    assert plan.splitlines()[0].strip() == 'REJA'
    found = {}
    for line in plan.splitlines()[1:]:
        match = re.match(r'^(.*?)\s*\.{3,}.*?(\d+)$', line.replace(' .', '.').strip())
        if match:
            found[flat(match.group(1).strip(' .'))] = int(match.group(2))
    assert found, plan
    for heading, number in found.items():
        words = heading.split(' ', 1)[-1] if re.match(r'^\d', heading) else heading
        on = next(index for index, text in enumerate(pages, 1) if index > 2 and words[:18] in flat(text))
        assert number == on, (heading, number, on)
    assert any('FOYDALANILGAN ADABIYOTLAR' in heading for heading in found)
    assert 'page_numbers_unsettled' not in result['metadata']['warnings']


def test_the_contents_has_leaders_and_levels_and_a_strip_has_no_numbers(tmp_path):
    flow = [1, 2, 4, 6]
    template = template_with('academic_mustaqil_ish', flow)
    result = draw(tmp_path, content(*chapters(), **FULL), template=template)
    first = pages_text(result)[0]
    assert '1.1' in first and 'Tushuncha va mohiyati' in first and '.....' in first.replace(' ', '')
    one = template_with('academic_mustaqil_ish', [dict(template['flow'][0], params={'label': 'plan', 'levels': 1}),
                                                  *template['flow'][1:]])
    result = draw(tmp_path, content(*chapters(), **FULL), template=one, name='one.pdf')
    first = pages_text(result)[0]
    assert 'Raqamli resurslar asoslari' in first and '1.1' not in first and 'Tushuncha' not in first
    strip = template_with('academic_mustaqil_ish', [
        {'block': 'toc', 'part': 'plan', 'params': {'label': 'plan', 'levels': 2, 'page_numbers': False,
                                                    'style': 'strip'}}, *template['flow'][1:]])
    result = draw(tmp_path, content(*chapters(), **FULL), template=strip, name='strip.pdf')
    head = pages_text(result)[0].split('\n')[:6]
    assert head[0].strip() == 'REJA' and not any(re.search(r'\.{3}|\d$', line.replace(' .', '.')) for line in head)


def test_a_contents_row_draws_its_page_number_and_leaders_at_its_last_line(tmp_path):
    long_heading = 'Raqamli o‘quv resurslarining nazariy asoslari va ularni maktab amaliyotiga joriy etishning ' \
                   'pedagogik va tashkiliy shartlari'
    sections = chapters()
    sections[1] = section('chapter', 'Bob haqida.', long_heading)
    template = template_with('academic_mustaqil_ish', [1, 2, 3, 4, 5])
    page_content = content(*sections, **FULL)
    result = draw(tmp_path, page_content, template=template)
    assert problems(result, page_content, template=template) == []
    with pdfplumber.open(result['path']) as document:
        words = document.pages[0].extract_words()
    tail = [word for word in words if word['text'].startswith('shartlari')]
    line = [word for word in words if tail and abs(word['top'] - tail[0]['top']) < 3]
    # The wrapped row's last line carries the leaders and the page the chapter starts on (the plan, the Kirish, it).
    assert tail and line[-1]['text'] == '3' and line[-1]['x0'] > tail[0]['x1']
    assert any(set(word['text']) == {'.'} for word in line)


def test_toc_plain_fallback_lists_the_headings(tmp_path):
    template = template_with('academic_mustaqil_ish', [1, 2, 4, 6])
    page_content = content(*chapters(), **FULL)
    ctx = ctx_for(page_content, template=template)
    place = Place('toc', None, mustaqil().part('plan'), (), {'label': 'plan'})
    made = registry.draw(ctx, place, plain_only=True)
    assert 'block_fallback:toc' in ctx.warnings and made


# ---------------------------------------------------------------- reference_list


SOURCES = ['1. Rahimova D. B. Raqamli pedagogika asoslari. – Gulzorobod: Ilm, 2022. – 184 b.',
           'Sobirov A. K. Maktabda axborot texnologiyalari. – Gulzorobod, 2021.',
           'Gulzorobod viloyati ta’lim boshqarmasining «Raqamli maktab» nizomi. – Gulzorobod, 2024.',
           'Tursunov B. Interaktiv dars usullari // Pedagogik izlanishlar. – 2023. – № 4.',
           'Resurslar katalogi [Elektron resurs]. – URL: https://example.com/katalog/'
           'boshlangich-sinflar-uchun-interaktiv-mashqlar-toplami-va-qollanmalar-royxati',
           'Karimova L. Elektron resurslar. – Gulzorobod, 2020. – 96 b.']


def references(tmp_path, items, *, name='refs.pdf', params=None, body=''):
    params = params or {'label': 'references', 'blank_entries': 10, 'blank_lines': 2, 'groups': True}
    template = template_with('academic_mustaqil_ish', [{'block': 'reference_list', 'part': 'references',
                                                        'params': params}])
    sources = section('references', body, items=items)
    sources['layout'] = 'list'
    page_content = content(sources, **FULL)
    return draw(tmp_path, page_content, template=template, name=name), page_content, template


def test_sources_are_numbered_in_groups_laws_first_with_a_long_url_inside_the_frame(tmp_path):
    result, page_content, template = references(tmp_path, SOURCES)
    text = pages_text(result)[0]
    assert text.index('Normativ-huquqiy hujjatlar') < text.index('Ilmiy va o‘quv adabiyotlar') < \
        text.index('Internet manbalari')
    assert re.search(r'^1\. Gulzorobod viloyati', text, re.M) and re.search(r'^2\. Rahimova', text, re.M)
    # The typed number is dropped: the list numbers itself.
    assert '1. 1.' not in text and 'Rahimova' in text
    assert problems(result, page_content, template=template) == []


def test_fewer_than_six_sources_or_one_group_keep_their_order_without_labels(tmp_path):
    result, _, _ = references(tmp_path, SOURCES[:5])
    text = pages_text(result)[0]
    assert 'Normativ' not in text and re.search(r'^1\. Rahimova', text, re.M)
    books = [f'Muallif{number} A. Kitob {number}. – Gulzorobod, 2020.' for number in range(1, 8)]
    result, _, _ = references(tmp_path, books, name='books.pdf')
    assert 'Ilmiy va o‘quv' not in pages_text(result)[0]


def test_sources_given_as_body_lines_and_repeated_items_print_once(tmp_path):
    result, _, _ = references(tmp_path, [SOURCES[1], SOURCES[1]], body=SOURCES[3] + '\n' + SOURCES[1])
    text = pages_text(result)[0]
    assert text.count('Sobirov A. K.') == 1 and 'Tursunov' in text


def test_no_source_draws_the_numbered_form_with_its_caption(tmp_path):
    result, page_content, template = references(tmp_path, [])
    text = pages_text(result)[0]
    numbers = re.findall(r'^(\d+)\.', text, re.M)
    assert numbers == [str(number) for number in range(1, 11)]
    assert '(muallif, nomi, shahar: nashriyot, yil, sahifalar soni)' in text
    assert len(rules(result)) == 20
    assert problems(result, page_content, template=template) == []
    result, _, _ = references(tmp_path, [], name='one.pdf', params={'label': 'references', 'blank_entries': 20,
                                                                     'blank_lines': 1})
    assert len(rules(result)) == 20 and result['page_count'] == 1


def test_the_reference_heading_joins_the_contents_unless_told_not_to():
    ctx = ctx_for(content(**FULL))
    place = Place('reference_list', None, mustaqil().part('references'), (), {'label': 'references'})
    academic.reference_list(ctx, place)
    assert ctx.marks == [(1, 'FOYDALANILGAN ADABIYOTLAR')]
    ctx = ctx_for(content(**FULL))
    academic.reference_list(ctx, Place('reference_list', None, None, (), {'label': 'references', 'in_toc': False}))
    assert ctx.marks == []


def test_reference_and_title_plain_fallbacks_draw_what_they_hold():
    ctx = ctx_for(content(section('references', items=SOURCES[:2]), **FULL))
    place = Place('reference_list', ctx.section('references'), mustaqil().part('references'), (),
                  {'label': 'references'})
    assert len(registry.draw(ctx, place, plain_only=True)) >= 3
    rows = catalogue.template('academic_mustaqil_ish')['flow'][0]
    place = Place('title_page', None, mustaqil().part('title_page'), tuple(rows['fields']), rows['params'])
    drawn = registry.draw(ctx, place, plain_only=True)
    assert 2 <= len(drawn) <= 9 and 'block_fallback:title_page' in ctx.warnings


def test_customer_text_on_the_academic_pages_is_text_never_markup(tmp_path):
    given = dict(FULL, topic='<b>Qalin</b> & <font size="40">katta</font>', student_name='A <i>B</i>')
    result, _, _ = references(tmp_path, ['Kitob <onDraw name="x"/> & boshqa. – 2020.'])
    assert '<onDraw' in pages_text(result)[0]
    result = draw(tmp_path, content(**given), template=template_with('academic_mustaqil_ish', [0]), name='t.pdf')
    text = pages_text(result)[0]
    assert '<b>Qalin</b> &' in text and 'A <i>B</i>' in text
    assert not [code for code in result['metadata']['warnings'] if code.startswith('block_fallback')]
