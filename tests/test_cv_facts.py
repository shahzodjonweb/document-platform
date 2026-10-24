"""What a CV is asked for, and what its description gives: the required and the optional facts.

A CV needs its person's name, a way to reach them (a phone number or an email)
and a job or a school (apps/studio/cv/content.py `facts`). Whatever is missing
is asked for before anything is made or counted (`cv_missing`); the optional
facts (the job wanted, a city, skills ...) are only offered. Detection is by
rule, never by a model, so these tests hold the rules to what customers
write: students, drivers, sellers and freelancers, in English, Uzbek and
Russian, with a Telegram handle, a birth year, an age or a passport number
where a phone or a job should be. The descriptions are kept in
apps/studio/cv/fact_cases.py, the one list the web's ticks are held to too
(contracts/cv_fact_cases.json). Everyone in them is fictional (example.com
contacts, the sample number).
"""
import json
import time
from pathlib import Path

import pytest

from apps.core.errors import DomainError, error_data
from apps.studio.cv import content as cv_content
from apps.studio.cv.content import OPTIONAL_FACTS, REQUIRED_FACTS, facts, missing_facts, name_in, require_facts
from apps.studio.cv.fact_cases import BACKGROUNDS, BRIEFS, CONTACTS, WEB_PLACEHOLDERS
from apps.studio.domain import CV, DOCUMENT, create_draft, pack, unpack, update_draft
from telegram.errors import bot_error
from telegram.ux_copy import MESSAGES, PROMPT_EXAMPLES
from tests.test_cv_content import BRIEF, customer  # noqa: F401  (customer is a fixture)
from tests.test_platform import login_client

ROOT = Path(__file__).resolve().parents[1]
LETTERS = dict(zip(REQUIRED_FACTS, 'NCB'))


def has(text, fact):
    return facts(text)[fact]


def payload_of(prompt, **more):
    """The payload of a new CV made from `prompt`, as domain._prepare_draft makes it."""
    return {'prompt': prompt, 'source_text': '', 'title': 'Untitled document', 'excerpts': [], 'options': {},
            'content': cv_content.seed('Untitled document'), **more}


def given_of(text):
    """The required facts `text` gives, as the letters of N(ame), C(ontact) and B(ackground)."""
    found = facts(text, name=bool(name_in(text)))
    return ''.join(LETTERS[fact] for fact in REQUIRED_FACTS if found[fact])


# --- The contact -----------------------------------------------------------------------------------
# CONTACTS: (text, whether it gives a phone number or an email).

@pytest.mark.parametrize('text,gives', CONTACTS)
def test_a_phone_number_or_an_email_is_a_contact_and_nothing_else_is(text, gives):
    assert facts(text)['contact'] is gives


# --- The background --------------------------------------------------------------------------------
# BACKGROUNDS: (text, whether it gives a job or an education).

@pytest.mark.parametrize('text,gives', BACKGROUNDS)
def test_a_job_or_an_education_is_a_background_and_a_wish_or_an_age_is_not(text, gives):
    assert facts(text)['background'] is gives


# --- Whole descriptions ----------------------------------------------------------------------------
# What a customer writes in one message, and which of the three required facts it gives (BRIEFS: note, the
# facts given as N, C and B, text).

@pytest.mark.parametrize('given,text', [pytest.param(given, text, id=note) for note, given, text in BRIEFS])
def test_a_description_gives_the_required_facts_it_gives_and_no_others(given, text):
    assert given_of(text) == given


# --- The optional facts ----------------------------------------------------------------------------

