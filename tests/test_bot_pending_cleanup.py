"""Expired language pickers must not retain private Telegram file handles."""
from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.core.models import BotConversation
from apps.core.services import cleanup_expired


pytestmark = pytest.mark.django_db(transaction=True)


def uploads(user_id):
    return [{'user_id': user_id, 'chat_id': user_id, 'message_id': 12,
             'date': int(timezone.now().timestamp()),
             'document': {'file_id': 'private-telegram-handle', 'file_unique_id': 'unique', 'file_name': 'document.pdf'}}]


def test_cleanup_removes_expired_upload_handles_and_keeps_other_pending_intents():
    remaining = {'challenge_id': str(uuid4()), 'referral_code': 'friend', 'auth_error': 'challenge_expired'}
    conversation = BotConversation.objects.create(
        telegram_user_id=901, language_nonce='expired-picker',
        language_expires_at=timezone.now() - timedelta(seconds=1),
        pending={**remaining, 'uploads': uploads(901)},
    )
    original_updated_at = conversation.updated_at
    assert cleanup_expired() == 0
    conversation.refresh_from_db()
    assert conversation.pending == {**remaining, 'resend_file': True}
    assert conversation.language_selected_at is None
    assert conversation.updated_at == original_updated_at  # Cleanup does not extend any prompt lifetime.
    cleanup_expired()
    conversation.refresh_from_db()
    assert conversation.pending == {**remaining, 'resend_file': True}


def test_cleanup_preserves_active_pending_uploads_and_auth_only_expired_picker():
    active_pending = {'uploads': uploads(902), 'referral_code': 'friend'}
    active = BotConversation.objects.create(
        telegram_user_id=902, language_nonce='active-picker',
        language_expires_at=timezone.now() + timedelta(minutes=10), pending=active_pending,
    )
    auth_pending = {'challenge_id': str(uuid4())}
    expired = BotConversation.objects.create(
        telegram_user_id=903, language_nonce='auth-picker',
        language_expires_at=timezone.now() - timedelta(seconds=1), pending=auth_pending,
    )
    cleanup_expired()
    active.refresh_from_db()
    expired.refresh_from_db()
    assert active.pending == active_pending
    assert expired.pending == auth_pending
    assert active.language_nonce == 'active-picker'
