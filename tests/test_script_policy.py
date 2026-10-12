"""Every word a reader sees is in the alphabet of the document's language.

Uzbek and English documents are Latin only; Russian ones are Cyrillic with
Latin kept for names, URLs and identifiers. The model is told so, and still
leaks: a Cyrillic Uzbek word in a Latin document, "Москва" in an English
deck, a Cyrillic "а" slipped into "market". apps/studio/scripts.py (with
apps/studio/uzbek.py) puts each field right without losing its meaning, and
checks the rendered file before it is delivered.

These tests cover every field kind, the exact Latin spelling that comes out
(o‘ and g‘ with ‘, the tutuq belgisi as ʼ), what must survive untouched
(numbers, units, emoji, URLs, product names, source quotes), the rare
Cyrillic letters no table lists, real rendered .pdf and .pptx files, and two
whole jobs whose fake model leaks Cyrillic into the body, notes, items and
questions.
"""
import copy
import json
import re
import unicodedata

import pytest

from apps.core import storage
from apps.core.services import execute_job, submit_job
from apps.studio import scripts, uzbek
from apps.studio.domain import SLIDES, create_draft, generation_quote, unpack
from apps.studio.language import CYRILLIC
from apps.studio.models import ProviderAttempt
from apps.studio.rendering import render_pdf
from apps.studio.slides import render_pptx
from operations.integrations import save_config
from tests.test_platform import account
from tests.test_provider_optimization import transport
from tests.test_studio import paid

TURNED = '‘'   # U+2018: the house form of o‘ and g‘
TUTUQ = 'ʼ'    # U+02BC: the tutuq belgisi, Cyrillic ъ
LATIN = re.compile(r'[A-Za-z]')


def slide(sid, layout, heading, body='', notes='', items=(), columns=()):
    return {'id': sid, 'heading': heading, 'body': body, 'notes': notes, 'layout': layout,
            'items': [dict(item) for item in items], 'columns': list(columns), 'image_query': ''}


def cyrillic_left(content):
    """Every visible field that still has a Cyrillic letter, with its text (for the failure message)."""
    return {path: text for path, text in scripts.fields(content) if isinstance(text, str) and CYRILLIC.search(text)}


def shape(content):
    """What enforcing may never change: ids, order, layouts, counts and keys."""
    return {'sections': [(s['id'], s.get('layout'), sorted(s), len(s.get('items') or []),
                          len(s.get('columns') or [])) for s in content['sections']],
            'questions': [(q['id'], sorted(q), len(q.get('options') or []), q.get('marks'))
                          for q in content['questions']],
            'citations': content.get('citations')}


# An Uzbek deck written partly in Cyrillic: every field kind a reader sees, and
# the Latin each must come back as.
UZ_FIELDS = {
    ('title',): ('Сунъий интеллект', 'Sunʼiy intellekt'),
    ('sections', 0, 'heading'): ('Сунъий интеллектнинг ривожланиши', 'Sunʼiy intellektning rivojlanishi'),
    ('sections', 0, 'body'): ('Қисқача шарҳ', 'Qisqacha sharh'),
    ('sections', 0, 'notes'): ('Салом, тингловчилар', 'Salom, tinglovchilar'),
    ('sections', 1, 'heading'): ('Асосий тушунчалар', 'Asosiy tushunchalar'),
    ('sections', 1, 'body'): ('Машина ўрганиш\nНейрон тармоқлар\nКатта тил моделлари',
                              'Mashina o‘rganish\nNeyron tarmoqlar\nKatta til modellari'),
    ('sections', 1, 'notes'): ('Ҳар бир атамани тушунтиринг', 'Har bir atamani tushuntiring'),
    ('sections', 2, 'heading'): ('Рақамлар', 'Raqamlar'),
    ('sections', 2, 'items', 0, 'label'): ('Фойдаланувчилар', 'Foydalanuvchilar'),
    ('sections', 2, 'items', 0, 'text'): ('Йиллик ўсиш', 'Yillik o‘sish'),
    ('sections', 2, 'items', 0, 'value'): ('120 млн', '120 mln'),
    ('sections', 2, 'items', 1, 'label'): ('Компаниялар', 'Kompaniyalar'),
    ('sections', 2, 'items', 1, 'text'): ('Жорий этиш', 'Joriy etish'),
    ('sections', 3, 'heading'): ('Ғалаба ва Ўзбекистон', 'G‘alaba va O‘zbekiston'),
    ('sections', 3, 'columns', 0): ('Машина', 'Mashina'),
    ('sections', 3, 'columns', 1): ('Инсон', 'Inson'),
    ('sections', 3, 'items', 0, 'label'): ('Тезлик', 'Tezlik'),
    ('sections', 3, 'items', 0, 'text'): ('Юқори', 'Yuqori'),
    ('sections', 3, 'items', 0, 'value'): ('Паст', 'Past'),
    ('questions', 0, 'stem'): ('Сунъий интеллект атамаси қачон пайдо бўлган?',
                               'Sunʼiy intellekt atamasi qachon paydo bo‘lgan?'),
    ('questions', 0, 'options', 0): ('1956 йилда', '1956 yilda'),
    ('questions', 0, 'options', 1): ('Ўтган асрнинг охирида', 'O‘tgan asrning oxirida'),
    ('questions', 0, 'answer'): ('1956 йилда', '1956 yilda'),
    ('questions', 0, 'explanation'): ('Дартмут анжуманида', 'Dartmut anjumanida'),
    ('questions', 0, 'topic'): ('Тарих', 'Tarix'),
}
QUOTE = 'Ушбу иқтибос манбадан сўзма-сўз олинган.'


