"""The paper checker and sample tool (apps/studio/paper/check.py, sample.py) and the family helper.

The real blocks are R1's and the families'; these tests register small
stand-in blocks, as test_paper_engine does, and write their samples to a
temporary folder. People and organisations are invented.
"""
import copy
import datetime
import json
import types

import pytest
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import Paragraph, Spacer

from apps.studio.categories import catalogue
from apps.studio.cv import fonts
from apps.studio.paper import check, page, registry, sample
from apps.studio.paper.registry import Block
from tests import paper_family

W, H = A4
DAY = datetime.date(2026, 9, 15)


# ---------------------------------------------------------------- stand-in blocks and samples


def _lines(ctx, place):
    section = place.section or {}
    texts = [line for line in str(section.get('body') or '').split('\n') if line.strip()]
    texts += [str(item.get('text') or item.get('label') or '') for item in section.get('items') or []]
    return [Paragraph(ctx.text(text), ctx.styles['body']) for text in texts if text.strip()]


def _list(ctx, place):
    return [Paragraph(ctx.text(ctx.label(place.params['label'])), ctx.styles['bold']), *_lines(ctx, place)]


def _facts(ctx, place):
    lines = []
    for field_id in place.fields:
        value = ctx.fact(field_id)
        if value is None and not ctx.blank(field_id):
            continue
        lines.append(Paragraph(ctx.text(value if value is not None else ctx.blank_run(field_id)), ctx.styles['body']))
    return lines


def _word(ctx, place):
    return [Spacer(1, 12), Paragraph(ctx.text(ctx.label(place.params['label'])), ctx.styles['caps']), Spacer(1, 12)]


STAND_INS = {'paragraph': _lines, 'list': _list, 'party_block': _facts, 'signature_row': _facts,
             'doc_title': _word, 'ruled_blank': _word}


@pytest.fixture
def blocks(monkeypatch):
    for name, function in STAND_INS.items():
        monkeypatch.setitem(registry.BLOCKS, name, Block(name, function))

    def register(name, function):
        monkeypatch.setitem(registry.BLOCKS, name, Block(name, function))
    return register


FACTS = {
    'uz': {'addressee_org': 'Namuna davlat universiteti', 'addressee_position': 'rektori B. A. Sobirovga',
           'applicant_name': 'Qodirova Malika Anvar qizidan', 'applicant_role': 'Tarix fakulteti 3-kurs talabasi',
           'date_written': '12.11.2026', 'signer_name': 'M. A. Qodirova'},
    'ru': {'addressee_org': 'Образцовый государственный университет', 'addressee_position': 'ректору Б. А. Собирову',
           'applicant_name': 'от Кодировой Малики Анваровны', 'applicant_role': 'студентки 3 курса',
           'date_written': '12.11.2026', 'signer_name': 'М. А. Кодирова'},
    'en': {'addressee_org': 'Sample State University', 'addressee_position': 'To the Rector, Mr B. A. Sobirov',
           'applicant_name': 'From Malika A. Qodirova', 'applicant_role': 'Third-year student, Faculty of History',
           'date_written': '12 November 2026', 'signer_name': 'M. A. Qodirova'},
}
REQUEST = {
    'uz': 'Oilaviy sharoitim tufayli 2026-yil 16-noyabrdan 20-noyabrgacha darslarga qatnasha olmayman. Shu kunlarda '
          'darsdan ozod qilishingizni so‘rayman.',
    'ru': 'По семейным обстоятельствам я не смогу посещать занятия с 16 по 20 ноября 2026 года. Прошу освободить '
          'меня от занятий в эти дни.',
    'en': 'For family reasons I cannot attend classes from 16 to 20 November 2026. I ask to be excused from classes '
          'on those days.',
}
ENCLOSURE = {'uz': 'Ma’lumotnoma nusxasi.', 'ru': 'Копия справки.', 'en': 'A copy of the certificate.'}


def _content(locale):
    return {'title': '', 'facts': FACTS[locale], 'sections': [
        {'id': 'request', 'heading': '', 'layout': 'text', 'items': [], 'body': REQUEST[locale]},
        {'id': 'enclosures', 'heading': '', 'layout': 'list', 'body': '',
         'items': [{'label': '', 'text': ENCLOSURE[locale]}]}]}


