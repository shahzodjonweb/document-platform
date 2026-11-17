"""The official and letter templates (package R4): split_row, the eight templates and what they print.

The ariza, the explanatory note, the character reference, the recommendation
(official form and English letter), the cover letter, the motivation letter
and its personal-statement head. Each template is drawn from its samples in
three languages and three cases and read back by the checker; then what the
mock-ups promise is read from the page: the English head names the person
first, Uzbek blanks carry their case ending, the Russian reference leads with
"на", signers given as "post | name" sign on their own rows, a verdict without
its target has its own words. People and organisations are invented.
"""
import datetime

import pdfplumber
import pytest
from reportlab.platypus import Paragraph, Table

from apps.studio import paper
from apps.studio.categories import catalogue
from apps.studio.paper import check, page, registry, sample
from apps.studio.paper.blocks import core, official
from apps.studio.paper.ctx import Ctx, Place, localised, places
from tests import paper_family

TEMPLATES = ('official_ariza', 'official_tushuntirish', 'official_tavsifnoma', 'tavsiya_rasmiy', 'letter_tavsiya',
             'letter_cover', 'letter_motivatsion', 'letter_statement')
ENTRIES = ('pdf.xat.ariza', 'pdf.xat.tushuntirish', 'pdf.xat.tavsifnoma', 'pdf.xat.tavsiya', 'pdf.xat.ishga_kirish',
           'pdf.xat.motivatsion')
DAY = datetime.date(2026, 9, 15)


# ---------------------------------------------------------------- helpers


def drawn(tmp_path, template_id, locale, *, case='full', facts=None, drop=(), sections=None, name='paper.pdf'):
    """A template's sample drawn, its facts changed (`facts` set or replace, `drop` take out); (artifact, text)."""
    given = sample.load(template_id, case)
    entry = catalogue.get(given.get('entry') or catalogue.template(template_id)['entries'][0])
    content = sample.content_of(given, locale)
    items = {item['label']: item['text'] for section in content['sections'] if section['id'] == 'facts'
             for item in section['items']}
    items.update(facts or {})
    for key in drop:
        items.pop(key, None)
    content['sections'] = [section for section in content['sections'] if section['id'] != 'facts']
    content['sections'].insert(0, {'id': 'facts', 'heading': '', 'body': '', 'layout': 'list',
                                   'items': [{'label': key, 'text': value} for key, value in items.items()]})
    for section in sections or ():
        content['sections'] = [item for item in content['sections'] if item['id'] != section['id']] + [section]
    artifact = paper.render_paper(content, tmp_path / name, locale, entry=entry, template=template_id,
                                  pages=int(given.get('pages') or 1), cues=frozenset(given.get('cues') or ()),
                                  day=DAY)
    with pdfplumber.open(artifact['path']) as document:
        text = '\n'.join(page_.extract_text() or '' for page_ in document.pages).replace('\xa0', ' ')
    return dict(artifact, content=content), text


def clean(artifact):
    warnings = artifact['metadata']['warnings']
    return not artifact['metadata'].get('template_fallback') and not any(code.startswith('block_fallback')
                                                                         for code in warnings)


def lines(text):
    return [line.strip() for line in text.split('\n') if line.strip()]


def context(template_id, locale='uz', facts=None, *, entry_id=None):
    """A build context of the template with `facts` as its verified values, at the first step."""
    template = catalogue.template(template_id)
    entry = catalogue.get(entry_id or template['entries'][0])
    content = {'title': '', 'questions': [], 'sections': [
        {'id': 'facts', 'heading': '', 'body': '', 'layout': 'list',
         'items': [{'label': key, 'text': value} for key, value in (facts or {}).items()]}]}
    left, bottom, width, height = page.geometry(template)
    return Ctx(content=content, entry=entry, template=template, locale=locale, step=0, pages=1, width=width,
               frame_height=height, day=DAY)


def place(block, params, fields=(), *, locale=None):
    return Place(block, None, None, tuple(fields), localised(params, locale) if locale else params)


