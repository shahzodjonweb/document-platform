"""Regulations and minutes (package R5b): the `clauses` block and the three templates it draws with the core blocks.

A staff instruction (business_yoriqnoma), a job description
(official_lavozim_yoriqnomasi) and meeting minutes (official_bayonnoma) are
drawn through the engine and read back with pdfplumber, so each is held to
what the page shows. People and organisations are invented.
"""
import copy
import datetime
import tempfile
from pathlib import Path

import pdfplumber
import pytest

from apps.studio import paper
from apps.studio.categories import catalogue
from apps.studio.paper import page, registry, sample
from apps.studio.paper.blocks import core, regulations
from apps.studio.paper.ctx import Ctx, Place
from tests import paper_family

DAY = datetime.date(2026, 11, 17)
TEMPLATES = ('business_yoriqnoma', 'official_lavozim_yoriqnomasi', 'official_bayonnoma')
ENTRIES = {'business_yoriqnoma': 'pdf.biz.yoriqnoma', 'official_lavozim_yoriqnomasi': 'pdf.biz.lavozim_yoriqnomasi',
           'official_bayonnoma': 'pdf.biz.bayonnoma'}


# ---------------------------------------------------------------- helpers


def content(template_id, locale='uz', *, facts=None, drop=(), sections=(), title=None):
    """The template's full sample in `locale`, with facts changed (None takes one out), parts dropped or replaced."""
    made = sample.content_of(sample.load(template_id, 'full'), locale)
    found = made['sections'][0]
    for key, value in (facts or {}).items():
        found['items'] = [item for item in found['items'] if item['label'] != key]
        if value is not None:
            found['items'].append({'label': key, 'text': value, 'value': ''})
    replaced = {item['id'] for item in sections}
    made['sections'] = [item for item in made['sections'] if item['id'] not in set(drop) | replaced] + list(sections)
    if title is not None:
        made['title'] = title
    return made


def section(part_id, rows=(), body='', heading=''):
    return {'id': part_id, 'heading': heading, 'body': body, 'layout': 'list' if rows else 'text',
            'items': [{'label': row[0], 'text': row[1], 'value': ''} if isinstance(row, tuple)
                      else {'label': '', 'text': row, 'value': ''} for row in rows]}


def draw(tmp_path, template_id, made, locale='uz', *, pages=None, cues=(), name='paper.pdf'):
    entry = catalogue.get(ENTRIES[template_id])
    return paper.render_paper(copy.deepcopy(made), tmp_path / name, locale, entry=entry, template=template_id,
                              pages=pages or entry.length['default'], cues=frozenset(cues), day=DAY)


def text(result):
    with pdfplumber.open(result['path']) as document:
        return '\n'.join(page_.extract_text() or '' for page_ in document.pages).replace('\xa0', ' ')


def chars(result):
    with pdfplumber.open(result['path']) as document:
        return [char for page_ in document.pages for char in page_.chars]


def clean(result):
    warnings = result['metadata']['warnings']
    return not result['metadata'].get('template_fallback') and not any(code.startswith('block_fallback')
                                                                       for code in warnings)


def ctx_for(template_id, made, locale='uz', cues=()):
    entry = catalogue.get(ENTRIES[template_id])
    template = catalogue.template(template_id)
    left, bottom, width, height = page.geometry(template)
    return Ctx(content=made, entry=entry, template=template, locale=locale, step=0, pages=entry.length['default'],
               width=width, frame_height=height, cues=frozenset(cues), day=DAY)


# ---------------------------------------------------------------- registration and the family check


def test_clauses_is_registered_here_and_the_three_papers_are_drawn_by_the_engine():
    assert registry.BLOCKS['clauses'].draw.__module__ == regulations.__name__
    assert registry.BLOCKS['clauses'].fallback is regulations._clauses_plain
    for template_id, entry_id in ENTRIES.items():
        assert list(catalogue.get(entry_id).templates) == [template_id]
        assert paper.ready({'options': {'category': entry_id, 'length': 2}, 'output_locale': 'uz', 'prompt': 'x'})
        problems = [str(problem) for problem in catalogue.check(entry_id)]
        assert not any('not yet registered' in problem for problem in problems), (entry_id, problems)


