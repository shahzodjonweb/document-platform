"""A document asked for in N pages comes out in N pages.

The word targets in apps/studio/pages.py were measured against the renderers
rather than estimated, and this renders for real so they cannot quietly drift:
if the default body size, leading or margins change, this fails and the targets
have to be measured again.
"""
import pytest

from apps.studio import pages
from apps.studio.domain import DOCUMENT, SLIDES, create_draft, generation_quote
from apps.studio.rendering import render_pdf, render_pptx
from apps.core.services import execute_job, submit_job
from tests.test_platform import account
from tests.test_studio import paid

pytestmark = pytest.mark.django_db


@pytest.fixture
def premium(settings):
    settings.DEBUG = True
    return paid(settings, account())


# Three word profiles, because a page fills by character and word length is
# what differs most between the locales this product serves.
PROSE = {
    'short': 'the tide rises twice a day and the range between high and low water changes'.split(),
    'long': 'consideration measurement observation understanding demonstration classification'.split(),
    'russian': 'приливы поднимаются дважды в сутки а разница между полной и малой водой'.split(),
}


def body_of(chars, profile='short'):
    words, out, total = PROSE[profile], [], 0
    while total < chars:
        word = words[len(out) % len(words)]
        out.append(word)
        total += len(word) + 1
    return ' '.join(out)


def filled(chars, sections, profile='short'):
    """A document whose every section holds one page of prose."""
    body = body_of(chars, profile)
    return {'title': 'Measured', 'questions': [], 'citations': [],
            'sections': [{'id': f's{i}', 'heading': f'Section {i + 1}', 'body': body, 'notes': ''}
                         for i in range(sections)]}


@pytest.mark.parametrize('sections', [1, 3, 5, 8])
@pytest.mark.parametrize('profile', list(PROSE))
def test_a_section_at_the_target_is_exactly_one_page(tmp_path, sections, profile):
    result = render_pdf(filled(pages.CHARS_PER_PAGE, sections, profile),
                        tmp_path / f'{profile}-{sections}.pdf')
    assert result['page_count'] == sections, f'{profile} prose at the target must not spill'


@pytest.mark.parametrize('sections', [1, 3, 5, 8])
def test_a_section_at_the_slide_target_is_exactly_one_slide(tmp_path, sections):
    result = render_pptx(filled(pages.CHARS_PER_SLIDE, sections), tmp_path / f'{sections}.pptx')
    assert result['page_count'] == sections


def test_a_short_section_still_gets_its_own_page(tmp_path):
    """The count is a promise: a model that writes short leaves whitespace,
    it does not quietly hand back fewer pages than were asked for."""
    assert render_pdf(filled(200, 5), tmp_path / 'sparse.pdf')['page_count'] == 5
    assert render_pptx(filled(60, 5), tmp_path / 'sparse.pptx')['page_count'] == 5


def test_a_description_asking_for_pages_produces_that_many(premium):
    """End to end: the brief names three pages and three pages come back."""
    # One paragraph per page, and the brief rides on the first of them: local
    # authoring splits the source on blank lines and the last section absorbs
    # whatever is left over.
    chunks = [body_of(pages.CHARS_PER_PAGE - 100) for _ in range(3)]
    chunks[0] = f'A 3 page guide. {chunks[0]}'
    draft = create_draft(premium, {'feature_id': DOCUMENT, 'title': 'Measured',
                                   'source_text': '\n\n'.join(chunks)})
    quote = generation_quote(premium, draft.id, draft.version)
    job, _ = submit_job(premium, quote.id, f'page-fill-doc-{draft.id}')
    job = execute_job(job.id)

    assert job.status == 'succeeded', job.error_code
    assert job.artifacts.get().file.page_count == 3


def test_the_quote_reserves_a_page_of_headroom(premium):
    """A section written to fill its page may spill; a paid job must survive it."""
    draft = create_draft(premium, {'feature_id': DOCUMENT, 'source_text': 'A 4 page guide to tides.'})
    quote = generation_quote(premium, draft.id, draft.version)
    assert quote.policy['generation_bounds']['output_pages'] == 5


def test_slides_and_documents_get_their_own_target():
    assert pages.chars_per_page('pdf') == pages.CHARS_PER_PAGE
    assert pages.chars_per_page('pptx') == pages.CHARS_PER_SLIDE
    assert pages.CHARS_PER_SLIDE < pages.CHARS_PER_PAGE, 'a slide holds far less than a page'


def test_the_page_ceiling_is_what_one_response_can_hold(premium):
    assert pages.response_tokens(pages.MAX_PAGES) <= pages.RESPONSE_CEILING
    assert pages.response_tokens(pages.MAX_PAGES + 1) == pages.RESPONSE_CEILING
    # Premium allows 30 pages, but one response cannot hold 30 full ones.
    assert pages.ceiling(premium, 'pdf') == pages.MAX_PAGES


@pytest.mark.parametrize('description,expected', [
    ('A 12 page report', 12), ('12-page report', 12), ('Explain tides in 7 pages', 7),
    ('Make 8 slides', 8), ('6 ta slayd tayyorla', 6), ('7 sahifa matn', 7),
    ('12 betlik hujjat', 12), ('Отчёт на 9 страниц', 9), ('Сделай 4 слайда', 4),
    ('a five page guide', 5), ('Besh sahifa matn', 5), ('Документ на пять страниц', 5),
    ('Tide tables explained', None), ('Chapter 3 of the manual', None),
    ('на 9 строк о приливах', None), ('0 pages', None),
])
def test_the_page_count_is_read_from_three_languages(description, expected):
    assert pages.requested_pages(description) == expected


def test_a_slide_deck_counts_slides_not_pages(premium):
    draft = create_draft(premium, {'feature_id': SLIDES, 'output_format': 'pptx',
                                   'source_text': 'Make 9 slides about tides.'})
    from apps.studio.domain import unpack
    assert unpack(draft.encrypted_data)['options']['length'] == 9
