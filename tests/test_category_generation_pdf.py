"""A category paper made by the job, with the model stubbed (architecture 3.6, 6.7 and 13, X2).

The job writes a category paper, checks it (quality.finish with its parts
spared), holds it to the customer's words (finish.apply) and draws it with
`draw_paper`: in its own template when this worker holds every block of it,
else the emergency fallback, today's renderer drawing finish.plain's
projection held to more pages than it was quoted at and marked
`template_fallback`. A paper that fills a count of pages and came out short
has its ungrounded elastic prose, and only that, written further once under
the category's rules; what that wrote is finished again before the same draw.
A ceiling paper is never topped up. The read-back is today's.

A PDF without a category is today's exactly: it never reaches the paper
engine, and render_pdf is called with the arguments it always was.

The real blocks are R1's and the families'; these tests register the paper
engine test's stand-in blocks, so they hold the job to its contract whatever
the blocks draw. `pdf.xat.toldirma` is an invented entry built beside the
real catalogue for the test only, a count paper with a grounded part, a
sources list and a signature. Every person, organisation and source here is
invented.
"""
import copy
import json
import re

import pdfplumber
import pytest

from apps.core.services import execute_job, submit_job
from apps.studio import execution, filling, paper, provider, rendering
from apps.studio.categories import catalogue, finish
from apps.studio.categories.catalogue import build, read
from apps.studio.categories.prompting import block
from apps.studio.domain import DOCUMENT, create_draft, generation_quote, unpack
from apps.studio.models import ProviderUsage
from apps.studio.paper import registry
from apps.studio.paper.registry import Block
from operations.categories_settings import save as save_switch
from tests.test_category_drafts import APPLICATION, ARIZA, text_upload
from tests.test_operations import staff_client
from tests.test_page_fill import live
from tests.test_paper_engine import STAND_INS
from tests.test_provider_optimization import transport

pytestmark = pytest.mark.django_db

TOLDIRMA = 'pdf.xat.toldirma'
USAGE = {'input_tokens': 1, 'output_tokens': 1}
CYRILLIC = re.compile('[Ѐ-ӿ]')
SOURCE = 'Каримов А. Иқтисодиёт асослари. Тошкент, 2019.'
FILE_NAME = 'Манбалар рўйхати.txt'
PROMPT = ('Namuna kolleji direktori Jasur Olimovga to‘ldirma xat: o‘quv amaliyoti haqida. Yozuvchi: Dilnoza '
          'Rahimova. Manbalar:\n1. ' + SOURCE)
INTRO = ('O‘quv amaliyoti talabaning bilimini amalda sinash imkonini beradi. Amaliyot davomida talaba ish '
         'jarayoni bilan tanishadi va o‘z kasbining asosiy vazifalarini o‘rganadi.')
LETTER = 'Jasur Olimovga o‘quv amaliyoti haqidagi ushbu xatni yuboraman.'
# What a top-up must never ship: a quotation and a law the customer never gave.
INVENTED = ('«Amaliyot bilimning eng yaxshi ustozidir» degan gap bor.\nO‘zbekiston Respublikasining 777-sonli '
            'qonuniga ko‘ra amaliyot majburiydir.')


def text3(uz, ru, en):
    return {'uz': uz, 'ru': ru, 'en': en}


