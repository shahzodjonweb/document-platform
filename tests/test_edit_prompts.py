"""What a customer's change request is told, so the model reads it and does all of it.

Real requests that went wrong (anonymised): "Reja ham bo'lsin kirish va xulosa
qismi ham" added one of the three parts; "Har bir slaydda rasm bo'lsin" brought
no pictures, because the change was told not to "add photos to meet a quota";
"Ko'proq ma'lumot" came back as the same lines reworded, because it was told to
"preserve existing length"; "Boshiga bitta sahifa qo'sh va … deb yoz" lost its
dictated name; "Test tuz" could not make a test, the change had no questions
field. Now the model splits the request into its instructions first
(edit_plan), is told how a page or slide is written, and is told what the
request asks for as apps/studio/edits.py reads it.

No model is called: these are the request bodies the provider would be sent,
and replies faked at the transport.
"""
import copy
import json
import re

import pytest

from apps.studio import deck_designs, doc_designs, layouts, pages, prompting, provider
from apps.studio.domain import DOCUMENT, SLIDES
from apps.studio.prompting import REVISION_SYSTEM, SELECTED_REVISION
from apps.studio.provider import DECK_RULES, DOCUMENT_RULES, EDIT_PLAN, revision_sizes
from tests.test_provider_contract import CONFIG, draft
from tests.test_provider_optimization import transport

FORMATS = {'pptx': SLIDES, 'pdf': DOCUMENT}


def edit(**asked):
    """An apps/studio/edits.Edit as domain stores it, asking for nothing unless told."""
    return {'total': None, 'delta': 0, 'parts': [], 'pictures': None, 'picture_count': None, 'photo_style': None,
            'questions': None, 'question_count': None, 'redesign': False, 'expand': False, 'format': None,
            'format_only': False, 'structural': False, **asked}


def changed(sections=12, fmt='pptx', request='Make it better.', count=None, **asked):
    """A whole-document change to a finished document of `sections`, now `count` long."""
    data = draft(sections, fmt)
    for number, section in enumerate(data['content']['sections'], 1):
        section.update(heading=f'Davlat {number}', body=f'Davlat {number} haqida matn.')
        if fmt == 'pptx':
            section.update(layout='cover' if number == 1 else 'bullets', items=[], columns=[], image_query='',
                           notes=f'Izoh {number}.')
    before = copy.deepcopy(data['content'])
    count = count or sections
    data['content']['sections'] = data['content']['sections'][:count]
    while len(data['content']['sections']) < count:
        data['content']['sections'].append({'id': f's{len(data["content"]["sections"]) + 1}', 'heading': '',
                                            'body': '', 'notes': ''})
    data['options']['length'] = count
    data['prompt'] = request
    data['revision'] = {'request': request, 'original_prompt': 'Eftaliylar haqida taqdimot.',
                        'edit': edit(**asked), 'before': before}
    return data


def bodies(data):
    feature = FORMATS[data['output_format']]
    return [provider.request_body(CONFIG, data, feature, span) for span in pages.batches(len(data['content']['sections']))]


def sent(body):
    return json.loads(body['input'])


def schema_of(body):
    return body['text']['format']['schema']['properties']


# --- The plan comes first ------------------------------------------------------------------

def test_a_change_is_split_into_its_instructions_before_a_word_is_written():
    whole = changed(5)
    picked = copy.deepcopy(whole)
    picked['revision'].update(selected_section_ids=['s2'], base_content=copy.deepcopy(picked['content']))
    for data in (whole, picked):
        properties = schema_of(provider.request_body(CONFIG, data, SLIDES))
        assert list(properties)[0] == 'edit_plan' and properties['edit_plan'] == EDIT_PLAN
        assert provider.request_body(CONFIG, data, SLIDES)['text']['format']['schema']['required'][0] == 'edit_plan'
    # A new document, its outline and a quality repair are not change requests.
    new = draft(5, 'pptx')
    from apps.studio import outlines
    repair = copy.deepcopy(whole)
    repair['revision'] = {'request': 'Quality repair of the pages with these ids: s2.', 'selected_section_ids': ['s2'],
                          'base_content': copy.deepcopy(whole['content']), 'original_prompt': 'Tides.'}
    repair['_stage'] = 'repair'
    for body in (provider.request_body(CONFIG, new, SLIDES), provider.request_body(CONFIG, outlines._payload(new),
                                                                                   'ai.outline'),
                 provider.request_body(CONFIG, repair, SLIDES)):
        assert 'edit_plan' not in schema_of(body)


def test_the_change_rules_ask_for_a_careful_reading_and_every_instruction_done():
    for phrase in ('word by word', 'fill it first: one entry for every separate instruction',
                   '"add a plan, an introduction and a conclusion" is three',
                   'lists every section it affects', 'carry out every instruction completely and visibly',
                   # "Varoqlarni hammasini bir xil qil" listed every slide, and the check that each listed slide
                   # changed sent all ten to a repair that could only rewrite what the customer kept.
                   'An instruction carried out outside the sections (by the design field, by the kind of pictures, '
                   'by the questions field or by the file format), one that keeps things as they were and one about '
                   'the spelling or the alphabet list no sections.',
                   'never a bare heading', 'the same text in other words is not more information',
                   '"Remove X and put Y instead" removes X entirely',
                   'copied exactly, complete and in their order', 'write ____ in its place',
                   'slide 1 of a deck is its cover', 'Never answer an instruction with a note that it cannot be done',
                   # What other parts and tests rely on stays.
                   'Existing questions remain', 'Do not add unrequested content',
                   'target language named at the end of these instructions'):
        assert phrase in REVISION_SYSTEM, phrase
    for data in (changed(5), changed(5, 'pdf')):
        guidance = sent(bodies(data)[0])['writing_guidance']
        for gone in ('Preserve existing length', 'meet a quota', 'Keep edited content within the existing'):
            assert gone not in guidance


