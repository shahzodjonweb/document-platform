import json
import pytest
from apps.studio.domain import GENERATION_IDS
from operations.integrations import save_config
from tests.test_platform import account,login_client

pytestmark=pytest.mark.django_db


def test_provider_availability_flags_reflect_admin_configuration(settings):
    settings.DEBUG=True
    client=login_client(account())
    provider=client.get('/api/v1/studio/config').json()['provider']
    assert provider['image_configured'] is False and provider['handwriting_configured'] is False
    save_config('ai',{'mode':'openai','model':'gpt-4.1','image_model':'test-image-model','api_key':'sk-offline-test-only'})
    data=client.get('/api/v1/studio/config').json()
    assert data['provider']['image_configured'] is True and data['provider']['handwriting_configured'] is True
    assert next(f for f in data['features'] if f['id']=='ai.images')['eligible'] is False
    assert 'api_key' not in data['provider']


def test_unreleased_generation_is_never_advertised_as_eligible(settings):
    settings.DEBUG=True;settings.ENABLE_BETA_TOOLS=False
    data=login_client(account()).get('/api/v1/studio/config').json()
    assert len(data['features'])==len(GENERATION_IDS)
    assert not any(f['eligible'] for f in data['features'])


def test_density_applies_to_every_plan_and_only_changes_spacing(settings):
    """Density is a layout control, not a paid template: a free account gets it,
    and it overrides spacing without replacing the template's own identity."""
    settings.DEBUG=True
    from apps.core.errors import DomainError
    from apps.studio.domain import create_draft,unpack
    from apps.studio.templates import DENSITIES,density_style

    a=account(uid=910001)
    fields={'feature_id':'ai.pdf_text','title':'Density','source_text':'Body text.'}

    for value in ('rich','airy'):
        draft=create_draft(a,{**fields,'options':{'density':value}})
        style=unpack(draft.encrypted_data)['options']['template_style']
        assert style['accent']=='#255e49', 'the template still supplies its own accent'
        for key,expected in DENSITIES[value].items():
            assert style[key]==expected, f'{value}.{key}'

    balanced=create_draft(a,{**fields,'options':{'density':'balanced'}})
    assert 'margin' not in unpack(balanced.encrypted_data)['options']['template_style']

    with pytest.raises(DomainError,match='invalid_parameters'):
        create_draft(a,{**fields,'options':{'density':'enormous'}})

    assert density_style(None)=={}


def test_density_and_tone_become_explicit_instructions_for_the_model():
    """A bare enum means nothing to a model. Density and tone must reach the
    request as instructions, and a long document at the densest setting must
    not be told to write more than the response can hold."""
    from apps.studio.provider import BODY_WORD_BUDGET,DENSITY_WORDS,request_body,writing_guidance

    def draft(options,sections=2):
        return {'output_locale':'en','prompt':'p','source_text':'','excerpts':[],
                'options':options,
                'content':{'title':'T','sections':[{'id':f's{i}','heading':'H','body':'B','notes':''}
                                                   for i in range(sections)],'questions':[],'citations':[]}}

    rich=writing_guidance({'density':'rich'},2)
    airy=writing_guidance({'density':'airy'},2)
    assert '170-260 words' in rich and 'fill the page' in rich
    assert '30-70 words' in airy and 'leaving space' in airy

    # Tone is appended; unknown free-text values from older drafts are ignored.
    assert 'plain language' in writing_guidance({'density':'balanced','style':'simple'},2).lower()
    assert writing_guidance({'density':'balanced','style':'whatever the user typed'},2).count('.')==2

    # The guard: many sections must shrink the per-section target.
    many=writing_guidance({'density':'rich'},40)
    cap=BODY_WORD_BUDGET//40
    assert cap<DENSITY_WORDS['rich'][0], 'this case must be tighter than the band'
    assert f'about {cap} words' in many, many
    assert 40*cap<=BODY_WORD_BUDGET, 'the whole document must fit the response budget'

    body=request_body({'model':'m'},draft({'density':'rich','style':'formal'}),'ai.pdf_text')
    assert 'writing_guidance' in json.loads(body['input'])
    assert 'follow its body length and tone' in body['instructions']

    # No density chosen still yields the balanced default, never nothing.
    assert '80-140 words' in writing_guidance({},2)
