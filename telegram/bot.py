"""Telegram transport over the same domain services as the browser.

Run with `python manage.py runbot`; no network traffic occurs at import time.
"""
import asyncio
import hashlib
import html
import io
import json
import logging
import secrets
import time
import uuid
import weakref
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
from apps.core.services import upload_file, create_quote, submit_job, execute_job, storage_path, cancel_job, RETIRED_IMAGE_SWITCHES
from apps.core import funnel, storage
from apps.core.serializers import quote_data
from apps.core.errors import DomainError, error_data
from apps.core.allowance import LIMIT_CODES

from .ux_copy import UX, STATUS, LEGACY_COPY, TOOL_NAMES, PROMPT_EXAMPLES, LOCALES, counted
from .errors import bot_error
from .clock import local_time, stamp, week_reset
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
          'ai_revise','ai_count','ai_retarget','support','contacts','job','download','channels_check',
          'commerce_manual_plan','commerce_manual_receipt','cv_mode','cv_wait_check'}
def usable(ref,now=None):
    """Whether a stored button may still be acted on."""
    return bool(ref) and (ref.expires_at>(now or timezone.now()) or ref.action in REUSABLE)
def retired_switch(ref):
    """An old crop or enhance button from images to PDF (6-11 Oct 2026): core
    0018 marked the stored ones; the keys themselves are checked as well."""
    p=ref.payload if ref and ref.action=='settings' else {}
    return p.get('retired')=='scan_switches' or bool(set(p.get('parameters') or {})&set(RETIRED_IMAGE_SWITCHES))
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
# A plans button under a used-up weekly or edit limit. Each plans button says
# where it is, so the admin can count where the plans are opened from.
FROM_LIMIT={'from':'limit'}
def own_message(message):
    """A screen the bot sent — the one a button was tapped on — which can be changed in place."""
    return bool(getattr(getattr(message,'from_user',None),'is_bot',False))

async def safe_error(message,account,exc):
    # A Free or Plus customer who has not joined the owner's channels is shown them,
    # not an error.
    if exc.code=='channels_required' and getattr(account,'telegram_user_id',None):
        from .channels import show_gate
        return await show_gate(message,account,edit=own_message(message))
    key='secure' if exc.code in ('password_required','secure_password_entry_required') else 'controls_expired' if exc.code=='controls_expired' else 'ai_format_only' if exc.code=='format_only_change' else None
    rows=[]
    if key=='secure': rows.append([InlineKeyboardButton(text=text(account,'open'),url=await web_url(account))])
    if getattr(account,'telegram_user_id',None):
        rows.append([await button(account,'continue_task','controls'),await button(account,'home','home')])
        # Only a used-up weekly allowance is something a plan buys. Every plan has
        # every tool, so a tool refused for the plan reads as "not available right
        # now", and a plans button under it would sell what no plan adds.
        if exc.code in LIMIT_CODES:
            rows.insert(0,[await button(account,'plans','plans',FROM_LIMIT)])
    body=text(account,key) if key else bot_error(exc,account.locale,account)
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

def album_caption(message):
    """The caption of this file, or of the album it came in.

    Telegram puts an album's caption on its first file, and only the newest
    file answers (album_target): the caption waits in the album's entry for it.
    Asked before album_target, to keep a caption; after it, to read the one kept.
    """
    import time
    own=(message.caption or '').strip()
    group=getattr(message,'media_group_id',None)
    if not group: return own
    entry=_albums.setdefault((message.chat.id,group),{'latest':0,'screen':None,'at':time.monotonic(),'said':set()})
    if own and not entry.get('caption'): entry['caption']=own
    return own or entry.get('caption','')

# Polling handles updates side by side (aiogram's handle_as_tasks), so a photo
# and a description sent together, or the two halves of a long description,
# are worked on at once. A CV's are taken one at a time per chat, each reading
# the chat's state afresh once it has its turn: the photo then goes on the CV
# the description made, and the second half onto the first. Locks belong to
# the event loop that made them, so there is one set per loop.
_chat_locks=weakref.WeakKeyDictionary()

def chat_lock(chat_id):
    """The lock that keeps this chat's CV updates one at a time, in the running loop."""
    locks=_chat_locks.setdefault(asyncio.get_running_loop(),{})
    if len(locks)>500:
        for key in [key for key,lock in locks.items() if not lock.locked()]: locks.pop(key,None)
    return locks.setdefault(chat_id,asyncio.Lock())

def album_first(message,what):
    """True the first time `what` happens in this album: one question per album, not one per file."""
    group=getattr(message,'media_group_id',None)
    if not group: return True
    entry=_albums.setdefault((message.chat.id,group),{'latest':message.message_id,'screen':None,'at':0,'said':set()})
    if what in entry['said']: return False
    entry['said'].add(what);return True

def cv_stash(message,name,raw):
    """Keep this file for the CV made from files, until its album's newest file takes them all.

    A CV is made from every file of an album, not only the newest: each waits
    in the album's entry, and the file that answers for the album (album_target)
    takes them (cv_unstash). A file on its own is returned to take itself.
    `raw` is None for a file of a kind no CV is made from, never downloaded.
    """
    import time
    item={'message_id':message.message_id,'name':name,'raw':raw,'date':message.date.timestamp(),
          'caption':(message.caption or '').strip()}
    group=getattr(message,'media_group_id',None)
    if not group: return [item]
    entry=_albums.setdefault((message.chat.id,group),{'latest':0,'screen':None,'at':time.monotonic(),'said':set()})
    entry.setdefault('files',[]).append(item)
    return []

def cv_unstash(message,own):
    """The files of this album still waiting for the CV, in the order they were sent; `own` for a file on its own."""
    group=getattr(message,'media_group_id',None)
    if not group: return own
    entry=_albums.get((message.chat.id,group)) or {}
    return sorted(entry.pop('files',[]),key=lambda item:item['message_id'])

def set_prompt(account,state='',prompt=None):
    BotConversation.objects.filter(pk=account.telegram_user_id).update(state=state,prompt=prompt or {},updated_at=timezone.now())

# A question left open this long is not answered by the next message: it goes
# to the menu instead (stale_reply).
QUESTION_LIFETIME=timedelta(minutes=30)
# A description that names no topic ("12 ta slayd kk") is refused before it is
# made or counted (apps.studio.domain.require_topic). What the customer wrote
# is kept in the chat's state, never in a button, while the topic is asked for,
# and is joined to the topic they send next. A few pieces are kept at most, so
# a customer who never names one cannot grow the description without end.
BRIEF_PIECES,BRIEF_CHARS=3,1000
# A CV's description is the CV: everything the customer wrote about themselves
# waits whole while what is missing from it is asked for. A long one is a few
# hundred words (Telegram sends at most 4096 characters at a time), far inside
# the plan's input limit (apps.studio.domain.limits source_chars).
CV_BRIEF_CHARS=12000
# A CV's facts may come a few at a time (a name, then a phone, then the job)
# while the bot asks for what is missing: more pieces are kept than for a
# topic, the first and the newest eleven.
CV_BRIEF_PIECES=12
# Text sent this soon after a new CV's review was drawn is the rest of its
# description: Telegram sends one longer than 4096 characters as two messages.
CV_APPEND_WINDOW=timedelta(minutes=2)
# A CV is made one of three ways, chosen on its first screen ('cv_choose'):
# written about yourself (the 'ai_input' question), or from the LinkedIn
# profile or the old CV sent as files ('cv_source', apps/studio/cv/sources.py).
# The extensions those files may have, by the kind the server reads them as.
CV_FILE_KINDS={'pdf':'pdf','docx':'docx','jpg':'image','jpeg':'image','png':'image'}
# A PDF or Word file sent this soon after the last of a CV's files, by when
# Telegram took each, is one more of them (cv_takes_more). A photo is one more
# while the review is not yet on screen, or in an album: after that a photo
# on its own is the portrait, or, on a CV made from photos or screenshots,
# asked about (cv_file).
CV_FILES_WINDOW=timedelta(seconds=30)
# A CV's files are read by the reader (apps/studio/cv/reads.py), never by the
# bot: each is queued for it as it is uploaded. While one is still waiting, the
# chat waits too ('cv_wait'), holding what the CV is made of. One message says
# where the files are in the queue, and becomes the review, or the question or
# refusal in its place, once they are read; more files and notes sent meanwhile
# join the CV. The bot looks at its waiting chats every CV_WAIT_POLL seconds
# (cv_wait_loop, beside the delivery loop), and says a new place in the queue
# at most every CV_WAIT_EDIT seconds, only when it moved. A wait whose place
# has not moved for CV_WAIT_LIMIT is said to take longer than usual; it is
# still looked at, every CV_WAIT_STALLED_POLL seconds, and still becomes the
# review by itself once its files are read.
CV_WAIT_POLL=2
CV_WAIT_EDIT=5
CV_WAIT_LIMIT=timedelta(minutes=10)
CV_WAIT_STALLED_POLL=30
# The chats this process waits for. The waits are kept in the database, so one
# outlives a restart: the loop finds them there when it starts.
CV_WAITING=set()
# A chat whose look Telegram could not take for a moment (a network error, its
# servers, too many requests): left alone until then, its wait unchanged, and
# looked at again after. When a stalled wait was last looked at.
CV_WAIT_PAUSED={}
CV_WAIT_LOOKED={}

def cv_waiting(conversation):
    """Whether the chat waits for its CV's files to be read, and the wait is not old (kept as long as a question)."""
    return (bool(conversation) and conversation.state=='cv_wait'
            and conversation.updated_at>=timezone.now()-QUESTION_LIFETIME)

def cv_place(status):
    """Where a CV's files are in the reader's queue, as the waiting message says it: 'now', 'next' or how many are ahead."""
    if status.get('reading'): return 'now'
    return int(status.get('ahead') or 0) or 'next'

def wait_account(chat_id):
    from apps.core.models import Account
    return Account.objects.filter(telegram_user_id=chat_id).first()

async def cv_waits_kept():
    """The waits kept in the database, for a process that starts to look at: the polling bot, or a webhook run."""
    CV_WAITING.update(await sync_to_async(lambda:list(BotConversation.objects.filter(state='cv_wait').values_list('pk',flat=True)))())

async def cv_wait_loop(bot,dispatcher):
    """The chats waiting for their CV's files, looked at every CV_WAIT_POLL seconds as long as the bot runs.

    The waits kept before a restart are found on the first turn that can
    read them: a database that refuses the first query only delays them.
    """
    kept=False
    while True:
        try:
            if not kept:
                await cv_waits_kept()
                kept=True
            await dispatcher.cv_waits(bot)
        except Exception: logging.getLogger(__name__).exception('The CV waits could not be looked at')
        await asyncio.sleep(CV_WAIT_POLL)

def cv_still_waiting(account,wait):
    """Whether the chat still waits on `wait`'s message: what a look made is kept only then, never over what the customer did meanwhile."""
    prompt=BotConversation.objects.filter(pk=account.telegram_user_id,state='cv_wait').values_list('prompt',flat=True).first()
    return prompt is not None and (prompt or {}).get('screen')==wait.get('screen')

def cv_wait_shown(account,wait,draft_id,notice):
    """The CV a wait for its files became, kept in the wait before its review is drawn ('then' 'show').

    Drawing it may fail (Telegram unreachable for a moment): the next look
    draws the same CV again and never makes another. False, and nothing
    kept, when the chat no longer waits on that message. What was added to
    the CV is in it now: nothing is left to add.
    """
    row=BotConversation.objects.filter(pk=account.telegram_user_id,state='cv_wait').values_list('prompt','updated_at').first()
    if row is None or (row[0] or {}).get('screen')!=wait.get('screen'): return False
    kept={**row[0],'then':'show','draft_id':str(draft_id),'notice':notice,'added':[],'more':[]}
    return bool(BotConversation.objects.filter(pk=account.telegram_user_id,state='cv_wait',updated_at=row[1])
                .update(prompt=kept,updated_at=timezone.now()))

def cv_wait_restored(account,wait,began):
    """A wait whose outcome Telegram did not take, put back so a later look does it again; whether it was.

    Only when this look moved the chat on to one of a CV's screens (its question
    for what is missing, a refusal, the first screen): the menu, or anything older than
    the look, is the customer's own doing and stays.
    """
    row=BotConversation.objects.filter(pk=account.telegram_user_id).values_list('state','updated_at').first()
    if row is None or row[0] not in ('cv_source','cv_choose','ai_input') or row[1]<began: return False
    return bool(BotConversation.objects.filter(pk=account.telegram_user_id,state=row[0],updated_at=row[1])
                .update(state='cv_wait',prompt=wait,updated_at=timezone.now()))

def cv_reads_dropped(account,ids):
    """The queued reads of files left out of a CV taken back: the reader never reads a file no CV takes.

    Not failed: a file left out for being one too many is not unreadable,
    and a CV that asks for it later queues it again (reads.ensure).
    """
    from apps.studio.models import CvSourceRead
    CvSourceRead.objects.filter(account=account,asset_id__in=ids,status='queued').delete()

def cv_adding(account,draft_id):
    """Whether files are still on their way to this CV (a wait to add them): it is not made without them."""
    row=BotConversation.objects.filter(pk=account.telegram_user_id,state='cv_wait').first()
    prompt=(row.prompt or {}) if cv_waiting(row) else {}
    return bool(draft_id) and prompt.get('then') in ('add','show') and prompt.get('draft_id')==str(draft_id)

def kept_brief(pieces,limit=BRIEF_CHARS,count=BRIEF_PIECES):
    """The pieces of a description kept while its topic is asked for, in the order written.

    The first stays, as it usually says what to make and how long ("12 ta
    slayd"); after it, the newest that fit in `limit` characters, `count` pieces in all.
    """
    pieces=[piece[:limit] for piece in pieces if piece]
    if not pieces: return []
    first,kept=pieces[0],[]
    for piece in reversed(pieces[1:][-(count-1):]):
        if len(first)+sum(map(len,kept))+len(piece)>limit: break
        kept.insert(0,piece)
    return [first,*kept]

def brief_quote(pieces,limit=160):
    """What was kept, on one line, as the topic question quotes it back."""
    said=' · '.join(' '.join(piece.split()) for piece in pieces)
    return said if len(said)<=limit else said[:limit-1].rstrip()+'…'

def pending_brief(account,question=None):
    """What is kept of a description still waiting for its topic; [] once that question is closed or old.

    `question` is the one a button was sent with (ai_topic_needed): a button
    left on an older question never carries what a newer one kept.
    """
    row=BotConversation.objects.filter(pk=account.telegram_user_id,state='ai_input').first()
    if row is None or row.updated_at<timezone.now()-QUESTION_LIFETIME: return []
    prompt=row.prompt or {}
    if question is not None and prompt.get('question')!=question: return []
    return list(prompt.get('brief') or [])

def pending_question(account,question):
    """The open question named `question` with what it kept — {'brief', 'ask', …} — or None once it is closed or old."""
    row=BotConversation.objects.filter(pk=account.telegram_user_id,state='ai_input').first()
    if not question or row is None or row.updated_at<timezone.now()-QUESTION_LIFETIME: return None
    prompt=row.prompt or {}
    return prompt if prompt.get('question')==question and prompt.get('brief') else None

def pending_portrait(account):
    """The photo sent for a CV still being described; '' once that question is closed or old.

    Like what was written, it waits in the chat's state, never in a button.
    The CV's first screens keep it too, while the customer chooses how the CV
    is made, and so does a wait for its files (cv_wait), for as long as a
    question is kept.
    """
    row=BotConversation.objects.filter(pk=account.telegram_user_id,state__in=('ai_input','cv_choose','cv_source','cv_wait')).first()
    if row is None or row.updated_at<timezone.now()-QUESTION_LIFETIME: return ''
    prompt=row.prompt or {}
    return str(prompt.get('portrait_asset_id') or '') if prompt.get('feature_id')=='ai.cv' else ''

def cv_brief(account):
    """What is kept of a CV described about yourself while what it lacks is asked for; [] with no such question."""
    row=BotConversation.objects.filter(pk=account.telegram_user_id,state='ai_input').first()
    if row is None or row.updated_at<timezone.now()-QUESTION_LIFETIME: return []
    prompt=row.prompt or {}
    return [str(piece) for piece in prompt.get('brief') or [] if piece] if prompt.get('feature_id')=='ai.cv' else []

def cv_asked(prompt):
    """The required facts a CV's open question asks for, from the state it was kept in; [] when it asks for none.

    A question kept before they were listed is still answered for a while
    (a state lives QUESTION_LIFETIME): `ask` 'name' asks for the name, and
    'details', which was for a description that said next to nothing, for all of them.
    """
    from apps.studio.cv.content import REQUIRED_FACTS
    prompt=prompt or {}
    ask=prompt.get('ask')
    if ask not in ('missing','name','details'): return []
    asked=[fact for fact in REQUIRED_FACTS if fact in (prompt.get('missing') or ())]
    return asked or (list(REQUIRED_FACTS) if ask=='details' else ['name'])

# The example beside each required fact on a CV's missing screen (ux_copy cv_*_sample). One with
# two ways of giving its fact has ' — ' between them, and each is shown as its own code.
CV_SAMPLE_KEYS={'name':'cv_name_sample','contact':'cv_fact_contact_sample','background':'cv_fact_background_sample'}

def compared(piece):
    """Words as the bot compares them: the same whichever way they were typed (case, spaces, line breaks)."""
    return ' '.join(str(piece or '').casefold().split())

