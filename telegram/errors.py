"""Short bot recovery messages; API codes and web error copy stay unchanged.

Never interpolate exception details, filenames, credentials, or payment data.
Codes with the same recovery instruction share copy, not application behavior.
"""
from apps.core.errors import cv_reading_ahead, error_data, page_limit_count


MESSAGES = {
    'invalid_request invalid_operation method_not_allowed idempotency_key_required': (
        '⚠️ That didn’t work. Open the menu and try again.',
        '⚠️ Amal bajarilmadi. Menyuni ochib, qayta urinib ko‘ring.',
        '⚠️ Не получилось. Откройте меню и попробуйте снова.',
    ),
    'authentication_required': (
        '🔒 Sign in to continue.', '🔒 Davom etish uchun hisobga kiring.', '🔒 Войдите, чтобы продолжить.',
    ),
    # Sizes and page counts are the same on every plan, so another plan is no
    # way past them and these never offer one.
    'file_too_large file_size_limit': (
        '📦 This file is too large. Send a smaller file.',
        '📦 Fayl juda katta. Kichikroq fayl yuboring.',
        '📦 Файл слишком большой. Отправьте файл поменьше.',
    ),
    # One file longer than any task may be, refused as it is uploaded: no tool
    # takes it, our Split PDF included, so it is split before uploading.
    # {limit} is the real figure, filled in by bot_error.
    'page_limit': (
        '📄 This file has more than {limit} pages. Split it into smaller files before you upload it.',
        '📄 Bu faylda {limit} sahifadan ko‘p. Yuklashdan oldin uni kichikroq fayllarga bo‘lib oling.',
        '📄 В этом файле больше {limit} страниц. Перед загрузкой разделите его на файлы поменьше.',
    ),
    # A task's files together, each of them fine on its own.
    'page_limit_exceeded': (
        '📄 Too many pages for one task. Remove a file or choose fewer pages.',
        '📄 Bitta vazifa uchun sahifalar juda ko‘p. Bitta faylni olib tashlang yoki kamroq sahifa tanlang.',
        '📄 Слишком много страниц для одной задачи. Уберите файл или выберите меньше страниц.',
    ),
    'file_unavailable not_found permission_denied': (
        '⚠️ This item isn’t available. Open your recent tasks or start again.',
        '⚠️ Bu element mavjud emas. So‘nggi vazifalarni oching yoki qayta boshlang.',
        '⚠️ Этот элемент недоступен. Откройте последние задачи или начните заново.',
    ),
    'file_expired': (
        '⌛ This file has expired. Send it again.',
        '⌛ Faylning muddati tugagan. Uni qayta yuboring.',
        '⌛ Срок хранения файла истёк. Отправьте его снова.',
    ),
    'file_changed': (
        '⚠️ This file has changed. Send it again to continue.',
        '⚠️ Fayl o‘zgargan. Davom etish uchun qayta yuboring.',
        '⚠️ Файл изменился. Отправьте его снова.',
    ),
    'file_required': (
        '📎 Send a file first.', '📎 Avval fayl yuboring.', '📎 Сначала отправьте файл.',
    ),
    'invalid_pages': (
        '📄 Check the page numbers. Use pages in this file without repeats, like 1,3-5.',
        '📄 Sahifa raqamlarini tekshiring. Fayldagi sahifalarni takrorsiz yozing, masalan: 1,3-5.',
        '📄 Проверьте номера страниц. Укажите страницы файла без повторов, например: 1,3-5.',
    ),
    'invalid_parameters invalid_inputs invalid_mode': (
        '⚠️ Check the settings and try again.',
        '⚠️ Sozlamalarni tekshirib, qayta urinib ko‘ring.',
        '⚠️ Проверьте настройки и попробуйте снова.',
    ),
    'processing_failed processor_failed conversion_failed invalid_output output_invalid empty_output output_directory_not_empty': (
        '⚠️ Couldn’t process this file. Try again or send another file.',
        '⚠️ Faylni qayta ishlay olmadik. Qayta urining yoki boshqa fayl yuboring.',
        '⚠️ Не удалось обработать файл. Попробуйте снова или отправьте другой.',
    ),
    # The bot follows this with its own advice and a Retry button, so it does
    # not say "try again" itself. It must keep saying the document was not
    # counted: the notice leaves out its own line when it does (notifications.py).
    # It comes under a "⚠️ Couldn’t finish" header, for a deck or a document,
    # so it carries neither the sign again nor a noun.
    'provider_failed': (
        'The AI didn’t manage it this time. It doesn’t count towards your limits.',
        'AI bu safar uddalay olmadi. Bu limitingizga hisoblanmaydi.',
        'ИИ на этот раз не справился. В лимиты это не засчитывается.',
    ),
    'processor_timeout worker_interrupted': (
        '⏳ Processing stopped before it finished. Please try again.',
        '⏳ Qayta ishlash oxiriga yetmadi. Qayta urinib ko‘ring.',
        '⏳ Обработка прервалась. Попробуйте ещё раз.',
    ),
    'password_required password_invalid password_expired unlock_first secure_password_entry_required': (
        '🔒 Open the web app to enter the PDF password. Don’t send passwords in chat.',
        '🔒 PDF parolini veb ilovada kiriting. Parolni chatga yubormang.',
        '🔒 Введите пароль PDF на сайте. Не отправляйте пароли в чат.',
    ),
    # Every plan has every tool, so a tool held back is never a reason to
    # change plan: should one be refused, it is said like one switched off.
    'feature_unavailable engine_unavailable conversion_preflight_unavailable feature_not_in_plan': (
        '🛠 This tool isn’t available right now. Try again later.',
        '🛠 Bu vosita hozir ishlamayapti. Keyinroq urinib ko‘ring.',
        '🛠 Этот инструмент сейчас недоступен. Попробуйте позже.',
    ),
    'checkout_disabled sandbox_disabled': (
        '⭐ Payments aren’t available right now. Your current plan still works.',
        '⭐ To‘lovlar hozir mavjud emas. Joriy tarifingiz ishlashda davom etadi.',
        '⭐ Оплата сейчас недоступна. Текущий тариф продолжает работать.',
    ),
    'csrf_failed session_changed': (
        '🔒 Your session changed. Sign in on the web again and restart this action.',
        '🔒 Seans o‘zgargan. Veb ilovaga qayta kirib, amalni boshidan boshlang.',
        '🔒 Сеанс изменился. Войдите на сайте снова и повторите действие.',
    ),
    'telegram_not_configured': (
        '🛠 Telegram sign-in isn’t ready yet. Please try again later.',
        '🛠 Telegram orqali kirish hali tayyor emas. Keyinroq urinib ko‘ring.',
        '🛠 Вход через Telegram ещё не настроен. Попробуйте позже.',
    ),
    'challenge_expired': (
        '⌛ This sign-in link expired. Start again in your browser.',
        '⌛ Kirish havolasi eskirgan. Brauzerda qayta boshlang.',
        '⌛ Ссылка для входа устарела. Начните заново в браузере.',
    ),
    'challenge_pending': (
        '🔒 Confirm the sign-in request here first.',
        '🔒 Avval shu yerda kirish so‘rovini tasdiqlang.',
        '🔒 Сначала подтвердите запрос на вход здесь.',
    ),
    'auth_replayed': (
        '🔒 This sign-in request was already used. Start a new one in your browser.',
        '🔒 Bu kirish so‘rovi ishlatilgan. Brauzerda yangisini boshlang.',
        '🔒 Этот запрос на вход уже использован. Начните новый в браузере.',
    ),
    'invalid_telegram_data': (
        '🔒 Couldn’t verify this Telegram request. Start again in your browser.',
        '🔒 Telegram so‘rovini tasdiqlay olmadik. Brauzerda qayta boshlang.',
        '🔒 Не удалось проверить запрос Telegram. Начните заново в браузере.',
    ),
    'concurrency_limit': (
        '⏳ Another task is still running. Try when it finishes.',
        '⏳ Boshqa vazifa bajarilmoqda. Tugagach, qayta urinib ko‘ring.',
        '⏳ Другая задача ещё выполняется. Дождитесь её завершения.',
    ),
    'job_already_running quote_already_submitted': (
        '⏳ This task has already started. Check Recent tasks for its status.',
        '⏳ Bu vazifa allaqachon boshlangan. Holatini So‘nggi vazifalarda ko‘ring.',
        '⏳ Эта задача уже запущена. Проверьте её в последних задачах.',
    ),
    'quote_expired': (
        '⌛ This estimate expired. Review the task again before running it.',
        '⌛ Hisob-kitob eskirgan. Boshlashdan oldin vazifani qayta tekshiring.',
        '⌛ Расчёт устарел. Проверьте задачу ещё раз перед запуском.',
    ),
    'quote_required confirmation_required': (
        '🧾 Review the task before running it.',
        '🧾 Boshlashdan oldin vazifani tekshiring.',
        '🧾 Проверьте задачу перед запуском.',
    ),
    'quote_policy_changed provider_changed': (
        '🧾 This task needs a fresh look. Review it again before running.',
        '🧾 Vazifani qayta ko‘rib chiqish kerak. Boshlashdan oldin yana bir bor tekshiring.',
        '🧾 Задачу нужно проверить заново. Посмотрите её ещё раз перед запуском.',
    ),
    'idempotency_conflict controls_expired version_conflict': (
        '⌛ These buttons are out of date. Open the current task from the menu.',
        '⌛ Bu tugmalar eskirgan. Joriy vazifani menyudan oching.',
        '⌛ Эти кнопки устарели. Откройте текущую задачу из меню.',
    ),
    'merge_needs_two_files': (
        '📎 Send at least 2 PDFs to merge.',
        '📎 Birlashtirish uchun kamida 2 ta PDF yuboring.',
        '📎 Отправьте хотя бы 2 PDF для объединения.',
    ),
    'unsupported_file unsupported_type invalid_content_type': (
        '📎 This file type isn’t supported here. Send a PDF, image, DOCX or PPTX.',
        '📎 Bu fayl turi qo‘llanmaydi. PDF, rasm, DOCX yoki PPTX yuboring.',
        '📎 Этот тип файла не поддерживается. Отправьте PDF, изображение, DOCX или PPTX.',
    ),
    'invalid_pdf invalid_file invalid_image invalid_archive': (
        '⚠️ Couldn’t read this file. Check that it opens, then send it again.',
        '⚠️ Faylni o‘qiy olmadik. Ochilishini tekshirib, qayta yuboring.',
        '⚠️ Не удалось прочитать файл. Проверьте, что он открывается, и отправьте снова.',
    ),
    'bot_transport_limit': (
        '📦 Telegram can only send us files up to 20 MB. Upload this one in the web app.',
        '📦 Telegram bizga 20 MB gacha fayl uzata oladi. Bu faylni veb ilovada yuklang.',
        '📦 Telegram передаёт нам файлы до 20 МБ. Загрузите этот файл на сайте.',
    ),
    'rate_limited': (
        '⏳ A little too fast. Please try again shortly.',
        '⏳ So‘rovlar ko‘payib ketdi. Birozdan keyin urinib ko‘ring.',
        '⏳ Слишком много запросов. Попробуйте чуть позже.',
    ),
    'unsafe_archive unsafe_path active_content_unsupported external_content_unsupported': (
        '🔒 This file contains content we can’t safely process. Try a clean copy.',
        '🔒 Fayl tarkibini xavfsiz qayta ishlay olmaymiz. Toza nusxasini yuboring.',
        '🔒 Содержимое файла нельзя безопасно обработать. Попробуйте чистую копию.',
    ),
    'interactive_pdf_unsupported': (
        '📄 This tool can’t handle the PDF’s interactive content. Use a plain copy.',
        '📄 Vosita bu PDF’ning interaktiv tarkibini qayta ishlay olmaydi. Oddiy nusxasini yuboring.',
        '📄 Инструмент не поддерживает интерактивное содержимое PDF. Нужна обычная копия.',
    ),
    'render_pixel_limit image_pixel_limit page_dimensions_invalid': (
        '📐 The page or image is too large to process. Try a smaller version.',
        '📐 Sahifa yoki rasm qayta ishlash uchun juda katta. Kichikroq nusxani yuboring.',
        '📐 Страница или изображение слишком большое. Попробуйте уменьшенную версию.',
    ),
    'output_size_limit processor_report_limit archive_limit': (
        '📦 The result exceeds processing limits. Try fewer pages or smaller files.',
        '📦 Natija qayta ishlash limitidan oshdi. Kamroq sahifa yoki kichikroq fayl bilan urining.',
        '📦 Результат превышает лимиты обработки. Возьмите меньше страниц или файлы поменьше.',
    ),
    'aggregate_size_exceeded': (
        '📦 These files are too large together. Remove a file or use smaller copies.',
        '📦 Fayllarning umumiy hajmi juda katta. Bittasini olib tashlang yoki kichikroq nusxalar yuboring.',
        '📦 Общий размер файлов слишком велик. Уберите файл или возьмите копии поменьше.',
    ),
    'input_count_exceeded': (
        '📎 Too many files for one task. Remove some and try again.',
        '📎 Bitta vazifa uchun fayllar juda ko‘p. Ba’zilarini olib tashlang.',
        '📎 Слишком много файлов для одной задачи. Уберите часть и попробуйте снова.',
    ),
    'file_in_use': (
        '⏳ This file is in use. Wait for its task to finish.',
        '⏳ Fayl hozir ishlatilmoqda. Vazifa tugashini kuting.',
        '⏳ Этот файл сейчас используется. Дождитесь завершения задачи.',
    ),
    'not_encrypted': (
        '🔓 This PDF isn’t password-protected. No need to unlock it.',
        '🔓 Bu PDF parol bilan himoyalanmagan. Qulfini ochish shart emas.',
        '🔓 У этого PDF нет пароля. Разблокировка не нужна.',
    ),
    'preview_unavailable': (
        '👀 No preview for this file. You can still use the other task controls.',
        '👀 Bu faylni oldindan ko‘rib bo‘lmaydi. Boshqa tugmalardan foydalanishingiz mumkin.',
        '👀 Предпросмотр недоступен. Остальные действия с задачей доступны.',
    ),
    'identity_already_linked': (
        '🔒 This login belongs to another account. Sign in to that account to manage its logins.',
        '🔒 Bu kirish usuli boshqa hisobga ulangan. Uni boshqarish uchun o‘sha hisobga kiring.',
        '🔒 Этот способ входа привязан к другому аккаунту. Войдите в него для управления входом.',
    ),
    'telegram_already_linked': (
        '🔗 Telegram is already linked to this account.',
        '🔗 Telegram bu hisobga allaqachon ulangan.',
        '🔗 Telegram уже привязан к этому аккаунту.',
    ),
    'telegram_link_required': (
        '🔗 First connect Telegram in the web app’s account settings.',
        '🔗 Avval veb ilovadagi hisob sozlamalarida Telegramni ulang.',
        '🔗 Сначала подключите Telegram в настройках аккаунта на сайте.',
    ),
    'invalid_plan': (
        '⭐ Choose an available plan in Plans.',
        '⭐ Tariflardan mavjud tarifni tanlang.',
        '⭐ Выберите доступный тариф в разделе «Тарифы».',
    ),
    'invalid_referral': (
        '⚠️ This invite link isn’t valid. You can still use the bot from the menu.',
        '⚠️ Taklif havolasi yaroqsiz. Botdan menyu orqali foydalanishingiz mumkin.',
        '⚠️ Приглашение недействительно. Бот по-прежнему доступен через меню.',
    ),
    'referral_already_claimed': (
        '🔗 An invite is already applied to your account.',
        '🔗 Hisobingizga taklif allaqachon qo‘llangan.',
        '🔗 Приглашение уже применено к вашему аккаунту.',
    ),
    'referral_window_closed': (
        '⌛ The time to apply an invite has passed. You can keep using the bot.',
        '⌛ Taklifni qo‘llash muddati tugagan. Botdan foydalanishda davom etishingiz mumkin.',
        '⌛ Срок применения приглашения истёк. Можно продолжать пользоваться ботом.',
    ),
    # A used-up limit: what was used, when it comes back, and the way past it.
    # {limit} and {when} are filled in by bot_error from the error itself.
    'weekly_ai_limit': (
        '⏳ This week’s AI documents are used up ({limit} a week). New ones from {when}, or choose a plan with more.',
        '⏳ Bu haftalik {limit} ta AI hujjat limitingiz tugadi. Limit yangilanadi: {when}. Ko‘proq kerak bo‘lsa, tarif tanlang.',
        '⏳ ИИ-документы на эту неделю закончились — по тарифу их {limit}. Лимит обновится: {when}. Нужно больше — выберите тариф.',
    ),
    'weekly_file_limit': (
        '⏳ This week’s file tasks are used up ({limit} a week). New ones from {when}, or choose a plan with unlimited file tools.',
        '⏳ Bu haftalik {limit} ta fayl vazifasi limitingiz tugadi. Limit yangilanadi: {when}. Cheksiz fayl vositalari uchun tarif tanlang.',
        '⏳ Задачи с файлами на эту неделю закончились — по тарифу их {limit}. Лимит обновится: {when}. Без ограничений — на другом тарифе.',
    ),
    'edit_limit': (
        '✏️ This file’s AI edits are used up ({limit} per file). Choose a plan with more edits, or make a new document.',
        '✏️ Bu fayl uchun {limit} ta AI tahrir ishlatib bo‘lindi. Ko‘proq tahrir uchun tarif tanlang yoki yangi hujjat yarating.',
        '✏️ ИИ-правки этого файла закончились — по тарифу их {limit}. Выберите тариф с большим числом правок или создайте новый документ.',
    ),
    'invalid_receipt': (
        '🧾 Send the receipt as a photo or screenshot, or as a PDF.',
        '🧾 Kvitansiyani rasm yoki skrinshot, yoxud PDF ko‘rinishida yuboring.',
        '🧾 Отправьте квитанцию фото, скриншотом или PDF-файлом.',
    ),
    'receipt_too_large': (
        '🧾 The receipt is too large. Send a screenshot under 10 MB.',
        '🧾 Kvitansiya juda katta. 10 MB dan kichik skrinshot yuboring.',
        '🧾 Квитанция слишком большая. Отправьте скриншот меньше 10 МБ.',
    ),
    'manual_payment_pending': (
        '⏳ Your previous payment is still being checked. We’ll message you here.',
        '⏳ Oldingi to‘lovingiz hali tekshirilmoqda. Natijani shu yerda yuboramiz.',
        '⏳ Предыдущий платёж ещё проверяется. Мы напишем вам здесь.',
    ),
    # A CV needs its name, a way to reach the person and a job or a school: asked for before anything is
    # made or counted. Each fact is said by its label on the bot's screens (ux_copy cv_fact_*), the same
    # words as i18n cv_missing; bot_error adds what is missing, by that label, under it.
    'cv_missing': (
        '✍️ A CV needs your full name, a phone or email, and work experience (with years) or education. Add what is missing and try again.',
        '✍️ CV uchun to‘liq ism-familiya, telefon yoki email hamda ish tajribasi (yillari bilan) yoki taʼlim kerak. Yetishmayotgan maʼlumotni qo‘shib, qayta urinib ko‘ring.',
        '✍️ Для резюме нужны имя и фамилия, телефон или почта, а также опыт работы (с годами) или образование. Добавьте недостающее и попробуйте снова.',
    ),
    # A CV made from a LinkedIn profile or an old CV needs the file, one we can read, of a kind it takes.
    'cv_file_required': (
        '📎 Send the file to make the CV from: your old CV (PDF, Word or photos) or your LinkedIn profile saved as a PDF.',
        '📎 CV tayyorlash uchun faylni yuboring: eski CV (PDF, Word yoki rasm) yoki PDF qilib saqlangan LinkedIn profilingiz.',
        '📎 Пришлите файл, из которого составить резюме: старое резюме (PDF, Word или фото) или профиль LinkedIn, сохранённый в PDF.',
    ),
    'cv_file_unreadable': (
        '🔍 We couldn’t read any text in this file. Send a clearer photo or scan, or a PDF without a password.',
        '🔍 Fayldagi matnni o‘qib bo‘lmadi. Aniqroq rasm yoki skan, yoxud parolsiz PDF yuboring.',
        '🔍 Не удалось прочитать текст в файле. Пришлите более чёткое фото или скан либо PDF без пароля.',
    ),
    'cv_file_kind': (
        '📄 This file can’t be used here. Send a PDF, a Word file (.docx) or photos; for LinkedIn, the profile saved as a PDF or screenshots.',
        '📄 Bu faylni ishlatib bo‘lmaydi. PDF, Word (.docx) yoki rasm yuboring; LinkedIn uchun PDF qilib saqlangan profil yoki skrinshotlar.',
        '📄 Этот файл не подходит. Пришлите PDF, файл Word (.docx) или фото; для LinkedIn — профиль в PDF или скриншоты.',
    ),
    # LinkedIn needs a sign-in and forbids reading its pages: its own PDF export, or screenshots.
    'cv_linkedin_link': (
        '🔗 We can’t open LinkedIn links. On a computer, open your profile, choose More → Save to PDF and send the file here; on a phone, do the same with the browser’s desktop site on, or send screenshots of your profile.',
        '🔗 LinkedIn havolalarini ocha olmaymiz. Kompyuterda profilingizni oching, More → Save to PDF ni bosing va faylni shu yerga yuboring; telefonda brauzerda «Kompyuter versiyasi»ni yoqib, xuddi shunday qiling yoki profil skrinshotlarini yuboring.',
        '🔗 Ссылки LinkedIn мы открыть не можем. На компьютере откройте профиль, нажмите «Ещё» → «Сохранить в формате PDF» и пришлите файл сюда; на телефоне сделайте то же, включив в браузере «Версию для ПК», или пришлите скриншоты профиля.',
    ),
    # A CV's files wait their turn to be read (apps/studio/cv/reads.py): how
    # many reads are ahead, never "try again". {ahead} is filled in by bot_error;
    # with none ahead, the files are being read now. The chat itself waits on
    # one message that becomes the review (telegram/bot.py cv_wait_start).
    'cv_reading': (
        '⏳ Your files are in the queue to be read — {ahead} ahead of them. This takes a moment; we’ll continue as soon as they’re read.',
        '⏳ Fayllaringiz o‘qish navbatida: oldinda {ahead} ta fayl bor. Bu ko‘p vaqt olmaydi — o‘qib bo‘lishimiz bilan davom etamiz.',
        '⏳ Ваши файлы в очереди на чтение, перед ними ещё {ahead}. Это недолго — продолжим, как только они будут прочитаны.',
    ),
    'cv_reading_now': (
        '⏳ Your files are being read. This takes a moment; we’ll continue as soon as they’re read.',
        '⏳ Fayllaringizni o‘qiyapmiz. Bu ko‘p vaqt olmaydi — o‘qib bo‘lishimiz bilan davom etamiz.',
        '⏳ Читаем ваши файлы. Это недолго — продолжим, как только они будут прочитаны.',
    ),
    'manual_payment_closed manual_payment_expired': (
        '⌛ This payment is closed. Open Plans to start a new one: /plans',
        '⌛ Bu to‘lov yopilgan. Yangisini boshlash uchun tariflarni oching: /plans',
        '⌛ Этот платёж закрыт. Откройте тарифы, чтобы начать новый: /plans',
    ),
}