def leaky_uzbek():
    text = {path: cyrillic for path, (cyrillic, _) in UZ_FIELDS.items()}
    return {
        'title': text[('title',)],
        'citations': [{'asset_id': 'a1', 'page': 2, 'quote': QUOTE}],
        'questions': [{'id': 'q1', 'stem': text[('questions', 0, 'stem')],
                       'options': [text[('questions', 0, 'options', 0)], text[('questions', 0, 'options', 1)]],
                       'answer': text[('questions', 0, 'answer')], 'explanation': text[('questions', 0, 'explanation')],
                       'topic': text[('questions', 0, 'topic')], 'marks': 1}],
        'sections': [
            slide('s1', 'cover', text[('sections', 0, 'heading')], text[('sections', 0, 'body')],
                  text[('sections', 0, 'notes')]),
            slide('s2', 'bullets', text[('sections', 1, 'heading')], text[('sections', 1, 'body')],
                  text[('sections', 1, 'notes')]),
            slide('s3', 'stats', text[('sections', 2, 'heading')], items=[
                {'label': text[('sections', 2, 'items', 0, 'label')], 'text': text[('sections', 2, 'items', 0, 'text')],
                 'value': text[('sections', 2, 'items', 0, 'value')]},
                {'label': text[('sections', 2, 'items', 1, 'label')], 'text': text[('sections', 2, 'items', 1, 'text')],
                 'value': '45%'}]),
            slide('s4', 'comparison', text[('sections', 3, 'heading')],
                  columns=[text[('sections', 3, 'columns', 0)], text[('sections', 3, 'columns', 1)]], items=[
                      {'label': text[('sections', 3, 'items', 0, 'label')],
                       'text': text[('sections', 3, 'items', 0, 'text')],
                       'value': text[('sections', 3, 'items', 0, 'value')]},
                      {'label': 'Aniqlik', 'text': 'Yaxshi', 'value': 'O‘rta'}]),
        ]}


def flat(text):
    """Extracted text with line wrapping undone, so a phrase is found wherever the renderer broke it."""
    return ' '.join(text.split())


def value_at(content, path):
    for key in path:
        content = content[key]
    return content


# --- Uzbek -------------------------------------------------------------------

def test_the_house_uzbek_apostrophes_are_turned_comma_and_modifier_letter():
    assert uzbek.LETTERS['ў'] == 'o' + TURNED and uzbek.LETTERS['ғ'] == 'g' + TURNED
    assert uzbek.LETTERS['ъ'] == TUTUQ


def test_every_field_of_an_uzbek_document_comes_back_in_latin_with_its_meaning():
    content = leaky_uzbek()
    before = copy.deepcopy(content)
    fixed, paths = scripts.enforce(content, 'uz')
    for path, (_, latin) in UZ_FIELDS.items():
        assert value_at(fixed, path) == latin, path
    assert cyrillic_left(fixed) == {}
    assert scripts.violations(fixed, 'uz') == []
    # Exactly the fields that held Cyrillic are reported, and nothing else moved.
    assert set(paths) == set(UZ_FIELDS)
    assert shape(fixed) == shape(content)
    assert fixed['sections'][2]['items'][1]['value'] == '45%'
    assert fixed['citations'] == [{'asset_id': 'a1', 'page': 2, 'quote': QUOTE}], 'a source quote stays verbatim'
    assert content == before, 'the caller keeps its own copy'


@pytest.mark.parametrize('cyrillic,latin', [
    ('Сунъий интеллектнинг ривожланиши', 'Sunʼiy intellektning rivojlanishi'),
    ('Ўзбекистон Республикаси', 'O‘zbekiston Respublikasi'),
    ('ЎЗБЕКИСТОН', 'O‘ZBEKISTON'),
    ('Ер юзи', 'Yer yuzi'),
    ('Ҳамма ёшлар', 'Hamma yoshlar'),
    ('Қишлоқ хўжалиги', 'Qishloq xo‘jaligi'),
    ('Маъно ва мўъжиза', 'Maʼno va mo‘ʼjiza'),
    ('Чорсу бозори', 'Chorsu bozori'),
    ('Шаҳар маркази', 'Shahar markazi'),
])
def test_cyrillic_uzbek_words_become_standard_uzbek_latin(cyrillic, latin):
    assert scripts.to_script(cyrillic, 'uz') == latin
    assert uzbek.clean_text(cyrillic) == latin


def test_uzbek_keeps_numbers_units_emoji_urls_and_product_names():
    text = 'Тошкент шаҳри 2024 йилда 3,5 % ўсди 🚀 5 км — https://example.com/a, Python, ChatGPT, COVID-19.'
    assert scripts.to_script(text, 'uz') == ('Toshkent shahri 2024 yilda 3,5 % o‘sdi 🚀 5 km — '
                                             'https://example.com/a, Python, ChatGPT, COVID-19.')
    latin = 'O‘zbekiston: 1 200 000 so‘m (≈ $95), 25 °C, H₂O, e = mc², «Python 3.12» — 👍'
    assert scripts.to_script(latin, 'uz') == latin


def test_uzbek_apostrophes_of_every_kind_become_the_house_one():
    assert scripts.to_script("o'zbek tili, g`alaba, Oʻzbekiston, g’isht", 'uz') == \
        'o‘zbek tili, g‘alaba, O‘zbekiston, g‘isht'


