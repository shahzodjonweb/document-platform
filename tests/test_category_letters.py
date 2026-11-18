"""The letters and official papers (pdf.xat): what their entries promise the paper engine and the model.

Six entries, each a draft on its own template until N2 signs it: their written
parts are grounded, their length is a ceiling, a letter is dated by the clock
and an official paper never is, the recommendation picks its English letter by
language, and each block fits the budget with no rewrite rule left.
"""
import re

import pytest

from apps.studio.categories import asking, catalogue, skeleton
from apps.studio.categories.catalogue import BLOCK_BUDGET, block_size, check

NONE = frozenset()
TEMPLATES = {
    'pdf.xat.motivatsion': ['letter_motivatsion', 'letter_statement'], 'pdf.xat.ishga_kirish': ['letter_cover'],
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
    # Ready since N2c (tests/test_category_letter_readiness.py); the test keeps its name, which the append-only
    # tests/core_tests.txt lists.
    assert (paper.service, paper.raw['parent'], paper.status) == ('pdf', 'pdf.xat', 'ready')
    assert list(paper.templates) == TEMPLATES[entry_id]
    assert all(entry_id in catalogue.template(name)['entries'] for name in paper.templates)
    assert block_size(paper) <= (BLOCK_BUDGET, False)
    assert not [rule for rule in paper.raw['rules'] if rule['to'] == 'rewrite']
    # What is left before ready is at most the paper engine's blocks and the people's gates, nothing of the entry's
    # own: the list empties as R1 and R4 register the blocks, and no problem of the entry or its templates is an error.
    found = check(entry_id)
    assert not [problem for problem in found if not problem.warning]
    assert all(problem.text.startswith('blocks not yet registered') for problem in found if problem.subject == entry_id)


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
    # A bare "ariza kerak" names no request: the model returns ____ and the form gets ruled lines for it by hand,
    # never an ARIZA with nothing under the title. if_needed, not blank: a blank field would draw them always.
    ariza = entry('pdf.xat.ariza')
    assert ariza.field('reason')['missing'] == ariza.field('request')['missing'] == 'if_needed'
    flow = {place.get('part'): place.get('when') for place in catalogue.template('official_ariza')['flow']
            if place['block'] == 'ruled_blank'}
    assert flow == {'reason_blank': 'blank:reason', 'request_blank': 'blank:request'}


def test_the_explanatory_notes_case_corpus_covers_english_too():
    corpus = next(gate for gate in entry('pdf.xat.tushuntirish').raw['gates'] if gate.startswith('Case corpus'))
    assert ' uz: ' in corpus and ' ru: ' in corpus and ' en (' in corpus
    assert '"To: Rustam Aliyev / Director, Misol Savdo"' in corpus and '"From: Nigora Salimova / Accountant"' in corpus
    # Rahimova is the stage-2 prompt tests' marker of customer text leaking into the instructions (P2).
    assert 'Rahimov' not in corpus and 'Рахимов' not in corpus


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
    assert asking.wanted(cover, 'Misol Soft kompaniyasiga dasturchi lavozimiga xat', has_files=False)
    assert asking.wanted(motivation, 'Namuna universitetiga magistraturaga xat', has_files=False)


def places():
    """(entry id, template name, placement) for every placement of the six letters' templates."""
    return [(entry_id, name, place) for entry_id, names in TEMPLATES.items() for name in names
            for place in catalogue.template(name)['flow']]


def test_a_flag_holds_only_when_it_is_true():
    # The model may return a flag as 'false'; a bare fact:seal would read that as given and print M.O‘. unasked.
    for entry_id, name, place in places():
        kind, _, rest = (place.get('when') or '').partition(':')
        field = entry(entry_id).field(rest.partition('=')[0]) if kind in ('fact', 'nofact') else None
        if field and field['kind'] == 'flag':
            assert rest.endswith('=true'), (name, place['when'])


@pytest.mark.parametrize('entry_id', sorted(TEMPLATES))
def test_a_field_the_question_asks_for_is_named_by_it(entry_id):
    # `ask` means named by ask.fields (the schema); a field nobody asks for draws its blank or nothing.
    paper = entry(entry_id)
    asked = set((paper.raw['ask'] or {}).get('fields', ()))
    assert {field['id'] for field in paper.fields if field['missing'] == 'ask'} <= asked


@pytest.mark.parametrize('entry_id', sorted(TEMPLATES))
def test_an_uzbek_or_english_paper_writes_a_cyrillic_name_in_latin(entry_id):
    rules = ' '.join(rule['text'] for rule in entry(entry_id).raw['rules'] if rule['to'] == 'model')
    assert re.search(r'Cyrillic(?: name)? is transliterated (?:into Latin )?in an Uzbek or English', rules)
    assert 'except a name' not in rules and 'script, order' not in rules


def test_the_statement_head_is_its_own_template_without_the_letters_apparatus():
    letter, statement = catalogue.template('letter_motivatsion'), catalogue.template('letter_statement')
    assert statement['pick'] == 'cue:statement'
    assert not {place.get('part') for place in statement['flow']} & {'addressee_row', 'salutation', 'close', 'enclosures'}
    assert not [place for place in letter['flow'] if 'statement' in (place.get('when') or '')]
    motivation = entry('pdf.xat.motivatsion')
    assert 'statement' in skeleton.cues(motivation, 'Personal statement for a master’s programme', has_files=False)


def test_a_motivation_letter_is_two_pages_only_for_a_real_degree_or_grant_word():
    letter = entry('pdf.xat.motivatsion')
    for text in ('I mastered Python and was granted a prize at the city olympiad', 'Grantlash tizimi haqida xat'):
        assert 'scholarship' not in skeleton.cues(letter, text, has_files=False), text
    for text in ('A letter for the Master’s in Economics', 'Masters programme in Finance', 'I apply for a grant',
                 'Grantga motivatsion xat', 'Письмо на грант'):
        assert 'scholarship' in skeleton.cues(letter, text, has_files=False), text


def test_a_strong_verdict_without_a_target_has_its_own_words():
    for name in TEMPLATES['pdf.xat.tavsiya']:
        template = catalogue.template(name)
        strong = next(place for place in template['flow'] if place.get('when') == 'fact:strength=strong')
        plain = template['labels'][strong['params']['without']['target']]
        assert all('{target}' not in text and '{candidate_short}' in text for text in plain.values())


def test_english_names_the_person_first_in_the_head():
    flow = {place.get('part'): place for place in catalogue.template('official_tushuntirish')['flow']}
    assert flow['addressee']['params']['order']['en'][0] == 'addressee_name'
    assert flow['writer']['params']['order']['en'][0] == 'writer_name'
    applicant = next(place for place in catalogue.template('official_ariza')['flow'] if place.get('part') == 'applicant')
    assert applicant['params']['order']['en'][0] == 'applicant_name'
    assert sorted(applicant['params']['order']['en']) == sorted(applicant['fields'])


LOCALE_KEYS = ('uz', 'ru', 'en')


def label_names(params):
    """(how it is named, label key, the locales it is drawn in) for each template label a placement's params name.

    A label named by a string is drawn in every language; a {locale: key} map is drawn only in the languages it
    names, which is how a placement gives a word to one language and none to the others.
    """
    for key, value in (params or {}).items():
        if key == 'label':
            values = [value]
        elif key in ('labels', 'captions') and isinstance(value, dict):
            values = list(value.values())
        else:
            continue
        for item in values:
            if isinstance(item, str):
                yield 'string', item, LOCALE_KEYS
            elif isinstance(item, dict):
                yield from (('map', name, (locale,)) for locale, name in item.items())


def test_a_label_drawn_in_a_language_has_words_in_it():
    # An empty label is never relied on to draw nothing: the paper engine reads '' as missing and takes the English
    # one, so a Russian note would print "To:". A word one language has and the others do not is a per-locale map.
    for entry_id, name, place in places():
        labels = catalogue.template(name)['labels']
        for kind, key, locales in label_names(place.get('params')):
            assert set(locales) <= set(LOCALE_KEYS), (name, key, locales)
            assert all(labels[key][locale] for locale in locales), (name, kind, key, locales)


def test_the_explanatory_notes_head_has_a_label_in_english_only():
    flow = {place.get('part'): place for place in catalogue.template('official_tushuntirish')['flow']}
    for part, key in (('addressee', 'to'), ('writer', 'from')):
        drawn = {locale for _, name, locales in label_names(flow[part]['params']) for locale in locales if name == key}
        assert drawn == {'en'}, part
    for name in ('official_tavsifnoma', 'tavsiya_rasmiy'):
        title = next(place for place in catalogue.template(name)['flow'] if place['block'] == 'doc_title')
        assert title['params']['labels']['name_after'] == {'uz': 'about'}, name
    lead = next(place for place in catalogue.template('official_tavsifnoma')['flow'] if place['block'] == 'doc_title')
    assert lead['params']['labels']['name_before'] == {'ru': 'subject_lead'}


def test_a_line_drawn_from_labels_alone_prints_no_inherited_fields():
    # A placement without fields draws its part's fields (the paper engine's Place), and the plain fallback prints
    # each: a closing line under sign_off would repeat the signer's name and phone, a seal line "M.O‘. false".
    # Such a line names no part; a ruled blank keeps the one field it is the blank for.
    for entry_id, name, place in places():
        if place.get('fields') or not place.get('part'):
            continue
        inherited = entry(entry_id).part(place['part']).get('fields') or []
        if place['block'] == 'ruled_blank':
            assert len(inherited) == 1 and place['when'] == f'blank:{inherited[0]}', (name, place['part'])
        else:
            assert not inherited, (name, place['block'], place['part'], inherited)


# What one page of each paper holds, in words (its own rules): the parts' most at the default length stay within it,
# so a rich message never fills a one-page quote onto two pages.
ONE_PAGE_WORDS = {'pdf.xat.ariza': 150, 'pdf.xat.ishga_kirish': 208, 'pdf.xat.motivatsion': 310,
                  'pdf.xat.tavsifnoma': 170, 'pdf.xat.tavsiya': 200, 'pdf.xat.tushuntirish': 300}


@pytest.mark.parametrize('entry_id', sorted(TEMPLATES))
def test_the_parts_most_words_fit_the_papers_first_page(entry_id):
    paper = entry(entry_id)
    most = sum(skeleton.words(paper, use, 1, NONE)[1] for use in skeleton.parts(paper, 1, NONE)
               if use.section_id and use.part['kind'] != 'list')
    assert most <= ONE_PAGE_WORDS[entry_id], most
