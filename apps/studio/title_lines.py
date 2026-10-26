"""The lines a customer dictates for a deck's title slide, read from what they wrote, and kept on its cover.

Students put their own name, group, class and teacher on the first slide:
"Tayyorladi: … / Qabul qildi: …", "… 026-136-guruh deb yoz", "напиши в начале
слайда сделала: … 205-группа", "Birinchi betiga:" and a block of lines. Left
to the model they were dropped, merged ("Name · group") or never reached the
cover at all: a change request that kept the rest of the deck kept the old
cover too, and only one of five ways people ask for it was even recognised as
being about the title page.

So the lines are read here, without the model — but only where the text
plainly dictates them: after a label of who did the work ("Tayyorladi:",
"Выполнила:"), in "… deb yoz" aimed at the title, in a block under
"Birinchi betiga:" or "Ustki qismiga", or as a name beside a student group
("… 026-136-guruh"). A role ("Student:", "O'qituvchi:") or a place ("Guruh:")
is one only beside a byline in the same block, or under the title page named
for it. A name in the topic ("Aleksandr Pushkin 9-sinf uchun"), a fact list
("Rahbari: Amir Temur"), a cast, a credit, a lesson plan, a slide plan, a
heading, a caption, an example or template, another slide, or a line quoted to
come off is not one, and whatever is not read stays the model's to write, as
before: a line missed costs what it always did, a line misread is on the
customer's cover.

What is read is placed without taking anything away: a line the cover lacks
is added, a line the model wrote its own way ("Name · group") is put back as
the customer wrote it, and every other line of the cover stays. A change
request places the lines it dictates; one that dictates none leaves the cover
to the model, which is given the deck as it stands. A new deck's lines are
kept with its draft (options.title_lines) for one thing only: after the
outline, the cover the customer reviewed says which of them are theirs.
"""
import bisect
import functools
import itertools
import re

TITLE_LINES = 8
LINE_WORDS = 24
LINE_CHARS = 160
# How far round a label, a "deb" or a group a title line is looked for: a line
# is short, and a long request is read in time proportional to its length.
REACH = 300

APOSTROPHES = "ʻʼ’‘`´"
LETTER = r"[^\W\d_]"
# A word, apostrophes inside it ("To‘xtasinova", "o'quvchi"); a hyphen ends it, so "kerak-Ali" is two.
WORD = re.compile(rf"{LETTER}(?:{LETTER}|['{APOSTROPHES}](?={LETTER}))*")
I = re.IGNORECASE
QUOTES = '"“”«»„'


def _fold(text):
    """Apostrophes as one, the same length as `text`, so positions found in it are positions in `text`."""
    return str(text or '').translate({ord(mark): "'" for mark in APOSTROPHES})


# --- What labels a title line ------------------------------------------------
# Who did the work or checked it. With a colon or a dash these may come before
# any name; without one only at the start of a clause that holds a name.
PERSON_VERBS = (r"tayyorladi(?:lar)?|tayyorlovchi|tayyorlagan|bajardi(?:lar)?|bajaruvchi|bajargan"
                r"|qabul[ \t]+qildi|qabul[ \t]+qiluvchi|qabul[ \t]+qilgan|tekshirdi|tekshiruvchi|tekshirgan|topshirdi"
                r"|тайёрлади|тайёрловчи|бажарди|қабул[ \t]+қилди|текширди"
                r"|выполнила?|выполнили|сделала?|сделали|подготовила?|подготовили|проверила?|приняла?"
                r"|prepared[ \t]+by|done[ \t]+by|made[ \t]+by|presented[ \t]+by|submitted[ \t]+by|submitted[ \t]+to"
                r"|checked[ \t]+by")
PERSON_NOUNS = (r"o'?qituvchi(?:si)?|ustoz(?:i)?|ilmiy[ \t]+rahbar(?:i)?|rahbar(?:i)?|talaba(?:si)?|o'?quvchi(?:si)?"
                r"|tuzuvchi|f\.[ \t]?i\.[ \t]?sh\.?|(?-i:FISH|FIO)|ўқитувчи|ўқувчи|талаба|раҳбар"
                r"|преподаватель|учитель|научный[ \t]+руководитель|руководитель|студентк?а?|учени(?:к|ца)"
                r"|фио|ф\.[ \t]?и\.[ \t]?о\.?"
                r"|student|teacher|supervisor|instructor|lecturer|tutor")
PLACE_NOUNS = (r"maktab|litsey|kollej|universitet|institut|akademiya|fakultet|kafedra|yo'nalish|guruh|sinf|kurs"
               r"|мактаб|гуруҳ|синф|курс|факультет|кафедра|йўналиш"
               r"|школа|лицей|колледж|университет|институт|академия|направление|группа|класс"
               r"|school|university|faculty|department|group|class|grade")
# A name asked for in passing: "Ismimni ham yoz: …", "My name: …", "O'qituvchimning ismini qo'sh: …".
NAME_NOUNS = r"(?:ism|familiya|исм|фамили|имя|имени|full[ \t]+name|name)\w*(?:[ \t]+[\w']+){0,3}?"
LABEL = re.compile(rf"(?<![\w'])(?:(?P<verb>{PERSON_VERBS})(?![\w'])(?P<vsep>[ \t]{{0,2}}[:\-–—])?"
                   rf"|(?P<person>{PERSON_NOUNS})[ \t]{{0,2}}:|(?P<place>{PLACE_NOUNS})[ \t]{{0,2}}:"
                   rf"|(?P<name>{NAME_NOUNS})[ \t]{{0,2}}:)[ \t]{{0,3}}", I)
VERB_WORD = re.compile(rf"(?:{PERSON_VERBS})", I)
# A name label that is the customer's own: "My name:", "Ismimni yoz:", "O'qituvchimning ismini qo'sh:" —
# never "My hero's name:" or "Mening qahramonim ismi:".
OWN_LABEL = re.compile(r"(?<![\w'])(?:(?:mening|my|моё|мое|моя|мою)[ \t]+(?:full[ \t]+|to'liq[ \t]+)?(?:ism\w*|familiya\w*|name"
                       r"|имя|фамилия|фамилию|фио)|to'liq[ \t]+ismim\w*|ismim\w*|familiyam\w*|ism[ \t-]*familiyam\w*"
                       r"|исмим\w*|фамилиям\w*|(?:o'?qituvchim|ustozim|rahbarim)\w*[ \t]+(?:ism|familiya)\w*)(?![\w'])", I)
# Whose name: the customer's own — "mening ismim", "ismimni", "my name", "моё имя", "o'qituvchimning".
# Never a writer's or a singer's ("Yozuvchi ismi:", "Olimning familiyasi:"), whatever the request asks to write.
OWN_NAME = re.compile(r"(?<![\w'])(?:mening|my|моё|мое|мою|моя|ism(?:im|imni|imiz|imizni)|familiya(?:m|mni|miz)"
                      r"|исм(?:им|имни)|фамили(?:ям|ямни)|(?:o'?qituvchim|ustozim|rahbarim)(?:ning|iz|izning)?)(?![\w'])", I)
GROUP_NOUN = re.compile(r"(?:guruh|гуруҳ|группа|group|sinf|синф|класс|class|grade|kurs|курс)", I)

# A student's group as students write it: "026-136-guruh", "205- группа", "группа 301", "302-гуруҳ".
GROUP = re.compile(r"(?<![\w'])(?:\d{2,3}(?:[ \t]{0,2}[-–][ \t]{0,2}\d{2,3})?[ \t]{0,2}[-–]?[ \t]{0,2}"
                   r"(?:[a-zа-я][ \t]{0,2}[-–]?[ \t]{0,2})?(?:guruh\w*|гуруҳ\w*|групп\w*|grupp\w*|group)"
                   r"|(?:guruh|гуруҳ|группа|группы|gruppa|gruppy|group)[ \t]{0,2}(?:№[ \t]{0,2})?\d{2,3}"
                   r"(?:[ \t]{0,2}[-–][ \t]{0,2}\d{2,3})?)(?![\w'])", I)
# A class or year, kept with a name it follows but never enough alone: "9-sinf uchun" is an audience.
CLASS = re.compile(r"(?<![\w'])\d{1,2}[ \t]{0,2}[-–]?[ \t]{0,2}(?:[«\"“]?[a-zа-я][»\"”]?[ \t]{0,2}[-–]?[ \t]{0,2})?"
                   r"(?:sinf\w*|синф\w*|класс\w*|kurs\w*|курс\w*|bosqich\w*|босқич\w*|grade)(?![\w'])", I)
AUDIENCE = re.compile(r"[ \t,]{0,3}(?:[\w']+[ \t]){0,2}(?:uchun|учун|для|for)(?![\w'])", I)
CONNECTOR = re.compile(r"(?:talaba(?:si)?|o'?quvchi(?:si)?|студент(?:ка|ки|а)?|учени(?:к|ца|ка|цы)|student|pupil)", I)

# "… deb yoz", "… deb yozib qo'y", "… deb kiriting": an order to write it, never "deb yozgan" (said).
DEB = re.compile(r"(?<![\w'])(?:deb|деб)(?![\w'])", I)
DEB_VERB = re.compile(r"[ \t]{1,3}(?:[\w']+[ \t]{1,3}){0,4}?(?:yozib[ \t]+(?:qo'?y|ber)(?:ing|ib|sangiz|ib[ \t]+bering)?|yozing|yozilsin"
                      r"|yozvor\w*|yoz|qo'?ying|qo'?y|kiriting|kirit|belgila|ёзиб[ \t]+қўй|ёзинг|ёз|қўйинг|қўй)(?![\w'])", I)
WRITE = re.compile(r"(?:ism|familiya|yoz|qo'y|ёз|исм)", I)
# Where a title line goes: what a "deb" aims at.
TITLE_PLACE = re.compile(r"(?<![\w'])(?:birinchi[ \t]+(?:bet|sahifa|slayd|varaq|list)\w*"
                         r"|1[ \t]?[-–]?[ \t]?(?:bet|sahifa|slayd|varaq|list)\w*|boshi(?:ga|da|dagi)|oldiga|titul\w*"
                         r"|muqova\w*|ustki[ \t]+qism\w*|yuqori[ \t]+qism\w*|биринчи[ \t]+(?:бет|слайд|саҳифа)\w*|бошига"
                         r"|титул\w*|титульн\w*|обложк\w*|перв\w*[ \t]+(?:слайд|страниц|лист)\w*"
                         r"|в[ \t]+начал\w*[ \t]+(?:слайда|презентации)|first[ \t]+(?:slide|page)|title[ \t]+(?:slide|page)"
                         r"|cover[ \t]+(?:slide|page)|on[ \t]+the[ \t]+cover)", I)
# Somewhere other than the title slide: another or the last slide, every slide, the conclusion, under a picture.
OTHER_SLIDE = re.compile(r"(?<![\w'])(?:(?:[2-9]|[1-9]\d)[ \t]?[-–][ \t]?(?:slayd|bet|sahifa|слайд|бет|саҳифа|страниц)"
                         r"(?:ga|da|dan|dagi|ning|ni|iga|ida|е|у|а|ы|га|да|дан)?"
                         r"|(?:ikkinchi|uchinchi|to'rtinchi|beshinchi|oltinchi|oxirgi|ohirgi|keyingi|so'nggi|songgi|sungi"
                         r"|иккинчи|учинчи"
                         r"|охирги|кейинги)[ \t]+(?:slayd|bet|sahifa|varaq|слайд|бет|саҳифа)\w*"
                         r"|(?:втор|трет|четв[её]рт|пят|последн|следующ)\w*[ \t]+(?:слайд|страниц|лист)\w*"
                         r"|(?:second|third|fourth|fifth|last|final|next)[ \t]+(?:slide|page)s?"
                         r"|(?:slide|page|slayd|слайд)[ \t]+(?:№[ \t]?)?(?:[2-9]|[1-9]\d)|(?:eng[ \t]+)?o[xh]ir(?:i|ida|iga|gi)"
                         r"|охир(?:и|ида|ига|ги)|в[ \t]+конце|at[ \t]+the[ \t]+end"
                         r"|har[ \t]+(?:bir[ \t]+)?(?:slayd|bet|sahifa)\w*|ҳар[ \t]+бир[ \t]+(?:слайд|бет)\w*|кажд\w*[ \t]+слайд\w*"
                         r"|(?:every|each|all)[ \t]+(?:the[ \t]+)?(?:slides?|pages?)|pastki[ \t]+qism\w*|пастки[ \t]+қисм\w*"
                         r"|(?<![\w'-])(?!(?:birinchi|bosh\w*|titul\w*|muqova\w*|1|ta|bitta)[ \t])[\w'-]{1,24}[ \t]+slayd(?:i|ga|iga|ida|da|ini)"
                         r"|barcha[ \t]+slayd\w*|на[ \t]+(?:всех|каждом)[ \t]+слайд\w*|на[ \t]+слайде(?=[ \t]+[«\"])"
                         r"|(?:thank[\w-]*|contents|intro\w*|closing|final|questions?)[ \t]+slide"
                         r"|(?:rasm|surat|portret|расм|сурат|портрет)\w*[ \t]+(?:tag|ost|past|таг|ост|паст)\w*"
                         r"|(?:under|below)[ \t]+(?:the[ \t]+)?(?:picture|image|photo|portrait)\w*|под[ \t]+(?:фото|картинк|рисунк)\w*"
                         r"|imzo\w*|имзо\w*|caption\w*|подпис\w*|jadval\w*|жадвал\w*|таблиц\w*|table"
                         r"|in[ \t]+the[ \t]+(?:conclusion|summary|end)|в[ \t]+заключени\w*|xulosa(?:ga|da|sida|siga)"
                         r"|хулоса(?:га|да|сида|сига)"
                         r"|(?:xulosa|reja|xotima|savol\w*|хулоса|режа|заключени\w*|план\w*|conclusion|summary|questions?)"
                         r"[ \t]+(?:slayd|qism|bet|слайд|қисм|бет|slide|page)\w*)(?![\w'])", I)
# What a "deb" names that is not a person on the title page: a heading, the topic, a slide's name, a quotation.
NAMING = re.compile(r"(?<![\w'])(?:sarlavha\w*|mavzu(?:ni|si|sini|ga|siga)|mavzu[ \t]+(?:sifatida|qilib)|nom(?:i|ini|iga|ga|lan\w*)"
                    r"|iqtibos\w*"
                    r"|в[ \t]+качестве[ \t]+(?:темы|заголовка|названия)|as[ \t]+(?:the[ \t]+)?(?:topic|title|heading)"
                    r"|she'r\w*|xulosa\w*|сарлавҳ\w*|мавзу(?:ни|си|сини|га|сига)|ном(?:и|ини|ига|га)|иқтибос\w*|шеър\w*"
                    r"|хулоса\w*|заголов\w*|тем[ауы]|цитат\w*|heading\w*|quote\w*)(?![\w'])", I)