def test_a_latin_uzbek_word_with_a_cyrillic_look_alike_is_pure_latin():
    leaked = 'm\u0430ktab T\u043eshkent'   # Cyrillic а and о slipped into "maktab Toshkent"
    assert CYRILLIC.search(leaked)
    assert scripts.to_script(leaked, 'uz') == 'maktab Toshkent'


@pytest.mark.parametrize('locale,mixed,latin', [
    ('uz', 'Тaққослаш', 'Taqqoslash'),   # Latin a inside Cyrillic "Таққослаш", not "Taqqoclash"
    ('uz', 'Рaҳмат', 'Rahmat'),
    ('uz', 'тaрих', 'tarix'),
    ('en', 'Мoсква', 'Moskva'),          # Latin o inside Cyrillic "Москва", not "Mockva"
    ('en', 'Еревaн', 'Yerevan'),
    ('en', 'МOСКВA', 'MOSKVA'),
])
def test_a_cyrillic_word_with_a_latin_look_alike_keeps_its_sound(locale, mixed, latin):
    assert CYRILLIC.search(mixed) and LATIN.search(mixed)
    assert scripts.to_script(mixed, locale) == latin


@pytest.mark.parametrize('locale,mixed,latin', [
    # A Cyrillic ending on a Latin word is read by sound, not shape: "лар" is lar, "сиз" is siz.
    ('uz', 'talabaлар', 'talabalar'),
    ('uz', 'kitobлар', 'kitoblar'),
    ('uz', 'Toshkentсиз', 'Toshkentsiz'),
    ('uz', 'o‘quvchiлари', 'o‘quvchilari'),
    ('uz', 'maktabдаги', 'maktabdagi'),
    ('en', 'Toshkentсиз', 'Toshkentsiz'),
    # A lone Cyrillic look-alike in a Latin word is its Latin twin.
    ('uz', 'm\u0430ktab', 'maktab'),
    ('en', 'm\u0430rket', 'market'),
    ('en', 'R\u0435\u0430ct', 'React'),    # two look-alikes in a row, and е is not "ye" after R
    ('uz', '\u043e‘zbek', 'o‘zbek'),
    # A Latin ending on a Cyrillic word was written in Latin on purpose.
    ("en", "Москва's", "Moskva's"),
    ('uz', 'Тошкентga', 'Toshkentga'),
    ('uz', 'Ўзбекистонcha', 'O‘zbekistoncha'),   # c is a look-alike, but "cha" is not one slipped in
    ('en', 'Ўзбекистонcha', 'O‘zbekistoncha'),
    ('uz', 'muҳим', 'muhim'),
])
def test_a_word_mixing_the_alphabets_is_read_by_its_main_alphabet_and_its_runs(locale, mixed, latin):
    assert CYRILLIC.search(mixed) and LATIN.search(mixed)
    assert scripts.to_script(mixed, locale) == latin
    assert scripts.to_script(latin, locale) == latin


# --- English -----------------------------------------------------------------

@pytest.mark.parametrize('cyrillic,latin', [
    ('Москва', 'Moskva'),
    ('Ереван', 'Yerevan'),
    ('МОСКВА', 'MOSKVA'),
    ('Санкт-Петербург', 'Sankt-Peterburg'),
    ('Тошкент', 'Toshkent'),
    ('Ўзбекистон', 'O‘zbekiston'),
    ('Самарқанд', 'Samarqand'),
    ('m\u0430rket', 'market'),     # Cyrillic а in a Latin word
    ('Pyth\u043en', 'Python'),     # Cyrillic о in a Latin word
])
def test_cyrillic_in_an_english_document_becomes_latin(cyrillic, latin):
    assert scripts.to_script(cyrillic, 'en') == latin


def test_an_english_sentence_keeps_everything_but_the_leaked_names():
    leaked = 'Flights from Москва to Ереван and Тошкент grew 12% in 2023 🚀 (see https://example.com/a).'
    assert scripts.to_script(leaked, 'en') == \
        'Flights from Moskva to Yerevan and Toshkent grew 12% in 2023 🚀 (see https://example.com/a).'
    clean = ("Don't miss O‘zbekiston’s 25 °C summers — 3.5% growth, COVID-19, ChatGPT, "
             'e = mc², 1,200 km/h, “quoted”, naïve café, https://example.com/a?x=1&y=2 👍')
    assert scripts.to_script(clean, 'en') == clean


def test_russian_names_in_an_english_document_keep_title_case():
    names = {'Хива': 'Khiva', 'Чехов': 'Chekhov', 'Жуков': 'Zhukov', 'Шостакович': 'Shostakovich',
             'Щукин': 'Shchukin', 'Юрий': 'Yuriy', 'Ярославль': 'Yaroslavl', 'Ёлка': 'Yolka', 'Їжак': 'Yizhak',
             'Юрий Гагарин': 'Yuriy Gagarin', 'Ёлкин': 'Yolkin', 'Антон Чехов': 'Anton Chekhov', 'Цой': 'Tsoy'}
    assert {name: scripts.to_script(name, 'en') for name in names} == names


