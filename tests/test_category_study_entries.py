"""The academic and study papers (C2a): mustaqil ish, kurs ishi, konspekt, dars ishlanmasi with tarqatma, test.

They are drafts until their templates are built and read (R3a, R3b, N2), so
nothing here draws a page: these tests hold what the entries promise the
packages that build on them. Chapters repeat as a group the model sizes to the
customer's plan; a title-page year is the clock's; a references part lists
only what was supplied; a handout is its own template, picked by its cue; a
long file is kept head and tail for notes; and every entry fits the model's
budget with no rule left to reword. The last test draws each entry at its
shortest and default length through the paper engine with stand-in blocks.
"""
import itertools

import pytest

from apps.studio.categories import catalogue, prompting, skeleton
from apps.studio.categories.catalogue import BLOCK_BUDGET, PAPER_BOUNDS, SOURCES_CUE

STUDY = ('pdf.mustaqil_ish', 'pdf.kurs_ishi', 'pdf.konspekt', 'pdf.dars_ishlanmasi', 'pdf.test')


def entry(entry_id):
    return catalogue.get(entry_id)


def subsets(paper):
    names = sorted(set(paper.raw['cues']) | {SOURCES_CUE})
    for size in range(len(names) + 1):
        for chosen in itertools.combinations(names, size):
            yield skeleton.effective(paper, chosen)


@pytest.mark.parametrize('entry_id', STUDY)
def test_each_entry_is_a_draft_paper_within_its_budgets(entry_id):
    paper = entry(entry_id)
    assert (paper.service, paper.status, paper.raw['parent']) == ('pdf', 'draft', None)
    assert len(prompting.block(paper)) <= BLOCK_BUDGET
    assert not [rule for rule in paper.raw['rules'] if rule['to'] == 'rewrite']
    found = [problem for problem in catalogue.check(entry_id) if problem.subject == entry_id]
    # What is left before ready is only the blocks R1, R3a and R3b register, and the readers N2 brings.
    assert all('not yet registered' in problem.text for problem in found), found


@pytest.mark.parametrize('entry_id', STUDY)
def test_every_length_and_cue_subset_seeds_within_the_paper_bounds(entry_id):
    paper = entry(entry_id)
    for held in subsets(paper):
        for length in range(paper.length['min'], paper.length['max'] + 1):
            sections = skeleton.seed(paper, length, held)
            assert len(sections) <= PAPER_BOUNDS.sections, (entry_id, length, sorted(held))
            assert len({section['id'] for section in sections}) == len(sections)


@pytest.mark.parametrize('entry_id', ['pdf.mustaqil_ish', 'pdf.kurs_ishi'])
def test_chapters_are_a_group_the_model_sizes_to_the_plan(entry_id):
    paper = entry(entry_id)
    assert paper.raw['groups']['chapter'] == {'min': 2, 'max': 3, 'sized': 'model'}
    for length in (paper.length['min'], paper.length['default'], paper.length['max']):
        chapters = [use for use in skeleton.parts(paper, length, frozenset()) if use.part['id'] == 'chapter']
        assert [use.section_id for use in chapters] == ['chapter', 'chapter_2', 'chapter_3']
    # A later instance's sections find their part, so finish and the template read them.
    assert paper.part('section_b_3')['id'] == 'section_b' and paper.part('chapter_2')['group'] == 'chapter'
    grouped = [part for part in paper.parts if part.get('group') == 'chapter']
    assert grouped[0]['id'] == 'chapter' and all(part['heading_mode'] in ('model', 'none') for part in grouped)


def test_a_short_paper_has_fewer_sections_to_a_chapter_than_a_long_one():
    paper = entry('pdf.mustaqil_ish')
    def per_chapter(length):
        return [use.part['id'] for use in skeleton.parts(paper, length, frozenset()) if use.instance == 1
                and use.group == 'chapter']
    # Below 11 pages a plan's points are the sections of two chapters, so a third section is there for five or six.
    assert per_chapter(8) == ['chapter', 'section_a', 'section_b', 'section_c']
    assert per_chapter(11) == ['chapter', 'section_a', 'section_b', 'section_c']
    assert per_chapter(12) == ['chapter', 'section_a', 'section_b', 'section_c', 'section_d']
    assert per_chapter(20) == ['chapter', 'section_a', 'section_b', 'section_c', 'section_d']


