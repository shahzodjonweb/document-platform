"""Explicit scope and source provenance preserve authored work exactly."""
from copy import deepcopy
from datetime import timedelta

import pytest
from django.utils import timezone
from apps.core.errors import DomainError
from apps.studio.domain import create_draft, draft_data, unpack, update_draft, ensure_selected_preservation
from apps.studio.revisions import merge_patch, provider_content
from tests.test_platform import account
from tests.test_studio import paid

pytestmark = pytest.mark.django_db


@pytest.fixture
def customer(settings):
    settings.DEBUG = True
    return paid(settings, account())


def source(customer):
    return create_draft(customer, {'prompt': 'A 3 page guide for new staff.',
                                  'source_text': 'Source one.\n\nSource two.\n\nSource three.'})


def revision(customer, draft, ids=None, version=None):
    options = {'revise_draft_id': str(draft.id)}
    if ids is not None:
        options.update(revise_section_ids=ids, revise_base_version=draft.version if version is None else version)
    return create_draft(customer, {'prompt': 'Make the selected page friendlier.', 'options': options})


def test_scope_is_explicit_and_preserves_original_source_and_brief(customer):
    original = source(customer)
    global_change = unpack(revision(customer, original).encrypted_data)
    assert 'selected_section_ids' not in global_change['revision']
    selected = revision(customer, original, ['s3', 's1'])
    data = unpack(selected.encrypted_data)
    before = unpack(original.encrypted_data)
    assert data['revision']['selected_section_ids'] == ['s1', 's3']
    assert data['revision']['base_content'] == before['content']
    assert data['source_text'] == before['source_text']
    assert data['revision']['original_prompt'] == before['prompt']
    assert data['options']['length'] == 3
    assert 'base_content' not in draft_data(selected)['revision']


@pytest.mark.parametrize('ids,version,code', [([], 1, 'invalid_parameters'), (['s1', 's1'], 1, 'invalid_parameters'),
                                           (['foreign'], 1, 'invalid_parameters'), ('s1', 1, 'invalid_parameters'),
                                           (['s1'], True, 'invalid_parameters'), (['s1'], 99, 'version_conflict')])
def test_selection_rejects_ambiguous_or_stale_identity(customer, ids, version, code):
    with pytest.raises(DomainError) as caught:
        revision(customer, source(customer), ids, version)
    assert caught.value.code == code


def test_selection_requires_owned_unexpired_source(customer, settings):
    original = source(customer)
    other = paid(settings, account(43))
    with pytest.raises(DomainError) as caught:
        revision(other, original, ['s1'])
    assert caught.value.code == 'not_found'
    original.expires_at = timezone.now() - timedelta(seconds=1)
    original.save(update_fields=['expires_at'])
    with pytest.raises(DomainError) as caught:
        revision(customer, original, ['s1'])
    assert caught.value.code == 'not_found'


def test_revision_snapshot_survives_original_changes_and_manual_edits(customer):
    original = source(customer)
    scoped = revision(customer, original, ['s2'])
    before = unpack(scoped.encrypted_data)
    changed = deepcopy(before['content'])
    changed['title'] = 'Manual title'
    changed['sections'][0]['body'] = 'An independently edited page.'
    changed['questions'] = [{'id': 'q1', 'stem': 'Question?', 'options': [], 'answer': 'Answer',
                             'explanation': '', 'topic': 'Staff', 'marks': 1}]
    scoped = update_draft(customer, scoped.id, {'version': scoped.version, 'title': 'Manual title', 'content': changed})
    update_draft(customer, original.id, {'version': original.version, 'prompt': 'A 3 page replacement.'})
    scoped = update_draft(customer, scoped.id, {'version': scoped.version, 'prompt': 'Clarify the selected page.'})
    current = unpack(scoped.encrypted_data)
    assert current['revision']['base_content'] == before['revision']['base_content']
    assert current['content'] == changed
    patch = {'sections': [{**changed['sections'][1], 'body': 'Rewritten selected page.'}], 'citations': []}
    merged = merge_patch(current, patch)
    assert merged['title'] == 'Manual title'
    assert merged['questions'] == changed['questions']
    assert merged['sections'][0] == changed['sections'][0]
    assert merged['sections'][2] == changed['sections'][2]
    assert merged['sections'][1]['body'] == 'Rewritten selected page.'
    assert current['content'] == changed, 'Merge cannot mutate the immutable quoted input'


