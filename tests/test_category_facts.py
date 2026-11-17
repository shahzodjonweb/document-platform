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
        {'id': 'facts', 'layout': 'list', 'items': [{'label': 'teacher', 'text': 'Sobirova Gulnora'}]},
        {'id': 'passage', 'heading': 'Matn', 'body': 'Matnni Jumanazarov Bekzod 1987-yilda yozgan. U '
                                                     '«bilim har bir yurtning eng katta boyligi» degan.'}]}
    data = {'prompt': 'Ona tili fanidan test', 'options': {'category': 'pdf.test'},
            'revision': {'request': 'Savollarni ko‘paytiring', 'original_prompt': 'Ona tili fanidan test',
                         'before': before}}
    known = facts.trusted(data)
    # The facts section was held to the customer's words when it was made; the passage is the model's own prose.
    assert supported('Sobirova Gulnora', 'person', known)
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
    assert verify_items(items, known, translated=True) == \
        ([items[0], items[1], items[4]], ['source:dropped'])


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
PLAIN_LINK = (r"(?:https?://|www\.)\S+|\b[\w\-]+(?:\.[\w\-]+)*\.(?:uz|com|ru|org|net|io|me|info|edu|gov)"
              r"(?:/\S*)?(?!\w)")
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
            [m.span() for m in re.finditer(f'{PLAIN_EMAIL}|{PLAIN_LINK}', text, re.IGNORECASE)], text[:80]
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