def test_a_third_chapter_comes_only_where_three_can_fill_their_pages():
    # Each chapter starts a page, so three equal chapters end on page 5 + 3k: at 9 or 10 pages they cannot end on
    # the quoted page without cutting most of their sentences. The rules say so, and the plan rule says where a
    # three-point plan goes instead.
    paper = entry('pdf.mustaqil_ish')
    plan = next(rule['text'] for rule in paper.raw['rules'] if rule['text'].startswith('A plan the customer gives'))
    assert 'From 11 pages, up to three points are the chapter titles' in plan
    assert 'Below 11 pages there are two chapters: every point is a section' in plan
    assert 'only from 11 pages' in paper.part('chapter')['write']
    kurs = entry('pdf.kurs_ishi')
    plan = next(rule['text'] for rule in kurs.raw['rules'] if rule['text'].startswith('A kafedra plan'))
    assert 'at most three chapters' in plan and 'three chapters only from 31 pages' in plan
    assert 'the paper is 14 pages or more' in kurs.part('section_c')['write'] and kurs.part('section_c')['from'] == 14


def test_a_title_page_year_is_the_clocks_and_no_other_fact_is():
    clocked = {(paper_id, item['id']): item['clock'] for paper_id in STUDY for item in entry(paper_id).fields
               if item.get('clock')}
    assert clocked == {('pdf.mustaqil_ish', 'year'): 'year', ('pdf.kurs_ishi', 'year'): 'year'}
    for paper_id in ('pdf.mustaqil_ish', 'pdf.kurs_ishi'):
        year = entry(paper_id).field('year')
        assert (year['kind'], year['missing']) == ('date', 'omit')
        title = next(part for part in entry(paper_id).parts if part['id'] == 'title_page')
        assert 'year' in title['fields']
    # A lesson's date is the teacher's to write: a blank, never today's.
    assert 'clock' not in entry('pdf.dars_ishlanmasi').field('date')


def test_references_are_a_sources_part_and_notes_list_them_only_when_supplied():
    for paper_id in ('pdf.mustaqil_ish', 'pdf.kurs_ishi'):
        references = entry(paper_id).part('references')
        assert references['kind'] == 'sources' and 'when' not in references
        assert 'references' in [use.section_id for use in skeleton.parts(entry(paper_id), 10, frozenset())]
    notes = entry('pdf.konspekt')
    assert notes.part('references')['kind'] == 'sources'
    assert 'references' not in [section['id'] for section in skeleton.seed(notes, 4, frozenset())]
    assert 'references' in [section['id'] for section in skeleton.seed(notes, 4, frozenset({SOURCES_CUE}))]
    assert not any(part['kind'] == 'sources' for paper_id in ('pdf.dars_ishlanmasi', 'pdf.test')
                   for part in entry(paper_id).parts)


def pdf_entries():
    return [paper for paper in catalogue._catalogue().entries.values() if paper.service == 'pdf']


def every_length(paper):
    return range(max(1, paper.length['min']), paper.length['max'] + 1)


def test_a_reference_list_is_never_asked_for_words_it_has_no_source_for():
    # A customer who supplied no source must not be told to write N words of
    # references: the only way to reach N is to invent the list.
    for paper in pdf_entries():
        for part in paper.parts:
            if part['kind'] != 'sources':
                continue
            for held in subsets(paper):
                for length in every_length(paper):
                    for use in skeleton.parts(paper, length, held):
                        if use.part['id'] == part['id'] and use.section_id:
                            assert skeleton.words(paper, use, length, held)[0] == 0, (paper.id, length)


def test_only_prose_grows_and_shrinks_in_a_count_paper():
    # The count rule trims and the top-up extends elastic prose only, so a list,
    # table or group marked elastic would be handed the leftover pages with
    # nothing able to cut or fill it. A test's question parts grow with the
    # count of questions it derives its pages from, so they are not this rule's.
    for paper in pdf_entries():
        if (paper.length['mode'], paper.length['target']) != ('count', 'count'):
            continue
        grown = [part['id'] for part in paper.parts if part.get('elastic') and part['kind'] != 'prose']
        assert not grown, (paper.id, grown)


