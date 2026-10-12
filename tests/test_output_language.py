"""Which language a document is written in.

A customer's app language, their settings, a language their description asks
for, one they picked on the review screen and — for a change — the document's
own language all have a say. apps/studio/language.py decides between them once,
when the draft is prepared, and the draft keeps the answer beside what decided
it (`locale_source`). Uzbek is always written in Latin letters, whatever
alphabet the description was typed in.

Most of these go through create_draft and update_draft the way the studio and
the bot do; the reading of a description is also checked on its own, through
language.explicit and language.resolve, because that is where a topic ("women
in Russian history") must not be mistaken for an instruction ("in Russian").
"""
import json

import pytest

from apps.core.errors import DomainError
from apps.studio import language
from apps.studio.domain import DOCUMENT, SLIDES, create_draft, pack, unpack, update_draft
from apps.studio.models import GenerationDraft
from tests.test_platform import account
from tests.test_revisions import generated
from tests.test_studio import paid

pytestmark = pytest.mark.django_db

ENGLISH_DECK = 'Create a 20-slide presentation about artificial intelligence in English.'
UZBEK_DECK = 'Menga O‘zbekiston iqtisodiyoti haqida o‘zbek tilida 15 ta slayd tayyorlab ber.'
RUSSIAN_DOCUMENT = 'Подготовь подробный документ об истории медицины на русском языке.'


def customer(app='en', preferences=None):
    """A customer whose app is in `app`, with these settings."""
    a = account()
    a.locale = app
    a.preferences = preferences or {}
    a.save(update_fields=['locale', 'preferences'])
    return a


def language_of(draft):
    """(language, what decided it, Uzbek alphabet) as the draft stored them."""
    payload = unpack(draft.encrypted_data)
    return payload['output_locale'], payload['locale_source'], payload['options']['uz_script']


@pytest.fixture(autouse=True)
def offline_authoring(settings):
    """Drafts are authored with the local fixture standing in for the model."""
    settings.DEBUG = True


@pytest.fixture
def premium(settings):
    return paid(settings, account())


# --- The owner's table, through create_draft ----------------------------------

@pytest.mark.parametrize('app,service,prompt,expected,source', [
    ('uz', SLIDES, 'O‘zbekiston tarixi haqida 10 ta slayd tayyorlab ber.', 'uz', 'settings'),
    ('en', DOCUMENT, 'A short guide to renewable energy for school pupils.', 'en', 'settings'),
    ('ru', DOCUMENT, 'Create a PDF about cybersecurity.', 'ru', 'settings'),
    ('uz', SLIDES, ENGLISH_DECK, 'en', 'prompt'),
    ('en', SLIDES, UZBEK_DECK, 'uz', 'prompt'),
    ('ru', SLIDES, UZBEK_DECK, 'uz', 'prompt'),
    ('uz', DOCUMENT, RUSSIAN_DOCUMENT, 'ru', 'prompt'),
    ('ru', SLIDES, ENGLISH_DECK, 'en', 'prompt'),
    ('uz', SLIDES, 'Ўзбекистон иқтисодиёти ҳақида 10 та слайд', 'uz', 'settings'),
    ('en', SLIDES, 'Create a presentation about the role of women in Russian history', 'en', 'settings'),
], ids=[
    'uzbek-app-no-language-named', 'english-app-no-language-named', 'russian-app-english-prompt',
    'uzbek-app-asks-english', 'english-app-asks-uzbek', 'russian-app-asks-uzbek', 'uzbek-app-asks-russian',
    'russian-app-asks-english', 'uzbek-app-cyrillic-uzbek-prompt', 'english-app-russian-history-topic',
])
def test_the_output_language_follows_the_owners_table(app, service, prompt, expected, source):
    draft = create_draft(customer(app), {'feature_id': service, 'prompt': prompt})
    assert language_of(draft) == (expected, source, 'latn')


