"""Files kept in the object storage bucket, with only their keys in the database."""
import io
from datetime import timedelta

import pytest
from django.utils import timezone
from pypdf import PdfReader

from apps.core import storage
from apps.core.errors import DomainError
from apps.core.models import FileAsset, StoredObject
from apps.core.services import cleanup_expired, create_quote, execute_job, storage_path, submit_job
from operations.integrations import object_storage_config, save_config
from operations.integrations import test_object_storage as check_connection
from tests.test_platform import account, upload

pytestmark = pytest.mark.django_db(transaction=True)
KEYS = {'access_key': 'FAKEACCESSKEY123', 'secret_key': 'fake/secret+key=0123456789abcdef'}


class FakeBody:
    def __init__(self, data):
        self.stream = io.BytesIO(data)

    def read(self, size=-1):
        return self.stream.read(size)


class FakeS3:
    """The bucket, in memory: the five calls the platform makes."""

    def __init__(self):
        self.objects, self.failing, self.corrupt, self.truncate = {}, False, False, False

    def put_object(self, Bucket, Key, Body, **extra):
        import base64
        import hashlib
        if self.failing:
            raise ConnectionError('bucket unreachable')
        data = Body.read()
        if 'ContentMD5' in extra and base64.b64decode(extra['ContentMD5']) != hashlib.md5(data).digest():
            raise ValueError('BadDigest')
        self.objects[(Bucket, Key)] = {'data': data, 'at': timezone.now(), **extra}
        return {'ETag': '"%s"' % (hashlib.md5(b'other' if self.corrupt else data).hexdigest())}

    def get_object(self, Bucket, Key):
        data = self.objects[(Bucket, Key)]['data']
        return {'Body': FakeBody(data[:-10] if self.truncate else data), 'ContentLength': len(data)}

    def delete_object(self, Bucket, Key):
        self.objects.pop((Bucket, Key), None)

    def list_objects_v2(self, Bucket, Prefix, **kwargs):
        return {'Contents': [{'Key': key, 'LastModified': item['at']} for (bucket, key), item in self.objects.items()
                             if bucket == Bucket and key.startswith(Prefix)], 'IsTruncated': False}

    def keys(self):
        return {key for _, key in self.objects}


@pytest.fixture
def bucket():
    fake = FakeS3()
    storage.client_factory = lambda settings: fake
    save_config('object_storage', {**KEYS, 'enabled': 'true'})
    return fake


def evict_now():
    StoredObject.objects.update(used_at=timezone.now() - timedelta(hours=storage.WORKING_COPY_HOURS + 1))
    storage.evict()


def test_without_object_storage_files_stay_on_the_server_as_before():
    asset = upload(account())
    assert storage_path(asset.object_key).is_file()
    assert StoredObject.objects.get(key=asset.object_key).remote is False
    assert storage.sync() == 0 and storage.evict() == 0


def test_an_upload_lands_in_the_bucket_and_the_database_keeps_only_its_key(bucket):
    asset = upload(account())
    row = StoredObject.objects.get(key=asset.object_key)
    assert row.remote and asset.object_key in bucket.keys()
    assert bucket.objects[('pdfmaster', asset.object_key)]['data'] == storage_path(asset.object_key).read_bytes()
    assert bucket.objects[('pdfmaster', asset.object_key)]['ContentType'] == 'application/pdf'


def test_a_working_copy_is_let_go_and_fetched_back_when_needed(bucket):
    asset = upload(account())
    original = storage_path(asset.object_key).read_bytes()
    evict_now()
    assert not storage_path(asset.object_key).exists(), 'only the bucket holds it now'
    assert storage.read_bytes(asset.object_key) == original


def test_a_task_runs_on_inputs_that_live_only_in_the_bucket(bucket):
    customer = account()
    first, second = upload(customer, widths=(210,)), upload(customer, name='two.pdf', widths=(310, 410))
    evict_now()
    quote = create_quote(customer, 'pdf.merge', [str(first.id), str(second.id)], {})
    job, _ = submit_job(customer, quote.id, 'bucket-merge-1')
    done = execute_job(job.id)
    assert done.status == 'succeeded', done.error_code
    result = done.artifacts.get().file
    assert result.object_key in bucket.keys() and StoredObject.objects.get(key=result.object_key).remote
    evict_now()
    pages = PdfReader(storage.local(result.object_key)).pages
    assert [float(p.mediabox.width) for p in pages] == [210, 310, 410]


