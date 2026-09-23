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
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, BufferedInputFile, BotCommand
from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from apps.core.models import BotConversation, BotCallback, BotDraft, BotInputReceipt, AuthChallenge, FileAsset, Job, SupportTicket
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


from .ux_copy import UX, STATUS
for locale, values in UX.items(): COPY[locale].update(values)

def text(account,key): return COPY.get(account.locale,COPY['en'])[key]
def user_dict(user): return {'id':user.id,'first_name':user.first_name,'username':user.username or '', 'language_code':user.language_code or 'en'}
def sender_language(user):
    locale=(user.language_code or 'en').split('-')[0]
    return SimpleNamespace(locale=locale if locale in COPY else 'en')
async def account_for(user):
    from .onboarding import chosen_locale
    data=user_dict(user)
    locale=await sync_to_async(chosen_locale)(user.id)
    data['language_code']=locale or data['language_code']
    account=await sync_to_async(resolve_account)(data,'bot')
    if locale and account.locale!=locale:
        account.locale=locale
        await sync_to_async(account.save)(update_fields=['locale'])
    return account
async def callback(account,action,payload=None):
    token=secrets.token_urlsafe(12)
    await sync_to_async(BotCallback.objects.create)(token=token,account=account,action=action,payload=payload or {},expires_at=timezone.now()+timedelta(minutes=30))
    return token
async def web_url(account,route=''):
    from apps.commerce.providers import telegram_config
    from urllib.parse import urlsplit,urlunsplit
    config=await sync_to_async(telegram_config)()
    url=urlsplit(config['webapp_url'])
    parts=url.path.rstrip('/').split('/')
    if len(parts)>1 and parts[1] in ('en','uz','ru'): parts[1]=account.locale
    return urlunsplit((url.scheme,url.netloc,'/'.join(parts)+('/'+route if route else ''),'',''))
async def button(account,label,action,payload=None):
    return InlineKeyboardButton(text=text(account,label),callback_data=await callback(account,action,payload))
async def safe_error(message,account,exc):
    key='secure' if exc.code in ('password_required','secure_password_entry_required') else 'controls_expired' if exc.code=='controls_expired' else None
    rows=[]
    if key=='secure': rows.append([InlineKeyboardButton(text=text(account,'open'),url=await web_url(account))])
    if getattr(account,'telegram_user_id',None):
        rows.append([await button(account,'continue_task','controls'),await button(account,'home','home')])
        if 'quota' in exc.code or 'balance' in exc.code or 'allowance' in exc.code or exc.code=='feature_not_in_plan':
            rows.insert(0,[await button(account,'plans','plans')])
    await message.answer(text(account,key) if key else error_data(exc,account.locale)['message'],reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None)

def set_prompt(account,state='',prompt=None):
    BotConversation.objects.filter(pk=account.telegram_user_id).update(state=state,prompt=prompt or {},updated_at=timezone.now())

def option_summary(account,draft):
    labels={'angle':'rotate_label','pages':'pages','order':'page_order','ranges':'split_groups','format':'format_label','dpi':None,'paper_size':'paper_label','orientation':None,'margin':'margin_button'}
    result=[]
    for key,value in draft.parameters.items():
        label=text(account,labels[key]) if labels.get(key) else 'DPI' if key=='dpi' else ''
        if key=='orientation': value=text(account,{'auto':'auto','portrait':'portrait','landscape':'landscape'}.get(value,'auto'))
        if isinstance(value,list): value=', '.join(map(str,value))
        if key=='angle': value=f'{value}°'
        if value=='all': value=text(account,'all_pages')
        value=str(value)
        if len(value)>180: value=value[:177]+'…'
        result.append(html.escape(f'{label}: {value}' if label else value))
    return '\n'.join(result) or text(account,'options_default')

