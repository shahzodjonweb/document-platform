"""The core paper blocks (apps/studio/paper/blocks/core.py): each parameter variant, the ariza they draw, fallbacks.

The papers are drawn through the engine (render_paper) and read back with
pdfplumber, so a block is held to what the page shows: the words, their
order and place, the rules and boxes. People and organisations are invented.
"""
import datetime
import re

import pdfplumber
import pytest
from reportlab.platypus import Paragraph

from apps.studio import paper
from apps.studio.categories import catalogue
from apps.studio.paper import page, registry
from apps.studio.paper.blocks import core
from apps.studio.paper.ctx import Ctx, places

DAY = datetime.date(2026, 11, 17)
CORE = ('paragraph', 'line', 'heading', 'doc_title', 'list', 'table', 'kv_table', 'callout', 'inline_blank',
        'ruled_blank', 'signature_row', 'date_line', 'doc_head', 'party_block', 'approval_block')
LOCALES = ('uz', 'ru', 'en')


# ---------------------------------------------------------------- helpers


def sample(locale='uz', flow=(), *, facts=None, sections=None, questions=None, labels=None, **changes):
    """The sample entry, a template drawing `flow`, and content with `facts` (all the sample's by default)."""
    entry, template, content = core.sample_paper(locale, samples=())
    # A label given as None is taken out of the template, to draw what a template without it draws.
    merged = {key: value for key, value in {**template['labels'], **(labels or {})}.items() if value is not None}
    template = dict(template, flow=[dict(item) for item in flow], labels=merged, **changes)
    if facts is not None:
        content['sections'][0]['items'] = [{'label': key, 'text': value} for key, value in facts.items()]
    for section in sections or ():
        content['sections'] = [item for item in content['sections'] if item['id'] != section['id']] + [section]
    if questions is not None:
        content['questions'] = questions
    return entry, template, content


def draw(tmp_path, flow, locale='uz', *, pages=1, name='paper.pdf', **options):
    entry, template, content = sample(locale, flow, **options)
    return paper.render_paper(content, tmp_path / name, locale, entry=entry, template=template, pages=pages,
                              day=DAY)


def pdf(result):
    return pdfplumber.open(result['path'])


def text(result):
    with pdf(result) as document:
        return '\n'.join(page_.extract_text() or '' for page_ in document.pages).replace('\xa0', ' ')


def words(result, page_number=0):
    with pdf(result) as document:
        return [dict(word, text=word['text'].replace('\xa0', ' '))
                for word in document.pages[page_number].extract_words(extra_attrs=['fontname', 'size'])]


def word(result, needle, page_number=0):
    return next(item for item in words(result, page_number) if needle in item['text'])


def clean(result):
    """No placement was drawn plain and the template was not given up."""
    warnings = result['metadata']['warnings']
    return not result['metadata'].get('template_fallback') and not any(code.startswith('block_fallback')
                                                                       for code in warnings)


def section(part_id, body='', items=(), heading='', layout='text'):
    return {'id': part_id, 'heading': heading, 'body': body, 'layout': layout, 'items': list(items)}


def frame(result_or_template=None):
    left, bottom, width, height = page.geometry(sample()[1])
    return left, width


def context(locale='uz', flow=(), **options):
    entry, template, content = sample(locale, flow, **options)
    left, bottom, width, height = page.geometry(template)
    return Ctx(content=content, entry=entry, template=template, locale=locale, step=0, pages=1, width=width,
               frame_height=height, day=DAY)


def made(ctx):
    """Every placement of the context's flow drawn: [(place, flowables)]."""
    return [(place, registry.draw(ctx, place)) for place in places(ctx)]


def ariza_content(**given):
    request = given.pop('request', 'Men 2026-yil 3-noyabrdan 12-noyabrgacha kasallik tufayli qoldirgan darslarimni '
                                   'uzrli deb hisoblashingizni so‘rayman.')
    enclosures = given.pop('enclosures', ['Shifokor ma’lumotnomasi.'])
    statements = given.pop('statements', [])
    return {'title': 'Ariza', 'questions': [], 'sections': [
        section('facts', items=[{'label': key, 'text': value} for key, value in given.items()], layout='list'),
        section('request', request),
        section('statements', items=[{'label': '', 'text': text_} for text_ in statements], layout='list'),
        section('enclosures', items=[{'label': '', 'text': text_} for text_ in enclosures], layout='list')]}


FULL = dict(addressee_org='Namuna davlat universiteti', addressee_position='iqtisodiyot fakulteti dekani '
            'dotsent K. M. Sodiqovga', applicant_role='iqtisodiyot fakulteti 2-kurs, 205-guruh talabasi',
            applicant_name='Karimova Dilnoza Rustam qizidan', phone='+998 90 123 45 67',
            signer_name='D. R. Karimova', date_written='14.11.2026')


def ariza(tmp_path, content, locale='uz', name='ariza.pdf'):
    return paper.render_paper(content, tmp_path / name, locale, entry=catalogue.get('pdf.xat.ariza'),
                              template='official_ariza', pages=1, day=DAY)


# ---------------------------------------------------------------- registration and the ariza


def test_the_core_blocks_are_registered_and_an_ariza_is_drawn_by_them_alone():
    for name in CORE:
        assert registry.BLOCKS[name].draw.__module__ == core.__name__
    draft = {'options': {'category': 'pdf.xat.ariza', 'length': 1}, 'output_locale': 'uz', 'prompt': 'Ariza'}
    assert paper.ready(draft)
    problems = [str(problem) for problem in catalogue.check('pdf.xat.ariza')]
    assert not any('not yet registered' in problem for problem in problems)


