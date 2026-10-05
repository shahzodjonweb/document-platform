"""Where the platform's files live.

With object storage connected (Admin → Integrations), every file — uploads,
task results, page previews, payment receipts, AI review copies — is kept in
the bucket, and the database holds only its key. The shared volume keeps a
working copy while something needs the bytes on disk (the document engines
work on files), and lets it go once it has sat unused for a while.

Without object storage the volume is where files live, exactly as before.

Writing never waits on the bucket inside a database transaction: a file is
registered first and uploaded once the transaction commits. If the bucket
cannot be reached, the file stays on the volume and the cleanup loop uploads
it later — the same sync that moves files kept on the volume before object
storage was connected.
"""
import logging
import os
import shutil
import time
from datetime import timedelta
from pathlib import Path

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

# Prefixes this module manages in the bucket; the sweep touches nothing else.
PREFIXES = ('inputs/', 'outputs/', 'previews/', 'receipts/', 'review/')
WORKING_COPY_HOURS = 2
CONFIG_SECONDS = 30
_config_cache = {'at': 0.0, 'value': None}
# Tests put a fake bucket here.
client_factory = None


def storage_path(key):
    from .services import storage_path as resolve
    return resolve(key)


def config():
    """The object storage settings, read at most every CONFIG_SECONDS per process."""
    now = time.monotonic()
    if _config_cache['value'] is None or now - _config_cache['at'] > CONFIG_SECONDS:
        try:
            from operations.integrations import object_storage_config
            _config_cache['value'] = object_storage_config()
        except Exception:
            logger.exception('Could not read the object storage settings')
            _config_cache['value'] = {'enabled': False, 'configured': False, 'ready': False}
        _config_cache['at'] = now
    return _config_cache['value']


def forget_config():
    _config_cache['value'] = None
    _buckets.clear()


