"""Customer credentials and single-account identity linking.

External identifiers are never transferred between accounts. Email equality alone
is not authorization to link a Google login; the existing session must prove it.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.request
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import (
    CommonPasswordValidator, MinimumLengthValidator, NumericPasswordValidator,
    UserAttributeSimilarityValidator, validate_password,
)
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.debug import sensitive_variables
from google.oauth2 import id_token

from operations.integrations import email_config, google_config, send_auth_email
from .errors import DomainError
from .identity import digest
from .models import Account, AnalyticsEvent, AuthRateLimit, EmailChallenge, GoogleChallenge

PASSWORD_VALIDATORS = [MinimumLengthValidator(12), CommonPasswordValidator(), NumericPasswordValidator(), UserAttributeSimilarityValidator()]


def normalize_email(value):
    if not isinstance(value, str) or len(value) > 254:
        raise DomainError('invalid_email')
    email = value.strip().lower()
    try:
        validate_email(email)
    except ValidationError:
        raise DomainError('invalid_email') from None
    return email


@sensitive_variables()
def password_hash(password, email='', display_name=''):
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise DomainError('weak_password')
    try:
        validate_password(password, get_user_model()(email=email, username=email.split('@')[0], first_name=display_name), PASSWORD_VALIDATORS)
    except ValidationError:
        raise DomainError('weak_password') from None
    return make_password(password)


def auth_limit(scope, identity, limit, seconds):
    """Atomic fixed-window limiter shared across workers, with hashed identifiers."""
    window = int(time.time()) // seconds
    key = salted_hmac('customer-auth-rate', f'{scope}:{identity}:{window}', algorithm='sha256').hexdigest()
    with transaction.atomic():
        row, _ = AuthRateLimit.objects.get_or_create(key=key, defaults={'expires_at': timezone.now() + timedelta(seconds=seconds * 2)})
        row = AuthRateLimit.objects.select_for_update().get(pk=row.pk)
        if row.count >= limit:
            raise DomainError('rate_limited', 429, retryable=True)
        row.count += 1
        row.save(update_fields=['count'])


def code_digest(challenge_id, code):
    return salted_hmac('customer-email-code', f'{challenge_id}:{code}', algorithm='sha256').hexdigest()


def assert_email_enabled():
    cfg = email_config()
    if not cfg['enabled'] or not cfg['configured']:
        raise DomainError('email_not_configured', 503)


def record_creation(account, channel):
    AnalyticsEvent.objects.create(account=account, event_type='account.created', channel=channel, locale=account.locale, environment='development' if settings.DEBUG else 'production')


@sensitive_variables()
def begin_email(purpose, email, password='', display_name='', locale='en', account=None):
    assert_email_enabled()
    email = normalize_email(email)
    auth_limit('email-send', email, 6, 3600)
    locale = locale if locale in ('en', 'uz', 'ru') else 'en'
    existing = Account.objects.filter(email=email).first()
    encoded = password_hash(password, email, display_name) if purpose != 'reset' else ''
    if purpose == 'link':
        if not account:
            raise DomainError('authentication_required', 401)
        if (existing and existing.pk != account.pk) or (account.email and account.email != email):
            raise DomainError('identity_already_linked', 409)
        if account.password_hash:
            raise DomainError('email_already_linked', 409)
    eligible = not existing if purpose == 'register' else True
    if purpose == 'reset':
        account = existing
        eligible = bool(existing and existing.password_hash and existing.email_verified_at and not existing.deletion_requested_at)
    code = f'{secrets.randbelow(100000000):08d}'
    challenge = EmailChallenge(email=email, purpose=purpose, account=account, auth_version=account.auth_version if account else 0,
        password_hash=encoded, display_name=str(display_name).strip()[:150], locale=locale, eligible=eligible,
        expires_at=timezone.now() + timedelta(minutes=15))
    challenge.code_hash = code_digest(challenge.pk, code)
    challenge.save()
    if eligible:
        try:
            send_auth_email(email, code, {'register': 'verify_email', 'link': 'link_email', 'reset': 'reset_password'}[purpose], locale)
        except Exception:
            challenge.delete()
            raise DomainError('email_delivery_failed', 503) from None
    return challenge


@sensitive_variables()
def consume_email(challenge_id, code, *, account=None, new_password=None):
    """Commit unsuccessful attempts before returning an error, so retries persist."""
    error = None
    result = None
    with transaction.atomic():
        try:
            challenge = EmailChallenge.objects.select_for_update().get(pk=challenge_id)
        except (EmailChallenge.DoesNotExist, ValueError, ValidationError):
            raise DomainError('invalid_verification_code') from None
        expected_purpose = 'reset' if new_password is not None else None
        if challenge.consumed_at or challenge.expires_at <= timezone.now():
            error = DomainError('verification_expired', 410)
        elif challenge.attempts >= 5:
            error = DomainError('verification_locked', 429)
        elif (expected_purpose == 'reset') != (challenge.purpose == 'reset'):
            error = DomainError('invalid_verification_code')
        elif challenge.purpose == 'link' and (not account or account.pk != challenge.account_id):
            error = DomainError('session_changed', 409)
        else:
            challenge.attempts += 1
            challenge.save(update_fields=['attempts'])
            if not isinstance(code, str) or len(code) != 8 or not code.isascii() or not code.isdigit() or not challenge.eligible or not hmac.compare_digest(challenge.code_hash, code_digest(challenge.pk, code)):
                error = DomainError('invalid_verification_code')
            else:
                try:
                    with transaction.atomic():
                        result = finish_email(challenge, new_password)
                        challenge.consumed_at = timezone.now()
                        challenge.password_hash = ''
                        challenge.save(update_fields=['consumed_at', 'password_hash'])
                except DomainError as exc:
                    error = exc
                except IntegrityError:
                    error = DomainError('identity_already_linked', 409)
    if error:
        raise error
    return result


@sensitive_variables()
def finish_email(challenge, new_password):
    if challenge.purpose == 'register':
        if Account.objects.filter(email=challenge.email).exists():
            raise DomainError('identity_already_linked', 409)
        account = Account.objects.create(email=challenge.email, password_hash=challenge.password_hash, email_verified_at=timezone.now(),
            display_name=challenge.display_name or challenge.email.split('@')[0], locale=challenge.locale, first_verified_channel='email')
        record_creation(account, 'email')
        return account
    account = Account.objects.select_for_update().get(pk=challenge.account_id)
    if account.deletion_requested_at or account.auth_version != challenge.auth_version:
        raise DomainError('session_changed', 409)
    if challenge.purpose == 'reset':
        if account.email != challenge.email or not account.password_hash:
            raise DomainError('session_changed', 409)
        account.password_hash = password_hash(new_password, account.email, account.display_name)
        account.auth_version += 1
        account.save(update_fields=['password_hash', 'auth_version'])
    else:
        if account.password_hash or (account.email and account.email != challenge.email):
            raise DomainError('email_already_linked', 409)
        account.email = challenge.email
        account.email_verified_at = timezone.now()
        account.password_hash = challenge.password_hash
        account.save(update_fields=['email', 'email_verified_at', 'password_hash'])
    return account


@sensitive_variables()
def email_login(email, password):
    assert_email_enabled()
    email = normalize_email(email)
    auth_limit('password-login', email, 10, 300)
    account = Account.objects.filter(email=email, deletion_requested_at__isnull=True).first()
    supplied = password if isinstance(password, str) and len(password) <= 128 else ''
    if not account or not account.password_hash or not account.email_verified_at:
        # Run the password hasher even for an unknown email to reduce timing leaks.
        make_password(supplied)
        raise DomainError('invalid_credentials', 401)
    if not check_password(supplied, account.password_hash):
        raise DomainError('invalid_credentials', 401)
    return account


@transaction.atomic
@sensitive_variables()
def change_password(account, current_password, password):
    account = Account.objects.select_for_update().get(pk=account.pk)
    if not account.password_hash or not isinstance(current_password, str) or len(current_password) > 128 or not check_password(current_password, account.password_hash):
        raise DomainError('invalid_credentials', 401)
    account.password_hash = password_hash(password, account.email, account.display_name)
    account.auth_version += 1
    account.save(update_fields=['password_hash', 'auth_version'])
    return account


@sensitive_variables()
def begin_google(request, intent, locale):
    cfg = google_config()
    if not cfg['enabled'] or not cfg['configured']:
        raise DomainError('google_not_configured', 503)
    if intent not in ('login', 'link'):
        raise DomainError('invalid_request')
    if intent == 'link' and not request.account:
        raise DomainError('authentication_required', 401)
    if intent == 'login' and request.account:
        raise DomainError('session_changed', 409)
    if request.account and request.account.google_sub:
        raise DomainError('google_already_linked', 409)
    state, browser, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(4))
    request.session['google_browser'] = browser
    challenge = GoogleChallenge.objects.create(state_hash=digest(state), browser_hash=digest(browser), nonce=nonce, verifier=verifier, intent=intent,
        account=request.account if intent == 'link' else None, auth_version=request.account.auth_version if request.account else 0,
        client_id=cfg['client_id'], redirect_uri=cfg['redirect_uri'], locale=locale if locale in ('en', 'uz', 'ru') else 'en',
        expires_at=timezone.now() + timedelta(minutes=10))
    pkce = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    return 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
        'client_id': cfg['client_id'], 'redirect_uri': cfg['redirect_uri'], 'response_type': 'code', 'scope': 'openid email profile',
        'state': state, 'nonce': nonce, 'code_challenge': pkce, 'code_challenge_method': 'S256', 'prompt': 'select_account',
    })


def take_google_challenge(request):
    state = request.GET.get('state', '')
    browser = request.session.get('google_browser', '')
    with transaction.atomic():
        challenge = GoogleChallenge.objects.select_for_update().filter(state_hash=digest(state)).first() if len(state) <= 128 else None
        if not challenge or not browser or not hmac.compare_digest(challenge.browser_hash, digest(browser)) or challenge.consumed_at or challenge.expires_at <= timezone.now():
            raise DomainError('invalid_oauth_state')
        challenge.consumed_at = timezone.now()
        challenge.save(update_fields=['consumed_at'])
    request.session.pop('google_browser', None)
    return challenge


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def google_request(url, data=None):
    request = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/x-www-form-urlencoded'} if data else {})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=10) as response:
        value = response.read(131073)
        if len(value) > 131072:
            raise ValueError('response too large')
        return value


def google_certificates(url, method='GET', **kwargs):
    if url != 'https://www.googleapis.com/oauth2/v1/certs' or method != 'GET':
        raise ValueError('unexpected certificate endpoint')
    certs = cache.get('google-oidc-certificates-v1')
    if certs is None:
        certs = google_request(url)
        cache.set('google-oidc-certificates-v1', certs, 300)
    return SimpleNamespace(status=200, data=certs)


@sensitive_variables()
def verify_google_code(code, challenge):
    cfg = google_config()
    if not cfg['enabled'] or not cfg['configured'] or cfg['client_id'] != challenge.client_id or cfg['redirect_uri'] != challenge.redirect_uri:
        raise DomainError('google_not_configured', 503)
    if not isinstance(code, str) or not code or len(code) > 4096:
        raise DomainError('google_login_failed', 401)
    try:
        tokens = json.loads(google_request('https://oauth2.googleapis.com/token', urlencode({
            'code': code, 'client_id': cfg['client_id'], 'client_secret': cfg['client_secret'],
            'redirect_uri': challenge.redirect_uri, 'grant_type': 'authorization_code', 'code_verifier': challenge.verifier,
        }).encode()))
        claims = id_token.verify_oauth2_token(tokens['id_token'], google_certificates, audience=cfg['client_id'])
        if not isinstance(claims.get('nonce'), str) or not hmac.compare_digest(claims['nonce'], challenge.nonce):
            raise ValueError('nonce')
        if claims.get('email_verified') is not True or not isinstance(claims.get('sub'), str) or not 1 <= len(claims['sub']) <= 255:
            raise ValueError('identity')
        if claims.get('azp', cfg['client_id']) != cfg['client_id']:
            raise ValueError('authorized party')
        claims['email'] = normalize_email(claims.get('email'))
        return claims
    except Exception:
        # Never include provider error bodies, codes, ID tokens or client secrets.
        raise DomainError('google_login_failed', 401) from None


@transaction.atomic
@sensitive_variables()
def finish_google(claims, challenge, account=None):
    existing = Account.objects.select_for_update().filter(google_sub=claims['sub']).first()
    if challenge.intent == 'link':
        if not account or account.pk != challenge.account_id:
            raise DomainError('session_changed', 409)
        target = Account.objects.select_for_update().get(pk=account.pk)
        if target.deletion_requested_at or target.auth_version != challenge.auth_version:
            raise DomainError('session_changed', 409)
        if existing and existing.pk != target.pk:
            raise DomainError('identity_already_linked', 409)
        if target.google_sub and target.google_sub != claims['sub']:
            raise DomainError('google_already_linked', 409)
        # A provider email owned by another account is never silently merged.
        if Account.objects.filter(email=claims['email']).exclude(pk=target.pk).exists():
            raise DomainError('identity_already_linked', 409)
        target.google_sub, target.google_email = claims['sub'], claims['email']
        if not target.email:
            target.email, target.email_verified_at = claims['email'], timezone.now()
        target.save(update_fields=['google_sub', 'google_email', 'email', 'email_verified_at'])
        return target
    if account:
        raise DomainError('session_changed', 409)
    if existing:
        if existing.deletion_requested_at:
            raise DomainError('invalid_credentials', 401)
        return existing
    if Account.objects.filter(email=claims['email']).exists():
        raise DomainError('identity_already_linked', 409)
    target = Account.objects.create(google_sub=claims['sub'], google_email=claims['email'], email=claims['email'], email_verified_at=timezone.now(),
        display_name=str(claims.get('name') or claims['email'].split('@')[0])[:150], locale=challenge.locale, first_verified_channel='google')
    record_creation(target, 'google')
    return target
