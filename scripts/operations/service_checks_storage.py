"""Fetch only this audit's retained synthetic files into a private cache.

The real working copies stay untouched. Expired cleanup canaries and unrelated
accounts never enter the selection, so the normal cleanup sweep cannot turn an
expected deletion into a reported checksum failure.
"""
import hashlib
from pathlib import Path
import tempfile
import uuid
from datetime import timedelta

from django.utils import timezone

from apps.core import storage
from apps.core.models import Account, FileAsset, StoredObject


PREFIX = 'Background service verification '
NAMESPACE = 'https://pdfmaster.orderdesk.live/background-service-check/'
COUNT = 3


def check_fetch_back(context):
    result = {'status': 'failed', 'scope': 'owned_canary_private_cache',
              'fetched': 0, 'matched': 0, 'missing': 0,
              'size_mismatch': 0, 'checksum_mismatch': 0}
    try:
        audit_id = uuid.UUID(str(context['audit_id']))
        expected_id = uuid.uuid5(uuid.NAMESPACE_URL, NAMESPACE + str(audit_id))
        if uuid.UUID(str(context['account_id'])) != expected_id:
            return result
        account = Account.objects.filter(pk=expected_id, is_test=True).first()
        if (not account or account.display_name != PREFIX + audit_id.hex
                or account.email or account.telegram_user_id is not None
                or account.google_sub or account.password_hash):
            return result
    except (KeyError, ValueError, TypeError, AttributeError):
        return result

    now = timezone.now()
    remote = StoredObject.objects.filter(remote=True).values('key')
    assets = list(FileAsset.objects.filter(
        account=account, state='ready', expires_at__gt=now + timedelta(minutes=10),
        object_key__in=remote).order_by('created_at', 'id')[:COUNT])
    if len(assets) != COUNT:
        result['missing'] = COUNT - len(assets)
        return result

    original_resolver = storage.storage_path
    original_logging = storage.logger.disabled
    with tempfile.TemporaryDirectory(prefix='pdfmaster-owned-storage-check-') as directory:
        private = {asset.object_key: Path(directory) / f'canary-{index:02d}'
                   for index, asset in enumerate(assets)}

        def cache_path(key):
            if key not in private:
                raise ValueError('Storage verification requested an unrelated key')
            return private[key]

        # This helper runs in its own Django shell audit process. Its resolver
        # override does not affect the API, cleanup daemon or worker processes.
        storage.storage_path = cache_path
        storage.logger.disabled = True
        try:
            for asset in assets:
                try:
                    path = storage.local(asset.object_key)
                    if path != private[asset.object_key] or not path.is_file():
                        result['missing'] += 1
                        continue
                    result['fetched'] += 1
                    if path.stat().st_size != asset.size_bytes:
                        result['size_mismatch'] += 1
                        continue
                    checksum = hashlib.sha256()
                    with path.open('rb') as source:
                        for chunk in iter(lambda: source.read(1024 * 1024), b''):
                            checksum.update(chunk)
                    if checksum.hexdigest() != asset.sha256:
                        result['checksum_mismatch'] += 1
                        continue
                    result['matched'] += 1
                except Exception:
                    # SDK errors may include endpoints and credentials. Counts
                    # are enough for the audit; no exception details are emitted.
                    result['missing'] += 1
        finally:
            storage.storage_path = original_resolver
            storage.logger.disabled = original_logging
    if result['fetched'] == COUNT and result['matched'] == COUNT:
        result['status'] = 'passed'
    return result
