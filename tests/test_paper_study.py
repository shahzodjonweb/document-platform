"""The study family's papers (R3b): the test sheet, the konspekt, the lesson plan and its handout.

The blocks (apps/studio/paper/blocks/study.py) are drawn through the engine
and read back with pdfplumber, so each is held to what the page shows; the
templates are drawn from their samples in every language and case and read
by the checker (tests/paper_family.py). People, schools and questions are
invented.
"""
import datetime
import re

import pdfplumber
import pytest

from apps.studio import paper
from apps.studio.categories import catalogue
from apps.studio.paper import page, registry, sample
from apps.studio.paper.blocks import study
from apps.studio.paper.ctx import Ctx, Place
from tests import paper_family

DAY = datetime.date(2026, 11, 17)
STUDY = ('cell_strip', 'question_list', 'answer_key', 'formula_line')
# The test and the handout are drawn by the core blocks and these; the konspekt's plan and the lesson plan's cover
# are R3a's toc and title_page, so those two are read once R3a's blocks are registered here.
OWN = ['study_test', 'study_tarqatma']
WITH_R3A = ['study_konspekt', 'study_dars_ishlanmasi']
TEMPLATES = OWN + WITH_R3A


def needs_r3a(template_id):
    absent = registry.missing(paper.flow_blocks(catalogue.template(template_id)))
    return pytest.mark.skipif(bool(absent), reason=f'{template_id} needs {", ".join(absent)} (R3a)')


# ---------------------------------------------------------------- helpers


def question(stem, options=(), answer='', explanation='', marks=1, topic=''):
    return {'stem': stem, 'options': list(options), 'answer': answer, 'explanation': explanation, 'marks': marks,
            'topic': topic}


CHOICE = [question('Hujayraning irsiy axborotini nima saqlaydi?', ['Yadro', 'Ribosoma', 'Vakuola', 'Lizosoma'],
                   'Yadro', 'Yadroda DNK bor.'),
          question('Fotosintez qayerda kechadi?', ['Mitoxondriya', 'Lizosoma', 'Xloroplast', 'Ribosoma'],
                   'Xloroplast', 'Xloroplastda xlorofill bor.')]
PASSAGE = [question('Matnga ko‘ra, o‘simlik qaysi gazni yutadi?', ['Kislorod', 'Karbonat angidrid', 'Azot', 'Vodorod'],
                    'Karbonat angidrid', topic='passage'),
           question('Matnga ko‘ra, qaysi gaz ajraladi?', ['Kislorod', 'Azot', 'Vodorod', 'Geliy'], 'Kislorod',
                    topic='passage')]
OPEN = [question('Mitoxondriyaning vazifasini tushuntiring.', answer='Energiya hosil qiladi.',
                 explanation='Energiya — 1 ball, jarayon — 1 ball.', marks=2),
        question('Yadroning vazifasini yozing.', answer='Irsiy axborotni saqlaydi.', marks=3)]
FACTS = {'school': 'Namuna tumanidagi 7-maktab', 'subject': 'Biologiya', 'class_level': '7',
         'topic': 'Hujayra tuzilishi', 'time_min': '30'}


def facts_section(facts):
    return {'id': 'facts', 'heading': '', 'body': '', 'layout': 'list',
            'items': [{'label': key, 'text': value} for key, value in facts.items()]}


def draw_test(tmp_path, *, questions=None, facts=None, sections=(), locale='uz', pages=3, name='test.pdf'):
    """A test drawn in its template: the questions (all kinds by default) and facts given."""
    content = {'title': 'Biologiya', 'questions': CHOICE + PASSAGE + OPEN if questions is None else questions,
               'sections': [facts_section(FACTS if facts is None else facts), *sections]}
    return paper.render_paper(content, tmp_path / name, locale, entry=catalogue.get('pdf.test'),
                              template='study_test', pages=pages, day=DAY)


def passage_section(body='Fotosintez xloroplastlarda kechadi. O‘simlik karbonat angidridni yutadi.'):
    return {'id': 'passage', 'heading': 'Fotosintez', 'body': body, 'layout': 'text', 'items': []}


def pages_text(result):
    with pdfplumber.open(result['path']) as document:
        return [(page_.extract_text() or '').replace('\xa0', ' ') for page_ in document.pages]


def text(result):
    return '\n'.join(pages_text(result))


def flat(value):
    """Text with its lines joined: a sentence that wraps is still found."""
    return ' '.join(value.replace('\xa0', ' ').split())


def words(result, number=0):
    with pdfplumber.open(result['path']) as document:
        return [dict(word, text=word['text'].replace('\xa0', ' '))
                for word in document.pages[number].extract_words(extra_attrs=['fontname', 'size'])]


def leaves(flowables):
    """The flowables with every KeepTogether opened: a heading travels inside its first question's."""
    for flowable in flowables:
        content = getattr(flowable, '_content', None)
        if isinstance(content, list):
            yield from leaves(content)
        else:
            yield flowable


def clean(result):
    warnings = result['metadata']['warnings']
    return not result['metadata'].get('template_fallback') and not any(code.startswith('block_fallback')
                                                                       for code in warnings)


