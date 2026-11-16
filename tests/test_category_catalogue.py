"""The category catalogue loads, holds together, keeps its ids, and answers what customers may pick."""
import copy
import json
import sys
import types

import pytest

from apps.core.errors import DomainError
from apps.studio import categories
from apps.studio.categories import catalogue, derive, edits
from apps.studio.categories.catalogue import (CHOSEN_EVENT, PAPER_BOUNDS, CatalogueError, build, check, lock_problems,
                                              read, read_lock, relock)

# The owner's names for the 28 categories, as the uz buttons carry them after their emoji.
OWNER_NAMES = {
    'pdf.mustaqil_ish': 'Mustaqil ish / Referat', 'pdf.kurs_ishi': 'Kurs ishi', 'pdf.konspekt': 'Konspekt / Xulosa',
    'pdf.dars_ishlanmasi': 'Dars ishlanmasi / tarqatma', 'pdf.test': 'Test savollari',
    'pdf.biz.biznes_reja': 'Biznes-reja', 'pdf.biz.tijorat_taklifi': 'Tijorat taklifi', 'pdf.biz.hisobot': 'Hisobot',
    'pdf.biz.yoriqnoma': 'Xodimlar uchun yo‘riqnoma', 'pdf.biz.lavozim_yoriqnomasi': 'Lavozim yo‘riqnomasi',
    'pdf.biz.bayonnoma': 'Yig‘ilish bayonnomasi', 'pdf.biz.marketing_reja': 'Marketing reja',
    'pdf.xat.motivatsion': 'Motivatsion xat', 'pdf.xat.ishga_kirish': 'Ishga kirish xati', 'pdf.xat.ariza': 'Ariza',
    'pdf.xat.tavsifnoma': 'Tavsifnoma', 'pdf.xat.tavsiya': 'Tavsiya xati', 'pdf.xat.tushuntirish': 'Tushuntirish xati',
    'slides.mavzu': 'Mavzu bo‘yicha slayd', 'slides.himoya': 'Himoya', 'slides.dars': 'Dars / ochiq dars',
    'slides.pitch': 'Startap / Pitch', 'slides.hisobot': 'Hisobot', 'slides.kompaniya': 'Kompaniya / mahsulot',
    'slides.tadbir.tarbiyaviy_soat': 'Tarbiyaviy soat', 'slides.tadbir.bayram': 'Bayram tadbiri',
    'slides.tadbir.ota_onalar': 'Ota-onalar yig‘ilishi', 'slides.tadbir.pedkengash': 'Pedagogik kengash',
}
OWNER_GROUPS = {'pdf.biz': 'Biznes va ish', 'pdf.xat': 'Xat va hujjatlar', 'slides.tadbir': 'Tarbiyaviy soat / tadbir'}
OWNER_OTHER = {None: 'Boshqa', 'pdf.biz': 'Boshqa hujjat', 'pdf.xat': 'Boshqa xat', 'slides.tadbir': 'Boshqa tadbir'}
OWNER_LISTS = {
    'ai.pdf_topic': ['pdf.mustaqil_ish', 'pdf.kurs_ishi', 'pdf.konspekt', 'pdf.dars_ishlanmasi', 'pdf.test', 'pdf.biz',
                     'pdf.xat', 'other'],
    'ai.pptx': ['slides.mavzu', 'slides.himoya', 'slides.dars', 'slides.tadbir', 'slides.pitch', 'slides.hisobot',
                'slides.kompaniya', 'other'],
}


def files():
    return copy.deepcopy(read())


def errors(found):
    return [str(problem) for problem in found if not problem.warning]


def built_problems(entries, templates, index):
    with pytest.raises(CatalogueError) as raised:
        build(entries, templates, index)
    return raised.value.problems


def checked(entries, templates, index, lock=None):
    made = build(entries, templates, index)
    return errors(check(catalogue=made, lock=catalogue.relock(made, {}) if lock is None else lock))


