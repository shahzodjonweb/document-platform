"""Independent durable result delivery. Retrying never reprocesses or recharges a job."""
import asyncio
import html
import logging
import re
import secrets
from datetime import timedelta
from urllib.parse import urlsplit, urlunsplit
from asgiref.sync import sync_to_async
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError,TelegramRetryAfter
from aiogram.types import BufferedInputFile,InlineKeyboardButton,InlineKeyboardMarkup,WebAppInfo
from cryptography.fernet import InvalidToken
from django.db import close_old_connections, connection, transaction
from django.utils import timezone
from apps.core.errors import DomainError
from apps.core.models import BotCallback
from apps.core import storage
from apps.commerce.models import BotDelivery
from apps.commerce.providers import telegram_config
from .ux_copy import EDIT_BUTTON_COPY, UX


RESULT_COPY = {
    'en': {
        'ready': '✅ Done!',
        'large': '✅ Done! The file is too large for Telegram. Download it from Recent tasks on the web within 24 hours of processing.',
        'open': '🌐 Open web app',
        'share': '✅ 📎 Made with {bot}',
    },
    'uz': {
        'ready': '✅ Tayyor!',
        'large': '✅ Tayyor! Fayl Telegram uchun juda katta. Qayta ishlanganidan keyin 24 soat ichida veb ilovadagi So‘nggi vazifalardan yuklab oling.',
        'open': '🌐 Veb ilova',
        'share': '✅ 📎 {bot} yordamida tayyorlandi',
    },
    'ru': {
        'ready': '✅ Готово!',
        'large': '✅ Готово! Файл слишком большой для Telegram. Скачайте его из последних задач на сайте в течение 24 часов после обработки.',
        'open': '🌐 Открыть сайт',
        'share': '✅ 📎 Сделано в {bot}',
    },
}


def share_link(account, username):
    """(username, link) to the bot for whoever this file is forwarded to, or ('', '').

    It carries the owner's referral code, so someone who starts the bot from a
    forwarded file is counted as their invitation. Nothing here may stop a
    delivery: without a configured username, or on any failure, the caption
    simply has no link.
    """
    username = (username or '').strip().lstrip('@')
    if not re.fullmatch(r'[A-Za-z0-9_]{5,32}', username):
        return '', ''
    link = f'https://t.me/{username}'
    try:
        from apps.commerce.services import referral_code
        code = referral_code(account).code
        if re.fullmatch(r'[A-Za-z0-9_-]{1,60}', code):
            link += f'?start=ref_{code}'
    except Exception:
        pass
    return username, link


def ready_caption(copy, username, link):
    """One short line under the file: who made it, linking to the bot.

    Without a bot to link to, just "Done!".
    """
    if not link:
        return html.escape(copy['ready'])
    mention = f'<a href="{html.escape(link)}">@{html.escape(username)}</a>'
    return html.escape(copy['share']).replace('{bot}', mention)


# Telegram's limit on a file's caption, in characters.
CAPTION_LIMIT = 1024


def category_notices(job, locale):
    """What a category document's file says under it, in the customer's language: [] for any other file.

    The category's own words (its entry's `bot.notices`), never a value from
    the document: `finished` always, what to do with the file; `blanks` when
    code took out or blanked a fact the customer did not give (the job warning
    facts_blanked), in the shared wording when the category has none;
    `shorter` when a paper whose pages are a ceiling (`length.target`) came
    out with fewer pages than it was quoted, so a one-page report asked for
    in four is not taken for a failure, also in the shared wording when the
    category has none; `draft` when a new deck has slides written from its
    topic alone, as a draft to check, because no file was sent. Never raises:
    a notice is never worth the file.
    """
    category = (job.parameters or {}).get('category')
    if not category:
        return []
    try:
        from apps.studio import categories
        from apps.core.serializers import warning_codes
        entry = categories.get(category)
        if entry is None:
            return []
        said = entry.raw['bot'].get('notices') or {}

        def words(notice):
            return notice.get(locale) or notice['en']
        lines = [words(said['finished'])] if said.get('finished') else []
        if 'facts_blanked' in warning_codes(job):
            lines.append(words(said['blanks']) if said.get('blanks') else UX[locale]['facts_blanked'])
    except Exception:
        _unread_notices(job)
        return []
    # The pages quoted are read from the draft and those made from the file:
    # a failure there loses this notice alone.
    try:
        short = _shorter(job, entry)
        if short:
            notice = words(said['shorter']) if said.get('shorter') else UX[locale]['paper_shorter']
            lines.append(notice.replace('{asked}', str(short[0])).replace('{pages}', str(short[1])))
    except Exception:
        _unread_notices(job)
    # Read from the draft, which may have changed shape since: a failure there
    # loses the draft notice alone, never the ones already worked out.
    try:
        if said.get('draft') and _drafted(job, entry):
            lines.append(words(said['draft']))
    except Exception:
        _unread_notices(job)
    return lines


