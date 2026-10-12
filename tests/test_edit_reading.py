"""What a change request asks for, read before it is priced (apps/studio/edits.py).

A change used to keep its document's length and look whatever it said: "add 1
page" was a total of one and so ignored, "Test tuz" found no number and added
no test, and "har bir slaydda rasm" got the same pictures as before. The
requests below are real ones, anonymised, with what each asks for.
"""
import time

import pytest

from apps.studio import edits
from apps.studio.edits import asks_only_for_format, read


def deck(count, *, headings=None, pictures=False):
    """A deck as it stands: a cover, then content slides, some with photos."""
    headings = headings or [f'Slide {n}' for n in range(1, count + 1)]
    return [{'id': f's{n + 1}', 'heading': headings[n], 'body': 'Text.',
             'layout': 'cover' if n == 0 else 'image_split' if pictures and n % 3 == 1 else 'bullets',
             'image_query': 'school class' if pictures and n % 3 == 1 else ''} for n in range(count)]


def document(count, headings=None):
    headings = headings or [f'Part {n}' for n in range(1, count + 1)]
    return [{'id': f's{n + 1}', 'heading': headings[n], 'body': 'Text.'} for n in range(count)]


def reading(request, fmt='pptx', count=8, questions=0, **kwargs):
    sections = deck(count, **kwargs) if fmt == 'pptx' else document(count)
    return read(request, fmt=fmt, sections=sections, questions=questions)


# The 27 change requests of the last thirty days, as they were written (names
# replaced), and what each of them asks for.
REAL = [
    (1, 'pdf', 5, 0, "Rasmlar boʻlsin", {'pictures': 'add'}),
    (2, 'pptx', 5, 0, "10 betli PowerPoint taqdimoti. Birinchi betda maktabing, sinfing va to‘liq isming. Muqovada 4 "
                      "ta kichik rasm. Har bir betda zamonaviy maktab hayotiga oid rasmlar. Chiroyli dizayn va "
                      "maqolning batafsil tahlili.",
     {'total': 10, 'pictures': 'every', 'redesign': True, 'expand': True}),
    (3, 'pdf', 5, 0, "Rasmlar yozuvlar orasida unchalik kichik bo'lmagan holda tayyorlansin.", {'pictures': 'add'}),
    (4, 'pptx', 12, 0, "Bu ilovada ochilmayapti pdf shaklida yubor", {'format': 'pdf', 'format_only': True}),
    # A deck's title page is its cover: the dictated lines go there, and no slide moves.
    (5, 'pptx', 12, 0, "Boshiga bitta sahifa qoʻsh va Karimova Dilnoza Rustam qizi 021-104-guruh deb yoz keyn "
                       "Eftaliylar Xioniylar kidariylar va Turk xoqonligi qachon va kim tomonidan tashkil topgani "
                       "va tugatilgani haqida ham yoz rasmlar qoʻsh mavzuga doir",
     {'parts': ['title_page'], 'delta': 0, 'total': None, 'pictures': 'add', 'structural': False}),
    (6, 'pptx', 12, 0, "Malumotlarni kengroq ber keyin har bir davlat haqida maʼlumot ber davlatni qachon va km "
                       "tashkil topgani va qachon va kim tomonidan tugatilgani haqida maʼlumot ber keyin har bir "
                       "davlatga mos rasm taxlab ber",
     {'expand': True, 'pictures': 'add', 'delta': 0}),
    (7, 'pptx', 7, 0, "Yosh bolacha rasm qoʻyma. Realga oʻxshasin. Oʻtirgan odam qiziqib tomosha qilsin",
     {'photo_style': 'photo', 'pictures': None}),
    (8, 'pptx', 7, 0, "Jinoyatga oid rasmlar ham qoʻsh", {'pictures': 'add'}),
    (9, 'pptx', 12, 10, "Vaziyatli masalalarni va testlarni oʻchir.", {'questions': 'remove', 'delta': 0}),
    (10, 'pptx', 9, 0, "Shunga boshidagi bir betga 45-maktab 7-B sinf oʻquvchisi Aliyev Sardorning \"Ustoz otangdek "
                       "ulugʻ\" maqoli boʻyicha tayyorlagan taqdimoti deb yoz va ustoz oʻquvchilarning rasmini kichik "
                       "kichik qilib toʻrtta qoʻy. Keyin hamma betda rasmlar boʻlsin",
     {'pictures': 'every', 'total': None, 'delta': 0, 'parts': []}),
    (11, 'pptx', 12, 0, "Reja ham bo'lsin kirish va xulosa qismi ham",
     {'parts': ['plan', 'introduction', 'conclusion'], 'structural': True}),
    (12, 'pptx', 12, 0, "Rasmlar tabiiyga o'xshash bo'lmasligi kerak kitoblarda beriladigan rasmga o'xshashi kerak",
     {'photo_style': 'illustration', 'pictures': None}),
    (13, 'pdf', 7, 0, "Har bir sahifada rasm bo'lishi kerak.", {'pictures': 'every', 'picture_count': None}),
    (14, 'pptx', 6, 0, "Ochiq darsga 6 ta slayd kerak. Tilshunoslik bõlimidan. Yozuv va uning tarixiy kõrinishlari. "
                       "Har slaydda tushuntirish va misol, och havorangda",
     {'total': 6, 'questions': None, 'pictures': None, 'structural': False}),
    (15, 'pptx', 10, 10, "savol so'rash salydi 2 bet bo'libdi. shuni 1 bet qil , yana bir betiga qanaqador malumot yoz",
     {'total': None, 'delta': 1, 'question_count': 5, 'questions': None}),
    (16, 'pptx', 10, 0, "Akbaraliga qo'yilgan rasmni olib tashlang, Akbarali obrazini to'liq yorit, parchadagi "
                        "Azimjon, Ochil bobo, Bektemir obrazlarini ham qo'shib, tavsiflab ber",
     {'pictures': 'remove', 'expand': True, 'delta': 3, 'structural': True}),
    (17, 'pdf', 6, 0, "Test tuz", {'questions': 'add', 'question_count': None}),
    (18, 'pptx', 10, 0, "Ong mavzusini olib tashlash va oʻrniga sezgi mavzusi haqida batafsil malumot berish",
     {'expand': True, 'delta': 0, 'pictures': None}),
    (19, 'pptx', 9, 0, "Hammasi avvalgidek bo‘lsin o‘sha men so‘ragan 9ta slayd faqat hamma yozuvlar lotin alifbosida "
                       "xatosiz yozilsin va har bir slaydda matnga mos rasm ham bolsin",
     {'total': 9, 'pictures': 'every', 'structural': False}),
    (20, 'pptx', 5, 0, "10 varoqlik va kengroq malumotli boʻlishi kerak", {'total': 10, 'expand': True}),
    (21, 'pptx', 8, 0, "Ingiliz tilida tayyorla", {}),
    (22, 'pptx', 8, 0, "Slayd English languageda boʻlsin", {}),
    (23, 'pptx', 12, 0, "Ko‘lproq malumot", {'expand': True}),
    (24, 'pptx', 10, 0, "Varoqlarni hammasini bir hil qil", {'redesign': True, 'delta': 0}),
    (25, 'pptx', 9, 0, "Krilcha harflarda yozilgan ayrim joylarda shuni to‘g‘rilash kerak. Keyin har 1ta slaydga rasm "
                       "qo‘shilsin. Matnga mos. Mavzu ham to‘liq yozilmagan. \"O‘zbekistonda pedagogika fanining "
                       "rivojlanishi\" deb to‘liq yozish kerak.",
     {'pictures': 'every', 'total': None, 'expand': False}),
    (26, 'pptx', 10, 0, "Orasidagi daftar varogʻiga oxshagan sahifalarni boshqasiga almashtir. Imlosiga etibor ber. "
                        "Toʻliqroq malumot boʻlsin. Rus alifbosini ishlatma",
     {'redesign': True, 'expand': True, 'delta': 0}),
    (27, 'pdf', 6, 0, "Shu mavzuga oid rasmlar ham qo'shing", {'pictures': 'add'}),
]
NOTHING = edits.Edit()


