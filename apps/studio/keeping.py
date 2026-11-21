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
"""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

KEPT_UNTIL = datetime(2999, 12, 31, tzinfo=dt_timezone.utc)
# How long a file lasts from when it was made: what a file no kept draft needs any more goes back to.
OWN_CLOCK = timedelta(hours=24)
# A deck's own files, named by the draft they belong to.
PICTURES = ('deck_photo', 'deck_slide')


def is_kept(moment):
    return moment is not None and moment >= KEPT_UNTIL


def shown(moment):
    """An expiry as a customer may see it: none at all for something kept."""
    return None if is_kept(moment) else moment


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
        keep(draft)
        kept += 1
    return kept