def test_uzbek_is_written_in_latin_even_when_an_old_client_asks_for_cyrillic():
    draft = create_draft(customer('uz'), {'feature_id': SLIDES, 'prompt': 'Ўзбекистон иқтисодиёти ҳақида 10 та слайд',
                                          'options': {'uz_script': 'cyrl'}})
    assert language_of(draft) == ('uz', 'settings', 'latn')


def test_the_resolved_language_is_what_the_model_is_told():
    from apps.studio.provider import request_body
    draft = create_draft(customer('uz'), {'feature_id': SLIDES, 'prompt': 'Ўзбекистон иқтисодиёти ҳақида 10 та слайд'})
    body = request_body({'model': 'gpt-5.6-luna'}, unpack(draft.encrypted_data), SLIDES)
    sent = json.loads(body['input'])
    assert (sent['output_locale'], sent['output_language'], sent['output_script']) == ('uz', 'Uzbek', 'latin')
    # Said last, so the long instructions before it stay a shared cached prefix.
    assert body['instructions'].endswith(language.instructions('uz'))


# --- Settings, the request and the fallback -----------------------------------

def test_the_output_language_in_settings_beats_the_app_language():
    draft = create_draft(customer('uz', {'output_locale': 'ru'}), {'prompt': 'A guide to solar panels.'})
    assert language_of(draft)[:2] == ('ru', 'settings')


def test_the_language_sent_with_the_request_beats_the_settings():
    draft = create_draft(customer('uz', {'output_locale': 'uz'}),
                         {'prompt': 'A guide to solar panels.', 'output_locale': 'ru'})
    assert language_of(draft)[:2] == ('ru', 'request')


@pytest.mark.parametrize('app,preferences', [('de', {}), ('', {'output_locale': 'fr'}), ('xx', [])],
                         ids=['unknown-app-language', 'unknown-preference', 'malformed-preferences'])
def test_english_when_nothing_valid_says_otherwise(app, preferences):
    draft = create_draft(customer(app, preferences), {'prompt': 'A guide to solar panels.'})
    assert language_of(draft)[:2] == ('en', 'default')


@pytest.mark.parametrize('requested', ['fr', 'de', 'uz-Cyrl', ''])
def test_an_unsupported_output_language_is_refused(requested):
    with pytest.raises(DomainError) as refused:
        create_draft(customer('uz'), {'prompt': 'A guide to solar panels.', 'output_locale': requested})
    assert refused.value.code == 'invalid_locale'


# --- A picked language, and a description written in Russian -----------------

def test_a_picked_language_beats_one_the_description_names():
    a = customer('uz')
    picked = create_draft(a, {'feature_id': SLIDES, 'prompt': ENGLISH_DECK, 'output_locale': 'ru',
                              'options': {'locale_chosen': True}})
    assert language_of(picked)[:2] == ('ru', 'picked')
    # Without the pick, the same language sent along is only the request, and
    # the description's own wins.
    sent = create_draft(a, {'feature_id': SLIDES, 'prompt': ENGLISH_DECK, 'output_locale': 'ru'})
    assert language_of(sent)[:2] == ('en', 'prompt')


def test_a_pick_flag_without_a_language_picks_nothing():
    draft = create_draft(customer('uz'), {'prompt': ENGLISH_DECK, 'options': {'locale_chosen': True}})
    assert language_of(draft)[:2] == ('en', 'prompt')


@pytest.mark.parametrize('sent', [None, 'uz'], ids=['nothing-sent', 'app-language-sent'])
def test_a_description_written_in_russian_is_answered_in_russian_even_in_an_uzbek_app(sent):
    data = {'feature_id': SLIDES, 'prompt': 'Сделай презентацию о солнечной энергии для школьников, 10 слайдов.'}
    if sent:
        data['output_locale'] = sent
    assert language_of(create_draft(customer('uz'), data))[:2] == ('ru', 'prompt_language')