@pytest.mark.parametrize('entry_id', ['pdf.mustaqil_ish', 'pdf.kurs_ishi', 'pdf.konspekt', 'pdf.dars_ishlanmasi'])
def test_the_shortest_length_holds_the_pages_its_template_forces(entry_id):
    # Each placement that starts a page and always draws (no condition, or a
    # required part) is one page the paper cannot do without, a group's once
    # per instance it is seeded with at the shortest length: a group the model
    # sizes is seeded at its max and the model fills it to the plan, so all of
    # them may be written. The entry's minimum must leave room for every one.
    paper = entry(entry_id)
    for template_id in paper.templates:
        flow = catalogue.template(template_id)['flow']
        forced = 1
        for place in flow:
            if not place.get('page_break_before'):
                continue
            part = paper.part(place['part']) if place.get('part') else None
            when = place.get('when')
            if when and not (when == f"part:{place.get('part')}" and part and part['need'] == 'required'):
                continue
            group = (part or {}).get('group')
            forced += skeleton.instances(paper, group, paper.length['min']) if group else 1
        assert forced <= paper.length['min'], (entry_id, template_id, forced)
    assert str(paper.length['min']) in paper.length['note'] or paper.length['min'] == 1
    assert any(f"{paper.length['min']} page" in gate for gate in paper.raw['gates']), entry_id


def test_a_handout_key_is_written_only_in_a_handout_and_only_when_asked():
    lesson = entry('pdf.dars_ishlanmasi')
    keyword = 'Mavzu bo‘yicha kalit so‘zlar va javoblar bilan dars ishlanmasi, 7-sinf'
    plan = skeleton.cues(lesson, keyword, has_files=False)
    assert 'h_key' not in [section['id'] for section in skeleton.seed(lesson, 4, plan)]
    sheet = [use for use in skeleton.parts(lesson, 2, frozenset({'handout'})) if use.part['id'] == 'h_key']
    assert skeleton.words(lesson, sheet[0], 2, frozenset({'handout'}))[0] == 0
    assert 'only when the customer asks for the answers' in lesson.part('h_key')['write']
    # "formula" or "format" in an English brief is not a grade.
    grade = lesson.field('grade')['cues']['en']
    assert not any(skeleton.stem_found(stem, 'a formula sheet in a printable format') for stem in grade)
    # Explaining a topic's content is notes, not a summary of a file.
    notes = entry('pdf.konspekt')
    assert 'summary' not in skeleton.cues(notes, 'Fotosintez mavzu mazmunini tushuntiring', has_files=False)


def test_a_handout_is_its_own_template_picked_by_its_cue():
    lesson = entry('pdf.dars_ishlanmasi')
    assert lesson.templates == ('study_dars_ishlanmasi', 'study_tarqatma')
    assert 'pick' not in catalogue.template('study_dars_ishlanmasi')
    assert catalogue.template('study_tarqatma')['pick'] == 'cue:handout'
    handout = skeleton.cues(lesson, '6-sinf biologiya, «Hujayra tuzilishi» mavzusiga tarqatma kerak',
                            has_files=False)
    assert 'handout' in handout
    plan = [section['id'] for section in skeleton.seed(lesson, 4, frozenset())]
    sheet = [section['id'] for section in skeleton.seed(lesson, 2, handout)]
    assert 'stage_new' in plan and not [section for section in plan if section.startswith(('h_', 'task'))]
    assert sheet[:3] == ['facts', 'h_rule', 'task'] and 'stage_new' not in sheet
    assert skeleton.length(lesson, cues=handout) == 2 and skeleton.length(lesson, cues=frozenset()) == 4
    # A plan's lesson stages are written; a stage's questions are its list items, never content.questions.
    assert lesson.part('stage_review')['kind'] == 'list' and lesson.raw['questions'] == {'default': 0, 'max': 0}


