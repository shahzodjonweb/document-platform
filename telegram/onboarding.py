"""Private, language-first bot onboarding independent of customer identity.

The gate runs before command and file handlers. Selecting a language does not
create an Account: the caller decides whether to resume a browser login/link,
claim a referral, or open the normal workspace.
"""
import hashlib
import re
import secrets
from datetime import timedelta

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from asgiref.sync import sync_to_async
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core import funnel
from apps.core.models import Account, AuthChallenge, BotCallback, BotConversation
from .verification import PREFIX as VERIFICATION_PREFIX, answer_verification, require_verification


LANGUAGES = (('uz', '🇺🇿 O‘zbekcha'), ('en', '🇬🇧 English'), ('ru', '🇷🇺 Русский'))
LOCALES = frozenset(locale for locale, _ in LANGUAGES)
PICKER_TEXT = '🌐 Tilni tanlang · Choose your language · Выберите язык'
PRIVATE_TEXT = {
    'en': '🔒 Open a private chat with me to continue.',
    'uz': '🔒 Davom etish uchun menga shaxsiy chatda yozing.',
    'ru': '🔒 Напишите мне в личный чат, чтобы продолжить.',
}
EXPIRED_TEXT = {
    'en': 'This menu has expired. Choose again with /language.',
    'uz': 'Menyu eskirgan. /language orqali qayta tanlang.',
    'ru': 'Меню устарело. Выберите язык снова: /language.',
}
LINK_RETURN_TEXT = {
    'en': '✅ Approved! Return to the browser where you started to finish linking. Then come back here.',
    'uz': '✅ Tasdiqlandi! Ulashni tugatish uchun boshlagan brauzeringizga qayting. Keyin shu yerga qaytishingiz mumkin.',
    'ru': '✅ Подтверждено! Завершите привязку в браузере, где вы её начали. Затем возвращайтесь сюда.',
}
LANGUAGE_PREFIX = 'lang:'
MAX_PENDING_UPLOADS = 10
PICKER_LIFETIME = timedelta(minutes=30)


def chosen_locale(telegram_user_id):
    """Return only a language explicitly selected in this bot, never a guess."""
    return BotConversation.objects.filter(
        telegram_user_id=telegram_user_id,
        language_selected_at__isnull=False,
        locale__in=LOCALES,
    ).values_list('locale', flat=True).first()


def _is_private(message, user):
    return bool(isinstance(message, Message) and user and not user.is_bot and 0 < user.id < 2**63
                and message.chat.type == 'private' and message.chat.id == user.id)


def _command(message):
    text = message.text or ''
    # Commands typed without entities still work in local/offline transports.
    return text.split(maxsplit=1)[0].split('@', 1)[0].lower() if text else ''


def _upload_hint(message):
    """Save only bounded Telegram handles, never file contents or captions."""
    user = message.from_user
    if not _is_private(message, user) or message.message_id <= 0:
        return None
    if message.date < timezone.now() - PICKER_LIFETIME:
        return None
    media = message.document or (message.photo[-1] if message.photo else None)
    if not media:
        return None
    values = {}
    for key, maximum in (('file_id', 1024), ('file_unique_id', 255), ('file_name', 255), ('mime_type', 128)):
        value = getattr(media, key, None)
        if value is not None:
            if not isinstance(value, str) or not value or len(value) > maximum:
                return None
            values[key] = value
    if 'file_id' not in values or 'file_unique_id' not in values:
        return None
    if media.file_size is not None:
        if not 0 <= media.file_size < 2**63:
            return None
        values['file_size'] = media.file_size
    envelope = {'user_id': user.id, 'chat_id': message.chat.id,
                'message_id': message.message_id, 'date': int(message.date.timestamp())}
    if message.document:
        envelope['document'] = values
    else:
        if not 0 < media.width < 2**31 or not 0 < media.height < 2**31:
            return None
        values.update(width=media.width, height=media.height)
        envelope['photo'] = [values]
    return envelope