def context(*, questions=(), facts=None, sections=(), template='study_test', entry='pdf.test', locale='uz'):
    raw = catalogue.template(template)
    left, bottom, width, height = page.geometry(raw)
    content = {'title': 'Namuna', 'questions': list(questions),
               'sections': [facts_section(facts or {}), *sections]}
    return Ctx(content=content, entry=catalogue.get(entry), template=raw, locale=locale, step=0, pages=2,
               width=width, frame_height=height, day=DAY)


def place(block, part=None, params=None, ctx=None, section=None):
    found = ctx.entry.part(part) if ctx is not None and part else None
    return Place(block, section, found, tuple((found or {}).get('fields') or ()), dict(params or {}))


def flow_params(template, block, part):
    return next(item['params'] for item in catalogue.template(template)['flow']
                if item['block'] == block and item.get('part') == part)


# ---------------------------------------------------------------- registration and the templates


def test_the_study_blocks_are_registered_and_the_test_is_ready():
    assert not registry.missing(STUDY)
    assert paper.ready({'options': {'category': 'pdf.test'}, 'output_locale': 'uz'})
    for template_id in OWN:
        assert not registry.missing(paper.flow_blocks(catalogue.template(template_id))), template_id
    # What the konspekt and the lesson plan still wait for is R3a's alone.
    for template_id in WITH_R3A:
        assert set(registry.missing(paper.flow_blocks(catalogue.template(template_id)))) <= {'toc', 'title_page'}


def test_every_study_template_has_its_samples():
    paper_family.assert_has_samples(TEMPLATES)


@paper_family.each(OWN)
def test_the_test_and_the_handout_read_well(template_id, locale, case, tmp_path):
    paper_family.assert_reads_well(template_id, locale, case, tmp_path)


@pytest.mark.parametrize(('template_id', 'locale', 'case'), [
    pytest.param(*item.values, id=item.id, marks=needs_r3a(item.values[0]))
    for item in paper_family.matrix(WITH_R3A)])
def test_the_konspekt_and_the_lesson_plan_read_well(template_id, locale, case, tmp_path):
    paper_family.assert_reads_well(template_id, locale, case, tmp_path)


@pytest.mark.parametrize('locale', ('uz', 'ru', 'en'))
@pytest.mark.parametrize('index', range(len(study.SAMPLES)), ids=[item['name'] for item in study.SAMPLES])
def test_every_block_sample_draws_without_a_fallback(tmp_path, index, locale):
    path, warnings = sample.draw_block(study.SAMPLES[index], locale, tmp_path, index)
    assert not [code for code in warnings if code.startswith(('block_fallback', 'label_missing'))], warnings
    with pdfplumber.open(path) as document:
        assert (document.pages[0].extract_text() or '').strip()


def test_a_full_test_has_its_head_strip_parts_passage_written_answers_and_key_on_its_own_page(tmp_path):
    result = draw_test(tmp_path, sections=[passage_section()])
    assert clean(result), result['metadata']
    pages = pages_text(result)
    first = pages[0]
    for wanted in ('NAMUNA TUMANIDAGI 7-MAKTAB', 'Biologiya, 7-sinf', 'Hujayra tuzilishi', 'F.I.Sh.:', 'Sinf:',
                   'Sana:', 'Ball:', 'Baho:', 'I qism. To‘g‘ri javobni tanlang', 'Vaqt: 30 daqiqa.'):
        assert wanted in flat(first), wanted
    whole = text(result)
    assert '3-4-savollarga matn asosida javob bering.' in whole
    assert 'II qism. Yozma javob bering' in whole and '(2 ball)' in whole and '(3 ball)' in whole
    assert 'Javob:' in whole and '/ 2' in whole and '/ 3' in whole
    # The key starts its own page: its letters, the closed questions' points, the model answers numbered on.
    key = pages[-1]
    assert 'KALITLAR' in key.replace(' ', '') and 'KALITLAR' not in ''.join(pages[:-1]).replace(' ', '')
    assert 'Faqat o‘qituvchi uchun' in key and 'Test savollari uchun ball: 4' in key
    assert re.search(r'1 2 3 4\s*\nA C B A', key), key
    assert re.search(r'^5 Energiya hosil qiladi', key, re.M) and re.search(r'^6 Irsiy axborotni', key, re.M)
    # The pupil strip's total is every mark: four closed and five written.
    assert '/ 9' in first


def test_the_strip_total_is_the_customers_total_points_when_given(tmp_path):
    result = draw_test(tmp_path, facts={**FACTS, 'total_points': '20'})
    assert '/ 20' in pages_text(result)[0]


@pytest.mark.parametrize('locale, lead', [('uz', '3-4-savollarga matn asosida javob bering.'),
                                          ('ru', 'Ответьте на вопросы 3–4 по тексту.'),
                                          ('en', 'Answer questions 3–4 using the text.')])
def test_the_passage_reference_line_names_its_questions(tmp_path, locale, lead):
    result = draw_test(tmp_path, locale=locale, sections=[passage_section()], facts={'subject': 'Biology'})
    assert lead in text(result)


def test_one_passage_question_takes_the_singular_line(tmp_path):
    result = draw_test(tmp_path, questions=CHOICE + PASSAGE[:1], sections=[passage_section()])
    assert '3-savolga matn asosida javob bering.' in text(result)


