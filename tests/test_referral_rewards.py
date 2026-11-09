"""Invite friends, earn Plus.

Every 5 counted friends earn Plus, one month more each time (1, 2, 3 …); a
friend counts after finishing a first task, at most 5 a Tashkent month; only
friends counted from launch on count. The months are an ordinary Plus period
that is never money.
"""
import asyncio
import itertools
from datetime import timedelta
from importlib import import_module
from unittest.mock import AsyncMock, Mock

import pytest
from django.apps import apps as django_apps
from django.test import Client, RequestFactory
from django.utils import timezone

from apps.commerce import manual, referrals, services
from apps.commerce.models import CommerceAction, Payment, Referral, ReferralReward, Subscription, SubscriptionPeriod
from apps.core.identity import resolve_account
from apps.core.models import BotConversation, Job, Quote
from apps.core.policy import usage_snapshot
from telegram import invites
from telegram.local import dispatch_local
from tests.test_manual_payments import configure, finance, paid, submitted

pytestmark = pytest.mark.django_db
_numbers = itertools.count(830000)


def account(is_test=True, locale='en'):
    number = next(_numbers)
    a = resolve_account({'id': number, 'first_name': f'Person {number}', 'language_code': locale}, is_test=is_test)
    if a.locale != locale:
        a.locale = locale
        a.save(update_fields=['locale'])
    return a


def finish_task(a):
    quote = Quote.objects.create(account=a, feature_id='pdf.merge', expires_at=timezone.now())
    Job.objects.create(account=a, quote=quote, feature_id='pdf.merge', status='succeeded',
                       idempotency_key=str(quote.id), request_hash='x')


def friends(inviter, count, done=True):
    code = services.referral_code(inviter).code
    made = []
    for _ in range(count):
        friend = account(inviter.is_test)
        services.claim_referral(friend, code)
        if done:
            finish_task(friend)
        made.append(friend)
    return made


def weekly(a):
    usage = usage_snapshot(a)
    return usage['plan'], usage['ai_documents']['limit'], usage['file_jobs']['limit'], usage['edits_per_file']


def bot_named(monkeypatch, username='pdfmaster_test_bot'):
    from apps.commerce import providers
    configured = providers.telegram_config
    monkeypatch.setattr(providers, 'telegram_config', lambda: {**configured(), 'username': username})


def client_for(a):
    c = Client()
    session = c.session
    session['customer_account_id'] = str(a.id)
    session.save()
    return c


def test_five_friends_who_finished_a_task_earn_a_month_of_plus():
    inviter = account()
    friends(inviter, 4)
    friends(inviter, 3, done=False)
    assert services.qualify_referrals() == 4
    assert not ReferralReward.objects.exists() and weekly(inviter)[0] == 'free'
    assert referrals.progress(inviter)['next_reward'] == {'tier': 1, 'months': 1, 'invites': 5, 'have': 4, 'remaining': 1}

    friends(inviter, 1)
    before = timezone.now()
    assert services.qualify_referrals(inviter) == 1
    reward = ReferralReward.objects.get()
    assert (reward.tier, reward.invites, reward.days, reward.status) == (1, 5, 30, 'pending')
    assert weekly(inviter) == ('plus', 20, None, 10), 'the weekly limits of Plus come with it'
    period = reward.period
    assert period.plan == 'plus' and before <= period.starts_at <= timezone.now()
    assert period.ends_at - period.starts_at == timedelta(days=30)
    payment = Payment.objects.get(account=inviter)
    assert (payment.provider, payment.amount_xtr, payment.currency, payment.plan) == ('referral', 0, 'UZS', 'plus')
    assert Subscription.objects.get(account=inviter).provider == 'referral'
    assert CommerceAction.objects.get(account=inviter, action='referral.rewarded').metadata['months'] == 1

    # Counting again changes nothing: one reward per step.
    assert services.qualify_referrals() == 0 and ReferralReward.objects.count() == 1
    state = referrals.progress(inviter)
    assert state['counted'] == 5 and state['pending'] == 3
    assert state['next_reward'] == {'tier': 2, 'months': 2, 'invites': 10, 'have': 0, 'remaining': 5}


