"""Numbers as values, so a fact is found however it is written.

The never-invent checks (facts.py) hold every number the model writes to the
numbers the customer gave. Compared as digit strings, real prices and dates
would blank: "1 150 000" is not "1150000", "1,5 mln" is not "1 500 000", and
"3-noyabr" is not "03.11". Here each way of writing a number is read as the
value it means:

- "1 150 000", "1.150.000" and "1,150,000" are one integer; "1,5" and "1.5"
  one decimal; "1,150" may be either, so it is both;
- "1,5 mln" and "20 ming" are also their scaled values (ming, тыс, thousand,
  mln, млн, million, mlrd, млрд, billion);
- a percent sign, and the suffix of "205-guruh", are not part of the number;
- "15.11.2026", "2026-11-15", "15-noyabr", "15 ноября", "15 November",
  "November 15" are the day and month 15.11 (and a year, when one is written,
  which is a number of its own); "с 3 по 12 ноября" gives both days their month;
- a phone number is its digits and its last nine digits, so "+998 90 123 45 67"
  is found as "90 123 45 67";
- a time "10:00" is one value, the hour and its minutes: "soat 10 da" gives it
  when the minutes are 00, and "10" and "30" written apart never make "10:30".

`found(text)` gives each number of a text with what it needs to be known: a
date needs its day and month, an amount any one of the values it may mean.
`values(text)` is everything a text gives, for the customer's side. It is
generous on purpose ("3-noyabr" also gives its day as a number, "ikki" and
"две" give 2): more ways to be found save a real fact from a blank, while what
the model writes is read strictly by `found`. It is never generous with parts
of one number: the groups of "1 150 000" or of a phone, and the day and month of
"03.11.2026", are not numbers the customer gave.

Numbers inside an e-mail or a link are not numbers; facts.py checks those whole.
"""
import re
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

from ..language import normalised
from ..uzbek import to_latin

GAP = '[ \u00a0\u202f\u2009]'
LETTER = r'[^\W\d_]'
# The months as a date names them, by number. Full names take any ending ("noyabrdan", "ноября"); short forms and
# words that are also ordinary words stand alone: "3 marta" is three times, never a date. "mayda" is both "in May"
# and "small", so "5 mayda" is a date only with the hyphen ("5-mayda") or a year or "kuni" beside it (`_small`).
MONTHS = (
    r"yanvar\w*|январ\w*|january|(?:jan|янв)\.?",
    r"fevral\w*|феврал\w*|february|(?:feb|фев)\.?",
    r"mart(?:da|dan|ga|gacha|ning|dagi|idan|igacha)?|март\w*|march|(?:mar|мар)\.?",
    r"aprel\w*|апрел\w*|april|(?:apr|апр)\.?",
    r"may(?:da|dan|ga|gacha|ning|dagi|idan|igacha)?|ма(?:й|я|е|ю|ем)",
    r"iyun\w*|июн\w*|june|jun\.?",
    r"iyul\w*|июл\w*|july|jul\.?",
    r"avgust\w*|август\w*|august|(?:aug|авг)\.?",
    r"sent[ay]?abr\w*|сентябр\w*|september|(?:sept?|сент?)\.?",
    r"okt[ay]?abr\w*|октябр\w*|october|(?:oct|окт)\.?",
    r"noyabr\w*|ноябр\w*|november|(?:nov|ноя)\.?",
    r"dekabr\w*|декабр\w*|december|(?:dec|дек)\.?",
)
MONTH = '(' + '|'.join(f'(?:{stems})' for stems in MONTHS) + rf')(?!{LETTER})'
MONTH_NUMBER = [re.compile(rf'(?:{stems})$', re.IGNORECASE) for stems in MONTHS]
DAY = r"(?<![\d.,/])(\d{1,2})(?:-?(?:st|nd|rd|th)|-(?:go|го|e|е|chi|inchi))?"
BEFORE_MONTH = r"(?:[ \u00a0]*-[ \u00a0]*|[ \u00a0]+(?:of[ \u00a0]+)?)"
# "3-noyabr", "3 ноября", "3rd of November"; "3-12-noyabr", "с 3 по 12 ноября", "5 to 18 January"; "November 3-12".
DAY_MONTH = re.compile(DAY + BEFORE_MONTH + MONTH, re.IGNORECASE)
RANGE = re.compile(DAY + r"[ \u00a0]*(?:[-–—]|[ \u00a0](?:po|по|to|till|until|and|va|и|до|dan|-)[ \u00a0])[ \u00a0]*"
                   + DAY[len(r"(?<![\d.,/])"):] + BEFORE_MONTH + MONTH, re.IGNORECASE)
