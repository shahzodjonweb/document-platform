"""The bot's side of the channel rule: which channels to join, and "I've joined".

A free customer who has not joined the owner's channels is shown them, with a
button to each and one to say they have joined; paid plans are offered as the
other way in. The rule itself lives in apps.core.channel_gate.
"""
from asgiref.sync import sync_to_async
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

COPY = {
    'en': {
        'gate_one': "📢 PDF Master is free for members of our Telegram community.\nJoin our channel, then tap «I've joined».",
        'gate_many': "📢 PDF Master is free for members of our Telegram community.\nJoin our channels, then tap «I've joined».",
        'joined': "✅ I've joined",
        'plans': '⭐ Or choose a paid plan',
        'welcome': '✅ Thanks for joining! Every service is open to you now.',
        'not_yet': "You haven't joined {titles} yet. Join, then tap «I've joined» again.",
    },
    'uz': {
        'gate_one': '📢 PDF Master Telegram hamjamiyatimiz a’zolari uchun bepul.\nKanalimizga qo‘shiling, so‘ng «Qo‘shildim» tugmasini bosing.',
        'gate_many': '📢 PDF Master Telegram hamjamiyatimiz a’zolari uchun bepul.\nKanallarimizga qo‘shiling, so‘ng «Qo‘shildim» tugmasini bosing.',
        'joined': '✅ Qo‘shildim',
        'plans': '⭐ Yoki pullik tarifni tanlang',
        'welcome': '✅ Qo‘shilganingiz uchun rahmat! Endi barcha xizmatlar siz uchun ochiq.',
        'not_yet': 'Siz hali {titles} ga qo‘shilmagansiz. Qo‘shiling va «Qo‘shildim»ni yana bosing.',
    },
    'ru': {
        'gate_one': '📢 PDF Master бесплатен для участников нашего Telegram-сообщества.\nПодпишитесь на канал и нажмите «Я подписался».',
        'gate_many': '📢 PDF Master бесплатен для участников нашего Telegram-сообщества.\nПодпишитесь на наши каналы и нажмите «Я подписался».',
        'joined': '✅ Я подписался',
        'plans': '⭐ Или выберите платный тариф',
        'welcome': '✅ Спасибо за подписку! Все сервисы теперь доступны.',
        'not_yet': 'Вы ещё не подписались на {titles}. Подпишитесь и снова нажмите «Я подписался».',
    },
}


def copy(account, key):
    return COPY.get(getattr(account, 'locale', 'en'), COPY['en'])[key]


async def blocked(account):
    """The channel state when this account may not use a service yet, else None."""
    from apps.core.channel_gate import status
    current = await sync_to_async(status)(account)
    return current if current['required'] and not current['joined'] else None


async def show_gate(message, account, current=None, notice=''):
    from apps.core.channel_gate import status
    from .bot import callback
    current = current or await sync_to_async(status)(account)
    rows = [[InlineKeyboardButton(text=('✅ ' if channel['joined'] else '📢 ') + channel['title'], url=channel['url'])]
            for channel in current['channels']]
    rows.append([InlineKeyboardButton(text=copy(account, 'joined'), callback_data=await callback(account, 'channels_check'))])
    rows.append([InlineKeyboardButton(text=copy(account, 'plans'), callback_data=await callback(account, 'plans'))])
    body = copy(account, 'gate_one' if len(current['channels']) == 1 else 'gate_many')
    await message.answer((notice + '\n\n' if notice else '') + body, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


async def check(message, account):
    """\"I've joined\": ask Telegram again. True when every channel is joined."""
    from apps.core.channel_gate import status
    current = await sync_to_async(status)(account, True)
    if current['joined']:
        await message.answer(copy(account, 'welcome'))
        return True
    missing = ', '.join(c['title'] for c in current['channels'] if not c['joined'])
    await show_gate(message, account, current, copy(account, 'not_yet').format(titles=missing))
    return False
