"""Never invent, in code: facts by kind, numbers as values, grounded and guarded parts, references.

Architecture section 4, row by row. Every person and organisation here is
invented; the messages are written for these tests, never a customer's.
"""
import re
import time
from pathlib import Path

import pytest

from apps.studio import categories
from apps.studio.categories import facts, numbers
from apps.studio.categories.facts import derived, ground, guard, supported, trusting, verify_items

ARIZA_UZ = ('Namuna davlat universiteti iqtisodiyot fakulteti dekaniga ariza yozing. Men Dilnoza Karimova, 2-kurs, '
            '205-guruh talabasiman. 2026-yil 3-noyabrdan 12-noyabrgacha kasallik tufayli qoldirgan darslarimni '
            'uzrli deb hisoblashingizni so‘rayman. Ilova: shifokor ma’lumotnomasi. Telefon: +998 90 123 45 67. '
            'E-pochta: dilnoza.k@example.com')
ARIZA_RU = ('Напишите заявление декану экономического факультета Образцового государственного университета. '
            'Я Дилноза Каримова, студентка 2 курса, группа 205. Прошу считать уважительными пропуски занятий '
            'с 3 по 12 ноября 2026 года из-за болезни. Приложение: справка от врача. Телефон: +998 90 123 45 67.')
ARIZA_EN = ('Write a request to the dean of the Faculty of Economics at Example State University. I am Dilnoza '
            'Karimova, a 2nd-year student, group 205. I ask you to treat my absence from classes from 3 to 12 '
            'November 2026 as excused because of illness. Phone: +998 90 123 45 67.')
CODES = {'ground:number', 'ground:name', 'ground:quote', 'ground:law', 'source:dropped'}


def draft(prompt='', **more):
    return {'prompt': prompt, 'options': {'category': 'pdf.xat.ariza'}, **more}


@pytest.fixture
def uz():
    return facts.trusted(draft(ARIZA_UZ))


# ---------------------------------------------------------------- names, by kind


def test_a_name_is_found_with_its_case_endings_in_both_alphabets(uz):
    for value in ('Dilnoza Karimova', 'Karimovaning', 'Karimovaga', 'Dilnozadan', 'Karimova D.', 'Каримовой',
                  'Каримову', 'Дилнозе', 'Dilnoza Karimova’s'):
        assert supported(value, 'person', uz), value
    known = trusting('Ali Valiyev va Анна Тестова keldi.')
    for value in ('Aliga', 'Alining', 'Анне', 'Анну', 'Тестовой'):
        assert supported(value, 'person', known), value


def test_the_spellings_of_one_name_across_the_alphabets_meet():
    known = trusting('Хамроева Нилуфар, Қодирова С., Джасур Юсупов, Фёдор Цой, Мария, Тошпулатова Мадина, Навоий')
    for value in ('Hamroyeva Nilufar', 'Khamroyeva', 'Xamroyeva', 'Qodirova', 'Kodirova', 'Jasur Yusupov',
                  'Djasur', 'Fyodor', 'Fedor', 'Tsoy', 'Mariya', 'Maria', 'Toshpo‘latova Madina', "Toshpo'latova",
                  'Navoiy', 'Navoi'):
        assert supported(value, 'person', known), value


def test_an_invented_name_is_not_found(uz):
    for value in ('Xolmirzayev', 'Dilnoza Xolmirzayeva', 'Karimjonova', 'Bahor Foods'):
        assert not supported(value, 'person', uz), value
    # A single initial is skipped: the check cannot tell whose it is, and an initial alone names no one.
    assert supported('X. Karimova', 'person', uz)


def test_people_organisations_places_and_lines_check_every_capitalised_word_and_number(uz):
    assert supported('Namuna davlat universitetiga', 'org', uz)
    assert not supported('Boshqa davlat universiteti', 'org', uz)
    assert supported('iqtisodiyot fakulteti 2-kurs, 205-guruh talabasi', 'line', uz)
    assert not supported('iqtisodiyot fakulteti 2-kurs, 206-guruh talabasi', 'line', uz)
    assert supported('Hurmatli dekan', 'line', uz), 'a formula of address is no one’s fact'


def test_a_document_in_another_language_checks_names_of_a_person_only():
    known = trusting(ARIZA_RU)
    assert supported('Dilnoza Karimova', 'person', known, translated=True)
    assert not supported('Botir Xolmirzayev', 'person', known, translated=True)
    # The organisation is translated, so its words are not the customer's; its numbers still are checked.
    assert supported('Namuna davlat universiteti', 'org', known, translated=True)
    assert not supported('Namuna davlat universiteti', 'org', known)
    assert not supported('7-sonli maktab', 'org', known, translated=True)


# ---------------------------------------------------------------- numbers, by kind


def test_dates_numbers_money_refs_and_phones_are_found_as_values(uz):
    for value, kind in (('03.11.2026', 'date'), ('3-noyabr 2026', 'date'), ('12 ноября 2026 года', 'date'),
                        ('November 3, 2026', 'date'), ('205', 'number'), ('+998901234567', 'phone'),
                        ('90 123 45 67', 'phone'), ('(90) 123-45-67', 'phone')):
        assert supported(value, kind, uz), value
    for value, kind in (('04.11.2026', 'date'), ('3-dekabr', 'date'), ('03.11.2025', 'date'), ('206', 'number'),
                        ('+998 90 123 45 68', 'phone'), ('1 150 000 so‘m', 'money')):
        assert not supported(value, kind, uz), value
    priced = trusting('Narxi 1150000 so‘m, chegirma 1,5 mln so‘m, 20 ming nusxa, shartnoma 125-son, 12,5% foyda')
    for value, kind in (('1 150 000 so‘m', 'money'), ('1.150.000', 'money'), ('1,150,000 UZS', 'money'),
                        ('1 500 000', 'money'), ('1.5 million', 'money'), ('20 000', 'number'),
                        ('№ 125', 'ref'), ('12.5 %', 'number')):
        assert supported(value, kind, priced), value
    for value, kind in (('1 150 001', 'money'), ('15 000', 'money'), ('2 000', 'number'), ('№ 126', 'ref')):
        assert not supported(value, kind, priced), value


def test_an_email_is_found_whole(uz):
    assert supported('dilnoza.k@example.com', 'email', uz)
    assert supported('Dilnoza.K@example.com', 'email', uz)
    for value in ('dilnoza.k@example.co', 'xdilnoza.k@example.com', 'dilnoza@example.com'):
        assert not supported(value, 'email', uz), value
    assert supported('Dilnoza Karimova, dilnoza.k@example.com', 'line', uz)
    assert not supported('Dilnoza Karimova, d.karimova@example.com', 'line', uz)


def test_text_checks_its_numbers_only(uz):
    assert supported('Xolmirzayev bilan 12 kun', 'text', uz)
    assert not supported('Xolmirzayev bilan 14 kun', 'text', uz)


def test_choices_flags_files_and_blanks_are_not_checked_here(uz):
    for value, kind in (('self_study', 'choice'), (True, 'flag'), ('anything', 'file'), ('____', 'person'),
                        ('', 'date'), (None, 'org')):
        assert supported(value, kind, uz)


def test_a_list_is_held_line_by_line(uz):
    assert supported('shifokor ma’lumotnomasi\nDilnoza Karimova', 'list', uz)
    assert supported('shifokor ma’lumotnomasi; 205-guruh', 'list', uz)
    assert not supported('shifokor ma’lumotnomasi\nXolmirzayev ma’lumotnomasi', 'list', uz)


def test_a_derived_value_takes_only_the_words_and_initials_of_its_base():
    base = 'Karimova Dilnoza Rustam qizi'
    for value in ('D. R. Karimova', 'Karimova D.R.', 'Dilnoza Karimova', 'Karimova D. R. qizi'):
        assert derived(value, base), value
    for value in ('D. Xolmirzayeva', 'A. Karimova', 'Dilnoza Karimova Botirovna'):
        assert not derived(value, base), value
    assert derived('Sh. Ergasheva', 'Ergasheva Shahnoza')
    assert derived('Ю. Жасур', 'Yusupov Jasur')


# ---------------------------------------------------------------- numbers.py


@pytest.mark.parametrize('written, given', [
    ('1 150 000', '1150000'), ('1.150.000', '1 150 000'), ('1,150,000', '1.150.000'),
    ('1\u00a0150\u00a0000', '1150000'),
    ('1,5', '1.5'), ('1.5', '1,5'), ('1,5 mln', '1 500 000'), ('1 500 000', '1,5 млн'), ('20 ming', '20 000'),
    ('20 000', '20 тыс.'), ('2,5 billion', '2 500 000 000'), ('15', '15%'), ('15 %', '15 foiz'), ('205', '205-guruh'),
    ('3-noyabr', '03.11.2026'), ('03.11', '3 ноября'), ('3 November', '3-noyabrdan'), ('November 3', '3 ноября'),
    ('2026', '2026-yil'), ('90 123 45 67', '+998 90 123 45 67'), ('+998901234567', '90-123-45-67'),
    ('12 ноября', 'с 3 по 12 ноября'), ('5 January', 'from 5 to 18 January 2027'), ('2', 'Две недели'),
    ('4', 'четырёхнедельная практика'), ('3', 'uchta savol'), ('2', 'two in surgery'),
])
def test_a_number_is_one_value_however_it_is_written(written, given):
    found = numbers.found(written)
    assert found, written
    assert all(numbers.known(number, numbers.values(given)) for number in found), (written, given)


@pytest.mark.parametrize('written, given', [
    ('1 150 001', '1 150 000'), ('1 500 000', '1,5'), ('20 000', '20'), ('4-noyabr', '03.11.2026'),
    ('3-dekabr', '3-noyabr'), ('90 123 45 68', '+998 90 123 45 67'), ('2027', '2026-yil'), ('3', 'uchun'),
    ('15 000', '15 ta'),
])
def test_a_different_number_is_never_taken_for_one_given(written, given):
    assert not all(numbers.known(number, numbers.values(given)) for number in numbers.found(written)), (written, given)


def test_a_date_is_read_in_every_language_and_alphabet():
    for text in ('3-noyabr', '3 noyabrda', '3-ноябр', '3 ноября', '3 November', 'November 3', '3rd of November',
                 'Nov. 3', '03.11.2026', '2026-11-03', '3/11/2026'):
        assert 'd:3.11' in numbers.values(text), text


def test_words_that_only_look_like_months_or_numbers_are_not_dates():
    assert numbers.values('40 marta') == {'40'}
    assert numbers.values('3 marta') == {'3'}
    assert 'd:5.3' not in numbers.values('5 marketing kanali')
    assert numbers.values('dilnoza2026@example.com va www.example.uz/2025') == set()
    assert '3' not in numbers.values('uchun') and '2' not in numbers.values('один')


