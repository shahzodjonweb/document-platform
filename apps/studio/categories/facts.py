"""Never invent, in code: what a category document says is held to what the customer said.

A category document is made from one message and the customer's files. The
prompt forbids inventing a person, organisation, date, number, price, law,
quotation or source, and this module checks that the model kept to it
(architecture section 4). It is the CV's fact check (cv/content.fact_check)
generalised, and it never sees a value it would log: what it takes out is
reported as codes.

- `trusted(data)` is everything the customer has said: the description, the
  pasted text and the files, every change request and the first description,
  the cover lines they keep and their brand name, and the document as it stood
  before a change (it went through these same checks when it was made).
- `supported(value, kind, trusted)` decides one fact the model read out of
  that, by the kind of its field: a person's or an organisation's capitalised
  words must be the customer's (with a case ending allowed), a date, sum or
  reference number must be one the customer gave however it is written
  (numbers.py), an e-mail must be found whole.
- `ground(text, trusted)` is for the written parts that state the customer's
  facts (a letter, an official paper, a business paper, a deck slide of the
  customer's figures): an unsupported number, run of capitalised words or
  quotation becomes ____, and a sentence citing a law, a decree or a code that
  the customer did not give is removed.
- `guard(text, trusted)` is for every other category part, subject prose
  included: only quotations and legal references are checked, since well
  known general knowledge (a historical date, a city) stays allowed there.
- `verify_items(items, trusted, file_names=...)` keeps the items of a
  references list that the customer named or that a file's own text gives, and
  never an item that is only a file's name.

Both sides are compared folded (`fold`): one apostrophe, lower case, Cyrillic
put into Latin with the house table, and the spellings a name takes across the
two alphabets made one (x, h and kh; yo and e; ya and ia; q and k; o‘ and u).
Folding can only make two spellings of the customer's own name meet; what it
cannot see is said plainly in the architecture: a name the model writes in
lower case, a wrong case ending. A transliteration the table misses blanks a
real name, which is a false blank and never an invention, and is counted.
"""
import math
import re
import unicodedata
from dataclasses import dataclass

from ..language import normalised
from ..uzbek import LETTERS
from . import numbers

BLANK = '____'
# Cyrillic put into Latin the house way (uzbek.py), with the Russian letters it leaves to taste spelled so that a
# name meets its Latin spelling: ц as ts, щ as sh, ё as yo, the signs dropped.
LATIN = str.maketrans({**LETTERS, 'ъ': '', 'ь': '', 'ц': 'ts', 'щ': 'sh', 'ё': 'yo', 'е': 'e', 'э': 'e', 'і': 'i',
                       'ї': 'i', 'є': 'e', 'ў': "o'", 'ғ': "g'", 'ҳ': 'h'})
WORD = re.compile(r"[^\W\d_](?:[^\W\d_]|['‘’ʻʼ`´](?=[^\W\d_]))*")
FOLDED_WORD = re.compile(r'[^\W\d_]+')
EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
LINK = re.compile(r"(?:https?://|www\.)\S+|\b[\w\-]+(?:\.[\w\-]+)*\.(?:uz|com|ru|org|net|io|me|info|edu|gov)"
                  r"(?:/\S*)?(?!\w)", re.IGNORECASE)
VOWELS = set('aeiouy')
# What a name takes in a sentence when it is three letters long and cannot meet the common-prefix rule:
# "Aliga", "Alining", "Алию", "Ali's" (folded).
ENDINGS = frozenset(('ning', 'ni', 'ga', 'ka', 'da', 'dan', 'dagi', 'lar', 'larga', 'larni', 'larning', 'lardan',
                     'a', 'u', 'om', 'e', 'oy', 'i', 'em', 'im', 's', 'ov', 'ova'))