def test_a_full_ariza_is_one_page_with_every_fact_its_word_and_its_captions(tmp_path):
    result = ariza(tmp_path, ariza_content(**FULL))
    assert clean(result) and result['page_count'] == 1 and result['metadata']['fit_step'] == 0
    shown = text(result)
    for value in ('Namuna davlat universiteti', 'Sodiqovga', '205-guruh', 'Karimova Dilnoza Rustam qizidan',
                  'Tel.: +998 90 123 45 67', 'ARIZA', 'so‘rayman', 'Ilova:', 'Shifokor ma’lumotnomasi.',
                  '14.11.2026', 'D. R. Karimova', 'Sana', 'Imzo', 'F.I.Sh.'):
        assert value in shown, value
    left, width = frame()
    template = catalogue.template('official_ariza')
    tleft, _, twidth, _ = page.geometry(template)
    # The addressee and the applicant stand in the right half; the word is centred on the frame.
    assert word(result, 'Namuna')['x0'] >= tleft + twidth / 2 - 1
    title = word(result, 'ARIZA')
    assert abs((title['x0'] + title['x1']) / 2 - (tleft + twidth / 2)) < 3
    assert 'Bold' in title['fontname']
    # Same content, same bytes.
    again = ariza(tmp_path, ariza_content(**FULL), name='again.pdf')
    assert (tmp_path / 'ariza.pdf').read_bytes() == (tmp_path / 'again.pdf').read_bytes()


def test_a_blank_ariza_draws_ruled_rows_with_captions_and_the_reason_lines(tmp_path):
    result = ariza(tmp_path, ariza_content(reason='____', phone='____', enclosures=[],
                                           request='Meni akademik ta’tilga chiqarishingizni so‘rayman.'))
    assert clean(result) and result['page_count'] == 1
    shown = text(result)
    for value in ('(tashkilot nomi)', '(rahbarning lavozimi, F.I.Sh.)', '(F.I.Sh.)', 'Tel.:', 'Sababi:', 'Sana'):
        assert value in shown, value
    assert 'Ilova' not in shown and '_' not in shown
    with pdf(result) as document:
        # Four party rows, the Tel. row, two reason rules and three signature rules.
        assert len(document.pages[0].lines) >= 10


@pytest.mark.parametrize('locale, word_, enclosures, label', [
    ('ru', 'ЗАЯВЛЕНИЕ', ['Справка от врача.', 'Копия паспорта.'], 'Приложение:'),
    ('en', 'APPLICATION', ['Doctor’s certificate.'], 'Enclosure:'),
    ('en', 'APPLICATION', ['Doctor’s certificate.', 'Copy of passport.'], 'Enclosures:')])
def test_an_ariza_in_russian_and_english_has_its_words_and_the_plural_label(tmp_path, locale, word_, enclosures,
                                                                            label):
    content = ariza_content(addressee_org='Example State University', applicant_name='Nilufar Toshmatova',
                            signer_name='N. Toshmatova', request='I ask for annual paid leave of 21 calendar days.',
                            enclosures=enclosures)
    result = ariza(tmp_path, content, locale)
    shown = text(result)
    assert clean(result) and word_ in shown and label in shown
    assert ('Signature' if locale == 'en' else 'Подпись') in shown


def test_a_long_ariza_takes_a_page_with_its_enclosures_and_signatures_whole(tmp_path):
    long = ' '.join(['Men 2026-yil 3-noyabrdan 12-noyabrgacha bo‘lgan davrda kasallik sababli darslarga qatnasha '
                     'olmadim, shu sababli dars qoldirishlarimni uzrli deb hisoblashingizni so‘rayman.'] * 7)
    content = ariza_content(**dict(FULL, request=f'{long}\n{long}',
                                   enclosures=[f'Ma’lumotnoma {number} nusxasi.' for number in range(1, 7)]))
    result = ariza(tmp_path, content)
    assert clean(result) and result['page_count'] == 2
    assert 'longer_than_quoted' in result['metadata']['warnings']
    with pdf(result) as document:
        last = (document.pages[1].extract_text() or '').replace('\xa0', ' ')
    for value in ('Ilova:', 'Ma’lumotnoma 1 nusxasi.', 'Ma’lumotnoma 6 nusxasi.', 'D. R. Karimova', 'F.I.Sh.'):
        assert value in last, value


# ---------------------------------------------------------------- every sample


@pytest.mark.parametrize('locale', LOCALES)
@pytest.mark.parametrize('index', range(len(core.SAMPLES)),
                         ids=[f"{item['block']}:{item['case']}" for item in core.SAMPLES])
def test_every_sample_draws_without_a_fallback(tmp_path, index, locale):
    item = core.SAMPLES[index]
    entry, template, content = core.sample_paper(locale, samples=[item])
    result = paper.render_paper(content, tmp_path / 'one.pdf', locale, entry=entry, template=template, pages=1,
                                day=DAY)
    assert clean(result), result['metadata']['warnings']
    with pdf(result) as document:
        first = document.pages[0]
        assert first.chars or first.lines or first.rects
        assert all(not char['text'] == '_' for page_ in document.pages for char in page_.chars)


@pytest.mark.parametrize('locale', LOCALES)
def test_the_sample_paper_draws_every_block_with_its_glyphs(tmp_path, locale):
    entry, template, content = core.sample_paper(locale)
    assert {item['block'] for item in core.SAMPLES} == set(CORE)
    result = paper.render_paper(content, tmp_path / 'blocks.pdf', locale, entry=entry, template=template, pages=1,
                                day=DAY)
    assert clean(result) and 'glyphs_dropped' not in result['metadata']['warnings']
    shown = text(result)
    if locale == 'uz':
        assert 'o‘rganish' in shown and 'ma’lumotnomasi' in shown and 'G‘. O‘. Rahimov' in shown
    if locale == 'ru':
        assert 'ЗАЯВЛЕНИЕ' in shown and 'а)' in shown
    with pdf(result) as document:
        assert all(char['fontname'].split('+')[-1].startswith('NotoSerif') for page_ in document.pages
                   for char in page_.chars)


# ---------------------------------------------------------------- paragraph and line