def write_sample(root, case='full', template='official_ariza', **more):
    folder = root / template
    folder.mkdir(parents=True, exist_ok=True)
    body = {'template': template, 'case': case, 'pages': 1, **{locale: _content(locale) for locale in FACTS}, **more}
    (folder / f'{case}.json').write_text(json.dumps(body, ensure_ascii=False), encoding='utf-8')
    return root


@pytest.fixture
def samples(tmp_path):
    return write_sample(tmp_path / 'samples')


# ---------------------------------------------------------------- hand-drawn PDFs


MM = 72 / 25.4
# The ariza's frame: margins of 30, 15, 20 and 20 mm.
FRAME = page.box(30 * MM, 20 * MM, W - 15 * MM, H - 20 * MM)


def drawn_pdf(path, pages, font='CVSerif'):
    """A PDF whose pages hold the (x, y, text) strings given, in `font`, at 11 pt; y from the top."""
    fonts.register()
    sheet = pdf_canvas.Canvas(str(path), pagesize=A4, invariant=1)
    for strings in pages:
        sheet.setFont(font, 11)
        for x, y, text in strings:
            sheet.drawString(x, H - y, text)
        sheet.showPage()
    sheet.save()
    return path


def expect(**more):
    return {'frames': {'first': [FRAME], 'later': [FRAME]}, 'furniture': {'first': [], 'later': []}, **more}


def test_a_clean_page_has_no_problems(tmp_path):
    path = drawn_pdf(tmp_path / 'clean.pdf', [[(100, 100, 'Namuna davlat universiteti'), (100, 130, 'ARIZA')]])
    assert check.problems(path, expect(facts=['Namuna davlat universiteti'], labels=['Ariza'], locale='uz')) == []


def test_text_outside_the_page_or_frame_is_found(tmp_path):
    path = drawn_pdf(tmp_path / 'outside.pdf', [[(100, 100, 'Ichida'), (20, 300, 'Hoshiyada'),
                                                 (560, 400, 'Sahifadan tashqarida')]])
    found = check.problems(path, expect())
    assert any('outside the page' in problem for problem in found)
    assert any('outside the frame' in problem and 'Hoshiyada'[:9] in problem for problem in found)
    # Furniture may print outside the frame where the template puts it: a top band on later pages.
    numbered = drawn_pdf(tmp_path / 'numbered.pdf', [[(100, 100, 'Birinchi')], [(290, 30, '2'), (100, 100, 'Ikki')]])
    band = page.box(FRAME[0], H - 20 * MM, FRAME[2], H)
    assert check.problems(numbered, expect(furniture={'first': [], 'later': [band]}, stub_min=0)) == []
    assert any('outside the frame' in problem for problem in check.problems(numbered, expect(stub_min=0)))


def test_overlapping_words_and_foreign_fonts_are_found(tmp_path):
    path = drawn_pdf(tmp_path / 'overlap.pdf', [[(100, 100, 'Imzo'), (103, 101, 'Sana')]])
    assert any('overlap' in problem for problem in check.problems(path, expect()))
    helvetica = drawn_pdf(tmp_path / 'helvetica.pdf', [[(100, 100, 'Imzo')]], font='Helvetica')
    assert any('not bundled: Helvetica' in problem for problem in check.problems(helvetica, expect()))


def test_a_missing_fact_or_label_is_found_whatever_the_case_and_apostrophes(tmp_path):
    path = drawn_pdf(tmp_path / 'facts.pdf', [[(100, 100, 'O‘ZBEKISTON TARIX MUZEYI'), (100, 130, 'Ilova:')]])
    found = check.problems(path, expect(facts=["O'zbekiston tarix muzeyi", 'Karimov Jasur'], labels=['ilova:', 'Imzo']))
    assert found == ['the fact "Karimov Jasur" is missing', 'the label "Imzo" is missing']