def test_a_dictated_title_page_keeps_every_line_in_a_new_deck_too():
    """"Ustki qismiga MUSTAQIL ISH / TAYYORLADI: KARIMOVA NODIRA / QABUL QILDI: RAHIMOVA ZARINA": told the
    cover's body is "one short subtitle line", the model kept the first line only."""
    from apps.studio.slide_layouts import TITLE_LINES
    assert 'goes into it exactly as given and complete' in provider.SYSTEM
    guidance = provider.writing_guidance({}, 5, 'pptx', 0, 5)
    assert ('its body is one short subtitle line, or the title-page lines the description dictates, exactly as '
            f'given, one per line, at most {TITLE_LINES}, each copied whole') in guidance


@pytest.mark.parametrize('fmt', ['pptx', 'pdf'])
def test_a_change_is_told_how_a_page_or_slide_is_written(fmt):
    data = changed(5, fmt)
    body = bodies(data)[0]
    assert (DECK_RULES if fmt == 'pptx' else DOCUMENT_RULES) in body['instructions']
    assert (DOCUMENT_RULES if fmt == 'pptx' else DECK_RULES) not in body['instructions']
    guidance = sent(body)['writing_guidance']
    assert revision_sizes(fmt) in guidance
    words = pages.target_words(fmt)
    if fmt == 'pptx':
        assert layouts.reference(False) in body['instructions']
        for size in ('at most 8 words', '4 to 6 bullets', '12 to 20 words', '40 to 80 words',
                     f'more than {round(words * 1.3)} words'):
            assert size in guidance, size
    else:
        assert f'at least {round(words * 0.8)} words' in guidance


# --- Pictures ---------------------------------------------------------------------------------

def added(guidance, fmt, first, last):
    """The pictures a part is told to add: a number, or every page of it that has none (a deck's cover aside)."""
    unit = 'slide' if fmt == 'pptx' else 'page'
    if f'Give a picture to every {unit} of this part that has none' in guidance:
        return last - first - (fmt == 'pptx' and first == 0)
    found = re.search(rf'Add a picture to (\d+) more {unit}', guidance)
    if found:
        return int(found.group(1))
    assert f'Add no picture in this part, and keep every picture these {unit}s already have.' in guidance
    return 0


@pytest.mark.parametrize('fmt,cap', [('pptx', 60), ('pptx', 5), ('pdf', 60)])
def test_pictures_on_every_page_are_asked_for_in_every_part(fmt, cap):
    data = changed(12, fmt, "Har bir slaydda rasm bo'lsin", pictures='every')
    # The pictures the changed document has in all: one on every content page.
    content = 11 if fmt == 'pptx' else 12
    data['options'].update(image_cap=cap, images_wanted=min(cap, content), wants_layouts=True)
    shares = []
    for body, (first, last) in zip(bodies(data), pages.batches(12)):
        guidance = sent(body)['writing_guidance']
        shares.append(added(guidance, fmt, first, last))
        assert 'Do not use' not in guidance and 'photo layouts in this part' not in guidance
    assert sum(shares) == min(cap, content)
    if cap >= content:
        assert all(f'Give a picture to every {"slide" if fmt == "pptx" else "page"} of this part that has none'
                   in sent(body)['writing_guidance'] for body in bodies(data))
    if fmt == 'pptx':
        assert layouts.reference(True) in body['instructions']


def pictured(data, *numbers):
    for number in numbers:
        for document in (data['content'], data['revision']['before']):
            document['sections'][number - 1].update(layout='image_split', image_query='ancient silk road city')
    return data


@pytest.mark.parametrize('request_,wanted,shares', [
    # "Yana 2 ta rasm qo'shing" on a deck with four: told "use 2 photo layouts", the first part kept two of its
    # three and the second was told to use none, and dropped its one. Four became two.
    ("Yana 2 ta rasm qo'shing", 4 + 2, [2, 0]),
    # "Rasmlar qo'sh" with no number: about one content slide in three more.
    ("Rasmlar qo'sh", 4 + 4, [3, 1]),
    # More than the slides that have none: every one of them.
    ("Har bir slaydda rasm bo'lsin", 11, [6, 1]),
])
def test_pictures_asked_of_a_deck_that_has_some_are_added_part_by_part(request_, wanted, shares):
    data = pictured(changed(12, request=request_, pictures='every' if 'Har' in request_ else 'add'), 3, 6, 9, 11)
    data['options'].update(image_cap=12, images_wanted=wanted)
    told = []
    for body, (first, last) in zip(bodies(data), pages.batches(12)):
        guidance = sent(body)['writing_guidance']
        told.append(added(guidance, 'pptx', first, last) if 'every slide' not in guidance else
                    sum(1 for n in range(first + 1, last + 1) if n not in (1, 3, 6, 9, 11)))
        assert 'keep every picture these slides already have' in guidance
        assert 'Do not use image_split or image_full' not in guidance
        assert 'Use 0 photo' not in guidance and 'photo layouts in this part' not in guidance
    assert told == shares


def test_a_part_with_pictures_and_no_share_keeps_them():
    data = pictured(changed(12, request="1 ta rasm qo'sh", pictures='add', picture_count=1), 3, 11)
    data['options'].update(image_cap=12, images_wanted=3)
    second = sent(bodies(data)[1])['writing_guidance']
    assert 'Add no picture in this part, and keep every picture these slides already have.' in second
    # The plan adds no pictures: none is added, and none taken away.
    data['options'].update(image_cap=0)
    for body in bodies(data):
        assert 'Add no picture in this part, and keep every picture' in sent(body)['writing_guidance']


