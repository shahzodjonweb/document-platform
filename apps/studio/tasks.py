"""Short free pieces of editor work, done one at a time by `runeditor`, the accounts taking turns.

A customer waiting on a slide should not wait behind a paid AI run, and the API
parses and draws nothing, so this work has a queue and a container of its own
(ADR 0002). A row is an EditorTask: taken under a lease with SKIP LOCKED and a
compare-and-set as cv/reads.py takes a read, and in the same fair order. A
runner that dies, or a LibreOffice that crashes or hangs on our own deck, gives
the task back to be taken again (`*_interrupted`), MAX_ATTEMPTS times in all;
nothing else is tried twice, least of all a customer's file that stalled pdfium,
which would only do so again. Only one of a draft's renders waits at a time: a
newer payload replaces the queued one, and it keeps its place. An account has at
most MAX_QUEUED waiting and so many seconds a day of each kind (editor_config),
past which it is told `lane_busy`; every attempt counts, up to its lease, however
long the lane was down after it. Payloads and results are the customer's, encrypted
as drafts are, and go an hour after the task finishes; the row stays a little
longer to count those seconds. In tests and local development
(settings.LOCAL_SYNC_JOBS) a task runs as it is queued, so nothing waits.

Kinds that run today: `render_deck`, `preview` and `photos` (deck_photos.py: a
deck's pictures, which never replace one another while waiting: one at a time
per draft). `inspect` and `text_check` are refused, not stubbed.

A slide's picture is keyed by what is on the slide: its XML and its pictures'
bytes, the deck's theme, the renderer's version and the language. Draft fields
would not do as a key: a slide's number, its place among the others ('03 / 12')
and the customer's brand name are drawn on it without being in its section, and
would leave the wrong number on a picture. So a slide changes its key exactly
when its picture changes: an edit to one of 60 reconverts one. A slide added at
the end also reconverts every slide that says how many there are, which is most
of them (87% of 12 slides across 15 designs), since they now say something else.
That costs little: LibreOffice takes 1.0 s for 12 slides against 0.9 s for one.

What LibreOffice costs, CI run 41329155494 (LibreOffice 7.4.7, 1.5 CPUs, 3 GiB),
seconds a conversion and peak MB:

    1 slide     cold 1.04 (220)  warm 0.91 (219)  held 0.15 (173)
    12 of text  cold 1.09 (219)  warm 0.95-1.01   held 0.11-0.21 (164)
    60 photos   cold 5.07 (475)  warm 4.28-4.30   held 3.94-4.12 (503, 377 at rest)

So each conversion is a process of its own from a warm profile, under the
child's limits and environment, gone when it ends. An office left running would
save 0.8 s on a small deck, nothing on a large one, and hold 377 MB and one
profile and font cache for as long as it lives. `convert_deck` is the one place
that would change for it, should T4 (2 s p50) be missed on real decks.
"""
import hashlib
import json
import logging
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime, time, timedelta
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Max, OuterRef, Q, Subquery, Sum
from django.utils import timezone
from lxml import etree

from apps.core import storage
from apps.core.allowance import WEEK_ZONE
from apps.core.errors import DomainError
from apps.core.models import Account, FileAsset
from apps.core.services import storage_path
from processors import ProcessorError
from processors.sandbox import execute_sandbox

from .cv.reads import fair_order
from .domain import EXPORT, pack, require, unpack
from .models import EditorTask, GenerationDraft, SlideRender

logger = logging.getLogger(__name__)

