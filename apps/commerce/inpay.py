"""inPAY (inpay.uz): the payment page a customer is sent to, and what inPAY says happened.

inPAY has two APIs, and which one is spoken follows from the credentials the
owner saved (operations.integrations.inpay_config):

- v2, with a secret key (`sk_live_…`, or `sk_test_…` for its simulator):
  payments are opened with an Idempotency-Key and webhooks are signed.
- v1, the classic one, with a merchant id and token: a bearer token is fetched
  once a day, and its webhooks carry no signature.

Nothing here decides anything or touches the database. `open_payment` opens a
payment and returns its page, `fetch` asks inPAY where a payment stands, and
`signature_ok` checks a webhook. What a payment means for a plan is decided in
apps/commerce/checkout.py, and only ever from `fetch`: a webhook says a payment
moved, inPAY's own answer says where to.
"""
import hashlib
import hmac
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = 'https://inpay.uz'
TIMEOUT = 8
# A webhook older than this is not acted on (inPAY's own rule for its signature).
SIGNATURE_AGE = 300
BEARER_SECONDS = 23 * 3600
# v1 takes 100 requests an hour from one address, for everything. We stop short
# of that, and checks on a payment's status stop sooner still, so a customer
# can always open a payment within the hour.
V1_HOURLY = 90
V1_STATUS_HOURLY = 65
_ID = re.compile(r'[A-Za-z0-9_-]{6,64}')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is an answer, not somewhere to go: the key in the request's header never leaves inpay.uz."""

    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


class Unavailable(Exception):
    """inPAY did not answer, or answered with something that may pass: worth asking again.

    `reason` is 'rate_limited' when inPAY's request limit (or our own share of
    it) is spent: that too passes, within the hour, but the owner should know.
    """

    def __init__(self, reason='unavailable'):
        self.reason = reason
        super().__init__(reason)


class Refused(Exception):
    """inPAY understood and said no. `code` is inPAY's own word for why."""

    def __init__(self, code, status=400):
        self.code, self.status = str(code or 'refused')[:64], status
        super().__init__(self.code)


def _call(method, path, *, headers=None, body=None, query=None):
    """One request to inPAY: (HTTP status, parsed JSON). Network trouble is Unavailable."""
    url = BASE + path + ('?' + urllib.parse.urlencode(query) if query else '')
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={
        'Accept': 'application/json', **({'Content-Type': 'application/json'} if data is not None else {}),
        **(headers or {})})
    try:
        with _opener.open(request, timeout=TIMEOUT) as response:
            status, raw = response.status, response.read(262144)
    except urllib.error.HTTPError as error:
        status = error.code
        try:
            raw = error.read(262144)
        except Exception:
            raise Unavailable() from None
    except Exception:
        raise Unavailable() from None
    try:
        parsed = json.loads(raw or b'{}')
    except ValueError:
        parsed = None
    if not isinstance(parsed, dict):
        # A gateway page instead of JSON: inPAY is not itself right now.
        raise Unavailable()
    return status, parsed


def _answer(status, parsed):
    """The body of an answer that succeeded; otherwise Refused or Unavailable."""
    if 200 <= status < 300 and parsed.get('success') is not False:
        return parsed
    error = parsed.get('error') if isinstance(parsed.get('error'), dict) else {}
    code = error.get('code') or parsed.get('error_code') or f'http_{status}'
    # Too many requests and inPAY's own faults pass by themselves.
    if status == 429 or code in ('RATE_LIMIT_EXCEEDED', 'rate_limited', 'rate_limit_exceeded'):
        raise Unavailable('rate_limited')
    if status >= 500 or code == 'TRANSACTION_SAVE_FAILED':
        raise Unavailable()
    raise Refused(code, status)


def _secure_page(url):
    """inPAY's own https page, or nothing: this address is handed to a customer to pay on."""
    try:
        parts = urllib.parse.urlsplit(str(url or ''))
    except ValueError:
        return ''
    host = (parts.hostname or '').lower()
    if parts.scheme != 'https' or parts.username or not (host == 'inpay.uz' or host.endswith('.inpay.uz')):
        return ''
    return str(url)


def _whole(amount):
    """An amount of so'm as inPAY writes it (15000, 15000.0 or "15000.00") as a whole number, or None."""
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return None
    return int(value) if value >= 0 and value == int(value) else None


# ---- v1: merchant id and token, a bearer token a day -----------------------------------------

