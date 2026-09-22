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
        account.display_name = defaults['display_name'] or account.display_name
        account.username = defaults['username']
        account.save(update_fields=['display_name','username'])
    return account

def validate_init_data(raw, now=None):
    if not settings.TELEGRAM_BOT_TOKEN or not isinstance(raw, str) or len(raw) > 16384:
        raise DomainError('invalid_telegram_data', 401)
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
        data = dict(pairs)
        if len(data) != len(pairs): raise ValueError('duplicate keys')
        received_hash = data.pop('hash')
        check = '\n'.join(f'{key}={value}' for key,value in sorted(data.items()))
        key = hmac.new(b'WebAppData', settings.TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256).digest()
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

def create_challenge(browser_hint):
    if not settings.TELEGRAM_BOT_USERNAME:
        raise DomainError('telegram_not_configured', 503)
    token, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
    challenge = AuthChallenge.objects.create(token_hash=digest(token), verifier_hash=digest(verifier), browser_hint=browser_hint[:160], expires_at=timezone.now()+timedelta(minutes=5))
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
    account = resolve_account(telegram_user, 'web')
    challenge.account, challenge.approved_at = account, timezone.now()
    challenge.save(update_fields=['account','approved_at'])
    return account

@transaction.atomic
def exchange_challenge(challenge_id, verifier):
    AuthChallenge.objects.select_for_update().filter(pk=challenge_id).first()
    challenge = get_bound_challenge(challenge_id, verifier)
    if not challenge.approved_at or not challenge.account_id: raise DomainError('challenge_pending', 409)
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
    account=resolve_account(telegram_user,'web')
    challenge.account,challenge.approved_at=account,timezone.now()
    challenge.save(update_fields=['account','approved_at'])
    return account