@pytest.mark.parametrize('text, read', [
    ('five years of experience', [('5', 'five')]),
    ('a team of twelve people and two hundred clients', [('12', 'twelve'), ('200', 'two hundred')]),
    ('two hundred and fifty thousand dollars', [('250000', 'two hundred and fifty thousand')]),
    ('twenty-one days, a dozen eggs, a hundred per cent', [('21', 'twenty-one'), ('12', 'a dozen'),
                                                           ('100', 'a hundred')]),
    ('revenue grew by a third, then by two thirds of it', [('f:1/3', 'a third'), ('f:2/3', 'two thirds')]),
    ('besh yuz million so‘m', [('500000000', 'besh yuz million')]),
    ('yillik yigirma foiz, o‘n bir kun, yuz nafar', [('20', 'yigirma'), ('11', 'o‘n bir'), ('100', 'yuz')]),
    ('bir yarim million so‘m, uchdan bir qismi', [('1500000', 'bir yarim million'), ('f:1/3', 'uchdan bir')]),
    ('besh-olti kun', [('5', 'besh'), ('6', 'olti')]),
    ('besh yuzta stul va yuzta stol', [('500', 'besh yuzta'), ('100', 'yuzta')]),
    ('беш юз минг сўм', [('500000', 'беш юз минг')]),
    ('более пяти лет, две тысячи пятьсот рублей', [('5', 'пяти'), ('2500', 'две тысячи пятьсот')]),
    ('тысяча рублей, два миллиона, треть клиентов', [('1000', 'тысяча'), ('2000000', 'два миллиона'),
                                                    ('f:1/3', 'треть')]),
], ids=['five', 'twelve', 'compound', 'article', 'fraction', 'uz-scale', 'uz-counts', 'uz-half', 'uz-range',
        'uz-yuzta', 'uz-cyrillic', 'ru-counts', 'ru-alone'])
def test_cardinal_numbers_written_as_words_are_read_with_their_scales(text, read):
    assert [(number.value, text[number.start:number.end]) for number in numbers.found(text, words=True)] == read
    assert not [number for number in numbers.found(text) if number.kind in ('spelled', 'fraction')]


@pytest.mark.parametrize('text', [
    'one of the best', 'the second stage', 'once a quarter', 'thousands of clients', 'often', 'ikkinchi bob',
    'muammo yuz berdi', 'ming yillik tarix', 'ikkala guruh', 'свою семью', 'третью неделю', 'a third party',
    'a third-party vendor', 'a third option',
])
def test_words_that_are_not_counts_are_not_read_as_numbers(text):
    assert [text[number.start:number.end] for number in numbers.found(text, words=True)] == []


def test_a_number_in_words_is_known_however_the_customer_wrote_it():
    given = numbers.values('Loyiha qiymati 500 mln so‘m, 5 yillik tajriba, yigirma besh nafar xodim, 33 foiz')
    for written in ('besh yuz million so‘m', 'five years', '25 people', 'двадцать пять сотрудников'):
        assert all(numbers.known(number, given) for number in numbers.found(written, words=True)), written
    assert not all(numbers.known(number, given) for number in numbers.found('a third', words=True))
    assert not all(numbers.known(number, given) for number in numbers.found('six years', words=True))


def test_a_phone_is_its_digits_and_its_last_nine():
    keys = numbers.values('Tel: +998 (90) 123-45-67')
    assert {'998901234567', 'tel:901234567'} <= keys
    assert [number.kind for number in numbers.found('1 150 000 so‘m')] == ['integer']


# ---------------------------------------------------------------- ground


def test_a_faithful_part_is_left_as_it_is():
    cases = (
        (ARIZA_UZ, 'Sizdan 2026-yil 3-noyabrdan 12-noyabrgacha kasalligim sababli qoldirgan darslarimni uzrli deb '
                   'hisoblashingizni so‘rayman. Men, Dilnoza Karimova, Namuna davlat universitetining 205-guruh '
                   'talabasiman.'),
        (ARIZA_RU, 'Прошу Вас считать уважительными пропуски занятий с 3 по 12 ноября 2026 года в связи с болезнью. '
                   'Студентка 2 курса группы 205 Дилноза Каримова.'),
        (ARIZA_EN, 'Dear Dean, I kindly ask you to treat my absence from 3 to 12 November 2026 as excused. '
                   'I am Dilnoza Karimova, a student of group 205 of the Faculty of Economics.'),
    )
    for message, part in cases:
        assert ground(part, facts.trusted(draft(message))) == (part, []), part


def test_an_invented_name_sum_quotation_and_decree_are_caught(uz):
    written, codes = ground('Bu ishga Xolmirzayev Botirjon rahbarlik qildi.', uz)
    assert written == 'Bu ishga ____ rahbarlik qildi.' and codes == ['ground:name']
    written, codes = ground('Loyihaga 4 870 000 so‘m sarflandi.', uz)
    assert written == 'Loyihaga ____ so‘m sarflandi.' and codes == ['ground:number']
    written, codes = ground('Muallif aytganidek, «bilim olish har bir insonning burchidir».', uz)
    assert written == 'Muallif aytganidek, ____.' and codes == ['ground:quote']
    written, codes = ground('Darslarim uzrli. Bu Vazirlar Mahkamasining 593-son qarori bilan belgilangan. Rahmat.', uz)
    assert written == 'Darslarim uzrli. Rahmat.' and codes == ['ground:law']


def test_a_quotation_of_the_customers_own_words_stays():
    known = trusting('Mavzu: “Kichik korxonada xodimlar almashinuvini kamaytirish yo‘llari”.')
    part = 'Ishning mavzusi «kichik korxonada xodimlar almashinuvini kamaytirish yo‘llari» deb belgilangan.'
    assert ground(part, known) == (part, [])
    # Fewer than three words is a name in quotation marks, not a quotation: its words are checked as names.
    assert ground('Biz «Namuna» MChJ bilan ishlaymiz.', known) == ('Biz «____» MChJ bilan ishlaymiz.', ['ground:name'])


def test_the_first_word_of_a_sentence_a_line_a_list_item_or_after_a_colon_is_not_a_name(uz):
    part = ('Bugun ariza yozaman. Iltimos, ko‘rib chiqing!\nTushuntirish: Kasallik sababli.\n- Ma’lumotnoma\n'
            '1) Nusxa\n2. Pasport')
    assert ground(part, uz) == (part, [])
    # After an initial or an abbreviation the next word is a name, not a sentence start.
    assert ground('Ishni prof. Xolmirzayev tekshirdi.', uz) == ('Ishni prof. ____ tekshirdi.', ['ground:name'])
    assert ground('Rahbar: B. Xolmirzayev.', uz)[0] == 'Rahbar: B. ____.'
    # The first word of a sentence is capitalised by grammar and stays; the rest of the run is checked.
    assert ground('Bobur Xolmirzayev ham keldi.', uz)[0] == 'Bobur ____ ham keldi.'
    assert ground('Shuningdek Xolmirzayev Botir ham keldi.', uz)[0] == 'Shuningdek ____ ham keldi.'


def test_words_no_ones_facts_are_in_are_never_taken_for_names(uz):
    part = ('Hurmatli Dekan! Ushbu ARIZA 3-noyabr, Dushanba kuni yozildi. Men Sizdan o‘zbek tilida javob '
            'so‘rayman. Ilova: shifokor ma’lumotnomasi. Hurmat bilan, Dilnoza Karimova.')
    assert ground(part, uz) == (part, [])
    known = facts.trusted({'prompt': ARIZA_RU, 'options': {'category': 'pdf.xat.ariza'}})
    assert ground('Прошу Вас рассмотреть моё ЗАЯВЛЕНИЕ. С уважением, Дилноза Каримова.', known)[1] == []


def test_list_numbers_are_not_facts(uz):
    part = '1. Shifokor ma’lumotnomasi\n2. Pasport nusxasi\n3) Talaba guvohnomasi'
    assert ground(part, uz) == (part, [])
    assert ground('Ilova 7 varaqda.', uz) == ('Ilova ____ varaqda.', ['ground:number'])


def test_an_address_not_the_customers_is_blanked(uz):
    assert ground('Javobni dilnoza.k@example.com ga yuboring.', uz)[1] == []
    assert ground('Javobni info@namuna.uz ga yuboring.', uz) == ('Javobni ____ ga yuboring.', ['ground:number'])


def test_a_translated_part_keeps_the_customers_people_and_never_an_invented_one():
    known = trusting(ARIZA_RU)
    part = 'Men talaba Dilnoza Karimova 2026-yil 3-noyabrdan dars qoldirdim.'
    assert ground(part, known, translated=True) == (part, [])
    assert ground('Men 4-noyabrdan dars qoldirdim.', known, translated=True)[1] == ['ground:number']
    # A person the customer never named is blanked in a translated part as in any other.
    assert ground('Men talaba Dilnoza Karimova, rahbarim Botir Xolmirzayev.', known, translated=True) == \
        ('Men talaba Dilnoza Karimova, rahbarim ____.', ['ground:name'])
    # A translated organisation cannot be told from an invented person, so it may be blanked too: a false blank,
    # never an invention ("Образцового государственного университета" is no spelling of Namuna).
    assert ground('Men Namuna davlat universiteti talabasiman.', known, translated=True) == \
        ('Men ____ davlat universiteti talabasiman.', ['ground:name'])


def test_a_translated_part_meets_the_customers_people_across_the_alphabets():
    latin = facts.trusted(draft('Ariza yozing. Men G‘ofurov Sardor, rahbarim Xo‘jayev Botir, Yo‘ldosheva Lola.'))
    part = 'Доклад подготовил Гафуров Сардор под руководством Ходжаев Ботир, рецензент Юлдашева Лола.'
    assert ground(part, latin, translated=True) == (part, [])
    assert ground('Доклад подготовил Гафуров Сардор, рецензент Мадаминов Шерзод.', latin, translated=True) == \
        ('Доклад подготовил Гафуров Сардор, рецензент ____.', ['ground:name'])
    cyrillic = trusting(ARIZA_RU)
    for part in ('Arizachi Dilnoza Karimova.', 'The applicant is Dilnoza Karimova.'):
        assert ground(part, cyrillic, translated=True) == (part, []), part
    assert ground('The applicant is Dilnoza Rahimova.', cyrillic, translated=True)[1] == ['ground:name']


def test_blanks_next_to_each_other_are_one(uz):
    assert ground('Bunga Xolmirzayev 4 870 000 so‘m berdi.', uz)[0] == 'Bunga ____ so‘m berdi.'


# ---------------------------------------------------------------- laws and guard


def test_a_legal_sentence_the_customer_gave_stays_in_any_language():
    known = trusting('Mehnat kodeksining 214-moddasi asosida 21 kunlik ta’til so‘rayman.')
    part = 'Mehnat kodeksining 214-moddasiga muvofiq menga 21 kunlik ta’til berishingizni so‘rayman.'
    assert ground(part, known) == (part, [])
    assert ground('Mehnat kodeksining 215-moddasiga muvofiq ta’til so‘rayman.', known)[1] == ['ground:law']
    russian = trusting('Прошу отпуск на 21 день по статье 214 Трудового кодекса.')
    assert ground(part, russian, translated=True) == (part, [])


def test_a_word_that_is_a_law_only_sometimes_needs_a_mark_of_one():
    known = trusting('Fizika fanidan mustaqil ish.')
    for part in ('Nyutonning ikkinchi qonuni kuch va tezlanishni bog‘laydi.', 'Rahbar tezda qaror qabul qildi.',
                 'Kimyoviy moddalar ehtiyotkorlik bilan saqlanadi.', 'In his article the author compares two schools.',
                 'Закон Ома связывает ток и напряжение.', 'The code of the program is short.'):
        assert guard(part, known) == (part, []), part
    for part in ('Bu O‘zbekiston Respublikasining qonuni bilan belgilangan.',
                 'Ta’lim to‘g‘risidagi Qonun shuni talab qiladi.',
                 'Согласно статье 15 это запрещено.', 'Under the Education Act schools must report.',
                 'Prezidentning farmoni bilan tasdiqlangan.'):
        assert guard(part, known)[1] == ['ground:law'], part


