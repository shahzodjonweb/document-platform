"""Where new people stop on their way to a first document in the bot.

An ad brought 193 people in a day and 50 of them made something; nothing
said where the other 143 stopped. Each step a person reaches is recorded once a
day, so the admin can show how many reached it and how many went on.

Before an account exists (choosing a language, the one-tap check) a person is
known only by a salted hash of their Telegram id, never the id itself.
"""
import hashlib

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

# The steps in the order people meet them. job.accepted and job.succeeded are
# recorded where jobs are, for every channel.
STEPS = ('bot.start', 'bot.language', 'bot.verified', 'bot.home', 'service.chosen', 'gate.shown',
         'gate.joined', 'ai.described', 'job.accepted', 'job.succeeded')
BEFORE_ACCOUNT = ('bot.start', 'bot.language', 'bot.verified')


def visitor(telegram_user_id):
    return hashlib.sha256(f'{settings.SECRET_KEY}:funnel:{telegram_user_id}'.encode()).hexdigest()[:20]


def step(name, *, account=None, telegram_user_id=None, feature=''):
    """Record that someone reached a step, once a day. Never raises."""
    try:
        if account is None and telegram_user_id is None:
            return
        who = str(account.pk) if account is not None else visitor(telegram_user_id)
        if not cache.add(f'funnel:{name}:{who}:{timezone.now():%Y-%m-%d}', 1, 60 * 60 * 26):
            return
        from .models import AnalyticsEvent
        test = settings.DEBUG or bool(getattr(account, 'is_test', False))
        AnalyticsEvent.objects.create(
            account=account, event_type=name, feature_id=feature or '', channel='bot',
            locale=getattr(account, 'locale', '') or 'en', plan_at_event=getattr(account, 'plan', 'free'),
            environment='development' if test else 'production',
            properties={} if account is not None else {'visitor': who})
    except Exception:
        # Counting is never worth a customer's request failing.
        return
