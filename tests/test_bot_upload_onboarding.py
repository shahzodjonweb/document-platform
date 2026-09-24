"""Language-first uploads retain handles, without downloading or creating users."""
import asyncio
import json
from datetime import timedelta

import pytest
from aiogram.methods import SendMessage
from aiogram.types import Document, PhotoSize, Update
from django.utils import timezone

from apps.core.models import Account, AuthChallenge, BotConversation
from tests.test_bot_onboarding import GateHarness, challenge


pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]


def document(number=1, **kwargs):
    return Document(file_id=f'file-{number}', file_unique_id=f'unique-{number}',
                    file_name=f'{number}.pdf', file_size=123, **kwargs)


def test_first_document_is_retained_without_caption_or_downloading_before_language():
    h = GateHarness()
    message = h.message(document=document(), caption='private password and login_token')
    pending = BotConversation.objects.get(pk=42).pending
    saved_date = pending['uploads'][0]['date']
    # aiogram's JSON round-trip normalizes Telegram dates to whole seconds.
    assert abs(saved_date - message.date.timestamp()) <= 1
    assert pending == {'uploads': [{
        'user_id': 42, 'chat_id': 42, 'message_id': message.message_id,
        'date': saved_date,
        'document': {'file_id': 'file-1', 'file_unique_id': 'unique-1',
                     'file_name': '1.pdf', 'file_size': 123},
    }]}
    assert 'private password' not in json.dumps(pending)
    assert not Account.objects.exists() and not h.handled
    h.click(h.language('uz'))
    assert h.ready[0][3] == pending
    assert BotConversation.objects.get(pk=42).pending == {}
    assert not Account.objects.exists()


def test_album_keeps_one_usable_language_picker_and_only_largest_photo_handles():
    h = GateHarness()
    h.message(document=document())
    original_button = h.language('ru')
    original_expiry = BotConversation.objects.get(pk=42).language_expires_at
    h.message(photo=[
        PhotoSize(file_id='small', file_unique_id='small-unique', width=40, height=50),
        PhotoSize(file_id='large', file_unique_id='large-unique', width=400, height=500, file_size=456),
    ], caption='never store this caption')
    conversation = BotConversation.objects.get(pk=42)
    assert conversation.language_expires_at == original_expiry
    assert len([call for call in h.session.calls if isinstance(call, SendMessage)]) == 1
    assert conversation.pending['uploads'][1]['photo'] == [{
        'file_id': 'large', 'file_unique_id': 'large-unique',
        'width': 400, 'height': 500, 'file_size': 456,
    }]
    assert 'small' not in json.dumps(conversation.pending)
    h.click(original_button)
    assert len(h.ready[0][3]['uploads']) == 2
    assert h.ready[0][2] == 'ru'


def test_pending_handles_are_deduplicated_and_capped_at_ten_files():
    h = GateHarness()
    first = h.message(document=document(0))
    original_button = h.language('en')
    asyncio.run(h.dispatcher.feed_update(h.bot, Update(update_id=888, message=first)))
    for number in range(1, 12):
        h.message(document=document(number))
    pending = BotConversation.objects.get(pk=42).pending
    assert len(pending['uploads']) == 10
    assert [item['document']['file_id'] for item in pending['uploads']] == [f'file-{i}' for i in range(10)]
    assert pending['resend_file'] is True
    h.click(original_button)
    assert h.ready[0][3] == pending
    assert not Account.objects.exists() and not h.handled


@pytest.mark.parametrize('intent', ['login', 'link'])
def test_authentication_priority_does_not_keep_or_replay_accidental_uploads(intent):
    c = challenge('private-auth-token', intent=intent)
    h = GateHarness()
    h.message(text='/start login_private-auth-token')
    first_button = h.language('en')
    h.message(document=document())
    h.click(first_button)
    pending = h.ready[0][3]
    assert pending == {'challenge_id': str(c.pk), 'resend_file': True}
    assert 'private-auth-token' not in json.dumps(pending)
    assert not Account.objects.filter(telegram_user_id=42).exists()
    assert not h.handled


def test_expired_authentication_stays_an_error_when_a_file_arrives_before_choice():
    c = challenge('private-link-token')
    h = GateHarness()
    h.message(text='/start login_private-link-token')
    first_button = h.language('en')
    AuthChallenge.objects.filter(pk=c.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    h.message(document=document())
    h.click(first_button)
    assert h.ready[0][3] == {'auth_error': 'challenge_expired', 'resend_file': True}
    assert not Account.objects.filter(telegram_user_id=42).exists()


def test_expired_picker_discards_old_uploads_and_retains_only_new_uploads():
    h = GateHarness()
    h.message(document=document(1))
    old_button = h.language('en')
    BotConversation.objects.filter(pk=42).update(language_expires_at=timezone.now() - timedelta(seconds=1))
    h.message(document=document(2))
    h.click(old_button)
    assert not h.ready
    h.click(h.language('en'))
    pending = h.ready[0][3]
    assert [item['document']['file_id'] for item in pending['uploads']] == ['file-2']
    assert pending['resend_file'] is True


def test_bad_or_stale_upload_metadata_falls_back_to_resend_without_storage():
    h = GateHarness()
    h.message(document=Document(file_id='x' * 1025, file_unique_id='unique'))
    assert BotConversation.objects.get(pk=42).pending == {'resend_file': True}
    h.click(h.language('en'))
    assert h.ready[0][3] == {'resend_file': True}
    assert not Account.objects.exists()


def test_plain_start_preserves_files_and_referral_until_language_choice():
    h = GateHarness()
    h.message(text='/start ref_friend')
    h.message(document=document())
    h.message(text='/start')
    h.click(h.language('en'))
    assert h.ready[0][3]['referral_code'] == 'friend'
    assert len(h.ready[0][3]['uploads']) == 1


def test_cancel_before_language_discards_uploads_without_skipping_language_choice():
    h = GateHarness()
    h.message(document=document())
    h.message(text='/cancel')
    assert BotConversation.objects.get(pk=42).pending == {}
    h.click(h.language('en'))
    assert h.ready[0][3] == {}
    assert not Account.objects.exists()
