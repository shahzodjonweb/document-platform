"""A generated deck keeps what draws it again exactly: its pins, with its draft.

A manual edit will redraw the deck from these, changing only the slide it
touches and asking neither the model nor Pixabay (conftest fails any test that
reaches either). Nothing a customer sees changes yet: no endpoint uses the pins,
generation draws what it always drew, and a draft without pins keeps working.
"""
import copy
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import uuid
import zipfile
from datetime import timedelta

import pytest
from PIL import Image
from django.conf import settings as django_settings
from django.utils import timezone

from apps.core import storage
from apps.core.errors import DomainError
from apps.core.models import FileAsset, Job, Quote, StoredObject
from apps.core.services import cleanup_expired, execute_job, settle_job, submit_job
from apps.studio import checkpoints, deck_designs, execution, photos as stock, provider, variants
from apps.studio.branding import render_style
from apps.studio.domain import (DOCUMENT, SLIDES, create_draft, draft_data, draft_jobs, generation_quote, pack, unpack, update_draft,
                                validate_generation_quote)
from apps.studio.models import GenerationDraft
from apps.studio.outlines import create_outline_quote
from apps.studio.slides import render_pptx
from apps.studio.variants import CLASSIC, fixtures
from operations.integrations import ai_config, save_config
from telegram.generation import resize
from tests.test_object_storage import bucket  # noqa: F401
from tests.test_operations_admin import staff_client
from tests.test_page_fill import live
from tests.test_photos import _run as run_paid_deck, hit, model, paid_deck, pixabay, slides  # noqa: F401
from tests.test_platform import account, login_client, upload
from tests.test_studio import paid

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def deck_editor_on(monkeypatch):
    monkeypatch.setenv('EDITOR_FLAG_DECK_EDITOR', '1')

TITLE = 'Harbour logistics review'
DESIGN = 'midnight'
# Slide ids in the deck below, by what they are.
COVER, CARDS, MORE_CARDS, STEPS, LIST, PHOTO, FIGURES, WORDS = 's1', 's2', 's3', 's4', 's5', 's6', 's7', 's8'
PHOTO_SLIDES = (COVER, PHOTO)


def deck_sections():
    """Two slides of one layout, so a second variant has to be chosen; a photo on the cover and on one slide."""
    made = [{'id': COVER, 'heading': 'Harbour logistics', 'body': 'Spring review', 'layout': 'cover',
             'image_query': 'harbour cranes'}]
    for section_id, kind, count in ((CARDS, 'cards', 3), (MORE_CARDS, 'cards', 3), (STEPS, 'process', 4), (LIST, 'bullets', 3),
                                    (PHOTO, 'image_split', 3), (FIGURES, 'stats', 3), (WORDS, 'quote', 1)):
        made.append({**fixtures.light(kind, count), 'id': section_id})
    return made


def questions(count=7):
    """Seven questions make two question slides, after the sections."""
    return [{'id': f'q{n}', 'stem': f'Which pier takes the bulk carriers, case {n}?', 'options': ['North', 'South'],
             'answer': 'North', 'marks': 1} for n in range(1, count + 1)]


def deck_draft(customer, sections=None, asked=None, title=TITLE, design=DESIGN):
    sections = deck_sections() if sections is None else sections
    options = {'pages': len(sections), **({'deck_design': design} if design else {})}
    draft = create_draft(customer, {'feature_id': SLIDES, 'title': title, 'source_text': 'Notes about the harbour.', 'options': options})
    return update_draft(customer, draft.id, {'version': draft.version, 'content': {
        'title': title, 'sections': sections, 'questions': questions() if asked is None else asked, 'citations': []}})


def run(customer, draft):
    quote = generation_quote(customer, draft.id, draft.version)
    job, _ = submit_job(customer, quote.id, f'deck-{quote.id}')
    return execute_job(job.id)


def generate(customer, **kwargs):
    """A deck made the way a customer has one: its draft as it now stands, and the job."""
    draft = deck_draft(customer, **kwargs)
    job = run(customer, draft)
    assert job.status == 'succeeded', job.error_code
    draft.refresh_from_db()
    return draft, job


def picture(seed, width=1600, height=1000):
    buffer = io.BytesIO()
    Image.new('RGB', (width, height), (seed * 37 % 255, 140, seed * 11 % 255)).save(buffer, 'JPEG', quality=85)
    return buffer.getvalue()


def pixabay_entry(number):
    return {'provider': 'pixabay', 'id': number, 'page_url': f'https://pixabay.com/photos/x-{number}/'}


@pytest.fixture
def stock_photos(monkeypatch):
    """Pixabay as a deck job sees it: each slide's photo, and its shortlist of four, of which the model saw two."""
    def fetch(sections, *, cap, budget, job=None, style='photo'):
        asking = stock.wanted(sections)
        found, shortlist = {}, {}
        for number, section in enumerate(asking, 1):
            found[section['id']] = {'jpeg': picture(number), 'width': 1600, 'height': 1000, **pixabay_entry(number)}
            shortlist[section['id']] = [
                {**pixabay_entry(number * 10 + hit_number), 'preview': f'https://pixabay.com/get/{number}{hit_number}_640.jpg',
                 'url': f'https://pixabay.com/get/{number}{hit_number}_1280.jpg',
                 **({'jpeg': picture(number * 10 + hit_number, 512, 320)} if hit_number < 2 else {})}
                for hit_number in range(stock.CANDIDATES)]
        return stock.PhotoResult(photos=found, wanted=len(asking), candidates=shortlist)
    monkeypatch.setattr(stock, 'fetch_for_deck', fetch)


@pytest.fixture
def clock(monkeypatch):
    """Moves the platform's clock to this many hours from now."""
    start = timezone.now()

    def move(hours):
        monkeypatch.setattr(timezone, 'now', lambda: start + timedelta(hours=hours))
    return move


@pytest.fixture
def customer(settings):
    settings.DEBUG = True
    return paid(settings, account())


