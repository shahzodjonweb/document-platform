from django.conf import settings
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from apps.core.errors import DomainError
from .auth import require_staff,audit,development_access
from .views import context,finish_render
from datetime import datetime
from .integrations import inpay_config,test_inpay,test_autopay,telegram_config,ai_config,google_config,email_config,antibot_config,pixabay_config,manual_payment_config,channel_gate_config,test_channels,CARD_LABELS,save_config,test_telegram,menu_button,apply_menu_button,test_email,test_pixabay,control_runner,runner_status,object_storage_config,test_object_storage
from .models import IntegrationConfig
from apps.studio.tuning import EFFORTS,TIERS

LABELS={
'en':{'integrations':'Integrations','intro':'Connect your Telegram bot and choose the document generation provider. Secrets are encrypted and never shown after saving.','telegram':'Telegram bot','token':'Bot token','username':'Bot username','webapp':'Web application URL','secret_hint':'Leave blank to keep the saved secret.','reason':'Reason for this change','save':'Save configuration','test':'Test connection','start':'Start local bot','stop':'Stop local bot','ai':'Document generation','mode':'Provider mode','local':'Local authoring · no AI calls','live':'OpenAI · real API calls','disabled':'Disabled','key':'API key','model':'Model ID','configured':'Configured','missing':'Not configured','running':'Running','stopped':'Stopped','local_note':'Local polling needs a real Telegram token. Telegram Mini Apps require an HTTPS URL; ordinary browser tools work on localhost.','saved':'Configuration saved.','connected':'Connected to Telegram.','action_done':'Bot control updated.','failure':'Could not complete this action. Check configuration and try again.','need_reason':'Enter a reason of at least 5 characters.','token_status':'Token status','provider_status':'Provider status','simulator':'Open local bot simulator'},
'uz':{'integrations':'Integratsiyalar','intro':'Telegram botingizni ulang va hujjat yaratish provayderini tanlang. Maxfiy kalitlar shifrlanadi va saqlangandan keyin ko‘rsatilmaydi.','telegram':'Telegram bot','token':'Bot tokeni','username':'Bot foydalanuvchi nomi','webapp':'Veb ilova manzili','secret_hint':'Saqlangan kalitni qoldirish uchun bo‘sh qoldiring.','reason':'O‘zgarish sababi','save':'Sozlamalarni saqlash','test':'Ulanishni tekshirish','start':'Mahalliy botni ishga tushirish','stop':'Mahalliy botni to‘xtatish','ai':'Hujjat yaratish','mode':'Provayder rejimi','local':'Mahalliy tahrirlash · AI chaqirilmaydi','live':'OpenAI · haqiqiy API','disabled':'O‘chirilgan','key':'API kaliti','model':'Model identifikatori','configured':'Sozlangan','missing':'Sozlanmagan','running':'Ishlamoqda','stopped':'To‘xtatilgan','local_note':'Mahalliy bot uchun haqiqiy Telegram tokeni kerak. Telegram Mini App uchun HTTPS manzil zarur; brauzer vositalari localhost’da ishlaydi.','saved':'Sozlamalar saqlandi.','connected':'Telegram ulandi.','action_done':'Bot boshqaruvi yangilandi.','failure':'Amal bajarilmadi. Sozlamalarni tekshirib, qayta urinib ko‘ring.','need_reason':'Kamida 5 belgidan iborat sabab kiriting.','token_status':'Token holati','provider_status':'Provayder holati','simulator':'Mahalliy bot simulyatorini ochish'},
'ru':{'integrations':'Интеграции','intro':'Подключите Telegram-бота и выберите провайдера генерации документов. Секреты шифруются и не показываются после сохранения.','telegram':'Telegram-бот','token':'Токен бота','username':'Имя бота','webapp':'Адрес веб-приложения','secret_hint':'Оставьте пустым, чтобы сохранить текущий ключ.','reason':'Причина изменения','save':'Сохранить настройки','test':'Проверить соединение','start':'Запустить локального бота','stop':'Остановить локального бота','ai':'Генерация документов','mode':'Режим провайдера','local':'Локальное редактирование · без ИИ','live':'OpenAI · реальные вызовы API','disabled':'Отключено','key':'Ключ API','model':'ID модели','configured':'Настроено','missing':'Не настроено','running':'Работает','stopped':'Остановлен','local_note':'Для локального бота нужен настоящий токен Telegram. Mini App требует HTTPS; инструменты браузера работают на localhost.','saved':'Настройки сохранены.','connected':'Соединение с Telegram установлено.','action_done':'Управление ботом обновлено.','failure':'Не удалось выполнить действие. Проверьте настройки и повторите.','need_reason':'Укажите причину длиной не менее 5 символов.','token_status':'Состояние токена','provider_status':'Состояние провайдера','simulator':'Открыть локальный симулятор бота'}}

for language,label in {'en':'Image model ID (optional)','uz':'Rasm modeli identifikatori (ixtiyoriy)','ru':'ID модели изображений (необязательно)'}.items():LABELS[language]['image_model']=label
# Call tuning (apps/studio/tuning.py).
for language,labels in {
    'en':{'writing_effort':'Reasoning effort: writing','photo_effort':'Reasoning effort: photo choice','service_tier':'Processing tier',
          'model_default':'Model default','account_default':'Account default','tier_priority':'Priority (faster, costs more)',
          'tuning_note':'Each call takes about 1 s plus 9.5 ms per output token, reasoning included. A setting the model does not accept is left out automatically.','parallel_parts':'Write long new documents in parts side by side (planned first)'},
    'uz':{'writing_effort':'Fikrlash darajasi: matn yozish','photo_effort':'Fikrlash darajasi: rasm tanlash','service_tier':'Ishlov berish darajasi',
          'model_default':'Model standarti','account_default':'Hisob standarti','tier_priority':'Ustuvor (tezroq, qimmatroq)',
          'tuning_note':'Har bir chaqiruv taxminan 1 soniya va har bir chiqish tokeni uchun 9,5 ms davom etadi, fikrlash ham shunga kiradi. Model qabul qilmaydigan sozlama avtomatik tashlab yuboriladi.','parallel_parts':'Uzun yangi hujjatlarni qismlab bir vaqtda yozish (avval reja)'},
    'ru':{'writing_effort':'Уровень рассуждений: текст','photo_effort':'Уровень рассуждений: выбор фото','service_tier':'Уровень обработки',
          'model_default':'По умолчанию модели','account_default':'По умолчанию аккаунта','tier_priority':'Приоритетный (быстрее, дороже)',
          'tuning_note':'Каждый вызов занимает около 1 с плюс 9,5 мс на выходной токен, включая рассуждения. Настройка, которую модель не принимает, отбрасывается автоматически.','parallel_parts':'Писать длинные новые документы частями параллельно (сначала план)'},
}.items():LABELS[language].update(labels)