def texts(flowables):
    """Every Paragraph's plain text among the flowables, a Table's cells included, in order."""
    found = []
    for flowable in flowables:
        if isinstance(flowable, Paragraph):
            found.append(' '.join(flowable.getPlainText().replace('\xa0', ' ').split()))
        elif isinstance(flowable, Table):
            for row in flowable._cellvalues:
                for cell in row:
                    found += texts(cell if isinstance(cell, list) else [cell])
    return found


# ---------------------------------------------------------------- the family


@paper_family.each(TEMPLATES)
def test_every_template_reads_well(template_id, locale, case, tmp_path):
    drawn_ = paper_family.assert_reads_well(template_id, locale, case, tmp_path)
    # One page for the fixed papers and every full or blank sample; a long one says it came out longer.
    if case != 'long':
        assert drawn_.artifact['page_count'] == 1
    else:
        assert 'longer_than_quoted' in drawn_.artifact['metadata']['warnings']


def test_every_template_has_its_samples():
    paper_family.assert_has_samples(TEMPLATES)


def test_every_template_is_drawn_by_the_engine_and_every_letter_entry_finds_one():
    # The engine can draw each entry's paper in every language; the entries themselves stay `draft` until N2's
    # native reading, so none of this is live.
    assert 'split_row' in registry.BLOCKS
    for template_id in TEMPLATES:
        assert not registry.missing(paper.flow_blocks(catalogue.template(template_id))), template_id
    for entry_id in ENTRIES:
        for locale in ('uz', 'ru', 'en'):
            assert paper.ready({'options': {'category': entry_id}, 'output_locale': locale, 'prompt': 'x'}), entry_id
        found = catalogue.check(entry_id)
        assert not [problem for problem in found if not problem.warning]
        assert not [problem for problem in found if problem.text.startswith('blocks not yet registered')]


def test_the_recommendation_is_the_letter_in_english_and_the_statement_head_by_its_cue():
    recommendation, motivation = catalogue.get('pdf.xat.tavsiya'), catalogue.get('pdf.xat.motivatsion')
    assert paper.pick(recommendation, 'en') == 'letter_tavsiya'
    assert paper.pick(recommendation, 'uz') == paper.pick(recommendation, 'ru') == 'tavsiya_rasmiy'
    assert paper.pick(motivation, 'en', frozenset({'statement'})) == 'letter_statement'
    assert paper.pick(motivation, 'en') == 'letter_motivatsion'


def test_every_word_a_line_says_is_a_label_or_field_of_its_template():
    # The catalogue checks `label`, `labels` and `captions`; a line's `text` and `without` name labels too, and a
    # misspelt one would print nothing at all.
    for template_id in TEMPLATES:
        template = catalogue.template(template_id)
        entry = catalogue.get(template['entries'][0])
        for flow in template['flow']:
            entries = [flow]
            params = flow.get('params') or {}
            if flow['block'] == 'split_row':
                entries = [item for side in ('left', 'right') for item in official._entries(params.get(side))]
            for item in entries:
                spec = item.get('params') or item
                for key in [spec.get('text'), *(spec.get('without') or {}).values()]:
                    if key is not None:
                        assert key in template['labels'] or entry.field(key) or entry.part(key), (template_id, key)


# ---------------------------------------------------------------- split_row


def test_split_row_puts_the_addressee_left_and_the_date_flush_right(tmp_path):
    artifact, text = drawn(tmp_path, 'letter_cover', 'en')
    assert clean(artifact)
    with pdfplumber.open(artifact['path']) as document:
        words = document.pages[0].extract_words()
        right = page.geometry(catalogue.template('letter_cover'))
        frame_right = right[0] + right[2]
    date = next(word for word in words if word['text'] == 'September')
    addressee = next(word for word in words if word['text'] == 'Ms')
    assert abs(date['top'] - addressee['top']) < 2, 'on one row'
    assert abs(next(word for word in words if word['text'] == '2026' and abs(word['top'] - date['top']) < 2)['x1']
               - frame_right) < 1.5, 'the date ends at the right edge of the frame'
    assert addressee['x0'] < right[0] + 2


