"""Public API boundaries for images-to-PDF: scanning has no switches; old clients' ones are dropped and logged."""
import io
import logging

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.core.models import Job, Quote
from tests.scan_fixtures import scanner_models
from tests.test_platform import account, login_client


pytestmark = pytest.mark.django_db


@pytest.fixture
def image_client(settings):
    # Test confirmation and the frozen job snapshot without starting a worker.
    settings.LOCAL_SYNC_JOBS = False
    client = login_client(account(991201), csrf=True)
    csrf = client.get('/api/v1/auth/session').json()['csrf_token']
    image = io.BytesIO()
    Image.new('RGB', (240, 320), (242, 242, 237)).save(image, format='PNG')
    response = client.post(
        '/api/v1/files/uploads',
        {'file': SimpleUploadedFile('document-photo.png', image.getvalue(), 'image/png')},
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert response.status_code == 201, response.content
    return client, csrf, response.json()['id']


def request_quote(image_client, parameters=None, *, omit_parameters=False):
    client, csrf, asset_id = image_client
    body = {'feature_id': 'pdf.images_to_pdf', 'input_ids': [asset_id]}
    if not omit_parameters:
        body['parameters'] = {} if parameters is None else parameters
    return client.post('/api/v1/quotes', body, content_type='application/json', HTTP_X_CSRFTOKEN=csrf)


DEFAULTS = {'paper_size': 'fit', 'orientation': 'auto', 'margin': 0}


def submit(image_client, quote_id, *, extra=None):
    client, csrf, _ = image_client
    return client.post(
        '/api/v1/jobs',
        {'quote_id': quote_id, **(extra or {})},
        content_type='application/json',
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY='image-scan-confirmed-task',
    )


def test_public_catalog_offers_the_layout_and_no_scan_switches(client):
    response = client.get('/api/v1/catalog')
    assert response.status_code == 200, response.content
    features = {feature['id']: feature for feature in response.json()['features']}
    schema = features['pdf.images_to_pdf']['parameters']
    assert schema['additionalProperties'] is False
    assert set(schema['properties']) == {'paper_size', 'orientation', 'margin'}
    assert schema['properties']['paper_size']['enum'] == ['fit', 'A4', 'Letter', 'original']
    assert schema['properties']['paper_size']['default'] == 'fit'
    assert 'Legal' in schema['properties']['paper_size']['description'], 'Fit may give a Legal page'
    assert schema['properties']['orientation']['default'] == 'auto'
    assert schema['properties']['margin']['default'] == 0


@pytest.mark.parametrize('parameters,omit_parameters', [
    ({}, True),
    ({}, False),
    ({'paper_size': 'Letter', 'orientation': 'landscape', 'margin': 0}, False),
])
def test_image_quotes_normalize_to_the_layout_alone(image_client, parameters, omit_parameters):
    response = request_quote(image_client, parameters, omit_parameters=omit_parameters)
    assert response.status_code == 201, response.content
    body = response.json()
    normalized = body['normalized_parameters']
    assert normalized == {**DEFAULTS, **parameters}
    assert Quote.objects.get(pk=body['id']).parameters == normalized
    confirmed = submit(image_client, body['id'])
    assert confirmed.status_code == 201, confirmed.content
    assert confirmed.json()['status'] == 'queued'
    assert confirmed.json()['parameters'] == normalized
    assert Job.objects.get(pk=confirmed.json()['id']).parameters == normalized


@pytest.mark.parametrize('legacy', [
    {'auto_crop': False},
    {'enhance_text': False},
    {'auto_crop': False, 'enhance_text': False, 'paper_size': 'A4'},
    {'auto_crop': 'yes', 'enhance_text': None},
], ids=['crop-off', 'enhance-off', 'both-off-with-a4', 'odd-values'])
def test_legacy_scan_switches_are_dropped_from_confirmed_job(settings, image_client, scanner_models, legacy, caplog):
    # A web tab opened before the switches were retired still sends them: the
    # quote drops them and the log says so, so the guard can go once it is quiet.
    with caplog.at_level(logging.WARNING, logger='apps.core.services'):
        response = request_quote(image_client, legacy)
    assert response.status_code == 201, response.content
    sent = ', '.join(key for key in ('auto_crop', 'enhance_text') if key in legacy)
    assert f'dropped retired images-to-PDF settings ({sent}) sent by an out-of-date client' in caplog.text
    quote = response.json()
    expected = {**DEFAULTS, **{key: value for key, value in legacy.items() if key == 'paper_size'}}
    assert quote['normalized_parameters'] == expected

    # Confirmation identifies the reviewed quote. Extra client parameters,
    # switches included, cannot replace the reviewed settings.
    settings.LOCAL_SYNC_JOBS = True
    confirmed = submit(image_client, quote['id'], extra={
        'parameters': {'auto_crop': True, 'paper_size': 'Letter'},
    })
    assert confirmed.status_code == 201, confirmed.content
    job_id = confirmed.json()['id']
    job = Job.objects.get(pk=job_id)
    assert job.parameters == expected and Quote.objects.get(pk=quote['id']).parameters == expected
    assert not {'auto_crop', 'enhance_text'} & set(job.parameters)
    assert job.status == 'succeeded', job.error_code

    client, _, _ = image_client
    detail = client.get(f'/api/v1/jobs/{job_id}')
    assert detail.status_code == 200
    assert detail.json()['parameters'] == expected

    replay = submit(image_client, quote['id'], extra={'parameters': {}})
    assert replay.status_code == 200, replay.content
    assert replay.json()['id'] == job_id
    assert Job.objects.count() == 1


def test_queued_job_saved_with_switches_runs_once_the_deploy_cleans_it(settings, image_client, scanner_models):
    # A job queued before the switches were retired is cleaned by core 0018;
    # the processor itself no longer knows them.
    import importlib
    from django.apps import apps as django_apps
    from apps.core.services import execute_job
    response = request_quote(image_client)
    assert response.status_code == 201, response.content
    confirmed = submit(image_client, response.json()['id'])
    job = Job.objects.get(pk=confirmed.json()['id'])
    Job.objects.filter(pk=job.pk).update(parameters={**job.parameters, 'auto_crop': True, 'enhance_text': True})
    importlib.import_module('apps.core.migrations.0018_retire_scan_switch_keys').retire_scan_switches(django_apps, None)
    execute_job(job.id)
    job.refresh_from_db()
    assert job.status == 'succeeded', job.error_code
    assert job.parameters == DEFAULTS


def test_worker_logs_photos_whose_scan_failed(settings, image_client, monkeypatch, caplog):
    # The sandbox child's own log is discarded; the job's metadata carries the
    # failures to the worker, which logs them. The job still succeeds.
    import logging
    import processors.scanner as scanner
    from processors import engine, sandbox
    from apps.core.services import execute_job

    def no_memory(bgr, paper):
        raise MemoryError
    monkeypatch.setattr(scanner, 'load_models', lambda: None)
    monkeypatch.setattr(scanner, 'scan', no_memory)
    monkeypatch.setattr(sandbox, 'execute_sandbox', lambda feature, paths, parameters, out, **kwargs:
                        engine.execute(feature, paths, parameters, out))
    response = request_quote(image_client)
    job = Job.objects.get(pk=submit(image_client, response.json()['id']).json()['id'])
    with caplog.at_level(logging.WARNING, logger='apps.core.services'):
        execute_job(job.id)
    job.refresh_from_db()
    assert job.status == 'succeeded', job.error_code
    assert f'Job {job.id}: 1 photo scan(s) failed (MemoryError), kept as uploaded' in caplog.text


@pytest.mark.parametrize('parameters', [{'auto_crop_page': True}, {'enhance': False}, {'scan': True},
                                        {'paper_size': 'Legal'}])
def test_public_quotes_reject_other_unknown_settings_before_any_task(image_client, parameters):
    response = request_quote(image_client, parameters)
    assert response.status_code == 400, response.content
    assert response.json()['error']['code'] == 'invalid_parameters'
    assert Quote.objects.count() == 0
    assert Job.objects.count() == 0
