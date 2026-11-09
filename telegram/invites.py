"""Invite friends, in the bot: the screen with your link and how far you are,
and the message when Plus months are earned.

The rules live in apps/commerce/referrals.py; this only says them. Dates are on
the reader's clock (telegram/clock.py), except the day new friends count from,
which is the start of a Tashkent month, written as the plans write their days.
"""
import html
from urllib.parse import quote

from aiogram.types import InlineKeyboardButton
from asgiref.sync import sync_to_async
from django.utils import timezone

COPY = {
    'en': {
        'invite_button': '🎁 Invite friends',
        'title': '🎁 <b>Invite friends — get Plus free</b>',
        'rules': 'A friend counts when they open the bot with your link and finish their first task. '
                 'Every {step} friends earn Plus: 1 month for the first {step}, 2 months for the next {step}, '
                 'then 3, and so on. Up to {cap} friends count each month.',
        'link': 'Your link:',
        'code': 'Your invitation code: <code>{code}</code>',
        'progress': 'Next reward: <b>{have} of {step}</b> friends → <b>{months}</b> of Plus',
        'month_full': 'This month’s {cap} friends are counted. New friends count from {day}.',
        'waiting_month': 'Waiting for next month: {count}',
        'waiting': 'Joined, no task finished yet: {count}',
        'earned': 'Earned so far:',
        'reward_line': '• {months} of Plus — until {date}',
        'share': '📤 Share link',
        'share_text': 'Make PDFs, slides and CVs right in Telegram:',
        'rewarded': '🎉 {count} friends joined through your link — you get <b>{months} of Plus</b> free!',
        'active_until': 'Plus is active until {date}.',
        'extended_until': 'Your Plus is extended until {date}.',
        'starts_later': 'It starts after your current plan, on {start}, and lasts until {date}.',
        'next': 'Invite {step} more friends to get {months}.',
        'from_invites': '🎁 From inviting friends',
        'active_label': 'Active until',
    },
    'uz': {
        'invite_button': '🎁 Do‘stlarni taklif qilish',
        'title': '🎁 <b>Do‘stlarni taklif qiling — Plus bepul</b>',
        'rules': 'Do‘stingiz botni havolangiz orqali ochib, birinchi vazifasini bajarganda hisobga olinadi. '
                 'Har {step} do‘st uchun Plus beriladi: birinchi {step} tasi uchun 1 oy, keyingi {step} tasi uchun '
                 '2 oy, keyin 3 oy va hokazo. Bir oyda {cap} tagacha do‘st hisobga olinadi.',
        'link': 'Havolangiz:',
        'code': 'Taklif kodingiz: <code>{code}</code>',
        'progress': 'Keyingi sovg‘a: <b>{have}/{step}</b> do‘st → <b>{months}</b> Plus',
        'month_full': 'Bu oy {cap} ta do‘st hisobga olindi. Yangi do‘stlar {day}dan hisoblanadi.',
        'waiting_month': 'Keyingi oyni kutmoqda: {count}',
        'waiting': 'Qo‘shilgan, hali vazifa bajarmagan: {count}',
        'earned': 'Olingan sovg‘alar:',
        'reward_line': '• {months} Plus — {date} gacha',
        'share': '📤 Havolani ulashish',
        'share_text': 'PDF, slayd va rezyumelarni Telegramda tayyorlang:',
        'rewarded': '🎉 Havolangiz orqali {count} ta do‘st qo‘shildi — sizga <b>{months} Plus</b> bepul!',
        'active_until': 'Plus {date} gacha faol.',
        'extended_until': 'Plus tarifingiz {date} gacha uzaytirildi.',
        'starts_later': 'U joriy tarifingizdan keyin, {start} kuni boshlanadi va {date} gacha davom etadi.',
        'next': 'Yana {step} ta do‘st taklif qiling va {months} oling.',
        'from_invites': '🎁 Do‘stlarni taklif qilganingiz uchun',
        'active_label': 'Faol muddati',
    },
    'ru': {
        'invite_button': '🎁 Пригласить друзей',
        'title': '🎁 <b>Пригласите друзей — получите Plus бесплатно</b>',
        'rules': 'Друг засчитывается, когда откроет бота по вашей ссылке и выполнит первую задачу. '
                 'Каждые {step} друзей дают Plus: 1 месяц за первых {step}, 2 месяца за следующих {step}, '
                 'затем 3 и так далее. В месяц засчитывается до {cap} друзей.',
        'link': 'Ваша ссылка:',
        'code': 'Ваш код приглашения: <code>{code}</code>',
        'progress': 'Следующая награда: <b>{have} из {step}</b> друзей → <b>{months}</b> Plus',
        'month_full': 'В этом месяце засчитано {cap} друзей. Новые друзья засчитаются с {day}.',
        'waiting_month': 'Ждут следующего месяца: {count}',
        'waiting': 'Присоединились, но ещё не выполнили задачу: {count}',
        'earned': 'Уже получено:',
        'reward_line': '• {months} Plus — до {date}',
        'share': '📤 Поделиться ссылкой',
        'share_text': 'PDF, слайды и резюме прямо в Telegram:',
        'rewarded': '🎉 По вашей ссылке пришли {count} друзей — вам <b>{months} Plus</b> бесплатно!',
        'active_until': 'Plus действует до {date}.',
        'extended_until': 'Ваш Plus продлён до {date}.',
        'starts_later': 'Он начнётся после текущего тарифа, {start}, и продлится до {date}.',
        'next': 'Пригласите ещё {step} друзей и получите {months}.',
        'from_invites': '🎁 За приглашённых друзей',
        'active_label': 'Действует до',
    },
}