MONTH_DAY = re.compile(r"(?<![^\W\d_])" + MONTH + r"\.?[ \u00a0]+(\d{1,2})(?:st|nd|rd|th)?(?!\d|[.,:]\d)"
                       r"(?:[ \u00a0]*[-–—][ \u00a0]*(\d{1,2})(?!\d|[.,:]\d))?", re.IGNORECASE)
DMY = re.compile(r"(?<![\d.,/-])(\d{1,2})([./-])(\d{1,2})\2(\d{4}|\d{2})(?!\d|[.,]\d)")
YMD = re.compile(r"(?<![\d.,/-])(\d{4})([./-])(\d{1,2})\2(\d{1,2})(?!\d|[.,]\d)")
TIME = re.compile(r"(?<![\d.,:])([01]?\d|2[0-3]):([0-5]\d)(?!\d|[.,:]\d)")
PHONE = re.compile(r"(?<![\w+.,])(\+?\(?\d{1,4}\)?(?:[ \u00a0\-]{1,2}\(?\d{2,4}\)?){2,6})(?![\w]|[.,]\d)")
LONG = re.compile(r"(?<![\d.,])\d{9,15}(?![\d]|[.,]\d)")
GROUPED = re.compile(rf"(?<![\d.,])\d{{1,3}}(?:{GAP}\d{{3}})+(?:[.,]\d+)?(?![\d]|[.,]\d)")
DOTTED = re.compile(r"(?<![\d.,])\d+(?:[.,]\d+)+(?![\d]|[.,]\d)")
PLAIN = re.compile(r"\d+")
SCALE = re.compile(r"[ \u00a0]*(ming|минг|тыс\w*\.?|thousand\w*|mln\.?|млн\.?|million\w*|миллион\w*|mlrd\.?|млрд\.?"
                   r"|milliard\w*|миллиард\w*|billion\w*|trln\.?|трлн\.?|trillion\w*)(?!\w)|(k)(?![^\W\d_])",
                   re.IGNORECASE)
SCALES = (('ming', 3), ('минг', 3), ('тыс', 3), ('thousand', 3), ('k', 3), ('mln', 6), ('млн', 6), ('million', 6),
          ('миллион', 6), ('mlrd', 9), ('млрд', 9), ('milliard', 9), ('миллиард', 9), ('billion', 9), ('trln', 12),
          ('трлн', 12), ('trillion', 12))
# An e-mail and a link as facts.py reads them (and as this module skips them), written to be read in time linear in
# the text: a file of long runs of letters, dots and hyphens made the plain forms try every start in a run and read
# the whole run from each, about 15 s for one 130,000-character source, inside the job's lease. Each run is now read
# once from where it may start: an address's local part is at most 64 characters (its own limit), a host label at
# most 63 and a host at most ten labels before its ending, read possessively, and a host starts only where a word
# starts outside another host ("ab.cd.uz" is tried at "ab", never again at "cd", which the first try covered). On
# text with real addresses they match what the plain forms matched.
EMAIL_PATTERN = r"[\w.+\-]{1,64}+@[\w\-]++(?:\.[\w\-]++)+"
LINK_PATTERN = (r"(?:https?://|www\.)\S+|\b(?<!\w)(?<!\w-)(?<!\w\.)(?:[\w\-]{1,63}+\.){1,10}"
                r"(?:uz|com|ru|org|net|io|me|info|edu|gov)(?:/\S*)?(?!\w)")
SKIPPED = re.compile(f'{EMAIL_PATTERN}|{LINK_PATTERN}', re.IGNORECASE)

