from django.conf import settings
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from apps.core.errors import DomainError
from .auth import require_staff,audit,development_access
from .views import context,finish_render
from datetime import datetime
from .integrations import telegram_config,ai_config,google_config,email_config,antibot_config,pixabay_config,manual_payment_config,channel_gate_config,test_channels,CARD_LABELS,save_config,test_telegram,test_email,test_pixabay,control_runner,runner_status,object_storage_config,test_object_storage
from .models import IntegrationConfig

LABELS={
'en':{'integrations':'Integrations','intro':'Connect your Telegram bot and choose the document generation provider. Secrets are encrypted and never shown after saving.','telegram':'Telegram bot','token':'Bot token','username':'Bot username','webapp':'Web application URL','secret_hint':'Leave blank to keep the saved secret.','reason':'Reason for this change','save':'Save configuration','test':'Test connection','start':'Start local bot','stop':'Stop local bot','ai':'Document generation','mode':'Provider mode','local':'Local authoring · no AI calls','live':'OpenAI · real API calls','disabled':'Disabled','key':'API key','model':'Model ID','configured':'Configured','missing':'Not configured','running':'Running','stopped':'Stopped','local_note':'Local polling needs a real Telegram token. Telegram Mini Apps require an HTTPS URL; ordinary browser tools work on localhost.','saved':'Configuration saved.','connected':'Connected to Telegram.','action_done':'Bot control updated.','failure':'Could not complete this action. Check configuration and try again.','need_reason':'Enter a reason of at least 5 characters.','token_status':'Token status','provider_status':'Provider status','simulator':'Open local bot simulator'},
'uz':{'integrations':'Integratsiyalar','intro':'Telegram botingizni ulang va hujjat yaratish provayderini tanlang. Maxfiy kalitlar shifrlanadi va saqlangandan keyin ko‘rsatilmaydi.','telegram':'Telegram bot','token':'Bot tokeni','username':'Bot foydalanuvchi nomi','webapp':'Veb ilova manzili','secret_hint':'Saqlangan kalitni qoldirish uchun bo‘sh qoldiring.','reason':'O‘zgarish sababi','save':'Sozlamalarni saqlash','test':'Ulanishni tekshirish','start':'Mahalliy botni ishga tushirish','stop':'Mahalliy botni to‘xtatish','ai':'Hujjat yaratish','mode':'Provayder rejimi','local':'Mahalliy tahrirlash · AI chaqirilmaydi','live':'OpenAI · haqiqiy API','disabled':'O‘chirilgan','key':'API kaliti','model':'Model identifikatori','configured':'Sozlangan','missing':'Sozlanmagan','running':'Ishlamoqda','stopped':'To‘xtatilgan','local_note':'Mahalliy bot uchun haqiqiy Telegram tokeni kerak. Telegram Mini App uchun HTTPS manzil zarur; brauzer vositalari localhost’da ishlaydi.','saved':'Sozlamalar saqlandi.','connected':'Telegram ulandi.','action_done':'Bot boshqaruvi yangilandi.','failure':'Amal bajarilmadi. Sozlamalarni tekshirib, qayta urinib ko‘ring.','need_reason':'Kamida 5 belgidan iborat sabab kiriting.','token_status':'Token holati','provider_status':'Provayder holati','simulator':'Mahalliy bot simulyatorini ochish'},
'ru':{'integrations':'Интеграции','intro':'Подключите Telegram-бота и выберите провайдера генерации документов. Секреты шифруются и не показываются после сохранения.','telegram':'Telegram-бот','token':'Токен бота','username':'Имя бота','webapp':'Адрес веб-приложения','secret_hint':'Оставьте пустым, чтобы сохранить текущий ключ.','reason':'Причина изменения','save':'Сохранить настройки','test':'Проверить соединение','start':'Запустить локального бота','stop':'Остановить локального бота','ai':'Генерация документов','mode':'Режим провайдера','local':'Локальное редактирование · без ИИ','live':'OpenAI · реальные вызовы API','disabled':'Отключено','key':'Ключ API','model':'ID модели','configured':'Настроено','missing':'Не настроено','running':'Работает','stopped':'Остановлен','local_note':'Для локального бота нужен настоящий токен Telegram. Mini App требует HTTPS; инструменты браузера работают на localhost.','saved':'Настройки сохранены.','connected':'Соединение с Telegram установлено.','action_done':'Управление ботом обновлено.','failure':'Не удалось выполнить действие. Проверьте настройки и повторите.','need_reason':'Укажите причину длиной не менее 5 символов.','token_status':'Состояние токена','provider_status':'Состояние провайдера','simulator':'Открыть локальный симулятор бота'}}

for language,label in {'en':'Image model ID (optional)','uz':'Rasm modeli identifikatori (ixtiyoriy)','ru':'ID модели изображений (необязательно)'}.items():LABELS[language]['image_model']=label

