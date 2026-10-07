"""Uzbek in one alphabet, as the customer wrote it.

Customers complained that Latin documents came back with words in Cyrillic
letters ("Krilcha harflarda yozilgan ayrim joylarda…", "Rus alifbosini
ishlatma"). The model is told which alphabet to use; this catches what it still
gets wrong: a Cyrillic word in a Latin document is transliterated, a word that
mixes the two alphabets is put into the one the rest of it uses, and the
several apostrophes of o‘ and g‘ become one.

A document about Russian, or one whose description quotes Cyrillic, keeps its
Cyrillic words: they are content there, not mistakes. Only words mixing both
alphabets are fixed then.
"""
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
CYRILLIC = re.compile(r'[Ѐ-ӿ]')
LATIN = re.compile(r'[A-Za-z]')
WORD = re.compile(r"[\wЀ-ӿ'‘’ʻʼ`]+")
# o‘ and g‘ are typed with whichever apostrophe is to hand; the house form is ‘.
TURNED = re.compile(r"(?<=[oOgG])['’ʻ`´](?=\w)")
RUSSIAN_TOPIC = re.compile(r'\brus\b|\brus\s*til|русск|kirill|кирилл', re.IGNORECASE)


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


def _mixed(word, script):
    """A word that mixes the alphabets, put into the document's own."""
    if script == 'cyrl':
        return ''.join(LATIN_TWINS.get(letter, letter) for letter in word)
    return ''.join(TWINS.get(letter) or to_latin(letter) for letter in word)


def clean_text(text, script='latn', *, keep_cyrillic=False):
    def fix(match):
        word = match.group(0)
        has_cyrillic, has_latin = bool(CYRILLIC.search(word)), bool(LATIN.search(word))
        if has_cyrillic and has_latin:
            word = _mixed(word, script)
        elif has_cyrillic and script == 'latn' and not keep_cyrillic:
            word = to_latin(word)
        return word

    text = WORD.sub(fix, text or '')
    return TURNED.sub('‘', text) if script == 'latn' else text


def clean(content, script='latn', description=''):
    """`content` with every field it shows written in one alphabet."""
    keep = bool(CYRILLIC.search(description or '')) or bool(RUSSIAN_TOPIC.search(description or ''))

    def fix(value):
        return clean_text(value, script, keep_cyrillic=keep) if isinstance(value, str) else value

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
