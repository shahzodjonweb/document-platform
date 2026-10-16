"""What a description says the document must cover, and whether it does.

The model is told the subtopics a description spells out (`required_subtopics`)
so a long deck written in several calls does not lose one; afterwards the
compiled document is checked for each. Only what the customer listed counts —
"including A, B and C", "quyidagilar: A, B, C", a bulleted list — never
subtopics guessed from the subject.
"""
import functools
import re

from .language import normalised
from .uzbek import CYRILLIC, to_latin

ITEM_LINE = re.compile(r'^\s*(?:[-•*–·▪]|\d{1,2}[.)]|[a-zа-я][.)])\s+(.+?)\s*$', re.MULTILINE | re.IGNORECASE)
CUES = re.compile(
    r"(?:\bincluding|\bcovering|\bsuch as|\binclude|\bcover|\btopics?\s*:|\bsections?\s*:|\bsubtopics?\s*:"
    r"|\bshu jumladan|\bjumladan|\bquyidagi\w*(?:\s+[\w']+){0,3}?\s*:|\bo'z ichiga olsin\s*:?|\bmavzular\s*:"
    r"|\bbo'limlar\s*:|включая|в том числе|такие как|следующие\s+\w+\s*:?|разделы\s*:|темы\s*:)\s*",
    re.IGNORECASE)
SPLIT = re.compile(r"\s*(?:[;,]|\band\b|\bva\b|\bhamda\b|(?<![\wЀ-ӿ])и(?![\wЀ-ӿ]))\s*", re.IGNORECASE)
# Counts, formats and languages are instructions about the document, not
# subtopics; so are its form, style and delivery ("modern design", "фото",
# "with speaker notes", "ilmiy uslubda", "a conclusion"). An item with nothing
# left once these are taken out is not sent as a subtopic to cover.
NOT_TOPIC = re.compile(
    r"\b\d+\b|\b(?:in|into|on|ta|tilida|tilda|языке|на)\b|\b(?:slides?|slayd\w*|pages?|bet|sahifa\w*|varaq\w*|слайд\w*|страниц\w*|pdf|pptx|questions?|savol\w*"
    r"|вопрос\w*|english|ingliz\w*|russian|rus\s*til\w*|uzbek|o'zbek\s*til\w*|англ\w*|русск\w*|узбек\w*"
    r"|photo(?:s|graph\w*)?|pictures?|images?|rasm\w*|surat\w*|фото(?!синтез)\w*|картин\w*"
    r"|tables?|jadval\w*|таблиц\w*|designs?|dizayn\w*|дизайн\w*|styles?|uslub\w*|стил\w*|tone|speaker\s+notes"
    r"|conclusions?|xulosa\w*|вывод\w*|заключен\w*|examples?|misol\w*|пример\w*"
    r"|statisti\w*|статистик\w*|bibliography|adabiyotlar\s+ro'yxat\w*|список\s+литератур\w*"
    r"|sources?|manba\w*|источник\w*|languages?|til\w*|язык\w*"
    r"|modern|friendly|scientific|ilmiy|formal|rasmiy)\b",
    re.IGNORECASE)
STOP = set('''the and for with from that this into about their your what which when where how why are was were has have
its can will also than then such other more most some many much each every all any both only very just over under
va bilan uchun haqida ham esa yoki hamda kabi deb bu shu ushbu uning ular qanday nima uchun orqali
и в во на о об с со для по не что как это из к у от при или также который которые является'''.split())


def required(prompt, limit=12):
    """The subtopics a description lists, in order, at most `limit`."""
    body = normalised(prompt)
    found = []
    lines = [match.group(1) for match in ITEM_LINE.finditer(body)]
    if len(lines) >= 2:
        found.extend(lines)
    for match in CUES.finditer(body):
        clause = re.split(r'[.!?\n]', body[match.end():], maxsplit=1)[0]
        parts = [part for part in SPLIT.split(clause) if part]
        if len(parts) >= 2 or (parts and match.group(0).rstrip().endswith(':')):
            found.extend(parts)
    seen, result = set(), []
    for item in found:
        item = item.strip(' \t"\'«»“”()[]:.-–—')
        key = item.lower()
        # "10 slides", "in English": what remains without those words is the subtopic, if any.
        if not 2 <= len(item) <= 80 or ':' in item or key in seen or not stems(NOT_TOPIC.sub(' ', item)):
            continue
        seen.add(key)
        result.append(item)
    return result[:limit]


def stems(text):
    """Word stems that survive suffixes: Uzbek and Russian inflect where English does not."""
    words = re.findall(r"[\wЀ-ӿ']+", normalised(text).lower())
    return {word.replace("'", '')[:5] for word in words if len(word) >= 3 and word not in STOP and not word.isdigit()}


def _alike(a, b):
    """One stem is the other with an ending: a short root keeps all but its last letter
    ('suv' ~ 'suvni', 'вода' ~ 'воды', 'tide' ~ 'tides'), and never fewer than three."""
    size = max(3, min(len(a), len(b)) - 1)
    return len(a) >= size and len(b) >= size and a[:size] == b[:size]


