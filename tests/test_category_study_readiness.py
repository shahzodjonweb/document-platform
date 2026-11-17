"""The academic and study papers are ready to be ticked (N2a): what a tick rests on, held in code.

Mustaqil ish, kurs ishi, konspekt, dars ishlanmasi with its tarqatma, and the
test are drawn in their own templates (R3a, R3b). A ready entry is only
tickable: the owner's tick on /ops/categories is what puts it in front of
customers, and that page shows each entry's gates beside its tick. So a ready
paper meets every readiness check of the catalogue as an error, says which
checks a person still makes (a native reader, one real-provider run, which
ai_smoke.py --category now makes for a paper too), and holds its pages: at
every length and under every cue subset its entry allows, a paper written at
0.9 of its parts' top word counts ends within its quote through the real
blocks, never cut below 0.7 of its sentences. A lesson's cover and a handout's
answer key are sheets the quote does not count, as the research counts body
pages (page_rule.uncounted). The three languages of that sweep were run by
hand for the readiness read; here it runs in Uzbek, whose fixed words are the
longest. Every person and organisation in the samples is invented.
"""
import itertools
import random
import re
import runpy
import sys
from pathlib import Path

import pdfplumber
import pytest

from apps.studio import paper, provider
from apps.studio.categories import catalogue, skeleton
from apps.studio.categories.catalogue import SOURCES_CUE
from apps.studio.paper import fit, sample
from tests.test_category_deck_readiness import customer_copy
from tests.test_category_study_entries import _content

STUDY = ('pdf.mustaqil_ish', 'pdf.kurs_ishi', 'pdf.konspekt', 'pdf.dars_ishlanmasi', 'pdf.test')
COUNTED = STUDY[:4]
SMOKE = Path(__file__).resolve().parents[1] / 'scripts' / 'operations' / 'ai_smoke.py'


def entry(entry_id):
    return catalogue.get(entry_id)


def test_every_study_paper_is_ready_and_meets_its_gates_as_errors():
    assert all(entry(entry_id).status == catalogue.READY for entry_id in STUDY)
    found = [str(problem) for problem in catalogue.check('pdf.') if problem.subject in STUDY]
    assert found == []
    for entry_id in STUDY:
        for template_id in entry(entry_id).templates:
            assert paper.registry.missing(paper.flow_blocks(catalogue.template(template_id))) == []


@pytest.mark.parametrize('entry_id', STUDY)
def test_the_switch_page_says_what_a_person_still_checks_before_the_tick(entry_id):
    gates = entry(entry_id).raw['gates']
    assert any(re.search(r'native (Uzbek|speaker)', gate) for gate in gates), 'a native reader'
    assert any(re.search(rf'ai_smoke\.py --category {re.escape(entry_id)}\b(?!\.)', gate) for gate in gates), \
        'one real-provider run'


def test_no_customer_text_breaks_off_mid_sentence():
    for entry_id in STUDY:
        for where, locale, text in customer_copy(entry(entry_id).raw):
            assert not text.rstrip().endswith((',', ';', ' —', ' -')), (entry_id, where, locale, text)


# ---------------------------------------------------------------- every length and cue subset


def subsets(paper_entry):
    """The cue subsets of an entry that draw a different paper: its effective cues, one per set of parts and template."""
    names = sorted(set(paper_entry.raw['cues']) | {SOURCES_CUE})
    seen = {}
    for size in range(len(names) + 1):
        for chosen in itertools.combinations(names, size):
            held = skeleton.effective(paper_entry, set(chosen))
            parts = tuple(sorted({use.part['id'] for length in (paper_entry.length['min'], paper_entry.length['max'])
                                  for use in skeleton.parts(paper_entry, length, held)}))
            uncounted = tuple(when for when in (catalogue.template(paper.pick(paper_entry, 'uz', held))['page_rule']
                                                .get('uncounted') or ()) if when.startswith(('cue:', 'nocue:'))
                              and (when.partition(':')[2] in held) == when.startswith('cue:'))
            seen.setdefault((paper.pick(paper_entry, 'uz', held), parts, uncounted), held)
    return list(seen.values())