@pytest.mark.parametrize('message', [
    '7-sinf ona tili, «Ot» mavzusida dars ishlanmasi. Metodlar: savol-javob, kartochkalar bilan ishlash',
    'Поурочный план, 5 класс, математика. Методы: беседа, работа по карточкам, дидактическая игра',
    'Dars ishlanmasi, 3-sinf tabiiy fan, jihozlar: darslik, doska, didaktik materiallar',
    'Lesson plan, grade 6 English, equipment: textbook, task cards',
    'Dars ishlanmasi va o‘quvchilar uchun tarqatma kerak, 8-sinf kimyo',
    'Lesson plan with a worksheet for the pupils, grade 5 maths',
], ids=['uz-cards', 'ru-cards', 'uz-didactic', 'en-task-cards', 'uz-plan-and-handout', 'en-plan-and-worksheet'])
def test_a_named_lesson_plan_is_the_plan_whatever_its_methods_and_materials(message):
    # Cards, worksheets and didactic material are a plan's methods and
    # equipment; a teacher who names the plan gets aims, stages and minutes.
    lesson = entry('pdf.dars_ishlanmasi')
    held = skeleton.cues(lesson, message, has_files=False)
    assert 'handout' not in held and 'lesson_plan' in held
    assert 'stage_new' in [section['id'] for section in skeleton.seed(lesson, 4, held)]


@pytest.mark.parametrize('message', [
    '6-sinf biologiya, «Hujayra tuzilishi» mavzusiga tarqatma kerak',
    'Раздатка для 6 класса: строение клетки, 5 заданий',
    'Рабочий лист по математике, 3 класс, сложение',
    'A worksheet for grade 4 on fractions, with answers',
], ids=['uz', 'ru', 'ru-worksheet', 'en'])
def test_a_handout_asked_for_without_a_plan_is_the_handout(message):
    lesson = entry('pdf.dars_ishlanmasi')
    assert 'handout' in skeleton.cues(lesson, message, has_files=False)


def test_a_handout_holds_its_two_pages_with_its_key():
    # Every handout part has fixed words, so its tasks are sized to the two
    # pupil pages. The key starts a sheet of its own after them (template.md
    # page K1): on the pupils' page it would be handed out with the tasks.
    lesson = entry('pdf.dars_ishlanmasi')
    handout = frozenset({'handout'})
    assert lesson.raw['groups']['task'] == {'min': 2, 'max': 6, 'sized': 'model'}
    top = sum(skeleton.words(lesson, use, 2, handout)[1] for use in skeleton.parts(lesson, 2, handout))
    assert top <= 600, top
    flow = catalogue.template('study_tarqatma')['flow']
    assert [place for place in flow if place.get('part') == 'h_key' and place.get('page_break_before')]


def test_the_technological_map_is_deferred_and_never_promised():
    lesson = entry('pdf.dars_ishlanmasi')
    deferred = next(item for item in lesson.raw['later'] if 'technological map' in item['text'])
    assert {'texnologik xarita', 'технологическ', 'technological map'} <= set(deferred['words'])
    copy = str([lesson.raw['bot']['prompt'], lesson.raw['bot']['examples'], lesson.raw['bot'].get('pool'),
                lesson.raw['bot']['notices']]).lower()
    assert not any(word in copy for word in deferred['words'])


def test_the_owners_label_for_lessons():
    assert entry('pdf.dars_ishlanmasi').label('uz') == '🏫 Dars ishlanmasi / tarqatma'
    assert catalogue._catalogue().index['owner_labels']['pdf.dars_ishlanmasi'] == 'Dars ishlanmasi / tarqatma'


def test_notes_keep_a_long_files_head_and_tail_and_read_their_form_from_the_message():
    notes = entry('pdf.konspekt')
    assert notes.raw['sources'] == {'take': 'head_tail'}
    assert skeleton.cues(notes, 'Biriktirilgan faylning qisqacha mazmuni kerak', has_files=True) == \
        {'summary', SOURCES_CUE}
    assert skeleton.cues(notes, 'Imtihon savollari: savol-javob, qisqacha mazmun emas', has_files=False) == {'qa'}
    answers = [use.section_id for use in skeleton.parts(notes, 4, frozenset({'qa'})) if use.part['id'] == 'answer']
    assert len(answers) == 12 and 'section' not in [section['id'] for section in
                                                    skeleton.seed(notes, 4, frozenset({'qa'}))]
    summary = [section['id'] for section in skeleton.seed(notes, 2, frozenset({'summary'}))]
    assert 'lead' in summary and 'main_points' in summary and 'takeaways' not in summary