def test_a_passage_longer_than_a_page_flows_with_its_rule_and_its_title_stays_with_it(tmp_path):
    long = ' '.join(['Fotosintez xloroplastlarda yorug‘lik ta’sirida kechadi.'] * 140)
    result = draw_test(tmp_path, sections=[passage_section(long)])
    assert clean(result), result['metadata']
    pages = pages_text(result)
    starts = next(index for index, page_text in enumerate(pages) if 'matn asosida javob bering' in page_text)
    assert 'Fotosintez' in pages[starts].split('matn asosida javob bering')[1]
    # It starts under the choice questions on the first page: no half page of white is pushed before it.
    assert starts == 0


def test_a_passage_with_its_question_too_tall_for_the_page_left_starts_where_it_stands(tmp_path):
    long = ' '.join(['Fotosintez xloroplastlarda yorug‘lik ta’sirida kechadi.'] * 40)
    pages = pages_text(draw_test(tmp_path, questions=PASSAGE + OPEN, sections=[passage_section(long)]))
    # The instruction, Part I, the reference line and the passage's title and first lines share the first page.
    first = flat(pages[0])
    assert 'Ko‘rsatma' in first and 'I qism.' in first and '1-2-savollarga matn asosida javob bering.' in first
    assert 'Fotosintez Fotosintez xloroplastlarda' in first


@pytest.mark.parametrize('extras', ('', 'answer_sheet'))
def test_a_part_heading_near_a_page_foot_goes_over_with_its_first_question(tmp_path, extras):
    facts = {**FACTS, 'answer_extras': extras} if extras else FACTS
    moved = False
    # The passage's length moves Part II down the first page and over its foot.
    for count in range(3, 25, 3):
        body = ' '.join(['Fotosintez xloroplastlarda yorug‘lik ta’sirida kechadi.'] * count)
        pages = pages_text(draw_test(tmp_path, sections=[passage_section(body)], facts=facts, name=f'{count}.pdf'))
        heading = next(index for index, page_text in enumerate(pages) if 'II qism. Yozma javob bering' in page_text)
        assert 'Mitoxondriyaning vazifasini' in pages[heading], (count, pages)
        moved = moved or heading > 0
    assert moved


def test_the_answer_sheets_head_near_a_page_foot_goes_over_with_its_grid(tmp_path):
    facts = {**FACTS, 'answer_extras': 'answer_sheet'}
    moved = False
    for count in range(16, 27, 2):
        body = ' '.join(['Fotosintez xloroplastlarda yorug‘lik ta’sirida kechadi.'] * count)
        pages = pages_text(draw_test(tmp_path, questions=CHOICE + PASSAGE, sections=[passage_section(body)],
                                     facts=facts, name=f'{count}.pdf'))
        sheet = next(index for index, page_text in enumerate(pages) if 'Javoblar varaqasi' in page_text)
        assert re.search(r'Javoblar varaqasi\s*\n\s*1 2 3 4', pages[sheet]), (count, pages)
        moved = moved or sheet > 0
    assert moved


def test_choice_only_has_no_part_headings_and_its_own_instruction(tmp_path):
    whole = text(draw_test(tmp_path, questions=CHOICE))
    assert 'I qism' not in whole and 'II qism' not in whole
    assert 'Har bir to‘g‘ri javob – 1 ball.' in whole and 'I qismda' not in whole


def test_written_only_says_so_and_draws_no_closed_key(tmp_path):
    result = draw_test(tmp_path, questions=OPEN)
    whole = text(result)
    assert 'Savollarga yozma, to‘liq javob bering.' in whole and 'doira ichiga' not in whole
    assert 'Test savollari' not in whole and 'Namunaviy javob' in whole
    assert re.search(r'^1\. Mitoxondriyaning', whole, re.M)


@pytest.mark.parametrize('use, head', [(None, 'KALITLAR'), ('self_study', 'JAVOBLAR')])
def test_written_only_model_answers_start_a_page_after_the_last_question(tmp_path, use, head):
    facts = {**FACTS, 'use': use} if use else FACTS
    pages = pages_text(draw_test(tmp_path, questions=OPEN, facts=facts))
    last = max(index for index, page_text in enumerate(pages) if 'Yadroning vazifasini yozing.' in page_text)
    answers = [index for index, page_text in enumerate(pages) if 'Namunaviy javob' in page_text]
    assert answers and min(answers) > last, pages
    # The key's head stands over the model answers on that page, without a grid of closed questions.
    assert head in pages[min(answers)].replace(' ', '') and 'Test savollari' not in pages[min(answers)]
    assert 'Maksimal ball: 5' in pages[-1]


def test_the_key_ends_with_the_papers_overall_maximum(tmp_path):
    key = pages_text(draw_test(tmp_path, sections=[passage_section()]))[-1]
    # One maximum on the page: the grid's line names the closed questions' points, the paper's maximum ends it.
    assert 'Test savollari uchun ball: 4' in key and 'Maksimal ball: 9 (4 + 5)' in key
    assert key.count('Maksimal ball') == 1 and key.index('Maksimal ball: 9') > key.index('Irsiy axborotni')
    given = pages_text(draw_test(tmp_path, facts={**FACTS, 'total_points': '20'}, name='given.pdf'))
    assert '/ 20' in given[0] and 'Maksimal ball: 20' in given[-1] and '(4 + 5)' not in given[-1]


