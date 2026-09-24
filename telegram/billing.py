"""Telegram Stars screens. Financial decisions remain in commerce services."""
import html

from asgiref.sync import sync_to_async
from aiogram import F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from django.utils import timezone

from apps.core.errors import DomainError
from apps.core.models import BotCallback, BotConversation
from apps.commerce import services
from apps.commerce.serializers import subscription_data

COPY = {
    'en': {
        'offers': '⭐ Plans & packs\nChoose one to see what’s included.',
        'sandbox': '🧪 Test payment — no real Telegram Stars spent.',
        'live': 'Pay with Telegram Stars. Your balance updates after confirmation.',
        'pay': '⭐ Pay in Telegram', 'simulate': '🧪 Try test payment',
        'confirmed': '✅ Paid! Your plan and balance are ready.',
        'unavailable': 'Payments aren’t ready yet. You can keep using your current plan.',
        'cancel': '⏸ Turn renewal off', 'resume': '▶️ Turn renewal on',
        'renewal_on': '🔄 Auto-renewal: on', 'renewal_off': '⏸ Auto-renewal: off',
        'active_until': 'Paid access until', 'scheduled': 'Next plan',
        'updated': '✅ Updated. Your paid access stays the same.',
        'support': 'Need a hand with this payment? Tap Payment support.',
        'payment_support': '💬 Payment support', 'home': '🏠 Main menu', 'back': '← Back',
        'plans': '⭐ Plans & packs', 'subscription': '💳 Subscription', 'balance': 'Included',
        'file_tasks': 'File tasks', 'file_page_units': 'Page units', 'ai_credits': 'AI credits',
        'task_pack': 'Extra file tasks', 'ai_pack': 'Extra AI credits', 'free': 'Free',
        'price': 'Price', 'period': 'Renews every 30 days', 'once': 'One-time payment',
        'review': '🧾 Your purchase', 'expires': 'Checkout expires in 10 minutes.',
        'no_subscription': 'You’re on Free. No paid subscription to manage.',
        'expired': 'Your subscription has ended. Pick a plan to continue.',
        'confirm_off': '⏸ Turn renewal off?\nKeep your paid access until {date}. No charge for the next period.',
        'confirm_on': '🔄 Turn renewal on?\nTelegram will renew your plan at the end of each paid period. Any scheduled plan change will be cancelled.',
        'confirm_change': '🔄 Switch to {plan} after {date}?\nKeep your current plan until then. Auto-renewal will stop. A new paid plan needs a separate payment.',
        'confirm': '✅ Confirm change', 'keep': '← Keep settings',
        'invalid_invoice': '⚠️ Couldn’t verify this payment. Try a new checkout or use /paysupport.',
    },
    'uz': {
        'offers': '⭐ Tariflar va paketlar\nTafsilotlarni ko‘rish uchun birini tanlang.',
        'sandbox': '🧪 Sinov to‘lovi — haqiqiy Telegram Stars sarflanmaydi.',
        'live': 'Telegram Stars bilan to‘lang. To‘lov tasdiqlangach, balans yangilanadi.',
        'pay': '⭐ Telegram’da to‘lash', 'simulate': '🧪 Sinov to‘lovi',
        'confirmed': '✅ To‘landi! Tarif va balansingiz tayyor.',
        'unavailable': 'To‘lov hozircha ishlamayapti. Joriy tarifdan foydalanishingiz mumkin.',
        'cancel': '⏸ Uzaytirishni o‘chirish', 'resume': '▶️ Uzaytirishni yoqish',
        'renewal_on': '🔄 Avto-uzaytirish: yoqilgan', 'renewal_off': '⏸ Avto-uzaytirish: o‘chirilgan',
        'active_until': 'Pulli tarif muddati', 'scheduled': 'Keyingi tarif',
        'updated': '✅ Yangilandi. Pulli tarif muddati o‘zgarmadi.',
        'support': 'To‘lovda yordam kerakmi? «To‘lov bo‘yicha yordam»ni bosing.',
        'payment_support': '💬 To‘lov bo‘yicha yordam', 'home': '🏠 Bosh menyu', 'back': '← Orqaga',
        'plans': '⭐ Tariflar va paketlar', 'subscription': '💳 Obuna', 'balance': 'Paketda',
        'file_tasks': 'Fayl vazifalari', 'file_page_units': 'Sahifa birligi', 'ai_credits': 'AI kreditlari',
        'task_pack': 'Qo‘shimcha fayl vazifalari', 'ai_pack': 'Qo‘shimcha AI kreditlari', 'free': 'Bepul',
        'price': 'Narx', 'period': 'Har 30 kunda uzaytiriladi', 'once': 'Bir martalik to‘lov',
        'review': '🧾 Xaridingiz', 'expires': 'To‘lov havolasi 10 daqiqa amal qiladi.',
        'no_subscription': 'Siz Bepul tarifdasiz. Pulli obunangiz yo‘q.',
        'expired': 'Obunangiz tugagan. Davom etish uchun tarif tanlang.',
        'confirm_off': '⏸ Uzaytirish o‘chirilsinmi?\nPulli tarif {date} gacha saqlanadi. Keyingi davr uchun to‘lov olinmaydi.',
        'confirm_on': '🔄 Uzaytirish yoqilsinmi?\nTelegram har bir pulli davr oxirida tarifni uzaytiradi. Rejalangan tarif o‘zgarishi bekor qilinadi.',
        'confirm_change': '🔄 {date} dan keyin {plan} tarifiga o‘tilsinmi?\nJoriy tarif shu vaqtgacha saqlanadi. Avto-uzaytirish to‘xtaydi. Yangi pulli tarif uchun alohida to‘lov kerak.',
        'confirm': '✅ Tasdiqlash', 'keep': '← O‘zgartirmaslik',
        'invalid_invoice': '⚠️ To‘lovni tekshira olmadik. Yangi to‘lovni oching yoki /paysupport orqali yozing.',
    },
    'ru': {
        'offers': '⭐ Тарифы и пакеты\nВыберите вариант, чтобы узнать подробности.',
        'sandbox': '🧪 Тестовая оплата — настоящие Telegram Stars не списываются.',
        'live': 'Оплата через Telegram Stars. Баланс обновится после подтверждения.',
        'pay': '⭐ Оплатить в Telegram', 'simulate': '🧪 Тестовая оплата',
        'confirmed': '✅ Оплачено! Тариф и баланс готовы.',
        'unavailable': 'Оплата пока недоступна. Текущий тариф продолжает работать.',
        'cancel': '⏸ Отключить продление', 'resume': '▶️ Включить продление',
        'renewal_on': '🔄 Автопродление: включено', 'renewal_off': '⏸ Автопродление: выключено',
        'active_until': 'Оплачено до', 'scheduled': 'Следующий тариф',
        'updated': '✅ Готово. Оплаченный срок не изменился.',
        'support': 'Нужна помощь? Нажмите «Помощь по оплате».',
        'payment_support': '💬 Помощь по оплате', 'home': '🏠 Главное меню', 'back': '← Назад',
        'plans': '⭐ Тарифы и пакеты', 'subscription': '💳 Подписка', 'balance': 'Включено',
        'file_tasks': 'Задачи с файлами', 'file_page_units': 'Единицы страниц', 'ai_credits': 'AI-кредиты',
        'task_pack': 'Дополнительные задачи', 'ai_pack': 'Дополнительные AI-кредиты', 'free': 'Бесплатный',
        'price': 'Цена', 'period': 'Продление каждые 30 дней', 'once': 'Разовый платёж',
        'review': '🧾 Ваша покупка', 'expires': 'Ссылка на оплату действует 10 минут.',
        'no_subscription': 'У вас бесплатный тариф. Платной подписки нет.',
        'expired': 'Подписка закончилась. Выберите тариф, чтобы продолжить.',
        'confirm_off': '⏸ Отключить продление?\nОплаченный доступ сохранится до {date}. Следующего списания не будет.',
        'confirm_on': '🔄 Включить продление?\nTelegram будет продлевать тариф в конце каждого оплаченного периода. Запланированная смена тарифа отменится.',
        'confirm_change': '🔄 Перейти на {plan} после {date}?\nТекущий тариф сохранится до этой даты. Автопродление отключится. Новый платный тариф нужно оплатить отдельно.',
        'confirm': '✅ Подтвердить', 'keep': '← Не менять',
        'invalid_invoice': '⚠️ Не удалось проверить платёж. Начните оплату заново или напишите в /paysupport.',
    },
}


