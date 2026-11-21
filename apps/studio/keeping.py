"""A generated document's draft, kept for good with every file a change of it needs.

Every AI PDF, deck and CV the customer was sent offers ✏️ Make changes, in the
chat however old its message is, and on the web (the task's page, the deck
editor). What a change reads is the draft the file was made from, so once a
file has been made from a draft (settle_job), the draft no longer expires: its
`expires_at` becomes KEPT_UNTIL, one far-off moment rather than a new column,
and every reader asking for a live draft (`expires_at__gt=now`) still finds it,
a day, a month or a year later. A change of a change is kept the same way once
a file is made from it.

So are the files a change reads (`needed`): the draft's sources and logo and a
CV's portrait (its uploads, which a change's quote asks for again), and a deck's
pictures, those on its slides and those on offer, and its slides as last drawn
(its own, named by their `draft_id`). An upload names the kept drafts that hold
it (`metadata['kept_by']`), as one upload may be the source of several. What a
kept draft no longer needs goes back on its own clock, the day it would have had
(24 hours from when it was made, or later for an upload, `own_until` below):
a picture a deck stopped wearing and offering, the files of a draft the
customer deleted (`delete`). Results themselves, and uploads no kept draft
needs, still go after 24 hours; a draft never generated expires as before.

KEPT_UNTIL is no date to show anyone: `shown` turns it into None for the API,
nothing adds time to it, and it is never shortened by a file's own deadline.

A kept upload is held for the changes, not as a download: after its own day
nothing serves it to the customer or takes it as a file tool's input
(`held_past_its_day`), as before. Its own day runs as any file's does (`own_until`):
24 hours from when it was made, or to the end of the latest task it went into
while that day lasted, the AI document it was first kept for among them
(`metadata['own_until']`, moved on by `used`). What refuses it says it is kept for the
document (`held_refusal`), never that it was deleted. Where it is listed as
something to open (an editor's file, a task's result) it says when its day ends
and is expired after it (`served_until`). One gone all the same (the customer deleted
it, or it ran out before it was kept) is gone: a change goes on without it
(`still_there`), from what was read of a source, which the draft holds, and
without a logo, which its file then says (logo_left_out).
Should a kept draft go any way but `delete` (a row removed by hand), the
cleanup's backstop (`release_orphans`) gives its files back their own clock.
An account that asked to be deleted has nothing kept (`keep`, `backfill`).
"""
import logging
from datetime import datetime, timedelta, timezone as dt_timezone

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

KEPT_UNTIL = datetime(2999, 12, 31, tzinfo=dt_timezone.utc)
# How long a file lasts from when it was made: what a file no kept draft needs any more goes back to.
OWN_CLOCK = timedelta(hours=24)
# Where a held upload notes when its own day ends, once a task has moved it past OWN_CLOCK (an ISO moment, in metadata).
OWN_UNTIL = 'own_until'
# A deck's own files, named by the draft they belong to.
PICTURES = ('deck_photo', 'deck_slide')
# How often the cleanup looks for kept files whose drafts are gone: it reads every kept file's row, this many at a time.
ORPHANS_EVERY = timedelta(hours=6)
ORPHANS_BATCH = 500
# Where the backfill notes how far it is (operations IntegrationConfig, as storage_health keeps its state). Once a
# pass finds nothing it could not settle, it goes on looking this long, for a draft a worker still running the code
# from before made while a deploy rolled, and then never again.
BACKFILL_STATE = 'kept_drafts_backfill'
BACKFILL_GRACE = timedelta(hours=24)

logger = logging.getLogger(__name__)


def is_kept(moment):
    return moment is not None and moment >= KEPT_UNTIL


def shown(moment):
    """An expiry as a customer may see it: none at all for something kept."""
    return None if is_kept(moment) else moment


def _held(asset):
    """An upload a kept draft holds: served for its own day only (own_until). Never a deck's own picture or slide."""
    metadata = asset.metadata or {}
    return is_kept(asset.expires_at) and 'kept_by' in metadata and metadata.get('kind') not in PICTURES


def own_until(asset):
    """When an upload's own day ends, as it would have without a kept draft holding it: OWN_CLOCK from when it was made,
    or the end of the latest task it went into while that day lasted (OWN_UNTIL), whichever is later."""
    from django.utils.dateparse import parse_datetime
    made = asset.created_at + OWN_CLOCK
    try:
        noted = parse_datetime(str((asset.metadata or {}).get(OWN_UNTIL) or ''))
    except ValueError:
        noted = None
    return max(made, noted) if noted is not None and noted.tzinfo is not None else made