@pytest.fixture
def switch(monkeypatch):
    """The switch row, as operations.categories_settings would hand it over."""
    state = {'on': False, 'live': []}
    module = types.ModuleType('operations.categories_settings')
    module.get = lambda: copy.deepcopy(state)
    monkeypatch.setitem(sys.modules, 'operations.categories_settings', module)
    return state


@pytest.fixture
def ready(monkeypatch):
    """The catalogue with the three examples marked ready, as N1 and N2 will mark entries."""
    entries, templates, index = files()
    for raw in entries.values():
        raw['status'] = 'ready'
    made = build(entries, templates, index)
    monkeypatch.setattr(catalogue, '_catalogue', lambda: made)
    return made


# ---------------------------------------------------------------- the files


def test_every_file_validates_and_the_catalogue_is_fit_to_ship():
    entries, templates, _ = read()
    assert {'pdf.xat.ariza', 'pdf.test', 'slides.himoya'} <= set(entries)
    assert {'official_ariza', 'study_test'} <= set(templates)
    assert not errors(check())


def test_the_command_line_checks_and_says_the_lock_is_whole(capsys):
    assert catalogue.main(['--check']) == 0
    assert '0 errors' in capsys.readouterr().out
    assert catalogue.main(['--check', 'slides.']) == 0
    out = capsys.readouterr().out
    assert 'slides.himoya: ready' in out and 'pdf.test: draft' not in out
    lock = read_lock()
    assert relock(catalogue._catalogue(), lock) == lock


def test_the_schema_refuses_a_malformed_entry_and_names_the_file():
    entries, templates, index = files()
    entries['pdf.test']['status'] = 'live'
    del entries['slides.himoya']['bot']
    found = built_problems(entries, templates, index)
    assert any(problem.startswith('pdf.test: status:') for problem in found)
    assert any(problem.startswith('slides.himoya:') and "'bot'" in problem for problem in found)


def test_a_template_is_validated_against_its_own_schema():
    entries, templates, index = files()
    templates['study_test']['page_rule'] = {'kind': 'stretch'}
    assert any(problem.startswith('templates/study_test: page_rule/kind') for problem in
               built_problems(entries, templates, index))