def slide_xml(path):
    """Each slide's XML by slide number: python-pptx writes fresh zip timestamps, so never the file's own bytes."""
    with zipfile.ZipFile(path) as deck:
        return {int(re.search(r'\d+', name).group()): hashlib.sha256(deck.read(name)).hexdigest()
                for name in deck.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml', name)}


def media(path):
    with zipfile.ZipFile(path) as deck:
        return sorted(hashlib.sha256(deck.read(name)).hexdigest() for name in deck.namelist() if name.startswith('ppt/media/'))


def delivered(job):
    return storage.local(job.artifacts.get().file.object_key)


def pins_of(draft):
    draft.refresh_from_db()
    return unpack(draft.encrypted_data).get('_render')


def kept_pictures(customer, **facts):
    return FileAsset.objects.filter(account=customer, metadata__kind='deck_photo', **{f'metadata__{key}': value for key, value in facts.items()})


def stored_photos(customer, pins):
    """The slides' pictures back from the account's files, as a redraw takes them."""
    found = {}
    for section_id, photo in pins['photos'].items():
        if photo['asset_id']:
            asset = FileAsset.objects.get(account=customer, pk=photo['asset_id'])
            found[section_id] = {'jpeg': storage.read_bytes(asset.object_key), 'width': asset.metadata['width'],
                                 'height': asset.metadata['height'], 'provider': asset.metadata['provider'],
                                 'id': asset.metadata['id'], 'page_url': asset.metadata['page_url']}
    return found


def redraw(customer, draft, path):
    """The deck again from nothing but what its draft holds, as a later edit will draw it."""
    draft.refresh_from_db()
    data = unpack(draft.encrypted_data)
    return render_pptx(data['content'], path, data['output_locale'], 'user_document',
                       style=render_style(customer, data, feature_id=SLIDES), photos=stored_photos(customer, data['_render']),
                       pins=data['_render'])


def edit_section(customer, draft, section_id, **fields):
    draft.refresh_from_db()
    content = copy.deepcopy(unpack(draft.encrypted_data)['content'])
    for section in content['sections']:
        if section['id'] == section_id:
            section.update(fields)
    return update_draft(customer, draft.id, {'version': draft.version, 'content': content})


def saved(customer, draft, **fields):
    """A save of the draft as it now stands, as a client makes one."""
    return update_draft(customer, draft.id, {'version': GenerationDraft.objects.get(pk=draft.pk).version, **fields})


def during_the_job(monkeypatch, *saves):
    """Each of `saves` made while the next job is drawing its deck."""
    real = execution.render_pptx

    def drawing(*args, **kwargs):
        monkeypatch.setattr(execution, 'render_pptx', real)
        for save in saves:
            save()
        return real(*args, **kwargs)
    monkeypatch.setattr(execution, 'render_pptx', drawing)


# ---------------------------------------------------------------- written at generation


def test_with_the_deck_editor_off_a_generated_deck_keeps_nothing(customer, stock_photos, monkeypatch):
    monkeypatch.delenv('EDITOR_FLAG_DECK_EDITOR')
    draft, job = generate(customer)
    assert job.status == 'succeeded'
    assert '_render' not in unpack(draft.encrypted_data) and not kept_pictures(customer).exists()
    metadata = job.artifacts.get().file.metadata
    assert 'deck_seed' not in metadata and 'render' not in metadata, 'the seed has the title in it'


def test_a_generated_deck_stores_what_draws_it_again(customer, stock_photos, tmp_path):
    draft, job = generate(customer)
    data = unpack(draft.encrypted_data)
    pins = data['_render']
    artifact = job.artifacts.get().file

    assert set(pins) == {'design', 'deck_seed', 'body_size', 'renderer_version', 'variants', 'photos'}
    assert pins['design'] == DESIGN == artifact.metadata['design']
    assert pins['deck_seed'] == variants.seed(deck_designs.look(data['options']['template_style']), data['content'])
    assert pins['body_size'] == artifact.metadata['body_size'] > 0
    assert pins['renderer_version'] == deck_designs.version()
    # Made at 1, its content set at 2, written back by the job at 3: the pins themselves are not a version.
    assert draft.version == 3

    # The variants by section id, in the order they were drawn; the question slides have none.
    ids = [section['id'] for section in data['content']['sections']]
    assert list(pins['variants']) == ids and artifact.page_count == len(ids) + 2
    assert [pins['variants'][section_id] for section_id in ids] == artifact.metadata['variants'][:len(ids)]
    assert pins['variants'][CARDS].startswith('cards.') and pins['variants'][PHOTO].startswith('image_split.')

    # Each photo and each small copy the model saw is the account's own file; the other two are only an address.
    assert set(pins['photos']) == set(PHOTO_SLIDES)
    for section_id in PHOTO_SLIDES:
        photo = pins['photos'][section_id]
        chosen = FileAsset.objects.get(account=customer, pk=photo['asset_id'])
        assert chosen.metadata['kind'] == 'deck_photo' and chosen.metadata['candidate'] is False
        assert chosen.metadata['draft_id'] == str(draft.id) and chosen.metadata['section_id'] == section_id
        assert chosen.metadata['provider'] == 'pixabay' and chosen.mime_type == 'image/jpeg'
        assert chosen.sha256 == hashlib.sha256(storage.read_bytes(chosen.object_key)).hexdigest()
        assert len(photo['candidates']) == stock.CANDIDATES
        for offered in photo['candidates']:
            assert set(offered) == {'asset_id', 'url', 'id', 'page_url'}
            assert offered['url'].startswith('https://pixabay.com/') and offered['page_url'].startswith('https://pixabay.com/')
        held = [offered for offered in photo['candidates'] if offered['asset_id']]
        assert len(held) == 2
        for offered in held:
            asset = FileAsset.objects.get(account=customer, pk=offered['asset_id'])
            assert asset.metadata['candidate'] is True and asset.metadata['id'] == offered['id']
            assert asset.metadata['page_url'] == offered['page_url'] and asset.metadata['section_id'] == section_id

    # From nothing but the draft, the deck as it was delivered, picture for picture.
    again = redraw(customer, draft, tmp_path / 'again.pptx')
    assert slide_xml(tmp_path / 'again.pptx') == slide_xml(delivered(job))
    assert media(tmp_path / 'again.pptx') == media(delivered(job))
    assert again['metadata']['repinned'] == [] and again['metadata']['variants'] == artifact.metadata['variants']


def test_generation_draws_what_it_drew_before_there_were_pins(customer, stock_photos, tmp_path):
    draft, job = generate(customer)
    data = unpack(draft.encrypted_data)
    plain = render_pptx(data['content'], tmp_path / 'plain.pptx', data['output_locale'], 'user_document',
                        style=render_style(customer, data, feature_id=SLIDES), photos=stored_photos(customer, data['_render']))
    assert slide_xml(tmp_path / 'plain.pptx') == slide_xml(delivered(job))
    assert plain['metadata']['repinned'] == []
    assert plain['metadata']['deck_seed'] == data['_render']['deck_seed']


def test_the_file_keeps_a_copy_of_the_pins_with_none_of_the_customers_words(customer, stock_photos):
    draft, job = generate(customer)
    pins = unpack(draft.encrypted_data)['_render']
    metadata = job.artifacts.get().file.metadata
    copied = metadata['render']
    # The seed has the deck's title in it, and this copy is not encrypted.
    assert 'deck_seed' not in metadata
    assert copied['deck_seed'] == hashlib.sha256(pins['deck_seed'].encode()).hexdigest()
    assert {key: copied[key] for key in ('design', 'body_size', 'variants', 'renderer_version')} == {
        key: pins[key] for key in ('design', 'body_size', 'variants', 'renderer_version')}
    assert {section_id: photo['asset_id'] for section_id, photo in copied['photos'].items()} == {
        section_id: photo['asset_id'] for section_id, photo in pins['photos'].items()}
    assert 'http' not in json.dumps(copied)
    written = json.dumps(metadata, ensure_ascii=False).lower()
    assert TITLE.lower() not in written and 'harbour' not in written and 'bulk carriers' not in written
    # A customer reading their job sees none of it: only the fields a file has always shown.
    shown = login_client(customer).get(f'/api/v1/jobs/{job.id}').json()
    assert 'render' not in json.dumps(shown['artifacts']) and 'deck_seed' not in json.dumps(shown['artifacts'])


def test_a_customers_edit_during_the_job_keeps_their_words_and_the_pins(customer, stock_photos, monkeypatch, tmp_path):
    draft = deck_draft(customer)
    client = login_client(customer)
    real = execution.render_pptx
    made = {}

    def while_editing(*args, **kwargs):
        content = copy.deepcopy(unpack(GenerationDraft.objects.get(pk=draft.pk).encrypted_data)['content'])
        content['sections'][2]['heading'] = 'The words the customer typed'
        answer = client.patch(f'/api/v1/generation/drafts/{draft.id}', json.dumps({'version': draft.version, 'content': content}),
                              content_type='application/json')
        assert answer.status_code == 200, answer.content
        made['version'] = answer.json()['version']
        return real(*args, **kwargs)
    monkeypatch.setattr(execution, 'render_pptx', while_editing)
    job = run(customer, draft)
    assert job.status == 'succeeded', job.error_code

    pins = pins_of(draft)
    data = unpack(draft.encrypted_data)
    assert draft.version == made['version'] == 3, 'the job wrote back nothing, and the pins are not a version'
    assert data['content']['sections'][2]['heading'] == 'The words the customer typed'
    assert pins['variants'] and set(pins['photos']) == set(PHOTO_SLIDES)
    assert job.artifacts.get().file.metadata['variants'][:8] == list(pins['variants'].values())

    # Their next save names the version they know, and the pins go on with it.
    monkeypatch.setattr(execution, 'render_pptx', real)
    answer = client.patch(f'/api/v1/generation/drafts/{draft.id}', json.dumps({'version': 3, 'title': 'A new title'}), content_type='application/json')
    assert answer.status_code == 200, answer.content
    assert pins_of(draft) == pins and answer.json()['render']['variants'] == pins['variants']
    # Drawn from the pins, the slide they edited is the one that differs from the deck delivered.
    redraw(customer, draft, tmp_path / 'edited.pptx')
    before, after = slide_xml(delivered(job)), slide_xml(tmp_path / 'edited.pptx')
    assert {number for number in before if before[number] != after[number]} == {3}


def reword(customer, draft):
    version = GenerationDraft.objects.get(pk=draft.pk).version
    answer = login_client(customer).patch(f'/api/v1/generation/drafts/{draft.id}', json.dumps({'version': version, 'prompt': 'A different deck about ferries'}),
                                          content_type='application/json')
    assert answer.status_code == 200, answer.content


def other_notes(customer, draft):
    saved(customer, draft, source_text='Other notes about ferries.')


def first_notes_again(customer, draft):
    saved(customer, draft, source_text='Notes about the harbour.')


def edit_words(customer, draft):
    edit_section(customer, GenerationDraft.objects.get(pk=draft.pk), LIST, heading='The words the customer typed')


@pytest.mark.parametrize('saves', [
    [reword],
    [other_notes],
    [lambda customer, draft: resize(customer, draft.id, 9)],
    [lambda customer, draft: resize(customer, draft.id, 9), lambda customer, draft: resize(customer, draft.id, 8)],
    [other_notes, first_notes_again],
    [reword, edit_words],
], ids=['reworded_brief', 'other_source_text', 'one_more_slide_on_the_bots_review', 'one_more_and_one_less', 'other_notes_and_back', 'reworded_then_edited'])
def test_a_save_during_the_job_that_rebuilds_the_outline_leaves_the_deck_behind(customer, stock_photos, monkeypatch, saves):
    """The new sections take the same ids: the deck just delivered would answer for slides now blank or about something else.

    Whatever the draft's brief and count say by the end: saved back as they were, the slides do not come back.
    """
    draft = deck_draft(customer)
    during_the_job(monkeypatch, *[lambda save=save: save(customer, draft) for save in saves])
    job = run(customer, draft)
    assert job.status == 'succeeded', job.error_code

    assert pins_of(draft) is None and 'render' not in draft_data(draft)
    assert unpack(draft.encrypted_data)['content']['sections'][0]['heading'] != 'Harbour logistics', 'rebuilt'
    assert draft.version == 2 + len(saves), 'the job wrote back nothing'
    # The file is still the deck it is, and the pictures no pins name go by their own clock.
    artifact = job.artifacts.get().file
    assert artifact.metadata['render']['variants']
    assert kept_pictures(customer) and all(picture.expires_at < artifact.expires_at for picture in kept_pictures(customer))


def test_a_save_during_the_job_that_rebuilds_with_nothing_said_leaves_the_deck_behind(customer, stock_photos, monkeypatch):
    """A slide added before the job leaves a count saved that the next save reads differently, and rebuilds on, whatever it names."""
    draft = deck_draft(customer)
    content = unpack(draft.encrypted_data)['content']
    draft = saved(customer, draft, content={**content, 'sections': [*content['sections'], {**fixtures.light('bullets', 3), 'id': 's9'}]})
    during_the_job(monkeypatch, lambda: saved(customer, draft, title='A new title'))
    job = run(customer, draft)
    assert job.status == 'succeeded', job.error_code
    assert len(job.artifacts.get().file.metadata['render']['variants']) == 9
    assert len(unpack(GenerationDraft.objects.get(pk=draft.pk).encrypted_data)['content']['sections']) == 8, 'rebuilt'
    assert pins_of(draft) is None and 'render' not in draft_data(draft)


@pytest.mark.parametrize('change', [
    lambda data: {'title': 'A new title'},
    lambda data: {'outline': outline_of(data)},
    lambda data: {'prompt': 'A reworded brief', 'content': data['content']},
    lambda data: {'prompt': 'A reworded brief', 'outline': outline_of(data)},
    lambda data: {'source_text': 'Other notes about ferries.', 'content': data['content']},
], ids=['title', 'outline', 'brief_with_its_content', 'brief_with_its_outline', 'source_text_with_its_content'])
def test_a_save_during_the_job_that_keeps_the_slides_keeps_the_deck(customer, stock_photos, monkeypatch, change):
    """As it does after the job: the customer said which slides these are, so they are the slides just drawn."""
    draft = deck_draft(customer)
    during_the_job(monkeypatch, lambda: saved(customer, draft, **change(unpack(draft.encrypted_data))))
    job = run(customer, draft)
    assert job.status == 'succeeded', job.error_code
    pins = pins_of(draft)
    assert draft.version == 3, 'the job wrote back nothing'
    assert list(pins['variants']) == [section['id'] for section in unpack(draft.encrypted_data)['content']['sections']]
    assert draft_data(draft)['render']['variants'] == pins['variants']


def test_a_rebuild_before_the_job_costs_it_nothing(customer, stock_photos, monkeypatch):
    draft = deck_draft(customer)
    during_the_job(monkeypatch, lambda: reword(customer, draft))
    assert run(customer, draft).status == 'succeeded'
    assert pins_of(draft) is None

    # The rebuilt draft, made: the deck drawn now is the one it holds.
    job = run(customer, draft)
    assert job.status == 'succeeded', job.error_code
    made = pins_of(draft)
    assert made and draft.version == 4 and list(made['variants']) == [section['id'] for section in unpack(draft.encrypted_data)['content']['sections']]

    # Rebuilt again and made with an edit during the job: that older rebuild says nothing about this deck.
    draft = saved(customer, draft, prompt='Another deck about ferries')
    assert pins_of(draft) is None
    during_the_job(monkeypatch, lambda: edit_words(customer, draft))
    job = run(customer, draft)
    assert job.status == 'succeeded', job.error_code
    assert pins_of(draft)['variants'] and unpack(draft.encrypted_data)['content']['sections'][4]['heading'] == 'The words the customer typed'


def test_a_change_reworded_during_its_job_is_rebuilt_and_a_selected_one_is_not(customer, stock_photos, monkeypatch):
    original, _ = generate(customer)
    revised = create_draft(customer, {'prompt': 'Make the second slide shorter.', 'options': {'revise_draft_id': str(original.id)}})
    during_the_job(monkeypatch, lambda: saved(customer, revised, prompt='Make the third slide shorter.'))
    assert run(customer, revised).status == 'succeeded'
    assert pins_of(revised) is None

    selected = create_draft(customer, {'prompt': 'Fix the typos on slide 2.', 'options': {
        'revise_draft_id': str(original.id), 'revise_section_ids': [CARDS], 'revise_base_version': original.version}})
    options = unpack(selected.encrypted_data)['options']
    during_the_job(monkeypatch, lambda: saved(customer, selected, prompt='Fix the spelling on slide 2.', options=options))
    assert run(customer, selected).status == 'succeeded'
    assert pins_of(selected)


TIDES = [{'id': 's1', 'heading': 'Tides', 'body': 'Moon', 'notes': '', 'layout': 'cover', 'items': [], 'columns': [], 'image_query': ''},
         {'id': 's2', 'heading': 'Why', 'body': 'Moon\nSun\nWater', 'notes': '', 'layout': 'bullets', 'items': [], 'columns': [], 'image_query': ''}]


def model_writes(monkeypatch, design=None, before=None):
    """The model's answer, with the design it chose, if it was asked to."""
    def writing(*args, **kwargs):
        if before:
            before()
        answer = {'title': 'Tides', 'answer_supported': True, 'citations': [], 'questions': [], 'sections': copy.deepcopy(TIDES)}
        return {**answer, **({'design': design} if design else {})}, {'input_tokens': 1, 'output_tokens': 1}
    monkeypatch.setattr(provider, 'generate', writing)


def the_models_deck(customer, monkeypatch, options=None, before=None):
    """A deck the model chose the design of."""
    draft = create_draft(customer, {'feature_id': SLIDES, 'prompt': 'Two slides about tides', **({'options': options} if options else {})})
    model_writes(monkeypatch, 'lagoon', before and (lambda: before(draft)))
    job = run(customer, draft)
    assert job.status == 'succeeded', job.error_code
    assert job.artifacts.get().file.metadata['design'] == 'lagoon'
    draft.refresh_from_db()
    return draft, job


def edited_during_the_job(customer):
    def edit(draft):
        update_draft(customer, draft.id, {'version': draft.version, 'content': {'title': 'Tides', 'sections': TIDES, 'questions': [], 'citations': []}})
    return edit


def a_change_of(customer, draft, monkeypatch, request='Make the second slide shorter.', design=None):
    """A paid change to this deck, and the file it comes back as."""
    revised = create_draft(customer, {'prompt': request, 'options': {'revise_draft_id': str(draft.id)}})
    model_writes(monkeypatch, design)
    job = run(customer, revised)
    assert job.status == 'succeeded', job.error_code
    return revised, job.artifacts.get().file


def style_of(draft):
    return unpack(draft.encrypted_data)['options']['template_style']


def test_the_design_the_model_chose_stays_with_the_pins_when_an_edit_skips_the_write_back(settings, monkeypatch, tmp_path):
    customer = live(settings)
    draft, job = the_models_deck(customer, monkeypatch, before=edited_during_the_job(customer))
    pins = pins_of(draft)
    data = unpack(draft.encrypted_data)
    assert draft.version == 2 and pins['design'] == 'lagoon'
    assert not data['options']['template_style'].get('deck_design'), 'it only ever reached the draft with the write-back'
    assert redraw(customer, draft, tmp_path / 'again.pptx')['metadata']['design'] == 'lagoon'
    assert slide_xml(tmp_path / 'again.pptx') == slide_xml(delivered(job))


@pytest.mark.parametrize('options', [None, {'deck_design': 'auto'}], ids=['no_setup_screen', 'auto_on_setup_screen'])
def test_a_change_after_a_save_keeps_the_design_the_model_chose(settings, monkeypatch, options):
    customer = live(settings)
    draft, _ = the_models_deck(customer, monkeypatch, options)
    assert style_of(draft)['deck_design'] == 'lagoon'
    saved = update_draft(customer, draft.id, {'version': draft.version, 'title': 'New'})
    assert style_of(saved)['deck_design'] == 'lagoon' and pins_of(saved)['design'] == 'lagoon'
    # And on through another save of what it says, and the change's own.
    saved = edit_section(customer, saved, 's2', heading='Why it happens')
    assert style_of(saved)['deck_design'] == 'lagoon'
    revised, changed = a_change_of(customer, saved, monkeypatch)
    assert changed.metadata['design'] == 'lagoon' and style_of(revised)['deck_design'] == 'lagoon'
    again = update_draft(customer, revised.id, {'version': GenerationDraft.objects.get(pk=revised.pk).version, 'title': 'Newer'})
    assert style_of(again)['deck_design'] == 'lagoon'


def test_a_change_takes_the_design_from_the_pins_when_the_style_never_had_it(settings, monkeypatch):
    customer = live(settings)
    draft, _ = the_models_deck(customer, monkeypatch, before=edited_during_the_job(customer))
    assert 'deck_design' not in style_of(draft) and pins_of(draft)['design'] == 'lagoon'
    _, changed = a_change_of(customer, draft, monkeypatch)
    assert changed.metadata['design'] == 'lagoon'
    # A save in between has nothing more to lose: the pins go on with it.
    saved = update_draft(customer, draft.id, {'version': draft.version, 'title': 'New'})
    assert 'deck_design' not in style_of(saved)
    _, changed = a_change_of(customer, saved, monkeypatch)
    assert changed.metadata['design'] == 'lagoon'
    # A change to one slide too: it may not restyle the deck, and that includes losing its look.
    selected = create_draft(customer, {'prompt': 'Fix the typos on slide 2.', 'options': {
        'revise_draft_id': str(saved.id), 'revise_section_ids': ['s2'], 'revise_base_version': saved.version}})
    assert style_of(selected)['deck_design'] == 'lagoon'


def test_a_change_asking_for_a_new_look_still_gets_one(settings, monkeypatch):
    customer = live(settings)
    draft, _ = the_models_deck(customer, monkeypatch, before=edited_during_the_job(customer))
    revised, changed = a_change_of(customer, draft, monkeypatch, 'Change the design of the deck.', design='midnight')
    assert changed.metadata['design'] == 'midnight' and pins_of(revised)['design'] == 'midnight'
    assert style_of(revised)['deck_design'] == 'midnight'
    # Which a later save of that change keeps, though its request is read as a new look each time.
    saved = update_draft(customer, revised.id, {'version': GenerationDraft.objects.get(pk=revised.pk).version, 'title': 'New'})
    assert style_of(saved)['deck_design'] == 'midnight'
    _, again = a_change_of(customer, saved, monkeypatch)
    assert again.metadata['design'] == 'midnight'


def test_auto_asked_for_now_or_another_design_replaces_the_one_the_model_chose(settings, monkeypatch):
    customer = live(settings)
    draft, _ = the_models_deck(customer, monkeypatch)
    options = unpack(draft.encrypted_data)['options']
    auto = update_draft(customer, draft.id, {'version': draft.version, 'options': {**options, 'deck_design': 'auto'}})
    assert 'deck_design' not in style_of(auto) and deck_designs.wanted(unpack(auto.encrypted_data))

    draft, _ = the_models_deck(customer, monkeypatch)
    options = unpack(draft.encrypted_data)['options']
    picked = update_draft(customer, draft.id, {'version': draft.version, 'options': {**options, 'deck_design': DESIGN}})
    assert style_of(picked)['deck_design'] == DESIGN
    # A design the customer picked is theirs to take back, by Auto or by no longer asking for it.
    options = unpack(picked.encrypted_data)['options']
    auto = update_draft(customer, picked.id, {'version': picked.version, 'options': {**options, 'deck_design': 'auto'}})
    assert 'deck_design' not in style_of(auto)
    picked = update_draft(customer, picked.id, {'version': auto.version, 'options': {**options, 'deck_design': DESIGN}})
    bare = update_draft(customer, picked.id, {'version': picked.version, 'options': {k: v for k, v in options.items() if k != 'deck_design'}})
    assert 'deck_design' not in style_of(bare)


def test_a_rebuilt_outline_lets_the_model_choose_a_look_again(settings, monkeypatch):
    customer = live(settings)
    draft, _ = the_models_deck(customer, monkeypatch)
    rebuilt = update_draft(customer, draft.id, {'version': draft.version, 'prompt': 'Two slides about ferries'})
    assert 'deck_design' not in style_of(rebuilt) and deck_designs.wanted(unpack(rebuilt.encrypted_data))


def test_a_quote_made_during_the_job_is_still_good_after_the_pins_are_written(customer, stock_photos, monkeypatch):
    draft = deck_draft(customer)
    real = execution.render_pptx
    made = {}

    def while_quoting(*args, **kwargs):
        edited = edit_section(customer, GenerationDraft.objects.get(pk=draft.pk), LIST, heading='Edited while it ran')
        made['quote'] = generation_quote(customer, edited.id, edited.version)
        return real(*args, **kwargs)
    monkeypatch.setattr(execution, 'render_pptx', while_quoting)
    assert run(customer, draft).status == 'succeeded'
    monkeypatch.setattr(execution, 'render_pptx', real)

    # Packing changed the draft's bytes, not its version: nothing the customer can see moved.
    draft.refresh_from_db()
    assert made['quote'].parameters['draft_version'] == draft.version
    validate_generation_quote(customer, Quote.objects.get(pk=made['quote'].pk))
    job, _ = submit_job(customer, made['quote'].id, 'quoted-while-it-ran')
    job = execute_job(job.id)
    assert job.status == 'succeeded', job.error_code


def test_a_job_waiting_on_the_draft_moves_with_the_pins(customer, stock_photos):
    draft = deck_draft(customer)
    quote = generation_quote(customer, draft.id, draft.version)
    waiting, _ = submit_job(customer, quote.id, 'queued-on-this-version')
    execution._write_pins(waiting, draft.id, {'design': DESIGN, 'deck_seed': 'x', 'body_size': 20.0, 'renderer_version': 'v', 'variants': {}, 'photos': {}}, draft.version)
    draft.refresh_from_db()
    quote.refresh_from_db()
    waiting.refresh_from_db()
    current = hashlib.sha256(bytes(draft.encrypted_data)).hexdigest()
    assert quote.parameters['snapshot'] == waiting.parameters['snapshot'] == current
    assert draft.version == 2
    assert execute_job(waiting.id).status == 'succeeded'


def test_a_failed_job_can_still_be_retried_after_pins_from_another_job(customer, stock_photos, monkeypatch):
    draft = deck_draft(customer)

    def broken(*args, **kwargs):
        raise OSError('the renderer broke')
    real = execution.render_pptx
    monkeypatch.setattr(execution, 'render_pptx', broken)
    before = bytes(GenerationDraft.objects.get(pk=draft.pk).encrypted_data)
    failed = run(customer, draft)
    assert failed.status == 'failed'
    monkeypatch.setattr(execution, 'render_pptx', real)
    draft.refresh_from_db()
    assert bytes(draft.encrypted_data) == before, 'a job that fails leaves its draft as it was, for its retry'
    assert '_render' not in unpack(draft.encrypted_data)

    execution._write_pins(failed, draft.id, {'design': DESIGN, 'deck_seed': 'x', 'body_size': 20.0, 'renderer_version': 'v', 'variants': {}, 'photos': {}}, draft.version)
    retry = checkpoints.retry_quote(customer, failed.id)
    again, _ = submit_job(customer, retry.id, 'retry-after-pins')
    # What a provider call checks of the retry's lineage, in the deck's first call.
    checkpoints._root_job(again, GenerationDraft.objects.get(pk=draft.pk))
    assert execute_job(again.id).status == 'succeeded'


def test_a_change_request_gets_pins_of_its_own(customer, stock_photos):
    original, _ = generate(customer)
    pins = pins_of(original)
    revised = create_draft(customer, {'prompt': 'Make the second slide shorter.', 'options': {'revise_draft_id': str(original.id)}})
    assert '_render' not in unpack(revised.encrypted_data), 'not carried over: the change draws its own deck'
    assert 'render' not in draft_data(revised)
    job = run(customer, revised)
    assert job.status == 'succeeded', job.error_code
    own = pins_of(revised)
    assert own['variants'] and own['deck_seed'] == pins['deck_seed']
    assert {photo['asset_id'] for photo in own['photos'].values()}.isdisjoint(photo['asset_id'] for photo in pins['photos'].values())
    assert kept_pictures(customer, draft_id=str(revised.id), candidate=False).count() == len(PHOTO_SLIDES)
    assert pins_of(original) == pins


def test_a_new_outline_leaves_the_deck_it_replaces_behind(customer, stock_photos):
    draft, _ = generate(customer)
    assert pins_of(draft)
    quote = create_outline_quote(customer, draft.id, draft.version)
    job, _ = submit_job(customer, quote.id, 'outline-after-deck')
    job = execute_job(job.id)
    assert job.status == 'succeeded', job.error_code
    assert pins_of(draft) is None and 'render' not in draft_data(draft)


@pytest.mark.parametrize('change', [
    lambda data: {'prompt': 'A different deck about ferries'},
    lambda data: {'source_text': 'Other notes about ferries.'},
    lambda data: {'options': {**data['options'], 'pages': len(data['content']['sections']) + 1}},
], ids=['reworded_brief', 'other_source_text', 'another_count'])
def test_a_save_that_rebuilds_the_outline_leaves_the_deck_behind(customer, stock_photos, change):
    """The new sections take the same ids: the old pins would answer for slides now blank or about something else."""
    draft, _ = generate(customer)
    data = unpack(draft.encrypted_data)
    saved = update_draft(customer, draft.id, {'version': draft.version, **change(data)})
    assert unpack(saved.encrypted_data)['content']['sections'][0]['heading'] != data['content']['sections'][0]['heading'], 'rebuilt'
    assert pins_of(saved) is None and 'render' not in draft_data(saved)


def outline_of(data):
    return [{'id': section['id'], 'title': section['heading'], 'body': section['body'],
             **{key: section[key] for key in ('layout', 'items', 'columns', 'image_query') if key in section}} for section in data['content']['sections']]


@pytest.mark.parametrize('change', [
    lambda data: {'title': 'A new title'},
    lambda data: {'content': data['content']},
    lambda data: {'outline': outline_of(data)},
    lambda data: {'prompt': 'A reworded brief', 'content': data['content']},
    lambda data: {'prompt': 'A reworded brief', 'outline': outline_of(data)},
], ids=['title', 'content', 'outline', 'brief_with_its_content', 'brief_with_its_outline'])
def test_a_save_that_keeps_the_slides_keeps_the_deck(customer, stock_photos, change):
    draft, _ = generate(customer)
    pins = pins_of(draft)
    data = unpack(draft.encrypted_data)
    saved = update_draft(customer, draft.id, {'version': draft.version, **change(data)})
    assert [section['id'] for section in unpack(saved.encrypted_data)['content']['sections']] == list(pins['variants'])
    assert pins_of(saved) == pins and draft_data(saved)['render']['variants'] == pins['variants']


def test_a_reworded_change_is_rebuilt_from_its_document_and_a_selected_one_is_not(customer, stock_photos):
    original, _ = generate(customer)
    revised = create_draft(customer, {'prompt': 'Make the second slide shorter.', 'options': {'revise_draft_id': str(original.id)}})
    assert run(customer, revised).status == 'succeeded'
    assert pins_of(revised)
    reworded = update_draft(customer, revised.id, {'version': GenerationDraft.objects.get(pk=revised.pk).version, 'prompt': 'Make the third slide shorter.'})
    assert pins_of(reworded) is None

    selected = create_draft(customer, {'prompt': 'Fix the typos on slide 2.', 'options': {
        'revise_draft_id': str(original.id), 'revise_section_ids': [CARDS], 'revise_base_version': original.version}})
    assert run(customer, selected).status == 'succeeded'
    pins = pins_of(selected)
    assert pins
    data = unpack(selected.encrypted_data)
    reworded = update_draft(customer, selected.id, {'version': selected.version, 'prompt': 'Fix the spelling on slide 2.', 'options': data['options']})
    assert unpack(reworded.encrypted_data)['content'] == data['content'] and pins_of(reworded) == pins


def test_a_change_that_outlives_its_document_can_still_be_saved(customer, stock_photos, clock):
    original, _ = generate(customer)
    clock(20)
    revised = create_draft(customer, {'prompt': 'Make the second slide shorter.', 'options': {'revise_draft_id': str(original.id)}})
    assert run(customer, revised).status == 'succeeded'
    revised.refresh_from_db()
    assert revised.expires_at > GenerationDraft.objects.get(pk=original.pk).expires_at
    # What a save makes of it while the document is there.
    revised = update_draft(customer, revised.id, {'version': revised.version, 'title': 'Saved in time'})
    before = unpack(revised.encrypted_data)

    # Hour 30: the document went at hour 24, the change has until hour 44. A save makes the same of it.
    clock(30)
    cleanup_expired()
    assert not GenerationDraft.objects.filter(pk=original.pk).exists()
    saved = update_draft(customer, revised.id, {'version': revised.version, 'title': 'Saved a day later'})
    after = unpack(saved.encrypted_data)
    assert saved.version == revised.version + 1 and after['title'] == after['content']['title'] == 'Saved a day later'
    for field in ('revision', 'options', '_render', 'output_locale', 'locale_source', 'prompt', 'source_ids'):
        assert after[field] == before[field], field
    assert after['content']['sections'] == before['content']['sections']

    # Its words too, over the API, as the editor will save them.
    content = copy.deepcopy(after['content'])
    content['sections'][1]['heading'] = 'Reworded a day later'
    answer = login_client(customer).patch(f'/api/v1/generation/drafts/{revised.id}', json.dumps({'version': saved.version, 'content': content}), content_type='application/json')
    assert answer.status_code == 200, answer.content
    assert answer.json()['content']['sections'][1]['heading'] == 'Reworded a day later' and answer.json()['render']['variants'] == before['_render']['variants']


def test_a_change_made_from_a_file_outlives_its_document_as_well(customer, clock):
    source = upload(customer)
    original = create_draft(customer, {'feature_id': DOCUMENT, 'title': 'From a file', 'source_text': 'Notes about the harbour.', 'source_ids': [str(source.id)]})
    assert run(customer, original).status == 'succeeded'
    clock(20)
    revised = create_draft(customer, {'prompt': 'Make it shorter.', 'options': {'revise_draft_id': str(original.id)}})
    assert run(customer, revised).status == 'succeeded'
    revised.refresh_from_db()
    clock(30)
    cleanup_expired()
    assert not GenerationDraft.objects.filter(pk=original.pk).exists()
    saved = update_draft(customer, revised.id, {'version': revised.version, 'title': 'Saved a day later'})
    assert unpack(saved.encrypted_data)['title'] == 'Saved a day later'


def test_a_change_never_generated_goes_with_the_file_it_is_made_from(customer, clock):
    """It could not be quoted without that file either: only a result carries its files on."""
    source = upload(customer)
    original = create_draft(customer, {'feature_id': DOCUMENT, 'title': 'From a file', 'source_text': 'Notes about the harbour.', 'source_ids': [str(source.id)]})
    assert run(customer, original).status == 'succeeded'
    clock(23)
    revised = create_draft(customer, {'prompt': 'Make it shorter.', 'options': {'revise_draft_id': str(original.id)}})
    clock(30)
    cleanup_expired()
    with pytest.raises(DomainError, match='file_unavailable'):
        update_draft(customer, revised.id, {'version': revised.version, 'title': 'Saved a day later'})
    with pytest.raises(DomainError, match='file_unavailable'):
        generation_quote(customer, revised.id, revised.version)


def test_a_change_never_generated_can_be_reworded_and_made_after_its_document_has_gone(customer, stock_photos, clock):
    original, _ = generate(customer)
    pages = unpack(original.encrypted_data)['content']
    clock(23)
    revised = create_draft(customer, {'prompt': 'Make the second slide shorter.', 'options': {'revise_draft_id': str(original.id)}})
    clock(30)
    cleanup_expired()
    assert not GenerationDraft.objects.filter(pk=original.pk).exists()
    reworded = update_draft(customer, revised.id, {'version': revised.version, 'prompt': 'Make the third slide shorter.'})
    data = unpack(reworded.encrypted_data)
    # Starts from the document it changes, as a reworded change does while that is still there.
    assert data['prompt'] == data['revision']['request'] == 'Make the third slide shorter.'
    assert data['content'] == data['revision']['before'] == pages and data['revision']['source_draft_id'] == str(original.id)
    job = run(customer, reworded)
    assert job.status == 'succeeded', job.error_code


def test_what_needs_the_document_itself_is_still_refused_once_it_has_gone(customer, stock_photos, clock):
    original, _ = generate(customer)
    clock(23)
    revised = create_draft(customer, {'prompt': 'Make the second slide shorter.', 'options': {'revise_draft_id': str(original.id)}})
    clock(30)
    cleanup_expired()
    data = unpack(revised.encrypted_data)
    # Picking pages of a document that has gone: there is nothing to pick from.
    with pytest.raises(DomainError, match='not_found'):
        update_draft(customer, revised.id, {'version': revised.version, 'options': {**data['options'], 'revise_section_ids': [CARDS], 'revise_base_version': original.version}})
    # Pointing a change at any other draft that has gone, or none it holds a copy of.
    with pytest.raises(DomainError, match='not_found'):
        update_draft(customer, revised.id, {'version': revised.version, 'options': {**data['options'], 'revise_draft_id': str(uuid.uuid4())}})
    GenerationDraft.objects.filter(pk=revised.pk).update(encrypted_data=pack({**data, 'revision': {key: value for key, value in data['revision'].items() if key != 'before'}}))
    with pytest.raises(DomainError, match='not_found'):
        update_draft(customer, revised.id, {'version': revised.version, 'title': 'No copy to go on from'})


def test_generating_again_replaces_the_pins(customer, stock_photos):
    draft, _ = generate(customer)
    first = pins_of(draft)
    job = run(customer, draft)
    assert job.status == 'succeeded', job.error_code
    second = pins_of(draft)
    assert second['variants'] == first['variants']
    assert second['photos'][PHOTO]['asset_id'] != first['photos'][PHOTO]['asset_id']


def test_only_a_deck_has_pins(customer):
    draft = create_draft(customer, {'feature_id': DOCUMENT, 'title': 'Harbour notes', 'source_text': 'Notes about the harbour.'})
    job = run(customer, draft)
    assert job.status == 'succeeded', job.error_code
    assert pins_of(draft) is None and 'render' not in draft_data(draft)
    assert 'render' not in job.artifacts.get().file.metadata and not kept_pictures(customer).exists()


# ---------------------------------------------------------------- slides and photos it may not have


def test_a_deck_without_photos_has_pins_and_nothing_kept(customer):
    """Photos are off here: the real fetcher gives nothing, which is a state, not a failure."""
    sections = [{**section, 'image_query': ''} for section in deck_sections()]
    draft, job = generate(customer, sections=sections, asked=[])
    pins = pins_of(draft)
    assert pins['photos'] == {} and list(pins['variants']) == [section['id'] for section in sections]
    assert not kept_pictures(customer).exists()
    assert draft_data(draft)['render']['photos'] == {}


def test_question_slides_are_drawn_again_but_never_pinned(customer, tmp_path):
    draft, job = generate(customer, sections=[{**section, 'image_query': ''} for section in deck_sections()])
    pins = pins_of(draft)
    assert 'q1' not in pins['variants'] and 'q2' not in pins['variants']
    assert job.artifacts.get().file.metadata['layouts'][-2:] == ['questions', 'questions']
    assert job.artifacts.get().file.metadata['variants'][-2:] == ['', '']
    redraw(customer, draft, tmp_path / 'again.pptx')
    assert slide_xml(tmp_path / 'again.pptx') == slide_xml(delivered(job))


def test_a_deck_of_one_slide_and_a_deck_without_a_design_have_pins_too(customer, tmp_path):
    only = [{**deck_sections()[3], 'image_query': ''}]
    draft, job = generate(customer, sections=only, asked=[])
    assert list(pins_of(draft)['variants']) == [only[0]['id']]
    redraw(customer, draft, tmp_path / 'one.pptx')
    assert slide_xml(tmp_path / 'one.pptx') == slide_xml(delivered(job))

    plain, job = generate(customer, sections=[{**section, 'image_query': ''} for section in deck_sections()], asked=[], design=None)
    pins = pins_of(plain)
    assert pins['design'] == '' and set(pins['variants'].values()) == {''}, 'a deck with no design is drawn by the classic drawers'
    redraw(customer, plain, tmp_path / 'plain.pptx')
    assert slide_xml(tmp_path / 'plain.pptx') == slide_xml(delivered(job))


def test_a_picture_the_deck_could_not_place_draws_the_same_text_slide_again(customer, stock_photos, monkeypatch, tmp_path):
    """The slide went to its text layout when the job drew it: drawn again, the same bytes take it the same way."""
    fetch = stock.fetch_for_deck

    def unplaceable(sections, **kwargs):
        result = fetch(sections, **kwargs)
        result.photos[PHOTO] = {**result.photos[PHOTO], 'jpeg': b'not a picture'}
        return result
    monkeypatch.setattr(stock, 'fetch_for_deck', unplaceable)
    draft, job = generate(customer)
    artifact = job.artifacts.get().file
    assert artifact.metadata['layouts'][5] != 'image_split' and [entry['slide'] for entry in artifact.metadata['photos']] == [1]
    result = redraw(customer, draft, tmp_path / 'again.pptx')
    assert slide_xml(tmp_path / 'again.pptx') == slide_xml(delivered(job))
    assert result['metadata']['repinned'] == [] and result['metadata']['variants'] == artifact.metadata['variants']


# ---------------------------------------------------------------- an edit, and nothing else


def test_an_edit_redraws_only_the_slide_it_touches(customer, stock_photos, tmp_path):
    draft, job = generate(customer)
    pins = pins_of(draft)
    before = slide_xml(delivered(job))
    # Long enough that the deck, drawn afresh, would set all its lists smaller.
    longest = '\n'.join(fixtures.words('en', 26, 3 * n) for n in range(6))
    edited = edit_section(customer, draft, LIST, body=longest)
    result = redraw(customer, edited, tmp_path / 'edited.pptx')
    after = slide_xml(tmp_path / 'edited.pptx')
    assert {number for number in before if before[number] != after[number]} == {5}
    assert result['metadata']['body_size'] == pins['body_size']
    assert media(tmp_path / 'edited.pptx') == media(delivered(job))

    # Which is the pins' doing: without them the whole deck moves.
    data = unpack(edited.encrypted_data)
    fresh = render_pptx(data['content'], tmp_path / 'fresh.pptx', data['output_locale'], 'user_document',
                        style=render_style(customer, data, feature_id=SLIDES), photos=stored_photos(customer, pins))
    assert fresh['metadata']['body_size'] < pins['body_size']


def test_a_new_title_reshuffles_nothing(customer, stock_photos, tmp_path):
    draft, job = generate(customer)
    pins = pins_of(draft)
    renamed = update_draft(customer, draft.id, {'version': draft.version, 'title': 'Something else entirely'})
    data = unpack(renamed.encrypted_data)
    assert data['content']['title'] == 'Something else entirely'
    result = redraw(customer, renamed, tmp_path / 'renamed.pptx')
    assert slide_xml(tmp_path / 'renamed.pptx') == slide_xml(delivered(job))
    assert result['metadata']['repinned'] == [] and result['metadata']['deck_seed'] == pins['deck_seed']

    # Which is the seed's doing: without the pins this title walks another order.
    fresh = render_pptx(data['content'], tmp_path / 'fresh.pptx', data['output_locale'], 'user_document',
                        style=render_style(customer, data, feature_id=SLIDES), photos=stored_photos(customer, pins))
    assert fresh['metadata']['variants'] != result['metadata']['variants']


def test_a_slide_added_later_takes_a_variant_no_other_slide_holds(customer, stock_photos, tmp_path):
    draft, job = generate(customer, asked=[])
    pins = pins_of(draft)
    data = unpack(draft.encrypted_data)
    content = copy.deepcopy(data['content'])
    content['sections'].append({**fixtures.light('cards', 3), 'id': 's99'})
    added = update_draft(customer, draft.id, {'version': draft.version, 'content': content})
    result = redraw(customer, added, tmp_path / 'added.pptx')
    drawn = dict(zip((section['id'] for section in content['sections']), result['metadata']['variants']))
    assert result['metadata']['repinned'] == [], 'a slide with no pin is not a pin that moved'
    assert drawn['s99'].startswith('cards.') and drawn['s99'] not in (pins['variants'][CARDS], pins['variants'][MORE_CARDS])
    assert all(drawn[section_id] == variant for section_id, variant in pins['variants'].items())


def test_a_cover_with_no_heading_shows_the_new_title_and_only_it_moves(tmp_path):
    content = {'title': TITLE, 'questions': [], 'citations': [],
               'sections': [{'id': COVER, 'heading': '', 'body': 'Spring review', 'layout': 'cover'},
                            *[{**section, 'image_query': ''} for section in deck_sections()[1:]]]}
    style = {'deck_design': DESIGN}
    first = render_pptx(content, tmp_path / 'first.pptx', style=style)['metadata']
    pins = {'body_size': first['body_size'], 'deck_seed': first['deck_seed'],
            'variants': dict(zip((section['id'] for section in content['sections']), first['variants']))}
    render_pptx({**content, 'title': 'Something else entirely'}, tmp_path / 'second.pptx', style=style, pins=pins)
    before, after = slide_xml(tmp_path / 'first.pptx'), slide_xml(tmp_path / 'second.pptx')
    assert {number for number in before if before[number] != after[number]} == {1}


# ---------------------------------------------------------------- a pin that no longer holds


def simple_deck(*extra):
    sections = [{'id': COVER, 'heading': 'Harbour logistics', 'body': 'Spring review', 'layout': 'cover'},
                {**fixtures.light('cards', 3), 'id': CARDS}, {**fixtures.light('cards', 3), 'id': MORE_CARDS},
                {**fixtures.light('process', 4), 'id': STEPS}, *extra]
    return {'title': TITLE, 'questions': [], 'citations': [], 'sections': sections}


def pins_from(result, content):
    metadata = result['metadata']
    return {'body_size': metadata['body_size'], 'deck_seed': metadata['deck_seed'],
            'variants': dict(zip((section['id'] for section in content['sections']), metadata['variants']))}


def too_long(section):
    """Every card as long as a client may send it: more than any variant holds whole."""
    return {**section, 'items': [{**item, 'text': fixtures.line('en', 590), 'label': fixtures.line('en', 150)} for item in section['items']]}


def test_a_pinned_variant_that_no_longer_fits_gives_way_and_is_reported(tmp_path):
    content = simple_deck()
    style = {'deck_design': DESIGN}
    first = render_pptx(content, tmp_path / 'first.pptx', style=style)
    pins = pins_from(first, content)
    assert pins['variants'][CARDS] != f'cards.{CLASSIC}'
    before = slide_xml(tmp_path / 'first.pptx')

    edited = copy.deepcopy(content)
    edited['sections'][1] = too_long(edited['sections'][1])
    result = render_pptx(edited, tmp_path / 'edited.pptx', style=style, pins=pins)
    after = slide_xml(tmp_path / 'edited.pptx')
    drawn = dict(zip((section['id'] for section in edited['sections']), result['metadata']['variants']))
    assert drawn[CARDS] != pins['variants'][CARDS] and result['metadata']['repinned'] == [CARDS]
    assert {number for number in before if before[number] != after[number]} == {2}
    assert drawn[MORE_CARDS] == pins['variants'][MORE_CARDS] and drawn[STEPS] == pins['variants'][STEPS]


def test_a_slide_that_chooses_again_leaves_every_other_pin_to_its_own_slide(tmp_path):
    content = simple_deck()
    style = {'deck_design': DESIGN}
    pool = variants.load('cards')
    first = render_pptx(content, tmp_path / 'first.pptx', style=style)
    pins = pins_from(first, content)
    # In this deck's own order, the slide's pin is gone and the variant after it is another slide's.
    order = [name for name in variants.order('cards', pins['deck_seed']) if name != CLASSIC and pool[name].holds(content['sections'][1], [])]
    pins['variants'][CARDS], pins['variants'][MORE_CARDS] = 'cards.retired_since', f'cards.{order[0]}'
    result = render_pptx(content, tmp_path / 'again.pptx', style=style, pins=pins)
    drawn = dict(zip((section['id'] for section in content['sections']), result['metadata']['variants']))
    assert result['metadata']['repinned'] == [CARDS]
    assert drawn[MORE_CARDS] == f'cards.{order[0]}' and drawn[CARDS].startswith('cards.') and drawn[CARDS] != drawn[MORE_CARDS]


@pytest.mark.parametrize('pin', ['cards.retired_since', 'process.never_was', 'nonsense', 'cards.'])
def test_a_pin_for_nothing_this_slide_can_draw_is_passed_over(tmp_path, pin):
    content = simple_deck()
    style = {'deck_design': DESIGN}
    first = render_pptx(content, tmp_path / 'first.pptx', style=style)
    pins = pins_from(first, content)
    pins['variants'][CARDS] = pin
    result = render_pptx(content, tmp_path / 'again.pptx', style=style, pins=pins)
    assert result['metadata']['repinned'] == [CARDS]
    assert result['metadata']['variants'][1].startswith('cards.')


def test_a_pin_to_another_layout_gives_way_when_the_slide_changes_layout(tmp_path):
    content = simple_deck()
    style = {'deck_design': DESIGN}
    first = render_pptx(content, tmp_path / 'first.pptx', style=style)
    pins = pins_from(first, content)
    edited = copy.deepcopy(content)
    edited['sections'][1] = {**fixtures.light('process', 4), 'id': CARDS}
    result = render_pptx(edited, tmp_path / 'edited.pptx', style=style, pins=pins)
    assert result['metadata']['repinned'] == [CARDS]
    assert result['metadata']['variants'][1].startswith('process.')
    assert result['metadata']['variants'][1] != pins['variants'][STEPS]


def test_a_variant_that_holds_too_little_is_not_kept_by_its_pin(tmp_path):
    """A pin is held to what `choose` holds a variant to: it may not draw a count it was not made for."""
    content = simple_deck()
    style = {'deck_design': DESIGN}
    narrow = next(variant for variant in variants.load('cards').values() if variant.counts and not variant.holds(content['sections'][1], []))
    first = render_pptx(content, tmp_path / 'first.pptx', style=style)
    pins = pins_from(first, content)
    pins['variants'][CARDS] = narrow.id
    result = render_pptx(content, tmp_path / 'again.pptx', style=style, pins=pins)
    assert result['metadata']['variants'][1] != narrow.id and result['metadata']['repinned'] == [CARDS]


def test_a_pin_to_classic_always_holds(tmp_path):
    content = simple_deck()
    style = {'deck_design': DESIGN}
    pins = pins_from(render_pptx(content, tmp_path / 'first.pptx', style=style), content)
    pins['variants'][CARDS] = f'cards.{CLASSIC}'
    result = render_pptx(content, tmp_path / 'again.pptx', style=style, pins=pins)
    assert result['metadata']['variants'][1] == f'cards.{CLASSIC}' and result['metadata']['repinned'] == []


def test_a_photo_no_longer_there_sends_its_slide_to_a_text_layout_and_is_reported(tmp_path):
    content = simple_deck({**fixtures.light('image_split', 3), 'id': PHOTO})
    style = {'deck_design': DESIGN}
    photo = {'jpeg': picture(1), 'width': 1600, 'height': 1000, **pixabay_entry(1)}
    pins = pins_from(render_pptx(content, tmp_path / 'first.pptx', style=style, photos={PHOTO: photo}), content)
    assert pins['variants'][PHOTO].startswith('image_split.')
    result = render_pptx(content, tmp_path / 'again.pptx', style=style, pins=pins)
    assert result['metadata']['repinned'] == [PHOTO] and not result['metadata']['photos']
    before, after = slide_xml(tmp_path / 'first.pptx'), slide_xml(tmp_path / 'again.pptx')
    assert {number for number in before if before[number] != after[number]} == {5}


def test_a_variant_that_breaks_on_its_trial_never_costs_the_deck(tmp_path, monkeypatch):
    content = simple_deck()
    style = {'deck_design': DESIGN}
    pins = pins_from(render_pptx(content, tmp_path / 'first.pptx', style=style), content)
    chosen = variants.get(pins['variants'][CARDS])

    def broken(context, section, lines):
        raise ValueError('a drawer with a bug')
    monkeypatch.setattr(chosen, 'draw', broken)
    result = render_pptx(content, tmp_path / 'again.pptx', style=style, pins=pins)
    assert result['metadata']['repinned'] == [CARDS] and result['metadata']['variants'][1] != chosen.id


def test_the_pinned_design_beats_the_style(tmp_path):
    content = simple_deck()
    first = render_pptx(content, tmp_path / 'first.pptx', style={'deck_design': DESIGN})
    pins = {**pins_from(first, content), 'design': DESIGN}
    again = render_pptx(content, tmp_path / 'again.pptx', style={}, pins=pins)
    assert again['metadata']['design'] == DESIGN and slide_xml(tmp_path / 'again.pptx') == slide_xml(tmp_path / 'first.pptx')
    plain = render_pptx(content, tmp_path / 'plain.pptx', style={'deck_design': DESIGN}, pins={'design': ''})
    assert plain['metadata']['design'] == '' and not any(plain['metadata']['variants'])


def test_the_bench_can_still_force_a_variant_past_any_pin(tmp_path):
    """`_variant` is the bench's and the tests': it skips the trial, and a pin does not stand in its way."""
    content = simple_deck()
    style = {'deck_design': DESIGN}
    pins = pins_from(render_pptx(content, tmp_path / 'first.pptx', style=style), content)
    forced = next(variant.id for variant in variants.load('cards').values() if variant.id != pins['variants'][CARDS] and variant.name != CLASSIC)
    edited = copy.deepcopy(content)
    edited['sections'][1]['_variant'] = forced
    result = render_pptx(edited, tmp_path / 'forced.pptx', style=style, pins=pins)
    assert result['metadata']['variants'][1] == forced


def test_another_process_draws_the_same_slides(tmp_path):
    """A deck is made by the worker and redrawn elsewhere: nothing in a drawer may follow a process's hash order."""
    content = {'title': TITLE, 'questions': questions(), 'citations': [],
               'sections': [{'id': COVER, 'heading': 'Harbour logistics', 'body': 'Spring review', 'layout': 'cover'},
                            *[{**fixtures.light(kind, fixtures.RANGES[kind][0]), 'id': f'{kind}-1', 'image_query': ''} for kind in fixtures.RANGES if kind not in ('image_split', 'image_full')]]}
    style = {'deck_design': DESIGN}
    result = render_pptx(content, tmp_path / 'here.pptx', 'en', style=style)
    (tmp_path / 'deck.json').write_text(json.dumps([content, style, pins_from(result, content)]))
    script = ('import json,sys,django\ndjango.setup()\nfrom pathlib import Path\nfrom apps.studio.slides import render_pptx\n'
              'content,style,pins=json.loads(Path(sys.argv[1]).read_text())\nrender_pptx(content,Path(sys.argv[2]),"en",style=style,pins=pins)\n')
    for seed in ('1', '2'):
        subprocess.run([sys.executable, '-c', script, str(tmp_path / 'deck.json'), str(tmp_path / f'{seed}.pptx')], check=True, timeout=180,
                       cwd=django_settings.BASE_DIR, env={**os.environ, 'PYTHONHASHSEED': seed, 'DJANGO_SETTINGS_MODULE': 'config.settings'})
        assert slide_xml(tmp_path / f'{seed}.pptx') == slide_xml(tmp_path / 'here.pptx')


# ---------------------------------------------------------------- the server's alone


def test_a_client_cannot_send_pins(customer, stock_photos):
    forged = {'design': 'x', 'deck_seed': 'x', 'body_size': 99, 'variants': {COVER: 'cards.classic'}, 'photos': {}}
    with pytest.raises(DomainError, match='invalid_parameters'):
        create_draft(customer, {'feature_id': SLIDES, 'prompt': 'A deck about harbours', '_render': forged})
    with pytest.raises(DomainError, match='invalid_parameters'):
        create_draft(customer, {'feature_id': SLIDES, 'prompt': 'A deck about harbours', 'options': {'_render': forged}})
    draft, _ = generate(customer)
    pins = pins_of(draft)
    client = login_client(customer)
    for body in ({'_render': forged}, {'render': forged}, {'options': {'_render': forged}}):
        answer = client.patch(f'/api/v1/generation/drafts/{draft.id}', json.dumps({'version': draft.version, **body}), content_type='application/json')
        assert answer.status_code == 400, answer.content
    assert pins_of(draft) == pins and draft.version == 3


def test_a_client_cannot_say_an_outline_was_rebuilt(customer, stock_photos):
    """That would keep a deck from its pins."""
    with pytest.raises(DomainError, match='invalid_parameters'):
        create_draft(customer, {'feature_id': SLIDES, 'prompt': 'A deck about harbours', '_rebuilt_version': 99})
    with pytest.raises(DomainError, match='invalid_parameters'):
        create_draft(customer, {'feature_id': SLIDES, 'prompt': 'A deck about harbours', 'options': {'_rebuilt_version': 99}})
    draft = deck_draft(customer)
    client = login_client(customer)
    for body in ({'_rebuilt_version': 99}, {'options': {'_rebuilt_version': 99}}):
        answer = client.patch(f'/api/v1/generation/drafts/{draft.id}', json.dumps({'version': draft.version, **body}), content_type='application/json')
        assert answer.status_code == 400, answer.content
    assert run(customer, draft).status == 'succeeded' and pins_of(draft)


def test_a_client_cannot_choose_a_variant_through_a_slide(customer):
    draft = deck_draft(customer, sections=[{**section, 'image_query': '', '_variant': 'cards.classic', '_questions': [{'number': 1}]} for section in deck_sections()], asked=[])
    for section in unpack(draft.encrypted_data)['content']['sections']:
        assert '_variant' not in section and '_questions' not in section


def test_a_draft_shows_its_pins_without_any_address(customer, stock_photos):
    draft, _ = generate(customer)
    pins = pins_of(draft)
    shown = draft_data(draft)
    assert '_render' not in shown
    assert set(shown['render']) == {'design', 'deck_seed', 'body_size', 'variants', 'photos'}
    assert {key: shown['render'][key] for key in ('design', 'deck_seed', 'body_size', 'variants')} == {
        key: pins[key] for key in ('design', 'deck_seed', 'body_size', 'variants')}
    for section_id, photo in shown['render']['photos'].items():
        assert set(photo) == {'asset_id', 'candidates'} and photo['asset_id'] == pins['photos'][section_id]['asset_id']
        assert [set(offered) for offered in photo['candidates']] == [{'asset_id'}, {'asset_id'}], 'a candidate with no copy has nothing to show'
    written = json.dumps(shown, default=str)
    assert 'http' not in written and 'pixabay' not in written and 'page_url' not in written

    answer = login_client(customer).get(f'/api/v1/generation/drafts/{draft.id}')
    assert answer.status_code == 200 and answer.json()['render']['variants'] == pins['variants']
    assert '_render' not in answer.json() and 'pixabay' not in answer.content.decode()


def test_a_draft_with_no_deck_yet_shows_no_pins_and_an_old_one_keeps_working(customer, tmp_path):
    draft = deck_draft(customer, sections=[{**section, 'image_query': ''} for section in deck_sections()])
    assert 'render' not in draft_data(draft), 'an old draft looks exactly like this one'
    saved = edit_section(customer, draft, LIST, heading='Edited before any deck')
    assert '_render' not in unpack(saved.encrypted_data)
    job = run(customer, saved)
    assert job.status == 'succeeded', job.error_code


def test_the_contract_describes_what_a_draft_shows(customer, stock_photos):
    import jsonschema
    draft, _ = generate(customer)
    contract = json.loads((django_settings.BASE_DIR / 'contracts' / 'public.openapi.json').read_text())
    schemas = contract['components']['schemas']
    assert 'render' in schemas['GenerationDraft']['properties'] and 'render' not in schemas['GenerationDraft']['required']
    shown = json.loads(json.dumps(draft_data(draft)['render'], default=str))
    jsonschema.validate(shown, schemas['DeckPins'], format_checker=jsonschema.FormatChecker())


def test_the_model_never_reads_the_pins(customer, stock_photos):
    draft, _ = generate(customer)
    data = unpack(draft.encrypted_data)
    save_config('ai', {'mode': 'openai', 'model': 'test-model', 'api_key': 'sk-offline-test'})
    with_pins = provider.request_body(ai_config(), data, SLIDES)
    without = provider.request_body(ai_config(), {key: value for key, value in data.items() if key != '_render'}, SLIDES)
    assert with_pins == without and data['_render']['deck_seed'] not in json.dumps(with_pins, ensure_ascii=False)


def test_only_the_server_reads_that_an_outline_was_rebuilt(customer):
    rebuilt = saved(customer, deck_draft(customer), prompt='A different deck about ferries')
    data = unpack(rebuilt.encrypted_data)
    assert data['_rebuilt_version'] == rebuilt.version
    assert '_rebuilt_version' not in draft_data(rebuilt)
    answer = login_client(customer).get(f'/api/v1/generation/drafts/{rebuilt.id}')
    assert answer.status_code == 200 and '_rebuilt_version' not in answer.json()
    save_config('ai', {'mode': 'openai', 'model': 'test-model', 'api_key': 'sk-offline-test'})
    without = {key: value for key, value in data.items() if key != '_rebuilt_version'}
    assert provider.request_body(ai_config(), data, SLIDES) == provider.request_body(ai_config(), without, SLIDES)


# ---------------------------------------------------------------- as long as the deck


def a_result_settled(customer, quoted, feature, draft, key):
    """A job naming this draft, settled with a file of its own: it leaves the draft's pins as they are, as a redraw will."""
    quote = generation_quote(customer, quoted.id, GenerationDraft.objects.get(pk=quoted.pk).version)
    job = Job.objects.create(account=customer, quote=quote, feature_id=feature, parameters={'generation_draft_id': str(draft.id)}, input_ids=[],
                             policy=quote.policy, idempotency_key=key, request_hash='x')
    folder = storage.storage_path(f'outputs/{customer.id}/{job.id}')
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'result.pdf').write_bytes(b'%PDF')
    return settle_job(job.id, 'succeeded', outputs=[{'path': str((folder / 'result.pdf').resolve()), 'name': 'result.pdf', 'mime_type': 'application/pdf', 'page_count': 1}])


