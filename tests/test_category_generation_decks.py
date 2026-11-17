"""A category deck made by the job, with the model stubbed (architecture 3.6, 7 and 11).

The job refuses a category it cannot make before any provider call: an id
the catalogue no longer holds is category_unknown (a paper category is made,
tests/test_category_generation_pdf.py). A deck is
written, checked by quality.finish with its repeating forms and fixed
headings spared (finish.exempt), held to the customer's words after
title_lines (finish.apply, which raises the warning facts_blanked when it
took something out), and drawn with its slots' variants on the first render
(finish.pins). validate_content is given the category's bounds at the job's
two sites and the repair's.

A deck without a category is today's: the golden request bodies, the deck
pins and quality tests pin that. The fixtures are the deck sample tool's
(tests/fixtures/categories/deck_himoya_*.json); every person, organisation
and figure in them is invented.
"""
import copy
import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.core.services import execute_job, submit_job
from apps.studio import domain, execution, photos as stock, provider, quality
from apps.studio.categories import catalogue, facts, finish, sample, skeleton
from apps.studio.domain import SLIDES, create_draft, generation_quote, unpack
from apps.studio.models import GenerationDraft, ProviderUsage
from operations.categories_settings import save as save_switch
from tests.test_category_drafts import ARIZA, HIMOYA, marked
from tests.test_operations import staff_client
from tests.test_page_fill import live

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).parent / 'fixtures' / 'categories'
SMOKE = Path(__file__).resolve().parents[1] / 'scripts' / 'operations' / 'ai_smoke.py'
USAGE = {'input_tokens': 1, 'output_tokens': 1}


def fixture(case):
    return json.loads((FIXTURES / f'deck_himoya_{case}.json').read_text(encoding='utf-8'))


@pytest.fixture
def switch(monkeypatch):
    """The three example entries ready, the switch on and every one ticked, as the owner does on /ops/categories."""
    marked(monkeypatch, 'ready')
    _, user = staff_client('Operations')
    save_switch({'on': 'true', 'live': [HIMOYA, ARIZA]}, user)


@pytest.fixture
def customer(settings, switch):
    return live(settings)


@pytest.fixture(autouse=True)
def no_photos(monkeypatch):
    monkeypatch.setattr(stock, 'fetch_for_deck', lambda sections, **kwargs: stock.PhotoResult())


class Model:
    """provider.generate as the job calls it: each request recorded, each answered with the sample's slides."""

    def __init__(self, monkeypatch, case='figures', change=None):
        self.case, self.change, self.calls = case, change, []
        monkeypatch.setattr(provider, 'generate', self)

    def __call__(self, config, data, feature_id, request_id, **kwargs):
        self.calls.append({'stage': data.get('_stage'), 'ids': [s['id'] for s in data['content']['sections']]})
        if data.get('_stage') == 'repair':
            return {'title': '', 'sections': copy.deepcopy(data['content']['sections']), 'questions': [],
                    'citations': []}, USAGE
        selected = (data.get('revision') or {}).get('selected_section_ids')
        if selected:
            # A change to selected slides comes back as the whole deck, the others exactly as they were.
            answer = copy.deepcopy(data['content'])
            for section in answer['sections']:
                if section['id'] in selected:
                    section['body'] = 'Xodimlar almashinuvi kamaydi.'
            return {**answer, 'answer_supported': True, 'edit_plan': []}, USAGE
        _, content = sample.draft(catalogue.get(HIMOYA), fixture(self.case), data['output_locale'],
                                  len(data['content']['sections']))
        answer = {**content, 'answer_supported': True}
        if self.change:
            self.change(answer)
        return answer, USAGE


def deck(who, case='figures', locale='uz', slides=10):
    prompt = fixture(case)['prompt'][locale]
    return create_draft(who, {'feature_id': SLIDES, 'prompt': prompt, 'output_locale': locale,
                              'options': {'category': HIMOYA, 'pages': slides}})


def queued(who, draft):
    quote = generation_quote(who, draft.id, draft.version)
    job, _ = submit_job(who, quote.id, f'category-{quote.id}')
    return job


def made(who, draft):
    job = execute_job(queued(who, draft).id)
    draft.refresh_from_db()
    return job, unpack(draft.encrypted_data)


def slot(data, section_id):
    uses = skeleton.parts(catalogue.get(HIMOYA), len(data['content']['sections']), skeleton.cues_of(data))
    return next(use.part for use in uses if use.section_id == section_id)


