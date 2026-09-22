import asyncio
from django.core.management.base import BaseCommand
from telegram.delivery import standalone
class Command(BaseCommand):
    help='Retry due Telegram deliveries independently from job processing and charging.'
    def handle(self,*args,**options): asyncio.run(standalone())
