"""The ten deck categories are ready to be ticked (N1): what a tick rests on, held in code.

A ready entry is only tickable; the owner's tick on /ops/categories is what
puts it in front of customers, and the switch page shows each entry's gates
beside its tick. So a ready deck must pass every readiness check of the
catalogue as an error, say on that page which checks a person still makes
(a native reader, one real-provider run), and draw its own samples to exactly
the count asked, as the sheets the owner compares with the mock-ups were
drawn. The copy corrections of the native read are pinned where a later
edit could quietly undo them. Every person and organisation in the samples
is invented.
"""
import re

import pytest

from apps.studio.categories import catalogue, sample

DECKS = [entry for entry in catalogue.for_feature('ai.pptx')]
# What the table layouts read as a row's cells, in order (variants/table_1.py, layouts.py 'table').
CELLS = ('label', 'text', 'value')


def test_every_deck_is_ready_and_meets_its_gates_as_errors():
    assert [entry.id for entry in DECKS] == [
        'slides.mavzu', 'slides.himoya', 'slides.dars', 'slides.tadbir.tarbiyaviy_soat', 'slides.tadbir.bayram',
        'slides.tadbir.ota_onalar', 'slides.tadbir.pedkengash', 'slides.pitch', 'slides.hisobot', 'slides.kompaniya']
    assert all(entry.status == catalogue.READY for entry in DECKS)
    assert [str(problem) for problem in catalogue.check('slides.')] == []


@pytest.mark.parametrize('entry', DECKS, ids=lambda entry: entry.id)
def test_the_switch_page_says_what_a_person_still_checks_before_the_tick(entry):
    gates = entry.raw['gates']
    assert any(re.search(r'native|mother-tongue', gate) for gate in gates), 'a native reader'
    assert any(f'ai_smoke.py --category {entry.id} ' in gate for gate in gates), 'one real-provider run'


@pytest.mark.parametrize('entry', DECKS, ids=lambda entry: entry.id)
def test_the_sample_tool_draws_both_cases_to_the_count_asked(entry, tmp_path):
    # The sheets the owner looks at: the default count in Uzbek with figures and in Russian from the topic only.
    length = entry.length['default']
    for case, locale in (('figures', 'uz'), ('topic_only', 'ru')):
        made = sample.run(entry, sample.load(entry.id, case), case, locale, length, tmp_path, width=160)
        assert made['slides'] == length and made['codes'] == [] and made['shortened'] == [], (case, locale, made)
        assert (tmp_path / f"{made['stem']}.pptx").is_file() and (tmp_path / f"{made['stem']}.png").is_file()


def test_a_sample_table_fills_every_cell_its_columns_name():
    # A two-column table reads label and text; a figure left in value was drawn as an empty column on the sheet.
    for entry in DECKS:
        for case in sample.CASES:
            for part_id, instances in sample.load(entry.id, case)['slots'].items():
                for instance in instances:
                    for locale, section in instance.items():
                        if section.get('layout') != 'table':
                            continue
                        width = len(section.get('columns') or ())
                        for item in section.get('items') or ():
                            empty = [key for key in CELLS[:width] if not str(item.get(key) or '').strip()]
                            assert empty == [], (entry.id, case, part_id, locale, item)


def customer_copy(raw):
    """Every text a customer reads of an entry, (where, locale, text): label, prompts, examples, notices, ask."""
    bot = raw['bot']
    found = [('labels', raw['labels']), ('bot.prompt', bot['prompt'])]
    found += [(f'bot.examples.{n}', text) for n, text in enumerate(bot['examples'])]
    found += [(f'bot.pool.{n}', text) for n, text in enumerate(bot.get('pool', ()))]
    found += [(f'bot.notices.{name}', text) for name, text in bot['notices'].items()]
    found += [(f'ask.{name}', text) for name, text in (raw['ask'] or {}).items() if isinstance(text, dict)]
    if raw.get('topic_prompt'):
        found.append(('topic_prompt', raw['topic_prompt']))
    found += [(f"parts.{part['id']}", part['heading']) for part in raw['parts'] if isinstance(part.get('heading'), dict)]
    return [(where, locale, text[locale]) for where, text in found for locale in catalogue.LOCALES]


def test_no_customer_text_breaks_off_mid_sentence():
    # An example cut where a talk length was taken out ended in a comma, in every language.
    for entry in DECKS:
        for where, locale, text in customer_copy(entry.raw):
            assert not text.rstrip().endswith((',', ';', ' —', ' -')), (entry.id, where, locale, text)


def test_uzbek_copy_writes_obyekt_as_the_latin_orthography_does():
    # The native read settled one spelling: the field labels already wrote obyekt, the headings ob’ekt.
    for entry in DECKS:
        for where, locale, text in customer_copy(entry.raw):
            assert not re.search(r'ob[’\'‘]ekt', text, re.IGNORECASE), (entry.id, where, locale, text)