def _pending_for(message):
    """Retain safe resumption hints; never persist raw login tokens or bytes."""
    if _command(message) == '/cancel':
        return {'cancel_uploads': True}
    if _command(message) == '/start':
        parts = (message.text or '').split(maxsplit=1)
        payload = parts[1] if len(parts) == 2 else ''
        if payload.startswith('login_'):
            token = payload[6:]
            if not token or len(token) > 128:
                return {'auth_error': 'challenge_expired'}
            challenge = AuthChallenge.objects.filter(
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                expires_at__gt=timezone.now(), consumed_at__isnull=True,
                approved_at__isnull=True,
            ).values_list('id', flat=True).first()
            return ({'challenge_id': str(challenge)} if challenge
                    else {'auth_error': 'challenge_expired'})
        if payload.startswith('ref_'):
            code = payload[4:]
            if re.fullmatch(r'[A-Za-z0-9_-]{1,64}', code):
                return {'referral_code': code}
        return {}
    if message.document or message.photo:
        upload = _upload_hint(message)
        return {'uploads': [upload]} if upload else {'resend_file': True}
    return None


def _active_link(telegram_user_id):
    """Recover only a still-valid link owned by this Telegram conversation.

    Approval in Telegram does not attach the identity until the initiating
    browser exchanges its verifier. During that gap, ordinary bot actions must
    not create a competing Telegram Account.
    """
    conversation = BotConversation.objects.filter(pk=telegram_user_id).first()
    pending_id = conversation.pending.get('challenge_id') if conversation else None
    if Account.objects.filter(telegram_user_id=telegram_user_id).exists():
        try:
            pending_is_link = pending_id and AuthChallenge.objects.filter(pk=pending_id, intent='link').exists()
        except (ValueError, TypeError, ValidationError):
            pending_is_link = True
        if pending_is_link:
            BotConversation.objects.filter(pk=telegram_user_id).update(pending={})
        return None
    candidates = AuthChallenge.objects.select_related('link_account').filter(
        intent='link', expires_at__gt=timezone.now(), consumed_at__isnull=True,
        link_account__isnull=False, link_account__deletion_requested_at__isnull=True,
    )
    challenge = None
    if pending_id:
        try:
            challenge = candidates.filter(pk=pending_id).first()
        except (ValueError, TypeError, ValidationError):
            challenge = None
    if not challenge:
        # Covers an already-onboarded customer whose link prompt was issued
        # before this process restarted or before conversation state existed.
        refs = BotCallback.objects.filter(
            action='link_login', payload__telegram_user_id=telegram_user_id,
            expires_at__gt=timezone.now(),
        ).order_by('-expires_at').values_list('payload', 'account_id')[:10]
        for payload, account_id in refs:
            try:
                challenge = candidates.filter(pk=payload.get('challenge_id'), link_account_id=account_id).first()
            except (ValueError, TypeError, ValidationError):
                continue
            if challenge:
                break
    if challenge and (challenge.link_auth_version != challenge.link_account.auth_version
                      or (challenge.approved_at and challenge.telegram_user.get('id') != telegram_user_id)):
        challenge = None
    if challenge:
        values = {'challenge_id': str(challenge.id)}
        if conversation and conversation.pending.get('resend_file'):
            values['resend_file'] = True
        BotConversation.objects.update_or_create(telegram_user_id=telegram_user_id, defaults={'pending': values})
    elif pending_id:
        # Login challenges still need their one-time continuation, so do not
        # erase one merely because it is not a linking challenge.
        try:
            was_link = AuthChallenge.objects.filter(pk=pending_id, intent='link').exists()
        except (ValueError, TypeError, ValidationError):
            was_link = True
        if was_link:
            # Until language choice, an expired auth intent must not turn an
            # accidental upload into a newly created Telegram account.
            pending = ({'auth_error': 'challenge_expired'}
                       if conversation and not conversation.language_selected_at else {})
            BotConversation.objects.filter(pk=telegram_user_id).update(pending=pending)
    return challenge


def _remember_link_start(telegram_user_id, pending):
    if not pending or not pending.get('challenge_id'):
        return
    challenge = AuthChallenge.objects.filter(
        pk=pending['challenge_id'], intent='link', expires_at__gt=timezone.now(), consumed_at__isnull=True,
    ).first()
    if challenge and not Account.objects.filter(telegram_user_id=telegram_user_id).exists():
        BotConversation.objects.update_or_create(telegram_user_id=telegram_user_id, defaults={'pending': pending})


def _is_link_confirmation(telegram_user_id, token, challenge):
    return BotCallback.objects.filter(
        token=token, action='link_login', account_id=challenge.link_account_id,
        payload__challenge_id=str(challenge.id), payload__telegram_user_id=telegram_user_id,
        expires_at__gt=timezone.now(),
    ).exists()


