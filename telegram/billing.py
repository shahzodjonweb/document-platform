"""Plans, payments and the subscription in the bot.

Prices, discounts included, come from apps.commerce.pricing; the financial
decisions stay in apps.commerce. A plan is paid for in so'm, online through
inPAY (apps/commerce/checkout.py) or by card transfer with a receipt
(apps/commerce/manual.py), whichever the owner has switched on.
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
        "card_pay": "💳 {plan} · {price} so'm a month",
        "card_pay_discount": "💳 {plan} · {price} so'm a month −{percent}%",
        "card_pay_year": "📅 {plan} · {per_month} so'm a month −{percent}%, paid yearly",
        "period_month": "30 days", "period_year": "1 year", "plan_year": "{plan} · 1 year",
        "card_intro": "💳 Pay by card transfer\nPick a plan. You send the money from your bank app, send us the receipt, and we switch your plan on after checking it.",
        "automatic_soon": "⚡ Automatic payment — coming soon",
        "manual_screen": "<b>💳 {plan} — {price} so'm for {period}</b>{note}\n\n1. Send exactly <b>{price} so'm</b> to this card:\n<code>{card}</code>\n{holder}\n\n2. Tap «I've paid» and send the receipt here as a photo or PDF.\n\nPayment code: <code>{reference}</code>\nWe check every payment by hand, usually within a few hours, and message you here.",
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
        "checkout_fallback": "⚠️ Online payment isn't working right now, so you can pay by card transfer instead.",
        "checkout_screen": "<b>⚡ {plan} — {price} so'm for {period}</b>{note}\n\nTap «Pay» to open inPAY's payment page and pay with Click, Payme, Uzcard or Humo.\n\nYour plan switches on by itself after the payment, usually within a minute, and we message you here. Nothing renews by itself.",
        "checkout_test_note": "\n\n🧪 Test mode: no money moves and your plan does not change.",
        "checkout_pay": "💳 Pay {price} so'm",
        "checkout_check": "🔄 I've paid — check",
        "checkout_waiting": "⏳ We haven't received the payment yet. If you have just paid, wait a minute and check again.",
        "checkout_paid": "✅ Payment received! {plan} is active until {date}. Thank you!",
        "checkout_failed": "The payment didn't go through, and nothing was charged. You can try again.",
        "checkout_refunded": "This payment was refunded, and its plan period ended with it.",
        "checkout_paid_test": "🧪 Test payment received. The payment system works: no money moved and your plan was not changed.",
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
        "card_pay": "💳 {plan} · oyiga {price} so'm",
        "card_pay_discount": "💳 {plan} · oyiga {price} so'm −{percent}%",
        "card_pay_year": "📅 {plan} · oyiga {per_month} so'm −{percent}%, yillik to‘lanadi",
        "period_month": "30 kun", "period_year": "1 yil", "plan_year": "{plan} · 1 yil",
        "card_intro": "💳 Karta orqali to‘lov\nTarifni tanlang. Pulni bank ilovangizdan o‘tkazasiz, kvitansiyani yuborasiz, tekshirgach tarifingizni yoqamiz.",
        "automatic_soon": "⚡ Avtomatik to‘lov — tez orada",
        "manual_screen": "<b>💳 {plan} — {period} uchun {price} so'm</b>{note}\n\n1. Shu kartaga aynan <b>{price} so'm</b> o‘tkazing:\n<code>{card}</code>\n{holder}\n\n2. «To‘ladim» tugmasini bosing va kvitansiyani shu yerga rasm yoki PDF qilib yuboring.\n\nTo‘lov kodi: <code>{reference}</code>\nHar bir to‘lovni qo‘lda tekshiramiz, odatda bir necha soat ichida, va shu yerga yozamiz.",
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
        "checkout_fallback": "⚠️ Onlayn to‘lov hozir ishlamayapti, shuning uchun kartaga o‘tkazma orqali to‘lashingiz mumkin.",
        "checkout_screen": "<b>⚡ {plan} — {period} uchun {price} so'm</b>{note}\n\n«To‘lash» tugmasini bosing: inPAY to‘lov sahifasi ochiladi, u yerda Click, Payme, Uzcard yoki Humo orqali to‘laysiz.\n\nTo‘lovdan keyin tarifingiz o‘zi yoqiladi, odatda bir daqiqa ichida, va shu yerga yozamiz. Hech narsa o‘z-o‘zidan uzaytirilmaydi.",
        "checkout_test_note": "\n\n🧪 Sinov rejimi: pul yechilmaydi va tarifingiz o‘zgarmaydi.",
        "checkout_pay": "💳 {price} so'm to‘lash",
        "checkout_check": "🔄 To‘ladim — tekshirish",
        "checkout_waiting": "⏳ To‘lov hali kelib tushmadi. Hozirgina to‘lagan bo‘lsangiz, bir daqiqa kutib, qayta tekshiring.",
        "checkout_paid": "✅ To‘lov qabul qilindi! {plan} tarifi {date} gacha faol. Rahmat!",
        "checkout_failed": "To‘lov o‘tmadi, hech narsa yechilmadi. Qayta urinib ko‘rishingiz mumkin.",
        "checkout_refunded": "Bu to‘lov qaytarilgan, uning tarif muddati ham tugatilgan.",
        "checkout_paid_test": "🧪 Sinov to‘lovi qabul qilindi. To‘lov tizimi ishlayapti: pul yechilmadi va tarifingiz o‘zgarmadi.",
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
        "card_pay": "💳 {plan} · {price} сум в месяц",
        "card_pay_discount": "💳 {plan} · {price} сум в месяц −{percent}%",
        "card_pay_year": "📅 {plan} · {per_month} сум в месяц −{percent}%, оплата за год",
        "period_month": "30 дней", "period_year": "1 год", "plan_year": "{plan} · 1 год",
        "card_intro": "💳 Оплата переводом на карту\nВыберите тариф. Вы переводите деньги из своего банковского приложения, присылаете квитанцию, и после проверки мы включаем тариф.",
        "automatic_soon": "⚡ Автоматическая оплата — скоро",
        "manual_screen": "<b>💳 {plan} — {price} сум за {period}</b>{note}\n\n1. Переведите ровно <b>{price} сум</b> на эту карту:\n<code>{card}</code>\n{holder}\n\n2. Нажмите «Я оплатил» и отправьте сюда квитанцию фото или PDF.\n\nКод платежа: <code>{reference}</code>\nМы проверяем каждый платёж вручную, обычно в течение нескольких часов, и напишем вам здесь.",
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
        "checkout_fallback": "⚠️ Онлайн-оплата сейчас не работает, поэтому можно оплатить переводом на карту.",
        "checkout_screen": "<b>⚡ {plan} — {price} сум за {period}</b>{note}\n\nНажмите «Оплатить»: откроется страница оплаты inPAY, где можно заплатить через Click, Payme, Uzcard или Humo.\n\nПосле оплаты тариф включится сам, обычно в течение минуты, и мы напишем вам здесь. Автоматического продления нет.",
        "checkout_test_note": "\n\n🧪 Тестовый режим: деньги не списываются, тариф не меняется.",
        "checkout_pay": "💳 Оплатить {price} сум",
        "checkout_check": "🔄 Я оплатил — проверить",
        "checkout_waiting": "⏳ Оплата пока не поступила. Если вы только что оплатили, подождите минуту и проверьте снова.",
        "checkout_paid": "✅ Оплата получена! Тариф {plan} действует до {date}. Спасибо!",
        "checkout_failed": "Оплата не прошла, ничего не списано. Можно попробовать ещё раз.",
        "checkout_refunded": "Этот платёж возвращён, и его период тарифа завершён.",
        "checkout_paid_test": "🧪 Тестовая оплата получена. Платёжная система работает: деньги не списаны, тариф не изменён.",
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
        'yearly_line': "📅 Or yearly: <b>{per_month}</b> so'm a month, billed {price} so'm once a year (−{percent}%)",
        'yours': ' · ✅ yours',
        'ai_week': 'AI documents and decks: {n} a week',
        'ai_unlimited': 'AI documents and decks: unlimited',
        'edits': 'AI edits: {n} per file',
        'edits_unlimited': 'AI edits: unlimited',
        'files_week': 'File tools, Image → PDF included: {n} tasks a week',
        'files_unlimited': 'File tools: unlimited',
        'no_channels': 'No channel subscription needed',
        'every_tool': '✅ Every plan includes every tool.',
        'how_auto': '<b>How to pay</b>\n1. Choose a plan below.\n2. Pay on inPAY\'s page with Click, Payme, Uzcard or Humo.\n'
                    '3. Your plan switches on by itself, usually within a minute.',
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
        'yearly_line': "📅 Yoki yillik: oyiga <b>{per_month}</b> so'm, yiliga bir yo‘la {price} so'm to‘lanadi (−{percent}%)",
        'yours': ' · ✅ sizniki',
        'ai_week': 'AI hujjat va taqdimotlar: haftasiga {n} ta',
        'ai_unlimited': 'AI hujjat va taqdimotlar: cheksiz',
        'edits': 'AI tahrirlar: har bir faylga {n} ta',
        'edits_unlimited': 'AI tahrirlar: cheksiz',
        'files_week': 'Fayl vositalari, Rasmlardan PDF ham: haftasiga {n} ta vazifa',
        'files_unlimited': 'Fayl vositalari: cheksiz',
        'no_channels': 'Kanallarga obuna bo‘lish shart emas',
        'every_tool': '✅ Har bir tarifda barcha vositalar bor.',
        'how_auto': '<b>Qanday to‘lanadi</b>\n1. Quyidan tarifni tanlang.\n2. inPAY sahifasida Click, Payme, Uzcard yoki Humo orqali to‘lang.\n'
                    '3. Tarifingiz o‘zi yoqiladi, odatda bir daqiqa ichida.',
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
        'yearly_line': '📅 Или на год: <b>{per_month}</b> сум в месяц, оплата {price} сум сразу за год (−{percent}%)',
        'yours': ' · ✅ ваш',
        'ai_week': 'ИИ-документы и презентации: {n} в неделю',
        'ai_unlimited': 'ИИ-документы и презентации: без ограничений',
        'edits': 'ИИ-правки: {n} на каждый файл',
        'edits_unlimited': 'ИИ-правки: без ограничений',
        'files_week': 'Задачи с файлами, включая PDF из фото: {n} в неделю',
        'files_unlimited': 'Задачи с файлами: без ограничений',
        'no_channels': 'Без обязательной подписки на каналы',
        'every_tool': '✅ Все инструменты есть в каждом тарифе.',
        'how_auto': '<b>Как оплатить</b>\n1. Выберите тариф ниже.\n2. Оплатите на странице inPAY через Click, Payme, Uzcard или Humo.\n'
                    '3. Тариф включится сам, обычно в течение минуты.',
        'how': '<b>Как оплатить</b>\n1. Выберите тариф ниже.\n2. Переведите сумму из банковского приложения на указанную карту.\n'
               '3. Отправьте сюда квитанцию. После проверки включим тариф, обычно в течение нескольких часов.',
    },
}
PLAN_ICONS = {'free': '🆓', 'plus': '⭐', 'premium': '💎'}

# Saved cards and monthly renewal (apps/commerce/autopay.py).
CARD_COPY = {
    'en': {
        'choice': "<b>{icon} {plan} — {price} so'm for 30 days</b>{note}\n\nHow would you like to pay?\n\n"
                  "💳 <b>Pay once</b> on inPAY's page with Click, Payme, Uzcard or Humo. Nothing renews.\n"
                  "🔁 <b>Renew every month</b> from your Uzcard or Humo card: {price} so'm now and every 30 days. "
                  "We remind you 3 days before each charge, and you can turn it off or remove the card any time in /subscription.",
        'choice_card': "\n\nYour saved card: •••• {last4}",
        'pay_once': "💳 Pay once — {price} so'm",
        'pay_renew': '🔁 Pay and renew every month',
        'pay_card': "💳 Pay {price} so'm with •••• {last4}",
        'pay_card_renew': '🔁 Pay with •••• {last4} and renew monthly',
        'pay_other': "🌐 Pay once on inPAY's page",
        'confirm': "<b>Confirm payment</b>\n{plan} for 30 days: <b>{price} so'm</b> from card •••• {last4}.",
        'confirm_renew': "\nThen {price} so'm every 30 days, until you turn it off in /subscription.",
        'confirm_pay': "✅ Pay {price} so'm",
        'bind': "<b>🔁 {plan} — {price} so'm every 30 days</b>\n\n"
                "1. Tap «Save card» and enter your Uzcard or Humo card and the SMS code on inPAY's page. "
                "There you can also set the most that may be charged at once.\n"
                "2. Come back here: we charge {price} so'm for the first month right away, then every 30 days.\n\n"
                "We remind you 3 days before each charge. Turn it off or remove the card any time in /subscription. "
                "The page stays open for 30 minutes.",
        'save_card': '💳 Save card on inPAY',
        'saved_check': "🔄 I've saved it — continue",
        'bind_waiting': "⏳ We don't see the saved card yet. Finish on inPAY's page, then tap «I've saved it — continue».",
        'bind_closed': 'The page for saving your card has closed. Start again from /plans.',
        'card_paid': '✅ Payment received! {plan} is active until {date}. Thank you!',
        'card_renew_note': "🔁 It renews by itself on {date}: {price} so'm from card •••• {last4}. Turn it off any time in /subscription.",
        'card_failed': "⚠️ We couldn't charge {price} so'm from card •••• {last4} for {plan}: {reason}. Nothing was charged. You can pay another way: /plans",
        'renewed': "🔁 {plan} renewed until {date}: {price} so'm charged from card •••• {last4}. Thank you!",
        'renewal_failed': "⚠️ We couldn't charge {price} so'm from card •••• {last4} to renew {plan}: {reason}. "
                          "We'll try again on {later}. To keep your plan without a break, pay now: /plans",
        'renewal_upcoming': "🔁 Your {plan} renews on {date}: {price} so'm will be charged from card •••• {last4}. "
                            "To stop it, turn auto-renewal off in /subscription.",
        'renewal_stopped': '⚠️ Auto-renewal of {plan} has stopped: {reason}. To keep using {plan}, pay again: /plans',
        'renew_on': "🔁 Auto-renewal: on. Next charge {date}: {price} so'm from card •••• {last4}.",
        'renew_retry': '⚠️ The last renewal charge did not go through. Next try: {date}.',
        'renew_off': 'Auto-renewal: off.',
        'renew_stopped': 'Auto-renewal stopped: {reason}.',
        'card_line': 'Saved card: •••• {last4}',
        'renew_turn_off': '⏸ Turn off auto-renewal',
        'renew_turn_on': '▶️ Turn on auto-renewal',
        'card_remove': '🗑 Remove card •••• {last4}',
        'remove_confirm': 'Remove card •••• {last4}? Auto-renewal stops, and nothing is charged to this card again.',
        'card_remove_yes': '🗑 Remove card',
        'card_removed': 'Your card is removed. No automatic payments will be made from now on.',
        'renew_turned_off': 'Auto-renewal is off. Your plan stays active until {date}, then ends. '
                            'Your card stays saved for paying in one tap; you can remove it below.',
        'renew_turned_on': "🔁 Auto-renewal is on. Next charge {date}: {price} so'm from card •••• {last4}.",
        'reason_declined': 'the bank declined the charge three times',
        'reason_card_removed': 'the card is no longer saved',
        'reason_consent_limit': 'the price is above the limit you set for this card',
        'reason_not_on_sale': 'this plan is no longer sold',
        'reason_review': 'we need to check the last charge, and will message you',
        'reason_CHARGE_FAILED': 'the bank declined it (not enough money, or the card is blocked)',
        'reason_CONSENT_LIMIT': 'the price is above the limit you set for this card',
        'reason_CARD_STATE': 'the card is no longer saved at inPAY',
        'reason_other': 'the payment system did not accept it',
    },
    'uz': {
        'choice': "<b>{icon} {plan} — 30 kun uchun {price} so'm</b>{note}\n\nQanday to‘laysiz?\n\n"
                  "💳 <b>Bir martalik to‘lov</b>: inPAY sahifasida Click, Payme, Uzcard yoki Humo orqali. Hech narsa o‘zi uzaytirilmaydi.\n"
                  "🔁 <b>Har oy avtomatik</b>: Uzcard yoki Humo kartangizdan hozir {price} so'm va keyin har 30 kunda. "
                  "Har yechimdan 3 kun oldin eslatamiz; uni istalgan payt /subscription bo‘limida o‘chirish yoki kartani uzish mumkin.",
        'choice_card': '\n\nSaqlangan kartangiz: •••• {last4}',
        'pay_once': "💳 Bir marta to‘lash — {price} so'm",
        'pay_renew': '🔁 To‘lash va har oy uzaytirish',
        'pay_card': "💳 •••• {last4} bilan {price} so'm to‘lash",
        'pay_card_renew': '🔁 •••• {last4} bilan to‘lash va har oy uzaytirish',
        'pay_other': '🌐 inPAY sahifasida bir marta to‘lash',
        'confirm': "<b>To‘lovni tasdiqlang</b>\n{plan}, 30 kun: •••• {last4} kartadan <b>{price} so'm</b>.",
        'confirm_renew': "\nKeyin har 30 kunda {price} so'm, /subscription bo‘limida o‘chirmaguningizcha.",
        'confirm_pay': "✅ {price} so'm to‘lash",
        'bind': "<b>🔁 {plan} — har 30 kunda {price} so'm</b>\n\n"
                "1. «Kartani saqlash» tugmasini bosing va inPAY sahifasida Uzcard yoki Humo kartangiz hamda SMS kodni kiriting. "
                "U yerda bir martada yechilishi mumkin bo‘lgan eng katta summani ham belgilashingiz mumkin.\n"
                "2. Shu yerga qayting: birinchi oy uchun {price} so'm darhol yechiladi, keyin har 30 kunda.\n\n"
                "Har yechimdan 3 kun oldin eslatamiz. Istalgan payt /subscription bo‘limida o‘chiring yoki kartani uzing. "
                "Sahifa 30 daqiqa ochiq turadi.",
        'save_card': '💳 inPAY’da kartani saqlash',
        'saved_check': '🔄 Saqladim — davom etish',
        'bind_waiting': '⏳ Saqlangan karta hali ko‘rinmayapti. inPAY sahifasida yakunlang, so‘ng «Saqladim — davom etish»ni bosing.',
        'bind_closed': 'Kartani saqlash sahifasi yopildi. /plans dan qaytadan boshlang.',
        'card_paid': '✅ To‘lov qabul qilindi! {plan} tarifi {date} gacha faol. Rahmat!',
        'card_renew_note': "🔁 U {date} kuni o‘zi uzaytiriladi: •••• {last4} kartadan {price} so'm. Istalgan payt /subscription bo‘limida o‘chiring.",
        'card_failed': "⚠️ {plan} uchun •••• {last4} kartadan {price} so'm yecha olmadik: {reason}. Hech narsa yechilmadi. Boshqa usulda to‘lashingiz mumkin: /plans",
        'renewed': "🔁 {plan} {date} gacha uzaytirildi: •••• {last4} kartadan {price} so'm yechildi. Rahmat!",
        'renewal_failed': "⚠️ {plan} ni uzaytirish uchun •••• {last4} kartadan {price} so'm yecha olmadik: {reason}. "
                          "{later} kuni yana urinib ko‘ramiz. Tarif uzilmasligi uchun hozir to‘lang: /plans",
        'renewal_upcoming': "🔁 {plan} tarifingiz {date} kuni uzaytiriladi: •••• {last4} kartadan {price} so'm yechiladi. "
                            "To‘xtatish uchun /subscription bo‘limida avtomatik uzaytirishni o‘chiring.",
        'renewal_stopped': '⚠️ {plan} ning avtomatik uzaytirilishi to‘xtadi: {reason}. {plan} dan foydalanishni davom ettirish uchun qayta to‘lang: /plans',
        'renew_on': "🔁 Avtomatik uzaytirish: yoqilgan. Keyingi yechim {date}: •••• {last4} kartadan {price} so'm.",
        'renew_retry': '⚠️ Oxirgi uzaytirish to‘lovi o‘tmadi. Keyingi urinish: {date}.',
        'renew_off': 'Avtomatik uzaytirish: o‘chirilgan.',
        'renew_stopped': 'Avtomatik uzaytirish to‘xtadi: {reason}.',
        'card_line': 'Saqlangan karta: •••• {last4}',
        'renew_turn_off': '⏸ Avtomatik uzaytirishni o‘chirish',
        'renew_turn_on': '▶️ Avtomatik uzaytirishni yoqish',
        'card_remove': '🗑 •••• {last4} kartani uzish',
        'remove_confirm': '•••• {last4} kartani uzasizmi? Avtomatik uzaytirish to‘xtaydi va bu kartadan boshqa hech narsa yechilmaydi.',
        'card_remove_yes': '🗑 Kartani uzish',
        'card_removed': 'Kartangiz uzildi. Bundan keyin avtomatik to‘lov amalga oshmaydi.',
        'renew_turned_off': 'Avtomatik uzaytirish o‘chirildi. Tarifingiz {date} gacha faol, keyin tugaydi. '
                            'Kartangiz bir bosishda to‘lash uchun saqlanib qoladi; uni pastda uzishingiz mumkin.',
        'renew_turned_on': "🔁 Avtomatik uzaytirish yoqildi. Keyingi yechim {date}: •••• {last4} kartadan {price} so'm.",
        'reason_declined': 'bank yechimni uch marta rad etdi',
        'reason_card_removed': 'karta endi saqlanmagan',
        'reason_consent_limit': 'narx bu karta uchun siz belgilagan chegaradan yuqori',
        'reason_not_on_sale': 'bu tarif endi sotilmaydi',
        'reason_review': 'oxirgi yechimni tekshirishimiz kerak, sizga yozamiz',
        'reason_CHARGE_FAILED': 'bank rad etdi (mablag‘ yetarli emas yoki karta bloklangan)',
        'reason_CONSENT_LIMIT': 'narx bu karta uchun siz belgilagan chegaradan yuqori',
        'reason_CARD_STATE': 'karta inPAY’da endi saqlanmagan',
        'reason_other': 'to‘lov tizimi qabul qilmadi',
    },
    'ru': {
        'choice': "<b>{icon} {plan} — {price} сум за 30 дней</b>{note}\n\nКак хотите оплатить?\n\n"
                  "💳 <b>Один раз</b> на странице inPAY через Click, Payme, Uzcard или Humo. Ничего не продлевается само.\n"
                  "🔁 <b>Каждый месяц</b> с карты Uzcard или Humo: {price} сум сейчас и каждые 30 дней. "
                  "Напомним за 3 дня до каждого списания; отключить или отвязать карту можно в любой момент в /subscription.",
        'choice_card': '\n\nСохранённая карта: •••• {last4}',
        'pay_once': '💳 Оплатить один раз — {price} сум',
        'pay_renew': '🔁 Оплатить и продлевать каждый месяц',
        'pay_card': '💳 Оплатить {price} сум картой •••• {last4}',
        'pay_card_renew': '🔁 Оплатить картой •••• {last4} и продлевать',
        'pay_other': '🌐 Оплатить один раз на странице inPAY',
        'confirm': '<b>Подтвердите оплату</b>\n{plan} на 30 дней: <b>{price} сум</b> с карты •••• {last4}.',
        'confirm_renew': '\nЗатем {price} сум каждые 30 дней, пока вы не отключите продление в /subscription.',
        'confirm_pay': '✅ Оплатить {price} сум',
        'bind': '<b>🔁 {plan} — {price} сум каждые 30 дней</b>\n\n'
                '1. Нажмите «Сохранить карту» и введите карту Uzcard или Humo и код из SMS на странице inPAY. '
                'Там же можно указать наибольшую сумму, которую можно списать за раз.\n'
                '2. Вернитесь сюда: сразу спишем {price} сум за первый месяц, затем каждые 30 дней.\n\n'
                'Напомним за 3 дня до каждого списания. Отключить продление или отвязать карту можно в любой момент в /subscription. '
                'Страница открыта 30 минут.',
        'save_card': '💳 Сохранить карту в inPAY',
        'saved_check': '🔄 Сохранил — продолжить',
        'bind_waiting': '⏳ Сохранённая карта пока не видна. Завершите на странице inPAY и нажмите «Сохранил — продолжить».',
        'bind_closed': 'Страница сохранения карты закрылась. Начните заново в /plans.',
        'card_paid': '✅ Оплата получена! Тариф {plan} действует до {date}. Спасибо!',
        'card_renew_note': '🔁 Он продлится сам {date}: {price} сум с карты •••• {last4}. Отключить можно в любой момент в /subscription.',
        'card_failed': '⚠️ Не удалось списать {price} сум с карты •••• {last4} за {plan}: {reason}. Ничего не списано. Можно оплатить другим способом: /plans',
        'renewed': '🔁 Тариф {plan} продлён до {date}: с карты •••• {last4} списано {price} сум. Спасибо!',
        'renewal_failed': '⚠️ Не удалось списать {price} сум с карты •••• {last4} для продления {plan}: {reason}. '
                          'Попробуем снова {later}. Чтобы тариф не прерывался, оплатите сейчас: /plans',
        'renewal_upcoming': '🔁 Ваш тариф {plan} продлится {date}: с карты •••• {last4} спишется {price} сум. '
                            'Чтобы остановить, отключите автопродление в /subscription.',
        'renewal_stopped': '⚠️ Автопродление {plan} остановлено: {reason}. Чтобы продолжить пользоваться {plan}, оплатите снова: /plans',
        'renew_on': '🔁 Автопродление: включено. Следующее списание {date}: {price} сум с карты •••• {last4}.',
        'renew_retry': '⚠️ Последнее списание за продление не прошло. Следующая попытка: {date}.',
        'renew_off': 'Автопродление: выключено.',
        'renew_stopped': 'Автопродление остановлено: {reason}.',
        'card_line': 'Сохранённая карта: •••• {last4}',
        'renew_turn_off': '⏸ Отключить автопродление',
        'renew_turn_on': '▶️ Включить автопродление',
        'card_remove': '🗑 Отвязать карту •••• {last4}',
        'remove_confirm': 'Отвязать карту •••• {last4}? Автопродление остановится, и с этой карты больше ничего не спишется.',
        'card_remove_yes': '🗑 Отвязать карту',
        'card_removed': 'Карта отвязана. Автоматических списаний больше не будет.',
        'renew_turned_off': 'Автопродление отключено. Тариф действует до {date}, затем закончится. '
                            'Карта остаётся сохранённой для оплаты в одно касание; отвязать её можно ниже.',
        'renew_turned_on': '🔁 Автопродление включено. Следующее списание {date}: {price} сум с карты •••• {last4}.',
        'reason_declined': 'банк трижды отклонил списание',
        'reason_card_removed': 'карта больше не сохранена',
        'reason_consent_limit': 'цена выше лимита, который вы указали для этой карты',
        'reason_not_on_sale': 'этот тариф больше не продаётся',
        'reason_review': 'нам нужно проверить последнее списание, мы напишем вам',
        'reason_CHARGE_FAILED': 'банк отклонил (недостаточно средств или карта заблокирована)',
        'reason_CONSENT_LIMIT': 'цена выше лимита, который вы указали для этой карты',
        'reason_CARD_STATE': 'карта больше не сохранена в inPAY',
        'reason_other': 'платёжная система не приняла списание',
    },
}


def card_copy(account, key):
    return CARD_COPY.get(account.locale, CARD_COPY['en'])[key]


def reason_text(account, code):
    words = CARD_COPY.get(account.locale, CARD_COPY['en'])
    return words.get(f'reason_{code}') or words['reason_other']


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
        # The year paid at once, spread over its months so it compares with the
        # month above; no discount touches it (apps/commerce/pricing.yearly).
        year = offer['yearly'] if plan != 'free' else None
        if year:
            head += '\n' + words['yearly_line'].format(per_month=money(year['per_month']), price=money(year['price']),
                                                       percent=year['percent'])
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


def term_name(account, plan, term):
    """'Plus', or 'Plus · 1 year' for a plan bought for a year, as the payment screens title it."""
    name = plan.title()
    return copy(account, 'plan_year').format(plan=name) if term == 'year' else name


def period_name(account, term):
    """'30 days' or '1 year', in the customer's language."""
    return copy(account, 'period_year' if term == 'year' else 'period_month')