def test_paragraph_draws_one_paragraph_per_line_with_the_first_line_indented(tmp_path):
    result = draw(tmp_path, [{'block': 'paragraph', 'part': 'request', 'params': {'indent_first_mm': 12.5}}],
                  sections=[section('request', 'Birinchi xatboshi.\nIkkinchi xatboshi.')])
    first, second = word(result, 'Birinchi'), word(result, 'Ikkinchi')
    left, _ = frame()
    assert abs(first['x0'] - (left + 12.5 * page.MM)) < 1 and abs(second['x0'] - first['x0']) < 1
    assert second['top'] > first['top']


def test_paragraph_label_run_in_label_style_and_gap(tmp_path):
    result = draw(tmp_path, [
        {'block': 'paragraph', 'part': 'request', 'params': {'label': 'reason', 'indent_first_mm': 0,
                                                             'gap_pt': 12, 'style': 'italic'}},
        {'block': 'paragraph', 'part': 'statements', 'params': {'run_in_label': True}}],
        sections=[section('request', 'Birinchi.\nIkkinchi.'),
                  section('statements', items=[{'label': '', 'text': '1. Muhim. Qolgan matn.'}], layout='list')])
    assert 'Bold' in word(result, 'Sababi')['fontname'] and 'Italic' in word(result, 'Birinchi')['fontname']
    first, second = word(result, 'Birinchi'), word(result, 'Ikkinchi')
    assert second['top'] - first['top'] > 18 + 10
    # A list part drawn as paragraphs: the typed number is dropped, the run-in sentence is bold.
    assert 'Bold' in word(result, 'Muhim')['fontname'] and 'Bold' not in word(result, 'Qolgan')['fontname']
    assert '1.' not in text(result)


def test_paragraph_of_an_empty_part_draws_nothing():
    ctx = context(flow=[{'block': 'paragraph', 'part': 'request'}], sections=[section('request', '  ')])
    assert made(ctx)[0][1] == []


def test_paragraph_justified(tmp_path):
    body = ' '.join(['Hujayra tirik organizmning eng kichik tuzilish birligidir.'] * 6)
    result = draw(tmp_path, [{'block': 'paragraph', 'part': 'request', 'params': {'align': 'justify',
                                                                                  'indent_first_mm': 0}}],
                  sections=[section('request', body)])
    left, width = frame()
    lines = {}
    for item in words(result):
        lines.setdefault(round(item['top']), []).append(item)
    full = [max(item['x1'] for item in row) for row in list(lines.values())[:-1]]
    assert full and all(abs(edge - (left + width)) < 1.5 for edge in full)


def test_line_joins_label_sentences_and_drops_one_whose_slot_is_empty(tmp_path):
    result = draw(tmp_path, [{'block': 'line', 'fields': ['time_min'], 'params': {
        'label': 'instruction', 'sentences': ['one_answer', 'time', 'time_none'], 'drop_empty_slots': True}}])
    shown = text(result)
    assert 'Ko‘rsatma: Har bir savolda bitta to‘g‘ri javob bor. Vaqt: 35 daqiqa.' in shown
    assert shown.count('Vaqt') == 1 and 'Bold' in word(result, 'Ko‘rsatma')['fontname']


def test_line_without_dropping_draws_a_blank_for_an_empty_slot(tmp_path):
    result = draw(tmp_path, [{'block': 'line', 'params': {'text': 'time_none'}}])
    with pdf(result) as document:
        assert 'Vaqt:' in document.pages[0].extract_text() and document.pages[0].chars
    assert '_' not in text(result)


def test_line_text_is_a_fact_or_a_part_and_aligns(tmp_path):
    result = draw(tmp_path, [{'block': 'line', 'params': {'text': 'org', 'align': 'right', 'style': 'caps'}},
                             {'block': 'line', 'params': {'text': 'greeting', 'align': 'centre'}},
                             {'block': 'line', 'params': {'text': 'request'}}],
                  sections=[section('request', 'Qisqa matn.')])
    left, width = frame()
    org = [item for item in words(result) if item['text'] == 'UNIVERSITETI'][0]
    assert abs(org['x1'] - (left + width)) < 1.5
    greeting = word(result, 'Hurmatli')
    assert greeting['x0'] > left + 40
    assert 'Qisqa matn.' in text(result)


def test_line_max_lines_steps_the_size_down_and_warns_when_it_cannot(tmp_path):
    body = ' '.join(['Bu juda uzun qator bo‘lib bir necha qatorga o‘tadi.'] * 4)
    result = draw(tmp_path, [{'block': 'line', 'part': 'request', 'params': {'max_lines': 2}}],
                  sections=[section('request', body)])
    assert word(result, 'juda')['size'] < 12
    result = draw(tmp_path, [{'block': 'line', 'part': 'request', 'params': {'max_lines': 1}}],
                  sections=[section('request', body)], name='over.pdf')
    assert 'line_over' in result['metadata']['warnings'] and 'necha' in text(result)


def test_line_balance_narrows_the_lines(tmp_path):
    body = ' '.join(['Muvozanatli qator sinovi uchun matn.'] * 3)
    flow = [{'block': 'line', 'part': 'request', 'params': {'balance': True}}]
    balanced = draw(tmp_path, flow, sections=[section('request', body)])
    plain = draw(tmp_path, [{'block': 'line', 'part': 'request'}], sections=[section('request', body)],
                 name='plain.pdf')
    widest = lambda result: max(item['x1'] for item in words(result))
    assert widest(balanced) < widest(plain) - 10


# ---------------------------------------------------------------- headings


@pytest.mark.parametrize('numbering, locale, expected', [
    ('decimal', 'uz', ['1. Vazifalar', '1.1 Vazifalar']), ('arabic', 'uz', ['1. Vazifalar', '1. Vazifalar']),
    ('roman', 'en', ['I. Tasks', 'I. Tasks']), ('chapter_word', 'uz', ['1-BOB. Vazifalar', '1-BOB. Vazifalar']),
    ('chapter_word', 'ru', ['ГЛАВА 1. Задачи', 'ГЛАВА 1. Задачи']),
    ('chapter_word', 'en', ['CHAPTER 1. Tasks', 'CHAPTER 1. Tasks']), ('none', 'uz', ['Vazifalar', 'Vazifalar'])])