def ready_with(monkeypatch, *, toldirma=False):
    """Every entry ready (as N2 marks them), optionally beside the invented count paper; the switch on, all ticked."""
    entries, templates, index = copy.deepcopy(read())
    if toldirma:
        raw = copy.deepcopy(entries[ARIZA])
        children = index['groups']['pdf.xat']['children']
        children.insert(children.index('other'), TOLDIRMA)
        signature = next(part for part in raw['parts'] if part['id'] == 'signature')
        raw.update(
            id=TOLDIRMA, order=children.index(TOLDIRMA) + 1, fill=True, quality='fixed', templates=['official_toldirma'],
            labels=text3('📝 To‘ldirma xat', '📝 Дополнительное письмо', '📝 Supplementary letter'),
            length={'unit': 'pages', 'mode': 'count', 'target': 'count', 'default': 2, 'min': 1, 'max': 5},
            parts=[
                {'id': 'kirish', 'kind': 'prose', 'heading': text3('Kirish', 'Введение', 'Introduction'),
                 'heading_mode': 'fixed', 'need': 'required', 'share': 0.5, 'elastic': True,
                 'write': 'What the practice is.'},
                {'id': 'maktub', 'kind': 'prose', 'heading': None, 'heading_mode': 'none', 'need': 'required',
                 'share': 0.2, 'elastic': True, 'grounded': True, 'words': [25, 90], 'write': 'The letter itself.'},
                {'id': 'manbalar', 'kind': 'sources', 'heading': text3('Manbalar', 'Источники', 'Sources'),
                 'heading_mode': 'fixed', 'need': 'optional', 'share': 0.1, 'write': 'The sources given.'},
                signature])
        entries[TOLDIRMA] = raw
        template = copy.deepcopy(templates['official_ariza'])
        template.update(id='official_toldirma', entries=[TOLDIRMA], page_rule={'kind': 'count'}, flow=[
            {'block': 'paragraph', 'part': 'kirish'},
            {'block': 'paragraph', 'part': 'maktub'},
            {'block': 'list', 'part': 'manbalar', 'when': 'part:manbalar'},
            {'block': 'signature_row', 'part': 'signature', 'fields': ['date_written', 'signer_name'],
             'keep': 'closing'}])
        templates['official_toldirma'] = template
    for raw in entries.values():
        raw['status'] = 'ready'
    made = build(entries, templates, index)
    monkeypatch.setattr(catalogue, '_catalogue', lambda: made)
    _, user = staff_client('Operations')
    save_switch({'on': 'true', 'live': [ARIZA] + ([TOLDIRMA] if toldirma else [])}, user)
    return made


@pytest.fixture
def blocks(monkeypatch):
    """The paper engine test's stand-ins registered as the blocks the templates draw with."""
    for name, function in STAND_INS.items():
        monkeypatch.setitem(registry.BLOCKS, name, Block(name, function))


@pytest.fixture
def no_blocks(monkeypatch):
    """No block registered, whatever modules have landed: every template is drawn by the emergency fallback."""
    for name in list(registry.BLOCKS):
        monkeypatch.delitem(registry.BLOCKS, name)


class Model:
    """provider.generate as the job calls it: each call recorded, each answered by filling the seeded sections."""

    def __init__(self, monkeypatch, **sections):
        self.sections, self.calls = sections, []
        monkeypatch.setattr(provider, 'generate', self)

    def __call__(self, config, data, feature_id, request_id, **kwargs):
        self.calls.append([section['id'] for section in data['content']['sections']])
        made = []
        for seeded in data['content']['sections']:
            section = copy.deepcopy(seeded)
            section.update(copy.deepcopy(self.sections.get(seeded['id'], {})))
            made.append(section)
        return {'title': 'Xat', 'answer_supported': True, 'sections': made, 'questions': [],
                'citations': copy.deepcopy(self.sections.get('citations', []))}, USAGE


def facts(**values):
    return {'items': [{'label': key, 'text': value} for key, value in values.items()]}


def ariza_answer():
    """The ariza as the model writes it: the customer's facts, and one name they never gave."""
    return {'facts': facts(addressee_org='“Yashil vodiy” MChJ', addressee_position='direktori Botir Qodirovga',
                           applicant_name='Nodira Saidovadan', applicant_role='buxgalter',
                           signer_name='Sherzod Tursunov'),
            'request': {'body': 'Sizdan 10-dekabrdan boshlab 5 kunlik mehnat ta’tili berishingizni so‘rayman.'}}


def queued(who, draft):
    quote = generation_quote(who, draft.id, draft.version)
    job, _ = submit_job(who, quote.id, f'paper-{quote.id}')
    return job


def made(who, draft):
    job = execute_job(queued(who, draft).id)
    draft.refresh_from_db()
    return job, unpack(draft.encrypted_data)


def text_of(path):
    with pdfplumber.open(path) as document:
        return '\n'.join(page.extract_text() or '' for page in document.pages)


