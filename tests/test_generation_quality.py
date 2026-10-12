"""The whole generated document is checked before it is drawn, and put right once.

A long deck is written in several calls that cannot see each other's mistakes,
and the model does not always write what it was asked: a slide that rewords an
earlier one, a slide in Russian inside an Uzbek deck, an empty page. These
tests hold apps/studio/quality.py and apps/studio/topics.py to what they
promise — what is flagged and what is not, and the change request a repair is
given — and then run whole jobs against a fake model to show the repair is one
extra call for the flagged sections only, that the rest of the document comes
through byte for byte, and that a repair that fails never costs the customer
the document.
"""
import copy
import json
import random

import pytest

from apps.core import storage
from apps.core.services import execute_job, submit_job
from apps.studio import language, provider, quality, scripts, topics
from apps.studio.domain import create_draft, generation_quote, unpack, update_draft
from apps.studio.models import ProviderAttempt, ProviderUsage
from operations.integrations import save_config
from tests.test_platform import account
from tests.test_provider_contract import CONFIG
from tests.test_studio import paid


# --- What the fake model writes -------------------------------------------------

MOON = ('Tides rise and fall twice a day because the Moon pulls the oceans toward it.\n'
        'Spring tides happen when the Sun and Moon line up at new and full moon.\n'
        'Neap tides are weaker because the Sun and Moon pull at right angles.')
# The same slide with two words changed: what a model writes when it runs out of things to say.
MOON_REWORDED = ('Tides rise and fall twice each day because the Moon pulls the oceans toward it.\n'
                 'Spring tides happen when the Sun and Moon line up at new and full moon.\n'
                 'Neap tides are smaller because the Sun and Moon pull at right angles.')
TABLES = ('Harbour pilots read tide tables to bring large ships through shallow channels safely.\n'
          'Fishermen plan their trips around slack water when the currents are slowest.\n'
          'Coastal engineers design sea walls using the highest recorded tidal levels.')
RUSSIAN = ('Приливы возникают из-за притяжения Луны, которое поднимает воду в океанах.\n'
           'Сильные приливы бывают в новолуние и полнолуние, когда Солнце и Луна на одной линии.\n'
           'Слабые приливы случаются, когда Солнце и Луна тянут воду под прямым углом.')
FOOTBALL = ('The national football league expanded to twenty clubs last season, and ticket prices '
            'climbed sharply in every stadium. Several famous strikers transferred abroad for record '
            'fees, while young academy players finally received regular minutes in the starting lineup.')

SILK_ROAD = ("Samarqand Buyuk Ipak yo‘lidagi eng muhim savdo shaharlaridan biri bo‘lgan.\n"
             "Shahar bozorlarida Xitoy ipagi, hind ziravorlari va fors gilamlari sotilgan.\n"
             "Karvonsaroylar savdogarlar uchun dam olish va mol saqlash joyi bo‘lib xizmat qilgan.")
SILK_ROAD_REWORDED = ("Samarqand Buyuk Ipak yo‘lidagi eng muhim savdo shaharlaridan biri edi.\n"
                      "Shahar bozorlarida Xitoy ipagi, hind ziravorlari va fors gilamlari sotilgan.\n"
                      "Karvonsaroylar savdogarlar uchun dam olish va mol saqlash joyi bo‘lib xizmat qilgan.")
TEMUR = ("Amir Temur Samarqandni o‘z davlatining poytaxtiga aylantirdi.\n"
         "U shaharda Bibixonim masjidi va boshqa ulkan imoratlarni qurdirdi.\n"
         "Temuriylar davrida Samarqand ilm va madaniyat markaziga aylandi.")
TEMUR_CYRILLIC = ("Амир Темур Самарқандни ўз давлатининг пойтахтига айлантирди.\n"
                  "У шаҳарда Бибихоним масжиди ва бошқа улкан иморатларни қурдирди.\n"
                  "Темурийлар даврида Самарқанд илм ва маданият маркази бўлиб қолди.")
ULUGBEK_RUSSIAN = ("Улугбек построил в Самарканде обсерваторию, которая стала одной из лучших в мире.\n"
                   "Учёные обсерватории составили звёздный каталог с точными координатами звёзд.\n"
                   "Медресе Улугбека на площади Регистан учило математике и астрономии.")


def slide(heading, body, notes='', layout='bullets'):
    return {'heading': heading, 'body': body, 'notes': notes, 'layout': layout}


def section(sid, heading, body, notes='', **extra):
    """A section as quality.check sees it."""
    return {'id': sid, 'heading': heading, 'body': body, 'notes': notes, 'items': [], 'columns': [], **extra}


def document(*sections, title='Ocean tides'):
    return {'title': title, 'sections': list(sections), 'questions': [], 'citations': []}


# A six-slide deck in each language: two slides repeat earlier ones and one is in Russian.
DECKS = {
    'en': {
        'prompt': 'Six slides about ocean tides for a school science class',
        'slides': [
            slide('How ocean tides work', 'The Moon, the Sun and the rhythm of the sea',
                  'Welcome the class and say what the deck covers.', 'cover'),
            slide('The Moon pulls the oceans', MOON, 'Explain the pull of the Moon with a drawing on the board.'),
            slide('Why the sea rises twice a day', MOON_REWORDED, 'Repeat the idea of the pull of the Moon.'),
            slide('Приливы и Луна', RUSSIAN, 'Расскажите о притяжении Луны и Солнца.'),
            slide('Tide tables keep harbours safe', TABLES, 'Show a printed tide table from a local port.'),
            slide('Reading a tide table', TABLES, 'Show the same printed tide table again.'),
        ],
        'repairs': {
            's3': slide('Spring and neap tides',
                        "Spring tides come at new and full moon, when the pull of the Sun adds to the Moon's.\n"
                        'Neap tides come at the quarter moons, when the two pulls partly cancel each other.\n'
                        'The range between high and low water can double from neap to spring.',
                        'Compare the two tide ranges on a simple chart.'),
            's4': slide('Tidal bulges on both sides',
                        'The ocean bulges toward the Moon and also on the far side of the Earth.\n'
                        'As the Earth turns through both bulges, most coasts see two high tides.\n'
                        'Each high tide arrives about fifty minutes later than the day before.',
                        'Use a globe to show both bulges.'),
            's6': slide('Tides shape coastal life',
                        'Mussels and barnacles survive for hours out of water between the tides.\n'
                        'Wading birds feed on mudflats that the falling tide uncovers.\n'
                        'Salt marshes flood at high water and trap mud that builds new land.',
                        'Ask the class which animals they have seen on a beach.'),
        },
        'gone': ['Why the sea rises twice a day', 'Reading a tide table', 'Prilivy'],
    },
    'uz': {
        'prompt': 'Samarqand tarixi haqida 6 ta slayd tayyorlab bering',
        'slides': [
            slide('Samarqand tarixi', 'Buyuk Ipak yo‘lidagi qadimiy shahar',
                  'Mavzuni qisqacha tanishtiring.', 'cover'),
            slide('Ipak yo‘lidagi savdo markazi', SILK_ROAD, 'Xaritada savdo yo‘llarini ko‘rsating.'),
            slide('Samarqand savdosi', SILK_ROAD_REWORDED, 'Savdo haqidagi fikrni yana takrorlang.'),
            slide('Обсерватория Улугбека', ULUGBEK_RUSSIAN, 'Расскажите об Улугбеке и его учёных.'),
            slide('Amir Temur davri', TEMUR, 'Temur qurdirgan binolar suratini ko‘rsating.'),
            slide('Temuriylar poytaxti', TEMUR, 'Temur davri haqidagi fikrni takrorlang.'),
        ],
        'repairs': {
            's3': slide('Registon maydoni',
                        'Registon maydonida uchta mashhur madrasa bir-biriga qarab turadi.\n'
                        'Ulug‘bek, Sherdor va Tillakori madrasalari turli asrlarda qurilgan.\n'
                        'Bugun maydon shaharning eng ko‘p ziyorat qilinadigan joyidir.',
                        'Registon suratini ko‘rsating.'),
            's4': slide('Ulug‘bek rasadxonasi',
                        'Mirzo Ulug‘bek Samarqandda o‘z davrining eng yirik rasadxonasini qurdirdi.\n'
                        'Rasadxona olimlari mingdan ortiq yulduzning o‘rnini aniq o‘lchab chiqqan.\n'
                        'Ulug‘bek madrasasida matematika va astronomiya o‘qitilgan.',
                        'Yulduzlar jadvali haqida gapirib bering.'),
            's6': slide('Shahar bugun',
                        'Bugungi Samarqand Zarafshon vodiysidagi yirik ilmiy va sayyohlik markazidir.\n'
                        'Shaharning tarixiy qismi Butunjahon merosi ro‘yxatiga kiritilgan.\n'
                        'Har yili bu yerda xalqaro musiqa festivali o‘tkaziladi.',
                        'Bugungi shahar suratlarini ko‘rsating.'),
        },
        'gone': ['Samarqand savdosi', 'Temuriylar poytaxti', 'Observatoriya'],
    },
}
FLAGGED = ['s3', 's4', 's6']


