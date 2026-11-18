"""The official papers and letters are ready to be ticked (N2c): what a tick rests on, held in code.

The six entries of the pdf.xat group: the motivation letter, the cover
letter, the ariza, the character reference, the recommendation and the
explanatory note. A ready entry is only tickable; the owner's tick on
/ops/categories is what puts it in front of customers, beside the entry's
gates. So a ready letter must pass every readiness check of the catalogue as
an error, say on that page which checks a person still makes (a native
Uzbek and a native Russian reader, one real-provider run), and be drawn by
its own template, never the emergency fallback, at every length it can be
quoted and under every set of cues its message can hold, in every language,
with the checker finding nothing, as the sheets the owner compares with the
mock-ups were drawn. The facts corpus at zero (tests/test_category_facts_
corpus.py) covers these entries' own examples as it covers every entry.
Every person and organisation here is invented.
"""
import itertools
import runpy
import sys
from pathlib import Path

import pdfplumber
import pytest

from apps.studio import paper, provider
from apps.studio.categories import catalogue, skeleton
from apps.studio.categories.catalogue import LOCALES
from apps.studio.categories.skeleton import SOURCES_CUE, cues_of
from apps.studio.paper import check, registry, sample

LETTERS = [entry for entry in catalogue.for_feature('ai.pdf_topic') if entry.id.startswith('pdf.xat.')]
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
    """The template's sample of `case` drawn as a job of this length and these cues draws it; (artifact, problems)."""
    template = catalogue.template(template_id)
    content = sample.content_of(sample.load(template_id, case), locale)
    path = Path(folder) / f'{template_id}-{case}-{locale}-{pages}-{"-".join(sorted(cues)) or "none"}.pdf'
    artifact = paper.render_paper(dict(content), path, locale, entry=entry, template=template_id, pages=pages,
                                  cues=cues, day=DAY)
    expect = check.expect_for(artifact, content, entry=entry, template=template, locale=locale, pages=pages,
                              cues=cues, day=DAY)
    return artifact, check.problems(Path(artifact['path']), expect)


def test_every_letter_is_ready_and_meets_its_gates_as_errors():
    assert [entry.id for entry in LETTERS] == [
        'pdf.xat.motivatsion', 'pdf.xat.ishga_kirish', 'pdf.xat.ariza', 'pdf.xat.tavsifnoma', 'pdf.xat.tavsiya',
        'pdf.xat.tushuntirish']
    assert all(entry.status == catalogue.READY for entry in LETTERS)
    assert [str(problem) for problem in catalogue.check('pdf.xat.')] == []


@pytest.mark.parametrize('entry', LETTERS, ids=lambda entry: entry.id)
def test_the_switch_page_says_what_a_person_still_checks_before_the_tick(entry):
    gates = ' '.join(entry.raw['gates'])
    assert 'native Uzbek reader' in gates and 'native Russian reader' in gates, 'the native read'
    assert f'ai_smoke.py --category {entry.id} ' in gates, 'one real-provider run'


@pytest.mark.parametrize('entry', LETTERS, ids=lambda entry: entry.id)
def test_every_template_of_a_letter_has_its_samples_and_every_block(entry):
    for template_id in entry.templates:
        assert sample.load(template_id, 'full'), template_id
        assert not registry.missing(paper.flow_blocks(catalogue.template(template_id))), template_id


@pytest.mark.parametrize('entry', LETTERS, ids=lambda entry: entry.id)
def test_every_length_and_cue_subset_is_seeded_and_drawn_in_its_template(entry, tmp_path):
    # The paper a job draws for each quote and cue set: seeded with every written part, asked for no more words
    # than a body holds, picked into a template this worker draws whole, and read back clean in both the full
    # case (every fact) and the blank one (every ruled blank) in each language.
    for held in held_sets(entry):
        for pages in lengths(entry):
            seeded = skeleton.seed(entry, pages, held)
            ids = [section['id'] for section in seeded]
            assert ids and len(ids) == len(set(ids)), (entry.id, sorted(held), pages)
            for use in skeleton.parts(entry, pages, held):
                low, high = skeleton.words(entry, use, pages, held)
                assert 0 <= low <= high <= skeleton.SECTION_WORDS, (entry.id, use.section_id, sorted(held), pages)
            for locale in LOCALES:
                template_id = paper.pick(entry, locale, held)
                assert template_id in entry.templates
                for case in ('full', 'blank'):
                    artifact, found = drawn(entry, template_id, case, locale, pages, held, tmp_path)
                    metadata = artifact['metadata']
                    assert metadata['template'] == template_id and not metadata.get('template_fallback')
                    assert not any(code.startswith('block_fallback') for code in metadata['warnings'])
                    assert found == [], (entry.id, template_id, case, locale, pages, sorted(held), found)