# Number words, on the customer's side only: "Две недели в терапии", "two in surgery", "ikkala guruh". "Bir", "один"
# and "one" are ordinary words too, and are left out. Russian forms are whole words or the start of a compound
# ("четырёхнедельная"); Uzbek ones take the endings of a count ("uchta", "uchinchi", "uchala"), never "uchun".
RU_WORDS = (
    (r"двадцат\w*", 20), (r"тридцат\w*", 30), (r"сорок\w*", 40), (r"пят[ьи]десят\w*", 50),
    (r"шест[ьи]десят\w*", 60), (r"сем[ьи]десят\w*", 70), (r"вос[еь]м[ьи]десят\w*", 80), (r"девяност\w*", 90),
    (r"сто|ста", 100), (r"дв(?:а|е|ух|ум|умя|ое|оих)|двух\w*|втор(?:ой|ая|ое|ого|ом|ую|ые|ых)|об[ае]|обоих", 2),
    (r"тр(?:и|ех|ёх|ем|ём|емя|ое|оих)|тр[её]х\w*|трет(?:ий|ья|ье|ьего|ьем|ью|ьи|ьих)", 3),
    (r"четыр\w*|четв[её]рт\w*", 4), (r"пят(?:ь|ью|ый|ая|ое|ого|ом|ой|ую|еро|ерых)|пяти\w*", 5),
    (r"шест(?:ь|ью|ой|ая|ое|ого|ом|ую|еро)|шести\w*", 6),
    (r"сем(?:ь|ью|ой|ая|ое|ого|ом|ую|еро)|семи|седьм\w*", 7),
    (r"вос(?:емь|ьми|ьмой|ьмая|ьмое|ьмого|ьмом)\w*", 8), (r"девят\w*", 9), (r"десят\w*", 10),
    (r"одиннадцат\w*", 11), (r"двенадцат\w*", 12),
)
EN_WORDS = (
    (r"two|second|both|twice|double", 2), (r"three|third|thrice", 3), (r"four|fourth", 4), (r"five|fifth", 5),
    (r"six|sixth", 6), (r"seven|seventh", 7), (r"eight|eighth", 8), (r"nine|ninth", 9), (r"ten|tenth", 10),
    (r"eleven|eleventh", 11), (r"twelve|twelfth|dozen", 12), (r"twenty|twentieth", 20), (r"thirty", 30),
    (r"forty", 40), (r"fifty", 50), (r"sixty", 60), (r"seventy", 70), (r"eighty", 80), (r"ninety", 90),
    (r"hundred", 100),
)
UZ_STEMS = (("ikki", 2), ("uch", 3), ("to'rt", 4), ("besh", 5), ("olti", 6), ("yetti", 7), ("sakkiz", 8),
            ("to'qqiz", 9), ("o'n", 10), ("yigirma", 20), ("o'ttiz", 30), ("qirq", 40), ("ellik", 50),
            ("oltmish", 60), ("yetmish", 70), ("sakson", 80), ("to'qson", 90))
UZ_ENDINGS = r"(?:ta\w*|inchi\w*|nchi\w*|ala\w*|ov\w*|ovlon\w*)?"
UZ_WORDS = tuple((re.escape(stem) + UZ_ENDINGS, value) for stem, value in UZ_STEMS) + ((r"ikkala\w*", 2),)
WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)*")


def _alternation(patterns):
    """One pattern for a table of (pattern, value), and the value of each of its groups, the first that fits winning."""
    joined = '|'.join(f'(?P<w{index}>{pattern})' for index, (pattern, _) in enumerate(patterns))
    return re.compile(f'(?:{joined})'), {f'w{index}': value for index, (_, value) in enumerate(patterns)}


WORD_TABLES = [_alternation(RU_WORDS + EN_WORDS), _alternation(UZ_WORDS)]


class Number(NamedTuple):
    """One number of a text. `needs` holds sets of keys: it is known when each set meets the known values."""

    start: int
    end: int
    kind: str  # integer, decimal, amount (may be either), scaled, date, time, phone
    value: str
    needs: tuple
    # Keys it gives the customer's side beyond its needs: a date's day as a number, an amount's unscaled value.
    extra: frozenset = frozenset()


def canon(number):
    """A Decimal as its key: "1150000", "1.5"; never an exponent or a trailing zero."""
    if number == number.to_integral_value():
        return str(int(number))
    return format(number.normalize(), 'f')


def _decimal(text):
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _date_key(day, month):
    return f'd:{int(day)}.{int(month)}'


def _valid(day, month):
    return 1 <= int(day) <= 31 and 1 <= int(month) <= 12


def _month(word):
    word = word.rstrip('.')
    for number, pattern in enumerate(MONTH_NUMBER, 1):
        if pattern.match(word):
            return number
    return None


def _year(text):
    return str(int(text)) if len(text) == 4 else f'20{text}'


def _small(text, start, month_start, month_end):
    """Whether "N mayda" from `start` is "N small" rather than a day of May: no hyphen, no year and no "kuni"."""
    if text[month_start:month_end].casefold() != 'mayda' or '-' in text[start:month_start]:
        return False
    after = re.match(r"[ \u00a0,]*(?:\d{4}|kuni)", text[month_end:]) is not None
    before = re.search(r"\d{4}[ \u00a0]*-?[ \u00a0]*y(?:il\w*|\.)[ \u00a0,]*$", text[:start]) is not None
    return not (after or before)


