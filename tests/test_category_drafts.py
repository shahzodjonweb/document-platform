"""A category draft in the domain: `options.category` from create to quote, PDF and deck (architecture 2.2).

A new draft may name a category of its own service that customers may pick
now. From then on the category is pinned, as a CV's way of being made is: a
save, the setup screen, the review's buttons, the answer to its one extra
question and a change all keep it, one naming another is refused, and a draft
made without one never gains one. A draft made while the switch was on still
saves and quotes after it is off. Its length and skeleton come from the
catalogue (skeleton.length, skeleton.seed), a paper's length is its pages and
not its parts, the quote carries the category and holds a paper to its pages,
and what the review says of its files and question is the server's.

A draft without a category is today's product exactly; the golden request
bodies (tests/test_prompt_golden.py) pin that.

The people and organisations here are invented.
"""
import copy
import io
import json
from dataclasses import asdict

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.errors import DomainError
from apps.core.models import FileAsset, Quote
from apps.core.services import upload_file
from apps.studio import categories, domain
from apps.studio.categories import catalogue, skeleton
from apps.studio.domain import (CV, DOCUMENT, SLIDES, create_draft, generation_quote, pack, unpack, update_draft,
                                validate_content)
from apps.studio.models import GenerationDraft
from operations.categories_settings import save as save_switch
from operations.integrations import save_config
from tests.test_operations import staff_client
from tests.test_platform import account, login_client
from tests.test_studio import paid
from tests.test_upload_ai_source import office_pages  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db

ARIZA = 'pdf.xat.ariza'     # length fixed at one page, topic false, no questions
TEST = 'pdf.test'           # length derived from its questions, topic true
HIMOYA = 'slides.himoya'    # length by count and cue, a default look, a review question, head_tail sources
EVERY = [ARIZA, TEST, HIMOYA]

DEFENCE = 'Kurs ishi himoyasi: "Kichik biznesda raqamli marketing". Muallif: Laylo Rahimova, 3-kurs.'
APPLICATION = ('“Yashil vodiy” MChJ direktori Botir Qodirovga ariza: 10-dekabrdan 5 kunlik mehnat ta’tili '
               'so‘rayman. Arizachi: Nodira Saidova, buxgalter.')
QUIZ = 'Biologiya, 7-sinf, fotosintez mavzusida 20 ta savollik test.'


@pytest.fixture
def ready(monkeypatch):
    """The catalogue with the three examples marked ready, as N1 and N2 will mark entries."""
    return marked(monkeypatch, 'ready')


def marked(monkeypatch, status, *, drop=()):
    entries, templates, index = copy.deepcopy(catalogue.read())
    for name in drop:
        entries.pop(name)
        for group in index['groups'].values():
            group['children'] = [child for child in group['children'] if child != name]
        for feature, items in index['lists'].items():
            index['lists'][feature] = [item for item in items if item != name]
        for template in templates.values():
            template['entries'] = [item for item in template['entries'] if item != name]
    if drop:
        # The entries after a dropped one move up a place in the owner's list, as they would if its file were
        # gone, so the catalogue's order check still holds when the entry has neighbours.
        for items in [*index['lists'].values(), *(group['children'] for group in index['groups'].values())]:
            for position, item in enumerate(items, 1):
                if item in entries:
                    entries[item]['order'] = position
    for raw in entries.values():
        raw['status'] = status
    made = catalogue.build(entries, {name: raw for name, raw in templates.items() if raw['entries']}, index)
    monkeypatch.setattr(catalogue, '_catalogue', lambda: made)
    return made


@pytest.fixture
def switch(ready):
    """Turns the switch on with these categories ticked, as the owner does on /ops/categories."""
    _, user = staff_client('Operations')

    def turn(on=True, live=tuple(EVERY)):
        save_switch({'on': 'true' if on else 'false', 'live': list(live)}, user)
    turn()
    return turn


@pytest.fixture
def customer(settings):
    settings.DEBUG = True
    # With a model to write them, a draft's sections are its skeleton's; local authoring is tried on its own below.
    save_config('ai', {'mode': 'openai', 'model': 'gpt-5.6-luna', 'api_key': 'sk-offline-test-only'})
    return paid(settings, account(77801))