@pytest.mark.parametrize('number,fmt,count,questions,request_text,expected', REAL,
                         ids=[f'request-{r[0]}' for r in REAL])
def test_real_change_requests_are_read_for_what_they_ask(number, fmt, count, questions, request_text, expected):
    # The decks asking for another kind of picture already have pictures.
    sections = deck(count, pictures=number in (7, 12)) if fmt == 'pptx' else document(count)
    edit = read(request_text, fmt=fmt, sections=sections, questions=questions)
    for key, value in expected.items():
        assert getattr(edit, key) == value, (key, edit)
    # Nothing is read that the request does not say.
    for key in ('total', 'delta', 'parts', 'questions', 'redesign', 'format'):
        if key not in expected:
            assert getattr(edit, key) == getattr(NOTHING, key), (key, edit)


@pytest.mark.parametrize('request_text,total', [
    ("savollar 10 ta bo'lsin", None),
    ("rasmlar 5 ta bo'lsin", None),
    ('10 varoqlik qil', 10),
    ('9ta slayd bo‘lsin', 9),
    ('make it 12 slides', 12),
    ('сделай 15 слайдов', 15),
    ('12 ta slayddan iborat bo‘lsin', 12),
    # A total of one is never taken from a change request.
    ('1 bet qil', None),
    # What the deck is now is not what it should be.
    ("12 ta slayd bo'libdi, kamroq qil", None),
])
def test_a_new_total_is_read(request_text, total):
    edit = reading(request_text)
    assert edit.total == total and edit.delta == 0


@pytest.mark.parametrize('request_text,delta', [
    ("bitta sahifa qo'sh", 1),
    ("yana 2 ta slayd qo'shing", 2),
    ("2 ta yangi slayd qo'sh", 2),
    ("yangi slayd qo'sh", 1),
    ('add one more slide', 1),
    ('add 3 slides', 3),
    ('add another page about the causes', 1),
    ('two more slides please', 2),
    ('добавь 2 слайда', 2),
    ('добавь ещё один слайд', 1),
    ("oxirgi slaydni olib tashla", -1),
    ("3-slaydni o'chir", -1),
    ("3- va 4-slaydlarni o'chir", -2),
    ("oxirgi ikkita slaydni o'chir", -2),
    ('remove the last two slides', -2),
    ('delete slide 3', -1),
    ('remove slides 3 and 4', -2),
    ('удали последний слайд', -1),
    ('удали последние 2 слайда', -2),
    # Cyrillic Uzbek is read as Uzbek.
    ('битта слайд қўш', 1),
    ('охирги слайдни ўчир', -1),
])
def test_pages_added_and_removed_are_read(request_text, delta):
    edit = reading(request_text)
    assert edit.delta == delta and edit.total is None and edit.structural


@pytest.mark.parametrize('request_text,expected', [
    # A picture on slide three, not three slides or a third slide gone.
    ("3-slaydga rasm qo'sh", {'pictures': 'add', 'picture_count': 1}),
    ("3 ta slaydga rasm qo'sh", {'pictures': 'add', 'picture_count': 3}),
    # A picture on every slide, not a one-slide deck.
    ('Keyin har 1ta slaydga rasm qo‘shilsin.', {'pictures': 'every'}),
    ('2-bobni kengaytir', {'expand': True}),
    ("3-slayddagi rasmni o'chir", {'pictures': 'remove'}),
    ('remove the picture on slide 3', {'pictures': 'remove'}),
    ("3-slaydni qisqartir", {}),
    ("o'chirma bu slaydni", {}),
])
def test_what_is_not_a_page_added_or_removed(request_text, expected):
    edit = reading(request_text)
    assert edit.delta == 0 and edit.total is None
    for key, value in expected.items():
        assert getattr(edit, key) == value, (key, edit)


@pytest.mark.parametrize('request_text,fmt,parts,delta', [
    ("reja ham bo'lsin", 'pptx', ['plan'], 0),
    ('kirish va xulosa qo‘shing', 'pptx', ['introduction', 'conclusion'], 0),
    ("titul varag'i bo'lsin", 'pdf', ['title_page'], 0),
    ("foydalanilgan adabiyotlar ro'yxatini qo'sh", 'pdf', ['references'], 0),
    ('add an introduction and a conclusion', 'pptx', ['introduction', 'conclusion'], 0),
    ('добавь введение и заключение', 'pptx', ['introduction', 'conclusion'], 0),
    ('режа ҳам бўлсин', 'pptx', ['plan'], 0),
    # A page at the start with lines dictated for it is a title page; on a deck
    # it is the cover, so it is read but adds no slide (edits.added_parts).
    ("Boshiga bitta sahifa qo'sh va unga TAYYORLADI: KARIMOVA NODIRA deb yoz", 'pptx', ['title_page'], 0),
    ('add a page at the beginning with my name', 'pptx', ['title_page'], 0),
    ("Boshiga 2 ta sahifa qo'sh, birinchisiga ismimni yoz", 'pptx', ['title_page'], 1),
    ("Boshiga titul varag'ini qo'sh: MUSTAQIL ISH, Tayyorladi: Karimova Nodira", 'pptx', ['title_page'], 0),
    ('Добавь в начало титульный лист: Выполнила Каримова Нодира', 'pptx', ['title_page'], 0),
    ("Boshiga bitta sahifa qo'sh va unga TAYYORLADI: KARIMOVA NODIRA deb yoz", 'pdf', ['title_page'], 0),
    # A deck that dictates nothing gets slides after its cover; a document's
    # bare page at the start is its title page, one that says what it is about is not.
    ("boshiga 2 ta sahifa qo'sh", 'pptx', [], 2),
    ("Boshiga bitta slayd qo'sh, unda mavzuning dolzarbligi haqida yoz", 'pptx', [], 1),
    ("boshiga 2 ta sahifa qo'sh", 'pdf', ['title_page'], 1),
    ("Boshiga bitta bet qo'sh, unda mavzuning dolzarbligi haqida yoz", 'pdf', [], 1),
    # The page added for a part is that part, counted once.
    ("xulosa uchun bitta slayd qo'sh", 'pptx', ['conclusion'], 0),
    ('add a conclusion slide', 'pptx', ['conclusion'], 0),
    # Changing a part is not adding one.
    ('xulosani qisqartir', 'pptx', [], 0),
    ("kirishga bir gap qo'sh", 'pptx', [], 0),
    # A deck opens on its cover: a title page is already there.
    ("titul varag'i bo'lsin", 'pptx', [], 0),
])
def test_parts_are_added_once_each(request_text, fmt, parts, delta):
    edit = reading(request_text, fmt=fmt)
    assert edit.parts == parts and edit.delta == delta
    assert edit.structural == bool(edits.added_parts(parts, fmt) or delta)


def test_a_part_the_document_has_is_not_added_again():
    sections = deck(6, headings=['Cover', 'Reja', 'Kirish', 'Tarix', 'Bugun', 'Xulosalar'])
    assert read("Reja ham bo'lsin kirish va xulosa qismi ham", fmt='pptx', sections=sections).parts == []
    # A slide about planets is not a plan.
    sections = deck(4, headings=['Quyosh tizimi', 'Planetalar', 'Yulduzlar', 'Kometalar'])
    assert read("reja ham bo'lsin", fmt='pptx', sections=sections).parts == ['plan']
    sections = document(4, ['1. Introduction', 'History', 'Today', 'Conclusion: what remains'])
    edit = read('add an introduction, a conclusion and references', fmt='pdf', sections=sections)
    assert edit.parts == ['references'] and edit.delta == 0
    # One the request removes goes, and the count with it.
    assert read("xulosa slaydini olib tashla", fmt='pdf', sections=sections).delta == -1