def test_passage_and_written_questions_get_the_closed_instruction_and_both_part_headings(tmp_path):
    whole = flat(text(draw_test(tmp_path, questions=PASSAGE + OPEN, sections=[passage_section()])))
    assert 'I qism. To‘g‘ri javobni tanlang' in whole and 'II qism. Yozma javob bering' in whole
    assert 'doira ichiga oling' in whole and 'I qismda har bir to‘g‘ri javob – 1 ball.' in whole
    assert 'Savollarga yozma, to‘liq javob bering' not in whole
    assert whole.index('I qism.') < whole.index('1-2-savollarga matn asosida') < whole.index('II qism.')
    assert whole.index('doira ichiga') < whole.index('1-2-savollarga')
    # With choice questions as well, Part I is named once, over the choice questions.
    whole = flat(text(draw_test(tmp_path, sections=[passage_section()], name='all.pdf')))
    assert len(re.findall(r'(?<!I)I qism\.', whole)) == 1


def test_passage_questions_without_a_passage_get_no_reference_line(tmp_path):
    result = draw_test(tmp_path, questions=CHOICE + PASSAGE)
    assert 'matn asosida' not in text(result) and 'passage_missing' in result['metadata']['warnings']


def test_an_answer_sheet_changes_the_instruction_and_draws_empty_cells(tmp_path):
    result = draw_test(tmp_path, facts={**FACTS, 'answer_extras': 'answer_sheet'})
    whole = text(result)
    assert 'javoblar varaqasiga yozing' in flat(whole) and 'Javoblar varaqasi' in whole


def test_self_study_has_no_strip_no_score_tab_and_an_explained_key(tmp_path):
    result = draw_test(tmp_path, facts={**FACTS, 'use': 'self_study'})
    assert clean(result)
    pages = pages_text(result)
    assert 'F.I.Sh.' not in pages[0] and 'Baho' not in pages[0]
    assert 'O‘zingizni sinab ko‘ring' in pages[0]
    whole = text(result)
    assert 'Ball: / 2' not in whole.replace('  ', ' ')
    key = pages[-1]
    assert 'J A V O B L A R' in key or 'JAVOBLAR' in key.replace(' ', '')
    assert 'Izoh' in key and 'Yadroda DNK bor.' in key and 'KALITLAR' not in key.replace(' ', '')


def test_an_explained_key_adds_the_reasons_under_the_grid(tmp_path):
    key = pages_text(draw_test(tmp_path, facts={**FACTS, 'answer_extras': 'explained'}))[-1]
    assert 'Maksimal ball' in key and 'Izoh' in key and 'Xloroplastda xlorofill bor.' in key


def test_no_name_line_leaves_the_teachers_cells_at_the_right_and_a_bsb_has_no_mark(tmp_path):
    result = draw_test(tmp_path, facts={**FACTS, 'pupil_identity': 'false'}, name='a.pdf')
    first = words(result)
    assert not [word for word in first if word['text'].startswith(('F.I.Sh', 'Sinf:', 'Sana:'))]
    left, bottom, width, height = page.geometry(catalogue.template('study_test'))
    ball = next(word for word in first if word['text'] == 'Ball:')
    assert ball['x0'] > left + width * 0.6
    bsb = words(draw_test(tmp_path, facts={**FACTS, 'kind': '2-BSB'}, name='b.pdf'))
    assert not [word for word in bsb if word['text'] == 'Baho:'] and [word for word in bsb if word['text'] == 'Ball:']
    tracked = ''.join(word['text'] for word in bsb)
    assert '2-BSB' in tracked


def test_teacher_score_false_drops_the_score_cells_and_the_tabs(tmp_path):
    result = draw_test(tmp_path, facts={**FACTS, 'teacher_score': 'false'})
    first = pages_text(result)[0]
    assert 'F.I.Sh.' in first and 'Baho' not in first and 'Ball:' not in first
    # No tab under a written answer either: the pages before the key carry no "Ball:" at all.
    assert not [page_text for page_text in pages_text(result)[:-1] if 'Ball:' in page_text]


def test_customer_text_is_text_never_markup(tmp_path):
    hostile = [question('<b>Qalin</b> & <font size="40">katta</font> savol?', ['<i>A</i>', 'B & C', 'D', 'E'],
                        'B & C')]
    result = draw_test(tmp_path, questions=hostile)
    assert clean(result)
    assert '<b>Qalin</b> & <font size="40">katta</font> savol?' in text(result)


# ---------------------------------------------------------------- the key letter


@pytest.mark.parametrize('answer, letter', [
    ('Xloroplast', 'C'), ('  xloroplast. ', 'C'), ('C) Xloroplast', 'C'), ('C', 'C'), ('c)', 'C'),
    ('Xloroplastt', 'C'), ('Golji apparati', None), ('', None)])
def test_the_key_letter_is_the_matching_option_never_a_guess(answer, letter):
    found = {'options': ['Mitoxondriya', 'Lizosoma', 'Xloroplast', 'Ribosoma'], 'answer': answer}
    assert study.key_letter(found) == letter


