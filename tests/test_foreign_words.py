"""Writing Uzbek, the model slides into another language part-way through a sentence.

A bench of gpt-6-luna's Uzbek referats and mustaqil ish papers (2026-11-27,
14 documents) found every kind of drift there is: a Cyrillic ending on a Latin
word (kurashлар), whole Uzbek sentences in Cyrillic, and, in 8 of the 14,
words of Mongolian (бөгөөд, болгоно, зохицуулалт), once with Armenian letters
in the middle (պահպանлах). Uzbek in Cyrillic is the same Uzbek in the other
alphabet and is put into Latin by rule (apps/studio/scripts.py); a Mongolian
word put into Latin letters is no word at all ("bogood"), so its section goes
back to the model once, with the words named. These tests hold each kind to
its own path: the reader (language.foreign_words), the check and the repair
line (quality.py), the one repair in a whole job, a category paper's repair,
and the length top-up, which has no repair and leaves such an addition out.

The sentences are the model's own, from the bench: no customer wrote them.
"""
import copy
import json
import time

import pytest

from apps.studio import filling, language, quality, scripts
from apps.studio.domain import unpack
from tests.test_generation_quality import (by_id, customer, delivered, document, is_repair, is_top_up, model, reply,  # noqa: F401
                                           run, section, sent, slide, stages, usage, writing_calls)

# --- The model's sentences ---------------------------------------------------------

# Uzbek, Latin, as it should be.
CLEAN = ("Fotosintez yashil o‘simliklarning barglarida kechadi.\n"
         "Bargdagi xloroplastlar quyosh nurini yutib, uni kimyoviy energiyaga aylantiradi.\n"
         "Bu jarayonda karbonat angidrid va suvdan glyukoza hamda kislorod hosil bo‘ladi.")
# A Mongolian word with Mongolian letters in an Uzbek sentence.
MONGOLIAN_LETTERS = "Karbonat angidrid — havoda uchraydigan gaz бөгөөд fotosintezda uglerod manbai bo‘lib xizmat qiladi."
# Mongolian written with Russian letters alone: a doubled vowel and a case ending.
MONGOLIAN_SHAPE = "Unda karbonat angidrid эхлээд mezofill hujayralarida to‘rt uglerodli birikmaga qo‘shiladi."
# A Mongolian verb with no sign in its letters, which only its form gives away.
MONGOLIAN_WORD = "Jarayonning batafsil mexanizmi buni yanada aniq болгоно."
# Mongolian endings on Latin Uzbek words.
MONGOLIAN_TAILS = ("Bunday tartib buyruqlarni quyi bo‘g‘inlarga yetkazishni yengillashtirсэн.\n"
                   "Harbiy intizom hukmdorning siyosiy hokimiyatini mustahруулахад хизмат қилган.")
# A third script in the middle of a word.
ARMENIAN = "Bunday tartib intizomni պահպանлах учун хизмат қилган."
# Uzbek in Cyrillic: the same Uzbek, put into Latin by rule.
UZBEK_CYRILLIC = ("Бундай мосланиш иссиқ, ёруғ жойларда фотосинтезни самарали олиб боришга ёрдам беради.\n"
                  "Аммо углеродни дастлабки бириктириш учун қўшимча энергия талаб қилади.")
# Uzbek words with a Cyrillic ending, and a Latin word with one Cyrillic look-alike: all Uzbek.
UZBEK_MIXED = "Bu kurashлар o‘simlikda yangi moddалардан hosил bo‘ladi va mаktab darsligida yoziladi."


