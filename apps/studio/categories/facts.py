"""Never invent, in code: what a category document says is held to what the customer said.

A category document is made from one message and the customer's files. The
prompt forbids inventing a person, organisation, date, number, price, law,
quotation or source, and this module checks that the model kept to it
(architecture section 4). It is the CV's fact check (cv/content.fact_check)
generalised, and it never sees a value it would log: what it takes out is
reported as codes.

- `trusted(data)` is everything the customer has said: the description, the
  pasted text and the files, every change request and the first description,
  the cover lines they keep and their brand name, and the parts of the document
  as it stood before a change that were held to their words when it was made
  (its facts, grounded parts and verified sources, never the model's guarded
  prose, whose text may only be quoted or cited again).
- `supported(value, kind, trusted)` decides one fact the model read out of
  that, by the kind of its field: a person's or an organisation's capitalised
  words must be the customer's (with a case ending allowed), a date, sum or
  reference number must be one the customer gave however it is written
  (numbers.py), an e-mail, a link or a handle ("@oqtosh_mebel") must be
  found whole.
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
A person's name in a document written in another language than the message is
also matched as Russian spells Uzbek names, with o as а (`respellings`). Such a
document's organisations and places are translated, so their words cannot be
looked up; a grounded part still holds every capitalised run to the customer's
names in those looser spellings, because an invented person must never pass
for a translated organisation. A paper's facts are held the same way
(`supported`'s `strict`), since its org, line and list fields name signers
and participants. A translated organisation's name may then be blanked: a
false blank, never an invention.
Folding can only make two spellings of the customer's own name meet; what it
cannot see is said plainly in the architecture: a name the model writes in
lower case, a wrong case ending. A transliteration the table misses blanks a
real name, which is a false blank and never an invention, and is counted.

More limits, said as plainly:
- A name is matched against every word the customer gave, lower case included,
  with an ending allowed, so "rahbarlik" supports "Rahbarov" and "salom"
  supports "Salomova". With long files most surnames find such a word.
- In `ground` the first word of a sentence is never blanked, so an invented
  "Javohir Saidov" opening a sentence becomes "Javohir ____". A slot whose
  `checks` hold names (`guard`) takes the whole run instead, and a grammar word
  before an invented name may go with it (`_names`). There a lone first word
  is held only when it is shaped as a surname ("Xolmatovga yuklansin."), so an
  invented given name alone at the start of a sentence still passes.
- `guard` removes any sentence with a strong legal stem (kodeks, farmon,
  Konstitutsiya ...) the customer did not give, even one that cites nothing
  specific ("U ko‘plab farmonlar chiqargan"), and a part may come back empty.
- A quotation is read by its marks (`QUOTE`): one written with none, an
  attribution only ("Filip Kotler ta’kidlaganidek, marketing — bu ..."), is
  not told from the model's own words and is not checked.
"""
import math
import re
import unicodedata
from dataclasses import dataclass, field, replace

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
# The forms numbers.py skips, read in linear time there (numbers.EMAIL_PATTERN says how).
EMAIL = re.compile(numbers.EMAIL_PATTERN)
LINK = re.compile(numbers.LINK_PATTERN, re.IGNORECASE)
HANDLE = re.compile(numbers.HANDLE_PATTERN)
# A handle given as a link, "t.me/oqtosh_mebel", "instagram.com/oqtosh_mebel": the same account as "@oqtosh_mebel".
HANDLE_LINK = re.compile(r"(?:t|telegram)\.me/([A-Za-z0-9_]{3,32})|instagram\.com/([A-Za-z0-9_.]{3,32})",
                         re.IGNORECASE)
VOWELS = set('aeiouy')
# What a name takes in a sentence when it is three letters long and cannot meet the common-prefix rule:
# "Aliga", "Alining", "Алию", "Ali's" (folded).
ENDINGS = frozenset(('ning', 'ni', 'ga', 'ka', 'da', 'dan', 'dagi', 'lar', 'larga', 'larni', 'larning', 'lardan',
                     'a', 'u', 'om', 'e', 'oy', 'i', 'em', 'im', 's', 'ov', 'ova'))
