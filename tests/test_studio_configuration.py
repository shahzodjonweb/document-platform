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
    # A document is a PDF and a deck is a PowerPoint. Neither is a choice.
    assert next(f for f in data['features'] if f['id'] == DOCUMENT)['parameter_schema']['output_format']['enum'] == ['pdf']
    assert next(f for f in data['features'] if f['id'] == SLIDES)['parameter_schema']['output_format']['enum'] == ['pptx']


def test_the_page_ceiling_is_published_so_the_form_can_say_it(settings):
    settings.DEBUG = True
    from apps.studio.pages import ceiling
    a = account()
    data = login_client(a).get('/api/v1/studio/config').json()
    for feature in data['features']:
        expected = ceiling(a, 'pptx' if feature['id'] == SLIDES else 'pdf')
        assert feature['max_pages'] == expected
    from apps.core.policy import plan_limits
    assert data['features'][0]['max_pages'] == plan_limits(a)['max_generated_pdf_pages'], \
        'the form is told exactly what the free plan allows'



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


def test_a_document_is_not_given_a_structure_nobody_asked_for(settings):
    """The description is the whole brief, so the structure comes from it.

    Every draft used to be seeded with a fixed Overview / Key ideas / Practice /
    Review cycle and the model was told to use that outline — so every document
    came back with a practice section of tasks and a review section the customer
    never asked for, and on anything past four pages the four repeated.
    """
    from apps.studio.domain import create_draft, draft_data
    settings.DEBUG = True
    customer = account()
    draft = create_draft(customer, {'feature_id': DOCUMENT,
                                    'prompt': 'A 6 page guide to reading tide tables.'})
    sections = draft_data(draft)['content']['sections']
    assert len(sections) == 6
    assert [section['heading'] for section in sections] == [''] * 6, \
        'nothing is put in the outline that the description did not ask for'
    assert draft_data(draft)['content']['questions'] == []


def test_the_model_is_told_to_write_only_what_was_asked_for():
    """The outline is empty now, so the instruction is what holds the line."""
    from apps.studio.provider import SYSTEM
    instructions = SYSTEM.lower()
    for unasked in ('exercises', 'practice tasks', 'review', 'summaries', 'glossaries', 'appendices'):
        assert unasked in instructions, f'the model is not told to leave out {unasked}'
    assert 'unless the description asks for them' in instructions
    # And it still has to name the sections it writes.
    assert 'write a heading that fits the description wherever one is blank' in instructions


@pytest.mark.parametrize('asked', ['pdf', 'pptx', None])
def test_a_deck_is_a_powerpoint_whatever_the_client_asks_for(settings, asked):
    """Slides used to come back as a PDF unless the client said otherwise.

    The format belongs to the service, not to the request: the bot could never
    produce a deck at all, and the web form defaulted the dropdown to PDF — so
    the editable deck the plan advertises was the option nobody took.
    """
    from apps.studio.domain import create_draft, draft_data
    settings.DEBUG = True
    customer = account()
    data = {'feature_id': SLIDES, 'prompt': 'A 4 slide deck about tide tables.'}
    if asked:
        data['output_format'] = asked
    assert draft_data(create_draft(customer, data))['output_format'] == 'pptx'
    # And a document stays a PDF by the same rule.
    assert draft_data(create_draft(customer, {'feature_id': DOCUMENT, 'prompt': 'A 2 page guide.',
                                              **({'output_format': asked} if asked else {})}))['output_format'] == 'pdf'


def test_a_change_request_to_an_older_slides_draft_comes_back_as_a_deck(settings):
    """A revision inherits its original — which for an older draft means PDF."""
    from apps.studio.domain import create_draft, draft_data, pack, unpack
    settings.DEBUG = True
    customer = account()
    draft = create_draft(customer, {'feature_id': SLIDES, 'prompt': 'A 4 slide deck about tides.'})
    # Force the stored format back to what a pre-deploy draft would hold, and
    # give it bodies so it is a finished document a change can be asked against.
    stored = unpack(draft.encrypted_data)
    written = {**stored['content'],
               'sections': [{**section, 'body': f'Slide {i + 1} says something.'}
                            for i, section in enumerate(stored['content']['sections'])]}
    draft.encrypted_data = pack({**stored, 'output_format': 'pdf', 'content': written})
    draft.save(update_fields=['encrypted_data'])

    revised = create_draft(customer, {'prompt': 'Make slide two punchier.',
                                      'options': {'revise_draft_id': str(draft.id)}})
    assert draft_data(revised)['output_format'] == 'pptx'


def test_an_unknown_output_format_is_still_refused(settings):
    """Forcing the format must not turn a malformed request into a silent success."""
    from apps.core.errors import DomainError
    from apps.studio.domain import create_draft
    settings.DEBUG = True
    with pytest.raises(DomainError, match='invalid_parameters'):
        create_draft(account(), {'feature_id': SLIDES, 'prompt': 'A deck.', 'output_format': 'png'})