def test_pictures_live_as_long_as_the_deck_and_a_later_result_extends_them(customer, stock_photos, clock):
    draft, job = generate(customer)
    artifact = job.artifacts.get().file
    pictures = list(kept_pictures(customer))
    assert len(pictures) == 2 * (1 + 2), 'two photos, and two small copies for each'
    deadline = artifact.expires_at
    assert draft.expires_at == deadline and all(picture.expires_at == deadline for picture in pictures)

    # Hour 23: everything is still there.
    clock(23)
    cleanup_expired()
    assert GenerationDraft.objects.filter(pk=draft.pk).exists()
    for asset in FileAsset.objects.filter(pk__in=[picture.pk for picture in pictures]):
        assert asset.state == 'ready' and storage.exists(asset.object_key)

    # A later result that keeps the pins, as a redraw will, carries their pictures to its own deadline, and shortens nothing.
    longer = pictures[0]
    far = timezone.now() + timedelta(days=30)
    FileAsset.objects.filter(pk=longer.pk).update(expires_at=far)
    second = a_result_settled(customer, draft, SLIDES, draft, 'a-later-result')
    new_deadline = second.artifacts.get().file.expires_at
    assert new_deadline > deadline
    draft.refresh_from_db()
    assert draft.expires_at == new_deadline
    for asset in FileAsset.objects.filter(pk__in=[picture.pk for picture in pictures[1:]]):
        assert asset.expires_at == new_deadline
    assert FileAsset.objects.get(pk=longer.pk).expires_at == far

    # Hour 30, past where they first would have gone: the pins still draw the deck.
    clock(30)
    cleanup_expired()
    assert GenerationDraft.objects.filter(pk=draft.pk).exists()
    pins = pins_of(draft)
    for photo in pins['photos'].values():
        assert FileAsset.objects.get(pk=photo['asset_id']).state == 'ready'
    assert storage.read_bytes(FileAsset.objects.get(pk=pins['photos'][PHOTO]['asset_id']).object_key)

    # Past that deadline they go with the deck, and leave no row: up to sixty a deck, and every key is read back each cleanup.
    clock(48)
    cleanup_expired()
    assert not GenerationDraft.objects.filter(pk=draft.pk).exists()
    assert FileAsset.objects.get(pk=second.artifacts.get().file_id).state == 'deleted'
    assert not any(storage.exists(picture.object_key) for picture in pictures[1:])
    assert list(kept_pictures(customer)) == [longer] and FileAsset.objects.get(pk=longer.pk).state == 'ready'