QUEUED, RUNNING, DONE, FAILED = 'queued', 'running', 'done', 'failed'
WAITING = (QUEUED, RUNNING)
RENDER, PREVIEW, PHOTOS = 'render_deck', 'preview', 'photos'
# The queued tasks the order is worked out over, oldest first, and how many of them a runner tries to lock at once.
WINDOW = 500
CLAIM_BATCH = 20
# One deck's drawing, its LibreOffice and pdfium children and storing the files, with room. A runner
# that outlives this does no harm: pictures go by key, and only the runner holding the task can finish it.
LEASE_SECONDS = 180
# A task the lane lost is the lane's fault the first time; one that takes it down every time is failed.
MAX_ATTEMPTS = 3
MAX_QUEUED = 3
# A task's payload and result, and so a slide's picture past the last result that can name it.
KEPT = timedelta(hours=1)
# The row itself, for the seconds it took: today's budget and the admin's page.
ROW_KEPT = timedelta(days=2)
# What the child says of a LibreOffice or pdfium that crashed or hung on a deck of ours. Any other refusal, and any
# of a customer's file, is the same again if tried again.
CRASHES = {'processor_timeout', 'processor_failed', 'processor_report_limit', 'conversion_failed'}
INTERRUPTED = {RENDER: 'render_deck_interrupted', PREVIEW: 'preview_interrupted'}
# A preview that failed is said to whoever asks again this soon, instead of being tried again.
PREVIEW_FAILED_SECONDS = 60
# Tasks of a draft or an account looked through for the one asked about, newest first.
HISTORY = 20
# LibreOffice's allowance for a render: 20 times what 12 slides took above, and about 7 times 60 photo slides on the
# lane's one CPU, each slide over 12 adding about 0.07 s. A hang costs the customer this long, and nobody else more.
OFFICE_SECONDS, OFFICE_SECONDS_PER_SLIDE, OFFICE_SLIDES = 20, 0.5, 12
# One page of a customer's file, and again to unlock it first: pdfium draws a slide in about 0.1 s (below). A page that takes
# longer is not worth one runner's time, which every customer's slides are waiting on, and the API's own 90 s stays as it was.
PREVIEW_SECONDS = 20
# pdfium's: on an M2 Pro 0.02 s for a slide of text and 0.11 s to write a full-bleed photo as a PNG, about 1.6 MB of it.
IMAGE_SECONDS, IMAGE_SECONDS_PER_SLIDE = 15, 0.5
PNG_DPI = 96  # a slide is 13.333 in wide: 1280 px
PNG_SIZE, THUMB_SIZE = (1280, 720), (96, 54)
PNG_BYTES = 20 * 1024 * 1024


# --- Budgets ---------------------------------------------------------------------------------

def _day_start(now):
    """Today's start, in the zone weeks are counted in: a day that moved with the account could be started again at will."""
    return datetime.combine(now.astimezone(WEEK_ZONE).date(), time.min, tzinfo=WEEK_ZONE)


def seconds_today(account, now=None):
    """{kind: seconds} of the lane this account has used today, the attempts of tasks given back too and the one in progress aside."""
    now = now or timezone.now()
    spans = EditorTask.objects.filter(account=account, started_at__gte=_day_start(now), spent_seconds__gt=0)
    return {row['kind']: row['spent'] for row in spans.values('kind').annotate(spent=Sum('spent_seconds'))}


def budget_of(account, kind, config=None):
    """Seconds a day of `kind` this account has: the plan's multiple of Free's. None for a kind with no budget."""
    if config is None:
        from operations.integrations import editor_config
        config = editor_config()
    return None if kind not in config else config[kind] * (1 if account.plan == 'free' else config['paid_multiplier'])


def _within_budget(account, kind):
    budget = budget_of(account, kind)
    if budget is not None and seconds_today(account).get(kind, 0) >= budget:
        raise DomainError('lane_busy', 429, retryable=True)


def lane_rows(account):
    """What the admin's user page shows: today's seconds of each kind against its budget."""
    from operations.integrations import EDITOR_BUDGETS, editor_config
    config, spent = editor_config(), seconds_today(account)
    return [{'kind': kind, 'seconds': round(spent.get(kind, 0)), 'budget': budget_of(account, kind, config)}
            for kind in EDITOR_BUDGETS if kind != 'paid_multiplier']