def sizes(paper_entry, length):
    """(instances written of each group the model sizes, parts its rules leave empty): the fewest and the most.

    A mustaqil ish below 11 pages has two chapters (its plan rule); three are drawn there too, with the third
    section empty, as C2a sized them, for a plan of five or six points.
    """
    groups = [spec for spec in (paper_entry.raw.get('groups') or {}).values() if spec['sized'] == 'model']
    if not groups:
        return [(0, ())]
    made = [(min(spec['min'] for spec in groups), ()), (max(spec['max'] for spec in groups) * 4, ())]
    if paper_entry.id == 'pdf.mustaqil_ish' and length < 11:
        made[1] = (3, ('section_c',))
    return made


def cases():
    found = []
    for entry_id in COUNTED:
        paper_entry = entry(entry_id)
        for held in subsets(paper_entry):
            for length in range(paper_entry.length['min'], paper_entry.length['max'] + 1):
                found.append(pytest.param(entry_id, held, length,
                                          id=f"{entry_id}-{'+'.join(sorted(held)) or 'plain'}-{length}"))
    return found


@pytest.mark.parametrize('entry_id, held, length', cases())
def test_every_length_and_cue_subset_ends_within_its_quote_barely_cut(entry_id, held, length, tmp_path):
    paper_entry = entry(entry_id)
    template_id = paper.pick(paper_entry, 'uz', held)
    for written, empty in sizes(paper_entry, length):
        content = _content(paper_entry, length, held, written, empty, random.Random(7))
        made = paper.render_paper(content, tmp_path / 'p.pdf', 'uz', entry=paper_entry, template=template_id,
                                  pages=length, cues=held)
        metadata = made['metadata']
        quoted = length + metadata['uncounted']
        assert made['page_count'] <= quoted and fit.LONGER not in metadata['warnings'], (written, made['page_count'],
                                                                                         metadata)
        assert metadata['trim_ratio'] is None or metadata['trim_ratio'] >= 0.7, (written, metadata['trim_ratio'])
        assert not [code for code in metadata['warnings'] if code.startswith(('block_fallback', 'template_fallback'))]


def test_the_sweep_covers_the_forms_the_gates_name():
    forms = {entry_id: [frozenset(held) for held in subsets(entry(entry_id))] for entry_id in COUNTED}
    assert {frozenset(), frozenset({'summary'}), frozenset({'qa'})} <= set(forms['pdf.konspekt'])
    assert frozenset({'handout'}) in forms['pdf.dars_ishlanmasi']
    assert any('cover' in held for held in forms['pdf.dars_ishlanmasi'])
    assert any('appendix' in held for held in forms['pdf.kurs_ishi'])


@pytest.mark.parametrize('questions', (1, 10, 20, 30, 40))
def test_a_test_of_any_size_holds_its_quote_in_every_language(questions, tmp_path):
    test = entry('pdf.test')
    pages = skeleton.length(test, questions=questions)
    full = sample.load('study_test', 'full')
    for locale in ('uz', 'ru', 'en'):
        content = sample.content_of(full, locale)
        given = content['questions']
        content['questions'] = [dict(given[number % len(given)]) for number in range(questions)]
        made = paper.render_paper(content, tmp_path / f'{locale}.pdf', locale, entry=test, template='study_test',
                                  pages=pages, day=sample.SAMPLE_DAY)
        # A test is a `flow` paper: its rule holds it within one page past the quote (fit.py: `pages + 1`), and
        # LONGER marks a run past that. Its key is inside the quote already (length.per.extra_pages), so this +1
        # is that tolerance, not a key: 40 Russian questions take 7 pages of a 6-page quote.
        assert made['page_count'] <= pages + 1 and fit.LONGER not in made['metadata']['warnings'], (locale, made)


# ---------------------------------------------------------------- what the sheets showed


