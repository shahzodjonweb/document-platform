"""Admin-owned identity-provider and email configuration security boundaries."""
import json
from unittest.mock import Mock

import pytest
from cryptography.fernet import Fernet
from django.core import mail
from django.test import Client

from apps.core.errors import DomainError
from operations.integrations import (email_config, google_config, save_config,
                                     send_auth_email, test_email as check_email)
from operations.models import AuditLog, IntegrationConfig
from tests.test_operations import staff_client

pytestmark = pytest.mark.django_db
GOOGLE_SECRET = 'oauth-secret-fixture-private'
SMTP_SECRET = 'smtp-secret-fixture-private'
GOOGLE = {'enabled': 'true', 'client_id': '123456-fixture.apps.googleusercontent.com',
          'client_secret': GOOGLE_SECRET, 'redirect_uri': 'https://app.example.com/api/v1/auth/google/callback'}
EMAIL = {'enabled': 'true', 'host': 'smtp.example.com', 'port': '587', 'username': 'sender@example.com',
         'password': SMTP_SECRET, 'from_email': 'sender@example.com', 'use_tls': 'true', 'use_ssl': 'false'}


@pytest.fixture(autouse=True)
def configuration_settings(settings, monkeypatch):
    settings.DEBUG = True
    settings.TELEGRAM_WEBAPP_URL = 'https://app.example.com/en/app'
    settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
    monkeypatch.setenv('INTEGRATION_ENCRYPTION_KEY', Fernet.generate_key().decode())


def post_config(client, kind, values):
    return client.post('/ops/integrations', {'action': 'save', 'integration': kind,
                                           'reason': 'Configure customer authentication provider', **values})


def test_auth_integrations_default_disabled_with_public_callback():
    google = google_config(); email = email_config()
    assert not google['enabled'] and not google['ready'] and not google['configured']
    assert google['redirect_uri'] == GOOGLE['redirect_uri']
    assert not email['enabled'] and not email['ready'] and email['use_tls']


def test_admin_saves_encrypted_secrets_without_echo_or_audit_leak():
    client, _ = staff_client()
    assert post_config(client, 'google', GOOGLE).status_code == 302
    assert post_config(client, 'email', EMAIL).status_code == 302
    assert google_config()['client_secret'] == GOOGLE_SECRET and google_config()['ready']
    assert email_config()['password'] == SMTP_SECRET and email_config()['ready']
    for row in IntegrationConfig.objects.all():
        for secret in (GOOGLE_SECRET, SMTP_SECRET):
            assert secret.encode() not in bytes(row.encrypted_secrets)
            assert secret not in json.dumps(row.configuration)
    for locale in ('en', 'uz', 'ru'):
        response = client.get('/ops/integrations?lang=' + locale)
        assert response.status_code == 200
        assert GOOGLE_SECRET.encode() not in response.content and SMTP_SECRET.encode() not in response.content
        assert 'client_secret' not in response.context['google'] and 'password' not in response.context['email']
        assert b'name="client_secret"' in response.content and b'name="from_email"' in response.content
    log = json.dumps(list(AuditLog.objects.values('before', 'after', 'reason')))
    assert GOOGLE_SECRET not in log and SMTP_SECRET not in log
    assert AuditLog.objects.filter(action='integration.save').count() == 2


def test_blank_secrets_keep_previous_and_explicit_disable_preserves_credentials():
    save_config('google', GOOGLE); save_config('email', EMAIL)
    save_config('google', {**GOOGLE, 'enabled': 'false', 'client_secret': ''})
    save_config('email', {**EMAIL, 'enabled': 'false', 'password': ''})
    assert google_config()['client_secret'] == GOOGLE_SECRET and not google_config()['ready']
    assert email_config()['password'] == SMTP_SECRET and not email_config()['ready']
    assert email_config()['configured'] and google_config()['configured']


