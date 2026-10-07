"""Short bot recovery messages; API codes and web error copy stay unchanged.

Never interpolate exception details, filenames, credentials, or payment data.
Codes with the same recovery instruction share copy, not application behavior.
"""
from apps.core.errors import error_data


MESSAGES = {
    'invalid_request invalid_operation method_not_allowed idempotency_key_required': (
        '⚠️ That didn’t work. Open the menu and try again.',
        '⚠️ Amal bajarilmadi. Menyuni ochib, qayta urinib ko‘ring.',
        '⚠️ Не получилось. Откройте меню и попробуйте снова.',
    ),
    'authentication_required': (
        '🔒 Sign in to continue.', '🔒 Davom etish uchun hisobga kiring.', '🔒 Войдите, чтобы продолжить.',
    ),
    'quota_exceeded': (
        '⚠️ Not enough balance for this task. Check Plans & packs.',
        '⚠️ Bu vazifa uchun balans yetmaydi. Tariflar va paketlarni ko‘ring.',
        '⚠️ Для этой задачи не хватает лимита. Посмотрите тарифы и пакеты.',
    ),
    'file_too_large file_size_limit': (
        '📦 This file is too large for your plan. Send a smaller file or choose another plan.',
        '📦 Fayl tarifingiz uchun juda katta. Kichikroq fayl yuboring yoki boshqa tarif tanlang.',
        '📦 Файл превышает лимит тарифа. Отправьте файл поменьше или смените тариф.',
    ),
    'page_limit_exceeded page_limit': (
        '📄 Too many pages for your plan. Use fewer pages or choose another plan.',
        '📄 Sahifalar tarif limitidan oshdi. Kamroq sahifa yoki boshqa tarif tanlang.',
        '📄 Страниц больше, чем позволяет тариф. Возьмите меньше страниц или смените тариф.',
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
    'feature_unavailable engine_unavailable conversion_preflight_unavailable': (
        '🛠 This tool isn’t available right now. Try again later.',
        '🛠 Bu vosita hozir ishlamayapti. Keyinroq urinib ko‘ring.',
        '🛠 Этот инструмент сейчас недоступен. Попробуйте позже.',
    ),
    'feature_not_in_plan': (
        '⭐ This tool needs another plan. Check Plans & packs.',
        '⭐ Bu vosita uchun boshqa tarif kerak. Tariflar va paketlarni ko‘ring.',
        '⭐ Для этого инструмента нужен другой тариф. Посмотрите тарифы и пакеты.',
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
        '🧾 Review the task and its cost before running it.',
        '🧾 Boshlashdan oldin vazifa va sarflanadigan limitni tekshiring.',
        '🧾 Проверьте задачу и расход лимита перед запуском.',
    ),
    'quote_policy_changed provider_changed': (
        '🧾 The task cost may have changed. Review it again before running.',
        '🧾 Vazifa xarajati o‘zgargan bo‘lishi mumkin. Boshlashdan oldin qayta tekshiring.',
        '🧾 Стоимость задачи могла измениться. Проверьте её ещё раз.',
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
    'quote_exceeded': (
        '⚠️ This task exceeded its estimate and stopped. Review it again before retrying.',
        '⚠️ Vazifa hisoblangan limitdan oshib, to‘xtadi. Qayta urinishdan oldin tekshiring.',
        '⚠️ Задача превысила расчёт и остановилась. Проверьте её перед повтором.',
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
    'invalid_invoice payment_amount_mismatch': (
        '⚠️ Couldn’t verify this payment. Open a new checkout or use /paysupport.',
        '⚠️ To‘lovni tekshira olmadik. Yangi to‘lovni oching yoki /paysupport orqali yozing.',
        '⚠️ Не удалось проверить платёж. Начните оплату заново или напишите в /paysupport.',
    ),
    'invoice_expired': (
        '⌛ This checkout expired. Choose the offer again to pay.',
        '⌛ To‘lov havolasi eskirgan. To‘lash uchun taklifni qayta tanlang.',
        '⌛ Ссылка на оплату устарела. Выберите предложение заново.',
    ),
    'invoice_already_paid': (
        '✅ This invoice is already paid. Check your balance in Account.',
        '✅ Bu hisob allaqachon to‘langan. Balansni Hisob bo‘limida ko‘ring.',
        '✅ Этот счёт уже оплачен. Проверьте баланс в аккаунте.',
    ),
    'subscription_already_active': (
        '💳 You already have a paid plan. Manage it in Subscription.',
        '💳 Pulli tarifingiz bor. Uni Obuna bo‘limida boshqaring.',
        '💳 У вас уже есть платный тариф. Управляйте им в разделе «Подписка».',
    ),
    'subscription_invoice_pending': (
        '💳 A subscription checkout is already open. Finish it or wait for it to expire.',
        '💳 Obuna uchun to‘lov ochilgan. Uni yakunlang yoki muddati tugashini kuting.',
        '💳 Оплата подписки уже открыта. Завершите её или дождитесь истечения ссылки.',
    ),
    'subscription_not_active': (
        '💳 No active paid subscription. Choose a plan to get started.',
        '💳 Faol pulli obuna yo‘q. Boshlash uchun tarif tanlang.',
        '💳 Активной платной подписки нет. Выберите тариф.',
    ),
    'renewal_disabled': (
        '⏸ Auto-renewal is off. Manage it in Subscription.',
        '⏸ Avto-uzaytirish o‘chirilgan. Uni Obuna bo‘limida boshqaring.',
        '⏸ Автопродление выключено. Настройте его в разделе «Подписка».',
    ),
    'invalid_plan invalid_plan_change': (
        '⭐ Choose an available plan in Plans & packs.',
        '⭐ Tariflar va paketlardan mavjud tarifni tanlang.',
        '⭐ Выберите доступный вариант в тарифах и пакетах.',
    ),
    'offer_version_conflict': (
        '⭐ This offer has changed. Open Plans & packs to see the latest options.',
        '⭐ Taklif o‘zgargan. Yangilangan variantlarni Tariflar va paketlarda ko‘ring.',
        '⭐ Предложение изменилось. Откройте тарифы и пакеты для актуальных вариантов.',
    ),
    'payment_provider_unavailable': (
        '⏳ Payment service isn’t responding. Try later or contact Payment support.',
        '⏳ To‘lov xizmati javob bermayapti. Keyinroq urining yoki to‘lov bo‘yicha yordamga yozing.',
        '⏳ Платёжный сервис не отвечает. Попробуйте позже или обратитесь в поддержку оплаты.',
    ),
    'invalid_charge charge_conflict subscription_period_required invalid_subscription_period renewal_contract_mismatch duplicate_subscription_period invalid_recurring_purchase': (
        '⚠️ Couldn’t confirm the payment details. Contact Payment support with /paysupport.',
        '⚠️ To‘lov tafsilotlarini tasdiqlay olmadik. /paysupport orqali yordamga yozing.',
        '⚠️ Не удалось подтвердить данные платежа. Обратитесь за помощью через /paysupport.',
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
    'daily_ai_limit': (
        '⏳ You’ve made today’s AI documents on the free plan. Come back tomorrow, or choose a paid plan for no daily limit.',
        '⏳ Bepul tarifdagi bugungi AI hujjatlar soni tugadi. Ertaga qayting yoki kunlik cheklovsiz pullik tarifni tanlang.',
        '⏳ Лимит ИИ-документов на сегодня на бесплатном тарифе исчерпан. Возвращайтесь завтра или выберите платный тариф без дневного лимита.',
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
    'manual_payment_closed manual_payment_expired': (
        '⌛ This payment is closed. Open Plans to start a new one: /plans',
        '⌛ Bu to‘lov yopilgan. Yangisini boshlash uchun tariflarni oching: /plans',
        '⌛ Этот платёж закрыт. Откройте тарифы, чтобы начать новый: /plans',
    ),
    'manual_subscription_not_renewable': (
        '💳 A card payment covers 30 days and doesn’t renew by itself. Pay again to continue: /plans',
        '💳 Karta orqali to‘lov 30 kunga amal qiladi va o‘zi uzaytirilmaydi. Davom etish uchun qayta to‘lang: /plans',
        '💳 Оплата картой действует 30 дней и сама не продлевается. Чтобы продолжить, оплатите снова: /plans',
    ),
}

COPY = {
    locale: {code: values[index] for codes, values in MESSAGES.items() for code in codes.split()}
    for index, locale in enumerate(('en', 'uz', 'ru'))
}


def bot_error(error, locale='en'):
    locale = locale if locale in COPY else 'en'
    if error.code == 'bot_wrong_file':
        from .ux_copy import UX
        return UX[locale]['wrong_file']
    if error.code in COPY[locale]:
        return COPY[locale][error.code]
    return '⚠️ ' + error_data(error, locale)['message']
