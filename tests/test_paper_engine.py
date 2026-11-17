"""The paper engine (apps/studio/paper): readiness, the flow, the context, text rules, page rules, fallbacks.

The real blocks are R1's and the families'; these tests register small
stand-in blocks, so they hold the engine to its contract whatever the blocks
look like. People and organisations are invented.
"""
import copy
import datetime
import io

import pdfplumber
import pytest
from reportlab.platypus import Paragraph, Spacer, Table

from apps.studio import paper
from apps.studio.categories import catalogue
from apps.studio.categories.catalogue import build, read
from apps.studio.paper import fit, page, registry
from apps.studio.paper.ctx import Ctx, Lazy, clock_value, holds, places
from apps.studio.paper.registry import Block
from apps.studio.paper.text import NBSP, Rules

DAY = datetime.date(2026, 11, 17)
REQUEST = ('Men 2026-yil 3-noyabrdan 12-noyabrgacha bo‘lgan davrda kasallik sababli darslarga qatnasha olmadim. '
           'Shu kunlardagi dars qoldirishlarimni uzrli deb hisoblashingizni so‘rayman.')


# ---------------------------------------------------------------- stand-in blocks


def _lines(ctx, place):
    section = place.section or {}
    texts = [line for line in str(section.get('body') or '').split('\n') if line.strip()]
    texts += [str(item.get('text') or item.get('label') or '') for item in section.get('items') or []]
    return [Paragraph(ctx.text(text), ctx.styles['body']) for text in texts if text.strip()]


def _facts(ctx, place):
    lines = []
    for field_id in place.fields:
        value = ctx.fact(field_id)
        if value is None and not ctx.blank(field_id):
            continue
        lines.append(Paragraph(ctx.text(value if value is not None else ctx.blank_run(field_id)), ctx.styles['body']))
    return lines


def _word(ctx, place):
    return [Spacer(1, 12), Paragraph(ctx.text(ctx.label(place.params['label'])), ctx.styles['caps']), Spacer(1, 12)]


def _heading(ctx, place):
    # The chapter's heading is the model's, on the chapter's section of the same instance.
    text = str((ctx.section('chapter', place.instance) or {}).get('heading') or f'Bob {place.instance}')
    return [ctx.mark(1, text), Paragraph(ctx.text(f'{ctx.number(1)}. {text}'), ctx.styles['h2'])]


def _contents(ctx, place):
    def make():
        return [Paragraph(ctx.text(f'{text} … {page_number or 0}'), ctx.styles['body'])
                for _, text, page_number in ctx.contents()]
    return [Lazy(make)]


def _broken(ctx, place):
    raise ValueError('a block that fails on its content')


def _too_tall(ctx, place):
    # One cell taller than any page: ReportLab cannot lay it out at all.
    return [Table([[Spacer(1, 2000)]])]


STAND_INS = {'paragraph': _lines, 'list': _lines, 'party_block': _facts, 'signature_row': _facts,
             'doc_title': _word, 'ruled_blank': _word, 'heading': _heading, 'toc': _contents}


@pytest.fixture
def blocks(monkeypatch):
    """The stand-ins registered as the blocks the templates name; returns a setter for more."""
    for name, function in STAND_INS.items():
        monkeypatch.setitem(registry.BLOCKS, name, Block(name, function))

    def register(name, function, fallback=None):
        monkeypatch.setitem(registry.BLOCKS, name, Block(name, function, fallback))
    return register


def ariza():
    return catalogue.get('pdf.xat.ariza')


def facts(**values):
    return {'id': 'facts', 'heading': '', 'body': '', 'layout': 'list',
            'items': [{'label': key, 'text': value} for key, value in values.items()]}


def letter(paragraphs=1, enclosures=3, **more):
    """An ariza's finished content: the customer's facts, a request of `paragraphs` paragraphs, enclosures."""
    given = dict(addressee_org='Namuna davlat universiteti', addressee_position='rektori B. A. Sobirovga',
                 applicant_name='Toshmatova Nilufar Akmal qizidan', signer_name='N. A. Toshmatova')
    given.update(more)
    return {'title': 'Ariza', 'questions': [], 'sections': [
        facts(**given),
        {'id': 'request', 'heading': '', 'layout': 'text', 'items': [],
         'body': '\n'.join([' '.join([REQUEST] * 3)] * paragraphs)},
        {'id': 'enclosures', 'heading': '', 'layout': 'list', 'body': '',
         'items': [{'label': '', 'text': f'Ma’lumotnoma {number} nusxasi.'} for number in range(1, enclosures + 1)]}]}


def template(**changes):
    """The ariza's template with `changes` to its top-level keys, as a dict render_paper draws."""
    raw = copy.deepcopy(catalogue.template('official_ariza'))
    raw.update(changes)
    return raw


def render(tmp_path, content=None, *, entry=None, name='paper.pdf', pages=1, **options):
    options.setdefault('template', 'official_ariza')
    return paper.render_paper(content or letter(), tmp_path / name, 'uz', entry=entry or ariza(), pages=pages,
                              day=DAY, **options)


def text_of(result):
    with pdfplumber.open(result['path']) as document:
        return [page_.extract_text() or '' for page_ in document.pages]


def context(content=None, *, entry=None, raw=None, locale='uz', **more):
    raw = raw or catalogue.template('official_ariza')
    left, bottom, width, height = page.geometry(raw)
    return Ctx(content=content or letter(), entry=entry or ariza(), template=raw, locale=locale, step=0,
               pages=more.pop('pages', 1), width=width, frame_height=height, day=DAY, **more)


# ---------------------------------------------------------------- readiness and picking


