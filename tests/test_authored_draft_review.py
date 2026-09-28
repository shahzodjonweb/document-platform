"""Reviewing an unchanged brief must keep the customer's authored content."""
import json

import pytest

from apps.studio.domain import create_draft, draft_data, update_draft
from tests.test_platform import account, login_client

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize('feature', ['ai.pdf_topic', 'ai.pptx'])
def test_review_with_unchanged_empty_description_preserves_authored_content(settings, feature):
    settings.DEBUG = True
    customer = account()
    draft = create_draft(customer, {
        'feature_id': feature,
        'title': 'Reviewed document',
        'prompt': '',
        'source_text': 'Original supplied paragraph.',
    })
    section = {
        'id': 's1', 'heading': 'Reviewed heading',
        'body': 'Manually reviewed content that must survive.', 'notes': 'Presenter note.',
    }
    if feature == 'ai.pptx':
        section.update(layout='stats', items=[
            {'label': 'First', 'text': '', 'value': '12'},
            {'label': 'Second', 'text': '', 'value': '34'},
        ], columns=[], image_query='')
    draft = update_draft(customer, draft.id, {
        'version': draft.version,
        'content': {'title': 'Reviewed document', 'sections': [section], 'questions': [], 'citations': []},
    })
    opened = draft_data(draft)
    assert opened['prompt'] == ''
    # The browser sends form settings without content when the editor is untouched.
    # A create-only service-name fallback must not turn this into a changed brief.
    payload = {key: opened[key] for key in (
        'version', 'title', 'prompt', 'source_text', 'source_ids',
        'output_locale', 'output_format', 'options',
    )}
    client = login_client(customer)
    response = client.patch(f'/api/v1/generation/drafts/{draft.id}',
                            data=json.dumps(payload), content_type='application/json')
    assert response.status_code == 200, response.content
    reviewed = response.json()
    assert reviewed['prompt'] == ''
    assert reviewed['content'] == opened['content']
    assert reviewed['version'] == opened['version'] + 1
    quote = client.post(f'/api/v1/generation/drafts/{draft.id}/quote',
                        data=json.dumps({'version': reviewed['version']}), content_type='application/json')
    assert quote.status_code == 201, quote.content