def test_split_row_stacks_the_outgoing_number_under_the_date_only_when_there_is_one(tmp_path):
    artifact, text = drawn(tmp_path, 'tavsiya_rasmiy', 'ru')
    assert clean(artifact) and 'Исх. № 118' in text
    assert lines(text).index('16.09.2026 В приёмную комиссию') < lines(text).index(
        'Исх. № 118 магистратуры Университета «Мисол»')
    artifact, text = drawn(tmp_path, 'tavsiya_rasmiy', 'ru', drop=['outgoing_number'], name='none.pdf')
    assert clean(artifact) and '№' not in text


def test_split_row_with_nothing_either_side_draws_nothing_and_one_side_alone_keeps_its_cell():
    ctx = context('letter_cover', 'uz')
    params = {'left': {'block': 'party_block', 'fields': ['recipient_person'], 'anchor': 'left'},
              'right': {'block': 'line', 'text': 'recipient_title'}, 'left_mm': 104}
    assert official.split_row(ctx, place('split_row', params)) == []
    ctx = context('letter_cover', 'uz', {'date_written': '15.09.2026'})
    params['right'] = {'block': 'date_line', 'fact': 'date_written', 'align': 'right'}
    made = official.split_row(ctx, place('split_row', params))
    table = next(flowable for flowable in made if isinstance(flowable, Table))
    assert table._cellvalues[0][0] == '' and texts(table._cellvalues[0][1]) == ['15.09.2026']
    assert ctx.width == page.geometry(ctx.template)[2], 'the frame width is given back after drawing a cell'


def test_split_row_cells_follow_left_mm_within_a_quarter_of_the_frame():
    ctx = context('letter_cover')
    width = ctx.width
    assert official.widths(ctx, {'left_mm': 104})[0] == pytest.approx(104 * 72 / 25.4)
    assert official.widths(ctx, {})[0] == pytest.approx(width / 2)
    assert official.widths(ctx, {'left_mm': 5})[0] == pytest.approx(width * 0.25)
    assert official.widths(ctx, {'left_mm': 500})[0] == pytest.approx(width * 0.75)
    assert sum(official.widths(ctx, {'left_mm': 70})) == pytest.approx(width)


def test_split_row_anchors_a_right_half_party_in_its_own_cell():
    ctx = context('tavsiya_rasmiy', 'uz', {'addressee': 'Misol universiteti qabul komissiyasiga'})
    params = {'right': {'block': 'party_block', 'fields': ['addressee'], 'anchor': 'right_half'}, 'left_mm': 82.5}
    made = official.split_row(ctx, place('split_row', params))
    table = next(flowable for flowable in made if isinstance(flowable, Table))
    paragraph = table._cellvalues[0][1][0]
    assert paragraph.style.leftIndent == 0, 'not pushed half a frame further inside the right cell'


def test_split_row_draws_a_side_whose_block_is_unknown_plainly_and_says_so():
    ctx = context('letter_cover', 'uz', {'date_written': '15.09.2026', 'employer_name': 'Misol Logistika'})
    params = {'left': {'block': 'no_such_block', 'fields': ['employer_name']},
              'right': {'block': 'date_line', 'fact': 'date_written'}}
    made = registry.draw(ctx, place('split_row', params, ['employer_name', 'date_written']))
    assert 'block_fallback:no_such_block' in ctx.warnings
    assert any('Misol Logistika' in line for line in texts(made)) and '15.09.2026' in texts(made)


def test_split_rows_plain_fallback_draws_both_sides_one_after_the_other():
    ctx = context('tavsiya_rasmiy', 'ru', {'letter_date': '16.09.2026', 'addressee': 'В приёмную комиссию'})
    params = {'left': {'block': 'date_line', 'fact': 'letter_date'},
              'right': {'block': 'party_block', 'fields': ['addressee']}}
    assert texts(official.split_plain(ctx, place('split_row', params))) == ['16.09.2026', 'В приёмную комиссию']


