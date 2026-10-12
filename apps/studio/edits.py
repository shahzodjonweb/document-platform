"""What a change request asks for, read by rule before any model sees it.

A change is priced, and its page count shown, before it is written. So what it
adds or removes — pages, a plan or a conclusion, pictures, a test — is read
here, the way pages.py reads a new description for its count, and becomes the
draft's options (domain._prepare_draft). The model is then handed the request
with this reading beside it, instead of being told only to "keep the length".
The bot shows no theme picker or page counter for a change: this reading is
the count.

Every reading comes from a real request (tests/test_edit_reading.py): "boshiga
bitta sahifa qo'sh" is a page at the start, "har 1ta slaydga rasm" a picture
on every slide (not a one-slide deck), "testlarni o'chir" no test, "kitoblarda
beriladigan rasmga o'xshasin" drawings rather than photos, and "pdf shaklida
yubor" the same deck as a PDF with nothing to rewrite. A number is a new total
only where it is said to be one ("12 ta slayd bo'lsin"), never where it points
at a slide ("3-slayddagi xato"), and "dizaynni o'zgartirma" keeps the design.

Every pattern starts at a fixed word or at the start of a word, and every gap
between words is bounded, so a pasted essay of 20 000 characters is read in
milliseconds instead of being backtracked over.
"""
import re
from dataclasses import dataclass, field

from .language import normalised
from .pages import QUESTIONS_PER_SLIDE, question_slides

PARTS = ('title_page', 'plan', 'introduction', 'conclusion', 'references')


@dataclass
class Edit:
    total: int | None = None          # a new total of pages or slides, named outright
    delta: int = 0                    # pages or slides added (+) or removed (-)
    parts: list = field(default_factory=list)  # parts asked to be added, from PARTS
    pictures: str | None = None       # 'add' | 'every' | 'remove'
    picture_count: int | None = None
    photo_style: str | None = None    # 'photo' | 'illustration'
    questions: str | None = None      # 'add' | 'remove'
    question_count: int | None = None
    more_questions: bool = False      # question_count is added to the questions the document has
    removed_question_slides: list = field(default_factory=list)  # a deck's question slides removed, from 1
    redesign: bool = False
    expand: bool = False              # more, fuller information
    format: str | None = None         # 'pdf' | 'pptx': the file in another format
    format_only: bool = False         # and nothing else
    structural: bool = False          # pages added, removed, inserted, moved or reordered


# --- Words --------------------------------------------------------------------

I = re.IGNORECASE
# The start of a word. Matching only from there is what keeps every pattern
# linear: a pattern free to start inside a long word retries from each letter.
W = r"(?<![\w'])"
NUMBERS = {
    'a': 1, 'an': 1, 'one': 1, 'another': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6,
    'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
    'bir': 1, 'bitta': 1, 'ikki': 2, 'ikkita': 2, 'uch': 3, 'uchta': 3, "to'rt": 4, "to'rtta": 4,
    'besh': 5, 'beshta': 5, 'olti': 6, 'oltita': 6, 'yetti': 7, 'yettita': 7, 'sakkiz': 8, 'sakkizta': 8,
    "to'qqiz": 9, "to'qqizta": 9, "o'n": 10, "o'nta": 10,
    'один': 1, 'одна': 1, 'одну': 1, 'одного': 1, 'два': 2, 'две': 2, 'три': 3, 'четыре': 4, 'пять': 5,
    'шесть': 6, 'семь': 7, 'восемь': 8, 'девять': 9, 'десять': 10,
    'eleven': 11, 'twelve': 12, 'fifteen': 15, 'twenty': 20, 'yigirma': 20, "o'ttiz": 30,
    'двенадцать': 12, 'пятнадцать': 15, 'двадцать': 20,
}
_SPELLED = '|'.join(re.escape(word) for word in sorted(NUMBERS, key=len, reverse=True))
# Uzbek tens come before the ones: "o'n ikki" is twelve, not two.
TENS = r"(?:o'n|yigirma|o'ttiz)\s+"
COUNT = r"(\d{1,3}|(?:" + TENS + r")?(?:" + _SPELLED + r")(?![\w']))"
NAMED_COUNT = COUNT.replace('(', '(?P<count>', 1)  # the same, read by name where a pattern has other groups
# Uzbek counts with a classifier: "2 ta", "2ta", "2-ta".
TA = r"(?:\s*(?:-\s*)?(?:ta|dona)(?![\w']))?"
# A page or slide in any case. "bet" only in its own forms: "betakror" is a word.
UNIT = (r"(?:slayd\w*|slide\w*|sahifa\w*|varaq\w*|varoq\w*|varag'\w*|varog'\w*"
        r"|bet(?:lar\w*|i|ga|da|ni|ini|iga|ida|dan|lik|li)?(?![\w'])|pages?(?![\w'])"
        r"|слайд\w*|страниц\w*|лист(?:а|ов|ы|ок)?(?![\w']))")
# A page or slide as the object of a verb: "slaydni o'chir", "2 ta slayd qo'sh".
OBJECT = (r"(?:(?:slayd|sahifa|varaq|varoq|bet)(?:lar)?(?:ini|sini|ni|si|i)?(?![\w'])"
          r"|varag'(?:i|ini)?(?![\w'])|varog'(?:i|ini)?(?![\w'])|slides?(?![\w'])|pages?(?![\w']))")
CLAUSE = re.compile(r"[^.!?\n;]+")


def _number(token):
    return int(token) if token.isdigit() else sum(NUMBERS[word] for word in token.lower().split())


def _text(request):
    """The request with one apostrophe, its Uzbek apostrophes put back, and Uzbek typed in Cyrillic put into Latin.

    Russian is left as it is: the Russian patterns read it in Cyrillic.
    """
    from .language import UZBEK_CYRILLIC, UZBEK_CYRILLIC_WORDS, cyrillic_share
    body = normalised(request)
    if cyrillic_share(body) >= 0.5 and (UZBEK_CYRILLIC.search(body) or UZBEK_CYRILLIC_WORDS.search(body)
                                        or UZBEK_VERBS.search(body)):
        from .uzbek import clean_text
        body = normalised(clean_text(body, 'latn'))
    return TOGRI.sub(r"\1'\2'", BARE.sub(lambda match: match.group(0) + "'", body))


# Uzbek is often typed without its apostrophes: "2 ta slayd qoshing", "3
# slaydni ochir", "rasm qoshmang", "bolsin". The words read here get theirs
# back, so every pattern below has one spelling: "2 ta slayd qoshing" was a
# deck of two and "rasm qoshmang" added pictures. Only these words, in these
# forms: "bola" is a child and "bold" is English.
BARE = re.compile(r"(?<![\w'])(?:qo(?=sh|y(?:ing|ib|il\w*|sin|gin|ma\w*|di|adi|ish\w*)?(?![\w']))"
                  r"|o(?=chir|zgar|xsha|rni|tkaz)"
                  r"|bo(?=l(?:sin|ish\w*|sa|di|ib\w*|gan\w*|ma\w*|adi|ar)?(?![\w']))"
                  r"|ko(?=p(?:roq)?(?![\w'])|rinish|chir|paytir|rsat)|so(?=nggi)|yo(?=q(?![\w']))|to(?=liq))", I)
TOGRI = re.compile(r"(?<![\w'])(to)'?(g)'?(?=ri|irla)", I)


# Uzbek in Cyrillic without a letter Russian lacks: "тест туз", "расм бер".
UZBEK_VERBS = re.compile(r"(?<![\w'])(?:туз|тузинг|расм\w*|ёз\w*|тайёрла\w*|ташла\w*|олиб)(?![\w'])", re.IGNORECASE)


# --- Pages added and removed ---------------------------------------------------

# "bitta sahifa qo'sh", "yana 2 ta slayd qo'shing", "2 ta yangi slayd qo'sh",
# "3 ta rasmli slayd qo'sh".
ADD_UZ = re.compile(W + r"(?:(?:yana|qo'shimcha|yangi|alohida)\s+)?" + COUNT + TA
                    + r"\s+(?:(?:yangi|qo'shimcha|alohida|bo'sh|[\w']+li)\s+)?" + OBJECT
                    + r"\s+(?:ham\s+|yana\s+)?(?:qo'sh|qo'y|kirit)(?!ma)\w*", I)
# "yana bir betiga … yoz": one more page, whatever is done with it.
MORE_UZ = re.compile(W + r"yana\s+" + COUNT + TA + r"\s+(?:[\w']+\s+)?" + UNIT, I)
# "yangi slayd qo'sh": one.
NEW_UZ = re.compile(W + r"(?:yangi|qo'shimcha|alohida)\s+" + OBJECT
                    + r"\s+(?:ham\s+)?(?:qo'sh|qo'y|kirit|yarat|och)(?!ma)\w*", I)
# "add one more slide", "add 3 slides", "add another page"; not "add page numbers".
ADD_EN = re.compile(W + r"(?:add|insert|include|append)(?:ing|ed)?\s+(?:" + COUNT + r"\s+)?"
                    r"(?:(?:more|extra|new|additional|blank)\s+)?(?:([\w']+)\s+)?(slides?|pages?)(?![\w'])"
                    r"(?!\s+(?:numbers?|numbering|transitions?|notes|titles?|headers?|footers?|breaks?|layouts?"
                    r"|designs?|backgrounds?|borders?))", I)