@pytest.fixture
def kept(monkeypatch, tmp_path):
    """A copy of every PDF the job draws, so its words can be read after the job's own folder is gone."""
    copies = []
    real = execution.draw_paper

    def keep(*args, **kwargs):
        artifact = real(*args, **kwargs)
        target = tmp_path / f'drawn-{len(copies)}.pdf'
        target.write_bytes(open(artifact['path'], 'rb').read())
        copies.append((artifact, target))
        return artifact
    monkeypatch.setattr(execution, 'draw_paper', keep)
    return copies


# ---------------------------------------------------------------- without a category


def test_a_pdf_without_a_category_never_reaches_the_paper_engine_and_is_drawn_as_today(settings, monkeypatch):
    who = live(settings)

    def never(*args, **kwargs):
        raise AssertionError('a document without a category reached the paper engine')
    monkeypatch.setattr(paper, 'render_paper', never)
    monkeypatch.setattr(execution, 'draw_paper', never)
    monkeypatch.setattr(catalogue, '_catalogue', never)
    calls = []
    real = execution.render_pdf

    def recorded(*args, **kwargs):
        calls.append((args, kwargs))
        return real(*args, **kwargs)
    monkeypatch.setattr(execution, 'render_pdf', recorded)
    monkeypatch.setattr(provider, 'generate', lambda *args, **kwargs: (
        {'title': 'Tides', 'answer_supported': True, 'citations': [], 'questions': [], 'sections': [
            {'id': 's1', 'heading': 'Tides', 'body': 'The Moon pulls the sea. ' * 40},
            {'id': 's2', 'heading': 'Why', 'body': 'The Sun pulls it too. ' * 40}]}, USAGE))
    monkeypatch.setattr(filling, 'top_up', lambda config, data, content, *args, **kwargs: content)
    draft = create_draft(who, {'feature_id': DOCUMENT, 'prompt': 'Two pages about tides', 'options': {'pages': 2}})
    job, _ = made(who, draft)
    assert job.status == 'succeeded', job.error_code
    # Exactly today's call: content, path, locale and role, then the style and the photos, never `pages`.
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert len(args) == 4 and args[2:] == ('en', 'user_document') and args[1].name == 'document.pdf'
    assert set(kwargs) == {'style', 'photos'}
    assert 'template_fallback' not in json.dumps(job.artifacts.get().file.metadata)


def test_render_pdf_without_pages_holds_a_document_to_its_sections_as_before(tmp_path):
    content = {'title': 'Tides', 'questions': [], 'citations': [], 'sections': [
        {'id': f's{n}', 'heading': f'Part {n}', 'body': 'The Moon pulls the sea toward it every day. ' * 300}
        for n in range(1, 3)]}
    before = rendering.render_pdf(content, tmp_path / 'a.pdf', 'en')
    same = rendering.render_pdf(content, tmp_path / 'b.pdf', 'en', pages=None)
    assert before['shortened'] and before['page_count'] <= 2
    assert (same['page_count'], same['shortened'], same['metadata']) == (before['page_count'], True, before['metadata'])
    assert text_of(same['path']) == text_of(before['path'])
    # Held to more pages, the same document is drawn whole: the fit never cuts it.
    whole = rendering.render_pdf(content, tmp_path / 'c.pdf', 'en', pages=20)
    assert not whole['shortened'] and whole['page_count'] > before['page_count']


# ---------------------------------------------------------------- a category paper


def test_a_paper_category_is_made_in_its_template_and_never_topped_up_as_a_ceiling(settings, monkeypatch, blocks,
                                                                                    kept):
    who = live(settings)
    ready_with(monkeypatch)
    model = Model(monkeypatch, **ariza_answer())
    topped = []
    monkeypatch.setattr(filling, 'top_up', lambda *args, **kwargs: topped.append(1))
    draft = create_draft(who, {'feature_id': catalogue.get(ARIZA).feature_id, 'prompt': APPLICATION,
                               'options': {'category': ARIZA}})
    job, data = made(who, draft)
    assert job.status == 'succeeded', job.error_code
    assert len(model.calls) == 1 and ProviderUsage.objects.filter(job=job, outcome='succeeded').exists()
    assert topped == [], 'a ceiling paper is never written further'
    [(artifact, copy_)] = kept
    metadata = artifact['metadata']
    assert (metadata['category'], metadata['template']) == (ARIZA, 'official_ariza')
    assert 'template_fallback' not in metadata and job.artifacts.get().file.page_count == 1
    # The signer the customer never named is not kept, and the job says it blanked something.
    assert 'facts_blanked' in job.warnings
    words = text_of(copy_)
    assert 'Sherzod' not in words and 'Nodira Saidova' in words and '10-dekabrdan' in words
    stored = json.dumps(data['content'], ensure_ascii=False)
    assert 'Sherzod' not in stored


