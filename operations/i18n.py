"""Small explicit catalogs for the implemented operations surface."""
EN = {
'brand':'PDF Master','workspace':'Operations workspace','overview':'Overview','users':'Users','acquisition':'Acquisition','engagement':'Engagement','features':'Feature performance','revenue':'Revenue','jobs':'Processing jobs','plans':'Plans & limits','payments':'Payments','support':'Support inbox','audit':'Audit trail','system':'System health','localization':'Localization','analytics':'ANALYTICS','manage':'MANAGE','platform':'PLATFORM','signout':'Sign out','language':'Language','skip':'Skip to content','search':'Search by account or task ID','overview_title':'A clear view of your workspace.','overview_desc':'People, documents, and service health — from your actual platform activity.','date_from':'From','date_to':'Before (exclusive)','timezone':'Report timezone','channel':'Channel','locale':'Account language','environment':'Environment','production':'Production','development':'Development / test','all':'All','apply':'Apply filters','export':'Export CSV','definitions':'Metric definitions v1.0','updated':'Updated','new_users':'New users','active_users':'Active task users','completed':'Successful tasks','success_rate':'Task success rate','failed':'Failed tasks','queued':'In progress','activated':'Activated within 7 days','not_observable':'Not yet observable','unavailable':'Unavailable','new_users_chart':'New accounts over time','activity':'Recent processing activity','activity_desc':'Task metadata only. Document contents stay private.','view_all':'View all','no_data':'No activity in this period','no_data_desc':'Records will appear here as people use the platform. Check your environment and date filters.','task':'Task','feature':'Tool','account':'Account','status':'Status','created':'Created','duration':'Duration','plan':'Plan','source':'Registration channel','id':'ID','name':'Display name','rows':'records','previous':'Previous','next':'Next','user_desc':'Canonical Telegram-linked accounts. Repeat sessions do not create new registrations.','job_desc':'Inspect task state and charge transitions without opening private files.','acquisition_desc':'Verified registration facts, grouped using the report timezone.','engagement_desc':'Meaningful task activity and mature signup cohorts. Passive page views are excluded.','feature_desc':'Real attempts and outcomes, grouped by tool. Canceled and no-op tasks are excluded from success rates.','revenue_desc':'Payment reporting requires an authoritative confirmed-payment ledger.','financial_gate':'Payments are not enabled','financial_gate_desc':'Production Stars prices are unset. Checkout and financial reports stay unavailable until payment integration and launch verification pass.','staging':'Draft staging configuration','plans_desc':'Server-owned limits. Edits here apply immediately to everyone on the plan and are recorded in the audit trail.','tasks':'Tasks / 30 days','pages':'Page units / 30 days','credits':'AI credits / 30 days','file_limit':'File limit','page_limit':'Pages / task','concurrency':'Concurrent tasks','price':'Stars price','not_set':'Not configured','free':'Free','support_desc':'Requests from customers. Status changes are recorded in the audit trail.','subject':'Subject','category':'Category','message':'Message','reason':'Reason for change','resolve':'Resolve case','reopen':'Reopen case','open':'Open','resolved':'Resolved','saved':'Change saved and audited.','reason_required':'Provide a reason between 5 and 1000 characters.','audit_desc':'An append-only record of staff actions and identifiable data exports.','actor':'Staff actor','action':'Action','target':'Target','system_desc':'Live database diagnostics. Worker or provider connectivity is not inferred from queue counts.','stored_files':'Retained file records','storage':'Stored bytes','expired_pending':'Expired files awaiting cleanup','outbox_pending':'Pending job events','cleanup_note':'Run the documented cleanup command on a regular schedule. Expired assets are inaccessible before physical deletion.','worker_note':'Worker heartbeat monitoring: not configured. Queue counts are measured database state.','login_title':'Your operations workspace.','login_desc':'Sign in with your staff username and password. Customer sign-in cannot access this workspace.','username':'Staff username','password':'Password','code':'Authenticator code','signin':'Sign in securely','dev_login':'Open local staff workspace','dev_note':'Local development only. Uses a separate staff session and shows real local records.','invalid_login':'Sign-in failed. Check your username and password.','rate_limit':'Too many attempts. Try again in 15 minutes.','local_only':'This action is available only in explicit local development.','private':'Private by default','staff':'Staff','retention':'Retention','expires':'Expires','total':'Total','attempts':'Attempts','succeeded':'Succeeded','canceled':'Canceled','no_op':'No reduction','running':'Processing','pending':'Pending','ready':'Ready','failed_status':'Failed','queued_status':'Queued','success_definition':'Succeeded / (succeeded + failed) in the selected task cohort. No-ops and cancellations are excluded.','new_definition':'Distinct canonical accounts created in the selected time window. Test data is excluded in Production.','active_definition':'Distinct accounts with an accepted task in the selected window.','completed_definition':'Succeeded atomic jobs created in the selected time window.','back':'Back','profile':'Account profile','allowance':'Allowance ledger','meter':'Meter','amount':'Amount','kind':'Transition','private_note':'Staff can open documents on this account. Every download is audited.','current_plan':'Assigned plan (not a paid-subscriber metric)','latency':'Processing latency','median':'Median','p95':'95th percentile','locale_desc':'Translation key coverage for the operations interface. Automated parity is not professional language-review signoff.','keys':'Keys','coverage':'Key coverage','review':'Language review','pending_review':'Pending human review','report_table':'Chart data table','notice_test':'You are viewing development/test records. They are excluded from production reports.','overview_short':'Your workspace at a glance','gated':'Release gated','feature_catalog':'Feature catalog','implemented':'Local capability','not_released':'Not released','quote':'Quote','engine':'Engine','error':'Error code','consumed':'Consumed','reserved':'Reserved','remaining':'Remaining','grant':'Grant','support_detail':'Support case','permissions':'Permissions','no_private':'Opening a customer document is recorded in the audit trail.','updated_definition':'Computed at request time from transactional database records.','assign_plan':'Assign a plan','assign_plan_note':'Not a payment: this never appears in revenue, and any paid subscription stays underneath and returns when the assignment ends.','assigned_by_staff':'Assigned by staff','paid_plan':'Paid subscription','plan_duration':'Days (blank = until removed)','clear_plan':'Remove assignment','effective_limits':'Limits in force','balance':'Remaining now','after_grant':'After this grant','quick_amounts':'Quick amounts','grant_pairing':'Tasks need page units to be usable, so add both.','files':'Documents','files_desc':'Every download is recorded in the audit trail.','file_name':'File','size':'Size','open_file':'Open','file_reason':'Reason for opening this document','no_files':'This account has no stored documents.','edit_plan':'Edit limits','plan_edit_note':'Applies to everyone on this plan, immediately and without a deploy.','seed_value':'Default','reset_plan':'Restore defaults','edited':'Changed','save_changes':'Save changes','no_limit':'No limit'}
RU_VALUES = {
'workspace':'Рабочее пространство','overview':'Обзор','users':'Пользователи','acquisition':'Привлечение','engagement':'Активность','features':'Использование функций','revenue':'Доходы','jobs':'Обработка файлов','plans':'Тарифы и лимиты','payments':'Платежи','support':'Обращения','audit':'Журнал действий','system':'Состояние системы','localization':'Локализация','analytics':'АНАЛИТИКА','manage':'УПРАВЛЕНИЕ','platform':'ПЛАТФОРМА','signout':'Выйти','language':'Язык','skip':'К содержимому','search':'Поиск по ID','overview_title':'Всё о работе вашей платформы.','overview_desc':'Пользователи, документы и состояние сервиса — на основе реальных данных.','date_from':'С даты','date_to':'До даты (не включая)','timezone':'Часовой пояс отчёта','channel':'Канал','locale':'Язык пользователя','environment':'Среда','production':'Рабочая','development':'Разработка / тест','all':'Все','apply':'Применить','export':'Экспорт CSV','definitions':'Определения метрик v1.0','updated':'Обновлено','new_users':'Новые пользователи','active_users':'Активные пользователи','completed':'Успешные задачи','success_rate':'Доля успешных задач','failed':'Ошибки','queued':'В обработке','activated':'Активация за 7 дней','not_observable':'Ещё не наблюдаемо','unavailable':'Недоступно','new_users_chart':'Новые аккаунты по дням','activity':'Последние задачи','activity_desc':'Только метаданные. Содержимое документов остаётся приватным.','view_all':'Показать все','no_data':'Нет данных за этот период','no_data_desc':'Записи появятся при использовании платформы. Проверьте среду и период.','task':'Задача','feature':'Инструмент','account':'Аккаунт','status':'Статус','created':'Создано','duration':'Длительность','plan':'Тариф','source':'Канал регистрации','name':'Имя','rows':'записей','previous':'Назад','next':'Далее','user_desc':'Единые аккаунты Telegram. Повторные сеансы не считаются регистрацией.','job_desc':'Состояние задач и списаний без доступа к приватным файлам.','acquisition_desc':'Подтверждённые регистрации в часовом поясе отчёта.','engagement_desc':'Активность по задачам и зрелые когорты. Просмотры страниц исключены.','feature_desc':'Попытки и результаты по инструментам. Отмены и задачи без изменений исключены из доли успеха.','revenue_desc':'Финансовые отчёты требуют подтверждённого платёжного реестра.','financial_gate':'Платежи не включены','financial_gate_desc':'Цены в Stars не заданы. Оплата и финансовые отчёты недоступны до проверки интеграции.','staging':'Черновая тестовая конфигурация','plans_desc':'Серверные лимиты. Изменения применяются сразу ко всем на тарифе и записываются в журнал.','tasks':'Задач за 30 дней','pages':'Единиц страниц за 30 дней','credits':'ИИ-кредитов за 30 дней','file_limit':'Размер файла','page_limit':'Страниц на задачу','concurrency':'Параллельные задачи','price':'Цена в Stars','not_set':'Не настроено','support_desc':'Обращения пользователей. Изменения статуса записываются в журнал.','subject':'Тема','category':'Категория','message':'Сообщение','reason':'Причина изменения','resolve':'Закрыть обращение','reopen':'Открыть повторно','open':'Открыто','resolved':'Закрыто','saved':'Изменение сохранено в журнале.','reason_required':'Укажите причину: от 5 до 1000 символов.','audit_desc':'Неизменяемый журнал действий сотрудников и экспорта персональных данных.','actor':'Сотрудник','action':'Действие','target':'Объект','system_desc':'Диагностика базы данных. Число задач не подтверждает доступность обработчиков.','stored_files':'Сохранённые файлы','storage':'Объём в байтах','expired_pending':'Ожидают удаления','outbox_pending':'Неотправленные события','cleanup_note':'Регулярно запускайте очистку. Истёкшие файлы недоступны до физического удаления.','worker_note':'Мониторинг обработчиков не настроен. Очередь отражает данные базы.','login_title':'Панель управления.','login_desc':'Войдите с логином и паролем сотрудника. Вход клиента не даёт доступа.','username':'Логин сотрудника','password':'Пароль','code':'Код аутентификатора','signin':'Войти','dev_login':'Открыть локальную панель','dev_note':'Только для локальной разработки. Отдельный сеанс и реальные локальные данные.','invalid_login':'Не удалось войти. Проверьте логин и пароль.','rate_limit':'Слишком много попыток. Повторите через 15 минут.','local_only':'Доступно только в режиме локальной разработки.','private':'Приватность по умолчанию','staff':'Сотрудник','retention':'Хранение','expires':'Срок хранения','total':'Всего','attempts':'Попытки','succeeded':'Успешно','canceled':'Отменено','no_op':'Без уменьшения','running':'Обработка','pending':'Ожидание','ready':'Готово','failed_status':'Ошибка','queued_status':'В очереди','success_definition':'Успешные / (успешные + ошибки) среди выбранных задач. Отмены исключены.','new_definition':'Уникальные аккаунты, созданные за период. Тестовые данные исключены из рабочей среды.','active_definition':'Уникальные аккаунты с принятой задачей за период.','completed_definition':'Успешные отдельные задачи, созданные за период.','back':'Назад','profile':'Профиль аккаунта','allowance':'Журнал использования','meter':'Ресурс','amount':'Количество','kind':'Операция','private_note':'Сотрудник может открывать документы этого аккаунта. Каждое скачивание фиксируется.','current_plan':'Назначенный тариф (не показатель платных подписок)','latency':'Время обработки','median':'Медиана','p95':'95-й процентиль','locale_desc':'Полнота ключей интерфейса. Автоматическая проверка не заменяет языковую редактуру.','keys':'Ключи','coverage':'Полнота ключей','review':'Проверка языка','pending_review':'Ожидает проверки','report_table':'Таблица данных графика','notice_test':'Показаны тестовые записи. Они исключены из рабочих отчётов.','overview_short':'Главное о платформе','gated':'Выпуск заблокирован','feature_catalog':'Каталог функций','implemented':'Локальная возможность','not_released':'Не выпущено','quote':'Расчёт','engine':'Обработчик','error':'Код ошибки','consumed':'Использовано','reserved':'Зарезервировано','remaining':'Осталось','grant':'Начисление','support_detail':'Обращение','permissions':'Права доступа','no_private':'Открытие документа клиента записывается в журнал аудита.','updated_definition':'Вычислено по актуальным данным базы при запросе.','assign_plan':'Назначить тариф','assign_plan_note':'Это не платёж: в доходы не попадает, а платная подписка сохраняется и вернётся после окончания назначения.','assigned_by_staff':'Назначено сотрудником','paid_plan':'Платная подписка','plan_duration':'Дней (пусто = до отмены)','clear_plan':'Убрать назначение','effective_limits':'Действующие лимиты','balance':'Остаток сейчас','after_grant':'После начисления','quick_amounts':'Быстрый выбор','grant_pairing':'Чтобы задачи работали, нужны и единицы страниц — добавьте оба.','files':'Документы','files_desc':'Каждое скачивание записывается в журнал.','file_name':'Файл','size':'Размер','open_file':'Открыть','file_reason':'Причина открытия документа','no_files':'В этом аккаунте нет сохранённых документов.','edit_plan':'Изменить лимиты','plan_edit_note':'Применяется ко всем на этом тарифе сразу, без развёртывания.','seed_value':'По умолчанию','reset_plan':'Вернуть стандартные','edited':'Изменён','save_changes':'Сохранить изменения','no_limit':'Без лимита'}
UZ_VALUES = {
'workspace':'Boshqaruv maydoni','overview':'Umumiy ko‘rinish','users':'Foydalanuvchilar','acquisition':'Yangi foydalanuvchilar','engagement':'Faollik','features':'Vositalar samaradorligi','revenue':'Daromad','jobs':'Fayl vazifalari','plans':'Tariflar va limitlar','payments':'To‘lovlar','support':'Yordam so‘rovlari','audit':'Amallar jurnali','system':'Tizim holati','localization':'Tillar','analytics':'TAHLIL','manage':'BOSHQARUV','platform':'PLATFORMA','signout':'Chiqish','language':'Til','skip':'Asosiy qismga o‘tish','search':'Hisob yoki vazifa ID bo‘yicha qidirish','overview_title':'Platformangiz haqida aniq ma’lumot.','overview_desc':'Foydalanuvchilar, hujjatlar va xizmat holati — haqiqiy ma’lumotlar asosida.','date_from':'Boshlanish','date_to':'Tugash (kiritilmaydi)','timezone':'Hisobot vaqt mintaqasi','channel':'Kanal','locale':'Foydalanuvchi tili','environment':'Muhit','production':'Ishchi muhit','development':'Dasturlash / sinov','all':'Barchasi','apply':'Qo‘llash','export':'CSV yuklab olish','definitions':'Ko‘rsatkich ta’riflari v1.0','updated':'Yangilangan','new_users':'Yangi foydalanuvchilar','active_users':'Faol foydalanuvchilar','completed':'Muvaffaqiyatli vazifalar','success_rate':'Muvaffaqiyat ulushi','failed':'Xatolar','queued':'Jarayonda','activated':'7 kun ichida faollashgan','not_observable':'Hali kuzatib bo‘lmaydi','unavailable':'Mavjud emas','new_users_chart':'Kunlar bo‘yicha yangi hisoblar','activity':'So‘nggi vazifalar','activity_desc':'Faqat metama’lumot. Hujjat mazmuni maxfiy qoladi.','view_all':'Barchasini ko‘rish','no_data':'Bu davrda faollik yo‘q','no_data_desc':'Platforma ishlatilganda yozuvlar paydo bo‘ladi. Muhit va davrni tekshiring.','task':'Vazifa','feature':'Vosita','account':'Hisob','status':'Holat','created':'Yaratilgan','duration':'Davomiylik','plan':'Tarif','source':'Ro‘yxatdan o‘tish kanali','name':'Ko‘rinadigan ism','rows':'yozuv','previous':'Oldingi','next':'Keyingi','user_desc':'Telegram bilan bog‘langan yagona hisoblar. Qayta kirish yangi ro‘yxatdan o‘tish hisoblanmaydi.','job_desc':'Maxfiy fayllarni ochmasdan vazifa holati va sarfni tekshiring.','acquisition_desc':'Tasdiqlangan ro‘yxatdan o‘tishlar hisobot vaqt mintaqasida.','engagement_desc':'Vazifa faolligi va yetilgan guruhlar. Sahifa ko‘rishlar hisobga olinmaydi.','feature_desc':'Vositalar bo‘yicha haqiqiy urinish va natijalar. Bekor qilingan vazifalar muvaffaqiyat ulushiga kirmaydi.','revenue_desc':'Moliyaviy hisobotlar uchun tasdiqlangan to‘lovlar jurnali zarur.','financial_gate':'To‘lovlar yoqilmagan','financial_gate_desc':'Stars narxlari belgilanmagan. Integratsiya tekshirilguncha to‘lov va moliyaviy hisobotlar yopiq.','staging':'Sinov uchun qoralama sozlamalar','plans_desc':'Server limitlari. Bu yerdagi o‘zgarish tarifdagi barchaga darhol qo‘llanadi va jurnalga yoziladi.','tasks':'30 kundagi vazifalar','pages':'30 kundagi sahifa birliklari','credits':'30 kundagi AI kreditlari','file_limit':'Fayl hajmi','page_limit':'Vazifadagi sahifalar','concurrency':'Bir vaqtdagi vazifalar','price':'Stars narxi','not_set':'Sozlanmagan','support_desc':'Foydalanuvchi so‘rovlari. Holat o‘zgarishi jurnalga yoziladi.','subject':'Mavzu','category':'Toifa','message':'Xabar','reason':'O‘zgarish sababi','resolve':'So‘rovni yopish','reopen':'Qayta ochish','open':'Ochiq','resolved':'Yopilgan','saved':'O‘zgarish saqlandi va jurnalga yozildi.','reason_required':'5 dan 1000 belgigacha sabab kiriting.','audit_desc':'Xodim amallari va shaxsiy ma’lumot eksportining o‘zgarmas jurnali.','actor':'Xodim','action':'Amal','target':'Obyekt','system_desc':'Ma’lumotlar bazasi diagnostikasi. Navbat soni ishlovchi xizmat holatini bildirmaydi.','stored_files':'Saqlangan fayllar','storage':'Baytlardagi hajm','expired_pending':'O‘chirishni kutayotgan fayllar','outbox_pending':'Kutilayotgan hodisalar','cleanup_note':'Tozalash buyrug‘ini muntazam bajaring. Muddati tugagan fayllar o‘chirilishdan oldin ham ochilmaydi.','worker_note':'Ishlovchi xizmat monitoringi sozlanmagan. Navbat bazadagi haqiqiy holatdir.','login_title':'Boshqaruv maydoningiz.','login_desc':'Xodim logini va paroli bilan kiring. Mijoz hisobi bu maydonga kira olmaydi.','username':'Xodim logini','password':'Parol','code':'Autentifikator kodi','signin':'Xavfsiz kirish','dev_login':'Mahalliy boshqaruvni ochish','dev_note':'Faqat mahalliy dasturlash uchun. Alohida xodim seansi va haqiqiy mahalliy yozuvlar.','invalid_login':'Kirish amalga oshmadi. Login va parolni tekshiring.','rate_limit':'Urinishlar juda ko‘p. 15 daqiqadan keyin qaytaring.','local_only':'Faqat mahalliy dasturlash muhitida ishlaydi.','private':'Maxfiylik standart holat','staff':'Xodim','retention':'Saqlash muddati','expires':'Muddati tugaydi','total':'Jami','attempts':'Urinishlar','succeeded':'Bajarildi','canceled':'Bekor qilindi','no_op':'Hajm kamaymadi','running':'Qayta ishlanmoqda','pending':'Kutilmoqda','ready':'Tayyor','failed_status':'Xato','queued_status':'Navbatda','success_definition':'Bajarilgan / (bajarilgan + xatolar). Bekor qilingan va o‘zgarmagan vazifalar kiritilmaydi.','new_definition':'Davr ichida yaratilgan yagona hisoblar. Ishchi muhitda sinov hisoblari chiqariladi.','active_definition':'Davr ichida qabul qilingan vazifasi bor yagona hisoblar.','completed_definition':'Davr ichida yaratilgan muvaffaqiyatli vazifalar.','back':'Orqaga','profile':'Hisob ma’lumotlari','allowance':'Sarf jurnali','meter':'Resurs','amount':'Miqdor','kind':'Amal turi','private_note':'Xodim bu hisobdagi hujjatlarni ocha oladi. Har bir yuklab olish jurnalga yoziladi.','current_plan':'Belgilangan tarif (pullik obuna ko‘rsatkichi emas)','latency':'Ishlov berish vaqti','median':'Mediana','p95':'95-persentil','locale_desc':'Interfeys kalitlari qamrovi. Avtomatik tekshiruv professional til tahririni almashtirmaydi.','keys':'Kalitlar','coverage':'Kalitlar qamrovi','review':'Til tekshiruvi','pending_review':'Mutaxassis tekshiruvi kutilmoqda','report_table':'Grafik ma’lumotlari jadvali','notice_test':'Sinov yozuvlari ko‘rsatilmoqda. Ular ishchi hisobotlarga kiritilmaydi.','overview_short':'Platforma haqida asosiy ma’lumot','gated':'Chiqarish yopiq','feature_catalog':'Imkoniyatlar katalogi','implemented':'Mahalliy imkoniyat','not_released':'Chiqarilmagan','quote':'Hisob-kitob','engine':'Ishlovchi dvigatel','error':'Xato kodi','consumed':'Sarflangan','reserved':'Band qilingan','remaining':'Qolgan','grant':'Ajratilgan','support_detail':'Yordam so‘rovi','permissions':'Ruxsatlar','no_private':'Mijoz hujjatini ochish audit jurnaliga yoziladi.','updated_definition':'So‘rov vaqtida bazaning haqiqiy yozuvlaridan hisoblandi.','assign_plan':'Tarif belgilash','assign_plan_note':'Bu to‘lov emas: daromadga kirmaydi, pullik obuna esa ostida saqlanib, muddat tugagach qaytadi.','assigned_by_staff':'Xodim tomonidan belgilangan','paid_plan':'Pullik obuna','plan_duration':'Kun (bo‘sh = bekor qilinmaguncha)','clear_plan':'Belgilashni bekor qilish','effective_limits':'Amaldagi limitlar','balance':'Hozirgi qoldiq','after_grant':'Ushbu qo‘shimchadan keyin','quick_amounts':'Tez tanlash','grant_pairing':'Vazifalar ishlashi uchun sahifa birliklari ham kerak, ikkalasini qo‘shing.','files':'Hujjatlar','files_desc':'Har bir yuklab olish jurnalga yoziladi.','file_name':'Fayl','size':'Hajmi','open_file':'Ochish','file_reason':'Ushbu hujjatni ochish sababi','no_files':'Bu hisobda saqlangan hujjat yo‘q.','edit_plan':'Limitlarni tahrirlash','plan_edit_note':'Ushbu tarifdagi barchaga darhol, deploysiz qo‘llanadi.','seed_value':'Standart','reset_plan':'Standartga qaytarish','edited':'O‘zgartirilgan','save_changes':'O‘zgarishlarni saqlash','no_limit':'Cheksiz'}
# Brand, ID, version and Free are product identifiers and intentionally identical.
IDENTICAL = {'brand', 'id', 'free'}
CATALOGS = {'en': EN, 'ru': {**{k:EN[k] for k in IDENTICAL}, **RU_VALUES}, 'uz': {**{k:EN[k] for k in IDENTICAL}, **UZ_VALUES}}
for locale, values in CATALOGS.items():
    if values.keys() != EN.keys():
        raise RuntimeError(f'Operations locale {locale} key mismatch: {EN.keys() ^ values.keys()}')


