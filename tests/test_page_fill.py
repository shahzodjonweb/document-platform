"""A document asked for in N pages comes out in N pages.

The word targets in apps/studio/pages.py were measured against the renderers
rather than estimated, and this renders for real so they cannot quietly drift:
if the default body size, leading or margins change, this fails and the targets
have to be measured again.
"""
import pytest
from django.utils import timezone

from apps.studio import pages
from apps.studio.domain import DOCUMENT, SLIDES, create_draft, draft_data, generation_quote
from pypdf import PdfReader
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


def test_the_plan_is_the_only_page_ceiling(premium):
    """What a plan sells is what a customer gets.

    A document too long for one response is written in several; nothing about
    how it is produced is allowed to quietly reduce the count.
    """
    from apps.core.policy import plan_limits
    allowed = plan_limits(premium)['max_generated_pdf_pages']
    assert pages.ceiling(premium, 'pdf') == allowed
    assert pages.resolve(premium, f'A {allowed} page report', 'pdf') == (allowed, allowed)
    # And every call stays inside one response, however long the document is.
    spans = pages.batches(allowed)
    assert [last - first for first, last in spans] == [
        min(pages.PAGES_PER_CALL, allowed - i * pages.PAGES_PER_CALL) for i in range(len(spans))]
    for first, last in spans:
        assert pages.response_tokens(last - first) <= pages.RESPONSE_CEILING
    assert [first for first, _ in spans] == sorted(first for first, _ in spans)
    assert spans[0][0] == 0 and spans[-1][1] == allowed


@pytest.mark.parametrize('overshoot', [0, 5, 10, 15, 20])
@pytest.mark.parametrize('profile', list(PROSE))
def test_a_model_writing_over_the_target_still_fills_exactly_one_page(tmp_path, overshoot, profile):
    """The target leaves room for the overshoot that always happens.

    A model told "about N characters" lands over it, and every section overshoots
    together — so asking for the page's full capacity put all five sections on
    the spill threshold at once and a five-page document rendered as ten. The
    target is set below capacity to absorb that; this is the margin.
    """
    written = int(pages.target_chars('pdf') * (1 + overshoot / 100))
    result = render_pdf(filled(written, 5, profile), tmp_path / f'{profile}-{overshoot}.pdf')
    assert result['page_count'] == 5, f'{profile} prose {overshoot}% over the target spilled'


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


def live(settings):
    """The paid path, with the provider stubbed rather than called."""
    from operations.integrations import save_config
    settings.DEBUG = True
    settings.LOCAL_SYNC_JOBS = True
    save_config('ai', {'mode': 'openai', 'model': 'test-model', 'api_key': 'sk-offline-test'})
    return paid(settings, account())


def test_the_top_plan_gets_every_page_it_is_sold(settings, monkeypatch):
    """A plan that offers 35 pages has to deliver 35 pages.

    Before this, the page count was capped at what one provider response could
    hold — 13 — so the top plan's own limit was unreachable and asking for it
    silently produced less.
    """
    from apps.core.policy import plan_limits
    from apps.studio import provider
    customer = live(settings)
    allowed = plan_limits(customer)['max_generated_pdf_pages']
    def one_call(config, data, fid, key, *, token_limit, span=None, **rest):
        first, last = span or (0, len(data['content']['sections']))
        return (filled(pages.target_chars('pdf'), last - first) | {'answer_supported': True},
                {'input_tokens': 100, 'output_tokens': 100})

    monkeypatch.setattr(provider, '_call', one_call)

    draft = create_draft(customer, {'feature_id': DOCUMENT,
                                    'prompt': f'A {allowed} page guide to tide tables.'})
    assert len(draft_data(draft)['content']['sections']) == allowed, 'the full count is quoted'
    quote = generation_quote(customer, draft.id, draft.version)
    job, _ = submit_job(customer, quote.id, f'top-plan-{draft.id}')
    job = execute_job(job.id)

    assert job.status == 'succeeded', job.error_code
    assert job.artifacts.get().file.page_count == allowed


@pytest.mark.parametrize('overshoot,shortening', [(1.5, False), (3.0, True)])
def test_a_model_writing_over_the_target_still_gets_the_pages_that_were_asked_for(
        settings, monkeypatch, overshoot, shortening):
    """Five pages asked for is five pages delivered, whatever the model writes.

    A model told to fill a page overshoots, and because every section gets the
    same instruction they overshoot together — so a five-page document came back
    in ten, one section spilling onto a second page each time. The page count is
    what was asked for and billed for, so the renderer holds it: the document is
    set tighter, and only when that is not enough is a section shortened, which
    the customer is told about.
    """
    from apps.core.models import UsageLedger
    from apps.studio import provider
    customer = live(settings)
    monkeypatch.setattr(provider, 'generate', lambda *args, **kwargs: (
        filled(int(pages.CHARS_PER_PAGE * overshoot), 5) | {'answer_supported': True},
        {'input_tokens': 100, 'output_tokens': 100}))

    draft = create_draft(customer, {'feature_id': DOCUMENT, 'prompt': 'A 5 page guide to tides.'})
    quote = generation_quote(customer, draft.id, draft.version)
    job, _ = submit_job(customer, quote.id, f'overshoot-{overshoot}-{draft.id}')
    job = execute_job(job.id)

    assert job.status == 'succeeded', job.error_code
    assert job.artifacts.get().file.page_count == 5, 'the count asked for is the count delivered'
    assert ('shortened_to_fit' in job.warnings) is shortening, job.warnings
    assert 'longer_than_quoted' not in job.warnings
    consumed = sum(UsageLedger.objects.filter(job=job, kind='consume', meter='ai_credits')
                   .values_list('amount', flat=True))
    assert consumed <= quote.meters['ai_credits'], 'billed at the quote, never above it'