def build_dispatcher():
    from .workflows import draft_for,configure,snapshot,bound_draft,quote_draft,run_quote,attach_input,order_inputs,discard_draft
    from .onboarding import install_onboarding,show_language,chosen_locale
    from .billing import register_billing_handlers,show_offers,show_subscription
    dp=Dispatcher()
    register_billing_handlers(dp)

    async def render(message,body,rows,edit=False):
        from aiogram.exceptions import TelegramBadRequest
        markup=InlineKeyboardMarkup(inline_keyboard=rows)
        if edit:
            try: return await message.edit_text(body,parse_mode='HTML',reply_markup=markup)
            except TelegramBadRequest as exc:
                if 'message is not modified' in str(exc): return None
                # Old photo/document messages cannot be changed into text.
                if not any(s in str(exc) for s in ('no text in the message','message to edit not found','message can\'t be edited')): raise
        return await message.answer(body,parse_mode='HTML',reply_markup=markup)

    async def nav(account):
        return [await button(account,'back','controls'),await button(account,'home','home')]

    async def home(message,account,edit=False,notice=''):
        await sync_to_async(set_prompt)(account)
        draft=await sync_to_async(lambda:BotDraft.objects.filter(account=account).first())()
        rows=[]
        if draft and draft.input_ids: rows.append([await button(account,'continue_task','controls')])
        rows.extend([
            [await button(account,'pdf_tools','menu',{'category':'pdf'}),await button(account,'convert_tools','menu',{'category':'convert'})],
            [await button(account,'recent','recent'),await button(account,'account','account')],
            [await button(account,'help_button','help'),await button(account,'language_button','language')],
            [InlineKeyboardButton(text=text(account,'open'),url=await web_url(account))],
        ])
        await render(message,(html.escape(notice)+'\n\n' if notice else '')+f'<b>PDF Master</b>\n{text(account,"home_title")}\n\n{text(account,"home_body")}',rows,edit)

    async def menu(message,account,page=0,category='pdf',edit=False):
        await sync_to_async(set_prompt)(account)
        ids=(['pdf.merge','pdf.compress','pdf.split','pdf.extract_pages','pdf.delete_pages','pdf.reorder','pdf.rotate'] if category=='pdf' else ['pdf.images_to_pdf','pdf.to_images','convert.word_to_pdf','convert.pptx_to_pdf'])
        available={f['id'] for f in await sync_to_async(catalog)(account)}
        ids=[key for key in ids if key in available]
        page=max(0,min(int(page),max(0,(len(ids)-1)//6)))
        draft=await sync_to_async(draft_for)(account)
        rows=[[InlineKeyboardButton(text=TOOL_NAMES[key][account.locale],callback_data=await callback(account,'tool',{**snapshot(draft),'feature_id':key}))] for key in ids[page*6:(page+1)*6]]
        paging=[]
        if page: paging.append(await button(account,'back','menu',{'page':page-1,'category':category}))
        if (page+1)*6<len(ids): paging.append(await button(account,'next','menu',{'page':page+1,'category':category}))
        if paging: rows.append(paging)
        rows.append([await button(account,'convert_tools' if category=='pdf' else 'pdf_tools','menu',{'category':'convert' if category=='pdf' else 'pdf'})])
        rows.extend([[InlineKeyboardButton(text=text(account,'web_tools'),url=await web_url(account))],[await button(account,'home','home')]])
        await render(message,text(account,'choose_tool'),rows,edit)

    async def controls(message,account,draft=None,edit=False):
        await sync_to_async(set_prompt)(account)
        draft=draft or await sync_to_async(draft_for)(account)
        binding=snapshot(draft);feature=draft.feature_id
        async def choice(label,parameters,replace=False):
            return InlineKeyboardButton(text=label,callback_data=await callback(account,'settings',{**binding,'parameters':parameters,'replace':replace}))
        async def prompt(label,kind): return await button(account,label,'prompt',{**binding,'kind':kind})
        rows=[]
        files=await sync_to_async(lambda:{str(a.id):a for a in FileAsset.objects.filter(account=account,id__in=draft.input_ids)})()
        title=TOOL_NAMES.get(feature,{}).get(account.locale,feature)
        hint='upload_merge' if feature=='pdf.merge' else 'upload_images' if feature=='pdf.images_to_pdf' else 'upload_word' if feature=='convert.word_to_pdf' else 'upload_slides' if feature=='convert.pptx_to_pdf' else 'upload_pdf'
        body=f'<b>{html.escape(title)}</b>\n\n{text(account,"options_title" if files else "upload_title")}\n{text(account,hint)}'
        if feature not in ('pdf.merge','pdf.images_to_pdf') and len(files)>1: body+='\n'+text(account,'one_file_hint')
        if files:
            listing='\n'.join(f'{i+1}. {html.escape(files[k].name[:24])} · {files[k].page_count or "—"}' for i,k in enumerate(draft.input_ids) if k in files)
            body+=f'\n\n{text(account,"files")}:\n{listing}\n\n{option_summary(account,draft)}'
        if feature=='pdf.rotate': rows.append([await choice(f'{angle}°',{'angle':angle}) for angle in (90,180,270)])
        if feature=='pdf.to_images':
            rows.append([await choice(value.upper(),{'format':value}) for value in ('png','jpg')])
            rows.append([await choice(f'{dpi} DPI',{'dpi':dpi}) for dpi in (72,96,150,200)])
        if feature=='pdf.images_to_pdf':
            rows.append([await choice(value,{'paper_size':value}) for value in ('A4','Letter','original')])
            rows.append([await choice(text(account,label),{'orientation':value}) for label,value in [('auto','auto'),('portrait','portrait'),('landscape','landscape')]])
            rows.append([await prompt('margin_button','margin')])
        if feature in ('pdf.extract_pages','pdf.delete_pages','pdf.rotate','pdf.to_images'):
            rows.append([await prompt('page_selection','pages')])
            if feature in ('pdf.rotate','pdf.to_images'):
                rows[-1].append(await choice(text(account,'all_pages'),{k:v for k,v in draft.parameters.items() if k!='pages'},True))
        if feature=='pdf.split': rows.append([await prompt('split_groups','split'),await choice(text(account,'each_page'),{},True)])
        if feature=='pdf.reorder': rows.append([await prompt('page_order','reorder')])
        if files:
            if len(files)>1: rows.append([await prompt('file_order','order')])
            rows.append([await prompt('remove_file','remove')])
            if draft.input_ids[0] in files and files[draft.input_ids[0]].mime_type=='application/pdf':
                rows.append([await button(account,'preview','preview',{**binding,'asset_id':draft.input_ids[0],'page':1})])
            rows.append([await button(account,'done_button','done',binding)])
        rows.append([await button(account,'back','menu',{'category':'convert' if feature in ('pdf.images_to_pdf','pdf.to_images') or feature.startswith('convert.') else 'pdf'}),await button(account,'cancel_button','cancel',binding)])
        rows.append([await button(account,'home','home')])
        # Telegram caps message text at 4096 characters even for large drafts.
        await render(message,body,rows,edit)

    async def quote_message(message,account,draft,quote,edit=False):
        names=await sync_to_async(lambda:{str(a.id):a.name for a in FileAsset.objects.filter(account=account,id__in=draft.input_ids)})()
        listing='\n'.join(f'{i+1}. {html.escape(names.get(key,"")[:24])}' for i,key in enumerate(draft.input_ids))
        summary=await sync_to_async(quote_data)(quote);meters=quote.meters;balances=summary['available_balances']
        rows=[[await button(account,'run','run',{**snapshot(draft),'quote_id':str(quote.id)})],[await button(account,'edit_settings','controls'),await button(account,'cancel_button','cancel',snapshot(draft))],[await button(account,'home','home')]]
        usage='\n'.join(f'{text(account,label)}: {meters[key]} / {balances[key]["remaining"]}' for key,label in [('file_tasks','file_tasks'),('file_page_units','page_units'),('ai_credits','ai_credits')] if meters.get(key) or key=='file_tasks')
        body=f'<b>{text(account,"review_title")}</b>\n{text(account,"review_hint")}\n\n{listing}\n\n{option_summary(account,draft)}\n\n{text(account,"cost")} / {text(account,"available")}:\n{usage}\n{text(account,"expires")}: {quote.expires_at:%Y-%m-%d %H:%M}'
        await render(message,body,rows,edit)

    async def review(message,account,binding=None,edit=False):
        await sync_to_async(set_prompt)(account)
        draft,quote=await sync_to_async(quote_draft)(account,binding)
        await quote_message(message,account,draft,quote,edit)

    async def deliver(message,account,job,request_key=None):
        from .delivery import enqueue,attempt
        artifacts=await sync_to_async(lambda:list(job.artifacts.select_related('file','account')))()
        for artifact in artifacts:
            key=f'resend:{request_key}:{artifact.id}' if request_key else f'job:{job.id}:{artifact.id}'
            delivery=await sync_to_async(enqueue)(artifact,key)
            await attempt(delivery.id,message.bot)

    async def send_preview(message,account,asset_id,page):
        from apps.core.previews import preview_asset
        preview=await sync_to_async(preview_asset)(account,asset_id,page)
        data=await sync_to_async(lambda:storage_path(preview.object_key).read_bytes())()
        await message.answer_document(BufferedInputFile(data,filename=preview.name))

    async def job_status(message,account,job,edit=False):
        rows=[]
        body=f'<b>{html.escape(TOOL_NAMES.get(job.feature_id,{}).get(account.locale,job.feature_id))}</b>\n{text(account,"recent")}: {str(job.id)[:8]}\n{STATUS[account.locale].get(job.status,job.status)}'
        if job.status in ('queued','running','finalizing'):
            body+='\n\n'+text(account,'queued' if job.status=='queued' else 'processing')
            rows.append([await button(account,'check_status','job',{'job_id':str(job.id)})])
        elif job.status=='succeeded':
            available=await sync_to_async(lambda:job.artifacts.filter(file__state='ready',file__expires_at__gt=timezone.now()).exists())()
            body+='\n\n'+text(account,'result' if available else 'result_expired')
            if available: rows.append([await button(account,'download','download',{'job_id':str(job.id)})])
        elif job.status=='no_op': body+='\n\n'+text(account,'no_op')
        elif job.status=='failed':
            body+='\n\n'+error_data(DomainError(job.error_code or 'processing_failed'),account.locale)['message']
            draft=await sync_to_async(lambda:BotDraft.objects.filter(account=account,quote_id=job.quote_id).first())()
            if draft: rows.append([await button(account,'retry_task','retry',snapshot(draft))])
        rows.extend([[await button(account,'new_task','new'),await button(account,'recent','recent')],[await button(account,'home','home')]])
        await render(message,body,rows,edit)

    async def recent(message,account,edit=False):
        await sync_to_async(set_prompt)(account)
        jobs=await sync_to_async(lambda:list(Job.objects.filter(account=account).order_by('-created_at')[:8]))()
        rows=[]
        for job in jobs:
            title=TOOL_NAMES.get(job.feature_id,{}).get(account.locale,job.feature_id)
            label=f'{STATUS[account.locale].get(job.status,job.status)} · {title} · {job.created_at:%m/%d %H:%M}'
            rows.append([InlineKeyboardButton(text=label[:64],callback_data=await callback(account,'job',{'job_id':str(job.id)}))])
        rows.extend([[await button(account,'new_task','new')],[await button(account,'home','home')]])
        await render(message,text(account,'recent' if jobs else 'recent_empty'),rows,edit)

    async def run(message,account,quote_id):
        job,_=await sync_to_async(run_quote)(account,quote_id)
        if settings.LOCAL_SYNC_JOBS:
            job=await sync_to_async(execute_job)(job.id)
        await job_status(message,account,job)
        if job.status=='succeeded': await deliver(message,account,job)

    async def auth_prompt(message,user,challenge):
        locale=await sync_to_async(chosen_locale)(user.id) or 'en'
        if not challenge: return await safe_error(message,SimpleNamespace(locale=locale),DomainError('challenge_expired'))
        data=user_dict(user);data['language_code']=locale
        if challenge.intent=='link':
            if message.chat.type!='private' or message.chat.id!=user.id or not challenge.link_account_id:
                return await safe_error(message,SimpleNamespace(locale=locale),DomainError('invalid_telegram_data'))
            account=challenge.link_account
            # Language choice does not change an unrelated browser account.
            account.locale=locale
            ref=await callback(account,'link_login',{'challenge_id':str(challenge.id),'telegram_user_id':user.id})
            key,label='link_login','link_confirm'
        else:
            account=await sync_to_async(resolve_account)(data,'web')
            ref=await callback(account,'login',{'challenge_id':str(challenge.id)})
            key,label='login','confirm'
        await render(message,f'{text(account,key)}\n{html.escape(challenge.browser_hint)}',[[InlineKeyboardButton(text=text(account,label),callback_data=ref)]])

    async def on_ready(message,user,locale,pending):
        from .commands import install_chat_commands
        await install_chat_commands(message.bot,user.id,locale)
        if pending.get('auth_error'): return await safe_error(message,SimpleNamespace(locale=locale),DomainError('challenge_expired'))
        if pending.get('challenge_id'):
            challenge=await sync_to_async(lambda:AuthChallenge.objects.select_related('link_account').filter(pk=pending['challenge_id'],expires_at__gt=timezone.now(),consumed_at__isnull=True,approved_at__isnull=True).first())()
            return await auth_prompt(message,user,challenge)
        account=await account_for(user)
        if pending.get('referral_code'):
            from apps.commerce.services import claim_referral
            try: await sync_to_async(claim_referral)(account,pending['referral_code'])
            except DomainError as exc: await safe_error(message,account,exc)
        await home(message,account,notice=text(account,'resend') if pending.get('resend_file') else '')
    install_onboarding(dp,on_ready)

    @dp.message(CommandStart())
    async def start(message):
        parts=(message.text or '').split(maxsplit=1)
        if len(parts)>1 and parts[1].startswith('login_'):
            challenge=await sync_to_async(lambda:AuthChallenge.objects.select_related('link_account').filter(token_hash=hashlib.sha256(parts[1][6:].encode()).hexdigest(),expires_at__gt=timezone.now(),consumed_at__isnull=True,approved_at__isnull=True).first())()
            return await auth_prompt(message,message.from_user,challenge)
        pending={'referral_code':parts[1][4:]} if len(parts)>1 and parts[1].startswith('ref_') else {}
        await on_ready(message,message.from_user,await sync_to_async(chosen_locale)(message.from_user.id),pending)

    @dp.message(Command('menu'))
    async def menu_command(message): await home(message,await account_for(message.from_user))
    @dp.message(Command('tools'))
    async def tools(message): await menu(message,await account_for(message.from_user))
    @dp.message(Command('settings'))
    async def settings_command(message):
        account=await account_for(message.from_user)
        draft=await sync_to_async(lambda:BotDraft.objects.filter(account=account).first())()
        await controls(message,account,draft) if draft else await account_view(message,account)

    async def input_prompt(message,account,payload,edit=False):
        from django.db import transaction
        def prepare():
            with transaction.atomic():
                draft=bound_draft(account,payload)
                set_prompt(account,'input',{**snapshot(draft),'kind':payload['kind']})
        await sync_to_async(prepare)()
        key={'pages':'pages_prompt','reorder':'reorder_prompt','split':'split_prompt','order':'order_prompt','remove':'remove_prompt','margin':'margin_prompt'}[payload['kind']]
        await render(message,text(account,key),[await nav(account),[await button(account,'cancel_button','cancel',payload)]],edit)

    async def cancel_prompt(message,account,new=False,edit=False,binding=None):
        draft=await sync_to_async(draft_for)(account)
        payload=binding or snapshot(draft)
        await render(message,text(account,'new_question' if new else 'cancel_question'),[[await button(account,'new_confirm' if new else 'cancel_confirm','discard',{**payload,'new':new})],[await button(account,'keep_task','controls'),await button(account,'home','home')]],edit)

    async def support_prompt(message,account,payment=False,edit=False):
        await sync_to_async(set_prompt)(account,'support',{'payment':payment})
        await render(message,text(account,'support_prompt'),[[await button(account,'home','home'),await button(account,'cancel_button','cancel')]],edit)

    async def support_review(message,account,value,payment=False):
        if not 5<=len(value)<=4000: return await message.answer(text(account,'support_prompt'))
        nonce=secrets.token_urlsafe(12)
        await sync_to_async(set_prompt)(account,'support_review',{'payment':payment,'message':value,'nonce':nonce})
        await render(message,f'{text(account,"support_confirm")}\n\n{html.escape(value[:2800])}',[[await button(account,'support_send','support_send',{'nonce':nonce})],[await button(account,'support_edit','support',{'payment':payment}),await button(account,'home','home')]])

    async def help_view(message,account,edit=False):
        await sync_to_async(set_prompt)(account)
        await render(message,text(account,'guide'),[[await button(account,'support_button','support'),await button(account,'payment_help','support',{'payment':True})],[InlineKeyboardButton(text=text(account,'open'),url=await web_url(account))],[await button(account,'home','home')]],edit)

    async def account_view(message,account,edit=False):
        await sync_to_async(set_prompt)(account)
        usage=await sync_to_async(usage_snapshot)(account)
        methods=['Telegram'] if account.telegram_user_id else []
        if account.email: methods.append('Email')
        if account.google_sub: methods.append('Google')
        meters=usage['meters']
        body=f'<b>{text(account,"account")}</b>\n{text(account,"plan_label")}: {html.escape(account.plan.title())}\n{text(account,"linked_methods")}: {", ".join(methods)}\n\n'+ '\n'.join(f'{text(account,label)}: {meters[key]["remaining"]} / {meters[key]["limit"]}' for key,label in [('file_tasks','file_tasks'),('file_page_units','page_units'),('ai_credits','ai_credits')])+f'\n{usage["resets_at"]:%Y-%m-%d %H:%M} UTC\n\n{text(account,"link_instructions")}'
        await render(message,body,[[await button(account,'plans','plans'),await button(account,'subscription','subscription')],[InlineKeyboardButton(text=text(account,'link_methods'),url=await web_url(account,'settings'))],[await button(account,'language_button','language'),await button(account,'home','home')]],edit)

    @dp.callback_query()
    async def click(query):
        ref=await sync_to_async(lambda:BotCallback.objects.select_related('account').filter(token=query.data,expires_at__gt=timezone.now()).first())()
        if not ref: return await query.answer(text(sender_language(query.from_user),'controls_expired'),show_alert=True)
        if ref.action=='link_login':
            if ref.payload.get('telegram_user_id')!=query.from_user.id or not query.message or query.message.chat.type!='private' or query.message.chat.id!=query.from_user.id:
                return await query.answer(text(sender_language(query.from_user),'controls_expired'),show_alert=True)
            await query.answer()
            try:
                account=await sync_to_async(approve_challenge_id)(ref.payload['challenge_id'],user_dict(query.from_user))
                locale=await sync_to_async(chosen_locale)(query.from_user.id)
                await query.message.answer(text(SimpleNamespace(locale=locale or account.locale),'link_approved'))
            except DomainError as exc: await safe_error(query.message,ref.account,exc)
            return
        if ref.account.telegram_user_id!=query.from_user.id: return await query.answer(text(sender_language(query.from_user),'controls_expired'),show_alert=True)
        await query.answer()  # Stop Telegram's spinner before any costly action.
        account=await account_for(query.from_user);message=query.message;p=ref.payload;action=ref.action
        try:
            if action=='login':
                await sync_to_async(approve_challenge_id)(p['challenge_id'],user_dict(query.from_user))
                await message.answer(text(account,'approved'))
            elif action=='home': await home(message,account,True)
            elif action=='language': await show_language(message,query.from_user,{})
            elif action=='menu': await menu(message,account,p.get('page',0),p.get('category','pdf'),True)
            elif action=='controls': await controls(message,account,edit=True)
            elif action=='tool':
                draft=await sync_to_async(configure)(account,feature_id=p['feature_id'],binding=p)
                await controls(message,account,draft,True)
            elif action=='settings':
                draft=await sync_to_async(configure)(account,parameters=p['parameters'],replace=p.get('replace',False),binding=p)
                await controls(message,account,draft,True)
            elif action=='prompt': await input_prompt(message,account,p,True)
            elif action=='attach':
                asset=await sync_to_async(lambda:FileAsset.objects.get(account=account,pk=p['asset_id']))()
                draft,_=await sync_to_async(attach_input)(account,asset,p['chat_id'],p['message_id'],p['mode'],p)
                await controls(message,account,draft,True)
            elif action in ('preview','run'):
                def authorize():
                    from django.db import transaction
                    with transaction.atomic():
                        draft=bound_draft(account,p)
                        if action=='preview' and p['asset_id'] not in draft.input_ids: raise DomainError('controls_expired',409)
                        if action=='run' and str(draft.quote_id)!=p['quote_id']: raise DomainError('controls_expired',409)
                await sync_to_async(authorize)()
                if action=='preview': await send_preview(message,account,p['asset_id'],p['page'])
                else: await run(message,account,p['quote_id'])
            elif action=='done': await review(message,account,p,True)
            elif action=='retry':
                draft=await sync_to_async(configure)(account,binding=p)
                await controls(message,account,draft,True)
            elif action in ('cancel','new'): await cancel_prompt(message,account,action=='new',True,p if 'draft_id' in p else None)
            elif action=='discard':
                await sync_to_async(discard_draft)(account,p)
                await home(message,account,True,notice='' if p.get('new') else text(account,'cancel'))
            elif action=='recent': await recent(message,account,True)
            elif action in ('job','download'):
                job=await sync_to_async(lambda:Job.objects.filter(account=account,pk=p['job_id']).first())()
                if not job: raise DomainError('controls_expired',409)
                await job_status(message,account,job,True)
                if action=='download' and job.status=='succeeded': await deliver(message,account,job,ref.token)
            elif action=='account': await account_view(message,account,True)
            elif action=='plans': await show_offers(message,account)
            elif action=='subscription': await show_subscription(message,account)
            elif action=='help': await help_view(message,account,True)
            elif action=='support': await support_prompt(message,account,p.get('payment',False),True)
            elif action=='support_send':
                def save_ticket():
                    from django.db import transaction
                    with transaction.atomic():
                        conversation=BotConversation.objects.select_for_update().get(pk=account.telegram_user_id)
                        if conversation.state!='support_review' or conversation.prompt.get('nonce')!=p['nonce']: raise DomainError('controls_expired',409)
                        ticket=SupportTicket.objects.create(account=account,subject='Telegram support',message=conversation.prompt['message'],category='payments' if conversation.prompt.get('payment') else 'general')
                        set_prompt(account)
                        return str(ticket.id)[:8]
                reference=await sync_to_async(save_ticket)()
                await home(message,account,True,notice=text(account,'support_saved').format(reference=reference))
        except DomainError as exc: await safe_error(message,account,exc)

    @dp.message(F.document | F.photo)
    async def receive(message,bot):
        account=await account_for(message.from_user)
        duplicate=await sync_to_async(lambda:BotInputReceipt.objects.filter(account=account,chat_id=message.chat.id,message_id=message.message_id).exists())()
        if duplicate: return await controls(message,account)
        doc=message.document or message.photo[-1]
        if (doc.file_size or 0)>20*1024*1024: return await safe_error(message,account,DomainError('bot_transport_limit'))
        name=(message.document.file_name or 'document') if message.document else 'photo.jpg'
        ext=name.rsplit('.',1)[-1].lower()
        if ext not in ('pdf','jpg','jpeg','png','docx','pptx'): return await message.answer(text(account,'unsupported'))
        stream=io.BytesIO()
        try:
            await bot.download(doc,destination=stream)
        except (TelegramAPIError,OSError,TimeoutError):
            return await home(message,account,notice=text(account,'download_error'))
        try:
            asset=await sync_to_async(upload_file)(account,SimpleUploadedFile(name,stream.getvalue()),'bot')
            draft=await sync_to_async(draft_for)(account)
            kind=asset.metadata.get('kind')
            if not draft.input_ids and draft.feature_id=='pdf.merge' and kind!='pdf':
                feature={'image':'pdf.images_to_pdf','docx':'convert.word_to_pdf','pptx':'convert.pptx_to_pdf'}.get(kind,'pdf.merge')
                draft=await sync_to_async(configure)(account,feature_id=feature)
            expected={'pdf.images_to_pdf':'image','convert.word_to_pdf':'docx','convert.pptx_to_pdf':'pptx'}.get(draft.feature_id,'pdf')
            if kind!=expected:
                await message.answer(text(account,'wrong_file'))
                return await controls(message,account,draft)
            if draft.input_ids and draft.quote_id:
                rows=[]
                for mode,label in [('add','add'),('new','new')]:
                    rows.append([await button(account,label,'attach',{**snapshot(draft),'asset_id':str(asset.id),'chat_id':message.chat.id,'message_id':message.message_id,'mode':mode})])
                await render(message,text(account,'new_file'),rows)
            else:
                draft,_=await sync_to_async(attach_input)(account,asset,message.chat.id,message.message_id)
                if message.photo: await message.answer(text(account,'photo_hint'))
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
    async def myfiles(message): await recent(message,await account_for(message.from_user))

    @dp.message(Command('plan','usage','account'))
    async def plan(message): await account_view(message,await account_for(message.from_user))

    @dp.message(Command('support','paysupport'))
    async def support(message):
        account=await account_for(message.from_user)
        parts=message.text.split(maxsplit=1);payment=parts[0].startswith('/paysupport')
        if len(parts)>1: return await support_review(message,account,parts[1],payment)
        await support_prompt(message,account,payment)

    @dp.message(Command('cancel'))
    async def cancel(message): await cancel_prompt(message,await account_for(message.from_user))

    @dp.message(Command('web','create','study','school','teach','editor'))
    async def open_workspace_mode(message):
        from urllib.parse import urlencode
        account=await account_for(message.from_user)
        command=message.text.split()[0].split('@')[0][1:]
        await sync_to_async(set_prompt)(account)
        url=await web_url(account,'' if command=='web' else command)
        draft=await sync_to_async(lambda:BotDraft.objects.filter(account=account).first())()
        if draft and draft.input_ids and command!='web': url+='?'+urlencode({'file_id':draft.input_ids[0]})
        await render(message,text(account,'web_hint'),[[InlineKeyboardButton(text=text(account,'open'),url=url)],[await button(account,'home','home')]])

    @dp.message(Command('help','terms','password'))
    async def help_(message):
        account=await account_for(message.from_user)
        if message.text.startswith('/password'): return await safe_error(message,account,DomainError('secure_password_entry_required'))
        if message.text.startswith('/terms'): return await render(message,text(account,'terms'),[[await button(account,'payment_help','support',{'payment':True})],[await button(account,'home','home')]])
        await help_view(message,account)

    @dp.message(F.text)
    async def fallback(message):
        account=await account_for(message.from_user)
        conversation=await sync_to_async(lambda:BotConversation.objects.get(pk=message.from_user.id))()
        if conversation.updated_at<timezone.now()-timedelta(minutes=30):
            await sync_to_async(set_prompt)(account)
            return await home(message,account,notice=text(account,'controls_expired'))
        value=(message.text or '').strip()
        if conversation.state=='support': return await support_review(message,account,value,conversation.prompt.get('payment',False))
        if conversation.state=='input':
            p=conversation.prompt;kind=p.get('kind')
            try:
                if kind in ('order','remove'):
                    draft=await sync_to_async(order_inputs)(account,[int(v.strip())-1 for v in value.split(',')] if kind=='order' else [],int(value)-1 if kind=='remove' else None,binding=p)
                else:
                    parameters={'pages':value} if kind=='pages' else {'order':[int(v.strip()) for v in value.split(',')]} if kind=='reorder' else {'ranges':[v.strip() for v in value.split(';')]} if kind=='split' else {'margin':float(value)}
                    draft=await sync_to_async(configure)(account,parameters=parameters,binding=p)
                return await controls(message,account,draft)
            except (ValueError,IndexError):
                await message.answer(text(account,'prompt_invalid'))
            except DomainError as exc:
                if exc.code=='controls_expired':
                    await sync_to_async(set_prompt)(account)
                    return await safe_error(message,account,exc)
                await safe_error(message,account,exc)
            return await input_prompt(message,account,p)
        await home(message,account,notice=text(account,'fallback'))
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
