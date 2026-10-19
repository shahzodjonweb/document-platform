"""Short, localized native menus. Advanced commands remain supported aliases."""
import logging

from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeChat, MenuButtonCommands
from asgiref.sync import sync_to_async
from django.db import transaction

from apps.core.models import BotConversation

# Raise this whenever COMMANDS changes. runbot installs the default and
# per-language menus on every start, but a chat's own menu (install_chat_commands,
# set when someone picks a language) outranks them, so people who picked a
# language before a change would keep the old labels for good. Each chat
# remembers the version it was given, and the language gate gives it the new
# one once, on that person's next message or tap (refresh_chat_commands).
COMMANDS_VERSION = 3
# Where that version is kept, without a schema change: BotConversation.review,
# beside the generation review on screen. The other JSON fields there, pending
# and prompt, are replaced whole at every sign-in step and input prompt;
# remember_review and forget_review (telegram/bot.py) carry this key over.
MENU_KEY = 'menu'
_refreshing = set()


COMMANDS = {
    'en': {
        'start': '🏠 Main menu',
        'document': '✨ PDF on a topic · AI', 'slides': '✨ Slides on a topic · AI', 'cv': '✨ CV · AI',
        'examples': '💡 How to describe it',
        'tools': '🛠 PDF & file tools',
        'myfiles': '🗂 Recent tasks',
        'usage': '📊 Plan & weekly limits', 'buy': '⭐ Plans',
        'subscription': '💳 Subscription', 'account': '👤 Account & logins',
        'web': '🌐 Open web app', 'settings': '⚙️ Settings', 'language': '🌐 Language',
        'help': '💡 How it works', 'support': '📞 Contacts & support', 'cancel': '✖️ Cancel step',
    },
    'uz': {
        'start': '🏠 Bosh menyu',
        'document': '✨ Mavzuga oid PDF · AI', 'slides': '✨ Mavzuga oid Slayd · AI', 'cv': '✨ CV (rezyume) · AI',
        'examples': '💡 Qanday yozish kerak',
        'tools': '🛠 PDF va fayl vositalari',
        'myfiles': '🗂 So‘nggi vazifalar',
        'usage': '📊 Tarif va haftalik limitlar', 'buy': '⭐ Tariflar',
        'subscription': '💳 Obuna', 'account': '👤 Hisob va kirish usullari',
        'web': '🌐 Veb ilova', 'settings': '⚙️ Sozlamalar', 'language': '🌐 Til',
        'help': '💡 Qanday ishlaydi', 'support': '📞 Aloqa va yordam', 'cancel': '✖️ Qadamni bekor qilish',
    },
    'ru': {
        'start': '🏠 Главное меню',
        'document': '✨ PDF по теме · ИИ', 'slides': '✨ Слайды по теме · ИИ', 'cv': '✨ Резюме · ИИ',
        'examples': '💡 Как описать',
        'tools': '🛠 Инструменты для файлов',
        'myfiles': '🗂 Последние задачи',
        'usage': '📊 Тариф и лимиты на неделю', 'buy': '⭐ Тарифы',
        'subscription': '💳 Подписка', 'account': '👤 Аккаунт и способы входа',
        'web': '🌐 Открыть сайт', 'settings': '⚙️ Настройки', 'language': '🌐 Язык',
        'help': '💡 Как это работает', 'support': '📞 Контакты и поддержка', 'cancel': '✖️ Отменить шаг',
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
    try:
        await sync_to_async(_remember_version)(chat_id)
    except Exception:
        # Not recorded means set again on the next update: harmless, unlike a
        # failed language choice.
        logging.getLogger(__name__).warning('Could not record the chat command menu version.', exc_info=True)
    return True


def menu_mark(review):
    """Only the menu version out of a stored review, to carry into its replacement."""
    review = review if isinstance(review, dict) else {}
    return {MENU_KEY: review[MENU_KEY]} if MENU_KEY in review else {}


@transaction.atomic
def _remember_version(chat_id):
    row = BotConversation.objects.select_for_update().filter(pk=chat_id).first()
    if row is None or menu_mark(row.review).get(MENU_KEY) == COMMANDS_VERSION:
        return
    review = row.review if isinstance(row.review, dict) else {}
    # A queryset update leaves updated_at alone: a menu is not something the
    # customer did, so it must not make an old input prompt look recent.
    BotConversation.objects.filter(pk=chat_id).update(review={**review, MENU_KEY: COMMANDS_VERSION})


async def refresh_chat_commands(bot, chat_id, locale, version):
    """Give a chat the current menu if it was last given an older one.

    `version` is what the chat has stored (None for anyone who picked a language
    before versions were kept). Anything other than the current version is
    replaced, so a rollback puts the older menu back too. An album arrives as
    several updates at once; only the first of them sets the menu.
    """
    if version == COMMANDS_VERSION or chat_id in _refreshing:
        return False
    _refreshing.add(chat_id)
    try:
        return await install_chat_commands(bot, chat_id, locale)
    except Exception:
        # This runs before the customer's own message is handled, and a menu is
        # only a convenience: nothing here may stop that message. The next
        # update tries again.
        logging.getLogger(__name__).warning('Could not refresh a chat command menu.', exc_info=True)
        return False
    finally:
        _refreshing.discard(chat_id)
