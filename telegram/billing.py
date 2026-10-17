"""Plans, card transfers and the subscription in the bot.

Prices, discounts included, come from apps.commerce.pricing; the financial
decisions stay in apps.commerce. Card transfer in so'm is the only way to pay.
"""
import html

from asgiref.sync import sync_to_async
from aiogram import F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from django.utils import timezone

from apps.core import funnel
from apps.core.errors import DomainError
from apps.core.models import BotCallback, BotConversation
from apps.commerce.serializers import subscription_data

from .clock import day_label, stamp

COPY = {
    'en': {
        "card_pay": "💳 {plan} · {price} so'm / 30 days",
        "card_pay_discount": "💳 {plan} −{percent}% · {price} so'm / 30 days",
        "card_intro": "💳 Pay by card transfer\nPick a plan. You send the money from your bank app, send us the receipt, and we switch your plan on after checking it.",
        "automatic_soon": "⚡ Automatic payment — coming soon",
        "manual_screen": "<b>💳 {plan} — {price} so'm for 30 days</b>{note}\n\n1. Send exactly <b>{price} so'm</b> to this card:\n<code>{card}</code>\n{holder}\n\n2. Tap «I've paid» and send the receipt here as a photo or PDF.\n\nPayment code: <code>{reference}</code>\nWe check every payment by hand, usually within a few hours, and message you here.",
        "manual_discount": "\nRegular price <s>{regular} so'm</s> · −{percent}% until {until}",
        "manual_waiting": "⏳ Payment {reference} ({plan}, {price} so'm) is waiting for our check. We'll message you here.",
        "manual_paid": "📎 I've paid — send receipt",
        "manual_resend": "📎 Send another receipt",
        "manual_cancel": "✖ Cancel payment",
        "manual_send_receipt": "📎 Send the receipt here as a photo or PDF. A screenshot from your bank app is fine.",
        "manual_received": "✅ Receipt received. We'll check the transfer and message you here, usually within a few hours.",
        "manual_cancelled": "Payment cancelled. Nothing was charged.",
        "manual_approved": "✅ Payment confirmed! {plan} is active until {date}. Thank you!",
        "manual_rejected": "⚠️ We couldn't confirm payment {reference}: {reason}\nIf you did pay, write to us: /paysupport",
        "manual_reminder": "⏰ Your {plan} plan ends on {date}. To keep it, pay again: /plans",
        "myid": "Your Telegram ID: <code>{id}</code>",
        'unavailable': 'Payments aren’t ready yet. You can keep using your current plan.',
        'active_until': 'Paid access until',
        'payment_support': '💬 Payment support', 'home': '🏠 Main menu', 'back': '← Back',
        'plans': '⭐ Plans', 'subscription': '💳 Subscription', 'free': 'Free',
        'no_subscription': 'You’re on Free. No paid subscription to manage.',
        'plan_without_subscription': 'Your plan: <b>{plan}</b>. It isn’t a paid subscription, so there is nothing to renew or cancel.',
        'expired': 'Your subscription has ended. Pick a plan to continue.',
    },
    'uz': {
        "card_pay": "💳 {plan} · {price} so'm / 30 kun",
        "card_pay_discount": "💳 {plan} −{percent}% · {price} so'm / 30 kun",
        "card_intro": "💳 Karta orqali to‘lov\nTarifni tanlang. Pulni bank ilovangizdan o‘tkazasiz, kvitansiyani yuborasiz, tekshirgach tarifingizni yoqamiz.",
        "automatic_soon": "⚡ Avtomatik to‘lov — tez orada",
        "manual_screen": "<b>💳 {plan} — 30 kun uchun {price} so'm</b>{note}\n\n1. Shu kartaga aynan <b>{price} so'm</b> o‘tkazing:\n<code>{card}</code>\n{holder}\n\n2. «To‘ladim» tugmasini bosing va kvitansiyani shu yerga rasm yoki PDF qilib yuboring.\n\nTo‘lov kodi: <code>{reference}</code>\nHar bir to‘lovni qo‘lda tekshiramiz, odatda bir necha soat ichida, va shu yerga yozamiz.",
        "manual_discount": "\nOdatdagi narx <s>{regular} so'm</s> · −{percent}% chegirma, {until}gacha",
        "manual_waiting": "⏳ {reference} to‘lovi ({plan}, {price} so'm) tekshiruvni kutmoqda. Natijani shu yerga yozamiz.",
        "manual_paid": "📎 To‘ladim — kvitansiya yuborish",
        "manual_resend": "📎 Boshqa kvitansiya yuborish",
        "manual_cancel": "✖ To‘lovni bekor qilish",
        "manual_send_receipt": "📎 Kvitansiyani shu yerga rasm yoki PDF qilib yuboring. Bank ilovasidan skrinshot ham bo‘ladi.",
        "manual_received": "✅ Kvitansiya qabul qilindi. O‘tkazmani tekshirib, odatda bir necha soat ichida shu yerga yozamiz.",
        "manual_cancelled": "To‘lov bekor qilindi. Hech narsa yechilmadi.",
        "manual_approved": "✅ To‘lov tasdiqlandi! {plan} tarifi {date} gacha faol. Rahmat!",
        "manual_rejected": "⚠️ {reference} to‘lovini tasdiqlay olmadik: {reason}\nAgar to‘lagan bo‘lsangiz, bizga yozing: /paysupport",
        "manual_reminder": "⏰ {plan} tarifingiz {date} kuni tugaydi. Davom ettirish uchun qayta to‘lang: /plans",
        "myid": "Telegram ID: <code>{id}</code>",
        'unavailable': 'To‘lov hozircha ishlamayapti. Joriy tarifdan foydalanishingiz mumkin.',
        'active_until': 'Pullik tarif muddati',
        'payment_support': '💬 To‘lov bo‘yicha yordam', 'home': '🏠 Bosh menyu', 'back': '← Orqaga',
        'plans': '⭐ Tariflar', 'subscription': '💳 Obuna', 'free': 'Bepul',
        'no_subscription': 'Siz Bepul tarifdasiz. Pullik obunangiz yo‘q.',
        'plan_without_subscription': 'Tarifingiz: <b>{plan}</b>. Bu pullik obuna emas, shuning uchun uzaytirish yoki bekor qilish kerak emas.',
        'expired': 'Obunangiz tugagan. Davom etish uchun tarif tanlang.',
    },
    'ru': {
        "card_pay": "💳 {plan} · {price} сум / 30 дней",
        "card_pay_discount": "💳 {plan} −{percent}% · {price} сум / 30 дней",
        "card_intro": "💳 Оплата переводом на карту\nВыберите тариф. Вы переводите деньги из своего банковского приложения, присылаете квитанцию, и после проверки мы включаем тариф.",
        "automatic_soon": "⚡ Автоматическая оплата — скоро",
        "manual_screen": "<b>💳 {plan} — {price} сум за 30 дней</b>{note}\n\n1. Переведите ровно <b>{price} сум</b> на эту карту:\n<code>{card}</code>\n{holder}\n\n2. Нажмите «Я оплатил» и отправьте сюда квитанцию фото или PDF.\n\nКод платежа: <code>{reference}</code>\nМы проверяем каждый платёж вручную, обычно в течение нескольких часов, и напишем вам здесь.",
        "manual_discount": "\nОбычная цена <s>{regular} сум</s> · −{percent}% до {until}",
        "manual_waiting": "⏳ Платёж {reference} ({plan}, {price} сум) ждёт проверки. Мы напишем вам здесь.",
        "manual_paid": "📎 Я оплатил — отправить квитанцию",
        "manual_resend": "📎 Отправить другую квитанцию",
        "manual_cancel": "✖ Отменить платёж",
        "manual_send_receipt": "📎 Отправьте сюда квитанцию фото или PDF. Скриншот из банковского приложения подойдёт.",
        "manual_received": "✅ Квитанция получена. Проверим перевод и напишем вам здесь, обычно в течение нескольких часов.",
        "manual_cancelled": "Платёж отменён. Ничего не списано.",
        "manual_approved": "✅ Оплата подтверждена! Тариф {plan} действует до {date}. Спасибо!",
        "manual_rejected": "⚠️ Не удалось подтвердить платёж {reference}: {reason}\nЕсли вы оплатили, напишите нам: /paysupport",
        "manual_reminder": "⏰ Ваш тариф {plan} заканчивается {date}. Чтобы продолжить, оплатите снова: /plans",
        "myid": "Ваш Telegram ID: <code>{id}</code>",
        'unavailable': 'Оплата пока недоступна. Текущий тариф продолжает работать.',
        'active_until': 'Оплачено до',
        'payment_support': '💬 Помощь по оплате', 'home': '🏠 Главное меню', 'back': '← Назад',
        'plans': '⭐ Тарифы', 'subscription': '💳 Подписка', 'free': 'Бесплатный',
        'no_subscription': 'У вас бесплатный тариф. Платной подписки нет.',
        'plan_without_subscription': 'Ваш тариф: <b>{plan}</b>. Это не платная подписка, продлевать или отменять нечего.',
        'expired': 'Подписка закончилась. Выберите тариф, чтобы продолжить.',
    },
}


