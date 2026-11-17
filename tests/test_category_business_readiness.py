"""The business papers are ready to be ticked (N2b): what a tick rests on, held in code.

The seven entries of the pdf.biz group: the business plan, the commercial
offer, the report, the staff instruction, the job description, the minutes
and the marketing plan, drawn in their own templates (R5a, R5b). A ready entry
is only tickable; the owner's tick on /ops/categories is what puts it in front
of customers, beside the entry's gates. So a ready paper must pass every
readiness check of the catalogue as an error, say on that page which checks a
person still makes (a native Uzbek and a native Russian reader, one
real-provider run), and be drawn by its own template, never the emergency
fallback, at every length it can be quoted and under every set of cues its
message can hold, in every language, with the checker finding nothing, as the
sheets the owner compares with the mock-ups were drawn. The facts corpus at
zero (tests/test_category_facts_corpus.py) covers these entries' own examples
as it covers every entry. Every person, organisation and figure here is
invented.
"""
import copy
import itertools
import runpy
import sys
from pathlib import Path

import pdfplumber
import pytest

from apps.studio import paper, provider
from apps.studio.categories import catalogue, derive, skeleton
from apps.studio.categories.catalogue import LOCALES
from apps.studio.categories.skeleton import SOURCES_CUE, cues_of
from apps.studio.paper import check, registry, sample
from tests.test_category_deck_readiness import customer_copy

BUSINESS = [entry for entry in catalogue.for_feature('ai.pdf_topic') if entry.id.startswith('pdf.biz.')]
SMOKE = Path(__file__).resolve().parents[1] / 'scripts' / 'operations' / 'ai_smoke.py'
DAY = sample.SAMPLE_DAY


def held_sets(entry):
    """Every set of cues a message can give the entry, after `exclusive`, each once."""
    names = sorted(set(entry.raw.get('cues') or {}) | {SOURCES_CUE})
    found = {skeleton.effective(entry, chosen) for size in range(len(names) + 1)
             for chosen in itertools.combinations(names, size)}
    return sorted(found, key=sorted)


def lengths(entry):
    return range(entry.length['min'], entry.length['max'] + 1)


def drawn(entry, template_id, case, locale, pages, cues, folder):
    """The template's sample of `case` drawn as a job of this length and these cues draws it; (artifact, problems).

    A job's paper holds only the sections its draft was seeded with: a one-page marketing plan is asked for no
    competitors or SWOT (the short forms are the parts' own `from`), so the sample keeps those sections alone.
    """
    template = catalogue.template(template_id)
    content = sample.content_of(sample.load(template_id, case), locale)
    seeded = {section['id'] for section in skeleton.seed(entry, pages, cues)} | {'facts'}
    content['sections'] = [section for section in content['sections'] if section['id'] in seeded]
    path = Path(folder) / f'{template_id}-{case}-{locale}-{pages}-{"-".join(sorted(cues)) or "none"}.pdf'
    artifact = paper.render_paper(dict(content), path, locale, entry=entry, template=template_id, pages=pages,
                                  cues=cues, day=DAY)
    expect = check.expect_for(artifact, content, entry=entry, template=template, locale=locale, pages=pages,
                              cues=cues, day=DAY)
    return artifact, check.problems(Path(artifact['path']), expect)


def test_every_business_paper_is_ready_and_meets_its_gates_as_errors():
    assert [entry.id for entry in BUSINESS] == [
        'pdf.biz.biznes_reja', 'pdf.biz.tijorat_taklifi', 'pdf.biz.hisobot', 'pdf.biz.yoriqnoma',
        'pdf.biz.lavozim_yoriqnomasi', 'pdf.biz.bayonnoma', 'pdf.biz.marketing_reja']
    assert all(entry.status == catalogue.READY for entry in BUSINESS)
    assert [str(problem) for problem in catalogue.check('pdf.biz.')] == []


@pytest.mark.parametrize('entry', BUSINESS, ids=lambda entry: entry.id)
def test_the_switch_page_says_what_a_person_still_checks_before_the_tick(entry):
    gates = ' '.join(entry.raw['gates'])
    assert 'native Uzbek' in gates and 'native Russian reader' in gates, 'the native read'
    assert f'ai_smoke.py --category {entry.id} ' in gates, 'one real-provider run'
    # The templates are R5a's and R5b's now, drawn and checked: no gate still calls them a placeholder.
    assert 'first draft' not in gates


def test_no_customer_text_breaks_off_mid_sentence():
    for entry in BUSINESS:
        for where, locale, text in customer_copy(entry.raw):
            assert not text.rstrip().endswith((',', ';', ' —', ' -')), (entry.id, where, locale, text)


@pytest.mark.parametrize('entry', BUSINESS, ids=lambda entry: entry.id)
def test_every_template_of_a_business_paper_has_its_samples_and_every_block(entry):
    for template_id in entry.templates:
        assert sample.load(template_id, 'full'), template_id
        assert not registry.missing(paper.flow_blocks(catalogue.template(template_id))), template_id