@pytest.mark.parametrize('pictures', ['add', 'every'])
def test_a_page_given_a_picture_is_asked_for_the_text_that_fits_beside_it(pictures):
    """"Har bir sahifada rasm bo'lishi kerak.": the model kept each page's text beside its new picture, and every
    page was cut off ("…") to fit; a page with a picture holds about six tenths of a page."""
    from apps.studio import doc_designs
    words = round(pages.target_words('pdf') * 0.62)
    assert doc_designs.image_words() == words
    data = changed(5, 'pdf', "Har bir sahifada rasm bo'lishi kerak.", pictures=pictures)
    data['options'].update(image_cap=12, images_wanted=5 if pictures == 'every' else 2, wants_layouts=True)
    body = bodies(data)[0]
    guidance = sent(body)['writing_guidance']
    assert (f'A page you give the image layout holds about {words} words beside its picture: rewrite that page\'s '
            f'text to about {words} words and no more, keeping its facts, names and dates; pages without a picture '
            'keep their text.') in guidance
    assert f'a page with it holds about {words} words of text' in body['instructions']
    # A deck is not told it, and neither is a document that adds no picture.
    deck = changed(5, 'pptx', "Rasmlar qo'sh", pictures=pictures)
    deck['options'].update(image_cap=12, images_wanted=2)
    assert 'beside its picture' not in sent(bodies(deck)[0])['writing_guidance']
    data['options'].update(image_cap=0)
    assert 'beside its picture' not in sent(bodies(data)[0])['writing_guidance']


def test_a_removed_picture_is_named_and_the_others_kept():
    for fmt, layout in (('pptx', 'not image_split or image_full'), ('pdf', 'text, not image')):
        data = changed(6, fmt, "Akbaraliga qo'yilgan rasmni olib tashlang", pictures='remove')
        guidance = sent(bodies(data)[0])['writing_guidance']
        assert 'removes pictures: on the sections it names' in guidance and layout in guidance
        assert 'keep every other picture' in guidance and 'Use 0 photo' not in guidance


def test_a_change_that_asks_nothing_of_pictures_is_not_told_a_count():
    data = changed(6)
    data['options']['image_cap'] = 12
    guidance = sent(bodies(data)[0])['writing_guidance']
    assert 'photo layout' not in guidance and 'image layout' not in guidance


# --- Questions --------------------------------------------------------------------------------

def test_a_test_asked_for_gets_its_questions_field_and_one_removed_loses_it():
    data = changed(6, 'pdf', 'Test tuz', questions='add')
    data['options']['question_count'] = 10
    body = bodies(data)[0]
    assert 'questions' in schema_of(body) and sent(body)['max_questions'] == 10
    assert 'asks for a test: return 10 questions' in sent(body)['writing_guidance']
    gone = changed(6, 'pptx', "Vaziyatli masalalarni va testlarni o'chir.", questions='remove')
    gone['content']['questions'] = [{'id': 'q1', 'stem': 'Savol?', 'options': ['A', 'B'], 'answer': 'A',
                                     'explanation': '', 'topic': 'Tarix', 'marks': 1}]
    body = bodies(gone)[0]
    assert 'questions' not in schema_of(body) and sent(body)['max_questions'] == 0
    assert sent(body)['outline']['questions'] == []
    assert 'removes the questions or tests' in sent(body)['writing_guidance']
    # A change that does not mention them keeps them, as before.
    kept = changed(6, 'pptx', "Imlosini to'g'rila.")
    kept['content']['questions'] = gone['content']['questions']
    assert 'questions' in schema_of(bodies(kept)[0]) and sent(bodies(kept)[0])['max_questions'] == 1


def test_a_test_asked_of_a_change_in_parts_is_written_by_the_last_part_from_the_whole_document():
    """"Test tuz" on a fifteen-slide deck: the first part had no questions field and was not told the test was
    another part's, and the last part wrote the test from its own five slides."""
    data = changed(15, request='Test tuz', questions='add')
    data['options']['question_count'] = 5
    first, last = bodies(data)
    assert 'questions' not in schema_of(first) and sent(first)['max_questions'] == 0
    assert ('The test is written by the last part of this change: do not write questions or a test slide here.'
            in sent(first)['writing_guidance'])
    assert 'questions' in schema_of(last) and 'return 5 questions' in sent(last)['writing_guidance']
    assert 'The test is written by the last part' not in sent(last)['writing_guidance']
    # A change that writes no test says nothing of it.
    assert 'The test is written' not in sent(bodies(changed(15, request="Ko'proq ma'lumot", expand=True))[0])[
        'writing_guidance']


@pytest.mark.django_db
def test_the_last_part_of_a_test_change_is_shown_what_the_earlier_parts_hold(monkeypatch):
    data = changed(15, request='Test tuz', questions='add')
    data['options']['question_count'] = 5
    calls = transport(monkeypatch, lambda body, number: answer(body))
    provider.generate(CONFIG, data, SLIDES, 'edit-test-in-parts', token_limit=200_000)
    first, second = (sent(body) for body in calls)
    assert 'already_written' not in first
    assert [entry['heading'] for entry in second['already_written']] == [f'Yangi s{n + 1}' for n in range(10)]
    assert all(entry['gist'] for entry in second['already_written'])
    assert 'already_written shows what the sections before this part say' in second['writing_guidance']
    # An ordinary change in parts is not given it: each part keeps its own sections.
    plain = changed(15, request="Ko'proq ma'lumot", expand=True)
    calls = transport(monkeypatch, lambda body, number: answer(body))
    provider.generate(CONFIG, plain, SLIDES, 'edit-expand-in-parts', token_limit=200_000)
    assert all('already_written' not in sent(body) for body in calls)


# --- Pages added, removed or moved ------------------------------------------------------------

def slot_plans(data):
    """Every part's slot_plan, in order, as one list of (slot id, what it holds)."""
    return [(row['id'], row['holds']) for body in bodies(data) for row in sent(body).get('slot_plan', [])]