@transaction.atomic
def _prepare_picker(telegram_user_id, pending):
    conversation, _ = BotConversation.objects.get_or_create(telegram_user_id=telegram_user_id)
    conversation = BotConversation.objects.select_for_update().get(pk=conversation.pk)
    now = timezone.now()
    reuse = bool(not conversation.language_selected_at and conversation.language_nonce
                 and conversation.language_expires_at and conversation.language_expires_at > now)
    if not reuse:
        conversation.language_nonce = secrets.token_urlsafe(12)
        conversation.language_expires_at = now + PICKER_LIFETIME
    active_link = _active_link(telegram_user_id)
    conversation.refresh_from_db(fields=['pending'])
    if pending and pending.get('cancel_uploads'):
        conversation.pending.pop('uploads', None)
        conversation.pending.pop('resend_file', None)
        pending = None
    if not reuse and conversation.pending.get('uploads'):
        # Starting a fresh picker must not replay files from an expired one.
        conversation.pending = {key: value for key, value in conversation.pending.items() if key != 'uploads'}
        conversation.pending['resend_file'] = True
    if active_link:
        resend = (conversation.pending.get('resend_file') or conversation.pending.get('uploads')
                  or (pending and (pending.get('resend_file') or pending.get('uploads'))))
        conversation.pending = {'challenge_id': str(active_link.id)}
        if resend:
            conversation.pending['resend_file'] = True
    elif pending is not None:
        auth_keys = ('challenge_id', 'auth_error')
        incoming_auth = any(key in pending for key in auth_keys)
        current_auth = any(key in conversation.pending for key in auth_keys)
        if incoming_auth:
            conversation.pending = pending
        elif current_auth:
            # Authentication always wins: do not retain or replay uploads into
            # a different account, even for an invalid/expired login link.
            if pending.get('uploads') or pending.get('resend_file'):
                conversation.pending['resend_file'] = True
            conversation.pending.pop('uploads', None)
        else:
            uploads = list(conversation.pending.get('uploads', []))
            identities = {(item['chat_id'], item['message_id']) for item in uploads}
            overflow = False
            for item in pending.get('uploads', []):
                identity = (item['chat_id'], item['message_id'])
                if identity in identities:
                    continue
                if len(uploads) >= MAX_PENDING_UPLOADS:
                    overflow = True
                    continue
                uploads.append(item)
                identities.add(identity)
            conversation.pending.update({key: value for key, value in pending.items() if key != 'uploads'})
            if uploads:
                conversation.pending['uploads'] = uploads
            if overflow:
                conversation.pending['resend_file'] = True
    conversation.state, conversation.prompt = '', {}
    conversation.save(update_fields=[
        'language_nonce', 'language_expires_at', 'pending', 'state', 'prompt', 'updated_at',
    ])
    # A file album needs one picker, not a new message for every photo. The
    # first picker remains usable because its nonce was deliberately retained.
    silent = bool(reuse and pending and (pending.get('uploads') or pending.get('resend_file')))
    return conversation.language_nonce, silent


async def show_language(message, user, pending=None):
    """Show an owner-bound picker; preserve it while first uploads arrive."""
    if not _is_private(message, user):
        return
    nonce, silent = await sync_to_async(_prepare_picker)(user.id, pending)
    if silent:
        return None
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=label, callback_data=f'{LANGUAGE_PREFIX}{user.id}:{nonce}:{locale}')
    ] for locale, label in LANGUAGES])
    return await message.answer(PICKER_TEXT, reply_markup=markup)


@transaction.atomic
def _select_language(telegram_user_id, callback_data):
    parts = callback_data.split(':')
    if (len(parts) != 4 or parts[0] != 'lang' or parts[1] != str(telegram_user_id)
            or not re.fullmatch(r'[A-Za-z0-9_-]{16}', parts[2]) or parts[3] not in LOCALES):
        return None
    conversation = BotConversation.objects.select_for_update().filter(pk=telegram_user_id).first()
    if (not conversation or not conversation.language_nonce
            or not secrets.compare_digest(conversation.language_nonce, parts[2])
            or not conversation.language_expires_at or conversation.language_expires_at <= timezone.now()):
        return None
    locale, pending = parts[3], conversation.pending
    original_challenge_id = pending.get('challenge_id')
    conversation.locale = locale
    conversation.language_selected_at = timezone.now()
    conversation.language_nonce = ''
    conversation.language_expires_at = None
    active_link = _active_link(telegram_user_id)
    conversation.refresh_from_db(fields=['pending'])
    pending = conversation.pending
    if original_challenge_id and not pending and not Account.objects.filter(telegram_user_id=telegram_user_id).exists():
        pending = {'auth_error': 'challenge_expired'}
    conversation.pending = {'challenge_id': str(active_link.id)} if active_link else {}
    conversation.state, conversation.prompt = '', {}
    conversation.save(update_fields=[
        'locale', 'language_selected_at', 'language_nonce', 'language_expires_at',
        'pending', 'state', 'prompt', 'updated_at',
    ])
    # Deliberately update rather than resolve/create: a linking visitor can have
    # an existing email/Google account that does not yet have a Telegram ID.
    Account.objects.filter(telegram_user_id=telegram_user_id).update(locale=locale)
    return locale, pending


