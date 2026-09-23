from datetime import timedelta
from pathlib import Path
import pytest
from django.utils import timezone
from django.test import Client
from apps.core.models import AuthRateLimit, EmailChallenge, GoogleChallenge
from apps.core.services import cleanup_expired

pytestmark = pytest.mark.django_db


def test_cleanup_removes_expired_credentials_but_preserves_active_challenge():
    old, future = timezone.now()-timedelta(minutes=1), timezone.now()+timedelta(minutes=5)
    expired = EmailChallenge.objects.create(email='owner@example.com', code_hash='x', purpose='register', password_hash='sensitivehash', expires_at=old)
    active = EmailChallenge.objects.create(email='other@example.com', code_hash='y', purpose='register', expires_at=future)
    GoogleChallenge.objects.create(state_hash='x', browser_hash='y', nonce='n', verifier='secret', intent='login', client_id='c', redirect_uri='https://example.com', expires_at=old)
    AuthRateLimit.objects.create(key='x', expires_at=old)
    cleanup_expired()
    assert not EmailChallenge.objects.filter(pk=expired.pk).exists()
    assert EmailChallenge.objects.filter(pk=active.pk).exists()
    assert not GoogleChallenge.objects.exists() and not AuthRateLimit.objects.exists()


def test_customer_auth_rate_buckets_do_not_combine_visitors_behind_gateway():
    from apps.core.auth_views import limit
    from django.test import RequestFactory
    from django.contrib.sessions.middleware import SessionMiddleware
    requests = [RequestFactory().get('/api/v1/auth/providers', REMOTE_ADDR='172.20.0.4') for _ in range(2)]
    for request in requests:
        SessionMiddleware(lambda r: None).process_request(request)
    limit(requests[0], 'test', 1)
    limit(requests[1], 'test', 1)
    assert requests[0].session['auth_rate_identity'] != requests[1].session['auth_rate_identity']
    assert AuthRateLimit.objects.count() == 2


def test_production_access_logs_omit_callback_query_strings(settings):
    dockerfile = (settings.BASE_DIR/'infra/Dockerfile').read_text()
    assert '--access-logformat' in dockerfile and '%(U)s' in dockerfile
    assert '%(r)s' not in dockerfile and '%(q)s' not in dockerfile
    config = (settings.BASE_DIR/'infra/production/nginx.conf').read_text()
    assert 'log_format pdfmaster_safe' in config and '$uri' in config
    assert '$request_uri' not in config and '$http_referer' not in config


@pytest.mark.parametrize('password', ['owner@example.com', 'Example Customer'])
def test_personal_details_are_rejected_as_passwords_without_server_error(password):
    from apps.core.customer_auth import password_hash
    from apps.core.errors import DomainError
    with pytest.raises(DomainError, match='weak_password'):
        password_hash(password, 'owner@example.com', 'Example Customer')