def test_every_part_of_a_structural_change_sees_the_document_as_it_stands():
    data = changed(12, request="Boshiga bitta slayd qo'sh, unda mavzuning dolzarbligi haqida yoz", count=13,
                   delta=1, structural=True)
    calls = bodies(data)
    assert len(calls) == 2
    for body, (first, last) in zip(calls, pages.batches(13)):
        fields = sent(body)
        stands = fields['document_as_it_stands']
        assert stands['title'] == data['content']['title']
        assert [s['slide'] for s in stands['sections']] == list(range(1, 13))
        assert [s['heading'] for s in stands['sections']] == [f'Davlat {n}' for n in range(1, 13)]
        # The outline names the slots of the new deck; what fills them is in the document as it stands.
        assert fields['outline']['sections'] == [{'id': f's{n + 1}'} for n in range(first, last)]
        assert 'document_plan' not in fields
        guidance = fields['writing_guidance']
        assert 'It had 12 slides and has 13 after the change.' in guidance and 'where it had' not in guidance
        assert 'Slot 1 is always drawn as the cover.' in guidance
        assert f'This call writes slots {first + 1}-{last} of 13 only' in guidance
    # A slide added at the beginning of a deck goes right after the cover, and every part is told where each
    # slide went, so the second part does not have to guess what the first did.
    assert slot_plans(data) == [('s1', 'slide 1, the cover'), ('s2', 'new: a slide revision.request adds')] + [
        (f's{n + 1}', f'slide {n}') for n in range(2, 13)]
    # Each part carries whole only the slides that can land in it, and the rest in brief.
    first, second = (sent(body)['document_as_it_stands']['sections'] for body in calls)
    assert [s['slide'] for s in first if 'body' in s] == list(range(1, 10))
    assert [s['slide'] for s in second if 'body' in s] == [10, 11, 12]
    assert first[0]['notes'] == 'Izoh 1.' and second[0] == {'slide': 1, 'heading': 'Davlat 1',
                                                            'gist': 'Davlat 1 haqida matn.'}
    # Counted from the slides, too, when the reading did not flag it.
    data['revision']['edit']['structural'] = False
    assert 'document_as_it_stands' in sent(bodies(data)[0])
    # An ordinary change sends the outline as it is, and no copy of it.
    plain = changed(12, request="Ko'proq ma'lumot", expand=True)
    fields = sent(bodies(plain)[0])
    assert 'document_as_it_stands' not in fields and fields['outline']['sections'][1]['body'] == 'Davlat 2 haqida matn.'
    assert 'slot_plan' not in fields
    assert 'asks for more, fuller information' in fields['writing_guidance']


def test_a_change_that_names_the_slides_it_moves_reads_them_from_the_request():
    """Which slides go, or where a slide named by number goes, only the request's words say."""
    removed = changed(12, request="5-slaydni o'chir", count=11, delta=-1, structural=True)
    moved = changed(12, request="3-slayd bilan 4-slaydning o'rnini almashtir", structural=True)
    for data in (removed, moved):
        for body in bodies(data):
            fields = sent(body)
            assert 'slot_plan' not in fields
            assert 'the cover stays slot 1 and a slide added at the beginning goes right after it, in slot 2' in \
                fields['writing_guidance']
    # A smaller size named outright is reached by merging, not by dropping slides.
    smaller = changed(9, request='6 ta slayd qil', count=6, total=6, structural=True)
    guidance = sent(bodies(smaller)[0])['writing_guidance']
    assert ('It had 9 slides and has 6 after the change. It asks for 3 fewer: merge neighbouring body slides on the '
            'closest topics into one slide each, keeping their facts') in guidance
    assert 'fewer: merge' not in sent(bodies(removed)[0])['writing_guidance']
    # Moved slides can land anywhere, so every part carries the whole document.
    assert all('body' in s for body in bodies(moved) for s in sent(body)['document_as_it_stands']['sections'])
    # Removed ones only shift the rest up: the second part carries slides 10-12 whole and one either side.
    later = sent(bodies(removed)[1])['document_as_it_stands']['sections']
    assert [s['slide'] for s in later if 'body' in s] == [10, 11, 12]


def test_added_parts_are_named_with_where_they_go():
    data = changed(12, request="Reja ham bo'lsin kirish va xulosa qismi ham", count=15, delta=0,
                   parts=['plan', 'introduction', 'conclusion'], structural=True)
    data['revision']['before']['sections'][-1].update(heading='E’tiboringiz uchun rahmat', layout='closing')
    guidance = sent(bodies(data)[0])['writing_guidance']
    assert ('adds a plan, the list of the main parts in order; an introduction; a conclusion: each is a slide of its '
            'own with real content') in guidance
    assert 'a plan and an introduction come right after the cover' in guidance
    assert 'In a deck anything added at the beginning goes right after the cover, in slot 2' in guidance
    assert 'It had 12 slides and has 15 after the change.' in guidance
    assert slot_plans(data) == (
        [('s1', 'slide 1, the cover'), ('s2', 'new: the plan'), ('s3', 'new: the introduction')]
        + [(f's{n + 2}', f'slide {n}') for n in range(2, 12)] + [('s14', 'new: the conclusion'), ('s15', 'slide 12')])
    # "Boshiga reja qo'sh": the plan goes after the cover, never in its place.
    plan = changed(9, request="Boshiga reja qo'sh", count=10, parts=['plan'], structural=True)
    assert slot_plans(plan)[:3] == [('s1', 'slide 1, the cover'), ('s2', 'new: the plan'), ('s3', 'slide 2')]
    # A document's added page at the beginning is its first page.
    document = changed(6, 'pdf', request="Boshiga reja qo'sh", count=7, parts=['plan'], structural=True)
    assert slot_plans(document)[:2] == [('s1', 'new: the plan'), ('s2', 'page 1')]


