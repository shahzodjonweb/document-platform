from django.conf import settings
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from apps.core.errors import DomainError
from .auth import require_staff,audit,development_access
from .views import context,finish_render
from .integrations import telegram_config,ai_config,google_config,email_config,antibot_config,pixabay_config,save_config,test_telegram,test_email,test_pixabay,control_runner,runner_status
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

@require_staff()
@sensitive_post_parameters('token','api_key','client_secret','password','secret_key','pixabay_key')
@require_http_methods(['GET','POST'])
def integrations(request):
    data=context(request,'integrations');labels=LABELS[data['lang']];data['i']=labels;data['title']=labels['integrations']
    if request.method=='POST':
        action=request.POST.get('action','save');reason=request.POST.get('reason','').strip()
        if not 5<=len(reason)<=1000:data['error']=labels['need_reason']
        else:
            try:
                key=request.POST.get('integration','telegram')
                if action!='save' and key!='telegram' and not (key in ('email','pixabay') and action=='test'):raise DomainError('invalid_parameters')
                if action=='save':save_config(key,request.POST);message='saved'
                elif action=='test':
                    if key=='email':test_email();message='email_connected'
                    elif key=='pixabay':test_pixabay();message='pixabay_connected'
                    else:test_telegram();message='connected'
                elif action in ('start','stop'):
                    if not development_access(request):raise DomainError('local_control_only',403)
                    control_runner(action);message='action_done'
                else:raise DomainError('invalid_parameters')
                audit(request.ops_user,'integration.'+action,key,reason,after={'configured':True})
                return redirect('/ops/integrations?lang='+data['lang']+'&notice='+message)
            except DomainError as e:
                data['error']=labels.get(e.code,labels['failure']);data['error_code']=e.code
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
    return finish_render(request,'ops/integrations.html',data)