@pytest.mark.parametrize('role', ['Analyst', 'Support', 'Operations', 'Finance', 'Content manager'])
def test_only_administrators_may_read_or_change_auth_configuration(role):
    client, _ = staff_client(role)
    assert client.get('/ops/integrations').status_code == 403
    assert post_config(client, 'google', GOOGLE).status_code == 403
    assert post_config(client, 'email', EMAIL).status_code == 403
    assert not IntegrationConfig.objects.exists()


def test_auth_config_requires_staff_csrf_and_audit_reason():
    assert post_config(Client(), 'google', GOOGLE).status_code == 302
    client, _ = staff_client(csrf=True)
    assert post_config(client, 'email', EMAIL).status_code == 403
    unguarded = Client(); unguarded.cookies = client.cookies
    assert post_config(unguarded, 'google', {**GOOGLE, 'reason': ''}).status_code == 200
    assert not IntegrationConfig.objects.exists()


@pytest.mark.parametrize('redirect_uri', [
    'https://evil.example/api/v1/auth/google/callback',
    'https://app.example.com/api/v1/auth/google/callback?next=evil',
    'https://app.example.com/api/v1/auth/google/callback#fragment',
    'https://app.example.com/incorrect', 'https://user:password@app.example.com/api/v1/auth/google/callback',
    'https://app.example.com:444/api/v1/auth/google/callback',
    'http://app.example.com/api/v1/auth/google/callback',
    'https://app.example.com/api/v1/auth/google/\ncallback',
    'https://app.example.com:bad/api/v1/auth/google/callback',
])
def test_google_callback_must_be_exact_secure_and_same_origin(redirect_uri):
    with pytest.raises(DomainError, match='invalid_google_redirect'):
        save_config('google', {**GOOGLE, 'redirect_uri': redirect_uri})
    assert not IntegrationConfig.objects.exists()


def test_google_requires_client_credentials_and_valid_google_id(settings):
    with pytest.raises(DomainError, match='google_not_configured'):
        save_config('google', {**GOOGLE, 'client_secret': ''})
    with pytest.raises(DomainError, match='invalid_google_client_id'):
        save_config('google', {**GOOGLE, 'client_id': 'arbitrary-url.example'})
    settings.TELEGRAM_WEBAPP_URL = 'http://localhost:3000/en/app'
    local = {**GOOGLE, 'redirect_uri': 'http://localhost:3000/api/v1/auth/google/callback'}
    save_config('google', local)
    assert google_config()['ready']
    settings.DEBUG = False
    with pytest.raises(DomainError, match='invalid_google_redirect'): save_config('google', local)


def test_google_stops_being_ready_if_webapp_origin_changes(settings):
    save_config('google', GOOGLE)
    settings.TELEGRAM_WEBAPP_URL = 'https://other.example.com/en/app'
    assert google_config()['enabled'] and not google_config()['ready']


@pytest.mark.parametrize(('changes', 'error'), [
    ({'host': 'smtp.example.com/path'}, 'invalid_smtp_host'),
    ({'host': 'smtp.example.com\r\n'}, 'invalid_smtp_host'),
    ({'port': '65536'}, 'invalid_smtp_port'), ({'port': '0'}, 'invalid_smtp_port'),
    ({'port': 'not-port'}, 'invalid_smtp_port'),
    ({'from_email': 'sender@example.com\r\nBcc: victim@example.com'}, 'invalid_email_sender'),
    ({'use_ssl': 'true'}, 'invalid_email_security'),
    ({'username': 'x' * 255}, 'invalid_parameters'),
    ({'password': 'x' * 1025}, 'invalid_parameters'),
    ({'password': ''}, 'email_not_configured'),
])
def test_smtp_input_validation(changes, error):
    with pytest.raises(DomainError, match=error): save_config('email', {**EMAIL, **changes})
    assert not IntegrationConfig.objects.exists()


def test_plaintext_smtp_is_disabled_in_production(settings):
    settings.DEBUG = False
    with pytest.raises(DomainError, match='email_tls_required'):
        save_config('email', {**EMAIL, 'use_tls': 'false'})
    save_config('email', {**EMAIL, 'use_tls': 'false', 'use_ssl': 'true', 'port': '465'})
    assert email_config()['ready']


