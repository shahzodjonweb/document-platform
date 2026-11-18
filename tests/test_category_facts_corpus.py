"""The facts corpus: every entry's own example messages lose nothing, and every invented fact is caught.

This is the tick gate of architecture section 4. A category is ticked only
with both rates at zero on its own copy:

- the false-blank rate: each example and pool message, as the customer's whole
  description, must pass `ground` and `guard` unchanged; its names must be found
  with the endings Uzbek, Russian and English give them, and its numbers in the
  other ways they are written ("1 150 000", "1.150.000", "3-noyabr", "03.11");
- the miss rate: each invented sentence of tests/fixtures/categories/invented.json
  (a person, a sum, a date, a phone, a decree, a law, a quotation not in the
  message) must be caught in every language against every message, and so
  must a figure written as words in a paper's grounded part.

Every entry present is covered as it lands: the C2 packages add theirs, and
their examples and pools are tested here without a line changing.
"""
import json
from pathlib import Path

import pytest

from apps.studio import categories
from apps.studio.categories import facts, finish, numbers
from apps.studio.language import CYRILLIC

INVENTED = json.loads((Path(__file__).parent / 'fixtures' / 'categories' / 'invented.json').read_text('utf-8'))
LANGUAGES = ('uz', 'ru', 'en')
UZ_MONTHS = ('yanvar', 'fevral', 'mart', 'aprel', 'may', 'iyun', 'iyul', 'avgust', 'sentabr', 'oktabr', 'noyabr',
             'dekabr')
RU_MONTHS = ('января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября',
             'ноября', 'декабря')
EN_MONTHS = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
             'November', 'December')


def entries():
    return [entry for feature in ('ai.pdf_topic', 'ai.pptx') for entry in categories.for_feature(feature)]


def messages():
    found = []
    for entry in entries():
        bot = entry.raw['bot']
        for number, text in enumerate((*bot['examples'], *bot.get('pool', ()))):
            for locale in LANGUAGES:
                found.append(pytest.param(entry.id, text[locale], id=f'{entry.id}-{number}-{locale}'))
    return found


def trusted(entry_id, text):
    return facts.trusted({'prompt': text, 'options': {'category': entry_id}})


def endings(word):
    """The forms a sentence gives a name: Uzbek and English endings in Latin, Russian declension in Cyrillic."""
    if CYRILLIC.search(word):
        if word[-1] in 'ая':
            return [word[:-1] + ending for ending in ('ы', 'е', 'у', 'ой')]
        if word[-1] == 'й':
            return [word[:-1] + ending for ending in ('я', 'ю', 'ем')]
        if word[-1].lower() in 'бвгджзклмнпрстфхцчшщ':
            return [word + ending for ending in ('а', 'у', 'ом', 'е')]
        return []
    return [word + ending for ending in ('ning', 'ni', 'ga', 'da', 'dan', '’s')]


def names(text):
    """Every capitalised word of a message that is a word (three letters or more, not an acronym)."""
    return sorted({word for word in facts.WORD.findall(text)
                   if word[0].isupper() and any(char.islower() for char in word)
                   and sum(char.isalpha() for char in word) >= 3})


def written_otherwise(number):
    """Other ways of writing a number of a message, each meaning what it means."""
    if number.kind == 'date':
        day, month = (int(part) for part in number.value[2:].split('.'))
        return [f'{day}-{UZ_MONTHS[month - 1]}', f'{day} {RU_MONTHS[month - 1]}', f'{day} {EN_MONTHS[month - 1]}',
                f'{EN_MONTHS[month - 1]} {day}', f'{day:02}.{month:02}']
    if number.kind == 'time':
        hour, minutes = number.value[2:].split(':')
        return [f'{hour}:{minutes}', f'{int(hour):02}:{minutes}'] + ([hour] if minutes == '00' else [])
    if number.kind == 'phone':
        digits = number.value
        last = digits[-9:]
        forms = [digits, f'{last[:2]} {last[2:5]} {last[5:7]} {last[7:]}',
                 f'({last[:2]}) {last[2:5]}-{last[5:7]}-{last[7:]}']
        return forms + ([f'+{digits}'] if len(digits) == 12 else [])
    if number.kind == 'decimal':
        return [number.value.replace('.', ','), number.value]
    if number.kind in ('integer', 'amount', 'scaled') and '.' not in number.value:
        value = int(number.value)
        if value < 1000 or 1900 <= value <= 2100:
            return [str(value)]
        grouped = f'{value:,}'
        return [grouped, grouped.replace(',', '.'), grouped.replace(',', ' '), grouped.replace(',', '\u00a0'),
                str(value)]
    return [number.value]


