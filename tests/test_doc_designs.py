"""Documents are plain, flowing text unless the description asks for more."""
import copy
import io
import json

import pytest
from PIL import Image
from pypdf import PdfReader

from apps.core.services import execute_job, submit_job
from apps.studio import doc_designs, provider
from apps.studio.doc_designs import DESIGN_IDS, LAYOUT_IDS, asks_for_design, asks_for_images, asks_for_layouts, look
from apps.studio.domain import create_draft, generation_quote, unpack, validate_content
from apps.studio.rendering import render_pdf
from operations.integrations import save_config
from tests.test_platform import account
from tests.test_provider_contract import CONFIG, draft
from tests.test_provider_optimization import transport
from tests.test_studio import paid

PARAGRAPH = ('Hamshiralik parvarishi davomida bemorning holati belgilangan tartibda kuzatiladi. '
             'Nafas olish qiyinlashuvi yoki qon ketishi aniqlansa, shifokorga darhol xabar beriladi. ') * 3


def document(sections):
    return {'title': 'Parvarish', 'questions': [], 'citations': [], 'sections': [
        {'id': f's{n + 1}', 'notes': '', **section} for n, section in enumerate(sections)]}


def text_of(path):
    return '\n'.join(page.extract_text() for page in PdfReader(str(path)).pages)


@pytest.mark.parametrize('brief,layouts,images,design', [
    ('A five page report about tides', False, False, False),
    ("Bemorlarni parvarish qilish haqida 3 betlik hujjat", False, False, False),
    ('Документ о приливах на 4 страницы', False, False, False),
    ('A guide to tides with pictures and a table of times', True, True, False),
    ("Jadval va rasmlar bilan suv toshqini haqida hujjat", True, True, False),
    ('Отчёт о продажах с таблицей и списком шагов', True, False, False),
    ('A colourful, modern looking handout about recycling', False, False, True),
    ("Chiroyli dizaynli taklifnoma", False, False, True),
    ('Красивый документ в синем цвете', False, False, True),
])
def test_the_description_decides_what_a_document_may_use(brief, layouts, images, design):
    assert asks_for_layouts(brief) is layouts
    assert asks_for_images(brief) is images
    assert asks_for_design(brief) is design


def test_a_document_is_black_and_white_unless_it_chose_otherwise():
    assert look({})['accent'] == '#111111' and look({})['id'] == 'plain'
    # The green every template once carried is nobody's choice.
    assert look({'accent': '#255e49'})['accent'] == '#111111'
    assert look({'doc_design': 'fresh'}) == {'id': 'fresh', 'accent': '#0F766E', 'style': 'band'}
    # A colour the customer named, or their brand, beats the design's.
    assert look({'doc_design': 'modern', 'accent': '#9B1B1B', 'accent_fixed': True})['accent'] == '#9B1B1B'
    # A template that has a colour of its own keeps it.
    assert look({'accent': '#273e65'})['accent'] == '#273e65'
    assert len(DESIGN_IDS) == 5 and len(LAYOUT_IDS) == 5 and DESIGN_IDS[0] == 'plain'


def test_headings_appear_only_where_a_topic_starts_and_text_flows(tmp_path):
    sections = [{'heading': 'Kuzatuv', 'body': f'{PARAGRAPH}\n\n{PARAGRAPH}'},
                {'heading': '', 'body': PARAGRAPH},
                {'heading': 'Ovqatlanish', 'body': PARAGRAPH}]
    path = tmp_path / 'flow.pdf'
    result = render_pdf(document(sections), path, 'uz')
    text = text_of(path)
    assert result['page_count'] == 1, 'three short sections share one page'
    assert text.count('Kuzatuv') == 1 and text.count('Ovqatlanish') == 1
    assert result['metadata']['design'] == 'plain'


def test_a_document_keeps_to_its_page_count_by_setting_tighter(tmp_path):
    body = '\n\n'.join([PARAGRAPH] * 6)
    result = render_pdf(document([{'heading': 'Bo‘lim' if n % 3 == 0 else '', 'body': body}
                                  for n in range(6)]), tmp_path / 'full.pdf', 'uz')
    assert result['page_count'] <= 6


@pytest.mark.parametrize('design', DESIGN_IDS)
def test_every_layout_renders_in_every_design(design, tmp_path):
    jpeg = io.BytesIO()
    Image.new('RGB', (800, 500), (40, 120, 160)).save(jpeg, 'JPEG')
    sections = [
        {'heading': 'Asosiy', 'body': PARAGRAPH},
        {'heading': 'Jadval', 'body': PARAGRAPH, 'layout': 'table', 'columns': ['Belgi', 'Chora', 'Vaqt'],
         'items': [{'label': 'Nafas', 'text': 'Shifokorga xabar', 'value': 'Darhol'},
                   {'label': 'Harorat', 'text': 'O‘lchanadi', 'value': '4 soat'}]},
        {'heading': 'Qoidalar', 'body': PARAGRAPH, 'layout': 'callout',
         'items': [{'label': 'Gigiyena', 'text': 'Og‘iz har ovqatdan keyin tozalanadi.', 'value': ''}]},
        {'heading': 'Bosqichlar', 'body': PARAGRAPH, 'layout': 'list',
         'items': [{'label': 'Qabul', 'text': 'Allergiya aniqlanadi.', 'value': ''}]},
        {'heading': 'Rasm', 'body': PARAGRAPH, 'layout': 'image', 'image_query': 'hospital ward'},
    ]
    path = tmp_path / f'{design}.pdf'
    result = render_pdf(document(sections), path, 'uz', style={'doc_design': design},
                        photos={'s5': {'jpeg': jpeg.getvalue()}})
    text = text_of(path)
    for word in ('Darhol', 'Gigiyena', 'Qabul', 'Belgi'):
        assert word in text, (design, word)
    assert result['metadata'] == {'design': design, 'layouts': ['text', 'table', 'callout', 'list', 'image']}
    assert sum(len(page.images) for page in PdfReader(str(path)).pages) == 1
    if design == 'academic':
        assert '1. Asosiy' in text and '2. Jadval' in text