@pytest.mark.parametrize('spoil, says', [
    (lambda e, t, i: e['pdf.xat.ariza']['parts'][0]['fields'].append('fax'), "unknown fields ['fax']"),
    (lambda e, t, i: e['pdf.xat.ariza']['parts'][0].update(group='chapters'), 'group chapters is not declared'),
    (lambda e, t, i: e['pdf.xat.ariza']['parts'][0].update(block='stamp'), 'block stamp is not a drawing block'),
    (lambda e, t, i: e['slides.himoya']['parts'][1].update(when='cue:phd'), 'when cue:phd names no cue'),
    (lambda e, t, i: e['slides.himoya']['parts'][1].update(layouts=['bullets', 'poster']), "unknown layouts ['poster']"),
    (lambda e, t, i: e['slides.himoya']['length']['by_cue'].append({'cue': 'phd', 'default': 12}), 'by_cue names no cue'),
    (lambda e, t, i: e['slides.himoya']['exclusive'][0].append('phd'), 'exclusive names cues'),
    (lambda e, t, i: e['slides.himoya']['ask']['fields'].append('grade'), "ask: unknown fields ['grade']"),
    (lambda e, t, i: e['pdf.test']['fields'].append(copy.deepcopy(e['pdf.test']['fields'][0])), 'field ids used twice'),
    (lambda e, t, i: e['pdf.xat.ariza']['fields'][-1].update(derived_from='nobody'), 'derived_from nobody'),
    (lambda e, t, i: e['pdf.test']['templates'].append('study_quiz'), 'template study_quiz has no file'),
    (lambda e, t, i: e['pdf.xat.ariza']['templates'].append('study_test'), 'does not list this entry'),
    (lambda e, t, i: t['study_test']['flow'][0].update(part='cover'), 'part cover is not a part for pdf.test'),
    (lambda e, t, i: t['study_test']['flow'][1].update(when='nofact:use=homework'), 'homework is not one of the choices'),
    (lambda e, t, i: t['official_ariza']['flow'][2]['params'].update(label='heading'), "labels ['heading']"),
    (lambda e, t, i: t['official_ariza']['labels']['name'].update(
        uz='{applicant_nick}', ru='{applicant_nick}', en='{applicant_nick}'), "slots ['applicant_nick'] are not fields"),
    (lambda e, t, i: e['pdf.test'].update(order=2), 'order is 2 but index.json shows it at 5'),
    (lambda e, t, i: e['pdf.xat.ariza'].update(parent=None), 'parent is None but index.json lists it under pdf.xat'),
    (lambda e, t, i: i['lists']['ai.pptx'].remove('slides.himoya'), 'slides.himoya: not in index.json'),
    (lambda e, t, i: i['groups']['pdf.xat']['children'].remove('other'), 'Boshqa (other) must be in the group once'),
    (lambda e, t, i: i['lists']['ai.pptx'].insert(0, 'pdf.konspekt'), 'not a group, a slides category id or other'),
    (lambda e, t, i: next(part for part in e['slides.himoya']['parts'] if part['source'] == 'customer').update(
        checks=['numbers']), 'checks go with source draft only'),
    (lambda e, t, i: next(part for part in e['slides.himoya']['parts'] if part['source'] == 'draft').update(
        checks=['dates']), "'dates' is not one of ['numbers', 'names']"),
])
def test_every_reference_resolves(spoil, says):
    entries, templates, index = files()
    spoil(entries, templates, index)
    found = built_problems(entries, templates, index)
    assert any(says in problem for problem in found), found


def test_the_event_deck_draft_slots_about_the_customers_own_school_hold_its_facts():
    """A council's problems, proposals and resolution and a parents' meeting's agenda and requests are drafts that
    state the customer's own facts: their numbers are checked, and their names too (their write texts forbid a name
    the source does not give), except on a parents' agenda, which only repeats the deck's slide headings."""
    checked = {(entry_id, part['id']): part['checks'] for entry_id, raw in read()[0].items()
               for part in raw['parts'] if part.get('checks')}
    assert checked == {
        ('slides.tadbir.pedkengash', 'kun_tartibi'): ['numbers', 'names'],
        ('slides.tadbir.pedkengash', 'muammo_yechim'): ['numbers', 'names'],
        ('slides.tadbir.pedkengash', 'muammolar'): ['numbers', 'names'],
        ('slides.tadbir.pedkengash', 'takliflar'): ['numbers', 'names'],
        ('slides.tadbir.pedkengash', 'takliflar_natija'): ['numbers', 'names'],
        ('slides.tadbir.pedkengash', 'qaror'): ['numbers', 'names'],
        ('slides.tadbir.ota_onalar', 'kun_tartibi'): ['numbers'],
        ('slides.tadbir.ota_onalar', 'iltimoslar'): ['numbers', 'names'],
    }


def test_an_index_id_with_no_entry_yet_is_allowed_and_never_shown(switch, ready):
    """The entries the C2 packages convert are listed already; until their files land they are not buttons."""
    switch.update(on=True, live=sorted(OWNER_NAMES))
    index = ready.index
    for feature, items in index['lists'].items():
        landed = [item for item in items if item == 'other' or item in ready.entries
                  or any(child in ready.entries for child in index['groups'].get(item, {}).get('children', ()))]
        assert [node.id for node in catalogue.menu(feature)] == landed
    # The deck entries have all landed (C2s); the papers still wait for theirs.
    assert [node.id for node in catalogue.menu('ai.pptx')] == OWNER_LISTS['ai.pptx']
    assert 'pdf.mustaqil_ish' not in [node.id for node in catalogue.menu('ai.pdf_topic')]


