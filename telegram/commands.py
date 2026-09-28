"""Short, localized native menus. Advanced commands remain supported aliases."""
import logging

from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeChat, MenuButtonCommands


COMMANDS = {
    'en': {
        'start': '🏠 Main menu',
        'document': '✨ PDF Document · AI', 'slides': '✨ PowerPoint Slides · AI',
        'examples': '💡 How to describe it',
        'tools': '🛠 PDF & file tools',
        'myfiles': '🗂 Recent tasks',
        'usage': '📊 Plan & balance', 'buy': '⭐ Plans & packs',
        'subscription': '💳 Subscription', 'account': '👤 Account & logins',
        'web': '🌐 Open web app', 'settings': '⚙️ Settings', 'language': '🌐 Language',
        'help': '💡 How it works', 'support': '💬 Contact support', 'cancel': '✖️ Cancel step',
    },
    'uz': {
        'start': '🏠 Bosh menyu',
        'document': '✨ PDF hujjat · AI', 'slides': '✨ PowerPoint slaydlar · AI',
        'examples': '💡 Qanday yozish kerak',
        'tools': '🛠 PDF va fayl vositalari',
        'myfiles': '🗂 So‘nggi vazifalar',
        'usage': '📊 Tarif va balans', 'buy': '⭐ Tariflar va paketlar',
        'subscription': '💳 Obuna', 'account': '👤 Hisob va kirish usullari',
        'web': '🌐 Veb ilova', 'settings': '⚙️ Sozlamalar', 'language': '🌐 Til',
        'help': '💡 Qanday ishlaydi', 'support': '💬 Yordamga yozish', 'cancel': '✖️ Qadamni bekor qilish',
    },
    'ru': {
        'start': '🏠 Главное меню',
        'document': '✨ PDF документ · ИИ', 'slides': '✨ PowerPoint слайды · ИИ',
        'examples': '💡 Как описать',
        'tools': '🛠 Инструменты для файлов',
        'myfiles': '🗂 Последние задачи',
        'usage': '📊 Тариф и баланс', 'buy': '⭐ Тарифы и пакеты',
        'subscription': '💳 Подписка', 'account': '👤 Аккаунт и способы входа',
        'web': '🌐 Открыть сайт', 'settings': '⚙️ Настройки', 'language': '🌐 Язык',
        'help': '💡 Как это работает', 'support': '💬 Поддержка', 'cancel': '✖️ Отменить шаг',
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
