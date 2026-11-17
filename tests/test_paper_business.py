"""The business templates (package R5a): letterhead, key_figures, card_grid and the four papers they draw.

The commercial offer, the report, the business plan and the marketing plan are
each drawn from their samples in three languages and three cases and read back
by the checker; then what the mock-ups promise is read from the page: an
offer's price table ends on code's total, a report's indicators carry their
difference and per cent and its strip of key figures the plan typed beside
them, a plan's money tables add up, the 4P list prints its words and not its
codes, the SWOT cards stand two by two. The small changes this package made to
the core table and list and to the page's keep-with-next are held here too.
People, organisations and figures are invented.
"""
import datetime

import pdfplumber
import pytest
from reportlab.platypus import Paragraph, Table

from apps.studio import paper
from apps.studio.categories import catalogue
from apps.studio.paper import page, registry, sample
from apps.studio.paper.blocks import business, core
from apps.studio.paper.ctx import Anchor, Ctx, Place
from tests import paper_family

TEMPLATES = ('business_taklif', 'business_hisobot', 'business_biznes_reja', 'business_marketing_reja')
ENTRIES = {'pdf.biz.tijorat_taklifi': 'business_taklif', 'pdf.biz.hisobot': 'business_hisobot',
           'pdf.biz.biznes_reja': 'business_biznes_reja', 'pdf.biz.marketing_reja': 'business_marketing_reja'}
BUSINESS = ('letterhead', 'key_figures', 'card_grid')
DAY = datetime.date(2026, 9, 15)


# ---------------------------------------------------------------- helpers


def context(template_id, sections=(), *, facts=None, locale='uz', pages=4):
    template = catalogue.template(template_id)
    entry = catalogue.get(template['entries'][0])
    content = {'title': 'Sinov', 'questions': [], 'sections': [
        {'id': 'facts', 'heading': '', 'body': '', 'layout': 'list',
         'items': [{'label': key, 'text': value} for key, value in (facts or {}).items()]}, *sections]}
    left, bottom, width, height = page.geometry(template)
    return Ctx(content=content, entry=entry, template=template, locale=locale, step=0, pages=pages, width=width,
               frame_height=height, day=DAY)


def place(ctx, block, part=None, fields=(), params=None):
    found = ctx.entry.part(part) if part else None
    section = ctx.section(part) if part else None
    return Place(block, section, found, tuple(fields or (found or {}).get('fields') or ()), dict(params or {}))


def texts(flowables):
    """Every Paragraph's plain text among the flowables, a Table's cells included, in order."""
    found = []
    for flowable in flowables:
        if isinstance(flowable, Paragraph):
            found.append(' '.join(flowable.getPlainText().replace('\xa0', ' ').split()))
        elif isinstance(flowable, Table):
            for row in flowable._cellvalues:
                for cell in row:
                    found += texts(cell if isinstance(cell, list) else [cell])
    return found


def table(section_id, rows, layout='table'):
    return {'id': section_id, 'heading': '', 'body': '', 'layout': layout,
            'items': [{'label': label, 'text': text, 'value': value} for label, text, value in rows]}


def drawn(tmp_path, template_id, locale='uz', case='full', *, change=None, name='paper.pdf'):
    """A template's sample drawn (its content changed by `change(content)`); (artifact, text of each page)."""
    given = sample.load(template_id, case)
    entry = catalogue.get(given['entry'])
    content = sample.content_of(given, locale)
    if change:
        change(content)
    artifact = paper.render_paper(content, tmp_path / name, locale, entry=entry, template=template_id,
                                  pages=int(given['pages']), day=DAY)
    with pdfplumber.open(artifact['path']) as document:
        pages = [(item.extract_text() or '').replace('\xa0', ' ') for item in document.pages]
    return artifact, pages


def clean(artifact):
    warnings = artifact['metadata']['warnings']
    return not artifact['metadata'].get('template_fallback') and not any(code.startswith('block_fallback')
                                                                         for code in warnings)


# ---------------------------------------------------------------- the family