# Words a document may capitalise that are no one's facts: formulas of address and closing, the polite forms of
# "you" that letters capitalise, titles, legal forms, currencies, role and unit acronyms, months, weekdays,
# languages and the country's own name. The entry's labels and fixed headings and its templates' labels are added
# per draft (`trusted`). They are matched whole, never by prefix: a prefix rule let "Jumayev" through as "juma",
# "Hurmatov" as "hurmat" and "Martin Bestuzhev" as "mart" and "best", so every form a formula word takes in a
# letter is listed instead ("Sizga", "Уважаемая", "Вашего").
ALLOWED = (
    "hurmatli hurmatlim muhtaram muhtarama assalomu alaykum hurmat bilan janob janobi janoblari xonim xonimlar "
    "siz sizga sizni sizning sizdan sizda sizlar sizlarga sizlarni sizlarning sizlardan "
    "dear sincerely regards respectfully yours faithfully truly kind best sir sirs madam mr mrs ms miss dr prof "
    "phd dsc you your i'm i've i'd i'll "
    # Academic titles, which a translated cover capitalises ("Supervisor: Associate Professor N. Rahimova"), with their
    # short forms ("Checked by: Assoc. Prof. B. Rahimov"), and the "No." of "School No. 21".
    "professor professors associate assistant senior lecturer docent dotsent dotsenti professori akademik academician "
    "assoc dots no "
    "доцент доцента профессор профессора академик старший преподаватель "
    "уважаемый уважаемая уважаемое уважаемые уважаемого уважаемой уважаемому уважаемым уважаемых "
    "глубокоуважаемый глубокоуважаемая глубокоуважаемые глубокоуважаемого глубокоуважаемой здравствуйте уважением "
    "вы вас вам вами ваш ваша ваше ваши вашего вашей вашему вашим вашими ваших вашу "
    "господин господина господину господином госпожа госпожи госпоже госпожу госпожой "
    "mchj aj xk qk yatt ooo ao pao ip llc ltd inc jsc plc gmbh ооо оао пао зао ао ип "
    "usd uzs eur rub gbp cny kzt so'm сум сума сумов рубль рубля рублей "
    "ceo cfo cto coo hr it pr qa kpi smm crm erp api ai ikt ict id qqs nds ндс vat inn stir инн "
    "pdf docx xlsx pptx kg km mb gb "
    "yanvar fevral mart aprel may iyun iyul avgust sentabr sentyabr oktabr oktyabr noyabr dekabr "
    "january february march april june july august september october november december "
    "январь февраль март апрель май июнь июль август сентябрь октябрь ноябрь декабрь "
    "января февраля марта апреля мая июня июля августа сентября октября ноября декабря "
    "январе феврале марте апреле мае июне июле августе сентябре октябре ноябре декабре "
    "dushanba seshanba chorshanba payshanba juma shanba yakshanba monday tuesday wednesday thursday friday "
    "saturday sunday понедельник вторник среда среду четверг пятница пятницу суббота субботу воскресенье "
    "o'zbek o'zbekcha ingliz inglizcha rus ruscha nemis fransuz arab turk xitoy koreys yapon qozoq qirg'iz tojik "
    "uzbek english russian german french arabic turkish chinese korean japanese kazakh kyrgyz tajik "
    "узбекский русский английский немецкий французский арабский турецкий китайский корейский японский казахский "
    "киргизский таджикский "
    "o'zbekiston o'zbekistonda o'zbekistonning o'zbekistonga o'zbekistondan respublikasi respublikasining "
    "respublikasida uzbekistan узбекистан узбекистана узбекистане узбекистану республика республики республике "
    "whom concern ladies gentlemen господа дамы"
).split()
# The people a letter is addressed to by their role, which letters capitalise: "Hurmatli Direktor!", "Muhtaram
# Rektor", "Hurmatli Hay’at a’zolari", "Уважаемый Директор", "Dear Hiring Manager". A role is no one's name, so it is
# allowed with the endings a sentence gives it, listed as whole words (`_forms`), never by prefix: a prefix would let
# Rahbarov or Mudirova through as rahbar and mudir. A role that is also a given name (rais, dean) is left out. The
# Uzbek endings hold no -ov, -ova or -ev, nor the Russian forms -ов or -ев, the endings of surnames made from such
# words (Директоров, Советов).
UZ_ROLES = ("direktor rektor prorektor dekan mudir rahbar rahbariyat boshliq hokim vazir prezident menejer "
            "ustoz domla muallim muallima o‘qituvchi tarbiyachi xodim hamkasb hamkor mijoz jamoa kengash komissiya "
            "hay’at a’zo ishtirokchi mehmon ota-ona talaba o‘quvchi").split()
UZ_ENDINGS = ('', 'i', 'si', 'ga', 'iga', 'siga', 'ni', 'ini', 'sini', 'ning', 'ining', 'sining', 'da', 'ida',
              'sida', 'dan', 'idan', 'sidan', 'lar', 'lari', 'larga', 'lariga', 'larni', 'larini', 'larning',
              'larining', 'miz', 'imiz', 'mizga', 'imizga', 'im', 'imga', 'm', 'mga')
RU_ROLES = ("директор директора директору директором директоре директорам "
            "ректор ректора ректору ректором ректоре проректор проректора проректору декан декана декану деканом "
            "руководитель руководителя руководителю руководителем руководители руководителей руководство руководства "
            "председатель председателя председателю председателем заведующий заведующая заведующему заведующей "
            "заведующего начальник начальника начальнику начальником коллеги коллегам коллега коллектив коллектива "
            "коллективу комиссия комиссии члены членам совет совета совету партнёры партнёрам партнеры партнерам "
            "клиенты клиентам учитель учителя учителю учителем преподаватель преподавателя преподавателю").split()
EN_ROLES = ("hiring manager team committee member board recruitment recruiter director principal head rector "
            "chair chairman chairperson colleague partner customer client department faculty officer staff "
            "teacher parent guest participant").split()


def _forms():
    """Every allowed word as typed, the roles with the endings a sentence gives them."""
    forms = list(ALLOWED) + list(RU_ROLES)
    forms += [role + ending for role in UZ_ROLES for ending in UZ_ENDINGS]
    forms += [role + ending for role in EN_ROLES for ending in ('', 's')]
    return forms


def _folded(words):
    return frozenset(word for item in words for word in FOLDED_WORD.findall(fold(item)))