class Bucket:
    """The few S3 calls the platform makes, against one bucket."""

    def __init__(self, settings):
        self.name = settings['bucket']
        if client_factory:
            self.client = client_factory(settings)
            return
        import boto3
        from botocore.config import Config
        self.client = boto3.client(
            's3', endpoint_url=settings['endpoint'], region_name=settings.get('region') or None,
            aws_access_key_id=settings['access_key'], aws_secret_access_key=settings['secret_key'],
            config=Config(signature_version='s3v4', s3={'addressing_style': 'path'},
                          retries={'max_attempts': 4, 'mode': 'standard'},
                          connect_timeout=10, read_timeout=120))

    def put(self, key, path, content_type=''):
        """Upload one file. The bucket refuses it unless the bytes it received
        match the MD5 sent with them, and the ETag it returns is checked too."""
        import base64
        import hashlib
        digest = hashlib.md5(usedforsecurity=False)
        with open(path, 'rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        extra = {'ContentType': content_type} if content_type else {}
        with open(path, 'rb') as source:
            response = self.client.put_object(Bucket=self.name, Key=key, Body=source,
                                              ContentMD5=base64.b64encode(digest.digest()).decode(), **extra)
        etag = str((response or {}).get('ETag', '')).strip('"')
        if len(etag) == 32 and etag != digest.hexdigest():
            raise IOError(f'Object storage stored different bytes for {key}')

    def get(self, key, path):
        response = self.client.get_object(Bucket=self.name, Key=key)
        expected, written = response.get('ContentLength'), 0
        with open(path, 'wb') as target:
            for chunk in iter(lambda: response['Body'].read(1024 * 1024), b''):
                target.write(chunk)
                written += len(chunk)
        if expected is not None and written != expected:
            raise IOError(f'Object storage returned {written} of {expected} bytes for {key}')

    def delete(self, key):
        self.client.delete_object(Bucket=self.name, Key=key)

    def listing(self, prefix):
        token = None
        while True:
            page = self.client.list_objects_v2(Bucket=self.name, Prefix=prefix,
                                               **({'ContinuationToken': token} if token else {}))
            yield from page.get('Contents', [])
            if not page.get('IsTruncated'):
                return
            token = page.get('NextContinuationToken')


_buckets = {}


def bucket(for_writing=True):
    """The bucket to use, or None. Reading works whenever credentials are saved,
    so switching uploads off never strands files already in the bucket."""
    import hashlib
    settings = config()
    if not settings.get('configured') or (for_writing and not settings.get('ready')):
        return None
    fingerprint = hashlib.sha256(repr(sorted((k, str(v)) for k, v in settings.items())).encode()).hexdigest()
    if client_factory or fingerprint not in _buckets:
        made = Bucket(settings)
        if client_factory:
            return made
        _buckets.clear()
        _buckets[fingerprint] = made
    return _buckets[fingerprint]


def save(key, content_type=''):
    """Register a file just written at its key, and send it to the bucket."""
    from .models import StoredObject
    path = storage_path(key)
    StoredObject.objects.update_or_create(key=key, defaults={
        'size': path.stat().st_size, 'content_type': content_type, 'remote': False,
        'uploaded_at': None, 'used_at': timezone.now()})
    transaction.on_commit(lambda: upload(key))


def upload(key):
    """Send one registered file to the bucket; on failure the sync tries again."""
    from .models import StoredObject
    target = bucket()
    row = StoredObject.objects.filter(key=key).first()
    path = storage_path(key)
    if not target or not row or row.remote or not path.is_file():
        return False
    try:
        target.put(key, path, row.content_type)
    except Exception:
        logger.warning('Upload of %s to object storage failed; the sync will retry', key, exc_info=True)
        return False
    StoredObject.objects.filter(key=key).update(remote=True, uploaded_at=timezone.now())
    return True


def local(key):
    """A path on the volume holding the file, fetched from the bucket if needed.

    The path is returned even when the file is gone everywhere; callers check
    `is_file()` as they always have.
    """
    from .models import StoredObject
    path = storage_path(key)
    now = timezone.now()
    if path.is_file():
        StoredObject.objects.filter(key=key, used_at__lt=now - timedelta(minutes=10)).update(used_at=now)
        return path
    row = StoredObject.objects.filter(key=key, remote=True).first()
    source = bucket(for_writing=False) if row else None
    if not source:
        return path
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    partial = path.with_name(f'.{path.name}.{os.getpid()}.part')
    try:
        source.get(key, partial)
        os.chmod(partial, 0o600)
        os.replace(partial, path)
    except Exception:
        partial.unlink(missing_ok=True)
        logger.warning('Could not fetch %s from object storage', key, exc_info=True)
        return path
    StoredObject.objects.filter(key=key).update(used_at=now)
    return path


def read_bytes(key):
    return local(key).read_bytes()


def exists(key):
    from .models import StoredObject
    return storage_path(key).is_file() or StoredObject.objects.filter(key=key, remote=True).exists()


def delete(key):
    """Remove a file everywhere. A bucket copy that cannot be removed now is
    caught by the sweep, which deletes objects no row refers to."""
    from .models import StoredObject
    if not key:
        return
    storage_path(key).unlink(missing_ok=True)
    row = StoredObject.objects.filter(key=key).first()
    if row and row.remote:
        target = bucket(for_writing=False)
        if target:
            try:
                target.delete(key)
            except Exception:
                logger.warning('Could not delete %s from object storage; the sweep will', key, exc_info=True)
    StoredObject.objects.filter(key=key).delete()


def delete_prefix(prefix):
    from .models import StoredObject
    for key in list(StoredObject.objects.filter(key__startswith=prefix).values_list('key', flat=True)):
        delete(key)
    shutil.rmtree(storage_path(prefix.rstrip('/')), ignore_errors=True)


def _legacy_keys():
    """Files kept on the volume from before object storage, by the records that use them."""
    from apps.commerce.models import ManualPayment
    from apps.studio.models import GenerationRecord
    from .models import FileAsset
    yield from FileAsset.objects.filter(state='ready', expires_at__gt=timezone.now()).values_list('object_key', 'mime_type')
    yield from ((k, '') for k in ManualPayment.objects.exclude(receipt_key='').values_list('receipt_key', flat=True))
    yield from GenerationRecord.objects.exclude(output_key='').values_list('output_key', 'output_mime')


def sync(limit=500):
    """Upload what is not in the bucket yet; returns how many arrived."""
    from .models import StoredObject
    try:
        if not bucket():
            return 0
    except Exception:
        logger.warning('Object storage is not usable; files stay on the volume', exc_info=True)
        return 0
    known = set(StoredObject.objects.values_list('key', flat=True))
    for key, content_type in _legacy_keys():
        if key and key not in known:
            path = storage_path(key)
            if path.is_file():
                StoredObject.objects.get_or_create(key=key, defaults={'size': path.stat().st_size,
                                                                      'content_type': content_type or ''})
                known.add(key)
    sent = 0
    for key in StoredObject.objects.filter(remote=False).order_by('created_at').values_list('key', flat=True)[:limit]:
        sent += upload(key)
    return sent


def evict(now=None, hours=WORKING_COPY_HOURS):
    """Let go of working copies that are safe in the bucket and unused for a while."""
    from .models import StoredObject
    if not bucket(for_writing=False):
        return 0
    now = now or timezone.now()
    gone = 0
    for key in StoredObject.objects.filter(remote=True, used_at__lt=now - timedelta(hours=hours)).values_list('key', flat=True).iterator():
        path = storage_path(key)
        if path.is_file():
            path.unlink(missing_ok=True)
            gone += 1
    return gone


def sweep(now=None, grace=timedelta(hours=24)):
    """Delete bucket objects no row refers to, once they are old enough that no
    upload can still be on its way. Only this module's prefixes are touched."""
    from .models import StoredObject
    target = bucket(for_writing=False)
    if not target:
        return 0
    now = now or timezone.now()
    removed = 0
    for prefix in PREFIXES:
        for item in target.listing(prefix):
            key = item['Key']
            if item['LastModified'] > now - grace or StoredObject.objects.filter(key=key).exists():
                continue
            try:
                target.delete(key)
                removed += 1
            except Exception:
                logger.warning('Sweep could not delete %s', key, exc_info=True)
    return removed


def unreferenced(keys):
    """Which of these stored files no record uses any more."""
    from apps.commerce.models import ManualPayment
    from apps.studio.models import GenerationRecord
    from .models import FileAsset
    keys = list(keys)
    used = set(FileAsset.objects.filter(object_key__in=keys).values_list('object_key', flat=True))
    used |= set(ManualPayment.objects.filter(receipt_key__in=keys).values_list('receipt_key', flat=True))
    records = {key: key.split('/')[2] for key in keys if key.startswith('review/') and len(key.split('/')) > 2}
    alive = {str(pk) for pk in GenerationRecord.objects.filter(pk__in=set(records.values())).values_list('pk', flat=True)} if records else set()
    used |= {key for key, record in records.items() if record in alive}
    return [key for key in keys if key not in used]


def prune(now=None, grace=timedelta(hours=24), batch=500):
    """Delete stored files no record uses, once they are a day old (so a file
    written just before its record is committed is never taken)."""
    from .models import StoredObject
    now = now or timezone.now()
    removed = 0
    old = StoredObject.objects.filter(created_at__lt=now - grace).order_by('key').values_list('key', flat=True)
    start = ''
    while True:
        keys = list(old.filter(key__gt=start)[:batch])
        if not keys:
            return removed
        for key in unreferenced(keys):
            delete(key)
            removed += 1
        start = keys[-1]


_last_sweep = {'at': 0.0}
SWEEP_SECONDS = 3600


def sweep_if_due(now=None):
    """The sweep lists the whole bucket, so the cleanup loop runs it hourly."""
    moment = time.monotonic()
    if _last_sweep['at'] and moment - _last_sweep['at'] < SWEEP_SECONDS:
        return 0
    _last_sweep['at'] = moment
    try:
        return sweep(now)
    except Exception:
        logger.warning('Object storage sweep failed', exc_info=True)
        return 0


def health():
    """Counts for the admin page."""
    from django.db.models import Count, Sum
    from .models import StoredObject
    totals = {row['remote']: row for row in StoredObject.objects.values('remote').annotate(n=Count('key'), bytes=Sum('size'))}
    there, waiting = totals.get(True, {}), totals.get(False, {})
    return {'remote_files': there.get('n', 0), 'remote_bytes': there.get('bytes') or 0,
            'waiting_files': waiting.get('n', 0), 'waiting_bytes': waiting.get('bytes') or 0}


def check(settings):
    """Write, read back and delete a small object with these settings."""
    import tempfile
    import uuid
    target = Bucket(settings)
    key = f'healthcheck/{uuid.uuid4().hex}.txt'
    payload = b'PDF Master storage check'
    with tempfile.TemporaryDirectory() as scratch:
        source, back = Path(scratch) / 'out.txt', Path(scratch) / 'in.txt'
        source.write_bytes(payload)
        target.put(key, source, 'text/plain')
        try:
            target.get(key, back)
            if back.read_bytes() != payload:
                raise ValueError('The object read back differs from the one written.')
        finally:
            target.delete(key)