def test_uzbek_typed_in_cyrillic_is_not_taken_for_russian():
    for prompt in ('Ўзбекистон иқтисодиёти ҳақида 10 та слайд',
                   'Менга сунъий интеллект ҳақида тақдимот тайёрлаб беринг'):
        assert not language.written_in_russian(prompt), prompt
    assert language.written_in_russian('Расскажи про историю Самарканда для школьников.')


# --- Mixed languages and more than one language named -------------------------

@pytest.mark.parametrize('app,prompt,expected', [
    ('uz', 'Menga sun’iy intellekt haqida presentation tayyorla in English', 'en'),
    ('ru', 'Write in English about how Russian is taught', 'en'),
    ('en', 'Сделай презентацию о космосе по-узбекски', 'uz'),
    ('en', 'Создай презентацию о России на узбекском языке', 'uz'),
    ('ru', 'Prezentatsiya: kosmos. Til: ingliz', 'en'),
])
def test_a_language_named_in_a_mixed_language_description_is_followed(app, prompt, expected):
    assert language_of(create_draft(customer(app), {'prompt': prompt}))[:2] == (expected, 'prompt')


@pytest.mark.parametrize('prompt,expected', [
    ('Write it in Russian, then add an English version.', 'ru'),
    ('Make it in English. Actually, in Russian.', 'en'),
    ("O'zbek tilida taqdimot tayyorla, ingliz tilida emas", 'uz'),
    ('Make a presentation in Uzbek about Russian literature', 'uz'),
    ('Create slides in English for Russian students', 'en'),
])
def test_the_earliest_language_named_wins(prompt, expected):
    assert language.explicit(prompt) == expected


def test_the_earliest_language_named_wins_through_create_draft():
    draft = create_draft(customer('uz'), {'prompt': 'Write it in Russian, then add an English version.'})
    assert language_of(draft)[:2] == ('ru', 'prompt')


# --- Reading a description: instructions and topics ---------------------------

@pytest.mark.parametrize('prompt,expected', [
    ('A report on tides in English.', 'en'),
    ('Slides about AI in the English language', 'en'),
    ('Presentation about AI in English, please', 'en'),
    ('Space exploration presentation — in English', 'en'),
    ('Make 10 slides in English about space', 'en'),
    ('Translate the history of Samarkand into Uzbek', 'uz'),
    ('Russian version please', 'ru'),
    ('Language: Russian', 'ru'),
    ('ingliz tilida qil', 'en'),
    ('inglizcha slayd tayyorla', 'en'),
    ("Prezentatsiya rus tilida bo'lsin", 'ru'),
    ('Ingliz tilida sun’iy intellekt haqida 10 ta slayd', 'en'),
    ('Ўзбекистон иқтисодиёти ҳақида инглиз тилида 10 та слайд тайёрла', 'en'),
    ('Подготовь доклад на английском', 'en'),
    ('Напиши реферат по-английски о космосе', 'en'),
    (RUSSIAN_DOCUMENT, 'ru'),
    (UZBEK_DECK, 'uz'),
    # Every way Uzbek types its o‘.
    ("Kosmos haqida o'zbek tilida yoz", 'uz'),
    ('Kosmos haqida oʻzbek tilida yoz', 'uz'),
    ('Kosmos haqida o`zbek tilida yoz', 'uz'),
    ('Kosmos haqida ózbek tilida yoz', 'uz'),
])
def test_an_output_language_the_description_asks_for_is_read(prompt, expected):
    assert language.explicit(prompt) == expected