def test_heading_numbering(tmp_path, numbering, locale, expected):
    result = draw(tmp_path, [{'block': 'heading', 'part': 'tasks', 'params': {'level': 1, 'numbering': numbering}},
                             {'block': 'heading', 'part': 'tasks', 'params': {'level': 2, 'numbering': numbering}}],
                  locale)
    lines = [line_ for line_ in text(result).split('\n') if line_.strip()]
    assert lines[:2] == expected


def test_heading_counters_restart_below_and_marks_feed_the_contents():
    flow = [{'block': 'heading', 'part': 'tasks', 'params': {'level': level, 'numbering': 'decimal'}}
            for level in (1, 2, 2, 1, 2, 3)]
    ctx = context(flow=flow)
    drawn = made(ctx)
    texts = [next(flowable for flowable in flowables if isinstance(flowable, Paragraph)).getPlainText()
             for _, flowables in drawn]
    assert [item.split()[0] for item in texts] == ['1.', '1.1', '1.2', '2.', '2.1', '2.1.1']
    # Levels 1 and 2 join the contents by default, level 3 does not.
    assert [mark[1].split()[0] for mark in ctx.marks] == ['1.', '1.1', '1.2', '2.', '2.1']


def test_heading_label_caps_rule_right_label_badge_and_fold(tmp_path):
    result = draw(tmp_path, [
        {'block': 'heading', 'part': 'tasks', 'params': {'level': 2, 'label': 'part_one', 'caps': True,
                                                         'rule': 'under', 'right_label': 'annex'}},
        {'block': 'heading', 'part': 'tasks', 'params': {'level': 3, 'numbering': 'arabic', 'style': 'badge'}},
        {'block': 'heading', 'part': 'tasks', 'params': {'level': 3, 'numbering': 'arabic',
                                                         'fold_number_below': 2}}])
    shown = text(result)
    assert 'I QISM. TO‘G‘RI JAVOBNI TANLANG' in shown and '1-ilova' in shown
    with pdf(result) as document:
        assert document.pages[0].lines
    left, width = frame()
    assert abs(word(result, '1-ilova')['x1'] - (left + width)) < 2
    # The folded heading: one instance of the group, below 2, so no number.
    assert shown.rstrip().split('\n')[-1].strip() == 'Vazifalar'


def test_heading_page_break_before_and_an_empty_heading(tmp_path):
    result = draw(tmp_path, [{'block': 'paragraph', 'part': 'request'},
                             {'block': 'heading', 'part': 'chapter', 'params': {'page_break_before': True}},
                             {'block': 'heading', 'part': 'request'}],
                  sections=[section('request', 'Matn.')])
    assert result['page_count'] == 2 and clean(result)
    ctx = context(flow=[{'block': 'heading', 'part': 'request'}])
    assert made(ctx)[0][1] == []


# ---------------------------------------------------------------- titles and heads


def test_doc_title_is_the_label_word_tracked_and_centred_with_subject_lines(tmp_path):
    result = draw(tmp_path, [{'block': 'doc_title', 'params': {'label': 'title', 'tracking_pt': 2,
                                                               'subject': ['org', 'name_blank']}}], 'ru')
    with pdf(result) as document:
        chars = [char for char in document.pages[0].chars if char['text'] in 'ЗАЯВЛЕНИЕ' and 'Bold' in
                 char['fontname']]
    assert ''.join(char['text'] for char in chars[:9]) == 'ЗАЯВЛЕНИЕ'
    # Letter spacing: each gap wider than the face's own.
    gaps = [after['x0'] - before['x1'] for before, after in zip(chars, chars[1:9])]
    assert min(gaps) > 1.5
    shown = text(result)
    assert 'Образцовый государственный университет' in shown and '_' not in shown


def test_doc_title_falls_back_to_the_papers_title_then_the_parts_heading(tmp_path):
    result = draw(tmp_path, [{'block': 'doc_title'}])
    assert 'Namuna hujjat' in text(result)
    result = draw(tmp_path, [{'block': 'doc_title', 'part': 'tasks', 'params': {'label': 'missing_word',
                                                                                'subject': 'chapter'}}],
                  name='part.pdf')
    shown = text(result)
    assert 'VAZIFALAR' in shown and 'Hujayra — tirik organizmning' in shown


def test_doc_head_draws_its_lines_in_order_between_two_rules(tmp_path):
    flow = [{'block': 'doc_head', 'params': {
        'overline': 'school', 'kind_line': 'subject_kind', 'kind_default': 'kind_test', 'term': 'topic',
        'org': 'org', 'title': ['subject', 'class_level'], 'subtitle': ['topic'],
        'formats': {'class_level': 'class_n'}, 'meta': ['date_given'], 'rules': 'both'}}]
    result = draw(tmp_path, flow)
    lines = [line_ for line_ in text(result).split('\n') if line_.strip()]
    assert lines[0] == 'NAMUNA TUMANIDAGI 99-SONLI MAKTAB' and lines[1] == 'TEST'
    assert 'Biologiya, 7-sinf' in lines and 'Sana: 14.11.2026' in lines[-1]
    assert lines.index('Biologiya, 7-sinf') > lines.index('Namuna davlat universiteti')
    with pdf(result) as document:
        assert len(document.pages[0].lines) == 2
    assert 'Bold' in word(result, 'Biologiya,')['fontname'] and word(result, 'Biologiya,')['size'] > 16


def test_doc_head_kind_from_a_fact_and_the_papers_title_when_no_title_fact(tmp_path):
    result = draw(tmp_path, [{'block': 'doc_head', 'params': {'kind_line': 'subject', 'title': ['time_none'],
                                                              'align': 'left'}}])
    lines = [line_ for line_ in text(result).split('\n') if line_.strip()]
    assert lines == ['BIOLOGIYA', 'Namuna hujjat']
    ctx = context(flow=[{'block': 'doc_head', 'params': {'title': ['time_none'], 'rules': 'both'}}])
    ctx.content['title'] = ''
    assert made(ctx)[0][1] == []