@pytest.mark.parametrize('options, answer, letter', [
    (['−5', '−3', '3', '5'], '5', 'D'), (['−5', '−3', '3', '5'], '−5', 'A'), (['−5', '−3', '3', '5'], '-5', 'A'),
    (['−5', '−3', '3', '5'], '3.', 'C'), (['-12', '12', '-1,2', '1,2'], '12', 'B'),
    (['x > 2', 'x < 2', 'x ≥ 2', 'x ≤ 2'], 'x < 2', 'B'), (['x > 2', 'x < 2', 'x ≥ 2', 'x ≤ 2'], 'x<2', 'B'),
    (['x > 2', 'x < 2', 'x ≥ 2', 'x ≤ 2'], 'x ≤ 2', 'D'), (['x > 2', 'x < 2', 'x ≥ 2', 'x ≤ 2'], 'x >= 2', 'C'),
    (['a + b', 'a − b', 'ab', 'a/b'], 'a − b', 'B'), (['a + b', 'a − b', 'ab', 'a/b'], 'a-b', 'B'),
    (['a + b', 'a − b', 'ab', 'a/b'], 'a/b', 'D'), (['a + b', 'a − b', 'ab', 'a/b'], 'ab', 'C'),
    (['2x + 3y = 12', '2x − 3y = 12', '3x + 2y = 12', '2x + 3y = 21'], '2x − 3y = 12', 'B'),
    # One text twice once normalised: neither letter, and never the alike match.
    (['5', '5.', '3', '7'], '5', None), (['a+b', 'a + b', 'ab', 'ba'], 'a + b', 'B'),
    (['a+b', 'a + b', 'ab', 'ba'], 'a+ b', None),
    # A wrong answer that only looks like an option is printed, not given its letter.
    (['1, 3, 4, 6', '1, 2', '2, 5', '3, 6'], '1, 3, 4, 5', None), (['−5', '−3', '3', '5'], '4', None),
    (['2x + 3y = 12', '2x − 3y = 12', 'x', 'y'], '2x + 3y = 13', None)])
def test_signs_and_numbers_keep_the_key_letter_apart(options, answer, letter):
    assert study.key_letter({'options': options, 'answer': answer}) == letter


@pytest.mark.parametrize('options', [
    ['А. Н. Толстой', 'Л. Н. Толстой', 'А. П. Чехов', 'И. С. Тургенев'],
    ['A. Qodiriy', 'E. Vohidov', 'A. Oripov', 'G‘. G‘ulom'],
    ['B. Franklin', 'A. Lincoln', 'G. Washington', 'D. Eisenhower'],
    ['A) Navoiy', 'C) Bobur', 'B) Furqat', 'D) Muqimiy'],
    ['A) 5', 'B. 6', 'C) 7'], ['A:B', 'B:C', 'C:D', 'D:E']])
def test_initials_and_letters_out_of_order_are_kept_as_written(options):
    assert study._options({'options': options}) == options


@pytest.mark.parametrize('options, printed', [
    (['A) Yadro', 'B) Ribosoma', 'C) Vakuola', 'D) Lizosoma'], ['Yadro', 'Ribosoma', 'Vakuola', 'Lizosoma']),
    (['а) Ядро', 'б) Рибосома', 'в) Вакуоль'], ['Ядро', 'Рибосома', 'Вакуоль']),
    (['А) Ядро', 'Б) Рибосома', 'В) Вакуоль', 'Г) Лизосома'], ['Ядро', 'Рибосома', 'Вакуоль', 'Лизосома']),
    (['a: 1', 'b: 2', 'c: 3', 'd: 4'], ['1', '2', '3', '4'])])
def test_letters_every_option_carries_in_order_are_taken_off(options, printed):
    assert study._options({'options': options}) == printed


@pytest.mark.parametrize('options, answer, letter', [
    (['А. Н. Толстой', 'Л. Н. Толстой', 'А. П. Чехов', 'И. С. Тургенев'], 'Л. Н. Толстой', 'B'),
    (['А. Н. Толстой', 'Л. Н. Толстой', 'А. П. Чехов', 'И. С. Тургенев'], 'А. П. Чехов', 'C'),
    (['А. Н. Толстой', 'Л. Н. Толстой', 'А. П. Чехов', 'И. С. Тургенев'], 'И. С. Тургенев', 'D'),
    (['A. Qodiriy', 'E. Vohidov', 'A. Oripov', 'Cho‘lpon'], 'E. Vohidov', 'B'),
    (['A. Qodiriy', 'E. Vohidov', 'A. Oripov', 'Cho‘lpon'], 'A. Oripov', 'C'),
    (['A) Yadro', 'B) Ribosoma', 'C) Vakuola', 'D) Lizosoma'], 'C) Vakuola', 'C'),
    (['А) Ядро', 'Б) Рибосома', 'В) Вакуоль', 'Г) Лизосома'], 'В) Вакуоль', 'C'),
    (['Ядро', 'Рибосома', 'Вакуоль', 'Лизосома'], 'В) Рибосома', 'B'),
    # A Cyrillic letter alone counts by its place in the Russian list, unless it looks like a Latin letter.
    (['Ядро', 'Рибосома', 'Вакуоль', 'Лизосома'], 'Б', 'B'), (['Ядро', 'Рибосома', 'Вакуоль', 'Лизосома'], 'г)', 'D'),
    (['Ядро', 'Рибосома', 'Вакуоль', 'Лизосома'], 'В', None), (['Ядро', 'Рибосома', 'Вакуоль', 'Лизосома'], 'Е', None),
    (['Ядро', 'Рибосома', 'Вакуоль'], 'Г', None), (['Б', 'Г', 'Д', 'Ж'], 'Г', 'B'),
    # The typed letter and the text name different options: no letter.
    (['Mitoxondriya', 'Lizosoma', 'Xloroplast', 'Ribosoma'], 'A) Xloroplast', None)])