def test_guard_checks_quotations_and_laws_and_leaves_general_knowledge():
    known = trusting('Amir Temur haqida mustaqil ish kerak.')
    part = 'Amir Temur 1336-yilda Keshda tug‘ilgan. U Samarqandni poytaxt qildi.'
    assert guard(part, known) == (part, [])
    assert ground(part, known)[1] == ['ground:number', 'ground:name']
    written, codes = guard('Temur «kuch adolatdadir» degan. Bu Farmon 5-moddada yozilgan. U buyuk edi.', known)
    assert written == 'Temur «kuch adolatdadir» degan. U buyuk edi.' and codes == ['ground:law']
    written, codes = guard('U shunday degan: “kuch adolatdadir va adolat kuchdadir”.', known)
    assert written == 'U shunday degan: ____.' and codes == ['ground:quote']


# ---------------------------------------------------------------- references


def test_a_reference_is_kept_only_when_the_customer_gave_it_and_never_as_a_file_name():
    known = trusting('Manbalar: Karimov A. “Iqtisodiyot nazariyasi”, 2019; Sharipova N. Menejment asoslari.\n'
                     'Jahon iqtisodiyoti va diplomatiya universiteti nashri.')
    items = [
        {'label': '1', 'text': 'Karimov A. Iqtisodiyot nazariyasi, 2019.'},
        {'label': '2', 'text': 'Sharipova N. Menejment asoslari.'},
        {'label': '3', 'text': 'Xolmirzayev B. Marketing, 2021.'},
        {'label': '4', 'text': 'kurs_ishi_final.docx'},
        {'label': '5', 'text': 'kurs ishi final'},
        {'label': '6', 'text': 'Manba: Thesis.pdf'},
        {'label': '7', 'text': 'Karimov A. Iqtisodiyot nazariyasi, 2020.'},
        'Jahon iqtisodiyoti va diplomatiya universiteti nashri',
    ]
    kept, codes = verify_items(items, known, file_names=['kurs_ishi_final.docx', 'Thesis.pdf'])
    assert kept == [items[0], items[1], items[7]]
    assert codes == ['source:dropped']
    assert verify_items([], known, file_names=[]) == ([], [])


def test_an_uzbek_paper_finds_its_cyrillic_sources_in_latin():
    known = facts.trusted(draft('Kurs ishi kerak', excerpts=[
        {'asset_id': 'a', 'page': 1, 'text': 'Каримов А. Иқтисодиёт назарияси. Тошкент: Фан, 2019.'}]))
    kept, codes = verify_items(['Karimov A. Iqtisodiyot nazariyasi. Toshkent: Fan, 2019.'], known,
                               file_names=['Каримов.pdf'])
    assert kept and not codes


# ---------------------------------------------------------------- what is trusted


def test_trusted_holds_every_word_the_customer_gave_and_nothing_else():
    data = draft('Yangi talab: Botirova Sevara ham qo‘shilsin', source_text='Matn: Qodirov Anvar',
                 excerpts=[{'asset_id': 'a', 'page': 1, 'text': 'Faylda: Ergasheva Lola'}],
                 revision={'request': 'Yangi talab: Botirova Sevara ham qo‘shilsin',
                           'original_prompt': 'Ariza: Nazarov Sardor',
                           'before': {'title': 'Ariza', 'sections': [{'id': 'request', 'heading': '',
                                                                      'body': 'Avvalgi: Toshmatov Jasur'}]}},
                 _cover_lines={'locale': 'uz', 'lines': ['Bajardi: Yusupova Malika']})
    data['options']['branding'] = {'name': 'Bahor Mebel'}
    known = facts.trusted(data)
    for name in ('Botirova Sevara', 'Qodirov Anvar', 'Ergasheva Lola', 'Nazarov Sardor', 'Toshmatov Jasur',
                 'Yusupova Malika', 'Bahor Mebel'):
        assert supported(name, 'person', known), name
    assert not supported('Xolmirzayev', 'person', known)


def test_the_categorys_own_words_are_allowed_but_its_made_up_examples_never_are():
    known = facts.trusted(draft('Ariza kerak'))
    # Labels and fixed headings of the ariza and of its template, in every language.
    assert ground('Ushbu ARIZA va Ilova. ЗАЯВЛЕНИЕ, APPLICATION, Расшифровка.', known)[1] == []
    # The field examples are invented people and organisations: never trusted, never allowed.
    assert not supported('Namuna davlat universiteti', 'org', known)
    assert not supported('Karimova Dilnoza Rustam qizi', 'person', known)
    # A draft without a category, or with one this catalogue lacks, still gets the base words.
    assert ground('Hurmatli Sizga yozaman.', facts.trusted({'prompt': 'x'}))[1] == []
    unknown = facts.trusted({'prompt': 'x', 'options': {'category': 'pdf.nope'}})
    assert ground('Hurmatli Sizga yozaman.', unknown)[1] == []


def test_an_earlier_version_is_trusted_only_where_it_was_held_to_the_customers_words():
    before = {'title': 'Test', 'sections': [
        {'id': 'facts', 'layout': 'list', 'items': [{'label': 'school', 'text': 'Sobirova Gulnora nomidagi maktab'},
                                                    {'label': 'teacher', 'text': 'Rasulova Iroda'}]},
        {'id': 'passage', 'heading': 'Matn', 'body': 'Matnni Jumanazarov Bekzod 1987-yilda yozgan. U '
                                                     '«bilim har bir yurtning eng katta boyligi» degan.'}]}
    data = {'prompt': 'Ona tili fanidan test', 'options': {'category': 'pdf.test'},
            'revision': {'request': 'Savollarni ko‘paytiring', 'original_prompt': 'Ona tili fanidan test',
                         'before': before}}
    known = facts.trusted(data)
    # The facts section was held to the customer's words when it was made; the passage is the model's own prose.
    assert supported('Sobirova Gulnora', 'person', known)
    # A value under a label that is no field of the entry was held to nothing: only its figures could be.
    assert not supported('Rasulova Iroda', 'person', known)
    assert ground('Testni Jumanazarov Bekzod 1987-yilda tuzgan.', known) == ('Testni ____-yilda tuzgan.',
                                                                              ['ground:number', 'ground:name'])
    # Its quotations may still be repeated in a later version.
    part = 'U «bilim har bir yurtning eng katta boyligi» degan.'
    assert guard(part, known) == (part, [])
    # A deck's slides are s1..sN and its slot mapping may have moved: nothing of them is read back as the customer's.
    deck = {'prompt': 'Himoya taqdimoti', 'options': {'category': 'slides.himoya'},
            'revision': {'request': 'Rangini o‘zgartiring', 'before': {'title': 'Himoya', 'sections': [
                {'id': 's2', 'heading': 'Dolzarblik', 'body': 'Ergashev Nodir 2019-yilda boshlagan.'}]}}}
    assert ground('Ergashev Nodir 2019-yilda boshlagan.', facts.trusted(deck))[1] == ['ground:number', 'ground:name']
    # Without a category, or with one this catalogue lacks, no earlier text is read as the customer's.
    for options in ({}, {'category': 'pdf.nope'}):
        known = facts.trusted({**data, 'options': options})
        assert not supported('Sobirova Gulnora', 'person', known)


def test_the_allow_list_is_matched_whole_never_by_prefix():
    known = facts.trusted(draft('Dekanga ariza yozing. Men Aliyev Vali, 2-kurs talabasiman.'))
    assert ground('The letter was signed by Martin Bestuzhev.', known) == ('The letter was signed by ____.',
                                                                           ['ground:name'])
    # Surnames and places that begin with a formula word, a weekday, a month or a language.
    for value in ('Jumayev', 'Madaminov', 'Hurmatov', 'Xonimova', 'Шанбаеву', 'Turkiston', 'Martin', 'Bestuzhev'):
        assert not supported(value, 'person', known), value
    # The forms a formula word takes in a letter are listed, so they still stand.
    part = ('Hurmatlim, Sizga yozaman. Sizning javobingizni kutaman. Уважаемая госпожа, прошу Вашего ответа. '
            'Ответ господину Aliyev. Dear Sir or Madam, kind regards.')
    assert ground(part, known) == (part, [])


def test_a_role_a_letter_is_addressed_to_is_not_a_name_but_the_name_beside_it_is_checked():
    known = facts.trusted(draft('Ariza yozing. Men Aliyev Vali.'))
    for part in ('Hurmatli Direktor! Sizdan so‘rayman.', 'Muhtaram Rektorimiz!', 'Hurmatli Hay’at a’zolari!',
                 'Assalomu alaykum, Hurmatli Ustoz!', 'Hurmatli Ota-onalar!', 'Уважаемый Директор! Прошу Вас.',
                 'Dear Hiring Manager,', 'Dear Members of the Committee,', 'To Whom It May Concern,'):
        assert ground(part, known) == (part, []), part
    assert ground('Hurmatli Direktor Jumayev Sardor!', known) == ('Hurmatli Direktor ____!', ['ground:name'])
    assert ground('Уважаемый Директор Мадаминов!', known) == ('Уважаемый Директор ____!', ['ground:name'])
    # A surname made from a role, and a role that is also a given name, are names.
    for value in ('Rahbarov', 'Mudirova', 'Директоров', 'Rais', 'Dean'):
        assert not supported(value, 'person', known), value


def test_a_month_is_never_an_allowed_spelling_of_a_name():
    known = facts.trusted(draft('2027-yil 5-yanvardan ta’til so‘rayman. Men Aliyev Vali.'))
    for value in ('Anvar', 'Анвар'):
        assert not supported(value, 'person', known), value
    assert supported('Yanvar', 'person', known) and supported('Январь', 'person', known)
    # Inside a word ya and ia still meet: Mariya, Maria and Мария are one name.
    assert supported('Maria', 'person', facts.trusted(draft('Men Mariya Aliyeva.')))
    assert supported('Мария', 'person', facts.trusted(draft('Men Mariya Aliyeva.')))


def test_currency_codes_and_role_acronyms_are_not_names():
    known = trusting('Narx 500 dollar. Bo‘limlar uchun ariza.')
    part = 'Narx 500 USD. IT bo‘limi va HR menejeri, CEO va KPI bilan; QQS UZS da.'
    assert ground(part, known) == (part, [])
    assert ground('Narx 500 USD, menejer Xolmirzayev.', known)[0] == 'Narx 500 USD, menejer ____.'


def test_general_knowledge_with_a_number_is_not_a_legal_reference():
    known = trusting('Kimyo fanidan referat: suv va moddalar.')
    for part in ('Suv murakkab modda bo‘lib, u 100 °C da qaynaydi.', 'Har bir modda 3 holatda bo‘ladi.',
                 'Talabalar 2 ta qaror qabul qilishdi.', 'Ohm’s law was formulated in 1827.',
                 'Закон Ома открыт в 1827 году.', 'Article 3 discusses methods.'):
        assert guard(part, known) == (part, []), part
    for part in ('Mehnat kodeksining 214-moddasiga ko‘ra', 'статья 214', 'Article 214 of the Labour Code',
                 '593-son qaror', 'Bu qonun № 15 bilan tasdiqlangan.', 'Закон от 12.05.2020 это требует.',
                 'Konstitutsiyaning 5-moddasiga ko‘ra.', 'Согласно Конституции это право.',
                 'The Constitution guarantees it.'):
        assert guard(part, known) == ('', ['ground:law']), part


def test_a_number_is_never_found_through_a_part_of_another():
    assert ground('Narxi 150 so‘m.', trusting('Narx 1 150 000 so‘m'))[1] == ['ground:number']
    assert ground('Narxi 1 so‘m.', trusting('Narx 1 150 000 so‘m'))[1] == ['ground:number']
    assert ground('Narx 45 so‘m', trusting('Tel: +998 90 123 45 67'))[1] == ['ground:number']
    keys = numbers.values('03.11.2026')
    assert 'd:3.11' in keys and '2026' in keys and '3' not in keys and '11' not in keys
    # "mayda" is "small" unless the hyphen, a year or "kuni" makes it a day of May.
    assert numbers.values('5 mayda bola') == {'5'}
    for text in ('5-mayda', '5 mayda kuni', '2026-yil 5 mayda'):
        assert 'd:5.5' in numbers.values(text), text