def _index(found):
    index = {}
    for stem in found:
        index.setdefault(stem[:3], []).append(stem)
    return index


def _present(stem, index):
    return any(_alike(stem, other) for other in index.get(stem[:3], ()))


def overlap(these, those):
    """Whether two sets of stems share a word."""
    index = _index(those)
    return any(_present(stem, index) for stem in these)


def missing(subtopics, text):
    """The subtopics that `text` does not mention: fewer than half their stems appear."""
    present = _index(stems(text))
    gaps = []
    for subtopic in subtopics:
        wanted = stems(subtopic)
        if wanted and sum(_present(stem, present) for stem in wanted) * 2 < len(wanted):
            gaps.append(subtopic)
    return gaps


# --- A description that names no topic at all ---------------------------------
#
# "12 ta slayd kk", "Ko‘k rangda bo‘lsin 12 betlik", "сделай презентацию", "a nice
# document please": every word is a count, a format, a request, a look or the
# word "topic" itself (the bot's own tool is called "Mavzuga oid PDF", and
# customers echo it). Sent to the model, such a request either comes back with
# a subject the model made up, which spends a weekly document on something
# nobody asked for, or with a reply too thin to pass the checks, which fails
# the job. A new document is refused before it is made instead, with a message
# that says what is missing (domain.create_draft).
#
# A wrong refusal blocks a customer with no way round it but rewording, so the
# test is conservative by construction:
#
# * Every word must be accounted for. One word the vocabulary below does not
#   know is taken to be the topic: "Chiroy", "Fotosintez", a name.
# * Words that are instructions in one form and topics in another ("rang"
#   colour, "dizayn", "rasm" picture, "til" language, "kitob" book, "tuz"
#   make/salt, "yoz" write/summer, colour names, "maktab", "universitet") are
#   WEAK: they count as instructions only when bound to one beside them ("ko‘k
#   rangda", "rasmlar bilan", "chiroyli dizayn", "7-sinf", "slayd tuz"). Alone
#   they are the topic: "Ranglar", "Tuz", "Ko‘k", "Qizil kitob". Things first
#   and colours second ("havo" air, "oltin" gold) are a colour only before a
#   colour noun ("havo rang", "oltin rangda").
# * A word in a topic slot ("X haqida", "X mavzusida", "about X", "про X",
#   "Mavzu: X") is the topic unless it is a count, a request or the word
#   "topic" ("Mavzuga oid", "on a topic", "по теме"). A format there is the
#   topic too ("PowerPoint haqida", "Mavzu: Word"), except after "on": "a
#   presentation on PowerPoint" says what it is made in.
# * A quoted title is a topic, and so is a year: counts have three digits at
#   most. So are an acronym ("IT", "US"), an English grammar lesson named by
#   its words ("Some and any", "In, on, at") and a "How to …" title.
# * Each line is read on its own: the bot joins the topic it asked for to what
#   was written before on a new line ("Havo" + "slayd kerak").
# * Something must be asked for: a count, a format, a request or "topic". A
#   look or a part alone ("Modern design", "Chiroyli", "План урока") could be
#   the subject, so it is left to the model as before.
#
# Typing slips: a letter typed twice or more counts once ("chiroooyli", "kk"),
# x and h are one letter in Uzbek Latin (xulosa/hulosa, mavxuga), Uzbek typed
# in Cyrillic is read in Latin, and a few frequent words are matched within one
# edit when their first two letters agree ("mavxuga", "slyad", "otqaz"). A real
# word folded onto a listed one ("soda" is not "sodda", "bee" is not "be") is
# never matched, and Cyrillic read in Latin is never an English word ("море"
# is not "more").
#
# The word lists are data: entries are written as they are typed and folded
# when compiled, "stem*" is a prefix and anything else a whole word. Latin
# entries are Uzbek or English, Cyrillic ones Russian. tests/test_topicless.py
# pins them; check a new word against both of its lists before adding it.

def fold(word):
    """A word as the vocabulary is keyed: lower case, no apostrophes, ё as е,
    x as h in Latin, and a letter repeated in a row once."""
    word = normalised(word).lower().replace("'", '').replace('ё', 'е')
    if not CYRILLIC.search(word):
        word = word.replace('x', 'h')
    return re.sub(r'(.)\1+', r'\1', word)


# Russian colours as the adjectives they are, in every form: as stems ("син*",
# "сер*", "бел*") they took Синонимы, Сердце and Беларусь for a look.
RUSSIAN_COLOURS = ' '.join(
    stem + ending
    for stem in 'син красн зелен желт бел черн голуб розов фиолетов оранжев сер темн светл'.split()
    for ending in 'ый ий ой ая яя ое ее ые ие ого его ому ему ым им ыми ими ых их ую юю ей ом ем'.split())