def test_initials_in_options_and_answers_still_find_their_letter(options, answer, letter):
    assert study.key_letter({'options': options, 'answer': answer}) == letter


def test_a_name_with_initials_is_printed_whole_in_the_test_and_its_key(tmp_path):
    names = [question('«Pyotr I» romanini kim yozgan?', ['А. Н. Толстой', 'Л. Н. Толстой', 'А. П. Чехов',
                                                           'И. С. Тургенев'], 'А. Н. Толстой'),
             question('«O‘tkan kunlar» muallifi kim?', ['A. Qodiriy', 'E. Vohidov', 'A. Oripov', 'Cho‘lpon'],
                      'E. Vohidov'),
             question('Qaysi son eng katta?', ['−5', '−3', '3', '5'], '5'),
             question('Tengsizlik qaysi?', ['x > 2', 'x < 2', 'x ≥ 2', 'x ≤ 2'], 'x < 2')]
    pages = pages_text(draw_test(tmp_path, questions=names))
    first = flat(pages[0])
    for wanted in ('А. Н. Толстой', 'Л. Н. Толстой', 'А. П. Чехов', 'И. С. Тургенев', 'A. Qodiriy', 'E. Vohidov'):
        assert wanted in first, wanted
    assert re.search(r'1 2 3 4\s*\nA B D B', pages[-1]), pages[-1]


def test_two_options_equally_alike_give_no_letter():
    assert study.key_letter({'options': ['abcdeX', 'abcdeY'], 'answer': 'abcdeZ'}) is None
    assert study.key_letter({'options': ['abcdeX', 'qwerty'], 'answer': 'abcdeZ'}) == 'A'


def test_an_answer_no_option_matches_is_printed_in_its_cell(tmp_path):
    odd = [question('Qaysi?', ['Bir', 'Ikki', 'Uch', 'To‘rt'], 'Besh')]
    key = pages_text(draw_test(tmp_path, questions=odd))[-1]
    assert 'Besh' in key


def test_the_key_grid_balances_its_rows_at_ten_at_most(tmp_path):
    many = [question(f'Savol {number}?', ['Bir', 'Ikki', 'Uch', 'To‘rt'], 'Ikki') for number in range(1, 15)]
    key = pages_text(draw_test(tmp_path, questions=many, pages=3))[-1]
    assert re.search(r'^1 2 3 4 5 6 7$', key, re.M) and re.search(r'^8 9 10 11 12 13 14$', key, re.M)
    assert 'Maksimal ball: 14' in key


# ---------------------------------------------------------------- question_list


@pytest.mark.parametrize('options, columns', [
    (['Yadro', 'Ribosoma', 'Vakuola', 'Lizosoma'], 4),
    (['Hujayra membranasi', 'Hujayra markazi', 'Golji apparati', 'Endoplazmatik to‘r'], 2),
    (['Ularda shakllangan yadro va mitoxondriya bo‘lmaydi', 'B', 'C', 'D'], 1)])
def test_options_take_four_two_or_one_columns_by_their_widest(options, columns):
    ctx = context()
    assert study._option_columns(ctx, options, ctx.styles['body'], 0) == columns
    assert study._option_columns(ctx, options, ctx.styles['body'], 2) == 2


def test_four_short_options_stand_on_one_line_after_the_stem(tmp_path):
    result = draw_test(tmp_path, questions=CHOICE[:1], facts={'subject': 'Fan'})
    line = next(row for row in pages_text(result)[0].splitlines() if row.startswith('A)'))
    assert line == 'A) Yadro B) Ribosoma C) Vakuola D) Lizosoma'


def test_statements_set_in_two_columns_from_six_and_numbers_run_through_the_paper(tmp_path):
    dtm = question('Qaysilari membranali?\n1) yadro\n2) ribosoma\n3) mitoxondriya\n4) xloroplast\n5) sentriola\n'
                   '6) lizosoma', ['1, 3', '2, 5', '1, 4', '3, 6'], '1, 4')
    first = pages_text(draw_test(tmp_path, questions=[dtm] + OPEN[:1]))[0]
    assert re.search(r'^1\) yadro 4\) xloroplast$', first, re.M)
    assert re.search(r'^2\. Mitoxondriyaning', first, re.M)


def test_a_written_question_has_two_dotted_rows_a_mark_and_its_tab():
    ctx = context(questions=OPEN)
    made = study.question_list(ctx, place('question_list', 'part_open', flow_params('study_test', 'question_list',
                                                                                    'part_open'), ctx))
    boxes = [flowable for item in made for flowable in getattr(item, '_content', [item])
             if isinstance(flowable, study.AnswerBox)]
    assert [box.rows for box in boxes] == [4, 6]
    assert [box.tab for box in boxes] == [('Ball:', '/ 2'), ('Ball:', '/ 3')]
    self_study = context(questions=OPEN, facts={'use': 'self_study'})
    made = study.question_list(self_study, place('question_list', 'part_open',
                                                 flow_params('study_test', 'question_list', 'part_open'),
                                                 self_study))
    assert all(box.tab is None for item in made for box in getattr(item, '_content', [item])
               if isinstance(box, study.AnswerBox))