def test_characters_named_to_be_added_each_get_a_slide():
    edit = read("Hikoyadagi Ali, Vali va Hasan obrazlarini ham qo'sh", fmt='pptx', sections=deck(8))
    assert edit.delta == 3 and edit.structural
    # One the deck already describes is not added again.
    edit = read("Ali, Vali va Hasan obrazlarini ham qo'sh", fmt='pptx',
                sections=deck(4, headings=['Cover', 'Ali obrazi', 'Vali', 'Xulosa']))
    assert edit.delta == 1
    assert read('add the characters Tom, Huck and Jim', fmt='pptx', sections=deck(8)).delta == 3
    # A document holds two to a page.
    assert read("Ali, Vali va Hasan obrazlarini ham qo'sh", fmt='pdf', sections=document(5)).delta == 2


@pytest.mark.parametrize('request_text,pictures,count', [
    ("rasmlar bo'lsin", 'add', None),
    ("rasm qo'sh", 'add', None),
    ("4 ta kichik rasm qo'sh", 'add', 4),
    ("bir nechta rasm qo'sh", 'add', None),
    ('add 3 pictures', 'add', 3),
    ('добавь картинки', 'add', None),
    ("chizmalar qo'sh", 'add', None),
    ("har bir slaydda rasm bo'lsin", 'every', None),
    ('hamma betda rasmlar', 'every', None),
    ('every slide a picture', 'every', None),
    ('на каждом слайде фото', 'every', None),
    ('ҳар бир слайдда расм бўлсин', 'every', None),
    ('rasmni olib tashla', 'remove', None),
    ('remove the pictures', 'remove', None),
    ('rasm kerak emas', 'remove', None),
    ('убери картинки', 'remove', None),
    # "Rasmiy" is official, not a picture; "tasvirla" is describe.
    ('Rasmiy uslubda yoz', None, None),
    ('Mavzuni batafsil tasvirlab ber', None, None),
])
def test_pictures_are_read(request_text, pictures, count):
    edit = reading(request_text)
    assert edit.pictures == pictures and edit.picture_count == count, edit


@pytest.mark.parametrize('request_text,style', [
    ("realga o'xshasin", 'photo'),
    ('haqiqiy rasmlar qo‘ying', 'photo'),
    ('use real photos', 'photo'),
    ('реалистичные картинки', 'photo'),
    ("yosh bolacha rasm qo'yma", 'photo'),
    ('kitoblardagi rasmlardek bo‘lsin', 'illustration'),
    ("kitoblarda beriladigan rasmga o'xshashi kerak", 'illustration'),
    ("chizma ko'rinishida bo'lsin", 'illustration'),
    ('illyustratsiya qilib ber', 'illustration'),
    ("rasmlar tabiiyga o'xshamasin", 'illustration'),
    ('use drawings', 'illustration'),
    ('illustrations instead of photos', 'illustration'),
    ('рисунки вместо фото', 'illustration'),
    ('иллюстрации', 'illustration'),
    ('yosh bolalar uchun tushunarli qil', None),
    ("rasm qo'sh", None),
])
def test_the_kind_of_picture_is_read(request_text, style):
    assert reading(request_text).photo_style == style


def test_pictures_made_bigger_or_swapped_are_not_more_pictures():
    assert reading('rasmlarni kattaroq qil', pictures=True).pictures is None
    assert reading('make the pictures bigger', pictures=True).pictures is None
    assert reading("rasmlarni mavzuga mos rasmlarga almashtir", pictures=True).pictures is None
    # A document without pictures that asks about them is asking for them.
    assert reading('rasmlarni kattaroq qil', pictures=False).pictures == 'add'


def test_a_kind_asked_of_pictures_a_document_lacks_adds_them():
    asked = "rasmlar kitoblardagi rasmlardek bo'lsin"
    assert reading(asked, pictures=True).pictures is None, 'the pictures it has, drawn instead'
    assert reading(asked, pictures=False).pictures == 'add'
    assert reading("haqiqiy rasmlar qo'sh", pictures=True).pictures == 'add'


@pytest.mark.parametrize('request_text,questions,count', [
    ('test tuz', 'add', None),
    ("test qo'sh", 'add', None),
    ("10 ta savol qo'sh", 'add', 10),
    ("savollar 10 ta bo'lsin", 'add', 10),
    ("yana 5 ta savol qo'sh", 'add', 15),
    ('add a quiz', 'add', None),
    ('make a test', 'add', None),
    ('добавь тест', 'add', None),
    ('добавь 7 вопросов', 'add', 7),
    ('тест туз', 'add', None),
    ("testlarni o'chir", 'remove', None),
    ('savollarni olib tashla', 'remove', None),
    ('remove the questions', 'remove', None),
    ('delete the tests', 'remove', None),
    ('убери вопросы', 'remove', None),
    ("3-savoldagi xatoni to'g'irla", None, None),
    ('savollarga javob ber', None, None),
])
def test_questions_are_read(request_text, questions, count):
    edit = reading(request_text, questions=10)
    assert edit.questions == questions and edit.question_count == count, edit


def test_the_question_slides_put_onto_fewer_slides_keep_that_many_questions():
    request_text = "savol so'rash salydi 2 bet bo'libdi. shuni 1 bet qil"
    assert reading(request_text, questions=10).question_count == 5
    assert reading(request_text, questions=4).question_count is None, 'they fit already'
    assert reading(request_text, questions=10).total is None, '"2 bet" is the deck as it is'


@pytest.mark.parametrize('request_text', [
    'chiroyli dizayn qil', "dizaynni o'zgartir", 'boshqa fon', "fonni o'zgartir",
    "varoqlarni hammasini bir xil qil", "daftar varag'iga o'xshagan sahifalarni almashtir",
    'change the design', 'change the background', 'make all slides look the same',
    'другой дизайн', 'другой фон', 'измени дизайн',
])
def test_a_new_look_is_read(request_text):
    assert reading(request_text).redesign


@pytest.mark.parametrize('request_text', [
    "bir xil so'zlarni takrorlama", 'change the style of writing to formal', 'Rasmiy uslubda yoz',
    'Dizayni yoqdi, faqat xatolarni tuzat', 'измени тему на экологию',
])
def test_what_is_not_a_new_look(request_text):
    assert not reading(request_text).redesign


@pytest.mark.parametrize('request_text', [
    'kengroq yoz', 'batafsil', "to'liqroq ma'lumot ber", "ko'proq ma'lumot", 'Ko‘lproq malumot',
    'more detail please', 'add more information', 'подробнее', 'больше информации', '2-bobni kengaytir',
])
def test_more_information_is_read(request_text):
    assert reading(request_text).expand


@pytest.mark.parametrize('request_text', ["to‘liq ismimni yoz", 'qisqaroq qil', 'Mavzu to‘liq yozilmagan'])
def test_what_is_not_more_information(request_text):
    assert not reading(request_text).expand


@pytest.mark.parametrize('request_text,fmt,kind,only', [
    ('pdf shaklida yubor', 'pptx', 'pdf', True),
    ('PDF formatida yuboring iltimos', 'pptx', 'pdf', True),
    ("pdf ko'rinishida bersangiz", 'pptx', 'pdf', True),
    ('send it as a pdf', 'pptx', 'pdf', True),
    ('в pdf пожалуйста', 'pptx', 'pdf', True),
    ('pdf qilib ber va 3-slaydni qisqartir', 'pptx', 'pdf', False),
    ('Ingliz tilida pdf qilib yubor', 'pptx', 'pdf', False),
    ('slayd qilib ber', 'pdf', 'pptx', True),
    ('pptx formatida kerak', 'pdf', 'pptx', True),
    # A document is already a PDF.
    ('pdf shaklida yubor', 'pdf', None, False),
    ('10 betli PowerPoint taqdimoti', 'pptx', None, False),
])
def test_another_file_format_is_read(request_text, fmt, kind, only):
    edit = reading(request_text, fmt=fmt)
    assert edit.format == kind and edit.format_only is only, edit