INSTRUCTIONS = {
    # Pages and slides as a count (pages.UNIT_WORDS, pages.AFTER).
    'unit': '''ta tadan talik tali tasi dona betlik betli betdan betga betda bet betlar betlarda betlardan betni
        sahifa* varaq* varoq* varag* varog* list listli listlik listdan listga listda listlar listlari listning
        soni sonini miqdori page pages sheet sheets
        страниц* стр лист листа листов листы листок штук*''',
    # What is made (pages.SLIDE_WORDS, pages.DOCUMENT_WORDS, edits.TO_PDF).
    'format': '''slayd* slaid* slide slides slideshow deck taqdimot* prezentats* presentats* prezentasi* presentasi*
        prezint* presentation presentations powerpoint ppt pptx pdf* word docx doc fayl* file
        hujjat hujjatni hujjatga hujjatda hujjati document documents referat* doklad* esse essay insho*
        maqola report handout worksheet assignment homework coursework tarqatma*
        презентац* слайд* документ* файл* реферат* доклад* эссе сочинени* презу преза презы презку презка
        ворд ворде ворда пдф''',
    # Asking for it (language.DOING): the verb forms only, never the noun.
    'verb': '''yasa yasab yasang yasangiz yasat yasatib yasagin yasaber yasabber yasavor yasash yasaysizmi
        ber bera bering beringiz beringlar berin bersin bergin berasizmi berasiz bervor bervoring
        qil qilib qiling qilingiz qilsin qilgin qilish qilasizmi qilibering qilinsin qilvor
        tayyorla tayyorlab tayyorlang tayyorlangiz tayyorlasin tayyorlagin tayyorlaber tayyorlasangiz
        tuzib tuzing tuzsin tuzgin yaratib yarating yaratsin yaratgin yarat
        yozib yozing yozsin yozgin yozilsin chiqar chiqarib chiqaring chiqsin chiqib chiqarsin
        kerak kerek kere k keragi kerakli bolsin bulsin bolsn bolishi bolsa bolib boladi
        jonat jonating yubor yuboring tashla tashlab tashlang
        make create generate prepare write build give need needs want do produce send help
        made needed would could like
        сделай* сделать создай* создать подготовь подготовьте подготовить подготовите напиши* написать
        составь* нужн* нужен надо хочу дай дайте помоги* оформи*''',
    # Turning a file into another format: the file tools' work, not a new
    # document's ("pdf ga o‘tkaz", "convert to pdf", "переведи в pdf").
    'convert': '''otkaz otkazib otkazing otkazber otkazish otkazvor aylantir aylantirib aylantiring aylantirish
        ogir ogirib ogiring convert turn переведи* перевести конвертир* преобразу*''',
    # The word "topic" itself.
    'placeholder': '''mavzu* topic topics subject тема темы теме тему темой тематик*''',
    # How it should look or read: adjectives, and look nouns in an inflected form.
    'style': '''chiroyli chiroyliroq chiroylik chiroylisi yorqin yorqinroq yorugroq rangli rangda rangdagi ranglarda
        ranglardan rangdan rangga ranglari rangi rangbarang rasmli suratli dizaynda dizaynli
        uslubda uslubida uslubdagi fonda fonli ozgacha qiziqarli sodda oddiy ajoyib zor kreativ
        professional zamonaviy batafsil toliq qisqa qisqacha tushunarli oson ilmiy akademik
        nice beautiful pretty bright colourful colorful good cool simple modern short long detailed brief clean
        creative attractive stylish
        красив* ярк* цветн* стильн* современн* подробн* кратк* интересн*''',
    # Its parts and what each page holds (edits.PART_WORDS).
    'structure': '''har tushuntirish tushuntirib tushuntirilsin izoh izohi izohlar izohli misol misollar misoli
        misollari savol savollar savollari savoli savolli fikr fikrlar oxirida oxiriga boshida
        boshiga reja rejali rejalar rejasi rejalari kirish hulosa hulosasi hulosalar mundarija sarlavha
        sarlavhali foydalanilgan adabiyotlar
        questions quiz conclusion introduction plan
        пример* пояснени* вопрос* вывод* заключени* введени* план''',
    # Who it is for, in a form that says so ("universitetga", "ochiq darsga").
    'audience': '''universitetga universitetda maktabga maktabda darsga darsda darsi seminarga seminarda sinfga
        sinflarga talabalarga oquvchilarga bolalarga institutga kollejga litseyga tehnikumga
        ochiq amaliy mustaqil ishga ishi ishlanma
        урока уроку вуза вузу школы школе студентов студентам''',
    # The language to write in (language.LANGUAGE_WORDS), in a form that says so.
    'language': '''inglizcha inglizchasiga inglizchada ruscha ruschada ozbekcha ozbekchada tilida tilda tiliga
        tilga
        русском английском узбекском языке языком''',
}
# Instructions in one form, topics in another: see _bound for what binds each.
WEAK = {
    'colour': '''kok qizil yashil sariq oq qora pushti binafsha binafsharang moviy havorang zangori kulrang
        jigarrang toq och savorang
        blue red green yellow white black pink purple violet orange grey gray dark
        светло темно ''' + RUSSIAN_COLOURS,
    # A thing first, a colour only before a colour noun: "havo" is air and
    # "havo rang" sky blue, "oltin" gold, "light" and "navy" nouns too.
    'colour_before_noun': '''havo oltin kumush tilla siyoh feruza bordo light navy''',
    'picture': '''rasm rasmlar rasmlari rasmlarni rasmi surat suratlar suratlari foto fotolar tasvir tasvirlar
        picture pictures image images photo photos illustration illustrations
        картинк* картин* изображени* иллюстрац* рисун* фото фотографи*''',
    'design': '''dizayn dizayni dizaynini uslub shablon fon rang ranglar
        design style theme template background colour color colours colors
        дизайн стил* оформлени* фон цвет* тон тона тонах тонов тонами оттенк*''',
    'audience': '''universitet maktab dars seminar sinf sinflar kurs talaba talabalar oquvchi oquvchilar bola bolalar
        institut kollej litsey tehnikum university school class lesson students kids teacher
        урок вуз школ* класс* студент* курс''',
    'language': '''ingliz rus ozbek uzbek english russian til tili язык русский английский узбекский''',
    'generic': '''kitob loyiha test malumot malumotlar malumoti malumotlari matn ish information info project paper
        text информаци* текст* проект''',
    'ambiguous_verb': '''tuz yoz''',
}
# Colour nouns, which bind a colour named beside them ("ko‘k rangda", "blue theme").
COLOUR_NOUNS = '''rang* fon* colour* color* background theme tone цвет* тон* фон* оттенк*'''
# Words that say nothing either way, on top of STOP. The words that mark a
# topic slot ("bo‘yicha", "asosida") are among them: they are never the topic.
FUNCTION_WORDS = '''ga da ni ning dan li lik oid doir menga bizga sizga mening men biz siz sizdan iltimos ilimos
    rahmat salom mana yana juda eng kop faqat shunchaki bitta ikkita barcha hamma ana unda ular o u bir
    edi tez tezroq olasizmi haqidagi haqda hakida to'g'risida to'g'risidagi bo'yicha buyicha asosida borasida
    yuzasidan
    a an i me my our us it to of in on at by as is be you please pls plz thanks
    мне нам мой моя моё мою пожалуйста чтобы пусть будет было быть еще ещё очень все всё а пж плз'''