# Every dash one hyphen, every apostrophe one: a sample typed or copied either way is the same sample.
SAMPLE_FOLDS=str.maketrans({**{char:'-' for char in '\u2010\u2011\u2012\u2013\u2014\u2015\u2212'},
                            **{char:"'" for char in '\u2018\u2019\u02bc\u02bb`'}})

def sample_form(piece):
    """Words as the sample guard compares them: no case, space or line break, one kind of dash and apostrophe.

    No space is compared at all, so "2021 - 2024", "Bahor Foods , 2021" and
    "+998901234567" are the sample's own "2021–2024", "Bahor Foods, 2021" and "+998 90 123 45 67".
    """
    return ''.join(str(piece or '').translate(SAMPLE_FOLDS).casefold().split())

def sample_ways(locale,fact):
    """The values the missing screen shows beside `fact` in `locale`: one, or the two ways of giving it."""
    return UX[locale][CV_SAMPLE_KEYS[fact]].split(' — ')

# Every value a missing screen offers to copy, in every language: a message that is nothing but these is ours.
CV_SAMPLES=frozenset(sample_form(way) for fact in CV_SAMPLE_KEYS for locale in LOCALES
                     for way in sample_ways(locale,fact))
# The phone, email, job and school the samples give, and each label of the screen's list with the word
# its example follows ("full name — e.g.", "to‘liq ism-familiya — masalan", the dash there or not), in
# every language: a message holding any of these holds our example, however often it is sent. Nobody
# has the sample's phone, address, job or school, and only a copy of the screen says "full name — e.g.".
# The name alone is ours only on its own, and only the first time (sent_back): a name like it may be the customer's.
def sample_labels(locale):
    """Each label of the missing screen's list with the word before its example, with the dash and without."""
    item=UX[locale]['cv_missing_item']
    word=item.split('{fact}',1)[1].split('{example}',1)[0].strip().lstrip('\u2014').strip().rstrip('.:')
    for fact in CV_SAMPLE_KEYS:
        label=UX[locale][f'cv_fact_{fact}']
        yield sample_form(f'{label} \u2014 {word}')
        yield sample_form(f'{label} {word}')

CV_SAMPLES_HELD=frozenset([*(sample_form(way) for fact in ('contact','background') for locale in LOCALES
                             for way in sample_ways(locale,fact)),
                           *(label for locale in LOCALES for label in sample_labels(locale))])

def sample_held(value):
    """Whether a message holds a sample's phone, email, job or school (any language), or a label of the screen's list.

    Always our example, sent once or again: never the customer's. Case,
    spaces, line breaks and the kind of dash or apostrophe are not compared
    (sample_form). A few fixed values looked for in the message, once each:
    time that grows with the message.
    """
    said=sample_form(value)
    return bool(said) and any(sample in said for sample in CV_SAMPLES_HELD)

def sent_back(value):
    """Whether a message is a sample a CV's missing screen shows, sent back: our example, not the customer's.

    It holds one of our samples (sample_held), or it is nothing but the
    sample name, line by line. Only the name is the customer's when sent again
    at once (`copied` on the screens): someone may have that name, nobody has
    the sample's phone, job or school.
    """
    if sample_held(value): return True
    lines=[sample_form(line) for line in str(value or '').split('\n')]
    lines=[line for line in lines if line]
    return bool(lines) and all(line in CV_SAMPLES for line in lines)

def tells_little(written):
    """Whether what was written for a CV, read once, says nothing about the person but who and how to reach them.

    says_little (apps/studio/cv/content.py) with every phone number and email
    taken out first: they say how to reach someone, not what they did, so
    "Dilnoza Karimova +998 90 123 45 67" tells as little as the name alone. A
    year still says something (a job's or a school's the check did not see),
    and so do a dozen words. `written` is the pieces, each once. A number
    with a year in it and no + is a period ("2019-2024"), not a phone.
    """
    from apps.studio.cv.content import EMAIL,PHONE,YEAR,says_little
    words=EMAIL.sub(' ','\n'.join(str(piece or '') for piece in written))
    words=PHONE.sub(lambda number:number.group() if YEAR.search(number.group()) and number.group()[0]!='+' else ' ',
                    words)
    return says_little(words)

def cv_insists(repeated,missing,written,answer=None):
    """Whether words sent again make a CV as they are, though the check still finds `missing` missing.

    The way past a check that does not see what is there, the same in a CV
    written about yourself and one made from files: the words are `repeated`
    (the same as words kept); while the name is missing, they look like a
    name (`answer`; None for the name-like answer the screen asks for); and
    while the job or school is missing, what was written (`written`, each
    piece once) tells more than a name, a phone and an email (tells_little).
    So a greeting, a name, or a name with a phone sent again never makes a CV,
    and a real description the check missed, sent again, does.
    """
    from apps.studio.cv.content import name_like
    return (bool(repeated) and ('name' not in missing or answer is None or name_like(answer))
            and ('background' not in missing or not tells_little(written)))

def facts_said(account,facts,between=' · '):
    """CV facts (apps/studio/cv/content.py names) said by their labels, in the order given."""
    return between.join(text(account,f'cv_fact_{fact}') for fact in facts)

def sample_shown(account,fact):
    """The example beside a missing fact: each of its values its own code, so a tap copies one, with 'or' between."""
    return f' {text(account,"cv_or")} '.join(f'<code>{html.escape(way)}</code>' for way in text(account,CV_SAMPLE_KEYS[fact]).split(' — '))

def missing_lines(account,missing,*,source=False,written=()):
    """What a CV still lacks, as its question says it: what is there, each missing fact with an example, and the way on.

    `missing` are the required facts (apps/studio/cv/content.py) the server
    found missing; none, or none it knows, asks for all of them. An example is
    code, to be copied. `source` is for a CV made from files: what is sent is
    added to them. `written` is what the customer wrote already, each piece
    once. The last line is the way past a check that did not see what is
    there, only where sending again can make the CV (cv_insists): with the
    name missing, the name alone, sent again; with only the phone or email
    missing, the same message again, which makes the CV without one; else the
    same message again. With nothing written (a file alone) no line says it
    was, and only a missing contact has a way on: any message twice. Where no
    message sent again can make it (the job or school missing, and what was
    written tells next to nothing), the line asks for more about the work or studies.
    """
    from apps.studio.cv.content import REQUIRED_FACTS
    asked=[fact for fact in REQUIRED_FACTS if fact in (missing or ())] or list(REQUIRED_FACTS)
    have=[fact for fact in REQUIRED_FACTS if fact not in asked]
    lines=[text(account,'cv_got').format(facts=facts_said(account,have))] if have else []
    lines.append(text(account,'cv_missing_title'))
    lines.extend(text(account,'cv_missing_item').format(fact=text(account,f'cv_fact_{fact}'),example=sample_shown(account,fact))
                 for fact in asked)
    lines.extend(['',text(account,'cv_missing_send_file' if source else 'cv_missing_send')])
    contact=asked==['contact']
    written=[piece for piece in written or () if piece]
    if not cv_insists(True,asked,written): again='cv_missing_more'
    elif written:
        again='cv_name_again' if 'name' in asked else 'cv_missing_again_contact' if contact else 'cv_missing_again'
    else: again='cv_missing_twice_contact' if contact else ''
    if again: lines.append(text(account,again))
    return '\n'.join(lines)

def can_add_line(account,found):
    """The line on a new CV's review for what it could still have: what it lacks, if the customer insisted, then what only adds to it.

    `found` is what the draft gives and lacks (generation.facts_of). At most
    four are named, the photo not among them (the review's own photo line
    says it); '' when there is nothing to add.
    """
    from apps.studio.cv.content import OPTIONAL_FACTS,REQUIRED_FACTS
    found=found or {}
    facts=[*(fact for fact in REQUIRED_FACTS if fact in (found.get('missing') or ())),
           *(fact for fact in OPTIONAL_FACTS if fact!='photo' and fact in (found.get('optional_missing') or ()))][:4]
    return text(account,'cv_can_add').format(facts=facts_said(account,facts)) if facts else ''

def cv_screen_open(conversation):
    """Whether the chat is on one of a CV's first screens (how to make it, or what to send for it) and it is not old.

    They are questions like the one about yourself: kept for QUESTION_LIFETIME.
    Text sent later goes to the menu (stale_reply), and a file is an ordinary
    file again, never a CV made from what someone sent days later.
    """
    return (bool(conversation) and conversation.state in ('cv_choose','cv_source')
            and conversation.updated_at>=timezone.now()-QUESTION_LIFETIME)

def cv_kept(account):
    """What a CV's first screens keep as the customer moves between them: {'notes', 'portrait_asset_id'}.

    The notes are words written for a CV made from files, before its file; the
    photo is one sent for the CV while it was being written about (pending_portrait).
    Like a question's answer, they are kept for QUESTION_LIFETIME.
    """
    row=BotConversation.objects.filter(pk=account.telegram_user_id).first()
    notes=[str(note) for note in ((row.prompt or {}).get('notes') or []) if note] if cv_screen_open(row) else []
    return {'notes':notes,'portrait_asset_id':pending_portrait(account)}

def open_cv_review(account):
    """The new CV whose review is the chat's current screen, while a photo sent now may still go on it; else ''."""
    row=BotConversation.objects.filter(pk=account.telegram_user_id,state='cv_review').first()
    if row is None or row.updated_at<timezone.now()-QUESTION_LIFETIME: return ''
    return str((row.prompt or {}).get('draft_id') or '')

def cv_refusal_said(account,exc):
    """A refusal of the files sent for a CV, as the chat says it.

    A protected PDF is a file with nothing to read in it, and too many files or
    pages are said with how many one CV is made from (apps/studio/cv/sources.py).
    """
    if exc.code=='generation_limit':
        from apps.core.policy import plan_limits
        from apps.studio.cv.sources import MAX_PAGES,max_files
        pages=min(MAX_PAGES,int(plan_limits(account)['max_ai_source_pages']))
        return text(account,'cv_files_limit').format(files=counted(account.locale,max_files(account),'file'),
                                                     pages=counted(account.locale,pages,'page'))
    code='cv_file_unreadable' if exc.code in ('password_required','password_invalid','secure_password_entry_required') else exc.code
    return bot_error(DomainError(code,exc.status,exc.params),account.locale,account)

def cv_takes_more(account,ext,sent,group=None):
    """Whether a file sent on a new CV's review is one more of the files it is made from.

    `sent` is when Telegram took it (seconds) and `group` its album. Only of a
    kind the CV's way takes: the rest of the album its files came in, a file
    sent before the review was on screen (screenshots sent one by one, which
    Telegram delivers while the first is read), or a PDF or Word file moments
    after the last of them (CV_FILES_WINDOW). A photo sent once the review is
    on screen is the CV's portrait, as the review says (cv_file).
    """
    from . import generation as ai
    from apps.studio.cv.sources import KINDS
    row=BotConversation.objects.filter(pk=account.telegram_user_id,state='cv_review').first()
    if row is None or row.updated_at<timezone.now()-QUESTION_LIFETIME: return False
    prompt=row.prompt or {}
    at,drawn=prompt.get('files_at'),prompt.get('drawn_at')
    if type(at) not in (int,float): return False
    way=ai.way_of(account,prompt.get('draft_id',''))
    kind=CV_FILE_KINDS.get(ext)
    if way not in KINDS or kind not in KINDS[way]: return False
    if group and str(group)==str(prompt.get('album') or ''): return True
    # Telegram dates a message in whole seconds: one dated the second the
    # review was drawn in may have been sent after it, and is not counted.
    if type(drawn) in (int,float) and sent<int(drawn): return True
    # An album is never one portrait: more pages or screenshots of the CV.
    if kind=='image': return bool(group)
    return sent-at<=CV_FILES_WINDOW.total_seconds()

def files_said(account,names):
    """A CV's files on one line: their names, two at most and how many more, then how many photos — Telegram names each photo.jpg."""
    photos=sum(1 for name in names if name=='photo.jpg')
    named=[name if len(name)<=40 else name[:39]+'…' for name in names if name and name!='photo.jpg']
    shown=', '.join(named[:2])+(f' +{len(named)-2}' if len(named)>2 else '')
    parts=[part for part in (shown,counted(account.locale,photos,'photo') if photos else '') if part]
    return ', '.join(parts) if parts else counted(account.locale,len(names),'file')

def unread_said(account,files,pages):
    """What of a CV's files could not be read, as its review says it; '' when all of it was read."""
    parts=([counted(account.locale,files,'file')] if files else [])+([counted(account.locale,pages,'page')] if pages else [])
    if not parts: return ''
    return text(account,'cv_unread').format(what=text(account,'cv_unread_and').join(parts))

def option_summary(account,draft):
    labels={'angle':'rotate_label','pages':'pages','order':'page_order','ranges':'split_groups','format':'format_label','dpi':None,'paper_size':'paper_label','orientation':None,'margin':'margin_button'}
    result=[]
    for key,value in draft.parameters.items():
        label=text(account,labels[key]) if labels.get(key) else 'DPI' if key=='dpi' else ''
        if key=='orientation': value=text(account,{'auto':'auto','portrait':'portrait','landscape':'landscape'}.get(value,'auto'))
        if isinstance(value,list): value=', '.join(map(str,value))
        if key=='angle': value=f'{value}°'
        if key=='paper_size' and value in ('fit','original'): value=text(account,'fit_page' if value=='fit' else 'original')
        if value=='all': value=text(account,'all_pages')
        value=str(value)
        if len(value)>180: value=value[:177]+'…'
        result.append(html.escape(f'{label}: {value}' if label else value))
    return '\n'.join(result) or text(account,'options_default')

def week_line(account,summary):
    """This week's file tasks beside a file task, on a plan that counts them; else nothing."""
    week=summary['usage']['file_jobs']
    return text(account,'files_week_used').format(used=week['used'],limit=week['limit'])+'\n' if week['limit'] is not None else ''

