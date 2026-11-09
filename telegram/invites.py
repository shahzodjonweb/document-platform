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

# The rules read as three steps and a ladder of rewards: 1, 2, 3 months for each
# next five friends (apps/commerce/referrals.months_for). Uzbek says "Plus tarifi",
# with the month as "1 oylik" before it (months_label).
COPY = {
    'en': {
        'invite_button': '🎁 Invite friends',
        'gift_button': '🎁 Free gift',
        'referrals_button': '👥 My referrals',
        'title': '🎁 <b>Invite friends — get Plus free!</b>',
        'rules': '<b>How it works</b>\n'
                 '1️⃣ Send your link to friends.\n'
                 '2️⃣ A friend counts once they open the bot with your link and finish their first task.\n'
                 '3️⃣ Every {step} friends earn you Plus free — and the gift grows each time:\n\n'
                 '🥉 First {step} friends → <b>1 month</b> of Plus\n'
                 '🥈 Next {step} friends → <b>2 months</b> of Plus\n'
                 '🥇 The {step} after that → <b>3 months</b> of Plus\n'
                 '…and so on!\n\n'
                 'ℹ️ Up to {cap} friends count each month. The rest count next month — none are lost.',
        'link': '🔗 <b>Your link:</b>',
        'code': '🔑 Your invitation code: <code>{code}</code>',
        'progress': '📊 Next gift: <b>{have} of {step}</b> friends → <b>{months} of Plus</b>',
        'month_full': '⏳ This month’s {cap} friends are counted. New friends count from {day}.',
        'waiting_month': '🕓 Counting next month: {count}',
        'waiting': '👋 Joined, no task finished yet: {count}',
        'earned': '🏆 <b>Earned so far:</b>',
        'reward_line': '• {months} of Plus — until {date}',
        'share': '📤 Share link',
        'share_text': 'Make PDFs, slides and CVs right in Telegram:',
        'rewarded': '🎉 <b>Congratulations!</b> {count} friends joined through your link — '
                    'you get <b>{months} of Plus</b> free!',
        'active_until': 'Plus is active until {date}.',
        'extended_until': 'Your Plus is extended until {date}.',
        'starts_later': 'It starts after your current plan, on {start}, and lasts until {date}.',
        'next': '👉 Invite {step} more friends — the next gift is <b>{months} of Plus</b>!',
        'from_invites': '🎁 A gift for inviting friends',
        'active_label': 'Active until',
    },
    'uz': {
        'invite_button': '🎁 Do‘stlarni taklif qilish',
        'gift_button': '🎁 Bepul sovg‘a',
        'referrals_button': '👥 Referallarim',
        'title': '🎁 <b>Do‘stlaringizni taklif qiling va Plus tarifini bepul oling!</b>',
        'rules': '<b>Qanday ishlaydi?</b>\n'
                 '1️⃣ Havolangizni do‘stlaringizga yuboring.\n'
                 '2️⃣ Do‘stingiz botni shu havola orqali ochib, birinchi vazifasini bajarsa, u hisobga olinadi.\n'
                 '3️⃣ Har {step} ta do‘st uchun Plus tarifini bepul olasiz — sovg‘a har safar kattaroq:\n\n'
                 '🥉 Dastlabki {step} ta do‘st → <b>1 oylik</b> Plus tarifi\n'
                 '🥈 Keyingi {step} ta do‘st → <b>2 oylik</b> Plus tarifi\n'
                 '🥇 Undan keyingi {step} ta do‘st → <b>3 oylik</b> Plus tarifi\n'
                 '…va hokazo!\n\n'
                 'ℹ️ Har oy {cap} tagacha do‘st hisobga olinadi. Qolganlari keyingi oyga o‘tadi — '
                 'hech biri behuda ketmaydi.',
        'link': '🔗 <b>Sizning havolangiz:</b>',
        'code': '🔑 Taklif kodingiz: <code>{code}</code>',
        'progress': '📊 Keyingi sovg‘a: <b>{have}/{step}</b> do‘st → <b>{months} Plus tarifi</b>',
        'month_full': '⏳ Bu oy uchun {cap} ta o‘rin to‘ldi. Yangi do‘stlar {day}dan boshlab hisobga olinadi.',
        'waiting_month': '🕓 Keyingi oyda hisobga olinadi: {count} ta do‘st',
        'waiting': '👋 Qo‘shildi, lekin hali vazifa bajarmadi: {count} ta do‘st',
        'earned': '🏆 <b>Olgan sovg‘alaringiz:</b>',
        'reward_line': '• {months} Plus tarifi — {date} gacha',
        'share': '📤 Do‘stlarga ulashish',
        'share_text': 'PDF, slayd va rezyumelarni to‘g‘ridan-to‘g‘ri Telegramda tayyorlang:',
        'rewarded': '🎉 <b>Tabriklaymiz!</b> Havolangiz orqali {count} ta do‘st qo‘shildi — '
                    'sizga <b>{months} Plus tarifi</b> sovg‘a qilindi!',
        'active_until': 'Plus tarifi {date} gacha faol.',
        'extended_until': 'Plus tarifingiz {date} gacha uzaytirildi.',
        'starts_later': 'Sovg‘a joriy tarifingiz tugagach, {start} kuni boshlanadi va {date} gacha amal qiladi.',
        'next': '👉 Yana {step} ta do‘st taklif qiling — keyingi sovg‘a: <b>{months} Plus tarifi</b>!',
        'from_invites': '🎁 Do‘stlarni taklif qilganingiz uchun sovg‘a',
        'active_label': 'Amal qilish muddati',
    },
    'ru': {
        'invite_button': '🎁 Пригласить друзей',
        'gift_button': '🎁 Бесплатный подарок',
        'referrals_button': '👥 Мои рефералы',
        'title': '🎁 <b>Приглашайте друзей — получайте тариф Plus бесплатно!</b>',
        'rules': '<b>Как это работает</b>\n'
                 '1️⃣ Отправьте свою ссылку друзьям.\n'
                 '2️⃣ Друг засчитывается, когда откроет бота по вашей ссылке и выполнит первую задачу.\n'
                 '3️⃣ За каждых {step} друзей — тариф Plus бесплатно, и с каждым разом подарок больше:\n\n'
                 '🥉 Первые {step} друзей → <b>1 месяц</b> тарифа Plus\n'
                 '🥈 Следующие {step} друзей → <b>2 месяца</b> тарифа Plus\n'
                 '🥇 Ещё {step} друзей → <b>3 месяца</b> тарифа Plus\n'
                 '…и так далее!\n\n'
                 'ℹ️ В месяц засчитывается до {cap} друзей. Остальные засчитаются в следующем месяце — '
                 'никто не потеряется.',
        'link': '🔗 <b>Ваша ссылка:</b>',
        'code': '🔑 Ваш код приглашения: <code>{code}</code>',
        'progress': '📊 Следующий подарок: <b>{have} из {step}</b> друзей → <b>{months} тарифа Plus</b>',
        'month_full': '⏳ В этом месяце уже засчитано {cap} друзей. Новые друзья засчитаются с {day}.',
        'waiting_month': '🕓 Засчитаются в следующем месяце: {count}',
        'waiting': '👋 Пришли, но ещё не выполнили задачу: {count}',
        'earned': '🏆 <b>Ваши подарки:</b>',
        'reward_line': '• {months} тарифа Plus — до {date}',
        'share': '📤 Поделиться ссылкой',
        'share_text': 'PDF, слайды и резюме прямо в Telegram:',
        'rewarded': '🎉 <b>Поздравляем!</b> По вашей ссылке пришли {count} друзей — '
                    'дарим вам <b>{months} тарифа Plus</b>!',
        'active_until': 'Тариф Plus действует до {date}.',
        'extended_until': 'Ваш тариф Plus продлён до {date}.',
        'starts_later': 'Подарок начнётся после текущего тарифа, {start}, и продлится до {date}.',
        'next': '👉 Пригласите ещё {step} друзей — следующий подарок: <b>{months} тарифа Plus</b>!',
        'from_invites': '🎁 Подарок за приглашённых друзей',
        'active_label': 'Действует до',
    },
}


def copy(locale, key):
    return COPY.get(locale, COPY['en'])[key]


def months_label(months, locale):
    """'1 month' / '2 months'; Uzbek '1 oylik', said before "Plus tarifi"; '1 месяц' / '2 месяца' / '5 месяцев'."""
    if locale == 'uz':
        return f'{months} oylik'
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
    have = max(0, min(nxt['have'], step))
    lines.append('🟩' * have + '⬜' * (step - have))
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


async def view(account):
    """(text, rows): the whole Invite friends screen with its Account and Home
    buttons. /invite, the menus' buttons and a post's button all show this one."""
    from .bot import button
    body, share = await screen(account)
    return body, [*share, [await button(account, 'account', 'account'), await button(account, 'home', 'home')]]


async def invite_button(account, label='invite_button'):
    from .bot import callback
    return InlineKeyboardButton(text=copy(account.locale, label), callback_data=await callback(account, 'invite'))


async def home_row(account):
    """Free gift and My referrals on the main menu: two ways into the same invite screen."""
    return [await invite_button(account, 'gift_button'), await invite_button(account, 'referrals_button')]


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