# English words in the lists above. A word typed in Cyrillic is read in Latin
# for Uzbek, never for one of these: "море" is not "more", nor "мост" "most".
ENGLISH = '''page pages sheet sheets slide slides slideshow deck presentation presentations powerpoint word docx doc
    file document documents essay report handout worksheet assignment homework coursework make create generate
    prepare write build give need needs want do produce send help made needed would could like convert turn topic
    topics subject nice beautiful pretty bright colourful colorful good cool simple modern short long detailed brief
    clean creative attractive stylish questions quiz conclusion introduction blue red green yellow white black pink
    purple violet orange grey gray dark light navy picture pictures image images photo photos illustration
    illustrations design style theme template background colour color colours colors university school class lesson
    students kids teacher uzbek english russian information info project paper text tone
    a an i me my our us it to of in on at by as is be you please pls plz thanks'''
# Real words folded onto a listed word: "soda" is not "sodda", "bee" is not "be".
REAL_WORDS = '''soda bee booth inn off god anna ann beer beet donna manna reed teen referral varan'''
# Matched within one edit: frequent, telling, and long enough not to catch a real word.
SLIPS = {
    'format': '''slayd slaydlar slayda slaydan slaydli slaydga taqdimot prezentatsiya referat
        презентация презентацию презентации слайды слайдов''',
    'verb': '''yasab yasang tayyorlab tayyorla tayyorlang yaratib qilib qiling kerak bolsin chiqsin chiqarib
        сделай сделайте''',
    'convert': '''otkaz otkazib aylantir''',
    'placeholder': '''mavzu mavzuga mavzusi mavzusida mavzuda''',
    'style': '''chiroyli yorqin rangda rangli красивую красивые красивый''',
    'unit': '''sahifa sahifali sahifalik varaq varaqli''',
}
# Real words one edit from one of those: "yashab" (living) is not "yasab" (made).
NOT_SLIPS = '''yashab yashang yashash yashasin qolib qoling qolsin'''
# A prefix entry that would swallow a subject: rasmiy (official), fotosintez,
# слайдер, faylasuf (philosopher), inshoot (building), документооборот,
# штукатурка, цветник. Written folded, as the key it is matched against.
NOT_PREFIXED = re.compile(r'^(?:rasmiy|fotosint|фотосинт|слайдер|presentativ|deckar|pdfdan|filelar|faylasuf|файласуф'
                          r'|inshot|inshoat|документобор|документальн|штукатур|цветник)')