MORE_EN = re.compile(W + COUNT + r"\s+(?:more|extra|additional)\s+(slides?|pages?)(?![\w'])", I)
# "добавь 2 слайда", "добавь ещё один слайд", "ещё 2 слайда".
ADD_RU = re.compile(W + r"(?:добав|встав)\w*\s+(?:ещ[её]\s+)?(?:" + COUNT + r"\s+)?"
                    r"(?:(?:нов|дополнительн|отдельн|пуст)\w*\s+)?(?:([\w']+)\s+)?(слайд\w*|страниц\w*|лист(?:а|ов|ы)?)"
                    r"(?![\w'])", I)
MORE_RU = re.compile(W + r"ещ[её]\s+" + COUNT + r"\s+(?:слайд|страниц|лист)\w*", I)
ADDING = (ADD_UZ, MORE_UZ, NEW_UZ, ADD_EN, MORE_EN, ADD_RU, MORE_RU)

# Slides named by number: "3- va 4-", "5-7", "5–7", "5, 6 va 7-", "3 and 4", "5 to 7", "5 и 6".
SEP = (r"(?:\s*[-–]\s*(?:(?:,|va|hamda|и|and)\s*)?|\s*[,&]\s*(?:(?:va|and|и)\s+)?"
       r"|\s+(?:va|hamda|and|и|to|through|по)\s+)")
LISTED = r"\d{1,3}(?:" + SEP + r"\d{1,3}){1,8}"
NUMBERED = r"\d{1,3}(?:" + SEP + r"\d{1,3}){0,8}(?![\w'])"
# A number right after a dash ends a range, it does not count slides: "5-7 slaydlarni" is not seven.
NOT_IN_RANGE = r"(?<![-–])(?<![-–]\s)"
# "oxirgi slaydni olib tashla", "3-slaydni o'chir", "3- va 4-slaydlarni o'chir", "5-7 slaydlarni o'chir".
REMOVE_UZ = re.compile(W + r"(?:(?P<first>oxirgi|so'nggi|birinchi|boshidagi|oxiridagi)\s+)?"
                       r"(?:" + NOT_IN_RANGE + NAMED_COUNT + TA + r"\s+)?"
                       r"(?P<listed>" + LISTED + r"\s*(?:[-–]\s*)?|\d{1,3}\s*[-–]\s*)?(?P<unit>" + OBJECT + r")\s+"
                       r"(?:[\w']+\s+)?(?:o'chir|olib\s+tashla|chiqarib\s+tashla|tashla|olib\s+qo'y)(?!ma)\w*", I)
# "remove the last two slides", "delete slide 3", "remove slides 3 and 4", "remove slides 5-7".
REMOVE_EN = re.compile(W + r"(?:remove|delete|drop|cut|take\s+out|get\s+rid\s+of)\s+(?:the\s+)?"
                       r"(?:(?P<first>last|first|final)\s+)?(?:" + NAMED_COUNT + r"\s+)?"
                       r"(?:(?P<first2>last|first|final)\s+)?(?:(?P<filler>[\w']+)\s+)?"
                       r"(?P<unit>slides?|pages?)(?![\w'])"
                       r"(?:\s+(?:no\.?\s*|number\s+|#\s*)?(?P<after>" + NUMBERED + r"))?", I)
# "удали последний слайд", "удали последние 2 слайда", "удали слайд 3", "удали 5 и 6 слайды", "удали слайды 5-7".
REMOVE_RU = re.compile(W + r"(?:удали|убери|убрать|удалить|выкин|выброс)\w*\s+(?:(?P<first>последн\w*|перв\w*)\s+)?"
                       r"(?:(?P<listed>" + LISTED + r"|\d{1,3}(?=\s*-\s*(?:й|ий|ый|ой)(?![\w'])))"
                       r"\s*(?:-\s*(?:й|ий|ый|ой|е|и)(?![\w']))?\s+|" + NAMED_COUNT + r"\s+)?"
                       r"(?:(?P<first2>последн\w*|перв\w*)\s+)?(?:(?P<filler>[\w']+)\s+)?"
                       r"(?P<unit>слайд\w*|страниц\w*|лист(?:а|ов|ы)?)(?![\w'])"
                       r"(?:\s+(?:№\s*)?(?P<after>" + NUMBERED + r"))?", I)
# A page added "at the beginning" may be a title page: "Boshiga bitta sahifa qo'sh … deb yoz" (_title_page).
AT_START = re.compile(r"(?<![\w'])(?:boshiga|boshida|oldiga|eng\s+oldiga|birinchi\s+bo'lib"
                      r"|at\s+the\s+(?:beginning|start|front)|в\s+(?:самое\s+)?начал\w*|в\s+начале)(?![\w'])", I)
# What makes it one: lines dictated for it ("… deb yoz", "ismimni yoz", "TAYYORLADI: …",
# "with my name", "выполнила …"), or a title page named outright.
DICTATED = re.compile(W + r"(?:deb\s+(?:yoz|qo'y|kirit)\w*|ism(?:im|imni|imiz|ing|ingni|ini)?(?![\w'])"
                      r"|ism-?(?:sharif|familiya)\w*|familiya\w*|tayyorladi|bajardi|qabul\s+qildi|tekshirdi"
                      r"|topshirdi|titul\w*|muqova\w*"
                      r"|(?:my|our|his|her|full)\s+names?|prepared\s+by|submitted\s+by|presented\s+by|done\s+by"
                      r"|title\s+(?:page|slide)|cover\s+(?:page|slide)"
                      r"|мо[её]\s+имя|фио|фамили\w*|выполнил\w*|подготовил\w*|проверил\w*|титульн\w*|обложк\w*)", I)
# What a page added at the start is about, when it is not a title page: "unda mavzuning
# dolzarbligi haqida yoz", "a slide about the causes", "страницу о причинах".
ABOUT = re.compile(W + r"(?:haqida\w*|to'g'risida\w*|about|regarding|про|о|об|посвящ\w*)(?![\w'])", I)
# Moving pages round changes no count, but the model must know the order changed.
REORDER = re.compile(W + r"(?:(?:o'rni|o'rnini|joyi|joyini|tartibi|tartibini|ketma-ketligini)\s+(?:[\w']+\s+)?"
                     r"(?:almashtir|o'zgartir)\w*|(?:oldinga|keyinga|oxiriga|oldiga)\s+(?:o'tkaz|ko'chir|sur)\w*"
                     r"|(?:move|swap|reorder|rearrange)(?:s|d|ed|ing)?(?![\w'])|поменя\w*\s+местами|перестав\w*"
                     r"|перенес\w*|перемест\w*)", I)

# --- Parts ---------------------------------------------------------------------

# Not in a case that places something in a part ("xulosaga qo'sh", "kirishda"):
# that changes the part, it does not ask for one.
PART_WORDS = (
    ('title_page', r"titul(?!ga|da)\w*|muqova(?!ga|da)\w*|title\s+(?:page|slide)|cover\s+(?:page|slide)"
                   r"|титульн\w*(?:\s+лист\w*)?|обложк\w*"),
    ('plan', r"reja(?!lashtir|ga|da|dan|siga|sida)\w*|mundarija(?!ga|da)\w*|plan(?![\w'])|agenda|table\s+of\s+contents"
             r"|план(?:а|у)?(?![\w'])|содержани\w*|оглавлени\w*"),
    ('introduction', r"kirish(?!ga|da|dan|ib|ish)\w*|introduction|intro(?![\w'])|введени\w*|вступлени\w*"),
    ('conclusion', r"xulosa(?!ga|da|dan|siga|sida)\w*|conclusions?(?![\w'])|заключени\w*|вывод(?:ы|ов)(?![\w'])"),
    ('references', r"(?:foydalanilgan\s+)?adabiyotlar\w*|foydalanilgan\s+(?:adabiyot|manba)\w*|manbalar\s+ro'yxat\w*"
                   r"|references|bibliography|works\s+cited|list\s+of\s+sources"
                   r"|список\s+(?:использованн\w+\s+)?(?:литератур|источник)\w*|использованн\w+\s+литератур\w*"),
)
PART_PATTERNS = [(name, re.compile(W + r"(?:" + words + r")", I)) for name, words in PART_WORDS]
# A heading that already is one of those parts: its first word, give or take
# an ending ("Xulosalar", "Выводы"), so "Planetalar" is not a plan.
HEADING_WORDS = {
    'title_page': r"titul|title\s+page|титульн\w*",
    'plan': r"reja|plan|agenda|mundarija|contents|table\s+of\s+contents|план|содержание|оглавление",
    'introduction': r"kirish|introduction|введение|вступление",
    'conclusion': r"xulosa|conclusion|summary|yakun|заключение|вывод|итог",
    'references': (r"foydalanilgan|adabiyot|manba|references|bibliography|sources|works\s+cited"
                   r"|список\s+литератур|литература|источник"),
}
HEADINGS = {name: re.compile(r"(?:" + words + r")\w{0,4}(?![\w'])", I) for name, words in HEADING_WORDS.items()}