def test_each_step_earns_a_month_more_and_five_friends_count_a_month():
    inviter = account()
    friends(inviter, 16)
    first = timezone.now()
    assert services.qualify_referrals(now=first) == 5, 'five a month'
    state = referrals.progress(inviter, first)
    assert state['month_full'] and state['waiting_next_month'] == 11 and state['counted_this_month'] == 5
    assert state['next_month'] == referrals.month_bounds(first)[1]

    second = referrals.month_bounds(first)[1] + timedelta(hours=1)
    assert services.qualify_referrals(now=second) == 5
    third = referrals.month_bounds(second)[1] + timedelta(hours=1)
    assert services.qualify_referrals(now=third) == 5
    rewards = list(ReferralReward.objects.filter(inviter=inviter).order_by('tier'))
    assert [(r.tier, r.invites, r.days) for r in rewards] == [(1, 5, 30), (2, 10, 60), (3, 15, 90)]
    # Laid end to end: a reward never cuts short the months already earned.
    for earlier, later, at in zip(rewards, rewards[1:], (second, third)):
        assert later.period.starts_at == max(earlier.period.ends_at, at)
        assert later.period.ends_at - later.period.starts_at == timedelta(days=later.days)
    assert Subscription.objects.get(account=inviter).current_period_end == rewards[-1].period.ends_at
    fourth = referrals.month_bounds(third)[1] + timedelta(hours=1)
    assert services.qualify_referrals(now=fourth) == 1
    assert referrals.progress(inviter, fourth)['next_reward'] == {'tier': 4, 'months': 4, 'invites': 20, 'have': 1, 'remaining': 4}


def test_the_month_is_tashkents():
    # 30 Nov 20:00 UTC is already 1 December in Tashkent.
    from datetime import datetime, timezone as dt_timezone
    start, end = referrals.month_bounds(datetime(2026, 11, 30, 20, 0, tzinfo=dt_timezone.utc))
    assert (start.month, start.day, start.hour, end.month, end.day) == (12, 1, 0, 1, 1)
    assert start.utcoffset() == timedelta(hours=5)


def test_only_friends_counted_from_launch_count():
    inviter = account()
    early = friends(inviter, 5)
    Referral.objects.filter(invitee__in=early).update(status='qualified', qualified_at=timezone.now())
    friends(inviter, 2)
    migration = import_module('apps.commerce.migrations.0005_referral_rewards')
    migration.counted_before_rewards(django_apps, None)
    assert Referral.objects.filter(counts_toward_reward=False).count() == 5, 'only those already counted'
    assert services.qualify_referrals() == 2, 'friends counted before launch take no room in the month'
    assert not ReferralReward.objects.exists()
    state = referrals.progress(inviter)
    assert (state['counted'], state['qualified_total'], state['counted_this_month']) == (2, 7, 2)
    friends(inviter, 3)
    services.qualify_referrals()
    assert ReferralReward.objects.get().tier == 1


def test_a_reward_follows_paid_plus_and_waits_for_paid_premium():
    plus = account()
    paid(plus, 'plus')
    paid_period = SubscriptionPeriod.objects.get(account=plus)
    friends(plus, 5)
    services.qualify_referrals()
    reward = ReferralReward.objects.get(inviter=plus)
    assert reward.period.starts_at == paid_period.ends_at and reward.period.ends_at == paid_period.ends_at + timedelta(days=30)
    subscription = Subscription.objects.get(account=plus)
    assert subscription.provider == 'manual', 'still a card subscription: someone paid'
    assert subscription.current_period_end == reward.period.ends_at
    assert invites.reward_message(reward).count('extended until') == 1

    premium = account()
    paid(premium, 'premium')
    premium_period = SubscriptionPeriod.objects.get(account=premium)
    friends(premium, 5)
    services.qualify_referrals()
    reward = ReferralReward.objects.get(inviter=premium)
    assert reward.period.starts_at == premium_period.ends_at, 'not swallowed by Premium'
    assert weekly(premium)[0] == 'premium'
    assert 'starts after your current plan' in invites.reward_message(reward)

    # Paying by card after a reward makes it a card subscription again.
    rewarded = account()
    friends(rewarded, 5)
    services.qualify_referrals()
    reward = ReferralReward.objects.get(inviter=rewarded)
    paid(rewarded, 'plus')
    card = SubscriptionPeriod.objects.filter(account=rewarded, payment__provider='manual').get()
    assert card.starts_at == reward.period.ends_at
    subscription = Subscription.objects.get(account=rewarded)
    assert subscription.provider == 'manual' and subscription.current_period_end == card.ends_at