def test_without_its_blocks_a_paper_is_the_emergency_fallback_on_todays_renderer(settings, monkeypatch, no_blocks,
                                                                                 kept):
    who = live(settings)
    ready_with(monkeypatch)
    Model(monkeypatch, **ariza_answer())
    sizes = []
    real = execution.render_pdf

    def recorded(*args, **kwargs):
        sizes.append(kwargs.get('pages'))
        return real(*args, **kwargs)
    monkeypatch.setattr(execution, 'render_pdf', recorded)
    draft = create_draft(who, {'feature_id': catalogue.get(ARIZA).feature_id, 'prompt': APPLICATION,
                               'options': {'category': ARIZA}})
    job, data = made(who, draft)
    assert job.status == 'succeeded', job.error_code
    [(artifact, copy_)] = kept
    assert artifact['metadata']['template_fallback'] is True and 'template_fallback' in artifact['metadata']['warnings']
    assert artifact['metadata']['category'] == ARIZA
    # Held to its sections or the quoted page and one more, whichever is more: never cut.
    projected = finish.plain(data, data['content'])
    assert sizes == [max(len(projected['sections']), 2)] and not artifact['shortened']
    words = text_of(copy_)
    assert 'Nodira Saidova' in words and '10-dekabrdan' in words and 'Sherzod' not in words


def test_draw_paper_never_prints_the_citation_lines(tmp_path, monkeypatch, no_blocks):
    ready_with(monkeypatch)
    entry = catalogue.get(ARIZA)
    data = {'options': {'category': ARIZA, 'length': 1}, 'prompt': APPLICATION, 'output_locale': 'uz',
            'output_format': 'pdf', 'source_ids': [], 'excerpts': []}
    content = {'title': 'Ariza', 'questions': [], 'sections': [
        {'id': 'facts', 'heading': '', 'body': '', 'layout': 'list', 'items': [
            {'label': 'applicant_name', 'text': 'Nodira Saidovadan'}]},
        {'id': 'request', 'heading': '', 'body': 'Sizdan mehnat ta’tili berishingizni so‘rayman.', 'layout': 'text',
         'items': []}],
        'citations': [{'asset_id': 'abcdef12-0000-0000-0000-000000000000', 'page': 1, 'quote': 'mehnat'}]}
    artifact = execution.draw_paper(data, content, tmp_path / 'document.pdf')
    assert artifact['metadata']['template_fallback'] is True and entry.id == artifact['metadata']['category']
    words = text_of(artifact['path'])
    assert 'Nodira Saidovadan' in words and 'abcdef12' not in words and 'Manba' not in words


# ---------------------------------------------------------------- the top-up of a count paper


def toldirma_answer(**more):
    answer = {'facts': facts(signer_name='Dilnoza Rahimova'), 'kirish': {'body': INTRO},
              'maktub': {'body': LETTER}, 'manbalar': {'items': [{'label': '1', 'text': SOURCE, 'value': ''}]}}
    answer.update(more)
    return answer