def test_a_request_for_the_file_alone_is_known_without_the_document():
    assert asks_only_for_format('Bu ilovada ochilmayapti pdf shaklida yubor') == 'pdf'
    assert asks_only_for_format('send as pdf') == 'pdf'
    assert asks_only_for_format('slayd qilib ber') == 'pptx'
    assert asks_only_for_format("pdf shaklida yubor, rasmlar ham bo'lsin") is None
    assert asks_only_for_format('Rasmlar boʻlsin') is None


# ------------------------------------------------- what the second review found
#
# A change has no page counter on the bot's review screen, so a count misread
# here can only be put right by rewording, and otherwise is paid for.


@pytest.mark.parametrize('request_text', [
    # A slide pointed at, not a size: these cut a ten-slide deck to two, seven or three.
    'fix typos on slide 2 and slide 6', '3-slayddagi va 7-slayddagi xatolarni tuzat', 'shorten the first 3 slides',
    'oxirgi 3 ta slaydni kengaytir', 'первые 3 слайда сократи', 'на 3 слайдах добавь фото',
    "3 ta slaydda xato bor", 'fix the typos in 3 slides',
    # The document as it is: "my twelve-slide deck".
    "12 slaydli taqdimotimga rasm qo'sh",
    # Not a slide count at all.
    'нужно 3 слайда про войну', 'I need 3 slides about the war', "misollar 3 ta bo'lsin",
    "har bir slaydda 3 ta bo'lsin", "2 betlik kirish qo'sh",
])
def test_a_number_that_is_not_a_new_size_is_no_total(request_text):
    assert reading(request_text, count=10).total is None


@pytest.mark.parametrize('request_text,total', [
    ("12 ta slayd bo'lsin", 12), ('6 ta slayd kerak', 6), ("10 ta slayd qilib ber", 10), ('12talik qil', 12),
    ("Taqdimot 10 ta slayddan iborat bo'lsin", 10), ('10 betli PowerPoint taqdimoti', 10),
    ("10 betli taqdimotni 12 betlik qil", 12), ('Slaydlarni 8 taga kamaytir', 8), ("10 slaydga qisqartir", 10),
    ("slaydlarni 12 tagacha ko'paytir", 12), ("slaydlar soni 12 ta bo'lsin", 12), ("o'n ikki slayd bo'lsin", 12),
    # What came is not what was asked: the number the request wants wins.
    ('8 ta slayd keldi, 10 ta kerak edi', 10), ("12 ta slayd emas, 10 ta bo'lsin", 10),
    ('make it 12 slides', 12), ('cut it down to 8 slides', 8), ('the deck has 12 slides, make it 10', 10),
    ('it should be about 10 slides', 10), ('10 slides instead of 12', 10), ('Same document but in 5 pages.', 5),
    ('сделай 15 слайдов', 15), ('сделай презентацию на 10 слайдов', 10), ('сократи до 8 слайдов', 8),
    ('всего 12 слайдов', 12), ('12 ta slayd.', 12),
])
def test_a_new_size_said_in_so_many_words_is_the_total(request_text, total):
    assert reading(request_text, count=10).total == total


@pytest.mark.parametrize('request_text,delta,total', [
    # Read as the same words with their apostrophes: "2 ta slayd qoshing" was a deck of two.
    ('2 ta slayd qoshing', 2, None), ('3 slaydni ochir', -3, None), ('ikki slayd qosh', 2, None),
    ('Oxiriga 2 ta slayd qosh', 2, None), ('oxirgi slaydni ochir', -1, None), ('3-slaydni ochir', -1, None),
    # A list or a range is that many slides, not its last number.
    ("5-7 slaydlarni o'chir", -3, None), ('5–7 slaydlarni olib tashla', -3, None),
    ("5, 6 va 7-slaydlarni olib tashla", -3, None), ("3 va 4-slaydlarni o'chir", -2, None),
    ('remove slides 5-7', -3, None), ('delete slides 2, 3 and 5', -3, None), ('удали слайды 5-7', -3, None),
    ('удали 5 и 6 слайды', -2, None),
    # Pages added beside a document described as it is now.
    ("10 ta slayddan iborat taqdimotga 2 ta slayd qo'sh", 2, None), ("3 ta rasmli slayd qo'sh", 3, None),
])
def test_pages_added_and_removed_however_they_are_typed(request_text, delta, total):
    edit = reading(request_text, count=10)
    assert (edit.delta, edit.total) == (delta, total)


def test_uzbek_without_apostrophes_reads_like_uzbek_with_them():
    pdf = reading('yana 3 bet qosh va rasmlar bolsin', fmt='pdf', count=5)
    assert pdf.delta == 3 and pdf.total is None and pdf.pictures == 'add'
    assert reading('testni ochir', questions=10).questions == 'remove'
    start = reading('Boshiga 1 bet qosh unga ismimni yoz')
    assert start.parts == ['title_page'] and start.delta == 0
    assert reading('rasm qoshmang', pictures=True).pictures == 'remove'
    assert reading("dizaynni ozgartirma, faqat xatolarni togirla").redesign is False


@pytest.mark.parametrize('request_text', [
    'rasmsiz qil', 'rasmlar shart emas', 'картинки не нужны', "rasmlarsiz bo'lsin", "rasmlarga hojat yo'q",
    "rasm qo'shmang", 'no pictures', 'без картинок',
])
def test_pictures_not_wanted_are_taken_away_and_never_added(request_text):
    assert reading(request_text, pictures=True).pictures == 'remove'
    # A document with none has nothing to take away, and gets none.
    assert reading(request_text, pictures=False).pictures is None
    assert reading(request_text, fmt='pdf').pictures is None


@pytest.mark.parametrize('request_text', ['test shart emas', 'testsiz qil', 'вопросы не нужны', 'savolsiz qil'])
def test_a_test_not_wanted_is_taken_away(request_text):
    edit = reading(request_text, questions=10)
    assert edit.questions == 'remove' and edit.question_count is None


@pytest.mark.parametrize('request_text', [
    "dizaynni o'zgartirma, faqat xatolarni tuzat", "don't change the design, only fix the typos",
    'do not change the background', 'keep the same design, add 2 slides', 'chiroyli dizaynini saqlab qol',
    'bir xil dizaynda qolsin', "fonni o'zgartirmang", "shablonni o'zgartirmang", 'не меняй дизайн', 'оставь дизайн',
    'boshqa dizayn kerak emas',
])
def test_a_look_kept_is_not_a_new_look(request_text):
    assert reading(request_text).redesign is False


@pytest.mark.parametrize('request_text', [
    "chiroyli dizayn qil va matnni saqla", "Dizaynni zamonaviy qil, matnni o'zgartirma", 'поменяй дизайн',
    "dizaynni o'zgartirmang, lekin fonni boshqa qil",
])
def test_a_new_look_beside_something_kept_is_still_a_new_look(request_text):
    assert reading(request_text).redesign is True


@pytest.mark.parametrize('request_text,count,more', [
    # The test's new size.
    ("savollar 5 ta bo'lsin", 5, False), ('savollarni 5 taga qisqartir', 5, False),
    ('savollar sonini 5 taga kamaytir', 5, False), ('leave only 5 questions', 5, False),
    ('оставь 5 вопросов', 5, False), ('reduce the questions to 5', 5, False), ('сократи вопросы до 5', 5, False),
    # Added to the ten the document has.
    ("10 ta savol qo'sh", 10, True), ('добавь 7 вопросов', 7, True), ("yana 5 ta savol qo'sh", 15, False),
])
def test_how_many_questions_and_whether_they_are_more(request_text, count, more):
    edit = reading(request_text, questions=10)
    assert edit.questions == 'add' and edit.question_count == count and edit.more_questions is more


