"""Posts from Admin → Posts, sent to the bot's users (apps/core/posts.py decides who).

Durable like the other outboxes: each person's copy is claimed under a lease,
sent once, and retried with backoff when Telegram is unavailable. Unlike them a
post can go to every user at once, so it is paced under Telegram's limit for a
bot, and a request to slow down pauses the whole post, not one copy.

A copy whose lease ran out, or whose send timed out, was cut off between the
send and its result. It may well have arrived, so it is not sent again: a
second copy is worse than one that is not counted. A tap on its button puts the
count right (apps.core.posts.record_view).

What goes wrong for one person (blocked the bot, a chat Telegram refuses) is
that person's; what goes wrong for everyone (Telegram down, the image not
readable) pauses the post and costs nobody their copy.
"""
import asyncio
import logging
import time
from datetime import timedelta

from asgiref.sync import sync_to_async
from aiogram import BaseMiddleware
from aiogram.exceptions import (
    TelegramBadRequest, TelegramEntityTooLarge, TelegramForbiddenError, TelegramNetworkError, TelegramNotFound,
    TelegramRetryAfter, TelegramServerError, TelegramUnauthorizedError,
)
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

# At most 20 messages a second: under Telegram's 30 for a bot, which customers'
# own replies share. Sends go one at a time, so Telegram's answer time slows
# this further.
PACE = 1 / 20
BATCH = 100
MAX_ATTEMPTS = 5
LEASE = 120
# While Telegram or the image store cannot be reached, the whole post waits this
# long between tries. Only the copy at the head of the line tries, so an outage
# costs one person attempts, and only after an hour of them their copy.
HOLD = 30
HOLD_ATTEMPTS = 120
PREFIX = 'post:'
BUTTON_DEFAULT = {'en': '👌 Got it', 'uz': '👌 Tushunarli', 'ru': '👌 Понятно'}
THANKS = {'en': 'Thanks!', 'uz': 'Rahmat!', 'ru': 'Спасибо!'}


@transaction.atomic
def claim(recipient_id):
    from apps.core.models import PostRecipient
    row = (PostRecipient.objects.select_for_update(of=('self',)).select_related('post', 'account')
           .filter(pk=recipient_id).first())
    now = timezone.now()
    if row is None or row.status not in ('pending', 'retrying', 'sending'):
        return None
    if row.status == 'sending':
        if not row.lease_until or row.lease_until <= now:
            row.status, row.error_code, row.lease_until = 'failed', 'interrupted', None
            row.save(update_fields=['status', 'error_code', 'lease_until'])
        return None
    if row.next_attempt_at > now:
        return None
    if row.account.deletion_requested_at:
        # Asked to be deleted after the post went out.
        row.status, row.error_code, row.lease_until = 'skipped', 'account_deleted', None
        row.save(update_fields=['status', 'error_code', 'lease_until'])
        return None
    if not row.is_test and row.post.status != 'sending':
        return None
    if row.post.paused_until and row.post.paused_until > now:
        return None
    row.status, row.lease_until, row.attempts = 'sending', now + timedelta(seconds=LEASE), row.attempts + 1
    row.save(update_fields=['status', 'lease_until', 'attempts'])
    return row


def finish(recipient_id, *, status, message_id=None, error='', delay=0):
    from apps.core.models import PostRecipient
    values = {'status': status, 'message_id': message_id, 'error_code': error, 'lease_until': None,
              'next_attempt_at': timezone.now() + timedelta(seconds=delay)}
    if status == 'delivered':
        values['delivered_at'] = timezone.now()
    PostRecipient.objects.filter(pk=recipient_id, status='sending').update(**values)


def pause(post_id, seconds):
    from apps.core.models import Post
    Post.objects.filter(pk=post_id).update(paused_until=timezone.now() + timedelta(seconds=seconds))


def hold(row, error):
    """Telegram or the image store is unavailable: the post pauses and the copy
    waits at the head of the line."""
    finish(row.id, status='failed' if row.attempts >= HOLD_ATTEMPTS else 'retrying', error=error, delay=HOLD)
    pause(row.post_id, HOLD)


def remember_photo(post_id, file_id):
    """Telegram's name for the image: everyone after the first gets it by this."""
    from apps.core.models import Post
    Post.objects.filter(pk=post_id, image_file_id='').update(image_file_id=file_id)


def forget_photo(post_id):
    from apps.core.models import Post
    Post.objects.filter(pk=post_id).update(image_file_id='')


def markup(row):
    """The one button under a post. Its data is the row's own id: the tap is
    checked against the row's account, so no token rows are kept for it."""
    locale = row.account.locale if row.account.locale in BUTTON_DEFAULT else 'en'
    label = row.post.button_label or BUTTON_DEFAULT[locale]
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, callback_data=PREFIX + row.id.hex)]])


def stale_file(error):
    """Telegram no longer knows the image by the name it gave it."""
    message = str(error).lower()
    return any(words in message for words in ('file identifier', 'file_id', 'remote file', 'file reference'))