# Words a document may capitalise that are no one's facts: formulas of address and closing, the polite forms of
# "you" that letters capitalise, titles, legal forms, months, weekdays and languages. The entry's labels and fixed
# headings and its templates' labels are added per draft (`trusted`). Prefixes take endings: "Hurmatli",
# "Уважаемая", "Вашего".
ALLOWED = (
    "hurmatli muhtaram assalomu alaykum hurmat bilan janob xonim siz sizlar dear sincerely regards respectfully "
    "yours faithfully truly kind best sir madam mr mrs ms miss dr prof phd dsc you your i'm i've i'd i'll "
    "уважаемый глубокоуважаемый здравствуйте уважением вы вас вам вами ваш господин госпожа "
    "mchj aj xk qk yatt ooo ao pao ip llc ltd inc jsc plc gmbh ооо оао пао зао ао ип "
    "yanvar fevral mart aprel may iyun iyul avgust sentabr sentyabr oktabr oktyabr noyabr dekabr "
    "january february march april june july august september october november december "
    "январь февраль март апрель май июнь июль август сентябрь октябрь ноябрь декабрь "
    "dushanba seshanba chorshanba payshanba juma shanba yakshanba monday tuesday wednesday thursday friday "
    "saturday sunday понедельник вторник среда четверг пятница суббота воскресенье "
    "o'zbek ingliz rus nemis fransuz arab turk xitoy koreys yapon qozoq qirg'iz tojik uzbek english russian german "
    "french arabic turkish chinese korean japanese kazakh kyrgyz tajik узбекский русский английский немецкий "
    "французский арабский турецкий китайский корейский японский казахский киргизский таджикский"
).split()
# Abbreviations whose full stop does not end a sentence, so the capitalised word after one is still checked:
# "prof. Xolmirzayev", "B. Rahimov", "ул. Садовая".
# A single letter is always an initial.
ABBREVIATIONS = frozenset((
    'prof', 'dots', 'dr', 'mr', 'mrs', 'ms', 'jr', 'sr', 'st', 'no', 'nr', 'tel', 'fig', 'vol', 'pp', 'vs', 'approx',
    'acad', 'akad', 'ch', 'sh', 'mfy', 'ul', 'kv', 'im', 'str', 'gr', 'проф', 'доц', 'акад', 'тел', 'им', 'ул', 'кв',
    'стр', 'гр'))
OPENING = ' \t«“„"\'‘(['
LIST_MARKS = '-–—•*·'
QUOTE = re.compile(r'«([^«»]{1,800})»|“([^“”]{1,800})”|„([^„“”]{1,800})[“”]|"([^"\n]{1,800})"')
SENTENCE_END = re.compile(r'[.!?…]+(?=[\s"»”)\]]|$)|\n+')
# Legal references, by what they cite, in the three languages (normalised, lower case). A strong stem is a
# citation by itself; a weak one also means something else ("Nyutonning ikkinchi qonuni", "qaror qabul qilish",
# "kimyoviy modda", "in his article") and is a citation only with a mark of one beside it (`LEGAL_MARK`).
LAW = (
    ('code', r"kodeks\w*|кодекс\w*", True),
    ('code', r"codes?", False),
    ('decree', r"farmon\w*|указ(?:а|е|ом|у|ы|ов|ами|ах)?|decrees?", True),
    ('order', r"farmoyish\w*|распоряжени\w*", True),
    ('order', r"buyru[qg]\w*|приказ\w*", False),
    ('resolution', r"постановлени\w*", True),
    ('resolution', r"qaror\w*|resolutions?", False),
    ('law', r"qonun(?!iyat)\w*|закон(?!омерн)\w*|laws?|acts?", False),
    ('article', r"modda\w*|стать(?:я|и|е|ю|ей|ям|ях)|articles?", False),
)
NUMBERED = re.compile(r"\d[ \u00a0]?-[ \u00a0]?son(?:i|ga|da|dan|ning)?(?![^\W\d_])")
LEGAL_MARK = re.compile(r"\d|№|\bno\.|to'g'risida|togrisida|respublika|республик|federal|федеральн|mahkama"
                        r"|министр|prezident|президент|oliy majlis|parliament|парламент")
STEMS = [(concept, re.compile(rf'(?<![^\W\d_])(?:{stem})(?![^\W\d_])', re.IGNORECASE), strong)
         for concept, stem, strong in LAW]


def fold(text):
    """`text` as both sides of every comparison are read: the spellings of one name across the alphabets made one."""
    text = normalised(str(text or '')).casefold().translate(LATIN)
    text = ''.join(char for char in unicodedata.normalize('NFKD', text) if not unicodedata.combining(char))
    # o‘ is u in Russian spelling (Toshpo‘latova, Тошпулатова); an English possessive ("Two's") is not an o‘.
    text = re.sub(r"o'(?!s\b)", 'u', text).replace("'", '')
    text = re.sub('dzh|dj|zh', 'j', text)
    text = text.replace('sh', '\x01').replace('ch', '\x02').replace('kh', 'x').replace('h', 'x')
    text = text.replace('\x01', 'sh').replace('\x02', 'ch')
    text = text.replace('yo', 'e').replace('q', 'k').replace('w', 'v')
    # ц is s in the Uzbek table and ts in English ("Цой", "Tsoy"); only where a word starts, so "Vaqt's" stays.
    text = re.sub(r'\bts', 's', text)
    text = re.sub(r'y(?=[aeiou])', '', text)
    return re.sub(r'iy\b', 'i', text)