def test_ready_needs_a_pdf_category_whose_template_blocks_are_all_registered(blocks, monkeypatch):
    draft = {'options': {'category': 'pdf.xat.ariza', 'length': 1}, 'output_locale': 'uz', 'prompt': 'Ariza'}
    assert paper.ready(draft)
    assert not paper.ready({'options': {}, 'output_locale': 'uz'})
    assert not paper.ready({'options': {'category': 'slides.himoya'}, 'output_locale': 'uz'})
    # An id this catalogue does not hold is no paper here, never an error.
    assert not paper.ready({'options': {'category': 'pdf.gone'}, 'output_locale': 'uz'})
    monkeypatch.delitem(registry.BLOCKS, 'signature_row')
    assert not paper.ready(draft)


def test_without_its_blocks_a_template_is_drawn_by_the_emergency_fallback(tmp_path, monkeypatch):
    for name in list(registry.BLOCKS):
        monkeypatch.delitem(registry.BLOCKS, name)
    result = render(tmp_path)
    assert result['metadata']['template_fallback'] is True
    assert 'template_fallback' in result['metadata']['warnings']
    assert result['metadata']['category'] == 'pdf.xat.ariza'
    assert any('Toshmatova Nilufar' in text for text in text_of(result))


@pytest.fixture
def english_letter(monkeypatch):
    """The ariza with a second template taken for English (`pick: locale:en`), and one taken on a cue."""
    entries, templates, index = copy.deepcopy(read())
    for name, rule in (('ariza_en', 'locale:en'), ('ariza_cue', 'cue:sources')):
        templates[name] = {**copy.deepcopy(templates['official_ariza']), 'id': name, 'pick': rule}
        entries['pdf.xat.ariza']['templates'].append(name)
    built = build(entries, templates, index)
    monkeypatch.setattr(catalogue, '_catalogue', lambda: built)
    return built


def test_pick_takes_the_default_unless_another_templates_pick_holds(english_letter):
    entry = ariza()
    assert paper.pick(entry, 'uz') == 'official_ariza'
    assert paper.pick(entry, 'en') == 'ariza_en'
    assert paper.pick(entry, 'ru', frozenset({'sources'})) == 'ariza_cue'
    draft = {'options': {'category': 'pdf.xat.ariza', 'length': 1}, 'output_locale': 'en', 'prompt': 'Application'}
    assert paper.template_for(draft) == 'ariza_en'
    assert paper.template_for({'options': {}, 'output_locale': 'en'}) is None


# ---------------------------------------------------------------- the flow and its predicates


@pytest.fixture
def chapters(monkeypatch):
    """The ariza given a model-sized group of chapters (heading and text) between the request and the enclosures."""
    entries, templates, index = copy.deepcopy(read())
    raw = entries['pdf.xat.ariza']
    raw['groups'] = {'chapter': {'min': 1, 'max': 4, 'sized': 'model'}}
    raw['parts'][4:4] = [
        {'id': 'chapter_head', 'kind': 'fixed', 'heading': None, 'heading_mode': 'none', 'need': 'required',
         'write': 'Nothing: the heading block draws the chapter number.', 'group': 'chapter'},
        {'id': 'chapter', 'kind': 'prose', 'heading': None, 'heading_mode': 'model', 'need': 'required',
         'write': 'Write the chapter.', 'group': 'chapter', 'share': 0.1, 'elastic': True}]
    built = build(entries, templates, index)
    monkeypatch.setattr(catalogue, '_catalogue', lambda: built)
    return built.entries['pdf.xat.ariza']


def chapter_flow():
    return [{'block': 'toc', 'params': {}},
            {'block': 'paragraph', 'part': 'request'},
            {'block': 'heading', 'part': 'chapter_head'},
            {'block': 'paragraph', 'part': 'chapter'},
            {'block': 'list', 'part': 'enclosures', 'when': 'part:enclosures'}]


def test_a_groups_placements_are_drawn_once_per_instance_the_content_holds_in_order(chapters):
    content = letter()
    content['sections'][2:2] = [{'id': 'chapter', 'heading': 'Birinchi', 'body': 'Bir.', 'layout': 'text'},
                                {'id': 'chapter_3', 'heading': 'Uchinchi', 'body': 'Uch.', 'layout': 'text'}]
    ctx = context(content, entry=chapters, raw=template(flow=chapter_flow()))
    made = [(place.block, place.part and place.part['id'], place.instance) for place in places(ctx)]
    assert made == [('toc', None, 1), ('paragraph', 'request', 1),
                    ('heading', 'chapter_head', 1), ('paragraph', 'chapter', 1),
                    ('heading', 'chapter_head', 3), ('paragraph', 'chapter', 3),
                    ('list', 'enclosures', 1)]
    third = [place for place in places(ctx) if place.instance == 3 and place.block == 'paragraph'][0]
    assert third.section['body'] == 'Uch.' and third.group == 'chapter'


def test_a_group_whose_instances_were_all_dropped_draws_nothing(chapters):
    ctx = context(letter(), entry=chapters, raw=template(flow=chapter_flow()))
    assert [place.block for place in places(ctx)] == ['toc', 'paragraph', 'list']