def year_label(account, item):
    """One plan's yearly button: a month of the year, what it saves, and that the year is paid at once.

    The owner's wording: "oyiga 11 000 so'm −45%, yillik to‘lanadi". The
    year's total is on the plan card above and on the payment screen it opens.
    """
    year = item['yearly']
    return copy(account, 'card_pay_year').format(plan=item['plan'].title(), per_month=money(year['per_month']),
                                                 percent=year['percent'])


def card_label(account, item):
    """One plan's monthly button: its price today, and how much off while a discount runs.

    Worded as the yearly button beside it, at the owner's request: "oyiga 20 000 so'm".

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
    from apps.commerce import checkout, manual
    await leave_input_prompt(account)
    # The bot's own inPAY kassa decides how customers pay here (apps/commerce/checkout.py).
    cards = await sync_to_async(manual.options)(account, 'bot')
    automatic = cards['automatic']['available']
    rows = []
    # One way to pay at a time: inPAY while it works, card transfer otherwise.
    # With saved cards on, a plan first asks: once, or every month.
    from apps.commerce import autopay
    renewable = automatic and await sync_to_async(autopay.offered)(account, 'bot')
    action = ('commerce_plan_choice' if renewable else 'commerce_checkout_plan') if automatic else 'commerce_manual_plan'
    for item in cards['plans']:
        rows.append([InlineKeyboardButton(
            text=card_label(account, item),
            callback_data=await callback(account, action, {'plan': item['plan']}),
        )])
        # A year is paid once, on inPAY's page (or by card transfer while that
        # is the way): it never renews from a saved card, so it skips that choice.
        if item.get('yearly'):
            rows.append([InlineKeyboardButton(
                text=year_label(account, item),
                callback_data=await callback(account, 'commerce_checkout_plan' if automatic else 'commerce_manual_plan',
                                             {'plan': item['plan'], 'term': 'year'}),
            )])
    rows.append([await button(account, 'subscription', 'subscription')])
    rows.extend(await navigation(account))
    overview = await sync_to_async(plans_overview)(account)
    words = PLAN_COPY.get(account.locale, PLAN_COPY['en'])
    if automatic:
        tail = words['how_auto']
    elif cards['enabled']:
        tail = words['how']
        # Automatic payment is announced until the owner sets it up; while card
        # transfer only stands in for a moment, it is not "coming soon".
        if not await sync_to_async(checkout.fallback)('bot'):
            tail += '\n\n' + html.escape(copy(account, 'automatic_soon'))
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


async def show_manual(message, account, plan, edit=False, switch=True, term='month'):
    """The card, the price and the code for one plan (a month or a year), and how to send the receipt."""
    from apps.commerce import manual
    await leave_input_prompt(account)
    try:
        payment, _ = await sync_to_async(manual.create)(account, plan, 'bot', term)
    except DomainError as exc:
        # Customers pay through inPAY now: a card-transfer button from before leads there.
        if not switch or exc.code != 'checkout_disabled' or not (await sync_to_async(manual.options)(account, 'bot'))['automatic']['available']:
            raise
        return await show_checkout(message, account, plan, edit, switch=False, term=term)
    await show_manual_payment(message, account, payment, edit)


async def show_checkout(message, account, plan, edit=False, switch=True, term='month'):
    """Open a payment at inPAY for one plan and show the button that leads to its page.

    When inPAY cannot open it, or stopped being the way since the plans were
    shown, card transfer is the way now wherever it is set up: the customer
    is taken there instead of being left with an error.
    """
    import asyncio
    from apps.commerce import checkout, manual
    await leave_input_prompt(account)
    try:
        row, request = await sync_to_async(checkout.begin)(account, plan, 'bot', term)
        if request is not None:
            # inPAY is asked off the thread the bot's queries share: a slow answer holds no other chat up.
            opened, failure = await asyncio.to_thread(checkout.ask, request)
            row = await sync_to_async(checkout.complete)(row, opened, failure)
    except DomainError as exc:
        if not switch or exc.code not in ('checkout_disabled', 'checkout_unavailable') or not (await sync_to_async(manual.options)(account, 'bot'))['enabled']:
            raise
        if exc.code == 'checkout_unavailable':
            # Said first, then the card screen under it as a message of its own.
            await message.answer(copy(account, 'checkout_fallback'))
            edit = False
        return await show_manual(message, account, plan, edit, switch=False, term=term)
    await show_checkout_row(message, account, row, edit)


async def show_checkout_row(message, account, row, edit=False):
    from .bot import callback
    note = await sync_to_async(discount_note)(account, row)
    body = copy(account, 'checkout_screen').format(plan=row.plan.title(), price=money(row.amount),
                                                   period=period_name(account, row.term), note=note)
    if not row.livemode:
        body += copy(account, 'checkout_test_note')
    rows = [
        # A link, not a Mini App: Click and Payme hand over to their own apps, which a browser does and a web view does not.
        [InlineKeyboardButton(text=copy(account, 'checkout_pay').format(price=money(row.amount)), url=row.checkout_url)],
        [InlineKeyboardButton(text=copy(account, 'checkout_check'), callback_data=await callback(account, 'commerce_checkout_check', {'checkout_id': str(row.id)}))],
        *(await navigation(account, 'plans', FROM_PAYMENT)),
    ]
    await show(message, body, rows, edit, 'HTML')


def _checkout_result(account, row):
    """What to say about a payment that is no longer waiting, and that it has been said.

    The same words the paid notice carries, so the notice still queued for
    this chat is not sent after them.
    """
    from apps.commerce.models import PaymentNotice, SubscriptionPeriod
    from .clock import local_time
    if row.status != 'paid':
        return copy(account, 'checkout_refunded' if row.status == 'refunded' else 'checkout_failed')
    kind = 'paid' if row.livemode else 'paid_test'
    PaymentNotice.objects.filter(checkout=row, kind=kind, status__in=('pending', 'retrying')).update(
        status='skipped', error_code='shown_in_chat')
    if not row.livemode:
        return copy(account, 'checkout_paid_test')
    period = SubscriptionPeriod.objects.filter(payment=row.payment).first() if row.payment_id else None
    date = local_time(account, period.ends_at).strftime('%d.%m.%Y') if period else ''
    return copy(account, 'checkout_paid').format(plan=row.plan.title(), date=date)


async def _inquire(row):
    """Ask inPAY about this payment if it is time to, and act on the answer: (row, asked)."""
    import asyncio
    from apps.commerce import checkout, inpay
    question = await sync_to_async(checkout.due)(row)
    if question is None:
        await sync_to_async(row.refresh_from_db)()
        return row, False
    try:
        remote = await asyncio.to_thread(checkout.look, question)
    except inpay.Refused as refused:
        await sync_to_async(checkout.lookup_refused)(refused, row.channel)
        remote = None
    except inpay.Unavailable:
        remote = None
    if remote is None:
        return row, False
    return await sync_to_async(checkout.apply)(row.pk, remote), True


def _settled(row, asked):
    """Whether there is an outcome to tell. A failure only when inPAY has just said
    so: the customer may have paid on the same page since we last asked."""
    return row.status in ('paid', 'refunded') or (asked and row.status in ('failed', 'cancelled', 'expired'))


async def _show_result(message, account, row, edit):
    text = await sync_to_async(_checkout_result)(account, row)
    rows = [[await button(account, 'subscription', 'subscription'), await button(account, 'plans', 'plans', FROM_PAYMENT)],
            *(await navigation(account))]
    return await show(message, text, rows, edit=edit)


async def check_checkout(message, account, checkout_id):
    """«I've paid — check»: ask inPAY about this payment now, and say where it stands."""
    from apps.commerce.models import Checkout
    row = await sync_to_async(lambda: Checkout.objects.filter(pk=checkout_id, account=account).first())()
    if row is None:
        raise DomainError('not_found', 404)
    row, asked = await _inquire(row)
    if _settled(row, asked):
        return await _show_result(message, account, row, edit=True)
    # Still waiting: the Pay button above stays where it is.
    await message.answer(copy(account, 'checkout_waiting'))


