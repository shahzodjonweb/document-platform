"""Telegram Stars screens. Financial decisions remain in commerce services."""
import html

from asgiref.sync import sync_to_async
from aiogram import F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from django.utils import timezone

from apps.core import funnel
from apps.core.errors import DomainError
from apps.core.models import BotCallback, BotConversation
from apps.commerce import services
from apps.commerce.serializers import subscription_data

from .clock import stamp

COPY = {
    'en': {
        "card_pay": "💳 {plan} · {price} so'm / 30 days",
        "card_intro": "💳 Pay by card transfer\nPick a plan. You send the money from your bank app, send us the receipt, and we switch your plan on after checking it.",
        "automatic_soon": "⚡ Automatic payment — coming soon",
        "manual_screen": "<b>💳 {plan} — {price} so'm for 30 days</b>\n\n1. Send exactly <b>{price} so'm</b> to this card:\n<code>{card}</code>\n{holder}\n\n2. Tap «I've paid» and send the receipt here as a photo or PDF.\n\nPayment code: <code>{reference}</code>\nWe check every payment by hand, usually within a few hours, and message you here.",
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
        'offers': '⭐ Plans\nChoose one to see what’s included.',
        'sandbox': '🧪 Test payment — no real Telegram Stars spent.',
        'live': 'Pay with Telegram Stars. Your plan switches on after confirmation.',
        'pay': '⭐ Pay in Telegram', 'simulate': '🧪 Try test payment',
        'confirmed': '✅ Paid! Your plan is on.',
        'unavailable': 'Payments aren’t ready yet. You can keep using your current plan.',
        'cancel': '⏸ Turn renewal off', 'resume': '▶️ Turn renewal on',
        'renewal_on': '🔄 Auto-renewal: on', 'renewal_off': '⏸ Auto-renewal: off',
        'active_until': 'Paid access until', 'scheduled': 'Next plan',
        'updated': '✅ Updated. Your paid access stays the same.',
        'support': 'Need a hand with this payment? Tap Payment support.',
        'payment_support': '💬 Payment support', 'home': '🏠 Main menu', 'back': '← Back',
        'plans': '⭐ Plans', 'subscription': '💳 Subscription', 'free': 'Free',
        'price': 'Price', 'period': 'Renews every 30 days',
        'review': '🧾 Your purchase', 'expires': 'Checkout expires in 10 minutes.',
        'no_subscription': 'You’re on Free. No paid subscription to manage.',
        'plan_without_subscription': 'Your plan: <b>{plan}</b>. It isn’t a paid subscription, so there is nothing to renew or cancel.',
        'expired': 'Your subscription has ended. Pick a plan to continue.',
        'confirm_off': '⏸ Turn renewal off?\nKeep your paid access until {date}. No charge for the next period.',
        'confirm_on': '🔄 Turn renewal on?\nTelegram will renew your plan at the end of each paid period. Any scheduled plan change will be cancelled.',
        'confirm_change': '🔄 Switch to {plan} after {date}?\nKeep your current plan until then. Auto-renewal will stop. A new paid plan needs a separate payment.',
        'confirm': '✅ Confirm change', 'keep': '← Keep settings',
        'invalid_invoice': '⚠️ Couldn’t verify this payment. Try a new checkout or use /paysupport.',
    },
    'uz': {
        "card_pay": "💳 {plan} · {price} so'm / 30 kun",
        "card_intro": "💳 Karta orqali to‘lov\nTarifni tanlang. Pulni bank ilovangizdan o‘tkazasiz, kvitansiyani yuborasiz, tekshirgach tarifingizni yoqamiz.",
        "automatic_soon": "⚡ Avtomatik to‘lov — tez orada",
        "manual_screen": "<b>💳 {plan} — 30 kun uchun {price} so'm</b>\n\n1. Shu kartaga aynan <b>{price} so'm</b> o‘tkazing:\n<code>{card}</code>\n{holder}\n\n2. «To‘ladim» tugmasini bosing va kvitansiyani shu yerga rasm yoki PDF qilib yuboring.\n\nTo‘lov kodi: <code>{reference}</code>\nHar bir to‘lovni qo‘lda tekshiramiz, odatda bir necha soat ichida, va shu yerga yozamiz.",
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
        'offers': '⭐ Tariflar\nTafsilotlarni ko‘rish uchun birini tanlang.',
        'sandbox': '🧪 Sinov to‘lovi — haqiqiy Telegram Stars sarflanmaydi.',
        'live': 'Telegram Stars bilan to‘lang. To‘lov tasdiqlangach, tarifingiz yoqiladi.',
        'pay': '⭐ Telegram’da to‘lash', 'simulate': '🧪 Sinov to‘lovi',
        'confirmed': '✅ To‘landi! Tarifingiz yoqildi.',
        'unavailable': 'To‘lov hozircha ishlamayapti. Joriy tarifdan foydalanishingiz mumkin.',
        'cancel': '⏸ Uzaytirishni o‘chirish', 'resume': '▶️ Uzaytirishni yoqish',
        'renewal_on': '🔄 Avto-uzaytirish: yoqilgan', 'renewal_off': '⏸ Avto-uzaytirish: o‘chirilgan',
        'active_until': 'Pulli tarif muddati', 'scheduled': 'Keyingi tarif',
        'updated': '✅ Yangilandi. Pulli tarif muddati o‘zgarmadi.',
        'support': 'To‘lovda yordam kerakmi? «To‘lov bo‘yicha yordam»ni bosing.',
        'payment_support': '💬 To‘lov bo‘yicha yordam', 'home': '🏠 Bosh menyu', 'back': '← Orqaga',
        'plans': '⭐ Tariflar', 'subscription': '💳 Obuna', 'free': 'Bepul',
        'price': 'Narx', 'period': 'Har 30 kunda uzaytiriladi',
        'review': '🧾 Xaridingiz', 'expires': 'To‘lov havolasi 10 daqiqa amal qiladi.',
        'no_subscription': 'Siz Bepul tarifdasiz. Pulli obunangiz yo‘q.',
        'plan_without_subscription': 'Tarifingiz: <b>{plan}</b>. Bu pullik obuna emas, shuning uchun uzaytirish yoki bekor qilish kerak emas.',
        'expired': 'Obunangiz tugagan. Davom etish uchun tarif tanlang.',
        'confirm_off': '⏸ Uzaytirish o‘chirilsinmi?\nPulli tarif {date} gacha saqlanadi. Keyingi davr uchun to‘lov olinmaydi.',
        'confirm_on': '🔄 Uzaytirish yoqilsinmi?\nTelegram har bir pulli davr oxirida tarifni uzaytiradi. Rejalangan tarif o‘zgarishi bekor qilinadi.',
        'confirm_change': '🔄 {date} dan keyin {plan} tarifiga o‘tilsinmi?\nJoriy tarif shu vaqtgacha saqlanadi. Avto-uzaytirish to‘xtaydi. Yangi pulli tarif uchun alohida to‘lov kerak.',
        'confirm': '✅ Tasdiqlash', 'keep': '← O‘zgartirmaslik',
        'invalid_invoice': '⚠️ To‘lovni tekshira olmadik. Yangi to‘lovni oching yoki /paysupport orqali yozing.',
    },
    'ru': {
        "card_pay": "💳 {plan} · {price} сум / 30 дней",
        "card_intro": "💳 Оплата переводом на карту\nВыберите тариф. Вы переводите деньги из своего банковского приложения, присылаете квитанцию, и после проверки мы включаем тариф.",
        "automatic_soon": "⚡ Автоматическая оплата — скоро",
        "manual_screen": "<b>💳 {plan} — {price} сум за 30 дней</b>\n\n1. Переведите ровно <b>{price} сум</b> на эту карту:\n<code>{card}</code>\n{holder}\n\n2. Нажмите «Я оплатил» и отправьте сюда квитанцию фото или PDF.\n\nКод платежа: <code>{reference}</code>\nМы проверяем каждый платёж вручную, обычно в течение нескольких часов, и напишем вам здесь.",
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
        'offers': '⭐ Тарифы\nВыберите тариф, чтобы узнать подробности.',
        'sandbox': '🧪 Тестовая оплата — настоящие Telegram Stars не списываются.',
        'live': 'Оплата через Telegram Stars. Тариф включится после подтверждения.',
        'pay': '⭐ Оплатить в Telegram', 'simulate': '🧪 Тестовая оплата',
        'confirmed': '✅ Оплачено! Тариф включён.',
        'unavailable': 'Оплата пока недоступна. Текущий тариф продолжает работать.',
        'cancel': '⏸ Отключить продление', 'resume': '▶️ Включить продление',
        'renewal_on': '🔄 Автопродление: включено', 'renewal_off': '⏸ Автопродление: выключено',
        'active_until': 'Оплачено до', 'scheduled': 'Следующий тариф',
        'updated': '✅ Готово. Оплаченный срок не изменился.',
        'support': 'Нужна помощь? Нажмите «Помощь по оплате».',
        'payment_support': '💬 Помощь по оплате', 'home': '🏠 Главное меню', 'back': '← Назад',
        'plans': '⭐ Тарифы', 'subscription': '💳 Подписка', 'free': 'Бесплатный',
        'price': 'Цена', 'period': 'Продление каждые 30 дней',
        'review': '🧾 Ваша покупка', 'expires': 'Ссылка на оплату действует 10 минут.',
        'no_subscription': 'У вас бесплатный тариф. Платной подписки нет.',
        'plan_without_subscription': 'Ваш тариф: <b>{plan}</b>. Это не платная подписка, продлевать или отменять нечего.',
        'expired': 'Подписка закончилась. Выберите тариф, чтобы продолжить.',
        'confirm_off': '⏸ Отключить продление?\nОплаченный доступ сохранится до {date}. Следующего списания не будет.',
        'confirm_on': '🔄 Включить продление?\nTelegram будет продлевать тариф в конце каждого оплаченного периода. Запланированная смена тарифа отменится.',
        'confirm_change': '🔄 Перейти на {plan} после {date}?\nТекущий тариф сохранится до этой даты. Автопродление отключится. Новый платный тариф нужно оплатить отдельно.',
        'confirm': '✅ Подтвердить', 'keep': '← Не менять',
        'invalid_invoice': '⚠️ Не удалось проверить платёж. Начните оплату заново или напишите в /paysupport.',
    },
}


