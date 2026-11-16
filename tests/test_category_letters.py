"""The letters and official papers (pdf.xat): what their entries promise the paper engine and the model.

Six entries, each a draft on its own template until N2 signs it: their written
parts are grounded, their length is a ceiling, a letter is dated by the clock
and an official paper never is, the recommendation picks its English letter by
language, and each block fits the budget with no rewrite rule left.
"""
import pytest

from apps.studio.categories import asking, catalogue, skeleton
from apps.studio.categories.catalogue import BLOCK_BUDGET, block_size, check

NONE = frozenset()
TEMPLATES = {
    'pdf.xat.motivatsion': ['letter_motivatsion'], 'pdf.xat.ishga_kirish': ['letter_cover'],
    'pdf.xat.ariza': ['official_ariza'], 'pdf.xat.tavsifnoma': ['official_tavsifnoma'],
    'pdf.xat.tavsiya': ['tavsiya_rasmiy', 'letter_tavsiya'], 'pdf.xat.tushuntirish': ['official_tushuntirish'],
}
# A letter goes out the day it is made; an official paper is dated by hand when it is signed.
CLOCKED = {'pdf.xat.ishga_kirish': {'date_written'}, 'pdf.xat.motivatsion': {'letter_date'},
           'pdf.xat.tavsiya': {'letter_date'}}
ONE_PAGE = ('pdf.xat.ariza', 'pdf.xat.ishga_kirish', 'pdf.xat.tushuntirish')


def entry(entry_id):
    return catalogue.get(entry_id)


@pytest.mark.parametrize('entry_id', sorted(TEMPLATES))
def test_each_letter_is_a_draft_on_its_own_template_within_its_budget(entry_id):
    paper = entry(entry_id)
    assert (paper.service, paper.raw['parent'], paper.status) == ('pdf', 'pdf.xat', 'draft')
    assert list(paper.templates) == TEMPLATES[entry_id]
    assert all(entry_id in catalogue.template(name)['entries'] for name in paper.templates)
    assert block_size(paper) <= (BLOCK_BUDGET, False)
    assert not [rule for rule in paper.raw['rules'] if rule['to'] == 'rewrite']
    # What is left before ready is the paper engine's blocks and the people's gates, nothing of the entry's own.
    found = [problem for problem in check(entry_id) if problem.subject == entry_id]
    assert [problem.text.split(':')[0] for problem in found] == [
        'blocks not yet registered in apps/studio/paper/registry.py']


def test_the_recommendation_is_the_official_form_and_the_personal_letter_in_english():
    assert not catalogue.template('tavsiya_rasmiy').get('pick')
    assert catalogue.template('letter_tavsiya')['pick'] == 'locale:en'


@pytest.mark.parametrize('entry_id', sorted(TEMPLATES))
def test_every_written_part_is_grounded_and_the_length_is_a_ceiling(entry_id):
    paper = entry(entry_id)
    written = [part for part in paper.parts if part['kind'] in skeleton.WRITTEN]
    assert written and all(part.get('grounded') for part in written)
    assert paper.length['target'] == 'ceiling' and not paper.raw['fill'] and paper.raw['title'] == 'label'
    assert not paper.topic
    if entry_id in ONE_PAGE:
        assert (paper.length['mode'], paper.length['default']) == ('fixed', 1)
        assert skeleton.length(paper, asked=5, cues=NONE) == 1


@pytest.mark.parametrize('entry_id', sorted(TEMPLATES))
def test_a_letter_is_dated_by_the_clock_and_an_official_paper_never(entry_id):
    clocked = {field['id'] for field in entry(entry_id).fields if field.get('clock')}
    assert clocked == CLOCKED.get(entry_id, set())
    assert all(entry(entry_id).field(name)['clock'] == 'date' for name in clocked)


def test_a_motivation_letter_is_two_pages_for_a_scholarship_and_one_otherwise():
    letter = entry('pdf.xat.motivatsion')
    cues = skeleton.cues(letter, 'Magistraturaga motivatsion xat kerak', has_files=False)
    assert skeleton.length(letter, cues=cues) == 2
    assert skeleton.length(letter, cues=skeleton.cues(letter, 'Exchange semester letter', has_files=False)) == 1
    assert skeleton.length(letter, asked=5, cues=NONE) == 3


def test_a_blank_form_is_drawn_only_when_the_model_asks_for_it():
    note = entry('pdf.xat.tushuntirish')
    assert note.field('what_happened')['missing'] == note.field('reason')['missing'] == 'if_needed'
    flow = {place.get('part'): place.get('when') for place in catalogue.template('official_tushuntirish')['flow']
            if place['block'] == 'ruled_blank'}
    assert flow == {'reason_blank': 'blank:reason', 'blank_body': 'blank:what_happened'}
    assert entry('pdf.xat.ariza').field('reason')['missing'] == 'if_needed'


def test_the_explanatory_notes_case_corpus_covers_english_too():
    corpus = next(gate for gate in entry('pdf.xat.tushuntirish').raw['gates'] if gate.startswith('Case corpus'))
    assert ' uz: ' in corpus and ' ru: ' in corpus and ' en (' in corpus
    assert '"To: Rustam Aliyev / Director, Bahor Foods"' in corpus and '"From: Nigora Rahimova / Accountant"' in corpus


def test_the_review_question_is_offered_for_a_thin_message_only():
    recommendation = entry('pdf.xat.tavsiya')
    cover, motivation = entry('pdf.xat.ishga_kirish'), entry('pdf.xat.motivatsion')
    rich, thin = recommendation.raw['bot']['examples'][:2]
    for locale in ('uz', 'ru', 'en'):
        assert not asking.wanted(recommendation, rich[locale], has_files=False)
        assert asking.wanted(recommendation, thin[locale], has_files=False)
        assert not asking.wanted(recommendation, thin[locale], has_files=True), 'an attached CV may hold them'
        for letter in (cover, motivation):
            # Every example gives its reason, so customers learn to; a message without one is asked for it.
            assert not any(asking.wanted(letter, example[locale], has_files=False)
                           for example in letter.raw['bot']['examples'])
    assert asking.wanted(cover, 'Zarnigor Soft kompaniyasiga dasturchi lavozimiga xat', has_files=False)
    assert asking.wanted(motivation, 'Namuna universitetiga magistraturaga xat', has_files=False)