def test_split_row_samples_draw_without_a_fallback(tmp_path):
    for index, item in enumerate(official.SAMPLES):
        for locale in ('uz', 'ru', 'en'):
            path, warnings = sample.draw_block(item, locale, tmp_path, index)
            assert not [code for code in warnings if code.startswith('block_fallback')], (item['name'], locale)


# ---------------------------------------------------------------- per-language parameters


def test_a_per_language_map_resolves_to_the_papers_language_and_is_absent_elsewhere():
    params = {'label': {'en': 'to'}, 'order': {'en': ['b', 'a']}, 'captions': {'a': 'cap'},
              'suffixes': {'uz': {'a': 'ga'}}, 'labels': {'name_after': {'uz': 'about'}}, 'max_lines': 4}
    assert localised(params, 'en') == {'label': 'to', 'order': ['b', 'a'], 'captions': {'a': 'cap'}, 'labels': {},
                                       'max_lines': 4}
    assert localised(params, 'uz') == {'captions': {'a': 'cap'}, 'suffixes': {'a': 'ga'},
                                       'labels': {'name_after': 'about'}, 'max_lines': 4}
    ctx = context('official_tushuntirish', 'ru')
    head = next(item for item in places(ctx) if item.part and item.part['id'] == 'addressee')
    assert 'label' not in head.params and 'order' not in head.params


# ---------------------------------------------------------------- what the papers print


def test_the_english_note_names_the_person_first_after_to_and_from(tmp_path):
    artifact, text = drawn(tmp_path, 'official_tushuntirish', 'en')
    assert clean(artifact)
    found = lines(text)
    assert found[:5] == ['To: Rustam Aliyev', 'Director, Misol Savdo LLC', 'From: Nigora Salimova', 'Accountant',
                         'Tel.: +998 90 000 11 22']
    for locale in ('uz', 'ru'):
        artifact, text = drawn(tmp_path, 'official_tushuntirish', locale, name=f'{locale}.pdf')
        assert 'To:' not in text and 'From:' not in text


def test_the_ariza_names_the_applicant_first_in_english(tmp_path):
    artifact, text = drawn(tmp_path, 'official_ariza', 'en')
    found = lines(text)
    assert found.index('From Sevara A. Komilova') < found.index('Third-year student, Faculty of History')
    artifact, text = drawn(tmp_path, 'official_ariza', 'uz', name='uz.pdf')
    found = lines(text)
    assert found.index('Tarix fakulteti 3-kurs talabasi') < found.index('Komilova Sevara Akmal qizidan')


def test_an_uzbek_blank_head_carries_its_case_ending_and_a_russian_one_none(tmp_path):
    drop = ['addressee_position', 'addressee_name', 'writer_name', 'writer_role', 'writer_phone']
    artifact, text = drawn(tmp_path, 'official_tushuntirish', 'uz', drop=drop)
    assert clean(artifact)
    assert 'ga' in lines(text)[0].split() and any(line.split()[-1:] == ['dan'] for line in lines(text)[:5])
    artifact, text = drawn(tmp_path, 'official_tushuntirish', 'ru', drop=drop, name='ru.pdf')
    assert ' ga' not in text and 'dan' not in text


def test_the_character_reference_leads_with_na_in_russian_and_ends_the_name_with_haqida_in_uzbek(tmp_path):
    artifact, text = drawn(tmp_path, 'official_tavsifnoma', 'ru')
    assert clean(artifact)
    assert 'на студентку 3 курса направления «Бухгалтерский учёт»' in text and 'ЮЛДАШЕВУ КАМОЛУ БОТИРОВНУ' in text
    artifact, text = drawn(tmp_path, 'official_tavsifnoma', 'uz', name='uz.pdf')
    assert 'YO‘LDOSHEVA KAMOLA BOTIR QIZI haqida' in text.replace("'", '‘')
    artifact, text = drawn(tmp_path, 'official_tavsifnoma', 'en', name='en.pdf')
    assert 'KAMOLA YULDASHEVA' in text and 'haqida' not in text