def lines(text):
    return [line for line in (text or '').split('\n') if line.strip()]


# ---------------------------------------------------------------- refused before the provider


def test_an_id_the_catalogue_no_longer_holds_fails_the_job_before_the_provider(customer, monkeypatch):
    model = Model(monkeypatch)
    job = queued(customer, deck(customer))
    # The catalogue rolled back while the job waited in the queue.
    marked(monkeypatch, 'ready', drop=[HIMOYA])
    job = execute_job(job.id)
    assert (job.status, job.error_code) == ('failed', 'category_unknown')
    assert model.calls == [] and not ProviderUsage.objects.filter(job=job).exists()


def test_a_job_without_a_category_never_reads_the_catalogue(monkeypatch):
    def unread():
        raise AssertionError('the catalogue was read for a draft without a category')
    monkeypatch.setattr(catalogue, '_catalogue', unread)
    assert execution._category({'options': {'length': 6}}) is None
    assert execution._category({'options': {}}) is None


# ---------------------------------------------------------------- made end to end


@pytest.mark.parametrize('locale', ['uz', 'ru', 'en'])
def test_a_deck_of_the_customers_own_figures_is_made_as_quoted_in_its_slots(customer, monkeypatch, locale):
    def astray(answer):
        # A model that wrote its own heading on a fixed slot and a layout the slot does not allow.
        answer['sections'][1].update(heading='Mening sarlavham', layout='image_full')
    model = Model(monkeypatch, change=astray)
    job, data = made(customer, deck(customer, locale=locale))
    assert job.status == 'succeeded', job.error_code
    assert len(model.calls) == 1, 'nothing was sent back to be repaired'
    sections = data['content']['sections']
    assert len(sections) == 10 and job.artifacts.get().file.page_count == 10
    for section in sections:
        part = slot(data, section['id'])
        assert section['layout'] in part['layouts']
        if part['heading_mode'] == 'fixed':
            assert section['heading'] == part['heading'][locale]
    assert 'facts_blanked' not in job.warnings
    # The lines the customer dictated for the title slide are all there.
    assert all(line in lines(sections[0]['body']) for line in lines(fixture('figures')['prompt'][locale])[-4:])


def test_a_topic_only_deck_loses_what_the_model_made_up_and_says_so(customer, monkeypatch):
    model = Model(monkeypatch, case='topic_only')
    job, data = made(customer, deck(customer, case='topic_only'))
    assert job.status == 'succeeded', job.error_code
    assert 'facts_blanked' in job.warnings
    text = json.dumps(data['content'], ensure_ascii=False)
    # The model's own figure, its "Toshkent — 2026" and its stand-in names never ship.
    assert '35' not in text and '2026' not in text and 'Rahbar' not in text
    assert facts.BLANK in text
    # The result slides are the same honest form by design: spared, they cost no repair call.
    assert len(finish.exempt(data)) >= 2
    assert [call['stage'] for call in model.calls] == [None]


def test_facts_blanked_is_the_bots_and_the_admins_never_a_clients(customer, monkeypatch):
    """The web shows a job's warning codes through its own words, and one it has none for appears raw.

    facts_blanked stays on the job, where the bot says it under the file in
    the category's words and the admin counts it, but the job a client reads
    (job_data, the jobs list and a workflow's jobs all use it) leaves it out.
    A warning the web knows still reaches it.
    """
    from apps.core.models import Job
    from apps.core.serializers import INTERNAL_WARNINGS, job_data, public_warnings, warning_codes
    from telegram.delivery import category_notices
    from tests.test_platform import login_client
    Model(monkeypatch, case='topic_only')
    job, _ = made(customer, deck(customer, case='topic_only'))
    assert finish.FACTS_BLANKED in INTERNAL_WARNINGS
    assert 'facts_blanked' in job.warnings and 'facts_blanked' in warning_codes(job)
    assert 'facts_blanked' not in public_warnings(job) and 'facts_blanked' not in job_data(job)['warnings']
    client = login_client(customer)
    assert 'facts_blanked' not in client.get(f'/api/v1/jobs/{job.id}').json()['warnings']
    assert all('facts_blanked' not in row['warnings'] for row in client.get('/api/v1/jobs').json()['results'])
    assert catalogue.get(HIMOYA).raw['bot']['notices']['blanks']['uz'] in category_notices(job, 'uz')
    Job.objects.filter(pk=job.pk).update(warnings=[*job.warnings, 'sections_trimmed'])
    job.refresh_from_db()
    assert client.get(f'/api/v1/jobs/{job.id}').json()['warnings'] == [
        code for code in job.warnings if isinstance(code, str) and code != 'facts_blanked']
    assert 'sections_trimmed' in job_data(job)['warnings']