def test_date_line_given_clock_and_blank_patterns(tmp_path):
    flow = [{'block': 'date_line', 'params': {'fact': 'date_given', 'align': 'right'}},
            {'block': 'date_line', 'params': {'fact': 'date_clock', 'label': 'date'}},
            {'block': 'date_line', 'params': {'fact': 'date_blank', 'year': 'clock'}},
            {'block': 'date_line', 'params': {'fact': 'date_blank'}}]
    uz, ru, en = (text(draw(tmp_path, flow, locale, name=f'{locale}.pdf')) for locale in LOCALES)
    assert '14.11.2026' in uz and 'Sana 17.11.2026' in uz and '2026-yil' in uz and re.search(r'20\s+-yil', uz)
    assert 'Дата 17.11.2026' in ru and '2026 г.' in ru
    assert '14 November 2026' in en and 'Date 17 November 2026' in en
    left, width = frame()
    result = draw(tmp_path, flow[:1])
    assert abs(word(result, '14.11.2026')['x1'] - (left + width)) < 1.5


def test_date_line_template_pattern_with_the_clocks_year(tmp_path):
    result = draw(tmp_path, [{'block': 'date_line', 'params': {'fact': 'date_blank', 'pattern': 'pattern',
                                                               'year': 'clock'}}])
    assert '2026-yil' in text(result) and '_' not in text(result)


# ---------------------------------------------------------------- lists


@pytest.mark.parametrize('marker, locale, expected', [
    ('number', 'uz', ['1.', '2.', '3.']), ('paren_number', 'uz', ['1)', '2)', '3)']),
    ('letter', 'uz', ['a)', 'b)', 'c)']), ('letter', 'ru', ['а)', 'б)', 'в)']), ('dash', 'uz', ['–', '–', '–']),
    ('bullet', 'en', ['•', '•', '•'])])
def test_list_markers_and_typed_markers_dropped(tmp_path, marker, locale, expected):
    result = draw(tmp_path, [{'block': 'list', 'part': 'tasks', 'params': {'marker': marker}}], locale)
    lines = [line_.split()[0] for line_ in text(result).split('\n') if line_.strip()]
    assert lines == expected
    # The model's own "1." on the first item is not drawn twice.
    assert '1. 1.' not in text(result)


def test_list_body_lines_single_unnumbered_and_never_cut(tmp_path):
    result = draw(tmp_path, [{'block': 'list', 'part': 'request', 'params': {'marker': 'number',
                                                                             'single_unnumbered': True}}],
                  sections=[section('request', 'Yagona hujjat.')])
    assert text(result).strip() == 'Yagona hujjat.'
    items = [{'label': '', 'text': f'Hujjat {number}.'} for number in range(1, 9)]
    result = draw(tmp_path, [{'block': 'list', 'part': 'enclosures', 'params': {'marker': 'number',
                                                                                'max_items': 6}}],
                  sections=[section('enclosures', items=items, layout='list')], name='many.pdf')
    assert 'Hujjat 8.' in text(result) and 'list_over' in result['metadata']['warnings']


def test_list_with_a_label_hangs_its_items_and_takes_the_plural(tmp_path):
    flow = [{'block': 'list', 'part': 'enclosures', 'params': {'marker': 'number', 'label': 'enclosure'}}]
    result = draw(tmp_path, flow, 'en')
    shown = text(result)
    assert 'Enclosures: 1. Doctor’s certificate.' in shown
    label, first = word(result, 'Enclosures:'), word(result, 'Doctor’s')
    second = word(result, 'Copy')
    assert abs(first['x0'] - second['x0']) < 1 and first['x0'] > label['x1']
    one = [{'label': '', 'text': 'Doctor’s certificate.'}]
    result = draw(tmp_path, [{'block': 'list', 'part': 'enclosures', 'params': {
        'marker': 'number', 'label': 'enclosure', 'single_unnumbered': True}}], 'en',
        sections=[section('enclosures', items=one, layout='list')], name='one.pdf')
    assert text(result).strip() == 'Enclosure: Doctor’s certificate.'


def test_list_in_two_columns_and_in_the_gutter(tmp_path):
    result = draw(tmp_path, [{'block': 'list', 'part': 'tasks', 'params': {'marker': 'letter', 'columns': 2}}])
    left, width = frame()
    assert word(result, 'Xulosa')['x0'] > left + width / 2 - 1
    result = draw(tmp_path, [{'block': 'list', 'part': 'tasks', 'params': {'marker': 'number', 'gutter': True}}],
                  name='gutter.pdf')
    assert word(result, '1.')['x0'] < left and abs(word(result, 'Mavzu')['x0'] - left) < 1


# ---------------------------------------------------------------- tables


def test_table_headers_come_from_the_catalogue_and_rows_are_padded_or_merged(tmp_path):
    items = [{'label': 'Sayt', 'text': '1 | dona', 'value': '12 000 000'}, {'label': 'Xosting', 'text': '',
                                                                            'value': '600 000'},
             {'label': 'Dizayn'}]
    result = draw(tmp_path, [{'block': 'table', 'part': 'prices'}],
                  sections=[{'id': 'prices', 'heading': 'Model wrote this', 'body': '', 'layout': 'table',
                             'columns': ['Draft', 'header'], 'items': items}])
    lines = [line_ for line_ in text(result).split('\n') if line_.strip()]
    assert lines[0] == 'Xizmat Miqdori Narxi, so‘m'
    assert 'Sayt 1; dona 12 000 000' in lines and 'Xosting 600 000' in lines and 'Dizayn' in lines
    assert 'Draft' not in text(result) and 'Model wrote this' not in text(result)