def _unread_notices(job):
    import logging
    logging.getLogger(__name__).exception('The notices of job %s could not be read', job.id)


def _shorter(job, entry):
    """(pages quoted, pages made) when a ceiling paper's file has fewer pages than its draft was quoted; else None.

    The quote is the draft's stored length (categories.skeleton.pages, the one
    reader of the number, which the review showed and the quote capped), the
    made pages are the delivered file's. A paper whose number is a count is
    filled to it, and a deck is always its count, so neither is ever shorter.
    A file whose page count is unknown (0) says nothing.
    """
    from apps.studio.categories import skeleton
    from apps.studio.domain import unpack
    from apps.studio.models import GenerationDraft
    if entry.service != 'pdf' or entry.length['target'] != 'ceiling':
        return None
    made = [artifact.file.page_count for artifact in job.artifacts.select_related('file')
            if artifact.role == 'user_document']
    draft = GenerationDraft.objects.filter(account=job.account, id=(job.parameters or {}).get('generation_draft_id')).first()
    if not made or draft is None:
        return None
    asked, pages = skeleton.pages(unpack(draft.encrypted_data)), max(made)
    return (asked, pages) if asked and 0 < pages < asked else None


def _drafted(job, entry):
    """Whether a new category deck has a slide its entry writes from the topic alone (source `draft`) and was given no file."""
    from apps.studio.categories import skeleton
    from apps.studio.domain import unpack
    from apps.studio.models import GenerationDraft
    if entry.service != 'slides':
        return False
    draft = GenerationDraft.objects.filter(account=job.account, id=(job.parameters or {}).get('generation_draft_id')).first()
    if draft is None:
        return False
    data = unpack(draft.encrypted_data)
    if data.get('revision') or data.get('source_ids'):
        return False
    uses = skeleton.parts(entry, len(data['content']['sections']), skeleton.cues_of(data))
    return any(use.part.get('source') == 'draft' for use in uses)


def visible_length(caption):
    """How long Telegram counts an HTML caption: its text without tags or entities, in UTF-16 units."""
    return len(html.unescape(re.sub(r'<[^>]*>', '', caption)).encode('utf-16-le')) // 2


def with_notices(caption, notices):
    """`caption` and the notices under it, each a paragraph, as many as fit Telegram's caption."""
    for notice in notices:
        more = f'{caption}\n\n{html.escape(notice)}'
        if visible_length(more) > CAPTION_LIMIT:
            break
        caption = more
    return caption


def enqueue(artifact,key):
    if artifact.account.telegram_user_id is None: raise DomainError('telegram_link_required',409)
    delivery,_=BotDelivery.objects.get_or_create(account=artifact.account,artifact=artifact,idempotency_key=key)
    return delivery


# Sends tried before a file is given up, whatever stopped them. attempt gives up on its
# own after five refusals; this ends a file whose send fails before attempt's guard,
# which a look would otherwise take again every two minutes for good.
MAX_ATTEMPTS = 10


@transaction.atomic
def claim(delivery_id):
    delivery=BotDelivery.objects.select_for_update().select_related('account','artifact__file').get(pk=delivery_id)
    now=timezone.now()
    if delivery.status in ('delivered','failed','blocked'): return None
    if delivery.status=='sending' and delivery.lease_until and delivery.lease_until>now: return None
    if delivery.next_attempt_at>now: return None
    if delivery.attempts>=MAX_ATTEMPTS:
        delivery.status,delivery.error_code,delivery.lease_until='failed','telegram_delivery_attempts_exhausted',None
        delivery.save(update_fields=['status','error_code','lease_until'])
        return None
    delivery.status='sending';delivery.lease_until=now+timedelta(seconds=120);delivery.attempts+=1
    delivery.save(update_fields=['status','lease_until','attempts'])
    return delivery


