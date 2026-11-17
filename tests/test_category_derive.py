"""derive.apply (package R5a): a business paper's computed cells and totals, made by code from verified numbers.

The model never does arithmetic: the finish empties what it wrote, and derive
multiplies, subtracts, takes per cents and shares and adds totals from the
numbers of the same row or column. A cell whose inputs are missing, unread or
not the customer's stays blank; a partial total is labelled as the items
listed, or left out where the template says so; a total the model wrote is
never the one printed. Figures are invented, and so are the organisations.
"""
import copy

import pytest

from apps.studio.categories import catalogue, derive, facts, finish
from apps.studio.paper import sample
from tests.test_category_business_entries import finished_table

OFFER, REPORT, PLAN, MARKETING = ('pdf.biz.tijorat_taklifi', 'pdf.biz.hisobot', 'pdf.biz.biznes_reja',
                                  'pdf.biz.marketing_reja')


def section(section_id, rows):
    return {'id': section_id, 'heading': '', 'body': '', 'layout': 'table',
            'items': [{'label': label, 'text': text, 'value': value} for label, text, value in rows]}


def made(entry_id, section_id, rows, *, locale='uz', trusted=None, facts_items=()):
    """The rows of one table after derive, as cell lists, and the total flag of each."""
    entry = catalogue.get(entry_id)
    sections = [section(section_id, rows)]
    if facts_items:
        sections.insert(0, {'id': 'facts', 'items': [{'label': key, 'text': value} for key, value in facts_items]})
    content = {'title': '', 'sections': sections, 'questions': []}
    result = derive.apply(entry, content, trusted if trusted is not None else object(), locale=locale)
    table = next(item for item in result['sections'] if item['id'] == section_id)
    count = len(entry.part(section_id)['columns'])
    return [finish.cells(item, count) for item in table['items']], [item.get('total') for item in table['items']]


# ---------------------------------------------------------------- products and totals


def test_an_offer_multiplies_quantity_by_price_and_adds_the_total_last():
    rows, totals = made(OFFER, 'prices', [('Parta', 'dona | 40 | 650 000', ''), ('Stul', 'dona | 40 | 280 000', ''),
                                          ('Stol', 'dona | 2 | 1 150 000', '')], facts_items=[('currency', 'so‘m')])
    assert rows == [['Parta', 'dona', '40', '650 000', '26 000 000'], ['Stul', 'dona', '40', '280 000', '11 200 000'],
                    ['Stol', 'dona', '2', '1 150 000', '2 300 000'], ['Jami', '', '', '', '39 500 000']]
    assert totals == [None, None, None, True]


def test_a_total_the_model_wrote_is_taken_out_and_made_again():
    rows, totals = made(OFFER, 'prices', [('Parta', 'dona | 4 | 100 000', ''), ('Stul', 'dona | 2 | 50 000', ''),
                                          ('Jami', '', '999 999'), ('', '', '1 000 000')])
    assert rows[-1] == ['Jami', '', '', '', '500 000'] and len(rows) == 3
    # A total row made by an earlier pass and sent back by a change, in any language, is made again too.
    again, _ = made(OFFER, 'prices', [('Parta', 'dona | 4 | 100 000', ''), ('Stul', 'dona | 2 | 50 000', ''),
                                      ('Итого', '', '450 000')], locale='ru')
    assert again[-1] == ['Итого', '', '', '', '500 000'] and len(again) == 3


def test_an_offer_with_a_line_it_cannot_compute_prints_no_total():
    # The template says partial: none: a total of some of the lines would read as the price of all of them.
    rows, totals = made(OFFER, 'prices', [('Parta', 'dona | 40 | 650 000', ''), ('Montaj', 'xizmat | 1 |', '')])
    assert rows == [['Parta', 'dona', '40', '650 000', '26 000 000'], ['Montaj', 'xizmat', '1', '', '']]
    assert totals == [None, None]


def test_a_plan_total_of_only_the_items_with_a_figure_says_so():
    rows, totals = made(PLAN, 'finance_investment', [('Uskunalar', '', '180 000 000'), ('Bino', '', '90 000 000'),
                                                      ('Xomashyo', '', '')])
    assert rows[-1] == ['Jami (ko‘rsatilgan moddalar)', '', '', '270 000 000'] and totals[-1] == 'named'
    english, _ = made(PLAN, 'finance_investment', [('Equipment', '', '180,000,000'), ('Building', '', '90,000,000'),
                                                    ('Stock', '', '')], locale='en')
    assert english[-1] == ['Total (items listed)', '', '', '270,000,000']


def test_a_table_of_one_row_has_no_total():
    rows, totals = made(PLAN, 'finance_investment', [('Uskunalar', '2 | 90 000 000', '')])
    assert rows == [['Uskunalar', '2', '90 000 000', '180 000 000']] and totals == [None]


