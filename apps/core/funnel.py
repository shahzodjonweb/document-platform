"""Where new people stop on their way to a first document in the bot.

An ad brought 193 people in a day and 50 of them made something; nothing
said where the other 143 stopped. Each step a person reaches is recorded once a
day, so the admin can show how many reached it and how many went on.

Before an account exists (choosing a language, the one-tap check) a person is
known only by a salted hash of their Telegram id, never the id itself.

Looks at the plans screen are kept here too (plans_viewed), each one, with
where it was opened from: the owner asked who looks at the plans and what they
do next.
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

# Where the plans screen was opened from: the main menu, the account screen,
# /plans or /buy (typed, from the command menu, or a /plans link tapped in a
# bot message's text, such as the renewal reminder or a closed-payment refusal:
# Telegram sends the same text for all three), a used-up weekly or edit limit,
# the channel gate, a button under a payment message from the bot (a payment
# confirmed, a receipt received, the /paysupport answer, a card plan's renewal
# reminder), the subscription screen, Back on a payment screen. A button from before sources
# were kept says nothing, and anything not on this list is 'other', so the
# admin's breakdown stays short.
PLAN_SOURCES = ('menu', 'account', 'command', 'limit', 'channels', 'notice', 'subscription', 'payment', 'other')
# A double tap sends the same button twice before the screen has changed, and
# each draws the plans again with fresh buttons, so Telegram never answers the
# second with "message is not modified". One button is one look for this long;
# a tap on it later (an old message the bot could not edit keeps its buttons)
# is a look of its own.
DOUBLE_TAP_SECONDS = 10


def visitor(telegram_user_id):
    return hashlib.sha256(f'{settings.SECRET_KEY}:funnel:{telegram_user_id}'.encode()).hexdigest()[:20]


def environment(account):
    """Test accounts, and anything recorded on a development machine, stay out of production reports."""
    return 'development' if settings.DEBUG or bool(getattr(account, 'is_test', False)) else 'production'


def step(name, *, account=None, telegram_user_id=None, feature=''):
    """Record that someone reached a step, once a day. Never raises."""
    try:
        if account is None and telegram_user_id is None:
            return
        who = str(account.pk) if account is not None else visitor(telegram_user_id)
        if not cache.add(f'funnel:{name}:{who}:{timezone.now():%Y-%m-%d}', 1, 60 * 60 * 26):
            return
        from .models import AnalyticsEvent
        AnalyticsEvent.objects.create(
            account=account, event_type=name, feature_id=feature or '', channel='bot',
            locale=getattr(account, 'locale', '') or 'en', plan_at_event=getattr(account, 'plan', 'free'),
            environment=environment(account),
            properties={} if account is not None else {'visitor': who})
    except Exception:
        # Counting is never worth a customer's request failing.
        return


def plans_viewed(account, source=None, tap=''):
    """Record one look at the plans screen in the bot. Never raises.

    Unlike a funnel step, every look is kept, not one a day: the admin shows
    how many people looked and how many times, and someone opening the plans
    five times before paying is worth seeing. `tap` is the button that opened
    it, so a double tap on that button is one look, not two.
    """
    try:
        if tap and not cache.add(f'plans-viewed:{tap}', 1, DOUBLE_TAP_SECONDS):
            return
        from apps.commerce.services import effective_plan
        from .models import AnalyticsEvent
        try:
            # The plan the screen says they have, which a staff assignment or a
            # lapsed period can make differ from the stored one.
            plan = effective_plan(account)
        except Exception:
            plan = getattr(account, 'plan', '') or 'free'
        AnalyticsEvent.objects.create(
            account=account, event_type='plans.viewed', channel='bot',
            locale=getattr(account, 'locale', '') or 'en', plan_at_event=plan,
            environment=environment(account),
            properties={'source': source if source in PLAN_SOURCES else 'other'})
    except Exception:
        # Counting is never worth a customer's request failing.
        return
