"""Files kept in the object storage bucket, with only their keys in the database."""
import io
from datetime import timedelta
from types import SimpleNamespace

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


def test_bytes_are_kept_whole_or_not_at_all(bucket, monkeypatch):
    key = 'inputs/account/whole.jpg'
    storage.write(key, b'first', 'image/jpeg')
    path = storage.storage_path(key)
    assert path.read_bytes() == b'first' and path.stat().st_mode & 0o777 == 0o600
    assert StoredObject.objects.get(key=key).size == 5

    def refuse(*args):
        raise OSError('disk full')
    monkeypatch.setattr(storage.os, 'replace', refuse)
    with pytest.raises(OSError):
        storage.write('inputs/account/half.jpg', b'second', 'image/jpeg')
    assert [item.name for item in path.parent.iterdir()] == ['whole.jpg'], 'no partial file left behind'
    assert not StoredObject.objects.filter(key='inputs/account/half.jpg').exists()


def test_a_file_kept_for_later_waits_for_the_sync(bucket, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        storage.write('inputs/account/now.jpg', b'now', 'image/jpeg')
        storage.write('inputs/account/later.jpg', b'later', 'image/jpeg', later=True)
    assert bucket.keys() == {'inputs/account/now.jpg'}
    assert not StoredObject.objects.get(key='inputs/account/later.jpg').remote
    assert storage.sync() == 1 and 'inputs/account/later.jpg' in bucket.keys()
    assert StoredObject.objects.get(key='inputs/account/later.jpg').remote


# A call to a bucket that does not answer: the client's timeouts and four tries.
STALL = 47


@pytest.fixture
def stopped(bucket, monkeypatch):
    """A bucket that can stop answering, each call then failing after what that costs on a clock of its own."""
    state = SimpleNamespace(answering=True, now=0.0, calls=0)

    def stalling(call):
        def wrapped(*args, **kwargs):
            if state.answering:
                return call(*args, **kwargs)
            state.now += STALL
            state.calls += 1
            raise ConnectionError('no answer')
        return wrapped
    for name in ('put_object', 'get_object', 'delete_object', 'list_objects_v2'):
        monkeypatch.setattr(bucket, name, stalling(getattr(bucket, name)))
    monkeypatch.setattr(storage, 'time', SimpleNamespace(monotonic=lambda: state.now))
    monkeypatch.setattr('apps.core.storage_health.pause', lambda seconds: None)
    monkeypatch.setitem(storage._last_sweep, 'at', 0.0)
    return state


def test_a_bucket_that_stopped_answering_holds_a_sync_for_minutes_and_the_next_goes_on(stopped, bucket):
    keys = {f'inputs/account/{number}.jpg' for number in range(10)}
    for key in keys:
        storage.write(key, b'x', 'image/jpeg', later=True)
    stopped.answering = False
    assert storage.sync() == 0
    assert stopped.calls == 3 and stopped.now <= storage.PASS_SECONDS + STALL
    assert not StoredObject.objects.filter(remote=True).exists()
    stopped.answering = True
    assert storage.sync() == 10 and bucket.keys() == keys


def test_a_bucket_that_stopped_answering_does_not_keep_the_alert_waiting(stopped, bucket):
    """Pictures wait in dozens, and go in dozens: neither may hold the health check up behind them for hours."""
    from apps.core.models import StaffAlert
    customer = account()
    for number in range(10):
        key = f'inputs/{customer.id}/gone-{number}.jpg'
        storage.write(key, b'x', 'image/jpeg')
        FileAsset.objects.create(account=customer, name=f'{number}.jpg', object_key=key, mime_type='image/jpeg', sha256='0' * 64, size_bytes=1, page_count=1,
                                 metadata={'kind': 'deck_photo'}, expires_at=timezone.now() - timedelta(minutes=1))
        storage.write(f'inputs/{customer.id}/waiting-{number}.jpg', b'x', 'image/jpeg', later=True)
    StoredObject.objects.filter(key__contains='waiting').update(created_at=timezone.now() - timedelta(minutes=20))
    stopped.answering = False
    cleanup_expired()
    assert StaffAlert.objects.get().kind == 'storage_failing'
    # Three bucket calls for the expired files, three for the sync, the sweep's one and the canary's two.
    assert stopped.calls == 3 + 3 + 1 + 2 and stopped.now == stopped.calls * STALL
    # What they had no time for is not lost: the next runs do it, once the bucket answers.
    assert FileAsset.objects.filter(account=customer, metadata__kind='deck_photo').count() == 7
    stopped.answering = True
    assert cleanup_expired() == 7
    assert not FileAsset.objects.filter(account=customer, metadata__kind='deck_photo').exists()
    assert not StoredObject.objects.filter(key__contains='gone').exists()
    assert {f'inputs/{customer.id}/waiting-{number}.jpg' for number in range(10)} <= bucket.keys()


def test_rows_whose_files_have_gone_do_not_stop_every_sync_at_the_same_place(bucket):
    for number in range(5):
        storage.write(f'inputs/account/gone-{number}.jpg', b'x', 'image/jpeg', later=True)
        storage.storage_path(f'inputs/account/gone-{number}.jpg').unlink()
    storage.write('inputs/account/here.jpg', b'x', 'image/jpeg', later=True)
    assert storage.sync() == 1 and bucket.keys() == {'inputs/account/here.jpg'}


def test_files_the_bucket_refuses_do_not_keep_the_others_from_arriving(bucket, monkeypatch):
    real = bucket.put_object

    def refusing(**fields):
        if 'refused' in fields['Key']:
            raise ValueError('refused')
        return real(**fields)
    monkeypatch.setattr(bucket, 'put_object', refusing)
    for number in range(5):
        storage.write(f'inputs/account/refused-{number}.jpg', b'x', 'image/jpeg', later=True)
    storage.write('inputs/account/taken.jpg', b'x', 'image/jpeg', later=True)
    assert storage.sync() == 1 and bucket.keys() == {'inputs/account/taken.jpg'}


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


def test_one_failing_storage_step_does_not_stop_the_others(bucket, monkeypatch):
    from apps.core import storage as module
    ran = []
    monkeypatch.setattr(module, 'prune', lambda now=None: (_ for _ in ()).throw(RuntimeError('prune broke')))
    monkeypatch.setattr(module, 'sync', lambda limit=500: ran.append('sync') or 0)
    monkeypatch.setattr('apps.core.storage_health.monitor', lambda now=None: ran.append('health'))
    cleanup_expired()
    assert ran == ['sync', 'health']


def test_the_download_link_serves_the_file_from_the_bucket(bucket):
    """/api/v1/artifacts/<id>/download after the server's working copy is gone."""
    from tests.test_platform import login_client
    customer = account()
    source = upload(customer, widths=(220, 330))
    quote = create_quote(customer, 'pdf.rotate', [str(source.id)], {'angle': 90})
    job, _ = submit_job(customer, quote.id, 'bucket-download-1')
    artifact = execute_job(job.id).artifacts.get()
    expected = bucket.objects[('pdfmaster', artifact.file.object_key)]['data']
    evict_now()
    assert not storage_path(artifact.file.object_key).exists()
    response = login_client(customer).get(f'/api/v1/artifacts/{artifact.id}/download')
    assert response.status_code == 200
    assert b''.join(response.streaming_content) == expected, 'the bytes came back from the bucket'