@pytest.mark.parametrize('text,words', [
    (MONGOLIAN_LETTERS, ['бөгөөд']),
    (MONGOLIAN_SHAPE, ['эхлээд']),
    (MONGOLIAN_WORD, ['болгоно']),
    (MONGOLIAN_TAILS, ['yengillashtirсэн', 'mustahруулахад']),
    (ARMENIAN, ['պահպանлах']),
    # Kazakh, Kyrgyz and Tajik letters no Uzbek or Russian word has.
    ('Bu әлем va бүгүн haqida', ['әлем', 'бүгүн']),
    ('Tojikcha ҷаҳон so‘zi', ['ҷаҳон']),
    ('RuBisCO kislorod bilan урвалд kirishadi', ['урвалд']),
    ('Metodi esa qiyosiy tahlil qilishэд оршино.', ['qilishэд', 'оршино']),
    ('Bunday зохицуулалт issiq joylarda foydali', ['зохицуулалт']),
    # A doubled vowel before a case ending, and the commonest words that show nothing in their letters.
    ('Markaziy захиргааны тухайн улс', ['захиргааны', 'тухайн', 'улс']),
    # Chinese in a Latin word.
    ('Bu jarayon no重复 tarzda kechadi', ['no重复']),
], ids=['mongolian-letters', 'mongolian-shape', 'mongolian-word', 'mongolian-endings-on-latin', 'armenian-inside',
        'kazakh-kyrgyz', 'tajik', 'mongolian-dative', 'mixed-ending-and-word', 'doubled-vowel', 'common-words',
        'chinese-inside'])
def test_each_kind_of_foreign_word_is_found(text, words):
    assert language.foreign_words(text) == words


@pytest.mark.parametrize('text', [
    CLEAN, UZBEK_CYRILLIC, UZBEK_MIXED,
    # Uzbek words Uzbek writes with a doubled vowel, in either alphabet.
    'Давлат манфаатлари, китоб мутолааси ва мудофаа ишлари. Davlat manfaatlari va kitob mutolaasi.',
    'Сиёсий, иқтисодий ва ижтимоий ҳаёт; ҳокимиятнинг ўрни эса эмас.',
    # Russian, the language an Uzbek lesson about Russian quotes.
    'Соответствие, сообщение, кооперация, доход и подход в экономике.',
    # Greek letters are science's symbols.
    'β-karotin va to‘lqin uzunligi λ = 680 nm, Δt vaqt',
    'Taʼlim, maʼnaviyat va sanʼat; o‘qituvchi g‘oyasi.',
], ids=['uzbek-latin', 'uzbek-in-cyrillic', 'uzbek-with-cyrillic-endings', 'uzbek-doubled-vowels',
        'uzbek-cyrillic-letters', 'russian', 'greek-symbols', 'uzbek-apostrophes'])
def test_uzbek_russian_and_symbols_are_never_foreign(text):
    assert language.foreign_words(text) == []


@pytest.mark.parametrize('text', [
    'э' * 60000, 'аа' * 30000, 'mustahруулахад ' * 5000, 'պահպանлах' * 4000, 'бөгөөд' * 10000,
], ids=['one-long-word', 'doubled-vowels', 'many-words', 'third-script', 'mongolian-letters'])
def test_reading_a_long_text_for_foreign_words_takes_linear_time(text):
    start = time.perf_counter()
    language.foreign_words(text)
    assert time.perf_counter() - start < 0.5


@pytest.mark.parametrize('text,named', [
    ('Qozoq tilidagi o‘zlashma so‘zlar haqida referat', True),
    ("Qirg'izcha va o‘zbekcha maqollar", True),
    ('Kazakh language basics for Uzbek students', True),
    ('Монгольский язык и его письменность', True),
    ('Rus tili darsi: fe’l zamonlari', True),
    # A people, a country or an empire is a subject, not a language the text quotes.
    ('Mo‘g‘ullar istilosi va Amir Temur davlatining tashkil topishi', False),
    ('Qozog‘iston iqtisodiyoti haqida maqola', False),
    ("Fotosintez jarayoni haqida referat, 10 bet", False),
], ids=['kazakh', 'kyrgyz', 'kazakh-english', 'mongolian-russian', 'russian', 'mongol-history', 'kazakhstan',
        'photosynthesis'])