# What makes the rest an instruction: something asked for, or how many.
ASKED = {'number', 'unit', 'format', 'verb', 'convert', 'placeholder'}
VERBS = {'verb', 'convert'}
# These never fill a topic slot: "Mavzuga oid PDF" names no topic. A format
# does, except after "on" (_slots).
NOT_A_TOPIC = ASKED | {'function'}
TOPIC_BEFORE = '''haqida haqda hakida haqidagi to'g'risida to'g'risidagi mavzusida mavzusidagi mavzuda mavzudagi
    mavzuga mavzusi bo'yicha buyicha oid doir asosida borasida yuzasidan'''
TOPIC_AFTER = '''about regarding concerning on про о об обо по'''
# "Mavzu: Amir Temur", "на тему экология": the name follows the word "topic".
PLACEHOLDER_NAMES = '''mavzu mavzusi topic subject тема тему теме'''
BIND_NEXT = '''bilan ham bolsin bulsin bolishi kerak k kerek uchun kop qosh qoshing qoshilsin qoy qoying qoyilsin
    solinsin ishlat ishlating joyla joylang chiqsin bolsa'''
STYLE_BEFORE = '''chiroyli zamonaviy ozgacha boshqa yangi yorqin rangli nice modern beautiful new
    красивый красивую красивые современный новый'''
GENERIC_BEFORE = '''toliq aniq batafsil kop qisqa mustaqil kurs loyiha diplom bitiruv amaliy ilmiy ijodiy
    full detailed more'''
# Not "my" or "our": "My school" is a subject; "for my class" is bound by "for".
WITH = '''with without in into for с со без в во для на har mos'''
COLOUR_JOINERS = '''va and и yoki or'''
# "uslub" said alone is the subject of an Ona tili lesson ("Ilmiy uslub",
# "Rasmiy uslub"); "ilmiy uslubda" is the request.
BARE_STYLE = '''uslub'''
# "Kurs ishi": coursework, a format.
KURS_WORK = '''ish ishi ishini'''
# A file named as the format turned into: the file tools convert it.
FILE_FORMAT = re.compile(r'^(?:pdf|word|docx?|fayl|file|файл|ворд|пдф)')
CONVERT_ONLY = {'format', 'verb', 'convert', 'function', 'number', 'unit'}

# An English lesson named by its words: "Some and any", "Can, could", "Was or
# were", "In on at", "A, an, the", and titles such as "How to write an essay"
# or "To do list". Each pair takes two of the words joined by and/or/vs/a
# comma; three articles or prepositions may also stand side by side.
_GRAMMAR = ('some|any|much|many|few|little|can|could|will|would|shall|should|must|may|might|have|has|had|was|were'
            '|is|are|am|be|been|do|does|did|make|say|tell|in|on|at|by|a|an|the|this|that|these|those|to|too')
_SIDE_BY_SIDE = 'a|an|the|in|on|at|by|this|that|these|those'
GRAMMAR_LESSON = re.compile(
    rf"(?<![\w'])(?:{_GRAMMAR})\s*(?:,|/|&|\band\b|\bor\b|\bvs\b\.?|\bversus\b)\s*(?:{_GRAMMAR})(?![\w'])"
    rf"|(?<![\w'])(?:{_SIDE_BY_SIDE})[\s,]+(?:{_SIDE_BY_SIDE})[\s,]+(?:{_SIDE_BY_SIDE})(?![\w'])"
    r"|^\W*(?:how\s+to|to\s+(?:do|be|make|have))(?![\w'])", re.IGNORECASE)

LONGEST = 300
TOKEN = re.compile(r"\d+|[^\W\d_]+(?:'[^\W\d_]+)*")
# Anything between quotes. Each match stops at the next quote mark, so a lone
# opening quote costs one scan to the next mark rather than a search per letter.
QUOTED = re.compile(r'["«“„]([^"«»“”„]*)["»”“]')
# "по-английски" is a language, not "по" followed by a topic.
PO_LANGUAGE = re.compile(r'(?<!\w)по-?\s*(?:английски|русски|узбекски)(?!\w)', re.IGNORECASE)


def _words(words):
    return {fold(word) for word in words.split()}


def _compile(table):
    exact, prefixes = {}, []
    for name, words in table.items():
        for word in words.split():
            if word.endswith('*'):
                prefixes.append((fold(word[:-1]), name))
            else:
                exact.setdefault(fold(word), name)
    prefixes.sort(key=lambda item: -len(item[0]))
    return exact, prefixes


