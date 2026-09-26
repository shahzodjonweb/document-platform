"""What the two services advertise, and what the page style is fixed at."""
import pytest

from apps.studio.domain import DOCUMENT, GENERATION_IDS, SLIDES
from operations.integrations import save_config
from tests.test_platform import account, login_client

pytestmark = pytest.mark.django_db


def test_the_catalogue_offered_is_two_services(settings):
    settings.DEBUG = True
    data = login_client(account()).get('/api/v1/studio/config').json()
    assert [f['id'] for f in data['features']] == [DOCUMENT, SLIDES]
    assert data['default_pages'] == 5
    # A document is a PDF; only slides offer the editable deck.
    assert next(f for f in data['features'] if f['id'] == DOCUMENT)['parameter_schema']['output_format']['enum'] == ['pdf']
    assert next(f for f in data['features'] if f['id'] == SLIDES)['parameter_schema']['output_format']['enum'] == ['pdf', 'pptx']


def test_the_page_ceiling_is_published_so_the_form_can_say_it(settings):
    settings.DEBUG = True
    from apps.studio.pages import ceiling
    a = account()
    data = login_client(a).get('/api/v1/studio/config').json()
    for feature in data['features']:
        expected = ceiling(a, 'pptx' if feature['id'] == SLIDES else 'pdf')
        assert feature['max_pages'] == expected
    assert data['features'][0]['max_pages'] == 2, 'a free account gets two pages'


def test_the_form_is_never_asked_for_what_the_description_carries(settings):
    """Length, density, tone and question count are read out of the brief."""
    settings.DEBUG = True
    data = login_client(account()).get('/api/v1/studio/config').json()
    for feature in data['features']:
        assert set(feature['parameter_schema']) == {'output_locale', 'output_format'}


def test_the_provider_key_is_never_published(settings):
    settings.DEBUG = True
    client = login_client(account())
    save_config('ai', {'mode': 'openai', 'model': 'gpt-4.1', 'api_key': 'sk-offline-test-only'})
    provider = client.get('/api/v1/studio/config').json()['provider']
    assert 'api_key' not in provider
    assert provider['configured'] is True and provider['mode'] == 'openai'


def test_unreleased_generation_is_never_advertised_as_eligible(settings):
    settings.DEBUG = True
    settings.ENABLE_BETA_TOOLS = False
    data = login_client(account()).get('/api/v1/studio/config').json()
    assert len(data['features']) == len(GENERATION_IDS)
    assert not any(f['eligible'] for f in data['features'])


def test_the_page_style_is_fixed_at_what_the_fill_targets_were_measured_against(settings):
    """A page that must be full has no spacing left to choose, so a density sent
    by an older client is ignored rather than quietly changing the geometry."""
    settings.DEBUG = True
    from apps.studio.domain import create_draft, unpack

    a = account(uid=910001)
    for sent in ({}, {'density': 'rich'}, {'density': 'airy'}):
        draft = create_draft(a, {'feature_id': DOCUMENT, 'title': 'Density',
                                 'source_text': 'Body text.', 'options': dict(sent)})
        style = unpack(draft.encrypted_data)['options']['template_style']
        assert style == {'accent': '#255e49'}, f'{sent} must not change the page metrics'
        assert 'margin' not in style and 'body_size' not in style, 'the renderer default stands'