def test_every_template_has_its_samples():
    paper_family.assert_has_samples(TEMPLATES)


@paper_family.each(TEMPLATES)
def test_every_template_reads_well(template_id, locale, case, tmp_path):
    drawn = paper_family.assert_reads_well(template_id, locale, case, tmp_path)
    if case != 'long':
        # Ceiling papers: the full and blank samples hold their quote, drawn at the loosest step.
        assert drawn.artifact['page_count'] <= drawn.pages and drawn.artifact['metadata']['fit_step'] == 0


def test_the_block_sheet_samples_draw_without_a_fallback():
    with tempfile.TemporaryDirectory() as folder:
        for index, item in enumerate(sample.block_samples(regulations)):
            for locale in ('uz', 'ru', 'en'):
                path, warnings = sample.draw_block(item, locale, folder, index)
                assert path.is_file() and not [code for code in warnings if code.startswith('block_fallback')], \
                    (item['name'], locale, warnings)


# ---------------------------------------------------------------- reading the clauses


def test_clauses_are_read_from_lead_ins_actions_single_clauses_and_body_lines():
    found = regulations.clauses_of(section('duties', [
        ('Xodim quyidagilarni bajaradi:', 'hisobot tuzadi | jurnal yuritadi'),
        '2.3. Xodim yig‘ilishlarda qatnashadi.',
        'Xodim: | birinchi | ikkinchi',
        '1.5 mln so‘m ajratilsin.',
    ]))
    assert found == [('Xodim quyidagilarni bajaradi:', ['hisobot tuzadi', 'jurnal yuritadi']),
                     ('Xodim yig‘ilishlarda qatnashadi.', []), ('Xodim:', ['birinchi', 'ikkinchi']),
                     ('1.5 mln so‘m ajratilsin.', [])]
    body = section('duties', body='1. Ombor tozalanadi:\n– polni yuvadi\n- javonlarni artadi\n2) Kalit topshiriladi.')
    assert regulations.clauses_of(body) == [('Ombor tozalanadi:', ['polni yuvadi', 'javonlarni artadi']),
                                            ('Kalit topshiriladi.', [])]
    assert regulations.clauses_of(None) == [] and regulations.clauses_of(section('duties')) == []


def test_a_clause_opened_with_a_dash_loses_it_and_an_abbreviation_keeps_its_stop():
    found = regulations.clauses_of(section('duties', [('- ish uchun javob beradi:', '– hujjatlarni | idishlar va h.k.'),
                                                      '• Kalit topshiriladi.']))
    assert found == [('ish uchun javob beradi:', ['hujjatlarni', 'idishlar va h.k.']), ('Kalit topshiriladi.', [])]
    assert regulations._punctuated(['моет посуду и т.д.', 'убирает зал.', 'сдаёт кассу, т.д.']) == [
        'моет посуду и т.д.;', 'убирает зал;', 'сдаёт кассу, т.д.']


def test_a_caution_clause_taller_than_a_page_is_drawn_unboxed_and_keeps_its_numbers(tmp_path):
    long = 'Diqqat! ' + ' '.join(['Ofitsiant issiq idishni ikki qo‘llab, sochiq bilan ushlab olib boradi.'] * 90)
    made = content('business_yoriqnoma', sections=[section('during_work', [long, 'Xodim ishni tartib bilan bajaradi.'])])
    result = draw(tmp_path, 'business_yoriqnoma', made)
    assert not any(code.startswith('block_fallback') for code in result['metadata']['warnings'])
    shown = text(result)
    assert '3.1. Diqqat!' in shown and '3.2. Xodim ishni tartib bilan bajaradi.' in shown