# --- Queueing --------------------------------------------------------------------------------

def _replace_queued(draft, kind, payload):
    """The draft's queued task of this kind, now carrying `payload` and in the place it had; None with none queued."""
    row = EditorTask.objects.filter(draft=draft, kind=kind, status=QUEUED).first()
    if row is None:
        return None
    packed = pack(payload)
    return row if EditorTask.objects.filter(pk=row.pk, status=QUEUED).update(encrypted_payload=packed, attempts=0) else None


def enqueue(account, kind, payload, *, draft=None, document=None, action='', check=None):
    """A task queued for the account, or the draft's queued render given this newer payload.

    `lane_busy` past the day's budget of its kind, or with MAX_QUEUED waiting;
    a replaced task takes no new place. `check()` runs under the account's lock,
    to refuse what counting first and queueing after would let through twice.
    `action` is what a picture task does, which its day's caps count. With
    settings.LOCAL_SYNC_JOBS it runs here and now.
    """
    if kind not in HANDLERS:
        raise DomainError('editor_task_unsupported', 409)
    _within_budget(account, kind)
    replaces = draft is not None and kind != PHOTOS
    with transaction.atomic():
        # The account's row held: two requests at once cannot both take the last place.
        Account.objects.select_for_update().filter(pk=account.pk).first()
        if check is not None:
            check()
        row = _replace_queued(draft, kind, payload) if replaces else None
        if row is None:
            if EditorTask.objects.filter(account=account, status=QUEUED).count() >= MAX_QUEUED:
                raise DomainError('lane_busy', 429, retryable=True)
            try:
                with transaction.atomic():
                    row = EditorTask.objects.create(account=account, kind=kind, draft=draft, document=document, action=action, encrypted_payload=pack(payload))
            except IntegrityError:
                # A render given back to the queue at this moment: the newer payload is the one to do.
                row = _replace_queued(draft, kind, payload) if replaces else None
                if row is None:
                    raise DomainError('lane_busy', 429, retryable=True) from None
    if settings.LOCAL_SYNC_JOBS:
        for _ in range(MAX_ATTEMPTS):
            taken = take(row)
            if taken is None:
                break
            perform(taken)
        row.refresh_from_db()
    return row


# --- The queue, as cv/reads.py keeps its own -------------------------------------------------

def queue(now=None):
    """The queued tasks in the order they will be run."""
    now = now or timezone.now()
    rows = list(EditorTask.objects.filter(status=QUEUED).only('id', 'account_id', 'created_at').order_by('created_at', 'id')[:WINDOW])
    owners = {row.account_id for row in rows}
    served = dict(EditorTask.objects.filter(account_id__in=owners, started_at__isnull=False).values('account_id')
                  .annotate(last=Max('started_at')).values_list('account_id', 'last'))
    return fair_order(rows, served, now)


def take(row, now=None):
    """`row` taken to run, if it is still queued: the row as taken, or None when another runner has it."""
    now = now or timezone.now()
    taken = EditorTask.objects.filter(pk=row.pk, status=QUEUED).update(
        status=RUNNING, started_at=now, finished_at=None, lease_expires_at=now + timedelta(seconds=LEASE_SECONDS), attempts=F('attempts') + 1)
    return EditorTask.objects.select_related('account').get(pk=row.pk) if taken else None


def claim(now=None):
    """The next task in turn, taken under a lease; None when nothing is queued. SKIP LOCKED: a second runner passes over what the first holds."""
    order = queue(now)
    for start in range(0, len(order), CLAIM_BATCH):
        batch = order[start:start + CLAIM_BATCH]
        with transaction.atomic():
            free = set(EditorTask.objects.select_for_update(skip_locked=True)
                       .filter(pk__in=[row.pk for row in batch], status=QUEUED).values_list('pk', flat=True))
            for row in batch:
                if row.pk in free:
                    taken = take(row, now)
                    if taken is not None:
                        return taken
    return None