@pytest.mark.parametrize('spoil, says', [
    (lambda e, t, i: e['pdf.test']['labels'].update(uz='📝 Тест'), 'Cyrillic in uz'),
    (lambda e, t, i: e['pdf.test']['bot']['examples'][0].update(en='Тест по истории'), 'Cyrillic in en'),
    (lambda e, t, i: e['pdf.test']['labels'].update(uz="📝 To'plam"), 'ASCII apostrophe in uz'),
    (lambda e, t, i: e['slides.himoya']['bot']['prompt'].update(ru='Слайды <b>защиты</b>'), '< or & in ru'),
    (lambda e, t, i: t['official_ariza']['labels']['sign'].update(en='Signed {date_written}'), 'different slots'),
    (lambda e, t, i: i['groups']['pdf.xat']['label'].update(en='Letters & papers'), '< or & in en'),
])
def test_customer_words_keep_their_alphabet_and_carry_no_markup(spoil, says):
    entries, templates, index = files()
    spoil(entries, templates, index)
    found = checked(entries, templates, index)
    assert any(says in problem for problem in found), found


def test_two_buttons_of_one_list_never_read_the_same():
    entries, templates, index = files()
    entries['pdf.xat.ariza']['labels']['ru'] = '✉️ Другое письмо'
    assert any('the ru label is the same as other in the pdf.xat list' in problem
               for problem in checked(entries, templates, index))


def test_bot_copy_never_promises_what_is_deferred():
    entries, templates, index = files()
    entries['pdf.test']['bot']['examples'][0]['ru'] += ' Нужно в двух вариантах.'
    assert any("deferred thing: 'вариантах'" in problem for problem in checked(entries, templates, index))
    entries, templates, index = files()
    entries['pdf.test']['bot']['examples'][0]['uz'] += ' Ikki variant kerak.'
    assert any("deferred thing: 'ikki variant'" in problem for problem in checked(entries, templates, index))


def test_the_required_parts_never_share_more_than_all_the_pages():
    entries, templates, index = files()
    entries['pdf.xat.ariza']['parts'][3]['share'] = 0.6
    assert any('share 1.07 of the pages' in problem for problem in checked(entries, templates, index))


def test_a_deck_names_only_designs_and_variants_that_exist():
    entries, templates, index = files()
    entries['slides.himoya']['look']['designs'][0] = 'velvet_moon'
    entries['slides.himoya']['parts'][1]['pins'] = ['bullets.no_such_variant']
    found = checked(entries, templates, index)
    assert any('velvet_moon is not a deck design' in problem for problem in found)
    assert any('bullets.no_such_variant is not a registered slide variant' in problem for problem in found)


def test_readiness_gates_are_warnings_on_a_draft_and_errors_on_a_ready_entry():
    entries, templates, index = files()
    # A deck converted by C2s meets its count and block gates; take them away again to see them caught. The prompt
    # is replaced whole, so the check does not hang on how himoya's own copy happens to write its count.
    himoya = entries['slides.himoya']
    himoya['status'] = 'draft'  # ready since N1; the gates are read here on a draft first
    himoya['bot']['prompt'] = {'uz': 'Bitta xabarda yozing.', 'ru': 'Напишите одним сообщением.',
                               'en': 'Say it in one message.'}
    himoya['rules'].append({'text': 'A long rule. ' * 400, 'to': 'model'})
    made = build(entries, templates, index)
    drafts = check(catalogue=made, lock=relock(made, {}))
    assert any(problem.warning and 'rewrite rule is left' in problem.text for problem in drafts)
    assert any(problem.warning and 'not yet registered' in problem.text for problem in drafts)
    assert any(problem.warning and 'default count 10' in problem.text for problem in drafts)
    for raw in entries.values():
        raw['status'] = 'ready'
    found = checked(entries, templates, index)
    assert any('pdf.test: a rewrite rule is left' in problem for problem in found)
    assert any('pdf.xat.ariza: blocks not yet registered' in problem and 'party_block' in problem for problem in found)
    assert any('slides.himoya: the default count 10 is not in the uz bot prompt' in problem for problem in found)
    assert any('slides.himoya: the instruction block is' in problem for problem in found)


