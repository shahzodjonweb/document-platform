"""Telegram transport over the same domain services as the browser.

Run with `python manage.py runbot`; no network traffic occurs at import time.
"""
import asyncio
import hashlib
import html
import io
import json
import secrets
import uuid
from types import SimpleNamespace
from datetime import timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, BufferedInputFile, BotCommand
from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from apps.core.models import BotCallback, BotDraft, BotInputReceipt, AuthChallenge, FileAsset, Job, SupportTicket
from apps.core.identity import resolve_account, approve_challenge_id
from apps.core.policy import catalog, usage_snapshot
from apps.core.services import upload_file, create_quote, submit_job, execute_job, storage_path, cancel_job
from apps.core.serializers import quote_data
from apps.core.errors import DomainError, error_data

COPY={
 'en':{'welcome':'Welcome to PDF Master. Send a PDF or image, then choose a tool. Files are retained for 24 hours after processing.','tools':'Choose a tool. Upload files in the requested order, then use /done.','received':'File received. Send more files or choose /tools, then /done.','done':'Review the file order below. Reply /order 2,1 to change it. Use /run to confirm this quote.','run':'Run task','empty':'Send a file first.','working':'Processing your task…','result':'Your result is ready. Server files expire after 24 hours; files delivered in Telegram remain in your chat.','no_op':'No useful size reduction was found. No allowance was charged.','support':'Use /support your message or /paysupport your message.','ticket':'Your support request was saved.','cancel':'The current input flow was canceled. Submitted tasks remain in task history.','help':'Send files → /tools → /done → /run. /order 2,1 sets input order. /parameters followed by a JSON object configures pages or rotation. Use /myfiles for results.','login':'Confirm sign-in for this browser only if you initiated it:','confirm':'Confirm sign-in','approved':'Sign-in approved. Return to the initiating browser.','language':'Choose your language.','open':'Open workspace','terms':'Local development beta. Paid checkout is disabled. Server binaries expire after 24 hours. /paysupport for purchase help.'},
 'uz':{'welcome':'PDF Master’ga xush kelibsiz. PDF yoki rasm yuboring, so‘ng vositani tanlang. Fayllar qayta ishlangandan keyin 24 soat saqlanadi.','tools':'Vositani tanlang. Fayllarni kerakli tartibda yuboring, so‘ng /done buyrug‘ini bering.','received':'Fayl qabul qilindi. Yana fayl yuboring yoki /tools, so‘ng /done buyrug‘ini tanlang.','done':'Quyidagi fayllar tartibini tekshiring. O‘zgartirish uchun /order 2,1 yuboring. Narxni tasdiqlash uchun /run yuboring.','run':'Vazifani bajarish','empty':'Avval fayl yuboring.','working':'Vazifa bajarilmoqda…','result':'Natija tayyor. Serverdagi fayllar 24 soatdan keyin o‘chiriladi; Telegram’ga yuborilgan fayllar chatda qoladi.','no_op':'Fayl hajmi sezilarli kamaymadi. Limit sarflanmadi.','support':'/support xabaringiz yoki /paysupport xabaringiz shaklida yozing.','ticket':'Yordam so‘rovingiz saqlandi.','cancel':'Joriy kiritish bekor qilindi. Yuborilgan vazifalar tarixda qoladi.','help':'Fayl yuboring → /tools → /done → /run. /order 2,1 tartibni belgilaydi. /parameters buyrug‘idan keyin JSON obyektida parametrlarni yuboring. Natijalar: /myfiles.','login':'Faqat o‘zingiz boshlagan bo‘lsangiz, ushbu brauzer uchun kirishni tasdiqlang:','confirm':'Kirishni tasdiqlash','approved':'Kirish tasdiqlandi. Boshlang‘ich brauzerga qayting.','language':'Tilni tanlang.','open':'Ish maydonini ochish','terms':'Mahalliy beta versiya. To‘lovlar o‘chirilgan. Server fayllari 24 soatdan keyin o‘chiriladi. To‘lov yordami: /paysupport.'},
 'ru':{'welcome':'Добро пожаловать в PDF Master. Отправьте PDF или изображение и выберите инструмент. Файлы хранятся 24 часа после обработки.','tools':'Выберите инструмент. Отправьте файлы в нужном порядке, затем нажмите /done.','received':'Файл получен. Отправьте ещё файлы или выберите /tools, затем /done.','done':'Проверьте порядок файлов. Для изменения отправьте /order 2,1. Подтвердите расчёт командой /run.','run':'Выполнить','empty':'Сначала отправьте файл.','working':'Обрабатываем задачу…','result':'Результат готов. Файлы на сервере истекают через 24 часа; отправленные в Telegram остаются в чате.','no_op':'Значимого уменьшения размера не найдено. Лимит не списан.','support':'Напишите /support ваш вопрос или /paysupport ваш вопрос.','ticket':'Обращение сохранено.','cancel':'Текущий ввод отменён. Отправленные задачи остаются в истории.','help':'Файлы → /tools → /done → /run. /order 2,1 меняет порядок. /parameters с JSON-объектом задаёт параметры. Результаты: /myfiles.','login':'Подтвердите вход в этом браузере, только если вы его инициировали:','confirm':'Подтвердить вход','approved':'Вход подтверждён. Вернитесь в исходный браузер.','language':'Выберите язык.','open':'Открыть рабочую область','terms':'Локальная бета-версия. Оплата отключена. Серверные файлы истекают через 24 часа. Помощь по оплате: /paysupport.'}}
