"""Localized Telegram command menus installed when the configured bot starts."""
from aiogram.types import BotCommand

COMMANDS={
'en':{'start':'Start PDF Master','tools':'Choose a file tool','settings':'Configure the current task','done':'Review the quote','run':'Run the confirmed task','myfiles':'Recent results','cancel':'Cancel current input','usage':'Allowances and usage','buy':'Plans and allowance packs','subscription':'Subscription and renewal','create':'Create a document or slides','study':'Study workspace','school':'School practice','teach':'Teacher workspace','editor':'PDF editor','language':'Choose language','support':'Contact support','paysupport':'Payment support','help':'Usage instructions'},
'uz':{'start':'PDF Master’ni boshlash','tools':'Fayl vositasini tanlash','settings':'Joriy vazifani sozlash','done':'Hisob-kitobni ko‘rish','run':'Tasdiqlangan vazifani bajarish','myfiles':'So‘nggi natijalar','cancel':'Joriy kiritishni bekor qilish','usage':'Limitlar va sarf','buy':'Tariflar va limit paketlari','subscription':'Obuna va uzaytirish','create':'Hujjat yoki slayd yaratish','study':'O‘rganish maydoni','school':'Maktab mashqlari','teach':'O‘qituvchi maydoni','editor':'PDF muharriri','language':'Tilni tanlash','support':'Yordamga murojaat','paysupport':'To‘lov bo‘yicha yordam','help':'Foydalanish yo‘riqnomasi'},
'ru':{'start':'Запустить PDF Master','tools':'Выбрать инструмент','settings':'Настроить текущую задачу','done':'Проверить расчёт','run':'Выполнить подтверждённую задачу','myfiles':'Последние результаты','cancel':'Отменить текущий ввод','usage':'Лимиты и использование','buy':'Тарифы и пакеты','subscription':'Подписка и продление','create':'Создать документ или слайды','study':'Учебное пространство','school':'Школьная практика','teach':'Пространство учителя','editor':'Редактор PDF','language':'Выбрать язык','support':'Обратиться в поддержку','paysupport':'Помощь по оплате','help':'Инструкция'},
}

async def install_commands(bot):
    for locale,commands in COMMANDS.items():
        await bot.set_my_commands([BotCommand(command=command,description=description) for command,description in commands.items()],language_code=locale)