OPTIONAL = [
    ('target', 'Looking for a head of marketing role', True), ('target', 'Buxgalter lavozimiga ish izlayapman', True),
    ('target', 'Ищу работу бухгалтером', True), ('target', 'I want a job as a sales manager', True),
    ('target', 'Sales manager at Artel since 2020', False),
    ('location', 'Marketing manager in Tashkent', True), ('location', 'Toshkentda yashayman', True),
    ('location', 'Живу в Самарканде', True), ('location', 'Sales manager since 2020', False),
    ('birth', 'Born in 1999', True), ('birth', 'Tug‘ilgan sana: 12.05.1999', True), ('birth', 'Мне 28 лет', True),
    ('birth', 'Dilnoza Karimova, 28 yoshda', True), ('birth', 'Sales manager, 03.07.2019 - 02.02.2022', False),
    # Typed without its apostrophe, as Uzbek often is.
    ('birth', 'Tugilgan yil 1996', True), ('birth', '1996 yilda tugilganman', True),
    ('skills', 'Skills: Excel, 1C', True), ('skills', 'Ko‘nikmalar: Excel', True), ('skills', 'Навыки: Excel', True),
    ('skills', 'Excel and 1C at Artel since 2020', False),
    ('languages', 'Languages: Uzbek, Russian', True), ('languages', 'Tillar: o‘zbek, rus', True),
    ('languages', 'Языки: узбекский', True), ('languages', 'English B2', True), ('languages', 'IELTS 7.0', True),
    ('languages', 'Python, Django, Docker', False),
    ('certificates', 'Certificate: CS50x', True), ('certificates', 'Sertifikat: Google Ads', True),
    ('certificates', 'Курс по 1С', True), ('certificates', 'Bachelor in finance', False),
    ('projects', 'Projects: a booking system', True), ('projects', 'Loyihalar: onlayn do‘kon', True),
    ('projects', 'Проекты: сайт', True), ('projects', 'Sales manager since 2020', False),
    ('links', '@dilnoza_smm', True), ('links', 'linkedin.com/in/dilnoza-k', True), ('links', 'github.com/dilnoza', True),
    ('links', 'LinkedIn: dilnoza-k', True), ('links', 'dilnoza.karimova@example.com', False),
    ('links', 'Sales manager since 2020', False),
    ('photo', 'Sales manager since 2020', False),
]


@pytest.mark.parametrize('fact,text,gives', [pytest.param(*row, id=f'{row[0]}-{number}') for number, row in
                                             enumerate(OPTIONAL)])
def test_an_optional_fact_is_given_by_the_words_that_give_it(fact, text, gives):
    assert facts(text)[fact] is gives


def test_a_photo_is_given_by_the_portrait_not_by_words():
    assert facts('Photo attached')['photo'] is False
    assert facts('Sales manager', portrait=True)['photo'] is True


def test_the_facts_are_the_twelve_there_are_and_missing_ones_come_in_the_order_they_are_shown():
    assert REQUIRED_FACTS == ('name', 'contact', 'background')
    assert OPTIONAL_FACTS == ('target', 'location', 'birth', 'skills', 'languages', 'certificates', 'projects', 'links',
                              'photo')
    found = facts(BRIEF, name=True)
    assert list(found) == [*REQUIRED_FACTS, *OPTIONAL_FACTS]
    nothing = facts('')
    assert not any(nothing.values()) and missing_facts(nothing) == (list(REQUIRED_FACTS), list(OPTIONAL_FACTS))
    assert missing_facts({'name': True, 'contact': False, 'background': True, 'skills': True, 'links': True}) == (
        ['contact'], ['target', 'location', 'birth', 'languages', 'certificates', 'projects', 'photo'])


# --- What the examples, the fixtures and the screens show ------------------------------------------
# WEB_PLACEHOLDERS are the Studio's three placeholders.

def file_payload(raw, kind, suffix):
    """The payload a CV made from this file has: its pages as the reader made them, the name at the top as a hint."""
    from tests.test_cv_sources import read
    result = read(raw, kind, suffix)
    excerpts = [{'asset_id': 'a1', **page} for page in result['pages']]
    excerpts[0]['names'] = result['names']
    return {**payload_of(''), 'excerpts': excerpts}