def get_locale(request):
    locale = request.GET.get('lang', request.COOKIES.get('ops_locale', 'en'))
    return locale if locale in CATALOGS else 'en'

CATALOGS["en"]["integrations"]="Integrations"
CATALOGS["uz"]["integrations"]="Integratsiyalar"
CATALOGS["ru"]["integrations"]="Интеграции"

CATALOGS["en"]["theme"]="Dark theme"
CATALOGS["uz"]["theme"]="Tungi mavzu"
CATALOGS["ru"]["theme"]="Тёмная тема"

CATALOGS["en"].update(reply="Reply to customer",send_reply="Save reply")
CATALOGS["uz"].update(reply="Mijozga javob",send_reply="Javobni saqlash")
CATALOGS["ru"].update(reply="Ответ клиенту",send_reply="Сохранить ответ")

CATALOGS["en"]["days"]="days"
CATALOGS["uz"]["days"]="kun"
CATALOGS["ru"]["days"]="дней"

CATALOGS["en"].update(grant_allowance="Grant exceptional allowance",grant_note="Adds a separately audited, non-expiring allowance. Does not change the plan or unlock features. Tasks require a page allowance.",cancel_task="Cancel queued task")
CATALOGS["uz"].update(grant_allowance="Qo‘shimcha limit berish",grant_note="Auditda qayd etiladigan muddatsiz limit qo‘shadi. Tarifni o‘zgartirmaydi va funksiyalarni ochmaydi. Vazifalar uchun sahifa limiti kerak.",cancel_task="Navbatdagi vazifani bekor qilish")
CATALOGS["ru"].update(grant_allowance="Выдать дополнительный лимит",grant_note="Добавляет бессрочный лимит с записью в аудит. Не меняет план и не открывает функции. Для задач нужен лимит страниц.",cancel_task="Отменить задачу в очереди")