def test_a_short_count_paper_tops_up_only_its_ungrounded_prose_and_finishes_it_again(settings, monkeypatch, blocks,
                                                                                    kept):
    who = live(settings)
    ready_with(monkeypatch, toldirma=True)
    model = Model(monkeypatch, **toldirma_answer())
    sent = []

    def handler(body, number):
        assert body['text']['format']['name'] == 'additions', 'only the top-up reaches the network'
        sent.append(body)
        payload = json.loads(body['input'])
        # The model adds to a part it was not asked for too; that addition is never kept.
        return {'sections': [{'id': 'kirish', 'addition': (INTRO + '\n') * 14 + INVENTED},
                             {'id': 'maktub', 'addition': 'Botir Qodirov 1 500 000 so‘m to‘ladi.'},
                             *({'id': s['id'], 'addition': ''} for s in payload['sections'] if s['id'] != 'kirish')]}
    transport(monkeypatch, handler)
    draft = create_draft(who, {'feature_id': catalogue.get(TOLDIRMA).feature_id, 'prompt': PROMPT,
                               'options': {'category': TOLDIRMA}})
    job, data = made(who, draft)
    assert job.status == 'succeeded', job.error_code
    assert len(model.calls) == 1 and len(sent) == 1
    body = sent[0]
    payload = json.loads(body['input'])
    assert [s['id'] for s in payload['sections']] == ['kirish'], 'only the ungrounded elastic prose is sent'
    assert body['instructions'].startswith(filling.CATEGORY_INSTRUCTIONS)
    assert block(catalogue.get(TOLDIRMA)) in body['instructions'] and 'facts,' not in body['instructions']
    assert {s['heading'] for s in payload.get('other_sections', [])} <= {''}, 'other parts go along in brief'
    # Drawn twice, alike: the second draw holds what the top-up wrote, finished again.
    assert len(kept) == 2 and kept[1][0]['page_count'] > kept[0][0]['page_count']
    sections = {s['id']: s for s in data['content']['sections']}
    assert sections['kirish']['body'].count(INTRO) > 1
    assert '«' not in sections['kirish']['body'] and '777' not in sections['kirish']['body']
    assert sections['maktub']['body'] == LETTER, 'a grounded part is never written further'
    assert 'facts_blanked' in job.warnings
    words = text_of(kept[1][1])
    assert '777' not in words and 'Botir' not in words


def test_a_count_paper_that_fills_its_pages_is_not_topped_up(settings, monkeypatch, blocks):
    who = live(settings)
    ready_with(monkeypatch, toldirma=True)
    Model(monkeypatch, **toldirma_answer(kirish={'body': '\n'.join([INTRO] * 30)}))
    sent = []
    transport(monkeypatch, lambda body, number: sent.append(body) or {'sections': []})
    draft = create_draft(who, {'feature_id': catalogue.get(TOLDIRMA).feature_id, 'prompt': PROMPT,
                               'options': {'category': TOLDIRMA}})
    job, _ = made(who, draft)
    assert job.status == 'succeeded', job.error_code
    assert sent == [] and job.artifacts.get().file.page_count >= 2


def test_a_paper_drawn_by_the_fallback_is_not_topped_up(settings, monkeypatch, no_blocks):
    who = live(settings)
    ready_with(monkeypatch, toldirma=True)
    Model(monkeypatch, **toldirma_answer())
    sent = []
    transport(monkeypatch, lambda body, number: sent.append(body) or {'sections': []})
    draft = create_draft(who, {'feature_id': catalogue.get(TOLDIRMA).feature_id, 'prompt': PROMPT,
                               'options': {'category': TOLDIRMA}})
    job, _ = made(who, draft)
    assert job.status == 'succeeded', job.error_code
    assert sent == [], 'the fallback\'s pages say nothing of what the template would draw'


def test_an_uzbek_paper_with_cyrillic_sources_and_file_names_is_delivered(settings, monkeypatch, blocks, kept):
    who = live(settings)
    ready_with(monkeypatch, toldirma=True)
    upload = text_upload(who, FILE_NAME, 'Каримов А. Иқтисодиёт асослари. Тошкент, 2019.\n'
                         + 'Амалиёт талабанинг билимини мустаҳкамлайди ва касбга тайёрлайди. ' * 20)
    excerpt = 'Амалиёт талабанинг билимини мустаҳкамлайди'
    Model(monkeypatch, **toldirma_answer(
        kirish={'body': '\n'.join([INTRO] * 30)},
        manbalar={'items': [{'label': '1', 'text': SOURCE, 'value': ''},
                            {'label': '2', 'text': FILE_NAME, 'value': ''}]},
        citations=[{'asset_id': str(upload.id), 'page': 1, 'quote': excerpt}]))
    transport(monkeypatch, lambda body, number: {'sections': []})
    draft = create_draft(who, {'feature_id': catalogue.get(TOLDIRMA).feature_id, 'prompt': PROMPT,
                               'output_locale': 'uz', 'source_ids': [str(upload.id)],
                               'options': {'category': TOLDIRMA}})
    job, data = made(who, draft)
    assert job.status == 'succeeded', job.error_code
    sources = next(s for s in data['content']['sections'] if s['id'] == 'manbalar')['items']
    assert len(sources) == 1, 'a file name is never a source'
    assert 'Karimov' in sources[0]['text'] and not CYRILLIC.search(sources[0]['text'])
    words = text_of(kept[-1][1])
    assert 'Karimov' in words and not CYRILLIC.search(words) and str(upload.id)[:8] not in words


