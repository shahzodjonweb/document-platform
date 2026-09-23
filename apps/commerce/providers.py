"""Provider calls are isolated here; sandbox never contacts Telegram."""
from asgiref.sync import async_to_sync
from django.conf import settings
from aiogram import Bot
from aiogram.types import LabeledPrice
from apps.core.errors import DomainError


def telegram_config():
    try:
        from operations.integrations import telegram_config as configured
        return configured()
    except ImportError:
        return {'token':settings.TELEGRAM_BOT_TOKEN,'username':settings.TELEGRAM_BOT_USERNAME,'webhook_secret':settings.TELEGRAM_WEBHOOK_SECRET,'webapp_url':settings.TELEGRAM_WEBAPP_URL}


class TelegramStarsProvider:
    sandbox=False
    def call(self,method,**kwargs):
        token=telegram_config().get('token')
        if not token: raise DomainError('telegram_not_configured',503)
        async def invoke():
            bot=Bot(token)
            try: return await getattr(bot,method)(**kwargs)
            finally: await bot.session.close()
        try: return async_to_sync(invoke)()
        except DomainError: raise
        except Exception: raise DomainError('payment_provider_unavailable',503,retryable=True) from None
    def invoice_link(self,invoice,payload):
        if invoice.account.telegram_user_id is None: raise DomainError('telegram_link_required',409)
        return self.call('create_invoice_link',title=invoice.snapshot['name'][:32],description='PDF Master '+invoice.snapshot['name'],payload=payload,currency='XTR',provider_token='',prices=[LabeledPrice(label=invoice.snapshot['name'],amount=invoice.amount_xtr)],subscription_period=invoice.snapshot.get('period_seconds'))
    def set_renewal(self,subscription,enabled):
        if subscription.account.telegram_user_id is None: raise DomainError('telegram_link_required',409)
        return self.call('edit_user_star_subscription',user_id=subscription.account.telegram_user_id,telegram_payment_charge_id=subscription.first_charge_id,is_canceled=not enabled)
    def refund(self,payment):
        if payment.account.telegram_user_id is None: raise DomainError('telegram_link_required',409)
        return self.call('refund_star_payment',user_id=payment.account.telegram_user_id,telegram_payment_charge_id=payment.provider_charge_id)
    def transactions(self,offset=0,limit=100):
        result=self.call('get_star_transactions',offset=offset,limit=limit)
        return [value.model_dump(mode='python') for value in result.transactions]


class SandboxStarsProvider:
    sandbox=True
    def invoice_link(self,invoice,payload): return ''
    def set_renewal(self,subscription,enabled): return True
    def refund(self,payment): return True
    def transactions(self,offset=0,limit=100): return []


def provider_for(sandbox): return SandboxStarsProvider() if sandbox else TelegramStarsProvider()