def test_a_ready_entry_meets_its_gates_once_the_work_is_done():
    entries, templates, index = files()
    himoya = entries['slides.himoya']
    himoya['status'] = 'ready'
    himoya['rules'] = [rule for rule in himoya['rules'] if len(rule['text']) < 300][:6]
    for locale in ('uz', 'ru', 'en'):
        himoya['bot']['prompt'][locale] += ' 10'
    found = [problem for problem in checked(entries, templates, index) if problem.startswith('slides.himoya')]
    assert found == []


def test_the_block_estimate_counts_what_the_model_reads():
    # Measured now that categories/prompting.py builds the block (P1), no longer estimated.
    from apps.studio.categories import prompting
    entry = catalogue.get('pdf.xat.ariza')
    size, estimated = catalogue.block_size(entry)
    assert not estimated and size == len(prompting.block(entry))
    rules = sum(len(rule['text']) for rule in entry.raw['rules'] if rule['to'] == 'model')
    assert size > rules + len(entry.raw['tone'])


# ---------------------------------------------------------------- the lock


def test_the_lock_holds_every_id_of_the_catalogue():
    lock = read_lock()
    assert not lock_problems(catalogue._catalogue(), lock)
    assert lock['entries']['pdf.xat.ariza']['fields']['signer_name'] == 'person'
    assert lock['entries']['slides.himoya']['parts']['cover'] == 'slide'
    assert lock['entries']['pdf.test']['templates'] == ['study_test']


def test_a_locked_id_may_never_disappear_or_change_kind():
    lock = read_lock()
    entries, templates, index = files()
    entries['pdf.xat.ariza']['fields'] = [item for item in entries['pdf.xat.ariza']['fields']
                                          if item['id'] != 'reference_numbers']
    entries['pdf.test']['parts'] = [part for part in entries['pdf.test']['parts'] if part['id'] != 'grade_scale']
    entries['pdf.test']['fields'][0]['kind'] = 'line'
    found = checked(entries, templates, index, lock=lock)
    assert any('pdf.xat.ariza: the locked field reference_numbers is gone' in problem for problem in found)
    assert any('pdf.test: the locked part grade_scale is gone: mark it retired' in problem for problem in found)
    assert any('pdf.test: the locked field subject changed kind from text to line' in problem for problem in found)
    with pytest.raises(CatalogueError):
        relock(build(entries, templates, index), lock)


def test_a_retired_part_keeps_its_id_and_an_entry_is_retired_never_deleted():
    lock = read_lock()
    entries, templates, index = files()
    entries['pdf.xat.ariza']['parts'][6]['retired'] = True
    entries['pdf.test']['status'] = 'retired'
    index['lists']['ai.pdf_topic'].remove('pdf.test')
    assert checked(entries, templates, index, lock=lock) == []
    del entries['pdf.test']
    del templates['study_test']
    found = checked(entries, templates, index, lock=lock)
    assert any('pdf.test: a locked entry is gone' in problem for problem in found)


def test_new_ids_must_be_locked_and_locking_adds_them_without_removing_any():
    lock = read_lock()
    entries, templates, index = files()
    extra = copy.deepcopy(entries['pdf.xat.ariza']['fields'][0])
    extra['id'] = 'addressee_office'
    entries['pdf.xat.ariza']['fields'].append(extra)
    found = checked(entries, templates, index, lock=lock)
    assert any('pdf.xat.ariza: not in ids.lock.json yet (field addressee_office)' in problem for problem in found)
    new = relock(build(entries, templates, index), lock)
    assert new['entries']['pdf.xat.ariza']['fields']['addressee_office'] == 'org'
    for entry_id, was in lock['entries'].items():
        for kind in ('fields', 'parts'):
            assert was[kind].items() <= new['entries'][entry_id][kind].items()
    assert checked(entries, templates, index, lock=new) == []