# Abbreviations whose full stop does not end a sentence, so the capitalised word after one is still checked:
# "prof. Xolmirzayev", "B. Rahimov", "ул. Садовая".
# A single letter is always an initial.
ABBREVIATIONS = frozenset((
    'prof', 'dots', 'dr', 'mr', 'mrs', 'ms', 'jr', 'sr', 'st', 'no', 'nr', 'tel', 'fig', 'vol', 'pp', 'vs', 'approx',
    'acad', 'akad', 'ch', 'sh', 'mfy', 'ul', 'kv', 'im', 'str', 'gr', 'проф', 'доц', 'акад', 'тел', 'им', 'ул', 'кв',
    'стр', 'гр'))
# A folded word shaped as a surname or a patronymic, with the case endings a sentence gives it in either language:
# Xolmatov, Xolmatovga, Xolmatovaning, Холматову, Холматовой, Xolmirzayev (folded xolmirzaev), Karimovna,
# Karimovich. Three letters at least come before the -ov or -ev, so "Lev" and "Kiev" are not read as one.
SURNAME_SHAPE = re.compile(
    r'[^\W\d_]{3,}(?:ov|ev)(?:a|na|ich)?(?:ga|ka|ni|ning|da|dan|dagi|lar|larga|larni|larning|u|e|im|om|oy|ix)?')
# Common words of that shape that are no one's name: tanlov (a contest), sinov (a test), to‘lov (a payment, folded
# tulov), with the same endings.
SHAPED_WORDS = re.compile(
    r'(?:tanl|sin|tul)ov(?:ga|ni|ning|da|dan|dagi|lar|larga|larni|larning)?')
OPENING = ' \t«“„"\'‘(['
LIST_MARKS = '-–—•*·'
# A quotation in any of the marks the three languages use: «…», “…”, „…“, "…", and the single ones ‘…’, '…', ‹…›,
# ‚…‘. A single mark opens only where no letter or digit stands before it and closes only where none follows, and
# inside it stands only between two letters: so Uzbek o‘, g‘ and the tutuq (ma’lumot, o'quvchi) and an English
# apostrophe (Drucker's, students') never open or close one, while ‘bilim — o‘quvchining burchi’ is read whole.
SINGLE_INSIDE = r"(?:[^{marks}\n]|(?<=[^\W\d_])[{marks}](?=[^\W\d_])){{1,800}}?"
QUOTE = re.compile(
    r'«([^«»]{1,800})»|“([^“”]{1,800})”|„([^„“”]{1,800})[“”]|"([^"\n]{1,800})"'
    r"|(?<![^\W_])‘(?=\S)(" + SINGLE_INSIDE.format(marks='‘’') + r")’(?![^\W\d_])"
    r"|(?<![^\W_])'(?=\S)(" + SINGLE_INSIDE.format(marks="'") + r")'(?![^\W\d_])"
    r"|‹([^‹›\n]{1,800})›|‚([^‚‘’\n]{1,800})[‘’]")
SENTENCE_END = re.compile(r'[.!?…]+(?=[\s"»”)\]]|$)|\n+')
# Legal references, by what they cite, in the three languages (normalised, lower case). A strong stem is a
# citation by itself; a weak one also means something else ("Nyutonning ikkinchi qonuni", "qaror qabul qilish",
# "kimyoviy modda", "in his article") and is a citation only with a mark of one beside it (`LEGAL_MARK`).
LAW = (
    ('constitution', r"konstitutsiya(?!viy)\w*|конституци(?:я|и|ю|ей|ях)|constitutions?", True),
    ('code', r"kodeks\w*|кодекс\w*", True),
    ('code', r"codes?", False),
    ('decree', r"farmon\w*|указ(?:а|е|ом|у|ы|ов|ами|ах)?|decrees?", True),
    ('order', r"farmoyish\w*|распоряжени\w*", True),
    # "order" in English, never "in order to".
    ('order', r"buyru[qg]\w*|приказ\w*|(?<!in )orders?(?![ \t]+to(?![^\W\d_]))", False),
    ('resolution', r"постановлени\w*", True),
    ('resolution', r"qaror\w*|resolutions?", False),
    ('law', r"qonun(?!iyat)\w*|закон(?!омерн)\w*|laws?|acts?", False),
    ('article', r"modda\w*|стать(?:я|и|е|ю|ей|ям|ях)|articles?", False),
    ('regulation', r"nizom\w*|положени\w*|regulations?", False),
    ('convention', r"konvensiya\w*|конвенци\w*|conventions?", False),
)
# "593-son", "PF-5712-son", "625-I-son": an act's number. "187-sonli buyruq" is the adjective, a mark (`LEGAL_MARK`)
# rather than a citation of its own, since "1-sonli jadval" and "45-sonli maktab" cite nothing.
# The number of an act, "593-son", "625-I-son", in either reading below.
SON = r"\d(?:[ \u00a0]?-[ \u00a0]?[ivxlc]{1,4})?[ \u00a0]?-[ \u00a0]?son"
NUMBERED = re.compile(SON + r"(?:i|ga|da|dan|ning)?(?![^\W\d_])")
# What makes a weak stem a citation (lower case). A bare digit anywhere in the sentence does not: "modda 100 °C da
# qaynaydi", "2 ta qaror", "Ohm's law ... in 1827" are general knowledge. A number belongs to the citation only
# when it is attached the way a citation attaches it: "214-moddasi" (an Uzbek count is "3 modda", never with the
# hyphen), "статья 214", "Article 214 of ..." or "under Article 214" ("Article 3 discusses" is a paper's own
# article), "№ 5" and "No. 5", "593-son" (`NUMBERED`), or a dd.mm.yyyy date right beside the stem (`DATED`).
LEGAL_MARK = re.compile(
    r"\d+\s*-\s*(?:modda|band|qism)\w*"
    r"|(?<![^\W\d_])(?:стать|пункт|част)\w*\s*№?\s*\d"
    r"|(?<![^\W\d_])(?:articles?|sections?)\s+\d+[\w.()]*\s+of(?![^\W\d_])"
    r"|(?<![^\W\d_])(?:under|pursuant to|according to|in accordance with|per)\s+(?:articles?|sections?)\s+\d"
    r"|№\s*\d|(?<![^\W\d_])no\.?\s*\d"  # language.normalised writes № as "No"
    r"|to'g'risida|togrisida|respublika|республик|federal|федеральн|mahkama|министр|prezident|президент"
    r"|oliy majlis|parliament|парламент"
    # A ministry's or the government's act: "vazirligining 187-sonli buyrug‘i", "hukumat qarori", "Ministry ... order".
    r"|" + SON + r"li|vazirli[gk]|hukumat|ministr(?:y|ies)|министерств")