# What each plan includes, written from the live plan settings so an edit in
# the admin is what customers read. People choose a plan by what it gives them,
# so the plans screen leads with this and only then says how to pay. Plans
# differ only in the three weekly counts and the channels: file sizes, page
# and slide counts and the tools are the same on every plan, so a card never
# lists them, and nobody is sold a plan on them.
#
# A discount is the regular price struck through, the price to pay, and how
# much off until which day: no countdown and no "last chance". The discount
# line is its own line under the head, not one of the bullets, which are the
# plan's limits and nothing else.
PLAN_COPY = {
    'en': {
        'title': '<b>📋 Plans</b>',
        'current': 'Your plan: <b>{plan}</b>',
        'head_free': "<b>{icon} {name}</b> — 0 so'm",
        'head': "<b>{icon} {name}</b> — {price} so'm / 30 days",
        'head_discount': "<b>{icon} {name}</b> — <s>{regular}</s> <b>{price}</b> so'm / 30 days",
        'discount_line': '−{percent}% until {until}',
        'yours': ' · ✅ yours',
        'ai_week': 'AI documents and decks: {n} a week',
        'ai_unlimited': 'AI documents and decks: unlimited',
        'edits': 'AI edits: {n} per file',
        'edits_unlimited': 'AI edits: unlimited',
        'files_week': 'File tools, Image → PDF included: {n} tasks a week',
        'files_unlimited': 'File tools: unlimited',
        'no_channels': 'No channel subscription needed',
        'every_tool': '✅ Every plan includes every tool.',
        'how': '<b>How to pay</b>\n1. Choose a plan below.\n2. Send the amount from your bank app to the card shown.\n'
               '3. Send the receipt here. We switch your plan on after checking, usually within a few hours.',
    },
    'uz': {
        'title': '<b>📋 Tariflar</b>',
        'current': 'Hozirgi tarifingiz: <b>{plan}</b>',
        'head_free': "<b>{icon} {name}</b> — 0 so'm",
        'head': "<b>{icon} {name}</b> — 30 kun uchun {price} so'm",
        'head_discount': "<b>{icon} {name}</b> — 30 kun uchun <s>{regular}</s> <b>{price}</b> so'm",
        'discount_line': '−{percent}% chegirma, {until}gacha',
        'yours': ' · ✅ sizniki',
        'ai_week': 'AI hujjat va taqdimotlar: haftasiga {n} ta',
        'ai_unlimited': 'AI hujjat va taqdimotlar: cheksiz',
        'edits': 'AI tahrirlar: har bir faylga {n} ta',
        'edits_unlimited': 'AI tahrirlar: cheksiz',
        'files_week': 'Fayl vositalari, Rasmlardan PDF ham: haftasiga {n} ta vazifa',
        'files_unlimited': 'Fayl vositalari: cheksiz',
        'no_channels': 'Kanallarga obuna bo‘lish shart emas',
        'every_tool': '✅ Har bir tarifda barcha vositalar bor.',
        'how': '<b>Qanday to‘lanadi</b>\n1. Quyidan tarifni tanlang.\n2. Ko‘rsatilgan kartaga bank ilovangizdan pul o‘tkazing.\n'
               '3. Kvitansiyani shu yerga yuboring. Tekshirgach tarifingizni yoqamiz, odatda bir necha soat ichida.',
    },
    'ru': {
        'title': '<b>📋 Тарифы</b>',
        'current': 'Ваш тариф: <b>{plan}</b>',
        'head_free': '<b>{icon} {name}</b> — 0 сум',
        'head': '<b>{icon} {name}</b> — {price} сум за 30 дней',
        'head_discount': '<b>{icon} {name}</b> — <s>{regular}</s> <b>{price}</b> сум за 30 дней',
        'discount_line': '−{percent}% до {until}',
        'yours': ' · ✅ ваш',
        'ai_week': 'ИИ-документы и презентации: {n} в неделю',
        'ai_unlimited': 'ИИ-документы и презентации: без ограничений',
        'edits': 'ИИ-правки: {n} на каждый файл',
        'edits_unlimited': 'ИИ-правки: без ограничений',
        'files_week': 'Задачи с файлами, включая PDF из фото: {n} в неделю',
        'files_unlimited': 'Задачи с файлами: без ограничений',
        'no_channels': 'Без обязательной подписки на каналы',
        'every_tool': '✅ Все инструменты есть в каждом тарифе.',
        'how': '<b>Как оплатить</b>\n1. Выберите тариф ниже.\n2. Переведите сумму из банковского приложения на указанную карту.\n'
               '3. Отправьте сюда квитанцию. После проверки включим тариф, обычно в течение нескольких часов.',
    },
}
PLAN_ICONS = {'free': '🆓', 'plus': '⭐', 'premium': '💎'}