# --- Removing, changing, adding: what is said around a thing --------------------

_STOP = r"[^,.!?;\n]"
# Taken away: "rasmni o'chir", "test kerak emas", "remove the pictures".
_GONE_AFTER = (r"o'chir(?!ma)|olib\s+tashla(?!ma)|chiqarib\s+tashla|tashla(?!ma)|olib\s+qo'y(?!ma)|kerak\s+emas"
               r"|kerakmas|keragi\s+yo'q|bo'lmasin")
_GONE_BEFORE = r"remove|delete|drop|get\s+rid\s+of|take\s+out|убери\w*|удали\w*|убрать"
# Not wanted: "rasm qo'shmang", "rasmlar shart emas", "rasmlarga hojat yo'q", "картинки не нужны", "no pictures".
_UNWANTED_AFTER = (r"qo'yma(?:ng|sin)?(?![\w'])|qo'shma(?:ng|sin)?(?![\w'])|solma|ishlatma|shart\s+emas|shartmas"
                   r"|hojat\w*\s+yo'q|zarur\s+emas|zarurmas|не\s+(?:нужн|надо)\w*|(?:are\s+|is\s+)?not\s+needed"
                   r"|aren't\s+needed|unnecessary")
_UNWANTED_BEFORE = (r"without|no|no\s+need\s+(?:for|of)|don't\s+(?:add|use|put|include|want)"
                    r"|do\s+not\s+(?:add|use|put|include|want)|без|никаких|не\s+(?:нужн|надо|добавля|став|вставля)\w*")
_AFTER = _STOP + r"{0,20}?(?<![\w'])(?:"
_BEFORE = r"(?<![\w'])(?:"
_BEFORE_END = r")\s+(?:(?:the|all|any|все|эти)\s+)?(?:[\w']+\s+)?$"
AFTER_REMOVE = re.compile(_AFTER + _GONE_AFTER + '|' + _UNWANTED_AFTER + ')', I)
BEFORE_REMOVE = re.compile(_BEFORE + _GONE_BEFORE + '|' + _UNWANTED_BEFORE + _BEFORE_END, I)
AFTER_GONE = re.compile(_AFTER + _GONE_AFTER + ')', I)
BEFORE_GONE = re.compile(_BEFORE + _GONE_BEFORE + _BEFORE_END, I)
# "rasmsiz", "rasmlarsiz", "testsiz", "savolsiz": without them.
WITHOUT = re.compile(r"siz$", I)
AFTER_CHANGE = re.compile(_STOP + r"{0,20}?(?<![\w'])(?:qisqartir|kengaytir|o'zgartir|tuzat|to'g'irla|yaxshila"
                          r"|qayta\s+yoz|tahrir)\w*", I)
BEFORE_CHANGE = re.compile(r"(?<![\w'])(?:expand|shorten|rewrite|change|fix|improve|edit|update|extend|сократи|расширь"
                           r"|измени|исправь|перепиши|дополни)\w*\s+(?:(?:the|my|your)\s+)?(?:[\w']+\s+)?$", I)
AFTER_ADD = re.compile(_STOP + r"{0,25}?(?<![\w'])(?:qo'sh|qo'y|joyla|kirit)(?!ma)\w*", I)
BEFORE_ADD = re.compile(r"(?<![\w'])(?:add|include|insert|put|place|use|добав\w*|встав\w*|помест\w*)\s+"
                        r"(?:(?:the|some|a|an|more|ещё|еще)\s+)?(?:[\w']+\s+)?$", I)


def _before(pattern, clause, start, reach=40):
    return bool(pattern.search(clause[max(0, start - reach):start]))


def _after(pattern, clause, end):
    return bool(pattern.match(clause, end))


# --- Pictures -----------------------------------------------------------------

PICTURE = re.compile(W + r"(?:rasm(?!iy|an|lashtir|ona)\w*|surat\w*|fotosurat\w*|foto\w*|tasvir(?!la)\w*"
                     r"|chizma(?!chilik)\w*|illyustrats\w*|pictures?|images?|photos?|photographs?|illustrations?"
                     r"|drawings?"
                     r"|картин\w*|фото\w*|изображени\w*|рисун\w*|иллюстрац\w*)(?![\w'])", I)
# On every slide: "har bir slaydda", "har 1ta slaydga", "hamma betda", "every slide".
EVERY = re.compile(W + r"(?:har\s+(?:bir\s+|1\s*(?:-\s*)?ta\s+|bitta\s+)?(?:slayd|sahifa|bet|varaq|varoq|list)\w*"
                   r"|(?:hamma|barcha|butun)\s+(?:slayd|sahifa|bet|varaq|varoq)\w*"
                   r"|(?:slayd|sahifa|varaq|varoq)\w*\s+(?:hammasi|barchasi)\w*"
                   r"|(?:every|each)\s+(?:single\s+)?(?:slide|page)s?(?![\w'])"
                   r"|all\s+(?:of\s+)?(?:the\s+)?(?:slides|pages)(?![\w'])"
                   r"|кажд\w+\s+(?:слайд|страниц)\w*|(?:всех|все)\s+(?:слайд|страниц)\w*)", I)
PICTURE_ALT = (r"(?:rasm(?!iy|an|lashtir|ona)|surat|foto|tasvir(?!la)|chizma(?!chilik)|illyustrats|picture|image"
               r"|photo|illustration|drawing|картин|фото|изображени|рисун|иллюстрац)")
# "4 ta kichik rasm", "3 pictures"; "rasmini … to'rtta qo'y". Not "3 ta rasmli slayd":
# three slides, with pictures.
PICTURE_COUNT = re.compile(W + COUNT + TA + r"\s+(?:([\w']+)\s+)?" + PICTURE_ALT + r"(?!(?:lar)?li(?![\w']))", I)
PICTURED = re.compile(W + COUNT + TA + r"\s+" + PICTURE_ALT + r"(?:lar)?li\s+(?:slayd|sahifa|bet|varaq|varoq)", I)
EACH = re.compile(r"(?<![\w'])(?:har|each|every|кажд\w*)\s+$", I)
# "bir nechta rasm", "a few pictures": some, not one.
VAGUE = re.compile(r"(?:nechta|necha|qancha|few|several|couple|some|несколько|пару)", I)
COUNT_AFTER = re.compile(_STOP + r"{0,30}?(?<![\w'])" + COUNT + TA + r"\s+(?:qo'y|qo'sh|bo'lsin|kerak)\w*", I)
# Pictures the document has, made bigger, moved or swapped: not more pictures.
RESHAPE_AFTER = re.compile(_STOP + r"{0,30}?(?<![\w'])(?:kattaroq|kichikroq|kattalashtir|kichraytir|o'zgartir|almashtir"
                           r"|tuzat|to'g'irla|joyini|joylashuvini|aniqroq|tiniqroq|bigger|smaller|larger)\w*", I)
RESHAPE_BEFORE = re.compile(r"(?<![\w'])(?:make|change|replace|fix|resize|move|enlarge|shrink|увеличь|уменьши|измени"
                            r"|замени|поменяй|перемести)\w*\s+(?:(?:the|all|все)\s+)?(?:[\w']+\s+)?$", I)
# A picture asked for on named slides: "3-slaydga rasm", "slide 3".
TARGET = re.compile(W + r"(?:(\d{1,3})\s*-\s*(?:slayd|sahifa|bet|varaq)\w*|(?:slide|page)\s+(\d{1,3})(?![\w'])"
                    r"|(?:слайд|страниц)\w*\s+(?:№\s*)?(\d{1,3})(?![\w']))", I)
# A count of the slides that get something is not a total: "3 ta slaydga rasm qo'sh".
PLACES = re.compile(W + COUNT + TA + r"\s*(?:slayd|sahifa|bet|varaq|varoq)\w*?(?:ga|da|dagi)(?![\w'])"
                    r"|(?<![\w'])(?:to|on|for|in)\s+" + COUNT + r"\s+(?:of\s+the\s+)?(?:slides|pages)(?![\w'])"
                    r"|(?<![\w'])на\s+" + COUNT + r"\s+(?:слайд|страниц)\w*", I)

# Drawn, not photographed: "kitoblarda beriladigan rasmga o'xshasin", "chizma",
# "illustrations". Photographed: "realga o'xshasin", "haqiqiy rasmlar".
DRAWN = re.compile(W + r"(?:kitob(?:lar)?(?:da|dagi)\w*(?:\s+[\w']+){0,2}\s+(?:rasm|surat)\w*|darslik\w*"
                   r"|chizma(?!chilik)\w*|chizilgan\w*|illyustrats\w*|multfilm\w*|multik\w*|animatsion\w*"
                   r"|drawings?|drawn|illustrat\w*"
                   r"|cartoon\w*|sketch\w*|рисун\w*|рисованн\w*|нарисованн\w*|иллюстрац\w*|мультяшн\w*"
                   r"|мультипликац\w*)", I)