ELSEWHERE = re.compile(rf"{OTHER_SLIDE.pattern}|{NAMING.pattern}", I)
# Where the title page plainly is: never "boshida" alone ("Har bir slayd boshida savol").
TITLE_PAGE = re.compile(r"(?<![\w'])(?:birinchi[ \t]+(?:bet|sahifa|slayd|varaq)\w*"
                        r"|1[ \t]?[-–]?[ \t]?(?:bet|sahifa|slayd|varaq)\w*|titul(?:ga|da|ni|[ \t]+(?:varag|sahifa|bet|slayd)\w*)"
                        r"|muqova(?:ga|da|ni|[ \t]+(?:sahifa|slayd)\w*)|ustki[ \t]+qism\w*"
                        r"|биринчи[ \t]+(?:бет|слайд|саҳифа)\w*|титул(?:га|да)|титульн\w*[ \t]+(?:лист|слайд|страниц)\w*|титульник\w*"
                        r"|перв\w*[ \t]+слайд\w*|на[ \t]+1[ \t]*-?(?:м|ом)?[ \t]+слайд\w*|в[ \t]+начал\w*[ \t]+(?:слайда|презентации)"
                        r"|first[ \t]+slide|title[ \t]+(?:slide|page)|cover[ \t]+(?:slide|page)|on[ \t]+the[ \t]+cover)", I)
# A block of title lines after where it goes: "Birinchi betiga:", "Titulga:", "На титульном листе:".
BLOCK = re.compile(r"(?<![\w'])(?:birinchi[ \t]+(?:bet|sahifa|slayd|varaq|list)\w*"
                   r"|1[ \t]?[-–]?[ \t]?(?:bet|sahifa|varaq|list|slayd)\w*|titul(?:ga|da|[ \t]+(?:varaq|varag|sahifa|bet|slayd)[\w']*)"
                   r"|titul(?=[ \t]{0,2}:[ \t]*\n)|титул(?=[ \t]{0,2}:[ \t]*\n)|титульн\w*[ \t]+(?:лист|слайд|страниц)\w*"
                   r"|muqova(?:ga|da|[ \t]+(?:sahifa|slayd)\w*)|на[ \t]+1[ \t]*-?(?:м|ом)?[ \t]+слайд\w*"
                   r"|slide[ \t]+1(?!\d)|1st[ \t]+(?:slide|page)|first[ \t]+page"
                   r"|boshi(?:ga|da)[ \t]+(?:yoz|qo'sh|qo'y|kirit)\w*"
                   r"|биринчи[ \t]+(?:бет|слайд|саҳифа)\w*|титул(?:га|да)|титульник\w*"
                   r"|на[ \t]+перв\w*[ \t]+(?:слайд|лист|страниц)\w*|на[ \t]+титульн\w*(?:[ \t]+\w+)?|на[ \t]+(?:титуле|обложке)"
                   r"|first[ \t]+slide|title[ \t]+(?:slide|page)|cover[ \t]+(?:slide|page)|on[ \t]+the[ \t]+cover)"
                   r"(?:[ \t]+[\w']+){0,3}[ \t]{0,2}:", I)
STANDALONE = re.compile(r"(?i)(?<![\w'])(?:ustki|yuqori|устки|юқори)[ \t]+(?:qism|қисм)\w*[ \t]{0,2}:?[ \t]{0,3}")
# A title page asked not to be: "Titul kerak emas", "no title slide", "Титульный слайд не нужен", "birinchi slaydni o'chir".
NO_TITLE = re.compile(r"(?<![\w'])(?:kerak[ \t]*emas|kerakmas|bo'lmasin|titulsiz|o'chir\w*|olib[ \t]+tashla\w*|не[ \t]+нуж\w*"
                      r"|без|убери\w*|удали\w*|no|not[ \t]+needed|without|remove|delete|mavzu\w*|тем[ауы]|topic|фото|rasm\w*"
                      r"|portret\w*|picture|photo|image|rang\w*|colou?r\w*|цвет\w*|фон\w*|fon|background|xarita\w*|карт[ауые]"
                      r"|map|flag|bayroq\w*|флаг\w*|logo\w*|логотип\w*|dark|blue|green|red|ko'k|qizil|yashil|тёмн\w*|темн\w*)(?![\w'])", I)
# A slide plan names its first slide too: "1-slayd: …\n2-slayd: …" is the deck's plan, not its title.
PLAN = re.compile(r"(?:^|\n|[,;.])[ \t•*\-–]{0,4}(?:(?:[2-9]|1\d)[ \t]?[-–.)][ \t]?(?:slayd|слайд|slide|bet|бет)\w*"
                  r"|(?:slayd|слайд|slide)[ \t]?(?:[2-9]|1\d)|ikkinchi[ \t]+slayd\w*|второй[ \t]+слайд\w*"
                  r"|second[ \t]+slide)[ \t]{0,2}[:\-–—)]", I)
# What a title page is headed with, on a line of its own above the names.
HEADERS = re.compile(r"(?i)^[ \t•\-–]*(?:mustaqil[ \t]+(?:ish|ta'lim)|referat|taqdimot|kurs[ \t]+ishi|amaliy[ \t]+ish"
                     r"|laboratoriya[ \t]+ishi|мустақил[ \t]+иш|самостоятельная[ \t]+работа|реферат|курсовая[ \t]+работа"
                     r"|доклад|independent[ \t]+work|report|essay)[ \t.!]*$")
# What asks for something rather than being a line of the title page.
ASKS = re.compile(r"(?<![\w'])(?:\d+[ \t]?ta\b|slayd\w*|rasm\w*|surat\w*|portret\w*|rang\w*|reja\w*|bo'lsin|kerak|qil\w*"
                  r"|qo'sh\w*|fon\w*|dizayn\w*|savol\w*|haqida\w*|ma'lumot\w*|tushuntir\w*|ber(?:ing|adi)?|yoz(?:ing)?"
                  r"|слайд\w*|нужн\w*|сделай\w*|добав\w*|рисун\w*|картин\w*|фото\w*|портрет\w*|цитат\w*|цвет\w*"
                  r"|план\w*|биограф\w*|напиши|отвеча\w*|объясн\w*"
                  r"|slides?|add|make|picture\w*|image\w*|photo\w*|portrait\w*|quote\w*|colou?r\w*|design\w*"
                  r"|questions?|explain\w*|please|about|biography)(?![\w'])", I)
# What a customer says before the name they dictate: "Ismimni …", "Mening ismim …", "было: …".
ASKING_WORDS = re.compile(r"^(?:(?:mening|men|meni|ismim\w*|ismimni|familiyam\w*|ism[ \t]+familiyam\w*|taqdimotni|uni"
                          r"|было|будет|моё[ \t]+имя|мое[ \t]+имя|my[ \t]+name(?:[ \t]+is)?|name"
                          r"|iltimos|илтимос|пожалуйста|please|yana|endi|keyin|avval|unga|salom|assalomu[ \t]+alaykum|ism|исм|имя"
                          r"|привет|здравствуйте|hello|hi)[ \t,:!]+)+", I)
# A request that takes something off: "ismimni olib tashla", "убери «Проверила: …»", "remove my name".
REMOVAL = re.compile(r"(?<![\w'])(?:olib[ \t]+tashla(?!ma)\w*|chiqarib[ \t]+tashla(?!ma)\w*|olib[ \t]+qo'y\w*"
                     r"|o'chir(?!ma)\w*|kerak[ \t]*emas|kerakmas|yozma\w*|bo'lmasin|qo'yma\w*|(?:ism|familiya|nom)\w*siz"
                     r"|yo'q[ \t]+qil\w*|yo'qot\w*|ketkaz\w*|yozilmasin|олиб[ \t]+ташла(?!ма)\w*|ўчир(?!ма)\w*|керак[ \t]*эмас"
                     r"|йўқ[ \t]+қил\w*|ёзма\w*|leave[ \t]+out|hide|don't[ \t]+(?:put|write|add)"
                     r"|убер\w*|убра\w*|удал\w*|сотр\w*|стер\w*|не[ \t]+(?:пиши|надо|нужн\w*)"
                     r"|без[ \t]+(?:имени|имён|имен|фамили\w*|фио)|remove\w*|delete\w*|take[ \t]+(?:[\w']+[ \t]+){0,2}(?:off|out)"
                     r"|get[ \t]+rid|without[ \t]+(?:my[ \t]+|the[ \t]+)?names?|no[ \t]+names?)(?![\w'])", I)
# A removal said not to happen: "Ismimni o'chirma", "don't remove my name", "не удаляй".
NOT_REMOVED = re.compile(r"(?<![\w'])(?:don't|do[ \t]+not|never|не)[ \t]+(?:\w+[ \t]+)?(?:remove|delete|take|убира\w*|убер\w*"
                         r"|удаля\w*|удал\w*|стира\w*)", I)
# A value that says what is not, or will be, rather than who: "Karimov Ali emas, matnni o'zgartir".
NOT_A_VALUE = re.compile(r"(?<![\w'])(?:emas|o'rniga|не|вместо|not|instead|will|should|would|qil\w*|o'zgartir\w*)(?![\w'])", I)
REPLACED = re.compile(r"(?<![\w'])(?:o'rniga|emas|вместо|instead[ \t]+of)(?![\w'])[ \t,]*", I)
# Words that name the work, said before who did it: "Работу выполнила …", "Taqdimotni … tayyorladi".
WORK_WORDS = re.compile(r"(?:работу|работа|презентацию|ishni|taqdimotni|slaydni|the[ \t]+presentation|this[ \t]+work)", I)
ABBREVIATION = re.compile(r"(?<![\w'])(?:dots|prof|dok|akad|dr|mr|mrs|ms|st|gr|sh|ass|доц|проф|ст|преп|акад|гр|г|ш"
                          r"|f\.f\.d|i\.f\.n|p\.f\.d|т\.н|к\.т\.н)$", I)

SURNAME = re.compile(r"(?:ov|ova|ev|eva|yev|yeva|in|ina|skiy|skaya|ovna|evna|ovich|evich|zoda|zade"
                     r"|ов|ова|ев|ева|ин|ина|ский|ская|овна|евна|ович|евич|зода|заде)$", I)
PATRONYMIC = re.compile(r"^(?:qizi|qiz|kizi|o'?g'?l[iu]|ogl[iu]|ug'?l[iu]|кизи|қизи|угли|ўғли|уғли)$", I)
# The endings that make a surname without doubt, beside a group with nothing else to say whose it is.
STRONG_SURNAME = re.compile(r"(?:ov|ova|ev|eva|yev|yeva|ovna|evna|ovich|evich|zoda|zade|ов|ова|ев|ева|овна|евна|ович|евич"
                            r"|зода|заде)$", I)
GIVEN_NAME_ENDING = re.compile(r"(?:ddin|ддин)$", I)


PLACE_STEM = re.compile(r"(?:titul|muqova|bet|sahifa|slayd|varaq|bosh|tepa|oxir|jadval|rasm|qism)", I)


def _surname(word):
    """Whether `word` (folded) is a surname or patronymic: "Karimova", "Ivanovich", "qizi" — not "in" or "Jaloliddin"."""
    stem = CASE_ENDING.sub('', word) if len(word) > 6 else word
    if stem != word and PLACE_STEM.fullmatch(stem):
        return False
    return bool(PATRONYMIC.match(word)) or any(
        len(form) >= 4 and SURNAME.search(form) and not GIVEN_NAME_ENDING.search(form) for form in {word, stem})
CASE_ENDING = re.compile(r"(?:ning|ni|ga|da|dan|man|miz)$", I)
NOT_NAMES = re.compile(r"^(?:universitet\w*|institut\w*|respublika\w*|davlat\w*|akademiya\w*|maktab\w*|litsey\w*"
                       r"|университет\w*|институт\w*|республик\w*|государств\w*|university|institute|state|republic)$", I)
# What an organisation is called by: never a person's line.
ORGANISATION = re.compile(r"(?<![\w'])(?:bank\w*|organi[sz]ation\w*|center|centre|council|assembly|committee|ministry|agency"
                          r"|foundation|corporation|company|inc|ltd|llc|union|nations|kengash\w*|assambleya\w*|qo'mita\w*"
                          r"|vazirlig\w*|agentlig\w*|jamg'arma\w*|kompaniya\w*|markaz\w*|tashkilot\w*|банк\w*|организаци\w*"
                          r"|центр\w*|совет\w*|ассамбле\w*|комитет\w*|министерств\w*|агентств\w*|фонд\w*|корпораци\w*"
                          r"|компани\w*|оон|юнеско|who|un|unesco|universitet\w*|university|университет\w*)(?![\w'])", I)


def _capital(word):
    return word[:1].isupper()


ACCUSATIVE = re.compile(r"ni$", I)
ORDER_WORD = re.compile(r"(?:deb|деб|yoz|yozib|yozing|yozilsin|yozvor\w*|qo'?y|qo'?ying|qo'?sh|qo'?shing|kirit\w*|ёз\w*"
                        r"|напиши|впиши|write|please|iltimos|sinov\w*|tanlov\w*)", I)


@functools.lru_cache(maxsize=20000)
def _not_a_name_word(word):
    """A word that cannot be part of a name: a label, an asking word, an Uzbek accusative ("Taqdimotni")."""
    folded = _fold(word)
    if (VERB_WORD.fullmatch(folded) or ASKING_WORDS.match(folded + ' ') or WORK_WORDS.fullmatch(folded)
            or ORDER_WORD.fullmatch(folded)):
        return True
    return bool(ACCUSATIVE.search(folded)) and not SURNAME.search(folded[:-2])


# A word a request puts before a name that is not part of it: "Titulga …", "Boshiga …", "Iltimos …", "Salom …".
LEAD_WORD = re.compile(r"(?:(?:titul|muqova|bosh|bet|sahifa|slayd|varaq|tepa|yuqori|o[xh]ir|past|ust|old|qism|jadval|rasm"
                       r"|taqdimot|joy|qator)\w*(?:ga|ka|qa|da|dagi|dan)|iltimos|илтимос|yana|endi|keyin|avval|unga|salom"
                       r"|assalomu|alaykum|привет|здравствуйте|пожалуйста|please|hello|hi|dear|вверх\w*|вверху|наверху)", I)