def test_chapters_are_numbered_as_drawn_and_an_empty_one_leaves_no_heading(tmp_path):
    made = content('official_lavozim_yoriqnomasi', drop=('qualification',))
    shown = text(draw(tmp_path, 'official_lavozim_yoriqnomasi', made))
    assert 'Malaka talablari' not in shown
    # Duties are the second chapter drawn, so their clauses are 2.1, 2.2 under "II.".
    assert 'II. Lavozim vazifalari' in shown and '2.1. O‘qituvchi quyidagi vazifalarni' in shown
    assert 'IV. Javobgarlik' in shown and '4.2.' in shown and '5.1.' not in shown


def test_official_actions_hang_behind_a_dash_and_are_punctuated(tmp_path):
    shown = text(draw(tmp_path, 'official_lavozim_yoriqnomasi', content('official_lavozim_yoriqnomasi')))
    assert '– dars rejalarini tuzadi;' in shown and '– ota-onalar bilan muntazam aloqa qiladi.' in shown
    assert '1.1. Mazkur lavozim yo‘riqnomasi' in shown


def test_a_typed_number_is_dropped_and_the_renderers_number_is_drawn(tmp_path):
    made = content('official_lavozim_yoriqnomasi', sections=[section('rights', ['7.4. O‘qituvchi takliflar kiritadi.'])])
    shown = text(draw(tmp_path, 'official_lavozim_yoriqnomasi', made))
    assert '4.1. O‘qituvchi takliflar kiritadi.' in shown and '7.4.' not in shown


def test_business_lead_ins_are_bold_and_a_caution_clause_is_boxed(tmp_path):
    result = draw(tmp_path, 'business_yoriqnoma', content('business_yoriqnoma'))
    assert clean(result)
    found = chars(result)
    lead = ''.join(char['text'] for char in found if 'Bold' in char['fontname'])
    assert 'Buyurtmaolishda' in lead.replace(' ', '') and 'Diqqat!' in lead
    # The plain action under it is not bold.
    assert 'buyurtmanianiqyozib' not in lead.replace(' ', '')
    with pdfplumber.open(result['path']) as document:
        tinted = [rect for page_ in document.pages for rect in page_.rects if rect.get('fill')
                  and rect.get('non_stroking_color') not in (None, (1,), [1], (1, 1, 1), [1, 1, 1])]
    assert tinted, 'the caution clause has its tinted box'


def test_no_caution_box_or_word_is_added_to_a_clause_that_did_not_ask_for_one(tmp_path):
    made = content('business_yoriqnoma', sections=[section('during_work', ['Xodim ishni tartib bilan bajaradi.'])])
    shown = text(draw(tmp_path, 'business_yoriqnoma', made))
    assert 'Diqqat' not in shown and '3.1. Xodim ishni tartib bilan bajaradi.' in shown


# ---------------------------------------------------------------- the staff instruction's kinds


def test_a_safety_instruction_titles_its_chapters_by_the_safety_rules(tmp_path):
    result = draw(tmp_path, 'business_yoriqnoma', content('business_yoriqnoma'), cues={'safety'})
    shown = text(result)
    assert '1. Umumiy xavfsizlik talablari' in shown and '3. Ish jarayonidagi xavfsizlik talablari' in shown
    assert 'Umumiy qoidalar' not in shown


def test_rules_of_conduct_draw_their_own_chapters_kind_word_and_acknowledgement(tmp_path):
    made = content('business_yoriqnoma', 'ru', drop=('before_work', 'during_work', 'emergency', 'after_work'),
                   sections=[section('rules_chapter', ['Рабочий день начинается в 9:00.'], heading='Рабочее время'),
                             section('rules_chapter_2', ['Курение в зале запрещается.'], heading='Поведение'),
                             section('final', ['Каждый работник знакомится с правилами под подпись.'])])
    result = draw(tmp_path, 'business_yoriqnoma', made, 'ru', cues={'rules'})
    shown = text(result)
    assert clean(result)
    assert 'П Р А В И Л А' in shown or 'ПРАВИЛА' in shown.replace(' ', '')
    assert '2. Рабочее время' in shown and '2.1. Рабочий день начинается в 9:00.' in shown
    assert '3. Поведение' in shown and '4. Заключительные положения' in shown
    assert 'С правилами ознакомлен(а):' in shown and 'С инструкцией' not in shown
    # The phone row belongs to the work and safety kinds only.
    assert 'Телефоны' not in shown