def copy(account, key):
    return COPY.get(account.locale, COPY['en'])[key]


def offer_name(account, offer):
    value = services.offer_data(offer) if not isinstance(offer, dict) else offer
    if value.get('plan'):
        return value['plan'].title()
    return copy(account, 'ai_pack' if value['kind'] == 'ai_pack' else 'task_pack')


async def button(account, label, action, payload=None):
    from .bot import callback
    return InlineKeyboardButton(text=copy(account, label), callback_data=await callback(account, action, payload))


async def navigation(account, back=None):
    rows = []
    if back:
        rows.append([await button(account, 'back', back)])
    rows.append([await button(account, 'home', 'home')])
    return rows


async def leave_input_prompt(account):
    # Opening billing is navigation, so a later ordinary reply must not be
    # interpreted as a forgotten page-range or support-message prompt.
    await sync_to_async(lambda: BotConversation.objects.filter(pk=account.telegram_user_id).update(state='', prompt={}, updated_at=timezone.now()))()


async def show_offers(message, account):
    from .bot import callback
    await leave_input_prompt(account)
    offers = await sync_to_async(services.available_offers)(account)
    rows = []
    for offer in offers:
        rows.append([InlineKeyboardButton(
            text=f'{offer_name(account, offer)} · ⭐ {offer.price_xtr}',
            callback_data=await callback(account, 'commerce_offer', {'offer_id': offer.offer_id}),
        )])
    rows.append([await button(account, 'subscription', 'subscription')])
    rows.extend(await navigation(account))
    body = copy(account, 'offers' if offers else 'unavailable')
    if offers:
        body += '\n\n' + copy(account, 'sandbox' if offers[0].sandbox else 'live')
    await message.answer(body, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


async def show_invoice(message, account, offer_id, key):
    from .bot import callback
    await leave_input_prompt(account)
    invoice, _ = await sync_to_async(services.create_invoice)(account, offer_id, key)
    invoice = await sync_to_async(services.present_invoice)(invoice)
    if invoice.sandbox:
        pay = InlineKeyboardButton(text=copy(account, 'simulate'), callback_data=await callback(account, 'commerce_pay', {'invoice_id': str(invoice.id)}))
    else:
        pay = InlineKeyboardButton(text=copy(account, 'pay'), url=invoice.invoice_url)
    lines = [f'<b>{copy(account, "review")}</b>', html.escape(offer_name(account, invoice.snapshot)),
             f'{copy(account, "price")}: ⭐ {invoice.amount_xtr} Telegram Stars',
             copy(account, 'period' if invoice.snapshot['kind'] == 'subscription' else 'once'),
             '', copy(account, 'balance') + ':']
    lines.extend(f'• {copy(account, meter)}: {quantity:,}' for meter, quantity in invoice.snapshot['quantities'].items() if quantity)
    lines.extend(['', copy(account, 'sandbox' if invoice.sandbox else 'live'), copy(account, 'expires')])
    rows = [[pay], *(await navigation(account, 'plans'))]
    await message.answer('\n'.join(lines), parse_mode='HTML', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


async def show_subscription(message, account):
    await leave_input_prompt(account)
    data = await sync_to_async(subscription_data)(account)
    sub = data['subscription']
    rows = []
    if not sub:
        lines = [copy(account, 'no_subscription')]
    else:
        lines = [f'<b>{html.escape(sub["plan"].title())}</b>']
        if sub['active_until']:
            lines.extend([copy(account, 'renewal_on' if sub['renewal_enabled'] else 'renewal_off'),
                          f'{copy(account, "active_until")}: {sub["current_period_end"]:%Y-%m-%d %H:%M} UTC'])
            rows.append([await button(account, 'cancel' if sub['renewal_enabled'] else 'resume',
                                      'commerce_cancel' if sub['renewal_enabled'] else 'commerce_resume', {'subscription_id': sub['id']})])
        else:
            lines.append(copy(account, 'expired'))
        if sub['scheduled_plan']:
            name = copy(account, 'free') if sub['scheduled_plan'] == 'free' else sub['scheduled_plan'].title()
            lines.append(f'{copy(account, "scheduled")}: {name}')
        if sub['sandbox']:
            lines.extend(['', copy(account, 'sandbox')])
    rows.append([await button(account, 'plans', 'plans')])
    rows.extend(await navigation(account))
    await message.answer('\n'.join(lines), parse_mode='HTML', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


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
            date=f'{sub["current_period_end"]:%Y-%m-%d %H:%M} UTC',
            plan=copy(account, 'free') if plan == 'free' else plan.title(),
        )
        action, payload = 'commerce_plan_confirm', {'subscription_id': sub['id'], 'plan': plan}
    else:
        body = copy(account, 'confirm_on' if enabled else 'confirm_off').format(date=f'{sub["current_period_end"]:%Y-%m-%d %H:%M} UTC')
        action, payload = 'commerce_renewal_confirm', {'subscription_id': sub['id'], 'enabled': enabled}
    rows = [[await button(account, 'confirm', action, payload)],
            [await button(account, 'keep', 'subscription')], *(await navigation(account))]
    await message.answer(body, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


async def payment_navigation(account):
    return InlineKeyboardMarkup(inline_keyboard=[
        [await button(account, 'subscription', 'subscription'), await button(account, 'plans', 'plans')],
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

    @dp.message(Command('buy', 'plans'))
    async def buy(message):
        account = await account_for(message.from_user)
        try:
            values = message.text.split(maxsplit=1)
            if len(values) > 1:
                return await show_invoice(message, account, values[1].strip(), f'telegram:{message.chat.id}:{message.message_id}')
            await show_offers(message, account)
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
        ref = await sync_to_async(lambda: BotCallback.objects.filter(token=query.data, account__telegram_user_id=query.from_user.id, action__startswith='commerce_', expires_at__gt=timezone.now()).first())()
        if not ref:
            raise SkipHandler()
        # Stop the Telegram loading spinner before an invoice/provider request.
        await query.answer()
        account = await account_for(query.from_user)
        try:
            if ref.action == 'commerce_offer':
                await show_invoice(query.message, account, ref.payload['offer_id'], f'telegram:{ref.token}')
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