def flat(text, *, folded=None):
    """Folded words and numbers with single spaces between, padded: what a quotation is looked up in."""
    return ' ' + ' '.join(re.findall(r'[^\W_]+', fold(text) if folded is None else folded)) + ' '


def _close(word, other):
    """Whether two folded words are one, allowing a case ending: Rahimova and Rahimovaning, Каримова and Каримовой."""
    if word == other:
        return True
    shorter, longer = sorted((word, other), key=len)
    size = len(shorter)
    common = 0
    for a, b in zip(word, other):
        if a != b:
            break
        common += 1
    if size >= 4 and common >= max(4, math.ceil(0.7 * size)):
        return True
    if size >= 4 and common == size - 1 and len(longer) - size <= 1 and shorter[-1] in VOWELS \
            and longer[size - 1] in VOWELS:
        return True  # Анна and Анне, Анной: an ending in place of the last vowel
    return size == 3 and common == 3 and longer[3:] in ENDINGS


class Words:
    """A set of folded words that answers whether a word is one of them, with its endings."""

    def __init__(self, words=()):
        self.exact = set()
        self.index = {}
        for word in words:
            self.add(word)

    def add(self, word):
        if word in self.exact:
            return
        self.exact.add(word)
        if len(word) >= 3:
            self.index.setdefault(word[:3], []).append(word)

    def known(self, word):
        word = fold(word)
        if not word:
            return True
        if word in self.exact:
            return True
        if len(word) < 3:
            return False
        return any(_close(word, other) for other in self.index.get(word[:3], ()))


@dataclass(frozen=True)
class Trusted:
    """What the customer said, read once per job in every form the checks look it up in."""

    words: Words
    allowed: Words
    values: frozenset
    flat: str
    lower: str
    emails: frozenset
    links: frozenset


def _link(text):
    return re.sub(r'^(?:https?://)?(?:www\.)?', '', text.lower()).rstrip('/.,;)')


def trusting(text, *, allowed=()):
    """A Trusted from plain text, `allowed` being more words no one's facts are in (labels, headings)."""
    text = str(text or '')
    folded = fold(text)
    words = Words(FOLDED_WORD.findall(folded))
    allow = Words()
    for item in (*ALLOWED, *allowed):
        for word in FOLDED_WORD.findall(fold(item)):
            allow.add(word)
    return Trusted(words, allow, frozenset(numbers.values(text)), flat(text, folded=folded),
                   normalised(text).casefold(), frozenset(email.lower().strip('.') for email in EMAIL.findall(text)),
                   frozenset(_link(link) for link in LINK.findall(EMAIL.sub(' ', text))))


def _texts(content):
    from ..scripts import fields
    return [text for _, text in fields(content) if isinstance(text, str)] if isinstance(content, dict) else []


def _catalogue_words(entry):
    """The fixed words of a category in every language: its labels, its parts' headings, its templates' labels."""
    if entry is None:
        return []
    from . import catalogue
    found = []

    def take(value):
        if isinstance(value, dict):
            found.extend(item for item in value.values() if isinstance(item, str))
    take(entry.raw.get('labels'))
    for part in entry.parts:
        take(part.get('heading'))
    for template_id in entry.templates:
        try:
            labels = catalogue.template(template_id).get('labels') or {}
        except KeyError:
            continue
        for label in labels.values():
            take(label)
    return found


def trusted(data):
    """Everything the customer has said in this draft, and the words of its category no one's facts are in."""
    from . import catalogue
    data = data or {}
    revision = data.get('revision') or {}
    options = data.get('options') if isinstance(data.get('options'), dict) else data.get('parameters') or {}
    parts = [data.get('prompt'), data.get('source_text'), revision.get('request'), revision.get('original_prompt')]
    parts += [excerpt.get('text') for excerpt in data.get('excerpts') or [] if isinstance(excerpt, dict)]
    cover = data.get('_cover_lines') if isinstance(data.get('_cover_lines'), dict) else {}
    parts += [line for line in cover.get('lines') or [] if isinstance(line, str)]
    branding = options.get('branding') if isinstance(options.get('branding'), dict) else {}
    parts.append(branding.get('name'))
    # A change keeps only the latest request and the first description; what an earlier change gave lives on in the
    # document it went into, which these checks read when it was made.
    for content in (revision.get('before'), revision.get('base_content')):
        parts += _texts(content)
    category = options.get('category')
    entry = catalogue.get(category) if isinstance(category, str) else None
    return trusting('\n'.join(str(part) for part in parts if part), allowed=_catalogue_words(entry))