def test_every_when_predicate(chapters):
    content = letter(period='____', reason='Kasallik')
    content['sections'][0]['items'].append({'label': 'applicant_role', 'text': 'talaba'})
    content['questions'] = [{'stem': 'A?', 'options': ['x', 'y'], 'answer': 'x'},
                            {'stem': 'B?', 'options': ['x', 'y'], 'answer': 'y', 'topic': 'passage'},
                            {'stem': 'C?', 'options': [], 'answer': 'z'}]
    content['sections'].append({'id': 'chapter_2', 'heading': '', 'body': 'Ikki.', 'layout': 'text'})
    ctx = context(content, entry=chapters, cues=frozenset({'sources'}), pages=3)
    assert holds(None, ctx)
    assert holds('fact:reason', ctx) and not holds('nofact:reason', ctx)
    assert holds('fact:applicant_role=talaba', ctx) and not holds('fact:applicant_role=dekan', ctx)
    assert holds('nofact:applicant_role=dekan', ctx) and holds('nofact:email', ctx)
    # The model asked for a blank; a missing field whose policy is blank draws one too; omit never does.
    assert holds('blank:period', ctx) and holds('blank:date_written', ctx) and not holds('blank:email', ctx)
    assert holds('part:enclosures', ctx) and holds('nopart:statements', ctx)
    later = [place for place in places(context(content, entry=chapters, raw=template(flow=chapter_flow())))
             if place.instance == 2][0]
    assert holds('part:chapter', ctx, later) and not holds('part:chapter', ctx)
    assert all(holds(f'questions:{kind}', ctx) for kind in ('choice', 'open', 'both', 'passage'))
    content['questions'] = content['questions'][:1]
    ctx = context(content, entry=chapters, cues=frozenset({'sources'}), pages=3)
    assert holds('questions:choice', ctx) and not holds('questions:open', ctx) and not holds('questions:both', ctx)
    assert holds('cue:sources', ctx) and not holds('nocue:sources', ctx) and not holds('cue:handout', ctx)
    assert holds('pages_from:3', ctx) and not holds('pages_from:4', ctx)
    assert not holds('fact:', ctx) and 'when_unknown' in ctx.warnings


# ---------------------------------------------------------------- the context


def test_facts_blanks_and_clock_values():
    ctx = context(letter(period='____', email=''))
    assert ctx.fact('addressee_org') == 'Namuna davlat universiteti'
    assert ctx.fact('period') is None and ctx.blank('period')
    assert ctx.fact('date_written') is None and ctx.blank('date_written')
    assert ctx.fact('email') is None and not ctx.blank('email')
    assert not ctx.blank('addressee_org')
    assert clock_value('year', DAY, 'uz') == '2026'
    assert clock_value('date', DAY, 'ru') == '17.11.2026'
    assert clock_value('date', DAY, 'en') == '17 November 2026'


def test_a_clock_field_the_customer_left_out_reads_the_tashkent_day(monkeypatch):
    entries, templates, index = copy.deepcopy(read())
    next(field for field in entries['pdf.xat.ariza']['fields'] if field['id'] == 'date_written')['clock'] = 'date'
    built = build(entries, templates, index)
    monkeypatch.setattr(catalogue, '_catalogue', lambda: built)
    ctx = context(entry=built.entries['pdf.xat.ariza'])
    assert ctx.fact('date_written') == '17.11.2026' and not ctx.blank('date_written')
    given = context(letter(date_written='5.11.2026'), entry=built.entries['pdf.xat.ariza'])
    assert given.fact('date_written') == '5.11.2026'


def test_labels_are_in_the_papers_language_with_slots_filled_or_blank():
    raw = template(labels={**catalogue.template('official_ariza')['labels'],
                           'formula': {'uz': '{applicant_name} {period} uchun', 'ru': '{applicant_name} за {period}',
                                       'en': '{applicant_name} for {period}'}})
    ctx = context(raw=raw)
    assert ctx.label('title') == 'ARIZA'
    assert context(raw=raw, locale='ru').label('title') == 'ЗАЯВЛЕНИЕ'
    assert ctx.label('formula') == 'Toshmatova Nilufar Akmal qizidan ________ uchun'
    assert ctx.label('formula', period='noyabr') == 'Toshmatova Nilufar Akmal qizidan noyabr uchun'
    assert ctx.label('nowhere') == '' and 'label_missing:nowhere' in ctx.warnings


def test_headings_counters_columns_and_questions():
    ctx = context()
    assert ctx.heading(ariza().part('title')) == 'ARIZA'
    assert context(locale='ru').heading(ariza().part('enclosures'), {'heading': 'Model'}) == 'Приложение:'
    assert ctx.heading(ariza().part('request'), {'heading': 'Model'}) == '', 'a part without a heading has none'
    assert ctx.heading({'heading_mode': 'model', 'heading': None}, {'heading': ' Model '}) == 'Model'
    assert [ctx.number(1), ctx.number(2), ctx.number(2), ctx.number(1), ctx.number(2)] == ['1', '1.1', '1.2', '2',
                                                                                         '2.1']
    assert ctx.count(1) == 2
    assert ctx.columns({'columns': [{'uz': 'Nomi', 'ru': 'Название', 'en': 'Name'}]}) == ['Nomi']
    assert ctx.questions('choice') == []


# ---------------------------------------------------------------- text rules


def test_text_rules_set_house_apostrophes_and_glue():
    rules = Rules('CVSerif', 'uz')
    assert rules.plain("O'zbekiston ma'lumot va g`alaba") == 'O‘zbekiston ma’lumot va g‘alaba'
    assert rules.plain('rektori B. A. Sobirovga') == f'rektori B.{NBSP}A.{NBSP}Sobirovga'
    assert rules.plain('O‘. Karimov, G‘. A. Aliyev') == f'O‘.{NBSP}Karimov, G‘.{NBSP}A.{NBSP}Aliyev'
    assert rules.plain('Vaqt: 35 daqiqa, № 5, 1 150 000 so‘m') == \
        f'Vaqt: 35{NBSP}daqiqa, №{NBSP}5, 1{NBSP}150{NBSP}000{NBSP}so‘m'
    assert rules.plain('bir — ikki') == f'bir{NBSP}— ikki'
    # Russian keeps its apostrophes as typed; only Uzbek takes the house ones.
    assert Rules('CVSerif', 'ru').plain("д'Артаньян") == "д'Артаньян"