@pytest.mark.parametrize('fmt,ceiling', [('pptx', 12), ('pdf', 15)])
def test_a_change_at_the_plan_limit_merges_neighbours_and_drops_nothing(fmt, ceiling):
    """"Reja ham bo'lsin kirish va xulosa qismi ham" on a twelve-slide deck at the free plan's twelve: told to add
    three slides, keep every slide and fit them all in twelve, the model dropped three slides whole, and the job
    succeeded without a warning."""
    unit = 'slide' if fmt == 'pptx' else 'page'
    data = changed(ceiling, fmt, "Reja ham bo'lsin kirish va xulosa qismi ham", count=ceiling,
                   parts=['plan', 'introduction', 'conclusion'], structural=True)
    data['revision']['before']['sections'][3]['body'] = 'Davlat 4 haqida matn. ' * 30
    if fmt == 'pptx':
        data['revision']['before']['sections'][-1].update(heading='E’tiboringiz uchun rahmat', layout='closing')
    calls = bodies(data)
    for body in calls:
        guidance = sent(body)['writing_guidance']
        assert (f'It had {ceiling} {unit}s and this change needs {ceiling + 3}, but it has room for {ceiling}, 3 '
                f'fewer: make room by merging 3 pairs of neighbouring body {unit}s into one {unit} each, keeping all '
                'their facts') in guidance
        assert 'where it had' not in guidance and 'now' not in guidance.split('revision.request changes')[1][:80]
    rows = slot_plans(data)
    assert [sid for sid, _ in rows] == [f's{n}' for n in range(1, ceiling + 1)]
    held = [int(n) for _, text in rows for n in re.findall(r'\d+', text.split(',')[0].split(':')[0])]
    # Every page of the document is in exactly one slot, the cover first and the last page last.
    assert sorted(held) == list(range(1, ceiling + 1))
    assert sum(text.startswith('new: ') for _, text in rows) == 3
    merged = [text for _, text in rows if 'merged into one' in text]
    assert len(merged) == 3
    # The shortest neighbours are merged: never the long fourth one, the cover or the last.
    assert not any(re.match(rf'{unit}s (?:\d+ and )?4\b|{unit}s 3 and 4', text) for text in merged)
    if fmt == 'pptx':
        assert rows[0] == ('s1', 'slide 1, the cover') and rows[-1] == (f's{ceiling}', f'slide {ceiling}')
        assert rows[-2] == (f's{ceiling - 1}', 'new: the conclusion')
    else:
        assert rows[0] == ('s1', 'new: the plan') and rows[-1] == (f's{ceiling}', 'new: the conclusion')


@pytest.mark.django_db
def test_a_model_that_follows_the_slot_plan_keeps_every_slide_at_the_plan_limit(monkeypatch):
    data = changed(12, request="Reja ham bo'lsin kirish va xulosa qismi ham", count=12,
                   parts=['plan', 'introduction', 'conclusion'], structural=True)
    data['revision']['before']['sections'][-1].update(heading='E’tiboringiz uchun rahmat', layout='closing')

    def follows(body, number):
        fields = sent(body)
        old = {s['slide']: s for s in fields['document_as_it_stands']['sections']}
        reply = answer(body)
        for section, row in zip(reply['sections'], fields['slot_plan']):
            numbers = [int(n) for n in re.findall(r'\d+', row['holds'].split(',')[0].split(':')[0])]
            if row['holds'].startswith('new: '):
                section.update(heading=row['holds'][5:], body='Yangi bo‘lim matni.')
            else:
                # Whole in this part: what it holds is there to copy.
                assert all('body' in old[n] for n in numbers), (row, number)
                section.update(heading=' / '.join(old[n]['heading'] for n in numbers),
                               body='\n'.join(old[n]['body'] for n in numbers))
        return reply

    transport(monkeypatch, follows)
    result, _ = provider.generate(CONFIG, data, SLIDES, 'edit-at-the-limit', token_limit=200_000)
    written = ' / '.join(s['heading'] for s in result['sections'])
    assert len(result['sections']) == 12
    for n in range(1, 12):
        assert f'Davlat {n}' in written
    assert 'E’tiboringiz uchun rahmat' == result['sections'][-1]['heading']
    assert [s['heading'] for s in result['sections']][1:3] == ['the plan', 'the introduction']
    assert result['sections'][-2]['heading'] == 'the conclusion'


def test_a_title_page_asked_of_a_deck_is_its_cover_and_of_a_document_its_dictated_lines():
    """"Boshiga bitta sahifa qo'sh va … deb yoz" on a deck: put in slot 1, drawn as the cover, the dictated lines
    showed at most as a subtitle and the old cover came second as a divider. On a document, the title page was
    told to be 577 words of prose."""
    from apps.studio.slide_layouts import TITLE_LINES
    request = "Boshiga bitta sahifa qo'sh va Karimova Dilnoza Rustam qizi 021-104-guruh deb yoz"
    deck = changed(9, request=request, parts=['title_page'])
    guidance = sent(bodies(deck)[0])['writing_guidance']
    assert ('revision.request asks for a title page: in a deck that is the cover itself, and it adds no slide. '
            'Slot 1 keeps layout cover and the deck title as its heading; its body is the subtitle line and then '
            'every line revision.request dictates for the title page, one per line, copied whole, at most '
            f'{TITLE_LINES} lines in all') in guidance
    assert 'Do not repeat the old cover on another slide.' in guidance
    assert 'is a slide of its own' not in guidance and 'document_as_it_stands' not in sent(bodies(deck)[0])
    # With another part: that one is a slide of its own, after the cover; the cover carries the lines.
    both = changed(9, request=request + " va reja qo'sh", count=10, parts=['title_page', 'plan'], structural=True)
    assert slot_plans(both)[:3] == [('s1', 'slide 1, the cover, with the title-page lines revision.request dictates'),
                                    ('s2', 'new: the plan'), ('s3', 'slide 2')]
    document = changed(6, 'pdf', request="Boshiga titul varag'ini qo'sh: MUSTAQIL ISH, Tayyorladi: Karimova Nodira",
                       count=7, parts=['title_page'], structural=True)
    guidance = sent(bodies(document)[0])['writing_guidance']
    assert ('revision.request adds a title page, whose body is only the lines the customer dictates for it, one per '
            'line, with nothing added, and whose heading is empty or the document title: it is a page of its own.'
            ) in guidance
    assert 'A body page the request adds, fills, rewrites or expands is written in full' in guidance
    assert slot_plans(document)[:2] == [('s1', 'new: the title page, only the lines revision.request dictates for it'),
                                        ('s2', 'page 1')]


# --- A new look ---------------------------------------------------------------------------------