def _name_runs(text, start=0, end=None, lower=False):
    """Spans of people's names in text[start:end]: two to five words, one a surname or patronymic.

    Capitalised words make a run; `lower` lets lower-case ones in too, for the
    value of a label ("Tayyorladi: tursunova nilufar"). A label word ends a run
    ("Tayyorladi Sobirova Madina" is a label and a name). A run starts at most
    one given name before its surname, two before a patronymic ("Dilnoza Aziz
    qizi"), and never at a word a request puts before a name ("Titulga …").
    """
    end = len(text) if end is None else end
    runs, current = [], []
    for match in WORD.finditer(text, start, end):
        word = match.group(0)
        gap = text[current[-1].end():match.start()] if current else ''
        # "A. Rahimova": an initial and its full stop join a name; "Rasulova-Karimova" is one surname.
        joined = current and (re.fullmatch(r"[ \t]+", gap)
                              or (len(current[-1].group(0)) == 1 and re.fullmatch(r"\.[ \t]*", gap))
                              or (gap == '-' and _capital(word) and _capital(current[-1].group(0))))
        fits = ((_capital(word) or lower or (current and PATRONYMIC.match(_fold(word))))
                and not _not_a_name_word(word))
        if fits and (joined or not current):
            current.append(match)
            continue
        runs.append(current)
        current = [match] if fits else []
    runs.append(current)
    found = []
    for run in runs:
        words = [_fold(match.group(0)) for match in run]
        if any(NOT_NAMES.match(word) for word in words):
            continue
        named = [index for index, word in enumerate(words) if _surname(word)]
        if not named:
            continue
        # "Sobirova Madina": "-ina" here is the given name; the surname that leaves no doubt sets the order.
        named = [index for index in named if STRONG_SURNAME.search(CASE_ENDING.sub('', words[index]) or words[index])
                 or STRONG_SURNAME.search(words[index]) or PATRONYMIC.match(words[index])] or named
        # "Surname Given …" leaves nothing before the surname a name ("Inflyatsiya Ergasheva Malika"); "Given
        # Surname" may have two given names before it ("Muhammad Ali Valiyev", "Ким Ольга Николаевна").
        tail = list(range(named[0] + 1, len(words)))
        if tail and PATRONYMIC.match(words[tail[-1]]):
            tail = tail[:-2]  # "… Anvar qizi": the father's name and its word
        first = named[0] if any(index not in named for index in tail) else max(0, named[0] - 2)
        # Only while a whole name is left: "Farida Karimova" keeps its "-da".
        while (first < named[0] and (LEAD_WORD.fullmatch(words[first]) or NOT_QUALIFIER.fullmatch(words[first]))
               and not _surname(words[first]) and len(words) - first - 1 >= 2):
            first += 1
        run, words = run[first:], words[first:]
        # A hyphenated surname is one word of the name.
        size = len(run) - sum(1 for a, b in zip(run, run[1:]) if text[a.end():b.start()] == '-')
        if 2 <= size <= 5:
            found.append((run[0].start(), run[-1].end()))
    return found


class _Scan:
    """One text read once — its names and groups — and asked about by position."""

    def __init__(self, text):
        self.text, self.folded = text, _fold(text)
        self.runs = _name_runs(text)
        self.run_starts = [start for start, _ in self.runs]
        self.groups = [(m.start(), m.end()) for m in GROUP.finditer(self.folded)]
        self.group_starts = [start for start, _ in self.groups]
        # Where each kind of word is, found once: a reader asks only whether one lies in a stretch.
        self.found = {name: [(m.start(), m.end()) for m in pattern.finditer(self.folded)]
                      for name, pattern in (('asks', ASKS), ('elsewhere', ELSEWHERE), ('title', TITLE_PLACE),
                                            ('class', CLASS), ('label', LABEL), ('other', OTHER_SLIDE), ('page', TITLE_PAGE),
                                            ('example', EXAMPLE))}
        self.found_starts = {name: [start for start, _ in spans] for name, spans in self.found.items()}
        self.taken = {}  # whether a sentence asks to take something off, by where it is
        # A request that names the title page, opens a block for it or heads it ("Mustaqil ish").
        self.titled = bool(any(not NO_TITLE.search(self.folded, *_clause(self.folded, match.start(), match.end()))
                               for match in TITLE_PAGE.finditer(self.folded))
                           or STANDALONE.search(self.folded)
                           or any(_block_header(self.folded, match) for match in BLOCK.finditer(self.folded)))

    def within(self, name, start, end):
        """The `name` matches lying wholly in [start, end)."""
        spans = self._between(self.found_starts[name], self.found[name], start, end)
        return [span for span in spans if span[1] <= end]

    def has(self, name, start, end):
        return bool(self.within(name, start, end))

    @staticmethod
    def _between(starts, items, start, end):
        return items[bisect.bisect_left(starts, start):bisect.bisect_left(starts, end)]

    def names(self, start, end):
        return [run for run in self._between(self.run_starts, self.runs, start, end) if run[1] <= end]

    def has_name(self, start, end):
        return bool(self.names(start, end))

    def groups_in(self, start, end):
        return [group for group in self._between(self.group_starts, self.groups, start, end) if group[1] <= end]


# --- Reading the lines ---------------------------------------------------------


def _clause(folded, start, end, marks='.!?\n;'):
    """The clause round [start, end): from the last sentence end before it to the next one after it."""
    reach = max(0, start - REACH)
    before = max(folded.rfind(mark, reach, start) for mark in marks)
    after = [position for position in (folded.find(mark, end, end + REACH) for mark in marks.replace(':', ''))
             if position >= 0]
    return before + 1 if before >= 0 else reach, min(after) if after else min(len(folded), end + REACH)


DESIGNATION_WORDS = re.compile(
    r"(?:va|and|и|ham|hamda|shahar\w*|tuman\w*|viloyat\w*|maktab\w*|litsey\w*|kollej\w*|universitet\w*|institut\w*"
    r"|akademiya\w*|fakultet\w*|kafedra\w*|yo'nalish\w*|kurs\w*|sinf\w*|guruh\w*|o'?quvchi\w*|talaba\w*|bitiruvchi\w*"
    r"|dotsent\w*|professor\w*|katta|o'qituvchi\w*|assistent\w*|magistr\w*|bakalavr\w*|PhD|bosqich\w*|mudir\w*|fan"
    r"|магистр\w*|босқич\w*|мудир\w*|фан"
    r"|мактаб\w*|синф\w*|гуруҳ\w*|ўқувчи\w*|талаба\w*|курс\w*|школ\w*|лице\w*|колледж\w*|университет\w*|институт\w*"
    r"|академи\w*|факультет\w*|кафедр\w*|направлени\w*|групп\w*|класс\w*|студент\w*|учени\w*|доцент\w*|профессор\w*"
    r"|преподаватель\w*|старш\w*|город\w*|г|school|university|institute|college|faculty|department|group|class|grade"
    r"|year|student|pupil|associate|assistant|senior|lecturer|professor)", I)


YEAR = re.compile(r"(?<![\d\-–])(?:1[5-9]|20)\d\d(?![\d\-–])")
INSTITUTION = re.compile(r"(?:maktab\w*|litsey\w*|kollej\w*|universitet\w*|institut\w*|akademiya\w*|fakultet\w*|kafedra\w*"
                         r"|мактаб\w*|школ\w*|лице\w*|колледж\w*|университет\w*|институт\w*|академи\w*|факультет\w*"
                         r"|кафедр\w*|school|university|institute|college|faculty|department)", I)


def _designation(folded, start, end):
    """Whether folded[start:end] says where or what someone studies or teaches: a group, class, school, faculty, title.

    "302-guruh", "11 «A» sinf o'quvchisi", "Iqtisodiyot fakulteti 2-kurs
    talabasi", "(302-guruh)", "i.f.n., dotsent" — the words that may sit
    beside a name on a title page. Capitalised words count only before the
    school or faculty they name ("Toshkent shahar 45-maktab").
    """
    piece = folded[start:end]
    if not piece.strip(' \t,()'):
        return False
    if re.search(r"(?<![\w'.])(?:men|biz|я|мы)(?![\w'.])", piece, I) or re.search(r"(?:man|miz)(?![\w'])", piece, I):
        return False  # "Men 302-guruh talabasiman": the customer speaking
    covered = [(m.start(), m.end()) for m in GROUP.finditer(piece)] + [(m.start(), m.end()) for m in CLASS.finditer(piece)]
    # A year is when something happened, not who someone is: "Charles Darwin in 1859".
    if any(not any(a <= m.start() < b for a, b in covered) for m in YEAR.finditer(piece)):
        return False
    words = [m for m in WORD.finditer(piece) if not any(a <= m.start() < b for a, b in covered)]
    for index, match in enumerate(words):
        word = match.group(0)
        if DESIGNATION_WORDS.fullmatch(word) or len(word) == 1 or ABBREVIATION.search(word):
            continue
        if ACCUSATIVE.search(word) and not WORK_WORDS.fullmatch(word) and not SURNAME.search(word[:-2]):
            return False  # "Tadbirni …": the thing done
        if ((word.isupper() and len(word) <= 6 and not piece.isupper())
                or re.match(r"[-–]?\d|(?:st|nd|rd|th)(?![\w'])", piece[match.end():match.end() + 3])):
            continue  # "TDIU", "СОШ", "MT-21", "11th"
        if word.isupper() and len(word) <= 6 and index and GROUP_NOUN.match(words[index - 1].group(0)):
            continue  # "группа ИВТ-21"
        following = words[index + 1:index + 4]
        if any(INSTITUTION.fullmatch(other.group(0)) for other in following) or (
                _capital(word) and any(DESIGNATION_WORDS.fullmatch(other.group(0)) for other in following[:2])):
            continue  # "Navoiy davlat pedagogika instituti", "Iqtisodiyot fakulteti", "Toshkent shahar"
        return False
    return not re.search(r"[!?]", piece)


def _initial(text, start, cut):
    """Whether text[start:cut] ends with a one-letter word: the initial of "N. Karimova"."""
    words = WORD.findall(text[max(start, cut - 3):cut])
    return bool(words) and len(words[-1]) == 1 and not text[max(start, cut - 2):cut - 1].strip(" \t'")[-1:].isalpha()


VALUE_STOP = re.compile(r"\n|;|[ \t]/[ \t]|(?<![\w'])(?:deb|деб|bo'lsin|yozilsin|yozing|yozib|qilib|напиши|допиши|please"
                        r"|iltimos)(?![\w'])", I)


def _value_end(text, folded, start, end):
    """Where a labelled value ends: at the line, the next label, a "deb", or a clause that asks for more."""
    line_end = end
    found = VALUE_STOP.search(folded, start, end)
    end = found.start() if found else end
    place = TITLE_PLACE.search(folded, start, end) or OTHER_SLIDE.search(folded, start, end)
    if place and place.start() > start:
        # "… Aziz Karimov on the first slide": the words that lead to the place go with it.
        end = start + len(re.sub(r"(?:[ \t,]+(?:on|the|in|to|at|onto|for|на|в|во|к|ко))+[ \t]*$", '',
                                 folded[start:place.start()], flags=I))
    following = LABEL.search(folded, start + 1, end)
    end = following.start() if following else end
    stops = [end]
    # A quote ends it, unless it wraps a class letter: 11-«A» sinf.
    for found in re.finditer(rf"[{QUOTES}]", folded[start:end]):
        position = start + found.start()
        if (re.match(rf"[{QUOTES}]\w{{1,3}}[{QUOTES}]", folded[position:position + 5])
                or re.search(rf"[{QUOTES}]\w{{1,3}}[{QUOTES}]$", folded[max(start, position - 4):position + 1])):
            continue
        stops.append(position)
        break
    for found in re.finditer(r"[.,]\s+", folded[start:end]):
        cut = start + found.start()
        mark = folded[cut]
        # Only the word before the mark: a long value is read once, not again at every mark.
        if mark == '.' and (_initial(text, start, cut) or ABBREVIATION.search(folded, max(start, cut - 12), cut)):
            continue  # "N. Karimova", "dots. Qodirov", "Dr. Brown", "gr. 301-21"
        if mark == ',':
            rest = folded[cut + 1:end]
            part_end = min([position for position in (rest.find(','), rest.find('.')) if position >= 0] or [len(rest)])
            whole = folded[cut + 1:line_end]
            whole_end = min([position for position in (whole.find(','), whole.find('.')) if position >= 0] or [len(whole)])
            if LABEL.search(folded, cut + 1, cut + 1 + whole_end):
                stops.append(cut)  # "Tayyorladi: X, Fan o'qituvchisi: Y": the next label's own words start there
                break
            if (ABBREVIATION.search(folded, max(start, cut - 12), cut) or _designation(rest, 0, part_end)
                    or ABBREVIATION.match(re.split(r"[\s.]", rest.lstrip() + ' ')[0])
                    or REPLACED.search(folded[max(start, cut - 12):cut])
                    or (_name_runs(text, cut + 1, cut + 1 + part_end) and not ASKS.search(rest[:part_end]))):
                continue  # "Ali Valiyev, 9-sinf", "студент 2 курса", "f.f.d., prof. …", "X emas, Y", "Ali, Vali"
        stops.append(cut)
        break
    return min(stops)


def _titles(piece):
    """Whether `piece` is a few titles or initials: "dots.", "prof. dr.", "f.f.d.,"."""
    tokens = piece.split()
    return 1 <= len(tokens) <= 4 and all(len(token) <= 12 and re.fullmatch(r"(?:\w{1,6}\.){1,4},?", token) for token in tokens)


