import asyncio
from django.core.management.base import BaseCommand
from telegram.bot import run_polling
class Command(BaseCommand):
    help='Run Telegram polling; requires a bot token and no webhook secret.'
    def handle(self,*args,**options): asyncio.run(run_polling())