def test_text_rules_escape_markup_draw_blanks_and_drop_what_the_face_lacks():
    rules = Rules('CVSerif', 'uz')
    made = rules.markup('<b>A & B</b> ____ va ___ va ' + '_' * 20 + ' 🙂', font='CVSerif', size=12)
    assert '&lt;b&gt;A &amp; B&lt;/b&gt;' in made
    widths = [len(run) for run in made.split('<u ')[1:]]
    assert len(widths) == 3 and widths[0] < widths[2] and widths[1] < widths[0]
    assert '🙂' not in made and '🙂' in rules.dropped
    narrow = rules.markup('_' * 20, font='CVSerif', size=12, room=40)
    assert narrow.count(NBSP) < made.split('<u ')[3].count(NBSP)


# ---------------------------------------------------------------- page rules


def test_a_fixed_paper_that_fits_is_one_page_at_the_loosest_step(tmp_path, blocks):
    result = render(tmp_path)
    assert result['page_count'] == 1 and not result['shortened']
    meta = result['metadata']
    assert (meta['category'], meta['template'], meta['fit_step'], meta['warnings']) == \
        ('pdf.xat.ariza', 'official_ariza', 0, [])
    assert meta['frames']['first'] == [page.box(*_frame('official_ariza'))]
    text = text_of(result)[0]
    assert 'ARIZA' in text and 'Toshmatova Nilufar' in text and 'bo‘lgan' in text


def _frame(template_id):
    left, bottom, width, height = page.geometry(catalogue.template(template_id))
    return left, bottom, left + width, bottom + height


def test_a_longer_fixed_paper_tightens_then_takes_a_page_with_its_closing_group_whole(tmp_path, blocks):
    tighter = render(tmp_path, letter(paragraphs=4, enclosures=6), name='tighter.pdf')
    assert tighter['page_count'] == 1 and tighter['metadata']['fit_step'] > 0
    longer = render(tmp_path, letter(paragraphs=5, enclosures=6), name='longer.pdf')
    assert longer['page_count'] == 2
    assert longer['metadata']['fit_step'] == len(catalogue.template('official_ariza')['type']['ladder']) - 1
    assert 'longer_than_quoted' in longer['metadata']['warnings']
    first, second = text_of(longer)
    # The enclosures and the signature travel together, with the request's last lines before them.
    assert 'nusxasi' not in first and 'Ma’lumotnoma 6 nusxasi' in second and 'N. A. Toshmatova' in second
    lines = second.split('\n')
    assert lines[0] == '2', 'the number alone over the frame on the later page'
    assert 'Ma’lumotnoma 1' not in lines[1] and 'Ma’lumotnoma 1' not in lines[2]
    assert not first.strip().split('\n')[0] == '1', 'page 1 carries no number'


def test_a_flow_paper_tightens_only_past_the_quote_and_is_never_cut(tmp_path, blocks):
    raw = template(page_rule={'kind': 'flow'})
    result = render(tmp_path, letter(paragraphs=8), template=raw, pages=1)
    assert result['page_count'] == 2 and result['metadata']['fit_step'] == 0 and not result['shortened']
    long = render(tmp_path, letter(paragraphs=40), template=raw, pages=1, name='long.pdf')
    assert long['page_count'] > 2 and 'longer_than_quoted' in long['metadata']['warnings']
    assert not long['shortened']


def test_a_count_paper_cuts_only_its_elastic_prose_when_no_step_holds_it(tmp_path, blocks):
    raw = template(page_rule={'kind': 'count'})
    result = render(tmp_path, letter(paragraphs=5, enclosures=6), template=raw, pages=1)
    assert result['page_count'] == 1 and result['shortened']
    assert 'shortened_to_fit' in result['metadata']['warnings'] and result['metadata']['trim_ratio'] < 1
    text = text_of(result)[0]
    assert '…' in text and 'Ma’lumotnoma 6 nusxasi' in text, 'the enclosures are not elastic prose'
    kept = render(tmp_path, letter(paragraphs=5, enclosures=6), template=template(page_rule={'kind': 'count',
                                                                                             'trim': False}),
                  pages=1, name='kept.pdf')
    assert kept['page_count'] == 2 and not kept['shortened'] and 'longer_than_quoted' in kept['metadata']['warnings']


class Fake:
    def __init__(self, pages, fill=0.5):
        self.pages, self.fill = pages, fill


def test_the_page_rules_choose_steps_as_specified():
    sizes = {0: 3, 1: 2, 2: 2}

    def make(step, ratio=None):
        return Fake(1 if ratio is not None and ratio <= 0.6 else sizes[step], fill=0.05 if step == 0 else 0.6)
    assert fit.fit(make, {'kind': 'fixed', 'pages': 2}, 3, 1).step == 1
    assert fit.fit(make, {'kind': 'fixed'}, 3, 1).codes == ['longer_than_quoted']
    assert fit.fit(make, {'kind': 'flow'}, 3, 2).step == 0
    assert fit.fit(make, {'kind': 'flow'}, 3, 1).step == 1
    counted = fit.fit(make, {'kind': 'count'}, 3, 1)
    assert counted.step == 2 and counted.ratio <= 0.6 and counted.codes == ['shortened_to_fit']
    # A last page under stub_min is pulled back by a tighter step that gives fewer pages.
    assert fit.fit(make, {'kind': 'flow', 'stub_min': 0.1}, 3, 3).step == 1


# ---------------------------------------------------------------- furniture, contents and keep groups


def test_a_running_header_and_n_of_n_numbers(tmp_path, blocks):
    raw = template(page_rule={'kind': 'flow'}, furniture={'first': 'number', 'later': 'header_number',
                                                          'format': 'n_of_N', 'header': ['addressee_org']})
    result = render(tmp_path, letter(paragraphs=12), template=raw, pages=3)
    pages = text_of(result)
    total = len(pages)
    assert total >= 2
    assert pages[0].rstrip().endswith(f'1 / {total}')
    assert pages[1].startswith('Namuna davlat universiteti') and pages[1].rstrip().endswith(f'2 / {total}')


