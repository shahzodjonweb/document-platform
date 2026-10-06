"""Storage probes use retained own canaries and never remove working copies."""
import hashlib
import importlib.util
from pathlib import Path
import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core import storage
from apps.core.models import Account, FileAsset, StoredObject
from operations.integrations import save_config
from tests.test_object_storage import FakeS3, KEYS


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/operations/service_checks_storage.py'
spec = importlib.util.spec_from_file_location('pdfmaster_storage_service_checks', SCRIPT)
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)
pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def canaries(monkeypatch):
    audit = uuid.uuid4()
    identifier = uuid.uuid5(uuid.NAMESPACE_URL, checks.NAMESPACE + str(audit))
    account = Account.objects.create(
        pk=identifier, is_test=True, display_name=checks.PREFIX + audit.hex)
    bucket = FakeS3()
    monkeypatch.setattr(storage, 'client_factory', lambda settings: bucket)
    save_config('object_storage', {**KEYS, 'enabled': 'true'})
    assets = []
    for index in range(4):
        payload = f'Unique retained canary {index}'.encode()
        key = f'inputs/{account.id}/{uuid.uuid4().hex}.png'
        path = storage.storage_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        asset = FileAsset.objects.create(
            account=account, name=f'canary-{index}.png', object_key=key,
            mime_type='image/png', sha256=hashlib.sha256(payload).hexdigest(),
            size_bytes=len(payload), page_count=1, expires_at=timezone.now() + timedelta(hours=24))
        storage.save(key, asset.mime_type)
        assert StoredObject.objects.get(key=key).remote
        assets.append(asset)
    context = {'audit_id': str(audit), 'account_id': str(account.id)}
    return account, bucket, assets, context


def test_fetch_back_reads_bucket_into_private_cache_and_keeps_real_copies(canaries, monkeypatch, capsys):
    account, bucket, assets, context = canaries
    resolver = storage.storage_path
    originals = {asset.object_key: resolver(asset.object_key).read_bytes() for asset in assets}
    destinations = []
    original_get = storage.Bucket.get

    def record_get(self, key, path):
        destinations.append(Path(path))
        assert key in originals
        assert not path.is_relative_to(resolver(key).parents[2])
        return original_get(self, key, path)

    monkeypatch.setattr(storage.Bucket, 'get', record_get)
    result = checks.check_fetch_back(context)
    assert result == {'status': 'passed', 'scope': 'owned_canary_private_cache',
                      'fetched': 3, 'matched': 3, 'missing': 0,
                      'size_mismatch': 0, 'checksum_mismatch': 0}
    assert storage.storage_path is resolver
    assert all(resolver(key).read_bytes() == payload for key, payload in originals.items())
    assert len(destinations) == 3 and not any(path.exists() for path in destinations)
    assert not capsys.readouterr().out


@pytest.mark.parametrize('field,value', [
    ('is_test', False), ('display_name', 'Ordinary customer'),
    ('email', 'real@example.test'), ('telegram_user_id', 0),
    ('google_sub', 'customer-google-identity'), ('password_hash', 'customer-password-hash'),
])
def test_scope_guard_refuses_real_or_misidentified_accounts(canaries, monkeypatch, field, value):
    account, bucket, assets, context = canaries
    Account.objects.filter(pk=account.pk).update(**{field: value})
    monkeypatch.setattr(storage, 'local', lambda key: pytest.fail('Scope failure must not read any file'))
    assert checks.check_fetch_back(context)['status'] == 'failed'


def test_scope_guard_refuses_foreign_account_and_malformed_audit(canaries, monkeypatch):
    account, bucket, assets, context = canaries
    monkeypatch.setattr(storage, 'local', lambda key: pytest.fail('Scope failure must not read any file'))
    for invalid in ({}, {**context, 'account_id': str(uuid.uuid4())},
                    {**context, 'audit_id': 'invalid'}, {**context, 'audit_id': None}):
        assert checks.check_fetch_back(invalid)['status'] == 'failed'


def test_expired_cleanup_canary_is_excluded_and_foreign_files_are_not_fetched(canaries, monkeypatch):
    account, bucket, assets, context = canaries
    FileAsset.objects.filter(pk=assets[0].pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    expected = {asset.object_key for asset in assets[1:]}
    foreign = Account.objects.create(is_test=True, display_name='Another audit')
    FileAsset.objects.filter(pk=assets[0].pk).update(account=foreign)
    fetched = []
    original_local = storage.local

    def record_local(key):
        assert key in expected
        fetched.append(key)
        return original_local(key)

    monkeypatch.setattr(storage, 'local', record_local)
    assert checks.check_fetch_back(context)['status'] == 'passed'
    assert set(fetched) == expected


def test_fewer_than_three_retained_remote_fixtures_fail_before_any_reads(canaries, monkeypatch):
    account, bucket, assets, context = canaries
    FileAsset.objects.filter(pk__in=[assets[0].pk, assets[1].pk]).update(
        expires_at=timezone.now() + timedelta(minutes=5))
    monkeypatch.setattr(storage, 'local', lambda key: pytest.fail('Insufficient fixtures must not read any file'))
    result = checks.check_fetch_back(context)
    assert result['status'] == 'failed' and result['missing'] == 1 and result['fetched'] == 0


@pytest.mark.parametrize('damage,field', [
    ('missing', 'missing'), ('size', 'size_mismatch'), ('checksum', 'checksum_mismatch')])
def test_fetch_failures_have_distinct_counts_and_restore_resolver(canaries, capsys, damage, field):
    account, bucket, assets, context = canaries
    key = ('pdfmaster', assets[0].object_key)
    if damage == 'missing':
        bucket.objects.pop(key)
    elif damage == 'size':
        bucket.objects[key]['data'] = b'short'
    else:
        before = bucket.objects[key]['data']
        bucket.objects[key]['data'] = b'X' * len(before)
    resolver = storage.storage_path
    logging = storage.logger.disabled
    result = checks.check_fetch_back(context)
    assert result['status'] == 'failed' and result[field] == 1 and result['matched'] == 2
    assert result['fetched'] == (2 if damage == 'missing' else 3)
    assert storage.storage_path is resolver and storage.logger.disabled is logging
    assert not capsys.readouterr().err
    assert resolver(assets[0].object_key).is_file()


def test_unexpected_fetch_exception_restores_private_cache_override(canaries, monkeypatch, capsys):
    account, bucket, assets, context = canaries
    resolver = storage.storage_path
    logging = storage.logger.disabled

    def fail(key):
        raise RuntimeError('fixture-private-storage-secret')

    monkeypatch.setattr(storage, 'local', fail)
    result = checks.check_fetch_back(context)
    assert result['status'] == 'failed' and result['missing'] == 3
    assert storage.storage_path is resolver and storage.logger.disabled is logging
    output = capsys.readouterr()
    assert 'fixture-private-storage-secret' not in output.out + output.err