def test_a_slide_number_past_the_content_is_a_question_slide():
    # Ten content slides and two of questions: slide 12 is the second question slide.
    edit = reading("12-slaydni o'chir", count=10, questions=10)
    assert edit.delta == 0 and edit.removed_question_slides == [2] and edit.question_count == 5
    assert reading("11-slaydni o'chir", count=10, questions=10).removed_question_slides == [1]
    both = reading("11-12 slaydlarni o'chir", count=10, questions=10)
    assert both.questions == 'remove' and both.delta == 0
    assert reading("10-slaydni o'chir", count=10, questions=10).delta == -1
    # A slide the deck does not have removes nothing.
    assert reading("15-slaydni o'chir", count=10, questions=10).delta == 0


def test_three_slides_with_pictures_are_three_slides_and_three_pictures():
    edit = reading("3 ta rasmli slayd qo'sh")
    assert edit.delta == 3 and edit.pictures == 'add' and edit.picture_count == 3


@pytest.mark.parametrize('text', [
    'a' * 20000, 'a ' * 10000, '1-' * 10000, '1' * 20000, '1' + ' ' * 20000, 'а' * 20000, "'" * 20000,
    '1ta ' * 5000, 'slayd ' * 3400, 'har bir ' * 2500, 'rasm ' * 4000, 'savol 1 ' * 2500, '\n' * 20000,
    ', ' * 10000, 'Ab, ' * 5000 + "obrazlarini qo'sh", 'расм қўш ' * 2200, 'удали последний слайд ' * 900,
    ("Rasmlar bo'lsin, 3-slaydni o'chir, yana 2 ta slayd qo'sh, test tuz. " * 300)[:20000],
    "o'n" + ' ' * 20000, '5-' * 7000, '5, ' * 7000, 'удали ' + '5 и ' * 5000, 'remove slides ' + '5, ' * 6000,
    'qosh ' * 4000, '10 betli ' * 2000, 'slaydlar soni ' * 1500, 'make it ' * 2500, 'keep the ' * 2500,
    'dizaynni ' + 'a ' * 9000, '5 taga ' * 3000, 'savollar ' * 2000 + '5 taga',
])
def test_a_long_request_is_read_in_linear_time(text):
    started = time.perf_counter()
    read(text, fmt='pptx', sections=deck(8), questions=10)
    asks_only_for_format(text)
    assert time.perf_counter() - started < 1.0


# ---------------------------------------------------------------- the draft

DRAFT_DB = pytest.mark.django_db


@pytest.fixture
def customer(settings):
    from tests.test_platform import account
    from tests.test_studio import paid
    settings.DEBUG = True
    return paid(settings, account())


def finished(customer, feature, count, *, questions=0, style=None, pictures=False):
    """A generated document of `count` sections, the way revision_source finds one."""
    from apps.studio.domain import SLIDES, create_draft, pack, unpack
    from apps.studio.models import GenerationDraft
    deckish = feature == SLIDES
    draft = create_draft(customer, {'feature_id': feature, 'prompt': f'{count} ta slayd: suv aylanishi'
                                    if deckish else f'{count} betlik referat: suv aylanishi'})
    data = unpack(draft.encrypted_data)
    data['content']['sections'] = (deck(count, pictures=pictures) if deckish else document(count))
    data['content']['questions'] = [{'id': f'q{n}', 'stem': f'Savol {n}?', 'options': ['A', 'B'], 'answer': 'A',
                                     'explanation': '', 'topic': 'Suv', 'marks': 1} for n in range(1, questions + 1)]
    from apps.studio.pages import question_slides
    from apps.studio.domain import validate_content
    data['content'] = validate_content(customer, data['content'], 'pptx' if deckish else 'pdf')
    data['options'].update(question_slides=question_slides(questions) if deckish else 0,
                           length=count + (question_slides(questions) if deckish else 0))
    if style:
        data['options']['template_style'] = {**data['options'].get('template_style', {}), **style}
    GenerationDraft.objects.filter(pk=draft.pk).update(encrypted_data=pack(data))
    return draft


def change(customer, source, request_text, **options):
    from apps.studio.domain import create_draft, unpack
    draft = create_draft(customer, {'prompt': request_text, 'options': {'revise_draft_id': str(source.id), **options}})
    return unpack(draft.encrypted_data)


@DRAFT_DB
def test_a_change_keeps_what_it_read_and_the_document_as_it_was(customer):
    from apps.studio.domain import DOCUMENT, draft_data, create_draft
    source = finished(customer, DOCUMENT, 4)
    data = change(customer, source, 'Test tuz')
    assert data['revision']['edit']['questions'] == 'add'
    assert [s['heading'] for s in data['revision']['before']['sections']] == ['Part 1', 'Part 2', 'Part 3', 'Part 4']
    # Kept for the job; the API has no use for a second copy of the document.
    draft = create_draft(customer, {'prompt': 'Test tuz', 'options': {'revise_draft_id': str(source.id)}})
    assert 'before' not in draft_data(draft)['revision'] and 'edit' in draft_data(draft)['revision']


@DRAFT_DB
@pytest.mark.parametrize('request_text,length,sections', [
    ("bitta sahifa qo'sh", 9, 9),
    ("yana 2 ta slayd qo'shing", 10, 10),
    ("Reja ham bo'lsin kirish va xulosa qismi ham", 11, 11),
    ("oxirgi slaydni olib tashla", 7, 7),
    ('12 ta slayd qil', 12, 12),
    # A named total wins over pages added.
    ("12 ta slayd bo'lsin, yana 2 ta slayd qo'sh", 12, 12),
    # A total of one is not a total.
    ("Keyin har 1ta slaydga rasm qo'shilsin.", 8, 8),
])
def test_the_count_of_a_change_follows_the_request(customer, request_text, length, sections):
    from apps.studio.domain import SLIDES
    data = change(customer, finished(customer, SLIDES, 8), request_text)
    assert data['options']['length'] == length
    assert len(data['content']['sections']) == sections
    assert len({s['id'] for s in data['content']['sections']}) == sections


@DRAFT_DB
def test_a_title_page_is_a_decks_cover_and_a_documents_first_page(customer):
    """Request #5 on a deck once made it 13 slides: a second title slide after the cover."""
    from apps.studio.domain import DOCUMENT, SLIDES
    request_text = next(row[4] for row in REAL if row[0] == 5)
    deck_change = change(customer, finished(customer, SLIDES, 12), request_text)
    assert deck_change['options']['length'] == 12 and len(deck_change['content']['sections']) == 12
    assert deck_change['options']['requested_pages'] is None, 'nothing was added, so nothing was cut'
    assert deck_change['revision']['edit']['parts'] == ['title_page']
    assert not deck_change['revision']['edit']['structural']
    # Pages added at the start past the title page are slides after the cover.
    more = change(customer, finished(customer, SLIDES, 12), "Boshiga 3 ta sahifa qo'sh, birinchisiga ismimni yoz")
    assert more['options']['length'] == 14 and more['revision']['edit']['structural']
    # A slide added at the start that dictates nothing is a slide: the customer asked for one.
    content = change(customer, finished(customer, SLIDES, 12), "Boshiga bitta slayd qo'sh, unda mavzuning "
                                                              "dolzarbligi haqida yoz")
    assert content['options']['length'] == 13 and content['revision']['edit']['parts'] == []
    # A document's title page is a page of its own.
    document_change = change(customer, finished(customer, DOCUMENT, 6), request_text)
    assert document_change['options']['length'] == 7 and document_change['revision']['edit']['structural']