REAL = re.compile(W + r"(?:real(?:ga|istik|istic|ni|dek|day)?(?![\w'])|haqiqiy\s+(?:rasm|surat|foto)\w*"
                  r"|(?:rasm|surat)\w*\s+(?:haqiqiy|tabiiy)\w*|tabiiy\w*(?=\s+(?:o'xsha|rasm|surat|foto|ko'rin))"
                  r"|photographs?|photo-?realistic|реалистичн\w*|реальн\w*|настоящ\w*\s+(?:фото|картин|изображ)\w*"
                  r"|живы\w*\s+фото\w*|фотореалист\w*)", I)
# Childish pictures, asked away, mean real ones: "Yosh bolacha rasm qo'yma".
CHILDISH = re.compile(W + r"(?:yosh\s+bola\w*|bolalarcha|bolacha|childish|kiddy|детск\w*)", I)
STYLE_AFTER_NOT = re.compile(_STOP + r"{0,25}?(?<![\w'])(?:emas|bo'lma|qo'yma|qo'shma|o'xshama|kerakmas|ishlatma"
                             r"|solma)\w*", I)
STYLE_BEFORE_NOT = re.compile(r"(?<![\w'])(?:no|not|don't|without|не|без|никаких)\s+(?:[\w']+\s+)?$", I)

# --- Questions ----------------------------------------------------------------

QUESTION = re.compile(W + r"(?:savol\w*|test(?!osteron)\w*|quiz\w*|questions?(?![\w'])|вопрос\w*|тест\w*"
                      r"|викторин\w*)", I)
QUESTION_ALT = r"(?:savol|test(?!osteron)|quiz|question|вопрос|тест|викторин)"
# What a page count is for, right after it: "yana 3 ta slaydga rasm". Not past
# "va": "yana 3 bet qo'sh va rasmlar bo'lsin" is three pages, and pictures.
CONJUNCTION = r"(?<![\w'])(?:va|hamda|and|и)(?![\w'])"
FOR_THING = re.compile(r"(?:(?!" + CONJUNCTION + r")" + _STOP + r"){0,25}?" + W + r"(?:" + PICTURE_ALT + r"|"
                       + QUESTION_ALT + r")", I)
NOT_UNIT = r"(?!(?:slayd|sahifa|bet|varaq|varoq|slide|page|слайд|страниц)\w*\s)"
QUESTION_COUNT = re.compile(W + r"(?:(yana|more|another|qo'shimcha|ещ[её])\s+)?" + COUNT + TA
                            + r"\s+(?:(?:more|extra|additional|new|yangi|qo'shimcha)\s+)?"
                            + r"(?:" + NOT_UNIT + r"[\w']+\s+)?" + QUESTION_ALT, I)
QUESTION_ADD_AFTER = re.compile(_STOP + r"{0,15}?(?<![\w'])(?:tuz|qo'sh|qo'y|bo'lsin|bo'lishi|kerak(?!\s*emas)"
                                r"|tayyorla|qilib\s+ber)(?!ma)\w*", I)
QUESTION_ADD_BEFORE = re.compile(r"(?<![\w'])(?:add|include|make|create|write|generate|prepare|append|добав\w*"
                                 r"|сделай|составь|включи\w*|подготовь|напиши)\s+(?:(?:a|an|the|some|short|new)\s+)?"
                                 r"(?:[\w']+\s+)?$", I)
# Questions added to those the document has: "10 ta savol qo'sh" on ten is twenty.
# Said any other way the number is the test's size: "savollar 5 ta bo'lsin".
MORE_AFTER = re.compile(_STOP + r"{0,15}?(?<![\w'])(?:qo'sh|qo'y|kirit|joyla)(?!ma)\w*", I)
MORE_BEFORE = re.compile(r"(?<![\w'])(?:add|include|insert|append|добав\w*|встав\w*)\s+(?:[\w']+\s+){0,2}$", I)
# The test cut or grown to a size: "savollarni 5 taga qisqartir", "savollar sonini 5 taga kamaytir",
# "reduce the questions to 5", "сократи вопросы до 5".
QUESTIONS_TO = re.compile(_STOP + r"{0,25}?" + W + COUNT + r"\s*(?:(?:-\s*)?ta)?(?:ga|gacha)\s+(?:[\w']+\s+)?"
                          r"(?:qisqartir|kamaytir|qoldir|tushir|yetkaz|ko'paytir|oshir|keltir)\w*"
                          r"|\s+(?:(?:down|up)\s+)?(?:to|до)\s+" + COUNT, I)
CUT_BEFORE = re.compile(r"(?<![\w'])(?:cut|reduce|trim|shorten|limit|bring|increase|raise|сократи\w*|уменьши\w*"
                        r"|увеличь\w*|доведи\w*|урежь\w*)\s+(?:(?:the|number|of|количество)\s+){0,3}$", I)
# "savol so'rash slaydi 2 bet bo'libdi. shuni 1 bet qil": the questions on one slide.
FIT = re.compile(W + COUNT + TA + r"\s*(?:bet|slayd|sahifa|slide|page|слайд|страниц)\w*\s+(?:ga\s+)?"
                 r"(?:qil(?:ing|sin|ib\s+ber)?|bo'lsin|sig'(?:sin|dir)\w*|joyla\w*|make|сделай)(?![\w'])", I)
FIT_REACH = 90
# The deck as it is now is not the deck asked for: "12 ta slayd bo'libdi", "8 ta slayd keldi",
# "instead of 9 slides". "10 ta kerak edi" is what was asked for, and wins.
STATE = re.compile(W + COUNT + TA + r"\s*(?:[\w']+\s+)?" + UNIT + r"\s+(?:bo'libdi|bo'lib\s+qolibdi|bo'lgan|chiqibdi"
                   r"|chiqdi|chiqqan|bo'ldi|edi|ekan|o'rniga|keldi|kelgan|kelibdi|kepti|bor|mavjud|emas)(?![\w'])"
                   r"|(?<![\w'])(?:instead\s+of|has|have|had|came\s+out\s+(?:as|at|to)|got|there\s+are|is\s+now"
                   r"|are\s+now)\s+" + COUNT + r"\s+(?:slides|pages)(?![\w'])"
                   r"|(?<![\w'])(?:вместо|получил\w*|вышл\w*|сейчас|было|есть)\s+" + COUNT
                   + r"\s+(?:слайд|страниц|лист)\w*", I)

# --- A new total ----------------------------------------------------------------

# A change names a new size in so many words, and only then is a number its
# total: "12 ta slayd bo'lsin", "10 varoqlik qil", "12talik qil", "slaydlarni 8
# taga kamaytir", "make it 12 slides", "сделай 15 слайдов". Read like a new
# description's count, any number beside a slide was one: "fix typos on slide 2
# and slide 6" cut a ten-slide deck to two, "oxirgi 3 ta slaydni kengaytir" to three.
PAGE = r"(?:slayd|sahifa|varaq|varoq|bet|list)"
SIZE_VERB = (r"(?:bo'lsin|bo'lishi|bo'lsa|kerak(?!\s+emas)|qil(?:ing|sin|ib|gin|ish|in\w*)?|tayyorla\w*|yasa\w*)"
             r"(?![\w'])")