DATED = re.compile(r"(?<![\d.])\d{1,2}[./]\d{1,2}[./](?:\d{4}|\d{2})(?!\d)")
# How far from a weak stem a date may stand and still be its date: "17.07.2019 dagi qaror", "закон от 12.05.2020".
DATED_REACH = 30
STEMS = [(concept, re.compile(rf'(?<![^\W\d_])(?:{stem})(?![^\W\d_])', re.IGNORECASE), strong)
         for concept, stem, strong in LAW]


def fold(text, *, respelled=False):
    """`text` as both sides of every comparison are read: the spellings of one name across the alphabets made one.

    `respelled` is the looser reading of a person's name in a document written
    in another language than the message (`respellings`).
    """
    text = normalised(str(text or '')).casefold().translate(LATIN)
    text = ''.join(char for char in unicodedata.normalize('NFKD', text) if not unicodedata.combining(char))
    # o‘ is u in Russian spelling (Toshpo‘latova, Тошпулатова); an English possessive ("Two's") is not an o‘.
    text = re.sub(r"o'(?!s\b)", 'o' if respelled else 'u', text).replace("'", '')
    text = re.sub('dzh|dj|zh', 'j', text)
    text = text.replace('sh', '\x01').replace('ch', '\x02').replace('kh', 'x').replace('h', 'x')
    text = text.replace('\x01', 'sh').replace('\x02', 'ch')
    text = text.replace('yo', 'e').replace('q', 'k').replace('w', 'v')
    # ц is s in the Uzbek table and ts in English ("Цой", "Tsoy"); only where a word starts, so "Vaqt's" stays.
    text = re.sub(r'\bts', 's', text)
    # ya and ia, yu and iu inside a word (Mariya, Maria); never where a word starts, which made the month "Yanvar"
    # an allowed spelling of the name Anvar.
    text = re.sub(r'(?<=[^\W\d_])y(?=[aeiou])', '', text)
    text = re.sub(r'iy\b', 'i', text)
    return text.replace('o', 'a') if respelled else text


def respellings(word):
    """The folded forms a name may take when a translation spells it anew.

    Russian writes an Uzbek o as а and an o‘ as о or у (G‘ofurov and Гафуров,
    Xo‘jayev and Ходжаев, Yo‘ldoshev and Юлдашев), which the plain fold keeps
    apart. Both sides are read with o as a and o‘ as both o and u.
    """
    return {fold(word).replace('o', 'a'), fold(word, respelled=True)}


# The allowed words folded once, here, rather than for every draft.
FORMULAS = _folded(_forms())


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
        return self.has(fold(word))

    def has(self, word):
        """`known` for a word already folded."""
        if not word:
            return True
        if word in self.exact:
            return True
        if len(word) < 3:
            return False
        return any(_close(word, other) for other in self.index.get(word[:3], ()))


class Exact:
    """A set of folded words matched whole: the words no one's facts are in, where an ending would let a name in."""

    def __init__(self, words=()):
        self.exact = frozenset(words)

    def known(self, word):
        word = fold(word)
        return not word or word in self.exact


@dataclass(frozen=True)
class Trusted:
    """What the customer said, read once per job in every form the checks look it up in."""

    words: Words
    allowed: Exact
    values: frozenset
    flat: str
    lower: str
    emails: frozenset
    links: frozenset
    said: str = ''
    # The customer's handles, lower case with their "@" ("@oqtosh_mebel"), from the text and from t.me/ links.
    handles: frozenset = frozenset()
    # What is read from `said` only when needed. `counting` makes a new Trusted with dataclasses.replace, which hands
    # this same dict on, so a slide's counted copy never folds the whole source again.
    cache: dict = field(default_factory=dict, compare=False, repr=False)

    @property
    def respelled(self):
        """The customer's words in their respelled forms, read only when a document is in another language."""
        if 'respelled' not in self.cache:
            folded = fold(self.said)
            self.cache['respelled'] = Words([*FOLDED_WORD.findall(folded.replace('o', 'a')),
                                             *FOLDED_WORD.findall(fold(self.said, respelled=True))])
        return self.cache['respelled']

    def person(self, word, translated=False):
        """Whether a capitalised word of a person's name is the customer's or one no one's facts are in."""
        if self.allowed.known(word) or self.words.known(word):
            return True
        return translated and any(self.respelled.has(form) for form in respellings(word))


