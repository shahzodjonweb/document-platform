"""Server-enforced, single-use Turnstile checks for customer auth initiation."""
import json
import secrets
from http.client import HTTPException
import urllib.error
import urllib.request
from datetime import timedelta
from urllib.parse import urlencode

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.utils.dateparse import parse_datetime
from django.views.decorators.debug import sensitive_variables

from operations.integrations import antibot_config
from .errors import DomainError
from .models import AuthReceipt

SITEVERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'
ACTION = 'customer_auth'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@sensitive_variables()
def siteverify(token, secret):
    request = urllib.request.Request(SITEVERIFY_URL, data=urlencode({
        'secret': secret, 'response': token,
    }).encode(), headers={'Content-Type': 'application/x-www-form-urlencoded'})
    # Do not forward untrusted proxy/IP headers or follow redirects with secrets.
    with urllib.request.build_opener(NoRedirect).open(request, timeout=8) as response:
        payload = response.read(16385)
        if len(payload) > 16384:
            raise ValueError('oversized response')
        return json.loads(payload)


def public_config(request):
    cfg = antibot_config()
    binding = ''
    if cfg['web_enabled']:
        binding = request.session.get('antibot_binding')
        if not binding:
            binding = secrets.token_urlsafe(24)
            request.session['antibot_binding'] = binding
    return {'enabled': cfg['web_enabled'], 'configured': cfg['configured'],
            'site_key': cfg['site_key'] if cfg['web_enabled'] else '', 'binding': binding}


@sensitive_variables()
def require_web_verification(request, data):
    cfg = antibot_config()
    if not cfg['web_enabled']:
        return
    if not cfg['configured']:
        raise DomainError('antibot_unavailable', 503, retryable=True)
    token = data.get('antibot_token')
    if not isinstance(token, str) or not token or len(token) > 2048:
        raise DomainError('antibot_required', 403, retryable=True)
    binding = request.session.get('antibot_binding')
    if not isinstance(binding, str) or not binding:
        raise DomainError('antibot_required', 403, retryable=True)
    # New cookies must not buy unlimited outbound provider work. This shared,
    # atomic budget caps traffic before the network call across API processes.
    from .customer_auth import auth_limit
    auth_limit('antibot-provider', 'global', 120, 60)
    auth_limit('antibot-browser', binding, 20, 60)

    # Database uniqueness prevents two concurrent requests from spending the same
    # proof, even before the provider responds. Invalid/failed proofs stay spent.
    receipt = salted_hmac('customer-antibot', token, algorithm='sha256').hexdigest()
    try:
        with transaction.atomic():
            AuthReceipt.objects.create(digest=receipt)
    except IntegrityError:
        raise DomainError('antibot_failed', 403, retryable=True) from None
    try:
        result = siteverify(token, cfg['secret_key'])
    except (OSError, ValueError, TypeError, urllib.error.URLError, HTTPException):
        raise DomainError('antibot_unavailable', 503, retryable=True) from None
    if not isinstance(result, dict):
        raise DomainError('antibot_unavailable', 503, retryable=True)
    if result.get('success') is not True:
        errors = result.get('error-codes', [])
        unavailable = isinstance(errors, list) and bool(set(str(code) for code in errors) & {
            'missing-input-secret', 'invalid-input-secret', 'internal-error',
        })
        raise DomainError('antibot_unavailable' if unavailable else 'antibot_failed', 503 if unavailable else 403, retryable=True)
    try:
        timestamp = parse_datetime(result.get('challenge_ts', ''))
        now = timezone.now()
        valid_time = timestamp is not None and timezone.is_aware(timestamp) and now - timedelta(seconds=300) <= timestamp <= now + timedelta(seconds=30)
    except (TypeError, ValueError):
        valid_time = False
    if (result.get('action') != ACTION or result.get('hostname') not in cfg['allowed_hostnames'] or not valid_time
            or not isinstance(result.get('cdata'), str) or not result['cdata'].isascii()
            or not secrets.compare_digest(result['cdata'], binding)):
        raise DomainError('antibot_failed', 403, retryable=True)