# The whole work, named after its size: "10 betli PowerPoint taqdimoti".
WORK = r"(?:taqdimot|prezentats|referat|hujjat|mustaqil|powerpoint|slayd)\w*"
TO_SIZE_VERB = r"(?:qisqartir|kamaytir|qoldir|tushir|yetkaz|ko'paytir|oshir|keltir|uzaytir)\w*"
_ABOUT_EN = r"(?:(?:about|around|exactly|only|just|at\s+least|at\s+most)\s+)?"
_DECK_EN = r"(?:it|this|that|the\s+[\w']+|my\s+[\w']+)"
_UNIT_EN = r"(?:slides?|pages?)(?![\w'])"
_UNIT_RU = r"(?:слайд|страниц|лист)\w*(?![\w'])"
_CUT_RU = r"(?:сократи|уменьши|урежь|сожми|увеличь|расширь|доведи|дополни)\w*"
_DOCUMENT_RU = r"(?:е[её]|его|презентаци\w*|документ\w*|реферат\w*|слайд\w*|страниц\w*)"
_CLAUSE_END = r"(?=\s*(?:[,.!?;\n]|$))"
TOTALS = [re.compile(W + pattern, I) for pattern in (
    # "12 ta slayd bo'lsin", "6 ta slayd kerak", "10 ta slayd qilib ber", "12 ta slayddan iborat bo'lsin".
    COUNT + TA + r"\s*" + PAGE + r"(?:lar)?(?:dan\s+iborat)?\s+(?:(?:atrofida|ham|faqat|jami|taxminan)\s+)?"
    + SIZE_VERB,
    # "10 varoqlik qil", "10 betli PowerPoint taqdimoti", "10 varoqlik va kengroq".
    COUNT + r"\s*(?:-\s*)?(?:ta\s*)?" + PAGE + r"(?:li|lik)(?![\w'])(?:" + _CLAUSE_END + r"|\s+(?:" + SIZE_VERB
    + r"|(?:va|and)(?![\w'])|" + WORK + r"))",
    # "o'sha men so'ragan 9ta slayd", "jami 12 ta slayd", "12talik qil", "10 slaydga qisqartir".
    r"so'ragan\s+(?:[\w']+\s+)?" + COUNT + TA + r"\s*" + PAGE + r"(?:lar)?(?![\w'])",
    r"(?:jami|umumiy)\s+" + COUNT + TA + r"\s*" + PAGE,
    r"(\d{1,3})\s*(?:-\s*)?talik\s+(?:qil|bo'l|kerak)",
    COUNT + r"\s*(?:ta\s*)?" + PAGE + r"(?:lar)?(?:ga|gacha)\s+(?:[\w']+\s+)?" + TO_SIZE_VERB,
    # "make it 12 slides", "make the deck a 10-page document", "it should be 10 pages", "I need 10 slides";
    # not "I need 3 slides about the war".
    r"(?:make|turn)\s+" + _DECK_EN + r"\s+(?:into\s+)?(?:(?:a|an)\s+)?" + _ABOUT_EN + COUNT + r"\s*(?:-\s*)?"
    + _UNIT_EN,
    r"(?:should|must|has\s+to|needs?\s+to|ought\s+to|to)\s+be\s+" + _ABOUT_EN + COUNT + r"\s*(?:-\s*)?" + _UNIT_EN,
    r"need\s+" + _ABOUT_EN + COUNT + r"\s+" + _UNIT_EN + r"(?!\s+(?:about|on|for|with|that|which|to|of)(?![\w']))",
    # "cut it to 8 slides", "shorten the deck to 8".
    r"(?:cut|shorten|reduce|trim|bring|condense|expand|extend|increase|lengthen)\s+(?:" + _DECK_EN + r"\s+)?"
    r"(?:(?:down|up)\s+)?to\s+" + _ABOUT_EN + COUNT + r"\s+" + _UNIT_EN,
    r"(?:cut|shorten|reduce|trim|bring|condense|expand|extend|increase|lengthen)\s+(?:it|this|the\s+(?:deck"
    r"|presentation|document|slides|pages|essay|paper))\s+(?:(?:down|up)\s+)?to\s+" + COUNT + _CLAUSE_END,
    # "the deck has 12 slides, make it 10".
    r"(?:make|turn)\s+(?:it|this|the\s+(?:deck|presentation|document))\s+(?:into\s+)?" + COUNT + _CLAUSE_END,
    # "Same document but in 5 pages", "put it in 8 slides"; not "fix the typos in 3 slides".
    r"(?:but|same\s+[\w']+|it|this|everything|fit)\s+(?:in|into|on)\s+" + _ABOUT_EN + COUNT + r"\s+" + _UNIT_EN,
    # "12 slides in total", "10 slides instead of 12", "leave only 8 slides", "number of slides: 12".
    COUNT + r"\s+(?:slides|pages)\s+(?:in\s+total|total|overall|altogether|in\s+all|instead\s+of)(?![\w'])",
    r"(?:total\s+of|leave\s+(?:only|just)|keep\s+(?:only|just))\s+" + COUNT + r"\s+(?:slides|pages)(?![\w'])",
    r"(?:number\s+of\s+(?:slides|pages)|(?:slide|page)\s+count)\s*(?::|-|–|=|should\s+be|to)\s*" + COUNT
    + r"(?![\w'])",
    # "сделай 15 слайдов", "нужно 10 слайдов", "сделай презентацию на 10 слайдов"; not "нужно 3 слайда про войну".
    r"(?:сдела\w*|переделай\w*|нужн\w*|надо|хочу|должн\w*\s+быть|пусть\s+будет)\s+(?:" + _DOCUMENT_RU + r"\s+)?"
    r"(?:из\s+|на\s+)?(?:(?:всего|ровно|примерно|около)\s+)?" + COUNT + r"\s+" + _UNIT_RU
    + r"(?!\s+(?:про|о|об|с|со|для|на)(?![\w']))",
    # "сократи до 8 слайдов", "сократи презентацию до 8", "всего 12 слайдов", "оставь 8 слайдов".
    _CUT_RU + r"\s+(?:[\w']+\s+){0,2}?до\s+" + COUNT + r"\s+" + _UNIT_RU,
    _CUT_RU + r"\s+" + _DOCUMENT_RU + r"\s+до\s+" + COUNT + _CLAUSE_END,
    r"(?:всего|итого|ровно|оставь|оставить)\s+(?:только\s+)?" + COUNT + r"\s+" + _UNIT_RU,
    COUNT + r"\s+" + _UNIT_RU + r"\s+вместо(?![\w'])",
    r"количеств\w*\s+" + _UNIT_RU + r"\s*(?:[:\-–—]\s*|до\s+)?" + COUNT + r"(?![\w'])",
    # "Sahifalar soni 20 ta", "slaydlar sonini 10 taga yetkaz"; not "slaydlar soni 12 ta bo'libdi".
    PAGE + r"\w*\s+(?:soni|sonini|miqdori|miqdorini)\s*(?:[:\-–]\s*)?" + COUNT
    + r"(?!\s*(?:-\s*)?ta\s+(?:bo'libdi|bo'lgan|chiqibdi|chiqdi|bo'ldi|edi|ekan|keldi|kelgan|bor)(?![\w']))",
)]
# With no noun, only after one: "slaydlarni 8 taga kamaytir", "8 ta slayd keldi, 10 ta kerak edi".
NOUNLESS = re.compile(W + COUNT + r"\s*(?:-\s*)?ta(?:(?:ga|gacha)\s+(?:[\w']+\s+)?" + TO_SIZE_VERB
                      + r"|(?:dan)?\s+(?:bo'lsin|bo'lishi|kerak(?!\s+emas)|qil\w*)(?![\w']))", I)
UNIT_BEFORE = re.compile(r"(?<![\w'])(?:" + PAGE + r"|slide|page)(?:lar|s)?(?:ni|i|im|imiz|ingiz)?"
                         r"(?:\s+(?:soni|sonini|miqdori))?[\s,:;-]+(?:[\w']+[\s,:;-]+){0,2}$", I)
# A request that is only a size: "12 ta slayd.", "10 slides please".
ONLY_SIZE = re.compile(r"\s*(?:(?:jami|faqat|iltimos|please|only|всего|только)\s+)*" + COUNT + TA + r"\s*(?:"
                       + PAGE + r"(?:lar)?|slides|pages|" + _UNIT_RU + r")(?:\s+(?:iltimos|please|пожалуйста"
                       r"|in\s+total|total|всего))?\s*", I)
# Counts that are not a new size, taken out before one is looked for.
NOT_TOTALS = (
    STATE,
    # "3-slayd", "3-slayddagi", "5-7-slaydlar", "5, 6 va 7-slaydlarni", "5-7 slaydlarni"; not "10-betlik", a size.
    re.compile(W + r"(?:\d{1,3}(?:" + SEP + r"\d{1,3}){0,8}\s*[-–]\s*" + PAGE + r"(?!(?:lar)?(?:lik|li)(?![\w']))[\w']*"
               r"|" + LISTED + r"\s+" + PAGE + r"[\w']*"
               # "slide 2", "slides 3 and 4", "slides 5-7", "the 3rd slide".
               r"|(?:slides?|pages?)\s+(?:no\.?\s*|number\s+|#\s*)?" + NUMBERED
               + r"|\d{1,3}(?:st|nd|rd|th)\s+(?:slide|page)s?(?![\w'])"
               # "слайд 3", "слайды 5-7", "5 и 6 слайды", "3-й слайд", "на 3 слайдах".
               r"|" + _UNIT_RU + r"\s+(?:№\s*)?" + NUMBERED
               + r"|" + LISTED + r"\s*(?:-?\s*[а-я]{1,3})?\s+" + _UNIT_RU
               + r"|\d{1,3}\s*-\s*(?:й|ий|ый|ой|ем|ом|ей|му|го|я|е|ю)\s+" + _UNIT_RU
               + r"|на\s+" + COUNT + r"\s+(?:слайд|страниц|лист)\w*ах"
               # "3 ta slaydda", "3 ta slayddagi": the slides something is on.
               r"|" + COUNT + TA + r"\s*" + PAGE + r"(?:lar)?(?:da|dagi)(?![\w']))", I),
    # "oxirgi 3 ta slaydni", "the first 3 slides", "первые 3 слайда".
    re.compile(W + r"(?:birinchi|oxirgi|so'nggi|dastlabki|boshidagi|oxiridagi|keyingi|first|last|final|next"
               r"|initial|перв\w*|последн\w*|начальн\w*|следующ\w*)\s+" + COUNT + TA + r"\s*(?:[\w']+\s+)?" + UNIT, I),
    # The document as it is: "12 slaydli taqdimotimga", "10 ta slayddan iborat taqdimotga".
    re.compile(W + COUNT + TA + r"\s*(?:-\s*)?" + PAGE + r"(?:lar)?(?:li|lik|dan\s+iborat)\s+"
               r"(?:(?!(?:va|and)(?![\w']))[\w']+\s+){0,2}?[\w']+(?:ga|ka|qa|da|dagi|ni|dan|ning|gacha)(?![\w'])", I),
)


