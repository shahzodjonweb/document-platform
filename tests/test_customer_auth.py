"""Customer identities share one account; every link requires proof of ownership."""
import base64
import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone as utc_timezone
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock

import pytest
from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from django.contrib.auth.hashers import check_password
from django.core import mail
from django.core.cache import cache
from django.test import Client
from django.utils import timezone
from google.auth import jwt
from google.auth.crypt import RSASigner

from apps.core import customer_auth as auth
from apps.core.errors import DomainError
from apps.core.identity import approve_challenge, digest, resolve_account
from apps.core.models import Account, AuthRateLimit, EmailChallenge, GoogleChallenge, UsageLedger
from apps.core.services import create_quote, execute_job, submit_job
from operations.integrations import save_config
from tests.test_platform import upload

pytestmark = pytest.mark.django_db
PASSWORD = 'Rivers!487-Cedar.Quilt'
NEW_PASSWORD = 'Volcano!902-Crystal.Moon'
EMAIL = {'enabled': 'true', 'host': 'smtp.example.com', 'port': '587', 'username': 'sender@example.com',
         'password': 'private-smtp-fixture', 'from_email': 'sender@example.com', 'use_tls': 'true', 'use_ssl': 'false'}
GOOGLE = {'enabled': 'true', 'client_id': '123456-fixture.apps.googleusercontent.com',
          'client_secret': 'private-google-fixture', 'redirect_uri': 'https://app.example.com/api/v1/auth/google/callback'}


@pytest.fixture(autouse=True)
def configured_identity_providers(settings, monkeypatch):
    settings.DEBUG = True
    settings.TELEGRAM_WEBAPP_URL = 'https://app.example.com/en/app'
    settings.TELEGRAM_BOT_USERNAME = 'PdfMasterFixtureBot'
    settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
    monkeypatch.setenv('INTEGRATION_ENCRYPTION_KEY', Fernet.generate_key().decode())
    save_config('email', EMAIL)
    save_config('google', GOOGLE)
    mail.outbox = []


def post(client, path, values, **headers):
    return client.post('/api/v1/auth/'+path, values, content_type='application/json', **headers)


def code():
    assert mail.outbox
    return re.search(r'\b(\d{8})\b', mail.outbox[-1].body).group(1)


def signup(email='owner@example.com', password=PASSWORD):
    challenge = auth.begin_email('register', email, password, 'Account owner')
    return auth.consume_email(challenge.pk, code())


def signed_in(account):
    client = Client()
    session = client.session
    session['customer_account_id'] = str(account.id)
    session['customer_auth_version'] = account.auth_version
    session.save()
    return client


def begin_google(client, intent='login', locale='en'):
    response = post(client, 'google/start', {'intent':intent, 'locale':locale})
    assert response.status_code == 200, response.content
    query = parse_qs(urlsplit(response.json()['authorization_url']).query)
    challenge = GoogleChallenge.objects.get(state_hash=digest(query['state'][0]))
    return challenge, query


def claims_for(challenge, **changes):
    return {'sub':'google-customer-123', 'email':'owner@example.com', 'email_verified':True,
            'name':'Account owner', 'nonce':challenge.nonce, 'aud':GOOGLE['client_id'],
            'azp':GOOGLE['client_id'], 'iss':'https://accounts.google.com',
            'iat':int(time.time())-5, 'exp':int(time.time())+600, **changes}


def google_callback(client, query, **parameters):
    return client.get('/api/v1/auth/google/callback', {'state':query['state'][0], 'code':'provider-code', **parameters})


def redirect_query(response):
    assert response.status_code == 302
    assert response['Location'].startswith('https://app.example.com/')
    assert 'no-store' in response['Cache-Control'].split(', ')
    assert response['Referrer-Policy'] == 'no-referrer'
    return parse_qs(urlsplit(response['Location']).query)