def plan_name(account, plan):
    return copy(account, 'free') if plan == 'free' else plan.title()


def weekly(words, key, unlimited, value):
    return words[unlimited] if value is None else words[key].format(n=money(int(value)))


def every_tool_on_every_plan():
    """Whether the tool catalog gives every plan the same access to every tool.

    The cards say so under them only while it is true: a tool held back from
    one plan would make the line a promise the plan does not keep.
    """
    from apps.core.policy import FEATURES
    return all(len({feature['plans'].get(plan) for plan in PLAN_ICONS}) == 1 for feature in FEATURES.values())


def plans_overview(account):
    """Every plan on offer, what it includes, and which one the customer has."""
    from apps.commerce.pricing import plan_price
    from apps.commerce.services import effective_plan
    from apps.core.policy import limits_for_plan
    locale = account.locale if account.locale in PLAN_COPY else 'en'
    words = PLAN_COPY[locale]
    current = effective_plan(account)
    blocks = [words['title'], words['current'].format(plan=html.escape(plan_name(account, current)))]
    for plan in ('free', 'plus', 'premium'):
        limits = limits_for_plan(plan)
        name = html.escape(plan_name(account, plan))
        discount = None
        if plan == 'free':
            head = words['head_free'].format(icon=PLAN_ICONS[plan], name=name)
        else:
            # Today's price: the discounted one while a discount runs, the
            # regular one after its last day, and none if the plan has no price.
            offer = plan_price(plan, limits)
            if offer is None:
                continue  # not on sale
            discount = offer['discount']
            if discount:
                head = words['head_discount'].format(icon=PLAN_ICONS[plan], name=name,
                                                     regular=money(discount['regular']), price=money(discount['price']))
            else:
                head = words['head'].format(icon=PLAN_ICONS[plan], name=name, price=money(offer['price']))
        if plan == current:
            head += words['yours']
        if discount:
            head += '\n' + words['discount_line'].format(percent=discount['percent'],
                                                         until=day_label(discount['until'], locale))
        # The weekly limits, as the owner's table puts them (a limit that is not
        # set is unlimited), then the channels, which Premium never asks for.
        # That is all a card says: nothing else differs between plans.
        lines = [weekly(words, 'ai_week', 'ai_unlimited', limits.get('weekly_ai_documents')),
                 weekly(words, 'edits', 'edits_unlimited', limits.get('edits_per_file')),
                 weekly(words, 'files_week', 'files_unlimited', limits.get('weekly_file_jobs')),
                 *([words['no_channels']] if plan == 'premium' else [])]
        blocks.append(head + '\n' + '\n'.join(f'• {line}' for line in lines))
    if every_tool_on_every_plan():
        blocks.append(words['every_tool'])
    return '\n\n'.join(blocks)