@pytest.mark.parametrize('prompt', [
    'Create a presentation about the role of women in Russian history',
    'history of the English language',
    'An essay about English literature',
    'Russian language teaching methods',
    'The impact of Russian on Uzbek vocabulary',
    'In Russian schools pupils learn English',
    'Uzbek literature in the 20th century',
    'the English Channel crossing',
    "Rus tilida fe'l zamonlari haqida",
    "Rus tilida fe'l zamonlari haqida 10 ta slayd tayyorlab ber",
    'Xitoy tilida omonimlar',
    'Ingliz tilida omonimlar haqida slayd',
    'Rus tilida yozilgan adabiyot haqida referat',
    'Rus tilida gapiradigan aholi haqida referat',
    'Ingliz tilida so‘zlashuvchi mamlakatlar haqida',
    'Ingliz tili grammatikasi haqida slayd',
    'Rus tili darslari uchun taqdimot',
    'Стратегия выхода на русский рынок',
    'Расскажи про бизнес на русском рынке',
    'Анализ продаж на английском рынке',
    'Презентация про английский язык',
])
def test_a_language_that_is_the_subject_is_not_an_instruction(prompt):
    assert language.explicit(prompt) is None


@pytest.mark.parametrize('prompt,expected', [
    ('Kosmos haqida ingliz tilida taqdimot', 'en'),
    ('Kosmos haqida rus tilida referat.', 'ru'),
    ('Ingliz tilida 10 ta slayd', 'en'),
    ('rus tilida 10 ta slayd', 'ru'),
    ('Uzbek tilida taqdimot', 'uz'),
    ('Ingliz tilida 5 betlik referat', 'en'),
    ('Ўзбекистон иқтисодиёти ҳақида инглиз тилида слайд', 'en'),
])
def test_an_uzbek_language_request_ending_in_a_format_word_is_read(prompt, expected):
    assert language.explicit(prompt) == expected


@pytest.mark.parametrize('prompt', [
    'Create a presentation about education in English-speaking countries',
    'Freedom of the press in Russian-language media',
    'Recent changes in Russian-Uzbek trade relations',
])
def test_a_hyphenated_compound_after_the_language_is_a_subject(prompt):
    assert language.explicit(prompt) is None


@pytest.mark.parametrize('prompt', [
    'Create a presentation about the role of women in Russian and Soviet history',
    'Women in Russian, Soviet and post-Soviet history',
])
def test_a_subject_with_two_adjectives_is_still_a_subject(prompt):
    assert language.explicit(prompt) is None


def test_an_uzbek_request_for_english_slides_is_followed_in_a_russian_app():
    draft = create_draft(customer('ru'), {'feature_id': SLIDES, 'prompt': 'Kosmos haqida ingliz tilida taqdimot'})
    assert language_of(draft)[:2] == ('en', 'prompt')


@pytest.mark.parametrize('prompt,expected', [
    ('English language da', 'en'),
    ('Inglizchada', 'en'),
    ('inglizchada yoz', 'en'),
    ('ruscha da', 'ru'),
    ("o'zbekcha", 'uz'),
    ('Uzbek tilida', 'uz'),
    ('in uzbek language', 'uz'),
    ('make it in uzbek latin script', 'uz'),
    ('in english 10 slides about climate', 'en'),
    ('A presentation about climate in English 10 slides', 'en'),
    ('Сделай презентацию на английском 10 слайдов', 'en'),
    ('Сделай презентацию на английском', 'en'),
    ('Нужна презентация на узбекском', 'uz'),
    ('написать по русски', 'ru'),
    ('Slides in English (10)', 'en'),
])
def test_more_ways_of_naming_the_output_language_are_read(prompt, expected):
    assert language.explicit(prompt) == expected


# --- Translating, and a translation beside the text --------------------------------

@pytest.mark.parametrize('prompt,expected', [
    ('ingliz tiliga tarjima qil', 'en'),
    ("Ingliz tiliga o'gir", 'en'),
    ("Bu bo'limni ingliz tiliga o'tkazing", 'en'),
    ('inglizchaga tarjima qiling', 'en'),
    ("o'zbek tiliga tarjima qiling", 'uz'),
    ('translate it to English', 'en'),
    ('translate to russian', 'ru'),
    ('Переведи на английский', 'en'),
    ('Make an English version', 'en'),
])
def test_a_request_to_translate_names_the_language(prompt, expected):
    assert language.explicit(prompt) == expected
    # On a document in another language it is the change asked for.
    assert language.resolve(prompt, document='uz' if expected != 'uz' else 'ru').locale == expected