def test_every_example_and_fixture_brief_gives_every_required_fact():
    from tests.test_cv_sources import docx_cv, docx_with_box, linkedin_pdf, one_column_pdf
    texts = {f'example {number}.{locale}': text for number, row in enumerate(PROMPT_EXAMPLES[CV])
             for locale, text in zip(('en', 'uz', 'ru'), row)}
    texts.update({f'placeholder {locale}': text for locale, text in zip(('en', 'uz', 'ru'), WEB_PLACEHOLDERS)})
    texts['BRIEF'] = BRIEF
    assert len(texts) == 13
    for label, text in texts.items():
        assert missing_facts(facts(text, name=bool(name_in(text))))[0] == [], label
    # A CV made from a file takes its facts from the file, and its name from the largest line at the top.
    for raw, kind, suffix, name in ((linkedin_pdf(), 'pdf', '.pdf', 'Dilnoza Karimova'),
                                    (one_column_pdf(), 'pdf', '.pdf', 'Timur Rakhimov'),
                                    (docx_cv(), 'docx', '.docx', 'Javlon Ergashev'),
                                    (docx_with_box(), 'docx', '.docx', 'Kamola Nazarova')):
        payload = file_payload(raw, kind, suffix)
        require_facts({}, CV, payload)
        assert payload['title'] == name and payload['cv_facts']['missing'] == [], name


def test_a_greeting_gives_nothing_and_a_name_alone_gives_only_the_name():
    for greeting in ('Assalomu alaykum', 'Здравствуйте, нужно резюме', 'Hi, I need a CV', 'rezyume kerak',
                     'Мне нужно резюме'):
        assert given_of(greeting) == '', greeting
    assert given_of('Dilnoza Karimova') == 'N'
    assert missing_facts(facts('Dilnoza Karimova', name=True))[0] == ['contact', 'background']


@pytest.mark.parametrize('index', range(3))
def test_every_sample_a_screen_shows_satisfies_the_check_that_asks_for_it(index):
    assert name_in(MESSAGES['cv_name_sample'][index])
    assert has(MESSAGES['cv_fact_contact_sample'][index], 'contact')
    assert has(MESSAGES['cv_fact_background_sample'][index], 'background')
    # The background sample shows both ways of giving one, and each is enough alone.
    job, school = MESSAGES['cv_fact_background_sample'][index].split(' — ')
    assert has(job, 'background') and has(school, 'background')
    sample = MESSAGES['cv_fact_contact_sample'][index]
    assert 'example.com' in sample and '90 123 45 67' in sample


def test_every_fact_has_its_label_in_every_language():
    for fact in (*REQUIRED_FACTS, *OPTIONAL_FACTS):
        labels = MESSAGES[f'cv_fact_{fact}']
        assert all(label.strip() for label in labels) and len(set(labels)) == 3, fact


# --- The parity corpus -----------------------------------------------------------------------------
# contracts/cv_fact_cases.json is the server's answer on every description of fact_cases, for the web's ticks to be
# held to (manage.py export_cv_fact_cases): like the public contract, it is what the command writes now.

def test_the_parity_corpus_is_what_the_server_says_now():
    from apps.studio.management.commands.export_cv_fact_cases import payload
    assert (ROOT / 'contracts' / 'cv_fact_cases.json').read_text(encoding='utf-8') == payload(), (
        'Run manage.py export_cv_fact_cases and copy contracts/cv_fact_cases.json to the web')


def test_the_parity_corpus_holds_every_case_here_every_example_and_the_reviewed_briefs():
    from apps.studio.cv import fact_cases
    texts = fact_cases.texts()
    assert texts == sorted(set(texts))
    samples = [text for key, row in MESSAGES.items() if key.startswith('cv_') and key.endswith('_sample') for text in row]
    assert samples
    for text in [*(text for text, _ in CONTACTS), *(text for text, _ in BACKGROUNDS), *(text for *_, text in BRIEFS),
                 *WEB_PLACEHOLDERS, *(text for row in PROMPT_EXAMPLES[CV] for text in row), *samples]:
        assert text in texts, text
    assert len(fact_cases.REVIEWED) >= 300 and set(fact_cases.REVIEWED) <= set(texts)
    path = ROOT / 'contracts' / 'cv_fact_cases.json'
    rows = json.loads(path.read_text(encoding='utf-8'))
    assert [row['text'] for row in rows] == texts and path.stat().st_size < 400_000
    assert all(sorted(row) == ['background', 'contact', 'name', 'text'] for row in rows)
    assert all(isinstance(row[fact], bool) for row in rows for fact in REQUIRED_FACTS)
    # It is the server's own answer: a name in a draft made from the text, and the facts the text gives.
    sample = next(row for row in rows if row['text'] == 'Aziz Karimov. 24 yosh. 3 yillik tajriba. 901234567')
    assert sample == {'text': sample['text'], 'name': True, 'contact': True, 'background': True}