def copy(account, key):
    return COPY.get(account.locale, COPY['en'])[key]


async def button(account, label, action, payload=None):
    from .bot import callback
    return InlineKeyboardButton(text=copy(account, label), callback_data=await callback(account, action, payload))


# Back to the plans from a payment screen. Each plans button says where it is,
# so the admin can count where the plans are opened from (funnel.PLAN_SOURCES).
FROM_PAYMENT = {'from': 'payment'}


async def navigation(account, back=None, payload=None):
    rows = []
    if back:
        rows.append([await button(account, 'back', back, payload)])
    rows.append([await button(account, 'home', 'home')])
    return rows


async def leave_input_prompt(account):
    # Opening billing is navigation, so a later ordinary reply must not be
    # interpreted as a forgotten page-range or support-message prompt.
    await sync_to_async(lambda: BotConversation.objects.filter(pk=account.telegram_user_id).update(state='', prompt={}, updated_at=timezone.now()))()


async def show(message, body, rows, edit=False, parse_mode=None):
    """A billing screen in place of the one whose button was tapped, or a new one.

    Editing is best effort, as elsewhere in the bot: a message that cannot be
    edited (too old, a photo, already gone) gets a fresh reply instead.
    """
    markup = InlineKeyboardMarkup(inline_keyboard=rows)
    if edit:
        try:
            return await message.edit_text(body, parse_mode=parse_mode, reply_markup=markup)
        except Exception as exc:
            if 'message is not modified' in str(exc):
                return None
    return await message.answer(body, parse_mode=parse_mode, reply_markup=markup)


