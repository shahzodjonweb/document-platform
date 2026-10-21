"""The files CVs are made from, read one at a time by `runreader`, the accounts taking turns.

A file uploaded for a CV (purpose 'cv_source', apps/core/services.upload_file)
is queued for reading as it arrives: a row of its own (models.CvSourceRead).
`runreader` reads the queue in a container of its own, one file at a time
in the bounded child (extraction.read_cv), and keeps what each file gave,
encrypted as drafts are. A draft is made from what was kept (sources.read)
and never reads a file itself: while one of its files is still waiting it
is refused with `cv_reading`, which says how many reads are ahead and about
how long they take, and the customer waits for them (GET /studio/cv-reads)
instead of being asked to try again. A file uploaded before reads were
queued is queued the first time a draft or the web asks for it. In tests
and local development (settings.LOCAL_SYNC_JOBS) a file is read as it is
queued, so nothing waits.

Accounts take turns as jobs do (apps/core/scheduling.select_outbox): the one
served longest ago goes first, so one customer's ten screenshots hold
another's single PDF up for one read, not ten, and a read that has waited
AGING_SECONDS goes ahead of the rest, oldest first. A reader takes its read
under a lease: one that dies mid-read (its container killed) leaves the read
to be taken again once the lease has lapsed, MAX_ATTEMPTS times in all, and
then it is failed. Rows are locked with SKIP LOCKED and taken with a
compare-and-set, so a second reader can run beside the first.
"""
import logging
import math
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone as dt_timezone

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Max
from django.utils import timezone

from apps.core.errors import DomainError

from . import sources

logger = logging.getLogger(__name__)

QUEUED, READING, DONE, FAILED = 'queued', 'reading', 'done', 'failed'
WAITING = (QUEUED, READING)
# A read waiting this long goes ahead of the turns, oldest first, as a job does.
AGING_SECONDS = 300
# The queued reads the order is worked out over, oldest first, and how many of
# them a reader tries to lock at once.
WINDOW = 500
CLAIM_BATCH = 20
# One file's reading, its child's grace and fetching it from the bucket, with room.
LEASE_SECONDS = sources.READ_SECONDS + 120
# Reads a file is given: a reader that dies mid-read is the reader's fault the
# first time; a file that takes the reader down every time is failed.
MAX_ATTEMPTS = 3
# How long a read takes is told from the latest reads of the last few hours.
HISTORY = 20
HISTORY_HOURS = 6
NEVER = datetime.min.replace(tzinfo=dt_timezone.utc)


def _model():
    from ..models import CvSourceRead
    return CvSourceRead


# --- Queueing ------------------------------------------------------------------------------

def enqueue(asset):
    """The read of `asset`, queued if it has none yet.

    A file no CV reads is failed at once (`cv_file_kind`, or
    `cv_file_unreadable` for a protected PDF), so a customer never waits for
    it. With settings.LOCAL_SYNC_JOBS the file is read here and now.
    """
    CvSourceRead = _model()
    row = CvSourceRead.objects.filter(asset=asset).first()
    if row is not None:
        return row
    kind = sources.kind_of(asset)
    error = 'cv_file_kind' if kind is None else 'cv_file_unreadable' if asset.metadata.get('encrypted') else ''
    now = timezone.now()
    try:
        # A savepoint, so a read queued at the same moment elsewhere leaves the caller's transaction whole.
        with transaction.atomic():
            row = CvSourceRead.objects.create(account_id=asset.account_id, asset=asset, created_at=now,
                                              **({'status': FAILED, 'error': error, 'finished_at': now} if error else {}))
    except IntegrityError:
        return CvSourceRead.objects.get(asset=asset)
    if settings.LOCAL_SYNC_JOBS and row.status == QUEUED:
        taken = take(row)
        if taken is not None:
            perform(taken)
        row.refresh_from_db()
    return row


def ensure(account, assets, *, results=True):
    """Each of `assets`' reads by its file's id, queued for a file that has none (an upload from before the queue).

    `results` False leaves what the reads gave unloaded: their state is all the web asks about.
    """
    rows = _model().objects.filter(account=account, asset__in=[asset.pk for asset in assets])
    if not results:
        rows = rows.defer('encrypted_result')
    found = {str(row.asset_id): row for row in rows}
    for asset in assets:
        if str(asset.pk) not in found:
            found[str(asset.pk)] = enqueue(asset)
    return found


def ensure_ids(account, ids):
    """ensure() for the ids a request sends, before the request is made.

    A draft refused with `cv_reading` inside a transaction (update_draft, the
    bot's build) takes back a read it queued: queued here first, outside it,
    the read stays. Ids that name no live file of the account's are left for
    the request itself to refuse.
    """
    if not isinstance(ids, list):
        return {}
    known = []
    for value in ids[:50]:
        try:
            known.append(uuid.UUID(str(value)))
        except (TypeError, ValueError, AttributeError):
            continue
    from apps.core.models import FileAsset
    assets = list(FileAsset.objects.filter(account=account, id__in=known, state='ready', expires_at__gt=timezone.now()))
    return ensure(account, assets, results=False) if assets else {}