def test_a_brief_about_another_cyrillic_language_is_known(text, named):
    assert language.other_cyrillic_language_named(text) is named


# --- quality.check and the repair line ---------------------------------------------

# A sentence of its own to open each page, so no two pages repeat each other.
LEADS = ("Fotosintez yashil o‘simliklarning barglarida kechadi.",
         "Bargning yuzasida gaz almashinuvi uchun mayda og‘izchalar joylashgan.",
         "Issiq iqlimda ayrim o‘simliklar uglerodni boshqacha yo‘l bilan to‘playdi.",
         "Hosil bo‘lgan shakar o‘simlikning ildiziga va mevasiga tashiladi.",
         "Amir Temur qo‘shinni o‘nlik, yuzlik va minglik bo‘linmalarga ajratgan.",
         "Davlat boshqaruvida vazirlar kengashi muhim vazifani bajargan.")


def uzbek(*bodies, prompt='Fotosintez jarayoni haqida referat, 6 bet'):
    pages = document(*(section(f's{n + 1}', f'{n + 1}-bo‘lim', LEADS[n] + '\n' + body)
                       for n, body in enumerate(bodies)), title='Fotosintez')
    return pages, quality.check(pages, locale='uz', fmt='pdf', prompt=prompt)


def test_a_section_with_foreign_words_goes_back_and_uzbek_in_cyrillic_does_not():
    _, report = uzbek(CLEAN, MONGOLIAN_LETTERS, UZBEK_CYRILLIC, UZBEK_MIXED,
                      MONGOLIAN_TAILS, ARMENIAN)
    assert report.issues['foreign_words'] == ['s2', 's5', 's6']
    assert report.to_repair() == ['s2', 's5', 's6']
    # Neither a wrong language (the section is Uzbek) nor anything for the log but codes and counts.
    assert 'wrong_language' not in report.issues
    assert report.summary()['foreign_words'] == 3 and 'бөгөөд' not in json.dumps(report.summary())
    # Each is named as the repair call will see it: in Latin letters, as enforce leaves it.
    assert report.foreign == {'s2': ['bogood'], 's5': ['yengillashtirsen', 'mustahruulaxad'], 's6': ['պահպանlax']}


def test_a_paragraph_that_reads_as_code_is_still_read_for_foreign_words():
    # _prose drops a line with a bracket or a semicolon from the language reading; Uzbek academic prose has both.
    body = ("Ishning maqsadi — boshqaruv tizimini yoritish; markaziy va mahalliy boshqaruvni tahlil qilish (XIV asr). "
            "Metodi esa boshqaruv unsurlarini qiyosiy tahlil qilishэд оршино.")
    _, report = uzbek(CLEAN, body)
    assert report.issues['foreign_words'] == ['s2']


@pytest.mark.parametrize('prompt', [
    'Qozoq tilidagi o‘zlashma so‘zlar haqida referat, 6 bet',
    'Rus tili darsi: fe’l zamonlari, 6 bet',
], ids=['kazakh-lesson', 'russian-lesson'])
def test_a_brief_about_another_cyrillic_language_keeps_its_words(prompt):
    _, report = uzbek(CLEAN, MONGOLIAN_LETTERS, prompt=prompt)
    assert 'foreign_words' not in report.issues and report.to_repair() == []


def test_foreign_words_are_read_only_in_an_uzbek_document_and_only_in_its_own_sections():
    pages = document(section('s1', 'Tides', 'The Moon pulls the sea. ' + MONGOLIAN_LETTERS),
                     section('s2', 'Tables', 'Pilots read tide tables.'))
    assert 'foreign_words' not in quality.check(pages, locale='en', fmt='pdf', prompt='A guide to tides').issues
    pages, _ = uzbek(MONGOLIAN_LETTERS, MONGOLIAN_WORD)
    # A category's exempt part holds names and figures; a selected change reports only its own pages.
    assert quality.check(pages, locale='uz', fmt='pdf', exempt=('s1',)).issues['foreign_words'] == ['s2']
    assert quality.check(pages, locale='uz', fmt='pdf', selected=['s1']).issues['foreign_words'] == ['s1']