@pytest.mark.parametrize('prompt', [
    'Add the English translation of each term',
    "Har bir atamaning inglizcha tarjimasini qo'shing",
    'Add an English version of the abstract at the end',
    'Atamalarning ruscha tarjimasini qavs ichida bering',
    'Rus tiliga tarjima qilmang',
])
def test_a_translation_beside_the_text_does_not_change_the_documents_language(prompt):
    assert language.explicit(prompt) is None
    resolved = language.resolve(prompt, document='uz')
    assert (resolved.locale, resolved.source) == ('uz', 'document')


# --- Corrections ---------------------------------------------------------------------

@pytest.mark.parametrize('prompt', [
    'Не на русском, а на узбекском',
    'Не на русском языке, а на узбекском',
    'Not in Russian, in Uzbek please',
    'Why is it in Russian? I need it in Uzbek',
    "Nega rus tilida? O'zbek tilida kerak edi",
    "Rus tilida emas, o'zbek tilida",
])
def test_a_correction_follows_the_language_it_asks_for_not_the_one_it_rejects(prompt):
    assert language.explicit(prompt) == 'uz'
    assert language.resolve(prompt, document='ru').locale == 'uz'


# --- Topics about a language -----------------------------------------------------------

@pytest.mark.parametrize('prompt', [
    'Cases in Russian',
    'Word order in Russian',
    'Vowel harmony in Uzbek',
    'Synonyms in Uzbek',
    'Phrasal verbs in English',
    'Add a slide about loanwords in English',
    'Add a section on phrasal verbs in English',
    'Changes in the English language since 1900',
    'Neologisms in the Uzbek language',
    'Translation from English into Uzbek: problems',
    'Влияние французского на английский язык',
    'Rus tilida olmoshlar haqida',
    'Rus tilida sifatlar haqida',
    'Rus tilida padejlar haqida',
    'Ingliz tilida sifatdoshlar haqida taqdimot',
    'Ingliz tilida present simple haqida',
    'Ingliz tilida passive voice haqida taqdimot',
    "Inglizcha so'zlar o'zbek tilida",
])
def test_grammar_and_the_study_of_a_language_are_subjects(prompt):
    assert language.explicit(prompt) is None
    # Inside a change request it does not move the document either.
    assert language.resolve(prompt, document='uz').source == 'document'


def test_modern_is_not_a_grammar_word():
    # "zamon" (tense) once caught "zamonaviy" (modern).
    assert language.explicit('Ingliz tilida zamonaviy texnologiyalar haqida taqdimot') == 'en'


# --- A description written in Russian --------------------------------------------------

@pytest.mark.parametrize('prompt', [
    'Напиши реферат об истории республик СССР',
    'Глобальное потепление',
    'Экономическое развитие республик Центральной Азии',
])
def test_russian_words_ending_like_uzbek_ones_are_still_russian(prompt):
    # "-лик" is an Uzbek suffix (birlik), not the Russian "республик" or "католик".
    assert language.written_in_russian(prompt)


@pytest.mark.parametrize('prompt', [
    'Ўзбекистон иқтисодиёти ҳақида 10 та слайд',
    'Менга сунъий интеллект ҳақида тақдимот тайёрлаб беринг',
    'Мамлакатимизда ахборот хавфсизлигини таъминлаш',
    'Узбекистон Республикасининг Конституцияси',
    'Ёшлик ва бирлик ҳақида',
])
def test_uzbek_in_cyrillic_is_still_not_russian(prompt):
    assert not language.written_in_russian(prompt)


# --- Long and hostile descriptions -----------------------------------------------------

LONG = 50_000


