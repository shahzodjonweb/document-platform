"""One-tap Telegram abuse friction, independent of customer account creation.

This native challenge slows automated onboarding; it is not a browser CAPTCHA.
Durable owner-bound state makes restarts, concurrent callbacks and stale menus
safe. Payment settlement deliberately remains outside the onboarding gate.
"""
import re
import secrets
from datetime import timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from apps.core.models import BotVerification


PREFIX = 'human:'
LIFETIME = timedelta(minutes=5)
VERIFIED_LIFETIME = timedelta(days=30)
COOLDOWN = timedelta(seconds=60)
PROMPT_INTERVAL = timedelta(seconds=15)
MAX_ATTEMPTS = 3
ICONS = ('🍎', '🌻', '🚗', '🐱', '⚽', '☕', '🌈', '🎁')
COPY = {
    'en': {
        'prompt': '🛡 One quick check: tap {icon}.',
        'wrong': 'Try another button 🙂',
        'cooldown': '⏳ Take a minute, then send /start to try again.',
        'expired': 'This check expired. Here’s a fresh one.',
        'invalid': 'This button isn’t yours or has expired.',
        'verified': '✅ You’re all set!',
    },
    'uz': {
        'prompt': '🛡 Tezkor tekshiruv: {icon} ni bosing.',
        'wrong': 'Boshqa tugmani sinab ko‘ring 🙂',
        'cooldown': '⏳ Bir daqiqa kuting, keyin /start yuboring.',
        'expired': 'Tekshiruv eskirdi. Yangisini sinab ko‘ring.',
        'invalid': 'Bu tugma sizniki emas yoki eskirgan.',
        'verified': '✅ Tayyor!',
    },
    'ru': {
        'prompt': '🛡 Быстрая проверка: нажмите {icon}.',
        'wrong': 'Попробуйте другую кнопку 🙂',
        'cooldown': '⏳ Подождите минуту и отправьте /start.',
        'expired': 'Проверка устарела. Вот новая.',
        'invalid': 'Эта кнопка не для вас или уже устарела.',
        'verified': '✅ Всё готово!',
    },
}


def enabled():
    from operations.integrations import antibot_config
    return antibot_config()['bot_enabled']


def _merge_pending(current, incoming, now):
    """Keep only onboarding's bounded hints, with authentication taking priority."""
    result = dict(current or {})
    incoming = dict(incoming or {})
    uploads = result.pop('uploads', [])
    fresh = [item for item in uploads if isinstance(item, dict)
             and isinstance(item.get('date'), int) and now.timestamp() - item['date'] < 1800]
    if len(fresh) != len(uploads):
        result['resend_file'] = True
    if incoming.pop('cancel_uploads', False):
        fresh = []
        result.pop('resend_file', None)
    auth_keys = ('challenge_id', 'auth_error')
    if any(key in incoming for key in auth_keys):
        resend = bool(fresh or result.get('resend_file') or incoming.get('resend_file'))
        result = {key: incoming[key] for key in auth_keys if key in incoming}
        if resend:
            result['resend_file'] = True
        return result
    if any(key in result for key in auth_keys):
        if fresh or incoming.get('uploads') or incoming.get('resend_file'):
            result['resend_file'] = True
        return result
    identities = {(item.get('chat_id'), item.get('message_id')) for item in fresh}
    for item in incoming.get('uploads', []):
        identity = (item.get('chat_id'), item.get('message_id'))
        if identity in identities:
            continue
        if len(fresh) == 10:
            result['resend_file'] = True
            break
        fresh.append(item)
        identities.add(identity)
    result.update({key: value for key, value in incoming.items() if key in ('referral_code', 'resend_file')})
    if fresh:
        result['uploads'] = fresh
    return result


@transaction.atomic
def prepare(telegram_user_id, pending=None):
    row, _ = BotVerification.objects.get_or_create(telegram_user_id=telegram_user_id)
    row = BotVerification.objects.select_for_update().get(pk=row.pk)
    now = timezone.now()
    if row.verified_until and row.verified_until > now:
        return {'status': 'verified'}
    row.pending = _merge_pending(row.pending, pending, now)
    quiet = bool(row.prompt_sent_at and row.prompt_sent_at + PROMPT_INTERVAL > now)
    if row.cooldown_until and row.cooldown_until > now:
        if not quiet:
            row.prompt_sent_at = now
        row.save(update_fields=['pending', 'prompt_sent_at', 'updated_at'])
        return {'status': 'cooldown', 'quiet': quiet}
    if not row.nonce or not row.expires_at or row.expires_at <= now:
        icons = secrets.SystemRandom().sample(ICONS, len(ICONS))
        choices = [{'icon': icon, 'token': secrets.token_hex(4)} for icon in icons]
        answer = secrets.choice(choices)
        row.nonce = secrets.token_urlsafe(12)
        row.challenge = {'choices': choices, 'answer': answer['token'], 'icon': answer['icon']}
        row.expires_at = now + LIFETIME
        row.failures = 0
        row.cooldown_until = None
        # A just-expired/replaced challenge must be visible even if the prior
        # prompt was recent; repeated updates reuse its nonce and are silent.
        quiet = False
    if not quiet:
        row.prompt_sent_at = now
    row.save(update_fields=['nonce', 'challenge', 'expires_at', 'failures', 'cooldown_until',
                            'pending', 'prompt_sent_at', 'updated_at'])
    return {'status': 'required', 'quiet': quiet, 'nonce': row.nonce, 'challenge': row.challenge}