@paper_family.each(TEMPLATES)
def test_every_template_reads_well(template_id, locale, case, tmp_path):
    drawn_ = paper_family.assert_reads_well(template_id, locale, case, tmp_path)
    warnings = drawn_.artifact['metadata']['warnings']
    if case == 'long':
        # A ceiling paper is never cut: it runs past its quote and says so.
        assert 'longer_than_quoted' in warnings and 'shortened_to_fit' not in warnings
    else:
        assert drawn_.artifact['page_count'] <= drawn_.pages + 1 and 'longer_than_quoted' not in warnings


def test_every_template_has_its_samples():
    paper_family.assert_has_samples(TEMPLATES)


def test_the_business_blocks_are_registered_with_their_plain_fallbacks():
    for name in BUSINESS:
        assert name in registry.BLOCKS and registry.BLOCKS[name].fallback is not None


@pytest.mark.parametrize('entry_id', sorted(ENTRIES))
def test_each_business_paper_is_drawn_by_its_own_template_and_stays_a_draft(entry_id):
    for locale in ('uz', 'ru', 'en'):
        data = {'options': {'category': entry_id}, 'output_locale': locale, 'prompt': 'x'}
        assert paper.ready(data) and paper.template_for(data) == ENTRIES[entry_id]
    found = catalogue.check(entry_id)
    assert not [problem for problem in found if not problem.warning]
    assert not [problem for problem in found if problem.text.startswith('blocks not yet registered')]
    # N2 makes them ready after the native reading; R5a only draws them.
    assert catalogue.get(entry_id).status == 'draft'


def test_the_offer_fits_its_page_and_a_long_one_says_it_came_out_longer(tmp_path):
    artifact, pages = drawn(tmp_path, 'business_taklif')
    assert artifact['page_count'] == 1 and clean(artifact)
    assert 'TIJORAT TAKLIFI' in pages[0] and 'Hurmat bilan,' in pages[0]


# ---------------------------------------------------------------- the papers


def test_the_offer_ends_its_price_table_on_codes_total_in_bold(tmp_path):
    artifact, pages = drawn(tmp_path, 'business_taklif')
    text = '\n'.join(pages)
    assert '26 000 000' in text and 'Jami 39 500 000' in text
    with pdfplumber.open(artifact['path']) as document:
        words = document.pages[0].extract_words(extra_attrs=['fontname'])
    total = next(word for word in words if word['text'] == 'Jami')
    assert total['fontname'].endswith('Bold')


def test_an_english_offer_writes_cents_and_thousands_as_english_does(tmp_path):
    _, pages = drawn(tmp_path, 'business_taklif', 'en')
    assert '2,100.00' in pages[0] and 'Total 3,194.80' in pages[0]


def test_an_offer_without_prices_draws_a_grid_to_fill_by_hand(tmp_path):
    def change(content):
        content['sections'] = [section for section in content['sections'] if section['id'] != 'prices']
    artifact, pages = drawn(tmp_path, 'business_taklif', change=change)
    assert clean(artifact) and 'Narxi' in pages[0] and 'Summasi' in pages[0] and 'Jami' not in pages[0]


def test_the_report_prints_differences_per_cents_and_a_strip_of_figures_with_the_plan_typed(tmp_path):
    artifact, pages = drawn(tmp_path, 'business_hisobot')
    first = pages[0]
    assert '+22' in first and '104,6%' in first and '−3' in first and '—' in first
    assert 'reja 480' in first and 'Farqi va foizlar' in first
    assert clean(artifact)


def test_the_plan_adds_up_its_money_and_names_its_shares(tmp_path):
    artifact, pages = drawn(tmp_path, 'business_biznes_reja')
    text = '\n'.join(pages)
    # The kind is set in tracked capitals, which read back letter by letter.
    assert 'BIZNES-REJA' in pages[0].replace(' ', '') and 'Bank krediti olish uchun' in pages[0], 'the purpose'
    assert 'Jami 420 000 000' in text and '29%' in text and '71%' in text and '21 800 000' in text
    assert 'Umumiy investitsiya' in text and '420 000 000' in pages[1], 'the strip shows the complete total'
    assert clean(artifact)