def _total(body, blank):
    """The new total of pages or slides a change names in so many words, else None."""
    text = _blank(body, blank + [match.span() for pattern in NOT_TOTALS for match in pattern.finditer(body)])
    found = [(match.start(), next(group for group in match.groups() if group))
             for pattern in TOTALS for match in pattern.finditer(text)]
    found += [(match.start(), match.group(1)) for match in NOUNLESS.finditer(text)
              if _before(UNIT_BEFORE, body, match.start())]
    found += [(start, size.group(1)) for start, clause in _clauses(text)
              for size in [ONLY_SIZE.fullmatch(clause)] if size]
    total = _number(min(found)[1]) if found else None
    return total if total and total >= 2 else None


# --- A new look, more information, another file -------------------------------

REDESIGN = re.compile(W + r"(?:"
                      r"dizayn\w*\s+(?:[\w']+\s+){0,2}?(?:o'zgartir|almashtir|yangila|boshqa|chiroyli|zamonaviy"
                      r"|yaxshila|yaxshiroq|qil|bo'lsin)\w*"
                      r"|(?:boshqa|yangi|chiroyli|zamonaviy|yaxshiroq|zo'r|ajoyib|qiziqarli|go'zal)\s+(?:[\w']+\s+)?"
                      r"dizayn\w*"
                      r"|(?:orqa\s+)?fon(?:i|ni|ini|lar\w*)?\s+(?:[\w']+\s+)?(?:o'zgartir|almashtir|boshqa|yangila)\w*"
                      r"|boshqa\s+(?:[\w']+\s+)?fon(?:i|ni|ini|lar\w*|da|ga)?(?![\w'])"
                      r"|(?:varaq|varoq|slayd|sahifa|bet)\w*\s+(?:[\w']+\s+){0,3}?bir\s+[xh]il\s+(?:qil|bo'l|ko'rin)\w*"
                      r"|bir\s+[xh]il\s+(?:dizayn|ko'rinish|uslub|fon)\w*"
                      r"|daftar\w*\s+(?:[\w']+\s+)?(?:varag'|varog'|varaq|varoq|sahifa|qog'oz|list)\w*"
                      r"|(?:shablon|uslub|stil)\w*\s+(?:[\w']+\s+)?(?:o'zgartir|almashtir|boshqa)\w*"
                      r"|(?:change|new|different|another|better|nicer|fresh|modern|redo|update|improve)\s+(?:the\s+)?"
                      r"(?:[\w']+\s+)?(?:design|theme|background|template|look)s?(?![\w'])"
                      r"|redesign\w*"
                      r"|(?:make|have)\s+all\s+(?:of\s+)?(?:the\s+)?(?:slides|pages)\s+(?:look\s+)?(?:the\s+same|alike"
                      r"|consistent|uniform)"
                      r"|(?:same|consistent|uniform)\s+(?:design|look|style|background)"
                      r"|(?:друг\w*|нов\w*|измени\w*|смени\w*|поменя\w*|меняй\w*|красив\w*|современн\w*)\s+"
                      r"(?:[\w']+\s+)?(?:дизайн\w*|фон\w*|оформлени\w*|шаблон\w*)"
                      r"|(?:дизайн|фон|оформлени)\w*\s+(?:[\w']+\s+)?(?:друг|нов|измени|смени|поменя)\w*"
                      r"|одинаков\w*\s+(?:дизайн|фон|оформлени|стил|вид)\w*|в\s+одном\s+стиле"
                      r"|(?:слайд|страниц)\w*\s+(?:[\w']+\s+)?одинаков\w*"
                      r")", I)
# The look kept, not changed: "dizaynni o'zgartirma", "chiroyli dizaynini saqlab qol", "bir xil
# dizaynda qolsin", "keep the same design", "don't change the background", "не меняй дизайн".
# Each of these once dropped the customer's design for a new one.
REFUSED = re.compile(r"ma(?:ng|ngiz|sin|sdan|slik|gan|y\w*)?$", I)
LOOK_KEPT_AFTER = re.compile(r"(?:(?!" + CONJUNCTION + r")" + _STOP + r"){0,25}?(?<![\w'])(?:qolsin|qolishi|qoldir\w*"
                             r"|saqla\w*|tegma\w*|o'zgarmasin|o'zgarishsiz|o'zgartirma\w*|almashtirma\w*|kerak\s+emas"
                             r"|kerakmas|shart\s+emas|as\s+it\s+is|unchanged|как\s+есть|прежн\w*)", I)
LOOK_KEPT_BEFORE = re.compile(r"(?<![\w'])(?:don't|dont|do\s+not|doesn't|never|keep|leave|retain|preserve|не|оставь\w*"
                              r"|сохрани\w*)\s+(?:[\w']+\s+){0,2}$", I)
NOT_IN = re.compile(r"(?<![\w'])(?:не|not|don't)(?![\w'])", I)

EXPAND = re.compile(W + r"(?:kengroq\w*|kengaytir\w*|batafsil\w*|to'liqroq\w*|to'liq\s+(?:yorit|ochib|tushuntir"
                    r"|ma'lumot|malumot|bayon)\w*|ko'l?proq\s+(?:[\w']+\s+)?(?:ma'lumot|malumot|axborot|fakt"
                    r"|tushuntirish|matn|izoh|misol)\w*"
                    r"|(?:ma'lumot|malumot)\w*\s+(?:ko'paytir|ko'proq|kengroq|qo'sh)\w*"
                    r"|chuqurroq"
                    r"|mukammalroq|uzunroq|more\s+(?:detail\w*|information|info|content|text|depth|examples?|facts)"
                    r"|in\s+(?:more\s+|greater\s+)?detail|detailed|expand\w*|elaborate\w*|in\s+depth|flesh\s+out"
                    r"|подробн\w*|детальн\w*|больше\s+(?:информации|текста|деталей|подробностей|фактов|примеров"
                    r"|сведений)|расширь\w*|разверн\w*)", I)
TO_PDF = re.compile(W + r"(?:pdf(?![\w'])\s*(?:(?:-\s*)?(?:shakl|format|ko'rinish|holat|hol|variant|fayl)\w*|qilib"
                    r"|da(?![\w'])|ga(?![\w']))|pdf(?:da|ga|ni|dek)(?![\w'])|(?:as|in|to|into)\s+(?:a\s+)?pdf(?![\w'])"
                    r"|pdf\s+(?:version|format|file)|(?:в|как|на)\s+pdf(?![\w'])|в\s+формате\s+pdf"
                    r"|pdf\s*-?\s*(?:файл|ом|ке|формат)\w*)", I)
TO_PPTX = re.compile(W + r"(?:(?:slayd|taqdimot|prezentatsiy?)\w*\s+(?:qilib|shaklida|formatida|ko'rinishida"
                     r"|holatida)\w*|(?:slayd|taqdimot|prezentatsiy?)\w*ga\s+(?:aylantir|o'tkaz)\w*"
                     r"|(?:as|into|in\s+the\s+form\s+of)\s+(?:a\s+)?(?:slides|slide\s+deck|presentation|powerpoint"
                     r"|pptx)(?![\w'])|pptx(?![\w'])|power\s*point(?![\w'])"
                     r"|(?:в\s+виде|в\s+формате)\s+(?:презентаци|слайд)\w*"
                     r"|(?:сделай|переделай)\s+(?:в\s+)?(?:презентаци|слайд)\w*)", I)
# What a request for the file alone may say besides the format: that it does
# not open, please, send it. Anything else is something to change.
ASIDE = re.compile(r"(?:bu|shu|shuni|uni|buni|ilova\w*|dastur\w*|telefon\w*|ochil\w*|o'qilma\w*|o'qib|bo'lmayapti"
                   r"|ishlama\w*|yubor\w*|jo'nat\w*|tashla\w*|ber\w*|iltimos|menga|qayta|fayl\w*|qilib|ham|kerak|edi"
                   r"|holda|uchun|chunki|hammasi|avvalgidek|o'zgarishsiz|qil|qiling|shakl\w*|format\w*|ko'rinish\w*"
                   r"|da|ga|men|bizga"
                   r"|please|send|resend|give|it|me|the|this|that|file|as|a|doesn't|does|not|open|opens|opening"
                   r"|can't|cannot|won't|app|phone|again|same|unchanged|version|instead|i|need|want|can|you|to|in"
                   r"|пожалуйста|отправь\w*|пришли\w*|скинь\w*|мне|его|её|файл\w*|не|открыва\w*|можно|в|виде"
                   r"|формате|без|изменений|это|этот|эту|нужн\w*|сделай)", I)


# --- Reading -------------------------------------------------------------------

def _clauses(body):
    return [(clause.start(), clause.group(0)) for clause in CLAUSE.finditer(body)]


def _has_pictures(sections):
    return any(section.get('image_query') for section in sections)