def test_no_approval_block_when_the_customer_says_so_and_a_false_flag_keeps_it(tmp_path):
    off = text(draw(tmp_path, 'official_lavozim_yoriqnomasi',
                    content('official_lavozim_yoriqnomasi', facts={'approval_mode': 'true'}), name='off.pdf'))
    kept = text(draw(tmp_path, 'official_lavozim_yoriqnomasi',
                     content('official_lavozim_yoriqnomasi', facts={'approval_mode': 'false'}), name='on.pdf'))
    assert 'T A S D I Q L A Y M A N' not in off and 'TASDIQLAYMAN' not in off.replace(' ', '')
    assert 'TASDIQLAYMAN' in kept.replace(' ', '')
    business = text(draw(tmp_path, 'business_yoriqnoma', content('business_yoriqnoma',
                                                                  facts={'approval_mode': 'true'}), name='b.pdf'))
    assert 'Tasdiqladi:' not in business and 'Yo‘riqnoma bilan tanishdim:' in business


def test_a_missing_organisation_is_a_captioned_rule_on_the_business_head(tmp_path):
    shown = text(draw(tmp_path, 'business_yoriqnoma', content('business_yoriqnoma', facts={'organisation': None})))
    assert '(tashkilot nomi)' in shown and 'YULDUZ' not in shown.replace(' ', '')


# ---------------------------------------------------------------- signers


def test_agreeing_posts_are_one_row_each_split_into_post_and_name(tmp_path):
    made = content('official_lavozim_yoriqnomasi', facts={
        'agreement_signers': 'Yurist: D. A. Umarova\nKasaba uyushmasi raisi\nBosh hisobchi — Rahimov B. S.'})
    result = draw(tmp_path, 'official_lavozim_yoriqnomasi', made)
    with pdfplumber.open(result['path']) as document:
        lines = [line['text'].replace('\xa0', ' ') for page_ in document.pages for line in page_.extract_text_lines()]
    assert any(line.startswith('Yurist') and line.endswith('D. A. Umarova') for line in lines)
    assert any(line.startswith('Bosh hisobchi') and line.endswith('Rahimov B. S.') for line in lines)
    assert any(line.strip() == 'Kasaba uyushmasi raisi' for line in lines)


def lines_of(result):
    with pdfplumber.open(result['path']) as document:
        return [line['text'].replace('\xa0', ' ') for page_ in document.pages for line in page_.extract_text_lines()]


def test_agreeing_signers_joined_by_semicolons_are_one_row_each(tmp_path):
    made = content('official_lavozim_yoriqnomasi', facts={
        'agreement_signers': 'Yurist: D. A. Umarova; Bosh hisobchi — Rahimov B. S.'})
    lines = lines_of(draw(tmp_path, 'official_lavozim_yoriqnomasi', made))
    assert any(line.startswith('Yurist') and line.endswith('D. A. Umarova') for line in lines)
    assert any(line.startswith('Bosh hisobchi') and line.endswith('Rahimov B. S.') for line in lines)
    assert not any('Umarova;' in line for line in lines)