def money(amount):
    return f'{amount:,}'.replace(',', ' ')


def card_label(account, item):
    """One plan's button on the plans screen: its price today, and how much off while a discount runs.

    An inline button cannot strike a price through, so the regular price is on
    the card above it; the button carries the percentage.
    """
    discount = item.get('discount')
    if discount:
        return copy(account, 'card_pay_discount').format(plan=item['plan'].title(), price=money(item['price']),
                                                         percent=discount['percent'])
    return copy(account, 'card_pay').format(plan=item['plan'].title(), price=money(item['price']))


async def show_offers(message, account, edit=False, source=None, tap=''):
    """The plans screen. `source` is where it was opened from, and `tap` the
    button tapped to open it, for the admin's count."""
    from .bot import callback
    from apps.commerce import manual
    await leave_input_prompt(account)
    cards = await sync_to_async(manual.options)()
    rows = []
    # Card transfer is the way to pay. Automatic payment is announced, not
    # offered, until it exists.
    for item in cards['plans']:
        rows.append([InlineKeyboardButton(
            text=card_label(account, item),
            callback_data=await callback(account, 'commerce_manual_plan', {'plan': item['plan']}),
        )])
    rows.append([await button(account, 'subscription', 'subscription')])
    rows.extend(await navigation(account))
    overview = await sync_to_async(plans_overview)(account)
    if cards['enabled']:
        tail = PLAN_COPY.get(account.locale, PLAN_COPY['en'])['how'] + '\n\n' + html.escape(copy(account, 'automatic_soon'))
    else:
        tail = html.escape(copy(account, 'unavailable'))
    shown = await show(message, overview + '\n\n' + tail, rows, edit, 'HTML')
    # Counted once the screen is on its way: a screen that could not be sent
    # raises before this, and is not a look. An edit Telegram turns down as
    # unchanged is not one either, though the fresh buttons above make that
    # rare; a double tap is caught by the button instead (funnel.plans_viewed).
    # Counting never raises.
    if shown is not None:
        await sync_to_async(funnel.plans_viewed)(account, source, tap)


