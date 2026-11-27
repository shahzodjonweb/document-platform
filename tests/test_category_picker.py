"""The web's category picker: the bot's AI PDF and AI Slides lists over the API, and what a picked category takes.

`GET /studio/categories` answers what customers may pick now, exactly as the
bot's lists do (catalogue.menu): nothing while the owner's switch is off or
nothing of a service is ticked, so the web opens today's description; else the
same buttons in the same order, without their emoji, each top button with its
line (index.json `hints`), each category with its own instructions (the bot's
prompt, one paragraph each, without emoji), its examples and whether it takes
files. A category's files are uploaded as `ai_source` from the web too, and
opening a category's screen is counted as the bot counts a tap on it.

The people and organisations here are invented.
"""
import copy
import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.models import AnalyticsEvent, FileAsset
from apps.studio import categories
from apps.studio.categories import catalogue
from apps.studio.categories.catalogue import CHOSEN_EVENT, EMOJI, CatalogueError, build, plain, read
from apps.studio.domain import unpack
from apps.studio.models import GenerationDraft
from operations.categories_settings import save as save_switch
from operations.integrations import save_config
from tests.test_operations import staff_client
from tests.test_platform import account, login_client
from tests.test_studio import paid

pytestmark = pytest.mark.django_db

EVERY = [entry.id for feature in catalogue.FEATURES.values() for entry in catalogue.for_feature(feature)]
TOP = {
    'ai.pdf_topic': [('pdf.mustaqil_ish', 'category'), ('pdf.kurs_ishi', 'category'), ('pdf.konspekt', 'category'),
                     ('pdf.dars_ishlanmasi', 'category'), ('pdf.test', 'category'), ('pdf.biz', 'group'),
                     ('pdf.xat', 'group'), ('other', 'other')],
    'ai.pptx': [('slides.mavzu', 'category'), ('slides.himoya', 'category'), ('slides.dars', 'category'),
                ('slides.tadbir', 'group'), ('slides.pitch', 'category'), ('slides.hisobot', 'category'),
                ('slides.kompaniya', 'category'), ('other', 'other')],
}
NOTES = ('Ota-onalar kengashi yig‘ilishi, 12-noyabr. Rais: Jasur Tursunov, kotib: Dilnoza Karimova. '
         'Kun tartibi: maktab hovlisini obodonlashtirish.')


@pytest.fixture
def switch():
    """The owner's switch, as /ops/categories saves it."""
    _, user = staff_client('Operations')

    def turn(on=True, live=tuple(EVERY)):
        save_switch({'on': 'true' if on else 'false', 'live': list(live)}, user)
    return turn


@pytest.fixture
def customer(settings):
    settings.DEBUG = True
    save_config('ai', {'mode': 'openai', 'model': 'gpt-5.6-luna', 'api_key': 'sk-offline-test-only'})
    who = paid(settings, account(77901))
    return who, login_client(who)


def lists(client, **query):
    response = client.get('/api/v1/studio/categories', query)
    assert response.status_code == 200
    return response.json()['features']


def test_nothing_is_offered_while_the_switch_is_off_or_nothing_is_ticked(customer, switch):
    _, client = customer
    assert lists(client) == {'ai.pdf_topic': [], 'ai.pptx': []}
    switch(on=True, live=())
    assert lists(client) == {'ai.pdf_topic': [], 'ai.pptx': []}
    switch(on=False)
    assert lists(client) == {'ai.pdf_topic': [], 'ai.pptx': []}
    assert login_client(account(77902)).get('/api/v1/studio/categories').status_code == 200
    from django.test import Client
    assert Client().get('/api/v1/studio/categories').status_code == 401


def test_every_list_is_the_bots_in_its_order_without_emoji_and_with_its_lines(customer, switch):
    _, client = customer
    switch()
    found = lists(client, locale='uz')
    for feature, top in TOP.items():
        nodes = found[feature]
        assert [(node['id'], node['kind']) for node in nodes] == top
        assert [node['label'] for node in nodes] == [plain(node.label('uz')) for node in catalogue.menu(feature)]
        for node in nodes:
            assert not EMOJI.match(node['label']) and node['label'] == node['label'].strip()
            if node['kind'] == 'other':
                assert node == {'id': 'other', 'kind': 'other', 'label': 'Boshqa'}
                continue
            assert node['hint'] == catalogue._catalogue().index['hints'][node['id']]['uz']
    mustaqil = found['ai.pdf_topic'][0]
    entry = categories.get('pdf.mustaqil_ish')
    assert mustaqil['label'] == 'Mustaqil ish / Referat'
    assert mustaqil['hint'] == 'Titul, reja, matn va adabiyotlar · 8–20 sahifa'
    # The bot's prompt line by line, each without the emoji it opens with: the web draws its own.
    assert mustaqil['prompt'] == [line.lstrip('🎓📎 ').strip() for line in entry.raw['bot']['prompt']['uz'].split('\n')]
    assert mustaqil['prompt'][0].startswith('Bitta xabarda yozing: mavzu, fan')
    assert mustaqil['examples'] == [example['uz'] for example in entry.raw['bot']['examples']]
    assert mustaqil['attach'] is True
    business = found['ai.pdf_topic'][5]
    assert business['label'] == 'Biznes va ish' and business['hint'].startswith('Biznes-reja, tijorat taklifi')
    assert [child['id'] for child in business['children']] == [*catalogue._catalogue().index['groups']['pdf.biz']['children']]
    assert business['children'][-1] == {'id': 'other', 'kind': 'other', 'label': 'Boshqa hujjat'}
    # Inside a group a button has no line: the web's group screen shows the names alone.
    assert {child.get('hint') for child in business['children'] if child['kind'] == 'category'} == {None}
    assert all(child['prompt'] and child['examples'] for child in business['children'] if child['kind'] == 'category')


