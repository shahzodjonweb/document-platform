"""Telegram copy in English, Uzbek and Russian.

Buttons pair a familiar symbol with words; messages keep the next action clear.
Use the same keys and format placeholders in every language.
"""
LOCALES = ('en', 'uz', 'ru')

MESSAGES = {
    'download_error': ('📎 I couldn’t download that file. Please send it again.', '📎 Faylni yuklab bo‘lmadi. Qayta yuboring.', '📎 Не удалось скачать файл. Отправьте его ещё раз.'),
    'wrong_file': ('📎 This file doesn’t match your tool. Send a matching file or choose another tool.', '📎 Fayl bu vositaga mos emas. Mos fayl yuboring yoki boshqa vosita tanlang.', '📎 Файл не подходит для этого инструмента. Отправьте подходящий файл или выберите другой инструмент.'),
    'home_title': ('👋 What shall we do with your document?', '👋 Hujjatingiz bilan nima qilamiz?', '👋 Что сделаем с документом?'),
    'home_body': ('Send a file or choose a tool below.', 'Fayl yuboring yoki quyidan vosita tanlang.', 'Отправьте файл или выберите инструмент.'),
    'home': ('🏠 Main menu', '🏠 Bosh menyu', '🏠 Главное меню'),
    'quick_tools': ('⚡ Quick actions', '⚡ Tezkor amallar', '⚡ Быстрые действия'),
    'all_tools': ('🧰 All tools', '🧰 Barcha vositalar', '🧰 Все инструменты'),
    'pdf_tools': ('📄 PDF tools', '📄 PDF vositalari', '📄 Инструменты PDF'),
    'convert_tools': ('🔄 Convert files', '🔄 Formatni o‘zgartirish', '🔄 Конвертация'),
    'recent': ('🗂 Recent tasks', '🗂 So‘nggi vazifalar', '🗂 Последние задачи'),
    'account': ('👤 My account', '👤 Hisobim', '👤 Мой аккаунт'),
    'language_button': ('🌐 Language', '🌐 Til', '🌐 Язык'),
    'continue_task': ('▶️ Continue task', '▶️ Davom etish', '▶️ Продолжить'),
    'choose_tool': ('🧰 What would you like to do?', '🧰 Nima qilmoqchisiz?', '🧰 Что нужно сделать?'),
    'choose_pdf_action': ('📄 PDF received. What shall we do?\nTo merge, send another PDF.', '📄 PDF qabul qilindi. Nima qilamiz?\nBirlashtirish uchun yana PDF yuboring.', '📄 PDF получен. Что сделаем?\nДля объединения отправьте ещё один PDF.'),
    'upload_title': ('📎 Send your file', '📎 Fayl yuboring', '📎 Отправьте файл'),
    'replace_file_question': ('📎 Replace the current file?', '📎 Joriy fayl almashtirilsinmi?', '📎 Заменить текущий файл?'),
    'replace_file': ('🔄 Replace file', '🔄 Faylni almashtirish', '🔄 Заменить файл'),
    'keep_file': ('↩️ Keep current file', '↩️ Joriy faylni qoldirish', '↩️ Оставить текущий'),
    'new_tool_question': ('{tool}\nThis tool needs different files. Start a new task? Saved files stay in your account.', '{tool}\nBu vositaga boshqa fayllar kerak. Yangi vazifa boshlaymizmi? Saqlangan fayllar hisobingizda qoladi.', '{tool}\nНужны другие файлы. Начать новую задачу? Сохранённые файлы останутся в аккаунте.'),
    'choose_one_file': ('📎 Which file shall we use?', '📎 Qaysi fayldan foydalanamiz?', '📎 Какой файл используем?'),
    'upload_pdf': ('Attach a PDF, up to 20 MB.', '20 MB gacha PDF yuboring.', 'Прикрепите PDF до 20 МБ.'),
    'upload_merge': ('Send 2 or more PDFs in the order you want. Up to 20 MB each.', 'Kamida 2 ta PDF’ni kerakli tartibda yuboring. Har biri 20 MB gacha.', 'Отправьте от 2 PDF в нужном порядке, до 20 МБ каждый.'),
    'upload_images': ('Send JPG or PNG images, up to 20 MB each. Attach as files for the best quality.', 'JPG yoki PNG yuboring, har biri 20 MB gacha. Sifatni saqlash uchun fayl sifatida yuboring.', 'Отправьте JPG или PNG до 20 МБ каждый. Для лучшего качества прикрепляйте как файлы.'),
    'document_scan_hint': ('Photos of documents are straightened, cleaned and matched to A4, Letter or Legal. Other photos are kept as they are.', 'Hujjat suratlari tekislanadi, tozalanadi va A4, Letter yoki Legal o‘lchamiga moslanadi. Boshqa suratlar o‘zgarishsiz qoladi.', 'Фото документов выравниваются, очищаются и подгоняются под A4, Letter или Legal. Остальные фото остаются как есть.'),
    'scan_switches_retired': ('Cropping and cleanup are automatic now: document photos are straightened and cleaned, other photos stay as they are.', 'Kesish va tozalash endi avtomatik: hujjat suratlari tekislanadi va tozalanadi, boshqa suratlar o‘zgarishsiz qoladi.', 'Обрезка и очистка теперь автоматические: фото документов выравниваются и очищаются, остальные фото остаются как есть.'),
    'upload_word': ('Send a Word file (.docx), up to 20 MB.', '20 MB gacha Word fayli (.docx) yuboring.', 'Отправьте файл Word (.docx) до 20 МБ.'),
    'upload_slides': ('Send a PowerPoint file (.pptx), up to 20 MB.', '20 MB gacha PowerPoint fayli (.pptx) yuboring.', 'Отправьте файл PowerPoint (.pptx) до 20 МБ.'),
    'upload_received': ('📎 Files added: {count}. Choose your next step below.', '📎 {count} ta fayl qo‘shildi. Quyidan keyingi amalni tanlang.', '📎 Добавлено файлов: {count}. Выберите действие ниже.'),
    'file_ready': ('📎 Files ready: {count}', '📎 Tayyor fayllar: {count}', '📎 Файлов готово: {count}'),
    'need_more_files': ('📎 Send one more PDF to merge them.', '📎 Birlashtirish uchun yana bitta PDF yuboring.', '📎 Отправьте ещё один PDF для объединения.'),
    'options_title': ('⚙️ Your files & options', '⚙️ Fayllar va sozlamalar', '⚙️ Файлы и настройки'),
    'files': ('Files', 'Fayllar', 'Файлы'),
    'pages': ('Pages', 'Sahifalar', 'Страницы'),
    'original': ('Original size', 'Asl o‘lcham', 'Исходный размер'),
    'fit_page': ('Fit image', 'Rasmga mos', 'По размеру фото'),
    'options_default': ('Standard settings', 'Standart sozlamalar', 'Стандартные настройки'),
    'options_button': ('⚙️ Options', '⚙️ Sozlamalar', '⚙️ Настройки'),
    'edit_options': ('⚙️ Adjust options', '⚙️ Sozlash', '⚙️ Настроить'),
    'settings_saved': ('✅ Settings updated.', '✅ Sozlamalar saqlandi.', '✅ Настройки сохранены.'),
    'autoquote_not_ready': ('Choose the pages below, then you’re ready to start.', 'Quyidan sahifalarni tanlang, keyin boshlash mumkin.', 'Выберите страницы ниже — и можно начинать.'),
    'page_selection': ('📑 Choose pages', '📑 Sahifalarni tanlash', '📑 Выбрать страницы'),
    'page_order': ('↕️ Page order', '↕️ Sahifalar tartibi', '↕️ Порядок страниц'),
    'split_groups': ('✂️ Page groups', '✂️ Sahifa guruhlari', '✂️ Группы страниц'),
    'all_pages': ('📑 All pages', '📑 Barcha sahifalar', '📑 Все страницы'),
    'each_page': ('📄 Each page separately', '📄 Har sahifa alohida', '📄 Каждая страница отдельно'),
    'file_order': ('↕️ File order', '↕️ Fayllar tartibi', '↕️ Порядок файлов'),
    'remove_file': ('➖ Remove file', '➖ Faylni olib tashlash', '➖ Убрать файл'),
    'margin_button': ('↔️ Margins', '↔️ Hoshiya', '↔️ Поля'),
    'pages_prompt': ('📑 Which pages?\nFor example: 1,3-5', '📑 Qaysi sahifalar?\nMasalan: 1,3-5', '📑 Какие страницы?\nНапример: 1,3-5'),
    'reorder_prompt': ('↕️ Send every page number once, in the new order.\nFor example: 3,1,2', '↕️ Har bir sahifa raqamini yangi tartibda bir marta yozing.\nMasalan: 3,1,2', '↕️ Укажите все страницы по одному разу в новом порядке.\nНапример: 3,1,2'),
    'split_prompt': ('✂️ Send page groups, separated by ;\nFor example: 1-2;3-5', '✂️ Sahifa guruhlarini ; bilan ajratib yozing.\nMasalan: 1-2;3-5', '✂️ Разделите группы страниц знаком ;\nНапример: 1-2;3-5'),
    'order_prompt': ('↕️ Send all file numbers in the new order.\nFor example: 2,1', '↕️ Barcha fayl raqamlarini yangi tartibda yozing.\nMasalan: 2,1', '↕️ Укажите все номера файлов в новом порядке.\nНапример: 2,1'),
    'remove_prompt': ('➖ Which file? Send its number, for example: 2.\nIt stays saved in your account.', '➖ Qaysi fayl? Raqamini yozing, masalan: 2.\nFayl hisobingizda saqlanadi.', '➖ Какой файл убрать? Введите номер, например: 2.\nОн останется в вашем аккаунте.'),
    'margin_prompt': ('↔️ Send a margin from 0 to 72 points.\nFor example: 24', '↔️ Hoshiyani 0–72 punkt oralig‘ida yozing.\nMasalan: 24', '↔️ Укажите размер полей от 0 до 72 пунктов.\nНапример: 24'),
    'review_title': ('✅ Ready to start', '✅ Boshlashga tayyor', '✅ Можно начинать'),
    'review_hint': ('Check the task below, then tap Start.', 'Quyidagi vazifani tekshirib, Boshlashni bosing.', 'Проверьте задачу и нажмите «Начать».'),
    'tap_to_run': ('Nothing counts until you tap Start.', 'Boshlashni bosmaguningizcha hech narsa hisoblanmaydi.', 'Ничего не засчитывается, пока вы не нажмёте «Начать».'),
    # This week's limits, on the account screen and beside a task. A plan with
    # no limit shows none of these numbers.
    'week_ai_documents': ('AI documents this week', 'Bu haftadagi AI hujjatlar', 'ИИ-документы на этой неделе'),
    'week_file_jobs': ('File tools this week', 'Bu haftadagi fayl vazifalari', 'Задачи с файлами на этой неделе'),
    'edits_per_file': ('Edits per file', 'Har bir faylga tahrirlar', 'Правок на файл'),
    'unlimited': ('unlimited', 'cheksiz', 'без ограничений'),
    'files_week_used': ('File tools this week: {used} of {limit}', 'Bu haftadagi fayl vazifalari: {limit} tadan {used} tasi', 'Задачи с файлами на этой неделе: {used} из {limit}'),
    'files_week_hint': ('This week’s file tasks are used up. New ones from {when}, or choose a plan with unlimited file tools.', 'Bu haftalik fayl vazifalari tugadi. Limit yangilanadi: {when}. Cheksiz fayl vositalari uchun tarif tanlang.', 'Задачи с файлами на эту неделю закончились. Лимит обновится: {when}. Без ограничений — на другом тарифе.'),
    'ai_week_used': ('AI documents this week: {used} of {limit}', 'Bu haftadagi AI hujjatlar: {limit} tadan {used} tasi', 'ИИ-документы на этой неделе: {used} из {limit}'),
    'ai_edits_used': ('✏️ Edits of this file: {used} of {limit} used', '✏️ Bu fayl tahrirlari: {limit} tadan {used} tasi ishlatilgan', '✏️ Правки этого файла: использовано {used} из {limit}'),
    'edit_settings': ('⚙️ Edit options', '⚙️ Sozlash', '⚙️ Настроить'),
    'cancel_step': ('✖️ Cancel', '✖️ Bekor qilish', '✖️ Отмена'),
    'cancel_button': ('✖️ Cancel task', '✖️ Bekor qilish', '✖️ Отменить задачу'),
    'cancel_question': ('Discard this draft? Your files and submitted tasks will stay saved.', 'Qoralama bekor qilinsinmi? Fayllar va yuborilgan vazifalar saqlanadi.', 'Удалить черновик? Файлы и отправленные задачи сохранятся.'),
    'cancel_confirm': ('🗑 Discard draft', '🗑 Bekor qilish', '🗑 Удалить черновик'),
    'keep_task': ('▶️ Keep working', '▶️ Davom etish', '▶️ Продолжить'),
    'new_question': ('Start fresh? This replaces your draft. Saved files and history stay.', 'Yangidan boshlaymizmi? Qoralama tozalanadi. Fayllar va tarix saqlanadi.', 'Начать заново? Черновик будет заменён. Файлы и история сохранятся.'),
    'new_confirm': ('➕ Start fresh', '➕ Yangidan boshlash', '➕ Начать заново'),
    'new_task': ('➕ New task', '➕ Yangi vazifa', '➕ Новая задача'),
    'processing': ('⏳ Working on it…\nYou can close the chat. I’ll send your result here.', '⏳ Tayyorlayapman…\nChatni yopishingiz mumkin. Natijani shu yerga yuboraman.', '⏳ Обрабатываю…\nМожно закрыть чат. Я пришлю результат сюда.'),
    'check_status': ('🔄 Refresh status', '🔄 Holatni yangilash', '🔄 Обновить статус'),
    'queued': ('⏳ You’re in the queue. I’ll send your result here when it’s ready.', '⏳ Vazifa navbatda. Tayyor natijani shu yerga yuboraman.', '⏳ Задача в очереди. Пришлю результат, когда он будет готов.'),
    'recent_empty': ('🗂 No tasks yet. Send a file to get started.', '🗂 Hali vazifalar yo‘q. Boshlash uchun fayl yuboring.', '🗂 Задач пока нет. Отправьте файл, чтобы начать.'),
    'download': ('📥 Send result again', '📥 Natijani qayta yuborish', '📥 Прислать результат снова'),
    'result_expired': ('⌛ This result is no longer stored. Send the original file to try again.', '⌛ Natijaning saqlash muddati tugagan. Asl faylni qayta yuboring.', '⌛ Срок хранения истёк. Отправьте исходный файл ещё раз.'),
    'retry_task': ('🔄 Review & retry', '🔄 Tekshirib qayta urinish', '🔄 Проверить и повторить'),
    'link_methods': ('🔑 Sign-in methods', '🔑 Kirish usullari', '🔑 Способы входа'),
    'linked_methods': ('Sign in with', 'Kirish usullari', 'Способы входа'),
    'link_instructions': ('Use email or Google already? Sign in to that account on the website → Settings → Sign-in methods → Connect Telegram. Approve here, then return to the same browser.', 'Email yoki Google bilan kirganmisiz? Saytda o‘sha hisobga kiring → Sozlamalar → Kirish usullari → Telegramni ulash. Bu yerda tasdiqlab, o‘sha brauzerga qayting.', 'Уже входите через email или Google? На сайте войдите в тот аккаунт → Настройки → Способы входа → Подключить Telegram. Подтвердите здесь и вернитесь в тот же браузер.'),
    'guide': ('📎 Send a file → choose what to do → Start.\n✨ Or tap PDF on a topic or Slides on a topic: describe what you want in one message, and check it before it is made.\n🔒 Enter PDF passwords and edit PDFs in the web app.', '📎 Fayl yuboring → amalni tanlang → Boshlash.\n✨ Yoki «Mavzuga oid PDF» yoki «Mavzuga oid Slayd»ni bosing: nima kerakligini bitta xabarda yozing va tayyorlanishidan oldin tekshiring.\n🔒 PDF parollarini kiriting va PDF tahrirlashni veb ilovada bajaring.', '📎 Отправьте файл → выберите действие → Начать.\n✨ Или нажмите «PDF по теме» или «Слайды по теме»: опишите задачу одним сообщением и проверьте её перед созданием.\n🔒 Пароли PDF вводите и редактируйте PDF на сайте.'),
    # Contacts & support: the two Telegram accounts set in the admin.
    'contacts_button': ('📞 Contacts & support', '📞 Aloqa va yordam', '📞 Контакты и поддержка'),
    'contacts_title': ('📞 Contacts & support', '📞 Aloqa va yordam', '📞 Контакты и поддержка'),
    'contacts_support': ('💬 Support', '💬 Yordam', '💬 Поддержка'),
    'contacts_ads': ('📣 Advertising and partnerships', '📣 Reklama va hamkorlik', '📣 Реклама и сотрудничество'),
    'contacts_write_support': ('💬 Write to support', '💬 Yordamga yozish', '💬 Написать в поддержку'),
    'contacts_write_ads': ('📣 Write about advertising', '📣 Reklama bo‘yicha yozish', '📣 Написать о рекламе'),
    'contacts_none': ('Contacts will appear here soon.', 'Aloqa ma’lumotlari tez orada shu yerda bo‘ladi.', 'Контакты скоро появятся здесь.'),
    'how_it_works': ('💡 How it works', '💡 Qanday ishlaydi', '💡 Как это работает'),
    'fallback': ('📎 Send a file or use the buttons below.', '📎 Fayl yuboring yoki quyidagi tugmalardan foydalaning.', '📎 Отправьте файл или выберите кнопку ниже.'),
    'unsupported': ('📎 Please send a PDF, JPG, PNG, Word (.docx) or PowerPoint (.pptx) file.', '📎 PDF, JPG, PNG, Word (.docx) yoki PowerPoint (.pptx) fayli yuboring.', '📎 Отправьте PDF, JPG, PNG, Word (.docx) или PowerPoint (.pptx).'),
    'resend': ('✅ Language saved. Send your file again to begin.', '✅ Til saqlandi. Boshlash uchun faylni qayta yuboring.', '✅ Язык сохранён. Отправьте файл ещё раз, чтобы начать.'),
    'web_tools': ('🌐 More tools on the web', '🌐 Saytda ko‘proq vositalar', '🌐 Больше инструментов на сайте'),
    'web_hint': ('🌐 Open the web app with the same account to edit PDFs and enter passwords securely.', '🌐 PDF tahrirlash va parollarni xavfsiz kiritish uchun shu hisob bilan veb ilovani oching.', '🌐 Откройте сайт с тем же аккаунтом, чтобы редактировать PDF и безопасно вводить пароли.'),
    'upload_more': ('📎 Add files', '📎 Fayl qo‘shish', '📎 Добавить файлы'),
    'one_file_hint': ('📎 This tool takes one file. Remove the extras or start a new task.', '📎 Bu vositaga bitta fayl kerak. Ortiqchasini olib tashlang yoki yangi vazifa boshlang.', '📎 Нужен один файл. Уберите лишние или начните новую задачу.'),
    'photo_hint': ('📷 Photo added. Next time, send as a file to keep the original quality.', '📷 Rasm qo‘shildi. Asl sifatni saqlash uchun keyingi safar fayl sifatida yuboring.', '📷 Фото добавлено. Для исходного качества отправляйте изображение как файл.'),
    'prompt_invalid': ('Try the format in the example, or tap Back.', 'Namunadagi shaklda yozing yoki Orqaga bosing.', 'Попробуйте ввести как в примере или нажмите «Назад».'),
    'free_plan': ('Free', 'Bepul', 'Бесплатный'),
    'resets': ('Resets', 'Yangilanadi', 'Обновится'),
    'plan_label': ('Plan', 'Tarif', 'Тариф'),
    'plans': ('⭐ Plans', '⭐ Tariflar', '⭐ Тарифы'),
    'usage_button': ('📊 My allowance', '📊 Limitlarim', '📊 Мои лимиты'),
    'subscription': ('💳 Subscription', '💳 Obuna', '💳 Подписка'),
    # The home screen's way to the plans: an invitation, not a status page.
    'subscribe_button': ('💎 Subscribe', '💎 Obuna bo‘lish', '💎 Оформить подписку'),
    'limits': ('📎 Bot limit: 20 MB per file. Use the website for larger files.', '📎 Botda: har fayl 20 MB gacha. Kattaroq fayl uchun saytdan foydalaning.', '📎 В боте: до 20 МБ на файл. Для больших файлов используйте сайт.'),
    'retention': ('🕒 Server files are stored for 24 hours. Copies sent here stay in your chat.', '🕒 Server fayllari 24 soat saqlanadi. Bu yerga yuborilgan nusxalar chatda qoladi.', '🕒 Файлы на сервере хранятся 24 часа. Отправленные сюда копии остаются в чате.'),
    # AI generation. The studio's own errors are translated in errors.py.
    'ai_ask_topic': ('✍️ Describe what you want. Say everything in one message: the subject, who it is for, the tone, and how many pages.', '✍️ Nima kerakligini yozing. Hammasini bitta xabarda ayting: mavzu, kim uchun, uslub va necha sahifa.', '✍️ Опишите, что нужно. Всё одним сообщением: тема, для кого, тон и сколько страниц.'),
    # The count a description that names none is given (apps/studio/pages.py
    # DEFAULT_PAGES), the same for a document and a deck on every plan.
    'ai_pages_hint': ('No page or slide count in your message means 10. For slides you can also ask for a look: “dark”, “bold”, or a colour.', 'Xabarda sahifa yoki slayd soni bo‘lmasa, 10 ta bo‘ladi. Slaydlar uchun ko‘rinishni ham so‘rashingiz mumkin: «qorong‘i», «yorqin» yoki rang.', 'Если число страниц или слайдов не указано, будет 10. Для слайдов можно попросить и вид: «тёмная», «ярко» или цвет.'),
    'ai_examples': ('💡 Example descriptions', '💡 Namuna tavsiflar', '💡 Примеры описаний'),
    'ai_examples_title': ('💡 Write it like this', '💡 Mana shunday yozing', '💡 Пишите вот так'),
    'ai_pages': ('Pages', 'Sahifalar', 'Страниц'),
    # The ceiling is the same on every plan, so it is said as ours, not the plan's:
    # naming the plan read as an offer to buy more pages.
    'ai_pages_clamped': ('{asked} asked for; {given} is the most we make in one go.', '{asked} so‘raldi; bir safarda eng ko‘pi {given} ta tayyorlaymiz.', 'Запрошено {asked}; за один раз мы делаем не больше {given}.'),
    'ai_slides': ('Slides', 'Slaydlar', 'Слайдов'),
    'ai_language': ('Language', 'Til', 'Язык'),
    # The deck's design and slide count, chosen in the Mini App over what the description says.
    'ai_theme': ('Design', 'Dizayn', 'Дизайн'),
    'ai_theme_auto': ('Auto — chosen for the topic', 'Avto — mavzuga qarab tanlanadi', 'Авто — по теме'),
    'ai_theme_button': ('🎨 Design and slides', '🎨 Dizayn va slaydlar', '🎨 Дизайн и слайды'),
    'ai_example_copied': ('✏️ That is one of our examples. Change the subject to yours and send it again.', '✏️ Bu bizning namunamiz. Mavzuni o‘zingiznikiga almashtirib, qayta yuboring.', '✏️ Это наш пример. Замените тему на свою и отправьте снова.'),
    # A description that names no topic ("12 ta slayd kk"): what was kept of it,
    # and the one thing still missing. The topic sent next is put in front of it.
    'ai_topic_kept': ('📝 Noted: “{brief}”.', '📝 Yozib oldim: «{brief}».', '📝 Учту: «{brief}».'),
    'ai_topic_question': ('✍️ Only the topic is missing — what should it be about? I’ll add it to what you wrote.', '✍️ Faqat mavzu yetishmayapti: nima haqida tayyorlaymiz? Mavzuni yuboring — uni avvalgi xabaringizga qo‘shaman.', '✍️ Не хватает только темы. На какую тему сделать? Я добавлю её к вашему сообщению.'),
    # The way past a topic the check did not recognise: the same words again are taken as the topic.
    'ai_topic_again': ('↩️ If that already is the topic, just send it again.', '↩️ Agar mavzu shu bo‘lsa, uni yana bir bor yuboring.', '↩️ Если это и есть тема, просто отправьте её ещё раз.'),
    # A file sent while the topic is asked for: only a PDF is read as a source.
    'ai_topic_pdf_only': ('📎 Only PDF files are read here — type the topic, or send a PDF.', '📎 Bu yerda faqat PDF fayl o‘qiladi — mavzuni yozing yoki PDF yuboring.', '📎 Здесь читаются только PDF-файлы — напишите тему или пришлите PDF.'),
    # A file conversion asked of an AI service ("pdf ga o‘tkaz"): the file tools do it.
    'ai_convert': ('🔄 To convert a file, just send it here — I’ll offer the right tool. This service makes something new on a topic you give.', '🔄 Faylni o‘girish uchun uni shu yerga yuboring — mos vositani taklif qilaman. Bu xizmat siz bergan mavzuda yangi material tayyorlaydi.', '🔄 Чтобы конвертировать файл, просто отправьте его сюда — я предложу нужный инструмент. Этот сервис создаёт новый материал на вашу тему.'),
    'ai_topic_example': ('For example: {example}', 'Masalan: {example}', 'Например: {example}'),
    'ai_topic_sample': ('The water cycle, for 6th grade', 'Tabiatda suvning aylanishi, 6-sinf uchun', 'Круговорот воды в природе, для 6 класса'),
    'ai_wrong_tool_slides': ('🖥 You asked for slides — this makes a PDF document.', '🖥 Siz slayd so‘radingiz — bu xizmat PDF hujjat tayyorlaydi.', '🖥 Вы просили слайды — этот сервис делает PDF-документ.'),
    'ai_switch_slides': ('🖥 Make slides instead', '🖥 Slayd qilib tayyorlash', '🖥 Сделать слайды'),
    'ai_wrong_tool_pdf': ('📄 You asked for a document — this makes slides.', '📄 Siz hujjat so‘radingiz — bu xizmat slayd tayyorlaydi.', '📄 Вы просили документ — этот сервис делает слайды.'),
    'ai_switch_pdf': ('📄 Make a PDF instead', '📄 PDF qilib tayyorlash', '📄 Сделать PDF'),
    # With the other format asked for, Generate says which one it makes: a deck
    # asked of the PDF service went through as a PDF beside a one-line warning.
    'ai_pdf_anyway': ('📄 Make a PDF anyway', '📄 Baribir PDF tayyorlash', '📄 Всё равно сделать PDF'),
    'ai_slides_anyway': ('🖥 Make slides anyway', '🖥 Baribir slayd tayyorlash', '🖥 Всё равно сделать слайды'),
    'ai_review_hint_button': ('Nothing counts until you tap “{button}”.', '«{button}» tugmasini bosmaguningizcha hech narsa hisoblanmaydi.', 'Ничего не засчитывается, пока вы не нажмёте «{button}».'),
    # Pictures asked for beyond what one document takes. The cap is the same on
    # every plan, so these never say it is the plan's.
    'ai_images_capped': ('🖼 You asked for pictures; a deck gets up to {count}.', '🖼 Rasm so‘radingiz; bir taqdimotga {count} tagacha rasm qo‘shiladi.', '🖼 Вы просили картинки; в презентацию добавляется до {count}.'),
    'ai_images_capped_pdf': ('🖼 You asked for pictures; a document gets up to {count}.', '🖼 Rasm so‘radingiz; bir hujjatga {count} tagacha rasm qo‘shiladi.', '🖼 Вы просили картинки; в документ добавляется до {count}.'),
    'ai_images_none': ('🖼 You asked for pictures, but none can be added to this one.', '🖼 Rasm so‘radingiz, lekin bunga rasm qo‘shib bo‘lmaydi.', '🖼 Вы просили картинки, но сюда их добавить нельзя.'),
    # A change that only asks for the deck as a PDF: the delivered file goes to
    # PowerPoint → PDF instead of spending an AI edit on the same slides.
    'ai_deck_as_pdf': ('📄 No AI edit needed: tap Start and your deck comes back as a PDF.', '📄 AI tahriri shart emas: «Boshlash»ni bosing — taqdimotingiz PDF bo‘lib keladi.', '📄 Редактировать через ИИ не нужно: нажмите «Начать», и презентация придёт в PDF.'),
    'ai_deck_gone': ('⌛ The deck file is no longer kept on our server. Tap PowerPoint → PDF and send the .pptx from this chat — it comes back as a PDF.', '⌛ Taqdimot fayli serverda endi saqlanmaydi. «PowerPoint → PDF»ni bosing va chatdagi .pptx faylni yuboring — PDF bo‘lib qaytadi.', '⌛ Файл презентации больше не хранится на сервере. Нажмите «PowerPoint → PDF» и отправьте .pptx из этого чата — он вернётся в PDF.'),
    # A change that only asks for a PDF document as slides: a new deck on its subject is offered.
    'ai_doc_to_slides': ('🖥 A change can’t turn this PDF into slides. A deck on the same topic is made as a new one — you’ll check it before it is made.', '🖥 O‘zgartirish bu PDF’ni slaydga aylantira olmaydi. Shu mavzudagi taqdimot yangidan tayyorlanadi — uni tayyorlanishidan oldin tekshirasiz.', '🖥 Изменением этот PDF не превратить в слайды. Презентацию на ту же тему можно сделать заново — вы проверите её перед созданием.'),
    'ai_as_slides': ('🖥 Make slides on this topic', '🖥 Shu mavzuda slayd tayyorlash', '🖥 Сделать слайды на эту тему'),
    # A change that asks for the file in the format it already has: it is sent again.
    'ai_same_format': ('📎 This file is already a {format} file — here it is again. Nothing was changed, and no edit was used.', '📎 Bu fayl allaqachon {format} formatida — mana, yana bir bor yubordim. Hech narsa o‘zgarmadi, tahrir ham ishlatilmadi.', '📎 Этот файл уже в формате {format} — отправляю его ещё раз. Ничего не изменено, правка не потрачена.'),
    'ai_file_gone': ('⌛ The file is no longer kept on our server, so it can’t be sent again. The copy sent earlier in this chat is the same file.', '⌛ Fayl serverda endi saqlanmaydi, shuning uchun uni qayta yuborib bo‘lmaydi. Chatda avval yuborilgan nusxa aynan shu fayl.', '⌛ Файл больше не хранится на сервере, поэтому отправить его снова нельзя. Копия, присланная ранее в этом чате, — тот же файл.'),
    # A format named beside other changes: the review says the file keeps its own.
    'ai_format_kept_deck': ('📎 The deck comes back as PowerPoint. For a PDF, tap {button} when it arrives and write just “PDF”.', '📎 Taqdimot PowerPoint bo‘lib keladi. PDF kerak bo‘lsa, kelgach «{button}» tugmasini bosing va faqat «PDF» deb yozing.', '📎 Презентация придёт в PowerPoint. Нужен PDF — после получения нажмите «{button}» и напишите только «PDF».'),
    'ai_format_kept_pdf': ('📎 The document stays a PDF: a change can’t turn it into slides. For slides, use {service}.', '📎 Hujjat PDF bo‘lib qoladi: o‘zgartirish uni slaydga aylantira olmaydi. Slayd kerak bo‘lsa, «{service}» xizmatidan foydalaning.', '📎 Документ останется в PDF: изменением его не превратить в слайды. Для слайдов выберите «{service}».'),
    # The server refusing a change that names only a file format, should one reach it.
    'ai_format_only': ('📎 That asks only for another file format, and an AI change does not convert files. Write what should change in the document.', '📎 Bu faqat boshqa fayl formatini so‘raydi, AI tahriri esa fayl formatini o‘zgartirmaydi. Hujjatda nimani o‘zgartirish kerakligini yozing.', '📎 Здесь просят только другой формат файла, а ИИ-правка не конвертирует файлы. Напишите, что изменить в документе.'),
    'ai_topic_empty': ('✍️ I need a description before I can start.', '✍️ Boshlashim uchun tavsif kerak.', '✍️ Чтобы начать, нужно описание.'),
    'ai_preparing': ('⏳ Preparing your draft…', '⏳ Qoralama tayyorlanmoqda…', '⏳ Готовлю черновик…'),
    'ai_generate': ('✨ Generate', '✨ Yaratish', '✨ Создать'),
    'ai_change_topic': ('✏️ Change the description', '✏️ Tavsifni o‘zgartirish', '✏️ Изменить описание'),
    'ai_review_hint': ('Nothing counts until you tap Generate.', '«Yaratish» tugmasini bosmaguningizcha hech narsa hisoblanmaydi.', 'Ничего не засчитывается, пока вы не нажмёте «Создать».'),
    'ai_back': ('◀️ Back', '◀️ Orqaga', '◀️ Назад'),
    'ai_revise': ('✏️ Make changes', '✏️ O‘zgartirish kiritish', '✏️ Внести изменения'),
    'ai_revise_title': ('✏️ What should change?', '✏️ Nimani o‘zgartiramiz?', '✏️ Что изменить?'),
    'ai_revise_ask': ('Describe the change in one message. Everything you do not mention stays exactly as it is.', 'O‘zgarishni bitta xabarda yozing. Siz aytmagan hamma narsa o‘z holicha qoladi.', 'Опишите изменение одним сообщением. Всё, о чём вы не упомянете, останется как есть.'),
    'ai_revise_examples': ('Make section 2 shorter · Use a friendlier tone · Add an example to each page · Same document in 8 pages', '2-bo‘limni qisqartiring · Do‘stona uslubda yozing · Har sahifaga misol qo‘shing · Xuddi shu hujjat 8 sahifada', 'Сократите раздел 2 · Сделайте тон дружелюбнее · Добавьте пример на каждую страницу · То же самое на 8 страницах'),
    'ai_revise_of': ('Changing', 'O‘zgartirilmoqda', 'Изменяем'),
    'ai_open_web': ('🌐 Open in web app', '🌐 Veb ilovada ochish', '🌐 Открыть в веб-приложении'),
    'ai_busy': ('⏳ One moment — still working on your last request.', '⏳ Bir lahza — oldingi so‘rovingiz ustida ishlanmoqda.', '⏳ Секунду — ещё обрабатываю прошлый запрос.'),
    # After the AI could not finish a new document: most such failures were a
    # reply our checks refused, which a fuller description makes less likely.
    'ai_failed_advice': ('💡 Try again. If it fails again, write it all in one message: the topic, who it is for and the length.', '💡 Qayta urinib ko‘ring. Yana bo‘lmasa, hammasini bitta xabarda yozing: mavzu, kim uchun va hajmi.', '💡 Попробуйте ещё раз. Если снова не выйдет, напишите всё одним сообщением: тема, для кого и объём.'),
    # A finished document can carry a note about what was adjusted to match what
    # was asked for. These are keyed by the job's own warning codes.
    'questions_trimmed': ('ℹ️ Questions you did not ask for were left out.', 'ℹ️ So‘ramagan savollar qo‘shilmadi.', 'ℹ️ Вопросы, которые вы не запрашивали, не добавлены.'),
    'sections_trimmed': ('ℹ️ The document was trimmed to the number of pages you asked for.', 'ℹ️ Hujjat siz so‘ragan sahifa soniga qisqartirildi.', 'ℹ️ Документ сокращён до запрошенного количества страниц.'),
    'images_skipped': ('ℹ️ A photo could not be added, so that slide was set as text.', 'ℹ️ Rasm qo‘shib bo‘lmadi, shuning uchun o‘sha slayd matn sifatida tayyorlandi.', 'ℹ️ Фото добавить не удалось, поэтому слайд оформлен текстом.'),
    'images_limited': ('ℹ️ A deck holds a set number of photos; the other photo slides were set as text.', 'ℹ️ Bir taqdimotdagi rasmlar soni cheklangan; qolgan rasmli slaydlar matn sifatida tayyorlandi.', 'ℹ️ Число фото в презентации ограничено; остальные слайды с фото оформлены текстом.'),
    'citations_dropped': ('ℹ️ A source reference that did not match any file you sent was left out.', 'ℹ️ Siz yuborgan fayllarga mos kelmagan manba havolasi qo‘shilmadi.', 'ℹ️ Ссылка на источник, не совпавшая с вашими файлами, не добавлена.'),
    'shortened_to_fit': ('ℹ️ A section was longer than its page, so its end was trimmed to keep the page count you asked for.', 'ℹ️ Bir bo‘lim sahifasiga sig‘madi, shuning uchun siz so‘ragan sahifa soni saqlanib, oxiri qisqartirildi.', 'ℹ️ Один раздел не помещался на страницу, поэтому его конец сокращён, чтобы сохранить запрошенное число страниц.'),
    'longer_than_quoted': ('ℹ️ This came out a little longer than estimated.', 'ℹ️ Hujjat taxmindan biroz uzunroq chiqdi.', 'ℹ️ Документ вышел чуть длиннее, чем ожидалось.'),
    # A CV's own notes: what was left out, and why.
    'cv_trimmed': ('ℹ️ The CV was shortened to fit on two pages: a few of the least important lines were left out.', 'ℹ️ CV ikki sahifaga sig‘ishi uchun qisqartirildi: eng kam ahamiyatli bir nechta satr tushirib qoldirildi.', 'ℹ️ Резюме сокращено, чтобы уместиться на двух страницах: несколько наименее важных строк убраны.'),
    'cv_contact_dropped': ('ℹ️ A contact detail that was not in your message was left out.', 'ℹ️ Xabaringizda bo‘lmagan aloqa maʼlumoti CV’ga kiritilmadi.', 'ℹ️ Контакт, которого не было в вашем сообщении, не добавлен в резюме.'),
    'cv_photo_unusable': ('ℹ️ The photo could not be used, so the CV was made without it.', 'ℹ️ Rasmdan foydalanib bo‘lmadi, shuning uchun CV rasmsiz tayyorlandi.', 'ℹ️ Фото использовать не удалось, поэтому резюме сделано без него.'),
    'cv_photo_gone': ('ℹ️ The photo is no longer stored, so this version of the CV is without it.', 'ℹ️ Rasmning saqlanish muddati tugagani uchun CV’ning bu nusxasi rasmsiz tayyorlandi.', 'ℹ️ Срок хранения фото истёк, поэтому эта версия резюме — без него.'),
    'cv_photo_no_slot': ('ℹ️ This template has no place for a photo, so the CV was made without it.', 'ℹ️ Bu shablonda rasm uchun joy yo‘q, shuning uchun CV rasmsiz tayyorlandi.', 'ℹ️ В этом шаблоне нет места для фото, поэтому резюме сделано без него.'),
    # The CV service in the chat, its first way: one message about yourself, as
    # for the other two services; the bot asks only for what a CV cannot be
    # made without, the name, and takes one photo for templates with a place for it.
    'cv_ask': ('✍️ Tell me about yourself in one message: your full name, phone or email, city, the job you want, your work experience with dates, education, skills and languages.', '✍️ O‘zingiz haqingizda bitta xabarda yozing: ism-familiyangiz, telefon yoki email, shahringiz, qanday ish qidirayotganingiz, ish tajribangiz (yillari bilan), taʼlimingiz, ko‘nikmalaringiz va qaysi tillarni bilishingiz.', '✍️ Расскажите о себе одним сообщением: имя и фамилия, телефон или почта, город, какую работу ищете, опыт работы с датами, образование, навыки и языки.'),
    'cv_photo_hint': ('📷 You can also send a photo, before or after the text: it goes on the CV if the template has a place for it.', '📷 Matndan oldin yoki keyin rasmingizni ham yuborishingiz mumkin: shablonda rasm uchun joy bo‘lsa, u CV’ga qo‘yiladi.', '📷 До или после текста можно прислать и фото: оно появится в резюме, если в шаблоне есть для него место.'),
    'cv_photo_attached': ('📷 Photo attached. To replace it, send another one.', '📷 Rasm qabul qilindi. Almashtirish uchun boshqasini yuboring.', '📷 Фото получено. Чтобы заменить его, пришлите другое.'),
    # A PDF or Word file sent while the CV is being written about yourself: the way to the old-CV screen.
    'cv_photo_only': ('📎 PDF and Word files aren’t read here: this CV is made from what you write. To make it from your old CV, tap 📄 From my old CV below and send the file again.', '📎 Bu yerda PDF va Word fayllar o‘qilmaydi: bu CV siz yozgan matndan tayyorlanadi. Uni eski CV’ingizdan tayyorlash uchun pastdagi «📄 Eski CV’imdan» tugmasini bosing va faylni qayta yuboring.', '📎 PDF и Word здесь не читаются: это резюме составляется по вашему сообщению. Чтобы составить его из старого резюме, нажмите «📄 Из старого резюме» ниже и пришлите файл ещё раз.'),
    # A photo too large for a CV (apps/studio/cv/portrait.py: 6 megapixels):
    # said when it arrives, so the description sent next is not refused for it.
    'cv_photo_rejected': ('📷 This image can’t go on a CV: it has to be a JPG or PNG of up to 6 megapixels. Send it as a photo rather than a file — Telegram makes it smaller.', '📷 Bu rasmni CV’ga qo‘yib bo‘lmaydi: u 6 megapikselgacha bo‘lgan JPG yoki PNG bo‘lishi kerak. Uni fayl sifatida emas, rasm sifatida yuboring — Telegram uni kichraytiradi.', '📷 Это изображение не подходит для резюме: нужен JPG или PNG до 6 мегапикселей. Отправьте его как фото, а не файлом — Telegram сам его уменьшит.'),
    # A description that names nobody: kept whole, and the name asked for.
    'cv_name_question': ('✍️ What is your full name? I’ll add it to what you wrote.', '✍️ Ism-familiyangizni to‘liq yozing — uni avvalgi xabaringizga qo‘shaman.', '✍️ Как вас зовут — имя и фамилия? Я добавлю их к вашему сообщению.'),
    'cv_name_sample': ('Dilnoza Karimova', 'Dilnoza Karimova', 'Дильноза Каримова'),
    # The way past a name the check did not see: the name alone, sent again, is taken as it is.
    'cv_name_again': ('↩️ If you already wrote it, send just your full name again.', '↩️ Agar uni yozgan bo‘lsangiz, faqat ism-familiyangizni yana bir bor yuboring.', '↩️ Если вы уже написали его, отправьте ещё раз только имя и фамилию.'),
    # A greeting, "I need a CV" or a name alone says nothing to make a CV of: kept, and the rest asked for.
    'cv_details_question': ('✍️ Now tell me about your work, education, skills and languages — I’ll add it to what you wrote.', '✍️ Endi ish tajribangiz, taʼlimingiz, ko‘nikmalaringiz va qaysi tillarni bilishingiz haqida yozing — uni avvalgi xabaringizga qo‘shaman.', '✍️ Теперь расскажите о работе, образовании, навыках и языках — я добавлю это к вашему сообщению.'),
    'cv_example_copied': ('✏️ That is one of our examples. Write your own details the same way and send them.', '✏️ Bu bizning namunamiz. Xuddi shunday qilib, o‘zingiz haqingizda yozib yuboring.', '✏️ Это наш пример. Напишите так же, но о себе, и отправьте.'),
    # The review of a CV: its length is the template's to decide, one page or two.
    'cv_length': ('1–2', '1–2', '1–2'),
    'cv_template': ('Template', 'Shablon', 'Шаблон'),
    'cv_template_auto': ('Auto — classic unless you pick one', 'Avto — boshqasini tanlamasangiz, klassik', 'Авто — классический, если не выберете другой'),
    'cv_template_button': ('🎨 CV template', '🎨 CV shabloni', '🎨 Шаблон резюме'),
    'cv_photo_line': ('📷 Photo: attached', '📷 Rasm: qo‘shilgan', '📷 Фото: добавлено'),
    # A photo on a template picked without a place for it: said before paying, with the way to one that has.
    'cv_photo_no_slot_line': ('📷 Photo: attached, but this template has no place for it — pick one marked “Photo”', '📷 Rasm: qo‘shilgan, lekin bu shablonda unga joy yo‘q — «Foto» belgisi bor shablonni tanlang', '📷 Фото: добавлено, но в этом шаблоне для него нет места — выберите шаблон с пометкой «Фото»'),
    # Text sent while a new CV's review is open: the second half of a long
    # description Telegram split is added to it; anything later is not.
    'cv_description_added': ('📝 Added to your description.', '📝 Tavsifingizga qo‘shildi.', '📝 Добавлено к вашему описанию.'),
    'cv_text_not_added': ('ℹ️ That text was not added to the CV. To change what it says, tap ✏️ Change the description.', 'ℹ️ Bu matn CV’ga qo‘shilmadi. Undagi maʼlumotni o‘zgartirish uchun ✏️ Tavsifni o‘zgartirish tugmasini bosing.', 'ℹ️ Этот текст не добавлен в резюме. Чтобы изменить его содержание, нажмите ✏️ Изменить описание.'),
    'cv_caption_not_added': ('ℹ️ The text sent with the photo was not added. To change what the CV says, tap ✏️ Change the description.', 'ℹ️ Rasm bilan yuborilgan matn qo‘shilmadi. CV’dagi maʼlumotni o‘zgartirish uchun ✏️ Tavsifni o‘zgartirish tugmasini bosing.', 'ℹ️ Текст, отправленный с фото, не добавлен. Чтобы изменить содержание резюме, нажмите ✏️ Изменить описание.'),
    # A photo sent for a change to a finished CV: a change takes none.
    'cv_revise_photo': ('📷 A new photo can’t be added to a finished CV. To use it, start a new CV with /cv and send the photo with your details.', '📷 Tayyor CV’ga yangi rasm qo‘shib bo‘lmaydi. Undan foydalanish uchun /cv orqali yangi CV boshlang va rasmni maʼlumotlaringiz bilan birga yuboring.', '📷 В готовое резюме нельзя добавить новое фото. Чтобы использовать его, начните новое резюме командой /cv и пришлите фото вместе с данными о себе.'),
    'cv_photo_none': ('📷 Photo: none', '📷 Rasm: yo‘q', '📷 Фото: нет'),
    # On a new CV's review a photo sent now still goes on it.
    'cv_photo_none_add': ('📷 Photo: none — to add one, send it here', '📷 Rasm: yo‘q — qo‘shish uchun shu yerga yuboring', '📷 Фото: нет — чтобы добавить, пришлите его сюда'),
    # Changes a CV takes, as the server reads them (apps/studio/edits.py):
    # "Remove the photo" takes the portrait off, "another design" picks again.
    'cv_revise_examples': ('Add IELTS 7.5 (2023) to the certificates · Make the profile shorter · Remove the photo · Use another design', 'Sertifikatlarga IELTS 7.5 (2023) ni qo‘shing · Profilni qisqartiring · Rasmsiz qiling · Boshqa dizayn qiling', 'Добавьте в сертификаты IELTS 7.5 (2023) · Сократите профиль · Уберите фото · Сделайте другой дизайн'),
    'cv_failed_advice': ('💡 Try again. If it fails again, write it all in one message: your name, contacts, jobs with dates, education and skills.', '💡 Qayta urinib ko‘ring. Yana bo‘lmasa, hammasini bitta xabarda yozing: ism-familiya, aloqa maʼlumotlari, ish joylari (yillari bilan), taʼlim va ko‘nikmalar.', '💡 Попробуйте ещё раз. Если снова не выйдет, напишите всё одним сообщением: имя, контакты, места работы с датами, образование и навыки.'),
    # How a CV is made, asked first (apps/studio/cv/sources.py): written about
    # yourself in one message, from the LinkedIn profile, or from an old CV.
    'cv_choose_ask': ('How shall we make your CV?', 'CV’ni qanday tayyorlaymiz?', 'Как составим резюме?'),
    'cv_choose_hint': ('✍️ About yourself: one message is enough\n🔗 LinkedIn: your profile as a PDF or screenshots\n📄 Old CV: a PDF, a Word file or photos of it', '✍️ O‘zingiz haqingizda: bitta xabar kifoya\n🔗 LinkedIn: profilingiz PDF yoki skrinshot ko‘rinishida\n📄 Eski CV: PDF, Word fayl yoki uning rasmlari', '✍️ О себе: достаточно одного сообщения\n🔗 LinkedIn: профиль в PDF или скриншотами\n📄 Старое резюме: PDF, файл Word или его фото'),
    'cv_mode_text': ('✍️ Write about myself', '✍️ O‘zim haqimda yozaman', '✍️ Напишу о себе'),
    'cv_mode_linkedin': ('🔗 From my LinkedIn', '🔗 LinkedIn profilimdan', '🔗 Из моего LinkedIn'),
    'cv_mode_file': ('📄 From my old CV', '📄 Eski CV’imdan', '📄 Из старого резюме'),
    # A greeting or a word or two sent on that screen, before any way was chosen.
    'cv_choose_first': ('👇 First choose how to make your CV.', '👇 Avval CV’ni qanday tayyorlashni tanlang.', '👇 Сначала выберите, как составить резюме.'),
    # LinkedIn needs a sign-in and forbids reading its pages by program: its own PDF export, or screenshots.
    'cv_linkedin_title': ('🔗 From your LinkedIn profile', '🔗 LinkedIn profilingizdan', '🔗 Из профиля LinkedIn'),
    'cv_linkedin_ask': ('LinkedIn doesn’t let us open profiles, so send yours as a file:', 'LinkedIn profillarni ochishga ruxsat bermaydi, shuning uchun profilingizni fayl qilib yuboring:', 'LinkedIn не даёт нам открывать профили, поэтому пришлите свой профиль файлом:'),
    'cv_linkedin_link_sent': ('🔗 LinkedIn links can’t be opened here, so send your profile as a file:', '🔗 LinkedIn havolalarini bu yerda ochib bo‘lmaydi, shuning uchun profilingizni fayl qilib yuboring:', '🔗 Ссылки LinkedIn здесь не открываются, поэтому пришлите профиль файлом:'),
    'cv_linkedin_computer': ('💻 On a computer: open your profile, click More → Save to PDF and send the file here.', '💻 Kompyuterda: profilingizni oching, «More» → «Save to PDF» tugmasini bosing va faylni shu yerga yuboring.', '💻 На компьютере: откройте профиль, нажмите «Ещё» → «Сохранить в формате PDF» (More → Save to PDF) и пришлите файл сюда.'),
    'cv_linkedin_phone': ('📱 On a phone: open linkedin.com in the browser with “Desktop site” on and do the same — or send screenshots of your whole profile, all at once.', '📱 Telefonda: brauzerda «Kompyuter versiyasi»ni yoqib, linkedin.com saytida xuddi shunday qiling — yoki butun profilingiz skrinshotlarini birdaniga yuboring.', '📱 На телефоне: откройте linkedin.com в браузере с включённой «Версией для ПК» и сделайте то же самое — или пришлите скриншоты всего профиля, все сразу.'),
    'cv_file_title': ('📄 From your old CV', '📄 Eski CV’ingizdan', '📄 Из старого резюме'),
    'cv_file_ask': ('Send your old CV: a PDF, a Word file (.docx), or photos or scans of its pages — all at once. Every fact in it is kept and written up neatly, in the language you choose.', 'Eski CV’ingizni yuboring: PDF, Word fayl (.docx) yoki sahifalarining rasmi yoxud skanini — hammasini birdaniga. Undagi barcha maʼlumotlar saqlanadi va siz tanlagan tilda chiroyli qilib qayta yoziladi.', 'Пришлите старое резюме: PDF, файл Word (.docx) или фото либо сканы страниц — всё сразу. Все факты из него сохранятся и будут аккуратно изложены на выбранном вами языке.'),
    # Words sent with the file, or before it, are notes on top of it, never its facts' place.
    'cv_notes_hint': ('✏️ In the caption or a message you can add notes: the job you want now, what to change or add.', '✏️ Fayl izohida yoki alohida xabarda istaklaringizni yozishingiz mumkin: hozir qanday ish qidiryapsiz, nimani o‘zgartirish yoki qo‘shish kerak.', '✏️ В подписи к файлу или сообщением можно добавить пожелания: какую работу ищете сейчас, что изменить или добавить.'),
    'cv_send_file_now': ('📎 Now send the file.', '📎 Endi faylni yuboring.', '📎 Теперь пришлите файл.'),
    # The description of a CV made from files written again: its files are still kept.
    'cv_files_kept': ('Write new notes to make the CV again from this file, or send another file to use instead.', 'CV’ni shu fayldan qayta tayyorlash uchun yangi istaklaringizni yozing yoki uning o‘rniga boshqa fayl yuboring.', 'Напишите новые пожелания, чтобы заново составить резюме из этого файла, или пришлите вместо него другой файл.'),
    'cv_file_name_question': ('✍️ I couldn’t find your name in the file. What is your full name?', '✍️ Fayldan ismingizni topa olmadim. Ism-familiyangizni to‘liq yozing.', '✍️ Не удалось найти в файле ваше имя. Как вас зовут — имя и фамилия?'),
    # A file the CV could not be made from: another one, or writing instead.
    'cv_send_another': ('📎 Send another file', '📎 Boshqa fayl yuborish', '📎 Отправить другой файл'),
    'cv_write_instead': ('✍️ Write about myself instead', '✍️ O‘rniga o‘zim haqimda yozaman', '✍️ Лучше напишу о себе'),
    # Said with counted(): "10 files", "10 ta fayl", "10 файлов".
    'cv_files_limit': ('📎 That’s too much for one CV: at most {files}, {pages} in all.', '📎 Bitta CV uchun bu juda ko‘p: ko‘pi bilan {files}, jami {pages}.', '📎 Для одного резюме это слишком много: максимум {files}, всего {pages}.'),
    # The review of a CV made from files: where its facts come from, and the notes on top of them.
    'cv_from_files': ('📎 From: {files}', '📎 Manba: {files}', '📎 Источник: {files}'),
    'cv_notes_line': ('📝 Notes: “{notes}”', '📝 Istaklaringiz: «{notes}»', '📝 Пожелания: «{notes}»'),
    'cv_notes_added': ('📝 Added to your notes.', '📝 Istaklaringizga qo‘shildi.', '📝 Добавлено к вашим пожеланиям.'),
    # Screenshots sent one at a time, or the end of an album that came late: more of the CV's files.
    # Pages past the OCR share or the time for one CV's files, and files that
    # could not be read, said on its review (apps/studio/cv/sources.py). {what}
    # is counted(): "1 file", "2 pages", joined by cv_unread_and.
    'cv_unread': ('⚠️ Couldn’t read: {what}. The CV is made without it; to include it, send fewer pages or clearer photos.', '⚠️ O‘qib bo‘lmadi: {what}. CV usiz tayyorlanadi; uni ham qo‘shish uchun kamroq sahifa yoki aniqroq rasm yuboring.', '⚠️ Не удалось прочитать: {what}. Резюме составлено без этого; чтобы это учесть, пришлите меньше страниц или более чёткие фото.'),
    'cv_unread_and': (' and ', ' va ', ' и '),
    # A CV made from photos or screenshots: a photo sent on its review may be its portrait or one more page.
    'cv_photo_none_add_pages': ('📷 Photo: none — to add one, send it here. More pages or screenshots? Send them together, as one album.', '📷 Rasm: yo‘q — qo‘shish uchun shu yerga yuboring. Yana sahifa yoki skrinshotlar bormi? Ularni birga, bitta albom qilib yuboring.', '📷 Фото: нет — чтобы добавить, пришлите его сюда. Есть ещё страницы или скриншоты? Пришлите их вместе, одним альбомом.'),
    'cv_photo_or_page': ('📷 Is this your photo for the CV, or one more page or screenshot to read?', '📷 Bu CV uchun rasmingizmi yoki o‘qish uchun yana bir sahifa yoxud skrinshotmi?', '📷 Это ваше фото для резюме или ещё одна страница либо скриншот, которые нужно прочитать?'),
    'cv_photo_is_portrait': ('📷 My photo for the CV', '📷 CV uchun rasmim', '📷 Моё фото для резюме'),
    'cv_photo_is_page': ('📄 A page to read', '📄 O‘qish uchun sahifa', '📄 Страница для чтения'),
    # A photo with nothing to read in it, sent before a way to make the CV was chosen: kept as its photo.
    'cv_photo_kept_choose': ('📷 There’s no text to read in this photo, so it will go on your CV as your photo. If it’s a page of your old CV, choose 📄 From my old CV and send a clearer one.', '📷 Bu rasmda o‘qiladigan matn yo‘q, shuning uchun u CV’ga rasmingiz sifatida qo‘yiladi. Agar u eski CV’ingiz sahifasi bo‘lsa, «📄 Eski CV’imdan»ni tanlang va aniqroq rasm yuboring.', '📷 В этом фото нет текста, поэтому оно будет фотографией в резюме. Если это страница старого резюме, выберите «📄 Из старого резюме» и пришлите более чёткое фото.'),
    # After a refusal that passes (too many at once), the CV made again from the files kept.
    'cv_try_again': ('🔄 Try again', '🔄 Qayta urinish', '🔄 Попробовать снова'),
    'cv_files_added': ('📎 Added to the CV’s files.', '📎 CV fayllariga qo‘shildi.', '📎 Добавлено к файлам резюме.'),
    # While a CV's files wait for the reader (apps/studio/cv/reads.py): one
    # message, which becomes the review once they are read. Its line says
    # where they are in the queue; {files} is counted(): "2 files". Only the
    # files of others are ahead of the customer.
    'cv_wait_one': ('⏳ Reading your file…', '⏳ Faylingizni o‘qiyapmiz…', '⏳ Читаем ваш файл…'),
    'cv_wait_many': ('⏳ Reading your files…', '⏳ Fayllaringizni o‘qiyapmiz…', '⏳ Читаем ваши файлы…'),
    'cv_wait_ahead': ('🕐 {files} ahead of you', '🕐 Sizdan oldin navbatda {files} bor', '🕐 Перед вами в очереди: {files}'),
    'cv_wait_next': ('🕐 You’re next', '🕐 Keyingi navbat sizniki', '🕐 Ваша очередь следующая'),
    'cv_wait_now': ('📖 Reading now', '📖 Hozir o‘qiyapmiz', '📖 Читаем прямо сейчас'),
    'cv_wait_hint': ('Your CV’s review will appear right here as soon as reading is done. Meanwhile you can send more files or notes.',
                     'O‘qib bo‘lishimiz bilan CV’ingiz tekshirish uchun shu yerda chiqadi. Bu orada yana fayl yoki istaklaringizni yuborishingiz mumkin.',
                     'Как только дочитаем, здесь появится ваше резюме для проверки. А пока можно прислать ещё файлы или пожелания.'),
    # A wait whose place has not moved for ten minutes (telegram/bot.py
    # CV_WAIT_LIMIT): it goes on, and the review still comes by itself. Check
    # now only looks at once; nothing is sent again.
    'cv_wait_slow': ('⏳ Reading is taking longer than usual. Your files and notes are kept, and your CV’s review will still appear right here once they’re read — there’s no need to send anything again.',
                     '⏳ O‘qish odatdagidan uzoqroq cho‘zilyapti. Fayllaringiz va istaklaringiz saqlanib turibdi: o‘qib bo‘lishimiz bilan CV tekshirish uchun shu yerda chiqadi — hech narsani qayta yuborishingiz shart emas.',
                     '⏳ Чтение занимает больше времени, чем обычно. Файлы и пожелания сохранены: как только дочитаем, резюме для проверки появится здесь — ничего присылать заново не нужно.'),
    'cv_wait_check_now': ('🔄 Check now', '🔄 Hozir tekshirish', '🔄 Проверить сейчас'),
    # Check now on an older waiting message, while the chat waits in a newer one.
    'cv_wait_moved': ('⏳ Your files are still being read — the review will appear in the newest message below.',
                      '⏳ Fayllaringizni hali o‘qiyapmiz — CV tekshirish uchun pastdagi eng yangi xabarda chiqadi.',
                      '⏳ Файлы ещё читаются — резюме для проверки появится в последнем сообщении ниже.'),
    # Generate on a CV's review while a file added to it is still being read: said above the review.
    'cv_wait_adding': ('⏳ Still reading the file you added. The CV with it will appear in the message below — make it from there.',
                       '⏳ Qo‘shgan faylingizni hali o‘qiyapmiz. U qo‘shilgan CV pastdagi xabarda chiqadi — uni o‘sha yerdan tayyorlang.',
                       '⏳ Ещё читаем добавленный файл. Резюме с ним появится в сообщении ниже — создайте его оттуда.'),
}