def test_the_design_list_is_offered_only_to_a_change_that_asks_for_a_new_look():
    plain = changed(12)
    assert not deck_designs.wanted(plain)
    assert all(deck_designs.reference(False) not in body['instructions'] for body in bodies(plain))
    assert all('design' not in schema_of(body) for body in bodies(plain))
    restyled = changed(12, request='Varoqlarni hammasini bir xil qil', redesign=True)
    calls = bodies(restyled)
    assert deck_designs.wanted(restyled) and not deck_designs.wanted(restyled, 10)
    assert all(deck_designs.reference(False) in body['instructions'] for body in calls)
    assert len({body['instructions'] for body in calls}) == 1
    assert ['design' in schema_of(body) for body in calls] == [True, False]
    assert schema_of(calls[0])['design']['enum'] == deck_designs.DESIGN_IDS
    assert 'Choose the new look in the design field' in sent(calls[0])['writing_guidance']
    # Never for a selected-page change or a repair.
    picked = copy.deepcopy(restyled)
    picked['revision'].update(selected_section_ids=['s2'], base_content=copy.deepcopy(picked['content']))
    assert not deck_designs.wanted(picked)
    # A document asked for a new look may choose its design again.
    document = changed(6, 'pdf', 'Chiroyliroq dizayn qil', redesign=True)
    body = bodies(document)[0]
    assert doc_designs.reference(False, True, 0) in body['instructions'] and 'design' in schema_of(body)


@pytest.mark.parametrize('fmt', ['pdf', 'pptx'])
def test_a_change_that_asks_no_new_look_keeps_the_design_the_document_has(fmt):
    """A document made "chiroyli dizaynda" chose elegant; "Test tuz" then asked it to choose again, "plain unless
    the description asks for a style", and the change request asks for none: its look was gone."""
    data = changed(6, fmt, 'Test tuz', questions='add')
    data['options'].update(question_count=5, wants_design=True, wants_layouts=True,
                           template_style={'doc_design': 'elegant'} if fmt == 'pdf' else {'deck_design': 'gala'})
    wanted = doc_designs.wanted if fmt == 'pdf' else deck_designs.wanted
    assert not wanted(data)
    body = bodies(data)[0]
    assert 'design' not in schema_of(body)
    assert 'choose the look of the whole document' not in body['instructions']
    assert deck_designs.reference(False) not in body['instructions']
    if fmt == 'pdf':
        assert doc_designs.reference(True, False, 0) in body['instructions']
    # Asked for a new look, the first call of the whole change chooses it, and only that one.
    restyled = copy.deepcopy(data)
    restyled['revision']['edit']['redesign'] = True
    assert wanted(restyled) and not wanted(restyled, 10)
    assert 'design' in schema_of(bodies(restyled)[0])
    if fmt == 'pdf':
        assert doc_designs.reference(True, True, 0) in bodies(restyled)[0]['instructions']
    # Never a change to selected pages or a repair, whatever it asks.
    picked = copy.deepcopy(restyled)
    picked['revision'].update(selected_section_ids=['s2'], base_content=copy.deepcopy(picked['content']))
    repair = copy.deepcopy(restyled)
    repair['_stage'] = 'repair'
    for data in (picked, repair):
        assert not wanted(data) and 'design' not in schema_of(provider.request_body(CONFIG, data, FORMATS[fmt]))
    # A new document still chooses once, when its description asks for a look.
    new = draft(6, fmt)
    new['options'].update(wants_design=True)
    assert wanted(new) and not wanted(new, 10)
    new['options']['template_style'] = {'doc_design': 'elegant'} if fmt == 'pdf' else {'deck_design': 'gala'}
    assert not wanted(new)


def test_a_format_named_beside_a_change_spends_nothing_on_it():
    data = changed(6, request="Rasmlar qo'sh va PDF qilib yubor", pictures='add', format='pdf')
    data['options']['image_cap'] = 6
    assert 'handled outside this change' in sent(bodies(data)[0])['writing_guidance']


def test_the_instructions_stay_one_cached_prefix_for_every_part_and_language():
    data = changed(20, request='Har bir slaydda rasm', pictures='every')
    data['options']['image_cap'] = 12
    prefixes = set()
    for locale in ('en', 'uz', 'ru'):
        data['output_locale'] = locale
        for body in bodies(data):
            from apps.studio import language
            prefixes.add(body['instructions'][:-len(language.instructions(locale))])
    assert len(prefixes) == 1
    assert SELECTED_REVISION not in prefixes.pop()


# --- Through the provider boundary --------------------------------------------------------------

def answer(body, plan=True):
    """A strict-schema reply to whatever `body` asked for, with an edit plan when it was asked for one."""
    fields, properties = sent(body), schema_of(body)
    wanted = properties['sections']['items']['properties']
    deck = 'image_split' in (wanted.get('layout') or {}).get('enum', [])
    sections = []
    for section in fields['outline']['sections']:
        written = {'id': section['id'], 'heading': f'Yangi {section["id"]}', 'body': 'Yangi matn.'}
        if 'notes' in wanted:
            written['notes'] = ''
        if 'layout' in wanted:
            written.update(layout='bullets' if deck else 'text', items=[], columns=[], image_query='')
        sections.append(written)
    reply = {'answer_supported': True, 'sections': sections}
    for field, value in (('title', 'Yangi'), ('questions', []), ('citations', [])):
        if field in properties:
            reply[field] = value
    if 'design' in properties:
        reply['design'] = properties['design']['enum'][0]
    if 'edit_plan' in properties and plan:
        reply['edit_plan'] = [{'instruction': f"boshiga sahifa qo'sh ({fields['writing_this_part']})"
                               if 'writing_this_part' in fields else "boshiga sahifa qo'sh",
                               'sections': [sections[0]['id']]}]
    return reply


