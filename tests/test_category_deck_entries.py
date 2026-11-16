"""What the ten deck entries tell the model, and the cues that pick a deck's path.

A deck has no derive step (derive.py is for papers), and the facts guard
blanks any figure on a slide that the brief does not hold. So a slot text
that asks the model to work out a change or a completion percentage gives a
customer who wrote plan and actual figures blanks on the main slides of the
report. These tests read what reaches the model, the category block and each
slot's holds (prompting.block and prompting.rows), and fail on such an
instruction, on a percent example no brief of the entry holds, and on the
research notes that cost tokens on every call and name things that do not
exist. People and organisations in the messages are invented.
"""
import re

from apps.studio.categories import catalogue, prompting, sample, skeleton
from apps.studio.categories.catalogue import LOCALES

DECKS = ('slides.mavzu', 'slides.himoya', 'slides.dars', 'slides.tadbir.tarbiyaviy_soat', 'slides.tadbir.bayram',
         'slides.tadbir.ota_onalar', 'slides.tadbir.pedkengash', 'slides.pitch', 'slides.hisobot', 'slides.kompaniya')
PERCENT = re.compile(r'\d+(?:[.,]\d+)?\s?%')
# Instructions to work a figure out, as the reviewed hisobot slots had them: a label of "name · percent", a
# completion stated as a percentage with its verb, and the research's derivation grammar by name.
DERIVING = re.compile(r'derived_figures|\bspec\.|\w · [↓↑]?\s?\d+(?:[.,]\d+)?\s?%|\d+(?:[.,]\d+)?\s?% bajarildi'
                      r'|percentage follows|draws the percentage|reja \d[\d ]*\w*: \d', re.IGNORECASE)
# Research notes: mock-ups, measurements, scripts, design documents and their section names, which the model
# cannot see and which say nothing about what to write.
NOTES = re.compile(r'\bmock\b|\.png\b|\.py\b|\bwork/|design document|\bmeasured\b|number_scaling|slot_item_rules'
                   r'|launch contract|not mocked|rule is removed|validator|shared with slides\.|\bVEON\b'
                   r'|<[^>]*sarlavha', re.IGNORECASE)


def model_texts(entry):
    """Every text of `entry` the model can be sent: the category block, and each slide slot's holds and notes."""
    texts = prompting.block(entry).split('\n')
    for part in entry.raw['parts']:
        if part['kind'] == 'slide' and not part.get('retired'):
            texts += [part.get('write') or '', part.get('notes') or '']
    return [text for text in texts if text]


def rows_sent(entry):
    """The holds of every row prompting.rows makes for the entry's samples at their longest, in each language."""
    for case in sample.CASES:
        given = sample.load(entry.id, case)
        for locale in LOCALES:
            data, content = sample.draft(entry, given, locale, entry.length['max'])
            data['content'] = content
            yield from (row['holds'] for row in prompting.rows(data, content['sections']))


def test_no_text_the_model_reads_asks_it_to_work_a_figure_out():
    for entry_id in DECKS:
        entry = catalogue.get(entry_id)
        for text in [*model_texts(entry), *rows_sent(entry)]:
            assert not DERIVING.search(text), (entry_id, DERIVING.search(text).group(0), text)


def test_a_percent_example_the_model_reads_is_one_a_brief_of_the_entry_holds():
    # An example is copied: a percentage no customer of the entry wrote teaches the model to make one, which the
    # facts guard then blanks.
    for entry_id in DECKS:
        entry = catalogue.get(entry_id)
        briefs = ' '.join(example[locale] for example in entry.raw['bot']['examples'] for locale in LOCALES)
        written = {figure.replace(' ', '') for figure in PERCENT.findall(briefs)}
        for text in model_texts(entry):
            for figure in PERCENT.findall(text):
                assert figure.replace(' ', '') in written, (entry_id, figure, text)


def test_no_research_note_reaches_the_model():
    for entry_id in DECKS:
        entry = catalogue.get(entry_id)
        for text in [*model_texts(entry), *rows_sent(entry)]:
            assert not NOTES.search(text), (entry_id, NOTES.search(text).group(0), text)


def test_a_report_on_plan_and_actual_is_told_to_show_the_figures_as_written():
    entry = catalogue.get('slides.hisobot')
    for slot in ('natijalar', 'reja_natija'):
        write = entry.part(slot)['write']
        assert 'only when the customer wrote it' in write and '%' not in write, slot


def held(entry_id, message):
    """The cues of a message as a draft's brief reads it (skeleton.brief ends the message with a new line)."""
    return skeleton.cues(catalogue.get(entry_id), skeleton.brief({'prompt': message}), has_files=False)


def test_a_company_profile_keeps_its_path_for_values_and_a_training_programme():
    for message in ('Namuna Ta’lim MChJ haqida taqdimot: ta’lim dasturi, qadriyatlarimiz, mijozlarimiz.',
                    'Презентация компании «Намуна»: наши ценности, программа обучения, клиенты.',
                    'A company presentation of Namuna Training: our values, the training programme, our approach.'):
        assert held('slides.kompaniya', message) == frozenset(), message


def test_a_product_deck_and_prices_are_still_found():
    for message in ('Namuna mobil dasturi taqdimoti, narxlari bilan.',
                    'Презентация нашего программного обеспечения, цены по тарифам.',
                    'A deck for our app, with pricing.',
                    'Prices are in the attachment; the deck is about our app'):
        assert held('slides.kompaniya', message) == {'mahsulot', 'narx'}, message