# --- Linear time -----------------------------------------------------------------------------------
# A description can be as long as the plan allows (tens of thousands of characters), and a customer, or a
# script, can send anything: the facts are read in time that grows with it, not with its square.

ADVERSARIAL = {
    'names': 'Men ' * 20000, 'years': '2019 ' * 20000, 'schools': 'universitet ' * 20000, 'brief': BRIEF * 60,
    'letters': 'a' * 240000, 'digits': '1' * 240000, 'numbers': '1 ' * 120000, 'ats': '@' * 240000,
    'emails': 'a@' * 120000, 'plus': '+' * 240000, 'dots': 'a.' * 120000, 'brackets': '(' * 240000,
    'dashes': '- ' * 120000, 'wishes': 'looking for ' * 20000, 'births': "tug'ilgan 2019 " * 20000,
    'born': '2019 born ' * 20000, 'periods': '2019-2022 ' * 24000, 'lines': '\n'.join(['2019 - 2020 abc'] * 20000),
    'phones': '+998 90 123 45 67 ' * 10000, 'none': 'no experience ' * 20000, 'prices': "1 000 000 so'm " * 16000,
    'verbs': 'work company ' * 20000, 'years of work': 'work 2019 ' * 30000, 'cyrillic': 'ё' * 240000,
    # What the clause rules read around each match: a course, a project, a marriage, a state of life, a dream, a
    # graduation, a label's colon at the end of a line.
    'courses': 'курсы 6 месяцев ' * 8000, 'course clauses': '5 лет, курс, ' * 10000,
    'course starts': 'курс с 2019 года ' * 7500, 'projects': "loyiha do'kon 2019 " * 6500,
    'marriages': 'женат 7 лет ' * 11000, 'states': '5 лет в декрете ' * 8000, 'dreams': 'my dream 2026 ' * 9000,
    'graduations': 'окончил курс ' * 10000, 'labels': 'Стаж:\n5 лет\n' * 10000,
    # A hobby beside a length or a start, the day one can start from, and a course one taught on.
    'hobbies': 'hobby 5 years, ' * 8000, 'hobby starts': 'хобби с 2019 года, ' * 6000,
    'availability': 'available from 2025 ' * 6000, 'start days': '2025 dan boshlab ishlay olaman ' * 4000,
    'course teachers': 'Преподаватель курсов, 5 лет, ' * 4000,
}


@pytest.mark.parametrize('text', ADVERSARIAL.values(), ids=ADVERSARIAL.keys())
def test_the_facts_are_read_in_time_that_grows_with_the_text(text):
    started = time.monotonic()
    facts(text, name=True)
    assert time.monotonic() - started < 1.5


