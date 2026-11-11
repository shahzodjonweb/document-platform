"""verify-services' document probe under Editor v2: editor cases go through an editor document, the
paid boundary is checked at the save, and a preview the lane is still drawing is asked for again."""
import io
import json
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from apps.core.services import upload_file
from scripts.operations import service_checks_documents as probe
from tests.test_platform import account, login_client, upload

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def editor_v2(settings, monkeypatch):
    settings.DEBUG = True; settings.ENABLE_BETA_TOOLS = True; settings.LOCAL_SYNC_JOBS = True
    monkeypatch.setenv('EDITOR_FLAG_EDITOR_V2', '1')


class Customer:
    """The probe's Customer.json, over Django's test client instead of HTTP."""
    def __init__(self, a):
        self.client = login_client(a)

    def json(self, method, path, data=None, expected=(200, 201), headers=None):
        call = getattr(self.client, method.lower())
        response = call('/api/v1/' + path, json.dumps(data, ensure_ascii=False).encode() if data is not None else None,
                        content_type='application/json')
        result = response.json()
        if response.status_code not in expected:
            raise probe.ProbeFailure(result.get('error', {}).get('code', 'http_' + str(response.status_code)))
        return result


def image(a):
    buffer = io.BytesIO(); Image.new('RGB', (100, 80), 'red').save(buffer, 'PNG')
    return upload_file(a, SimpleUploadedFile('red.png', buffer.getvalue(), 'image/png'))


@pytest.mark.parametrize('feature,commands,with_image', [
    ('editor.add_text', [{'type': 'add_text', 'page': 1, 'x': 40, 'y': 100, 'text': 'Salom Привет', 'font_size': 18}], False),
    ('editor.signature_image', [{'type': 'signature', 'page': 1, 'x': 40, 'y': 100, 'width': 140, 'height': 45, 'input_index': 1}], True),
])
def test_an_editor_case_is_quoted_from_an_editor_document(feature, commands, with_image):
    a = account()
    assets = [{'id': str(upload(a).id)}] + ([{'id': str(image(a).id)}] if with_image else [])
    payload = {'feature_id': feature, 'input_ids': [x['id'] for x in assets], 'parameters': {'commands': commands}}
    quote = probe.editor_v2_quote(Customer(a), assets, payload)
    assert quote['feature_id'] == 'editor.visual'


def test_the_old_route_staying_open_fails_the_check(monkeypatch):
    monkeypatch.setenv('EDITOR_FLAG_EDITOR_V2', '0')
    a = account(); asset = {'id': str(upload(a).id)}
    payload = {'feature_id': 'editor.add_text', 'input_ids': [asset['id']], 'parameters': {'commands': [
        {'type': 'add_text', 'page': 1, 'x': 40, 'y': 100, 'text': 'x', 'font_size': 18}]}}
    with pytest.raises(probe.ProbeFailure) as failure:
        probe.editor_v2_quote(Customer(a), [asset], payload)
    assert failure.value.code == 'http_201'


def test_marks_the_plan_has_are_saved():
    a = account()
    probe.editor_v2_plan_boundary(Customer(a), a, {'id': str(upload(a).id)})


def test_marks_the_plan_lacks_are_refused(monkeypatch):
    for module in ('apps.studio.domain', 'apps.studio.editor_policy'):
        monkeypatch.setattr(module + '.allowed', lambda account, fid: fid not in ('editor.existing_text', 'editor.redact'))
    a = account()
    probe.editor_v2_plan_boundary(Customer(a), a, {'id': str(upload(a).id)})


def test_the_check_notices_a_mark_saved_that_the_plan_lacks(monkeypatch):
    monkeypatch.setattr('apps.studio.domain.allowed', lambda account, fid: False)
    a = account()
    with pytest.raises(probe.ProbeFailure) as failure:
        probe.editor_v2_plan_boundary(Customer(a), a, {'id': str(upload(a).id)})
    assert failure.value.code == 'http_200'


def test_a_preview_being_drawn_is_asked_for_again(monkeypatch):
    answers = iter([(202, b'{"task_id": "x"}', {}), (202, b'{"task_id": "x"}', {}), (200, b'\x89PNG...', {})])
    customer = type('C', (), {'request': lambda self, method, url: next(answers)})()
    monkeypatch.setattr(probe.time, 'sleep', lambda seconds: None)
    assert probe.fetch_preview(customer, '/preview') == (200, b'\x89PNG...')


def test_a_preview_never_drawn_fails_the_check(monkeypatch):
    customer = type('C', (), {'request': lambda self, method, url: (202, b'{}', {})})()
    monkeypatch.setattr(probe.time, 'sleep', lambda seconds: None)
    with pytest.raises(probe.ProbeFailure) as failure:
        probe.fetch_preview(customer, '/preview', wait=0)
    assert failure.value.code == 'preview_timeout'
