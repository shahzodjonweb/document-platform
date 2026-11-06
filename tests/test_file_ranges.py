"""A file's download answers one byte range, so a viewer can read a long PDF page by page."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core import storage
from apps.core.models import Artifact
from apps.core.services import execute_job, storage_path, submit_job
from apps.core.views import byte_range
from tests.test_object_storage import bucket, evict_now  # noqa: F401
from tests.test_platform import account, login_client, quote, upload

pytestmark = pytest.mark.django_db


def fetch(client, asset, wanted=None, **headers):
    if wanted:
        headers['HTTP_RANGE'] = wanted
    response = client.get(f'/api/v1/files/{asset.id}/download', **headers)
    return response, b''.join(response.streaming_content) if response.streaming else response.content


def stored(asset):
    return storage_path(asset.object_key).read_bytes()


def bucket_only(asset):
    """The file is in the bucket and its working copy has gone, as after a couple of idle hours."""
    assert storage.sync() >= 1
    evict_now()
    assert not storage_path(asset.object_key).exists()


def test_a_part_of_a_file_comes_with_its_range():
    owner = account()
    asset = upload(owner, name='Ўзбекистон тарихи.pdf')
    data, size = stored(asset), len(stored(asset))
    client = login_client(owner)
    whole, body = fetch(client, asset)
    assert whole.status_code == 200 and body == data and whole['Accept-Ranges'] == 'bytes' and 'Content-Range' not in whole
    part, body = fetch(client, asset, 'bytes=10-19')
    assert part.status_code == 206 and body == data[10:20]
    assert part['Content-Range'] == f'bytes 10-19/{size}' and part['Content-Length'] == '10' and part['Accept-Ranges'] == 'bytes'
    for header in ('Content-Type', 'Content-Disposition', 'Cache-Control', 'Content-Security-Policy'):
        assert part[header] == whole[header], header
    assert fetch(login_client(account(43)), asset, 'bytes=10-19')[0].status_code == 404
    refused, body = fetch(client, asset, f'bytes={size}-')
    assert refused.status_code == 416 and refused['Content-Range'] == f'bytes */{size}'
    assert refused.json()['error']['code'] == 'range_not_satisfiable'


@pytest.mark.parametrize('wanted,first,last', [
    ('bytes=0-0', 0, 0),
    ('bytes=5-', 5, 99),
    ('BYTES=5-6', 5, 6),
    ('bytes=-7', 93, 99),
    ('bytes=-500', 0, 99),
    ('bytes=90-500', 90, 99),
    ('bytes=99-99', 99, 99),
    ('bytes=0-999999999999999999', 0, 99),
])
def test_what_each_range_reads(wanted, first, last):
    assert byte_range(wanted, 100) == (first, last)


@pytest.mark.parametrize('wanted', ['bytes=100-', 'bytes=100-200', 'bytes=-0', 'bytes=999999999999999999-'])
def test_ranges_nothing_can_answer(wanted):
    assert byte_range(wanted, 100) is False


def test_nothing_in_an_empty_file_answers_a_range():
    assert byte_range('bytes=0-', 0) is False and byte_range('bytes=-5', 0) is False


@pytest.mark.parametrize('wanted', ['', 'bytes=', 'bytes=-', 'bytes=5-2', 'bytes=a-b', 'pages=0-1', 'bytes=0-1,5-6', 'bytes=0-1, -3', '0-1', 'bytes=٠-١', f'bytes={"9" * 5000}-'])
def test_ranges_that_get_the_whole_file(wanted):
    assert byte_range(wanted, 100) is None


def test_several_ranges_and_an_unreadable_one_get_the_whole_file():
    owner = account()
    asset = upload(owner)
    client = login_client(owner)
    for wanted in ('bytes=0-1,5-6', 'pages=0-1', 'bytes=5-2'):
        response, body = fetch(client, asset, wanted)
        assert response.status_code == 200 and body == stored(asset) and 'Content-Range' not in response, wanted


def test_an_if_range_gets_the_whole_file_as_no_validator_was_ever_sent():
    owner = account()
    asset = upload(owner)
    response, body = fetch(login_client(owner), asset, 'bytes=0-1', HTTP_IF_RANGE='"anything"')
    assert response.status_code == 200 and body == stored(asset)


def test_the_parts_add_up_to_the_file():
    owner = account()
    asset = upload(owner)
    data = stored(asset)
    client = login_client(owner)
    parts = [fetch(client, asset, f'bytes={start}-{start + 99}')[1] for start in range(0, len(data), 100)]
    assert b''.join(parts) == data
    assert fetch(client, asset, 'bytes=-5')[1] == data[-5:] and fetch(client, asset, 'bytes=7-')[1] == data[7:]


def test_a_range_refused_speaks_the_customers_language():
    owner = account()
    asset = upload(owner)
    owner.locale = 'uz'
    owner.save(update_fields=['locale'])
    refused, _ = fetch(login_client(owner), asset, f'bytes={asset.size_bytes}-')
    assert refused.status_code == 416 and refused.json()['error']['message'] == 'Faylning bu qismi mavjud emas.'


def test_a_part_of_an_expired_file_is_refused():
    owner = account()
    asset = upload(owner)
    client = login_client(owner)
    asset.expires_at = timezone.now() - timedelta(minutes=1)
    asset.save(update_fields=['expires_at'])
    assert fetch(client, asset, 'bytes=0-1')[0].status_code == 410


def test_a_part_of_a_file_gone_everywhere_is_not_found():
    owner = account()
    asset = upload(owner)
    storage_path(asset.object_key).unlink()
    assert fetch(login_client(owner), asset, 'bytes=0-1')[0].status_code == 404


def test_a_file_only_in_the_bucket_sends_just_the_part_and_leaves_nothing_on_the_volume(bucket):  # noqa: F811
    owner = account()
    asset = upload(owner)
    data = stored(asset)
    bucket_only(asset)
    client = login_client(owner)
    part, body = fetch(client, asset, 'bytes=10-19')
    assert part.status_code == 206 and body == data[10:20] and part['Content-Range'] == f'bytes 10-19/{len(data)}'
    assert fetch(client, asset, 'bytes=-5')[1] == data[-5:]
    assert bucket.reads == ['bytes=10-19', f'bytes={len(data) - 5}-{len(data) - 1}']
    assert not storage_path(asset.object_key).exists()
    refused, _ = fetch(client, asset, f'bytes={len(data)}-')
    assert refused.status_code == 416 and len(bucket.reads) == 2, 'the size is known without asking the bucket'


def test_a_bucket_that_sends_the_whole_object_for_a_part_still_gives_the_part(bucket):  # noqa: F811
    owner = account()
    asset = upload(owner)
    data = stored(asset)
    bucket_only(asset)
    bucket.ignores_ranges = True
    part, body = fetch(login_client(owner), asset, 'bytes=10-19')
    assert part.status_code == 206 and body == data[10:20] and part['Content-Length'] == '10'


def test_a_bucket_that_stopped_answering_is_a_file_unavailable_now(bucket):  # noqa: F811
    owner = account()
    asset = upload(owner)
    bucket_only(asset)
    bucket.failing = True
    assert fetch(login_client(owner), asset, 'bytes=0-1')[0].status_code == 404
    assert bucket.reads == ['bytes=0-1'], 'not asked again for the whole file'


def test_a_file_on_the_volume_is_not_asked_of_the_bucket(bucket):  # noqa: F811
    owner = account()
    asset = upload(owner)
    data = stored(asset)
    assert storage.sync() >= 1
    assert fetch(login_client(owner), asset, 'bytes=0-1')[1] == data[:2] and bucket.reads == []


def test_only_a_files_own_download_answers_ranges():
    owner = account()
    asset = upload(owner)
    job, _ = submit_job(owner, quote(owner, asset).id, 'range-request-key')
    execute_job(job.id)
    artifact = Artifact.objects.get(job=job)
    response = login_client(owner).get(f'/api/v1/artifacts/{artifact.id}/download', HTTP_RANGE='bytes=0-1')
    assert response.status_code == 200 and 'Accept-Ranges' not in response and 'Content-Range' not in response