async def attempt(recipient_id, bot):
    """Send one person's copy. False when the post has to wait: Telegram asked
    the bot to slow down, or Telegram or the image cannot be reached."""
    row = await sync_to_async(claim)(recipient_id)
    if not row:
        return True
    account, post = row.account, row.post
    if account.telegram_user_id is None:
        await sync_to_async(finish)(row.id, status='blocked', error='telegram_link_required')
        return True
    from aiogram.client.session.aiohttp import AiohttpSession
    if account.is_test and isinstance(getattr(bot, 'session', None), AiohttpSession):
        await sync_to_async(finish)(row.id, status='blocked', error='test_account_delivery')
        return True
    data = None
    if post.image_key and not post.image_file_id:
        from apps.core import storage
        try:
            data = await sync_to_async(storage.read_bytes)(post.image_key)
        except Exception:
            logging.getLogger(__name__).warning('The image of post %s could not be read', post.id, exc_info=True)
            await sync_to_async(hold)(row, 'post_image_unavailable')
            return False
    chat, buttons = account.telegram_user_id, markup(row)
    try:
        # Plain text, as written: no parse mode, so nothing in it is markup.
        if post.image_file_id:
            response = await bot.send_photo(chat, post.image_file_id, caption=post.text, parse_mode=None,
                                            reply_markup=buttons)
        elif data is not None:
            response = await bot.send_photo(chat, BufferedInputFile(data, filename='post.jpg'), caption=post.text,
                                            parse_mode=None, reply_markup=buttons)
        else:
            response = await bot.send_message(chat, post.text, parse_mode=None, disable_web_page_preview=True,
                                              reply_markup=buttons)
    except TelegramRetryAfter as exc:
        delay = min(3600, max(1, exc.retry_after))
        await sync_to_async(finish)(row.id, status='retrying', error='telegram_rate_limited', delay=delay)
        await sync_to_async(pause)(post.id, delay)
        return False
    except TelegramForbiddenError:
        await sync_to_async(finish)(row.id, status='blocked', error='telegram_blocked')
        return True
    except TelegramEntityTooLarge:
        await sync_to_async(finish)(row.id, status='failed', error='telegram_rejected')
        return True
    except TelegramNetworkError as exc:
        if 'timeout' in str(exc).lower():
            # It may have arrived: not sent again (see the top of this module).
            await sync_to_async(finish)(row.id, status='failed', error='interrupted')
            await sync_to_async(pause)(post.id, HOLD)
        else:
            await sync_to_async(hold)(row, 'telegram_unavailable')
        return False
    except (TelegramServerError, TelegramUnauthorizedError):
        await sync_to_async(hold)(row, 'telegram_unavailable')
        return False
    except (TelegramBadRequest, TelegramNotFound) as exc:
        if post.image_file_id and stale_file(exc):
            await sync_to_async(forget_photo)(post.id)
            await sync_to_async(finish)(row.id, status='retrying', error='telegram_delivery_failed', delay=1)
        else:
            # Telegram refuses this chat (or this copy): asking again changes nothing.
            await sync_to_async(finish)(row.id, status='failed', error='telegram_rejected')
        return True
    except Exception:
        logging.getLogger(__name__).warning('A copy of post %s could not be sent', post.id, exc_info=True)
        await sync_to_async(finish)(row.id, status='failed' if row.attempts >= MAX_ATTEMPTS else 'retrying',
                                    error='telegram_delivery_failed', delay=min(3600, 2 ** row.attempts * 10))
        return True
    # Kept after the send, not inside it: a failure here must not send it again.
    await sync_to_async(finish)(row.id, status='delivered', message_id=response.message_id)
    photo = getattr(response, 'photo', None)
    if data is not None and photo:
        await sync_to_async(remember_photo)(post.id, photo[-1].file_id)
    return True


def due(account=None, limit=BATCH):
    """Copies to send now: a test first, then in the order the posts went out.

    Test accounts get theirs only through the local simulator (`account`),
    which has no loop of its own."""
    from apps.core.models import PostRecipient
    now = timezone.now()
    rows = (PostRecipient.objects.filter(status__in=('pending', 'retrying', 'sending'), next_attempt_at__lte=now)
            .filter(Q(post__status='sending') | Q(is_test=True)).exclude(post__paused_until__gt=now))
    rows = rows.filter(account=account) if account else rows.filter(account__is_test=False)
    return list(rows.order_by('-is_test', 'created_at', 'pk').values_list('id', flat=True)[:limit])


async def drain(bot, account=None):
    """Send what is due, at the pace. Returns how many copies were looked at."""
    from apps.core.posts import settle
    ids = await sync_to_async(due)(account)
    for identifier in ids:
        began = time.monotonic()
        if not await attempt(identifier, bot):
            break
        await asyncio.sleep(max(0, PACE - (time.monotonic() - began)))
    await sync_to_async(settle)()
    return len(ids)


async def post_loop(bot):
    """The polling bot's sender, alongside result delivery."""
    while True:
        looked = 0
        try:
            looked = await drain(bot)
        except Exception:
            logging.getLogger(__name__).exception('Posts could not be sent')
        await asyncio.sleep(0.5 if looked else 3)


async def standalone_drain(bot, seconds=50):
    """A webhook deployment's `deliverbot` run: what is due, for under a minute,
    so runs a minute apart do not pile up."""
    end = time.monotonic() + seconds
    while time.monotonic() < end and await drain(bot):
        pass


class PostTaps(BaseMiddleware):
    """A tap on a post's button, answered before anything else sees it: before
    the language choice and the anti-bot check, so anyone's view counts, and
    before the menu's catch-all, which would call the button stale."""

    async def __call__(self, handler, event, data):
        if not isinstance(event, CallbackQuery) or not (event.data or '').startswith(PREFIX):
            return await handler(event, data)
        from apps.core.posts import record_view
        row = await sync_to_async(record_view)(event.data[len(PREFIX):], event.from_user.id)
        if row is None:
            from .bot import sender_language, text
            return await event.answer(text(sender_language(event.from_user), 'controls_expired'), show_alert=True)
        locale = row.account.locale if row.account.locale in THANKS else 'en'
        await event.answer(THANKS[locale])
        if event.message:
            try:
                await event.message.edit_reply_markup(reply_markup=None)
            except Exception:
                # The thanks is what matters; an old or edited message keeps its button.
                pass


def install_post_taps(dp):
    dp.callback_query.outer_middleware(PostTaps())