def test_every_word_is_in_the_locale_asked_or_the_accounts(customer, switch):
    who, client = customer
    switch()
    russian = lists(client, locale='ru')['ai.pptx']
    assert russian[0]['label'] == 'Презентация по теме' and russian[-1]['label'] == 'Другое'
    assert russian[3]['label'] == 'Классный час / мероприятие' and russian[3]['children'][-1]['label'] == 'Другое мероприятие'
    assert russian[0]['examples'] == [example['ru'] for example in categories.get('slides.mavzu').raw['bot']['examples']]
    assert lists(client, locale='xx')['ai.pptx'][0]['label'] == 'Topic presentation'
    who.locale = 'uz'
    who.save(update_fields=['locale'])
    assert lists(client)['ai.pptx'][0]['label'] == 'Mavzu bo‘yicha slayd'


def test_only_what_is_ticked_is_offered_and_a_group_shows_its_live_children(customer, switch):
    _, client = customer
    switch(live=['pdf.biz.hisobot', 'pdf.test'])
    found = lists(client, locale='en')
    assert [(node['id'], node['kind']) for node in found['ai.pdf_topic']] == [
        ('pdf.test', 'category'), ('pdf.biz', 'group'), ('other', 'other')]
    assert [child['id'] for child in found['ai.pdf_topic'][1]['children']] == ['pdf.biz.hisobot', 'other']
    assert found['ai.pptx'] == []


def test_a_top_button_without_its_line_or_a_line_for_no_top_button_does_not_load():
    entries, templates, index = copy.deepcopy(read())
    del index['hints']['pdf.kurs_ishi']
    index['hints']['pdf.biz.hisobot'] = {'uz': 'Hisobot', 'ru': 'Отчёт', 'en': 'Report'}
    index['hints']['slides.pitch'] = {'uz': 'Pitch'}
    with pytest.raises(CatalogueError) as raised:
        build(entries, templates, index)
    assert set(raised.value.problems) == {
        'index: hints: pdf.kurs_ishi needs its line in uz, ru and en',
        'index: hints: slides.pitch needs its line in uz, ru and en',
        'index: hints: pdf.biz.hisobot is inside a group, where buttons have no line'}
    del index['hints']
    with pytest.raises(CatalogueError) as raised:
        build(entries, templates, index)
    assert raised.value.problems == ['index: hints: the line under each button of the top lists is missing']


def test_a_line_in_uzbek_is_latin_and_written_with_the_house_apostrophes():
    entries, templates, index = copy.deepcopy(read())
    index['hints']['pdf.konspekt']['uz'] = "Mavzu, reja va o'quvchi uchun xulosa"
    made = build(entries, templates, index)
    found = [str(problem) for problem in catalogue.check(catalogue=made) if not problem.warning]
    assert any(text.startswith('index: hints/pdf.konspekt: an ASCII apostrophe in uz') for text in found)
    index['hints']['pdf.konspekt']['uz'] = 'Тема и выводы'
    found = [str(problem) for problem in catalogue.check(catalogue=build(entries, templates, index))]
    assert any(text.startswith('index: hints/pdf.konspekt: Cyrillic in uz') for text in found)


def test_plain_takes_every_opening_emoji_of_the_catalogue_and_nothing_else():
    for entry in catalogue._catalogue().entries.values():
        for locale in catalogue.LOCALES:
            assert plain(entry.label(locale)) == entry.name(locale)
            for line in entry.raw['bot']['prompt'][locale].split('\n'):
                kept = plain(line)
                assert kept and not EMOJI.match(kept)
                # Words are never touched: what is left is the line's own end.
                assert line.endswith(kept)
    for group in catalogue._catalogue().index['groups'].values():
        assert plain(group['label']['uz']) == group['label']['uz'].split(' ', 1)[1]
    assert plain('• F.I.Sh., tug‘ilgan yili') == '• F.I.Sh., tug‘ilgan yili'
    assert plain('🧑‍🏫 Dars slaydlari.') == 'Dars slaydlari.' and plain('✍️ Bitta xabarda') == 'Bitta xabarda'
    assert plain('2024-yil hisoboti') == '2024-yil hisoboti'