def drafted(who, category, prompt, fid=None, **options):
    fid = fid or categories.get(category).feature_id
    draft = create_draft(who, {'feature_id': fid, 'prompt': prompt, 'options': {'category': category, **options}})
    return draft, unpack(draft.encrypted_data)


def saved(who, draft, **fields):
    draft.refresh_from_db()
    draft = update_draft(who, draft.id, {'version': draft.version, **fields})
    return draft, unpack(draft.encrypted_data)


def refusal(call, *args, **kwargs):
    with pytest.raises(DomainError) as refused:
        call(*args, **kwargs)
    return refused.value


def stored(draft, change):
    """Write `change(data)` into the draft as the job would, outside update_draft."""
    draft.refresh_from_db()
    data = unpack(draft.encrypted_data)
    change(data)
    GenerationDraft.objects.filter(pk=draft.pk).update(encrypted_data=pack(data))
    draft.refresh_from_db()
    return draft


def text_upload(who, name, text):
    return upload_file(who, SimpleUploadedFile(name, text.encode('utf-8')), 'bot', purpose='ai_source')


def pdf(*pages):
    """A PDF with these lines of text, one page each; an empty string is a page with no text layer (a scan)."""
    from reportlab.pdfgen.canvas import Canvas
    raw = io.BytesIO()
    canvas = Canvas(raw)
    for text in pages:
        if text:
            canvas.drawString(45, 700, text)
        canvas.showPage()
    canvas.save()
    return raw.getvalue()


# ------------------------------------------------------------------ which category a new draft may have


def test_a_new_draft_names_a_category_of_its_own_service_or_is_refused(customer, switch):
    for fid, category in ((SLIDES, ARIZA), (DOCUMENT, HIMOYA), (CV, ARIZA), (DOCUMENT, 'pdf.nothing'),
                          (DOCUMENT, 'other'), (DOCUMENT, 5), (DOCUMENT, ['pdf.test'])):
        assert refusal(create_draft, customer, {'feature_id': fid, 'prompt': APPLICATION,
                                                'options': {'category': category}}).code == 'invalid_parameters'
    draft, data = drafted(customer, ARIZA, APPLICATION)
    assert draft.feature_id == DOCUMENT and data['options']['category'] == ARIZA
    # An explicit null is no category: today's draft, without the key.
    data = unpack(create_draft(customer, {'feature_id': DOCUMENT, 'prompt': 'Suvning aylanishi haqida referat',
                                          'options': {'category': None}}).encrypted_data)
    assert 'category' not in data['options']


def test_a_new_draft_needs_the_switch_on_and_its_category_ticked_and_ready(customer, switch, monkeypatch):
    switch(on=False)
    assert refusal(drafted, customer, HIMOYA, DEFENCE).code == 'category_unavailable'
    switch(live=[ARIZA])
    assert refusal(drafted, customer, HIMOYA, DEFENCE).code == 'category_unavailable'
    assert drafted(customer, ARIZA, APPLICATION)[1]['options']['category'] == ARIZA
    # Ticked while ready, then sent back to draft by a deploy: no longer offered, so no new draft.
    marked(monkeypatch, 'draft')
    error = refusal(drafted, customer, ARIZA, APPLICATION)
    assert (error.code, error.status) == ('category_unavailable', 409)


def test_a_draft_made_while_on_still_saves_and_quotes_once_the_switch_is_off_or_its_entry_retired(
        customer, switch, monkeypatch):
    draft, _ = drafted(customer, HIMOYA, DEFENCE)
    switch(on=False)
    draft, data = saved(customer, draft, options={**unpack(draft.encrypted_data)['options'], 'pages': 8})
    assert data['options']['category'] == HIMOYA and data['options']['length'] == 8
    assert generation_quote(customer, draft.id, draft.version).parameters['category'] == HIMOYA
    marked(monkeypatch, 'retired')
    draft, data = saved(customer, draft, title='Raqamli marketing')
    assert data['options']['category'] == HIMOYA
    assert generation_quote(customer, draft.id, draft.version).parameters['category'] == HIMOYA


