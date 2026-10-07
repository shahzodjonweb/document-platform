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
from apps.core.models import BotConversation, BotCallback, BotDraft, BotInputReceipt, AuthChallenge, FileAsset, Job
from apps.core.identity import resolve_account, approve_challenge_id
from apps.core.policy import catalog, usage_snapshot
from apps.core.services import upload_file, create_quote, submit_job, execute_job, storage_path, cancel_job
from apps.core import funnel, storage
from apps.core.serializers import quote_data
from apps.core.errors import DomainError, error_data

from .ux_copy import UX, STATUS, LEGACY_COPY, TOOL_NAMES, PROMPT_EXAMPLES, LOCALES
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
# A button that commits something stays valid for 30 minutes, but old messages
# stay in the chat for good, and customers scroll back and tap them. These actions only open a screen,
# or carry a snapshot of the task they act on and refuse when it has moved on,
# so they keep working however old their message is. The others — starting a
# paid task, signing in, paying, changing a renewal, sending a message,
# discarding a task — must be fresh; an old one opens the menu instead.
REUSABLE={'home','menu','account','plans','subscription','language','help','recent','controls','settings',
          'prompt','attach','preview','done','retry','cancel','new','tool','start_tool','ai_tool','ai_examples',
          'ai_revise','support','contacts','job','download','channels_check','commerce_manual_plan','commerce_manual_receipt'}
def usable(ref,now=None):
    """Whether a stored button may still be acted on."""
    return bool(ref) and (ref.expires_at>(now or timezone.now()) or ref.action in REUSABLE)
async def callback(account,action,payload=None):
    token=secrets.token_urlsafe(12)
    # Cleanup deletes a button once it expires, so one that opens a screen is
    # given long enough to still be there when someone scrolls back to it.
    lifetime=timedelta(days=30) if action in REUSABLE else timedelta(minutes=30)
    await sync_to_async(BotCallback.objects.create)(token=token,account=account,action=action,payload=payload or {},expires_at=timezone.now()+lifetime)
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
def own_message(message):
    """A screen the bot sent — the one a button was tapped on — which can be changed in place."""
    return bool(getattr(getattr(message,'from_user',None),'is_bot',False))

async def safe_error(message,account,exc):
    # A free customer who has not joined the owner's channels is shown them,
    # not an error.
    if exc.code=='channels_required' and getattr(account,'telegram_user_id',None):
        from .channels import show_gate
        return await show_gate(message,account,edit=own_message(message))
    key='secure' if exc.code in ('password_required','secure_password_entry_required') else 'controls_expired' if exc.code=='controls_expired' else None
    rows=[]
    if key=='secure': rows.append([InlineKeyboardButton(text=text(account,'open'),url=await web_url(account))])
    if getattr(account,'telegram_user_id',None):
        rows.append([await button(account,'continue_task','controls'),await button(account,'home','home')])
        if 'quota' in exc.code or 'balance' in exc.code or 'allowance' in exc.code or exc.code in ('feature_not_in_plan','daily_ai_limit'):
            rows.insert(0,[await button(account,'plans','plans')])
    body=text(account,key) if key else bot_error(exc,account.locale)
    markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
    # After a button tap the error takes that screen's place: tapping again
    # cannot stack up the same error.
    if own_message(message):
        # Best effort: a screen that is gone or cannot be changed gets a reply.
        try: return await message.edit_text(body,reply_markup=markup)
        except Exception as failure:
            if 'message is not modified' in str(failure): return None
    await message.answer(body,reply_markup=markup)

# Files sent together (an album) arrive as separate messages a moment apart,
# and each used to get its own screen. One screen answers the whole album: each
# file waits briefly, only the newest draws the screen, and a screen already
# shown for the album is edited. This works whether updates are handled one at
# a time (webhook) or side by side (polling).
ALBUM_SETTLE=0.8
_albums={}

class _Screen:
    """A message already on screen, changed through the bot handling this update."""
    def __init__(self,bot,chat_id,message_id):
        self.bot,self.chat_id,self.message_id=bot,chat_id,message_id
    async def edit_text(self,text,**kwargs):
        return await self.bot.edit_message_text(text=text,chat_id=self.chat_id,message_id=self.message_id,**kwargs)
    async def answer(self,text,**kwargs):
        return await self.bot.send_message(self.chat_id,text,**kwargs)

async def album_target(message,bot=None):
    """(message to show the screen in, edit) for this file — or (None, False)
    when a later file of the same album will show it."""
    import time
    group=getattr(message,'media_group_id',None)
    if not group: return message,False
    now=time.monotonic()
    for stale in [key for key,value in _albums.items() if now-value['at']>120]: _albums.pop(stale,None)
    entry=_albums.setdefault((message.chat.id,group),{'latest':0,'screen':None,'at':now,'said':set()})
    # The last file to arrive answers, whatever its id; exactly one does.
    entry['latest']=message.message_id;entry['at']=now
    await asyncio.sleep(ALBUM_SETTLE)
    if entry['latest']!=message.message_id: return None,False
    return (_Screen(bot,*entry['screen']),True) if entry['screen'] is not None else (message,False)