def test_a_translated_persons_name_may_take_the_russian_spelling_of_o():
    known = facts.trusted(draft('Ariza yozing. Men G‘ofurov Sardor, rahbarim Xo‘jayev Botir, Yo‘ldosheva Lola.'))
    for value in ('Гафуров Сардор', 'Ходжаев Ботир', 'Хужаев Ботир', 'Юлдашева Лола'):
        assert supported(value, 'person', known, translated=True), value
    # Only for a translated document, and never a name the customer did not give.
    assert not supported('Гафуров Сардор', 'person', known)
    for value in ('Гаффаров Сардор', 'Мадаминов Ботир', 'Anvar'):
        assert not supported(value, 'person', known, translated=True), value


def test_a_time_is_one_value_its_hour_and_minutes():
    known = trusting('Majlis soat 10 da boshlanadi va 14:30 gacha davom etadi.')
    part = 'Majlis soat 10:00 da boshlanadi va 14:30 da tugaydi.'
    assert ground(part, known) == (part, [])
    # Numbers given apart never make a time, and a time gives its hour only on the hour.
    for part in ('Soat 10:30 da boshlanadi.', 'Soat 14 da tugaydi.', 'Soat 9:00 da.'):
        assert ground(part, known)[1] == ['ground:number'], part
    assert {'t:9:05', 'd:15.11'} <= numbers.values('15.11.2026, 09:05')


def test_a_translated_references_list_is_held_by_its_numbers():
    known = trusting('Manba: Karimov A. Iqtisodiyot nazariyasi, 2019.')
    items = ['Karimov A. Economic Theory, 2019.', 'Karimov A. Economic Theory, 2020.']
    assert verify_items(items, known) == ([], ['source:dropped'])
    assert verify_items(items, known, translated=True) == ([items[0]], ['source:dropped'])


def test_a_translated_references_list_still_holds_the_authors_it_opens_with():
    known = trusting('Manba: Karimov A. Iqtisodiyot nazariyasi, 2019.')
    items = ['Karimov A. Economic Theory, 2019.', 'Каримов А. Экономическая теория, 2019.',
             'Xolmatov S. Basics of Economics', 'A. Karimov, S. Xolmatov. Economic Theory', 'Economic Theory. Part I.']
    # A title opening an item is held as its head (`_people_named_known`): one a translation renamed goes, a false
    # drop, so that an author written in full is never let through as a title.
    assert verify_items(items, known, translated=True) == ([items[0], items[1]], ['source:dropped'])


def test_a_translated_cover_keeps_an_academic_title():
    # A cover line's label is the label's own (finish._line_known); its value is held as a person's.
    known = trusting('Ilmiy rahbar: dotsent Rahimova N.')
    assert supported('Associate Professor N. Rahimova', 'person', known, translated=True)
    assert supported('Доцент Рахимова Н.', 'person', known, translated=True)
    assert not supported('Associate Professor B. Xolmirzayev', 'person', known, translated=True)


def test_codes_name_what_was_taken_never_the_value(uz):
    found = set()
    for text in ('Xolmirzayev 4 870 000 so‘m. «bir ikki uch to‘rt besh». PF-60-son Farmon.', 'info@namuna.uz'):
        found |= set(ground(text, uz)[1])
    found |= set(verify_items(['Xolmirzayev'], uz, file_names=[])[1])
    assert found <= CODES and found


# ---------------------------------------------------------------- addresses in linear time

# The address forms as they were before they were made linear, the reference for what they must still match.
PLAIN_EMAIL = r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+"
PLAIN_LINK = (r"(?:https?://|www\.)\S+|\b[\w\-]+(?:\.[\w\-]+)*\."
              r"(?:uz|com|ru|org|net|io|me|info|edu|gov|kz|tj|kg|su|shop|store|online|site|co|de)(?:/\S*)?(?!\w)")
PLAIN_HANDLE = r"(?<![\w.@])@[A-Za-z0-9_](?:[A-Za-z0-9_.]{1,30}[A-Za-z0-9_])(?![\w@])"
ADDRESSES = (
    'E-pochta: dilnoza.k@example.com, nusxasi info@namuna.uz ga.',
    'Почта: d.karimova+ariza@mail.namuna.ru; сайт https://namuna.uz/qabul?id=7 и www.namuna-edu.uz/about.',
    'Sayt: namuna.uz, mail.ped.namuna.edu.uz va e-library.namuna.uz/kitoblar; my.gov.uz orqali ariza bering.',
    'Write to j.yusupov@test-mail.co.uz or visit test-school.org/en. The file is report.v2.pdf, not a link.',
    'Ro‘yxat: -namuna.uz, (namuna.com), «namuna.ru», sub.domain.namuna.info. Oxiri.namuna.io!',
    'Matn.Gap.Sayt: uz.namuna.uz-ga, foo.uz.bar, foo.uz-bar va a--b.namuna.net hamda x@y.z.uz.',
)


def test_addresses_are_read_as_before_on_ordinary_text():
    texts = list(ADDRESSES)
    for path in sorted((Path(categories.__file__).parent / 'data').glob('*.json')):
        texts.append(path.read_text(encoding='utf-8'))
    for text in texts:
        assert [m.span() for m in facts.EMAIL.finditer(text)] == \
            [m.span() for m in re.finditer(PLAIN_EMAIL, text)], text[:80]
        assert [m.span() for m in facts.LINK.finditer(text)] == \
            [m.span() for m in re.finditer(PLAIN_LINK, text, re.IGNORECASE)], text[:80]
        assert [m.span() for m in numbers.SKIPPED.finditer(text)] == \
            [m.span() for m in re.finditer(f'{PLAIN_EMAIL}|{PLAIN_LINK}|{PLAIN_HANDLE}', text, re.I)], text[:80]
    known = trusting(ADDRESSES[0] + ' ' + ADDRESSES[1])
    assert known.emails == {'dilnoza.k@example.com', 'info@namuna.uz', 'd.karimova+ariza@mail.namuna.ru'}
    assert known.links == {'namuna.uz/qabul?id=7', 'namuna-edu.uz/about'}


# 'a--.' (labels ending in hyphens, joined by dots) is the slowest shape found: the link's lookbehinds allow a start
# at every letter after '--'.
@pytest.mark.parametrize('run', ['ab.', 'a-b', 'ab.cd-', 'a.+', 'a--', 'a--.', 'a.' * 40 + '@b', '1.2-3', 'аб.вг-',
                                 'a-' * 31 + 'a.'])
