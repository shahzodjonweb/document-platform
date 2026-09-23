from operations.integrations import telegram_config
import hashlib
import hmac
import json
import secrets
import time
from datetime import timedelta
from urllib.parse import parse_qsl
from django.conf import settings
from django.db import transaction, IntegrityError
from django.utils import timezone
from .models import Account, AuthChallenge, AuthReceipt, AnalyticsEvent
from .errors import DomainError

def digest(value): return hashlib.sha256(value.encode()).hexdigest()

def resolve_account(user, channel='bot', is_test=False):
    uid = user.get('id')
    if not isinstance(uid, int) or isinstance(uid, bool) or not 0 < uid < 2**63:
        raise DomainError('invalid_telegram_data', 401)
    language = str(user.get('language_code', 'en')).split('-')[0]
    defaults = {'display_name': str(user.get('first_name', ''))[:150], 'username': str(user.get('username', ''))[:64], 'locale': language if language in ('en','uz','ru') else 'en', 'first_verified_channel': channel, 'is_test': is_test}
    account, created = Account.objects.get_or_create(telegram_user_id=uid, defaults=defaults)
    if created:
        AnalyticsEvent.objects.create(account=account, event_type='account.created', channel=channel, locale=account.locale, plan_at_event='free', environment='development' if is_test or settings.DEBUG else 'production')
    else:
        if account.deletion_requested_at: raise DomainError('invalid_credentials', 401)
        account.display_name = defaults['display_name'] or account.display_name
        account.username = defaults['username']
        account.save(update_fields=['display_name','username'])
    return account

def validate_init_data(raw, now=None):
    if not telegram_config()['token'] or not isinstance(raw, str) or len(raw) > 16384:
        raise DomainError('invalid_telegram_data', 401)
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
        data = dict(pairs)
        if len(data) != len(pairs): raise ValueError('duplicate keys')
        received_hash = data.pop('hash')
        check = '\n'.join(f'{key}={value}' for key,value in sorted(data.items()))
        key = hmac.new(b'WebAppData', telegram_config()['token'].encode(), hashlib.sha256).digest()
        expected = hmac.new(key, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(received_hash, expected): raise ValueError('signature')
        age = (now if now is not None else time.time()) - int(data['auth_date'])
        if not -30 <= age <= 300: raise ValueError('stale')
        user = json.loads(data['user'])
        if not isinstance(user,dict): raise ValueError('user')
        return user, digest(expected)
    except (ValueError, KeyError, TypeError):
        raise DomainError('invalid_telegram_data', 401) from None

@transaction.atomic
def exchange_miniapp(raw):
    user, token_digest = validate_init_data(raw)
    try:
        with transaction.atomic(): AuthReceipt.objects.create(digest=token_digest)
    except IntegrityError:
        raise DomainError('auth_replayed', 409) from None
    return resolve_account(user, 'mini_app')

def create_challenge(browser_hint, link_account=None):
    if not telegram_config()['username']:
        raise DomainError('telegram_not_configured', 503)
    token, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
    challenge = AuthChallenge.objects.create(token_hash=digest(token), verifier_hash=digest(verifier), browser_hint=browser_hint[:160], expires_at=timezone.now()+timedelta(minutes=5), intent='link' if link_account else 'login', link_account=link_account, link_auth_version=link_account.auth_version if link_account else 0)
    return challenge, token, verifier

def get_bound_challenge(challenge_id, verifier):
    try: challenge = AuthChallenge.objects.get(pk=challenge_id)
    except (AuthChallenge.DoesNotExist, ValueError): raise DomainError('not_found', 404)
    if not verifier or not hmac.compare_digest(challenge.verifier_hash, digest(verifier)):
        raise DomainError('not_found', 404)
    if challenge.consumed_at: raise DomainError('auth_replayed', 409)
    if challenge.expires_at <= timezone.now(): raise DomainError('challenge_expired', 410)
    return challenge

@transaction.atomic
def approve_challenge(token, telegram_user):
    try: challenge = AuthChallenge.objects.select_for_update().get(token_hash=digest(token))
    except AuthChallenge.DoesNotExist: raise DomainError('not_found', 404)
    if challenge.expires_at <= timezone.now() or challenge.consumed_at or challenge.approved_at:
        raise DomainError('challenge_expired', 410)
    return approve_identity(challenge, telegram_user)

@transaction.atomic
def exchange_challenge(challenge_id, verifier, link_account=None):
    AuthChallenge.objects.select_for_update().filter(pk=challenge_id).first()
    challenge = get_bound_challenge(challenge_id, verifier)
    if not challenge.approved_at or not challenge.account_id: raise DomainError('challenge_pending', 409)
    if challenge.intent == 'link':
        if not link_account or link_account.pk != challenge.link_account_id:
            raise DomainError('session_changed', 409)
        account = Account.objects.select_for_update().get(pk=link_account.pk)
        validate_link(challenge, account, challenge.telegram_user)
        account.telegram_user_id = challenge.telegram_user['id']
        account.username = str(challenge.telegram_user.get('username', ''))[:64]
        try:
            with transaction.atomic(): account.save(update_fields=['telegram_user_id', 'username'])
        except IntegrityError: raise DomainError('identity_already_linked', 409) from None
        challenge.account = account
    elif link_account and link_account.pk != challenge.account_id:
        raise DomainError('session_changed', 409)
    if challenge.account.deletion_requested_at: raise DomainError('invalid_credentials', 401)
    challenge.consumed_at = timezone.now()
    challenge.save(update_fields=['consumed_at'])
    return challenge.account

@transaction.atomic
def approve_challenge_id(challenge_id, telegram_user):
    """Only the identity-bound bot callback adapter calls this, never public HTTP."""
    try: challenge=AuthChallenge.objects.select_for_update().get(pk=challenge_id)
    except (AuthChallenge.DoesNotExist,ValueError): raise DomainError('not_found',404)
    if challenge.expires_at<=timezone.now() or challenge.consumed_at or challenge.approved_at:
        raise DomainError('challenge_expired',410)
    return approve_identity(challenge, telegram_user)


def validate_link(challenge, account, user):
    uid = user.get('id')
    if not isinstance(uid, int) or isinstance(uid, bool) or not 0 < uid < 2**63:
        raise DomainError('invalid_telegram_data', 401)
    if account.deletion_requested_at or account.auth_version != challenge.link_auth_version:
        raise DomainError('session_changed', 409)
    if account.telegram_user_id and account.telegram_user_id != uid:
        raise DomainError('telegram_already_linked', 409)
    if Account.objects.filter(telegram_user_id=uid).exclude(pk=account.pk).exists():
        raise DomainError('identity_already_linked', 409)


def approve_identity(challenge, user):
    if challenge.intent == 'link':
        account = Account.objects.select_for_update().get(pk=challenge.link_account_id)
        validate_link(challenge, account, user)
        challenge.telegram_user = {key: user[key] for key in ('id', 'username') if key in user}
    else:
        account = resolve_account(user, 'web')
    challenge.account, challenge.approved_at = account, timezone.now()
    challenge.save(update_fields=['account', 'approved_at', 'telegram_user'])
    return account