# The most a description and its files may hold (domain.limits 'source_chars'), filled with what once made a rule
# try every split of a run of blanks, or of a chain of digit groups, before it failed: a word a rule starts with,
# then the same character over and over, then one that ends nothing.
CAP = 130_000
HOSTILE = {
    'digit, spaces': ('5', ' ', 'x'), 'digit, tabs': ('1', '\t', 'x'), 'digit, spaces and tabs': ('1', ' \t', 'x'),
    'digit, no-break spaces': ('5', ' ', 'x'), 'course number': ('3 -', ' ', 'x'),
    'experience': ('experience', ' ', 'x'), 'work experience': ('work experience', ' ', 'x'),
    'experience, tabs': ('experience', '\t', 'x'), 'experience, lines': ('experience', '\n', 'x'),
    'tajriba': ('tajriba', ' ', 'x'), 'опыт': ('опыт', ' ', 'x'), 'стаж': ('стаж', ' ', 'x'),
    'no experience': ('no experience', ' ', 'x'), 'образование': ('образование', ' ', 'x'),
    "ma'lumot": ("ma'lumot", ' ', 'x'), 'plus': ('+998', ' ', 'x'), 'year': ('2019', ' ', 'x'),
    'year, dash': ('2019 -', ' ', 'x'), 'since': ('since', ' ', 'x'), 'birth': ("tug'ilgan", ' ', 'x'),
    'wish': ('Looking for', ' ', 'x'), 'ru wish': ('Ищу работу', ' ', 'x'), 'licence': ("driver's license", ' ', 'x'),
    'passport': ('pasport raqami', ' ', 'x'), 'cue': ('Tel', ' ', 'x'), 'name': ('Dilnoza Karimova', ' ', 'x'),
    'name, comma': ('Dilnoza Karimova,', ' ', 'x'), 'name, tabs': ('Dilnoza Karimova', '\t', 'x'),
    'introduced name': ('Men Dilnoza Karimova', ' ', 'x'), 'label': ('Ism:', ' ', 'x'), 'я': ('Я', ' ', 'x'),
    'company': ('Artel', ' ', 'x'), 'three-digit groups': ('', '123 ', ''), 'thousands': ('1', ' 000', ''),
    'thousands, currency': ('1', ' 000', " so'm"), 'durations with dashes': ('', '5 - ', ''),
    'dashes': ('5', ' -', 'x'), 'commas': ('5 yil', ',', 'x'),
}