def test_the_lock_file_is_the_command_lines_own_output():
    lock = read_lock()
    text = (catalogue.DATA / 'ids.lock.json').read_text(encoding='utf-8')
    assert text == json.dumps(relock(catalogue._catalogue(), lock), ensure_ascii=False, indent=1, sort_keys=True) + '\n'


# ---------------------------------------------------------------- the owner's words


def test_the_uz_labels_are_the_owners_names():
    for entry in catalogue._catalogue().entries.values():
        assert entry.name('uz') == OWNER_NAMES[entry.id], entry.id
        assert all(len(label) <= 32 for label in entry.raw['labels'].values())
    index = catalogue._catalogue().index
    assert {group: node['label']['uz'].split(' ', 1)[1] for group, node in index['groups'].items()} == OWNER_GROUPS
    assert index['other']['uz'].split(' ', 1)[1] == OWNER_OTHER[None]
    assert {group: node['other']['uz'].split(' ', 1)[1] for group, node in index['groups'].items()} == {
        group: OWNER_OTHER[group] for group in OWNER_GROUPS}


def test_the_lists_are_in_the_owners_order_and_hold_all_28():
    index = catalogue._catalogue().index
    assert index['lists'] == OWNER_LISTS
    listed = {item for feature in OWNER_LISTS for item in catalogue._walk(index, feature)} - {'other'}
    assert listed == set(OWNER_NAMES)


def test_an_owner_label_that_drifts_is_caught():
    entries, templates, index = files()
    entries['pdf.test']['labels']['uz'] = '📝 Testlar'
    index['owner_labels']['pdf.test'] = 'Test savollari'
    assert any("the uz label must be the owner's 'Test savollari'" in problem
               for problem in checked(entries, templates, index))


# ---------------------------------------------------------------- asking


def test_get_and_the_entry_it_gives():
    entry = catalogue.get('slides.himoya')
    assert (entry.id, entry.service, entry.feature_id, entry.status) == ('slides.himoya', 'slides', 'ai.pptx', 'ready')
    assert entry.label('uz') == '🛡 Himoya' and entry.label('ru') == '🛡 Защита работы'
    assert entry.label('de') == entry.label('en') and entry.name('en') == 'Thesis defence'
    assert entry.field('results')['kind'] == 'text' and entry.field('nothing') is None
    assert entry.part('cover')['layouts'] == ['cover'] and entry.part('nothing') is None
    assert entry.parts[0]['id'] == 'cover' and entry.fields[0]['id'] == 'topic'
    assert entry.templates == () and entry.look['designs'][0] == 'boardroom'
    assert entry.length['default'] == 10 and entry.ask['when'] == 'no_digits' and entry.topic is True
    assert entry.raw['id'] == 'slides.himoya' and len(entry.digest) == 8
    paper = catalogue.get('pdf.xat.ariza')
    assert paper.feature_id == 'ai.pdf_topic' and paper.templates == ('official_ariza',) and paper.look is None
    assert catalogue.get('pdf.nothing') is None and catalogue.get(None) is None and catalogue.get(['pdf.test']) is None
    with pytest.raises(Exception):
        entry.status = 'ready'


def test_a_later_instance_of_a_grouped_part_finds_its_part(monkeypatch):
    entries, templates, index = files()
    entries['pdf.xat.ariza']['groups'] = {'items': {'min': 1, 'max': 3, 'sized': 'model'}}
    entries['pdf.xat.ariza']['parts'][3]['group'] = 'items'
    made = build(entries, templates, index)
    entry = made.entries['pdf.xat.ariza']
    assert entry.part('request_2')['id'] == 'request'
    assert entry.part('statements_2') is None