async def returned_from_checkout(message, account, reference):
    """Back from inPAY's page: its return link opens the chat with `/start pay_<id>`.

    inPAY is asked about the payment at once and the outcome is said here. A
    payment not seen yet is shown again, with its Pay and check buttons, as
    the money may still be on its way. A link that is not this customer's
    payment leads to the plans.
    """
    import uuid
    from apps.commerce.models import Checkout
    try:
        checkout_id = uuid.UUID(hex=str(reference))
    except ValueError:
        checkout_id = None
    row = await sync_to_async(lambda: Checkout.objects.filter(pk=checkout_id, account=account).exclude(
        status='created').first())() if checkout_id else None
    if row is None:
        return await show_offers(message, account, source='payment')
    row, asked = await _inquire(row)
    if _settled(row, asked):
        return await _show_result(message, account, row, edit=False)
    await message.answer(copy(account, 'checkout_waiting'))
    if row.status == 'pending' and row.checkout_url:
        return await show_checkout_row(message, account, row)
    return await show_offers(message, account, source='payment')


# ---- saved cards and monthly renewal (apps/commerce/autopay.py) ----------------------------------

async def show_plan_choice(message, account, plan, edit=False):
    """Once on inPAY's page, or every month from a saved card: the customer's choice for one plan."""
    from types import SimpleNamespace
    from .bot import callback
    from apps.commerce import autopay
    await leave_input_prompt(account)
    price = ((await sync_to_async(autopay.offers)()).get(plan) or {}).get('price')
    if not price or not await sync_to_async(autopay.offered)(account, 'bot'):
        return await show_checkout(message, account, plan, edit)
    # Only a card saved in the bot is charged from here: the website's belongs to the website's kassa.
    card = await sync_to_async(autopay.active_card)(account, 'bot')
    note = await sync_to_async(discount_note)(account, SimpleNamespace(plan=plan, amount=price))
    values = {'plan': plan.title(), 'price': money(price), 'icon': PLAN_ICONS.get(plan, '⭐'), 'note': note}
    body = card_copy(account, 'choice').format(**values)
    if card:
        body += card_copy(account, 'choice_card').format(last4=html.escape(card.last4))
        rows = [
            [InlineKeyboardButton(text=card_copy(account, 'pay_card_renew').format(last4=card.last4),
                                  callback_data=await callback(account, 'commerce_card_confirm', {'plan': plan, 'renew': True}))],
            [InlineKeyboardButton(text=card_copy(account, 'pay_card').format(price=money(price), last4=card.last4),
                                  callback_data=await callback(account, 'commerce_card_confirm', {'plan': plan, 'renew': False}))],
            [InlineKeyboardButton(text=card_copy(account, 'pay_other'),
                                  callback_data=await callback(account, 'commerce_checkout_plan', {'plan': plan}))],
        ]
    else:
        rows = [
            [InlineKeyboardButton(text=card_copy(account, 'pay_renew'),
                                  callback_data=await callback(account, 'commerce_card_bind', {'plan': plan}))],
            [InlineKeyboardButton(text=card_copy(account, 'pay_once').format(price=money(price)),
                                  callback_data=await callback(account, 'commerce_checkout_plan', {'plan': plan}))],
        ]
    rows.extend(await navigation(account, 'plans', FROM_PAYMENT))
    await show(message, body, rows, edit, 'HTML')