def test_an_id_the_catalogue_no_longer_holds_fails_before_anything_is_quoted(customer, switch, monkeypatch):
    draft, _ = drafted(customer, ARIZA, APPLICATION)
    marked(monkeypatch, 'ready', drop=[ARIZA])
    error = refusal(generation_quote, customer, draft.id, draft.version)
    assert (error.code, error.status) == ('category_unknown', 500)
    assert refusal(saved, customer, draft, title='Ariza').code == 'category_unknown'
    assert not Quote.objects.filter(parameters__generation_draft_id=str(draft.id)).exists()


# ------------------------------------------------------------------ pinned on every path


def test_the_category_is_pinned_through_a_save_the_setup_screen_and_the_review_buttons(customer, switch):
    from telegram import generation as bot_generation
    draft, data = drafted(customer, HIMOYA, DEFENCE)
    # A client that leaves it out (a save that replaces options whole) gets it back.
    draft, data = saved(customer, draft, options={'pages': 7})
    assert data['options']['category'] == HIMOYA and data['options']['length'] == 7
    assert refusal(saved, customer, draft, options={'category': 'slides.other_one'}).code == 'invalid_parameters'
    # The setup screen merges the stored options and keeps it.
    response = login_client(customer).post(f'/api/v1/generation/drafts/{draft.id}/setup',
                                           data=json.dumps({'pages': 9, 'deck_design': 'midnight'}),
                                           content_type='application/json')
    assert response.status_code == 200, response.content
    assert response.json()['draft']['options']['category'] == HIMOYA
    draft, _ = bot_generation.resize(customer, draft.id, 11)
    data = unpack(draft.encrypted_data)
    assert data['options']['category'] == HIMOYA and data['options']['length'] == 11
    assert len(data['content']['sections']) == 11


def test_a_draft_made_without_a_category_never_gains_one(customer, switch):
    draft = create_draft(customer, {'feature_id': DOCUMENT, 'prompt': 'Suvning aylanishi haqida 3 betlik referat'})
    assert refusal(saved, customer, draft, options={'category': ARIZA}).code == 'invalid_parameters'
    assert 'category' not in saved(customer, draft, title='Suv')[1]['options']


def test_server_owned_keys_are_stripped_and_details_added_is_set_once_by_the_answer(customer, switch):
    draft, data = drafted(customer, HIMOYA, DEFENCE, details_added=True, unread_sources=['x'], sources_cut=True)
    assert not {'details_added', 'unread_sources', 'sources_cut'} & set(data['options'])
    # The bot appends the answer to the prompt and saves it as the answer.
    answer = f"{DEFENCE}\nNatijalar: savdo 18% oshdi, 240 nafar mijoz so‘rovnomada qatnashdi."
    draft.refresh_from_db()
    draft = update_draft(customer, draft.id, {'version': draft.version, 'prompt': answer}, details=True)
    data = unpack(draft.encrypted_data)
    assert data['options']['details_added'] is True and data['prompt'] == answer
    # Kept by every later save, even one that sends it away.
    options = {key: value for key, value in data['options'].items() if key != 'details_added'}
    draft, data = saved(customer, draft, options={**options, 'pages': 8})
    assert data['options']['details_added'] is True
    # Answered once.
    draft.refresh_from_db()
    assert refusal(update_draft, customer, draft.id, {'version': draft.version, 'prompt': answer + ' Yana.'},
                   details=True).code == 'invalid_parameters'
    # Only a category draft has the question.
    plain = create_draft(customer, {'feature_id': SLIDES, 'prompt': 'Fotosintez haqida 8 ta slayd'})
    assert refusal(update_draft, customer, plain.id, {'version': plain.version, 'prompt': 'Fotosintez, 8 slayd'},
                   details=True).code == 'invalid_parameters'


# ------------------------------------------------------------------ length and skeleton


def test_a_category_paper_is_its_skeleton_and_its_length_is_its_pages(customer, switch):
    entry = categories.get(ARIZA)
    _, data = drafted(customer, ARIZA, APPLICATION + ' 3 betlik', pages=4)
    # An ariza is one page whatever is asked; the parts are its written parts, after the facts section.
    assert data['options']['length'] == 1 and data['options']['requested_pages'] is None
    assert data['options']['question_count'] == 0 and data['options']['image_cap'] == 0
    written = [use.section_id for use in skeleton.parts(entry, 1, frozenset()) if use.section_id]
    assert [s['id'] for s in data['content']['sections']] == ['facts', *written] == [
        'facts', 'request', 'statements', 'enclosures']
    assert [(s.get('layout', 'text'), s['heading'], s['body']) for s in data['content']['sections']] == [
        ('list', '', ''), ('text', '', ''), ('list', '', ''), ('list', '', '')]
    # A test is as long as its questions need: the default twenty, or the count the brief names.
    _, data = drafted(customer, TEST, 'Biologiya, 7-sinf, fotosintez mavzusida test.')
    assert (data['options']['question_count'], data['options']['length']) == (20, 4)
    _, data = drafted(customer, TEST, 'Biologiya, 7-sinf, fotosintez mavzusida 35 ta savollik test.')
    assert (data['options']['question_count'], data['options']['length']) == (35, 5)