# The Mini App on the bot's card: always on at an HTTPS address (operations/integrations.py mini_app_ready).
for language,labels in {
    'en':{'mini_app_note':'Telegram’s menu button beside the message field, «DOC Master mini-app», and the bot’s Open app buttons always open this web application inside Telegram, signed in to the same account; the bot keeps working as before. Needs an HTTPS address. The menu button takes the place of the command list; commands still work when typed with /.',
          'menu_pending':'Saved. Telegram could not be told about the menu button just now; the bot sets it when it next starts.'},
    'uz':{'mini_app_note':'Xabar maydoni yonidagi Telegram menyu tugmasi «DOC Master mini-app» va botning «Ilovani ochish» tugmalari shu veb ilovani har doim Telegram ichida, o‘sha hisob bilan ochadi; bot avvalgidek ishlayveradi. HTTPS manzil kerak. Menyu tugmasi buyruqlar ro‘yxati o‘rnini egallaydi; buyruqlar / bilan yozilganda ishlayveradi.',
          'menu_pending':'Saqlandi. Menyu tugmasi haqida Telegram’ga hozir xabar berib bo‘lmadi; bot keyingi safar ishga tushganda uni o‘rnatadi.'},
    'ru':{'mini_app_note':'Кнопка меню Telegram рядом с полем ввода, «DOC Master mini-app», и кнопки бота «Открыть приложение» всегда открывают это веб-приложение внутри Telegram с тем же аккаунтом; бот работает как прежде. Нужен адрес HTTPS. Кнопка меню заменяет список команд; команды по-прежнему работают, если набрать /.',
          'menu_pending':'Сохранено. Сообщить Telegram о кнопке меню сейчас не удалось; бот установит её при следующем запуске.'},
}.items():LABELS[language].update(labels)

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
        'invalid_antibot_hostnames': 'Use exact hostnames, such as docmaster.live. URLs, ports, and wildcards are not accepted.',
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
        'invalid_antibot_hostnames': 'docmaster.live kabi aniq domen kiriting. URL, port va yulduzcha belgisi qabul qilinmaydi.',
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
        'invalid_antibot_hostnames': 'Укажите точный домен, например docmaster.live. URL, порты и звёздочки не допускаются.',
        'invalid_antibot_site_key': 'Проверьте и вставьте ключ сайта Turnstile ещё раз.',
        'invalid_antibot_secret_key': 'Проверьте и вставьте секретный ключ Turnstile ещё раз.',
        'antibot_test_keys_forbidden': 'Для рабочего сайта нужны настоящие ключи Turnstile. Тестовые ключи доступны только при локальной разработке.',
    },
}
for language, labels in ANTIBOT_LABELS.items(): LABELS[language].update(labels)