@pytest.mark.parametrize('locale,caps,latin', [
    ('en', 'МОСКВА', 'MOSKVA'), ('en', 'ХИВА', 'KHIVA'), ('en', 'ЧЕХОВ', 'CHEKHOV'), ('en', 'США', 'SSHA'),
    ('en', 'ЄВРОПА', 'YEVROPA'),
    # A letter no Uzbek table lists is put right after the rest of its word, and keeps its capitals too.
    ('uz', 'ЄВРОПА', 'YEVROPA'), ('uz', 'ЇЖАК', 'YIJAK'), ('uz', 'ЎЗБЕКИСТОН', 'O‘ZBEKISTON'),
])
def test_an_all_caps_word_stays_all_caps(locale, caps, latin):
    assert scripts.to_script(caps, locale) == latin


# --- Russian -----------------------------------------------------------------

def test_a_russian_document_keeps_latin_names_urls_and_identifiers():
    text = 'Python и ChatGPT помогают врачам при COVID-19: https://example.com/a, ID-42, iPhone 15.'
    assert scripts.to_script(text, 'ru') == text
    content = {'title': text, 'sections': [slide('s1', 'bullets', 'Москва', text)], 'questions': [], 'citations': []}
    assert scripts.violations(content, 'ru') == []
    fixed, paths = scripts.enforce(content, 'ru')
    assert fixed == content and paths == []


def test_a_russian_document_fixes_only_latin_look_alikes_inside_cyrillic_words():
    # Latin a, p and a inside "маркет", "рынок", "Москва".
    assert scripts.to_script('мaркет, pынок и Москвa', 'ru') == 'маркет, рынок и Москва'
    content = {'title': 'Рынок', 'questions': [], 'citations': [],
               'sections': [slide('s1', 'bullets', 'Тренды', 'Новый мaркет\nPython остаётся')]}
    fixed, paths = scripts.enforce(content, 'ru')
    assert fixed['sections'][0]['body'] == 'Новый маркет\nPython остаётся'
    assert paths == [('sections', 0, 'body')]


def test_a_latin_name_with_a_cyrillic_look_alike_stays_latin_in_russian():
    assert scripts.to_script('Pyth\u043en', 'ru') == 'Python'      # not "Руthоn"
    assert scripts.to_script('\u0421hatGPT и iPh\u043ene', 'ru') == 'ChatGPT и iPhone'
    assert scripts.to_script('м\u0061ркет', 'ru') == 'маркет'
    # A Russian ending on a Latin name is neither a look-alike nor transliterated.
    assert scripts.to_script('Windowsом', 'ru') == 'Windowsом'


def test_russian_enforce_reports_exactly_the_fields_it_changed():
    content = {'title': 'Python и Windowsом', 'questions': [], 'citations': [],
               'sections': [slide('s1', 'bullets', 'Pyth\u043en', 'Новый м\u0061ркет', 'Москва'),
                            slide('s2', 'bullets', 'Тренды', 'iPhone 15, COVID-19')]}
    fixed, paths = scripts.enforce(content, 'ru')
    assert (fixed['sections'][0]['heading'], fixed['sections'][0]['body']) == ('Python', 'Новый маркет')
    assert paths == [('sections', 0, 'heading'), ('sections', 0, 'body')]
    assert fixed['title'] == content['title'] and fixed['sections'][1] == content['sections'][1]
    assert scripts.enforce(fixed, 'ru') == (fixed, [])


# --- Rare Cyrillic -----------------------------------------------------------

def every_cyrillic_code_point():
    ranges = [(0x0400, 0x052F), (0x1C80, 0x1C8F), (0x2DE0, 0x2DFF), (0xA640, 0xA69F)]
    points = [chr(c) for start, end in ranges for c in range(start, end + 1)] + ['ᴫ', 'ᵸ']
    return [c for c in points if CYRILLIC.match(c)]


@pytest.mark.parametrize('locale', ['uz', 'en'])
def test_no_cyrillic_code_point_survives_in_uzbek_or_english(locale):
    """Kazakh, Ukrainian, Serbian, the Supplement block, historic letters and combining marks alike."""
    survivors = {}
    for letter in every_cyrillic_code_point():
        for text in (letter, f'a{letter}b', f'{letter}{letter.upper()}x'):
            result = scripts.to_script(text, locale)
            if CYRILLIC.search(result):
                survivors[text] = result
    assert survivors == {}


@pytest.mark.parametrize('locale', ['uz', 'en'])
def test_rare_letters_are_written_as_their_latin_sound(locale):
    assert scripts.to_script('әлем ң ө ү ұ һ і ї є ґ ђ ћ џ', locale) == 'alem ng o u u h i yi ye g dj c dz'
    assert scripts.to_script('Қазақстан', locale) == 'Qazaqstan'
    # The Supplement block and combining marks: no Cyrillic, and the marks themselves are dropped.
    result = scripts.to_script('Ԁ ԓ ԯ сл҃во ⷠ', locale)
    assert not CYRILLIC.search(result)
    assert 'slvo' in result and '҃' not in result and 'ⷠ' not in result


@pytest.mark.parametrize('locale,composed,latin', [
    ('uz', 'йўл ёз', 'yo‘l yoz'),
    ('en', 'Йошкар-Ола', 'Yoshkar-Ola'),
    ('en', 'Ёлкин и Їжак', 'Yolkin i Yizhak'),
])
def test_decomposed_cyrillic_letters_read_like_composed_ones(locale, composed, latin):
    decomposed = unicodedata.normalize('NFD', composed)
    assert decomposed != composed
    result = scripts.to_script(decomposed, locale)
    assert not any(unicodedata.combining(c) for c in result)    # not "ĭŭl yëz"
    assert result == latin


# --- enforce / violations ----------------------------------------------------