@transaction.atomic
def consume(telegram_user_id, callback_data):
    parts = callback_data.split(':')
    if (len(parts) != 4 or parts[0] != 'human' or parts[1] != str(telegram_user_id)
            or not re.fullmatch(r'[A-Za-z0-9_-]{16}', parts[2])
            or not re.fullmatch(r'[a-f0-9]{8}', parts[3])):
        return {'status': 'invalid'}
    row = BotVerification.objects.select_for_update().filter(pk=telegram_user_id).first()
    now = timezone.now()
    if not row:
        return {'status': 'invalid'}
    if row.verified_until and row.verified_until > now:
        return {'status': 'already_verified'}
    if row.cooldown_until and row.cooldown_until > now:
        return {'status': 'cooldown'}
    if not row.nonce or not secrets.compare_digest(row.nonce, parts[2]):
        return {'status': 'invalid'}
    if not row.expires_at or row.expires_at <= now:
        return {'status': 'expired'}
    if not secrets.compare_digest(str(row.challenge.get('answer', '')), parts[3]):
        row.failures += 1
        status = 'wrong'
        if row.failures >= MAX_ATTEMPTS:
            row.cooldown_until = now + COOLDOWN
            row.nonce, row.challenge = '', {}
            row.prompt_sent_at = now
            status = 'cooldown'
        row.save(update_fields=['failures', 'cooldown_until', 'nonce', 'challenge', 'prompt_sent_at', 'updated_at'])
        return {'status': status}
    pending = _merge_pending(row.pending, None, now)
    row.verified_until = now + VERIFIED_LIFETIME
    row.nonce, row.challenge, row.pending = '', {}, {}
    row.expires_at, row.cooldown_until, row.prompt_sent_at = None, None, None
    row.failures = 0
    row.save(update_fields=['verified_until', 'nonce', 'challenge', 'pending', 'expires_at',
                            'cooldown_until', 'prompt_sent_at', 'failures', 'updated_at'])
    return {'status': 'verified', 'pending': pending}


async def require_verification(message, user, locale, pending=None):
    """Return True when the event was held by verification, False if allowed."""
    if not await sync_to_async(enabled)():
        return False
    result = await sync_to_async(prepare)(user.id, pending)
    if result['status'] == 'verified':
        return False
    if result.get('quiet'):
        return True
    copy = COPY.get(locale, COPY['en'])
    if result['status'] == 'cooldown':
        await message.answer(copy['cooldown'])
    else:
        buttons = [InlineKeyboardButton(
            text=choice['icon'], callback_data=f"{PREFIX}{user.id}:{result['nonce']}:{choice['token']}",
        ) for choice in result['challenge']['choices']]
        await message.answer(copy['prompt'].format(icon=result['challenge']['icon']),
                             reply_markup=InlineKeyboardMarkup(inline_keyboard=[buttons[:4], buttons[4:]]))
    return True


async def answer_verification(event, locale, on_verified):
    copy = COPY.get(locale, COPY['en'])
    if not await sync_to_async(enabled)():
        await event.answer(copy['invalid'])
        return
    result = await sync_to_async(consume)(event.from_user.id, event.data or '')
    status = result['status']
    if status == 'verified':
        await event.answer(copy['verified'])
        from apps.core import funnel
        await sync_to_async(funnel.step)('bot.verified', telegram_user_id=event.from_user.id)
        return await on_verified(event.message, event.from_user, locale, result['pending'])
    if status == 'already_verified':
        return await event.answer(copy['verified'])
    await event.answer(copy[status], show_alert=status == 'cooldown')
    if status == 'expired':
        await require_verification(event.message, event.from_user, locale)


def cleanup_expired_pending(now):
    """Release private file handles when a verification challenge expires."""
    candidates = BotVerification.objects.filter(expires_at__lte=now, pending__has_key='uploads')
    for telegram_user_id in candidates.values_list('pk', flat=True).iterator():
        with transaction.atomic():
            row = BotVerification.objects.select_for_update().filter(
                pk=telegram_user_id, expires_at__lte=now, pending__has_key='uploads',
            ).first()
            if row:
                row.pending.pop('uploads', None)
                row.pending['resend_file'] = True
                row.save(update_fields=['pending', 'updated_at'])
