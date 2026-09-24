"""Administrator-only anti-bot configuration and credential handling."""
import json

import pytest
from cryptography.fernet import Fernet
from django.test import Client

from apps.core.errors import DomainError
from operations.integrations import antibot_config, save_config
from operations.models import AuditLog, IntegrationConfig
from tests.test_operations import staff_client

pytestmark = pytest.mark.django_db
SECRET = 'turnstile-secret-private-fixture'
CONFIG = {'web_enabled': 'true', 'bot_enabled': 'true',
          'site_key': 'turnstile-site-fixture', 'secret_key': SECRET,
          'allowed_hostnames': 'pdfmaster.orderdesk.live'}
TEST_SITE_KEYS = (
    '1x00000000000000000000AA', '2x00000000000000000000AB',
    '1x00000000000000000000BB', '2x00000000000000000000BB',
    '3x00000000000000000000FF',
)
TEST_SECRET_KEYS = (
    '1x0000000000000000000000000000000AA',
    '2x0000000000000000000000000000000AA',
    '3x0000000000000000000000000000000AA',
)


@pytest.fixture(autouse=True)
def configuration_settings(settings, monkeypatch):
    settings.DEBUG = True
    monkeypatch.setenv('INTEGRATION_ENCRYPTION_KEY', Fernet.generate_key().decode())


def post_config(client, values):
    return client.post('/ops/integrations', {'action': 'save', 'integration': 'antibot',
                                           'reason': 'Configure abuse protection', **values})


def test_defaults_do_not_claim_web_protection_without_keys(settings):
    config = antibot_config()
    assert not config['web_enabled'] and not config['ready'] and not config['configured']
    assert config['site_key'] == config['secret_key'] == ''
    assert config['allowed_hostnames'] == ['pdfmaster.orderdesk.live']
    assert not config['bot_enabled']
    settings.DEBUG = False
    assert antibot_config()['bot_enabled']


def test_secret_is_encrypted_and_never_returned_in_admin_or_audit():
    client, _ = staff_client()
    assert post_config(client, CONFIG).status_code == 302
    config = antibot_config()
    assert config['ready'] and config['configured'] and config['bot_enabled']
    assert config['secret_key'] == SECRET
    row = IntegrationConfig.objects.get(key='antibot')
    assert SECRET.encode() not in bytes(row.encrypted_secrets)
    assert SECRET not in json.dumps(row.configuration)
    for locale in ('en', 'uz', 'ru'):
        response = client.get('/ops/integrations?lang=' + locale)
        assert response.status_code == 200
        assert b'id="antibot-settings"' in response.content
        assert b'name="secret_key"' in response.content
        assert SECRET.encode() not in response.content
        assert 'secret_key' not in response.context['antibot']
        assert response.context['antibot']['site_key'] == CONFIG['site_key']
        assert response.context['i']['antibot']
    assert SECRET not in json.dumps(list(AuditLog.objects.values('before', 'after', 'reason')))
    assert AuditLog.objects.filter(action='integration.save', target='antibot').count() == 1


def test_blank_secret_retains_credentials_and_independent_toggles():
    save_config('antibot', CONFIG)
    save_config('antibot', {**CONFIG, 'secret_key': '', 'web_enabled': 'false', 'bot_enabled': 'false'})
    config = antibot_config()
    assert config['secret_key'] == SECRET and config['configured']
    assert not config['ready'] and not config['web_enabled'] and not config['bot_enabled']
    save_config('antibot', {**CONFIG, 'secret_key': '', 'web_enabled': 'false'})
    assert antibot_config()['bot_enabled'] and not antibot_config()['ready']


def test_bot_verification_can_be_enabled_without_external_credentials():
    save_config('antibot', {'bot_enabled': 'true', 'web_enabled': 'false'})
    assert antibot_config()['bot_enabled'] and not antibot_config()['configured']


@pytest.mark.parametrize('change', [{'site_key': ''}, {'secret_key': ''}, {'allowed_hostnames': ''}])
def test_web_cannot_be_enabled_without_complete_configuration(change):
    with pytest.raises(DomainError, match='antibot_not_configured'):
        save_config('antibot', {**CONFIG, **change})
    assert not IntegrationConfig.objects.exists()


