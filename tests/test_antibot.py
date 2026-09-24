"""Auth gates reject missing, replayed, misdirected and unverifiable proofs."""
from datetime import timedelta
from http.client import IncompleteRead
from unittest.mock import Mock

import pytest
from django.test import Client, RequestFactory
from django.utils import timezone

from apps.core import antibot
from apps.core.errors import DomainError
from apps.core.models import Account, AuthReceipt

pytestmark = pytest.mark.django_db


@pytest.fixture
def protection(monkeypatch):
    cfg = {'web_enabled': True, 'configured': True, 'site_key': 'public-site-key',
           'secret_key': 'private-test-secret', 'allowed_hostnames': ['pdfmaster.orderdesk.live']}
    monkeypatch.setattr(antibot, 'antibot_config', lambda: cfg)
    check = Mock(return_value={'success': True, 'action': 'customer_auth',
                             'hostname': 'pdfmaster.orderdesk.live', 'challenge_ts': timezone.now().isoformat(), 'cdata': 'browser-binding'})
    monkeypatch.setattr(antibot, 'siteverify', check)
    return cfg, check


def verify(token='fresh-proof'):
    request = RequestFactory().post('/')
    request.session = {'antibot_binding': 'browser-binding'}
    antibot.require_web_verification(request, {'antibot_token': token})


def rejects(code, fn, status=403):
    with pytest.raises(DomainError) as exc:
        fn()
    assert (exc.value.code, exc.value.status) == (code, status)


@pytest.mark.parametrize('token', [None, '', [], {}, True, 123, 'x' * 2049])
def test_missing_malformed_proof_never_contacts_provider(protection, token):
    rejects('antibot_required', lambda: verify(token))
    protection[1].assert_not_called()
    assert not AuthReceipt.objects.exists()


def test_proof_is_single_use_even_on_different_browser(protection):
    verify()
    rejects('antibot_failed', verify)
    protection[1].assert_called_once_with('fresh-proof', 'private-test-secret')
    assert AuthReceipt.objects.count() == 1
    assert 'fresh-proof' not in AuthReceipt.objects.get().digest


@pytest.mark.parametrize('overrides', [
    {'success': False}, {'success': 'true'}, {'action': 'another_action'},
    {'cdata': 'different-browser'}, {'cdata': None}, {'cdata': 'é'},
    {'hostname': 'attacker.example'}, {'hostname': 'pdfmaster.orderdesk.live.attacker.example'},
    {'challenge_ts': ''}, {'challenge_ts': '2026-01-01'}, {'challenge_ts': 25},
    {'challenge_ts': (timezone.now() - timedelta(seconds=301)).isoformat()},
    {'challenge_ts': (timezone.now() + timedelta(seconds=60)).isoformat()},
])
def test_provider_result_must_match_action_host_freshness(protection, overrides):
    protection[1].return_value.update(overrides)
    rejects('antibot_failed', verify)
    rejects('antibot_failed', verify)
    assert protection[1].call_count == 1


@pytest.mark.parametrize('failure', [TimeoutError(), OSError(), ValueError(), IncompleteRead(b''), None, [],
                                  {'success': False, 'error-codes': ['invalid-input-secret']}])
def test_upstream_failure_is_fail_closed_and_sanitized(protection, failure):
    if isinstance(failure, Exception):
        protection[1].side_effect = failure
    else:
        protection[1].return_value = failure
    rejects('antibot_unavailable', verify, 503)
    # A retry needs a fresh widget token, including after provider timeouts.
    rejects('antibot_failed', verify)


def test_disabled_does_not_load_or_verify_turnstile(protection):
    protection[0]['web_enabled'] = False
    verify(None)
    protection[1].assert_not_called()
    assert antibot.public_config(RequestFactory().get('/')) == {'enabled': False, 'configured': True, 'site_key': '', 'binding': ''}


def test_enabled_but_incomplete_fails_closed(protection):
    protection[0]['configured'] = False
    rejects('antibot_unavailable', verify, 503)
    protection[1].assert_not_called()


@pytest.mark.parametrize('path', ['email/register', 'email/login', 'email/reset',
                                 'google/start', 'browser/challenges', 'telegram/miniapp'])
def test_auth_initiation_cannot_skip_verification(protection, path):
    response = Client().post('/api/v1/auth/' + path, {}, content_type='application/json')
    assert response.status_code == 403
    assert response.json()['error']['code'] == 'antibot_required'
    assert not Account.objects.exists()
    protection[1].assert_not_called()


def test_email_link_requires_verification_for_signed_in_user(protection):
    account = Account.objects.create()
    client = Client()
    session = client.session
    session['customer_account_id'] = str(account.pk)
    session.save()
    response = client.post('/api/v1/auth/email/link', {}, content_type='application/json')
    assert response.status_code == 403
    assert response.json()['error']['code'] == 'antibot_required'


def test_valid_proof_reaches_auth_service_and_never_exposes_secret(protection, monkeypatch):
    from apps.core import auth_views
    account = Account.objects.create()
    login = Mock(return_value=account)
    monkeypatch.setattr(auth_views.auth, 'email_login', login)
    client = Client()
    binding = client.get('/api/v1/auth/providers').json()['antibot']['binding']
    protection[1].return_value['cdata'] = binding
    response = client.post('/api/v1/auth/email/login', {'email': 'a@example.com',
                           'password': 'password', 'antibot_token': 'proof'}, content_type='application/json')
    assert response.status_code == 200
    login.assert_called_once_with('a@example.com', 'password')
    metadata = client.get('/api/v1/auth/providers')
    assert metadata.json()['antibot'] == {'enabled': True, 'configured': True, 'site_key': 'public-site-key', 'binding': binding}
    assert 'private-test-secret' not in metadata.content.decode() + response.content.decode()


def test_existing_csrf_enforcement_precedes_antibot(protection):
    response = Client(enforce_csrf_checks=True).post('/api/v1/auth/email/login',
        {'antibot_token': 'proof'}, content_type='application/json')
    assert response.status_code == 403
    protection[1].assert_not_called()


def test_fresh_browser_sessions_share_provider_attempt_budget(protection, monkeypatch):
    from apps.core.models import AuthRateLimit
    from apps.core import customer_auth
    monkeypatch.setattr(customer_auth.time, 'time', lambda: 1200)
    customer_auth.auth_limit('antibot-provider', 'global', 120, 60)
    AuthRateLimit.objects.update(count=120)
    request = RequestFactory().post('/')
    request.session = {'antibot_binding': 'new-browser'}
    rejects('rate_limited', lambda: antibot.require_web_verification(request, {'antibot_token': 'new-token'}), 429)
    protection[1].assert_not_called()
    assert not AuthReceipt.objects.exists()


def test_provider_transport_bounds_response_and_uses_fixed_https(monkeypatch):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = b'{"success": false}'
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr(antibot.urllib.request, 'build_opener', Mock(return_value=opener))
    assert antibot.siteverify('proof', 'secret') == {'success': False}
    request = opener.open.call_args.args[0]
    assert request.full_url == antibot.SITEVERIFY_URL
    assert request.data == b'secret=secret&response=proof'
    assert opener.open.call_args.kwargs['timeout'] == 8
    response.read.assert_called_once_with(16385)
    assert antibot.NoRedirect().redirect_request(None, None, 302, None, None, 'https://attacker.example') is None