def test_the_repair_line_names_the_words_and_keeps_the_rest_of_the_page():
    _, report = uzbek(CLEAN, MONGOLIAN_LETTERS + ' ' + MONGOLIAN_WORD)
    text = quality.request_text(report, 'uz', 'pdf', ['s2'])
    line = next(line for line in text.split('\n') if line.startswith('s2:'))
    assert '"bogood", "bolgono"' in line
    assert 'Rewrite in Uzbek every sentence that is not entirely Uzbek' in line
    assert 'keep the sentences already in Uzbek word for word' in line
    # A section in the wrong language altogether is rewritten whole, and gets that line alone.
    report.add('wrong_language', 's2')
    text = quality.request_text(report, 'uz', 'pdf', ['s2'])
    assert 's2: written in the wrong language' in text and 'slipped into' not in text


# --- quality.finish -----------------------------------------------------------------

def test_what_a_repair_leaves_in_another_language_is_counted_and_never_delivered_in_cyrillic(monkeypatch):
    pages, _ = uzbek(CLEAN, MONGOLIAN_LETTERS)
    data = {'output_locale': 'uz', 'output_format': 'pdf', 'prompt': 'Fotosintez haqida referat', 'content': pages}

    def stubborn(config, data, content, report, **kwargs):
        # The model wrote the page again with a Mongolian word still in it.
        again = copy.deepcopy(content)
        again['sections'][1]['body'] = MONGOLIAN_SHAPE
        return again, 'repaired'
    monkeypatch.setattr(quality, 'repair', stubborn)
    content, summary = quality.finish({}, data, pages, job=None)
    assert summary['found']['foreign_words'] == 1 and summary['repair'] == 'repaired'
    assert summary['left'] == {'foreign_words': 1}
    assert not scripts.violations(content, 'uz')


def test_a_fixed_paper_sends_back_its_foreign_words_once_and_a_cv_sends_back_nothing(monkeypatch):
    pages, _ = uzbek(CLEAN, MONGOLIAN_LETTERS)
    data = {'output_locale': 'uz', 'output_format': 'pdf', 'prompt': 'Fotosintez haqida mustaqil ish', 'content': pages}
    sent_back = []

    def recorded(config, data, content, report, **kwargs):
        sent_back.append((report.to_repair(), quality.request_text(report, 'uz', 'pdf', report.to_repair())))
        return content, 'failed'
    monkeypatch.setattr(quality, 'repair', recorded)
    _, summary = quality.finish({}, data, pages, job=None, deterministic=True)
    assert sent_back == [] and summary['repair'] is None
    content, summary = quality.finish({}, data, pages, job=None, deterministic=True,
                                      repair_codes=('wrong_language', 'foreign_words'))
    (ids, request), = sent_back
    assert ids == ['s2'] and '"bogood"' in request and summary['repair'] == 'failed'
    # A repair that fails still delivers the page, in Latin letters.
    assert not scripts.violations(content, 'uz')


# --- Whole jobs ---------------------------------------------------------------------

PROMPT = 'Fotosintez jarayoni haqida 4 ta slayd tayyorlab bering'
SLIDES = by_id([
    slide('Fotosintez', 'Yashil o‘simliklar hayotining asosi', 'Mavzuni qisqacha tanishtiring.', 'cover'),
    slide('Barg va xloroplast', CLEAN, 'Barg tuzilishini rasmda ko‘rsating.'),
    slide('Karbonat angidrid', 'Karbonat angidrid barg og‘izchalari orqali kiradi.\n' + MONGOLIAN_LETTERS + '\n'
          + MONGOLIAN_WORD, 'Gazlar almashinuvini tushuntiring.'),
    slide('C4 o‘simliklar', 'Makkajo‘xori va shakarqamish issiq iqlimga moslashgan.\n' + UZBEK_CYRILLIC,
          'Misollar keltiring.'),
])
REPAIRED = slide('Karbonat angidrid', 'Karbonat angidrid barg og‘izchalari orqali kiradi.\n'
                 'Karbonat angidrid — havoda uchraydigan va fotosintezda uglerod manbai bo‘lib xizmat qiladigan gaz.\n'
                 'Jarayonning batafsil mexanizmi buni yanada aniq ko‘rsatadi.', 'Gazlar almashinuvini tushuntiring.')