def _charged(row):
    """What the attempt taken as `row` adds to the task's seconds: its lease at most, so a lane that was down is not the customer's to pay for."""
    return F('spent_seconds') + min(LEASE_SECONDS, max(0.0, (timezone.now() - row.started_at).total_seconds()))


def finish(row, status, *, result=None, error=''):
    """The task taken as `row` finished. Whether it was kept: not when it was given up meanwhile, or its draft deleted."""
    values = {'status': status, 'error': error[:40], 'finished_at': timezone.now(), 'lease_expires_at': None, 'spent_seconds': _charged(row)}
    if result is not None:
        values['encrypted_result'] = pack(result)
    return bool(EditorTask.objects.filter(pk=row.pk, status=RUNNING, attempts=row.attempts).update(**values))


def _give_back(row, code):
    """A task the lane lost, queued again: failed with `code` after MAX_ATTEMPTS, or when a newer one of its draft's is already waiting.

    A picture task is never run twice: a runner slow past its lease may still be
    spending the provider calls a second would spend again (deck_photos._write
    keeps the slow one from landing).
    """
    if row.attempts < MAX_ATTEMPTS and row.kind != PHOTOS:
        try:
            with transaction.atomic():
                return bool(EditorTask.objects.filter(pk=row.pk, status=RUNNING, attempts=row.attempts).update(status=QUEUED, lease_expires_at=None, spent_seconds=_charged(row)))
        except IntegrityError:
            pass
    return finish(row, FAILED, error=code)


def sweep(now=None):
    """Tasks whose runner stopped mid-task, their lease lapsed: queued again, or failed after MAX_ATTEMPTS. How many."""
    now = now or timezone.now()
    lapsed = list(EditorTask.objects.filter(status=RUNNING, lease_expires_at__lte=now))
    for row in lapsed:
        _give_back(row, INTERRUPTED.get(row.kind, 'editor_task_failed'))
    return len(lapsed)


def perform(row):
    """The task taken as `row` run and finished. A crash is given back; a refusal is the task's answer. Nothing of it is logged."""
    handler = HANDLERS.get(row.kind)
    if handler is None:
        return finish(row, FAILED, error='editor_task_unsupported')
    try:
        return finish(row, DONE, result=handler(row))
    except (DomainError, ProcessorError) as exc:
        code = exc.code
    except Exception as exc:
        # The type alone: a message could quote the deck.
        logger.error('An editor task (%s) failed: %s', row.kind, type(exc).__name__)
        code = 'editor_task_failed'
    return _give_back(row, INTERRUPTED[row.kind]) if row.kind == RENDER and code in CRASHES else finish(row, FAILED, error=code)


def next_task(now=None):
    """One turn of the runner: tasks left by a stopped runner queued again, and the next in turn run. Whether one was."""
    sweep(now)
    row = claim(now)
    if row is None:
        return False
    perform(row)
    return True


def prune(now=None):
    """What the cleanup service does: finished tasks lose their payload and result after KEPT, and their row after ROW_KEPT; slide pictures no render has used for KEPT go.

    A draft's last render keeps its pictures however long ago it was: they are
    what it shows, and what the next render reuses. The rest go, with nothing
    else needing to happen on the draft: a customer who took a word off a slide
    and stopped editing is not left with it on the volume until the draft's clock runs out.
    """
    now = now or timezone.now()
    EditorTask.objects.filter(finished_at__lte=now - KEPT).exclude(encrypted_payload__isnull=True, encrypted_result__isnull=True).update(encrypted_payload=None, encrypted_result=None)
    # A task nobody took, with the lane stopped, goes too: whoever wanted it has long gone.
    EditorTask.objects.filter(Q(finished_at__lte=now - ROW_KEPT) | Q(status=QUEUED, created_at__lte=now - ROW_KEPT)).delete()
    last = SlideRender.objects.filter(draft=OuterRef('draft')).order_by('-used_at').values('used_at')[:1]
    for old in SlideRender.objects.filter(used_at__lte=now - KEPT).annotate(last=Subquery(last)).filter(used_at__lt=F('last')):
        _drop(old)


