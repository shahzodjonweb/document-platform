import asyncio
import time
from django.core.management.base import BaseCommand
from telegram.bot import run_polling
class Command(BaseCommand):
    help='Run Telegram polling; requires a bot token and no webhook secret.'

    def add_arguments(self,parser):
        parser.add_argument('--wait-for-config',action='store_true',
                            help='Wait for credentials saved through Admin Integrations.')

    def handle(self,*args,**options):
        if options.get('wait_for_config'):
            from apps.commerce.providers import telegram_config
            announced=False
            while True:
                config=telegram_config()
                if config.get('token') and not config.get('webhook_secret'):break
                if not announced:
                    self.stdout.write('Waiting for polling credentials in Admin Integrations.')
                    announced=True
                time.sleep(10)
        asyncio.run(run_polling())