def _person_value(text, start, end, *, named=False, lower=True):
    """Whether text[start:end] names a person: a name, maybe with initials, a title, a group or a class.

    A surname ("-ova", "qizi") may be in any case — unless `lower` is off —
    and in lower case the value is the name alone; a name without one ("Kim
    Viktoriya", "John Miller") is capitalised, word by word, and only when
    `named` is off.
    """
    value = text[start:end]
    folded = _fold(value)
    words = WORD.findall(value)
    if (not words or len(words) > 14 or ASKS.search(folded) or NOT_A_VALUE.search(folded)
            or value.rstrip().endswith('?')):
        return False
    capital = any(_capital(word) for word in words)
    if not capital and not lower:
        return False
    if ORGANISATION.search(folded) and not _strongly_named(text, start, end):
        return False  # "Prepared by: World Health Organization", "Tayyorladi: Jahon Banki"
    runs = _name_runs(text, start, end, lower=not capital)
    if not capital and (not STRONG_SURNAME.search(_fold(words[0])) or len(runs) != 1
                        or _leftover(text, _fold(text), start, end)):
        return False  # "приветствие учеников", "works in pairs", "перевод текстов": words, not a name
    if runs:
        first, last = runs[0][0], runs[-1][1]
        before, after = _fold(text[start:first]), _fold(text[last:end])
        return (not before.strip(' \t,') or _designation(before, 0, len(before))
                or _titles(before)) and (
            not after.strip(' \t,.') or _designation(after, 0, len(after))
            or bool(re.fullmatch(r"[ \t,]*(?:\w\.[ \t]*)+", after)))
    if named:
        return False
    # No surname: capitalised words, with initials, a title or a designation after them.
    names = re.match(r"[ \t]*(?:(?:[\w']+\.[ \t]*)?)((?:[A-ZА-ЯЁЎҚҒҲ][\w']+[ \t]*){1,4})(.*)$", folded, re.S)
    if not names:
        return False
    rest = names.group(2)
    return (1 <= len(names.group(1).split()) <= 4 and (len(names.group(1).split()) >= 2 or re.search(r"\w\.", folded))
            and (not rest.strip(' \t,.') or _designation(rest, 0, len(rest)) or bool(re.fullmatch(r"[ \t]*(?:\w\.[ \t]*)+", rest))))


def _place_value(label, value):
    """Whether `value` fills a place label: a group or class designation, or a school's or faculty's name."""
    words = WORD.findall(value)
    if GROUP_NOUN.fullmatch(_fold(label).strip()):
        # "Sinf: 8-B", "Guruh: 21-05", "Группа: 305" — a designation, not a count of people.
        return (bool(re.fullmatch(r"[\w\-–/ «»\"]{1,12}", value.strip())) and bool(re.search(r"\d", value))
                and not re.search(r"(?:kishi|odam|человек|people|students|talaba)", value, I))
    return 0 < len(words) <= 8 and not ASKS.search(_fold(value)) and (
        _capital(value.strip()) or value.strip()[:1].isdigit())


CONJUNCTION_END = re.compile(r"[ \t,]+(?:va|and|и|hamda|ham)[ \t]*$", I)
# What a value may end with that is not part of it: "Ergasheva Malika!", an emoji.
VALUE_TAIL = re.compile(r"[\s!¡…\u2600-\u27BF\U0001F000-\U0001FAFF\uFE0F]+$")
# English verbs that say who made anything at all ("the first car, made by Karl Benz"): a label only with a colon.
GENERIC_VERB = re.compile(r"(?:done|made|presented)[ \t]+by", I)
# Words that may stand before a label as part of it: "Fan o'qituvchisi:", "Классный руководитель:".
LABEL_LEAD = re.compile(r"[ \t]*(?:[\w'-]+[ \t]+){1,2}", I)


def _line_start(folded, position):
    found = folded.rfind('\n', max(0, position - REACH), position)
    return found + 1 if found >= 0 else max(0, position - REACH)


def _aimed_elsewhere(scan, position, end=None):
    """Whether what is written at `position` goes on another slide: "Oxirgi slaydga yoz: Tayyorladi: …".

    Its own clause says so, before it or right after it ("Tayyorladi: X —
    oxirgi slaydga"), or the block it is in is headed so; a sentence before
    it about other slides ("Har bir slaydda rasm bo'lsin.") does not.
    """
    folded = scan.folded
    line_start = _line_start(folded, position)
    clause = max([line_start] + [folded.rfind(mark, line_start, position) + 1 for mark in '.!?;'])
    if scan.has('other', clause, position):
        return True
    header = folded.find(':', line_start, position)
    if header >= 0 and not re.search(r"[.!?;]", folded[line_start:header]) and scan.has('other', line_start, header):
        return True
    if end is not None:
        stops = [found for found in (folded.find(mark, end, end + REACH) for mark in '.!?;\n') if found >= 0]
        stop = min(stops or [min(len(folded), end + REACH)])
        if scan.has('other', end, stop):
            rest = OTHER_SLIDE.sub(' ', folded[end:stop])
            if not ASKS.search(rest) and not NAMING.search(rest):
                return True
    # The block it is in: "Oxirgi slaydga:\nTayyorladi: …", "Ohirgi slaydga\n…".
    above = line_start - 1
    for _ in range(TITLE_LINES):
        if above <= 0 or folded[above:above + 1] != '\n':
            return False
        row_start = _line_start(folded, above)
        row = folded[row_start:above]
        if not row.strip():
            return False
        if not LABEL.match(row.lstrip()) and (row.rstrip().endswith(':') or len(row.split()) <= 5):
            if scan.has('other', row_start, above):
                return True
            if row.rstrip().endswith(':'):
                return False
        above = row_start - 1
    return False


# Words before a label that join it to what came before, never part of it: "Va Qabul qildi:", "Ниже Выполнила:".
NOT_QUALIFIER = re.compile(r"(?:va|and|и|а|ham|hamda|keyin|so'ng|also|then|below|above|ниже|выше|также|потом|далее|pastda"
                           r"|tepada|yana|endi|bu|shu|this|the|a|an)", I)


def _label_start(folded, start):
    """Where a role's label starts with the words before it on its own line or clause: "Fan o'qituvchisi:"."""
    line_start = _line_start(folded, start)
    cut = max([line_start] + [folded.rfind(mark, line_start, start) + 1 for mark in '.;,!?'])
    lead = folded[cut:start]
    if not lead.strip() or not LABEL_LEAD.fullmatch(lead) or re.search(r"\d", lead):
        return start
    if (ASKS.search(lead) or TITLE_PLACE.search(lead) or ELSEWHERE.search(lead) or LABEL.search(lead)
            or any(LEAD_WORD.fullmatch(word) or NOT_QUALIFIER.fullmatch(word) for word in WORD.findall(lead))):
        return start
    return cut + len(lead) - len(lead.lstrip())


def _strongly_named(text, start, end):
    """Whether text[start:end] holds a name whose surname leaves no doubt: "Sobirov Jasur", "… Anvar qizi"."""
    for run_start, run_end in _name_runs(text, start, end):
        words = [_fold(word) for word in WORD.findall(text[run_start:run_end])]
        if any(STRONG_SURNAME.search(word) or PATRONYMIC.match(word) for word in words):
            return True
    return False


def _trimmed(text, folded, start, end):
    """A value's end without what trails it: "va" before the next person, "!" and emoji."""
    while end > start and (text[end - 1].isspace() or VALUE_TAIL.match(text[end - 1])):
        end -= 1
    joined = CONJUNCTION_END.search(folded, max(start, end - 12), end)
    if joined:
        end = joined.start()
        while end > start and text[end - 1] in ' \t,':
            end -= 1
    return end


# Words that may stand right before who did the work: fillers, orders, "unga" — not the thing that was done.
LEFT_OF_VERB = re.compile(r"(?:va|and|и|а|ham|hamda|also|then|unga|shunga|bunga|ниже|выше|также|далее|внизу|pastida|ostida"
                          r"|yana|endi|keyin|so'ng|qilib|deb|напиши|впиши|укажи|write|put|add|yoz\w*|qo'?sh\w*|qo'?y\w*)", I)


# What a request calls the thing it asks for.
REQUEST_WORDS = re.compile(r"(?<![\w'])(?:taqdimot\w*|prezentatsiya\w*|referat\w*|mustaqil[ \t]+ish\w*|презентаци\w*|доклад\w*"
                           r"|реферат\w*|presentation\w*|deck|report|essay)(?![\w'])", I)


def _block_head(scan, position):
    """The header row ("Шаблон титульника:") above the run of label rows `position` is in; None if there is none."""
    folded = scan.folded
    line_start = _line_start(folded, position)
    for _ in range(TITLE_LINES):
        if line_start <= 0 or folded[line_start - 1] != '\n':
            return None
        above = _line_start(folded, line_start - 1)
        row = folded[above:line_start - 1]
        if not row.strip():
            return None
        if not LABEL.match(row.lstrip()):
            return (above, line_start - 1) if row.rstrip().endswith(':') else None
        line_start = above
    return None


def _signs_here(scan, start, value_start, value_end):
    """Whether a "Tayyorladi:"-style label at `start` signs this deck, not something done in the topic.

    The word just before it is a filler, an order, a work word ("Taqdimotni",
    "Работу") or part of where it goes ("в начале слайда") — never the thing
    done ("Tajribani bajardi:", "Опыт выполнил:"). Opening a sentence mid-line,
    the sentence before it is the request's own, a title key, or a label.
    """
    text, folded = scan.text, scan.folded
    line_start = _line_start(folded, start)
    clause = max([line_start] + [folded.rfind(mark, line_start, start) + 1 for mark in '.!?;,:'])
    words = WORD.findall(folded[clause:start])
    if words:
        last = words[-1]
        placed = any(a <= start and start - b <= 3 for a, b in scan.within('title', clause, start))
        if not (placed or LEFT_OF_VERB.fullmatch(last) or WORK_WORDS.fullmatch(last) or LEAD_WORD.fullmatch(last)):
            return False
        return True
    previous = folded[max(line_start, clause - REACH):clause].strip(' \t.!?;,:')
    if clause == line_start or not previous:
        return True  # its own line
    # The line so far is the request's own words, a title key or a byline: "10 ta slayd. Tayyorladi: …".
    return bool(ASKS.search(previous) or REQUEST_WORDS.search(previous) or TITLE_KEY_ROW.match(previous)
                or LABEL.search(previous) or scan.titled or scan.groups_in(value_start, value_end)
                or scan.within('class', value_start, value_end) or _designation(folded, value_start, value_end))