def test_a_category_deck_takes_its_cue_length_writes_it_for_the_setup_screen_and_starts_in_its_look(customer, switch):
    draft, data = drafted(customer, HIMOYA, DEFENCE)
    entry = categories.get(HIMOYA)
    assert skeleton.cues_of(data) == {'kurs'}
    # The count came from the entry, not the customer: nothing to say was cut.
    assert data['options']['length'] == data['options']['pages'] == 6 and data['options']['requested_pages'] is None
    slots = skeleton.slots(entry, 6, frozenset({'kurs'}))
    assert [(s['id'], s['layout']) for s in data['content']['sections']] == [
        (f's{n}', slot['layouts'][0]) for n, slot in enumerate(slots, 1)]
    assert data['options']['template_style']['deck_design'] == entry.look['designs'][0]
    assert 'deck_design' not in data['options'], 'a look, never a pick the customer made'
    # The setup screen sends the count it shows; a design picked there replaces the default look.
    shown = data['options']['pages']
    response = login_client(customer).post(f'/api/v1/generation/drafts/{draft.id}/setup',
                                           data=json.dumps({'pages': shown, 'deck_design': 'midnight'}),
                                           content_type='application/json')
    assert response.status_code == 200, response.content
    options = response.json()['draft']['options']
    assert options['length'] == 6 and options['template_style']['deck_design'] == 'midnight'
    # A count named in the brief wins and is the brief's, so nothing is written for it.
    _, data = drafted(customer, HIMOYA, DEFENCE + ' 12 ta slayd.')
    assert data['options']['length'] == 12 and 'pages' not in data['options']
    # A colour named still applies over the look.
    _, data = drafted(customer, HIMOYA, DEFENCE + ' Yashil rangda.')
    style = data['options']['template_style']
    assert style['deck_design'] == entry.look['designs'][0] and style.get('accent_fixed') is True


def test_an_answer_that_adds_a_cue_seeds_the_slots_it_now_gives(customer, switch):
    entry = categories.get(HIMOYA)
    draft, data = drafted(customer, HIMOYA, 'Himoya uchun slaydlar: "Kichik biznesda raqamli marketing".', pages=15)
    assert skeleton.cues_of(data) == frozenset() and data['options']['length'] == 15
    before = [s['layout'] for s in data['content']['sections']]
    draft.refresh_from_db()
    draft = update_draft(customer, draft.id, {'version': draft.version, 'prompt': data['prompt']
                                              + '\nBu magistrlik dissertatsiyasi himoyasi.'}, details=True)
    data = unpack(draft.encrypted_data)
    assert skeleton.cues_of(data) == {'masters'} and data['options']['length'] == 15, 'the count it was given stays'
    after = [s['layout'] for s in data['content']['sections']]
    assert after == [slot['layouts'][0] for slot in skeleton.slots(entry, 15, frozenset({'masters'}))] != before


def test_local_authoring_puts_the_customers_words_in_the_first_elastic_part(customer, switch):
    save_config('ai', {'mode': 'local_fixture'})
    _, data = drafted(customer, ARIZA, APPLICATION)
    request = next(s for s in data['content']['sections'] if s['id'] == 'request')
    assert request['body'] == APPLICATION and data['options']['length'] == 1
    # A deck keeps its length; its paragraphs are not its slides.
    _, data = drafted(customer, HIMOYA, DEFENCE)
    assert data['options']['length'] == 6 and data['content']['sections'][0]['body'] == DEFENCE


