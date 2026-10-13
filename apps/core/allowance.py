"""Weekly limits, counted from the jobs an account has started.

There are no credits to spend. Each plan has a number of AI documents and of
file tasks a week, and a number of AI edits for each generated file
(docs/product/plan_seed.json; null is unlimited, and the admin panel can change
any of them). A job counts from the moment it is submitted, so two quick
submissions cannot both see room for one more; one that failed, was cancelled,
expired or produced nothing gives its place back; and a replayed submission
returns the job it already made, so nothing is counted twice.

A week starts on Monday at 00:00 in Tashkent, for everyone. It is a fixed zone
rather than the account's own: an account can change its time zone, and a week
that moved with it could be started again at will. The customer still sees the
reset time in their own zone.
"""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from .errors import DomainError
from .models import Job

WEEK_ZONE = ZoneInfo('Asia/Tashkent')
# Jobs that produced nothing do not use up a week's allowance.
NOT_COUNTED = ('failed', 'canceled', 'expired', 'no_op')
LIMIT_CODES = ('weekly_ai_limit', 'weekly_file_limit', 'edit_limit')


def _generation_ids():
    # Imported late: the studio imports core, never the other way round.
    from apps.studio.domain import GENERATION_IDS
    return GENERATION_IDS


def week_bounds(now=None):
    """The current week: (Monday 00:00 Tashkent, the next Monday 00:00), both time-zone aware."""
    local = (now or timezone.now()).astimezone(WEEK_ZONE)
    monday = datetime.combine((local - timedelta(days=local.weekday())).date(), time.min, tzinfo=WEEK_ZONE)
    return monday, monday + timedelta(days=7)


def _counted(account, start, end):
    return (Job.objects.filter(account=account, created_at__gte=start, created_at__lt=end)
            .exclude(status__in=NOT_COUNTED))


def ai_documents_this_week(account, now=None):
    """AI documents and decks started this week. An outline is a step towards a
    document, not one, and an edit is counted per file instead (edits_of)."""
    start, end = week_bounds(now)
    rows = (_counted(account, start, end).filter(feature_id__in=_generation_ids())
            .values_list('parameters', flat=True))
    return sum(1 for parameters in rows
               if (parameters or {}).get('stage') != 'outline' and not (parameters or {}).get('revision'))


def file_jobs_this_week(account, now=None):
    """File tasks started this week: every tool that is not AI generation.

    A confirmed batch holds a place for each of its files from the moment it is
    confirmed, although its children become jobs one at a time.
    """
    start, end = week_bounds(now)
    jobs = _counted(account, start, end).exclude(feature_id__in=_generation_ids()).count()
    return jobs + _waiting_items().filter(run__account=account).count()


def _waiting_items():
    """Files of a confirmed batch that hold a place and are not jobs yet.

    Only files not yet tried: one that failed before it became a job (its quote
    expired, its file changed) made nothing and gives its place back while the
    rest of the run waits. A waiting file holds its place in whichever week it
    is still waiting, not only the week its batch was confirmed in; once it
    runs, its job is counted in the week it was started.
    """
    from apps.studio.batch_models import BatchItem
    return BatchItem.objects.filter(status='pending', job__isnull=True, run__status__in=('queued', 'running'))


def edits_of(account, root_draft_id):
    """AI edits made to one generated file, over its whole life (a draft lives a day)."""
    if not root_draft_id:
        return 0
    return (Job.objects.filter(account=account, feature_id__in=_generation_ids(), parameters__revision=True,
                               parameters__root_draft_id=str(root_draft_id))
            .exclude(status__in=NOT_COUNTED).count())


def file_made(account, draft_id):
    """Whether an AI document or deck was actually made from this draft.

    An outline is a plan, not a file. A finished edit is a made file too: an
    edit asked for before roots were recorded is counted against the edit it
    changed (apps.studio.domain.edit_root), and that edit is what was made.
    """
    if not draft_id:
        return False
    rows = (Job.objects.filter(account=account, feature_id__in=_generation_ids(), status='succeeded',
                               parameters__generation_draft_id=str(draft_id))
            .values_list('parameters', flat=True))
    return any((parameters or {}).get('stage') != 'outline' for parameters in rows)


