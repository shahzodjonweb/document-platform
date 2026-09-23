"""Short, localized native menus. Advanced commands remain supported aliases."""
import logging

from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeChat, MenuButtonCommands


COMMANDS = {
    'en': {
        'start': 'Main menu', 'tools': 'PDF and file tools', 'myfiles': 'Recent files and results',
        'usage': 'Plan and remaining balance', 'buy': 'Plans and extra credits',
        'subscription': 'Manage subscription', 'account': 'Account and linked logins',
        'web': 'Open web app', 'settings': 'Settings', 'language': 'Change language',
        'help': 'How it works', 'support': 'Contact support', 'cancel': 'Cancel current step',
    },
    'uz': {
        'start': 'Bosh menyu', 'tools': 'PDF va fayl vositalari', 'myfiles': 'So‘nggi fayllar va natijalar',
        'usage': 'Tarif va qolgan limitlar', 'buy': 'Tariflar va qo‘shimcha kreditlar',
        'subscription': 'Obunani boshqarish', 'account': 'Hisob va kirish usullari',
        'web': 'Veb ilovani ochish', 'settings': 'Sozlamalar', 'language': 'Tilni o‘zgartirish',
        'help': 'Qanday ishlaydi', 'support': 'Yordamga murojaat', 'cancel': 'Joriy qadamni bekor qilish',
    },
    'ru': {
        'start': 'Главное меню', 'tools': 'Инструменты PDF и файлов', 'myfiles': 'Последние файлы и результаты',
        'usage': 'Тариф и остаток лимитов', 'buy': 'Тарифы и дополнительные кредиты',
        'subscription': 'Управление подпиской', 'account': 'Аккаунт и способы входа',
        'web': 'Открыть веб-приложение', 'settings': 'Настройки', 'language': 'Изменить язык',
        'help': 'Как это работает', 'support': 'Связаться с поддержкой', 'cancel': 'Отменить текущий шаг',
    },
}


async def install_commands(bot):
    # A default menu covers clients with an unsupported or missing language code.
    for locale in ('', *COMMANDS):
        commands = COMMANDS.get(locale, COMMANDS['en'])
        await bot.set_my_commands(
            [BotCommand(command=command, description=description) for command, description in commands.items()],
            language_code=locale,
        )
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())


async def install_chat_commands(bot, chat_id, locale):
    """Follow the language selected in PDF Master even if Telegram differs.

    A chat-specific default beats the globally localized menus. This is an
    optional UI enhancement, so transient API errors must not block onboarding.
    """
    commands = COMMANDS.get(locale, COMMANDS['en'])
    try:
        await bot.set_my_commands(
            [BotCommand(command=command, description=description) for command, description in commands.items()],
            scope=BotCommandScopeChat(chat_id=chat_id),
            language_code='',
        )
    except TelegramAPIError:
        logging.getLogger(__name__).warning('Could not update the selected-language Telegram command menu.')
        return False
    return True