def test_pictures_the_pins_no_longer_name_go_by_their_own_clock(customer, stock_photos, clock):
    """Or a customer generating again each day would keep every earlier picture alive, none of them pinned."""
    draft, job = generate(customer)
    deadline = job.artifacts.get().file.expires_at
    replaced = list(kept_pictures(customer).values_list('pk', flat=True))

    clock(20)
    second = run(customer, GenerationDraft.objects.get(pk=draft.pk))
    assert second.status == 'succeeded', second.error_code
    new_deadline = second.artifacts.get().file.expires_at
    draft.refresh_from_db()
    assert draft.expires_at == new_deadline
    assert {picture.expires_at for picture in FileAsset.objects.filter(pk__in=replaced)} == {deadline}
    current = kept_pictures(customer).exclude(pk__in=replaced)
    assert current.count() == len(replaced) and {picture.expires_at for picture in current} == {new_deadline}
    pins = pins_of(draft)
    named = {pins['photos'][PHOTO]['asset_id'], *(offered['asset_id'] for offered in pins['photos'][PHOTO]['candidates'] if offered['asset_id'])}
    assert named <= {str(pk) for pk in current.values_list('pk', flat=True)}

    # Hour 30: the replaced ones are gone, the draft and what its pins name are not.
    clock(30)
    cleanup_expired()
    assert not FileAsset.objects.filter(pk__in=replaced).exists()
    assert {str(pk) for pk in current.values_list('pk', flat=True)} >= named
    assert stored_photos(customer, pins)[PHOTO]['jpeg']