@pytest.mark.parametrize('locale', ['uz', 'en'])
def test_enforce_is_idempotent(locale):
    once, paths = scripts.enforce(leaky_uzbek(), locale)
    assert paths and cyrillic_left(once) == {}
    twice, again = scripts.enforce(once, locale)
    assert twice == once and again == []


@pytest.mark.parametrize('locale', ['uz', 'en', 'ru'])
def test_enforce_is_idempotent_on_mixed_names_and_capitals(locale):
    text = ('Тaққослаш talabaлар Мoсква\'s m\u0430rket Pyth\u043en Ўзбекистонcha Хива ХИВА Ёлкин '
            + unicodedata.normalize('NFD', 'йўл'))
    content = {'title': text, 'questions': [], 'citations': [], 'sections': [slide('s1', 'bullets', text, text)]}
    once, paths = scripts.enforce(content, locale)
    assert len(paths) == 3
    twice, again = scripts.enforce(once, locale)
    assert twice == once and again == []
    if locale != 'ru':
        assert cyrillic_left(once) == {}
        assert once['title'] == ('Taqqoslash talabalar Moskva\'s market Python O‘zbekistoncha '
                                 + ('Xiva XIVA Yolkin yo‘l' if locale == 'uz' else 'Khiva KHIVA Yolkin yo‘l'))


def test_violations_name_paths_only_and_only_for_latin_languages():
    content = leaky_uzbek()
    found = scripts.violations(content, 'uz')
    assert set(found) == set(UZ_FIELDS)
    assert all(isinstance(path, tuple) for path in found), 'paths, never the customer text'
    assert scripts.violations(content, 'en') == found
    assert scripts.violations(content, 'ru') == []
    # Citations are source quotes, never a violation.
    quote_only = {'title': 'Manba', 'sections': [slide('s1', 'bullets', 'Iqtibos', 'Matn')], 'questions': [],
                  'citations': [{'asset_id': 'a1', 'page': 1, 'quote': QUOTE}]}
    assert scripts.violations(quote_only, 'uz') == []
    assert scripts.enforce(quote_only, 'uz') == (quote_only, [])


def test_citations_are_never_touched_in_any_language():
    for locale in ('uz', 'en', 'ru'):
        content = leaky_uzbek()
        content['citations'] = [{'asset_id': 'a1', 'page': 2, 'quote': QUOTE},
                                {'asset_id': 'a2', 'page': 3, 'quote': 'Москвa, Pyth\u043en'}]
        fixed, _ = scripts.enforce(content, locale)
        assert fixed['citations'] == content['citations'], locale


def test_enforce_refuses_content_it_could_not_put_right(monkeypatch):
    monkeypatch.setattr(scripts, 'to_script', lambda text, locale: text)
    with pytest.raises(scripts.ScriptPolicyError) as raised:
        scripts.enforce(leaky_uzbek(), 'uz')
    assert set(raised.value.paths) == set(UZ_FIELDS)
    assert 'Сунъий' not in str(raised.value), 'the error names fields, never their text'


# --- Rendered files ----------------------------------------------------------

UZ_WORDS = ['Sunʼiy intellektning rivojlanishi', 'Mashina o‘rganish', 'Har bir atamani tushuntiring',
            'Foydalanuvchilar', 'Yillik o‘sish', 'G‘alaba va O‘zbekiston', 'Tezlik', 'Yuqori',
            'Sunʼiy intellekt atamasi qachon paydo bo‘lgan?', 'O‘tgan asrning oxirida', 'Savollar', 'Javoblar']


def test_an_uzbek_deck_renders_with_no_cyrillic_left(tmp_path):
    fixed, _ = scripts.enforce(leaky_uzbek(), 'uz')
    path = tmp_path / 'deck.pptx'
    result = render_pptx(fixed, path, 'uz')
    assert result['metadata']['layouts'] == ['cover', 'bullets', 'stats', 'comparison', 'questions']
    assert scripts.artifact_violations(path, 'uz') == []
    text = flat(scripts.artifact_text(path))
    assert not CYRILLIC.search(text)
    for words in UZ_WORDS:
        assert words in text, words


def test_an_uzbek_document_renders_with_no_cyrillic_left(tmp_path):
    content = leaky_uzbek()
    content['sections'] = [
        {'id': 's1', 'heading': 'Сунъий интеллектнинг ривожланиши', 'notes': '',
         'body': 'Тошкентда 2024 йилда 5 км йўл қурилди.\nМашина ўрганиш тез ривожланмоқда.'},
        {'id': 's2', 'heading': 'Жадвал', 'body': 'Қуйидаги жадвал', 'notes': '', 'layout': 'table',
         'items': [{'label': 'Шаҳар', 'text': 'Аҳоли', 'value': '3 млн'}], 'columns': ['Номи', 'Изоҳ', 'Сон'],
         'image_query': ''},
        {'id': 's3', 'heading': 'Рўйхат', 'body': '', 'notes': '', 'layout': 'list',
         'items': [{'label': 'Биринчи', 'text': 'қадам', 'value': ''}], 'columns': [], 'image_query': ''},
        {'id': 's4', 'heading': 'Эслатма', 'body': '', 'notes': '', 'layout': 'callout',
         'items': [{'label': 'Муҳим', 'text': 'эслаб қолинг', 'value': ''}], 'columns': [], 'image_query': ''},
    ]
    content['citations'] = []
    fixed, _ = scripts.enforce(content, 'uz')
    path = tmp_path / 'document.pdf'
    render_pdf(fixed, path, 'uz')
    assert scripts.artifact_violations(path, 'uz') == []
    text = flat(scripts.artifact_text(path))
    for words in ('Sunʼiy intellektning rivojlanishi', 'Toshkentda 2024 yilda 5 km yo‘l qurildi.', 'Jadval',
                  'Shahar', 'Aholi', '3 mln', 'Izoh', 'Ro‘yxat', 'Birinchi', 'Muhim', 'eslab qoling', 'Savollar',
                  'O‘tgan asrning oxirida'):
        assert words in text, words


