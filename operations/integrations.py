"""Admin-managed credentials. Never put tokens in URLs returned to clients or logs."""
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import urllib.request
from urllib.parse import urlsplit
from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
from apps.core.errors import DomainError
from .models import IntegrationConfig

_process = None
_lock = threading.Lock()

def cipher():
    legacy = Fernet(base64.urlsafe_b64encode(hashlib.sha256((settings.SECRET_KEY + ':integration-secrets-v1').encode()).digest()))
    configured=os.getenv('INTEGRATION_ENCRYPTION_KEY','')
    if configured:return Fernet(configured.encode())
    if not settings.DEBUG:return legacy
    # Persist a random local key outside Git even when the demo signing key is used.
    root=settings.PRIVATE_STORAGE_ROOT
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=root/'integration.key'
    try:
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:pass
    else:
        with os.fdopen(fd,'wb') as output:output.write(Fernet.generate_key())
    # Legacy reader preserves drafts created before local key provisioning.
    return MultiFernet([Fernet(path.read_bytes()),legacy])

def read_config(key):
    row = IntegrationConfig.objects.filter(pk=key).first()
    if not row: return {}, {}
    secrets = json.loads(cipher().decrypt(bytes(row.encrypted_secrets))) if row.encrypted_secrets else {}
    return row.configuration, secrets

def telegram_config():
    cfg, secret = read_config('telegram')
    return {'token':secret.get('token') or settings.TELEGRAM_BOT_TOKEN,
            'username':cfg.get('username') or settings.TELEGRAM_BOT_USERNAME,
            'webhook_secret':secret.get('webhook_secret') or settings.TELEGRAM_WEBHOOK_SECRET,
            'webapp_url':cfg.get('webapp_url') or settings.TELEGRAM_WEBAPP_URL}

def ai_config():
    cfg, secret = read_config('ai')
    return {'mode':cfg.get('mode','local_fixture' if settings.DEBUG else 'disabled'),
            'model':cfg.get('model') or os.getenv('AI_MODEL',''),
            'image_model':cfg.get('image_model') or os.getenv('AI_IMAGE_MODEL',''),
            'api_key':secret.get('api_key') or os.getenv('OPENAI_API_KEY','')}

def _boolean(value):
    if value is True or value in ('true', '1', 'on'): return True
    if value is False or value in ('false', '0', 'off', '', None): return False
    raise DomainError('invalid_parameters')

def _web_origin(url):
    try:
        parsed = urlsplit(url)
        valid = (parsed.hostname and not parsed.username and not parsed.password
                 and (parsed.port is None or 1 <= parsed.port <= 65535)
                 and not any(ord(c) < 33 or ord(c) == 127 for c in url))
        secure = parsed.scheme == 'https' or (settings.DEBUG and parsed.scheme == 'http'
                                             and parsed.hostname in ('localhost', '127.0.0.1', '::1'))
        if not valid or not secure: raise ValueError()
        return parsed, (parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == 'https' else 80))
    except (ValueError, TypeError): raise DomainError('invalid_google_redirect') from None

def _validate_google(cfg, secrets, webapp_url):
    client_id = cfg.get('client_id', '')
    if client_id and not re.fullmatch(r'[A-Za-z0-9_-]{1,220}\.apps\.googleusercontent\.com', client_id):
        raise DomainError('invalid_google_client_id')
    redirect = cfg.get('redirect_uri', '')
    if redirect:
        callback, origin = _web_origin(redirect)
        _, web_origin = _web_origin(webapp_url)
        if origin != web_origin or callback.path != '/api/v1/auth/google/callback' or callback.query or callback.fragment:
            raise DomainError('invalid_google_redirect')
    if cfg.get('enabled') and not (client_id and secrets.get('client_secret') and redirect):
        raise DomainError('google_not_configured')