@pytest.mark.parametrize('entry', BUSINESS, ids=lambda entry: entry.id)
def test_every_length_and_cue_subset_is_seeded_and_drawn_in_its_template(entry, tmp_path):
    # The paper a job draws for each quote and cue set: seeded with every written part, asked for no more words
    # than a body holds, picked into a template this worker draws whole, and read back clean in both the full
    # case (every fact) and the blank one (every ruled blank) in each language. Every business paper is a
    # ceiling: drawn at a quote below its sample's pages it runs past and says so, and is never cut.
    for held in held_sets(entry):
        for pages in lengths(entry):
            seeded = skeleton.seed(entry, pages, held)
            ids = [section['id'] for section in seeded]
            assert ids and len(ids) == len(set(ids)), (entry.id, sorted(held), pages)
            for use in skeleton.parts(entry, pages, held):
                low, high = skeleton.words(entry, use, pages, held)
                assert 0 == low <= high <= skeleton.SECTION_WORDS, (entry.id, use.section_id, sorted(held), pages)
            for locale in LOCALES:
                template_id = paper.pick(entry, locale, held)
                assert template_id in entry.templates
                for case in ('full', 'blank'):
                    artifact, found = drawn(entry, template_id, case, locale, pages, held, tmp_path)
                    metadata = artifact['metadata']
                    assert metadata['template'] == template_id and not metadata.get('template_fallback')
                    assert not any(code.startswith(('block_fallback', 'shortened')) for code in metadata['warnings'])
                    assert metadata['trim_ratio'] is None
                    assert found == [], (entry.id, template_id, case, locale, pages, sorted(held), found)


# ---------------------------------------------------------------- what the sheets showed


def words(path):
    with pdfplumber.open(path) as document:
        return [word for page_ in document.pages for word in page_.extract_words()]


def lines(path):
    with pdfplumber.open(path) as document:
        text = '\n'.join(page_.extract_text() or '' for page_ in document.pages).replace('\xa0', ' ')
    return [line.strip() for line in text.split('\n') if line.strip()]


def test_a_blank_row_whose_label_takes_two_lines_is_drawn_below_the_row_above_it(tmp_path):
    # The blank business plan in Russian: "Организационно-правовая форма" wraps in its 48 mm column, and its row
    # was held to one line's height, so the label was drawn over "Инициатор" above it. It breaks at its hyphen
    # now, not inside a word, and its row is as tall as the label.
    plan = catalogue.get('pdf.biz.biznes_reja')
    artifact, found = drawn(plan, 'business_biznes_reja', 'blank', 'ru', plan.length['default'], frozenset(),
                            tmp_path)
    assert found == []
    shown = words(artifact['path'])
    above = next(word for word in shown if word['text'] == 'Инициатор')
    label = [word for word in shown if word['text'].startswith('Организационно')]
    assert [word['text'] for word in label] == ['Организационно-']
    assert label[0]['top'] >= above['bottom']
    assert 'правовая' in [word['text'] for word in shown]


def cells(path):
    """Each printed line of the first page as its cells: words closer than a column gap ("26 000 000") joined."""
    with pdfplumber.open(path) as document:
        found = document.pages[0].extract_words(x_tolerance=5, keep_blank_chars=True)
    rows = itertools.groupby(sorted(found, key=lambda word: (round(word['top']), word['x0'])),
                             key=lambda word: round(word['top']))
    return [[word['text'] for word in row] for _, row in rows]


@pytest.mark.parametrize('locale', LOCALES)
def test_every_amount_and_total_of_the_drawn_offer_is_its_quantity_times_its_price(locale, tmp_path):
    # The offer's gate: check by hand that every computed amount and total equals quantity times price. The rows
    # are read back from the drawn page in the language's own marks, so what a reader multiplies is what derive
    # wrote (so‘m in uz and ru, dollars and cents in en).
    offer = catalogue.get('pdf.biz.tijorat_taklifi')
    artifact, found = drawn(offer, 'business_taklif', 'full', locale, 1, frozenset(), tmp_path)
    assert found == []
    rows, totals = [], []
    for line in cells(artifact['path']):
        read = [derive.read(cell, locale) for cell in line[-3:]]
        if line[0] in ('Jami', 'Итого', 'Total'):
            totals.append(derive.read(line[-1], locale).value)
        elif len(line) == 5 and all(read):
            rows.append([number.value for number in read])
    assert len(rows) == 3, rows
    for quantity, price, line_amount in rows:
        assert quantity * price == line_amount, (locale, quantity, price, line_amount)
    assert totals == [sum(row[2] for row in rows)]


def strip_words(path):
    """The words of the key-figure strip on the plan's second page, from its first label to the next heading."""
    shown = [word['text'] for word in words(path)]
    start = next(index for index, word in enumerate(shown) if word in ('Umumiy', 'Общие', 'Total'))
    return shown[start:shown.index('1.1', start)]


