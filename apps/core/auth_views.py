"""Same-origin, CSRF-protected customer authentication endpoints."""
from urllib.parse import urlencode, urlsplit

from django.db import IntegrityError
from django.http import HttpResponseRedirect
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from operations.integrations import email_config, google_config, telegram_config
from . import customer_auth as auth
from .antibot import public_config, require_web_verification
from .errors import DomainError
from .views import api, body, sign_in, current_account


def limit(request, scope, count=50):
    # REMOTE_ADDR is a shared gateway across our two proxies. Use a server-
    # issued browser bucket plus the service's per-email/account limits.
    import secrets
    identity = request.session.get('auth_rate_identity')
    if not identity:
        identity = secrets.token_urlsafe(32)
        request.session['auth_rate_identity'] = identity
    auth.auth_limit(scope, identity, count, 60)


@api(auth=False)
def providers(request):
    email, google, telegram = email_config(), google_config(), telegram_config()
    return {'email': {'enabled': email['enabled'], 'configured': email['configured']},
            'google': {'enabled': google['enabled'], 'configured': google['configured']},
            'telegram': {'enabled': bool(telegram['token'] and telegram['username']), 'configured': bool(telegram['token'] and telegram['username'])},
            'antibot': public_config(request)}


@sensitive_post_parameters('password')
@sensitive_variables()
@api(('POST',), auth=False)
def email_register(request):
    limit(request, 'email-register', 30)
    if request.account:
        raise DomainError('session_changed', 409)
    data = body(request)
    require_web_verification(request, data)
    challenge = auth.begin_email('register', data.get('email'), data.get('password'), data.get('display_name', ''), data.get('locale', 'en'))
    return {'status': 'verification_sent', 'challenge_id': str(challenge.pk)}


@sensitive_post_parameters('password')
@sensitive_variables()
@api(('POST',))
def email_link(request):
    limit(request, 'email-link', 20)
    data = body(request)
    require_web_verification(request, data)
    challenge = auth.begin_email('link', data.get('email'), data.get('password'), locale=request.account.locale, account=request.account)
    return {'status': 'verification_sent', 'challenge_id': str(challenge.pk)}


@sensitive_post_parameters('code')
@sensitive_variables()
@api(('POST',), auth=False)
def email_verify(request):
    limit(request, 'email-verify', 40)
    auth.assert_email_enabled()
    data = body(request)
    # A signup verification must not unexpectedly replace another signed-in user.
    from .models import EmailChallenge
    if request.account and EmailChallenge.objects.filter(pk=data.get('challenge_id'), purpose='register').exists():
        raise DomainError('session_changed', 409)
    account = auth.consume_email(data.get('challenge_id'), data.get('code'), account=request.account)
    return sign_in(request, account)


@sensitive_post_parameters('password')
@sensitive_variables()
@api(('POST',), auth=False)
def email_login(request):
    limit(request, 'email-login', 60)
    data = body(request)
    require_web_verification(request, data)
    account = auth.email_login(data.get('email'), data.get('password'))
    if request.account and request.account.pk != account.pk:
        raise DomainError('session_changed', 409)
    return sign_in(request, account)


@sensitive_variables()
@api(('POST',), auth=False)
def email_reset(request):
    limit(request, 'email-reset', 30)
    data = body(request)
    require_web_verification(request, data)
    challenge = auth.begin_email('reset', data.get('email'), locale=data.get('locale', 'en'))
    return {'status': 'verification_sent', 'challenge_id': str(challenge.pk)}


@sensitive_post_parameters('code', 'password')
@sensitive_variables()
@api(('POST',), auth=False)
def email_reset_confirm(request):
    limit(request, 'email-reset-confirm', 40)
    auth.assert_email_enabled()
    data = body(request)
    if 'password' not in data:
        raise DomainError('weak_password')
    auth.consume_email(data.get('challenge_id'), data.get('code'), new_password=data.get('password'))
    return {'status': 'password_reset'}


@sensitive_post_parameters('current_password', 'password')
@sensitive_variables()
@api(('POST',))
def password_change(request):
    limit(request, 'password-change', 20)
    auth.auth_limit('password-change-account', str(request.account.pk), 10, 300)
    data = body(request)
    return sign_in(request, auth.change_password(request.account, data.get('current_password'), data.get('password')))


@sensitive_variables()
@api(('POST',), auth=False)
def google_start(request):
    limit(request, 'google-start', 40)
    data = body(request)
    require_web_verification(request, data)
    return {'authorization_url': auth.begin_google(request, data.get('intent', 'login'), data.get('locale', 'en'))}


@sensitive_variables()
def google_callback(request):
    locale, intent, error = 'en', 'login', None
    try:
        if request.method != 'GET':
            raise DomainError('invalid_oauth_state')
        limit(request, 'google-callback', 60)
        challenge = auth.take_google_challenge(request)
        locale, intent = challenge.locale, challenge.intent
        if request.GET.get('error'):
            raise DomainError('google_cancelled')
        claims = auth.verify_google_code(request.GET.get('code'), challenge)
        account = auth.finish_google(claims, challenge, current_account(request))
        sign_in(request, account)
    except DomainError as exc:
        error = exc.code
    except IntegrityError:
        error = 'identity_already_linked'
    cfg = google_config()
    parsed = urlsplit(cfg['webapp_url'])
    origin = f'{parsed.scheme}://{parsed.netloc}'
    # Destination is admin-configured, never accepted from callback parameters.
    destination = origin + f'/{locale}/app' + ('/settings' if intent == 'link' else '')
    response = HttpResponseRedirect(destination + '?' + urlencode({'auth_error': error} if error else {'auth_status': 'success'}))
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'no-referrer'
    return response