async def show_card_confirm(message, account, plan, renew, edit=False):
    """One more tap before a saved card is charged: the amount, the card, and whether it renews."""
    from .bot import callback
    from apps.commerce import autopay
    card = await sync_to_async(autopay.active_card)(account, 'bot')
    price = ((await sync_to_async(autopay.offers)()).get(plan) or {}).get('price')
    if card is None or not price:
        return await show_plan_choice(message, account, plan, edit)
    body = card_copy(account, 'confirm').format(plan=plan.title(), price=money(price), last4=html.escape(card.last4))
    if renew:
        body += card_copy(account, 'confirm_renew').format(price=money(price))
    rows = [[InlineKeyboardButton(text=card_copy(account, 'confirm_pay').format(price=money(price)),
                                  callback_data=await callback(account, 'commerce_card_pay',
                                                               {'plan': plan, 'renew': bool(renew), 'card_id': str(card.id)}))],
            [await button(account, 'back', 'commerce_plan_choice', {'plan': plan})]]
    await show(message, body, rows, edit, 'HTML')


async def pay_with_card(message, account, plan, renew, card_id):
    """Charge the saved card for `plan` and say how it went; with `renew`, renewal turns on."""
    import asyncio
    from apps.commerce import autopay
    from apps.commerce.models import SavedCard
    await leave_input_prompt(account)
    card = await sync_to_async(lambda: SavedCard.objects.filter(pk=card_id, account=account, status='active', kassa='bot').first())()
    if card is None:
        return await show_plan_choice(message, account, plan, edit=True)
    row, request = await sync_to_async(autopay.begin_charge)(account, card, plan, 'first' if renew else 'one_tap', channel='bot')
    if request is not None:
        answer, failure = await asyncio.to_thread(autopay.ask_charge, request)
        row = await sync_to_async(autopay.apply_charge)(row.pk, answer, failure)
    if renew:
        await sync_to_async(autopay.after_first)(row)
    await show_charge_result(message, account, row, edit=True)