def _link(text):
    return re.sub(r'^(?:https?://)?(?:www\.)?', '', text.lower()).rstrip('/.,;)')


def trusting(text, *, allowed=(), wording=''):
    """A Trusted from plain text, `allowed` being more words no one's facts are in (labels, headings).

    `wording` is text whose quotations and legal sentences may be repeated but
    whose names and numbers are not the customer's: the earlier version of a
    document, model prose included. It reaches only the quotation and the
    legal-concept lookups.
    """
    text = str(text or '')
    folded = fold(text)
    words = Words(FOLDED_WORD.findall(folded))
    allow = Exact(FORMULAS | _folded(allowed))
    wording = str(wording or '')
    quoted = flat(text, folded=folded) + (flat(wording) if wording.strip() else '')
    lower = normalised(text).casefold() + ('\n' + normalised(wording).casefold() if wording.strip() else '')
    return Trusted(words, allow, frozenset(numbers.values(text)), quoted, lower,
                   frozenset(email.lower().strip('.') for email in EMAIL.findall(text)),
                   frozenset(_link(link) for link in LINK.findall(EMAIL.sub(' ', text))), text, _handles(text))


def _handles(text):
    """The handles `text` gives, from "@name" and from a t.me/ or instagram.com/ link, lower case with their "@"."""
    found = {handle.lower() for handle in HANDLE.findall(EMAIL.sub(' ', text))}
    found |= {'@' + (match.group(1) or match.group(2)).lower().rstrip('.') for match in HANDLE_LINK.finditer(text)}
    return frozenset(found)


def counting(trusted, count):
    """`trusted` that also holds one count the document makes of itself (a slide's rows), never a fact of anyone's."""
    if not count:
        return trusted
    return replace(trusted, values=trusted.values | frozenset(numbers.values(str(count))))


def _texts(content):
    return [text for _, text in _fields(content)] if isinstance(content, dict) else []


def _held(content, entry):
    """The texts of an earlier version whose values were held to the customer's words when it was made.

    That is the `facts` section, the grounded parts, the customer's and the
    template's slots and the verified sources. Guarded prose and deck draft
    slots are the model's, where general knowledge is allowed: a year or a name
    written there must never become the customer's on the next change. A deck's
    sections are `s1..sN` and its slot mapping may no longer hold after the
    customer edited slides, so they resolve to no part and give nothing here.
    """
    if entry is None or not isinstance(content, dict):
        return []
    def kept(section):
        if section.get('id') == 'facts':
            return True
        part = entry.part(section.get('id'))
        return bool(part) and bool(part.get('grounded') or part.get('kind') == 'sources'
                                   or part.get('source') in ('customer', 'template'))
    sections = [section for section in content.get('sections') or [] if isinstance(section, dict) and kept(section)]
    return [text for _, text in _fields({'sections': sections}) if text]


def _fields(content):
    from ..scripts import fields
    return [(path, text) for path, text in fields(content) if isinstance(text, str)]


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
    category = options.get('category')
    entry = catalogue.get(category) if isinstance(category, str) else None
    # A change keeps only the latest request and the first description; what an earlier change gave lives on in the
    # document it went into. Only the parts held to the customer's words are read back as theirs (`_held`); the whole
    # earlier text may still be quoted or cited, never mined for names and numbers.
    earlier = [revision.get('before'), revision.get('base_content')]
    for content in earlier:
        parts += _held(content, entry)
    wording = '\n'.join(text for content in earlier for text in _texts(content) if text)
    return trusting('\n'.join(str(part) for part in parts if part), allowed=_catalogue_words(entry), wording=wording)


# ---------------------------------------------------------------- one fact


def _strip_addresses(text, trusted):
    """(text without its e-mails, links and handles, whether every one of them is the customer's, found whole)."""
    whole = True
    for email in EMAIL.findall(text):
        whole = whole and email.lower().strip('.') in trusted.emails
    text = EMAIL.sub(' ', text)
    for handle in HANDLE.findall(text):
        whole = whole and handle.lower() in trusted.handles
    text = HANDLE.sub(' ', text)
    for link in LINK.findall(text):
        whole = whole and _link(link) in trusted.links
    return LINK.sub(' ', text), whole


def _names_known(text, trusted, translated=False):
    """Whether every capitalised word of two letters or more is the customer's or one no one's facts are in."""
    for match in WORD.finditer(text):
        word = match.group(0)
        if not word[0].isupper() or len(re.sub(r"['‘’ʻʼ`´]", '', word)) < 2:
            continue
        if not trusted.person(word, translated):
            return False
    return True