def test_signers_given_as_post_and_name_sign_on_their_own_rows(tmp_path):
    artifact, text = drawn(tmp_path, 'official_tavsifnoma', 'uz')
    assert '|' not in text
    rows = [line for line in lines(text) if line.startswith(('Dekan', 'Kafedra mudiri'))]
    assert rows == ['Dekan F. R. Qosimov', 'Kafedra mudiri M. T. Ergasheva']
    artifact, text = drawn(tmp_path, 'tavsiya_rasmiy', 'uz', facts={'second_signer': 'Kafedra mudiri | O. N. Rasulov'},
                           name='second.pdf')
    assert clean(artifact) and '|' not in text
    assert any(line.startswith('Kafedra mudiri') and line.endswith('O. N. Rasulov') for line in lines(text))
    # The checker reads each side of the line back as the cell it prints in.
    entry, template = catalogue.get('pdf.xat.tavsiya'), catalogue.template('tavsiya_rasmiy')
    expect = check.expect_for(artifact, artifact['content'], entry=entry, template=template, locale='uz', pages=1,
                              day=DAY)
    assert {'Kafedra mudiri', 'O. N. Rasulov'} <= set(expect['facts'])
    assert check.problems(artifact['path'], expect) == []


def test_only_a_list_or_line_field_alone_is_read_as_post_and_name_lines():
    ctx = context('tavsiya_rasmiy', 'uz', {'second_signer': 'Kafedra mudiri | O. N. Rasulov\nDekan | F. Qosimov',
                                           'recommender_name': 'Jamshid Qurbonov\nikkinchi qator'})
    assert core._signers(ctx, place('signature_row', {}, ['second_signer'])) == [
        ('Kafedra mudiri', 'O. N. Rasulov'), ('Dekan', 'F. Qosimov')]
    # A name field is a person, never a list: its one row stays one row whatever its value holds.
    assert core._signers(ctx, place('signature_row', {}, ['recommender_name'])) == [
        ('', 'Jamshid Qurbonov\nikkinchi qator')]


def test_a_long_post_on_the_signature_row_wraps_at_the_body_size():
    post = 'Associate professor, information systems department of the faculty of computing'
    ctx = context('tavsiya_rasmiy', 'en', {'recommender_position': post, 'recommender_name': 'Jamshid Kurbanov'})
    made = core.signature_row(ctx, place('signature_row', {'variant': 'post_sign_name'},
                                         ['recommender_position', 'recommender_name']))
    table = next(flowable for flowable in made if isinstance(flowable, Table))
    typed = next(item for item in table._cellvalues[0][0] if isinstance(item, Paragraph))
    assert typed.style.fontSize == ctx.styles['body'].fontSize
    # The short name gives its spare room to the post.
    assert table._colWidths[0] > ctx.width * 0.38


def test_a_character_reference_without_signers_has_one_blank_row_to_sign(tmp_path):
    artifact, text = drawn(tmp_path, 'official_tavsifnoma', 'uz', drop=['signers'])
    assert clean(artifact)
    assert '(lavozimi)' in text and '(imzo)' in text and '(F.I.Sh.)' in text


@pytest.mark.parametrize('template_id', ['tavsiya_rasmiy', 'letter_tavsiya'])
def test_the_verdict_says_its_target_when_given_and_its_own_words_without(template_id, tmp_path):
    words = catalogue.template(template_id)['labels']
    for strength, target, key in (('standard', True, 'verdict_target'), ('standard', False, 'verdict'),
                                  ('strong', True, 'verdict_strong'), ('strong', False, 'verdict_strong_plain')):
        facts = {'strength': strength, 'candidate_short': 'Shahnoza'}
        artifact, text = drawn(tmp_path, template_id, 'en', facts=facts, drop=() if target else ['target'],
                               name=f'{strength}-{target}.pdf')
        expected = words[key]['en'].replace('{candidate_short}', 'Shahnoza').replace(
            '{target}', 'admission to the information systems master’s programme')
        assert ' '.join(expected.split()) in ' '.join(text.split()), (strength, target)
        assert clean(artifact)
        if not target:
            assert 'admission to the information systems' not in text