def _labelled(scan):
    """Spans a label names: "Tayyorladi: …", "Talaba: …", "Tayyorladi Sobirova Madina", "Ali Valiyev tayyorladi".

    Each is (start, end, kind): 'person', 'place', or 'value' for a name
    asked for in passing ("Ismimni yoz: …"), which is the name alone. Who did
    the work ("Tayyorladi:", "Выполнила:") is a title line wherever it is; a
    role ("O'qituvchi:", "Teacher:") or a place ("Guruh:") only on a request
    that speaks of a title page — a fact list ("Rahbari: Amir Temur"), a cast
    ("Student: Harry Potter") or a lesson plan ("Учитель: …") is not one.
    """
    text, folded = scan.text, scan.folded
    signed, roles = [], []
    for match in LABEL.finditer(folded):
        start, value_start = match.start(), match.end()
        line_end = folded.find('\n', value_start, value_start + REACH)
        line_end = min(len(text), value_start + REACH) if line_end < 0 else line_end
        value_end = _value_end(text, folded, value_start, line_end)
        value_end = value_start + len(text[value_start:value_end].rstrip())
        value_end = _trimmed(text, folded, value_start, value_end)
        if _aimed_elsewhere(scan, start, value_end) or scan.has('other', start, value_start):
            continue  # "Oxirgi slaydga yoz: Tayyorladi: …", "Ismimni oxirgi slaydga yoz: …"
        head = _block_head(scan, start)
        if (scan.has('example', _line_start(folded, start), start) or scan.has('example', value_start, value_end)
                or (head and scan.has('example', *head))):
            continue  # "Masalan: Tayyorladi: Sobirov Jasur. Shu kabi titul …", "Шаблон титульника:\nВыполнил: …"
        if match.group('name'):
            phrase = folded[max(0, start - 24):value_start]
            own = next((found for found in OWN_LABEL.finditer(phrase) if found.end() > start - max(0, start - 24)), None)
            if not own:
                continue  # "Ism: Yevgeniy Onegin", "Yozuvchi ismi: …", "My hero's name: …" — someone else's name
            replaced = list(REPLACED.finditer(folded, value_start, value_end))
            value_start = replaced[-1].end() if replaced else value_start
            if _person_value(text, value_start, value_end):
                signed.append((value_start, value_end, 'value'))
            continue
        if match.group('place'):
            if _place_value(match.group('place'), text[value_start:value_end]):
                roles.append((_label_start(folded, start), value_end, 'place'))
            continue
        generic = bool(match.group('verb') and GENERIC_VERB.fullmatch(match.group('verb')))
        if match.group('vsep') and not _signs_here(scan, start, value_start, value_end):
            continue  # "Tajribani bajardi: Ivan Pavlov", "Периодический закон. Сделал: Дмитрий Менделеев"
        if match.group('person') or match.group('vsep'):
            # Who did the work signs; a role ("Talaba:") or "Made by:" is a title line only on a title page.
            found = signed if match.group('vsep') and not generic else roles
            lower = bool(match.group('vsep')) and not generic
            label_start = start if found is signed else _label_start(folded, start)
            if _person_value(text, value_start, value_end, lower=lower):
                found.append((label_start, value_end, 'person'))
            elif not text[value_start:value_end].strip() or _designation(folded, value_start, value_end):
                # "Tayyorladi:\nSobirov Jasur", "Bajardi: 2-kurs talabasi\nSobirov Jasur": the name on the next line.
                next_start = value_end + 1 if folded[value_end:value_end + 1] == '\n' else -1
                next_end = folded.find('\n', next_start, next_start + REACH) if next_start > 0 else -1
                next_end = min(len(text), next_start + REACH) if next_start > 0 and next_end < 0 else next_end
                if (next_start > 0 and not LABEL.match(folded, next_start)
                        and _person_value(text, next_start, next_end, lower=lower)):
                    found.append((label_start, _trimmed(text, folded, next_start, next_end), 'person'))
            continue
        after = folded[match.end():match.end() + 12]
        if re.match(r"(?:qism|qator|joy|deb)", after, I):
            continue  # "Qabul qildi qismiga …" is a "deb" dictation's
        if QUIZ.search(folded, max(0, start - REACH), min(len(folded), match.end() + REACH)):
            continue  # "… kim tayyorladi? Javob: Sergey Korolyov tayyorladi": a quiz, not a byline
        if scan.has('example', _line_start(folded, start), start):
            continue
        # A verb with no colon opening its clause: "Tayyorladi Sobirova Madina", "Работу выполнила …", "Birinchi
        # slaydga tayyorladi …" — never after a topic ("Космический полет, выполнила Валентина Терешкова").
        clause_start, clause_end = _clause(folded, start, match.end(), '.!?\n;:')
        lead = folded[clause_start:start].strip(' \t,')
        joined = bool(VERB_WORD.search(folded, clause_start, start))  # "… tayyorladi X, qabul qildi Y"
        placed = bool(lead) and bool(TITLE_PLACE.fullmatch(lead) or TITLE_PAGE.fullmatch(lead))
        if not lead or WORK_WORDS.fullmatch(lead) or joined or placed:
            end = _trimmed(text, folded, value_start, value_end)
            found = roles if generic else signed  # "made by Karl Benz" is anyone's
            # Opening a sentence after a topic it may be a credit ("Фреска «Троица». Сделал Андрей Рублёв."): it signs
            # on its own line or after the request's own words, or with the title page said, or with a group or class.
            designated = scan.groups_in(value_start, end) or scan.within('class', value_start, end)
            context = WORK_WORDS.fullmatch(lead) or joined or placed or scan.titled or designated
            previous = folded[max(_line_start(folded, clause_start), clause_start - REACH):clause_start]
            if previous.strip() and not ASKS.search(previous) and not context:
                continue
            if (context or _strongly_named(text, value_start, end)) and (_person_value(text, value_start, end) or (
                    _designation(folded, value_start, end) and scan.names(value_start, end))):
                found.append((start if not WORK_WORDS.fullmatch(lead) else clause_start + folded[clause_start:start].find(lead),
                              end, 'person'))
            continue
        # "Ali Valiyev tayyorladi.", "…, Ali Valiyev tayyorladi, …": a name (and its group) alone before it in
        # its clause, nothing after it but the clause's end — never "… qabul qildi, deb yozilgan".
        clause_start, clause_end = _clause(folded, start, match.end(), '.!?\n;:,')
        if re.match(r"[ \t,]*(?:deb|деб)(?![\w'])", folded[match.end():match.end() + 15], I):
            continue
        tail = folded[match.end():clause_end].strip(' \t,.!')
        runs = [run for run in scan.names(clause_start, start) if start - run[1] <= 2]
        found = roles if generic else signed
        # "Karimova Dilnoza tayyorladi": who prepared this — not who did something in the topic ("Ivan Pavlov tekshirdi").
        if not re.match(r"(?:tayyorla|тайёрла|подготов|выполн)", match.group('verb'), I) and not scan.titled:
            continue
        if runs and not tail:
            prefix = folded[clause_start:runs[-1][0]].strip(' \t,')
            if not prefix or _designation(prefix, 0, len(prefix)):
                found.append((clause_start + len(text[clause_start:start]) - len(text[clause_start:start].lstrip()),
                               match.end(), 'person'))
    def widened(spans, people_above):
        found = []
        for start, end, kind in spans:
            line_end = folded.find('\n', end, end + REACH)
            line_end = min(len(text), end + REACH) if line_end < 0 else line_end
            if kind != 'value' and not folded[end:line_end].strip():
                start, end = _around(scan, start, end, people_above)
            found.append((start, end, kind))
        return found

    def beside(start, end):
        # Next to a byline with nothing but title rows between: "Tayyorladi: X\nQabul qildi: Y", "…, O'qituvchi: Y".
        for a, b, kind in signed:
            gap = folded[b:start] if b <= start else folded[end:a] if end <= a else None
            if gap is None or kind != 'person' or len(gap) > 2 * REACH or '\n\n' in gap:
                continue
            if all(not piece.strip() or LABEL.match(piece.strip()) or HEADERS.match(piece) or _designation(piece, 0, len(piece))
                   for piece in re.split(r"[.;,\n]", gap)):
                return True
        return False

    def placed(start):
        # "Birinchi slaydga: Talaba: …", "Titulga:\nTalaba: …", "Talaba: …\nO'qituvchi: …\nShularni birinchi slaydga yoz".
        line_start = _line_start(folded, start)
        above = folded.rfind('\n', max(0, line_start - 1 - REACH), max(0, line_start - 1)) + 1
        header = folded[above:max(above, line_start - 1)]
        if any(not NO_TITLE.search(folded, *_clause(folded, a, b)) for a, b in scan.within('page', line_start, start)):
            return True
        if line_start > 0 and header.rstrip().endswith(':') and scan.has('page', above, line_start) and not NO_TITLE.search(header):
            return True
        after = start
        for _ in range(TITLE_LINES):
            row_end = folded.find('\n', after)
            if row_end < 0:
                return False
            row = folded[row_end + 1:folded.find('\n', row_end + 1) if folded.find('\n', row_end + 1) >= 0 else len(folded)]
            if not row.strip():
                return False
            if TITLE_KEY_ROW.match(row) or _designation(row, 0, len(row)):
                after = row_end + 1
                continue
            if not LABEL.match(row.strip()):
                return (len(row.split()) <= 7 and bool(ORDER.search(row)) and bool(TITLE_PAGE.search(row))
                        and not NO_TITLE.search(row))
            after = row_end + 1
        return False

    def facts(start):
        # Its block also holds facts ("Poytaxti: Samarqand", "Asoschisi: Amir Temur"): a fact list, not a title page.
        first = folded.rfind('\n\n', max(0, start - TITLE_LINES * REACH), start)
        last = folded.find('\n\n', start, start + TITLE_LINES * REACH)
        block = folded[first + 2 if first >= 0 else max(0, start - TITLE_LINES * REACH):last if last >= 0 else len(folded)]
        for key in re.finditer(r"(?:^|[\n.;!?][ \t]*)([^\W\d_][\w' ]{0,24}):", block):
            word = key.group(1).strip()
            label = LABEL.search(word + ':')
            if not ((label and label.end() == len(word) + 1) or TITLE_KEY_ROW.match(word + ':') or HEADERS.match(word)
                    or TITLE_PAGE.search(word)
                    or BLOCK.match(word + ':') or OWN_LABEL.search(word) or ASKS.search(word) or EXAMPLE.search(word)):
                return True
        return False

    # A role off a title page counts with its student's group or class in it: "Talaba: 301-guruh Sobirov Jasur".
    roles = [(start, end, kind) for start, end, kind in roles
             if ((beside(start, end) or placed(start)) and not facts(start))
             or ((scan.groups_in(start, end) or scan.within('class', start, end)) and _strongly_named(text, start, end))]
    return widened(signed, False) + widened(roles, True)


def _around(scan, start, end, people_above=True):
    """A labelled line with the lines that go with it: its header above, a group or name below.

    Above who did the work ("Tayyorladi: …") only a header or a place: a
    name there is the topic ("Александр Пушкин\nВыполнила: …").
    """
    text, folded = scan.text, scan.folded
    line_start = folded.rfind('\n', max(0, start - REACH), start) + 1
    taken = 0
    while line_start > max(0, start - REACH) and not folded[line_start:start].strip() and taken < TITLE_LINES:
        # The lines above it: a header ("Mustaqil ish"), the school and class, the student's name.
        above_end = line_start - 1
        above_start = folded.rfind('\n', max(0, above_end - REACH), max(0, above_end)) + 1
        row = folded[above_start:above_end]
        if not row.strip() or len(row.split()) > 12 or not (HEADERS.match(row) or (not ASKS.search(row) and not LABEL.search(row) and (
                _designation(folded, above_start, above_end)
                or (people_above and _strongly_named(text, above_start, above_end)
                    and _person_value(text, above_start, above_end, named=True))))):
            break
        start, line_start, taken = above_start, above_start, taken + 1
    pending = None
    while end < len(text) and folded[end:end + 1] == '\n':
        next_end = folded.find('\n', end + 1, end + 1 + REACH)
        if next_end < 0:
            next_end = min(len(text), end + 1 + REACH)
        row = folded[end + 1:next_end]
        if not row.strip() or len(row.split()) > 8:
            break
        if (not ASKS.search(row) and not LABEL.search(row) and _strongly_named(text, end + 1, next_end)
                and _person_value(text, end + 1, next_end, named=True)):
            if re.match(r"[ \t]*\w\.[ \t]*\w", row):
                end = next_end  # "M. Rashidova": a co-author signs as the first did
                continue
            pending = pending or end
            end = next_end  # a name: the student's only if a group or class row closes them
            continue
        title_like = (_designation(folded, end + 1, next_end)
                      or re.fullmatch(r"[ \t]*[A-ZА-ЯЁЎҚҒҲ][\w'-]+,?[ \t]+(?:19|20)\d\d(?:[ \t]?-?[ \t]?(?:yil|год|г)\.?)?[ \t]*",
                                      row))
        if not row.strip() or not title_like or ASKS.search(row) or LABEL.search(row) or len(row.split()) > 8:
            break
        end, pending = next_end, None
    return start, pending if pending is not None else end


def _leftover(text, folded, start, end):
    """The words of text[start:end] that are neither a name, nor a group, class or school, nor a joining word."""
    lower = not any(_capital(word) for word in WORD.findall(text[start:end]))
    covered = [(a, b) for a, b in _name_runs(text, start, end, lower=lower)]
    covered += [(m.start(), m.end()) for m in GROUP.finditer(folded, start, end)]
    covered += [(m.start(), m.end()) for m in CLASS.finditer(folded, start, end)]
    left = []
    for match in WORD.finditer(text, start, end):
        if any(a <= match.start() < b for a, b in covered):
            continue
        word = _fold(match.group(0)).lower()
        if len(word) == 1 or re.fullmatch(r"(?:va|and|и|ham|hamda|maktab\w*|школ\w*|sinf\w*|класс\w*|guruh\w*|групп\w*"
                                          r"|o'?quvchi\w*|talaba\w*|студент\w*|учени\w*|kurs\w*|курс\w*|ўқувчи\w*|талаба\w*"
                                          r"|синф\w*|гуруҳ\w*|мактаб\w*)", word):
            continue
        left.append(word)
    return left


SAID = re.compile(r"(?:gan|di|ilgan)", I)
# A quiz asks who did it: the answer is not the customer's byline.
QUIZ = re.compile(r"\?|(?<![\w'])(?:kim|kimning|savol\w*|javob\w*|viktorina\w*|кто|вопрос\w*|ответ\w*|викторин\w*|who|question\w*"
                  r"|answer\w*|quiz\w*)(?![\w'])", I)
# A request dictates a few lines; past this many "deb"s it is pasted text, not orders.
DEB_LIMIT = 40
QUOTED_END = re.compile(rf"[{QUOTES}']([^{QUOTES}]{{2,200}})[{QUOTES}']$")
LABEL_PART_END = re.compile(rf"(?P<label>{PERSON_VERBS}|{PERSON_NOUNS})[ \t]+(?:qism|qator|joy)\w*[ \t]*$", I)
# Where the request's own words end before what a "deb" dictates: "… qo'sh va", "bir betga", "Boshiga yoz:".
DEB_LEAD = re.compile(r"(?<![\w'])[\w']*(?:qo'sh|qo'y|yoz|qil|ber|kirit|tayyorla)[\w']*[ \t]+va(?![\w'])"
                      r"|(?<![\w'])(?:bet|sahifa|slayd|varaq|list|qism|bosh|qator|joy|titul|muqova|tepa|yuqori)\w*"
                      r"(?:ga|iga|ida|da)(?![\w'])|:", I)


# What a student says of their own work beside their name: "… Sobirova Madinaning taqdimoti", "… tayyorladi".
WORKISH = re.compile(r"(?:taqdimot\w*|ish\w*|referat\w*|mustaqil|tayyorla\w*|bajar\w*|тайёрла\w*|презентаци\w*|работ\w*"
                     r"|выполнил\w*|подготовил\w*)", I)


def _elsewhere(scan, start, end):
    """Whether text[start:end] sends what it dictates elsewhere — not "oxirida emas, boshida" (not at the end)."""
    return any(not re.match(r"[ \t]+(?:emas|не|not)(?![\w'])", scan.folded[b:b + 8], I)
               for _, b in scan.within('elsewhere', start, end))


def _dictated_with_deb(scan):
    """What "… deb yoz" dictates for the title: "Ali Valiyeva 11-B sinf deb boshidagi qismiga yozib qo'y".

    Each is (start, end, kind): 'line', or 'label:<start>' when the label it
    fills was named before it ("Qabul qildi qismiga Nazarova Feruza deb yoz").
    """
    text, folded = scan.text, scan.folded
    spans, read_to = [], -1
    for match in itertools.islice(DEB.finditer(folded), DEB_LIMIT):
        if match.start() < read_to:
            continue  # within what the last one dictated
        ordered = DEB_VERB.match(folded, match.end())
        if ordered and SAID.match(folded, ordered.end()):
            continue  # "deb yozgan": what someone wrote, not an order
        if not ordered:
            # A bare "deb" ending its line: only when the request has just asked for a name to be written.
            if (folded[match.end():match.end() + 20].lstrip(' \t.!')[:1] not in ('', '\n')
                    or not WRITE.search(folded[max(0, match.start() - 160):match.start()])):
                continue
        clause_start, clause_end = _clause(folded, match.start(), match.end())
        # Where the order sends it, up to its verb: what follows ("…, oxirida xulosa") is another order.
        aimed = ordered.end() if ordered else match.end()
        if _elsewhere(scan, clause_start, aimed) or _aimed_elsewhere(scan, clause_start):
            continue  # another slide, a heading, a caption, a name for something, a quotation
        window = max(clause_start, match.start() - REACH)
        before = folded[window:match.start()].rstrip()
        end = window + len(before)
        label_start = None
        quoted = QUOTED_END.search(before, max(0, len(before) - 203)) if before[-1:] in QUOTES + "'" else None
        if quoted:
            start, end = window + quoted.start(1), window + quoted.end(1)
        else:
            start = window
            # The request's own words come off the front: "Boshiga bitta sahifa qo'sh va …", "bir betga …".
            for found in DEB_LEAD.finditer(before):
                start = window + found.end()
            label_from = max(clause_start, start - 60)
            labelled = LABEL_PART_END.search(folded[label_from:start])
            if labelled:
                label_start = label_from + labelled.start('label')
            lower = not any(_capital(word) for word in WORD.findall(text[start:end]))
            runs = _name_runs(text, start, end, lower=True) if lower else scan.names(start, end)
            marks = ([run[0] for run in runs]
                     + [g for g, _ in scan.groups_in(start, end)] + [a for a, _ in scan.within('class', start, end)]
                     + [m.start() for m in re.finditer(r"\d{1,3}[ \t]?[-–]?[ \t]?(?:maktab|мактаб)", folded[start:end], I)])
            first = min(marks) if marks else start
            if first > start and (scan.has('asks', start, first) or ASKING_WORDS.match(folded[start:first].strip() + ' ')
                                  or scan.has('title', start, first)):
                start = first
        # "X o'rniga Y", "X emas, Y": Y alone.
        replaced = list(REPLACED.finditer(folded, start, end))
        if replaced:
            start = replaced[-1].end()
        asking = ASKING_WORDS.match(folded[start:end].lstrip())
        if asking:
            start += len(folded[start:end]) - len(folded[start:end].lstrip()) + asking.end()
        start += len(text[start:end]) - len(text[start:end].lstrip())
        heading = LABEL.match(folded, start)  # "qabul qildi Nazarova Feruza deb yoz": the label is the line's
        if start >= end or scan.has('asks', heading.end() if heading else start, end):
            continue
        lower = not any(_capital(word) for word in WORD.findall(text[start:end]))
        if not (_name_runs(text, start, end, lower=True) if lower else scan.names(start, end)):
            continue
        pure = not _leftover(text, folded, start, end)
        connected = bool(re.search(r"(?:o'?quvchi|talaba|студент|учени|ўқувчи|талаба|tayyorla|bajar|тайёрла|бажар)\w*",
                                   folded[start:end], I))
        # Aimed at the title: it says so, the customer's own name is asked for just before, or what it dictates
        # is plainly a student's ("… 11-B sinf o'quvchisi", "… 302-guruh") — never "Jadvalga X deb kirit".
        # Aimed at the title page, said in its clause ("… deb boshidagi qismiga yoz"), or the customer's own name
        # asked for in it or on the line before ("Ism familiyamni ham yozib qo'y …\nKarimova Dilnoza … deb").
        asked_from = _line_start(folded, max(0, _line_start(folded, clause_start) - 1))
        student = ((connected or scan.groups_in(start, end) or scan.within('class', start, end))
                   and _strongly_named(text, start, end) and len(_name_runs(text, start, end)) == 1
                   and all(WORKISH.fullmatch(word) for word in _leftover(text, folded, start, end))
                   and not scan.has('example', clause_start, clause_end))
        titled = (scan.has('title', clause_start, clause_end) or OWN_NAME.search(folded, asked_from, start)
                  or label_start is not None or student)
        if titled and (pure or connected or label_start is not None or scan.has('label', start, end)):
            spans.append((start, end, 'line' if label_start is None else f'label:{label_start}'))
            read_to = match.end()
    return spans