def _spend(kind):
    """Count one v1 request against the last hour, or refuse it when this kind's share is spent.

    Counted in ten-minute buckets and summed over the last seven, so no stretch
    of sixty minutes, wherever it starts, holds more than the share. Kept where
    every process counts, so the API, the bot and the cleanup share one budget.
    With that store away nothing is refused: inPAY's own limit still answers,
    and is reported.
    """
    from django.core.cache import caches
    cache, bucket = caches['limits'], int(time.time()) // 600
    keys = [f'inpay:v1:calls:{bucket - back}' for back in range(7)]
    try:
        used = sum(value or 0 for value in cache.get_many(keys).values())
    except Exception:
        return
    if used >= (V1_HOURLY if kind == 'open' else V1_STATUS_HOURLY):
        raise Unavailable('rate_limited')
    try:
        if not cache.add(keys[0], 1, 4500):
            cache.incr(keys[0])
    except Exception:
        pass


def _bearer_key(cfg):
    digest = hashlib.sha256(f"{cfg['merchant_id']}:{cfg['merchant_token']}".encode()).hexdigest()[:24]
    return f'inpay:bearer:{digest}'


def _bearer(cfg, fresh=False):
    """The day's bearer token, kept where every process finds it: fetching one counts against inPAY's hourly limit."""
    from django.core.cache import caches
    cache, key = caches['limits'], _bearer_key(cfg)
    try:
        token = None if fresh else cache.get(key)
    except Exception:
        token = None
    if token:
        return token
    _spend('open')
    parsed = _answer(*_call('GET', '/api/v1/authorization/', query={
        'merchant_id': cfg['merchant_id'], 'merchant_token': cfg['merchant_token']}))
    token = parsed.get('bearer_token')
    if not isinstance(token, str) or not token:
        raise Unavailable()
    try:
        cache.set(key, token, BEARER_SECONDS)
    except Exception:
        pass
    return token


def _v1(cfg, method, path, kind, **request):
    """A v1 call with the bearer token; a token inPAY no longer takes is fetched again, once."""
    for fresh in (False, True):
        headers = {'Authorization': 'Bearer ' + _bearer(cfg, fresh)}
        _spend(kind)
        try:
            return _answer(*_call(method, path, headers=headers, **request))
        except Refused as refused:
            if refused.code != 'INVALID_TOKEN' or fresh:
                raise
    raise Unavailable()


# ---- what the rest of the code calls ---------------------------------------------------------

def open_payment(cfg, *, reference, amount, description, return_url='', webhook_url=''):
    """Open a payment of `amount` so'm; returns {'id', 'url', 'live'}.

    `reference` is our own id for it. v2 takes it as the Idempotency-Key, so a
    request repeated after a lost answer opens nothing twice, and carries it
    back in every answer about the payment. An address left empty is not sent:
    inPAY then uses the one saved on the kassa, or its own page.
    """
    addresses = {'return_url': return_url} if return_url else {}
    if cfg['api'] == 'v2':
        parsed = _answer(*_call('POST', '/api/v2/payments/', headers={
            'Authorization': 'Bearer ' + cfg['secret_key'], 'Idempotency-Key': reference}, body={
            'amount': amount, 'currency': 'UZS', 'description': description, **addresses,
            **({'webhook_url': webhook_url} if webhook_url else {}), 'metadata': {'checkout': reference}}))
        data = parsed.get('data') if isinstance(parsed.get('data'), dict) else {}
        identifier, url, live = data.get('id'), data.get('checkout_url'), data.get('livemode') is not False
    elif cfg['api'] == 'v1':
        parsed = _v1(cfg, 'POST', '/api/v1/create/', 'open', body={
            'merchant_id': str(cfg['merchant_id']), 'token': cfg['merchant_token'], 'amount': amount,
            'description': description, **addresses, **({'callback_url': webhook_url} if webhook_url else {})})
        identifier, url, live = parsed.get('order_id'), parsed.get('pay_url'), True
    else:
        raise Refused('not_configured')
    url = _secure_page(url)
    if not isinstance(identifier, str) or not _ID.fullmatch(identifier) or not url:
        raise Unavailable()
    return {'id': identifier, 'url': url, 'live': live}


_V2_STATES = {'succeeded': 'paid', 'failed': 'failed', 'canceled': 'cancelled'}
_V1_STATES = {'success': 'paid', 'failed': 'failed', 'cancelled': 'cancelled'}