def test_the_corpus_covers_every_entry_present():
    assert entries(), 'the catalogue holds no entry'
    assert all(entry.raw['bot']['examples'] for entry in entries())
    assert set(INVENTED) - {'about'} == set(LANGUAGES)
    kinds = {item['kind'] for item in INVENTED['uz']}
    assert {'name', 'sum', 'date', 'decree', 'quote'} <= kinds
    assert all({item['kind'] for item in INVENTED[locale]} == kinds for locale in LANGUAGES)


@pytest.mark.parametrize('entry_id, text', messages())
def test_a_message_loses_none_of_its_own_facts(entry_id, text):
    """The false-blank rate: the customer's own words, names and numbers are all found, however written."""
    known = trusted(entry_id, text)
    assert facts.ground(text, known) == (text, [])
    assert facts.guard(text, known) == (text, [])
    # A paper's grounded parts also read the numbers written as words (finish.ground_paper): the message's own
    # "ikki hafta", "пять лет" or "two hundred" must be found as the values they are.
    assert facts.guard(text, known, checks=('numbers',), words=True) == (text, [])
    # And as a paper's grounded part reads it, names strictly, an organisation's opening word held by its shape.
    assert finish.ground_paper(text, known) == (text, [])
    blanked = [form for word in names(text) for form in [word, *endings(word)]
               if not facts.supported(form, 'person', known)]
    assert not blanked, f'names of the message blanked: {blanked}'
    blanked = [form for number in numbers.found(text) for form in written_otherwise(number)
               if not facts.supported(form, 'number', known) or facts.ground(form, known)[1]]
    assert not blanked, f'numbers of the message blanked: {blanked}'


# Figures written as words that no example or pool message gives, as a model invents them in a letter or a plan.
SPELLED_INVENTED = {
    'uz': 'Loyiha qiymati uch yuz qirq yetti million so‘mni tashkil etadi.',
    'ru': 'У меня более семнадцати лет опыта, а команда насчитывает триста сорок семь человек.',
    'en': 'With over seventeen years of experience, I served three hundred and forty-seven clients.',
}


# The same as they are commonly spoken: a count fused to what it counts, half a scale, an Uzbek case ending, a bare
# "ming", a compound with "and".
SPOKEN_INVENTED = {
    'uz': 'Yiliga ming yetti yuz tonna non sotiladi, mijozlar soni yetmish uchtadan oshadi.',
    'ru': 'У меня семнадцатилетний опыт, а оборот превысил полмиллиарда.',
    'en': 'We served one thousand and seventy-three clients.',
}


@pytest.mark.parametrize('entry_id, text', messages())
def test_every_invented_figure_written_in_words_is_caught_in_a_paper(entry_id, text):
    known = trusted(entry_id, text)
    missed = [(locale, sentence) for invented in (SPELLED_INVENTED, SPOKEN_INVENTED)
              for locale, sentence in invented.items()
              if 'ground:number' not in facts.guard(sentence, known, checks=('numbers',), words=True)[1]]
    assert not missed, f'invented figures in words that passed: {missed}'


@pytest.mark.parametrize('entry_id, text', messages())
def test_every_invented_fact_is_caught(entry_id, text):
    """The miss rate: an invented person, sum, date, phone, decree, law or quotation never passes."""
    known = trusted(entry_id, text)
    missed = []
    for locale in LANGUAGES:
        for item in INVENTED[locale]:
            if item.get('paper'):
                continue  # read as a paper's grounded part reads it (below), where a sentence's first word is held
            written, codes = facts.ground(item['text'], known)
            if item['code'] not in codes or written == item['text']:
                missed.append((locale, item['kind'], 'ground'))
            # A paper in another language than the message lets a name through in the spellings a translation
            # gives it, never one the customer did not give, nor a number, quotation or law.
            written, codes = facts.ground(item['text'], known, translated=True)
            if item['code'] not in codes:
                missed.append((locale, item['kind'], 'translated'))
            if item.get('guard'):
                written, codes = facts.guard(item['text'], known)
                if item['code'] not in codes:
                    missed.append((locale, item['kind'], 'guard'))
    assert not missed, f'invented facts that passed: {missed}'


@pytest.mark.parametrize('entry_id, text', messages())
def test_every_invented_organisation_opening_a_sentence_is_caught_in_a_paper(entry_id, text):
    """The miss rate of a paper's grounded part: an organisation's name opening a sentence, held by its shape."""
    known = trusted(entry_id, text)
    missed = [(locale, item['text']) for locale in LANGUAGES for item in INVENTED[locale] if item.get('paper')
              and item['code'] not in finish.ground_paper(item['text'], known)[1]]
    assert not missed, f'invented organisations that passed: {missed}'