@pytest.mark.django_db
def test_a_reply_with_its_edit_plan_passes_strict_validation_and_keeps_the_plan(monkeypatch):
    data = changed(12, request="Boshiga bitta slayd qo'sh, unda mavzuning dolzarbligi haqida yoz", count=13,
                   delta=1, structural=True)
    calls = transport(monkeypatch, lambda body, number: answer(body))
    result, _ = provider.generate(CONFIG, data, SLIDES, 'edit-plan-offline', token_limit=200_000)
    assert len(calls) == 2
    assert [s['id'] for s in result['sections']] == [f's{n + 1}' for n in range(13)]
    assert [entry['instruction'] for entry in result['edit_plan']] == [
        "boshiga sahifa qo'sh (sections 1-10 of 13)", "boshiga sahifa qo'sh (sections 11-13 of 13)"]
    assert result['edit_plan'][1]['sections'] == ['s11']
    # Both parts see the document as it was; the second also what the first now holds.
    first, second = (sent(body) for body in calls)
    assert [s['heading'] for s in first['document_as_it_stands']['sections']] == \
        [s['heading'] for s in second['document_as_it_stands']['sections']]
    assert 'already_written' not in first
    assert [entry['heading'] for entry in second['already_written']] == [f'Yangi s{n + 1}' for n in range(10)]
    assert 'already_written shows what the earlier slots hold now' in second['writing_guidance']
    # The document itself is what the execution layer validates; the plan is not part of it.
    from apps.studio.domain import validate_content
    from tests.test_platform import account
    assert 'edit_plan' not in validate_content(account(), result, 'pptx')


@pytest.mark.django_db
def test_a_reply_that_left_out_or_misshaped_its_plan_is_still_the_document_paid_for(monkeypatch):
    data = changed(5, 'pdf', "Ko'proq ma'lumot", expand=True)

    def misshaped(body, number):
        reply = answer(body, plan=number != 1)
        if number == 2:
            reply['edit_plan'] = 'not a list'
        return reply

    transport(monkeypatch, misshaped)
    result, _ = provider.generate(CONFIG, data, DOCUMENT, 'edit-plan-missing', token_limit=200_000)
    assert 'edit_plan' not in result and len(result['sections']) == 5
    result, _ = provider.generate(CONFIG, data, DOCUMENT, 'edit-plan-misshaped', token_limit=200_000)
    assert 'edit_plan' not in result
    # A new document's reply may not carry one at all.
    fresh = draft(3)
    transport(monkeypatch, lambda body, number: {**answer(body), 'edit_plan': []})
    from apps.core.errors import DomainError
    with pytest.raises(DomainError, match='provider_failed'):
        provider.generate(CONFIG, fresh, DOCUMENT, 'edit-plan-uninvited', token_limit=200_000)


@pytest.mark.django_db
def test_a_selected_change_keeps_its_plan_beside_the_untouched_pages(monkeypatch):
    data = changed(5, request='Ikkinchi slaydni kengaytir')
    data['revision'].update(selected_section_ids=['s2'], base_content=copy.deepcopy(data['content']))
    data['revision'].pop('edit')
    transport(monkeypatch, lambda body, number: answer(body))
    result, _ = provider.generate(CONFIG, data, SLIDES, 'edit-plan-selected', token_limit=200_000)
    assert result['edit_plan'] == [{'instruction': "boshiga sahifa qo'sh", 'sections': ['s2']}]
    assert result['sections'][0] == data['content']['sections'][0]
    assert result['sections'][1]['body'] == 'Yangi matn.'


@pytest.mark.django_db
def test_a_retried_change_reuses_a_checkpoint_that_carries_its_plan(settings, monkeypatch):
    from apps.core.errors import DomainError
    from apps.core.models import Job
    from apps.core.services import submit_job
    from apps.studio import checkpoints
    from apps.studio.domain import create_draft, generation_quote, pack, unpack
    from apps.studio.models import GenerationDraft, ProviderCheckpoint
    from tests.test_prompt_assembly import _customer
    customer = _customer(settings)
    original = create_draft(customer, {'feature_id': DOCUMENT, 'prompt': 'A 12 page guide to tides.',
                                       'options': {'pages': 12}})
    finished = unpack(original.encrypted_data)
    for number, section in enumerate(finished['content']['sections'], 1):
        section.update(heading=f'Part {number}', body=f'What part {number} says about tides.')
    GenerationDraft.objects.filter(pk=original.pk).update(encrypted_data=pack(finished))
    change = create_draft(customer, {'prompt': 'Make every page fuller.',
                                     'options': {'revise_draft_id': str(original.id)}})
    data = unpack(change.encrypted_data)
    assert len(data['content']['sections']) == 12
    job, _ = submit_job(customer, generation_quote(customer, change.id, change.version).id, 'edit-plan-first')

    def flaky(body, number):
        if number in (2, 3):
            raise TimeoutError('offline simulated timeout')
        return answer(body)

    calls = transport(monkeypatch, flaky)
    with pytest.raises(DomainError, match='provider_failed'):
        provider.generate(CONFIG, data, job.feature_id, job.id, token_limit=200_000)
    assert ProviderCheckpoint.objects.filter(status='completed').count() == 1
    Job.objects.filter(pk=job.id).update(status='failed')
    retried, _ = submit_job(customer, checkpoints.retry_quote(customer, job.id).id, 'edit-plan-retry')
    result, _ = provider.generate(CONFIG, data, retried.feature_id, retried.id, token_limit=200_000)
    assert len(calls) == 4, 'only the missing part is asked for again'
    assert len(result['edit_plan']) == 2 and result['edit_plan'][0]['sections'] == ['s1']


# --- Through real drafts (apps/studio/edits.py and domain._prepare_draft read the request) -------

def _finished(customer, fmt, count, prompt, pictured=()):
    """A document the customer already has, written the way a model would have, with pictures on `pictured`."""
    from apps.studio.domain import create_draft, pack, unpack
    from apps.studio.models import GenerationDraft
    document = create_draft(customer, {'feature_id': FORMATS[fmt], 'prompt': prompt, 'options': {'pages': count}})
    data = unpack(document.encrypted_data)
    assert len(data['content']['sections']) == count
    for number, section in enumerate(data['content']['sections'], 1):
        section.update(heading=f'Davlat {number}', body=f'Davlat {number} qachon va kim tomonidan tashkil topgani.')
        if fmt == 'pptx':
            section.update(layout='cover' if number == 1 else 'bullets', items=[], columns=[], image_query='',
                           notes=f'Taqdimotchi izohi {number}.')
            if number in pictured:
                section.update(layout='image_split', image_query='ancient city ruins')
    GenerationDraft.objects.filter(pk=document.pk).update(encrypted_data=pack(data))
    return document