CATALOGS['en']['ai_usage'] = 'AI token usage'
CATALOGS['uz']['ai_usage'] = 'AI token sarfi'
CATALOGS['ru']['ai_usage'] = 'Расход токенов ИИ'

# AI requests: what customers asked the AI for and what it made.
CATALOGS['en'].update(
    generations='AI requests',
    gen_intro='What customers asked the AI for and what it made. Kept for {days} days, then deleted. Opening a request is recorded in the audit log.',
    gen_who='Customer: name, username or Telegram ID', gen_words='Words in the request', gen_all_services='All services',
    gen_document='PDF document', gen_slides='Slides', gen_when='When', gen_customer='Customer', gen_service='Service',
    gen_request='Request', gen_result='Result', gen_open='Open', gen_revised='Change',
    gen_prompt='What they asked for', gen_revision='What they asked to change', gen_original='Their first request',
    gen_outline='Outline', gen_sources='Files they attached', gen_questions='Practice questions', gen_language='Language',
    gen_format='Format', gen_channel='Made in', gen_task='Task', gen_kept_until='Kept until {date}',
    gen_document_title='The document', gen_download='Download', gen_page='Page {n} of {count}',
    gen_previous_page='Previous page', gen_next_page='Next page', gen_no_preview='No page preview for slides — download the file to look at it.',
    gen_no_output='The task finished, but no document was kept.', gen_running='The document is still being made.',
    gen_failed='The task did not finish ({code}), so there is no document.',
    gen_none='No AI requests here', gen_none_desc='Requests appear once a customer starts making an AI document.',
    gen_customer_recent='AI requests',
)
CATALOGS['uz'].update(
    generations='AI so‘rovlari',
    gen_intro='Mijozlar AI’dan nima so‘ragani va u nima yaratgani. {days} kun saqlanadi, keyin o‘chiriladi. So‘rovni ochish audit jurnaliga yoziladi.',
    gen_who='Mijoz: ism, username yoki Telegram ID', gen_words='So‘rovdagi so‘zlar', gen_all_services='Barcha xizmatlar',
    gen_document='PDF hujjat', gen_slides='Taqdimot', gen_when='Qachon', gen_customer='Mijoz', gen_service='Xizmat',
    gen_request='So‘rov', gen_result='Natija', gen_open='Ochish', gen_revised='O‘zgartirish',
    gen_prompt='Nima so‘ragan', gen_revision='Nimani o‘zgartirishni so‘ragan', gen_original='Birinchi so‘rovi',
    gen_outline='Reja', gen_sources='Biriktirgan fayllari', gen_questions='Mashq savollari', gen_language='Til',
    gen_format='Format', gen_channel='Qayerda', gen_task='Vazifa', gen_kept_until='{date} gacha saqlanadi',
    gen_document_title='Hujjat', gen_download='Yuklab olish', gen_page='{count} sahifadan {n}-sahifa',
    gen_previous_page='Oldingi sahifa', gen_next_page='Keyingi sahifa', gen_no_preview='Taqdimot uchun sahifa ko‘rinishi yo‘q — ko‘rish uchun faylni yuklab oling.',
    gen_no_output='Vazifa tugadi, lekin hujjat saqlanmadi.', gen_running='Hujjat hali tayyorlanmoqda.',
    gen_failed='Vazifa tugamadi ({code}), shuning uchun hujjat yo‘q.',
    gen_none='Bu yerda AI so‘rovlari yo‘q', gen_none_desc='Mijoz AI hujjat yaratishni boshlaganda so‘rovlar shu yerda paydo bo‘ladi.',
    gen_customer_recent='AI so‘rovlari',
)
CATALOGS['ru'].update(
    generations='Запросы к ИИ',
    gen_intro='Что клиенты просили у ИИ и что он создал. Хранится {days} дней, затем удаляется. Открытие запроса записывается в журнал аудита.',
    gen_who='Клиент: имя, username или Telegram ID', gen_words='Слова в запросе', gen_all_services='Все сервисы',
    gen_document='PDF-документ', gen_slides='Презентация', gen_when='Когда', gen_customer='Клиент', gen_service='Сервис',
    gen_request='Запрос', gen_result='Результат', gen_open='Открыть', gen_revised='Правка',
    gen_prompt='Что попросили', gen_revision='Что попросили изменить', gen_original='Первый запрос',
    gen_outline='План', gen_sources='Приложенные файлы', gen_questions='Вопросы для практики', gen_language='Язык',
    gen_format='Формат', gen_channel='Где создан', gen_task='Задача', gen_kept_until='Хранится до {date}',
    gen_document_title='Документ', gen_download='Скачать', gen_page='Страница {n} из {count}',
    gen_previous_page='Предыдущая страница', gen_next_page='Следующая страница', gen_no_preview='Для презентаций нет предпросмотра — скачайте файл, чтобы посмотреть.',
    gen_no_output='Задача завершилась, но документ не сохранён.', gen_running='Документ ещё создаётся.',
    gen_failed='Задача не завершилась ({code}), документа нет.',
    gen_none='Здесь нет запросов к ИИ', gen_none_desc='Запросы появятся, когда клиент начнёт создавать AI-документ.',
    gen_customer_recent='Запросы к ИИ',
)
assert CATALOGS['en'].keys() == CATALOGS['uz'].keys() == CATALOGS['ru'].keys()