def finish(delivery_id,*,status,message_id=None,error='',delay=0):
    values={'status':status,'message_id':message_id,'error_code':error,'lease_until':None,'next_attempt_at':timezone.now()+timedelta(seconds=delay)}
    if status=='delivered': values['delivered_at']=timezone.now()
    BotDelivery.objects.filter(pk=delivery_id,status='sending').update(**values)


def revisable_draft(delivery):
    """The draft behind a generated document, when there is one to change."""
    from apps.studio.domain import GENERATION_IDS, RENDER_IDS
    job = delivery.artifact.job
    if job.feature_id not in GENERATION_IDS | RENDER_IDS:
        return ''
    identifier = (job.parameters or {}).get('generation_draft_id', '')
    if not identifier:
        return ''
    from apps.studio.models import GenerationDraft
    exists = GenerationDraft.objects.filter(account=delivery.account, id=identifier,
                                            expires_at__gt=timezone.now()).exists()
    return str(identifier) if exists else ''


def app_url(webapp_url, locale, route=''):
    """A page of the web app, in the customer's language."""
    url = urlsplit(webapp_url)
    parts = url.path.rstrip('/').split('/')
    if len(parts) > 1 and parts[1] in ('en', 'uz', 'ru'):
        parts[1] = locale
    return urlunsplit((url.scheme, url.netloc, '/'.join(parts) + ('/' + route if route else ''), '', ''))


def app_button(label, url):
    """Opens a page as a Mini App where Telegram allows one (https), else as a link."""
    if url.startswith('https://'):
        return InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url))
    return InlineKeyboardButton(text=label, url=url)


def editable_pdf(asset):
    """A file the editor would open now: the same refusals as studio.views.editors."""
    return (asset.mime_type == 'application/pdf' and not asset.metadata.get('encrypted')
            and asset.state == 'ready' and asset.expires_at > timezone.now())


def editable_deck(account, identifier):
    """A deck the editor would draw now: the same refusal as render_export, as a live
    draft can have no pins. One that cannot be read is no reason to hold the file back."""
    from apps.studio.domain import unpack
    from apps.studio.models import GenerationDraft
    from apps.studio.render_export import _editable
    draft = GenerationDraft.objects.filter(account=account, id=identifier, expires_at__gt=timezone.now()).first()
    if draft is None:
        return False
    try:
        _editable(draft, unpack(draft.encrypted_data))
    except (DomainError, InvalidToken, ValueError):
        return False
    return True


def deck_route(account, draft, flags):
    """Where ✏️ Edit takes a deck's file: back to its slides, while the deck editor is on and the deck is drawn."""
    return f'editor/deck/{draft}' if flags['deck_editor'] and draft and editable_deck(account, draft) else ''


def edit_route(delivery, flags):
    """Where ✏️ Edit takes this result, or '' when there is nothing to open.

    An edited PDF goes back to the upload its marks are on, so it comes up with
    them; all a deck makes, in either format, goes back to its slides.
    """
    from apps.studio.domain import RENDER_IDS, SLIDES
    from apps.studio.models import EditorDocument
    asset = delivery.artifact.file
    document = asset.metadata.get('editor_document_id')
    if document:
        source = EditorDocument.objects.select_related('file').filter(account=delivery.account, id=document).first()
        return f'editor?file_id={source.file_id}' if source and editable_pdf(source.file) else ''
    if delivery.artifact.job.feature_id in RENDER_IDS | {SLIDES}:
        return deck_route(delivery.account, asset.metadata.get('generation_draft_id'), flags)
    return f'editor?file_id={asset.id}' if editable_pdf(asset) else ''


def edit_url(account, route):
    """The page ✏️ Edit opens for `route`, or '' when no button is drawn: Telegram refuses
    a message whose button has no address, and the file matters more."""
    locale = account.locale if account.locale in UX else 'en'
    url = app_url(telegram_config()['webapp_url'], locale, route) if route else ''
    return url if url.startswith(('https://', 'http://')) else ''