def test_a_new_plan_leaves_the_pictures_of_the_deck_it_replaces_to_their_own_clock(customer, stock_photos, clock):
    draft, job = generate(customer)
    deadline = job.artifacts.get().file.expires_at
    clock(20)
    draft.refresh_from_db()
    quote = create_outline_quote(customer, draft.id, draft.version)
    planned, _ = submit_job(customer, quote.id, 'outline-after-deck')
    planned = execute_job(planned.id)
    assert planned.status == 'succeeded', planned.error_code
    draft.refresh_from_db()
    assert draft.expires_at > deadline
    assert {picture.expires_at for picture in kept_pictures(customer)} == {deadline}


def test_a_save_that_rebuilt_the_outline_leaves_its_pictures_to_their_own_clock(customer, stock_photos, clock):
    draft, job = generate(customer)
    deadline = job.artifacts.get().file.expires_at
    clock(20)
    draft = update_draft(customer, draft.id, {'version': draft.version, 'prompt': 'A different deck about ferries'})
    later = a_result_settled(customer, draft, SLIDES, draft, 'a-result-of-the-new-plan')
    draft.refresh_from_db()
    assert draft.expires_at == later.artifacts.get().file.expires_at > deadline
    assert {picture.expires_at for picture in kept_pictures(customer)} == {deadline}


