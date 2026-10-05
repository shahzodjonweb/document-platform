"""Is file storage working? Checked by the cleanup loop, told to the owner.

Every hour the bucket is asked to take, return and delete a small file, and
files still waiting for upload are watched: one that has waited longer than
BACKLOG_MINUTES means uploads are failing. When storage goes from working to
not working — or back — the owner gets one Telegram message, and the admin's
storage card shows what is wrong.
"""
import logging
import time
from datetime import datetime, timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

STATE_KEY = 'object_storage_health'
pause = time.sleep  # between the two canary tries; tests skip it
CANARY_MINUTES = 60
BACKLOG_MINUTES = 15
# English for the owner's Telegram alert; the admin shows its own translation.
PROBLEMS = {
    'canary_failed': 'File storage did not accept a test file.',
    'upload_backlog': '{waiting} files have waited more than {minutes} minutes to reach the bucket.',
}


def describe(problem):
    return PROBLEMS[problem['code']].format(**problem)


def state():
    from operations.models import IntegrationConfig
    row = IntegrationConfig.objects.filter(pk=STATE_KEY).first()
    return dict(row.configuration) if row else {}


def _save(values):
    from operations.models import IntegrationConfig
    IntegrationConfig.objects.update_or_create(key=STATE_KEY, defaults={'configuration': values})


def _canary(settings):
    """Two tries a few seconds apart, so one dropped connection is not an alarm."""
    from . import storage
    for attempt in range(2):
        try:
            storage.check(settings)
            return True
        except Exception:
            logger.warning('Object storage canary failed (attempt %s)', attempt + 1, exc_info=True)
            if attempt == 0:
                pause(5)
    return False


def monitor(now=None):
    """Check storage, remember the result, and alert on a change."""
    from . import storage
    from .models import StoredObject
    settings = storage.config()
    if not settings.get('ready'):
        return None
    now = now or timezone.now()
    current = state()
    problems = []
    last = current.get('canary_at')
    due = not last or now - datetime.fromisoformat(last) >= timedelta(minutes=CANARY_MINUTES)
    canary_ok = current.get('canary_ok', True)
    if due:
        canary_ok = _canary(settings)
        current.update(canary_at=now.isoformat(), canary_ok=canary_ok)
    if not canary_ok:
        problems.append({'code': 'canary_failed'})
    late = StoredObject.objects.filter(remote=False, created_at__lt=now - timedelta(minutes=BACKLOG_MINUTES))
    waiting = late.count()
    if waiting:
        problems.append({'code': 'upload_backlog', 'waiting': waiting, 'minutes': BACKLOG_MINUTES})
    healthy = not problems
    if current.get('healthy', True) != healthy:
        _alert(healthy, problems)
    current.update(healthy=healthy, problems=problems, checked_at=now.isoformat())
    _save(current)
    return current


def _alert(healthy, problems):
    from .models import StaffAlert
    if healthy:
        text = '✅ File storage is working again. Files are reaching the bucket.'
        kind = 'storage_recovered'
    else:
        text = '⚠️ File storage needs attention.\n' + '\n'.join(f'• {describe(p)}' for p in problems) + \
               '\nFiles are kept on the server meanwhile and uploaded once the bucket answers.\nAdmin → Integrations → File storage'
        kind = 'storage_failing'
    StaffAlert.objects.create(kind=kind, text=text)


def summary():
    """What the admin card shows."""
    from .models import StoredObject
    from django.db.models import Max, Min
    current = state()
    times = StoredObject.objects.aggregate(last_upload=Max('uploaded_at'))
    oldest = StoredObject.objects.filter(remote=False).aggregate(at=Min('created_at'))['at']
    return {'healthy': current.get('healthy', True), 'problems': current.get('problems', []),
            'canary_at': current.get('canary_at'), 'canary_ok': current.get('canary_ok'),
            'checked_at': current.get('checked_at'), 'last_upload': times['last_upload'], 'oldest_waiting': oldest}