# ---------------------------------------------------------------- one fact


def _strip_addresses(text, trusted):
    """(text without its e-mails and links, whether every one of them is the customer's, found whole)."""
    whole = True
    for email in EMAIL.findall(text):
        whole = whole and email.lower().strip('.') in trusted.emails
    text = EMAIL.sub(' ', text)
    for link in LINK.findall(text):
        whole = whole and _link(link) in trusted.links
    return LINK.sub(' ', text), whole


def _names_known(text, trusted):
    """Whether every capitalised word of two letters or more is the customer's or one no one's facts are in."""
    for match in WORD.finditer(text):
        word = match.group(0)
        if not word[0].isupper() or len(re.sub(r"['‘’ʻʼ`´]", '', word)) < 2:
            continue
        if not (trusted.allowed.known(word) or trusted.words.known(word)):
            return False
    return True


def supported(value, kind, trusted, *, translated=False):
    """Whether a fact of this kind is the customer's (architecture 4, "Verifying").

    person, org, place, line: every capitalised word is theirs and every number
    is one they gave; date, number, money, ref, phone, text: every number;
    email: found whole; list: each line as a line; choice, flag, file: not
    checked here. `translated` (the document is in another language than the
    message) checks names for a person only: organisations and places are
    translated, a person's name only spelled anew, which the fold meets.
    """
    if kind in ('choice', 'flag', 'file') or value is None or isinstance(value, bool):
        return True
    text = str(value).strip()
    if not text or not re.sub(r'[_\s.\-]', '', text):
        return True  # nothing, or the blank the model returns for an if_needed field
    if kind == 'list':
        return all(supported(line, 'line', trusted, translated=translated)
                   for line in re.split(r'[\n;]+', text) if line.strip())
    rest, whole = _strip_addresses(text, trusted)
    if not whole:
        return False
    if not all(numbers.known(number, trusted.values) for number in numbers.found(rest)):
        return False
    if kind in ('person', 'org', 'place', 'line') and not (translated and kind != 'person'):
        return _names_known(rest, trusted)
    return True


def derived(value, base):
    """Whether `value` is made of the words and initials of `base` only: "D. R. Karimova" of "Karimova Dilnoza"."""
    base = str(base or '')
    words = Words(FOLDED_WORD.findall(fold(base)))
    starts = {fold(word)[:1] for word in WORD.findall(base)} | {word[:1].lower() for word in WORD.findall(base)}
    folded = [fold(word) for word in WORD.findall(base)]
    text = str(value or '')
    for match in WORD.finditer(text):
        word = match.group(0)
        abbreviated = text[match.end():match.end() + 1] == '.'
        if len(word) == 1:
            if word.lower() not in starts and fold(word)[:1] not in starts:
                return False
        elif abbreviated and len(word) <= 3:
            if not any(other.startswith(fold(word)) for other in folded):
                return False
        elif not words.known(word):
            return False
    return True


# ---------------------------------------------------------------- written parts


def _abbreviation(text, stop):
    """Whether the full stop at `stop` ends an abbreviation or an initial rather than a sentence."""
    match = re.search(r"([^\W\d_][^\W\d_.‘’']*)$", text[:stop])
    if not match:
        return False
    word = match.group(1).lower()
    return len(word) == 1 or word in ABBREVIATIONS


def _starts(text, position):
    """Whether a word at `position` starts a sentence, a line, a list item or the words after a colon."""
    at = position - 1
    while at >= 0 and text[at] in OPENING:
        at -= 1
    if at < 0 or text[at] == '\n' or text[at] in ':!?…':
        return True
    if text[at] == '.':
        line = text[text.rfind('\n', 0, at) + 1:at].strip()
        if re.fullmatch(r'\d{1,3}|[^\W\d_]', line):
            return True  # "1. Item", "a. Item"
        return not _abbreviation(text, at)
    if text[at] == ')':
        line = text[text.rfind('\n', 0, at) + 1:at].strip()
        return re.fullmatch(r'\(?(?:\d{1,3}|[^\W\d_])', line) is not None
    if text[at] in LIST_MARKS:
        return not text[text.rfind('\n', 0, at) + 1:at].strip()
    return False