def held_past_its_day(asset, now=None):
    """An upload a kept draft holds, past its own day (own_until): kept for a change of the draft, never served or used otherwise.

    Never a deck's own picture or slide, which its deck editor shows and sends however old it is.
    """
    return _held(asset) and own_until(asset) <= (now or timezone.now())


def served_until(asset):
    """When a file stops being opened or downloaded, as a customer may see it: a kept draft's upload at the end of its
    own day (held_past_its_day after that), something else kept never (None), anything else at its expiry."""
    return own_until(asset) if _held(asset) else shown(asset.expires_at)


@transaction.atomic
def used(account_id, ids, until):
    """These files went into a task whose files last until `until`: a held upload among them is served until then too,
    as any other input is moved to its task's day (settle_job, a send again). Never shorter than it was, and never one
    whose own day is over: past it, a change of its draft reads it and no more."""
    from apps.core.models import FileAsset
    now = timezone.now()
    for asset in FileAsset.objects.select_for_update().filter(account_id=account_id, pk__in=[str(value) for value in ids or []],
                                                              state='ready', expires_at__gte=KEPT_UNTIL, metadata__has_key='kept_by'):
        if _held(asset) and now < own_until(asset) < until:
            asset.metadata = {**asset.metadata, OWN_UNTIL: until.isoformat()}
            asset.save(update_fields=['metadata'])


# Why a held upload past its day is refused (`message_params.reason`): it is still stored, only for changing the AI
# document made from it, so the refusal never says it was deleted or ran out.
KEPT_FOR_DOCUMENT = 'kept_for_document'


def held_refusal():
    """The refusal of a held upload past its day: `file_expired`, as before, saying why (KEPT_FOR_DOCUMENT)."""
    from apps.core.errors import DomainError
    return DomainError('file_expired', 410, params={'reason': KEPT_FOR_DOCUMENT})


def still_there(account, ids):
    """Those of these files the account still has to read, in their order: what a change of a kept draft goes on with.

    A file the customer deleted, or one that ran out before its draft was kept, is left out. One held past its day
    is still there: it is held for exactly this.
    """
    import uuid
    from apps.core.models import FileAsset
    valid = []
    for value in ids or []:
        try:
            valid.append(str(uuid.UUID(str(value))))
        except (TypeError, ValueError, AttributeError):
            continue
    found = {str(pk) for pk in FileAsset.objects.filter(account=account, pk__in=valid, state='ready',
                                                         expires_at__gt=timezone.now()).values_list('pk', flat=True)}
    return [value for value in ids or [] if str(value) in found]


def button_until(account, draft_id, default):
    """How long a ✏️ Make changes button for this draft is kept: as long as the draft, once it is kept."""
    from .models import GenerationDraft
    if not draft_id:
        return default
    try:
        kept = GenerationDraft.objects.filter(account=account, pk=draft_id, expires_at__gte=KEPT_UNTIL).exists()
    except (ValueError, TypeError, ValidationError):
        return default
    return KEPT_UNTIL if kept else default


def _pictures(draft, data):
    """The deck's pictures on its slides and on offer, and its slides as last drawn."""
    from .tasks import current_pictures
    photos = (data.get('_render') or {}).get('photos') or {}
    pinned = {str(asset_id) for photo in photos.values()
              for asset_id in (photo.get('asset_id'), *(c.get('asset_id') for c in photo.get('candidates') or [])) if asset_id}
    return pinned | {str(asset_id) for asset_id in current_pictures(draft)}


def _uploads(data):
    """The customer's files a change asks for again: the sources and logo its quote lists, and a CV's portrait."""
    from .branding import generation_inputs
    ids = {str(asset_id) for asset_id in generation_inputs(data)}
    portrait = (data.get('options') or {}).get('portrait_asset_id')
    if portrait:
        ids.add(str(portrait))
    return ids


def needed(draft, data=None):
    """(pictures, uploads): the ids of the files a change of this draft reads."""
    from .domain import unpack
    data = unpack(draft.encrypted_data) if data is None else data
    return _pictures(draft, data), _uploads(data)


def _own_clock(asset, now):
    return max(own_until(asset), now)