def _scale(text, end):
    """(power of ten, end) of the scale word right after a number ("1,5 mln", "20 ming"), or (0, end)."""
    match = SCALE.match(text, end)
    if not match:
        return 0, end
    word = (match.group(1) or match.group(2)).lower().rstrip('.')
    for stem, power in SCALES:
        if word.startswith(stem):
            return power, match.end()
    return 0, end


def _readings(token):
    """(kind, values) of a number written without spaces: "1,5", "1.150.000", "1,150", "1.150,50", "3"."""
    seps = re.findall(r'[.,]', token)
    groups = re.split(r'[.,]', token)
    if not seps:
        return 'integer', [Decimal(int(token))]
    if len(seps) == 1:
        whole, part = groups
        decimal = Decimal(f'{int(whole)}.{part}')
        if len(part) == 3 and len(whole) <= 3 and whole[0] != '0':
            # "1,150" is a thousand and a hundred and fifty in one country and one and fifteen hundredths in another.
            return 'amount', [Decimal(int(whole + part)), decimal]
        return 'decimal', [decimal]
    if len(set(seps)) == 1 and all(len(group) == 3 for group in groups[1:]) and len(groups[0]) <= 3:
        return 'integer', [Decimal(int(''.join(groups)))]
    last = token.rfind(seps[-1])
    head, tail = token[:last], token[last + 1:]
    if seps[-1] not in head and all(len(group) == 3 for group in re.split(r'[.,]', head)[1:]) \
            and len(re.split(r'[.,]', head)[0]) <= 3:
        return 'decimal', [Decimal(f"{int(re.sub(r'[.,]', '', head))}.{tail}")]
    return 'parts', [Decimal(int(group)) for group in groups if group]