# Keep the older keys for commands, saved controls and transport compatibility.
# They share the same tone as the primary flow instead of exposing command syntax.
LEGACY_MESSAGES = {
    'welcome': ('👋 Welcome to PDF Master! Send a file to begin. Server copies are kept for 24 hours.', '👋 PDF Master’ga xush kelibsiz! Boshlash uchun fayl yuboring. Serverdagi nusxalar 24 soat saqlanadi.', '👋 Добро пожаловать в PDF Master! Отправьте файл. Копии на сервере хранятся 24 часа.'),
    'tools': ('🧰 Choose what to do with your file.', '🧰 Fayl bilan nima qilishni tanlang.', '🧰 Выберите действие с файлом.'),
    'received': ('📎 File added. Send more or tap Start when ready.', '📎 Fayl qo‘shildi. Yana yuboring yoki Boshlashni bosing.', '📎 Файл добавлен. Отправьте ещё или нажмите «Начать».'),
    'done': ('✅ Check your files, then tap Start.', '✅ Fayllarni tekshirib, Boshlashni bosing.', '✅ Проверьте файлы и нажмите «Начать».'),
    'run': ('▶️ Start', '▶️ Boshlash', '▶️ Начать'),
    'empty': ('📎 Send a file first.', '📎 Avval fayl yuboring.', '📎 Сначала отправьте файл.'),
    'working': ('⏳ Working on your file…', '⏳ Fayl tayyorlanmoqda…', '⏳ Обрабатываю файл…'),
    'result': ('✅ Your result is ready! Server copies expire after 24 hours; files sent here stay in the chat.', '✅ Natija tayyor! Serverdagi nusxalar 24 soatdan keyin o‘chiriladi; bu yerdagi fayllar chatda qoladi.', '✅ Готово! Копии на сервере удалятся через 24 часа; присланные файлы останутся в чате.'),
    'no_op': ('✅ Your file is unchanged. No allowance was used.', '✅ Fayl o‘zgarmadi. Limit sarflanmadi.', '✅ Файл не изменился. Лимит не списан.'),
    'support': ('💬 Tell us what you need help with.', '💬 Qanday yordam kerakligini yozing.', '💬 Напишите, с чем нужна помощь.'),
    'ticket': ('✅ Your message is with support.', '✅ Xabaringiz yordam xizmatiga yuborildi.', '✅ Сообщение передано в поддержку.'),
    'cancel': ('✅ Draft discarded. Your files and task history are saved.', '✅ Qoralama bekor qilindi. Fayllar va vazifalar tarixi saqlandi.', '✅ Черновик удалён. Файлы и история задач сохранены.'),
    'help': ('📎 Send a file → choose an action → Start. Use the buttons to adjust options or find recent results.', '📎 Fayl yuboring → amalni tanlang → Boshlash. Sozlamalar va natijalar uchun tugmalardan foydalaning.', '📎 Отправьте файл → выберите действие → Начать. Настройки и результаты доступны по кнопкам.'),
    'login': ('🔐 Approve sign-in only if you requested it in this browser:', '🔐 Faqat ushbu brauzerda kirishni o‘zingiz boshlagan bo‘lsangiz, tasdiqlang:', '🔐 Подтверждайте вход, только если вы запросили его в этом браузере:'),
    'confirm': ('🔐 Approve sign-in', '🔐 Kirishni tasdiqlash', '🔐 Подтвердить вход'),
    'approved': ('✅ Sign-in approved. Return to the same browser.', '✅ Kirish tasdiqlandi. O‘sha brauzerga qayting.', '✅ Вход подтверждён. Вернитесь в тот же браузер.'),
    'language': ('🌐 Choose your language.', '🌐 Tilni tanlang.', '🌐 Выберите язык.'),
    'open': ('🌐 Open web app', '🌐 Veb ilova', '🌐 Открыть сайт'),
    'terms': ('🕒 Server files expire after 24 hours; copies sent to Telegram stay in your chat.\n✨ For AI documents we keep your description and the result for 30 days so our team can check quality and stop misuse; then they are deleted.\n💳 A plan switches on after we check your card transfer.\nPayment help: /paysupport', '🕒 Server fayllari 24 soatdan keyin o‘chiriladi; Telegram’ga yuborilgan nusxalar chatda qoladi.\n✨ AI hujjatlar uchun tavsifingiz va natija 30 kun saqlanadi — jamoamiz sifatni tekshirishi va suiiste’molning oldini olishi uchun; keyin o‘chiriladi.\n💳 Tarif karta o‘tkazmangizni tekshirganimizdan keyin yoqiladi.\nTo‘lov yordami: /paysupport', '🕒 Файлы сервера удаляются через 24 часа; копии в Telegram остаются в чате.\n✨ Для ИИ-документов мы храним ваше описание и результат 30 дней, чтобы команда могла проверять качество и предотвращать злоупотребления; затем они удаляются.\n💳 Тариф включается после того, как мы проверим ваш перевод на карту.\nПомощь с оплатой: /paysupport'),
    'settings': ('⚙️ Task options', '⚙️ Vazifa sozlamalari', '⚙️ Настройки задачи'),
    'done_button': ('✅ Review & start', '✅ Tekshirish va boshlash', '✅ Проверить и начать'),
    'back': ('← Back', '← Orqaga', '← Назад'),
    'next': ('🧰 More tools', '🧰 Boshqa vositalar', '🧰 Ещё инструменты'),
    'pages_hint': ('📑 Choose pages, for example: 1,3-5.', '📑 Sahifalarni tanlang, masalan: 1,3-5.', '📑 Выберите страницы, например: 1,3-5.'),
    'split_hint': ('✂️ Choose page groups, or save each page separately.', '✂️ Sahifa guruhlarini tanlang yoki har sahifani alohida saqlang.', '✂️ Выберите группы страниц или сохраните каждую отдельно.'),
    'reorder_hint': ('↕️ Set the order of all pages, for example: 3,1,2.', '↕️ Barcha sahifalar tartibini yozing, masalan: 3,1,2.', '↕️ Задайте порядок всех страниц, например: 3,1,2.'),
    'merge_hint': ('↕️ Files merge in the order shown. You can change it below.', '↕️ Fayllar shu tartibda birlashadi. Quyida o‘zgartirishingiz mumkin.', '↕️ Файлы объединятся в указанном порядке. Его можно изменить ниже.'),
    'image_hint': ('⚙️ Adjust the paper, orientation or margins if needed.', '⚙️ Kerak bo‘lsa qog‘oz, yo‘nalish yoki hoshiyani sozlang.', '⚙️ При желании настройте бумагу, ориентацию и поля.'),
    'secure': ('🔒 Enter PDF passwords only in the web app. Please don’t send them here.', '🔒 PDF parollarini faqat veb ilovada kiriting. Bu chatga yubormang.', '🔒 Вводите пароли PDF только на сайте. Не отправляйте их сюда.'),
    'rotate_label': ('Rotation', 'Aylantirish', 'Поворот'),
    'format_label': ('Image format', 'Rasm formati', 'Формат изображения'),
    'paper_label': ('Paper size', 'Qog‘oz o‘lchami', 'Размер бумаги'),
    'portrait': ('↕️ Portrait', '↕️ Tik', '↕️ Книжная'),
    'landscape': ('↔️ Landscape', '↔️ Yotiq', '↔️ Альбомная'),
    'auto': ('✨ Auto', '✨ Avtomatik', '✨ Авто'),
    'expires': ('Valid until', 'Amal qiladi', 'Действует до'),
    'parameters': ('Options', 'Sozlamalar', 'Настройки'),
    'add': ('📎 Add to this task', '📎 Shu vazifaga qo‘shish', '📎 Добавить к задаче'),
    'new': ('➕ New task', '➕ Yangi vazifa', '➕ Новая задача'),
    'new_file': ('📎 Add this file to your draft, or start fresh?', '📎 Faylni qoralamaga qo‘shamizmi yoki yangidan boshlaymizmi?', '📎 Добавить файл к черновику или начать заново?'),
    'controls_expired': ('That button is from an earlier step. Continue your task or open the menu.', 'Bu tugma oldingi bosqichdan qolgan. Vazifani davom ettiring yoki menyuni oching.', 'Эта кнопка из прошлого шага. Продолжите задачу или откройте меню.'),
    'stale_button': ('That button was from an earlier step, so here is the menu.', 'Bu tugma oldingi bosqichdan qolgan edi, mana menyu.', 'Эта кнопка была из прошлого шага, поэтому вот меню.'),
    'stale_reply': ('It has been a while since that question, so let’s start from the menu.', 'O‘sha savoldan beri ancha vaqt o‘tdi, keling, menyudan boshlaymiz.', 'С того вопроса прошло время, давайте начнём с меню.'),
    'no_preview': ('A preview isn’t available. You can still process the file.', 'Ko‘rib chiqish imkoni yo‘q. Fayl bilan ishlashni davom ettirishingiz mumkin.', 'Предпросмотр недоступен. Файл всё равно можно обработать.'),
    'preview': ('👁 Preview page 1', '👁 1-sahifani ko‘rish', '👁 Посмотреть страницу 1'),
    'link_login': ('🔗 Connect Telegram to your existing PDF Master account? Approve only if you started this in account settings:', '🔗 Telegramni mavjud PDF Master hisobingizga ulaymizmi? Faqat hisob sozlamalarida o‘zingiz boshlagan bo‘lsangiz, tasdiqlang:', '🔗 Подключить Telegram к вашему аккаунту PDF Master? Подтверждайте, только если вы начали это в настройках аккаунта:'),
    'link_confirm': ('🔗 Connect Telegram', '🔗 Telegramni ulash', '🔗 Подключить Telegram'),
    'link_approved': ('✅ Telegram approved. Return to the same browser to finish linking.', '✅ Telegram tasdiqlandi. Ulashni tugatish uchun o‘sha brauzerga qayting.', '✅ Telegram подтверждён. Вернитесь в тот же браузер, чтобы завершить привязку.'),
}