def test_smtp_connection_test_authenticates_without_sending_mail(monkeypatch):
    save_config('email', EMAIL)
    connection = Mock()
    factory = Mock(return_value=connection)
    monkeypatch.setattr('operations.integrations._email_connection', factory)
    check_email()
    connection.open.assert_called_once_with(); connection.close.assert_called_once_with()
    connection.send_messages.assert_not_called()
    row = IntegrationConfig.objects.get(key='email')
    assert row.check_status == 'connected' and row.checked_at is not None


def test_smtp_test_failure_is_sanitized_in_admin_and_not_logged(monkeypatch):
    client, _ = staff_client(); save_config('email', EMAIL)
    connection = Mock(); connection.open.side_effect = RuntimeError('Provider response ' + SMTP_SECRET)
    monkeypatch.setattr('operations.integrations._email_connection', lambda cfg: connection)
    response = client.post('/ops/integrations', {'integration': 'email', 'action': 'test',
                                               'reason': 'Check saved SMTP connection'})
    assert response.status_code == 200 and b'email_connection_failed' in response.content
    assert SMTP_SECRET.encode() not in response.content
    assert not AuditLog.objects.exists()


def test_smtp_action_cannot_trigger_google_or_bot_actions(monkeypatch):
    client, _ = staff_client(); probe = Mock()
    monkeypatch.setattr('operations.integration_views.test_telegram', probe)
    monkeypatch.setattr('operations.integration_views.test_email', probe)
    for kind, action in [('google', 'test'), ('email', 'start'), ('email', 'stop')]:
        response = client.post('/ops/integrations', {'integration': kind, 'action': action,
                                                   'reason': 'Reject action for another provider'})
        assert response.status_code == 200 and b'invalid_parameters' in response.content
    probe.assert_not_called()


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_auth_codes_use_private_mail_backend_and_single_recipient(locale):
    save_config('email', EMAIL)
    send_auth_email('recipient@example.com', '123456', 'verify_email', locale)
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ['recipient@example.com']
    assert mail.outbox[0].from_email == EMAIL['from_email']
    assert '123456' in mail.outbox[0].body
    assert GOOGLE_SECRET not in mail.outbox[0].body and SMTP_SECRET not in mail.outbox[0].body


def test_smtp_runtime_uses_explicit_saved_settings_and_timeout(settings, monkeypatch):
    save_config('email', EMAIL)
    settings.DEBUG = False
    connection = Mock(); connection.send_messages.return_value = 1
    factory = Mock(return_value=connection)
    monkeypatch.setattr('django.core.mail.get_connection', factory)
    send_auth_email('recipient@example.com', '246810', 'reset_password')
    factory.assert_called_once_with('django.core.mail.backends.smtp.EmailBackend', host=EMAIL['host'], port=587,
                                   username=EMAIL['username'], password=SMTP_SECRET, use_tls=True, use_ssl=False,
                                   timeout=10, fail_silently=False)
    sent = connection.send_messages.call_args.args[0][0]
    assert 'password reset' in sent.subject and sent.to == ['recipient@example.com']
    connection.close.assert_called_once()


def test_disabled_email_and_provider_errors_fail_closed(monkeypatch):
    with pytest.raises(DomainError, match='email_not_configured'):
        send_auth_email('recipient@example.com', '123456', 'verify_email')
    save_config('email', EMAIL)
    connection = Mock(); connection.send_messages.side_effect = RuntimeError(SMTP_SECRET)
    monkeypatch.setattr('operations.integrations._email_connection', lambda cfg: connection)
    with pytest.raises(DomainError, match='email_delivery_failed') as caught:
        send_auth_email('recipient@example.com', '123456', 'verify_email')
    assert SMTP_SECRET not in str(caught.value)
    connection.close.assert_called_once()
