"""Independent negative integration coverage across API, identity and worker boundary."""
import hashlib
import hmac
import io
import json
import time
from datetime import timedelta
from urllib.parse import parse_qsl, urlencode

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone
from pypdf import PdfReader, PdfWriter
from apps.core.identity import resolve_account
from apps.core.models import AnalyticsEvent, Artifact, FileAsset, Job, Quote, Reservation, UsageLedger
from apps.core.services import cleanup_expired, execute_job, storage_path

pytestmark = pytest.mark.django_db


def principal(number=77001, csrf=False):
    account = resolve_account({'id': number, 'first_name': 'Adversarial fixture'}, is_test=True)
    client = Client(enforce_csrf_checks=csrf, raise_request_exception=False)
    session = client.session
    session['customer_account_id'] = str(account.id)
    session.save()
    return account, client


def pdf_data(widths=(200, 300)):
    writer = PdfWriter()
    for width in widths:
        writer.add_blank_page(width=width, height=400)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def upload(client, data=None, name='fixture.pdf'):
    response = client.post('/api/v1/files/uploads', {'file': SimpleUploadedFile(name, data or pdf_data(), 'application/pdf')})
    assert response.status_code == 201, response.content
    return response.json()


def quote(client, asset, feature='pdf.rotate', parameters=None):
    response = client.post('/api/v1/quotes', {'feature_id': feature, 'input_ids': [asset['id']], 'parameters': parameters or {}}, content_type='application/json')
    assert response.status_code == 201, response.content
    return response.json()


def submit(client, quote_id, key='adversarial-job-key'):
    return client.post('/api/v1/jobs', {'quote_id': str(quote_id)}, content_type='application/json', HTTP_IDEMPOTENCY_KEY=key)