PROMPT_EXAMPLES = {
    'ai.pdf_topic': (
        ('I need a 10 page university assignment on the history of trade routes through Bukhara. Academic tone, each section under a clear heading.',
         'Universitetga mustaqil ish kerak: Buxoro savdo yo‘llari tarixi, 10 sahifa. Ilmiy uslubda yozing, har bo‘lim aniq sarlavha ostida bo‘lsin.',
         'Нужна самостоятельная работа для университета: история торговых путей Бухары, 10 страниц. Академическим стилем, каждый раздел под ясным заголовком.'),
        ('A 3 page guide for the new waiters at my cafe: greeting a guest, taking an order, what to do about a complaint. Friendly but clear.',
         'Kafemdagi yangi ofitsiantlar uchun 3 sahifalik qo‘llanma yozib bering: mijozni kutib olish, buyurtma olish, shikoyat bo‘lsa nima qilish. Do‘stona, lekin aniq.',
         'Напишите инструкцию на 3 страницы для новых официантов в моём кафе: встретить гостя, принять заказ, что делать при жалобе. Дружелюбно, но ясно.'),
        ('A 4 page handout for my year 7 biology lesson on cell structure. Keep it plain, one example on every page, 5 quiz questions at the end.',
         '7-sinf biologiya darsiga 4 sahifalik tarqatma tayyorlab bering — hujayra tuzilishi haqida. Sodda tilda bo‘lsin, har sahifada bitta misol, oxirida 5 ta test savoli.',
         'Сделайте раздатку на 4 страницы для урока биологии в 7 классе — о строении клетки. Простым языком, на каждой странице пример, в конце 5 тестовых вопросов.'),
    ),
    'ai.pptx': (
        ('10 slides for an open lesson — year 9 geography, the shrinking of the Aral Sea. Explain each point with an example, 5 questions at the end. Make it look good, in navy.',
         'Ochiq darsga 10 ta slayd kerak — 9-sinf geografiya, Orol dengizi muammosi. Har slaydda tushuntirish va misol, oxirida 5 ta savol. Ko‘k rangda chiroyli chiqsin.',
         'Нужно 10 слайдов для открытого урока — география, 9 класс, проблема Аральского моря. С пояснениями и примерами, 5 вопросов в конце. В синем, чтобы выглядело красиво.'),
        ('6 slides pitching my online shop to investors: the problem, the solution, the market, the numbers, the ask. Confident, no jargon.',
         'Investorlarga online do‘konim haqida 6 ta slayd: muammo, yechim, bozor, raqamlar, nima so‘rayotganim. Ishonchli ohangda, jargonsiz.',
         '6 слайдов о моём интернет-магазине для инвесторов: проблема, решение, рынок, цифры, запрос. Уверенно, без жаргона.'),
        ('7 slides for the monthly meeting: the sales figures, what went well, what slipped, the plan for next month. Show the sales as a chart.',
         'Oylik yig‘ilishga 7 ta slayd: sotuv raqamlari, nima yaxshi ketdi, nima oqsadi, keyingi oy rejasi. Sotuvni diagramma qilib ko‘rsating.',
         '7 слайдов для месячного собрания: цифры продаж, что получилось, что нет, план на следующий месяц. Продажи покажите диаграммой.'),
    ),
    # A CV is described, not sized: these name no page count. Everyone in them
    # is made up, with example.com addresses and the sample number.
    'ai.cv': (
        ('Kamila Yusupova\nMarketing manager in Tashkent, looking for a head of marketing role. Email kamila.yusupova@example.com. Since 03.2021 marketing manager at Bahor Foods: launched the online shop and grew online sales by 40% in two years; I lead a team of five. 2018–2021 SMM specialist at the Bright Media agency, running campaigns for 12 brands. Bachelor’s in marketing, Tashkent State University of Economics, 2014–2018. Skills: brand strategy, Google Ads, Meta Ads, Google Analytics, copywriting. Languages: Uzbek (native), Russian (fluent), English (IELTS 7.0).',
         'Kamila Yusupova\nToshkentda marketing menejeriman, marketing bo‘limi rahbari lavozimiga ish izlayapman. Email: kamila.yusupova@example.com. 2021-yil martdan beri Bahor Foods kompaniyasida marketing menejeri: onlayn do‘konni ishga tushirdim, ikki yilda onlayn savdoni 40% ga oshirdim, besh kishilik jamoaga rahbarlik qilaman. 2018–2021-yillarda Bright Media agentligida SMM mutaxassisi bo‘lib, 12 ta brendning reklama kampaniyalarini olib borganman. Toshkent davlat iqtisodiyot universiteti, marketing yo‘nalishi bo‘yicha bakalavr, 2014–2018. Ko‘nikmalar: brend strategiyasi, Google Ads, Meta Ads, Google Analytics, kopirayting. Tillar: o‘zbek (ona tili), rus (erkin), ingliz (IELTS 7.0).',
         'Камила Юсупова\nМаркетолог из Ташкента, ищу должность руководителя отдела маркетинга. Почта: kamila.yusupova@example.com. С марта 2021 года — менеджер по маркетингу в Bahor Foods: запустила интернет-магазин, за два года увеличила онлайн-продажи на 40%, руковожу командой из пяти человек. 2018–2021 — SMM-специалист в агентстве Bright Media, вела рекламные кампании 12 брендов. Ташкентский государственный экономический университет, бакалавр по маркетингу, 2014–2018. Навыки: стратегия бренда, Google Ads, Meta Ads, Google Analytics, копирайтинг. Языки: узбекский (родной), русский (свободно), английский (IELTS 7.0).'),
        ('Jasur Toshmatov\nJunior backend developer from Samarkand, open to remote work. Email jasur.toshmatov@example.com. BSc in Computer Science, Samarkand State University, 2021–2025; final project: a booking system for guesthouses, built with Django. Internship at a software studio in summer 2024: wrote REST endpoints and unit tests, fixed bugs in a payments service. Skills: Python, Django, PostgreSQL, Docker, Git, Linux. Certificate: CS50x, Harvard, 2023. Languages: Uzbek, Russian, English (B2).',
         'Jasur Toshmatov\nSamarqandlik yosh backend dasturchiman, masofaviy ishga ham tayyorman. Email: jasur.toshmatov@example.com. Samarqand davlat universiteti, kompyuter ilmlari bo‘yicha bakalavr, 2021–2025; bitiruv ishim — mehmon uylari uchun bron qilish tizimi (Django). 2024-yil yozida dasturlash studiyasida amaliyot o‘taganman: REST endpointlar va unit testlar yozdim, to‘lov xizmatidagi xatolarni tuzatdim. Ko‘nikmalar: Python, Django, PostgreSQL, Docker, Git, Linux. Sertifikat: CS50x, Harvard, 2023. Tillar: o‘zbek, rus, ingliz (B2).',
         'Жасур Тошматов\nНачинающий backend-разработчик из Самарканда, готов к удалённой работе. Почта: jasur.toshmatov@example.com. Самаркандский государственный университет, бакалавр по информатике, 2021–2025; дипломный проект — система бронирования для гостевых домов на Django. Летом 2024 года стажировался в студии разработки: писал REST-эндпоинты и юнит-тесты, исправлял ошибки в платёжном сервисе. Навыки: Python, Django, PostgreSQL, Docker, Git, Linux. Сертификат: CS50x, Harvard, 2023. Языки: узбекский, русский, английский (B2).'),
        ('Malika Ergasheva\nNurse in Bukhara, looking for a ward nurse job in a private clinic. Email malika.ergasheva@example.com. Since 09.2019 nurse in the cardiology ward of the Bukhara regional hospital: patient care, injections and IV drips, ECGs, training new nurses. 2017–2019 nurse at a family clinic. Diploma in nursing, Bukhara Medical College, 2014–2017. Certificates: Basic Life Support (2023), an infection control course (2022). Languages: Uzbek, Russian, English (A2).',
         'Malika Ergasheva\nBuxorodagi hamshiraman, xususiy klinikada palata hamshirasi bo‘lib ishlamoqchiman. Email: malika.ergasheva@example.com. 2019-yil sentabrdan Buxoro viloyat shifoxonasining kardiologiya bo‘limida hamshiraman: bemorlarni parvarish qilish, ukol va tomchi dori qo‘yish, EKG olish, yangi hamshiralarni o‘rgatish. 2017–2019-yillarda oilaviy poliklinikada hamshira bo‘lib ishlaganman. Buxoro tibbiyot kolleji, hamshiralik ishi, 2014–2017. Sertifikatlar: Basic Life Support (2023), infeksiya nazorati kursi (2022). Tillar: o‘zbek, rus, ingliz (A2).',
         'Малика Эргашева\nМедсестра из Бухары, ищу работу палатной медсестрой в частной клинике. Почта: malika.ergasheva@example.com. С сентября 2019 года — медсестра кардиологического отделения Бухарской областной больницы: уход за пациентами, уколы и капельницы, снятие ЭКГ, обучение новых медсестёр. 2017–2019 — медсестра в семейной поликлинике. Бухарский медицинский колледж, сестринское дело, 2014–2017. Сертификаты: Basic Life Support (2023), курс по инфекционному контролю (2022). Языки: узбекский, русский, английский (A2).'),
    ),
}