def test_the_contents_print_the_pages_the_headings_land_on(tmp_path, blocks, chapters):
    content = letter(paragraphs=1)
    filler = ' '.join([REQUEST] * 16)
    content['sections'][2:2] = [{'id': 'chapter' if number == 1 else f'chapter_{number}',
                                 'heading': f'Bob nomi {number}', 'body': '\n'.join([filler] * 3), 'layout': 'text'}
                                for number in (1, 2, 3)]
    raw = template(flow=chapter_flow(), page_rule={'kind': 'flow'})
    result = paper.render_paper(content, tmp_path / 'contents.pdf', 'uz', entry=chapters, template=raw, pages=4,
                                day=DAY)
    pages = text_of(result)
    landed = {number: next(index + 1 for index, text in enumerate(pages) if f'{number}. Bob nomi {number}' in text)
              for number in (1, 2, 3)}
    for number, where in landed.items():
        assert f'Bob nomi {number} … {where}' in pages[0]
    assert len(set(landed.values())) > 1


def test_a_keep_group_never_separates(tmp_path, blocks):
    raw = template(page_rule={'kind': 'flow'})
    for paragraphs in range(1, 12):
        result = render(tmp_path, letter(paragraphs=paragraphs, enclosures=6), template=raw, pages=1,
                        name=f'keep{paragraphs}.pdf')
        last = text_of(result)[-1]
        assert 'Ma’lumotnoma 1 nusxasi' in last and 'N. A. Toshmatova' in last, paragraphs


def _closing_flow(tail=None):
    closing = {'tail_lines': tail} if tail is not None else {}
    return [{'block': 'paragraph', 'part': 'request'},
            {'block': 'heading', 'part': 'chapter_head'}, {'block': 'paragraph', 'part': 'chapter'},
            {'block': 'list', 'part': 'enclosures', 'keep': 'closing', 'params': closing},
            {'block': 'signature_row', 'part': 'signature', 'fields': ['signer_name'], 'keep': 'closing'}]


@pytest.mark.parametrize('rule', [{'kind': 'fixed', 'pages': 1}, {'kind': 'flow'}], ids=['fixed', 'flow'])
def test_a_heading_and_a_one_paragraph_part_before_the_closing_group_stay_on_the_page_they_fit(tmp_path, blocks,
                                                                                            chapters, rule):
    for paragraphs in (1, 3):
        content = letter(paragraphs=paragraphs)
        content['sections'][2:2] = [{'id': 'chapter', 'heading': 'Xulosa', 'body': ' '.join([REQUEST] * 2),
                                     'layout': 'text'}]
        result = paper.render_paper(content, tmp_path / f'closing{paragraphs}.pdf', 'uz', entry=chapters,
                                    template=template(flow=_closing_flow(), page_rule=rule), pages=1, day=DAY)
        pages = text_of(result)
        assert result['page_count'] == 1 and len(pages) == 1, paragraphs
        assert '1. Xulosa' in pages[0] and 'N. A. Toshmatova' in pages[0]
        assert 'longer_than_quoted' not in result['metadata']['warnings']


def test_a_heading_before_the_contents_stays_where_it_fits(tmp_path, blocks, chapters):
    blocks('doc_title', lambda ctx, place: [Paragraph(ctx.text('MUNDARIJA'), ctx.styles['h2'])])
    content = letter(paragraphs=1)
    content['sections'][2:2] = [{'id': 'chapter' if number == 1 else f'chapter_{number}', 'heading': f'Bob {number}',
                                 'body': REQUEST, 'layout': 'text'} for number in (1, 2, 3, 4)]
    flow = [{'block': 'paragraph', 'part': 'request'}, {'block': 'doc_title', 'part': 'title'},
            {'block': 'toc', 'params': {}}, {'block': 'heading', 'part': 'chapter_head'},
            {'block': 'paragraph', 'part': 'chapter'}]
    result = paper.render_paper(content, tmp_path / 'contents.pdf', 'uz', entry=chapters,
                                template=template(flow=flow, page_rule={'kind': 'flow'}), pages=2, day=DAY)
    first = text_of(result)[0]
    assert result['page_count'] == 1
    assert 'MUNDARIJA' in first and 'Bob 1 … 1' in first and 'Bob 4 … 1' in first


def test_a_table_contents_taller_than_the_rest_of_the_page_runs_on(tmp_path, blocks):
    def contents(ctx, place):
        def make():
            return [Table([[Paragraph(ctx.text(f'Bob {number}'), ctx.styles['body']), str(number)]
                           for number in range(1, 61)], colWidths=[ctx.width - 40, 40])]
        return [Lazy(make)]
    blocks('toc', contents)
    flow = [{'block': 'paragraph', 'part': 'request'}, {'block': 'toc', 'params': {}},
            {'block': 'list', 'part': 'enclosures'}]
    result = render(tmp_path, letter(paragraphs=3), template=template(flow=flow, page_rule={'kind': 'flow'}), pages=2)
    pages = text_of(result)
    assert 'block_fallback:toc' not in result['metadata']['warnings']
    assert 'Bob 1\n' in pages[0] + '\n' and 'Bob 60' in pages[-1] and 'Ma’lumotnoma 3 nusxasi' in pages[-1]