LIMITS = ('weekly_ai_limit', 'weekly_file_limit', 'edit_limit')
COPY = {
    locale: {code: values[index] for codes, values in MESSAGES.items() for code in codes.split()}
    for index, locale in enumerate(('en', 'uz', 'ru'))
}


# When a week starts again, for a reader whose own clock is not known
# (telegram/clock.py week_reset): most bot customers never open the web app.
WEEK_START = {'en': 'Monday 00:00, Tashkent time', 'uz': 'dushanba 00:00, Toshkent vaqti',
              'ru': 'понедельник 00:00 по Ташкенту'}


def _limit_text(error, locale, account):
    """A used-up limit with its numbers, or None when the error does not carry them.

    Only whole numbers and a time are put in the message, never other params.
    """
    params = error.params or {}
    numbers = {key: params.get(key) for key in ('limit', 'used')}
    if not all(type(value) is int for value in numbers.values()):
        return None
    from .clock import week_reset
    when = week_reset(account, params.get('resets_at'), locale)
    return COPY[locale][error.code].format(when=when, **numbers)


def _missing_text(error, locale):
    """What a CV lacks, said and listed by the name of each required fact it lacks.

    Only the names in apps.studio.cv.content.REQUIRED_FACTS are looked up
    (telegram/ux_copy.py cv_fact_*): whatever else the error carries is never
    echoed.
    """
    from apps.studio.cv.content import REQUIRED_FACTS
    from .ux_copy import UX
    asked = (error.params or {}).get('missing')
    asked = asked if isinstance(asked, (list, tuple)) else []
    labels = [UX[locale][f'cv_fact_{fact}'] for fact in REQUIRED_FACTS if fact in asked]
    return '\n'.join([COPY[locale]['cv_missing'], *(f'• {label}' for label in labels)])


def bot_error(error, locale='en', account=None):
    """The bot's message for an error; `account` puts a reset time on its clock."""
    locale = locale if locale in COPY else 'en'
    if error.code == 'bot_wrong_file':
        from .ux_copy import UX
        return UX[locale]['wrong_file']
    if error.code in LIMITS:
        value = _limit_text(error, locale, account)
        if value:
            return value
        return '⚠️ ' + error_data(error, locale)['message']
    if error.code == 'page_limit':
        return COPY[locale][error.code].format(limit=page_limit_count(error))
    if error.code == 'cv_missing':
        return _missing_text(error, locale)
    if error.code == 'cv_reading':
        ahead = cv_reading_ahead(error)
        return COPY[locale]['cv_reading'].format(ahead=ahead) if ahead else COPY[locale]['cv_reading_now']
    if error.code in COPY[locale]:
        return COPY[locale][error.code]
    return '⚠️ ' + error_data(error, locale)['message']