def test_the_marketing_plan_prints_its_4p_words_its_swot_cards_and_budget_shares(tmp_path):
    artifact, pages = drawn(tmp_path, 'business_marketing_reja')
    text = '\n'.join(pages)
    assert 'Mahsulot. Onlayn' in text and 'Rag‘batlantirish. Instagram' in text
    assert 'product' not in text and 'promotion' not in text, 'no code prints'
    assert 'Kuchli tomonlar' in text and 'Xavflar' in text and 'tashqi omil' in text
    assert '39%' in text and 'Jami 36 000 000 100%' in text
    assert 'TASDIQLAYMAN' in pages[0]
    assert clean(artifact)


def test_a_heading_never_stands_alone_at_the_foot_of_a_page(tmp_path):
    # The report's fifth chapter falls at the foot of page 1: its heading goes over with its first item.
    _, pages = drawn(tmp_path, 'business_hisobot')
    for number, text in enumerate(pages):
        lines = [line for line in text.split('\n') if line.strip()]
        assert not lines or not lines[-1].startswith(('5. ', '4. ', '3. ')), f'page {number + 1} ends on a heading'
    assert '5. Kelgusi davr rejalari' in pages[1] and '2 ta yangi menejerni' in pages[1]


def test_the_keep_with_next_group_reads_its_space_before_past_the_marks():
    heading = Paragraph('Sarlavha', core._style(context('business_hisobot'), 'h1', spaceBefore=17))
    group = page.Together([Anchor(0), heading, Paragraph('Matn', heading.style)])
    assert group.getSpaceBefore() == 17
    assert page.Together([Anchor(0)]).getSpaceBefore() == 0


# ---------------------------------------------------------------- letterhead


def test_a_letterhead_sets_the_name_left_and_the_contacts_right_over_a_rule():
    ctx = context('business_taklif', facts={'seller_name': 'Misol Mebel MChJ', 'seller_phone': '+998 90 111 22 33',
                                            'seller_email': 'savdo@misol.example'})
    made = business.letterhead(ctx, place(ctx, 'letterhead', 'letterhead', params={'labels': {'seller_phone': 'tel'}}))
    assert texts(made) == ['Misol Mebel MChJ', 'Tel.: +998 90 111 22 33', 'savdo@misol.example']
    assert any(isinstance(flowable, core.Hair) for flowable in made)


def test_a_letterhead_without_a_name_draws_a_captioned_rule_and_with_nothing_nothing():
    ctx = context('business_taklif', facts={'seller_phone': '+998 90 111 22 33'})
    params = {'labels': {'seller_phone': 'tel'}, 'captions': {'seller_name': 'cap_company'}}
    made = business.letterhead(ctx, place(ctx, 'letterhead', 'letterhead', params=params))
    assert '(kompaniya nomi)' in texts(made) and 'Tel.: +998 90 111 22 33' in texts(made)
    empty = context('business_taklif')
    # seller_name draws a blank when missing, so even an empty head keeps its rule to write on.
    assert texts(business.letterhead(empty, place(empty, 'letterhead', 'letterhead', ['seller_phone']))) == []
    assert business.letterhead(empty, place(empty, 'letterhead', 'letterhead', ['seller_phone'],
                                            {'name': 'seller_phone'})) == []


# ---------------------------------------------------------------- key_figures


INDICATORS = [('Sotuv', 'mln so‘m | 480 | 502 | +22 | 104,6%', ''), ('Mijozlar', 'ta | 40 | 48 | +8 | 120,0%', ''),
              ('Qaytarish', 'ta | 12 | 9 | −3 | 75,0%', ''), ('Ulush', '% | 62 | 66 | +4 | —', ''),
              ('Muddat', 'kun | 3 | 3 | 0 | 100,0%', '')]
FROM_INDICATORS = {'from': 'indicators', 'value_column': 3, 'unit_column': 1, 'compare_column': 2,
                   'compare_label': 'kf_plan', 'min_rows': 5, 'boxes': 4}