@pytest.mark.parametrize('patch', [
    {'sections': []}, {'sections': [{'id': 's1'}]}, {'sections': [{'id': 's2'}, {'id': 's2'}]},
    {'sections': [{'id': 's2'}], 'title': 'Unauthorized'},
    {'sections': [{'id': 's2'}], 'questions': []},
])
def test_patch_cannot_touch_unselected_or_global_fields(customer, patch):
    data = unpack(revision(customer, source(customer), ['s2']).encrypted_data)
    with pytest.raises(DomainError):
        merge_patch(data, patch)


def test_patch_unions_citations_without_dropping_old_references(customer):
    data = unpack(revision(customer, source(customer), ['s2']).encrypted_data)
    old = {'asset_id': 'one', 'page': 1, 'quote': 'Existing quote'}
    new = {'asset_id': 'two', 'page': 2, 'quote': 'New quote'}
    data['content']['citations'] = [old]
    result = merge_patch(data, {'sections': [data['content']['sections'][1]], 'citations': [old, new]})
    assert result['citations'] == [old, new]


def test_only_untouched_server_seed_is_removed_from_provider_copy(customer):
    draft = source(customer)
    original = unpack(draft.encrypted_data)
    assert '_source_seed' not in draft_data(draft)
    assert all(not s['body'] for s in provider_content(original)['sections'])
    assert original['content']['sections'][0]['body'] == 'Source one.'
    authored = deepcopy(original)
    authored['content']['sections'][0]['heading'] = 'A customer heading'
    assert provider_content(authored)['sections'][0]['body'] == 'Source one.'
    legacy = deepcopy(original)
    legacy.pop('_source_seed')
    assert provider_content(legacy) == original['content']
    changed_sources = deepcopy(original)
    changed_sources['source_text'] = 'Different source'
    assert provider_content(changed_sources) == original['content']


def test_author_edits_clear_provenance_even_when_text_matches(customer):
    draft = source(customer)
    before = unpack(draft.encrypted_data)
    unchanged = update_draft(customer, draft.id, {'version': draft.version, 'prompt': before['prompt']})
    assert unpack(unchanged.encrypted_data)['_source_seed'] == before['_source_seed']
    edited = update_draft(customer, draft.id, {'version': unchanged.version, 'content': before['content']})
    assert '_source_seed' not in unpack(edited.encrypted_data)
    assert provider_content(unpack(edited.encrypted_data)) == before['content']


def test_client_cannot_forge_source_provenance(customer):
    with pytest.raises(DomainError):
        create_draft(customer, {'prompt': 'A guide', '_source_seed': {'sections': {}}})
    with pytest.raises(DomainError):
        create_draft(customer, {'prompt': 'A guide', 'options': {'_source_seed': {}}})


def test_selected_scope_cannot_be_changed_or_resized_by_saving(customer):
    original = source(customer)
    scoped = revision(customer, original, ['s2'])
    for fields in ({'options': {}}, {'prompt': 'Make this 5 pages.'},
                   {'options': {'revise_draft_id': str(original.id),
                                'revise_base_version': original.version, 'revise_section_ids': ['s1']}}):
        with pytest.raises(DomainError):
            update_draft(customer, scoped.id, {'version': scoped.version, **fields})
    data = unpack(scoped.encrypted_data)
    content = deepcopy(data['content'])
    content['sections'].pop()
    with pytest.raises(DomainError):
        update_draft(customer, scoped.id, {'version': scoped.version, 'content': content})