def test_the_topic_question_runs_only_for_a_category_that_has_one(customer, switch):
    # An ariza is about itself: its description names no subject, and needs none.
    assert drafted(customer, ARIZA, 'Ariza kerak')[1]['options']['category'] == ARIZA
    assert refusal(drafted, customer, HIMOYA, '10 ta slayd kk').code == 'topic_required'
    assert drafted(customer, HIMOYA, '10 ta slayd kk', topic_given=True)[1]['options']['category'] == HIMOYA


# ------------------------------------------------------------------ bounds at create and at save


def test_a_category_paper_is_held_to_the_paper_bounds_and_stores_no_columns(customer, switch):
    many = [{'id': f'p{n}', 'heading': '', 'body': 'Matn.'} for n in range(1, 56)]
    rows = {'id': 'prices', 'heading': '', 'body': '', 'layout': 'table', 'columns': ['Nomi', 'Soni', 'Narxi'],
            'items': [{'label': f'Mahsulot {n}', 'text': f'{n} dona', 'value': f'{n}000'} for n in range(1, 36)]}
    content = {'title': 'Taklif', 'sections': [rows, *many]}
    paper = validate_content(customer, content, 'pdf', category=categories.PAPER_BOUNDS)
    assert len(paper['sections']) == 56 and len(paper['sections'][0]['items']) == 35
    assert paper['sections'][0]['columns'] == []
    plain = validate_content(customer, content, 'pdf')
    assert len(plain['sections']) == domain.limits(customer)['sections'] < 56
    assert len(plain['sections'][0]['items']) == 16 and plain['sections'][0]['columns'] == ['Nomi', 'Soni', 'Narxi']
    # The save site holds a paper to the same bounds; a document keeps today's.
    draft, data = drafted(customer, ARIZA, APPLICATION)
    sections = copy.deepcopy(data['content']['sections'])
    sections[2] = {**sections[2], 'layout': 'list', 'items': [{'label': f'{n}', 'text': f'Ilova {n}'} for n in range(30)]}
    draft, data = saved(customer, draft, content={**data['content'], 'sections': sections})
    assert len(data['content']['sections'][2]['items']) == 30
    # Its length stays its pages, not its parts.
    assert data['options']['length'] == 1


def test_a_papers_outline_is_not_the_clients_to_edit_and_a_decks_is(customer, switch):
    draft, data = drafted(customer, ARIZA, APPLICATION)
    outline = [{'id': s['id'], 'title': 'Sarlavha', 'body': ''} for s in data['content']['sections']]
    assert refusal(saved, customer, draft, outline=outline).code == 'invalid_parameters'
    draft, data = drafted(customer, HIMOYA, DEFENCE)
    outline = [{'id': s['id'], 'title': f'Slayd {n}', 'body': '', 'layout': s['layout']}
               for n, s in enumerate(data['content']['sections'], 1)]
    _, data = saved(customer, draft, outline=outline)
    assert data['content']['sections'][1]['heading'] == 'Slayd 2' and data['options']['category'] == HIMOYA


# ------------------------------------------------------------------ the quote and the outline stage


def test_the_quote_carries_the_category_and_holds_a_paper_to_its_pages(customer, switch):
    from apps.studio.provider import call_budget
    draft, data = drafted(customer, ARIZA, APPLICATION)
    quote = generation_quote(customer, draft.id, draft.version)
    assert quote.parameters['category'] == ARIZA
    assert len(data['content']['sections']) == 4 and quote.policy['generation_bounds']['output_pages'] == 2
    assert quote.policy['lease_seconds'] == call_budget(1) + 240
    draft, data = drafted(customer, HIMOYA, DEFENCE)
    quote = generation_quote(customer, draft.id, draft.version)
    assert quote.parameters['category'] == HIMOYA and quote.policy['generation_bounds']['output_pages'] == 7
    plain = create_draft(customer, {'feature_id': DOCUMENT, 'prompt': 'Suvning aylanishi haqida 3 betlik referat'})
    assert 'category' not in generation_quote(customer, plain.id, plain.version).parameters