def test_an_uzbek_file_drawn_from_unchecked_content_is_caught(tmp_path):
    deck, document = tmp_path / 'deck.pptx', tmp_path / 'document.pdf'
    render_pptx(leaky_uzbek(), deck, 'uz')
    render_pdf(leaky_uzbek(), document, 'uz')
    for path in (deck, document):
        found = scripts.artifact_violations(path, 'uz')
        assert 'Сунъий' in found and 'бўлган' in found, path.name
        assert scripts.artifact_violations(path, 'en') == found
        assert scripts.artifact_violations(path, 'ru') == [], 'Russian files are Cyrillic by right'
    # The speaker notes are read too.
    notes_only = leaky_uzbek()
    notes_only, _ = scripts.enforce(notes_only, 'uz')
    notes_only['sections'][1]['notes'] = 'Ҳар бир атамани тушунтиринг'
    render_pptx(notes_only, deck, 'uz')
    assert scripts.artifact_violations(deck, 'uz') == sorted({'Ҳар', 'бир', 'атамани', 'тушунтиринг'})


def test_the_customers_own_brand_name_is_allowed_in_cyrillic(tmp_path):
    fixed, _ = scripts.enforce(leaky_uzbek(), 'uz')
    style = {'brand_name': 'Зарафшон'}
    deck, document = tmp_path / 'deck.pptx', tmp_path / 'document.pdf'
    render_pptx(fixed, deck, 'uz', style=style)
    render_pdf(fixed, document, 'uz', style=style)
    for path in (deck, document):
        assert scripts.artifact_violations(path, 'uz') == ['Зарафшон'], path.name
        assert scripts.artifact_violations(path, 'uz', 'Зарафшон') == [], path.name


def leaky_english():
    return {
        'title': 'Silk Road cities',
        'citations': [],
        'questions': [{'id': 'q1', 'stem': 'Which city lies on the Зарафшон river?',
                       'options': ['Самарқанд', 'Москва'], 'answer': 'Самарқанд',
                       'explanation': 'Самарқанд grew on the river.', 'topic': 'Ипак йўли', 'marks': 1}],
        'sections': [
            slide('s1', 'cover', 'Silk Road cities', 'From Москва to Ереван'),
            slide('s2', 'bullets', 'Trade routes', 'Caravans crossed Бухоро\nSilk reached Москва\nThe m\u0430rket grew',
                  notes='Mention Тошкент and Ереван.'),
            slide('s3', 'timeline', 'Key dates', items=[
                {'label': 'Самарқанд founded', 'text': 'An early oasis city', 'value': '700 BC'},
                {'label': 'Москва trade fair', 'text': 'Merchants met there', 'value': '1500'},
                {'label': 'Railway to Тошкент', 'text': 'A new route opened', 'value': '1888'}]),
            slide('s4', 'table', 'Distances', columns=['Route', 'Км'], items=[
                {'label': 'Москва → Ереван', 'text': '1 790 km', 'value': ''},
                {'label': 'Самарқанд → Бухоро', 'text': '270 км', 'value': ''}]),
        ]}


EN_WORDS = ['From Moskva to Yerevan', 'Caravans crossed Bukhoro', 'Silk reached Moskva', 'The market grew',
            'Mention Toshkent and Yerevan.', 'Samarqand founded', 'Railway to Toshkent', 'Moskva → Yerevan', '270 km',
            'Which city lies on the Zarafshon river?']


def test_english_deck_and_document_render_with_no_cyrillic_left(tmp_path):
    fixed, paths = scripts.enforce(leaky_english(), 'en')
    assert cyrillic_left(fixed) == {} and ('sections', 1, 'notes') in paths and ('questions', 0, 'topic') in paths
    assert fixed['questions'][0]['topic'] == 'Ipak yo‘li'
    deck, document = tmp_path / 'deck.pptx', tmp_path / 'document.pdf'
    drawn = render_pptx(fixed, deck, 'en')
    assert drawn['metadata']['layouts'] == ['cover', 'bullets', 'timeline', 'table', 'questions']
    render_pdf(fixed, document, 'en')
    for path in (deck, document):
        assert scripts.artifact_violations(path, 'en') == [], path.name
        text = flat(scripts.artifact_text(path))
        assert not CYRILLIC.search(text), path.name
        assert 'Samarqand' in text and 'Moskva' in text and 'Yerevan' in text, path.name
    deck_text = flat(scripts.artifact_text(deck))
    for words in EN_WORDS:
        assert words in deck_text, words
    assert 'Answers: 1. Samarqand' in deck_text


# --- Whole jobs ----------------------------------------------------------------

