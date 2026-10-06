"""Changing a document that has already been generated.

The customer says what should change in the same way they said what to make,
and everything else stays as it was. This is not a third service: it is the
same two, handed the document they already produced.
"""
import pytest

from apps.core.errors import DomainError
from apps.core.services import execute_job, submit_job
from apps.studio import pages
from apps.studio.domain import DOCUMENT, SLIDES, create_draft, generation_quote, unpack
from tests.test_platform import account
from tests.test_studio import paid

pytestmark = pytest.mark.django_db


@pytest.fixture
def premium(settings):
    settings.DEBUG = True
    return paid(settings, account())


def generated(customer, description='A 3 page guide to tide tables.', feature=DOCUMENT, fmt='pdf'):
    """A finished document, the way a customer would have one."""
    # A slide holds far less than a page, so size the body to the output.
    words = 12 if fmt == 'pptx' else 120
    chunks = [' '.join(['measurement'] * words) for _ in range(3)]
    chunks[0] = f'{description} {chunks[0]}'
    draft = create_draft(customer, {'feature_id': feature, 'output_format': fmt,
                                    'title': 'Tide tables', 'source_text': '\n\n'.join(chunks)})
    quote = generation_quote(customer, draft.id, draft.version)
    job, _ = submit_job(customer, quote.id, f'generated-{draft.id}')
    job = execute_job(job.id)
    assert job.status == 'succeeded', job.error_code
    draft.refresh_from_db()
    return draft


def test_a_change_request_inherits_the_document_it_changes(premium):
    original = generated(premium)
    before = unpack(original.encrypted_data)

    revised = create_draft(premium, {'prompt': 'Make the second section shorter.',
                                     'options': {'revise_draft_id': str(original.id)}})
    payload = unpack(revised.encrypted_data)

    assert payload['revision']['request'] == 'Make the second section shorter.'
    assert payload['revision']['source_draft_id'] == str(original.id)
    assert revised.feature_id == original.feature_id
    assert payload['output_format'] == before['output_format']
    assert payload['output_locale'] == before['output_locale']
    assert payload['title'] == before['title']
    # The model is handed the document as it stands, not an empty structure.
    assert [s['body'] for s in payload['content']['sections']] == [
        s['body'] for s in before['content']['sections']
    ]
    assert payload['options']['length'] == len(before['content']['sections'])


def test_a_change_may_ask_for_a_different_length(premium):
    original = generated(premium)
    revised = create_draft(premium, {'prompt': 'Same document but in 5 pages.',
                                     'options': {'revise_draft_id': str(original.id)}})
    payload = unpack(revised.encrypted_data)
    assert payload['options']['length'] == 5
    assert payload['options']['requested_pages'] == 5
    # The sections that existed keep their text; the new ones start empty.
    assert payload['content']['sections'][0]['body'].strip()
    assert not payload['content']['sections'][-1]['body'].strip()


def test_the_change_reaches_the_model_as_a_revision(premium):
    from apps.studio.provider import request_body
    import json
    original = generated(premium)
    revised = create_draft(premium, {'prompt': 'Use a friendlier tone throughout.',
                                     'options': {'revise_draft_id': str(original.id)}})
    sent = json.loads(request_body({'model': 'm'}, unpack(revised.encrypted_data), DOCUMENT)['input'])
    assert sent['revision'] == {'request': 'Use a friendlier tone throughout.'}
    assert sent['outline']['sections'][0]['body'].strip(), 'the current text is what it revises'


def test_a_change_costs_what_the_document_costs(premium):
    original = generated(premium)
    revised = create_draft(premium, {'prompt': 'Make it friendlier.',
                                     'options': {'revise_draft_id': str(original.id)}})
    quote = generation_quote(premium, revised.id, revised.version)
    assert quote.feature_id == original.feature_id
    assert quote.policy['generation_bounds']['output_pages'] == 4, 'three pages plus the headroom'


def test_a_change_produces_a_new_document_of_the_same_length(premium):
    original = generated(premium)
    revised = create_draft(premium, {'prompt': 'Make it friendlier.',
                                     'options': {'revise_draft_id': str(original.id)}})
    quote = generation_quote(premium, revised.id, revised.version)
    job, _ = submit_job(premium, quote.id, f'revision-{revised.id}')
    job = execute_job(job.id)
    assert job.status == 'succeeded', job.error_code
    # Same length: the same three sections. A short document flows onto fewer
    # pages rather than leaving the rest of each page empty.
    revised.refresh_from_db()
    assert len(unpack(revised.encrypted_data)['content']['sections']) == 3
    assert job.artifacts.get().file.page_count <= 3


def test_a_change_needs_something_to_change(premium):
    """An empty draft has no document yet, and a request has to say something."""
    empty = create_draft(premium, {'prompt': 'A guide to tide tables in 2 pages.'})
    with pytest.raises(DomainError) as caught:
        create_draft(premium, {'prompt': 'Make it shorter.',
                               'options': {'revise_draft_id': str(empty.id)}})
    assert caught.value.code == 'revision_not_ready'

    original = generated(premium)
    with pytest.raises(DomainError) as caught:
        create_draft(premium, {'prompt': '   ', 'options': {'revise_draft_id': str(original.id)}})
    assert caught.value.code == 'prompt_required'


def test_a_change_can_only_be_asked_for_on_your_own_document(premium, settings):
    original = generated(premium)
    stranger = paid(settings, account(43))
    with pytest.raises(DomainError) as caught:
        create_draft(stranger, {'prompt': 'Make it shorter.',
                                'options': {'revise_draft_id': str(original.id)}})
    assert caught.value.code == 'not_found'
    with pytest.raises(DomainError):
        create_draft(premium, {'prompt': 'Make it shorter.',
                               'options': {'revise_draft_id': 'not-a-uuid'}})


def test_a_change_can_itself_be_changed(premium):
    """Revisions chain: the second request applies to the first one's result."""
    original = generated(premium)
    first = create_draft(premium, {'prompt': 'Make it friendlier.',
                                   'options': {'revise_draft_id': str(original.id)}})
    quote = generation_quote(premium, first.id, first.version)
    job, _ = submit_job(premium, quote.id, f'revision-chain-{first.id}')
    assert execute_job(job.id).status == 'succeeded'
    first.refresh_from_db()

    second = create_draft(premium, {'prompt': 'Now make it shorter.',
                                    'options': {'revise_draft_id': str(first.id)}})
    payload = unpack(second.encrypted_data)
    assert payload['revision']['source_draft_id'] == str(first.id)
    assert payload['content']['sections'][0]['body'].strip()


def test_slides_are_revised_as_slides(premium):
    original = generated(premium, 'A 3 slide deck about tides.', SLIDES, 'pptx')
    revised = create_draft(premium, {'prompt': 'Make slide two punchier.',
                                     'options': {'revise_draft_id': str(original.id)}})
    payload = unpack(revised.encrypted_data)
    assert revised.feature_id == SLIDES and payload['output_format'] == 'pptx'
    # And the slide target, not the page one, still applies.
    from apps.studio.provider import writing_guidance
    guidance = writing_guidance({}, 3, 'pptx')
    assert 'one slide' in guidance and 'bullets, one per line' in guidance
    assert str(round(pages.target_words('pptx') * 1.3)) in guidance