# Where "my name is …" is an example, a character's words or a role play, not the customer's own.
EXAMPLE = re.compile(r"(?<![\w'])(?:misol\w*|masalan|namuna\w*|мисол\w*|масалан|намуна\w*|example\w*|e\.g|for[ \t]+instance"
                     r"|shablon\w*|andoza\w*|шаблон\w*|template\w*|как[ \t]+оформить|qanday[ \t]+rasmiylashtir\w*"
                     r"|how[ \t]+to[ \t]+format|представля\w*|говорит|скажет|introduc\w*|says|saying|speech|bubble|gapir\w*"
                     r"|so'zlaydi|aytadi|deydi"
                     r"|sample\w*|фраз\w*|например|пример\w*|образ[ец]\w*|tilidan|nomidan|first[ \t]+person|от[ \t]+(?:первого|имени)\w*"
                     r"|birinchi[ \t]+shaxs\w*|monolog\w*|dialog\w*|диалог\w*|монолог\w*|role[ \t-]?play\w*)(?![\w'])", I)
# "Ismimni yoz …", "write my name …", "напиши моё имя …", "имя исправь на …": the customer's name asked for.
OWN_ORDER = re.compile(r"(?<![\w'])(?:(?:mening[ \t]+)?(?:ismim|ism[ \t-]*familiyam|familiyam)ni(?:[ \t]+ham)?[ \t]+"
                       r"(?:yozing|yozib[ \t]+(?:qo'y|ber)\w*|yoz|qo'shing|qo'sh|qo'ying|qo'y|kiriting|kirit)"
                       r"|(?:напиши|добавь|впиши|укажи)[ \t]+(?:моё|мое|мою)[ \t]+(?:имя|фамилию|фио)"
                       r"|(?:write|put|add)[ \t]+my[ \t]+(?:full[ \t]+)?name"
                       r"|(?:мо[её]|мою)[ \t]+(?:имя|фамилию)[ \t]+(?:исправь|измени|поменяй)[ \t]+на"
                       r"|(?:^|(?<=\n))[ \t]*(?:имя|фамилию)[ \t]+(?:исправь|измени|поменяй)[ \t]+на"
                       r"|(?:^|(?<=\n))[ \t]*(?:исправь|измени|поменяй)[ \t]+(?:мо[её][ \t]+)?(?:имя|фамилию)"
                       r"|(?:исправь|измени|поменяй)[ \t]+(?:мо[её]|мою)[ \t]+(?:имя|фамилию)[ \t]+на"
                       r"|change[ \t]+my[ \t]+name(?:[ \t]+on[ \t]+the[ \t]+(?:title|first|cover)[ \t]+(?:slide|page))?"
                       r"[ \t]+to)(?![\w'])[ \t:,-]*", I)
# "Mening ismim …", "меня зовут …", "my name is …": the customer's name said, to be written only where it says so.
OWN_STATEMENT = re.compile(r"(?<![\w'])(?:(?:mening[ \t]+)?ismim(?:[ \t]+ham)?|меня[ \t]+зовут|мо[её][ \t]+имя"
                           r"|my[ \t]+name[ \t]+is|my[ \t]+name)(?![\w'])[ \t:,-]*", I)


def _self_named(scan):
    """"Ismimni yoz …", "Mening ismim …, birinchi slaydga yoz", "my name is …": the customer's own name.

    Asked for in so many words, or said in the same line as where it goes —
    never in an example ("Misol yoz: My name is Anna Brown") or someone's
    words ("Amir Temur tilidan yoz: Mening ismim …").
    """
    text, folded = scan.text, scan.folded
    spans = []
    orders = list(OWN_ORDER.finditer(folded))
    # "write my name …" is an order, its "my name" no statement of its own.
    statements = [m for m in OWN_STATEMENT.finditer(folded)
                  if not any(order.start() <= m.start() < order.end() for order in orders)]
    found = sorted([(m, True) for m in orders] + [(m, False) for m in statements], key=lambda item: item[0].start())
    for index, (match, ordered) in enumerate(found):
        line_start = _line_start(folded, match.start())
        line_end = folded.find('\n', match.end(), match.end() + REACH)
        line_end = min(len(text), match.end() + REACH) if line_end < 0 else line_end
        if (scan.has('example', max(0, match.start() - REACH), min(len(text), match.end() + REACH))
                or _aimed_elsewhere(scan, match.start())):
            continue
        # Read up to the next one: a long request is read once.
        bound = found[index + 1][0].start() if index + 1 < len(found) else len(text)
        clause_start, clause_end = _clause(folded, match.start(), match.end())
        value_start = match.end()
        place = TITLE_PLACE.match(folded, value_start + len(re.match(r"(?:[ \t]*(?:on|in|to|at|the|на|в|во)[ \t]+)*",
                                                                      folded[value_start:]).group(0)))
        if place:
            value_start = place.end() + len(re.match(r"[ \t]*[:,\-–—]?[ \t]*", folded[place.end():]).group(0))
        end = _value_end(text, folded, value_start, min(line_end, bound))
        end = _trimmed(text, folded, value_start, value_start + len(text[value_start:end].rstrip()))
        if _aimed_elsewhere(scan, match.start(), end):
            continue
        # "Ismim Sobirova Mohinur bo'lsin" asks as plainly as "ismimni yoz"; "Mening ismim …" only with where it goes.
        ordered = ordered or bool(re.match(r"[ \t,]*(?:bo'lsin|bo'lishi|deb|qilib)(?![\w'])", folded[end:end + 20], I))
        following = _clause(folded, clause_end + 1, clause_end + 1) if clause_end < len(folded) else (clause_end, clause_end)
        pointed = (scan.has('title', *following)
                   and re.match(r"[ \t]*(?:shuni|buni|uni|ularni|familiyamni|ismimni|it|this|это|его|их)(?![\w'])",
                                folded[following[0]:following[1]], I))
        if not ordered and not scan.has('title', clause_start, clause_end) and not pointed:
            continue
        if _person_value(text, value_start, end):
            spans.append((value_start, end, 'value'))
    # "Tayyorladi qismida Sobirova Madina bo'lsin": the label and the name, as one line.
    for match in re.finditer(rf"(?<![\w'])(?P<label>{PERSON_VERBS}|{PERSON_NOUNS})[ \t]+(?:qism|qator|joy)\w*[ \t]+",
                             folded, I):
        stop = re.compile(r"[ \t]+(?:bo'lsin|bo'lishi|deb)(?![\w'])|[.\n]", I).search(folded, match.end(),
                                                                                       match.end() + REACH)
        if stop and stop.group(0).strip() in ("bo'lsin", "bo'lishi") and _person_value(text, match.end(), stop.start()):
            spans.append((match.end(), stop.start(), f'label:{match.start()}'))
    return spans


def _pieces(text, folded, start, end):
    """A line split where it lists title lines inline: "MUSTAQIL ISH, Tayyorladi: …. Har bir …"."""
    pieces, begin = [], start
    for found in re.finditer(r"[ \t]/[ \t]|;|[.,](?=\s)", folded[start:end]):
        cut = start + found.start()
        if found.group().startswith('.') and (_initial(text, begin, cut)
                                              or ABBREVIATION.search(folded, max(begin, cut - 12), cut)):
            continue  # an initial or a title: "N. Karimova", "dots. Qodirov"
        if found.group().startswith(',') and not LABEL.match(folded, start + found.end() + len(
                folded[start + found.end():end]) - len(folded[start + found.end():end].lstrip())):
            continue  # a comma splits only where a new label starts: "Ali Valiyev, 9-sinf" is one line
        pieces.append((begin, cut))
        begin = start + found.end()
    pieces.append((begin, end))
    return [(a + len(text[a:b]) - len(text[a:b].lstrip()), b) for a, b in pieces if text[a:b].strip()]


def _block_header(folded, match):
    """Whether a BLOCK match heads title lines, not a heading, a topic or pictures: "Birinchi slaydga portretlar:"."""
    header = folded[_line_start(folded, match.start()):match.end()]
    return not (NAMING.search(header) or OTHER_SLIDE.search(header) or EXAMPLE.search(header)
                or re.search(r"(?<![\w'])(?:portret\w*|портрет\w*|portrait\w*|rasm\w*|surat\w*|фото\w*|photo\w*|picture\w*)", header, I))


# A row of a title page that is neither a label nor a name: the institution, the ministry, the city and year.
PLACE_ROW = re.compile(r"(?:maktab\w*|litsey\w*|kollej\w*|universitet\w*|institut\w*|akademiya\w*|fakultet\w*|kafedra\w*"
                       r"|yo'nalish\w*|vazirlig\w*|мактаб\w*|университет\w*|институт\w*|факультет\w*|кафедр\w*|министерств\w*"
                       r"|направлени\w*|школ\w*|лице\w*|колледж\w*|академи\w*|school|university|institute|college|faculty"
                       r"|department|ministry)", I)
CITY_YEAR = re.compile(r"[ \t]*[A-ZА-ЯЁЎҚҒҲ][\w'-]+,?[ \t]+(?:19|20)\d\d(?:[ \t]?-?[ \t]?(?:yil|год|г)\.?)?[ \t]*")
# A title page's own "Key: value" rows: "Mavzu: …", "Fan: …".
TITLE_KEY_ROW = re.compile(r"[ \t•\-–]*(?:mavzu\w*|мавзу\w*|тема|topic|subject|fan|фан|предмет|kafedra\w*|yo'nalish\w*|id"
                           r"|направлени\w*|mutaxassislik\w*|специальност\w*)[ \t]{0,2}:", I)


def _title_row(scan, start, end):
    """Whether text[start:end] is a row a title page has: a label, a header, a place, a name, a designation."""
    text, folded = scan.text, scan.folded
    row = folded[start:end].strip()
    if not row or (ASKS.search(row) and not LABEL.match(row)):
        return False
    return bool(LABEL.match(row) or HEADERS.match(row) or TITLE_KEY_ROW.match(row) or CITY_YEAR.fullmatch(row)
                or (PLACE_ROW.search(row) and any(_capital(word) or word.isupper() for word in WORD.findall(text[start:end])))
                or VERB_WORD.search(row) or _designation(folded, start, end) or _person_value(text, start, end))


def _bare_name(scan, start, end):
    """Whether a row is a name and nothing that says what it is: no label, header, place or designation."""
    folded = scan.folded
    row = folded[start:end].strip()
    return not (LABEL.match(row) or HEADERS.match(row) or TITLE_KEY_ROW.match(row) or CITY_YEAR.fullmatch(row)
                or PLACE_ROW.search(row) or VERB_WORD.search(row) or scan.groups_in(start, end)
                or scan.within('class', start, end)) and bool(_name_runs(scan.text, start, end) or _person_value(scan.text, start, end))


def _blocks(scan):
    """The lines under "Birinchi betiga:", "Titulga:", "Ustki qismiga": up to a blank line or a row that is not one."""
    text, folded = scan.text, scan.folded
    spans, read_to = [], -1
    starts = sorted([m.end() for m in BLOCK.finditer(folded) if _block_header(folded, m)]
                    + [m.end() for m in STANDALONE.finditer(folded)])
    for begin in starts:
        if begin < read_to:
            continue  # inside a block already read
        if PLAN.search(folded, begin, begin + 2 * REACH):
            read_to = begin + 2 * REACH
            continue  # "1-slayd: …\n2-slayd: …" is a plan of the slides
        lines, position, signed, bare = [], begin, False, 0
        for number, raw in enumerate(text[begin:begin + TITLE_LINES * REACH].split('\n')):
            row_start, row_end = position, position + len(raw)
            position = row_end + 1
            if not raw.strip():
                if lines:
                    # A blank line ends the block, unless what follows it is still the title page.
                    rest = folded[position:position + REACH].lstrip('\n \t')
                    following = rest.split('\n', 1)[0]
                    offset = position + len(folded[position:position + REACH]) - len(folded[position:position + REACH].lstrip('\n \t'))
                    if not following or not (LABEL.match(following) or HEADERS.match(following)
                                             or TITLE_KEY_ROW.match(following) or CITY_YEAR.fullmatch(following)):
                        break  # past a blank line only labels and headers are the title page's
                continue
            pieces = _pieces(text, folded, row_start, row_end) if number == 0 or ' / ' in raw else (
                [(row_start + len(raw) - len(raw.lstrip()), row_end)])
            stop = False
            for a, b in pieces:
                label = LABEL.match(folded, a)
                if label:
                    value_end = _trimmed(text, folded, label.end(), _value_end(text, folded, label.end(), b))
                    value_end = label.end() + len(text[label.end():value_end].rstrip())
                    if folded[value_end:b].strip(' \t.,;'):
                        lines.append((a, value_end))
                        stop = True  # the row goes on to ask for something else
                        break
                elif not _title_row(scan, a, b):
                    stop = True  # "Rahmat", "Ingliz tilida", "Use a blue theme": the request goes on
                    break
                elif _bare_name(scan, a, b):
                    # "Sobirova Madina" under the header — never "Aleksandr Pushkin" after the byline, or a topic.
                    if signed or bare >= 2 or not (_strongly_named(text, a, b) or _designation(folded, a, b)):
                        stop = True
                        break
                    bare += 1
                signed = signed or bool(label and (label.group('verb') or label.group('person')))
                lines.append((a, b))
            if stop or len(lines) >= TITLE_LINES:
                break
        read_to = max(read_to, position)
        people = [line for line in lines if LABEL.match(folded, line[0]) or _person_value(text, *line)]
        # Names alone under it say nothing of whose they are: "Birinchi slaydga: Ivan Pavlov".
        if people and all(_bare_name(scan, *line) for line in lines):
            people = []
        if people:
            spans += [(a, b, 'block') for a, b in lines]
    return spans