@pytest.mark.parametrize(('line', 'expected'), [
    ('ombor mudiri A. K. Sodiqov', ('ombor mudiri', 'A. K. Sodiqov', True)),
    ('Direktor — B. S. Toshmatov', ('Direktor', 'B. S. Toshmatov', True)),
    ('R. A. Aliyev — direktor', ('direktor', 'R. A. Aliyev', True)),
    ('Bosh hisobchi Rahimov B. S.', ('Bosh hisobchi', 'Rahimov B. S.', True)),
    ('mehnat muhofazasi bo‘yicha mutaxassis', ('mehnat muhofazasi bo‘yicha mutaxassis', '', False)),
    ('Г. О. Юлдошева', ('', 'Г. О. Юлдошева', True)),
    # Uzbek digraph and o‘ initials are one letter each, and the stop after a final one stays.
    ('Sh. R. Karimova', ('', 'Sh. R. Karimova', True)),
    ('Ch. T. Ergashev', ('', 'Ch. T. Ergashev', True)),
    ('Yo‘ldosheva G. O‘.', ('', 'Yo‘ldosheva G. O‘.', True)),
    ('Karimova Sh.', ('', 'Karimova Sh.', True)),
    ('Sh. R. Karimova — direktor', ('direktor', 'Sh. R. Karimova', True)),
    ('huquqshunos.', ('huquqshunos', '', False)),
    # A full name without initials is a name beside a post, and two capitalised sides are only a guess.
    ('Rustamova Zarina — direktor', ('direktor', 'Rustamova Zarina', True)),
    ('Иванов Иван Иванович — директор', ('директор', 'Иванов Иван Иванович', True)),
    ('Chief Accountant — John Smith', ('Chief Accountant', 'John Smith', False)),
    # A one-word surname beside a capitalised English post: the full-name side is no name, so only a guess.
    ('Sales Manager — Smith', ('Sales Manager', 'Smith', False)),
    # o‘ and g‘ initials as typed: an ASCII apostrophe, a backtick or the Uzbek letter ʻ, never only the house ‘.
    ("G'. A. Karimov", ('', "G'. A. Karimov", True)),
    ("Yo'ldosheva G. O'.", ('', "Yo'ldosheva G. O'.", True)),
    ('Xolmatov M. Gʻ.', ('', 'Xolmatov M. Gʻ.', True)),
    ('direktor — Oʻ. T. Karimov', ('direktor', 'Oʻ. T. Karimov', True)),
    ('zal menejeri Ergasheva D. G`.', ('zal menejeri', 'Ergasheva D. G`.', True)),
    ("O'quv ishlari bo'yicha direktor o'rinbosari Xolmatov M. G'.",
     ("O'quv ishlari bo'yicha direktor o'rinbosari", "Xolmatov M. G'.", True)),
    # The catalogue's own comma form: a name with initials, then the post.
    ('B. S. Toshmatov, direktor', ('direktor', 'B. S. Toshmatov', True)),
    ('Б. С. Тошматов, директор', ('директор', 'Б. С. Тошматов', True)),
    ('Toshmatov B. S., direktor', ('direktor', 'Toshmatov B. S.', True)),
    # A bare full name is a name, only unsure: a caller keeps it in the name cell.
    ('Karimova Nilufar', ('', 'Karimova Nilufar', False)),
    ("O'. Karimov", ('', "O'. Karimov", True)),
])
def test_a_signers_line_is_split_into_post_and_name(line, expected):
    assert core._post_and_name(line) == expected


def test_an_o_or_g_initial_typed_with_any_apostrophe_is_drawn_with_the_house_mark():
    from apps.studio.paper.text import NBSP, Rules
    rules = Rules('CVSerif', 'uz')
    assert rules.plain("G'. O`. Yo'ldosheva") == f'G‘.{NBSP}O‘.{NBSP}Yo‘ldosheva'
    assert rules.plain('Xolmatov M. Gʻ.') == f'Xolmatov M.{NBSP}G‘.'
    # Only an initial: a word ending in a mark before a stop, and other languages, keep what was typed.
    assert rules.plain("Oleg'.") == "Oleg'." and Rules('CVSerif', 'en').plain("G'. Smith") == "G'. Smith"


@pytest.mark.parametrize(('locale', 'chair', 'word', 'name'), [
    ('uz', 'Sh. R. Karimova — direktor', 'Rais', 'Sh. R. Karimova'),
    ('uz', 'Rustamova Zarina — direktor', 'Rais', 'Rustamova Zarina'),
    ('ru', 'Иванов Иван Иванович — директор', 'Председатель', 'Иванов Иван Иванович'),
    # Neither side is surely a name: the line is typed whole, never the post alone in the name cell.
    ('en', 'Head Teacher — Grace Hill', 'Chair', 'Head Teacher — Grace Hill'),
    ('en', 'Sales Manager — Smith', 'Chair', 'Sales Manager — Smith'),
    # An initial typed with an ASCII apostrophe keeps its surname, and the page draws the house o‘.
    ('uz', "G'. A. Karimov — direktor", 'Rais', 'G‘. A. Karimov'),
    ('ru', 'Б. С. Тошматов, директор', 'Председатель', 'Б. С. Тошматов'),
], ids=['uz-digraph-initials', 'uz-full-name', 'ru-full-name', 'en-guess-kept-whole', 'en-one-word-surname',
        'uz-ascii-initial', 'ru-comma-form'])