def test_table_template_columns_widths_alignment_grid_zebra_and_blank_rows(tmp_path):
    flow = [{'block': 'table', 'part': 'prices', 'params': {
        'columns': [{'label': 'service', 'width_mm': 'flex'}, {'label': 'quantity', 'width_mm': 22,
                                                               'align': 'centre'},
                    {'label': 'price', 'width_mm': 35, 'type': 'money'}],
        'rules': 'grid', 'zebra': True, 'blank_rows': 2, 'heading': True}}]
    result = draw(tmp_path, flow)
    left, width = frame()
    row = word(result, 'Veb-sayt')['top']
    edge = max(item['x1'] for item in words(result) if abs(item['top'] - row) < 1)
    assert abs(edge - (left + width - 1.7 * page.MM)) < 1.5
    shown = text(result)
    assert shown.split('\n')[0].strip() == 'Narxlar' and 'Miqdori' in shown
    with pdf(result) as document:
        tinted = [rect for rect in document.pages[0].rects if rect.get('fill')
                  and tuple(rect.get('non_stroking_color') or ()) not in ((), (1,), (1, 1, 1), (0,), (0, 0, 0))]
    assert tinted


def test_table_model_answers_are_numbered_after_the_closed_questions(tmp_path):
    flow = [{'block': 'table', 'part': 'prices', 'params': {
        'from': 'questions:open', 'columns': [{'label': 'no', 'width_mm': 11}, {'label': 'model_answer',
                                                                                'width_mm': 'flex'},
                                              {'label': 'score', 'width_mm': 17}]}}]
    result = draw(tmp_path, flow)
    lines = [line_ for line_ in text(result).split('\n') if line_.strip()]
    assert lines[0] == '№ Namunaviy javob Ball'
    assert lines[1] == '2 Xloroplastlarda. Yorug‘lik ta’sirida — 2 ball. 2'


def test_table_captions_count_and_notes_and_the_body_are_kept(tmp_path):
    flow = [{'block': 'table', 'part': 'prices', 'params': {'caption': True, 'note': 'vat_note'}},
            {'block': 'table', 'part': 'prices', 'params': {'caption': True}}]
    prices = core._sample_sections('ru')[-3]
    prices = dict(prices, body='Сроки согласуются отдельно.')
    result = draw(tmp_path, flow, 'ru', sections=[prices])
    shown = text(result)
    assert 'Таблица 1. Цены' in shown and 'Таблица 2. Цены' in shown
    assert 'Цены указаны с НДС.' in shown and shown.count('Сроки согласуются отдельно.') == 2


def test_table_drops_empty_columns_marks_a_total_row_and_repeats_its_header(tmp_path):
    items = [{'label': f'Xizmat {number}', 'text': ' | ', 'value': '100'} for number in range(1, 60)]
    items.append({'label': 'Jami', 'text': '', 'value': '5 900', 'total': True})
    result = draw(tmp_path, [{'block': 'table', 'part': 'prices', 'params': {'drop_empty_columns': True}}],
                  sections=[section('prices', items=items, layout='table')])
    assert clean(result) and result['page_count'] >= 2
    with pdf(result) as document:
        texts = [(page_.extract_text() or '') for page_ in document.pages]
    assert all(page_text.startswith('Xizmat Narxi, so‘m') for page_text in texts)
    assert 'Miqdori' not in texts[0]
    last = words(result, result['page_count'] - 1)
    assert 'Bold' in next(item for item in last if item['text'] == 'Jami')['fontname']


def test_a_table_without_rows_draws_nothing():
    ctx = context(flow=[{'block': 'table', 'part': 'prices'}], sections=[section('prices', layout='table')])
    assert made(ctx)[0][1] == []


def test_kv_table_rows_from_facts_and_a_part(tmp_path):
    result = draw(tmp_path, [
        {'block': 'kv_table', 'fields': ['org', 'person', 'name_blank', 'time_none'], 'params': {
            'labels': {'org': 'cap_org'}}},
        {'block': 'kv_table', 'part': 'roster', 'params': {'rows': 'roster', 'rules': 'box'}}])
    shown = text(result)
    assert '(tashkilot nomi) Namuna davlat universiteti' in shown
    # The field's label loses its bot note; a missing omit field is no row; a blank field is a ruled row.
    assert 'F.I.Sh. Toshmatova' in shown and 'ixtiyoriy' not in shown and 'Vaqt' not in shown
    assert 'Rais B. A. Karimov' in shown
    with pdf(result) as document:
        assert document.pages[0].lines or document.pages[0].rects


# ---------------------------------------------------------------- set-off passages and blanks


@pytest.mark.parametrize('style', ['tint', 'box', 'bar'])
def test_callout_styles(tmp_path, style):
    result = draw(tmp_path, [{'block': 'callout', 'part': 'passage', 'params': {'style': style}}])
    assert clean(result) and 'Fotosintez' in text(result)
    assert 'Bold' in word(result, 'Fotosintez')['fontname']
    with pdf(result) as document:
        first = document.pages[0]
        if style == 'bar':
            assert any(abs(line_['x0'] - line_['x1']) < 0.1 for line_ in first.lines)
        else:
            assert first.rects or len(first.lines) >= 4


def test_callout_label_source_and_a_passage_longer_than_a_page(tmp_path):
    result = draw(tmp_path, [{'block': 'callout', 'params': {'source': 'request', 'label': 'passage'}}],
                  sections=[section('request', '\n'.join(['Uzun matnning bir xatboshisi, bir necha so‘z bilan.'
                                                          ] * 70))])
    assert clean(result) and result['page_count'] >= 2 and text(result).startswith('Matn')