async def review_screen(account,draft,quote):
    """The review of a generation before it is made, as (body, rows).

    Never submit without showing this: making it uses one of the week's AI
    documents, or one of the file's edits, and the customer sees which.
    """
    from . import generation as ai
    from .onboarding import LANGUAGES
    title=TOOL_NAMES[draft.feature_id][account.locale]
    heading=await sync_to_async(ai.title_of)(draft)
    given,asked=await sync_to_async(ai.summary)(draft)
    change=await sync_to_async(ai.change_request)(draft)
    before=await sync_to_async(ai.length_before)(draft)
    locale=await sync_to_async(ai.language_of)(draft)
    wanted,cap=await sync_to_async(ai.images_wanted)(draft)
    deck=draft.feature_id==ai.SLIDES
    # A CV is one page or two, as its template lays it out: there is no count
    # to read wrong, so none to show or put right.
    cv=draft.feature_id==ai.CV
    unit='ai_slides' if deck else 'ai_pages'
    # A description asking for the other service is offered it, before anything
    # is spent. Said first, in bold, with its button on top and Generate named
    # for what it makes: as one line above the hint it went unread, and decks
    # asked of the PDF service were made as PDFs.
    other=await sync_to_async(ai.other_service)(draft)
    body=(f'<b>{text(account,"ai_wrong_tool_slides" if other==ai.SLIDES else "ai_wrong_tool_pdf")}</b>\n\n' if other else '')
    body+=(f'<b>{text(account,"review_title")}</b>\n{html.escape(title)}\n'
           f'📄 {html.escape(heading)}\n')
    # A change says what is changing; a new document says what it is.
    if change: body+=f'✏️ {html.escape(change)}\n'
    pages_more=False
    if cv:
        # A CV made from files says which, what of them could not be read, and
        # the notes written on top of them.
        way,names,notes=await sync_to_async(ai.made_from)(draft)
        if way==ai.LINKEDIN: body+=text(account,'cv_linkedin_title')+'\n'
        elif way==ai.FILE: body+=html.escape(text(account,'cv_from_files').format(files=files_said(account,names)))+'\n'
        unread=unread_said(account,*await sync_to_async(ai.unread_of)(draft))
        if unread: body+=html.escape(unread)+'\n'
        if notes: body+=html.escape(text(account,'cv_notes_line').format(notes=brief_quote(notes.split('\n'))))+'\n'
        body+=f'{text(account,unit)}: {text(account,"cv_length")}'
        # Made from photos or screenshots, a photo sent now may be another page.
        made=await sync_to_async(ai.cv_files)(account,draft.id) if way!=ai.TEXT and not change else None
        pages_more=bool(made and made['images'])
    else:
        # A change that alters the count says so: 9 → 1 must never go unseen.
        count=f'{before} → {given}' if before and before!=given else f'{given}'
        body+=f'{text(account,unit)}: {count}'
        # A clamped request is said out loud rather than quietly honoured short.
        if asked and asked>given: body+='\n'+text(account,'ai_pages_clamped').format(asked=asked,given=given)
    names=dict(LANGUAGES)
    if locale in names: body+=f'\n{text(account,"ai_language")}: {names[locale]}'
    # A change is made from its request alone: there is no design to pick, the
    # count and the language are only shown, and nothing on this screen alters them.
    if deck and not change:
        design=await sync_to_async(ai.design_of)(draft)
        body+=f'\n{text(account,"ai_theme")}: '+(html.escape(design) if design else text(account,'ai_theme_auto'))
    photo=await sync_to_async(ai.portrait_of)(draft) if cv else ''
    if cv:
        if not change:
            template=await sync_to_async(ai.template_of)(draft)
            body+=f'\n{text(account,"cv_template")}: '+(html.escape(template) if template else text(account,'cv_template_auto'))
        # Whether the CV carries a photo, which a change keeps unless it asks
        # for none. A new CV's review still takes one sent now (receive()).
        # A photo on a template picked without a place for it is said before paying.
        slot=await sync_to_async(ai.photo_slot)(draft) if photo else True
        body+='\n'+text(account,('cv_photo_line' if slot else 'cv_photo_no_slot_line') if photo
                         else 'cv_photo_none' if change else 'cv_photo_none_add_pages' if pages_more else 'cv_photo_none_add')
        # What a new CV lacks, or could still have, is said before it is paid for: a line, no step.
        adding=can_add_line(account,await sync_to_async(ai.facts_of)(draft)) if not change else ''
        if adding: body+='\n'+adding
    # Pictures the plan cannot add are said, never quietly left out. A change
    # asking for them on a plan that adds none is told so too, unless photos are
    # off altogether and no plan could add them.
    short=wanted>cap and (cap>0 or bool(change) and await sync_to_async(ai.pictures_on)())
    if short and cap: body+='\n'+text(account,'ai_images_capped' if deck else 'ai_images_capped_pdf').format(count=cap)
    elif short: body+='\n'+text(account,'ai_images_none')
    # A file format named beside other changes is not something a change makes:
    # the file comes back in its own format, and the way to the other is said.
    # A CV is only ever a PDF, and slides of one are no service of ours.
    if change and not cv and await sync_to_async(ai.format_kept)(draft):
        body+='\n'+html.escape(text(account,'ai_format_kept_deck' if deck else 'ai_format_kept_pdf').format(
            button=text(account,'ai_revise'),service=TOOL_NAMES[ai.SLIDES][account.locale]))
    generate='ai_generate' if not other else 'ai_pdf_anyway' if other==ai.SLIDES else 'ai_slides_anyway'
    hint=(text(account,'ai_review_hint_button').format(button=text(account,generate).split(' ',1)[1]) if other
          else text(account,'ai_review_hint'))
    body+=f'\n\n{hint}'
    # What this uses on a plan with limits: an edit counts against its file, a
    # new document against the week. Unlimited plans are not told a number.
    source=await sync_to_async(ai.revised_from)(draft)
    if source:
        used,limit=await sync_to_async(ai.edits_used)(draft)
        if limit is not None: body+='\n\n'+text(account,'ai_edits_used').format(used=used,limit=limit)
    else:
        week=(await sync_to_async(usage_snapshot)(account))['ai_documents']
        if week['limit'] is not None: body+='\n\n'+text(account,'ai_week_used').format(used=week['used'],limit=week['limit'])
    body+=f'\n{text(account,"expires")}: {stamp(account,quote.expires_at)}'
    # Rewording a change goes back to the change, not to a blank document. A
    # CV's description written again goes back to the way it was made, with
    # the photo and the files sent for it (by the draft it is on: a button
    # never carries what the customer sent).
    reword=(await button(account,'ai_revise','ai_revise',{'draft_id':source}) if source
            else await button(account,'ai_change_topic','ai_tool',{'feature_id':draft.feature_id,**({'draft_id':str(draft.id)} if photo or cv else {})}))
    rows=[[await button(account,generate,'ai_run',{'quote_id':str(quote.id),'draft_id':str(draft.id)})]]
    if other:
        rows.insert(0,[await button(account,'ai_switch_slides' if other==ai.SLIDES else 'ai_switch_pdf','ai_switch',
                                    {'draft_id':str(draft.id),'feature_id':other})])
    # A change has none of the controls below: its request already says what
    # to do, and a stepper or a theme beside it was read as part of the change.
    if not change and not cv:
        # The count can be put right here, before anything is made. Every plan has
        # the same ceiling, so at it there is no "more" button and no plan offered
        # in its place: only the weekly allowance differs by plan.
        from apps.studio.pages import ceiling
        top=await sync_to_async(ceiling)(account,'pptx' if deck else 'pdf')
        # [➖] [10 slides] [➕]: the count between the buttons that change it. The
        # middle one only shows it; a button at the limit is left out.
        stepper=[InlineKeyboardButton(text=counted(account.locale,given,'slide' if deck else 'page'),
                                      callback_data=await callback(account,'ai_count'))]
        if given>1:
            stepper.insert(0,InlineKeyboardButton(text='➖',callback_data=await callback(account,'ai_length',{'draft_id':str(draft.id),'pages':given-1})))
        if given<top:
            stepper.append(InlineKeyboardButton(text='➕',callback_data=await callback(account,'ai_length',{'draft_id':str(draft.id),'pages':given+1})))
        rows.append(stepper)
    # The deck's design and count together, or the CV's template, on a screen of their own.
    if not change and (deck or cv): rows.append([await setup_button(account,draft)])
    # The language it will be written in, switchable in one tap.
    if not change:
        rows.append([InlineKeyboardButton(text=('✅ ' if code==locale else '')+label.split(' ',1)[0],
                                          callback_data=await callback(account,'ai_locale',{'draft_id':str(draft.id),'locale':code}))
                     for code,label in LANGUAGES])
    rows.append([reword,await button(account,'cancel_button','home')])
    return body,rows

async def setup_button(account,draft):
    """Opens the deck's or the CV's setup screen: as a Mini App where Telegram allows one (https), else as a link."""
    from aiogram.types import WebAppInfo
    route,label=('cv-setup','cv_template_button') if draft.feature_id=='ai.cv' else ('deck-setup','ai_theme_button')
    url=await web_url(account,f'{route}?draft={draft.id}')
    if url.startswith('https://'):
        return InlineKeyboardButton(text=text(account,label),web_app=WebAppInfo(url=url))
    return InlineKeyboardButton(text=text(account,label),url=url)

async def remember_review(account,draft,screen):
    """Keep where a review is shown, so the setup screen can redraw it there."""
    if screen is None: return
    chat_id=getattr(screen,'chat_id',None) or getattr(getattr(screen,'chat',None),'id',None)
    message_id=getattr(screen,'message_id',None)
    if not chat_id or not message_id: return
    from .local import LocalTelegramSession
    local=isinstance(getattr(getattr(screen,'bot',None),'session',None),LocalTelegramSession)
    shown={'draft_id':str(draft.id),'chat_id':chat_id,'message_id':message_id,'local':local}
    def keep():
        from django.db import transaction
        from .commands import menu_mark
        with transaction.atomic():
            row,_=BotConversation.objects.select_for_update().get_or_create(telegram_user_id=account.telegram_user_id)
            # The chat's menu version shares this field (telegram/commands.py);
            # losing it would set the menu again on the next update.
            row.review={**menu_mark(row.review),**shown}
            row.save(update_fields=['review','updated_at'])
    await sync_to_async(keep)()

def forget_review(account,draft_id):
    """Once Generate is tapped the review becomes the job's status: never redraw it as a review.

    A redraw there would offer Generate again for a job already submitted. Only
    that draft's review is forgotten; one shown since for another draft stays.
    The chat's menu version, kept in the same field, stays as well.
    """
    from .commands import menu_mark
    rows=BotConversation.objects.filter(telegram_user_id=account.telegram_user_id,review__draft_id=str(draft_id))
    for review in rows.values_list('review',flat=True)[:1]:
        rows.update(review=menu_mark(review))

def refresh_review(account,draft,quote):
    """Redraw the review in the chat after the draft changed elsewhere (the Mini App).

    Best effort: the change is saved whatever happens here. The old screen's
    Generate button carries the old quote, so it is replaced in place, or a new
    review is sent if Telegram will no longer edit that message.
    """
    import logging
    from asgiref.sync import async_to_sync
    if account.telegram_user_id is None: return False
    conversation=BotConversation.objects.filter(telegram_user_id=account.telegram_user_id).first()
    shown=(conversation.review if conversation else None) or {}
    if shown.get('draft_id')!=str(draft.id): return False
    async def run():
        if shown.get('local'):
            from .local import LocalTelegramSession
            bot=Bot('123456:LOCAL_SIMULATOR_NO_NETWORK',session=LocalTelegramSession(account))
        else:
            from apps.commerce.providers import telegram_config
            token=(await sync_to_async(telegram_config)())['token']
            if not token: return False
            bot=Bot(token)
        try:
            body,rows=await review_screen(account,draft,quote)
            markup=InlineKeyboardMarkup(inline_keyboard=rows)
            screen=_Screen(bot,shown['chat_id'],shown['message_id'])
            try: sent=await screen.edit_text(body,parse_mode='HTML',reply_markup=markup)
            except Exception as exc:
                if 'not modified' in str(exc): return True
                sent=await screen.answer(body,parse_mode='HTML',reply_markup=markup)
            if sent is not None and sent is not True:
                await remember_review(account,draft,sent)
            return True
        finally: await bot.session.close()
    try: return async_to_sync(run)()
    except Exception:
        logging.getLogger(__name__).warning('review refresh failed',exc_info=True)
        return False