@DRAFT_DB
def test_a_long_change_is_held_to_the_calls_its_job_sends(customer, monkeypatch):
    """A fifteen-page Russian change was refused at 142 KB, though the two calls it makes were 98 KB and 53 KB."""
    from operations.integrations import save_config
    from apps.core.errors import DomainError
    from apps.studio import domain, provider
    from apps.studio.domain import DOCUMENT, create_draft, generation_quote, pack, unpack
    from apps.studio.models import GenerationDraft
    from apps.studio.pages import batches
    from tests.test_provider_contract import CONFIG
    save_config('ai', {'mode': 'openai', 'model': CONFIG['model'], 'api_key': 'sk-offline-test-only'})
    sentence = 'Древние государства Центральной Азии контролировали торговые пути и развивали ремесленные города.'
    source = finished(customer, DOCUMENT, 15)
    data = unpack(source.encrypted_data)
    for section in data['content']['sections']:
        section['body'] = '\n'.join(' '.join([sentence] * 6) for _ in range(6))
    GenerationDraft.objects.filter(pk=source.pk).update(encrypted_data=pack(data))
    draft = create_draft(customer, {'prompt': 'Сделай подробнее', 'options': {'revise_draft_id': str(source.id)}})
    payload = unpack(draft.encrypted_data)
    whole = provider.body_tokens(provider.request_body(CONFIG, payload, DOCUMENT))
    calls = [provider.body_tokens(provider.request_body(CONFIG, payload, DOCUMENT, span)) for span in batches(15)]
    assert len(calls) == 2 and max(calls) < whole
    domain.enforce_budget(CONFIG, payload, DOCUMENT, max(calls))
    with pytest.raises(DomainError) as refused:
        domain.enforce_budget(CONFIG, payload, DOCUMENT, max(calls) - 1)
    assert refused.value.code == 'generation_limit'
    # The quote holds it to the same calls, on a plan whose budget the whole body is over.
    real = domain.plan_limits
    monkeypatch.setattr(domain, 'plan_limits', lambda account: {**real(account), 'max_ai_input_tokens': max(calls)})
    assert generation_quote(customer, draft.id, draft.version).meters['ai_credits'] > 0
    monkeypatch.setattr(domain, 'plan_limits', lambda account: {**real(account), 'max_ai_input_tokens': max(calls) - 1})
    with pytest.raises(DomainError):
        generation_quote(customer, draft.id, draft.version)
    # A new document is held to its whole body, as it always was.
    monkeypatch.setattr(domain, 'plan_limits', real)
    new = unpack(create_draft(customer, {'feature_id': DOCUMENT, 'prompt': 'Реферат на 15 страниц',
                                         'source_text': '\n\n'.join([' '.join([sentence] * 30)] * 15)}).encrypted_data)
    largest = provider.body_tokens(provider.largest_body(CONFIG, new, DOCUMENT))
    assert largest < provider.body_tokens(provider.request_body(CONFIG, new, DOCUMENT))
    with pytest.raises(DomainError):
        domain.enforce_budget(CONFIG, new, DOCUMENT, largest)


@DRAFT_DB
def test_a_count_chosen_on_the_review_screen_still_wins(customer):
    from apps.studio.domain import SLIDES
    data = change(customer, finished(customer, SLIDES, 8), "yana 2 ta slayd qo'shing", pages=6)
    assert data['options']['length'] == 6 and len(data['content']['sections']) == 6


@DRAFT_DB
def test_pages_added_beyond_the_plan_are_cut_and_said(customer):
    from apps.studio.domain import SLIDES
    from apps.studio.pages import ceiling
    top = ceiling(customer, 'pptx')
    data = change(customer, finished(customer, SLIDES, top - 1), "yana 5 ta slayd qo'shing")
    assert data['options']['length'] == top and data['options']['requested_pages'] == top + 4


@DRAFT_DB
def test_removing_the_test_takes_its_slides_away(customer):
    from apps.studio.domain import SLIDES
    data = change(customer, finished(customer, SLIDES, 9, questions=10), "Vaziyatli masalalarni va testlarni oʻchir.")
    assert data['content']['questions'] == [] and data['options']['question_slides'] == 0
    assert data['options']['length'] == 9 and data['options']['question_count'] == 0


@DRAFT_DB
def test_a_test_asked_for_is_added(customer):
    from apps.studio.domain import DOCUMENT, SLIDES
    document_change = change(customer, finished(customer, DOCUMENT, 6), 'Test tuz')
    assert document_change['options']['question_count'] == 10
    deck_change = change(customer, finished(customer, SLIDES, 8), "10 ta savol qo'sh")
    assert deck_change['options']['question_count'] == 10 and deck_change['options']['question_slides'] == 2
    assert deck_change['options']['length'] == 10 and len(deck_change['content']['sections']) == 8
    plain = change(customer, finished(customer, SLIDES, 8), 'test tuz')
    assert plain['options']['question_count'] == 5 and plain['options']['question_slides'] == 1


@DRAFT_DB
def test_questions_put_on_one_slide_keep_five(customer):
    from apps.studio.domain import SLIDES
    data = change(customer, finished(customer, SLIDES, 10, questions=10),
                  "savol so'rash salydi 2 bet bo'libdi. shuni 1 bet qil , yana bir betiga qanaqador malumot yoz")
    assert len(data['content']['questions']) == 5 and data['options']['question_slides'] == 1
    assert len(data['content']['sections']) == 11 and data['options']['length'] == 12


@DRAFT_DB
def test_pictures_asked_for_get_the_plans_allowance(customer):
    from operations.integrations import save_config
    from apps.core.policy import plan_limits
    from apps.studio.domain import DOCUMENT, SLIDES
    save_config('pixabay', {'pixabay_key': '12345678-0123456789abcdef0123456789abcdef', 'enabled': 'true'})
    allowance = plan_limits(customer)['max_deck_images']
    # A picture on each of the eight slides after the cover.
    every = change(customer, finished(customer, SLIDES, 9), "har bir slaydda matnga mos rasm bo'lsin")
    assert every['options']['images_wanted'] == 8 and every['options']['image_cap'] == allowance
    some = change(customer, finished(customer, SLIDES, 9), "Jinoyatga oid rasmlar ham qoʻsh")
    assert some['options']['images_wanted'] == 3
    document_change = change(customer, finished(customer, DOCUMENT, 5), 'Rasmlar boʻlsin')
    assert document_change['options']['wants_layouts'] and document_change['options']['image_cap'] == allowance
    assert document_change['options']['images_wanted'] == 2
    # A change that does not ask keeps what the document had: here, none.
    plain = change(customer, finished(customer, DOCUMENT, 5), 'Ikkinchi bo‘limni qisqartir')
    assert plain['options']['image_cap'] == 0 and 'images_wanted' not in plain['options']


