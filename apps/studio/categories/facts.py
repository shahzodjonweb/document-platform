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
  invented given name alone at the start of a sentence still passes. A
  paper's grounded part (finish.ground_paper) also holds one that opens an
  organisation's name by its shape ("Hamkorbank ...", "Acme LLC ...",
  "«Baraka» MChJ ...") or by the Uzbek kind after it in the possessive a name
  gives it ("Asaka banki ...", "Artel kompaniyasidagi ...", never "Tijorat
  banki"), or that the same finish took out elsewhere, a rejected fact's or a
  blanked run's ("Artelda ishlaganman" when the employer Artel was blanked:
  only a word that names someone wherever it stands, matched whole or with a
  case ending, `Named`), or that is no common word of the three languages
  (`common`, words/*.txt): a brand, a city or a given name alone ("Korzinka",
  "Ucell bilan ...", "Smith led ...", a table's cell and a list item
  included). A given name, a surname, a place or a brand of words/names.txt
  is never a common word, even one that is also a word ("Umid", "Grace",
  "Надежда"): a false blank where it is the word ("Umid qilamanki"), never an
  invention, in a paper of any language: an English given name that is an
  Uzbek word ("Tom yopish") is blanked in an Uzbek paper too, since "Tom yangi
  filialni ochdi" names an invented person in the same words; and an English
  paper reads a Latin word against the English lexicon only (`common`'s
  `language`). A common word the lexicon lacks is held too: a false blank
  ("Sinergiya ..."), counted on held-out prose in the commit that grew it. A
  name that is an everyday word and is left out of names.txt ("Yangi",
  "Xalq", "Hikmat") still passes alone.
- `guard` removes any sentence with a strong legal stem (kodeks, farmon,
  Konstitutsiya ...) the customer did not give, even one that cites nothing
  specific ("U ko‘plab farmonlar chiqargan"), and a part may come back empty.
- A quotation is read by its marks (`QUOTE`): one written with none, an
  attribution only ("Filip Kotler ta’kidlaganidek, marketing — bu ..."), is
  not told from the model's own words and is not checked.
"""
import functools
import math
import re
import unicodedata
from dataclasses import dataclass, field, replace
from pathlib import Path

from ..language import normalised
from ..uzbek import LETTERS, to_latin
from . import numbers

BLANK = '____'
# Cyrillic put into Latin the house way (uzbek.py), with the Russian letters it leaves to taste spelled so that a
# name meets its Latin spelling: ц as ts, щ as sh, ё as yo, the signs dropped.
LATIN = str.maketrans({**LETTERS, 'ъ': '', 'ь': '', 'ц': 'ts', 'щ': 'sh', 'ё': 'yo', 'е': 'e', 'э': 'e', 'і': 'i',
                       'ї': 'i', 'є': 'e', 'ў': "o'", 'ғ': "g'", 'ҳ': 'h'})
WORD = re.compile(r"[^\W\d_](?:[^\W\d_]|['‘’ʻʼ`´](?=[^\W\d_]))*")
# The letters only Uzbek writes in Cyrillic: a customer's text with them is Uzbek, read in Latin too (`Trusted.legal`).
UZBEK_CYRILLIC = re.compile('[ўқғҳЎҚҒҲ]')
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
    # The words a seller's bank details carry: "MFO 00440", "TIN 301234567", "«Kapitalbank» ATB", "БИК", "IBAN".
    "mfo мфо tin atb akb aitb oked окэд bik бик swift iban bic kpp кпп okpo окпо ogrn огрн "
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
    "respublikasida uzbekistan republic узбекистан узбекистана узбекистане узбекистану республика республики республике "
    "whom concern ladies gentlemen господа дамы "
    # A class's own words, which a translated grade capitalises ("Year 7", "Grade 7").
    "year grade class"
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


# What an organisation's name runs into: its legal form or its kind ("Acme LLC", "«Baraka» MChJ", "Westminster
# University", "Uzum Market", "Xalq Banki"). In a paper's grounded part a run that does so is an organisation's name,
# so its opening word is held too, as a surname-shaped one is (`_names`'s `orgs`). Whole words, with the endings a
# sentence gives them, never by prefix.
ORG_FORMS = ("mchj aj atb akb xk qk yatt oaj llc ltd inc jsc plc gmbh corp ooo oao pao zao ao ip "
             "ооо оао пао зао ао ип").split()
ORG_KINDS = ("universitet institut akademiya kollej market supermarket gipermarket bank kompaniya xolding "
             "korporatsiya").split()
EN_ORG_KINDS = "university institute academy college market supermarket group holding bank company corporation".split()
# The Uzbek legal forms, which a sentence gives its endings ("«Baraka Savdo» MChJning", "AJga"): no one's name.
UZ_ORG_FORMS = "mchj aj atb akb aitb xk qk yatt oaj".split()
# An Uzbek name is followed by its kind in the possessive the name gives it, in lower case: "Asaka banki", "Artel
# kompaniyasidagi", "Westminster universitetida", "Korzinka supermarketi", "Akfa zavodida". Only that form counts
# (`ORG_AFTER`): a kind in the plural or bare ("Tijorat banklari", "Bizning kompaniyamiz", "Markaziy bank") follows
# no one's name. A chain is "Korzinka supermarketlar tarmog‘i" (`CHAIN`).
UZ_ORG_KINDS = ("bank kompaniya universitet institut akademiya kollej market supermarket gipermarket xolding "
                "korporatsiya firma korxona zavod fabrika shirkat klinika platforma").split()
UZ_CASES = ('', 'ga', 'da', 'dan', 'ning', 'ni', 'dagi', 'gacha')
# A place is followed so by its kind: "Samarqand shahrida", "Yunusobod tumanida", "Chilonzor mahallasida".
UZ_PLACES_AFTER = ("shahri viloyati tumani qishlog‘i mahallasi ko‘chasi").split()
# A Russian name is an adjective before its kind in lower case: "Вестминстерский университет", "Самаркандский
# филиал банка" is none. Only an adjective of a place's or a name's shape counts (-ский, -цкий), never one that makes
# the kind a kind ("Медицинский институт", "Коммерческий банк", "Городская школа").
RU_ORG_KINDS = re.compile(r"(?:университет|институт|колледж|академи|банк|завод|фабрик|компани|холдинг|супермаркет"
                          r"|гипермаркет|корпораци|комбинат)\w*")
RU_NAMED = re.compile(r"[а-яё]+[сц]к(?:ий|ая|ое|ого|ой|ом|ому|ую|ие|их|им|ими)")
RU_KIND_ADJECTIVES = re.compile(r"[а-яё]*(?:ическ|ческ|медицинск|городск|сельск|детск|женск|мужск|президентск"
                                r"|банковск|университетск|институтск|гражданск|частн|международн|тельск|торск)\w*")
RU_ADJECTIVE = re.compile(r"[а-яё]+(?:ый|ий|ой|ая|яя|ое|ее|ого|его|ому|ему|ым|им|ом|ем|ую|юю|ых|их|ыми|ими)")
# The words that make such a kind a kind of organisation, never one's name, opening a sentence: "Tijorat banki",
# "Davlat universiteti", "Xususiy klinikasi", "Qurilish kompaniyasi bilan ...", and a place or a platform a kind of
# one ("Ta’lim platformasi", "Onlayn platformasi", "Sanoat shahri").
KINDS_OF = ("tijorat davlat xususiy xorijiy mahalliy yirik kichik katta yangi ushbu mazkur bu shu har biror birorta "
            "boshqa bitta bir oliy xalqaro hamkor raqobatchi sug‘urta qurilish savdo logistika transport "
            "investitsiya mikromoliya oilaviy tibbiyot texnika pedagogika iqtisodiyot quyidagi tegishli "
            "ta’lim onlayn raqamli elektron sanoat o‘quv").split()


def _forms():
    """Every allowed word as typed, the roles with the endings a sentence gives them."""
    forms = list(ALLOWED) + list(RU_ROLES)
    forms += [role + ending for role in UZ_ROLES for ending in UZ_ENDINGS]
    forms += [role + ending for role in EN_ROLES for ending in ('', 's')]
    forms += [form + ending for form in UZ_ORG_FORMS for ending in UZ_ENDINGS]
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
# A weak stem that also names much else (an English "order", a Nizom, a convention): in the plural it is a citation
# only with a number or a date beside it ("nizomlar soddalashtirildi", "the regulations of the Ministry" cite none).
LOOSE = 'loose'
LAW = (
    ('constitution', r"konstitutsiya(?!viy)\w*|конституци(?:я|и|ю|ей|ях)|constitutions?", True),
    ('code', r"kodeks\w*|кодекс\w*", True),
    ('code', r"codes?", False),
    ('decree', r"farmon\w*|указ(?:а|е|ом|у|ы|ов|ами|ах)?|decrees?", True),
    ('order', r"farmoyish\w*|распоряжени\w*", True),
    ('order', r"buyru[qg]\w*|приказ\w*", False),
    # "order" in English, never "in order to".
    ('order', r"(?<!in )orders?(?![ \t]+to(?![^\W\d_]))", LOOSE),
    ('resolution', r"постановлени\w*", True),
    ('resolution', r"qaror\w*|resolutions?", False),
    ('law', r"qonun(?!iyat)\w*|закон(?!омерн)\w*|laws?|acts?", False),
    ('article', r"modda\w*|стать(?:я|и|е|ю|ей|ям|ях)|articles?", False),
    # «Положение о школе» and "Положение о налогах было принято ...": a regulation named by its title, wherever it
    # stands; never the "положение" (situation) of "экономическое положение республики", "Положение в экономике ..."
    # or "Положение дел ...", nor "положение о том, что ..." (a thesis).
    ('regulation', r"положени\w*(?=[ \t]+(?:о|об)[ \t]+(?!(?:том|тех)(?![^\W\d_])))", True),
    # Capitalised, «Положение» is a title only inside a sentence (`_concepts`).
    ('regulation', r"nizom\w*|regulations?|(?-i:Положени\w*)", LOOSE),
    # The Geneva Convention, a convention on or of something, never "the convention centre".
    ('convention', r"konvensiya\w*|конвенци\w*|(?-i:Conventions?)|conventions?(?=[ \t]+(?:on|of|for|against)(?![^\W\d_]))",
     LOOSE),
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
NUMBER_MARK = re.compile(
    r"\d+\s*-\s*(?:modda|band|qism)\w*"
    r"|(?<![^\W\d_])(?:стать|пункт|част)\w*\s*№?\s*\d"
    r"|(?<![^\W\d_])(?:articles?|sections?)\s+\d+[\w.()]*\s+of(?![^\W\d_])"
    r"|(?<![^\W\d_])(?:under|pursuant to|according to|in accordance with|per)\s+(?:articles?|sections?)\s+\d"
    r"|№\s*\d|(?<![^\W\d_])no\.?\s*\d"  # language.normalised writes № as "No"
    # An act's number as the adjective: "vazirligining 187-sonli buyrug‘i", "625-I-sonli qonun".
    r"|" + SON + r"li")
# A word that marks a weak stem as a citation anywhere in its sentence: "... to‘g‘risidagi qonun", "Prezident qarori".
WORD_MARK = re.compile(r"to'g'risida|togrisida|respublika|республик|federal|федеральн|mahkama|министр|prezident"
                       r"|президент|oliy majlis|parliament|парламент")
# Who issues an act, a mark only for a stem in the singular near it ("hukumat qarori", "vazirlikning buyrug‘i",
# "the Ministry of Public Education order"): "Hukumat qator qarorlar qabul qildi" and "the Ministry reports that
# orders grew" cite nothing.
ISSUER = re.compile(r"vazirli[gk]|hukumat|ministr(?:y|ies)|министерств")
ISSUER_REACH = 60
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


# The allowed words folded once, here, rather than for every draft. An Uzbek legal form heads a name with the endings a
# sentence gives it too ("Baraka MChJning ...", "Artel MChJga ...", "Kvarts AJga ..."): allowed as no one's name, it
# still says the word before it is an organisation's.
FORMULAS = _folded(_forms())
ORG_HEADS = _folded(ORG_FORMS + [form + ending for form in UZ_ORG_FORMS for ending in UZ_ENDINGS]
                    + [kind + ending for kind in ORG_KINDS for ending in UZ_ENDINGS]
                    + [kind + ending for kind in EN_ORG_KINDS for ending in ('', 's')])
ORG_AFTER = _folded([kind + own + case for kind in UZ_ORG_KINDS for own in ('i', 'si') for case in UZ_CASES]
                    + [place + case for place in UZ_PLACES_AFTER for case in UZ_CASES])
CHAIN = _folded(['tarmog‘i' + case for case in UZ_CASES])
# The people a clinic or a cooperative serves, whose plural before it is its kind, never its name: "Bolalar
# klinikasi", "Fermerlar shirkati" (`_organisation`). "Do‘stlar klinikasi", "Yoshlar banki" are still names.
PEOPLE_SERVED = _folded("bolalar fermerlar dehqonlar ayollar onalar keksalar nogironlar bemorlar hunarmandlar".split())
SERVING_KINDS = _folded([kind + own + case for kind in ('klinika', 'shirkat') for own in ('i', 'si')
                         for case in UZ_CASES])
KIND_WORDS = _folded(KINDS_OF)


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


# The case endings of a word held as invented (`Named`), folded: Uzbek ("Artelga", "Arteldagi", "Hamkorbankdan",
# "Artelning", with the possessive: "Barakasining"), Russian ("Артелю", "Артелем", "Каримову", "Каримовой") and the
# English "'s".
NAME_ENDINGS = frozenset((
    'ga', 'ka', 'da', 'dan', 'ning', 'ni', 'dagi', 'gacha', 'dek', 'niki', 'lar', 'larga', 'larda', 'lardan',
    'larning', 'larni', 'i', 'si', 'iga', 'siga', 'ida', 'sida', 'idan', 'sidan', 'ining', 'sining', 'ini', 'sini',
    'idagi', 'sidagi', 'a', 'u', 'e', 'om', 'em', 'oy', 'ey', 'im', 'ym', 's'))
# A Russian name in -a takes them in place of its -a: "Дилнозы", "Дилнозе", "Дилнозу", "Дилнозой".
A_ENDINGS = frozenset(('i', 'y', 'e', 'u', 'oy', 'oi', 'ou'))


class Named:
    """The folded words a paper's finish took out as no one's the customer gave (`held_names`, `_names`'s `blanked`).

    A word is one of them whole or with a case ending (`NAME_ENDINGS`), never by a common prefix as `Words` reads a
    customer's word: "Xalqaro" and "Moliyaviy" are no forms of an invented "Xalq" or "Moliya".
    """

    def __init__(self, words=()):
        self.exact = set()
        for word in words:
            self.add(word)

    def add(self, word):
        if word:
            self.exact.add(word)

    def has(self, word):
        if word in self.exact:
            return True
        for cut in range(3, len(word)):
            base, ending = word[:cut], word[cut:]
            if (base in self.exact and ending in NAME_ENDINGS) or (base + 'a' in self.exact and ending in A_ENDINGS):
                return True
        return False


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

    @property
    def legal(self):
        """`lower` with the customer's Uzbek Cyrillic also put in Latin: what a law's stem and name are looked up in.

        A customer who writes "Меҳнат кодексига мувофиқ" named the paper's "Mehnat kodeksi", which Uzbek is written
        in; their Russian stays as it is ("Трудовой кодекс" is matched by its own forms).
        """
        if 'legal' not in self.cache:
            latin = normalised(to_latin(self.said)).casefold() if UZBEK_CYRILLIC.search(self.said) else ''
            self.cache['legal'] = self.lower + ('\n' + latin if latin else '')
        return self.cache['legal']

    def person(self, word, translated=False):
        """Whether a capitalised word of a person's name is the customer's or one no one's facts are in."""
        if self.allowed.known(word) or self.words.known(word):
            return True
        return translated and any(self.respelled.has(form) for form in respellings(word))


def _link(text):
    return re.sub(r'^(?:https?://)?(?:www\.)?', '', text.lower()).rstrip('/.,;)')


def trusting(text, *, allowed=(), wording='', quotable=()):
    """A Trusted from plain text, `allowed` being more words no one's facts are in (labels, headings).

    `wording` is text whose quotations and legal sentences may be repeated but
    whose names and numbers are not the customer's: the earlier version of a
    document, model prose included. It reaches only the quotation and the
    legal-concept lookups. `quotable` are phrases the category itself puts in
    quotation marks for the model to write («Bugun nimani bildim?»): they
    reach the quotation lookup only.
    """
    text = str(text or '')
    folded = fold(text)
    words = Words(FOLDED_WORD.findall(folded))
    allow = Exact(FORMULAS | _folded(allowed))
    wording = str(wording or '')
    quoted = flat(text, folded=folded) + (flat(wording) if wording.strip() else '')
    quoted += ''.join(flat(phrase) for phrase in quotable)
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


def _held(content, entry, translated=False):
    """The words of an earlier version that were held to the customer's words when it was made.

    That is the `facts` section, the grounded parts, the customer's and the
    template's slots and the verified sources. Guarded prose and deck draft
    slots are the model's, where general knowledge is allowed: a year or a name
    written there must never become the customer's on the next change. A deck's
    sections are `s1..sN` and its slot mapping may no longer hold after the
    customer edited slides, so they resolve to no part and give nothing here.

    Only what a check read is held, so nothing it let through by design comes
    back as the customer's on the next change: a person's, organisation's,
    place's, line's or list's fact whole; a figure's (date, number, money,
    ref, phone) and a fact-led paper's text without the opening word its names
    check left free; a guarded paper's text, a fact of no field and a sources
    item verified in translation by their numbers and addresses only; and a
    grounded part without each sentence's, cell's or item's free first word
    (`_checked_only`). An invented "Hamkorbank krediti" cell or a translated
    reference's publisher never makes the next version's loan_bank or
    university the customer's.
    """
    if entry is None or not isinstance(content, dict):
        return []
    led = any(part.get('grounded') for part in entry.parts)
    held = []
    for section in content.get('sections') or []:
        if not isinstance(section, dict):
            continue
        if section.get('id') == 'facts':
            for item in section.get('items') or []:
                if not isinstance(item, dict):
                    continue
                field = entry.field(str(item.get('label') or '').strip())
                kind = field['kind'] if field is not None else None
                for text in (item.get('text'), item.get('value')):
                    if not isinstance(text, str) or not text.strip():
                        continue
                    if kind in ('person', 'org', 'place', 'line', 'list', 'email', 'choice', 'flag', 'file') \
                            or (field is not None and (field.get('derived_from') or field.get('clock'))):
                        held.append(text)
                    elif kind in NAMED_NUMBERS or (kind == 'text' and led):
                        held.append(_checked_only(text))
                    else:
                        held.append(_figures_only(text))
            continue
        part = entry.part(section.get('id'))
        if not part:
            continue
        if part.get('kind') == 'sources':
            texts = [text for _, text in _fields({'sections': [section]}) if text]
            held += [_figures_only(text) for text in texts] if translated else texts
        elif part.get('grounded') or part.get('source') in ('customer', 'template'):
            held += [_checked_only(text) for _, text in _fields({'sections': [section]}) if text]
    return [text for text in held if text.strip()]


def _checked_only(text):
    """`text` without the words no names check read: each sentence's, cell's or item's free first word (`_names`)."""
    spans = []
    for run in _runs(text):
        start, end, word = run[0]
        if not _starts(text, start) or _after_colon(text, start) or _surname(word) or _organisation(text, run) \
                or (len(run) > 1 and all(_letters(other) < 2 for _, _, other in run[1:])):
            continue
        spans.append((start, end))
    for start, end in reversed(spans):
        text = text[:start] + ' ' + text[end:]
    return text


def _figures_only(text):
    """Only the numbers and the addresses of `text`, as a check that read nothing else held it."""
    kept = [text[number.start:number.end] for number in numbers.found(text, words=True)]
    kept += [match.group(0) for pattern in (EMAIL, HANDLE, LINK) for match in pattern.finditer(text)]
    return ' ; '.join(kept)


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


def _translated(data, entry):
    """Whether a paper is written in another language than its message (finish._translated, read the same way)."""
    if entry is None:
        return False
    from ..language import written_in
    revision = data.get('revision') or {}
    said = written_in(revision.get('original_prompt') or data.get('prompt') or '')
    locale = data.get('output_locale') if data.get('output_locale') in ('uz', 'ru', 'en') else 'en'
    return bool(said) and said != locale


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
    translated = _translated(data, entry)
    for content in earlier:
        parts += _held(content, entry, translated)
    wording = '\n'.join(text for content in earlier for text in _texts(content) if text)
    return trusting('\n'.join(str(part) for part in parts if part), allowed=_catalogue_words(entry), wording=wording,
                    quotable=_catalogue_quotes(entry))


def _catalogue_quotes(entry):
    """The phrases a category's own instructions put in « » for the model to write («Bugun nimani bildim?»,
    «Darslikdagi shu mavzuga oid mashqlar bajariladi»): no one's quotation, so never blanked as one."""
    if entry is None:
        return []
    texts = [rule.get('text') for rule in entry.raw.get('rules') or [] if isinstance(rule, dict)]
    texts += [part.get('write') for part in entry.parts]
    return [inner for text in texts if isinstance(text, str) for inner in re.findall(r'«([^«»]{1,200})»', text)]


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


# A class's letter after its number: "7-«B» sinf", "7-B", "7B-sinf", "7 «Б» класс", "Grade 7B", "Year 7B", "Sinf:
# 7B", "7B o‘quvchisi", or a grade written "7B" and nothing else. A single capital is no name the names check reads, so
# an invented parallel ("7-«B» sinf" for the customer's "7-sinf") is held here; never an initial ("7 A. Karimova") or
# a word ("7 Apples"). Only a letter a class is written with is one (`_class_letter`, `_class_letters`); "1C
# dasturchisi", "3D dizayner" and "12A uy" name no class. The customer's letter is matched as Uzbek writes a Cyrillic
# one in Latin (В as V, С as S), never by its look inside a class: their "7 «В»" is the paper's "7-«V»", and a paper's
# "7-«B»" is another class; only their own token ("1С dasturi") is matched by its look (`LOOKALIKES`).
CLASS_LETTER = re.compile(r"""(?<!\d)(\d{1,2})([ \u00a0]?-?[ \u00a0]?[«"“'‘]?)([A-ZА-ЯЁ])([»"”'’]?)(?![^\W\d_]|\.)""")
# The same in the customer's words, where a full stop may end it ("... программист 1С.").
CLASS_TOKEN = re.compile(r"""(?<!\d)(\d{1,2})([ \u00a0]?-?[ \u00a0]?[«"“'‘]?)([A-ZА-ЯЁ])([»"”'’]?)(?![^\W\d_])""")
CLASS_WORD = re.compile(r"sinf\w*|класс\w*|class(?:es)?|grades?|years?", re.IGNORECASE)
# A pupil's word, beside which a number and a letter are a class: "7B o‘quvchisi", "an 11A student", "ученик 9Б".
PUPIL_WORD = re.compile(r"o['‘’ʻʼ`]?quvchi\w*|ученик\w*|ученица\w*|учащ\w*|школьни\w*|students?|pupils?"
                        r"|schoolchild\w*", re.IGNORECASE)
# A class's label, whose value a number and a letter are a class as: "Sinf: 7B", "Class: 7B", "Класс: 7Б".
CLASS_LABEL = re.compile(r"(?<![^\W\d_])(?:sinf\w*|класс\w*|class|grade|year)[  ]*:[  ]*$", re.IGNORECASE)
# A number the customer wrote as their class: "7-sinf", "7 «В» класса", "в 7-м классе", "grade 11", "Year 7".
CLASS_NUMBER = re.compile(
    r"(?<!\d)(\d{1,2})[  ]*-?[  ]*(?:[«\"“'‘]?[^\W\d_]{1,2}[»\"”'’]?[  ]*-?[  ]*)?"
    r"(?:sinf|класс|class|grade)"
    r"|(?<![^\W\d_])(?:sinf\w*|класс\w*|class|grade|year)[  ]*№?[  ]*(\d{1,2})(?!\d)", re.IGNORECASE)
# The Cyrillic capitals a Latin one looks like: the customer's "1С" is the paper's "1C" where no class is written.
LOOKALIKES = str.maketrans('АВСЕКМНОРТХ', 'ABCEKMHOPTX')
# The fields that hold a grade or a class: there a number and a letter anywhere ("7B", "Sinf: 7B", "7B, matematika")
# are a class.
GRADE_FIELDS = frozenset(('grade', 'class_level', 'level', 'grade_line'))


def _class_letter(text, match, grade=False):
    """Whether a CLASS_LETTER match is a class's letter by what is written beside it: quoted, after a hyphen, beside a
    class word (one after a hyphen too: "7B-sinf") or a pupil's (`PUPIL_WORD`: "7B o‘quvchisi", "an 11A student"),
    as a class label's value (`CLASS_LABEL`: "Sinf: 7B"), or anywhere in a grade's or a class's field (`grade`).
    Anywhere else a number and a letter name no class by themselves: "1C dasturchisi", "3D dizayner", "12A uy"."""
    if grade or match.group(4) or '-' in match.group(2) or re.search(r"[«\"“'‘]", match.group(2)):
        return True
    if CLASS_LABEL.search(text[:match.start()]):
        return True
    after = re.match(rf"[  ]*-?[  ]*({WORD.pattern})", text[match.end():])
    before = re.search(rf"({WORD.pattern})[  ]*$", text[:match.start()])
    return any(word is not None and (CLASS_WORD.fullmatch(word.group(1)) or PUPIL_WORD.fullmatch(word.group(1)))
               for word in (after, before))


def _class_numbers(trusted):
    """The numbers the customer wrote as their class (`CLASS_NUMBER`), read once per Trusted."""
    if 'classes' not in trusted.cache:
        trusted.cache['classes'] = frozenset(
            match.group(1) or match.group(2) for match in CLASS_NUMBER.finditer(normalised(trusted.said)))
    return trusted.cache['classes']


def _token(trusted, number, letter):
    """Whether the customer wrote `number` and `letter` as a token of their own, no class ("1С dasturi", "программист
    1С"): their letter matched as the Latin one it looks like (`LOOKALIKES`), never one beside a class's words."""
    said = normalised(trusted.said)
    return any(match.group(1) == number and match.group(3).translate(LOOKALIKES) == letter
               and not _class_letter(said, match) for match in CLASS_TOKEN.finditer(said))


def _class_letters(text, trusted, grade=False, weak=False):
    """The class letters of `text` the customer never wrote after the same number, as match objects.

    `weak` (a title-page line, a line or a list fact) also reads as a class a number and a letter that are the whole
    value ("7B" on a cover, "Sinf: 7B" once its label is split off) or whose number the customer wrote as their class
    ("7B matematika" for their "7-sinf"), unless the customer wrote them as a token of their own (`_token`)."""
    said = fold(trusted.said)
    found = []
    for match in CLASS_LETTER.finditer(text):
        strong = _class_letter(text, match, grade)
        whole = not text[:match.start()].strip() and not text[match.end():].strip()
        if not strong and not (weak and (whole or match.group(1) in _class_numbers(trusted))):
            continue
        number, letter = match.group(1), fold(match.group(3))
        if re.search(rf"(?<!\d){number}\W{{0,4}}{re.escape(letter)}(?![^\W\d_])", said):
            continue
        if not strong and _token(trusted, number, match.group(3)):
            continue
        found.append(match)
    return found


def without_class_letters(text, trusted, *, grade=False, weak=False):
    """(`text` without the class letters the customer never wrote, whether any was taken): "7-«B» sinf" is "7-sinf".

    `grade` is for a grade's or a class's field (`GRADE_FIELDS`), where a number and a letter anywhere are a class;
    `weak` for a line or a list fact (`_class_letters`)."""
    found = _class_letters(text, trusted, grade, weak)
    for match in reversed(found):
        joint = '-' if '-' in match.group(2) else ''
        rest = text[match.end():]
        text = text[:match.start(2)] + joint + (rest.lstrip(' \u00a0') if joint else rest)
    return text, bool(found)


def _names_known(text, trusted, translated=False):
    """Whether every capitalised word of two letters or more is the customer's or one no one's facts are in."""
    for match in WORD.finditer(text):
        word = match.group(0)
        if not word[0].isupper() or len(re.sub(r"['‘’ʻʼ`´]", '', word)) < 2:
            continue
        if not trusted.person(word, translated):
            return False
    return True


# The kinds whose values are figures first: read for their numbers, and in a paper's facts for the names beside them.
NAMED_NUMBERS = ('date', 'number', 'money', 'ref', 'phone')
# The words a figure's own labels capitalise beside it in any of the three languages, no one's name: a seller's bank
# details ("Kapitalbank JSCB, MFO 00440", "Bank code (MFO)", "Банк: АКБ «Капиталбанк»", "Settlement account") and a
# phone's ("Mobile", "Telegram", "WhatsApp"). Read only in those kinds (`supported`'s `strict`), never in prose.
REQUISITES = (
    "account accounts settlement current correspondent corr bank banks code details branch office jscb ojsc cjsc pjsc "
    "ojscb cb mobile cell phone telephone tel fax telegram whatsapp viber "
    "банк банка банке банком банку расчетный расчетного счет счета корр корреспондентский корсчет филиал филиала "
    "отделение отделения реквизиты мобильный моб телефон тел факс телеграм ватсап "
    "bank banki bankida bankining hisob hisobi hisobraqam hisobraqami raqam raqami kitob mobil telefon tel faks filial "
    "filiali bo‘lim bo‘limi rekvizitlar").split()


def supported(value, kind, trusted, *, translated=False, strict=False, words=False, classed=None):
    """Whether a fact of this kind is the customer's (architecture 4, "Verifying").

    person, org, place, line: every capitalised word is theirs and every number
    is one they gave; date, number, money, ref, phone, text: every number;
    email: found whole; list: each line as a line; choice, flag, file: not
    checked here. `translated` (the document is in another language than the
    message) checks names for a person only: organisations and places are
    translated, a person's name only spelled anew, which the fold meets, with
    the Russian spellings of o and o‘ allowed (`respellings`).

    `strict` is for a paper's facts, where translation never switches the
    names off, and a date, number, sum, reference or phone has the names
    beside its figures read too (`NAMED_NUMBERS`): a paper draws its org, place, line and list values in a
    letterhead, a title page, the minutes' head and its signature rows, and
    those hold people ("Rais: …", "Director | …", a list of participants) as
    often as a person field does. With `translated` they are then read as a
    person's are, in the looser spellings, so a translated organisation whose
    words do not fold to the customer's is not kept: a false blank, never an
    invention, and never one that a later change would read back as theirs.

    `words` also reads the numbers written as words (numbers.SPELLED): a
    paper's "five years", "besh yuz million so‘m" or "двенадцать человек" must
    be a value the customer gave, as its digits must.

    A class letter the customer never wrote is refused (`_class_letters`); a
    line's (or, with `classed`, any kind's: a title-page line held as a
    person's) whole value "7B" and a number the customer wrote as their class
    ("7B matematika" for their "7-sinf") are read as a class too.
    """
    if kind in ('choice', 'flag', 'file') or value is None or isinstance(value, bool):
        return True
    text = str(value).strip()
    if not text or not re.sub(r'[_\s.\-]', '', text):
        return True  # nothing, or the blank the model returns for an if_needed field
    if kind == 'list':
        return all(supported(line, 'line', trusted, translated=translated, strict=strict, words=words,
                             classed=classed) for line in re.split(r'[\n;]+', text) if line.strip())
    rest, whole = _strip_addresses(text, trusted)
    if not whole:
        return False
    read = numbers.found(rest, words=words, uzbek_cyrillic=False)
    if not all(numbers.known(number, trusted.values) for number in read):
        return False
    if kind in ('person', 'org', 'place', 'line') and _class_letters(
            rest, trusted, weak=kind == 'line' if classed is None else classed):
        return False
    if kind in ('person', 'org', 'place', 'line') and (strict or not translated or kind == 'person'):
        return _names_known(rest, trusted, translated)
    if strict and kind in NAMED_NUMBERS:
        # A paper's sum, reference, phone or date may carry a name beside its figures: the bank of "h/r …,
        # «Kapitalbank» ATB, MFO 00440", the lender of "200 mln so‘m (Hamkorbank krediti)", the person of "+998 90 123
        # 45 67 (Aziz Karimov)". Its names are read as a title-page line's are (people_known), so the value's own
        # opening word ("Mobile:", "Average check", "Договор №") stays a label, and so do the words such labels
        # capitalise beside the figures (REQUISITES: "Kapitalbank JSCB", "Банк: …", "(mobile, Telegram)").
        return people_known(rest, _labelled(trusted), translated=translated, orgs=True)
    return True


def _labelled(trusted):
    """`trusted` with the words a figure's labels capitalise (REQUISITES) allowed too, made once per Trusted."""
    if 'labelled' not in trusted.cache:
        trusted.cache['labelled'] = replace(trusted, allowed=Exact(trusted.allowed.exact | _folded(REQUISITES)),
                                            cache={})
    return trusted.cache['labelled']


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
    """The legal things `sentence` cites, or an empty set when it cites none (a weak stem with no mark beside it).

    A weak stem cites with a strong one, a number or a date beside it (NUMBER_MARK, `DATED`) or a word mark
    anywhere (WORD_MARK), a LOOSE one in the plural only with the first two; with an issuer (ISSUER) only in the
    singular and near it.
    """
    text = normalised(sentence)
    found, weak, dated = set(), [], False
    for concept, stem, strong in STEMS:
        for match in stem.finditer(text):
            if strong == LOOSE and match.group(0).startswith('Положени') and _starts(text, match.start()):
                continue  # "Положение в экономике ...": a situation; «Положение о …» is read by its title above
            # A weak stem capitalised inside a sentence is a title ("Mehnat Kodeksi", "Labour Code", "Закон о …").
            if strong is True or (match.group(0)[0].isupper() and not _starts(text, match.start())):
                found.add(concept)
            else:
                weak.append((concept, match, strong))
                reach = text[max(0, match.start() - DATED_REACH):match.end() + DATED_REACH]
                dated = dated or DATED.search(reach) is not None
    lower = text.casefold()
    if NUMBERED.search(lower):
        found.add('number')
    if not weak:
        return found
    marked = bool(found) or dated or NUMBER_MARK.search(lower) is not None
    worded = WORD_MARK.search(lower) is not None
    issuers = [match.span() for match in ISSUER.finditer(lower)]
    for concept, match, strength in weak:
        plural = _plural(match.group(0))
        if marked or (worded and not (strength == LOOSE and plural)) or (not plural and any(
                start - ISSUER_REACH <= match.end() and match.start() <= end + ISSUER_REACH for start, end in issuers)):
            found.add(concept)
    return found


def _plural(word):
    """Whether a legal stem is in the plural: "qarorlar", "qonunlariga", "orders", "regulations", "приказы"."""
    low = word.casefold()
    if 'lar' in low:
        return True
    if low.isascii():
        return low.endswith('s')
    return re.fullmatch(r"(?:приказ|закон)\w*?(?:ы|ов|ам|ами|ах)", low) is not None


# The codes and laws a sentence names by a word before its stem ("Soliq kodeksi", "Трудовой кодекс", "Labour Code"),
# by what they are, in the three languages: in a paper in another language than the message, the customer's "Трудовой
# кодекс" is the paper's "Mehnat kodeksi", and only that.
LAW_NAMES = (
    r"mehnat|трудов|labou?r", r"soliq|налог|tax", r"jinoyat|уголовн|criminal", r"fuqarolik|гражданск|civil",
    r"ma'muriy|административн|administrative", r"oila|семейн|family", r"bojxona|таможен|customs",
    r"yer|земельн|land", r"uy-joy|жилищн|housing", r"bu?d?jet|бюджетн|budget", r"saylov|избирательн|elector",
    r"suv|водн|water", r"o'rmon|лесн|forest", r"shaharsozlik|градостроительн|urban", r"ta'lim|образован|education",
    # What a law is on, as a model renders it after its "on" ("the Law on accounting", "the Law on the protection of
    # consumer rights"): read in any language as the codes' names are.
    r"buxgalteriya|бухгалтерск|accounting", r"iste'molchi|потребител|consumers?", r"raqobat|конкуренц|competition",
    r"reklama|реклам|advertising", r"litsenziya|лицензир|licen[cs]ing", r"sug'urta|страхован|insurance",
    # The words of the commonest such law, "the Law on the protection of consumer rights" («О защите прав
    # потребителей», "Iste’molchilarning huquqlarini himoya qilish to‘g‘risida"): read as names, so the customer's own
    # law translated keeps its words and an invented one must still be theirs word for word.
    r"himoya\w*|защит\w*|protection", r"huquq\w*|прав[оа]?(?![а-яё])|rights?",
)
# A Latin form is a whole word, with an ending a sentence may give it ("Labour", "Mehnat", "taxes", never
# "laboratory", "taxi" or "suvenir"); a Russian one is a stem its adjective declines from ("трудового", "налоговому").
LAW_NAME_ENDINGS = r"(?:lar)?(?:ning|ni|ga|da|dan|iy|es|s)?"


def _law_name_form(forms):
    latin = '|'.join(form for form in forms.split('|') if not re.search('[а-я]', form))
    cyrillic = '|'.join(form for form in forms.split('|') if re.search('[а-я]', form))
    return re.compile(rf"(?<![^\W\d_])(?:(?:{latin}){LAW_NAME_ENDINGS}(?![^\W\d_])|(?:{cyrillic}))", re.IGNORECASE)


LAW_NAME_FORMS = [_law_name_form(forms) for forms in LAW_NAMES]


# The stems a code or a law is named before: "Soliq kodeksi", "Labour Code", "Education Act". A constitution, a
# decree or an article is not ("День Конституции" is a day, not a constitution's name).
NAMED_STEMS = [stem for concept, stem, _ in STEMS if concept in ('code', 'law')]


# What joins a law's name to its stem without naming anything: "Ma’muriy javobgarlik to‘g‘risidagi kodeks", "Sport
# haqidagi qonun". The name is what stands before it, up to `LAW_ABOUT_REACH` words.
LAW_ABOUT = re.compile(r"to'g'risida(?:gi)?|tog'risida(?:gi)?|haqida(?:gi)?")
LAW_ABOUT_REACH = 4
# A code's kind of procedure, part of its name: "Fuqarolik protsessual kodeksi", "Jinoyat-protsessual kodeksi",
# "Уголовно-процессуальный кодекс", "Criminal Procedure Code".
LAW_KIND = re.compile(r"protsessual\w*|процессуальн\w*|procedur\w*|ijro\w*|исполнительн\w*")
# What may stand between a code and the preposition its name follows ("Кодекс Республики Узбекистан об
# административной ответственности", "Code of the Republic of ..."): the country, no one's law.
LAW_COUNTRY = re.compile(r"the|o'zbekiston\w*|respublika\w*|uzbekistan|republic|республик\w*|узбекистан\w*|руз|ruz")
# The preposition a law's name follows in Russian and English: "Кодекс об административных правонарушениях",
# "Code of Administrative Offences", "Law on Education". The name after it is its words in the case "о" and "об" give
# them in Russian; in English its capitalised words, and the words of LAW_NAMES and kinds of procedure a model writes
# in lower case ("the Code of administrative offences", "the Law on taxes and fees", "the Code of criminal
# procedure"), read through the words between them, at most `LAW_OF_REACH`, the country passed over. It ends at a
# conjunction ("... of the Republic of Uzbekistan and tax rules", "... ответственности и налоговым правилам") or at a
# word that goes on the sentence (`LAW_OF_STOP`: "... of Uzbekistan applies to land workers", "... on education when
# training interns").
LAW_OF = re.compile(r"of|on|об|о")
LAW_OF_REACH = 6
# A law or a code with no name before its stem ("the Law of the Republic of Uzbekistan on state duty", "the Law on
# personal data", "the Code of professional ethics") is named by every word after its "of" or "on" up to a word that
# goes on the sentence, a conjunction or a mark, at most this many, its own grammar words (`LAW_OF_GRAMMAR`) passed.
LAW_OF_UNNAMED_REACH = 8
LAW_OF_GRAMMAR = re.compile(r"of|the|a|an")
LAW_OF_STOP = re.compile(
    r"is|are|was|were|be|been|being|has|have|had|do|does|did|will|shall|would|should|must|may|might|can|could"
    # A verb's forms only, never the noun of the same stem a law is named by ("on state duty", "on accounting
    # requirements", "on the regulation of ...").
    r"|appl(?:y|ies|ied|ying)|govern(?:s|ed|ing)?|regulat(?:e|es|ed|ing)|requir(?:e|es|ed|ing)|set|sets"
    r"|cover(?:s|ed|ing)?|say|says|said|state[sd]|provid(?:e|es|ed|ing)"
    r"|allow(?:s|ed|ing)?|forbid\w*|oblig(?:e|es|ed|ing)|mean(?:s|t)?|follow(?:s|ed|ing)?|keep\w*|kept|make\w*"
    r"|made|take\w*|took|give\w*|gave"
    r"|when|where|while|which|who|whom|whose|that|this|these|those|if|unless|because|since|as|than|so|too|also"
    r"|to|in|into|for|with|without|by|at|from|under|over|after|before|during|through|within|about|against|between"
    r"|its|their|his|her|our|your|it|they|he|she|we|you|i|all|each|every|any|some|no|not|only|even")
LAW_AND = re.compile(r"and|or|but|и|или|а|но|va|yoki|hamda|ham")
LAW_OF_CASE = re.compile(r"[а-яё]+(?:е|и|ах|ях|ой|ей|ом|ем|ых|их|ий|ия)")
LAW_TOKEN = re.compile(WORD.pattern + r"|[,;:()«»\"“”„!?]")
# A word that points at a code already named, no one's name for it: "Ushbu kodeks", "Mazkur kodeksga", "Настоящий
# кодекс", "This Code".
# "Tegishli kodeks", "barcha", "boshqa", "har qanday", "yangi" point at a code without naming one either.
LAW_THIS = re.compile(r"ushbu|mazkur|bu|shu|amaldagi|yuqoridagi|tegishli|barcha|boshqa|har|qanday|yangi|joriy"
                      r"|настоящ\w*|данн\w*|указанн\w*|эт(?:от|ого|ому|им|ом)"
                      r"|действующ\w*|соответствующ\w*|нов(?:ый|ого|ому|ым|ом|ая|ой|ую)|this|that|said|present|current")
# A Russian code is named by its adjectives, in lower case, before its stem: "по арбитражному процессуальному
# кодексу", "Трудовой кодекс".
LAW_ADJECTIVE = re.compile(r"[а-яё]+(?:ый|ий|ой|ая|яя|ое|ее|ого|его|ому|ему|ым|им|ом|ем|ую|юю|ых|их|ыми|ими)")
# An Uzbek code is named by its first word, capitalised, and the words after it in lower case and no case of their
# own ("Raqamli iqtisodiyot kodeksi", "Mehnat kodeksi"); "Barcha xodimlar kodeks talablariga ..." names none.
UZ_LAW_STEM = re.compile(r"kodeks\w*|qonun\w*")
# The dative's -ka and -qa only follow a k and a q ("bankka", "qishloqqa"): "etika", "texnika" are no case.
UZ_INFLECTED = re.compile(r"[^\W\d_]*(?:lar\w*|ning|ni|ga|kka|qqa|da|dan|dagi|gacha|ini|ida|idan|iga)")
LAW_HEAD_REACH = 2
# A sentence's capitalised first word that is its subject or its grammar, no code's first word: a person, a job, a
# workplace or a pronoun ("Xodim", "Buxgalter", "Korxona", "U", "Employees", "Under"), in any case.
LAW_SUBJECT_NOUNS = ("xodim ishchi korxona tashkilot muassasa kompaniya jamiyat firma maktab bo‘lim rahbariyat "
                     "ish beruvchi u ular biz men siz bu shu har barcha hamma ushbu mazkur "
                     # The words a sentence opens with before what it says ("Hozirda mehnat kodeksiga ko‘ra ...").
                     "hozirda hozir bugun bugungi shuningdek masalan ayniqsa odatda amalda asosan ya’ni chunki lekin "
                     "ammo biroq demak avvalo birinchidan ikkinchidan keyin so‘ng bunda shunda unda").split()
LAW_SUBJECT_WORDS = ("the a an under according per in by every each all our his her their its this that employee "
                     "employees staff worker workers company organisation organization school").split()
LAW_SUBJECTS = _folded([noun + ending for noun in LAW_SUBJECT_NOUNS for ending in UZ_ENDINGS] + LAW_SUBJECT_WORDS)


def _law_names(sentence):
    """The words naming a code or a law (start, word), in any case: what stands right before its stem, or after it.

    Before it: the capitalised words, the words of LAW_NAMES and a kind of procedure side by side with it ("Soliq
    kodeksi", "Jinoyat-protsessual kodeksiga", "Трудовой кодекс", "Labour Code"), or every word up to
    `LAW_ABOUT_REACH` before a "to‘g‘risidagi" ("Ma’muriy javobgarlik to‘g‘risidagi kodeksga"). After it: the
    words after its "of", "on", "об" or "о", the country passed over ("Кодекс Республики Узбекистан об
    административной ответственности", "Code of Administrative Offences"). They are held wherever they stand, a
    sentence's or a list item's first word included: there the start of a sentence was taken for grammar, and an
    invented "Jinoyat kodeksiga muvofiq javobgar bo‘ladi" or "Ma’muriy javobgarlik to‘g‘risidagi kodeksga
    muvofiq ..." passed once the customer had named any code. A sentence's first word before another of the name
    is grammar ("The Criminal Code", "Согласно Трудовому кодексу", "Korxona Mehnat kodeksiga ..."), unless it is
    one of LAW_NAMES, and a word pointing at the code already named ("Ushbu kodeks", "Настоящий кодекс",
    `LAW_THIS`) ends its name.
    """
    tokens = [(match.start(), match.group(0)) for match in LAW_TOKEN.finditer(sentence)]

    def word(index):
        return 0 <= index < len(tokens) and WORD.fullmatch(tokens[index][1]) is not None \
            and not any(stem.fullmatch(tokens[index][1]) for stem in NAMED_STEMS)
    found = []
    for at, (_, token) in enumerate(tokens):
        if not any(stem.fullmatch(token) for stem in NAMED_STEMS):
            continue
        name, index, about = [], at - 1, None
        headed = _law_head(sentence, tokens, at, word) if UZ_LAW_STEM.fullmatch(normalised(token).casefold()) else []
        while word(index) and not headed:
            low = normalised(tokens[index][1]).casefold()
            if LAW_THIS.fullmatch(low):
                break
            if about is not None:
                if about == LAW_ABOUT_REACH:
                    break
                about += 1
                name.append(tokens[index])
            elif LAW_ABOUT.fullmatch(low) and not name:
                about = 0
            elif _law_name(tokens[index][1]) or LAW_KIND.fullmatch(low) or tokens[index][1][0].isupper() \
                    or LAW_ADJECTIVE.fullmatch(low):
                name.append(tokens[index])
            else:
                break
            index -= 1
        name.reverse()
        if headed:
            name = headed
        elif len(name) > 1 and _starts(sentence, name[0][0]) and not _law_name(name[0][1]) \
                and (name[1][1][0].isupper() or _law_subject(name[0][1])):
            name = name[1:]
        index = at + 1
        while word(index) and LAW_COUNTRY.fullmatch(normalised(tokens[index][1]).casefold()):
            index += 1
        if index < len(tokens) and tokens[index][1] in '«"“„' and word(index + 1) \
                and LAW_OF.fullmatch(normalised(tokens[index + 1][1]).casefold()):
            index += 1  # a title in its marks: the Law "On Education", Закон «Об образовании»
        if word(index) and LAW_OF.fullmatch(normalised(tokens[index][1]).casefold()):
            index, taken = index + 1, 0
            # No name before the stem ("the Law of the Republic of Uzbekistan on state duty"): every word after its
            # "of" or "on" is its name, so an invented subject in lower case is the customer's or the sentence goes.
            unnamed = not any(_letters(text) >= 2 and not LAW_COUNTRY.fullmatch(normalised(text).casefold())
                              for _, text in name)
            while word(index) and taken < (LAW_OF_UNNAMED_REACH if unnamed else LAW_OF_REACH):
                token = tokens[index][1]
                low = normalised(token).casefold()
                if not taken and (LAW_COUNTRY.fullmatch(low) or LAW_OF.fullmatch(low)):
                    index += 1
                    continue
                if LAW_AND.fullmatch(low):
                    break
                if re.search('[а-яё]', low):
                    if LAW_OF_CASE.fullmatch(low) is None:
                        break
                    name.append(tokens[index])
                elif token[0].isupper() or _law_name(token) or LAW_KIND.fullmatch(low):
                    name.append(tokens[index])
                elif LAW_OF_STOP.fullmatch(low):
                    break  # a word that goes on the sentence ends the name
                elif unnamed:
                    if not LAW_OF_GRAMMAR.fullmatch(low):
                        name.append(tokens[index])
                elif not taken and not (word(index + 1) and normalised(tokens[index + 1][1]).casefold() == 'of'):
                    # After a named stem, a first word that is no name word begins one only before its own "of"
                    # ("the Labour Code on working hours" names the Labour Code; never "... of Uzbekistan applies
                    # to land workers" or "... protects consumer interests").
                    break
                index, taken = index + 1, taken + 1
        found += [(start, text) for start, text in name if _letters(text) >= 2
                  and not LAW_COUNTRY.fullmatch(normalised(text).casefold())]
    return list(dict.fromkeys(found))


def _law_head(sentence, tokens, at, word):
    """An Uzbek code's name with its lower-case words before its stem at `at`, from its capitalised first word:
    "Raqamli iqtisodiyot kodeksiga" gives Raqamli and iqtisodiyot; [] when the word before the stem is no such word.

    A sentence's capitalised subject is no code's first word unless it is one of LAW_NAMES: of "Xodim odob-axloq
    kodeksiga ..." only odob and axloq are the code's name, and "Xodim tegishli kodeks talablarini biladi" names none
    (`LAW_THIS`)."""
    lower, index = [], at - 1
    while word(index) and len(lower) < LAW_HEAD_REACH:
        text = tokens[index][1]
        low = normalised(text).casefold()
        if text[0].isupper():
            break
        if _law_name(text) or LAW_KIND.fullmatch(low) or LAW_THIS.fullmatch(low) or LAW_ABOUT.fullmatch(low) \
                or UZ_INFLECTED.fullmatch(low) or re.search('[а-яё]', low):
            return []
        lower.append(tokens[index])
        index -= 1
    if not lower or not word(index) or not tokens[index][1][0].isupper() \
            or LAW_THIS.fullmatch(normalised(tokens[index][1]).casefold()):
        return []
    if _starts(sentence, tokens[index][0]) and not _law_name(tokens[index][1]) and _law_subject(tokens[index][1]):
        return list(reversed(lower))
    return [tokens[index], *reversed(lower)]


def _law_subject(word):
    """Whether a capitalised word opening a sentence before a code's name is the sentence's subject or grammar, no word
    of the name: a person's, a job's or a workplace's noun or a pronoun (`LAW_SUBJECT_NOUNS`, `_role_word`: "Xodim",
    "Buxgalter", "Korxona"), an English determiner or preposition, or a Russian word that is no adjective ("Согласно",
    "Работник"; "Арбитражный процессуальный кодекс" is a code's whole name, as "Korporativ boshqaruv kodeksi" is)."""
    low = normalised(word).casefold()
    if re.search('[а-яё]', low):
        return LAW_ADJECTIVE.fullmatch(low) is None
    return fold(word) in LAW_SUBJECTS or _role_word(word)


def _law_name(word):
    """The forms (LAW_NAME_FORMS) of the code or law a word names, or None."""
    folded = normalised(word).casefold()
    return next((forms for forms in LAW_NAME_FORMS if forms.match(folded)), None)


def _law_name_known(word, trusted):
    """Whether a word naming a code in a translated paper is the customer's: the same code named in any language."""
    forms = _law_name(word)
    if forms is not None:
        return forms.search(trusted.legal) is not None
    return trusted.allowed.known(word) or trusted.person(word, True)


def _legal_known(sentence, concepts, trusted, translated, *, names=True):
    """Whether a legal sentence cites only what the customer gave: its kinds of act, numbers and the code's name;
    with `names`, every other capitalised word of it too (a person, a ministry, a date's issuer)."""
    for concept in concepts - {'number'}:
        if not any(stem.search(trusted.legal) for name, stem, _ in STEMS if name == concept):
            return False
    if not all(numbers.known(number, trusted.values) for number in numbers.found(sentence)):
        return False
    words = _law_names(sentence)
    # Which code or law it is ("Jinoyat", "административных", "Labour"), in any case and any language, is the
    # customer's: the same code named in their words.
    if not all(_law_name(word).search(trusted.legal) for _, word in words if _law_name(word) is not None):
        return False
    # Its other words in lower case ("арбитражному", "iqtisodiyot", "javobgarlik") are the customer's too: as they
    # wrote them, or in a translated paper in the spellings a translation gives a name. A translated code's words
    # not of LAW_NAMES cannot be told from an invented one's, so they go: a false removal, never an invention.
    plain = [word for _, word in words if not word[0].isupper() and _law_name(word) is None
             and not LAW_KIND.fullmatch(normalised(word).casefold())]
    if not all(trusted.person(word, True) if translated else trusted.words.known(word) for word in plain):
        return False
    named = [(start, word) for start, word in words if word[0].isupper()]
    if translated:
        # A translated sentence's other words are the translation's; the code it names is still the customer's.
        return all(_law_name_known(word, trusted) for _, word in named)
    if not names:
        return all(trusted.allowed.known(word) or trusted.words.known(word) for _, word in named)
    held = {start for start, _ in named}
    for match in WORD.finditer(sentence):
        word = match.group(0)
        if (word[0].isupper() and len(word) >= 2 and (match.start() in held or not _starts(sentence, match.start()))
                and not trusted.allowed.known(word) and not trusted.words.known(word)):
            return False
    return True


def _legal_words(text, trusted):
    """Where the words naming a code or a law the customer named stand in `text`, in any language: no one's name.

    A legal sentence that is kept names the customer's code (`_laws`): in a paper in another language than the
    message its "Mehnat kodeksi" or "Labour Code" is their "Трудовой кодекс", and the names check must not take
    the code's name for an invented one ("Bosh buxgalter ____ kodeksiga muvofiq", "follows the ____ of the
    Republic"). Only a word of LAW_NAMES their words name and a stem of a kind of act they named are given.
    """
    found = set()
    for start, end in _sentences(text):
        sentence = text[start:end]
        if not _concepts(sentence):
            continue
        for at, word in _law_names(sentence):
            forms = _law_name(word)
            if forms is not None and forms.search(trusted.legal):
                found.add(start + at)
        for concept, stem, _ in STEMS:
            if concept in ('code', 'law', 'constitution') and any(
                    other.search(trusted.legal) for name, other, _ in STEMS if name == concept):
                found |= {start + match.start() for match in stem.finditer(sentence)}
    return found


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


def _organisation(text, run):
    """Whether a run that opens a sentence names an organisation by its shape, so its first word is held (`orgs`).

    Its first word is shaped as one ("Hamkorbank", "Kapitalbanki", "UzAuto", "UNICEF"; never a roman numeral), or
    the run goes on in an organisation's form or kind ("Acme LLC", "Westminster University", "Xalq Banki"), or a
    quoted name is followed by one ("«Baraka» MChJ"), or an Uzbek name by its kind in lower case in the possessive
    it gives it ("Asaka banki", "Artel kompaniyasidagi", "Korzinka supermarketlar tarmog‘ida": `ORG_AFTER`), unless
    the word is one that makes the kind a kind ("Tijorat banki", "Davlat universiteti": `KIND_WORDS`).
    """
    first = run[0][2]
    if _org_shaped(first):
        return True
    if any(fold(word) in ORG_HEADS for _, _, word in run[1:]):
        return True
    after = re.match(r"[»\"”'’]+[ \t\u00a0]*([^\W\d_][^\W\d_'‘’ʻʼ`´-]*)", text[run[-1][1]:])
    if after is not None and fold(after.group(1)) in ORG_HEADS:
        return True
    if len(run) == 1 and fold(first) in KIND_WORDS:
        return False
    kind = re.match(rf"[»\"”'’]*[ \t\u00a0]+({WORD.pattern})(?:[ \t\u00a0]+({WORD.pattern}))?", text[run[-1][1]:])
    if kind is None or not kind.group(1)[0].islower():
        return False
    if len(run) == 1 and RU_NAMED.fullmatch(first.casefold()) and not RU_KIND_ADJECTIVES.fullmatch(first.casefold()):
        # "Вестминстерский университет", "Самаркандский государственный институт".
        after = kind.group(1).casefold()
        second = (kind.group(2) or '').casefold()
        return RU_ORG_KINDS.fullmatch(after) is not None or (
            RU_ADJECTIVE.fullmatch(after) is not None and RU_ORG_KINDS.fullmatch(second) is not None)
    # A plural before a kind is a name as often as a common noun ("Do‘stlar kompaniyasida", "Yoshlar banki" beside
    # "Keyslar banki", a bank of cases): it is held, a false blank at worst; never the people a clinic or a
    # cooperative serves ("Bolalar klinikasida", "Fermerlar shirkati": `PEOPLE_SERVED`).
    word = fold(kind.group(1))
    if len(run) == 1 and fold(first) in PEOPLE_SERVED and word in SERVING_KINDS:
        return False
    return word in ORG_AFTER or (word.endswith('lar') and kind.group(2) is not None and fold(kind.group(2)) in CHAIN)


def _org_shaped(word):
    """Whether a word is shaped as an organisation's name: a bank's ("Hamkorbank", "Kapitalbanki"), CamelCase
    ("UzAuto"), or an acronym of three capitals or more that is no roman numeral ("UNICEF")."""
    if re.fullmatch(r"[^\W\d_]{2,}bank[^\W\d_]*", fold(word)) or any(
            a.islower() and b.isupper() for a, b in zip(word, word[1:])):
        return True
    return word.isupper() and _letters(word) >= 3 and not re.fullmatch(r"[IVXLCDM]+", word)


# The common words a paper's sentence, cell or item may open with, by language (words/*.txt, `common`), and the
# endings a sentence gives them there, so that "Savdoda", "Soliqlar", "Kompaniyangizda", "Компания" and "Trading"
# are found from "savdo", "soliq", "kompaniya", "компании" and "trade".
WORDS = Path(__file__).with_name('words')
UZ_SUFFIXES = frozenset(
    derived + plural + own + case
    for derived in ('', 'li', 'siz', 'lik', 'lig', 'iy', 'viy', 'chi', 'gi', 'ki', 'roq', 'cha')
    for plural in ('', 'lar')
    for own in ('', 'i', 'si', 'im', 'ing', 'imiz', 'ingiz', 'm', 'ng', 'miz', 'ngiz', 'lari', 'ri')
    for case in ('', 'ga', 'ka', 'qa', 'ni', 'ning', 'da', 'dan', 'dagi', 'gacha', 'dek', 'day', 'ki', 'mi', 'gina'))
RU_SUFFIXES = frozenset((
    'а я о е и ы у ю ь й ой ей ий ый ая яя ое ее ые ие ом ем ам ям ах ях ами ями ов ев ого его ому ему ую юю ых их ым '
    'им ыми ими ью ию ия ии ием иям иях иями ость ости остью остей ться тся ет ют ит ят ут ат ил ила ило или ал ала '
    'ало али ел ела ело ели').split())
# An Uzbek verb's endings, after a stem a common word gives: "Ishlab", "Ta’minlaydi", "Bajarilsin", "Qadoqlanadi",
# "O‘rgatilgan", "Tayyorlanmoqda": a voice (passive, causative, reflexive), a negation and a form.
UZ_VERB_SUFFIXES = frozenset(
    voice + negation + form
    for voice in ('', 'il', 'in', 'n', 'l', 'tir', 'dir', 'iz', 'ish', 'sh', 'lan', 'lash', 'tiril', 'diril')
    for negation in ('', 'ma')
    for form in ('adi', 'aydi', 'ydi', 'di', 'dim', 'dik', 'ding', 'dingiz', 'dilar', 'gan', 'gandi', 'ganda',
                 'gani', 'ganini', 'ganligi', 'gach', 'guncha', 'ib', 'b', 'ish', 'ishi', 'ishni', 'ishga', 'ishda',
                 'ishdan', 'ishning', 'moq', 'moqda', 'moqchi', 'adigan', 'aydigan', 'ydigan', 'ayotgan', 'yotgan',
                 'ayapti', 'yapti', 'sin', 'sinlar', 'ylik', 'aylik', 'ar', 'masdan', 'sa', 'sak', 'sangiz',
                 'ng', 'ngiz', 'gin', 'ladi', 'lanadi')) - {''}
# No -er nor -est: "Fuller", "Gardener", "Walker", "Turner" are surnames as often as words, so a word in -er is listed.
EN_SUFFIXES = frozenset("s es 's ed d ing ly ment ments ness ion ions al ally ity ive".split())
SUFFIXES = {'uz': (UZ_SUFFIXES | UZ_VERB_SUFFIXES) - {''}, 'ru': RU_SUFFIXES, 'en': EN_SUFFIXES}
# A Russian finite verb or infinitive, which a list item of duties opens with ("Соблюдает", "Ведёт", "Руководствуется",
# "Обеспечивать", "Участвовали", "Родился"), and an adjective not of a name's shape ("Переменные расходы",
# "Эксплуатационные", "Подоходный"): no name is one. Never the -ий of Дмитрий or Евгений, nor the -ой of Москвой.
RU_VERB = re.compile(r"[а-яё]{3,}(?:[аяуеё]ет|[аяуеё]ют|ит|ят|ётся|ется|ится|ются|ятся|ться|ать|ять|ить|еть|йте|ите"
                     r"|лся|лась|лось|лись)|[а-яё]{5,}(?:али|или|ели)")
RU_COMMON_ADJECTIVE = re.compile(r"[а-яё]{4,}(?:ый|[кгхжшщч]ий|ая|яя|ое|ее|ые|ие|ого|его|ому|ему|ую|юю|ых|их|ыми|ими)")
# The suffixes that make a common noun, an adjective, a verb's form or an adverb and never a name (`common`), on the
# word as typed, after a base of four letters: an Uzbek abstract noun, agent, place, verbal noun or converb
# ("Ko‘ngillilik", "Haydovchi", "Omborxona", "Qadoqlash", "Bitirgach", "Mikroiqtisodiyot"), a Russian abstract noun,
# agent or action ("Скромность", "Волонтёрство", "Уборщица", "Упаковка", "Принимал"), an English abstract noun,
# adjective or adverb ("Depreciation", "Punctuality", "Admittedly", "Upselling"). A name that ends so is in names.txt
# ("Людмила", "Fleming", "Lawrence") and refused first.
DERIVED = {
    'uz': re.compile(r"[a-z']{4,}(?:lik|lig|chilik|garchilik|xona|lash|lashtir|lantir|uvchi|ovchi|uvchan|dosh|shunos"
                     r"|iyat|iyot|gach|ilgach|ilgan|lgan|moq|chi|siz)(?:[a-z']*)"),
    'ru': re.compile(r"[а-яё]{4,}(?:ость|ости|остью|остей|остям|ство|ства|ству|ством|стве|ств|ние|ния|нию|нием|нии"
                     r"|ний|ниям|ниях|ция|ции|цию|цией|ций|циям|щик|щика|щику|щиком|щики|щиков|щица|щицы|щице|щицу"
                     r"|щицей|чик|чика|чику|чиком|чики|чиков|чица|чицы|чице|чицу|тель|теля|телю|телем|тели|телей"
                     r"|тельница|тельницы|изм|изма|изму|измом|ировка|ировки|ировку|овка|овки|овку|овкой|ёвка|евка"
                     r"|ал|ала|ало|ял|яла|яло|ил|ила|ило|ел|ела|ело|ул|ула)"),
    'en': re.compile(r"[a-z]{4,}(?:tion|tions|sion|sions|ment|ments|ness|ity|ities|ism|isms|ance|ances|ence|ences"
                     r"|ship|ships|hood|ful|less|able|ible|ive|ous|ally|edly|ingly|ously|ively|fully|ately|ently"
                     r"|antly|ably|ibly|ing|ings|ise|ize|ised|ized|ising|izing|isation|ization)"),
}


# The shortest base an ending is read after (`common`), and the shortest a stem is cut to: a three-letter base made
# names of common words ("Malika" of mal+ika, "Peter" of pet+er, "Termiz" of ter+miz, "Анна" of анн+а). A word of
# three letters takes only a case or a plural (`SHORT_ENDINGS`): "Sexni", "Ishga", "Uylar", "Дома", "Uses".
LEXICON_BASE = 4
SHORT_ENDINGS = {
    'uz': frozenset(case + more for case in ('', 'lar') for more in ('', 'ga', 'ka', 'qa', 'ni', 'ning', 'da', 'dan',
                                                                       'dagi', 'gacha', 'dek')) - {''},
    'ru': frozenset('а у е ы и ом ам ах ами ов ой ей ю я'.split()),
    'en': frozenset(('s', 'es', 'ed', 'ing', "'s")),
}
# The endings a name takes in a sentence, folded (`_name_forms`): Uzbek cases ("Malikaga", "Toshkentdan"), the -lik
# of a place's people ("Toshkentlik"), and the Russian cases of a name in -a ("Малике", "Маликой") and of one in a
# consonant ("Ивана", "Иваном"). An English possessive is read off the word as typed ("Smith's"), never a plural.
NAME_CASES = ('ga', 'ka', 'ni', 'ning', 'da', 'dan', 'dagi', 'gacha', 'dek', 'niki')
PLACE_PEOPLE = ('lik', 'likka', 'likni', 'liklar', 'liklarga', 'liklarni', 'liklarning')
RU_A_CASES = ('i', 'e', 'u', 'oy', 'ou', 'ey')
RU_CASES = ('a', 'u', 'om', 'e')


@functools.cache
def _lexicon():
    """{language: (its common words, their stems before an ending)}, read once per process."""
    found = {}
    for language, endings in SUFFIXES.items():
        lines = (WORDS / f'{language}.txt').read_text('utf-8').splitlines()
        words = frozenset(line.strip() for line in lines if line.strip() and not line.startswith('#'))
        stems = frozenset(word[:cut] for word in words for cut in range(LEXICON_BASE, len(word))
                          if word[cut:] in endings)
        found[language] = (words, stems)
    return found


@functools.cache
def _name_forms():
    """(the names of words/names.txt folded, their forms with a case ending folded), read once per process.

    Every section refuses its words in a paper of any language (`common`): a Russian given name ("Larisa") is as
    realistic an invented person in an English or an Uzbek paper as in a Russian one, and an English given name that
    is an Uzbek word ("Tom", "Sara", "Joy", "Kim") as realistic in an Uzbek paper as the word itself."""
    names, forms, place = set(), set(), False
    for line in (WORDS / 'names.txt').read_text('utf-8').splitlines():
        line = line.strip()
        if line.startswith('#'):
            place = place if not line.startswith('# ----') else 'places' in line.casefold()
            continue
        if not line:
            continue
        name = fold(line)
        names.add(name)
        forms.update(name + ending for ending in NAME_CASES + (PLACE_PEOPLE if place else ()))
        forms.update(name[:-1] + ending for ending in RU_A_CASES) if name.endswith('a') else \
            forms.update(name + ending for ending in RU_CASES)
    return frozenset(names), frozenset(forms - names)


def _named(low):
    """Whether a word (lower case) is a name of words/names.txt, whole or with a case ending (`_name_forms`).

    The name itself is one even where it is also a common word ("Umid", "Grace", "Надежда"); a form of it with an
    ending only where the language has no such word ("Malikaga", never "Umidi", "Shirinlik", "Ширина").
    """
    names, forms = _name_forms()
    possessive = re.fullmatch(r"(.{2,}?)(?:'s|s')", low)
    if fold(low) in names or (possessive is not None and fold(possessive.group(1)) in names):
        return True
    if fold(low) not in forms:
        return False
    return not any(low in _lexicon()[language][0] for language in SUFFIXES)


def common(word, language=None):
    """Whether a capitalised word is a common word of Uzbek, Russian or English rather than a name: one of the
    lexicon's (words/*.txt) with or without an ending, a number word, a plural or a Russian verb (no name is one:
    "O‘quvchilar", "Соблюдает"), and never a given name, a surname, a place or a brand of words/names.txt
    (`_named`), even one that is also a common word, in a paper of any language: the owner's tie-break, a blank
    before a leak. An Uzbek paper's "Tom yopish ishlari" is blanked as its "Tom yangi filialni ochdi" must be.

    `language` is the paper's: an English paper reads a Latin word against the English lexicon only, so a name the
    Uzbek lexicon happens to parse ("Yana", "Sita", "Larisa" as lari+sa) is no common word there; an Uzbek or a
    Russian paper, or no language, reads it against both."""
    low = normalised(word).casefold()
    cyrillic = re.search('[а-яё]', low) is not None
    if _named(low):
        return False
    if numbers._spelled_role(low, False) is not None or numbers.ORDINAL.fullmatch(low):
        return True
    if not cyrillic and re.search(r"lar(?:i|ning|ni|ga|da|dan|imiz|ingiz)?$", low):
        return True
    if cyrillic and (RU_VERB.fullmatch(low) or (RU_COMMON_ADJECTIVE.fullmatch(low) and (
            not RU_NAMED.fullmatch(low) or RU_KIND_ADJECTIVES.fullmatch(low)))):
        return True
    if re.fullmatch(r"[A-Z]{2,}s", word) or re.fullmatch(r"[IVXLC]+", word):
        return True  # an acronym's plural ("SOPs", "CVs"; an organisation's name is no plural), a roman numeral
    for lexicon in (('ru',) if cyrillic else ('en',) if language == 'en' else ('uz', 'en')):
        words, stems = _lexicon()[lexicon]
        if low in words or low in stems:
            return True
        endings = SUFFIXES[lexicon]
        if len(low) > 3 and low[:3] in words and low[3:] in SHORT_ENDINGS[lexicon]:
            return True
        for cut in range(LEXICON_BASE, len(low)):
            base = low[:cut]
            if low[cut:] in endings and (base in words or base in stems or (lexicon == 'en' and (
                    base + 'e' in words or (low[cut:] in ('es', 'ed') and base.endswith('i')
                                            and base[:-1] + 'y' in words)))):
                return True  # "Trading" of "trade", "Complies" of "comply"
        if DERIVED[lexicon].fullmatch(low):
            return True
    return False


# "Aziz hamkorlar, …", "Aziz mijozlarimiz!": a letter's "dear" before the plural it addresses and that address's mark,
# never a person named Aziz ("Aziz hamkorlar bilan uchrashdi", "Aziz, …").
ADDRESS_WORDS = frozenset(('aziz', 'qadrli'))
ADDRESSED = re.compile(r"[ \t\u00a0]+[^\W\d_A-ZА-ЯЁ](?:[^\W\d_]|['‘’ʻʼ`-](?=[^\W\d_]))*?"
                       r"lar(?:im|imiz|ing|ingiz)?[ \t\u00a0]*[,!]")


def _address(text, run):
    """Whether a run's one word is a letter's "dear" addressing its readers (`ADDRESS_WORDS`, `ADDRESSED`)."""
    return len(run) == 1 and fold(run[0][2]) in ADDRESS_WORDS and ADDRESSED.match(text, run[0][1]) is not None


def _compound(text, run):
    """Whether a run's one word joins a lower-case word with a hyphen ("Long-term", "Wood-fired"): no lone name."""
    return len(run) == 1 and re.match(r"-[^\W\d_]", text[run[0][1]:]) is not None \
        and text[run[0][1] + 1].islower()


def _unknown_runs(text, trusted, translated=False, *, strict=False, orgs=False, invented=None, legal=(), lone=False,
                  language=None):
    """(run, positions of its words not the customer's, whether its first word was left free) of each run (`_names`).

    `legal` holds where the words of the customer's own code stand (`_legal_words`): never a name. `lone` (a paper's
    grounded part) holds a first word that is no common word (`common`, in the paper's `language`), the customer's or
    no one's.
    """
    for run in _runs(text):
        bad = []
        first_free = _starts(text, run[0][0])
        if strict and first_free and (_after_colon(text, run[0][0])
                                      or (len(run) > 1 and all(_letters(word) < 2 for _, _, word in run[1:]))
                                      or _surname(run[0][2]) or (orgs and _organisation(text, run))
                                      or (invented is not None and invented.has(fold(run[0][2])))
                                      or (lone and not common(run[0][2], language) and not _compound(text, run)
                                          and not _address(text, run))):
            first_free = False
        for position, (start, end, word) in enumerate(run):
            if _letters(word) < 2 or (position == 0 and first_free) or start in legal:
                continue
            if not trusted.person(word, translated):
                bad.append(position)
        yield run, bad, first_free


def _holdable(text, run, bad):
    """The folded words of a run's words not the customer's (`bad`, positions) that name someone wherever they stand.

    A person's: the words side by side with one shaped as a surname ("Karimova Dilnoza", "Sardor Xolmatov"). An
    organisation's: a word shaped as one ("Hamkorbank", "UNICEF") or a quoted name («Baraka»), never its kind or a
    word that makes a kind ("Market", "Savdo"). A run of common words ("Davlat Soliq Qo‘mitasi", "Moliya
    Vazirligi", the "Bosh" of "Bosh hisobchi") gives none, so it never blanks "Davlat ro‘yxatidan o‘tish ..." or
    "Bosh ofis ..." elsewhere (`_names`'s `blanked`, `held_names`).
    """
    bad = [position for position in bad if _letters(run[position][2]) >= 2]
    found, group = [], []
    for position in bad + [None]:
        if position is not None and (not group or position == group[-1] + 1):
            group.append(position)
            continue
        if any(_surname(run[at][2]) for at in group):
            found += [fold(run[at][2]) for at in group]
        group = [position] if position is not None else []
    quoted = _quoted(text, run)
    for position in bad:
        word = run[position][2]
        folded = fold(word)
        if folded not in found and folded not in ORG_HEADS and folded not in KIND_WORDS \
                and (quoted or _org_shaped(word)):
            found.append(folded)
    return found


def _quoted(text, run):
    """Whether a run stands in quotation marks of its own: «Baraka», "Oqtosh"."""
    before = text[:run[0][0]].rstrip(' \t\u00a0')
    after = text[run[-1][1]:].lstrip(' \t\u00a0')
    return before[-1:] in ('«', '"', '“', '„', "'", '‘') and after[:1] in ('»', '"', '”', '“', "'", '’')


def _names(text, trusted, codes, translated=False, *, strict=False, orgs=False, invented=None, blanked=None,
           lone=False, language=None):
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

    `orgs` (a paper's grounded part) also holds a first word that opens an
    organisation's name by its shape (`_organisation`): "Hamkorbank 200 mln
    so‘m kredit beradi.", "Acme LLC increased sales", "«Baraka» MChJ ...".
    `invented` (`Named`) holds the words the same finish has already taken
    out as no one's the customer gave (a rejected fact's names, a blanked run
    elsewhere): a first word that is one of them, whole or with a case ending,
    is held too, so "Artelda ishlaganman." is not left when the employer
    "Artel" was just blanked. `blanked`, a `Named`, receives the words of each
    run blanked here that name someone (`_holdable`): a person's beside a
    surname, the free first word of one blanked whole included ("Hikmat
    Rahimov ..." gives hikmat too), an organisation's shaped or quoted, never
    a common word alone.
    """
    spans = []
    # A paper's grounded part names the customer's code in its own language (`_legal_words`).
    legal = _legal_words(text, trusted) if orgs else ()
    for run, bad, first_free in _unknown_runs(text, trusted, translated, strict=strict, orgs=orgs, invented=invented,
                                              legal=legal, lone=lone, language=language):
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
        if blanked is not None:
            # Read once the run is blanked whole: a person's free first word goes with the surname beside it
            # ("Larisa Ivanova ...", then "Larisa also ..."), so a later lone reference is held too.
            for word in _holdable(text, run, bad):
                blanked.add(word)
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


def _rejected(text, trusted, rejected, codes, translated=False):
    """Blank the runs naming a person or an organisation whose fact this finish has just taken out.

    `rejected` holds each such fact's words that were not the customer's, folded ("karimova", "dilnoza",
    "baxodirovna"). A run of a guarded part with two of them side by side, or the one of a one-word name, goes with
    the initials beside it: the lesson's "O‘qituvchi Karimova Dilnoza Bahodirovna o‘quvchilar bilan salomlashadi"
    when the teacher "Karimova Dilnoza Bahodirovna" was just blanked. A surname so taken also takes the names
    beside it that are not the customer's either: "Karimova Dilnoza" when the teacher was "Karimova D. R.". Nothing
    else is read for names there.
    """

    def other(position):
        word = run[position][2]
        return _letters(word) < 2 or not trusted.person(word, translated)
    spans = []
    for run in _runs(text):
        for value in rejected:
            words = Words(value)
            hits = [position for position, (_, _, word) in enumerate(run)
                    if _letters(word) >= 2 and words.has(fold(word)) and not trusted.person(word, translated)]
            group = []
            for position in hits + [None]:
                if position is not None and (not group or position == group[-1] + 1):
                    group.append(position)
                    continue
                if len(group) >= min(2, len(value)):
                    named = any(_surname(run[at][2]) for at in group)
                    while group[0] > 0 and (_letters(run[group[0] - 1][2]) < 2 or (named and other(group[0] - 1))):
                        group.insert(0, group[0] - 1)
                    while group[-1] + 1 < len(run) and (_letters(run[group[-1] + 1][2]) < 2
                                                        or (named and other(group[-1] + 1))):
                        group.append(group[-1] + 1)
                    spans.append(_span(text, run, group, True))
                group = [position] if position is not None else []
    if not spans:
        return text
    codes.append('ground:name')
    merged = []
    for start, end in sorted(set(spans)):
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return _replace(text, merged)


def guard(text, trusted, *, translated=False, checks=(), words=False, orgs=False, invented=None, blanked=None,
          rejected=(), lone=False, language=None):
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
    `orgs`, `invented`, `blanked`, `lone` and `language` (the paper's) are passed to the 'names' check
    (`_names`, a paper's grounded parts). `rejected` (`_rejected`) is for a paper's
    guarded parts and title: the people and organisations of facts the same
    finish has taken out are blanked there too.
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
        text = _names(text, trusted, codes, translated, strict=True, orgs=orgs, invented=invented, blanked=blanked,
                      lone=lone, language=language)
    if rejected:
        text = _rejected(text, trusted, rejected, codes, translated)
    return _tidy(text), list(dict.fromkeys(codes))


def guarded_known(text, trusted, *, translated=False):
    """Whether a guarded paper's text fact (its topic) says nothing of the customer's they did not give.

    The topic keeps its general knowledge, as the paper's guarded parts do ("Abdulla Qodiriy ijodi", "The First
    Amendment to the United States Constitution"), but not a quotation (`_quotes`), a law, a code or an act the
    customer did not name (`_legal_known` without its names check: the act and the code's name are what a topic
    cites), nor an organisation named by its shape or form (`_organisation`): "«Vatan sajdagoh kabi muqaddasdir»
    degan g‘oya ...", "(Ta’lim to‘g‘risidagi qonun talablari asosida)", "(«Hamkorbank» ATB misolida)".
    """
    codes = []
    _quotes(text, trusted, codes)
    if codes:
        return False
    for start, end in _sentences(text):
        sentence = text[start:end]
        concepts = _concepts(sentence)
        if concepts and not _legal_known(sentence, concepts, trusted, translated, names=False):
            return False
    return all(not _organisation(text, run) or all(trusted.person(word, translated) for _, _, word in run
                                                   if _letters(word) >= 2) for run in _runs(text))


def people_known(text, trusted, *, translated=False, orgs=False):
    """Whether guard's 'names' check would leave `text` whole: every capitalised run the customer's, read strictly.

    For a line that is kept or dropped whole, such as a title-page line: a
    first word is free only as `_names` leaves it free in strict mode, so a
    line's own opening word ("Grocery shop", "Term paper") is not taken for a
    name, but a surname, a word before initials or before an invented name is.
    """
    codes = []
    _names(str(text or ''), trusted, codes, translated, strict=True, orgs=orgs)
    return not codes


def failed_names(value, kind, trusted, *, translated=False):
    """The folded words of a fact taken out as not the customer's that name someone they never gave.

    A person's, an organisation's, a place's, a line's or a list's every capitalised word that is not theirs, a
    label's before its colon left ("Rais: Karimov Aziz" gives karimov and aziz, never rais); a figure's or a text's
    as a grounded line reads them (`_names`, its opening word free). A value taken out only for a number gives
    nothing it did not fail on.
    """
    text, _ = _strip_addresses(str(value or ''), trusted)
    found = []
    for line in re.split(r'[\n;]+', text):
        if kind in ('person', 'org', 'place', 'line', 'list'):
            # Every capitalised word was checked; a label's own words before its colon ("Rais:", "Kotiba:") name no one.
            line = re.sub(r'^[^:\d\n]{1,40}:', ' ', line.strip())
            found += [fold(word) for word in WORD.findall(line)
                      if word[0].isupper() and _letters(word) >= 2 and not trusted.person(word, translated)]
            continue
        for run, bad, _ in _unknown_runs(line, trusted, translated, strict=True, orgs=True):
            found += [fold(run[position][2]) for position in bad if _letters(run[position][2]) >= 2]
    return list(dict.fromkeys(found))


def held_names(value, kind, trusted, *, translated=False, people=True):
    """The folded words of a fact taken out as not the customer's that a paper holds wherever they open a sentence.

    Only words that name someone wherever they stand (finish's `invented`, read whole or with a case ending,
    `Named`): a person's every word not the customer's but a role's opening word ("Bosh direktor Karimova
    Dilnoza" gives karimova and dilnoza, never bosh); else a person's beside a surname ("Bosh hisobchi Karimova
    Dilnoza"), every word of a line's name (`_line_names`: "Rais: Hikmat Rahim", a participants' list's
    "Rahmat", "Direktor | Hikmat", "Grant Fuller", a given name that is also a word included: the owner's
    tie-break, a blank before a leak), never the "Bosh Hisobchi", "Maktab Direktori" or "Rezyume" of a line, nor
    any word of a field that holds no people (`people`: the enclosures), an organisation's shaped or quoted
    ("Hamkorbank", "«Baraka» nonvoyxonasi"), and an
    organisation's or a place's name before its legal form or alone ("Acme LLC", "Artel MChJ", "Artel",
    "Samarqand"; of "Acme Trading LLC" the first). A name its value follows with its kind ("Xalq banki",
    "Westminster University") is held by that kind where it opens a sentence (`_organisation`); alone it may be a
    common word ("Xalq sayllarida"), so it is not held. A run of common words ("Moliya Vazirligi") gives nothing.
    """
    text, _ = _strip_addresses(str(value or ''), trusted)
    found = []
    for line in re.split(r'[\n;]+', text):
        if kind in ('person', 'org', 'place', 'line', 'list'):
            # Every capitalised word was checked; a label's own words before its colon ("Rais:", "Kotiba:") name no one.
            line = re.sub(r'^[^:\d\n]{1,40}:', ' ', line.strip())
            runs = [(run, [position for position, (_, _, word) in enumerate(run)
                           if _letters(word) >= 2 and not trusted.person(word, translated)]) for run in _runs(line)]
        else:
            runs = [(run, bad) for run, bad, _ in _unknown_runs(line, trusted, translated, strict=True, orgs=True)]
        if kind == 'person':
            found += [fold(run[position][2]) for run, bad in runs if not _role_opening(line, run)
                      for position in bad if _letters(run[position][2]) >= 2]
            continue
        for run, bad in runs:
            found += _holdable(line, run, bad)
        if kind in ('line', 'list') and people:
            found += [fold(word) for word in _line_names(line)
                      if _letters(word) >= 2 and not trusted.person(word, translated)]
        if kind in ('org', 'place'):
            found += _one_name(line, runs)
    return list(dict.fromkeys(found))


# The words a name takes after it in lower case, part of it rather than a role's: "Malika opa", "Aziz aka", "Dilnoza
# xonim", "Karim domla", "Малика хоним".
HONORIFICS = re.compile(r"opa|opajon|aka|akajon|xonim|janob|bonu|hoji|domla|mulla|ака|опа|хоним|жаноб|бону|ҳожи|домла",
                        re.IGNORECASE)


def _role_opening(line, run):
    """Whether a run is a role's capitalised opening word, a lower-case word after it: "Bosh" of "Bosh direktor",
    never a name's honorific ("Malika opa", `HONORIFICS`)."""
    after = re.match(rf"[ \t\u00a0]+({WORD.pattern})", line[run[-1][1]:])
    return len(run) == 1 and not _surname(run[0][2]) and after is not None and after.group(1)[:1].islower() \
        and not HONORIFICS.fullmatch(normalised(after.group(1)))


def _only_name(line):
    """Whether a line is a name and nothing else: one to three capitalised words with its initials, none a kind
    ("Aziz Rahim", "Dilnoza", "Peter Brown", "Chase Banks"); never "Bosh hisobchi Karimova D." nor "Moliya
    Vazirligi". An English kind in the plural is a surname's word there ("Banks"), never an organisation's kind."""
    words = [word for word in WORD.findall(line) if not HONORIFICS.fullmatch(normalised(word))]
    named = [word for word in words if _letters(word) >= 2]
    return 1 <= len(named) <= 3 and all(word[0].isupper() for word in words) and not any(
        fold(word) in ONLY_NAME_KINDS or re.search(r'(?:si|gi)$', fold(word)) for word in named)


# The words of a line that make it a role's, a job's or a document's rather than someone's name: "Direktor",
# "Bosh Hisobchi", "Maktab Direktori", "Rezyume", "Diplom nusxasi", "Head of Sales", "Секретарь", with the endings a
# sentence gives them. A line's name stands after the last of them ("Direktor Hikmat Rahim", "Bosh hisobchi Karimova
# Dilnoza"), and a line or a part of one that is only such words names no one (`_line_names`). Read for that only:
# these are no allowed words of the names check, where a role that is also a given name would let a name through.
ROLE_STEMS = UZ_ROLES + (
    "rais o‘rinbosar hisobchi buxgalter kassir sotuvchi kotib kotiba muhandis yurist iqtisodchi mutaxassis "
    "inspektor nazoratchi operator maslahatchi dasturchi dizayner shifokor hamshira haydovchi omborchi novvoy oshpaz "
    "ofitsiant farrosh qorovul usta ishchi laborant metodist psixolog kutubxonachi murabbiy auditor koordinator "
    "administrator assistent bosh "
    # The documents an enclosures' or an attachments' line lists.
    "rezyume tavsiyanoma tavsifnoma diplom sertifikat pasport ariza ma’lumotnoma guvohnoma nusxa xat shartnoma "
    "buyruq dalolatnoma bayonnoma hujjat ilova attestat transkript portfolio").split()
ROLE_MUTATED = ("boshlig‘ rahbarlig‘").split()
# The line and list fields that hold no people, whose rejected words a paper never holds as a name (`held_names`'s
# `people`): the documents a letter encloses, a statement's points, a position's or a status's words.
NO_PEOPLE = frozenset(('enclosures', 'attachments', 'statements', 'key_dates', 'position', 'applicant_role',
                       'writer_role', 'subject_role', 'candidate_status', 'recommender_position', 'approver_post',
                       'signer_position', 'currency', 'period', 'legal_form', 'loan_term', 'loan_grace',
                       'loan_repayment', 'tax_regime', 'vat_status', 'price_info', 'meeting_time', 'source_pages'))
EN_ROLE_WORDS = EN_ROLES + (
    "dean accountant cashier secretary engineer lawyer economist specialist deputy supervisor coordinator "
    "administrator advisor adviser consultant inspector instructor tutor lecturer professor head vice "
    "cv resume certificate certificates diploma transcript passport letter copy copies reference portfolio essay "
    "enclosure enclosures attachment attachments").split()
RU_ROLE_WORDS = re.compile(
    r"(?:директор|ректор|декан|руководител|председател|заведующ|начальник|заместител|бухгалтер|кассир|продав"
    r"|секретар|инженер|юрист|экономист|специалист|менеджер|учител|преподавател|член|главн|старш|инспектор"
    r"|резюме|диплом|сертификат|справк|копи|паспорт|письм|рекомендац|характеристик|заявлени|приложени|аттестат)\w*")
ROLE_WORDS = _folded([stem + ending for stem in ROLE_STEMS for ending in UZ_ENDINGS]
                     + [stem + ending for stem in ROLE_MUTATED for ending in ('i', 'ini', 'iga', 'ida', 'idan', 'ining')]
                     + [word + ending for word in EN_ROLE_WORDS for ending in ('', 's')])
# The kinds no line that is only a name holds (`_only_name`): an English kind in the plural is a surname's word.
ONLY_NAME_KINDS = (ORG_HEADS | ORG_AFTER | KIND_WORDS) - _folded([kind + 's' for kind in EN_ORG_KINDS])
# Where a line's parts part: "Direktor | Hikmat", "John Smith, Head of Sales", "Hikmat Rahim (kotib)", "Rais — …".
LINE_PARTS = re.compile(r"[ \t ]*[|,()/][ \t ]*|[ \t ]+[–—-][ \t ]+")


# A line's words, a hyphenated one whole ("Ota-onalar", "Vice-President").
LINE_TOKEN = re.compile(WORD.pattern + r"(?:-" + WORD.pattern + r")*")
# The words that make a role a kind of one beside it in a line, no one's name there (`_line_roles`): "Katta
# o‘qituvchi", "Ijrochi direktor", "Senior Sales Manager", "Chief Financial Officer", "Vice President of Sales",
# "Head of Human Resources".
ROLE_MODIFIERS = _folded((
    "katta kichik bosh yetakchi ijrochi texnik moliyaviy tijorat ilmiy muvaqqat "
    "senior junior chief executive general deputy assistant associate regional national international global "
    "sales marketing finance financial accounting accounts account operations operating technical technology "
    "information human resources commercial product project customer service services quality research "
    "development logistics procurement purchasing production administrative office branch store shop retail area "
    "district communications public relations business strategy strategic digital brand key legal compliance risk "
    "security training education academic admissions payroll credit investment budget analytics data engineering "
    "design creative content media events export import supply chain warehouse division unit group "
    "vice president managing founding interim acting").split())
# A role's grammar words, part of it in a line: "Head of Sales", "Head of Sales and Marketing", "Head of the Department".
ROLE_GRAMMAR = frozenset(('of', 'for', 'and', 'the'))


def _role_word(word):
    """Whether a word is a role's, a job's or a document's (`ROLE_WORDS`, `RU_ROLE_WORDS`)."""
    return fold(word) in ROLE_WORDS or RU_ROLE_WORDS.fullmatch(normalised(word).casefold()) is not None


# A Russian adjective in the nominative, which a role takes before it in a line: "Главный", "Финансовый директор".
RU_ROLE_ADJECTIVE = re.compile(r"[а-яё]{3,}(?:ый|ий|ой|ая|яя|ое|ее)")


def _possessive(token):
    """Whether a line's Latin word ends in the Uzbek possessive a role or its modifier takes ("direktori", "raisi",
    "boshlig‘i", "bo‘limi", "qo‘mitasi"), never an agent's -chi ("o‘qituvchi", "hisobchi")."""
    folded = fold(token)
    return len(folded) >= 4 and folded.endswith('i') and not folded.endswith('chi') \
        and re.search('[а-яё]', token.casefold()) is None


def _line_roles(tokens):
    """Which words of a line's part (`LINE_TOKEN`) are its role's rather than someone's name.

    A role's, a job's or a document's word (`_role_word`); the words an Uzbek possessive role takes before it, each
    one's possessive taking the one before ("Maktab direktori", "Moliya bo‘limi boshlig‘i", never the "Hikmat Rahim"
    of "Hikmat Rahim maktab direktori"); a modifier (`ROLE_MODIFIERS`) or a role's grammar word beside a role's word,
    or a Russian adjective before one ("Katta o‘qituvchi", "Senior Sales Manager", "Head of", "Sales and Marketing",
    "Финансовый директор"); the word a role's "of" or "for" names ("Head of Biology"); a word between two of them ("Head of the
    Biology Department"); and every word before a "by" ("Prepared by", "Compiled and edited by").
    """
    marked = [_role_word(token) for token in tokens]
    if 'by' in tokens:
        last = len(tokens) - 1 - tokens[::-1].index('by')
        marked[:last + 1] = [True] * (last + 1)
    changed = True
    while changed:
        changed = False
        for index, token in enumerate(tokens):
            if marked[index]:
                continue
            left = index > 0 and marked[index - 1]
            right = index + 1 < len(tokens) and marked[index + 1]
            low = token.casefold()
            if (right and _possessive(tokens[index + 1])) or (left and right) \
                    or ((left or right) and (fold(token) in ROLE_MODIFIERS or token in ROLE_GRAMMAR)) \
                    or (right and RU_ROLE_ADJECTIVE.fullmatch(low) is not None) \
                    or (left and index >= 2 and tokens[index - 1] in ('of', 'for', 'the') and marked[index - 2]):
                marked[index] = changed = True
    return marked


def _line_names(line):
    """The words of a line fact that are someone's name: of each part of it (`LINE_PARTS`), each run of capitalised
    words that are not its role's (`_line_roles`) when the run is only a name (`_only_name`), before the role, after it
    or with none. "Direktor | Hikmat" gives Hikmat, "Direktor Hikmat Rahim", "Hikmat Rahim kotib", "Hikmat Rahim
    maktab direktori" and "Bosh hisobchi Hikmat Rahim" Hikmat and Rahim, "Head of Sales Grant Fuller", "Grant Fuller
    Head of Sales" and "Prepared by Grant Fuller" Grant and Fuller, "Rahmat aka" Rahmat; "Bosh Hisobchi", "Maktab
    Direktori", "Moliya bo‘limi boshlig‘i", "Rezyume", "Head of Sales", "Senior Sales Manager" give none."""
    found = []
    for part in LINE_PARTS.split(line):
        tokens = LINE_TOKEN.findall(part)
        run = []
        for token, role in list(zip(tokens, _line_roles(tokens))) + [('', True)]:
            if not role and token[:1].isupper():
                run.append(token)
                continue
            if run and _only_name(' '.join(run)):
                found += [word for word in WORD.findall(' '.join(run)) if not HONORIFICS.fullmatch(normalised(word))]
            run = []
    return found


# The legal forms, with the endings an Uzbek sentence gives them ("MChJning"), apart from an organisation's kinds.
LEGAL_FORMS = _folded(ORG_FORMS + [form + ending for form in UZ_ORG_FORMS for ending in UZ_ENDINGS])


def _one_name(line, runs):
    """An organisation's or a place's name not the customer's: its only word unless its kind follows it ("Xalq
    banki"), or the first of its words before its legal form ("Acme Trading LLC") (`held_names`)."""
    names = [(run, position) for run, bad in runs for position in bad if _letters(run[position][2]) >= 2
             and fold(run[position][2]) not in ORG_HEADS and fold(run[position][2]) not in KIND_WORDS]
    if not names:
        return []
    last, at = names[-1]
    after = re.match(rf"[»\"”'’]*[ \t ]+({WORD.pattern})", line[last[at][1]:])
    following = fold(after.group(1)) if after is not None else ''
    first = fold(names[0][0][names[0][1]][2])
    if len(names) == 1:
        # A name before its legal form is always a name ("Acme LLC", "Artel MChJ"); one before its kind may be a
        # common word ("Xalq banki"), held by that kind where it opens a sentence instead.
        return [] if following in (ORG_HEADS | ORG_AFTER) - LEGAL_FORMS else [first]
    return [first] if following in LEGAL_FORMS else []

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


# An editor named in a references item: after "Edited by", "под ред.", "mas’ul muharrir", or before "tahriri ostida".
NAME_RUN = r"(?:[^\W\d_]\.[ \t]?){0,2}[^\W\d_][^\W\d_'‘’-]+(?:[ \t,]+(?:[^\W\d_]\.[ \t]?){1,2})?"
EDITOR_AFTER = re.compile(
    rf"(?:edited\s+by|eds\.|ed\.|под\s+ред(?:акцией)?\.?|ред\.|muharrir(?:i|lar)?)[\s:]*(?P<name>{NAME_RUN})",
    re.IGNORECASE)
EDITOR_BEFORE = re.compile(r"(?P<name>[^\W\d_][^\W\d_'‘’-]+\s+(?:[^\W\d_]\.\s?){1,2})\s*tahrir", re.IGNORECASE)


def _people_named_known(text, trusted):
    """Whether a translated references item's people are the customer's: those it opens with and its editors.

    The head, up to the first full stop or colon, is read as a title-page line is (people_known, in a
    translation's spellings): "Karimov A." and "A. Karimov" as `_authors` reads them, but also an author written
    in full ("Karimov Abdulla.", "Kotler, Philip.", "Philip Kotler and Kevin Keller.") and an English title
    there ("Economic Theory. Part I."), which a translation cannot have kept in the customer's words: a false
    drop, never an invention. So is an editor ("Edited by D. Chaffey", "mas’ul muharrir Saidov B.").
    """
    head = re.split(r"[.:]", text, maxsplit=1)[0]
    if not people_known(head, trusted, translated=True):
        return False
    names = [match.group('name') for pattern in (EDITOR_AFTER, EDITOR_BEFORE) for match in pattern.finditer(text)]
    return all(people_known(name, trusted, translated=True) for name in names)


# The words a references item adds around a source's own words that say nothing of which source it is: its
# publisher's and pages' words, its link's (folded). A genre is one only beside an author (`GENRES`).
BIBLIOGRAPHY = re.compile(r"nashr\w*|izd\w*|izdatel\w*|press|publish\w*|bet\w*|sahifa\w*|str|tom|jild|vol\w*|eds?"
                          r"|edition|url|http\w*|www|doi|isbn|issn|vip\w*|nomer|son|no")
# A source's genre, which a GOST reference adds after its title ("Raqamli marketing: darslik", "o‘quv qo‘llanma",
# "учебник", "учебное пособие", "a textbook"), folded: no word of the source's own when its author and title are the
# customer's. The topic with a genre after it and no author ("Raqamli marketing strategiyalari: o‘quv qo‘llanma.") is
# still an invented book.
GENRES = re.compile(r"darslik\w*|ukuv|kullanma\w*|uslubi\w*|monografi\w*|risola\w*|uchebn\w*|posobi\w*|metodichesk\w*"
                    r"|textbooks?|manual|handbook|monographs?|coursebook|guide")


def _words_given(text, trusted):
    """Whether every word of a references item is the customer's, its bibliography's own words left (`verify_items`),
    and its genre's beside an author."""
    authored = bool(_authors(text))
    for word in WORD.findall(text):
        if _letters(word) < 3 or BIBLIOGRAPHY.fullmatch(fold(word)) or trusted.allowed.known(word) \
                or (authored and GENRES.fullmatch(fold(word))):
            continue
        if not trusted.words.known(word):
            return False
    return True


def verify_items(items, trusted, *, file_names=(), translated=False, whole=False):
    """(kept, codes): the items of a references list that are the customer's sources, in order.

    Each is held as a line to what the customer said and the files' own text
    (a book they named, a description taken from a file's first page); with
    `whole` (a paper's) every word of it, lower case included, but its
    publisher's and pages' (`BIBLIOGRAPHY`): the topic with a genre after it
    ("Raqamli marketing strategiyalari: o‘quv qo‘llanma.") is no source the
    customer gave. One that is not, or that is an attached file's name with
    or without its extension, is dropped: a references list never shows a
    file name.
    `translated` is for a list written in another language than the message,
    whose titles are translated: its capitalised words are then not checked,
    only its numbers, the authors it opens with ("Karimov A.", "Kotler,
    Philip.") and its editors, which are people's names and only spelled anew
    (`_people_named_known`), so pass it only when the titles really are
    translated.
    """
    kept, codes = [], []
    for item in items or []:
        text = _item_text(item).strip()
        if not text:
            continue
        if _file_name(text, file_names) or not supported(text, 'line', trusted, translated=translated) \
                or (translated and not (_authors_known(text, trusted) and _people_named_known(text, trusted))) \
                or (whole and not translated and not _words_given(text, trusted)):
            codes.append('source:dropped')
            continue
        kept.append(item)
    return kept, list(dict.fromkeys(codes))