for language, values in {
    'en': ('Managed by server', 'Waiting for credentials', 'Save your Telegram token and username here. The server starts the bot automatically; use Test connection to verify the credentials.'),
    'uz': ('Server boshqaradi', 'Kirish ma’lumotlari kutilmoqda', 'Telegram tokeni va foydalanuvchi nomini shu yerda saqlang. Server botni avtomatik ishga tushiradi; ma’lumotlarni Ulanishni tekshirish orqali tekshiring.'),
    'ru': ('Управляется сервером', 'Ожидание учётных данных', 'Сохраните токен Telegram и имя бота здесь. Сервер запустит бота автоматически; проверьте данные кнопкой «Проверить соединение».'),
}.items():
    LABELS[language].update(zip(('managed', 'waiting', 'production_note'), values))

AUTH_LABELS = {
    'en': {
        'intro': 'Connect Telegram, Google sign-in, email delivery, and your document generation provider. Secrets are encrypted and never shown after saving.',
        'google': 'Google sign-in', 'google_enabled': 'Enable Google sign-in', 'client_id': 'OAuth client ID',
        'client_secret': 'OAuth client secret', 'redirect_uri': 'Authorized redirect URI',
        'google_hint': 'Create a Web application OAuth client in Google Cloud and copy this exact redirect URI into its authorized redirect URIs. The callback must use the same origin as the web application URL above.',
        'email': 'Email and password sign-in', 'email_enabled': 'Enable email registration and recovery',
        'smtp_host': 'SMTP host', 'smtp_port': 'SMTP port', 'smtp_username': 'SMTP username',
        'smtp_password': 'SMTP password', 'from_email': 'Sender email address',
        'tls': 'STARTTLS (usually port 587)', 'ssl': 'Implicit TLS (usually port 465)',
        'email_hint': 'Verification and password reset codes use this mailbox. Choose one TLS mode, save, then test the connection. The test authenticates with your saved settings without sending an email.',
        'email_connected': 'SMTP connection and authentication succeeded. No email was sent.',
        'active': 'Enabled', 'inactive': 'Disabled', 'setup_required': 'Setup required',
    },
    'uz': {
        'intro': 'Telegram, Google orqali kirish, elektron pochta va hujjat yaratish provayderini sozlang. Maxfiy kalitlar shifrlanadi va saqlangandan keyin ko‘rsatilmaydi.',
        'google': 'Google orqali kirish', 'google_enabled': 'Google orqali kirishni yoqish', 'client_id': 'OAuth mijoz identifikatori',
        'client_secret': 'OAuth maxfiy kaliti', 'redirect_uri': 'Ruxsat etilgan qaytish manzili',
        'google_hint': 'Google Cloud’da Web application turidagi OAuth mijozini yarating va ushbu manzilni ruxsat etilgan qaytish manzillari ro‘yxatiga aynan kiriting. Qaytish manzili yuqoridagi veb ilova bilan bir xil domen va protokoldan foydalanishi kerak.',
        'email': 'Elektron pochta va parol bilan kirish', 'email_enabled': 'Pochta orqali ro‘yxatdan o‘tish va tiklashni yoqish',
        'smtp_host': 'SMTP serveri', 'smtp_port': 'SMTP porti', 'smtp_username': 'SMTP foydalanuvchi nomi',
        'smtp_password': 'SMTP paroli', 'from_email': 'Yuboruvchi pochta manzili',
        'tls': 'STARTTLS (odatda 587-port)', 'ssl': 'Bevosita TLS (odatda 465-port)',
        'email_hint': 'Tasdiqlash va parolni tiklash kodlari ushbu pochta orqali yuboriladi. Bitta TLS rejimini tanlang, saqlang va ulanishni tekshiring. Tekshirish saqlangan ma’lumotlar bilan xat yubormasdan amalga oshiriladi.',
        'email_connected': 'SMTP ulanishi va autentifikatsiya muvaffaqiyatli. Xat yuborilmadi.',
        'active': 'Yoqilgan', 'inactive': 'O‘chirilgan', 'setup_required': 'Sozlash kerak',
    },
    'ru': {
        'intro': 'Настройте Telegram, вход через Google, отправку почты и генерацию документов. Секреты шифруются и не показываются после сохранения.',
        'google': 'Вход через Google', 'google_enabled': 'Включить вход через Google', 'client_id': 'ID клиента OAuth',
        'client_secret': 'Секрет клиента OAuth', 'redirect_uri': 'Разрешённый URI перенаправления',
        'google_hint': 'Создайте OAuth-клиент типа Web application в Google Cloud и добавьте этот точный URI в разрешённые адреса перенаправления. Обратный адрес должен использовать тот же домен, протокол и порт, что и адрес веб-приложения выше.',
        'email': 'Вход по почте и паролю', 'email_enabled': 'Включить регистрацию и восстановление по почте',
        'smtp_host': 'Сервер SMTP', 'smtp_port': 'Порт SMTP', 'smtp_username': 'Имя пользователя SMTP',
        'smtp_password': 'Пароль SMTP', 'from_email': 'Адрес отправителя',
        'tls': 'STARTTLS (обычно порт 587)', 'ssl': 'Неявный TLS (обычно порт 465)',
        'email_hint': 'Коды подтверждения и сброса пароля отправляются через этот почтовый ящик. Выберите один режим TLS, сохраните настройки и проверьте соединение. Проверка использует сохранённые настройки и не отправляет писем.',
        'email_connected': 'Соединение и аутентификация SMTP проверены. Письмо не отправлялось.',
        'active': 'Включено', 'inactive': 'Отключено', 'setup_required': 'Требуется настройка',
    },
}
for language, labels in AUTH_LABELS.items(): LABELS[language].update(labels)