def test_the_chair_signs_by_name_and_never_by_post(tmp_path, locale, chair, word, name):
    lines = lines_of(draw(tmp_path, 'official_bayonnoma', content('official_bayonnoma', locale,
                                                                   facts={'chair': chair}), locale))
    signed = [line for line in lines if line.startswith(word) and ':' not in line]
    assert signed and signed[-1].endswith(name), signed


def test_the_secretary_with_ascii_initials_keeps_the_surname_and_every_initial(tmp_path):
    made = content('official_bayonnoma', facts={'secretary': "Yo'ldosheva G. O'."})
    lines = lines_of(draw(tmp_path, 'official_bayonnoma', made))
    signed = [line for line in lines if line.startswith('Kotib') and ':' not in line]
    assert signed and signed[-1].endswith('Yo‘ldosheva G. O‘.'), signed


def test_the_instructions_author_with_ascii_initials_is_split_whole(tmp_path):
    made = content('business_yoriqnoma', facts={'author': "zal menejeri Ergasheva D. G'."})
    lines = lines_of(draw(tmp_path, 'business_yoriqnoma', made))
    assert any(line.startswith('zal menejeri') and line.endswith('Ergasheva D. G‘.') for line in lines), lines
    made = content('business_yoriqnoma', facts={'author': 'D. G. Ergasheva, zal menejeri'})
    lines = lines_of(draw(tmp_path, 'business_yoriqnoma', made, name='comma.pdf'))
    assert any(line.startswith('zal menejeri') and line.endswith('D. G. Ergasheva') for line in lines), lines


def test_agreeing_signers_typed_with_ascii_apostrophes_a_comma_or_a_bare_name(tmp_path):
    made = content('official_lavozim_yoriqnomasi', facts={
        'agreement_signers': "Bosh hisobchi — Yo'ldosheva G. O'.\nD. A. Umarova, yurist\nKarimova Nilufar"})
    lines = lines_of(draw(tmp_path, 'official_lavozim_yoriqnomasi', made))
    assert any(line.startswith('Bosh hisobchi') and line.endswith('Yo‘ldosheva G. O‘.') for line in lines), lines
    assert any(line.startswith('yurist') and line.endswith('D. A. Umarova') for line in lines), lines
    # The bare name stands where a name goes, never as a post with an empty name rule beside it.
    assert any(line.strip() == 'Karimova Nilufar' for line in lines)
    ctx = ctx_for('official_lavozim_yoriqnomasi', made)
    place = Place('signature_row', None, None, ('agreement_signers',), {'variant': 'post_sign_name'})
    assert ('', 'Karimova Nilufar') in core._signers(ctx, place)


def test_an_english_capitalised_post_alone_stays_a_post():
    made = content('official_lavozim_yoriqnomasi', 'en', facts={'agreement_signers': 'Chief Accountant'})
    ctx = ctx_for('official_lavozim_yoriqnomasi', made, 'en')
    place = Place('signature_row', None, None, ('agreement_signers',), {'variant': 'post_sign_name'})
    assert core._signers(ctx, place) == [('Chief Accountant', '')]


def test_the_minutes_sign_by_name_while_the_roster_keeps_the_role(tmp_path):
    result = draw(tmp_path, 'official_bayonnoma', content('official_bayonnoma'))
    with pdfplumber.open(result['path']) as document:
        lines = [line['text'].replace('\xa0', ' ') for page_ in document.pages for line in page_.extract_text_lines()]
    assert 'Rais: Z. A. Rustamova — direktor' in lines
    assert any(line.startswith('Rais') and line.endswith('Z. A. Rustamova') for line in lines)