def test_of_is_three_way_no_category_a_known_one_or_a_refusal():
    assert catalogue.of({'options': {'pages': 10}}) is None
    assert catalogue.of({'options': {'category': None}}) is None
    assert catalogue.of({}) is None and catalogue.of(None) is None
    assert catalogue.of({'options': {'category': 'pdf.test'}}).id == 'pdf.test'
    assert catalogue.of({'parameters': {'category': 'slides.himoya'}}).id == 'slides.himoya'
    for wrong in ('pdf.nothing', 'other', '', 7):
        with pytest.raises(DomainError) as raised:
            catalogue.of({'options': {'category': wrong}})
        assert (raised.value.code, raised.value.status) == ('category_unknown', 500)


def test_a_retired_entry_still_answers_for_the_drafts_made_with_it(monkeypatch):
    entries, templates, index = files()
    entries['pdf.test']['status'] = 'retired'
    made = build(entries, templates, index)
    monkeypatch.setattr(catalogue, '_catalogue', lambda: made)
    assert catalogue.of({'options': {'category': 'pdf.test'}}).status == 'retired'
    assert 'pdf.test' not in [entry.id for entry in catalogue.for_feature('ai.pdf_topic')]


def test_bounds_are_the_papers_for_a_category_pdf_and_todays_otherwise():
    assert catalogue.bounds({'options': {'category': 'pdf.xat.ariza'}}) == PAPER_BOUNDS == (60, 40)
    assert catalogue.bounds({'options': {'category': 'slides.himoya'}}) is None
    assert catalogue.bounds({'options': {}}) is None


def test_for_feature_lists_each_service_in_the_lists_order():
    # The paper entries land package by package (C2a, C2b, C2c): whatever has landed is listed in the owner's
    # order, a group's children where the group stands.
    order = list(catalogue._walk(catalogue.read()[2], 'ai.pdf_topic'))
    papers = [entry.id for entry in catalogue.for_feature('ai.pdf_topic')]
    assert papers == [item for item in order if item in papers] and {'pdf.test', 'pdf.xat.ariza'} <= set(papers)
    assert [item for item in papers if item.startswith('pdf.biz.')] == [
        'pdf.biz.biznes_reja', 'pdf.biz.tijorat_taklifi', 'pdf.biz.hisobot', 'pdf.biz.yoriqnoma',
        'pdf.biz.lavozim_yoriqnomasi', 'pdf.biz.bayonnoma', 'pdf.biz.marketing_reja']
    assert [entry.id for entry in catalogue.for_feature('ai.pptx')] == [
        'slides.mavzu', 'slides.himoya', 'slides.dars', 'slides.tadbir.tarbiyaviy_soat', 'slides.tadbir.bayram',
        'slides.tadbir.ota_onalar', 'slides.tadbir.pedkengash', 'slides.pitch', 'slides.hisobot', 'slides.kompaniya']
    assert catalogue.for_feature('pdf.merge') == []


def test_everything_is_off_while_the_switch_module_does_not_exist(monkeypatch, ready):
    monkeypatch.setitem(sys.modules, 'operations.categories_settings', None)
    assert catalogue.on() is False
    assert catalogue.live('ai.pptx') == [] and catalogue.menu('ai.pptx') == []


def test_off_is_off_whatever_is_ticked(switch, ready):
    switch['live'] = ['slides.himoya', 'pdf.test']
    assert catalogue.on() is False and catalogue.live('ai.pptx') == [] and catalogue.menu('ai.pdf_topic') == []


def test_only_ticked_ready_entries_of_the_service_are_live(switch):
    switch.update(on=True, live=['slides.himoya', 'pdf.test'])
    assert catalogue.on() is True
    # The decks are ready since N1 and the papers still drafts: a ticked draft is not live.
    assert [entry.id for entry in catalogue.live('ai.pptx')] == ['slides.himoya']
    assert catalogue.live('ai.pdf_topic') == [] and catalogue.menu('ai.pdf_topic') == []