TOOL_LABELS = {
    'pdf.merge': ('📑 Merge PDFs', '📑 PDF birlashtirish', '📑 Объединить PDF'),
    'pdf.compress': ('🗜 Compress PDF', '🗜 PDF hajmini kamaytirish', '🗜 Сжать PDF'),
    'pdf.split': ('✂️ Split PDF', '✂️ PDF bo‘lish', '✂️ Разделить PDF'),
    'pdf.extract_pages': ('📑 Extract pages', '📑 Sahifalarni ajratish', '📑 Извлечь страницы'),
    'pdf.delete_pages': ('🗑 Delete pages', '🗑 Sahifalarni o‘chirish', '🗑 Удалить страницы'),
    'pdf.reorder': ('↕️ Reorder pages', '↕️ Sahifalar tartibi', '↕️ Порядок страниц'),
    'pdf.rotate': ('🔄 Rotate pages', '🔄 Sahifalarni aylantirish', '🔄 Повернуть страницы'),
    'pdf.images_to_pdf': ('🖼 PDF from images', '🖼 Rasmlardan PDF', '🖼 PDF из фото'),
    'pdf.to_images': ('🖼 PDF → images', '🖼 PDF → rasmlar', '🖼 PDF → изображения'),
    'convert.word_to_pdf': ('📝 Word → PDF', '📝 Word → PDF', '📝 Word → PDF'),
    'convert.pptx_to_pdf': ('📊 PowerPoint → PDF', '📊 PowerPoint → PDF', '📊 PowerPoint → PDF'),
    # The three AI services. Names are kept in step with the web app's locales.
    'ai.pdf_topic': ('✨ PDF on a topic · AI', '✨ Mavzuga oid PDF · AI', '✨ PDF по теме · ИИ'),
    'ai.pptx': ('✨ Slides on a topic · AI', '✨ Mavzuga oid Slayd · AI', '✨ Слайды по теме · ИИ'),
    'ai.cv': ('✨ CV · AI', '✨ CV (rezyume) · AI', '✨ Резюме · ИИ'),
}