# --- LibreOffice -----------------------------------------------------------------------------

_office = {'home': None}


def _office_home():
    """This process's warm profile and font cache: this lane's only, for our decks in our faces, in the container's own /tmp."""
    if _office['home'] is None or not Path(_office['home']).is_dir():
        _office['home'] = tempfile.mkdtemp(prefix='editor-office-')
    return _office['home']


def forget_office():
    """The warm profile gone: after a crash it may hold a lock or half a write, so the next conversion starts cold."""
    home, _office['home'] = _office['home'], None
    if home:
        shutil.rmtree(home, ignore_errors=True)


def office_seconds(slides):
    return int(OFFICE_SECONDS + OFFICE_SECONDS_PER_SLIDE * max(0, slides - OFFICE_SLIDES))


def convert_deck(source, folder, slides):
    """A deck of ours to PDF. The one function that knows how, so a resident office could replace it.

    A process of its own under the child's rlimits and allowlisted environment,
    in its own process group, which the sandbox kills whatever happens to it.
    """
    seconds = office_seconds(slides)
    try:
        return execute_sandbox('convert.pptx_to_pdf', [source], {}, folder, timeout=seconds + 10, office_timeout=seconds, deck_fonts=True, office_home=_office_home())['artifacts'][0]
    except ProcessorError:
        forget_office()
        raise


# --- Drawing slides --------------------------------------------------------------------------

def _shared_digest(presentation):
    """The part of a slide's look kept outside it: the theme and the master apply_theme and apply_fonts write."""
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    master = presentation.slide_master
    digest = hashlib.sha256(etree.tostring(master._element))
    digest.update(master.part.part_related_by(RT.THEME).blob)
    return digest.hexdigest()


def slide_key(version, shared, locale, slide):
    """What a slide's picture is made from, and nothing else: see the top of this file."""
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    # Its pictures, by their bytes. Its notes are not on it, and its layout is the blank one of every slide.
    parts = [hashlib.sha256(rel.target_part.blob).hexdigest() for _, rel in sorted(slide.part.rels.items()) if rel.reltype not in (RT.NOTES_SLIDE, RT.SLIDE_LAYOUT)]
    digest = hashlib.sha256(json.dumps([version, shared, locale, parts]).encode())
    digest.update(etree.tostring(slide._element))
    return digest.hexdigest()


def _only_these(presentation, indexes, path):
    """A copy of the deck holding only the slides at `indexes`, in order, each still saying its own number.

    A slide's number is a field its viewer fills in from where the slide stands,
    which is no longer where it stands in the deck, so here it becomes the number it is.
    """
    from pptx.oxml.ns import qn
    listed = presentation.slides._sldIdLst
    for index, entry in reversed(list(enumerate(listed))):
        if index not in indexes:
            presentation.part.drop_rel(entry.rId)
            listed.remove(entry)
    for slide in presentation.slides:
        for field in list(slide._element.iter(qn('a:fld'))):
            if field.get('type') == 'slidenum':
                run = field.makeelement(qn('a:r'), {})
                run.extend(child for child in list(field) if child.tag in (qn('a:rPr'), qn('a:t')))
                field.getparent().replace(field, run)
    presentation.save(str(path))