# --- The fake provider ------------------------------------------------------------

class Broken(str):
    """A reply that is not JSON at all, as a garbled or cut-off response is."""


def model(monkeypatch, handler):
    """Every provider call answered by `handler(body, number)`; returns the request bodies, in order.

    tests/test_provider_optimization.transport, except that a handler may also
    answer with `Broken` text, which is sent as it is rather than as JSON.
    """
    requests = []

    class Response:
        def __init__(self, result): self.result = result
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return json.dumps(self.result).encode()

    class Opener:
        def open(self, request, timeout):
            body = json.loads(request.data)
            requests.append(body)
            raw = handler(body, len(requests))
            text = str(raw) if isinstance(raw, Broken) else json.dumps(raw)
            return Response({'id': f'resp_offline_{len(requests)}', 'model': CONFIG['model'],
                             'status': 'completed', 'output': [{'type': 'message', 'content': [
                                 {'type': 'output_text', 'text': text}]}],
                             'usage': {'input_tokens': 120, 'output_tokens': 80}})
    monkeypatch.setattr(provider.urllib.request, 'build_opener', lambda _: Opener())
    return requests


def sent(body):
    return json.loads(body['input'])


def is_repair(body):
    return 'revision' in sent(body) and body['text']['format']['name'] == 'document'


def is_top_up(body):
    return body['text']['format']['name'] == 'additions'


def writing_calls(requests):
    return [body for body in requests if not is_top_up(body)]


def wire(fields, sid, written):
    """One section exactly as the request's schema asks for it."""
    out = {}
    for key, definition in fields.items():
        if key == 'id':
            out[key] = sid
        elif key in written:
            out[key] = written[key]
        elif definition.get('type') == 'array':
            out[key] = []
        elif 'enum' in definition:
            out[key] = 'bullets' if 'bullets' in definition['enum'] else definition['enum'][0]
        else:
            out[key] = ''
    return out


def reply(body, written, title='Generated'):
    """The model's answer: `written` maps each requested section id to its fields."""
    properties = body['text']['format']['schema']['properties']
    if is_top_up(body):
        # The length top-up of a short PDF adds nothing here.
        return {'sections': [{'id': s['id'], 'addition': ''} for s in sent(body)['sections']]}
    fields = properties['sections']['items']['properties']
    answer = {'answer_supported': True,
              'sections': [wire(fields, s['id'], written[s['id']]) for s in sent(body)['outline']['sections']]}
    if 'title' in properties:
        answer['title'] = title
    if 'design' in properties:
        answer['design'] = properties['design']['enum'][0]
    for field in ('citations', 'questions'):
        if field in properties:
            answer[field] = []
    return answer


def by_id(slides):
    return {f's{n + 1}': written for n, written in enumerate(slides)}


@pytest.fixture
def customer(settings):
    settings.DEBUG = True
    customer = paid(settings, account())
    save_config('ai', {'mode': 'openai', 'model': CONFIG['model'], 'api_key': 'sk-offline-test-only'})
    return customer


def run(customer, prompt, *, feature='ai.pptx', locale='en', pages, key, options=None):
    authored = create_draft(customer, {'feature_id': feature, 'prompt': prompt, 'output_locale': locale,
                                       'options': {'pages': pages, **(options or {})}})
    quote = generation_quote(customer, authored.id, authored.version)
    job, _ = submit_job(customer, quote.id, key)
    job = execute_job(job.id)
    authored.refresh_from_db()
    return job, authored


def stages(job):
    return list(ProviderAttempt.objects.filter(job=job).order_by('created_at').values_list('stage', flat=True))


def usage(job):
    return sorted(ProviderUsage.objects.filter(job=job).values_list('provider', 'outcome'))


def delivered(job):
    """The delivered file's text, with line wrapping undone."""
    return ' '.join(scripts.artifact_text(storage.local(job.artifacts.get().file.object_key)).split())


# --- quality.check: what is flagged ----------------------------------------------

def test_a_slide_that_rewords_an_earlier_one_is_a_duplicate_and_distinct_slides_are_not():
    deck = document(section('s1', 'How ocean tides work', 'The Moon, the Sun and the rhythm of the sea'),
                    section('s2', 'The Moon pulls the oceans', MOON),
                    section('s3', 'Why the sea rises twice a day', MOON_REWORDED),
                    section('s4', 'Tide tables keep harbours safe', TABLES),
                    section('s5', 'Reading a tide table', TABLES))
    report = quality.check(deck, locale='en', fmt='pptx', prompt='Five slides about ocean tides')
    assert report.issues.get('duplicate_section') == ['s3', 's5']
    assert report.to_repair() == ['s3', 's5']
    assert 'wrong_language' not in report.issues and 'empty_section' not in report.issues


def test_a_heading_used_twice_is_flagged_on_the_later_section():
    deck = document(section('s1', 'The Moon pulls the oceans', MOON),
                    section('s2', 'Tide tables', TABLES),
                    section('s3', 'The moon pulls the oceans!', 'Each high tide arrives about fifty minutes later '
                                                               'than the day before as the Earth turns.'))
    report = quality.check(deck, locale='en', fmt='pptx')
    assert report.issues.get('repeated_heading') == ['s3']
    assert 's3' in report.to_repair() and 'duplicate_section' not in report.issues


def test_a_repeated_paragraph_inside_a_new_page_is_flagged():
    fresh = ('Coastal engineers measure the tidal range at every port before they plan any new quay.\n'
             + MOON.split('\n')[0] + '\n'
             'Ferry timetables in shallow estuaries are rewritten every month to follow the tide.')
    pages = document(section('s1', 'Why tides happen', MOON),
                     section('s2', 'Living with the tide', fresh))
    report = quality.check(pages, locale='en', fmt='pdf')
    assert report.issues.get('duplicate_paragraph') == ['s2']
    assert 'duplicate_section' not in report.issues


def test_empty_sections_are_flagged_but_a_continuing_pdf_page_is_not():
    pages = document(section('s1', 'Why tides happen', MOON),
                     # A document's continuing page has no heading of its own: that is not empty.
                     section('s2', '', TABLES),
                     section('s3', 'Tidal energy', ''),
                     section('s4', '', ''))
    report = quality.check(pages, locale='en', fmt='pdf')
    assert report.issues.get('empty_section') == ['s3', 's4']
    deck = document(section('s1', 'How ocean tides work', 'The Moon and the sea', layout='cover'),
                    section('s2', 'The Moon pulls the oceans', MOON),
                    section('s3', '', ''))
    assert quality.check(deck, locale='en', fmt='pptx').issues.get('empty_section') == ['s3']