def test_cyrillic_is_found_in_uzbek_and_english_papers_only(tmp_path):
    path = drawn_pdf(tmp_path / 'cyrillic.pdf', [[(100, 100, 'Ariza Заявление')]])
    for locale in ('uz', 'en'):
        found = check.problems(path, expect(locale=locale))
        assert any('Cyrillic letters in an ' + locale in problem for problem in found)
    assert check.problems(path, expect(locale='ru')) == []


def test_a_stub_last_page_is_found_unless_it_may_stand_alone(tmp_path):
    full = [(100, 70 + 14 * line, f'Qator {line}') for line in range(40)]
    path = drawn_pdf(tmp_path / 'stub.pdf', [full, [(100, 70, 'Oxirgi qator')]])
    assert any('the last page is' in problem for problem in check.problems(path, expect()))
    assert check.problems(path, expect(stub_min=0)) == []
    # A one-page paper is never a stub, however short.
    assert check.problems(drawn_pdf(tmp_path / 'one.pdf', [[(100, 70, 'Qisqa')]]), expect()) == []


@pytest.mark.parametrize(('rule', 'quoted', 'pages', 'longer', 'wrong'), [
    ('fixed', 1, 1, False, False),
    ('fixed', 1, 2, False, True),
    ('fixed', 1, 2, True, False),
    ('fixed', 1, 3, True, True),
    ('flow', 2, 3, False, False),
    ('flow', 2, 4, False, True),
    ('flow', 2, 6, True, False),
    ('count', 3, 3, False, False),
    ('count', 3, 4, False, True),
    ('count', 3, 4, True, False),
    ('count', 35, 37, True, True),
])
def test_the_page_count_is_held_to_the_rule(rule, quoted, pages, longer, wrong):
    found = check._pages_problem(pages, {'rule': rule, 'quoted': quoted, 'longer': longer,
                                         'rule_pages': 1 if rule == 'fixed' else None})
    assert bool(found) is wrong


def test_the_engines_codes_for_a_paper_not_drawn_as_its_template_are_problems(tmp_path):
    path = drawn_pdf(tmp_path / 'codes.pdf', [[(100, 100, 'Ariza')]])
    found = check.problems(path, expect(warnings=['template_fallback', 'block_fallback:list', 'longer_than_quoted',
                                                  'glyphs_dropped']))
    assert found == ['the engine says template_fallback', 'the engine says block_fallback:list',
                     'the engine says glyphs_dropped']


# ---------------------------------------------------------------- what a paper is expected to hold


def test_expect_holds_the_printed_facts_of_placements_that_hold_and_their_labels(blocks, tmp_path):
    entry = catalogue.get('pdf.xat.ariza')
    raw = copy.deepcopy(catalogue.template('official_ariza'))
    raw['labels']['dated'] = {'uz': 'Yozilgan: {date_written}', 'ru': 'Написано: {date_written}',
                              'en': 'Written: {date_written}'}
    raw['labels']['dialled'] = {'uz': 'Tel.: {phone}', 'ru': 'Тел.: {phone}', 'en': 'Tel.: {phone}'}
    raw['flow'] += [{'block': 'line', 'params': {'label': 'dated'}}, {'block': 'line', 'params': {'label': 'dialled'}}]
    content = sample.content_of(json.loads((write_sample(tmp_path / 's') / 'official_ariza' / 'full.json')
                                           .read_text(encoding='utf-8')), 'uz')
    artifact = {'page_count': 1, 'metadata': {'frames': {'first': [FRAME]}, 'warnings': ['longer_than_quoted']}}
    found = check.expect_for(artifact, content, entry=entry, template=raw, locale='uz', pages=1, day=DAY)
    assert set(found['facts']) == set(FACTS['uz'].values())
    # The title, the enclosure word (its part holds) and a label whose slot is filled; never one with an empty slot,
    # nor the reason, whose placement holds only when its blank is drawn.
    assert found['labels'] == ['ARIZA', 'Ilova:', 'Yozilgan: 12.11.2026']
    assert found['rule'] == 'fixed' and found['rule_pages'] == 1 and found['longer'] and found['locale'] == 'uz'
    assert found['stub_min'] == check.STUB_MIN