# The redesigned frame and the Today, Users, Support and Plans screens.
CATALOGS['en'].update(
    today='Today', today_desc='What happened since midnight, and what is waiting for you.',
    today_new_users='New users', today_active_users='Active users', today_tasks='Tasks today',
    today_ai_documents='AI documents', today_received="So'm received", yesterday='Yesterday',
    today_payments='Card payments to review', today_payments_none='Nothing to review',
    today_support='Support questions open', today_support_none='Inbox is clear',
    today_failed='Failed tasks today', today_failed_none='No failures today',
    oldest_waiting='Oldest waiting', open_list='Open the list', queue_now='In the queue',
    file_storage='File storage', storage_ok='Working', storage_problem='Needs attention',
    customers='Customers', money='Money', product='Product', settings='Settings',
    nav_support='Support', nav_analytics='Analytics', nav_tasks='Tasks',
    waiting='waiting', menu='Menu', close='Close', cancel='Cancel',
    find_customer='Find a customer: name, @username or Telegram ID', search_button='Search',
    period='Period', filters='Filters', last_7='7 days', last_30='30 days', last_90='90 days',
    results_for='Results for', joined_in_period='Joined in this period', clear_search='Clear search',
    no_users='No customers found', no_users_desc='Try a name, @username or Telegram ID. Searches cover every account.',
    tasks_in_period='Tasks in this period',
    support_open='Open', support_waiting_customer='Waiting for customer', support_resolved='Resolved', support_all='All',
    waiting_customer='Waiting for customer', received='Received', replies='Replies',
    support_none='Nothing here', support_none_desc='Questions customers send from the app and the bot arrive here.',
    conversation='Conversation', reply_placeholder='Write to the customer…',
    changes='Changes',
    joined='Joined', grant_short='Add credits', tab_overview='Overview', tab_tasks='Tasks', tab_usage='Usage',
    allowance_left='Allowance left', allowance_desc='Every charge and refund of the allowance, newest first.',
    completed_at='Finished',
    payments_desc='Card transfers waiting for your check come first. Approve only after the money shows in your bank app.',
    not_for_sale='Not for sale',
    group_price='Price', group_allowance='Allowance per 30 days', group_daily='Daily limits',
    group_task='Each task', group_ai='AI documents', group_saved='Saved items',
    field_price_uzs="Price, so'm / 30 days", field_price_xtr='Price, Telegram Stars',
    field_file_tasks='File tasks', field_file_page_units='Page units', field_ai_credits='AI credits',
    field_daily_file_tasks='File tasks a day', field_daily_ai_documents='AI documents a day',
    field_max_file_mib='File size, MB', field_max_pages_per_job='Pages per task', field_concurrent_jobs='Tasks at once',
    field_max_ai_source_pages='Source pages', field_max_ai_source_files='Source files',
    field_max_deck_images='Photos per deck', field_max_ai_input_tokens='Input tokens',
    field_max_generated_pdf_pages='PDF pages made', field_max_generated_slides='Slides made',
    field_saved_workflows='Saved workflows', field_saved_teacher_templates='Teacher templates',
)
CATALOGS['uz'].update(
    today='Bugun', today_desc='Yarim tundan beri nima bo‘ldi va sizni nima kutmoqda.',
    today_new_users='Yangi foydalanuvchilar', today_active_users='Faol foydalanuvchilar', today_tasks='Bugungi vazifalar',
    today_ai_documents='AI hujjatlar', today_received="Tushgan so'm", yesterday='Kecha',
    today_payments='Tekshiriladigan karta to‘lovlari', today_payments_none='Tekshiradigan narsa yo‘q',
    today_support='Ochiq murojaatlar', today_support_none='Hammasiga javob berilgan',
    today_failed='Bugun xato bilan tugaganlar', today_failed_none='Bugun xato yo‘q',
    oldest_waiting='Eng uzoq kutayotgani', open_list='Ro‘yxatni ochish', queue_now='Navbatda',
    file_storage='Fayl ombori', storage_ok='Ishlayapti', storage_problem='E’tibor kerak',
    customers='Mijozlar', money='Pul', product='Mahsulot', settings='Sozlamalar',
    nav_support='Yordam', nav_analytics='Analitika', nav_tasks='Vazifalar',
    waiting='kutmoqda', menu='Menyu', close='Yopish', cancel='Bekor qilish',
    find_customer='Mijozni topish: ism, @username yoki Telegram ID', search_button='Qidirish',
    period='Davr', filters='Filtrlar', last_7='7 kun', last_30='30 kun', last_90='90 kun',
    results_for='Natijalar:', joined_in_period='Shu davrda qo‘shilganlar', clear_search='Qidiruvni tozalash',
    no_users='Mijoz topilmadi', no_users_desc='Ism, @username yoki Telegram ID bilan urinib ko‘ring. Qidiruv barcha hisoblarni qamraydi.',
    tasks_in_period='Shu davrdagi vazifalar',
    support_open='Ochiq', support_waiting_customer='Mijoz javobi kutilmoqda', support_resolved='Hal qilingan', support_all='Hammasi',
    waiting_customer='Mijoz javobi kutilmoqda', received='Kelgan', replies='Javoblar',
    support_none='Bu yerda hech narsa yo‘q', support_none_desc='Mijozlar ilova va botdan yuborgan savollar shu yerga keladi.',
    conversation='Yozishma', reply_placeholder='Mijozga yozing…',
    changes='O‘zgarishlar',
    joined='Qo‘shilgan', grant_short='Kredit qo‘shish', tab_overview='Umumiy', tab_tasks='Vazifalar', tab_usage='Sarf',
    allowance_left='Qolgan limit', allowance_desc='Limitdan har bir yechish va qaytarish, eng yangisi birinchi.',
    completed_at='Tugagan',
    payments_desc='Tekshiruvingizni kutayotgan karta o‘tkazmalari birinchi turadi. Pul bank ilovangizda ko‘ringandan keyingina tasdiqlang.',
    not_for_sale='Sotuvda emas',
    group_price='Narx', group_allowance='30 kunlik limit', group_daily='Kunlik limitlar',
    group_task='Har bir vazifa', group_ai='AI hujjatlar', group_saved='Saqlanganlar',
    field_price_uzs="Narx, so'm / 30 kun", field_price_xtr='Narx, Telegram Stars',
    field_file_tasks='Fayl vazifalari', field_file_page_units='Sahifa birliklari', field_ai_credits='AI kreditlar',
    field_daily_file_tasks='Kuniga fayl vazifalari', field_daily_ai_documents='Kuniga AI hujjatlar',
    field_max_file_mib='Fayl hajmi, MB', field_max_pages_per_job='Bir vazifadagi sahifalar', field_concurrent_jobs='Bir vaqtdagi vazifalar',
    field_max_ai_source_pages='Manba sahifalari', field_max_ai_source_files='Manba fayllari',
    field_max_deck_images='Taqdimotdagi rasmlar', field_max_ai_input_tokens='Kiruvchi tokenlar',
    field_max_generated_pdf_pages='Yaratiladigan PDF sahifalari', field_max_generated_slides='Yaratiladigan slaydlar',
    field_saved_workflows='Saqlangan jarayonlar', field_saved_teacher_templates='O‘qituvchi shablonlari',
)
CATALOGS['ru'].update(
    today='Сегодня', today_desc='Что произошло с полуночи и что ждёт вашего ответа.',
    today_new_users='Новые пользователи', today_active_users='Активные пользователи', today_tasks='Задачи сегодня',
    today_ai_documents='ИИ-документы', today_received='Получено сумов', yesterday='Вчера',
    today_payments='Платежи картой на проверку', today_payments_none='Проверять нечего',
    today_support='Открытые обращения', today_support_none='Все обращения разобраны',
    today_failed='Ошибки сегодня', today_failed_none='Сегодня без ошибок',
    oldest_waiting='Дольше всех ждёт', open_list='Открыть список', queue_now='В очереди',
    file_storage='Хранилище файлов', storage_ok='Работает', storage_problem='Нужно внимание',
    customers='Клиенты', money='Деньги', product='Продукт', settings='Настройки',
    nav_support='Поддержка', nav_analytics='Аналитика', nav_tasks='Задачи',
    waiting='ждут', menu='Меню', close='Закрыть', cancel='Отмена',
    find_customer='Найти клиента: имя, @username или Telegram ID', search_button='Найти',
    period='Период', filters='Фильтры', last_7='7 дней', last_30='30 дней', last_90='90 дней',
    results_for='Результаты по запросу', joined_in_period='Пришли за этот период', clear_search='Сбросить поиск',
    no_users='Клиенты не найдены', no_users_desc='Попробуйте имя, @username или Telegram ID. Поиск идёт по всем аккаунтам.',
    tasks_in_period='Задачи за период',
    support_open='Открытые', support_waiting_customer='Ждём клиента', support_resolved='Решённые', support_all='Все',
    waiting_customer='Ждём клиента', received='Получено', replies='Ответы',
    support_none='Здесь пусто', support_none_desc='Сюда приходят вопросы, которые клиенты отправляют из приложения и бота.',
    conversation='Переписка', reply_placeholder='Напишите клиенту…',
    changes='Изменения',
    joined='С нами с', grant_short='Добавить кредиты', tab_overview='Обзор', tab_tasks='Задачи', tab_usage='Расход',
    allowance_left='Остаток лимита', allowance_desc='Каждое списание и возврат лимита, сначала новые.',
    completed_at='Завершена',
    payments_desc='Сначала — переводы на карту, которые ждут вашей проверки. Подтверждайте, только когда деньги видны в банковском приложении.',
    not_for_sale='Не продаётся',
    group_price='Цена', group_allowance='Лимит на 30 дней', group_daily='Дневные лимиты',
    group_task='Одна задача', group_ai='ИИ-документы', group_saved='Сохранённое',
    field_price_uzs='Цена, сум / 30 дней', field_price_xtr='Цена, Telegram Stars',
    field_file_tasks='Задачи с файлами', field_file_page_units='Единицы страниц', field_ai_credits='Кредиты ИИ',
    field_daily_file_tasks='Задач с файлами в день', field_daily_ai_documents='ИИ-документов в день',
    field_max_file_mib='Размер файла, МБ', field_max_pages_per_job='Страниц в задаче', field_concurrent_jobs='Задач одновременно',
    field_max_ai_source_pages='Страниц источников', field_max_ai_source_files='Файлов-источников',
    field_max_deck_images='Фото в презентации', field_max_ai_input_tokens='Входных токенов',
    field_max_generated_pdf_pages='Страниц PDF на выходе', field_max_generated_slides='Слайдов на выходе',
    field_saved_workflows='Сохранённые сценарии', field_saved_teacher_templates='Шаблоны учителя',
)
CATALOGS['en'].update(send_reply='Send reply', overview='Overview')
CATALOGS['uz'].update(send_reply='Javob yuborish')
CATALOGS['ru'].update(send_reply='Отправить ответ')
CATALOGS['en'].update(no_payments='No card payments from this customer.')
CATALOGS['uz'].update(no_payments='Bu mijozdan karta to‘lovlari yo‘q.')
CATALOGS['ru'].update(no_payments='Платежей картой от этого клиента нет.')
CATALOGS['en'].update(this_computer='this computer')
CATALOGS['uz'].update(this_computer='shu kompyuter')
CATALOGS['ru'].update(this_computer='этот компьютер')
