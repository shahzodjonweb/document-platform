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
the model writes is read strictly by `found`. With `words`, `found` also reads
the cardinals written as words, compounds and scales included ("five years",
"besh yuz million so‘m", "более пяти лет"), which a paper's grounded parts and
facts ask for (`SPELLED`); `values` always reads them, so a figure the
customer wrote in words meets the model's digits. It is never generous with parts
of one number: the groups of "1 150 000" or of a phone, and the day and month of
"03.11.2026", are not numbers the customer gave.

Numbers inside an e-mail or a link are not numbers; facts.py checks those whole.
"""
import functools
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
# A thin or narrow no-break space before the scale word is a space too ("1,5\u202fmln"), and "bn" and "mn" are the
# English papers' billion and million ("$1.2bn"): read as the bare number, a changed scale passed on any number the
# customer gave.
SCALE = re.compile(r"[ \u00a0\u202f\u2009]*(ming|минг|тыс\w*\.?|thousand\w*|mln\.?|млн\.?|million\w*|миллион\w*"
                   r"|mlrd\.?|млрд\.?|milliard\w*|миллиард\w*|billion\w*|trln\.?|трлн\.?|trillion\w*|bn|mn)(?!\w)"
                   r"|(k)(?![^\W\d_])", re.IGNORECASE)
SCALES = (('ming', 3), ('минг', 3), ('тыс', 3), ('thousand', 3), ('k', 3), ('mln', 6), ('млн', 6), ('million', 6),
          ('миллион', 6), ('mlrd', 9), ('млрд', 9), ('milliard', 9), ('миллиард', 9), ('billion', 9), ('trln', 12),
          ('трлн', 12), ('trillion', 12), ('bn', 9), ('mn', 6))
# "$3M", "€3m", "$1.2B", "3M USD": a capital M or B, or a small m, glued to an amount is its million or billion only
# beside a currency, since "100 m" is metres and "9B sinf" a class.
GLUED_SCALE = re.compile(r"([MBm])(?![^\W\d_])")
GLUED_POWER = {'M': 6, 'm': 6, 'B': 9}
CURRENCY_BEFORE = re.compile(r"[$€£₽¥][ \u00a0]?$")
CURRENCY_AFTER = re.compile(r"[ \u00a0\u202f\u2009]*(?:usd|eur|gbp|rub|uzs|so['‘’ʻ]?m|sum|dollar\w*|euro\w*|evro\w*"
                            r"|руб\w*|долл\w*|евро|сум\w*)(?![^\W\d_])", re.IGNORECASE)
# An e-mail and a link as facts.py reads them (and as this module skips them), written to be read in time linear in
# the text: a file of long runs of letters, dots and hyphens made the plain forms try every start in a run and read
# the whole run from each, about 15 s for one 130,000-character source, inside the job's lease. Each run is now read
# once from where it may start: an address's local part is at most 64 characters (its own limit), a host label at
# most 63 and a host at most ten labels before its ending, read possessively, and a host starts only where a word
# starts outside another host ("ab.cd.uz" is tried at "ab", never again at "cd", which the first try covered). On
# text with real addresses they match what the plain forms matched. The local part has no lookbehind, so one longer
# than 64 characters (no real address has one) is read as its last 64 and the host, the rest left as plain text;
# the customer's side and the model's are read alike, so such a text is still compared fairly.
EMAIL_PATTERN = r"[\w.+\-]{1,64}+@[\w\-]++(?:\.[\w\-]++)+"
# The endings are listed, never any letters: "S.Xolmatov" and "sh.Chilonzor" are no links. Beside the usual ones, the
# region's (kz, tj, kg, su) and the shops' (shop, store, online, site, co, de).
LINK_PATTERN = (r"(?:https?://|www\.)\S+|\b(?<!\w)(?<!\w-)(?<!\w\.)(?:[\w\-]{1,63}+\.){1,10}"
                r"(?:uz|com|ru|org|net|io|me|info|edu|gov|kz|tj|kg|su|shop|store|online|site|co|de)(?:/\S*)?(?!\w)")
# A Telegram or Instagram handle, "@oqtosh_mebel", "@namuna.mebel": a contact detail found whole, as an e-mail is.
# Never the "@" of an e-mail, which a letter or digit always stands before, nor a full stop that ends the sentence.
HANDLE_PATTERN = r"(?<![\w.@])@[A-Za-z0-9_](?:[A-Za-z0-9_.]{1,30}[A-Za-z0-9_])(?![\w@])"
SKIPPED = re.compile(f'{EMAIL_PATTERN}|{LINK_PATTERN}|{HANDLE_PATTERN}', re.IGNORECASE)

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

# Cardinal numbers written as words, read on both sides when `found` is asked for them (`words`): "five years",
# "twelve people", "two hundred clients", "besh yuz million so‘m", "yigirma foiz", "более пяти лет". A model asked
# never to invent a figure still writes one in words, which the digit reading never saw. Only cardinals are read,
# never an ordinal ("ikkinchi bob", "the second stage", nor the tens before one: "yigirma birinchi asr") nor "both"
# or "ikkala", and the words that are also ordinary words are read only where they must be numbers: "one", "bir",
# "один" and "a" only before a multiplier, after a ten or after a scale ("a hundred", "one million", "twenty-one",
# "bir yarim", "девять тысяч один"), a bare Uzbek "yuz" or "ming" (also a face, and "yuz berdi", it happened) only
# before a scale, a count of its own ("yuz ellik"), with -ta, before a counted noun ("yuz nafar", "ming tonna") or
# as "yuzdan ortiq" (`_bare`), any other scale word alone only in the Russian forms that cannot mean "thousands"
# ("тысяча рублей"), and "семью" never (also "family"). The common spoken forms are read too: an Uzbek count's case
# endings ("ellikdan ortiq"), a Russian count fused to what it counts ("пятилетний"), half a scale ("yarim milliard",
# "полмиллиона") and how many times over ("doubled", "вдвое"); "twice", "half", "decade" and the vague "o‘nlab",
# "hundreds" are not. Each word is a role and a value; a run of them side by side is one number (`_Reader.spelled`).
# The endings an Uzbek count takes as the last word of a number: "beshta", "ellikdan ortiq", "yigirmaga yetadi",
# "o‘ttiz birta", "ellikka yaqin", "o‘ngacha", "beshdagi", "ikkini"; never "-lab" (o‘nlab, yuzlab: tens, hundreds),
# which names no figure.
UZ_CASES = r"(?:ta\w*|[gkq]a|[gkq]acha|dan|da|dagi|ni|ning)?"
# Russian counts fused to what they count, "пятилетний опыт", "двухнедельный курс", "двадцатипятилетний",
# "сорокакратный": the count is the figure. "десятилетия" (decades) and "многолетний" (many years) name none.
RU_FUSED_TAIL = r"(?:летн|кратн|месячн|дневн|недельн|часов|минутн)\w*"
RU_FUSED_UNITS = (('двух', 2), ('тр[её]х', 3), ('четыр[её]х', 4), ('пяти', 5), ('шести', 6), ('семи', 7),
                  ('восьми', 8), ('девяти', 9))
RU_FUSED_TENS = (('двадцати', 20), ('тридцати', 30), ('сорока', 40), ('пятидесяти', 50), ('шестидесяти', 60),
                 ('семидесяти', 70), ('восьмидесяти', 80), ('девяноста', 90))
RU_FUSED_ALONE = RU_FUSED_UNITS + RU_FUSED_TENS + (
    ('десяти', 10), ('одиннадцати', 11), ('двенадцати', 12), ('тринадцати', 13), ('четырнадцати', 14),
    ('пятнадцати', 15), ('шестнадцати', 16), ('семнадцати', 17), ('восемнадцати', 18), ('девятнадцати', 19),
    ('сто', 100))
RU_FUSED = tuple((stem + RU_FUSED_TAIL, 'unit', value) for stem, value in RU_FUSED_ALONE) + tuple(
    (tens + unit + RU_FUSED_TAIL, 'unit', ten + one) for tens, ten in RU_FUSED_TENS for unit, one in RU_FUSED_UNITS)
SPELLED = (
    # English.
    (r"one", 'one', 1), (r"an?", 'article', 1), (r"two", 'unit', 2), (r"three", 'unit', 3), (r"four", 'unit', 4),
    (r"five", 'unit', 5), (r"six", 'unit', 6), (r"seven", 'unit', 7), (r"eight", 'unit', 8), (r"nine", 'unit', 9),
    (r"ten", 'unit', 10), (r"eleven", 'unit', 11), (r"twelve", 'unit', 12), (r"thirteen", 'unit', 13),
    (r"fourteen", 'unit', 14), (r"fifteen", 'unit', 15), (r"sixteen", 'unit', 16), (r"seventeen", 'unit', 17),
    (r"eighteen", 'unit', 18), (r"nineteen", 'unit', 19), (r"twenty", 'tens', 20), (r"thirty", 'tens', 30),
    (r"forty", 'tens', 40), (r"fifty", 'tens', 50), (r"sixty", 'tens', 60), (r"seventy", 'tens', 70),
    (r"eighty", 'tens', 80), (r"ninety", 'tens', 90), (r"hundred", 'hundred', 100), (r"dozen", 'dozen', 12),
    (r"thousand", 'scale', 3), (r"million", 'scale', 6), (r"billion", 'scale', 9), (r"trillion", 'scale', 12),
    (r"thirds?", 'fraction', 3), (r"and", 'and', 0),
    # How many times over: "doubled", "tripled", "fivefold"; "twice" and "double" are left, being ordinary words too.
    # A number of its own, never part of a count beside it (`_Reader._spelled_run`).
    (r"doubled", 'times', 2), (r"tripled", 'times', 3), (r"quadrupled", 'times', 4),
    *((rf"{word}fold", 'times', value) for word, value in (
        ('two', 2), ('three', 3), ('four', 4), ('five', 5), ('six', 6), ('seven', 7), ('eight', 8), ('nine', 9),
        ('ten', 10))),
    # Russian, in the cases a count takes.
    (r"один|одна|одно|одного|одной|одному|одним|одну", 'one', 1),
    (r"полтора|полторы|полутора", 'unit', Decimal('1.5')),
    (r"два|две|двух|двум|двумя|двое|двоих", 'unit', 2), (r"три|тр[её]х|тр[её]м|тремя|трое|троих", 'unit', 3),
    (r"четыре|четыр[её]х|четыр[её]м|четырьмя|четверо|четверых", 'unit', 4),
    (r"пять|пяти|пятью|пятеро|пятерых", 'unit', 5),
    (r"шесть|шести|шестью|шестеро|шестерых", 'unit', 6), (r"семь|семи|семеро|семерых", 'unit', 7),
    (r"восемь|восьми|восемью|восьмью", 'unit', 8), (r"девять|девяти|девятью", 'unit', 9),
    (r"десять|десяти|десятью", 'unit', 10),
    *((rf"{stem}надцат(?:ь|и|ью)", 'unit', value) for stem, value in (
        ('один', 11), ('две', 12), ('три', 13), ('четыр', 14), ('пят', 15), ('шест', 16), ('сем', 17),
        ('восем', 18), ('девят', 19))),
    (r"двадцат(?:ь|и|ью)", 'tens', 20), (r"тридцат(?:ь|и|ью)", 'tens', 30), (r"сорок|сорока", 'tens', 40),
    (r"пятьдесят|пятидесяти|пятьюдесятью", 'tens', 50), (r"шестьдесят|шестидесяти", 'tens', 60),
    (r"семьдесят|семидесяти", 'tens', 70), (r"восемьдесят|восьмидесяти", 'tens', 80),
    (r"девяносто|девяноста", 'tens', 90),
    # The hundreds in every case: "с тремястами клиентами", "пятистам", "о двухстах".
    (r"сто|ста", 'unit', 100), (r"двести|двухсот|двумстам|двумястами|двухстах", 'unit', 200),
    (r"триста|тр[её]хсот|тр[её]мстам|тремястами|тр[её]хстах", 'unit', 300),
    *((rf"{nominative}|{stem}(?:сот|стам|стами|стах)|{instrumental}стами", 'unit', value)
      for nominative, stem, instrumental, value in (
          ('четыреста', 'четыр[её]х', 'четырьмя', 400), ('пятьсот', 'пяти', 'пятью', 500),
          ('шестьсот', 'шести', 'шестью', 600), ('семьсот', 'семи', 'семью', 700),
          ('восемьсот', 'восьми', 'восемью', 800), ('девятьсот', 'девяти', 'девятью', 900))),
    # A ten as a noun, "десятком сотрудников" ("десятки", tens, names no figure).
    (r"десяток|десятка|десятку|десятком|десятке", 'unit', 10),
    (r"тысяча|тысячу|миллион|миллиона|миллиард|миллиарда", 'alone', 0),
    (r"тысяч\w*|тыс", 'scale', 3), (r"миллион\w*|млн", 'scale', 6), (r"миллиард\w*|млрд", 'scale', 9),
    (r"триллион\w*|трлн", 'scale', 12), (r"треть|трети", 'fraction', 3),
    # A hundred as a noun, "сотню клиентов" ("сотни", hundreds, names no figure); half a scale, "полмиллиона"; and
    # how many times over, "вдвое", "впятеро".
    (r"сотня|сотню|сотней", 'unit', 100), (r"полмиллиона", 'unit', 500000), (r"полмиллиарда", 'unit', 500000000),
    (r"полтысячи", 'unit', 500),
    *((rf"в{stem}", 'times', value) for stem, value in (
        ('двое', 2), ('трое', 3), ('четверо', 4), ('пятеро', 5), ('шестеро', 6), ('семеро', 7), ('восьмеро', 8),
        ('девятеро', 9), ('десятеро', 10))),
    # A count fused to what it counts: "пятилетний опыт", "двухнедельный", "двадцатипятилетний" (RU_FUSED).
    *(RU_FUSED),
    # Uzbek (Latin; Cyrillic is read in Latin first). "uchdan bir" is a third; a count takes the endings of a case,
    # "ellikdan ortiq", "yigirmaga yetadi", "beshta", "o‘ttiz birta" (UZ_CASES), and "bir" keeps the role of "one",
    # so "birdan" (suddenly) and "birga" (together) are never read alone.
    (r"bir" + UZ_CASES, 'one', 1), (r"yarim", 'half', Decimal('0.5')),
    *((re.escape(stem) + r"dan", 'denominator', value) for stem, value in UZ_STEMS[:9]),
    # "oltini" is also "its gold".
    *((re.escape(stem) + (UZ_CASES.replace('|ni|', '|') if stem == 'olti' else UZ_CASES),
       'tens' if value >= 20 or stem == "o'n" else 'unit', value) for stem, value in UZ_STEMS),
    (r"yuz" + UZ_CASES, 'hundred', 100),
    (r"ming" + UZ_CASES, 'scale', 3), (r"million\w*|mln", 'scale', 6),
    (r"milliard\w*|mlrd", 'scale', 9), (r"trillion\w*|trln", 'scale', 12),
)
SPELLED_TABLE = re.compile('|'.join(f'(?P<s{index}>{pattern})' for index, (pattern, _, _) in enumerate(SPELLED)))
SPELLED_ROLES = {f's{index}': (role, value) for index, (_, role, value) in enumerate(SPELLED)}
SPELLED_POWER = {'тысяча': 3, 'тысячу': 3, 'миллион': 6, 'миллиона': 6, 'миллиард': 9, 'миллиарда': 9}
SPELLED_TOKEN = re.compile(r"[^\W\d_]+(?:['‘’ʻʼ`´][^\W\d_]+)*")
# What follows an English fraction: "a third of the clients", "by a third."; "a third option" is an ordinal.
FRACTION_END = re.compile(r"[ \t\u00a0]+of(?![^\W\d_])|[ \t\u00a0]*(?:[.,;:!?)]|$)")
# What two number words of one number may stand apart by: spaces, or a hyphen ("twenty-five", "besh-olti").
SPELLED_GAP = re.compile(r"[ \t\u00a0]*(?:[-–][ \t\u00a0]*)?")
# What a bare Uzbek "yuz" or "ming" counts: "yuz nafar", "yuz foiz", "ming tonna"; elsewhere "yuz" is a face or "yuz
# berdi" (it happened). Read on the Latin form, so "Юз нафар" counts too.
UZ_COUNTED = re.compile(r"[ \t\u00a0]+(?:foiz|nafar|kishi|so'm|sum|dollar|evro|rubl|gektar|tonna|metr|kilo\w*|yil|oy|"
                        r"kun|soat|daqiqa|marta|mijoz|xodim|o'quvchi|talaba|dona|xil|ish o'rn|o'rin|o'rn|oila|xonadon|"
                        r"litr|nusxa|sahifa|savol|ball)", re.IGNORECASE)
# What a bare "yuzdan" or "mingga" is a count before: "yuzdan ortiq", "mingga yaqin".
UZ_ABOUT = re.compile(r"[ \t\u00a0]+(?:ortiq|ko'p|ziyod|oshiq|yaqin|kam|yet|osh)", re.IGNORECASE)
# A word that makes the number words right before it an ordinal's: "yigirma birinchi", "twenty-first", "двадцать
# первом", "o‘n beshinchi". The run is then not a count: "the twenty-first century" names no figure of twenty.
ORDINAL = re.compile(
    r"(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|\w+teenth|\w+tieth"
    r"|hundredth|thousandth|millionth)"
    r"|(?:bir|ikki|uch|to'rt|besh|olti|yetti|sakkiz|to'qqiz|o'n|yigirma|o'ttiz|qirq|ellik|oltmish|yetmish|sakson"
    r"|to'qson|yuz|ming|million|milliard)i?nchi\w*"
    r"|перв\w*|втор(?:ой|ая|ое|ого|ом|ую|ые|ых|ым|ыми|ому|ою)|трет(?:ий|ья|ье|ьего|ьем|ью|ьи|ьих|ьему|ьей|ьим)"
    r"|четв[её]рт\w*|(?:пят|шест|седьм|восьм|девят|десят|\w+надцат|двадцат|тридцат|сороков|пятидесят|шестидесят"
    r"|семидесят|восьмидесят|девяност|сот|тысячн)(?:ый|ой|ая|ое|ого|ом|ую|ые|ых|ым|ыми|ому|ей)")
# No number is read past this: a run of thousands of "hundred"s once made a value too long to write as digits.
SPELLED_CAP = Decimal(10) ** 24
# A year written beside a day and a month in words is that date's year, as a numeric date's is: "2025-yil 12-may",
# "12 мая 2025 года", "1 September 2023", "May 12, 2025". The customer's "1 September 2019" never makes the model's
# "1 September 2023", though 2023 is a year they wrote elsewhere.
YEAR_AFTER = re.compile(r"(?:[ \u00a0]*,)?[ \u00a0]+((?:19|20)\d{2})"
                        r"(?:[ \u00a0]*-?[ \u00a0]*(?:yil\w*|y\.|г\.|года|году|год))?(?![\d]|[.,]\d)", re.IGNORECASE)
YEAR_BEFORE = re.compile(r"(?<![\d.,])((?:19|20)\d{2})[ \u00a0]*-?[ \u00a0]*(?:yil(?:ning|da|i)?|y\.)[ \u00a0,]*$",
                         re.IGNORECASE)


class Number(NamedTuple):
    """One number of a text. `needs` holds sets of keys: it is known when each set meets the known values."""

    start: int
    end: int
    kind: str  # integer, decimal, amount (may be either), scaled, date, time, phone
    value: str
    needs: tuple
    # Keys it gives the customer's side beyond its needs: a date's day as a number, an amount's unscaled value.
    extra: frozenset = frozenset()
    # What it gives the customer's side in place of its needs, when the two differ: a dated day and month gives its
    # own year, never the "any year" its needs also accept ("d:15.1.?").
    gives: frozenset = None


def canon(number):
    """A Decimal as its key: "1150000", "1.5"; never an exponent or a trailing zero, below 10**30."""
    if number.adjusted() >= 30:
        return format(number.normalize(), 'E')  # past any real figure; never a string of thousands of digits
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


def _scale(text, end, start=None):
    """(power of ten, end) of the scale word right after a number ("1,5 mln", "20 ming", "$3M"), or (0, end)."""
    match = SCALE.match(text, end)
    if not match:
        glued = GLUED_SCALE.match(text, end)
        if glued and start is not None and (CURRENCY_BEFORE.search(text[max(0, start - 2):start])
                                            or CURRENCY_AFTER.match(text, glued.end())):
            return GLUED_POWER[glued.group(1)], glued.end()
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

    def __init__(self, text, cyrillic=True):
        self.text = text
        # Whether a word in Cyrillic is also read as Uzbek put in Latin ("беш юз минг"): the customer's side. A
        # paper's own Cyrillic is Russian (Uzbek is written in Latin), where that reading made "тень" ten.
        self.cyrillic = cyrillic
        # One byte per character, set where a number (or an address) was read: a long file has thousands of numbers.
        self.taken = bytearray(len(text))
        self.numbers = []
        self.words = False
        for match in SKIPPED.finditer(text):
            self.take(match.start(), match.end())

    def take(self, start, end):
        self.taken[start:end] = b'\x01' * (end - start)

    def free(self, start, end):
        return 1 not in self.taken[start:end]

    def add(self, start, end, kind, value, needs, extra=(), gives=None):
        self.numbers.append(Number(start, end, kind, value, tuple(frozenset(need) for need in needs),
                                   frozenset(extra), None if gives is None else frozenset(gives)))
        self.take(start, end)

    def read(self, words=False):
        # A paper's reading (`words`) also ties a written date's year to it (`dated`); a deck's reads as before.
        self.words = words
        self._digits()
        if words:
            self.spelled()
        self.numbers.sort(key=lambda number: number.start)
        return self.numbers

    def _digits(self):
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
                key, year = _date_key(day, month), str(int(year))
                # Day and month are a pair here, never two plain numbers: "03.11.2026" does not give "3" or "11". And
                # the year is tied to them: the customer's "15.01.2025" never makes the model's "15.01.2024", though
                # 2024 is a year they wrote elsewhere. A day and month they wrote with no year tied to it ("15-yanvar",
                # "2025-yil 15-yanvar", "15.01") gives "d:15.1.?", which any of their years may complete.
                self.add(*match.span(), 'date', key, [{f'{key}.{year}', f'{key}.?'}, {year}],
                         gives={key, f'{key}.{year}', year})
        for match in RANGE.finditer(text):
            month = _month(match.group(3))
            first, second = match.group(1), match.group(2)
            if month is None or not (_valid(first, month) and _valid(second, month)) \
                    or _small(text, match.start(), *match.span(3)):
                continue
            if not self.free(*match.span()):
                continue
            self.add(match.start(1), match.end(1), 'date', _date_key(first, month), [{_date_key(first, month)}],
                     {str(int(first)), _date_key(first, month) + '.?'})
            self.add(match.start(2), match.end(), 'date', _date_key(second, month), [{_date_key(second, month)}],
                     {str(int(second)), _date_key(second, month) + '.?'})
        for match in DAY_MONTH.finditer(text):
            month = _month(match.group(2))
            if month is None or not _valid(match.group(1), month) or not self.free(*match.span()) \
                    or _small(text, match.start(), *match.span(2)):
                continue
            self.dated(match.start(), match.end(), match.group(1), month)
        for match in MONTH_DAY.finditer(text):
            month = _month(match.group(1))
            days = [day for day in (match.group(2), match.group(3)) if day]
            if month is None or not all(_valid(day, month) for day in days) or not self.free(*match.span()):
                continue
            if len(days) == 1:
                self.dated(match.start(), match.end(), days[0], month)
                continue
            needs = [{_date_key(day, month)} for day in days]
            self.add(*match.span(), 'date', _date_key(days[0], month), needs,
                     {str(int(day)) for day in days} | {_date_key(day, month) + '.?' for day in days})
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
                power, end = _scale(text, match.end(), match.start())
                needs = {canon(item) for item in found}
                if kind == 'decimal' and pattern is DOTTED and re.fullmatch(r'\d{1,2}[.]\d{1,2}', token):
                    day, month = token.split('.')
                    if _valid(day, month):
                        # "03.11" is a date as often as a decimal, with no year tied to it.
                        needs.add(_date_key(day, month))
                        extra.add(_date_key(day, month) + '.?')
                if power:
                    extra |= needs
                    found = [item * (Decimal(10) ** power) for item in found]
                    needs = {canon(item) for item in found}
                    kind = 'scaled'
                self.add(match.start(), end, kind, canon(found[0]), [needs], extra)

    def dated(self, start, end, day, month):
        """A day and a month written in words, with the year written beside them tied to them (`YEAR_AFTER`)."""
        text, key = self.text, _date_key(day, month)
        after = YEAR_AFTER.match(text, end) if self.words else None
        before = YEAR_BEFORE.search(text, max(0, start - 24), start) if self.words else None
        if after is not None and self.free(end, after.end()):
            end, year = after.end(), after.group(1)
        elif before is not None and self.free(before.start(), start):
            start, year = before.start(), before.group(1)
        else:
            self.add(start, end, 'date', key, [{key}], {str(int(day)), key + '.?'})
            return
        # As a numeric date's: the customer's tied year gives no other year its day and month ("d:12.5.?").
        self.add(start, end, 'date', key, [{f'{key}.{year}', f'{key}.?'}, {year}], {str(int(day))},
                 gives={key, f'{key}.{year}', year})

    def spelled(self):
        """The cardinal numbers written as words (`SPELLED`), outside every number and address already read.

        A run of number words straight before an ordinal ("yigirma birinchi asr", "the twenty-first century") is an
        ordinal's tens, not a count, and is left unread.
        """
        text, run = self.text, []
        for match in SPELLED_TOKEN.finditer(text):
            role = None
            free = self.free(*match.span())
            if free:
                role = _spelled_role(match.group(0), self.cyrillic)
            beside = bool(run) and SPELLED_GAP.fullmatch(text[run[-1][1]:match.start()]) is not None
            if role is None and beside and free and _ordinal(text, match):
                run = []
                continue
            if role is None or (run and not beside):
                self._spelled_run(run)
                run = []
            if role is not None:
                run.append((match.start(), match.end(), *role, match.group(0)))
        self._spelled_run(run)

    def _spelled_run(self, run):
        """Read a run of number words side by side as one number or several ("besh-olti kun" is 5 and 6)."""
        text = self.text
        total, current, last, first, end, fraction = Decimal(0), None, None, None, None, None
        # Whether the number so far is only an "a" or "one" waiting for its multiplier, which is no number alone.
        lone = False
        # The power of the last scale word taken into `total`, where that part of the number ends, and where the
        # count after it starts: "ikki ming - uch ming" is a range of two numbers, never 2 003 000.
        power_taken, taken_end, group = None, None, None
        # Whether the last word multiplied the count ("yuz", "hundred", "dozen"): another right after it ("hundred
        # hundred") starts no bigger number.
        multiplied = False

        def close():
            nonlocal total, current, last, first, end, lone, power_taken, taken_end, group, multiplied
            if first is not None and (total or current is not None) and not lone:
                value = canon(total + (current or 0))
                self.add(first, end, 'spelled', value, [{value}])
            total, current, last, first, end, lone = Decimal(0), None, None, None, None, False
            power_taken, taken_end, group, multiplied = None, None, None, False

        def count(start, stop, value):
            """`value` added to the count after the last scale word."""
            nonlocal current, last, end, lone, group, first, multiplied
            if first is None:
                first = start
            if current is None:
                group = start
            current, last, end, lone, multiplied = (current or 0) + value, value, stop, False, False

        for index, (start, stop, role, value, word) in enumerate(run):
            after = run[index + 1][2] if index + 1 < len(run) else None
            if fraction is not None:
                begin, denominator = fraction
                fraction = None
                key = f'f:{canon(Decimal(value))}/{denominator}'
                self.add(begin, stop, 'fraction', key, [{key}])
                continue
            if role in ('one', 'article'):
                # "a", "one", "bir", "один": a number only before a multiplier or a fraction, after a ten ("twenty-one",
                # "o‘ttiz birta"), or after a scale ("bir million bir yuz ...", "девять тысяч один").
                if role == 'one' and current is not None and last is not None and last >= 10 and last % 10 == 0:
                    current, last, end = current + 1, 1, stop
                    continue
                if role == 'one' and total and current is None and (
                        after in ('hundred', 'dozen', 'half')
                        or (after is None and not _hyphenated(text, stop) and not _counting_one(text, word, stop))):
                    group, current, last, end, lone, multiplied = start, Decimal(1), 1, stop, False, False
                    continue
                if after in ('hundred', 'dozen', 'scale', 'alone', 'fraction', 'half'):
                    close()
                    first, group, current, last, end, lone = start, start, Decimal(1), 1, stop, True
                    continue
                close()
                continue
            if role == 'times':
                # "doubled", "fivefold", "вдвое": how many times over, a number of its own; "a team of ten tripled
                # revenue" is ten, then three times, never 13.
                close()
                times = canon(Decimal(value))
                self.add(start, stop, 'spelled', times, [{times}])
                continue
            if role == 'and':
                # "two hundred and fifty", "one hundred and one": only between a multiplier and what it is added to.
                if current is None and not total or after not in ('unit', 'tens', 'one'):
                    close()
                continue
            if role == 'denominator':
                # "uchdan bir" is a third; "uchdan" alone is "from three".
                nxt = run[index + 1] if index + 1 < len(run) else None
                if nxt is not None and nxt[2] in ('one', 'unit') and nxt[3] < value:
                    close()
                    fraction = (start, value)
                    continue
                role = 'unit'
            if role == 'fraction':
                # "a third", "two thirds", "треть", "две трети"; a bare "third" is an ordinal.
                russian = word.casefold().startswith('трет')
                if (current is None and not russian) or (not russian and not FRACTION_END.match(text, stop)):
                    close()
                    continue
                if not russian and current >= 10:
                    # "the twenty-third of May": an ordinal, never 20/3.
                    total, current, last, first, end, lone = Decimal(0), None, None, None, None, False
                    power_taken, taken_end, group, multiplied = None, None, None, False
                    continue
                key = f'f:{canon(current if current is not None else Decimal(1))}/{value}'
                begin = first if first is not None else start
                total, current, last, first, end, lone = Decimal(0), None, None, None, None, False
                power_taken, taken_end, group, multiplied = None, None, None, False
                self.add(begin, stop, 'fraction', key, [{key}])
                continue
            if role in ('unit', 'tens'):
                value = Decimal(value)
                if current is not None and last is not None and len(str(int(value))) >= len(str(int(last))):
                    close()  # two counts side by side: a range ("besh-olti"), never their sum
                count(start, stop, value)
                continue
            if role == 'half':
                if current is not None and last is not None and last < 10:
                    current, last, end, lone = current + value, value, stop, False
                elif current is None and not total and after == 'scale':
                    # "yarim milliard": half the scale after it.
                    count(start, stop, value)
                else:
                    close()
                continue
            if role in ('hundred', 'dozen'):
                if multiplied:
                    close()  # "hundred hundred", "yuz yuz": no bigger number
                    continue
                if current is None:
                    # A bare "yuz" or "hundred": a number only where it must be one (`_bare`); after a scale it
                    # goes on the number ("ming yuz", 1100).
                    if not total and not _bare(text, word, role, stop, after):
                        close()
                        continue
                    if first is None:
                        first = start
                    group = start
                current, last, end, lone, multiplied = (current or Decimal(1)) * value, value, stop, False, True
                if total + current >= SPELLED_CAP:
                    close()
                continue
            power = SPELLED_POWER.get(word.casefold(), value) if role == 'alone' else value
            if current is None:
                if total:
                    close()  # "ming ming", "thousand million": a scale right after a scale counts nothing
                    continue
                if role != 'alone' and not _bare(text, word, role, stop, after):
                    continue  # "ming yillik", "thousands": no count before it
                first = group = start
                current = Decimal(1)
            elif power_taken is not None and power >= power_taken:
                # "ikki ming - uch ming": the count after a scale meets a scale as large again, so it is a number
                # of its own, never 2 003 000.
                value_so_far = canon(total)
                self.add(first, taken_end, 'spelled', value_so_far, [{value_so_far}])
                total, first = Decimal(0), group
            total, current, last, end = total + current * (Decimal(10) ** power), None, None, stop
            power_taken, taken_end, lone, multiplied = power, stop, False, False
            if total >= SPELLED_CAP:
                close()
        close()

    def _phone(self, start, end, digits):
        keys = {digits, 'tel:' + digits[-9:]} if len(digits) >= 9 else {'tel:' + digits}
        # A phone's groups stay phone keys: "+998 90 123 45 67" never makes "45" a price the customer gave.
        extra = {'tel:' + digits[-7:], 'tel:' + digits}
        self.add(start, end, 'phone', digits, [keys], extra)


@functools.lru_cache(maxsize=8192)
def _spelled_role(word, cyrillic=True):
    """(role, value) of a number word (`SPELLED`), Uzbek Cyrillic read in Latin when `cyrillic`, or None.

    Cached: a long source repeats its words, and each is tried against the whole table, twice for Cyrillic.
    """
    word = normalised(word).lower()
    match = SPELLED_TABLE.fullmatch(word)
    if match is None and cyrillic and re.search('[а-яёўқғҳ]', word):
        match = SPELLED_TABLE.fullmatch(normalised(to_latin(word)).lower())
    return SPELLED_ROLES[match.lastgroup] if match is not None else None

def _bare(text, word, role, stop, after):
    """Whether a multiplier with no count before it is a number: "a hundred thousand", "yuz ellik", "ming besh yuz".

    "hundred" or "yuz" before a scale; a bare Uzbek "yuz" or "ming" before a count of its own ("yuz ellik" is 150,
    never 50), with -ta ("mingta non"), before a counted noun ("yuz nafar", "ming tonna"; "ming yillik tarix" is no
    figure), or with -dan or -ga before "ortiq", "yaqin" ("yuzdan ortiq"). Elsewhere "yuz" is a face or "yuz
    berdi", and a scale word alone ("thousands", "ming afsus") counts nothing.
    """
    bare = normalised(to_latin(word)).casefold()
    if role != 'scale' and after == 'scale':
        return True
    if not bare.startswith(('yuz', 'ming')):
        return False
    if bare in ('yuz', 'ming') and after in ('unit', 'tens', 'one', 'denominator') \
            or bare == 'ming' and after == 'hundred':
        return True
    if bare.startswith(('yuzta', 'mingta')):
        return True
    rest = normalised(to_latin(text[stop:stop + 40]))
    counted = UZ_COUNTED.match(rest) if bare in ('yuz', 'ming') else None
    if counted is not None and not (bare == 'ming' and rest[counted.end():counted.end() + 3] == 'lik'):
        return True
    return bare.endswith(('dan', 'ga', 'gacha')) and UZ_ABOUT.match(rest) is not None


def _counting_one(text, word, stop):
    """Whether an Uzbek "bir" after a scale is the "one" of a price's "per one": "besh ming bir dona uchun" is five
    thousand for one piece, never 5001; "ming bir xodim" (1001 employees) and "ming bir kecha" stay one number."""
    if normalised(to_latin(word)).casefold() != 'bir':
        return False
    rest = normalised(to_latin(text[stop:stop + 60]))
    counted = UZ_COUNTED.match(rest)
    return counted is not None and re.match(r"[^\W\d_]*[ \t\u00a0]+uchun(?![^\W\d_])", rest[counted.end():]) is not None


def _hyphenated(text, stop):
    """Whether a word goes on in a hyphen and more letters ("one-time", "first-rate")."""
    return re.match(r"-[^\W\d_]", text[stop:stop + 2]) is not None


def _ordinal(text, match):
    """Whether a word is an ordinal standing alone ("birinchi", "first", "первом"), never "first-rate"."""
    return ORDINAL.fullmatch(normalised(match.group(0)).lower()) is not None and not _hyphenated(text, match.end())


def found(text, *, words=False, uzbek_cyrillic=True):
    """Every number of `text`, in order, as Numbers; with `words`, the cardinals written as words too (`SPELLED`).

    `uzbek_cyrillic` also reads a Cyrillic word as Uzbek put in Latin ("беш юз минг"), as the customer may write;
    a paper's own text is read without it (its Cyrillic is Russian, where "тень" and "уч." are no numbers).
    """
    return _Reader(str(text or ''), uzbek_cyrillic).read(words)


def known(number, values):
    """Whether `values` (from `values()`) holds this number in one of the ways it may be written."""
    return all(need & values for need in number.needs)


def unknown(text, values):
    """The numbers of `text` that `values` does not hold."""
    return [number for number in found(text) if not known(number, values)]


def values(text):
    """Every value `text` gives as a set of keys: what a number the model wrote is looked up in."""
    keys = set()
    for number in found(text, words=True):
        if number.gives is not None:
            keys |= number.gives
        else:
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