def signed_init(token, age=0):
    values = {'auth_date': str(int(time.time()) - age), 'query_id': 'adversarial-query', 'user': json.dumps({'id': 99001, 'first_name': 'Fixture'}, separators=(',', ':'))}
    canonical = '\n'.join(f'{key}={value}' for key, value in sorted(values.items()))
    secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    values['hash'] = hmac.new(secret, canonical.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def test_equivalent_signed_init_data_cannot_be_replayed(settings):
    settings.TELEGRAM_BOT_TOKEN = '10000:fixture-only-token'
    raw = signed_init(settings.TELEGRAM_BOT_TOKEN)
    reordered = urlencode(list(reversed(parse_qsl(raw))))
    assert raw != reordered
    route = '/api/v1/auth/telegram/miniapp'
    first = Client().post(route, {'init_data': raw}, content_type='application/json')
    assert first.status_code == 200, first.content
    second = Client().post(route, {'init_data': reordered}, content_type='application/json')
    assert second.status_code == 409, second.content
    assert second.json()['error']['code'] == 'auth_replayed'


@pytest.mark.parametrize('age', [301, -31])
def test_signed_but_expired_or_future_auth_fails(settings, age):
    settings.TELEGRAM_BOT_TOKEN = '10000:fixture-only-token'
    from apps.core.identity import exchange_miniapp
    from apps.core.errors import DomainError
    with pytest.raises(DomainError) as error:
        exchange_miniapp(signed_init(settings.TELEGRAM_BOT_TOKEN, age))
    assert error.value.code == 'invalid_telegram_data'


def test_overlapping_split_is_quoted_for_actual_page_units_or_rejected():
    _, client = principal()
    asset = upload(client)
    response = client.post('/api/v1/quotes', {'feature_id': 'pdf.split', 'input_ids': [asset['id']], 'parameters': {'ranges': ['1-2', '1-2']}}, content_type='application/json')
    if response.status_code == 400:
        assert response.json()['error']['code'] in ('invalid_pages', 'invalid_parameters')
        return
    assert response.status_code == 201, response.content
    meters = {m['meter']: m['amount'] for m in response.json()['meters']}
    assert meters['file_page_units'] == 4
    result = submit(client, response.json()['id'])
    assert result.status_code == 201 and result.json()['status'] == 'succeeded', result.content
    assert len(result.json()['artifacts']) == 2


@pytest.mark.parametrize('value', ['definitely-not-a-uuid', {}, [], True, 42])
def test_invalid_quote_identifiers_return_safe_client_errors(value):
    _, client = principal()
    response = client.post('/api/v1/jobs', {'quote_id': value}, content_type='application/json', HTTP_IDEMPOTENCY_KEY='invalid-uuid-key')
    assert response.status_code in (400, 404), response.content[:500]
    assert 'error' in response.json()
    assert Job.objects.count() == 0 and Reservation.objects.count() == 0


def test_foreign_assets_quotes_jobs_and_downloads_are_inaccessible():
    owner, client = principal()
    _, attacker = principal(77002)
    asset = upload(client)
    quoted = quote(client, asset)
    unauthorized = attacker.post('/api/v1/quotes', {'feature_id': 'pdf.rotate', 'input_ids': [asset['id']]}, content_type='application/json')
    assert unauthorized.status_code == 404
    assert submit(attacker, quoted['id']).status_code == 404
    job = submit(client, quoted['id']).json()
    assert job['status'] == 'succeeded'
    for path in (f"files/{asset['id']}", f"files/{asset['id']}/download", f"jobs/{job['id']}", f"artifacts/{job['artifacts'][0]['id']}/download"):
        assert attacker.get('/api/v1/' + path).status_code == 404
    assert attacker.delete(f"/api/v1/files/{asset['id']}").status_code == 404
    assert FileAsset.objects.get(pk=asset['id']).state == 'ready'
    assert set(Job.objects.values_list('account_id', flat=True)) == {owner.id}


def test_expired_quote_and_idempotency_conflict_do_not_reserve(settings):
    _, client = principal()
    asset = upload(client)
    expired = quote(client, asset)
    Quote.objects.filter(pk=expired['id']).update(expires_at=timezone.now() - timedelta(seconds=1))
    response = submit(client, expired['id'])
    assert response.status_code == 409 and response.json()['error']['code'] == 'quote_expired'
    assert Reservation.objects.count() == 0
    valid = quote(client, asset)
    first = submit(client, valid['id'], 'stable-idempotency-key')
    assert first.status_code == 201
    replay = submit(client, valid['id'], 'stable-idempotency-key')
    assert replay.status_code == 200 and replay.json()['id'] == first.json()['id']
    other = quote(client, asset)
    conflict = submit(client, other['id'], 'stable-idempotency-key')
    assert conflict.status_code == 409 and conflict.json()['error']['code'] == 'idempotency_conflict'
    assert UsageLedger.objects.filter(kind='consume', meter='file_tasks').count() == 1


def test_corrupt_after_reservation_releases_once_and_emits_no_private_data(settings):
    settings.LOCAL_SYNC_JOBS = False
    account, client = principal()
    asset = upload(client, name='sensitive-customer-name.pdf')
    quoted = quote(client, asset)
    response = submit(client, quoted['id'])
    job_id = response.json()['id']
    original = FileAsset.objects.get(pk=asset['id'])
    storage_path(original.object_key).write_bytes(b'%PDF-1.7\ncorrupt-after-reservation')
    result = execute_job(job_id)
    assert result.status == 'failed'
    execute_job(job_id)
    assert UsageLedger.objects.filter(job_id=job_id, kind='consume').count() == 0
    assert UsageLedger.objects.filter(job_id=job_id, kind='release', meter='file_tasks').count() == 1
    assert all(grant.reserved == 0 for grant in account.usage_grants.all())
    serialized = json.dumps(list(AnalyticsEvent.objects.values('properties')))
    assert 'sensitive-customer-name' not in serialized and 'corrupt-after-reservation' not in serialized


@pytest.mark.parametrize('params', [{'password': 'secret-fixture'}, {'output_dir': '/tmp/outside'}, {'pages': '../1'}, {'pages': {'password': 'secret-fixture'}}])
def test_malicious_parameters_are_not_persisted(params):
    _, client = principal()
    asset = upload(client)
    response = client.post('/api/v1/quotes', {'feature_id': 'pdf.extract_pages', 'input_ids': [asset['id']], 'parameters': params}, content_type='application/json')
    assert response.status_code in (400, 409)
    assert Quote.objects.count() == 0 and Job.objects.count() == 0
    assert 'secret-fixture' not in response.content.decode()


def test_csrf_protects_delete_upload_and_cross_origin_requests():
    _, client = principal(csrf=True)
    assert client.delete('/api/v1/me').status_code == 403
    assert client.post('/api/v1/files/uploads', {'file': SimpleUploadedFile('fixture.pdf', pdf_data())}).status_code == 403
    token = client.get('/api/v1/auth/session').json()['csrf_token']
    response = client.patch('/api/v1/me', {'locale': 'ru'}, content_type='application/json', HTTP_X_CSRFTOKEN=token, HTTP_ORIGIN='https://attacker.example')
    assert response.status_code == 403


def test_cleanup_deletes_only_expired_registered_assets(settings, tmp_path):
    _, client = principal()
    expired = upload(client)
    live = upload(client, name='live.pdf')
    expired_asset = FileAsset.objects.get(pk=expired['id'])
    live_asset = FileAsset.objects.get(pk=live['id'])
    FileAsset.objects.filter(pk=expired_asset.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    outside = tmp_path / 'outside-sentinel'
    outside.write_text('keep')
    assert client.get(f"/api/v1/files/{expired['id']}/download").status_code == 410
    assert cleanup_expired() == 1
    assert not storage_path(expired_asset.object_key).exists()
    assert storage_path(live_asset.object_key).is_file() and outside.read_text() == 'keep'


def test_interrupted_worker_reaper_removes_unregistered_private_outputs(settings):
    from django.core.management import call_command
    settings.LOCAL_SYNC_JOBS = False
    owner, client = principal()
    asset = upload(client)
    quoted = quote(client, asset)
    response = submit(client, quoted['id'])
    job_id = response.json()['id']
    Job.objects.filter(pk=job_id).update(status='running', lease_expires_at=timezone.now() - timedelta(seconds=1))
    output_dir = storage_path(f'outputs/{owner.id}/{job_id}')
    output_dir.mkdir(parents=True)
    output = output_dir / 'result.pdf'
    output.write_bytes(pdf_data())
    assert not Artifact.objects.filter(job_id=job_id).exists()
    call_command('runworker', once=True, verbosity=0)
    assert Job.objects.get(pk=job_id).status == 'failed'
    assert not output.exists(), 'Worker-interrupted outputs must not escape retention by lacking a FileAsset row'
    assert all(grant.reserved == 0 for grant in owner.usage_grants.all())


def test_password_api_preserves_encryption_metadata_without_plaintext(settings):
    from apps.core.models import SecretHandle
    owner, client = principal()
    asset = upload(client)
    password = 'private-password-fixture'
    response = client.post('/api/v1/secrets', {'password': password}, content_type='application/json')
    assert response.status_code == 201
    handle_id = response.json()['id']
    assert password not in response.content.decode()
    assert password.encode() not in bytes(SecretHandle.objects.get(pk=handle_id).ciphertext)
    response = client.post('/api/v1/quotes', {'feature_id': 'pdf.protect', 'input_ids': [asset['id']], 'parameters': {}, 'secret_id': handle_id}, content_type='application/json')
    assert response.status_code == 201, response.content
    result = submit(client, response.json()['id'])
    assert result.status_code == 201 and result.json()['status'] == 'succeeded', result.content
    assert password not in result.content.decode()
    output = Artifact.objects.get(job_id=result.json()['id']).file
    reader = PdfReader(storage_path(output.object_key))
    assert reader.is_encrypted and reader.decrypt(password)
    assert output.metadata.get('encrypted') is True
    assert result.json()['artifacts'][0]['encrypted'] is True
    assert not SecretHandle.objects.filter(pk=handle_id).exists()
    assert password not in json.dumps(list(Quote.objects.values('parameters')))


def test_expired_password_handle_releases_queued_reservation(settings):
    from apps.core.models import SecretHandle
    settings.LOCAL_SYNC_JOBS = False
    owner, client = principal()
    asset = upload(client)
    secret = client.post('/api/v1/secrets', {'password': 'temporary-fixture'}, content_type='application/json').json()
    response = client.post('/api/v1/quotes', {'feature_id': 'pdf.protect', 'input_ids': [asset['id']], 'parameters': {}, 'secret_id': secret['id']}, content_type='application/json')
    assert response.status_code == 201, response.content
    result = submit(client, response.json()['id'])
    assert result.json()['status'] == 'queued'
    SecretHandle.objects.filter(pk=secret['id']).update(expires_at=timezone.now() - timedelta(seconds=1))
    done = execute_job(result.json()['id'])
    assert done.status == 'failed' and done.error_code == 'password_expired'
    assert not SecretHandle.objects.filter(pk=secret['id']).exists()
    assert not UsageLedger.objects.filter(job=done, kind='consume').exists()
    assert all(g.reserved == 0 for g in owner.usage_grants.all())


def test_orphan_sweep_respects_age_registration_and_symlinks(settings, tmp_path):
    import os
    _, client = principal()
    live = upload(client)
    registered = FileAsset.objects.get(pk=live['id'])
    registered_path = storage_path(registered.object_key)
    orphan = storage_path('inputs/abandoned/old.pdf')
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(pdf_data())
    recent = orphan.parent / 'recent.pdf'
    recent.write_bytes(pdf_data())
    outside = tmp_path / 'outside-private-root.pdf'
    outside.write_bytes(pdf_data())
    link = orphan.parent / 'outside.pdf'
    link.symlink_to(outside)
    old = (timezone.now() - timedelta(hours=25)).timestamp()
    for path in (registered_path, orphan, outside):
        os.utime(path, (old, old))
    cleanup_expired()
    assert not orphan.exists()
    assert recent.exists() and registered_path.exists()
    assert link.is_symlink() and outside.exists()