def test_expect_leaves_out_codes_and_lets_a_part_that_starts_a_page_stand_alone(blocks):
    entry = catalogue.get('pdf.test')
    content = {'title': 'Test', 'questions': [], 'sections': [
        {'id': 'facts', 'heading': '', 'body': '', 'layout': 'list', 'items': [
            {'label': 'subject', 'text': 'Biologiya'}, {'label': 'use', 'text': 'self_study'},
            {'label': 'answer_extras', 'text': 'answer_sheet'}, {'label': 'time_min', 'text': '40'}]}]}
    artifact = {'page_count': 2, 'metadata': {}}
    found = check.expect_for(artifact, content, entry=entry, template=catalogue.template('study_test'), locale='uz',
                             pages=2, day=DAY)
    assert 'Biologiya' in found['facts'] and 'self_study' not in found['facts']
    assert 'answer_sheet' not in found['facts']
    # The answer key starts its own page, so a short last page is the key and not a stub.
    assert found['stub_min'] == 0
    assert found['frames'] is None


# ---------------------------------------------------------------- samples


def test_a_missing_case_is_made_from_the_full_sample_and_an_own_file_wins(samples):
    full = sample.load('official_ariza', 'full', samples)
    blank = sample.load('official_ariza', 'blank', samples)
    long = sample.load('official_ariza', 'long', samples)
    assert blank['derived'] == 'full' and blank['case'] == 'blank'
    assert 'facts' not in blank['uz'] and not check_facts(sample.content_of(blank, 'uz'))
    assert check_facts(sample.content_of(full, 'uz')) == FACTS['uz']
    request = next(section for section in sample.content_of(long, 'ru')['sections'] if section['id'] == 'request')
    assert len(request['body']) >= sample.LONG_CHARS and request['body'].count(REQUEST['ru']) >= sample.LONG_TEXT
    write_sample(samples, 'blank')
    assert 'derived' not in sample.load('official_ariza', 'blank', samples)
    assert sample.load('study_test', 'full', samples) == {}
    with pytest.raises(ValueError):
        sample.load('official_ariza', 'short', samples)
    write_sample(samples, 'long', template='official_ariza')
    (samples / 'official_ariza' / 'long.json').write_text(json.dumps({'template': 'study_test'}), encoding='utf-8')
    with pytest.raises(ValueError):
        sample.load('official_ariza', 'long', samples)


def check_facts(content):
    facts = next((section for section in content['sections'] if section['id'] == 'facts'), None)
    return {item['label']: item['text'] for item in (facts or {}).get('items') or []}


@paper_family.each(['official_ariza'])
def test_the_family_helper_draws_and_reads_every_case_and_language(template_id, locale, case, blocks, samples,
                                                                   tmp_path):
    drawn = paper_family.assert_reads_well(template_id, locale, case, tmp_path, root=samples)
    assert drawn.artifact['metadata']['template'] == 'official_ariza'
    if case == 'long':
        assert drawn.artifact['page_count'] == 2 and drawn.expect['longer']
    else:
        assert drawn.artifact['page_count'] == 1
    if case == 'full':
        assert set(drawn.expect['facts']) == set(FACTS[locale].values())


def test_the_family_helper_fails_a_paper_that_loses_a_fact(blocks, samples, tmp_path):
    def forgetful(ctx, place):
        return _facts(ctx, place)[:-1]
    blocks('signature_row', forgetful)
    found = paper_family.problems('official_ariza', 'en', 'full', tmp_path, root=samples)
    assert found == ['the fact "M. A. Qodirova" is missing']
    assert paper_family.problems('official_ariza', 'en', 'full', tmp_path, root=samples,
                                 allow=('the fact',)) == []
    with pytest.raises(AssertionError, match='M. A. Qodirova'):
        paper_family.assert_reads_well('official_ariza', 'en', 'full', tmp_path, root=samples)


def test_a_template_without_its_blocks_fails_as_the_emergency_fallback(monkeypatch, samples, tmp_path):
    for name in list(registry.BLOCKS):
        monkeypatch.delitem(registry.BLOCKS, name)
    found = paper_family.problems('official_ariza', 'uz', 'full', tmp_path, root=samples)
    assert 'the engine says template_fallback' in found