@pytest.mark.parametrize('selected', [['s1'], ['s3']])
def test_new_selected_revision_rejects_lowered_full_document_cap(customer, monkeypatch, selected):
    from apps.studio import domain
    original = source(customer)
    caps = domain.limits(customer)
    monkeypatch.setattr(domain, 'limits', lambda _: {**caps, 'sections':2})
    with pytest.raises(DomainError, match='generation_limit'):
        revision(customer, original, selected)
    original.refresh_from_db()
    assert len(unpack(original.encrypted_data)['content']['sections']) == 3


def test_new_selected_revision_rejects_lowered_question_cap(customer, monkeypatch):
    from apps.studio import domain
    original = source(customer)
    content = unpack(original.encrypted_data)['content']
    content['questions'] = [dict(id=f'q{i}', stem='Keep this question?', options=[], answer='Yes',
                                 explanation='', topic='Staff', marks=1) for i in range(2)]
    original = update_draft(customer, original.id, {'version':original.version, 'content':content})
    caps = domain.limits(customer)
    monkeypatch.setattr(domain, 'limits', lambda _: {**caps, 'questions':1})
    with pytest.raises(DomainError, match='generation_limit'):
        revision(customer, original, ['s2'])


def _queued_selected_job(customer):
    from apps.core.services import submit_job
    from apps.studio.domain import generation_quote
    from operations.integrations import save_config
    save_config('ai', {'mode':'openai', 'model':'offline-model', 'api_key':'offline-test-key'})
    scoped = revision(customer, source(customer), ['s2'])
    quote = generation_quote(customer, scoped.id, scoped.version)
    job, _ = submit_job(customer, quote.id, 'mutable-cap-selected-job')
    return scoped, job


def test_queued_selected_revision_rechecks_caps_before_calling_provider(customer, monkeypatch):
    from apps.core.services import execute_job
    from apps.studio import domain, provider
    scoped, job = _queued_selected_job(customer)
    before = bytes(scoped.encrypted_data)
    caps = domain.limits(customer)
    monkeypatch.setattr(domain, 'limits', lambda _: {**caps, 'sections':2})
    def never_call(*args, **kwargs):
        pytest.fail('Mutable cap rejection must happen before a paid provider call')
    monkeypatch.setattr(provider, 'generate', never_call)
    completed = execute_job(job.id)
    assert completed.status == 'failed' and completed.error_code == 'generation_limit'
    scoped.refresh_from_db()
    assert bytes(scoped.encrypted_data) == before and not completed.artifacts.exists()


def test_cap_change_during_provider_call_never_delivers_truncated_revision(customer, monkeypatch):
    from apps.core.services import execute_job
    from apps.studio import domain, provider
    scoped, job = _queued_selected_job(customer)
    before = bytes(scoped.encrypted_data)
    caps = domain.limits(customer)
    calls = []
    def change_cap(*args, **kwargs):
        calls.append('provider')
        monkeypatch.setattr(domain, 'limits', lambda _: {**caps, 'sections':2})
        result = deepcopy(unpack(before)['content'])
        result['sections'][1]['body'] = 'A carefully rewritten selected page.'
        return {**result, 'answer_supported':True}, {'input_tokens':100, 'output_tokens':50}
    monkeypatch.setattr(provider, 'generate', change_cap)
    completed = execute_job(job.id)
    assert completed.status == 'failed' and completed.error_code == 'generation_limit'
    assert calls == ['provider'] and not completed.artifacts.exists()
    scoped.refresh_from_db()
    assert bytes(scoped.encrypted_data) == before


@pytest.mark.parametrize('changed', ['section', 'title', 'questions', 'order'])
def test_final_selected_normalization_must_preserve_all_untouched_content(customer, changed):
    scoped = revision(customer, source(customer), ['s2'])
    data = unpack(scoped.encrypted_data)
    normalized = deepcopy(data['content'])
    normalized['sections'][1]['body'] = 'Allowed change to the selected page.'
    ensure_selected_preservation(data, normalized)
    if changed == 'section':normalized['sections'][0]['body']='Unrequested rewrite'
    elif changed == 'title':normalized['title']='Unrequested title'
    elif changed == 'questions':normalized['questions']=[{'id':'q1'}]
    else:normalized['sections'].reverse()
    with pytest.raises(DomainError, match='generation_limit'):
        ensure_selected_preservation(data, normalized)