async def show_manual(message, account, plan, edit=False):
    """The card, the price and the code for one plan, and how to send the receipt."""
    from apps.commerce import manual
    await leave_input_prompt(account)
    payment, _ = await sync_to_async(manual.create)(account, plan, 'bot')
    await show_manual_payment(message, account, payment, edit)


def discount_note(account, payment):
    """The regular price struck through, with how much off until when, under the
    title of a payment screen that asks for a discounted amount; otherwise ''.

    Only when the plan's discount runs today and the request is for exactly
    the discounted price. A request at the regular price, opened before the
    discount or reopened after its last day, is asked for as the plans screen
    shows it, and a note about a discount would contradict the amount.
    """
    from apps.commerce.pricing import plan_price
    offer = plan_price(payment.plan)
    discount = offer['discount'] if offer else None
    if not discount or payment.amount != offer['price']:
        return ''
    locale = account.locale if account.locale in COPY else 'en'
    return copy(account, 'manual_discount').format(regular=money(discount['regular']), percent=discount['percent'],
                                                   until=day_label(discount['until'], locale))


async def show_manual_payment(message, account, payment, edit=False):
    from .bot import callback
    card = payment.card or {}
    number = ' '.join(card.get('number', '')[i:i + 4] for i in range(0, len(card.get('number', '')), 4))
    holder = html.escape(' · '.join(part for part in (card.get('holder', ''), card.get('label', '')) if part))
    values = {'plan': payment.plan.title(), 'price': money(payment.amount), 'card': number,
              'holder': holder, 'reference': payment.reference, 'note': ''}
    if payment.status == 'submitted':
        body = copy(account, 'manual_waiting').format(**values)
        send = 'manual_resend'
    else:
        values['note'] = await sync_to_async(discount_note)(account, payment)
        body = copy(account, 'manual_screen').format(**values)
        send = 'manual_paid'
    rows = [
        [InlineKeyboardButton(text=copy(account, send), callback_data=await callback(account, 'commerce_manual_receipt', {'payment_id': str(payment.id)}))],
        [InlineKeyboardButton(text=copy(account, 'manual_cancel'), callback_data=await callback(account, 'commerce_manual_cancel', {'payment_id': str(payment.id)}))],
        *(await navigation(account, 'plans', FROM_PAYMENT)),
    ]
    await show(message, body, rows, edit, 'HTML')


async def receive_receipt(message, account, payment_id, raw):
    """A photo or PDF sent while the bot waits for a receipt belongs to that payment."""
    from apps.commerce import manual
    from .bot import safe_error
    try:
        await sync_to_async(manual.attach_receipt)(account, payment_id, raw, '', 'bot')
    except DomainError as exc:
        return await safe_error(message, account, exc)
    await leave_input_prompt(account)
    await message.answer(copy(account, 'manual_received'), reply_markup=await payment_navigation(account))