def test_the_list_shows_live_categories_groups_with_something_live_and_boshqa(switch, ready):
    switch.update(on=True, live=['pdf.xat.ariza', 'slides.himoya', 'pdf.nothing'])
    assert [entry.id for entry in catalogue.live('ai.pdf_topic')] == ['pdf.xat.ariza']
    top = catalogue.menu('ai.pdf_topic')
    assert [(node.id, node.kind) for node in top] == [('pdf.xat', 'group'), ('other', 'other')]
    assert [node.label('uz') for node in top] == ['✉️ Xat va hujjatlar', '✏️ Boshqa']
    group = catalogue.menu('ai.pdf_topic', 'pdf.xat')
    assert [(node.id, node.kind) for node in group] == [('pdf.xat.ariza', 'category'), ('other', 'other')]
    assert group[0].entry is catalogue.get('pdf.xat.ariza') and group[0].label('ru') == '📝 Заявление'
    assert group[1].label('en') == '✉️ Another letter'
    assert catalogue.menu('ai.pdf_topic', 'pdf.biz') == []
    assert catalogue.menu('ai.pptx', 'pdf.xat') == [] and catalogue.menu('ai.pdf_topic', 'pdf.nothing') == []
    switch['live'] = ['pdf.test']
    assert [node.id for node in catalogue.menu('ai.pdf_topic')] == ['pdf.test', 'other']
    assert catalogue.menu('ai.pptx') == []


def test_the_switch_is_read_on_every_call(switch, ready):
    switch.update(on=True, live=['slides.himoya'])
    assert catalogue.menu('ai.pptx')
    switch['on'] = False
    assert catalogue.menu('ai.pptx') == []


def test_examples_hold_every_example_and_pool_text_in_every_language():
    found = catalogue.examples()
    for entry in catalogue._catalogue().entries.values():
        for text in (*entry.raw['bot']['examples'], *entry.raw['bot'].get('pool', [])):
            assert set(text.values()) <= found


def test_version_and_digests_follow_the_content_not_its_layout():
    entries, templates, index = files()
    first = build(entries, templates, index)
    assert first.version == catalogue.version() and len(first.version) == 12
    again = build(*files())
    assert again.version == first.version
    templates['official_ariza']['labels']['sign']['en'] = 'Signed'
    changed = build(entries, templates, index)
    assert changed.version != first.version
    assert changed.entries['pdf.xat.ariza'].digest != first.entries['pdf.xat.ariza'].digest
    assert changed.entries['pdf.test'].digest == first.entries['pdf.test'].digest


def test_a_template_is_given_by_its_id():
    assert catalogue.template('study_test')['entries'] == ['pdf.test']
    with pytest.raises(KeyError):
        catalogue.template('study_quiz')


def test_the_package_answers_for_the_catalogue():
    assert categories.of is catalogue.of and categories.live is catalogue.live and categories.Entry is catalogue.Entry
    assert categories.CHOSEN_EVENT == CHOSEN_EVENT == 'category.chosen'
    with pytest.raises(AttributeError):
        categories.nothing


def test_the_stubs_change_nothing_until_their_packages_build_them():
    entry = catalogue.get('pdf.test')
    content = {'title': 'Tarix', 'sections': [], 'questions': []}
    assert edits.read('Kirish qo‘sh', entry, fmt='pdf', sections=[]) is None
    assert derive.apply(entry, content, object()) is content


def test_the_unknown_category_refusal_has_words_in_each_language():
    words = {locale: json.loads((catalogue.DATA.parents[3] / 'i18n' / f'{locale}.json').read_text(encoding='utf-8'))
             ['category_unknown'] for locale in ('en', 'uz', 'ru')}
    assert all(words.values()) and "'" not in words['uz']