# ---------------------------------------------------------------- the top-up's own rules


def paper_content():
    return {'title': 'Xat', 'questions': [], 'citations': [], 'sections': [
        {'id': 'facts', 'heading': '', 'body': '', 'items': [{'label': 'signer_name', 'text': 'Dilnoza Rahimova'}]},
        {'id': 'kirish', 'heading': 'Kirish', 'body': INTRO},
        {'id': 'maktub', 'heading': '', 'body': LETTER}]}


def test_a_papers_shortfall_is_read_in_pages_alone():
    content = paper_content()
    # Its few written characters would ask for pages of text; its pages ask for one page's worth.
    assert filling.shortfall(content, 3, 2, pages_only=True) == int(filling.CHARS_PER_PAGE * 0.8)
    assert filling.shortfall(content, 3, 2) > filling.shortfall(content, 3, 2, pages_only=True)
    assert filling.shortfall(content, 3, 3, pages_only=True) == 0


def test_the_top_up_body_carries_the_category_rules_only_for_a_paper():
    data = {'output_locale': 'uz', 'prompt': PROMPT}
    config = {'model': 'test-model'}
    plain = filling.request_body(config, data, paper_content(), 200)
    assert plain['instructions'].startswith(filling.INSTRUCTIONS)
    ruled = filling.request_body(config, data, paper_content(), 200, rules='Category pdf.xat.toldirma.')
    assert ruled['instructions'].startswith(filling.CATEGORY_INSTRUCTIONS + '\nCategory pdf.xat.toldirma.\n')
    assert 'facts' not in filling.CATEGORY_INSTRUCTIONS and 'quotation' in filling.CATEGORY_INSTRUCTIONS
    assert {key: value for key, value in ruled.items() if key != 'instructions'} == \
        {key: value for key, value in plain.items() if key != 'instructions'}


def test_top_up_with_only_changes_only_those_sections(settings, monkeypatch):
    from types import SimpleNamespace
    sent = []

    def handler(body, number):
        sent.append(json.loads(body['input']))
        return {'sections': [{'id': 'kirish', 'addition': 'Amaliyot oxirida hisobot yoziladi.'},
                             {'id': 'maktub', 'addition': 'Yana bir gap.'},
                             {'id': 'facts', 'addition': 'Aziz Karimov'}]}
    transport(monkeypatch, handler)
    monkeypatch.setattr('apps.studio.provider_usage.start_attempt', lambda *args, **kwargs: None)
    monkeypatch.setattr('apps.studio.provider_usage.received', lambda *args, **kwargs: None)
    monkeypatch.setattr('apps.studio.provider_usage.finish', lambda *args, **kwargs: None)
    job = SimpleNamespace(id='top-up-test', feature_id='ai.pdf_topic')
    data = {'output_locale': 'uz', 'prompt': PROMPT, 'output_format': 'pdf'}
    content = paper_content()
    longer = filling.top_up({'model': 'test-model', 'api_key': 'offline'}, data, content, 3, 2, job=job,
                            only={'kirish'}, rules='Category pdf.xat.toldirma.')
    assert [s['id'] for s in sent[0]['sections']] == ['kirish']
    assert [s['gist'] for s in sent[0]['other_sections']] and len(sent[0]['other_sections']) == 1, \
        'the letter goes along in brief; the facts, which hold no body, do not'
    after = {s['id']: s for s in longer['sections']}
    assert after['kirish']['body'].endswith('Amaliyot oxirida hisobot yoziladi.')
    assert after['maktub'] == content['sections'][2] and after['facts'] == content['sections'][0]
    # Nothing to extend: no call at all.
    sent.clear()
    assert filling.top_up({'model': 'test-model', 'api_key': 'offline'}, data, content, 3, 2, job=job,
                          only=set(), rules='x') is content
    assert sent == []