def _unpack_pages(archive, count, folder):
    """The page PNGs of a pdf.to_images zip, written out one by one: a deck of photos is too much to hold."""
    from PIL import Image
    found = []
    folder.mkdir(mode=0o700)
    with zipfile.ZipFile(archive) as pages:
        for number in range(1, count + 1):
            name = f'page-{number:04d}.png'
            entry = pages.getinfo(name)
            if entry.file_size > PNG_BYTES:
                raise ProcessorError('output_size_limit')
            path = folder / name
            path.write_bytes(pages.read(entry))
            thumb = folder / f'thumb-{number:04d}.png'
            with Image.open(path) as picture:
                # LibreOffice's page can round to a pixel over.
                if picture.size != PNG_SIZE:
                    picture.resize(PNG_SIZE, Image.LANCZOS).save(path, 'PNG')
                picture.resize(THUMB_SIZE, Image.LANCZOS).convert('RGB').save(thumb, 'PNG')
            found.append((path, thumb))
    return found


def draw_slides(content, locale, style, pins, pictures, known, folder):
    """(the deck's slides as a render says them, {key: (png path, thumbnail path, frames)} of those not drawn before).

    `known(keys)` says which keys have a picture already: those slides are
    dropped from a copy before LibreOffice sees it, so only what changed is
    converted. `folder` is the caller's to clean. No database: the container
    smoke runs this too.
    """
    from pptx import Presentation
    from . import slide_fit
    from .deck_designs import version
    from .slides import prepare_slides, render_pptx
    drawn = render_pptx(content, folder / 'deck.pptx', locale, 'user_document', style=style, photos=pictures, pins=pins)['metadata']
    presentation = Presentation(str(folder / 'deck.pptx'))
    prepared, _ = prepare_slides(content, locale, pictures)
    renderer, shared = version(), _shared_digest(presentation)
    over = {row['index'] for row in drawn['shortened']}
    pictured = {row['slide'] for row in drawn['photos']}
    slides = []
    for index, (slide, kind, row) in enumerate(zip(presentation.slides, drawn['layouts'], prepared)):
        section = row[2]
        letters = max(1, slide_fit.letters_left_out(kind, section, slide)) if index in over else 0
        slides.append({'index': index, 'key': slide_key(renderer, shared, locale, slide), 'frames': slide_fit.slide_frames(kind, section, slide, index + 1 in pictured),
                       'fits': index not in over, 'letters_over': letters})
    have = known({row['key'] for row in slides})
    wanted = {}
    for row in slides:
        if row['key'] not in have:
            wanted.setdefault(row['key'], row)
    if not wanted:
        return slides, {}
    _only_these(presentation, {row['index'] for row in wanted.values()}, folder / 'wanted.pptx')
    pdf = convert_deck(folder / 'wanted.pptx', folder / 'pdf', len(wanted))
    if pdf['page_count'] != len(wanted):
        raise ProcessorError('conversion_failed')
    seconds = int(IMAGE_SECONDS + IMAGE_SECONDS_PER_SLIDE * len(wanted))
    archive = execute_sandbox('pdf.to_images', [pdf['path']], {'pages': 'all', 'format': 'png', 'dpi': PNG_DPI}, folder / 'images', timeout=seconds)['artifacts'][0]['path']
    images = _unpack_pages(archive, len(wanted), folder / 'pages')
    return slides, {key: (*files, row['frames']) for (key, row), files in zip(wanted.items(), images)}


def _drop(render):
    """A slide's picture and thumbnail gone, row and bytes: deleting a file takes its row with it."""
    for asset in FileAsset.objects.filter(pk__in=(render.file_id, render.thumb_id)):
        storage.delete(asset.object_key)
        asset.delete()


def drop_renders(draft):
    """All a draft's slide pictures, for a draft being deleted: they would otherwise wait out the draft's clock."""
    for render in SlideRender.objects.filter(draft=draft):
        _drop(render)


def current_pictures(draft):
    """The files of the slides of the draft's last render. Any others are on their way out (prune)."""
    rows = SlideRender.objects.filter(draft=draft)
    last = rows.aggregate(last=Max('used_at'))['last']
    return [asset for pair in rows.filter(used_at=last).values_list('file_id', 'thumb_id') for asset in pair]


