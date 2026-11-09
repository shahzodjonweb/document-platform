"""Invite friends, earn Plus.

A friend counts once they opened the bot with your link and finished a first
task. At most five friends count in a calendar month (Tashkent, like the weekly
limits); the rest wait for the next month, so nothing is lost. Every five
counted friends earn Plus, one month more each time: the first five 1 month,
the next five 2 months, then 3, and so on. A month is 30 days, as when paying.

The months are an ordinary Plus period (apps/commerce/periods.py, provider
'referral'): they follow a paid Plus period, and wait for a paid Premium one to
end, so a reward is never swallowed. They cost nothing and are never money:
the finance report and the customer's payments leave them out.

Friends counted before invitations earned Plus stay in the totals and never
count toward a reward (Referral.counts_toward_reward).

`qualify_referrals` runs every five minutes from the file cleanup, and whenever
someone opens their invitations in the bot or on the web.
"""
from datetime import timedelta

from django.db import transaction
from django.db.models import Exists, Max, OuterRef
from django.utils import timezone

from apps.core.allowance import WEEK_ZONE

STEP = 5
MONTHLY_CAP = 5
PLAN = 'plus'
MONTH_DAYS = 30


def months_for(tier):
    """Plus months the n-th five friends earn: one more each time."""
    return tier


def month_bounds(now=None):
    """The current calendar month in Tashkent: (first day 00:00, next month's first day 00:00)."""
    local = (now or timezone.now()).astimezone(WEEK_ZONE)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, (start + timedelta(days=32)).replace(day=1)


def _ready(inviter=None):
    """Friends not yet counted who have finished a task."""
    from apps.core.models import Job
    from .models import Referral
    query = Referral.objects.filter(status='pending').filter(
        Exists(Job.objects.filter(account_id=OuterRef('invitee_id'), status='succeeded')))
    if inviter is not None:
        query = query.filter(inviter=inviter)
    return query


def qualify_referrals(account=None, now=None):
    """Count the friends who are due, and give the Plus months they earn. Returns how many were counted."""
    inviters = list(_ready(account).values_list('inviter_id', flat=True).distinct())
    return sum(_settle(inviter_id, now) for inviter_id in inviters)


@transaction.atomic
def _settle(inviter_id, now=None):
    from apps.core.models import Account
    from .models import Referral
    now = now or timezone.now()
    # One inviter at a time: the month's room and the rewards are read and
    # written under the inviter's row lock.
    inviter = Account.objects.select_for_update().get(pk=inviter_id)
    start, end = month_bounds(now)
    counted = Referral.objects.filter(inviter=inviter, status='qualified', counts_toward_reward=True,
                                      qualified_at__gte=start, qualified_at__lt=end).count()
    room = max(0, MONTHLY_CAP - counted)
    ready = list(_ready(inviter).order_by('created_at', 'id')[:room]) if room else []
    for referral in ready:
        referral.status, referral.qualified_at = 'qualified', now
        referral.save(update_fields=['status', 'qualified_at'])
    grant_due_rewards(inviter, now)
    return len(ready)


def grant_due_rewards(inviter, now=None):
    """Every step the inviter's counted friends reached and was not yet rewarded. Caller holds the row lock."""
    from .models import Referral, ReferralReward
    now = now or timezone.now()
    counted = Referral.objects.filter(inviter=inviter, status='qualified', counts_toward_reward=True).count()
    earned = ReferralReward.objects.filter(inviter=inviter).aggregate(n=Max('tier'))['n'] or 0
    rewards = []
    while counted >= STEP * (earned + 1):
        earned += 1
        rewards.append(_reward(inviter, earned, now))
    return rewards


def _reward(inviter, tier, now):
    from .models import CommerceAction, OfferVersion, ReferralReward
    from .periods import grant
    months = months_for(tier)
    days = MONTH_DAYS * months
    reward = ReferralReward.objects.create(inviter=inviter, tier=tier, invites=STEP * tier, days=days,
                                           created_at=now, next_attempt_at=now)
    offer, _ = OfferVersion.objects.get_or_create(
        id=f'referral:{PLAN}:{days}',
        defaults={'offer_id': f'referral_{PLAN}', 'version': 'referral-v1', 'kind': 'subscription', 'plan': PLAN,
                  'name': f'{PLAN.title()} · invitation reward', 'period_seconds': days * 86400,
                  'sandbox': False, 'enabled': False})
    snapshot = {'id': offer.id, 'offer_id': offer.offer_id, 'version': offer.version, 'kind': offer.kind,
                'plan': PLAN, 'name': offer.name, 'currency': 'UZS', 'price': 0, 'regular_price': None,
                'discounted': False, 'provider': 'referral', 'period_seconds': days * 86400, 'period_days': days,
                'tier': tier, 'invites': STEP * tier}
    _, period = grant(inviter, PLAN, days, provider='referral', charge=f'referral:{reward.id}', amount=0,
                      currency='UZS', offer=offer, snapshot=snapshot, occurred_at=now, now=now)
    reward.period = period
    reward.save(update_fields=['period'])
    CommerceAction.objects.create(account=inviter, action='referral.rewarded', target=str(reward.id),
                                  metadata={'tier': tier, 'invites': STEP * tier, 'months': months, 'days': days,
                                            'starts_at': period.starts_at.isoformat(),
                                            'ends_at': period.ends_at.isoformat()})
    return reward


def progress(account, now=None):
    """Where someone stands: friends counted, the next reward, and the rewards so far."""
    from .models import Referral, ReferralReward
    now = now or timezone.now()
    sent = Referral.objects.filter(inviter=account)
    counting = sent.filter(status='qualified', counts_toward_reward=True)
    counted = counting.count()
    start, end = month_bounds(now)
    this_month = counting.filter(qualified_at__gte=start, qualified_at__lt=end).count()
    rewards = list(ReferralReward.objects.filter(inviter=account).select_related('period').order_by('tier'))
    tier = (rewards[-1].tier if rewards else 0) + 1
    have = min(STEP, max(0, counted - STEP * (tier - 1)))
    return {
        'step': STEP,
        'monthly_cap': MONTHLY_CAP,
        'counted': counted,
        'counted_this_month': this_month,
        'month_full': this_month >= MONTHLY_CAP,
        'next_month': end,
        'pending': sent.filter(status='pending').count(),
        # Finished a task, but this month's five are already counted.
        'waiting_next_month': _ready(account).count(),
        'qualified_total': sent.filter(status='qualified').count(),
        'next_reward': {'tier': tier, 'months': months_for(tier), 'invites': STEP * tier,
                        'have': have, 'remaining': STEP - have},
        'rewards': [{'tier': r.tier, 'months': months_for(r.tier), 'invites': r.invites, 'days': r.days,
                     'starts_at': r.period.starts_at if r.period else None,
                     'ends_at': r.period.ends_at if r.period else None, 'created_at': r.created_at}
                    for r in rewards],
    }