class _Reader:
    """Walks a text once, pattern by pattern, never reading the same characters as two numbers."""

    def __init__(self, text):
        self.text = text
        # One byte per character, set where a number (or an address) was read: a long file has thousands of numbers.
        self.taken = bytearray(len(text))
        self.numbers = []
        for match in SKIPPED.finditer(text):
            self.take(match.start(), match.end())

    def take(self, start, end):
        self.taken[start:end] = b'\x01' * (end - start)

    def free(self, start, end):
        return 1 not in self.taken[start:end]

    def add(self, start, end, kind, value, needs, extra=()):
        self.numbers.append(Number(start, end, kind, value, tuple(frozenset(need) for need in needs),
                                   frozenset(extra)))
        self.take(start, end)

    def read(self):
        text = self.text
        for pattern, order in ((DMY, 'dmy'), (YMD, 'ymd')):
            for match in pattern.finditer(text):
                if not self.free(*match.span()):
                    continue
                if order == 'dmy':
                    day, month, year = match.group(1), match.group(3), _year(match.group(4))
                else:
                    year, month, day = match.group(1), match.group(3), match.group(4)
                if not _valid(day, month):
                    continue
                key = _date_key(day, month)
                # Day and month are a pair here, never two plain numbers: "03.11.2026" does not give "3" or "11".
                self.add(*match.span(), 'date', key, [{key}, {str(int(year))}], {str(int(year)), f'{key}.{int(year)}'})
        for match in RANGE.finditer(text):
            month = _month(match.group(3))
            first, second = match.group(1), match.group(2)
            if month is None or not (_valid(first, month) and _valid(second, month)) \
                    or _small(text, match.start(), *match.span(3)):
                continue
            if not self.free(*match.span()):
                continue
            self.add(match.start(1), match.end(1), 'date', _date_key(first, month), [{_date_key(first, month)}],
                     {str(int(first))})
            self.add(match.start(2), match.end(), 'date', _date_key(second, month), [{_date_key(second, month)}],
                     {str(int(second))})
        for match in DAY_MONTH.finditer(text):
            month = _month(match.group(2))
            if month is None or not _valid(match.group(1), month) or not self.free(*match.span()) \
                    or _small(text, match.start(), *match.span(2)):
                continue
            key = _date_key(match.group(1), month)
            self.add(*match.span(), 'date', key, [{key}], {str(int(match.group(1)))})
        for match in MONTH_DAY.finditer(text):
            month = _month(match.group(1))
            days = [day for day in (match.group(2), match.group(3)) if day]
            if month is None or not all(_valid(day, month) for day in days) or not self.free(*match.span()):
                continue
            needs = [{_date_key(day, month)} for day in days]
            self.add(*match.span(), 'date', _date_key(days[0], month), needs, {str(int(day)) for day in days})
        for match in TIME.finditer(text):
            if not self.free(*match.span()):
                continue
            hour, minutes = int(match.group(1)), match.group(2)
            key = f't:{hour}:{minutes}'
            # On the hour, the hour alone is the same time: "soat 10 da" and "10:00".
            self.add(*match.span(), 'time', key, [{key, str(hour)} if minutes == '00' else {key}],
                     {str(hour)} if minutes == '00' else ())
        for match in PHONE.finditer(text):
            token = match.group(1)
            digits = re.sub(r'\D', '', token)
            groups = re.findall(r'\d+', token)
            if not 7 <= len(digits) <= 15 or not self.free(*match.span()):
                continue
            marked = token.startswith('+') or '(' in token or '-' in token
            thousands = re.fullmatch(rf'\d{{1,3}}(?:{GAP}\d{{3}})+', token) is not None
            years = all(len(group) == 4 and group[:2] in ('19', '20') for group in groups)
            if (thousands and not marked) or years:
                continue
            self._phone(match.start(1), match.end(1), digits)
        for match in LONG.finditer(text):
            if self.free(*match.span()):
                digits = match.group(0)
                self.add(*match.span(), 'phone', digits, [{str(int(digits)), 'tel:' + digits[-9:]}],
                         {'tel:' + digits[-7:]})
        for pattern in (GROUPED, DOTTED, PLAIN):
            for match in pattern.finditer(text):
                if not self.free(*match.span()):
                    continue
                token = match.group(0)
                if pattern is GROUPED:
                    groups = re.split(GAP, re.split(r'[.,]', token)[0])
                    tail = re.split(r'[.,]', token)[1] if re.search(r'[.,]', token) else ''
                    kind = 'decimal' if tail else 'integer'
                    found = [Decimal(f"{int(''.join(groups))}{'.' + tail if tail else ''}")]
                    # Its groups are not numbers of their own: "1 150 000" never makes "150" or "1" the customer's.
                    extra = set()
                else:
                    kind, found = _readings(token)
                    extra = set()
                if kind == 'parts':
                    # "1.2.3": not one number; each of its parts must be known.
                    self.add(*match.span(), 'integer', canon(found[0]), [{canon(item)} for item in found])
                    continue
                power, end = _scale(text, match.end())
                needs = {canon(item) for item in found}
                if kind == 'decimal' and pattern is DOTTED and re.fullmatch(r'\d{1,2}[.]\d{1,2}', token):
                    day, month = token.split('.')
                    if _valid(day, month):
                        # "03.11" is a date as often as a decimal.
                        needs.add(_date_key(day, month))
                if power:
                    extra |= needs
                    found = [item * (Decimal(10) ** power) for item in found]
                    needs = {canon(item) for item in found}
                    kind = 'scaled'
                self.add(match.start(), end, kind, canon(found[0]), [needs], extra)
        self.numbers.sort(key=lambda number: number.start)
        return self.numbers

    def _phone(self, start, end, digits):
        keys = {digits, 'tel:' + digits[-9:]} if len(digits) >= 9 else {'tel:' + digits}
        # A phone's groups stay phone keys: "+998 90 123 45 67" never makes "45" a price the customer gave.
        extra = {'tel:' + digits[-7:], 'tel:' + digits}
        self.add(start, end, 'phone', digits, [keys], extra)


def found(text):
    """Every number of `text`, in order, as Numbers."""
    return _Reader(str(text or '')).read()


def known(number, values):
    """Whether `values` (from `values()`) holds this number in one of the ways it may be written."""
    return all(need & values for need in number.needs)


def unknown(text, values):
    """The numbers of `text` that `values` does not hold."""
    return [number for number in found(text) if not known(number, values)]


def values(text):
    """Every value `text` gives as a set of keys: what a number the model wrote is looked up in."""
    keys = set()
    for number in found(text):
        for need in number.needs:
            keys |= need
        keys |= number.extra
    keys |= _words(text)
    return keys


def _words(text):
    """Numbers written as words, in Uzbek (either alphabet), Russian and English."""
    keys = set()
    (other, other_values), (uzbek, uzbek_values) = WORD_TABLES
    for word in set(WORD.findall(normalised(str(text or '')).lower())):
        match = other.fullmatch(word)
        if match is None:
            latin = normalised(to_latin(word)).lower() if re.search('[а-яёўқғҳ]', word) else word
            match = uzbek.fullmatch(latin)
            values = uzbek_values
        else:
            values = other_values
        if match is not None:
            keys.add(str(values[match.lastgroup]))
    return keys