def test_free_months_are_never_money():
    from operations.commerce_views import financial_report
    from operations.metrics import Filters
    configure()
    inviter = account(is_test=False)
    friends(inviter, 5)
    services.qualify_referrals()
    assert weekly(inviter)[0] == 'plus'
    payer = account(is_test=False)
    manual.approve(submitted(payer).id, finance())
    report = financial_report(Filters.from_request(RequestFactory().get('/ops/payments', {'environment': 'production'})))
    assert report['totals'] == {'uzs_gross': 60_000, 'uzs_refunds': 0, 'uzs_net': 60_000, 'payers': 1, 'paid': 1,
                                'first': 1, 'manual_pending': 0}
    assert [row.account_id for row in report['rows']] == [payer.id]
    assert client_for(inviter).get('/api/v1/billing/transactions').json()['results'] == []


def test_the_api_says_where_someone_stands(monkeypatch):
    bot_named(monkeypatch)
    inviter = account()
    friends(inviter, 5)
    friends(inviter, 1, done=False)
    data = client_for(inviter).get('/api/v1/referrals').json()
    code = services.referral_code(inviter).code
    assert data['url'] == f'https://t.me/pdfmaster_test_bot?start=ref_{code}'
    assert (data['step'], data['monthly_cap'], data['counted'], data['pending_count'], data['rewards_count']) == (5, 5, 5, 1, 5)
    assert data['next_reward'] == {'tier': 2, 'months': 2, 'invites': 10, 'have': 0, 'remaining': 5}
    assert data['month_full'] is True and data['waiting_next_month'] == 0 and 'expires_in_days' not in data
    [reward] = data['rewards']
    assert (reward['tier'], reward['months'], reward['invites'], reward['days']) == (1, 1, 5, 30)
    assert reward['starts_at'] and reward['ends_at']


def test_the_cleanup_counts_friends_and_gives_the_months():
    from apps.core.services import cleanup_expired
    inviter = account()
    friends(inviter, 5)
    cleanup_expired()
    assert ReferralReward.objects.filter(inviter=inviter).exists()


@pytest.mark.parametrize('locale, months, more', [
    ('en', '1 month of Plus', 'Invite 5 more friends to get 2 months.'),
    ('uz', '1 oy Plus', 'Yana 5 ta do‘st taklif qiling va 2 oy oling.'),
    ('ru', '1 месяц Plus', 'Пригласите ещё 5 друзей и получите 2 месяца.'),
])
def test_the_reward_message_in_each_language(locale, months, more):
    inviter = account(locale=locale)
    inviter.time_zone = 'Asia/Tashkent'
    inviter.save(update_fields=['time_zone'])
    friends(inviter, 5)
    services.qualify_referrals()
    reward = ReferralReward.objects.get()
    text = invites.reward_message(reward)
    ends = invites.day(inviter, reward.period.ends_at)
    assert months in text and more in text and ends in text and '5' in text


def test_russian_and_english_months_agree_with_their_number():
    assert [invites.months_label(n, 'ru') for n in (1, 2, 5, 11, 21, 22)] == [
        '1 месяц', '2 месяца', '5 месяцев', '11 месяцев', '21 месяц', '22 месяца']
    assert [invites.months_label(n, 'en') for n in (1, 3)] == ['1 month', '3 months']