def album_shown(message,sent):
    group=getattr(message,'media_group_id',None)
    entry=_albums.get((message.chat.id,group)) if group else None
    if entry is not None and entry['screen'] is None and getattr(sent,'message_id',None): entry['screen']=(sent.chat.id,sent.message_id)

def album_first(message,what):
    """True the first time `what` happens in this album: one question per album, not one per file."""
    group=getattr(message,'media_group_id',None)
    if not group: return True
    entry=_albums.setdefault((message.chat.id,group),{'latest':message.message_id,'screen':None,'at':0,'said':set()})
    if what in entry['said']: return False
    entry['said'].add(what);return True

def set_prompt(account,state='',prompt=None):
    BotConversation.objects.filter(pk=account.telegram_user_id).update(state=state,prompt=prompt or {},updated_at=timezone.now())

def option_summary(account,draft):
    labels={'angle':'rotate_label','pages':'pages','order':'page_order','ranges':'split_groups','format':'format_label','dpi':None,'paper_size':'paper_label','orientation':None,'margin':'margin_button','auto_crop':'auto_crop_label','enhance_text':'enhance_text_label'}
    result=[]
    parameters={'auto_crop':True,'enhance_text':True,**draft.parameters} if draft.feature_id=='pdf.images_to_pdf' else draft.parameters
    for key,value in parameters.items():
        label=text(account,labels[key]) if labels.get(key) else 'DPI' if key=='dpi' else ''
        if key in ('auto_crop','enhance_text'): value=text(account,'option_on' if value else 'option_off')
        if key=='orientation': value=text(account,{'auto':'auto','portrait':'portrait','landscape':'landscape'}.get(value,'auto'))
        if isinstance(value,list): value=', '.join(map(str,value))
        if key=='angle': value=f'{value}°'
        if key=='paper_size' and value in ('fit','original'): value=text(account,'fit_page' if value=='fit' else 'original')
        if value=='all': value=text(account,'all_pages')
        value=str(value)
        if len(value)>180: value=value[:177]+'…'
        result.append(html.escape(f'{label}: {value}' if label else value))
    return '\n'.join(result) or text(account,'options_default')

