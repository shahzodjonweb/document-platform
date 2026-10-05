"""Decks wear one of ten designs, chosen by the model; what the customer named still wins."""
import copy
import json

import pytest
from pptx import Presentation
from pptx.oxml.ns import qn

from apps.core.services import execute_job, submit_job
from apps.studio import deck_designs, provider
from apps.studio.deck_designs import DESIGN_IDS, DESIGNS, look, remember, wanted
from apps.studio.domain import create_draft, generation_quote, unpack
from apps.studio.slides import _luminance, contrast_ratio, palette, render_pptx
from operations.integrations import save_config
from tests.test_platform import account
from tests.test_provider_contract import CONFIG, draft
from tests.test_provider_optimization import transport
from tests.test_studio import paid


def deck():
    return {'title': 'Tides', 'questions': [], 'citations': [], 'sections': [
        {'id': 's1', 'heading': 'Tides', 'body': 'Why the sea moves', 'notes': '', 'layout': 'cover',
         'items': [], 'columns': [], 'image_query': ''},
        {'id': 's2', 'heading': 'The moon pulls the water', 'body': 'Gravity\nTwo bulges\nTwice a day',
         'notes': '', 'layout': 'bullets', 'items': [], 'columns': [], 'image_query': ''},
        {'id': 's3', 'heading': 'Spring and neap', 'body': 'Sun and moon together', 'notes': '',
         'layout': 'section', 'items': [], 'columns': [], 'image_query': ''},
    ]}


def faces(presentation):
    found = set()
    for slide in presentation.slides:
        found |= {latin.get('typeface') for latin in slide._element.iter(qn('a:latin'))}
    return found


def theme_fonts(presentation):
    from apps.studio.slides import _theme_part
    from lxml import etree
    theme = etree.fromstring(_theme_part(presentation).blob)
    return [theme.find('.//' + qn(tag)).find(qn('a:latin')).get('typeface')
            for tag in ('a:majorFont', 'a:minorFont')]


@pytest.mark.parametrize('design', DESIGN_IDS)
def test_every_design_renders_its_own_colour_and_fonts(design, tmp_path):
    path = tmp_path / 'deck.pptx'
    result = render_pptx(deck(), path, style={'accent': '#255e49', 'deck_design': design})
    chosen = DESIGNS[design]
    presentation = Presentation(str(path))
    assert result['metadata']['design'] == design
    # The accent element is still shapes[0] and still the exact accent.
    for slide in presentation.slides:
        assert str(slide.shapes[0].fill.fore_color.rgb) == chosen['accent'].lstrip('#').upper()
    assert faces(presentation) <= {chosen['heading_font'], chosen['body_font']}
    assert chosen['body_font'] in faces(presentation)
    assert theme_fonts(presentation) == [chosen['heading_font'], chosen['body_font']]
    ground = str(presentation.slides[1].background.fill.fore_color.rgb)
    assert (_luminance(ground) < 0.1) == (chosen['theme'] == 'dark')


@pytest.mark.parametrize('design', DESIGN_IDS)
def test_every_design_keeps_text_readable(design):
    shown = look({'deck_design': design})
    roles = palette(shown['accent'], shown['theme'], shown['secondary'], shown['paper'], shown['accent_headings'])
    pairs = [('ink', 'surface', 7.0), ('muted', 'surface', 4.5), ('accent_text', 'surface', 4.5),
             ('heading', 'surface', 4.5), ('cover_ink', 'cover_fill', 4.5), ('band_ink', 'band', 4.5),
             ('card_ink', 'card', 7.0), ('soft_ink', 'accent_soft', 7.0)]
    for text, ground, target in pairs:
        assert contrast_ratio(roles[text], roles[ground]) >= target - 0.05, (design, text, ground)


def test_the_ten_designs_are_ten_different_looks():
    signatures = {(d['accent'], d['theme'], d['paper'], d['heading_font'], d['body_font'])
                  for d in DESIGNS.values()}
    assert len(DESIGNS) == 10 and len(signatures) == 10
    assert len({d['accent'] for d in DESIGNS.values()}) == 10
    assert {d['theme'] for d in DESIGNS.values()} == {'light', 'dark', 'bold'}


def test_what_the_customer_named_wins_over_the_design(tmp_path):
    # A brand colour, or one named in the brief, replaces the design's accent.
    shown = look({'deck_design': 'spotlight', 'accent': '#1F4E9C', 'accent_fixed': True})
    assert shown['accent'] == '#1F4E9C' and shown['secondary'] is None and shown['heading_font'] == 'Arial'
    # The template's default green is not a choice anyone made.
    assert look({'deck_design': 'spotlight', 'accent': '#255e49'})['accent'] == '#D94A26'
    # "A dark deck" keeps the design's fonts but not its light paper.
    dark = look({'deck_design': 'scholar', 'deck_theme': 'dark'})
    assert dark['theme'] == 'dark' and dark['paper'] is None and dark['heading_font'] == 'Constantia'
    path = tmp_path / 'deck.pptx'
    render_pptx(deck(), path, style={'deck_design': 'lagoon', 'accent': '#9B1B1B', 'accent_fixed': True})
    assert str(Presentation(str(path)).slides[0].shapes[0].fill.fore_color.rgb) == '9B1B1B'