def supported(value, kind, trusted, *, translated=False, strict=False, words=False):
    """Whether a fact of this kind is the customer's (architecture 4, "Verifying").

    person, org, place, line: every capitalised word is theirs and every number
    is one they gave; date, number, money, ref, phone, text: every number;
    email: found whole; list: each line as a line; choice, flag, file: not
    checked here. `translated` (the document is in another language than the
    message) checks names for a person only: organisations and places are
    translated, a person's name only spelled anew, which the fold meets, with
    the Russian spellings of o and o‘ allowed (`respellings`).

    `strict` is for a paper's facts, where translation never switches the
    names off: a paper draws its org, place, line and list values in a
    letterhead, a title page, the minutes' head and its signature rows, and
    those hold people ("Rais: …", "Director | …", a list of participants) as
    often as a person field does. With `translated` they are then read as a
    person's are, in the looser spellings, so a translated organisation whose
    words do not fold to the customer's is not kept: a false blank, never an
    invention, and never one that a later change would read back as theirs.

    `words` also reads the numbers written as words (numbers.SPELLED): a
    paper's "five years", "besh yuz million so‘m" or "двенадцать человек" must
    be a value the customer gave, as its digits must.
    """
    if kind in ('choice', 'flag', 'file') or value is None or isinstance(value, bool):
        return True
    text = str(value).strip()
    if not text or not re.sub(r'[_\s.\-]', '', text):
        return True  # nothing, or the blank the model returns for an if_needed field
    if kind == 'list':
        return all(supported(line, 'line', trusted, translated=translated, strict=strict, words=words)
                   for line in re.split(r'[\n;]+', text) if line.strip())
    rest, whole = _strip_addresses(text, trusted)
    if not whole:
        return False
    read = numbers.found(rest, words=words, uzbek_cyrillic=False)
    if not all(numbers.known(number, trusted.values) for number in read):
        return False
    if kind in ('person', 'org', 'place', 'line') and (strict or not translated or kind == 'person'):
        return _names_known(rest, trusted, translated)
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
    found, weak, dated = set(), set(), False
    for concept, stem, strong in STEMS:
        for match in stem.finditer(text):
            # A weak stem capitalised inside a sentence is a title ("Mehnat Kodeksi", "Labour Code", "Закон о …").
            if strong or (match.group(0)[0].isupper() and not _starts(text, match.start())):
                found.add(concept)
            else:
                weak.add(concept)
                reach = text[max(0, match.start() - DATED_REACH):match.end() + DATED_REACH]
                dated = dated or DATED.search(reach) is not None
    lower = text.casefold()
    if NUMBERED.search(lower):
        found.add('number')
    if weak and (found or dated or LEGAL_MARK.search(lower)):
        found |= weak
    return found


# The codes and laws a sentence names by a word before its stem ("Soliq kodeksi", "Трудовой кодекс", "Labour Code"),
# by what they are, in the three languages: in a paper in another language than the message, the customer's "Трудовой
# кодекс" is the paper's "Mehnat kodeksi", and only that.
LAW_NAMES = (
    r"mehnat|трудов|labou?r", r"soliq|налог|tax", r"jinoyat|уголовн|criminal", r"fuqarolik|гражданск|civil",
    r"ma'muriy|административн|administrative", r"oila|семейн|family", r"bojxona|таможен|customs",
    r"yer|земельн|land", r"uy-joy|жилищн|housing", r"bu?d?jet|бюджетн|budget", r"saylov|избирательн|elector",
    r"suv|водн|water", r"o'rmon|лесн|forest", r"shaharsozlik|градостроительн|urban", r"ta'lim|образован|education",
)
LAW_NAME_FORMS = [re.compile(rf"(?<![^\W\d_])(?:{forms})", re.IGNORECASE) for forms in LAW_NAMES]


# The stems a code or a law is named before: "Soliq kodeksi", "Labour Code", "Education Act". A constitution, a
# decree or an article is not ("День Конституции" is a day, not a constitution's name).
NAMED_STEMS = [stem for concept, stem, _ in STEMS if concept in ('code', 'law')]


def _law_names(sentence):
    """The words naming a code or a law: a run of capitalised words right before its stem, or ending in it.

    "Soliq kodeksi", "Jinoyat kodeksiga", "Mehnat Kodeksi", "Labour Code". They are held wherever they stand, a
    sentence's or a list item's first word included: there the start of a sentence was taken for grammar, and an
    invented "Jinoyat kodeksiga muvofiq javobgar bo‘ladi" passed once the customer had named any code.
    """
    found = []
    for run in _runs(sentence):
        named = [index for index, word in enumerate(run) if any(stem.fullmatch(word[2]) for stem in NAMED_STEMS)]
        if named:
            names = run[:named[0]]
        else:
            after = re.match(r"[ \t\u00a0]+([^\W\d_]+)", sentence[run[-1][1]:])
            if not after or not any(stem.fullmatch(after.group(1)) for stem in NAMED_STEMS):
                continue
            names = run
        if len(names) > 1 and _starts(sentence, names[0][0]) and not _law_name(names[0][2]):
            names = names[1:]  # "The Criminal Code", "Согласно Трудовому кодексу": the first word is grammar
        found += [(start, word) for start, _, word in names if _letters(word) >= 2]
    return found


def _law_name(word):
    """The forms (LAW_NAME_FORMS) of the code or law a word names, or None."""
    folded = normalised(word).casefold()
    return next((forms for forms in LAW_NAME_FORMS if forms.match(folded)), None)


def _law_name_known(word, trusted):
    """Whether a word naming a code in a translated paper is the customer's: the same code named in any language."""
    forms = _law_name(word)
    if forms is not None:
        return forms.search(trusted.lower) is not None
    return trusted.allowed.known(word) or trusted.person(word, True)


