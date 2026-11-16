"""The seven business papers of AI PDF (pdf.biz) as catalogue entries, before their templates are built.

Each is a draft converted from its research spec. What these tests hold is
what the converted data promises the later packages and the customer:

- the fact-led papers are ceilings (nothing pads them) and the business plan
  a count with nothing a top-up may extend, because every written part of a
  business paper is grounded;
- a table's computed cells and totals name columns that exist, so derive.py
  (R5a) fills what the model leaves empty from the customer's own numbers;
- the minutes' agenda items are one model-sized group, so a meeting of three
  items fills three and the rest are dropped;
- what this round does not build (repayment schedules, the formal forms,
  acknowledgement sheets) is in `later`, and no bot copy promises it;
- nothing the model reads is a research note or a law it would have to cite,
  since the facts guard strips a sentence naming a code the customer did not;
- a draft of every entry is made, seeded and quoted by the domain as it is.

People and organisations in the messages are invented.
"""
import copy
import itertools
import re

import pytest

from apps.studio import categories
from apps.studio.categories import catalogue, prompting, skeleton
from apps.studio.categories.catalogue import PAPER_BOUNDS, SOURCES_CUE
from apps.studio.domain import create_draft, generation_quote, unpack, validate_content
from operations.categories_settings import save as save_switch
from tests.test_operations import staff_client
from tests.test_platform import account
from tests.test_studio import paid

BUSINESS = ('pdf.biz.biznes_reja', 'pdf.biz.tijorat_taklifi', 'pdf.biz.hisobot', 'pdf.biz.yoriqnoma',
            'pdf.biz.lavozim_yoriqnomasi', 'pdf.biz.bayonnoma', 'pdf.biz.marketing_reja')
CEILINGS = set(BUSINESS) - {'pdf.biz.biznes_reja'}
# Research notes and renderer plumbing the model cannot use: mock-ups, scripts, measurements, the research's
# document numbers and waves, token syntax for figures code fills.
NOTES = re.compile(r'\bmock\b|\.png\b|\.py\b|\bwork/|\bmeasured\b|\bdocs? \d|\bsources/|\bwave \d|\{\{|\bspec\b'
                   r'|open question|\brenderer\b', re.IGNORECASE)
# A legal source the guard removes whole unless the customer gave it: a paper told to cite one comes back without it.
CITED = re.compile(r'kodeks|кодекс|labou?r code|konstitutsiya|конституци|respublikasi qonun', re.IGNORECASE)


def entry(entry_id):
    return catalogue.get(entry_id)


def model_texts(item):
    """What the model can be sent of an entry: its block and the write of every written part (a parts row)."""
    texts = prompting.block(item).split('\n')
    texts += [part['write'] for part in item.parts if part['kind'] != 'fixed' and not part.get('retired')]
    return [text for text in texts if text]


def test_the_seven_business_papers_are_drafts_under_their_group_in_the_owners_order():
    assert [item.id for item in catalogue.for_feature('ai.pdf_topic') if item.id.startswith('pdf.biz.')] == \
        list(BUSINESS)
    for entry_id in BUSINESS:
        item = entry(entry_id)
        assert (item.service, item.status, item.raw['parent'], item.topic) == ('pdf', 'draft', 'pdf.biz', False)
        assert len(item.templates) == 1 and catalogue.template(item.templates[0])['entries'] == [entry_id]
    assert entry('pdf.biz.yoriqnoma').name('uz') == 'Xodimlar uchun yo‘riqnoma'


def test_the_fact_led_papers_are_ceilings_and_the_plan_a_count_with_nothing_to_top_up():
    for entry_id in BUSINESS:
        length = entry(entry_id).length
        assert length['mode'] == 'count' and length['min'] <= length['default'] <= length['max'] <= 35
        assert length['target'] == ('ceiling' if entry_id in CEILINGS else 'count'), entry_id
        assert entry(entry_id).raw['fill'] is False
    # Top-up extends only ungrounded elastic prose, and a business paper has none, so the plan's fill is off.
    plan = entry('pdf.biz.biznes_reja')
    assert not [part['id'] for part in plan.parts if part['kind'] in skeleton.WRITTEN and not part.get('grounded')]