@functools.cache
def _vocabulary():
    """The lists above, folded once, on first use."""
    from .edits import NUMBERS
    from .pages import WORDS
    return {
        'strong': _compile(INSTRUCTIONS), 'weak': _compile(WEAK),
        'colour_nouns': _compile({'colour_noun': COLOUR_NOUNS}),
        'function': _words(FUNCTION_WORDS) | {fold(word) for word in STOP},
        # Spelled counts as pages and edits read them; an article is not one.
        'numbers': {fold(word) for word in (*WORDS, *NUMBERS) if word not in ('a', 'an', 'another')},
        'slips': [(fold(word), name) for name, words in SLIPS.items() for word in words.split()],
        'not_slips': _words(NOT_SLIPS),
        'english': _words(ENGLISH) | {fold(word) for word in STOP if not CYRILLIC.search(word)},
        'real_words': set(REAL_WORDS.split()),
        'topic_before': _words(TOPIC_BEFORE), 'placeholder_names': _words(PLACEHOLDER_NAMES),
        'bind_next': _words(BIND_NEXT), 'style_before': _words(STYLE_BEFORE),
        'generic_before': _words(GENERIC_BEFORE), 'with': _words(WITH), 'joiners': _words(COLOUR_JOINERS),
        'topic_after': _words(TOPIC_AFTER), 'for': _words('uchun for'), 'open': _words('ochiq amaliy'),
        'into': _words('in into на'), 'bare_style': _words(BARE_STYLE), 'kurs': _words('kurs'),
        'kurs_work': _words(KURS_WORK),
    }


def _lookup(key, compiled):
    exact, prefixes = compiled
    if key in exact:
        return exact[key]
    if NOT_PREFIXED.match(key):
        return None
    for stem, name in prefixes:
        if key.startswith(stem):
            return name
    return None


def _one_edit(a, b):
    """Whether a and b are one insertion, deletion, substitution or swap apart."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        return len(diff) == 1 or (len(diff) == 2 and diff[1] == diff[0] + 1
                                  and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])
    short, long = (a, b) if len(a) < len(b) else (b, a)
    return any(long[:i] + long[i + 1:] == short for i in range(len(long)))


def _slip(key):
    vocabulary = _vocabulary()
    if len(key) < 4 or key in vocabulary['not_slips']:
        return None
    for target, name in vocabulary['slips']:
        if len(target) >= 5 and key[:2] == target[:2] and _one_edit(key, target):
            return name
    return None


@functools.lru_cache(maxsize=4096)
def _keys(word):
    """The keys a word is looked up by: itself folded and, typed in Cyrillic, in
    Latin too — for Uzbek, never as an English word."""
    keys = [fold(word)]
    if CYRILLIC.search(word):
        latin = fold(to_latin(word.lower()))
        if latin not in _vocabulary()['english']:
            keys.append(latin)  # Uzbek in Cyrillic
    return tuple(dict.fromkeys(keys))


@functools.lru_cache(maxsize=4096)
def _class(word):
    """(kind, strength) of one word; strength is 'strong', 'weak', 'function' or None (unknown)."""
    vocabulary = _vocabulary()
    keys = _keys(word)
    if word.isdigit():
        # A count has three digits at most (pages.NUMBER); "1945" is a subject.
        return ('number', 'strong') if len(word) <= 3 else (None, None)
    plain = normalised(word).lower().replace("'", '')
    if plain in vocabulary['real_words'] or (CYRILLIC.search(plain) and to_latin(plain) in vocabulary['real_words']):
        return None, None
    if keys[0] in vocabulary['numbers']:
        return 'number', 'strong'
    for key in keys:
        if key in vocabulary['function']:
            # In capitals it is an acronym, and a subject: "IT", "US".
            if len(word) > 1 and word.isupper():
                return None, None
            return 'function', 'function'
    for strength in ('strong', 'weak'):
        for key in keys:
            name = _lookup(key, vocabulary[strength])
            if name:
                return name, strength
    for key in keys:
        name = _slip(key)
        if name:
            return name, 'strong'
    return None, None


def _lines(body):
    """A description's lines, each read on its own, with "по-английски" made one word."""
    return PO_LANGUAGE.sub(' на английском ', body).split('\n')


def _tokens(line):
    vocabulary = _vocabulary()
    found = []
    for match in TOKEN.finditer(line):
        word = match.group(0)
        kind, strength = _class(word)
        keys = set(_keys(word))
        found.append({'word': word, 'span': match.span(), 'keys': keys, 'class': kind, 'strength': strength,
                      'colour_noun': any(_lookup(key, vocabulary['colour_nouns']) for key in keys)})
    return found


def _next(tokens, index, step):
    """The index of the nearest word that is not a function word, in one direction, or None."""
    index += step
    while 0 <= index < len(tokens):
        if tokens[index]['strength'] != 'function':
            return index
        index += step
    return None


def _neighbour(tokens, index, step):
    """The nearest word that is not a function word, in one direction."""
    found = _next(tokens, index, step)
    return None if found is None else tokens[found]


def _beside(tokens, index):
    return tokens[index]['keys'] if 0 <= index < len(tokens) else set()