def _known(draft_id, keys):
    """Which of `keys` the draft has a picture of still. One whose files have gone is forgotten, to be drawn again."""
    now = timezone.now()
    found = set()
    for render in SlideRender.objects.select_related('file', 'thumb').filter(draft_id=draft_id, key__in=keys):
        if all(asset.state == 'ready' and asset.expires_at > now and storage.exists(asset.object_key) for asset in (render.file, render.thumb)):
            found.add(render.key)
        else:
            _drop(render)
    return found


def _keep_png(account_id, draft, path, size):
    data = path.read_bytes()
    key = f'previews/{account_id}/{draft.pk}/{uuid.uuid4().hex}.png'
    # Sent to the bucket by the cleanup loop's sync: sixty of them must not wait on it one by one with the draft locked.
    storage.write(key, data, 'image/png', later=True)
    return FileAsset.objects.create(account_id=account_id, name='slide.png', object_key=key, mime_type='image/png', sha256=hashlib.sha256(data).hexdigest(),
                                    size_bytes=len(data), page_count=1, expires_at=draft.expires_at,
                                    metadata={'kind': 'deck_slide', 'draft_id': str(draft.pk), 'width': size[0], 'height': size[1]})


def _store(account_id, draft_id, images, used):
    """The new pictures kept and all of the render's marked as used (`used`, its keys), under the draft's lock so it cannot go halfway; nothing when it was deleted mid-task. They go by its clock."""
    with transaction.atomic():
        draft = GenerationDraft.objects.select_for_update().filter(pk=draft_id).first()
        if draft is None:
            return False
        existing = set(SlideRender.objects.filter(draft=draft, key__in=images).values_list('key', flat=True))
        for key, (png, thumb, frames) in images.items():
            if key not in existing:
                SlideRender.objects.create(draft=draft, key=key, frames=frames, file=_keep_png(account_id, draft, png, PNG_SIZE), thumb=_keep_png(account_id, draft, thumb, THUMB_SIZE))
        SlideRender.objects.filter(draft=draft, key__in=used).update(used_at=timezone.now())
    return True


def _render_deck(row):
    """The draft as it now stands, its slides that changed drawn and kept; its result names the version it drew.

    A later save may leave this a version behind, which harms nothing: pictures
    go by key, so two renders' can stand side by side, and each result answers
    only for its own version (render_state). The slides of a deck may not all fit:
    a preview shows what would show and says so, which is what a customer fixes from.
    """
    from .render_export import _editable, _pictures, _style, chosen_photos
    draft = GenerationDraft.objects.filter(pk=row.draft_id, expires_at__gt=timezone.now()).first()
    if draft is None:
        raise DomainError('not_found', 404)
    data = unpack(draft.encrypted_data)
    _editable(draft, data)
    pictures = _pictures(row.account, chosen_photos(data))
    style = _style(row.account, EXPORT, data, [])
    root = storage_path('scratch')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix='editor-', dir=root) as scratch:
        slides, images = draw_slides(data['content'], data['output_locale'], style, data['_render'], pictures, lambda keys: _known(draft.pk, keys), Path(scratch))
        _store(row.account_id, draft.pk, images, {slide['key'] for slide in slides})
    return {'version': draft.version, 'slides': slides}


def _preview(row):
    """One page of a customer's PDF, in the bounded child: core/previews.py keeps it, and the request that asks again finds it."""
    from apps.core.previews import preview_asset
    payload = unpack(row.encrypted_payload)
    return {'file_id': str(preview_asset(row.account, payload['asset_id'], payload['page'], payload.get('secret_id'), timeout=PREVIEW_SECONDS).pk)}


def _photos(row):
    from .deck_photos import run
    return run(row)


HANDLERS = {RENDER: _render_deck, PREVIEW: _preview, PHOTOS: _photos}


# --- What the customer is told ---------------------------------------------------------------