def test_a_callouts_heading_goes_over_a_page_foot_with_its_first_line(tmp_path):
    # N2a made a named callout's first two rows one piece for the notes' "Key points"; every family draws callouts
    # (a proposal's terms, a marketing plan's note), so here it is held in the official measures of this sample.
    # Each filler length moves the box one line further down page 1, across the foot.
    terms = '\n'.join(['Yetkazib berish muddati va to‘lov tartibi shu bandda.'] * 6)
    for lines in range(32, 44):
        result = draw(tmp_path, [{'block': 'paragraph', 'part': 'request'},
                                 {'block': 'callout', 'part': 'passage', 'params': {'style': 'bar'}}],
                      sections=[section('request', '\n'.join(['Oddiy xatboshi, sahifani to‘ldiradi.'] * lines)),
                                section('passage', terms, heading='Taklif shartlari')], pages=2)
        with pdf(result) as document:
            pages = [page_.extract_text() or '' for page_ in document.pages]
        holding = [text_ for text_ in pages if 'Taklif shartlari' in text_]
        assert clean(result) and holding and all('Yetkazib berish' in text_ for text_ in holding), lines


def test_inline_blank_draws_rules_never_underscores(tmp_path):
    result = draw(tmp_path, [{'block': 'inline_blank', 'params': {'label': 'blank_line'}},
                             {'block': 'inline_blank', 'params': {'width': 'full'}},
                             {'block': 'inline_blank', 'params': {'width': 'day'}}])
    assert clean(result) and '_' not in text(result) and 'kun ta’til' in text(result)
    with pdf(result) as document:
        assert document.pages[0].lines or document.pages[0].rects


def test_ruled_blank_styles(tmp_path):
    result = draw(tmp_path, [{'block': 'ruled_blank', 'fields': ['reason'], 'params': {'label': 'reason',
                                                                                       'lines': 3}}])
    with pdf(result) as document:
        assert len(document.pages[0].lines) == 3
    assert 'Sababi:' in text(result)
    result = draw(tmp_path, [{'block': 'ruled_blank', 'params': {'label': 'tel', 'caption': 'cap_name',
                                                                 'style': 'captioned', 'width_mm': 80}}],
                  name='captioned.pdf')
    with pdf(result) as document:
        lines = document.pages[0].lines
    left, _ = frame()
    assert len(lines) == 1 and lines[0]['x1'] <= left + 80 * page.MM + 1
    assert '(F.I.Sh.)' in text(result)
    for style in ('box', 'dashed_box'):
        result = draw(tmp_path, [{'block': 'ruled_blank', 'params': {'label': 'drawing', 'lines': 4,
                                                                     'style': style}}], name=f'{style}.pdf')
        with pdf(result) as document:
            assert document.pages[0].rects or len(document.pages[0].lines) >= 4


def test_ruled_blank_prints_a_given_value_and_splits_many_lines_across_pages(tmp_path):
    result = draw(tmp_path, [{'block': 'ruled_blank', 'fields': ['org'], 'params': {'label': 'reason'}}])
    assert text(result).strip() == 'Sababi: Namuna davlat universiteti'
    result = draw(tmp_path, [{'block': 'paragraph', 'part': 'request'},
                             {'block': 'ruled_blank', 'params': {'lines': 40}}],
                  sections=[section('request', '\n'.join(['Matn qatori.'] * 20))], name='many.pdf')
    assert clean(result) and result['page_count'] == 2
    with pdf(result) as document:
        assert sum(len(page_.lines) for page_ in document.pages) == 40


# ---------------------------------------------------------------- signatures, parties, approval


def test_signature_row_types_the_date_and_the_name_on_their_rules(tmp_path):
    result = draw(tmp_path, [{'block': 'signature_row', 'fields': ['date_given', 'signer'],
                              'params': {'variant': 'date_sign_name'}}])
    with pdf(result) as document:
        rules = sorted(document.pages[0].lines, key=lambda line_: line_['x0'])
    assert len(rules) == 3 and len({round(line_['top']) for line_ in rules}) == 1
    date, name, caption = word(result, '14.11.2026'), word(result, 'Toshmatova'), word(result, 'Imzo')
    assert date['bottom'] <= rules[0]['top'] + 0.5 and caption['top'] >= rules[1]['top']
    assert rules[2]['x0'] <= name['x0'] <= rules[2]['x1'] and 'Italic' in caption['fontname']


def test_signature_row_blank_and_its_built_in_captions(tmp_path):
    result = draw(tmp_path, [{'block': 'signature_row', 'fields': ['date_blank', 'name_blank']}], 'ru',
                  labels={'date': None, 'sign': None, 'name': None})
    lines = [line_ for line_ in text(result).split('\n') if line_.strip()]
    assert lines == ['Дата Подпись Ф.И.О.']


def test_signature_row_post_label_and_grid_variants(tmp_path):
    result = draw(tmp_path, [
        {'block': 'signature_row', 'fields': ['post', 'signer', 'post_two', 'signer_two'],
         'params': {'variant': 'post_sign_name'}},
        {'block': 'signature_row', 'fields': ['signer'], 'params': {'variant': 'label_sign_name',
                                                                    'label': 'done_by'}},
        {'block': 'signature_row', 'part': 'members', 'params': {'variant': 'grid', 'signers': 'members',
                                                                 'max_rows': 2}}])
    shown = text(result)
    for value in ('Kafedra mudiri', 'Bosh hisobchi', 'D. K. Yusupova', 'Bajardi:', 'B. A. Karimov, Rais',
                  'G‘. O‘. Rahimov, A’zo', 'Lavozimi'):
        assert value in shown, value
    assert 'signature_row_over' in result['metadata']['warnings']


def test_signature_row_shrinks_or_wraps_a_long_name(tmp_path):
    result = draw(tmp_path, [{'block': 'signature_row', 'fields': ['date_blank', 'signer']}],
                  facts={'signer': 'Abdurahmonova-Qodirova Gulnora Abdumalik qizi'})
    assert clean(result) and 'Gulnora' in text(result)