def copy(locale, key):
    return COPY.get(locale, COPY['en'])[key]


def months_label(months, locale):
    """'1 month' / '2 months', '1 oy', '1 месяц' / '2 месяца' / '5 месяцев'."""
    if locale == 'uz':
        return f'{months} oy'
    if locale == 'ru':
        if months % 10 == 1 and months % 100 != 11:
            word = 'месяц'
        elif 2 <= months % 10 <= 4 and not 12 <= months % 100 <= 14:
            word = 'месяца'
        else:
            word = 'месяцев'
        return f'{months} {word}'
    return f'{months} month' + ('' if months == 1 else 's')


def day(account, value):
    """A day on the reader's clock, as payment messages write it: 09.12.2026."""
    from .clock import local_time
    return local_time(account, value).strftime('%d.%m.%Y')


def month_start_label(value, locale):
    """The day new friends count from, joined the way each language says "from": 1-dekabr|dan."""
    from .clock import day_label
    return day_label(value, locale)


def link_for(account):
    """(link, code): the bot link carrying this person's code, or (None, code) without a bot username."""
    from apps.commerce.providers import telegram_config
    from apps.commerce.services import referral_code
    code = referral_code(account).code
    username = (telegram_config().get('username') or '').strip().lstrip('@')
    return (f'https://t.me/{username}?start=ref_{code}' if username else None), code


def state(account):
    """Count whoever is due, then read where this person stands, with their link."""
    from apps.commerce.referrals import progress
    from apps.commerce.services import qualify_referrals
    qualify_referrals(account)
    link, code = link_for(account)
    return progress(account), link, code


def body(account, data, link, code):
    """The invite screen's text (HTML)."""
    locale = account.locale
    c = COPY.get(locale, COPY['en'])
    step, cap = data['step'], data['monthly_cap']
    lines = [c['title'], '', c['rules'].format(step=step, cap=cap), '']
    if link:
        lines += [c['link'], html.escape(link), '']
    else:
        lines += [c['code'].format(code=html.escape(code)), '']
    nxt = data['next_reward']
    lines.append(c['progress'].format(have=nxt['have'], step=step, months=months_label(nxt['months'], locale)))
    if data['month_full']:
        lines.append(c['month_full'].format(cap=cap, day=month_start_label(data['next_month'], locale)))
    if data['waiting_next_month']:
        lines.append(c['waiting_month'].format(count=data['waiting_next_month']))
    still = data['pending'] - data['waiting_next_month']
    if still > 0:
        lines.append(c['waiting'].format(count=still))
    if data['rewards']:
        lines += ['', c['earned']]
        lines += [c['reward_line'].format(months=months_label(r['months'], locale), date=day(account, r['ends_at']))
                  for r in data['rewards'] if r['ends_at']]
    return '\n'.join(lines)


def share_url(account, link):
    text = copy(account.locale, 'share_text')
    return f'https://t.me/share/url?url={quote(link, safe="")}&text={quote(text, safe="")}'


async def screen(account):
    """(text, share_row): the invite screen, and a Share button row when there is a link to share."""
    data, link, code = await sync_to_async(state)(account)
    rows = [[InlineKeyboardButton(text=copy(account.locale, 'share'), url=share_url(account, link))]] if link else []
    return body(account, data, link, code), rows


async def invite_button(account):
    from .bot import callback
    return InlineKeyboardButton(text=copy(account.locale, 'invite_button'), callback_data=await callback(account, 'invite'))


def reward_message(reward, now=None):
    """The bot message for Plus months earned (HTML)."""
    from apps.commerce.referrals import STEP, months_for
    from apps.commerce.services import active_period
    account = reward.inviter
    locale = account.locale
    c = COPY.get(locale, COPY['en'])
    now = now or timezone.now()
    period = reward.period
    lines = [c['rewarded'].format(count=reward.invites, months=months_label(months_for(reward.tier), locale))]
    if period is not None:
        if period.starts_at <= now:
            lines.append(c['active_until'].format(date=day(account, period.ends_at)))
        else:
            running = active_period(account, now)
            if running is not None and running.plan == period.plan:
                lines.append(c['extended_until'].format(date=day(account, period.ends_at)))
            else:
                lines.append(c['starts_later'].format(start=day(account, period.starts_at),
                                                      date=day(account, period.ends_at)))
    lines.append(c['next'].format(step=STEP, months=months_label(months_for(reward.tier + 1), locale)))
    return '\n'.join(lines)