def test_a_plain_document_is_asked_for_plain_prose():
    data = draft(5)
    body = provider.request_body(CONFIG, data, 'ai.pdf_topic')
    schema = body['text']['format']['schema']
    assert 'design' not in schema['properties']
    assert set(schema['properties']['sections']['items']['properties']) == {'id', 'heading', 'body'}
    assert 'Choose a layout' not in body['instructions'] and '`design`' not in body['instructions']
    guidance = json.loads(body['input'])['writing_guidance']
    assert 'leave the heading empty when the section continues' in guidance


def test_a_document_that_asks_is_offered_layouts_and_a_design_once():
    data = draft(20)
    data['options'].update(wants_layouts=True, wants_design=True, image_cap=2)
    first = provider.request_body(CONFIG, data, 'ai.pdf_topic', (0, 8))
    later = provider.request_body(CONFIG, data, 'ai.pdf_topic', (8, 16))
    fields = first['text']['format']['schema']['properties']['sections']['items']['properties']
    assert fields['layout']['enum'] == LAYOUT_IDS and 'image_query' in fields
    assert first['text']['format']['schema']['properties']['design']['enum'] == DESIGN_IDS
    assert 'design' not in later['text']['format']['schema']['properties']
    assert first['instructions'] == later['instructions'], 'one cached prefix across batches'
    assert 'at most 2 sections' in first['instructions']
    data['options']['template_style'] = {'doc_design': 'academic'}
    assert 'design' not in provider.request_body(CONFIG, data, 'ai.pdf_topic')['text']['format']['schema']['properties']


@pytest.mark.django_db
def test_a_plain_document_section_keeps_its_four_keys(settings):
    settings.DEBUG = True
    customer = paid(settings, account())
    plain = validate_content(customer, document([{'heading': 'H', 'body': 'B', 'layout': 'text', 'items': [],
                                                  'columns': [], 'image_query': ''}]), 'pdf')
    assert set(plain['sections'][0]) == {'id', 'heading', 'body', 'notes'}
    table = validate_content(customer, document([{'heading': 'H', 'body': 'B', 'layout': 'table',
                                                  'columns': ['A', 'B'], 'items': [{'label': 'x', 'text': 'y'}]}]), 'pdf')
    assert table['sections'][0]['layout'] == 'table' and table['sections'][0]['columns'] == ['A', 'B']


@pytest.mark.django_db
def test_the_brief_sets_what_the_model_is_offered(settings):
    settings.DEBUG = True
    customer = paid(settings, account())
    plain = unpack(create_draft(customer, {'prompt': 'A three page guide to tides'}).encrypted_data)['options']
    assert not plain['wants_layouts'] and not plain['wants_design'] and plain['image_cap'] == 0
    rich = unpack(create_draft(customer, {'prompt': 'A colourful guide to tides with a table'}).encrypted_data)['options']
    assert rich['wants_layouts'] and rich['wants_design'] and rich['image_cap'] == 0
    forged = unpack(create_draft(customer, {'prompt': 'A guide to tides',
                                            'options': {'wants_layouts': True, 'wants_design': True}}).encrypted_data)['options']
    assert not forged['wants_layouts'] and not forged['wants_design'], 'the client cannot switch these on'


@pytest.mark.django_db
def test_a_generated_document_uses_the_table_and_design_the_model_chose(settings, monkeypatch):
    settings.DEBUG = True
    customer = paid(settings, account())
    save_config('ai', {'mode': 'openai', 'model': CONFIG['model'], 'api_key': 'offline-only'})
    authored = create_draft(customer, {'prompt': 'A colourful two page guide to tides with a table of times',
                                       'options': {'length': 2}})

    def answer(body, number):
        properties = body['text']['format']['schema']['properties']
        sent = json.loads(body['input'])
        reply = {'title': 'Tides', 'answer_supported': True, 'sections': [
            {'id': s['id'], 'heading': 'High and low water' if n == 0 else '', 'body': PARAGRAPH,
             'layout': 'table' if n == 1 else 'text', 'columns': ['Port', 'High water'] if n == 1 else [],
             'items': [{'label': 'Tashkent', 'text': '06:10', 'value': ''}] if n == 1 else [], 'image_query': ''}
            for n, s in enumerate(sent['outline']['sections'])]}
        if 'design' in properties:
            reply['design'] = 'fresh'
        for field in ('citations', 'questions'):
            if field in properties:
                reply[field] = []
        return reply

    transport(monkeypatch, answer)
    quote = generation_quote(customer, authored.id, authored.version)
    job, _ = submit_job(customer, quote.id, 'doc-design-offline')
    job = execute_job(job.id)
    assert job.status == 'succeeded', job.error_code
    authored.refresh_from_db()
    data = unpack(authored.encrypted_data)
    assert data['options']['template_style']['doc_design'] == 'fresh'
    assert data['content']['sections'][1]['layout'] == 'table'
    assert 'layout' not in data['content']['sections'][0], 'a plain section stays four keys'
    from apps.core import storage
    text = text_of(storage.local(job.artifacts.get().file.object_key))
    assert 'Tashkent' in text and text.count('High and low water') == 1