def _shown_in_chat(row, kind):
    """The notice the next run would send about this charge, said here already."""
    from apps.commerce.models import PaymentNotice
    notice, _ = PaymentNotice.objects.get_or_create(charge=row, kind=kind)
    PaymentNotice.objects.filter(pk=notice.pk, status__in=('pending', 'retrying')).update(status='skipped', error_code='shown_in_chat')


def charge_result_text(account, row):
    from apps.commerce import autopay
    from .clock import local_time
    if row.status == 'paid':
        period = autopay.period_of(row)
        text = card_copy(account, 'card_paid').format(plan=row.plan.title(), date=local_time(account, period.ends_at).strftime('%d.%m.%Y') if period else '')
        renewal = autopay.renewal(account)
        if row.purpose == 'first' and renewal and renewal.status == 'on':
            text += '\n' + card_copy(account, 'card_renew_note').format(
                date=local_time(account, renewal.renews_at).strftime('%d.%m.%Y'), price=money(row.amount), last4=row.card.last4)
        _shown_in_chat(row, 'card_paid')
        return text
    if row.status == 'failed':
        _shown_in_chat(row, 'card_failed')
        return card_copy(account, 'card_failed').format(price=money(row.amount), last4=row.card.last4, plan=row.plan.title(),
                                                        reason=reason_text(account, row.failure))
    # inPAY's answer was lost: the next run asks again under the same key and messages the customer.
    return copy(account, 'checkout_waiting')