def test_a_request_paragraph_longer_than_two_pages_ends_with_its_closing_group(tmp_path, blocks):
    content = letter()
    content['sections'][1]['body'] = ' '.join([REQUEST] * 45)
    result = render(tmp_path, content)
    pages = text_of(result)
    assert len(pages) >= 3 and result['page_count'] == len(pages)
    warnings = result['metadata']['warnings']
    assert not result['metadata'].get('template_fallback') and not any(code.startswith('block_fallback')
                                                                       for code in warnings)
    last = pages[-1].split('\n')
    assert 'Ma’lumotnoma 1 nusxasi.' in last and 'Ma’lumotnoma 3 nusxasi.' in last and 'N. A. Toshmatova' in last
    # The request's last lines travel with the group, never the enclosures alone.
    assert last[1].startswith(('Men', 'darslarga', 'qatnasha', 'Shu', 'kunlardagi', 'deb', 'hisoblash', 'olmadim',
                               'davrda', 'kasallik', 'sababli', '3-noyabrdan', '12-noyabrgacha', 'bo‘lgan', 'dars',
                               'qoldirish', 'uzrli', 'so‘rayman'))


def test_a_page_break_before_a_placement_that_draws_nothing_adds_no_page(tmp_path, blocks):
    blocks('answer_key', lambda ctx, place: [])
    flow = [*catalogue.template('official_ariza')['flow'], {'block': 'answer_key', 'page_break_before': True}]
    result = render(tmp_path, template=template(flow=flow))
    assert result['page_count'] == 1 and result['metadata']['warnings'] == []
    assert result['metadata']['last_page_fill'] > 0
    # Nor does one first in the paper, after only marks.
    first = render(tmp_path, template=template(flow=[{'block': 'answer_key'},
                                                     {'block': 'paragraph', 'part': 'request',
                                                      'page_break_before': True}]), name='first.pdf')
    assert first['page_count'] == 1


def test_a_spacer_alone_after_a_page_break_adds_no_page(tmp_path, blocks):
    blocks('answer_key', lambda ctx, place: [Spacer(1, 30)])
    flow = [*catalogue.template('official_ariza')['flow'], {'block': 'answer_key', 'page_break_before': True}]
    assert render(tmp_path, template=template(flow=flow))['page_count'] == 1


def test_a_keep_group_taller_than_any_page_starts_where_it_stands(tmp_path, blocks):
    # A passage group: no lines of the paragraph before travel with it, and it is taller than a page.
    flow = [{'block': 'paragraph', 'part': 'request'},
            {'block': 'list', 'part': 'enclosures', 'keep': 'passage'},
            {'block': 'signature_row', 'part': 'signature', 'fields': ['signer_name'], 'keep': 'passage'}]
    result = render(tmp_path, letter(enclosures=70), template=template(flow=flow, page_rule={'kind': 'flow'}))
    pages = text_of(result)
    assert 'Ma’lumotnoma 1 nusxasi' in pages[0], 'page 1 is not left half empty'
    assert result['page_count'] == len(pages) == 2 and 'Ma’lumotnoma 70 nusxasi' in pages[-1]
    # One that would fit a page whole still moves on rather than separate.
    kept = render(tmp_path, letter(paragraphs=6, enclosures=12), template=template(flow=flow, page_rule={'kind': 'flow'}),
                  name='kept.pdf')
    first, second = text_of(kept)
    assert 'nusxasi' not in first and 'Ma’lumotnoma 1 nusxasi' in second


def test_the_head_left_before_a_closing_group_is_measured_not_counted():
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfgen.canvas import Canvas
    style = ParagraphStyle('lead', fontName='Helvetica', fontSize=10, leading=12, spaceBefore=30)
    big = ' '.join(['so‘z'] * 12 + ['<font size="22">KATTA</font>'] + ['so‘z'] * 12)
    lead = Paragraph(' '.join([big] * 6), style)
    closing = fit.Closing((), page.Mark(()), lead, [Paragraph('Imzo', style)], 2, 700)
    canvas = Canvas(io.BytesIO())
    closing.canv = canvas
    parts = closing.split(200, 160)
    assert len(parts) == 3 and isinstance(parts[2], fit.Closing)
    _, tall = parts[1].wrapOn(canvas, 200, 160)
    assert tall + parts[1].getSpaceBefore() <= 160


def test_a_keep_group_takes_the_paragraph_before_its_gap_and_two_lines_only_when_it_closes(blocks):
    def gapped(ctx, place):
        return [*_lines(ctx, place), Spacer(1, 12)]
    blocks('paragraph', gapped)
    ctx = context(letter())
    closing = next(flowable for flowable in fit.story(ctx, places(ctx)) if isinstance(flowable, fit.Closing))
    assert isinstance(closing.lead, Paragraph) and closing.tail == 2
    assert isinstance(closing.group[0], Spacer), 'the gap stays between the paragraph and the group'
    flow = [{**placement, 'keep': 'passage'} if placement.get('keep') else placement
            for placement in catalogue.template('official_ariza')['flow']]
    ctx = context(letter(), raw=template(flow=flow))
    made = fit.story(ctx, places(ctx))
    assert not any(isinstance(flowable, fit.Closing) and flowable.lead is not None for flowable in made)


def test_customer_text_never_reaches_the_log(tmp_path, blocks, monkeypatch, caplog):
    def raising(ctx, place):
        raise ValueError(f"paragraph text '{ctx.fact('applicant_name')}' caused exception")

    def markup(ctx, place):
        return [Paragraph('<para>Toshmatova Nilufar <b>', ctx.styles['body'])]
    blocks('list', raising)
    blocks('paragraph', markup)
    with caplog.at_level('DEBUG'):
        result = render(tmp_path)
    assert {'block_fallback:list', 'block_fallback:paragraph'} <= set(result['metadata']['warnings'])

    def failing(*args, **kwargs):
        raise RuntimeError('Splitting error on page 1 in <Paragraph> Toshmatova Nilufar Akmal qizidan')
    monkeypatch.setattr(page, 'build', failing)
    with caplog.at_level('DEBUG'):
        assert render(tmp_path, name='failed.pdf')['metadata']['template_fallback'] is True
    logged = '\n'.join(record.getMessage() + str(record.exc_info or '') for record in caplog.records)
    assert 'Paper block list raised ValueError' in logged
    assert 'Toshmatova' not in logged and 'Nilufar' not in logged