def test_key_figures_from_a_report_show_four_figures_with_the_plan_typed_beside_them():
    ctx = context('business_hisobot', [table('indicators', INDICATORS)])
    made = business.key_figures(ctx, place(ctx, 'key_figures', 'figures', params=FROM_INDICATORS))
    found = texts(made)
    assert found[:3] == ['Sotuv', '502 mln so‘m', 'reja 480'] and 'Muddat' not in found
    assert len(made[0]._cellvalues[0]) == 7, 'four boxes and three gaps'


def test_key_figures_need_their_rows_and_never_shrink_a_figure_that_does_not_fit():
    few = context('business_hisobot', [table('indicators', INDICATORS[:4])])
    assert business.key_figures(few, place(few, 'key_figures', 'figures', params=FROM_INDICATORS)) == []
    wide = INDICATORS[:4] + [('Juda katta', 'so‘m | 1 | 123 456 789 012 345 678 | | ', '')]
    ctx = context('business_hisobot', [table('indicators', wide)])
    found = texts(business.key_figures(ctx, place(ctx, 'key_figures', 'figures', params=FROM_INDICATORS)))
    assert 'Juda katta' not in found and 'Sotuv' in found


def test_key_figures_from_facts_and_a_complete_total_only():
    investment = table('finance_investment', [('Uskuna', '', '180 000 000'), ('Bino', '', '90 000 000')])
    total = {'label': 'Jami', 'text': '', 'value': '270 000 000', 'total': True}
    params = {'figures': [{'total': 'finance_investment', 'column': 3, 'label': 'kf_investment'},
                          {'field': 'own_funds', 'label': 'kf_own'}], 'min': 1}
    ctx = context('business_biznes_reja', [dict(investment, items=investment['items'] + [total])],
                  facts={'own_funds': '120 mln so‘m'})
    found = texts(business.key_figures(ctx, place(ctx, 'key_figures', 'summary_figures', params=params)))
    assert found == ['Umumiy investitsiya', '270 000 000', 'O‘z mablag‘i', '120 mln so‘m']
    named = dict(total, total='named', label='Jami (ko‘rsatilgan moddalar)')
    ctx = context('business_biznes_reja', [dict(investment, items=investment['items'] + [named])],
                  facts={'own_funds': '120 mln so‘m'})
    found = texts(business.key_figures(ctx, place(ctx, 'key_figures', 'summary_figures', params=params)))
    assert found == ['O‘z mablag‘i', '120 mln so‘m'], 'a total of only the items listed is no key figure'
    assert business.key_figures(ctx, place(ctx, 'key_figures', 'summary_figures', params=dict(params, min=2))) == []


def test_a_goal_figure_carries_its_target_word_and_where_it_stands_now():
    goals = table('goals', [('Oylik buyurtmalar', '120 | 300 | avgust', 'hisob')])
    ctx = context('business_marketing_reja', [goals], facts={'budget_total': '36 mln so‘m'})
    params = {'figures': [{'field': 'budget_total', 'label': 'kf_budget'}], 'from': 'goals', 'value_column': 2,
              'compare_column': 1, 'compare_label': 'kf_now', 'label_suffix': 'kf_goal', 'min': 1}
    found = texts(business.key_figures(ctx, place(ctx, 'key_figures', 'summary_figures', params=params)))
    assert found == ['Marketing byudjeti', '36 mln so‘m', 'Oylik buyurtmalar, maqsad', '300', 'hozir 120']


# ---------------------------------------------------------------- card_grid


SWOT_PARAMS = {'labels': {'strengths': 'sw_s', 'weaknesses': 'sw_w', 'opportunities': 'sw_o', 'threats': 'sw_t'},
               'tags': {'strengths': 'tag_inner', 'opportunities': 'tag_outer'}}