@pytest.mark.parametrize('head,unit,tail', HOSTILE.values(), ids=HOSTILE.keys())
def test_a_description_as_long_as_one_may_be_is_checked_in_time_whatever_it_holds(head, unit, tail):
    payload = payload_of(head + unit * ((CAP - len(head) - len(tail)) // len(unit)) + tail)
    started = time.monotonic()
    require_facts({}, CV, payload, refuse=False)
    assert time.monotonic() - started < 1.5


def test_the_same_text_always_gives_the_same_facts_whatever_order_its_lines_come_in():
    assert [facts(BRIEF) for _ in range(3)] == [facts(BRIEF)] * 3
    assert facts(BRIEF) == facts('\n'.join(reversed(BRIEF.split('\n'))))


# --- The check ---------------------------------------------------------------------------------------

def test_a_cv_lacking_a_required_fact_is_refused_with_what_it_lacks_and_what_it_could_have():
    payload = payload_of('Dilnoza Karimova, +998 90 123 45 67')
    with pytest.raises(DomainError) as refused:
        require_facts({}, CV, payload)
    assert refused.value.code == 'cv_missing' and refused.value.status == 400
    assert refused.value.params == {'missing': ['background'], 'optional_missing': list(OPTIONAL_FACTS)}
    # The draft says the same, for the review, whether or not the customer insisted.
    assert payload['cv_facts'] == {'given': ['name', 'contact'], **refused.value.params}
    insisted = payload_of('Dilnoza Karimova, +998 90 123 45 67')
    require_facts({}, CV, insisted, refuse=False)
    assert insisted['cv_facts'] == payload['cv_facts']
    # Nothing missing: nothing raised, and the optional facts given are listed in the order they are shown.
    whole = payload_of(BRIEF, options={'portrait_asset_id': 'a-photo'})
    require_facts({}, CV, whole)
    assert whole['cv_facts']['missing'] == [] and whole['title'] == whole['content']['title'] == 'Dilnoza Karimova'
    assert whole['cv_facts']['given'] == ['name', 'contact', 'background', 'location', 'skills', 'languages', 'links',
                                          'photo']
    assert whole['cv_facts']['optional_missing'] == ['target', 'birth', 'certificates', 'projects']


def test_only_a_new_cv_is_asked_for_its_facts():
    document = payload_of('The water cycle')
    require_facts({}, DOCUMENT, document)
    assert 'cv_facts' not in document
    change = payload_of('Make it shorter', revision={'request': 'Make it shorter', 'source_draft_id': 'x'})
    require_facts({}, CV, change)
    assert 'cv_facts' not in change and change['title'] == 'Untitled document'


def test_a_title_typed_by_hand_is_kept_when_the_description_was_not_reworded():
    payload = payload_of(BRIEF, title='My CV for banks')
    require_facts({}, CV, payload, refuse=False, retitle=False)
    assert payload['title'] == 'My CV for banks' and payload['cv_facts']['missing'] == []
    require_facts({}, CV, payload, refuse=False)
    assert payload['title'] == 'Dilnoza Karimova'


def test_the_check_is_still_known_by_the_name_it_had_when_it_asked_only_for_the_name():
    assert cv_content.require_name is require_facts


@pytest.mark.parametrize('locale,words', [('en', 'full name'), ('uz', 'to‘liq ism'), ('ru', 'имя и фамилия')])
def test_the_refusal_is_said_in_every_language_with_its_facts_in_the_params(locale, words):
    refused = DomainError('cv_missing', 400, {'missing': ['name', 'contact'], 'optional_missing': ['photo']})
    data = error_data(refused, locale)
    assert data['code'] == 'cv_missing' and data['message_key'] == 'errors.cv_missing'
    assert data['message_params'] == {'missing': ['name', 'contact'], 'optional_missing': ['photo']}
    assert words in data['message'] and data['message'] != error_data(DomainError('invalid_request'), locale)['message']
    messages = json.loads((ROOT / 'i18n' / f'{locale}.json').read_text(encoding='utf-8'))
    assert 'cv_missing' in messages and 'cv_name_required' not in messages


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_the_bot_names_each_required_fact_that_is_missing_and_echoes_nothing_else(locale):
    from telegram.errors import COPY
    refused = DomainError('cv_missing', 400, {'missing': ['background', '<b>name</b>', 'name', 'contact', 5, 'photo'],
                                              'optional_missing': ['photo']})
    text = bot_error(refused, locale)
    labels = [MESSAGES[f'cv_fact_{fact}'][('en', 'uz', 'ru').index(locale)] for fact in REQUIRED_FACTS]
    assert text == '\n'.join([COPY[locale]['cv_missing'], *(f'• {label}' for label in labels)])
    assert '<' not in text and 'photo' not in text.lower().split('\n', 1)[1]
    # Without the facts, only the sentence; with a wrong shape, the same.
    for params in ({}, {'missing': 'name'}, {'missing': None}):
        assert bot_error(DomainError('cv_missing', 400, params), locale) == COPY[locale]['cv_missing']
    assert 'cv_name_required' not in COPY[locale]


# --- The draft and the studio ------------------------------------------------------------------------

def api(customer, method, path, data=None):
    """The API's answer to `method` on `path` as the customer, with `data` as the JSON body."""
    return getattr(login_client(customer), method)(f'/api/v1{path}', data=json.dumps(data) if data else None,
                                                   content_type='application/json')


@pytest.mark.django_db
def test_the_draft_says_what_it_gives_and_lacks_when_made_read_and_changed(customer):
    created = api(customer, 'post', '/generation/drafts', {'feature_id': CV, 'prompt': BRIEF})
    assert created.status_code == 201, created.content
    draft = created.json()
    expected = {'given': ['name', 'contact', 'background', 'location', 'skills', 'languages', 'links'],
                'missing': [], 'optional_missing': ['target', 'birth', 'certificates', 'projects', 'photo']}
    assert draft['cv_facts'] == expected
    assert api(customer, 'get', f"/generation/drafts/{draft['id']}").json()['cv_facts'] == expected
    # Another template, another language or a hand-typed title keeps it, though the payload is rebuilt each time.
    path = f"/generation/drafts/{draft['id']}"
    version = draft['version']
    for change in ({'output_locale': 'ru'}, {'options': {**draft['options'], 'cv_template': 'lab'}},
                   {'title': 'My CV for banks'}, {'output_locale': 'uz'}):
        response = api(customer, 'patch', path, {'version': version, **change})
        assert response.status_code == 200, response.content
        assert response.json()['cv_facts'] == expected, change
        version = response.json()['version']
    assert response.json()['title'] == 'My CV for banks'
    # The setup screen's template pick keeps it too.
    setup = api(customer, 'post', f'{path}/setup', {'cv_template': 'classic_navy'})
    assert setup.status_code == 200, setup.content
    assert setup.json()['draft']['cv_facts'] == expected
    # A reworded description is read again, and its title follows its name.
    reworded = api(customer, 'patch', path, {'version': setup.json()['draft']['version'],
                                             'prompt': 'Malika Yusupova. Phone +998 90 123 45 67'})
    assert reworded.status_code == 200, reworded.content
    shown = reworded.json()
    assert shown['title'] == 'Malika Yusupova'
    assert shown['cv_facts'] == {'given': ['name', 'contact'], 'missing': ['background'],
                                 'optional_missing': list(OPTIONAL_FACTS)}
    # An update is never refused for what it lacks: the draft was accepted when it was made.
    assert api(customer, 'patch', path, {'version': shown['version'], 'output_locale': 'en'}).status_code == 200


@pytest.mark.django_db
def test_a_customer_who_gave_every_fact_in_their_own_words_gets_the_draft(customer):
    # The ways of saying them that were once refused: an age before a length of service, a birth year run on into
    # a job's, a wish run on into experience, a name or a job that begins like an id word before the phone, a
    # school finished with no year, Uzbek in Cyrillic, a trade the lists do not know, "N лет" beside a title.
    for prompt in ('Aziz Karimov. 24 yosh. 3 yillik tajriba. 901234567',
                   "Aziz Karimov. Men 1998 yilda tug'ilganman 2019 yildan beri ishlayman. 901234567",
                   'Дильноза Каримова, +998 90 123 45 67. Ищу работу менеджером опыт 3 года',
                   'Иванова Инна, +7 916 123-45-67, бухгалтер в ООО Прогресс с 2015 года',
                   'Rustamova Dilnoza, hisobchi, +998 90 123 45 67, 2018-yildan beri Artelda ishlayman',
                   'Ismim Botir Tojiyev. Universitetni tugatganman. Telefon: +998 90 999 88 77',
                   'Мен Азиз Каримов, 5 йил ишлаганман. Тел: 901234567',
                   'Dilnoza Karimova, +998 90 123 45 67. Since 2019 hairdresser.',
                   'Сардор Алиев, +998 90 123 45 67. Кассир, 3 года.'):
        response = api(customer, 'post', '/generation/drafts', {'feature_id': CV, 'prompt': prompt})
        assert response.status_code == 201, (prompt, response.content)
        assert response.json()['cv_facts']['missing'] == [], prompt


@pytest.mark.django_db
def test_a_customer_who_insists_gets_the_draft_with_what_it_lacks(customer):
    thin = {'feature_id': CV, 'prompt': 'Dilnoza Karimova'}
    refused = api(customer, 'post', '/generation/drafts', thin)
    assert refused.status_code == 400
    error = refused.json()['error']
    assert error['code'] == 'cv_missing' and error['message_params']['missing'] == ['contact', 'background']
    insisted = api(customer, 'post', '/generation/drafts', {**thin, 'options': {'topic_given': True}})
    assert insisted.status_code == 201
    assert insisted.json()['cv_facts']['missing'] == ['contact', 'background']
    assert insisted.json()['cv_facts']['given'] == ['name']
    # A phone and a job added by an update take them off the list.
    path = f"/generation/drafts/{insisted.json()['id']}"
    fixed = api(customer, 'patch', path, {'version': insisted.json()['version'],
                                          'prompt': 'Dilnoza Karimova, +998 90 123 45 67, cashier at Makro, 2021-2024'})
    assert fixed.json()['cv_facts']['missing'] == []


@pytest.mark.django_db
def test_a_photo_is_one_of_the_facts_a_cv_gives_and_a_document_has_none(customer):
    from tests.test_cv_content import portrait
    jpeg = portrait(customer)
    draft = create_draft(customer, {'feature_id': CV, 'prompt': BRIEF, 'options': {'portrait_asset_id': str(jpeg.id)}})
    assert 'photo' in unpack(draft.encrypted_data)['cv_facts']['given']
    plain = create_draft(customer, {'feature_id': CV, 'prompt': BRIEF})
    assert 'photo' in unpack(plain.encrypted_data)['cv_facts']['optional_missing']
    attached = update_draft(customer, plain.id, {'version': plain.version, 'options': {
        **unpack(plain.encrypted_data)['options'], 'portrait_asset_id': str(jpeg.id)}})
    assert 'photo' in unpack(attached.encrypted_data)['cv_facts']['given']
    document = create_draft(customer, {'feature_id': DOCUMENT, 'prompt': 'A guide to tides'})
    assert 'cv_facts' not in unpack(document.encrypted_data)


@pytest.mark.django_db
def test_a_file_made_cv_is_asked_only_for_what_its_file_and_notes_do_not_give(customer):
    from tests.test_cv_sources import _lines, _pdf, uploaded
    bare = uploaded(customer, 'bare.pdf', _pdf(lambda page, _: _lines(page, 60, 780, [
        ('Helvetica-Bold', 20, 'Timur Rakhimov', 24), ('Helvetica', 11, 'Mechanical engineer, Samarkand', 16),
        ('Helvetica', 11, 'Skills: CAD, gearbox design, finite element analysis, project planning, quality control', 16),
        ('Helvetica', 11, 'Languages: Uzbek, Russian, English', 16)])))
    request = {'feature_id': CV, 'source_ids': [str(bare.id)], 'options': {'cv_source': 'file'}}
    with pytest.raises(DomainError) as asked:
        create_draft(customer, request)
    assert asked.value.code == 'cv_missing' and asked.value.params['missing'] == ['contact', 'background']
    # The notes beside the file count as much as the file does.
    notes = 'Phone +998 91 765 43 21. Lead engineer at Example Motors since 2020.'
    draft = create_draft(customer, {**request, 'prompt': notes})
    assert unpack(draft.encrypted_data)['cv_facts']['missing'] == []
    assert unpack(draft.encrypted_data)['title'] == 'Timur Rakhimov'


@pytest.mark.django_db
def test_the_studio_config_lists_the_facts_a_cv_is_made_of(settings):
    from tests.test_platform import account
    settings.DEBUG = True
    features = {f['id']: f for f in login_client(account()).get('/api/v1/studio/config').json()['features']}
    assert features[CV]['cv_facts'] == {'required': list(REQUIRED_FACTS), 'optional': list(OPTIONAL_FACTS)}
    assert 'cv_facts' not in features[DOCUMENT]


def test_the_bot_reads_what_a_draft_gives_and_lacks():
    from types import SimpleNamespace
    from telegram import generation
    facts_of = generation.facts_of
    found = {'given': ['name'], 'missing': ['contact', 'background'], 'optional_missing': ['photo']}
    assert facts_of(SimpleNamespace(encrypted_data=pack({'cv_facts': found}))) == found
    # A change is decided by its request alone, and an older draft never had them.
    assert facts_of(SimpleNamespace(encrypted_data=pack({'cv_facts': found, 'revision': {'request': 'x'}}))) == {}
    assert facts_of(SimpleNamespace(encrypted_data=pack({'title': 'x'}))) == {}
    assert 'cv_missing' in generation.READ_REFUSALS and 'cv_name_required' not in generation.READ_REFUSALS


def test_the_public_contract_describes_the_facts():
    contract = json.loads((ROOT / 'contracts' / 'public.openapi.json').read_text())
    draft = contract['components']['schemas']['GenerationDraft']['properties']['cv_facts']
    assert sorted(draft['properties']) == ['given', 'missing', 'optional_missing']
    assert 'cv_facts' not in contract['components']['schemas']['GenerationDraft']['required']
    config = contract['paths']['/studio/config']['get']['responses']['200']['content']['application/json']['schema']
    assert '"cv_facts"' in json.dumps(config)
