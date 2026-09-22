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
