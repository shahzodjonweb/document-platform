"""The academic and study papers (C2a): mustaqil ish, kurs ishi, konspekt, dars ishlanmasi with tarqatma, test.

They are drafts until their templates are built and read (R3a, R3b, N2), so
nothing here draws a page: these tests hold what the entries promise the
packages that build on them. Chapters repeat as a group the model sizes to the
customer's plan; a title-page year is the clock's; a references part lists
only what was supplied; a handout is its own template, picked by its cue; a
long file is kept head and tail for notes; and every entry fits the model's
budget with no rule left to reword.
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
    assert per_chapter(7) == ['chapter', 'section_a', 'section_b']
    assert per_chapter(9) == ['chapter', 'section_a', 'section_b']
    assert per_chapter(10) == ['chapter', 'section_a', 'section_b', 'section_c']
    assert per_chapter(20) == ['chapter', 'section_a', 'section_b', 'section_c', 'section_d']


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
    # required part, a group's at its fewest instances) is one page the paper
    # cannot do without; the entry's minimum must leave room for all of them.
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
            forced += paper.raw['groups'][group]['min'] if group else 1
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