@DRAFT_DB
def test_pictures_asked_for_are_the_total_with_those_the_document_has(customer, monkeypatch):
    """images_wanted is how many pictures the document has once changed, its cover's aside.

    It was the pictures to add, which the model read as the total: "Yana 2 ta
    rasm qo'shing" on a deck with four told a part to use two, and the model
    took two away.
    """
    from operations.integrations import save_config
    from apps.studio import domain
    from apps.studio.domain import DOCUMENT, SLIDES
    save_config('pixabay', {'pixabay_key': '12345678-0123456789abcdef0123456789abcdef', 'enabled': 'true'})
    # Twelve slides, pictures on s2, s5, s8 and s11: four, and eleven after the cover.
    pictured = finished(customer, SLIDES, 12, pictures=True)
    assert change(customer, pictured, "Yana 2 ta rasm qo'shing")['options']['images_wanted'] == 4 + 2
    assert change(customer, pictured, "Rasmlar qo'sh")['options']['images_wanted'] == 4 + 4
    assert change(customer, pictured, 'Jinoyatga oid rasmlar ham qoʻsh')['options']['images_wanted'] == 4 + 4
    assert change(customer, pictured, "har bir slaydda rasm bo'lsin")['options']['images_wanted'] == 11
    # A document's title page added by the change is no page for a picture.
    titled = change(customer, finished(customer, DOCUMENT, 6),
                    "Boshiga titul varag'ini qo'sh: MUSTAQIL ISH, Tayyorladi: Karimova Nodira. Har bir sahifada rasm "
                    "bo'lsin")
    assert titled['options']['length'] == 7 and titled['options']['images_wanted'] == 6
    # Never more than the plan adds, and a cover photo takes one of those.
    monkeypatch.setattr(domain, '_image_cap', lambda account, fid: 5)
    assert change(customer, pictured, "Rasmlar qo'sh")['options']['images_wanted'] == 5
    covered = finished(customer, SLIDES, 12, pictures=True)
    covered.refresh_from_db()
    data = domain.unpack(covered.encrypted_data)
    data['content']['sections'][0]['image_query'] = 'old library'
    from apps.studio.models import GenerationDraft
    GenerationDraft.objects.filter(pk=covered.pk).update(encrypted_data=domain.pack(data))
    assert change(customer, covered, "Rasmlar qo'sh")['options']['images_wanted'] == 4
    # On a plan that adds none the count is the request's, so the review can say
    # the plan adds none; the model is told of no pictures (image_cap 0).
    monkeypatch.setattr(domain, '_image_cap', lambda account, fid: 0)
    none = change(customer, pictured, "Rasmlar qo'sh")['options']
    assert none['image_cap'] == 0 and none['images_wanted'] == 8
    # A change that asks nothing of pictures asks for no count.
    assert 'images_wanted' not in change(customer, pictured, 'Ikkinchi slaydni qisqartir')['options']


@DRAFT_DB
def test_the_kind_of_picture_is_kept_with_the_draft(customer):
    from apps.studio.domain import SLIDES, create_draft, unpack
    drawn = change(customer, finished(customer, SLIDES, 8, pictures=True),
                   "Rasmlar tabiiyga o'xshash bo'lmasligi kerak kitoblarda beriladigan rasmga o'xshashi kerak")
    assert drawn['options']['photo_style'] == 'illustration'
    new = unpack(create_draft(customer, {'feature_id': SLIDES, 'prompt': "8 ta slayd, rasmlar kitoblardagi "
                                                                         "rasmlardek bo'lsin"}).encrypted_data)
    assert new['options']['photo_style'] == 'illustration'
    plain = unpack(create_draft(customer, {'feature_id': SLIDES, 'prompt': '8 ta slayd'}).encrypted_data)
    assert 'photo_style' not in plain['options']


@DRAFT_DB
def test_a_new_look_drops_the_design_and_keeps_a_named_colour(customer):
    from apps.studio.domain import SLIDES
    source = finished(customer, SLIDES, 8, style={'deck_design': 'gala', 'deck_theme': 'dark'})
    kept = change(customer, source, 'Ikkinchi slaydni qisqartir')['options']['template_style']
    assert kept['deck_design'] == 'gala' and kept['deck_theme'] == 'dark'
    redone = change(customer, source, 'Varoqlarni hammasini bir hil qil')['options']['template_style']
    assert 'deck_design' not in redone and 'deck_theme' not in redone
    coloured = change(customer, source, "boshqa dizayn, yashil rangda")['options']['template_style']
    assert 'deck_design' not in coloured and coloured['accent_fixed']


@DRAFT_DB
def test_a_change_to_selected_pages_reads_nothing_new(customer):
    from apps.studio.domain import SLIDES
    source = finished(customer, SLIDES, 8)
    data = change(customer, source, "reja ham bo'lsin, rasmlar bo'lsin, test tuz, boshqa dizayn",
                  revise_section_ids=['s2'], revise_base_version=source.version)
    assert data['options']['length'] == 8 and len(data['content']['sections']) == 8
    assert 'edit' not in data['revision'] and 'before' not in data['revision']
    assert 'images_wanted' not in data['options'] and data['options']['question_count'] == 0


@DRAFT_DB
@pytest.mark.parametrize('request_text,length', [
    # Each of these once cut the deck to its number.
    ('fix typos on slide 2 and slide 6', 10), ('3-slayddagi va 7-slayddagi xatolarni tuzat', 10),
    ('shorten the first 3 slides', 10), ('oxirgi 3 ta slaydni kengaytir', 10), ('первые 3 слайда сократи', 10),
    ("12 slaydli taqdimotimga rasm qo'sh", 10), ('2 ta slayd qoshing', 12), ("5-7 slaydlarni o'chir", 7),
    ('удали 5 и 6 слайды', 8), ("10 ta slayddan iborat taqdimotga 2 ta slayd qo'sh", 12),
    ("3 ta rasmli slayd qo'sh", 13), ('Slaydlarni 8 taga kamaytir', 8), ('12talik qil', 12),
])
def test_the_length_of_a_change_is_only_what_it_says(customer, request_text, length):
    from apps.studio.domain import SLIDES
    data = change(customer, finished(customer, SLIDES, 10), request_text)
    assert data['options']['length'] == length and len(data['content']['sections']) == length
    assert data['options']['requested_pages'] in (None, length)


@DRAFT_DB
def test_what_came_and_what_was_wanted(customer):
    from apps.studio.domain import SLIDES
    data = change(customer, finished(customer, SLIDES, 8), '8 ta slayd keldi, 10 ta kerak edi')
    assert data['options']['length'] == 10


@DRAFT_DB
def test_questions_asked_onto_fewer_slides_keep_the_deck(customer):
    from apps.studio.domain import SLIDES
    data = change(customer, finished(customer, SLIDES, 10, questions=10), "savollar 2 slaydda bo'lsin")
    assert len(data['content']['sections']) == 10 and data['options']['question_slides'] == 2
    assert len(data['content']['questions']) == 10 and data['options']['length'] == 12


@DRAFT_DB
def test_a_selected_change_that_points_at_slides_is_not_refused(customer):
    from apps.core.errors import DomainError
    from apps.studio.domain import SLIDES
    source = finished(customer, SLIDES, 10)
    data = change(customer, source, 'fix typos on slide 2 and slide 6', revise_section_ids=['s2', 's6'],
                  revise_base_version=source.version)
    assert data['options']['length'] == 10
    # One that names a new size still is: a selection cannot resize.
    with pytest.raises(DomainError):
        change(customer, source, 'make it 5 slides', revise_section_ids=['s2'], revise_base_version=source.version)


@DRAFT_DB
def test_pictures_not_wanted_are_not_added(customer):
    from operations.integrations import save_config
    from apps.studio.domain import DOCUMENT, SLIDES
    save_config('pixabay', {'pixabay_key': '12345678-0123456789abcdef0123456789abcdef', 'enabled': 'true'})
    for request_text in ('rasmsiz qil', 'rasmlar shart emas', 'картинки не нужны'):
        data = change(customer, finished(customer, SLIDES, 8, pictures=True), request_text)
        assert data['revision']['edit']['pictures'] == 'remove' and 'images_wanted' not in data['options']
    document_change = change(customer, finished(customer, DOCUMENT, 5), 'rasmsiz qil')
    assert not document_change['options']['wants_layouts'] and 'images_wanted' not in document_change['options']
    assert document_change['options']['image_cap'] == 0


@DRAFT_DB
def test_a_design_asked_to_stay_stays(customer):
    from apps.studio.domain import SLIDES
    source = finished(customer, SLIDES, 8, style={'deck_design': 'gala', 'deck_theme': 'dark'})
    for request_text in ("dizaynni o'zgartirma, faqat xatolarni tuzat", 'keep the same design, add 2 slides',
                         "fonni o'zgartirmang", 'не меняй дизайн'):
        style = change(customer, source, request_text)['options']['template_style']
        assert style['deck_design'] == 'gala' and style['deck_theme'] == 'dark', request_text