def test_a_job_that_fails_extends_nothing(customer, stock_photos, clock, monkeypatch):
    draft, job = generate(customer)
    deadline = job.artifacts.get().file.expires_at
    clock(5)

    def broken(*args, **kwargs):
        raise OSError('the renderer broke')
    monkeypatch.setattr(execution, 'render_pptx', broken)
    failed = run(customer, GenerationDraft.objects.get(pk=draft.pk))
    assert failed.status == 'failed'
    draft.refresh_from_db()
    assert draft.expires_at == deadline
    assert all(picture.expires_at == deadline for picture in kept_pictures(customer))


def test_a_result_extends_only_a_generations_own_draft(settings, customer):
    """A file task has no draft to extend, and one naming another account's draft cannot reach it."""
    other = paid(settings, account(77))
    theirs = deck_draft(other, sections=[{**section, 'image_query': ''} for section in deck_sections()], asked=[])
    mine = deck_draft(customer, sections=[{**section, 'image_query': ''} for section in deck_sections()], asked=[])
    mine_until, theirs_until = mine.expires_at, theirs.expires_at

    a_result_settled(customer, mine, 'pdf.rotate', mine, 'a-file-task-naming-a-draft')
    a_result_settled(customer, mine, SLIDES, theirs, 'a-job-naming-a-foreign-draft')
    mine.refresh_from_db()
    theirs.refresh_from_db()
    assert mine.expires_at == mine_until and theirs.expires_at == theirs_until