@pytest.mark.parametrize('locale, mark', [('uz', 'so‘m'), ('ru', 'сумов'), ('en', 'UZS')])
def test_the_plans_computed_investment_card_carries_the_currency_its_neighbours_name(locale, mark, tmp_path):
    # The investment rows name no currency, so derive's total is a bare number; beside "120 mln so‘m" the card
    # read "420 000 000" alone. derive takes such amounts to be in the paper's currency, so the card says it: the
    # strip's three cards each carry the mark (its small unit sits on its own line of the extracted text).
    plan = catalogue.get('pdf.biz.biznes_reja')
    artifact, found = drawn(plan, 'business_biznes_reja', 'full', locale, 5, frozenset(), tmp_path)
    assert found == []
    assert strip_words(artifact['path']).count(mark) == 3


@pytest.mark.parametrize('facts, shown', [
    # Dollars beside so‘m (no currency fact): which one the bare total is in would be a guess, so it stays bare.
    ({'own_funds': '$10 000'}, ['420', '000', '000', '$10']),
    # Dollars on both cards but no currency fact: derive reads the bare rows as so‘m, so the card names neither.
    ({'own_funds': '$10 000', 'external_funding': '$20 000'}, ['420', '000', '000', '$10']),
    # The customer named dollars: the rows, their total and both cards are in dollars, written as derive writes them.
    ({'own_funds': '$10 000', 'external_funding': '$20 000', 'currency': 'AQSH dollari'}, ['$420', '000', '000']),
])
def test_a_computed_card_takes_a_currency_only_when_the_paper_and_its_neighbours_agree(facts, shown, tmp_path):
    plan = catalogue.get('pdf.biz.biznes_reja')
    given = copy.deepcopy(sample.load('business_biznes_reja', 'full'))
    given['uz']['facts'].update(facts)
    content = sample.content_of(given, 'uz')
    artifact = paper.render_paper(content, tmp_path / 'mixed.pdf', 'uz', entry=plan, template='business_biznes_reja',
                                  pages=5, cues=frozenset(), day=DAY)
    strip = [word for word in strip_words(artifact['path']) if word not in ('so‘m', 'mln')]
    first = strip.index(shown[0])
    assert strip[first:first + len(shown)] == shown, strip


def test_the_three_kinds_of_staff_instruction_take_their_own_head_and_chapters(tmp_path):
    # A work, a safety and a rules instruction (the yo‘riqnoma's render gate), in the one template.
    instruction = catalogue.get('pdf.biz.yoriqnoma')
    shown = {}
    for name, cues in (('work', frozenset()), ('safety', frozenset({'safety'})), ('rules', frozenset({'rules'}))):
        assert paper.pick(instruction, 'uz', cues) == 'business_yoriqnoma'
        artifact, found = drawn(instruction, 'business_yoriqnoma', 'full', 'uz', 3, cues, tmp_path)
        assert found == [] and not artifact['metadata'].get('template_fallback'), (name, found)
        shown[name] = ' '.join(lines(artifact['path']))
    assert 'Umumiy qoidalar' in shown['work'] and 'xavfsizlik talablari' in shown['safety']
    assert 'QOIDALAR' in shown['rules'].replace(' ', '') and 'Qoidalar bilan tanishdim' in shown['rules']
    assert 'Yo‘riqnoma bilan tanishdim' in shown['work'] and 'Yo‘riqnoma bilan tanishdim' in shown['safety']


class Model:
    """provider.generate answered with the picked template's full sample: the smoke's pipeline, no network."""

    def __init__(self, monkeypatch):
        self.calls = []
        monkeypatch.setattr(provider, 'generate', self)

    def __call__(self, config, data, feature_id, request_id, **kwargs):
        entry = catalogue.get(data['options']['category'])
        template_id = paper.pick(entry, data['output_locale'], cues_of(data))
        self.calls.append((entry.id, template_id, data['options']['length']))
        content = sample.content_of(sample.load(template_id, 'full'), data['output_locale'])
        return {'title': content['title'], 'sections': content['sections'], 'questions': [],
                'answer_supported': True}, {'input_tokens': 1, 'output_tokens': 1}


@pytest.mark.django_db
@pytest.mark.parametrize('locale', ('uz', 'ru'))
def test_the_smoke_makes_every_business_paper_in_its_own_template(locale, settings, monkeypatch, capsys, tmp_path):
    # The real-provider gate runs this script on the server; here the provider is the samples.
    from operations.integrations import save_config
    save_config('ai', {'mode': 'openai', 'model': 'test-model', 'api_key': 'sk-offline-test'})
    model = Model(monkeypatch)
    monkeypatch.setattr(sys, 'argv', [str(SMOKE), '--category', 'pdf.biz.', '--locale', locale, '--out',
                                      str(tmp_path)])
    with pytest.raises(SystemExit) as ended:
        runpy.run_path(str(SMOKE), run_name='__main__')
    out = capsys.readouterr().out
    assert ended.value.code == 0, out
    assert 'FAIL' not in out and 'Every category checked was made.' in out
    assert [call[0] for call in model.calls] == [entry.id for entry in BUSINESS]
    for entry_id, template_id, length in model.calls:
        assert f'{entry_id} template' in out and template_id in out
    assert len(list(tmp_path.glob('*.pdf'))) == len(BUSINESS)