@pytest.mark.django_db(transaction=True)
def test_the_reward_message_is_sent_once():
    from telegram.referral_notices import drain
    inviter = account()
    friends(inviter, 5)
    services.qualify_referrals()
    bot = Mock(send_message=AsyncMock(return_value=Mock(message_id=77)))
    asyncio.run(drain(bot))
    asyncio.run(drain(bot))
    assert bot.send_message.await_count == 1
    chat, text = bot.send_message.await_args.args
    assert chat == inviter.telegram_user_id and '1 month of Plus' in text
    markup = bot.send_message.await_args.kwargs['reply_markup']
    assert markup.inline_keyboard[0][0].text == '🎁 Invite friends'
    reward = ReferralReward.objects.get()
    assert (reward.status, reward.message_id) == ('delivered', 77)


@pytest.mark.django_db(transaction=True)
def test_a_test_account_is_never_messaged_over_the_real_telegram():
    from aiogram.client.session.aiohttp import AiohttpSession
    from telegram.referral_notices import drain
    inviter = account(is_test=True)
    friends(inviter, 5)
    services.qualify_referrals()
    bot = Mock(session=AiohttpSession(), send_message=AsyncMock())
    asyncio.run(drain(bot))
    assert not bot.send_message.await_count
    assert ReferralReward.objects.get().status == 'blocked'


@pytest.fixture
def chat(settings, bot_verification_disabled):
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    a = account()
    BotConversation.objects.create(telegram_user_id=a.telegram_user_id, locale='en', language_selected_at=timezone.now())
    return a


@pytest.mark.django_db(transaction=True)
def test_the_invite_screen_in_the_bot(chat, monkeypatch):
    from telegram.commands import COMMANDS, COMMANDS_VERSION
    assert COMMANDS_VERSION == 5 and all('invite' in COMMANDS[locale] for locale in ('en', 'uz', 'ru'))
    bot_named(monkeypatch)
    friends(chat, 3)
    friends(chat, 1, done=False)
    shown = dispatch_local(chat, text='/invite')['messages'][-1]
    code = services.referral_code(chat).code
    assert f'https://t.me/pdfmaster_test_bot?start=ref_{code}' in shown['text']
    assert '3 of 5' in shown['text'] and '1 month' in shown['text'] and 'no task finished yet: 1' in shown['text']
    labels = [button['label'] for row in shown['buttons'] for button in row]
    assert labels[0] == '📤 Share link'
    share = shown['buttons'][0][0]['url']
    assert share.startswith('https://t.me/share/url?url=https%3A%2F%2Ft.me%2Fpdfmaster_test_bot')

    # The account screen leads here too.
    account_screen = dispatch_local(chat, text='/account')['messages'][-1]
    invite = next(b for row in account_screen['buttons'] for b in row if b['label'] == '🎁 Invite friends')
    result = dispatch_local(chat, callback_data=invite['callback_data'])['messages']
    # The account screen becomes the invite screen in place.
    assert '3 of 5' in next(m for m in result if m['id'] == account_screen['id'])['text']

    friends(chat, 2)
    shown = dispatch_local(chat, text='/invite')['messages'][-1]['text']
    assert 'Earned so far:' in shown and '1 month of Plus — until' in shown
    assert 'This month’s 5 friends are counted.' in shown
    subscription = dispatch_local(chat, text='/subscription')['messages'][-1]['text']
    assert 'Active until' in subscription and '🎁 From inviting friends' in subscription
    assert 'Paid access until' not in subscription


@pytest.mark.parametrize('lang, title', [('en', 'Invitations'), ('uz', 'Takliflar'), ('ru', 'Приглашения')])
def test_the_admin_shows_the_invitations_on_the_account_page(lang, title):
    from tests.test_manual_payments import staff_client
    inviter = account()
    friends(inviter, 6)
    friends(inviter, 1, done=False)
    services.qualify_referrals()
    client, _ = staff_client('Support')
    page = client.get(f'/ops/users/{inviter.id}?lang={lang}').content.decode()
    assert f'<h2>{title}</h2>' in page and 'id="invites"' in page
    reward = ReferralReward.objects.get()
    assert f'<td class="mono">{reward.days}</td>' in page
    if lang == 'en':
        assert '0 of 5 friends → Plus for 60 days' in page and '5 / 5' in page