def test_the_test_keeps_its_locked_shape_with_its_rules_reworded():
    test = entry('pdf.test')
    assert test.part('grade_scale')['retired'] is True
    assert skeleton.length(test) == 4 and skeleton.length(test, questions=40) == 6
    assert [section['id'] for section in skeleton.seed(test, 4, frozenset())] == ['facts', 'passage']
    rules = ' '.join(rule['text'] for rule in test.raw['rules'])
    assert 'One variant only' in rules and 'copy the text of the correct option exactly into answer' in rules


@pytest.mark.parametrize('entry_id', ['pdf.mustaqil_ish', 'pdf.kurs_ishi', 'pdf.konspekt', 'pdf.dars_ishlanmasi'])
def test_a_count_paper_names_its_default_in_every_language(entry_id):
    paper = entry(entry_id)
    assert paper.length['mode'] == 'count'
    for locale in ('uz', 'ru', 'en'):
        assert str(paper.length['default']) in paper.raw['bot']['prompt'][locale]


# ---------------------------------------------------------------- pages, drawn


FILLER = ('ta’lim jarayonida o‘quvchilarning mustaqil fikrlashi muhim ahamiyatga ega bo‘lib zamonaviy usullar dars '
          'samaradorligini oshirishga xizmat qiladi va tahlil natijalari amaliyotda qo‘llaniladi bu ham esa bilan '
          'uchun bir har o‘z keng yangi turli usul fan kun yil ish reja natija maqsad vazifa sinf bola oila hayot '
          'bilim ko‘nikma malaka tizimli yondashuv asosida tashkil etiladi muntazam baholanadi').split()


def _sentence(rng, size):
    words = [rng.choice(FILLER) for _ in range(max(3, size))]
    return ' '.join([words[0].capitalize(), *words[1:]]) + '.'


def _prose(rng, count):
    sentences = []
    while count > 0:
        size = min(count, rng.randint(9, 15))
        sentences.append(_sentence(rng, size))
        count -= size
    return '\n'.join(' '.join(sentences[start:start + 5]) for start in range(0, len(sentences), 5))