def test_a_list_without_its_questions_draws_nothing():
    ctx = context(questions=CHOICE)
    assert study.question_list(ctx, place('question_list', 'part_open', {'filter': 'open'}, ctx)) == []
    assert study.answer_key(context(questions=OPEN), place('answer_key', 'answer_key', {'style': 'grid'},
                                                           context())) == []


def test_the_intro_is_drawn_once_over_the_first_questions():
    ctx = context(questions=CHOICE + OPEN, facts={'time_min': '25'})
    choice = study.question_list(ctx, place('question_list', 'part_choice',
                                            flow_params('study_test', 'question_list', 'part_choice'), ctx))
    opened = study.question_list(ctx, place('question_list', 'part_open',
                                            flow_params('study_test', 'question_list', 'part_open'), ctx))
    intro = [flat(flowable.text) for flowable in leaves(choice + opened) if hasattr(flowable, 'text') and
             'Ko‘rsatma' in flowable.text]
    assert len(intro) == 1 and 'Vaqt: 25 daqiqa.' in intro[0] and 'I qismda' in intro[0]


# ---------------------------------------------------------------- cell_strip


def test_a_head_box_drops_a_cell_left_out_stretches_its_neighbour_and_leaves_a_blank_empty(tmp_path):
    entry = catalogue.get('pdf.dars_ishlanmasi')
    content = {'title': 'Kasrlar', 'questions': [], 'sections': [facts_section(
        {'grade': '5-«A»', 'subject': 'Matematika', 'topic': 'Kasrlarni qo‘shish'})]}
    raw = dict(catalogue.template('study_dars_ishlanmasi'))
    raw['flow'] = [item for item in raw['flow'] if item['block'] == 'cell_strip']
    result = paper.render_paper(content, tmp_path / 'head.pdf', 'uz', entry=entry, template=raw, pages=2, day=DAY)
    assert clean(result), result['metadata']
    found = words(result)
    names = [word['text'] for word in found]
    # The date and the teacher draw blanks: their cells stay, empty. The school and the length are left out.
    assert 'Sana' in names and 'O‘qituvchi' in names and 'Maktab' not in names and 'Davomiyligi' not in names
    assert 'Matematika' in names and 'Kasrlarni' in names
    with pdfplumber.open(result['path']) as document:
        rects = document.pages[0].rects
    left, bottom, width, height = page.geometry(raw)
    teacher_box = [rect for rect in rects if abs(rect['width'] - width) < 2]
    assert len(teacher_box) >= 2


@pytest.mark.parametrize('locale, word, note', [('uz', 'JAVOBLAR', 'tarqatilmaydi'),
                                                ('ru', 'ОТВЕТЫ', 'не раздаётся'),
                                                ('en', 'ANSWERS', 'not handed out')])
def test_the_handouts_answers_are_on_a_sheet_of_their_own(tmp_path, locale, word, note):
    drawn = paper_family.draw('study_tarqatma', locale, 'full', tmp_path)
    pages = pages_text(drawn.artifact)
    last_task = drawn.content['sections'][-2]['heading']
    tasks = max(index for index, page_text in enumerate(pages) if last_task in flat(page_text))
    key = next(index for index, page_text in enumerate(pages) if word in page_text.replace(' ', ''))
    assert key > tasks and note in flat(pages[key]) and not any(note in flat(page_text) for page_text in pages[:key])
    assert drawn.artifact['page_count'] <= drawn.pages


def test_a_cell_strip_without_rows_draws_nothing_and_its_fallback_says_label_and_blank():
    ctx = context()
    assert study.cell_strip(ctx, place('cell_strip', 'pupil_line', {}, ctx)) == []
    plain = study._strip_plain(ctx, place('cell_strip', 'pupil_line', {'rows': study.PUPIL_ROWS}, ctx))
    assert 'F.I.Sh.:' in plain[0].text and 'Baho:' in plain[0].text


# ---------------------------------------------------------------- formula_line


def test_formulas_are_numbered_by_their_section_with_scripts_and_their_legend(tmp_path):
    entry = catalogue.get('pdf.konspekt')
    raw = dict(catalogue.template('study_konspekt'))
    raw['flow'] = [item for item in raw['flow'] if item.get('part') in ('section', 'formulas')]
    sections = [facts_section({'topic': 'Dinamika'}),
                {'id': 'section', 'heading': 'Kuch', 'body': 'Kuch haqida.', 'layout': 'text', 'items': []},
                {'id': 'section_2', 'heading': 'Energiya', 'body': 'Energiya haqida.', 'layout': 'text',
                 'items': []},
                {'id': 'formulas_2', 'heading': '', 'body': '', 'layout': 'list', 'items': [
                    {'label': 'E_{k} = m · v^{2} / 2', 'text': 'E_{k} — kinetik energiya.', 'value': ''},
                    {'label': 'p = m · v', 'text': 'bu yerda: p — impuls.', 'value': '7'}]}]
    content = {'title': 'Dinamika', 'questions': [], 'sections': sections}
    result = paper.render_paper(content, tmp_path / 'formulas.pdf', 'uz', entry=entry, template=raw, pages=2,
                                day=DAY)
    assert clean(result), result['metadata']
    whole = text(result)
    assert '(2.1)' in whole and '(7)' in whole
    assert 'bu yerda: E' in whole and whole.count('bu yerda:') == 2
    found = words(result)
    script = [word for word in found if word['text'].startswith('k') and word['size'] < 11]
    assert script and all(word['size'] >= 9 for word in script)


