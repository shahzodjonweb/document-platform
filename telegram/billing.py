"""Telegram Stars adapters. All financial decisions remain in commerce services."""
import html
from asgiref.sync import sync_to_async
from aiogram import F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton,InlineKeyboardMarkup
from django.conf import settings
from django.utils import timezone
from apps.core.errors import DomainError,error_data
from apps.core.identity import resolve_account
from apps.core.models import BotCallback
from apps.commerce import services
from apps.commerce.models import Invoice
from apps.commerce.serializers import subscription_data

COPY={
'en':{'offers':'Choose an offer. Local sandbox offers do not spend real Stars.','pay':'Pay in Telegram','simulate':'Simulate local payment','confirmed':'Payment confirmed. Your account and allowances have been updated.','unavailable':'Checkout is not configured.','cancel':'Turn renewal off','resume':'Turn renewal on','renewal_on':'Renewal on','renewal_off':'Renewal off','active_until':'Active until','scheduled':'Scheduled plan','updated':'Subscription updated. Current paid access is preserved.','support':'Use /paysupport followed by your payment question.'},
'uz':{'offers':'Taklifni tanlang. Mahalliy sinov takliflari haqiqiy Stars sarflamaydi.','pay':'Telegram’da to‘lash','simulate':'Mahalliy to‘lovni sinash','confirmed':'To‘lov tasdiqlandi. Hisob va limitlaringiz yangilandi.','unavailable':'To‘lov sozlanmagan.','cancel':'Uzaytirishni o‘chirish','resume':'Uzaytirishni yoqish','renewal_on':'Uzaytirish yoqilgan','renewal_off':'Uzaytirish o‘chirilgan','active_until':'Amal qilish muddati','scheduled':'Rejalashtirilgan tarif','updated':'Obuna yangilandi. Joriy pulli kirish saqlanadi.','support':'To‘lov savolini /paysupport buyrug‘idan keyin yozing.'},
'ru':{'offers':'Выберите предложение. Локальные тестовые предложения не тратят реальные Stars.','pay':'Оплатить в Telegram','simulate':'Симулировать оплату локально','confirmed':'Платёж подтверждён. Аккаунт и лимиты обновлены.','unavailable':'Оплата не настроена.','cancel':'Отключить продление','resume':'Включить продление','renewal_on':'Продление включено','renewal_off':'Продление отключено','active_until':'Доступ до','scheduled':'Запланированный план','updated':'Подписка обновлена. Текущий оплаченный доступ сохранён.','support':'Напишите вопрос об оплате после /paysupport.'}}

def copy(account,key): return COPY.get(account.locale,COPY['en'])[key]