def fill(schema, value):
    """`value` shaped to exactly the keys and types the request's schema asks for."""
    kind = schema['type']
    if kind == 'object':
        value = value if isinstance(value, dict) else {}
        return {key: fill(sub, value.get(key)) for key, sub in schema['properties'].items()}
    if kind == 'array':
        return [fill(schema['items'], item) for item in (value or [])]
    if 'enum' in schema:
        return value if value in schema['enum'] else schema['enum'][0]
    if kind == 'string':
        return value if isinstance(value, str) else ''
    if kind == 'integer':
        return value if type(value) is int else 1
    if kind == 'boolean':
        return True if value is None else value
    raise AssertionError(kind)


def leaky_model(sections, questions, title, addition=''):
    """A fake model that writes the outline's sections, leaking Cyrillic as `sections` says."""
    calls = []

    def answer(body, number):
        schema = body['text']['format']['schema']
        sent = json.loads(body['input'])
        calls.append(body['text']['format']['name'])
        if body['text']['format']['name'] == 'additions':
            return fill(schema, {'sections': [{'id': s['id'], 'addition': addition} for s in sent['sections']]})
        ids = [s['id'] for s in sent['outline']['sections']]
        assert len(ids) == len(sections), 'the fake writes the whole outline in one call'
        reply = {'title': title, 'answer_supported': True, 'citations': [], 'design': 'lagoon',
                 'sections': [{**section, 'id': sid} for sid, section in zip(ids, sections)],
                 'questions': questions[:sent.get('max_questions', 0)]}
        return fill(schema, reply)

    return answer, calls


def run(customer, draft, key):
    quote = generation_quote(customer, draft.id, draft.version)
    job, _ = submit_job(customer, quote.id, key)
    return execute_job(job.id)


UZ_QUESTIONS = [
    {'id': 'q1', 'stem': 'Sunʼiy intellekt atamasi qachon paydo bo‘lgan?', 'options': ['1956 йилда', '1990 yilda'],
     'answer': '1956 йилда', 'explanation': 'Дартмут анжуманида', 'topic': 'Тарих', 'marks': 1},
    {'id': 'q2', 'stem': 'Нейрон тармоқ нима?', 'options': ['Ҳисоблаш модели', 'Kompyuter qismi'],
     'answer': 'Ҳисоблаш модели', 'explanation': 'Миянинг соддалаштирилган модели', 'topic': 'Асослар', 'marks': 1},
]


@pytest.mark.django_db
def test_an_uzbek_deck_job_delivers_no_cyrillic_when_the_model_leaks_it(settings, monkeypatch):
    settings.DEBUG = True
    customer = paid(settings, account())
    save_config('ai', {'mode': 'openai', 'model': 'gpt-5.6-luna', 'api_key': 'sk-offline-test-only'})
    draft = create_draft(customer, {'feature_id': SLIDES, 'output_locale': 'uz', 'options': {'pages': 4},
                                    'prompt': "Sun'iy intellekt haqida taqdimot, oxirida 2 ta savol"})
    data = unpack(draft.encrypted_data)
    assert data['output_locale'] == 'uz' and len(data['content']['sections']) == 3
    sections = [
        {'heading': 'Sunʼiy intellekt', 'body': 'Қисқача шарҳ', 'notes': '', 'layout': 'cover'},
        {'heading': 'Asosiy tushunchalar', 'layout': 'bullets',
         'body': ('Mashina ўрганиш ma’lumotdan foydalanadi\nNeyron тармоқлар miyaga o‘xshaydi\n'
                  'Katta til modellari matn yozadi'),
         'notes': 'Ҳар бир атамани мисол билан тушунтиринг'},
        {'heading': 'Рақамлар', 'layout': 'stats', 'body': '', 'notes': 'Манба: йиллик ҳисобот',
         'items': [{'label': 'Фойдаланувчилар', 'text': 'Йиллик ўсиш', 'value': '120 млн'},
                   {'label': 'Kompaniyalar', 'text': 'Жорий этиш', 'value': '45%'}]},
    ]
    answer, calls = leaky_model(sections, UZ_QUESTIONS, 'Сунъий интеллект')
    sent = transport(monkeypatch, answer)
    job = run(customer, draft, 'script-policy-uz-deck')
    assert job.status == 'succeeded', job.error_code
    assert json.loads(sent[0]['input'])['output_script'] == 'latin', 'the model was told, and leaked anyway'
    path = storage.local(job.artifacts.get().file.object_key)
    assert scripts.artifact_violations(path, 'uz') == []
    text = flat(scripts.artifact_text(path))
    assert not CYRILLIC.search(text)
    for words in ('Sunʼiy intellekt', 'Qisqacha sharh', 'Mashina o‘rganish', 'Neyron tarmoqlar',
                  'Har bir atamani misol bilan tushuntiring', 'Raqamlar', 'Foydalanuvchilar', 'Yillik o‘sish',
                  '120 mln', 'Joriy etish', 'Manba: yillik hisobot', 'Neyron tarmoq nima?', 'Savollar',
                  'B) Kompyuter qismi', 'Hisoblash modeli', 'Javoblar: 1. 1956 yilda; 2. Hisoblash modeli'):
        assert words in text, words
    stored = unpack(type(draft).objects.get(pk=draft.pk).encrypted_data)['content']
    assert cyrillic_left(stored) == {}
    assert stored['title'] == 'Sunʼiy intellekt'
    assert [s['id'] for s in stored['sections']] == [s['id'] for s in data['content']['sections']]
    assert [s['layout'] for s in stored['sections']] == ['cover', 'bullets', 'stats']
    assert stored['questions'][1]['explanation'] == 'Miyaning soddalashtirilgan modeli'
    # The alphabet is put right without asking the model again.
    assert calls == ['document']
    assert not ProviderAttempt.objects.filter(job=job, stage='repair').exists()