def test_a_lessons_cover_and_a_handouts_key_are_sheets_the_quote_does_not_count(tmp_path):
    lesson = entry('pdf.dars_ishlanmasi')
    for held, template_id in ((frozenset({'cover'}), 'study_dars_ishlanmasi'),
                              (frozenset({'handout'}), 'study_tarqatma')):
        content = _content(lesson, 2, held, 6, (), random.Random(7))
        made = paper.render_paper(content, tmp_path / 'p.pdf', 'uz', entry=lesson, template=template_id, pages=2,
                                  cues=held)
        metadata = made['metadata']
        assert (made['page_count'], metadata['uncounted']) == (3, 1), metadata
        assert fit.LONGER not in metadata['warnings'] and (metadata['trim_ratio'] or 1) >= 0.7, metadata
        if 'cover' in held:
            # A title page carries no number but still counts, as the body's "2 / 3" shows.
            with pdfplumber.open(made['path']) as pdf:
                feet = [' '.join(word['text'] for word in page.extract_words() if word['top'] > page.height - 40)
                        for page in pdf.pages]
            assert feet == ['', '2 / 3', '3 / 3'], feet
    # Without them, nothing beyond the quote.
    content = _content(lesson, 2, frozenset(), 6, (), random.Random(7))
    made = paper.render_paper(content, tmp_path / 'p.pdf', 'uz', entry=lesson, template='study_dars_ishlanmasi',
                              pages=2, cues=frozenset())
    assert (made['page_count'], made['metadata']['uncounted']) == (2, 0)


def test_an_uncounted_page_names_a_cue_or_part_its_entries_have():
    import copy
    entries, templates, index = copy.deepcopy(catalogue.read())
    templates['study_tarqatma']['page_rule']['uncounted'] = ['part:h_keys']
    with pytest.raises(catalogue.CatalogueError) as refused:
        catalogue.build(entries, templates, index)
    assert 'page_rule uncounted: when part:h_keys names no part' in str(refused.value)


def test_the_short_lesson_plan_and_the_shortest_kurs_ishi_leave_out_what_has_no_room():
    lesson, kurs = entry('pdf.dars_ishlanmasi'), entry('pdf.kurs_ishi')
    asked = frozenset({'results', 'group'})
    assert not {'expected_results', 'group_tasks'} & {use.part['id'] for use in skeleton.parts(lesson, 2, asked)}
    assert {'expected_results', 'group_tasks'} <= {use.part['id'] for use in skeleton.parts(lesson, 3, asked)}
    assert 'appendix' not in [use.part['id'] for use in skeleton.parts(kurs, 12, frozenset({'appendix'}))]
    assert 'appendix' in [use.part['id'] for use in skeleton.parts(kurs, 13, frozenset({'appendix'}))]
    assert skeleton.words(kurs, next(use for use in skeleton.parts(kurs, 35, frozenset({'appendix'}))
                                     if use.part['id'] == 'appendix'), 35, frozenset({'appendix'})) == (40, 250)


def test_a_boxed_heading_goes_over_a_page_foot_with_its_first_line(tmp_path):
    # The notes' "Key points" box once left its bold name alone at the foot of page 1, its lines on page 2.
    drawn = sample.draw('study_konspekt', 'blank', 'en', tmp_path)
    with pdfplumber.open(drawn.path) as pdf:
        pages = [page.extract_text() or '' for page in pdf.pages]
    holding = [text for text in pages if 'Key points' in text]
    assert holding and all('First law' in text for text in holding)


# ---------------------------------------------------------------- the real-provider run


def smoke(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, 'argv', [str(SMOKE), *argv])
    with pytest.raises(SystemExit) as ended:
        runpy.run_path(str(SMOKE), run_name='__main__')
    return ended.value.code, capsys.readouterr().out


@pytest.mark.django_db
@pytest.mark.parametrize('entry_id', STUDY)
def test_the_smoke_makes_a_study_paper_through_the_real_pipeline(entry_id, settings, monkeypatch, capsys, tmp_path):
    # The owner's run on the server, with the model stubbed: it answers with the template's own sample.
    from tests.test_page_fill import live
    live(settings)
    calls = []

    def model(config, data, feature_id, request_id, **kwargs):
        calls.append([section['id'] for section in data['content']['sections']])
        template_id = paper.template_for(data)
        content = sample.content_of(sample.load(template_id, 'full'), data['output_locale'])
        return {**content, 'answer_supported': True}, {'input_tokens': 1, 'output_tokens': 1}
    monkeypatch.setattr(provider, 'generate', model)
    code, out = smoke(monkeypatch, capsys, '--category', entry_id, '--locale', 'uz', '--out', str(tmp_path))
    assert code == 0, out
    assert len(calls) == 1 and f'{entry_id} template' in out and 'emergency fallback' not in out
    assert 'FAIL' not in out and f'{entry_id} pages' in out
    assert list(tmp_path.glob(f'{entry_id}-uz-*.pdf'))