# --- The order of the queue ------------------------------------------------------------------

def fair_order(rows, served, now):
    """Queued reads in the order they will be read: aged reads first, oldest first, then the accounts in turn.

    `served` is when each account's last read began (None or missing for one
    never served); the account served longest ago goes first, and each takes
    one read a round. The same rule as apps/core/scheduling.select_outbox.
    """
    cutoff = now - timedelta(seconds=AGING_SECONDS)
    queues = defaultdict(deque)
    for row in sorted(rows, key=lambda row: (row.created_at, str(row.pk))):
        queues[row.account_id].append(row)

    def owner_order(owner):
        head = queues[owner][0]
        aged = head.created_at <= cutoff
        return (0 if aged else 1, head.created_at if aged else served.get(owner) or NEVER, head.created_at, str(owner))
    order = []
    while queues:
        for owner in sorted(queues, key=owner_order):
            order.append(queues[owner].popleft())
            if not queues[owner]:
                del queues[owner]
    return order


def queue(now=None):
    """(the queued reads in the order they will be read, how many are being read now)."""
    CvSourceRead = _model()
    now = now or timezone.now()
    rows = list(CvSourceRead.objects.filter(status=QUEUED).only('id', 'account_id', 'created_at')
                .order_by('created_at', 'id')[:WINDOW])
    owners = {row.account_id for row in rows}
    served = dict(CvSourceRead.objects.filter(account_id__in=owners, started_at__isnull=False).values('account_id')
                  .annotate(last=Max('started_at')).values_list('account_id', 'last'))
    reading = CvSourceRead.objects.filter(status=READING).count()
    return fair_order(rows, served, now), reading


def places(order, reading):
    """How many reads finish before each queued one: those being read, then those before it in turn."""
    return {row.pk: index + reading for index, row in enumerate(order)}


def ahead_of(row, place, beyond):
    """How many reads finish before `row`: 0 once it is being read; `beyond` for one past the window."""
    return place.get(row.pk, beyond) if row.status == QUEUED else 0


def estimate(ahead, reading, now=None):
    """About how many seconds until `ahead` reads and one more are done, from how long the latest took; None with none to go by.

    Readers side by side share the work: as many as are reading now.
    """
    now = now or timezone.now()
    spans = (_model().objects.filter(status__in=(DONE, FAILED), started_at__isnull=False,
                                     finished_at__gte=now - timedelta(hours=HISTORY_HOURS))
             .exclude(error='reader_interrupted').order_by('-finished_at')
             .values_list('started_at', 'finished_at')[:HISTORY])
    seconds = [max(0.0, (end - start).total_seconds()) for start, end in spans]
    if not seconds:
        return None
    return max(1, math.ceil(sum(seconds) / len(seconds) * (ahead + 1) / max(1, reading)))


def waiting(rows, now=None):
    """(ahead, estimated_seconds) for the last of `rows` to be read: how many reads finish before it, and about how long."""
    unfinished = [row for row in rows if row.status in WAITING]
    if not unfinished:
        return 0, 0
    order, reading = queue(now)
    place = places(order, reading)
    ahead = max(ahead_of(row, place, len(order) + reading) for row in unfinished)
    return ahead, estimate(ahead, reading, now)


def refusal(rows):
    """A draft whose files are still being read, refused until they are (`cv_reading`): never "try again"."""
    ahead, seconds = waiting(rows)
    return DomainError('cv_reading', 409, {'ahead': ahead, 'estimated_seconds': seconds}, retryable=True)


# --- Reading ---------------------------------------------------------------------------------

def take(row, now=None):
    """`row` taken for reading, if it is still queued: the row as taken, or None when another reader has it."""
    CvSourceRead = _model()
    now = now or timezone.now()
    taken = CvSourceRead.objects.filter(pk=row.pk, status=QUEUED).update(
        status=READING, started_at=now, lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
        attempts=F('attempts') + 1)
    return CvSourceRead.objects.select_related('asset').get(pk=row.pk) if taken else None


def claim(now=None):
    """The next read in turn, taken under a lease; None when nothing is queued.

    The candidates are locked SKIP LOCKED, so a second reader passes over the
    rows the first holds instead of waiting for them, and taken only while
    still queued (take): one read is never read twice at once.
    """
    CvSourceRead = _model()
    order, _ = queue(now)
    for start in range(0, len(order), CLAIM_BATCH):
        batch = order[start:start + CLAIM_BATCH]
        with transaction.atomic():
            free = set(CvSourceRead.objects.select_for_update(skip_locked=True)
                       .filter(pk__in=[row.pk for row in batch], status=QUEUED).values_list('pk', flat=True))
            for row in batch:
                if row.pk in free:
                    taken = take(row, now)
                    if taken is not None:
                        return taken
    return None