def test_a_final_pass_that_adds_a_page_is_longer_than_quoted(tmp_path, blocks, monkeypatch):
    real = paper._Paper.build

    def grown(self, step, ratio=None, **options):
        made = real(self, step, ratio, **options)
        if options.get('known') is not None:
            made.pages += 1  # the contents' numbers grew a line and pushed the signature over
        return made
    monkeypatch.setattr(paper._Paper, 'build', grown)
    raw = template(furniture={'first': 'number', 'later': 'number_bottom', 'format': 'n_of_N'})
    warnings = render(tmp_path, template=raw)['metadata']['warnings']
    assert 'longer_than_quoted' in warnings and paper.UNSETTLED not in warnings


def test_the_final_passes_start_from_the_chosen_build_and_say_when_they_did_not_settle():
    class Built:
        def __init__(self, pages, state):
            self.pages, self.anchors, self.state = pages, {}, state
            self.ctx = type('Ctx', (), {'wants_contents': True})()

    class Paper:
        def __init__(self, sizes):
            self.sizes, self.states = iter(sizes), []

        def build(self, step, ratio=None, *, known=None, total=None, state=None):
            self.states.append(state)
            return Built(next(self.sizes), state)
    chosen = (frozenset({(3, 0)}), frozenset({(5, 1)}))
    choice = fit.Choice(Built(2, chosen), 1, None, [])
    steady = Paper([2])
    built, settled = paper._final(steady, choice, {'format': 'n_of_N'})
    assert settled and built.pages == 2 and steady.states == [chosen]
    swinging = Paper([3, 2])
    built, settled = paper._final(swinging, choice, {'format': 'n_of_N'})
    assert not settled and swinging.states == [chosen, chosen]


def test_a_build_with_a_state_starts_from_it(blocks):
    made = paper._Paper(letter(), 'uz', ariza(), catalogue.template('official_ariza'), 1, frozenset(), DAY, None)
    made.failed, made.dropped = {(9, 0)}, {(8, 0)}
    built = made.build(0, state=(frozenset(), frozenset()))
    assert built.state == (frozenset(), frozenset()) and not made.failed and not made.dropped


def test_a_one_page_paper_carries_no_page_number(tmp_path, blocks):
    for style in ('n', 'n_of_N'):
        raw = template(furniture={'first': 'number', 'later': 'number_bottom', 'format': style})
        one = text_of(render(tmp_path, template=raw, name=f'one_{style}.pdf'))
        assert len(one) == 1 and one[0].rstrip().split('\n')[-1] != '1' and '1 / 1' not in one[0]
        more = text_of(render(tmp_path, letter(paragraphs=8), template=template(
            furniture=raw['furniture'], page_rule={'kind': 'flow'}), name=f'more_{style}.pdf'))
        assert more[0].rstrip().split('\n')[-1] == ('1' if style == 'n' else f'1 / {len(more)}')


def test_a_running_header_word_longer_than_the_line_is_cut():
    cut = page._cut('Namunaviy' * 20, 'CVSerif', 9, 100)
    assert cut.endswith('…') and page.stringWidth(cut, 'CVSerif', 9) <= 100


def test_a_block_module_that_fails_to_import_leaves_only_its_blocks_missing(monkeypatch, caplog):
    import importlib
    import pkgutil

    real = importlib.import_module

    def fake_import(name, *args):
        if name.endswith('.broken'):
            registry.block('half_made')(_word)
            raise SyntaxError('a broken family module')
        return real(name, *args)
    monkeypatch.setattr(pkgutil, 'iter_modules', lambda path: [pkgutil.ModuleInfo(None, 'broken', False)])
    monkeypatch.setattr(importlib, 'import_module', fake_import)
    registry.discover()
    assert 'half_made' not in registry.BLOCKS
    assert any('broken' in record.getMessage() for record in caplog.records)


def test_the_mark_after_a_heading_keeps_it_with_what_follows(blocks, chapters):
    content = letter()
    content['sections'][2:2] = [{'id': 'chapter', 'heading': 'Birinchi', 'body': 'Bir.', 'layout': 'text'}]
    ctx = context(content, entry=chapters, raw=template(flow=chapter_flow()))
    made = fit.story(ctx, places(ctx))
    heading = next(position for position, flowable in enumerate(made)
                   if isinstance(flowable, Paragraph) and 'Birinchi' in flowable.text)
    assert isinstance(made[heading + 1], page.Mark) and made[heading + 1].getKeepWithNext()
    marks = [flowable for flowable in made if isinstance(flowable, page.Mark)]
    assert not marks[0].getKeepWithNext(), 'a mark after ordinary text keeps nothing together'


# ---------------------------------------------------------------- failures


def test_a_block_that_raises_is_drawn_by_its_fallback(tmp_path, blocks):
    blocks('list', _broken)
    result = render(tmp_path)
    assert result['page_count'] == 1 and 'block_fallback:list' in result['metadata']['warnings']
    assert 'Ma’lumotnoma 3 nusxasi' in text_of(result)[0], 'the plain fallback draws the items'
    assert not result['metadata'].get('template_fallback')

    def own(ctx, place):
        return [Paragraph('Ilova bor.', ctx.styles['body'])]
    blocks('list', _broken, own)
    assert 'Ilova bor.' in text_of(render(tmp_path, name='own.pdf'))[0]