def test_opening_a_category_on_the_web_is_counted_once_in_half_an_hour(customer, switch):
    who, client = customer
    switch()
    from django.core.cache import cache
    cache.clear()
    for _ in range(2):
        response = client.post('/api/v1/studio/categories/chosen', {'category': 'pdf.kurs_ishi'},
                               content_type='application/json')
        assert response.status_code == 200 and response.json() == {'recorded': True}
    events = AnalyticsEvent.objects.filter(account=who, event_type=CHOSEN_EVENT)
    assert [(event.channel, event.feature_id, event.properties) for event in events] == [
        ('web', 'ai.pdf_topic', {'category': 'pdf.kurs_ishi'})]
    for value in ('pdf.nothing', 'other', None, ['pdf.kurs_ishi']):
        response = client.post('/api/v1/studio/categories/chosen', {'category': value},
                               content_type='application/json')
        assert response.status_code == 400 and response.json()['error']['code'] == 'invalid_parameters'
    assert events.count() == 1


def test_the_bot_still_counts_its_taps_through_the_same_window(customer, switch):
    who, _ = customer
    from django.core.cache import cache
    from telegram import generation
    cache.clear()
    generation.chosen(who, 'slides.pitch')
    generation.chosen(who, 'slides.pitch')
    generation.chosen(who, 'pdf.nothing')
    assert list(AnalyticsEvent.objects.filter(account=who, event_type=CHOSEN_EVENT)
                .values_list('channel', 'properties')) == [('bot', {'category': 'slides.pitch'})]


def test_a_category_picked_on_the_web_is_made_from_its_description_and_a_text_file_sent_as_its_source(customer, switch):
    """The web's main path: the list, a category, a .txt uploaded as ai_source, the draft with the category."""
    who, client = customer
    switch()
    nodes = lists(client, locale='uz')['ai.pdf_topic']
    minutes = next(child for child in nodes[5]['children'] if child['id'] == 'pdf.biz.bayonnoma')
    assert minutes['attach'] is True
    uploaded = client.post('/api/v1/files/uploads', {'file': SimpleUploadedFile('qaydlar.txt', NOTES.encode()),
                                                      'purpose': 'ai_source'})
    assert uploaded.status_code == 201, uploaded.content
    asset = FileAsset.objects.get(pk=uploaded.json()['id'])
    assert asset.metadata['kind'] == 'text'
    response = client.post('/api/v1/generation/drafts', json.dumps({
        'feature_id': 'ai.pdf_topic', 'prompt': 'Yig‘ilish bayonnomasi, ilovadagi qaydlar asosida.',
        'source_ids': [str(asset.id)], 'output_locale': 'uz', 'options': {'category': minutes['id']}}),
        content_type='application/json')
    assert response.status_code == 201, response.content
    draft = response.json()
    assert draft['options']['category'] == 'pdf.biz.bayonnoma'
    stored = unpack(GenerationDraft.objects.get(pk=draft['id']).encrypted_data)
    assert [excerpt['text'] for excerpt in stored['excerpts']] == [NOTES]
    # A category the owner has since taken off the list is said, not made as Boshqa.
    switch(live=['pdf.test'])
    refused = client.post('/api/v1/generation/drafts', json.dumps({
        'feature_id': 'ai.pdf_topic', 'prompt': 'Yig‘ilish bayonnomasi.', 'options': {'category': 'pdf.biz.bayonnoma'}}),
        content_type='application/json')
    assert refused.status_code == 409 and refused.json()['error']['code'] == 'category_unavailable'


def test_a_category_source_from_the_web_is_still_refused_by_every_tool(customer):
    who, client = customer
    uploaded = client.post('/api/v1/files/uploads', {'file': SimpleUploadedFile('qaydlar.txt', NOTES.encode()),
                                                      'purpose': 'ai_source'})
    assert uploaded.status_code == 201
    quote = client.post('/api/v1/quotes', json.dumps({'feature_id': 'convert.word_to_pdf',
                                                      'input_ids': [uploaded.json()['id']], 'parameters': {}}),
                        content_type='application/json')
    assert quote.status_code in (400, 409) and 'error' in quote.json()
    picture = client.post('/api/v1/files/uploads', {'file': SimpleUploadedFile('rasm.png', b'\x89PNG\r\n\x1a\n'),
                                                     'purpose': 'ai_source'})
    assert picture.status_code == 400 and picture.json()['error']['code'] == 'unsupported_file'