def test_a_deck_without_a_design_looks_exactly_as_before(tmp_path):
    path = tmp_path / 'deck.pptx'
    result = render_pptx(deck(), path, style={'accent': '#255e49'})
    presentation = Presentation(str(path))
    assert result['metadata']['design'] == ''
    assert str(presentation.slides[0].shapes[0].fill.fore_color.rgb) == '255E49'
    assert faces(presentation) <= {'Cambria', 'Corbel'}


def test_the_model_is_asked_once_per_deck():
    data = draft(20, 'pptx')
    first = provider.request_body(CONFIG, data, 'ai.pptx', (0, 8))
    later = provider.request_body(CONFIG, data, 'ai.pptx', (8, 16))
    assert first['text']['format']['schema']['properties']['design']['enum'] == DESIGN_IDS
    assert 'design' not in later['text']['format']['schema']['properties']
    # The list is in every call's instructions, so long decks keep one cached prefix.
    assert 'boardroom:' in first['instructions'] and first['instructions'] == later['instructions']
    chosen = copy.deepcopy(data)
    chosen['options']['template_style'] = {'deck_design': 'gala'}
    assert 'design' not in provider.request_body(CONFIG, chosen, 'ai.pptx')['text']['format']['schema']['properties']
    revising = copy.deepcopy(data)
    revising['revision'] = {'request': 'Fix a typo.', 'original_prompt': 'Tides.'}
    assert not wanted(revising)
    assert 'design' not in provider.request_body(CONFIG, draft(3, 'pdf'), 'ai.pdf_topic')['text']['format']['schema']['properties']


def test_the_choice_is_kept_and_only_replaced_when_asked():
    data = {'options': {'template_style': {'accent': '#255e49'}}}
    remember(data, {'design': 'not-a-design'})
    assert 'deck_design' not in data['options']['template_style']
    remember(data, {'design': 'royal'})
    remember(data, {'design': 'gala'})
    assert data['options']['template_style']['deck_design'] == 'royal'
    remember(data, {'design': 'gala'}, replace=True)
    assert data['options']['template_style']['deck_design'] == 'gala'


@pytest.mark.django_db
def test_a_brief_fixes_only_what_it_names(settings):
    settings.DEBUG = True
    customer = paid(settings, account())
    plain = unpack(create_draft(customer, {'feature_id': 'ai.pptx', 'prompt': 'Five slides on tides'}).encrypted_data)
    assert 'deck_theme' not in plain['options']['template_style']
    assert not plain['options']['template_style'].get('accent_fixed')
    named = unpack(create_draft(customer, {'feature_id': 'ai.pptx',
                                           'prompt': 'A dark deck in navy about tides'}).encrypted_data)
    style = named['options']['template_style']
    assert style['deck_theme'] == 'dark' and style['accent'] == '#16305C' and style['accent_fixed']


@pytest.mark.django_db
def test_a_generated_deck_wears_the_design_the_model_chose(settings, monkeypatch, tmp_path):
    settings.DEBUG = True
    customer = paid(settings, account())
    save_config('ai', {'mode': 'openai', 'model': CONFIG['model'], 'api_key': 'offline-only'})
    authored = create_draft(customer, {'feature_id': 'ai.pptx', 'prompt': 'Three slides about tides',
                                       'options': {'length': 3}})

    def answer(body, number):
        sent = json.loads(body['input'])
        reply = {'title': 'Tides', 'answer_supported': True,
                 'sections': [{'id': s['id'], 'heading': f'Tides {n}', 'body': 'Moon\nSun\nWater',
                               'notes': 'Say it.', 'layout': 'cover' if n == 0 else 'bullets', 'items': [],
                               'columns': [], 'image_query': ''}
                              for n, s in enumerate(sent['outline']['sections'])]}
        if 'design' in body['text']['format']['schema']['properties']:
            reply['design'] = 'lagoon'
        for field in ('citations', 'questions'):
            if field in body['text']['format']['schema']['properties']:
                reply[field] = []
        return reply

    transport(monkeypatch, answer)
    quote = generation_quote(customer, authored.id, authored.version)
    job, _ = submit_job(customer, quote.id, 'design-offline')
    job = execute_job(job.id)
    assert job.status == 'succeeded', job.error_code
    authored.refresh_from_db()
    assert unpack(authored.encrypted_data)['options']['template_style']['deck_design'] == 'lagoon'
    from apps.core import storage
    path = storage.local(job.artifacts.get().file.object_key)
    presentation = Presentation(str(path))
    assert str(presentation.slides[0].shapes[0].fill.fore_color.rgb) == '0F766E'
    assert 'Candara' in faces(presentation)