def _colour_bound(tokens, index):
    """A run of colours ("och pushti", "ko‘k va oq") followed by a colour noun, a
    format, a look or a count ("rangda", "slayd"), or after "in"/"в" ("in blue")."""
    joiners = _vocabulary()['joiners']
    start = end = index
    # A colour may be led by a word that is one only before it: "light blue".
    while start > 0 and (tokens[start - 1]['class'] in ('colour', 'colour_before_noun')
                         or (tokens[start - 1]['keys'] & joiners and start > 1
                             and tokens[start - 2]['class'] == 'colour')):
        start -= 1
    while end + 1 < len(tokens) and (tokens[end + 1]['class'] == 'colour'
                                     or (tokens[end + 1]['keys'] & joiners and end + 2 < len(tokens)
                                         and tokens[end + 2]['class'] == 'colour')):
        end += 1
    after = _neighbour(tokens, end, 1)
    return bool((after and (after['colour_noun'] or after['class'] in ('format', 'style', 'unit')))
                or _beside(tokens, start - 1) & _vocabulary()['with'])


def _bound(tokens, index):
    """Whether a weak word is an instruction here, given the words beside it."""
    vocabulary = _vocabulary()
    kind = tokens[index]['class']
    before, after = _beside(tokens, index - 1), _beside(tokens, index + 1)
    previous, following = _neighbour(tokens, index, -1), _neighbour(tokens, index, 1)
    if kind == 'colour':
        return _colour_bound(tokens, index)
    if kind == 'colour_before_noun':
        # "havo rang", "oltin rangda", "light blue"; "Havo", "Oltin O‘rda" and "Light" are subjects.
        nearest = _next(tokens, index, 1)
        return bool(following and (following['colour_noun']
                                   or (following['class'] == 'colour' and _colour_bound(tokens, nearest))))
    if kind == 'picture':
        return bool(after & vocabulary['bind_next'] or before & vocabulary['with']
                    or before & vocabulary['style_before']
                    or (previous and previous['class'] in ('number', 'unit', 'style')))
    if kind == 'design':
        bare = bool(tokens[index]['keys'] & vocabulary['bare_style'])
        return bool(after & vocabulary['bind_next'] or before & vocabulary['style_before']
                    or before & vocabulary['with'] or (previous and previous['class'] == 'style' and not bare)
                    or (index and tokens[index - 1]['class'] in ('colour', 'colour_before_noun'))
                    or (following and following['class'] == 'style'))
    if kind == 'audience':
        return bool(after & vocabulary['for'] or before & vocabulary['with'] or before & vocabulary['open']
                    or (previous and previous['class'] == 'number')
                    or (tokens[index]['keys'] & vocabulary['kurs'] and following
                        and following['keys'] & vocabulary['kurs_work']))
    if kind == 'language':
        return bool((following and following['class'] == 'language' and following['strength'] == 'strong')
                    or before & vocabulary['into'])
    if kind == 'generic':
        return bool(after & vocabulary['bind_next'] or before & vocabulary['generic_before']
                    or (following and following['class'] in VERBS))
    if kind == 'ambiguous_verb':
        return bool(previous and previous['class'] in ('format', 'structure', 'unit', 'generic', 'number'))
    return False


def _slots(tokens):
    """Indexes of words in a topic slot: before "haqida", after "about", after "Mavzu:"."""
    vocabulary = _vocabulary()
    # The nearest word that is not a function word on each side, found in one
    # pass each way: "oid oid oid …" must not be walked back over for every word.
    previous, last = [], -1
    for index, token in enumerate(tokens):
        previous.append(last)
        if token['strength'] != 'function':
            last = index
    following, last = [0] * len(tokens), -1
    for index in range(len(tokens) - 1, -1, -1):
        following[index] = last
        if tokens[index]['strength'] != 'function':
            last = index
    slots, after_on = set(), set()
    for index, token in enumerate(tokens):
        if token['keys'] & vocabulary['topic_before'] and previous[index] >= 0:
            slots.add(previous[index])
        # "Mavzu bo‘yicha slayd": the word "topic" is in a slot itself, and names nothing.
        named = (token['keys'] & vocabulary['placeholder_names']
                 and not _beside(tokens, index + 1) & vocabulary['topic_before'])
        if (token['word'].lower() in vocabulary['topic_after'] or named) and following[index] >= 0:
            slots.add(following[index])
            if token['word'].lower() == 'on':
                after_on.add(following[index])
    # "PowerPoint haqida", "Mavzu: Word": the format is the subject. "A
    # presentation on PowerPoint" is made in it.
    return {index for index in slots if tokens[index]['class'] not in NOT_A_TOPIC
            or (tokens[index]['class'] == 'format' and index not in after_on)}


def _read(line):
    """Each word of one line as (token, verdict)."""
    tokens = _tokens(line)
    slots = _slots(tokens)
    rows = []
    for index, token in enumerate(tokens):
        if index in slots:
            verdict = 'TOPIC(slot)'
        elif token['strength'] == 'weak':
            verdict = 'instr' if _bound(tokens, index) else 'TOPIC(weak)'
        elif token['strength'] == 'strong':
            verdict = 'instr'
        elif token['strength'] == 'function':
            verdict = 'fn'
        else:
            verdict = 'TOPIC'
        rows.append((token, verdict))
    return rows