# ---------------------------------------------------------------- never at the deck's expense


def test_a_picture_that_cannot_be_kept_costs_only_its_pin(customer, stock_photos, monkeypatch, caplog):
    real = storage.write
    calls = []

    def flaky(key, data, content_type='', later=False):
        calls.append(key)
        if len(calls) == 1:
            raise OSError(f'No space left to write {key}')
        return real(key, data, content_type, later=later)
    monkeypatch.setattr(storage, 'write', flaky)
    draft, job = generate(customer)
    pins = pins_of(draft)
    assert job.artifacts.get().file.page_count == 10
    assert pins['photos'][COVER]['asset_id'] is None, 'the slide simply has no pin for that photo'
    assert pins['photos'][PHOTO]['asset_id'] and len(pins['photos'][COVER]['candidates']) == stock.CANDIDATES
    assert 'OSError' in caplog.text and 'No space' not in caplog.text and calls[0] not in caplog.text
    assert 'pixabay' not in caplog.text


def test_storage_that_fails_altogether_does_not_fail_the_job(customer, stock_photos, monkeypatch, caplog):
    def refuse(*args, **kwargs):
        raise OSError('bucket and volume are gone')
    monkeypatch.setattr(storage, 'write', refuse)
    draft, job = generate(customer)
    pins = pins_of(draft)
    assert job.status == 'succeeded' and 'images_skipped' not in job.warnings
    assert not kept_pictures(customer).exists()
    assert pins['variants'] and all(photo['asset_id'] is None for photo in pins['photos'].values())
    shown = draft_data(draft)['render']['photos']
    assert shown[PHOTO] == {'asset_id': None, 'candidates': []}, '"no candidates" is a state the reader knows'
    assert 'are gone' not in caplog.text