async def show_charge_result(message, account, row, edit=False):
    text = await sync_to_async(charge_result_text)(account, row)
    rows = [[await button(account, 'subscription', 'subscription'), await button(account, 'plans', 'plans', FROM_PAYMENT)],
            *(await navigation(account))]
    await show(message, text, rows, edit)


async def show_binding(message, account, plan, edit=False):
    """Open inPAY's page for saving a card, for paying for `plan` and renewing it every month."""
    import asyncio
    from apps.commerce import autopay
    await leave_input_prompt(account)
    try:
        card, request = await sync_to_async(autopay.begin_binding)(account, plan, 'bot')
        if request is not None:
            answer, failure = await asyncio.to_thread(autopay.ask_binding, request)
            card = await sync_to_async(autopay.complete_binding)(card, answer, failure)
    except DomainError as exc:
        # Saved cards are not on, or inPAY's page could not be opened: paying once is still there.
        if exc.code not in ('autopay_unavailable', 'checkout_disabled'):
            raise
        return await show_checkout(message, account, plan, edit)
    await show_binding_card(message, account, card, edit)


async def show_binding_card(message, account, card, edit=False):
    from .bot import callback
    from apps.commerce import autopay
    plan = card.intent or 'plus'
    price = ((await sync_to_async(autopay.offers)()).get(plan) or {}).get('price') or 0
    body = card_copy(account, 'bind').format(plan=plan.title(), price=money(price))
    rows = [
        # A link, not a Mini App: the bank's SMS page works the same in any browser.
        [InlineKeyboardButton(text=card_copy(account, 'save_card'), url=card.bind_url)],
        [InlineKeyboardButton(text=card_copy(account, 'saved_check'),
                              callback_data=await callback(account, 'commerce_card_check', {'card_id': str(card.id)}))],
        *(await navigation(account, 'plans', FROM_PAYMENT)),
    ]
    await show(message, body, rows, edit, 'HTML')