@pytest.mark.parametrize('locale,sections,prompt', [
    ('en', [section('s1', 'The Moon pulls the oceans', MOON), section('s2', 'Приливы', RUSSIAN),
            section('s3', 'Tide tables', TABLES)], 'Three slides about ocean tides'),
    ('uz', [section('s1', 'Ipak yo‘li', SILK_ROAD), section('s2', 'Улугбек', ULUGBEK_RUSSIAN),
            section('s3', 'Amir Temur', TEMUR)], 'Samarqand tarixi haqida 3 ta slayd'),
])
def test_a_whole_section_in_russian_is_in_the_wrong_language(locale, sections, prompt):
    report = quality.check(document(*sections), locale=locale, fmt='pptx', prompt=prompt)
    assert report.issues.get('wrong_language') == ['s2']
    assert report.to_repair() == ['s2']
    # Its alphabet is wrong too, which the deterministic pass handles separately.
    assert ('sections', 1, 'body') in report.issues['script']


def test_uzbek_written_in_cyrillic_is_a_script_fix_not_a_wrong_language():
    deck = document(section('s1', 'Ipak yo‘li', SILK_ROAD), section('s2', 'Темур даври', TEMUR_CYRILLIC),
                    title='Samarqand tarixi')
    report = quality.check(deck, locale='uz', fmt='pptx', prompt='Samarqand tarixi haqida 2 ta slayd')
    assert 'wrong_language' not in report.issues and report.to_repair() == []
    assert ('sections', 1, 'body') in report.issues['script']
    fixed, paths = scripts.enforce(deck, 'uz')
    assert ('sections', 1, 'body') in paths and not scripts.violations(fixed, 'uz')


def test_english_examples_in_an_uzbek_english_lesson_are_content_not_a_wrong_language():
    rule = ("Present Simple zamoni odatiy harakatlar va doimiy faktlarni ifodalash uchun ishlatiladi.\n"
            "Uchinchi shaxs birlikda fe'lga -s qo'shimchasi qo'shiladi va bu qoida juda muhim.\n"
            "Inkor gaplarda do not yoki does not yordamchi so'zlari ishlatiladi.")
    examples = ('Present Simple is used for habits and facts: I go to school every day.\n'
                'We add -s to the verb with he, she and it: She reads a book every evening.\n'
                'Negative sentences use do not or does not: He does not like coffee at all.')
    deck = document(section('s1', 'Qoida', rule), section('s2', 'Misollar', examples), title='Present Simple')
    lesson = quality.check(deck, locale='uz', fmt='pptx',
                           prompt='Ingliz tili darsi uchun Present Simple zamoni haqida 2 ta slayd')
    assert 'wrong_language' not in lesson.issues and lesson.to_repair() == []
    # A brief in Uzbek that never names English: the slide is still content, recorded and left alone.
    other = quality.check(deck, locale='uz', fmt='pptx', prompt='Present Simple mavzusida 3 ta slayd, misollar bilan')
    assert other.issues.get('foreign_passage') == ['s2'] and other.to_repair() == []
    # The same slide is plainly wrong when the brief is in English and Uzbek was asked for:
    # the model wrote in the brief's language instead.
    english = quality.check(deck, locale='uz', fmt='pptx',
                            prompt='Two slides on the Present Simple tense for my class, with examples')
    assert english.issues.get('wrong_language') == ['s2'] and english.to_repair() == ['s2']


@pytest.mark.parametrize('locale,prompt,sections', [
    ('uz', 'Samarqand tarixi haqida 3 ta slayd. Tayyorladi: Rustam Karimov, 9-sinf',
     [section('s1', 'Ipak yo‘li', SILK_ROAD), section('s2', 'Улугбек', ULUGBEK_RUSSIAN),
      section('s3', 'Amir Temur', TEMUR)]),
    ('en', 'Three slides on the California Gold Rush and the tides of San Francisco Bay',
     [section('s1', 'The Moon pulls the oceans', MOON), section('s2', 'Приливы', RUSSIAN),
      section('s3', 'Tide tables', TABLES)]),
])
def test_a_name_that_merely_begins_like_russian_does_not_excuse_a_russian_slide(locale, prompt, sections):
    report = quality.check(document(*sections), locale=locale, fmt='pptx', prompt=prompt)
    assert report.issues.get('wrong_language') == ['s2']


@pytest.mark.parametrize('text,named', [
    ('Rus tili darsi', {'ru'}), ('ruscha tarjimasi bilan', {'ru'}), ("rus tilida yozing", {'ru'}),
    ('Russian verbs of motion', {'ru'}), ('Презентация о русском языке', {'ru'}), ('Рус тилида', {'ru'}),
    ('Tayyorladi: Rustam Karimov', set()), ('Ruslan va Rushana', set()), ('The California Gold Rush', set()),
    ('How rust forms on iron', set()), ("O'zbekiston tarixi", set()), ('Tourism in Uzbekistan', set()),
    ("o'zbekcha izoh bilan", {'uz'}), ('inglizcha misollar', {'en'}), ('English-speaking countries', {'en'}),
])
def test_a_language_is_named_only_by_a_whole_word(text, named):
    assert quality._languages_named(text) == named


CODE = ("for item in items:\n    if item is None or item == '':\n        continue\n    print(item)\n"
        "result = [x for x in data if x is not None and x > 0]")
SQL = ("SELECT name, city FROM users WHERE age > 18 AND city = 'Tashkent' ORDER BY name;\n"
       "SELECT COUNT(*) FROM orders WHERE status = 'paid' AND total > 100;")
GATSBY = ("Kitob nomi: The Great Gatsby. Muallif: F. Scott Fitzgerald. Janr: roman. Yil: 1925. "
          "Asosiy g'oya: the American Dream and its decline.")
IELTS = ('IELTS Writing Task 2 namunasi: Some people believe that university education should be free for all '
         'students. To what extent do you agree or disagree?')
QUOTE = ("“The only way to do great work is to love what you do. If you haven't found it yet, keep looking.” "
         "— Steve Jobs")


@pytest.mark.parametrize('locale,prompt,slides', [
    # Code is in no language, whatever language the brief is in.
    ('ru', 'Сделай презентацию про циклы в Python', [('Пример кода', CODE, 'bullets')]),
    ('ru', 'Five slides on Python loops for beginners', [('Пример кода', CODE, 'bullets')]),
    ('uz', "SQL so'rovlari haqida taqdimot", [("So'rov namunasi", SQL, 'bullets')]),
    ('uz', 'A deck about SQL queries for my students', [("So'rov namunasi", SQL, 'bullets')]),
    # A quotation is kept in the words it was said in.
    ('uz', 'Mashhur insonlarning motivatsion iqtiboslari, original tilida', [('Stiv Jobs', QUOTE, 'quote')]),
    ('uz', 'Famous motivational quotes for students', [('Stiv Jobs', QUOTE, 'quote')]),
    ('uz', 'Samarqand tarixi haqida 3 ta slayd', [('Улугбек', ULUGBEK_RUSSIAN, 'quote')]),
    # An English book title or exam sample in an Uzbek document is its subject.
    ('uz', 'Buyuk Getsbi romani haqida 3 ta slayd tayyorlab bering', [('Kitob haqida', GATSBY, 'bullets')]),
    ('uz', "IELTS imtihoniga tayyorgarlik haqida 3 ta slayd kerak", [('Namuna', IELTS, 'bullets')]),
    # Russian in a brief that names Russian is lesson material.
    ('uz', "Rus tili darsi: oila a'zolari haqida 3 ta slayd", [('Oila', ULUGBEK_RUSSIAN, 'bullets')]),
    ('en', 'Three slides on Russian verbs of motion', [('Verbs', RUSSIAN, 'bullets')]),
])
def test_a_passage_that_may_be_content_is_never_sent_back_for_its_language(locale, prompt, slides):
    deck = document(section('s1', 'Cover', 'Opening words of the deck', layout='cover'),
                    *[section(f's{n}', heading, body, layout=layout)
                      for n, (heading, body, layout) in enumerate(slides, start=2)])
    report = quality.check(deck, locale=locale, fmt='pptx', prompt=prompt)
    assert 'wrong_language' not in report.issues and report.to_repair() == []


