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
        'offers': 'Plans & credits\nChoose an option to review its price and included balance.',
        'sandbox': 'Test checkout: no real Telegram Stars are spent.',
        'live': 'Pay securely with Telegram Stars. Access changes only after payment is confirmed.',
        'pay': 'Pay in Telegram', 'simulate': 'Simulate local payment',
        'confirmed': 'Payment confirmed. Your plan and balance are ready to use.',
        'unavailable': 'Checkout is not available yet. Your current plan remains available.',
        'cancel': 'Turn renewal off', 'resume': 'Turn renewal on',
        'renewal_on': 'Automatic renewal: on', 'renewal_off': 'Automatic renewal: off',
        'active_until': 'Paid access until', 'scheduled': 'Next plan',
        'updated': 'Subscription updated. Your current paid access is unchanged.',
        'support': 'Need help with this payment? Choose Payment support below.',
        'payment_support': 'Payment support', 'home': 'Main menu', 'back': 'Back',
        'plans': 'Plans & credits', 'subscription': 'My subscription', 'balance': 'Included balance',
        'file_tasks': 'File tasks', 'file_page_units': 'Page units', 'ai_credits': 'AI credits',
        'task_pack': 'Extra file tasks', 'ai_pack': 'Extra AI credits', 'free': 'Free',
        'price': 'Price', 'period': 'Every 30 days', 'once': 'One-time purchase',
        'review': 'Review your purchase', 'expires': 'This checkout is available for 10 minutes.',
        'no_subscription': 'You are on the Free plan. There is no paid renewal to manage.',
        'expired': 'This subscription has ended. Choose a plan to start again.',
        'confirm_off': 'Turn automatic renewal off?\nYour paid access stays available until {date}. You will not be charged for the next period.',
        'confirm_on': 'Turn automatic renewal on?\nTelegram will renew your current plan at the end of each paid period. Any scheduled plan change will be removed.',
        'confirm_change': 'Switch to {plan} after {date}?\nYour current paid access continues until then. Automatic renewal will stop. A new paid plan needs a separate checkout.',
        'confirm': 'Confirm change', 'keep': 'Keep current settings',
        'invalid_invoice': 'This payment could not be verified. Open a new checkout or contact /paysupport.',
    },
    'uz': {
        'offers': 'Tariflar va kreditlar\nNarx va kiritilgan limitlarni ko‘rish uchun taklifni tanlang.',
        'sandbox': 'Sinov to‘lovi: haqiqiy Telegram Stars sarflanmaydi.',
        'live': 'Telegram Stars orqali xavfsiz to‘lang. Limitlar faqat to‘lov tasdiqlangandan keyin yangilanadi.',
        'pay': 'Telegram’da to‘lash', 'simulate': 'Mahalliy to‘lovni sinash',
        'confirmed': 'To‘lov tasdiqlandi. Tarif va limitlaringiz foydalanishga tayyor.',
        'unavailable': 'To‘lov hozircha mavjud emas. Joriy tarifingizdan foydalanishingiz mumkin.',
        'cancel': 'Uzaytirishni o‘chirish', 'resume': 'Uzaytirishni yoqish',
        'renewal_on': 'Avtomatik uzaytirish: yoqilgan', 'renewal_off': 'Avtomatik uzaytirish: o‘chirilgan',
        'active_until': 'Pulli tarif muddati', 'scheduled': 'Keyingi tarif',
        'updated': 'Obuna yangilandi. Joriy pulli kirish muddati o‘zgarmadi.',
        'support': 'To‘lov bo‘yicha yordam kerakmi? Quyidagi yordam tugmasini tanlang.',
        'payment_support': 'To‘lov bo‘yicha yordam', 'home': 'Bosh menyu', 'back': 'Orqaga',
        'plans': 'Tariflar va kreditlar', 'subscription': 'Mening obunam', 'balance': 'Kiritilgan limitlar',
        'file_tasks': 'Fayl vazifalari', 'file_page_units': 'Sahifa birliklari', 'ai_credits': 'AI kreditlari',
        'task_pack': 'Qo‘shimcha fayl vazifalari', 'ai_pack': 'Qo‘shimcha AI kreditlari', 'free': 'Bepul',
        'price': 'Narx', 'period': 'Har 30 kunda', 'once': 'Bir martalik xarid',
        'review': 'Xaridni tekshiring', 'expires': 'Ushbu to‘lov havolasi 10 daqiqa amal qiladi.',
        'no_subscription': 'Siz Bepul tarifdasiz. Boshqarish uchun pulli obuna mavjud emas.',
        'expired': 'Bu obuna tugagan. Qayta boshlash uchun tarif tanlang.',
        'confirm_off': 'Avtomatik uzaytirish o‘chirilsinmi?\nPulli kirish {date} gacha saqlanadi. Keyingi davr uchun to‘lov olinmaydi.',
        'confirm_on': 'Avtomatik uzaytirish yoqilsinmi?\nTelegram har bir pulli davr oxirida joriy tarifni uzaytiradi. Rejalashtirilgan tarif o‘zgarishi bekor qilinadi.',
        'confirm_change': '{date} dan keyin {plan} tarifiga o‘tilsinmi?\nJoriy pulli kirish shu vaqtgacha saqlanadi. Avtomatik uzaytirish to‘xtaydi. Yangi pulli tarif alohida to‘lov talab qiladi.',
        'confirm': 'O‘zgarishni tasdiqlash', 'keep': 'Joriy sozlamalarni saqlash',
        'invalid_invoice': 'To‘lovni tekshirib bo‘lmadi. Yangi to‘lovni oching yoki /paysupport orqali murojaat qiling.',
    },
    'ru': {
        'offers': 'Тарифы и кредиты\nВыберите предложение, чтобы проверить цену и включённые лимиты.',
        'sandbox': 'Тестовая оплата: настоящие Telegram Stars не списываются.',
        'live': 'Безопасная оплата через Telegram Stars. Доступ изменится только после подтверждения оплаты.',
        'pay': 'Оплатить в Telegram', 'simulate': 'Симулировать оплату локально',
        'confirmed': 'Платёж подтверждён. Тариф и лимиты готовы к использованию.',
        'unavailable': 'Оплата пока недоступна. Текущий тариф остаётся доступным.',
        'cancel': 'Отключить продление', 'resume': 'Включить продление',
        'renewal_on': 'Автопродление: включено', 'renewal_off': 'Автопродление: выключено',
        'active_until': 'Оплаченный доступ до', 'scheduled': 'Следующий тариф',
        'updated': 'Подписка обновлена. Текущий оплаченный доступ не изменился.',
        'support': 'Нужна помощь с оплатой? Нажмите «Помощь по оплате» ниже.',
        'payment_support': 'Помощь по оплате', 'home': 'Главное меню', 'back': 'Назад',
        'plans': 'Тарифы и кредиты', 'subscription': 'Моя подписка', 'balance': 'Включённые лимиты',
        'file_tasks': 'Задачи с файлами', 'file_page_units': 'Единицы страниц', 'ai_credits': 'AI-кредиты',
        'task_pack': 'Дополнительные задачи', 'ai_pack': 'Дополнительные AI-кредиты', 'free': 'Бесплатный',
        'price': 'Цена', 'period': 'Каждые 30 дней', 'once': 'Разовая покупка',
        'review': 'Проверьте покупку', 'expires': 'Эта ссылка на оплату действует 10 минут.',
        'no_subscription': 'У вас бесплатный тариф. Платной подписки для управления нет.',
        'expired': 'Эта подписка завершена. Выберите тариф, чтобы начать снова.',
        'confirm_off': 'Отключить автопродление?\nОплаченный доступ сохранится до {date}. За следующий период плата не спишется.',
        'confirm_on': 'Включить автопродление?\nTelegram будет продлевать текущий тариф в конце каждого оплаченного периода. Запланированная смена тарифа будет отменена.',
        'confirm_change': 'Перейти на тариф {plan} после {date}?\nТекущий оплаченный доступ сохранится до этой даты. Автопродление остановится. Новый платный тариф потребует отдельной оплаты.',
        'confirm': 'Подтвердить изменение', 'keep': 'Оставить текущие настройки',
        'invalid_invoice': 'Не удалось проверить платёж. Откройте новую оплату или обратитесь в /paysupport.',
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