def test_long_runs_of_letters_dots_and_hyphens_are_read_in_linear_time(run):
    """A source of 130,000 characters made of such runs once took facts.trusting about 15 s, inside the lease."""
    part = (run * (3000 // len(run)))[:3000]
    source = '\n'.join([part] * 44)
    started = time.monotonic()
    facts.trusting(source)
    assert time.monotonic() - started < 2


def test_a_draft_slot_with_checks_holds_its_numbers_and_names_and_nothing_more_without():
    known = trusting('Pedagogik kengash: bilim sifati 58,4%, nazorat Mohira Namunovaga yuklatilsin.')
    part = 'Sifat 58,4% dan 61% ga oshsin, nazorat Mohira Namunova va Sardor Xolmatovga, info@namuna.uz.'
    assert guard(part, known) == (part, [])
    assert guard(part, known, checks=('numbers',)) == \
        ('Sifat 58,4% dan ____% ga oshsin, nazorat Mohira Namunova va Sardor Xolmatovga, ____.', ['ground:number'])
    assert guard(part, known, checks=('numbers', 'names')) == \
        ('Sifat 58,4% dan ____% ga oshsin, nazorat Mohira Namunova va ____, ____.', ['ground:number', 'ground:name'])


@pytest.mark.parametrize('part, written', [
    ('Ma’ruzachi: Xolmatov S.', 'Ma’ruzachi: ____'),
    ('Qo‘shimcha darslar tashkil etilsin — mas’ul: Xolmatov S.', 'Qo‘shimcha darslar tashkil etilsin — mas’ul: ____'),
    ('Mas’ul: Xolmatov Sardor', 'Mas’ul: ____'),
    ('Sardor Xolmatov', '____'),
    ('Xolmatov S. hisobot beradi', '____ hisobot beradi'),
    ('S. R. Xolmatov hisobot beradi', '____ hisobot beradi'),
], ids=['reporter-initial', 'responsible-after-dash', 'responsible-full', 'row-of-its-own', 'sentence-first-initial',
        'initials-first'])
def test_a_slot_that_checks_names_takes_an_invented_name_whole_where_a_label_or_a_row_names_it(part, written):
    known = trusting('Pedagogik kengash: bilim sifati, nazorat Mohira Namunovaga yuklatilsin.')
    assert guard(part, known, checks=('names',)) == (written, ['ground:name'])


@pytest.mark.parametrize('part', [
    'Ma’ruzachi: Namunova M.', 'Mas’ul: Mohira Namunova', 'Nazorat Namunova M. zimmasiga', 'Bunga e’tibor bering',
    'Shuningdek, bilim sifati oshsin', 'Mas’ul: direktor o‘rinbosari'])
def test_a_slot_that_checks_names_keeps_the_customers_people_and_a_lone_grammar_word(part):
    known = trusting('Pedagogik kengash: bilim sifati, nazorat Mohira Namunovaga yuklatilsin.')
    assert guard(part, known, checks=('names',)) == (part, [])


@pytest.mark.parametrize('part, written', [
    ('Xolmatovga yuklansin.', '____ yuklansin.'),
    ('Darslar tashkil etilsin. Xolmatov javobgar.', 'Darslar tashkil etilsin. ____ javobgar.'),
    ('1. Xolmatov javobgar', '1. ____ javobgar'),
    ('— Xolmatov', '— ____'),
    ('Xolmatov', '____'),
    ('Холматовой поручить', '____ поручить'),
    ('Xolmirzayevaga topshirilsin', '____ topshirilsin'),
    ('Mas’ul: S.Xolmatov', 'Mas’ul: ____'),
], ids=['case-ending', 'opens-a-sentence', 'list-item', 'dash-row', 'item-alone', 'cyrillic', 'yev-feminine',
        'initial-without-space'])
def test_a_slot_that_checks_names_takes_a_lone_invented_surname_that_opens_a_sentence_or_a_row(part, written):
    # A surname alone at the start of a row is the very form a resolution's or an agenda's responsible person takes.
    known = trusting('Pedagogik kengash: bilim sifati, nazorat Mohira Namunovaga yuklatilsin.')
    assert guard(part, known, checks=('names',)) == (written, ['ground:name'])


@pytest.mark.parametrize('part', [
    'Namunova javobgar.', '1. Namunovaga yuklansin', 'Tanlov o‘tkazilsin.', 'Sinovlar yakunlansin.',
    'To‘lovlar o‘z vaqtida qilinsin.', 'Pedsovet qarori bajarilsin.'])
def test_a_surname_shaped_first_word_is_kept_when_it_is_the_customers_or_a_common_word(part):
    known = trusting('Pedagogik kengash: bilim sifati, nazorat Mohira Namunovaga yuklatilsin.')
    assert guard(part, known, checks=('names',)) == (part, [])


def test_people_known_reads_a_line_as_the_names_check_does():
    known = trusting('Kurs ishi. Bajardi: Yusupov Jasur.')
    assert facts.people_known('Term paper', known) and facts.people_known('Yusupov Jasur', known)
    assert not facts.people_known('Xolmirzayev Botir', known)
    assert not facts.people_known('Prepared by Botir Xolmirzayev', known)
    assert facts.people_known('Toshkent davlat iqtisodiyot universiteti', known)


def test_guard_reads_numbers_in_words_only_when_asked():
    known = trusting('Sotuv menejeri lavozimiga xat, men savdoda ishlaganman.')
    text = 'With over five years of experience, I led twelve people.'
    assert guard(text, known, checks=('numbers',)) == (text, [])
    assert guard(text, known, checks=('numbers',), words=True) == (
        'With over ____ years of experience, I led ____ people.', ['ground:number'])
    assert ground(text, known) == (text, []), 'a deck slide keeps its reading'
    assert not supported('five years in retail', 'text', known, words=True)
    assert supported('five years in retail', 'text', known)
    assert supported('five years in retail', 'text', trusting('5 yil savdoda ishlaganman'), words=True)


def test_ground_still_leaves_the_first_word_of_a_sentence():
    # ground's limit is unchanged until the owner takes the false blanks the strict reading costs everywhere.
    known = trusting('Pedagogik kengash')
    assert ground('Sardor Xolmatov hisobot beradi', known) == ('Sardor ____ hisobot beradi', ['ground:name'])


def test_a_count_the_document_makes_of_itself_is_held_and_nothing_more():
    known = facts.counting(trusting('Pedagogik kengash'), 4)
    assert guard('Bugun 4 ta masala ko‘riladi', known, checks=('numbers',)) == ('Bugun 4 ta masala ko‘riladi', [])
    assert guard('Bugun 5 ta masala ko‘riladi', known, checks=('numbers',)) == \
        ('Bugun ____ ta masala ko‘riladi', ['ground:number'])
    assert facts.counting(known, 0) is known


def test_a_counted_copy_shares_the_respelled_words_rather_than_folding_the_source_again():
    known = trusting('Nazorat Mohira Namunovaga yuklatilsin.')
    counted = facts.counting(known, 4)
    assert counted is not known and counted.respelled is known.respelled
    assert facts.counting(trusting('Pedagogik kengash'), 3).person('Namunova', True) is False


# ---------------------------------------------------------------- numbers in words (stage-2 re-audit)


def read(text, *, model=True):
    """(value, words) of each number of `text`, read as a paper's own text is (`model`) or as the customer's."""
    return [(number.value, text[number.start:number.end])
            for number in numbers.found(text, words=True, uzbek_cyrillic=not model)]


@pytest.mark.parametrize('text, found', [
    ('У меня более чем пятилетний опыт работы', [('5', 'пятилетний')]),
    ('Мой десятилетний опыт, двухнедельный курс', [('10', 'десятилетний'), ('2', 'двухнедельный')]),
    ('двадцатипятилетний стаж и сорокакратный рост', [('25', 'двадцатипятилетний'), ('40', 'сорокакратный')]),
    ('Оборот превысил полмиллиона долларов', [('500000', 'полмиллиона')]),
    ('Loyihaning qiymati yarim milliard so‘m', [('500000000', 'yarim milliard')]),
    ('Yiliga ming tonna non, kuniga mingta non', [('1000', 'ming'), ('1000', 'mingta')]),
    ('Ellikdan ortiq ish o‘rni, mijozlar yigirmaga yetadi', [('50', 'Ellikdan'), ('20', 'yigirmaga')]),
    ('Ellikka yaqin o‘rin, jamoa beshga yetadi, o‘ttizdan ortiq mijoz',
     [('50', 'Ellikka'), ('5', 'beshga'), ('30', 'o‘ttizdan')]),
    ('Loyiha yuz ish o‘rnini yaratadi, yuzdan ortiq mijoz', [('100', 'yuz'), ('100', 'yuzdan')]),
    ('I doubled sales; a fivefold rise; продажи выросли вдвое; обслуживал сотню клиентов',
     [('2', 'doubled'), ('5', 'fivefold'), ('2', 'вдвое'), ('100', 'сотню')]),
], ids=['ru-fused', 'ru-fused-two', 'ru-fused-tens', 'ru-half-scale', 'uz-half-scale', 'uz-bare-ming', 'uz-cases',
        'uz-cases-more', 'uz-bare-yuz', 'times-over'])
def test_the_common_ways_a_figure_is_spoken_are_read(text, found):
    assert read(text) == found


@pytest.mark.parametrize('text', [
    'последние десятилетия', 'многолетний опыт', 'полгода', 'o‘nlab mijozlar', 'yuzlab mijozlar', 'birdan',
    'birga ishlaymiz', 'oltini', 'ming yillik tarix', 'muammo yuz berdi', 'yuzni yuvdi', 'ming afsus',
    'a one-time fee', 'twice a week', 'hundreds of clients',
])
def test_vague_and_ordinary_words_are_still_not_read_as_figures(text):
    assert read(text) == []


@pytest.mark.parametrize('text, found', [
    ('Jami bir million bir yuz ellik ming so‘m', [('1150000', 'bir million bir yuz ellik ming')]),
    ('eleven thousand one hundred and forty-one', [('11141', 'eleven thousand one hundred and forty-one')]),
    ('one hundred and one clients', [('101', 'one hundred and one')]),
    ('two thousand one hundred people', [('2100', 'two thousand one hundred')]),
    ('девять тысяч один рубль', [('9001', 'девять тысяч один')]),
    ('o‘ttiz birta xodim', [('31', 'o‘ttiz birta')]),
    ('Kuniga yuz ellik nafar mijoz', [('150', 'yuz ellik')]),
    ('o‘n beshga yetadi', [('15', 'o‘n beshga')]),
    ('ming besh yuz ming so‘m', [('1000', 'ming'), ('500000', 'besh yuz ming')]),
    ('ikki ming-uch ming so‘m', [('2000', 'ikki ming'), ('3000', 'uch ming')]),
], ids=['uz-million', 'en-thousands', 'en-and-one', 'en-one-hundred', 'ru-one-last', 'uz-birta', 'uz-bare-yuz',
        'uz-ending', 'uz-scale-again', 'uz-range'])
def test_a_compound_is_read_whole_never_split_into_numbers_the_customer_gave(text, found):
    assert read(text) == found


def test_a_compound_another_way_round_never_passes_on_the_parts_the_customer_gave():
    for brief, written in (('Ustav kapitali 1 000 000 so‘m, aylanma 150 000 so‘m.', 'bir million bir yuz ellik ming'),
                           ('Kafemiz 50 o‘rinli.', 'yuz ellik nafar'), ('30 nafar xodim', 'o‘ttiz birta xodim'),
                           ('10 nafar xodim', 'o‘n beshga yetadi'), ('9000 рублей', 'девять тысяч один рубль')):
        given = numbers.values(brief)
        assert not all(numbers.known(number, given) for number in numbers.found(written, words=True)), written


EN_UNITS = ['', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve',
            'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen']
EN_TENS = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety']
UZ_UNITS = ['', 'bir', 'ikki', 'uch', 'to‘rt', 'besh', 'olti', 'yetti', 'sakkiz', 'to‘qqiz']
UZ_TENS = ['', 'o‘n', 'yigirma', 'o‘ttiz', 'qirq', 'ellik', 'oltmish', 'yetmish', 'sakson', 'to‘qson']
RU_UNITS = ['', 'один', 'два', 'три', 'четыре', 'пять', 'шесть', 'семь', 'восемь', 'девять', 'десять',
            'одиннадцать', 'двенадцать', 'тринадцать', 'четырнадцать', 'пятнадцать', 'шестнадцать', 'семнадцать',
            'восемнадцать', 'девятнадцать']
RU_TENS = ['', '', 'двадцать', 'тридцать', 'сорок', 'пятьдесят', 'шестьдесят', 'семьдесят', 'восемьдесят',
           'девяносто']
RU_HUNDREDS = ['', 'сто', 'двести', 'триста', 'четыреста', 'пятьсот', 'шестьсот', 'семьсот', 'восемьсот',
               'девятьсот']


def english(value):
    if value >= 10 ** 6:
        return f'{english(value // 10 ** 6)} million {english(value % 10 ** 6)}'.strip()
    if value >= 1000:
        joint = 'and ' if 0 < value % 1000 < 100 else ''
        return f'{english(value // 1000)} thousand {joint}{english(value % 1000)}'.strip()
    if value >= 100:
        return f'{EN_UNITS[value // 100]} hundred {"and " if value % 100 else ""}{english(value % 100)}'.strip()
    if value >= 20:
        return EN_TENS[value // 10] + (f'-{EN_UNITS[value % 10]}' if value % 10 else '')
    return EN_UNITS[value]


def uzbek(value, formal):
    """Uzbek in words, formally ("bir yuz", "bir ming") or as it is spoken ("yuz", "ming")."""
    words = []
    if value >= 10 ** 6:
        words += [uzbek(value // 10 ** 6, formal), 'million']
        value %= 10 ** 6
    if value >= 1000:
        if value // 1000 > 1 or formal:
            words.append(uzbek(value // 1000, formal))
        words.append('ming')
        value %= 1000
    if value >= 100:
        if value // 100 > 1 or formal:
            words.append(UZ_UNITS[value // 100])
        words.append('yuz')
        value %= 100
    words += [UZ_TENS[value // 10], UZ_UNITS[value % 10]]
    return ' '.join(word for word in words if word)


def russian(value):
    words = ['тысяча'] if value >= 1000 else []
    value %= 1000
    words.append(RU_HUNDREDS[value // 100])
    value %= 100
    words += [RU_UNITS[value]] if value < 20 else [RU_TENS[value // 10], RU_UNITS[value % 10]]
    return ' '.join(word for word in words if word)


def uzbek_with(text, case):
    """`text` with a case ending on its last word, as Uzbek joins it: "ellikka", "qirqqa", "beshga", "beshdan"."""
    if case == 'ga':
        return text + ('ka' if text.endswith('k') else 'qa' if text.endswith('q') else 'ga')
    return text + case


def test_every_number_written_in_words_reads_as_itself():
    """found(spelled(n)) == [n] for 2..1999 in each language and Uzbek's case endings, and for round amounts."""
    wrong = []
    for value in range(2, 2000):
        texts = [f'{english(value)} clients', f'{russian(value)} рублей']
        for formal in (True, False):
            spoken = uzbek(value, formal)
            texts += [f'{spoken} xodim', f'{spoken}ta xodim', f'{uzbek_with(spoken, "dan")} ortiq',
                      f'{uzbek_with(spoken, "ga")} yetadi']
        wrong += [(text, read(text)) for text in texts if [found for found, _ in read(text)] != [str(value)]]
    for count in range(2, 1000, 37):
        for value in (count * 1000, count * 10 ** 6, count * 10 ** 6 + 150000, count * 10 ** 6 + 1000 * count):
            for text in (english(value), uzbek(value, True), uzbek(value, False)):
                if [found for found, _ in read(f'{text} so‘m')] != [str(value)]:
                    wrong.append((text, read(f'{text} so‘m')))
    assert not wrong, wrong[:10]


@pytest.mark.parametrize('text', [
    'yigirma birinchi asr ko‘nikmalari', 'the twenty-first century', 'o‘ttiz ikkinchi maktab', 'в двадцать первом веке',
])
def test_the_tens_of_an_ordinal_are_never_read_as_a_count(text):
    assert read(text) == []
    assert ground_paper_of(text) == (text, [])


# An ordinal before a month is a date's day, never a count of its tens (round 4: "o‘n beshinchi mayda" passed for the
# customer's "12-may"); one before a placing or a run of years is a figure.
@pytest.mark.parametrize('text, found', [
    ('o‘n beshinchi mayda', [('d:15.5', 'o‘n beshinchi mayda')]),
    ('the twenty-third of May', [('d:23.5', 'twenty-third of May')]),
    ('пятнадцатого мая 2025 года', [('d:15.5', 'пятнадцатого мая 2025 года')]),
    ('olimpiadada ikkinchi o‘rinni egalladi', [('2', 'ikkinchi')]),
    ('I won first place', [('1', 'first')]), ('In the first place, I won', []),
    ('for the fifth consecutive year', [('5', 'fifth')]), ('Пятый год подряд', [('5', 'Пятый')]),
    ('over a decade of experience', [('10', 'a decade')]), ('decades of experience', []),
], ids=['uz-date', 'en-date', 'ru-date-with-year', 'uz-place', 'en-place', 'en-firstly', 'en-years-running',
        'ru-years-running', 'a-decade', 'decades'])
def test_an_ordinal_that_dates_places_or_counts_years_is_read_as_its_figure(text, found):
    assert read(text) == found


@pytest.mark.parametrize('brief, written, kept', [
    ('I joined on 1 September 2019 and left on 30 June 2023.', 'I joined on 1 September 2023.', False),
    ('Я работала с 1 сентября 2019 года по 30 июня 2023 года.', '1 сентября 2023 года', False),
    ('Majlis 2025-yil 12-mayda bo‘ldi, 2024-yil natijalari.', '2024-yil 12-may', False),
    ('Majlis 2025-yil 12-mayda bo‘ldi.', '2025-yil 12-may', True),
    ('Majlis 12-may kuni, 2025-yil rejasi.', '2025-yil 12-may', True),
    ('The meeting is on May 12, 2025.', '12 May 2025', True),
], ids=['en-other-year', 'ru-other-year', 'uz-other-year', 'uz-same', 'uz-written-apart', 'en-month-first'])
def test_a_written_dates_year_is_tied_to_its_day_and_month(brief, written, kept):
    found = numbers.found(written, words=True)
    assert all(numbers.known(number, numbers.values(brief)) for number in found) is kept


def test_a_count_before_a_word_that_only_starts_like_an_ordinal_is_still_read():
    assert read('twenty first-rate clients') == [('20', 'twenty')]


def ground_paper_of(text):
    from apps.studio.categories import finish
    return finish.ground_paper(text, trusting('11-sinf o‘quvchilari uchun dars ishlanmasi'))


def test_a_paper_reads_its_own_cyrillic_as_russian_never_as_uzbek_in_latin():
    for text in ('Тень от дерева', 'Итоги 2024/25 уч. года', 'Саксонская династия'):
        assert [found for found in read(text) if not found[1].isdigit() and '/' not in found[1]] == [], text
    assert read('беш юз минг сўм', model=False) == [('500000', 'беш юз минг')]
    assert '100' in numbers.values('Юз нафар ишчи ишлайди.'), 'a counted noun is read on the Latin form'


def test_a_run_of_multipliers_never_makes_a_number_too_long_to_write():
    for text in ('one ' + 'hundred ' * 2200, 'besh ' + 'yuz ' * 2200, 'a ' + 'dozen ' * 6000,
                 'hundred thousand ' * 3000, '-'.join(['hundred'] * 2200)):
        started = time.monotonic()
        keys = numbers.values(text)
        assert all(len(key) < 40 for key in keys) and time.monotonic() - started < 2
    assert [found for found, _ in read('besh yuz yuz kishi')] == ['500']
    assert [found for found, _ in read('one hundred hundred')] == ['100']


def test_a_source_of_repeated_multipliers_never_fails_a_paper_or_unchecks_a_deck():
    known = facts.trusted(draft('Ariza yozing. ' + 'bir ' + 'yuz ' * 2300))
    assert ground('Kompaniya 2024-yilda 750 mln so‘m foyda oldi.', known)[1] == ['ground:number']


@pytest.mark.parametrize('brief, written, kept', [
    ('2024-yil faoliyati bo‘yicha hisobot, sanasi 15.01.2025', '15.01.2024', False),
    ('2024-yil faoliyati bo‘yicha hisobot, sanasi 15.01.2025', '15.01.2025', True),
    ('2024-yil faoliyati bo‘yicha hisobot, sanasi 15.01.2025', '2025-01-15', True),
    ('2024-yil faoliyati bo‘yicha hisobot, sanasi 15.01.2025', '15-yanvar', True),
    ('Majlis 2025-yil 12-mayda bo‘ldi, 2024-yil natijalari', '12.05.2025', True),
    ('Majlis 12-may kuni, 2025-yil rejasi', '12.05.2025', True),
    ('Sanasi 15.01', '15.01.2025', False),
    ('Sanasi 15.01, 2025-yil', '15.01.2025', True),
], ids=['other-year', 'same', 'iso', 'no-year', 'written-with-year', 'written-apart', 'year-not-given', 'dotted'])
def test_a_numeric_dates_year_is_tied_to_its_day_and_month(brief, written, kept):
    assert all(numbers.known(number, numbers.values(brief)) for number in numbers.found(written)) is kept


@pytest.mark.parametrize('brief, written, kept', [
    ('I raised 1.2 million dollars.', 'I raised $1.2bn.', False),
    ('I raised 1.2 million dollars.', 'I raised $1.2B.', False),
    ('Our team has 3 people.', 'We raised $3M.', False),
    ('Budget 5 thousand dollars.', 'Budget €5m.', False),
    ('Narx 5 so‘m.', 'Narx 5 mlrd so‘m.', False),
    ('I raised 1.2 billion dollars.', 'I raised $1.2bn.', True),
    ('$2M seed round', 'a seed round of 2 million dollars', True),
    ('Kredit 1 500 000 so‘m', 'Kredit 1,5\u202fmln so‘m', True),
    ('Kredit 1 500 000 so‘m', 'Kredit 1,5\u2009mln so‘m', True),
    ('Masofa 100 m, 9B sinf', '100 m masofa, 9B sinf', True),
], ids=['bn', 'B', 'M', 'm', 'mlrd', 'bn-given', 'M-given', 'narrow-space', 'thin-space', 'metres-and-class'])
def test_a_scale_written_short_or_glued_to_a_currency_is_read(brief, written, kept):
    assert all(numbers.known(number, numbers.values(brief)) for number in numbers.found(written)) is kept


# ---------------------------------------------------------------- laws (stage-2 re-audit)


@pytest.mark.parametrize('part', [
    'Dars Xalq ta’limi vazirligining 2017-yil 6-apreldagi 187-sonli buyrug‘i asosida tashkil etiladi.',
    'Bu hukumatning 2019-yil 3-martdagi 175-sonli qarorida belgilangan.',
    'Bu 1998-yil 29-avgustdagi 625-I-sonli qonun bilan tasdiqlangan.',
    'Bu 625-I-son qonun bilan tasdiqlangan.',
    'Reja 45-sonli Nizom asosida tuziladi.',
    'BMTning Bola huquqlari to‘g‘risidagi konvensiyasida shunday deyilgan.',
    'In line with the Ministry of Public Education order of 6 April 2017 lessons last 45 minutes.',
    'Under Regulation 2016/679 the data is protected.',
    'Согласно Положению о школе уроки длятся 45 минут.',
    'Согласно приказу Министерства образования от 6 апреля 2017 года урок длится 45 минут.',
], ids=['ministry-sonli', 'government-sonli', 'law-sonli-roman', 'law-son-roman', 'nizom', 'convention', 'en-order',
        'en-regulation', 'ru-polozhenie', 'ru-ministry'])
def test_a_ministry_or_government_act_the_customer_never_named_is_a_legal_sentence(part):
    known = trusting('7-sinf matematika fanidan dars ishlanmasi: kasrlarni qo‘shish.')
    assert guard(part, known) == ('', ['ground:law'])
    assert ground(part, known) == ('', ['ground:law']), 'never a skeleton of the citation with its figures blanked'


@pytest.mark.parametrize('part', [
    '1-sonli jadvalda ko‘rsatilganidek, natija yaxshi.', 'Tadqiqot Toshkent shahridagi 45-sonli maktabda o‘tkazildi.',
    'Ma’lumotlar 3-sonli ilovada keltirilgan.', 'O‘quvchilar maktab nizomiga rioya qiladi.',
    'In order to finish, we work.', 'We work in order to finish on time.', 'The order of the chapters is clear.',
    'A naming convention helps the reader.',
])
def test_a_numbered_table_school_or_annex_and_order_in_other_senses_are_no_legal_sentence(part):
    known = trusting('Iqtisodiyot fanidan kurs ishi: 1-sonli jadval, 45-sonli maktab, 3-sonli ilova.')
    assert guard(part, known) == (part, [])


def test_an_order_the_customer_named_stays():
    known = trusting('Dars Xalq ta’limi vazirligining 2017-yil 6-apreldagi 187-sonli buyrug‘i asosida o‘tadi.')
    part = 'Dars Xalq ta’limi vazirligining 2017-yil 6-apreldagi 187-sonli buyrug‘i asosida tashkil etiladi.'
    assert guard(part, known) == (part, []) and ground(part, known) == (part, [])


JOB_UZ = 'Bosh buxgalter uchun lavozim yo‘riqnomasi yozing, Mehnat kodeksiga muvofiq.'


@pytest.mark.parametrize('part', [
    'Soliq kodeksi va Mehnat kodeksi talablariga amal qiladi.', 'Fuqarolik kodeksining talablariga rioya qiladi.',
    'Jinoyat kodeksiga muvofiq javobgar bo‘ladi.', '- Bojxona kodeksi talablarini biladi.',
], ids=['tax-and-labour', 'civil', 'criminal', 'customs-item'])
def test_a_code_the_customer_never_named_goes_when_its_name_opens_the_sentence(part):
    known = trusting(JOB_UZ)
    assert guard(part, known) == ('', ['ground:law'])
    russian = trusting('Напишите должностную инструкцию главного бухгалтера согласно Трудовому кодексу.')
    assert guard(part.lstrip('- '), russian, translated=True) == ('', ['ground:law'])


@pytest.mark.parametrize('part, translated', [
    ('Mehnat kodeksiga muvofiq ishlaydi.', False), ('O‘zbekiston Respublikasi Mehnat kodeksiga amal qiladi.', False),
    ('Mehnat kodeksi talablariga amal qiladi.', True), ('The Labour Code requires a written contract.', True),
    ('Согласно Трудовому кодексу работник отдыхает.', True),
], ids=['uz', 'uz-republic', 'translated-uz', 'translated-en', 'ru'])
def test_the_code_the_customer_named_stays_in_any_language(part, translated):
    known = trusting('Напишите должностную инструкцию согласно Трудовому кодексу.') if translated else trusting(JOB_UZ)
    assert guard(part, known, translated=translated) == (part, [])


# ---------------------------------------------------------------- quotation marks (stage-2 re-audit)


@pytest.mark.parametrize('part', [
    'As Peter Drucker put it, ‘the aim of marketing is to make selling superfluous’.',
    "As Peter Drucker put it, 'the aim of marketing is to make selling superfluous'.",
    'Как писал Котлер, ‹маркетинг — это искусство находить клиентов›.',
    'Как писал Котлер, ‚маркетинг — это искусство находить клиентов‘.',
    'Muallif aytganidek, ‘bilim olish har bir o‘quvchining burchidir’.',
], ids=['curly-single', 'straight-single', 'guillemet-single', 'low-single', 'uz-single'])
def test_a_quotation_in_single_marks_is_checked_as_any_other(part):
    known = trusting('Marketing bo‘yicha kurs ishi yozib bering.')
    written, codes = guard(part, known)
    assert codes == ['ground:quote'] and written.endswith(', ____.')
    assert guard(part, trusting(part)) == (part, []), 'the customer\'s own quotation stays'


@pytest.mark.parametrize('part', [
    'O‘quvchilar ma’lumot oldi, g‘oyalar o‘rganildi va bo‘limlar ko‘rib chiqildi.',
    "O'quvchilar ma'lumot oldi, g'oyalar o'rganildi va bo'limlar ko'rib chiqildi.",
    "O ‘quvchilar ma ’lumot oldi, g ‘oyalar o ‘rganildi va bo ‘limlar ko ‘rib chiqildi.",
    "Drucker's book and the students' work show the teachers' role in it's own way.",
], ids=['uz-marks', 'uz-straight', 'uz-spaced', 'en-apostrophes'])
def test_uzbek_letters_and_english_apostrophes_are_never_quotation_marks(part):
    assert guard(part, trusting('Marketing bo‘yicha kurs ishi yozib bering.')) == (part, [])


# ---------------------------------------------------------------- handles and sites (stage-2 re-audit)


@pytest.mark.parametrize('value', ['@aziz_karimov', 'aziz-karimov.kz', 'aziz.shop', 'aziz.online/portfolio',
                                   't.me/aziz', 'instagram.com/aziz'])
def test_a_handle_or_a_site_the_customer_never_gave_is_not_kept(value):
    known = trusting('Sotuv menejeri lavozimiga xat yozing. Men Aziz Karimov, telefon +998 90 123 45 67.')
    assert not supported(value, 'line', known, strict=True)
    assert ground(f'Bog‘lanish: {value}', known) == ('Bog‘lanish: ____', ['ground:number'])


def test_the_customers_own_handle_is_kept_however_they_gave_it():
    known = trusting('Telegram: @Oqtosh_Mebel, sayt oqtosh.shop, bot t.me/oqtosh_bot, Instagram: @oqtosh.uz')
    for value in ('@oqtosh_mebel', '@Oqtosh_Mebel', '@oqtosh_bot', 'oqtosh.shop', '@oqtosh.uz'):
        assert supported(value, 'line', known, strict=True), value
        assert ground(f'Buyurtma: {value}.', known) == (f'Buyurtma: {value}.', []), value
    assert numbers.values('@aziz_2024 kanaliga yozing') == set(), 'a handle\'s digits are no figure'
    assert ground('Muallif: S.Xolmatov, sh.Chilonzor', trusting('S.Xolmatov, sh.Chilonzor')) == (
        'Muallif: S.Xolmatov, sh.Chilonzor', []), 'an initial or an abbreviation before a name is no link'


# ---------------------------------------------------------------- class letters (stage-2 re-audit)


@pytest.mark.parametrize('value, repaired', [
    ('7-«B» sinf', '7-sinf'), ('7-B sinf', '7-sinf'), ('7 «B» sinf', '7 sinf'), ('Grade 7B', 'Grade 7'),
    ('7Б класс', '7 класс'),
], ids=['uz-quoted', 'uz-hyphen', 'uz-spaced', 'en', 'ru'])
def test_a_class_letter_the_customer_never_wrote_is_not_theirs(value, repaired):
    known = trusting('7-sinf matematika fanidan dars ishlanmasi yozing.')
    assert not supported(value, 'line', known)
    assert facts.without_class_letters(value, known) == (repaired, True)
    assert facts.without_class_letters(repaired, known) == (repaired, False)


@pytest.mark.parametrize('brief', ['7 «Б» класс, математика', '7b sinf matematika', '7-«B» sinf uchun dars'])
def test_the_customers_own_class_letter_stays_in_either_alphabet(brief):
    assert supported('7-«B» sinf', 'line', trusting(brief))
    assert facts.without_class_letters('7-«B» sinf', trusting(brief)) == ('7-«B» sinf', False)


def test_an_initial_after_a_number_is_no_class_letter():
    known = trusting('7-sinf rahbari Karimova Aziza')
    assert facts.without_class_letters('7-sinf rahbari A. Karimova', known) == ('7-sinf rahbari A. Karimova', False)


# ---------------------------------------------------------------- translated references (stage-2 re-audit)


@pytest.mark.parametrize('item', [
    'Karimov Abdulla. Raqamli marketing strategiyalari. — Toshkent: Fan.',
    'Abdulla Karimov. Raqamli marketing asoslari: darslik.',
    'Marketing asoslari / mas’ul muharrir Saidov B. — T.: Iqtisodiyot.',
    'Kotler, Philip. Marketing Management. Pearson Education.',
    'Philip Kotler and Kevin Keller. Marketing Management. Pearson.',
    'Ryan, Damian. Understanding Digital Marketing. Kogan Page.',
    'Digital Marketing. Edited by D. Chaffey. Pearson.',
], ids=['surname-name', 'name-surname', 'editor-uz', 'surname-comma-name', 'two-full-names', 'ryan', 'editor-en'])
def test_a_translated_source_whose_author_or_editor_is_written_in_full_is_still_held(item):
    known = trusting('Напишите курсовую работу на узбекском языке о цифровом маркетинге.')
    assert verify_items([item], known, translated=True) == ([], ['source:dropped'])


def test_a_translated_source_by_the_customers_author_in_full_stays():
    known = trusting('Источники: Каримов Абдулла, учебник по цифровому маркетингу. Курсовая на узбекском.')
    item = 'Karimov Abdulla. Raqamli marketing strategiyalari.'
    assert verify_items([item], known, translated=True) == ([item], [])


# ---------------------------------------------------------------- names beside figures (stage-2 re-audit)


OFFER_UZ = ('Oqtosh Mebel MChJ nomidan tijorat taklifi. h/r 20208000900123456001, MFO 00440, STIR 301234567, '
            'telefon +998 90 123 45 67.')


@pytest.mark.parametrize('value, kind', [
    ('h/r 20208000900123456001, «Kapitalbank» ATB Toshkent filiali, MFO 00440, STIR 301234567', 'ref'),
    ('+998 90 123 45 67 (Aziz Karimov)', 'phone'),
    ('200 mln so‘m (Hamkorbank krediti)', 'money'),
], ids=['bank-in-requisites', 'person-beside-phone', 'lender-beside-sum'])
def test_a_paper_facts_figure_never_carries_a_name_the_customer_did_not_give(value, kind):
    known = trusting(OFFER_UZ + ' Kredit 200 mln so‘m.')
    assert not supported(value, kind, known, strict=True, words=True)
    assert supported(value, kind, known), 'a deck slot keeps its reading'


@pytest.mark.parametrize('value, kind', [
    ('account 20208000900123456001, Kapitalbank, MFO 00440, TIN 301234567', 'ref'),
    ('Average check UZS 220,000', 'money'), ('As of 30 June', 'date'), ('Mobile: +998 90 123 45 67', 'phone'),
    ('Year 7', 'number'), ('Contract No. 125', 'ref'),
], ids=['requisites', 'label-money', 'label-date', 'label-phone', 'label-number', 'label-ref'])
def test_a_figures_own_label_and_the_customers_bank_stay_in_a_translated_paper(value, kind):
    known = trusting('Коммерческое предложение на английском. Р/с 20208000900123456001, Капиталбанк, МФО 00440, '
                     'ИНН 301234567. Средний чек 220 000 сум. Договор № 125. Год 7. На 30 июня. '
                     'Моб. +998 90 123 45 67.')
    assert supported(value, kind, known, translated=True, strict=True, words=True)


# ---------------------------------------------------------------- what a change reads back (stage-2 re-audit)


PLAN_CHANGE = ('Toshkentda nonvoyxona ochish bo‘yicha biznes-reja yozib bering. Direktor Qodirova Malika. Bankdan '
               '200 mln so‘m kredit olamiz.')


def changed(before, prompt=PLAN_CHANGE, category='pdf.biz.biznes_reja', locale='uz'):
    return facts.trusted({'prompt': prompt, 'output_locale': locale, 'options': {'category': category},
                          'revision': {'request': 'Moliyalashtirish bo‘limini batafsilroq yozing.',
                                       'original_prompt': prompt, 'before': before}})


def test_a_word_no_names_check_read_is_never_read_back_as_the_customers():
    before = {'title': 'Biznes-reja', 'sections': [
        {'id': 'facts', 'layout': 'list', 'items': [
            {'label': 'director', 'text': 'Qodirova Malika'},
            {'label': 'external_funding', 'text': 'Korzinka: 200 mln so‘m'}]},
        {'id': 'finance_sources', 'layout': 'table', 'items': [
            {'label': 'Makro krediti', 'text': '200 mln so‘m', 'value': ''}]},
        {'id': 'summary_lead', 'body': 'Sardor loyihani boshqaradi. Kredit Qodirova Malika nomiga olinadi.'}]}
    known = changed(before)
    for invented in ('Korzinka', 'Makro', 'Sardor'):
        assert not known.person(invented), invented
    assert known.person('Qodirova') and known.person('Malika')
    assert '200000000' in known.values, 'a figure that was checked is still the customer\'s'


def test_a_guarded_papers_topic_and_a_translated_reference_give_back_only_their_figures():
    before = {'title': 'Kurs ishi', 'sections': [
        {'id': 'facts', 'layout': 'list', 'items': [
            {'label': 'topic', 'text': 'Kredit riskini boshqarish («Hamkorbank» ATB misolida), 2024'}]},
        {'id': 'references', 'layout': 'list', 'items': [
            {'label': '', 'text': 'Kichik biznes iqtisodiyoti. Westminster University Press.', 'value': ''}]}]}
    prompt = 'Напишите курсовую работу на узбекском языке о кредитном риске в коммерческих банках.'
    known = changed(before, prompt=prompt, category='pdf.kurs_ishi')
    assert not known.person('Hamkorbank') and not known.person('Westminster')
    assert '2024' in known.values


@pytest.mark.parametrize('text, found', [
    ('Я работал с тремястами клиентами', [('300', 'тремястами')]),
    ('Обслуживал пятистам клиентам, о двухстах заявках', [('500', 'пятистам'), ('200', 'двухстах')]),
    ('Руководил десятком сотрудников', [('10', 'десятком')]),
], ids=['instrumental', 'dative-prepositional', 'a-ten'])
def test_russian_hundreds_in_every_case_and_a_ten_as_a_noun_are_read(text, found):
    assert read(text) == found
    assert read('десятки сотрудников, свою семью') == []


# ---------------------------------------------------------------- what a paper holds again (stage-2 re-audit, round 2)


def test_a_held_name_is_matched_whole_or_with_a_case_ending_never_by_a_prefix():
    held = facts.Named([facts.fold(word) for word in ('Dilnoza', 'Artel', 'Xalq', 'Hamkorbank')])
    for word in ('Dilnoza', 'Dilnozaga', 'Дилнозы', 'Дилнозой', 'Artelda', 'Arteldagi', 'Артелем', "Artel's",
                 'Hamkorbankdan', 'Xalq'):
        assert held.has(facts.fold(word)), word
    for word in ('Xalqaro', 'Artelxona', 'Dilnozaxon', 'Hamkor'):
        assert not held.has(facts.fold(word)), word


@pytest.mark.parametrize('value, kind, held', [
    ('Bosh hisobchi Karimova Dilnoza', 'line', ['karimova', 'dilnoza']),
    ('Rais: Karimov Aziz Bahodirovich', 'line', ['karimov', 'aziz', 'baxodirovich']),
    # A name before its legal form is always a name (round 3: a rejected "Acme LLC" printed "Acme also ..." again).
    ('Xalq banki', 'org', []), ('Westminster University', 'org', []), ('Acme LLC', 'org', ['acme']),
    ('Artel', 'org', ['artel']), ('Hamkorbank', 'org', ['xamkorbank']), ('«Baraka» MChJ', 'org', ['baraka']),
    ('«Baraka» nonvoyxonasi', 'line', ['baraka']), ('Moliya Vazirligi', 'org', []),
    ('Samarqand', 'place', ['samarkand']), ('Malika', 'person', ['malika']),
    ('Artel MChJ', 'org', ['artel']), ('Acme Trading LLC', 'org', ['acme']), ('Aziz Rahim', 'line', ['aziz', 'raxim']),
    ('Dilnoza\nSardor', 'list', ['dilnoza', 'sardor']),
    ('Bosh direktor Karimova Dilnoza', 'person', ['karimova', 'dilnoza']),
], ids=['role-and-person', 'chair', 'bank-of-a-word', 'university', 'llc', 'one-word', 'bank-shape', 'quoted-form',
        'quoted-project', 'ministry', 'city', 'given-name', 'uzbek-form', 'llc-of-two-words', 'a-line-only-a-name',
        'a-list-of-names', 'a-role-before-a-person'])
def test_a_rejected_fact_holds_only_the_words_that_name_someone_wherever_they_stand(value, kind, held):
    known = trusting('Nonvoyxona uchun hujjat yozib bering.')
    assert facts.held_names(value, kind, known) == held


# ---------------------------------------------------------------- laws in other senses (stage-2 re-audit, round 2)


@pytest.mark.parametrize('part', [
    'Экономическое положение Республики Узбекистан улучшилось.',
    'Социально-экономическое положение республики остаётся стабильным.',
    'Министерство экономики изучило положение малого бизнеса.',
    'The Ministry of Economy reports that orders from small firms grew.',
    'Parliament discussed the convention centre project.',
    'Hukumat kichik biznesni qo‘llab-quvvatlash bo‘yicha qator qarorlar qabul qildi.',
    'Respublika iqtisodiyotida nizomlar soddalashtirildi.',
    'ОБЩИЕ ПОЛОЖЕНИЯ',
], ids=['ru-situation', 'ru-situation-lower', 'ru-ministry-situation', 'en-ministry-orders', 'en-convention-centre',
        'uz-government-resolutions', 'uz-plural-regulations', 'ru-general-provisions'])
def test_a_situation_a_plural_act_or_a_convention_centre_is_no_legal_sentence(part):
    assert guard(part, trusting('Iqtisodiyot fanidan kurs ishi yozing.')) == (part, [])


@pytest.mark.parametrize('brief, part', [
    ('Bosh buxgalter uchun lavozim yo‘riqnomasi, Mehnat kodeksiga muvofiq.', 'Ushbu kodeks talablariga rioya qiladi.'),
    ('Bosh buxgalter uchun lavozim yo‘riqnomasi, Mehnat kodeksiga muvofiq.', 'Mazkur kodeksga muvofiq javob beradi.'),
    ('Должностная инструкция по Трудовому кодексу.', 'Настоящий кодекс обязателен для исполнения.'),
    ('A job description under the Labour Code.', 'This Code applies to every employee.'),
], ids=['ushbu', 'mazkur', 'nastoyashchiy', 'this'])
def test_a_code_pointed_at_after_the_customer_named_one_stays(brief, part):
    assert guard(part, trusting(brief)) == (part, [])
    assert ground(part, trusting(brief)) == (part, [])


@pytest.mark.parametrize('part', [
    'Hukumat qarori bilan dastur tasdiqlangan.', 'The Ministry of Public Education order sets the length.',
    'Согласно Положению о школе урок длится 45 минут.', 'Under the Geneva Convention prisoners are protected.',
    'Respublika qonunchiligida nizom № 5 bilan belgilangan.',
], ids=['government-resolution', 'ministry-order', 'ru-polozhenie', 'geneva-convention', 'numbered-nizom'])
def test_an_issuers_act_a_regulation_and_a_convention_are_still_legal_sentences(part):
    assert guard(part, trusting('7-sinf matematika fanidan dars ishlanmasi yozing.')) == ('', ['ground:law'])


# ---------------------------------------------------------------- what no class letter is (stage-2 re-audit, round 2)


@pytest.mark.parametrize('brief, value', [
    ('1С dasturchisi lavozimiga ishga kirish xati kerak.', '1C dasturchisi'),
    ('Нужно сопроводительное письмо, должность: программист 1С.', 'Programmer 1C'),
    ('1C dasturchisi lavozimiga xat.', '1С dasturchisi'),
    ('Buxgalter lavozimi, 1C bilishi kerak.', 'Buxgalter (1C)'),
    ('3D dizayner lavozimiga xat.', '3D dizayner'),
    ('Ofis manzili: Chilonzor 9-kvartal, 12A uy.', 'Chilonzor 9-kvartal, 12A uy'),
], ids=['uz-cyrillic-1c', 'ru-1c', 'latin-given', 'brackets', '3d', 'house'])
def test_a_letter_after_a_number_that_names_no_class_is_kept_whole(brief, value):
    known = trusting(brief)
    assert facts.without_class_letters(value, known) == (value, False)
    assert supported(value, 'line', known, strict=True, words=True)


# The customer's Cyrillic class letter is the Latin one Uzbek writes for it, never the one it looks like (round 3: a
# paper's "7-«B»" passed for the customer's "7 «В»", the third parallel, not the second).
@pytest.mark.parametrize('brief, kept, taken', [
    ('7 «В» класс, математика', 'V', 'B'), ('7С класс, урок', 'S', 'C'), ('7 «Б» класс, математика', 'B', 'V'),
], ids=['ve', 'es', 'be'])
def test_the_customers_class_letter_typed_in_cyrillic_stays_in_latin(brief, kept, taken):
    known = trusting(brief)
    assert facts.without_class_letters(f'7-«{kept}» sinf', known) == (f'7-«{kept}» sinf', False)
    assert facts.without_class_letters(f'7-«{taken}» sinf', known) == ('7-sinf', True)


@pytest.mark.parametrize('value, left', [('7B', '7'), ('7B-sinf', '7-sinf'), ('Year 7B', 'Year 7'), ('7 B', '7')],
                         ids=['bare', 'before-a-hyphenated-class-word', 'after-year', 'bare-spaced'])
def test_an_invented_class_letter_is_taken_however_the_grade_writes_it(value, left):
    assert facts.without_class_letters(value, trusting('7-sinf matematika dars ishlanmasi')) == (left, True)


# ---------------------------------------------------------------- a figure's own labels (stage-2 re-audit, round 2)


REQUISITES_RU = ('Коммерческое предложение на английском. Телефон +998 90 123 45 67. Реквизиты: р/с '
                 '20208000900123456001, АКБ «Капиталбанк», МФО 00440, ИНН 301234567.')


@pytest.mark.parametrize('value, kind', [
    ('Account 20208000900123456001, Kapitalbank JSCB, MFO 00440, TIN 301234567', 'ref'),
    ('Account 20208000900123456001, JSCB Kapitalbank, MFO 00440, TIN 301234567', 'ref'),
    ('Settlement account 20208000900123456001 at Kapitalbank, Bank code (MFO) 00440, TIN 301234567', 'ref'),
    ('Расчётный счёт 20208000900123456001, Банк: АКБ «Капиталбанк», МФО 00440', 'ref'),
    ('+998 90 123 45 67 (mobile, Telegram)', 'phone'),
], ids=['jscb-after', 'jscb-before', 'bank-code', 'ru-bank-label', 'phone-telegram'])
def test_the_customers_bank_details_and_phone_keep_their_labels_in_a_translated_paper(value, kind):
    assert supported(value, kind, trusting(REQUISITES_RU), translated=True, strict=True, words=True)


@pytest.mark.parametrize('value, kind', [
    ('Account 20208000900123456001, Hamkorbank JSCB, MFO 00440, TIN 301234567', 'ref'),
    ('Расчётный счёт 20208000900123456001, Банк: АКБ «Хамкорбанк», МФО 00440', 'ref'),
    ('+998 90 123 45 67 (mobile, Aziz Karimov)', 'phone'),
], ids=['other-bank', 'ru-other-bank', 'phone-person'])
def test_an_invented_bank_or_person_beside_the_customers_figures_is_still_not_theirs(value, kind):
    assert not supported(value, kind, trusting(REQUISITES_RU), translated=True, strict=True, words=True)


# ---------------------------------------------------------------- numbers side by side (stage-2 re-audit, round 2)


@pytest.mark.parametrize('brief, text', [
    ('Team of 10; revenue tripled.', 'Our team of ten tripled revenue.'),
    ('Команда из 10 человек, продажи выросли вдвое.', 'Десять сотрудников вдвое увеличили продажи.'),
    ('Narxi 5000 so‘m.', 'Narxi besh ming bir dona uchun.'),
], ids=['en-tripled', 'ru-vdvoe', 'uz-one-piece'])
def test_a_count_beside_a_multiplier_or_a_counted_one_is_read_apart(brief, text):
    assert guard(text, trusting(brief), checks=('numbers',), words=True) == (text, [])


def test_a_thousand_and_one_is_still_read_whole():
    assert [number.value for number in numbers.found('Ming bir kecha ertaklari.', words=True)] == ['1001']
    assert [number.value for number in numbers.found('Zavodda ming bir xodim ishlaydi.', words=True)] == ['1001']
    assert [number.value for number in numbers.found('Two thousand and one copies.', words=True)] == ['2001']
    assert guard('Our team of ten tripled revenue.', trusting('Team of 12.'), checks=('numbers',), words=True)[1] == [
        'ground:number'], 'an invented count beside a multiplier is still blanked'


# ---------------------------------------------------------------- a name by the kind after it (stage-2 round 4)


@pytest.mark.parametrize('sentence, brief, kept', [
    ('Samarqand shahrida yangi filial ochildi.', 'Kompaniyamiz yillik hisoboti kerak.', False),
    ('Yunusobod tumanida do‘kon ochamiz.', 'Nonvoyxona uchun biznes-reja yozing.', False),
    ('Toshkent shahrida do‘kon ochamiz.', 'Toshkentda nonvoyxona ochmoqchimiz.', True),
    ('Uzum platformasida savdo boshlandi.', 'Kompaniyamiz yillik hisoboti kerak.', False),
    ('Вестминстерский университет принял меня.', 'Напишите сопроводительное письмо, я работала в рознице.', False),
    ('Самаркандский государственный институт принял меня.', 'Напишите письмо, я работала в рознице.', False),
    ('Медицинский институт принял меня.', 'Напишите сопроводительное письмо, я работала в рознице.', True),
    # A plural before a kind is a name as often ("Do‘stlar kompaniyasida"): held, the price of it (owner's tie-break).
    ('Keyslar banki ilovada berilgan.', 'Raqamli marketing mavzusida kurs ishi yozing.', False),
], ids=['uz-city', 'uz-district', 'uz-the-customers-city', 'uz-platform', 'ru-name-adjective',
        'ru-name-adjective-before-another', 'ru-kind-adjective', 'uz-plural-before-a-kind'])
def test_a_first_word_is_a_name_by_the_kind_after_it(sentence, brief, kept):
    from apps.studio.categories import finish
    assert (finish.ground_paper(sentence, trusting(brief))[0] == sentence) is kept
