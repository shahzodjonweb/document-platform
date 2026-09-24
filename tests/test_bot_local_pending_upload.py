"""Local onboarding keeps bounded private uploads across separate HTTP calls."""
import asyncio
import io
import os
import stat
import time

import pytest
from aiogram.methods import GetFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from pypdf import PdfWriter

from apps.core.errors import DomainError
from apps.core.identity import resolve_account
from apps.core.models import BotConversation, BotDraft, FileAsset, Job
from telegram.local import (
    LocalTelegramSession, PENDING_UPLOAD_TTL, _pending_directory, dispatch_local,
)

from telegram.ux_copy import UX

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def customer(settings):
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    return resolve_account({'id': 996001, 'first_name': 'Local upload'}, is_test=True)


def pdf(name='before-language.pdf'):
    payload = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=400)
    writer.write(payload)
    return SimpleUploadedFile(name, payload.getvalue(), content_type='application/pdf')


def language_token(result, locale='en'):
    for message in reversed(result['messages']):
        for row in message['buttons']:
            for button in row:
                token = button.get('callback_data') or ''
                if token.startswith('lang:') and token.endswith(':' + locale):
                    return token
    raise AssertionError('Missing language picker')


def file_id_for(customer):
    return BotConversation.objects.get(pk=customer.telegram_user_id).pending['uploads'][0]['document']['file_id']


def test_first_upload_resumes_once_in_a_new_local_session(customer, monkeypatch):
    # No external provider or real Telegram connection is involved.
    from apps.commerce.providers import TelegramStarsProvider
    monkeypatch.setattr(TelegramStarsProvider, 'call', lambda *args, **kwargs: pytest.fail('Live Telegram called'))
    result = dispatch_local(customer, uploaded=pdf())
    token = language_token(result)
    identifier = file_id_for(customer)
    path = _pending_directory(customer) / identifier
    assert path.exists() and stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert FileAsset.objects.filter(account=customer).count() == 0
    dispatch_local(customer, callback_data=token)
    assets = FileAsset.objects.filter(account=customer)
    assert assets.count() == 1
    assert BotDraft.objects.get(account=customer).input_ids == [str(assets.get().pk)]
    assert not path.exists()
    dispatch_local(customer, callback_data=token)
    assert FileAsset.objects.filter(account=customer).count() == 1


def test_two_files_before_language_both_survive_separate_dispatches(customer):
    first = dispatch_local(customer, uploaded=pdf('first.pdf'))
    dispatch_local(customer, uploaded=pdf('second.pdf'))
    assert len(BotConversation.objects.get(pk=customer.telegram_user_id).pending['uploads']) == 2
    assert len(list(_pending_directory(customer).iterdir())) == 2
    dispatch_local(customer, callback_data=language_token(first))
    assert FileAsset.objects.filter(account=customer).count() == 2
    assert len(BotDraft.objects.get(account=customer).input_ids) == 2
    assert list(_pending_directory(customer).iterdir()) == []


def test_staged_files_reject_other_accounts_and_path_traversal(customer):
    dispatch_local(customer, uploaded=pdf())
    identifier = file_id_for(customer)
    other = resolve_account({'id': 996002, 'first_name': 'Other local user'}, is_test=True)

    async def request(account, file_id):
        return await LocalTelegramSession(account).make_request(None, GetFile(file_id=file_id))

    for account, file_id in ((other, identifier), (customer, '../' + identifier)):
        with pytest.raises(DomainError, match='file_unavailable'):
            asyncio.run(request(account, file_id))
    assert (_pending_directory(customer) / identifier).exists()


def test_expired_staged_bytes_are_unreadable_and_removed(customer):
    dispatch_local(customer, uploaded=pdf())
    identifier = file_id_for(customer)
    path = _pending_directory(customer) / identifier
    expired = time.time() - PENDING_UPLOAD_TTL - 1
    os.utime(path, (expired, expired))

    async def read():
        return [chunk async for chunk in LocalTelegramSession(customer).stream_content('https://local/' + identifier)]

    with pytest.raises(DomainError, match='file_unavailable'):
        asyncio.run(read())
    assert not path.exists()


def test_cancel_removes_staged_uploads_before_language_selection(customer):
    dispatch_local(customer, uploaded=pdf())
    path = _pending_directory(customer) / file_id_for(customer)
    dispatch_local(customer, text='/cancel')
    assert not path.exists()
    assert not BotConversation.objects.get(pk=customer.telegram_user_id).pending.get('uploads')


def test_pending_uploads_are_bounded_and_reported_size_cannot_bypass_limit(customer):
    for index in range(11):
        dispatch_local(customer, uploaded=pdf(f'{index}.pdf'))
    pending = BotConversation.objects.get(pk=customer.telegram_user_id).pending
    assert len(pending['uploads']) == 10
    assert len(list(_pending_directory(customer).iterdir())) == 10
    assert FileAsset.objects.filter(account=customer).count() == 0
    oversized = SimpleUploadedFile('oversized.pdf', b'x' * (20 * 1024 * 1024 + 1))
    oversized.size = 1  # The content length, not caller metadata, is authoritative.
    with pytest.raises(DomainError, match='bot_transport_limit'):
        dispatch_local(customer, uploaded=oversized)
    assert len(list(_pending_directory(customer).iterdir())) == 10


@pytest.mark.parametrize('locale', ('en', 'uz', 'ru'))
def test_missing_staged_upload_recovers_after_language_choice_without_http_error(customer, locale):
    result = dispatch_local(customer, uploaded=pdf())
    token = language_token(result, locale)
    (_pending_directory(customer) / file_id_for(customer)).unlink()
    client = Client()
    session = client.session
    session['customer_account_id'] = str(customer.pk)
    session.save()
    response = client.post('/api/v1/telegram/local/messages', {'callback_data': token}, content_type='application/json')
    assert response.status_code == 200, response.content
    outbound = [message for message in response.json()['messages'] if message['direction'] == 'outbound']
    assert any(UX[locale]['download_error'] in message['text'] for message in outbound)
    assert not FileAsset.objects.filter(account=customer).exists()
    assert not Job.objects.filter(account=customer).exists()
    conversation = BotConversation.objects.get(pk=customer.telegram_user_id)
    assert conversation.locale == locale and not conversation.pending.get('uploads')