def styled_deck(customer):
    from tests.test_studio_branding import logo
    asset=logo(customer)
    draft=create_draft(customer, {
        'feature_id':'ai.pptx', 'prompt':'A dark 3 slide briefing in navy.',
        'source_text':'First point.\n\nSecond point.\n\nThird point.',
        'options':{'template_id':'executive_report',
                   'branding':{'name':'Acme', 'accent':'#285cff', 'logo_asset_id':str(asset.id)}}})
    return draft,asset


@pytest.mark.parametrize('scoped', [False,True])
def test_typo_revision_preserves_dark_template_branding_and_logo(customer,scoped):
    from apps.studio.branding import render_style
    original,_=styled_deck(customer)
    before=unpack(original.encrypted_data)
    revised=revision(customer,original,['s2'] if scoped else None)
    data=unpack(revised.encrypted_data)
    assert data['options']['template_id']=='executive_report'
    assert data['options']['template_style']==before['options']['template_style']
    assert data['options']['template_style']['deck_theme']=='dark'
    assert data['options']['branding']==before['options']['branding']
    assert render_style(customer,data,feature_id='ai.pptx')==render_style(customer,before,feature_id='ai.pptx')
    revised=update_draft(customer,revised.id,{'version':revised.version,'prompt':'Clarify the wording.'})
    saved=unpack(revised.encrypted_data)
    assert saved['options']['template_style']==before['options']['template_style']
    assert saved['options']['branding']==before['options']['branding']


def test_whole_document_revision_can_explicitly_change_template_theme_and_brand(customer):
    original,_=styled_deck(customer)
    revised=create_draft(customer,{
        'prompt':'Use a light theme with green accents.',
        'options':{'revise_draft_id':str(original.id),'template_id':'compact_brief','branding':{}}})
    data=unpack(revised.encrypted_data)
    assert data['options']['template_id']=='compact_brief'
    assert data['options']['template_style']['layout']=='compact'
    assert data['options']['template_style']['deck_theme']=='light'
    assert data['options']['template_style']['accent']=='#1E6B45'
    assert 'branding' not in data['options']
    saved=update_draft(customer,revised.id,{'version':revised.version,'prompt':'Fix another typo.'})
    assert unpack(saved.encrypted_data)['options']['template_style']==data['options']['template_style']


def test_selected_revision_does_not_apply_theme_words_to_the_whole_deck(customer):
    original,_=styled_deck(customer)
    revised=create_draft(customer,{
        'prompt':'Clarify the light background topic in this slide.',
        'options':{'revise_draft_id':str(original.id),'revise_base_version':original.version,
                   'revise_section_ids':['s2']}})
    assert unpack(revised.encrypted_data)['options']['template_style']==unpack(original.encrypted_data)['options']['template_style']


@pytest.mark.parametrize('override',[{'template_id':'clean'},{'branding':{}}])
def test_selected_revision_rejects_global_template_or_brand_override(customer,override):
    original,_=styled_deck(customer)
    with pytest.raises(DomainError,match='invalid_parameters'):
        create_draft(customer,{'prompt':'Fix a typo.',
                              'options':{'revise_draft_id':str(original.id),'revise_base_version':original.version,
                                         'revise_section_ids':['s2'],**override}})


def test_inherited_brand_logo_is_revalidated_for_retention(customer):
    original,asset=styled_deck(customer)
    asset.expires_at=timezone.now()-timedelta(seconds=1)
    asset.save(update_fields=['expires_at'])
    with pytest.raises(DomainError,match='file_unavailable'):
        revision(customer,original,['s2'])


def test_inherited_template_rechecks_current_entitlement(customer,monkeypatch):
    from apps.studio import domain
    original,_=styled_deck(customer)
    allowed=domain.allowed
    monkeypatch.setattr(domain,'allowed',lambda user,feature:False if feature=='template.professional' else allowed(user,feature))
    with pytest.raises(DomainError,match='feature_not_in_plan'):
        revision(customer,original)
