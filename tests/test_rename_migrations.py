"""The PDF Master -> DocMaster rename moves app-level names without signing anyone out.

Remove with the migrations they cover: apps.core.middleware.LegacyCookieMiddleware
(two weeks after the rename shipped), the legacy workflow salt (ten minutes after)
and the PDFMASTER_ fallback in processors/env.py (once no deployment sets one).
"""
from datetime import timedelta
from importlib import import_module
from urllib.parse import parse_qs, urlsplit

import pytest
from django.conf import settings
from django.core import signing
from django.test import Client

from apps.core.identity import approve_challenge, resolve_account
from apps.studio import workflows
from processors.env import env

pytestmark = pytest.mark.django_db
OLD, NEW = 'pdfmaster_session', 'docmaster_session'


def session_of(account):
    store = import_module(settings.SESSION_ENGINE).SessionStore()
    store['customer_account_id'] = str(account.id)
    store['customer_auth_version'] = account.auth_version
    store.save()
    return store.session_key


def customer(number):
    return resolve_account({'id': number, 'first_name': 'Rename fixture'}, is_test=True)


def deleted(response, name):
    return name in response.cookies and response.cookies[name].value == '' and response.cookies[name]['max-age'] == 0


def test_the_session_cookie_has_the_new_name():
    assert settings.SESSION_COOKIE_NAME == NEW
    assert 'apps.core.middleware.LegacyCookieMiddleware' in settings.MIDDLEWARE
    assert settings.MIDDLEWARE.index('apps.core.middleware.LegacyCookieMiddleware') < \
        settings.MIDDLEWARE.index('django.contrib.sessions.middleware.SessionMiddleware')


def test_an_old_session_cookie_stays_signed_in_and_moves_to_the_new_name():
    account = customer(91001)
    key = session_of(account)
    client = Client()
    client.cookies[OLD] = key
    response = client.get('/api/v1/me')
    assert response.status_code == 200 and response.json()['id'] == str(account.id)
    moved = response.cookies[NEW]
    assert moved.value == key and moved['max-age'] == settings.SESSION_COOKIE_AGE
    assert moved['path'] == settings.SESSION_COOKIE_PATH and moved['httponly'] and moved['samesite'] == 'Lax'
    assert bool(moved['secure']) == settings.SESSION_COOKIE_SECURE
    assert deleted(response, OLD) and response.cookies[OLD]['path'] == settings.SESSION_COOKIE_PATH
    # The browser now sends only the new cookie, and nothing more is set.
    client = Client()
    client.cookies[NEW] = key
    again = client.get('/api/v1/me')
    assert again.json()['id'] == str(account.id)
    assert NEW not in again.cookies and OLD not in again.cookies


def test_a_request_with_the_new_cookie_is_untouched():
    account = customer(91002)
    client = Client()
    client.cookies[NEW] = session_of(account)
    response = client.get('/api/v1/me')
    assert response.status_code == 200 and response.json()['id'] == str(account.id)
    assert NEW not in response.cookies and OLD not in response.cookies


def test_with_both_cookies_the_new_one_wins_and_the_old_one_goes():
    new_owner, old_owner = customer(91003), customer(91004)
    key = session_of(new_owner)
    client = Client()
    client.cookies[NEW] = key
    client.cookies[OLD] = session_of(old_owner)
    response = client.get('/api/v1/me')
    assert response.json()['id'] == str(new_owner.id)
    assert NEW not in response.cookies and deleted(response, OLD)


def test_an_old_cookie_for_a_session_that_is_gone_is_cleared_under_both_names():
    client = Client()
    client.cookies[OLD] = 'no-such-session-key-000000000000'
    response = client.get('/api/v1/me')
    assert response.status_code == 401
    assert deleted(response, NEW) and deleted(response, OLD)


def test_signing_out_with_an_old_cookie_keeps_the_views_cookie():
    account = customer(91005)
    key = session_of(account)
    client = Client()
    client.cookies[OLD] = key
    response = client.delete('/api/v1/auth/session')
    assert response.status_code == 200 and response.json()['authenticated'] is False
    assert response.cookies[NEW].value not in ('', key)
    assert deleted(response, OLD)


def test_a_browser_sign_in_started_under_the_old_challenge_cookie_still_finishes(settings):
    settings.DEBUG = True
    settings.TELEGRAM_BOT_USERNAME = 'DocMasterFixtureBot'
    client = Client()
    response = client.post('/api/v1/auth/browser/challenges', {}, content_type='application/json')
    assert response.status_code == 201, response.content
    values = response.json()
    issued = response.cookies['docmaster_challenge']
    assert issued['path'] == '/api/v1/auth/browser/' and issued['max-age'] == 300 and issued['httponly']
    # As if the challenge had been issued before the rename.
    del client.cookies['docmaster_challenge']
    client.cookies['pdfmaster_challenge'] = issued.value
    client.cookies['pdfmaster_challenge']['path'] = '/api/v1/auth/browser/'
    token = parse_qs(urlsplit(values['telegram_url']).query)['start'][0][6:]
    approve_challenge(token, {'id': 91006, 'first_name': 'Telegram fixture'})
    status = client.get('/api/v1/auth/browser/challenges/' + values['id'])
    assert status.status_code == 200 and status.json()['status'] == 'approved'
    assert status.cookies['docmaster_challenge'].value == issued.value and deleted(status, 'pdfmaster_challenge')
    del client.cookies['docmaster_challenge']
    client.cookies['pdfmaster_challenge'] = issued.value
    client.cookies['pdfmaster_challenge']['path'] = '/api/v1/auth/browser/'
    exchange = client.post('/api/v1/auth/browser/challenges/' + values['id'] + '/exchange', {}, content_type='application/json')
    assert exchange.status_code == 200 and exchange.json()['authenticated'] is True
    # The view's own deletion stands, and the old cookie goes too.
    assert deleted(exchange, 'docmaster_challenge') and deleted(exchange, 'pdfmaster_challenge')
    assert exchange.cookies[NEW].value


@pytest.mark.parametrize('values, expected', [
    ({'DOCMASTER_SOFFICE_BIN': '/new', 'PDFMASTER_SOFFICE_BIN': '/old'}, '/new'),
    ({'PDFMASTER_SOFFICE_BIN': '/old'}, '/old'),
    ({'DOCMASTER_SOFFICE_BIN': '', 'PDFMASTER_SOFFICE_BIN': '/old'}, '/old'),
    ({}, 'fallback'),
])
def test_settings_read_the_new_name_first_then_the_old_one(monkeypatch, values, expected):
    for name in ('DOCMASTER_SOFFICE_BIN', 'PDFMASTER_SOFFICE_BIN'):
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    assert env('SOFFICE_BIN', 'fallback') == expected


def test_a_workflow_confirmation_signed_before_the_rename_is_still_accepted():
    payload = {'workflow_id': 'fixture'}
    assert workflows._confirmation(signing.dumps(payload, salt=workflows.SALT, compress=True)) == payload
    assert workflows._confirmation(signing.dumps(payload, salt=workflows.LEGACY_SALT, compress=True)) == payload
    with pytest.raises(signing.BadSignature):
        workflows._confirmation(signing.dumps(payload, salt='another.salt'))


def test_an_expired_confirmation_stays_expired(monkeypatch):
    token = signing.dumps({'workflow_id': 'fixture'}, salt=workflows.SALT)
    monkeypatch.setattr(signing.time, 'time', lambda real=signing.time.time: real() + timedelta(minutes=11).total_seconds())
    with pytest.raises(signing.SignatureExpired):
        workflows._confirmation(token)