def test_a_category_paper_has_no_outline_stage_and_a_deck_plans_on_its_category(customer, switch):
    from apps.studio.outlines import _payload, create_outline_quote
    draft, _ = drafted(customer, ARIZA, APPLICATION)
    assert refusal(create_outline_quote, customer, draft.id, draft.version).code == 'invalid_parameters'
    assert not Quote.objects.filter(parameters__generation_draft_id=str(draft.id)).exists()
    draft, data = drafted(customer, HIMOYA, DEFENCE)
    assert _payload(data)['options']['category'] == HIMOYA
    plain = create_draft(customer, {'feature_id': SLIDES, 'prompt': 'Fotosintez haqida 8 ta slayd'})
    assert 'category' not in _payload(unpack(plain.encrypted_data))['options']


# ------------------------------------------------------------------ a change


def made(draft, sections=None, questions=0):
    """The draft as a generated document: what revision_source finds (premium has no weekly limit to check)."""
    def write(data):
        if sections is not None:
            data['content']['sections'] = sections(data['content']['sections'])
        data['content']['questions'] = [{'id': f'q{n}', 'stem': f'Savol {n}?', 'options': ['Ha', 'Yo‘q'],
                                         'answer': 'Ha', 'explanation': '', 'topic': 'Fotosintez', 'marks': 1}
                                        for n in range(1, questions + 1)]
    return stored(draft, write)


def written(sections):
    return [{**s, 'body': s['body'] or f'{s["id"]} matni.'} for s in sections]


def test_a_change_inherits_the_category_and_keeps_a_papers_parts_and_pages(customer, switch):
    source, before = drafted(customer, ARIZA, APPLICATION)
    source = made(source, written)
    switch(on=False)  # a change of a document made while on is still that document's change
    change = create_draft(customer, {'prompt': 'Yana ikki sahifa qo‘shing va rasmlar qo‘ying',
                                     'options': {'revise_draft_id': str(source.id)}})
    data = unpack(change.encrypted_data)
    assert data['options']['category'] == ARIZA
    assert [s['id'] for s in data['content']['sections']] == [s['id'] for s in before['content']['sections']]
    assert data['options']['length'] == 1 and data['options']['image_cap'] == 0
    assert generation_quote(customer, change.id, change.version).parameters['category'] == ARIZA
    assert refusal(create_draft, customer, {'prompt': 'Qisqaroq qiling', 'options': {
        'revise_draft_id': str(source.id), 'category': TEST}}).code == 'invalid_parameters'
    # A saved change keeps it too.
    change, data = saved(customer, change, prompt='Yana bir sahifa qo‘shing')
    assert data['options']['category'] == ARIZA and data['options']['length'] == 1


def test_a_change_to_a_test_follows_its_questions(customer, switch):
    source, _ = drafted(customer, TEST, QUIZ)
    source = made(source, written, questions=20)
    data = unpack(create_draft(customer, {'prompt': "Yana 10 ta savol qo'sh",
                                          'options': {'revise_draft_id': str(source.id)}}).encrypted_data)
    assert (data['options']['question_count'], data['options']['length']) == (30, 5)
    data = unpack(create_draft(customer, {'prompt': 'Imlo xatolarini tuzating',
                                          'options': {'revise_draft_id': str(source.id)}}).encrypted_data)
    assert data['options']['length'] == 4, 'twenty questions kept, as many pages'


def test_a_change_to_a_paper_asks_the_categorys_reader_first_and_a_deck_never(customer, switch, monkeypatch):
    from apps.studio import edits as editing
    from apps.studio.categories import edits as category_edits
    asked = []

    def read(request, entry, **context):
        asked.append((request, entry.id, sorted(context)))
        return editing.Edit(expand=True) if 'kengaytir' in request else None
    monkeypatch.setattr(category_edits, 'read', read)
    source, _ = drafted(customer, ARIZA, APPLICATION)
    source = made(source, written)
    data = unpack(create_draft(customer, {'prompt': 'Batafsil kengaytiring',
                                          'options': {'revise_draft_id': str(source.id)}}).encrypted_data)
    assert asked == [('Batafsil kengaytiring', ARIZA, ['fmt', 'questions', 'sections'])]
    assert data['revision']['edit']['expand'] is True
    # None is today's reading.
    data = unpack(create_draft(customer, {'prompt': 'Rasmiyroq yozing',
                                          'options': {'revise_draft_id': str(source.id)}}).encrypted_data)
    assert data['revision']['edit'] == asdict(editing.read('Rasmiyroq yozing', fmt='pdf',
                                                                    sections=data['revision']['before']['sections']))
    deck, _ = drafted(customer, HIMOYA, DEFENCE)
    deck = made(deck, written)
    asked.clear()
    data = unpack(create_draft(customer, {'prompt': "Yana 2 ta slayd qo'sh",
                                          'options': {'revise_draft_id': str(deck.id)}}).encrypted_data)
    assert asked == [] and data['options']['category'] == HIMOYA and data['options']['length'] == 8