def test_email_signup_verification_login_preserves_customer_files_and_usage():
    client = Client()
    response = post(client, 'email/register', {'email':' Owner@Example.COM ', 'password':PASSWORD, 'display_name':'Account owner'})
    assert response.status_code == 200 and response.json()['status'] == 'verification_sent'
    assert not Account.objects.exists()
    challenge = EmailChallenge.objects.get(pk=response.json()['challenge_id'])
    assert mail.outbox[-1].to == ['owner@example.com']
    assert PASSWORD not in mail.outbox[-1].body and PASSWORD not in challenge.password_hash
    assert check_password(PASSWORD, challenge.password_hash)
    assert code() != challenge.code_hash
    response = post(client, 'email/verify', {'challenge_id':str(challenge.pk), 'code':code()})
    assert response.status_code == 200 and response.json()['authenticated']
    account = Account.objects.get()
    assert response.json()['user']['id'] == str(account.pk)
    assert account.email == 'owner@example.com' and account.email_verified_at and account.telegram_user_id is None
    assert 'password_hash' not in response.json()['user']
    challenge.refresh_from_db()
    assert challenge.consumed_at and not challenge.password_hash
    asset = upload(account)
    quote = create_quote(account, 'pdf.rotate', [str(asset.pk)], {'angle':90})
    job, _ = submit_job(account, quote.pk, 'verified-email-document-job')
    assert execute_job(job.pk).status == 'succeeded'
    before = client.get('/api/v1/usage').json()
    assert UsageLedger.objects.filter(account=account, kind='consume').exists()
    client.delete('/api/v1/auth/session')
    assert client.get('/api/v1/me').status_code == 401
    login = post(client, 'email/login', {'email':'OWNER@example.com', 'password':PASSWORD})
    assert login.status_code == 200 and login.json()['user']['id'] == str(account.pk)
    assert client.get('/api/v1/files/'+str(asset.pk)).status_code == 200
    assert client.get('/api/v1/usage').json() == before
    assert Account.objects.count() == 1


def test_email_verification_attempt_limit_persists_and_replay_is_rejected():
    challenge = auth.begin_email('register', 'owner@example.com', PASSWORD)
    correct = code()
    wrong = '00000000' if correct != '00000000' else '99999999'
    for _ in range(5):
        with pytest.raises(DomainError, match='invalid_verification_code'):
            auth.consume_email(challenge.pk, wrong)
    challenge.refresh_from_db()
    assert challenge.attempts == 5
    cache.clear()
    with pytest.raises(DomainError, match='verification_locked'):
        auth.consume_email(challenge.pk, correct)
    assert not Account.objects.exists()
    second = auth.begin_email('register', 'another@example.com', PASSWORD)
    second_code = code()
    account = auth.consume_email(second.pk, second_code)
    with pytest.raises(DomainError, match='verification_expired'):
        auth.consume_email(second.pk, second_code)
    assert Account.objects.count() == 1 and account.email == 'another@example.com'