def test_the_official_form_prints_the_presentation_line_only_without_an_addressee(tmp_path):
    words = catalogue.template('tavsiya_rasmiy')['labels']['presentation']['uz']
    artifact, text = drawn(tmp_path, 'tavsiya_rasmiy', 'uz')
    assert words not in ' '.join(text.split())
    artifact, text = drawn(tmp_path, 'tavsiya_rasmiy', 'uz', drop=['addressee'], name='bare.pdf')
    assert words in ' '.join(text.split())


def test_a_letter_signs_with_the_name_or_a_captioned_rule_for_it(tmp_path):
    artifact, text = drawn(tmp_path, 'letter_cover', 'uz')
    assert lines(text)[-2:] == ['Malika Tursunova', 'Ilova: Rezyume (CV).']
    artifact, text = drawn(tmp_path, 'letter_cover', 'uz', drop=['applicant_name'], name='blank.pdf')
    assert clean(artifact) and '(F.I.Sh.)' in text
    # The cover letter's sender never draws ruled rows: without a name its contacts stay one small line.
    assert lines(text)[0] == '+998 90 123 45 67 · malika.tursunova@example.com · Toshkent'


def test_the_motivation_letters_greeting_and_close_follow_its_form(tmp_path):
    artifact, text = drawn(tmp_path, 'letter_motivatsion', 'en')
    assert 'Dear Admissions Committee,' in text and 'Yours faithfully,' in text
    artifact, text = drawn(tmp_path, 'letter_motivatsion', 'en',
                           facts={'salutation_form': 'person', 'salutation': 'Dear Dr Keller,'}, name='person.pdf')
    assert 'Dear Dr Keller,' in text and 'Yours sincerely,' in text and 'Admissions Committee,' not in text


def test_a_motivation_letter_without_a_programme_keeps_its_institution_without_the_lead_word(tmp_path):
    artifact, text = drawn(tmp_path, 'letter_motivatsion', 'en', drop=['target_programme'])
    assert clean(artifact)
    assert 'Letter of motivation:' not in text and 'Misol University of Technology, autumn 2027 intake' in text


def test_the_contact_line_joins_the_senders_contacts_and_blanks_what_is_missing(tmp_path):
    artifact, text = drawn(tmp_path, 'letter_motivatsion', 'uz')
    assert '+998 90 765 43 21 · aziz.normurodov@example.com · Samarqand' in text
    artifact, text = drawn(tmp_path, 'letter_motivatsion', 'ru', drop=['applicant_name', 'phone', 'email', 'address'],
                           name='blank.pdf')
    assert clean(artifact) and 'Тел.:' in text and 'Эл. почта:' in text and '(Ф.И.О.)' in text
    artifact, text = drawn(tmp_path, 'letter_statement', 'en', name='statement.pdf')
    assert 'Samarkand · +998 90 765 43 21 · aziz.normurodov@example.com' in text
    assert 'Dear' not in text and 'Yours' not in text


def test_the_letter_recommendation_lists_its_contacts_with_their_words(tmp_path):
    artifact, text = drawn(tmp_path, 'letter_tavsiya', 'en')
    assert 'Phone: +998 90 123 45 67 · E-mail: j.kurbanov@example.com' in text
    artifact, text = drawn(tmp_path, 'letter_tavsiya', 'en', drop=['recommender_email'], name='phone.pdf')
    assert 'Phone: +998 90 123 45 67' in text and 'E-mail' not in text