async def show_subscription(message, account, edit=False):
    """The plan, and until when it is paid for. A card transfer covers 30 days
    and never renews by itself, so there is no renewal to switch, only the
    plans to pay again from."""
    await leave_input_prompt(account)
    data = await sync_to_async(subscription_data)(account)
    sub = data['subscription']
    if not sub and data['plan'] != 'free':
        # A plan the team gave, or one paid for outside a subscription: say so
        # rather than claim the customer is on Free.
        lines = [copy(account, 'plan_without_subscription').format(plan=html.escape(data['plan'].title()))]
    elif not sub:
        lines = [copy(account, 'no_subscription')]
    else:
        lines = [f'<b>{html.escape(sub["plan"].title())}</b>']
        if sub['active_until']:
            lines.append(f'{copy(account, "active_until")}: {stamp(account, sub["current_period_end"])}')
        else:
            lines.append(copy(account, 'expired'))
    rows = [[await button(account, 'plans', 'plans', {'from': 'subscription'})], *(await navigation(account))]
    await show(message, '\n'.join(lines), rows, edit, 'HTML')


async def payment_navigation(account):
    return InlineKeyboardMarkup(inline_keyboard=[
        [await button(account, 'subscription', 'subscription'), await button(account, 'plans', 'plans', {'from': 'notice'})],
        [await button(account, 'payment_support', 'support', {'payment': True})],
        *(await navigation(account)),
    ])


def register_billing_handlers(dp):
    from .bot import account_for, safe_error, sender_language

    @dp.message(Command('myid'))
    async def my_id(message):
        # The owner's ID is what Admin → Integrations needs for payment alerts.
        await message.answer(copy(sender_language(message.from_user), 'myid').format(id=message.from_user.id), parse_mode='HTML')

    @dp.message(Command('buy', 'plans'))
    async def buy(message):
        # `/buy plus` and `/buy ai100` once opened a checkout for that one
        # thing. Typed from habit or from an old message, they open the plans,
        # where every plan on sale and its card transfer are.
        account = await account_for(message.from_user)
        try:
            await show_offers(message, account, source='command')
        except DomainError as exc:
            await safe_error(message, account, exc)

    @dp.message(Command('subscription'))
    async def subscription(message):
        account = await account_for(message.from_user)
        try:
            await show_subscription(message, account)
        except DomainError as exc:
            await safe_error(message, account, exc)

    @dp.callback_query(F.data)
    async def commerce_callback(query):
        from aiogram.dispatcher.event.bases import SkipHandler
        # Authentication-link callbacks must reach the auth router without
        # registering a duplicate Telegram customer account.
        from .bot import usable
        ref = await sync_to_async(lambda: BotCallback.objects.filter(token=query.data, account__telegram_user_id=query.from_user.id, action__startswith='commerce_').first())()
        # An old payment button that has to be fresh goes on to the general
        # handler, which opens the menu in its place.
        if not usable(ref):
            raise SkipHandler()
        # Stop the Telegram loading spinner before the payment is opened.
        await query.answer()
        account = await account_for(query.from_user)
        try:
            if ref.action == 'commerce_manual_plan':
                await show_manual(query.message, account, ref.payload['plan'], edit=True)
            elif ref.action == 'commerce_manual_receipt':
                from .bot import set_prompt
                await sync_to_async(set_prompt)(account, 'payment_receipt', {'payment_id': ref.payload['payment_id']})
                await query.message.answer(copy(account, 'manual_send_receipt'))
            elif ref.action == 'commerce_manual_cancel':
                from apps.commerce import manual
                await sync_to_async(manual.cancel)(account, ref.payload['payment_id'])
                await leave_input_prompt(account)
                await show(query.message, copy(account, 'manual_cancelled'), await navigation(account, 'plans', FROM_PAYMENT), edit=True)
            else:
                # A button from a chat older than card transfer: an offer or a
                # renewal switch for a checkout that no longer exists. The plans
                # on sale today, rather than nothing.
                await show_offers(query.message, account)
        except DomainError as exc:
            await safe_error(query.message, account, exc)