def test_card_grid_stands_four_titled_cards_two_by_two_with_their_points():
    swot = table('swot', [('strengths', 'Tez almashtirish', ''), ('Zaif tomonlar', 'Narx yuqori', ''),
                          ('opportunities', 'Telegram kanali', ''), ('nimadir', 'Begona nuqta', '')], 'list')
    ctx = context('business_marketing_reja', [swot])
    made = business.card_grid(ctx, place(ctx, 'card_grid', 'swot', params=SWOT_PARAMS))
    found = texts(made)
    assert found[:3] == ['Kuchli tomonlar', 'ichki omil', 'Tez almashtirish']
    assert 'Narx yuqori' in found, 'a card named by its own word is found'
    assert 'Begona nuqta' not in found and 'card_grid_unknown' in ctx.warnings
    grid = made[0]
    assert len(grid._cellvalues) == 2 and len(grid._cellvalues[0]) == 3, 'two rows of two cards and a gap'
    threats = grid._cellvalues[1][2]
    assert any(isinstance(flowable, core.Hair) for flowable in threats._cellvalues[1][0]), 'an empty card is ruled'


def test_card_grid_without_points_draws_nothing_and_its_fallback_lists_them():
    empty = context('business_marketing_reja', [table('swot', [], 'list')])
    assert business.card_grid(empty, place(empty, 'card_grid', 'swot', params=SWOT_PARAMS)) == []
    ctx = context('business_marketing_reja', [table('swot', [('strengths', 'Tez', '')], 'list')])
    assert texts(business._card_grid_plain(ctx, place(ctx, 'card_grid', 'swot', params=SWOT_PARAMS))) == [
        'Kuchli tomonlar', 'Tez']


def test_the_business_fallbacks_draw_what_their_blocks_hold():
    ctx = context('business_taklif', facts={'seller_name': 'Misol Mebel MChJ', 'seller_phone': '+998 90 111 22 33'})
    lines = texts(business._letterhead_plain(ctx, place(ctx, 'letterhead', 'letterhead', params={
        'labels': {'seller_phone': 'tel'}})))
    assert lines == ['Misol Mebel MChJ', 'Tel.: +998 90 111 22 33']
    report = context('business_hisobot', [table('indicators', INDICATORS)])
    plain = business._key_figures_plain(report, place(report, 'key_figures', 'figures', params=FROM_INDICATORS))
    assert texts(plain)[0] == 'Sotuv — 502 mln so‘m — reja 480'


def test_the_block_samples_draw_without_a_fallback(tmp_path):
    for index, item in enumerate(sample.block_samples(business)):
        for locale in ('uz', 'ru', 'en'):
            path, warnings = sample.draw_block(item, locale, tmp_path, index)
            assert path.exists() and not [code for code in warnings if code.startswith('block_fallback')], item['name']


# ---------------------------------------------------------------- core changes this family needs


def test_a_list_prints_a_code_label_as_its_word_and_drops_a_code_it_does_not_know():
    mix = table('mix', [('price', '150 000 so‘mdan.', ''), ('place', 'Onlayn.', ''), ('channel', 'Telegram.', '')],
                'list')
    ctx = context('business_marketing_reja', [mix])
    params = {'marker': 'bullet', 'labels': {'price': 'p_price', 'place': 'p_place'}}
    made = core.list_block(ctx, place(ctx, 'list', 'mix', params=params))
    assert texts(made) == ['Narx. 150 000 so‘mdan.', 'Taqsimlash. Onlayn.', 'Telegram.']
    assert 'CVSans-Bold' in made[0].text, 'the word is run in bold'


def test_a_table_column_spec_without_a_label_keeps_the_catalogue_header():
    prices = table('prices', [('Parta', 'dona | 2 | 10', '20')])
    ctx = context('business_taklif', [prices])
    made = core.table(ctx, place(ctx, 'table', 'prices', params={'columns': [{'width_mm': 'flex'}, {'width_mm': 16},
                                                                             {'width_mm': 18, 'type': 'number'},
                                                                             {'width_mm': 30, 'type': 'money'},
                                                                             {'width_mm': 32, 'type': 'money'}]}))
    assert texts(made)[:5] == ['Nomi', 'Birlik', 'Miqdori', 'Narxi', 'Summasi']


def test_customer_text_on_the_business_blocks_is_text_never_markup():
    ctx = context('business_taklif', facts={'seller_name': 'A <b>&</b> B'})
    made = business.letterhead(ctx, place(ctx, 'letterhead', 'letterhead'))
    assert texts(made)[0] == 'A <b>&</b> B'