def test_a_formula_list_without_formulas_draws_nothing_and_its_fallback_is_a_line():
    ctx = context(template='study_konspekt', entry='pdf.konspekt')
    assert study.formula_line(ctx, place('formula_line', 'formulas', {}, ctx, section={'items': []})) == []
    section = {'items': [{'label': 'F = m · a', 'text': 'bu yerda: F — kuch.'}]}
    plain = study._formula_plain(ctx, place('formula_line', 'formulas', {}, ctx, section=section))
    assert 'F = m · a — bu yerda: F — kuch.' in plain[0].text.replace('\xa0', ' ')


# ---------------------------------------------------------------- fallbacks


@pytest.mark.parametrize('name', ('cell_strip', 'question_list', 'answer_key'))
def test_a_block_that_raises_is_drawn_by_its_plain_fallback(tmp_path, monkeypatch, name):
    def broken(ctx, place_):
        raise RuntimeError('broken on purpose')
    monkeypatch.setitem(registry.BLOCKS, name, registry.Block(name, broken, registry.BLOCKS[name].fallback))
    result = draw_test(tmp_path, facts={**FACTS, 'answer_extras': 'answer_sheet'})
    assert f'block_fallback:{name}' in result['metadata']['warnings']
    assert not result['metadata'].get('template_fallback')
    wanted = {'cell_strip': 'F.I.Sh.:', 'question_list': '1. Hujayraning', 'answer_key': '1 — A'}[name]
    assert wanted in flat(text(result))


def test_a_raising_formula_line_is_drawn_as_body_lines(monkeypatch):
    def broken(ctx, place_):
        raise RuntimeError('broken on purpose')
    monkeypatch.setitem(registry.BLOCKS, 'formula_line', registry.Block('formula_line', broken,
                                                                        registry.BLOCKS['formula_line'].fallback))
    ctx = context(template='study_konspekt', entry='pdf.konspekt')
    drawn = registry.draw(ctx, place('formula_line', 'formulas', {}, ctx, section={'items': [{'label': 'F = m · a'}]}))
    assert 'block_fallback:formula_line' in ctx.warnings and 'F = m · a' in flat(drawn[0].text)


def test_the_key_fallback_writes_number_and_letter_lines():
    ctx = context(questions=CHOICE)
    lines = [flat(flowable.text) for flowable in study._key_plain(ctx, place('answer_key', 'answer_key',
                                                                             {'label': 'key'}, ctx))
             if hasattr(flowable, 'text')]
    assert lines[0] == 'KALITLAR' and '1 — A' in lines[1] and '2 — C' in lines[2]
    sheet = study._key_plain(ctx, place('answer_key', 'answer_sheet', {'style': 'sheet'}, ctx))
    assert '<u ' in sheet[0].text and '— A' not in sheet[0].text


def test_the_question_fallback_is_todays_list():
    ctx = context(questions=CHOICE + OPEN)
    lines = [flat(flowable.text) for flowable in study._questions_plain(ctx, place('question_list', 'part_choice',
                                                                                   {'filter': 'all'}, ctx))
             if hasattr(flowable, 'text')]
    assert lines[0].startswith('1. Hujayraning') and any('A) Yadro' in line for line in lines)
    assert any(line.startswith('3. Mitoxondriyaning') and '(2)' in line for line in lines)


@pytest.mark.parametrize('options, answer, letter', [
    (['an', 'a', 'the', '—'], 'a', 'B'), (['Ca', 'C', 'Co', 'Cu'], 'C', 'B'), (['D', 'E', 'B', 'G'], 'D', 'A'),
    (['a', 'x', 'b', 'y'], 'b', 'C'), (['a', 'x', 'b', 'y'], 'a', 'A'), (['a', 'x', 'b', 'y'], 'C', None),
], ids=['article', 'symbol', 'note', 'variable', 'variable-first', 'letter-of-no-option'])
def test_an_answer_whose_option_is_one_letter_is_keyed_by_its_text(options, answer, letter):
    # pdf.test asks the model to copy the correct option's text: "a" is the article, not option A.
    assert study.key_letter({'options': options, 'answer': answer}) == letter


def test_an_articles_test_is_keyed_by_the_options_text_in_the_drawn_key(tmp_path):
    articles = [question('I have ___ dog.', ['an', 'a', 'the', '—'], 'a'),
                question('She is ___ engineer.', ['an', 'a', 'the', '—'], 'an'),
                question('___ sun is hot.', ['an', 'a', 'The', '—'], 'The'),
                question('He bought ___ car.', ['the', 'an', 'a', '—'], 'a')]
    pages = pages_text(draw_test(tmp_path, questions=articles))
    assert re.search(r'1 2 3 4\s*\nB A C C', pages[-1]), pages[-1]