def test_a_letterhead_of_ruled_blanks_alone_has_no_second_rule_under_it():
    ctx = context('official_tavsifnoma', 'uz')
    head = next(item for item in places(ctx) if item.part and item.part['id'] == 'issuer')
    made = core.party_block(ctx, head)
    assert not [flowable for flowable in made if isinstance(flowable, core.Hair)]
    ctx = context('official_tavsifnoma', 'uz', {'issuer_name': 'Namuna kolleji'})
    made = core.party_block(ctx, next(item for item in places(ctx) if item.part and item.part['id'] == 'issuer'))
    assert [flowable for flowable in made if isinstance(flowable, core.Hair)]
    assert texts(made) == ['NAMUNA KOLLEJI']


@pytest.mark.parametrize('template_id', TEMPLATES)
def test_nothing_is_cut_when_the_head_and_the_closing_run_long(template_id, tmp_path):
    given = sample.load(template_id, 'full')
    entry = catalogue.get(given['entry'])
    longer = {key: f'{value} {value}' for key, value in given['uz']['facts'].items()
              if entry.field(key)['kind'] in ('org', 'line', 'place', 'person')}
    artifact, text = drawn(tmp_path, template_id, 'uz', facts=longer)
    assert clean(artifact)
    # The checker reads every printed fact back whole, a wrapped one too.
    expect = check.expect_for(artifact, artifact['content'], entry=entry, template=catalogue.template(template_id),
                              locale='uz', pages=1, day=DAY)
    assert [problem for problem in check.problems(artifact['path'], expect) if 'missing' in problem] == []
    assert set(longer.values()) & set(expect['facts'])


def strings(value):
    if isinstance(value, dict):
        return [item for nested in value.values() for item in strings(nested)]
    if isinstance(value, list):
        return [item for nested in value for item in strings(nested)]
    return [value] if isinstance(value, str) else []


def test_the_samples_keep_each_languages_script_and_the_house_apostrophes():
    from apps.studio.language import CYRILLIC
    for template_id in TEMPLATES:
        given = sample.load(template_id, 'full')
        for locale in ('uz', 'en'):
            assert not [text for text in strings(given[locale]) if CYRILLIC.search(text)], (template_id, locale)
        assert not [text for text in strings(given['uz']) if "'" in text], template_id
        assert 'Rahimov' not in str(given) and 'Рахимов' not in str(given)


@pytest.mark.parametrize('template_id', [template_id for template_id in TEMPLATES
                                         if catalogue.template(template_id)['family'] == 'letter'
                                         and 'close' in catalogue.template(template_id)['labels']])
def test_a_letters_close_and_its_signer_never_part_across_a_page(template_id, tmp_path):
    # The closing paragraph, the close word, the signature, the name, the post, the contacts and the enclosures
    # are one keep group: a body grown a sentence at a time never leaves "Hurmat bilan," at a page's foot with
    # the name or the enclosures alone overleaf.
    given = sample.load(template_id, 'full')
    template = catalogue.template(template_id)
    name = next(given['uz']['facts'][field_id] for field_id in ('recommender_name', 'applicant_name')
                if field_id in given['uz']['facts'])
    close = template['labels']['close']['uz']
    body = max((section for section in given['uz']['sections'] if section.get('body')),
               key=lambda section: len(section['body']))
    sentence = 'Bu gap matnni sahifadan oshirish uchun qo‘shilgan.'
    pages_seen = set()
    for extra in range(0, 63, 3):
        grown = dict(body, body=' '.join([body['body']] + [sentence] * extra))
        artifact, text = drawn(tmp_path, template_id, 'uz', sections=[grown], name=f'grown-{extra}.pdf')
        with pdfplumber.open(artifact['path']) as document:
            pages = [(page_.extract_text() or '').replace('\xa0', ' ') for page_ in document.pages]
        pages_seen.add(len(pages))
        last = len(pages) - 1
        assert close in pages[last] and name in pages[last], (extra, len(pages))
    assert pages_seen >= {1, 2}, 'the sweep crosses the page break'