def _style(body):
    """'photo' or 'illustration' when the request names the kind of picture; the last one named wins."""
    found = []
    for start, clause in _clauses(body):
        # Pictures for young children are not drawings asked for; refused, they are photos asked for.
        for pattern, kind, other in ((DRAWN, 'illustration', 'photo'), (REAL, 'photo', 'illustration'),
                                     (CHILDISH, None, 'photo')):
            for match in pattern.finditer(clause):
                negated = (_after(STYLE_AFTER_NOT, clause, match.end())
                           or _before(STYLE_BEFORE_NOT, clause, match.start(), 20))
                if (other if negated else kind):
                    found.append((start + match.start(), other if negated else kind))
    return max(found)[1] if found else None


def _redesign(body):
    """Whether a new look is asked for: a design, a background or one look for every slide, not kept."""
    for _, clause in _clauses(body):
        for match in REDESIGN.finditer(clause):
            if not (REFUSED.search(re.findall(r"[\w']+", match.group(0))[-1]) or NOT_IN.search(match.group(0))
                    or _after(LOOK_KEPT_AFTER, clause, match.end())
                    or _before(LOOK_KEPT_BEFORE, clause, match.start(), 30)):
                return True
    return False


def photo_style(text):
    """The kind of picture a description asks for, new or a change: 'photo', 'illustration' or None."""
    return _style(_text(text))


def without_pictures(request):
    """A change request with its pictures taken out: what else it asks of a document's layout.

    Whether it wants pictures at all is `read`'s: "rasmsiz qil" names them to have none.
    """
    return PICTURE.sub(' ', _text(request))


def _format(body, fmt=None):
    """('pdf' | 'pptx', spans) for a file asked for in another format than `fmt`, else (None, [])."""
    for kind, pattern in (('pdf', TO_PDF), ('pptx', TO_PPTX)):
        if kind == fmt:
            continue
        spans = [match.span() for match in pattern.finditer(body)]
        if spans:
            return kind, spans
    return None, []


def _only(body, spans):
    """Whether nothing but an aside is left once the format is taken out."""
    rest = _blank(body, spans)
    return all(ASIDE.fullmatch(word) for word in re.findall(r"[\w']+", rest))


def asks_only_for_format(request):
    """'pdf' or 'pptx' when a change asks for nothing but the file in that format, else None."""
    body = _text(request)
    kind, spans = _format(body)
    if not kind or not _only(body, spans):
        return None
    edit = read(request, fmt='pptx' if kind == 'pdf' else 'pdf', sections=[])
    return kind if edit.format_only else None


def _blank(body, spans):
    """`body` with these spans as spaces, so the offsets of everything else stay put."""
    chars = list(body)
    for start, end in spans:
        chars[start:end] = ' ' * (end - start)
    return ''.join(chars)


def _overlaps(span, spans):
    return any(span[0] < end and start < span[1] for start, end in spans)


def _numbers(text):
    """The page numbers a list names: "5-7" is three pages, "5, 6 va 7" three, "3- va 4-" two."""
    found = []
    for match in re.finditer(r"(\d{1,3})(?:\s*(?:[-–]|to|through|по)\s*(\d{1,3}))?", text or ''):
        first, last = int(match.group(1)), int(match.group(2) or match.group(1))
        found += range(first, last + 1) if first <= last <= first + 60 else (first, last)
    return list(dict.fromkeys(found))[:60]


def _describes(body, span, part):
    """Whether a page added is the part named right beside it: "xulosa uchun bitta slayd qo'sh"."""
    gap = body[span[1]:part[0]] if part[0] >= span[1] else body[part[1]:span[0]]
    return (part[0] >= span[1] or part[1] <= span[0]) and len(gap) <= 15 and not SEPARATOR.search(gap)


def _title_page(body, clause_start, clause, fmt):
    """Whether pages added at the start of the document (`clause`, at `clause_start`) open on a title page.

    They do when lines are dictated for it, here or after it ("… deb yoz",
    "ismimni yoz", "TAYYORLADI: …" on the lines below), or the request names
    one. A document's page that says what it is about ("unda mavzuning
    dolzarbligi haqida yoz") is a page of content; one that says nothing is
    its title page, as students ask for one. A deck already opens on its
    cover, its title page: a slide added at its start that dictates nothing
    is a slide of content, after the cover.
    """
    if DICTATED.search(body, clause_start):
        return True
    return fmt != 'pptx' and not ABOUT.search(clause)


def _deltas(body, parts_at, most=60, fmt=None):
    """(pages added and removed, whether one was added at the start as its title page, the spans they were
    read from, the page numbers removed by name). One removal takes at most `most` pages."""
    delta, start_page, spans, named = 0, False, [], []
    for start, clause in _clauses(body):
        for pattern in ADDING:
            for match in pattern.finditer(clause):
                span = (start + match.start(), start + match.end())
                if _overlaps(span, spans):
                    continue
                count = _number(match.group(1)) if pattern is not NEW_UZ and match.group(1) else 1
                filler = match.group(2) if pattern in (ADD_EN, ADD_RU) else None
                # "add a conclusion slide": the part is the page, counted once.
                if filler and _part_word(filler):
                    continue
                if pattern is MORE_UZ and FOR_THING.match(clause, match.end()):
                    continue  # "yana 3 ta slaydga rasm": pictures on three more slides
                if any(_describes(body, span, part) for part in parts_at):
                    continue
                spans.append(span)
                near = clause[max(0, match.start() - 25):match.end() + 20]
                if AT_START.search(near) and not start_page and _title_page(body, start, clause, fmt):
                    start_page, count = True, count - 1
                delta += max(0, min(count, 20))
        for pattern in (REMOVE_UZ, REMOVE_EN, REMOVE_RU):
            for match in pattern.finditer(clause):
                span = (start + match.start(), start + match.end())
                if _overlaps(span, spans):
                    continue
                found = match.groupdict()
                first, count, unit = found['first'] or found.get('first2'), found['count'], found['unit']
                ordinals = found.get('listed') or found.get('after')
                if pattern is REMOVE_UZ:
                    before = re.findall(r"[\w']+", clause[max(0, match.start() - 20):match.start()])
                    # "savollar slaydini olib tashla" takes the test away; "xulosa slaydini" a part.
                    if before and (QUESTION.fullmatch(before[-1]) or _part_word(before[-1])):
                        continue
                    plural = 'lar' in unit.lower()
                else:
                    filler = found['filler']
                    # "remove the question slides" takes the test away; "the conclusion slide" a part.
                    if filler and (QUESTION.fullmatch(filler) or PICTURE.fullmatch(filler) or _part_word(filler)):
                        continue
                    plural = unit.lower().endswith('s')
                if pattern is REMOVE_RU:
                    plural = unit.lower() not in ('слайд', 'страницу', 'лист')
                    # "удали 3 слайд" is slide three; "удали 3 слайда" three slides.
                    if count and count.isdigit() and not plural:
                        count, ordinals = None, count
                numbers = [] if count else _numbers(ordinals)
                removed = _number(count) if count else len(numbers) if numbers else 1 if first or not plural else 0
                spans.append(span)
                named += numbers
                delta -= max(0, min(removed, most))
    return delta, start_page, spans, named


def _part_word(word):
    return any(pattern.fullmatch(word) for _, pattern in PART_PATTERNS)


def added_parts(parts, fmt):
    """The parts a change adds that take a page or slide of their own.

    A deck's title page is its cover, which every deck has: the lines
    dictated for it go on the cover, and no slide is added for it.
    """
    return [part for part in parts or [] if not (fmt == 'pptx' and part == 'title_page')]


def _parts(body, sections, fmt):
    """(parts asked to be added, positions they are named at, existing parts asked to go)."""
    headings = [re.sub(r"^[\W\d_]+", '', normalised(s.get('heading') or '')) for s in sections]
    have = {name for name, pattern in HEADINGS.items() if any(pattern.match(heading) for heading in headings)}
    # A deck opens on its cover, which is its title page: a title page named
    # with nothing dictated for it is already there.
    if fmt == 'pptx' and sections and not DICTATED.search(PART_PATTERNS[0][1].sub(' ', body)):
        have.add('title_page')
    asked, at, gone = [], [], []
    for start, clause in _clauses(body):
        for name, pattern in PART_PATTERNS:
            for match in pattern.finditer(clause):
                if (_after(AFTER_REMOVE, clause, match.end())
                        or _before(BEFORE_REMOVE, clause, match.start(), 30)):
                    if name in have and name not in gone:
                        gone.append(name)
                    continue
                if _after(AFTER_CHANGE, clause, match.end()) or _before(BEFORE_CHANGE, clause, match.start(), 30):
                    continue
                at.append((start + match.start(), start + match.end()))
                if name not in have and name not in asked:
                    asked.append(name)
    return [name for name in PARTS if name in asked], at, gone


CHARACTER = re.compile(W + r"(?:obraz|qahramon|personaj|character|персонаж|образ|геро[яеи])\w*", I)
CHARACTER_ADD_AFTER = re.compile(r"\s{0,3}(?:ham\s+)?(?:qo'sh|kirit)(?!ma)\w*", I)
SEPARATOR = re.compile(r"\s*(?:,|;|(?<![\w'])(?:va|hamda|and|и)(?![\w']))\s*", I)


