"""What remains of the PDF Master -> DocMaster rename in the app: the new cookie names, and the
PDFMASTER_ fallback in processors/env.py (remove it and its test once no deployment sets one).
The old-cookie carry-over and the old workflow salt were removed on 2026-11-12.
"""
from datetime import timedelta

import pytest
from django.conf import settings
from django.core import signing

from apps.studio import workflows
from processors.env import env


def test_the_cookies_have_the_new_names_and_old_ones_are_not_read():
    from apps.core.middleware import CHALLENGE_COOKIE
    assert settings.SESSION_COOKIE_NAME == 'docmaster_session' and CHALLENGE_COOKIE == 'docmaster_challenge'
    assert not any('Legacy' in name for name in settings.MIDDLEWARE)


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


def test_a_workflow_confirmation_needs_the_docmaster_salt():
    payload = {'workflow_id': 'fixture'}
    assert workflows._confirmation(signing.dumps(payload, salt=workflows.SALT, compress=True)) == payload
    for salt in ('pdfmaster.workflow.confirmation.v1', 'another.salt'):
        with pytest.raises(signing.BadSignature):
            workflows._confirmation(signing.dumps(payload, salt=salt))


def test_an_expired_confirmation_stays_expired(monkeypatch):
    token = signing.dumps({'workflow_id': 'fixture'}, salt=workflows.SALT)
    monkeypatch.setattr(signing.time, 'time', lambda real=signing.time.time: real() + timedelta(minutes=11).total_seconds())
    with pytest.raises(signing.SignatureExpired):
        workflows._confirmation(token)