def test_a_change_request_that_names_russian_keeps_a_russian_slide():
    deck = document(section('s1', 'Ipak yo‘li', SILK_ROAD), section('s2', 'Улугбек', ULUGBEK_RUSSIAN),
                    section('s3', 'Amir Temur', TEMUR))
    prompt = 'Samarqand tarixi haqida 3 ta slayd'
    plain = quality.check(deck, locale='uz', fmt='pptx', prompt=prompt, request='Ikkinchi slaydni qisqartiring')
    assert plain.issues.get('wrong_language') == ['s2']
    asked = quality.check(deck, locale='uz', fmt='pptx', prompt=prompt,
                          request='Ikkinchi slaydni rus tilida qoldiring')
    assert asked.issues.get('foreign_passage') == ['s2'] and asked.to_repair() == []


def test_a_revision_mostly_in_another_language_is_a_translation_and_is_kept():
    """A change request may ask for a translation in words the language reader does not know."""
    english = [section('s1', 'Silk Road trade', 'Samarkand was one of the most important trading cities on the '
                                                'Great Silk Road, and its bazaars sold silk from China.')]
    # Asked for in Uzbek with English picked: an Uzbek slide is the model following the brief's language.
    brief = 'Samarqand tarixi haqida sinfim uchun ikki slayd tayyorlab bering'
    uzbek = document(section('s1', 'Ipak yo‘li', SILK_ROAD), section('s2', 'Amir Temur', TEMUR), title='Samarqand')
    whole = quality.check(uzbek, locale='en', fmt='pptx', prompt=brief)
    assert whole.issues.get('wrong_language') == ['s1', 's2']
    revised = quality.check(uzbek, locale='en', fmt='pptx', prompt=brief, request="Hammasini o'zbekchaga o'gir")
    assert revised.issues.get('foreign_passage') == ['s1', 's2'] and revised.to_repair() == []
    # One slide of two in the wrong language is not a translation: it is put right.
    mixed = document(english[0], section('s2', 'Amir Temur', TEMUR), title='Samarqand')
    assert quality.check(mixed, locale='en', fmt='pptx', prompt=brief,
                         request='Make the slides shorter').issues.get('wrong_language') == ['s2']


def test_cover_closing_and_divider_slides_may_repeat_a_heading():
    agenda = [{'label': label, 'text': '', 'value': ''}
              for label in ('Solar power potential', 'Wind power projects', 'Policy and investment')]
    deck = document(
        section('s1', 'Renewable Energy in Uzbekistan', 'Opportunities and challenges to 2030', layout='cover'),
        section('s2', 'Agenda', '', layout='agenda', items=agenda),
        section('s3', 'Part one', '', layout='section'),
        section('s4', 'Solar power potential', 'Uzbekistan receives over 300 sunny days a year, and large solar '
                                               'parks are under construction in Samarkand and Jizzakh.'),
        section('s5', 'Part one', '', layout='section'),
        section('s6', 'Questions?', 'Ask anything about the first part of the lecture', layout='closing'),
        section('s7', 'Questions?', 'Ask anything about the first part of the lecture', layout='closing'),
        section('s8', 'Renewable Energy in Uzbekistan', 'Thank you for your attention', layout='closing'),
        section('s9', 'Renewable Energy in Uzbekistan', 'Opportunities and challenges for solar and wind power in '
                                                        'Uzbekistan up to 2030', layout='closing'),
        section('s10', 'Thank you', 'Opportunities and challenges for solar and wind power in Uzbekistan up to '
                                    '2030', layout='closing'),
        title='Renewable Energy in Uzbekistan')
    report = quality.check(deck, locale='en', fmt='pptx', prompt='Renewable energy in Uzbekistan, 10 slides')
    assert report.issues == {} and report.to_repair() == []
    # The same repeats between two body slides are still put right.
    body = copy.deepcopy(deck)
    for position in (7, 8, 9):
        body['sections'][position]['layout'] = 'bullets'
    repeated = quality.check(body, locale='en', fmt='pptx', prompt='Renewable energy in Uzbekistan, 10 slides')
    assert repeated.issues.get('repeated_heading') == ['s9'] and set(repeated.to_repair()) == {'s9', 's10'}


def test_a_document_page_that_repeats_the_heading_above_it_is_a_continuing_page():
    pages = document(section('s1', 'Why tides happen', MOON),
                     section('s2', 'Living with the tide', HARBOURS),
                     section('s3', 'Living with the tide', TABLES),
                     section('s4', '', 'Each high tide arrives about fifty minutes later than the day before.'),
                     section('s5', 'Living with  the tide!', 'Ferry timetables follow the tides in estuaries.'),
                     section('s6', 'Why tides happen', 'The Sun pulls on the oceans too, about half as hard.'))
    report = quality.check(pages, locale='en', fmt='pdf', prompt='A short report about ocean tides')
    # s3 and s5 go on with the topic over them: emptied without a model call.
    assert report.issues.get('continued_heading') == ['s3', 's5']
    # s6 comes back to an earlier topic: only the model can tell what to call it.
    assert report.issues.get('repeated_heading') == ['s6'] and report.to_repair() == ['s6']
    data = {'output_locale': 'en', 'output_format': 'pdf', 'prompt': 'A short report about ocean tides',
            'content': pages}
    finished, summary = quality.finish(None, data, pages, job=None, mode='local')
    assert [s['heading'] for s in finished['sections']] == [
        'Why tides happen', 'Living with the tide', '', '', '', 'Why tides happen']
    assert [s['body'] for s in finished['sections']] == [s['body'] for s in pages['sections']]
    assert summary['found']['continued_heading'] == 2 and 'continued_heading' not in summary['left']
    # A slide is never a continuing page: the same heading twice is a repeat.
    deck = quality.check(pages, locale='en', fmt='pptx', prompt='A short report about ocean tides')
    assert 'continued_heading' not in deck.issues and deck.issues.get('repeated_heading') == ['s3', 's5', 's6']


def test_a_selected_section_is_compared_with_the_whole_document_but_only_it_is_reported():
    deck = document(section('s1', 'How ocean tides work', 'The Moon, the Sun and the rhythm of the sea'),
                    section('s2', 'The Moon pulls the oceans', MOON),
                    section('s3', 'More about the Moon', MOON_REWORDED),
                    section('s4', 'Приливы', RUSSIAN),
                    section('s5', 'Reading a tide table', TABLES),
                    section('s6', 'Tide tables keep harbours safe', TABLES))
    copied = quality.check(deck, locale='en', fmt='pptx', prompt='Six slides about ocean tides', selected=['s3'])
    assert copied.issues.get('duplicate_section') == ['s3'] and copied.to_repair() == ['s3']
    assert {sid for ids in copied.issues.values() for sid in ids} == {'s3'}, 'an untouched slide is never reported'
    # A selected slide that a later, untouched one repeats is the one to change.
    earlier = quality.check(deck, locale='en', fmt='pptx', prompt='Six slides about ocean tides', selected=['s5'])
    assert earlier.issues.get('duplicate_section') == ['s5'] and earlier.to_repair() == ['s5']
    alone = quality.check(deck, locale='en', fmt='pptx', prompt='Six slides about ocean tides', selected=['s1'])
    assert alone.to_repair() == [] and 'script' not in alone.issues