def require_made(account, root_draft_id):
    """Refuse an edit of a draft that no file was made from (revision_not_ready).

    An edit is counted against its file's edits, not the week's documents, so
    "editing" a draft that was never generated — a new one holds its source
    text already — would make a whole new document outside the week's limit,
    again and again. A plan without a weekly limit may make as many documents
    as it likes, so there the same request gains nothing and is let through.
    """
    if _limit(account, 'weekly_ai_documents') is None:
        return
    if not file_made(account, root_draft_id):
        raise DomainError('revision_not_ready')


def _limit(account, key):
    from .policy import plan_limits
    return plan_limits(account).get(key)


def require_ai_document(account):
    limit = _limit(account, 'weekly_ai_documents')
    if limit is None:
        return
    used = ai_documents_this_week(account)
    if used >= limit:
        raise DomainError('weekly_ai_limit', 429, {'limit': limit, 'used': used, 'resets_at': week_bounds()[1].isoformat()})


def require_file_jobs(account, count=1):
    limit = _limit(account, 'weekly_file_jobs')
    if limit is None:
        return
    used = file_jobs_this_week(account)
    if used + count > limit:
        raise DomainError('weekly_file_limit', 429, {'limit': limit, 'used': used, 'requested': count,
                                                    'resets_at': week_bounds()[1].isoformat()})


def require_edit(account, root_draft_id):
    limit = _limit(account, 'edits_per_file')
    if limit is None:
        return
    used = edits_of(account, root_draft_id)
    if used >= limit:
        raise DomainError('edit_limit', 429, {'limit': limit, 'used': used})


def quote_kind(quote):
    """'file', 'ai_document', 'outline' or 'edit' — which allowance a quote draws on."""
    if quote.feature_id not in _generation_ids():
        return 'file'
    parameters = quote.parameters or {}
    if parameters.get('revision'):
        return 'edit'
    return 'outline' if parameters.get('stage') == 'outline' else 'ai_document'


def _holds_place(quote):
    """Whether this quote is a file of a confirmed batch, whose place was taken
    when the batch was confirmed (file_jobs_this_week counts it already)."""
    if getattr(quote, 'pk', None) is None:
        return False
    return _waiting_items().filter(quote_id=quote.pk).exists()


def require_quote(account, quote, count=1):
    """Refuse a quote whose allowance is used up. An outline is checked but never
    counted, so a week's last document can still be planned before it is made."""
    kind = quote_kind(quote)
    if kind == 'edit':
        root = (quote.parameters or {}).get('root_draft_id')
        # Asked again here, under the account lock on submission. The draft was
        # checked when it was made, but one made before that check existed was
        # not, and a selected-page edit saved again keeps its snapshot without
        # looking at its document a second time. A quote that names no file was
        # priced before files were named; its old policy version refuses it
        # (quote_policy_changed), which asks for a fresh look rather than
        # telling the customer their file was never made.
        if root:
            require_made(account, root)
        require_edit(account, root)
    elif kind in ('ai_document', 'outline'):
        require_ai_document(account)
    elif not _holds_place(quote):
        require_file_jobs(account, count)


def _block(limit, used):
    return {'limit': limit, 'used': used, 'remaining': None if limit is None else max(0, limit - used)}


def usage_snapshot(account, now=None):
    from .policy import plan_limits
    limits = plan_limits(account)
    start, end = week_bounds(now)
    return {'plan': account.plan,
            'week': {'starts_at': start, 'resets_at': end, 'time_zone': 'Asia/Tashkent'},
            'ai_documents': _block(limits.get('weekly_ai_documents'), ai_documents_this_week(account, now)),
            'file_jobs': _block(limits.get('weekly_file_jobs'), file_jobs_this_week(account, now)),
            'edits_per_file': limits.get('edits_per_file'),
            'resets_at': end}