def test_a_statement_and_an_english_recommendation_take_their_own_templates():
    motivatsion, tavsiya = catalogue.get('pdf.xat.motivatsion'), catalogue.get('pdf.xat.tavsiya')
    assert paper.pick(motivatsion, 'uz', frozenset({'statement'})) == 'letter_statement'
    assert paper.pick(motivatsion, 'uz', frozenset({'scholarship'})) == 'letter_motivatsion'
    assert [paper.pick(tavsiya, locale) for locale in LOCALES] == ['tavsiya_rasmiy', 'tavsiya_rasmiy',
                                                                   'letter_tavsiya']
    # A draft reads its cues from the customer's own words.
    data = {'options': {'category': 'pdf.xat.motivatsion'}, 'output_locale': 'en', 'prompt': 'A personal statement',
            'source_text': ''}
    assert 'statement' in cues_of(data) and paper.template_for(data) == 'letter_statement'


def lines(path):
    with pdfplumber.open(path) as document:
        text = '\n'.join(page_.extract_text() or '' for page_ in document.pages).replace('\xa0', ' ')
    return [line.strip() for line in text.split('\n') if line.strip()]


def ariza(tmp_path, locale, facts, name):
    entry = catalogue.get('pdf.xat.ariza')
    content = sample.content_of(sample.load('official_ariza', 'blank'), locale)
    content['sections'].insert(0, {'id': 'facts', 'heading': '', 'body': '', 'layout': 'list',
                                   'items': [{'label': key, 'text': value} for key, value in facts.items()]})
    artifact = paper.render_paper(content, tmp_path / name, locale, entry=entry, template='official_ariza', pages=1,
                                  day=DAY)
    assert not artifact['metadata'].get('template_fallback')
    return lines(artifact['path'])


def test_an_uzbek_ariza_blank_head_ends_in_ga_and_dan_as_the_mock_draws_it(tmp_path):
    # The ruled head of the blank ariza: "____ga (rahbarning lavozimi, F.I.Sh.)", "____dan (F.I.Sh.)".
    found = ariza(tmp_path, 'uz', {}, 'blank.pdf')
    head = ' '.join(found[:found.index('ARIZA')]).split()
    assert 'ga' in head and 'dan' in head
    # A named head's last line carries the dative itself: the blank row above it takes no second ending.
    found = ariza(tmp_path, 'uz', {'addressee_person': 'B. A. Namunovga'}, 'named.pdf')
    head = found[:found.index('ARIZA')]
    assert 'B. A. Namunovga' in head
    head = ' '.join(head).split()
    assert 'ga' not in head and 'dan' in head
    for locale in ('ru', 'en'):
        head = ' '.join(ariza(tmp_path, locale, {}, f'{locale}.pdf')[:4]).split()
        assert 'ga' not in head and 'dan' not in head


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
def test_the_smoke_makes_every_letter_in_its_own_template(settings, monkeypatch, capsys, tmp_path):
    # The real-provider gate runs this script on the server; here the provider is the samples.
    from operations.integrations import save_config
    save_config('ai', {'mode': 'openai', 'model': 'test-model', 'api_key': 'sk-offline-test'})
    model = Model(monkeypatch)
    monkeypatch.setattr(sys, 'argv', [str(SMOKE), '--category', 'pdf.xat.', '--locale', 'en', '--out',
                                      str(tmp_path)])
    with pytest.raises(SystemExit) as ended:
        runpy.run_path(str(SMOKE), run_name='__main__')
    out = capsys.readouterr().out
    assert ended.value.code == 0, out
    assert 'FAIL' not in out and 'Every category checked was made.' in out
    assert [call[0] for call in model.calls] == [entry.id for entry in LETTERS]
    for entry_id, template_id, length in model.calls:
        assert f'{entry_id} template' in out and template_id in out
    assert len(list(tmp_path.glob('*.pdf'))) == len(LETTERS)