def _content(paper, length, cues, written, empty, rng, share=0.9):
    """A paper's content with each written part at `share` of its top word count, as a model that nearly meets
    its targets writes it; a group the model sizes has `written` instances, the rest left empty and dropped, and
    the parts in `empty` are left empty as their rule says they are for this brief."""
    sections = [{'id': 'facts', 'heading': '', 'body': '', 'notes': '', 'layout': 'list', 'items': []}]
    for use in skeleton.parts(paper, length, cues):
        if not use.section_id or use.part['kind'] == 'sources':
            continue
        if use.group and paper.raw['groups'][use.group]['sized'] == 'model' and use.instance > written:
            continue
        if use.part['id'] in empty:
            continue
        if 'qa' in cues and use.part['id'] in ('takeaways', 'review'):
            continue  # "None in the questions-and-answers form."
        count = round(share * skeleton.words(paper, use, length, cues)[1])
        if not count:
            continue
        section = {'id': use.section_id, 'heading': _sentence(rng, 6).rstrip('.'), 'body': '', 'notes': '',
                   'layout': 'text', 'items': []}
        if use.part['kind'] == 'prose':
            section['body'] = _prose(rng, count)
        else:
            section['items'] = [{'label': '', 'text': _sentence(rng, 14), 'value': ''}
                                for _ in range(max(1, count // 14))]
        sections.append(section)
    return {'title': 'Sinov', 'sections': sections, 'questions': []}


def _stand_ins():
    """Blocks drawn about as the families will draw them: headings with their gaps, first-line indents, bulleted
    items, ruled boxes for tables, key-value rows, callouts and head boxes, a page of title facts."""
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    from apps.studio.paper.registry import Block

    def items(place):
        return [' — '.join(str(item.get(key) or '') for key in ('label', 'text') if item.get(key))
                for item in (place.section or {}).get('items') or []]

    def boxed(ctx, rows, widths, pad=3):
        table = Table(rows, colWidths=widths)
        table.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 0.5, '#000000'), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                   *[(side, (0, 0), (-1, -1), pad) for side in ('TOPPADDING', 'BOTTOMPADDING')],
                                   *[(side, (0, 0), (-1, -1), pad + 2) for side in ('LEFTPADDING', 'RIGHTPADDING')]]))
        return [table, Spacer(1, ctx.leading * 0.5)]

    def label_of(ctx, place):
        text = ctx.heading(place.part, place.section)
        label = (place.params or {}).get('label')
        return text or (ctx.label(label) if label in (ctx.template.get('labels') or {}) else '')

    def heading(ctx, place):
        text = label_of(ctx, place)
        if not text:
            return []
        level = min(3, int((place.params or {}).get('level', 2)))
        style = ctx.styles[f'h{level}']
        return [Spacer(1, ctx.leading * (1 if level == 1 else 0.5)), ctx.mark(level, text),
                Paragraph(ctx.text(text, style), style), Spacer(1, ctx.leading * 0.4)]

    def paragraph(ctx, place):
        body = ParagraphStyle('filled', parent=ctx.styles['body'],
                              firstLineIndent=(ctx.template['type'].get('indent_first_mm') or 0) * ctx.mm)
        lines = str((place.section or {}).get('body') or '').split('\n')
        return [Paragraph(ctx.text(line, body), body) for line in lines if line.strip()]

    def listed(ctx, place):
        style = ParagraphStyle('item', parent=ctx.styles['body'], leftIndent=14, firstLineIndent=-9, spaceAfter=2)
        made = paragraph(ctx, place) + [Paragraph(ctx.text('• ' + text), style) for text in items(place) if text]
        return made + [Spacer(1, ctx.leading * 0.6)] if made else []

    def table(ctx, place):
        cell = ctx.styles['cell']
        rows = [[Paragraph(ctx.text(' '.join(text.split()[:2]), cell), cell),
                 Paragraph(ctx.text(' '.join(text.split()[2:]), cell), cell)] for text in items(place) if text]
        return boxed(ctx, [[Paragraph('Atama', ctx.styles['bold']), Paragraph('Ta’rif', ctx.styles['bold'])], *rows],
                     [38 * ctx.mm, ctx.width - 38 * ctx.mm]) if rows else []

    def key_value(ctx, place):
        text = str((place.section or {}).get('body') or '').replace('\n', ' ') or ' '.join(items(place))
        row = [Paragraph('Ta’limiy maqsad', ctx.styles['bold']), Paragraph(ctx.text(text), ctx.styles['body'])]
        return boxed(ctx, [row], [40 * ctx.mm, ctx.width - 40 * ctx.mm], 2)[:1] if text.strip() else []

    def callout(ctx, place):
        inner = paragraph(ctx, place) + [Paragraph(ctx.text('• ' + text), ctx.styles['body'])
                                         for text in items(place)]
        return [Spacer(1, ctx.leading * 0.4), *boxed(ctx, [[inner]], [ctx.width], 6)] if inner else []

    def facts(ctx, place):
        rows = [[Paragraph(ctx.text(ctx.field_label(field_id) or field_id), ctx.styles['bold']),
                 Paragraph(ctx.text(ctx.fact(field_id) or ctx.blank_run(field_id)), ctx.styles['body'])]
                for field_id in place.fields if ctx.fact(field_id) is not None or ctx.blank(field_id)]
        rows = rows or [[Paragraph('Mavzu', ctx.styles['bold']), Paragraph('____', ctx.styles['body'])]]
        return [Paragraph('Sinov mavzusi', ctx.styles['h1']), Spacer(1, 4),
                *boxed(ctx, rows, [45 * ctx.mm, ctx.width - 45 * ctx.mm])]

    def strip(ctx, place):
        cells = [Paragraph(ctx.text(word + ' ________'), ctx.styles['body']) for word in ('Ism', 'Sinf', 'Sana')]
        return boxed(ctx, [cells], [ctx.width / 3] * 3)

    def title_page(ctx, place):
        made = []
        for field_id in place.fields:
            shown = ctx.fact(field_id) or ctx.blank_run(field_id)
            made += [Paragraph(ctx.text(shown), ctx.styles['body']), Spacer(1, ctx.leading)]
        return made

    def contents(ctx, place):
        made = [Paragraph(ctx.text(label_of(ctx, place) or 'Reja'), ctx.styles['h1'])]
        return made + [Paragraph(ctx.text(section['heading'] + ' …… 3'), ctx.styles['body'])
                       for section in ctx.content['sections'] if section.get('heading')]

    def references(ctx, place):
        lines = int((place.params or {}).get('blank_entries', 10))
        return [Paragraph(ctx.text(label_of(ctx, place) or 'Adabiyotlar'), ctx.styles['h1']), Spacer(1, ctx.leading),
                *[Paragraph(f'{number}. ' + '_' * 60, ctx.styles['body']) for number in range(1, lines + 1)]]

    drawn = {'heading': heading, 'paragraph': paragraph, 'list': listed, 'line': paragraph, 'formula_line': listed,
             'table': table, 'kv_table': key_value, 'callout': callout, 'doc_head': facts, 'approval_block': facts,
             'cell_strip': strip, 'title_page': title_page, 'toc': contents, 'reference_list': references}
    return {name: Block(name, function) for name, function in drawn.items()}