def build_dispatcher():
    from .workflows import draft_for,configure,snapshot,bound_draft,quote_draft,run_quote,attach_input,order_inputs,discard_draft,choose_tool,start_tool,discard_finished_draft,accept_upload,record_receipt
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
        """One of the three generation services, offered directly.

        They take a description rather than a file, so they carry their own
        callback — but they are services like any other and belong in the list
        beside the rest, not behind a folder of their own.
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
        # Five full-width buttons for what people come for: the three AI services
        # (a PDF, slides, a CV), PDF from images, and the plans. Every other tool
        # is one tap away in All tools.
        rows.extend(await ai_service_rows(account))
        available={f['id'] for f in await sync_to_async(catalog)(account)}
        if 'pdf.images_to_pdf' in available: rows.append([await tool_button(account,draft,'pdf.images_to_pdf')])
        rows.append([await button(account,'subscribe_button','plans',{'from':'menu'})])
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

    async def controls(message,account,draft=None,edit=False,advanced=False,notice=''):
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
        async def prompt(label,kind): return await button(account,label,'prompt',{**binding,'kind':kind})
        rows=[]
        files=await sync_to_async(lambda:{str(a.id):a for a in FileAsset.objects.filter(account=account,id__in=draft.input_ids)})()
        title=TOOL_NAMES.get(feature,{}).get(account.locale,feature)
        hint='upload_merge' if feature=='pdf.merge' else 'upload_images' if feature=='pdf.images_to_pdf' else 'upload_word' if feature=='convert.word_to_pdf' else 'upload_slides' if feature=='convert.pptx_to_pdf' else 'upload_pdf'
        body=(html.escape(notice)+'\n\n' if notice else '')+f'<b>{html.escape(title)}</b>'
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
            body+='\n\n'+week_line(account,summary)+f'{text(account,"expires")}: {stamp(account,quote.expires_at,"%H:%M")}'
            # "Nothing counts until you tap Start" only beside a Start button:
            # at the limit Start becomes Plans.
            if summary['affordable']:
                body+='\n'+text(account,'tap_to_run')
                rows.append([await button(account,'run','run',{**snapshot(draft),'quote_id':str(quote.id)})])
            else:
                body+='\n'+text(account,'files_week_hint').format(when=week_reset(account,summary['usage']['resets_at']))
                rows.append([await button(account,'plans','plans',FROM_LIMIT)])
        if quote_error and quote_error.code=='channels_required':
            return await show_gate(message,account,resume={'kind':'controls'},edit=edit)
        if quote_error:
            body+='\n\n'+html.escape(bot_error(quote_error,account.locale,account))
            if quote_error.code in ('password_required','unlock_first','secure_password_entry_required'):
                rows.append([InlineKeyboardButton(text=text(account,'open'),url=await web_url(account))])
        if feature=='pdf.rotate': rows.append([await choice(f'{angle}°',{'angle':angle}) for angle in (90,180,270)])
        if feature=='pdf.to_images' and advanced:
            rows.append([await choice(value.upper(),{'format':value}) for value in ('png','jpg')])
            rows.append([await choice(f'{dpi} DPI',{'dpi':dpi}) for dpi in (72,96,150,200)])
        if feature=='pdf.images_to_pdf' and advanced:
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
        summary=await sync_to_async(quote_data)(quote)
        start=([await button(account,'run','run',{**snapshot(draft),'quote_id':str(quote.id)})] if summary['affordable']
               else [await button(account,'plans','plans',FROM_LIMIT)])
        rows=[start,[await button(account,'edit_settings','controls'),await button(account,'cancel_button','cancel',snapshot(draft))],[await button(account,'home','home')]]
        body=f'<b>{text(account,"review_title")}</b>\n{text(account,"review_hint")}\n\n{listing}\n\n{option_summary(account,draft)}\n\n{week_line(account,summary)}{text(account,"expires")}: {stamp(account,quote.expires_at)}'
        if not summary['affordable']: body+='\n'+text(account,'files_week_hint').format(when=week_reset(account,summary['usage']['resets_at']))
        await render(message,body,rows,edit)

    async def review(message,account,binding=None,edit=False):
        await sync_to_async(set_prompt)(account)
        draft,quote=await sync_to_async(quote_draft)(account,binding)
        await quote_message(message,account,draft,quote,edit)

    # --- AI generation -------------------------------------------------------
    # Three services and one message. Everything else — pages, tone, audience,
    # questions — is read out of what the customer writes. A CV is written from
    # what the customer says about themselves, with the photo they send.

    async def ai_studio_url(account):
        """The web studio, carrying whatever files are already in the chat."""
        from urllib.parse import urlencode
        url=await web_url(account,'create')
        staged=await sync_to_async(lambda:draft_for(account).input_ids[:5])()
        return url+('?'+urlencode({'file_id':staged},doseq=True) if staged else '')

    def ai_example(account,feature_id,index):
        return PROMPT_EXAMPLES[feature_id][index][LOCALES.index(account.locale if account.locale in LOCALES else 'en')]

    async def ai_prompt(message,account,feature_id,edit=False,notice='',portrait=None):
        """One screen, one question: what do you want? Examples included.

        One description is visible; the rest sit in an expandable blockquote,
        so the screen stays the length of a single example until the customer
        taps to open it. `<code>` is deliberately not nested inside the quote
        — Telegram documents inline styling as quotable content, and the
        first example stays tappable to copy where it matters most.

        A CV asks about the customer and takes a photo too: `portrait` is one
        just sent, or None to keep the one already waiting with this question.
        `notice` is a line about a file just sent.
        """
        cv=feature_id==ai.CV
        if portrait is None: portrait=await sync_to_async(pending_portrait)(account) if cv else ''
        await sync_to_async(set_prompt)(account,'ai_input',{'feature_id':feature_id,**({'portrait_asset_id':portrait} if portrait else {})})
        title=TOOL_NAMES[feature_id][account.locale]
        samples=[ai_example(account,feature_id,index) for index in range(len(PROMPT_EXAMPLES[feature_id]))]
        body=(html.escape(notice)+'\n\n' if notice else '')+f'<b>{html.escape(title)}</b>\n'
        if cv:
            # No page count to ask for: one page or two is the template's to decide. What a CV
            # needs and what only adds to it are said before the customer writes, by the labels
            # the missing screen and the review use.
            from apps.studio.cv.content import OPTIONAL_FACTS,REQUIRED_FACTS
            needs=text(account,'cv_required').format(facts=facts_said(account,REQUIRED_FACTS))
            adds=text(account,'cv_optional').format(facts=facts_said(account,OPTIONAL_FACTS,', '))
            body+=(f'{text(account,"cv_ask")}\n\n{needs}\n{adds}\n\n'
                   +(text(account,'cv_photo_attached') if portrait else f'<i>{text(account,"cv_photo_hint")}</i>'))
        else: body+=f'{text(account,"ai_ask_topic")}\n<i>{text(account,"ai_pages_hint")}</i>'
        body+=f'\n\n{text(account,"ai_examples")}:\n\n1. <code>{html.escape(samples[0])}</code>'
        if samples[1:]:
            rest='\n\n'.join(f'{number}. {html.escape(sample)}'
                              for number,sample in enumerate(samples[1:],2))
            body+=f'\n\n<blockquote expandable>{rest}</blockquote>'
        staged=await sync_to_async(lambda:ai.sources(account,draft_for(account).input_ids,feature_id))()
        if staged: body+=f'\n\n📎 {len(staged)}'
        # A CV's examples come back to this question, and its Back to the
        # first screen, where the other ways to make a CV are.
        rows=[[await button(account,'ai_examples','ai_examples',{'feature_id':feature_id,**({'cv_source':'text'} if cv else {})})],
              [await button(account,'ai_back','cv_mode') if cv else await button(account,'ai_back','home')]]
        # A PDF or Word file sent here was meant as the old CV: the way to that screen.
        if cv and notice==text(account,'cv_photo_only'):
            rows.insert(0,[await button(account,'cv_mode_file','cv_mode',{'cv_source':ai.FILE})])
        return await render(message,body,rows,edit)

    async def cv_choose(message,account,edit=False,notice=''):
        """The first CV screen: how shall we make it? One question, three ways, before anything else is asked.

        Written about yourself in one message (the question ai_prompt asks), from
        the LinkedIn profile, or from the old CV (cv_mode_screen). A photo sent for
        the CV and notes written for its file stay with it (cv_kept). A file sent
        here, before a way was chosen, is taken as the old CV (cv_source_file),
        and a description written here as one about yourself (cv_choose_text).
        """
        kept=await sync_to_async(cv_kept)(account)
        await sync_to_async(set_prompt)(account,'cv_choose',{'feature_id':ai.CV,**{key:value for key,value in kept.items() if value}})
        body=(html.escape(notice)+'\n\n' if notice else '')+(f'<b>{html.escape(TOOL_NAMES[ai.CV][account.locale])}</b>\n'
              f'{text(account,"cv_choose_ask")}\n\n<i>{text(account,"cv_choose_hint")}</i>')
        rows=[[await button(account,'cv_mode_text','cv_mode',{'cv_source':ai.TEXT})],
              [await button(account,'cv_mode_linkedin','cv_mode',{'cv_source':ai.LINKEDIN})],
              [await button(account,'cv_mode_file','cv_mode',{'cv_source':ai.FILE})],
              [await button(account,'ai_back','home')]]
        return await render(message,body,rows,edit)

    async def cv_mode_screen(message,account,way,edit=False,notice='',notes=None,files=None,ask='file',asked=0,link=False,portrait=None,
                             retry=False,missing=(),copied=''):
        """The LinkedIn or old-CV screen: what to send for a CV made from files, and what is kept for it.

        The file holds the facts; words sent before it, with it or just after
        it are notes on top of them. A photo sent here is a page to read, never
        the portrait, which is sent on the review. `notes` and `portrait` are
        None to keep what the CV's screens keep (cv_kept); `files` are files
        kept for it. `ask` is what the screen waits for: 'file'; 'missing', asked
        `asked` times already, when the files and the notes do not give what a
        CV needs (`missing` are the required facts that are not there, and the
        answer goes before the notes); or 'again', new notes or another file
        for the files kept, when a CV's description is written again. A screen
        kept before 'missing' was listed has 'name' for it. `link` says a
        LinkedIn link was sent instead of the profile: it is never opened, and
        the way to save the profile is said instead.
        `retry` offers to make the CV again at once from the files kept, after
        a refusal that passes (`rate_limited`). `copied` is a sample of the
        missing screen just sent back (as `compared` gives it): sent again at
        once, it is the customer's own.
        """
        kept=await sync_to_async(cv_kept)(account)
        notes=[note for note in (kept['notes'] if notes is None else notes) if note]
        portrait=kept['portrait_asset_id'] if portrait is None else portrait
        files=[str(identifier) for identifier in files or []]
        if ask in ('missing','name'): ask,missing='missing',cv_asked({'ask':ask,'missing':missing})
        state={'feature_id':ai.CV,'cv_source':way,'notes':notes,'source_ids':files,'ask':ask,
               **({'missing':missing} if ask=='missing' else {}),**({'copied':copied} if copied and ask=='missing' else {}),
               **({'asked':asked} if asked else {}),**({'portrait_asset_id':portrait} if portrait else {})}
        await sync_to_async(set_prompt)(account,'cv_source',state)
        linkedin=way==ai.LINKEDIN
        body=(html.escape(notice)+'\n\n' if notice else '')+(f'<b>{html.escape(TOOL_NAMES[ai.CV][account.locale])}</b>\n'
              f'<b>{text(account,"cv_linkedin_title" if linkedin else "cv_file_title")}</b>\n')
        noted=text(account,'ai_topic_kept').format(brief=html.escape(brief_quote(notes))) if notes else ''
        if files and ask in ('missing','again'):
            names=await sync_to_async(ai.file_names)(account,files)
            body+=html.escape(text(account,'cv_from_files').format(files=files_said(account,names)))+'\n'
            if noted: body+=noted+'\n'
            if ask=='missing':
                body+=f'\n{text(account,"cv_file_missing_question")}\n{missing_lines(account,missing,source=True,written=notes)}'
            else: body+='\n'+text(account,'cv_files_kept')
        else:
            if linkedin:
                body+=(f'{text(account,"cv_linkedin_link_sent" if link else "cv_linkedin_ask")}\n'
                       f'{text(account,"cv_linkedin_computer")}\n{text(account,"cv_linkedin_phone")}')
            else: body+=text(account,'cv_file_ask')
            body+=f'\n\n{noted}\n{text(account,"cv_send_file_now")}' if noted else f'\n\n<i>{text(account,"cv_notes_hint")}</i>'
        rows=[[await button(account,'ai_back','cv_mode'),await button(account,'home','home')]]
        if files and ask=='again' and retry:
            rows.insert(0,[await button(account,'cv_try_again','cv_retry',{'cv_source':way})])
        if files and ask=='missing':
            # Like a file that could not be used: another file instead, or writing about yourself.
            rows[:0]=[[await button(account,'cv_send_another','cv_mode',{'cv_source':way})],
                      [await button(account,'cv_write_instead','cv_mode',{'cv_source':ai.TEXT})]]
        return await render(message,body,rows,edit)

    async def cv_screen_again(message,account,conversation):
        """The CV screen the chat is on, drawn again with what it keeps: the same message delivered twice."""
        p=conversation.prompt or {}
        if conversation.state=='cv_choose': return await cv_choose(message,account)
        way=p.get('cv_source') if p.get('cv_source') in (ai.LINKEDIN,ai.FILE) else ai.FILE
        return await cv_mode_screen(message,account,way,notes=list(p.get('notes') or []),files=list(p.get('source_ids') or []),
                                    ask=p.get('ask','file'),asked=int(p.get('asked') or 0),missing=p.get('missing') or ())

    async def cv_refused(message,account,way,notes,exc,edit=True):
        """A CV that could not be made from the files sent: why, and the ways on — another file, or writing instead.

        The notes stay, and a file sent next is read at once: the buttons only
        say so. The refusal is said as cv_refusal_said says it.
        """
        portrait=await sync_to_async(pending_portrait)(account)
        await sync_to_async(set_prompt)(account,'cv_source',{'feature_id':ai.CV,'cv_source':way,'notes':notes,'source_ids':[],'ask':'file',
                                                              **({'portrait_asset_id':portrait} if portrait else {})})
        said=await sync_to_async(cv_refusal_said)(account,exc)
        body=f'<b>{html.escape(TOOL_NAMES[ai.CV][account.locale])}</b>\n{html.escape(said)}'
        rows=[[await button(account,'cv_send_another','cv_mode',{'cv_source':way})],
              [await button(account,'cv_write_instead','cv_mode',{'cv_source':ai.TEXT})],
              [await button(account,'home','home')]]
        return await render(message,body,rows,edit)

    async def cv_build(message,account,way,notes,files,*,given=False,asked=0,notice='',at=None,album=None,waited=None):
        """A CV made from the customer's files and the notes on top of them, priced and on its review.

        Nothing is counted yet. `message` is the "Preparing…" line, which becomes
        the review, or the question or refusal in its place: a name, a phone or
        email, or a job or school that neither the files nor the notes give is
        asked for, keeping both (`asked` times asked; `given` takes the answers
        as they are); a file that cannot be read offers another file
        or writing instead. While a file is still waiting for the reader, it
        becomes the wait for them (cv_wait_start), and this is done again once
        they are read. `at` is when Telegram took the newest file and
        `album` the album they came in: the rest of it, or a file sent before
        the review is on screen, is another of its files (cv_takes_more).
        `notice` is a line about the files just sent, said above the review.

        `waited` is the wait this is the end of (cv_wait_done). What is made
        is kept only while the chat still waits on its message: a customer who
        moved on meanwhile (/start, /cv) keeps where they went. The CV is kept
        in the wait before its review is drawn (cv_wait_shown), so a review
        Telegram did not take is drawn again, never made again.
        """
        portrait=await sync_to_async(ai.usable_portrait)(account,(await sync_to_async(cv_kept)(account))['portrait_asset_id'])
        notes=kept_brief([note for note in notes if note],CV_BRIEF_CHARS,CV_BRIEF_PIECES)
        wait={'then':'build','cv_source':way,'notes':notes,'source_ids':[str(identifier) for identifier in files],
              'given':bool(given),'asked':int(asked or 0),'notice':notice,'files_at':at,'album':album,
              **({'portrait_asset_id':portrait} if portrait else {})}
        # The reader has the files: the draft is made once it has read them, never from half of them.
        status=await sync_to_async(ai.cv_reading)(account,files,way)
        if status: return await cv_wait_start(message,account,wait,status)
        draft=None
        try:
            draft=await sync_to_async(ai.build)(account,ai.CV,'\n'.join(notes),files,given,portrait,way)
            await sync_to_async(funnel.step)('ai.described',account=account,feature=ai.CV)
            _,quote=await sync_to_async(ai.quote)(account,draft.id)
        except DomainError as exc:
            if waited is not None and not await sync_to_async(cv_still_waiting)(account,waited): return None
            if exc.code=='cv_reading':
                status=await sync_to_async(ai.cv_reading)(account,files,way)
                return await cv_wait_start(message,account,wait,status or {'reading':True})
            if exc.code=='cv_missing':
                return await cv_mode_screen(message,account,way,True,notes=notes,files=files,ask='missing',asked=asked,portrait=portrait,
                                            missing=(exc.params or {}).get('missing') or [])
            if exc.code=='channels_required':
                # Behind the channels the files and the notes wait on this screen.
                from .channels import show_gate
                await sync_to_async(set_prompt)(account,'cv_source',{'feature_id':ai.CV,'cv_source':way,'notes':notes,'source_ids':files,
                                                                      'ask':'again',**({'portrait_asset_id':portrait} if portrait else {})})
                resume={'kind':'ai_draft','draft_id':str(draft.id)} if draft else {'kind':'cv_mode','cv_source':way}
                return await show_gate(message,account,resume=resume,edit=True)
            if exc.code in ('weekly_ai_limit','edit_limit'): return await ai_refused(message,account,exc,{},None)
            # A refusal that passes (too many at once) keeps the files, to make the CV from them again.
            if exc.retryable and files:
                said=await sync_to_async(cv_refusal_said)(account,exc)
                return await cv_mode_screen(message,account,way,True,said,notes=notes,files=files,ask='again',portrait=portrait,
                                            retry=True)
            return await cv_refused(message,account,way,notes,exc)
        # A file sent while the review is on its way is one more of its files.
        window={'files_at':at,'album':album}
        if waited is not None:
            # The review sets the chat's state once Telegram has taken it.
            if not await sync_to_async(cv_wait_shown)(account,waited,draft.id,notice): return None
        else: await sync_to_async(set_prompt)(account,'cv_review',{'draft_id':str(draft.id),**{key:value for key,value in window.items() if value}})
        return await ai_review(message,account,draft,quote,True,notice,files=window,waited=waited is not None)

    async def cv_upload(account,chat_id,files,way):
        """The files sent for a CV, stored as the customer's own: (their asset ids, the first refusal, or None).

        Noted as received (record_receipt), so the same message delivered twice
        is one file, and never put on the file tools' draft: the menu would offer
        to continue a task nobody started. A kind its way does not take is
        refused here, before anything is stored.
        """
        from apps.studio.cv.sources import KINDS
        ids,failure=[],None
        for item in files:
            kind=CV_FILE_KINDS.get(item['name'].rsplit('.',1)[-1].lower())
            try:
                if item['raw'] is None or kind not in KINDS[way]: raise DomainError('cv_file_kind')
                # A CV's own file: a Word CV with an email or LinkedIn link in it is read too.
                asset=await sync_to_async(upload_file)(account,SimpleUploadedFile(item['name'],item['raw']),'bot',
                                                       purpose='cv_source')
                await sync_to_async(record_receipt)(account,asset,chat_id,item['message_id'])
                ids.append(str(asset.id))
            except DomainError as exc: failure=failure or exc
        return ids,failure

    async def cv_source_file(message,bot,account,name,raw):
        """A file sent for a CV made from files; False when the chat no longer makes one, and it is an ordinary file.

        Sent on the LinkedIn or old-CV screen, or on the first CV screen (taken
        as the old CV), it is what the CV is made from; its caption, or words
        sent before it, are notes on top of it. A photo there is a page to
        read, never the portrait. On a new CV's review, the rest of its album,
        or a file sent before the review was on screen, is one more of its
        files (cv_takes_more), and so is any file sent while the chat waits for
        the reader (cv_wait_join). Every file of an album is read, not only the
        newest (cv_stash). The chat is read again once these files have their
        turn (chat_lock): one sent just after another finds the review the
        first made, and joins its CV. Those screens are kept as long as a
        question is (cv_screen_open): later, a file is an ordinary file.
        """
        album_caption(message)
        own=cv_stash(message,name,raw)
        target,edit=await album_target(message,bot)
        if target is None: return True
        files=cv_unstash(message,own)
        if not files: return True
        sent=max(item['date'] for item in files)
        group=getattr(message,'media_group_id',None)
        async with chat_lock(message.chat.id):
            conversation=await sync_to_async(lambda:BotConversation.objects.filter(pk=message.from_user.id).first())()
            state=conversation.state if conversation else ''
            if cv_waiting(conversation):
                album_shown(message,await cv_wait_join(bot,account,conversation,files,sent))
                return True
            newest=files[-1]['name'].rsplit('.',1)[-1].lower()
            more=state=='cv_review' and await sync_to_async(cv_takes_more)(account,newest,sent,group)
            if not more and not cv_screen_open(conversation): return False
            p=dict(conversation.prompt or {})
            waiting=target if edit else await target.answer(text(account,'ai_preparing'))
            if more:
                draft_id=p.get('draft_id','')
                way=await sync_to_async(ai.way_of)(account,draft_id)
                ids,failure=await cv_upload(account,message.chat.id,files,way)
                captions=' '.join(item['caption'] for item in files if item['caption'])
                window={'files_at':max(sent,p.get('files_at') or 0),'album':p.get('album') or group} if ids else None
                if ids:
                    # The files the CV was made from and these: it waits for the reader to read them all.
                    made=await sync_to_async(ai.cv_files)(account,draft_id)
                    every=[*made['source_ids'],*[i for i in ids if i not in made['source_ids']]] if made else ids
                    status=await sync_to_async(ai.cv_reading)(account,every,way)
                    if status:
                        notice=await sync_to_async(cv_refusal_said)(account,failure) if failure else ''
                        album_shown(message,await cv_wait_start(waiting,account,{
                            'then':'add','cv_source':way,'draft_id':draft_id,'added':ids,'more':[captions] if captions else [],
                            'source_ids':every,'notice':notice,**(window or {})},status))
                        return True
                album_shown(message,await cv_add(waiting,account,draft_id,ids,captions,failure,window))
                return True
            way=p.get('cv_source') if state=='cv_source' and p.get('cv_source') in (ai.LINKEDIN,ai.FILE) else ai.FILE
            notes=[str(note) for note in p.get('notes') or [] if note]
            caption=album_caption(message)
            if caption: notes.append(caption)
            # The files that were asked about stay beside these; any other screen's are replaced by them.
            kept=[str(identifier) for identifier in p.get('source_ids') or []] if p.get('ask') in ('missing','name') else []
            ids,failure=await cv_upload(account,message.chat.id,files,way)
            if not ids:
                album_shown(message,await cv_refused(waiting,account,way,notes,failure or DomainError('cv_file_kind')))
                return True
            # One photo on the first screen, before a way was chosen, with no text
            # in it to read, is no old CV: it is the CV's photo, sent first as the
            # question about yourself always took it, and its caption the description.
            # Whether it has text is known once the reader has read it.
            if state=='cv_choose' and len(files)==1 and len(ids)==1 and CV_FILE_KINDS.get(newest)=='image':
                status=await sync_to_async(ai.cv_reading)(account,ids,way)
                if status:
                    album_shown(message,await cv_wait_start(waiting,account,{
                        'then':'photo','cv_source':way,'notes':notes,'caption':caption,'source_ids':ids,
                        'files_at':sent,'album':group},status))
                    return True
                if not await sync_to_async(ai.cv_readable)(account,ids,way):
                    album_shown(message,await cv_portrait_first(waiting,account,ids[0],caption,notes))
                    return True
            # Some files of an album could not be used: said above the review the others made.
            notice=await sync_to_async(cv_refusal_said)(account,failure) if failure else ''
            album_shown(message,await cv_build(waiting,account,way,notes,[*kept,*ids],asked=int(p.get('asked') or 0),
                                               notice=notice,at=sent,album=group))
        return True

    async def cv_add(message,account,draft_id,ids,more='',failure=None,window=None,notice='',waited=None):
        """Files added to a new CV made from files, its review drawn again with them (`message` becomes it).

        `more` is what was written with them, added to the notes; `failure`
        what was refused of the files sent, said above the review (or
        `notice`, said already), as is a file that could not be added.
        `window` is when Telegram took the newest of them and their album
        (cv_takes_more). A CV no longer kept is the menu, said so.
        `waited` is the wait this is the end of, as for cv_build: kept only
        while the chat still waits on its message, and the CV kept in the wait
        before it is drawn. Its notes are added even with no file (words sent
        to the wait while its review was being drawn).
        """
        try:
            if ids or (waited is not None and more): draft,quote=await sync_to_async(ai.add_sources)(account,draft_id,ids,more)
            else: draft,quote=await sync_to_async(ai.quote)(account,draft_id)
        except DomainError as exc:
            if waited is not None and not await sync_to_async(cv_still_waiting)(account,waited): return None
            if exc.code=='controls_expired': return await home(message,account,True,notice=text(account,'stale_button'))
            draft,quote=await sync_to_async(ai.quote)(account,draft_id)
            failure=exc
        if failure: notice=await sync_to_async(cv_refusal_said)(account,failure)
        notice=notice or text(account,'cv_files_added')
        if waited is not None and not await sync_to_async(cv_wait_shown)(account,waited,draft.id,notice): return None
        return await ai_review(message,account,draft,quote,True,notice,files=window,waited=waited is not None)

    # --- Waiting for the reader ----------------------------------------------
    # A CV's files are read by the reader, in turn with everyone else's
    # (apps/studio/cv/reads.py). Until they are, the chat waits ('cv_wait'):
    # what the CV is made of waits in its state, never in a button, with what
    # to do once they are read ('then'): make the CV ('build'), add them to the
    # CV on review ('add'), or see whether a photo sent first has text in it
    # ('photo'). Its message says where they are in the queue and becomes the
    # review. The loop (cv_wait_loop) and every handler that touches a wait
    # hold the chat's lock (chat_lock), and read the wait again under it.

    async def cv_wait_start(message,account,wait,status):
        """The chat waits for its CV's files: `message` (the "Preparing…" line) says where they are in the queue.

        `wait` is what the CV is made of and what to do once they are read;
        `status` where they stand (generation.cv_reading). Made again from a
        wait whose files turned out to wait once more, it keeps that wait's
        start, its Cancel button and what it last said.
        """
        from .local import LocalTelegramSession
        current=await sync_to_async(lambda:BotConversation.objects.filter(pk=account.telegram_user_id,state='cv_wait')
                                    .values_list('prompt',flat=True).first())() or {}
        portrait=wait.get('portrait_asset_id') or await sync_to_async(pending_portrait)(account)
        chat_id=getattr(message,'chat_id',None) or message.chat.id
        local=isinstance(getattr(getattr(message,'bot',None),'session',None),LocalTelegramSession)
        kept={key:current[key] for key in ('since','cancel','said') if key in current}
        wait={'feature_id':ai.CV,'screen':[chat_id,message.message_id],'local':local,'since':time.time(),
              **kept,**{key:value for key,value in wait.items() if value not in (None,'',[])},
              **({'portrait_asset_id':portrait} if portrait else {})}
        # Cancel goes to the menu, which ends the wait; its button is kept for every redraw.
        if not wait.get('cancel'): wait['cancel']=await callback(account,'home',{'from':'cv_wait'})
        return await cv_wait_screen(message,account,wait,status)

    async def cv_wait_screen(message,account,wait,status):
        """The waiting message drawn with where the files are now, and the wait kept with it.

        `moved_at` is when the place it says last moved: only a place that has
        not moved for CV_WAIT_LIMIT is said to take long (cv_wait_look).
        """
        names=await sync_to_async(ai.file_names)(account,wait['source_ids'])
        place=cv_place(status)
        line=(text(account,'cv_wait_now') if place=='now' else text(account,'cv_wait_next') if place=='next'
              else text(account,'cv_wait_ahead').format(files=counted(account.locale,place,'file')))
        said=wait.get('said','')
        body=(html.escape(said)+'\n\n' if said else '')+(
            f'<b>{html.escape(TOOL_NAMES[ai.CV][account.locale])}</b>\n'
            f'{text(account,"cv_wait_one" if len(names)==1 else "cv_wait_many")}\n'
            f'{html.escape(text(account,"cv_from_files").format(files=files_said(account,names)))}\n{line}\n\n'
            f'<i>{text(account,"cv_wait_hint")}</i>')
        rows=[[InlineKeyboardButton(text=text(account,'cancel_button'),callback_data=wait['cancel'])]]
        sent=await render(message,body,rows,True)
        now=time.time()
        moved=now if place!=wait.get('shown') else float(wait.get('moved_at') or wait.get('since') or now)
        return await cv_wait_kept(account,{**wait,'shown':place,'shown_at':now,'moved_at':moved,'stalled':False},sent)

    async def cv_wait_kept(account,wait,sent):
        """The wait saved with the message it is on now: a new one when Telegram would no longer change the old."""
        if getattr(sent,'message_id',None): wait['screen']=[wait['screen'][0],sent.message_id]
        await sync_to_async(set_prompt)(account,'cv_wait',wait)
        CV_WAITING.add(wait['screen'][0])
        return sent

    async def cv_wait_stalled(message,account,wait):
        """A wait whose place has not moved for CV_WAIT_LIMIT: said to take longer than usual.

        It goes on: still looked at (every CV_WAIT_STALLED_POLL seconds), and
        it still becomes the review here by itself once the files are read.
        Check now only looks at once.
        """
        rows=[[await button(account,'cv_wait_check_now','cv_wait_check')],
              [InlineKeyboardButton(text=text(account,'cancel_button'),callback_data=wait['cancel'])]]
        body=f'<b>{html.escape(TOOL_NAMES[ai.CV][account.locale])}</b>\n{text(account,"cv_wait_slow")}'
        sent=await render(message,body,rows,True)
        return await cv_wait_kept(account,{**wait,'stalled':True},sent)

    async def cv_wait_look(screen,account,wait,again=False):
        """One look at a chat's wait: once its files are read, what it waited for; else its place, said when it moved.

        `screen` is its message. A place is said again only when it moved, and
        at most every CV_WAIT_EDIT seconds. A place that has not moved for
        CV_WAIT_LIMIT (no reader is taking the reads) is said to take longer
        than usual, once; the wait goes on, and is the waiting message again
        when its place moves. A file being read, or a place that keeps moving,
        never stalls. `again` (Check now, or a file or a note sent to it) draws
        it at once and starts it anew.
        """
        status=await sync_to_async(ai.cv_reading)(account,wait['source_ids'])
        if status is None: return await cv_wait_done(screen,account,wait)
        now=time.time()
        if again: return await cv_wait_screen(screen,account,{**wait,'since':now,'moved_at':now},status)
        if cv_place(status)==wait.get('shown'):
            if wait.get('stalled'): return None
            if now-float(wait.get('moved_at') or wait.get('since') or 0)>CV_WAIT_LIMIT.total_seconds():
                return await cv_wait_stalled(screen,account,wait)
            return None
        if wait.get('stalled') or now-float(wait.get('shown_at') or 0)>=CV_WAIT_EDIT:
            return await cv_wait_screen(screen,account,wait,status)
        return None

    async def cv_wait_done(screen,account,wait):
        """The files a chat waited for are read: what it waited for, in the waiting message's place.

        A CV already made from them ('show': Telegram did not take its review)
        is drawn, never made again; files or words sent to it since are added
        to it first. Whatever is made is kept only while the chat still waits
        on this message (cv_still_waiting).
        """
        way=wait.get('cv_source') if wait.get('cv_source') in (ai.LINKEDIN,ai.FILE) else ai.FILE
        notes=[str(note) for note in wait.get('notes') or [] if note]
        ids=[str(identifier) for identifier in wait.get('source_ids') or []]
        window={key:wait[key] for key in ('files_at','album') if wait.get(key)}
        if wait.get('then') in ('add','show'):
            added=[str(identifier) for identifier in wait.get('added') or []]
            # Each message sent to the wait is a line of the notes, as on the review.
            more='\n'.join(str(piece) for piece in wait.get('more') or [] if piece)
            if wait.get('then')=='show' and not added and not more:
                draft,quote=await sync_to_async(ai.quote)(account,wait.get('draft_id',''))
                if not await sync_to_async(cv_still_waiting)(account,wait): return None
                return await ai_review(screen,account,draft,quote,True,wait.get('notice',''),files=window,waited=True)
            return await cv_add(screen,account,wait.get('draft_id',''),added,more,window=window,
                                notice=wait.get('notice',''),waited=wait)
        # A photo sent first with no text in it is the portrait, and what was written with it or since its description.
        if wait.get('then')=='photo' and len(ids)==1 and not await sync_to_async(ai.cv_readable)(account,ids,way):
            if not await sync_to_async(cv_still_waiting)(account,wait): return None
            return await cv_portrait_first(screen,account,ids[0],wait.get('caption',''),notes)
        return await cv_build(screen,account,way,notes,ids,given=bool(wait.get('given')),asked=int(wait.get('asked') or 0),
                              notice=wait.get('notice',''),at=wait.get('files_at'),album=wait.get('album'),waited=wait)

    def wait_screen(bot,wait):
        return _Screen(bot,*wait['screen'])

    async def cv_wait_join(bot,account,conversation,files,sent):
        """Files sent while the chat waits for the reader: more of the same CV's files, read in their turn.

        Their caption is more of its notes. A file its way does not take, or
        one past the files or pages one CV is made from, is said on the
        waiting message, and the wait goes on with the files that fit, as a
        review keeps the files that fit: the read of one left out is taken
        back, so the reader never spends its time on it. A photo sent first is
        no longer alone: the files make the CV. A wait that had stopped starts
        anew; one whose CV was made already adds them to it.
        """
        from apps.studio.cv.sources import checked
        wait=dict(conversation.prompt or {})
        way=wait.get('cv_source') if wait.get('cv_source') in (ai.LINKEDIN,ai.FILE) else ai.FILE
        ids,failure=await cv_upload(account,wait['screen'][0],files,way)
        captions=[item['caption'] for item in files if item['caption']]
        known=[str(identifier) for identifier in wait.get('source_ids') or []]
        fits=[]
        for identifier in [identifier for identifier in ids if identifier not in known]:
            try:
                await sync_to_async(checked)(account,[*known,*fits,identifier],way)
                fits.append(identifier)
            except DomainError as exc: failure=failure or exc
        left_out=[identifier for identifier in ids if identifier not in known and identifier not in fits]
        if left_out: await sync_to_async(cv_reads_dropped)(account,left_out)
        wait['source_ids']=[*known,*fits]
        if wait.get('then')=='show': wait['then']='add'
        if wait.get('then')=='add':
            wait['added']=[*wait.get('added',[]),*fits]
            wait['more']=kept_brief([*wait.get('more',[]),*captions],CV_BRIEF_CHARS,CV_BRIEF_PIECES)
        else:
            wait['notes']=kept_brief([*wait.get('notes',[]),*captions],CV_BRIEF_CHARS,CV_BRIEF_PIECES)
            if fits and wait.get('then')=='photo': wait['then']='build'
        wait['files_at']=max(sent,float(wait.get('files_at') or 0))
        wait['said']=await sync_to_async(cv_refusal_said)(account,failure) if failure else text(account,'cv_files_added')
        # Their reads were queued as they were uploaded (cv_upload).
        return await cv_wait_look(wait_screen(bot,wait),account,wait,again=True)

    async def cv_wait_text(message,account,conversation,value):
        """Words sent while the chat waits for the reader: more of the CV's notes, said so on the waiting message."""
        if not value: return await message.answer(text(account,'ai_topic_empty'))
        wait=dict(conversation.prompt or {})
        if wait.get('then')=='show': wait['then']='add'
        if wait.get('then')=='add': wait['more']=kept_brief([*wait.get('more',[]),value],CV_BRIEF_CHARS,CV_BRIEF_PIECES)
        else: wait['notes']=kept_brief([*wait.get('notes',[]),value],CV_BRIEF_CHARS,CV_BRIEF_PIECES)
        if wait.get('then')=='photo': wait['caption']='\n'.join(piece for piece in (wait.get('caption',''),value) if piece)[:CV_BRIEF_CHARS]
        wait['said']=text(account,'cv_notes_added')
        return await cv_wait_look(wait_screen(message.bot,wait),account,wait,again=True)

    async def cv_waits(bot,chats=None):
        """One look at every chat waiting for its CV's files (cv_wait_loop), or at `chats` (the local simulator's).

        Each is looked at under its chat's lock, its wait read again there: a
        file or a note may have joined it, or the customer moved on. A wait on
        the local simulator is never the real bot's to look at. A chat whose
        last look Telegram did not take is left alone while CV_WAIT_PAUSED
        says, a stalled wait is looked at every CV_WAIT_STALLED_POLL seconds,
        and a wait older than a question is kept (QUESTION_LIFETIME) is let go.
        """
        for chat_id in list(CV_WAITING if chats is None else chats):
            if CV_WAIT_PAUSED.get(chat_id,0)>time.time(): continue
            # A chat a handler is busy with is left to it: what it does looks at the wait, or the next turn will.
            lock=chat_lock(chat_id)
            if lock.locked(): continue
            async with lock:
                conversation=await sync_to_async(lambda:BotConversation.objects.filter(pk=chat_id,state='cv_wait').first())()
                wait=dict(conversation.prompt or {}) if conversation else {}
                if not wait.get('screen') or not cv_waiting(conversation) or (chats is None and wait.get('local')):
                    CV_WAITING.discard(chat_id)
                    CV_WAIT_LOOKED.pop(chat_id,None)
                    continue
                if wait.get('stalled'):
                    if time.time()-CV_WAIT_LOOKED.get(chat_id,0)<CV_WAIT_STALLED_POLL: continue
                    CV_WAIT_LOOKED[chat_id]=time.time()
                account=await sync_to_async(wait_account)(chat_id)
                if account is None:
                    CV_WAITING.discard(chat_id)
                    continue
                CV_WAIT_PAUSED.pop(chat_id,None)
                screen=wait_screen(bot,wait)
                began=timezone.now()
                try: await cv_wait_look(screen,account,wait)
                except Exception as exc: await cv_wait_failed(screen,account,wait,exc,began)

    async def cv_wait_failed(screen,account,wait,exc,began):
        """A look at a wait that failed, which never stops the others or comes back every turn.

        Telegram unreachable for a moment (a network error, its servers, or
        too many requests) changes nothing: the chat is looked at again once
        CV_WAIT_PAUSED lets it, and draws then what this look could not. What
        this look moved the chat on to is put back for that (cv_wait_restored),
        and a CV it made waits in the wait to be drawn, never made again
        (cv_wait_shown). A chat that blocked the bot is shown nothing. A
        refusal is said in the waiting message's place, and the wait is over:
        looking again would not change it. Anything else (a fault of ours, a
        message Telegram refuses) says the wait takes long; it is still looked
        at, and a CV made already is sent as a new message.
        """
        from aiogram.exceptions import TelegramForbiddenError,TelegramNetworkError,TelegramRetryAfter,TelegramServerError
        chat_id=wait['screen'][0]
        log=logging.getLogger(__name__)
        if isinstance(exc,(TelegramNetworkError,TelegramRetryAfter,TelegramServerError)):
            CV_WAIT_PAUSED[chat_id]=time.time()+max(CV_WAIT_POLL,float(getattr(exc,'retry_after',0) or 0))
            log.warning('A CV wait could not be drawn; it is looked at again shortly',exc_info=exc)
            await sync_to_async(cv_wait_restored)(account,wait,began)
            return None
        if isinstance(exc,TelegramForbiddenError):
            CV_WAITING.discard(chat_id)
            return None
        current=await sync_to_async(lambda:BotConversation.objects.filter(pk=account.telegram_user_id,state='cv_wait')
                                    .values_list('prompt',flat=True).first())()
        if current is not None and current.get('screen')==wait.get('screen'): wait=dict(current)
        if not isinstance(exc,DomainError) and not wait.get('stalled'):
            log.error('A CV wait could not be looked at',exc_info=exc)
        try:
            if isinstance(exc,DomainError):
                CV_WAITING.discard(chat_id)
                await sync_to_async(set_prompt)(account)
                return await render(screen,html.escape(bot_error(exc,account.locale,account)),[[await button(account,'home','home')]],True)
            if current is None and not await sync_to_async(cv_wait_restored)(account,wait,began): return None
            # Said once: a stalled wait that fails again is left to age out (cv_waits), never saved anew.
            if wait.get('stalled') and wait.get('then')!='show': return None
            if wait.get('then')=='show':
                # The CV is made: its review as a new message, below the one Telegram would not change.
                draft,quote=await sync_to_async(ai.quote)(account,wait.get('draft_id',''))
                window={key:wait[key] for key in ('files_at','album') if wait.get(key)}
                return await ai_review(screen,account,draft,quote,False,wait.get('notice',''),files=window,waited=True)
            return await cv_wait_stalled(screen,account,wait)
        except Exception:
            log.warning('A CV wait could not be said to have stopped',exc_info=True)
            # Stalled, it is looked at again later; kept as old as it was, so a wait that always fails ages out.
            if not isinstance(exc,DomainError):
                await sync_to_async(lambda:BotConversation.objects.filter(pk=account.telegram_user_id,state='cv_wait')
                                    .update(prompt={**wait,'stalled':True}))()

    async def cv_portrait_first(message,account,asset_id,caption,notes):
        """A photo with nothing to read in it, sent on the first CV screen: the CV's portrait, not an old CV.

        With a caption that says who the customer is, the CV is written from
        it, as the question about yourself takes a photo and its caption; with
        none, or one that says too little, the first screen again with the
        photo kept (and the caption as notes), saying how to send an old CV
        instead. A photo that cannot be a portrait either is a file with
        nothing to read.
        """
        from apps.studio.cv.content import says_little
        try: await sync_to_async(ai.check_portrait)(account,asset_id)
        except DomainError as exc:
            if exc.code not in ('invalid_image','image_pixel_limit'): raise
            return await cv_refused(message,account,ai.FILE,notes,DomainError('cv_file_unreadable'))
        if caption and not await sync_to_async(says_little)(caption):
            await sync_to_async(set_prompt)(account,'ai_input',{'feature_id':ai.CV,'portrait_asset_id':str(asset_id)})
            return await ai_start(message,account,ai.CV,caption,(),'',str(asset_id))
        await sync_to_async(set_prompt)(account,'cv_choose',{'feature_id':ai.CV,'portrait_asset_id':str(asset_id),
                                                              **({'notes':notes} if notes else {})})
        return await cv_choose(message,account,True,notice=text(account,'cv_photo_kept_choose'))

    async def ai_topic_needed(message,account,feature_id,brief,other='',edit=True,question='',notice='',portrait=None,ask='missing',
                              missing=(),copied=''):
        """A description that names no topic: what was kept of it, and the one thing missing.

        `message` is the "Preparing…" line, which becomes this question: one
        screen, not an error followed by the question again. What was written
        waits in the chat's state for the topic. A description asking for the
        other format is offered that service first, keeping what was written.
        `question` names this question in the state and on its button, and is
        kept while the same description is asked about again; `notice` is a
        line about what was just sent.

        For a CV what is missing is a name, a phone or email, or a job or
        school (`missing`, the required facts the server found missing): all
        are listed on one screen, each with an example, and answered in one
        message or several. A greeting, or a name alone, misses all but the
        name. A question kept before they were listed has `ask` 'name', or
        'details' for all of them (cv_asked). No other service is offered: a
        CV is about someone, not on a topic. Its photo (`portrait`, or None for
        the one already waiting) waits with it, and the examples button comes
        back to this question, not a blank one. `copied` is a sample of this
        screen just sent back (as `compared` gives it): sent again at once, it
        is the customer's own.
        """
        cv=feature_id==ai.CV
        question=question or secrets.token_urlsafe(6)
        if portrait is None: portrait=await sync_to_async(pending_portrait)(account) if cv else ''
        asked=cv_asked({'ask':ask,'missing':missing}) if cv else []
        state={'feature_id':feature_id,'brief':brief,'question':question,**({'portrait_asset_id':portrait} if portrait else {}),
               **({'ask':'missing','missing':asked,**({'copied':copied} if copied else {})} if cv else {})}
        await sync_to_async(set_prompt)(account,'ai_input',state)
        body=f'<b>{html.escape(TOOL_NAMES[feature_id][account.locale])}</b>\n'
        if notice: body+=f'{html.escape(notice)}\n'
        elif portrait: body+=f'{text(account,"cv_photo_line")}\n'
        rows=[]
        if other in ai.SERVICES and other!=feature_id and not cv:
            body+=f'<b>{text(account,"ai_wrong_tool_slides" if other==ai.SLIDES else "ai_wrong_tool_pdf")}</b>\n'
            rows.append([await button(account,'ai_switch_slides' if other==ai.SLIDES else 'ai_switch_pdf','ai_retarget',
                                      {'feature_id':other,'question':question})])
        body+=f'\n{text(account,"ai_topic_kept").format(brief=html.escape(brief_quote(brief)))}\n\n'
        if cv: body+=missing_lines(account,asked,written=brief)
        else:
            sample=f'<code>{html.escape(text(account,"ai_topic_sample"))}</code>'
            body+=(f'{text(account,"ai_topic_question")}\n{text(account,"ai_topic_example").format(example=sample)}\n'
                   f'{text(account,"ai_topic_again")}')
        # A PDF or Word file sent here was meant as the old CV: the way to that
        # screen, which keeps what was written as its notes (cv_mode).
        if cv and notice==text(account,'cv_photo_only'):
            rows.append([await button(account,'cv_mode_file','cv_mode',{'cv_source':ai.FILE})])
        # A CV's examples come back to this question, or once it is closed to
        # the question about yourself, never to the first CV screen.
        rows.append([await button(account,'ai_examples','ai_examples',{'feature_id':feature_id,
                                                                       **({'question':question,'cv_source':ai.TEXT} if cv else {})})])
        rows.append([await button(account,'ai_back','home')])
        return await render(message,body,rows,edit)

    async def ai_convert(message,account,edit=True):
        """A file conversion asked of an AI service ("pdf ga o‘tkaz", "convert to
        pdf"): the file tools do it, so they are offered in place of the topic
        question. The question is closed, so a file sent next starts a file task."""
        await sync_to_async(set_prompt)(account)
        draft=await sync_to_async(draft_for)(account)
        available={f['id'] for f in await sync_to_async(catalog)(account)}
        rows=[[await tool_button(account,draft,key)] for key in ('convert.word_to_pdf','convert.pptx_to_pdf','pdf.images_to_pdf')
              if key in available]
        rows.append([await button(account,'all_tools','menu'),await button(account,'home','home')])
        return await render(message,html.escape(text(account,'ai_convert')),rows,edit)

    async def ai_revise_prompt(message,account,draft_id,edit=False,notice=''):
        """One screen: what should change? Everything unmentioned stays put. `notice` is a line about a file just sent."""
        title=await sync_to_async(ai.revisable)(account,draft_id)
        if title is None: return await safe_error(message,account,DomainError('revision_not_ready'))
        # A file with no edits left says so now, not after the change is written.
        try: await sync_to_async(ai.editable)(account,draft_id)
        except DomainError as exc: return await safe_error(message,account,exc)
        await sync_to_async(set_prompt)(account,'ai_revise',{'draft_id':str(draft_id)})
        # A CV has no pages to resize: its examples are the changes a CV takes.
        examples='cv_revise_examples' if await sync_to_async(ai.service_of)(account,draft_id)==ai.CV else 'ai_revise_examples'
        body=(f'{html.escape(notice)}\n\n' if notice else '')+(f'<b>{text(account,"ai_revise_title")}</b>\n'
              f'{text(account,"ai_revise_of")}: {html.escape(title)}\n\n'
              f'{text(account,"ai_revise_ask")}\n\n'
              f'{text(account,"ai_examples")}:\n<code>{html.escape(text(account,examples))}</code>')
        rows=[[await button(account,'ai_back','home')]]
        return await render(message,body,rows,edit)

    async def ai_refused(message,account,exc,resume,again):
        """An AI request that could not be priced, said once.

        `message` is the bot's own "Preparing…" line. Channels to join replace
        it; a used-up limit, or any other error, takes its place, and only an
        error the customer can fix by writing again asks the question again.
        """
        if exc.code=='channels_required':
            await sync_to_async(set_prompt)(account)
            from .channels import show_gate
            return await show_gate(message,account,resume=resume,edit=True)
        # The shared error copy cannot say what the chat does with a file format.
        body=html.escape(text(account,'ai_format_only') if exc.code=='format_only_change' else bot_error(exc,account.locale,account))
        if exc.code in ('weekly_ai_limit','edit_limit'):
            # Nothing to rewrite: the limit and the way past it, in place of "Preparing…".
            await sync_to_async(set_prompt)(account)
            return await render(message,body,[[await button(account,'plans','plans',FROM_LIMIT)],[await button(account,'home','home')]],True)
        await render(message,body,[],True)
        return await again()

    async def ai_revise_start(message,account,draft_id,request):
        """The change is priced and shown before an edit is used, as ever.

        `message` is the "Preparing…" line, which becomes the priced draft.
        """
        # A file format and nothing else is not an AI edit: the AI would only
        # write the same document again and spend an edit on it.
        kind,feature=await sync_to_async(ai.asked_format)(account,draft_id,request)
        if kind=='pdf' and feature==ai.SLIDES: return await deck_as_pdf(message,account,draft_id)
        if kind=='pptx' and feature==ai.DOCUMENT: return await document_as_slides(message,account,draft_id)
        if kind: return await send_again(message,account,draft_id,kind)
        draft=None
        try:
            draft=await sync_to_async(ai.revise)(account,draft_id,request)
            _,quote=await sync_to_async(ai.quote)(account,draft.id)
        except DomainError as exc:
            resume={'kind':'ai_draft','draft_id':str(draft.id)} if draft else {}
            return await ai_refused(message,account,exc,resume,lambda:ai_revise_prompt(message,account,draft_id))
        await sync_to_async(set_prompt)(account)
        await ai_review(message,account,draft,quote,True)

    async def deck_as_pdf(message,account,draft_id):
        """The delivered deck in PowerPoint → PDF, ready to start; or, once the
        server no longer keeps it, the same tool offered for the copy in the chat."""
        await sync_to_async(set_prompt)(account)
        try: draft=await sync_to_async(ai.deck_to_pdf)(account,draft_id)
        except DomainError as exc: return await safe_error(message,account,exc)
        if draft: return await controls(message,account,draft,True,notice=text(account,'ai_deck_as_pdf'))
        waiting=await sync_to_async(draft_for)(account)
        rows=[[await tool_button(account,waiting,ai.CONVERTER)],[await button(account,'home','home')]]
        await render(message,html.escape(text(account,'ai_deck_gone')),rows,True)

    async def document_as_slides(message,account,draft_id):
        """A change cannot make slides of a PDF: a new deck on the same subject
        is offered instead, made from the description the document began with."""
        await sync_to_async(set_prompt)(account)
        rows=[[await button(account,'ai_as_slides','ai_switch',{'draft_id':str(draft_id),'feature_id':ai.SLIDES})],
              [await button(account,'ai_revise','ai_revise',{'draft_id':str(draft_id)}),await button(account,'home','home')]]
        await render(message,html.escape(text(account,'ai_doc_to_slides')),rows,True)

    async def send_again(message,account,draft_id,kind):
        """The file asked for in the format it already has: the same file, sent again."""
        await sync_to_async(set_prompt)(account)
        job,_=await sync_to_async(ai.delivered)(account,draft_id)
        if job is None:
            rows=[[await button(account,'ai_revise','ai_revise',{'draft_id':str(draft_id)}),await button(account,'home','home')]]
            return await render(message,html.escape(text(account,'ai_file_gone')),rows,True)
        name='PDF' if kind=='pdf' else 'PowerPoint'
        await render(message,html.escape(text(account,'ai_same_format').format(format=name)),[],True)
        await deliver(message,account,job,f'same-format:{secrets.token_urlsafe(9)}')

    async def ai_examples(message,account,feature_id=None,edit=False,question='',cv_source=''):
        """What a good description looks like, in the customer's language.

        Opened from a CV's open question (`question`), its service button goes
        back to that question with what was written, not to a blank one; opened
        from the question about yourself (`cv_source` 'text'), back to it, not
        to the first CV screen that asks how to make one.
        """
        rows=[]
        body=f'<b>{text(account,"ai_examples_title")}</b>'
        for fid in ([feature_id] if feature_id else list(ai.SERVICES)):
            body+=f'\n\n<b>{html.escape(TOOL_NAMES[fid][account.locale])}</b>'
            for index in range(len(PROMPT_EXAMPLES[fid])):
                body+=f'\n\n{index+1}. <code>{html.escape(ai_example(account,fid,index))}</code>'
            back={'feature_id':fid,**({'question':question} if question and fid==feature_id else {}),
                  **({'cv_source':cv_source} if cv_source and fid==feature_id else {})}
            rows.append([InlineKeyboardButton(text=TOOL_NAMES[fid][account.locale],callback_data=await callback(account,'ai_tool',back))])
        rows.append([await button(account,'ai_back','home'),
                     InlineKeyboardButton(text=text(account,'ai_open_web'),url=await ai_studio_url(account))])
        await render(message,body,rows,edit)

    async def ai_review(message,account,draft,quote,edit=False,notice='',files=None,waited=False):
        """Never submit without showing this: it says what the document uses of the plan.

        A new CV's review stays open to a photo: one sent while it is the
        chat's screen goes on that CV (receive()), as its hint says, and so
        does the rest of a description Telegram split in two (fallback()).
        For a CV just made from files, `files` is {'files_at', 'album'}: when
        Telegram took the newest of them, and the album they came in. With
        when the review was drawn, they say which file sent next is one more
        of them (cv_takes_more). The review drawn again for the same CV keeps
        them. `notice` is a line said above it. `waited`: the review a wait
        for the reader became, the chat's screen only while it still waits (a
        customer who moved on meanwhile keeps where they went).
        """
        import time
        body,rows=await review_screen(account,draft,quote)
        if notice: body=html.escape(notice)+'\n\n'+body
        sent=await render(message,body,rows,edit)
        await remember_review(account,draft,sent or message)
        if draft.feature_id==ai.CV and not await sync_to_async(ai.revised_from)(draft):
            # Files on their way to this CV (a wait to add them) go on waiting: a review drawn
            # elsewhere meanwhile (a language tapped on it) is not the end of their wait.
            going=await sync_to_async(lambda:BotConversation.objects.filter(pk=account.telegram_user_id,state='cv_wait')
                                      .values_list('prompt',flat=True).first())() or {}
            if (going.get('then') in ('add','show') and going.get('draft_id')==str(draft.id)
                    and (going.get('screen') or [0,0])[1]!=getattr(message,'message_id',None)): return sent
            if files is None:
                shown=await sync_to_async(lambda:BotConversation.objects.filter(pk=account.telegram_user_id,state='cv_review')
                                          .values_list('prompt',flat=True).first())() or {}
                files={key:shown[key] for key in ('files_at','album','drawn_at') if key in shown} if shown.get('draft_id')==str(draft.id) else {}
            elif files: files={**{key:value for key,value in files.items() if value},'drawn_at':time.time()}
            shown={'draft_id':str(draft.id),**files}
            if waited:
                await sync_to_async(lambda:BotConversation.objects.filter(pk=account.telegram_user_id,state='cv_wait')
                                    .update(state='cv_review',prompt=shown,updated_at=timezone.now()))()
            else: await sync_to_async(set_prompt)(account,'cv_review',shown)
        return sent

    async def ai_start(message,account,feature_id,description,brief=(),question='',portrait='',missing=(),copied=''):
        """One chat message in, a priced draft out. Nothing is counted yet.

        `message` is the "Preparing…" line, which becomes the priced draft.
        `brief` is what was kept of an earlier description that named no topic:
        this message is its topic, so it goes first and becomes the title. A
        message that is a whole description of its own ("A 3 page PDF report
        about volcanoes") replaces what was kept instead: joined on, an earlier
        "10 slides please" would contradict it. `question` is the topic question
        this answers, asked again under the same name if the topic is still missing.

        For a CV, `brief` is what was written before (a description that lacked
        something, or a greeting), `missing` the required facts that question
        asked for, and `portrait` the photo sent for it. What was written is
        always kept: a CV can only say what the customer told us, and a fact
        said twice is better than one lost. The server says what is missing
        (name, phone or email, job or school) and the customer is asked for it,
        in one message or several. Words sent again are the way past a check
        that does not see what is there, but only a real description is made
        into a CV that way (cv_insists), never a greeting, a name alone or a
        name with a phone or email: while the name is missing, only an answer
        that looks like one ("dilnoza karimova") counts, never a line of the
        description sent again; while the job or school is missing, only a
        description that says more about the person than who they are and how
        to reach them. So a short bio with a name and a school is made without
        the phone or email it lacks. A message holding a sample of the missing
        screen, or a copy of its list, is ours, not theirs (sent_back): not
        kept, and the screen says so, however often it is sent (sample_held);
        only the sample name sent again at once (`copied`) is the customer's own.
        """
        draft=None
        cv=feature_id==ai.CV
        from apps.studio.topics import restates
        if brief and not cv and await sync_to_async(restates)(description,list(brief)): brief=()
        # The topic question answered with the same words again, or answered a
        # second time, is taken as it is: the check reads words, and a topic it
        # does not know ("Bahor") must not keep the customer asking.
        repeated=[piece for piece in brief if compared(piece)==compared(description)]
        # A sample the missing screen shows, sent back as it is: the same screen, saying it is
        # ours, and nothing kept. Only the sample name sent again at once is the customer's own;
        # a sample phone, email, job or school, or the list's own labels, never are (sample_held).
        if (cv and brief and missing and not repeated
                and (sample_held(description) or (compared(description)!=copied and sent_back(description)))):
            return await ai_topic_needed(message,account,feature_id,list(brief),question=question,
                                         notice=text(account,'cv_example_copied'),portrait=portrait or None,missing=missing,
                                         copied=compared(description))
        given=bool(repeated) or len(brief)>=2
        brief=[piece for piece in brief if piece not in repeated]
        # The words are the same whichever way they were typed: the first time is kept, as written then.
        if repeated and cv: description=repeated[0]
        # Our own example sent back unchanged would make our example, not theirs.
        if await sync_to_async(ai.is_example)(description):
            return await render(message,text(account,'cv_example_copied' if cv else 'ai_example_copied'),
                                [[await button(account,'ai_examples','ai_examples',{'feature_id':feature_id,
                                                                                    **({'cv_source':ai.TEXT} if cv else {})}),
                                  await button(account,'cancel_button','home')]],True)
        if cv:
            from apps.studio.cv.sources import linkedin_link_only
            # The same words sent again are taken as they are: while the name is missing, if
            # they look like one; while the job or school is missing, if the description,
            # read once, says more than a name, a phone and an email (cv_insists).
            given=await sync_to_async(cv_insists)(repeated,missing,[description,*brief],description)
            # A photo that arrived while this was on its way is the CV's too.
            portrait=portrait or await sync_to_async(pending_portrait)(account)
            # A LinkedIn profile's link is never opened: the way to send the profile instead.
            if linkedin_link_only('\n'.join([description,*brief])):
                return await cv_mode_screen(message,account,ai.LINKEDIN,True,link=True,portrait=portrait)
        # A photo kept with the question may have expired since: the CV goes ahead without it.
        portrait=await sync_to_async(ai.usable_portrait)(account,portrait) if cv else ''
        try:
            file_ids=await sync_to_async(lambda:draft_for(account).input_ids)()
            draft=await sync_to_async(ai.build)(account,feature_id,'\n'.join([description,*brief]),file_ids,given,portrait)
            await sync_to_async(funnel.step)('ai.described',account=account,feature=feature_id)
            _,quote=await sync_to_async(ai.quote)(account,draft.id)
        except DomainError as exc:
            if exc.code=='convert_requested': return await ai_convert(message,account)
            if exc.code=='cv_linkedin_link': return await cv_mode_screen(message,account,ai.LINKEDIN,True,link=True,portrait=portrait)
            if exc.code=='cv_missing':
                # Something a CV needs is not there yet: everything written is
                # kept, and what is missing listed, with an example of each.
                return await ai_topic_needed(message,account,feature_id,kept_brief([*brief,description],CV_BRIEF_CHARS,CV_BRIEF_PIECES),
                                             question=question if brief else '',portrait=portrait,
                                             missing=(exc.params or {}).get('missing') or [])
            if exc.code=='topic_required':
                # Still no topic: both pieces are kept, and the topic asked for again.
                other=(exc.params or {}).get('service') or ''
                return await ai_topic_needed(message,account,feature_id,kept_brief([*brief,description]),other,
                                             question=question if brief else '')
            # The description is kept: after joining, the customer is shown its
            # review; without one, the question again (a CV's about yourself).
            resume=({'kind':'ai_draft','draft_id':str(draft.id)} if draft else {'kind':'cv_mode','cv_source':ai.TEXT} if cv
                    else {'kind':'ai_prompt','feature_id':feature_id})
            return await ai_refused(message,account,exc,resume,lambda:ai_prompt(message,account,feature_id))
        # A new CV's review takes a photo sent while it is drawn, so the chat
        # says so from now on: never empty while the review is on its way.
        if cv: await sync_to_async(set_prompt)(account,'cv_review',{'draft_id':str(draft.id)})
        else: await sync_to_async(set_prompt)(account)
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
                # A new document the AI could not finish: the advice the notice
                # gave, and a new description beside Retry (notifications.py).
                from .notifications import model_failed
                if model_failed(job):
                    body+='\n\n'+text(account,'cv_failed_advice' if job.feature_id==ai.CV else 'ai_failed_advice')
                    rows.append([await button(account,'ai_change_topic','ai_tool',{'feature_id':job.feature_id})])
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
            label=f'{STATUS[account.locale].get(job.status,job.status)} · {title} · {local_time(account,job.created_at):%m/%d %H:%M}'
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
        unlimited=text(account,'unlimited')
        week='\n'.join(f'{text(account,label)}: '+(f'{usage[key]["used"]} / {usage[key]["limit"]}' if usage[key]['limit'] is not None else unlimited)
                       for key,label in (('ai_documents','week_ai_documents'),('file_jobs','week_file_jobs')))
        edits=usage['edits_per_file']
        body=(f'<b>{text(account,"account")}</b>\n{text(account,"plan_label")}: {html.escape(text(account,'free_plan') if account.plan=='free' else account.plan.title())}\n{text(account,"linked_methods")}: {", ".join(methods)}\n\n'
              f'{week}\n{text(account,"edits_per_file")}: {unlimited if edits is None else edits}\n'
              f'{text(account,"resets")}: {week_reset(account,usage["resets_at"])}\n\n{text(account,"link_instructions")}')
        await render(message,body,[[await button(account,'plans','plans',{'from':'account'}),await button(account,'subscription','subscription')],[InlineKeyboardButton(text=text(account,'link_methods'),url=await web_url(account,'settings'))],[await button(account,'language_button','language'),await button(account,'home','home')]],edit)

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
        # Stop Telegram's spinner before any costly action. Crop and enhance
        # are automatic now: their old buttons are answered with a notice.
        retired=usable(ref) and retired_switch(ref)
        await (query.answer(text(ref.account,'scan_switches_retired'),show_alert=True) if retired else query.answer())
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
            elif action=='home' and p.get('from')=='cv_wait':
                # Cancel on the waiting message: the wait is ended under its lock, never turned into a review after.
                async with chat_lock(message.chat.id): await home(message,account,True)
            elif action=='home': await home(message,account,True)
            elif action=='language': await show_language(message,query.from_user,{})
            elif action=='menu': await menu(message,account,p.get('page',0),p.get('category','pdf'),True)
            elif action=='controls': await controls(message,account,edit=True,advanced=p.get('advanced',False))
            elif action=='ai_examples': await ai_examples(message,account,p.get('feature_id'),True,p.get('question',''),p.get('cv_source',''))
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
                    else:
                        # Back from the examples to a CV's open question: what was
                        # written, and the photo, are still waiting for the answer.
                        waiting=await sync_to_async(pending_question)(account,p.get('question',''))
                        if waiting and waiting.get('feature_id')==p['feature_id']:
                            return await ai_topic_needed(message,account,p['feature_id'],list(waiting['brief']),'',True,
                                                         p['question'],ask=waiting.get('ask','missing'),missing=waiting.get('missing') or ())
                        # A CV is asked first how it is made. Its description written
                        # again goes back to the way it was made, keeping its photo and
                        # the files it was made from; back from the examples of the
                        # question about yourself, to that question.
                        if p['feature_id']==ai.CV and p.get('cv_source')!=ai.TEXT:
                            again=await sync_to_async(ai.written_again)(account,p['draft_id']) if p.get('draft_id') else None
                            if again is None: return await cv_choose(message,account,True)
                            if again['cv_source'] in (ai.LINKEDIN,ai.FILE):
                                return await cv_mode_screen(message,account,again['cv_source'],True,notes=again['notes'],
                                                            files=again['source_ids'],ask='again' if again['source_ids'] else 'file',
                                                            portrait=again['portrait_asset_id'])
                            return await ai_prompt(message,account,ai.CV,True,portrait=again['portrait_asset_id'])
                        # A CV's description written again keeps the photo of the CV it rewrites.
                        portrait=await sync_to_async(ai.kept_portrait)(account,p['draft_id']) if p.get('draft_id') else None
                        await ai_prompt(message,account,p['feature_id'],True,portrait=portrait)
            elif action=='cv_mode':
                # A way to make a CV, chosen on its first screen; none is that screen.
                # Each only opens a screen: what it keeps waits in the chat's state.
                way=p.get('cv_source','')
                try: await sync_to_async(ai.available)(account,ai.CV)
                except DomainError as exc: await safe_error(message,account,exc)
                else:
                    from .channels import blocked,show_gate
                    current=await blocked(account)
                    if current: await show_gate(message,account,current,resume={'kind':'cv_mode','cv_source':way},edit=True)
                    elif way==ai.TEXT:
                        # Notes written for a file are the start of the description, never lost.
                        kept=await sync_to_async(cv_kept)(account)
                        if kept['notes']:
                            portrait=kept['portrait_asset_id']
                            await sync_to_async(set_prompt)(account,'ai_input',{'feature_id':ai.CV,**({'portrait_asset_id':portrait} if portrait else {})})
                            await render(message,text(account,'ai_preparing'),[],True)
                            await ai_start(message,account,ai.CV,'\n'.join(kept['notes']),(),'',portrait)
                        else: await ai_prompt(message,account,ai.CV,True)
                    elif way in (ai.LINKEDIN,ai.FILE):
                        # A description still waiting for what it lacks becomes the notes on the file.
                        brief=await sync_to_async(cv_brief)(account)
                        await cv_mode_screen(message,account,way,True,notes=kept_brief(brief,CV_BRIEF_CHARS,CV_BRIEF_PIECES) if brief else None)
                    else: await cv_choose(message,account,True)
            elif action=='cv_retry':
                # The CV made again from the files kept after a refusal that passed (cv_build).
                conversation=await sync_to_async(lambda:BotConversation.objects.filter(pk=account.telegram_user_id).first())()
                kept=(conversation.prompt or {}) if cv_screen_open(conversation) and conversation.state=='cv_source' else {}
                way=kept.get('cv_source')
                if kept.get('source_ids') and kept.get('ask')=='again' and way in (ai.LINKEDIN,ai.FILE):
                    await render(message,text(account,'ai_preparing'),[],True)
                    async with chat_lock(message.chat.id):
                        await cv_build(message,account,way,[str(note) for note in kept.get('notes') or [] if note],
                                       [str(identifier) for identifier in kept['source_ids']])
                else: await cv_choose(message,account,True)
            elif action=='cv_photo_as':
                # A photo sent on a CV made from photos or screenshots: its portrait, or one more page (cv_file).
                async with chat_lock(message.chat.id): await cv_photo_as(message,account,p.get('draft_id',''),p.get('as',''))
            elif action=='cv_wait_check':
                # Check now on a wait that took long: the files are looked at again, never sent again.
                # Only on the message the wait is on: an older one's button leaves a newer wait where it is.
                async with chat_lock(message.chat.id):
                    conversation=await sync_to_async(lambda:BotConversation.objects.filter(pk=account.telegram_user_id,state='cv_wait').first())()
                    wait=dict(conversation.prompt or {}) if cv_waiting(conversation) else {}
                    if wait.get('screen') and wait['screen'][1]==message.message_id:
                        await cv_wait_look(message,account,wait,again=True)
                    elif wait.get('screen'): await render(message,text(account,'cv_wait_moved'),[],True)
                    else: await home(message,account,True,notice=text(account,'stale_button'))
            elif action=='ai_retarget':
                # "Make slides instead" on the topic question: what was written,
                # now for the other service, after the checks choosing it makes.
                # Once that question is answered or old, it is a plain choice.
                # A button from an older question carries nothing a newer one kept.
                try: await sync_to_async(ai.available)(account,p['feature_id'])
                except DomainError as exc: await safe_error(message,account,exc)
                else:
                    from .channels import blocked,show_gate
                    current=await blocked(account)
                    question=p.get('question','')
                    brief=await sync_to_async(pending_brief)(account,question)
                    if current:
                        # Behind the channels, the topic typed next is for the service chosen.
                        if brief: await sync_to_async(set_prompt)(account,'ai_input',{'feature_id':p['feature_id'],'brief':brief,'question':question})
                        resume={'kind':'ai_topic','feature_id':p['feature_id'],'question':question} if brief else {'kind':'ai_prompt','feature_id':p['feature_id']}
                        await show_gate(message,account,current,resume=resume,edit=True)
                    elif brief: await ai_topic_needed(message,account,p['feature_id'],brief,question=question)
                    else: await ai_prompt(message,account,p['feature_id'],True)
            elif action=='ai_switch':
                try: draft,quote=await sync_to_async(ai.switch)(account,p['draft_id'],p['feature_id'])
                except DomainError as exc:
                    # A draft accepted before descriptions were read for a topic, or
                    # whose file has gone since: the topic is asked for, for the
                    # service chosen, keeping the description.
                    if exc.code=='topic_required':
                        brief=await sync_to_async(ai.description_of)(account,p['draft_id'])
                        await ai_topic_needed(message,account,p['feature_id'],kept_brief([brief]),(exc.params or {}).get('service') or '')
                    elif exc.code=='convert_requested': await ai_convert(message,account)
                    else: await safe_error(message,account,exc)
                else: await ai_review(message,account,draft,quote,True)
            elif action=='ai_count': pass  # The count on the stepper; the tap is already answered.
            elif action in ('ai_length','ai_locale'):
                change=ai.resize if action=='ai_length' else ai.relocale
                value=p['pages'] if action=='ai_length' else p['locale']
                try: draft,quote=await sync_to_async(change)(account,p['draft_id'],value)
                except DomainError as exc:
                    # ➖/➕ or a language left on a change's old review, or on a
                    # draft gone since: an old button, so the menu, said so.
                    if exc.code=='controls_expired': await home(message,account,True,notice=text(account,'stale_button'))
                    else: await safe_error(message,account,exc)
                else: await ai_review(message,account,draft,quote,True)
            elif action=='ai_run':
                # Generate on a CV whose added files are still being read: not made without them.
                if await sync_to_async(cv_adding)(account,p.get('draft_id','')):
                    draft,quote=await sync_to_async(ai.quote)(account,p['draft_id'])
                    body,rows=await review_screen(account,draft,quote)
                    return await render(message,html.escape(text(account,'cv_wait_adding'))+'\n\n'+body,rows,True)
                existing=await sync_to_async(ai.submitted)(account,p['quote_id'])
                job=existing or await sync_to_async(ai.start)(account,p['quote_id'])
                await sync_to_async(forget_review)(account,p['draft_id'])
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
            elif action=='settings' and retired:
                # The task they belong to, if still under way, is redrawn without them.
                draft=await sync_to_async(lambda:BotDraft.objects.filter(account=account,pk=p.get('draft_id'),feature_id='pdf.images_to_pdf',state='collecting').first())()
                if draft: await controls(message,account,draft,True,advanced=p.get('advanced',False))
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
            # Where the button was: a button from before sources were kept is
            # 'other'. The button itself, so a double tap on it is one look.
            elif action=='plans': await show_offers(message,account,True,source=p.get('from'),tap=ref.token)
            elif action=='channels_check':
                from .channels import check as check_channels
                if await check_channels(message,account,p):
                    kind=p.get('kind')
                    if kind=='ai_draft': await ai_resume(message,account,p['draft_id'])
                    elif kind=='ai_prompt' and p.get('feature_id')==ai.CV: await cv_choose(message,account)
                    elif kind=='ai_prompt': await ai_prompt(message,account,p['feature_id'])
                    elif kind=='cv_mode':
                        # The CV's screen again, with the files and notes kept behind the channels.
                        way=p.get('cv_source','')
                        conversation=await sync_to_async(lambda:BotConversation.objects.filter(pk=account.telegram_user_id).first())()
                        if way==ai.TEXT: await ai_prompt(message,account,ai.CV)
                        elif way not in (ai.LINKEDIN,ai.FILE): await cv_choose(message,account)
                        elif conversation and conversation.state=='cv_source' and (conversation.prompt or {}).get('cv_source')==way:
                            await cv_screen_again(message,account,conversation)
                        else: await cv_mode_screen(message,account,way)
                    elif kind=='ai_topic':
                        # The topic question again, for the service chosen, with what was kept.
                        question=p.get('question','')
                        brief=await sync_to_async(pending_brief)(account,question)
                        if brief: await ai_topic_needed(message,account,p['feature_id'],brief,edit=False,question=question)
                        else: await ai_prompt(message,account,p['feature_id'])
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

    def cv_question(conversation):
        """Whether the chat is asking for a CV's description (or what it lacks) now."""
        return bool(conversation) and conversation.state=='ai_input' and (conversation.prompt or {}).get('feature_id')==ai.CV

    async def cv_file(message,bot,account,name,raw):
        """A file sent while a CV is described, or while a new CV's review is on screen; False when it is not the CV's.

        A JPG or PNG is the CV's photo. Sent with the question, it waits with
        it on a receipt, never on the file tools' draft (the menu would offer to
        continue an images-to-PDF task nobody started), and a caption sent with
        it, or with the album it came in, is the description. Sent on the
        review, it goes on that CV, which is priced again; a caption sent with
        it then is not read, and the customer is told. On the review of a CV
        made from photos or screenshots it may as well be one more page: the
        customer is asked which (cv_photo_as). Of an album, only the newest
        photo counts (on a CV made from files, an album is more of its files:
        cv_takes_more). Any other file is not read for a CV, and the question
        says so, with the way to the old-CV screen.

        The chat is read again once this file has its turn (chat_lock): a
        description sent with the photo may have made its review meanwhile,
        and the photo goes on that. A chat that has moved on from the CV by
        then (False) takes the file as an ordinary one.
        """
        album_caption(message)
        target,edit=await album_target(message,bot)
        if target is None: return True
        photo=name.rsplit('.',1)[-1].lower() in ('jpg','jpeg','png')
        async with chat_lock(message.chat.id):
            conversation=await sync_to_async(lambda:BotConversation.objects.filter(pk=message.from_user.id).first())()
            reviewing=(bool(conversation) and conversation.state=='cv_review'
                       and bool(await sync_to_async(open_cv_review)(account)))
            if not (reviewing and photo or cv_question(conversation)): return False
            pending=conversation.prompt or {}
            caption=album_caption(message)
            asset,notice=None,'' if photo else text(account,'cv_photo_only')
            # On a CV made from photos or screenshots, one photo on its own may
            # be the portrait or one more page: asked (cv_photo_as), and only
            # checked as a portrait once it is one.
            made=await sync_to_async(ai.cv_files)(account,pending.get('draft_id','')) if reviewing and photo else None
            asking=bool(made and made['images'] and not made['revision'] and not getattr(message,'media_group_id',None))
            if photo:
                try:
                    asset=await sync_to_async(upload_file)(account,SimpleUploadedFile(name,raw),'bot')
                    if not asking: await sync_to_async(ai.check_portrait)(account,asset.id)
                    await sync_to_async(record_receipt)(account,asset,message.chat.id,message.message_id)
                except DomainError as exc:
                    # Too large, or not really a JPEG or PNG: said now, so the
                    # description sent next is not refused for it.
                    if exc.code not in ('invalid_image','image_pixel_limit'): raise
                    asset,notice=None,text(account,'cv_photo_rejected')
            if reviewing:
                if asset is None:
                    album_shown(message,await render(target,html.escape(notice),[],edit))
                    return True
                if asking:
                    # A caption sent with it waits too: notes on a page, never read with a portrait.
                    await sync_to_async(set_prompt)(account,'cv_review',{**pending,'photo_asked':str(asset.id),
                                                                         **({'photo_caption':caption} if caption else {})})
                    draft_id=pending.get('draft_id','')
                    rows=[[await button(account,'cv_photo_is_portrait','cv_photo_as',{'draft_id':draft_id,'as':'portrait'})],
                          [await button(account,'cv_photo_is_page','cv_photo_as',{'draft_id':draft_id,'as':'page'})]]
                    album_shown(message,await render(target,text(account,'cv_photo_or_page'),rows,edit))
                    return True
                draft,quote=await sync_to_async(ai.add_portrait)(account,pending.get('draft_id',''),asset.id)
                # Words sent with it would skip the name and detail checks: not added, and said so.
                album_shown(message,await ai_review(target,account,draft,quote,edit,
                                                    text(account,'cv_caption_not_added') if caption else ''))
                return True
            portrait=str(asset.id) if asset else None
            brief=await sync_to_async(pending_brief)(account)
            if photo and caption:
                # A photo and its caption are one message: the caption is the description.
                if notice: await target.answer(html.escape(notice))
                waiting=target if edit else await target.answer(text(account,'ai_preparing'))
                album_shown(message,await ai_start(waiting,account,ai.CV,caption,brief,pending.get('question',''),
                                                   pending.get('portrait_asset_id','') if portrait is None else portrait,
                                                   cv_asked(pending),pending.get('copied','')))
            elif brief:
                album_shown(message,await ai_topic_needed(target,account,ai.CV,brief,'',edit,pending.get('question',''),
                                                          notice or text(account,'cv_photo_attached'),portrait,
                                                          pending.get('ask','missing'),pending.get('missing') or ()))
            else: album_shown(message,await ai_prompt(target,account,ai.CV,edit,notice,portrait))
        return True

    async def cv_photo_as(message,account,draft_id,kind):
        """The answer to whether a photo sent on a CV made from photos or screenshots is its portrait or one more page.

        The photo waits in the review's state (cv_file), never in the button. A
        page is read with the CV's other files and the review drawn again; a
        portrait goes on the CV, as a photo sent on any other review does. An
        answer for a review no longer on screen opens the one that is.
        """
        conversation=await sync_to_async(lambda:BotConversation.objects.filter(pk=account.telegram_user_id).first())()
        pending=dict(conversation.prompt or {}) if conversation and conversation.state=='cv_review' else {}
        asset_id=str(pending.pop('photo_asked','') or '')
        caption=str(pending.pop('photo_caption','') or '')
        if not asset_id or str(pending.get('draft_id') or '')!=str(draft_id) or kind not in ('portrait','page'):
            reviewed=await sync_to_async(open_cv_review)(account)
            if reviewed: return await ai_resume(message,account,reviewed)
            return await home(message,account,True,notice=text(account,'stale_button'))
        await sync_to_async(set_prompt)(account,'cv_review',pending)
        await render(message,text(account,'ai_preparing'),[],True)
        notice=''
        try:
            if kind=='page':
                # Read with the CV's other files by the reader: the review waits for it if it has not had its turn.
                made=await sync_to_async(ai.cv_files)(account,draft_id)
                if made:
                    every=[*made['source_ids'],*([asset_id] if asset_id not in made['source_ids'] else [])]
                    status=await sync_to_async(ai.cv_reading)(account,every,made['way'])
                    if status:
                        window={key:pending[key] for key in ('files_at','album') if pending.get(key)}
                        return await cv_wait_start(message,account,{
                            'then':'add','cv_source':made['way'],'draft_id':draft_id,'added':[asset_id],
                            'more':[caption] if caption else [],'source_ids':every,**window},status)
                draft,quote=await sync_to_async(ai.add_sources)(account,draft_id,[asset_id],caption)
                notice=text(account,'cv_files_added')
            else:
                try:
                    await sync_to_async(ai.check_portrait)(account,asset_id)
                    draft,quote=await sync_to_async(ai.add_portrait)(account,draft_id,asset_id)
                    # Words sent with it would skip the name and detail checks: not added, and said so.
                    if caption: notice=text(account,'cv_caption_not_added')
                except DomainError as exc:
                    if exc.code not in ('invalid_image','image_pixel_limit'): raise
                    draft,quote=await sync_to_async(ai.quote)(account,draft_id)
                    notice=text(account,'cv_photo_rejected')
        except DomainError as exc:
            if exc.code=='controls_expired': return await home(message,account,True,notice=text(account,'stale_button'))
            draft,quote=await sync_to_async(ai.quote)(account,draft_id)
            notice=await sync_to_async(cv_refusal_said)(account,exc)
        return await ai_review(message,account,draft,quote,True,notice)

    @dp.message(F.document | F.photo)
    async def receive(message,bot):
        account=await account_for(message.from_user)
        duplicate=await sync_to_async(lambda:BotInputReceipt.objects.filter(account=account,chat_id=message.chat.id,message_id=message.message_id).exists())()
        if duplicate:
            # The same message delivered twice: the screen it led to, drawn again.
            conversation=await sync_to_async(lambda:BotConversation.objects.filter(pk=message.from_user.id).first())()
            # A file that already joined a wait: its waiting message is the screen it led to.
            if cv_waiting(conversation): return
            if conversation and conversation.state in ('cv_choose','cv_source'): return await cv_screen_again(message,account,conversation)
            if cv_question(conversation):
                brief=await sync_to_async(pending_brief)(account)
                if brief: return await ai_topic_needed(message,account,ai.CV,brief,'',False,conversation.prompt.get('question',''),
                                                       ask=conversation.prompt.get('ask','missing'),
                                                       missing=conversation.prompt.get('missing') or ())
                return await ai_prompt(message,account,ai.CV)
            reviewed=await sync_to_async(open_cv_review)(account)
            if reviewed: return await ai_resume(message,account,reviewed)
            return await controls(message,account)
        doc=message.document or message.photo[-1]
        if (doc.file_size or 0)>20*1024*1024: return await safe_error(message,account,DomainError('bot_transport_limit'))
        name=(message.document.file_name or 'document') if message.document else 'photo.jpg'
        ext=name.rsplit('.',1)[-1].lower()
        # A CV made from files takes any file sent on its first screens — one of
        # a kind it does not read is said so there, never downloaded — and, on
        # its review, one more of its files sent moments after the last.
        conversation=await sync_to_async(lambda:BotConversation.objects.filter(pk=message.from_user.id).first())()
        sources=cv_screen_open(conversation) or cv_waiting(conversation) or (bool(conversation) and conversation.state=='cv_review'
            and await sync_to_async(cv_takes_more)(account,ext,message.date.timestamp(),getattr(message,'media_group_id',None)))
        if sources and ext not in CV_FILE_KINDS and await cv_source_file(message,bot,account,name,None): return
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
        if sources and await cv_source_file(message,bot,account,name,stream.getvalue()): return
        # A CV being described takes a file as its photo, and so does a new
        # CV's review on screen; anything else sent then is a file task's.
        conversation=await sync_to_async(lambda:BotConversation.objects.filter(pk=message.from_user.id).first())()
        # A photo sent for a change to a finished CV: a change takes none, and
        # the change question stays open rather than becoming a file task.
        if (ext in ('jpg','jpeg','png') and conversation is not None and conversation.state=='ai_revise'
                and conversation.updated_at>=timezone.now()-QUESTION_LIFETIME
                and await sync_to_async(ai.service_of)(account,(conversation.prompt or {}).get('draft_id',''))==ai.CV):
            target,edit=await album_target(message,bot)
            if target is None: return
            return album_shown(message,await ai_revise_prompt(target,account,conversation.prompt['draft_id'],edit,
                                                              text(account,'cv_revise_photo')))
        cv_photo=cv_question(conversation) or ext in ('jpg','jpeg','png') and bool(await sync_to_async(open_cv_review)(account))
        try:
            if cv_photo and await cv_file(message,bot,account,name,stream.getvalue()): return
            asset=await sync_to_async(upload_file)(account,SimpleUploadedFile(name,stream.getvalue()),'bot')
            # A file sent while an AI tool is waiting belongs to that tool, not
            # to the file-tool draft the upload would otherwise start.
            conversation=await sync_to_async(lambda:BotConversation.objects.get(pk=message.from_user.id))()
            if conversation.state=='ai_input':
                pending=conversation.prompt
                await sync_to_async(attach_input)(account,asset,message.chat.id,message.message_id)
                target,edit=await album_target(message,bot)
                if target is None: return
                brief=await sync_to_async(pending_brief)(account)
                if brief:
                    # The topic question is open, and what was written stays. A
                    # PDF is what the document is about, so its review comes at
                    # once; the AI services read nothing else, so after a photo,
                    # Word or PowerPoint file the question is asked again.
                    feature_id=pending['feature_id']
                    staged=await sync_to_async(lambda:ai.sources(account,draft_for(account).input_ids))()
                    if staged:
                        waiting=target if edit else await target.answer(text(account,'ai_preparing'))
                        return album_shown(message,await ai_start(waiting,account,feature_id,'\n'.join(brief)))
                    from apps.studio.topics import asked_other_service
                    other=await sync_to_async(asked_other_service)('\n'.join(brief),feature_id)
                    return album_shown(message,await ai_topic_needed(target,account,feature_id,brief,other,edit,
                                                                     pending.get('question',''),text(account,'ai_topic_pdf_only')))
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

    # Making a document, a deck or a CV happens in the chat; editing a PDF is a
    # canvas and stays on the web.
    AI_COMMANDS={'create':ai.DOCUMENT,'document':ai.DOCUMENT,'slides':ai.SLIDES,'cv':ai.CV}

    @dp.message(Command('ai','create','document','slides','cv','examples'))
    async def open_ai_mode(message):
        account=await account_for(message.from_user)
        command=message.text.split()[0].split('@')[0][1:]
        if command=='examples': return await ai_examples(message,account)
        feature_id=AI_COMMANDS.get(command)
        if not feature_id: return await home(message,account)
        # A CV is asked first how it is made.
        if feature_id==ai.CV: return await cv_choose(message,account)
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

    async def ai_text(message,account,conversation,value):
        """A description, or the answer to its question, for the AI service the chat is asking about."""
        p=conversation.prompt
        if not value: return await message.answer(text(account,'ai_topic_empty'))
        waiting=await message.answer(text(account,'ai_preparing'))
        return await ai_start(waiting,account,p['feature_id'],value,p.get('brief') or [],p.get('question',''),
                              p.get('portrait_asset_id',''),cv_asked(p),p.get('copied',''))

    async def cv_review_text(message,account,conversation,value):
        """Text sent while a new CV's review is on screen.

        Within moments of the review it is the rest of the description:
        Telegram sends one longer than 4096 characters as two messages, and the
        second arrives on the review the first made. It is added to the CV and
        the review drawn again. For a CV made from files it is the notes sent
        just after the file. Later, it is not read as part of the CV, and the
        customer is shown the review again with the way to change it.
        """
        from apps.studio.models import GenerationDraft
        if not value: return await message.answer(text(account,'ai_topic_empty'))
        draft_id=(conversation.prompt or {}).get('draft_id','')
        try:
            if conversation.updated_at>=timezone.now()-CV_APPEND_WINDOW:
                draft,quote=await sync_to_async(ai.append_description)(account,draft_id,value)
                # For a CV made from files they are more of the notes on top of them.
                way=await sync_to_async(ai.way_of)(account,draft_id)
                notice='cv_notes_added' if way in (ai.LINKEDIN,ai.FILE) else 'cv_description_added'
            else:
                draft=await sync_to_async(lambda:GenerationDraft.objects.filter(pk=draft_id,account=account,
                                                                                expires_at__gt=timezone.now()).first())()
                if draft is None: return await home(message,account,notice=text(account,'fallback'))
                _,quote=await sync_to_async(ai.quote)(account,draft.id)
                notice='cv_text_not_added'
        except DomainError as exc: return await safe_error(message,account,exc)
        return await ai_review(message,account,draft,quote,notice=text(account,notice))

    async def cv_choose_text(message,account,conversation,value):
        """Words sent on the first CV screen, before a way to make it was chosen.

        A description of the customer is the first way: it is written about
        yourself, and goes on as the question about yourself would take it. A
        LinkedIn profile's link is answered with the way to send the profile,
        never opened; a greeting or a word or two, with the screen again.
        """
        from apps.studio.cv.content import says_little
        from apps.studio.cv.sources import linkedin_link_only
        if not value: return await message.answer(text(account,'ai_topic_empty'))
        if linkedin_link_only(value): return await cv_mode_screen(message,account,ai.LINKEDIN,link=True)
        if says_little(value): return await cv_choose(message,account,notice=text(account,'cv_choose_first'))
        portrait=await sync_to_async(pending_portrait)(account)
        await sync_to_async(set_prompt)(account,'ai_input',{'feature_id':ai.CV,**({'portrait_asset_id':portrait} if portrait else {})})
        waiting=await message.answer(text(account,'ai_preparing'))
        return await ai_start(waiting,account,ai.CV,value,(),'',portrait)

    async def cv_source_text(message,account,conversation,value):
        """Words sent on the LinkedIn or old-CV screen.

        Before the file they are notes, kept for it and said so. Asked for what
        the files and the notes did not give (a name, a phone or email, a job
        or school), the answer goes first, before the notes; the same words
        sent again (the same as any kept) are taken as they are by the rule the
        question about yourself takes them by (cv_insists): while the name is
        missing only if they look like one, and while the job or school is
        missing only if the notes and the answer say more than a name, a phone
        and an email. The newest answers are kept, and the first note: a
        chatty customer's facts are never pushed out by older words. A sample of
        the missing screen sent back is answered as one and not kept, as the
        question about yourself answers it. Files are not read again for an
        answer. For the files a CV's description written again kept, they are
        its new notes, and the CV is made again. A LinkedIn profile's link is answered with the way to send
        the profile instead: it is never opened.
        """
        from apps.studio.cv.sources import linkedin_link_only
        p=conversation.prompt or {}
        way=p.get('cv_source') if p.get('cv_source') in (ai.LINKEDIN,ai.FILE) else ai.FILE
        notes=[str(note) for note in p.get('notes') or [] if note]
        files=[str(identifier) for identifier in p.get('source_ids') or []]
        ask=p.get('ask','file')
        if not value: return await message.answer(text(account,'ai_topic_empty'))
        if ask in ('missing','name') and files:
            asked=int(p.get('asked') or 0)
            same=[note for note in notes if compared(note)==compared(value)]
            repeated=bool(same)
            # A sample the screen shows, sent back as it is: said so, nothing kept or counted. Only the
            # sample name sent again at once is the customer's own, as in the question about yourself.
            if not repeated and (sample_held(value) or (compared(value)!=p.get('copied','') and sent_back(value))):
                return await cv_mode_screen(message,account,way,notice=text(account,'cv_example_copied'),notes=notes,files=files,
                                            ask='missing',asked=asked,missing=cv_asked(p),copied=compared(value))
            # The words are the same whichever way they were typed: the first time is kept, as written then.
            if repeated: value,notes=same[0],[note for note in notes if note not in same]
            # The answer goes first and the notes are newest first: the first note written and the
            # newest are kept, CV_BRIEF_PIECES and CV_BRIEF_CHARS with the answer, so no answer is
            # pushed out by older words (cv_build then keeps them all).
            notes=kept_brief(notes[::-1],max(CV_BRIEF_CHARS-len(value),0),CV_BRIEF_PIECES-1)[::-1]
            # Taken as they are by the same rule as the question about yourself (cv_insists): the
            # notes and the answer, each once, are what the customer wrote.
            given=await sync_to_async(cv_insists)(repeated,cv_asked(p),[value,*notes],value)
            waiting=await message.answer(text(account,'ai_preparing'))
            return await cv_build(waiting,account,way,[value,*notes],files,given=given,asked=asked+1)
        if linkedin_link_only(value):
            return await cv_mode_screen(message,account,ai.LINKEDIN,notes=notes,files=files if way==ai.LINKEDIN else [],
                                        ask=ask if files and way==ai.LINKEDIN else 'file',link=True)
        if files and ask=='again':
            waiting=await message.answer(text(account,'ai_preparing'))
            return await cv_build(waiting,account,way,[value],files)
        return await cv_mode_screen(message,account,way,notes=kept_brief([*notes,value],CV_BRIEF_CHARS,CV_BRIEF_PIECES),
                                    files=files,ask=ask)

    @dp.message(F.text)
    async def fallback(message):
        account=await account_for(message.from_user)
        conversation=await sync_to_async(lambda:BotConversation.objects.get(pk=message.from_user.id))()
        if conversation.state and conversation.updated_at<timezone.now()-QUESTION_LIFETIME:
            await sync_to_async(set_prompt)(account)
            return await home(message,account,notice=text(account,'stale_reply'))
        value=(message.text or '').strip()
        # Someone who was writing a support message when tickets were retired.
        if conversation.state in ('support','support_review'): return await contacts_view(message,account)
        if conversation.state in ('cv_review','cv_choose','cv_source','cv_wait') or cv_question(conversation):
            # A CV's messages one at a time, each reading the chat again once it
            # has its turn: the second half of a long description finds the
            # review the first half made, a photo sent with it its CV, and notes
            # sent with a file the CV the file made, or its wait for the reader.
            async with chat_lock(message.chat.id):
                conversation=await sync_to_async(lambda:BotConversation.objects.get(pk=message.from_user.id))()
                if conversation.state=='cv_wait': return await cv_wait_text(message,account,conversation,value)
                if conversation.state=='cv_review': return await cv_review_text(message,account,conversation,value)
                if conversation.state=='cv_choose': return await cv_choose_text(message,account,conversation,value)
                if conversation.state=='cv_source': return await cv_source_text(message,account,conversation,value)
                if cv_question(conversation): return await ai_text(message,account,conversation,value)
        if conversation.state=='ai_input': return await ai_text(message,account,conversation,value)
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
    # The bot's loop looks at the chats waiting for the reader through the
    # dispatcher that answers them (cv_wait_loop), with the same screens.
    dp.cv_waits=cv_waits
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
    loops=[]
    try:
        await install_commands(bot)
        dispatcher=build_dispatcher()
        loops=[asyncio.create_task(delivery_loop(bot)),asyncio.create_task(cv_wait_loop(bot,dispatcher))]
        await dispatcher.start_polling(bot)
    finally:
        for task in loops:
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
        await bot.session.close()