EN_QUESTIONS = [
    {'id': 'q1', 'stem': 'Which city lies on the Зарафшон river?', 'options': ['Самарқанд', 'Москва'],
     'answer': 'Самарқанд', 'explanation': 'It grew in the Зарафшон valley.', 'topic': 'Ипак йўли', 'marks': 1},
    {'id': 'q2', 'stem': 'Where did the northern route end?', 'options': ['Ереван', 'Kashgar'],
     'answer': 'Ереван', 'explanation': 'Caravans reached the Caucasus.', 'topic': 'Routes', 'marks': 1},
]


@pytest.mark.django_db
def test_an_english_document_job_delivers_no_cyrillic_when_the_model_leaks_it(settings, monkeypatch):
    settings.DEBUG = True
    customer = paid(settings, account())
    save_config('ai', {'mode': 'openai', 'model': 'gpt-5.6-luna', 'api_key': 'sk-offline-test-only'})
    draft = create_draft(customer, {'output_locale': 'en', 'options': {'pages': 2},
                                    'prompt': 'A report on the cities of the Silk Road with a table of cities '
                                              'and 2 questions at the end'})
    data = unpack(draft.encrypted_data)
    assert data['output_locale'] == 'en' and data['output_format'] == 'pdf'
    assert data['options']['question_count'] == 2 and data['options']['wants_layouts']
    sections = [
        {'heading': 'Caravan cities', 'layout': 'text', 'notes': 'Не показывать',
         'body': 'Merchants travelled from Москва to Самарқанд along the northern route, trading silk, '
                 'spices and paper for many centuries.\nThe m\u0430rket towns of Бухоро grew rich on this trade.'},
        {'heading': 'Cities and distances', 'layout': 'table', 'notes': '',
         'body': 'Distances between the main stops changed little before the railway reached Тошкент.',
         'columns': ['City', 'Region', 'Distance'],
         'items': [{'label': 'Самарқанд', 'text': 'Зарафшон valley', 'value': '300 км'},
                   {'label': 'Ереван', 'text': 'South Caucasus', 'value': '2 000 km'}]},
    ]
    answer, calls = leaky_model(sections, EN_QUESTIONS, 'Ипак йўли',
                                addition='Later travellers from Москва described the bazaars of Бухоро in detail.')
    sent = transport(monkeypatch, answer)
    job = run(customer, draft, 'script-policy-en-document')
    assert job.status == 'succeeded', job.error_code
    assert json.loads(sent[0]['input'])['output_language'] == 'English'
    path = storage.local(job.artifacts.get().file.object_key)
    assert scripts.artifact_violations(path, 'en') == []
    text = flat(scripts.artifact_text(path))
    assert not CYRILLIC.search(text)
    for words in ('Ipak yo‘li', 'from Moskva to Samarqand', 'The market towns of Bukhoro', 'Toshkent', 'Zarafshon',
                  'Yerevan', '300 km', 'Which city lies on the Zarafshon river?'):
        assert words in text, words
    stored = unpack(type(draft).objects.get(pk=draft.pk).encrypted_data)['content']
    assert cyrillic_left(stored) == {}
    assert [s['id'] for s in stored['sections']] == [s['id'] for s in data['content']['sections']]
    assert stored['sections'][1]['layout'] == 'table' and len(stored['sections'][1]['items']) == 2
    assert stored['questions'][0]['options'] == ['Samarqand', 'Moskva']
    assert stored['questions'][1]['answer'] == 'Yerevan'
    # Two short sections make one page of two, so the page top-up runs after the
    # check; what it adds is put into Latin as well.
    assert calls == ['document', 'additions']
    assert 'Later travellers from Moskva described the bazaars of Bukhoro in detail.' in text
    assert 'Later travellers from Moskva described the bazaars of Bukhoro in detail.' in stored['sections'][0]['body']
    assert not ProviderAttempt.objects.filter(job=job, stage='repair').exists()


@pytest.mark.django_db
def test_a_file_that_still_has_cyrillic_is_never_delivered(settings, monkeypatch):
    """The last gate: were the field check skipped, the rendered file itself fails the job."""
    from apps.studio import quality
    settings.DEBUG = True
    customer = paid(settings, account())
    save_config('ai', {'mode': 'openai', 'model': 'gpt-5.6-luna', 'api_key': 'sk-offline-test-only'})
    draft = create_draft(customer, {'feature_id': SLIDES, 'output_locale': 'uz', 'options': {'pages': 2},
                                    'prompt': "Sun'iy intellekt haqida taqdimot"})
    sections = [{'heading': 'Sunʼiy intellekt', 'body': 'Qisqacha sharh', 'notes': '', 'layout': 'cover'},
                {'heading': 'Asosiy tushunchalar', 'body': 'Mashina o‘rganish\nNeyron tarmoqlar', 'layout': 'bullets',
                 'notes': 'Ҳар бир атамани тушунтиринг'}]
    answer, _ = leaky_model(sections, [], 'Sunʼiy intellekt')
    transport(monkeypatch, answer)
    monkeypatch.setattr(quality, 'finish', lambda config, data, content, **kwargs: (content, {}))
    job = run(customer, draft, 'script-policy-gate')
    assert job.status == 'failed' and job.error_code == 'script_policy'
    assert not job.artifacts.exists()