@pytest.mark.django_db
def test_an_uzbek_deck_with_mongolian_words_is_repaired_once_for_that_slide(customer, monkeypatch):
    requests = model(monkeypatch, lambda body, number: reply(body, {**SLIDES, 's3': REPAIRED} if is_repair(body)
                                                             else SLIDES))
    job, authored = run(customer, PROMPT, locale='uz', pages=4, key='foreign-words-deck')
    assert job.status == 'succeeded', job.error_code
    calls = writing_calls(requests)
    assert len(calls) == 2 and is_repair(calls[1]) and stages(job).count('repair') == 1
    request = sent(calls[1])
    # Only the slide with Mongolian words: the Uzbek written in Cyrillic (s4) is put into Latin by rule.
    assert request['revision']['selected_section_ids'] == ['s3']
    assert '"bogood", "bolgono"' in request['revision']['request']
    text = delivered(job)
    assert 'bogood' not in text and 'bolgono' not in text and 'xizmat qiladigan gaz' in text
    assert 'Bunday moslanish issiq' in text, 'Uzbek in Cyrillic arrives in Latin letters'
    stored = {s['id']: s for s in unpack(authored.encrypted_data)['content']['sections']}
    assert stored['s2']['body'] == CLEAN


@pytest.mark.django_db
def test_a_top_up_that_slides_into_mongolian_is_left_out(customer, monkeypatch):
    # Five pages asked for, five short ones written: the document is topped up.
    pages = by_id([slide(f'{n}-bo‘lim', CLEAN, layout='') for n in range(1, 6)])
    added = {sid: 'Quyosh nuri bo‘lmasa, fotosintez to‘xtaydi va o‘simlik zaxira moddalarini sarflay boshlaydi.'
             for sid in pages}
    added['s2'] = 'Xloroplastlar ichidagi yashil pigment xlorofill deb ataladi. ' + MONGOLIAN_LETTERS
    tops = []

    def answer(body, number):
        if is_top_up(body):
            tops.append(number)
            return {'sections': [{'id': s['id'], 'addition': added[s['id']]} for s in sent(body)['sections']]}
        return reply(body, pages, title='Fotosintez')
    model(monkeypatch, answer)
    job, authored = run(customer, 'Fotosintez haqida referat, 5 bet', feature='ai.pdf_topic', locale='uz', pages=5,
                        key='foreign-words-top-up')
    assert job.status == 'succeeded', job.error_code
    assert tops, 'the short document is topped up'
    stored = {s['id']: s for s in unpack(authored.encrypted_data)['content']['sections']}
    assert stored['s1']['body'].endswith(added['s1']) and stored['s3']['body'].endswith(added['s3'])
    assert stored['s2']['body'] == CLEAN, 'the addition with Mongolian in it is left out'
    assert 'bogood' not in delivered(job)


def test_the_top_up_reads_foreign_words_only_for_uzbek_and_not_for_a_brief_about_kazakh():
    assert filling.foreign_reader({'output_locale': 'uz', 'prompt': 'Fotosintez'})(MONGOLIAN_LETTERS) == ['бөгөөд']
    assert filling.foreign_reader({'output_locale': 'en', 'prompt': 'Tides'})(MONGOLIAN_LETTERS) == []
    assert filling.foreign_reader({'output_locale': 'uz', 'prompt': 'Qozoq tili darsi'})(MONGOLIAN_LETTERS) == []