def _deck_draft(account, draft_id):
    draft = GenerationDraft.objects.filter(account=account, pk=draft_id, expires_at__gt=timezone.now()).first()
    if draft is None:
        raise DomainError('not_found', 404)
    require(account, EXPORT)
    return draft


def _state(draft, version):
    """(status, the task that says so, its result if done) of the render of this version of the draft.

    `queued` and `running`: a task will draw this version or a later one, which
    is what a customer who kept typing wants. `done`: one drew exactly this
    version. `stale`: not this version, and the deck has moved on. `failed`: the
    last try at it failed. `none`: nothing has been asked, or what was has gone
    (POST /render asks).
    """
    rows = list(EditorTask.objects.filter(draft=draft, kind=RENDER).order_by('-created_at')[:HISTORY])
    payloads = {row.pk: unpack(row.encrypted_payload) for row in rows if row.encrypted_payload}
    for row in rows:
        if row.status == DONE and row.encrypted_result:
            result = unpack(row.encrypted_result)
            keys = {slide['key'] for slide in result['slides']}
            # A picture that has since gone leaves nothing to show: it is drawn again when asked for.
            if result['version'] == version and keys == set(SlideRender.objects.filter(draft=draft, key__in=keys).values_list('key', flat=True)):
                return DONE, row, result
    waiting = [row for row in rows if row.status in WAITING and payloads.get(row.pk, {}).get('version', -1) >= version]
    if waiting:
        # The one furthest along.
        row = next((row for row in waiting if row.status == RUNNING), waiting[0])
        return row.status, row, None
    failed = next((row for row in rows if row.status == FAILED and payloads.get(row.pk, {}).get('version') == version), None)
    if failed is not None:
        return FAILED, failed, None
    return ('stale' if version != draft.version else 'none'), None, None


def render_state(account, draft_id, version=None):
    """How the render of a version of the draft stands, as GET /render says it: the draft's current one if none is named."""
    draft = _deck_draft(account, draft_id)
    version = draft.version if version is None else version
    status, row, result = _state(draft, version)
    base = f'/api/v1/generation/drafts/{draft.pk}/slides/'
    slides = [{**slide, 'url': f'{base}{slide["key"]}.png', 'thumb_url': f'{base}{slide["key"]}.thumb.png'} for slide in (result or {}).get('slides', [])]
    return {'status': status, 'version': version, 'slides': slides, 'error': row.error if status == FAILED else None}


def request_render(account, draft_id, version):
    """The render of this version asked for: the task doing it if there is one, a queued one if not. Nothing is drawn here."""
    from .render_export import _editable
    draft = _deck_draft(account, draft_id)
    if type(version) is not int or version != draft.version:
        raise DomainError('version_conflict', 409)
    _editable(draft, unpack(draft.encrypted_data))
    status, row, _ = _state(draft, version)
    if status in (DONE, *WAITING):
        return status, row
    row = enqueue(account, RENDER, {'version': version}, draft=draft)
    return row.status, row


def waiting_preview(account, asset_id, page):
    """The preview task of this page still waiting, or `None`; one that failed just now is said again, not tried again.

    Up to MAX_QUEUED wait and few fail, so unpacking a few payloads is all this costs.
    """
    now = timezone.now()
    rows = EditorTask.objects.filter(Q(status__in=WAITING) | Q(status=FAILED, finished_at__gte=now - timedelta(seconds=PREVIEW_FAILED_SECONDS)),
                                     account=account, kind=PREVIEW).order_by('-created_at')[:HISTORY]
    for row in rows:
        payload = unpack(row.encrypted_payload) if row.encrypted_payload else {}
        if payload.get('asset_id') == str(asset_id) and payload.get('page') == page:
            if row.status == FAILED:
                raise DomainError(row.error or 'editor_task_failed', 409, retryable=row.error in INTERRUPTED.values())
            return row
    return None
