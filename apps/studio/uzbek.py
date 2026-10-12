"""Uzbek in the Latin alphabet, always.

Customers complained that Latin documents came back with words in Cyrillic
letters ("Krilcha harflarda yozilgan ayrim joylarda…", "Rus alifbosini
ishlatma"), and since 2026-10-12 Uzbek is written only in Latin, whatever
alphabet the description used. The model is told so in every call; this
catches what it still gets wrong: a Cyrillic word is transliterated, a word
that mixes the two alphabets is put into Latin, and the several apostrophes of
o‘ and g‘ become one. apps/studio/scripts.py applies it to every field.
"""
import itertools
import re

LETTERS = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo', 'ж': 'j', 'з': 'z',
    'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r',
    'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'x', 'ц': 's', 'ч': 'ch', 'ш': 'sh', 'щ': 'sh',
    'ъ': 'ʼ', 'ы': 'i', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya', 'ў': 'o‘', 'қ': 'q', 'ғ': 'g‘',
    'ҳ': 'h',
}
VOWELS = set('аеёиоуэюяў')
# Letters that look the same in both alphabets, for words that mix them: a
# word that does is almost always one alphabet with a look-alike slipped in.
TWINS = {'а': 'a', 'е': 'e', 'о': 'o', 'р': 'p', 'с': 'c', 'х': 'x', 'у': 'y', 'і': 'i',
         'А': 'A', 'В': 'B', 'Е': 'E', 'К': 'K', 'М': 'M', 'Н': 'H', 'О': 'O', 'Р': 'P', 'С': 'C',
         'Т': 'T', 'Х': 'X', 'У': 'Y', 'І': 'I'}
LATIN_TWINS = {lat: cyr for cyr, lat in TWINS.items() if cyr not in 'іІ'}
CYRILLIC = re.compile('[\u0400-\u052F\u1C80-\u1C8F\u2DE0-\u2DFF\uA640-\uA69F]')
UZBEK_LETTERS = re.compile(r'[ЎўҚқҒғҲҳ]')
LATIN = re.compile(r'[A-Za-z]')
WORD = re.compile(r"[\w\u0400-\u052F'‘’ʻʼ`]+")
# o‘ and g‘ are typed with whichever apostrophe is to hand; the house form is ‘.
TURNED = re.compile(r"(?<=[oOgG])['’ʻ`´](?=\w)")


def to_latin(word):
    """A Cyrillic Uzbek word in the Latin alphabet."""
    out = []
    for position, letter in enumerate(word):
        lower = letter.lower()
        if lower not in LETTERS:
            out.append(letter)
            continue
        value = LETTERS[lower]
        # е is "ye" at the start of a word and after a vowel: ер → yer, оila stays.
        if lower == 'е' and (position == 0 or word[position - 1].lower() in VOWELS):
            value = 'ye'
        if letter.isupper():
            whole = word.isupper() and len(word) > 1
            value = value.upper() if whole else value[:1].upper() + value[1:]
        out.append(value)
    return ''.join(out)


def _alphabet(letter):
    return 'cyrl' if CYRILLIC.match(letter) else 'latn' if LATIN.match(letter) else ''


def settle(word):
    """A word that mixes the alphabets, with its look-alikes in the one most of its letters use.

    Mostly Cyrillic (a tie too): a Latin look-alike slipped in becomes its
    Cyrillic twin, so "Тaққослаш" is then read by sound (Taqqoslash), not by
    shape (Taqqoclash). A Latin run with other letters in it (Ўзбекистонcha,
    Москва's) was written in Latin on purpose and stays. Mostly Latin: a lone
    Cyrillic look-alike becomes its Latin twin (mаktab); two Cyrillic letters
    or more are a real ending (talabaлар), left to be transliterated by sound.
    """
    if not (CYRILLIC.search(word) and LATIN.search(word)):
        return word
    runs = [(alphabet, ''.join(letters)) for alphabet, letters in itertools.groupby(word, _alphabet)]
    cyrillic = sum(len(run) for alphabet, run in runs if alphabet == 'cyrl')
    latin = sum(len(run) for alphabet, run in runs if alphabet == 'latn')
    if cyrillic >= latin:
        return ''.join(''.join(LATIN_TWINS[letter] for letter in run)
                       if alphabet == 'latn' and all(letter in LATIN_TWINS for letter in run) else run
                       for alphabet, run in runs)
    return ''.join(TWINS.get(run, run) if alphabet == 'cyrl' else run for alphabet, run in runs)


def clean_text(text, script='latn', *, keep_cyrillic=False):
    def fix(match):
        word = settle(match.group(0))
        if script == 'latn' and not keep_cyrillic and CYRILLIC.search(word):
            word = to_latin(word)
        return word

    text = WORD.sub(fix, text or '')
    return TURNED.sub('‘', text) if script == 'latn' else text


def clean(content, script='latn', description=''):
    """`content` with every field it shows in the Latin alphabet.

    `script` and `description` are accepted for older callers: there is no
    Cyrillic Uzbek document any more, and no description keeps a Cyrillic word.
    """
    def fix(value):
        return clean_text(value, 'latn') if isinstance(value, str) else value

    result = dict(content)
    result['title'] = fix(content.get('title', ''))
    sections = []
    for section in content.get('sections', []):
        section = dict(section)
        for key in ('heading', 'body', 'notes'):
            if key in section:
                section[key] = fix(section[key])
        if section.get('items'):
            section['items'] = [{key: fix(value) for key, value in item.items()} for item in section['items']]
        if section.get('columns'):
            section['columns'] = [fix(column) for column in section['columns']]
        sections.append(section)
    result['sections'] = sections
    questions = []
    for question in content.get('questions', []):
        question = dict(question)
        for key in ('stem', 'answer', 'explanation'):
            if key in question:
                question[key] = fix(question[key])
        question['options'] = [fix(option) for option in question.get('options', [])]
        questions.append(question)
    result['questions'] = questions
    return result