def test_missing_subtopics_are_reported_only_when_the_brief_lists_them_and_the_text_lacks_them():
    brief = 'A presentation on renewable energy, including solar power, wind turbines and hydroelectric dams.'
    partial = document(section('s1', 'Solar power', 'Solar panels turn sunlight into electric power for homes.'),
                       section('s2', 'Wind turbines', 'Wind turbines spin in steady coastal winds.'),
                       title='Renewable energy')
    assert quality.check(partial, locale='en', fmt='pptx', prompt=brief).missing_subtopics == ['hydroelectric dams']
    complete = copy.deepcopy(partial)
    complete['sections'].append(section('s3', 'Hydroelectric dams', 'Hydroelectric dams store river water.'))
    assert quality.check(complete, locale='en', fmt='pptx', prompt=brief).missing_subtopics == []
    # Words are compared only within one language: an Uzbek brief says nothing about an English deck's words.
    uzbek = ("Qayta tiklanuvchi energiya haqida taqdimot. Quyidagilarni o'z ichiga olsin: quyosh energiyasi, "
             "shamol energiyasi va gidroenergetika.")
    assert quality.check(partial, locale='en', fmt='pptx', prompt=uzbek).missing_subtopics == []
    # A missing subtopic is a note for a repair, never a repair of its own.
    assert quality.check(partial, locale='en', fmt='pptx', prompt=brief).to_repair() == []


HARBOURS = ('Harbour masters publish the times of high and low tides every week, because large ships can '
            'only cross the shallow bar at high water. Ferry timetables in narrow estuaries follow the tides '
            'too, and they are rewritten each month.')


def test_an_off_topic_section_is_recorded_but_never_repaired():
    pages = document(section('s1', 'Why tides happen', MOON),
                     section('s2', 'Ports and the tides', HARBOURS),
                     section('s3', 'Football news', FOOTBALL))
    report = quality.check(pages, locale='en', fmt='pdf', prompt='A short report about ocean tides and the moon')
    assert report.issues.get('off_topic') == ['s3']
    assert report.to_repair() == []
    assert report.summary()['off_topic'] == 1


# --- quality.tidy and the repair request -------------------------------------------

def test_tidy_removes_markdown_tags_and_control_characters_from_every_visible_field():
    assert quality.tidy_text('## Key **ideas** of <b>tides</b>\x07 and\ufffd the moon\u200b') == \
        'Key ideas of tides and the moon'
    assert quality.tidy_text('# Heading\nLine with  two   spaces  \n  ### Sub') == 'Heading\nLine with  two   spaces\nSub'
    assert quality.tidy_text('one<br>two<br/>three<BR />four') == 'one\ntwo\nthree\nfour'
    assert quality.tidy_text('<b><i>Nested</i></b> and <strong>strong</strong>') == 'Nested and strong'
    raw = {'title': '**Tides**', 'citations': [{'quote': '**kept as quoted**'}],
           'sections': [{'id': 's1', 'heading': '# Intro', 'body': '<strong>Bold</strong> text\x00',
                         'notes': 'Say it\ufffd', 'items': [{'label': '**L**', 'text': '<i>t</i>', 'value': ''}],
                         'columns': ['<em>C</em>']}],
           'questions': [{'stem': '**Q**?', 'options': ['<b>A</b>'], 'answer': 'A', 'explanation': '', 'topic': ''}]}
    clean, changed = quality.tidy(raw)
    assert clean['title'] == 'Tides'
    assert clean['sections'][0] == {'id': 's1', 'heading': 'Intro', 'body': 'Bold text', 'notes': 'Say it',
                                    'items': [{'label': 'L', 'text': 't', 'value': ''}], 'columns': ['C']}
    assert clean['questions'][0]['stem'] == 'Q?' and clean['questions'][0]['options'] == ['A']
    assert clean['citations'] == raw['citations'], 'a verbatim source quote is never touched'
    assert ('title',) in changed and ('sections', 0, 'items', 0, 'text') in changed
    assert raw['title'] == '**Tides**', 'the input is not changed in place'


@pytest.mark.parametrize('text', [
    '1. She ____ (go) to school.',
    'Name: ________  Date: ________',
    "Bo'sh joyni to'ldiring: Men har kuni ______ boraman",
    'Every class may define __init__ to set its attributes.',
    'if __name__ == "__main__":\n    main()',
    'x**2 + y**2 = r**2',
    'if a<b and c>d then swap',
    'For 0<p<1 and q>0 the series converges.',
    'Use the HTML <p> tag for a paragraph and <b> for bold.',
    'def f(x):\n    if x > 0:\n        return x\n    return -x',
    '# of students grew by 10%',
    'Column A    Column B\n  indented line',
])
def test_tidy_never_changes_text_that_only_looks_like_markup(text):
    """Blanks to fill in, dunder names, powers, comparisons, code and spacing are the text itself."""
    assert quality.tidy_text(text) == text

def flagged():
    report = quality.Report()
    report.add('duplicate_section', 's3')
    report.add('wrong_language', 's4')
    report.add('empty_section', 's6')
    report.add('repeated_heading', 's7')
    report.add('off_topic', 's5')
    report.missing_subtopics = ['neap tides', 'tide tables']
    return report


def test_the_repair_request_names_only_its_ids_and_what_is_wrong_with_each():
    text = quality.request_text(flagged(), 'uz', 'pptx', ['s3', 's4'])
    first = text.split('\n')[0]
    assert 's3, s4' in first and 'slides' in first and 'Uzbek, Latin alphabet' in first
    # Only what is wrong is changed: a slide with a repeated heading keeps its text.
    assert ('Change only these slides, and in each only what its line below asks for; keep the rest word for '
            'word.') in first
    assert 's6' not in text and 's7' not in text and 's5' not in text
    assert 's4: written in the wrong language' in text
    duplicate = next(line for line in text.split('\n') if line.startswith('s3:'))
    assert 'repeat what other slides already say' in duplicate
    assert 'neap tides; tide tables' in duplicate, 'a replaced slide should cover what the brief still misses'
    assert 'empty' not in text and 'heading repeats' not in text


def test_the_repair_request_says_each_code_in_its_own_words():
    text = quality.request_text(flagged(), 'ru', 'pdf', ['s4', 's6', 's7'])
    assert 'pages' in text.split('\n')[0] and 'Russian, Cyrillic alphabet' in text
    assert ('s6: empty. Write each as the page that belongs at this point of the document, following '
            'writing_guidance') in text
    # A document page that only goes on with the topic before it gets no heading at all.
    assert ('s7: the heading repeats an earlier one. If the page continues the topic of the page before it, '
            'return an empty heading; otherwise give it a heading that names what this page adds. Change nothing '
            'else.') in text
    # Without a repeated section to replace, the missing subtopics are not asked for.
    assert 'neap tides' not in text and 's3' not in text
    # A slide always has a heading of its own.
    deck = quality.request_text(flagged(), 'en', 'pptx', ['s7'])
    assert 's7: the heading repeats an earlier one.' in deck and 'empty heading' not in deck


# --- topics -----------------------------------------------------------------------

@pytest.mark.parametrize('brief,expected', [
    ('A 10-slide presentation on renewable energy, including solar power, wind turbines and hydroelectric dams.',
     ['solar power', 'wind turbines', 'hydroelectric dams']),
    ('A presentation about renewable energy in English, 12 slides, covering solar power, wind power and '
     'energy storage.', ['solar power', 'wind power', 'energy storage']),
    ("Qayta tiklanuvchi energiya haqida 10 ta slayd. Quyidagilarni o'z ichiga olsin: quyosh energiyasi, "
     "shamol energiyasi va gidroenergetika.", ['quyosh energiyasi', 'shamol energiyasi', 'gidroenergetika']),
    ('Qayta tiklanuvchi energiya haqida taqdimot, shu jumladan quyosh panellari, shamol turbinalari hamda '
     'geotermal energiya', ['quyosh panellari', 'shamol turbinalari', 'geotermal energiya']),
    ('Презентация о возобновляемой энергетике, включая солнечную энергию, ветровую энергию и гидроэнергетику.',
     ['солнечную энергию', 'ветровую энергию', 'гидроэнергетику']),
    ('Slides about the water cycle:\n- Evaporation\n- Condensation\n- Precipitation',
     ['Evaporation', 'Condensation', 'Precipitation']),
    ("Suv aylanishi haqida slaydlar:\n1. Bug'lanish\n2) Kondensatsiya\n3. Yog'ingarchilik",
     ["Bug'lanish", 'Kondensatsiya', "Yog'ingarchilik"]),
])
def test_the_subtopics_a_brief_lists_are_read_in_each_language(brief, expected):
    assert topics.required(brief) == expected