# ------------------------------------------------------------------ sources


def test_a_category_draft_reads_word_and_text_files_and_says_which_it_could_not(customer, switch, office_pages,
                                                                                 monkeypatch):
    from docx import Document
    raw = io.BytesIO()
    document = Document()
    document.add_paragraph('Kirish. Kichik biznesda raqamli marketing savdoni oshiradi.')
    document.add_paragraph('Xulosa. So‘rovnomada 240 nafar mijoz qatnashdi.')
    document.save(raw)
    thesis = upload_file(customer, SimpleUploadedFile('ish.docx', raw.getvalue()), 'bot', purpose='ai_source')
    scan = upload_file(customer, SimpleUploadedFile('skan.pdf', pdf('')), 'bot', purpose='ai_source')
    draft = create_draft(customer, {'feature_id': SLIDES, 'prompt': DEFENCE, 'source_ids': [str(thesis.id), str(scan.id)],
                                    'options': {'category': HIMOYA}})
    data = unpack(draft.encrypted_data)
    assert {item['asset_id'] for item in data['excerpts']} == {str(thesis.id)}
    assert 'raqamli marketing' in data['excerpts'][0]['text']
    assert data['options']['unread_sources'] == [str(scan.id)] and 'sources_cut' not in data['options']
    # A tap on the review does not read the files again, and still says so.
    from apps.studio import extraction
    reads = []
    monkeypatch.setattr(extraction, 'read_source', lambda *args, **kwargs: reads.append(args))
    monkeypatch.setattr(extraction, 'extract_pages', lambda *args, **kwargs: reads.append(args))
    draft, data = saved(customer, draft, options={**data['options'], 'pages': 7})
    assert reads == [] and data['options']['unread_sources'] == [str(scan.id)]
    # A document without a category reads PDFs only, as today.
    assert refusal(create_draft, customer, {'feature_id': DOCUMENT, 'prompt': 'Shu ish asosida referat',
                                            'source_ids': [str(thesis.id)]}).code == 'unsupported_file'


def test_a_thesis_too_long_for_the_request_keeps_its_ends_and_the_draft_says_so(customer, switch, monkeypatch):
    long_text = '\n'.join(f'{number}-bo‘lim. ' + 'Tadqiqot natijalari kichik biznes uchun muhim. ' * 60
                          for number in range(1, 13))
    thesis = text_upload(customer, 'ish.txt', long_text)
    real = domain.limits
    monkeypatch.setattr(domain, 'limits', lambda who: {**real(who), 'source_chars': 9000})
    draft = create_draft(customer, {'feature_id': SLIDES, 'prompt': DEFENCE, 'source_ids': [str(thesis.id)],
                                    'options': {'category': HIMOYA}})
    data = unpack(draft.encrypted_data)
    assert data['options']['sources_cut'] is True and 'unread_sources' not in data['options']
    assert sum(len(item['text']) for item in data['excerpts']) <= 9000 - len(DEFENCE)
    pages = [item['page'] for item in data['excerpts']]
    assert pages[0] == 1 and pages[-1] == thesis.page_count


def test_a_drawn_category_deck_is_saved_without_its_files_being_read_or_looked_for(customer, switch):
    thesis = text_upload(customer, 'ish.txt', 'Kirish. Kichik biznesda raqamli marketing savdoni oshiradi. ' * 5)
    draft = create_draft(customer, {'feature_id': SLIDES, 'prompt': DEFENCE, 'source_ids': [str(thesis.id)],
                                    'options': {'category': HIMOYA}})
    before = unpack(draft.encrypted_data)['excerpts']
    draft = stored(draft, lambda data: data.update(_render={'design': 'boardroom', 'deck_seed': 1}))
    FileAsset.objects.filter(pk=thesis.pk).delete()
    draft, data = saved(customer, draft, title='Raqamli marketing')
    assert data['excerpts'] == before and data['options']['category'] == HIMOYA