# The next words making the person the topic: "Bu talaba haqida", "про его достижения", "about her".
ABOUT_THEM = re.compile(r"(?<![\w'])(?:(?:bu|shu|u|uning)[ \t]+(?:[\w']+[ \t]+){0,2}haqida|uning[ \t]+haqida"
                        r"|про[ \t]+(?:его|её|ее|него|неё|нее|этого|эту)|о[ \t]+(?:нём|ней|нем)|(?:его|её|ее)[ \t]+достижени\w*"
                        r"|about[ \t]+(?:him|her|them|this)|his[ \t]+achievements|her[ \t]+achievements)(?![\w'])", I)
# An order to write, or to let it be: what a request says around what it dictates.
ORDER = re.compile(r"(?<![\w'])(?:deb[ \t]+)?(?:bo'lsin|bo'lishi[ \t]+kerak|kerak|yoz\w*|qo'?sh\w*|qo'?y\w*|kirit\w*|напиши|впиши|добавь"
                   r"|укажи|write|add|put|please|iltimos)(?![\w'])(?:[ \t]+(?:bo'lsin|kerak|qo'y\w*|ber\w*|please))*", I)


def _beside_group(scan):
    """A person's name next to their student group: "Ali Valiyeva 026-136-guruh", "205-группа Ali Valiyeva".

    Only where the two are the whole clause ("…kerak-Karimova Dilnoza
    026-136-guruh. …") and the surname leaves no doubt: a topic beside an
    audience ("302-guruh Zahiriddin Muhammad Bobur hayoti", "Киевская Русь,
    группа 205") is not one.
    """
    text, folded = scan.text, scan.folded
    pairs = []
    for first, last in scan.runs:
        if not _strongly_named(text, first, last):
            continue
        for g_start, g_end in scan._between(scan.group_starts, scan.groups, first - 60, last + 31):
            gap = folded[last:g_start] if g_start >= last else folded[g_end:first]
            if re.search(r"[\n.!?;,]", gap) or (g_start < last and g_end > first):
                continue
            words = WORD.findall(gap)
            if len(gap) > 30 or len(words) > 2 or not all(CONNECTOR.fullmatch(w) for w in words):
                continue
            pairs.append((min(first, g_start), max(last, g_end)))
    if len(set(pairs)) > 1 and not scan.titled:
        return []  # "301-guruh — Sobirov Jasur, 302-guruh — …": who presents what, not a signature
    spans = []
    for start, end in pairs:
        # "201-guruh talabalari uchun", "Ali Valiyev haqida": an audience or a subject, not a signature.
        if AUDIENCE.match(folded, end) or re.match(r"[ \t]{0,2}(?:haqida|about|о|об|про)(?![\w'])",
                                                   folded[end:end + 12], I):
            continue
        before = re.split(r"[\n.!?;,:\-–—]", folded[max(0, start - 60):start])[-1]
        after = re.split(r"[\n.!?;,:]|[ \t][\-–—]", folded[end:end + 60])[0]
        ordered = ORDER.search(before) and not re.search(r"(?<![\w'])(?:про|о|об|about|haqida)(?![\w'])", before, I)
        if not ordered and any(not LEAD_WORD.fullmatch(word) and not ASKING_WORDS.match(word + ' ')
                               and not TITLE_PLACE.search(word) for word in WORD.findall(TITLE_PLACE.sub(' ', before))):
            continue  # "302-guruh Zahiriddin Muhammad Bobur …": a topic, not a signature
        if after.strip() and not _designation(after, 0, len(after)) and not ORDER.fullmatch(after.strip()):
            continue
        if after.strip() and _designation(after, 0, len(after)):
            end += len(after.rstrip())  # "… 301-21 guruh talabasi"
        if _aimed_elsewhere(scan, start, end):
            continue
        key = re.search(r"([^\W\d_][\w' ]{0,30}):[ \t]*$", folded[max(0, start - 40):start])
        if key and not (OWN_LABEL.search(key.group(1)) or LABEL.match(key.group(1) + ':') or TITLE_PAGE.search(key.group(1))
                        or TITLE_PLACE.search(key.group(1))):
            continue  # "Победитель олимпиады: Иванова Анна 205-группа": a fact, not a signature
        if re.match(r"[ \t]*[\-–—]", folded[end:end + 4]) or ABOUT_THEM.search(folded, end, min(len(folded), end + 160)):
            continue  # "… 205-группа — лучший студент", "…. Bu talaba haqida 10 slayd": the topic
        spans.append((start, end, 'person'))
    return spans


UNPRINTABLE = re.compile('[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F\uFFFD\uFFFE\uFFFF\u200B-\u200F'
                         '\u202A-\u202E\u2060-\u2069\uFEFF]')


FIRST_PERSON = re.compile(r"(?<![\w'])((?:o'?qituvchi|ustoz|rahbar|guruh|sinf|kurs|talaba|o'?quvchi)(?:si)?)(?:m|im|miz|imiz)"
                          r"(?=[ \t]*:)|(?<=si)(?:man|miz)(?![\w'])", I)


LIST_MARK = re.compile(r"^[ \t]*(?:\d{1,2}[.)][ \t]+|[*•·▪◦➤➡👉✅✔☑\u2600-\u27BF\U0001F000-\U0001FAFF\uFE0F]+[ \t]*)+")


def _clean(line):
    line = FIRST_PERSON.sub(lambda match: match.group(1) or '', LIST_MARK.sub('', UNPRINTABLE.sub('', line)))
    line = VALUE_TAIL.sub('', ' '.join(line.split())).strip(' ,;-–—').lstrip(':').strip()
    if line.endswith(':') and not LABEL.fullmatch(_fold(line) + ' '):
        line = line.rstrip(':').strip()  # a label alone on its line keeps its colon: "Tayyorladi:"
    pairs = {'«': '»', '“': '”', '„': '“', '"': '"', "'": "'"}
    if line[:1] in pairs and pairs[line[:1]] not in line[1:]:
        line = line[1:]  # an opening quote whose words were cut off
    closing = {value: key for key, value in pairs.items()}
    if line[-1:] in closing and closing[line[-1:]] not in line[:-1]:
        line = line[:-1]
    if line.endswith('.') and not re.search(r"(?<![\w'])\w\.$", line) and not ABBREVIATION.search(_fold(line[:-1])):
        line = line[:-1]
    return line.strip()


def _a_person(line):
    """Whether a title line says who: a person's label, or a name in it."""
    folded = _fold(line)
    label = LABEL.match(folded)
    if label and (label.group('verb') or label.group('person')):
        return True
    lower = not any(_capital(word) for word in WORD.findall(line))
    return bool(_name_runs(line, lower=lower)) or _person_value(line, 0, len(line))


MOVED = re.compile(r"(?<![\w'])(?:перенес\w*|перемест\w*|ko'chir\w*|move\w*)(?![\w'])", I)


def _taken_away(scan, position):
    """Whether the sentence round `position` asks to remove or move what is there, not to write it."""
    start, end = _clause(scan.folded, position, position)
    if (start, end) not in scan.taken:
        scan.taken[start, end] = _removes(scan.folded[start:end])
    return scan.taken[start, end]


def _removes(sentence):
    return bool((REMOVAL.search(sentence) or MOVED.search(sentence)) and not NOT_REMOVED.search(sentence)
                and not re.search(r"(?<![\w'])(?:yoz|yozing|yozib|yozilsin|qo'?sh|qo'?shing|qo'?y|qo'?ying|напиши|добавь|впиши"
                                  r"|write|add|put)(?![\w'])", sentence, I))


def dictated(text):
    """The title-page lines `text` dictates, exactly as written and in its order; [] if it plainly dictates none."""
    text = str(text or '')
    if not text.strip():
        return []
    scan = _Scan(text)
    debs = _dictated_with_deb(scan)
    named = _self_named(scan)
    debs += [span for span in named if span[2].startswith('label:')]
    spans = (_labelled(scan) + [span for span in debs if span[2] == 'line'] + _blocks(scan) + _beside_group(scan)
             + [span for span in named if not span[2].startswith('label:')])
    # Lines quoted to come off or move elsewhere are not dictated: "Muqovadagi «Qabul qildi: …» ni o'chir".
    spans = [span for span in spans if not _taken_away(scan, span[0])]
    # The widest reading of each piece of text, in the order it was written.
    kept = []
    for start, end, _ in sorted(set(spans), key=lambda span: (span[0], -span[1])):
        if kept and start < kept[-1][1]:
            kept[-1] = (kept[-1][0], max(end, kept[-1][1]))
            continue
        kept.append((start, end))
    pieces = [(start, text[start:end]) for start, end in kept]
    # "Qabul qildi qismiga Nazarova Feruza deb yoz": the line "Qabul qildi: Nazarova Feruza".
    for start, end, kind in debs:
        if kind.startswith('label:'):
            label_start = int(kind.split(':')[1])
            label = re.match(rf"(?:{PERSON_VERBS}|{PERSON_NOUNS})", scan.folded[label_start:], I)
            pieces.append((label_start, f'{text[label_start:label_start + label.end()]}: {text[start:end]}'))
    lines, seen = [], set()
    for _, piece in sorted(pieces):
        for part in re.split(r"\n|[ \t]/[ \t]", piece):
            line = _clean(part)
            if line and len(line.split()) <= LINE_WORDS and len(line) <= LINE_CHARS and line.lower() not in seen:
                lines.append(line)
                seen.add(line.lower())
    # A title page says who made it: a group, a class or a school alone is a lesson plan's heading —
    # unless the request puts a student group on the title page itself ("Birinchi slaydga: 302-guruh").
    if not any(_a_person(line) for line in lines):
        return []
    if len(lines) > TITLE_LINES:
        # Too many for a cover: who made it and their group stay, the headers above them give way.
        people = [index for index, line in enumerate(lines)
                  if _a_person(line) or GROUP.search(_fold(line)) or CLASS.search(_fold(line))
                  or GROUP_NOUN.match(_fold(line))][:TITLE_LINES]
        rest = [index for index in range(len(lines)) if index not in people][:TITLE_LINES - len(people)]
        lines = [lines[index] for index in sorted(people + rest)]
    return lines


# ---------------------------------------------------------------- the cover


# The role a title line's label gives it, read in Latin so a line and its translation have the same one.
ROLES = (
    ('made', r"tayyorl|bajar|topshir|tuzuvchi|muallif|ijrochi|taqdim etdi|v[iy]poln|sdela|podgotov|avtor|prepared"
             r"|done by|made by|presented|submitted by|completed by|created by|author"),
    ('student', r"talaba|o'?quvchi|student|uchen|pupil|f\.?i\.?sh|fio"),
    ('checked', r"qabul|tekshir|prover|prinya|checked|reviewed|submitted to|accepted"),
    ('teacher', r"o'?qituvchi|ustoz|rahbar|prepodav|uchitel|rukovod|teacher|supervisor|instructor|lecturer|tutor"),
    ('group', r"guruh|grupp|group"), ('class', r"sinf|klass|class|grade"), ('course', r"kurs|course|bosqich"),
    ('faculty', r"fakultet|faculty"), ('department', r"kafedra|department"),
    ('school', r"maktab|litse|kollej|kolledzh|shkol|school|college"),
    ('university', r"universitet|institut|akademi|university|institute|academy"),
    ('direction', r"yo'nalish|napravleni|direction|specialty"),
)
# A label as a line opens with it, in Latin: "Tayyorladi:", "Vypolnila:", "Prepared by", "Fan o'qituvchisi:".
LATIN_LABEL = re.compile(r"^[ \t•\-–]*(?:[\w'.]+[ \t]+){0,2}?(?:tayyorl\w*|bajar\w*|qabul[ \t]+qil\w*|tekshir\w*|topshir\w*"
                         r"|tuzuvchi|muallif\w*|ijrochi|taqdim[ \t]+etdi|v[iy]poln\w*|sdelal\w*|podgotovil\w*|proveril\w*"
                         r"|prinyal\w*|avtor\w*|prepodavatel\w*|uchitel\w*|rukovoditel\w*|student\w*|uchenik\w*|uchenitsa"
                         r"|talaba\w*|o'?quvchi\w*|o'?qituvchi\w*|ustoz\w*|rahbar\w*|f\.?i\.?sh\.?|fio|ism[ \t]+familiya"
                         r"|guruh|gruppa|group|sinf|klass|class|kurs|course|fakultet|faculty|kafedra|department|maktab|school"
                         r"|universitet|university|(?:prepared|done|made|presented|submitted|completed|checked|reviewed)[ \t]+(?:by|to)"
                         r"|created[ \t]+by|accepted[ \t]+by|author|teacher|supervisor|instructor|lecturer|tutor|pupil)"
                         r"(?:\([a-z]{1,2}\))?(?:[ \t]*[:\-–—]|(?=[ \t]))", I)
LATIN_VERB = re.compile(r"(?:tayyorladi|bajardi|qabul qildi|tekshirdi|v[iy]polnil\w*|sdelal\w*|podgotovil\w*"
                        r"|proveril\w*|prepared by|submitted by|checked by|made by|done by|presented by)")
# Endings a name takes in a sentence: "Malikaman" (I am Malika), "Dilnozaning" (Dilnoza's).
WORD_ENDINGS = ('man', 'miz', 'ning', 'ni', 'ga', 'da', 'dan', 'im', 'si')