def _legal_known(sentence, concepts, trusted, translated):
    for concept in concepts - {'number'}:
        if not any(stem.search(trusted.lower) for name, stem, _ in STEMS if name == concept):
            return False
    if not all(numbers.known(number, trusted.values) for number in numbers.found(sentence)):
        return False
    named = _law_names(sentence)
    if translated:
        # A translated sentence's other words are the translation's; the code it names is still the customer's.
        return all(_law_name_known(word, trusted) for _, word in named)
    held = {start for start, _ in named}
    for match in WORD.finditer(sentence):
        word = match.group(0)
        if (word[0].isupper() and len(word) >= 2 and (match.start() in held or not _starts(sentence, match.start()))
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


def _numbers(text, trusted, codes, words=False):
    spans = [(number.start, number.end) for number in numbers.found(text, words=words, uzbek_cyrillic=False)
             if not _enumerator(text, number) and not numbers.known(number, trusted.values)]
    if spans:
        codes.append('ground:number')
    return _replace(text, spans)


def _addresses(text, trusted, codes):
    # An e-mail, a link or a handle is a contact detail, counted with the numbers: never a name, quotation or law.
    emails = list(EMAIL.finditer(text))
    spans = [match.span() for match in emails if match.group(0).lower().strip('.') not in trusted.emails]
    # A link is looked for with the e-mails masked, so the domain of a known address is not read as a link.
    masked = EMAIL.sub(lambda match: ' ' * len(match.group(0)), text)
    spans += [match.span() for match in HANDLE.finditer(masked) if match.group(0).lower() not in trusted.handles]
    # A handle is masked too, so "@namuna.uz" is never also read as the link "namuna.uz".
    masked = HANDLE.sub(lambda match: ' ' * len(match.group(0)), masked)
    spans += [match.span() for match in LINK.finditer(masked) if _link(match.group(0)) not in trusted.links]
    if spans:
        codes.append('ground:number')
    return _replace(text, spans)


def _runs(text):
    """Runs of capitalised words side by side (an initial's full stop between allowed): [[(start, end, word)]].

    An initial joins the word after it with or without a space ("S. Xolmatov",
    "S.Xolmatov"), so it goes with that word when the word is blanked.
    """
    runs, current = [], []
    for match in WORD.finditer(text):
        word = match.group(0)
        capital = word[0].isupper()
        if current and capital and re.fullmatch(r"[ \t\u00a0]*|\.[ \t\u00a0]*", text[current[-1][1]:match.start()]) \
                and (text[current[-1][1]:match.start()].strip() != '.' or len(current[-1][2]) == 1):
            current.append((match.start(), match.end(), word))
            continue
        if current:
            runs.append(current)
        current = [(match.start(), match.end(), word)] if capital else []
    if current:
        runs.append(current)
    return runs


def _letters(word):
    return len(re.sub(r"['‘’ʻʼ`´]", '', word))


def _surname(word):
    """Whether a word is shaped as a surname or a patronymic (`SURNAME_SHAPE`), not a common word of that shape."""
    folded = fold(word)
    return SURNAME_SHAPE.fullmatch(folded) is not None and SHAPED_WORDS.fullmatch(folded) is None


def _after_colon(text, position):
    """Whether the word at `position` is the first after a colon: a label's value ("mas’ul: Xolmatov S.")."""
    at = position - 1
    while at >= 0 and text[at] in OPENING:
        at -= 1
    return at >= 0 and text[at] == ':'


def _names(text, trusted, codes, translated=False, *, strict=False):
    """Blank the runs of capitalised words that are not the customer's (see `ground`).

    The first word of a sentence is capitalised by grammar ("Bunga",
    "Shuningdek") and is not blanked; an invented name that is a sentence's first
    word is then a limit the architecture names. `strict` is for the slots that
    name people as a label's value or a row of their own (a resolution's
    "mas’ul: …", an agenda's "Ma’ruzachi: …"), where that limit let the very form
    they ask for through. There the first word is held too when it follows a
    colon, when only initials follow it in its run ("Xolmatov S."), or when
    another word of its run is blanked ("Sardor Xolmatov", and so also "Nazorat
    Sardor Xolmatov": a grammar word before an invented name may go with it, a
    false blank in a sentence that had one anyway), or when it is shaped as a
    surname and is not the customer's ("Xolmatovga yuklansin.", "1. Xolmatov
    javobgar", "— Xolmatov"); the initials beside a blanked word go with it,
    their full stops included, so no part of an invented name is left. A lone
    grammar word opening a sentence stays, and so does one before the
    customer's own people ("Nazorat Namunova M."). An invented given name alone
    at the start of a sentence ("Sardor javobgar.") is still read as grammar.
    """
    spans = []
    for run in _runs(text):
        bad = []
        first_free = _starts(text, run[0][0])
        if strict and first_free and (_after_colon(text, run[0][0])
                                      or (len(run) > 1 and all(_letters(word) < 2 for _, _, word in run[1:]))
                                      or _surname(run[0][2])):
            first_free = False
        for position, (start, end, word) in enumerate(run):
            if _letters(word) < 2 or (position == 0 and first_free):
                continue
            if not trusted.person(word, translated):
                bad.append(position)
        if strict and bad:
            if first_free and bad[0] != 0 and _letters(run[0][2]) >= 2 and not trusted.person(run[0][2], translated):
                bad.insert(0, 0)
            taken = set(bad)
            for position in bad:
                for step in (-1, 1):
                    near = position + step
                    while 0 <= near < len(run) and _letters(run[near][2]) < 2:
                        taken.add(near)
                        near += step
            bad = sorted(taken)
        group = []
        for position in bad:
            if group and position != group[-1] + 1:
                spans.append(_span(text, run, group, strict))
                group = []
            group.append(position)
        if group:
            spans.append(_span(text, run, group, strict))
    if spans:
        codes.append('ground:name')
    return _replace(text, spans)


def _span(text, run, group, strict):
    """Where a group of a run's blanked words starts and ends; with `strict`, a last initial's full stop included."""
    start, end = run[group[0]][0], run[group[-1]][1]
    if strict and _letters(run[group[-1]][2]) < 2 and text[end:end + 1] == '.':
        end += 1
    return start, end


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
    `translated` (the part is in another language than the message) also lets
    a capitalised word through in the spellings a translation gives a person's
    name (`respellings`); every run is still checked, as a person's, so a
    translated organisation's name may be blanked but an invented person never
    passes. Numbers, quotations and laws are always checked.
    """
    codes = []
    text = str(text or '')
    if not text.strip():
        return text, codes
    text = _laws(text, trusted, translated, codes)
    text = _quotes(text, trusted, codes)
    text = _addresses(text, trusted, codes)
    text = _numbers(text, trusted, codes)
    text = _names(text, trusted, codes, translated)
    return _tidy(text), list(dict.fromkeys(codes))


def guard(text, trusted, *, translated=False, checks=(), words=False):
    """(text, codes): any other category part, with no quotation and no legal reference the customer did not give.

    Names, numbers and general knowledge are left as SYSTEM allows them in a
    subject paper; a quotation that is not the customer's becomes ____ and a
    legal sentence that is not theirs is removed, in any language.

    `checks` are the catalogue's for a draft slot that also states the
    customer's own facts (a council's problems and resolution, a parents'
    meeting's requests), where a percentage, a deadline, a fee or a person
    would rest on the prompt alone: 'numbers' holds its numbers, e-mails and
    links as `ground` does, 'names' its runs of capitalised words, more strictly
    than `ground` at the start of a sentence or a label's value, since these
    slots name a responsible person or a reporter in just that place (`_names`).
    `words` makes 'numbers' read the numbers written as words too
    (numbers.SPELLED), which a paper's grounded parts ask for: "five years of
    experience" or "yigirma foiz" the customer never gave becomes ____.
    """
    codes = []
    text = str(text or '')
    if not text.strip():
        return text, codes
    text = _laws(text, trusted, translated, codes)
    text = _quotes(text, trusted, codes)
    if 'numbers' in checks:
        text = _addresses(text, trusted, codes)
        text = _numbers(text, trusted, codes, words)
    if 'names' in checks:
        text = _names(text, trusted, codes, translated, strict=True)
    return _tidy(text), list(dict.fromkeys(codes))


def people_known(text, trusted, *, translated=False):
    """Whether guard's 'names' check would leave `text` whole: every capitalised run the customer's, read strictly.

    For a line that is kept or dropped whole, such as a title-page line: a
    first word is free only as `_names` leaves it free in strict mode, so a
    line's own opening word ("Grocery shop", "Term paper") is not taken for a
    name, but a surname, a word before initials or before an invented name is.
    """
    codes = []
    _names(str(text or ''), trusted, codes, translated, strict=True)
    return not codes


# ---------------------------------------------------------------- references


# An author at the head of a references item, the way a list writes one: a surname with one or two initials after it
# ("Karimov A.", "Каримов А. А.") or before it ("A. Karimov"), then a comma, a full stop or a space before the next
# author or the title. Only a surname of two letters or more beside its initials counts, so a title's "Part I." is
# never read as one: it is not at the head of the item.
INITIALS = r"[^\W\d_]\.(?:[ \t\u00a0]?[^\W\d_]\.)?"
SURNAME = r"[^\W\d_](?:[^\W\d_]|['‘’ʻʼ`´-](?=[^\W\d_]))+"
AUTHOR = re.compile(rf"[ \t\u00a0]*(?:(?P<surname>{SURNAME})[ \t\u00a0,]+{INITIALS}"
                    rf"|{INITIALS}[ \t\u00a0]?(?P<after>{SURNAME}))[ \t\u00a0]*[,;.]?")


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


def _authors(text):
    """The surnames of the authors a references item opens with: "Karimov A., Saidova B. B. Title" or "A. Karimov. Title"."""
    found, at = [], 0
    while True:
        match = AUTHOR.match(text, at)
        if not match:
            return found
        found.append(match.group('surname') or match.group('after'))
        at = match.end()


def _authors_known(text, trusted):
    return all(trusted.person(surname, True) for surname in _authors(text))


def verify_items(items, trusted, *, file_names=(), translated=False):
    """(kept, codes): the items of a references list that are the customer's sources, in order.

    Each is held as a line to what the customer said and the files' own text
    (a book they named, a description taken from a file's first page). One
    that is not, or that is an attached file's name with or without its
    extension, is dropped: a references list never shows a file name.
    `translated` is for a list written in another language than the message,
    whose titles are translated: its capitalised words are then not checked,
    only its numbers and the authors it opens with ("Karimov A."), which are
    people's names and only spelled anew, so pass it only when the titles
    really are translated.
    """
    kept, codes = [], []
    for item in items or []:
        text = _item_text(item).strip()
        if not text:
            continue
        if _file_name(text, file_names) or not supported(text, 'line', trusted, translated=translated) \
                or (translated and not _authors_known(text, trusted)):
            codes.append('source:dropped')
            continue
        kept.append(item)
    return kept, list(dict.fromkeys(codes))