def test_the_first_render_draws_the_variants_the_slots_name(customer, monkeypatch):
    seen = {}
    real = finish.pins

    def pins(data, content):
        seen.update(real(data, content).get('variants', {}))
        return real(data, content)
    monkeypatch.setattr(finish, 'pins', pins)
    Model(monkeypatch)
    job, data = made(customer, deck(customer))
    assert job.status == 'succeeded', job.error_code
    metadata = job.artifacts.get().file.metadata
    assert seen, 'the deck had pins to try'
    drawn = dict(zip([section['id'] for section in data['content']['sections']], metadata['variants']))
    held = {sid for sid, variant in seen.items() if drawn[sid] == variant}
    assert held | set(metadata['repinned']) >= set(seen), 'a pin is drawn, or gives way and is listed'
    assert held, 'pins hold their slides'


def test_a_change_to_a_category_deck_is_not_pinned_again(customer, monkeypatch):
    Model(monkeypatch)
    original, _ = made(customer, deck(customer))
    assert original.status == 'succeeded'
    drawn = []
    real = execution.render_pptx

    def render(*args, **kwargs):
        drawn.append(kwargs.get('pins'))
        return real(*args, **kwargs)
    monkeypatch.setattr(execution, 'render_pptx', render)
    draft = GenerationDraft.objects.get(pk=original.parameters['generation_draft_id'])
    revised = create_draft(customer, {'prompt': 'Xulosani qisqartiring.', 'options': {'revise_draft_id': str(draft.id)}})
    job, data = made(customer, revised)
    assert job.status == 'succeeded', job.error_code
    assert data['options']['category'] == HIMOYA and drawn == [None]


# ---------------------------------------------------------------- bounds at the three sites


def test_the_job_gives_validate_content_the_categorys_bounds_at_both_sites(customer, monkeypatch):
    """A deck's bounds are today's (None); what is checked is that the job passes on what categories.bounds says.

    The bounds are swapped for a marker only once the draft is made and
    quoted, so the domain's own sites (D1's) are left as they are.
    """
    marker = catalogue.Bounds(sections=61, items=41)
    given = []
    real = execution.validate_content

    def validate(*args, category=None, **kwargs):
        given.append(category)
        return real(*args, category=None, **kwargs)

    def bounded():
        monkeypatch.setattr(domain, '_bounds', lambda data: marker if (data.get('options') or {}).get('category') else None)
        monkeypatch.setattr(execution, 'validate_content', validate)
    Model(monkeypatch)
    job = queued(customer, deck(customer))
    bounded()
    original = execute_job(job.id)
    assert original.status == 'succeeded' and given == [marker], 'the model output site'
    monkeypatch.undo()
    Model(monkeypatch)
    monkeypatch.setattr(stock, 'fetch_for_deck', lambda sections, **kwargs: stock.PhotoResult())
    marked(monkeypatch, 'ready')
    draft = GenerationDraft.objects.get(pk=original.parameters['generation_draft_id'])
    selected = create_draft(customer, {'prompt': 'Xulosani qisqartiring.', 'options': {
        'revise_draft_id': str(draft.id), 'revise_section_ids': ['s9'], 'revise_base_version': draft.version}})
    job = queued(customer, selected)
    given.clear()
    bounded()
    job = execute_job(job.id)
    assert job.status == 'succeeded', job.error_code
    assert given == [marker, marker], 'the selected-preservation site, then the model output site'


def test_a_job_without_a_category_gives_today_s_bounds(settings, monkeypatch):
    who = live(settings)
    given = []
    real = execution.validate_content

    def validate(*args, category=None, **kwargs):
        given.append(category)
        return real(*args, category=category, **kwargs)
    monkeypatch.setattr(execution, 'validate_content', validate)
    monkeypatch.setattr(provider, 'generate', lambda *args, **kwargs: (
        {'title': 'Tides', 'answer_supported': True, 'citations': [], 'questions': [], 'sections': [
            {'id': 's1', 'heading': 'Tides', 'body': 'The Moon and the Sun', 'layout': 'cover'},
            {'id': 's2', 'heading': 'Why', 'body': 'Moon\nSun\nWater', 'layout': 'bullets'}]}, USAGE))
    draft = create_draft(who, {'feature_id': SLIDES, 'prompt': 'Two slides about tides', 'options': {'pages': 2}})
    job, _ = made(who, draft)
    assert job.status == 'succeeded', job.error_code
    assert given == [None]