def test_a_long_document_is_given_a_lease_long_enough_to_finish_it(settings, monkeypatch):
    """The worker must still hold the job when the last call comes back.

    A document written in five provider calls cannot finish inside the ten
    minutes a file task gets: the reclaim sweep would take the job back and throw
    away work the customer had already paid for. The quote says how long it needs
    and the runner honours it, within bounds that stop a bad value from parking a
    worker forever.
    """
    import time
    from apps.core.models import Job
    from apps.studio import provider
    customer = live(settings)
    seen = {}

    def stubbed(config, data, feature_id, request_id, *, token_limit, deadline=None):
        row = Job.objects.get(pk=request_id)
        seen['lease'] = (row.lease_expires_at - timezone.now()).total_seconds()
        seen['deadline'] = deadline - time.monotonic() if deadline else None
        return filled(pages.target_chars('pdf'), len(data['content']['sections'])) | {'answer_supported': True}, \
            {'input_tokens': 1, 'output_tokens': 1}

    monkeypatch.setattr(provider, 'generate', stubbed)
    long_draft = create_draft(customer, {'feature_id': DOCUMENT, 'prompt': 'A 30 page guide to tides.'})
    quote = generation_quote(customer, long_draft.id, long_draft.version)
    assert len(pages.batches(30)) > 1, 'thirty pages must take more than one call'
    assert quote.policy['lease_seconds'] > 600, 'and must ask for more than a file task gets'
    job, _ = submit_job(customer, quote.id, f'lease-{long_draft.id}')
    job = execute_job(job.id)

    assert job.status == 'succeeded', job.error_code
    assert seen['lease'] > 600, 'the runner gave the job the lease its quote asked for'
    assert 0 < seen['deadline'] < seen['lease'], 'and the calls must finish inside it, with room to render'

    # A short document is unchanged: it keeps the ordinary lease.
    short = create_draft(customer, {'feature_id': DOCUMENT, 'prompt': 'A 3 page guide to tides.'})
    short_quote = generation_quote(customer, short.id, short.version)
    assert short_quote.policy['lease_seconds'] <= 600


def test_a_nonsense_lease_on_a_quote_cannot_park_a_worker(settings, monkeypatch):
    """The lease is read off the quote, so it is bounded on the way in.

    Without bounds a quote could hand a worker a lease of years (parking it on one
    job) or of nothing (losing a job that was still working).
    """
    from apps.core.models import Job
    from apps.studio import provider
    customer = live(settings)
    seen = {}

    def stubbed(config, data, feature_id, request_id, **rest):
        row = Job.objects.get(pk=request_id)
        seen['lease'] = (row.lease_expires_at - timezone.now()).total_seconds()
        return filled(100, 1) | {'answer_supported': True}, {'input_tokens': 1, 'output_tokens': 1}

    monkeypatch.setattr(provider, 'generate', stubbed)
    for requested, expected in ((10 ** 9, 2400), (-5, 600), ('forever', 600), (None, 600)):
        draft = create_draft(customer, {'feature_id': DOCUMENT, 'prompt': 'A 1 page note.'})
        quote = generation_quote(customer, draft.id, draft.version)
        quote.policy = {**quote.policy, 'lease_seconds': requested}
        quote.save(update_fields=['policy'])
        job, _ = submit_job(customer, quote.id, f'lease-bound-{requested}')
        assert execute_job(job.id).status == 'succeeded'
        assert abs(seen['lease'] - expected) < 60, \
            f'a lease of {requested!r} must be held to {expected}s, not {seen["lease"]:.0f}s'


@pytest.mark.parametrize('chars', [600, 2550, 4000, 8000, 16000])
@pytest.mark.parametrize('profile', list(PROSE))
def test_five_sections_are_five_pages_however_much_the_model_writes(tmp_path, chars, profile):
    """The page count cannot depend on how much prose the model chose to write.

    It is what the customer asked for and what they were billed for, so the
    renderer holds it: the document is set tighter, and a section is shortened
    only when the smallest readable setting still cannot hold it.
    """
    result = render_pdf(filled(chars, 5, profile), tmp_path / f'{profile}-{chars}.pdf')
    assert result['page_count'] == 5, f'{chars} chars of {profile} prose did not keep to five pages'
    # Shortening is the last resort, never the first: ordinary overshoot is absorbed.
    assert result['shortened'] is (chars > 5000), result


@pytest.mark.parametrize('chars', [200, 650, 1400, 8000])
def test_five_sections_are_five_slides_however_much_the_model_writes(tmp_path, chars):
    result = render_pptx(filled(chars, 5), tmp_path / f'{chars}.pptx')
    assert result['page_count'] == 5, f'{chars} chars per section did not keep to five slides'


def test_shortening_cuts_whole_sentences_and_says_so(tmp_path):
    """A shortened section ends at a sentence, not mid-word, and shows it."""
    from apps.studio.rendering import render_pdf as render
    sentences = [f'This is sentence number {n} of a section far longer than its page.' for n in range(300)]
    long_section = {'title': 'Measured', 'questions': [], 'citations': [],
                    'sections': [{'id': 's1', 'heading': 'One', 'body': ' '.join(sentences), 'notes': ''}]}
    result = render(long_section, tmp_path / 'cut.pdf')
    assert result['page_count'] == 1 and result['shortened']
    text = ''.join(page.extract_text() for page in PdfReader(tmp_path / 'cut.pdf').pages)
    assert '…' in text, 'the reader can see the text was cut'
    kept = text.split('…')[0].rstrip()
    assert kept.endswith('page.'), f'cut mid-sentence: {kept[-60:]!r}'