def test_every_written_part_of_a_business_paper_is_grounded():
    for entry_id in BUSINESS:
        loose = [part['id'] for part in entry(entry_id).parts
                 if part['kind'] in skeleton.WRITTEN and not part.get('grounded')]
        assert not loose, (entry_id, loose)


def test_computed_cells_and_totals_name_columns_of_their_own_table():
    tables = 0
    for entry_id in BUSINESS:
        for part in entry(entry_id).parts:
            if part['kind'] != 'table':
                assert 'computed' not in part and 'total' not in part, (entry_id, part['id'])
                continue
            tables += 1
            width = len(part['columns'])
            for rule in part.get('computed', ()):
                assert 0 < rule['column'] < width and rule['of'], (entry_id, part['id'], rule)
                assert all(0 < column < width and column != rule['column'] for column in rule['of']), (entry_id, rule)
                # A computed cell sits between the first and the last cell, or is the last: never the row's label.
            for column in part.get('total', ()):
                assert 0 < column < width, (entry_id, part['id'], column)
    assert tables >= 15
    prices = entry('pdf.biz.tijorat_taklifi').part('prices')
    assert prices['computed'] == [{'column': 4, 'op': 'product', 'of': [2, 3]}] and prices['total'] == [4]
    indicators = entry('pdf.biz.hisobot').part('indicators')
    assert [rule['op'] for rule in indicators['computed']] == ['difference', 'percent']
    assert entry('pdf.biz.marketing_reja').part('budget')['computed'] == [{'column': 2, 'op': 'share', 'of': [1]}]


def test_the_minutes_repeat_report_discussion_decisions_and_vote_once_per_agenda_item():
    minutes = entry('pdf.biz.bayonnoma')
    assert minutes.raw['groups'] == {'items': {'min': 1, 'max': 8, 'sized': 'model'}}
    grouped = [part['id'] for part in minutes.parts if part.get('group') == 'items']
    assert grouped == ['item_report', 'item_speakers', 'item_decisions', 'item_vote']
    sections = [section['id'] for section in skeleton.seed(minutes, 2, frozenset())]
    assert sections[:2] == ['facts', 'agenda'] and sections[-1] == 'attachments'
    assert sections[2:6] == grouped and sections[-5:-1] == [f'{part}_8' for part in grouped]
    # Each item's parts keep their own word maximums: an eighth of a two-page share would be no report at all.
    report = next(use for use in skeleton.parts(minutes, 2, frozenset()) if use.section_id == 'item_report_3')
    assert skeleton.words(minutes, report, 2, frozenset()) == (0, 150)
    assert minutes.part('item_decisions_5')['id'] == 'item_decisions'


def test_every_business_paper_seeds_within_the_paper_bounds_at_every_length_and_cue():
    for entry_id in BUSINESS:
        item = entry(entry_id)
        names = sorted(set(item.raw.get('cues') or {}) | {SOURCES_CUE})
        for size in range(len(names) + 1):
            for chosen in itertools.combinations(names, size):
                held = skeleton.effective(item, chosen)
                for length in range(item.length['min'], item.length['max'] + 1):
                    sections = skeleton.seed(item, length, held)
                    assert 1 < len(sections) <= PAPER_BOUNDS.sections, (entry_id, length, sorted(held))


def test_a_staff_instruction_takes_its_chapters_from_its_kind():
    instruction = entry('pdf.biz.yoriqnoma')

    def chapters(message):
        held = skeleton.cues(instruction, message, has_files=False)
        return [use.section_id for use in skeleton.parts(instruction, 3, held) if use.section_id]
    work = chapters('Bahor kafesining yangi ofitsiantlari uchun ish yo‘riqnomasi kerak.')
    assert work == ['general', 'before_work', 'during_work', 'emergency', 'after_work', 'final']
    # A safety rule is a safety instruction, never rules of conduct; its headings are the template's.
    assert chapters('Omborda mehnat muhofazasi va xavfsizlik qoidalari bo‘yicha yo‘riqnoma.') == work
    rules = chapters('Do‘kon xodimlari uchun ichki tartib qoidalari kerak.')
    assert rules == ['general', 'rules_chapter', *[f'rules_chapter_{n}' for n in range(2, 7)], 'final']