@pytest.mark.parametrize('category, expected', [(ARIZA, catalogue.PAPER_BOUNDS), (HIMOYA, None), (None, None)])
def test_the_repair_gives_validate_content_the_categorys_bounds(customer, monkeypatch, category, expected):
    given = []
    real = domain.validate_content

    def validate(*args, category=None, **kwargs):
        given.append(category)
        return real(*args, category=category, **kwargs)
    monkeypatch.setattr(domain, 'validate_content', validate)
    sections = [{'id': 's1', 'heading': 'Kirish', 'body': ''}, {'id': 's2', 'heading': 'Asosiy', 'body': 'Matn.'}]
    monkeypatch.setattr(provider, 'generate', lambda *args, **kwargs: (
        {'title': 'x', 'sections': [{'id': 's1', 'heading': 'Kirish', 'body': 'Yozildi.'}], 'questions': [],
         'citations': []}, USAGE))
    monkeypatch.setattr(ProviderUsage.objects, 'create', lambda **kwargs: None)
    data = {'output_locale': 'uz', 'output_format': 'pdf', 'prompt': 'Mavzu',
            'options': {**({'category': category} if category else {})},
            'content': {'title': 'x', 'sections': sections, 'questions': [], 'citations': []}}
    job = SimpleNamespace(id='repair-test', account=customer, feature_id='ai.pdf_topic',
                          quote=SimpleNamespace(policy={'generation_bounds': {'input_tokens': 50_000}}))
    report = quality.Report()
    report.add('empty_section', 's1')
    repaired, outcome = quality.repair({'model': 'test-model'}, data, data['content'], report, job=job)
    assert outcome == 'repaired' and repaired['sections'][0]['body'] == 'Yozildi.'
    assert given == [expected]


# ---------------------------------------------------------------- quality exemptions


def forms():
    """A deck whose three result slides are the same honest form under one heading, as a topic-only himoya has them."""
    form = {'heading': 'Natija', 'body': 'Ko‘rsatkich: ____\nDavr: ____\nNatija: ____', 'layout': 'bullets'}
    return {'title': 'Himoya', 'sections': [
        {'id': 's1', 'heading': 'Kichik korxonada xodimlar almashinuvi', 'body': 'Bitiruv malakaviy ishi', 'layout': 'cover'},
        {'id': 's2', 'heading': 'Dolzarblik', 'body': 'Xodimlar almashinuvi kichik korxonalar uchun katta xarajat.\n'
                                                       'Har bir ketgan xodim o‘rniga yangisini o‘qitish kerak bo‘ladi.',
         'layout': 'bullets'},
        {'id': 's3', **form}, {'id': 's4', **form}, {'id': 's5', **form},
        {'id': 's6', 'heading': '', 'body': '', 'layout': 'bullets'}]}


def test_check_spares_the_exempt_slides_and_still_reports_the_rest():
    content = forms()
    plain = quality.check(content, locale='uz', fmt='pptx')
    assert set(plain.ids('repeated_heading', 'duplicate_section')) >= {'s4', 's5'}
    assert plain.ids('empty_section') == ['s6']
    spared = quality.check(content, locale='uz', fmt='pptx', exempt={'s3', 's4', 's5'})
    assert not spared.ids('repeated_heading', 'duplicate_section', 'duplicate_paragraph')
    assert spared.ids('empty_section') == ['s6'], 'a slide that is not exempt is still sent back'
    assert set(quality.check(content, locale='uz', fmt='pptx', exempt={'s6'}).ids('empty_section')) == set()


def test_an_exempt_section_is_never_sent_back_for_its_language_but_keeps_its_alphabet():
    """A paper's facts section holds what the customer wrote, in the language they wrote it (F2 will exempt it)."""
    facts_section = ('Заявитель: Нодира Саидова, бухгалтер отдела учёта.\nАдресат: директор общества Ботир Кодиров.\n'
                     'Срок отпуска: пять календарных дней начиная с десятого декабря.')
    content = {'title': 'Ariza', 'sections': [
        {'id': 'facts', 'heading': '', 'body': facts_section},
        {'id': 'matn', 'heading': 'Ariza', 'body': 'Sizdan 10-dekabrdan boshlab besh kunlik mehnat ta’tili berishingizni '
                                                     'so‘rayman. Ish vazifalarimni hamkasbimga topshiraman.'}]}
    brief = 'Ariza yozing: mehnat ta’tili uchun, besh kunga, buxgalteriya bo‘limidan'
    plain = quality.check(content, locale='uz', fmt='pdf', prompt=brief)
    assert plain.ids('wrong_language') == ['facts']
    spared = quality.check(content, locale='uz', fmt='pdf', prompt=brief, exempt={'facts'})
    assert not spared.to_repair()
    assert spared.ids('script') == [('sections', 0, 'body')], 'its alphabet is still put right'