def _unheld(metadata):
    """A file's metadata once no kept draft holds it: its expiry says when its day ends from then on."""
    return {key: value for key, value in (metadata or {}).items() if key not in ('kept_by', OWN_UNTIL)}


def _let_go(asset, holder, now):
    """`holder` no longer holds this upload; with no kept draft left holding it, it goes on its own clock."""
    holders = [value for value in asset.metadata.get('kept_by') or [] if value != holder]
    if holders:
        asset.metadata = {**asset.metadata, 'kept_by': holders}
        asset.save(update_fields=['metadata'])
        return
    asset.expires_at = _own_clock(asset, now)
    asset.metadata = _unheld(asset.metadata)
    asset.save(update_fields=['metadata', 'expires_at'])


def deleting(account_id):
    """Whether the account asked to be deleted (DELETE /me): nothing of it is kept from then on."""
    from apps.core.models import Account
    return Account.objects.filter(pk=account_id, deletion_requested_at__isnull=False).exists()


@transaction.atomic
def keep(draft, data=None):
    """A draft a file was made from, kept for good with all a change of it needs (settle_job).

    Nothing for an account that asked to be deleted: a job settling after the ask leaves its draft to expire.
    """
    from apps.core.models import BotCallback
    from .models import GenerationDraft
    if deleting(draft.account_id):
        return
    GenerationDraft.objects.filter(pk=draft.pk).update(expires_at=KEPT_UNTIL)
    draft.expires_at = KEPT_UNTIL
    # Its ✏️ Make changes buttons last as long as it does: the cleanup would otherwise take them with the file.
    BotCallback.objects.filter(account_id=draft.account_id, action='ai_revise', payload={'draft_id': str(draft.pk)}).update(expires_at=KEPT_UNTIL)
    hold(draft, data)


@transaction.atomic
def hold(draft, data=None, before=None):
    """What a kept draft needs now kept with it, and what it no longer needs let go. Nothing for a draft not kept.

    `before`: the draft as it was before a save, whose uploads it may have let go of.
    """
    from apps.core.models import FileAsset
    if not is_kept(draft.expires_at):
        return
    from .domain import unpack
    data = unpack(draft.encrypted_data) if data is None else data
    pictures, uploads = needed(draft, data)
    now = timezone.now()
    owner = str(draft.pk)
    account = draft.account_id
    FileAsset.objects.filter(account_id=account, state='ready', metadata__kind__in=PICTURES, pk__in=pictures,
                             expires_at__lt=KEPT_UNTIL).update(expires_at=KEPT_UNTIL)
    # A picture of its own it stopped wearing and offering: a slide's next one, a search's that fell off its list.
    # Slides it no longer draws are the prune's (tasks.prune), which knows when a render last used them.
    for asset in FileAsset.objects.filter(account_id=account, metadata__kind='deck_photo', metadata__draft_id=owner,
                                          expires_at__gte=KEPT_UNTIL).exclude(pk__in=pictures):
        asset.expires_at = _own_clock(asset, now)
        asset.save(update_fields=['expires_at'])
    # An upload already gone is not brought back: a change then goes on without it (still_there).
    for asset in FileAsset.objects.select_for_update().filter(account_id=account, state='ready', pk__in=uploads, expires_at__gt=now):
        holders = list(asset.metadata.get('kept_by') or [])
        if owner not in holders or not is_kept(asset.expires_at):
            metadata = {**asset.metadata, 'kept_by': [*holders, owner] if owner not in holders else holders}
            if not is_kept(asset.expires_at):
                # Its own day as it stood, for what serves it (own_until): settle_job has just carried it to the end
                # of the document made from it, as it carries every input of a task.
                metadata[OWN_UNTIL] = max(own_until(asset), asset.expires_at).isoformat()
            asset.metadata = metadata
            asset.expires_at = KEPT_UNTIL
            asset.save(update_fields=['metadata', 'expires_at'])
    dropped = (_uploads(before) - uploads) if before is not None else set()
    for asset in FileAsset.objects.select_for_update().filter(account_id=account, pk__in=dropped, expires_at__gte=KEPT_UNTIL):
        if owner in (asset.metadata.get('kept_by') or []):
            _let_go(asset, owner, now)


def _delete_bytes(keys):
    from apps.core import storage
    for key in keys:
        storage.delete(key)