UX = {locale: {key: values[index] for key, values in MESSAGES.items()} for index, locale in enumerate(LOCALES)}

# A count of pages or slides in each language's own plural forms, for the
# review stepper's middle button: "10 slides", "10 slayd", "10 слайдов".
COUNT_FORMS = {
    'en': {'page': ('page', 'pages'), 'slide': ('slide', 'slides'), 'photo': ('photo', 'photos'), 'file': ('file', 'files')},
    'uz': {'page': ('sahifa',), 'slide': ('slayd',), 'photo': ('ta rasm',), 'file': ('ta fayl',)},
    'ru': {'page': ('страница', 'страницы', 'страниц'), 'slide': ('слайд', 'слайда', 'слайдов'),
           'photo': ('фото', 'фото', 'фото'), 'file': ('файл', 'файла', 'файлов')},
}


def counted(locale, count, unit):
    forms = COUNT_FORMS.get(locale, COUNT_FORMS['en'])[unit]
    if len(forms) == 1:
        form = forms[0]
    elif len(forms) == 2:
        form = forms[0] if count == 1 else forms[1]
    elif count % 10 == 1 and count % 100 != 11:
        form = forms[0]
    elif 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        form = forms[1]
    else:
        form = forms[2]
    return f'{count} {form}'
LEGACY_COPY = {locale: {key: values[index] for key, values in LEGACY_MESSAGES.items()} for index, locale in enumerate(LOCALES)}
TOOL_NAMES = {key: dict(zip(LOCALES, labels)) for key, labels in TOOL_LABELS.items()}
STATUS = {
    'en': {'queued': '⏳ Queued', 'running': '⚙️ Processing', 'finalizing': '📦 Finishing', 'succeeded': '✅ Ready', 'failed': '⚠️ Couldn’t finish', 'canceled': '✖️ Cancelled', 'expired': '⌛ Expired', 'no_op': '✅ No change'},
    'uz': {'queued': '⏳ Navbatda', 'running': '⚙️ Tayyorlanmoqda', 'finalizing': '📦 Yakunlanmoqda', 'succeeded': '✅ Tayyor', 'failed': '⚠️ Bajarilmadi', 'canceled': '✖️ Bekor qilindi', 'expired': '⌛ Muddati tugagan', 'no_op': '✅ O‘zgarish yo‘q'},
    'ru': {'queued': '⏳ В очереди', 'running': '⚙️ Обработка', 'finalizing': '📦 Завершение', 'succeeded': '✅ Готово', 'failed': '⚠️ Не удалось завершить', 'canceled': '✖️ Отменено', 'expired': '⌛ Срок истёк', 'no_op': '✅ Без изменений'},
}