@pytest.mark.parametrize(('word', 'title'), [(None, 'BAYONNOMA'), ('bayonnoma', 'BAYONNOMA'), ('bayon', 'BAYON'),
                                             ('bayoni', 'BAYONI')])
def test_the_minutes_title_takes_the_customers_word_and_only_one_title_is_drawn(tmp_path, word, title):
    shown = text(draw(tmp_path, 'official_bayonnoma', content('official_bayonnoma', facts={'title_word': word})))
    titles = [line for line in shown.split('\n') if line.replace(' ', '').startswith(('BAYON', 'B A Y O N'))]
    assert len(titles) == 1 and titles[0].replace(' ', '').startswith(title + '№'), titles


# ---------------------------------------------------------------- the minutes, drawn per agenda item


def test_each_item_follows_its_agenda_line_with_its_report_decisions_and_vote(tmp_path):
    result = draw(tmp_path, 'official_bayonnoma', content('official_bayonnoma'))
    assert clean(result)
    shown = text(result)
    order = ['KUN TARTIBI:', '1. Birinchi chorak natijalari haqida', 'ESHITILDI:', 'SO‘ZGA CHIQDILAR:',
             'QAROR QILINDI:', '2. Sust o‘zlashtirayotgan', 'Ovoz berish natijalari: yoqlab — 25',
             '2. Ota-onalar yig‘ilishini o‘tkazish to‘g‘risida', '1. Ota-onalar yig‘ilishi 28-noyabr',
             '3. Qishki ta’til rejasi haqida', '1. Qishki ta’til rejasi tasdiqlansin.', 'Ilova:', 'M.O‘.']
    # Searched in turn, each after the one before: the agenda lines come first, the items' headings after them.
    at = shown.find('3. Qishki ta’til rejasi haqida')
    for piece in order[1:]:
        at = shown.find(piece, at + 1)
        assert at != -1, piece


def test_russian_minutes_number_their_decisions_by_item(tmp_path):
    shown = text(draw(tmp_path, 'official_bayonnoma', content('official_bayonnoma', 'ru'), 'ru'))
    assert '1.1. Принять итоги первой четверти' in shown and '2.1. Провести родительское собрание' in shown
    assert '3.1. Утвердить план зимних каникул.' in shown


def test_a_decisions_tail_is_italic_in_the_same_paragraph(tmp_path):
    found = chars(draw(tmp_path, 'official_bayonnoma', content('official_bayonnoma')))
    italic = ''.join(char['text'] for char in found if 'Italic' in char['fontname'])
    assert '(mas’ul:M.B.Xolmatov;muddat:1-dekabr).' in italic.replace(' ', '').replace('\xa0', '')
    assert 'tashkiletilsin' not in italic.replace(' ', '')


def test_one_item_has_no_item_heading_and_a_decision_not_given_is_two_blanks(tmp_path):
    made = content('official_bayonnoma', 'en', sections=[section('agenda', ['Results of the first term'])],
                   drop=[f'{part}_{number}' for part in ('item_report', 'item_speakers', 'item_decisions', 'item_vote')
                         for number in (2, 3)] + ['item_decisions'])
    result = draw(tmp_path, 'official_bayonnoma', made, 'en', pages=1)
    shown = text(result)
    assert clean(result) and result['page_count'] <= 2
    assert shown.count('Results of the first term') == 1 and '1. Results' not in shown
    resolved = shown.split('RESOLVED:')[1]
    assert resolved.lstrip().startswith('1.') and '2.' in resolved.split('Vote:')[0]
    with pdfplumber.open(result['path']) as document:
        rules = [line for page_ in document.pages for line in page_.lines if line['x1'] - line['x0'] > 300]
    assert len(rules) >= 2


def test_decisions_given_are_never_padded_with_blanks(tmp_path):
    shown = text(draw(tmp_path, 'official_bayonnoma', content('official_bayonnoma')))
    decisions = shown.split('QAROR QILINDI:')[2].split('Ovoz berish')[0]
    assert decisions.strip() == '1. Ota-onalar yig‘ilishi 28-noyabr kuni soat 17:00 da o‘tkazilsin.'


