"""Public API boundaries for the images-to-PDF document cleanup switches."""
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.core.models import Job, Quote, Reservation
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


def submit(image_client, quote_id, *, extra=None):
    client, csrf, _ = image_client
    return client.post(
        '/api/v1/jobs',
        {'quote_id': quote_id, **(extra or {})},
        content_type='application/json',
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY='image-scan-confirmed-task',
    )


def test_public_catalog_exposes_default_on_document_switches(client):
    response = client.get('/api/v1/catalog')
    assert response.status_code == 200, response.content
    features = {feature['id']: feature for feature in response.json()['features']}
    schema = features['pdf.images_to_pdf']['parameters']
    assert schema['additionalProperties'] is False
    for field in ('auto_crop', 'enhance_text'):
        assert schema['properties'][field]['type'] == 'boolean'
        assert schema['properties'][field]['default'] is True
        assert field not in schema['required'], 'Older clients may omit either switch'
        assert 'document' in schema['properties'][field]['description'].lower()
        assert field not in features['pdf.compress']['parameters']['properties']


@pytest.mark.parametrize('parameters,omit_parameters', [
    ({}, True),
    ({}, False),
    ({'paper_size': 'Letter', 'orientation': 'landscape', 'margin': 0}, False),
])
def test_legacy_image_quotes_normalize_default_on_switches(image_client, parameters, omit_parameters):
    response = request_quote(image_client, parameters, omit_parameters=omit_parameters)
    assert response.status_code == 201, response.content
    body = response.json()
    normalized = body['normalized_parameters']
    assert normalized['auto_crop'] is True
    assert normalized['enhance_text'] is True
    for field, value in parameters.items():
        assert normalized[field] == value
    quote = Quote.objects.get(pk=body['id'])
    assert quote.parameters == normalized

    confirmed = submit(image_client, body['id'])
    assert confirmed.status_code == 201, confirmed.content
    assert confirmed.json()['status'] == 'queued'
    assert confirmed.json()['parameters'] == normalized
    job = Job.objects.get(pk=confirmed.json()['id'])
    assert job.parameters['auto_crop'] is True
    assert job.parameters['enhance_text'] is True


@pytest.mark.parametrize('opt_out,expected', [
    ({'auto_crop': False}, {'auto_crop': False, 'enhance_text': True}),
    ({'enhance_text': False}, {'auto_crop': True, 'enhance_text': False}),
    ({'auto_crop': False, 'enhance_text': False}, {'auto_crop': False, 'enhance_text': False}),
])
def test_explicit_opt_out_is_frozen_in_confirmed_job(image_client, opt_out, expected):
    response = request_quote(image_client, opt_out)
    assert response.status_code == 201, response.content
    quote = response.json()
    for field, value in expected.items():
        assert quote['normalized_parameters'][field] is value

    # Confirmation identifies the reviewed quote. Extra client parameters cannot
    # replace the reviewed settings, even when they try to turn an opt-out on.
    confirmed = submit(image_client, quote['id'], extra={
        'parameters': {'auto_crop': True, 'enhance_text': True},
    })
    assert confirmed.status_code == 201, confirmed.content
    job_id = confirmed.json()['id']
    normalized = quote['normalized_parameters']
    assert confirmed.json()['parameters'] == normalized
    assert Quote.objects.get(pk=quote['id']).parameters == normalized
    assert Job.objects.get(pk=job_id).parameters == normalized

    client, _, _ = image_client
    detail = client.get(f'/api/v1/jobs/{job_id}')
    assert detail.status_code == 200
    assert detail.json()['parameters'] == normalized

    later_quote = request_quote(image_client)
    assert later_quote.status_code == 201, later_quote.content
    assert later_quote.json()['normalized_parameters']['auto_crop'] is True
    assert later_quote.json()['normalized_parameters']['enhance_text'] is True
    assert Job.objects.get(pk=job_id).parameters == normalized

    replay = submit(image_client, quote['id'], extra={'parameters': {}})
    assert replay.status_code == 200, replay.content
    assert replay.json()['id'] == job_id
    assert replay.json()['parameters'] == normalized
    assert Job.objects.count() == 1


@pytest.mark.parametrize('field', ['auto_crop', 'enhance_text'])
@pytest.mark.parametrize('value', [None, 0, 1, 'true', 'false', [], {}])
def test_public_quotes_reject_non_boolean_switches_before_reservation(image_client, field, value):
    response = request_quote(image_client, {field: value})
    assert response.status_code == 400, response.content
    assert response.json()['error']['code'] == 'invalid_parameters'
    assert Quote.objects.count() == 0
    assert Job.objects.count() == 0
    assert Reservation.objects.count() == 0