@pytest.mark.parametrize('brief,expected', [
    ('The water cycle\n- 10 slides\n- in English\n- Evaporation\n- Condensation', ['Evaporation', 'Condensation']),
    ("Suv aylanishi\n- 10 ta slayd\n- o'zbek tilida\n- Bug'lanish\n- Kondensatsiya", ["Bug'lanish", 'Kondensatsiya']),
    ('Круговорот воды\n- 10 слайдов\n- на русском языке\n- Испарение\n- Конденсация', ['Испарение', 'Конденсация']),
    ('Make a deck on climate change in English including 10 slides, 5 questions and a PDF', []),
    ("Iqlim haqida. Quyidagilarni o'z ichiga olsin: 12 ta slayd, 5 ta savol", []),
    ('Сделай презентацию о климате, включая 10 слайдов, на русском языке и парниковый эффект',
     ['парниковый эффект']),
    ('Five slides about tides.', []),
])
def test_counts_formats_and_languages_in_a_list_are_not_subtopics(brief, expected):
    assert topics.required(brief) == expected


def test_a_language_line_spelled_out_in_english_is_not_a_subtopic():
    assert topics.required('Photosynthesis\n- 10 slides\n- English language\n- Light reactions\n- Calvin cycle') \
        == ['Light reactions', 'Calvin cycle']


@pytest.mark.parametrize('brief,expected', [
    ('Make a presentation about marketing, including examples, statistics and a conclusion, 10 slides, modern '
     'design', []),
    ('Сделай презентацию на 12 слайдов про экологию, включая фото, таблицы и выводы', []),
    ('Create slides for teachers covering classroom management and assessment, with speaker notes and in a '
     'friendly tone', ['classroom management', 'assessment']),
    ("Iqtisodiyot haqida referat. Quyidagilarni o'z ichiga olsin: ilmiy uslubda, adabiyotlar ro'yxati bilan, "
     "rasmlar, xulosa", []),
    ('A report on solar energy, including sources, images and a table, in a formal style', []),
    # A subject that only starts like a form word stays: photosynthesis is not a photo.
    ('Презентация по биологии, включая фотосинтез, дыхание и брожение', ['фотосинтез', 'дыхание', 'брожение']),
    ('A deck on energy, including photosynthesis, examples of solar farms and tide tables',
     ['photosynthesis', 'examples of solar farms', 'tide tables']),
])
def test_form_style_and_delivery_requests_are_not_subtopics(brief, expected):
    """Photos, tables, design, tone, a conclusion or statistics are how to write it, not what to cover."""
    assert topics.required(brief) == expected


def test_a_subtopic_is_found_through_uzbek_and_russian_endings():
    uzbek = ["quyosh energiyasi", "shamol energiyasi", "gidroenergetika"]
    text = "Quyosh energiyasidan foydalanish ortmoqda. Shamol energiyasining afzalliklari ko'p."
    assert topics.missing(uzbek, text) == ['gidroenergetika']
    russian = ['солнечную энергию', 'ветровую энергию', 'гидроэнергетику']
    assert topics.missing(russian, 'Солнечная энергия дешевеет. Ветровая энергетика растёт. '
                                   'Гидроэнергетика старейшая.') == []
    assert topics.missing(['solar power', 'wind turbines'], 'Solar panels give power. Turbines need wind.') == []
    # The apostrophe an Uzbek word is typed with does not matter.
    assert topics.missing(["O‘zbekiston tarixi"], "O'zbekistonning tarixiy shaharlari") == []


def test_a_short_root_with_an_ending_still_counts_as_covered():
    text = ("Suvning ifloslanishi baliqlarga zarar yetkazadi. Havoning tozaligi sog'liq uchun muhim. "
            "Tuproqning ifloslanishi hosilni kamaytiradi.")
    assert topics.missing(['havo', 'suv', 'tuproq ifloslanishi'], text) == []
    assert topics.missing(['вода'], 'Без воды нет жизни.') == []
    assert topics.missing(['tide'], 'Tides rise twice a day.') == []
    # Still a different word when only the first letters agree.
    assert topics.missing(['suv'], 'Sut va sutli mahsulotlar.') == ['suv']
    assert topics.missing(['tide'], 'Tickets are sold at the gate.') == ['tide']
    # The same stems decide off-topic: a section on tide tables is on the topic of a report on tides.
    pages = document(section('s1', 'Why tides happen', MOON), section('s2', 'Tide tables', TABLES),
                     section('s3', 'Ports and the tides', HARBOURS))
    report = quality.check(pages, locale='en', fmt='pdf', prompt='A short report about ocean tides and the moon')
    assert 'off_topic' not in report.issues


# --- Whole jobs: the repair is one extra call ---------------------------------------

@pytest.mark.django_db
@pytest.mark.parametrize('feature', ['ai.pptx', 'ai.pdf_topic'])
@pytest.mark.parametrize('locale', ['en', 'uz'])
def test_a_flawed_document_is_repaired_once_for_the_flagged_sections_only(customer, monkeypatch, locale, feature):
    deck = DECKS[locale]
    first = by_id(deck['slides'])

    def answer(body, number):
        return reply(body, deck['repairs'] if is_repair(body) else first)

    requests = model(monkeypatch, answer)
    job, authored = run(customer, deck['prompt'], feature=feature, locale=locale, pages=6,
                        key=f'quality-repair-{locale}-{feature}')
    assert job.status == 'succeeded', job.error_code
    calls = writing_calls(requests)
    assert len(calls) == 2 and not is_repair(calls[0]) and is_repair(calls[1])
    assert stages(job).count('generate') == 1 and stages(job).count('repair') == 1
    assert ('openai_repair', 'succeeded') in usage(job) and ('openai', 'succeeded') in usage(job)

    request = sent(calls[1])
    assert request['revision']['selected_section_ids'] == FLAGGED
    assert [s['id'] for s in request['outline']['sections']] == FLAGGED
    assert [s['id'] for s in request['document_context']['sections']] == list(first)
    assert 's3, s4, s6' in request['revision']['request']
    assert request['output_locale'] == locale
    assert all(body['instructions'].endswith(language.instructions(locale)) for body in calls)
    assert 'title' not in calls[1]['text']['format']['schema']['properties']

    stored = {s['id']: s for s in unpack(authored.encrypted_data)['content']['sections']}
    for sid, written in first.items():
        fields = calls[0]['text']['format']['schema']['properties']['sections']['items']['properties']
        expected = wire(fields, sid, deck['repairs'].get(sid, written))
        assert {key: stored[sid][key] for key in expected} == expected, sid
    text = delivered(job)
    assert not scripts.artifact_violations(storage.local(job.artifacts.get().file.object_key), locale)
    for fix in deck['repairs'].values():
        assert fix['heading'] in text
    for heading in deck['gone']:
        assert heading not in text


@pytest.mark.django_db
@pytest.mark.parametrize('feature', ['ai.pptx', 'ai.pdf_topic'])
def test_a_clean_document_gets_no_repair_call(customer, monkeypatch, feature):
    slides = by_id([DECKS['en']['slides'][0], DECKS['en']['slides'][1], DECKS['en']['slides'][4],
                    *DECKS['en']['repairs'].values()])
    requests = model(monkeypatch, lambda body, number: reply(body, slides))
    job, authored = run(customer, DECKS['en']['prompt'], feature=feature, pages=6, key=f'quality-clean-{feature}')
    assert job.status == 'succeeded', job.error_code
    assert len(writing_calls(requests)) == 1
    assert 'repair' not in stages(job)
    assert [provider for provider, _ in usage(job)] == ['openai']