def register_billing_handlers(dp):
    from .bot import account_for,callback,safe_error

    async def show_invoice(message,account,offer_id,key):
        invoice,_=await sync_to_async(services.create_invoice)(account,offer_id,key)
        invoice=await sync_to_async(services.present_invoice)(invoice)
        if invoice.sandbox:
            button=InlineKeyboardButton(text=copy(account,'simulate'),callback_data=await callback(account,'commerce_pay',{'invoice_id':str(invoice.id)}))
        else: button=InlineKeyboardButton(text=copy(account,'pay'),url=invoice.invoice_url)
        await message.answer(f'{html.escape(invoice.snapshot["name"])}\n{invoice.amount_xtr} XTR',parse_mode='HTML',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[button]]))

    async def show_subscription(message,account):
        data=await sync_to_async(subscription_data)(account)
        sub=data['subscription']
        if not sub: return await message.answer(data['plan'].title())
        action='commerce_cancel' if sub['renewal_enabled'] else 'commerce_resume'
        button=InlineKeyboardButton(text=copy(account,'cancel' if sub['renewal_enabled'] else 'resume'),callback_data=await callback(account,action,{'subscription_id':sub['id']}))
        await message.answer(f'{sub["plan"].title()}\n{copy(account,"renewal_on" if sub["renewal_enabled"] else "renewal_off")}\n{copy(account,"active_until")}: {sub["current_period_end"]:%Y-%m-%d %H:%M} UTC',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[button]]))

    @dp.pre_checkout_query()
    async def precheckout(query):
        try:
            await sync_to_async(services.validate_precheckout)(query.from_user.id,query.invoice_payload,query.currency,query.total_amount,False)
            await query.answer(ok=True)
        except DomainError:
            await query.answer(ok=False,error_message='The invoice could not be verified. Open a new invoice or contact /paysupport.')

    @dp.message(F.successful_payment)
    async def successful(message):
        data=message.successful_payment
        account=await account_for(message.from_user)
        try:
            await sync_to_async(services.record_payment)(message.from_user.id,data.invoice_payload,data.currency,data.total_amount,data.telegram_payment_charge_id,provider_charge_id=data.provider_payment_charge_id,expiration_date=data.subscription_expiration_date,is_recurring=bool(data.is_recurring),is_first_recurring=bool(data.is_first_recurring),occurred_at=message.date,sandbox=False)
            await message.answer(copy(account,'confirmed'))
        except DomainError as exc:
            await safe_error(message,account,exc)
            await message.answer(copy(account,'support'))

    @dp.message(Command('buy'))
    async def buy(message):
        account=await account_for(message.from_user)
        try:
            values=message.text.split(maxsplit=1)
            if len(values)>1: return await show_invoice(message,account,values[1].strip(),f'telegram:{message.chat.id}:{message.message_id}')
            offers=await sync_to_async(services.available_offers)(account)
            if not offers: return await message.answer(copy(account,'unavailable'))
            rows=[[InlineKeyboardButton(text=f'{o.plan.title() if o.plan else o.offer_id} · {o.price_xtr} XTR',callback_data=await callback(account,'commerce_offer',{'offer_id':o.offer_id}))] for o in offers]
            await message.answer(copy(account,'offers'),reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        except DomainError as exc: await safe_error(message,account,exc)

    @dp.message(Command('subscription','cancelrenewal','resumerenewal','changeplan'))
    async def subscription(message):
        account=await account_for(message.from_user)
        try:
            command=message.text.split()[0].split('@')[0]
            if command=='/cancelrenewal': await sync_to_async(services.set_renewal)(account,False)
            elif command=='/resumerenewal': await sync_to_async(services.set_renewal)(account,True)
            elif command=='/changeplan': await sync_to_async(services.schedule_plan_change)(account,message.text.split(maxsplit=1)[1].strip())
            await show_subscription(message,account)
        except (ValueError,IndexError): await safe_error(message,account,DomainError('invalid_plan'))
        except DomainError as exc: await safe_error(message,account,exc)

    @dp.callback_query(F.data)
    async def commerce_callback(query):
        # Returning UNHANDLED allows the existing tool callback router to proceed.
        from aiogram.dispatcher.event.bases import SkipHandler
        account=await account_for(query.from_user)
        ref=await sync_to_async(lambda:BotCallback.objects.filter(token=query.data,account=account,action__startswith='commerce_',expires_at__gt=timezone.now()).first())()
        if not ref: raise SkipHandler()
        try:
            if ref.action=='commerce_offer': await show_invoice(query.message,account,ref.payload['offer_id'],f'telegram:{ref.token}')
            elif ref.action=='commerce_pay':
                await sync_to_async(services.sandbox_pay)(account,ref.payload['invoice_id'])
                await query.message.answer(copy(account,'confirmed'))
            elif ref.action in ('commerce_cancel','commerce_resume'):
                from apps.commerce.models import Subscription
                valid=await sync_to_async(lambda:Subscription.objects.filter(pk=ref.payload['subscription_id'],account=account).exists())()
                if not valid: raise DomainError('not_found',404)
                await sync_to_async(services.set_renewal)(account,ref.action=='commerce_resume')
                await show_subscription(query.message,account)
            await query.answer()
        except DomainError as exc:
            await safe_error(query.message,account,exc);await query.answer()


def fast_precheckout(update):
    """Call from verified webhook receiver before durable normal-update dispatch."""
    query=update.get('pre_checkout_query')
    if not query: return False
    from apps.commerce.providers import TelegramStarsProvider
    ok=True
    try: services.validate_precheckout(query['from']['id'],query['invoice_payload'],query['currency'],query['total_amount'],False)
    except (DomainError,KeyError,TypeError): ok=False
    kwargs={'pre_checkout_query_id':query['id'],'ok':ok}
    if not ok: kwargs['error_message']='Invoice validation failed. Open a new invoice or contact /paysupport.'
    TelegramStarsProvider().call('answer_pre_checkout_query',**kwargs)
    return True
