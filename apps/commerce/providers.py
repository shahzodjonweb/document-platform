"""The bot's credentials, read the one way every process reads them.

Telegram Stars was removed; the only payment is a card transfer reviewed by
hand (apps/commerce/manual.py), so no provider is called from here any more.
This shim stays because the bot, delivery and the management commands import
the bot configuration through it.
"""
from django.conf import settings


def telegram_config():
    try:
        from operations.integrations import telegram_config as configured
        return configured()
    except ImportError:
        return {'token':settings.TELEGRAM_BOT_TOKEN,'username':settings.TELEGRAM_BOT_USERNAME,'webhook_secret':settings.TELEGRAM_WEBHOOK_SECRET,'webapp_url':settings.TELEGRAM_WEBAPP_URL}
