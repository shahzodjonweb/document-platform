"""The bot message that Plus months were earned by inviting friends.

Durable like the card-transfer notices (telegram/payment_notices.py): each
ReferralReward is claimed under a lease, sent once, and retried with backoff
when Telegram is unavailable, so a reward is never silently unannounced and
never announced twice.
"""
from datetime import timedelta

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

MAX_ATTEMPTS = 5


@transaction.atomic
def claim(reward_id):
    from apps.commerce.models import ReferralReward
    reward = ReferralReward.objects.select_for_update().select_related('inviter', 'period').filter(pk=reward_id).first()
    now = timezone.now()
    if reward is None or reward.status not in ('pending', 'retrying', 'sending'):
        return None
    if reward.status == 'sending' and reward.lease_until and reward.lease_until > now:
        return None
    if reward.next_attempt_at > now:
        return None
    reward.status, reward.lease_until, reward.attempts = 'sending', now + timedelta(seconds=120), reward.attempts + 1
    reward.save(update_fields=['status', 'lease_until', 'attempts'])
    return reward


def finish(reward_id, *, status, message_id=None, error='', delay=0):
    from apps.commerce.models import ReferralReward
    values = {'status': status, 'message_id': message_id, 'error_code': error, 'lease_until': None,
              'next_attempt_at': timezone.now() + timedelta(seconds=delay)}
    if status == 'delivered':
        values['delivered_at'] = timezone.now()
    ReferralReward.objects.filter(pk=reward_id, status='sending').update(**values)


def compose(reward):
    """(chat_id, text) for a reward, or (None, reason) when it cannot be sent."""
    from .invites import reward_message
    if reward.inviter.telegram_user_id is None:
        return None, 'telegram_link_required'
    if reward.inviter.deletion_requested_at:
        return None, 'account_deleted'
    return reward.inviter.telegram_user_id, reward_message(reward)


async def buttons(reward):
    """An Invite friends button under the message, or nothing: the message matters more."""
    try:
        from aiogram.types import InlineKeyboardMarkup
        from .invites import invite_button
        return InlineKeyboardMarkup(inline_keyboard=[[await invite_button(reward.inviter)]])
    except Exception:
        return None


async def attempt(reward_id, bot):
    reward = await sync_to_async(claim)(reward_id)
    if not reward:
        return
    from aiogram.client.session.aiohttp import AiohttpSession
    if reward.inviter.is_test and isinstance(getattr(bot, 'session', None), AiohttpSession):
        return await sync_to_async(finish)(reward.id, status='blocked', error='test_account_delivery')
    chat, text = await sync_to_async(compose)(reward)
    if chat is None:
        return await sync_to_async(finish)(reward.id, status='skipped', error=text)
    markup = await buttons(reward)
    try:
        response = await bot.send_message(chat, text, parse_mode='HTML', disable_web_page_preview=True,
                                          reply_markup=markup)
        await sync_to_async(finish)(reward.id, status='delivered', message_id=response.message_id)
    except TelegramRetryAfter as exc:
        await sync_to_async(finish)(reward.id, status='retrying', error='telegram_rate_limited',
                                    delay=min(3600, max(1, exc.retry_after)))
    except TelegramForbiddenError:
        await sync_to_async(finish)(reward.id, status='blocked', error='telegram_blocked')
    except Exception:
        await sync_to_async(finish)(reward.id, status='failed' if reward.attempts >= MAX_ATTEMPTS else 'retrying',
                                    error='telegram_delivery_failed', delay=min(3600, 2 ** reward.attempts * 10))


async def drain(bot):
    from apps.commerce.models import ReferralReward
    due = await sync_to_async(lambda: list(
        ReferralReward.objects.filter(status__in=('pending', 'retrying', 'sending'), next_attempt_at__lte=timezone.now())
        .order_by('created_at').values_list('id', flat=True)[:20]))()
    for identifier in due:
        await attempt(identifier, bot)
