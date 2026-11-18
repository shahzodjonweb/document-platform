"""A change request to a category paper, read narrower than a document's (apps/studio/categories/edits.py).

A paper is drawn by its template from a fixed list of parts, so a change
rewrites what the parts say and nothing else: a new look is refused, pages,
parts and pictures are not added or taken away, a new total moves the pages of
an entry whose length is a count and only those, and a test keeps its
questions. A request for the file in another format is still the domain's
format_only_change. The reading itself is today's (tests/test_edit_reading.py),
so these requests are read the same words the same way.

The people and organisations here are invented.
"""
import copy
import dataclasses
from dataclasses import asdict

import pytest

from apps.studio import categories
from apps.studio import edits as editing
from apps.studio.categories import catalogue, edits, skeleton
from apps.studio.domain import create_draft, unpack
from tests.test_category_drafts import (APPLICATION, ARIZA, HIMOYA, QUIZ, TEST, customer, drafted,  # noqa: F401
                                        made, ready, refusal, switch, written)

pytestmark = pytest.mark.django_db

COUNT = {'unit': 'pages', 'mode': 'count', 'target': 'count', 'default': 3, 'min': 1, 'max': 12}


def counted(entry):
    """The entry with a length the customer counts, as the stage-2 subject papers have (a mustaqil ish)."""
    return dataclasses.replace(entry, raw={**entry.raw, 'length': dict(COUNT)})


def paper(*headings):
    return [{'id': f'p{n}', 'heading': heading, 'body': 'Matn.'} for n, heading in enumerate(headings, 1)]


def reading(request, entry=ARIZA, sections=None, questions=0):
    entry = entry if isinstance(entry, catalogue.Entry) else categories.get(entry)
    return edits.read(request, entry, fmt='pdf', sections=sections or paper('', '', ''), questions=questions)


# ------------------------------------------------------------------ the reading


def test_a_deck_or_no_entry_is_left_to_todays_reader():
    assert edits.read('Yana 2 ta slayd qo‘sh', categories.get(HIMOYA), fmt='pptx', sections=paper('A')) is None
    assert edits.read('Batafsilroq yozing', None, fmt='pdf', sections=paper('A')) is None


@pytest.mark.parametrize('request_text', [
    'Yana ikki sahifa qo‘shing va rasmlar qo‘ying',
    'Boshiga titul varaq qo‘shing, reja va xulosa ham bo‘lsin',
    '2-sahifani olib tashlang',
    'Har bir sahifaga rasm qo‘ying',
    'Добавьте ещё 2 страницы и картинки',
    'Add a conclusion and 3 more pages with pictures',
])
def test_pages_parts_and_pictures_are_not_added_or_taken_away(request_text):
    today = editing.read(request_text, fmt='pdf', sections=paper('', '', ''))
    assert today.delta or today.parts or today.pictures or today.structural, 'today reads something to move'
    edit = reading(request_text)
    assert (edit.delta, edit.parts, edit.pictures, edit.picture_count, edit.photo_style) == (0, [], None, None, None)
    assert edit.structural is False and edit.total is None


@pytest.mark.parametrize('request_text', [
    'Dizaynni o‘zgartiring',
    'Boshqa shablon qiling, chiroyli dizayn bo‘lsin',
    'Сделайте другой дизайн',
    'Change the design and the background',
])
def test_a_new_look_is_refused_because_the_template_is_the_look(request_text):
    assert editing.read(request_text, fmt='pdf', sections=paper('A')).redesign
    edit = reading(request_text)
    assert edit.redesign is False and edit.format_only is False
    assert asdict(edit) == asdict(editing.Edit()), 'nothing else read: the paper comes back as it is'


def test_an_introduction_asked_of_a_paper_that_has_one_moves_nothing():
    sections = paper('Kirish', 'Asosiy qism', 'Xulosa')
    assert editing.read('Kirish qo‘shing', fmt='pdf', sections=paper('Asosiy qism')).parts == ['introduction']
    edit = reading('Kirish qo‘shing', sections=sections)
    assert asdict(edit) == asdict(editing.Edit())
    # One it does not have is not added either: a paper's parts are its entry's.
    assert asdict(reading('Kirish qo‘shing', sections=paper('Asosiy qism'))) == asdict(editing.Edit())


@pytest.mark.parametrize('request_text', [
    'Batafsilroq yozing', 'Ko‘proq ma’lumot qo‘shing', 'Подробнее, пожалуйста', 'Please add more detail'])
def test_more_fuller_information_is_kept(request_text):
    assert reading(request_text).expand is True


@pytest.mark.parametrize('request_text,kind,only', [
    ('PowerPoint qilib bering', 'pptx', True),
    ('Сделай в виде презентации', 'pptx', True),
    ('Slayd qilib bering va batafsilroq yozing', 'pptx', False),
])
def test_another_format_is_kept_for_the_domain_to_answer(request_text, kind, only):
    edit = reading(request_text)
    assert (edit.format, edit.format_only) == (kind, only)