def google_config():
    cfg, secret = read_config('google')
    webapp_url = telegram_config()['webapp_url']
    parsed = urlsplit(webapp_url)
    redirect_uri = cfg.get('redirect_uri') or f'{parsed.scheme}://{parsed.netloc}/api/v1/auth/google/callback'
    result = {'enabled': cfg.get('enabled', False), 'client_id': cfg.get('client_id', ''),
              'client_secret': secret.get('client_secret', ''), 'redirect_uri': redirect_uri,
              'webapp_url': webapp_url}
    configured = bool(result['client_id'] and result['client_secret'] and redirect_uri)
    try: _validate_google(result, secret, webapp_url)
    except DomainError: configured = False
    return {**result, 'configured': configured, 'ready': bool(result['enabled'] and configured)}

def email_config():
    cfg, secret = read_config('email')
    result = {'enabled': cfg.get('enabled', False), 'host': cfg.get('host', ''), 'port': cfg.get('port', 587),
              'username': cfg.get('username', ''), 'password': secret.get('password', ''),
              'use_tls': cfg.get('use_tls', True), 'use_ssl': cfg.get('use_ssl', False),
              'from_email': cfg.get('from_email', '')}
    configured = bool(result['host'] and result['from_email'] and (not result['username'] or result['password'])
                      and not (result['use_tls'] and result['use_ssl'])
                      and (settings.DEBUG or result['use_tls'] or result['use_ssl']))
    return {**result, 'configured': configured, 'ready': bool(result['enabled'] and configured)}

# Cloudflare's published dummy credentials must never become production protection.
# https://developers.cloudflare.com/turnstile/troubleshooting/testing/
_TURNSTILE_TEST_SITE_KEYS = frozenset({
    '1x00000000000000000000AA', '2x00000000000000000000AB',
    '1x00000000000000000000BB', '2x00000000000000000000BB',
    '3x00000000000000000000FF',
})
_TURNSTILE_TEST_SECRET_KEYS = frozenset({
    '1x0000000000000000000000000000000AA',
    '2x0000000000000000000000000000000AA',
    '3x0000000000000000000000000000000AA',
})
_ANTIBOT_DEFAULT_HOSTS = ('pdfmaster.orderdesk.live',)


def _antibot_hostnames(value):
    if isinstance(value, str):
        if len(value) > 6000: raise DomainError('invalid_antibot_hostnames')
        value = re.split(r'[\s,]+', value.strip()) if value.strip() else []
    if not isinstance(value, (list, tuple)) or len(value) > 20:
        raise DomainError('invalid_antibot_hostnames')
    hosts = []
    for hostname in value:
        if not isinstance(hostname, str) or not hostname or len(hostname) > 253:
            raise DomainError('invalid_antibot_hostnames')
        # Exact DNS names only: no schemes, ports, paths, credentials or wildcards.
        hostname = hostname.lower()
        if any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
               for label in hostname.split('.')):
            raise DomainError('invalid_antibot_hostnames')
        if hostname not in hosts: hosts.append(hostname)
    return hosts