@functools.lru_cache(maxsize=512)
def _latin(line):
    """A line as lines are compared: in Latin, one apostrophe."""
    from .scripts import to_script
    return _fold(to_script(line, 'en'))


def _key(line):
    return ' '.join(re.findall(r"[\w']+", _latin(line).lower()))


@functools.lru_cache(maxsize=512)
def _label(line):
    """(role, label) of a line that opens with a label (or ends with a verb: "X tayyorladi"); (None, '') otherwise."""
    latin = _latin(line)
    found = LATIN_LABEL.match(latin)
    head = found.group(0) if found else ''
    if not head:
        verb = LATIN_VERB.search(latin.lower().rstrip(' .'), max(0, len(latin.rstrip(' .')) - 16))
        head = verb.group(0) if verb and verb.end() >= len(latin.rstrip(' .')) else ''
    role = next((role for role, pattern in ROLES if head and re.search(pattern, head.lower())), None)
    if not found:
        return role, ''
    # The label as the line writes it, in its own alphabet: up to its colon, or as long as the label read.
    colon = line.find(':')
    own = LABEL.match(_fold(line))
    label = line[:colon] if 0 <= colon <= len(line) and colon <= found.end() + 4 else line[:own.end()] if own else ''
    return role, label.rstrip(' \t:-–—')


def _role(line):
    return _label(line)[0]


@functools.lru_cache(maxsize=512)
def _words(line):
    """What a line says, label aside, as words in Latin: names, groups, places."""
    latin = _latin(line)
    found = LATIN_LABEL.match(latin)
    rest = latin[found.end():] if found else latin
    words = [word.lower() for word in re.findall(r"[\w']+", rest)]
    role = _label(line)[0]
    if role and not found:  # "Karimova Dilnoza tayyorladi"
        words = [word for word in words if not LATIN_VERB.fullmatch(word) and word not in ('by', 'qildi')]
    return tuple(words)


def _has(word, words):
    """Whether `word` is among `words`, an initial among full names, an ending aside ("Malika" in "Malikaman")."""
    for other in words:
        if word == other or (len(word) == 1 and other.startswith(word)):
            return True
        shorter, longer = sorted((word, other), key=len)
        if len(shorter) >= 3 and longer.startswith(shorter) and longer[len(shorter):] in WORD_ENDINGS:
            return True
    return False


def _covers(line, other):
    """Whether `line` says everything `other` says: "Tayyorladi: Sobirov Jasur, MT-21 guruh" covers its first half.

    A label is part of what a line says: "Karimova Dilnoza · Rashidova Malika"
    does not say "Tayyorladi: Karimova Dilnoza".
    """
    words = _words(other)
    role = _role(other)
    return bool(words) and (not role or role == _role(line)) and all(_has(word, _words(line)) for word in words)


def _people(line):
    """The surnames a line names, in Latin: "karimova" for "Каримова Дилноза" and "Karimova D."."""
    latin = _latin(line)
    words = WORD.findall(latin)
    found = set()
    for start, end in _name_runs(latin, lower=not any(_capital(word) for word in words)):
        found |= {CASE_ENDING.sub('', word.lower()) if len(word) > 6 else word.lower()
                  for word in WORD.findall(latin[start:end]) if _surname(_fold(word)) and not PATRONYMIC.match(word)}
    return found


@functools.lru_cache(maxsize=512)
def _names(line):
    """Every word of the names a line has, in Latin, with no case ending: {"karimova", "dilnoza"}."""
    latin = _latin(line)
    lower = not any(_capital(word) for word in WORD.findall(latin))
    return frozenset(CASE_ENDING.sub('', word.lower()) if len(word) > 6 else word.lower()
                     for start, end in _name_runs(latin, lower=lower) for word in WORD.findall(latin[start:end])
                     if not PATRONYMIC.match(word))


def _same_person(line, other):
    """Two lines for one person in one role: "Tayyorladi: Ergasheva M." and "Bajardi: Ergasheva Malika"."""
    role = _role(line)
    return bool(role and role == _role(other) and _people(line) & _people(other))


def _only_people(line):
    """Whether a line says who and nothing else: names, a group, a school — not "Bobur hayoti va ijodi"."""
    rest = line[len(_label(line)[1]):].lstrip(' \t:-–—') if _label(line)[1] else line
    folded = _fold(rest)
    left = [word for word in _leftover(rest, folded, 0, len(rest))
            if not (DESIGNATION_WORDS.fullmatch(word) or INSTITUTION.fullmatch(word) or ABBREVIATION.fullmatch(word))]
    return bool(WORD.search(rest)) and not left


def _corrections(request):
    """The names a request corrects: "Sobirova Madina o'rniga Sobirova Mohinur", "Sobirova emas, Sabirova" — (old, new)."""
    text = str(request or '')
    folded = _fold(text)
    pairs = []
    for found in REPLACED.finditer(folded):
        before = [run for run in _name_runs(text, max(0, found.start() - 60), found.start())
                  if found.start() - run[1] <= 3]
        after = [run for run in _name_runs(text, found.end(), found.end() + 60) if run[0] - found.end() <= 3]
        if before and after:
            old, new = text[before[-1][0]:before[-1][1]], text[after[0][0]:after[0][1]]
            if word := next((word for word in WORD.findall(old) if _surname(_fold(word))), None):
                pairs.append((old, new))
    return pairs


# A change that adds a person beside those there: "yana bir ism qo'sh", "add another name", "добавь ещё".
ADDING = re.compile(r"(?<![\w'])(?:yana[ \t]+bir|yana[ \t]+(?:ism|odam|muallif|talaba)\w*|qo'shimcha|ikkinchi[ \t]+(?:muallif|ism)"
                    r"|sherig\w*|hamkor\w*|another|also[ \t]+add|too|partner\w*|co-?authors?|second[ \t]+(?:author|name)|ещ[её]"
                    r"|и[ \t]+также|тоже|соавтор\w*|напарни\w*|второ\w*[ \t]+(?:автор|им))(?![\w'])", I)


def _at(body, entry):
    """Where `entry` itself is in `body` — not another line that reads the same."""
    return next(index for index, other in enumerate(body) if other is entry)


def _cover_lines(content, cover_id):
    """The lines of `content`'s cover, if it is the same cover; None otherwise."""
    sections = (content or {}).get('sections') or [] if isinstance(content, dict) else []
    if not sections or not isinstance(sections[0], dict) or sections[0].get('id') != cover_id:
        return None
    return [line for line in str(sections[0].get('body') or '').split('\n') if line.strip()]


def apply(data, content):
    """`place`, never failing a job: a deck whose lines cannot be placed is drawn as the model wrote it."""
    try:
        return place(data, content)
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Title lines could not be set on a cover')
        return content


# A byline the model left to fill in: "Tayyorladi: ______", "Prepared by: [Your Name]", "Выполнил: ФИО".
PLACEHOLDER = re.compile(r"[\s_.\-–—…*]*|\[.*\]|<.*>|\(.*\)|ism[ \t]+familiya\w*|familiya[ \t]+ism\w*|f\.?\s?i\.?\s?sh\.?|фио"
                         r"|ф\.\s?и\.\s?о\.?|your[ \t]+name|name[ \t]+surname|student[ \t]+name|ismingiz|talaba|student|студент\w*", I)


def _placeholder(line):
    """Whether a line is a label with nothing of anyone's after it, or a stand-in for a name."""
    label = _label(line)[1]
    return bool(label) and bool(PLACEHOLDER.fullmatch(line[len(label):].strip(' \t:-–—')))


def _joined(lines):
    """The cover's lines with a bare label joined to the name on the line below it: "Tayyorladi:\nKarimova Dilnoza"."""
    out = []
    for line in lines:
        if out and _placeholder(out[-1]) and not _label(line)[1] and _only_people(line):
            out[-1] = f'{_label(out[-1])[1]}: {line.strip()}'
            continue
        out.append(line)
    return out


def place(data, content):
    """Put the lines the customer dictates for a deck's title slide on its cover, taking nothing else off it; the content.

    A new deck takes them from its description, a change from its request; a
    change that dictates none leaves the cover to the model, which is given
    the deck as it stands. A line the cover already says in full is left as
    the model wrote it; the model's own version of one (its "Name · Name",
    its "Bajardi: Ergasheva M.", a placeholder, or in a change another
    person in that role) becomes the customer's; every other line stays, and
    theirs go in among each other in the order they wrote them. A correction
    ("X o'rniga Y") is made in the model's line for X. After an outline, the
    cover the customer reviewed says which of its lines are still theirs.
    Lines are set in the deck's alphabet.
    """
    if data.get('output_format') != 'pptx':
        return content
    sections = content.get('sections') or []
    revision = data.get('revision') or {}
    if len(sections) < 2 or not isinstance(sections[0], dict):
        return content
    cover = sections[0]
    selected = revision.get('selected_section_ids')
    if selected and cover.get('id') not in selected:
        return content
    from .scripts import to_script
    locale = data.get('output_locale')

    def written(line):
        return _clean(to_script(line, locale) if locale else line)

    options = data.setdefault('options', {})
    request = (revision.get('request') or '') if revision else (data.get('prompt') or '')
    wanted = [line for line in dict.fromkeys(written(line) for line in dictated(request)) if line]
    had = options.get('title_lines') if isinstance(options.get('title_lines'), list) else None
    seen = _cover_lines(data.get('content'), cover.get('id'))
    if not revision and had is not None and seen is not None:
        # The outline carried them: a line the customer edited there is theirs as edited, one they deleted is gone.
        outlined = [line for line in dict.fromkeys(written(line) for line in had if isinstance(line, str)) if line]
        mine, taken = [], set()
        for line in outlined:
            match = next((index for index, other in enumerate(seen) if index not in taken and _key(other) == _key(line)), None)
            if match is None:
                match = next((index for index, other in enumerate(seen) if index not in taken
                              and (_covers(other, line) or _same_person(line, other))), None)
            if match is not None:
                taken.add(match)
                mine.append(written(seen[match]))
        wanted = mine + [line for line in wanted if not any(
            _key(line) == _key(other) or _covers(other, line) or _same_person(line, other) for other in outlined)]
    body = [[line, 'model'] for line in _joined([line for line in str(cover.get('body') or '').split('\n') if line.strip()])]
    # "Sobirova Madina o'rniga Sobirova Mohinur deb yoz": corrected in the model's line for it.
    for old, right in _corrections(request) if revision else []:
        for entry in body:
            if entry[1] == 'model' and _covers(entry[0], old) and not _covers(entry[0], right):
                whole = re.compile(rf"(?<![\w']){re.escape(old)}(?![\w'])", I)
                label = _label(entry[0])[1]
                entry[:] = [written(whole.sub(right, entry[0]) if whole.search(entry[0]) else
                                    f'{label}: {right}' if label else right), 'new']
                wanted = [line for line in wanted if not _covers(entry[0], line)]
    if not wanted and not any(origin == 'new' for _, origin in body):
        if not revision:
            options['title_lines'] = []
        return content
    adding = bool(revision) and bool(ADDING.search(_fold(request)))
    people = set().union(*(_people(line) for line in wanted)) if wanted else set()
    everything = [word for line in wanted for word in _words(line)]

    def alone(line, other):
        # The model's line names no one else of the customer's: "Tayyorladi: X va Y" is not X's line alone.
        return not ((_people(other) & people) - _people(line))

    placed = []
    for line in wanted:
        entry = next((entry for entry in body if entry[1] == 'model' and _key(entry[0]) == _key(line)), None) or next(
            (entry for entry in body if entry[1] == 'model' and _covers(entry[0], line) and alone(line, entry[0])), None)
        if entry is not None:
            if _words(line) == _words(entry[0]) and (_label(line)[1] or not _label(entry[0])[1]):
                entry[0] = line  # says just the same: as the customer wrote it ("Выполнила:", not "Выполнил(а):")
            entry[1] = 'new'  # the cover already says it, perhaps more fully
            placed.append(entry)
            continue
        candidates = [entry for entry in body if entry[1] == 'model']
        entry = (next((entry for entry in candidates if _same_person(line, entry[0])), None)
                 # Its own line for this person, labelled otherwise or not at all: "9-sinf o'quvchisi Karimova Dilnoza".
                 or next((entry for entry in candidates if _only_people(entry[0]) and len(_names(entry[0]) & _names(line)) >= 2
                          and alone(line, entry[0])), None)
                 # A line merging the customer's people: "Karimova Dilnoza · Rashidova Malika".
                 or next((entry for entry in candidates if _only_people(entry[0]) and _people(entry[0]) & _people(line)
                          and all(_has(word, everything) for word in _words(entry[0]))), None)
                 # A placeholder for the role: "Tayyorladi: ______".
                 or next((entry for entry in candidates if _role(line) and _role(entry[0]) == _role(line)
                          and _placeholder(entry[0])), None))
        if entry is None and revision and not adding and _role(line) in ('made', 'checked', 'teacher'):
            # A change that dictates who did it again means that person, not another beside them.
            entry = next((entry for entry in candidates if _role(entry[0]) == _role(line) and not _people(entry[0]) & people), None)
        if entry is not None:
            entry[:] = [line, 'new']
            # And the model's lines it now says in full: "026-136-guruh" alone under "Karimova Dilnoza 026-136-guruh".
            body = [other for other in body if other is entry or other[1] != 'model'
                    or not _only_people(other[0]) or not _covers(entry[0], other[0])]
        placed.append(entry)
    for number, line in enumerate(wanted):
        if placed[number] is not None:
            continue
        if any(_key(entry[0]) == _key(line) or (_covers(entry[0], line) and alone(line, entry[0])) for entry in body):
            continue  # already there, in a line the customer's own lines took
        before = next((entry for entry in reversed(placed[:number]) if entry is not None), None)
        after = next((entry for entry in placed[number + 1:] if entry is not None), None)
        position = (_at(body, before) + 1 if before else _at(body, after) if after else len(body))
        placed[number] = [line, 'new']
        body.insert(position, placed[number])
    while len(body) > TITLE_LINES and any(entry[1] == 'model' for entry in body):
        del body[_at(body, next(entry for entry in reversed(body) if entry[1] == 'model'))]  # the model's own give way
    body = body[:TITLE_LINES]
    if not revision:
        options['title_lines'] = [line for line, origin in body if origin != 'model']
    text = '\n'.join(line for line, _ in body)
    if text == cover.get('body'):
        return content
    return {**content, 'sections': [{**cover, 'body': text}] + sections[1:]}