def test_a_placement_that_breaks_the_layout_is_drawn_plain(tmp_path, blocks):
    blocks('list', _too_tall)
    result = render(tmp_path)
    assert 'block_fallback:list' in result['metadata']['warnings']
    assert not result['metadata'].get('template_fallback')
    assert 'Ma’lumotnoma 2 nusxasi' in text_of(result)[0]
    # A fallback that breaks it too leaves out a placement without facts, and the paper is still drawn.
    blocks('callout', _too_tall, _too_tall)
    flow = [*catalogue.template('official_ariza')['flow'], {'block': 'callout'}]
    left = render(tmp_path, template=template(flow=flow), name='left.pdf')
    assert 'block_fallback:callout' in left['metadata']['warnings'] and not left['metadata'].get('template_fallback')
    assert 'Toshmatova' in text_of(left)[0]
    # A placement of the closing group (or one with facts) is never left out: the paper takes the emergency fallback.
    blocks('list', _too_tall, _too_tall)
    kept = render(tmp_path, name='kept.pdf')
    assert kept['metadata']['template_fallback'] is True
    assert any('Ma’lumotnoma 2 nusxasi' in text for text in text_of(kept))


def test_a_placement_that_breaks_one_instance_is_drawn_plain_in_that_instance_only(tmp_path, blocks, chapters):
    def chapter(ctx, place):
        if place.instance == 2:
            return _too_tall(ctx, place)
        return [Paragraph(ctx.text('Blok: ' + place.section['body']), ctx.styles['body'])]
    blocks('chapter_text', chapter)
    content = letter()
    content['sections'][2:2] = [{'id': 'chapter' if number == 1 else f'chapter_{number}', 'heading': '',
                                 'body': word, 'layout': 'text'}
                                for number, word in ((1, 'Bir.'), (2, 'Ikki.'), (3, 'Uch.'))]
    flow = [{'block': 'paragraph', 'part': 'request'}, {'block': 'heading', 'part': 'chapter_head'},
            {'block': 'chapter_text', 'part': 'chapter'}]
    result = paper.render_paper(content, tmp_path / 'chapters.pdf', 'uz', entry=chapters,
                                template=template(flow=flow, page_rule={'kind': 'flow'}), pages=1, day=DAY)
    text = '\n'.join(text_of(result))
    assert 'Blok: Bir.' in text and 'Blok: Uch.' in text
    assert 'Ikki.' in text and 'Blok: Ikki.' not in text
    assert 'block_fallback:chapter_text' in result['metadata']['warnings']


def test_a_build_that_fails_whatever_is_drawn_plain_gives_the_emergency_fallback(tmp_path, blocks, monkeypatch):
    def failing(*args, **kwargs):
        raise RuntimeError('a build that cannot be made')
    monkeypatch.setattr(page, 'build', failing)
    result = render(tmp_path)
    assert result['metadata']['template_fallback'] is True and result['metadata']['fit_step'] is None
    assert result['page_count'] >= 1 and any('Toshmatova Nilufar' in text for text in text_of(result))


def test_an_unknown_template_gives_the_emergency_fallback_or_the_callers(tmp_path, blocks):
    result = render(tmp_path, template='official_gone')
    assert result['metadata']['template_fallback'] is True and result['metadata']['template'] == 'official_gone'
    called = []

    def mine(content, path):
        called.append(path.name)
        return {'path': str(path), 'name': path.name, 'page_count': 1, 'metadata': {'warnings': ['facts_blanked']}}
    made = render(tmp_path, template='official_gone', fallback=mine, name='mine.pdf')
    assert called == ['mine.pdf']
    assert made['metadata']['warnings'] == ['facts_blanked', 'template_fallback']


def test_the_emergency_projection_keeps_every_fact_cell_and_question():
    content = letter(period='____')
    content['sections'].append({'id': 'statements', 'heading': '', 'layout': 'table', 'body': '',
                                'items': [{'label': 'Bir', 'text': 'ikki | uch', 'value': 'to‘rt'}]})
    content['questions'] = [{'stem': 'Savol?', 'options': ['a', 'b'], 'answer': 'a'}]
    made = paper.plain(content, ariza(), 'uz')
    assert made['title'] == 'Ariza' and made['questions'] == content['questions']
    first = made['sections'][0]['body'].split('\n')
    assert 'Kimga: tashkilot: Namuna davlat universiteti' in first
    assert 'Sanalar yoki muddat: ____' in first
    statements = next(section for section in made['sections'] if section['id'] == 'statements')
    assert statements['body'] == 'Bir — ikki | uch — to‘rt'


# ---------------------------------------------------------------- the registry and the output


def test_the_registry_discovers_block_modules_and_refuses_a_name_twice(monkeypatch):
    monkeypatch.setitem(registry.BLOCKS, 'line', Block('line', _lines))
    assert registry.missing({'line', 'nowhere'}) == ['nowhere']
    with pytest.raises(ValueError):
        registry.block('line')(_word)
    registry.discover()


def test_the_same_paper_gives_the_same_bytes_and_draws_uzbek_and_cyrillic(tmp_path, blocks):
    one = render(tmp_path, name='one.pdf')
    two = render(tmp_path, name='two.pdf')
    assert (tmp_path / 'one.pdf').read_bytes() == (tmp_path / 'two.pdf').read_bytes()
    russian = paper.render_paper(letter(addressee_org='Образцовый университет'), tmp_path / 'ru.pdf', 'ru',
                                 entry=ariza(), template='official_ariza', pages=1, day=DAY)
    text = text_of(russian)[0]
    assert 'Образцовый университет' in text and 'ЗАЯВЛЕНИЕ' in text
    assert 'glyphs_dropped' not in russian['metadata']['warnings']
    assert 'o‘' in text_of(one)[0] or 'bo‘lgan' in text_of(one)[0]
    with pdfplumber.open(io.BytesIO((tmp_path / 'one.pdf').read_bytes())) as document:
        fonts = {char['fontname'].split('+')[-1] for char in document.pages[0].chars}
    assert fonts and all(name.startswith('NotoSerif') for name in fonts)
    assert two['page_count'] == one['page_count']