def _validate_antibot(cfg, secrets):
    site_key, secret_key = cfg.get('site_key', ''), secrets.get('secret_key', '')
    if site_key and (not isinstance(site_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{10,256}', site_key)):
        raise DomainError('invalid_antibot_site_key')
    if secret_key and (not isinstance(secret_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{10,1024}', secret_key)):
        raise DomainError('invalid_antibot_secret_key')
    hosts = _antibot_hostnames(cfg.get('allowed_hostnames', list(_ANTIBOT_DEFAULT_HOSTS)))
    if not settings.DEBUG and (site_key in _TURNSTILE_TEST_SITE_KEYS or secret_key in _TURNSTILE_TEST_SECRET_KEYS):
        raise DomainError('antibot_test_keys_forbidden')
    if cfg.get('web_enabled') and not (site_key and secret_key and hosts):
        raise DomainError('antibot_not_configured')


def antibot_config():
    cfg, secret = read_config('antibot')
    result = {'web_enabled': cfg.get('web_enabled', False),
              'bot_enabled': cfg.get('bot_enabled', not settings.DEBUG),
              'site_key': cfg.get('site_key', ''), 'secret_key': secret.get('secret_key', ''),
              'allowed_hostnames': cfg.get('allowed_hostnames', list(_ANTIBOT_DEFAULT_HOSTS))}
    configured = bool(result['site_key'] and result['secret_key'] and result['allowed_hostnames'])
    try: _validate_antibot(result, secret)
    except DomainError: configured = False
    return {**result, 'configured': configured, 'ready': bool(result['web_enabled'] and configured)}

# Pixabay issues keys as "<account number>-<hex>". Anything else is a paste
# error, and refusing it here beats discovering it inside a customer's job.
_PIXABAY_KEY = re.compile(r'[0-9]{1,12}-[0-9a-f]{20,40}')


def pixabay_config():
    """Stock photos for slide decks. `enabled` is the kill switch."""
    cfg, secret = read_config('pixabay')
    api_key = secret.get('api_key') or os.getenv('PIXABAY_API_KEY', '')
    enabled = bool(cfg.get('enabled', False))
    return {'enabled': enabled, 'api_key': api_key, 'configured': bool(api_key),
            'ready': bool(enabled and api_key)}


# Telegram usernames: 5-32 characters, letters, digits and underscores, starting with a letter.
_TELEGRAM_USERNAME = re.compile(r'[A-Za-z][A-Za-z0-9_]{4,31}')
CONTACT_KINDS = ('support', 'ads')


def contacts_config():
    """The Telegram accounts customers are pointed to: support, and ads or partnerships."""
    cfg, _ = read_config('contacts')
    def one(kind):
        username = str(cfg.get(kind) or '').strip()
        return {'username': username, 'url': f'https://t.me/{username}' if username else ''}
    return {kind: one(kind) for kind in CONTACT_KINDS}


def _contact_username(value):
    """@name, name or a t.me link, as the bare username; '' clears it."""
    value = str(value or '').strip()
    value = re.sub(r'^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/', '', value, flags=re.IGNORECASE)
    value = value.lstrip('@').strip('/')
    if value and not _TELEGRAM_USERNAME.fullmatch(value):
        raise DomainError('invalid_contact_username')
    return value


_BUCKET = re.compile(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]')
_STORAGE_KEY = re.compile(r'[A-Za-z0-9/+=_-]{8,128}')
OBJECT_STORAGE_DEFAULTS = {'endpoint': 'https://usc1.contabostorage.com', 'bucket': 'pdfmaster', 'region': ''}


def object_storage_config():
    """The S3-compatible bucket files are kept in (Contabo Object Storage).

    `enabled` sends new files there; reading files already there needs only the
    credentials, so switching it off never strands what is stored.
    """
    cfg, secret = read_config('object_storage')
    values = {key: cfg.get(key) or default for key, default in OBJECT_STORAGE_DEFAULTS.items()}
    configured = bool(secret.get('access_key') and secret.get('secret_key'))
    enabled = bool(cfg.get('enabled', False))
    return {**values, 'enabled': enabled, 'configured': configured, 'ready': enabled and configured,
            'access_key': secret.get('access_key', ''), 'secret_key': secret.get('secret_key', '')}


def test_object_storage():
    """Write, read back and delete a small object, so the keys are known to work."""
    from apps.core import storage
    cfg = object_storage_config()
    if not cfg['configured']: raise DomainError('object_storage_not_configured', 409)
    try: storage.check(cfg)
    except Exception: raise DomainError('object_storage_connection_failed', 409) from None
    IntegrationConfig.objects.filter(pk='object_storage').update(check_status='connected', checked_at=timezone.now())


_CARD = re.compile(r'[0-9]{16}')
CARD_LABELS = ('Uzcard', 'Humo', 'Visa', 'Mastercard')


def _luhn(number):
    """The card-number checksum, which catches nearly every mistyped digit."""
    total = 0
    for position, digit in enumerate(int(c) for c in reversed(number)):
        if position % 2:
            digit = digit * 2 - 9 if digit > 4 else digit * 2
        total += digit
    return total % 10 == 0


def manual_payment_config():
    """Card transfers the owner reviews by hand.

    Not a secret: the card is shown to every customer who starts a payment, so
    it lives in the plain configuration. `enabled` is the switch, and it starts
    on, as the owner asked; customers see the option only when it is on, a valid
    card and holder are set, and a plan has a price.
    """
    cfg, _ = read_config('manual_payments')
    number = str(cfg.get('card_number') or '')
    holder = str(cfg.get('card_holder') or '')
    configured = bool(_CARD.fullmatch(number) and _luhn(number) and holder)
    enabled = bool(cfg.get('enabled', True))
    alert = cfg.get('alert_telegram_id')
    return {'enabled': enabled, 'configured': configured, 'ready': enabled and configured,
            'card_number': number, 'card_holder': holder,
            'card_label': cfg.get('card_label', '') if cfg.get('card_label') in CARD_LABELS else '',
            'alert_telegram_id': alert if type(alert) is int and alert > 0 else None}


_PUBLIC_CHANNEL = re.compile(r'(?:https://)?(?:t\.me|telegram\.me)/([A-Za-z][A-Za-z0-9_]{3,31})/?|@([A-Za-z][A-Za-z0-9_]{3,31})')
_INVITE_LINK = re.compile(r'https://t\.me/(?:\+|joinchat/)[A-Za-z0-9_-]{8,64}')
_CHAT_ID = re.compile(r'-100[0-9]{6,15}')
MAX_CHANNELS = 5


def parse_channels(text):
    """Required channels, one per line: `@name`, `https://t.me/name`, or for a
    private channel or group its invite link and numeric chat ID together.

    The chat is what the bot asks Telegram about; the link is what customers
    tap to join. A public channel's username is both.
    """
    channels, seen = [], set()
    for number, raw in enumerate(str(text or '').splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        public = _PUBLIC_CHANNEL.fullmatch(parts[0]) if len(parts) == 1 else None
        if public:
            name = public.group(1) or public.group(2)
            if name.lower() in ('joinchat', 'share', 'addstickers', 'proxy', 'iv'):
                raise DomainError('invalid_channel', 400, {'line': number})
            chat, url = '@' + name, 'https://t.me/' + name
        else:
            invite = next((part for part in parts if _INVITE_LINK.fullmatch(part)), None)
            chat = next((part for part in parts if _CHAT_ID.fullmatch(part)), None)
            if len(parts) != 2 or not invite or not chat:
                raise DomainError('invalid_channel', 400, {'line': number})
            url = invite
        if chat.lower() in seen:
            continue
        seen.add(chat.lower())
        channels.append({'chat': chat, 'url': url})
    if len(channels) > MAX_CHANNELS:
        raise DomainError('too_many_channels', 400, {'max': MAX_CHANNELS})
    return channels


def channel_gate_config():
    """Telegram channels a free account must join before using a service."""
    cfg, _ = read_config('channels')
    channels = [c for c in cfg.get('channels') or [] if isinstance(c, dict) and c.get('chat') and c.get('url')]
    checks = cfg.get('checks') if isinstance(cfg.get('checks'), dict) else {}
    for channel in channels:
        check = checks.get(channel['chat']) or {}
        channel['title'] = str(check.get('title') or '')[:80] or channel['chat'].lstrip('@')
        channel['check'] = {'ok': check.get('ok'), 'reason': check.get('reason', ''), 'checked_at': check.get('checked_at')}
    enabled = bool(cfg.get('enabled', False))
    return {'enabled': enabled, 'channels': channels, 'ready': enabled and bool(channels)}


def test_channels():
    """Ask Telegram, for each channel, whether the bot can see who has joined.

    A channel needs the bot as an administrator; a group needs it as a member.
    The result and the channel's title are kept, so the panel can say which
    channel needs fixing and customers see the real name.
    """
    from apps.core import channel_gate
    config = channel_gate_config()
    token = telegram_config()['token']
    if not token: raise DomainError('bot_not_configured')
    if not config['channels']: raise DomainError('channels_not_configured')
    bot_id = int(token.split(':', 1)[0])
    checks, problems = {}, []
    for channel in config['channels']:
        result = channel_gate.inspect(channel['chat'], bot_id, token)
        checks[channel['chat']] = {**result, 'checked_at': timezone.now().isoformat()}
        if not result['ok']: problems.append(channel['chat'])
    row = IntegrationConfig.objects.get(pk='channels')
    row.configuration = {**row.configuration, 'checks': checks}
    row.check_status = 'connected' if not problems else 'attention'
    row.checked_at = timezone.now()
    row.save(update_fields=['configuration', 'check_status', 'checked_at'])
    if problems: raise DomainError('channels_bot_not_admin', 409, {'channels': problems})


def test_pixabay():
    """One real search, so an operator knows the key works before a customer does."""
    from apps.studio import photos
    cfg = pixabay_config()
    if not cfg['configured']: raise DomainError('pixabay_not_configured', 409)
    try: photos.search('nature', cfg['api_key'], per_page=3)
    except Exception: raise DomainError('pixabay_connection_failed', 409) from None
    IntegrationConfig.objects.filter(pk='pixabay').update(check_status='connected', checked_at=timezone.now())


def _email_connection(cfg):
    from django.core.mail import get_connection
    # Only the memory backend can replace SMTP in development; codes never go to stdout.
    backend = ('django.core.mail.backends.locmem.EmailBackend'
               if settings.DEBUG and settings.EMAIL_BACKEND == 'django.core.mail.backends.locmem.EmailBackend'
               else 'django.core.mail.backends.smtp.EmailBackend')
    return get_connection(backend, host=cfg['host'], port=cfg['port'], username=cfg['username'],
                          password=cfg['password'], use_tls=cfg['use_tls'], use_ssl=cfg['use_ssl'],
                          timeout=10, fail_silently=False)

def test_email():
    cfg = email_config()
    if not cfg['configured']: raise DomainError('email_not_configured', 409)
    connection = _email_connection(cfg)
    try:
        # Opening SMTP performs TLS negotiation and authentication without sending mail.
        connection.open()
    except Exception: raise DomainError('email_connection_failed', 409) from None
    finally:
        try: connection.close()
        except Exception: pass
    row, _ = IntegrationConfig.objects.get_or_create(key='email')
    row.checked_at = timezone.now(); row.check_status = 'connected'
    row.save(update_fields=['checked_at', 'check_status'])

def send_auth_email(recipient, code, purpose, locale='en'):
    from django.core.mail import EmailMessage
    cfg = email_config()
    if not cfg['ready']: raise DomainError('email_not_configured', 503)
    try: validate_email(recipient)
    except (ValidationError, TypeError): raise DomainError('invalid_email') from None
    if not isinstance(code, str) or not re.fullmatch(r'[A-Za-z0-9_-]{4,128}', code):
        raise DomainError('invalid_parameters')
    messages = {
        'en': ('PDF Master verification code', 'Your PDF Master verification code is: {code}\n\nUse this code only in PDF Master. If you did not request it, you can ignore this email.', 'PDF Master password reset code'),
        'uz': ('PDF Master tasdiqlash kodi', 'PDF Master tasdiqlash kodingiz: {code}\n\nKodni faqat PDF Master ilovasida kiriting. Agar so‘rov yubormagan bo‘lsangiz, xatni e’tiborsiz qoldiring.', 'PDF Master parolni tiklash kodi'),
        'ru': ('Код подтверждения PDF Master', 'Ваш код подтверждения PDF Master: {code}\n\nИспользуйте код только в PDF Master. Если вы не запрашивали код, проигнорируйте письмо.', 'Код сброса пароля PDF Master'),
    }
    subject, body, reset_subject = messages.get(locale, messages['en'])
    if purpose in ('reset_password', 'password_reset', 'reset'): subject = reset_subject
    connection = _email_connection(cfg)
    try:
        sent = EmailMessage(subject, body.format(code=code), cfg['from_email'], [recipient], connection=connection).send()
        if sent != 1: raise ValueError()
    except Exception: raise DomainError('email_delivery_failed', 503) from None
    finally:
        try: connection.close()
        except Exception: pass

@transaction.atomic
def save_config(key, values):
    cfg, secrets = read_config(key)
    if key == 'telegram':
        token = values.get('token','').strip()
        if token:
            if not re.fullmatch(r'[0-9]{5,20}:[A-Za-z0-9_-]{25,150}',token): raise DomainError('invalid_bot_token')
            secrets['token'] = token
        username = values.get('username','').strip().lstrip('@')
        if username and not re.fullmatch(r'[A-Za-z0-9_]{5,32}',username): raise DomainError('invalid_bot_username')
        url = values.get('webapp_url',settings.TELEGRAM_WEBAPP_URL).strip()
        from urllib.parse import urlparse
        try:
            parsed = urlparse(url)
            valid_host=bool(parsed.hostname) and not parsed.username and not parsed.password
            valid_port=parsed.port is None or 1<=parsed.port<=65535
        except ValueError:raise DomainError('invalid_webapp_url') from None
        if not valid_host or not valid_port or any(ord(c)<33 for c in url):raise DomainError('invalid_webapp_url')
        if parsed.scheme != 'https' and not (settings.DEBUG and parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1')): raise DomainError('invalid_webapp_url')
        cfg.update(username=username,webapp_url=url)
    elif key == 'ai':
        mode = values.get('mode','local_fixture')
        if mode not in ('local_fixture','openai','disabled') or (mode=='local_fixture' and not settings.DEBUG): raise DomainError('invalid_parameters')
        if values.get('api_key','').strip(): secrets['api_key']=values['api_key'].strip()
        model=values.get('model','').strip()
        if mode=='openai' and (not (secrets.get('api_key') or os.getenv('OPENAI_API_KEY','')) or not model): raise DomainError('provider_not_configured')
        image_model=values.get('image_model',cfg.get('image_model','')).strip()
        if image_model and not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}',image_model):raise DomainError('invalid_parameters')
        cfg.update(mode=mode,model=model[:100],image_model=image_model)
    elif key == 'google':
        client_secret = values.get('client_secret', '')
        if client_secret.strip():
            if len(client_secret) > 1024 or any(ord(c) < 33 or ord(c) == 127 for c in client_secret):
                raise DomainError('invalid_parameters')
            secrets['client_secret'] = client_secret
        current = google_config()
        cfg.update(enabled=_boolean(values.get('enabled', False)),
                   client_id=values.get('client_id', cfg.get('client_id', '')).strip(),
                   redirect_uri=values.get('redirect_uri', current['redirect_uri']).strip())
        _validate_google(cfg, secrets, current['webapp_url'])
    elif key == 'email':
        password = values.get('password', '')
        if password.strip():
            if len(password) > 1024 or any(ord(c) < 32 or ord(c) == 127 for c in password):
                raise DomainError('invalid_parameters')
            secrets['password'] = password
        raw_host = values.get('host', cfg.get('host', ''))
        if any(ord(c) < 32 or ord(c) == 127 for c in raw_host): raise DomainError('invalid_smtp_host')
        host = raw_host.strip()
        username = values.get('username', cfg.get('username', '')).strip()
        sender = values.get('from_email', cfg.get('from_email', '')).strip()
        if len(sender) > 254: raise DomainError('invalid_email_sender')
        if host and (len(host) > 253 or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', host)):
            raise DomainError('invalid_smtp_host')
        if len(username) > 254 or any(ord(c) < 32 or ord(c) == 127 for c in username):
            raise DomainError('invalid_parameters')
        if sender:
            try: validate_email(sender)
            except ValidationError: raise DomainError('invalid_email_sender') from None
        try:
            port = int(values.get('port', cfg.get('port', 587)))
            if not 1 <= port <= 65535: raise ValueError()
        except (ValueError, TypeError): raise DomainError('invalid_smtp_port') from None
        use_tls = _boolean(values.get('use_tls', cfg.get('use_tls', True)))
        use_ssl = _boolean(values.get('use_ssl', cfg.get('use_ssl', False)))
        enabled = _boolean(values.get('enabled', False))
        if use_tls and use_ssl: raise DomainError('invalid_email_security')
        if not settings.DEBUG and not (use_tls or use_ssl): raise DomainError('email_tls_required')
        if enabled and (not host or not sender or (username and not secrets.get('password'))):
            raise DomainError('email_not_configured')
        cfg.update(enabled=enabled, host=host, port=port, username=username, from_email=sender,
                   use_tls=use_tls, use_ssl=use_ssl)
    elif key == 'antibot':
        secret_key = values.get('secret_key', '')
        if not isinstance(secret_key, str): raise DomainError('invalid_antibot_secret_key')
        if secret_key.strip(): secrets['secret_key'] = secret_key.strip()
        site_key = values.get('site_key', cfg.get('site_key', ''))
        if not isinstance(site_key, str): raise DomainError('invalid_antibot_site_key')
        cfg.update(web_enabled=_boolean(values.get('web_enabled', False)),
                   bot_enabled=_boolean(values.get('bot_enabled', not settings.DEBUG)),
                   site_key=site_key.strip(),
                   allowed_hostnames=_antibot_hostnames(values.get('allowed_hostnames', cfg.get('allowed_hostnames', list(_ANTIBOT_DEFAULT_HOSTS)))))
        _validate_antibot(cfg, secrets)
    elif key == 'channels':
        channels = parse_channels(values.get('channels', ''))
        enabled = _boolean(values.get('enabled', False))
        if enabled and not channels: raise DomainError('channels_not_configured')
        # Checks are kept only for channels still on the list.
        kept = {c['chat'] for c in channels}
        checks = {chat: value for chat, value in (cfg.get('checks') or {}).items() if chat in kept}
        cfg.update(enabled=enabled, channels=channels, checks=checks)
    elif key == 'manual_payments':
        number = re.sub(r'[\s-]', '', str(values.get('card_number', '') or ''))
        if number:
            # A wrong digit here sends customers' money to a stranger's card.
            if not _CARD.fullmatch(number) or not _luhn(number): raise DomainError('invalid_card_number')
            cfg['card_number'] = number
        holder = ' '.join(str(values.get('card_holder', cfg.get('card_holder', '')) or '').split())
        if holder and (not 2 <= len(holder) <= 60 or any(c.isdigit() or c in '<>' for c in holder)):
            raise DomainError('invalid_card_holder')
        if holder: cfg['card_holder'] = holder
        label = str(values.get('card_label', cfg.get('card_label', '')) or '')
        if label and label not in CARD_LABELS: raise DomainError('invalid_parameters')
        cfg['card_label'] = label
        alert = str(values.get('alert_telegram_id', '') or '').strip()
        if alert and not re.fullmatch(r'[0-9]{1,15}', alert): raise DomainError('invalid_telegram_id')
        cfg['alert_telegram_id'] = int(alert) if alert else None
        enabled = _boolean(values.get('enabled', False))
        if enabled and not (cfg.get('card_number') and cfg.get('card_holder')):
            raise DomainError('manual_payments_not_configured')
        cfg.update(enabled=enabled)
    elif key == 'contacts':
        cfg.update({kind: _contact_username(values.get(kind, '')) for kind in CONTACT_KINDS})
    elif key == 'pixabay':
        api_key = values.get('pixabay_key', '')
        if not isinstance(api_key, str): raise DomainError('invalid_pixabay_key')
        if api_key.strip():
            if not _PIXABAY_KEY.fullmatch(api_key.strip()): raise DomainError('invalid_pixabay_key')
            secrets['api_key'] = api_key.strip()
        enabled = _boolean(values.get('enabled', False))
        if enabled and not (secrets.get('api_key') or os.getenv('PIXABAY_API_KEY', '')):
            raise DomainError('pixabay_not_configured')
        cfg.update(enabled=enabled)
    elif key == 'object_storage':
        from urllib.parse import urlparse
        endpoint = str(values.get('endpoint') or OBJECT_STORAGE_DEFAULTS['endpoint']).strip().rstrip('/')
        parsed = urlparse(endpoint)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query: raise DomainError('invalid_storage_endpoint')
        bucket = str(values.get('bucket') or OBJECT_STORAGE_DEFAULTS['bucket']).strip()
        if not _BUCKET.fullmatch(bucket): raise DomainError('invalid_storage_bucket')
        region = str(values.get('region') or '').strip()
        if region and not re.fullmatch(r'[a-z0-9-]{1,32}', region): raise DomainError('invalid_storage_region')
        for field in ('access_key', 'secret_key'):
            value = values.get(field, '')
            if not isinstance(value, str): raise DomainError('invalid_storage_key')
            if value.strip():
                if not _STORAGE_KEY.fullmatch(value.strip()): raise DomainError('invalid_storage_key')
                secrets[field] = value.strip()
        enabled = _boolean(values.get('enabled', False))
        if enabled and not (secrets.get('access_key') and secrets.get('secret_key')):
            raise DomainError('object_storage_not_configured')
        cfg.update(enabled=enabled, endpoint=endpoint, bucket=bucket, region=region)
    else: raise DomainError('invalid_parameters')
    row = IntegrationConfig.objects.update_or_create(key=key,defaults={'configuration':cfg,'encrypted_secrets':cipher().encrypt(json.dumps(secrets).encode()),'check_status':'not_checked'})[0]
    if key == 'object_storage':
        from apps.core import storage
        storage.forget_config()  # this process; the others reread within half a minute
    return row

def test_telegram():
    cfg=telegram_config()
    if not cfg['token']: raise DomainError('bot_not_configured')
    # The URL is internal to this bounded request and never returned/logged on errors.
    try:
        req=urllib.request.Request('https://api.telegram.org/bot'+cfg['token']+'/getMe',data=b'{}',headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=10) as response: data=json.loads(response.read(65536))
        if not data.get('ok') or not data.get('result',{}).get('is_bot'): raise ValueError()
    except Exception: raise DomainError('bot_connection_failed',409) from None
    username=data['result'].get('username','')
    row,_=IntegrationConfig.objects.get_or_create(key='telegram')
    row.configuration={**row.configuration,'username':username};row.checked_at=timezone.now();row.check_status='connected'
    row.save(update_fields=['configuration','checked_at','check_status'])
    return username

def _locked_runner_pid():
    import fcntl
    import shlex
    path=settings.PRIVATE_STORAGE_ROOT/'runbot.lock'
    try:
        with path.open('r') as handle:
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                raw=handle.read(30).strip()
                if not raw.isdigit():return None
                pid=int(raw)
                result=subprocess.run(['/bin/ps','-p',str(pid),'-o','args='],capture_output=True,text=True,timeout=2)
                args=shlex.split(result.stdout.strip())
                if pid>1 and result.returncode==0 and len(args)>=3 and args[1]==str(settings.BASE_DIR/'manage.py') and args[2]=='runbot':return pid
                return None
            return None
    except (OSError,ValueError,subprocess.SubprocessError):return None

def runner_status():
    with _lock:
        return 'running' if (_process is not None and _process.poll() is None) or _locked_runner_pid() else 'stopped'

def control_runner(action):
    global _process
    if not settings.DEBUG: raise DomainError('local_control_only',403)
    with _lock:
        known_pid=_locked_runner_pid()
        running=(_process is not None and _process.poll() is None) or bool(known_pid)
        if action=='stop':
            if _process is not None and _process.poll() is None:_process.terminate()
            elif known_pid:
                import signal
                try:os.kill(known_pid,signal.SIGTERM)
                except ProcessLookupError:pass
            return
        if action!='start': raise DomainError('invalid_parameters')
        if running: return
        cfg=telegram_config()
        if not cfg['token']: raise DomainError('bot_not_configured')
        if cfg['webhook_secret']: raise DomainError('webhook_polling_conflict',409)
        test_telegram()
        # Credentials are fetched by the child from encrypted DB; never passed in argv.
        _process=subprocess.Popen([sys.executable,str(settings.BASE_DIR/'manage.py'),'runbot'],cwd=settings.BASE_DIR,
                                  stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