def _enumerator(text, number):
    """Whether a number numbers a list item ("1. ", "2) ") rather than stating a fact."""
    line = text[text.rfind('\n', 0, number.start) + 1:number.start]
    return not line.strip(' \t' + LIST_MARKS) and re.match(r'[.)][ \t]', text[number.end:number.end + 2]) is not None


def _sentences(text):
    """(start, end) of each sentence of `text`, its closing marks and the spaces after it included."""
    spans, start = [], 0
    for match in SENTENCE_END.finditer(text):
        if match.group(0).startswith('.') and len(match.group(0)) == 1 and _abbreviation(text, match.start()):
            continue
        end = match.end()
        while end < len(text) and text[end] in ' \t"»”)]':
            end += 1
        if text[start:end].strip():
            spans.append((start, end))
        start = end
    if text[start:].strip():
        spans.append((start, len(text)))
    return spans


def _concepts(sentence):
    """The legal things `sentence` cites, or an empty set when it cites none (a weak stem with no mark beside it)."""
    text = normalised(sentence)
    found, weak = set(), set()
    for concept, stem, strong in STEMS:
        for match in stem.finditer(text):
            # A weak stem capitalised inside a sentence is a title ("Mehnat Kodeksi", "Labour Code", "Закон о …").
            if strong or (match.group(0)[0].isupper() and not _starts(text, match.start())):
                found.add(concept)
            else:
                weak.add(concept)
    lower = text.casefold()
    if NUMBERED.search(lower):
        found.add('number')
    if weak and (found or LEGAL_MARK.search(lower)):
        found |= weak
    return found


def _legal_known(sentence, concepts, trusted, translated):
    for concept in concepts - {'number'}:
        if not any(stem.search(trusted.lower) for name, stem, _ in STEMS if name == concept):
            return False
    if not all(numbers.known(number, trusted.values) for number in numbers.found(sentence)):
        return False
    if translated:
        return True
    for match in WORD.finditer(sentence):
        word = match.group(0)
        if (word[0].isupper() and len(word) >= 2 and not _starts(sentence, match.start())
                and not trusted.allowed.known(word) and not trusted.words.known(word)):
            return False
    return True


def _laws(text, trusted, translated, codes):
    kept, removed = [], False
    last = 0
    for start, end in _sentences(text):
        sentence = text[start:end]
        concepts = _concepts(sentence)
        if concepts and not _legal_known(sentence, concepts, trusted, translated):
            kept.append(text[last:start])
            last = end
            removed = True
            continue
    if not removed:
        return text
    codes.append('ground:law')
    kept = ''.join(kept) + text[last:]
    # The spaces after the sentence before a removed last one are not left hanging.
    return kept if text != text.rstrip() else kept.rstrip()


def _replace(text, spans):
    for start, end in sorted(spans, reverse=True):
        text = text[:start] + BLANK + text[end:]
    return text


def _quotes(text, trusted, codes):
    spans = []
    for match in QUOTE.finditer(text):
        inner = next(group for group in match.groups() if group is not None)
        if len(WORD.findall(inner)) >= 3 and flat(inner) not in trusted.flat:
            spans.append(match.span())
    if spans:
        codes.append('ground:quote')
    return _replace(text, spans)


def _numbers(text, trusted, codes):
    spans = [(number.start, number.end) for number in numbers.found(text)
             if not _enumerator(text, number) and not numbers.known(number, trusted.values)]
    if spans:
        codes.append('ground:number')
    return _replace(text, spans)


def _addresses(text, trusted, codes):
    # An e-mail or a link is a contact detail, counted with the numbers: it is never a name, quotation or law.
    emails = list(EMAIL.finditer(text))
    spans = [match.span() for match in emails if match.group(0).lower().strip('.') not in trusted.emails]
    # A link is looked for with the e-mails masked, so the domain of a known address is not read as a link.
    masked = EMAIL.sub(lambda match: ' ' * len(match.group(0)), text)
    spans += [match.span() for match in LINK.finditer(masked) if _link(match.group(0)) not in trusted.links]
    if spans:
        codes.append('ground:number')
    return _replace(text, spans)