def _change(customer, document, request):
    from apps.studio.domain import create_draft, unpack
    return unpack(create_draft(customer, {'prompt': request,
                                          'options': {'revise_draft_id': str(document.id)}}).encrypted_data)


@pytest.fixture
def customer(settings, db):
    from operations.integrations import save_config
    from tests.test_prompt_assembly import _customer
    from tests.test_photos import KEY
    customer = _customer(settings)
    save_config('pixabay', {'pixabay_key': KEY, 'enabled': 'true'})
    return customer


DECK = "Eftaliylar, Xioniylar, Kidariylar va Turk xoqonligi haqida 12 slaydli taqdimot"


def test_a_plan_introduction_and_conclusion_are_three_slides_with_the_deck_rules(customer):
    data = _change(customer, _finished(customer, 'pptx', 12, DECK), "Reja ham bo'lsin kirish va xulosa qismi ham")
    assert data['revision']['edit']['parts'] == ['plan', 'introduction', 'conclusion']
    calls = bodies(data)
    assert len(data['content']['sections']) == 15 and len(calls) == 2
    for body in calls:
        assert REVISION_SYSTEM in body['instructions'] and DECK_RULES in body['instructions']
        assert layouts.reference(bool(data['options'].get('image_cap'))) in body['instructions']
        assert deck_designs.reference(bool(data['options'].get('image_cap'))) not in body['instructions']
        assert list(schema_of(body))[0] == 'edit_plan'
        fields = sent(body)
        assert len(fields['document_as_it_stands']['sections']) == 12
        assert 'adds a plan, the list of the main parts in order; an introduction; a conclusion' in \
            fields['writing_guidance']


def test_a_picture_on_every_slide_is_asked_for_on_every_slide(customer):
    from apps.core.policy import plan_limits
    data = _change(customer, _finished(customer, 'pptx', 12, DECK), "Har bir slaydda rasm bo'lsin")
    assert data['revision']['edit']['pictures'] == 'every' and len(data['content']['sections']) == 12
    cap = plan_limits(customer)['max_deck_images']
    assert data['options']['image_cap'] == cap
    shares = []
    for body, (first, last) in zip(bodies(data), pages.batches(12)):
        assert layouts.reference(True) in body['instructions']
        shares.append(added(sent(body)['writing_guidance'], 'pptx', first, last))
        assert 'document_as_it_stands' not in sent(body)
    assert sum(shares) == data['options']['images_wanted'] > 0


def test_pictures_added_to_a_deck_that_has_some_keep_them_and_add_more(customer):
    """"Jinoyatga oid rasmlar ham qo'sh" on a seven-slide deck with pictures on slides 3 and 5: told to "use 2
    photo layouts", which it had, the model added none."""
    data = _change(customer, _finished(customer, 'pptx', 7, DECK, pictured=(3, 5)), 'Jinoyatga oid rasmlar ham qoʻsh')
    assert data['revision']['edit']['pictures'] == 'add'
    wanted = data['options']['images_wanted']
    assert wanted > 2
    guidance = sent(bodies(data)[0])['writing_guidance']
    assert (f'Add a picture to {wanted - 2} more slide{"s" if wanted - 2 != 1 else ""} of this part that '
            f'{"have" if wanted - 2 != 1 else "has"} none') in guidance
    assert 'keep every picture these slides already have' in guidance


def test_making_every_slide_look_the_same_offers_the_design_list(customer):
    data = _change(customer, _finished(customer, 'pptx', 12, DECK), 'Varoqlarni hammasini bir xil qil')
    assert data['revision']['edit']['redesign'] is True
    assert 'deck_design' not in data['options']['template_style']
    calls = bodies(data)
    photos = bool(data['options'].get('image_cap'))
    assert all(deck_designs.reference(photos) in body['instructions'] for body in calls)
    assert ['design' in schema_of(body) for body in calls] == [True, False]


def test_make_a_test_gives_a_document_its_questions(customer):
    data = _change(customer, _finished(customer, 'pdf', 6, "Eftaliylar davlati haqida 6 betlik referat"), 'Test tuz')
    assert data['revision']['edit']['questions'] == 'add'
    body = bodies(data)[0]
    assert DOCUMENT_RULES in body['instructions']
    assert 'questions' in schema_of(body) and sent(body)['max_questions'] == data['options']['question_count'] == 10
    assert list(schema_of(body))[0] == 'edit_plan'


def test_a_page_at_the_beginning_with_dictated_text_goes_on_a_decks_cover_and_before_a_documents_first_page(
        customer):
    request = "Boshiga bitta sahifa qo'sh va Karimova Nodira 021-104-guruh deb yoz"
    data = _change(customer, _finished(customer, 'pptx', 12, DECK), request)
    # A deck's title page is its cover: no slide is added, and the cover carries the lines.
    assert data['revision']['edit']['parts'] == ['title_page'] and len(data['content']['sections']) == 12
    calls = bodies(data)
    assert len(calls) == 2
    first = sent(calls[0])
    assert first['revision']['request'] == request
    assert 'revision.request asks for a title page: in a deck that is the cover itself' in first['writing_guidance']
    assert 'copied exactly, complete and in their order' in calls[0]['instructions']
    document = _change(customer, _finished(customer, 'pdf', 6, "Eftaliylar davlati haqida 6 betlik referat"), request)
    assert document['revision']['edit']['structural'] is True and len(document['content']['sections']) == 7
    fields = sent(bodies(document)[0])
    assert len(fields['document_as_it_stands']['sections']) == 6
    assert fields['slot_plan'][:2] == [
        {'id': 's1', 'holds': 'new: the title page, only the lines revision.request dictates for it'},
        {'id': 's2', 'holds': 'page 1'}]
    assert 'whose body is only the lines the customer dictates for it' in fields['writing_guidance']