def test_party_block_stands_in_the_right_half_with_blanks_captions_prefix_and_ending(tmp_path):
    flow = [{'block': 'party_block', 'fields': ['org', 'head'], 'params': {'anchor': 'right_half'}},
            {'block': 'party_block', 'fields': ['org_blank', 'name_blank', 'phone_blank', 'time_none'], 'params': {
                'anchor': 'right_half', 'gap_pt': 12, 'captions': {'org_blank': 'cap_org',
                                                                   'name_blank': 'cap_name'},
                'labels': {'phone_blank': 'tel'}, 'suffixes': {'name_blank': 'ga'}}}]
    result = draw(tmp_path, flow)
    left, width = frame()
    for item in words(result):
        assert item['x0'] >= left + width / 2 - 1, item['text']
    shown = text(result)
    assert '(tashkilot nomi)' in shown and '(F.I.Sh.)' in shown and 'Tel.:' in shown and 'ga' in shown
    with pdf(result) as document:
        assert len(document.pages[0].lines) == 3


def test_party_block_groups_and_a_bold_large_first_line(tmp_path):
    result = draw(tmp_path, [{'block': 'party_block', 'params': {
        'groups': [['org'], ['person', 'phone']], 'name_style': 'bold_large', 'labels': {'phone': 'tel'}}}])
    org, person, phone = word(result, 'Namuna'), word(result, 'Toshmatova'), word(result, '+998')
    assert 'Bold' in org['fontname'] and org['size'] > 12 and 'Bold' in person['fontname']
    assert person['top'] - org['bottom'] > 12 and 'Tel.:' in text(result)
    ctx = context(flow=[{'block': 'party_block', 'fields': ['time_none']}])
    assert made(ctx)[0][1] == []


def test_approval_block_right_left_pair_order_lines_and_dates(tmp_path):
    result = draw(tmp_path, [{'block': 'approval_block', 'fields': ['post', 'org'],
                              'params': {'word': 'approve', 'name': 'signer'}}])
    left, width = frame()
    assert word(result, 'TASDIQLAYMAN')['x0'] > left + width * 0.5 - 1
    shown = text(result)
    assert 'Kafedra mudiri' in shown and 'N. A. Toshmatova' in shown and '-yil' in shown
    result = draw(tmp_path, [{'block': 'approval_block', 'fields': ['post'], 'params': {
        'word': 'agree', 'side': 'left', 'year': 'clock', 'order_lines': ['head']}}], name='left.pdf')
    assert word(result, 'KELISHILDI')['x0'] < left + 1 and '2026-yil' in text(result)
    assert text(result).index('rektori') < text(result).index('KELISHILDI')
    result = draw(tmp_path, [{'block': 'approval_block', 'params': {'side': 'pair', 'groups': [
        {'word': 'agree', 'rows': ['post_two'], 'name': 'signer_two', 'date': False},
        {'word': 'approve', 'rows': ['post'], 'name': 'signer', 'date': 'date_given'}]}}], 'en', name='pair.pdf')
    agreed, approved = word(result, 'AGREED'), word(result, 'APPROVED')
    assert abs(agreed['top'] - approved['top']) < 1 and approved['x0'] > left + width / 2
    assert '14 November 2026' in text(result)


# ---------------------------------------------------------------- fallbacks and safety


@pytest.mark.parametrize('name', ['doc_title', 'ruled_blank', 'signature_row', 'date_line', 'party_block',
                                  'approval_block'])
def test_a_core_blocks_plain_fallback_draws_what_it_holds(name):
    item = next(sample_ for sample_ in core.SAMPLES if sample_['block'] == name)
    entry, template, content = core.sample_paper('uz', samples=[item])
    left, bottom, width, height = page.geometry(template)
    ctx = Ctx(content=content, entry=entry, template=template, locale='uz', step=0, pages=1, width=width,
              frame_height=height, day=DAY)
    place = places(ctx)[0]
    drawn = registry.draw(ctx, place, plain_only=True)
    assert f'block_fallback:{name}' in ctx.warnings
    assert any(isinstance(flowable, Paragraph) and flowable.getPlainText().strip() for flowable in drawn)


def test_a_block_that_raises_is_drawn_by_its_fallback(tmp_path, monkeypatch):
    def broken(ctx, place):
        raise ValueError('content the block cannot draw')
    monkeypatch.setitem(registry.BLOCKS, 'signature_row', registry.Block('signature_row', broken,
                                                                         core._signature_plain))
    result = ariza(tmp_path, ariza_content(**FULL))
    assert 'block_fallback:signature_row' in result['metadata']['warnings']
    assert 'D. R. Karimova' in text(result)


def test_customer_text_is_text_never_markup(tmp_path):
    result = draw(tmp_path, [{'block': 'paragraph', 'part': 'request'},
                             {'block': 'party_block', 'fields': ['org']},
                             {'block': 'table', 'part': 'prices'}],
                  facts={'org': 'A & B <b>MChJ</b>'},
                  sections=[section('request', 'Narx < 5 & > 2 <i>emas</i>'),
                            section('prices', items=[{'label': '<br/>', 'text': 'x & y', 'value': '1'}],
                                    layout='table')])
    shown = text(result)
    assert clean(result)
    assert 'Narx < 5 & > 2 <i>emas</i>' in shown and 'A & B <b>MChJ</b>' in shown and '<br/>' in shown


def test_a_gap_never_starts_a_page(tmp_path):
    gap = core.Gap(1, 30)
    assert gap.wrap(100, 10) == (1, 10) and gap.wrap(100, -5) == (1, 0) and gap.wrap(100, 50) == (1, 30)
    # A paper that ends exactly at a page's foot, then a block with a gap under it, is still the same pages.
    lines = '\n'.join(['Sahifani to‘ldiruvchi qator.'] * 40)
    without = draw(tmp_path, [{'block': 'paragraph', 'part': 'request', 'params': {'after_pt': 0}}],
                   sections=[section('request', lines)])
    with_gap = draw(tmp_path, [{'block': 'paragraph', 'part': 'request', 'params': {'after_pt': 120}}],
                    sections=[section('request', lines)], name='gap.pdf')
    assert with_gap['page_count'] == without['page_count'] == 1