# ---------------------------------------------------------------- stage-2 re-audit: every span's ids


SPANNED = ('Kurs ishi: Mehnat bozorida yoshlar bandligi. Talaba: Yusufbekova Gulshoda, Toshkent davlat iqtisodiyot '
           'universiteti, 3-kurs.')


def spanned_section(section_id):
    made = {'id': section_id, 'heading': f'H {section_id}', 'body': f'Matn {section_id} haqida umumiy fikr.',
            'layout': 'text', 'items': []}
    if section_id == 'facts':
        made.update(body='', layout='list', items=[
            {'label': 'student_name', 'text': 'Mirzaxo‘jayev Zafar Baxtiyorovich', 'value': ''}])
    if section_id in ('references', 'proposals'):
        made.update(body='', layout='list', items=[
            {'label': '', 'text': 'Xudoyberdiyev B. Mehnat iqtisodiyoti asoslari. – Toshkent: Fan.', 'value': ''}
            if section_id == 'references' else {'label': '', 'text': 'Yoshlar uchun kurslar ochish.', 'value': ''}])
    return made


def test_a_paper_written_in_several_calls_never_takes_a_reordered_span_by_position(monkeypatch):
    from apps.studio.categories import skeleton
    from tests.test_provider_contract import CONFIG
    from tests.test_provider_optimization import transport
    for name in ('start_attempt', 'received', 'finish'):
        monkeypatch.setattr(f'apps.studio.provider_usage.{name}', lambda *args, **kwargs: None)
    entry = catalogue.get('pdf.kurs_ishi')
    data = {'output_locale': 'uz', 'prompt': SPANNED, 'source_text': '', 'excerpts': [], 'output_format': 'pdf',
            'options': {'question_count': 0, 'length': 25, 'requested_pages': None, 'image_cap': 0,
                        'category': entry.id}}
    data['content'] = {'title': 'Untitled document', 'questions': [], 'citations': [],
                       'sections': skeleton.seed(entry, 25, skeleton.cues(entry, SPANNED, has_files=False))}
    assert len(skeleton.spans(data)) == 2, 'the paper is written in two calls'
    swapped = set()

    def reply(body, number):
        sent = json.loads(body['input'] if isinstance(body['input'], str) else body['input'][0]['content'])
        ids = [section['id'] for section in sent['outline']['sections']]
        sections = [spanned_section(section_id) for section_id in ids]
        for first, second in (('facts', 'relevance'), ('proposals', 'references')):
            if first in ids and second in ids and (first, second) not in swapped:
                swapped.add((first, second))  # the first try of each span comes back reordered, the retry whole
                one, two = ids.index(first), ids.index(second)
                sections[one], sections[two] = sections[two], sections[one]
        full = {'title': 'Kurs ishi', 'answer_supported': True, 'sections': sections, 'citations': [],
                'questions': []}
        return {key: value for key, value in full.items() if key in body['text']['format']['schema']['properties']}
    sent = transport(monkeypatch, reply)
    merged, _ = provider.generate(CONFIG, data, DOCUMENT, 'not-a-job', token_limit=200_000)
    seeded = [section['id'] for section in data['content']['sections']]
    assert [section['id'] for section in merged['sections']] == seeded
    assert len(sent) == 4 and sum(isinstance(body['input'], list) for body in sent) == 2, 'one retry a span'
    facts_section = next(section for section in merged['sections'] if section['id'] == 'facts')
    relevance = next(section for section in merged['sections'] if section['id'] == 'relevance')
    assert facts_section['items'] and not relevance['items']
    made, _ = finish.apply(data, merged)
    flat = json.dumps(made, ensure_ascii=False)
    assert 'student_name —' not in flat and 'Mirzaxo‘jayev' not in flat and 'Xudoyberdiyev' not in flat
