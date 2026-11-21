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
kept draft no longer needs goes back on its own clock, 24 hours from when it was
made: a picture a deck stopped wearing and offering, the files of a draft the
customer deleted (`delete`). Results themselves, and uploads no kept draft
needs, still go after 24 hours; a draft never generated expires as before.

KEPT_UNTIL is no date to show anyone: `shown` turns it into None for the API,
nothing adds time to it, and it is never shortened by a file's own deadline.

A kept upload is held for the changes, not as a download: after its own 24
hours it is no longer served to the customer (`held_past_its_day`), as before.
Should a kept draft go any way but `delete` (a row removed by hand), the
cleanup's backstop (`release_orphans`) gives its files back their own clock.
"""
import logging
from datetime import datetime, timedelta, timezone as dt_timezone

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

KEPT_UNTIL = datetime(2999, 12, 31, tzinfo=dt_timezone.utc)
# How long a file lasts from when it was made: what a file no kept draft needs any more goes back to.
OWN_CLOCK = timedelta(hours=24)
# A deck's own files, named by the draft they belong to.
PICTURES = ('deck_photo', 'deck_slide')
# How often the cleanup looks for kept files whose drafts are gone: it reads every kept file's row.
ORPHANS_EVERY = timedelta(hours=6)

logger = logging.getLogger(__name__)


def is_kept(moment):
    return moment is not None and moment >= KEPT_UNTIL


def shown(moment):
    """An expiry as a customer may see it: none at all for something kept."""
    return None if is_kept(moment) else moment


def held_past_its_day(asset, now=None):
    """An upload a kept draft holds, past the 24 hours it had: kept for a change of the draft, no longer to be downloaded."""
    return (is_kept(asset.expires_at) and 'kept_by' in (asset.metadata or {})
            and asset.created_at + OWN_CLOCK <= (now or timezone.now()))


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
    return max(asset.created_at + OWN_CLOCK, now)


def _let_go(asset, holder, now):
    """`holder` no longer holds this upload; with no kept draft left holding it, it goes on its own clock."""
    holders = [value for value in asset.metadata.get('kept_by') or [] if value != holder]
    metadata = {key: value for key, value in asset.metadata.items() if key != 'kept_by'}
    if holders:
        asset.metadata = {**metadata, 'kept_by': holders}
        asset.save(update_fields=['metadata'])
        return
    asset.metadata = metadata
    asset.expires_at = _own_clock(asset, now)
    asset.save(update_fields=['metadata', 'expires_at'])


@transaction.atomic
def keep(draft, data=None):
    """A draft a file was made from, kept for good with all a change of it needs (settle_job)."""
    from apps.core.models import BotCallback
    from .models import GenerationDraft
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
    # An upload already gone is not brought back: the change then goes on without it, as it did before.
    for asset in FileAsset.objects.select_for_update().filter(account_id=account, state='ready', pk__in=uploads, expires_at__gt=now):
        holders = list(asset.metadata.get('kept_by') or [])
        if owner not in holders or not is_kept(asset.expires_at):
            asset.metadata = {**asset.metadata, 'kept_by': [*holders, owner] if owner not in holders else holders}
            asset.expires_at = KEPT_UNTIL
            asset.save(update_fields=['metadata', 'expires_at'])
    dropped = (_uploads(before) - uploads) if before is not None else set()
    for asset in FileAsset.objects.select_for_update().filter(account_id=account, pk__in=dropped, expires_at__gte=KEPT_UNTIL):
        if owner in (asset.metadata.get('kept_by') or []):
            _let_go(asset, owner, now)


@transaction.atomic
def delete(draft):
    """A draft deleted with what it held: its own pictures and slides at once, uploads no other kept draft holds on their own clock.

    The one way a draft goes other than by expiring (the customer's delete, an account's): a kept draft's files
    would otherwise be kept for good with nothing left to need them.
    """
    from apps.core import storage
    from apps.core.models import BotCallback, FileAsset
    from .models import GenerationDraft
    from .tasks import drop_renders
    # Under the draft's lock: a render storing its pictures finishes first and they are seen here, or it finds the draft gone.
    GenerationDraft.objects.select_for_update().filter(pk=draft.pk).first()
    drop_renders(draft)
    owner = str(draft.pk)
    for asset in FileAsset.objects.filter(account_id=draft.account_id, metadata__kind__in=PICTURES, metadata__draft_id=owner):
        storage.delete(asset.object_key)
        asset.delete()
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


def backfill():
    """Drafts a file was made from that are not kept yet, kept now: those from before drafts were kept. Idempotent.

    The cleanup's first step, before anything expires: drafts made before this shipped, still there when it first
    runs (expired but not yet taken included), are kept with their files as if settled now. After that it finds
    none, as settle_job keeps each draft it makes a file from.
    """
    from .models import GenerationDraft
    waiting = list(GenerationDraft.objects.filter(expires_at__lt=KEPT_UNTIL).values_list('pk', flat=True))
    found = made_from(waiting)
    kept = 0
    for draft in GenerationDraft.objects.filter(pk__in=[value for value in waiting if str(value) in found]):
        # One draft that cannot be read (a key changed, a malformed row) is left to expire as it would have:
        # it never holds up the others, nor the cleanup after it. keep() is atomic, so it leaves nothing half done.
        try:
            keep(draft)
        except Exception:
            logger.exception('A draft a file was made from could not be kept: %s', draft.pk)
            continue
        kept += 1
    return kept


_orphans = {'at': None}


def _exists(draft_id):
    from .models import GenerationDraft
    try:
        return GenerationDraft.objects.filter(pk=draft_id).exists()
    except (ValueError, ValidationError):
        return False


def release_orphans(now=None, force=False):
    """The backstop: kept files whose drafts are all gone, by any way but `delete`, back on their own clock. Every ORPHANS_EVERY.

    A deck's picture or slide whose draft no longer exists, an upload none of whose holders exist (the gone
    ones dropped from `kept_by` where others remain), and a ✏️ Make changes button kept for a gone draft.
    """
    from apps.core.models import BotCallback, FileAsset
    from .models import GenerationDraft
    now = now or timezone.now()
    last = _orphans['at']
    if not force and last is not None and last <= now < last + ORPHANS_EVERY:
        return 0
    _orphans['at'] = now
    rows = list(FileAsset.objects.filter(expires_at__gte=KEPT_UNTIL).values_list('pk', 'metadata'))
    named = {str(value) for _, metadata in rows for value in [(metadata or {}).get('draft_id'), *((metadata or {}).get('kept_by') or [])] if value}
    named |= {str((payload or {}).get('draft_id')) for payload in BotCallback.objects.filter(action='ai_revise', expires_at__gte=KEPT_UNTIL)
              .values_list('payload', flat=True) if (payload or {}).get('draft_id')}
    living = set()
    names = sorted(named)
    for start in range(0, len(names), 500):
        try:
            living |= {str(pk) for pk in GenerationDraft.objects.filter(pk__in=names[start:start + 500]).values_list('pk', flat=True)}
        except (ValueError, ValidationError):
            # A name that is no draft id at all holds nothing: each of the batch is asked alone.
            living |= {name for name in names[start:start + 500] if _exists(name)}
    released = 0
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
            asset.metadata = {**{key: value for key, value in asset.metadata.items() if key != 'kept_by'}, **({'kept_by': left} if left else {})}
            if not left:
                asset.expires_at = _own_clock(asset, now)
                released += 1
            asset.save(update_fields=['metadata', 'expires_at'])
    for token, payload in BotCallback.objects.filter(action='ai_revise', expires_at__gte=KEPT_UNTIL).values_list('pk', 'payload'):
        draft_id = str((payload or {}).get('draft_id'))
        if draft_id not in living and (draft_id in named or not _exists(draft_id)):
            BotCallback.objects.filter(pk=token).delete()
    if released:
        logger.warning('Kept files whose drafts are gone were let go: %s', released)
    return released