def _runs(text):
    """Runs of capitalised words side by side (an initial's full stop between allowed): [[(start, end, word)]]."""
    runs, current = [], []
    for match in WORD.finditer(text):
        word = match.group(0)
        capital = word[0].isupper()
        if current and capital and re.fullmatch(r"[ \t\u00a0]*|\.[ \t\u00a0]+", text[current[-1][1]:match.start()]) \
                and (text[current[-1][1]:match.start()].strip() != '.' or len(current[-1][2]) == 1):
            current.append((match.start(), match.end(), word))
            continue
        if current:
            runs.append(current)
        current = [(match.start(), match.end(), word)] if capital else []
    if current:
        runs.append(current)
    return runs


def _names(text, trusted, codes):
    spans = []
    for run in _runs(text):
        bad = []
        for position, (start, end, word) in enumerate(run):
            letters = len(re.sub(r"['‘’ʻʼ`´]", '', word))
            # The first word of a sentence is capitalised by grammar ("Bunga", "Shuningdek") and is never blanked;
            # an invented name that is a sentence's first word alone is a limit the architecture names.
            if letters < 2 or (position == 0 and _starts(text, start)):
                continue
            if not (trusted.allowed.known(word) or trusted.words.known(word)):
                bad.append(position)
        group = []
        for position in bad:
            if group and position != group[-1] + 1:
                spans.append((run[group[0]][0], run[group[-1]][1]))
                group = []
            group.append(position)
        if group:
            spans.append((run[group[0]][0], run[group[-1]][1]))
    if spans:
        codes.append('ground:name')
    return _replace(text, spans)


def _tidy(text):
    return re.sub(rf'{BLANK}(?:[ \t\u00a0]+{BLANK})+', BLANK, text)


def ground(text, trusted, *, translated=False):
    """(text, codes): a written part that states the customer's facts, with nothing in it they did not give.

    A sentence citing a law, a decree, a code or a resolution is removed unless
    what it cites, and every name and number in it, is the customer's. Then a
    quotation of three words or more that is not theirs word for word, a
    number they did not give, an e-mail or link not theirs, and a run of
    capitalised words that is not theirs become ____. The first word of a
    sentence, a line, a list item or the words after a colon is not taken for a
    name, nor is a word no one's facts are in (a label, a month, "Hurmatli").
    `translated` leaves names to the translation; numbers, quotations and laws
    are always checked.
    """
    codes = []
    text = str(text or '')
    if not text.strip():
        return text, codes
    text = _laws(text, trusted, translated, codes)
    text = _quotes(text, trusted, codes)
    text = _addresses(text, trusted, codes)
    text = _numbers(text, trusted, codes)
    if not translated:
        text = _names(text, trusted, codes)
    return _tidy(text), list(dict.fromkeys(codes))


def guard(text, trusted, *, translated=False):
    """(text, codes): any other category part, with no quotation and no legal reference the customer did not give.

    Names, numbers and general knowledge are left as SYSTEM allows them in a
    subject paper; a quotation that is not the customer's becomes ____ and a
    legal sentence that is not theirs is removed, in any language.
    """
    codes = []
    text = str(text or '')
    if not text.strip():
        return text, codes
    text = _laws(text, trusted, translated, codes)
    text = _quotes(text, trusted, codes)
    return _tidy(text), list(dict.fromkeys(codes))


# ---------------------------------------------------------------- references


def _item_text(item):
    """The words of a references item; a label that only numbers it ("1", "[2]", "3.") is not one of them."""
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return ''
    label = item.get('label') if isinstance(item.get('label'), str) else ''
    if re.fullmatch(r'\W*\d{1,3}\W*', label):
        label = ''
    return ' '.join(part for part in (label, *(item.get(key) for key in ('text', 'value'))) if isinstance(part, str))


def _file_name(text, file_names):
    folded = flat(text)
    for name in file_names or ():
        name = str(name or '').strip()
        if not name:
            continue
        stem = name.rsplit('.', 1)[0] if '.' in name else name
        whole, short = flat(name), flat(stem)
        if folded == whole or (short.strip() and folded == short) or ('.' in name and whole.strip()
                                                                       and whole in folded):
            return True
    return False


def verify_items(items, trusted, *, file_names=()):
    """(kept, codes): the items of a references list that are the customer's sources, in order.

    Each is held as a line to what the customer said and the files' own text
    (a book they named, a description taken from a file's first page). One
    that is not, or that is an attached file's name with or without its
    extension, is dropped: a references list never shows a file name.
    """
    kept, codes = [], []
    for item in items or []:
        text = _item_text(item).strip()
        if not text:
            continue
        if _file_name(text, file_names) or not supported(text, 'line', trusted):
            codes.append('source:dropped')
            continue
        kept.append(item)
    return kept, list(dict.fromkeys(codes))