async def check_binding(message, account, reference, edit=False):
    """«I've saved it»: ask inPAY whether the card is saved; then pay for the plan and turn renewal on."""
    import asyncio
    import uuid
    from apps.commerce import autopay
    from apps.commerce.models import SavedCard
    try:
        card_id = uuid.UUID(str(reference))
    except ValueError:
        card_id = None
    card = await sync_to_async(lambda: SavedCard.objects.filter(pk=card_id, account=account).first())() if card_id else None
    if card is None:
        return await show_offers(message, account, source='payment')
    if card.status == 'binding':
        question = await sync_to_async(autopay.look_cards)(card)
        if question is not None:
            cards, _ = await asyncio.to_thread(autopay.ask_cards, question)
            if cards is not None:
                card = await sync_to_async(autopay.apply_cards)(card.pk, cards)
    if card.status == 'binding':
        await message.answer(card_copy(account, 'bind_waiting'))
        return await show_binding_card(message, account, card)
    if card.status != 'active':
        await message.answer(card_copy(account, 'bind_closed'))
        return await show_offers(message, account, source='payment')
    plan = await sync_to_async(autopay.claim_intent)(card)
    if not plan:
        # Saved already, and its first month paid (here or by the periodic run): say where it stands.
        return await show_subscription(message, account, edit=edit)
    row, request = await sync_to_async(autopay.begin_charge)(account, card, plan, 'first')
    if request is not None:
        answer, failure = await asyncio.to_thread(autopay.ask_charge, request)
        row = await sync_to_async(autopay.apply_charge)(row.pk, answer, failure)
    await sync_to_async(autopay.after_first)(row)
    await show_charge_result(message, account, row, edit=edit)