@DRAFT_DB
def test_a_document_keeps_its_design_unless_a_new_look_is_asked_for(customer):
    from apps.studio.domain import DOCUMENT
    source = finished(customer, DOCUMENT, 5, style={'doc_design': 'elegant'})
    # A colour named is the accent on the design the document has, not a design to choose again.
    for request_text in ("dizaynni o'zgartirma, faqat xatolarni tuzat", 'Ikkinchi bo‘limni qisqartir',
                         'Rasmiy uslubda yoz', 'Test tuz', 'yashil rangda qil'):
        options = change(customer, source, request_text)['options']
        assert options['template_style']['doc_design'] == 'elegant' and not options['wants_design'], request_text
    options = change(customer, source, 'boshqa dizayn qil')['options']
    assert 'doc_design' not in options['template_style'] and options['wants_design']


@DRAFT_DB
def test_a_test_added_at_the_plans_limit_says_what_it_cut(customer):
    from apps.studio.domain import SLIDES
    from apps.studio.pages import ceiling
    top = ceiling(customer, 'pptx')
    data = change(customer, finished(customer, SLIDES, top), 'Test tuz')
    assert data['options']['length'] == top and data['options']['question_slides'] == 1
    # The slide the test pushed out is shown as cut, so the review says so and offers more.
    assert data['options']['requested_pages'] == top + 1


@DRAFT_DB
@pytest.mark.parametrize('request_text,questions,slides', [
    ("savollar 5 ta bo'lsin", 5, 1), ('savollarni 5 taga qisqartir', 5, 1), ('leave only 5 questions', 5, 1),
    ('оставь 5 вопросов', 5, 1),
])
def test_fewer_questions_asked_for_cut_the_test(customer, request_text, questions, slides):
    from apps.studio.domain import SLIDES
    data = change(customer, finished(customer, SLIDES, 8, questions=10), request_text)
    assert len(data['content']['questions']) == questions and data['options']['question_count'] == questions
    assert data['options']['question_slides'] == slides and data['options']['length'] == 8 + slides


@DRAFT_DB
def test_questions_added_are_added_to_those_there(customer):
    from apps.studio.domain import SLIDES
    data = change(customer, finished(customer, SLIDES, 8, questions=10), "10 ta savol qo'sh")
    assert data['options']['question_count'] == 20 and data['options']['question_slides'] == 4
    assert len(data['content']['questions']) == 10 and data['options']['length'] == 12


@DRAFT_DB
def test_a_question_slide_removed_by_its_number_takes_its_questions(customer):
    from apps.studio.domain import SLIDES
    source = finished(customer, SLIDES, 10, questions=10)
    data = change(customer, source, "12-slaydni o'chir")
    assert len(data['content']['sections']) == 10 and data['options']['question_slides'] == 1
    assert [q['id'] for q in data['content']['questions']] == ['q1', 'q2', 'q3', 'q4', 'q5']
    assert data['options']['length'] == 11
    first = change(customer, source, "11-slaydni o'chir")
    assert [q['id'] for q in first['content']['questions']] == ['q6', 'q7', 'q8', 'q9', 'q10']


@DRAFT_DB
def test_a_reworded_change_starts_again_from_the_document(customer):
    from apps.studio.domain import SLIDES, create_draft, unpack, update_draft
    source = finished(customer, SLIDES, 8, style={'deck_design': 'gala', 'deck_theme': 'dark'})
    draft = create_draft(customer, {'prompt': 'boshqa dizayn', 'options': {'revise_draft_id': str(source.id)}})
    assert 'deck_design' not in unpack(draft.encrypted_data)['options']['template_style']
    draft = update_draft(customer, draft.id, {'version': draft.version, 'prompt': 'Ikkinchi slaydni qisqartir'})
    style = unpack(draft.encrypted_data)['options']['template_style']
    assert style['deck_design'] == 'gala' and style['deck_theme'] == 'dark'
    # The test the first wording took away is back with the second, and so is its slides' price.
    tested = finished(customer, SLIDES, 8, questions=10)
    draft = create_draft(customer, {'prompt': "testlarni o'chir", 'options': {'revise_draft_id': str(tested.id)}})
    assert unpack(draft.encrypted_data)['options']['question_slides'] == 0
    draft = update_draft(customer, draft.id, {'version': draft.version, 'prompt': "Rasmlar bo'lsin"})
    data = unpack(draft.encrypted_data)
    assert len(data['content']['questions']) == 10 and data['options']['question_slides'] == 2
    assert data['options']['length'] == 10


@DRAFT_DB
def test_a_colour_named_in_a_document_change_is_its_colour(customer):
    from apps.studio.domain import DOCUMENT
    red = finished(customer, DOCUMENT, 5, style={'accent': '#AA0000', 'accent_fixed': True})
    style = change(customer, red, "ko'k rangda qil")['options']['template_style']
    assert style['accent'] == '#1F4E9C' and style['accent_fixed']
    style = change(customer, finished(customer, DOCUMENT, 5), 'yashil rangda qil')['options']['template_style']
    assert style['accent'] == '#1E6B45' and style['accent_fixed']
    # One that names none keeps the document's.
    assert change(customer, red, 'Ikkinchi bo‘limni qisqartir')['options']['template_style']['accent'] == '#AA0000'


@DRAFT_DB
@pytest.mark.parametrize('feature,request_text', [
    ('ai.pptx', 'Bu ilovada ochilmayapti pdf shaklida yubor'), ('ai.pptx', 'send it as a pdf'),
    ('ai.pdf_topic', 'slayd qilib ber'), ('ai.pdf_topic', 'pptx formatida kerak'),
])
def test_a_change_asking_only_for_another_file_format_is_refused(customer, feature, request_text):
    from apps.core.errors import DomainError
    with pytest.raises(DomainError) as refused:
        change(customer, finished(customer, feature, 5), request_text)
    assert refused.value.code == 'format_only_change'


@DRAFT_DB
def test_a_format_named_beside_a_change_keeps_the_change(customer):
    from apps.studio.domain import SLIDES
    data = change(customer, finished(customer, SLIDES, 8), 'pdf qilib ber va 3-slaydni qisqartir')
    assert data['revision']['edit']['format'] == 'pdf' and data['options']['length'] == 8


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_the_refusal_is_said_in_every_language(locale):
    import json
    from pathlib import Path
    messages = json.loads((Path(__file__).resolve().parents[1] / 'i18n' / f'{locale}.json').read_text())
    assert 'PowerPoint → PDF' in messages['format_only_change']


# ---------------------------------------------------------------- the photos


def test_drawings_are_searched_as_illustrations_and_cached_apart(monkeypatch):
    import io
    import json
    from urllib.parse import parse_qs, urlsplit
    from apps.studio import photos
    asked = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    def network(request, timeout, handler):
        query = parse_qs(urlsplit(request.full_url).query)
        asked.append(query['image_type'][0])
        hits = [{'id': n, 'type': kind, 'imageWidth': 1920, 'imageHeight': 1280, 'tags': 'water cycle',
                 'pageURL': f'https://pixabay.com/x-{n}/', 'largeImageURL': f'https://pixabay.com/get/{n}.jpg'}
                for n, kind in ((1, 'photo'), (2, 'illustration'))]
        return Response(json.dumps({'totalHits': 2, 'hits': hits}).encode())

    monkeypatch.setattr(photos, '_open', network)
    assert [hit['id'] for hit in photos.search('water cycle', 'k')] == [1]
    assert [hit['id'] for hit in photos.search('water cycle', 'k', image_type='illustration')] == [2]
    assert asked == ['photo', 'illustration']
    assert [hit['id'] for hit in photos.search('water cycle', 'k', image_type='vector')] == [1], 'only the two kinds'
    # Photos keep the key they always had, so a warm cache stays warm.
    import hashlib
    assert photos._cache_key('water cycle') == hashlib.sha256(b'v2|water cycle').hexdigest()
    assert photos._cache_key('water cycle', 'illustration') != photos._cache_key('water cycle')
