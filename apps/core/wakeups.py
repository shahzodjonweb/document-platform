"""Wake a runner the moment there is work for it, instead of at its next look.

The worker looked for queued jobs every second and the bot for finished files
every two: about a second and a half of every job was spent waiting to be
noticed (benchmark of 2026-11-13). Queuing a job, or settling one with a file
for the bot to send, now pushes a token onto a Redis list that its runner
blocks on, with its old look as the timeout. Nothing depends on the token:
without Redis, or with Redis down, runners look on their timer as before, and
a lost token only means the next look finds the work.
"""
import asyncio
import logging
import time

from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)

PREFIX = 'docmaster:wake:'
JOBS = 'jobs'              # the worker, which runs every tool
AI_JOBS = 'jobs:ai'        # the AI lane (runworker --lane ai)
DELIVERIES = 'deliveries'  # the bot's delivery loop
# A token nobody took is gone after this long: the work it announced was found by a look.
TOKEN_SECONDS = 120
# A blocked read is given this long beyond its own timeout before the socket gives up.
SOCKET_GRACE = 3

_clients = {}


def _url():
    return getattr(settings, 'REDIS_URL', '') or ''


def _client(blocking=False):
    url = _url()
    if not url:
        return None
    key = (url, blocking)
    if key not in _clients:
        import redis
        _clients[key] = redis.Redis.from_url(url, socket_connect_timeout=0.25,
                                             socket_timeout=10 + SOCKET_GRACE if blocking else 0.25)
    return _clients[key]


def notify(*names):
    """Wake the runners of `names` now; never raises."""
    try:
        client = _client()
        if client is None or not names:
            return
        pipe = client.pipeline(transaction=False)
        for name in names:
            pipe.rpush(PREFIX + name, 1)
            pipe.expire(PREFIX + name, TOKEN_SECONDS)
        pipe.execute()
    except Exception as exc:
        logger.debug('Wake-up not sent (%s)', type(exc).__name__)


def notify_on_commit(*names):
    """Wake them once the transaction that made the work commits: never before it can be seen."""
    transaction.on_commit(lambda: notify(*names))


def wait(names, seconds, idle=None):
    """Block until one of `names` is woken or `seconds` pass; True when woken.

    Without Redis it sleeps `idle` seconds (default `seconds`), the runner's old
    look. A burst of tokens wakes it once: the look that follows finds them all.
    """
    client = _client(blocking=True)
    if client is None:
        time.sleep(seconds if idle is None else idle)
        return False
    keys = [PREFIX + name for name in names]
    try:
        woken = client.blpop(keys, timeout=seconds)
        if woken:
            client.delete(*keys)
        return bool(woken)
    except Exception as exc:
        logger.debug('Wake-up wait failed (%s)', type(exc).__name__)
        time.sleep(seconds if idle is None else idle)
        return False


_async_clients = {}


async def wait_async(names, seconds):
    """`wait` for an asyncio loop (the bot): woken early, or after `seconds` as before."""
    url = _url()
    if not url:
        await asyncio.sleep(seconds)
        return False
    keys = [PREFIX + name for name in names]
    try:
        loop = asyncio.get_running_loop()
        client = _async_clients.get((url, id(loop)))
        if client is None:
            import redis.asyncio as aioredis
            client = aioredis.Redis.from_url(url, socket_connect_timeout=0.25, socket_timeout=seconds + SOCKET_GRACE)
            _async_clients[(url, id(loop))] = client
        woken = await client.blpop(keys, timeout=seconds)
        if woken:
            await client.delete(*keys)
        return bool(woken)
    except Exception as exc:
        logger.debug('Wake-up wait failed (%s)', type(exc).__name__)
        await asyncio.sleep(seconds)
        return False