async def renewal_lines(account):
    """The saved card and renewal, under the plan on the subscription screen, and their buttons."""
    from .bot import callback
    from apps.commerce import autopay
    from .clock import local_time
    state = await sync_to_async(autopay.status)(account, 'bot')
    card, plan = state['card'], state['renewal']
    lines, rows = [], []
    if plan and plan['status'] == 'on' and card:
        date = local_time(account, plan['renews_at']).strftime('%d.%m.%Y')
        lines.append(card_copy(account, 'renew_on').format(date=date, price=money(plan['amount']) if plan['amount'] else '—',
                                                           last4=html.escape(card['last4'])))
        if plan['attempts'] and plan['next_try_at']:
            lines.append(card_copy(account, 'renew_retry').format(date=local_time(account, plan['next_try_at']).strftime('%d.%m.%Y')))
        rows.append([InlineKeyboardButton(text=card_copy(account, 'renew_turn_off'),
                                          callback_data=await callback(account, 'commerce_renew_off'))])
    elif card:
        if plan and plan['status'] == 'stopped':
            lines.append(card_copy(account, 'renew_stopped').format(reason=html.escape(reason_text(account, plan['stopped_reason']))))
        elif plan:
            lines.append(card_copy(account, 'renew_off'))
        lines.append(card_copy(account, 'card_line').format(last4=html.escape(card['last4'])))
        if state['can_turn_on']:
            rows.append([InlineKeyboardButton(text=card_copy(account, 'renew_turn_on'),
                                              callback_data=await callback(account, 'commerce_renew_on'))])
    if card:
        # inPAY's contract: the customer can always take the card away from here.
        rows.append([InlineKeyboardButton(text=card_copy(account, 'card_remove').format(last4=card['last4']),
                                          callback_data=await callback(account, 'commerce_card_remove', {'card_id': card['id']}))])
    return lines, rows


async def show_card_remove(message, account, card_id, edit=False):
    from .bot import callback
    from apps.commerce.models import SavedCard
    card = await sync_to_async(lambda: SavedCard.objects.filter(pk=card_id, account=account, status__in=('active', 'binding')).first())()
    if card is None:
        return await show_subscription(message, account, edit)
    rows = [[InlineKeyboardButton(text=card_copy(account, 'card_remove_yes'),
                                  callback_data=await callback(account, 'commerce_card_remove_yes', {'card_id': str(card.id)}))],
            [await button(account, 'back', 'subscription')]]
    await show(message, card_copy(account, 'remove_confirm').format(last4=card.last4), rows, edit)


async def remove_card(message, account, card_id):
    import asyncio
    from apps.commerce import autopay
    card, request = await sync_to_async(autopay.begin_removal)(account, card_id)
    done, _ = await asyncio.to_thread(autopay.ask_removal, request)
    await sync_to_async(autopay.finish_removal)(card, done)
    rows = [[await button(account, 'subscription', 'subscription'), await button(account, 'plans', 'plans', FROM_PAYMENT)],
            *(await navigation(account))]
    await show(message, card_copy(account, 'card_removed'), rows, edit=True)


async def switch_renewal(message, account, on):
    from apps.commerce import autopay
    from .clock import local_time
    if on:
        renewal = await sync_to_async(autopay.turn_on)(account)
        price = ((await sync_to_async(autopay.offers)()).get(renewal.plan) or {}).get('price')
        text = card_copy(account, 'renew_turned_on').format(date=local_time(account, renewal.renews_at).strftime('%d.%m.%Y'),
                                                            price=money(price) if price else '—', last4=renewal.card.last4)
    else:
        await sync_to_async(autopay.turn_off)(account)
        until = await sync_to_async(autopay.paid_until)(account)
        text = card_copy(account, 'renew_turned_off').format(date=local_time(account, until).strftime('%d.%m.%Y') if until else '—')
    await message.answer(text)
    await show_subscription(message, account)


def discount_note(account, payment):
    """The regular price struck through, with how much off until when, under the
    title of a payment screen that asks for a discounted amount; otherwise ''.

    Only when the plan's discount runs today and the request is for exactly
    the discounted price. A request at the regular price, opened before the
    discount or reopened after its last day, is asked for as the plans screen
    shows it, and a note about a discount would contradict the amount.
    """
    from apps.commerce.pricing import plan_price
    # A year has its own price, which no discount lowers.
    if getattr(payment, 'term', 'month') == 'year':
        return ''
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
              'holder': holder, 'reference': payment.reference, 'note': '', 'period': period_name(account, payment.term)}
    if payment.status == 'submitted':
        # "(Plus · 1 year, 132 000 so'm)": the waiting line has no period of its own to say it.
        body = copy(account, 'manual_waiting').format(**{**values, 'plan': term_name(account, payment.plan, payment.term)})
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


def _invite_months_ahead(account):
    """Whether Plus months earned by inviting friends are running or still to come."""
    from apps.commerce.models import SubscriptionPeriod
    return SubscriptionPeriod.objects.filter(account=account, payment__provider='referral', revoked_at__isnull=True,
                                             ends_at__gt=timezone.now()).exists()


async def show_subscription(message, account, edit=False):
    """The plan, and until when it is paid for; the saved card and its monthly
    renewal, with the buttons to turn renewal off and to remove the card. A plan
    paid once covers 30 days and never renews by itself: there is only the
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
        from .invites import copy as invite_copy
        rewarded = await sync_to_async(_invite_months_ahead)(account)
        lines = [f'<b>{html.escape(sub["plan"].title())}</b>']
        if sub['active_until']:
            # Months earned by inviting friends were not paid for: say what they are.
            label = invite_copy(account.locale, 'active_label') if sub['provider'] == 'referral' else copy(account, 'active_until')
            lines.append(f'{label}: {stamp(account, sub["current_period_end"])}')
        else:
            lines.append(copy(account, 'expired'))
        if rewarded:
            lines.append(invite_copy(account.locale, 'from_invites'))
    renewal, switches = await renewal_lines(account)
    if renewal:
        lines += [''] + renewal
    rows = [*switches, [await button(account, 'plans', 'plans', {'from': 'subscription'})], *(await navigation(account))]
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
                await show_manual(query.message, account, ref.payload['plan'], edit=True, term=ref.payload.get('term') or 'month')
            elif ref.action == 'commerce_checkout_plan':
                await show_checkout(query.message, account, ref.payload['plan'], edit=True, term=ref.payload.get('term') or 'month')
            elif ref.action == 'commerce_checkout_check':
                await check_checkout(query.message, account, ref.payload['checkout_id'])
            elif ref.action == 'commerce_plan_choice':
                await show_plan_choice(query.message, account, ref.payload['plan'], edit=True)
            elif ref.action == 'commerce_card_confirm':
                await show_card_confirm(query.message, account, ref.payload['plan'], ref.payload.get('renew'), edit=True)
            elif ref.action == 'commerce_card_pay':
                await pay_with_card(query.message, account, ref.payload['plan'], ref.payload.get('renew'), ref.payload['card_id'])
            elif ref.action == 'commerce_card_bind':
                await show_binding(query.message, account, ref.payload['plan'], edit=True)
            elif ref.action == 'commerce_card_check':
                await check_binding(query.message, account, ref.payload['card_id'])
            elif ref.action == 'commerce_renew_off':
                await switch_renewal(query.message, account, on=False)
            elif ref.action == 'commerce_renew_on':
                await switch_renewal(query.message, account, on=True)
            elif ref.action == 'commerce_card_remove':
                await show_card_remove(query.message, account, ref.payload['card_id'], edit=True)
            elif ref.action == 'commerce_card_remove_yes':
                await remove_card(query.message, account, ref.payload['card_id'])
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