@pytest.mark.parametrize('hostname', [
    'https://pdfmaster.orderdesk.live', '*.orderdesk.live', 'example.com/path',
    'example.com:443', 'user@example.com', '.example.com', 'example.com.',
    'two..example.com', '-bad.example.com', 'bad-.example.com',
    'domain_' + '.example.com', 'x' * 64 + '.example.com',
    'example.com\\anything', '<script>', ['example.com', 123],
    ['site%d.example.com' % number for number in range(21)],
])
def test_only_bounded_exact_hostnames_are_accepted(hostname):
    with pytest.raises(DomainError, match='invalid_antibot_hostnames'):
        save_config('antibot', {**CONFIG, 'allowed_hostnames': hostname})
    assert not IntegrationConfig.objects.exists()


def test_hostnames_are_normalized_and_deduplicated():
    save_config('antibot', {**CONFIG, 'allowed_hostnames': 'PDFMaster.orderdesk.live,\nwww.example.com pdfmaster.orderdesk.live'})
    assert antibot_config()['allowed_hostnames'] == ['pdfmaster.orderdesk.live', 'www.example.com']


@pytest.mark.parametrize(('change', 'error'), [
    ({'site_key': 'short'}, 'invalid_antibot_site_key'),
    ({'site_key': 'key-with\nlinebreak'}, 'invalid_antibot_site_key'),
    ({'site_key': 'x' * 257}, 'invalid_antibot_site_key'),
    ({'secret_key': 'secret with spaces'}, 'invalid_antibot_secret_key'),
    ({'secret_key': 'x' * 1025}, 'invalid_antibot_secret_key'),
    ({'web_enabled': 'maybe'}, 'invalid_parameters'),
    ({'bot_enabled': 'maybe'}, 'invalid_parameters'),
])
def test_keys_and_toggles_are_validated(change, error):
    with pytest.raises(DomainError, match=error): save_config('antibot', {**CONFIG, **change})
    assert not IntegrationConfig.objects.exists()


@pytest.mark.parametrize('key', TEST_SITE_KEYS)
def test_production_rejects_official_site_test_keys(settings, key):
    settings.DEBUG = False
    with pytest.raises(DomainError, match='antibot_test_keys_forbidden'):
        save_config('antibot', {**CONFIG, 'site_key': key})


@pytest.mark.parametrize('key', TEST_SECRET_KEYS)
def test_production_rejects_official_secret_test_keys(settings, key):
    settings.DEBUG = False
    with pytest.raises(DomainError, match='antibot_test_keys_forbidden'):
        save_config('antibot', {**CONFIG, 'secret_key': key})


def test_development_dummy_config_becomes_unready_in_production(settings):
    save_config('antibot', {**CONFIG, 'site_key': TEST_SITE_KEYS[0], 'secret_key': TEST_SECRET_KEYS[0],
                           'allowed_hostnames': 'localhost,127.0.0.1'})
    assert antibot_config()['ready']
    settings.DEBUG = False
    assert antibot_config()['web_enabled'] and not antibot_config()['configured'] and not antibot_config()['ready']


@pytest.mark.parametrize('role', ['Analyst', 'Support', 'Operations', 'Finance', 'Content manager'])
def test_only_administrators_can_manage_protection(role):
    client, _ = staff_client(role)
    assert client.get('/ops/integrations').status_code == 403
    assert post_config(client, CONFIG).status_code == 403
    assert not IntegrationConfig.objects.exists()


def test_configuration_requires_staff_csrf_and_audit_reason():
    assert post_config(Client(), CONFIG).status_code == 302
    client, _ = staff_client(csrf=True)
    assert post_config(client, CONFIG).status_code == 403
    unguarded = Client(); unguarded.cookies = client.cookies
    assert post_config(unguarded, {**CONFIG, 'reason': ''}).status_code == 200
    assert not IntegrationConfig.objects.exists()


def test_invalid_secret_is_not_echoed_and_old_configuration_survives():
    client, _ = staff_client(); save_config('antibot', CONFIG)
    invalid_secret = 'private secret with spaces'
    response = post_config(client, {**CONFIG, 'secret_key': invalid_secret})
    assert response.status_code == 200 and b'invalid_antibot_secret_key' in response.content
    assert invalid_secret.encode() not in response.content and SECRET.encode() not in response.content
    assert antibot_config()['secret_key'] == SECRET and antibot_config()['ready']