def test_the_helper_names_templates_without_samples(samples):
    paper_family.assert_has_samples(['official_ariza'], root=samples)
    with pytest.raises(AssertionError, match='study_test: no full sample'):
        paper_family.assert_has_samples(['official_ariza', 'study_test'], root=samples)
    assert [param.id for param in paper_family.matrix(['study_test'], cases=('full',))] == [
        'study_test-uz-full', 'study_test-ru-full', 'study_test-en-full']


# ---------------------------------------------------------------- sheets and the command


def test_the_sheet_draws_a_row_per_case_and_language(blocks, samples, tmp_path):
    out = sample.sheet(tmp_path / 'sheet.png', templates=['official_ariza'], root=samples, width=120,
                       cases=['full', 'long'], locales=['uz'])
    with Image.open(out) as image:
        height = round(120 * 841.89 / 595.27)
        # Two rows; the long paper's two pages make the sheet two pages wide.
        assert image.height > 2 * height and image.width > 2 * 120
    # Without a template: every template with samples, in Uzbek and the full case.
    with Image.open(sample.sheet(tmp_path / 'all.png', root=samples, width=100)) as image:
        assert image.height < 2 * round(100 * 841.89 / 595.27)


def test_the_block_sheet_draws_each_sample_alone(blocks, tmp_path):
    module = types.SimpleNamespace(SAMPLES=[
        {'block': 'signature_row', 'name': 'name only', 'template': 'official_ariza', 'fields': ['signer_name'],
         'facts': {'signer_name': {'uz': 'D. R. Usmonova', 'ru': 'Д. Р. Усмонова', 'en': 'D. R. Usmonova'}}},
        {'block': 'paragraph',
         'section': {'id': 'note', 'body': {'uz': 'Namuna matni.', 'ru': 'Пример.', 'en': 'Text.'}}},
        {'block': 'doc_title', 'params': {'label': 'own'},
         'labels': {'own': {'uz': 'MA’LUMOTNOMA', 'ru': 'СПРАВКА', 'en': 'CERTIFICATE'}}}])
    path, warnings = sample.draw_block(module.SAMPLES[0], 'ru', tmp_path)
    assert 'Д. Р. Усмонова' in page_text(path) and warnings == []
    path, _ = sample.draw_block(module.SAMPLES[1], 'ru', tmp_path, 1)
    assert page_text(path).strip() == 'Пример.'
    path, _ = sample.draw_block(module.SAMPLES[2], 'uz', tmp_path, 2)
    assert 'MA’LUMOTNOMA' in page_text(path)
    out = sample.blocks_sheet(tmp_path / 'blocks.png', modules=[('stand_ins', module), ('broken', ImportError())])
    with Image.open(out) as image:
        assert image.width == 16 + 2 * (760 + 16)
    assert len(sample.block_samples(types.SimpleNamespace(SAMPLES=lambda: {'list': [{}, {'name': 'b'}]}))) == 2
    with pytest.raises(ValueError):
        sample.blocks_sheet(tmp_path / 'none.png', modules=[])


def page_text(path):
    import pdfplumber
    with pdfplumber.open(str(path)) as document:
        return '\n'.join(page_.extract_text() or '' for page_ in document.pages)


def test_the_command_checks_a_template_and_writes_its_pages(blocks, samples, tmp_path, capsys):
    assert sample.main(['--check', 'official_ariza', '--samples', str(samples), '--locale', 'uz', '--case', 'full',
                        '--pages', str(tmp_path / 'pages')]) == 0
    said = capsys.readouterr().out
    assert 'ok   official_ariza · full · uz · 1p of 1 · s0' in said
    assert (tmp_path / 'pages' / 'official_ariza-full-uz-p1.png').is_file()
    blocks('list', _lines)
    assert sample.main(['--check', 'official_ariza', '--samples', str(samples), '--locale', 'en,ru',
                        '--case', 'blank']) == 1
    said = capsys.readouterr().out
    assert said.count('FAIL') == 2 and 'the label "Enclosure:" is missing' in said
    with pytest.raises(SystemExit):
        sample.main(['--check', 'study_test', '--samples', str(samples)])
    with pytest.raises(SystemExit):
        sample.main(['--check', 'official_ariza', '--case', 'short'])