def test_a_continuing_heading_after_an_exempt_part_is_still_read_as_continuing():
    content = {'title': 'x', 'sections': [
        {'id': 'jadval', 'heading': 'Narxlar', 'body': '', 'items': [{'label': 'Stol', 'text': '', 'value': '100'}]},
        {'id': 'davomi', 'heading': 'Narxlar', 'body': 'Narxlar qo‘shilgan qiymat solig‘isiz ko‘rsatilgan.'}]}
    report = quality.check(content, locale='uz', fmt='pdf', exempt={'jadval'})
    assert report.ids('continued_heading') == ['davomi']
    assert 'jadval' not in report.ids('continued_heading', 'empty_section', 'repeated_heading')


def test_finish_passes_the_exemptions_to_the_check_and_the_skip_to_the_deterministic_branch(monkeypatch):
    data = {'output_locale': 'uz', 'output_format': 'pptx', 'prompt': 'Himoya taqdimoti', 'options': {},
            'content': forms()}
    _, summary = quality.finish({}, data, forms(), job=None, mode='local', exempt={'s3', 's4', 's5'})
    assert not {'repeated_heading', 'duplicate_section'} & set(summary['found'])
    _, summary = quality.finish({}, data, forms(), job=None, mode='local')
    assert {'repeated_heading', 'duplicate_section'} & set(summary['found'])

    asked = []
    real = quality.enforce

    def enforce(content, locale, selected=None, skip=None):
        asked.append(skip)
        return real(content, locale, selected, skip=skip)
    monkeypatch.setattr(quality, 'enforce', enforce)
    marker = lambda part: set()  # noqa: E731
    quality.finish({}, data, forms(), job=None, deterministic=True, skip=marker)
    quality.finish({}, data, forms(), job=None, deterministic=True)
    assert asked == [marker, None]


# ---------------------------------------------------------------- ai_smoke --category


def smoke(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, 'argv', [str(SMOKE), *argv])
    with pytest.raises(SystemExit) as ended:
        runpy.run_path(str(SMOKE), run_name='__main__')
    return ended.value.code, capsys.readouterr().out


def test_the_smoke_makes_one_category_deck_through_the_real_pipeline(settings, monkeypatch, capsys, tmp_path):
    live(settings)
    model = Model(monkeypatch)
    # The message is now the entry's own sample, which asks for 6 slides; the count is given so the deck is the
    # fixture's ten whatever a sample's wording asks for.
    code, out = smoke(monkeypatch, capsys, '--category', HIMOYA, '--locale', 'uz', '--case', 'figures',
                      '--slides', '10', '--out', str(tmp_path))
    assert code == 0, out
    assert len(model.calls) == 1 and len(model.calls[0]['ids']) == 10
    assert 'FAIL' not in out and HIMOYA in out
    assert list(tmp_path.glob('*.pptx'))


def test_the_smoke_says_what_finish_took_out_and_names_an_unknown_id(settings, monkeypatch, capsys, tmp_path):
    # A paper is made by the smoke too since N2c (tests/test_category_letter_readiness.py).
    live(settings)
    Model(monkeypatch, case='topic_only')
    code, out = smoke(monkeypatch, capsys, '--category', HIMOYA, '--case', 'topic_only', '--slides', '6',
                      '--out', str(tmp_path))
    assert code == 0, out
    assert 'facts_blanked' in out
    code, out = smoke(monkeypatch, capsys, '--category', 'slides.gone')
    assert code == 1 and 'slides.gone is not in this catalogue' in out


def test_the_smoke_runs_every_deck_entry_under_a_prefix(settings, monkeypatch, capsys, tmp_path):
    live(settings)
    model = Model(monkeypatch)
    code, out = smoke(monkeypatch, capsys, '--category', 'slides.', '--slides', '6', '--out', str(tmp_path))
    decks = catalogue.for_feature(SLIDES)
    assert code == 0, out
    assert len(model.calls) == len(decks) and all(f'{entry.id} drawn' in out for entry in decks)
