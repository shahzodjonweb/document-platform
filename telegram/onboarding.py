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

from apps.core.models import Account, AuthChallenge, BotCallback, BotConversation


LANGUAGES = (('uz', 'O‘zbekcha'), ('en', 'English'), ('ru', 'Русский'))
LOCALES = frozenset(locale for locale, _ in LANGUAGES)
PICKER_TEXT = 'Tilni tanlang · Choose your language · Выберите язык'
PRIVATE_TEXT = {
    'en': 'Open a private chat with this bot to continue.',
    'uz': 'Davom etish uchun bot bilan shaxsiy chatni oching.',
    'ru': 'Чтобы продолжить, откройте личный чат с ботом.',
}
EXPIRED_TEXT = {
    'en': 'This language menu has expired. Use /language to choose again.',
    'uz': 'Bu til menyusi eskirdi. Qayta tanlash uchun /language yuboring.',
    'ru': 'Это меню языка устарело. Выберите язык снова командой /language.',
}
LINK_RETURN_TEXT = {
    'en': 'Telegram link approved. Return to the browser where you started to finish linking your account. Then come back here.',
    'uz': 'Telegram ulanishi tasdiqlandi. Hisobni ulashni tugatish uchun boshlagan brauzeringizga qayting. So‘ng bu yerga qayting.',
    'ru': 'Привязка Telegram подтверждена. Вернитесь в браузер, где вы начали, чтобы завершить привязку аккаунта. Затем возвращайтесь сюда.',
}
LANGUAGE_PREFIX = 'lang:'


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


def _pending_for(message):
    """Retain safe resumption hints; never persist raw login tokens or files."""
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
        return {'resend_file': True}
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
            BotConversation.objects.filter(pk=telegram_user_id).update(pending={})
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
    conversation.language_nonce = secrets.token_urlsafe(12)
    conversation.language_expires_at = timezone.now() + timedelta(minutes=30)
    active_link = _active_link(telegram_user_id)
    conversation.refresh_from_db(fields=['pending'])
    if active_link:
        resend = conversation.pending.get('resend_file') or (pending and pending.get('resend_file'))
        conversation.pending = {'challenge_id': str(active_link.id)}
        if resend:
            conversation.pending['resend_file'] = True
    elif pending is not None:
        # An accidental upload while choosing a language must not discard a
        # pending account-link challenge and fall through to account creation.
        conversation.pending = ({**conversation.pending, **pending}
                                if pending == {'resend_file': True} else pending)
    conversation.state, conversation.prompt = '', {}
    conversation.save(update_fields=[
        'language_nonce', 'language_expires_at', 'pending', 'state', 'prompt', 'updated_at',
    ])
    return conversation.language_nonce


async def show_language(message, user, pending=None):
    """Show a fresh one-use picker, including for an already onboarded user."""
    if not _is_private(message, user):
        return
    nonce = await sync_to_async(_prepare_picker)(user.id, pending)
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
            pending = await sync_to_async(_pending_for)(event) if not locale or _command(event) == '/start' else None
            await sync_to_async(_remember_link_start)(user.id, pending)
            active_link = await sync_to_async(_active_link)(user.id)
            if _command(event) == '/language':
                return await show_language(event, user)
            if not locale:
                return await show_language(event, user, pending)
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
                active_link = await sync_to_async(_active_link)(user.id)
                if active_link and active_link.approved_at:
                    from .commands import install_chat_commands
                    await install_chat_commands(event.bot, user.id, locale)
                    return await self.resume_link(event.message, user, locale, active_link)
                # query.message.from_user is the bot; always supply the verified
                # callback sender explicitly to the identity-resuming handler.
                return await self.on_ready(event.message, user, locale, pending)
            if not locale:
                await event.answer()
                return await show_language(event.message, user)
            active_link = await sync_to_async(_active_link)(user.id)
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