ANTIBOT_LABELS = {
    'en': {
        'intro': 'Manage sign-in, bot protection, Telegram, email delivery, and document generation. Secrets are encrypted and never shown after saving.',
        'antibot': 'Anti-bot verification', 'antibot_web': 'Web verification',
        'antibot_web_enabled': 'Enable web verification', 'antibot_bot_enabled': 'Enable Telegram bot verification',
        'antibot_site_key': 'Turnstile site key', 'antibot_secret_key': 'Turnstile secret key',
        'antibot_hosts': 'Allowed hostnames', 'antibot_hosts_hint': 'One exact hostname per line, without https://, paths, or wildcards.',
        'antibot_web_hint': 'Create a Managed Turnstile widget for these hostnames in Cloudflare. Save its site key and secret key here, then enable web verification.',
        'antibot_setup': 'Open Cloudflare Turnstile',
        'antibot_bot_hint': 'A quick emoji choice helps limit simple automated abuse in Telegram. No external keys are needed.',
        'antibot_not_configured': 'Add both Turnstile keys and at least one hostname before enabling web verification.',
        'invalid_antibot_hostnames': 'Use exact hostnames, such as pdfmaster.orderdesk.live. URLs, ports, and wildcards are not accepted.',
        'invalid_antibot_site_key': 'Check the Turnstile site key and paste it again.',
        'invalid_antibot_secret_key': 'Check the Turnstile secret key and paste it again.',
        'antibot_test_keys_forbidden': 'Use real Turnstile credentials on the live website. Test keys only work in local development.',
    },
    'uz': {
        'intro': 'Kirish, botlardan himoya, Telegram, pochta va hujjat yaratishni sozlang. Maxfiy kalitlar shifrlanadi va saqlangandan keyin ko‘rsatilmaydi.',
        'antibot': 'Botlardan himoya', 'antibot_web': 'Veb tekshiruvi',
        'antibot_web_enabled': 'Veb tekshiruvini yoqish', 'antibot_bot_enabled': 'Telegram botida tekshiruvni yoqish',
        'antibot_site_key': 'Turnstile sayt kaliti', 'antibot_secret_key': 'Turnstile maxfiy kaliti',
        'antibot_hosts': 'Ruxsat etilgan domenlar', 'antibot_hosts_hint': 'Har qatorga bitta aniq domen kiriting. https://, yo‘l va yulduzcha belgisi kerak emas.',
        'antibot_web_hint': 'Cloudflare’da shu domenlar uchun Managed rejimidagi Turnstile vidjetini yarating. Sayt va maxfiy kalitlarni shu yerda saqlang, keyin veb tekshiruvini yoqing.',
        'antibot_setup': 'Cloudflare Turnstile’ni ochish',
        'antibot_bot_hint': 'Telegramda oddiy avtomatik so‘rovlarni kamaytirish uchun qisqa emoji tekshiruvi qo‘llanadi. Tashqi kalitlar kerak emas.',
        'antibot_not_configured': 'Veb tekshiruvini yoqishdan oldin ikkala Turnstile kaliti va kamida bitta domenni kiriting.',
        'invalid_antibot_hostnames': 'pdfmaster.orderdesk.live kabi aniq domen kiriting. URL, port va yulduzcha belgisi qabul qilinmaydi.',
        'invalid_antibot_site_key': 'Turnstile sayt kalitini tekshirib, qayta kiriting.',
        'invalid_antibot_secret_key': 'Turnstile maxfiy kalitini tekshirib, qayta kiriting.',
        'antibot_test_keys_forbidden': 'Ishlayotgan saytda haqiqiy Turnstile kalitlaridan foydalaning. Sinov kalitlari faqat mahalliy muhitda ishlaydi.',
    },
    'ru': {
        'intro': 'Настройте вход, защиту от ботов, Telegram, отправку почты и генерацию документов. Секреты шифруются и не показываются после сохранения.',
        'antibot': 'Защита от ботов', 'antibot_web': 'Проверка на сайте',
        'antibot_web_enabled': 'Включить проверку на сайте', 'antibot_bot_enabled': 'Включить проверку в Telegram-боте',
        'antibot_site_key': 'Ключ сайта Turnstile', 'antibot_secret_key': 'Секретный ключ Turnstile',
        'antibot_hosts': 'Разрешённые домены', 'antibot_hosts_hint': 'Один точный домен в строке, без https://, путей и звёздочек.',
        'antibot_web_hint': 'Создайте виджет Turnstile в режиме Managed для этих доменов в Cloudflare. Сохраните здесь ключ сайта и секретный ключ, затем включите проверку на сайте.',
        'antibot_setup': 'Открыть Cloudflare Turnstile',
        'antibot_bot_hint': 'Быстрый выбор эмодзи помогает сдерживать простые автоматические запросы в Telegram. Внешние ключи не нужны.',
        'antibot_not_configured': 'Перед включением проверки добавьте оба ключа Turnstile и хотя бы один домен.',
        'invalid_antibot_hostnames': 'Укажите точный домен, например pdfmaster.orderdesk.live. URL, порты и звёздочки не допускаются.',
        'invalid_antibot_site_key': 'Проверьте и вставьте ключ сайта Turnstile ещё раз.',
        'invalid_antibot_secret_key': 'Проверьте и вставьте секретный ключ Turnstile ещё раз.',
        'antibot_test_keys_forbidden': 'Для рабочего сайта нужны настоящие ключи Turnstile. Тестовые ключи доступны только при локальной разработке.',
    },
}
for language, labels in ANTIBOT_LABELS.items(): LABELS[language].update(labels)