def test_a_payroll_multiplies_and_totals_both_the_people_and_the_pay():
    rows, totals = made(PLAN, 'team', [('Qandolatchi', '4 | 4 500 000', ''), ('Haydovchi', '1 | 3 800 000', '')])
    assert rows == [['Qandolatchi', '4', '4 500 000', '18 000 000'], ['Haydovchi', '1', '3 800 000', '3 800 000'],
                    ['Jami', '5', '', '21 800 000']]


# ---------------------------------------------------------------- differences, per cents, shares


def test_a_report_computes_difference_and_per_cent_of_plan_with_their_signs():
    rows, _ = made(REPORT, 'indicators', [('Sotuv', 'mln so‘m | 480 | 502 | | ', ''),
                                          ('Qaytarilgan', 'ta | 12 | 9 | | ', 'kam'),
                                          ('Muddat', 'kun | 3 | 3 | | ', '')])
    assert rows == [['Sotuv', 'mln so‘m', '480', '502', '+22', '104,6%', ''],
                    ['Qaytarilgan', 'ta', '12', '9', '−3', '75,0%', 'kam'],
                    ['Muddat', 'kun', '3', '3', '0', '100,0%', '']]
    english, _ = made(REPORT, 'indicators', [('Sales', 'UZS mln | 1,920 | 2,046 | | ', '')], locale='en')
    assert english[0][4:6] == ['+126', '106.6%']


def test_a_level_indicator_in_per_cent_has_a_dash_and_a_plan_of_zero_no_per_cent():
    rows, _ = made(REPORT, 'indicators', [('Ulush', '% | 62 | 66 | | ', ''), ('Yangi', 'ta | 0 | 4 | | ', '')])
    assert rows[0][4:6] == ['+4', '—']
    assert rows[1][4:6] == ['+4', ''], 'a per cent of nothing is no figure'


def test_shares_are_whole_per_cents_adding_to_a_hundred_and_the_total_row_says_so():
    rows, totals = made(MARKETING, 'budget', [('Instagram', '10 000 000', ''), ('Bloggerlar', '10 000 000', ''),
                                              ('Telegram', '10 000 000', '')])
    assert [row[2] for row in rows] == ['34%', '33%', '33%', '100%']
    assert rows[-1] == ['Jami', '30 000 000', '100%'] and totals[-1] is True
    plan, _ = made(PLAN, 'finance_sources', [('O‘z mablag‘i', '120 mln', ''), ('Kredit', '300 mln', '')])
    assert plan == [['O‘z mablag‘i', '120 mln', '29%'], ['Kredit', '300 mln', '71%'], ['Jami', '420 mln', '100%']]


# ---------------------------------------------------------------- reading and writing numbers


def test_units_and_scales_follow_the_inputs():
    rows, _ = made(OFFER, 'prices', [('Uskuna', 'dona | 2 | 1,5 mln so‘m', ''),
                                     ('Montaj', 'xizmat | 1 | 2 mln so‘m', '')])
    assert [row[4] for row in rows] == ['3 mln so‘m', '2 mln so‘m', '5 mln so‘m']
    # Inputs written differently are added as full numbers.
    mixed, _ = made(PLAN, 'finance_investment', [('Uskuna', '', '130 mln'), ('Bino', '', '40 000 000')])
    assert mixed[-1][3] == '170 000 000'


@pytest.mark.parametrize(('text', 'locale', 'value'), [
    ('650 000 so‘m', 'uz', 650000), ('1,5 mln', 'uz', 1500000), ('$120.55', 'en', 120.55), ('12 %', 'uz', 12),
    ('1.150.000', 'uz', 1150000), ('1,150,000', 'en', 1150000), ('2,100.00', 'en', 2100), ('1.067,08', 'ru', 1067.08),
    ('1,150', 'en', 1150), ('−3', 'uz', -3), ('130 млн сум', 'ru', 130000000),
])
def test_one_number_as_a_customer_types_it_is_read(text, locale, value):
    assert float(derive.read(text, locale).value) == pytest.approx(value)


@pytest.mark.parametrize('text', ['taxminan 500 000', '3-5', '10–15 kun', '1,150', '____', '', 'kelishiladi',
                                  '~200', '12.03.2026', '2 ta 500 dan'])
def test_a_range_a_guess_a_date_or_an_ambiguous_figure_is_not_read(text):
    assert derive.read(text, 'uz') is None


def test_a_cell_computed_from_an_unread_input_stays_blank():
    rows, totals = made(OFFER, 'prices', [('Parta', 'dona | taxminan 40 | 650 000', ''),
                                          ('Stul', 'dona | 40 | 1,150', '')])
    assert [row[4] for row in rows] == ['', ''] and totals == [None, None]