TOOL_NAMES={'pdf.merge':{'en':'Merge PDFs','uz':'PDF birlashtirish','ru':'Объединить PDF'},'pdf.compress':{'en':'Compress PDF','uz':'PDF siqish','ru':'Сжать PDF'},'pdf.split':{'en':'Split PDF','uz':'PDF ajratish','ru':'Разделить PDF'},'pdf.extract_pages':{'en':'Extract pages','uz':'Sahifalarni ajratish','ru':'Извлечь страницы'},'pdf.delete_pages':{'en':'Delete pages','uz':'Sahifalarni o‘chirish','ru':'Удалить страницы'},'pdf.reorder':{'en':'Reorder pages','uz':'Sahifalar tartibi','ru':'Порядок страниц'},'pdf.rotate':{'en':'Rotate pages','uz':'Sahifalarni aylantirish','ru':'Повернуть страницы'},'pdf.images_to_pdf':{'en':'Images to PDF','uz':'Rasmlardan PDF','ru':'Изображения в PDF'},'pdf.to_images':{'en':'PDF to images','uz':'PDF’dan rasmlar','ru':'PDF в изображения'}}

WORKFLOW_COPY={
'en':{'settings':'Task settings','done_button':'Review quote','back':'Back','next':'More tools','pages_hint':'Use /pages 1,3-5 to select pages.','split_hint':'Use /split 1-2;3-4 for ranges, or /done for one file per page.','reorder_hint':'Use /pages 3,1,2 to set every page’s new order.','merge_hint':'Use /order 2,1 to reorder files or /remove 2 to remove an input.','image_hint':'Choose paper and orientation below. Use /margin 24 to set a margin in points.','secure':'Enter PDF passwords only in the secure web workspace. Do not send passwords to this chat.','rotate_label':'Rotate','format_label':'Image format','paper_label':'Paper','portrait':'Portrait','landscape':'Landscape','auto':'Automatic','quote_cost':'task / page units','balance':'Available task / page units','expires':'Quote expires (UTC)','parameters':'Settings','add':'Add to this task','new':'Start a new task','new_file':'There is an existing task. Choose where this new file belongs.','controls_expired':'These controls have expired. Use /settings to continue.','help':'Send files → /tools → /settings → /done → /run. /pages 1,3-5 selects pages; /split 1-2;3-4 creates groups; /rotate 90 changes rotation; /format png 96 sets images; /order 2,1 changes file order. /remove 2 removes a file. /myfiles returns recent results.','no_preview':'A preview is unavailable for this file.','preview':'Preview first page'},
'uz':{'settings':'Vazifa sozlamalari','done_button':'Hisob-kitobni ko‘rish','back':'Orqaga','next':'Boshqa vositalar','pages_hint':'Sahifalarni tanlash uchun /pages 1,3-5 yuboring.','split_hint':'Oraliqlar uchun /split 1-2;3-4, har sahifani ajratish uchun /done yuboring.','reorder_hint':'Sahifalar tartibi uchun /pages 3,1,2 yuboring.','merge_hint':'Fayllar tartibi: /order 2,1. Faylni olib tashlash: /remove 2.','image_hint':'Qog‘oz va yo‘nalishni tanlang. Hoshiyani punktda belgilash uchun /margin 24 yuboring.','secure':'PDF parollarini faqat xavfsiz veb ish maydonida kiriting. Parollarni bu chatga yubormang.','rotate_label':'Aylantirish','format_label':'Rasm formati','paper_label':'Qog‘oz','portrait':'Tik','landscape':'Yotiq','auto':'Avtomatik','quote_cost':'vazifa / sahifa birligi','balance':'Mavjud vazifa / sahifa birligi','expires':'Hisob-kitob muddati (UTC)','parameters':'Sozlamalar','add':'Joriy vazifaga qo‘shish','new':'Yangi vazifa boshlash','new_file':'Joriy vazifa mavjud. Yangi faylni qayerga qo‘shishni tanlang.','controls_expired':'Bu boshqaruv tugmalari eskirdi. Davom etish uchun /settings yuboring.','help':'Fayl → /tools → /settings → /done → /run. /pages 1,3-5 sahifalarni tanlaydi; /split 1-2;3-4 guruhlaydi; /rotate 90 aylantiradi; /format png 96 rasmlarni sozlaydi; /order 2,1 fayllarni tartiblaydi. /remove 2 faylni olib tashlaydi. Natijalar: /myfiles.','no_preview':'Bu faylni oldindan ko‘rib bo‘lmaydi.','preview':'Birinchi sahifani ko‘rish'},
'ru':{'settings':'Настройки задачи','done_button':'Проверить расчёт','back':'Назад','next':'Другие инструменты','pages_hint':'Выберите страницы командой /pages 1,3-5.','split_hint':'Используйте /split 1-2;3-4 для групп или /done для отдельного файла на страницу.','reorder_hint':'Задайте новый порядок всех страниц: /pages 3,1,2.','merge_hint':'Изменить порядок файлов: /order 2,1. Удалить файл: /remove 2.','image_hint':'Выберите бумагу и ориентацию. Поле в пунктах: /margin 24.','secure':'Вводите пароли PDF только в защищённом веб-интерфейсе. Не отправляйте пароли в этот чат.','rotate_label':'Поворот','format_label':'Формат изображения','paper_label':'Бумага','portrait':'Книжная','landscape':'Альбомная','auto':'Автоматически','quote_cost':'задача / единицы страниц','balance':'Доступно задач / единиц страниц','expires':'Расчёт действует до (UTC)','parameters':'Настройки','add':'Добавить к задаче','new':'Начать новую задачу','new_file':'У вас уже есть задача. Выберите, куда добавить новый файл.','controls_expired':'Эти кнопки устарели. Продолжите командой /settings.','help':'Файлы → /tools → /settings → /done → /run. /pages 1,3-5 выбирает страницы; /split 1-2;3-4 задаёт группы; /rotate 90 — поворот; /format png 96 — изображения; /order 2,1 меняет порядок файлов. /remove 2 удаляет файл. Результаты: /myfiles.','no_preview':'Предпросмотр этого файла недоступен.','preview':'Посмотреть первую страницу'}}
for locale,values in WORKFLOW_COPY.items(): COPY[locale].update(values)
for locale,values in {
    'en':{'link_login':'Link this Telegram identity to your existing PDF Master account only if you started this request in account settings:','link_confirm':'Confirm Telegram link','link_approved':'Telegram link approved. Return to the initiating browser to finish linking your account.'},
    'uz':{'link_login':'Faqat hisob sozlamalarida o‘zingiz boshlagan bo‘lsangiz, ushbu Telegram hisobini mavjud PDF Master hisobingizga ulashni tasdiqlang:','link_confirm':'Telegram ulanishini tasdiqlash','link_approved':'Telegram ulanishi tasdiqlandi. Hisobni ulashni tugatish uchun boshlang‘ich brauzerga qayting.'},
    'ru':{'link_login':'Подтвердите привязку этого Telegram к существующему аккаунту PDF Master, только если вы начали её в настройках аккаунта:','link_confirm':'Подтвердить привязку Telegram','link_approved':'Привязка Telegram подтверждена. Вернитесь в исходный браузер, чтобы завершить её.'},
}.items(): COPY[locale].update(values)
for locale,value in {
    'en':'Server files expire after 24 hours. Purchases activate only after confirmed payment. Local simulation does not spend real Stars. /buy for offers; /paysupport for payment help.',
    'uz':'Server fayllari 24 soatdan keyin o‘chiriladi. Xaridlar faqat to‘lov tasdiqlangandan keyin faollashadi. Mahalliy sinov haqiqiy Stars sarflamaydi. Takliflar: /buy; to‘lov yordami: /paysupport.',
    'ru':'Файлы сервера истекают через 24 часа. Покупки активируются после подтверждённой оплаты. Локальная симуляция не тратит реальные Stars. Предложения: /buy; помощь по оплате: /paysupport.',
}.items():COPY[locale]['terms']=value
TOOL_NAMES.update({'convert.word_to_pdf':{'en':'Word to PDF','uz':'Word’dan PDF','ru':'Word в PDF'},'convert.pptx_to_pdf':{'en':'PowerPoint to PDF','uz':'PowerPoint’dan PDF','ru':'PowerPoint в PDF'}})