def test_expired_email_verification_never_creates_account():
    challenge = auth.begin_email('register', 'owner@example.com', PASSWORD)
    EmailChallenge.objects.filter(pk=challenge.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
    with pytest.raises(DomainError, match='verification_expired'):
        auth.consume_email(challenge.pk, code())
    assert not Account.objects.exists()


def test_duplicate_registration_and_missing_reset_have_generic_response_and_no_mail():
    existing = signup()
    client = Client()
    mail.outbox.clear()
    duplicate = post(client, 'email/register', {'email':existing.email, 'password':PASSWORD})
    missing_reset = post(client, 'email/reset', {'email':'missing@example.com'})
    assert duplicate.status_code == missing_reset.status_code == 200
    assert set(duplicate.json()) == set(missing_reset.json()) == {'status', 'challenge_id'}
    assert duplicate.json()['status'] == missing_reset.json()['status'] == 'verification_sent'
    assert mail.outbox == []
    for response in (duplicate, missing_reset):
        challenge = EmailChallenge.objects.get(pk=response.json()['challenge_id'])
        assert not challenge.eligible
    assert Account.objects.count() == 1


def test_password_reset_revokes_every_existing_session_and_old_password():
    account = signup()
    first, second, resetter = signed_in(account), signed_in(account), Client()
    result = post(resetter, 'email/reset', {'email':account.email})
    challenge_id = result.json()['challenge_id']
    result = post(resetter, 'email/reset/confirm', {'challenge_id':challenge_id, 'code':code(), 'password':NEW_PASSWORD})
    assert result.status_code == 200 and result.json()['status'] == 'password_reset'
    assert first.get('/api/v1/me').status_code == second.get('/api/v1/me').status_code == 401
    assert not resetter.get('/api/v1/auth/session').json()['authenticated']
    assert post(first, 'email/login', {'email':account.email, 'password':PASSWORD}).status_code == 401
    response = post(first, 'email/login', {'email':account.email, 'password':NEW_PASSWORD})
    assert response.status_code == 200 and response.json()['user']['id'] == str(account.pk)
    account.refresh_from_db()
    assert account.auth_version == 1 and check_password(NEW_PASSWORD, account.password_hash)


def test_password_change_requires_current_password_and_keeps_only_current_session():
    account = signup()
    current, other = signed_in(account), signed_in(account)
    wrong = post(current, 'password', {'current_password':'wrong', 'password':NEW_PASSWORD})
    assert wrong.status_code == 401
    assert other.get('/api/v1/me').status_code == 200
    changed = post(current, 'password', {'current_password':PASSWORD, 'password':NEW_PASSWORD})
    assert changed.status_code == 200 and changed.json()['user']['id'] == str(account.pk)
    assert current.get('/api/v1/me').status_code == 200
    assert other.get('/api/v1/me').status_code == 401


def test_telegram_customer_adds_verified_email_password_on_same_account():
    account = resolve_account({'id':4444,'first_name':'Telegram customer'})
    client = signed_in(account)
    response = post(client, 'email/link', {'email':'owner@example.com', 'password':PASSWORD})
    assert response.status_code == 200
    verified = post(client, 'email/verify', {'challenge_id':response.json()['challenge_id'], 'code':code()})
    assert verified.status_code == 200 and verified.json()['user']['id'] == str(account.pk)
    assert auth.email_login('owner@example.com', PASSWORD).pk == account.pk
    assert resolve_account({'id':4444,'first_name':'Telegram customer'}).pk == account.pk
    assert Account.objects.count() == 1


def test_google_customer_adds_email_password_on_same_account():
    account = Account.objects.create(google_sub='existing-google-sub', google_email='owner@example.com',
                                     email='owner@example.com', email_verified_at=timezone.now())
    client = signed_in(account)
    response = post(client, 'email/link', {'email':account.email, 'password':PASSWORD})
    assert response.status_code == 200
    verified = post(client, 'email/verify', {'challenge_id':response.json()['challenge_id'], 'code':code()})
    assert verified.status_code == 200 and verified.json()['user']['id'] == str(account.pk)
    assert auth.email_login(account.email, PASSWORD).pk == account.pk
    account.refresh_from_db()
    assert account.google_sub == 'existing-google-sub' and Account.objects.count() == 1


def test_email_link_requires_original_account_and_unchanged_auth_version():
    owner = resolve_account({'id':4444,'first_name':'Owner'})
    other = resolve_account({'id':5555,'first_name':'Other'})
    challenge = auth.begin_email('link', 'owner@example.com', PASSWORD, account=owner)
    correct = code()
    for wrong_account in (None, other):
        with pytest.raises(DomainError, match='session_changed'):
            auth.consume_email(challenge.pk, correct, account=wrong_account)
    Account.objects.filter(pk=owner.pk).update(auth_version=1)
    with pytest.raises(DomainError, match='session_changed'):
        auth.consume_email(challenge.pk, correct, account=owner)
    owner.refresh_from_db()
    assert owner.email is None


def test_signup_verification_does_not_replace_a_different_logged_in_customer():
    challenge = auth.begin_email('register', 'owner@example.com', PASSWORD)
    other = resolve_account({'id':5555,'first_name':'Other'})
    client = signed_in(other)
    response = post(client, 'email/verify', {'challenge_id':str(challenge.pk), 'code':code()})
    assert response.status_code == 409 and response.json()['error']['code'] == 'session_changed'
    assert client.get('/api/v1/me').json()['id'] == str(other.pk)
    assert not Account.objects.filter(email='owner@example.com').exists()


@pytest.mark.parametrize('path,values', [
    ('email/register', {'email':'owner@example.com','password':PASSWORD}),
    ('email/login', {'email':'owner@example.com','password':PASSWORD}),
    ('email/verify', {'challenge_id':'unused','code':'12345678'}),
    ('email/reset', {'email':'owner@example.com'}),
    ('email/reset/confirm', {'challenge_id':'unused','code':'12345678','password':NEW_PASSWORD}),
    ('email/link', {'email':'owner@example.com','password':PASSWORD}),
    ('password', {'current_password':PASSWORD,'password':NEW_PASSWORD}),
    ('google/start', {'intent':'login'}),
])
def test_auth_mutations_require_csrf(path, values):
    client = Client(enforce_csrf_checks=True)
    assert post(client, path, values).status_code == 403
    assert not EmailChallenge.objects.exists() and not GoogleChallenge.objects.exists()


def test_signup_with_same_origin_csrf_token_succeeds_and_bad_origin_does_not():
    client = Client(enforce_csrf_checks=True)
    token = client.get('/api/v1/auth/session').json()['csrf_token']
    values = {'email':'owner@example.com','password':PASSWORD}
    assert post(client, 'email/register', values, HTTP_X_CSRFTOKEN=token, HTTP_ORIGIN='https://evil.example').status_code == 403
    response = post(client, 'email/register', values, HTTP_X_CSRFTOKEN=token)
    assert response.status_code == 200


def test_auth_rate_limit_is_persistent_and_does_not_store_raw_identifier():
    identity = 'private-customer@example.com'
    auth.auth_limit('fixture', identity, 2, 3600)
    cache.clear()
    auth.auth_limit('fixture', identity, 2, 3600)
    cache.clear()
    with pytest.raises(DomainError, match='rate_limited') as error:
        auth.auth_limit('fixture', identity, 2, 3600)
    assert error.value.status == 429
    row = AuthRateLimit.objects.get()
    assert row.count == 2 and len(row.key) == 64 and identity not in row.key


def test_google_start_uses_state_nonce_pkce_and_provider_callback_only():
    client = Client()
    challenge, query = begin_google(client, locale='ru')
    expected = base64.urlsafe_b64encode(hashlib.sha256(challenge.verifier.encode()).digest()).decode().rstrip('=')
    assert query['code_challenge'] == [expected] and query['code_challenge_method'] == ['S256']
    assert query['nonce'] == [challenge.nonce] and query['scope'] == ['openid email profile']
    assert query['redirect_uri'] == [GOOGLE['redirect_uri']]
    assert GOOGLE['client_secret'] not in str(query)
    assert query['state'][0] != challenge.state_hash
    assert client.session['google_browser'] != challenge.browser_hash


def test_google_state_bound_to_browser_and_single_use(monkeypatch):
    client = Client()
    challenge, query = begin_google(client)
    exchange = Mock(return_value=claims_for(challenge))
    monkeypatch.setattr(auth, 'verify_google_code', exchange)
    assert redirect_query(google_callback(Client(), query)) == {'auth_error':['invalid_oauth_state']}
    exchange.assert_not_called()
    challenge.refresh_from_db()
    assert challenge.consumed_at is None
    assert redirect_query(google_callback(client, query)) == {'auth_status':['success']}
    assert redirect_query(google_callback(client, query)) == {'auth_error':['invalid_oauth_state']}
    assert exchange.call_count == 1 and Account.objects.count() == 1


@pytest.mark.parametrize('outcome', ['expired','cancelled'])
def test_google_expiry_and_cancel_do_not_exchange_provider_code(monkeypatch, outcome):
    client = Client()
    challenge, query = begin_google(client, locale='uz')
    exchange = Mock(side_effect=AssertionError('Provider must not be called'))
    monkeypatch.setattr(auth, 'verify_google_code', exchange)
    if outcome == 'expired':
        GoogleChallenge.objects.filter(pk=challenge.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        response = google_callback(client, query)
        assert redirect_query(response) == {'auth_error':['invalid_oauth_state']}
    else:
        response = google_callback(client, query, error='access_denied', redirect_uri='https://evil.example')
        assert redirect_query(response) == {'auth_error':['google_cancelled']}
        assert '/uz/app?' in response['Location']
        challenge.refresh_from_db()
        assert challenge.consumed_at is not None
    exchange.assert_not_called()
    assert not Account.objects.exists()


def test_existing_email_requires_explicit_authenticated_google_link_then_both_logins_match(monkeypatch):
    owner = signup()
    client = Client()
    challenge, query = begin_google(client)
    monkeypatch.setattr(auth, 'verify_google_code', lambda _, challenge:claims_for(challenge))
    response = google_callback(client, query)
    assert redirect_query(response) == {'auth_error':['identity_already_linked']}
    owner.refresh_from_db()
    assert owner.google_sub is None
    assert post(client, 'email/login', {'email':owner.email,'password':PASSWORD}).status_code == 200
    challenge, query = begin_google(client, 'link')
    response = google_callback(client, query)
    assert redirect_query(response) == {'auth_status':['success']}
    assert '/en/app/settings?' in response['Location']
    assert client.get('/api/v1/me').json()['id'] == str(owner.pk)
    browser = Client()
    _, query = begin_google(browser)
    assert redirect_query(google_callback(browser, query)) == {'auth_status':['success']}
    assert browser.get('/api/v1/me').json()['id'] == str(owner.pk)
    assert auth.email_login(owner.email, PASSWORD).pk == owner.pk and Account.objects.count() == 1


def test_google_link_fails_when_original_account_session_changes(monkeypatch):
    owner = signup()
    client = signed_in(owner)
    challenge, query = begin_google(client, 'link')
    other = resolve_account({'id':5555,'first_name':'Other'})
    session = client.session
    session['customer_account_id'] = str(other.pk)
    session['customer_auth_version'] = other.auth_version
    session.save()
    monkeypatch.setattr(auth, 'verify_google_code', lambda _, challenge:claims_for(challenge))
    response = google_callback(client, query)
    assert redirect_query(response) == {'auth_error':['session_changed']}
    owner.refresh_from_db(); other.refresh_from_db()
    assert owner.google_sub is None and other.google_sub is None
    assert client.get('/api/v1/me').json()['id'] == str(other.pk)


@pytest.mark.parametrize('changes', [
    {'nonce':'wrong-nonce'}, {'nonce':None}, {'email_verified':False}, {'email_verified':'true'},
    {'sub':None}, {'sub':123}, {'sub':''}, {'sub':'x'*256},
    {'azp':'another-client.apps.googleusercontent.com'}, {'email':None}, {'email':'invalid'},
])
def test_google_additional_claim_validation_fails_closed_without_secret_leak(monkeypatch, changes):
    challenge, _ = begin_google(Client())
    monkeypatch.setattr(auth, 'google_request', lambda *args:json.dumps({'id_token':'private-provider-token'}).encode())
    monkeypatch.setattr(auth.id_token, 'verify_oauth2_token', lambda *args, **kwargs:claims_for(challenge, **changes))
    with pytest.raises(DomainError, match='google_login_failed') as error:
        auth.verify_google_code('private-provider-code', challenge)
    assert error.value.status == 401 and 'private' not in str(error.value)
    assert not Account.objects.exists()


@pytest.fixture(scope='module')
def local_rsa_material():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Local identity verification test')])
    now = datetime.now(utc_timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
            .not_valid_after(now+timedelta(days=1)).sign(key, hashes.SHA256()))
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return RSASigner.from_string(pem, key_id='fixture-key'), cert.public_bytes(serialization.Encoding.PEM).decode()


@pytest.mark.parametrize('mutation', ['valid','signature','audience','issuer','expired','future'])
def test_google_auth_verifies_real_rsa_signature_audience_issuer_and_time(monkeypatch, local_rsa_material, mutation):
    signer, certificate = local_rsa_material
    challenge, _ = begin_google(Client())
    claims = claims_for(challenge)
    if mutation == 'audience': claims['aud'] = 'attacker-client.apps.googleusercontent.com'
    if mutation == 'issuer': claims['iss'] = 'https://attacker.example'
    if mutation == 'expired': claims['iat'], claims['exp'] = int(time.time())-1000, int(time.time())-100
    if mutation == 'future': claims['iat'], claims['exp'] = int(time.time())+600, int(time.time())+1200
    token = jwt.encode(signer, claims).decode()
    if mutation == 'signature':
        parts = token.split('.')
        parts[2] = ('A' if parts[2][0] != 'A' else 'B')+parts[2][1:]
        token = '.'.join(parts)
    requests = []
    def exchange(url, data=None):
        requests.append((url, data))
        if url == 'https://oauth2.googleapis.com/token':
            submitted = parse_qs(data.decode())
            assert submitted['code_verifier'] == [challenge.verifier]
            assert submitted['client_secret'] == [GOOGLE['client_secret']]
            return json.dumps({'id_token':token}).encode()
        assert url == 'https://www.googleapis.com/oauth2/v1/certs'
        return json.dumps({'fixture-key':certificate}).encode()
    monkeypatch.setattr(auth, 'google_request', exchange)
    if mutation == 'valid':
        verified = auth.verify_google_code('fixture-provider-code', challenge)
        assert verified['sub'] == claims['sub'] and verified['email'] == claims['email']
    else:
        with pytest.raises(DomainError, match='google_login_failed'):
            auth.verify_google_code('fixture-provider-code', challenge)
    assert [entry[0] for entry in requests] == ['https://oauth2.googleapis.com/token','https://www.googleapis.com/oauth2/v1/certs']


def test_email_google_and_telegram_share_one_uuid_documents_and_usage(monkeypatch):
    owner = signup()
    asset = upload(owner)
    quote = create_quote(owner, 'pdf.rotate', [str(asset.pk)], {'angle':90})
    job, _ = submit_job(owner, quote.pk, 'three-identities-document')
    assert execute_job(job.pk).status == 'succeeded'
    client = signed_in(owner)
    original_usage = client.get('/api/v1/usage').json()
    challenge, query = begin_google(client, 'link')
    monkeypatch.setattr(auth, 'verify_google_code', lambda _, challenge:claims_for(challenge))
    assert redirect_query(google_callback(client, query)) == {'auth_status':['success']}
    response = post(client, 'browser/challenges', {'intent':'link'})
    assert response.status_code == 201, response.content
    values = response.json()
    token = parse_qs(urlsplit(values['telegram_url']).query)['start'][0][6:]
    approve_challenge(token, {'id':4444,'first_name':'Telegram owner'})
    response = post(client, 'browser/challenges/'+values['id']+'/exchange', {})
    assert response.status_code == 200 and response.json()['user']['id'] == str(owner.pk)
    assert auth.email_login(owner.email, PASSWORD).pk == owner.pk
    assert resolve_account({'id':4444,'first_name':'Telegram owner'}).pk == owner.pk
    google_browser = Client()
    _, query = begin_google(google_browser)
    assert redirect_query(google_callback(google_browser, query)) == {'auth_status':['success']}
    assert google_browser.get('/api/v1/me').json()['id'] == str(owner.pk)
    assert google_browser.get('/api/v1/files/'+str(asset.pk)).status_code == 200
    assert google_browser.get('/api/v1/usage').json() == original_usage
    assert Account.objects.count() == 1