@pytest.mark.django_db
@pytest.mark.parametrize('failure', ['raises', 'not_json', 'wrong_shape'])
def test_a_repair_that_fails_still_delivers_the_document(customer, monkeypatch, failure):
    deck = DECKS['en']
    first = by_id(deck['slides'])

    def answer(body, number):
        if not is_repair(body):
            return reply(body, first)
        if failure == 'raises':
            raise ConnectionResetError('provider dropped the connection')
        if failure == 'not_json':
            return Broken('{"sections": [{"id": "s3", "heading": "Spring')
        return {'sections': 'not a list'}

    requests = model(monkeypatch, answer)
    job, authored = run(customer, deck['prompt'], pages=6, key=f'quality-repair-fails-{failure}')
    assert job.status == 'succeeded', job.error_code
    assert ('openai_repair', 'failed') in usage(job) and ('openai', 'succeeded') in usage(job)
    attempts = ProviderAttempt.objects.filter(job=job, stage='repair')
    assert attempts.exists() and not attempts.filter(status='succeeded').exists()
    assert len(writing_calls(requests)) == 1 + attempts.count()
    # The document goes out as first written, in its own alphabet.
    stored = unpack(authored.encrypted_data)['content']
    assert stored['sections'][1]['body'] == MOON and stored['sections'][2]['body'] == MOON_REWORDED
    assert not scripts.violations(stored, 'en')
    assert 'The Moon pulls the oceans' in delivered(job)


# --- A change to selected slides ----------------------------------------------------

def generated_deck(customer, monkeypatch, slides):
    model(monkeypatch, lambda body, number: reply(body, slides, title='Ocean tides'))
    job, authored = run(customer, DECKS['en']['prompt'], pages=len(slides), key='quality-original-deck')
    assert job.status == 'succeeded', job.error_code
    return authored


def change(customer, original, ids, request, key):
    revised = create_draft(customer, {'prompt': request, 'options': {
        'revise_draft_id': str(original.id), 'revise_base_version': original.version, 'revise_section_ids': ids}})
    quote = generation_quote(customer, revised.id, revised.version)
    job, _ = submit_job(customer, quote.id, key)
    job = execute_job(job.id)
    revised.refresh_from_db()
    return job, revised


ORIGINAL = by_id([DECKS['en']['slides'][0], DECKS['en']['slides'][1], DECKS['en']['slides'][4],
                  *DECKS['en']['repairs'].values()])


@pytest.mark.django_db
def test_a_selected_slide_written_in_russian_is_repaired_without_touching_the_others(customer, monkeypatch):
    original = generated_deck(customer, monkeypatch, ORIGINAL)
    before = {s['id']: s for s in unpack(original.encrypted_data)['content']['sections']}
    clearer = slide('Harbour pilots and the tide', 'Pilots time each arrival to the rising tide in narrow channels.\n'
                    'A tide table tells them when the water is deep enough to cross the bar.', 'Show a chart.')
    russian = slide('Приливы и Луна', RUSSIAN, 'Расскажите о притяжении Луны.')
    fixed = slide('Two tides every day', 'The Earth turns through two ocean bulges every day.\n'
                  'That is why most coasts have two high tides and two low tides.', 'Use a globe.')

    def answer(body, number):
        request = sent(body)
        if request['revision']['request'].startswith('Quality repair'):
            return reply(body, {'s4': fixed})
        return reply(body, {'s3': clearer, 's4': russian})

    requests = model(monkeypatch, answer)
    job, revised = change(customer, original, ['s3', 's4'], 'Make these clearer for students.', 'quality-selected-ru')
    assert job.status == 'succeeded', job.error_code
    assert len(requests) == 2 and stages(job) == ['revision', 'repair']
    repair = sent(requests[1])
    assert repair['revision']['selected_section_ids'] == ['s4']
    assert requests[1]['instructions'].endswith(language.instructions('en'))
    after = {s['id']: s for s in unpack(revised.encrypted_data)['content']['sections']}
    assert after['s3']['heading'] == 'Harbour pilots and the tide'
    assert after['s4']['heading'] == 'Two tides every day' and after['s4']['body'] == fixed['body']
    for sid in ('s1', 's2', 's5', 's6'):
        assert after[sid] == before[sid], sid


@pytest.mark.django_db
def test_a_selected_slide_that_copies_an_unselected_one_is_repaired_alone(customer, monkeypatch):
    original = generated_deck(customer, monkeypatch, ORIGINAL)
    before = {s['id']: s for s in unpack(original.encrypted_data)['content']['sections']}
    # Asked to rework slide 3, the model hands back slide 2 again under a new heading.
    copied = slide('More about the Moon', MOON, 'Explain the pull of the Moon once more.')
    fixed = slide('Harbour pilots and the tide', 'Pilots time each arrival to the rising tide in narrow channels.\n'
                  'A tide table tells them when the water is deep enough to cross the bar.', 'Show a chart.')

    def answer(body, number):
        if sent(body)['revision']['request'].startswith('Quality repair'):
            return reply(body, {'s3': fixed})
        return reply(body, {'s3': copied})

    requests = model(monkeypatch, answer)
    job, revised = change(customer, original, ['s3'], 'Rework slide three.', 'quality-selected-copy')
    assert job.status == 'succeeded', job.error_code
    assert stages(job) == ['revision', 'repair']
    assert sent(requests[1])['revision']['selected_section_ids'] == ['s3']
    after = {s['id']: s for s in unpack(revised.encrypted_data)['content']['sections']}
    assert after['s3']['body'] == fixed['body']
    for sid in ('s1', 's2', 's4', 's5', 's6'):
        assert after[sid] == before[sid], sid


def edited(customer, draft, change):
    """The draft after the customer edits its content in the studio."""
    content = unpack(draft.encrypted_data)['content']
    change(content)
    return update_draft(customer, draft.id, {'version': draft.version, 'content': content})


HARBOUR_PILOTS = slide('Harbour pilots and the tide', 'Pilots time each arrival to the rising tide in narrow '
                       'channels.\nA tide table tells them when the water is deep enough to cross the bar.',
                       'Show a chart.')


@pytest.mark.django_db
def test_a_repair_in_a_selected_change_never_touches_a_slide_with_long_russian_notes(customer, monkeypatch):
    """Transliterating the untouched notes made them longer than a note may be, and the job failed."""
    original = generated_deck(customer, monkeypatch, ORIGINAL)
    notes = ('Здесь я подчёркиваю, что движущая сила прилива — притяжение Луны и Солнца. ' * 40)[:1990]
    original = edited(customer, original, lambda content: content['sections'][0].update(notes=notes))
    before = {s['id']: s for s in unpack(original.encrypted_data)['content']['sections']}

    def answer(body, number):
        if sent(body)['revision']['request'].startswith('Quality repair'):
            return reply(body, {'s3': HARBOUR_PILOTS})
        return reply(body, {'s3': slide('', '', '')})

    model(monkeypatch, answer)
    job, revised = change(customer, original, ['s3'], 'Rework slide three.', 'quality-selected-notes')
    assert job.status == 'succeeded', job.error_code
    assert stages(job) == ['revision', 'repair']
    after = {s['id']: s for s in unpack(revised.encrypted_data)['content']['sections']}
    assert after['s3']['body'] == HARBOUR_PILOTS['body']
    for sid in ('s1', 's2', 's4', 's5', 's6'):
        assert after[sid] == before[sid], sid
    assert after['s1']['notes'] == notes