def fetch(cfg, api, identifier):
    """Where inPAY says a payment stands.

    {'state': 'pending' | 'paid' | 'failed' | 'cancelled', 'amount': so'm or None,
     'currency', 'live', 'reference': our id when inPAY carries it, 'receipt': fiscal receipt link}
    """
    if not _ID.fullmatch(str(identifier or '')):
        raise Refused('invalid_id')
    if api == 'v2' and cfg.get('secret_key'):
        parsed = _answer(*_call('GET', f'/api/v2/payments/{identifier}', headers={
            'Authorization': 'Bearer ' + cfg['secret_key']}))
        data = parsed.get('data') if isinstance(parsed.get('data'), dict) else {}
        metadata = data.get('metadata') if isinstance(data.get('metadata'), dict) else {}
        if data.get('id') != identifier:
            raise Unavailable()
        return {'state': _V2_STATES.get(data.get('status'), 'pending'), 'amount': _whole(data.get('amount')),
                'currency': str(data.get('currency') or 'UZS').upper(), 'live': data.get('livemode') is not False,
                'reference': str(metadata.get('checkout') or '') or None, 'receipt': _receipt(data.get('fiscal_url'))}
    if api == 'v1' and cfg.get('merchant_id') and cfg.get('merchant_token'):
        parsed = _v1(cfg, 'GET', '/api/v1/transactions/', 'status', query={'order_id': identifier})
        if parsed.get('order_id') != identifier:
            raise Unavailable()
        return {'state': _V1_STATES.get(parsed.get('status'), 'pending'), 'amount': _whole(parsed.get('amount')),
                'currency': 'UZS', 'live': True, 'reference': None, 'receipt': ''}
    # The credentials this payment was opened with are gone: nobody can be asked.
    raise Refused('not_configured')


def _receipt(url):
    """A fiscal receipt link on the tax committee's own site, or ''."""
    try:
        parts = urllib.parse.urlsplit(str(url or ''))
    except ValueError:
        return ''
    host = (parts.hostname or '').lower()
    return str(url) if parts.scheme == 'https' and (host == 'soliq.uz' or host.endswith('.soliq.uz')) else ''


def signature_state(secret, header, raw, now=None):
    """How a v2 webhook is signed: `t=<unix>,v1=<hex>` over "<t>.<raw body>".

    'valid': by inPAY, lately. 'stale': by inPAY, but long ago, which a retry
    sent with its first timestamp would be as well as a replay; either way the
    payment is only looked up, so it is listened to like an unsigned webhook.
    'invalid': not by inPAY.
    """
    parts = dict(part.strip().split('=', 1) for part in str(header or '').split(',') if '=' in part)
    stamp, given = parts.get('t', ''), parts.get('v1', '').strip().lower()
    if not secret or not stamp.isascii() or not stamp.isdigit() or not given:
        return 'invalid'
    expected = hmac.new(secret.encode(), stamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
    try:
        if not hmac.compare_digest(expected.encode(), given.encode()):
            return 'invalid'
    except (TypeError, ValueError, UnicodeError):
        return 'invalid'
    return 'valid' if abs((now if now is not None else time.time()) - int(stamp)) <= SIGNATURE_AGE else 'stale'


def signature_ok(secret, header, raw, now=None):
    """Whether a v2 webhook was signed by inPAY, lately."""
    return signature_state(secret, header, raw, now) == 'valid'


def webhook_claim(payload):
    """What a webhook says happened: 'paid', 'failed', or None. Only ever a reason to ask inPAY."""
    if not isinstance(payload, dict):
        return None
    if payload.get('object') == 'event':
        kind = str(payload.get('type') or '')
        return 'paid' if kind == 'payment.succeeded' else 'failed' if kind in ('payment.failed', 'payment.canceled') else None
    status = payload.get('status')
    return 'paid' if status == 'success' else 'failed' if status in ('failed', 'cancelled') else None


def webhook_payment(payload):
    """The id of the payment a webhook is about, in either API's shape; None when it is about something else."""
    if not isinstance(payload, dict):
        return None
    if payload.get('object') == 'event':
        if not str(payload.get('type') or '').startswith('payment.'):
            return None
        data = payload.get('data') if isinstance(payload.get('data'), dict) else {}
        subject = data.get('object') if isinstance(data.get('object'), dict) else {}
        identifier = subject.get('id')
    else:
        identifier = payload.get('order_id')
    return identifier if isinstance(identifier, str) and _ID.fullmatch(identifier) else None


def check(cfg):
    """One harmless call that proves the saved credentials work: {'live': bool}."""
    if cfg['api'] == 'v2':
        parsed = _answer(*_call('GET', '/api/v2/balance/', headers={'Authorization': 'Bearer ' + cfg['secret_key']}))
        data = parsed.get('data') if isinstance(parsed.get('data'), dict) else {}
        return {'live': data.get('livemode') is not False}
    if cfg['api'] == 'v1':
        _bearer(cfg, fresh=True)
        return {'live': True}
    raise Refused('not_configured')


def webhook_secret(cfg):
    """The secret inPAY signs this kassa's webhooks with. inPAY gives it to a live v2 key only."""
    parsed = _answer(*_call('GET', '/api/v2/webhooks/secret/', headers={'Authorization': 'Bearer ' + cfg['secret_key']}))
    data = parsed.get('data') if isinstance(parsed.get('data'), dict) else {}
    secret = data.get('secret')
    return secret if isinstance(secret, str) and secret.startswith('whsec_') else ''