@pytest.mark.parametrize('request_text,total', [
    ('8 sahifa bo‘lsin', 8),
    ('Hajmini 6 betga yetkazing', 6),
    ('Сделайте 5 страниц', 5),
    ('Make it 4 pages', 4),
    ('3-sahifadagi xatoni tuzating', None),      # a page pointed at is not a size
    ('2 ta sahifa qo‘shing', None),              # pages added are not a total
])
def test_a_new_total_is_read_for_a_counted_entry_only(request_text, total):
    assert reading(request_text, counted(categories.get(ARIZA))).total == total
    assert reading(request_text).total is None, 'an ariza is always one page'
    assert reading(request_text, TEST).total is None, 'a test is as long as its questions'


def test_a_tests_questions_are_added_or_cut_and_never_taken_away():
    edit = reading('Yana 10 ta savol qo‘shing', TEST, questions=20)
    assert (edit.questions, edit.question_count) == ('add', 30)
    edit = reading('10 ta savol qo‘shing', TEST, questions=20)
    assert (edit.questions, edit.question_count, edit.more_questions) == ('add', 10, True)
    edit = reading('Faqat 5 ta savol qoldiring', TEST, questions=20)
    assert (edit.questions, edit.question_count) == ('add', 5)
    assert editing.read('Testlarni olib tashlang', fmt='pdf', sections=paper('A'), questions=20).questions == 'remove'
    edit = reading('Testlarni olib tashlang', TEST, questions=20)
    assert (edit.questions, edit.question_count) == (None, None)
    # A paper with no questions is given none, whatever the change asks.
    edit = reading('10 ta savol qo‘shing')
    assert (edit.questions, edit.question_count, edit.more_questions) == (None, None, False)


def test_a_pasted_essay_is_read_in_milliseconds():
    import time
    started = time.perf_counter()
    reading('Kirish qo‘shing ' + 'mavzuni batafsil yoritib bering, ' * 600, TEST, questions=20)
    assert time.perf_counter() - started < 1.5


# ------------------------------------------------------------------ in the domain


@pytest.fixture
def counting(switch, monkeypatch):
    """The ariza given a counted length, the other examples ready, the switch on."""
    entries, templates, index = copy.deepcopy(catalogue.read())
    for raw in entries.values():
        raw['status'] = 'ready'
    entries[ARIZA]['length'] = dict(COUNT)
    made_ = catalogue.build(entries, {name: raw for name, raw in templates.items() if raw['entries']}, index)
    monkeypatch.setattr(catalogue, '_catalogue', lambda: made_)
    return made_


def change(who, source, prompt):
    return unpack(create_draft(who, {'prompt': prompt, 'options': {'revise_draft_id': str(source.id)}}).encrypted_data)


def test_a_new_total_sets_a_counted_papers_pages_and_keeps_its_parts(customer, counting):
    source, before = drafted(customer, ARIZA, APPLICATION)
    source = made(source, written)
    ids = [s['id'] for s in before['content']['sections']]
    assert before['options']['length'] == 3
    data = change(customer, source, '8 sahifa bo‘lsin')
    assert [s['id'] for s in data['content']['sections']] == ids
    assert (data['options']['length'], data['options']['requested_pages']) == (8, 8)
    assert skeleton.pages(data) == 8
    # Pages added are not a total, and the paper keeps its own.
    data = change(customer, source, 'Yana ikki sahifa qo‘shing')
    assert [s['id'] for s in data['content']['sections']] == ids and data['options']['length'] == 3
    assert data['revision']['edit']['delta'] == 0 and data['revision']['edit']['structural'] is False


def test_a_new_look_asked_of_a_paper_chooses_none(customer, switch):
    source, before = drafted(customer, ARIZA, APPLICATION)
    source = made(source, written)
    data = change(customer, source, 'Dizaynni o‘zgartiring va rasmlar qo‘ying')
    assert data['revision']['edit']['redesign'] is False and data['revision']['edit']['pictures'] is None
    assert data['options']['wants_design'] is False and data['options']['image_cap'] == 0
    assert data['options']['template_style'] == before['options']['template_style']
    assert data['options']['length'] == 1


def test_a_paper_asked_for_as_slides_alone_is_answered_without_a_change(customer, switch):
    source, _ = drafted(customer, ARIZA, APPLICATION)
    source = made(source, written)
    assert refusal(create_draft, customer, {'prompt': 'PowerPoint qilib bering', 'options': {
        'revise_draft_id': str(source.id)}}).code == 'format_only_change'


def test_an_introduction_asked_of_a_paper_keeps_it_as_it_is(customer, switch):
    source, before = drafted(customer, ARIZA, APPLICATION)
    source = made(source, lambda sections: [{**s, 'heading': 'Kirish' if n == 0 else s['heading'],
                                             'body': s['body'] or 'Matn.'} for n, s in enumerate(sections)])
    data = change(customer, source, 'Kirish qo‘shing')
    assert [s['id'] for s in data['content']['sections']] == [s['id'] for s in before['content']['sections']]
    assert data['options']['length'] == 1
    assert data['revision']['edit'] == asdict(editing.Edit())


def test_a_tests_change_keeps_its_questions_when_asked_to_drop_them(customer, switch):
    source, _ = drafted(customer, TEST, QUIZ)
    source = made(source, written, questions=20)
    data = change(customer, source, 'Testlarni olib tashlang')
    assert data['revision']['edit']['questions'] is None
    assert data['options']['length'] == 4, 'twenty questions kept, as many pages'
    data = change(customer, source, 'Yana 10 ta savol qo‘shing')
    assert (data['options']['question_count'], data['options']['length']) == (30, 5)