def test_a_row_that_cannot_be_made_leaves_no_file_registered(customer, stock_photos, monkeypatch):
    real = FileAsset.objects.create

    def refuse_pictures(**fields):
        if fields.get('metadata', {}).get('kind') == 'deck_photo':
            raise ValueError('no row')
        return real(**fields)
    monkeypatch.setattr(FileAsset.objects, 'create', refuse_pictures)
    draft, job = generate(customer)
    assert job.status == 'succeeded'
    assert all(photo['asset_id'] is None for photo in pins_of(draft)['photos'].values())
    assert not StoredObject.objects.filter(key__startswith=f'inputs/{customer.id}/').exists()


def test_pins_that_cannot_be_made_or_written_cost_nothing_but_the_pins(customer, stock_photos, monkeypatch, caplog):
    def broken():
        raise RuntimeError('no digest')
    monkeypatch.setattr(deck_designs, 'version', broken)
    draft, job = generate(customer)
    metadata = job.artifacts.get().file.metadata
    assert job.status == 'succeeded' and pins_of(draft) is None
    assert 'deck_seed' not in metadata and 'render' not in metadata, 'the title stays out of the file, pins or no pins'
    assert 'RuntimeError' in caplog.text and 'no digest' not in caplog.text


def test_a_write_that_fails_leaves_the_draft_as_the_job_left_it(customer, stock_photos, monkeypatch, caplog):
    real = execution.unpack
    reads = []

    def second_read_fails(value):
        reads.append(value)
        if len(reads) == 2:
            raise ValueError('cannot read the draft')
        return real(value)
    monkeypatch.setattr(execution, 'unpack', second_read_fails)
    draft, job = generate(customer)
    assert job.status == 'succeeded' and draft.version == 3 and pins_of(draft) is None
    assert 'ValueError' in caplog.text and 'cannot read' not in caplog.text


def test_pictures_wait_for_the_sync_not_the_job(customer, stock_photos, bucket, django_capture_on_commit_callbacks):  # noqa: F811
    """Dozens of small files must not hold a job up on a slow bucket until its lease runs out."""
    with django_capture_on_commit_callbacks(execute=True):
        draft, job = generate(customer)
    keys = set(kept_pictures(customer).values_list('object_key', flat=True))
    assert keys and job.artifacts.get().file.object_key in bucket.keys(), 'the deck itself went straight up'
    assert not keys & bucket.keys()
    assert StoredObject.objects.filter(key__in=keys, remote=False, content_type='image/jpeg').count() == len(keys)

    storage.sync()
    assert keys <= bucket.keys()
    # And with the working copies let go, the pins still draw the deck, through the store.
    for key in keys:
        storage.storage_path(key).unlink()
    pins = pins_of(draft)
    assert stored_photos(customer, pins)[PHOTO]['jpeg'] == picture(2)


def test_a_kept_picture_is_private_to_the_platform(customer, stock_photos):
    generate(customer)
    for asset in kept_pictures(customer):
        path = storage.storage_path(asset.object_key)
        assert path.stat().st_mode & 0o777 == 0o600 and asset.object_key.startswith(f'inputs/{customer.id}/')
        assert path.read_bytes()[:3] == b'\xff\xd8\xff'
    assert not list(storage.storage_path(f'inputs/{customer.id}').glob('.*part'))


def test_a_deck_the_policy_check_refuses_keeps_nothing(paid_deck, pixabay, monkeypatch):  # noqa: F811
    """A job that fails leaves its draft byte for byte as it was, which is what its retry is checked against."""
    monkeypatch.setattr('apps.studio.scripts.artifact_violations', lambda *args: True)
    _, job = run_paid_deck(paid_deck)
    assert job.status == 'failed' and job.error_code == 'script_policy'
    draft = GenerationDraft.objects.get(pk=job.parameters['generation_draft_id'])
    assert draft.version == 1 and hashlib.sha256(bytes(draft.encrypted_data)).hexdigest() == job.parameters['snapshot']
    assert pins_of(draft) is None and not kept_pictures(paid_deck).exists()


def test_a_paid_deck_keeps_what_the_model_looked_at_and_draws_again_with_no_call(paid_deck, model, pixabay, tmp_path):  # noqa: F811
    pixabay.hits = [hit(n, tags='modern, office, team, meeting') for n in range(1, 7)]
    model.picks = [{'slide': 's2', 'photo': 2}, {'slide': 's3', 'photo': 3}]
    _, job = run_paid_deck(paid_deck)
    assert job.status == 'succeeded', job.error_code
    draft = GenerationDraft.objects.get(pk=job.parameters['generation_draft_id'])
    pins = pins_of(draft)
    assert set(pins['photos']) == {'s2', 's3'}
    # The same six hits come back for both, so each slide's shortlist is the first four.
    for section_id in ('s2', 's3'):
        offered = pins['photos'][section_id]['candidates']
        assert [entry['id'] for entry in offered] == [1, 2, 3, 4] and all(entry['asset_id'] for entry in offered)
        assert all('_1280' in entry['url'] for entry in offered)
    assert kept_pictures(paid_deck, candidate=True).count() == 8 and kept_pictures(paid_deck, candidate=False).count() == 2
    assert {asset.metadata['id'] for asset in kept_pictures(paid_deck, candidate=False)} == {2, 3}

    calls, asked = len(pixabay.calls), len(model.requests)
    redraw(paid_deck, draft, tmp_path / 'again.pptx')
    assert slide_xml(tmp_path / 'again.pptx') == slide_xml(delivered(job))
    assert media(tmp_path / 'again.pptx') == media(delivered(job))
    assert (len(pixabay.calls), len(model.requests)) == (calls, asked)


# ---------------------------------------------------------------- the shortlist


def test_a_slides_shortlist_comes_with_the_copies_the_model_saw_and_no_other_call(model, pixabay):  # noqa: F811
    pixabay.hits = [hit(n, tags='office, meeting') for n in range(1, 7)]
    model.picks = [{'slide': 's2', 'photo': 2}]
    result = stock.fetch_for_deck(slides('office meeting'), cap=6, budget=60)
    shortlist = result.candidates['s2']
    assert [entry['id'] for entry in shortlist] == [1, 2, 3, 4], 'at most CANDIDATES, best first'
    for entry in shortlist:
        assert set(entry) == {'provider', 'id', 'preview', 'url', 'page_url', 'jpeg'}
        assert entry['provider'] == 'pixabay' and entry['preview'].endswith('_640.jpg') and entry['url'].endswith('_1280.jpg')
        assert entry['jpeg'][:3] == b'\xff\xd8\xff'
    # One search, the four copies the model looks at anyway, and the photo it chose: nothing for the shortlist.
    assert len(pixabay.searches) == 1 and len(pixabay.calls) == 1 + 4 + 1
    assert result.photos['s2']['id'] == 2


def test_with_no_model_a_shortlist_has_addresses_and_no_bytes(pixabay):  # noqa: F811
    pixabay.hits = [hit(n, tags='office, meeting') for n in range(1, 7)]
    result = stock.fetch_for_deck(slides('office meeting'), cap=6, budget=30)
    assert [entry['id'] for entry in result.candidates['s2']] == [1, 2, 3, 4]
    assert all('jpeg' not in entry for entry in result.candidates['s2'])
    assert len(pixabay.calls) == 1 + 1, 'one search and the chosen photo'


def test_with_too_little_time_a_shortlist_has_no_bytes(model, pixabay):  # noqa: F811
    result = stock.fetch_for_deck(slides('office'), cap=6, budget=stock.PICK_MIN_SECONDS)
    assert result.candidates['s2'] and all('jpeg' not in entry for entry in result.candidates['s2'])
    assert model.requests == []


def test_a_copy_that_would_not_download_leaves_that_candidate_without_bytes(model, pixabay, monkeypatch):  # noqa: F811
    pixabay.hits = [hit(n, tags='office') for n in range(1, 5)]
    model.picks = [{'slide': 's2', 'photo': 1}]

    def flaky(request, timeout, handler):
        if 'img3_640' in request.full_url:
            raise OSError('dropped')
        return pixabay(request, timeout, handler)
    monkeypatch.setattr(stock, '_open', flaky)
    result = stock.fetch_for_deck(slides('office'), cap=6, budget=60)
    assert [('jpeg' in entry) for entry in result.candidates['s2']] == [True, True, False, True]


@pytest.mark.parametrize('case', ['no hits', 'nothing fits', 'no preview', 'over the cap'])
def test_no_candidates_is_a_state_not_a_failure(pixabay, case):  # noqa: F811
    sections = slides('office', 'harbour')
    if case == 'no hits':
        pixabay.hits = []
    elif case == 'nothing fits':
        pixabay.hits = [hit(1, tags='sunset, beach')]
    elif case == 'no preview':
        pixabay.hits = [{**hit(1), 'webformatURL': ''}]
    result = stock.fetch_for_deck(sections, cap=1 if case == 'over the cap' else 6, budget=30)
    if case == 'over the cap':
        assert set(result.candidates) == {'s2'}, 'a slide the plan has no photo for has no shortlist either'
    else:
        assert result.candidates == {}


def test_an_unconfigured_or_failed_fetch_has_no_candidates(pixabay, monkeypatch):  # noqa: F811
    assert stock.PhotoResult().candidates == {}
    pixabay.fail = OSError('down')
    assert stock.fetch_for_deck(slides('office'), cap=6, budget=30).candidates == {}


# ---------------------------------------------------------------- only a generation holds a draft up


def test_only_a_generation_holds_up_an_edit_of_its_draft(customer):
    draft = deck_draft(customer, sections=[{**section, 'image_query': ''} for section in deck_sections()])
    quote = generation_quote(customer, draft.id, draft.version)
    drawing = Job.objects.create(account=customer, quote=quote, feature_id='deck.render', parameters=quote.parameters, input_ids=[], policy=quote.policy,
                                 idempotency_key='a-render-only-job', request_hash='x', status='queued')
    assert not draft_jobs(customer, draft.id, ('queued',))
    draft = update_draft(customer, draft.id, {'version': draft.version, 'title': 'Saved while it waits'})
    drawing.delete()

    quote = generation_quote(customer, draft.id, draft.version)
    submit_job(customer, quote.id, 'a-generation-waits')
    assert draft_jobs(customer, draft.id, ('queued',))
    with pytest.raises(DomainError, match='generation_running'):
        update_draft(customer, draft.id, {'version': draft.version, 'title': 'Too soon'})


# ---------------------------------------------------------------- the admin


def test_the_admins_list_shows_a_customers_documents_not_a_decks_pictures(customer, stock_photos):
    _, job = generate(customer)
    document = upload(customer)
    # A file with no kind recorded is a document like any other.
    bare = FileAsset.objects.create(account=customer, name='no-kind.pdf', object_key=f'inputs/{customer.id}/no-kind.pdf', mime_type='application/pdf',
                                    sha256='0' * 64, size_bytes=1, page_count=1, metadata={}, expires_at=timezone.now() + timedelta(hours=1))
    client, _ = staff_client('Support')
    page = client.get(f'/ops/users/{customer.id}').content.decode()
    assert document.name in page and job.artifacts.get().file.name in page and bare.name in page
    assert 'deck-photo-' not in page
