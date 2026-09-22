import asyncio
from aiogram import Bot
from aiogram.types import Update
from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.core.models import WebhookReceipt
from telegram.bot import build_dispatcher
class Command(BaseCommand):
    help='Dispatch authenticated durable webhook receipts; retries share domain idempotency.'
    def handle(self,*args,**options): asyncio.run(self.dispatch())
    async def dispatch(self):
        if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_WEBHOOK_SECRET: raise RuntimeError('Webhook token and secret required.')
        bot=Bot(settings.TELEGRAM_BOT_TOKEN);dispatcher=build_dispatcher()
        try:
            receipts=await sync_to_async(lambda:list(WebhookReceipt.objects.filter(processed_at__isnull=True).order_by('update_id')[:100]))()
            for receipt in receipts:
                await dispatcher.feed_update(bot,Update.model_validate(receipt.payload))
                receipt.processed_at=timezone.now();receipt.payload={}
                await sync_to_async(receipt.save)(update_fields=['processed_at','payload'])
        finally: await bot.session.close()
