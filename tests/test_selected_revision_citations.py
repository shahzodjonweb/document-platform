"""Source-location seeds must not invalidate a successfully revised document."""
from copy import deepcopy
import json

import pytest

from apps.core.services import execute_job, submit_job
from apps.studio.domain import create_draft, generation_quote, unpack, update_draft
from apps.studio.models import ProviderAttempt, ProviderCheckpoint
from apps.studio.revisions import merge_patch
from operations.integrations import save_config
from tests.test_platform import account, upload
from tests.test_provider_contract import CONFIG
from tests.test_provider_optimization import transport
from tests.test_studio import paid

pytestmark = pytest.mark.django_db
SOURCE = 'Tidal energy is renewable.\n\nTidal patterns are predictable.\n\nSites need careful planning.'


def payload():
    placeholder = {'asset_id': 'owned-source', 'page': 1}
    quoted = {**placeholder, 'quote': 'Tidal energy is renewable.'}
    content = {'title': 'Tides', 'sections': [{'id': 's1', 'heading': 'Energy', 'body': SOURCE, 'notes': ''}],
               'questions': [], 'citations': [placeholder, quoted]}
    return {'content': content, 'excerpts': [{'asset_id': 'owned-source', 'page': 1, 'text': SOURCE}],
            'revision': {'selected_section_ids': ['s1'], 'base_content': deepcopy(content)}}


def test_only_real_baseline_page_placeholders_are_removed_without_mutating_draft():
    data = payload()
    before = deepcopy(data)
    patch = {'sections': data['content']['sections'], 'citations': [data['content']['citations'][1]]}
    result = merge_patch(data, patch)
    assert result['citations'] == [data['content']['citations'][1]]
    assert data == before


@pytest.mark.parametrize('reference', [
    {'asset_id': 'foreign-source', 'page': 1},
    {'asset_id': 'owned-source', 'page': 99},
    {'asset_id': 'owned-source', 'page': True},
    {'asset_id': 'owned-source', 'page': 1, 'quote': ''},
    {'asset_id': 'owned-source', 'page': 1, 'quote': 'Invented unsupported statement.'},
    {'asset_id': 'owned-source', 'page': 1, 'extra': 'not a source seed'},
])
def test_invalid_or_forged_references_are_retained_for_validation(reference):
    data = payload()
    data['content']['citations'] = [reference]
    data['revision']['base_content']['citations'] = [reference]
    result = merge_patch(data, {'sections': data['content']['sections'], 'citations': []})
    assert result['citations'] == [reference]


def test_new_quote_less_reference_is_not_silently_removed():
    data = payload()
    data['revision']['base_content']['citations'] = [data['content']['citations'][1]]
    result = merge_patch(data, {'sections': data['content']['sections'], 'citations': []})
    assert result['citations'] == data['content']['citations']


def test_uploaded_source_selected_revision_reaches_real_render_and_settlement(settings, monkeypatch):
    settings.DEBUG = True
    customer = paid(settings, account())
    asset = upload(customer, widths=(200,))
    monkeypatch.setattr('apps.studio.extraction.extract_pages', lambda path: [(1, SOURCE)])
    save_config('ai', {'mode': 'openai', 'model': CONFIG['model'], 'api_key': 'offline-only'})
    authored = create_draft(customer, {'prompt': 'A 3 page guide to tidal energy.', 'source_ids': [str(asset.id)]})
    original = unpack(authored.encrypted_data)
    # A pre-generation draft has the exact source-page placeholder that used
    # to be preserved into output and then fail citation validation.
    assert original['content']['citations'] == [{'asset_id': str(asset.id), 'page': 1}]
    verified = {'asset_id': str(asset.id), 'page': 1, 'quote': 'Tidal energy is renewable.'}
    content = deepcopy(original['content'])
    content['citations'].append(verified)
    authored = update_draft(customer, authored.id, {'version': authored.version, 'content': content})
    selected = create_draft(customer, {'prompt': 'Make the selected explanation friendlier.', 'options': {
        'revise_draft_id': str(authored.id), 'revise_section_ids': ['s2'], 'revise_base_version': authored.version}})
    before = unpack(selected.encrypted_data)
    quote = generation_quote(customer, selected.id, selected.version)
    job, _ = submit_job(customer, quote.id, 'selected-source-citation-regression')

    def answer(body, number):
        sent = json.loads(body['input'])
        assert [s['id'] for s in sent['outline']['sections']] == ['s2']
        return {'answer_supported': True, 'sections': [{'id': 's2', 'heading': 'Predictable tides',
                 'body': 'You can predict tidal patterns and plan ahead.'}], 'citations': [verified]}

    calls = transport(monkeypatch, answer)
    done = execute_job(job.id)
    assert done.status == 'succeeded', done.error_code
    assert done.artifacts.get().file.name.endswith('.pdf')
    selected.refresh_from_db()
    after = unpack(selected.encrypted_data)
    assert after['content']['citations'] == [verified]
    assert after['content']['sections'][0] == before['content']['sections'][0]
    assert after['content']['sections'][2] == before['content']['sections'][2]
    assert after['content']['sections'][1]['body'] == 'You can predict tidal patterns and plan ahead.'
    assert len(calls) == 1 and ProviderAttempt.objects.get().status == 'succeeded'
    assert ProviderCheckpoint.objects.get().status == 'completed'