# (entry, pages, cues, instances the model writes of a group it sizes, parts its rules leave empty): each entry at
# its shortest and its default length. Mustaqil ish has two chapters below 11 pages (a plan's points are their
# sections, a third only for a plan of five or six) and three from 11; a kurs ishi's kafedra plan may have three
# chapters at any length; notes in their three forms; a lesson plan; a handout with six tasks on its two pupil
# pages, and with its key on the sheet after them (spec: added after the pupil pages, not counted; the engine counts
# every page, so the case is drawn at the three it takes).
DRAWN = [
    ('pdf.mustaqil_ish', 8, (), 2, ('section_c',)), ('pdf.mustaqil_ish', 8, (), 3, ('section_c',)),
    ('pdf.mustaqil_ish', 10, (), 2, ()), ('pdf.mustaqil_ish', 11, (), 3, ()),
    ('pdf.kurs_ishi', 12, (), 2, ()), ('pdf.kurs_ishi', 12, (), 3, ()), ('pdf.kurs_ishi', 25, (), 2, ()),
    ('pdf.kurs_ishi', 25, (), 3, ()),
    ('pdf.konspekt', 2, (), 0, ()), ('pdf.konspekt', 4, (), 0, ()), ('pdf.konspekt', 2, ('summary',), 0, ()),
    ('pdf.konspekt', 4, ('summary',), 0, ()), ('pdf.konspekt', 2, ('qa',), 6, ()), ('pdf.konspekt', 4, ('qa',), 12, ()),
    ('pdf.dars_ishlanmasi', 2, (), 0, ()), ('pdf.dars_ishlanmasi', 4, (), 0, ()),
    ('pdf.dars_ishlanmasi', 2, ('handout',), 6, ('h_key',)), ('pdf.dars_ishlanmasi', 3, ('handout',), 6, ()),
]


@pytest.mark.parametrize('entry_id, length, cues, written, empty', DRAWN,
                         ids=[f"{case[0]}-{case[1]}-{'+'.join(case[2]) or 'plain'}-{case[3]}" for case in DRAWN])
def test_the_shortest_and_the_default_length_end_on_their_page_without_heavy_cuts(entry_id, length, cues, written,
                                                                                   empty, monkeypatch, tmp_path):
    # skeleton.words asks for a page at its generic words a page, while these
    # templates hold about half of that and start pages of their own; each
    # entry's shares are set so a paper written at 0.9 of its targets ends
    # within its count with at most three sentences in ten cut. Stand-in
    # blocks keep this the entry's own check, whatever the families draw;
    # the real templates are sampled by their gates.
    import random

    from apps.studio import paper as paper_engine
    from apps.studio.paper import fit, registry
    monkeypatch.setattr(registry, 'BLOCKS', _stand_ins())
    paper = entry(entry_id)
    held = skeleton.effective(paper, set(cues))
    content = _content(paper, length, held, written, empty, random.Random(7))
    made = paper_engine.render_paper(content, tmp_path / 'paper.pdf', 'uz', entry=paper,
                                     template=paper_engine.pick(paper, 'uz', held), pages=length, cues=held)
    meta = made['metadata']
    assert fit.LONGER not in meta['warnings'] and made['page_count'] <= length, (made['page_count'], meta)
    assert meta['trim_ratio'] is None or meta['trim_ratio'] >= 0.7, meta['trim_ratio']
