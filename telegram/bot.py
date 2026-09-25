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
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, BufferedInputFile, BotCommand, Message, Chat
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

from .ux_copy import UX, STATUS, LEGACY_COPY, TOOL_NAMES
from .errors import bot_error
COPY={locale:{**LEGACY_COPY[locale],**UX[locale]} for locale in UX}

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
    await message.answer(text(account,key) if key else bot_error(exc,account.locale),reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None)

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
        if key=='paper_size' and value=='original': value=text(account,'original')
        if value=='all': value=text(account,'all_pages')
        value=str(value)
        if len(value)>180: value=value[:177]+'…'
        result.append(html.escape(f'{label}: {value}' if label else value))
    return '\n'.join(result) or text(account,'options_default')

def build_dispatcher():
    from .workflows import draft_for,configure,snapshot,bound_draft,quote_draft,run_quote,attach_input,order_inputs,discard_draft,choose_tool,start_tool,discard_finished_draft,accept_upload
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

    async def tool_button(account,draft,feature):
        return InlineKeyboardButton(text=TOOL_NAMES[feature][account.locale],callback_data=await callback(account,'tool',{**snapshot(draft),'feature_id':feature}))

    async def home(message,account,edit=False,notice=''):
        await sync_to_async(set_prompt)(account)
        draft=await sync_to_async(draft_for)(account)
        submitted=await sync_to_async(lambda:Job.objects.filter(account=account,quote_id=draft.quote_id).exists() if draft.quote_id else False)()
        rows=[]
        if draft.input_ids and not submitted: rows.append([await button(account,'continue_task','controls')])
        available={f['id'] for f in await sync_to_async(catalog)(account)}
        quick=[key for key in ('pdf.merge','pdf.compress','pdf.images_to_pdf','pdf.to_images') if key in available]
        for index in range(0,len(quick),2): rows.append([await tool_button(account,draft,key) for key in quick[index:index+2]])
        rows.extend([
            [await button(account,'all_tools','menu'),await button(account,'recent','recent')],
            [await button(account,'account','account'),await button(account,'help_button','help')],
            [await button(account,'language_button','language'),InlineKeyboardButton(text=text(account,'open'),url=await web_url(account))],
        ])
        body=(html.escape(notice)+'\n\n' if notice else '')+f'<b>👋 PDF Master</b>\n{text(account,"home_body")}'
        await render(message,body,rows,edit)

    async def menu(message,account,page=0,category='all',edit=False,pdf_only=False):
        await sync_to_async(set_prompt)(account)
        ids=['pdf.merge','pdf.compress','pdf.split','pdf.rotate','pdf.extract_pages','pdf.delete_pages','pdf.reorder']
        if not pdf_only: ids+=['pdf.images_to_pdf','pdf.to_images','convert.word_to_pdf','convert.pptx_to_pdf']
        else: ids+=['pdf.to_images']
        available={f['id'] for f in await sync_to_async(catalog)(account)}
        ids=[key for key in ids if key in available]
        draft=await sync_to_async(draft_for)(account)
        rows=[]
        for index in range(0,len(ids),2): rows.append([await tool_button(account,draft,key) for key in ids[index:index+2]])
        rows.append([await button(account,'home','home'),InlineKeyboardButton(text=text(account,'web_tools'),url=await web_url(account))])
        body=text(account,'choose_pdf_action' if pdf_only else 'choose_tool')
        if pdf_only:
            names=await sync_to_async(lambda:list(FileAsset.objects.filter(account=account,id__in=draft.input_ids).values_list('name',flat=True)))()
            body='📎 '+html.escape(names[0][:100] if names else '')+'\n'+body
        await render(message,body,rows,edit)

    async def controls(message,account,draft=None,edit=False,advanced=False):
        await sync_to_async(set_prompt)(account)
        draft=draft or await sync_to_async(draft_for)(account)
        if draft.state=='choosing_tool' and draft.input_ids:
            return await menu(message,account,edit=edit,pdf_only=True)
        submitted=await sync_to_async(lambda:Job.objects.filter(account=account,quote_id=draft.quote_id).first() if draft.quote_id else None)()
        if submitted: return await job_status(message,account,submitted,edit)
        binding=snapshot(draft);feature=draft.feature_id
        async def choice(label,parameters,replace=False):
            selected=bool(parameters) and all(draft.parameters.get(key)==value for key,value in parameters.items())
            return InlineKeyboardButton(text=('✅ ' if selected else '')+label,callback_data=await callback(account,'settings',{**binding,'parameters':parameters,'replace':replace,'advanced':advanced}))
        async def prompt(label,kind): return await button(account,label,'prompt',{**binding,'kind':kind})
        rows=[]
        files=await sync_to_async(lambda:{str(a.id):a for a in FileAsset.objects.filter(account=account,id__in=draft.input_ids)})()
        title=TOOL_NAMES.get(feature,{}).get(account.locale,feature)
        hint='upload_merge' if feature=='pdf.merge' else 'upload_images' if feature=='pdf.images_to_pdf' else 'upload_word' if feature=='convert.word_to_pdf' else 'upload_slides' if feature=='convert.pptx_to_pdf' else 'upload_pdf'
        body=f'<b>{html.escape(title)}</b>'
        if not files or (feature=='pdf.merge' and len(files)<2): body+='\n'+text(account,hint)
        if feature not in ('pdf.merge','pdf.images_to_pdf') and len(files)>1: body+='\n'+text(account,'one_file_hint')
        if files:
            listing='\n'.join(f'{i+1}. {html.escape(files[k].name[:24])} · {files[k].page_count or "—"}' for i,k in enumerate(draft.input_ids) if k in files)
            body+=f'\n{listing}\n\n{option_summary(account,draft)}'
        quote=None;quote_error=None
        if files:
            required={'pdf.extract_pages':'pages','pdf.delete_pages':'pages','pdf.reorder':'order'}.get(feature)
            ready=(not required or required in draft.parameters) and (feature!='pdf.merge' or len(files)>=2)
            if ready:
                try: draft,quote=await sync_to_async(quote_draft)(account,binding)
                except DomainError as exc: quote_error=exc
        if quote:
            summary=await sync_to_async(quote_data)(quote)
            usage=' · '.join(f'{text(account,label)}: {quote.meters[key]}' for key,label in [('file_tasks','file_tasks'),('file_page_units','page_units'),('ai_credits','ai_credits')] if quote.meters.get(key))
            balance=' · '.join(f'{text(account,label)}: {summary["available_balances"][key]["remaining"]}' for key,label in [('file_tasks','file_tasks'),('file_page_units','page_units'),('ai_credits','ai_credits')] if quote.meters.get(key))
            body+=f'\n\n{text(account,"cost")}: {usage}\n{text(account,"available")}: {balance}\n{text(account,"expires")}: {quote.expires_at:%H:%M}\n{text(account,"tap_to_run")}'
            if summary['affordable']:
                rows.append([await button(account,'run','run',{**snapshot(draft),'quote_id':str(quote.id)})])
            else:
                body+='\n'+text(account,'quota_hint')
                rows.append([await button(account,'plans','plans')])
        if quote_error:
            body+='\n\n'+html.escape(bot_error(quote_error,account.locale))
            if quote_error.code in ('password_required','unlock_first','secure_password_entry_required'):
                rows.append([InlineKeyboardButton(text=text(account,'open'),url=await web_url(account))])
        if feature=='pdf.rotate': rows.append([await choice(f'{angle}°',{'angle':angle}) for angle in (90,180,270)])
        if feature=='pdf.to_images' and advanced:
            rows.append([await choice(value.upper(),{'format':value}) for value in ('png','jpg')])
            rows.append([await choice(f'{dpi} DPI',{'dpi':dpi}) for dpi in (72,96,150,200)])
        if feature=='pdf.images_to_pdf' and advanced:
            rows.append([await choice(text(account,'original') if value=='original' else value,{'paper_size':value}) for value in ('A4','Letter','original')])
            rows.append([await choice(text(account,label),{'orientation':value}) for label,value in [('auto','auto'),('portrait','portrait'),('landscape','landscape')]])
            rows.append([await prompt('margin_button','margin')])
        if feature in ('pdf.extract_pages','pdf.delete_pages') or (feature in ('pdf.rotate','pdf.to_images') and advanced):
            rows.append([await prompt('page_selection','pages')])
            if feature in ('pdf.rotate','pdf.to_images'):
                rows[-1].append(await choice(text(account,'all_pages'),{k:v for k,v in draft.parameters.items() if k!='pages'},True))
        if feature=='pdf.split' and advanced: rows.append([await prompt('split_groups','split'),await choice(text(account,'each_page'),{},True)])
        if feature=='pdf.reorder': rows.append([await prompt('page_order','reorder')])
        if files and advanced:
            if len(files)>1: rows.append([await prompt('file_order','order'),await prompt('remove_file','remove')])
            else: rows.append([await prompt('remove_file','remove')])
            if draft.input_ids[0] in files and files[draft.input_ids[0]].mime_type=='application/pdf':
                rows.append([await button(account,'preview','preview',{**binding,'asset_id':draft.input_ids[0],'page':1})])
        if files:
            rows.append([await button(account,'back' if advanced else 'edit_options','controls',{'advanced':not advanced})])
        rows.append([await button(account,'cancel_button' if advanced else 'all_tools','cancel' if advanced else 'menu'),await button(account,'home','home')])
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
            body+='\n\n'+bot_error(DomainError(job.error_code or 'processing_failed'),account.locale)
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

    async def run(message,account,quote_id,binding):
        job,_=await sync_to_async(run_quote)(account,quote_id,binding)
        if settings.LOCAL_SYNC_JOBS:
            job=await sync_to_async(execute_job)(job.id)
        if job.status=='succeeded': await deliver(message,account,job)
        else: await job_status(message,account,job)

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
        uploads=pending.get('uploads',[])
        if uploads:
            resend=bool(pending.get('resend_file'))
            for upload in uploads[:10]:
                try:
                    if upload['user_id']!=user.id or upload['chat_id']!=user.id: raise ValueError('ownership')
                    age=timezone.now().timestamp()-int(upload['date'])
                    if not -30<=age<=1800: raise ValueError('expired')
                    values={key:upload[key] for key in ('document','photo') if key in upload}
                    if len(values)!=1: raise ValueError('file')
                    incoming=Message(message_id=upload['message_id'],date=upload['date'],chat=Chat(id=user.id,type='private'),from_user=user,**values).as_(message.bot)
                except (KeyError,ValueError,TypeError):
                    resend=True
                    continue
                await receive(incoming,message.bot)
            if resend: await message.answer(text(account,'resend'))
            return
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
        await controls(message,account,draft,advanced=True) if draft else await account_view(message,account)

    async def input_prompt(message,account,payload,edit=False):
        from django.db import transaction
        def prepare():
            with transaction.atomic():
                draft=bound_draft(account,payload)
                set_prompt(account,'input',{**snapshot(draft),'kind':payload['kind']})
        await sync_to_async(prepare)()
        key={'pages':'pages_prompt','reorder':'reorder_prompt','split':'split_prompt','order':'order_prompt','remove':'remove_prompt','margin':'margin_prompt'}[payload['kind']]
        await render(message,text(account,key),[await nav(account),[await button(account,'cancel_step','cancel',payload)]],edit)

    async def cancel_prompt(message,account,new=False,edit=False,binding=None):
        conversation=await sync_to_async(lambda:BotConversation.objects.filter(pk=account.telegram_user_id).first())()
        if not new and conversation and conversation.state in ('input','support','support_review'):
            await sync_to_async(set_prompt)(account)
            if conversation.state=='input': return await controls(message,account,edit=edit)
            return await home(message,account,edit)
        draft=await sync_to_async(draft_for)(account)
        payload=binding or snapshot(draft)
        if await sync_to_async(discard_finished_draft)(account,payload):
            return await home(message,account,edit)
        await render(message,text(account,'new_question' if new else 'cancel_question'),[[await button(account,'new_confirm' if new else 'cancel_confirm','discard',{**payload,'new':new})],[await button(account,'keep_task','controls'),await button(account,'home','home')]],edit)

    async def support_prompt(message,account,payment=False,edit=False):
        await sync_to_async(set_prompt)(account,'support',{'payment':payment})
        await render(message,text(account,'support_prompt'),[[await button(account,'cancel_step','cancel'),await button(account,'home','home')]],edit)

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
        body=f'<b>{text(account,"account")}</b>\n{text(account,"plan_label")}: {html.escape(text(account,'free_plan') if account.plan=='free' else account.plan.title())}\n{text(account,"linked_methods")}: {", ".join(methods)}\n\n'+ '\n'.join(f'{text(account,label)}: {meters[key]["remaining"]} / {meters[key]["limit"]}' for key,label in [('file_tasks','file_tasks'),('file_page_units','page_units'),('ai_credits','ai_credits')])+f'\n{text(account,"resets")}: {usage["resets_at"]:%Y-%m-%d %H:%M} UTC\n\n{text(account,"link_instructions")}'
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
            elif action=='controls': await controls(message,account,edit=True,advanced=p.get('advanced',False))
            elif action=='tool':
                try:
                    draft=await sync_to_async(choose_tool)(account,p['feature_id'],p,p.get('asset_id'))
                except DomainError as exc:
                    if exc.code=='bot_tool_needs_new_files':
                        body=text(account,'new_tool_question').format(tool=html.escape(TOOL_NAMES[p['feature_id']][account.locale]))
                        return await render(message,body,[[await button(account,'new_confirm','start_tool',p)],[await button(account,'keep_task','controls')]],True)
                    if exc.code=='bot_choose_one_file':
                        draft=await sync_to_async(draft_for)(account)
                        assets=await sync_to_async(lambda:{str(item.id):item for item in FileAsset.objects.filter(account=account,id__in=draft.input_ids)})()
                        rows=[[InlineKeyboardButton(text='📎 '+assets[key].name[:40],callback_data=await callback(account,'tool',{**p,'asset_id':key}))] for key in draft.input_ids if key in assets]
                        rows.append([await button(account,'keep_task','controls')])
                        return await render(message,text(account,'choose_one_file'),rows,True)
                    raise
                await controls(message,account,draft,True)
            elif action=='start_tool':
                draft=await sync_to_async(start_tool)(account,p['feature_id'],p)
                await controls(message,account,draft,True)
            elif action=='settings':
                draft=await sync_to_async(configure)(account,parameters=p['parameters'],replace=p.get('replace',False),binding=p)
                await controls(message,account,draft,True,advanced=p.get('advanced',False))
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
                if action=='preview':
                    await sync_to_async(authorize)()
                    await send_preview(message,account,p['asset_id'],p['page'])
                else: await run(message,account,p['quote_id'],p)
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
        except (TelegramAPIError,OSError,TimeoutError,DomainError):
            return await home(message,account,notice=text(account,'download_error'))
        try:
            asset=await sync_to_async(upload_file)(account,SimpleUploadedFile(name,stream.getvalue()),'bot')
            draft=await sync_to_async(accept_upload)(account,asset,message.chat.id,message.message_id)
            await controls(message,account,draft)
        except DomainError as exc:
            if exc.code=='bot_replace_file':
                draft=await sync_to_async(draft_for)(account)
                payload={**snapshot(draft),'asset_id':str(asset.id),'chat_id':message.chat.id,'message_id':message.message_id,'mode':'replace'}
                return await render(message,text(account,'replace_file_question')+'\n'+html.escape(asset.name[:100]),[[await button(account,'replace_file','attach',payload)],[await button(account,'keep_file','controls')]])
            await safe_error(message,account,exc)
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
            await run(message,account,str(draft.quote_id),snapshot(draft))
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
        # Hand the files over so they are not uploaded a second time. The editor
        # opens one document; generation accepts at most five sources, so a
        # longer file-tool draft is truncated rather than rejected on arrival.
        if draft and draft.input_ids and command!='web':
            ids=draft.input_ids[:1 if command=='editor' else 5]
            url+='?'+urlencode({'file_id':ids},doseq=True)
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