@pytest.mark.parametrize('text', [
    'rus tilida' + ' ' * LONG + 'x',
    'rus tilida' + '\t\u00a0' * (LONG // 2) + 'x',
    'а' * LONG,
    'а' * LONG + ' и в на о с по не что',
    'a' * LONG,
    'a' * LONG + ' the and of to is are in that',
    'in English ' * (LONG // 11),
    'на русском ' * (LONG // 11),
    'not in English ' * (LONG // 15),
    'Phrasal verbs in English ' * (LONG // 25),
    ('rus tilida ' + 'a ' * 30) * (LONG // 71),
    'а ' * (LONG // 4) + '1' * (LONG // 2),
], ids=['spaces-after-tilida', 'tabs-and-nbsp', 'cyrillic-run', 'cyrillic-run-then-words', 'latin-run',
        'latin-run-then-words', 'in-english-repeated', 'na-russkom-repeated', 'negated-repeated',
        'topic-repeated', 'tilida-without-haqida', 'long-number'])
def test_reading_a_long_description_takes_linear_time(text):
    import time
    # A prompt may be 50,000 characters on the free plan; a pattern that
    # backtracks over a run of it once held a worker for minutes.
    for read in (language.explicit, language.written_in_russian, language.written_in, language.resolve):
        start = time.perf_counter()
        read(text)
        assert time.perf_counter() - start < 0.2, read.__name__


# --- The precedence itself ------------------------------------------------------

@pytest.mark.parametrize('prompt,kwargs,expected', [
    (ENGLISH_DECK, {'picked': 'ru', 'requested': 'uz', 'settings': 'uz', 'document': 'uz'}, ('ru', 'picked')),
    (ENGLISH_DECK, {'requested': 'ru', 'settings': 'ru', 'document': 'uz'}, ('en', 'prompt')),
    ('Сделай второй раздел короче.', {'requested': 'uz', 'settings': 'uz', 'document': 'en'}, ('en', 'document')),
    ('Сделай второй раздел короче.', {'requested': 'uz', 'settings': 'uz'}, ('ru', 'prompt_language')),
    ('A guide to tides.', {'requested': 'ru', 'settings': 'uz'}, ('ru', 'request')),
    ('A guide to tides.', {'settings': 'uz'}, ('uz', 'settings')),
    ('A guide to tides.', {}, ('en', 'default')),
    # Anything unsupported is passed over, not trusted.
    ('A guide to tides.', {'picked': 'fr', 'requested': 'de', 'settings': 'xx', 'document': 'kk'}, ('en', 'default')),
])
def test_each_rung_of_the_precedence(prompt, kwargs, expected):
    resolved = language.resolve(prompt, **kwargs)
    assert (resolved.locale, resolved.source) == expected
    assert resolved.script == ('cyrillic' if expected[0] == 'ru' else 'latin')


# --- A change to a finished document -------------------------------------------

@pytest.fixture
def russian_document(premium):
    """A finished Russian document whose owner has since switched the app to Uzbek."""
    premium.locale = 'ru'
    premium.save(update_fields=['locale'])
    original = generated(premium)
    assert unpack(original.encrypted_data)['output_locale'] == 'ru'
    premium.locale = 'uz'
    premium.save(update_fields=['locale'])
    return premium, original


@pytest.mark.parametrize('request_text,sent,chosen,expected', [
    ('Make the second section shorter.', None, False, ('ru', 'document')),
    ('Ikkinchi bo‘limni qisqartiring.', None, False, ('ru', 'document')),
    # The studio always sends the app language along; it does not move the document.
    ('Make the second section shorter.', 'uz', False, ('ru', 'document')),
    ('Hujjatni ingliz tilida qil.', None, False, ('en', 'prompt')),
    ('Make the second section shorter.', 'en', True, ('en', 'picked')),
], ids=['english-request', 'uzbek-request', 'app-language-sent', 'names-english', 'english-picked'])
def test_a_change_keeps_the_documents_language_unless_told_otherwise(russian_document, request_text, sent, chosen,
                                                                      expected):
    owner, original = russian_document
    data = {'prompt': request_text, 'options': {'revise_draft_id': str(original.id)}}
    if sent:
        data['output_locale'] = sent
    if chosen:
        data['options']['locale_chosen'] = True
    assert language_of(create_draft(owner, data)) == (*expected, 'latn')


def test_a_change_written_in_russian_keeps_an_english_document_english(premium):
    original = generated(premium)
    assert unpack(original.encrypted_data)['output_locale'] == 'en'
    revised = create_draft(premium, {'prompt': 'Сделай второй раздел короче и проще.',
                                     'options': {'revise_draft_id': str(original.id)}})
    assert language_of(revised)[:2] == ('en', 'document')


def test_rewording_a_change_that_named_a_language_returns_to_the_documents(russian_document):
    owner, original = russian_document
    revised = create_draft(owner, {'prompt': 'Hujjatni ingliz tilida qil.', 'options': {'revise_draft_id': str(original.id)}})
    assert language_of(revised)[:2] == ('en', 'prompt')
    reworded = update_draft(owner, revised.id, {'version': revised.version, 'prompt': 'Ikkinchi bo‘limni qisqartiring.',
                                                'output_locale': 'en'})
    assert language_of(reworded)[:2] == ('ru', 'document')


def selected_change(owner, original, prompt, **extra):
    """A change to the first page only, the way the studio's page picker sends it."""
    options = {'revise_draft_id': str(original.id), 'revise_section_ids': ['s1'],
               'revise_base_version': original.version, **extra.pop('options', {})}
    return create_draft(owner, {'prompt': prompt, 'options': options, **extra})


@pytest.mark.parametrize('prompt,extra', [
    ('Переведи этот слайд на английский', {}),
    ('Bu sahifani ingliz tilida yozing', {}),
    ('Make this page shorter.', {'output_locale': 'en', 'options': {'locale_chosen': True}}),
], ids=['translate-one-slide', 'names-english', 'english-picked'])
def test_a_change_to_selected_pages_keeps_the_documents_language(premium, prompt, extra):
    # Only the selected pages are rewritten: had the whole deck taken another
    # language, the untouched pages would come out transliterated.
    premium.locale = 'ru'
    premium.save(update_fields=['locale'])
    deck = generated(premium, feature=SLIDES, fmt='pptx')
    assert unpack(deck.encrypted_data)['output_locale'] == 'ru'
    revision = unpack(selected_change(premium, deck, prompt, **extra).encrypted_data)
    assert (revision['output_locale'], revision['locale_source']) == ('ru', 'document')
    assert revision['revision']['base_locale'] == 'ru'


def test_rewording_a_change_to_selected_pages_keeps_the_documents_language(russian_document):
    owner, original = russian_document
    revised = selected_change(owner, original, 'Bu sahifani qisqaroq qiling.')
    assert language_of(revised)[:2] == ('ru', 'document')
    # The revision's own last language is not the document's: one saved in
    # English (as a selected change could be before) is reworded in Russian.
    stale = unpack(revised.encrypted_data)
    stale.update(output_locale='en', locale_source='prompt')
    GenerationDraft.objects.filter(pk=revised.pk).update(encrypted_data=pack(stale))
    reworded = update_draft(owner, revised.id, {'version': revised.version, 'output_locale': 'en',
                                                'prompt': 'Bu sahifani ingliz tilida qisqaroq yozing.'})
    assert language_of(reworded)[:2] == ('ru', 'document')


# --- Rewording a draft ------------------------------------------------------------

@pytest.mark.parametrize('echo', [True, False], ids=['studio-echoes-the-language', 'nothing-sent'])
def test_rewording_the_description_drops_a_language_it_no_longer_names(echo):
    a = customer('uz')
    # The studio sends the app language with a new draft, and the shown one back.
    draft = create_draft(a, {'prompt': 'A presentation about solar power in English.', 'output_locale': 'uz'})
    assert language_of(draft)[:2] == ('en', 'prompt')
    change = {'version': draft.version, 'prompt': 'A presentation about solar power.'}
    if echo:
        change['output_locale'] = 'en'
    assert language_of(update_draft(a, draft.id, change))[:2] == ('uz', 'settings')


def test_rewording_a_russian_description_into_uzbek_drops_russian():
    a = customer('uz')
    draft = create_draft(a, {'prompt': 'Сделай презентацию о солнечной энергии для школьников.'})
    assert language_of(draft)[:2] == ('ru', 'prompt_language')
    reworded = update_draft(a, draft.id, {'version': draft.version, 'output_locale': 'ru',
                                          'prompt': 'Quyosh energiyasi haqida maktab o‘quvchilari uchun taqdimot.'})
    assert language_of(reworded)[:2] == ('uz', 'settings')


def test_rewording_to_name_another_language_follows_it():
    a = customer('uz')
    draft = create_draft(a, {'prompt': 'A presentation about solar power in English.'})
    reworded = update_draft(a, draft.id, {'version': draft.version, 'output_locale': 'en',
                                          'prompt': 'A presentation about solar power in Russian.'})
    assert language_of(reworded)[:2] == ('ru', 'prompt')


def test_a_picked_language_survives_rewording():
    a = customer('uz')
    draft = create_draft(a, {'prompt': 'A presentation about solar power in English.', 'output_locale': 'ru',
                             'options': {'locale_chosen': True}})
    assert language_of(draft)[:2] == ('ru', 'picked')
    for prompt in ('A presentation about solar power.', 'A presentation about solar power in English.'):
        draft = update_draft(a, draft.id, {'version': draft.version, 'prompt': prompt, 'output_locale': 'ru'})
        assert language_of(draft)[:2] == ('ru', 'picked'), prompt


def test_picking_a_language_on_a_draft_replaces_the_one_the_description_named():
    a = customer('uz')
    draft = create_draft(a, {'prompt': 'A presentation about solar power in English.'})
    options = {**unpack(draft.encrypted_data)['options'], 'locale_chosen': True}
    picked = update_draft(a, draft.id, {'version': draft.version, 'output_locale': 'ru', 'options': options})
    assert language_of(picked)[:2] == ('ru', 'picked')


def test_a_language_the_customer_sent_is_not_dropped_by_rewording():
    a = customer('en')
    draft = create_draft(a, {'prompt': 'A presentation about solar power.', 'output_locale': 'ru'})
    assert language_of(draft)[:2] == ('ru', 'request')
    reworded = update_draft(a, draft.id, {'version': draft.version, 'output_locale': 'ru',
                                          'prompt': 'A short presentation about solar power.'})
    assert language_of(reworded)[:2] == ('ru', 'request')


# --- The bot, and what the model is told -------------------------------------------

@pytest.mark.parametrize('preferences,expected', [({'output_locale': 'ru'}, 'ru'), ({}, 'uz')],
                         ids=['output-language-in-settings', 'nothing-in-settings'])
def test_the_bot_sends_the_output_language_from_settings_like_the_web(premium, preferences, expected):
    from telegram.generation import build
    premium.locale = 'uz'
    premium.preferences = preferences
    premium.save(update_fields=['locale', 'preferences'])
    draft = build(premium, DOCUMENT, 'Iqtisodiyot haqida referat')
    assert language_of(draft)[:2] == (expected, 'request')


def test_the_model_composes_in_the_target_language_rather_than_translating():
    for locale in language.SUPPORTED:
        block = language.instructions(locale)
        assert 'rather than translating a draft from another language' in block
        assert 'never draft in another language' not in block
    uzbek = language.instructions('uz')
    assert all(rule in uzbek for rule in ('maʼlumot', '2024-yil', '3,5 foiz', 'Bugungi kunda', 'IT Park'))
    russian = language.instructions('ru')
    assert all(rule in russian for rule in ('units of measurement in Russian', '«ёлочки»', 'канцелярит'))