def test_an_expired_file_leaves_the_bucket(bucket):
    asset = upload(account())
    FileAsset.objects.filter(pk=asset.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    cleanup_expired()
    assert asset.object_key not in bucket.keys() and not StoredObject.objects.filter(key=asset.object_key).exists()


def test_when_the_bucket_is_down_the_file_waits_on_the_server_and_goes_up_later(bucket):
    bucket.failing = True
    asset = upload(account())
    assert storage_path(asset.object_key).is_file() and not StoredObject.objects.get(key=asset.object_key).remote
    evict_now()
    assert storage_path(asset.object_key).is_file(), 'never let go of the only copy'
    bucket.failing = False
    cleanup_expired()
    assert StoredObject.objects.get(key=asset.object_key).remote and asset.object_key in bucket.keys()


def test_files_kept_on_the_server_before_the_bucket_are_moved_there(settings):
    asset = upload(account())
    StoredObject.objects.all().delete()  # as before this change: no row, file on the volume
    fake = FakeS3()
    storage.client_factory = lambda settings: fake
    save_config('object_storage', {**KEYS, 'enabled': 'true'})
    cleanup_expired()
    assert asset.object_key in fake.keys() and StoredObject.objects.get(key=asset.object_key).remote


def test_the_sweep_removes_only_its_own_orphans_once_they_are_old(bucket):
    asset = upload(account())
    old = timezone.now() - timedelta(days=2)
    bucket.objects[('pdfmaster', 'outputs/x/orphan.pdf')] = {'data': b'x', 'at': old}
    bucket.objects[('pdfmaster', 'outputs/x/new.pdf')] = {'data': b'x', 'at': timezone.now()}
    bucket.objects[('pdfmaster', 'someone-else/keep.txt')] = {'data': b'x', 'at': old}
    storage.sweep()
    assert bucket.keys() == {asset.object_key, 'outputs/x/new.pdf', 'someone-else/keep.txt'}


def test_a_file_no_record_uses_is_pruned_after_a_day(bucket):
    asset = upload(account())
    FileAsset.objects.filter(pk=asset.pk).delete()  # as when an account is deleted
    storage.prune()
    assert asset.object_key in bucket.keys(), 'a fresh file may still be waiting for its record'
    StoredObject.objects.filter(key=asset.object_key).update(created_at=timezone.now() - timedelta(days=2))
    storage.prune()
    assert asset.object_key not in bucket.keys() and not StoredObject.objects.filter(key=asset.object_key).exists()


def test_switching_uploads_off_still_reads_what_is_in_the_bucket(bucket):
    asset = upload(account())
    evict_now()
    save_config('object_storage', {'enabled': 'false'})
    assert object_storage_config()['configured'] and not object_storage_config()['ready']
    assert storage.local(asset.object_key).is_file()
    second = upload(account(43))
    assert second.object_key not in bucket.keys(), 'new files stay on the server while uploads are off'


def test_the_connection_test_writes_reads_and_deletes_a_file(bucket):
    check_connection()
    assert bucket.keys() == set(), 'the test file is removed again'
    bucket.failing = True
    with pytest.raises(DomainError, match='object_storage_connection_failed'):
        check_connection()


def test_keys_are_required_before_turning_storage_on_and_never_shown_back():
    with pytest.raises(DomainError, match='object_storage_not_configured'):
        save_config('object_storage', {'enabled': 'true'})
    with pytest.raises(DomainError, match='invalid_storage_endpoint'):
        save_config('object_storage', {'endpoint': 'http://usc1.contabostorage.com'})
    save_config('object_storage', {**KEYS})
    from tests.test_manual_payments import staff_client
    client, _ = staff_client('Administrator')
    page = client.get('/ops/integrations').content.decode()
    assert 'object-storage-settings' in page and 'pdfmaster' in page and 'usc1.contabostorage.com' in page
    assert KEYS['access_key'] not in page and KEYS['secret_key'] not in page
    for role in ('Finance', 'Support', 'Operations'):
        other, _ = staff_client(role)
        assert other.post('/ops/integrations', {'integration': 'object_storage', 'enabled': 'false'}).status_code in (302, 403)
    assert object_storage_config()['configured']


def test_a_file_the_bucket_stored_differently_is_not_counted_as_uploaded(bucket):
    bucket.corrupt = True
    asset = upload(account())
    assert not StoredObject.objects.get(key=asset.object_key).remote, 'retried by the sync instead'
    bucket.corrupt = False
    storage.sync()
    assert StoredObject.objects.get(key=asset.object_key).remote


def test_a_short_download_never_becomes_the_working_copy(bucket):
    asset = upload(account())
    evict_now()
    bucket.truncate = True
    assert not storage.local(asset.object_key).is_file()
    bucket.truncate = False
    assert storage.local(asset.object_key).is_file()


def test_storage_trouble_is_told_to_the_owner_once_and_its_recovery_too(bucket, monkeypatch):
    from apps.core.models import StaffAlert
    from apps.core.storage_health import monitor, state
    monkeypatch.setattr('apps.core.storage_health.pause', lambda seconds: None)
    assert monitor()['healthy'] and StaffAlert.objects.count() == 0
    bucket.failing = True
    StoredObject.objects.all().delete()
    later = timezone.now() + timedelta(hours=2)
    assert not monitor(later)['healthy']
    assert StaffAlert.objects.get().kind == 'storage_failing'
    assert not monitor(later + timedelta(minutes=5))['healthy']
    assert StaffAlert.objects.count() == 1, 'the same trouble is told once'
    bucket.failing = False
    assert monitor(later + timedelta(hours=2))['healthy']
    assert list(StaffAlert.objects.order_by('created_at').values_list('kind', flat=True)) == ['storage_failing', 'storage_recovered']
    assert state()['canary_ok'] is True


def test_files_stuck_waiting_raise_the_alarm(bucket):
    from apps.core.models import StaffAlert
    from apps.core.storage_health import monitor
    bucket.failing = True
    asset = upload(account())
    StoredObject.objects.filter(key=asset.object_key).update(created_at=timezone.now() - timedelta(minutes=20))
    bucket.failing = False  # the hourly test passes; the backlog alone is the problem
    result = monitor()
    assert not result['healthy'] and result['problems'] == [{'code': 'upload_backlog', 'waiting': 1, 'minutes': 15}]
    assert '1 files have waited more than 15 minutes' in StaffAlert.objects.get().text


def test_the_alert_reaches_the_owners_telegram(bucket):
    import asyncio
    from apps.core.models import StaffAlert
    from telegram.staff_alerts import drain
    from tests.test_manual_payments import configure
    configure()  # sets the alert Telegram ID 1234567
    StaffAlert.objects.create(kind='storage_failing', text='⚠️ File storage needs attention.')

    class Bot:
        sent = []

        async def send_message(self, chat, text, **kwargs):
            self.sent.append((chat, text))
    asyncio.run(drain(Bot()))
    assert Bot.sent == [(1234567, '⚠️ File storage needs attention.')]
    assert StaffAlert.objects.get().status == 'delivered'
    asyncio.run(drain(Bot()))
    assert len(Bot.sent) == 1, 'sent once'


def test_the_admin_card_says_whether_storage_is_working(bucket, monkeypatch):
    from apps.core.storage_health import monitor
    monkeypatch.setattr('apps.core.storage_health.pause', lambda seconds: None)
    from tests.test_manual_payments import staff_client
    monitor()
    client, _ = staff_client('Administrator')
    assert 'storage-healthy' in client.get('/ops/integrations').content.decode()
    bucket.failing = True
    monitor(timezone.now() + timedelta(hours=2))
    page = client.get('/ops/integrations').content.decode()
    assert 'storage-problems' in page and 'The hourly test could not write, read or delete a file' in page