def test_eight_items_each_draw_their_heading_from_the_agenda(tmp_path):
    agenda = [f'{number}-masala haqida' for number in range(1, 9)]
    parts = [section('agenda', agenda)]
    for number in range(1, 9):
        suffix = '' if number == 1 else f'_{number}'
        parts.append(section(f'item_report{suffix}', body=f'Kotib {number}-masala bo‘yicha ma’lumot berdi.'))
        parts.append(section(f'item_decisions{suffix}', [f'{number}-masala qabul qilinsin.']))
    made = content('official_bayonnoma', drop=[item['id'] for item in content('official_bayonnoma')['sections']
                                               if item['id'] != 'facts'], sections=parts)
    result = draw(tmp_path, 'official_bayonnoma', made, pages=3)
    shown = text(result)
    assert clean(result) and result['page_count'] <= 4
    at = shown.find('8. 8-masala haqida')
    for number in range(1, 9):
        at = shown.find(f'{number}. {number}-masala haqida', at + 1)
        assert at != -1 and shown.find(f'{number}-masala qabul qilinsin.', at) > at, (number, shown[:600])


def test_the_item_heading_reads_the_agenda_line_of_its_instance():
    made = content('official_bayonnoma')
    ctx = ctx_for('official_bayonnoma', made)
    part = ctx.entry.part('item_report')
    params = {'source': 'agenda', 'pick': 'instance', 'style': 'bold', 'from_instances': 2}
    drawn = regulations.clauses(ctx, Place('clauses', ctx.section('item_report', 2), part, (), params, 2, 0,
                                           'items'))
    paragraphs = [flowable for flowable in drawn if hasattr(flowable, 'text')]
    assert len(paragraphs) == 1 and 'Ota-onalar yig‘ilishini' in paragraphs[0].text
    assert paragraphs[0].bulletText == '2.' and paragraphs[0].keepWithNext


# ---------------------------------------------------------------- the fallback and safety


def test_the_plain_fallback_draws_numbered_lines_and_actions():
    made = content('official_lavozim_yoriqnomasi')
    ctx = ctx_for('official_lavozim_yoriqnomasi', made)
    place = Place('clauses', ctx.section('duties'), ctx.entry.part('duties'), (), {})
    lines = [flowable.text for flowable in regulations._clauses_plain(ctx, place)]
    assert lines[0].startswith('1. O‘qituvchi quyidagi') and lines[1].startswith('– 1–4-sinflarda')


def test_a_clauses_block_that_raises_is_drawn_plain(tmp_path, monkeypatch):
    def broken(ctx, place):
        raise RuntimeError('a bad clause')
    monkeypatch.setitem(registry.BLOCKS, 'clauses', registry.Block('clauses', broken, regulations._clauses_plain))
    result = draw(tmp_path, 'official_lavozim_yoriqnomasi', content('official_lavozim_yoriqnomasi'))
    assert 'block_fallback:clauses' in result['metadata']['warnings']
    assert not result['metadata'].get('template_fallback') and 'dars rejalarini tuzadi' in text(result)


def test_customer_text_in_a_clause_is_text_never_markup(tmp_path):
    made = content('official_lavozim_yoriqnomasi', sections=[section('rights', ['<b>O‘qituvchi</b> & ota-onalar'])])
    result = draw(tmp_path, 'official_lavozim_yoriqnomasi', made)
    assert clean(result) and '<b>O‘qituvchi</b> & ota-onalar' in text(result)


def test_the_templates_draw_only_registered_blocks_and_their_labels_hold_in_every_language():
    for template_id in TEMPLATES:
        template = catalogue.template(template_id)
        assert not registry.missing(paper.flow_blocks(template)), template_id
        for key, words in template['labels'].items():
            assert set(words) == {'uz', 'ru', 'en'} and "'" not in words['uz'], (template_id, key)
        assert Path(sample.SAMPLES / template_id / 'full.json').is_file()