def test_numbers_are_written_in_the_papers_language_rounded_half_up():
    assert derive.number(derive.Decimal('1067.075'), 'en', decimals=2) == '1,067.08'
    assert derive.number(derive.Decimal('1067.075'), 'ru', decimals=2) == '1 067,08'
    assert derive.number(derive.Decimal('104.55'), 'uz', decimals=1) == '104,6'
    assert derive.number(derive.Decimal('-3'), 'uz', sign=True) == '−3'
    assert derive.number(derive.Decimal('22'), 'uz', sign=True) == '+22'
    assert derive.number(derive.Decimal('2.50'), 'uz') == '2,5'


def test_an_offer_rounds_each_amount_to_its_currency_and_totals_the_rounded_amounts():
    dollars, _ = made(OFFER, 'prices', [('A', 'pcs | 3 | 0.335', ''), ('B', 'pcs | 1 | 2.10', '')], locale='en',
                      facts_items=[('currency', 'USD')])
    assert [row[4] for row in dollars] == ['1.01', '2.10', '3.11']
    sums, _ = made(OFFER, 'prices', [('A', 'dona | 3 | 333,5', ''), ('B', 'dona | 1 | 1 000', '')],
                   facts_items=[('currency', 'so‘m')])
    assert [row[4] for row in sums] == ['1 001', '1 000', '2 001']


# ---------------------------------------------------------------- trust and safety


def test_an_input_the_customer_never_gave_computes_nothing_while_code_made_cells_add_up():
    trusted = facts.trusting('4 nafar qandolatchi, oyligi 4 500 000; 1 haydovchi')
    rows, totals = made(PLAN, 'team', [('Qandolatchi', '4 | 4 500 000', ''), ('Haydovchi', '1 | 3 800 000', '')],
                        trusted=trusted)
    assert rows[0][3] == '18 000 000', 'its inputs are the customer\'s'
    assert rows[1][3] == '', '3 800 000 was never said'
    # The people add up; one pay is no total of pay, so that cell stays empty under the partial total's word.
    assert rows[-1] == ['Jami (ko‘rsatilgan moddalar)', '5', '', ''] and totals[-1] == 'named'


def test_an_entry_without_computed_tables_gets_its_content_back_as_it_is():
    content = {'title': 'Ariza', 'sections': [], 'questions': []}
    assert derive.apply(catalogue.get('pdf.xat.ariza'), content, object()) is content


def test_derive_never_raises_on_odd_content_and_leaves_the_rest_alone():
    entry = catalogue.get(OFFER)
    content = {'title': 'x', 'sections': ['not a section', {'id': 'prices', 'items': ['row', None, 3]},
                                          {'id': 'opening', 'body': 'Salom'}], 'questions': []}
    result = derive.apply(entry, copy.deepcopy(content), object(), locale='uz')
    assert result['sections'][2] == {'id': 'opening', 'body': 'Salom'}
    assert derive.apply(entry, None, object()) is None


def test_derive_is_idempotent():
    entry = catalogue.get(MARKETING)
    content = {'title': '', 'questions': [], 'sections': [section('budget', [('A', '14 000 000', ''),
                                                                            ('B', '6 000 000', '')])]}
    once = derive.apply(entry, content, object(), locale='uz')
    assert derive.apply(entry, once, object(), locale='uz') == once


@pytest.mark.parametrize('template_id', ['business_taklif', 'business_hisobot', 'business_biznes_reja',
                                         'business_marketing_reja'])
@pytest.mark.parametrize('case', ['full', 'long'])
def test_every_business_sample_is_what_derive_makes_of_it(template_id, case):
    # The samples are finished content: their computed cells and totals are derive's, so a sheet shows a job's paper.
    given = sample.load(template_id, case)
    entry = catalogue.get(given['entry'])
    for locale in ('uz', 'ru', 'en'):
        content = sample.content_of(given, locale)
        assert derive.apply(entry, content, object(), locale=locale) == content, locale


# ---------------------------------------------------------------- in the finish


def test_the_finish_fills_computed_cells_from_the_customers_numbers_after_grounding():
    offer = ('Misol Mebel MChJ nomidan 41-maktabga tijorat taklifi: 40 ta parta har biri 650 000 so‘m, 40 ta stul '
             '280 000 so‘mdan, jami 40 000 000 so‘m.')
    rows = finished_table(OFFER, offer, 1, 'prices', [('Parta', 'dona | 40 | 650 000', '26 000 000'),
                                                      ('Stul', 'dona | 40 | 280 000', ''),
                                                      ('Jami', '', '40 000 000')])
    # 26 000 000 and 11 200 000 were never typed: code wrote them after the grounding, and the customer's own
    # 40 000 000 is not the sum of the lines, so it never prints.
    assert rows == [['Parta', 'dona', '40', '650 000', '26 000 000'], ['Stul', 'dona', '40', '280 000', '11 200 000'],
                    ['Jami', '', '', '', '37 200 000']]