PHOTO_LABELS = {
    'en': {'pixabay': 'Stock photos (Pixabay)', 'pixabay_enabled': 'Add photos to AI slide decks',
           'pixabay_key': 'Pixabay API key',
           'pixabay_hint': 'Free key from pixabay.com/api/docs. Photos are searched while a paid deck is being generated and, with the editor switch \"Fetching pictures outside an AI run\" on, when a customer adds pictures in the slide editor (3 fills and 10 searches a day per account, 12 pictures a deck); answers are cached for 24 hours as Pixabay requires, and downloaded into the deck — never hotlinked. How many photos a deck may use is the "max_deck_images" limit on each plan. Untick to stop all photo requests at once.',
           'pixabay_connected': 'Pixabay answered a test search.',
           'invalid_pixabay_key': 'That does not look like a Pixabay key (digits, a dash, then letters and digits).',
           'pixabay_not_configured': 'Add a Pixabay key before turning photos on.',
           'pixabay_connection_failed': 'Pixabay did not answer the test search. Check the key.'},
    'uz': {'pixabay': 'Stok rasmlar (Pixabay)', 'pixabay_enabled': 'AI taqdimotlariga rasm qo‘shish',
           'pixabay_key': 'Pixabay API kaliti',
           'pixabay_hint': 'Bepul kalit: pixabay.com/api/docs. Rasmlar pullik taqdimot yaratilayotganda va muharrirdagi «Rasmlarni AI ishidan tashqari olish» yoqilgan bo‘lsa, mijoz slayd muharririda rasm qo‘shganda qidiriladi (hisobga kuniga 3 ta to‘ldirish va 10 ta qidiruv, taqdimotga 12 ta rasm); javoblar Pixabay talabi bo‘yicha 24 soat keshlanadi va taqdimotga yuklab olinadi. Bir taqdimotdagi rasmlar soni har bir tarifdagi "max_deck_images" chegarasi. Barcha so‘rovlarni to‘xtatish uchun belgini olib tashlang.',
           'pixabay_connected': 'Pixabay sinov qidiruviga javob berdi.',
           'invalid_pixabay_key': 'Bu Pixabay kalitiga o‘xshamaydi (raqamlar, chiziqcha, so‘ng harf va raqamlar).',
           'pixabay_not_configured': 'Rasmlarni yoqishdan oldin Pixabay kalitini qo‘shing.',
           'pixabay_connection_failed': 'Pixabay sinov qidiruviga javob bermadi. Kalitni tekshiring.'},
    'ru': {'pixabay': 'Стоковые фото (Pixabay)', 'pixabay_enabled': 'Добавлять фото в ИИ-презентации',
           'pixabay_key': 'API-ключ Pixabay',
           'pixabay_hint': 'Бесплатный ключ: pixabay.com/api/docs. Фото ищутся во время создания оплаченной презентации и, если в редакторе включено «Подбор изображений вне запуска ИИ», когда клиент добавляет изображения в редакторе слайдов (3 подбора и 10 поисков в день на учётную запись, 12 изображений на презентацию); ответы кешируются на 24 часа, как требует Pixabay, и загружаются в файл. Сколько фото в одной презентации — лимит «max_deck_images» в каждом тарифе. Снимите флажок, чтобы сразу остановить все запросы.',
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
           'manual_hint': 'Customers who start a payment see this card, the plan price and a reference, transfer the money, and upload the receipt. You approve or reject each one under Payments. Prices are set per plan under Plans (price and discount). Send /myid to the bot to learn your Telegram ID. Untick to stop new card payments at once.',
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
           'manual_hint': 'To‘lovni boshlagan mijoz shu kartani, tarif narxini va raqamni ko‘radi, pul o‘tkazadi va kvitansiyani yuboradi. Har birini To‘lovlar bo‘limida tasdiqlaysiz yoki rad etasiz. Narxlar Tariflar bo‘limida (narx va chegirma). Telegram ID ni bilish uchun botga /myid yuboring. Yangi to‘lovlarni darhol to‘xtatish uchun belgini olib tashlang.',
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
           'manual_hint': 'Клиент, начавший оплату, видит эту карту, цену тарифа и код платежа, переводит деньги и загружает квитанцию. Каждый платёж вы подтверждаете или отклоняете в разделе «Платежи». Цены задаются в «Тарифах» (цена и скидка). Чтобы узнать свой Telegram ID, отправьте боту /myid. Снимите флажок, чтобы сразу остановить новые платежи.',
           'card_on_file': 'Сохранённая карта', 'no_card': 'Карта ещё не указана',
           'no_prices': 'Клиенты пока не могут оплатить картой: у Plus и Premium нет цены в сумах. Укажите цены в разделе «Тарифы».',
           'open_plans': 'Открыть тарифы',
           'invalid_card_number': 'В номере карты ошибка. Проверьте: клиенты будут переводить деньги на эту карту.',
           'invalid_card_holder': 'Введите имя владельца только буквами, от 2 до 60 символов.',
           'invalid_telegram_id': 'Telegram ID состоит только из цифр. Отправьте боту /myid, чтобы узнать свой.',
           'manual_payments_not_configured': 'Укажите номер и владельца карты, прежде чем включать оплату переводом.'},
}
for language, labels in CARD_SECTION_LABELS.items(): LABELS[language].update(labels)
# Automatic payments through inPAY (apps/commerce/checkout.py).
INPAY_SECTION_LABELS = {'en': {'inpay': 'Automatic payments (inPAY)', 'inpay_enabled': 'Let customers pay online through inPAY', 'inpay_secret_key': 'API v2 secret key (sk_live_… or sk_test_…)', 'inpay_webhook_secret': 'Webhook signing secret (whsec_…), optional', 'inpay_remove_key': 'Remove the saved v2 key', 'inpay_v1': 'Classic API v1, only if the kassa has no v2 keys', 'inpay_merchant_id': 'Merchant ID', 'inpay_merchant_token': 'Merchant token', 'inpay_hint': 'Customers choose a plan, pay on inPAY’s page with Click, Payme, Uzcard or Humo, and the plan switches on by itself. In the inPAY cabinet create a kassa of type «Veb-sayt» for the website shown above, open Kassa → API v2 keys and paste the secret key here. Save, press Test connection, then tick the box. With a test key (sk_test_) only you see the option, as the Telegram ID saved under Card transfer payments, and a test payment grants nothing; save the live key to start selling. inPAY returns money only from its own cabinet: return it there, then mark the refund on the payment’s page under Payments.', 'inpay_site': 'Kassa website', 'inpay_webhook_url': 'Webhook address (sent with every payment; set it as the kassa’s default too)', 'inpay_mode': 'Mode', 'inpay_mode_live': 'Live: real payments', 'inpay_mode_test': 'Test: only you see it, nothing is granted', 'inpay_mode_none': 'No key saved', 'inpay_signed': 'Webhooks are checked by signature.', 'inpay_unsigned': 'No signing secret is saved. Every payment is still confirmed by asking inPAY directly; Test connection fetches the secret when the key is live.', 'inpay_no_owner': 'With a test key the option is shown only to the Telegram ID saved under Card transfer payments. Save yours there first (send /myid to the bot).', 'inpay_no_site': 'Save the web application URL under Telegram bot first: inPAY returns customers to that website.', 'inpay_connected': 'inPAY accepted the saved credentials.', 'invalid_inpay_key': 'That is not an inPAY v2 secret key. It starts with sk_live_ or sk_test_.', 'invalid_inpay_webhook_secret': 'A webhook signing secret starts with whsec_.', 'invalid_inpay_merchant': 'Check the merchant ID (digits only) and the merchant token.', 'inpay_not_configured': 'Save an inPAY key before switching automatic payments on.', 'inpay_connection_failed': 'inPAY did not accept the saved credentials. Check the key, and that the kassa is approved.'},
 'uz': {'inpay': 'Avtomatik to‘lovlar (inPAY)', 'inpay_enabled': 'Mijozlarga inPAY orqali onlayn to‘lashga ruxsat berish', 'inpay_secret_key': 'API v2 maxfiy kaliti (sk_live_… yoki sk_test_…)', 'inpay_webhook_secret': 'Webhook imzo siri (whsec_…), ixtiyoriy', 'inpay_remove_key': 'Saqlangan v2 kalitini o‘chirish', 'inpay_v1': 'Klassik API v1, faqat kassada v2 kalitlari bo‘lmasa', 'inpay_merchant_id': 'Merchant ID', 'inpay_merchant_token': 'Merchant token', 'inpay_hint': 'Mijoz tarifni tanlaydi, inPAY sahifasida Click, Payme, Uzcard yoki Humo orqali to‘laydi va tarif o‘zi yoqiladi. inPAY kabinetida yuqorida ko‘rsatilgan sayt uchun «Veb-sayt» turidagi kassa yarating, Kassa → API v2 kalitlari bo‘limini ochib, maxfiy kalitni shu yerga kiriting. Saqlang, «Ulanishni tekshirish»ni bosing, so‘ng belgini qo‘ying. Sinov kaliti (sk_test_) bilan bu usulni faqat siz ko‘rasiz (Karta orqali to‘lov bo‘limidagi Telegram ID bo‘yicha) va sinov to‘lovi hech narsa bermaydi; sotishni boshlash uchun jonli kalitni saqlang. inPAY pulni faqat o‘z kabineti orqali qaytaradi: avval o‘sha yerda qaytaring, so‘ng To‘lovlar bo‘limidagi to‘lov sahifasida belgilang.', 'inpay_site': 'Kassa sayti', 'inpay_webhook_url': 'Webhook manzili (har bir to‘lov bilan yuboriladi; kassaning standart manzili sifatida ham kiriting)', 'inpay_mode': 'Rejim', 'inpay_mode_live': 'Jonli: haqiqiy to‘lovlar', 'inpay_mode_test': 'Sinov: faqat siz ko‘rasiz, hech narsa berilmaydi', 'inpay_mode_none': 'Kalit saqlanmagan', 'inpay_signed': 'Webhooklar imzo bo‘yicha tekshiriladi.', 'inpay_unsigned': 'Imzo siri saqlanmagan. Har bir to‘lov baribir inPAY’dan to‘g‘ridan-to‘g‘ri so‘rab tasdiqlanadi; kalit jonli bo‘lsa, «Ulanishni tekshirish» sirni o‘zi oladi.', 'inpay_no_owner': 'Sinov kaliti bilan bu usul faqat Karta orqali to‘lov bo‘limida saqlangan Telegram ID’ga ko‘rinadi. Avval o‘zingiznikini o‘sha yerda saqlang (botga /myid yuboring).', 'inpay_no_site': 'Avval Telegram bot bo‘limida veb ilova manzilini saqlang: inPAY mijozni o‘sha saytga qaytaradi.', 'inpay_connected': 'inPAY saqlangan ma’lumotlarni qabul qildi.', 'invalid_inpay_key': 'Bu inPAY v2 maxfiy kaliti emas. U sk_live_ yoki sk_test_ bilan boshlanadi.', 'invalid_inpay_webhook_secret': 'Webhook imzo siri whsec_ bilan boshlanadi.', 'invalid_inpay_merchant': 'Merchant ID (faqat raqamlar) va merchant tokenni tekshiring.', 'inpay_not_configured': 'Avtomatik to‘lovlarni yoqishdan oldin inPAY kalitini saqlang.', 'inpay_connection_failed': 'inPAY saqlangan ma’lumotlarni qabul qilmadi. Kalitni va kassa tasdiqlanganini tekshiring.'},
 'ru': {'inpay': 'Автоматическая оплата (inPAY)', 'inpay_enabled': 'Разрешить онлайн-оплату через inPAY', 'inpay_secret_key': 'Секретный ключ API v2 (sk_live_… или sk_test_…)', 'inpay_webhook_secret': 'Секрет подписи вебхуков (whsec_…), необязательно', 'inpay_remove_key': 'Удалить сохранённый ключ v2', 'inpay_v1': 'Классический API v1, только если у кассы нет ключей v2', 'inpay_merchant_id': 'Merchant ID', 'inpay_merchant_token': 'Merchant token', 'inpay_hint': 'Клиент выбирает тариф, платит на странице inPAY через Click, Payme, Uzcard или Humo, и тариф включается сам. В кабинете inPAY создайте кассу типа «Veb-sayt» для сайта, указанного выше, откройте Касса → Ключи API v2 и вставьте секретный ключ сюда. Сохраните, нажмите «Проверить соединение», затем отметьте флажок. С тестовым ключом (sk_test_) способ видите только вы (по Telegram ID из раздела «Оплата переводом на карту»), и тестовая оплата ничего не выдаёт; чтобы начать продажи, сохраните боевой ключ. inPAY возвращает деньги только из своего кабинета: верните их там, затем отметьте возврат на странице платежа в разделе «Платежи».', 'inpay_site': 'Сайт кассы', 'inpay_webhook_url': 'Адрес вебхука (передаётся с каждым платежом; укажите его и как адрес кассы по умолчанию)', 'inpay_mode': 'Режим', 'inpay_mode_live': 'Боевой: реальные платежи', 'inpay_mode_test': 'Тестовый: видите только вы, ничего не выдаётся', 'inpay_mode_none': 'Ключ не сохранён', 'inpay_signed': 'Вебхуки проверяются по подписи.', 'inpay_unsigned': 'Секрет подписи не сохранён. Каждый платёж всё равно подтверждается прямым запросом в inPAY; с боевым ключом «Проверить соединение» получает секрет само.', 'inpay_no_owner': 'С тестовым ключом способ показывается только Telegram ID из раздела «Оплата переводом на карту». Сначала сохраните там свой (отправьте боту /myid).', 'inpay_no_site': 'Сначала сохраните адрес веб-приложения в разделе Telegram-бота: inPAY возвращает клиентов на этот сайт.', 'inpay_connected': 'inPAY принял сохранённые данные.', 'invalid_inpay_key': 'Это не секретный ключ inPAY v2. Он начинается с sk_live_ или sk_test_.', 'invalid_inpay_webhook_secret': 'Секрет подписи вебхуков начинается с whsec_.', 'invalid_inpay_merchant': 'Проверьте Merchant ID (только цифры) и merchant token.', 'inpay_not_configured': 'Сохраните ключ inPAY, прежде чем включать автоматическую оплату.', 'inpay_connection_failed': 'inPAY не принял сохранённые данные. Проверьте ключ и что касса одобрена.'}}