@transaction.atomic
def delete(draft):
    """A draft deleted with what it held: its own pictures and slides at once, uploads no other kept draft holds on their own clock.

    The one way a draft goes other than by expiring (the customer's delete, an account's): a kept draft's files
    would otherwise be kept for good with nothing left to need them. Their rows go with the draft, and their bytes
    once that is committed: a delete rolled back (a request that fails after it) leaves every file in place, and
    bytes that cannot be removed then are the storage sweep's.
    """
    from apps.core.models import BotCallback, FileAsset
    from .models import GenerationDraft, SlideRender
    # Under the draft's lock: a render storing its pictures finishes first and they are seen here, or it finds the draft gone.
    GenerationDraft.objects.select_for_update().filter(pk=draft.pk).first()
    owner = str(draft.pk)
    # Its pictures and its slides as drawn, the slides' rows (SlideRender) going with their files.
    own = set(FileAsset.objects.filter(account_id=draft.account_id, metadata__kind__in=PICTURES, metadata__draft_id=owner).values_list('pk', flat=True))
    own |= {pk for pair in SlideRender.objects.filter(draft=draft).values_list('file_id', 'thumb_id') for pk in pair}
    keys = [key for key in FileAsset.objects.filter(pk__in=own).values_list('object_key', flat=True) if key]
    FileAsset.objects.filter(pk__in=own).delete()
    if keys:
        transaction.on_commit(lambda: _delete_bytes(keys), robust=True)
    now = timezone.now()
    for asset in FileAsset.objects.select_for_update().filter(account_id=draft.account_id, expires_at__gte=KEPT_UNTIL, metadata__has_key='kept_by'):
        if owner in (asset.metadata.get('kept_by') or []):
            _let_go(asset, owner, now)
    BotCallback.objects.filter(account_id=draft.account_id, action='ai_revise', payload={'draft_id': owner}).delete()
    draft.delete()


def made_from(draft_ids):
    """Which of these drafts a file was made from: a generation that succeeded with a file, an outline aside."""
    from apps.core.models import Job
    from .domain import GENERATION_IDS
    ids = [str(value) for value in draft_ids]
    found = set()
    # A day of drafts not kept yet can be thousands: asked about a few hundred at a time.
    for start in range(0, len(ids), 500):
        rows = (Job.objects.filter(feature_id__in=GENERATION_IDS, status='succeeded', parameters__generation_draft_id__in=ids[start:start + 500],
                                   artifacts__isnull=False).values_list('parameters', flat=True))
        found |= {parameters['generation_draft_id'] for parameters in rows if (parameters or {}).get('stage') != 'outline'}
    return found


def _backfill_state():
    from operations.models import IntegrationConfig
    row = IntegrationConfig.objects.filter(pk=BACKFILL_STATE).only('configuration').first()
    return dict(row.configuration) if row else {}


def _note_backfill(values):
    from operations.models import IntegrationConfig
    IntegrationConfig.objects.update_or_create(key=BACKFILL_STATE, defaults={'configuration': values})


def backfill():
    """Drafts a file was made from that are not kept yet, kept now: those from before drafts were kept. Idempotent.

    The cleanup's first step, before anything expires: drafts made before this shipped, still there when it first
    runs (expired but not yet taken included), are kept with their files as if settled now. An account that asked
    to be deleted has them deleted instead. After that it finds none, as settle_job keeps each draft it makes a
    file from, so it stops: once a pass has found nothing it could not settle, it goes on BACKFILL_GRACE more and
    then reads one row a pass (BACKFILL_STATE), with no draft or job looked at again.
    """
    from django.utils.dateparse import parse_datetime
    from .models import GenerationDraft
    state = _backfill_state()
    if state.get('done'):
        return 0
    now = timezone.now()
    clean_since = parse_datetime(state['clean_since']) if state.get('clean_since') else None
    if clean_since is not None and now >= clean_since + BACKFILL_GRACE:
        _note_backfill({**state, 'done': True, 'done_at': now.isoformat()})
        return 0
    waiting = list(GenerationDraft.objects.filter(expires_at__lt=KEPT_UNTIL).values_list('pk', flat=True))
    found = made_from(waiting)
    kept = failed = 0
    for draft in GenerationDraft.objects.filter(pk__in=[value for value in waiting if str(value) in found]):
        # One draft that cannot be read (a key changed, a malformed row) is left to expire as it would have:
        # it never holds up the others, nor the cleanup after it. keep() is atomic, so it leaves nothing half done.
        try:
            if deleting(draft.account_id):
                delete(draft)
                continue
            keep(draft)
        except Exception:
            failed += 1
            logger.exception('A draft a file was made from could not be kept: %s', draft.pk)
            continue
        kept += 1
    if not failed and clean_since is None:
        _note_backfill({**state, 'clean_since': now.isoformat()})
    return kept