def build_dispatcher():
    from .workflows import draft_for,configure,snapshot,bound_draft,quote_draft,run_quote,attach_input,order_inputs,discard_draft,choose_tool,start_tool,discard_finished_draft,accept_upload
    from . import generation as ai
    from .onboarding import install_onboarding,show_language,chosen_locale,LANGUAGES
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

    async def ai_service_button(account,feature):
        """One of the two generation services, offered directly.

        They take a description rather than a file, so they carry their own
        callback — but they are services like any other and belong in the list
        beside the rest, not behind a folder of two.
        """
        return InlineKeyboardButton(text=TOOL_NAMES[feature][account.locale],callback_data=await callback(account,'ai_tool',{'feature_id':feature}))

    async def ai_service_rows(account):
        return [[await ai_service_button(account,feature)] for feature in ai.SERVICES]

    async def home(message,account,edit=False,notice=''):
        await sync_to_async(set_prompt)(account)
        await sync_to_async(funnel.step)('bot.home',account=account)
        draft=await sync_to_async(draft_for)(account)
        submitted=await sync_to_async(lambda:Job.objects.filter(account=account,quote_id=draft.quote_id).exists() if draft.quote_id else False)()
        rows=[]
        if draft.input_ids and not submitted: rows.append([await button(account,'continue_task','controls')])
        # Four full-width buttons for what people come for: the two AI services,
        # PDF from images, and the plans. Every other tool is one tap away in All tools.
        rows.extend(await ai_service_rows(account))
        available={f['id'] for f in await sync_to_async(catalog)(account)}
        if 'pdf.images_to_pdf' in available: rows.append([await tool_button(account,draft,'pdf.images_to_pdf')])
        rows.append([await button(account,'subscribe_button','plans')])
        rows.extend([
            [await button(account,'all_tools','menu'),await button(account,'recent','recent')],
            [await button(account,'account','account'),await button(account,'contacts_button','contacts')],
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
        rows=[] if pdf_only else await ai_service_rows(account)
        for index in range(0,len(ids),2): rows.append([await tool_button(account,draft,key) for key in ids[index:index+2]])
        rows.append([await button(account,'home','home'),InlineKeyboardButton(text=text(account,'web_tools'),url=await web_url(account))])
        body=text(account,'choose_pdf_action' if pdf_only else 'choose_tool')
        if pdf_only:
            names=await sync_to_async(lambda:list(FileAsset.objects.filter(account=account,id__in=draft.input_ids).values_list('name',flat=True)))()
            body='📎 '+html.escape(names[0][:100] if names else '')+'\n'+body
        return await render(message,body,rows,edit)

    async def controls(message,account,draft=None,edit=False,advanced=False):
        await sync_to_async(set_prompt)(account)
        # Choosing a service, sending a file or changing an option all land here:
        # a customer who still has channels to join is shown only those, in
        # place of the service screen, and comes back to it after joining.
        from .channels import blocked,show_gate
        current=await blocked(account)
        if current: return await show_gate(message,account,current,resume={'kind':'controls'},edit=edit)
        draft=draft or await sync_to_async(draft_for)(account)
        if draft.state=='choosing_tool' and draft.input_ids:
            return await menu(message,account,edit=edit,pdf_only=True)
        submitted=await sync_to_async(lambda:Job.objects.filter(account=account,quote_id=draft.quote_id).first() if draft.quote_id else None)()
        if submitted: return await job_status(message,account,submitted,edit)
        binding=snapshot(draft);feature=draft.feature_id
        async def choice(label,parameters,replace=False):
            selected=bool(parameters) and all(draft.parameters.get(key)==value for key,value in parameters.items())
            return InlineKeyboardButton(text=('✅ ' if selected else '')+label,callback_data=await callback(account,'settings',{**binding,'parameters':parameters,'replace':replace,'advanced':advanced}))
        async def image_toggle(key,label):
            enabled=draft.parameters.get(key,True)
            state=text(account,'option_on' if enabled else 'option_off')
            return InlineKeyboardButton(text=f'{"✅" if enabled else "⬜"} {text(account,label)}: {state}',callback_data=await callback(account,'settings',{**binding,'parameters':{key:not enabled},'advanced':advanced}))
        async def prompt(label,kind): return await button(account,label,'prompt',{**binding,'kind':kind})
        rows=[]
        files=await sync_to_async(lambda:{str(a.id):a for a in FileAsset.objects.filter(account=account,id__in=draft.input_ids)})()
        title=TOOL_NAMES.get(feature,{}).get(account.locale,feature)
        hint='upload_merge' if feature=='pdf.merge' else 'upload_images' if feature=='pdf.images_to_pdf' else 'upload_word' if feature=='convert.word_to_pdf' else 'upload_slides' if feature=='convert.pptx_to_pdf' else 'upload_pdf'
        body=f'<b>{html.escape(title)}</b>'
        if not files or (feature=='pdf.merge' and len(files)<2): body+='\n'+text(account,hint)
        if feature=='pdf.images_to_pdf': body+='\n'+html.escape(text(account,'document_scan_hint'))
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
        if quote_error and quote_error.code=='channels_required':
            return await show_gate(message,account,resume={'kind':'controls'},edit=edit)
        if quote_error:
            body+='\n\n'+html.escape(bot_error(quote_error,account.locale))
            if quote_error.code in ('password_required','unlock_first','secure_password_entry_required'):
                rows.append([InlineKeyboardButton(text=text(account,'open'),url=await web_url(account))])
        if feature=='pdf.rotate': rows.append([await choice(f'{angle}°',{'angle':angle}) for angle in (90,180,270)])
        if feature=='pdf.to_images' and advanced:
            rows.append([await choice(value.upper(),{'format':value}) for value in ('png','jpg')])
            rows.append([await choice(f'{dpi} DPI',{'dpi':dpi}) for dpi in (72,96,150,200)])
        if feature=='pdf.images_to_pdf':
            rows.append([await image_toggle('auto_crop','auto_crop_label')])
            rows.append([await image_toggle('enhance_text','enhance_text_label')])
            if advanced:
                for values in (('fit','original'),('A4','Letter')):
                    rows.append([await choice(text(account,'fit_page' if value=='fit' else 'original') if value in ('fit','original') else value,{'paper_size':value}) for value in values])
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
        return await render(message,body,rows,edit)

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

    # --- AI generation -------------------------------------------------------
    # Two services and one message. Everything else — pages, tone, audience,
    # questions — is read out of what the customer writes.

    async def ai_studio_url(account):
        """The web studio, carrying whatever files are already in the chat."""
        from urllib.parse import urlencode
        url=await web_url(account,'create')
        staged=await sync_to_async(lambda:draft_for(account).input_ids[:5])()
        return url+('?'+urlencode({'file_id':staged},doseq=True) if staged else '')

    def ai_example(account,feature_id,index):
        return PROMPT_EXAMPLES[feature_id][index][LOCALES.index(account.locale if account.locale in LOCALES else 'en')]

    async def ai_prompt(message,account,feature_id,edit=False):
        """One screen, one question: what do you want? Examples included.

        One description is visible; the rest sit in an expandable blockquote,
        so the screen stays the length of a single example until the customer
        taps to open it. `<code>` is deliberately not nested inside the quote
        — Telegram documents inline styling as quotable content, and the
        first example stays tappable to copy where it matters most.
        """
        await sync_to_async(set_prompt)(account,'ai_input',{'feature_id':feature_id})
        title=TOOL_NAMES[feature_id][account.locale]
        samples=[ai_example(account,feature_id,index) for index in range(len(PROMPT_EXAMPLES[feature_id]))]
        body=(f'<b>{html.escape(title)}</b>\n{text(account,"ai_ask_topic")}\n'
              f'<i>{text(account,"ai_pages_hint")}</i>\n\n'
              f'{text(account,"ai_examples")}:\n\n1. <code>{html.escape(samples[0])}</code>')
        if samples[1:]:
            rest='\n\n'.join(f'{number}. {html.escape(sample)}'
                              for number,sample in enumerate(samples[1:],2))
            body+=f'\n\n<blockquote expandable>{rest}</blockquote>'
        staged=await sync_to_async(lambda:ai.sources(account,draft_for(account).input_ids))()
        if staged: body+=f'\n\n📎 {len(staged)}'
        rows=[[await button(account,'ai_examples','ai_examples',{'feature_id':feature_id})],
              [await button(account,'ai_back','home')]]
        return await render(message,body,rows,edit)

    async def ai_revise_prompt(message,account,draft_id,edit=False):
        """One screen: what should change? Everything unmentioned stays put."""
        title=await sync_to_async(ai.revisable)(account,draft_id)
        if title is None: return await safe_error(message,account,DomainError('revision_not_ready'))
        await sync_to_async(set_prompt)(account,'ai_revise',{'draft_id':str(draft_id)})
        body=(f'<b>{text(account,"ai_revise_title")}</b>\n'
              f'{text(account,"ai_revise_of")}: {html.escape(title)}\n\n'
              f'{text(account,"ai_revise_ask")}\n\n'
              f'{text(account,"ai_examples")}:\n<code>{html.escape(text(account,"ai_revise_examples"))}</code>')
        rows=[[await button(account,'ai_back','home')]]
        await render(message,body,rows,edit)

    async def ai_refused(message,account,exc,resume,again):
        """An AI request that could not be priced, said once.

        `message` is the bot's own "Preparing…" line. Channels to join replace
        it; the daily limit, or any other error, takes its place, and only an
        error the customer can fix by writing again asks the question again.
        """
        if exc.code=='channels_required':
            await sync_to_async(set_prompt)(account)
            from .channels import show_gate
            return await show_gate(message,account,resume=resume,edit=True)
        body=html.escape(bot_error(exc,account.locale))
        if exc.code=='daily_ai_limit':
            # Nothing to rewrite: the limit and the way past it, in place of "Preparing…".
            await sync_to_async(set_prompt)(account)
            return await render(message,body,[[await button(account,'plans','plans')],[await button(account,'home','home')]],True)
        await render(message,body,[],True)
        return await again()

    async def ai_revise_start(message,account,draft_id,request):
        """The change is priced and shown before anything is spent, as ever.

        `message` is the "Preparing…" line, which becomes the priced draft.
        """
        draft=None
        try:
            draft=await sync_to_async(ai.revise)(account,draft_id,request)
            _,quote=await sync_to_async(ai.quote)(account,draft.id)
        except DomainError as exc:
            resume={'kind':'ai_draft','draft_id':str(draft.id)} if draft else {}
            return await ai_refused(message,account,exc,resume,lambda:ai_revise_prompt(message,account,draft_id))
        await sync_to_async(set_prompt)(account)
        await ai_review(message,account,draft,quote,True)

    async def ai_examples(message,account,feature_id=None,edit=False):
        """What a good description looks like, in the customer's language."""
        rows=[]
        body=f'<b>{text(account,"ai_examples_title")}</b>'
        for fid in ([feature_id] if feature_id else list(ai.SERVICES)):
            body+=f'\n\n<b>{html.escape(TOOL_NAMES[fid][account.locale])}</b>'
            for index in range(len(PROMPT_EXAMPLES[fid])):
                body+=f'\n\n{index+1}. <code>{html.escape(ai_example(account,fid,index))}</code>'
            rows.append([InlineKeyboardButton(text=TOOL_NAMES[fid][account.locale],callback_data=await callback(account,'ai_tool',{'feature_id':fid}))])
        rows.append([await button(account,'ai_back','home'),
                     InlineKeyboardButton(text=text(account,'ai_open_web'),url=await ai_studio_url(account))])
        await render(message,body,rows,edit)

    async def ai_review(message,account,draft,quote,edit=False):
        """Never submit without showing this: generating spends AI credits."""
        title=TOOL_NAMES[draft.feature_id][account.locale]
        summary=await sync_to_async(quote_data)(quote)
        balances=summary['available_balances']
        usage='\n'.join(f'{text(account,label)}: {quote.meters[key]} / {balances[key]["remaining"]}'
                        for key,label in (('ai_credits','ai_credits'),('file_tasks','file_tasks'))
                        if quote.meters.get(key))
        heading=await sync_to_async(ai.title_of)(draft)
        given,asked=await sync_to_async(ai.summary)(draft)
        change=await sync_to_async(ai.change_request)(draft)
        before=await sync_to_async(ai.length_before)(draft)
        locale=await sync_to_async(ai.language_of)(draft)
        wanted,cap=await sync_to_async(ai.images_wanted)(draft)
        deck=draft.feature_id==ai.SLIDES
        unit='ai_slides' if deck else 'ai_pages'
        body=(f'<b>{text(account,"review_title")}</b>\n{html.escape(title)}\n'
              f'📄 {html.escape(heading)}\n')
        # A change says what is changing; a new document says what it is.
        if change: body+=f'✏️ {html.escape(change)}\n'
        # A change that alters the count says so: 9 → 1 must never go unseen.
        count=f'{before} → {given}' if before and before!=given else f'{given}'
        body+=f'{text(account,unit)}: {count}'
        # A clamped request is said out loud rather than quietly honoured short.
        if asked and asked>given: body+='\n'+text(account,'ai_pages_clamped').format(asked=asked,given=given)
        names=dict(LANGUAGES)
        if locale in names: body+=f'\n{text(account,"ai_language")}: {names[locale]}'
        if wanted>cap>0: body+='\n'+text(account,'ai_images_capped').format(count=cap)
        # A description asking for the other service is offered it, before anything is spent.
        other=await sync_to_async(ai.other_service)(draft)
        if other: body+='\n\n'+text(account,'ai_wrong_tool_slides' if other==ai.SLIDES else 'ai_wrong_tool_pdf')
        body+=f'\n\n{text(account,"ai_review_hint")}'
        if usage: body+=f'\n\n{text(account,"cost")} / {text(account,"available")}:\n{usage}'
        body+=f'\n{text(account,"expires")}: {quote.expires_at:%Y-%m-%d %H:%M}'
        # Rewording a change goes back to the change, not to a blank document.
        source=await sync_to_async(ai.revised_from)(draft)
        reword=(await button(account,'ai_revise','ai_revise',{'draft_id':source}) if source
                else await button(account,'ai_change_topic','ai_tool',{'feature_id':draft.feature_id}))
        rows=[[await button(account,'ai_generate','ai_run',{'quote_id':str(quote.id),'draft_id':str(draft.id)})]]
        if other:
            rows.insert(0,[await button(account,'ai_switch_slides' if other==ai.SLIDES else 'ai_switch_pdf','ai_switch',
                                        {'draft_id':str(draft.id),'feature_id':other})])
        # The count can be put right here, before anything is charged. At the
        # plan's limit the "more" button becomes the plan that gives more.
        from apps.studio.pages import ceiling
        top=await sync_to_async(ceiling)(account,'pptx' if deck else 'pdf')
        stepper=[]
        if given>1:
            stepper.append(InlineKeyboardButton(text=f'➖ {given-1}',callback_data=await callback(account,'ai_length',{'draft_id':str(draft.id),'pages':given-1})))
        if given<top:
            stepper.append(InlineKeyboardButton(text=f'➕ {given+1}',callback_data=await callback(account,'ai_length',{'draft_id':str(draft.id),'pages':given+1})))
        if stepper: rows.append(stepper)
        upsell=[]
        if given>=top or (asked and asked>given):
            more=await sync_to_async(ai.next_plan)(account,'max_generated_slides' if deck else 'max_generated_pdf_pages',max(asked or 0,given+1))
            if more: upsell.append(('ai_more_slides' if deck else 'ai_more_pages',more))
        if wanted>cap>0:
            more=await sync_to_async(ai.next_plan)(account,'max_deck_images',wanted)
            if more: upsell.append(('ai_more_images',more))
        from .billing import plan_name
        for key,(plan,limit) in upsell[:1]:
            rows.append([InlineKeyboardButton(text=text(account,key).format(count=limit,plan=plan_name(account,plan)),
                                              callback_data=await callback(account,'plans'))])
        # The language it will be written in, switchable in one tap.
        rows.append([InlineKeyboardButton(text=('✅ ' if code==locale else '')+label.split(' ',1)[0],
                                          callback_data=await callback(account,'ai_locale',{'draft_id':str(draft.id),'locale':code}))
                     for code,label in LANGUAGES])
        rows.append([reword,await button(account,'cancel_button','home')])
        await render(message,body,rows,edit)

    async def ai_start(message,account,feature_id,description):
        """One chat message in, a priced draft out. Nothing is charged yet.

        `message` is the "Preparing…" line, which becomes the priced draft.
        """
        draft=None
        # Our own example sent back unchanged would make our example, not theirs.
        if await sync_to_async(ai.is_example)(description):
            return await render(message,text(account,'ai_example_copied'),
                                [[await button(account,'ai_examples','ai_examples',{'feature_id':feature_id}),
                                  await button(account,'cancel_button','home')]],True)
        try:
            file_ids=await sync_to_async(lambda:draft_for(account).input_ids)()
            draft=await sync_to_async(ai.build)(account,feature_id,description,file_ids)
            await sync_to_async(funnel.step)('ai.described',account=account,feature=feature_id)
            _,quote=await sync_to_async(ai.quote)(account,draft.id)
        except DomainError as exc:
            # The description is kept: after joining, the customer is shown its price.
            resume={'kind':'ai_draft','draft_id':str(draft.id)} if draft else {'kind':'ai_prompt','feature_id':feature_id}
            return await ai_refused(message,account,exc,resume,lambda:ai_prompt(message,account,feature_id))
        await sync_to_async(set_prompt)(account)
        await ai_review(message,account,draft,quote,True)

    async def ai_resume(message,account,draft_id):
        """The description written before joining, priced now."""
        from apps.studio.models import GenerationDraft
        draft=await sync_to_async(lambda:GenerationDraft.objects.filter(pk=draft_id,account=account,expires_at__gt=timezone.now()).first())()
        if draft is None: return await home(message,account)
        _,quote=await sync_to_async(ai.quote)(account,draft.id)
        await ai_review(message,account,draft,quote)

    def notes(account,job):
        """What was adjusted to match the request, in the customer's language.

        A warning we have no wording for is dropped rather than shown as a bare
        code — the codes are internal.
        """
        lines=[COPY.get(account.locale,COPY['en']).get(code) for code in (job.warnings or [])]
        return '\n'.join(line for line in lines if line)

    async def deliver(message,account,job,request_key=None):
        from .delivery import enqueue,attempt
        artifacts=await sync_to_async(lambda:list(job.artifacts.select_related('file','account')))()
        for artifact in artifacts:
            key=f'resend:{request_key}:{artifact.id}' if request_key else f'job:{job.id}:{artifact.id}'
            delivery=await sync_to_async(enqueue)(artifact,key)
            await attempt(delivery.id,message.bot)
        note=notes(account,job)
        if note and not request_key: await message.answer(html.escape(note))

    async def send_preview(message,account,asset_id,page):
        from apps.core.previews import preview_asset
        preview=await sync_to_async(preview_asset)(account,asset_id,page)
        data=await sync_to_async(lambda:storage.read_bytes(preview.object_key))()
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
            note=notes(account,job)
            if note: body+='\n\n'+html.escape(note)
            if available: rows.append([await button(account,'download','download',{'job_id':str(job.id)})])
        elif job.status=='no_op': body+='\n\n'+text(account,'no_op')
        elif job.status=='failed':
            body+='\n\n'+bot_error(DomainError(job.error_code or 'processing_failed'),account.locale)
            if job.feature_id in ai.SERVICES and job.parameters.get('stage')!='outline':
                rows.append([await button(account,'retry_task','ai_retry',{'job_id':str(job.id)})])
            else:
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

    async def contacts_view(message,account,edit=False):
        """Where to reach a person: the support account and the ads account, as set in the admin."""
        from operations.integrations import contacts_config
        await sync_to_async(set_prompt)(account)
        people=await sync_to_async(contacts_config)()
        lines=[f"<b>{text(account,'contacts_title')}</b>"]
        rows=[]
        for kind,label,opener in (('support','contacts_support','contacts_write_support'),('ads','contacts_ads','contacts_write_ads')):
            if people[kind]['username']:
                lines.append(f"{text(account,label)}: @{html.escape(people[kind]['username'])}")
                rows.append([InlineKeyboardButton(text=text(account,opener),url=people[kind]['url'])])
        if len(lines)==1: lines.append(text(account,'contacts_none'))
        rows.append([await button(account,'how_it_works','help'),await button(account,'home','home')])
        await render(message,'\n'.join(lines),rows,edit)

    async def help_view(message,account,edit=False):
        await sync_to_async(set_prompt)(account)
        await render(message,text(account,'guide'),[[await button(account,'contacts_button','contacts')],[InlineKeyboardButton(text=text(account,'open'),url=await web_url(account))],[await button(account,'home','home')]],edit)

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
        ref=await sync_to_async(lambda:BotCallback.objects.select_related('account').filter(token=query.data).first())()
        if ref and ref.action=='link_login':
            if ref.expires_at<=timezone.now() or ref.payload.get('telegram_user_id')!=query.from_user.id or not query.message or query.message.chat.type!='private' or query.message.chat.id!=query.from_user.id:
                return await query.answer(text(sender_language(query.from_user),'controls_expired'),show_alert=True)
            await query.answer()
            try:
                account=await sync_to_async(approve_challenge_id)(ref.payload['challenge_id'],user_dict(query.from_user))
                locale=await sync_to_async(chosen_locale)(query.from_user.id)
                await query.message.answer(text(SimpleNamespace(locale=locale or account.locale),'link_approved'))
            except DomainError as exc: await safe_error(query.message,ref.account,exc)
            return
        if ref and ref.account.telegram_user_id!=query.from_user.id: return await query.answer(text(sender_language(query.from_user),'controls_expired'),show_alert=True)
        await query.answer()  # Stop Telegram's spinner before any costly action.
        if not usable(ref):
            # An old button for something that has to be fresh, or one no longer
            # known: its message becomes the menu rather than a dead end.
            account=await account_for(query.from_user)
            await sync_to_async(set_prompt)(account)
            try: return await home(query.message,account,True,notice=text(account,'stale_button'))
            except Exception: return await home(query.message,account,notice=text(account,'stale_button'))
        account=await account_for(query.from_user);message=query.message;p=ref.payload;action=ref.action
        try:
            if action=='login':
                await sync_to_async(approve_challenge_id)(p['challenge_id'],user_dict(query.from_user))
                await message.answer(text(account,'approved'))
            elif action=='home': await home(message,account,True)
            elif action=='language': await show_language(message,query.from_user,{})
            elif action=='menu': await menu(message,account,p.get('page',0),p.get('category','pdf'),True)
            elif action=='controls': await controls(message,account,edit=True,advanced=p.get('advanced',False))
            elif action=='ai_examples': await ai_examples(message,account,p.get('feature_id'),True)
            elif action=='ai_revise': await ai_revise_prompt(message,account,p['draft_id'],True)
            elif action=='ai_retry':
                draft,quote=await sync_to_async(ai.retry)(account,ref.token)
                existing=await sync_to_async(ai.submitted)(account,quote.id)
                await sync_to_async(set_prompt)(account)
                if existing: await job_status(message,account,existing,True)
                else: await ai_review(message,account,draft,quote,True)
            elif action=='ai_tool':
                await sync_to_async(funnel.step)('service.chosen',account=account,feature=p['feature_id'])
                try: await sync_to_async(ai.available)(account,p['feature_id'])
                except DomainError as exc: await safe_error(message,account,exc)
                else:
                    from .channels import blocked,show_gate
                    current=await blocked(account)
                    if current: await show_gate(message,account,current,resume={'kind':'ai_prompt','feature_id':p['feature_id']},edit=True)
                    else: await ai_prompt(message,account,p['feature_id'],True)
            elif action=='ai_switch':
                try: draft,quote=await sync_to_async(ai.switch)(account,p['draft_id'],p['feature_id'])
                except DomainError as exc: await safe_error(message,account,exc)
                else: await ai_review(message,account,draft,quote,True)
            elif action in ('ai_length','ai_locale'):
                change=ai.resize if action=='ai_length' else ai.relocale
                value=p['pages'] if action=='ai_length' else p['locale']
                try: draft,quote=await sync_to_async(change)(account,p['draft_id'],value)
                except DomainError as exc: await safe_error(message,account,exc)
                else: await ai_review(message,account,draft,quote,True)
            elif action=='ai_run':
                existing=await sync_to_async(ai.submitted)(account,p['quote_id'])
                job=existing or await sync_to_async(ai.start)(account,p['quote_id'])
                await sync_to_async(set_prompt)(account)
                if settings.LOCAL_SYNC_JOBS and not existing:
                    job=await sync_to_async(execute_job)(job.id)
                if job.status=='succeeded': await deliver(message,account,job)
                else: await job_status(message,account,job,True)
            elif action=='tool':
                await sync_to_async(funnel.step)('service.chosen',account=account,feature=p['feature_id'])
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
            elif action=='plans': await show_offers(message,account,True)
            elif action=='channels_check':
                from .channels import check as check_channels
                if await check_channels(message,account,p):
                    kind=p.get('kind')
                    if kind=='ai_draft': await ai_resume(message,account,p['draft_id'])
                    elif kind=='ai_prompt': await ai_prompt(message,account,p['feature_id'])
                    elif kind=='controls': await controls(message,account)
                    else:
                        # Refused somewhere else: a file task still waiting, or the menu.
                        draft=await sync_to_async(draft_for)(account)
                        await (controls(message,account,draft) if draft.input_ids else home(message,account))
            elif action=='subscription': await show_subscription(message,account,True)
            elif action=='help': await help_view(message,account,True)
            # `support` and `support_send` are buttons on messages from before tickets were retired.
            elif action in ('contacts','support','support_send'): await contacts_view(message,account,True)
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
        # A receipt for a card payment is not a document for the PDF tools: it
        # goes to the payment before it could become an ordinary upload.
        waiting=await sync_to_async(lambda:BotConversation.objects.filter(pk=message.from_user.id,state='payment_receipt').values_list('prompt',flat=True).first())()
        if waiting is not None:
            from .billing import receive_receipt
            return await receive_receipt(message,account,(waiting or {}).get('payment_id'),stream.getvalue())
        try:
            asset=await sync_to_async(upload_file)(account,SimpleUploadedFile(name,stream.getvalue()),'bot')
            # A file sent while an AI tool is waiting belongs to that tool, not
            # to the file-tool draft the upload would otherwise start.
            conversation=await sync_to_async(lambda:BotConversation.objects.get(pk=message.from_user.id))()
            if conversation.state=='ai_input':
                pending=conversation.prompt
                await sync_to_async(attach_input)(account,asset,message.chat.id,message.message_id)
                target,edit=await album_target(message,bot)
                if target is None: return
                return album_shown(message,await ai_prompt(target,account,pending['feature_id'],edit))
            draft=await sync_to_async(accept_upload)(account,asset,message.chat.id,message.message_id)
            # The file is kept either way. controls() shows the channels to join
            # instead, when there are any, and "I've joined" comes back here.
            target,edit=await album_target(message,bot)
            if target is None: return
            album_shown(message,await controls(target,account,None,edit))
        except DomainError as exc:
            if not album_first(message,exc.code): return
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

    @dp.message(Command('support','paysupport','contacts'))
    async def support(message):
        await contacts_view(message,await account_for(message.from_user))

    @dp.message(Command('cancel'))
    async def cancel(message): await cancel_prompt(message,await account_for(message.from_user))

    # Making a document happens in the chat; editing a PDF is a canvas and
    # stays on the web.
    AI_COMMANDS={'create':ai.DOCUMENT,'document':ai.DOCUMENT,'slides':ai.SLIDES}

    @dp.message(Command('ai','create','document','slides','examples'))
    async def open_ai_mode(message):
        account=await account_for(message.from_user)
        command=message.text.split()[0].split('@')[0][1:]
        if command=='examples': return await ai_examples(message,account)
        feature_id=AI_COMMANDS.get(command)
        if not feature_id: return await home(message,account)
        await ai_prompt(message,account,feature_id)

    @dp.message(Command('web','editor'))
    async def open_workspace_mode(message):
        from urllib.parse import urlencode
        account=await account_for(message.from_user)
        command=message.text.split()[0].split('@')[0][1:]
        await sync_to_async(set_prompt)(account)
        url=await web_url(account,'' if command=='web' else command)
        draft=await sync_to_async(lambda:BotDraft.objects.filter(account=account).first())()
        # Hand the file over so it is not uploaded a second time. The editor
        # opens exactly one document; /web is the home page and carries nothing.
        if draft and draft.input_ids and command=='editor':
            url+='?'+urlencode({'file_id':draft.input_ids[:1]},doseq=True)
        await render(message,text(account,'web_hint'),[[InlineKeyboardButton(text=text(account,'open'),url=url)],[await button(account,'home','home')]])

    @dp.message(Command('help','terms','password'))
    async def help_(message):
        account=await account_for(message.from_user)
        if message.text.startswith('/password'): return await safe_error(message,account,DomainError('secure_password_entry_required'))
        if message.text.startswith('/terms'): return await render(message,text(account,'terms'),[[await button(account,'contacts_button','contacts')],[await button(account,'home','home')]])
        await help_view(message,account)

    @dp.message(F.text)
    async def fallback(message):
        account=await account_for(message.from_user)
        conversation=await sync_to_async(lambda:BotConversation.objects.get(pk=message.from_user.id))()
        if conversation.state and conversation.updated_at<timezone.now()-timedelta(minutes=30):
            await sync_to_async(set_prompt)(account)
            return await home(message,account,notice=text(account,'stale_reply'))
        value=(message.text or '').strip()
        # Someone who was writing a support message when tickets were retired.
        if conversation.state in ('support','support_review'): return await contacts_view(message,account)
        if conversation.state=='ai_input':
            p=conversation.prompt
            if not value: return await message.answer(text(account,'ai_topic_empty'))
            waiting=await message.answer(text(account,'ai_preparing'))
            return await ai_start(waiting,account,p['feature_id'],value)
        if conversation.state=='ai_revise':
            p=conversation.prompt
            if not value: return await message.answer(text(account,'ai_topic_empty'))
            waiting=await message.answer(text(account,'ai_preparing'))
            return await ai_revise_start(waiting,account,p['draft_id'],value)
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