def text(account,key): return COPY.get(account.locale,COPY['en'])[key]
def user_dict(user): return {'id':user.id,'first_name':user.first_name,'username':user.username or '', 'language_code':user.language_code or 'en'}
def sender_language(user):
    # Authentication errors must not create a customer account as a side effect.
    locale=(user.language_code or 'en').split('-')[0]
    return SimpleNamespace(locale=locale if locale in COPY else 'en')
async def account_for(user): return await sync_to_async(resolve_account)(user_dict(user),'bot')
async def callback(account,action,payload=None):
    token=secrets.token_urlsafe(12)
    await sync_to_async(BotCallback.objects.create)(token=token,account=account,action=action,payload=payload or {},expires_at=timezone.now()+timedelta(minutes=10))
    return token
async def safe_error(message,account,exc):
    key='secure' if exc.code in ('password_required','secure_password_entry_required') else 'controls_expired' if exc.code=='controls_expired' else None
    from apps.commerce.providers import telegram_config
    config=await sync_to_async(telegram_config)() if key=='secure' else {}
    markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text(account,'open'),url=config['webapp_url'])]]) if key=='secure' else None
    await message.answer(text(account,key) if key else error_data(exc,account.locale)['message'],reply_markup=markup)

def build_dispatcher():
    from .workflows import draft_for,configure,snapshot,bound_draft,quote_draft,run_quote,attach_input,order_inputs
    dp=Dispatcher()
    from .billing import register_billing_handlers
    register_billing_handlers(dp)

    async def controls(message,account,draft=None):
        draft=draft or await sync_to_async(draft_for)(account)
        binding=snapshot(draft)
        async def choice(label,parameters):
            return InlineKeyboardButton(text=label,callback_data=await callback(account,'settings',{**binding,'parameters':parameters}))
        rows=[]
        feature=draft.feature_id
        hints=[]
        if feature=='pdf.rotate': rows.append([await choice(f'{angle}°',{'angle':angle}) for angle in (90,180,270)])
        if feature=='pdf.to_images':
            rows.append([await choice(value.upper(),{'format':value}) for value in ('png','jpg')])
            rows.append([await choice(f'{dpi} DPI',{'dpi':dpi}) for dpi in (72,96,150,200)])
        if feature=='pdf.images_to_pdf':
            rows.append([await choice(value,{'paper_size':value}) for value in ('A4','Letter','original')])
            rows.append([await choice(text(account,label),{'orientation':value}) for label,value in [('auto','auto'),('portrait','portrait'),('landscape','landscape')]])
            hints.append(text(account,'image_hint'))
        if feature in ('pdf.extract_pages','pdf.delete_pages','pdf.rotate','pdf.to_images'): hints.append(text(account,'pages_hint'))
        if feature=='pdf.split': hints.append(text(account,'split_hint'))
        if feature=='pdf.reorder': hints.append(text(account,'reorder_hint'))
        if feature in ('pdf.merge','pdf.images_to_pdf'): hints.append(text(account,'merge_hint'))
        rows.append([InlineKeyboardButton(text=text(account,'done_button'),callback_data=await callback(account,'done',binding))])
        files=await sync_to_async(lambda:{str(a.id):a for a in FileAsset.objects.filter(account=account,id__in=draft.input_ids)})()
        listing='\n'.join(f'{i+1}. {html.escape(files[k].name)} · {files[k].page_count}' for i,k in enumerate(draft.input_ids) if k in files)
        if draft.input_ids and draft.input_ids[0] in files and files[draft.input_ids[0]].mime_type=='application/pdf':
            rows.append([InlineKeyboardButton(text=text(account,'preview'),callback_data=await callback(account,'preview',{**binding,'asset_id':draft.input_ids[0],'page':1}))])
        title=TOOL_NAMES.get(feature,{}).get(account.locale,feature)
        params=html.escape(json.dumps(draft.parameters,ensure_ascii=False))
        await message.answer(f'<b>{html.escape(title)}</b>\n{listing}\n\n{text(account,"parameters")}: {params}\n'+ '\n'.join(hints),parse_mode='HTML',reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

    async def menu(message,account,page=0):
        features=[f for f in await sync_to_async(catalog)(account) if not f.get('capabilities',{}).get('requires_secret')]
        page=max(0,min(page,max(0,(len(features)-1)//6)))
        draft=await sync_to_async(draft_for)(account)
        rows=[]
        for f in features[page*6:(page+1)*6]:
            label=TOOL_NAMES.get(f['id'],{}).get(account.locale,f['name'])
            rows.append([InlineKeyboardButton(text=label,callback_data=await callback(account,'tool',{**snapshot(draft),'feature_id':f['id']}))])
        nav=[]
        if page: nav.append(InlineKeyboardButton(text=text(account,'back'),callback_data=await callback(account,'menu',{'page':page-1})))
        if (page+1)*6<len(features): nav.append(InlineKeyboardButton(text=text(account,'next'),callback_data=await callback(account,'menu',{'page':page+1})))
        if nav: rows.append(nav)
        from apps.commerce.providers import telegram_config
        config=await sync_to_async(telegram_config)()
        rows.append([InlineKeyboardButton(text=text(account,'open'),url=config['webapp_url'])])
        await message.answer(text(account,'tools'),reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

    async def quote_message(message,account,draft,quote):
        names=await sync_to_async(lambda:{str(a.id):a.name for a in FileAsset.objects.filter(account=account,id__in=draft.input_ids)})()
        listing='\n'.join(f'{i+1}. {html.escape(names.get(key,""))}' for i,key in enumerate(draft.input_ids))
        summary=await sync_to_async(quote_data)(quote)
        meters=quote.meters;balances=summary['available_balances']
        run=InlineKeyboardButton(text=text(account,'run'),callback_data=await callback(account,'run',{**snapshot(draft),'quote_id':str(quote.id)}))
        credits={'en':'AI credits / available','uz':'AI kredit / mavjud','ru':'AI-кредиты / доступно'}.get(account.locale,'AI credits / available')
        credit_line=f'\n{credits}: {meters["ai_credits"]} / {balances["ai_credits"]["remaining"]}' if meters.get('ai_credits') else ''
        await message.answer(f'{listing}\n\n{meters["file_tasks"]} / {meters["file_page_units"]} {text(account,"quote_cost")}\n{text(account,"balance")}: {balances["file_tasks"]["remaining"]} / {balances["file_page_units"]["remaining"]}{credit_line}\n{text(account,"expires")}: {quote.expires_at:%Y-%m-%d %H:%M}\n{text(account,"done")}',parse_mode='HTML',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[run]]))

    async def review(message,account,binding=None):
        draft,quote=await sync_to_async(quote_draft)(account,binding)
        await quote_message(message,account,draft,quote)

    async def deliver(message,account,job):
        from .delivery import enqueue,attempt
        artifacts=await sync_to_async(lambda:list(job.artifacts.select_related('file','account')))()
        requested_again=(message.text or '').startswith('/myfiles')
        for artifact in artifacts:
            key=f'myfiles:{message.message_id}:{artifact.id}' if requested_again else f'job:{job.id}:{artifact.id}'
            delivery=await sync_to_async(enqueue)(artifact,key)
            await attempt(delivery.id,message.bot)

    async def send_preview(message,account,asset_id,page):
        from apps.core.previews import preview_asset
        preview=await sync_to_async(preview_asset)(account,asset_id,page)
        data=await sync_to_async(lambda:storage_path(preview.object_key).read_bytes())()
        await message.answer_document(BufferedInputFile(data,filename=preview.name))

    async def run(message,account,quote_id):
        job,_=await sync_to_async(run_quote)(account,quote_id)
        status=await message.answer(text(account,'working'))
        job=await sync_to_async(execute_job)(job.id)
        if job.status=='succeeded':
            await status.edit_text(text(account,'result'))
            await deliver(message,account,job)
        elif job.status=='no_op': await status.edit_text(text(account,'no_op'))
        elif job.status in ('queued','running','finalizing'): await status.edit_text(text(account,'working'))
        else: await status.edit_text(error_data(DomainError(job.error_code or 'processing_failed'),account.locale)['message'])

    @dp.message(CommandStart())
    async def start(message):
        payload=(message.text or '').split(maxsplit=1)
        if len(payload)>1 and payload[1].startswith('login_'):
            token=payload[1][6:]
            challenge=await sync_to_async(lambda:AuthChallenge.objects.select_related('link_account').filter(token_hash=hashlib.sha256(token.encode()).hexdigest(),expires_at__gt=timezone.now(),consumed_at__isnull=True,approved_at__isnull=True).first())()
            if not challenge: return await safe_error(message,sender_language(message.from_user),DomainError('challenge_expired'))
            if challenge.intent=='link':
                if message.chat.type!='private' or message.chat.id!=message.from_user.id or not challenge.link_account_id:
                    return await safe_error(message,sender_language(message.from_user),DomainError('invalid_telegram_data'))
                account=challenge.link_account
                ref=await callback(account,'link_login',{'challenge_id':str(challenge.id),'telegram_user_id':message.from_user.id})
                return await message.answer(f'{text(account,"link_login")}\n{html.escape(challenge.browser_hint)}',parse_mode='HTML',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text(account,'link_confirm'),callback_data=ref)]]))
            account=await sync_to_async(resolve_account)(user_dict(message.from_user),'web')
            ref=await callback(account,'login',{'challenge_id':str(challenge.id)})
            return await message.answer(f'{text(account,"login")}\n{html.escape(challenge.browser_hint)}',parse_mode='HTML',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text(account,'confirm'),callback_data=ref)]]))
        account=await account_for(message.from_user)
        if len(payload)>1 and payload[1].startswith('ref_'):
            from apps.commerce.services import claim_referral
            try: await sync_to_async(claim_referral)(account,payload[1][4:])
            except DomainError as exc: await safe_error(message,account,exc)
        await message.answer(text(account,'welcome'))
        await menu(message,account)

    @dp.message(Command('menu','tools'))
    async def tools(message): await menu(message,await account_for(message.from_user))

    @dp.message(Command('settings'))
    async def settings_command(message): await controls(message,await account_for(message.from_user))

    @dp.message(Command('language'))
    async def language(message):
        account=await account_for(message.from_user)
        rows=[[InlineKeyboardButton(text=label,callback_data=await callback(account,'locale',{'locale':locale}))] for locale,label in [('uz','O‘zbekcha'),('en','English'),('ru','Русский')]]
        await message.answer(text(account,'language'),reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

    @dp.callback_query()
    async def click(query):
        # A linking sender may not have an Account yet. Bind this callback to the
        # initiating Telegram user without calling account_for and creating one.
        ref=await sync_to_async(lambda:BotCallback.objects.select_related('account').filter(token=query.data,expires_at__gt=timezone.now()).first())()
        if not ref:
            return await query.answer(text(sender_language(query.from_user),'controls_expired'),show_alert=True)
        if ref.action=='link_login':
            if ref.payload.get('telegram_user_id')!=query.from_user.id or not query.message or query.message.chat.type!='private' or query.message.chat.id!=query.from_user.id:
                return await query.answer(text(sender_language(query.from_user),'controls_expired'),show_alert=True)
            try:
                account=await sync_to_async(approve_challenge_id)(ref.payload['challenge_id'],user_dict(query.from_user))
                await query.message.answer(text(account,'link_approved'))
            except DomainError as exc:
                await safe_error(query.message,ref.account,exc)
            return await query.answer()
        if ref.account.telegram_user_id!=query.from_user.id:
            return await query.answer(text(sender_language(query.from_user),'controls_expired'),show_alert=True)
        account=await account_for(query.from_user)
        try:
            if ref.action=='login':
                await sync_to_async(approve_challenge_id)(ref.payload['challenge_id'],user_dict(query.from_user))
                await query.message.answer(text(account,'approved'))
            elif ref.action=='locale':
                account.locale=ref.payload['locale']
                await sync_to_async(account.save)(update_fields=['locale'])
                await controls(query.message,account)
            elif ref.action=='menu': await menu(query.message,account,ref.payload['page'])
            elif ref.action=='tool':
                draft=await sync_to_async(configure)(account,feature_id=ref.payload['feature_id'],binding=ref.payload)
                await controls(query.message,account,draft)
            elif ref.action=='settings':
                draft=await sync_to_async(configure)(account,parameters=ref.payload['parameters'],binding=ref.payload)
                await controls(query.message,account,draft)
            elif ref.action=='attach':
                asset=await sync_to_async(lambda:FileAsset.objects.get(account=account,pk=ref.payload['asset_id']))()
                draft,_=await sync_to_async(attach_input)(account,asset,ref.payload['chat_id'],ref.payload['message_id'],ref.payload['mode'],ref.payload)
                await controls(query.message,account,draft)
            elif ref.action=='preview':
                def authorize_preview():
                    from django.db import transaction
                    with transaction.atomic():
                        draft=bound_draft(account,ref.payload)
                        if ref.payload['asset_id'] not in draft.input_ids: raise DomainError('controls_expired',409)
                await sync_to_async(authorize_preview)()
                await send_preview(query.message,account,ref.payload['asset_id'],ref.payload['page'])
            elif ref.action=='done': await review(query.message,account,ref.payload)
            elif ref.action=='run':
                def authorize_run():
                    from django.db import transaction
                    with transaction.atomic():
                        draft=bound_draft(account,ref.payload)
                        if str(draft.quote_id)!=ref.payload['quote_id']: raise DomainError('controls_expired',409)
                await sync_to_async(authorize_run)()
                await run(query.message,account,ref.payload['quote_id'])
            await query.answer()
        except DomainError as exc:
            await safe_error(query.message,account,exc)
            await query.answer()

    @dp.message(F.document | F.photo)
    async def receive(message,bot):
        account=await account_for(message.from_user)
        duplicate=await sync_to_async(lambda:BotInputReceipt.objects.filter(account=account,chat_id=message.chat.id,message_id=message.message_id).exists())()
        if duplicate: return await controls(message,account)
        doc=message.document or message.photo[-1]
        if (doc.file_size or 0)>20*1024*1024: return await safe_error(message,account,DomainError('bot_transport_limit'))
        stream=io.BytesIO();await bot.download(doc,destination=stream)
        name=message.document.file_name if message.document else 'photo.jpg'
        try:
            asset=await sync_to_async(upload_file)(account,SimpleUploadedFile(name,stream.getvalue()),'bot')
            draft=await sync_to_async(draft_for)(account)
            if draft.input_ids and draft.quote_id:
                rows=[]
                for mode,label in [('add','add'),('new','new')]:
                    token=await callback(account,'attach',{**snapshot(draft),'asset_id':str(asset.id),'chat_id':message.chat.id,'message_id':message.message_id,'mode':mode})
                    rows.append([InlineKeyboardButton(text=text(account,label),callback_data=token)])
                await message.answer(text(account,'new_file'),reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
            else:
                draft,_=await sync_to_async(attach_input)(account,asset,message.chat.id,message.message_id)
                await controls(message,account,draft)
        except DomainError as exc: await safe_error(message,account,exc)

    @dp.message(Command('order','remove'))
    async def order(message):
        account=await account_for(message.from_user)
        try:
            command,value=message.text.split(maxsplit=1)
            remove=int(value)-1 if command.split('@')[0]=='/remove' else None
            positions=[int(v.strip())-1 for v in value.split(',')] if remove is None else []
            draft=await sync_to_async(order_inputs)(account,positions,remove)
            await controls(message,account,draft)
        except (ValueError,IndexError): await safe_error(message,account,DomainError('invalid_parameters'))
        except DomainError as exc: await safe_error(message,account,exc)

    @dp.message(Command('pages','split','rotate','format','paper','margin','layout','parameters'))
    async def parameter_command(message):
        account=await account_for(message.from_user)
        try:
            command,value=message.text.split(maxsplit=1);command=command.split('@')[0]
            draft=await sync_to_async(draft_for)(account)
            feature=None;replace=False
            if command=='/pages': parameters={'order':[int(v.strip()) for v in value.split(',')]} if draft.feature_id=='pdf.reorder' else {'pages':value.strip()}
            elif command=='/split': feature='pdf.split';parameters={'ranges':[v.strip() for v in value.split(';')]}
            elif command=='/rotate':
                feature='pdf.rotate';pieces=value.split(maxsplit=1);parameters={'angle':int(pieces[0])}
                if len(pieces)>1: parameters['pages']=pieces[1]
            elif command=='/format':
                feature='pdf.to_images';pieces=value.split();parameters={'format':pieces[0].lower()}
                if len(pieces)>1: parameters['dpi']=int(pieces[1])
            elif command=='/paper': feature='pdf.images_to_pdf';parameters={'paper_size':value.strip()}
            elif command=='/margin': parameters={'margin':float(value)}
            elif command=='/layout': feature='pdf.images_to_pdf';parameters={'orientation':value.strip()}
            else: parameters=json.loads(value);replace=True
            draft=await sync_to_async(configure)(account,feature_id=feature,parameters=parameters,replace=replace)
            await controls(message,account,draft)
        except (ValueError,IndexError): await safe_error(message,account,DomainError('invalid_parameters'))
        except DomainError as exc: await safe_error(message,account,exc)

    @dp.message(Command('preview'))
    async def preview_command(message):
        account=await account_for(message.from_user)
        try:
            pieces=message.text.split();page=int(pieces[1]) if len(pieces)>1 else 1
            index=int(pieces[2])-1 if len(pieces)>2 else 0
            draft=await sync_to_async(draft_for)(account)
            if not 0<=index<len(draft.input_ids): raise DomainError('invalid_parameters')
            await send_preview(message,account,draft.input_ids[index],page)
        except (ValueError,IndexError): await safe_error(message,account,DomainError('invalid_parameters'))
        except DomainError as exc: await safe_error(message,account,exc)

    @dp.message(Command('done'))
    async def done(message):
        account=await account_for(message.from_user)
        try: await review(message,account)
        except DomainError as exc: await safe_error(message,account,exc)

    @dp.message(Command('run'))
    async def run_command(message):
        account=await account_for(message.from_user)
        draft=await sync_to_async(draft_for)(account)
        try:
            if not draft.quote_id: raise DomainError('quote_required')
            await run(message,account,str(draft.quote_id))
        except DomainError as exc: await safe_error(message,account,exc)

    @dp.message(Command('myfiles'))
    async def myfiles(message):
        account=await account_for(message.from_user)
        jobs=await sync_to_async(lambda:list(Job.objects.filter(account=account,status='succeeded').order_by('-created_at')[:3]))()
        if not jobs: return await message.answer(text(account,'empty'))
        for job in jobs: await deliver(message,account,job)

    @dp.message(Command('plan','usage'))
    async def plan(message):
        account=await account_for(message.from_user)
        usage=await sync_to_async(usage_snapshot)(account)
        remaining=usage['meters']['file_tasks']['remaining']
        await message.answer(f'{account.plan.title()} · {remaining} / {usage["meters"]["file_tasks"]["limit"]}\n{usage["resets_at"].isoformat()} UTC')

    @dp.message(Command('support','paysupport'))
    async def support(message):
        account=await account_for(message.from_user)
        parts=message.text.split(maxsplit=1)
        if len(parts)<2: return await message.answer(text(account,'support'))
        await sync_to_async(SupportTicket.objects.create)(account=account,subject='Telegram support',message=parts[1][:4000],category='payments' if parts[0].startswith('/paysupport') else 'general')
        await message.answer(text(account,'ticket'))

    @dp.message(Command('cancel'))
    async def cancel(message):
        account=await account_for(message.from_user)
        await sync_to_async(lambda:BotDraft.objects.filter(account=account).delete())()
        await message.answer(text(account,'cancel'))

    @dp.message(Command('create','study','school','teach','editor'))
    async def open_workspace_mode(message):
        from apps.commerce.providers import telegram_config
        from urllib.parse import urlencode
        account=await account_for(message.from_user)
        command=message.text.split()[0].split('@')[0][1:]
        cfg=await sync_to_async(telegram_config)()
        labels={
            'en':{'create':'Create a document or presentation','study':'Study workspace','school':'School practice','teach':'Teaching workspace','editor':'Open the PDF editor'},
            'uz':{'create':'Hujjat yoki taqdimot yaratish','study':'O‘rganish maydoni','school':'Maktab mashqlari','teach':'O‘qituvchi maydoni','editor':'PDF tahrirchisini ochish'},
            'ru':{'create':'Создать документ или презентацию','study':'Учебное пространство','school':'Школьная практика','teach':'Пространство учителя','editor':'Открыть редактор PDF'}}
        title=labels.get(account.locale,labels['en'])[command]
        url=cfg['webapp_url'].rstrip('/')+'/'+command
        draft=await sync_to_async(draft_for)(account)
        if draft.input_ids: url+='?'+urlencode({'file_id':draft.input_ids[0]})
        await message.answer(title,reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=title,url=url)]]))

    @dp.message(Command('help','terms','password'))
    async def help_(message):
        account=await account_for(message.from_user)
        key='secure' if message.text.startswith('/password') else 'terms' if message.text.startswith('/terms') else 'help'
        await message.answer(text(account,key))

    @dp.message(F.text)
    async def fallback(message):
        account=await account_for(message.from_user)
        await message.answer(text(account,'help'))
    return dp

async def run_polling():
    from .locking import polling_lock
    with polling_lock():
        await _run_polling()

async def _run_polling():
    from apps.commerce.providers import telegram_config
    config=await sync_to_async(telegram_config)()
    if not config.get('token'): raise RuntimeError('Configure a Telegram bot token in the admin panel.')
    if config.get('webhook_secret'): raise RuntimeError('Disable webhook mode before using polling.')
    bot=Bot(config['token'])
    from .commands import install_commands
    from .delivery import delivery_loop
    deliveries=None
    try:
        await install_commands(bot)
        deliveries=asyncio.create_task(delivery_loop(bot))
        await build_dispatcher().start_polling(bot)
    finally:
        if deliveries:
            deliveries.cancel()
            try: await deliveries
            except asyncio.CancelledError: pass
        await bot.session.close()