# What each plan includes, written from the live plan settings so an edit in
# the admin is what customers read. People choose a plan by what it gives them,
# so the plans screen leads with this and only then says how to pay. Plans
# differ only in the three weekly counts and the channels: file sizes, page
# and slide counts and the tools are the same on every plan, so a card never
# lists them, and nobody is sold a plan on them.
PLAN_COPY = {
    'en': {
        'title': '<b>📋 Plans</b>',
        'current': 'Your plan: <b>{plan}</b>',
        'head_free': "<b>{icon} {name}</b> — 0 so'm",
        'head': "<b>{icon} {name}</b> — {price} so'm / 30 days",
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
    from apps.commerce.services import effective_plan
    from apps.core.policy import limits_for_plan
    words = PLAN_COPY.get(account.locale, PLAN_COPY['en'])
    current = effective_plan(account)
    blocks = [words['title'], words['current'].format(plan=html.escape(plan_name(account, current)))]
    for plan in ('free', 'plus', 'premium'):
        limits = limits_for_plan(plan)
        price = limits.get('price_uzs')
        if plan != 'free' and not (type(price) is int and price > 0):
            continue  # not on sale
        head = words['head_free' if plan == 'free' else 'head'].format(
            icon=PLAN_ICONS[plan], name=html.escape(plan_name(account, plan)), price=money(price or 0))
        if plan == current:
            head += words['yours']
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


def offer_name(account, offer):
    value = services.offer_data(offer) if not isinstance(offer, dict) else offer
    # Only plans are sold; an invoice for a pack made before then keeps its own name.
    return value['plan'].title() if value.get('plan') else value.get('name', '')


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


async def show_offers(message, account, edit=False, source=None, tap=''):
    """The plans screen. `source` is where it was opened from, and `tap` the
    button tapped to open it, for the admin's count."""
    from .bot import callback
    from apps.commerce import manual
    await leave_input_prompt(account)
    offers = await sync_to_async(services.available_offers)(account)
    cards = await sync_to_async(manual.options)()
    rows = []
    # Card transfer first: it is the way to pay today. Automatic payment is
    # announced, not offered, until it exists.
    for item in cards['plans']:
        rows.append([InlineKeyboardButton(
            text=copy(account, 'card_pay').format(plan=item['plan'].title(), price=money(item['price'])),
            callback_data=await callback(account, 'commerce_manual_plan', {'plan': item['plan']}),
        )])
    for offer in offers:
        rows.append([InlineKeyboardButton(
            text=f'{offer_name(account, offer)} · ⭐ {offer.price_xtr}',
            callback_data=await callback(account, 'commerce_offer', {'offer_id': offer.offer_id}),
        )])
    rows.append([await button(account, 'subscription', 'subscription')])
    rows.extend(await navigation(account))
    overview = await sync_to_async(plans_overview)(account)
    if cards['enabled']:
        tail = PLAN_COPY.get(account.locale, PLAN_COPY['en'])['how'] + '\n\n' + html.escape(copy(account, 'automatic_soon'))
    else:
        tail = html.escape(copy(account, 'offers' if offers else 'unavailable'))
    if offers:
        tail += '\n\n' + html.escape(copy(account, 'sandbox' if offers[0].sandbox else 'live'))
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
    from .bot import callback
    from apps.commerce import manual
    await leave_input_prompt(account)
    payment, _ = await sync_to_async(manual.create)(account, plan, 'bot')
    await show_manual_payment(message, account, payment, edit)


async def show_manual_payment(message, account, payment, edit=False):
    from .bot import callback
    card = payment.card or {}
    number = ' '.join(card.get('number', '')[i:i + 4] for i in range(0, len(card.get('number', '')), 4))
    holder = html.escape(' · '.join(part for part in (card.get('holder', ''), card.get('label', '')) if part))
    values = {'plan': payment.plan.title(), 'price': money(payment.amount), 'card': number,
              'holder': holder, 'reference': payment.reference}
    if payment.status == 'submitted':
        body = copy(account, 'manual_waiting').format(**values)
        send = 'manual_resend'
    else:
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


async def show_invoice(message, account, offer_id, key, source=None):
    from .bot import callback
    await leave_input_prompt(account)
    # Packs are no longer sold, but their old buttons stay in chats and people
    # still type /buy ai100. Those open the plans on sale today rather than
    # say payments are unavailable, which they are not.
    offers = await sync_to_async(services.available_offers)(account)
    if offer_id not in {offer.offer_id for offer in offers}:
        return await show_offers(message, account, source=source)
    invoice, _ = await sync_to_async(services.create_invoice)(account, offer_id, key)
    invoice = await sync_to_async(services.present_invoice)(invoice)
    if invoice.sandbox:
        pay = InlineKeyboardButton(text=copy(account, 'simulate'), callback_data=await callback(account, 'commerce_pay', {'invoice_id': str(invoice.id)}))
    else:
        pay = InlineKeyboardButton(text=copy(account, 'pay'), url=invoice.invoice_url)
    lines = [f'<b>{copy(account, "review")}</b>', html.escape(offer_name(account, invoice.snapshot)),
             f'{copy(account, "price")}: ⭐ {invoice.amount_xtr} Telegram Stars', copy(account, 'period'),
             '', copy(account, 'sandbox' if invoice.sandbox else 'live'), copy(account, 'expires')]
    rows = [[pay], *(await navigation(account, 'plans', FROM_PAYMENT))]
    await message.answer('\n'.join(lines), parse_mode='HTML', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


async def show_subscription(message, account, edit=False):
    await leave_input_prompt(account)
    data = await sync_to_async(subscription_data)(account)
    sub = data['subscription']
    rows = []
    if not sub and data['plan'] != 'free':
        # A plan the team gave, or one paid for outside a subscription: say so
        # rather than claim the customer is on Free.
        lines = [copy(account, 'plan_without_subscription').format(plan=html.escape(data['plan'].title()))]
    elif not sub:
        lines = [copy(account, 'no_subscription')]
    else:
        lines = [f'<b>{html.escape(sub["plan"].title())}</b>']
        if sub['active_until']:
            lines.extend([copy(account, 'renewal_on' if sub['renewal_enabled'] else 'renewal_off'),
                          f'{copy(account, "active_until")}: {stamp(account, sub["current_period_end"])}'])
            rows.append([await button(account, 'cancel' if sub['renewal_enabled'] else 'resume',
                                      'commerce_cancel' if sub['renewal_enabled'] else 'commerce_resume', {'subscription_id': sub['id']})])
        else:
            lines.append(copy(account, 'expired'))
        if sub['scheduled_plan']:
            name = copy(account, 'free') if sub['scheduled_plan'] == 'free' else sub['scheduled_plan'].title()
            lines.append(f'{copy(account, "scheduled")}: {name}')
        if sub['sandbox']:
            lines.extend(['', copy(account, 'sandbox')])
    rows.append([await button(account, 'plans', 'plans', {'from': 'subscription'})])
    rows.extend(await navigation(account))
    await show(message, '\n'.join(lines), rows, edit, 'HTML')


async def show_subscription_confirmation(message, account, *, enabled=None, plan=None, subscription_id=None):
    await leave_input_prompt(account)
    data = await sync_to_async(subscription_data)(account)
    sub = data['subscription']
    if not sub or not sub['active_until']:
        raise DomainError('subscription_not_active', 409)
    if subscription_id and sub['id'] != subscription_id:
        raise DomainError('controls_expired', 409)
    if plan is not None:
        if plan not in ('free', 'plus', 'premium'):
            raise DomainError('invalid_plan')
        if plan == sub['plan']:
            raise DomainError('invalid_plan_change', 409)
        body = copy(account, 'confirm_change').format(
            date=stamp(account, sub["current_period_end"]),
            plan=copy(account, 'free') if plan == 'free' else plan.title(),
        )
        action, payload = 'commerce_plan_confirm', {'subscription_id': sub['id'], 'plan': plan}
    else:
        body = copy(account, 'confirm_on' if enabled else 'confirm_off').format(date=stamp(account, sub["current_period_end"]))
        action, payload = 'commerce_renewal_confirm', {'subscription_id': sub['id'], 'enabled': enabled}
    rows = [[await button(account, 'confirm', action, payload)],
            [await button(account, 'keep', 'subscription')], *(await navigation(account))]
    await message.answer(body, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


async def payment_navigation(account):
    return InlineKeyboardMarkup(inline_keyboard=[
        [await button(account, 'subscription', 'subscription'), await button(account, 'plans', 'plans', {'from': 'notice'})],
        [await button(account, 'payment_support', 'support', {'payment': True})],
        *(await navigation(account)),
    ])


def register_billing_handlers(dp):
    from .bot import account_for, safe_error, sender_language

    @dp.pre_checkout_query()
    async def precheckout(query):
        try:
            await sync_to_async(services.validate_precheckout)(query.from_user.id, query.invoice_payload, query.currency, query.total_amount, False)
            await query.answer(ok=True)
        except DomainError:
            await query.answer(ok=False, error_message=copy(sender_language(query.from_user), 'invalid_invoice'))

    @dp.message(F.successful_payment)
    async def successful(message):
        data = message.successful_payment
        account = await account_for(message.from_user)
        try:
            await sync_to_async(services.record_payment)(message.from_user.id, data.invoice_payload, data.currency, data.total_amount, data.telegram_payment_charge_id, provider_charge_id=data.provider_payment_charge_id, expiration_date=data.subscription_expiration_date, is_recurring=bool(data.is_recurring), is_first_recurring=bool(data.is_first_recurring), occurred_at=message.date, sandbox=False)
            await message.answer(copy(account, 'confirmed'), reply_markup=await payment_navigation(account))
        except DomainError as exc:
            await safe_error(message, account, exc)
            await message.answer(copy(account, 'support'), reply_markup=await payment_navigation(account))

    @dp.message(Command('myid'))
    async def my_id(message):
        # The owner's ID is what Admin → Integrations needs for payment alerts.
        await message.answer(copy(sender_language(message.from_user), 'myid').format(id=message.from_user.id), parse_mode='HTML')

    @dp.message(Command('buy', 'plans'))
    async def buy(message):
        account = await account_for(message.from_user)
        try:
            values = message.text.split(maxsplit=1)
            # Typed, or chosen from the command menu: Telegram sends the same text.
            if len(values) > 1:
                return await show_invoice(message, account, values[1].strip(), f'telegram:{message.chat.id}:{message.message_id}', 'command')
            await show_offers(message, account, source='command')
        except DomainError as exc:
            await safe_error(message, account, exc)

    @dp.message(Command('subscription', 'cancelrenewal', 'resumerenewal', 'changeplan'))
    async def subscription(message):
        account = await account_for(message.from_user)
        try:
            command = message.text.split()[0].split('@')[0]
            if command in ('/cancelrenewal', '/resumerenewal'):
                return await show_subscription_confirmation(message, account, enabled=command == '/resumerenewal')
            if command == '/changeplan':
                return await show_subscription_confirmation(message, account, plan=message.text.split(maxsplit=1)[1].strip())
            await show_subscription(message, account)
        except (ValueError, IndexError):
            await safe_error(message, account, DomainError('invalid_plan'))
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
        # Stop the Telegram loading spinner before an invoice/provider request.
        await query.answer()
        account = await account_for(query.from_user)
        try:
            if ref.action == 'commerce_offer':
                await show_invoice(query.message, account, ref.payload['offer_id'], f'telegram:{ref.token}')
            elif ref.action == 'commerce_manual_plan':
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
            elif ref.action == 'commerce_pay':
                await sync_to_async(services.sandbox_pay)(account, ref.payload['invoice_id'])
                await query.message.answer(copy(account, 'confirmed'), reply_markup=await payment_navigation(account))
            elif ref.action in ('commerce_cancel', 'commerce_resume'):
                await show_subscription_confirmation(query.message, account, enabled=ref.action == 'commerce_resume', subscription_id=ref.payload['subscription_id'])
            elif ref.action in ('commerce_renewal_confirm', 'commerce_plan_confirm'):
                from apps.commerce.models import Subscription
                valid = await sync_to_async(lambda: Subscription.objects.filter(pk=ref.payload['subscription_id'], account=account).exists())()
                if not valid:
                    raise DomainError('controls_expired', 409)
                if ref.action == 'commerce_renewal_confirm':
                    await sync_to_async(services.set_renewal)(account, ref.payload['enabled'])
                else:
                    await sync_to_async(services.schedule_plan_change)(account, ref.payload['plan'])
                await query.message.answer(copy(account, 'updated'))
                await show_subscription(query.message, account)
        except DomainError as exc:
            await safe_error(query.message, account, exc)


def fast_precheckout(update):
    """Call from verified webhook receiver before durable normal-update dispatch."""
    query = update.get('pre_checkout_query')
    if not query:
        return False
    from types import SimpleNamespace
    from apps.commerce.providers import TelegramStarsProvider
    ok = True
    try:
        services.validate_precheckout(query['from']['id'], query['invoice_payload'], query['currency'], query['total_amount'], False)
    except (DomainError, KeyError, TypeError):
        ok = False
    kwargs = {'pre_checkout_query_id': query['id'], 'ok': ok}
    if not ok:
        locale = (query.get('from', {}).get('language_code') or 'en').split('-')[0]
        kwargs['error_message'] = copy(SimpleNamespace(locale=locale), 'invalid_invoice')
    TelegramStarsProvider().call('answer_pre_checkout_query', **kwargs)
    return True