_orphans = {'at': None}


def _exists(draft_id):
    from .models import GenerationDraft
    try:
        return GenerationDraft.objects.filter(pk=draft_id).exists()
    except (ValueError, ValidationError):
        return False


def _living(names):
    """Which of these draft ids are drafts that exist, asked a few hundred at a time."""
    from .models import GenerationDraft
    living = set()
    names = sorted(names)
    for start in range(0, len(names), ORPHANS_BATCH):
        batch = names[start:start + ORPHANS_BATCH]
        try:
            living |= {str(pk) for pk in GenerationDraft.objects.filter(pk__in=batch).values_list('pk', flat=True)}
        except (ValueError, ValidationError):
            # A name that is no draft id at all holds nothing: each of the batch is asked alone.
            living |= {name for name in batch if _exists(name)}
    return living


def _in_batches(rows, key):
    """`rows` (a queryset of value tuples, the key first) ORPHANS_BATCH at a time, in key order: never all of them at once."""
    last = None
    while True:
        batch = list((rows.filter(**{f'{key}__gt': last}) if last is not None else rows).order_by(key)[:ORPHANS_BATCH])
        if not batch:
            return
        yield batch
        last = batch[-1][0]


def release_orphans(now=None, force=False):
    """The backstop: kept files whose drafts are all gone, by any way but `delete`, back on their own clock. Every ORPHANS_EVERY.

    A deck's picture or slide whose draft no longer exists, an upload none of whose holders exist (the gone
    ones dropped from `kept_by` where others remain), and a ✏️ Make changes button kept for a gone draft.
    Kept files are read ORPHANS_BATCH at a time, so the pass holds no more than that however much is kept.
    """
    from apps.core.models import BotCallback, FileAsset
    now = now or timezone.now()
    last = _orphans['at']
    if not force and last is not None and last <= now < last + ORPHANS_EVERY:
        return 0
    _orphans['at'] = now
    released = 0
    for rows in _in_batches(FileAsset.objects.filter(expires_at__gte=KEPT_UNTIL).values_list('pk', 'metadata'), 'pk'):
        named = {str(value) for _, metadata in rows for value in [(metadata or {}).get('draft_id'), *((metadata or {}).get('kept_by') or [])] if value}
        living = _living(named)
        for pk, metadata in rows:
            metadata = metadata or {}
            owner = metadata.get('draft_id') if metadata.get('kind') in PICTURES else None
            holders = [str(value) for value in metadata.get('kept_by') or []]
            # A deck's own file goes with its draft; an upload once none of its holders is left (one held by nothing, too).
            if (str(owner) in living) if owner else (holders and all(value in living for value in holders)):
                continue
            with transaction.atomic():
                asset = FileAsset.objects.select_for_update().filter(pk=pk, expires_at__gte=KEPT_UNTIL).first()
                if asset is None:
                    continue
                # A holder added since the drafts were looked up (a change kept meanwhile) is asked about now.
                left = [] if owner else [value for value in asset.metadata.get('kept_by') or []
                                         if str(value) in living or (str(value) not in named and _exists(value))]
                asset.metadata = {**asset.metadata, 'kept_by': left}
                if not left:
                    asset.expires_at = _own_clock(asset, now)
                    asset.metadata = _unheld(asset.metadata)
                    released += 1
                asset.save(update_fields=['metadata', 'expires_at'])
    for rows in _in_batches(BotCallback.objects.filter(action='ai_revise', expires_at__gte=KEPT_UNTIL).values_list('token', 'payload'), 'token'):
        named = {str((payload or {}).get('draft_id')) for _, payload in rows if (payload or {}).get('draft_id')}
        living = _living(named)
        gone = [token for token, payload in rows if str((payload or {}).get('draft_id')) not in living]
        if gone:
            BotCallback.objects.filter(pk__in=gone).delete()
    if released:
        logger.warning('Kept files whose drafts are gone were let go: %s', released)
    return released