for language, labels in INPAY_SECTION_LABELS.items(): LABELS[language].update(labels)
# How customers pay right now: shown on both payment cards.
PAYMENT_WAY_LABELS = {'en': {'payment_way': 'Customers pay by', 'way_inpay': 'Automatic payment through inPAY. Card transfer is not shown; it comes back by itself if inPAY cannot open a payment.', 'way_inpay_test': 'Card transfer. With the test key only you see automatic payment.', 'way_card': 'Card transfer. Automatic payment is not set up.', 'way_card_fallback': 'Card transfer for now: inPAY could not open the last payment. inPAY is tried again within 10 minutes.', 'way_none': 'Nothing yet: neither way to pay is ready.'}, 'uz': {'payment_way': 'Mijozlar to‘lov usuli', 'way_inpay': 'inPAY orqali avtomatik to‘lov. Kartaga o‘tkazma ko‘rsatilmaydi; inPAY to‘lov ocha olmasa, o‘zi qaytadi.', 'way_inpay_test': 'Kartaga o‘tkazma. Sinov kaliti bilan avtomatik to‘lovni faqat siz ko‘rasiz.', 'way_card': 'Kartaga o‘tkazma. Avtomatik to‘lov sozlanmagan.', 'way_card_fallback': 'Hozircha kartaga o‘tkazma: inPAY oxirgi to‘lovni ocha olmadi. inPAY 10 daqiqa ichida qayta sinab ko‘riladi.', 'way_none': 'Hozircha hech qaysi: ikkala usul ham tayyor emas.'}, 'ru': {'payment_way': 'Клиенты платят', 'way_inpay': 'Автоматической оплатой через inPAY. Перевод на карту не показывается; он вернётся сам, если inPAY не сможет открыть платёж.', 'way_inpay_test': 'Переводом на карту. С тестовым ключом автоматическую оплату видите только вы.', 'way_card': 'Переводом на карту. Автоматическая оплата не настроена.', 'way_card_fallback': 'Пока переводом на карту: inPAY не смог открыть последний платёж. inPAY попробуем снова в течение 10 минут.', 'way_none': 'Пока никак: ни один способ оплаты не готов.'}}
for language, labels in PAYMENT_WAY_LABELS.items(): LABELS[language].update(labels)
# One inPAY kassa for the website and one for the bot: inPAY approves a kassa for one place.
INPAY_KASSA_LABELS = {
    'en': {'inpay': 'Automatic payments on the website (inPAY)', 'inpay_bot': 'Automatic payments in the bot (inPAY)',
           'inpay_enabled': 'Let customers on the website pay online through inPAY',
           'inpay_bot_enabled': 'Let customers in the bot pay online through inPAY',
           'inpay_bot_hint': 'Customers in the bot choose a plan, pay on inPAY’s page with Click, Payme, Uzcard or Humo, come back to the chat, and the plan switches on by itself. In the inPAY cabinet create a kassa of type «Telegram» for the bot’s link shown above. In that kassa set the Webhook URL to the address shown above, open API v2 keys and paste the secret key here. Save, press Test connection, then tick the box. With a test key (sk_test_) only you see the option, as the Telegram ID saved under Card transfer payments, and a test payment grants nothing; save the live key to start selling. inPAY returns money only from its own cabinet: return it there, then mark the refund on the payment’s page under Payments.',
           'inpay_bot_site': 'Kassa website (the bot’s link)',
           'inpay_bot_webhook_url': 'Webhook address (set it as the kassa’s Webhook URL in the inPAY cabinet)',
           'inpay_no_bot': 'The bot’s username is not saved yet: press Test connection under Telegram bot. Until then customers stay on inPAY’s page after paying instead of coming back to the chat.',
           'payment_way_web': 'Website customers pay by', 'payment_way_bot': 'Bot customers pay by'},
    'uz': {'inpay': 'Saytda avtomatik to‘lovlar (inPAY)', 'inpay_bot': 'Botda avtomatik to‘lovlar (inPAY)',
           'inpay_enabled': 'Saytdagi mijozlarga inPAY orqali onlayn to‘lashga ruxsat berish',
           'inpay_bot_enabled': 'Botdagi mijozlarga inPAY orqali onlayn to‘lashga ruxsat berish',
           'inpay_bot_hint': 'Botdagi mijoz tarifni tanlaydi, inPAY sahifasida Click, Payme, Uzcard yoki Humo orqali to‘laydi, chatga qaytadi va tarif o‘zi yoqiladi. inPAY kabinetida yuqorida ko‘rsatilgan bot havolasi uchun «Telegram» turidagi kassa yarating. O‘sha kassada Webhook URL sifatida yuqoridagi manzilni kiriting, API v2 kalitlari bo‘limini ochib, maxfiy kalitni shu yerga kiriting. Saqlang, «Ulanishni tekshirish»ni bosing, so‘ng belgini qo‘ying. Sinov kaliti (sk_test_) bilan bu usulni faqat siz ko‘rasiz (Karta orqali to‘lov bo‘limidagi Telegram ID bo‘yicha) va sinov to‘lovi hech narsa bermaydi; sotishni boshlash uchun jonli kalitni saqlang. inPAY pulni faqat o‘z kabineti orqali qaytaradi: avval o‘sha yerda qaytaring, so‘ng To‘lovlar bo‘limidagi to‘lov sahifasida belgilang.',
           'inpay_bot_site': 'Kassa sayti (bot havolasi)',
           'inpay_bot_webhook_url': 'Webhook manzili (inPAY kabinetida kassaning Webhook URL maydoniga kiriting)',
           'inpay_no_bot': 'Bot foydalanuvchi nomi hali saqlanmagan: Telegram bot bo‘limida «Ulanishni tekshirish»ni bosing. Shungacha mijozlar to‘lovdan keyin chatga qaytmay, inPAY sahifasida qoladi.',
           'payment_way_web': 'Saytdagi mijozlar to‘lov usuli', 'payment_way_bot': 'Botdagi mijozlar to‘lov usuli'},
    'ru': {'inpay': 'Автоматическая оплата на сайте (inPAY)', 'inpay_bot': 'Автоматическая оплата в боте (inPAY)',
           'inpay_enabled': 'Разрешить клиентам на сайте онлайн-оплату через inPAY',
           'inpay_bot_enabled': 'Разрешить клиентам в боте онлайн-оплату через inPAY',
           'inpay_bot_hint': 'Клиент в боте выбирает тариф, платит на странице inPAY через Click, Payme, Uzcard или Humo, возвращается в чат, и тариф включается сам. В кабинете inPAY создайте кассу типа «Telegram» для ссылки на бота, указанной выше. В этой кассе укажите Webhook URL — адрес выше, откройте Ключи API v2 и вставьте секретный ключ сюда. Сохраните, нажмите «Проверить соединение», затем отметьте флажок. С тестовым ключом (sk_test_) способ видите только вы (по Telegram ID из раздела «Оплата переводом на карту»), и тестовая оплата ничего не выдаёт; чтобы начать продажи, сохраните боевой ключ. inPAY возвращает деньги только из своего кабинета: верните их там, затем отметьте возврат на странице платежа в разделе «Платежи».',
           'inpay_bot_site': 'Сайт кассы (ссылка на бота)',
           'inpay_bot_webhook_url': 'Адрес вебхука (укажите его как Webhook URL кассы в кабинете inPAY)',
           'inpay_no_bot': 'Имя бота ещё не сохранено: нажмите «Проверить соединение» в разделе Telegram-бота. До тех пор после оплаты клиенты остаются на странице inPAY, а не возвращаются в чат.',
           'payment_way_web': 'Клиенты на сайте платят', 'payment_way_bot': 'Клиенты в боте платят'},
}
for language, labels in INPAY_KASSA_LABELS.items(): LABELS[language].update(labels)
# Saved cards and monthly renewal through inPAY's Avto PAY (apps/commerce/autopay.py).
AUTOPAY_LABELS = {
    'en': {'autopay': 'Saved cards and monthly renewal (Avto PAY)', 'autopay_enabled': 'Let bot customers save a card and renew every month',
           'autopay_audience': 'Who sees it', 'autopay_owner': 'Only me, to try it first', 'autopay_everyone': 'Every customer',
           'autopay_key_id': 'Avto PAY key ID (ap_…)', 'autopay_secret': 'Avto PAY secret', 'autopay_remove': 'Remove the saved Avto PAY key',
           'autopay_test': 'Test Avto PAY',
           'autopay_web_enabled': 'Let website customers save a card and renew every month',
           'autopay_web_hint': 'In the inPAY cabinet open Xizmatlar → Avto PAY → Kalitlar, create a key for the website’s kassa and paste its ID and secret here (the secret is shown once). Website customers save their card on inPAY’s own page and come back to the website; we never see the number. A card saved on the website is charged through this kassa only, and the website charges in one tap only a card saved here. There is no test mode: every charge is real money. Start with «Only me», buy a plan with «Pay and renew every month» on the website signed in as yourself, then switch to «Every customer». The billing page always offers «Remove card», as inPAY requires.',
           'autopay_hint': 'In the inPAY cabinet open Xizmatlar → Avto PAY → Kalitlar, create a key for this kassa and paste its ID and secret here (the secret is shown once). Customers save their card on inPAY’s own page; we never see the number. There is no test mode: every charge is real money. Start with «Only me», buy a plan with «Pay and renew every month» from your own Telegram, then switch to «Every customer». The bot always offers «Remove card», as inPAY requires.',
           'autopay_state_on': 'On', 'autopay_state_off': 'Off', 'autopay_for_owner': 'shown only to you', 'autopay_for_everyone': 'shown to every customer',
           'autopay_stats': '{renewing} customers renew monthly · {cards} saved cards', 'autopay_connected': 'inPAY accepted the Avto PAY key.',
           'invalid_autopay_key': 'Check the Avto PAY key ID (it starts with ap_) and its secret.',
           'autopay_not_configured': 'Save the Avto PAY key ID and secret before switching it on.',
           'autopay_connection_failed': 'inPAY did not accept the Avto PAY key. Check the key ID and secret, and that Avto PAY is approved for this kassa.'},
    'uz': {'autopay': 'Saqlangan kartalar va oylik uzaytirish (Avto PAY)', 'autopay_enabled': 'Botdagi mijozlarga kartani saqlash va har oy uzaytirishga ruxsat berish',
           'autopay_audience': 'Kim ko‘radi', 'autopay_owner': 'Faqat men, avval sinab ko‘rish uchun', 'autopay_everyone': 'Barcha mijozlar',
           'autopay_key_id': 'Avto PAY kalit ID (ap_…)', 'autopay_secret': 'Avto PAY maxfiy kaliti', 'autopay_remove': 'Saqlangan Avto PAY kalitini o‘chirish',
           'autopay_test': 'Avto PAY’ni tekshirish',
           'autopay_web_enabled': 'Saytdagi mijozlarga kartani saqlash va har oy uzaytirishga ruxsat berish',
           'autopay_web_hint': 'inPAY kabinetida Xizmatlar → Avto PAY → Kalitlar bo‘limini oching, sayt kassasi uchun kalit yarating va uning ID hamda maxfiy kalitini shu yerga kiriting (maxfiy kalit bir marta ko‘rsatiladi). Saytdagi mijozlar kartasini inPAY’ning o‘z sahifasida saqlaydi va saytga qaytadi; biz raqamni hech qachon ko‘rmaymiz. Saytda saqlangan karta faqat shu kassa orqali yechiladi, sayt esa bir bosishda faqat shu yerda saqlangan kartadan yechadi. Sinov rejimi yo‘q: har bir yechim haqiqiy pul. «Faqat men» bilan boshlang, saytga o‘zingiz kirib «To‘lash va har oy uzaytirish» bilan tarif sotib oling, so‘ng «Barcha mijozlar»ga o‘tkazing. To‘lovlar sahifasi inPAY talabiga ko‘ra har doim «Kartani uzish» tugmasini ko‘rsatadi.',
           'autopay_hint': 'inPAY kabinetida Xizmatlar → Avto PAY → Kalitlar bo‘limini oching, shu kassa uchun kalit yarating va uning ID hamda maxfiy kalitini shu yerga kiriting (maxfiy kalit bir marta ko‘rsatiladi). Mijozlar kartasini inPAY’ning o‘z sahifasida saqlaydi; biz raqamni hech qachon ko‘rmaymiz. Sinov rejimi yo‘q: har bir yechim haqiqiy pul. «Faqat men» bilan boshlang, o‘z Telegramingizdan «To‘lash va har oy uzaytirish» bilan tarif sotib oling, so‘ng «Barcha mijozlar»ga o‘tkazing. Bot inPAY talabiga ko‘ra har doim «Kartani uzish» tugmasini ko‘rsatadi.',
           'autopay_state_on': 'Yoqilgan', 'autopay_state_off': 'O‘chirilgan', 'autopay_for_owner': 'faqat sizga ko‘rinadi', 'autopay_for_everyone': 'barcha mijozlarga ko‘rinadi',
           'autopay_stats': '{renewing} mijoz har oy uzaytiradi · {cards} ta saqlangan karta', 'autopay_connected': 'inPAY Avto PAY kalitini qabul qildi.',
           'invalid_autopay_key': 'Avto PAY kalit ID (ap_ bilan boshlanadi) va maxfiy kalitini tekshiring.',
           'autopay_not_configured': 'Yoqishdan oldin Avto PAY kalit ID va maxfiy kalitini saqlang.',
           'autopay_connection_failed': 'inPAY Avto PAY kalitini qabul qilmadi. Kalit ID, maxfiy kalit va Avto PAY shu kassa uchun tasdiqlanganini tekshiring.'},
    'ru': {'autopay': 'Сохранённые карты и ежемесячное продление (Avto PAY)', 'autopay_enabled': 'Разрешить клиентам в боте сохранять карту и продлевать каждый месяц',
           'autopay_audience': 'Кто видит', 'autopay_owner': 'Только я, чтобы сначала проверить', 'autopay_everyone': 'Все клиенты',
           'autopay_key_id': 'ID ключа Avto PAY (ap_…)', 'autopay_secret': 'Секрет Avto PAY', 'autopay_remove': 'Удалить сохранённый ключ Avto PAY',
           'autopay_test': 'Проверить Avto PAY',
           'autopay_web_enabled': 'Разрешить клиентам на сайте сохранять карту и продлевать каждый месяц',
           'autopay_web_hint': 'В кабинете inPAY откройте Xizmatlar → Avto PAY → Kalitlar, создайте ключ для кассы сайта и вставьте сюда его ID и секрет (секрет показывается один раз). Клиенты на сайте сохраняют карту на собственной странице inPAY и возвращаются на сайт; номер карты мы никогда не видим. Карта, сохранённая на сайте, списывается только через эту кассу, а сайт в одно нажатие списывает только с карты, сохранённой здесь. Тестового режима нет: каждое списание — реальные деньги. Начните с «Только я», купите тариф с «Оплатить и продлевать каждый месяц» на сайте под своим аккаунтом, затем переключите на «Все клиенты». Страница оплаты всегда показывает «Отвязать карту», как требует inPAY.',
           'autopay_hint': 'В кабинете inPAY откройте Xizmatlar → Avto PAY → Kalitlar, создайте ключ для этой кассы и вставьте сюда его ID и секрет (секрет показывается один раз). Клиенты сохраняют карту на собственной странице inPAY; номер карты мы никогда не видим. Тестового режима нет: каждое списание — реальные деньги. Начните с «Только я», купите тариф с «Оплатить и продлевать каждый месяц» из своего Telegram, затем переключите на «Все клиенты». Бот всегда показывает «Отвязать карту», как требует inPAY.',
           'autopay_state_on': 'Включено', 'autopay_state_off': 'Выключено', 'autopay_for_owner': 'видно только вам', 'autopay_for_everyone': 'видно всем клиентам',
           'autopay_stats': 'Продлевают каждый месяц: {renewing} · сохранённых карт: {cards}', 'autopay_connected': 'inPAY принял ключ Avto PAY.',
           'invalid_autopay_key': 'Проверьте ID ключа Avto PAY (начинается с ap_) и его секрет.',
           'autopay_not_configured': 'Сохраните ID ключа и секрет Avto PAY, прежде чем включать.',
           'autopay_connection_failed': 'inPAY не принял ключ Avto PAY. Проверьте ID ключа, секрет и что Avto PAY одобрен для этой кассы.'},
}
for language, labels in AUTOPAY_LABELS.items(): LABELS[language].update(labels)
CHANNEL_SECTION_LABELS = {
    'en': {'bot_not_configured': 'Set the Telegram bot token above first.', 'channels': 'Required Telegram channels', 'channels_enabled': 'Free and Plus customers must join these channels to use the services',
           'channels_list': 'Channels, one per line',
           'channels_hint': 'Write @name or https://t.me/name for a public channel. For a private channel or group, write its invite link and its numeric chat ID on one line, e.g. https://t.me/+AbCdEf123 -1001234567890. Add the bot as an administrator of each channel (or a member of each group), then press Check. Premium customers are never asked. If Telegram cannot be reached, customers are let through rather than locked out.',
           'channels_connected': 'The bot can see who has joined every channel.',
           'channel_ok': 'bot can check members', 'channel_bot_not_admin': 'make the bot an administrator', 'channel_chat_not_found': 'not found — check the link or ID', 'channel_unchecked': 'not checked yet',
           'invalid_channel': 'A line is not a channel: use @name, a t.me link, or an invite link with its numeric chat ID.',
           'too_many_channels': 'Add at most 5 channels.', 'channels_not_configured': 'Add at least one channel before switching this on.',
           'channels_bot_not_admin': 'The bot cannot see the members of some channels. Make it an administrator there, then Check again.'},
    'uz': {'bot_not_configured': 'Avval yuqorida Telegram bot tokenini kiriting.', 'channels': 'Majburiy Telegram kanallar', 'channels_enabled': 'Bepul va Plus tarifidagi mijozlar xizmatlardan foydalanish uchun shu kanallarga qo‘shilishi kerak',
           'channels_list': 'Kanallar, har biri alohida qatorda',
           'channels_hint': 'Ochiq kanal uchun @nom yoki https://t.me/nom yozing. Yopiq kanal yoki guruh uchun bir qatorda taklif havolasi va raqamli chat ID ni yozing, masalan https://t.me/+AbCdEf123 -1001234567890. Botni har bir kanalga administrator (guruhga a’zo) qilib qo‘shing, so‘ng «Tekshirish»ni bosing. Premium tarifidagi mijozlardan so‘ralmaydi. Telegram javob bermasa, mijozlar to‘xtatilmaydi.',
           'channels_connected': 'Bot barcha kanallarda kim qo‘shilganini ko‘ra oladi.',
           'channel_ok': 'bot a’zolarni tekshira oladi', 'channel_bot_not_admin': 'botni administrator qiling', 'channel_chat_not_found': 'topilmadi — havola yoki ID ni tekshiring', 'channel_unchecked': 'hali tekshirilmagan',
           'invalid_channel': 'Qatordagi qiymat kanal emas: @nom, t.me havola yoki raqamli chat ID bilan taklif havolasini yozing.',
           'too_many_channels': 'Ko‘pi bilan 5 ta kanal qo‘shing.', 'channels_not_configured': 'Yoqishdan oldin kamida bitta kanal qo‘shing.',
           'channels_bot_not_admin': 'Bot ba’zi kanallar a’zolarini ko‘ra olmaydi. Uni u yerda administrator qiling va qayta tekshiring.'},
    'ru': {'bot_not_configured': 'Сначала укажите токен Telegram-бота выше.', 'channels': 'Обязательные Telegram-каналы', 'channels_enabled': 'Клиенты на тарифах Free и Plus должны подписаться на эти каналы, чтобы пользоваться сервисами',
           'channels_list': 'Каналы, по одному в строке',
           'channels_hint': 'Для открытого канала напишите @имя или https://t.me/имя. Для закрытого канала или группы — ссылку-приглашение и числовой ID чата в одной строке, например https://t.me/+AbCdEf123 -1001234567890. Добавьте бота администратором каждого канала (или участником группы) и нажмите «Проверить». Клиентов на Premium это не касается. Если Telegram недоступен, клиентов пропускают, а не блокируют.',
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
CONTACT_LABELS = {
    'en': {'contacts': 'Contacts & support', 'contacts_intro': 'The Telegram accounts the bot and the web app point people to. Leave one empty to hide it.',
           'contact_support': 'Support account', 'contact_ads': 'Advertising and partnerships account',
           'contact_hint': '@username, username or a t.me link', 'contacts_none': 'Not set',
           'invalid_contact_username': 'That is not a Telegram username: 5–32 letters, digits or underscores, starting with a letter.'},
    'uz': {'contacts': 'Aloqa va yordam', 'contacts_intro': 'Bot va veb ilova odamlarni yo‘naltiradigan Telegram hisoblari. Ko‘rsatmaslik uchun bo‘sh qoldiring.',
           'contact_support': 'Yordam hisobi', 'contact_ads': 'Reklama va hamkorlik hisobi',
           'contact_hint': '@username, username yoki t.me havolasi', 'contacts_none': 'Belgilanmagan',
           'invalid_contact_username': 'Bu Telegram username emas: harf bilan boshlanadigan 5–32 ta harf, raqam yoki pastki chiziq.'},
    'ru': {'contacts': 'Контакты и поддержка', 'contacts_intro': 'Telegram-аккаунты, на которые бот и сайт направляют людей. Оставьте пустым, чтобы скрыть.',
           'contact_support': 'Аккаунт поддержки', 'contact_ads': 'Аккаунт по рекламе и сотрудничеству',
           'contact_hint': '@username, username или ссылка t.me', 'contacts_none': 'Не задан',
           'invalid_contact_username': 'Это не имя пользователя Telegram: 5–32 буквы, цифры или подчёркивания, начиная с буквы.'},
}
for language, labels in CONTACT_LABELS.items(): LABELS[language].update(labels)
# The company's legal details, shown at the end of the web Help page and the bot's About the bot.
COMPANY_LABELS = {
    'en': {'company': 'Company details', 'company_intro': 'Payment providers require these on the site and in the bot (About the bot). An empty name, number or address shows the registration certificate’s; an empty phone or email is hidden.',
           'company_name': 'Legal name', 'company_tin': 'Taxpayer number (STIR)', 'company_address': 'Legal address',
           'company_phone': 'Phone', 'company_email': 'Email',
           'invalid_company_tin': 'A STIR has 9 digits.', 'invalid_company_phone': 'That is not a phone number, for example +998 90 123 45 67.',
           'invalid_company_email': 'That is not an email address.'},
    'uz': {'company': 'Rekvizitlar', 'company_intro': 'To‘lov tizimlari ularni sayt va botda («Bot haqida») talab qiladi. Bo‘sh nom, raqam yoki manzil o‘rniga guvohnomadagisi ko‘rsatiladi; bo‘sh telefon yoki pochta ko‘rsatilmaydi.',
           'company_name': 'Yuridik nomi', 'company_tin': 'STIR (INN)', 'company_address': 'Yuridik manzil',
           'company_phone': 'Telefon', 'company_email': 'Elektron pochta',
           'invalid_company_tin': 'STIR 9 ta raqamdan iborat.', 'invalid_company_phone': 'Bu telefon raqami emas, masalan +998 90 123 45 67.',
           'invalid_company_email': 'Bu elektron pochta manzili emas.'},
    'ru': {'company': 'Реквизиты', 'company_intro': 'Платёжные системы требуют их на сайте и в боте («О боте»). Вместо пустого названия, номера или адреса показываются данные из свидетельства; пустые телефон и почта скрыты.',
           'company_name': 'Юридическое название', 'company_tin': 'ИНН (STIR)', 'company_address': 'Юридический адрес',
           'company_phone': 'Телефон', 'company_email': 'Эл. почта',
           'invalid_company_tin': 'ИНН состоит из 9 цифр.', 'invalid_company_phone': 'Это не номер телефона, например +998 90 123 45 67.',
           'invalid_company_email': 'Это не адрес электронной почты.'},
}
for language, labels in COMPANY_LABELS.items(): LABELS[language].update(labels)


def _autopay_stats(labels, kassa):
    """Customers renewing from cards saved through this kassa, and its saved cards."""
    from apps.commerce.models import AutoRenewal, SavedCard
    return labels['autopay_stats'].format(renewing=AutoRenewal.objects.filter(status='on', card__kassa=kassa).count(),
                                          cards=SavedCard.objects.filter(status='active', kassa=kassa).count())


@require_staff()
@sensitive_post_parameters('token','api_key','client_secret','password','secret_key','pixabay_key','access_key','webhook_secret','merchant_token','autopay_secret')
@require_http_methods(['GET','POST'])
def integrations(request):
    data=context(request,'integrations');labels=LABELS[data['lang']];data['i']=labels;data['title']=labels['integrations']
    if request.method=='POST':
        action=request.POST.get('action','save')
        try:
            key=request.POST.get('integration','telegram')
            if action!='save' and key!='telegram' and not (key in ('email','pixabay','channels','object_storage','inpay','inpay_bot') and action=='test') \
                    and not (key in ('inpay','inpay_bot') and action=='test_autopay'):raise DomainError('invalid_parameters')
            if action=='save':
                before=menu_button() if key=='telegram' else None
                save_config(key,request.POST);message='saved'
                # Every chat's menu button follows a new web app address at once, and the bot sets it again when it starts.
                if key=='telegram' and menu_button()!=before and not apply_menu_button():message='menu_pending'
            elif action=='test_autopay':test_autopay('bot' if key=='inpay_bot' else 'web');message='autopay_connected'
            elif action=='test':
                if key=='email':test_email();message='email_connected'
                elif key=='pixabay':test_pixabay();message='pixabay_connected'
                elif key=='object_storage':test_object_storage();message='storage_connected'
                elif key=='channels':test_channels();message='channels_connected'
                elif key in ('inpay','inpay_bot'):test_inpay('bot' if key=='inpay_bot' else 'web');message='inpay_connected'
                else:test_telegram();message='connected'
            elif action in ('start','stop'):
                if not development_access(request):raise DomainError('local_control_only',403)
                control_runner(action);message='action_done'
            else:raise DomainError('invalid_parameters')
            after={'configured':True}
            # Who changed the card customers pay into, and to which one, must be traceable.
            if key=='manual_payments':
                card=manual_payment_config();after.update(card_last4=card['card_number'][-4:],enabled=card['enabled'])
            # Which kind of key takes customers' money, and whether it is switched on; never any part of the key.
            if key in ('inpay','inpay_bot'):
                pay=inpay_config('bot' if key=='inpay_bot' else 'web');after.update(api=pay['api'],live=pay['live'],enabled=pay['enabled'])
                # Who may have their card charged without a code, and whether it is on; never the key.
                after.update(autopay=pay['autopay_enabled'],autopay_audience=pay['autopay_audience'],autopay_key=bool(pay['autopay_configured']))
            audit(request.ops_user,'integration.'+action,key,after=after)
            return redirect('/ops/integrations?lang='+data['lang']+'&notice='+message)
        except DomainError as e:
            data['error']=labels.get(e.code,labels['failure']);data['error_code']=e.code
            # What inPAY itself answered tells a wrong key from an inactive kassa or a spent limit.
            if e.params.get('inpay'):data['error_code']+=' · inPAY: '+e.params['inpay']
            # The card the problem belongs to stays open, with what was typed.
            data['open_integration']=request.POST.get('integration','telegram')
    bot=telegram_config();ai=ai_config();google=google_config();email=email_config();antibot=antibot_config()
    from .integrations import company_details, contacts_config
    data['contacts']=contacts_config();data['company']=company_details()
    local_controls=development_access(request)
    # A container-managed bot has a different PID namespace from the API.
    # Do not misreport it as stopped using the local development PID check.
    status=labels[runner_status()] if local_controls else labels['managed' if bot['token'] else 'waiting']
    # Never include credentials in the template context.
    data.update(bot={'username':bot['username'],'webapp_url':bot['webapp_url'],'configured':bool(bot['token']),'status':status},ai={'mode':ai['mode'],'model':ai['model'],'image_model':ai['image_model'],'configured':bool(ai['api_key']),'writing_effort':ai['writing_effort'],'photo_effort':ai['photo_effort'],'service_tier':ai['service_tier'],'parallel_parts':ai['parallel_parts']},efforts=EFFORTS,tiers=TIERS,local_controls=local_controls,notice=labels.get(request.GET.get('notice',''),''))
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
    # The keys never reach the page: only which API they speak, their mode, and whether a signing secret is saved.
    # One card per kassa, the bot's first: each place customers pay has its own.
    from apps.core.links import web_origin
    from apps.commerce.checkout import payment_way
    site=web_origin();username=str(bot['username'] or '').strip().lstrip('@')
    webhook=site+'/api/v1/webhooks/inpay' if site else ''
    data['kassas']=[]
    for kassa,key in (('bot','inpay_bot'),('web','inpay')):
        pay=inpay_config(kassa)
        bot_kassa=kassa=='bot'
        data['kassas'].append({**{name: pay[name] for name in ('enabled','configured','ready','live','api','merchant_id')},
            'key':key,'kassa':kassa,'card_id':'inpay-bot-settings' if bot_kassa else 'inpay-settings',
            'title':labels[key],'enabled_label':labels[key+'_enabled'],'hint':labels['inpay_bot_hint' if bot_kassa else 'inpay_hint'],
            'site_label':labels['inpay_bot_site' if bot_kassa else 'inpay_site'],
            'site':(f'https://t.me/{username}' if username else '') if bot_kassa else site,
            'webhook_label':labels['inpay_bot_webhook_url' if bot_kassa else 'inpay_webhook_url'],'webhook_url':webhook,
            'missing':labels['inpay_no_bot'] if bot_kassa and not username else labels['inpay_no_site'] if not bot_kassa and not site else '',
            'signed':bool(pay['webhook_secret']),'priced':bool(card_prices()),'owner_known':bool(card['alert_telegram_id']),
            # Customers are offered one way at a time in each place; the cards say which it is now.
            'way':payment_way(kassa),'way_label':labels['payment_way_'+kassa],
            # Avto PAY, each kassa its own: the key's id is shown, its secret never.
            'autopay':True,'autopay_enabled':pay['autopay_enabled'],'autopay_configured':pay['autopay_configured'],
            'autopay_key_id':pay['autopay_key_id'],'autopay_audience':pay['autopay_audience'],
            'autopay_enabled_label':labels['autopay_enabled' if bot_kassa else 'autopay_web_enabled'],
            'autopay_hint':labels['autopay_hint' if bot_kassa else 'autopay_web_hint'],
            'autopay_stats':_autopay_stats(labels,kassa)})
    return finish_render(request,'ops/integrations.html',data)