def explain(prompt):
    """Each word with how it was read, for checking the vocabulary: (word, kind, verdict)."""
    return [(token['word'], token['class'], verdict)
            for line in _lines(normalised(prompt or '')) for token, verdict in _read(line)]


# A program sent as the whole description is the lesson's subject ("Word" in an
# IT class), not the format of the file: a format alone is no request to make one.
PROGRAMS = {'word', 'powerpoint', 'ворд'}


def names_no_topic(prompt):
    """Whether every word of a description is an instruction, so it names no topic."""
    body = normalised(prompt or '')
    if not body.strip() or any(re.search(r'[^\W\d_]', match.group(1)) for match in QUOTED.finditer(body)):
        return False
    words = TOKEN.findall(PO_LANGUAGE.sub(' на английском ', body))
    # One unknown word is the topic: most descriptions stop here, long ones too.
    # Past LONGEST words nothing real is made of instructions alone, and reading
    # each word beside its neighbours would grow with the square of the length.
    if len(words) > LONGEST or any(_class(word)[1] is None for word in words):
        return False
    if len(words) == 1 and words[0].casefold() in PROGRAMS:
        return False
    if any(GRAMMAR_LESSON.search(line) for line in body.split('\n')):
        return False
    rows = explain(body)
    if any(verdict.startswith('TOPIC') for _, _, verdict in rows):
        return False
    return any(kind in ASKED for _, kind, _ in rows)


def asks_to_convert(prompt):
    """Whether a description names no topic and asks only for a file in another
    format ("pdf ga o‘tkaz", "convert to pdf", "переведи в pdf"): the file tools'
    work. A count may be said too; a look, a part or "topic" asks for a new document."""
    if not names_no_topic(prompt):
        return False
    tokens = [token for line in _lines(normalised(prompt)) for token in _tokens(line)]
    kinds = {token['class'] for token in tokens}
    return ('convert' in kinds and kinds <= CONVERT_ONLY
            and any(FILE_FORMAT.match(key) for token in tokens if token['class'] == 'format' for key in token['keys']))


def _without_topic(prompt):
    """The description with the words in its topic slots blanked: "PowerPoint
    haqida referat" asks for a referat, about PowerPoint."""
    lines = []
    for line in _lines(normalised(prompt or '')):
        rows = _read(line)
        spans = [token['span'] for token, verdict in rows if verdict == 'TOPIC(slot)']
        for start, end in reversed(spans):
            line = line[:start] + ' ' * (end - start) + line[end:]
        lines.append(line)
    return '\n'.join(lines)


def asked_other_service(prompt, feature_id):
    """The other AI service a description asks for, or ''.

    Slides asked for in the PDF tool name the Slides tool; a PDF or a document
    asked for in the Slides tool, with no slides named, names the PDF tool. A
    format that is the topic ("PowerPoint haqida referat") asks for nothing.
    The bot's review screen reads it the same way (telegram.generation.other_service).
    """
    from .domain import DOCUMENT, SLIDES
    from .pages import names_document, names_slides
    asked = _without_topic(prompt)
    if feature_id == DOCUMENT and names_slides(asked):
        return SLIDES
    if feature_id == SLIDES and names_document(asked) and not names_slides(asked):
        return DOCUMENT
    return ''


def restates(answer, kept):
    """Whether an answer to the topic question is a whole description of its own,
    so what was kept before it goes rather than being joined on.

    It is when it names a topic and also asks for the other format than what was
    kept ("A 3 page PDF report about volcanoes" after "10 slides please"), gives
    its own count where one was kept, or is a long request in its own right.
    Otherwise it is the topic, and what was kept still holds.
    """
    if not answer or not kept or names_no_topic(answer):
        return False
    from .pages import names_document, names_slides

    def kind(text):
        return 'slides' if names_slides(text) else 'document' if names_document(text) else ''

    earlier = '\n'.join(kept)
    mine, theirs = kind(_without_topic(answer)), kind(_without_topic(earlier))
    if mine and theirs and mine != theirs:
        return True
    tokens = [token for line in _lines(normalised(answer)) for token in _tokens(line)]
    if _counts(tokens) and _counts([token for line in _lines(normalised(earlier)) for token in _tokens(line)]):
        return True
    return len(tokens) > 8 and any(token['class'] in ('format', *VERBS) for token in tokens)


def _counts(tokens):
    """Whether the words say how many: a number before a unit or a format ("5 pages", "10 ta slayd")."""
    for index, token in enumerate(tokens):
        if token['class'] == 'number':
            after = _neighbour(tokens, index, 1)
            if after and after['class'] in ('unit', 'format'):
                return True
    return False