PHOTO_LABELS = {
    'en': {'pixabay': 'Stock photos (Pixabay)', 'pixabay_enabled': 'Add photos to AI slide decks',
           'pixabay_key': 'Pixabay API key',
           'pixabay_hint': 'Free key from pixabay.com/api/docs. Photos are searched only while a paid deck is being generated, cached for 24 hours as Pixabay requires, and downloaded into the deck — never hotlinked. How many photos a deck may use is the "max_deck_images" limit on each plan. Untick to stop all photo requests at once.',
           'pixabay_connected': 'Pixabay answered a test search.',
           'invalid_pixabay_key': 'That does not look like a Pixabay key (digits, a dash, then letters and digits).',
           'pixabay_not_configured': 'Add a Pixabay key before turning photos on.',
           'pixabay_connection_failed': 'Pixabay did not answer the test search. Check the key.'},
    'uz': {'pixabay': 'Stok rasmlar (Pixabay)', 'pixabay_enabled': 'AI taqdimotlariga rasm qo‘shish',
           'pixabay_key': 'Pixabay API kaliti',
           'pixabay_hint': 'Bepul kalit: pixabay.com/api/docs. Rasmlar faqat pullik taqdimot yaratilayotganda qidiriladi, Pixabay talabi bo‘yicha 24 soat keshlanadi va taqdimotga yuklab olinadi. Bir taqdimotdagi rasmlar soni har bir tarifdagi "max_deck_images" chegarasi. Barcha so‘rovlarni to‘xtatish uchun belgini olib tashlang.',
           'pixabay_connected': 'Pixabay sinov qidiruviga javob berdi.',
           'invalid_pixabay_key': 'Bu Pixabay kalitiga o‘xshamaydi (raqamlar, chiziqcha, so‘ng harf va raqamlar).',
           'pixabay_not_configured': 'Rasmlarni yoqishdan oldin Pixabay kalitini qo‘shing.',
           'pixabay_connection_failed': 'Pixabay sinov qidiruviga javob bermadi. Kalitni tekshiring.'},
    'ru': {'pixabay': 'Стоковые фото (Pixabay)', 'pixabay_enabled': 'Добавлять фото в ИИ-презентации',
           'pixabay_key': 'API-ключ Pixabay',
           'pixabay_hint': 'Бесплатный ключ: pixabay.com/api/docs. Фото ищутся только во время создания оплаченной презентации, кешируются на 24 часа, как требует Pixabay, и загружаются в файл. Сколько фото в одной презентации — лимит «max_deck_images» в каждом тарифе. Снимите флажок, чтобы сразу остановить все запросы.',
           'pixabay_connected': 'Pixabay ответил на тестовый поиск.',
           'invalid_pixabay_key': 'Это не похоже на ключ Pixabay (цифры, дефис, затем буквы и цифры).',
           'pixabay_not_configured': 'Добавьте ключ Pixabay, прежде чем включать фото.',
           'pixabay_connection_failed': 'Pixabay не ответил на тестовый поиск. Проверьте ключ.'},
}
for language, labels in PHOTO_LABELS.items(): LABELS[language].update(labels)
CARD_SECTION_LABELS = {
    'en': {'manual': 'Card transfer payments', 'manual_enabled': 'Let customers pay by card transfer',
           'card_number': 'Card number', 'card_holder': 'Card holder (as the bank shows it)', 'card_label': 'Card type',
           'alert_telegram_id': 'Your Telegram ID for alerts (new payments, file storage problems)',
           'manual_hint': 'Customers who start a payment see this card, the plan price and a reference, transfer the money, and upload the receipt. You approve or reject each one under Payments. Prices are set per plan under Plans (price_uzs). Send /myid to the bot to learn your Telegram ID. Untick to stop new card payments at once.',
           'card_on_file': 'Card on file', 'no_card': 'No card yet',
           'no_prices': 'Customers can’t pay by card yet: Plus and Premium have no price in so‘m. Set their prices in Plans.',
           'open_plans': 'Open Plans',
           'invalid_card_number': 'That card number has a wrong digit. Check it: customers will send money to it.',
           'invalid_card_holder': 'Enter the holder name as letters only, 2 to 60 characters.',
           'invalid_telegram_id': 'A Telegram ID is digits only. Send /myid to the bot to get yours.',
           'manual_payments_not_configured': 'Add the card number and holder before switching card payments on.'},
    'uz': {'manual': 'Karta orqali to‘lov', 'manual_enabled': 'Mijozlarga karta orqali to‘lashga ruxsat berish',
           'card_number': 'Karta raqami', 'card_holder': 'Karta egasi (bank ko‘rsatgandek)', 'card_label': 'Karta turi',
           'alert_telegram_id': 'Xabarlar uchun Telegram ID (yangi to‘lovlar, fayl ombori muammolari)',
           'manual_hint': 'To‘lovni boshlagan mijoz shu kartani, tarif narxini va raqamni ko‘radi, pul o‘tkazadi va kvitansiyani yuboradi. Har birini To‘lovlar bo‘limida tasdiqlaysiz yoki rad etasiz. Narxlar Tariflar bo‘limida (price_uzs). Telegram ID ni bilish uchun botga /myid yuboring. Yangi to‘lovlarni darhol to‘xtatish uchun belgini olib tashlang.',
           'card_on_file': 'Saqlangan karta', 'no_card': 'Karta hali yo‘q',
           'no_prices': 'Mijozlar hali karta orqali to‘lay olmaydi: Plus va Premium uchun so‘mda narx yo‘q. Narxlarni Tariflar bo‘limida kiriting.',
           'open_plans': 'Tariflarni ochish',
           'invalid_card_number': 'Karta raqamida xato raqam bor. Tekshiring: mijozlar pulni shu kartaga yuboradi.',
           'invalid_card_holder': 'Karta egasining ismini faqat harflar bilan, 2–60 belgi kiriting.',
           'invalid_telegram_id': 'Telegram ID faqat raqamlardan iborat. Uni bilish uchun botga /myid yuboring.',
           'manual_payments_not_configured': 'Karta orqali to‘lovni yoqishdan oldin karta raqami va egasini kiriting.'},
    'ru': {'manual': 'Оплата переводом на карту', 'manual_enabled': 'Разрешить оплату переводом на карту',
           'card_number': 'Номер карты', 'card_holder': 'Владелец карты (как в банке)', 'card_label': 'Тип карты',
           'alert_telegram_id': 'Ваш Telegram ID для уведомлений (новые платежи, проблемы хранилища)',
           'manual_hint': 'Клиент, начавший оплату, видит эту карту, цену тарифа и код платежа, переводит деньги и загружает квитанцию. Каждый платёж вы подтверждаете или отклоняете в разделе «Платежи». Цены задаются в «Тарифах» (price_uzs). Чтобы узнать свой Telegram ID, отправьте боту /myid. Снимите флажок, чтобы сразу остановить новые платежи.',
           'card_on_file': 'Сохранённая карта', 'no_card': 'Карта ещё не указана',
           'no_prices': 'Клиенты пока не могут оплатить картой: у Plus и Premium нет цены в сумах. Укажите цены в разделе «Тарифы».',
           'open_plans': 'Открыть тарифы',
           'invalid_card_number': 'В номере карты ошибка. Проверьте: клиенты будут переводить деньги на эту карту.',
           'invalid_card_holder': 'Введите имя владельца только буквами, от 2 до 60 символов.',
           'invalid_telegram_id': 'Telegram ID состоит только из цифр. Отправьте боту /myid, чтобы узнать свой.',
           'manual_payments_not_configured': 'Укажите номер и владельца карты, прежде чем включать оплату переводом.'},
}
for language, labels in CARD_SECTION_LABELS.items(): LABELS[language].update(labels)
CHANNEL_SECTION_LABELS = {
    'en': {'bot_not_configured': 'Set the Telegram bot token above first.', 'channels': 'Required Telegram channels', 'channels_enabled': 'Free users must join these channels to use the services',
           'channels_list': 'Channels, one per line',
           'channels_hint': 'Write @name or https://t.me/name for a public channel. For a private channel or group, write its invite link and its numeric chat ID on one line, e.g. https://t.me/+AbCdEf123 -1001234567890. Add the bot as an administrator of each channel (or a member of each group), then press Check. Paid plans are never asked. If Telegram cannot be reached, customers are let through rather than locked out.',
           'channels_connected': 'The bot can see who has joined every channel.',
           'channel_ok': 'bot can check members', 'channel_bot_not_admin': 'make the bot an administrator', 'channel_chat_not_found': 'not found — check the link or ID', 'channel_unchecked': 'not checked yet',
           'invalid_channel': 'A line is not a channel: use @name, a t.me link, or an invite link with its numeric chat ID.',
           'too_many_channels': 'Add at most 5 channels.', 'channels_not_configured': 'Add at least one channel before switching this on.',
           'channels_bot_not_admin': 'The bot cannot see the members of some channels. Make it an administrator there, then Check again.'},
    'uz': {'bot_not_configured': 'Avval yuqorida Telegram bot tokenini kiriting.', 'channels': 'Majburiy Telegram kanallar', 'channels_enabled': 'Bepul foydalanuvchilar xizmatlardan foydalanish uchun shu kanallarga qo‘shilishi kerak',
           'channels_list': 'Kanallar, har biri alohida qatorda',
           'channels_hint': 'Ochiq kanal uchun @nom yoki https://t.me/nom yozing. Yopiq kanal yoki guruh uchun bir qatorda taklif havolasi va raqamli chat ID ni yozing, masalan https://t.me/+AbCdEf123 -1001234567890. Botni har bir kanalga administrator (guruhga a’zo) qilib qo‘shing, so‘ng «Tekshirish»ni bosing. Pullik tariflardan so‘ralmaydi. Telegram javob bermasa, mijozlar to‘xtatilmaydi.',
           'channels_connected': 'Bot barcha kanallarda kim qo‘shilganini ko‘ra oladi.',
           'channel_ok': 'bot a’zolarni tekshira oladi', 'channel_bot_not_admin': 'botni administrator qiling', 'channel_chat_not_found': 'topilmadi — havola yoki ID ni tekshiring', 'channel_unchecked': 'hali tekshirilmagan',
           'invalid_channel': 'Qatordagi qiymat kanal emas: @nom, t.me havola yoki raqamli chat ID bilan taklif havolasini yozing.',
           'too_many_channels': 'Ko‘pi bilan 5 ta kanal qo‘shing.', 'channels_not_configured': 'Yoqishdan oldin kamida bitta kanal qo‘shing.',
           'channels_bot_not_admin': 'Bot ba’zi kanallar a’zolarini ko‘ra olmaydi. Uni u yerda administrator qiling va qayta tekshiring.'},
    'ru': {'bot_not_configured': 'Сначала укажите токен Telegram-бота выше.', 'channels': 'Обязательные Telegram-каналы', 'channels_enabled': 'Бесплатные пользователи должны подписаться на эти каналы, чтобы пользоваться сервисами',
           'channels_list': 'Каналы, по одному в строке',
           'channels_hint': 'Для открытого канала напишите @имя или https://t.me/имя. Для закрытого канала или группы — ссылку-приглашение и числовой ID чата в одной строке, например https://t.me/+AbCdEf123 -1001234567890. Добавьте бота администратором каждого канала (или участником группы) и нажмите «Проверить». Платные тарифы не затрагиваются. Если Telegram недоступен, клиентов пропускают, а не блокируют.',
           'channels_connected': 'Бот видит подписчиков во всех каналах.',
           'channel_ok': 'бот может проверять подписку', 'channel_bot_not_admin': 'сделайте бота администратором', 'channel_chat_not_found': 'не найден — проверьте ссылку или ID', 'channel_unchecked': 'ещё не проверен',
           'invalid_channel': 'Строка не похожа на канал: укажите @имя, ссылку t.me или ссылку-приглашение с числовым ID чата.',
           'too_many_channels': 'Добавьте не больше 5 каналов.', 'channels_not_configured': 'Добавьте хотя бы один канал, прежде чем включать.',
           'channels_bot_not_admin': 'Бот не видит подписчиков некоторых каналов. Сделайте его там администратором и проверьте снова.'},
}
for language, labels in CHANNEL_SECTION_LABELS.items(): LABELS[language].update(labels)
STORAGE_SECTION_LABELS = {
    'en': {'object_storage': 'File storage (Contabo Object Storage)',
           'storage_problem_canary_failed': 'The hourly test could not write, read or delete a file in the bucket.',
           'storage_problem_upload_backlog': '{waiting} files have waited more than {minutes} minutes to reach the bucket.',
           'storage_working': 'Working', 'storage_last_test': 'Last test', 'storage_last_upload': 'Last upload', 'storage_never': 'not yet',
           'storage_alerts': 'Problems are sent to the Telegram ID set under Card payments, and again when storage recovers.', 'storage_enabled': 'Keep files in the bucket',
           'storage_endpoint': 'Endpoint', 'storage_bucket': 'Bucket', 'storage_region': 'Region (leave empty for Contabo)',
           'storage_access_key': 'Access key', 'storage_secret_key': 'Secret key',
           'storage_hint': 'In the Contabo panel: Object Storage → Security & Access → S3 credentials. Save the keys, press Test, then tick the box. New files go to the bucket from then on, and files already on the server are moved there by the cleanup job within minutes. The server keeps only a short-lived working copy.',
           'storage_in_bucket': 'In the bucket', 'storage_waiting': 'Waiting to upload', 'storage_files': 'files',
           'storage_connected': 'The bucket accepted a test file, returned it and deleted it.',
           'invalid_storage_endpoint': 'The endpoint must be an https address with nothing after the domain, like https://usc1.contabostorage.com.',
           'invalid_storage_bucket': 'That is not a valid bucket name.', 'invalid_storage_region': 'That is not a valid region name.',
           'invalid_storage_key': 'That does not look like an S3 access or secret key.',
           'object_storage_not_configured': 'Save the access key and secret key before turning file storage on.',
           'object_storage_connection_failed': 'The bucket did not accept the test file. Check the keys, bucket name and endpoint.'},
    'uz': {'object_storage': 'Fayl ombori (Contabo Object Storage)',
           'storage_problem_canary_failed': 'Soatlik sinov bucket’da faylni yoza, o‘qiy yoki o‘chira olmadi.',
           'storage_problem_upload_backlog': '{waiting} ta fayl {minutes} daqiqadan ko‘proq bucket’ga yetib borolmayapti.',
           'storage_working': 'Ishlayapti', 'storage_last_test': 'Oxirgi sinov', 'storage_last_upload': 'Oxirgi yuklash', 'storage_never': 'hali yo‘q',
           'storage_alerts': 'Muammolar Karta to‘lovlari bo‘limidagi Telegram ID’ga yuboriladi, tiklanganda ham xabar keladi.', 'storage_enabled': 'Fayllarni bucket’da saqlash',
           'storage_endpoint': 'Endpoint', 'storage_bucket': 'Bucket', 'storage_region': 'Region (Contabo uchun bo‘sh qoldiring)',
           'storage_access_key': 'Access key', 'storage_secret_key': 'Secret key',
           'storage_hint': 'Contabo panelida: Object Storage → Security & Access → S3 credentials. Kalitlarni saqlang, «Tekshirish»ni bosing, keyin belgini qo‘ying. Shundan so‘ng yangi fayllar bucket’ga tushadi, serverdagi mavjud fayllar esa bir necha daqiqada tozalash jarayoni orqali ko‘chiriladi. Serverda faqat qisqa muddatli ishchi nusxa qoladi.',
           'storage_in_bucket': 'Bucket’da', 'storage_waiting': 'Yuklanishni kutmoqda', 'storage_files': 'ta fayl',
           'storage_connected': 'Bucket sinov faylini qabul qildi, qaytardi va o‘chirdi.',
           'invalid_storage_endpoint': 'Endpoint https manzil bo‘lishi kerak va domendan keyin hech narsa bo‘lmasin, masalan https://usc1.contabostorage.com.',
           'invalid_storage_bucket': 'Bucket nomi noto‘g‘ri.', 'invalid_storage_region': 'Region nomi noto‘g‘ri.',
           'invalid_storage_key': 'Bu S3 access yoki secret key’ga o‘xshamaydi.',
           'object_storage_not_configured': 'Fayl omborini yoqishdan oldin access key va secret key’ni saqlang.',
           'object_storage_connection_failed': 'Bucket sinov faylini qabul qilmadi. Kalitlar, bucket nomi va endpoint’ni tekshiring.'},
    'ru': {'object_storage': 'Хранилище файлов (Contabo Object Storage)',
           'storage_problem_canary_failed': 'Ежечасная проверка не смогла записать, прочитать или удалить файл в бакете.',
           'storage_problem_upload_backlog': '{waiting} файлов ждут загрузки в бакет дольше {minutes} минут.',
           'storage_working': 'Работает', 'storage_last_test': 'Последняя проверка', 'storage_last_upload': 'Последняя загрузка', 'storage_never': 'ещё нет',
           'storage_alerts': 'О проблемах сообщается в Telegram ID из раздела «Оплата картой», и ещё раз — когда хранилище восстановится.', 'storage_enabled': 'Хранить файлы в бакете',
           'storage_endpoint': 'Endpoint', 'storage_bucket': 'Бакет', 'storage_region': 'Регион (для Contabo оставьте пустым)',
           'storage_access_key': 'Access key', 'storage_secret_key': 'Secret key',
           'storage_hint': 'В панели Contabo: Object Storage → Security & Access → S3 credentials. Сохраните ключи, нажмите «Проверить», затем отметьте флажок. После этого новые файлы попадают в бакет, а файлы, уже лежащие на сервере, переносятся туда задачей очистки за несколько минут. На сервере остаётся только короткоживущая рабочая копия.',
           'storage_in_bucket': 'В бакете', 'storage_waiting': 'Ждут загрузки', 'storage_files': 'файлов',
           'storage_connected': 'Бакет принял тестовый файл, вернул его и удалил.',
           'invalid_storage_endpoint': 'Endpoint должен быть https-адресом без пути после домена, например https://usc1.contabostorage.com.',
           'invalid_storage_bucket': 'Некорректное имя бакета.', 'invalid_storage_region': 'Некорректное имя региона.',
           'invalid_storage_key': 'Это не похоже на S3 access или secret key.',
           'object_storage_not_configured': 'Сохраните access key и secret key, прежде чем включать хранилище.',
           'object_storage_connection_failed': 'Бакет не принял тестовый файл. Проверьте ключи, имя бакета и endpoint.'},
}
for language, labels in STORAGE_SECTION_LABELS.items(): LABELS[language].update(labels)