def test_what_this_round_does_not_build_is_deferred_with_the_words_bot_copy_must_not_hold():
    def words(entry_id):
        return {word for later in entry(entry_id).raw['later'] for word in later.get('words', ())}
    assert {'qaytarish jadvali', 'repayment schedule', 'annuitet'} <= words('pdf.biz.biznes_reja')
    for entry_id in ('pdf.biz.tijorat_taklifi', 'pdf.biz.hisobot', 'pdf.biz.yoriqnoma'):
        assert 'rasmiy' in words(entry_id), entry_id
    for entry_id in ('pdf.biz.yoriqnoma', 'pdf.biz.lavozim_yoriqnomasi'):
        assert {'лист ознакомления', 'acknowledgement sheet'} <= words(entry_id), entry_id
    for entry_id in BUSINESS:
        bot = entry(entry_id).raw['bot']
        copy_ = ' '.join(text for item in [bot['prompt'], *bot['examples'], *bot['notices'].values()]
                         for text in item.values()).lower()
        assert not [word for word in words(entry_id) if word.lower() in copy_], entry_id


def test_no_research_note_or_law_to_cite_reaches_the_model():
    for entry_id in BUSINESS:
        for text in model_texts(entry(entry_id)):
            assert not NOTES.search(text), (entry_id, NOTES.search(text).group(0), text[:120])
            assert not CITED.search(text), (entry_id, CITED.search(text).group(0), text[:120])


def test_the_ceiling_papers_say_when_they_came_out_shorter_and_every_paper_says_what_to_check():
    for entry_id in BUSINESS:
        notices = entry(entry_id).raw['bot']['notices']
        assert {'finished', 'blanks'} <= set(notices), entry_id
        assert ('shorter' in notices) == (entry_id in CEILINGS), entry_id


# ---------------------------------------------------------------- drafts the domain makes


@pytest.fixture
def ready(monkeypatch):
    """The catalogue with the business papers marked ready, as N2 will mark them."""
    entries, templates, index = copy.deepcopy(catalogue.read())
    for name in BUSINESS:
        entries[name]['status'] = 'ready'
    made = catalogue.build(entries, templates, index)
    monkeypatch.setattr(catalogue, '_catalogue', lambda: made)
    _, user = staff_client('Operations')
    save_switch({'on': 'true', 'live': list(BUSINESS)}, user)
    return made


@pytest.fixture
def customer(settings):
    from operations.integrations import save_config
    settings.DEBUG = True
    save_config('ai', {'mode': 'openai', 'model': 'gpt-5.6-luna', 'api_key': 'sk-offline-test-only'})
    return paid(settings, account(77821))


@pytest.mark.django_db
@pytest.mark.parametrize('entry_id', BUSINESS)
def test_each_example_makes_a_draft_of_its_skeleton_held_to_its_pages_and_quoted(customer, ready, entry_id):
    item = categories.get(entry_id)
    for number, example in enumerate(item.raw['bot']['examples']):
        for locale in ('uz', 'ru'):
            draft = create_draft(customer, {'feature_id': item.feature_id, 'prompt': example[locale],
                                            'options': {'category': entry_id}})
            data = unpack(draft.encrypted_data)
            length = data['options']['length']
            assert item.length['min'] <= length <= item.length['max'], (entry_id, number, locale)
            held = skeleton.cues_of(data)
            written = [use.section_id for use in skeleton.parts(item, length, held) if use.section_id]
            assert [section['id'] for section in data['content']['sections']] == ['facts', *written]
            assert validate_content(customer, data['content'], 'pdf', category=PAPER_BOUNDS)['sections']
    quote = generation_quote(customer, draft.id, draft.version)
    assert quote.parameters['category'] == entry_id
    assert quote.policy['generation_bounds']['output_pages'] == data['options']['length'] + 1