@pytest.mark.django_db
def test_a_selected_change_leaves_every_other_page_as_the_customer_wrote_it(customer, monkeypatch):
    pages = by_id([slide('Constructors', 'Every class may define a constructor that Python calls when an object '
                         'is created.'),
                   slide('Comparisons', 'Objects compare equal when their class says they do.')])
    model(monkeypatch, lambda body, number: reply(body, pages, title='Python classes'))
    job, original = run(customer, 'A two page guide to Python classes', feature='ai.pdf_topic', pages=2,
                        key='quality-pdf-original')
    assert job.status == 'succeeded', job.error_code

    def typed(content):
        # Marks, spacing and a Russian word the customer typed themselves.
        content['title'] = 'Python classes, or классы'
        content['sections'][0]['body'] = ('  Define __init__ to set attributes; **x** stays as typed.\n'
                                          'In Russian the word is класс.')
    original = edited(customer, original, typed)
    before = unpack(original.encrypted_data)['content']
    model(monkeypatch, lambda body, number: reply(body, {'s2': {
        'heading': '**Friendly** comparisons', 'body': 'A friendlier second page about classes.\x07'}}))
    job, revised = change(customer, original, ['s2'], 'Make the second page friendlier.', 'quality-pdf-selected')
    assert job.status == 'succeeded', job.error_code
    after = unpack(revised.encrypted_data)['content']
    assert after['title'] == before['title'] and after['sections'][0] == before['sections'][0]
    # The page that was asked for is tidied as any written page is.
    assert after['sections'][1]['heading'] == 'Friendly comparisons'
    assert after['sections'][1]['body'] == 'A friendlier second page about classes.'


@pytest.mark.django_db
def test_a_whole_document_translated_on_request_is_not_translated_back(customer, monkeypatch):
    uzbek = by_id(DECKS['uz']['repairs'].values())
    model(monkeypatch, lambda body, number: reply(body, uzbek, title='Samarqand'))
    job, original = run(customer, 'Samarqand tarixi haqida 3 ta slayd tayyorlab bering', locale='uz', pages=3,
                        key='quality-uz-original')
    assert job.status == 'succeeded', job.error_code
    english = by_id([
        slide('Registan Square', 'Three famous madrasas face each other on Registan Square.\nThey were built in '
              'different centuries by different rulers.\nToday the square is the most visited place in the city.',
              'Show a photo of the square.'),
        slide('The observatory of Ulugh Beg', 'Ulugh Beg built the largest observatory of his time in Samarkand.\n'
              'Its scientists measured the positions of more than a thousand stars.\nMathematics and astronomy '
              'were taught in his madrasa.', 'Talk about the star catalogue.'),
        slide('The city today', 'Samarkand is a large centre of science and tourism in the Zarafshan valley.\nIts '
              'historic centre is on the World Heritage list.\nAn international music festival is held here every '
              'year.', 'Show photos of the modern city.')])
    requests = model(monkeypatch, lambda body, number: reply(body, english))
    revised = create_draft(customer, {'prompt': 'Ingliz tiliga tarjima qilib ber',
                                      'options': {'revise_draft_id': str(original.id)}})
    quote = generation_quote(customer, revised.id, revised.version)
    job, _ = submit_job(customer, quote.id, 'quality-uz-translated')
    job = execute_job(job.id)
    assert job.status == 'succeeded', job.error_code
    assert stages(job) == ['revision'] and len(requests) == 1
    revised.refresh_from_db()
    stored = unpack(revised.encrypted_data)['content']
    assert [s['body'] for s in stored['sections']] == [s['body'] for s in english.values()]
    # Were the request's language missed and the document kept in Uzbek, the English pages are still kept.
    missed = quality.check(stored, locale='uz', fmt='pptx', prompt='Samarqand tarixi haqida 3 ta slayd tayyorlab '
                           'bering', request='Ingliz tiliga tarjima qilib ber')
    assert missed.to_repair() == [] and len(missed.issues['foreign_passage']) == 3


@pytest.mark.django_db
def test_a_repair_reply_that_cannot_be_put_back_still_delivers_the_document(customer, monkeypatch):
    first = by_id(DECKS['en']['slides'])
    model(monkeypatch, lambda body, number: reply(body, DECKS['en']['repairs'] if is_repair(body) else first))
    real = provider.generate

    def generate(config, data, *args, **kwargs):
        raw, used = real(config, data, *args, **kwargs)
        if data.get('_stage') == 'repair':
            raw['sections'] = [s for s in raw['sections'] if s['id'] != 's4']
        return raw, used

    monkeypatch.setattr(provider, 'generate', generate)
    job, authored = run(customer, DECKS['en']['prompt'], pages=6, key='quality-repair-unusable')
    assert job.status == 'succeeded', job.error_code
    assert 'repair' in stages(job)
    stored = unpack(authored.encrypted_data)['content']
    assert stored['sections'][1]['body'] == MOON and stored['sections'][2]['body'] == MOON_REWORDED
    assert not scripts.violations(stored, 'en')


@pytest.mark.django_db
def test_a_continuing_page_loses_its_repeated_heading_without_a_model_call(customer, monkeypatch):
    repairs = list(DECKS['en']['repairs'].values())
    pages = by_id([slide('Why the tides happen', MOON), slide('Why the tides happen', repairs[1]['body']),
                   slide('Tides shape coastal life', repairs[2]['body'])])
    requests = model(monkeypatch, lambda body, number: reply(body, pages))
    job, authored = run(customer, 'A report about ocean tides for a school science class', feature='ai.pdf_topic',
                        pages=3, key='quality-continuing-page')
    assert job.status == 'succeeded', job.error_code
    assert len(writing_calls(requests)) == 1 and 'repair' not in stages(job)
    stored = unpack(authored.encrypted_data)['content']['sections']
    assert [s['heading'] for s in stored] == ['Why the tides happen', '', 'Tides shape coastal life']


# --- A long deck is written in parts that see each other ----------------------------

WORDS = ('solar wind hydro dam turbine panel grid storage battery river reservoir blade tower inverter cell '
         'silicon sunlight rooftop farm offshore onshore cable substation demand supply tariff subsidy policy '
         'investment carbon emission climate target capacity output megawatt household village factory '
         'school hospital network meter forecast season summer winter drought flood valley canyon lake '
         'pipeline export import price auction contract operator engineer technician training job wage '
         'region province city desert steppe mountain coast harbour island transport vehicle charger '
         'hydrogen electrolyser ammonia steel cement mining lithium cobalt recycling waste landfill heat '
         'pump boiler district cooling efficiency insulation window roof wall standard label audit budget').split()


def varied(index):
    """A slide no other slide repeats: its own words in its own order."""
    pick = random.Random(index)
    lines = [' '.join(pick.choice(WORDS) for _ in range(12)).capitalize() + '.' for _ in range(4)]
    return slide(f'Renewable energy point {index}', '\n'.join(lines), 'Explain this point with an example.',
                 'cover' if index == 1 else 'bullets')


@pytest.mark.django_db
def test_a_forty_slide_deck_is_written_in_four_parts_that_share_the_brief_and_language(customer, monkeypatch):
    slides = {f's{n}': varied(n) for n in range(1, 41)}
    requests = model(monkeypatch, lambda body, number: reply(body, slides, title='Renewable energy'))
    brief = ('A presentation on renewable energy for city planners, including solar power, wind turbines '
             'and hydroelectric dams.')
    job, authored = run(customer, brief, pages=40, key='quality-forty-slides')
    assert job.status == 'succeeded', job.error_code
    assert len(unpack(authored.encrypted_data)['content']['sections']) == 40
    assert stages(job) == ['generate'] * 4 and len(requests) == 4

    block = language.instructions('en')
    assert all(body['instructions'].endswith(block) for body in requests)
    assert len({body['instructions'] for body in requests}) == 1, 'one cached prefix for every part'
    inputs = [sent(body) for body in requests]
    assert [len(part['outline']['sections']) for part in inputs] == [10, 10, 10, 10]
    for part in inputs:
        assert part['required_subtopics'] == ['solar power', 'wind turbines', 'hydroelectric dams']
        assert part['output_locale'] == 'en'
    assert 'already_written' not in inputs[0]
    for number, part in enumerate(inputs[1:], start=1):
        earlier = [slides[f's{n}']['heading'] for n in range(1, number * 10 + 1)]
        assert [entry['heading'] for entry in part['already_written']] == earlier
        assert all(entry['gist'] for entry in part['already_written'])