@require_staff()
@sensitive_post_parameters('token','api_key','client_secret','password','secret_key','pixabay_key','access_key')
@require_http_methods(['GET','POST'])
def integrations(request):
    data=context(request,'integrations');labels=LABELS[data['lang']];data['i']=labels;data['title']=labels['integrations']
    if request.method=='POST':
        action=request.POST.get('action','save')
        try:
            key=request.POST.get('integration','telegram')
            if action!='save' and key!='telegram' and not (key in ('email','pixabay','channels','object_storage') and action=='test'):raise DomainError('invalid_parameters')
            if action=='save':save_config(key,request.POST);message='saved'
            elif action=='test':
                if key=='email':test_email();message='email_connected'
                elif key=='pixabay':test_pixabay();message='pixabay_connected'
                elif key=='object_storage':test_object_storage();message='storage_connected'
                elif key=='channels':test_channels();message='channels_connected'
                else:test_telegram();message='connected'
            elif action in ('start','stop'):
                if not development_access(request):raise DomainError('local_control_only',403)
                control_runner(action);message='action_done'
            else:raise DomainError('invalid_parameters')
            after={'configured':True}
            # Who changed the card customers pay into, and to which one, must be traceable.
            if key=='manual_payments':
                card=manual_payment_config();after.update(card_last4=card['card_number'][-4:],enabled=card['enabled'])
            audit(request.ops_user,'integration.'+action,key,after=after)
            return redirect('/ops/integrations?lang='+data['lang']+'&notice='+message)
        except DomainError as e:
            data['error']=labels.get(e.code,labels['failure']);data['error_code']=e.code
            # The card the problem belongs to stays open, with what was typed.
            data['open_integration']=request.POST.get('integration','telegram')
    bot=telegram_config();ai=ai_config();google=google_config();email=email_config();antibot=antibot_config()
    local_controls=development_access(request)
    # A container-managed bot has a different PID namespace from the API.
    # Do not misreport it as stopped using the local development PID check.
    status=labels[runner_status()] if local_controls else labels['managed' if bot['token'] else 'waiting']
    # Never include credentials in the template context.
    data.update(bot={'username':bot['username'],'webapp_url':bot['webapp_url'],'configured':bool(bot['token']),'status':status},ai={'mode':ai['mode'],'model':ai['model'],'image_model':ai['image_model'],'configured':bool(ai['api_key'])},local_controls=local_controls,notice=labels.get(request.GET.get('notice',''),''))
    data['google'] = {key: google[key] for key in ('enabled','client_id','redirect_uri','configured','ready')}
    data['email'] = {key: email[key] for key in ('enabled','host','port','username','use_tls','use_ssl','from_email','configured','ready')}
    data['antibot'] = {key: antibot[key] for key in ('web_enabled','bot_enabled','site_key','allowed_hostnames','configured','ready')}
    data['antibot']['hostnames_text'] = '\n'.join(antibot['allowed_hostnames'])
    photos=pixabay_config()
    data['pixabay'] = {key: photos[key] for key in ('enabled','configured','ready')}
    # The keys never reach the page: only whether they are saved.
    from apps.core import storage
    bucket=object_storage_config()
    from apps.core.storage_health import summary as storage_summary
    health=storage_summary()
    problems=[labels['storage_problem_'+p['code']].format(**p) for p in health['problems']] if bucket['ready'] else []
    data['object_storage']={**{key: bucket[key] for key in ('enabled','configured','ready','endpoint','bucket','region')},**storage.health(),
                            'healthy':not problems,'problems':problems,'last_upload':health['last_upload'],
                            'canary_at':datetime.fromisoformat(health['canary_at']) if health['canary_at'] else None,'canary_ok':health['canary_ok']}
    gate=channel_gate_config()
    data['channels']={'enabled':gate['enabled'],'ready':gate['ready'],
                      'text':'\n'.join(c['chat'] if c['url']=='https://t.me/'+c['chat'].lstrip('@') else c['url']+' '+c['chat'] for c in gate['channels']),
                      'rows':[{'title':c['title'],'url':c['url'],'state':'unchecked' if c['check']['ok'] is None else 'ok' if c['check']['ok'] else (c['check']['reason'] or 'bot_not_admin')} for c in gate['channels']]}
    card=manual_payment_config()
    from apps.commerce.manual import prices as card_prices
    # A saved card is not enough: customers are offered card payment only for a
    # plan with a price in so'm, so without one the card is never shown.
    data['manual'] = {**{key: card[key] for key in ('enabled','configured','ready','card_number','card_holder','card_label','alert_telegram_id')},
                      'priced':bool(card_prices()),
                      'labels':CARD_LABELS,'card_display':' '.join(card['card_number'][i:i+4] for i in range(0,len(card['card_number']),4))}
    return finish_render(request,'ops/integrations.html',data)