def sweep(now=None):
    """Reads whose reader stopped mid-read, their lease lapsed: queued again, or failed after MAX_ATTEMPTS. How many."""
    now = now or timezone.now()
    lapsed = _model().objects.filter(status=READING, lease_expires_at__lte=now)
    failed = lapsed.filter(attempts__gte=MAX_ATTEMPTS).update(status=FAILED, error='reader_interrupted',
                                                             finished_at=now, lease_expires_at=None)
    return failed + lapsed.filter(attempts__lt=MAX_ATTEMPTS).update(status=QUEUED, lease_expires_at=None)


def read_file(asset):
    """One file read in the bounded child: what it gave, as a draft takes it. DomainError when it could not be read.

    {'pages', 'names', 'ocr_pages', 'ocr_skipped'}: OCR reads at most
    sources.MAX_OCR_PAGES of its pages, which is all one draft may take of
    it, and the child has sources.READ_SECONDS. A file the reader ran out of
    time on is `read_timeout`, one it could not parse
    `source_extraction_failed`; neither is read again.
    """
    from apps.core import storage
    from ..extraction import read_cv
    path = storage.local(asset.object_key)
    if not path.is_file():
        raise DomainError('file_unavailable', 404)
    begun = time.monotonic()
    try:
        result = read_cv(path, sources.kind_of(asset), ocr_pages=sources.MAX_OCR_PAGES, seconds=sources.READ_SECONDS)
    except DomainError:
        raise DomainError('read_timeout' if time.monotonic() - begun >= sources.READ_SECONDS
                          else 'source_extraction_failed') from None
    return {'pages': [page for page in result['pages'] if isinstance(page, dict) and type(page.get('page')) is int],
            'names': [str(name)[:120] for name in result.get('names') or [] if isinstance(name, str)][:3],
            'ocr_pages': int(result.get('ocr_pages') or 0), 'ocr_skipped': int(result.get('ocr_skipped') or 0)}


def finish(row, status, *, result=None, error=''):
    """The read taken as `row` finished: done with what it gave, or failed with why. Whether it was kept.

    Not kept when the read was given up meanwhile (its lease lapsed and it
    was queued or taken again): the reader that has it now finishes it.
    """
    from ..domain import pack
    values = {'status': status, 'error': error[:40], 'finished_at': timezone.now(), 'lease_expires_at': None}
    if result is not None:
        values.update(encrypted_result=pack(result), ocr_pages=min(result['ocr_pages'], 32767),
                      pages=min(sum(1 for page in result['pages'] if str(page.get('text') or '').strip()), 32767))
    return bool(_model().objects.filter(pk=row.pk, status=READING, attempts=row.attempts).update(**values))


def perform(row):
    """The read taken as `row` read and finished (finish). Nothing of the file is logged: its text is the customer's."""
    asset = row.asset
    try:
        if asset.state != 'ready' or asset.expires_at <= timezone.now():
            raise DomainError('file_unavailable', 404)
        result = read_file(asset)
    except DomainError as exc:
        return finish(row, FAILED, error=exc.code)
    except Exception:
        logger.exception('A CV source file could not be read')
        return finish(row, FAILED, error='reader_error')
    return finish(row, DONE, result=result)


def next_read(now=None):
    """One turn of the reader: reads left by a stopped reader queued again, and the next in turn read. Whether one was."""
    sweep(now)
    row = claim(now)
    if row is None:
        return False
    perform(row)
    return True


def result_of(row):
    """What a done read gave, as sources.excerpts_of takes it; None for one that failed or is not done."""
    if row.status != DONE or not row.encrypted_result:
        return None
    from ..domain import unpack
    return unpack(row.encrypted_result)


# --- What the customer is told -----------------------------------------------------------------

def state(account, assets):
    """How the reading of these files is going, as GET /studio/cv-reads says it.

    {'reads': [{'asset_id', 'status', 'ahead', 'pages', 'ocr_pages', 'error'}],
    'ahead', 'estimated_seconds'}: `ahead` is the most reads that finish
    before any of them is read (0 when none waits), and `estimated_seconds`
    about how long until the last is read, 0 when none waits and None with no
    reads to tell it from. A file that has no read yet is queued.
    """
    rows = ensure(account, assets, results=False)
    order, reading = queue()
    place, beyond = places(order, reading), len(order) + reading
    listed = []
    for asset in assets:
        row = rows[str(asset.pk)]
        listed.append({'asset_id': str(asset.pk), 'status': row.status, 'ahead': ahead_of(row, place, beyond),
                       'pages': row.pages, 'ocr_pages': row.ocr_pages, 'error': row.error or None})
    unfinished = [entry['ahead'] for entry in listed if entry['status'] in WAITING]
    ahead = max(unfinished, default=0)
    return {'reads': listed, 'ahead': ahead, 'estimated_seconds': estimate(ahead, reading) if unfinished else 0}


def upload_state(asset):
    """The read an upload for a CV queued, as the upload's response says it: {'status', 'ahead', 'error'}."""
    row = enqueue(asset)
    ahead = 0
    if row.status == QUEUED:
        order, reading = queue()
        ahead = ahead_of(row, places(order, reading), len(order) + reading)
    return {'status': row.status, 'ahead': ahead, 'error': row.error or None}