class LanguageGate(BaseMiddleware):
    def __init__(self, on_ready):
        self.on_ready = on_ready

    async def resume_link(self, message, user, locale, challenge):
        if challenge.approved_at:
            return await message.answer(LINK_RETURN_TEXT[locale or 'en'])
        return await self.on_ready(message, user, locale, {'challenge_id': str(challenge.id)})

    async def continue_ready(self, message, user, locale, pending):
        active_link = await sync_to_async(_active_link)(user.id)
        if active_link and active_link.approved_at:
            from .commands import install_chat_commands
            await install_chat_commands(message.bot, user.id, locale)
            return await self.resume_link(message, user, locale, active_link)
        if active_link:
            pending = {'challenge_id': str(active_link.id),
                       **({'resend_file': True} if pending.get('resend_file') or pending.get('uploads') else {})}
        return await self.on_ready(message, user, locale, pending)

    async def __call__(self, handler, event, data):
        if isinstance(event, Message):
            # Settlement must be processed even if a customer has never used
            # this version of onboarding, or their conversation state was reset.
            if event.successful_payment:
                return await handler(event, data)
            user = event.from_user
            if not user or user.is_bot:
                return None
            locale = await sync_to_async(chosen_locale)(user.id)
            if not _is_private(event, user):
                return await event.answer(PRIVATE_TEXT[locale or 'en'])
            pending = await sync_to_async(_pending_for)(event)
            await sync_to_async(_remember_link_start)(user.id, pending)
            active_link = await sync_to_async(_active_link)(user.id)
            if _command(event) == '/language':
                return await show_language(event, user)
            if not locale:
                await sync_to_async(funnel.step)('bot.start', telegram_user_id=user.id)
                return await show_language(event, user, pending)
            verification_pending = pending
            if active_link:
                verification_pending = {'challenge_id': str(active_link.id)}
                if pending and (pending.get('uploads') or pending.get('resend_file')):
                    verification_pending['resend_file'] = True
            if await require_verification(event, user, locale, verification_pending):
                return None
            if active_link:
                return await self.resume_link(event, user, locale, active_link)
            data['bot_locale'] = locale
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            user = event.from_user
            locale = await sync_to_async(chosen_locale)(user.id)
            if not _is_private(event.message, user):
                return await event.answer(PRIVATE_TEXT[locale or 'en'], show_alert=True)
            if (event.data or '').startswith(LANGUAGE_PREFIX):
                selected = await sync_to_async(_select_language)(user.id, event.data)
                if not selected:
                    return await event.answer(EXPIRED_TEXT[locale or 'en'], show_alert=True)
                locale, pending = selected
                await event.answer()
                await sync_to_async(funnel.step)('bot.language', telegram_user_id=user.id)
                if await require_verification(event.message, user, locale, pending):
                    return None
                # query.message.from_user is the bot; always supply the verified
                # callback sender explicitly to the identity-resuming handler.
                return await self.continue_ready(event.message, user, locale, pending)
            if not locale:
                await event.answer()
                return await show_language(event.message, user)
            if (event.data or '').startswith(VERIFICATION_PREFIX):
                return await answer_verification(event, locale, self.continue_ready)
            active_link = await sync_to_async(_active_link)(user.id)
            pending = {'challenge_id': str(active_link.id)} if active_link else None
            if await require_verification(event.message, user, locale, pending):
                return await event.answer()
            if active_link:
                allowed = (not active_link.approved_at and await sync_to_async(_is_link_confirmation)(user.id, event.data, active_link))
                if not allowed:
                    await event.answer()
                    return await self.resume_link(event.message, user, locale, active_link)
            data['bot_locale'] = locale
            return await handler(event, data)
        return await handler(event, data)


def install_onboarding(dispatcher, on_ready):
    """Attach before all message/callback handlers; pre-checkout is untouched."""
    gate = LanguageGate(on_ready)
    dispatcher.message.outer_middleware(gate)
    dispatcher.callback_query.outer_middleware(gate)
    return gate