def _names(text, backwards):
    """The capitalised names listed next to "obrazlari" / "characters": "Azimjon, Ochil bobo, Bektemir"."""
    pieces = [piece.split() for piece in SEPARATOR.split(text.strip())]
    names = []
    for words in (reversed(pieces) if backwards else pieces):
        if not words:
            break
        lead = 0
        if backwards:
            while lead < len(words) and not words[lead][:1].isupper():
                lead += 1
        name = words[lead:]
        if not name or not name[0][:1].isupper() or len(name) > 3:
            break
        names.append(' '.join(name))
        if lead:
            break
    return names[:6]


def _characters(body, sections):
    """Characters named to be added, each a page or slide of its own, minus those the document has."""
    headings = ' '.join(normalised(s.get('heading') or '') for s in sections).lower()
    found = []
    for start, clause in _clauses(body):
        for match in CHARACTER.finditer(clause):
            if CHARACTER_ADD_AFTER.match(clause, match.end()):
                names = _names(clause[max(0, match.start() - 150):match.start()], True)
            elif _before(BEFORE_ADD, clause, match.start(), 30):
                names = _names(re.split(r"[.!?;\n]", clause[match.end():match.end() + 150])[0], False)
            else:
                continue
            found += [name for name in names if name.split()[0].lower() not in headings and name not in found]
    return found


def read(request, *, fmt, sections, questions=0):
    """What a change request asks for. `sections` is the document as it stands; `questions` how many it has."""
    body = _text(request)
    sections = list(sections or [])
    edit = Edit()
    blank = []

    edit.format, format_spans = _format(body, fmt)

    # Questions.
    asked = removed = more = False
    count = None
    for start, clause in _clauses(body):
        for match in QUESTION.finditer(clause):
            if re.search(r"\d\s*-\s*$", clause[max(0, match.start() - 6):match.start()]):
                continue  # "3-savol" is one question, not the test
            if (WITHOUT.search(match.group(0)) or _after(AFTER_REMOVE, clause, match.end())
                    or _before(BEFORE_REMOVE, clause, match.start(), 30)):
                removed = True
                continue
            dative = re.search(r"(?:ga|da|dagi)$", match.group(0), I)
            if ((not dative and _after(QUESTION_ADD_AFTER, clause, match.end()))
                    or _before(QUESTION_ADD_BEFORE, clause, match.start(), 40)):
                asked = True
            # "savollar 10 ta bo'lsin": the number after the noun, which is not ten pages.
            after = COUNT_AFTER.match(clause, match.end())
            if after and not dative and count is None:
                asked, count = True, _number(after.group(1))
                more = bool(re.search(r"(?:qo'y|qo'sh)\w*$", after.group(0), I))
                blank.append((start + after.start(1), start + after.end()))
            # "savollarni 5 taga qisqartir", "reduce the questions to 5": the test's new size.
            size = QUESTIONS_TO.match(clause, match.end())
            if size and count is None and (size.group(1) or _before(CUT_BEFORE, clause, match.start())):
                asked, count, more = True, _number(size.group(1) or size.group(2)), False
                blank.append((start + match.end(), start + size.end()))
        for match in QUESTION_COUNT.finditer(clause):
            if _after(AFTER_REMOVE, clause, match.end()):
                continue
            asked = True
            blank.append((start + match.start(), start + match.end()))
            if match.group(2).lower() in ('a', 'an', 'another'):
                continue  # "add a quiz": a test, of no number
            number = _number(match.group(2))
            count = (questions + number) if match.group(1) else number
            more = not match.group(1) and bool(_after(MORE_AFTER, clause, match.end())
                                               or _before(MORE_BEFORE, clause, match.start(), 30))
    # "savol slaydi 2 bet bo'libdi, shuni 1 bet qil": its questions on one slide.
    for match in QUESTION.finditer(body) if not (asked or removed) else ():
        fit = FIT.search(body, match.end(), min(len(body), match.end() + FIT_REACH))
        if fit:
            blank.append((match.start(), fit.end()))
            slides = _number(fit.group(1))
            if fmt == 'pptx' and questions > slides * QUESTIONS_PER_SLIDE:
                count = slides * QUESTIONS_PER_SLIDE
            break
    if removed and not asked:
        edit.questions = 'remove'
    elif asked:
        edit.questions = 'add'
    edit.question_count = count if edit.questions != 'remove' else None
    edit.more_questions = bool(more and edit.questions == 'add' and count)

    # Pictures.
    edit.photo_style = _style(body)
    has = _has_pictures(sections)
    kinds, counts, targets = set(), [], set()
    for start, clause in _clauses(body):
        mentions = list(PICTURE.finditer(clause))
        if not mentions:
            continue
        styled = bool(DRAWN.search(clause) or REAL.search(clause) or CHILDISH.search(clause))
        every = EVERY.search(clause)
        adds = False
        for match in PICTURE_COUNT.finditer(clause):
            # "har 1ta slaydga rasm", "har bir sahifada rasm": one a page, not one in all.
            each = EACH.search(clause[max(0, match.start() - 8):match.start()])
            if ((match.group(1).isdigit() or match.group(1).lower() not in ('a', 'an', 'another'))
                    and not each and not (match.group(2) and VAGUE.fullmatch(match.group(2)))):
                counts.append(_number(match.group(1)))
            blank.append((start + match.start(), start + match.end()))
        # "3 ta rasmli slayd qo'sh": three slides, so three pictures.
        counts += [_number(match.group(1)) for match in PICTURED.finditer(clause)]
        for match in PLACES.finditer(clause):
            blank.append((start + match.start(), start + match.end()))
        for match in mentions:
            gone = _after(AFTER_GONE, clause, match.end()) or _before(BEFORE_GONE, clause, match.start())
            negated = (gone or WITHOUT.search(match.group(0)) or _after(AFTER_REMOVE, clause, match.end())
                       or _before(BEFORE_REMOVE, clause, match.start()))
            explicit = _after(AFTER_ADD, clause, match.end()) or _before(BEFORE_ADD, clause, match.start())
            if not counts:
                after = COUNT_AFTER.match(clause, match.end())
                if after and not negated:
                    counts.append(_number(after.group(1)))
                    blank.append((start + after.start(1), start + after.end()))
            if negated:
                # "Yosh bolacha rasm qo'yma": the kind is refused, not the pictures. Pictures not
                # wanted ("rasmsiz", "rasm qo'shmang", "картинки не нужны") take away those the
                # document has, and add none.
                kinds.add(None if styled else 'remove' if gone or has else None)
            elif every:
                kinds.add('every')
            elif has and not explicit and (styled or _after(RESHAPE_AFTER, clause, match.end())
                                           or _before(RESHAPE_BEFORE, clause, match.start())):
                kinds.add(None)  # the pictures it has, of another kind, size or place
            else:
                kinds.add('add')
                adds = True
        if adds:
            targets.update(next(g for g in m.groups() if g) for m in TARGET.finditer(clause))
    edit.pictures = next((kind for kind in ('every', 'add', 'remove') if kind in kinds), None)
    if edit.pictures in ('add', 'every'):
        edit.picture_count = max(counts) if counts else (len(targets) or None)

    # Parts, pages added and removed, characters.
    edit.parts, parts_at, gone = _parts(body, sections, fmt)
    delta, start_page, spans, named = _deltas(body, parts_at, len(sections) or 60, fmt)
    blank += spans
    if start_page and 'title_page' not in edit.parts:
        # Read on a deck too, so the model is told the dictated lines go on its
        # cover; it adds no slide there (added_parts).
        edit.parts = [name for name in PARTS if name in edit.parts or name == 'title_page']
    names = _characters(body, sections)
    if names:
        delta += len(names) if fmt == 'pptx' else -(-len(names) // 2)
    # A number past the last content slide is not a content slide. On a deck it is
    # one of the question slides at the end: "12-slaydni o'chir" on ten slides and
    # two of questions takes the second of those, and the questions on it.
    beyond = sorted({number for number in named if sections and number > len(sections)})
    delta += len(beyond)
    if fmt == 'pptx' and questions and beyond and edit.questions is None and edit.question_count is None:
        dropped = [number - len(sections) for number in beyond if number - len(sections) <= question_slides(questions)]
        left = sum(1 for n in range(questions) if n // QUESTIONS_PER_SLIDE + 1 not in dropped)
        edit.removed_question_slides = dropped
        if not left:
            edit.questions = 'remove'
        elif dropped:
            edit.question_count = left
    edit.delta = delta - len(gone)

    # A total only where the request names a new size; never a number that
    # points at a slide, counts the ones something is on, or says what is there now.
    edit.total = _total(body, blank + format_spans)

    edit.redesign = _redesign(body)
    edit.expand = bool(EXPAND.search(body))
    current = len(sections) + (question_slides(questions) if fmt == 'pptx' else 0)
    # A deck's title page moves nothing: it is written on the cover.
    edit.structural = bool(edit.delta or added_parts(edit.parts, fmt) or REORDER.search(body)
                           or (edit.total is not None and sections and edit.total != current))
    edit.format_only = bool(edit.format) and _only(body, format_spans) and not (
        edit.total or edit.delta or edit.parts or edit.pictures or edit.photo_style or edit.questions
        or edit.question_count or edit.redesign or edit.expand or edit.structural)
    return edit