def deck_change_label(account, draft):
    """The UX key of the button under a deck's file that changes it, as result_controls draws them:
    ✏️ Edit where it is drawn, else the AI change, which every deck made from a draft has."""
    from operations.integrations import editor_flags
    flags = editor_flags()
    if flags['edit_buttons'] and edit_url(account, deck_route(account, draft, flags)):
        return 'edit'
    return EDIT_BUTTON_COPY['ai_revise'] if flags['edit_buttons'] else 'ai_revise'


@transaction.atomic
def result_controls(delivery):
    """Stable owner-bound navigation; retries reuse tokens instead of adding rows."""
    BotDelivery.objects.select_for_update().get(pk=delivery.pk)
    locale = delivery.account.locale if delivery.account.locale in UX else 'en'
    from operations.integrations import editor_flags
    flags = editor_flags()
    rows = []
    payload = {'delivery_id': str(delivery.id)}
    # A link holds no token, so a retry draws the same button.
    url = edit_url(delivery.account, edit_route(delivery, flags) if flags['edit_buttons'] else '')
    if url:
        rows.append([app_button(UX[locale]['edit'], url)])
    # A generated document can be changed by asking; a converted file cannot.
    revise = revisable_draft(delivery)
    if revise:
        from apps.studio.keeping import button_until
        controls = BotCallback.objects.filter(account=delivery.account, action='ai_revise', payload={'draft_id': revise})
        # One button for a draft however often it is sent: it lasts as long as the draft, kept for good once a file
        # is made from it (apps/studio/keeping.py), and never less than the newest file.
        until = button_until(delivery.account, revise, delivery.artifact.file.expires_at)
        controls.filter(expires_at__lt=until).update(expires_at=until)
        control = controls.first()
        if control is None:
            control = BotCallback.objects.create(
                token=secrets.token_urlsafe(12), account=delivery.account, action='ai_revise',
                payload={'draft_id': revise}, expires_at=until,
            )
        label = EDIT_BUTTON_COPY['ai_revise'] if flags['edit_buttons'] else 'ai_revise'
        rows.append([InlineKeyboardButton(text=UX[locale][label], callback_data=control.token)])
    for action, label in (('home', 'home'), ('recent', 'recent'), ('new', 'new_task')):
        control = BotCallback.objects.filter(account=delivery.account, action=action, payload=payload).first()
        if control is None:
            control = BotCallback.objects.create(
                token=secrets.token_urlsafe(12), account=delivery.account, action=action,
                payload=payload, expires_at=delivery.artifact.file.expires_at,
            )
        rows.append([InlineKeyboardButton(text=UX[locale][label], callback_data=control.token)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def attempt(delivery_id,bot):
    delivery=await sync_to_async(claim)(delivery_id)
    if not delivery: return
    if delivery.account.telegram_user_id is None:
        return await sync_to_async(finish)(delivery.id,status='blocked',error='telegram_link_required')
    from aiogram.client.session.aiohttp import AiohttpSession
    if delivery.account.is_test and isinstance(getattr(bot,'session',None),AiohttpSession):
        return await sync_to_async(finish)(delivery.id,status='blocked',error='test_account_delivery')
    asset=delivery.artifact.file
    from apps.studio.keeping import held_past_its_day
    # A result kept only as a document's source is held for its changes, not sent again after its day (keeping.py).
    if asset.state!='ready' or asset.expires_at<=timezone.now() or held_past_its_day(asset):
        return await sync_to_async(finish)(delivery.id,status='failed',error='file_expired')
    try:
        locale = delivery.account.locale if delivery.account.locale in RESULT_COPY else 'en'
        copy = RESULT_COPY[locale]
        controls = await sync_to_async(result_controls)(delivery)
        # A category's document says under it what to do with it (category_notices); any other file nothing more.
        notices = (await sync_to_async(lambda: category_notices(delivery.artifact.job, locale))()
                   if delivery.artifact.role == 'user_document' else [])
        if asset.size_bytes>50*1024*1024:
            cfg=await sync_to_async(telegram_config)()
            controls.inline_keyboard.insert(0, [InlineKeyboardButton(text=copy['open'], url=cfg['webapp_url'])])
            large='\n\n'.join([copy['large'],*notices])
            response=await bot.send_message(delivery.account.telegram_user_id,large,reply_markup=controls)
        else:
            payload=await sync_to_async(lambda:storage.read_bytes(asset.object_key))()
            # The buttons belong to the owner; whoever the file is forwarded to
            # finds the way to the bot in the caption itself.
            cfg=await sync_to_async(telegram_config)()
            username,link=await sync_to_async(share_link)(delivery.account,cfg.get('username',''))
            caption=with_notices(ready_caption(copy,username,link),notices)
            response=await bot.send_document(delivery.account.telegram_user_id,BufferedInputFile(payload,filename=asset.name),caption=caption,parse_mode='HTML',reply_markup=controls)
        await sync_to_async(finish)(delivery.id,status='delivered',message_id=response.message_id)
    except TelegramRetryAfter as exc:
        await sync_to_async(finish)(delivery.id,status='retrying',error='telegram_rate_limited',delay=min(3600,max(1,exc.retry_after)))
    except TelegramForbiddenError:
        await sync_to_async(finish)(delivery.id,status='blocked',error='telegram_blocked')
    except Exception:
        await sync_to_async(finish)(delivery.id,status='failed' if delivery.attempts>=5 else 'retrying',error='telegram_delivery_failed',delay=min(3600,2**delivery.attempts*10))


logger = logging.getLogger(__name__)


def _reset_connection():
    """After an error, drop a database connection that is broken or too old, so the next query opens a new one.

    The bot runs every query on one thread (sync_to_async) and nothing else ever
    recycles that thread's connection: once Postgres dropped it, every query failed
    until a restart. Never inside a transaction, a test's or a caller's: closing
    the connection would end it.
    """
    if not connection.in_atomic_block:
        close_old_connections()


# The kinds of step failing now. While Postgres is down every look fails every step:
# the first failure of a run is logged with its traceback, which names the cause,
# and the next ones in a line each, so the traceback is not rotated out of the log.
_failing = set()


async def _step(kind, run, name=''):
    """One step of a look: an error is logged and the look goes on, so it never holds back the steps after it."""
    try:
        result = await run()
    except Exception as exc:
        if kind in _failing:
            logger.error('%s could not be sent again (%s)', name or kind, type(exc).__name__)
        else:
            _failing.add(kind)
            logger.exception('%s could not be sent', name or kind)
        await sync_to_async(_reset_connection)()
        return None
    _failing.discard(kind)
    return result


async def drain(bot):
    """One look at everything the bot sends on its own: result files first, then the notices.

    Each file and each kind of notice is a step of its own (_step): a dropped
    connection or a row that cannot be read loses that step on this look, never the
    files and notices after it, and the next look tries it again.
    """
    ids=await _step('Result files',sync_to_async(lambda:list(BotDelivery.objects.filter(account__is_test=False,status__in=('pending','retrying','sending'),next_attempt_at__lte=timezone.now()).order_by('created_at').values_list('id',flat=True)[:20]))) or []
    for identifier in ids: await _step('A result file',lambda identifier=identifier:attempt(identifier,bot),f'Result file {identifier}')
    from .notifications import drain_notices
    from .payment_notices import drain as drain_payment_notices
    from .referral_notices import drain as drain_referral_notices
    from .staff_alerts import drain as drain_staff_alerts
    for what,run in (('Job notices',drain_notices),('Payment notices',drain_payment_notices),
                     ('Referral notices',drain_referral_notices),('Staff alerts',drain_staff_alerts)):
        await _step(what,lambda run=run:run(bot))


async def delivery_loop(bot):
    """The polling bot's sender of result files and notices, for as long as the bot runs.

    Nothing that goes wrong on one look may end it. It is an asyncio task nobody
    awaits before shutdown, so an error that escaped it once stopped every later
    file and notice, without a line in the log, while the bot still answered taps.
    """
    from apps.core import wakeups
    while True:
        try:
            await drain(bot)
        except Exception:
            logger.exception('Deliveries could not be sent')
            await sync_to_async(_reset_connection)()
        # Woken the moment a job settles with something to send; a look every 2 s regardless.
        await wakeups.wait_async([wakeups.DELIVERIES], 2)


async def standalone():
    cfg=await sync_to_async(telegram_config)()
    if not cfg.get('token'): raise RuntimeError('Configure the Telegram bot token in the admin panel.')
    bot=Bot(cfg['token'])
    try:
        await drain(bot)
        from .posts import standalone_drain
        await standalone_drain(bot)
    finally: await bot.session.close()
