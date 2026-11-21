"""The grounding matrix: what a category paper's finish must blank and what it must keep, pinned both ways.

Every case here comes from the stage-2 audits, re-audits and their probes
(people, organisations, places, numbers, dates, quotations, laws, handles,
class letters, references), each in one of three directions:

- `blank`: the model invented it, and it must not reach the paper. The
  `gone` words must be absent from the finished paper (every title, fact,
  heading, body, item and question), or `supported` must refuse the value.
- `keep`: it is the customer's own word, figure, law or label, or an
  ordinary word that names no one; the model's text must come through
  verbatim where it was put.
- `accepted_false_blank`: the owner's tie-break. Where a leak and a false
  blank cannot both be avoided (the same words in the same place play both
  parts), the blank is chosen. The case asserts the blank and names, in
  `pair`, the leak it is the price of. A fix that keeps such a word while its
  pair still blanks is an improvement; it changes the case to `keep` and says
  so. A fix never keeps it by letting the pair leak. An accepted id the core
  list names stays, repointed to the same word where the tie-break still holds
  (`RESTORED`).

Owner's rules the matrix holds: never invent a customer fact on a category
page; when blank and leak collide, blank. Cases run through the calls the
probes used: finish.apply on the shipped entries (a fact, a grounded or
guarded part's body, a list item, a table cell, the title, a test question),
and finish.ground_paper, facts.guard and facts.supported for unit cases.
Ids read lens-what-language-direction. No case is xfail: a failing id is
open work. Every person, organisation, figure and source here is invented.
"""
import copy
import re
from dataclasses import dataclass, replace

import pytest

from apps.studio.categories import catalogue, facts, finish, skeleton

BLANK, KEEP, ACCEPTED = 'blank', 'keep', 'accepted_false_blank'

# The length each entry is seeded at, so the parts the cases write are in the seed.
LENGTHS = {
    'pdf.biz.biznes_reja': 8, 'pdf.biz.hisobot': 3, 'pdf.biz.bayonnoma': 2, 'pdf.biz.lavozim_yoriqnomasi': 2,
    'pdf.biz.tijorat_taklifi': 1, 'pdf.biz.marketing_reja': 5, 'pdf.kurs_ishi': 10, 'pdf.mustaqil_ish': 5,
    'pdf.konspekt': 3, 'pdf.dars_ishlanmasi': 4, 'pdf.test': 2,
}


@dataclass(frozen=True)
class Case:
    id: str
    direction: str
    brief: str
    locale: str
    where: str                 # 'fact:<field>', 'body:<part>', 'item:<part>', 'cell:<part>', 'title', 'question'
    value: object              # the model's value, sentence, cell or question
    entry: str = ''            # a catalogue id for finish.apply; '' for a unit case
    call: str = ''             # a unit case's call: 'ground_paper', 'guard', 'supported:<kind>'
    gone: tuple = ()
    translated: object = None  # the finish's reading of the brief against the paper's language, asserted first
    facts: tuple = ()          # other facts the model wrote: ((field, value), ...)
    parts: tuple = ()          # other sections the model wrote: ((part, {key: value}), ...)
    row: tuple = ('', '')      # a table cell's row: (text, value) beside the label
    pair: str = ''             # an accepted_false_blank's leak case

    def __str__(self):
        return self.id


def fact(id, direction, entry, brief, locale, field_id, value, **more):
    return Case(id, direction, brief, locale, f'fact:{field_id}', value, entry=entry, **more)


def body(id, direction, entry, brief, locale, part_id, value, **more):
    return Case(id, direction, brief, locale, f'body:{part_id}', value, entry=entry, **more)


def item(id, direction, entry, brief, locale, part_id, value, **more):
    return Case(id, direction, brief, locale, f'item:{part_id}', value, entry=entry, **more)


def cell(id, direction, entry, brief, locale, part_id, value, **more):
    return Case(id, direction, brief, locale, f'cell:{part_id}', value, entry=entry, **more)


def title(id, direction, entry, brief, locale, value, **more):
    return Case(id, direction, brief, locale, 'title', value, entry=entry, **more)


def question(id, direction, entry, brief, locale, value, **more):
    return Case(id, direction, brief, locale, 'question', value, entry=entry, **more)


def gp(id, direction, brief, locale, value, **more):
    return Case(id, direction, brief, locale, 'text', value, call='ground_paper', **more)


def guard(id, direction, brief, locale, value, **more):
    return Case(id, direction, brief, locale, 'text', value, call='guard', **more)


def supported(id, direction, brief, locale, kind, value, **more):
    return Case(id, direction, brief, locale, 'value', value, call=f'supported:{kind}', **more)


def removed(keep, gone, pair, listed=False):
    """The cases a keep becomes once the exemption it was made for is removed (round 5, the owner's decision: four
    exemptions kept leaking paraphrases, so a position at the company, a place of work, the idiom "birinchi o‘rinni
    egallaydi" and a technology token are read as c491da9 reads them). The model's words are an accepted false blank
    paid for by `pair`, a blank case c491da9 blanks too. A keep id the core list names (`listed`) still exists,
    repointed to the customer's own words: their brief says the same, and the paper keeps it."""
    said = keep.value if keep.value.endswith('.') else keep.value + '.'
    blank = replace(keep, id=keep.id.removesuffix('-' + KEEP) + '-' + ACCEPTED, direction=ACCEPTED, gone=gone,
                    pair=pair)
    return [replace(keep, brief=f'{keep.brief} {said}'), blank] if listed else [blank]


# ---------------------------------------------------------------- briefs (the customer's messages, from the probes)

COVER_UZ = ('Ishga kirish xati yozing. Ismim Qodirova Malika, sotuv menejeri lavozimiga topshiraman. '
            'Tajribam bor, mijozlar bilan ishlashni yaxshi bilaman.')
COVER_EN = ('Please write a cover letter for the sales manager position for me, Malika Qodirova. I have worked in '
            'retail sales and I am good with customers.')
COVER_RU = ('Напишите сопроводительное письмо на должность менеджера по продажам, я Малика Кодирова, работала '
            'в рознице.')
COVER_UZ_EN = ('Menga ingliz tilida ishga kirish uchun xat yozib bering, sotuv menejeri lavozimiga, men Qodirova '
               'Malika, savdo sohasida ishlaganman va mijozlar bilan ishlashni yaxshi bilaman.')
COVER_UZ_EN_ARTEL = COVER_UZ_EN + ' Xatni Artel kompaniyasiga yuboraman.'
COVER_RU_1C_UZ = ('Напишите сопроводительное письмо на узбекском на должность программиста 1С в компанию. '
                  'Меня зовут Каримов Азиз, опыт работы с 1С три года.')
COVER_RU_1C_EN = ('Напишите сопроводительное письмо на английском на должность программиста 1С. Меня зовут '
                  'Каримов Азиз, работаю в этой сфере давно.')
MOTIVATION_UZ_EN = ('Menga ingliz tilida motivatsion xat yozib bering, chet eldagi universitetga magistraturaga '
                    'kirmoqchiman, iqtisodiyot yo‘nalishi. Ismim Qodirova Malika, Toshkentda bakalavrni tugatganman.')
RECOMMENDATION_EN = ('Please write a recommendation letter for my former student Malika Qodirova, who is applying '
                     'for a master’s programme. I taught her economics at school and she was always the best.')
RECOMMENDATION_UZ_EN = ('Menga ingliz tilida tavsiya xati yozib bering, shogirdim Qodirova Malika magistraturaga '
                        'kirmoqchi, men unga maktabda iqtisodiyot fanidan dars berganman va u eng yaxshi o‘quvchi edi.')
REFERENCE_UZ = ('Qodirova Malika uchun tavsifnoma yozib bering, u 11-sinf o‘quvchisi, olimpiadada qatnashgan, '
                'darslarda faol.')
PLAN_UZ = ('Nonvoyxona ochmoqchiman, biznes reja kerak. Toshkentda, mahallada issiq non sotamiz. '
           'O‘z mablag‘im 200 mln so‘m, kredit 200 mln so‘m olaman. Direktor Qodirova Malika.')
PLAN_COMPETITORS_UZ = ('Toshkentda nonvoyxona ochish bo‘yicha biznes-reja yozib bering. Mahalla aholisiga issiq non '
                       'va somsa sotamiz. Raqobatchilar: yaqin atrofdagi do‘konlar va supermarketlar. Xodimlar: '
                       'novvoy, sotuvchi, kassir. Direktor Qodirova Malika. O‘z mablag‘imiz 120 mln so‘m, bankdan '
                       '200 mln so‘m kredit olmoqchimiz. Ijara oyiga 5 mln so‘m.')
PLAN_RU_EN = ('Напишите бизнес-план пекарни в Ташкенте на английском языке. Собственные средства 120 млн сумов, '
              'кредит 200 млн сумов, аренда 5 млн сумов в месяц.')
PLAN_EN = 'Write a business plan for a bakery in Tashkent. Own funds 120 million soums, a loan of 200 million soums.'
REPORT_UZ = ('Kompaniyamizning 2025-yil faoliyati bo‘yicha yillik hisobot yozing. Sotuv 1,2 mlrd so‘mga yetdi, '
             'yangi filial ochildi.')
REPORT_RU_EN = 'Напишите отчёт о работе компании за 2025 год на английском. Продажи выросли до 1,2 млрд сумов.'
REPORT_RU = 'Напишите отчёт о работе компании за 2025 год на русском языке. Продажи выросли до 1,2 млрд сумов.'
MINUTES_UZ = 'Ota-onalar majlisi bayonnomasini yozing. Kun tartibi: yangi o‘quv yili, maktab formasi.'
MINUTES_RU_UZ = ('Составьте протокол родительского собрания на узбекском языке. Повестка: новый учебный год, '
                 'школьная форма.')
MINUTES_RU_UZ_NAMED = MINUTES_RU_UZ + ' Председатель Каримов Азиз Баходирович, секретарь Юлдашева Малика.'
JOB_UZ = ('Bosh buxgalter uchun lavozim yo‘riqnomasi tuzib bering. Mehnat kodeksiga muvofiq bo‘lsin, '
          'xodim moliya bo‘limiga bo‘ysunadi.')
JOB_UZ_LAWS = ('Bosh buxgalter uchun lavozim yo‘riqnomasi tuzib bering. Mehnat kodeksi va qonun hujjatlariga muvofiq '
               'ishlaydi, direktorga bo‘ysunadi.')
JOB_UZ_ETHICS = JOB_UZ_LAWS + ' Kasbiy etika va boshqaruv tamoyillariga rioya qiladi.'
JOB_RU = ('Составьте должностную инструкцию главного бухгалтера на русском, в соответствии с Трудовым кодексом, '
          'подчиняется финансовому директору.')
JOB_RU_UZ = JOB_RU.replace('на русском', 'на узбекском')
JOB_RU_UZ_ARTICLE = JOB_RU_UZ + ' Материальная ответственность по статье 214 Трудового кодекса.'
JOB_RU_EN = ('Составьте должностную инструкцию бухгалтера на английском языке, по Трудовому кодексу, '
             'подчиняется директору.')
JOB_RU_EN_LAW = ('Составьте должностную инструкцию бухгалтера на английском языке, по Трудовому кодексу и Закону о '
                 'бухгалтерском учёте.')
JOB_EN_LAW = 'Write a job description for an accountant in line with the Labour Code and the Law on Accounting.'
JOB_EN = 'Write a job description for a chief accountant in line with the Labour Code; reports to the CFO.'
JOB_EN_TAX = 'Write a job description for a lab assistant in line with the Tax Code; reports to the head of the lab.'
JOB_RU_ADMIN = ('Составьте должностную инструкцию кассира на русском, ответственность по Кодексу об административной '
                'ответственности, подчиняется директору.')
JOB_RU_ADMIN_UZ = JOB_RU_ADMIN.replace('на русском', 'на узбекском')
JOB_UZ_CYRILLIC = ('Бош бухгалтер учун лавозим йўриқномаси ёзинг. «Нур» МЧЖ. Меҳнат кодексига мувофиқ ишлайди, '
                   'директорга бўйсунади.')
STATUTE_UZ_CYRILLIC = ('Мактаб ходими учун лавозим йўриқномаси ёзинг. Таълим тўғрисидаги қонунга мувофиқ ишлайди, '
                       'директорга бўйсунади.')
OFFER_UZ = ('Tijorat taklifi yozing. Telefon +998 90 123 45 67. h/r 20208000900123456001, MFO 00440, '
            'STIR 301234567.')
OFFER_UZ_BANK = ('Tijorat taklifi. Telefon +998 90 123 45 67 (Telegram ham bor). Rekvizitlar: h/r '
                 '20208000900123456001, «Kapitalbank» ATB, MFO 00440, STIR 301234567. Shartnoma № 125.')
OFFER_RU_EN = ('Коммерческое предложение на английском. Телефон +998 90 123 45 67. Реквизиты: р/с '
               '20208000900123456001, АКБ «Капиталбанк», МФО 00440, ИНН 301234567.')
OFFER_UZ_RU = ('Menga rus tilida tijorat taklifi yozib bering, biz mebel sotamiz va bizning telefon +998 90 123 45 67. '
               'Rekvizitlar: h/r 20208000900123456001, «Kapitalbank» ATB, MFO 00440, STIR 301234567. Shartnoma № 125 '
               'bo‘yicha ishlaymiz, mijozlar uchun chegirma bor.')
COURSE_UZ = 'Marketing fanidan "Raqamli marketing strategiyalari" mavzusida kurs ishi yozib bering.'
COURSE_UZ_BOOKS = ('Raqamli marketing mavzusida kurs ishi yozing. Adabiyotlar: Karimov A. Raqamli marketing. Toshkent: '
                   'Fan, 2021. Kotler F. Marketing asoslari. Toshkent, 2019.')
COURSE_RU_BOOKS = ('Курсовая работа по маркетингу. Литература: Котлер Ф. Основы маркетинга. М.: Вильямс, 2019. '
                   'Ламбен Ж.-Ж. Менеджмент, ориентированный на рынок. СПб.: Питер, 2018.')
COURSE_RU_UZ = ('Напишите, пожалуйста, курсовую работу по маркетингу на тему «Стратегии цифрового маркетинга», '
                'на узбекском языке, объём около двадцати страниц.')
COURSE_RU_UZ_UNIVERSITY = ('Напишите курсовую работу по экономике на узбекском языке, я учусь в Образцовом '
                           'государственном университете, тема: развитие малого бизнеса в регионах.')
COURSE_RU_UZ_NAMED = ('Курсовая работа на узбекском языке по маркетингу. Литература: Каримов Абдулла. Стратегии '
                      'цифрового маркетинга. Ташкент: Фан.')
ESSAY_RU_EN = ('Напишите, пожалуйста, самостоятельную работу по теме цифрового маркетинга на английском, для '
               'студентов, примерно десять страниц.')
ESSAY_RU_EN_NAMED = ('Напишите самостоятельную работу на английском по цифровому маркетингу. Источники: Котлер '
                     'Филип. Маркетинг менеджмент.')
LESSON_UZ = '7-sinf matematika fanidan "Kasrlarni qo‘shish" mavzusida dars ishlanmasi tuzing.'
LESSON_RU_EN = 'Составьте план урока математики на английском языке для 7 класса, тема: сложение дробей.'
LESSON_RU_V = 'Составьте план урока математики на узбекском языке для 7 «В» класса, тема: сложение дробей.'
UZ_NONE = 'Nonvoyxona uchun biznes-reja yozing. Issiq non sotamiz.'
RU_NONE = 'Напишите сопроводительное письмо менеджера по продажам, я работала в рознице.'
EN_NONE = 'Write a cover letter for a sales manager; I worked in retail.'
PLAN_RU = ('Напишите бизнес-план пекарни в Ташкенте на русском языке. Собственные средства 120 млн сумов, кредит '
           '200 млн сумов.')
APPLICATION_UZ_RU = ('Menga rus tilida ariza yozib bering, men bu kompaniyada buxgalter bo‘lib ishlayman, menga ta’til '
                     'kerak, ismim Qodirova Malika va men direktor nomiga yozaman.')
LESSON_UZ_RU = ('Menga rus tilida 7-sinf uchun matematika fanidan dars ishlanmasi tuzib bering, mavzu kasrlarni '
                'qo‘shish bo‘lsin va dars 45 daqiqa davom etadi.')
ECONOMICS = {'uz': 'Iqtisodiyot bo‘yicha mustaqil ish yozing.', 'ru': 'Курсовая работа по экономике.',
             'en': 'Course paper in economics: small business development in Uzbekistan.'}


# ---------------------------------------------------------------- the cases

CASES = [
    # ---- A paper in another language than the message still holds the names of its facts (first audit must-fix 1).
    fact('translated-minutes-chair-ru-to-uz-blank', BLANK, 'pdf.biz.bayonnoma', MINUTES_RU_UZ, 'uz', 'chair',
         'Rais: Karimov Aziz Bahodirovich', gone=('Karimov', 'Aziz'), translated=True),
    fact('translated-minutes-secretary-ru-to-uz-blank', BLANK, 'pdf.biz.bayonnoma', MINUTES_RU_UZ, 'uz', 'secretary',
         'Kotiba: Yo‘ldosheva Malika', gone=('Yo‘ldosheva',), translated=True),
    fact('translated-minutes-participants-ru-to-uz-blank', BLANK, 'pdf.biz.bayonnoma', MINUTES_RU_UZ, 'uz',
         'participants', 'Rahimov B.\nSaidova D.', gone=('Rahimov', 'Saidova'), translated=True),
    fact('translated-minutes-organisation-ru-to-uz-blank', BLANK, 'pdf.biz.bayonnoma', MINUTES_RU_UZ, 'uz',
         'organisation', '«Ziyo» xususiy maktabi', gone=('Ziyo',), translated=True),
    fact('translated-minutes-place-ru-to-uz-blank', BLANK, 'pdf.biz.bayonnoma', MINUTES_RU_UZ, 'uz', 'meeting_place',
         'Yunusobod tumani, majlislar zali', gone=('Yunusobod',), translated=True),
    fact('translated-report-author-ru-to-en-blank', BLANK, 'pdf.biz.hisobot', REPORT_RU_EN, 'en', 'author',
         'John Smith, Head of Sales', gone=('Smith',), translated=True),
    fact('translated-report-signers-ru-to-en-blank', BLANK, 'pdf.biz.hisobot', REPORT_RU_EN, 'en', 'signers',
         'Director | Peter Brown', gone=('Brown',), translated=True),
    fact('translated-report-organization-ru-to-en-blank', BLANK, 'pdf.biz.hisobot', REPORT_RU_EN, 'en',
         'organization', 'Acme Trading LLC', gone=('Acme',), translated=True),
    fact('translated-course-university-ru-to-uz-blank', BLANK, 'pdf.kurs_ishi', COURSE_RU_UZ, 'uz', 'university',
         'Westminster xalqaro universiteti', gone=('Westminster',), translated=True),
    fact('translated-course-kafedra-ru-to-uz-blank', BLANK, 'pdf.kurs_ishi', COURSE_RU_UZ, 'uz', 'kafedra',
         'Raqamli iqtisodiyot kafedrasi', gone=('Raqamli iqtisodiyot',), translated=True),
    fact('translated-cover-salutation-uz-to-en-blank', BLANK, 'pdf.xat.ishga_kirish', COVER_UZ_EN, 'en',
         'salutation', 'Dear Mr. Johnson,', gone=('Johnson',), translated=True),
    fact('translated-cover-employer-uz-to-en-blank', BLANK, 'pdf.xat.ishga_kirish', COVER_UZ_EN, 'en',
         'employer_name', 'Deloitte Uzbekistan LLC', gone=('Deloitte',), translated=True),
    fact('translated-cover-recipient-title-uz-to-en-blank', BLANK, 'pdf.xat.ishga_kirish', COVER_UZ_EN, 'en',
         'recipient_title', 'HR Director, Deloitte', gone=('Deloitte',), translated=True),
    fact('facts-recommendation-addressee-never-given-en-blank', BLANK, 'pdf.xat.tavsiya', RECOMMENDATION_EN, 'en',
         'addressee', 'Admissions Committee, University of Westminster', gone=('Westminster',), translated=False),
    fact('translated-recommendation-second-signer-uz-to-en-blank', BLANK, 'pdf.xat.tavsiya', RECOMMENDATION_UZ_EN,
         'en', 'second_signer', 'Dean | Prof. Peter Brown', gone=('Brown',), translated=True),
    fact('translated-minutes-chair-named-in-cyrillic-ru-to-uz-keep', KEEP, 'pdf.biz.bayonnoma', MINUTES_RU_UZ_NAMED,
         'uz', 'chair', 'Karimov Aziz Bahodirovich', translated=True),
    fact('translated-minutes-secretary-respelled-ru-to-uz-keep', KEEP, 'pdf.biz.bayonnoma', MINUTES_RU_UZ_NAMED,
         'uz', 'secretary', 'Yo‘ldosheva Malika', translated=True),
    fact('translated-cover-employer-named-in-latin-uz-to-en-keep', KEEP, 'pdf.xat.ishga_kirish', COVER_UZ_EN_ARTEL,
         'en', 'employer_name', 'Artel', translated=True),
    fact('translated-cover-dear-hiring-manager-uz-to-en-keep', KEEP, 'pdf.xat.ishga_kirish', COVER_UZ_EN, 'en',
         'salutation', 'Dear Hiring Manager,', translated=True),
    fact('translated-application-addressee-person-uz-to-ru-blank', BLANK, 'pdf.xat.ariza', APPLICATION_UZ_RU, 'ru',
         'addressee_person', 'Иванов Пётр Сергеевич', gone=('Иванов',), translated=True),
    fact('translated-application-applicant-respelled-uz-to-ru-keep', KEEP, 'pdf.xat.ariza', APPLICATION_UZ_RU, 'ru',
         'applicant_name', 'Кодирова Малика', translated=True),
    # The owner accepts it (53f3227): a translated organisation whose words do not fold to the customer's.
    fact('translated-university-not-folding-ru-to-uz-accepted_false_blank', ACCEPTED, 'pdf.kurs_ishi',
         COURSE_RU_UZ_UNIVERSITY, 'uz', 'university', 'Namunaviy davlat universiteti', gone=('Namunaviy',),
         translated=True, pair='translated-course-university-ru-to-uz-blank'),

    # ---- Numbers written as words (first audit must-fix 2, 9f77149).
    body('numbers-spelled-five-years-and-a-third-en-blank', BLANK, 'pdf.xat.ishga_kirish', COVER_EN, 'en', 'fit',
         'With over five years of experience in sales, I increased revenue by a third.', gone=('five', 'a third')),
    body('numbers-spelled-twelve-people-two-hundred-clients-en-blank', BLANK, 'pdf.xat.ishga_kirish', COVER_EN, 'en',
         'fit', 'I led a team of twelve people and served two hundred clients a month.',
         gone=('twelve', 'two hundred')),
    body('numbers-spelled-project-cost-uz-blank', BLANK, 'pdf.biz.biznes_reja', PLAN_UZ, 'uz', 'summary_lead',
         'Loyihaning umumiy qiymati besh yuz million so‘mni tashkil etadi.', gone=('besh yuz',)),
    body('numbers-spelled-loan-rate-uz-blank', BLANK, 'pdf.biz.biznes_reja', PLAN_UZ, 'uz', 'summary_lead',
         'Kredit yillik yigirma foiz stavkada olinadi.', gone=('yigirma',)),
    body('numbers-spelled-payback-uz-blank', BLANK, 'pdf.biz.biznes_reja', PLAN_UZ, 'uz', 'summary_lead',
         'Loyiha uch yilda o‘zini qoplaydi.', gone=('uch yilda',)),
    body('numbers-spelled-experience-ru-blank', BLANK, 'pdf.xat.ishga_kirish', COVER_RU, 'ru', 'fit',
         'У меня более пяти лет опыта в продажах.', gone=('пяти',)),
    fact('numbers-spelled-experience-fact-en-blank', BLANK, 'pdf.xat.ishga_kirish', COVER_EN, 'en',
         'experience_facts', 'Five years of retail sales experience', gone=('Five',)),
    gp('numbers-spelled-customer-gave-digits-en-keep', KEEP, 'I have 5 years of experience. Write a cover letter.',
       'en', 'I have five years of experience.'),
    gp('numbers-spelled-customer-gave-words-uz-keep', KEEP, 'Korxonada yigirma besh nafar xodim bor.', 'uz',
       'Korxonada 25 nafar xodim ishlaydi.'),
    gp('numbers-spelled-customer-gave-digits-ru-keep', KEEP, 'Опыт 5 лет, команда 12 человек.', 'ru',
       'Команда из двенадцати человек.'),
    gp('numbers-yuz-berdi-is-no-number-uz-keep', KEEP, PLAN_UZ, 'uz', 'Savdoda qiyinchiliklar yuz berdi.'),
    gp('numbers-a-third-option-and-third-party-en-keep', KEEP, COVER_EN, 'en',
       'We chose a third option with a third-party supplier.'),
    gp('numbers-both-is-no-number-en-keep', KEEP, COVER_EN, 'en', 'Both of my teams met the plan.'),
    gp('numbers-ikkala-is-no-number-uz-keep', KEEP, PLAN_UZ, 'uz', 'Ikkala filial ham ishlaydi.'),
    gp('numbers-semyu-is-family-ru-keep', KEEP, COVER_RU, 'ru', 'Я поддерживаю семью и работаю в рознице.'),

    # ---- The common spoken forms of a figure (judge: spelled-misses, 74338ad, 8146b7c).
    gp('numbers-spelled-compound-count-uz-blank', BLANK, UZ_NONE, 'uz', 'Bizda o‘ttiz besh nafar xodim bor.',
       gone=('o‘ttiz besh',)),
    gp('numbers-spelled-tadan-ending-uz-blank', BLANK, UZ_NONE, 'uz', 'Yigirmatadan ortiq mijoz keladi.',
       gone=('Yigirmatadan',)),
    gp('numbers-bare-ming-with-ending-uz-blank', BLANK, UZ_NONE, 'uz', 'Mingdan ortiq mijozimiz bor.',
       gone=('Mingdan',)),
    gp('numbers-and-a-half-yarim-uz-blank', BLANK, UZ_NONE, 'uz', 'Loyiha uch yarim yilda qoplanadi.',
       gone=('uch yarim',)),
    gp('numbers-half-a-billion-uz-blank', BLANK, UZ_NONE, 'uz', 'Loyihaning umumiy qiymati yarim milliard so‘m.',
       gone=('yarim milliard',)),
    gp('numbers-fused-letniy-ru-blank', BLANK, RU_NONE, 'ru', 'У меня более чем пятилетний опыт работы в продажах.',
       gone=('пятилетний',)),
    gp('numbers-pol-million-ru-blank', BLANK, RU_NONE, 'ru', 'Оборот моего отдела превысил полмиллиона долларов.',
       gone=('полмиллиона',)),
    gp('numbers-multiplier-vdvoe-ru-blank', BLANK, RU_NONE, 'ru', 'Продажи выросли вдвое.', gone=('вдвое',)),
    gp('numbers-genitive-count-ru-blank', BLANK, RU_NONE, 'ru', 'Я руководила командой из двенадцати человек.',
       gone=('двенадцати',)),
    gp('numbers-multiplier-doubled-en-blank', BLANK, EN_NONE, 'en', 'I doubled sales in my region.',
       gone=('doubled',)),
    gp('numbers-half-a-dozen-en-blank', BLANK, EN_NONE, 'en', 'I led half a dozen projects.', gone=('dozen',)),
    gp('numbers-a-decade-en-blank', BLANK, EN_NONE, 'en', 'I have over a decade of experience.', gone=('decade',)),
    gp('numbers-hyphenated-hundred-en-blank', BLANK, EN_NONE, 'en', 'I served two-hundred clients.',
       gone=('two-hundred',)),
    gp('numbers-spelled-counts-the-customer-gave-uz-keep', KEEP, 'Bizda 35 nafar xodim bor, 1000 dan ortiq mijoz.',
       'uz', 'Bizda o‘ttiz besh nafar xodim, mingdan ortiq mijoz bor.'),
    gp('numbers-fused-letniy-the-customer-gave-ru-keep', KEEP, 'Опыт 5 лет, команда 12 человек.', 'ru',
       'Пятилетний опыт, команда из двенадцати человек.'),
    gp('numbers-doubled-the-customer-gave-en-keep', KEEP, 'Grew sales 2x. Write a cover letter for me.', 'en',
       'I doubled sales.'),
    gp('numbers-loan-terms-the-customer-gave-uz-keep', KEEP, 'Kredit 12 oyga, 6 oy imtiyozli davr.', 'uz',
       'Kredit o‘n ikki oyga, olti oylik imtiyoz bilan.'),

    # ---- Number words side by side: a multiplier, a price's "per one", a compound (ce17868, 74338ad).
    gp('numbers-count-beside-multiplier-en-keep', KEEP, 'Team of 10; revenue tripled.', 'en',
       'Our team of ten tripled revenue.'),
    gp('numbers-price-per-one-uz-keep', KEEP, 'Narxi 5000 so‘m.', 'uz', 'Narxi besh ming bir dona uchun.'),
    gp('numbers-thousand-and-one-uz-keep', KEEP, 'Korxonada 1001 xodim bor.', 'uz',
       'Korxonada ming bir xodim ishlaydi.'),
    gp('numbers-hundred-fifty-uz-keep', KEEP, 'Xodimlar soni 150 nafar.', 'uz',
       'Korxonada yuz ellik nafar xodim ishlaydi.'),
    gp('numbers-nine-thousand-one-ru-keep', KEEP, 'Сумма 9001 рубль.', 'ru', 'Сумма девять тысяч один рубль.'),
    gp('numbers-hundred-and-one-en-keep', KEEP, 'We served 101 clients.', 'en',
       'We served one hundred and one clients.'),
    gp('numbers-teni-is-shade-ru-keep', KEEP, 'Отчёт о работе отдела за год.', 'ru',
       'Сотрудники отдыхали в тени деревьев.'),
    gp('numbers-thirteen-beside-multiplier-en-blank', BLANK, 'Team of 10. Write a cover letter.', 'en',
       'Our team of thirteen tripled revenue.', gone=('thirteen',)),
    gp('numbers-hundred-fifty-not-fifty-uz-blank', BLANK, 'Xodimlar 50 nafar.', 'uz',
       'Korxonada yuz ellik nafar xodim ishlaydi.', gone=('yuz ellik',)),
    gp('numbers-hundred-and-one-not-hundred-en-blank', BLANK, 'We had 100 clients.', 'en',
       'We served one hundred and one clients.', gone=('one hundred and one',)),
    gp('numbers-thirty-one-not-thirty-uz-blank', BLANK, 'Xodimlar 30 ta.', 'uz', 'Korxonada o‘ttiz birta xodim bor.',
       gone=('o‘ttiz birta',)),
    gp('numbers-nine-thousand-one-not-nine-thousand-ru-blank', BLANK, 'Сумма 9000 рублей.', 'ru',
       'Сумма девять тысяч один рубль.', gone=('девять тысяч один',)),
    # A long run of multipliers in what the customer pasted is read without failing the paper (multiplier-overflow).
    gp('numbers-a-long-run-of-number-words-the-customer-pasted-uz-keep', KEEP,
       PLAN_UZ + ' bir ' + 'yuz ' * 2300, 'uz', 'Kredit 200 mln so‘m olinadi.'),

    # ---- A scale written short or glued to a currency (de4c591).
    gp('numbers-scale-glued-million-en-blank', BLANK, 'Our team has 3 people.', 'en', 'We raised $3M last year.',
       gone=('$3M',)),
    gp('numbers-scale-bn-en-blank', BLANK, 'I raised 1.2 million dollars.', 'en', 'I raised $1.2bn.',
       gone=('1.2bn',)),
    gp('numbers-scale-mlrd-uz-blank', BLANK, 'Narx 1,5 mln so‘m.', 'uz', 'Narx 1,5 mlrd so‘m.', gone=('1,5 mlrd',)),
    gp('numbers-scale-mlrd-ru-blank', BLANK, 'Цена 1,5 млн сумов за партию.', 'ru', 'Цена 1,5 млрд сумов за партию.',
       gone=('1,5 млрд',)),
    gp('numbers-scale-written-out-en-keep', KEEP, 'We need $2M.', 'en', 'We need 2 million dollars.'),
    gp('numbers-scale-glued-euro-en-keep', KEEP, 'We need 3 million euros.', 'en', 'We need €3m.'),
    gp('numbers-metres-are-no-scale-uz-keep', KEEP, 'Yugurish 100 m masofaga.', 'uz',
       'O‘quvchilar 100 m masofaga yuguradi.'),
    gp('numbers-mln-for-digits-uz-keep', KEEP, 'Kredit 1 500 000 so‘m.', 'uz', 'Kredit 1,5 mln so‘m.'),
    gp('numbers-mln-for-digits-ru-keep', KEEP, 'Кредит 1 500 000 сумов на два года.', 'ru',
       'Кредит 1,5 млн сумов на два года.'),
    gp('numbers-class-9b-is-no-scale-uz-keep', KEEP, '9B sinf uchun dars.', 'uz', '9B sinf o‘quvchilari.'),

    # ---- Ordinals: a ten is no count of its own (judge: ordinals); a placing or a run of years is a figure.
    body('numbers-twenty-first-century-en-keep', KEEP, 'pdf.xat.ishga_kirish', COVER_EN, 'en', 'fit',
         'I bring twenty-first century skills to the team.'),
    gp('numbers-twenty-first-century-uz-keep', KEEP, MOTIVATION_UZ_EN, 'uz',
       'Yigirma birinchi asr ko‘nikmalari muhim.'),
    gp('numbers-twenty-first-century-ru-keep', KEEP, RU_NONE, 'ru', 'В двадцать первом веке навыки важны.'),
    body('numbers-ordinal-the-customer-gave-uz-keep', KEEP, 'pdf.xat.tavsifnoma', REFERENCE_UZ, 'uz', 'achievements',
         'U o‘n birinchi sinf o‘quvchisi sifatida faol.'),
    body('numbers-ordinal-placing-uz-blank', BLANK, 'pdf.xat.tavsifnoma', REFERENCE_UZ, 'uz', 'achievements',
         'U olimpiadada ikkinchi o‘rinni egalladi.', gone=('ikkinchi',)),
    body('numbers-digit-placing-uz-blank', BLANK, 'pdf.xat.tavsifnoma', REFERENCE_UZ, 'uz', 'achievements',
         'U olimpiadada 2-o‘rinni egalladi.', gone=('2-o‘rin',)),
    body('numbers-ordinal-placing-en-blank', BLANK, 'pdf.xat.ishga_kirish', COVER_EN, 'en', 'fit',
         'I won first place in the regional sales contest.', gone=('first place',)),
    body('numbers-ordinal-years-running-en-blank', BLANK, 'pdf.xat.ishga_kirish', COVER_EN, 'en', 'fit',
         'For the fifth consecutive year I was the top seller.', gone=('fifth',)),
    body('numbers-ordinal-years-running-ru-blank', BLANK, 'pdf.xat.ishga_kirish', COVER_RU, 'ru', 'fit',
         'Пятый год подряд я лучший продавец магазина.', gone=('Пятый',)),
    # A placing is read with its verb or case, never the locative idioms "birinchi o‘rinda", "на первом месте", a
    # "first position" or "the first place I worked", nor a modal "may" as a month (round 2 of the convergence).
    gp('numbers-ordinal-placing-with-sazovor-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Shahar olimpiadasida ikkinchi o‘ringa sazovor bo‘ldi.', gone=('ikkinchi',)),
    gp('numbers-ordinal-placing-bare-in-a-list-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Tuman olimpiadasi — ikkinchi o‘rin.', gone=('ikkinchi',)),
    gp('numbers-ordinal-placing-with-its-verb-ru-blank', BLANK, COVER_RU, 'ru', 'Я заняла второе место в конкурсе.',
       gone=('второе',)),
    gp('numbers-ordinal-placing-with-took-en-blank', BLANK, COVER_EN, 'en', 'I took second place in the city contest.',
       gone=('second',)),
    gp('numbers-ordinal-prize-en-blank', BLANK, COVER_EN, 'en', 'My team won the first prize at a retail fair.',
       gone=('first',)),
    gp('numbers-first-place-locative-idiom-uz-keep', KEEP, PLAN_UZ, 'uz',
       'Mijozlar ehtiyoji biz uchun birinchi o‘rinda turadi.'),
    gp('numbers-first-place-dative-idiom-uz-keep', KEEP, PLAN_UZ, 'uz', 'Sifat birinchi o‘ringa qo‘yiladi.'),
    body('numbers-first-place-idiom-opening-a-letter-sentence-uz-keep', KEEP, 'pdf.xat.ishga_kirish', COVER_UZ, 'uz',
         'fit', 'Birinchi o‘rinda mijozlar bilan ishlash tajribam haqida aytmoqchiman.'),
    gp('numbers-first-place-locative-idiom-ru-keep', KEEP,
       'Напишите бизнес-план пекарни в Ташкенте. Собственные средства 120 млн сумов.', 'ru',
       'Для нас на первом месте качество хлеба.'),
    gp('numbers-first-position-en-keep', KEEP, COVER_EN, 'en',
       'In my first position as a sales assistant, I learned to listen to customers.'),
    gp('numbers-the-first-place-i-worked-en-keep', KEEP, COVER_EN, 'en', 'The first place I worked was a small shop.'),
    gp('numbers-the-first-may-seem-harder-en-keep', KEEP, COVER_EN, 'en', 'The first may seem harder, but it pays off.'),
    gp('numbers-the-first-may-reduce-costs-en-keep', KEEP, COVER_EN, 'en',
       'Of the options, the first may reduce costs and the second may raise sales.'),
    gp('numbers-ordinal-day-of-may-in-lower-case-en-blank', BLANK, 'The meeting is on 12 May.', 'en',
       'The meeting is on the fifteenth of may.', gone=('fifteenth',)),
    # A bare "first place" or "first position" places unless "the", "my", "a" or "an" stands before it, and any
    # of them does beside a contest's or a ranking's word; Uzbek "o‘rinda", "o‘ringa" and Russian "на … месте" place
    # beside one (round 3 of the convergence, must: 16b2e75 let these through).
    body('numbers-bare-first-place-opening-an-evidence-sentence-uz-to-en-blank', BLANK, 'pdf.xat.motivatsion',
         MOTIVATION_UZ_EN, 'en', 'evidence',
         'First place in the university economics olympiad. I also led the student debate club.', gone=('First',),
         translated=True),
    body('numbers-her-first-place-at-an-olympiad-en-blank', BLANK, 'pdf.xat.tavsiya', RECOMMENDATION_EN, 'en',
         'evidence', 'Her first place at the city economics olympiad made the whole school proud.', gone=('first',)),
    body('numbers-ordinal-placing-dative-with-chiqdi-beside-an-olympiad-uz-blank', BLANK, 'pdf.xat.tavsifnoma',
         REFERENCE_UZ, 'uz', 'achievements', 'Viloyat fan olimpiadasida ikkinchi o‘ringa chiqdi.', gone=('ikkinchi',)),
    body('numbers-ordinal-placing-locative-beside-an-olympiad-uz-blank', BLANK, 'pdf.xat.tavsifnoma', REFERENCE_UZ,
         'uz', 'achievements', 'Tuman olimpiadasida ikkinchi o‘rinda bo‘ldi.', gone=('ikkinchi',)),
    body('numbers-ordinal-placing-prepositional-in-the-region-ru-blank', BLANK, 'pdf.xat.ishga_kirish', COVER_RU, 'ru',
         'fit', 'По итогам 2023 года мой магазин оказался на первом месте в регионе по продажам.', gone=('первом',)),
    gp('numbers-bare-first-place-in-a-list-line-en-blank', BLANK, RECOMMENDATION_EN, 'en',
       'First place, Regional Economics Olympiad, 2022.', gone=('First',)),
    gp('numbers-winner-of-first-place-en-blank', BLANK, RECOMMENDATION_EN, 'en',
       'She was the winner of first place in the city olympiad.', gone=('first',)),
    gp('numbers-held-first-position-in-regional-sales-en-blank', BLANK, COVER_EN, 'en',
       'My store held first position in regional sales for 2023.', gone=('first',)),
    gp('numbers-the-first-place-at-an-olympiad-en-blank', BLANK, RECOMMENDATION_EN, 'en',
       'The first place at the regional olympiad went to her.', gone=('first',)),
    gp('numbers-ranked-first-en-blank', BLANK, RECOMMENDATION_EN, 'en', 'She ranked first among her classmates.',
       gone=('first',)),
    gp('numbers-placed-second-en-blank', BLANK, RECOMMENDATION_EN, 'en', 'She placed second at the national olympiad.',
       gone=('second',)),
    gp('numbers-a-first-place-finish-en-blank', BLANK, RECOMMENDATION_EN, 'en',
       'She secured a first-place finish at the olympiad.', gone=('first',)),
    gp('numbers-in-the-first-place-idiom-en-keep', KEEP, COVER_EN, 'en',
       'I applied in the first place because I love sales.'),
    gp('numbers-my-first-position-as-en-keep', KEEP, COVER_EN, 'en', 'My first position was a cashier at a mall.'),
    gp('numbers-came-first-idiom-en-keep', KEEP, COVER_EN, 'en', 'For me the customer always came first.'),
    # The idiom and the placing in the same words beside a contest's word: only the contest tells them, so blank.
    gp('numbers-first-place-locative-idiom-beside-an-olympiad-uz-accepted_false_blank', ACCEPTED, REFERENCE_UZ, 'uz',
       'Olimpiadaga tayyorlanishda u uchun bilim birinchi o‘rinda turadi.', gone=('birinchi',),
       pair='numbers-ordinal-placing-locative-beside-an-olympiad-uz-blank'),
    gp('numbers-first-place-prepositional-idiom-beside-a-contest-ru-accepted_false_blank', ACCEPTED, COVER_RU, 'ru',
       'В любом конкурсе для меня на первом месте честность.', gone=('первом',),
       pair='numbers-ordinal-placing-prepositional-in-the-region-ru-blank'),
    gp('numbers-the-first-place-beside-a-contest-en-accepted_false_blank', ACCEPTED, COVER_EN, 'en',
       'The first place I worked ran a regional sales contest.', gone=('first',),
       pair='numbers-the-first-place-at-an-olympiad-en-blank'),

    # ---- Dates: a day and month the customer gave are not enough when the month or year is the model's.
    fact('dates-numeric-year-from-another-date-uz-blank', BLANK, 'pdf.biz.hisobot',
         'Namuna MChJ savdo bo‘limining 2024-yil faoliyati bo‘yicha hisobot, sanasi 15.01.2025.', 'uz',
         'report_date', '15.01.2024', gone=('15.01.2024',)),
    fact('dates-written-year-from-another-date-uz-blank', BLANK, 'pdf.biz.bayonnoma',
         'Namuna MChJ kuzatuv kengashi majlisi 2025-yil 12-mayda bo‘ldi, 2024-yil natijalari ko‘rildi. Rais Karimov A.',
         'uz', 'meeting_date', '2024-yil 12-may', gone=('2024-yil 12-may',)),
    gp('dates-month-changed-uz-blank', BLANK, 'Majlis 2025-yil 12-may kuni bo‘lib o‘tdi.', 'uz',
       'Majlis 2025-yil 12-mart kuni bo‘lib o‘tdi.', gone=('12-mart',)),
    gp('dates-month-changed-en-blank', BLANK, 'The meeting took place on 12 May 2025.', 'en',
       'The meeting took place on 12 March 2025.', gone=('12 March',)),
    gp('dates-month-changed-ru-blank', BLANK, 'Собрание прошло 12 мая 2025 года.', 'ru',
       'Собрание прошло 12 марта 2025 года.', gone=('12 марта',)),
    gp('dates-spelled-day-uz-blank', BLANK, 'Majlis 12-may kuni bo‘ldi.', 'uz', 'Majlis o‘n beshinchi mayda bo‘ldi.',
       gone=('o‘n beshinchi',)),
    gp('dates-spelled-day-en-blank', BLANK, 'The meeting is on 12 May.', 'en',
       'The meeting is on the fifteenth of May.', gone=('fifteenth',)),
    gp('dates-spelled-day-ru-blank', BLANK, 'Собрание будет 12 мая.', 'ru', 'Собрание будет пятнадцатого мая.',
       gone=('пятнадцатого',)),
    # An Uzbek month is written in lower case: only an English ordinal needs its month capitalised (round 3 of the
    # convergence, from 16b2e75).
    gp('dates-spelled-day-before-a-lower-case-uzbek-month-uz-blank', BLANK, MINUTES_UZ, 'uz',
       'Keyingi majlis beshinchi mart kuni bo‘ladi.', gone=('beshinchi',)),
    gp('dates-spelled-compound-day-before-an-uzbek-month-uz-blank', BLANK, REPORT_UZ, 'uz',
       'Hisobot yigirma beshinchi dekabr kuni tasdiqlandi.', gone=('beshinchi',)),
    body('dates-spelled-day-before-an-uzbek-month-in-a-decision-uz-blank', BLANK, 'pdf.biz.bayonnoma', MINUTES_UZ, 'uz',
         'item_decisions', 'Birinchi sentabrdan boshlab yangi maktab formasi joriy etilsin.', gone=('Birinchi',)),
    gp('dates-the-customers-day-spelled-before-an-uzbek-month-uz-keep', KEEP, 'Keyingi majlis 5-mart kuni bo‘ladi.',
       'uz', 'Keyingi majlis beshinchi mart kuni bo‘ladi.'),
    gp('dates-year-from-another-date-en-blank', BLANK, 'I joined on 1 September 2019 and left on 30 June 2023.', 'en',
       'I joined on 1 September 2023.', gone=('September 2023',)),
    gp('dates-year-from-another-date-ru-blank', BLANK, 'Я работала с 1 сентября 2019 года по 30 июня 2023 года.', 'ru',
       'Я пришла на работу 1 сентября 2023 года.', gone=('1 сентября 2023',)),
    gp('dates-the-customers-date-written-anew-uz-keep', KEEP, 'Majlis 12.05.2025 da bo‘ldi.', 'uz',
       'Majlis 2025-yil 12-may kuni bo‘ldi.'),
    gp('dates-the-customers-date-written-anew-en-keep', KEEP, 'The meeting took place on 12 May 2025.', 'en',
       'The meeting was held on 12 May 2025.'),
    gp('dates-the-customers-date-written-anew-ru-keep', KEEP, 'Собрание прошло 12 мая 2025 года.', 'ru',
       'Собрание состоялось 12 мая 2025 года.'),
    fact('dates-the-customers-numeric-date-uz-keep', KEEP, 'pdf.biz.hisobot',
         'Namuna MChJ savdo bo‘limining 2024-yil faoliyati bo‘yicha hisobot, sanasi 15.01.2025.', 'uz',
         'report_date', '15.01.2025'),

    # ---- An organisation opening a sentence, by its shape, kind or legal form (8656b81, 3b7d121).
    gp('names-bank-shaped-first-word-uz-blank', BLANK, PLAN_UZ, 'uz', 'Hamkorbank 200 mln so‘m kredit beradi.',
       gone=('Hamkorbank',)),
    gp('names-kind-in-the-possessive-bank-uz-blank', BLANK, PLAN_UZ, 'uz', 'Asaka banki 200 mln so‘m kredit beradi.',
       gone=('Asaka',)),
    gp('names-kind-in-the-possessive-company-uz-blank', BLANK, COVER_UZ, 'uz',
       'Artel kompaniyasidagi sotuv menejeri lavozimiga ariza bermoqchiman.', gone=('Artel',)),
    gp('names-kind-in-the-possessive-university-uz-blank', BLANK, COVER_UZ, 'uz',
       'Westminster universitetida o‘qishni xohlayman.', gone=('Westminster',)),
    gp('names-chain-before-tarmogi-uz-blank', BLANK, COVER_UZ, 'uz', 'Korzinka supermarketlar tarmog‘ida ishlaganman.',
       gone=('Korzinka',)),
    gp('names-quoted-name-before-form-uz-blank', BLANK, PLAN_UZ, 'uz', '«Baraka» MChJ yangi filial ochdi.',
       gone=('Baraka',)),
    gp('names-name-before-bare-form-uz-blank', BLANK, PLAN_UZ, 'uz', 'Baraka MChJ non ishlab chiqaradi.',
       gone=('Baraka',)),
    gp('names-name-before-title-case-kind-uz-blank', BLANK, PLAN_UZ, 'uz', 'Uzum Market orqali sotamiz.',
       gone=('Uzum',)),
    gp('names-name-before-kind-en-blank', BLANK, MOTIVATION_UZ_EN, 'en',
       'Westminster University has long been the place for me.', gone=('Westminster',)),
    gp('names-name-before-form-en-blank', BLANK, REPORT_RU_EN, 'en', 'Acme LLC increased sales.', gone=('Acme',)),
    gp('names-name-before-lowercase-kind-ru-blank', BLANK, RU_NONE, 'ru', 'Вестминстерский университет принял меня.',
       gone=('Вестминстерский',)),
    gp('names-a-kind-of-bank-is-no-name-uz-keep', KEEP, COVER_UZ, 'uz', 'Tijorat banki bilan ishlaganman.'),
    gp('names-a-state-university-is-no-name-uz-keep', KEEP, COVER_UZ, 'uz', 'Davlat universitetida o‘qiganman.'),
    gp('names-our-company-is-no-name-uz-keep', KEEP, PLAN_UZ, 'uz', 'Bizning kompaniyamiz yangi filial ochdi.'),
    gp('names-a-bare-kind-is-no-name-uz-keep', KEEP, PLAN_UZ, 'uz', 'Markaziy bank stavkani o‘zgartirdi.'),
    gp('names-a-building-company-is-no-name-uz-keep', KEEP, PLAN_UZ, 'uz',
       'Qurilish kompaniyasi bilan shartnoma tuzamiz.'),
    gp('names-a-bread-factory-is-no-name-uz-keep', KEEP, PLAN_UZ, 'uz', 'Non zavodi qurilmaydi.'),
    # A place or a platform of a kind opens no name (round 2 of the convergence, regression from 7da99e9).
    gp('names-an-education-platform-is-no-name-uz-keep', KEEP, PLAN_UZ, 'uz',
       'Ta’lim platformasi yordamida xodimlar o‘qitiladi.'),
    gp('names-an-online-platform-is-no-name-uz-keep', KEEP, PLAN_UZ, 'uz',
       'Onlayn platformasi orqali sotuv yo‘lga qo‘yiladi.'),
    gp('names-a-digital-platform-is-no-name-uz-keep', KEEP, PLAN_UZ, 'uz',
       'Raqamli platformasi orqali buyurtmalar qabul qilinadi.'),
    gp('names-an-industrial-town-is-no-name-uz-keep', KEEP, PLAN_UZ, 'uz', 'Sanoat shahri yaqinida sex joylashgan.'),
    gp('names-a-platforms-name-before-its-kind-uz-blank', BLANK, PLAN_UZ, 'uz', 'Uzum platformasida sotamiz.',
       gone=('Uzum',)),
    gp('names-a-towns-name-before-its-kind-uz-blank', BLANK, PLAN_UZ, 'uz', 'Chirchiq shahrida filial ochamiz.',
       gone=('Chirchiq',)),
    # A plural before an Uzbek kind in the possessive is an organisation's name as often as a common noun's
    # ("Do‘stlar kompaniyasida", "Yoshlar banki"): the run is held (round 2 of the convergence, must, regression from
    # 7da99e9), and a plural common noun before a kind goes with it, the price of it.
    gp('names-plural-name-before-banki-uz-blank', BLANK, PLAN_UZ, 'uz', 'Yoshlar banki 200 mln so‘m kredit beradi.',
       gone=('Yoshlar',)),
    body('names-plural-name-before-kind-in-a-letter-uz-blank', BLANK, 'pdf.xat.ishga_kirish', COVER_UZ, 'uz', 'fit',
         'Do‘stlar kompaniyasida sotuvchi bo‘lib ishlaganman.', gone=('Do‘stlar',),
         facts=(('applicant_name', 'Qodirova Malika'),)),
    body('names-plural-names-before-kinds-in-a-letter-uz-blank', BLANK, 'pdf.xat.ishga_kirish', COVER_UZ, 'uz', 'fit',
         'Yulduzlar supermarketida kassir bo‘lib ishlaganman. Do‘stlar kompaniyasida sotuv bo‘limida tajriba '
         'orttirdim.', gone=('Yulduzlar', 'Do‘stlar'), facts=(('applicant_name', 'Qodirova Malika'),)),
    cell('names-plural-name-before-kind-in-a-competitor-cell-uz-blank', BLANK, 'pdf.biz.biznes_reja', PLAN_UZ, 'uz',
         'market_competitors', 'Do‘stlar supermarketi', row=('', 'Narxlari yuqori'), gone=('Do‘stlar',)),
    gp('names-plural-name-before-zavodida-uz-blank', BLANK, COVER_UZ, 'uz', 'Ustalar zavodida ishlaganman.',
       gone=('Ustalar',)),
    gp('names-plural-name-before-akademiyasida-uz-blank', BLANK, COVER_UZ, 'uz',
       'Yulduzlar akademiyasida malaka oshirganman.', gone=('Yulduzlar',)),
    gp('names-a-plural-noun-before-banki-uz-accepted_false_blank', ACCEPTED, COURSE_UZ, 'uz',
       'Keyslar banki ilovada berilgan.', gone=('Keyslar',), pair='names-plural-name-before-banki-uz-blank'),
    # A plural of people a clinic or a cooperative serves is its kind, never its name ("Bolalar klinikasi", "Fermerlar
    # shirkati"; round 3 of the convergence, should, from 2b740e7); any other plural or kind is still held.
    gp('names-children-before-a-clinic-uz-keep', KEEP, COVER_UZ, 'uz',
       'Bolalar klinikasida hamshira bo‘lib ishlaganman.'),
    gp('names-farmers-before-a-cooperative-uz-keep', KEEP, PLAN_UZ, 'uz', 'Fermerlar shirkati bilan shartnoma tuzamiz.'),
    gp('names-plural-name-before-a-clinic-uz-blank', BLANK, COVER_UZ, 'uz',
       'Do‘stlar klinikasida hamshira bo‘lib ishlaganman.', gone=('Do‘stlar',)),
    gp('names-youth-before-a-bank-uz-blank', BLANK, PLAN_UZ, 'uz', 'Yoshlar banki kredit beradi.', gone=('Yoshlar',)),
    gp('names-children-before-a-company-uz-blank', BLANK, COVER_UZ, 'uz',
       'Bolalar kompaniyasida sotuvchi bo‘lib ishlaganman.', gone=('Bolalar',)),
    # The customer's own plural before a kind is theirs, and stays.
    gp('names-a-plural-noun-before-banki-uz-keep', KEEP, COURSE_UZ + ' Keyslar banki ilovada bo‘lsin.', 'uz',
       'Keyslar banki ilovada berilgan.'),
    gp('names-a-bank-in-lower-case-en-keep', KEEP, PLAN_EN, 'en', 'The bank will lend 200 million soums.'),
    gp('names-a-bank-opening-a-sentence-ru-keep', KEEP, PLAN_RU, 'ru', 'Банк выдаст кредит 200 млн сумов.'),
    gp('names-the-customers-bank-opening-a-sentence-uz-keep', KEEP, PLAN_UZ + ' Kreditni Hamkorbank beradi.', 'uz',
       'Hamkorbank 200 mln so‘m kredit beradi.'),

    # ---- An Uzbek legal form with a case ending is an organisation's (round 3 must, regression from 3b7d121).
    gp('names-form-with-ning-opening-a-sentence-uz-blank', BLANK, PLAN_UZ, 'uz',
       'Baraka MChJning asosiy faoliyati non ishlab chiqarish.', gone=('Baraka',)),
    gp('names-form-with-ga-opening-a-sentence-uz-blank', BLANK, COVER_UZ, 'uz', 'Artel MChJga ariza bermoqchiman.',
       gone=('Artel',)),
    gp('names-quoted-name-before-form-with-ning-uz-blank', BLANK, PLAN_UZ, 'uz',
       '«Baraka» MChJning asosiy faoliyati non ishlab chiqarish.', gone=('Baraka',)),
    gp('names-joint-stock-form-with-ga-uz-blank', BLANK, PLAN_UZ, 'uz', 'Kvarts AJga xomashyo yetkazildi.',
       gone=('Kvarts',)),
    title('names-form-with-ning-in-the-title-uz-blank', BLANK, 'pdf.biz.hisobot',
          'Kompaniyamizning 2025-yil faoliyati bo‘yicha yillik hisobot yozing. Sotuv 1,2 mlrd so‘mga yetdi.', 'uz',
          'Baraka MChJning 2025-yil faoliyati to‘g‘risida hisobot', gone=('Baraka',),
          facts=(('organization', 'Baraka MChJ'),)),
    body('names-form-with-ning-in-a-summary-uz-blank', BLANK, 'pdf.biz.hisobot',
         'Kompaniyamizning 2025-yil faoliyati bo‘yicha yillik hisobot yozing. Sotuv 1,2 mlrd so‘mga yetdi.', 'uz',
         'summary', 'Baraka MChJning 2025-yildagi sotuvi 1,2 mlrd so‘mga yetdi.', gone=('Baraka',),
         facts=(('organization', 'Baraka MChJ'),)),
    item('names-form-with-ga-in-a-list-item-uz-blank', BLANK, 'pdf.biz.hisobot',
         'Kompaniyamizning 2025-yil faoliyati bo‘yicha yillik hisobot yozing. Sotuv 1,2 mlrd so‘mga yetdi.', 'uz',
         'problems', 'Baraka MChJga xomashyo kech yetkazildi.', gone=('Baraka',),
         facts=(('organization', 'Baraka MChJ'),)),
    body('names-form-with-ga-opening-a-letter-uz-blank', BLANK, 'pdf.xat.ishga_kirish', COVER_UZ, 'uz', 'opening',
         'Artel MChJga sotuv menejeri lavozimiga ariza bilan murojaat qilaman.', gone=('Artel',),
         facts=(('applicant_name', 'Qodirova Malika'), ('employer_name', 'Artel MChJ'))),
    cell('names-form-with-ning-in-a-table-cell-uz-blank', BLANK, 'pdf.biz.biznes_reja', PLAN_UZ, 'uz',
         'market_competitors', 'Oqtepa MChJning nonvoyxonasi', row=('', 'Narxlari yuqori'), gone=('Oqtepa',)),
    gp('names-the-customers-form-with-ning-uz-keep', KEEP, PLAN_UZ + ' Korxonamiz Baraka MChJ deb ataladi.', 'uz',
       'Baraka MChJning asosiy faoliyati non ishlab chiqarish.'),

    # ---- A lone word opening a sentence, a cell or an item: a brand, a city, a given name (deferred part c;
    # never an owner decision) blanks, and the ordinary words the re-checks found blanked stay.
    cell('names-lone-brand-in-a-competitor-cell-uz-blank', BLANK, 'pdf.biz.biznes_reja', PLAN_COMPETITORS_UZ, 'uz',
         'market_competitors', 'Korzinka', row=('', 'Narxlari yuqori, issiq non yo‘q'), gone=('Korzinka',)),
    cell('names-lone-brand-makro-in-a-competitor-cell-uz-blank', BLANK, 'pdf.biz.biznes_reja', PLAN_COMPETITORS_UZ,
         'uz', 'market_competitors', 'Makro', row=('', 'Uzoqda joylashgan'), gone=('Makro',)),
    cell('names-lone-brand-havas-in-a-competitor-cell-uz-blank', BLANK, 'pdf.biz.biznes_reja', PLAN_COMPETITORS_UZ,
         'uz', 'market_competitors', 'Havas', row=('', 'Assortimenti kam'), gone=('Havas',)),
    Case('names-lone-given-name-in-a-team-cell-uz-blank', BLANK, PLAN_COMPETITORS_UZ, 'uz', 'cell:team', 'Novvoy',
         entry='pdf.biz.biznes_reja', row=('Jasur', ''), gone=('Jasur',)),
    item('names-lone-brand-in-a-list-item-uz-blank', BLANK, 'pdf.biz.biznes_reja', PLAN_COMPETITORS_UZ, 'uz',
         'marketing', 'Korzinka yonida banner', gone=('Korzinka',)),
    body('names-lone-city-opening-a-sentence-uz-blank', BLANK, 'pdf.biz.hisobot', REPORT_UZ, 'uz', 'work_done',
         'Samarqand shahrida yangi filial ochildi.', gone=('Samarqand',)),
    body('names-lone-platform-opening-a-sentence-uz-blank', BLANK, 'pdf.biz.hisobot', REPORT_UZ, 'uz', 'work_done',
         'Uzum platformasida savdo boshlandi.', gone=('Uzum',)),
    body('names-lone-brand-opening-a-sentence-uz-blank', BLANK, 'pdf.xat.ishga_kirish', COVER_UZ, 'uz', 'fit',
         'Ucell bilan hamkorlikda ham ishlaganman.', gone=('Ucell',)),
    gp('names-lone-given-name-opening-a-sentence-uz-blank', BLANK, PLAN_UZ, 'uz', 'Sardor javobgar.',
       gone=('Sardor',)),
    body('names-lone-university-opening-a-sentence-uz-to-en-blank', BLANK, 'pdf.xat.motivatsion', MOTIVATION_UZ_EN,
         'en', 'why', 'Oxford offers the strongest economics programme.', gone=('Oxford',), translated=True),
    body('names-lone-firm-opening-a-sentence-uz-to-en-blank', BLANK, 'pdf.xat.motivatsion', MOTIVATION_UZ_EN, 'en',
         'evidence', 'Deloitte gave me my first internship, where I analysed data.', gone=('Deloitte',),
         translated=True),
    body('names-lone-surname-opening-a-sentence-ru-to-en-blank', BLANK, 'pdf.biz.hisobot', REPORT_RU_EN, 'en',
         'summary', 'Smith led the sales department.', gone=('Smith',), translated=True),
    body('names-lone-firm-opening-a-sentence-ru-blank', BLANK, 'pdf.biz.hisobot', REPORT_RU, 'ru', 'summary',
         'Артель увеличила продажи.', gone=('Артель',)),
    # Round 4: a first word that is no common word (facts.common, words/*.txt) is held as a name; a common word with
    # its endings, a Russian duty's verb and an English connector stay, and a rare common word goes, the price of it.
    body('names-common-word-with-endings-opening-a-sentence-uz-keep', KEEP, 'pdf.xat.ishga_kirish', COVER_UZ, 'uz',
         'fit', 'Kompaniyangizdagi bo‘sh lavozim meni qiziqtiradi.'),
    item('names-a-duty-opening-with-its-verb-ru-keep', KEEP, 'pdf.biz.lavozim_yoriqnomasi', JOB_RU, 'ru', 'duties',
         'Соблюдает требования охраны труда.'),
    body('names-a-connector-opening-a-sentence-ru-to-en-keep', KEEP, 'pdf.biz.hisobot', REPORT_RU_EN, 'en', 'summary',
         'Despite the slow first quarter, sales grew.', translated=True),
    # Round 2 of the convergence grew the lexicon (a hand vocabulary of each language, derivational suffixes), so the
    # first two rare words of round 4 are now read as common and kept; rarer words still go, the price of it.
    gp('names-a-rare-common-word-opening-a-sentence-uz-accepted_false_blank', ACCEPTED, PLAN_UZ, 'uz',
       'Sinergiya jamoani kuchaytiradi.', gone=('Sinergiya',),
       pair='names-lone-given-name-opening-a-sentence-uz-blank'),
    body('names-a-rare-common-word-opening-a-sentence-ru-accepted_false_blank', ACCEPTED, 'pdf.biz.hisobot', REPORT_RU,
         'ru', 'work_done', 'Аутсорсинг бухгалтерии снизил расходы.', gone=('Аутсорсинг',),
         pair='names-lone-firm-opening-a-sentence-ru-blank'),
    # A table's thing the lexicon lacks is held as a name (round 3 of the convergence, should): growing the English
    # lexicon from the one real word list on this machine (Tesseract's) also made fresh surnames that are words read
    # as common ("Whitehead", "Nightingale", "Valiant"), a leak, so the cell's blank is the price; no Uzbek or Russian
    # list is here.
    cell('names-a-things-name-the-lexicon-lacks-in-a-cell-ru-to-en-accepted_false_blank', ACCEPTED,
         'pdf.biz.biznes_reja', PLAN_RU_EN, 'en', 'finance_costs', 'Tripod', row=('', '5 million soums'),
         gone=('Tripod',), translated=True, pair='names-a-surname-that-is-a-rare-word-en-blank'),
    gp('names-a-surname-that-is-a-rare-word-en-blank', BLANK, EN_NONE, 'en', 'Whitehead supervised the workshop.',
       gone=('Whitehead',)),
    cell('names-a-things-name-the-lexicon-lacks-in-a-cell-ru-accepted_false_blank', ACCEPTED, 'pdf.biz.biznes_reja',
         PLAN_RU, 'ru', 'finance_costs', 'Штатив', row=('', '5 млн сумов'), gone=('Штатив',),
         pair='names-lone-firm-opening-a-sentence-ru-blank'),
    cell('names-a-things-name-the-lexicon-lacks-in-a-cell-uz-accepted_false_blank', ACCEPTED, 'pdf.biz.biznes_reja',
         PLAN_UZ, 'uz', 'finance_costs', 'Softboks', row=('', '5 mln so‘m'), gone=('Softboks',),
         pair='names-lone-brand-in-a-competitor-cell-uz-blank'),
    gp('names-a-word-of-the-grown-lexicon-opening-a-sentence-uz-keep', KEEP, PLAN_UZ, 'uz',
       'Pudratchi ishni o‘z vaqtida bajaradi.'),
    body('names-a-derived-noun-opening-a-sentence-ru-keep', KEEP, 'pdf.biz.hisobot', REPORT_RU, 'ru', 'work_done',
         'Кастомизация продукции выросла.'),
    body('names-a-rare-common-word-opening-a-sentence-uz-to-en-accepted_false_blank', ACCEPTED, 'pdf.xat.motivatsion',
         MOTIVATION_UZ_EN, 'en', 'evidence', 'Handicraft workshops taught me patience.', gone=('Handicraft',),
         translated=True, pair='names-lone-firm-opening-a-sentence-uz-to-en-blank'),
    # A given name, a surname, a place or a brand (words/names.txt) is no common word, even where it is one too, and
    # no ending after a three-letter base makes it one (round 2 of the convergence): the tie-break's blank.
    gp('names-lone-given-name-that-stemmed-as-common-uz-blank', BLANK, UZ_NONE, 'uz', 'Malika loyihani boshqaradi.',
       gone=('Malika',)),
    gp('names-lone-given-name-iroda-uz-blank', BLANK, UZ_NONE, 'uz', 'Iroda sotuv bo‘limini boshqaradi.',
       gone=('Iroda',)),
    gp('names-lone-given-name-umid-uz-blank', BLANK, UZ_NONE, 'uz', 'Umid sotuv bo‘limini boshqaradi.',
       gone=('Umid',)),
    gp('names-lone-given-name-bahor-uz-blank', BLANK, UZ_NONE, 'uz', 'Bahor kassada ishlaydi.', gone=('Bahor',)),
    gp('names-lone-given-name-with-a-case-ending-uz-blank', BLANK, UZ_NONE, 'uz', 'Malikaga rahmat aytamiz.',
       gone=('Malika',)),
    gp('names-lone-city-termiz-uz-blank', BLANK, UZ_NONE, 'uz', 'Termiz filiali yaqinda ochiladi.',
       gone=('Termiz',)),
    gp('names-lone-city-with-a-case-ending-uz-blank', BLANK, UZ_NONE, 'uz', 'Qarshida yangi do‘kon ochamiz.',
       gone=('Qarshi',)),
    gp('names-a-citys-people-uz-blank', BLANK, UZ_NONE, 'uz', 'Samarqandlik mijozlar ham keladi.',
       gone=('Samarqand',)),
    gp('names-lone-brand-asaka-uz-blank', BLANK, UZ_NONE, 'uz', 'Asaka kredit beradi.', gone=('Asaka',)),
    gp('names-lone-given-name-peter-en-blank', BLANK, EN_NONE, 'en', 'Peter managed the shop floor.',
       gone=('Peter',)),
    gp('names-lone-given-name-grace-en-blank', BLANK, EN_NONE, 'en', 'Grace manages the shop floor.',
       gone=('Grace',)),
    gp('names-lone-surname-brown-en-blank', BLANK, EN_NONE, 'en', 'Brown joined the team last spring.',
       gone=('Brown',)),
    gp('names-lone-surname-with-a-possessive-en-blank', BLANK, EN_NONE, 'en', 'Smith’s team grew quickly.',
       gone=('Smith',)),
    gp('names-lone-given-name-jordan-en-blank', BLANK, EN_NONE, 'en', 'Jordan handled the accounts.',
       gone=('Jordan',)),
    gp('names-lone-given-name-anna-ru-blank', BLANK, RU_NONE, 'ru', 'Анна руководит отделом продаж.', gone=('Анна',)),
    gp('names-lone-given-name-nadezhda-ru-blank', BLANK, RU_NONE, 'ru', 'Надежда руководит магазином.',
       gone=('Надежда',)),
    gp('names-lone-given-name-with-a-case-ending-ru-blank', BLANK, RU_NONE, 'ru', 'Марии поручено вести учёт.',
       gone=('Марии',)),
    gp('names-a-given-name-that-is-a-common-word-opening-a-sentence-uz-accepted_false_blank', ACCEPTED, UZ_NONE,
       'uz', 'Umid qilamanki, loyiha muvaffaqiyatli bo‘ladi.', gone=('Umid',),
       pair='names-lone-given-name-umid-uz-blank'),
    gp('names-a-given-name-that-is-a-season-uz-accepted_false_blank', ACCEPTED, UZ_NONE, 'uz',
       'Bahor faslida savdo oshadi.', gone=('Bahor',), pair='names-lone-given-name-bahor-uz-blank'),
    gp('names-a-given-name-that-is-a-loan-term-en-accepted_false_blank', ACCEPTED, PLAN_EN, 'en',
       'Grace period on the loan is agreed with the bank.', gone=('Grace',),
       pair='names-lone-given-name-grace-en-blank'),
    gp('names-a-surname-that-is-a-colour-en-accepted_false_blank', ACCEPTED, PLAN_EN, 'en',
       'Brown bread is baked every morning.', gone=('Brown',), pair='names-lone-surname-brown-en-blank'),
    gp('names-a-given-name-that-is-a-common-word-ru-accepted_false_blank', ACCEPTED, RU_NONE, 'ru',
       'Надежда на рост продаж велика.', gone=('Надежда',), pair='names-lone-given-name-nadezhda-ru-blank'),
    gp('names-a-surname-word-in-a-hyphen-compound-en-keep', KEEP, PLAN_EN, 'en', 'Long-term loans are cheaper.'),
    gp('names-a-plural-of-a-surname-word-en-keep', KEEP, PLAN_EN, 'en', 'Prices are set below supermarkets.'),
    gp('names-a-case-form-that-is-a-common-word-ru-keep', KEEP, RU_NONE, 'ru', 'Ширина помещения достаточна.'),
    gp('names-a-common-word-made-from-a-given-name-uz-keep', KEEP, UZ_NONE, 'uz',
       'Shirinliklar ham sotiladi.'),
    body('names-ordinary-first-word-uz-keep', KEEP, 'pdf.biz.hisobot', REPORT_UZ, 'uz', 'work_done',
         'Kompaniya yangi filial ochdi.'),
    body('names-ordinary-first-word-ru-keep', KEEP, 'pdf.biz.hisobot', REPORT_RU, 'ru', 'work_done',
         'Компания открыла новый филиал.'),
    body('names-ordinary-first-word-ru-to-en-keep', KEEP, 'pdf.biz.hisobot', REPORT_RU_EN, 'en', 'work_done',
         'Management opened a new branch.', translated=True),
    body('names-common-word-after-a-blanked-run-uz-keep', KEEP, 'pdf.biz.biznes_reja', PLAN_UZ, 'uz', 'operations',
         'Davlat ro‘yxatidan o‘tish tez amalga oshiriladi.',
         parts=(('summary_lead', {'body': 'Biz Davlat Soliq Qo‘mitasi talablariga rioya qilamiz.'}),)),
    cell('names-common-word-cost-cell-after-a-blanked-run-uz-keep', KEEP, 'pdf.biz.biznes_reja', PLAN_UZ, 'uz',
         'finance_costs', 'Davlat boji',
         parts=(('summary_lead', {'body': 'Biz Davlat Soliq Qo‘mitasi talablariga rioya qilamiz.'}),)),
    cell('names-common-word-cost-cell-soliqlar-uz-keep', KEEP, 'pdf.biz.biznes_reja', PLAN_COMPETITORS_UZ, 'uz',
         'finance_costs', 'Soliqlar'),
    cell('names-common-word-cost-cell-xomashyo-uz-keep', KEEP, 'pdf.biz.biznes_reja', PLAN_COMPETITORS_UZ, 'uz',
         'finance_costs', 'Xomashyo'),
    cell('names-translated-cost-cell-ru-to-en-keep', KEEP, 'pdf.biz.biznes_reja', PLAN_RU_EN, 'en', 'finance_costs',
         'Rent', row=('', '5 million soums'), translated=True),
    body('names-common-word-after-a-blanked-central-bank-en-keep', KEEP, 'pdf.biz.biznes_reja', PLAN_EN, 'en',
         'operations', 'Central heating is installed.',
         parts=(('summary_lead', {'body': 'Rates follow the Central Bank of Uzbekistan.'}),)),

    # ---- A fact taken out holds its names wherever they open a sentence (eb958ac; round 3 must, regression).
    body('held-org-before-form-rejected-ru-to-en-blank', BLANK, 'pdf.biz.hisobot', REPORT_RU_EN, 'en', 'summary',
         'Acme also opened a new branch.', gone=('Acme',), facts=(('organization', 'Acme LLC'),), translated=True),
    body('held-org-before-form-with-possessive-ru-to-en-blank', BLANK, 'pdf.biz.hisobot', REPORT_RU_EN, 'en',
         'work_done', 'Acme’s sales team grew.', gone=('Acme',), facts=(('organization', 'Acme LLC'),),
         translated=True),
    body('held-org-before-form-with-ending-uz-blank', BLANK, 'pdf.xat.ishga_kirish', COVER_UZ, 'uz', 'opening',
         'Artelga sotuv menejeri lavozimiga ariza bilan murojaat qilaman.', gone=('Artel',),
         facts=(('applicant_name', 'Qodirova Malika'), ('employer_name', 'Artel MChJ'))),
    body('held-org-before-form-bare-uz-blank', BLANK, 'pdf.xat.ishga_kirish', COVER_UZ, 'uz', 'motive',
         'Artel yetakchi ishlab chiqaruvchi hisoblanadi.', gone=('Artel',),
         facts=(('applicant_name', 'Qodirova Malika'), ('employer_name', 'Artel MChJ'))),
    body('held-given-names-of-rejected-chair-and-participants-uz-blank', BLANK, 'pdf.biz.bayonnoma', MINUTES_UZ, 'uz',
         'item_speakers', 'Dilnoza maktab formasi haqida gapirdi. Aziz yangi o‘quv yili rejasini taqdim etdi. '
         'Sardor taklif kiritdi.', gone=('Dilnoza', 'Aziz', 'Sardor'),
         facts=(('chair', 'Aziz Rahim'), ('participants', 'Dilnoza\nSardor\nMalika'))),
    body('held-one-word-org-rejected-uz-blank', BLANK, 'pdf.xat.ishga_kirish', COVER_UZ, 'uz', 'fit',
         'Artelda ishlaganman.', gone=('Artel',), facts=(('employer_name', 'Artel'),)),
    body('held-bank-rejected-opening-a-sentence-uz-blank', BLANK, 'pdf.biz.biznes_reja', PLAN_UZ, 'uz',
         'summary_lead', 'Xalq banki 200 mln so‘m kredit beradi.', gone=('Xalq',),
         facts=(('loan_bank', 'Xalq banki'),)),
    body('held-rejected-teacher-in-guarded-stage-uz-blank', BLANK, 'pdf.dars_ishlanmasi',
         '7-sinf ona tili darsi uchun dars ishlanmasi: ot so‘z turkumi.', 'uz', 'stage_opening',
         'O‘qituvchi Karimova Dilnoza Bahodirovna o‘quvchilar bilan salomlashadi.', gone=('Karimova', 'Dilnoza'),
         facts=(('teacher', 'Karimova Dilnoza Bahodirovna'),)),
    body('held-given-name-beside-rejected-initials-in-guarded-stage-uz-blank', BLANK, 'pdf.dars_ishlanmasi', LESSON_UZ,
         'uz', 'stage_opening', 'O‘qituvchi Karimova Dilnoza o‘quvchilar bilan salomlashadi.',
         gone=('Karimova', 'Dilnoza'), facts=(('teacher', 'Karimova D. R.'),)),
    body('held-rejected-person-given-name-uz-blank', BLANK, 'pdf.biz.biznes_reja', UZ_NONE, 'uz', 'summary_lead',
         'Umid loyihani boshqaradi.', gone=('Umid',), facts=(('director', 'Umid Karimov'),)),
    # An honorific is part of the name, never a role's lower-case word (round 2 of the convergence, from 9de1cf9).
    body('held-given-name-with-an-honorific-rejected-uz-blank', BLANK, 'pdf.biz.biznes_reja', UZ_NONE, 'uz',
         'summary_lead', 'Malika loyihani boshqaradi.', gone=('Malika',), facts=(('director', 'Malika opa'),)),
    body('held-given-name-with-aka-rejected-uz-blank', BLANK, 'pdf.biz.biznes_reja', UZ_NONE, 'uz', 'summary_lead',
         'Azizning tajribasi katta.', gone=('Aziz',), facts=(('director', 'Aziz aka'),)),
    body('held-given-name-with-an-honorific-in-a-chair-line-rejected-uz-blank', BLANK, 'pdf.biz.bayonnoma', MINUTES_UZ,
         'uz', 'item_speakers', 'Dilnoza maktab formasi haqida gapirdi.', gone=('Dilnoza',),
         facts=(('chair', 'Dilnoza xonim'),)),
    body('held-quoted-org-rejected-ru-blank', BLANK, 'pdf.biz.hisobot', REPORT_RU, 'ru', 'work_done',
         'Акме открыла новый филиал.', gone=('Акме',), facts=(('organization', 'ООО «Акме»'),)),
    body('held-common-word-after-rejected-org-ru-to-en-keep', KEEP, 'pdf.biz.hisobot', REPORT_RU_EN, 'en',
         'work_done', 'Trading volumes grew.', facts=(('organization', 'Acme Trading LLC'),), translated=True),
    body('held-common-word-after-rejected-org-ru-keep', KEEP, 'pdf.biz.hisobot', REPORT_RU, 'ru', 'work_done',
         'Торговый оборот вырос.', facts=(('organization', 'Торговый дом «Акме»'),)),
    body('held-common-words-after-rejected-bank-uz-keep', KEEP, 'pdf.biz.biznes_reja', PLAN_UZ, 'uz', 'conclusion',
         'Xalqaro ko‘rgazmalarda qatnashamiz.', facts=(('loan_bank', 'Xalq banki'),)),
    item('held-common-word-item-after-rejected-bank-uz-keep', KEEP, 'pdf.biz.biznes_reja', PLAN_UZ, 'uz', 'marketing',
         'Xalq sayllarida stend', facts=(('loan_bank', 'Xalq banki'),)),
    body('held-role-word-after-rejected-author-line-uz-keep', KEEP, 'pdf.biz.hisobot', REPORT_UZ, 'uz', 'summary',
         'Bosh ofis ta’mirlandi.', facts=(('author', 'Bosh hisobchi Karimova Dilnoza'),),
         parts=(('work_done', {'body': 'Kompaniya Moliya Vazirligi bilan hamkorlik qildi.'}),)),
    item('held-role-item-after-rejected-author-line-uz-keep', KEEP, 'pdf.biz.hisobot', REPORT_UZ, 'uz', 'problems',
         'Bosh hisobchi lavozimi bo‘sh qoldi.', facts=(('author', 'Bosh hisobchi Karimova Dilnoza'),)),
    item('held-common-word-item-after-blanked-ministry-uz-keep', KEEP, 'pdf.biz.hisobot', REPORT_UZ, 'uz', 'plans',
         'Moliyaviy resurslar yetishmadi.',
         parts=(('work_done', {'body': 'Kompaniya Moliya Vazirligi bilan hamkorlik qildi.'}),)),
    body('held-common-word-after-blanked-ministry-uz-keep', KEEP, 'pdf.biz.hisobot', REPORT_UZ, 'uz', 'conclusion',
         'Moliya bo‘limi kengaytirildi.',
         parts=(('work_done', {'body': 'Kompaniya Moliya Vazirligi bilan hamkorlik qildi.'}),)),
    # A rejected line or list of capitalised common words holds none of them (round 2 of the convergence, from 9de1cf9).
    body('held-common-word-of-a-rejected-signers-line-uz-keep', KEEP, 'pdf.biz.hisobot', REPORT_UZ, 'uz', 'summary',
         'Bosh ofis ta’mirlandi.', facts=(('signers', 'Bosh Hisobchi'),)),
    body('held-common-words-of-rejected-enclosures-uz-keep', KEEP, 'pdf.xat.ishga_kirish', COVER_UZ, 'uz', 'closing',
         'Rezyume ilova qilinadi. Tavsiyanoma ham ilova qilingan.',
         facts=(('applicant_name', 'Qodirova Malika'), ('enclosures', 'Rezyume\nTavsiyanoma'))),
    body('held-common-word-of-a-rejected-author-line-uz-keep', KEEP, 'pdf.biz.hisobot', REPORT_UZ, 'uz', 'summary',
         'Maktab binosi ta’mirlandi.', facts=(('author', 'Maktab Direktori'),)),
    body('held-given-names-of-a-rejected-participants-list-uz-blank', BLANK, 'pdf.biz.bayonnoma', MINUTES_UZ, 'uz',
         'item_speakers', 'Malika maktab formasi haqida gapirdi.', gone=('Malika',),
         facts=(('participants', 'Dilnoza\nSardor\nMalika'),)),
    body('held-role-word-of-rejected-person-uz-keep', KEEP, 'pdf.biz.biznes_reja', UZ_NONE, 'uz', 'summary_lead',
         'Bosh ofis mahallada joylashgan.', facts=(('director', 'Bosh direktor Karimova Dilnoza'),)),
    # A rejected line that is only a name holds every word of it, a given name that is also a word included ("Hikmat",
    # "Rahmat", "Fuller", "Rich"); only a role's, a kind's or a document's words, and a field of no people, hold none
    # (round 3 of the convergence, must, regression from 1557cee).
    body('held-rejected-participant-hikmat-uz-blank', BLANK, 'pdf.biz.bayonnoma', MINUTES_UZ, 'uz', 'item_speakers',
         'Hikmat maktab formasi haqida gapirdi.', gone=('Hikmat',), facts=(('participants', 'Hikmat\nSardor\nMalika'),)),
    body('held-rejected-participant-rahmat-uz-blank', BLANK, 'pdf.biz.bayonnoma', MINUTES_UZ, 'uz', 'item_speakers',
         'Rahmat maktab formasi haqida gapirdi.', gone=('Rahmat',), facts=(('participants', 'Rahmat\nSardor'),)),
    body('held-rejected-participant-gul-uz-blank', BLANK, 'pdf.biz.bayonnoma', MINUTES_UZ, 'uz', 'item_speakers',
         'Gul maktab formasi haqida gapirdi.', gone=('Gul',), facts=(('participants', 'Gul\nSardor'),)),
    body('held-rejected-chair-hikmat-rahim-uz-blank', BLANK, 'pdf.biz.bayonnoma', MINUTES_UZ, 'uz', 'item_speakers',
         'Hikmat majlisni ochdi.', gone=('Hikmat',), facts=(('chair', 'Rais: Hikmat Rahim'),)),
    body('held-rejected-chair-rahmat-aka-uz-blank', BLANK, 'pdf.biz.bayonnoma', MINUTES_UZ, 'uz', 'item_speakers',
         'Rahmat majlisni ochdi.', gone=('Rahmat',), facts=(('chair', 'Rahmat aka'),)),
    body('held-rejected-chair-hikmat-opa-uz-blank', BLANK, 'pdf.biz.bayonnoma', MINUTES_UZ, 'uz', 'item_speakers',
         'Hikmat majlisni ochdi.', gone=('Hikmat',), facts=(('chair', 'Hikmat opa'),)),
    body('held-rejected-signers-list-hikmat-uz-blank', BLANK, 'pdf.biz.hisobot', REPORT_UZ, 'uz', 'summary',
         'Hikmat yangi filialni ochdi.', gone=('Hikmat',), facts=(('signers', 'Hikmat\nRahmat'),)),
    body('held-rejected-signers-beside-their-roles-uz-blank', BLANK, 'pdf.biz.hisobot', REPORT_UZ, 'uz', 'summary',
         'Hikmat yangi filialni ochdi.', gone=('Hikmat',),
         facts=(('signers', 'Direktor | Hikmat\nBosh hisobchi | Rahmat'),)),
    body('held-rejected-chair-after-a-role-in-one-run-uz-blank', BLANK, 'pdf.biz.bayonnoma', MINUTES_UZ, 'uz',
         'item_speakers', 'Hikmat majlisni ochdi.', gone=('Hikmat',), facts=(('chair', 'Direktor Hikmat Rahim'),)),
    body('held-rejected-second-signer-fuller-en-blank', BLANK, 'pdf.xat.tavsiya', RECOMMENDATION_EN, 'en', 'evidence',
         'Fuller also supervised her project.', gone=('Fuller',), facts=(('second_signer', 'Grant Fuller'),)),
    body('held-rejected-second-signer-rich-en-blank', BLANK, 'pdf.xat.tavsiya', RECOMMENDATION_EN, 'en', 'evidence',
         'Rich also supervised her project.', gone=('Rich',), facts=(('second_signer', 'Dawn Rich'),)),
    body('held-rejected-second-signer-banks-en-blank', BLANK, 'pdf.xat.tavsiya', RECOMMENDATION_EN, 'en', 'evidence',
         'Banks also supervised her project.', gone=('Banks',), facts=(('second_signer', 'Chase Banks'),)),
    body('held-role-word-beside-a-rejected-signer-uz-keep', KEEP, 'pdf.biz.hisobot', REPORT_UZ, 'uz', 'summary',
         'Bosh ofis ta’mirlandi.', facts=(('signers', 'Bosh hisobchi | Hikmat Rahim'),)),
    body('held-document-words-of-rejected-enclosures-uz-keep', KEEP, 'pdf.xat.ishga_kirish', COVER_UZ, 'uz', 'closing',
         'Diplom nusxasi ilova qilinadi.',
         facts=(('applicant_name', 'Qodirova Malika'), ('enclosures', 'Diplom Nusxasi\nPasport'))),
    # The same word in the same place is the rejected person's name and the verb's noun: only grammar tells them.
    body('held-given-name-that-is-a-common-word-uz-accepted_false_blank', ACCEPTED, 'pdf.biz.biznes_reja', UZ_NONE,
         'uz', 'summary_lead', 'Umid qilamanki, loyiha muvaffaqiyatli bo‘ladi.', gone=('Umid',),
         facts=(('director', 'Umid Karimov'),), pair='held-rejected-person-given-name-uz-blank'),
    # By design (facts._names): in a grounded part a grammar word before an invented name goes with it.
    gp('names-grammar-word-before-invented-name-uz-accepted_false_blank', ACCEPTED, PLAN_UZ, 'uz',
       'Nazorat Sardor Xolmatovga yuklansin.', gone=('Nazorat', 'Xolmatov'),
       pair='names-invented-full-name-opening-a-sentence-uz-blank'),
    gp('names-invented-full-name-opening-a-sentence-uz-blank', BLANK, PLAN_UZ, 'uz', 'Sardor Xolmatov javobgar.',
       gone=('Sardor', 'Xolmatov')),

    # ---- A figure's fact carries no invented name, and keeps its own labels (486d2e4, 51d59a9).
    fact('figures-invented-bank-in-requisites-uz-blank', BLANK, 'pdf.biz.tijorat_taklifi', OFFER_UZ, 'uz',
         'seller_requisites', 'h/r 20208000900123456001, «Kapitalbank» ATB Toshkent filiali, MFO 00440, STIR 301234567',
         gone=('Kapitalbank',)),
    fact('figures-invented-person-beside-phone-uz-blank', BLANK, 'pdf.biz.tijorat_taklifi', OFFER_UZ, 'uz',
         'seller_phone', '+998 90 123 45 67 (Aziz Karimov)', gone=('Karimov',)),
    fact('figures-invented-lender-beside-a-sum-uz-blank', BLANK, 'pdf.biz.biznes_reja', PLAN_UZ, 'uz',
         'external_funding', '200 mln so‘m (Hamkorbank krediti)', gone=('Hamkorbank',)),
    fact('figures-invented-city-beside-a-date-uz-blank', BLANK, 'pdf.biz.hisobot',
         'Namuna MChJ savdo bo‘limining 2024-yil faoliyati bo‘yicha hisobot, sanasi 15.01.2025.', 'uz',
         'report_date', '15.01.2025, Samarqand', gone=('Samarqand',)),
    supported('figures-invented-bank-beside-the-customers-account-ru-to-en-blank', BLANK, OFFER_RU_EN, 'en', 'ref',
              'Account 20208000900123456001, Asaka Bank JSCB, MFO 00440', translated=True),
    supported('figures-invented-bank-beside-the-customers-account-uz-to-ru-blank', BLANK, OFFER_UZ_RU, 'ru', 'ref',
              'р/с 20208000900123456001 в АКБ «Ипак Йули», МФО 00440', translated=True),
    supported('figures-jscb-label-beside-the-customers-bank-ru-to-en-keep', KEEP, OFFER_RU_EN, 'en', 'ref',
              'Account 20208000900123456001, Kapitalbank JSCB, MFO 00440, TIN 301234567', translated=True),
    supported('figures-bank-code-label-ru-to-en-keep', KEEP, OFFER_RU_EN, 'en', 'ref',
              'Settlement account 20208000900123456001 at Kapitalbank, Bank code (MFO) 00440', translated=True),
    supported('figures-bank-label-uz-to-ru-keep', KEEP, OFFER_UZ_RU, 'ru', 'ref',
              'Расчётный счёт 20208000900123456001, Банк: АКБ «Капиталбанк», МФО 00440', translated=True),
    supported('figures-phone-labels-ru-to-en-keep', KEEP, OFFER_RU_EN, 'en', 'phone',
              '+998 90 123 45 67 (mobile, Telegram)', translated=True),
    fact('figures-the-customers-requisites-uz-keep', KEEP, 'pdf.biz.tijorat_taklifi', OFFER_UZ_BANK, 'uz',
         'seller_requisites', 'h/r 20208000900123456001, «Kapitalbank» ATB, MFO 00440, STIR 301234567'),
    fact('figures-the-customers-contract-number-uz-keep', KEEP, 'pdf.biz.tijorat_taklifi', OFFER_UZ_BANK, 'uz',
         'doc_number', 'Shartnoma № 125'),
    fact('figures-the-customers-contract-number-uz-to-ru-keep', KEEP, 'pdf.xat.ariza',
         'Rus tilida ariza yozib bering, men bu kompaniyada buxgalter bo‘lib ishlayman, menga shartnoma № 125 bo‘yicha '
         'ta’til kerak, ismim Qodirova Malika.', 'ru', 'reference_numbers', 'Договор № 125', translated=True),
    fact('figures-mobile-label-ru-to-en-keep', KEEP, 'pdf.xat.ishga_kirish',
         'Напишите сопроводительное письмо на английском на вакансию Э-7, зарплата 8 000 000 сумов, телефон '
         '+998 90 123 45 67.', 'en', 'phone', 'Mobile: +998 90 123 45 67', translated=True),
    fact('figures-vacancy-reference-respelled-ru-to-en-keep', KEEP, 'pdf.xat.ishga_kirish',
         'Напишите сопроводительное письмо на английском на вакансию Э-7, зарплата 8 000 000 сумов, телефон '
         '+998 90 123 45 67.', 'en', 'vacancy_reference', 'E-7', translated=True),
    fact('figures-year-label-of-a-class-uz-to-en-keep', KEEP, 'pdf.test',
         'Menga ingliz tilida 7-sinf uchun matematika testi tuzib bering, 20 ta savol bo‘lsin va vaqt 30 daqiqa, '
         'savollar oson bo‘lsin.',
         'en', 'class_level', 'Year 7', translated=True),
    fact('figures-as-of-label-uz-to-en-keep', KEEP, 'pdf.biz.marketing_reja',
         'Menga ingliz tilida marketing rejasi yozib bering, bizning kafe uchun byudjet 36 mln so‘m, o‘rtacha chek '
         '220 000 so‘m, 30-iyun holatiga ma’lumotlar bilan.', 'en', 'avg_check', 'Average check UZS 220,000',
         translated=True),

    # ---- A code's whole name is the customer's, wherever it stands and in any language (e1ed476, 75dbd27).
    item('laws-another-code-opening-an-item-uz-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', JOB_UZ, 'uz',
         'responsibility', 'Jinoyat kodeksiga muvofiq javobgar bo‘ladi.', gone=('Jinoyat',)),
    item('laws-code-named-before-togrisidagi-uz-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', JOB_UZ, 'uz',
         'responsibility', 'Ma’muriy javobgarlik to‘g‘risidagi kodeksga muvofiq javobgar bo‘ladi.',
         gone=('Ma’muriy',)),
    item('laws-procedural-code-uz-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', JOB_UZ, 'uz', 'responsibility',
         'Fuqarolik protsessual kodeksi talablariga rioya qiladi.', gone=('Fuqarolik',)),
    item('laws-hyphenated-procedural-code-uz-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', JOB_UZ, 'uz',
         'responsibility', 'Jinoyat-protsessual kodeksiga muvofiq javob beradi.', gone=('Jinoyat',)),
    item('laws-another-code-beside-the-customers-uz-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', JOB_UZ, 'uz',
         'general', 'Soliq kodeksi va Mehnat kodeksi talablariga amal qiladi.', gone=('Soliq',)),
    item('laws-another-law-uz-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', JOB_UZ, 'uz', 'duties',
         'Soliq to‘g‘risidagi qonunga muvofiq hisobot topshiradi.', gone=('Soliq',)),
    item('laws-invented-code-name-uz-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', JOB_UZ, 'uz', 'responsibility',
         'Raqamli iqtisodiyot kodeksiga muvofiq javobgar.', gone=('Raqamli',)),
    item('laws-code-named-after-ob-ru-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', JOB_RU, 'ru', 'responsibility',
         'Несёт ответственность по Кодексу об административных правонарушениях.', gone=('административных',)),
    item('laws-lowercase-code-name-not-listed-ru-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', JOB_RU, 'ru',
         'responsibility', 'Споры рассматриваются по арбитражному процессуальному кодексу.', gone=('арбитражному',)),
    item('laws-code-named-before-togrisidagi-ru-to-uz-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', JOB_RU_UZ, 'uz',
         'responsibility', 'U Ma’muriy javobgarlik to‘g‘risidagi kodeksga ko‘ra javob beradi.',
         gone=('to‘g‘risidagi kodeksga',), translated=True),
    item('laws-code-named-after-of-en-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', JOB_EN, 'en', 'responsibility',
         'The Code of Administrative Offences applies to breaches.', gone=('Administrative',)),
    item('laws-the-customers-code-uz-keep', KEEP, 'pdf.biz.lavozim_yoriqnomasi', JOB_UZ, 'uz', 'responsibility',
         'Mehnat kodeksiga muvofiq javobgar bo‘ladi.'),
    item('laws-the-customers-code-with-the-country-uz-keep', KEEP, 'pdf.biz.lavozim_yoriqnomasi', JOB_UZ, 'uz',
         'general', 'O‘zbekiston Respublikasi Mehnat kodeksiga muvofiq ish yuritadi.'),
    item('laws-pointer-at-the-customers-code-ushbu-uz-keep', KEEP, 'pdf.biz.lavozim_yoriqnomasi', JOB_UZ, 'uz',
         'responsibility', 'Ushbu kodeks talablariga rioya qiladi.'),
    item('laws-pointer-at-the-customers-code-mazkur-uz-keep', KEEP, 'pdf.biz.lavozim_yoriqnomasi', JOB_UZ, 'uz',
         'responsibility', 'Mazkur kodeksga muvofiq javob beradi.'),
    item('laws-pointer-at-the-customers-code-ru-keep', KEEP, 'pdf.biz.lavozim_yoriqnomasi', JOB_RU, 'ru',
         'responsibility', 'Настоящий кодекс обязателен для исполнения.'),
    item('laws-pointer-at-the-customers-code-en-keep', KEEP, 'pdf.biz.lavozim_yoriqnomasi', JOB_EN, 'en',
         'responsibility', 'This Code applies to every employee.'),
    item('laws-the-customers-code-in-uzbek-cyrillic-general-uz-keep', KEEP, 'pdf.biz.lavozim_yoriqnomasi',
         JOB_UZ_CYRILLIC, 'uz', 'general', 'Bosh buxgalter o‘z faoliyatida Mehnat kodeksiga amal qiladi.',
         translated=False),
    item('laws-the-customers-code-in-uzbek-cyrillic-responsibility-uz-keep', KEEP, 'pdf.biz.lavozim_yoriqnomasi',
         JOB_UZ_CYRILLIC, 'uz', 'responsibility', 'Mehnat kodeksiga muvofiq javobgar bo‘ladi.', translated=False),
    item('laws-the-customers-law-in-uzbek-cyrillic-uz-keep', KEEP, 'pdf.biz.lavozim_yoriqnomasi', STATUTE_UZ_CYRILLIC,
         'uz', 'general', 'Ta’lim to‘g‘risidagi qonunga muvofiq faoliyat yuritadi.', translated=False),
    item('laws-the-customers-code-translated-mid-sentence-ru-to-uz-keep', KEEP, 'pdf.biz.lavozim_yoriqnomasi',
         JOB_RU_UZ, 'uz', 'general', 'Bosh buxgalter Mehnat kodeksiga muvofiq ishlaydi.', translated=True),
    item('laws-the-customers-code-translated-opening-an-item-ru-to-uz-keep', KEEP, 'pdf.biz.lavozim_yoriqnomasi',
         JOB_RU_UZ, 'uz', 'responsibility', 'Mehnat kodeksiga muvofiq javobgar bo‘ladi.', translated=True),
    item('laws-the-customers-article-translated-ru-to-uz-keep', KEEP, 'pdf.biz.lavozim_yoriqnomasi',
         JOB_RU_UZ_ARTICLE, 'uz', 'responsibility', 'Mehnat kodeksining 214-moddasiga muvofiq javobgar bo‘ladi.',
         translated=True),
    item('laws-words-after-the-customers-code-and-tax-rules-ru-to-en-keep', KEEP, 'pdf.biz.lavozim_yoriqnomasi',
         JOB_RU_EN, 'en', 'general',
         'The accountant follows the Labour Code of the Republic of Uzbekistan and tax rules.', translated=True),
    item('laws-words-after-the-customers-code-land-workers-ru-to-en-keep', KEEP, 'pdf.biz.lavozim_yoriqnomasi',
         JOB_RU_EN, 'en', 'general', 'The Labour Code of Uzbekistan applies to land workers too.', translated=True),
    item('laws-the-customers-code-of-the-republic-ru-to-en-keep', KEEP, 'pdf.biz.lavozim_yoriqnomasi', JOB_RU_EN, 'en',
         'general', 'The accountant follows the Labour Code of the Republic of Uzbekistan.', translated=True),
    item('laws-laboratory-is-no-labour-code-en-keep', KEEP, 'pdf.biz.lavozim_yoriqnomasi', JOB_EN_TAX, 'en', 'general',
         'The Tax Code of Uzbekistan applies to laboratory equipment purchases.'),
    # A sentence's capitalised subject is no code's first word, and "tegishli", "boshqa", "yangi" point at a code
    # without naming one (round 2 of the convergence, regression from 8a00abe); the lower-case words between the
    # subject and the stem are still the code's name.
    item('laws-subject-before-tegishli-kodeks-uz-keep', KEEP, 'pdf.biz.lavozim_yoriqnomasi', JOB_UZ_LAWS, 'uz',
         'duties', 'Xodim tegishli kodeks talablarini biladi.'),
    item('laws-subject-before-yangi-kodeks-uz-keep', KEEP, 'pdf.biz.lavozim_yoriqnomasi', JOB_UZ_LAWS, 'uz',
         'duties', 'Xodim yangi kodeks talablarini o‘rganadi.'),
    item('laws-subject-before-boshqa-qonun-hujjatlari-uz-keep', KEEP, 'pdf.biz.lavozim_yoriqnomasi', JOB_UZ_LAWS, 'uz',
         'general', 'Xodim boshqa qonun hujjatlariga ham amal qiladi.'),
    item('laws-subject-before-an-unnamed-code-of-ethics-uz-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', JOB_UZ_LAWS,
         'uz', 'general', 'Xodim odob-axloq kodeksiga va Mehnat kodeksiga rioya qiladi.', gone=('odob-axloq',)),
    item('laws-subject-before-an-invented-code-uz-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', JOB_UZ_LAWS, 'uz',
         'general', 'Xodim Raqamli iqtisodiyot kodeksiga muvofiq ishlaydi.', gone=('Raqamli',)),
    # A code's lower-case words before its stem are its name too, and a translation's cannot be told from an invented
    # code's (round 4): the customer's administrative code written as Uzbek's about-phrase goes with them.
    item('laws-invented-about-phrase-translated-ru-to-uz-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', JOB_RU_UZ, 'uz',
         'responsibility', 'Xodim raqamli iqtisodiyot to‘g‘risidagi kodeksga muvofiq javob beradi.',
         gone=('raqamli',), translated=True),
    guard('laws-the-customers-code-translated-as-an-about-phrase-ru-to-uz-accepted_false_blank', ACCEPTED,
          JOB_RU_ADMIN_UZ, 'uz', 'Kassir Ma’muriy javobgarlik to‘g‘risidagi kodeksga muvofiq javob beradi.',
          gone=('javobgarlik',), translated=True, pair='laws-invented-about-phrase-translated-ru-to-uz-blank'),
    # Where the entry's own words hold it (lavozim_yoriqnomasi's "Javobgarlik" heading), the same sentence stays.
    item('laws-the-customers-code-translated-as-an-about-phrase-of-the-entrys-words-ru-to-uz-keep', KEEP,
         'pdf.biz.lavozim_yoriqnomasi', JOB_RU_ADMIN_UZ, 'uz', 'responsibility',
         'Kassir Ma’muriy javobgarlik to‘g‘risidagi kodeksga muvofiq javob beradi.', translated=True),
    # The same window and prefix mechanisms through facts.guard alone, where no names check runs (round3/e_more.py).
    guard('laws-window-after-of-reads-tax-rules-ru-to-en-keep', KEEP, JOB_RU_EN, 'en',
          'The accountant follows the Labour Code of the Republic of Uzbekistan and tax rules.', translated=True),
    guard('laws-window-after-of-reads-land-workers-ru-to-en-keep', KEEP, JOB_RU_EN, 'en',
          'The Labour Code of Uzbekistan applies to land workers too.', translated=True),
    guard('laws-window-after-ob-reads-tax-rules-ru-keep', KEEP, JOB_RU_ADMIN, 'ru',
          'Кассир несёт ответственность по Кодексу об административной ответственности и налоговым правилам.'),
    guard('laws-another-code-named-after-of-ru-to-en-blank', BLANK, JOB_RU_EN, 'en',
          'The Code of Administrative Offences of the Republic of Uzbekistan applies to late reports.',
          gone=('Administrative',), translated=True),
    # A code's or a law's name in lower case after its capitalised stem's "of" or "on", as a model renders the
    # Russian and Uzbek names in English (round 2 of the convergence, must, regression from e6dcaea): the reach reads
    # through the names, the kinds of procedure and the noun after them, and stops at a conjunction or a verb.
    item('laws-code-named-in-lower-case-after-of-ru-to-en-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', JOB_RU_EN,
         'en', 'responsibility', 'The accountant is liable under the Code of administrative offences.',
         gone=('administrative',), translated=True),
    item('laws-procedure-code-named-in-lower-case-after-of-ru-to-en-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi',
         JOB_RU_EN, 'en', 'responsibility', 'The accountant is liable under the Code of criminal procedure.',
         gone=('criminal',), translated=True),
    guard('laws-law-named-in-lower-case-after-on-ru-to-en-blank', BLANK, JOB_RU_EN_LAW, 'en',
          'The accountant follows the Law on education when training interns.', gone=('education',), translated=True),
    guard('laws-law-named-in-lower-case-after-on-en-blank', BLANK, JOB_EN_LAW, 'en',
          'The accountant follows the Law on education when training interns.', gone=('education',)),
    guard('laws-plural-law-name-after-on-ru-to-en-blank', BLANK, JOB_RU_EN_LAW, 'en',
          'Under the Law on taxes and fees, reports are filed monthly.', gone=('taxes',), translated=True),
    guard('laws-plural-law-name-after-on-en-blank', BLANK, JOB_EN_LAW, 'en',
          'Under the Law on taxes and fees, reports are filed monthly.', gone=('taxes',)),
    guard('laws-law-name-after-the-country-ru-to-en-blank', BLANK, JOB_RU_EN_LAW, 'en',
          'The accountant follows the Law of the Republic of Uzbekistan on education.', gone=('education',),
          translated=True),
    guard('laws-law-name-after-the-country-en-blank', BLANK, JOB_EN_LAW, 'en',
          'The accountant follows the Law of the Republic of Uzbekistan on education.', gone=('education',)),
    guard('laws-code-named-in-lower-case-beside-a-law-ru-to-en-blank', BLANK, JOB_RU_EN_LAW, 'en',
          'The accountant follows the Code of administrative offences.', gone=('administrative',), translated=True),
    guard('laws-code-named-in-lower-case-beside-a-law-en-blank', BLANK, JOB_EN_LAW, 'en',
          'The accountant follows the Code of administrative offences.', gone=('administrative',)),
    gp('laws-law-named-in-lower-case-in-a-grounded-part-en-blank', BLANK, JOB_EN_LAW, 'en',
       'Under the Law on taxes and fees, reports are filed monthly.', gone=('taxes',)),
    guard('laws-the-customers-law-in-lower-case-after-on-en-keep', KEEP,
          'Write a job description for a school teacher in line with the Law on Education.', 'en',
          'The teacher follows the Law on education when planning lessons.'),
    guard('laws-the-customers-law-after-on-ru-to-en-keep', KEEP, JOB_RU_EN_LAW, 'en',
          'The accountant keeps records under the Law on accounting.', translated=True),
    guard('laws-the-customers-law-after-on-en-keep', KEEP, JOB_EN_LAW, 'en',
          'Under the Law on Accounting, records are kept carefully.'),
    guard('laws-the-customers-code-applies-to-an-education-en-keep', KEEP, JOB_EN, 'en',
          'The Labour Code applies to education staff too.'),
    guard('laws-law-named-after-on-the-protection-of-ru-to-en-blank', BLANK, JOB_RU_EN_LAW, 'en',
          'The accountant also follows the Law on the protection of consumer rights.', gone=('consumer',),
          translated=True),
    guard('laws-the-customers-code-protects-consumer-interests-ru-to-en-keep', KEEP, JOB_RU_EN, 'en',
          'The Labour Code of Uzbekistan protects consumer interests too.', translated=True),
    guard('laws-the-customers-law-capitalised-after-on-ru-to-en-keep', KEEP, JOB_RU_EN_LAW, 'en',
          'Under the Law on Accounting, records are kept carefully.', translated=True),
    guard('laws-law-title-in-marks-after-its-stem-ru-to-en-blank', BLANK, JOB_RU_EN_LAW, 'en',
          'The accountant follows the Law "On Education".', gone=('Education',), translated=True),
    guard('laws-the-customers-law-title-in-marks-ru-to-en-keep', KEEP,
          'Составьте должностную инструкцию учителя на английском языке, по Закону «Об образовании».', 'en',
          'The teacher follows the Law "On Education".', translated=True),
    guard('laws-another-law-named-in-russian-after-o-ru-blank', BLANK,
          'Составьте должностную инструкцию бухгалтера, по Закону о бухгалтерском учёте.', 'ru',
          'Бухгалтер соблюдает Закон о защите прав потребителей.', gone=('потребителей',)),
    # A law or a code with no name before its stem is named by every word after its "of" or "on", the country passed
    # over, up to a word that goes on the sentence, a conjunction or a mark: "the Law of the Republic of Uzbekistan on
    # state duty" is the standard English for an Uzbek law, and "the Law on personal data" its bare form (round 3 of
    # the convergence, must; kept at a2005ea and a591d6c, removed at 8146b7c).
    guard('laws-law-of-the-republic-on-state-duty-en-blank', BLANK, JOB_EN_LAW, 'en',
          'The accountant follows the Law of the Republic of Uzbekistan on state duty.', gone=('duty',)),
    guard('laws-law-of-the-republic-on-personal-data-ru-to-en-blank', BLANK, JOB_RU_EN_LAW, 'en',
          'The accountant follows the Law of the Republic of Uzbekistan on personal data.', gone=('personal',),
          translated=True),
    guard('laws-law-of-the-republic-on-state-procurement-uz-to-en-blank', BLANK,
          'Menga ingliz tilida bosh buxgalter uchun lavozim yo‘riqnomasi yozing, Mehnat kodeksi va qonun hujjatlariga '
          'muvofiq ishlaydi.', 'en', 'The accountant follows the Law of the Republic of Uzbekistan on state procurement.',
          gone=('procurement',), translated=True),
    item('laws-law-of-the-republic-on-auditing-activity-in-an-item-en-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi',
         JOB_EN_LAW, 'en', 'general', 'The accountant follows the Law of the Republic of Uzbekistan on auditing activity.',
         gone=('auditing',)),
    gp('laws-law-of-the-republic-on-electronic-commerce-in-an-offer-en-blank', BLANK,
       'Write a commercial offer for our furniture shop in Tashkent; we follow the Law on Accounting and give a 5% '
       'discount.', 'en', 'The accountant follows the Law of the Republic of Uzbekistan on electronic commerce.',
       gone=('electronic',)),
    guard('laws-bare-law-on-personal-data-en-blank', BLANK, JOB_EN_LAW, 'en',
          'The accountant follows the Law on personal data.', gone=('personal',)),
    guard('laws-bare-law-on-the-protection-of-personal-data-en-blank', BLANK, JOB_EN_LAW, 'en',
          'The accountant follows the Law on the protection of personal data.', gone=('personal',)),
    guard('laws-bare-law-on-joint-stock-companies-ru-to-en-blank', BLANK, JOB_RU_EN_LAW, 'en',
          'The accountant applies the Law on joint-stock companies.', gone=('joint',), translated=True),
    guard('laws-bare-code-of-professional-ethics-en-blank', BLANK, JOB_EN_LAW, 'en',
          'The accountant follows the Code of professional ethics.', gone=('ethics',)),
    guard('laws-the-customers-law-of-the-republic-on-accounting-en-keep', KEEP, JOB_EN_LAW, 'en',
          'The accountant follows the Law of the Republic of Uzbekistan on accounting.'),
    guard('laws-the-customers-law-of-the-republic-on-accounting-ru-to-en-keep', KEEP, JOB_RU_EN_LAW, 'en',
          'The accountant follows the Law of the Republic of Uzbekistan on accounting.', translated=True),
    guard('laws-the-customers-law-on-state-duty-of-the-republic-en-keep', KEEP,
          'Write a job description for an accountant in line with the Law on State Duty.', 'en',
          'The accountant follows the Law of the Republic of Uzbekistan on state duty.'),
    guard('laws-the-customers-law-on-accounting-before-a-verb-en-keep', KEEP, JOB_EN_LAW, 'en',
          'The Law on accounting applies to every firm.'),
    guard('laws-the-customers-law-on-accounting-before-a-conjunction-en-keep', KEEP, JOB_EN_LAW, 'en',
          'The Law on accounting and the Labour Code apply.'),
    guard('laws-the-customers-code-on-working-hours-en-keep', KEEP, JOB_EN, 'en',
          'The Labour Code on working hours applies to all staff.'),
    guard('laws-the-customers-code-of-uzbekistan-on-annual-leave-en-keep', KEEP, JOB_EN, 'en',
          'The Labour Code of Uzbekistan on annual leave applies.'),
    guard('laws-the-customers-consumer-rights-law-translated-ru-to-en-keep', KEEP,
          'Составьте должностную инструкцию бухгалтера на английском, по Закону о защите прав потребителей.', 'en',
          'The accountant follows the Law on the protection of consumer rights.', translated=True),
    # A translated law's words not of LAW_NAMES cannot be told from an invented law's: the customer's own law goes.
    guard('laws-the-customers-personal-data-law-translated-ru-to-en-accepted_false_blank', ACCEPTED,
          'Составьте должностную инструкцию бухгалтера на английском, по Закону о персональных данных.', 'en',
          'The accountant follows the Law on personal data.', gone=('personal',), translated=True,
          pair='laws-law-of-the-republic-on-personal-data-ru-to-en-blank'),
    # A word after the customer's law that goes on the sentence with no verb before it reads as the law's name.
    guard('laws-a-noun-after-the-customers-law-on-accounting-en-accepted_false_blank', ACCEPTED, JOB_EN_LAW, 'en',
          'The accountant follows the Law on accounting requirements strictly.', gone=('requirements',),
          pair='laws-bare-law-on-personal-data-en-blank'),
    # A sentence's capitalised first word is no code's name only when it is a known subject (Xodim, Korxona,
    # Buxgalter) or the next word is capitalised too (round 3 of the convergence, from 5c56d4f): "Korporativ
    # boshqaruv kodeksi" is a code's whole name.
    item('laws-capitalised-first-word-of-an-uzbek-code-uz-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', JOB_UZ_ETHICS,
         'uz', 'general', 'Korporativ boshqaruv kodeksiga muvofiq ishlaydi.', gone=('Korporativ',)),
    item('laws-capitalised-first-word-before-a-noun-in-ka-uz-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi',
         JOB_UZ_ETHICS, 'uz', 'general', 'Korporativ etika kodeksiga rioya qiladi.', gone=('Korporativ',)),
    item('laws-subject-before-an-invented-lower-case-code-uz-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi',
         JOB_UZ_ETHICS, 'uz', 'general', 'Xodim korporativ etika kodeksiga rioya qiladi.', gone=('korporativ',)),
    item('laws-the-customers-code-of-ethics-opening-an-item-uz-keep', KEEP, 'pdf.biz.lavozim_yoriqnomasi',
         JOB_UZ_ETHICS, 'uz', 'general', 'Kasbiy etika kodeksiga rioya qiladi.'),
    item('laws-a-subject-before-the-customers-code-of-ethics-uz-keep', KEEP, 'pdf.biz.lavozim_yoriqnomasi',
         JOB_UZ_ETHICS, 'uz', 'general', 'Xodim kasbiy etika kodeksiga rioya qiladi.'),
    item('laws-a-known-subject-before-the-customers-code-uz-keep', KEEP, 'pdf.biz.lavozim_yoriqnomasi', JOB_UZ, 'uz',
         'general', 'Korxona mehnat kodeksiga muvofiq ish yuritadi.'),
    item('laws-a-subject-before-a-capitalised-code-uz-keep', KEEP, 'pdf.biz.lavozim_yoriqnomasi', JOB_UZ, 'uz',
         'general', 'Korxona Mehnat kodeksiga muvofiq ish yuritadi.'),
    guard('laws-capitalised-first-adjective-of-a-russian-code-ru-blank', BLANK, JOB_RU, 'ru',
          'Арбитражный процессуальный кодекс применяется к спорам.', gone=('Арбитражный',)),
    guard('laws-a-preposition-before-the-customers-russian-code-ru-keep', KEEP, JOB_RU, 'ru',
          'Согласно трудовому кодексу работник несёт ответственность.'),

    # ---- A legal sentence by its marks; a situation, a plural act, a convention centre is none (274f7c1, 9cd639f).
    guard('laws-cabinet-resolution-uz-blank', BLANK, ECONOMICS['uz'], 'uz',
          'Vazirlar Mahkamasining qarori bilan dastur tasdiqlandi.', gone=('Mahkamasining',)),
    guard('laws-government-resolution-uz-blank', BLANK, ECONOMICS['uz'], 'uz',
          'Hukumat qarori bilan soliqlar kamaytirildi.', gone=('qarori',)),
    guard('laws-ministry-order-uz-blank', BLANK, ECONOMICS['uz'], 'uz',
          'Moliya vazirligining buyrug‘i bilan stavkalar o‘zgardi.', gone=('buyrug‘i',)),
    guard('laws-capitalised-regulation-ru-blank', BLANK, ECONOMICS['ru'], 'ru',
          'Согласно Положению о лицензировании, фирмы получают лицензию.', gone=('Положению',)),
    guard('laws-regulation-opening-a-sentence-ru-blank', BLANK, ECONOMICS['ru'], 'ru',
          'Положение о налогах было принято в 2020 году.', gone=('Положение о налогах',)),
    guard('laws-geneva-convention-en-blank', BLANK, ECONOMICS['en'], 'en', 'The Geneva Convention protects civilians.',
          gone=('Geneva',)),
    guard('laws-ministry-order-number-en-blank', BLANK, ECONOMICS['en'], 'en',
          'Ministry of Finance order No. 45 sets the rates.', gone=('order No. 45',)),
    body('laws-sonli-ministry-order-in-a-lesson-uz-blank', BLANK, 'pdf.dars_ishlanmasi', LESSON_UZ, 'uz', 'stage_new',
         'Dars Xalq ta’limi vazirligining 2017-yil 6-apreldagi 187-sonli buyrug‘i asosida tashkil etiladi.',
         gone=('187-sonli',)),
    body('laws-ministry-order-dated-in-a-lesson-en-blank', BLANK, 'pdf.dars_ishlanmasi',
         'Make a maths lesson plan for grade 7 on adding fractions, please, in English.', 'en', 'stage_new',
         'In line with the Ministry of Public Education order of 6 April 2017, the lesson lasts 45 minutes.',
         gone=('Ministry of Public Education',)),
    body('laws-convention-in-a-course-paper-uz-blank', BLANK, 'pdf.kurs_ishi', COURSE_UZ, 'uz', 'relevance',
         'Bolalar huquqlari BMTning 1989-yildagi Bola huquqlari to‘g‘risidagi konvensiyasida mustahkamlangan.',
         gone=('konvensiyasida',)),
    body('laws-numbered-regulation-in-a-course-paper-en-blank', BLANK, 'pdf.kurs_ishi',
         'Write a course paper on digital marketing for small businesses in Uzbekistan, about twenty pages.', 'en',
         'relevance', 'Under Regulation 2016/679 of the European Parliament, personal data is protected.',
         gone=('Regulation 2016/679',)),
    guard('laws-situation-of-the-republic-ru-keep', KEEP, ECONOMICS['ru'], 'ru',
          'Экономическое положение Республики Узбекистан улучшилось.'),
    guard('laws-social-situation-ru-keep', KEEP, ECONOMICS['ru'], 'ru',
          'Социально-экономическое положение республики остаётся стабильным.'),
    guard('laws-ministry-studied-a-situation-ru-keep', KEEP, ECONOMICS['ru'], 'ru',
          'Министерство экономики изучило положение малого бизнеса.'),
    guard('laws-situation-opening-a-sentence-ru-keep', KEEP, ECONOMICS['ru'], 'ru',
          'Положение в экономике Республики Узбекистан улучшилось.'),
    guard('laws-situation-of-affairs-opening-a-sentence-ru-keep', KEEP, ECONOMICS['ru'], 'ru',
          'Положение дел в республике остаётся стабильным.'),
    guard('laws-ministry-reports-orders-grew-en-keep', KEEP, ECONOMICS['en'], 'en',
          'The Ministry of Economy reports that orders from small firms grew.'),
    guard('laws-convention-centre-en-keep', KEEP, ECONOMICS['en'], 'en',
          'Parliament discussed the convention centre project.'),
    guard('laws-in-order-to-en-keep', KEEP, ECONOMICS['en'], 'en', 'In order to grow, small firms need credit.'),
    guard('laws-firm-fulfils-orders-en-keep', KEEP, ECONOMICS['en'], 'en', 'The firm fulfils orders within a week.'),
    guard('laws-government-plural-resolutions-uz-keep', KEEP, ECONOMICS['uz'], 'uz',
          'Hukumat iqtisodiyotni qo‘llab-quvvatlash bo‘yicha qator qarorlar qabul qildi.'),
    guard('laws-ministry-data-uz-keep', KEEP, ECONOMICS['uz'], 'uz', 'Vazirlik ma’lumotlariga ko‘ra eksport o‘sdi.'),
    guard('laws-sonli-table-uz-keep', KEEP, ECONOMICS['uz'], 'uz', 'Natijalar 1-sonli jadvalda ko‘rsatilgan.'),
    guard('laws-sonli-school-uz-keep', KEEP, ECONOMICS['uz'], 'uz',
          'Tadqiqot Toshkent shahridagi 45-sonli maktabda o‘tkazildi.'),
    guard('laws-school-statute-in-general-uz-keep', KEEP, ECONOMICS['uz'], 'uz',
          'O‘quvchilar maktab nizomiga rioya qiladi.'),
    guard('laws-newtons-law-uz-keep', KEEP, ECONOMICS['uz'], 'uz',
          'Nyutonning ikkinchi qonuni kuch va tezlanishni bog‘laydi.'),
    # By design (facts docstring): a strong legal stem that cites nothing goes, since it cannot be told from one
    # that cites an invented decree.
    body('laws-strong-stem-citing-nothing-uz-accepted_false_blank', ACCEPTED, 'pdf.mustaqil_ish',
         'Amir Temur davri mavzusida mustaqil ish yozib bering.', 'uz', 'introduction',
         'Amir Temur o‘z davrida ko‘plab farmonlar chiqargan.', gone=('farmonlar',),
         pair='laws-strong-stem-citing-an-invented-decree-uz-blank'),
    body('laws-strong-stem-citing-an-invented-decree-uz-blank', BLANK, 'pdf.mustaqil_ish',
         'Amir Temur davri mavzusida mustaqil ish yozib bering.', 'uz', 'introduction',
         'Prezident yangi farmon bilan Amir Temur muzeyini tashkil etdi.', gone=('farmon',)),

    # ---- Quotations in every mark the three languages use (002e1ce); apostrophes are no marks.
    body('quotes-curly-single-marks-en-blank', BLANK, 'pdf.kurs_ishi', COURSE_UZ, 'en', 'relevance',
         'As Peter Drucker put it, ‘the aim of marketing is to make selling superfluous’.',
         gone=('make selling superfluous',)),
    body('quotes-straight-single-marks-en-blank', BLANK, 'pdf.kurs_ishi', COURSE_UZ, 'en', 'relevance',
         "As Peter Drucker put it, 'the aim of marketing is to make selling superfluous'.",
         gone=('make selling superfluous',)),
    body('quotes-single-guillemets-ru-blank', BLANK, 'pdf.kurs_ishi', COURSE_UZ, 'ru', 'relevance',
         'Как писал Котлер, ‹маркетинг — это искусство удовлетворять потребности с прибылью›.',
         gone=('удовлетворять потребности',)),
    body('quotes-low-single-marks-ru-blank', BLANK, 'pdf.kurs_ishi', COURSE_UZ, 'ru', 'relevance',
         'Как писал Котлер, ‚маркетинг — это искусство находить ценность‘.', gone=('находить ценность',)),
    body('quotes-guillemets-uz-blank', BLANK, 'pdf.kurs_ishi', COURSE_UZ, 'uz', 'relevance',
         'Filip Kotler ta’kidlaganidek, «marketing bu ehtiyojlarni foyda bilan qondirish san’atidir».',
         gone=('ehtiyojlarni foyda bilan',)),
    body('quotes-apostrophes-are-no-marks-en-keep', KEEP, 'pdf.kurs_ishi', COURSE_UZ, 'en', 'relevance',
         "Students' work in the 1990s, the teachers' reviews and the parents' notes were all collected for the "
         "study."),
    body('quotes-uzbek-letters-are-no-marks-uz-keep', KEEP, 'pdf.kurs_ishi', COURSE_UZ, 'uz', 'relevance',
         'O‘quvchilar ta’lim jarayonida o‘z bilimlarini mustahkamlaydi, g‘oyalarni sinab ko‘radi va san’atga '
         'qiziqadi.'),
    body('quotes-a-one-word-name-in-marks-ru-keep', KEEP, 'pdf.kurs_ishi', COURSE_UZ, 'ru', 'relevance',
         'Компании вроде «Артели» активно используют цифровой маркетинг.'),
    body('quotes-lessons-own-phrase-uz-keep', KEEP, 'pdf.dars_ishlanmasi',
         '5-sinf matematika, "Kasrlarni qo‘shish" mavzusida dars ishlanmasi, 45 daqiqa.', 'uz', 'stage_close',
         '5 daqiqa. Refleksiya: «Bugun nimani bildim?» O‘quvchilar javob beradi.'),
    body('quotes-lessons-own-homework-phrase-uz-keep', KEEP, 'pdf.dars_ishlanmasi',
         '5-sinf matematika, "Kasrlarni qo‘shish" mavzusida dars ishlanmasi, 45 daqiqa.', 'uz', 'stage_homework',
         '5 daqiqa. «Darslikdagi shu mavzuga oid mashqlar bajariladi».'),
    question('quotes-question-left-asking-nothing-uz-blank', BLANK, 'pdf.test',
             'Alisher Navoiy ijodi bo‘yicha 8-sinf uchun 5 ta savollik test tuzib bering.', 'uz',
             {'stem': 'Navoiy qaysi asarida «Ilm — zulmatda chiroq, bilim — hayot mazmuni» deb yozgan?',
              'options': ['Xamsa', 'Devon', 'Mezon', 'Muhokamat'], 'answer': 'Xamsa', 'explanation': '', 'marks': 1,
              'topic': ''}, gone=('zulmatda chiroq',)),
    # A title of three words or more is checked as a quotation (632766f: "the guard is not loosened"), and a
    # real work's title cannot be told from an invented saying by its marks.
    question('quotes-work-title-in-a-test-question-uz-accepted_false_blank', ACCEPTED, 'pdf.test',
             'Alisher Navoiy ijodi bo‘yicha 8-sinf uchun 5 ta savollik test tuzib bering.', 'uz',
             {'stem': '«Farhod va Shirin» dostoni kimning qalamiga mansub?',
              'options': ['Alisher Navoiy', 'Bobur', 'Lutfiy', 'Ogahiy'], 'answer': 'Alisher Navoiy',
              'explanation': '', 'marks': 1, 'topic': ''}, gone=('Farhod va Shirin',),
             pair='quotes-question-left-asking-nothing-uz-blank'),

    # ---- A guarded paper's text fact is guarded too (judge: guarded-text-facts-skip-guard).
    fact('guarded-topic-with-invented-quotation-uz-blank', BLANK, 'pdf.mustaqil_ish',
         'Abdulla Qodiriy ijodi mavzusida mustaqil ish yozib bering.', 'uz', 'topic',
         '«Vatan sajdagoh kabi muqaddasdir» degan g‘oya asosida Abdulla Qodiriy ijodi', gone=('sajdagoh',)),
    fact('guarded-topic-with-invented-law-uz-blank', BLANK, 'pdf.mustaqil_ish',
         'Abdulla Qodiriy ijodi mavzusida mustaqil ish yozib bering.', 'uz', 'topic',
         'Abdulla Qodiriy ijodi (Ta’lim to‘g‘risidagi qonun talablari asosida)', gone=('qonun',)),
    fact('guarded-topic-with-invented-organisation-uz-blank', BLANK, 'pdf.kurs_ishi',
         'Kurs ishi yozib bering: tijorat banklarida kredit riskini boshqarish.', 'uz', 'topic',
         'Tijorat banklarida kredit riskini boshqarish («Hamkorbank» ATB misolida)', gone=('Hamkorbank',)),
    fact('guarded-topic-with-invented-quotation-ru-blank', BLANK, 'pdf.mustaqil_ish',
         'Самостоятельная работа по экономике на тему плановой экономики.', 'ru', 'topic',
         '«Экономика должна быть экономной» как лозунг плановой экономики', gone=('должна быть экономной',)),
    fact('guarded-topic-with-invented-quotation-en-blank', BLANK, 'pdf.mustaqil_ish',
         'An essay on Adam Smith and market economics, about ten pages.', 'en', 'topic',
         'Adam Smith and “the invisible hand of the market” today', gone=('invisible hand of the market',)),
    fact('guarded-topic-naming-the-customers-constitution-ru-keep', KEEP, 'pdf.mustaqil_ish',
         'Самостоятельная работа: Конституция Узбекистана и права человека.', 'ru', 'topic',
         'Конституция Республики Узбекистан и права человека'),
    fact('guarded-topic-naming-the-customers-constitution-en-keep', KEEP, 'pdf.mustaqil_ish',
         'An essay on the US Constitution and its amendments, about ten pages.', 'en', 'topic',
         'The First Amendment to the United States Constitution'),
    fact('guarded-topic-naming-the-customers-code-uz-keep', KEEP, 'pdf.mustaqil_ish',
         'Mehnat kodeksi bo‘yicha mustaqil ish yozing, talabalar uchun.', 'uz', 'topic',
         'Mehnat kodeksining asosiy qoidalari'),
    fact('guarded-topic-naming-the-customers-constitution-uz-keep', KEEP, 'pdf.mustaqil_ish',
         'Konstitutsiya asoslari mavzusida mustaqil ish yozib bering.', 'uz', 'topic',
         'O‘zbekiston Respublikasi Konstitutsiyasining asosiy tamoyillari'),
    fact('guarded-topic-short-work-title-uz-keep', KEEP, 'pdf.mustaqil_ish',
         'Navoiyning Xamsa asari mavzusida mustaqil ish yozib bering.', 'uz', 'topic', '«Xamsa» dostonlari'),
    fact('guarded-topic-newtons-law-uz-keep', KEEP, 'pdf.konspekt',
         'Fizika fanidan Nyutonning ikkinchi qonuni mavzusida konspekt yozib bering.', 'uz', 'topic',
         'Nyutonning ikkinchi qonuni'),

    # ---- Handles and sites on any ending are contact details found whole (4bcbbd9).
    fact('contacts-invented-handle-fact-uz-blank', BLANK, 'pdf.xat.ishga_kirish',
         'Ishga kirish uchun xat yozing. Ismim Karimov Aziz, sotuv menejeri lavozimiga. Telefonim +998 90 123 45 67.',
         'uz', 'other_contact', '@aziz_karimov', gone=('@aziz_karimov',)),
    body('contacts-invented-handle-and-site-in-a-letter-uz-blank', BLANK, 'pdf.xat.ishga_kirish',
         'Ishga kirish uchun xat yozing. Ismim Karimov Aziz, sotuv menejeri lavozimiga. Telefonim +998 90 123 45 67.',
         'uz', 'closing', 'Men bilan telegram orqali @aziz_karimov yoki aziz-karimov.kz saytim orqali '
         'bog‘lanishingiz mumkin.', gone=('@aziz_karimov', 'aziz-karimov.kz')),
    fact('contacts-invented-shop-site-uz-blank', BLANK, 'pdf.biz.tijorat_taklifi',
         'Tijorat taklifi tuzing: "Oqtosh Mebel" MChJ, ofis mebeli. Stol 1 200 000 so‘m. Aloqa: +998 71 200 10 10.',
         'uz', 'seller_website', 'oqtoshmebel.shop', gone=('oqtoshmebel.shop',)),
    fact('contacts-the-customers-handle-from-a-link-uz-keep', KEEP, 'pdf.xat.ishga_kirish',
         'Ishga kirish uchun xat yozing. Ismim Karimov Aziz, sotuv menejeri lavozimiga. Telegram: t.me/aziz_karimov.',
         'uz', 'other_contact', '@aziz_karimov'),
    fact('contacts-invented-handle-fact-en-blank', BLANK, 'pdf.xat.ishga_kirish', COVER_EN, 'en', 'other_contact',
         '@malika_sales', gone=('@malika_sales',)),
    fact('contacts-the-customers-site-en-keep', KEEP, 'pdf.xat.ishga_kirish',
         COVER_EN + ' My profile: linkedin.com/in/malika-qodirova', 'en', 'other_contact',
         'linkedin.com/in/malika-qodirova'),
    gp('contacts-initial-glued-to-a-surname-is-no-site-uz-keep', KEEP,
       'Hisobotni S.Xolmatov tayyorlaydi, ofis sh.Chilonzor tumanida.', 'uz',
       'Hisobotni S.Xolmatov tayyorlaydi.'),

    # ---- A class letter the customer never wrote (4b19d8e, b072a59); "1C" and "3D" name no class.
    fact('class-letter-bare-in-the-grade-uz-blank', BLANK, 'pdf.dars_ishlanmasi', LESSON_UZ, 'uz', 'grade', '7B',
         gone=('7B',)),
    fact('class-letter-before-a-hyphenated-class-word-uz-blank', BLANK, 'pdf.dars_ishlanmasi', LESSON_UZ, 'uz', 'grade',
         '7B-sinf', gone=('7B',)),
    fact('class-letter-quoted-uz-blank', BLANK, 'pdf.dars_ishlanmasi', LESSON_UZ, 'uz', 'grade', '7-«B» sinf',
         gone=('«B»',)),
    fact('class-letter-after-year-ru-to-en-blank', BLANK, 'pdf.dars_ishlanmasi', LESSON_RU_EN, 'en', 'grade',
         'Year 7B', gone=('7B',), translated=True),
    fact('class-letter-after-grade-ru-to-en-blank', BLANK, 'pdf.dars_ishlanmasi', LESSON_RU_EN, 'en', 'grade',
         'Grade 7B', gone=('7B',), translated=True),
    fact('class-letter-latin-b-for-cyrillic-ve-ru-to-uz-blank', BLANK, 'pdf.dars_ishlanmasi', LESSON_RU_V, 'uz',
         'grade', '7-«B» sinf', gone=('«B»',), translated=True),
    fact('class-letter-invented-in-a-russian-paper-uz-to-ru-blank', BLANK, 'pdf.dars_ishlanmasi', LESSON_UZ_RU, 'ru',
         'grade', '7 «Б» класс', gone=('«Б»',), translated=True),
    fact('class-letter-none-in-a-russian-paper-uz-to-ru-keep', KEEP, 'pdf.dars_ishlanmasi', LESSON_UZ_RU, 'ru',
         'grade', '7 класс', translated=True),
    fact('class-letter-year-label-without-a-letter-ru-to-en-keep', KEEP, 'pdf.dars_ishlanmasi', LESSON_RU_EN, 'en',
         'grade', 'Year 7', translated=True),
    fact('class-letter-the-customers-cyrillic-ve-ru-to-uz-keep', KEEP, 'pdf.dars_ishlanmasi', LESSON_RU_V, 'uz',
         'grade', '7-«V» sinf', translated=True),
    fact('class-letter-the-customers-letter-uz-keep', KEEP, 'pdf.dars_ishlanmasi',
         '7-«A» sinf uchun matematika fanidan "Kasrlarni qo‘shish" mavzusida dars ishlanmasi tuzing.', 'uz', 'grade',
         '7-«A» sinf'),
    fact('class-letter-the-customers-cyrillic-a-ru-to-uz-keep', KEEP, 'pdf.dars_ishlanmasi',
         'Составьте план урока математики на узбекском языке для 7 «А» класса, тема: сложение дробей.', 'uz',
         'grade', '7-«A» sinf', translated=True),
    fact('class-letter-1c-position-ru-to-uz-keep', KEEP, 'pdf.xat.ishga_kirish', COVER_RU_1C_UZ, 'uz', 'position',
         '1C dasturchisi', translated=True),
    fact('class-letter-1c-position-ru-to-en-keep', KEEP, 'pdf.xat.ishga_kirish', COVER_RU_1C_EN, 'en', 'position',
         '1C Programmer', translated=True),
    fact('class-letter-3d-position-uz-keep', KEEP, 'pdf.xat.ishga_kirish',
         '3D dizayner lavozimiga ishga kirish xati yozing. Ismim Karimov Aziz, tajribam bor.', 'uz', 'position',
         '3D dizayner'),
    fact('class-letter-3d-position-invented-uz-blank', BLANK, 'pdf.xat.ishga_kirish',
         'Grafik dizayner lavozimiga ishga kirish xati yozing. Ismim Karimov Aziz, tajribam bor.', 'uz', 'position',
         '3D dizayner', gone=('3D',)),
    supported('class-letter-house-number-is-no-class-uz-keep', KEEP, 'Ofis manzili: Chilonzor 9-kvartal, 12A uy.',
              'uz', 'place', 'Chilonzor 9-kvartal, 12A uy'),
    # A value of a number and a letter alone is a class only in a grade's or a class's field: the customer's Cyrillic
    # "1С" is a line's or a slot's Latin "1C" (round 2 of the convergence, regression from fe4c307).
    supported('class-letter-1c-whole-value-of-a-line-ru-keep', KEEP,
              'Напишите презентацию о компании, мы партнёр 1С и внедряем 1С: Бухгалтерию.', 'ru', 'line', '1C'),
    fact('class-letter-1c-whole-value-of-a-position-ru-to-uz-keep', KEEP, 'pdf.xat.ishga_kirish', COVER_RU_1C_UZ, 'uz',
         'position', '1C', translated=True),
    fact('class-letter-bare-in-a-tests-class-level-uz-blank', BLANK, 'pdf.test',
         '7-sinf uchun matematika testi tuzing, 10 ta savol bo‘lsin.', 'uz', 'class_level', '7B', gone=('7B',)),
    fact('class-letter-bare-in-a-notes-level-uz-blank', BLANK, 'pdf.konspekt',
         '7-sinf uchun fizika fanidan konspekt yozing, mavzu: kuch.', 'uz', 'level', '7B', gone=('7B',)),
    # A number and a letter are a class too as a class label's value, beside a pupil's word, after a number the
    # customer wrote as their class, and anywhere in a grade's field (round 3 of the convergence, must, regression
    # from 0157a2a); "1C" and "3D" stay where no class is written.
    fact('class-letter-as-a-labels-value-in-the-grade-uz-blank', BLANK, 'pdf.dars_ishlanmasi', LESSON_UZ, 'uz', 'grade',
         'Sinf: 7B', gone=('7B',)),
    fact('class-letter-beside-a-subject-in-the-grade-uz-blank', BLANK, 'pdf.dars_ishlanmasi', LESSON_UZ, 'uz', 'grade',
         '7B, matematika', gone=('7B',)),
    fact('class-letter-after-the-customers-class-number-in-a-subject-uz-blank', BLANK, 'pdf.dars_ishlanmasi', LESSON_UZ,
         'uz', 'subject', '7B matematika', gone=('7B',)),
    fact('class-letter-beside-a-pupils-word-uz-blank', BLANK, 'pdf.xat.tavsifnoma', REFERENCE_UZ, 'uz', 'subject_role',
         '11A o‘quvchisi', gone=('11A',)),
    fact('class-letter-beside-a-students-word-en-blank', BLANK, 'pdf.xat.tavsiya',
         'Please write a recommendation letter for my former student Malika Qodirova, who studied in grade 11 at our '
         'school and is applying for a master’s programme.', 'en', 'candidate_status', 'an 11A student',
         gone=('11A',)),
    body('class-letter-beside-a-pupils-word-in-a-grounded-part-uz-blank', BLANK, 'pdf.xat.tavsifnoma', REFERENCE_UZ,
         'uz', 'identity', 'Qodirova Malika 11-«A» sinf o‘quvchisi.', gone=('«A»',)),
    fact('class-letter-none-beside-a-pupils-word-uz-keep', KEEP, 'pdf.xat.tavsifnoma', REFERENCE_UZ, 'uz',
         'subject_role', '11-sinf o‘quvchisi'),
    body('class-letter-none-in-a-grounded-part-uz-keep', KEEP, 'pdf.xat.tavsifnoma', REFERENCE_UZ, 'uz', 'identity',
         'Qodirova Malika 11-sinf o‘quvchisi.'),
    fact('class-letter-the-customers-letter-beside-a-pupils-word-uz-keep', KEEP, 'pdf.xat.tavsifnoma',
         REFERENCE_UZ.replace('11-sinf', '11-«A» sinf'), 'uz', 'subject_role', '11A o‘quvchisi'),
    supported('class-letter-1c-position-beside-the-customers-class-number-ru-keep', KEEP,
              'Напишите презентацию для 1 класса о профессиях, мой папа программист 1С.', 'ru', 'line',
              '1C dasturchisi'),

    # ---- A guarded title's labelled author tail (0e3a40f).
    title('author-tail-vypolnila-ru-blank', BLANK, 'pdf.mustaqil_ish',
          'Самостоятельная работа по экономике, тема: инфляция и её последствия.', 'ru',
          'Инфляция и её последствия. Выполнила: Каримова Д.', gone=('Каримова',)),
    title('author-tail-sostavila-ru-blank', BLANK, 'pdf.mustaqil_ish',
          'Самостоятельная работа по экономике, тема: инфляция и её последствия.', 'ru',
          'Инфляция и её последствия. Составила: Каримова Д.', gone=('Каримова',)),
    title('author-tail-maruzachi-uz-blank', BLANK, 'pdf.konspekt', 'Iqtisodiyot fanidan konspekt, mavzu: inflyatsiya.',
          'uz', 'Inflyatsiya. Ma’ruzachi: dotsent Rahimov B.', gone=('Rahimov',)),
    title('author-tail-talaba-uz-blank', BLANK, 'pdf.mustaqil_ish',
          'Iqtisodiyotdan mustaqil ish, mavzu: inflyatsiya va uning oqibatlari.', 'uz',
          'Inflyatsiya va uning oqibatlari. Talaba: Karimova D.', gone=('Karimova',)),
    title('author-tail-student-en-blank', BLANK, 'pdf.kurs_ishi',
          'Course paper on economics: inflation and its consequences.', 'en',
          'Inflation and its consequences. Student: Karimova D.', gone=('Karimova',)),
    title('author-tail-by-en-blank', BLANK, 'pdf.kurs_ishi',
          'Course paper on economics: inflation and its consequences.', 'en',
          'Inflation and its consequences by Dilnoza Karimova', gone=('Karimova',)),
    # A bare "by" tail is an author's when it has a surname's shape or initials, or a word that is no common word
    # (round 2 of the convergence): a common given name beside the surname no longer keeps it.
    title('author-tail-by-a-common-given-name-and-a-surname-en-blank', BLANK, 'pdf.kurs_ishi',
          'Course paper on economics: inflation and its consequences.', 'en',
          'Inflation and its consequences by Malika Karimova', gone=('Karimova',)),
    title('author-tail-by-a-given-name-and-a-male-surname-en-blank', BLANK, 'pdf.kurs_ishi',
          'Course paper on economics: inflation and its consequences.', 'en',
          'Inflation and its consequences by Aziz Karimov', gone=('Karimov',)),
    title('author-tail-by-an-english-name-en-blank', BLANK, 'pdf.kurs_ishi',
          'Course paper on economics: inflation and its consequences.', 'en',
          'Inflation and its consequences by Peter Brown', gone=('Brown',)),
    title('author-tail-by-initials-en-blank', BLANK, 'pdf.kurs_ishi',
          'Course paper on economics: inflation and its consequences.', 'en',
          'Inflation and its consequences by D. R. Hall', gone=('Hall',)),
    title('author-tail-by-a-word-like-given-name-and-a-surname-en-blank', BLANK, 'pdf.kurs_ishi',
          'Course paper on economics: inflation and its consequences.', 'en',
          'Inflation and its consequences by Hikmat Karimov', gone=('Karimov',)),
    title('author-tail-by-objectives-en-keep', KEEP, 'pdf.kurs_ishi',
          'Course paper on management: management by objectives in small firms.', 'en',
          'Management by Objectives'),
    title('author-tail-by-doing-en-keep', KEEP, 'pdf.kurs_ishi',
          'Course paper on pedagogy: learning by doing in primary schools.', 'en', 'Learning by Doing'),
    title('author-tail-by-a-title-phrase-en-keep', KEEP, 'pdf.kurs_ishi',
          'Course paper on economics: growth driven by foreign investment.', 'en',
          'Growth Driven by Foreign Investment'),
    title('author-tail-label-opening-a-topic-ru-keep', KEEP, 'pdf.mustaqil_ish',
          'Самостоятельная работа по менеджменту, тема: руководитель, его роль и функции.', 'ru',
          'Руководитель: роль и функции'),
    title('author-tail-label-opening-a-topic-uz-keep', KEEP, 'pdf.mustaqil_ish',
          'Pedagogika fanidan mustaqil ish, mavzu: o‘qituvchi kasbi va uning mas’uliyati.', 'uz',
          'O‘qituvchi: kasb va mas’uliyat'),
    title('author-tail-label-opening-a-topic-en-keep', KEEP, 'pdf.mustaqil_ish',
          'An essay on management: the supervisor, the role and its functions.', 'en',
          'Supervisor: role and functions'),
    title('author-tail-the-customers-author-ru-keep', KEEP, 'pdf.mustaqil_ish',
          'Самостоятельная работа по экономике, тема: инфляция и её последствия. Выполнила Каримова Д.', 'ru',
          'Инфляция и её последствия. Выполнила: Каримова Д.'),

    # ---- References: only the customer's sources, translated ones by their people (02bba31, topic echo).
    item('sources-invented-full-name-author-ru-to-uz-blank', BLANK, 'pdf.kurs_ishi', COURSE_RU_UZ, 'uz', 'references',
         'Karimov Abdulla. Raqamli marketing strategiyalari. — Toshkent: Fan.', gone=('Abdulla',), translated=True),
    item('sources-invented-full-name-author-ru-to-en-blank', BLANK, 'pdf.mustaqil_ish', ESSAY_RU_EN, 'en',
         'references', 'Kotler, Philip. Marketing Management. Pearson Education.', gone=('Kotler',), translated=True),
    item('sources-invented-editor-ru-to-en-blank', BLANK, 'pdf.mustaqil_ish', ESSAY_RU_EN, 'en', 'references',
         'Digital Marketing: Strategy, Implementation and Practice. Edited by D. Chaffey. Pearson.',
         gone=('Chaffey',), translated=True),
    item('sources-invented-authors-in-apa-form-ru-to-en-blank', BLANK, 'pdf.mustaqil_ish', ESSAY_RU_EN, 'en',
         'references', 'Chaffey, D., & Ellis-Chadwick, F. Digital Marketing. Pearson.', gone=('Chaffey',),
         translated=True),
    item('sources-the-topic-echoed-as-a-title-uz-blank', BLANK, 'pdf.kurs_ishi', COURSE_UZ, 'uz', 'references',
         'Raqamli marketing strategiyalari: o‘quv qo‘llanma.', gone=('o‘quv qo‘llanma',)),
    # Round 4: a paper's source is the customer's word for word, its publisher's and pages' words aside.
    item('sources-genres-for-sources-uz-blank', BLANK, 'pdf.kurs_ishi', COURSE_UZ, 'uz', 'references',
         'Marketing bo‘yicha darsliklar va o‘quv qo‘llanmalar.', gone=('darsliklar',)),
    item('sources-the-customers-book-with-its-publishers-words-uz-keep', KEEP, 'pdf.kurs_ishi',
         COURSE_UZ + ' Adabiyot: Karimov A. Raqamli marketing. Toshkent: Fan, 2021.', 'uz', 'references',
         'Karimov A. Raqamli marketing. — Toshkent: Fan nashriyoti, 2021.'),
    item('sources-invented-author-with-initials-uz-blank', BLANK, 'pdf.kurs_ishi', COURSE_UZ, 'uz', 'references',
         'Karimov A. Raqamli marketing. — T.: Fan, 2021.', gone=('Karimov',)),
    # A GOST reference adds its genre to the customer's own book ("darslik", "o‘quv qo‘llanma", "учебник", "учебное
    # пособие"): kept when its author and title are theirs (round 2 of the convergence, regression from 764d221).
    item('sources-the-customers-book-with-a-genre-uz-keep', KEEP, 'pdf.kurs_ishi', COURSE_UZ_BOOKS, 'uz', 'references',
         'Karimov A. Raqamli marketing: darslik. — T.: Fan, 2021.'),
    item('sources-the-customers-book-with-a-two-word-genre-uz-keep', KEEP, 'pdf.kurs_ishi', COURSE_UZ_BOOKS, 'uz',
         'references', 'Kotler F. Marketing asoslari: o‘quv qo‘llanma. — Toshkent, 2019.'),
    item('sources-the-customers-book-with-a-genre-ru-keep', KEEP, 'pdf.kurs_ishi', COURSE_RU_BOOKS, 'ru', 'references',
         'Котлер Ф. Основы маркетинга: учебник. — М.: Вильямс, 2019.'),
    item('sources-the-customers-book-with-a-two-word-genre-ru-keep', KEEP, 'pdf.kurs_ishi', COURSE_RU_BOOKS, 'ru',
         'references', 'Ламбен Ж.-Ж. Менеджмент, ориентированный на рынок: учебное пособие. — СПб.: Питер, 2018.'),
    item('sources-the-customers-book-with-a-genre-en-keep', KEEP, 'pdf.kurs_ishi',
         'Course paper on marketing. Sources: Kotler P. Principles of Marketing. Pearson, 2019.', 'en', 'references',
         'Kotler P. Principles of Marketing: a textbook. Pearson, 2019.'),
    item('sources-invented-author-with-a-genre-uz-blank', BLANK, 'pdf.kurs_ishi', COURSE_UZ_BOOKS, 'uz', 'references',
         'Saidov B. Raqamli marketing: darslik. — T.: Fan, 2021.', gone=('Saidov',)),
    item('sources-the-customers-author-with-an-invented-title-and-genre-uz-blank', BLANK, 'pdf.kurs_ishi',
         COURSE_UZ_BOOKS, 'uz', 'references', 'Karimov A. Brend strategiyasi: darslik. — T.: Fan, 2021.',
         gone=('Brend',)),
    item('sources-an-authorless-topic-with-a-genre-ru-blank', BLANK, 'pdf.kurs_ishi', COURSE_RU_BOOKS, 'ru',
         'references', 'Основы маркетинга: учебное пособие.', gone=('пособие',)),
    item('sources-the-customers-book-translated-ru-to-uz-keep', KEEP, 'pdf.kurs_ishi', COURSE_RU_UZ_NAMED, 'uz',
         'references', 'Karimov Abdulla. Raqamli marketing strategiyalari. — Toshkent: Fan.', translated=True),
    item('sources-the-customers-book-ru-to-en-keep', KEEP, 'pdf.mustaqil_ish', ESSAY_RU_EN_NAMED, 'en', 'references',
         'Kotler F. Marketing Management.', translated=True),
    item('sources-the-customers-authorless-book-uz-keep', KEEP, 'pdf.kurs_ishi',
         COURSE_UZ + ' Adabiyot: "Raqamli marketing strategiyalari" o‘quv qo‘llanmasi.', 'uz', 'references',
         'Raqamli marketing strategiyalari: o‘quv qo‘llanma.'),
    # 02bba31: a full name a translation respells beyond the fold ("Philip" for "Филип") goes, as an invented one.
    item('sources-the-customers-author-respelled-beyond-the-fold-ru-to-en-accepted_false_blank', ACCEPTED,
         'pdf.mustaqil_ish', ESSAY_RU_EN_NAMED, 'en', 'references', 'Kotler, Philip. Marketing Management.',
         gone=('Philip',), translated=True, pair='sources-invented-full-name-author-ru-to-en-blank'),

    # ---- A table's figure reused for a line the customer never gave (judge: value-reuse-in-tables).
    cell('tables-invented-budget-line-with-a-reused-figure-uz-blank', BLANK, 'pdf.biz.marketing_reja',
         '“Gulzor” kafesi uchun 2027-yil 1-chorak marketing rejasi. Byudjet 12 mln so‘m: Instagram reklama 5 mln, '
         'bloger 3 mln, flayer 2 mln.', 'uz', 'budget', 'Telegram kanal', row=('2 mln so‘m', ''), gone=('Telegram',)),
    cell('tables-the-customers-budget-line-uz-keep', KEEP, 'pdf.biz.marketing_reja',
         '“Gulzor” kafesi uchun 2027-yil 1-chorak marketing rejasi. Byudjet 12 mln so‘m: Instagram reklama 5 mln, '
         'bloger 3 mln, flayer 2 mln.', 'uz', 'budget', 'Instagram reklama', row=('5 mln so‘m', '')),
]

# ---- words/names.txt is read by the paper's language (round 3 of the convergence, should, from db19bc0): an English
# given name refuses no Uzbek word in an Uzbek paper; a name that is a word of its own paper's language is still held,
# and each such collision kept is an accepted false blank beside the leak it pays for.
PLAN_UZ_EN = ('Menga ingliz tilida nonvoyxona uchun biznes-reja yozing. Toshkentda issiq non va somsa sotamiz, '
              'o‘z mablag‘im 120 mln so‘m, xodimlar: novvoy, sotuvchi, kassir.')
CAFE_UZ = ('Toshkentda kichik kafe ochish uchun biznes-reja yozing. Choy, sharbat va shirinliklar sotamiz. '
           'O‘z mablag‘im 150 mln so‘m.')
CAFE_RU_EN = ('Напишите бизнес-план кафе в Ташкенте на английском языке. Чай, соки и выпечка. Собственные средства '
              '150 млн сумов.')
OFFER_MEBEL_UZ = 'Mebel do‘konimiz uchun tijorat taklifi yozing, Toshkentda oshxona mebeli sotamiz, chegirma 10 foiz.'
CASES += [
    # The final re-check (must 1) found these keeps let the same words through as invented people in an Uzbek paper
    # ('Tom yangi filialni ochdi.'): names.txt refuses a Latin word in every paper again, so each is now an accepted
    # false blank beside the leak it pays for.
    cell('names-english-given-name-joy-is-an-uzbek-word-in-a-cost-cell-uz-accepted_false_blank', ACCEPTED,
         'pdf.biz.biznes_reja', PLAN_UZ, 'uz', 'finance_costs', 'Joy ijarasi', gone=('Joy',),
         pair='names-english-name-joy-in-an-uzbek-paper-uz-blank'),
    body('names-english-given-name-joy-is-an-uzbek-word-opening-a-sentence-uz-accepted_false_blank', ACCEPTED,
         'pdf.biz.biznes_reja', PLAN_UZ, 'uz', 'operations', 'Joy tanlashda transport qulayligi hisobga olindi.',
         gone=('Joy',), pair='names-english-name-joy-in-an-uzbek-paper-uz-blank'),
    cell('names-english-given-name-tom-is-an-uzbek-word-uz-accepted_false_blank', ACCEPTED, 'pdf.biz.biznes_reja',
         PLAN_UZ, 'uz', 'finance_costs', 'Tom yopish ishlari', gone=('Tom',),
         pair='names-english-name-tom-in-an-uzbek-paper-uz-blank'),
    body('names-english-given-name-sara-is-an-uzbek-word-uz-accepted_false_blank', ACCEPTED, 'pdf.biz.biznes_reja',
         PLAN_UZ, 'uz', 'product', 'Sara navli bug‘doy unidan non yopamiz.', gone=('Sara',),
         pair='names-english-name-sara-in-an-uzbek-paper-uz-blank'),
    gp('names-english-surname-kim-is-an-uzbek-word-uz-accepted_false_blank', ACCEPTED, UZ_NONE, 'uz',
       'Kim javobgar ekanini direktor belgilaydi.', gone=('Kim',),
       pair='names-english-name-kim-in-an-uzbek-paper-uz-blank'),
    # These five ids are bbeccfc's and keep their names because tests/core_tests.txt is append-only, but they no
    # longer pin the Uzbek sense of a names.txt word: that sense alone is blanked now (the accepted false blanks
    # above). What they pin is that the same words stay where the customer wrote them in the brief ("joy ijaraga",
    # "Tom yopish", "Sara navli", "Kim javobgar"), since the customer's own words are never held.
    cell('names-english-given-name-joy-is-an-uzbek-word-in-a-cost-cell-uz-keep', KEEP, 'pdf.biz.biznes_reja',
         PLAN_UZ + ' Do‘kon uchun joy ijaraga olamiz.', 'uz', 'finance_costs', 'Joy ijarasi'),
    body('names-english-given-name-joy-is-an-uzbek-word-opening-a-sentence-uz-keep', KEEP, 'pdf.biz.biznes_reja',
         PLAN_UZ + ' Do‘kon uchun joy ijaraga olamiz.', 'uz', 'operations',
         'Joy tanlashda transport qulayligi hisobga olindi.'),
    cell('names-english-given-name-tom-is-an-uzbek-word-uz-keep', KEEP, 'pdf.biz.biznes_reja',
         PLAN_UZ + ' Tom yopish ishlari ham kerak.', 'uz', 'finance_costs', 'Tom yopish ishlari'),
    body('names-english-given-name-sara-is-an-uzbek-word-uz-keep', KEEP, 'pdf.biz.biznes_reja',
         PLAN_UZ + ' Sara navli bug‘doy unidan foydalanamiz.', 'uz', 'product', 'Sara navli bug‘doy unidan non yopamiz.'),
    gp('names-english-surname-kim-is-an-uzbek-word-uz-keep', KEEP,
       UZ_NONE + ' Kim javobgar ekanini direktor belgilaydi.', 'uz', 'Kim javobgar ekanini direktor belgilaydi.'),
    body('names-english-given-name-joy-in-an-english-paper-uz-to-en-blank', BLANK, 'pdf.biz.biznes_reja', PLAN_UZ_EN,
         'en', 'operations', 'Joy manages the shop floor.', gone=('Joy',), translated=True),
    gp('names-english-given-name-tom-in-an-english-paper-en-blank', BLANK, EN_NONE, 'en', 'Tom supervised the bakers.',
       gone=('Tom',)),
    gp('names-english-given-name-sara-in-an-english-paper-en-blank', BLANK, EN_NONE, 'en',
       'Sara handled the accounts.', gone=('Sara',)),
    gp('names-english-given-name-grace-in-an-uzbek-paper-uz-blank', BLANK, UZ_NONE, 'uz', 'Grace kassada ishlaydi.',
       gone=('Grace',)),
    gp('names-uzbek-given-name-said-in-an-english-paper-en-blank', BLANK, EN_NONE, 'en', 'Said handled the accounts.',
       gone=('Said',)),
    # An Uzbek given name that is an Uzbek word, in an Uzbek paper.
    gp('names-uzbek-given-name-asal-uz-blank', BLANK, UZ_NONE, 'uz', 'Asal kassada ishlaydi.', gone=('Asal',)),
    cell('names-uzbek-given-name-asal-is-honey-in-a-product-cell-uz-accepted_false_blank', ACCEPTED,
         'pdf.biz.biznes_reja', CAFE_UZ, 'uz', 'product', 'Asal va murabbo', gone=('Asal',),
         pair='names-uzbek-given-name-asal-uz-blank'),
    gp('names-uzbek-given-name-erkin-uz-blank', BLANK, UZ_NONE, 'uz', 'Erkin loyihani boshqaradi.', gone=('Erkin',)),
    body('names-uzbek-given-name-erkin-is-free-opening-a-sentence-uz-accepted_false_blank', ACCEPTED,
         'pdf.biz.biznes_reja', PLAN_UZ, 'uz', 'market_customers', 'Erkin raqobat sharoitida narx muhim.',
         gone=('Erkin',), pair='names-uzbek-given-name-erkin-uz-blank'),
    gp('names-uzbek-given-name-kumush-uz-blank', BLANK, UZ_NONE, 'uz', 'Kumush sotuvni boshqaradi.', gone=('Kumush',)),
    body('names-uzbek-given-name-kumush-is-silver-opening-a-sentence-uz-accepted_false_blank', ACCEPTED,
         'pdf.biz.biznes_reja', PLAN_UZ, 'uz', 'product', 'Kumush rangli qadoqda sotamiz.', gone=('Kumush',),
         pair='names-uzbek-given-name-kumush-uz-blank'),
    gp('names-uzbek-given-name-aziz-uz-blank', BLANK, UZ_NONE, 'uz', 'Aziz loyihani boshqaradi.', gone=('Aziz',)),
    # "Aziz" before a plural and the mark of an address is the letter's "dear", never a person (round 3 of the
    # convergence: an offer's "Aziz hamkorlar, ..." was blanked).
    body('names-aziz-addressing-plural-readers-uz-keep', KEEP, 'pdf.biz.tijorat_taklifi', OFFER_MEBEL_UZ, 'uz',
         'opening', 'Aziz hamkorlar, sizga oshxona mebellarimizni taklif qilamiz.'),
    gp('names-aziz-addressing-plural-readers-with-a-possessive-uz-keep', KEEP, UZ_NONE, 'uz',
       'Aziz mijozlarimiz! Issiq non har kuni tayyor.'),
    gp('names-aziz-before-a-plural-with-no-address-mark-uz-blank', BLANK, UZ_NONE, 'uz',
       'Aziz hamkorlar bilan uchrashdi.', gone=('Aziz',)),
    gp('names-aziz-before-a-comma-uz-blank', BLANK, UZ_NONE, 'uz', 'Aziz, hamkorlar bilan uchrashing.',
       gone=('Aziz',)),
    gp('names-uzbek-given-name-said-in-an-english-paper-is-a-verb-en-accepted_false_blank', ACCEPTED, EN_NONE, 'en',
       'Said differently, our prices stay low.', gone=('Said',),
       pair='names-uzbek-given-name-said-in-an-english-paper-en-blank'),
    # An English surname, given name or brand that is an English word, in an English paper.
    cell('names-english-surname-baker-is-a-trade-in-a-team-cell-uz-to-en-accepted_false_blank', ACCEPTED,
         'pdf.biz.biznes_reja', PLAN_UZ_EN, 'en', 'team', 'Baker', gone=('Baker',), translated=True,
         pair='names-english-surname-baker-en-blank'),
    cell('names-english-surname-cook-is-a-trade-in-a-team-cell-ru-to-en-accepted_false_blank', ACCEPTED,
         'pdf.biz.biznes_reja', CAFE_RU_EN, 'en', 'team', 'Cook', gone=('Cook',), translated=True,
         pair='names-english-surname-cook-en-blank'),
    cell('names-english-surname-black-is-a-colour-in-a-product-cell-ru-to-en-accepted_false_blank', ACCEPTED,
         'pdf.biz.biznes_reja', CAFE_RU_EN, 'en', 'product', 'Black tea', gone=('Black',), translated=True,
         pair='names-english-surname-black-en-blank'),
    cell('names-english-surname-green-is-a-colour-in-a-product-cell-ru-to-en-accepted_false_blank', ACCEPTED,
         'pdf.biz.biznes_reja', CAFE_RU_EN, 'en', 'product', 'Green tea', gone=('Green',), translated=True,
         pair='names-english-surname-green-en-blank'),
    cell('names-brand-apple-is-a-fruit-in-a-product-cell-ru-to-en-accepted_false_blank', ACCEPTED,
         'pdf.biz.biznes_reja', CAFE_RU_EN, 'en', 'product', 'Apple juice', gone=('Apple',), translated=True,
         pair='names-brand-apple-en-blank'),
    body('names-english-surname-stone-is-a-material-uz-to-en-accepted_false_blank', ACCEPTED, 'pdf.biz.biznes_reja',
         PLAN_UZ_EN, 'en', 'product', 'Stone oven bread is baked every morning.', gone=('Stone',), translated=True,
         pair='names-english-surname-stone-en-blank'),
]
for word, sentence in (('Price', 'Price is our main advantage over supermarkets.'),
                       ('King', 'King prawns are on the menu.'), ('Long', 'Long queues form at noon.'),
                       ('Mark', 'Mark the opening date in the calendar.'), ('Bill', 'Bill payments are made monthly.')):
    CASES += [
        gp(f'names-english-name-{word.lower()}-is-a-word-en-accepted_false_blank', ACCEPTED, PLAN_EN, 'en', sentence,
           gone=(word,), pair=f'names-english-name-{word.lower()}-en-blank'),
        gp(f'names-english-name-{word.lower()}-en-blank', BLANK, EN_NONE, 'en', f'{word} handled the accounts.',
           gone=(word,)),
    ]
for word in ('Baker', 'Cook', 'Black', 'Green', 'Stone'):
    CASES.append(gp(f'names-english-surname-{word.lower()}-en-blank', BLANK, EN_NONE, 'en',
                    f'{word} supervised the bakery team.', gone=(word,)))
CASES.append(gp('names-brand-apple-en-blank', BLANK, EN_NONE, 'en', 'Apple supplies our tablets.', gone=('Apple',)))

# ---- words/names.txt refuses a Latin word in every paper (final re-check, must 1, regression from bbeccfc): a Russian
# given name in an English or an Uzbek paper, and an English given name that is an Uzbek word in an Uzbek paper, is a
# name, so an invented one alone at a sentence start, or after its blanked full name, is held. The same words in
# their Uzbek senses are accepted false blanks beside the leak each pays for.
REPORT_EN = 'Write the annual report of our company for 2025. Sales grew to 1.2 billion soums.'
MINUTES_CYRILLIC = 'Ота-оналар мажлиси баённомасини ёзинг. Кун тартиби: янги ўқув йили, мактаб формаси.'
CASES += [
    gp('names-russian-given-name-larisa-alone-en-blank', BLANK, EN_NONE, 'en', 'Larisa joined the team in March.',
       gone=('Larisa',)),
    gp('names-russian-given-name-alla-alone-en-blank', BLANK, EN_NONE, 'en', 'Alla oversaw the audit.', gone=('Alla',)),
    gp('names-russian-given-name-larisa-alone-uz-blank', BLANK, UZ_NONE, 'uz', 'Larisa moliya bo‘limini boshqaradi.',
       gone=('Larisa',)),
    gp('names-russian-given-name-alla-alone-uz-blank', BLANK, UZ_NONE, 'uz', 'Alla kassada ishlaydi.', gone=('Alla',)),
    body('names-russian-given-name-alone-in-a-report-ru-to-en-blank', BLANK, 'pdf.biz.hisobot', REPORT_RU_EN, 'en',
         'summary', 'Larisa opened the new branch.', gone=('Larisa',), translated=True),
    gp('names-english-given-name-in-latin-in-a-russian-paper-ru-blank', BLANK,
       'Напишите отчёт о работе компании за 2025 год.', 'ru', 'Tom возглавил отдел продаж.', gone=('Tom',)),
    # The full name, then its given name alone, the way a report or the minutes refer back.
    body('names-given-name-after-its-blanked-full-name-larisa-ru-to-en-blank', BLANK, 'pdf.biz.hisobot', REPORT_RU_EN,
         'en', 'summary', 'Larisa Ivanova led the finance team this year. Larisa also opened the new branch.',
         gone=('Larisa', 'Ivanova'), translated=True),
    body('names-given-name-after-its-blanked-full-name-alla-ru-to-en-blank', BLANK, 'pdf.biz.hisobot', REPORT_RU_EN,
         'en', 'summary', 'Alla Sokolova managed procurement. Alla cut costs.', gone=('Alla', 'Sokolova'),
         translated=True),
    body('names-given-name-after-its-blanked-full-name-larisa-uz-blank', BLANK, 'pdf.biz.hisobot', REPORT_UZ, 'uz',
         'summary', 'Larisa Petrova moliya bo‘limini boshqardi. Larisa yangi filialni ochdi.',
         gone=('Larisa', 'Petrova')),
    body('names-given-name-after-its-blanked-full-name-tom-uz-blank', BLANK, 'pdf.biz.hisobot', REPORT_UZ, 'uz',
         'summary', 'Tom Brown marketing bo‘limini boshqardi. Tom yangi filialni ochdi.', gone=('Tom', 'Brown')),
    body('names-given-name-after-its-blanked-full-name-sara-uz-blank', BLANK, 'pdf.biz.hisobot', REPORT_UZ, 'uz',
         'summary', 'Sara Johnson investor sifatida qatnashdi. Sara yangi filialni ochdi.', gone=('Sara', 'Johnson')),
    body('names-given-name-after-its-blanked-full-name-larisa-ru-to-uz-blank', BLANK, 'pdf.biz.bayonnoma',
         MINUTES_RU_UZ, 'uz', 'item_speakers',
         'Larisa Petrovna maktab formasi haqida gapirdi. Larisa yangi taklif kiritdi.', gone=('Larisa',),
         translated=True),
    body('names-given-name-after-its-blanked-full-name-alla-uz-blank', BLANK, 'pdf.biz.bayonnoma', MINUTES_UZ, 'uz',
         'item_speakers', 'Alla Ivanovna maktab formasi haqida gapirdi. Alla yangi taklif kiritdi.', gone=('Alla',)),
    body('names-given-name-after-its-blanked-full-name-larisa-en-blank', BLANK, 'pdf.xat.tavsiya', RECOMMENDATION_EN,
         'en', 'evidence', 'Larisa Brown, her head teacher, praised her work. Larisa also supervised her project.',
         gone=('Larisa',)),
    body('names-given-name-after-its-blanked-full-name-uzbek-cyrillic-brief-uz-blank', BLANK, 'pdf.biz.bayonnoma',
         MINUTES_CYRILLIC, 'uz', 'item_speakers', 'Larisa Petrovna gapirdi. Larisa yangi taklif kiritdi.',
         gone=('Larisa',)),
]
for word, sentence in (('Tom', 'Tom yangi filialni ochdi.'), ('Sara', 'Sara yangi filialni ochdi.'),
                       ('Joy', 'Joy mijozlar bilan ishlaydi.'), ('Kim', 'Kim sexni boshqaradi.'),
                       ('Bob', 'Bob uskunalarni yetkazib beradi.'), ('Alan', 'Alan maslahatchi sifatida ishlaydi.'),
                       ('Brenda', 'Brenda dizaynni tayyorlaydi.'), ('Manning', 'Manning loyihani boshqaradi.')):
    CASES.append(gp(f'names-english-name-{word.lower()}-in-an-uzbek-paper-uz-blank', BLANK, UZ_NONE, 'uz', sentence,
                    gone=(word,)))
CASES += [
    gp('names-english-given-name-bob-is-an-uzbek-word-uz-accepted_false_blank', ACCEPTED, UZ_NONE, 'uz',
       'Bob oxirida xulosa beriladi.', gone=('Bob',), pair='names-english-name-bob-in-an-uzbek-paper-uz-blank'),
]

# ---- A rejected line's name stands before its role with no mark, after an English role with "of" or after
# "Prepared by" (final re-check, must 2, from fc1c196): its given name alone in prose is held. A role's, a
# department's, a modifier's or a label's words hold nothing.
CASES += [
    body('held-rejected-chair-name-before-its-role-uz-blank', BLANK, 'pdf.biz.bayonnoma', MINUTES_UZ, 'uz',
         'item_speakers', 'Hikmat majlisni ochdi.', gone=('Hikmat',), facts=(('chair', 'Hikmat Rahim kotib'),)),
    body('held-rejected-chair-name-before-a-lower-case-role-phrase-uz-blank', BLANK, 'pdf.biz.bayonnoma', MINUTES_UZ,
         'uz', 'item_speakers', 'Hikmat majlisni ochdi.', gone=('Hikmat',),
         facts=(('chair', 'Hikmat Rahim maktab direktori'),)),
    body('held-rejected-chair-name-before-a-role-phrase-uzbek-cyrillic-brief-uz-blank', BLANK, 'pdf.biz.bayonnoma',
         MINUTES_CYRILLIC, 'uz', 'item_speakers', 'Hikmat majlisni ochdi.', gone=('Hikmat',),
         facts=(('chair', 'Hikmat Rahim maktab direktori'),)),
    body('held-rejected-secretary-name-before-sinf-rahbari-uz-blank', BLANK, 'pdf.biz.bayonnoma', MINUTES_UZ, 'uz',
         'item_speakers', 'Hikmat majlis bayonnomasini yozdi.', gone=('Hikmat',),
         facts=(('secretary', 'Hikmat Rahim sinf rahbari'),)),
    body('held-rejected-secretary-name-before-oqituvchi-uz-blank', BLANK, 'pdf.biz.bayonnoma', MINUTES_UZ, 'uz',
         'item_speakers', 'Hikmat majlis bayonnomasini yozdi.', gone=('Hikmat',),
         facts=(('secretary', 'Hikmat Rahim o‘qituvchi'),)),
    body('held-rejected-secretary-name-before-kotiba-uz-blank', BLANK, 'pdf.biz.bayonnoma', MINUTES_UZ, 'uz',
         'item_speakers', 'Gul majlis bayonnomasini yozdi.', gone=('Gul',), facts=(('secretary', 'Gul Sabr kotiba'),)),
    body('held-rejected-author-after-head-of-sales-ru-to-en-blank', BLANK, 'pdf.biz.hisobot', REPORT_RU_EN, 'en',
         'summary', 'Grant also opened the new branch.', gone=('Grant',),
         facts=(('author', 'Head of Sales Grant Fuller'),), translated=True),
    body('held-rejected-author-after-director-of-finance-ru-to-en-blank', BLANK, 'pdf.biz.hisobot', REPORT_RU_EN, 'en',
         'summary', 'Grant also opened the new branch.', gone=('Grant',),
         facts=(('author', 'Director of Finance Grant Fuller'),), translated=True),
    body('held-rejected-author-after-head-of-marketing-ru-to-en-blank', BLANK, 'pdf.biz.hisobot', REPORT_RU_EN, 'en',
         'summary', 'Dawn also opened the new branch.', gone=('Dawn',),
         facts=(('author', 'Head of Marketing Dawn Rich'),), translated=True),
    body('held-rejected-author-after-vice-president-of-sales-ru-to-en-blank', BLANK, 'pdf.biz.hisobot', REPORT_RU_EN,
         'en', 'summary', 'Grant also opened the new branch.', gone=('Grant',),
         facts=(('author', 'Vice President of Sales Grant Fuller'),), translated=True),
    body('held-rejected-author-before-head-of-sales-ru-to-en-blank', BLANK, 'pdf.biz.hisobot', REPORT_RU_EN, 'en',
         'summary', 'Grant also opened the new branch.', gone=('Grant',),
         facts=(('author', 'Grant Fuller Head of Sales'),), translated=True),
    body('held-rejected-author-after-prepared-by-ru-to-en-blank', BLANK, 'pdf.biz.hisobot', REPORT_RU_EN, 'en',
         'summary', 'Grant also opened the new branch.', gone=('Grant',), facts=(('author', 'Prepared by Grant Fuller'),),
         translated=True),
    body('held-rejected-author-after-director-of-finance-en-blank', BLANK, 'pdf.biz.hisobot', REPORT_EN, 'en',
         'summary', 'Grant also opened the new branch.', gone=('Grant',),
         facts=(('author', 'Director of Finance Grant Fuller'),)),
    body('held-rejected-second-signer-before-head-of-department-en-blank', BLANK, 'pdf.xat.tavsiya',
         RECOMMENDATION_EN, 'en', 'evidence', 'Grant also supervised her project.', gone=('Grant',),
         facts=(('second_signer', 'Grant Fuller Head of Department'),)),
    body('held-department-of-a-rejected-head-of-sales-line-ru-to-en-keep', KEEP, 'pdf.biz.hisobot', REPORT_RU_EN, 'en',
         'summary', 'Sales grew to 1.2 billion soums.', facts=(('author', 'Head of Sales'),), translated=True),
    body('held-department-beside-a-rejected-author-ru-to-en-keep', KEEP, 'pdf.biz.hisobot', REPORT_RU_EN, 'en',
         'summary', 'Finance costs fell slightly.', facts=(('author', 'Director of Finance Grant Fuller'),),
         translated=True),
    body('held-modifiers-of-a-rejected-senior-sales-manager-line-ru-to-en-keep', KEEP, 'pdf.biz.hisobot', REPORT_RU_EN,
         'en', 'summary', 'Sales grew to 1.2 billion soums.', facts=(('author', 'Senior Sales Manager'),),
         translated=True),
    body('held-label-of-a-rejected-prepared-by-line-ru-to-en-keep', KEEP, 'pdf.biz.hisobot', REPORT_RU_EN, 'en',
         'summary', 'Prepared meals were added to the menu.', facts=(('author', 'Prepared by Grant Fuller'),),
         translated=True),
    body('held-izafet-of-a-rejected-head-of-a-department-uz-keep', KEEP, 'pdf.biz.hisobot', REPORT_UZ, 'uz', 'summary',
         'Moliya bo‘limi yangi tizimni joriy qildi.', facts=(('author', 'Moliya bo‘limi boshlig‘i Hikmat Rahim'),)),
    body('held-modifier-of-a-rejected-senior-teacher-uz-keep', KEEP, 'pdf.biz.bayonnoma', MINUTES_UZ, 'uz',
         'item_speakers', 'Katta e’tibor maktab formasiga qaratildi.',
         facts=(('secretary', 'Katta o‘qituvchi Hikmat Rahim'),)),
]

# ---- An Uzbek Cyrillic brief's "7-синф" is the customer's class number (final re-check, must 3, from e4f9b7e). A
# technology token equal to the class number was no class letter (should, from e4f9b7e) until round 5 removed the
# technology exemption: it is the class c491da9 reads, the customer's own "3D modellash" stays.
LESSON_UZ_CYRILLIC = '7-синф математика фанидан дарс ишланмаси ёзинг, мавзу: касрлар.'
LESSON_UZ_3 = '3-sinf texnologiya fanidan dars ishlanmasi yozing, mavzu: modellar.'
CASES += [
    fact('class-letter-after-the-customers-cyrillic-class-number-uz-blank', BLANK, 'pdf.dars_ishlanmasi',
         LESSON_UZ_CYRILLIC, 'uz', 'subject', '7B matematika', gone=('7B',)),
    fact('class-letter-in-a-textbook-line-after-the-customers-cyrillic-class-number-uz-blank', BLANK,
         'pdf.dars_ishlanmasi', LESSON_UZ_CYRILLIC, 'uz', 'textbook', 'Matematika, 7B', gone=('7B',)),
    fact('class-the-customers-cyrillic-class-number-uz-keep', KEEP, 'pdf.dars_ishlanmasi', LESSON_UZ_CYRILLIC, 'uz',
         'subject', '7-sinf matematika'),
    fact('class-the-customers-cyrillic-class-letter-uz-keep', KEEP, 'pdf.dars_ishlanmasi',
         '7-«Б» синф математика фанидан дарс ишланмаси ёзинг, мавзу: касрлар.', 'uz', 'subject', '7B matematika'),
    *removed(fact('class-technology-token-3d-equal-to-the-class-number-uz-keep', KEEP, 'pdf.dars_ishlanmasi',
                  LESSON_UZ_3, 'uz', 'textbook', 'Texnologiya 3D modellash'),
             ('3D',), 'class-technology-shaped-letter-3d-before-model-darsi-uz-blank', listed=True),
    *removed(fact('class-technology-token-5g-equal-to-the-class-number-uz-keep', KEEP, 'pdf.dars_ishlanmasi',
                  '5-sinf informatika dars ishlanmasi, mavzu: aloqa.', 'uz', 'subject', 'Informatika: 5G aloqa'),
             ('5G',), 'class-technology-shaped-letter-3d-before-aloqa-madaniyati-uz-blank', listed=True),
    fact('class-letter-after-the-customers-class-number-in-a-textbook-line-uz-blank', BLANK, 'pdf.dars_ishlanmasi',
         LESSON_UZ_3, 'uz', 'textbook', 'Texnologiya 3B', gone=('3B',)),
    fact('class-technology-token-beside-a-class-word-uz-blank', BLANK, 'pdf.dars_ishlanmasi', LESSON_UZ_3, 'uz',
         'textbook', 'Texnologiya, 3-«D» sinf', gone=('«D»',)),
]

# ---- Placings written as ordinal words (final re-check, must 4, an old limit): read beside a contest, a diploma or
# a ranking. A place of work, a position at a company and the idiom "birinchi o‘rinni egallaydi" placed nothing until
# round 5 removed those exemptions: they are the placings c491da9 reads, the customer's own words stay.
CASES += [
    gp('numbers-ordinal-with-boldi-beside-an-olympiad-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Viloyat olimpiadasida uchinchi bo‘ldi.', gone=('uchinchi',)),
    gp('numbers-ordinal-lik-noun-placing-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Tuman olimpiadasida ikkinchilikni qo‘lga kiritdi.', gone=('ikkinchilik',)),
    gp('numbers-ordinal-degree-diploma-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Viloyat olimpiadasida ikkinchi darajali diplom oldi.', gone=('ikkinchi',)),
    gp('numbers-ordinal-after-stala-by-sales-ru-blank', BLANK, COVER_RU, 'ru', 'Я стала второй по продажам в регионе.',
       gone=('второй',)),
    gp('numbers-top-three-of-the-best-ru-blank', BLANK, COVER_RU, 'ru', 'Вошла в тройку лучших продавцов региона.',
       gone=('тройку',)),
    gp('numbers-diploma-of-the-second-degree-ru-blank', BLANK, COVER_RU, 'ru',
       'Получила диплом второй степени на конкурсе.', gone=('второй',)),
    gp('numbers-was-second-in-an-olympiad-en-blank', BLANK, RECOMMENDATION_EN, 'en',
       'She was second in the regional economics olympiad.', gone=('second',)),
    gp('numbers-took-second-at-an-olympiad-en-blank', BLANK, RECOMMENDATION_EN, 'en',
       'She took second at the regional olympiad.', gone=('second',)),
    gp('numbers-second-degree-diploma-en-blank', BLANK, RECOMMENDATION_EN, 'en',
       'She received a second-degree diploma at the olympiad.', gone=('second',)),
    gp('numbers-second-in-a-ranking-en-blank', BLANK, COVER_EN, 'en',
       'I was the top seller and second in the regional ranking.', gone=('second',)),
    gp('numbers-second-best-in-an-olympiad-en-blank', BLANK, RECOMMENDATION_EN, 'en',
       'She was the second-best student in the regional olympiad.', gone=('second',)),
    gp('numbers-first-place-accusative-present-beside-an-olympiad-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Viloyat olimpiadasida har yili birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    gp('numbers-first-place-accusative-present-in-a-region-uz-blank', BLANK, PLAN_UZ, 'uz',
       'Nonvoyxonamiz viloyatda birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    *removed(gp('numbers-her-first-place-of-work-en-keep', KEEP, RECOMMENDATION_EN, 'en',
                'Her first place of work was a pharmacy.'),
             ('first',), 'numbers-her-first-place-of-study-an-olympiad-en-blank', listed=True),
    *removed(gp('numbers-his-first-position-at-the-company-en-keep', KEEP, RECOMMENDATION_EN, 'en',
                'His first position at the company was junior accountant.'),
             ('first',), 'numbers-her-first-position-at-the-company-in-loan-sales-en-blank', listed=True),
    *removed(gp('numbers-this-first-place-of-employment-en-keep', KEEP, COVER_EN, 'en',
                'This first place of employment taught me discipline.'),
             ('first',), 'numbers-held-first-place-of-study-in-a-cover-letter-en-blank', listed=True),
    *removed(gp('numbers-first-place-accusative-idiom-uz-keep', KEEP, REFERENCE_UZ, 'uz',
                'Mijoz manfaati birinchi o‘rinni egallaydi.'),
             ('birinchi',), 'numbers-first-place-of-quality-in-a-region-uz-blank', listed=True),
    gp('numbers-came-first-to-arrive-uz-keep', KEEP, REFERENCE_UZ, 'uz', 'U darsga har doim birinchi bo‘lib keladi.'),
    gp('numbers-first-rate-importance-uz-keep', KEEP, PLAN_UZ, 'uz', 'Sifat biz uchun birinchi darajali ahamiyatga ega.'),
    gp('numbers-second-contest-of-mine-ru-keep', KEEP, COVER_RU, 'ru', 'Это был мой второй конкурс продавцов.'),
    gp('numbers-first-in-line-en-keep', KEEP, COVER_EN, 'en', 'I was first in line when the store opened.'),
    gp('numbers-the-first-in-her-family-en-keep', KEEP, RECOMMENDATION_EN, 'en',
       'She was the first in her family to apply abroad.'),
    gp('numbers-took-the-first-step-en-keep', KEEP, COVER_EN, 'en', 'I took the first step in sales at a small shop.'),
    gp('numbers-first-degree-relatives-en-keep', KEEP, COVER_EN, 'en', 'My first-degree relatives also work in retail.'),
]

# ---- A legal reference written in lower case (final re-check, must 5, an old limit): "the civil code", "the tax
# code", "the law on …" and "закон о …" are read as citations, held to the laws the customer named in any language.
JOB_EN_CIVIL = 'Write a job description for a company lawyer in line with the Civil Code.'
JOB_UZ_EN_CIVIL = 'Menga ingliz tilida yurist uchun lavozim yo‘riqnomasi yozing, Fuqarolik kodeksiga muvofiq ishlaydi.'
JOB_RU_ACCOUNTING = 'Составьте должностную инструкцию бухгалтера, по Закону о бухгалтерском учёте.'
CASES += [
    guard('laws-lower-case-civil-code-no-law-named-en-blank', BLANK, ECONOMICS['en'], 'en',
          'He also follows the civil code in contracts.', gone=('civil code',)),
    guard('laws-lower-case-civil-code-beside-another-code-en-blank', BLANK, JOB_EN, 'en',
          'He also follows the civil code in contracts.', gone=('civil code',)),
    guard('laws-lower-case-tax-code-en-blank', BLANK, JOB_EN, 'en', 'He knows the tax code well.',
          gone=('tax code',)),
    guard('laws-lower-case-law-on-state-duty-en-blank', BLANK, JOB_EN_LAW, 'en',
          'He follows the law on state duty when filing documents.', gone=('state duty',)),
    guard('laws-lower-case-law-on-no-law-named-en-blank', BLANK, JOB_EN, 'en',
          'He follows the law on state duty when filing documents.', gone=('state duty',)),
    guard('laws-lower-case-zakon-o-ru-blank', BLANK, JOB_RU, 'ru', 'Соблюдает закон о бухгалтерском учёте.',
          gone=('бухгалтерском',)),
    item('laws-lower-case-civil-code-in-a-grounded-item-en-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', JOB_EN, 'en',
         'general', 'Follows the civil code in contracts.', gone=('civil code',)),
    item('laws-lower-case-zakon-o-in-a-grounded-item-ru-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', JOB_RU, 'ru',
         'general', 'Соблюдает закон о бухгалтерском учёте.', gone=('бухгалтерском',)),
    guard('laws-lower-case-code-on-a-law-name-en-blank', BLANK, JOB_EN_LAW, 'en',
          'The accountant follows the code on administrative offences.', gone=('administrative',)),
    guard('laws-lower-case-law-on-after-the-country-en-blank', BLANK, JOB_EN_LAW, 'en',
          'Under the law of the Republic of Uzbekistan on taxes, reports are filed monthly.', gone=('taxes',)),
    # A duty's verb opening the sentence names no code; a Russian code named by its genitive still goes.
    guard('laws-a-duty-verb-before-an-invented-russian-code-ru-blank', BLANK, JOB_RU, 'ru',
          'Соблюдает Кодекс корпоративной этики.', gone=('корпоративной',)),
    guard('laws-a-duty-verb-before-the-customers-russian-code-ru-keep', KEEP, JOB_RU, 'ru',
          'Соблюдает Трудовой кодекс.'),
    guard('laws-the-customers-civil-code-in-lower-case-en-keep', KEEP, JOB_EN_CIVIL, 'en',
          'He also follows the civil code in contracts.'),
    guard('laws-the-customers-civil-code-translated-in-lower-case-uz-to-en-keep', KEEP, JOB_UZ_EN_CIVIL, 'en',
          'He also follows the civil code in contracts.', translated=True),
    guard('laws-the-customers-zakon-o-in-lower-case-ru-keep', KEEP, JOB_RU_ACCOUNTING, 'ru',
          'Соблюдает закон о бухгалтерском учёте.'),
    guard('laws-the-customers-zakon-o-translated-in-lower-case-ru-to-en-keep', KEEP, JOB_RU_EN_LAW, 'en',
          'He follows the law on accounting.', translated=True),
    guard('laws-tax-law-as-a-field-of-study-en-keep', KEEP, COVER_EN, 'en', 'He studied tax law at university.'),
    guard('laws-a-code-of-conduct-en-keep', KEEP, COVER_EN, 'en', 'The code of conduct is posted in the office.'),
    guard('laws-the-law-of-supply-and-demand-ru-keep', KEEP, COVER_RU, 'ru', 'Закон спроса и предложения действует везде.'),
    guard('laws-newtons-law-of-gravity-en-keep', KEEP, ECONOMICS['en'], 'en', 'Newton described the law of gravity.'),
]

# ---- The customer's own law followed by a verb or an adverb (final re-check, should 6, over-blank from 34ae7a8): an
# unnamed law's name ended at the first word that cannot continue it, so the customer's law sentences stayed and an
# invented law still went. Round 8 reads every word of the name again, as c491da9 does: the keeps are accepted false
# blanks (`PAID`, the re-check of round 7).
EDU_EN = 'Write an independent study paper on the main provisions of the Law on Education.'
EDU_UZ_EN = 'Menga ingliz tilida mustaqil ish yozib bering, mavzu: Ta’lim to‘g‘risidagi qonunning asosiy qoidalari.'
CONSUMER_RU_EN = ('Напишите самостоятельную работу на английском на тему «Закон о защите прав потребителей в '
                  'Узбекистане».')
for verb in ('guarantees free schooling', 'defines the rights of pupils', 'establishes the main principles',
             'became the basis of the reform', 'plays a key role', 'contains eight chapters'):
    slug = verb.split()[0]
    CASES += [
        guard(f'laws-the-customers-law-on-education-{slug}-en-keep', KEEP, EDU_EN, 'en', f'The Law on Education {verb}.'),
        guard(f'laws-the-customers-law-on-education-{slug}-uz-to-en-keep', KEEP, EDU_UZ_EN, 'en',
              f'The Law on Education {verb}.', translated=True),
    ]
CASES += [
    guard('laws-the-customers-law-on-education-in-lower-case-before-a-verb-en-keep', KEEP, EDU_EN, 'en',
          'The Law on education guarantees free schooling.'),
    guard('laws-the-customers-consumer-rights-law-before-a-verb-ru-to-en-keep', KEEP, CONSUMER_RU_EN, 'en',
          'The Law on the Protection of Consumer Rights protects buyers.', translated=True),
    guard('laws-the-customers-law-on-accounting-before-well-en-keep', KEEP, JOB_EN_LAW, 'en',
          'He knows the Law on Accounting well.'),
    guard('laws-the-customers-law-on-accounting-before-daily-en-keep', KEEP, JOB_EN_LAW, 'en',
          'The accountant applies the Law on Accounting daily.'),
    guard('laws-the-customers-law-on-accounting-before-together-en-keep', KEEP, JOB_EN_LAW, 'en',
          'The accountant follows the Law on Accounting together with internal rules.'),
    guard('laws-the-customers-law-of-the-republic-before-an-adverb-en-keep', KEEP, JOB_EN_LAW, 'en',
          'He studies the Law of the Republic of Uzbekistan on Accounting carefully.'),
    guard('laws-the-customers-law-on-accounting-before-well-ru-to-en-keep', KEEP, JOB_RU_EN_LAW, 'en',
          'He knows the Law on Accounting well.', translated=True),
    guard('laws-an-invented-law-before-a-verb-en-blank', BLANK, EDU_EN, 'en', 'The Law on Media guarantees free speech.',
          gone=('Media',)),
    guard('laws-an-invented-lower-case-law-before-a-verb-en-blank', BLANK, JOB_EN_LAW, 'en',
          'The Law on personal data guarantees privacy.', gone=('personal',)),
    guard('laws-an-invented-law-before-an-adverb-en-blank', BLANK, JOB_EN_LAW, 'en',
          'He knows the Law on Advertising well.', gone=('Advertising',)),
    guard('laws-an-invented-law-of-the-republic-before-an-adverb-en-blank', BLANK, JOB_EN_LAW, 'en',
          'He studies the Law of the Republic of Uzbekistan on Science carefully.', gone=('Science',)),
    guard('laws-an-invented-law-before-a-past-verb-en-blank', BLANK, EDU_EN, 'en',
          'The Law on Science became the basis of the reform.', gone=('Science',)),
]

# ---------------------------------------------------------------- the re-check of round 1 (fix-r1), both ways
# Each round-1 fix that kept something let something else through, or blanked an ordinary word: the leaks are pinned
# here as blanks next to the keeps they were the price of, and the false blanks as keeps next to the leaks they must
# not reopen.

# ---- A technology token is no class letter only beside a technology word (must, from 595f182): Uzbek classes are
# lettered A, B, V, G, D, so the paper's "5G" and "3D" for the customer's "5-sinf" and "3-sinf" are invented classes
# unless "modellash", "aloqa", "printer" or such stands beside them. The whole value and a class label's value are
# always a class. Round 5 removed the technology exemption: beside "printer" too the token is the class c491da9 reads.
LESSON_UZ_5 = '5-sinf matematika fanidan dars ishlanmasi yozing, mavzu: kasrlar.'
for number, letter in (('5', 'G'), ('3', 'D'), ('4', 'G'), ('2', 'D')):
    brief = f'{number}-sinf matematika fanidan dars ishlanmasi yozing, mavzu: kasrlar.'
    token = number + letter
    CASES += [
        fact(f'class-technology-shaped-letter-{token.lower()}-in-a-subject-line-uz-blank', BLANK,
             'pdf.dars_ishlanmasi', brief, 'uz', 'subject', f'{token} matematika', gone=(token,)),
        fact(f'class-technology-shaped-letter-{token.lower()}-in-a-textbook-line-uz-blank', BLANK,
             'pdf.dars_ishlanmasi', brief, 'uz', 'textbook', f'Matematika, {token}', gone=(token,)),
        fact(f'class-technology-shaped-letter-{token.lower()}-as-the-whole-value-uz-blank', BLANK,
             'pdf.dars_ishlanmasi', brief, 'uz', 'subject', token, gone=(token,)),
    ]
CASES += [
    fact('class-technology-shaped-letter-5g-in-a-textbook-line-ru-blank', BLANK, 'pdf.dars_ishlanmasi',
         '5-класс математика, составьте план урока, тема: дроби.', 'ru', 'textbook', 'Математика, 5G', gone=('5G',)),
    fact('class-technology-shaped-letter-5g-uzbek-cyrillic-brief-uz-blank', BLANK, 'pdf.dars_ishlanmasi',
         '5-синф математика дарс ишланмаси, мавзу: касрлар.', 'uz', 'textbook', 'Matematika, 5G', gone=('5G',)),
    fact('class-technology-shaped-letter-after-a-subject-word-uz-blank', BLANK, 'pdf.dars_ishlanmasi', LESSON_UZ_3,
         'uz', 'textbook', 'Texnologiya, 3D', gone=('3D',)),
    *removed(fact('class-technology-token-beside-a-printer-uz-keep', KEEP, 'pdf.dars_ishlanmasi', LESSON_UZ_3, 'uz',
                  'textbook', 'Texnologiya: 3D printer bilan ishlash'),
             ('3D',), 'class-technology-shaped-letter-3d-before-printsiplari-uz-blank', listed=True),
    # A technology token with no technology word beside it reads as the class it may be: the blank is the price of
    # "5G matematika".
    fact('class-technology-token-with-no-technology-word-uz-accepted_false_blank', ACCEPTED, 'pdf.dars_ishlanmasi',
         '5-sinf informatika dars ishlanmasi, mavzu: aloqa.', 'uz', 'subject', 'Informatika: 5G', gone=('5G',),
         pair='class-technology-shaped-letter-5g-in-a-subject-line-uz-blank'),
]

# ---- "o‘rinni egallaydi" is the idiom "comes first" only with "birinchi", an abstract subject or "uchun"/"hayotida",
# and no place or "bo‘yicha" scope (must, from bdfb210): any other ordinal, and a locative or "bo‘yicha" beside it,
# make it a placing. Round 5 removed the idiom exemption: "birinchi o‘rinni egallaydi" is always the placing c491da9
# reads.
CASES += [
    gp('numbers-first-place-present-in-a-class-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'U har yili sinfda birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    gp('numbers-first-place-present-in-studies-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'O‘qishda doimo birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    gp('numbers-second-place-present-by-a-scope-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'U maktabda o‘zlashtirish bo‘yicha ikkinchi o‘rinni egallaydi.', gone=('ikkinchi',)),
    gp('numbers-first-place-present-every-year-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'U har yili birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    gp('numbers-first-place-present-in-a-science-month-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Fan oyligida u har doim birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    gp('numbers-first-place-present-by-sales-uz-blank', BLANK, COVER_UZ, 'uz',
       'Filialimiz sotuv bo‘yicha birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    gp('numbers-second-place-present-continuous-in-a-company-uz-blank', BLANK, COVER_UZ, 'uz',
       'Jamoamiz kompaniyada ikkinchi o‘rinni egallab keladi.', gone=('ikkinchi',)),
    gp('numbers-first-place-present-in-a-neighbourhood-uz-blank', BLANK, PLAN_UZ, 'uz',
       'Nonvoyxonamiz mahallada birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    gp('numbers-first-place-present-by-quality-uz-blank', BLANK, PLAN_UZ, 'uz',
       'Mahsulotimiz sifat bo‘yicha birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    body('numbers-first-place-present-in-a-reference-uz-blank', BLANK, 'pdf.xat.tavsifnoma', REFERENCE_UZ, 'uz',
         'achievements', 'U har yili sinfda birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    body('numbers-first-place-present-in-a-cover-letter-uz-blank', BLANK, 'pdf.xat.ishga_kirish', COVER_UZ, 'uz',
         'fit', 'Filialimiz sotuv bo‘yicha birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    *removed(gp('numbers-first-place-idiom-for-me-uz-keep', KEEP, COVER_UZ, 'uz',
                'Men uchun mijoz manfaati birinchi o‘rinni egallaydi.'),
             ('birinchi',), 'numbers-first-place-present-for-teachers-by-a-names-upbringing-uz-blank', listed=True),
    *removed(gp('numbers-first-place-idiom-in-her-life-uz-keep', KEEP, REFERENCE_UZ, 'uz',
                'Uning hayotida bilim birinchi o‘rinni egallaydi.'),
             ('birinchi',), 'numbers-first-place-present-in-her-own-life-by-a-pronoun-uz-blank', listed=True),
    *removed(gp('numbers-first-place-idiom-quality-for-us-uz-keep', KEEP, PLAN_UZ, 'uz',
                'Sifat biz uchun birinchi o‘rinni egallaydi.'),
             ('birinchi',), 'numbers-first-place-present-for-us-by-a-pronoun-always-uz-blank', listed=True),
    # The idiom said with a place reads as the placing the same words make: the blank is the price of "Mahsulot
    # sifati viloyatda birinchi o‘rinni egallaydi" (re-check of round 2, below).
    gp('numbers-first-place-idiom-in-a-company-uz-accepted_false_blank', ACCEPTED, COVER_UZ, 'uz',
       'Kompaniyamizda mijoz manfaati birinchi o‘rinni egallaydi.', gone=('birinchi',),
       pair='numbers-first-place-of-quality-in-a-region-uz-blank'),
]

# ---- A possessive or a demonstrative before "first place" exempts nothing (must, from bdfb210): only a position as
# a job is no placing. Round 5 removed the exemptions of a place of work, study, residence or business and of a
# position at the company: they are the placings c491da9 reads.
CASES += [
    gp('numbers-her-first-place-at-a-science-fair-en-blank', BLANK, RECOMMENDATION_EN, 'en',
       'Her first place at the regional science fair shows her talent.', gone=('first',)),
    gp('numbers-her-second-place-at-a-festival-en-blank', BLANK, RECOMMENDATION_EN, 'en',
       'Her second place at the science festival followed.', gone=('second',)),
    gp('numbers-his-first-place-in-a-marathon-en-blank', BLANK, RECOMMENDATION_EN, 'en',
       'His first place in the city marathon made the news.', gone=('first',)),
    gp('numbers-their-first-place-at-an-exhibition-en-blank', BLANK, RECOMMENDATION_EN, 'en',
       'Their first place at the regional exhibition was well deserved.', gone=('first',)),
    gp('numbers-her-first-place-in-a-quiz-en-blank', BLANK, RECOMMENDATION_EN, 'en',
       'Her first place in the national quiz is a highlight.', gone=('first',)),
    gp('numbers-this-first-place-at-a-hackathon-en-blank', BLANK, RECOMMENDATION_EN, 'en',
       'This first place at the hackathon opened doors for her.', gone=('first',)),
    gp('numbers-our-first-place-in-sales-en-blank', BLANK, COVER_EN, 'en',
       'Our first place in sales across the chain came in 2024.', gone=('first',)),
    body('numbers-her-first-place-in-a-recommendation-en-blank', BLANK, 'pdf.xat.tavsiya', RECOMMENDATION_EN, 'en',
         'evidence', 'Her first place at the regional science fair shows her talent.', gone=('first',)),
    gp('numbers-her-first-position-as-a-job-en-keep', KEEP, RECOMMENDATION_EN, 'en',
       'Her first position as a cashier taught her patience.'),
    *removed(gp('numbers-their-first-place-of-business-en-keep', KEEP, COVER_EN, 'en',
                'Their first place of business was a market stall.'),
             ('first',), 'numbers-her-first-place-of-study-an-olympiad-en-blank', listed=True),
]

# ---- A title-case law name goes on in lower case through "of" and its noun phrase and through noun modifiers (must,
# from e04969c): an invented law that continues the customer's title words still goes; the customer's law before a
# verb stays.
EDU_EN_COUNTRY = 'Write an independent study paper in English on the Law on Education of Uzbekistan.'
ACCOUNTING_EN = 'Write a job description for an accountant under the Law on Accounting.'
CASES += [
    guard('laws-the-customers-title-words-then-of-adults-en-blank', BLANK, EDU_EN_COUNTRY, 'en',
          'The Law on Education of adults regulates night schools.', gone=('adults',)),
    guard('laws-the-customers-title-words-then-of-children-en-blank', BLANK, EDU_EN_COUNTRY, 'en',
          'The Law on Education of children with disabilities guarantees inclusive schooling.', gone=('children',)),
    guard('laws-the-customers-title-words-then-of-state-enterprises-en-blank', BLANK, ACCOUNTING_EN, 'en',
          'He applies the Law on Accounting of state enterprises.', gone=('enterprises',)),
    guard('laws-the-customers-title-words-then-a-noun-phrase-en-blank', BLANK, EDU_EN_COUNTRY, 'en',
          'The Law on Education quality assessment created the inspectorate.', gone=('quality',)),
    guard('laws-the-customers-title-words-then-standards-for-banks-en-blank', BLANK, ACCOUNTING_EN, 'en',
          'He applies the Law on Accounting standards for banks.', gone=('standards',)),
    guard('laws-the-customers-title-words-then-standards-before-a-verb-en-blank', BLANK, EDU_EN_COUNTRY, 'en',
          'The Law on Education standards defines curricula.', gone=('standards',)),
    guard('laws-the-customers-title-words-then-funding-en-blank', BLANK, EDU_EN_COUNTRY, 'en',
          'The Law on Education funding guarantees teacher pay.', gone=('funding',)),
    body('laws-the-customers-title-words-then-of-adults-in-a-section-en-blank', BLANK, 'pdf.mustaqil_ish',
         EDU_EN_COUNTRY, 'en', 'section_a', 'The Law on Education of adults regulates night schools.',
         gone=('adults',)),
    guard('laws-the-customers-law-of-the-republic-before-a-verb-en-keep', KEEP, EDU_EN_COUNTRY, 'en',
          'The Law on Education of the Republic of Uzbekistan guarantees free schooling.'),
    guard('laws-the-customers-title-law-on-accounting-before-requires-en-keep', KEEP, ACCOUNTING_EN, 'en',
          'The Law on Accounting requires accurate records.'),
]

# ---- Placings written as ordinal words, the forms round 1 left (must, item 4): Russian "третьей", sales rankings
# with no contest word, "second-highest", Uzbek "uchlik" of the best, "bo‘lib" beside a contest and "birinchiligi".
CASES += [
    gp('numbers-diploma-of-the-third-degree-ru-blank', BLANK, COVER_RU, 'ru',
       'Получила диплом третьей степени на олимпиаде.', gone=('третьей',)),
    gp('numbers-awarded-a-diploma-of-the-third-degree-ru-blank', BLANK, COVER_RU, 'ru',
       'Награждена дипломом третьей степени.', gone=('третьей',)),
    gp('numbers-third-in-a-sellers-ranking-ru-blank', BLANK, COVER_RU, 'ru', 'Стала третьей в рейтинге продавцов.',
       gone=('третьей',)),
    gp('numbers-third-by-sales-ru-blank', BLANK, COVER_RU, 'ru', 'Была третьей по продажам в регионе.',
       gone=('третьей',)),
    gp('numbers-second-by-sales-in-a-branch-uz-blank', BLANK, COVER_UZ, 'uz', 'Sotuv bo‘yicha filialda ikkinchi bo‘ldim.',
       gone=('ikkinchi',)),
    gp('numbers-third-by-trade-volume-uz-blank', BLANK, COVER_UZ, 'uz',
       'Savdo hajmi bo‘yicha viloyatda uchinchi bo‘ldim.', gone=('uchinchi',)),
    gp('numbers-top-three-by-sales-uz-blank', BLANK, COVER_UZ, 'uz', 'Sotuvlar bo‘yicha eng yaxshi uchlikka kirdim.',
       gone=('uchlik',)),
    gp('numbers-second-with-bolib-beside-a-contest-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Shahar musobaqasida ikkinchi bo‘lib, kumush medal oldi.', gone=('ikkinchi',)),
    gp('numbers-second-in-a-district-championship-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Tuman birinchiligida ikkinchi bo‘ldi.', gone=('ikkinchi',)),
    gp('numbers-top-three-in-an-olympiad-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Viloyat olimpiadasida eng yaxshi uchlikka kirdi.', gone=('uchlik',)),
    gp('numbers-among-the-top-three-winners-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'U olimpiadada g‘oliblar uchligidan joy oldi.', gone=('uchlig',)),
    gp('numbers-second-in-sales-en-blank', BLANK, COVER_EN, 'en', 'I was second in sales across the whole region.',
       gone=('second',)),
    gp('numbers-third-in-the-company-for-sales-en-blank', BLANK, COVER_EN, 'en',
       'I was third in the company for sales last year.', gone=('third',)),
    gp('numbers-second-highest-seller-en-blank', BLANK, COVER_EN, 'en', 'I was the second highest seller in the region.',
       gone=('second',)),
    gp('numbers-second-highest-earner-en-blank', BLANK, COVER_EN, 'en', 'I was the store’s second-highest earner.',
       gone=('second',)),
    gp('numbers-first-to-register-for-an-olympiad-uz-keep', KEEP, REFERENCE_UZ, 'uz',
       'U olimpiadaga birinchi bo‘lib ro‘yxatdan o‘tdi.'),
    gp('numbers-her-second-olympiad-uz-keep', KEEP, REFERENCE_UZ, 'uz', 'Bu uning ikkinchi olimpiadasi bo‘ldi.'),
    gp('numbers-second-highest-cost-en-keep', KEEP, PLAN_EN, 'en', 'Rent is the second highest cost of the bakery.'),
    gp('numbers-third-task-ru-keep', KEEP, COVER_RU, 'ru', 'Третьей задачей было обучение персонала.'),
    gp('numbers-first-in-line-beside-a-ranking-en-keep', KEEP, COVER_EN, 'en',
       'I was first in line for promotion in the sales ranking review.'),
    # "был/была" before an ordinal with its noun after it orders, never places (should, from 21147ba).
    gp('numbers-it-was-her-first-experience-of-an-olympiad-ru-keep', KEEP, COVER_RU, 'ru',
       'Для неё это был первый опыт участия в олимпиаде.'),
    gp('numbers-it-was-her-second-olympiad-ru-keep', KEEP, COVER_RU, 'ru', 'Это была вторая олимпиада в её жизни.'),
]

# ---- A lower-case code after a law-name word is cited with or without "the" right before it (must, item 5):
# adjectives may stand between ("the new tax code"); a code's identifier sense with nothing to tell it ("the customs
# code to imported items") is the accepted price; "code of" a noun that names no law is an identifier and stays.
CASES += [
    guard('laws-lower-case-new-tax-code-en-blank', BLANK, JOB_EN, 'en', 'He follows the new tax code in all filings.',
          gone=('tax code',)),
    guard('laws-lower-case-current-civil-code-en-blank', BLANK, JOB_EN, 'en',
          'He follows the current civil code in contracts.', gone=('civil code',)),
    guard('laws-lower-case-uzbek-tax-code-en-blank', BLANK, JOB_EN, 'en', 'He knows the Uzbek tax code thoroughly.',
          gone=('tax code',)),
    guard('laws-lower-case-tax-code-requirements-en-blank', BLANK, JOB_EN, 'en',
          'He ensures compliance with tax code requirements.', gone=('tax code',)),
    guard('laws-lower-case-customs-code-provisions-en-blank', BLANK, JOB_EN, 'en',
          'He applies customs code provisions to imports.', gone=('customs code',)),
    guard('laws-lower-case-tax-code-of-the-republic-en-blank', BLANK, JOB_EN, 'en',
          'He follows the tax code of the Republic of Uzbekistan.', gone=('tax code',)),
    guard('laws-a-tax-code-of-each-supplier-en-keep', KEEP, JOB_EN, 'en',
          'He enters the tax code of each supplier in the register.'),
    guard('laws-a-promo-code-en-keep', KEEP, COVER_EN, 'en', 'Customers enter the promo code at checkout.'),
    guard('laws-the-customs-code-of-an-item-en-accepted_false_blank', ACCEPTED, JOB_EN, 'en',
          'He assigns the customs code to imported items.', gone=('customs code',),
          pair='laws-lower-case-customs-code-provisions-en-blank'),
    # Accepted as a blank in round 2 as "... the customs code to each imported item"; the re-check of round 2 reads
    # "to each" item as the identifier, so that sentence is kept now while its pair still blanks.
    guard('laws-the-customs-code-to-each-imported-item-en-keep', KEEP, JOB_EN, 'en',
          'He assigns the customs code to each imported item.'),
    # "the law on" a pronoun or a stock phrase, and a law field before a noun, cite nothing (should, from 02ef0cc).
    guard('laws-the-law-on-this-point-en-keep', KEEP, COVER_EN, 'en', 'The law on this point is not clear.'),
    guard('laws-the-law-on-paper-en-keep', KEEP, COVER_EN, 'en', 'The law on paper differs from practice.'),
    guard('laws-labour-law-knowledge-en-keep', KEEP, COVER_EN, 'en', 'Their labour law knowledge is weak.'),
    guard('laws-a-law-of-which-ru-keep', KEEP, COVER_RU, 'ru', 'Это закон о котором многие не знают.'),
    # "Закон о" something opening a sentence cites a law, even one said to be unadopted: the price of an invented
    # "Закон о частном предпринимательстве".
    guard('laws-an-invented-zakon-o-opening-a-sentence-ru-blank', BLANK, COVER_RU, 'ru',
          'Закон о частном предпринимательстве защищает малые фирмы.', gone=('частном',)),
    guard('laws-a-draft-zakon-o-opening-a-sentence-ru-accepted_false_blank', ACCEPTED, COVER_RU, 'ru',
          'Закон о малом бизнесе обсуждается давно, но пока не принят.', gone=('малом',),
          pair='laws-an-invented-zakon-o-opening-a-sentence-ru-blank'),
    # The customer's law named in Uzbek or English, cited in a Russian paper in lower case (accepted false blanks since
    # round 8: c491da9 reads no lower-case law, and the head noun is the customer's word).
    guard('laws-the-customers-uzbek-law-as-zakon-o-in-lower-case-uz-to-ru-keep', KEEP,
          'Buxgalter uchun lavozim yo‘riqnomasini rus tilida yozing, Buxgalteriya hisobi to‘g‘risidagi qonunga muvofiq.',
          'ru', 'Руководствуется законом о бухгалтерском учёте.', translated=False),  # too short a brief to tell
    guard('laws-the-customers-english-law-as-zakon-o-in-lower-case-en-to-ru-keep', KEEP,
          'Write in Russian a job description for an accountant under the Law on Accounting.', 'ru',
          'Руководствуется законом о бухгалтерском учёте.', translated=True),
    # The customer's law in lower case before a sentence adverb or "aims to" (should, from 02ef0cc and e04969c; accepted
    # false blanks since round 8, `PAID`).
    guard('laws-an-invented-lower-case-law-before-thus-en-blank', BLANK, EDU_EN, 'en',
          'The law on media thus protects journalists.', gone=('media',)),
    guard('laws-an-invented-law-before-aims-to-en-blank', BLANK, EDU_EN, 'en',
          'The Law on Media aims to protect journalists.', gone=('Media',)),
]
for tail in ('thus protects pupils', 'aims to raise quality', 'seeks to raise quality', 'itself is short',
             'therefore matters', 'however leaves gaps', 'is short'):
    slug = tail.split()[0]
    CASES += [
        guard(f'laws-the-customers-lower-case-law-on-education-{slug}-en-keep', KEEP, EDU_EN, 'en',
              f'The law on education {tail}.'),
        guard(f'laws-the-customers-lower-case-law-on-education-{slug}-ru-to-en-keep', KEEP,
              'Напишите на английском самостоятельную работу о Законе об образовании.', 'en',
              f'The law on education {tail}.', translated=True),
    ]

# A lower-case "act on" something names a law as an invented one would: the customer's law described as "the main act
# on schooling" goes with it, the price of "the act on media".
CASES += [
    guard('laws-an-invented-lower-case-act-on-beside-the-customers-law-en-blank', BLANK, EDU_EN, 'en',
          'The law on education and the act on media apply to schools.', gone=('media',)),
    guard('laws-the-customers-law-described-as-an-act-on-en-accepted_false_blank', ACCEPTED, EDU_EN, 'en',
          'The law on education is the main act on schooling.', gone=('schooling',),
          pair='laws-an-invented-lower-case-act-on-beside-the-customers-law-en-blank'),
    # The customer's law in lower case is a citation like its title, so a year they never gave goes with it as it
    # does with "The Law on Education first appeared in 1992".
    guard('laws-an-invented-year-of-the-customers-lower-case-law-en-blank', BLANK, EDU_EN, 'en',
          'The law on education first appeared in 1992.', gone=('1992',)),
]

# ---- A blanked full name's free first word is held only as a two-word name's given name (should, from a2e73ae): a
# role word, a role's modifier or an adverb before the name opens other sentences across the paper.
for case_id, brief, locale, first, second, translated in (
        ('bosh-of-bosh-hisobchi-uz', REPORT_UZ, 'uz', 'Bosh Hisobchi Nodira Karimova hisobotni tayyorladi.',
         'Bosh ofis yangi binoga ko‘chdi.', None),
        ('katta-of-katta-hisobchi-uz', REPORT_UZ, 'uz', 'Katta Hisobchi Nodira Karimova hisobotni tayyorladi.',
         'Katta e’tibor sifatga qaratildi.', None),
        ('hozirda-uz', REPORT_UZ, 'uz', 'Hozirda Hikmat Rahimov savdo bo‘limini boshqaradi.',
         'Hozirda firmada yangi tizim ishlaydi.', None),
        ('today-ru-to-en', REPORT_RU_EN, 'en', 'Today Larisa Ivanova leads the sales team.',
         'Today the firm has a new office.', True),
        ('currently-ru-to-en', REPORT_RU_EN, 'en', 'Currently Larisa Ivanova heads procurement.',
         'Currently the firm rents its office.', True),
        ('chief-of-chief-accountant-ru-to-en', REPORT_RU_EN, 'en', 'Chief Accountant Larisa Ivanova closed the books.',
         'Chief among the risks is inflation.', True),
        ('glavnyi-of-glavnyi-bukhgalter-ru', REPORT_RU, 'ru', 'Главный Бухгалтер Ольга Смирнова закрыла год.',
         'Главный офис переехал.', None),
        ('seichas-ru', REPORT_RU, 'ru', 'Сейчас Ольга Смирнова руководит отделом.', 'Сейчас фирма арендует новый офис.',
         None)):
    CASES.append(body(f'held-free-first-word-{case_id}-keep', KEEP, 'pdf.biz.hisobot', brief, locale, 'work_done',
                      second, parts=(('summary', {'body': first}),), translated=translated))
CASES += [
    body('held-given-name-of-a-two-word-name-uz-blank', BLANK, 'pdf.biz.hisobot', REPORT_UZ, 'uz', 'work_done',
         'Hikmat yangi mijozlar topdi.', gone=('Hikmat',),
         parts=(('summary', {'body': 'Hikmat Rahimov savdo bo‘limini boshqardi.'}),)),
]

# ---- A rejected role-only line holds no common word before its role (should, from 572cb45): "Kitchen Manager" holds
# nothing, so "Kitchen staff …" stays; a name before or after a role is still held.
MARKETING_EN = 'Write a marketing plan for our bakery in Tashkent for 2026. Budget 50 million soums.'
for case_id, entry, brief, locale, field_id, line, part, prose, translated in (
        ('kitchen-manager', 'pdf.biz.hisobot', REPORT_EN, 'en', 'author', 'Kitchen Manager', 'summary',
         'Kitchen staff grew in spring.', None),
        ('shift-supervisor', 'pdf.biz.hisobot', REPORT_EN, 'en', 'author', 'Shift Supervisor', 'summary',
         'Shift patterns were changed.', None),
        ('planning-department', 'pdf.biz.hisobot', REPORT_EN, 'en', 'author', 'Planning Department', 'summary',
         'Planning began in January.', None),
        ('delivery-manager', 'pdf.biz.hisobot', REPORT_EN, 'en', 'author', 'Delivery Manager', 'summary',
         'Delivery times improved.', None),
        ('audit-committee', 'pdf.biz.hisobot', REPORT_EN, 'en', 'author', 'Audit Committee', 'summary',
         'Audit findings were minor.', None),
        ('supervisory-board', 'pdf.biz.hisobot', REPORT_EN, 'en', 'author', 'Supervisory Board', 'summary',
         'Supervisory checks were tightened.', None),
        ('quality-control-manager', 'pdf.biz.hisobot', REPORT_EN, 'en', 'author', 'Quality Control Manager',
         'summary', 'Control checks rose.', None),
        ('founders-and-investors', 'pdf.biz.hisobot', REPORT_EN, 'en', 'addressee', 'Founders and Investors',
         'summary', 'Investors received a dividend.', None),
        ('owner-and-founder', 'pdf.biz.hisobot', REPORT_EN, 'en', 'author', 'Owner and Founder', 'summary',
         'Founder equity was unchanged.', None),
        ('strategy-and-growth-lead', 'pdf.biz.hisobot', REPORT_EN, 'en', 'author', 'Strategy and Growth Lead',
         'summary', 'Growth slowed in May.', None),
        ('general-meeting-of-shareholders', 'pdf.biz.hisobot', REPORT_EN, 'en', 'addressee',
         'General Meeting of Shareholders', 'summary', 'General costs fell.', None),
        ('prepared-by-planning-office', 'pdf.biz.hisobot', REPORT_EN, 'en', 'author', 'Prepared by Planning Office',
         'summary', 'Planning began in January.', None),
        ('social-media-manager', 'pdf.biz.marketing_reja', MARKETING_EN, 'en', 'author', 'Social Media Manager',
         'summary_text', 'Social channels bring most orders.', None),
        ('mathematics-teacher', 'pdf.xat.tavsiya', RECOMMENDATION_EN, 'en', 'second_signer', 'Mathematics Teacher',
         'evidence', 'Mathematics was her strongest subject.', None),
        ('ishlab-chiqarish-menejeri', 'pdf.biz.hisobot', REPORT_UZ, 'uz', 'author', 'Ishlab Chiqarish Menejeri',
         'summary', 'Ishlab chiqarish hajmi oshdi.', None)):
    CASES.append(body(f'held-role-only-line-{case_id}-holds-no-common-word-{locale}-keep', KEEP, entry, brief, locale,
                      part, prose, facts=((field_id, line),), translated=translated))
CASES += [
    body('held-rejected-author-before-store-manager-en-blank', BLANK, 'pdf.biz.hisobot', REPORT_EN, 'en', 'summary',
         'Grant also opened the new branch.', gone=('Grant',), facts=(('author', 'Grant Fuller Store Manager'),)),
    body('held-rejected-author-before-bosh-hisobchi-uz-blank', BLANK, 'pdf.biz.hisobot', REPORT_UZ, 'uz', 'summary',
         'Hikmat yangi filialni ochdi.', gone=('Hikmat',), facts=(('author', 'Hikmat Rahim bosh hisobchi'),)),
    body('held-rejected-author-after-a-hyphenated-role-ru-to-en-blank', BLANK, 'pdf.biz.hisobot', REPORT_RU_EN, 'en',
         'summary', 'Grant also opened the new branch.', gone=('Grant',),
         facts=(('author', 'Vice-President for Sales Grant Fuller'),), translated=True),
]

# ---- An English paper reads a Latin word against the Uzbek lexicon too (should, from a2e73ae): an Uzbek word the
# paper names its own things by ("Tandir bread", "Bozor prices") stays; the few given names the Uzbek lexicon parses
# ("Yana", "Sita") are refused in an English paper only, so the Uzbek "Yana bir ..." stays in an Uzbek paper.
for word, sentence in (('tandir', 'Tandir bread is our main product.'), ('patir', 'Patir bread sells at weekends.'),
                       ('bozor', 'Bozor prices set our ceiling.'),
                       ('choyxona', 'Choyxona owners are our wholesale buyers.'),
                       ('hashar', 'Hashar days cleaned the yard.'), ('kurash', 'Kurash clubs meet twice a week.'),
                       ('manaviyat', 'Ma’naviyat hours run weekly.')):
    CASES.append(gp(f'names-uzbek-word-{word}-opening-an-english-sentence-uz-to-en-keep', KEEP, PLAN_UZ_EN, 'en',
                    sentence, translated=True))
CASES += [
    gp('names-uzbek-parsed-given-name-yana-en-blank', BLANK, EN_NONE, 'en', 'Yana joined the team in March.',
       gone=('Yana',)),
    gp('names-uzbek-parsed-given-name-sita-en-blank', BLANK, EN_NONE, 'en', 'Sita manages the store.', gone=('Sita',)),
    gp('names-yana-opening-an-uzbek-sentence-uz-keep', KEEP, UZ_NONE, 'uz', 'Yana bir muhim jihat bor.'),
]

# ---------------------------------------------------------------- the re-check of round 2 (fix-r2), both ways
# Round 2 left forms of four items open and let new false blanks in: each leak is pinned here as a blank beside the
# keep it must not cost, and each false blank as a keep beside the leak it must not reopen.

# ---- The customer's own law before a verb whose -s ends as a plural noun does, or before its possessive (must, item 6,
# from f3253a7): "ensures", "lists", "consists", "implements" and "mentions" end a law's name in title case and in
# lower case, so the customer's law sentences stayed in English, Russian and Uzbek briefs; the same verbs after an
# invented law still take it out. Round 8 reads every word of the name again, the possessive's noun too: the keeps are
# accepted false blanks (`PAID`).
EDU_RU_EN = 'Напишите на английском самостоятельную работу о Законе об образовании.'
EDU_UZC_EN = 'Менга инглиз тилида мустақил иш ёзиб беринг, мавзу: Таълим тўғрисидаги қонуннинг асосий қоидалари.'
for slug, tail in (('ensures', 'ensures equal access to schooling'), ('lists', 'lists the rights of pupils'),
                   ('consists', 'consists of eight chapters'), ('implements', 'implements the state programme'),
                   ('mentions', 'mentions inclusive education')):
    for shape, law, invented in (('title', 'The Law on Education', 'The Law on Media'),
                                 ('lower', 'The law on education', 'The law on media')):
        for brief_slug, brief, translated in (('en', EDU_EN, None), ('ru-to-en', EDU_RU_EN, True),
                                              ('uz-to-en', EDU_UZ_EN, True)):
            CASES.append(guard(f'laws-the-customers-{shape}-law-on-education-{slug}-{brief_slug}-keep', KEEP, brief,
                               'en', f'{law} {tail}.', translated=translated))
        CASES.append(guard(f'laws-an-invented-{shape}-law-on-media-{slug}-en-blank', BLANK, EDU_EN, 'en',
                           f'{invented} {tail}.', gone=(invented.split()[-1],)))
    CASES.append(guard(f'laws-the-customers-law-on-education-{slug}-uz-cyrillic-to-en-keep', KEEP, EDU_UZC_EN, 'en',
                       f'The Law on Education {tail}.', translated=True))
# Verbs no list names before a plural or a possessive object, and the name's own possessive.
for slug, tail in (('secures', 'secures the right to study'), ('upholds', 'upholds students’ rights'),
                   ('reinforces', 'reinforces parents’ responsibilities'), ('affirms', 'affirms pupils’ rights'),
                   ('motivates', 'motivates teachers'), ('equips', 'equips schools with rights'),
                   ('balances', 'balances pupils’ rights and duties'), ('functions', 'functions as a framework'),
                   ('exists', 'exists to protect pupils'), ('measures', 'measures school performance'),
                   ('features', 'features a chapter on teachers'), ('assists', 'assists schools in planning')):
    CASES += [
        guard(f'laws-the-customers-law-on-education-{slug}-en-keep', KEEP, EDU_EN, 'en',
              f'The Law on Education {tail}.'),
        guard(f'laws-the-customers-lower-case-law-on-education-{slug}-ru-to-en-keep', KEEP, EDU_RU_EN, 'en',
              f'The law on education {tail}.', translated=True),
        guard(f'laws-an-invented-law-on-media-{slug}-en-blank', BLANK, EDU_EN, 'en', f'The Law on Media {tail}.',
              gone=('Media',)),
    ]
ACCOUNTING_UZ_EN = ('Buxgalter uchun ingliz tilida lavozim yo‘riqnomasi yozing. U Buxgalteriya hisobi to‘g‘risidagi '
                    'qonunni bilishi kerak.')
for slug, sentence in (('ensures', 'The Law on Accounting ensures reliable reporting.'),
                       ('consists', 'The Law on Accounting consists of several chapters.'),
                       ('secures', 'The Law on Accounting secures transparent reporting.'),
                       ('insists', 'The Law on Accounting insists on timely reporting.'),
                       ('possessive', 'The Law on Accounting’s rules apply to all firms.')):
    for brief_slug, brief, translated in (('en', ACCOUNTING_EN, None), ('ru-to-en', JOB_RU_EN_LAW, True),
                                          ('uz-to-en', ACCOUNTING_UZ_EN, True)):
        CASES.append(guard(f'laws-the-customers-law-on-accounting-{slug}-{brief_slug}-keep', KEEP, brief, 'en',
                           sentence, translated=translated))
CASES += [
    guard('laws-the-customers-law-on-education-possessive-en-keep', KEEP, EDU_EN, 'en',
          'The Law on Education’s main aim is quality.'),
    guard('laws-an-invented-law-on-auditing-ensures-en-blank', BLANK, ACCOUNTING_EN, 'en',
          'The Law on Auditing ensures reliable reporting.', gone=('Auditing',)),
    guard('laws-an-invented-law-possessive-en-blank', BLANK, EDU_EN, 'en',
          'The Law on Media’s main aim is press freedom.', gone=('Media',)),
    guard('laws-the-customers-title-words-then-higher-possessive-en-blank', BLANK, EDU_EN, 'en',
          'The Law on Higher Education’s main aim is research.', gone=('Higher',)),
    guard('laws-the-customers-lower-case-words-then-funding-before-ensures-en-blank', BLANK, EDU_EN, 'en',
          'The law on education funding ensures teacher pay.', gone=('funding',)),
    guard('laws-the-customers-lower-case-words-after-preschool-before-lists-en-blank', BLANK, EDU_EN, 'en',
          'The law on preschool education lists the rights of children.', gone=('preschool',)),
    guard('laws-an-invented-lower-case-law-on-food-supplements-en-blank', BLANK, EDU_EN, 'en',
          'The law on food supplements applies to school canteens.', gone=('supplements',)),
]

# ---- A rejected line's name before an abbreviated role or the Uzbek "tomonidan" (must, item 2, from fc1c196): "VP",
# "SVP" are roles, and "X tomonidan tayyorlandi" holds the X as "Prepared by X" does; a role-only line holds none of
# its common words.
for case_id, line in (('before-vp-of-finance', 'VP of Finance Grant Fuller'),
                      ('before-vp-finance', 'VP Finance Grant Fuller'),
                      ('after-vp-of-finance', 'Grant Fuller VP of Finance'),
                      ('before-svp-of-sales', 'SVP of Sales Grant Fuller')):
    CASES.append(body(f'held-rejected-author-{case_id}-en-blank', BLANK, 'pdf.biz.hisobot', REPORT_EN, 'en', 'summary',
                      'Grant also cut costs.', gone=('Grant',), facts=(('author', line),)))
CASES += [
    body('held-rejected-author-before-tomonidan-uz-blank', BLANK, 'pdf.biz.hisobot', REPORT_UZ, 'uz', 'summary',
         'Hikmat xarajatlarni kamaytirdi.', gone=('Hikmat',),
         facts=(('author', 'Hikmat Rahim tomonidan tayyorlandi'),)),
    body('held-role-only-line-vp-of-finance-holds-no-common-word-en-keep', KEEP, 'pdf.biz.hisobot', REPORT_EN, 'en',
         'summary', 'Finance costs fell.', facts=(('author', 'VP of Finance'),)),
    body('held-role-only-line-moliya-bolimi-tomonidan-holds-no-common-word-uz-keep', KEEP, 'pdf.biz.hisobot',
         REPORT_UZ, 'uz', 'summary', 'Moliya bo‘limi xarajatlarni kamaytirdi.',
         facts=(('author', 'Moliya bo‘limi tomonidan tayyorlandi'),)),
    # A line led by its verb of preparing holds the run that ends it, as "Prepared by" does.
    body('held-rejected-author-after-tayyorladi-uz-blank', BLANK, 'pdf.biz.hisobot', REPORT_UZ, 'uz', 'summary',
         'Hikmat xarajatlarni kamaytirdi.', gone=('Hikmat',), facts=(('author', 'Hisobotni tayyorladi Hikmat Rahim'),)),
    body('held-role-only-line-tayyorladi-moliya-bolimi-holds-no-common-word-uz-keep', KEEP, 'pdf.biz.hisobot',
         REPORT_UZ, 'uz', 'summary', 'Moliya bo‘limi xarajatlarni kamaytirdi.',
         facts=(('author', 'Hisobotni tayyorladi Moliya bo‘limi'),)),
]

# ---- Placings written as ordinal words, the paraphrases round 2 left (must, item 4): the Uzbek past copula "edi" and
# "<ordinal> natija", a Russian ordinal with no verb or after a dash and "<ordinal> строчка", the English "was second"
# closing its clause and "second runner-up"; an ordinal before its own noun stays.
CASES += [
    gp('numbers-second-with-edi-in-an-olympiad-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Viloyat olimpiadasida u ikkinchi edi.', gone=('ikkinchi',)),
    gp('numbers-third-with-edim-by-sales-uz-blank', BLANK, COVER_UZ, 'uz', 'Filialimizda sotuv bo‘yicha uchinchi edim.',
       gone=('uchinchi',)),
    gp('numbers-second-result-in-an-olympiad-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Olimpiadada ikkinchi natijani ko‘rsatdi.', gone=('ikkinchi',)),
    gp('numbers-third-result-by-trade-volume-uz-blank', BLANK, COVER_UZ, 'uz',
       'Savdo hajmi bo‘yicha uchinchi natijani ko‘rsatdim.', gone=('uchinchi',)),
    gp('numbers-second-step-of-a-podium-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Olimpiada g‘olibi bo‘lib, ikkinchi pog‘onaga ko‘tarildi.', gone=('ikkinchi',)),
    gp('numbers-second-in-a-sellers-ranking-with-no-verb-ru-blank', BLANK, COVER_RU, 'ru',
       'Она вторая в рейтинге продавцов банка.', gone=('вторая',)),
    gp('numbers-third-by-sales-with-no-verb-ru-blank', BLANK, COVER_RU, 'ru', 'По продажам она третья в филиале.',
       gone=('третья',)),
    gp('numbers-third-by-sales-in-a-branch-with-no-verb-ru-blank', BLANK, COVER_RU, 'ru',
       'Она третья по продажам в нашем филиале.', gone=('третья',)),
    gp('numbers-third-line-of-a-sales-ranking-ru-blank', BLANK, COVER_RU, 'ru',
       'Она заняла третью строчку рейтинга продаж.', gone=('третью',)),
    gp('numbers-third-seller-after-a-dash-ru-blank', BLANK, COVER_RU, 'ru',
       'Она — третий продавец банка по объёму продаж.', gone=('третий',)),
    gp('numbers-third-among-a-regions-managers-ru-blank', BLANK, COVER_RU, 'ru',
       'Она оказалась третьей среди всех менеджеров региона.', gone=('третьей',)),
    gp('numbers-was-second-closing-its-clause-en-blank', BLANK, RECOMMENDATION_EN, 'en',
       'At the regional olympiad she was second.', gone=('second',)),
    gp('numbers-second-runner-up-en-blank', BLANK, RECOMMENDATION_EN, 'en', 'She was second runner-up at the olympiad.',
       gone=('second',)),
    gp('numbers-third-best-performer-in-a-sales-ranking-en-blank', BLANK, COVER_EN, 'en',
       'Last year I was the third best performer in the sales ranking.', gone=('third',)),
    gp('numbers-ranked-third-among-consultants-en-blank', BLANK, COVER_EN, 'en',
       'I ranked third in sales among 40 consultants.', gone=('third',)),
    gp('numbers-her-second-olympiad-with-edi-uz-keep', KEEP, REFERENCE_UZ, 'uz', 'Bu uning ikkinchi olimpiadasi edi.'),
    gp('numbers-the-second-stage-of-an-olympiad-uz-keep', KEEP, REFERENCE_UZ, 'uz',
       'Olimpiadaning ikkinchi bosqichi may oyida bo‘ldi.'),
    gp('numbers-the-second-part-of-an-olympiad-ru-keep', KEEP, COVER_RU, 'ru', 'Вторая часть олимпиады прошла онлайн.'),
    gp('numbers-second-to-none-at-an-olympiad-en-keep', KEEP, RECOMMENDATION_EN, 'en',
       'At the olympiad she was second to none in effort.'),
    gp('numbers-her-second-olympiad-en-keep', KEEP, RECOMMENDATION_EN, 'en', 'The regional olympiad was her second.'),
    # The round-1 re-check's forms the sweep still printed: a contest between "finished" and the ordinal, and a sales
    # race beside "my first place".
    gp('numbers-finished-an-olympiad-in-second-en-blank', BLANK, RECOMMENDATION_EN, 'en',
       'She finished the olympiad in second.', gone=('second',)),
    gp('numbers-my-first-place-in-a-sales-race-en-blank', BLANK, COVER_EN, 'en',
       'My first place in the sales race earned me a bonus.', gone=('first',)),
    gp('numbers-finished-a-course-in-second-year-en-keep', KEEP, RECOMMENDATION_EN, 'en',
       'She finished the course in second year.'),
    gp('numbers-her-first-result-at-an-olympiad-uz-keep', KEEP, REFERENCE_UZ, 'uz',
       'Olimpiadada uning birinchi natijasi yaxshi bo‘ldi.'),
    gp('numbers-the-first-from-a-school-who-went-to-an-olympiad-ru-keep', KEEP, COVER_RU, 'ru',
       'Мы с ней — первые из школы, кто поехал на олимпиаду.'),
    gp('numbers-winning-is-second-at-an-olympiad-en-keep', KEEP, RECOMMENDATION_EN, 'en',
       'Her goal at the olympiad is to learn, and winning is second.'),
]

# ---- "In sales" and "savdo bo‘yicha" are a ranking's scope only beside a ranking (should, from 3167c90): a sales
# letter's "comes first", "put the client first", "my first position in sales" and the job title "Savdo bo‘yicha
# menejer" place nothing; a placing in sales still goes.
CASES += [
    gp('numbers-the-customer-comes-first-in-sales-en-keep', KEEP, COVER_EN, 'en',
       'In sales, the customer always comes first.'),
    gp('numbers-needs-come-first-in-sales-en-keep', KEEP, COVER_EN, 'en', 'Customer needs always come first in sales.'),
    gp('numbers-trust-comes-first-for-sales-teams-en-keep', KEEP, COVER_EN, 'en',
       'For sales teams, trust comes first.'),
    gp('numbers-service-came-first-beside-sales-en-keep', KEEP, COVER_EN, 'en',
       'I was responsible for sales, and service always came first.'),
    gp('numbers-listening-comes-first-in-sales-en-keep', KEEP, COVER_EN, 'en',
       'Listening comes first in sales, and I practise it daily.'),
    gp('numbers-put-the-client-first-in-sales-en-keep', KEEP, COVER_EN, 'en',
       'I always put the client first in sales.'),
    gp('numbers-my-first-position-in-sales-en-keep', KEEP, COVER_EN, 'en',
       'My first position in sales was at a phone shop.'),
    gp('numbers-first-in-my-family-to-work-in-sales-en-keep', KEEP, COVER_EN, 'en',
       'I was first in my family to work in sales.'),
    gp('numbers-first-in-my-team-to-finish-sales-training-en-keep', KEEP, COVER_EN, 'en',
       'I was first in my team to finish the training in sales.'),
    gp('numbers-sales-manager-title-beside-first-in-priority-uz-keep', KEEP, COVER_UZ, 'uz',
       'Savdo bo‘yicha menejer sifatida men uchun mijoz doim birinchi o‘rinda turadi.'),
    gp('numbers-sales-work-beside-first-in-priority-uz-keep', KEEP, COVER_UZ, 'uz',
       'Sotuv bo‘yicha ishda mijoz manfaati birinchi o‘rinda.'),
    gp('numbers-first-in-sales-across-a-region-en-blank', BLANK, COVER_EN, 'en',
       'I was first in sales across the whole region.', gone=('first',)),
    gp('numbers-first-in-sales-last-year-en-blank', BLANK, COVER_EN, 'en', 'I was first in sales last year.',
       gone=('first',)),
    gp('numbers-came-first-in-a-branch-sales-ranking-en-blank', BLANK, COVER_EN, 'en',
       'I came first in the branch sales ranking.', gone=('first',)),
    gp('numbers-finished-the-year-third-in-sales-en-blank', BLANK, COVER_EN, 'en',
       'I finished the year third in sales.', gone=('third',)),
    gp('numbers-first-by-sales-uz-blank', BLANK, COVER_UZ, 'uz', 'Savdo bo‘yicha birinchi bo‘ldim.',
       gone=('birinchi',)),
]

# ---- A lower-case law after an adjective and its law-name word (must, item 5): "the current labour law", "the Uzbek
# labour law" cite a law as "the current civil code" does; a field ("labour law knowledge", "a degree in labour law")
# cites none.
JD_EN = 'Write a job description for an HR officer at our trading company.'
CASES += [
    guard('laws-lower-case-uzbek-labour-law-en-blank', BLANK, JD_EN, 'en', 'She must know the Uzbek labour law.',
          gone=('labour law',)),
    guard('laws-lower-case-current-labour-law-en-blank', BLANK, JD_EN, 'en',
          'She applies the current labour law to every contract.', gone=('labour law',)),
    guard('laws-a-degree-in-labour-law-en-keep', KEEP, JD_EN, 'en', 'She holds a degree in labour law.'),
    # A lower-case law with its "on" in quotation marks cites a law as the title in them does.
    guard('laws-lower-case-law-with-a-quoted-on-en-blank', BLANK, JD_EN, 'en',
          'He follows the law “on accounting” closely.', gone=('accounting',)),
    guard('laws-the-customers-lower-case-law-with-a-quoted-on-en-keep', KEEP, ACCOUNTING_EN, 'en',
          'He follows the law “on accounting” closely.'),
    guard('laws-the-customers-lower-case-zakon-with-its-quoted-title-ru-keep', KEEP, JOB_RU_ACCOUNTING, 'ru',
          'Применяет закон «О бухгалтерском учёте».'),
    guard('laws-an-invented-lower-case-zakon-with-its-quoted-title-ru-blank', BLANK, JOB_RU_ACCOUNTING, 'ru',
          'Применяет закон «О государственной пошлине».', gone=('пошлине',)),
    guard('laws-her-current-labour-law-knowledge-en-keep', KEEP, JD_EN, 'en',
          'Her current labour law knowledge is strong.'),
    # A law's rules after an adjective read as the law the same words cite: the blank is the price of "the new labour
    # law rules on leave".
    guard('laws-lower-case-new-labour-law-rules-en-blank', BLANK, JD_EN, 'en',
          'She follows the new labour law rules on leave.', gone=('labour law',)),
    guard('laws-the-basic-labour-law-rules-en-accepted_false_blank', ACCEPTED, JD_EN, 'en',
          'She explains the basic labour law rules to staff.', gone=('labour law',),
          pair='laws-lower-case-new-labour-law-rules-en-blank'),
]

# ---- A code's identifier sense after an indefinite article or an item's possessive, before "to each", "per", "for
# VAT" or "on each", or beside another identifier code (should, from 424c38a): no code is cited; "the tax code" alone,
# "the new tax code" and "the tax code in each filing" still are. A sentence that denies "the law about this" cites
# none either.
CASES += [
    guard('laws-a-budget-code-to-each-expense-en-keep', KEEP, JOB_EN, 'en',
          'He assigns a budget code to each expense.'),
    guard('laws-the-correct-tax-code-to-each-invoice-en-keep', KEEP, JOB_EN, 'en',
          'He applies the correct tax code to each invoice.'),
    guard('laws-the-tax-code-for-vat-on-each-line-en-keep', KEEP, JOB_EN, 'en',
          'The accountant enters the tax code for VAT on each line.'),
    guard('laws-each-items-customs-code-en-keep', KEEP, JOB_EN, 'en',
          'The accountant checks each item’s customs code.'),
    guard('laws-the-product-code-and-the-tax-code-en-keep', KEEP, JOB_EN, 'en',
          'The accountant enters the product code and the tax code in the system.'),
    guard('laws-the-tax-code-per-invoice-en-keep', KEEP, JOB_EN, 'en', 'He records one tax code per invoice.'),
    guard('laws-lower-case-tax-code-in-each-filing-en-blank', BLANK, JOB_EN, 'en',
          'He follows the tax code in each filing.', gone=('tax code',)),
    guard('laws-lower-case-the-countrys-tax-code-en-blank', BLANK, JOB_EN, 'en',
          'He knows the country’s tax code well.', gone=('tax code',)),
    guard('laws-a-law-about-this-ru-keep', KEEP, COVER_RU, 'ru',
          'Бухгалтер не нарушает закон об этом и никогда не спорит.'),
]

# ---- A held free first word is a given name, never a noun for people before a surname (should, from 8a3c061):
# "Investor Karimov ..." and "Клиент Иванова ..." hold no "Investor" or "Клиент" across the paper; "Kira Sokolova ..."
# still holds Kira.
CASES += [
    body('held-free-first-word-investor-uz-keep', KEEP, 'pdf.biz.hisobot', REPORT_UZ, 'uz', 'work_done',
         'Investor bilan muzokaralar davom etadi.',
         parts=(('summary', {'body': 'Investor Karimov 500 mln so‘m kiritdi.'}),)),
    body('held-free-first-word-klient-ru-keep', KEEP, 'pdf.biz.hisobot', REPORT_RU, 'ru', 'work_done',
         'Клиент всегда прав.', parts=(('summary', {'body': 'Клиент Иванова сделала крупный заказ.'}),)),
    body('held-given-name-of-a-two-word-name-ru-to-en-blank', BLANK, 'pdf.biz.hisobot', REPORT_RU_EN, 'en', 'work_done',
         'Kira also opened the new branch.', gone=('Kira',),
         parts=(('summary', {'body': 'Kira Sokolova led the finance team.'}),), translated=True),
]

# ---- The idiom's accepted blank is paid for by a placing the same words make (should, matrix): "birinchi", an
# abstract subject among the first two words and a place. A need comes first as an interest does, and a contest the
# idiom's "hayotida" subject is about places nothing (round 1's sweep, from 2ea06f3); the same idiom said at a
# workplace is the placing's accepted price. Round 5 removed the idiom exemption: every such idiom is that price now.
CASES += [
    gp('numbers-first-place-of-quality-in-a-region-uz-blank', BLANK, PLAN_UZ, 'uz',
       'Mahsulot sifati viloyatda birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    *removed(gp('numbers-first-place-idiom-customers-needs-uz-keep', KEEP, COVER_UZ, 'uz',
                'Mijozlar ehtiyoji har doim birinchi o‘rinni egallaydi.'),
             ('birinchi',), 'numbers-first-place-present-by-a-full-names-knowledge-uz-blank', listed=True),
    *removed(gp('numbers-first-place-idiom-preparing-for-an-olympiad-in-her-life-uz-keep', KEEP, REFERENCE_UZ, 'uz',
                'Olimpiadaga tayyorgarlik uning hayotida birinchi o‘rinni egallaydi.'),
             ('birinchi',), 'numbers-first-place-at-an-olympiad-in-her-life-uz-blank', listed=True),
    gp('numbers-first-place-at-an-olympiad-in-her-life-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Hayotida ilk bor olimpiadada birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    gp('numbers-first-place-idiom-at-my-workplace-uz-accepted_false_blank', ACCEPTED, COVER_UZ, 'uz',
       'Ish joyimda mijoz manfaati birinchi o‘rinni egallaydi.', gone=('birinchi',),
       pair='numbers-first-place-of-quality-in-a-region-uz-blank'),
]

# ---- An English paper reads a Latin word against the Uzbek lexicon whole, never through an ending (should, item 1):
# the given names the Uzbek lexicon parses ("Bogdan" bog+dan) or holds as a bare form ("Kira", "Dan", "Ida") are
# names there; an Uzbek word a paper names its own things by stays.
for name in ('Kira', 'Bogdan', 'Lina', 'Dan', 'Alma', 'Ida', 'Kara'):
    CASES.append(body(f'names-uzbek-lexicon-given-name-{name.lower()}-ru-to-en-blank', BLANK, 'pdf.biz.hisobot',
                      REPORT_RU_EN, 'en', 'summary', f'{name} opened the new branch in March.', gone=(name,),
                      translated=True))
for word, sentence in (('manti', 'Manti sell best in winter.'), ('mahalla', 'Mahalla committees support us.'),
                       ('somsa', 'Somsa is our best seller.'), ('halim', 'Halim is served in winter.')):
    CASES.append(gp(f'names-uzbek-word-{word}-opening-an-english-sentence-uz-to-en-keep', KEEP, PLAN_UZ_EN, 'en',
                    sentence, translated=True))

# ---------------------------------------------------------------- the re-check of round 3 (fix-r3), both ways
# Three exemptions of round 3 kept what c491da9 blanked: a position at the company held by a placing verb, the idiom
# "birinchi o‘rinni egallaydi" with a person, a name or a product as its subject, and a technology token before a
# school subject's or a curriculum's word. The leaks are pinned as blanks next to the keeps the exemptions were made
# for. Round 5 removed the three exemptions: the keeps are accepted false blanks those leaks pay for.

# ---- A position at the company is a job only after a possessive or a demonstrative, never after a placing verb
# (must, from bdfb210 and 800bc39); "first position as ..." stays a job as in c491da9. Round 5 removed the exemption
# of a position at the company: after a possessive too it is the placing c491da9 reads.
CASES += [
    gp('numbers-held-first-position-at-the-company-in-loan-sales-en-blank', BLANK, COVER_EN, 'en',
       'She held first position at the company in loan sales.', gone=('first',)),
    gp('numbers-reached-first-position-at-the-bank-en-blank', BLANK, COVER_EN, 'en',
       'I reached first position at the bank.', gone=('first',)),
    gp('numbers-reached-first-position-at-the-bank-in-deposits-en-blank', BLANK, COVER_EN, 'en',
       'I reached first position at the bank in deposits.', gone=('first',)),
    gp('numbers-took-first-position-at-the-firm-en-blank', BLANK, COVER_EN, 'en', 'He took first position at the firm.',
       gone=('first',)),
    gp('numbers-was-in-first-position-at-the-company-en-blank', BLANK, COVER_EN, 'en',
       'She was in first position at the company for sales volume.', gone=('first',)),
    gp('numbers-held-first-position-at-the-store-for-quarters-en-blank', BLANK, COVER_EN, 'en',
       'I held first position at the store for three quarters.', gone=('first',)),
    gp('numbers-secured-first-position-at-the-office-en-blank', BLANK, COVER_EN, 'en',
       'I secured first position at the office in monthly sales.', gone=('first',)),
    gp('numbers-claimed-first-position-at-the-organisation-en-blank', BLANK, COVER_EN, 'en',
       'She claimed first position at the organisation last year.', gone=('first',)),
    gp('numbers-achieved-first-position-at-the-shop-en-blank', BLANK, COVER_EN, 'en',
       'He achieved first position at the shop for customer service.', gone=('first',)),
    gp('numbers-earned-first-position-at-the-bank-en-blank', BLANK, COVER_EN, 'en',
       'I earned first position at the bank in loan sales.', gone=('first',)),
    gp('numbers-won-first-position-at-the-company-en-blank', BLANK, COVER_EN, 'en',
       'She won first position at the company in customer reviews.', gone=('first',)),
    gp('numbers-was-at-first-position-at-the-bank-en-blank', BLANK, COVER_EN, 'en',
       'She was at first position at the bank all year.', gone=('first',)),
    gp('numbers-remained-in-first-position-at-the-firm-en-blank', BLANK, COVER_EN, 'en',
       'He remained in first position at the firm all year.', gone=('first',)),
    gp('numbers-held-second-position-at-the-company-en-blank', BLANK, COVER_EN, 'en',
       'She held second position at the company in sales.', gone=('second',)),
    gp('numbers-reached-third-position-at-the-bank-en-blank', BLANK, COVER_EN, 'en',
       'I reached third position at the bank in deposits.', gone=('third',)),
    gp('numbers-kept-its-first-position-at-the-bank-en-blank', BLANK, COVER_EN, 'en',
       'The branch kept its first position at the bank in deposits.', gone=('first',)),
    gp('numbers-took-her-first-position-at-the-school-in-mathematics-en-blank', BLANK, RECOMMENDATION_EN, 'en',
       'She took her first position at the school in mathematics.', gone=('first',)),
    body('numbers-held-first-position-at-the-company-in-a-cover-letter-en-blank', BLANK, 'pdf.xat.ishga_kirish',
         COVER_EN, 'en', 'fit', 'In my last job I held first position at the company in monthly sales.',
         gone=('first',)),
    body('numbers-reached-first-position-at-the-store-in-a-cover-letter-uz-to-en-blank', BLANK,
         'pdf.xat.ishga_kirish', COVER_UZ_EN, 'en', 'fit',
         'I reached first position at the store and kept it for a year.', gone=('first',)),
    body('numbers-took-first-position-at-the-school-in-a-recommendation-en-blank', BLANK, 'pdf.xat.tavsiya',
         RECOMMENDATION_EN, 'en', 'evidence', 'She took first position at the school in mathematics.',
         gone=('first',)),
    *removed(gp('numbers-her-first-position-at-the-bank-en-keep', KEEP, RECOMMENDATION_EN, 'en',
                'Her first position at the bank was in the loans department.'),
             ('first',), 'numbers-her-first-position-at-the-company-in-loan-sales-en-blank', listed=True),
    *removed(gp('numbers-their-first-position-at-the-firm-en-keep', KEEP, RECOMMENDATION_EN, 'en',
                'Their first position at the firm was an internship.'),
             ('first',), 'numbers-their-first-position-at-the-bank-for-deposit-growth-en-blank', listed=True),
    *removed(gp('numbers-this-first-position-at-the-company-en-keep', KEEP, COVER_EN, 'en',
                'This first position at the company taught me discipline.'),
             ('first',), 'numbers-kept-this-first-position-at-the-company-en-blank', listed=True),
    *removed(gp('numbers-that-first-position-at-the-store-en-keep', KEEP, COVER_EN, 'en',
                'That first position at the store taught me patience.'),
             ('first',), 'numbers-maintained-that-first-position-at-the-bank-en-blank', listed=True),
    *removed(gp('numbers-in-her-first-position-at-the-company-en-keep', KEEP, RECOMMENDATION_EN, 'en',
                'In her first position at the company, she learned to listen to clients.'),
             ('first',), 'numbers-in-loan-sales-her-first-position-at-the-company-en-blank', listed=True),
    gp('numbers-my-first-position-as-an-analyst-en-keep', KEEP, COVER_EN, 'en',
       'My first position as an analyst taught me to check every figure.'),
    gp('numbers-took-her-first-position-as-an-analyst-en-keep', KEEP, RECOMMENDATION_EN, 'en',
       'She took her first position as an analyst after university.'),
    # A placing verb before the possessive reads as the placing the same words make: the blank is the price of "She
    # took her first position at the school in mathematics" (c491da9 blanks it too).
    gp('numbers-took-her-first-position-at-the-bank-en-accepted_false_blank', ACCEPTED, COVER_EN, 'en',
       'She took her first position at the bank after university.', gone=('first',),
       pair='numbers-took-her-first-position-at-the-school-in-mathematics-en-blank'),
]

# ---- "birinchi o‘rinni egallaydi" is the idiom "comes first" only with an abstract noun as its subject right before
# "birinchi", past an adverb of "always" and a "... uchun" or "... hayotida" (must, from 2ea06f3 and d4eeef4): a
# person, a name or a possessed organisation or product as the subject, a genitive or an "our" before the abstract
# noun ("Uning bilimi", "Mahsulotimiz sifati"), and "jihatidan", "bilan" or "bo‘yicha" before it make it a placing.
# Round 5 removed the idiom exemption: with an abstract subject too it is the placing c491da9 reads.
OFFER_UZ_FURNITURE = ('Mebel do‘konimiz uchun tijorat taklifi yozing, Toshkentda oshxona mebeli sotamiz, '
                      'chegirma 10 foiz.')
ESSAY_UZ_EDUCATION = 'Ta’lim sifati mavzusida mustaqil ish yozib bering.'
CASES += [
    gp('numbers-first-place-present-with-knowledge-by-a-pronoun-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Bilimi bilan u birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    gp('numbers-first-place-present-continuous-for-a-team-by-a-pronoun-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Jamoa uchun u doimo birinchi o‘rinni egallab keladi.', gone=('birinchi',)),
    gp('numbers-first-place-present-for-a-school-every-year-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Maktab uchun u har yili birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    gp('numbers-first-place-present-for-a-class-by-a-name-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Sinfi uchun Malika birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    gp('numbers-first-place-present-in-her-own-life-by-a-pronoun-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'U o‘z hayotida birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    gp('numbers-first-place-present-for-us-by-a-pronoun-always-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Biz uchun u har doim birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    gp('numbers-first-place-present-for-students-by-a-name-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Talabalar uchun Malika har doim birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    gp('numbers-first-place-present-by-a-student-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Bu talaba har doim birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    gp('numbers-first-place-present-with-manners-and-knowledge-by-a-name-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Odobi va bilimi bilan Malika birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    gp('numbers-first-place-present-continuous-for-them-by-a-name-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Ular uchun Malika birinchi o‘rinni egallab keladi.', gone=('birinchi',)),
    gp('numbers-first-place-present-in-quality-by-our-product-uz-blank', BLANK, PLAN_UZ, 'uz',
       'Sifat jihatidan mahsulotimiz birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    gp('numbers-first-place-present-in-quality-by-our-bakery-uz-blank', BLANK, PLAN_UZ, 'uz',
       'Sifat jihatdan nonvoyxonamiz birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    gp('numbers-first-place-present-in-its-quality-by-our-bread-uz-blank', BLANK, PLAN_UZ, 'uz',
       'Sifati jihatidan nonimiz birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    gp('numbers-first-place-present-with-its-quality-by-our-product-uz-blank', BLANK, PLAN_UZ, 'uz',
       'Mahsulotimiz sifati bilan birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    gp('numbers-first-place-present-by-our-products-in-demand-uz-blank', BLANK, PLAN_UZ, 'uz',
       'Ehtiyoji yuqori mahsulotlarimiz birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    gp('numbers-first-place-present-for-a-client-by-our-team-uz-blank', BLANK, COVER_UZ, 'uz',
       'Jamoamiz mijoz uchun birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    gp('numbers-first-place-present-by-our-products-quality-uz-blank', BLANK, PLAN_UZ, 'uz',
       'Mahsulotimiz sifati birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    gp('numbers-first-place-present-by-her-knowledge-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Uning bilimi birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    gp('numbers-first-place-present-by-a-names-knowledge-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Malikaning bilimi birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    gp('numbers-first-place-present-for-a-school-by-a-pupil-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Maktab uchun o‘quvchi har doim birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    body('numbers-first-place-present-with-knowledge-in-a-reference-uz-blank', BLANK, 'pdf.xat.tavsifnoma',
         REFERENCE_UZ, 'uz', 'achievements', 'Bilimi bilan u birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    body('numbers-first-place-present-continuous-for-a-team-in-a-reference-uz-blank', BLANK, 'pdf.xat.tavsifnoma',
         REFERENCE_UZ, 'uz', 'achievements', 'Jamoa uchun u doimo birinchi o‘rinni egallab keladi.',
         gone=('birinchi',)),
    body('numbers-first-place-present-in-quality-in-an-offer-uz-blank', BLANK, 'pdf.biz.tijorat_taklifi',
         OFFER_UZ_FURNITURE, 'uz', 'advantages', 'Sifat jihatidan mahsulotimiz birinchi o‘rinni egallaydi.',
         gone=('birinchi',)),
    *removed(gp('numbers-first-place-idiom-knowledge-for-a-name-uz-keep', KEEP, REFERENCE_UZ, 'uz',
                'Malika uchun bilim birinchi o‘rinni egallaydi.'),
             ('birinchi',), 'numbers-first-place-present-for-a-class-by-a-name-uz-blank', listed=True),
    *removed(gp('numbers-first-place-idiom-demand-uz-keep', KEEP, PLAN_UZ, 'uz', 'Talab birinchi o‘rinni egallaydi.'),
             ('birinchi',), 'numbers-first-place-present-by-a-name-that-is-an-abstract-noun-uz-blank', listed=True),
    *removed(gp('numbers-first-place-idiom-clients-demands-for-us-uz-keep', KEEP, PLAN_UZ, 'uz',
                'Mijozlar talabi biz uchun birinchi o‘rinni egallaydi.'),
             ('birinchi',), 'numbers-first-place-present-for-us-by-a-names-knowledge-uz-blank', listed=True),
    *removed(gp('numbers-first-place-idiom-safety-always-for-us-uz-keep', KEEP, PLAN_UZ, 'uz',
                'Biz uchun xavfsizlik har doim birinchi o‘rinni egallaydi.'),
             ('birinchi',), 'numbers-first-place-present-for-us-by-a-pronoun-always-uz-blank', listed=True),
    *removed(gp('numbers-first-place-idiom-childrens-safety-uz-keep', KEEP, PLAN_UZ, 'uz',
                'Bolalar xavfsizligi birinchi o‘rinni egallaydi.'),
             ('birinchi',), 'numbers-first-place-present-by-a-names-knowledge-without-the-genitive-uz-blank',
             listed=True),
    *removed(gp('numbers-first-place-idiom-family-in-her-life-uz-keep', KEEP, REFERENCE_UZ, 'uz',
                'Oila uning hayotida birinchi o‘rinni egallaydi.'),
             ('birinchi',), 'numbers-first-place-present-in-her-own-life-by-a-pronoun-uz-blank', listed=True),
    # The idiom said in a field ("sohasida", a locative) reads as the placing the same words make, as at a company or
    # a workplace above: the blank is the price of "Mahsulot sifati viloyatda birinchi o‘rinni egallaydi" (c491da9
    # blanks it too).
    gp('numbers-first-place-idiom-quality-in-the-field-of-education-uz-accepted_false_blank', ACCEPTED,
       ESSAY_UZ_EDUCATION, 'uz', 'Ta’lim sohasida sifat birinchi o‘rinni egallaydi.', gone=('birinchi',),
       pair='numbers-first-place-of-quality-in-a-region-uz-blank'),
    # A person's noun as the subject reads as the placing a pupil's makes, and a genitive before the abstract noun as
    # someone's own: the blanks are the price of "Maktab uchun o‘quvchi ..." and "Malikaning bilimi ..." (c491da9
    # blanks both too).
    gp('numbers-first-place-idiom-the-client-for-us-uz-accepted_false_blank', ACCEPTED, COVER_UZ, 'uz',
       'Biz uchun mijoz har doim birinchi o‘rinni egallaydi.', gone=('birinchi',),
       pair='numbers-first-place-present-for-a-school-by-a-pupil-uz-blank'),
    gp('numbers-first-place-idiom-the-clients-interest-in-the-genitive-uz-accepted_false_blank', ACCEPTED, COVER_UZ,
       'uz', 'Mijozning manfaati birinchi o‘rinni egallaydi.', gone=('birinchi',),
       pair='numbers-first-place-present-by-a-names-knowledge-uz-blank'),
]

# ---- A technology token is no class letter only before a device's or a medium's word, never a school subject's or
# a curriculum's (must, from f5904a5): "3D texnologiya", "Texnologiya 3D dasturi asosida" and "Informatika, 5G dastur"
# for the customer's "3-sinf" and "5-sinf" are invented classes; "3D modellash", "3D printer", "5G aloqa" stayed until
# round 5 removed the technology exemption: they are the classes c491da9 reads, the customer's own tokens stay.
for number, letter in (('3', 'D'), ('4', 'D'), ('5', 'G'), ('4', 'G'), ('2', 'D')):
    brief = f'{number}-sinf texnologiya fanidan dars ishlanmasi yozing, mavzu: qog‘oz bilan ishlash.'
    token = number + letter
    CASES += [
        fact(f'class-technology-shaped-letter-{token.lower()}-before-texnologiya-uz-blank', BLANK,
             'pdf.dars_ishlanmasi', brief, 'uz', 'subject', f'{token} texnologiya', gone=(token,)),
        fact(f'class-technology-shaped-letter-{token.lower()}-before-dasturi-uz-blank', BLANK,
             'pdf.dars_ishlanmasi', brief, 'uz', 'subject', f'Texnologiya {token} dasturi asosida', gone=(token,)),
        fact(f'class-technology-shaped-letter-{token.lower()}-before-a-lesson-of-texnologiya-uz-blank', BLANK,
             'pdf.dars_ishlanmasi', brief, 'uz', 'textbook', f'{token} texnologiya darsi', gone=(token,)),
    ]
LESSON_UZ_3_PAPER = '3-sinf texnologiya fanidan dars ishlanmasi yozing, mavzu: qog‘oz bilan ishlash.'
LESSON_UZ_5_NETWORKS = '5-sinf informatika fanidan dars ishlanmasi yozing, mavzu: kompyuter tarmoqlari.'
LESSON_RU_3 = '3-класс, технология, составьте план урока, тема: работа с бумагой.'
CASES += [
    fact('class-technology-shaped-letter-3d-before-a-comma-and-dasturi-uz-blank', BLANK, 'pdf.dars_ishlanmasi',
         LESSON_UZ_3_PAPER, 'uz', 'textbook', 'Texnologiya, 3D dasturi', gone=('3D',)),
    fact('class-technology-shaped-letter-5g-before-dastur-uz-blank', BLANK, 'pdf.dars_ishlanmasi',
         LESSON_UZ_5_NETWORKS, 'uz', 'textbook', 'Informatika, 5G dastur', gone=('5G',)),
    fact('class-technology-shaped-letter-5g-before-dasturi-in-a-subject-line-uz-blank', BLANK, 'pdf.dars_ishlanmasi',
         LESSON_UZ_5_NETWORKS, 'uz', 'subject', 'Informatika 5G dasturi', gone=('5G',)),
    fact('class-technology-shaped-letter-3d-before-tekhnologiya-ru-blank', BLANK, 'pdf.dars_ishlanmasi', LESSON_RU_3,
         'ru', 'subject', '3D технология', gone=('3D',)),
    fact('class-technology-shaped-letter-3d-before-programma-ru-blank', BLANK, 'pdf.dars_ishlanmasi', LESSON_RU_3,
         'ru', 'textbook', 'Технология, 3D программа', gone=('3D',)),
    *removed(fact('class-technology-token-5g-before-tarmoq-uz-keep', KEEP, 'pdf.dars_ishlanmasi',
                  LESSON_UZ_5_NETWORKS, 'uz', 'textbook', 'Informatika: 5G tarmoq'),
             ('5G',), 'class-technology-shaped-letter-5g-before-dastur-uz-blank', listed=True),
    *removed(fact('class-technology-token-3d-before-modellash-uz-keep', KEEP, 'pdf.dars_ishlanmasi',
                  LESSON_UZ_3_PAPER, 'uz', 'subject', '3D modellash'),
             ('3D',), 'class-technology-shaped-letter-3d-before-model-darsi-uz-blank', listed=True),
    *removed(fact('class-technology-token-3d-before-printer-uz-keep', KEEP, 'pdf.dars_ishlanmasi',
                  LESSON_UZ_3_PAPER, 'uz', 'textbook', 'Texnologiya: 3D printer'),
             ('3D',), 'class-technology-shaped-letter-3d-before-printsiplari-uz-blank', listed=True),
    *removed(fact('class-technology-token-3d-before-grafika-uz-keep', KEEP, 'pdf.dars_ishlanmasi',
                  LESSON_UZ_3_PAPER, 'uz', 'textbook', 'Texnologiya: 3D grafika asoslari'),
             ('3D',), 'class-technology-shaped-letter-5g-before-grafika-uz-blank', listed=True),
    *removed(fact('class-technology-token-2d-before-animatsiya-uz-keep', KEEP, 'pdf.dars_ishlanmasi',
                  '2-sinf texnologiya fanidan dars ishlanmasi yozing, mavzu: multfilm.', 'uz', 'textbook',
                  'Texnologiya: 2D animatsiya'),
             ('2D',), 'class-technology-shaped-letter-2d-before-videodars-uz-blank', listed=True),
    *removed(fact('class-technology-token-5g-before-aloqa-uz-keep', KEEP, 'pdf.dars_ishlanmasi',
                  LESSON_UZ_5_NETWORKS, 'uz', 'subject', 'Informatika: 5G aloqa'),
             ('5G',), 'class-technology-shaped-letter-3d-before-aloqa-madaniyati-uz-blank', listed=True),
    *removed(fact('class-technology-token-3d-before-modelirovanie-ru-keep', KEEP, 'pdf.dars_ishlanmasi', LESSON_RU_3,
                  'ru', 'textbook', 'Технология: 3D моделирование'),
             ('3D',), 'class-technology-shaped-letter-4k-before-modelirovanie-zadach-ru-blank', listed=True),
]

# ---------------------------------------------------------------- the re-check of round 4 (narrow-r1), both ways
# Round 4's narrowings still kept what c491da9 blanked: a position at the company after a possessive with any verb the
# list left out, the idiom "birinchi o‘rinni egallaydi" with a name, a person's or an organisation's possessed noun or
# a comparison's scope, a technology token before a curriculum word its stem collides with, and a place of study a
# verb holds. The leaks are pinned as blanks next to the keeps the exemptions were made for. Two narrowing rounds left
# paraphrase leaks, so round 5 removed the four exemptions (the owner's tie-break: when a leak and a false blank cannot
# both be avoided, blank): every keep they made is an accepted false blank c491da9 has too.

# ---- A position at the company is a job only where the possessive or the demonstrative opens its sentence, past one
# opening preposition, and no scope follows it (must, from 1bd1f8e): any verb, copula or noun before the possessive
# makes it the placing the same words make. Round 5: there too.
CASES += [
    gp(f'numbers-{slug}-en-blank', BLANK, brief, 'en', sentence, gone=gone)
    for slug, brief, sentence, gone in (
        ('was-in-her-first-position-at-the-company', COVER_EN,
         'She was in her first position at the company for sales volume.', ('first',)),
        ('was-at-her-first-position-at-the-bank', COVER_EN,
         'She was at her first position at the bank in deposits for a year.', ('first',)),
        ('remained-in-his-first-position-at-the-firm', COVER_EN,
         'He remained in his first position at the firm in loan sales.', ('first',)),
        ('stayed-in-her-first-position-at-the-store', COVER_EN,
         'She stayed in her first position at the store for three quarters.', ('first',)),
        ('is-in-her-first-position-at-the-company', COVER_EN,
         'She is in her first position at the company in loan sales this year.', ('first',)),
        ('has-been-in-her-first-position-at-the-bank', COVER_EN,
         'She has been in her first position at the bank in deposits since 2022.', ('first',)),
        ('maintained-her-first-position-at-the-bank-in-deposits', COVER_EN,
         'She maintained her first position at the bank in deposits for three years.', ('first',)),
        ('defended-his-first-position-at-the-company', COVER_EN,
         'He defended his first position at the company in sales volume.', ('first',)),
        ('regained-her-first-position-at-the-store', COVER_EN,
         'She regained her first position at the store last year.', ('first',)),
        ('retook-her-first-position-at-the-bank', COVER_EN,
         'She retook her first position at the bank in deposits.', ('first',)),
        ('reclaimed-his-first-position-at-the-firm', COVER_EN,
         'He reclaimed his first position at the firm in loan sales.', ('first',)),
        ('clinched-her-first-position-at-the-company', COVER_EN,
         'She clinched her first position at the company in monthly sales.', ('first',)),
        ('climbed-to-her-first-position-at-the-bank', COVER_EN,
         'She climbed to her first position at the bank in deposits.', ('first',)),
        ('rose-to-her-first-position-at-the-company', COVER_EN,
         'She rose to her first position at the company in loan sales.', ('first',)),
        ('held-on-to-her-first-position-at-the-company', COVER_EN,
         'She has held on to her first position at the company in loan sales.', ('first',)),
        ('kept-her-first-position-at-the-company', COVER_EN,
         'She kept her first position at the company in loan sales.', ('first',)),
        ('retained-his-first-position-at-the-firm', COVER_EN,
         'He retained his first position at the firm for two quarters.', ('first',)),
        ('occupied-his-first-position-at-the-company', COVER_EN,
         'He occupied his first position at the company in sales volume for a year.', ('first',)),
        ('cemented-her-first-position-at-the-store', COVER_EN,
         'She cemented her first position at the store for three quarters.', ('first',)),
        ('sales-earn-her-first-position-at-the-bank', COVER_EN,
         'Her loan sales earn her first position at the bank every quarter.', ('first',)),
        ('helped-her-achieve-her-first-position-at-the-company', COVER_EN,
         'Her results helped her achieve her first position at the company in loan sales.', ('first',)),
        ('worked-hard-to-claim-her-first-position-at-the-store', COVER_EN,
         'She worked hard to claim her first position at the store in monthly sales.', ('first',)),
        ('went-on-to-secure-her-first-position-at-the-bank', COVER_EN,
         'She went on to secure her first position at the bank in deposit growth.', ('first',)),
        ('maintained-that-first-position-at-the-bank', COVER_EN,
         'He maintained that first position at the bank in loan sales.', ('first',)),
        ('kept-this-first-position-at-the-company', COVER_EN,
         'She kept this first position at the company for a year.', ('first',)),
        ('by-sales-volume-their-first-position-at-the-bank', COVER_EN,
         'By sales volume, their first position at the bank never changed.', ('first',)),
        ('top-seller-her-first-position-at-the-store', COVER_EN,
         'Top seller of the year: her first position at the store in monthly sales.', ('first',)),
        ('in-loan-sales-her-first-position-at-the-company', COVER_EN,
         'In loan sales, her first position at the company lasted three quarters.', ('first',)),
        ('with-record-deposits-her-first-position-at-the-bank', COVER_EN,
         'With record deposits, her first position at the bank was secured.', ('first',)),
        ('her-first-position-at-the-company-in-loan-sales', COVER_EN,
         'Her first position at the company in loan sales lasted three quarters.', ('first',)),
        ('their-first-position-at-the-bank-for-deposit-growth', COVER_EN,
         'Their first position at the bank for deposit growth held all year.', ('first',)),
        ('kept-her-second-position-at-the-company', COVER_EN,
         'She kept her second position at the company in loan sales.', ('second',)),
        ('was-in-her-third-position-at-the-store', COVER_EN,
         'She was in her third position at the store in monthly sales.', ('third',)),
        ('defended-her-second-position-at-the-school', RECOMMENDATION_EN,
         'She defended her second position at the school in mathematics.', ('second',)),
        ('kept-her-first-position-at-the-school', RECOMMENDATION_EN,
         'She kept her first position at the school in mathematics.', ('first',)),
        ('her-first-position-at-the-school-in-mathematics', RECOMMENDATION_EN,
         'Her first position at the school in mathematics was well deserved.', ('first',)),
    )
]
CASES += [
    body('numbers-maintained-our-first-position-at-the-store-in-a-cover-letter-en-blank', BLANK,
         'pdf.xat.ishga_kirish', COVER_EN, 'en', 'fit',
         'In my last job I maintained our first position at the store in monthly sales.', gone=('first',)),
    body('numbers-kept-her-first-position-at-the-school-in-a-recommendation-en-blank', BLANK, 'pdf.xat.tavsiya',
         RECOMMENDATION_EN, 'en', 'evidence',
         'She kept her first position at the school in mathematics for three years.', gone=('first',)),
    *removed(gp('numbers-her-first-position-at-the-store-in-customer-service-en-keep', KEEP, COVER_EN, 'en',
                'Her first position at the store was in customer service.'),
             ('first',), 'numbers-her-first-position-at-the-company-in-loan-sales-en-blank'),
    *removed(gp('numbers-during-his-first-position-at-the-bank-en-keep', KEEP, RECOMMENDATION_EN, 'en',
                'During his first position at the bank, he learned to read contracts.'),
             ('first',), 'numbers-in-loan-sales-her-first-position-at-the-company-en-blank'),
    *removed(gp('numbers-after-her-first-position-at-the-firm-en-keep', KEEP, RECOMMENDATION_EN, 'en',
                'After her first position at the firm, she studied accounting.'),
             ('first',), 'numbers-with-record-deposits-her-first-position-at-the-bank-en-blank'),
    *removed(gp('numbers-her-second-position-at-the-bank-en-keep', KEEP, RECOMMENDATION_EN, 'en',
                'Her second position at the bank was in risk management.'),
             ('second',), 'numbers-kept-her-second-position-at-the-company-en-blank'),
    # A verb before the possessive, or a place after the company, reads as the placing the same words make: the blanks
    # are the price of "She maintained her first position at the bank in deposits ..." and "Her first position at the
    # company in loan sales ..." (c491da9 blanks both too).
    gp('numbers-started-her-first-position-at-the-bank-en-accepted_false_blank', ACCEPTED, RECOMMENDATION_EN, 'en',
       'She started her first position at the bank after university.', gone=('first',),
       pair='numbers-maintained-her-first-position-at-the-bank-in-deposits-en-blank'),
    gp('numbers-left-his-first-position-at-the-firm-en-accepted_false_blank', ACCEPTED, RECOMMENDATION_EN, 'en',
       'He left his first position at the firm after university.', gone=('first',),
       pair='numbers-maintained-her-first-position-at-the-bank-in-deposits-en-blank'),
    gp('numbers-her-first-position-at-the-store-in-the-city-centre-en-accepted_false_blank', ACCEPTED, COVER_EN, 'en',
       'Her first position at the store in the city centre was a cashier.', gone=('first',),
       pair='numbers-her-first-position-at-the-company-in-loan-sales-en-blank'),
]

# ---- A place of work, study or business is no placing only where its ordinal or the possessive before it opens the
# sentence and no contest or ranking stands in it (should, from bdfb210): "She held first place of study in her
# class" is a placing. Round 5 removed the exemption: a place of residence or of work is the placing c491da9 reads.
CASES += [
    gp('numbers-held-first-place-of-study-in-her-class-en-blank', BLANK, RECOMMENDATION_EN, 'en',
       'She held first place of study in her class.', gone=('first',)),
    gp('numbers-held-first-place-of-study-in-a-cover-letter-en-blank', BLANK, COVER_EN, 'en',
       'She held first place of study in her class.', gone=('first',)),
    gp('numbers-holds-first-place-of-study-in-her-group-en-blank', BLANK, RECOMMENDATION_EN, 'en',
       'She holds first place of study in her group.', gone=('first',)),
    gp('numbers-her-first-place-of-study-an-olympiad-en-blank', BLANK, RECOMMENDATION_EN, 'en',
       'Her first place of study: the regional olympiad, where she took the top prize.', gone=('first',)),
    gp('numbers-her-second-place-of-study-ranked-second-en-blank', BLANK, RECOMMENDATION_EN, 'en',
       'Her second place of study was ranked second in the region.', gone=('second',)),
    *removed(gp('numbers-his-first-place-of-residence-en-keep', KEEP, RECOMMENDATION_EN, 'en',
                'His first place of residence was a village.'),
             ('first',), 'numbers-her-first-place-of-study-an-olympiad-en-blank'),
    *removed(gp('numbers-first-place-of-work-opening-a-line-en-keep', KEEP, COVER_EN, 'en',
                'First place of work: a pharmacy.'),
             ('First',), 'numbers-held-first-place-of-study-in-a-cover-letter-en-blank'),
]

# ---- "birinchi o‘rinni egallaydi" is the idiom only with an abstract noun as its subject: bare and alone, after a
# dative ("Olimpiadaga tayyorgarlik") or, bare or possessed, after one word of a generic beneficiary ("Mijoz manfaati",
# "Bolalar xavfsizligi"), past a "... uchun" or "... hayotida" and an adverb of "always" (must, from 89970c9). A name
# ("Adolat"), a quoted or a capitalised word, a person's or an organisation's possessed noun ("Malika bilimi",
# "Do‘konimiz mahsulotlari sifati", "Kompaniya sifati") and a comparison's or a ranking's scope ("nisbatan",
# "bo‘ylab", "ko‘ra", "orasidan") make it a placing. Round 5: so does every abstract subject.
REFERENCE_UZ_ADOLAT = ('Karimova Adolat uchun tavsifnoma yozib bering, u 9-sinf o‘quvchisi, darslarda faol.')
REFERENCE_UZ_ADOLAT_CYRILLIC = 'Каримова Адолат учун тавсифнома ёзиб беринг, у 9-синф ўқувчиси, дарсларда фаол.'
CASES += [
    gp(f'numbers-first-place-present-{slug}-uz-blank', BLANK, brief, 'uz', sentence, gone=('birinchi',))
    for slug, brief, sentence in (
        ('every-year-by-a-name-that-is-an-abstract-noun', REFERENCE_UZ_ADOLAT,
         'Har yili Adolat birinchi o‘rinni egallaydi.'),
        ('always-by-a-name-that-is-an-abstract-noun', REFERENCE_UZ_ADOLAT, 'Adolat doimo birinchi o‘rinni egallaydi.'),
        ('by-a-name-that-is-an-abstract-noun', REFERENCE_UZ_ADOLAT, 'Adolat birinchi o‘rinni egallaydi.'),
        ('by-a-name-that-is-an-abstract-noun-cyrillic-brief', REFERENCE_UZ_ADOLAT_CYRILLIC,
         'Har doim Adolat birinchi o‘rinni egallaydi.'),
        ('held-by-a-name-that-is-an-abstract-noun', REFERENCE_UZ_ADOLAT, 'Adolat har doim birinchi o‘rinni tutadi.'),
        ('by-a-names-knowledge-without-the-genitive', REFERENCE_UZ, 'Malika bilimi birinchi o‘rinni egallaydi.'),
        ('always-by-a-names-knowledge', REFERENCE_UZ, 'Malika bilimi doimo birinchi o‘rinni egallaydi.'),
        ('by-a-full-names-knowledge', REFERENCE_UZ, 'Qodirova Malika bilimi har doim birinchi o‘rinni egallaydi.'),
        ('by-this-pupils-knowledge', REFERENCE_UZ, 'Bu o‘quvchi bilimi birinchi o‘rinni egallaydi.'),
        ('by-her-class-discipline', REFERENCE_UZ, 'Uning sinfi intizomi birinchi o‘rinni egallaydi.'),
        ('for-us-by-a-names-knowledge', REFERENCE_UZ, 'Biz uchun Malika bilimi birinchi o‘rinni egallaydi.'),
        ('for-teachers-by-a-names-upbringing', REFERENCE_UZ,
         'O‘qituvchilar uchun Malika tarbiyasi birinchi o‘rinni egallaydi.'),
        ('by-a-name-and-quality', REFERENCE_UZ, 'Malika sifat birinchi o‘rinni egallaydi.'),
        ('held-by-a-names-manners', REFERENCE_UZ, 'Malika odobi birinchi o‘rinni tutadi.'),
        ('continuous-by-a-names-knowledge', REFERENCE_UZ, 'Malika bilimi har doim birinchi o‘rinni egallab keladi.'),
        ('by-a-class-discipline', REFERENCE_UZ, 'Sinf intizomi har doim birinchi o‘rinni egallaydi.'),
        ('by-her-own-knowledge-alone', REFERENCE_UZ, 'Bilimi doimo birinchi o‘rinni egallaydi.'),
        ('across-a-district-by-knowledge', REFERENCE_UZ, 'Tuman bo‘ylab bilim birinchi o‘rinni egallaydi.'),
        ('by-the-results-by-her-knowledge', REFERENCE_UZ, 'Natijalarga ko‘ra bilimi birinchi o‘rinni egallaydi.'),
        ('by-the-figures-by-her-knowledge', REFERENCE_UZ,
         'Ko‘rsatkichlar yuzasidan bilimi birinchi o‘rinni egallaydi.'),
        ('from-the-marks-point-of-view-by-her-knowledge', REFERENCE_UZ,
         'Baholar nuqtai nazaridan bilimi birinchi o‘rinni egallaydi.'),
        ('beside-classmates-by-her-knowledge', REFERENCE_UZ,
         'Sinfdoshlariga nisbatan bilimi birinchi o‘rinni egallaydi.'),
        ('among-pupils-by-discipline', REFERENCE_UZ, 'O‘quvchilar orasidan intizom birinchi o‘rinni egallaydi.'),
        ('by-our-stores-products-quality', OFFER_UZ_FURNITURE,
         'Do‘konimiz mahsulotlari sifati birinchi o‘rinni egallaydi.'),
        ('by-our-furnitures-quality', OFFER_UZ_FURNITURE, 'Bizning mebel sifati birinchi o‘rinni egallaydi.'),
        ('by-our-firms-service-quality', OFFER_UZ_FURNITURE, 'Firmamiz xizmati sifati birinchi o‘rinni egallaydi.'),
        ('by-a-companys-quality', OFFER_UZ_FURNITURE, 'Kompaniya sifati birinchi o‘rinni egallaydi.'),
        ('by-a-stores-quality', OFFER_UZ_FURNITURE, 'Do‘kon sifati har doim birinchi o‘rinni egallaydi.'),
        ('by-furnitures-quality', OFFER_UZ_FURNITURE, 'Mebel sifati doimo birinchi o‘rinni egallaydi.'),
        ('by-a-quoted-name', OFFER_UZ_FURNITURE, '«Ishonch» birinchi o‘rinni egallaydi.'),
        ('beside-competitors-by-furnitures-quality', OFFER_UZ_FURNITURE,
         'Raqobatchilarga nisbatan mebel sifati birinchi o‘rinni egallaydi.'),
        ('beside-other-stores-by-quality', OFFER_UZ_FURNITURE,
         'Boshqa do‘konlarga nisbatan sifat birinchi o‘rinni egallaydi.'),
        ('among-competitors-by-quality', OFFER_UZ_FURNITURE,
         'Raqobatchilar orasidan sifat birinchi o‘rinni egallaydi.'),
        ('compared-with-other-stores-by-quality', OFFER_UZ_FURNITURE,
         'Boshqa do‘konlar bilan solishtirganda sifat birinchi o‘rinni egallaydi.'),
        ('across-a-city-by-furnitures-quality', OFFER_UZ_FURNITURE,
         'Toshkent bo‘ylab mebel sifati birinchi o‘rinni egallaydi.'),
        ('across-a-region-by-quality', OFFER_UZ_FURNITURE, 'Viloyat bo‘ylab sifat birinchi o‘rinni egallaydi.'),
        ('by-clients-opinion-by-furnitures-quality', OFFER_UZ_FURNITURE,
         'Mijozlar fikriga ko‘ra mebel sifati birinchi o‘rinni egallaydi.'),
        ('beside-colleagues-by-sales-quality', COVER_UZ,
         'Hamkasblarga nisbatan sotuv sifati birinchi o‘rinni egallaydi.'),
        ('across-a-branch-by-clients-trust', COVER_UZ, 'Filial bo‘ylab mijozlar ishonchi birinchi o‘rinni egallaydi.'),
    )
]
CASES += [
    body('numbers-first-place-present-by-a-names-knowledge-in-a-reference-uz-blank', BLANK, 'pdf.xat.tavsifnoma',
         REFERENCE_UZ, 'uz', 'achievements', 'Malika bilimi doimo birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    body('numbers-first-place-present-by-a-name-that-is-an-abstract-noun-in-a-reference-uz-blank', BLANK,
         'pdf.xat.tavsifnoma', REFERENCE_UZ_ADOLAT, 'uz', 'achievements',
         'Har yili Adolat birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    body('numbers-first-place-present-by-a-name-that-is-an-abstract-noun-cyrillic-brief-in-a-reference-uz-blank',
         BLANK, 'pdf.xat.tavsifnoma', REFERENCE_UZ_ADOLAT_CYRILLIC, 'uz', 'achievements',
         'Har doim Adolat birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    body('numbers-first-place-present-across-a-city-in-an-offer-uz-blank', BLANK, 'pdf.biz.tijorat_taklifi',
         OFFER_UZ_FURNITURE, 'uz', 'advantages', 'Toshkent bo‘ylab mebel sifati birinchi o‘rinni egallaydi.',
         gone=('birinchi',)),
    body('numbers-first-place-present-beside-competitors-in-an-offer-uz-blank', BLANK, 'pdf.biz.tijorat_taklifi',
         OFFER_UZ_FURNITURE, 'uz', 'advantages', 'Raqobatchilarga nisbatan mebel sifati birinchi o‘rinni egallaydi.',
         gone=('birinchi',)),
    *removed(gp('numbers-first-place-idiom-trust-always-uz-keep', KEEP, PLAN_UZ, 'uz',
                'Ishonch doimo birinchi o‘rinni egallaydi.'),
             ('birinchi',), 'numbers-first-place-present-always-by-a-name-that-is-an-abstract-noun-uz-blank'),
    *removed(gp('numbers-first-place-idiom-clients-trust-always-uz-keep', KEEP, COVER_UZ, 'uz',
                'Mijozlar ishonchi doimo birinchi o‘rinni egallaydi.'),
             ('birinchi',), 'numbers-first-place-present-always-by-a-names-knowledge-uz-blank'),
    *removed(gp('numbers-first-place-idiom-buyers-interest-for-us-uz-keep', KEEP, OFFER_UZ_FURNITURE, 'uz',
                'Xaridorlar manfaati biz uchun doimo birinchi o‘rinni egallaydi.'),
             ('birinchi',), 'numbers-first-place-present-for-us-by-a-names-knowledge-uz-blank'),
    *removed(gp('numbers-first-place-idiom-exam-preparation-in-her-life-uz-keep', KEEP, REFERENCE_UZ, 'uz',
                'Imtihonga tayyorgarlik uning hayotida birinchi o‘rinni egallaydi.'),
             ('birinchi',), 'numbers-first-place-at-an-olympiad-in-her-life-uz-blank'),
    *removed(gp('numbers-first-place-idiom-quality-and-honesty-uz-keep', KEEP, OFFER_UZ_FURNITURE, 'uz',
                'Sifat va halollik birinchi o‘rinni egallaydi.'),
             ('birinchi',), 'numbers-first-place-present-by-a-name-and-knowledge-uz-blank'),
    gp('numbers-first-place-present-by-a-name-and-knowledge-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'Malika va bilimi birinchi o‘rinni egallaydi.', gone=('birinchi',)),
    # A noun before the abstract noun that is no generic beneficiary reads as the owner a placing ranks: the blanks are
    # the price of "Mebel sifati doimo ..." and "Kompaniya sifati ..." (c491da9 blanks both too).
    gp('numbers-first-place-idiom-product-quality-uz-accepted_false_blank', ACCEPTED, OFFER_UZ_FURNITURE, 'uz',
       'Mahsulot sifati birinchi o‘rinni egallaydi.', gone=('birinchi',),
       pair='numbers-first-place-present-by-furnitures-quality-uz-blank'),
    gp('numbers-first-place-idiom-service-quality-uz-accepted_false_blank', ACCEPTED, OFFER_UZ_FURNITURE, 'uz',
       'Xizmat sifati birinchi o‘rinni egallaydi.', gone=('birinchi',),
       pair='numbers-first-place-present-by-a-companys-quality-uz-blank'),
]

# ---- A technology token is no class letter only before its own device's or medium's word (must, from dbfe0b8): "3D"
# and the other D tokens before a model, a printer, graphics, an animation or a film; "3G" to "5G" before a network, the
# internet or a phone; "4K" and "8K" before a video or a screen; "1C" before accounting. A curriculum word a stem
# collides with ("monitoring", "printsiplari", "videodars", "kinodars", "model darsi", "связная речь", "графики
# функций") and a school subject ("dizayn va texnologiya", "Design and Technology") name no technology. Round 5
# removed the technology exemption: before its own device's word too the token is the class c491da9 reads.
LESSON_UZ_N = '{}-sinf matematika fanidan dars ishlanmasi yozing, mavzu: qo‘shish va ayirish.'
TEST_UZ_MONITORING = '{}-sinf matematika fanidan choraklik monitoring testi tuzing, 10 ta savol.'
LESSON_RU_N = 'Напишите план урока для {} класса по русскому языку, тема: {}.'
LESSON_EN_DESIGN = 'Write a lesson plan for grade 3 design and technology, topic: paper models.'
for number, letter in (('2', 'D'), ('3', 'D'), ('4', 'D'), ('3', 'G'), ('4', 'G'), ('5', 'G')):
    token = number + letter
    CASES += [
        fact(f'class-technology-shaped-letter-{token.lower()}-before-monitoring-testi-uz-blank', BLANK, 'pdf.test',
             TEST_UZ_MONITORING.format(number), 'uz', 'kind', f'{token} monitoring testi', gone=(token,)),
        fact(f'class-technology-shaped-letter-{token.lower()}-before-monitoring-in-a-term-uz-blank', BLANK, 'pdf.test',
             TEST_UZ_MONITORING.format(number), 'uz', 'term_and_number', f'{token} monitoring', gone=(token,)),
        fact(f'class-technology-shaped-letter-{token.lower()}-before-monitoring-in-a-subject-uz-blank', BLANK,
             'pdf.dars_ishlanmasi', LESSON_UZ_N.format(number), 'uz', 'subject', f'Matematika, {token} monitoring',
             gone=(token,)),
        fact(f'class-technology-shaped-letter-{token.lower()}-before-monitoringi-uz-blank', BLANK, 'pdf.test',
             TEST_UZ_MONITORING.format(number), 'uz', 'kind', f'{token} monitoringi', gone=(token,)),
        fact(f'class-technology-shaped-letter-{token.lower()}-hyphen-monitoring-uz-blank', BLANK, 'pdf.test',
             TEST_UZ_MONITORING.format(number), 'uz', 'kind', f'{token}-monitoring', gone=(token,)),
        fact(f'class-technology-shaped-letter-{token.lower()}-spaced-before-monitoring-uz-blank', BLANK, 'pdf.test',
             TEST_UZ_MONITORING.format(number), 'uz', 'kind', f'{number} {letter} monitoring testi',
             gone=(token, f'{number} {letter}')),
    ]
    CASES += [
        fact(f'class-technology-shaped-letter-{token.lower()}-before-{slug}-uz-blank', BLANK, 'pdf.dars_ishlanmasi',
             LESSON_UZ_N.format(number), 'uz', 'subject', f'{token} {words}', gone=(token,))
        for slug, words in (('printsiplari', 'printsiplari'), ('videodars', 'videodars'), ('kinodars', 'kinodars'),
                            ('model-darsi', 'model darsi'), ('dizayn-va-texnologiya', 'dizayn va texnologiya'),
                            ('ekran-oldida', 'ekran oldida'), ('video-darslik', 'video darslik'))
    ]
for number, letter, words, slug in (('1', 'С', 'печатные буквы', 'pechatnye-bukvy'),
                                    ('1', 'С', 'связная речь', 'svyaznaya-rech'),
                                    ('8', 'К', 'графики функций', 'grafiki-funktsiy'),
                                    ('4', 'К', 'графический диктант', 'graficheskiy-diktant'),
                                    ('4', 'К', 'моделирование задач', 'modelirovanie-zadach'),
                                    ('8', 'К', 'связь слов', 'svyaz-slov'),
                                    ('8', 'К', 'графика', 'grafika')):
    CASES.append(fact(f'class-technology-shaped-letter-{number}{"c" if letter == "С" else "k"}-before-{slug}-ru-blank',
                      BLANK, 'pdf.dars_ishlanmasi', LESSON_RU_N.format(number, words), 'ru', 'subject',
                      f'{number}{letter} {words}', gone=(number + letter,)))
CASES += [
    fact('class-technology-shaped-letter-5g-before-grafika-uz-blank', BLANK, 'pdf.dars_ishlanmasi',
         LESSON_UZ_N.format(5), 'uz', 'subject', '5G grafika', gone=('5G',)),
    fact('class-technology-shaped-letter-3d-before-aloqa-madaniyati-uz-blank', BLANK, 'pdf.dars_ishlanmasi',
         LESSON_UZ_N.format(3), 'uz', 'subject', '3D aloqa madaniyati', gone=('3D',)),
    fact('class-technology-shaped-letter-3d-before-design-and-technology-en-blank', BLANK, 'pdf.dars_ishlanmasi',
         LESSON_EN_DESIGN, 'en', 'subject', '3D Design and Technology', gone=('3D',)),
    fact('class-technology-shaped-letter-3d-before-design-en-blank', BLANK, 'pdf.dars_ishlanmasi', LESSON_EN_DESIGN,
         'en', 'textbook', '3D design', gone=('3D',)),
    *removed(fact('class-technology-token-3d-before-printing-en-keep', KEEP, 'pdf.dars_ishlanmasi', LESSON_EN_DESIGN,
                  'en', 'subject', '3D printing'),
             ('3D',), 'class-technology-shaped-letter-3d-before-design-en-blank'),
    *removed(fact('class-technology-token-3d-before-modelling-en-keep', KEEP, 'pdf.dars_ishlanmasi', LESSON_EN_DESIGN,
                  'en', 'textbook', '3D modelling'),
             ('3D',), 'class-technology-shaped-letter-3d-before-design-and-technology-en-blank'),
    # A bare "model" or "dizayn" after "3D" reads as the class a curriculum word makes: the blanks are the price of "2D
    # model darsi" and "3D dizayn va texnologiya" (c491da9 blanks both too).
    fact('class-technology-token-3d-before-a-bare-model-uz-accepted_false_blank', ACCEPTED, 'pdf.dars_ishlanmasi',
         LESSON_UZ_3_PAPER, 'uz', 'textbook', 'Texnologiya: 3D model yasash', gone=('3D',),
         pair='class-technology-shaped-letter-2d-before-model-darsi-uz-blank'),
    fact('class-technology-token-3d-before-dizayn-uz-accepted_false_blank', ACCEPTED, 'pdf.dars_ishlanmasi',
         LESSON_UZ_3_PAPER, 'uz', 'textbook', 'Texnologiya: 3D dizayn asoslari', gone=('3D',),
         pair='class-technology-shaped-letter-3d-before-dizayn-va-texnologiya-uz-blank'),
]

# ---------------------------------------------------------------- the re-check of round 5 (drop-r1), both ways
# Round 5 left two readings that kept what c491da9 blanks: the customer's collective of the best gave its count as a
# figure, and a translated paper's accounting law took any word of its head noun's stem.

# ---- A collective of the best is a key of its own (must, from 21147ba and 3167c90): the customer's "вошла в тройку
# лучших", "входит в тройку лидеров рынка", "eng yaxshi uchlikka kirdi" or "g‘oliblar beshligiga kirgan" grounds the
# paper's same collective, never a bare 3, "третье место", "uchinchi o‘rin" or "3 года". Being among the top three is
# not finishing third.
COVER_RU_TOP3 = ('Напишите сопроводительное письмо на должность менеджера по продажам. Я Малика Кодирова, работала в '
                 'рознице, в прошлом году вошла в тройку лучших продавцов региона.')
COVER_RU_TOP3_LEADERS = ('Напишите сопроводительное письмо менеджера по продажам. Я Малика Кодирова, в прошлом году '
                         'была в тройке лидеров продаж сети.')
COVER_RU_THREE_YEARS = ('Напишите сопроводительное письмо на должность менеджера по продажам. Я Малика Кодирова, '
                        'работала в рознице 3 года.')
COVER_RU_THREE_BEST = ('Напишите сопроводительное письмо на должность менеджера по продажам. Я Малика Кодирова, '
                       'в прошлом году была среди трёх лучших продавцов региона.')
COVER_EN_TOP3_RU = ('Please write in Russian a cover letter for me, Malika Qodirova, sales manager. Last year I was '
                    'among the top three sellers of the region.')
COVER_UZ_TOP3 = ('Ishga kirish xati yozing. Ismim Qodirova Malika, sotuv menejeri lavozimiga topshiraman. O‘tgan yili '
                 'viloyat sotuvchilari reytingida eng yaxshi uchlikka kirdim.')
COVER_UZ_THREE_BEST = ('Ishga kirish xati yozing. Ismim Qodirova Malika, sotuv menejeri lavozimiga topshiraman. O‘tgan '
                       'yili viloyatda eng yaxshi uch sotuvchidan biri bo‘ldim.')
COVER_UZ_THREE_YEARS = ('Ishga kirish xati yozing. Ismim Qodirova Malika, sotuv menejeri lavozimiga topshiraman. '
                        'Savdoda 3 yil ishlaganman.')
REFERENCE_UZ_TOP5 = ('Qodirova Malika uchun tavsifnoma yozing, u o‘quvchi, viloyat olimpiadasida g‘oliblar beshligiga '
                     'kirgan, darslarda faol.')
REPORT_RU_TOP3 = ('Напишите отчёт о работе нашей пекарни за год. Наша пекарня входит в тройку лидеров рынка Ташкента, '
                  'продажи выросли, открыли новый цех.')
REPORT_UZ_TOP3 = ('Nonvoyxonamiz faoliyati bo‘yicha yillik hisobot yozing. Nonvoyxonamiz shahar bozorida eng yaxshi '
                  'uchlikka kirdi, sotuv o‘sdi, yangi sex ochdik.')
for slug, brief, locale, rows in (
        ('a-bakerys-report', REPORT_RU_TOP3, 'ru', (
            ('three-new-branches', 'В этом году мы открыли 3 новых филиала.', ('3',)),
            ('third-place-in-a-city-ranking', 'Пекарня заняла третье место в городском рейтинге.', ('третье',)),
            ('three-quarters-in-a-row', 'Продажи выросли за 3 квартала подряд.', ('3',)))),
        ('a-bakerys-report', REPORT_UZ_TOP3, 'uz', (
            ('three-new-branches', 'Bu yil 3 ta yangi filial ochdik.', ('3',)),
            ('third-place-in-a-city-ranking', 'Nonvoyxona shahar reytingida uchinchi o‘rinni egalladi.',
             ('uchinchi',)),
            ('three-quarters', 'Sotuv 3 chorak davomida o‘sdi.', ('3',))))):
    for row_slug, sentence, gone in rows:
        CASES += [
            gp(f'numbers-top-three-in-{slug}-grounds-no-{row_slug}-{locale}-blank', BLANK, brief, locale, sentence,
               gone=gone),
            body(f'numbers-top-three-in-{slug}-grounds-no-{row_slug}-in-its-results-{locale}-blank', BLANK,
                 'pdf.biz.hisobot', brief, locale, 'results', sentence, gone=gone),
        ]
for row_slug, sentence, gone in (
        ('third-place-among-sellers', 'В прошлом году я заняла третье место среди продавцов региона.', ('третье',)),
        ('three-years-in-sales', 'Я работаю в продажах 3 года.', ('3',)),
        ('three-months', 'За 3 месяца я увеличила продажи вдвое.', ('3',)),
        ('three-years-in-words', 'Мой опыт в рознице — три года.', ('три',))):
    CASES += [
        gp(f'numbers-top-three-in-a-cover-letter-grounds-no-{row_slug}-ru-blank', BLANK, COVER_RU_TOP3, 'ru', sentence,
           gone=gone),
        body(f'numbers-top-three-in-a-cover-letter-grounds-no-{row_slug}-in-its-fit-ru-blank', BLANK,
             'pdf.xat.ishga_kirish', COVER_RU_TOP3, 'ru', 'fit', sentence, gone=gone),
    ]
for row_slug, sentence, gone in (
        ('third-place-by-sales', 'O‘tgan yili viloyatda sotuv bo‘yicha uchinchi o‘rinni egalladim.', ('uchinchi',)),
        ('third-in-a-ranking', 'Viloyat reytingida uchinchi bo‘ldim.', ('uchinchi',)),
        ('three-years-in-trade', 'Savdoda 3 yil ishlaganman.', ('3',)),
        ('three-months', 'Sotuvni 3 oyda oshirdim.', ('3',)),
        ('three-years-in-words', 'Savdo sohasida uch yillik tajribam bor.', ('uch',))):
    CASES.append(gp(f'numbers-top-three-in-a-cover-letter-grounds-no-{row_slug}-uz-blank', BLANK, COVER_UZ_TOP3, 'uz',
                    sentence, gone=gone))
for row_slug, sentence, gone in (
        ('fifth-place', 'Viloyat olimpiadasida beshinchi o‘rinni egallagan.', ('beshinchi',)),
        ('five-years', 'U 5 yildan beri olimpiadalarga tayyorlanadi.', ('5',))):
    CASES += [
        gp(f'numbers-top-five-in-a-reference-grounds-no-{row_slug}-uz-blank', BLANK, REFERENCE_UZ_TOP5, 'uz', sentence,
           gone=gone),
        body(f'numbers-top-five-in-a-reference-grounds-no-{row_slug}-in-its-traits-uz-blank', BLANK,
             'pdf.xat.tavsifnoma', REFERENCE_UZ_TOP5, 'uz', 'traits', sentence, gone=gone),
    ]
CASES += [
    gp('numbers-top-three-leaders-grounds-no-third-place-ru-blank', BLANK, COVER_RU_TOP3_LEADERS, 'ru',
       'Она заняла третье место.', gone=('третье',)),
    gp('numbers-top-three-leaders-grounds-no-three-years-ru-blank', BLANK, COVER_RU_TOP3_LEADERS, 'ru',
       'Опыт работы — 3 года.', gone=('3',)),
    # The paper's collective needs the customer's: their "3 года" grounds no "тройку лучших".
    gp('numbers-three-years-grounds-no-top-three-ru-blank', BLANK, COVER_RU_THREE_YEARS, 'ru',
       'В прошлом году я вошла в тройку лучших продавцов региона.', gone=('тройку',)),
    gp('numbers-top-three-grounds-no-top-five-ru-blank', BLANK, COVER_RU_TOP3, 'ru',
       'Вошла в пятёрку лучших продавцов региона.', gone=('пятёрку',)),
    gp('numbers-the-customers-top-three-ru-keep', KEEP, COVER_RU_TOP3, 'ru',
       'В прошлом году я вошла в тройку лучших продавцов региона.'),
    gp('numbers-the-customers-top-three-leaders-of-a-market-ru-keep', KEEP, REPORT_RU_TOP3, 'ru',
       'Пекарня входит в тройку лидеров рынка Ташкента.'),
    gp('numbers-the-customers-top-three-uz-keep', KEEP, COVER_UZ_TOP3, 'uz',
       'O‘tgan yili viloyat reytingida eng yaxshi uchlikka kirdim.'),
    gp('numbers-the-customers-top-five-winners-uz-keep', KEEP, REFERENCE_UZ_TOP5, 'uz',
       'Viloyat olimpiadasida g‘oliblar beshligiga kirgan.'),
    gp('numbers-three-years-grounds-no-top-three-uz-blank', BLANK, COVER_UZ_THREE_YEARS, 'uz',
       'O‘tgan yili viloyatda eng yaxshi uchlikka kirdim.', gone=('uchlik',)),
    # The customer's top three in other words ("среди трёх лучших", English "the top three", "eng yaxshi uch
    # sotuvchidan biri") gives only its bare 3, as c491da9 reads it, and a bare 3 grounds no collective: the blanks are
    # the price of "3 года" and "3 yil" grounding "тройку лучших" and "uchlikka" (c491da9 reads no collective and keeps
    # these, as it keeps the leaks).
    gp('numbers-the-customers-three-best-in-other-words-ru-accepted_false_blank', ACCEPTED, COVER_RU_THREE_BEST, 'ru',
       'В прошлом году я вошла в тройку лучших продавцов региона.', gone=('тройку',),
       pair='numbers-three-years-grounds-no-top-three-ru-blank'),
    gp('numbers-the-customers-english-top-three-en-to-ru-accepted_false_blank', ACCEPTED, COVER_EN_TOP3_RU, 'ru',
       'В прошлом году я вошла в тройку лучших продавцов региона.', gone=('тройку',), translated=True,
       pair='numbers-three-years-grounds-no-top-three-ru-blank'),
    gp('numbers-the-customers-best-three-in-other-words-uz-accepted_false_blank', ACCEPTED, COVER_UZ_THREE_BEST, 'uz',
       'O‘tgan yili viloyatda eng yaxshi uchlikka kirdim.', gone=('uchlik',),
       pair='numbers-three-years-grounds-no-top-three-uz-blank'),
]

# ---- A translated paper's accounting law takes only its head noun's own forms (must, from 424c38a): "учёт", "учёта",
# "учёте" and "hisob", "hisobi", "hisobiga" are the name of the customer's Law on Accounting; a word built on the stem
# ("hisobotlari", "hisobchilari", "hisobvaraqlari", "учётчиках", "учётности") names another law. Round 8 removed the
# head noun's exemption: the head is the customer's word, as in c491da9, and the keeps are accepted false blanks.
ACCOUNTING_EN_UZ = 'Write a job description for an accountant in Uzbek. He must know the Law on Accounting.'
ACCOUNTING_EN_RU = 'Write a job description for an accountant in Russian. He must know the Law on Accounting.'
ACCOUNTING_UZ_RU = ('Buxgalter uchun rus tilida lavozim yo‘riqnomasi yozing. U Buxgalteriya hisobi to‘g‘risidagi '
                    'qonunni bilishi kerak.')
for slug, brief, locale, sentence, gone in (
        ('hisobotlari-en-to-uz', ACCOUNTING_EN_UZ, 'uz',
         'Buxgalter Buxgalteriya hisobotlari to‘g‘risidagi qonunni biladi.', ('hisobotlari',)),
        ('hisobchilari-en-to-uz', ACCOUNTING_EN_UZ, 'uz',
         'Buxgalter Buxgalteriya hisobchilari to‘g‘risidagi qonunga amal qiladi.', ('hisobchilari',)),
        ('hisobvaraqlari-en-to-uz', ACCOUNTING_EN_UZ, 'uz',
         'Buxgalter Buxgalteriya hisobvaraqlari to‘g‘risidagi qonunni biladi.', ('hisobvaraqlari',)),
        ('lower-case-hisoboti-en-to-uz', ACCOUNTING_EN_UZ, 'uz',
         'Buxgalter buxgalteriya hisoboti to‘g‘risidagi qonunni biladi.', ('hisoboti',)),
        ('uchetchikah-en-to-ru', ACCOUNTING_EN_RU, 'ru', 'Бухгалтер соблюдает Закон о бухгалтерских учётчиках.',
         ('учётчиках',)),
        ('uchetnosti-en-to-ru', ACCOUNTING_EN_RU, 'ru', 'Бухгалтер соблюдает Закон о бухгалтерской учётности.',
         ('учётности',)),
        ('uchetchikah-uz-to-ru', ACCOUNTING_UZ_RU, 'ru', 'Бухгалтер соблюдает Закон о бухгалтерских учётчиках.',
         ('учётчиках',)),
        ('uchetnosti-uz-to-ru', ACCOUNTING_UZ_RU, 'ru', 'Бухгалтер соблюдает Закон о бухгалтерской учётности.',
         ('учётности',))):
    CASES += [
        guard(f'laws-an-accounting-law-head-stem-{slug}-blank', BLANK, brief, locale, sentence, gone=gone,
              translated=True),
        body(f'laws-an-accounting-law-head-stem-in-a-qualification-{slug}-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi',
             brief, locale, 'qualification', sentence, gone=gone),
    ]
CASES += [
    guard('laws-the-customers-law-on-accounting-as-hisobi-en-to-uz-keep', KEEP, ACCOUNTING_EN_UZ, 'uz',
          'Buxgalter Buxgalteriya hisobi to‘g‘risidagi qonunni biladi.', translated=True),
    guard('laws-the-customers-law-on-accounting-as-uchete-en-to-ru-keep', KEEP, ACCOUNTING_EN_RU, 'ru',
          'Бухгалтер соблюдает Закон о бухгалтерском учёте.', translated=True),
    guard('laws-the-customers-law-on-accounting-as-uchete-uz-to-ru-keep', KEEP, ACCOUNTING_UZ_RU, 'ru',
          'Бухгалтер руководствуется Законом о бухгалтерском учёте.', translated=True),
]

# ---------------------------------------------------------------- the re-check of round 6 (drop-r2), both ways
# Round 6 left two readings that kept what c491da9 blanks: the customer's placing in a form only this branch reads gave
# its bare figure, and a translated paper's accounting law exempted its head noun with an unread tail after it.

# ---- The customer's placing in a form c491da9 never read gives a key of its own (must, from 21147ba, 3167c90 and
# fdea722): "U olimpiadada birinchi bo‘ldi", "I was first in sales", "Она стала третьей" ground the paper's placing,
# never its "1 yil", "1-sinf", "1%", "grade 1" or "3 года". Being first at an olympiad is no year of experience.
PLACING_LETTERS = {'ru': 'Напишите рекомендательное письмо для ученицы Малики Кодировой. ',
                   'en': 'Please write a recommendation letter for my student Malika Qodirova. ',
                   'uz': 'O‘quvchim Qodirova Malika uchun tavsiyanoma yozing. '}
PLACING_FIGURES = {
    'ru': (('a-year-of-experience', 'Опыт работы — {n} год.'), ('a-class', 'Она учится в {n} классе.'),
           ('a-percent', 'Продажи выросли на {n}%.'), ('a-club', 'Она открыла {n} кружок.')),
    'en': (('a-year-of-experience', 'I have {n} year of experience.'), ('a-branch', 'We opened {n} new branch.'),
           ('a-percent', 'Sales grew by {n}%.'), ('a-grade', 'She is in grade {n}.')),
    'uz': (('a-year', 'U {n} yil to‘garakka qatnashgan.'), ('a-class', 'U {n}-sinfda o‘qiydi.'),
           ('a-percent', 'Savdo {n}% ga oshdi.'), ('branches', 'Kompaniya {n} ta filial ochdi.')),
}
for locale, slug, said, figure in (
        ('ru', 'became-first-in-the-region', 'Он стал первым в регионе по продажам.', '1'),
        ('ru', 'became-first-at-an-olympiad', 'Она стала первой на городской олимпиаде.', '1'),
        ('ru', 'first-in-a-class-ranking', 'Она первая в рейтинге класса.', '1'),
        ('ru', 'first-pupil-after-a-dash', 'Она — первая ученица школы по итогам олимпиады.', '1'),
        ('ru', 'first-degree-diploma', 'Она получила диплом первой степени.', '1'),
        ('ru', 'first-line-of-a-ranking', 'Она заняла первую строчку рейтинга.', '1'),
        ('ru', 'first-place-by-region', 'Она была на первом месте по региону.', '1'),
        ('ru', 'first-place-by-sales-volume', 'Она была на первом месте по объёму продаж.', '1'),
        ('ru', 'turned-out-first', 'Она оказалась первой среди участников олимпиады.', '1'),
        ('ru', 'finished-with-third-place', 'Она закончила олимпиаду с третьим местом.', '3'),
        ('ru', 'became-third', 'Она стала третьей на олимпиаде.', '3'),
        ('ru', 'became-fifth', 'Он стал пятым в рейтинге школы.', '5'),
        ('ru', 'held-third-position', 'Она занимала третьей позицией в рейтинге.', '3'),
        ('en', 'first-in-sales', 'I was first in sales last year.', '1'),
        ('en', 'was-first-at-an-olympiad', 'At the regional olympiad she was first.', '1'),
        ('en', 'took-first-at-an-olympiad', 'She took first at the city olympiad.', '1'),
        ('en', 'first-in-a-ranking', 'She was first in the regional ranking.', '1'),
        ('en', 'finished-in-first', 'She finished the olympiad in first.', '1'),
        ('en', 'first-degree-diploma', 'She received a first-degree diploma.', '1'),
        ('en', 'diploma-of-the-first-degree', 'She got a diploma of the first degree.', '1'),
        ('en', 'first-runner-up', 'She was named first runner-up.', '1'),
        ('en', 'first-best-student', 'She was the first-best student in the olympiad.', '1'),
        ('en', 'came-out-first-among', 'She came out first among the olympiad participants.', '1'),
        ('uz', 'became-first-at-an-olympiad', 'U olimpiadada birinchi bo‘ldi.', '1'),
        ('uz', 'was-first-with-edi', 'Viloyat olimpiadasida u birinchi edi.', '1'),
        ('uz', 'showed-the-first-result', 'Olimpiadada birinchi natijani ko‘rsatdi.', '1'),
        ('uz', 'rose-to-the-first-step', 'Musobaqada birinchi pog‘onaga ko‘tarildi.', '1'),
        ('uz', 'first-degree-diploma', 'U birinchi darajali diplom oldi.', '1'),
        ('uz', 'first-with-bolib-and-a-medal', 'Musobaqada birinchi bo‘lib, oltin medal oldi.', '1'),
        ('uz', 'won-the-first-ness', 'U tanlovda birinchilikni qo‘lga kiritdi.', '1'),
        ('uz', 'first-by-sales', 'Sotuv bo‘yicha birinchi o‘rinda.', '1'),
        ('uz', 'first-by-trade-volume', 'Savdo hajmi bo‘yicha birinchi o‘ringa chiqdi.', '1'),
        ('uz', 'had-been-first', 'Tanlovda birinchi bo‘lgan.', '1')):
    for row_slug, sentence in PLACING_FIGURES[locale]:
        CASES.append(gp(f'numbers-the-customers-placing-{slug}-grounds-no-{row_slug}-{locale}-blank', BLANK,
                        PLACING_LETTERS[locale] + said, locale, sentence.format(n=figure), gone=(figure,)))
for locale, slug, said, sentence, figure in (
        ('ru', 'finished-with-third-place', 'Она закончила олимпиаду с третьим местом.', 'Опыт работы — 3 года.', '3'),
        ('en', 'first-in-sales', 'I was first in sales last year.', 'I have 1 year of experience.', '1'),
        ('uz', 'became-first-at-an-olympiad', 'U olimpiadada birinchi bo‘ldi.', 'U 1 yil to‘garakka qatnashgan.', '1')):
    CASES.append(body(f'numbers-the-customers-placing-{slug}-grounds-no-figure-in-a-references-achievements-{locale}'
                      '-blank', BLANK, 'pdf.xat.tavsifnoma', PLACING_LETTERS[locale] + said, locale, 'achievements',
                      sentence, gone=(figure,)))
    if locale != 'ru':
        CASES.append(fact(f'numbers-the-customers-placing-{slug}-grounds-no-figure-in-a-references-role-{locale}-blank',
                          BLANK, 'pdf.xat.tavsifnoma', PLACING_LETTERS[locale] + said, locale, 'subject_role',
                          sentence, gone=(figure,)))
# The customer's placing still grounds the paper's, restated in their words or in another placing's.
CASES += [
    gp('numbers-the-customers-placing-became-first-restated-uz-keep', KEEP,
       PLACING_LETTERS['uz'] + 'U olimpiadada birinchi bo‘ldi.', 'uz', 'U olimpiadada birinchi bo‘ldi.'),
    gp('numbers-the-customers-placing-became-first-as-first-place-uz-keep', KEEP,
       PLACING_LETTERS['uz'] + 'U olimpiadada birinchi bo‘ldi.', 'uz', 'U olimpiadada birinchi o‘rinni egalladi.'),
    body('numbers-the-customers-placing-became-first-in-a-references-achievements-uz-keep', KEEP, 'pdf.xat.tavsifnoma',
         PLACING_LETTERS['uz'] + 'U olimpiadada birinchi bo‘ldi.', 'uz', 'achievements',
         'U olimpiadada birinchi bo‘ldi.'),
    gp('numbers-the-customers-placing-won-the-first-ness-restated-uz-keep', KEEP,
       PLACING_LETTERS['uz'] + 'U tanlovda birinchilikni qo‘lga kiritdi.', 'uz',
       'U tanlovda birinchilikni qo‘lga kiritdi.'),
    gp('numbers-the-customers-placing-first-degree-diploma-restated-uz-keep', KEEP,
       PLACING_LETTERS['uz'] + 'U birinchi darajali diplom oldi.', 'uz', 'U birinchi darajali diplom oldi.'),
    gp('numbers-the-customers-placing-first-in-sales-restated-en-keep', KEEP,
       PLACING_LETTERS['en'] + 'I was first in sales last year.', 'en', 'Last year I was first in sales.'),
    gp('numbers-the-customers-placing-took-first-at-an-olympiad-as-first-place-en-keep', KEEP,
       PLACING_LETTERS['en'] + 'She took first at the city olympiad.', 'en',
       'She won first place at the city olympiad.'),
    gp('numbers-the-customers-placing-first-degree-diploma-restated-en-keep', KEEP,
       PLACING_LETTERS['en'] + 'She received a first-degree diploma.', 'en', 'She received a first-degree diploma.'),
    gp('numbers-the-customers-placing-became-third-restated-ru-keep', KEEP,
       PLACING_LETTERS['ru'] + 'Она стала третьей на олимпиаде.', 'ru', 'Она стала третьей на олимпиаде.'),
    gp('numbers-the-customers-placing-became-third-as-third-place-ru-keep', KEEP,
       PLACING_LETTERS['ru'] + 'Она стала третьей на олимпиаде.', 'ru', 'Она заняла третье место на олимпиаде.'),
    gp('numbers-the-customers-placing-finished-with-third-place-as-third-place-ru-keep', KEEP,
       PLACING_LETTERS['ru'] + 'Она закончила олимпиаду с третьим местом.', 'ru',
       'Она заняла третье место на олимпиаде.'),
    gp('numbers-the-customers-placing-became-first-ru-to-uz-keep', KEEP,
       'Напишите характеристику на узбекском для Малики Кодировой, она стала первой на олимпиаде.', 'uz',
       'U olimpiadada birinchi bo‘ldi.'),
    # A placing c491da9 read gives its figure as there: the customer's "1-o‘rinni egallagan" grounds "birinchi
    # bo‘ldi", and their "first place" the paper's "1st place".
    gp('numbers-the-customers-digit-placing-as-became-first-uz-keep', KEEP,
       'Qodirova Malika uchun tavsifnoma yozing, u olimpiadada 1-o‘rinni egallagan.', 'uz',
       'U olimpiadada birinchi bo‘ldi.'),
    gp('numbers-the-customers-first-place-as-a-digit-placing-en-keep', KEEP,
       PLACING_LETTERS['en'] + 'She won first place at the city olympiad.', 'en',
       'She won 1st place at the city olympiad.'),
]
# No ordinal written in Uzbek Cyrillic is read, on either side: the customer's "биринчи бўлди" or "биринчи даражали
# диплом" grounds no placing, so the paper's "birinchi bo‘ldi" and "birinchi darajali diplom" blank under their brief.
# c491da9 reads neither paper form and keeps them, as it keeps them invented: the blanks are the price of the pairs.
REFERENCE_UZC_FIRST = 'Қодирова Малика учун тавсифнома ёзинг, у олимпиадада биринчи бўлди.'
REFERENCE_UZC_DIPLOMA = 'Қодирова Малика учун тавсифнома ёзинг, у биринчи даражали диплом олган.'
CASES += [
    gp('numbers-first-with-boldi-beside-an-olympiad-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'U olimpiadada birinchi bo‘ldi.', gone=('birinchi',)),
    gp('numbers-first-degree-diploma-with-darajali-uz-blank', BLANK, REFERENCE_UZ, 'uz',
       'U birinchi darajali diplom olgan.', gone=('birinchi',)),
    gp('numbers-the-customers-cyrillic-placing-became-first-uz-accepted_false_blank', ACCEPTED, REFERENCE_UZC_FIRST,
       'uz', 'U olimpiadada birinchi bo‘ldi.', gone=('birinchi',),
       pair='numbers-first-with-boldi-beside-an-olympiad-uz-blank'),
    body('numbers-the-customers-cyrillic-placing-became-first-in-a-references-achievements-uz-accepted_false_blank',
         ACCEPTED, 'pdf.xat.tavsifnoma', REFERENCE_UZC_FIRST, 'uz', 'achievements', 'U olimpiadada birinchi bo‘ldi.',
         gone=('birinchi',), pair='numbers-first-with-boldi-beside-an-olympiad-uz-blank'),
    gp('numbers-the-customers-cyrillic-first-degree-diploma-uz-accepted_false_blank', ACCEPTED, REFERENCE_UZC_DIPLOMA,
       'uz', 'U birinchi darajali diplom olgan.', gone=('birinchi',),
       pair='numbers-first-degree-diploma-with-darajali-uz-blank'),
    body('numbers-the-customers-cyrillic-first-degree-diploma-in-a-references-achievements-uz-accepted_false_blank',
         ACCEPTED, 'pdf.xat.tavsifnoma', REFERENCE_UZC_DIPLOMA, 'uz', 'achievements',
         'U birinchi darajali diplom olgan.', gone=('birinchi',),
         pair='numbers-first-degree-diploma-with-darajali-uz-blank'),
]
# An English paper reads a Latin word against the Uzbek lexicon only whole (8bb7198), so an Uzbek sentence's inflected
# first word ("Olimpiadada", "Reytingda", "Musobaqada") blanks as a name, as "Bogdan" (bog+dan) must: the re-check's
# Uzbek placings in an English paper (r2) showed it. c491da9 keeps the word, as it keeps "Bogdan".
COVER_EN_FIGURES = ('Please write a cover letter for me, Malika Qodirova. I have 1 year of retail experience, '
                    '2 certificates and 3 languages.')
for word, sentence in (('Olimpiadada', 'Olimpiadada uchinchi natijani qayd etdi.'),
                       ('Reytingda', 'Reytingda ikkinchi pog‘onani egalladi.'),
                       ('Musobaqada', 'Musobaqada uchinchi bo‘lib, bronza medal oldi.')):
    CASES.append(gp(f'names-an-inflected-uzbek-word-opening-an-english-sentence-{word.lower()}-en-accepted_false_blank',
                    ACCEPTED, COVER_EN_FIGURES, 'en', sentence, gone=(word,),
                    pair='names-uzbek-lexicon-given-name-bogdan-ru-to-en-blank'))

# ---- A translated paper's accounting law exempts its head noun only where its name ends there (must, from 424c38a
# and 0bdb620): "... о бухгалтерском учёте." or "... учёте» регулирует ...". After "и", a comma or a preposition
# ("... учёте и аудите", "... учёте, аудите и налогах", "... учёте в банках", "... учёте для банков") the name goes on
# past what `_law_names` reads, so the head is the customer's word or the sentence goes, as in c491da9. Round 8
# removed the exemption everywhere: these blanks stand, the keeps after them are accepted false blanks (`PAID`).
for slug, sentence, gone in (
        ('and-audit', 'Бухгалтер соблюдает Закон о бухгалтерском учёте и аудите.', ('аудите',)),
        ('in-banks', 'Бухгалтер соблюдает Закон о бухгалтерском учёте в банках.', ('банках',)),
        ('audit-and-taxes', 'Бухгалтер соблюдает Закон о бухгалтерском учёте, аудите и налогах.',
         ('аудите', 'налогах')),
        ('of-the-republic-and-audit', 'Бухгалтер соблюдает Закон Республики Узбекистан о бухгалтерском учёте и '
         'аудите.', ('аудите',)),
        ('for-banks', 'Бухгалтер соблюдает Закон о бухгалтерском учёте для банков.', ('банков',)),
        ('in-bankruptcy', 'Бухгалтер соблюдает Закон о бухгалтерском учёте при банкротстве.', ('банкротстве',)),
        ('reporting-and-audit', 'Бухгалтер соблюдает Закон о бухгалтерском учёте, отчётности и аудите.',
         ('отчётности', 'аудите')),
        ('and-auditing', 'Бухгалтер соблюдает Закон о бухгалтерском учёте и аудиторской деятельности.',
         ('аудиторской',)),
        ('and-financial-reporting', 'Бухгалтер обязан знать Закон о бухгалтерском учёте и финансовой отчётности.',
         ('финансовой',))):
    for brief, direction in ((ACCOUNTING_EN_RU, 'en-to-ru'), (ACCOUNTING_UZ_RU, 'uz-to-ru')):
        CASES += [
            guard(f'laws-an-accounting-law-head-before-{slug}-{direction}-blank', BLANK, brief, 'ru', sentence,
                  gone=gone, translated=True),
            body(f'laws-an-accounting-law-head-before-{slug}-in-a-qualification-{direction}-blank', BLANK,
                 'pdf.biz.lavozim_yoriqnomasi', brief, 'ru', 'qualification', sentence, gone=gone),
        ]
# The customer's law named alone stayed: its name ended at the head before the sentence's end, a verb or its date.
ACCOUNTING_EN_RU_DATED = ('Write a job description for an accountant in Russian. He must know the Law on Accounting '
                          'of 13 April 2016.')
CASES += [
    guard('laws-the-customers-law-on-accounting-before-a-verb-en-to-ru-keep', KEEP, ACCOUNTING_EN_RU, 'ru',
          'Бухгалтер знает, что Закон о бухгалтерском учёте устанавливает правила.', translated=True),
    guard('laws-the-customers-law-on-accounting-before-a-verb-uz-to-ru-keep', KEEP, ACCOUNTING_UZ_RU, 'ru',
          'Бухгалтер знает, что Закон о бухгалтерском учёте устанавливает правила.', translated=True),
    guard('laws-the-customers-law-on-accounting-before-its-date-en-to-ru-keep', KEEP, ACCOUNTING_EN_RU_DATED, 'ru',
          'Бухгалтер соблюдает Закон о бухгалтерском учёте от 13 апреля 2016 года.', translated=True),
]

# ---------------------------------------------------------------- the re-check of round 7 (parity-r1), both ways
# Round 7's targeted fixes still kept what c491da9 blanks, so parity with c491da9 is kept by construction (the owner's
# decision): the customer's numbers are c491da9's reading, a placing read since adding only its place key
# (numbers.values); a paper's number holds c491da9's reading of the same characters and needs what that needed
# (numbers.found); and the law-name readings the re-check found leaking read as c491da9 reads them. An unnamed law's
# name no longer ends where the sentence goes on (an -s verb, an -ed or -ly word, an adverb) nor at a possessive, and
# the accounting law's head noun ("учёте", "hisobi") is the customer's word in a translated paper too. Each leak is
# pinned here as a blank; each keep it costs is an accepted false blank (below) naming the blank it pays for.

# ---- A customer's sentence that is no placing, or a negated one, grounds no placing c491da9 reads (must, p1, p3):
# its place key ("place:1") never stands for the figure "first place" needs.
NOT_PLACINGS = (
    ('en', 'not-first-in-the-ranking', 'She was not first in the ranking, but she improved a lot.',
     'She won first place at the olympiad.', 'first'),
    ('en', 'first-in-her-class-to-qualify', 'She was first in her class to qualify for the regional olympiad.',
     'She won first place at the olympiad.', 'first'),
    ('ru', 'did-not-become-first', 'Она не стала первой на олимпиаде.', 'На олимпиаде она заняла первое место.',
     'первое'),
    ('ru', 'first-olympiad-of-her-life', 'Эта олимпиада была первой в её жизни.',
     'На олимпиаде она заняла первое место.', 'первое'),
    ('ru', 'third-olympiad-of-her-life', 'Эта олимпиада стала третьей в её жизни.',
     'На олимпиаде она заняла третье место.', 'третье'),
    ('ru', 'first-of-her-class-through-to-the-olympiad', 'Она первой из класса прошла на олимпиаду.',
     'На олимпиаде она заняла первое место.', 'первое'),
    ('uz', 'contest-was-her-first', 'Bu tanlov u uchun birinchi edi.', 'U olimpiadada birinchi o‘rinni egalladi.',
     'birinchi'),
    ('uz', 'could-not-reach-the-first-step', 'U olimpiadada birinchi pog‘onaga chiqa olmadi.',
     'U olimpiadada birinchi o‘rinni egalladi.', 'birinchi'),
    ('uz', 'lost-the-first-ness', 'U tanlovda birinchilikni raqibiga boy berdi.',
     'U olimpiadada birinchi o‘rinni egalladi.', 'birinchi'),
    ('uz', 'registered-first', 'Musobaqada birinchi bo‘lib, ro‘yxatdan o‘tdi.',
     'U olimpiadada birinchi o‘rinni egalladi.', 'birinchi'))
for locale, slug, said, sentence, word in NOT_PLACINGS:
    CASES += [
        gp(f'numbers-a-customers-non-placing-{slug}-grounds-no-placing-{locale}-blank', BLANK,
           PLACING_LETTERS[locale] + said, locale, sentence, gone=(word,)),
        body(f'numbers-a-customers-non-placing-{slug}-grounds-no-placing-in-a-references-achievements-{locale}-blank',
             BLANK, 'pdf.xat.tavsifnoma', PLACING_LETTERS[locale] + said, locale, 'achievements', sentence,
             gone=(word,)),
    ]
CASES += [
    gp('numbers-a-customers-non-placing-first-olympiad-of-her-life-grounds-no-placing-ru-to-uz-blank', BLANK,
       'Напишите характеристику на узбекском для Малики Кодировой. Эта олимпиада была первой в её жизни.', 'uz',
       'U olimpiadada birinchi o‘rinni egalladi.', gone=('birinchi',)),
    gp('numbers-a-customers-non-placing-contest-was-her-first-grounds-no-placing-uz-to-en-blank', BLANK,
       'Malika Qodirova uchun ingliz tilida tavsifnoma yozing. Bu tanlov u uchun birinchi edi.', 'en',
       'She won first place at the olympiad.', gone=('first',)),
]

# ---- The accounting law's head noun is the customer's word when they never named the law (must, p2): their
# "бухгалтерской службы", "accounting" or "Buxgalteriya bo‘limi" and their "laws" name no Law on Accounting.
UNNAMED_ACCOUNTING = (
    ('ru', 'Составьте должностную инструкцию сотрудника бухгалтерской службы. Он должен соблюдать законы.'),
    ('en-to-ru', 'Write a job description in Russian for an accounting assistant. He must obey the law.'),
    ('uz-to-ru', 'Buxgalteriya bo‘limi xodimi uchun rus tilida lavozim yo‘riqnomasi yozing. U qonunlarga qat’iy rioya '
                 'qilishi kerak.'))
for direction, brief in UNNAMED_ACCOUNTING:
    CASES += [
        guard(f'laws-an-unnamed-accounting-law-as-uchete-{direction}-blank', BLANK, brief, 'ru',
              'Сотрудник соблюдает Закон о бухгалтерском учёте.', gone=('учёте',)),
        guard(f'laws-an-unnamed-accounting-law-in-the-instrumental-{direction}-blank', BLANK, brief, 'ru',
              'Сотрудник руководствуется Законом о бухгалтерском учёте.', gone=('учёте',)),
        guard(f'laws-an-unnamed-accounting-law-in-lower-case-{direction}-blank', BLANK, brief, 'ru',
              'Сотрудник руководствуется законом о бухгалтерском учёте.', gone=('учёте',)),
        body(f'laws-an-unnamed-accounting-law-as-uchete-in-a-qualification-{direction}-blank', BLANK,
             'pdf.biz.lavozim_yoriqnomasi', brief, 'ru', 'qualification',
             'Сотрудник соблюдает Закон о бухгалтерском учёте.', gone=('учёте',)),
    ]
for direction, brief in (
        ('uz', 'Buxgalteriya bo‘limi xodimi uchun lavozim yo‘riqnomasi yozing. U qonunlarga qat’iy rioya qilishi '
               'kerak.'),
        ('en-to-uz', 'Write a job description in Uzbek for an accounting assistant. He must obey the law.'),
        ('ru-to-uz', 'Составьте должностную инструкцию на узбекском для сотрудника бухгалтерской службы. Он должен '
                     'соблюдать законы.')):
    CASES.append(guard(f'laws-an-unnamed-accounting-law-as-hisobi-{direction}-blank', BLANK, brief, 'uz',
                       'Xodim Buxgalteriya hisobi to‘g‘risidagi qonunga amal qiladi.', gone=('hisobi',)))

# ---- An unnamed law's name goes on past an -ed or -ly modifier and an -s word that is also a verb (must, p5, p7,
# p10): every word after its "on" is the customer's, as c491da9 reads it.
TAX_LAW_EN = 'Write a job description for an accountant. He must know the Tax Code and the Law on taxes.'
STATE_DUTY_EN = 'Write a short report for a school. Mention the Law on state duty.'
FAMILY_LAW_EN = 'Write an independent study paper on the Family Code and the Law on the family.'
CASES += [
    guard('laws-an-invented-tail-after-the-customers-law-on-taxes-related-offences-en-blank', BLANK, TAX_LAW_EN, 'en',
          'He follows the Law on tax related offences.', gone=('offences',)),
    body('laws-an-invented-tail-after-the-customers-law-on-taxes-related-offences-in-a-qualification-en-blank', BLANK,
         'pdf.biz.lavozim_yoriqnomasi', TAX_LAW_EN, 'en', 'qualification',
         'He follows the Law on tax related offences. He checks invoices daily.', gone=('offences',)),
    guard('laws-an-invented-tail-after-the-customers-law-on-state-duty-funded-schools-en-blank', BLANK, STATE_DUTY_EN,
          'en', 'Schools follow the Law on state funded schools.', gone=('funded',)),
    guard('laws-an-invented-tail-after-the-customers-law-on-state-duty-owned-enterprises-en-blank', BLANK,
          STATE_DUTY_EN, 'en', 'Schools follow the Law on state owned enterprises.', gone=('enterprises',)),
    guard('laws-an-invented-tail-after-the-customers-law-on-state-duty-guaranteed-loans-en-blank', BLANK,
          STATE_DUTY_EN, 'en', 'He follows the Law on state guaranteed loans.', gone=('loans',)),
    guard('laws-an-invented-tail-after-the-customers-law-on-the-family-friendly-workplaces-en-blank', BLANK,
          FAMILY_LAW_EN, 'en', 'Parents follow the Law on family friendly workplaces.', gone=('workplaces',)),
    guard('laws-an-invented-tail-after-the-customers-law-on-the-family-owned-businesses-en-blank', BLANK,
          FAMILY_LAW_EN, 'en', 'Owners follow the Law on family owned businesses.', gone=('businesses',)),
    guard('laws-an-invented-tail-after-the-customers-law-on-education-grants-en-blank', BLANK, EDU_EN, 'en',
          'Students apply under the Law on Education grants for students.', gone=('grants',)),
    guard('laws-an-invented-tail-after-the-customers-law-on-education-related-offences-en-blank', BLANK, EDU_EN, 'en',
          'Teachers follow the Law on education related offences.', gone=('offences',)),
    guard('laws-an-invented-tail-after-the-customers-law-on-education-supports-en-blank', BLANK, EDU_EN, 'en',
          'Schools follow the Law on Education supports for disabled pupils.', gone=('supports',)),
    # The same in lower case, which c491da9 never read as a citation: this branch does (`_lower_cited`).
    guard('laws-an-invented-tail-after-the-customers-lower-case-law-on-education-grants-en-blank', BLANK, EDU_EN, 'en',
          'Students apply under the law on education grants for students.', gone=('grants',)),
    guard('laws-an-invented-tail-after-the-customers-lower-case-law-on-education-related-offences-en-blank', BLANK,
          EDU_EN, 'en', 'Teachers follow the law on education related offences.', gone=('offences',)),
    guard('laws-an-invented-tail-after-the-customers-lower-case-law-on-the-family-friendly-workplaces-en-blank',
          BLANK, FAMILY_LAW_EN, 'en', 'Parents follow the law on family friendly workplaces.', gone=('workplaces',)),
]

# ---- A LAW_NAMES word's possessive no longer ends the name (should, p9): the part after it is the customer's words.
for direction, brief in (('en', ACCOUNTING_EN), ('ru-to-en', JOB_RU_EN_LAW), ('uz-to-en', ACCOUNTING_UZ_EN)):
    CASES.append(guard(f'laws-an-invented-part-after-the-law-on-accountings-possessive-{direction}-blank', BLANK,
                       brief, 'en', 'He follows the Law on Accounting’s banking supplement.', gone=('banking',)))
for direction, brief in (('en', EDU_EN), ('ru-to-en', EDU_RU_EN)):
    CASES.append(guard(f'laws-an-invented-part-after-the-law-on-educations-possessive-{direction}-blank', BLANK,
                       brief, 'en', 'He follows the Law on Education’s vocational annex.', gone=('vocational',)))

# ---- The keeps these readings cost: each is an accepted false blank naming the leak it pays for, and keeps its id
# under the customer's own words (`removed`). The lower-case laws c491da9 never read as citations (it keeps every one
# of them, invented or not) are new false blanks; the rest c491da9 blanks too.
GOES_ON_S = 'laws-an-invented-tail-after-the-customers-law-on-education-grants-en-blank'
GOES_ON_S_LOWER = 'laws-an-invented-tail-after-the-customers-lower-case-law-on-education-grants-en-blank'
GOES_ON_ED = 'laws-an-invented-tail-after-the-customers-law-on-taxes-related-offences-en-blank'
GOES_ON_LY = 'laws-an-invented-tail-after-the-customers-law-on-the-family-friendly-workplaces-en-blank'
GOES_ON_LY_LOWER = 'laws-an-invented-tail-after-the-customers-lower-case-law-on-the-family-friendly-workplaces-en-blank'
PAID = {
    'laws-the-customers-law-on-education-in-lower-case-before-a-verb-en-keep': (('guarantees',), GOES_ON_S),
    'laws-the-customers-consumer-rights-law-before-a-verb-ru-to-en-keep': (('protects',), GOES_ON_S),
    'laws-the-customers-law-of-the-republic-before-a-verb-en-keep': (('guarantees',), GOES_ON_S),
    'laws-the-customers-law-on-accounting-before-well-en-keep': (('well',), GOES_ON_LY),
    'laws-the-customers-law-on-accounting-before-well-ru-to-en-keep': (('well',), GOES_ON_LY),
    'laws-the-customers-law-on-accounting-before-daily-en-keep': (('daily',), GOES_ON_LY),
    'laws-the-customers-law-on-accounting-before-together-en-keep': (('together',), GOES_ON_LY),
    'laws-the-customers-law-of-the-republic-before-an-adverb-en-keep': (('carefully',), GOES_ON_LY),
    'laws-the-customers-law-on-accounting-possessive-en-keep': (('rules',),
                                                                'laws-an-invented-part-after-the-law-on-accountings'
                                                                '-possessive-en-blank'),
    'laws-the-customers-law-on-accounting-possessive-ru-to-en-keep': (('rules',),
                                                                      'laws-an-invented-part-after-the-law-on'
                                                                      '-accountings-possessive-ru-to-en-blank'),
    'laws-the-customers-law-on-accounting-possessive-uz-to-en-keep': (('rules',),
                                                                      'laws-an-invented-part-after-the-law-on'
                                                                      '-accountings-possessive-uz-to-en-blank'),
    'laws-the-customers-law-on-education-possessive-en-keep': (('aim',),
                                                               'laws-an-invented-part-after-the-law-on-educations'
                                                               '-possessive-en-blank'),
    'laws-the-customers-law-on-accounting-as-hisobi-en-to-uz-keep': (('hisobi',),
                                                                     'laws-an-unnamed-accounting-law-as-hisobi-en-to'
                                                                     '-uz-blank'),
    'laws-the-customers-law-on-accounting-as-uchete-en-to-ru-keep': (('учёте',),
                                                                     'laws-an-unnamed-accounting-law-as-uchete-en-to'
                                                                     '-ru-blank'),
    'laws-the-customers-law-on-accounting-as-uchete-uz-to-ru-keep': (('учёте',),
                                                                     'laws-an-unnamed-accounting-law-in-the'
                                                                     '-instrumental-uz-to-ru-blank'),
    'laws-the-customers-law-on-accounting-before-a-verb-en-to-ru-keep': (('учёте',),
                                                                         'laws-an-accounting-law-head-before-and-audit'
                                                                         '-en-to-ru-blank'),
    'laws-the-customers-law-on-accounting-before-a-verb-uz-to-ru-keep': (('учёте',),
                                                                         'laws-an-accounting-law-head-before-and-audit'
                                                                         '-uz-to-ru-blank'),
    'laws-the-customers-law-on-accounting-before-its-date-en-to-ru-keep': (('учёте',),
                                                                           'laws-an-accounting-law-head-before-and'
                                                                           '-audit-en-to-ru-blank'),
    'laws-the-customers-uzbek-law-as-zakon-o-in-lower-case-uz-to-ru-keep': (('учёте',),
                                                                            'laws-an-unnamed-accounting-law-in-lower'
                                                                            '-case-uz-to-ru-blank'),
    'laws-the-customers-english-law-as-zakon-o-in-lower-case-en-to-ru-keep': (('учёте',),
                                                                              'laws-an-unnamed-accounting-law-in-lower'
                                                                              '-case-en-to-ru-blank'),
    'numbers-the-customers-placing-became-first-as-first-place-uz-keep': (
        ('birinchi',), 'numbers-a-customers-non-placing-contest-was-her-first-grounds-no-placing-uz-blank'),
    'numbers-the-customers-placing-took-first-at-an-olympiad-as-first-place-en-keep': (
        ('first',), 'numbers-a-customers-non-placing-first-in-her-class-to-qualify-grounds-no-placing-en-blank'),
    'numbers-the-customers-placing-became-third-as-third-place-ru-keep': (
        ('третье',), 'numbers-a-customers-non-placing-third-olympiad-of-her-life-grounds-no-placing-ru-blank'),
    'numbers-the-customers-placing-finished-with-third-place-as-third-place-ru-keep': (
        ('третье',), 'numbers-a-customers-non-placing-third-olympiad-of-her-life-grounds-no-placing-ru-blank'),
}
for verb in ('guarantees', 'defines', 'establishes', 'became', 'plays', 'contains'):
    for direction in ('en', 'uz-to-en'):
        PAID[f'laws-the-customers-law-on-education-{verb}-{direction}-keep'] = (
            (verb,), GOES_ON_ED if verb == 'became' else GOES_ON_S)
for word in ('thus', 'aims', 'seeks', 'itself', 'therefore', 'however'):
    for direction in ('en', 'ru-to-en'):
        PAID[f'laws-the-customers-lower-case-law-on-education-{word}-{direction}-keep'] = (
            (word,), GOES_ON_S_LOWER if word in ('aims', 'seeks') else GOES_ON_LY_LOWER)
for verb in ('ensures', 'lists', 'consists', 'implements', 'mentions'):
    for direction in ('en', 'ru-to-en', 'uz-to-en'):
        PAID[f'laws-the-customers-title-law-on-education-{verb}-{direction}-keep'] = ((verb,), GOES_ON_S)
        PAID[f'laws-the-customers-lower-law-on-education-{verb}-{direction}-keep'] = ((verb,), GOES_ON_S_LOWER)
    PAID[f'laws-the-customers-law-on-education-{verb}-uz-cyrillic-to-en-keep'] = ((verb,), GOES_ON_S)
for verb in ('secures', 'upholds', 'reinforces', 'affirms', 'motivates', 'equips', 'balances', 'functions', 'exists',
             'measures', 'features', 'assists'):
    PAID[f'laws-the-customers-law-on-education-{verb}-en-keep'] = ((verb,), GOES_ON_S)
    PAID[f'laws-the-customers-lower-case-law-on-education-{verb}-ru-to-en-keep'] = ((verb,), GOES_ON_S_LOWER)
for verb in ('ensures', 'consists', 'secures', 'insists'):
    for direction in ('en', 'ru-to-en', 'uz-to-en'):
        PAID[f'laws-the-customers-law-on-accounting-{verb}-{direction}-keep'] = ((verb,), GOES_ON_S)
assert all(sum(case.id == keep for case in CASES) == 1 for keep in PAID), 'every paid keep is a case'


# ---- Round 10 (the keeps eb8b05c has, restored where no leak comes back): an unnamed law's name ends where the
# sentence goes on with a word and nothing of a name can follow it (`facts._goes_on`), and at a LAW_NAMES word's
# possessive before a part of the law that goes on with a verb (`facts._owns_part`: "The Law on Accounting’s rules
# apply ..."), so the customer's law before a verb, an adverb or its rules is theirs again, their own words under
# their own brief. The leaks the round-8 removal closed stay
# blank: a modifier before a noun ("tax related offences", "family friendly workplaces"), a verb's -s before a
# preposition or at the end ("grants for students"). Each restored keep's accepted id stays (the core list names it),
# with the same word before a comma, where a list may go on the name ("the Law on state funded, private and public
# schools"): the tie-break the restored reading keeps, paid for by the same blank.
# The same words where a name may go on after them stay the name's (must, restore-r10 r1): eb8b05c ended the name
# at each of them.
for slug, brief, sentence, gone in (
        ('state-grants-at-the-end', STATE_DUTY_EN, 'He follows the Law on state grants.', ('grants',)),
        ('state-paid-leave', STATE_DUTY_EN, 'He follows the Law on state paid leave.', ('leave',)),
        ('state-funded-before-a-comma', STATE_DUTY_EN,
         'Schools follow the Law on state funded, private and public schools.', ('funded',)),
        ('education-grants-and-scholarships', EDU_EN, 'Schools follow the Law on Education grants and scholarships.',
         ('grants',)),
        ('education-grants-to-students', EDU_EN, 'Students apply under the Law on Education grants to students.',
         ('grants',)),
        ('education-funds-allocation', EDU_EN, 'Schools follow the Law on Education funds allocation.', ('funds',)),
        ('further-education', EDU_EN, 'He follows the Law on further education.', ('further',)),
        ('education-of-the-disabled', EDU_EN, 'Teachers follow the Law on Education of the disabled.', ('disabled',)),
        ('education-deprived-of', EDU_RU_EN, 'He follows the Law on Education deprived of funding.', ('deprived',)),
        ('family-friendly-measures', FAMILY_LAW_EN, 'Parents follow the Law on family friendly measures.',
         ('measures',)),
        ('accountings-rules-for-banks', ACCOUNTING_EN, 'He follows the Law on Accounting’s rules for banks.',
         ('banks',)),
        ('accountings-rules-and-annexes', ACCOUNTING_EN, 'He follows the Law on Accounting’s rules and annexes.',
         ('annexes',)),
        ('accountings-rules-before-a-comma', ACCOUNTING_EN,
         'He follows the Law on Accounting’s rules, standards and annexes.', ('standards',))):
    CASES.append(guard(f'laws-an-invented-tail-after-the-customers-law-{slug}-en-blank', BLANK, brief, 'en', sentence,
                       gone=gone))
# eb8b05c's keeps the narrowed reading keeps too: a verb's -s before "in force" or an object's determiner, an adverb
# before a clause's "and" and its verb.
CASES += [
    guard('laws-the-customers-law-on-education-remains-in-force-en-keep', KEEP, EDU_EN, 'en',
          'The Law on Education remains in force.'),
    # Round 11: "all" opens a relative clause's subject as often as a verb's object, so it is no sign of a verb any
    # more (`facts.LAW_OBJECT`): the keep is the customer's own words, the model's an accepted false blank.
    *removed(guard('laws-the-customers-law-on-education-protects-all-pupils-en-keep', KEEP, EDU_EN, 'en',
                   'The Law on Education protects all pupils.'), ('protects',),
             'laws-a-plural-noun-of-an-unnamed-law-grants-all-pupils-receive-en-blank', listed=True),
    guard('laws-the-customers-law-on-accounting-well-and-a-verb-en-keep', KEEP, ACCOUNTING_EN, 'en',
          'He knows the Law on Accounting well and applies it daily.'),
]
# The Uzbek head before an invented tail, as the Russian one (round 6): "... hisobi va audit to‘g‘risidagi qonun".
CASES.append(guard('laws-an-accounting-law-head-before-and-audit-en-to-uz-blank', BLANK, ACCOUNTING_EN_UZ, 'uz',
                   'Buxgalter Buxgalteriya hisobi va audit to‘g‘risidagi qonunga amal qiladi.', gone=('audit',),
                   translated=True))
# ---- The false blanks versus eb8b05c the sweep still shows (round 10), each the price of the blank it names: an -s
# whose base is no LAW_VERBS word before a noun ("funds allocation"), a verb's -s before a preposition not its own
# ("grants for students"), an adverb before a past form and a noun ("state funded schools"); c491da9's reading of a
# rejected line's name (N3, "Direktor Junior Smith") holding a unit's common word; the customer's placing in a form
# c491da9 never read giving its place key alone (L1).
REPORT_EN_ANNUAL = 'Write the annual report of our firm for 2025. Revenue grew to 3 billion soums.'
CASES += [
    guard('laws-the-customers-law-on-education-prioritises-en-accepted_false_blank', ACCEPTED, EDU_EN, 'en',
          'The Law on Education prioritises quality.', gone=('prioritises',),
          pair='laws-an-invented-tail-after-the-customers-law-education-funds-allocation-en-blank'),
    guard('laws-the-customers-law-on-education-deals-with-en-accepted_false_blank', ACCEPTED, EDU_EN, 'en',
          'The Law on Education deals with teacher training.', gone=('deals',),
          pair='laws-an-invented-tail-after-the-customers-law-on-education-grants-en-blank'),
    guard('laws-the-customers-law-on-education-fundamentally-changed-en-accepted_false_blank', ACCEPTED, EDU_EN, 'en',
          'The Law on Education fundamentally changed schools.', gone=('fundamentally',),
          pair='laws-an-invented-tail-after-the-customers-law-on-state-duty-funded-schools-en-blank'),
    body('names-a-rejected-units-common-word-opening-a-sentence-en-accepted_false_blank', ACCEPTED, 'pdf.biz.hisobot',
         REPORT_EN_ANNUAL, 'en', 'summary', 'Retail sales grew.', gone=('Retail',), facts=(('unit', 'Retail Network'),),
         pair='names-a-line-modifier-given-name-direktor-junior-opening-a-sentence-en-blank'),
    gp('numbers-the-customers-placing-became-first-as-a-digit-place-uz-accepted_false_blank', ACCEPTED,
       'Qodirova Malika uchun tavsifnoma yozing, u olimpiadada birinchi bo‘ldi.', 'uz',
       'U olimpiadada 1-o‘rinni egalladi.', gone=('1',),
       pair='numbers-a-customers-non-placing-contest-was-her-first-grounds-no-placing-uz-blank'),
]
# The Russian head before "и" and another law of the customer's ends the name there: "... учёте и налоговый кодекс".
ACCOUNTING_TAX_UZ_RU = ('Buxgalter uchun rus tilida lavozim yo‘riqnomasi yozing. U Buxgalteriya hisobi to‘g‘risidagi '
                        'qonunni va Soliq kodeksini bilishi kerak.')
CASES.append(guard('laws-the-customers-accounting-law-head-before-and-their-tax-code-uz-to-ru-keep', KEEP,
                   ACCOUNTING_TAX_UZ_RU, 'ru', 'Знает закон о бухгалтерском учёте и налоговый кодекс.', translated=True))
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU)):
    CASES.append(guard(f'laws-an-accounting-law-head-before-as-well-as-audit-{direction}-blank', BLANK, brief, 'ru',
                       'Бухгалтер руководствуется Законом о бухгалтерском учёте, а также аудите.', gone=('аудите',),
                       translated=True))
# The keeps restored, and the blank each one's accepted id now pays for: a word before a comma, where a list may go
# on the name (`_aside`); the Russian head before a preposition ("... учёте на практике", as "... учёте в банках");
# the Uzbek head before another word than "to‘g‘risidagi" ("... hisobi bo‘yicha Qonunni").
COMMA_AFTER = 'laws-an-invented-tail-after-the-customers-law-state-funded-before-a-comma-en-blank'
RESTORED = {keep: COMMA_AFTER for keep, (_, pair) in PAID.items()
            if pair in (GOES_ON_S, GOES_ON_S_LOWER, GOES_ON_ED, GOES_ON_LY, GOES_ON_LY_LOWER)}
RESTORED.update({keep: 'laws-an-invented-tail-after-the-customers-law-accountings-rules-before-a-comma-en-blank'
                 for keep, (_, pair) in PAID.items() if 'possessive' in pair})
RESTORED.update({keep: ('laws-an-accounting-law-head-before-and-audit-en-to-uz-blank' if keep.endswith('-to-uz-keep')
                        else 'laws-an-accounting-law-head-before-in-banks-'
                        + ('en' if keep.endswith('-en-to-ru-keep') else 'uz') + '-to-ru-blank')
                 for keep, (gone, _) in PAID.items() if gone in (('учёте',), ('hisobi',))})
ASIDE = {'en': ', in practice', 'ru': ' на практике'}


def _aside(value, word, locale):
    """`value` with an aside after the first `word`, before a comma: "The Law on Education guarantees, in practice,
    free schooling.", "He knows the Law on Accounting well, in practice."; the Russian head before a preposition:
    "... Законом о бухгалтерском учёте на практике."; the Uzbek head before "bo‘yicha" for its "to‘g‘risidagi": "...
    hisobi bo‘yicha Qonunni biladi." """
    if locale == 'uz':
        return value.replace(f'{word} to‘g‘risidagi qonun', f'{word} bo‘yicha Qonun')
    found = re.search(r'(?<![^\W_])' + re.escape(word) + r'(?![^\W_])', value)
    end = found.end()
    rest = value[end:]
    return value[:end] + ASIDE[locale] + ('' if rest in ('.', '') or locale == 'ru' else ',') + rest


def _paid(case):
    """A paid keep: the accepted false blank, and its id under the customer's own words. Those words, in the paper's
    language, may tell the brief's language otherwise, so the keep no longer asserts how it is read. A restored keep
    (`RESTORED`) is the keep as it was, and its accepted id the same word where the tie-break still holds (`_aside`),
    paid for by the blank `RESTORED` names."""
    gone, pair = PAID[case.id]
    if case.id in RESTORED:
        blank = replace(case, id=case.id.removesuffix('-' + KEEP) + '-' + ACCEPTED, direction=ACCEPTED,
                        value=_aside(case.value, gone[0], case.locale), gone=gone, pair=RESTORED[case.id])
        return [case, blank]
    keep, blank = removed(case, gone, pair, listed=True)
    return [replace(keep, translated=None), blank]


CASES = [made for case in CASES for made in (_paid(case) if case.id in PAID else [case])]

# ---------------------------------------------------------------- the re-check of round 8 (parity-r2), both ways
# Round 8 left three readings that keep what c491da9 blanks, each pinned here as blanks under the briefs the re-check
# used, with the keeps eb8b05c (in production) has for the same readings.

# ---- A sentence's opening word before a law's stem is the name's unless the name after "о", "об", "of" or "on" ends
# there (must, q1, q6, q7, q9): at the sentence's end, a verb or the law's date, or before a word that cannot go on it.
# An opening word dropped before "и", "and", a comma or a preposition let an invented tail through ("Соблюдает Закон о
# бухгалтерском учёте и аудите", "Under Law on Accounting and Auditing, ..."); c491da9 holds the word and blanks.
EDU_RU = 'Составьте должностную инструкцию учителя. Он должен знать Закон об образовании.'
for slug, brief, sentence, gone in (
        ('and-audit', JOB_RU_ACCOUNTING, 'Соблюдает Закон о бухгалтерском учёте и аудите.', ('аудите',)),
        ('in-banks', JOB_RU_ACCOUNTING, 'Соблюдает Закон о бухгалтерском учёте в банках.', ('банках',)),
        ('for-banks', JOB_RU_ACCOUNTING, 'Применяет Закон о бухгалтерском учёте для банков.', ('банков',)),
        ('audit-and-taxes', JOB_RU_ACCOUNTING, 'Знает Закон о бухгалтерском учёте, аудите и налогах.',
         ('аудите', 'налогах')),
        ('as-well-as-audit', JOB_RU_ACCOUNTING, 'Соблюдает Закон о бухгалтерском учёте, а также аудите.',
         ('аудите',)),
        ('in-bankruptcy', JOB_RU_ACCOUNTING, 'Руководствуется Законом о бухгалтерском учёте при банкротстве.',
         ('банкротстве',)),
        ('according-to-and-audit', JOB_RU_ACCOUNTING,
         'Согласно Закону о бухгалтерском учёте и аудите, бухгалтер ведёт книги.', ('аудите',)),
        ('knowledge-of-and-audit', JOB_RU_ACCOUNTING, 'Знание Закона о бухгалтерском учёте и аудите обязательно.',
         ('аудите',)),
        ('requirements-of-and-audit', JOB_RU_ACCOUNTING,
         'Требования Закона о бухгалтерском учёте и аудите соблюдаются.', ('аудите',)),
        ('having-studied-and-taxation', JOB_RU_ACCOUNTING,
         'Изучив Закон о бухгалтерском учёте и налогообложении, он составляет отчёты.', ('налогообложении',)),
        ('in-lower-case-and-audit', JOB_RU_ACCOUNTING, 'Знает закон о бухгалтерском учёте и аудите.', ('аудите',)),
        ('education-science-and-culture', EDU_RU, 'Соблюдает Закон об образовании, науке и культуре.',
         ('науке', 'культуре')),
        ('education-in-universities', EDU_RU, 'Знает Закон об образовании в вузах.', ('вузах',))):
    CASES += [
        guard(f'laws-an-opening-word-before-a-named-law-{slug}-ru-blank', BLANK, brief, 'ru', sentence, gone=gone,
              translated=False),
        gp(f'laws-an-opening-word-before-a-named-law-{slug}-in-a-grounded-part-ru-blank', BLANK, brief, 'ru', sentence,
           gone=gone),
    ]
CASES += [
    body('laws-an-opening-word-before-a-named-law-and-audit-in-a-qualification-ru-blank', BLANK,
         'pdf.biz.lavozim_yoriqnomasi', JOB_RU_ACCOUNTING, 'ru', 'qualification',
         'Соблюдает Закон о бухгалтерском учёте и аудите.', gone=('аудите',)),
]
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU)):
    CASES.append(guard(f'laws-an-opening-word-before-a-named-law-and-audit-{direction}-blank', BLANK, brief, 'ru',
                       'Соблюдает Закон о бухгалтерском учёте и аудите.', gone=('аудите',), translated=True))
for slug, sentence, gone in (
        ('under-and-auditing', 'Under Law on Accounting and Auditing, the accountant keeps the books.', ('Auditing',)),
        ('per-and-auditing', 'Per Law on Accounting and Auditing, reports are filed monthly.', ('Auditing',)),
        ('by-and-auditing', 'By Law on Accounting and Auditing, the books are kept.', ('Auditing',)),
        ('under-in-banks', 'Under Law on Accounting in Banks, reports are filed.', ('Banks',)),
        ('under-auditing-and-taxes', 'Under Law on Accounting, Auditing and Taxes, reports are filed.',
         ('Auditing', 'Taxes')),
        ('a-role-and-auditing', 'Accountant Law on Accounting and Auditing applies.', ('Auditing',))):
    for direction, brief in (('ru-to-en', JOB_RU_EN_LAW), ('uz-to-en', ACCOUNTING_UZ_EN)):
        CASES.append(guard(f'laws-an-opening-word-before-a-named-law-{slug}-{direction}-blank', BLANK, brief, 'en',
                           sentence, gone=gone, translated=True))
# eb8b05c keeps the customer's own law after a duty's verb or a preposition opening the sentence where its name ends:
# at the sentence's end, or before a word that cannot go on it (a clause after "и" or a comma).
CASES += [
    guard('laws-an-opening-word-before-the-customers-law-ru-keep', KEEP, JOB_RU_ACCOUNTING, 'ru',
          'Соблюдает Закон о бухгалтерском учёте.'),
    gp('laws-an-opening-word-before-the-customers-law-in-a-grounded-part-ru-keep', KEEP, JOB_RU_ACCOUNTING, 'ru',
       'Руководствуется Законом о бухгалтерском учёте.'),
    guard('laws-an-opening-word-before-the-customers-law-and-a-clause-ru-keep', KEEP, JOB_RU_ACCOUNTING, 'ru',
          'Знает Закон о бухгалтерском учёте и умеет вести книги.'),
    guard('laws-an-opening-word-before-the-customers-law-and-a-comma-clause-ru-keep', KEEP, JOB_RU_ACCOUNTING, 'ru',
          'Согласно Закону о бухгалтерском учёте, бухгалтер ведёт книги.'),
    guard('laws-an-opening-word-before-the-customers-law-on-education-ru-keep', KEEP, EDU_RU, 'ru',
          'Соблюдает Закон об образовании.'),
    guard('laws-an-opening-word-before-the-customers-law-and-a-comma-clause-ru-to-en-keep', KEEP, JOB_RU_EN_LAW, 'en',
          'Under Law on Accounting, the accountant keeps the books.', translated=True),
    guard('laws-an-opening-word-before-the-customers-law-and-a-comma-clause-uz-to-en-keep', KEEP, ACCOUNTING_UZ_EN,
          'en', 'Under Law on Accounting, the accountant keeps the books.', translated=True),
]

# ---- An Uzbek ordinal with its apostrophe inside ("to‘rtinchi", "to'rtinchi", "o‘ninchi", "to‘qqizinchi",
# "o‘ttizinchi", "o‘n to‘rtinchi", "yigirma to‘rtinchi") is read whole (must, q3, q4): a placing's patterns read only its
# letters after the apostrophe, which make no ordinal, and the tip skipped the match, so the paper's invented placing
# went unchecked; c491da9 and eb8b05c stopped there and emptied the part. A placing whose words make no ordinal at all
# ("kechinchi o‘rinni") blanks as they did.
ORDINAL_BRIEFS = {
    'uz': 'O‘quvchim Qodirova Malika uchun tavsiyanoma yozing. U a’lochi, matematikani yaxshi ko‘radi.',
    'ru-to-uz': 'Напишите на узбекском рекомендательное письмо для ученицы Малики Кодировой. Она отличница.',
    'en-to-uz': 'Please write a recommendation letter in Uzbek for my student Malika Qodirova. She loves maths.',
}
APOSTROPHE_ORDINALS = (('fourth', 'to‘rtinchi'), ('fourth-ascii', "to'rtinchi"), ('fourth-modifier', 'toʼrtinchi'),
                       ('tenth', 'o‘ninchi'), ('ninth', 'to‘qqizinchi'), ('thirtieth', 'o‘ttizinchi'),
                       ('fourteenth', 'o‘n to‘rtinchi'), ('twenty-fourth', 'yigirma to‘rtinchi'))
APOSTROPHE_PLACINGS = (('took-place', 'U viloyat olimpiadasida {o} o‘rinni egalladi.'),
                       ('was-awarded-place', 'U shahar tanlovida {o} o‘ringa sazovor bo‘ldi.'),
                       ('at-place', 'Matematika olimpiadasida {o} o‘rinda.'),
                       ('became', 'U tanlovda {o} bo‘ldi.'),
                       ('degree-diploma', 'U {o} darajali diplom oldi.'),
                       ('prize', 'Musobaqada {o} sovrinni qo‘lga kiritdi.'),
                       ('result', 'Respublika olimpiadasida {o} natijani ko‘rsatdi.'))
for direction, brief in ORDINAL_BRIEFS.items():
    for slug, ordinal in APOSTROPHE_ORDINALS:
        word = ordinal.split()[-1]
        for form, template in APOSTROPHE_PLACINGS:
            CASES.append(gp(f'numbers-an-apostrophe-ordinal-{slug}-{form}-{direction}-blank', BLANK, brief, 'uz',
                            template.format(o=ordinal), gone=(word,)))
        CASES += [
            body(f'numbers-an-apostrophe-ordinal-{slug}-in-a-references-achievements-{direction}-blank', BLANK,
                 'pdf.xat.tavsifnoma', brief, 'uz', 'achievements',
                 APOSTROPHE_PLACINGS[0][1].format(o=ordinal), gone=(word,)),
            fact(f'numbers-an-apostrophe-ordinal-{slug}-in-a-references-subject-role-{direction}-blank', BLANK,
                 'pdf.xat.tavsifnoma', brief, 'uz', 'subject_role', APOSTROPHE_PLACINGS[0][1].format(o=ordinal),
                 gone=(word,)),
        ]
CASES += [
    gp('numbers-a-placing-whose-words-make-no-ordinal-uz-blank', BLANK, ORDINAL_BRIEFS['uz'], 'uz',
       'U viloyat olimpiadasida kechinchi o‘rinni egalladi.', gone=('kechinchi',)),
    body('numbers-a-placing-whose-words-make-no-ordinal-in-a-references-achievements-uz-blank', BLANK,
         'pdf.xat.tavsifnoma', ORDINAL_BRIEFS['uz'], 'uz', 'achievements',
         'U viloyat olimpiadasida kechinchi o‘rinni egalladi.', gone=('kechinchi',)),
    gp('numbers-an-apostrophe-ordinal-noun-uz-blank', BLANK, ORDINAL_BRIEFS['uz'], 'uz',
       'U tanlovda to‘rtinchilikni qo‘lga kiritdi.', gone=('to‘rtinchilikni',)),
]
# The customer's placing in a form c491da9 never read, their collective, or their bare figure grounds no apostrophe
# ordinal's placing: c491da9 and eb8b05c read none of them there.
for slug, said, locale, sentence, word in (
        ('ranks-fourth-in-sales', 'Savdo bo‘yicha to‘rtinchi o‘rinda turadi.', 'uz', 'U to‘rtinchi o‘rinni egalladi.',
         'to‘rtinchi'),
        ('rose-to-the-fourth-line', 'Он поднялся на четвёртую строчку рейтинга.', 'ru', 'U to‘rtinchi o‘rinni egalladi.',
         'to‘rtinchi'),
        ('took-fourth-at-a-championship', 'He took fourth at the regional championship.', 'en',
         'U to‘rtinchi o‘rinni egalladi.', 'to‘rtinchi'),
        ('entered-the-top-ten', 'Он вошёл в десятку сильнейших.', 'ru', 'U o‘ninchi o‘rinni egalladi.', 'o‘ninchi'),
        ('four-years', 'U 4 yil to‘garakka qatnashgan.', 'uz', 'U to‘rtinchi o‘rinni egalladi.', 'to‘rtinchi')):
    direction = 'uz' if locale == 'uz' else f'{locale}-to-uz'
    CASES.append(gp(f'numbers-a-customers-{slug}-grounds-no-apostrophe-ordinal-{direction}-blank', BLANK,
                    PLACING_LETTERS[locale] + said, 'uz', sentence, gone=(word,)))
# The customer's own placing restated with an apostrophe ordinal blanks too (c491da9 and eb8b05c emptied the part, so
# neither kept it): their "fourth place" gives the figure and the place key their sales ranking "to‘rtinchi o‘rinda
# turadi" gives, and their digits the bare figure "U 4 yil to‘garakka qatnashgan" gives: the owner's tie-break.
CASES += [
    gp('numbers-the-customers-fourth-place-as-an-apostrophe-ordinal-en-to-uz-accepted_false_blank', ACCEPTED,
       PLACING_LETTERS['en'] + 'She won fourth place at the regional olympiad.', 'uz',
       'U viloyat olimpiadasida to‘rtinchi o‘rinni egalladi.', gone=('to‘rtinchi',),
       pair='numbers-a-customers-took-fourth-at-a-championship-grounds-no-apostrophe-ordinal-en-to-uz-blank'),
    gp('numbers-the-customers-fourth-place-as-an-apostrophe-ordinal-ru-to-uz-accepted_false_blank', ACCEPTED,
       PLACING_LETTERS['ru'] + 'На олимпиаде она заняла четвёртое место.', 'uz',
       'U olimpiadada to‘rtinchi o‘rinni egalladi.', gone=('to‘rtinchi',),
       pair='numbers-a-customers-rose-to-the-fourth-line-grounds-no-apostrophe-ordinal-ru-to-uz-blank'),
    gp('numbers-the-customers-digit-placing-as-an-apostrophe-ordinal-uz-accepted_false_blank', ACCEPTED,
       PLACING_LETTERS['uz'] + 'U viloyat olimpiadasida 4-o‘rinni egallagan.', 'uz',
       'U viloyat olimpiadasida to‘rtinchi o‘rinni egalladi.', gone=('to‘rtinchi',),
       pair='numbers-a-customers-four-years-grounds-no-apostrophe-ordinal-uz-blank'),
]

# ---- A rejected line's given name that is also a role's modifier ("Junior", "Global", "Content") is held as c491da9
# holds it (must, q5): the words after a line's last role word, beside the tip's own reading of its name.
SALES_REPORT = {'en': 'Write a monthly sales report for our shop.', 'uz': 'Do‘konimiz uchun oylik savdo hisobotini yozing.'}
for slug, line in (('direktor-junior', 'Direktor Junior Smith'),
                   ('senior-sales-manager-junior', 'Senior Sales Manager Junior Smith'),
                   ('bosh-hisobchi-junior', 'Bosh hisobchi Junior Smith'),
                   ('director-junior', 'Director Junior Smith'),
                   ('direktor-global', 'Direktor Global Aziz'),
                   ('direktor-content', 'Direktor Content Nodir')):
    word = line.split()[-2]
    for locale, brief in SALES_REPORT.items():
        sentence = (f'{word} reviewed the figures with the team.' if locale == 'en'
                    else f'{word} jamoa bilan raqamlarni ko‘rib chiqdi.')
        CASES.append(body(f'names-a-line-modifier-given-name-{slug}-opening-a-sentence-{locale}-blank', BLANK,
                          'pdf.biz.hisobot', brief, locale, 'summary', sentence, gone=(word,),
                          facts=(('author', line),)))

# ---------------------------------------------------------------- the re-check of round 10 (pr77-r1), both ways
# Round 10 left four readings that keep what eb8b05c (in production) or c491da9 blanks, each pinned here as blanks
# under the briefs the re-check used, with the keeps eb8b05c has for the same readings.

# ---- An unnamed law's -s word ends its name only as a verb (a6, a7, a8): a plural noun of the name before a
# determiner and a clause of its own ("The Law on Education fees some parents pay were cut", "Under the Law on
# Education grants every school gets, ..."), before "in force" or before "on" is the name's, as c491da9 reads it.
COURSE_EN = ('Write a course paper in English on school funding in Uzbekistan. Use the Law on Education as the main '
             'source.')
COURSE_EN_LOWER = COURSE_EN.replace('the Law on Education', 'the law on education')
STATE_DUTY_LOWER_EN = 'Write an essay about taxes in Uzbekistan. Mention the law on state duty.'
RELATIVE_TAILS = (
    ('standards-all-schools-meet', COURSE_EN, 'The Law on Education standards all schools meet are strict.',
     'standards'),
    ('fees-some-parents-pay', COURSE_EN, 'The Law on Education fees some parents pay were cut.', 'fees'),
    ('lower-case-fees-some-parents-pay', COURSE_EN_LOWER, 'The law on education fees some parents pay were cut.',
     'fees'),
    ('state-fees-some-citizens-pay', STATE_DUTY_LOWER_EN, 'The law on state fees some citizens pay was amended.',
     'fees'),
    ('loans-many-students-take', COURSE_EN, 'The Law on Education loans many students take are cheap.', 'loans'),
    ('grants-every-school-gets', COURSE_EN, 'Under the Law on Education grants every school gets, funding grew.',
     'grants'),
    ('vouchers-each-family-gets', COURSE_EN, 'The Law on Education vouchers each family gets were raised in 2020.',
     'vouchers'),
    ('quotas-these-regions-set', COURSE_EN, 'The Law on Education quotas these regions set are fair.', 'quotas'),
    ('fees-every-family-pays', COURSE_EN, 'The Law on Education fees every family pays were cut.', 'fees'),
    ('standards-the-state-sets', COURSE_EN, 'The Law on Education standards the state sets are strict.', 'standards'),
    ('grants-the-state-sets', EDU_EN, 'The Law on Education grants the state sets was amended.', 'grants'),
    ('grants-many-families-get', EDU_EN, 'The Law on Education grants many families get was amended.', 'grants'),
    ('grants-such-firms-claim', EDU_EN, 'The Law on Education grants such firms claim was amended.', 'grants'),
    ('grants-all-schools-meet', EDU_EN, 'The Law on Education grants all schools meet was amended.', 'grants'),
    ('grants-families-get', EDU_EN, 'The Law on Education grants families get were cut.', 'grants'),
    ('grants-each-pupil-receives', EDU_EN, 'Under the Law on Education grants each pupil receives, schools grew.',
     'grants'),
    ('state-loans-all-banks-issue', STATE_DUTY_LOWER_EN, 'The law on state loans all banks issue was amended.',
     'loans'),
    ('state-duty-exemptions-any-firm-can-claim', STATE_DUTY_LOWER_EN,
     'The law on state duty exemptions any firm can claim was amended.', 'exemptions'),
    ('state-fees-in-force', STATE_DUTY_LOWER_EN, 'The law on state fees in force was amended.', 'fees'),
    ('education-measures-in-force', EDU_EN, 'The Law on Education measures in force were cut.', 'measures'),
    ('education-requirements-on-schools', EDU_EN, 'The Law on Education requirements on schools are strict.',
     'requirements'),
)
for slug, brief, sentence, word in RELATIVE_TAILS:
    CASES += [
        guard(f'laws-a-plural-noun-of-an-unnamed-law-{slug}-en-blank', BLANK, brief, 'en', sentence, gone=(word,)),
        gp(f'laws-a-plural-noun-of-an-unnamed-law-{slug}-in-a-grounded-part-en-blank', BLANK, brief, 'en', sentence,
           gone=(word,)),
    ]
for slug, brief, sentence, word in RELATIVE_TAILS[:6]:
    CASES.append(body(f'laws-a-plural-noun-of-an-unnamed-law-{slug}-in-a-course-papers-relevance-en-blank', BLANK,
                      'pdf.kurs_ishi', brief, 'en', 'relevance', sentence, gone=(word,)))
# eb8b05c's keeps the reading keeps: a verb's -s before its object, a determiner's noun phrase that goes on with no
# clause of its own.
for slug, sentence in (('grants-every-school-a-budget', 'The Law on Education grants every school a budget.'),
                       ('defines-the-basic-principles', 'The Law on Education defines the basic principles of state '
                                                        'policy.'),
                       ('guarantees-every-citizen-the-right', 'The Law on Education guarantees every citizen the right '
                                                              'to education.'),
                       ('sets-the-rules-every-school-follows', 'The Law on Education sets the rules every school '
                                                               'follows.'),
                       ('protects-every-child-equally', 'The Law on Education protects every child equally.'),
                       ('grants-schools-autonomy', 'The Law on Education grants schools autonomy.'),
                       ('guarantees-many-rights', 'The Law on Education guarantees many rights.'),
                       ('lists-several-rights', 'The Law on Education lists several rights.'),
                       ('highlights-the-role-of-teachers', 'The Law on Education highlights the role of teachers.'),
                       ('explains-how-schools-are-run', 'The Law on Education explains how schools are run.')):
    CASES.append(guard(f'laws-the-customers-law-on-education-{slug}-en-keep', KEEP, EDU_EN, 'en', sentence))
# What the reading costs against eb8b05c: a determiner that opens a relative clause's subject as often as a verb's
# object ("all", "that") is no sign of a verb, so the customer's law before such a verb blanks, the price of an
# invented plural noun before the same determiner and a relative clause whose verb is no auxiliary.
CASES += [
    guard('laws-a-plural-noun-of-an-unnamed-law-grants-all-pupils-receive-en-blank', BLANK, EDU_EN, 'en',
          'The Law on Education grants all pupils receive rose in 2020.', gone=('grants',)),
    guard('laws-a-plural-noun-of-an-unnamed-law-grants-that-pupils-receive-en-blank', BLANK, EDU_EN, 'en',
          'The Law on Education grants that pupils receive rose in 2020.', gone=('grants',)),
    guard('laws-the-customers-law-on-education-equally-protects-all-pupils-en-accepted_false_blank', ACCEPTED, EDU_EN,
          'en', 'The Law on Education equally protects all pupils.', gone=('protects',),
          pair='laws-a-plural-noun-of-an-unnamed-law-grants-all-pupils-receive-en-blank'),
    guard('laws-the-customers-law-on-education-guarantees-that-every-child-can-study-en-accepted_false_blank', ACCEPTED,
          EDU_EN, 'en', 'The Law on Education guarantees that every child can study.', gone=('guarantees',),
          pair='laws-a-plural-noun-of-an-unnamed-law-grants-that-pupils-receive-en-blank'),
]

# ---- The customer's Uzbek ordinal with its apostrophe in a placing gives its place key alone (a1, a8, q3): the
# number word `_words` reads inside it ("to‘rtinchi", "o‘n to‘rtinchi") is no bare figure of theirs, so their
# "to‘rtinchi o‘rinni egalladi" grounds no "4 yil", "4-sinf" or "4 года" (c491da9 and eb8b05c stopped reading there and
# failed the job). A tens word before it the reader did not know ("qirq to‘rtinchi", 44th) makes no fourth place.
APOSTROPHE_SIGNS = (('', '‘'), ('-ascii', "'"), ('-right-quote', '’'), ('-backtick', '`'))
for slug, ordinal, n in (('fourth', 'to{a}rtinchi', 4), ('tenth', 'o{a}ninchi', 10), ('ninth', 'to{a}qqizinchi', 9),
                         ('fourteenth', 'o{a}n to{a}rtinchi', 14), ('twenty-fourth', 'yigirma to{a}rtinchi', 24)):
    for sign, a in APOSTROPHE_SIGNS:
        said = PLACING_LETTERS['uz'] + f'Viloyat olimpiadasida {ordinal.format(a=a)} o{a}rinni egalladi.'
        CASES.append(gp(f'numbers-a-customers-{slug}{sign}-apostrophe-placing-grounds-no-years-uz-blank', BLANK, said,
                        'uz', f'U {n} yil to‘garakka qatnashgan.', gone=(str(n),)))
    said = PLACING_LETTERS['uz'] + f'Viloyat olimpiadasida {ordinal.format(a="‘")} o‘rinni egalladi.'
    CASES += [
        gp(f'numbers-a-customers-{slug}-apostrophe-placing-grounds-no-grade-uz-blank', BLANK, said, 'uz',
           f'U {n}-sinfda o‘qiydi.', gone=(str(n),)),
        gp(f'numbers-a-customers-{slug}-apostrophe-placing-grounds-no-years-uz-to-ru-blank', BLANK, said, 'ru',
           f'Опыт работы — {n} года.', gone=(str(n),)),
        gp(f'numbers-a-customers-{slug}-apostrophe-placing-grounds-no-years-uz-to-en-blank', BLANK, said, 'en',
           f'I have {n} years of experience.', gone=(str(n),)),
        body(f'numbers-a-customers-{slug}-apostrophe-placing-grounds-no-years-in-references-achievements-uz-blank',
             BLANK, 'pdf.xat.tavsifnoma', said, 'uz', 'achievements', f'U {n} yil matematika to‘garagiga qatnashgan.',
             gone=(str(n),)),
        fact(f'numbers-a-customers-{slug}-apostrophe-placing-grounds-no-years-in-references-subject-role-uz-blank',
             BLANK, 'pdf.xat.tavsifnoma', said, 'uz', 'subject_role', f'U {n} yil matematika to‘garagiga qatnashgan.',
             gone=(str(n),)),
    ]
CASES += [
    body('numbers-a-customers-tenth-apostrophe-placing-grounds-no-projects-in-references-achievements-uz-blank', BLANK,
         'pdf.xat.tavsifnoma', PLACING_LETTERS['uz'] + 'Tuman tanlovida o‘ninchi o‘rinda.', 'uz', 'achievements',
         'U 10 ta loyiha tayyorlagan.', gone=('10',)),
]
for slug, ordinal, small in (('forty-fourth', 'qirq to‘rtinchi', 4), ('eighty-fourth', 'sakson to‘rtinchi', 4),
                             ('ninety-fourth', 'to‘qson to‘rtinchi', 4), ('fifty-ninth', 'ellik to‘qqizinchi', 9),
                             ('sixty-fourth', 'oltmish to‘rtinchi', 4), ('seventy-fourth', 'yetmish to‘rtinchi', 4),
                             ('hundred-and-tenth', 'yuz o‘ninchi', 10), ('hundred-and-fourth', 'yuz to‘rtinchi', 4)):
    said = PLACING_LETTERS['uz'] + f'Viloyat olimpiadasida {ordinal} o‘rinni egalladi.'
    word = {4: 'fourth', 9: 'ninth', 10: 'tenth'}[small]
    CASES += [
        gp(f'numbers-a-customers-{slug}-apostrophe-placing-grounds-no-{word}-place-uz-blank', BLANK, said, 'uz',
           f'U olimpiadada {small}-o‘rinni egalladi.', gone=(str(small),)),
        gp(f'numbers-a-customers-{slug}-apostrophe-placing-grounds-no-{word}-place-uz-to-en-blank', BLANK, said, 'en',
           f'She took {word} place at the olympiad.', gone=(word,)),
        gp(f'numbers-a-customers-{slug}-apostrophe-placing-grounds-no-{word}-place-in-digits-uz-to-en-blank', BLANK,
           said, 'en', f'She took {small}th place at the olympiad.', gone=(str(small),)),
        gp(f'numbers-a-customers-{slug}-apostrophe-placing-grounds-no-{word}-place-uz-to-ru-blank', BLANK, said, 'ru',
           f'Она заняла {small}-е место на олимпиаде.', gone=(str(small),)),
        body(f'numbers-a-customers-{slug}-apostrophe-placing-grounds-no-{word}-place-in-references-achievements-uz'
             f'-blank', BLANK, 'pdf.xat.tavsifnoma', said, 'uz', 'achievements',
             f'U olimpiadada {small}-o‘rinni egalladi.', gone=(str(small),)),
    ]

# ---- A semicolon after a law's name ends it only before a word that cannot go on it, as a comma does (a3, a4, a8):
# "Соблюдает Закон о бухгалтерском учёте; аудите и налогах" names more than the customer's law; c491da9 blanks it.
SEMICOLON_BRIEFS = (('ru', JOB_RU_ACCOUNTING, 'ru'), ('en-to-ru', ACCOUNTING_EN_RU, 'ru'),
                    ('uz-to-ru', ACCOUNTING_UZ_RU, 'ru'))
for slug, sentence, gone in (
        ('audit-and-taxes', 'Соблюдает Закон о бухгалтерском учёте; аудите и налогах.', ('аудите', 'налогах')),
        ('about-audit', 'Соблюдает Закон о бухгалтерском учёте; об аудите.', ('аудите',)),
        ('auditing', 'Соблюдает Закон о бухгалтерском учёте; аудиторской деятельности.', ('аудиторской',)),
        ('audit-taxes', 'Руководствуется Законом о бухгалтерском учёте; аудите; налогах.', ('аудите', 'налогах')),
        ('in-banks', 'Знает Закон о бухгалтерском учёте; в банках.', ('банках',))):
    for direction, brief, locale in SEMICOLON_BRIEFS:
        CASES += [
            guard(f'laws-a-tail-after-a-semicolon-after-a-named-law-{slug}-{direction}-blank', BLANK, brief, locale,
                  sentence, gone=gone),
            gp(f'laws-a-tail-after-a-semicolon-after-a-named-law-{slug}-in-a-grounded-part-{direction}-blank', BLANK,
               brief, locale, sentence, gone=gone),
        ]
for part in ('qualification', 'duties'):
    for slug, sentence, gone in (('audit-and-taxes', 'Соблюдает Закон о бухгалтерском учёте; аудите и налогах.',
                                  ('аудите',)),
                                 ('about-audit', 'Соблюдает Закон о бухгалтерском учёте; об аудите.', ('аудите',))):
        CASES.append(body(f'laws-a-tail-after-a-semicolon-after-a-named-law-{slug}-in-a-{part}-ru-blank', BLANK,
                          'pdf.biz.lavozim_yoriqnomasi', JOB_RU_ACCOUNTING, 'ru', part, sentence, gone=gone))
for direction, brief in (('ru-to-en', JOB_RU_EN_LAW), ('uz-to-en', ACCOUNTING_UZ_EN)):
    CASES.append(guard(f'laws-a-tail-after-a-semicolon-after-a-named-law-auditing-and-taxes-{direction}-blank', BLANK,
                       brief, 'en', 'Under Law on Accounting; Auditing and Taxes, the accountant keeps the books.',
                       gone=('Auditing',)))
# eb8b05c keeps the customer's law before a semicolon and a clause, or at the end.
for slug, sentence in (('keeps-books', 'Соблюдает Закон о бухгалтерском учёте; ведёт книги.'),
                       ('makes-reports', 'Соблюдает Закон о бухгалтерском учёте; составляет отчёты.'),
                       ('can-keep-books', 'Знает Закон о бухгалтерском учёте; умеет вести книги.'),
                       ('at-the-end', 'Соблюдает Закон о бухгалтерском учёте;')):
    for direction, brief, locale in SEMICOLON_BRIEFS:
        CASES.append(guard(f'laws-the-customers-law-before-a-semicolon-{slug}-{direction}-keep', KEEP, brief, locale,
                           sentence))

# ---- An article after "and" or a comma is passed over before what follows is read (a3): "Under Law on Accounting
# and the Auditing of Banks, ..." names more than the customer's law in a translated paper too; c491da9 blanks it.
for slug, sentence, gone in (
        ('and-the-auditing-of-banks', 'Under Law on Accounting and the Auditing of Banks, the accountant keeps the '
                                      'books.', ('Auditing',)),
        ('and-an-audit-of-banks', 'Per Law on Accounting and an Audit of Banks, the accountant keeps the books.',
         ('Audit',)),
        ('comma-the-auditing-of-banks', 'Under Law on Accounting, the Auditing of Banks, the accountant keeps the '
                                        'books.', ('Auditing',)),
        ('and-a-banking-supplement', 'Under Law on Accounting and a Banking Supplement, reports are filed.',
         ('Banking',)),
        ('and-the-auditing-of-banks-in-lower-case', 'Under Law on Accounting and the auditing of banks, reports are '
                                                    'filed.', ('auditing',))):
    for direction, brief in (('ru-to-en', JOB_RU_EN_LAW), ('uz-to-en', ACCOUNTING_UZ_EN)):
        CASES.append(guard(f'laws-an-article-before-a-tail-after-a-named-law-{slug}-{direction}-blank', BLANK, brief,
                           'en', sentence, gone=gone, translated=True))
for call in (guard, gp):
    CASES.append(call(f'laws-an-article-before-a-tail-after-a-named-law-in-lower-case-{call.__name__}-en-blank', BLANK,
                      JOB_EN_LAW, 'en', 'Under Law on Accounting and the auditing of banks, reports are filed.',
                      gone=('auditing',)))
# eb8b05c keeps the customer's law before an article and another law of theirs.
for direction, brief in (('en', JOB_EN_LAW), ('ru-to-en', JOB_RU_EN_LAW)):
    CASES.append(guard(f'laws-the-customers-law-before-an-article-and-their-labour-code-{direction}-keep', KEEP, brief,
                       'en', 'Under Law on Accounting and the Labour Code, the accountant keeps the books.'))

# ---- A law's making before a preposition ends its name only before the law's date or number, and a sentence adverb
# never ends the name of a law a preposition governs (a3, joined to the sweep in round 11): "Under Law on accounting
# adopted for banks, ...", "Under Law on accounting thus auditing applies" name more than the customer's law; c491da9
# blanks them, eb8b05c kept them.
for slug, sentence, gone in (
        ('adopted-for-banks', 'Under Law on accounting adopted for banks, the accountant keeps the books.', ('banks',)),
        ('thus-auditing-applies', 'Under Law on accounting thus auditing applies.', ('auditing',)),
        ('amended-for-banks', 'Per the Law on accounting amended for banks, reports are filed.', ('banks',))):
    for direction, brief, translated in (('en', ACCOUNTING_EN, False), ('ru-to-en', JOB_RU_EN_LAW, True),
                                         ('uz-to-en', ACCOUNTING_UZ_EN, True)):
        CASES += [
            guard(f'laws-a-tail-after-a-named-law-{slug}-{direction}-blank', BLANK, brief, 'en', sentence, gone=gone,
                  translated=translated),
            gp(f'laws-a-tail-after-a-named-law-{slug}-in-a-grounded-part-{direction}-blank', BLANK, brief, 'en',
               sentence, gone=gone),
        ]
# eb8b05c keeps the customer's law before its making's date, and before an adverb where no preposition governs it.
for slug, sentence in (('adopted-in-a-year', 'The Law on Education adopted in 1997 is still in force.'),
                       ('thus-protects', 'The Law on Education thus protects pupils.')):
    CASES.append(guard(f'laws-the-customers-law-on-education-{slug}-en-keep', KEEP, EDU_EN + ' It was adopted in 1997.',
                       'en', sentence))

# ---- The false blanks versus eb8b05c the round-11 sweep shows once the re-check's probes join it (a5, a9), each the
# price of the blank it names. A sentence's opening noun before a law's stem is the name's, as c491da9 holds it
# (9f843a9), so the customer's law after "Знание", "Требования", "Нарушение" blanks with an invented role opening the
# same place ("Аудитор Закона о бухгалтерском учёте обязателен"). A word after the name read in no case of its ("...
# учёте бухгалтер ведёт книги", "... учёте отчёт сдаётся") may go on the name as a genitive tail does ("... учёте
# банков регулируется отчётность"), and a preposition may ("... учёте в работе", "... учёте в банках"). A past form
# before a plural noun reads as "state funded schools" ("The Law on Education changed schools").
JOB_RU_KNOWS_ACCOUNTING = 'Составьте должностную инструкцию бухгалтера. Он должен знать Закон о бухгалтерском учёте.'
RUSSIAN_ACCOUNTING = (('ru', JOB_RU_KNOWS_ACCOUNTING), ('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU))
for direction, brief in RUSSIAN_ACCOUNTING:
    translated = direction != 'ru'
    role = f'laws-an-invented-role-opening-a-sentence-before-a-named-law-{direction}-blank'
    tail = f'laws-a-genitive-tail-before-a-clause-verb-after-a-named-law-{direction}-blank'
    banks = ('laws-an-opening-word-before-a-named-law-in-banks-ru-blank' if direction == 'ru'
             else f'laws-an-opening-word-before-a-named-law-in-banks-{direction}-blank')
    CASES += [
        guard(role, BLANK, brief, 'ru', 'Аудитор Закона о бухгалтерском учёте обязателен.', gone=('Аудитор',),
              translated=translated),
        guard(tail, BLANK, brief, 'ru', 'Согласно Закону о бухгалтерском учёте банков регулируется отчётность.',
              gone=('банков',), translated=translated),
    ]
    if translated:
        CASES.append(guard(banks, BLANK, brief, 'ru', 'Соблюдает Закон о бухгалтерском учёте в банках.',
                           gone=('банках',), translated=True))
    for slug, sentence, word, pair in (
            ('knowledge', 'Знание Закона о бухгалтерском учёте обязательно.', 'Знание', role),
            ('requirements', 'Требования Закона о бухгалтерском учёте обязательны.', 'Требования', role),
            ('violation', 'Нарушение Закона о бухгалтерском учёте недопустимо.', 'Нарушение', role),
            ('observance', 'Соблюдение Закона о бухгалтерском учёте обязательно.', 'Соблюдение', role),
            ('provisions', 'Положения Закона о бухгалтерском учёте соблюдаются.', 'Положения', role),
            ('norms', 'Нормы Закона о бухгалтерском учёте применяются.', 'Нормы', role),
            ('according-to-a-clause', 'Согласно Закону о бухгалтерском учёте бухгалтер ведёт книги.', 'бухгалтер',
             tail),
            ('by-a-clause', 'По Закону о бухгалтерском учёте отчёт сдаётся ежегодно.', 'отчёт', tail),
            ('according-to-a-reflexive-clause', 'Согласно Закону о бухгалтерском учёте отчётность сдаётся ежегодно.',
             'отчётность', tail),
            ('at-work', 'Применяет Закон о бухгалтерском учёте в работе.', 'работе', banks)):
        CASES.append(gp(f'laws-the-customers-law-after-an-opening-word-{slug}-{direction}-accepted_false_blank',
                        ACCEPTED, brief, 'ru', sentence, gone=(word,), pair=pair))
FUNDED_SCHOOLS_GREW = 'laws-an-invented-tail-after-the-customers-law-on-education-funded-schools-grew-en-blank'
CASES += [
    guard(FUNDED_SCHOOLS_GREW, BLANK, EDU_EN, 'en', 'The Law on Education funded schools grew.', gone=('funded',)),
    gp('laws-the-customers-law-on-education-introduced-new-standards-en-accepted_false_blank', ACCEPTED, EDU_EN, 'en',
       'The Law on Education introduced new standards.', gone=('introduced',), pair=FUNDED_SCHOOLS_GREW),
    gp('laws-the-customers-law-on-education-changed-schools-en-accepted_false_blank', ACCEPTED, EDU_EN, 'en',
       'The Law on Education changed schools.', gone=('changed',), pair=FUNDED_SCHOOLS_GREW),
]

# ---------------------------------------------------------------- the re-check of round 11 (pr77-r2), both ways
# Round 11 left four readings that keep what eb8b05c (in production) or c491da9 blanks, each pinned here as blanks
# under the briefs the re-check used, with the keeps eb8b05c has for the same readings.

# ---- Past "и", "and", a comma or a semicolon after a law's name, the words that open no clause are passed over before
# what follows is judged (p1, p4, p5): a particle, a parenthetical word or an adverb ("и особенно аудите", "а именно
# аудите", ", то есть аудите", ", т. е. аудите", ", как и об аудите", "и лишь налогообложении", "and even auditing",
# ", i.e. Auditing") and an English determiner ("and its auditing rules", "and every auditing standard"); "as well as"
# joins as "and" does. The tip judged the first word after the conjunction alone and ended the name there, so an
# opening verb or preposition was dropped, or a translated paper's head noun "учёте" passed as the customer's, and the
# invented tail went unread; c491da9 holds the opening word or the head noun and blanks.
FILLER_TAILS_RU = (
    ('and-especially-audit', 'Соблюдает Закон о бухгалтерском учёте и особенно аудите.', ('аудите',)),
    ('namely-audit', 'Знает Закон о бухгалтерском учёте, а именно аудите.', ('аудите',)),
    ('that-is-audit', 'Применяет Закон о бухгалтерском учёте, то есть аудите.', ('аудите',)),
    ('ie-audit', 'Руководствуется Законом о бухгалтерском учёте, т. е. аудите.', ('аудите',)),
    ('as-about-audit', 'Согласно Закону о бухгалтерском учёте, как и об аудите, бухгалтер ведёт книги.', ('аудите',)),
    ('and-of-course-audit', 'Изучает Закон о бухгалтерском учёте и конечно аудите.', ('аудите',)),
    ('and-accordingly-audit', 'Соблюдает Закон о бухгалтерском учёте и соответственно аудите.', ('аудите',)),
    ('and-naturally-audit', 'Знает Закон о бухгалтерском учёте и разумеется аудите.', ('аудите',)),
    ('and-only-audit', 'Применяет Закон о бухгалтерском учёте и только аудите.', ('аудите',)),
    ('and-just-taxation', 'Соблюдает Закон о бухгалтерском учёте и лишь налогообложении.', ('налогообложении',)),
    ('and-a-little-audit', 'Знает Закон о бухгалтерском учёте и немного аудите.', ('аудите',)),
    ('and-sometimes-audit', 'Соблюдает Закон о бухгалтерском учёте и иногда аудите.', ('аудите',)),
    ('and-necessarily-audit', 'Соблюдает Закон о бухгалтерском учёте и обязательно аудите.', ('аудите',)),
    ('and-once-more-audit', 'Соблюдает Закон о бухгалтерском учёте и ещё раз аудите.', ('аудите',)),
    ('of-course-in-commas-audit', 'Соблюдает Закон о бухгалтерском учёте, конечно, аудите.', ('аудите',)))
for direction, brief in RUSSIAN_ACCOUNTING:
    for slug, sentence, gone in FILLER_TAILS_RU:
        CASES += [
            guard(f'laws-a-tail-past-a-filler-after-a-named-law-{slug}-{direction}-blank', BLANK, brief, 'ru', sentence,
                  gone=gone, translated=direction != 'ru'),
            gp(f'laws-a-tail-past-a-filler-after-a-named-law-{slug}-in-a-grounded-part-{direction}-blank', BLANK,
               brief, 'ru', sentence, gone=gone),
        ]
    CASES.append(body(f'laws-a-tail-past-a-filler-after-a-named-law-and-especially-audit-in-a-qualification-{direction}'
                      f'-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', brief, 'ru', 'qualification',
                      FILLER_TAILS_RU[0][1], gone=('аудите',)))
# A translated paper's head noun "учёте" after a subject, no opening word: only the head noun decides.
ACCOUNTING_UZC_RU = ('Бухгалтер учун рус тилида лавозим йўриқномаси ёзинг. У Бухгалтерия ҳисоби тўғрисидаги қонунни '
                     'билиши керак.')
for slug, sentence, gone in (
        ('and-especially-audit', 'Бухгалтер соблюдает Закон о бухгалтерском учёте и особенно аудите.', ('аудите',)),
        ('namely-audit', 'Бухгалтер обязан знать Закон о бухгалтерском учёте, а именно аудите.', ('аудите',)),
        ('as-about-audit', 'Работник применяет Закон о бухгалтерском учёте, как и об аудите.', ('аудите',)),
        ('and-just-taxation', 'Он хорошо знает Закон о бухгалтерском учёте и лишь налогообложении.',
         ('налогообложении',)),
        ('ie-audit', 'Бухгалтер соблюдает Закон о бухгалтерском учёте, т. е. аудите.', ('аудите',))):
    for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU),
                             ('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU)):
        CASES += [
            guard(f'laws-a-translated-head-noun-before-a-filler-and-a-tail-{slug}-{direction}-blank', BLANK, brief,
                  'ru', sentence, gone=gone, translated=True),
            gp(f'laws-a-translated-head-noun-before-a-filler-and-a-tail-{slug}-in-a-grounded-part-{direction}-blank',
               BLANK, brief, 'ru', sentence, gone=gone),
        ]
    CASES.append(body(f'laws-a-translated-head-noun-before-a-filler-and-a-tail-{slug}-in-a-qualification-en-to-ru'
                      f'-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', ACCOUNTING_EN_RU, 'ru', 'qualification',
                      sentence, gone=gone))
JOB_EN_KNOWS_ACCOUNTING = 'Write a job description for an accountant. He must know the Law on Accounting.'
FILLER_TAILS_EN = (
    ('as-well-as-auditing', 'Under Law on Accounting as well as auditing.', ('auditing',)),
    ('as-well-as-auditing-capitalised', 'Per Law on Accounting as well as Auditing, reports are filed.', ('Auditing',)),
    ('as-well-as-on-auditing', 'Under Law on Accounting as well as on auditing, reports are filed.',
     ('auditing',)),
    ('and-even-auditing', 'Under Law on Accounting and even auditing.', ('auditing',)),
    ('and-only-auditing', 'Per Law on Accounting and only auditing, reports are filed.', ('auditing',)),
    ('and-so-auditing', 'Under Law on Accounting and so auditing, reports are filed.', ('auditing',)),
    ('and-not-only-auditing', 'Per Law on Accounting and not only auditing, reports are filed.', ('auditing',)),
    ('and-its-auditing-rules', 'Under Law on Accounting and its auditing rules, reports are filed.', ('auditing',)),
    ('and-every-auditing-standard', 'Per Law on Accounting and every auditing standard, reports are filed.',
     ('auditing',)),
    ('and-all-auditing-rules', 'Under Law on Accounting and all auditing rules, reports are filed.', ('auditing',)),
    ('comma-ie-auditing', 'Under Law on Accounting, i.e. auditing, reports are filed.', ('auditing',)),
    ('ie-auditing', 'Per Law on Accounting i.e. auditing, reports are filed.', ('auditing',)),
    ('comma-that-is-auditing', 'Under Law on Accounting, that is, auditing, reports are filed.', ('auditing',)),
    ('comma-even-auditing', 'Per Law on Accounting, even auditing, reports are filed.', ('auditing',)))
for direction, brief, translated in (('en', JOB_EN_KNOWS_ACCOUNTING, False), ('ru-to-en', JOB_RU_EN_LAW, True),
                                     ('uz-to-en', ACCOUNTING_UZ_EN, True)):
    for slug, sentence, gone in FILLER_TAILS_EN:
        CASES += [
            guard(f'laws-a-tail-past-a-filler-after-a-named-law-{slug}-{direction}-blank', BLANK, brief, 'en', sentence,
                  gone=gone, translated=translated),
            gp(f'laws-a-tail-past-a-filler-after-a-named-law-{slug}-in-a-grounded-part-{direction}-blank', BLANK,
               brief, 'en', sentence, gone=gone),
        ]
    CASES.append(body(f'laws-a-tail-past-a-filler-after-a-named-law-as-well-as-auditing-in-a-qualification-{direction}'
                      f'-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', brief, 'en', 'qualification',
                      FILLER_TAILS_EN[0][1], gone=('auditing',)))
# eb8b05c keeps the customer's law before a word past the conjunction or the comma that cannot go on its name: another
# object, a clause's subject or verb, another law of theirs, "и т. д.", "and so on".
for slug, sentence in (
        ('and-the-cash-procedure', 'Знает Закон о бухгалтерском учёте и порядок ведения кассовых операций.'),
        ('and-the-rules-of-bookkeeping', 'Знает Закон о бухгалтерском учёте и правила ведения книг.'),
        ('and-the-method-of-reporting', 'Знает Закон о бухгалтерском учёте и методику составления отчётности.'),
        ('and-the-basics-of-taxation', 'Знает Закон о бухгалтерском учёте и основы налогообложения.'),
        ('and-keeps-books', 'Знает Закон о бухгалтерском учёте и ведёт книги.'),
        ('and-so-on', 'Знает Закон о бухгалтерском учёте и т. д.'),
        ('and-so-forth', 'Знает Закон о бухгалтерском учёте и так далее.'),
        ('comma-and-the-accountant', 'Соблюдает Закон о бухгалтерском учёте, а бухгалтер ведёт книги.'),
        ('comma-as-a-rule', 'Согласно Закону о бухгалтерском учёте, как правило, отчёты сдаются ежегодно.'),
        ('comma-it-is-required', 'Согласно Закону о бухгалтерском учёте, это обязательно.'),
        ('comma-the-chief-accountant', 'Согласно Закону о бухгалтерском учёте, главный бухгалтер ведёт книги.')):
    for direction, brief in RUSSIAN_ACCOUNTING:
        CASES.append(guard(f'laws-the-customers-law-before-a-word-that-cannot-go-on-it-{slug}-{direction}-keep', KEEP,
                           brief, 'ru', sentence))
CASES.append(guard('laws-the-customers-law-before-their-other-legislation-ru-keep', KEEP,
                   JOB_RU_KNOWS_ACCOUNTING + ' Также законодательство о налогах.', 'ru',
                   'Знает Закон о бухгалтерском учёте и законодательство о налогах.'))
for slug, sentence in (('a-subject-keeps-books', 'Бухгалтер соблюдает Закон о бухгалтерском учёте и умеет вести '
                                                 'книги.'),
                       ('a-subject-and-the-rules', 'Бухгалтер соблюдает Закон о бухгалтерском учёте, а также правила '
                                                   'ведения книг.')):
    for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU)):
        CASES.append(guard(f'laws-the-customers-translated-law-before-a-word-that-cannot-go-on-it-{slug}-{direction}'
                           f'-keep', KEEP, brief, 'ru', sentence, translated=True))
for slug, sentence in (('comma-its-rules-apply', 'Under Law on Accounting, its rules apply to all firms.'),
                       ('comma-every-firm-keeps', 'Under Law on Accounting, every firm keeps its books.'),
                       ('comma-all-firms-keep', 'Under Law on Accounting, all firms keep books.'),
                       ('comma-this-applies', 'Under Law on Accounting, this applies to all firms.'),
                       ('comma-he-keeps', 'Under Law on Accounting, he keeps the books.'),
                       ('and-so-on', 'Follows the Law on Accounting and so on.'),
                       ('and-applies-it', 'Follows the Law on Accounting and applies it daily.'),
                       ('and-this-applies', 'Knows the Law on Accounting and this applies to all firms.')):
    for direction, brief in (('en', JOB_EN_KNOWS_ACCOUNTING), ('ru-to-en', JOB_RU_EN_LAW),
                             ('uz-to-en', ACCOUNTING_UZ_EN)):
        CASES.append(guard(f'laws-the-customers-law-before-a-word-that-cannot-go-on-it-{slug}-{direction}-keep', KEEP,
                           brief, 'en', sentence))

# eb8b05c's keeps the census of round 11 found blanked (p6), restored where no leak comes back: a clause after a comma
# whose lower-case subject goes on with an auxiliary or a modal ("..., teachers must protect pupils", "..., books are
# kept daily"), and an adverb right after the law's name before the sentence's end ("... учёте хорошо."). A list after
# the comma and a tail after the adverb still blank.
TEACHER_EN = 'Write a job description for a teacher. He must know the Law on Education.'
CASES += [
    guard('laws-the-customers-law-before-a-comma-and-a-clause-teachers-must-protect-en-keep', KEEP, TEACHER_EN, 'en',
          'Under Law on Education, teachers must protect pupils.'),
    guard('laws-a-tail-past-a-comma-after-a-named-law-a-list-before-a-verb-en-blank', BLANK, JOB_EN_KNOWS_ACCOUNTING,
          'en', 'Under Law on Accounting, auditing and taxes are covered.', gone=('auditing', 'taxes')),
]
for direction, brief in (('en', JOB_EN_KNOWS_ACCOUNTING), ('ru-to-en', JOB_RU_EN_LAW), ('uz-to-en', ACCOUNTING_UZ_EN)):
    CASES.append(guard(f'laws-the-customers-law-before-a-comma-and-a-clause-books-are-kept-{direction}-keep', KEEP,
                       brief, 'en', 'Under Law on Accounting, books are kept daily.'))
for direction, brief in RUSSIAN_ACCOUNTING:
    CASES += [
        guard(f'laws-the-customers-law-before-an-adverb-at-the-end-{direction}-keep', KEEP, brief, 'ru',
              'Знает Закон о бухгалтерском учёте хорошо.'),
        guard(f'laws-a-tail-past-an-adverb-after-a-named-law-in-banks-{direction}-blank', BLANK, brief, 'ru',
              'Соблюдает Закон о бухгалтерском учёте строго в банках.', gone=('банках',), translated=direction != 'ru'),
        guard(f'laws-a-tail-past-an-adverb-after-a-named-law-and-audit-{direction}-blank', BLANK, brief, 'ru',
              'Соблюдает Закон о бухгалтерском учёте хорошо и аудите.', gone=('аудите',), translated=direction != 'ru'),
    ]
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU)):
    CASES += [
        guard(f'laws-the-customers-translated-law-before-an-adverb-at-the-end-{direction}-keep', KEEP, brief, 'ru',
              'Бухгалтер знает Закон о бухгалтерском учёте хорошо.', translated=True),
        guard(f'laws-a-translated-head-noun-before-an-adverb-and-a-tail-{direction}-blank', BLANK, brief, 'ru',
              'Бухгалтер знает Закон о бухгалтерском учёте особенно аудите.', gone=('аудите',), translated=True),
    ]

# ---- After a law's date or number, its name ends only at the sentence's or its clause's end, a verb, or past "и" or a
# comma where it cannot go on (p1, p4): "Соблюдает Закон о бухгалтерском учёте от 13 апреля 2016 года и аудите", "... №
# 404 в банках", "Under Law on Accounting of 13 April 2016 and Auditing" name more than the customer's law; the tip
# ended the name at the date and c491da9 blanks.
JOB_RU_KNOWS_ACCOUNTING_DATED = ('Составьте должностную инструкцию бухгалтера. Он должен знать Закон о бухгалтерском '
                                 'учёте от 13 апреля 2016 года № 404.')
ACCOUNTING_EN_RU_NUMBERED = ('Write a job description for an accountant in Russian. He must know the Law on Accounting '
                             'of 13 April 2016 No. 404.')
ACCOUNTING_UZ_RU_NUMBERED = ('Buxgalter uchun rus tilida lavozim yo‘riqnomasi yozing. U 2016 yil 13 apreldagi '
                             '404-sonli Buxgalteriya hisobi to‘g‘risidagi qonunni bilishi kerak.')
JOB_EN_KNOWS_ACCOUNTING_DATED = ('Write a job description for an accountant. He must know the Law on Accounting of 13 '
                                 'April 2016 No. 404.')
DATED_TAILS_RU = (
    ('and-audit', 'Соблюдает Закон о бухгалтерском учёте от 13 апреля 2016 года и аудите.', ('аудите',)),
    ('audit-and-taxes', 'Знает Закон о бухгалтерском учёте от 13 апреля 2016 года, аудите и налогах.',
     ('аудите', 'налогах')),
    ('number-and-audit', 'Руководствуется Законом о бухгалтерском учёте № 404 и аудите.', ('аудите',)),
    ('number-in-banks', 'Применяет Закон о бухгалтерском учёте № 404 в банках.', ('банках',)),
    ('in-banks', 'Согласно Закону о бухгалтерском учёте от 13 апреля 2016 года в банках отчёты сдаются.', ('банках',)),
    ('and-about-audit', 'Изучает Закон о бухгалтерском учёте от 13 апреля 2016 года и об аудите.', ('аудите',)),
    ('number-and-especially-audit', 'Соблюдает Закон о бухгалтерском учёте № 404 и особенно аудите.', ('аудите',)))
for direction, brief in (('ru', JOB_RU_KNOWS_ACCOUNTING_DATED), ('en-to-ru', ACCOUNTING_EN_RU_NUMBERED)):
    for slug, sentence, gone in DATED_TAILS_RU:
        CASES += [
            guard(f'laws-a-tail-after-a-named-laws-date-{slug}-{direction}-blank', BLANK, brief, 'ru', sentence,
                  gone=gone, translated=direction != 'ru'),
            gp(f'laws-a-tail-after-a-named-laws-date-{slug}-in-a-grounded-part-{direction}-blank', BLANK, brief, 'ru',
               sentence, gone=gone),
        ]
    CASES.append(body(f'laws-a-tail-after-a-named-laws-date-and-audit-in-a-qualification-{direction}-blank', BLANK,
                      'pdf.biz.lavozim_yoriqnomasi', brief, 'ru', 'qualification', DATED_TAILS_RU[0][1],
                      gone=('аудите',)))
for slug, sentence, gone in (
        ('and-audit', 'Бухгалтер соблюдает Закон о бухгалтерском учёте от 13 апреля 2016 года и аудите.', ('аудите',)),
        ('number-audit-and-taxes', 'Бухгалтер соблюдает Закон о бухгалтерском учёте № 404, аудите и налогах.',
         ('аудите', 'налогах')),
        ('in-banks', 'Работник применяет Закон о бухгалтерском учёте от 13 апреля 2016 года в банках.', ('банках',))):
    for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU_NUMBERED), ('uz-to-ru', ACCOUNTING_UZ_RU_NUMBERED)):
        CASES.append(guard(f'laws-a-translated-head-noun-before-a-date-and-a-tail-{slug}-{direction}-blank', BLANK,
                           brief, 'ru', sentence, gone=gone, translated=True))
for slug, sentence, gone in (
        ('and-auditing', 'Under Law on Accounting of 13 April 2016 and auditing, reports are filed.', ('auditing',)),
        ('for-banks', 'Per Law on Accounting of 13 April 2016 for banks, reports are filed.', ('banks',)),
        ('number-and-auditing', 'Under Law on Accounting of 13 April 2016 No. 404 and auditing, reports are filed.',
         ('auditing',))):
    CASES += [
        guard(f'laws-a-tail-after-a-named-laws-date-{slug}-en-blank', BLANK, JOB_EN_KNOWS_ACCOUNTING_DATED, 'en',
              sentence, gone=gone, translated=False),
        gp(f'laws-a-tail-after-a-named-laws-date-{slug}-in-a-grounded-part-en-blank', BLANK,
           JOB_EN_KNOWS_ACCOUNTING_DATED, 'en', sentence, gone=gone),
    ]
# A genitive tail after the law's number names more than the customer's law, as it does right after the name.
NUMBER_GENITIVE_TAIL = 'laws-a-genitive-tail-after-a-named-laws-number-before-a-clause-verb-ru-blank'
CASES.append(guard(NUMBER_GENITIVE_TAIL, BLANK, JOB_RU_KNOWS_ACCOUNTING_DATED, 'ru',
                   'Согласно Закону о бухгалтерском учёте № 404 банков регулируется отчётность.', gone=('банков',)))
# eb8b05c keeps the customer's law and its date before the sentence's end, a verb, or a clause past "и" or a comma.
for slug, sentence in (('at-the-end', 'Знает Закон о бухгалтерском учёте от 13 апреля 2016 года.'),
                       ('and-can-keep-books', 'Знает Закон о бухгалтерском учёте от 13 апреля 2016 года и умеет вести '
                                              'книги.'),
                       ('number-comma-a-clause', 'Соблюдает Закон о бухгалтерском учёте № 404, бухгалтер ведёт книги.'),
                       ('a-verb', 'Закон о бухгалтерском учёте от 13 апреля 2016 года регулирует учёт.')):
    for direction, brief in (('ru', JOB_RU_KNOWS_ACCOUNTING_DATED), ('en-to-ru', ACCOUNTING_EN_RU_NUMBERED)):
        CASES.append(guard(f'laws-the-customers-law-and-its-date-{slug}-{direction}-keep', KEEP, brief, 'ru',
                           sentence))
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU_NUMBERED), ('uz-to-ru', ACCOUNTING_UZ_RU_NUMBERED)):
    CASES.append(guard(f'laws-the-customers-translated-law-and-its-date-at-the-end-{direction}-keep', KEEP, brief, 'ru',
                       'Бухгалтер соблюдает Закон о бухгалтерском учёте от 13 апреля 2016 года.', translated=True))
for slug, sentence in (('comma-a-clause', 'Under Law on Accounting of 13 April 2016, the accountant keeps the books.'),
                       ('number-at-the-end', 'Follows the Law on Accounting of 13 April 2016 No. 404.'),
                       ('and-applies-it', 'Follows the Law on Accounting of 13 April 2016 and applies it daily.')):
    CASES.append(guard(f'laws-the-customers-law-and-its-date-{slug}-en-keep', KEEP, JOB_EN_KNOWS_ACCOUNTING_DATED, 'en',
                       sentence))
# What the reading costs against eb8b05c: a clause after the law's date with its subject first ("... № 404 отчёты
# сдаются ежегодно") reads as a genitive tail after the number does, so the customer's law blanks.
CASES.append(guard('laws-the-customers-law-and-its-number-before-a-subject-and-its-verb-ru-accepted_false_blank',
                   ACCEPTED, JOB_RU_KNOWS_ACCOUNTING_DATED, 'ru',
                   'Согласно Закону о бухгалтерском учёте от 13 апреля 2016 года № 404 отчёты сдаются ежегодно.',
                   gone=('отчёты',), pair=NUMBER_GENITIVE_TAIL))

# ---- A placing only the placings read since see, its Uzbek ordinal with its apostrophe left unread, gives the
# customer's side its place key alone (the sweep's 146 lines versus eb8b05c, p2): c491da9 read the ordinal's number word
# alone as a bare figure, so their "to‘rtinchi natijani ko‘rsatdi" grounded the paper's "4 yil", "4-sinf" or "4 года";
# eb8b05c stopped reading there and failed the job. The owner's decision: c491da9's numbers change for these texts only
# (tests/test_category_numbers_parity.py names them).
SECOND_PLACINGS = (('result', 'Tuman olimpiadasida {o} natijani ko{a}rsatdi.'),
                   ('step', 'Musobaqada {o} pog{a}onaga ko{a}tarildi.'),
                   ('degree-diploma', 'U {o} darajali diplom oldi.'),
                   ('sales-place', 'Savdo hajmi bo{a}yicha {o} o{a}ringa chiqdi.'),
                   ('became', 'Olimpiadada {o} bo{a}ldi.'),
                   ('ranks-in-sales', 'Savdo bo{a}yicha {o} o{a}rinda turadi.'))
SECOND_ORDINALS = (('fourth', 'to{a}rtinchi', 4), ('ninth', 'to{a}qqizinchi', 9), ('tenth', 'o{a}ninchi', 10),
                   ('fourteenth', 'o{a}n to{a}rtinchi', 14), ('twenty-ninth', 'yigirma to{a}qqizinchi', 29))
for form, template in SECOND_PLACINGS:
    for slug, ordinal, n in SECOND_ORDINALS:
        said = PLACING_LETTERS['uz'] + template.format(o=ordinal.format(a='‘'), a='‘')
        CASES.append(gp(f'numbers-a-customers-second-reading-{form}-placing-{slug}-grounds-no-years-uz-blank', BLANK,
                        said, 'uz', f'U {n} yil to‘garakka qatnashgan.', gone=(str(n),)))
    for sign, a in (('ascii', "'"), ('right-quote', '’'), ('backtick', '`')):
        said = PLACING_LETTERS['uz'] + template.format(o=f'to{a}rtinchi', a=a)
        CASES.append(gp(f'numbers-a-customers-second-reading-{form}-placing-fourth-{sign}-grounds-no-years-uz-blank',
                        BLANK, said, 'uz', 'U 4 yil to‘garakka qatnashgan.', gone=('4',)))
    said = PLACING_LETTERS['uz'] + template.format(o='to‘rtinchi', a='‘')
    CASES += [
        gp(f'numbers-a-customers-second-reading-{form}-placing-grounds-no-grade-uz-blank', BLANK, said, 'uz',
           'U 4-sinfda o‘qiydi.', gone=('4',)),
        gp(f'numbers-a-customers-second-reading-{form}-placing-grounds-no-projects-uz-blank', BLANK, said, 'uz',
           'U 4 ta loyihada qatnashdi.', gone=('4',)),
        gp(f'numbers-a-customers-second-reading-{form}-placing-grounds-no-years-uz-to-ru-blank', BLANK, said, 'ru',
           'Опыт работы — 4 года.', gone=('4',)),
        gp(f'numbers-a-customers-second-reading-{form}-placing-grounds-no-years-uz-to-en-blank', BLANK, said, 'en',
           'I have 4 years of experience.', gone=('4',)),
        body(f'numbers-a-customers-second-reading-{form}-placing-grounds-no-years-in-references-achievements-uz-blank',
             BLANK, 'pdf.xat.tavsifnoma', said, 'uz', 'achievements', 'U 4 yil matematika to‘garagiga qatnashgan.',
             gone=('4',)),
    ]

# ---- The false blanks versus eb8b05c the round-12 sweep and the re-check's census (p6) still show, each the price of
# the blank it names: a preposition after the law's name may go on it ("... учёте на практике", "... учёте во всём", as
# "... учёте в банках"); a clause's subject after the name reads as a genitive tail ("... учёте бухгалтер отвечает за
# отчёты", as "... учёте банков регулируется отчётность"); a determiner that opens a relative clause's subject as
# often as a verb's object is no sign of a verb ("guarantees each child", "protects some pupils", as "vouchers each
# family gets", "fees some parents pay"); "to" before a determiner reads as before a noun ("matters to every teacher",
# as "grants to students").
for direction, brief in RUSSIAN_ACCOUNTING:
    banks = ('laws-an-opening-word-before-a-named-law-in-banks-ru-blank' if direction == 'ru'
             else f'laws-an-opening-word-before-a-named-law-in-banks-{direction}-blank')
    tail = f'laws-a-genitive-tail-before-a-clause-verb-after-a-named-law-{direction}-blank'
    for slug, sentence, word, pair in (
            ('in-practice', 'Применяет Закон о бухгалтерском учёте на практике.', 'практике', banks),
            ('in-everything', 'Следует Закону о бухгалтерском учёте во всём.', 'всём', banks),
            ('by-a-subject-and-its-verb', 'По Закону о бухгалтерском учёте бухгалтер отвечает за отчёты.', 'бухгалтер',
             tail)):
        CASES.append(gp(f'laws-the-customers-law-after-an-opening-word-{slug}-{direction}-accepted_false_blank',
                        ACCEPTED, brief, 'ru', sentence, gone=(word,), pair=pair))
CASES += [
    guard('laws-the-customers-law-on-education-guarantees-each-child-a-place-en-accepted_false_blank', ACCEPTED,
          EDU_EN, 'en', 'The Law on Education guarantees each child a place.', gone=('guarantees',),
          pair='laws-a-plural-noun-of-an-unnamed-law-vouchers-each-family-gets-en-blank'),
    guard('laws-the-customers-law-on-education-protects-some-pupils-more-en-accepted_false_blank', ACCEPTED, EDU_EN,
          'en', 'The Law on Education protects some pupils more.', gone=('protects',),
          pair='laws-a-plural-noun-of-an-unnamed-law-fees-some-parents-pay-en-blank'),
    guard('laws-the-customers-law-on-education-matters-to-every-teacher-en-accepted_false_blank', ACCEPTED, EDU_EN,
          'en', 'The Law on Education matters to every teacher.', gone=('matters',),
          pair='laws-an-invented-tail-after-the-customers-law-education-grants-to-students-en-blank'),
    guard('laws-the-customers-law-and-its-number-before-a-subject-and-its-verb-en-to-ru-accepted_false_blank', ACCEPTED,
          ACCOUNTING_EN_RU_NUMBERED, 'ru',
          'Согласно Закону о бухгалтерском учёте от 13 апреля 2016 года № 404 отчёты сдаются ежегодно.',
          gone=('отчёты',), pair=NUMBER_GENITIVE_TAIL),
]

# ---------------------------------------------------------------- the re-check of round 12 (pr77-r3), both ways
# Round 12 left one reading that keeps what c491da9 blanks (eb8b05c, in production, keeps it too), pinned here as blanks
# under the briefs the re-check used, with the keeps 28c1b69 has for the same readings.

# ---- A Russian noun that keeps its -о in every case ("радио", "кино", "казино", "метро", "видео", "фото", "евро",
# "бюро", "сальдо") may go on a law's name (a1, a3): after "и", a comma, "а также", a passed adverb, the law's date or
# number, in a quoted title, or right after the name as its genitive ("... учёте казино"). 28c1b69 passed it over as an
# adverb in -о, or read it as no case the name takes, and ended the name there, so an opening verb or preposition was
# dropped, or a translated paper's head noun "учёте" passed as the customer's, and the invented tail went unread;
# c491da9 holds the opening word or the head noun and blanks.
INDECLINABLE_TAILS_RU = (
    ('and-radio', 'Знает Закон о бухгалтерском учёте и радио.', ('радио',)),
    ('casino-as-a-genitive', 'Знает Закон о бухгалтерском учёте казино.', ('казино',)),
    ('as-well-as-cinema', 'Согласно Закону о бухгалтерском учёте, а также кино, бухгалтер ведёт книги.', ('кино',)),
    ('and-especially-metro', 'Руководствуется Законом о бухгалтерском учёте и особенно метро.', ('метро',)),
    ('bureau-and-audit', 'Применяет Закон о бухгалтерском учёте, бюро и аудите.', ('бюро', 'аудите')),
    ('and-balance', 'Соблюдает Закон о бухгалтерском учёте и сальдо.', ('сальдо',)),
    ('and-video-before-a-comma-clause', 'По Закону о бухгалтерском учёте и видео, бухгалтер ведёт книги.', ('видео',)),
    ('a-quoted-title-and-photo', 'Знает Закон «О бухгалтерском учёте и фото».', ('фото',)),
    ('having-studied-and-euro', 'Изучив Закон о бухгалтерском учёте и евро, бухгалтер ведёт книги.', ('евро',)),
    ('and-radio-strictly', 'Знает Закон о бухгалтерском учёте и радио строго.', ('радио',)))
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence, gone in INDECLINABLE_TAILS_RU:
        CASES += [
            guard(f'laws-an-indeclinable-tail-after-a-named-law-{slug}-{direction}-blank', BLANK, brief, 'ru',
                  sentence, gone=gone, translated=direction != 'ru'),
            gp(f'laws-an-indeclinable-tail-after-a-named-law-{slug}-in-a-grounded-part-{direction}-blank', BLANK,
               brief, 'ru', sentence, gone=gone),
        ]
    CASES.append(body(f'laws-an-indeclinable-tail-after-a-named-law-and-radio-in-a-qualification-{direction}-blank',
                      BLANK, 'pdf.biz.lavozim_yoriqnomasi', brief, 'ru', 'qualification', INDECLINABLE_TAILS_RU[0][1],
                      gone=('радио',)))
    if direction != 'ru':
        # A translated paper checks no capitalised word but the law's own: the noun capitalised is read as it is.
        CASES.append(guard(f'laws-an-indeclinable-tail-after-a-named-law-and-radio-capitalised-{direction}-blank',
                           BLANK, brief, 'ru', 'Знает Закон о бухгалтерском учёте и Радио.', gone=('Радио',),
                           translated=True))
for direction, brief in (('ru', JOB_RU_KNOWS_ACCOUNTING_DATED), ('en-to-ru', ACCOUNTING_EN_RU_NUMBERED)):
    for slug, sentence, gone in (
            ('date-and-metro', 'Изучив Закон о бухгалтерском учёте от 13 апреля 2016 года и метро, бухгалтер ведёт '
                               'книги.', ('метро',)),
            ('number-and-euro', 'Соблюдает Закон о бухгалтерском учёте № 404 и евро.', ('евро',))):
        CASES += [
            guard(f'laws-an-indeclinable-tail-after-a-named-laws-{slug}-{direction}-blank', BLANK, brief, 'ru',
                  sentence, gone=gone, translated=direction != 'ru'),
            gp(f'laws-an-indeclinable-tail-after-a-named-laws-{slug}-in-a-grounded-part-{direction}-blank', BLANK,
               brief, 'ru', sentence, gone=gone),
        ]
JOB_RU_KNOWS_TV = 'Составьте должностную инструкцию редактора. Он должен знать Закон о телевидении.'
TV_AND_RADIO = 'laws-an-indeclinable-tail-after-the-law-on-television-and-radio-ru-blank'
CASES += [
    guard(TV_AND_RADIO, BLANK, JOB_RU_KNOWS_TV, 'ru', 'Знает Закон о телевидении и радио.', gone=('радио',),
          translated=False),
    gp('laws-an-indeclinable-tail-after-the-law-on-television-and-radio-in-a-grounded-part-ru-blank', BLANK,
       JOB_RU_KNOWS_TV, 'ru', 'Знает Закон о телевидении и радио.', gone=('радио',)),
    body('laws-an-indeclinable-tail-after-the-law-on-television-and-radio-in-a-qualification-ru-blank', BLANK,
         'pdf.biz.lavozim_yoriqnomasi', JOB_RU_KNOWS_TV, 'ru', 'qualification', 'Знает Закон о телевидении и радио.',
         gone=('радио',)),
    guard('laws-an-indeclinable-tail-after-the-law-on-television-cinema-and-print-ru-blank', BLANK, JOB_RU_KNOWS_TV,
          'ru', 'Соблюдает Закон о телевидении, кино и печати.', gone=('кино',), translated=False),
]
# A translated paper's head noun "учёте" after a subject, no opening word: only the head noun decides.
INDECLINABLE_HEAD_TAILS = (
    ('and-radio', 'Бухгалтер знает Закон о бухгалтерском учёте и радио.', ('радио',)),
    ('casino-as-a-genitive', 'Бухгалтер соблюдает Закон о бухгалтерском учёте казино.', ('казино',)),
    ('in-lower-case-as-well-as-cinema', 'Бухгалтер знает закон о бухгалтерском учёте, а также кино.', ('кино',)),
    ('and-especially-metro', 'Работа ведётся согласно Закону о бухгалтерском учёте и особенно метро.', ('метро',)),
    ('and-euro', 'Бухгалтер руководствуется Законом о бухгалтерском учёте и евро.', ('евро',)),
    ('bureau-and-audit', 'Бухгалтер знает Закон о бухгалтерском учёте, бюро и аудите.', ('бюро',)),
    ('and-radio-capitalised', 'Бухгалтер знает Закон о бухгалтерском учёте и Радио.', ('Радио',)))
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU),
                         ('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU)):
    for slug, sentence, gone in INDECLINABLE_HEAD_TAILS:
        CASES += [
            guard(f'laws-a-translated-head-noun-before-an-indeclinable-tail-{slug}-{direction}-blank', BLANK, brief,
                  'ru', sentence, gone=gone, translated=True),
            gp(f'laws-a-translated-head-noun-before-an-indeclinable-tail-{slug}-in-a-grounded-part-{direction}-blank',
               BLANK, brief, 'ru', sentence, gone=gone),
        ]
    CASES.append(body(f'laws-a-translated-head-noun-before-an-indeclinable-tail-and-radio-in-a-qualification-'
                      f'{direction}-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', brief, 'ru', 'qualification',
                      INDECLINABLE_HEAD_TAILS[0][1], gone=('радио',)))
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU_NUMBERED), ('uz-to-ru', ACCOUNTING_UZ_RU_NUMBERED)):
    CASES.append(guard(f'laws-a-translated-head-noun-before-a-date-and-an-indeclinable-tail-{direction}-blank', BLANK,
                       brief, 'ru', 'Бухгалтер соблюдает Закон о бухгалтерском учёте от 13 апреля 2016 года и метро.',
                       gone=('метро',), translated=True))
# 28c1b69 keeps the customer's law before an adverb, a particle or a pronoun in -о, which the reading still passes over:
# one the lexicon holds or makes from an adjective ("досконально", "качественно"), of an adverb's shape
# ("неукоснительно", "ежеквартально"), or named ("что", "либо", "свято").
for slug, sentence in (
        ('thoroughly', 'Знает Закон о бухгалтерском учёте досконально.'),
        ('strictly-and-a-clause', 'Соблюдает Закон о бухгалтерском учёте неукоснительно и умеет вести книги.'),
        ('comma-which-lets', 'Знает Закон о бухгалтерском учёте, что позволяет вести книги.'),
        ('quarterly', 'Применяет Закон о бухгалтерском учёте ежеквартально.'),
        ('with-quality', 'Соблюдает Закон о бухгалтерском учёте качественно.'),
        ('and-on-time-a-clause', 'Знает Закон о бухгалтерском учёте и своевременно сдаёт отчёты.'),
        ('religiously', 'Соблюдает Закон о бухгалтерском учёте свято.'),
        ('namely-a-clause', 'Руководствуется Законом о бухгалтерском учёте, а именно ведёт книги.'),
        ('and-either-or', 'Знает Закон о бухгалтерском учёте и либо сам ведёт книги, либо проверяет их.'),
        ('that-is-a-clause', 'Соблюдает Закон о бухгалтерском учёте, т. е. ведёт книги точно.')):
    for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
        CASES.append(guard(f'laws-the-customers-law-before-an-adverb-in-o-{slug}-{direction}-keep', KEEP, brief, 'ru',
                           sentence))
for slug, sentence in (('thoroughly', 'Бухгалтер знает Закон о бухгалтерском учёте досконально.'),
                       ('strictly-and-a-clause', 'Бухгалтер соблюдает Закон о бухгалтерском учёте неукоснительно и '
                                                 'умеет вести книги.'),
                       ('comma-which-lets', 'Бухгалтер знает Закон о бухгалтерском учёте, что позволяет ему вести '
                                            'книги.')):
    for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU)):
        CASES.append(guard(f'laws-the-customers-translated-law-before-an-adverb-in-o-{slug}-{direction}-keep', KEEP,
                           brief, 'ru', sentence, translated=True))
# The customer's own law named with such a noun is theirs where no opening word stands before it.
JOB_RU_KNOWS_TV_AND_RADIO = 'Составьте должностную инструкцию редактора. Он должен знать Закон о телевидении и радио.'
CASES.append(guard('laws-the-customers-law-on-television-and-radio-ru-keep', KEEP, JOB_RU_KNOWS_TV_AND_RADIO, 'ru',
                   'Закон о телевидении и радио регулирует вещание.'))

# ---- What the reading costs against 28c1b69: the customer's own law named with such a noun after an opening word
# ("Знает Закон о телевидении и радио", their brief naming that law) reads as an invented tail after their "Закон о
# телевидении" does, so the opening word is the name's and blanks, as "Соблюдает Закон о бухгалтерском учёте и аудите"
# does under a brief naming that law.
CASES += [
    guard('laws-the-customers-law-on-television-and-radio-after-an-opening-word-ru-accepted_false_blank', ACCEPTED,
          JOB_RU_KNOWS_TV_AND_RADIO, 'ru', 'Знает Закон о телевидении и радио.', gone=('радио',), pair=TV_AND_RADIO),
    gp('laws-the-customers-law-on-television-and-radio-after-an-opening-word-in-a-grounded-part-ru-'
       'accepted_false_blank', ACCEPTED, JOB_RU_KNOWS_TV_AND_RADIO, 'ru', 'Знает Закон о телевидении и радио.',
       gone=('радио',), pair=TV_AND_RADIO),
]

# ---------------------------------------------------------------- the re-check of round 13 (pr78-r1), both ways
# Round 13 read a noun that keeps its form in every case as able to go on a law's name; the re-check found more such
# nouns read as unable to (p1: L1, L2, L3), and the keeps 28c1b69 has that the reading blanks (p2, p5). Each is pinned
# here under the briefs the re-check used.

# ---- A Russian clause after a comma or a semicolon (p5): a noun that keeps its form in every case opening it, its verb
# after it, "не" or one word between ("..., сальдо переносится на следующий период", "...; бюро ведёт учёт", "...,
# видео не является ..."). A list in a law's name joins its last word with "и", never a comma alone, so the name ended
# at the comma, as 28c1b69 read it; round 13 read the noun into the name and blanked the customer's law.
CLAUSE_AFTER_A_COMMA_RU = (
    ('balance-carried-over', 'Согласно Закону о бухгалтерском учёте, сальдо переносится на следующий период.'),
    ('balance-of-an-account', 'Согласно Закону о бухгалтерском учёте, сальдо счёта переносится на следующий период.'),
    ('a-bureau-keeps-books', 'Согласно Закону о бухгалтерском учёте, бюро ведёт учёт самостоятельно.'),
    ('a-semicolon-balance', 'Согласно Закону о бухгалтерском учёте; сальдо переносится на следующий период.'),
    ('net-assets', 'Согласно Закону о бухгалтерском учёте, нетто-активы рассчитываются ежегодно.'),
    ('a-photo-of-documents', 'Согласно Закону о бухгалтерском учёте, фото документов хранится в архиве.'),
    ('euro-recalculated', 'Согласно Закону о бухгалтерском учёте, евро пересчитывается по курсу.'),
    ('video-is-not', 'Согласно Закону о бухгалтерском учёте, видео не является первичным документом.'))
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence in CLAUSE_AFTER_A_COMMA_RU:
        CASES += [
            guard(f'laws-the-customers-law-before-an-indeclinable-opening-a-comma-clause-{slug}-{direction}-keep', KEEP,
                  brief, 'ru', sentence, translated=direction != 'ru'),
            gp(f'laws-the-customers-law-before-an-indeclinable-opening-a-comma-clause-{slug}-in-a-grounded-part-'
               f'{direction}-keep', KEEP, brief, 'ru', sentence),
        ]
    CASES.append(body(f'laws-the-customers-law-before-an-indeclinable-opening-a-comma-clause-balance-carried-over-in-'
                      f'a-report-{direction}-keep', KEEP, 'pdf.biz.hisobot', brief, 'ru', 'work_done',
                      CLAUSE_AFTER_A_COMMA_RU[0][1]))
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU),
                         ('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU)):
    for slug, sentence in (('balance-carried-over', 'Бухгалтер знает Закон о бухгалтерском учёте, сальдо переносит '
                                                    'вовремя.'),
                           ('a-semicolon-bureau', 'Бухгалтер применяет Закон о бухгалтерском учёте; бюро ведёт учёт '
                                                  'самостоятельно.')):
        CASES += [
            guard(f'laws-the-customers-translated-law-before-an-indeclinable-opening-a-comma-clause-{slug}-{direction}'
                  f'-keep', KEEP, brief, 'ru', sentence, translated=True),
            gp(f'laws-the-customers-translated-law-before-an-indeclinable-opening-a-comma-clause-{slug}-in-a-grounded-'
               f'part-{direction}-keep', KEEP, brief, 'ru', sentence),
        ]
for direction, brief in (('ru', JOB_RU_KNOWS_ACCOUNTING_DATED), ('en-to-ru', ACCOUNTING_EN_RU_NUMBERED)):
    CASES.append(guard(f'laws-the-customers-dated-law-before-an-indeclinable-opening-a-comma-clause-{direction}-keep',
                       KEEP, brief, 'ru', 'Знает Закон о бухгалтерском учёте от 13 апреля 2016 года № 404, сальдо '
                       'переносит вовремя.', translated=direction != 'ru'))
# The clause check reads no list, preposition or word in the name's case after the noun: the name goes on with it.
for slug, sentence, gone in (
        ('and-audit-before-a-verb', 'Согласно Закону о бухгалтерском учёте, сальдо и аудите регулируется отчётность.',
         ('сальдо',)),
        ('in-banks-before-a-verb', 'Согласно Закону о бухгалтерском учёте, бюро в банках регулирует отчётность.',
         ('бюро',)),
        ('of-credit-histories-and-audit', 'Согласно Закону о бухгалтерском учёте, бюро кредитных историй и аудите, '
                                          'бухгалтер ведёт книги.', ('бюро',))):
    for direction, brief in RUSSIAN_ACCOUNTING:
        CASES += [
            guard(f'laws-an-indeclinable-tail-in-a-list-before-a-verb-after-a-named-law-{slug}-{direction}-blank',
                  BLANK, brief, 'ru', sentence, gone=gone, translated=direction != 'ru'),
            gp(f'laws-an-indeclinable-tail-in-a-list-before-a-verb-after-a-named-law-{slug}-in-a-grounded-part-'
               f'{direction}-blank', BLANK, brief, 'ru', sentence, gone=gone),
        ]
# After "и" the noun before a verb may be the name's last word, the verb the sentence's ("Согласно Закону о телевидении
# и радио регулируется вещание"), so the opening word is the name's and blanks.
TV_AND_RADIO_BEFORE_A_VERB = 'laws-an-indeclinable-tail-before-a-verb-after-the-law-on-television-ru-blank'
CASES += [
    guard(TV_AND_RADIO_BEFORE_A_VERB, BLANK, JOB_RU_KNOWS_TV, 'ru',
          'Согласно Закону о телевидении и радио регулируется вещание.', gone=('радио',), translated=False),
    gp('laws-an-indeclinable-tail-before-a-verb-after-the-law-on-television-in-a-grounded-part-ru-blank', BLANK,
       JOB_RU_KNOWS_TV, 'ru', 'Согласно Закону о телевидении и радио регулируется вещание.', gone=('радио',)),
]
# Where the sentence has its verb before the law ("Знает Закон о ...", "Бухгалтер знает Закон о ..."), a verb after "и"
# and such a noun is another clause's, so 28c1b69's keep stays (an accepted false blank until the verb before was read).
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    CASES += [
        guard(f'laws-the-customers-law-before-an-indeclinable-opening-a-clause-after-and-{direction}-keep', KEEP, brief,
              'ru', 'Знает Закон о бухгалтерском учёте и сальдо переносит вовремя.', translated=direction != 'ru'),
        gp(f'laws-the-customers-law-before-an-indeclinable-opening-a-clause-after-and-in-a-grounded-part-{direction}-'
           f'keep', KEEP, brief, 'ru', 'Знает Закон о бухгалтерском учёте и сальдо переносит вовремя.'),
    ]
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU),
                         ('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU)):
    CASES.append(guard(f'laws-the-customers-translated-law-before-an-indeclinable-opening-a-clause-after-and-'
                       f'{direction}-keep', KEEP, brief, 'ru', 'Бухгалтер знает Закон о бухгалтерском учёте и сальдо '
                       'переносит вовремя.', translated=True))

# ---- An adverb, a participle or a particle in -о after the customer's law (p2): 28c1b69 passed it over as an adverb,
# round 13 read it as a noun that keeps its -о and blanked the customer's law. A short participle in -ано, -ено, -ято,
# -ыто, -уто or -ито ("гарантировано", "закрыто"), an adverb of an adjective in -йный, -йкий or -ивый ("постатейно",
# "стойко", "настойчиво"), and "будто", "надолго".
ADVERBS_IN_O_RU = (
    ('guaranteed', 'Согласно Закону о бухгалтерском учёте, гарантировано право на отпуск.'),
    ('persistently', 'Знает Закон о бухгалтерском учёте и настойчиво требует его соблюдения.'),
    ('steadfastly', 'Соблюдает Закон о бухгалтерском учёте и стойко отстаивает его нормы.'),
    ('as-if', 'Знает Закон о бухгалтерском учёте, будто сам его писал.'),
    ('for-long', 'Запоминает Закон о бухгалтерском учёте надолго.'),
    ('article-by-article', 'Применяет Закон о бухгалтерском учёте постатейно.'),
    ('without-accidents', 'Применяет Закон о бухгалтерском учёте безаварийно.'))
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence in ADVERBS_IN_O_RU:
        CASES += [
            guard(f'laws-the-customers-law-before-an-adverb-or-participle-in-o-{slug}-{direction}-keep', KEEP, brief,
                  'ru', sentence, translated=direction != 'ru'),
            gp(f'laws-the-customers-law-before-an-adverb-or-participle-in-o-{slug}-in-a-grounded-part-{direction}-keep',
               KEEP, brief, 'ru', sentence),
        ]
    CASES.append(body(f'laws-the-customers-law-before-an-adverb-or-participle-in-o-guaranteed-in-a-report-{direction}-'
                      f'keep', KEEP, 'pdf.biz.hisobot', brief, 'ru', 'work_done', ADVERBS_IN_O_RU[0][1]))
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU),
                         ('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU)):
    for slug, sentence in (('for-long', 'Бухгалтер запоминает Закон о бухгалтерском учёте надолго.'),
                           ('article-by-article', 'Бухгалтер применяет Закон о бухгалтерском учёте постатейно.'),
                           ('steadfastly', 'Бухгалтер соблюдает Закон о бухгалтерском учёте и стойко отстаивает его '
                                           'нормы.'),
                           ('persistently', 'Бухгалтер знает Закон о бухгалтерском учёте и настойчиво требует его '
                                            'соблюдения.')):
        CASES.append(guard(f'laws-the-customers-translated-law-before-an-adverb-or-participle-in-o-{slug}-{direction}-'
                           f'keep', KEEP, brief, 'ru', sentence, translated=True))
# The nouns those shapes would read as adverbs keep their -о in every case: the name goes on with them and blanks.
SHAPED_INDECLINABLE_TAILS_RU = (
    ('and-soprano', 'Знает Закон о бухгалтерском учёте и сопрано.', ('сопрано',)),
    ('piano-and-audit', 'Соблюдает Закон о бухгалтерском учёте, фортепиано и аудите.', ('фортепиано',)),
    ('as-well-as-a-circus', 'Согласно Закону о бухгалтерском учёте, а также шапито, бухгалтер ведёт книги.',
     ('шапито',)),
    ('and-especially-mojito', 'Руководствуется Законом о бухгалтерском учёте и особенно мохито.', ('мохито',)),
    ('and-americano', 'Знает Закон о бухгалтерском учёте и американо.', ('американо',)),
    ('guano-as-a-genitive', 'Знает Закон о бухгалтерском учёте гуано.', ('гуано',)),
    ('and-a-chateau', 'Изучив Закон о бухгалтерском учёте и шато, бухгалтер ведёт книги.', ('шато',)))
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence, gone in SHAPED_INDECLINABLE_TAILS_RU:
        CASES += [
            guard(f'laws-an-indeclinable-tail-of-an-adverbs-shape-after-a-named-law-{slug}-{direction}-blank', BLANK,
                  brief, 'ru', sentence, gone=gone, translated=direction != 'ru'),
            gp(f'laws-an-indeclinable-tail-of-an-adverbs-shape-after-a-named-law-{slug}-in-a-grounded-part-'
               f'{direction}-blank', BLANK, brief, 'ru', sentence, gone=gone),
        ]
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU),
                         ('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU)):
    CASES.append(guard(f'laws-a-translated-head-noun-before-an-indeclinable-tail-of-an-adverbs-shape-and-soprano-'
                       f'{direction}-blank', BLANK, brief, 'ru', 'Бухгалтер знает Закон о бухгалтерском учёте и '
                       'сопрано.', gone=('сопрано',), translated=True))

# ---- A Russian noun in -у, -ю, -а or -э that keeps its form in every case ("шоу", "меню", "интервью", "тату", "гуру",
# "буржуа", "каратэ", "алоэ", "рандеву") may go on a law's name as "радио" may (p1: L2, L2C): round 13 read only nouns
# in -о so, and ended the name before these, so an opening word was dropped or a translated head noun "учёте" passed as
# the customer's, and the invented tail went unread; c491da9 holds the opening word or the head noun and blanks.
INDECLINABLE_NON_O_TAILS_RU = (
    ('and-an-interview', 'Знает Закон о бухгалтерском учёте и интервью.', ('интервью',)),
    ('and-a-show', 'Соблюдает Закон о бухгалтерском учёте и шоу.', ('шоу',)),
    ('as-well-as-a-menu', 'Согласно Закону о бухгалтерском учёте, а также меню, бухгалтер ведёт книги.', ('меню',)),
    ('and-especially-tattoo', 'Руководствуется Законом о бухгалтерском учёте и особенно тату.', ('тату',)),
    ('a-guru-and-audit', 'Применяет Закон о бухгалтерском учёте, гуру и аудите.', ('гуру',)),
    ('and-of-course-karate', 'Знает Закон о бухгалтерском учёте и, конечно, каратэ.', ('каратэ',)),
    ('a-semicolon-and-aloe', 'Знает Закон о бухгалтерском учёте; алоэ.', ('алоэ',)),
    ('a-quoted-title-and-the-bourgeois', 'Знает Закон «О бухгалтерском учёте и буржуа».', ('буржуа',)),
    ('having-studied-and-a-rendezvous', 'Изучив Закон о бухгалтерском учёте и рандеву, бухгалтер ведёт книги.',
     ('рандеву',)),
    ('a-role-as-a-genitive', 'Знает Закон о бухгалтерском учёте амплуа.', ('амплуа',)))
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence, gone in INDECLINABLE_NON_O_TAILS_RU:
        CASES += [
            guard(f'laws-an-indeclinable-tail-in-u-a-or-e-after-a-named-law-{slug}-{direction}-blank', BLANK, brief,
                  'ru', sentence, gone=gone, translated=direction != 'ru'),
            gp(f'laws-an-indeclinable-tail-in-u-a-or-e-after-a-named-law-{slug}-in-a-grounded-part-{direction}-blank',
               BLANK, brief, 'ru', sentence, gone=gone),
        ]
    CASES.append(body(f'laws-an-indeclinable-tail-in-u-a-or-e-after-a-named-law-and-an-interview-in-a-qualification-'
                      f'{direction}-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', brief, 'ru', 'qualification',
                      INDECLINABLE_NON_O_TAILS_RU[0][1], gone=('интервью',)))
    CASES.append(body(f'laws-an-indeclinable-tail-in-u-a-or-e-after-a-named-law-as-well-as-an-interview-in-a-report-'
                      f'{direction}-blank', BLANK, 'pdf.biz.hisobot', brief, 'ru', 'work_done',
                      'Применяет Закон о бухгалтерском учёте, а также интервью.', gone=('интервью',)))
    if direction != 'ru':
        CASES.append(guard(f'laws-an-indeclinable-tail-in-u-a-or-e-after-a-named-law-and-a-show-capitalised-'
                           f'{direction}-blank', BLANK, brief, 'ru', 'Знает Закон о бухгалтерском учёте и Шоу.',
                           gone=('Шоу',), translated=True))
for direction, brief in (('ru', JOB_RU_KNOWS_ACCOUNTING_DATED), ('en-to-ru', ACCOUNTING_EN_RU_NUMBERED)):
    for slug, sentence in (('date-and-a-show', 'Знает Закон о бухгалтерском учёте от 13 апреля 2016 года и шоу.'),
                           ('number-and-a-show', 'Соблюдает Закон о бухгалтерском учёте № 404 и шоу.')):
        CASES += [
            guard(f'laws-an-indeclinable-tail-in-u-a-or-e-after-a-named-laws-{slug}-{direction}-blank', BLANK, brief,
                  'ru', sentence, gone=('шоу',), translated=direction != 'ru'),
            gp(f'laws-an-indeclinable-tail-in-u-a-or-e-after-a-named-laws-{slug}-in-a-grounded-part-{direction}-blank',
               BLANK, brief, 'ru', sentence, gone=('шоу',)),
        ]
COURSE_RU_TV = 'Курсовая работа о телевидении. Опирайся на Закон о телевидении.'
CASES += [
    guard('laws-an-indeclinable-tail-in-u-a-or-e-after-the-law-on-television-and-an-interview-ru-blank', BLANK,
          JOB_RU_KNOWS_TV, 'ru', 'Знает Закон о телевидении и интервью.', gone=('интервью',), translated=False),
    gp('laws-an-indeclinable-tail-in-u-a-or-e-after-the-law-on-television-and-an-interview-in-a-grounded-part-ru-blank',
       BLANK, JOB_RU_KNOWS_TV, 'ru', 'Знает Закон о телевидении и интервью.', gone=('интервью',)),
    body('laws-an-indeclinable-tail-in-u-a-or-e-after-the-law-on-television-and-a-show-in-a-course-paper-ru-blank',
         BLANK, 'pdf.kurs_ishi', COURSE_RU_TV, 'ru', 'relevance', 'Знает Закон о телевидении и шоу.', gone=('шоу',)),
]
INDECLINABLE_NON_O_HEAD_TAILS = (
    ('and-a-menu', 'Бухгалтер знает Закон о бухгалтерском учёте и меню.', ('меню',)),
    ('in-lower-case-as-well-as-an-interview', 'Бухгалтер знает закон о бухгалтерском учёте, а также интервью.',
     ('интервью',)),
    ('and-especially-tattoo', 'Работа ведётся согласно Закону о бухгалтерском учёте и особенно тату.', ('тату',)),
    ('a-guru-and-audit', 'Бухгалтер знает Закон о бухгалтерском учёте, гуру и аудите.', ('гуру',)),
    ('and-a-show-capitalised', 'Бухгалтер знает Закон о бухгалтерском учёте и Шоу.', ('Шоу',)))
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU),
                         ('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU)):
    for slug, sentence, gone in INDECLINABLE_NON_O_HEAD_TAILS:
        CASES += [
            guard(f'laws-a-translated-head-noun-before-an-indeclinable-tail-in-u-a-or-e-{slug}-{direction}-blank',
                  BLANK, brief, 'ru', sentence, gone=gone, translated=True),
            gp(f'laws-a-translated-head-noun-before-an-indeclinable-tail-in-u-a-or-e-{slug}-in-a-grounded-part-'
               f'{direction}-blank', BLANK, brief, 'ru', sentence, gone=gone),
        ]
    CASES.append(body(f'laws-a-translated-head-noun-before-an-indeclinable-tail-in-u-a-or-e-and-a-menu-in-a-'
                      f'qualification-{direction}-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', brief, 'ru',
                      'qualification', INDECLINABLE_NON_O_HEAD_TAILS[0][1], gone=('меню',)))
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU_NUMBERED), ('uz-to-ru', ACCOUNTING_UZ_RU_NUMBERED)):
    CASES.append(guard(f'laws-a-translated-head-noun-before-a-date-and-an-indeclinable-tail-in-u-a-or-e-{direction}-'
                       f'blank', BLANK, brief, 'ru', 'Бухгалтер соблюдает Закон о бухгалтерском учёте от 13 апреля '
                       '2016 года и шоу.', gone=('шоу',), translated=True))
# 28c1b69 keeps such a noun opening a comma clause, its verb after it; the clause check keeps it too.
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence in (('a-menu-agreed', 'Согласно Закону о бухгалтерском учёте, меню согласуется с руководством.'),
                           ('an-interview-held', 'Согласно Закону о бухгалтерском учёте, интервью проводится до '
                                                 'приёма на работу.')):
        CASES.append(guard(f'laws-the-customers-law-before-an-indeclinable-in-u-opening-a-comma-clause-{slug}-'
                           f'{direction}-keep', KEEP, brief, 'ru', sentence, translated=direction != 'ru'))
# After "и" such a noun before a verb reads as the name's last word where the sentence has no verb before the law
# ("Согласно Закону о телевидении и шоу регулируется вещание"); where it has one, the verb after is another clause's,
# and 28c1b69's keep stays (an accepted false blank until the verb before was read).
TV_AND_SHOW_BEFORE_A_VERB = 'laws-an-indeclinable-tail-in-u-before-a-verb-after-the-law-on-television-ru-blank'
CASES.append(guard(TV_AND_SHOW_BEFORE_A_VERB, BLANK, JOB_RU_KNOWS_TV, 'ru',
                   'Согласно Закону о телевидении и шоу регулируется вещание.', gone=('шоу',), translated=False))
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    CASES.append(guard(f'laws-the-customers-law-before-an-indeclinable-in-u-opening-a-clause-after-and-{direction}-'
                       f'keep', KEEP, brief, 'ru', 'Знает Закон о бухгалтерском учёте и меню согласует с руководством.',
                       translated=direction != 'ru'))

# ---- A rare loan in -о that `_ru_adverb` read as an adverb by its shape or the lexicon ("фиаско", "фламенко",
# "сирокко" of -Cко and -Cно; "бунгало", "мерло", "пуэбло", "пикколо" of -ло; "лего" of -его; "плато", "тако" of an
# adjective's stem) keeps its -о in every case (p1 L1, p4): round 13 passed it over, so the name ended before it, and
# "Знает Закон о бухгалтерском учёте и фиаско", "... учёте фиаско", "Согласно Закону о бухгалтерском учёте и плато,
# работа ведётся по плану" printed. A capitalised word in -о mid-sentence is no adverb either ("... и Осло").
RARE_LOAN_TAILS_RU = (
    ('and-a-fiasco', 'Знает Закон о бухгалтерском учёте и фиаско.', ('фиаско',)),
    ('a-fiasco-as-a-genitive', 'Знает Закон о бухгалтерском учёте фиаско.', ('фиаско',)),
    ('and-a-plateau-before-a-comma-clause', 'Согласно Закону о бухгалтерском учёте и плато, работа ведётся по плану.',
     ('плато',)),
    ('as-well-as-a-bungalow', 'Применяет Закон о бухгалтерском учёте, а также бунгало.', ('бунгало',)),
    ('and-especially-flamenco', 'Руководствуется Законом о бухгалтерском учёте и особенно фламенко.', ('фламенко',)),
    ('lego-and-audit', 'Соблюдает Закон о бухгалтерском учёте, лего и аудите.', ('лего',)),
    ('a-semicolon-and-merlot', 'Знает Закон о бухгалтерском учёте; мерло.', ('мерло',)),
    ('and-of-course-a-pueblo', 'Знает Закон о бухгалтерском учёте и, конечно, пуэбло.', ('пуэбло',)),
    ('having-studied-and-a-sirocco', 'Изучив Закон о бухгалтерском учёте и сирокко, бухгалтер ведёт книги.',
     ('сирокко',)),
    ('and-a-taco', 'Знает Закон о бухгалтерском учёте и тако.', ('тако',)))
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence, gone in RARE_LOAN_TAILS_RU:
        CASES += [
            guard(f'laws-a-rare-indeclinable-loan-after-a-named-law-{slug}-{direction}-blank', BLANK, brief, 'ru',
                  sentence, gone=gone, translated=direction != 'ru'),
            gp(f'laws-a-rare-indeclinable-loan-after-a-named-law-{slug}-in-a-grounded-part-{direction}-blank', BLANK,
               brief, 'ru', sentence, gone=gone),
        ]
    CASES.append(body(f'laws-a-rare-indeclinable-loan-after-a-named-law-and-a-plateau-in-a-report-{direction}-blank',
                      BLANK, 'pdf.biz.hisobot', brief, 'ru', 'work_done', RARE_LOAN_TAILS_RU[2][1], gone=('плато',)))
    CASES.append(body(f'laws-a-rare-indeclinable-loan-after-a-named-law-and-a-fiasco-in-a-qualification-{direction}-'
                      f'blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', brief, 'ru', 'qualification',
                      RARE_LOAN_TAILS_RU[0][1], gone=('фиаско',)))
for direction, brief in (('ru', JOB_RU_KNOWS_ACCOUNTING_DATED), ('en-to-ru', ACCOUNTING_EN_RU_NUMBERED)):
    CASES.append(guard(f'laws-a-rare-indeclinable-loan-after-a-named-laws-number-and-a-fiasco-{direction}-blank', BLANK,
                       brief, 'ru', 'Соблюдает Закон о бухгалтерском учёте № 404 и фиаско.', gone=('фиаско',),
                       translated=direction != 'ru'))
CASES.append(guard('laws-a-rare-indeclinable-loan-after-the-law-on-television-and-a-fiasco-ru-blank', BLANK,
                   JOB_RU_KNOWS_TV, 'ru', 'Знает Закон о телевидении и фиаско.', gone=('фиаско',), translated=False))
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU),
                         ('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU)):
    for slug, sentence, gone in (
            ('and-a-fiasco', 'Бухгалтер знает Закон о бухгалтерском учёте и фиаско.', ('фиаско',)),
            ('a-fiasco-as-a-genitive', 'Бухгалтер знает Закон о бухгалтерском учёте фиаско.', ('фиаско',)),
            ('as-well-as-a-plateau', 'Работа ведётся согласно Закону о бухгалтерском учёте, а также плато.',
             ('плато',)),
            ('and-oslo-capitalised', 'Бухгалтер знает Закон о бухгалтерском учёте и Осло.', ('Осло',)),
            ('and-flamenco-capitalised', 'Бухгалтер знает Закон о бухгалтерском учёте и Фламенко.', ('Фламенко',))):
        CASES += [
            guard(f'laws-a-translated-head-noun-before-a-rare-indeclinable-loan-{slug}-{direction}-blank', BLANK,
                  brief, 'ru', sentence, gone=gone, translated=True),
            gp(f'laws-a-translated-head-noun-before-a-rare-indeclinable-loan-{slug}-in-a-grounded-part-{direction}-'
               f'blank', BLANK, brief, 'ru', sentence, gone=gone),
        ]

# ---- A Russian compound with a hyphen after the customer's law is read by its last part (the fixer's own probe, the
# same family as p1): "интернет-торговле", "бизнес-планах", "пресс-службе" stand in the name's case and "ток-шоу",
# "ноу-хау", "кунг-фу" keep their form, so the name may go on with them. 28c1b69, eb8b05c and round 13 read the first
# part, which takes no case ("интернет", "бизнес", "ток"), ended the name before it, and "Знает Закон о бухгалтерском
# учёте и интернет-торговле" printed; c491da9 holds the opening word or the head noun and blanks.
COMPOUND_TAILS_RU = (
    ('and-internet-trade', 'Знает Закон о бухгалтерском учёте и интернет-торговле.', ('торговле',)),
    ('business-plans-and-audit', 'Применяет Закон о бухгалтерском учёте, бизнес-планах и аудите.', ('планах',)),
    ('as-well-as-a-press-office', 'Согласно Закону о бухгалтерском учёте, а также пресс-службе, бухгалтер ведёт '
                                  'книги.', ('службе',)),
    ('and-especially-online-tills', 'Руководствуется Законом о бухгалтерском учёте и особенно онлайн-кассах.',
     ('кассах',)),
    ('and-a-talk-show', 'Соблюдает Закон о бухгалтерском учёте и ток-шоу.', ('шоу',)),
    ('a-semicolon-and-know-how', 'Знает Закон о бухгалтерском учёте; ноу-хау.', ('хау',)),
    ('having-studied-and-kung-fu', 'Изучив Закон о бухгалтерском учёте и кунг-фу, бухгалтер ведёт книги.', ('фу',)))
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence, gone in COMPOUND_TAILS_RU:
        CASES += [
            guard(f'laws-a-hyphenated-tail-after-a-named-law-{slug}-{direction}-blank', BLANK, brief, 'ru', sentence,
                  gone=gone, translated=direction != 'ru'),
            gp(f'laws-a-hyphenated-tail-after-a-named-law-{slug}-in-a-grounded-part-{direction}-blank', BLANK, brief,
               'ru', sentence, gone=gone),
        ]
    CASES.append(body(f'laws-a-hyphenated-tail-after-a-named-law-and-internet-trade-in-a-qualification-{direction}-'
                      f'blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', brief, 'ru', 'qualification',
                      COMPOUND_TAILS_RU[0][1], gone=('торговле',)))
for direction, brief in (('ru', JOB_RU_KNOWS_ACCOUNTING_DATED), ('en-to-ru', ACCOUNTING_EN_RU_NUMBERED)):
    CASES.append(guard(f'laws-a-hyphenated-tail-after-a-named-laws-date-and-internet-trade-{direction}-blank', BLANK,
                       brief, 'ru', 'Знает Закон о бухгалтерском учёте от 13 апреля 2016 года и интернет-торговле.',
                       gone=('торговле',), translated=direction != 'ru'))
CASES.append(guard('laws-a-hyphenated-tail-after-the-law-on-television-and-a-talk-show-ru-blank', BLANK,
                   JOB_RU_KNOWS_TV, 'ru', 'Знает Закон о телевидении и ток-шоу.', gone=('шоу',), translated=False))
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU),
                         ('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU)):
    for slug, sentence, gone in (
            ('and-internet-trade', 'Бухгалтер знает Закон о бухгалтерском учёте и интернет-торговле.', ('торговле',)),
            ('as-well-as-business-processes', 'Работа ведётся согласно Закону о бухгалтерском учёте, а также '
                                              'бизнес-процессах.', ('процессах',)),
            ('and-internet-trade-capitalised', 'Бухгалтер знает Закон о бухгалтерском учёте и Интернет-торговле.',
             ('торговле',))):
        CASES += [
            guard(f'laws-a-translated-head-noun-before-a-hyphenated-tail-{slug}-{direction}-blank', BLANK, brief, 'ru',
                  sentence, gone=gone, translated=True),
            gp(f'laws-a-translated-head-noun-before-a-hyphenated-tail-{slug}-in-a-grounded-part-{direction}-blank',
               BLANK, brief, 'ru', sentence, gone=gone),
        ]
# A compound whose last part takes no case of a name is read as that part is: the name ended before it, as 28c1b69 reads
# "... и интернет-банкинг", "..., бизнес-план составляет сам", "..., нетто-активы рассчитываются ежегодно".
for slug, sentence in (('an-object', 'Знает Закон о бухгалтерском учёте и интернет-банкинг.'),
                       ('a-comma-clause', 'Знает Закон о бухгалтерском учёте, бизнес-план составляет сам.'),
                       ('a-clause-after-and', 'Соблюдает Закон о бухгалтерском учёте и кое-что знает об аудите.')):
    for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
        CASES.append(guard(f'laws-the-customers-law-before-a-hyphenated-word-out-of-the-names-case-{slug}-{direction}-'
                           f'keep', KEEP, brief, 'ru', sentence, translated=direction != 'ru'))

# ---- An abbreviation in capitals ("НДС", "ООО", "АО", "ИП", "МСФО", "НКО", "ПО", "УСН") stands unchanged in any case,
# so a law's name may go on with it (p1 L3, p4): 28c1b69, eb8b05c and round 13 read no word in capitals as able to, so
# the name ended before it, and "Знает Закон о бухгалтерском учёте и НДС", "Согласно Закону о бухгалтерском учёте и НДС,
# работа ведётся по плану" printed, or a translated head noun "учёте" passed as the customer's; c491da9 blanks.
ABBREVIATION_TAILS_RU = (
    ('and-vat', 'Знает Закон о бухгалтерском учёте и НДС.', ('НДС',)),
    ('and-vat-before-a-comma-clause', 'Согласно Закону о бухгалтерском учёте и НДС, работа ведётся по плану.',
     ('НДС',)),
    ('vat-and-audit', 'Знает Закон о бухгалтерском учёте, НДС и аудите.', ('НДС',)),
    ('as-well-as-an-llc', 'Соблюдает Закон о бухгалтерском учёте, а также ООО.', ('ООО',)),
    ('and-especially-ifrs', 'Руководствуется Законом о бухгалтерском учёте и особенно МСФО.', ('МСФО',)),
    ('a-semicolon-and-a-sole-trader', 'Знает Закон о бухгалтерском учёте; ИП.', ('ИП',)),
    ('having-studied-and-a-jsc', 'Изучив Закон о бухгалтерском учёте и АО, бухгалтер ведёт книги.', ('АО',)),
    ('and-of-course-the-simplified-tax', 'Знает Закон о бухгалтерском учёте и, конечно, УСН.', ('УСН',)),
    ('vat-as-a-genitive', 'Знает Закон о бухгалтерском учёте НДС.', ('НДС',)))
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence, gone in ABBREVIATION_TAILS_RU:
        CASES += [
            guard(f'laws-an-abbreviation-tail-after-a-named-law-{slug}-{direction}-blank', BLANK, brief, 'ru',
                  sentence, gone=gone, translated=direction != 'ru'),
            gp(f'laws-an-abbreviation-tail-after-a-named-law-{slug}-in-a-grounded-part-{direction}-blank', BLANK,
               brief, 'ru', sentence, gone=gone),
        ]
    CASES.append(body(f'laws-an-abbreviation-tail-after-a-named-law-and-vat-in-a-report-{direction}-blank', BLANK,
                      'pdf.biz.hisobot', brief, 'ru', 'work_done', ABBREVIATION_TAILS_RU[1][1], gone=('НДС',)))
    CASES.append(body(f'laws-an-abbreviation-tail-after-a-named-law-and-vat-in-a-qualification-{direction}-blank',
                      BLANK, 'pdf.biz.lavozim_yoriqnomasi', brief, 'ru', 'qualification', ABBREVIATION_TAILS_RU[0][1],
                      gone=('НДС',)))
for direction, brief in (('ru', JOB_RU_KNOWS_ACCOUNTING_DATED), ('en-to-ru', ACCOUNTING_EN_RU_NUMBERED)):
    for slug, sentence in (('date-and-vat', 'Знает Закон о бухгалтерском учёте от 13 апреля 2016 года и НДС.'),
                           ('number-and-vat', 'Соблюдает Закон о бухгалтерском учёте № 404 и НДС.')):
        CASES.append(guard(f'laws-an-abbreviation-tail-after-a-named-laws-{slug}-{direction}-blank', BLANK, brief,
                           'ru', sentence, gone=('НДС',), translated=direction != 'ru'))
CASES.append(guard('laws-an-abbreviation-tail-after-the-law-on-television-and-an-ngo-ru-blank', BLANK,
                   JOB_RU_KNOWS_TV, 'ru', 'Знает Закон о телевидении и НКО.', gone=('НКО',), translated=False))
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU),
                         ('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU)):
    for slug, sentence, gone in (
            ('and-vat', 'Бухгалтер знает Закон о бухгалтерском учёте и НДС.', ('НДС',)),
            ('as-well-as-ifrs', 'Работа ведётся согласно Закону о бухгалтерском учёте, а также МСФО.', ('МСФО',)),
            ('software-and-audit', 'Бухгалтер знает Закон о бухгалтерском учёте, ПО и аудите.', ('ПО',)),
            ('and-especially-the-simplified-tax', 'Бухгалтер знает Закон о бухгалтерском учёте и особенно УСН.',
             ('УСН',))):
        CASES += [
            guard(f'laws-a-translated-head-noun-before-an-abbreviation-tail-{slug}-{direction}-blank', BLANK, brief,
                  'ru', sentence, gone=gone, translated=True),
            gp(f'laws-a-translated-head-noun-before-an-abbreviation-tail-{slug}-in-a-grounded-part-{direction}-blank',
               BLANK, brief, 'ru', sentence, gone=gone),
        ]
    CASES.append(body(f'laws-a-translated-head-noun-before-an-abbreviation-tail-and-vat-in-a-qualification-'
                      f'{direction}-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', brief, 'ru', 'qualification',
                      'Бухгалтер знает Закон о бухгалтерском учёте и НДС.', gone=('НДС',)))
# 28c1b69 keeps an abbreviation opening a comma or semicolon clause, its verb after it (p3); the clause check keeps it.
ABBREVIATION_CLAUSES_RU = (
    ('an-llc-must-keep-books', 'Согласно Закону о бухгалтерском учёте, ООО обязано вести бухгалтерский учёт.'),
    ('a-sole-trader-may-not', 'Согласно Закону о бухгалтерском учёте, ИП может не вести бухгалтерский учёт.'),
    ('a-jsc-publishes', 'Согласно Закону о бухгалтерском учёте, АО публикует отчётность.'),
    ('vat-computed', 'Знает Закон о бухгалтерском учёте, НДС рассчитывает самостоятельно.'),
    ('vat-not-charged', 'Согласно Закону о бухгалтерском учёте, НДС не начисляется на экспорт.'),
    ('having-studied-an-llc-keeps', 'Изучив Закон о бухгалтерском учёте, ООО ведёт учёт самостоятельно.'),
    ('and-keeps-vat-records', 'Знает Закон о бухгалтерском учёте и ведёт учёт НДС.'))
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence in ABBREVIATION_CLAUSES_RU:
        CASES += [
            guard(f'laws-the-customers-law-before-an-abbreviation-opening-a-clause-{slug}-{direction}-keep', KEEP,
                  brief, 'ru', sentence, translated=direction != 'ru'),
            gp(f'laws-the-customers-law-before-an-abbreviation-opening-a-clause-{slug}-in-a-grounded-part-{direction}-'
               f'keep', KEEP, brief, 'ru', sentence),
        ]
    CASES.append(body(f'laws-the-customers-law-before-an-abbreviation-opening-a-clause-an-llc-must-keep-books-in-a-'
                      f'report-{direction}-keep', KEEP, 'pdf.biz.hisobot', brief, 'ru', 'work_done',
                      ABBREVIATION_CLAUSES_RU[0][1]))
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU),
                         ('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU)):
    CASES.append(guard(f'laws-the-customers-translated-law-before-an-abbreviation-opening-a-comma-clause-{direction}-'
                       f'keep', KEEP, brief, 'ru', 'Бухгалтер знает Закон о бухгалтерском учёте, НДС рассчитывает '
                       'самостоятельно.', translated=True))
# What the reading costs against 28c1b69, each where the same words in the same place may name a law: an abbreviation
# after "и" before a verb where the sentence has no verb before the law ("Согласно Закону о бухгалтерском учёте и НДС
# регулируется отчётность"; with one, "Соблюдает Закон ... и НДС начисляет вовремя" is kept), before a comma clause
# ("Знает Закон о бухгалтерском учёте и НДС, бухгалтер ведёт книги"), and two joined by "и" after a comma before a verb
# ("Согласно Закону о бухгалтерском учёте, НДС и ЕСП регулируется отчётность"): the customer's law before them blanks.
VAT_BEFORE_A_VERB = 'laws-an-abbreviation-tail-before-a-verb-after-a-named-law-ru-blank'
VAT_BEFORE_A_COMMA_CLAUSE = 'laws-an-abbreviation-tail-before-a-comma-clause-after-a-named-law-ru-blank'
VAT_AND_USP_BEFORE_A_VERB = 'laws-two-abbreviations-before-a-verb-after-a-named-law-ru-blank'
CASES += [
    guard(VAT_BEFORE_A_VERB, BLANK, JOB_RU_KNOWS_ACCOUNTING, 'ru',
          'Согласно Закону о бухгалтерском учёте и НДС регулируется отчётность.', gone=('НДС',), translated=False),
    guard(VAT_BEFORE_A_COMMA_CLAUSE, BLANK, JOB_RU_KNOWS_ACCOUNTING, 'ru',
          'Знает Закон о бухгалтерском учёте и НДС, бухгалтер ведёт книги.', gone=('НДС',), translated=False),
    guard(VAT_AND_USP_BEFORE_A_VERB, BLANK, JOB_RU_KNOWS_ACCOUNTING, 'ru',
          'Согласно Закону о бухгалтерском учёте, НДС и ЕСП регулируется отчётность.', gone=('НДС', 'ЕСП'),
          translated=False),
]
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence, gone, pair in (
            ('vat-before-a-comma-clause', 'Знает Закон о бухгалтерском учёте и НДС, применяет их на практике.',
             ('НДС',), VAT_BEFORE_A_COMMA_CLAUSE),
            ('two-abbreviations-opening-a-comma-clause', 'Согласно Закону о бухгалтерском учёте, ООО и ИП обязаны '
                                                         'вести учёт.', ('ООО', 'ИП'), VAT_AND_USP_BEFORE_A_VERB)):
        CASES += [
            guard(f'laws-the-customers-law-before-an-abbreviation-{slug}-{direction}-accepted_false_blank', ACCEPTED,
                  brief, 'ru', sentence, gone=gone, translated=direction != 'ru', pair=pair),
            gp(f'laws-the-customers-law-before-an-abbreviation-{slug}-in-a-grounded-part-{direction}-'
               f'accepted_false_blank', ACCEPTED, brief, 'ru', sentence, gone=gone, pair=pair),
        ]

# ---- A verb before the law (the fixer's own probe, r14 k1, k2): where the sentence has its finite verb before the
# law's stem ("Соблюдает Закон о ...", "Бухгалтер знает Закон о ...", "Работа ведётся согласно Закону о ..."), a verb
# after "и" and a noun that keeps its form or an abbreviation is another clause's, never the sentence's after a longer
# name, so 28c1b69's keep stays. With no finite verb before (a preposition, a gerund, an infinitive, a participle:
# "Согласно Закону о телевидении и радио регулируется вещание", "Изучив Закон о бухгалтерском учёте и НДС начисляет его
# вовремя"), or one of a subordinate clause ("Бухгалтер, который знает Закон ... и НДС регулирует учёт"), the noun may
# be the name's last word and blanks.
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence in (
            ('vat-charged', 'Соблюдает Закон о бухгалтерском учёте и НДС начисляет вовремя.'),
            ('a-sole-trader-advised', 'Соблюдает Закон о бухгалтерском учёте и ИП консультирует по учёту.'),
            ('a-balance-of-an-account', 'Знает Закон о бухгалтерском учёте и сальдо счёта переносит вовремя.'),
            ('as-well-as-a-dated-law', 'Знает Закон о бухгалтерском учёте, а также НДС начисляет вовремя.')):
        CASES += [
            guard(f'laws-the-customers-law-after-a-verb-before-a-clause-after-and-{slug}-{direction}-keep', KEEP,
                  brief, 'ru', sentence, translated=direction != 'ru'),
            gp(f'laws-the-customers-law-after-a-verb-before-a-clause-after-and-{slug}-in-a-grounded-part-{direction}-'
               f'keep', KEEP, brief, 'ru', sentence),
        ]
    CASES.append(body(f'laws-the-customers-law-after-a-verb-before-a-clause-after-and-vat-charged-in-a-report-'
                      f'{direction}-keep', KEEP, 'pdf.biz.hisobot', brief, 'ru', 'work_done',
                      'Соблюдает Закон о бухгалтерском учёте и НДС начисляет вовремя.'))
    for slug, sentence, gone in (
            ('having-studied', 'Изучив Закон о бухгалтерском учёте и НДС начисляет его вовремя.', ('НДС',)),
            ('to-observe', 'Соблюдать Закон о бухгалтерском учёте и НДС начислять вовремя.', ('НДС',)),
            ('according-to', 'Согласно Закону о бухгалтерском учёте и шоу проводится вовремя.', ('шоу',))):
        CASES.append(guard(f'laws-an-indeclinable-tail-before-a-verb-with-no-verb-before-the-law-{slug}-{direction}-'
                           f'blank', BLANK, brief, 'ru', sentence, gone=gone, translated=direction != 'ru'))
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU),
                         ('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU)):
    for slug, sentence in (('vat-charged', 'Бухгалтер знает Закон о бухгалтерском учёте и НДС начисляет вовремя.'),
                           ('work-done-and-vat-charged', 'Работа ведётся согласно Закону о бухгалтерском учёте и НДС '
                                                         'начисляется вовремя.')):
        CASES.append(guard(f'laws-the-customers-translated-law-after-a-verb-before-a-clause-after-and-{slug}-'
                           f'{direction}-keep', KEEP, brief, 'ru', sentence, translated=True))
    for slug, sentence, gone in (
            ('a-participle', 'Бухгалтер, знающий Закон о бухгалтерском учёте и НДС, начисляет его вовремя.', ('НДС',)),
            ('a-relative-clause', 'Бухгалтер, который знает Закон о бухгалтерском учёте и НДС регулирует учёт.',
             ('НДС',)),
            ('a-conditional-clause', 'Если знает Закон о бухгалтерском учёте и НДС регулирует учёт.', ('НДС',)),
            ('according-to', 'Согласно Закону о бухгалтерском учёте и НДС регулируется отчётность.', ('НДС',))):
        CASES.append(guard(f'laws-a-translated-head-noun-before-an-abbreviation-with-no-verb-before-the-law-{slug}-'
                           f'{direction}-blank', BLANK, brief, 'ru', sentence, gone=gone, translated=True))

# ---------------------------------------------------------------- the re-check of round 14 (pr78-r2), both ways
# Round 14 left three readings that print what c491da9 blanks (c1, c2, c3, c4), pinned here as blanks under the briefs
# the re-check used, with the keeps 28c1b69 has for the same readings.
REPORT_RU_ACCOUNTING = ('Напишите отчёт о работе бухгалтерии за 2025 год на русском языке. Отдел соблюдал Закон о '
                        'бухгалтерском учёте.')
REPORT_EN_RU_ACCOUNTING = ('Write a report on the accounting department for 2025 in Russian. The department followed '
                           'the Law on Accounting.')
REPORT_UZ_RU_ACCOUNTING = ('Buxgalteriya bo‘limining 2025 yildagi ishi haqida rus tilida hisobot yozing. Bo‘lim '
                           'Buxgalteriya hisobi to‘g‘risidagi qonunga amal qildi.')
REPORTS_ON_ACCOUNTING = (('ru', REPORT_RU_ACCOUNTING), ('en-to-ru', REPORT_EN_RU_ACCOUNTING),
                         ('uz-to-ru', REPORT_UZ_RU_ACCOUNTING))
COURSE_EN_RU_ACCOUNTING = ('Write a course paper in Russian on "Accounting in small firms". It must cover the Law on '
                           'Accounting.')
COURSE_UZ_RU_ACCOUNTING = ('Rus tilida "Kichik firmalarda buxgalteriya hisobi" mavzusida kurs ishi yozing. Unda '
                           'Buxgalteriya hisobi to‘g‘risidagi qonun yoritilsin.')
COURSES_ON_ACCOUNTING = (('en-to-ru', COURSE_EN_RU_ACCOUNTING), ('uz-to-ru', COURSE_UZ_RU_ACCOUNTING))

# ---- A noun that keeps its form in every case outside round 14's lists (c1): in -а after a vowel ("медиа",
# "мультимедиа"), in -у, -ю or -а ("авеню", "тофу", "хайку", "ню", "инженю", "бижу", "тирамису", "ультра"), "мумиё", and
# a loan in -о of an adverb's shape or an adjective's stem ("пиано", "франко", "инкогнито", "нано", "порно", "жиро").
# Round 14 read none as able to go on a law's name, or passed the loan in -о over as an adverb, so the name ended before
# it: an opening word was dropped or a translated head noun "учёте" passed as the customer's, and "Знает Закон о
# бухгалтерском учёте и медиа" printed; c491da9 holds the opening word or the head noun and blanks.
MORE_INDECLINABLE_TAILS_RU = (
    ('and-media', 'Знает Закон о бухгалтерском учёте и медиа.', ('медиа',)),
    ('media-and-audit', 'Знает Закон о бухгалтерском учёте, медиа и аудите.', ('медиа', 'аудите')),
    ('and-multimedia-before-a-comma-clause', 'Согласно Закону о бухгалтерском учёте и мультимедиа, бухгалтер ведёт '
                                             'книги.', ('мультимедиа',)),
    ('as-well-as-an-avenue', 'Применяет Закон о бухгалтерском учёте, а также авеню.', ('авеню',)),
    ('and-especially-tofu', 'Руководствуется Законом о бухгалтерском учёте и особенно тофу.', ('тофу',)),
    ('a-semicolon-haiku-and-taxes', 'Знает Закон о бухгалтерском учёте; хайку и налогах.', ('хайку',)),
    ('having-studied-and-an-ingenue', 'Изучив Закон о бухгалтерском учёте и инженю, бухгалтер ведёт книги.',
     ('инженю',)),
    ('and-a-nude', 'Соблюдает Закон о бухгалтерском учёте и ню.', ('ню',)),
    ('and-bijou', 'Знает Закон о бухгалтерском учёте и бижу.', ('бижу',)),
    ('and-tiramisu', 'Знает Закон о бухгалтерском учёте и тирамису.', ('тирамису',)),
    ('and-ultra', 'Знает Закон о бухгалтерском учёте и ультра.', ('ультра',)),
    ('and-mumiyo', 'Соблюдает Закон о бухгалтерском учёте и мумиё.', ('мумиё',)),
    ('and-a-piano', 'Знает Закон о бухгалтерском учёте и пиано.', ('пиано',)),
    ('and-franco-strictly', 'Знает Закон о бухгалтерском учёте и франко строго.', ('франко',)),
    ('as-well-as-incognito', 'Применяет Закон о бухгалтерском учёте, а также инкогнито.', ('инкогнито',)),
    ('and-of-course-nano', 'Знает Закон о бухгалтерском учёте и, конечно, нано.', ('нано',)),
    ('as-well-as-porn', 'Согласно Закону о бухгалтерском учёте, а также порно, бухгалтер ведёт книги.', ('порно',)),
    ('a-giro-as-a-genitive', 'Знает Закон о бухгалтерском учёте жиро.', ('жиро',)))
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence, gone in MORE_INDECLINABLE_TAILS_RU:
        CASES += [
            guard(f'laws-a-further-indeclinable-tail-after-a-named-law-{slug}-{direction}-blank', BLANK, brief, 'ru',
                  sentence, gone=gone, translated=direction != 'ru'),
            gp(f'laws-a-further-indeclinable-tail-after-a-named-law-{slug}-in-a-grounded-part-{direction}-blank',
               BLANK, brief, 'ru', sentence, gone=gone),
        ]
    CASES.append(body(f'laws-a-further-indeclinable-tail-after-a-named-law-and-media-in-a-qualification-{direction}-'
                      f'blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', brief, 'ru', 'qualification',
                      MORE_INDECLINABLE_TAILS_RU[0][1], gone=('медиа',)))
    if direction != 'ru':
        CASES.append(guard(f'laws-a-further-indeclinable-tail-after-a-named-law-and-media-capitalised-{direction}-'
                           f'blank', BLANK, brief, 'ru', 'Знает Закон о бухгалтерском учёте и Медиа.', gone=('Медиа',),
                           translated=True))
for direction, brief in (('ru', JOB_RU_KNOWS_ACCOUNTING_DATED), ('en-to-ru', ACCOUNTING_EN_RU_NUMBERED)):
    for slug, sentence, gone in (
            ('date-and-media', 'Знает Закон о бухгалтерском учёте от 13 апреля 2016 года и медиа.', ('медиа',)),
            ('number-and-tofu', 'Соблюдает Закон о бухгалтерском учёте № 404 и тофу.', ('тофу',)),
            ('number-and-a-piano', 'Соблюдает Закон о бухгалтерском учёте № 404 и пиано.', ('пиано',))):
        CASES += [
            guard(f'laws-a-further-indeclinable-tail-after-a-named-laws-{slug}-{direction}-blank', BLANK, brief, 'ru',
                  sentence, gone=gone, translated=direction != 'ru'),
            gp(f'laws-a-further-indeclinable-tail-after-a-named-laws-{slug}-in-a-grounded-part-{direction}-blank',
               BLANK, brief, 'ru', sentence, gone=gone),
        ]
CASES += [
    guard('laws-a-further-indeclinable-tail-after-the-law-on-television-and-media-ru-blank', BLANK, JOB_RU_KNOWS_TV,
          'ru', 'Знает Закон о телевидении и медиа.', gone=('медиа',), translated=False),
    gp('laws-a-further-indeclinable-tail-after-the-law-on-television-and-media-in-a-grounded-part-ru-blank', BLANK,
       JOB_RU_KNOWS_TV, 'ru', 'Знает Закон о телевидении и медиа.', gone=('медиа',)),
    body('laws-a-further-indeclinable-tail-after-the-law-on-television-and-media-in-a-qualification-ru-blank', BLANK,
         'pdf.biz.lavozim_yoriqnomasi', JOB_RU_KNOWS_TV, 'ru', 'qualification', 'Знает Закон о телевидении и медиа.',
         gone=('медиа',)),
    guard('laws-a-further-indeclinable-tail-after-the-law-on-television-multimedia-and-print-ru-blank', BLANK,
          JOB_RU_KNOWS_TV, 'ru', 'Соблюдает Закон о телевидении, мультимедиа и печати.', gone=('мультимедиа',),
          translated=False),
    guard('laws-a-further-indeclinable-tail-after-the-law-on-television-and-porn-ru-blank', BLANK, JOB_RU_KNOWS_TV,
          'ru', 'Изучив Закон о телевидении и порно, редактор готовит выпуск.', gone=('порно',), translated=False),
]
MORE_INDECLINABLE_HEAD_TAILS = (
    ('and-media', 'Бухгалтер знает Закон о бухгалтерском учёте и медиа.', ('медиа',)),
    ('in-lower-case-as-well-as-multimedia', 'Бухгалтер знает закон о бухгалтерском учёте, а также мультимедиа.',
     ('мультимедиа',)),
    ('and-especially-a-piano', 'Работа ведётся согласно Закону о бухгалтерском учёте и особенно пиано.', ('пиано',)),
    ('and-tofu', 'Бухгалтер руководствуется Законом о бухгалтерском учёте и тофу.', ('тофу',)),
    ('and-mumiyo', 'Бухгалтер знает Закон о бухгалтерском учёте и мумиё.', ('мумиё',)),
    ('and-franco', 'Бухгалтер знает Закон о бухгалтерском учёте и франко.', ('франко',)),
    ('and-media-capitalised', 'Бухгалтер знает Закон о бухгалтерском учёте и Медиа.', ('Медиа',)))
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU),
                         ('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU)):
    for slug, sentence, gone in MORE_INDECLINABLE_HEAD_TAILS:
        CASES += [
            guard(f'laws-a-translated-head-noun-before-a-further-indeclinable-tail-{slug}-{direction}-blank', BLANK,
                  brief, 'ru', sentence, gone=gone, translated=True),
            gp(f'laws-a-translated-head-noun-before-a-further-indeclinable-tail-{slug}-in-a-grounded-part-'
               f'{direction}-blank', BLANK, brief, 'ru', sentence, gone=gone),
        ]
    CASES.append(body(f'laws-a-translated-head-noun-before-a-further-indeclinable-tail-and-media-in-a-qualification-'
                      f'{direction}-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', brief, 'ru', 'qualification',
                      MORE_INDECLINABLE_HEAD_TAILS[0][1], gone=('медиа',)))
# End to end on a report's work done and a course paper's relevance (c3); a Russian paper's law after its subject, no
# opening word, is read by the translated head noun alone (in a Russian brief c491da9 prints it too).
for direction, brief in REPORTS_ON_ACCOUNTING:
    for slug, sentence, gone in (
            ('and-media', 'Отдел соблюдал Закон о бухгалтерском учёте и медиа.', ('медиа',)),
            ('and-media-before-a-comma-clause', 'Согласно Закону о бухгалтерском учёте и медиа, отдел вёл книги.',
             ('медиа',)),
            ('and-multimedia', 'Отдел вёл книги согласно Закону о бухгалтерском учёте и мультимедиа.',
             ('мультимедиа',))):
        if direction == 'ru' and not sentence.startswith('Согласно'):
            continue
        CASES.append(body(f'laws-a-further-indeclinable-tail-after-a-named-law-{slug}-in-a-report-{direction}-blank',
                          BLANK, 'pdf.biz.hisobot', brief, 'ru', 'work_done', sentence, gone=gone))
for direction, brief in COURSES_ON_ACCOUNTING:
    CASES.append(body(f'laws-a-further-indeclinable-tail-after-a-named-law-and-media-in-a-course-paper-{direction}-'
                      f'blank', BLANK, 'pdf.kurs_ishi', brief, 'ru', 'relevance',
                      'Согласно Закону о бухгалтерском учёте и медиа, отдел вёл книги.', gone=('медиа',)))

# ---- A particle after a hyphen ("аудите-то", "налогах-таки", "аудиторской-то деятельности", "аудите-ка", c2 C, c3):
# round 14 read the compound by its last part, the particle, which cannot go on a law's name, so the name ended before
# the word in its case, an opening word was dropped or a translated head noun passed as the customer's, and "Знает Закон
# о бухгалтерском учёте и аудите-то" printed; c491da9 blanks. The part before the particle says.
PARTICLE_COMPOUND_TAILS_RU = (
    ('and-audit-to', 'Знает Закон о бухгалтерском учёте и аудите-то.', ('аудите',)),
    ('audit-to-and-taxes', 'Согласно Закону о бухгалтерском учёте, аудите-то и налогах.', ('аудите',)),
    ('and-auditing-to-activity', 'Изучив Закон о бухгалтерском учёте и аудиторской-то деятельности.',
     ('аудиторской',)),
    ('and-taxes-to', 'Знает Закон о бухгалтерском учёте и налогах-то.', ('налогах',)),
    ('and-audit-ka', 'Знает Закон о бухгалтерском учёте и аудите-ка.', ('аудите',)),
    ('and-audit-taki', 'Соблюдает Закон о бухгалтерском учёте и аудите-таки.', ('аудите',)),
    ('as-well-as-audit-de', 'Применяет Закон о бухгалтерском учёте, а также аудите-де.', ('аудите',)),
    ('and-especially-audit-s', 'Руководствуется Законом о бухгалтерском учёте и особенно аудите-с.', ('аудите',)),
    ('and-media-to', 'Знает Закон о бухгалтерском учёте и медиа-то.', ('медиа',)))
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence, gone in PARTICLE_COMPOUND_TAILS_RU:
        CASES += [
            guard(f'laws-a-particle-after-a-hyphen-in-a-tail-after-a-named-law-{slug}-{direction}-blank', BLANK, brief,
                  'ru', sentence, gone=gone, translated=direction != 'ru'),
            gp(f'laws-a-particle-after-a-hyphen-in-a-tail-after-a-named-law-{slug}-in-a-grounded-part-{direction}-'
               f'blank', BLANK, brief, 'ru', sentence, gone=gone),
        ]
    CASES.append(body(f'laws-a-particle-after-a-hyphen-in-a-tail-after-a-named-law-and-audit-to-in-a-qualification-'
                      f'{direction}-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', brief, 'ru', 'qualification',
                      PARTICLE_COMPOUND_TAILS_RU[0][1], gone=('аудите',)))
for direction, brief in REPORTS_ON_ACCOUNTING:
    CASES.append(body(f'laws-a-particle-after-a-hyphen-in-a-tail-after-a-named-law-and-audit-to-in-a-report-'
                      f'{direction}-blank', BLANK, 'pdf.biz.hisobot', brief, 'ru', 'work_done',
                      'Согласно Закону о бухгалтерском учёте и аудите-то, отдел вёл книги.', gone=('аудите',)))
for direction, brief in (('ru', JOB_RU_KNOWS_ACCOUNTING_DATED), ('en-to-ru', ACCOUNTING_EN_RU_NUMBERED)):
    CASES.append(guard(f'laws-a-particle-after-a-hyphen-in-a-tail-after-a-named-laws-date-and-audit-to-{direction}-'
                       f'blank', BLANK, brief, 'ru', 'Знает Закон о бухгалтерском учёте от 13 апреля 2016 года и '
                       'аудите-то.', gone=('аудите',), translated=direction != 'ru'))
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU),
                         ('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU)):
    for slug, sentence, gone in (
            ('and-audit-to', 'Бухгалтер знает Закон о бухгалтерском учёте и аудите-то.', ('аудите',)),
            ('as-well-as-taxes-taki', 'Работа ведётся согласно Закону о бухгалтерском учёте, а также налогах-таки.',
             ('налогах',))):
        CASES += [
            guard(f'laws-a-translated-head-noun-before-a-particle-after-a-hyphen-{slug}-{direction}-blank', BLANK,
                  brief, 'ru', sentence, gone=gone, translated=True),
            gp(f'laws-a-translated-head-noun-before-a-particle-after-a-hyphen-{slug}-in-a-grounded-part-{direction}-'
               f'blank', BLANK, brief, 'ru', sentence, gone=gone),
        ]
# The particle's word decides where it cannot go on the name: an adverb or a pronoun before it ("... и когда-то
# применял его", "... и как-то применяет его", "... и кое-что об аудите"); 28c1b69 keeps these.
for slug, sentence in (('and-once-applied-it', 'Знает Закон о бухгалтерском учёте и когда-то применял его.'),
                       ('and-somehow-applies-it', 'Соблюдает Закон о бухгалтерском учёте и как-то применяет его.'),
                       ('and-something-of-audit', 'Знает Закон о бухгалтерском учёте и кое-что об аудите.')):
    for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
        CASES.append(guard(f'laws-the-customers-law-before-a-pronoun-or-adverb-with-a-particle-{slug}-{direction}-keep',
                           KEEP, brief, 'ru', sentence, translated=direction != 'ru'))

# ---- A verb before the law that is not the law's sentence's (c2 A, c3, c4): round 14 walked back from the law's stem
# past "и" and a dash to the verb of an earlier conjunct or clause ("Бухгалтер знает своё дело и Закон о ...",
# "Бухгалтер составляет отчёты — Закон о ..."), and read a noun in -ит or -ли as a finite verb ("Аудит Закона о ...",
# "Лимит по Закону о ...", "Показатели согласно Закону о ..."), so "и" with a noun that keeps its form and a verb after
# the name read as another clause, and the invented tail of a law that opens its own conjunct or clause printed
# ("Бухгалтер знает своё дело и Закон о бухгалтерском учёте и казино не нарушает"); c491da9 blanks. The walk stops
# at "и", "а", "но" or "или" before a verb and at a dash, and a form in -ит, -ят, -ите or -ли counts as a verb only
# where the lexicon holds its infinitive, never as the capitalised word opening the sentence.
CONJUNCT_LAW_TAILS_RU = (
    ('knows-his-job-and-the-law-and-a-casino', 'Бухгалтер знает своё дело и Закон о бухгалтерском учёте и казино не '
                                               'нарушает.', ('казино',)),
    ('knows-his-job-and-the-law-and-software', 'Бухгалтер знает своё дело и Закон о бухгалтерском учёте и ПО '
                                               'выполняет.', ('ПО',)),
    ('works-honestly-and-under-the-law-and-radio', 'Бухгалтер работает честно и согласно Закону о бухгалтерском учёте '
                                                   'и радио не составляет отчёты.', ('радио',)),
    ('reports-and-by-the-law-and-vat', 'Бухгалтер составляет отчёты и по Закону о бухгалтерском учёте и НДС '
                                       'отчитывается.', ('НДС',)),
    ('a-dash-and-a-casino', 'Бухгалтер составляет отчёты — Закон о бухгалтерском учёте и казино требует этого.',
     ('казино',)),
    ('a-dash-and-vat', 'Отдел знает своё дело — Закон о бухгалтерском учёте и НДС не запрещает этого.', ('НДС',)),
    ('an-en-dash-and-radio', 'Бухгалтер составляет отчёты – Закон о бухгалтерском учёте и радио требует этого.',
     ('радио',)),
    ('a-spaced-hyphen-and-a-show', 'Бухгалтер составляет отчёты - Закон о бухгалтерском учёте и шоу требует этого.',
     ('шоу',)),
    ('an-audit-by-the-law-and-radio', 'Аудит по Закону о бухгалтерском учёте и радио не превышает нормы.',
     ('радио',)),
    ('a-limit-under-the-law-and-a-casino', 'Лимит согласно Закону о бухгалтерском учёте и казино регулируется '
                                           'отдельно.', ('казино',)),
    ('a-credit-by-the-law-and-a-show', 'Кредит по Закону о бухгалтерском учёте и шоу регулируется отдельно.',
     ('шоу',)),
    ('an-audit-under-the-law-and-ifrs', 'Аудит согласно Закону о бухгалтерском учёте и МСФО проводится ежегодно.',
     ('МСФО',)),
    ('indicators-under-the-law-and-vat', 'Показатели согласно Закону о бухгалтерском учёте и НДС рассчитываются '
                                         'ежегодно.', ('НДС',)))
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU),
                         ('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU)):
    for slug, sentence, gone in CONJUNCT_LAW_TAILS_RU:
        CASES += [
            guard(f'laws-a-translated-head-noun-before-a-tail-with-no-verb-of-its-own-before-the-law-{slug}-'
                  f'{direction}-blank', BLANK, brief, 'ru', sentence, gone=gone, translated=True),
            gp(f'laws-a-translated-head-noun-before-a-tail-with-no-verb-of-its-own-before-the-law-{slug}-in-a-'
               f'grounded-part-{direction}-blank', BLANK, brief, 'ru', sentence, gone=gone),
        ]
    CASES.append(body(f'laws-a-translated-head-noun-before-a-tail-with-no-verb-of-its-own-before-the-law-knows-his-job-'
                      f'and-the-law-and-a-casino-in-a-qualification-{direction}-blank', BLANK,
                      'pdf.biz.lavozim_yoriqnomasi', brief, 'ru', 'qualification', CONJUNCT_LAW_TAILS_RU[0][1],
                      gone=('казино',)))
# A noun in -ит opening the sentence before the law's stem (c4): an opening word of the name, held as the customer's.
NOUN_OPENER_TAILS_RU = (
    ('an-audit-and-radio', 'Аудит Закона о бухгалтерском учёте и радио не превышает нормы.', ('радио',)),
    ('a-limit-and-a-casino', 'Лимит Закона о бухгалтерском учёте и казино регулируется отдельно.', ('казино',)),
    ('a-transit-and-media', 'Транзит Закона о бухгалтерском учёте и медиа проводится ежегодно.', ('медиа',)))
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence, gone in NOUN_OPENER_TAILS_RU:
        CASES += [
            guard(f'laws-a-noun-in-it-opening-a-sentence-before-a-named-law-and-a-tail-{slug}-{direction}-blank', BLANK,
                  brief, 'ru', sentence, gone=gone, translated=direction != 'ru'),
            gp(f'laws-a-noun-in-it-opening-a-sentence-before-a-named-law-and-a-tail-{slug}-in-a-grounded-part-'
               f'{direction}-blank', BLANK, brief, 'ru', sentence, gone=gone),
        ]
# End to end on a report's work done and a course paper's relevance (c3); in a Russian brief only an opening word reads.
for direction, brief in REPORTS_ON_ACCOUNTING:
    for slug, sentence, gone in (
            ('knows-its-job-and-the-law-and-a-casino', 'Отдел знает своё дело и Закон о бухгалтерском учёте и казино '
                                                       'не нарушает.', ('казино',)),
            ('a-dash-and-vat', 'Отдел знает своё дело — Закон о бухгалтерском учёте и НДС не запрещает этого.',
             ('НДС',)),
            ('a-limit-by-the-law-and-radio', 'Лимит по Закону о бухгалтерском учёте и радио не превышает нормы.',
             ('радио',)),
            ('an-audit-of-the-law-and-radio', 'Аудит Закона о бухгалтерском учёте и радио не превышает нормы.',
             ('радио',))):
        if direction == 'ru' and not sentence.startswith('Аудит Закона'):
            continue
        CASES.append(body(f'laws-a-tail-with-no-verb-of-its-own-before-a-named-law-{slug}-in-a-report-{direction}-'
                          f'blank', BLANK, 'pdf.biz.hisobot', brief, 'ru', 'work_done', sentence, gone=gone))
for direction, brief in COURSES_ON_ACCOUNTING:
    CASES.append(body(f'laws-a-tail-with-no-verb-of-its-own-before-a-named-law-a-credit-by-the-law-and-a-show-in-a-'
                      f'course-paper-{direction}-blank', BLANK, 'pdf.kurs_ishi', brief, 'ru', 'relevance',
                      'Кредит по Закону о бухгалтерском учёте и шоу регулируется отдельно.', gone=('шоу',)))
# 28c1b69's keeps the reading holds: the law's sentence's own verb before it, two verbs joined by "и" ("Бухгалтер знает
# и соблюдает Закон о ..."), a verb in -ит whose infinitive the lexicon holds ("следит" of "следить"), and the name
# ending at the sentence's verb after a noun in -ит or -ли opening it ("Аудит Закона о ... проводится ежегодно").
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU),
                         ('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU)):
    for slug, sentence in (
            ('two-verbs-joined', 'Бухгалтер знает и соблюдает Закон о бухгалтерском учёте и НДС начисляет вовремя.'),
            ('a-verb-in-it', 'Бухгалтер следит за отчётностью согласно Закону о бухгалтерском учёте и НДС начисляет '
                             'вовремя.'),
            ('a-dash-before-the-verb', 'Он опытный специалист — бухгалтер соблюдает Закон о бухгалтерском учёте и НДС '
                                       'начисляет вовремя.')):
        CASES.append(guard(f'laws-the-customers-translated-law-after-its-sentences-verb-before-a-clause-after-and-'
                           f'{slug}-{direction}-keep', KEEP, brief, 'ru', sentence, translated=True))
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence in (('an-audit-held-yearly', 'Аудит Закона о бухгалтерском учёте проводится ежегодно.'),
                           ('indicators-computed-yearly', 'Показатели согласно Закону о бухгалтерском учёте '
                                                          'рассчитываются ежегодно.')):
        CASES.append(guard(f'laws-the-customers-law-after-a-noun-in-it-or-li-opening-a-sentence-{slug}-{direction}-'
                           f'keep', KEEP, brief, 'ru', sentence, translated=direction != 'ru'))

# ---- An adverb in -о neither the lexicon nor an adverb's shape gives (k2, the fixer's k1): "не" before an adverb that
# is one ("неплохо", "нехорошо", "нечасто", "нескоро", "нетвёрдо") and the adverbs of adjectives the lexicon lacks
# ("трезво", "здраво", "храбро", "резво", "шустро", "наскоро", "хмуро", "лихо"). Round 14 read them as nouns that keep
# their -о and blanked the customer's law; 28c1b69 passed every lower-case word in -о over and keeps them.
UNREAD_ADVERBS_IN_O_RU = (
    ('not-badly', 'Знает Закон о бухгалтерском учёте неплохо.'),
    ('not-badly-and-a-clause', 'Соблюдает Закон о бухгалтерском учёте неплохо и умеет вести книги.'),
    ('not-often-a-comma-clause', 'Знает Закон о бухгалтерском учёте, нечасто применяет его на практике.'),
    ('not-firmly', 'Изучив Закон о бухгалтерском учёте нетвёрдо, бухгалтер ведёт книги.'),
    ('soberly', 'Применяет Закон о бухгалтерском учёте трезво.'),
    ('sensibly-and-a-clause', 'Знает Закон о бухгалтерском учёте и здраво применяет его.'),
    ('bravely', 'Соблюдает Закон о бухгалтерском учёте храбро.'),
    ('hastily', 'Изучив Закон о бухгалтерском учёте наскоро, бухгалтер ведёт книги.'),
    ('glumly-and-a-clause', 'Соблюдает Закон о бухгалтерском учёте хмуро и умеет вести книги.'))
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence in UNREAD_ADVERBS_IN_O_RU:
        CASES += [
            guard(f'laws-the-customers-law-before-an-adverb-in-o-the-lexicon-lacks-{slug}-{direction}-keep', KEEP,
                  brief, 'ru', sentence, translated=direction != 'ru'),
            gp(f'laws-the-customers-law-before-an-adverb-in-o-the-lexicon-lacks-{slug}-in-a-grounded-part-{direction}-'
               f'keep', KEEP, brief, 'ru', sentence),
        ]
    CASES.append(body(f'laws-the-customers-law-before-an-adverb-in-o-the-lexicon-lacks-not-badly-and-a-clause-in-a-'
                      f'report-{direction}-keep', KEEP, 'pdf.biz.hisobot', brief, 'ru', 'work_done',
                      UNREAD_ADVERBS_IN_O_RU[1][1]))
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU),
                         ('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU)):
    for slug, sentence in (('not-badly', 'Бухгалтер знает Закон о бухгалтерском учёте неплохо.'),
                           ('soberly-and-a-clause', 'Бухгалтер применяет Закон о бухгалтерском учёте трезво и ведёт '
                                                    'книги.')):
        CASES.append(guard(f'laws-the-customers-translated-law-before-an-adverb-in-o-the-lexicon-lacks-{slug}-'
                           f'{direction}-keep', KEEP, brief, 'ru', sentence, translated=True))
# "не" before a noun that keeps its -о makes no adverb: the name goes on with "нетто" and blanks.
for direction, brief in RUSSIAN_ACCOUNTING:
    CASES.append(guard(f'laws-an-indeclinable-tail-in-ne-after-a-named-law-and-net-{direction}-blank', BLANK, brief,
                       'ru', 'Знает Закон о бухгалтерском учёте и нетто.', gone=('нетто',),
                       translated=direction != 'ru'))

# ---- "как" after the subject before the law's verb ("Бухгалтер как специалист знает Закон о ...", k2): a role, no
# subordinate clause, so the verb is the law's sentence's and "и НДС начисляет вовремя" another clause, as 28c1b69
# keeps it; round 14 read every "как" as opening a clause and blanked. "так как", "после того как" open one still.
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU),
                         ('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU)):
    for slug, sentence in (('knows-and-vat-charged', 'Бухгалтер как специалист знает Закон о бухгалтерском учёте и НДС '
                                                     'начисляет вовремя.'),
                           ('observes-and-balance-carried', 'Бухгалтер как специалист соблюдает Закон о бухгалтерском '
                                                            'учёте и сальдо переносит вовремя.')):
        CASES.append(guard(f'laws-the-customers-translated-law-after-a-role-with-kak-before-a-clause-after-and-{slug}-'
                           f'{direction}-keep', KEEP, brief, 'ru', sentence, translated=True))
    for slug, sentence in (('since', 'Так как бухгалтер знает Закон о бухгалтерском учёте и НДС регулирует учёт.'),
                           ('after', 'После того как бухгалтер изучает Закон о бухгалтерском учёте и НДС регулирует '
                                     'учёт.')):
        CASES.append(guard(f'laws-a-translated-head-noun-before-an-abbreviation-in-a-clause-with-kak-{slug}-'
                           f'{direction}-blank', BLANK, brief, 'ru', sentence, gone=('НДС',), translated=True))

# ---- What the reading costs against 28c1b69 (k1, the re-check's own keeps): the customer's law after an opening word
# or a translated head noun, then an abbreviation or a noun that keeps its form with nothing that ends the name ("...
# учёте и МСФО", "..., НСБУ и МСФО", "... и сальдо по счетам", "... и евро как валюту учёта", "... и бюро кредитных
# историй"). The same words in the same place name an invented law ("... учёте и НДС", "... учёте и радио"), so the
# opening word or the head noun is the name's and blanks, as round 14 has it; 28c1b69 read none of them as able to go on
# the name and kept them.
OPENER_COSTS_RU = (
    ('ifrs-at-the-end', 'Знает Закон о бухгалтерском учёте и МСФО.', ('МСФО',),
     'laws-an-abbreviation-tail-after-a-named-law-and-vat-ru-blank'),
    ('the-tax-code-of-uzbekistan', 'Соблюдает Закон о бухгалтерском учёте и НК РУз.', ('НК',),
     'laws-an-abbreviation-tail-after-a-named-law-and-vat-ru-blank'),
    ('an-llc', 'Применяет Закон о бухгалтерском учёте и ООО.', ('ООО',),
     'laws-an-abbreviation-tail-after-a-named-law-and-vat-ru-blank'),
    ('two-standards-in-a-list', 'Знает Закон о бухгалтерском учёте, НСБУ и МСФО.', ('НСБУ', 'МСФО'),
     'laws-an-abbreviation-tail-after-a-named-law-vat-and-audit-ru-blank'),
    ('a-balance-of-accounts', 'Знает Закон о бухгалтерском учёте и сальдо по счетам.', ('сальдо',),
     'laws-an-indeclinable-tail-after-a-named-law-and-balance-ru-blank'),
    ('balances-and-turnovers', 'Применяет Закон о бухгалтерском учёте, сальдо и обороты по счетам.', ('сальдо',),
     'laws-an-indeclinable-tail-after-a-named-law-bureau-and-audit-ru-blank'),
    ('the-euro-as-a-currency', 'Знает Закон о бухгалтерском учёте и евро как валюту учёта.', ('евро',),
     'laws-an-indeclinable-tail-after-a-named-law-and-radio-ru-blank'),
    ('a-credit-bureau', 'Руководствуется Законом о бухгалтерском учёте и бюро кредитных историй.', ('бюро',),
     'laws-an-indeclinable-tail-in-a-list-before-a-verb-after-a-named-law-of-credit-histories-and-audit-ru-blank'),
    ('and-video', 'Знает Закон о бухгалтерском учёте и видео.', ('видео',),
     'laws-an-indeclinable-tail-after-a-named-law-and-radio-ru-blank'),
    ('ifrs-before-a-comma-clause', 'Согласно Закону о бухгалтерском учёте и МСФО, бухгалтер составляет отчётность.',
     ('МСФО',), 'laws-an-abbreviation-tail-after-a-named-law-and-vat-before-a-comma-clause-ru-blank'),
    ('an-adverb-and-vat-before-a-verb', 'Согласно Закону о бухгалтерском учёте хорошо и НДС начисляет верно, бухгалтер '
                                        'составляет отчётность.', ('НДС',), VAT_BEFORE_A_VERB))
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence, gone, pair in OPENER_COSTS_RU:
        CASES.append(guard(f'laws-the-customers-law-before-an-abbreviation-or-indeclinable-{slug}-{direction}-'
                           f'accepted_false_blank', ACCEPTED, brief, 'ru', sentence, gone=gone,
                           translated=direction != 'ru', pair=pair))
    CASES.append(gp(f'laws-the-customers-law-before-an-abbreviation-or-indeclinable-ifrs-at-the-end-in-a-grounded-part-'
                    f'{direction}-accepted_false_blank', ACCEPTED, brief, 'ru', OPENER_COSTS_RU[0][1], gone=('МСФО',),
                    pair=OPENER_COSTS_RU[0][3]))
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU),
                         ('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU)):
    for slug, sentence, gone, pair in (
            ('ifrs', 'Бухгалтер знает Закон о бухгалтерском учёте и МСФО.', ('МСФО',),
             f'laws-a-translated-head-noun-before-an-abbreviation-tail-and-vat-{direction}-blank'),
            ('two-standards', 'Бухгалтер руководствуется Законом о бухгалтерском учёте, НСБУ и МСФО.', ('НСБУ',),
             f'laws-a-translated-head-noun-before-an-abbreviation-tail-software-and-audit-{direction}-blank'),
            ('a-balance-of-accounts', 'Бухгалтер знает Закон о бухгалтерском учёте и сальдо по счетам.', ('сальдо',),
             f'laws-a-translated-head-noun-before-an-indeclinable-tail-and-radio-{direction}-blank'),
            ('reporting-under-the-law-and-ifrs', 'Отчётность составляется согласно Закону о бухгалтерском учёте и '
                                                 'МСФО.', ('МСФО',),
             f'laws-a-translated-head-noun-before-an-abbreviation-tail-as-well-as-ifrs-{direction}-blank'),
            ('a-credit-bureau', 'Бухгалтер знает Закон о бухгалтерском учёте и бюро кредитных историй.', ('бюро',),
             f'laws-a-translated-head-noun-before-an-indeclinable-tail-bureau-and-audit-{direction}-blank')):
        CASES.append(guard(f'laws-the-customers-translated-law-before-an-abbreviation-or-indeclinable-{slug}-'
                           f'{direction}-accepted_false_blank', ACCEPTED, brief, 'ru', sentence, gone=gone,
                           translated=True, pair=pair))

# ---------------------------------------------------------------- the re-check of round 15 (pr78-r3), both ways
# Round 15 left four readings that print what c491da9 blanks (b1, b2, b3), and the owner decided a fifth (pr78-r2's c2
# groups O and A13), pinned here as blanks under the briefs the re-check used, with the keeps 28c1b69 has for the same
# readings and the false blanks against it the owner's tie-break accepts.
JOB_RU_KNOWS_LANGUAGE = 'Составьте должностную инструкцию переводчика. Он должен знать Закон о государственном языке.'

# ---- A loan in -о that an adverb's shape, the lexicon or an adjective's stem reads as an adverb ("фортепьяно",
# "просекко", "инферно", "москито", "бонито", "пармиджано", "кено", "бронко", "челло", "дьябло", b1 R), and a noun in -у
# that keeps its form ("урду", "банту", "пушту", "Баку", b1 U): round 15 passed the loan over, or read the noun as
# unable to go on a law's name, so the name ended before it and "Знает Закон о бухгалтерском учёте и фортепьяно"
# printed (28c1b69 and eb8b05c print it too); c491da9 blanks.
LOAN_TAILS_R16 = (
    ('and-a-fortepiano', 'Знает Закон о бухгалтерском учёте и фортепьяно.', ('фортепьяно',)),
    ('prosecco-as-a-genitive', 'Знает Закон о бухгалтерском учёте просекко.', ('просекко',)),
    ('as-well-as-an-inferno', 'Соблюдает Закон о бухгалтерском учёте, а также инферно.', ('инферно',)),
    ('and-especially-a-mosquito', 'Согласно Закону о бухгалтерском учёте и особенно москито, бухгалтер ведёт книги.',
     ('москито',)),
    ('and-a-bonito', 'Знает Закон о бухгалтерском учёте и бонито.', ('бонито',)),
    ('parmigiano-and-audit', 'Соблюдает Закон о бухгалтерском учёте, пармиджано и аудите.', ('пармиджано',)),
    ('and-keno', 'Знает Закон о бухгалтерском учёте и кено.', ('кено',)),
    ('and-a-cello', 'Руководствуется Законом о бухгалтерском учёте и челло.', ('челло',)),
    ('and-diablo', 'Знает Закон о бухгалтерском учёте и дьябло.', ('дьябло',)),
    ('and-baku-capitalised', 'Знает Закон о бухгалтерском учёте и Баку.', ('Баку',)))
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence, gone in LOAN_TAILS_R16:
        CASES += [
            guard(f'laws-a-loan-read-as-an-adverb-after-a-named-law-{slug}-{direction}-blank', BLANK, brief, 'ru',
                  sentence, gone=gone, translated=direction != 'ru'),
            gp(f'laws-a-loan-read-as-an-adverb-after-a-named-law-{slug}-in-a-grounded-part-{direction}-blank', BLANK,
               brief, 'ru', sentence, gone=gone),
        ]
    CASES.append(body(f'laws-a-loan-read-as-an-adverb-after-a-named-law-and-a-fortepiano-in-a-qualification-'
                      f'{direction}-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', brief, 'ru', 'qualification',
                      LOAN_TAILS_R16[0][1], gone=('фортепьяно',)))
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU),
                         ('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU)):
    for slug, sentence, gone in (
            ('and-a-fortepiano', 'Бухгалтер знает Закон о бухгалтерском учёте и фортепьяно.', ('фортепьяно',)),
            ('a-bronco-as-a-genitive', 'Бухгалтер соблюдает Закон о бухгалтерском учёте бронко.', ('бронко',)),
            ('and-toro', 'Бухгалтер знает Закон о бухгалтерском учёте и торо.', ('торо',))):
        CASES += [
            guard(f'laws-a-translated-head-noun-before-a-loan-read-as-an-adverb-{slug}-{direction}-blank', BLANK,
                  brief, 'ru', sentence, gone=gone, translated=True),
            gp(f'laws-a-translated-head-noun-before-a-loan-read-as-an-adverb-{slug}-in-a-grounded-part-{direction}-'
               f'blank', BLANK, brief, 'ru', sentence, gone=gone),
        ]
for slug, sentence, gone in (
        ('and-urdu', 'Знает Закон о государственном языке и урду.', ('урду',)),
        ('bantu-and-hindi', 'Соблюдает Закон о государственном языке, банту и хинди.', ('банту',)),
        ('and-pashto-before-a-comma-clause', 'Согласно Закону о государственном языке и пушту, переводчик ведёт '
                                             'перевод.', ('пушту',))):
    CASES += [
        guard(f'laws-a-language-in-u-after-the-law-on-the-state-language-{slug}-ru-blank', BLANK,
              JOB_RU_KNOWS_LANGUAGE, 'ru', sentence, gone=gone, translated=False),
        gp(f'laws-a-language-in-u-after-the-law-on-the-state-language-{slug}-in-a-grounded-part-ru-blank', BLANK,
           JOB_RU_KNOWS_LANGUAGE, 'ru', sentence, gone=gone),
    ]
CASES.append(body('laws-a-language-in-u-after-the-law-on-the-state-language-and-urdu-in-a-qualification-ru-blank',
                  BLANK, 'pdf.biz.lavozim_yoriqnomasi', JOB_RU_KNOWS_LANGUAGE, 'ru', 'qualification',
                  'Знает Закон о государственном языке и урду.', gone=('урду',)))
# An adverb in -ьяно is still passed over ("рьяно"): 28c1b69 keeps the customer's law before it.
for direction, brief in RUSSIAN_ACCOUNTING:
    CASES.append(guard(f'laws-the-customers-law-before-an-adverb-in-yano-zealously-{direction}-keep', KEEP, brief, 'ru',
                       'Соблюдает Закон о бухгалтерском учёте рьяно.', translated=direction != 'ru'))

# ---- An infinitive after "и" and a noun that keeps its form (b1 I, IH, IM, b2, b3): a verb before the law that governs
# an infinitive ("Умеет", "Старается", "Стремится", "Обязуется") makes the law the infinitive's fronted object, so "Умеет
# Закон о телевидении и радио не нарушать" names "Закон о телевидении и радио". Round 15 took the infinitive for the
# verb of a clause the noun opens and ended the name at "и", so an opening word was dropped or a translated head noun
# passed as the customer's (28c1b69 blanked the lines with "не", reading it as a word in the name's case); c491da9 blanks.
INFINITIVE_TAILS_RU = (
    ('can-and-radio-not-break', 'Умеет Закон о бухгалтерском учёте и радио не нарушать.', ('радио',)),
    ('tries-and-a-casino-strictly-keep', 'Старается Закон о бухгалтерском учёте и казино строго соблюдать.',
     ('казино',)),
    ('strives-and-video-apply', 'Стремится Закон о бухгалтерском учёте и видео применять на практике.', ('видео',)),
    ('undertakes-and-a-bureau-never-break', 'Обязуется Закон о бухгалтерском учёте и бюро не нарушать никогда.',
     ('бюро',)),
    ('tries-by-the-law-and-radio-not-neglect', 'Старается Законом о бухгалтерском учёте и радио не пренебрегать.',
     ('радио',)),
    ('can-and-radio-not-confuse', 'Умеет Закон о бухгалтерском учёте и радио не путать с другими.', ('радио',)))
INFINITIVE_RADIO = 'laws-an-infinitive-after-an-indeclinable-tail-after-a-named-law-can-and-radio-not-break-ru-blank'
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence, gone in INFINITIVE_TAILS_RU:
        CASES += [
            guard(f'laws-an-infinitive-after-an-indeclinable-tail-after-a-named-law-{slug}-{direction}-blank', BLANK,
                  brief, 'ru', sentence, gone=gone, translated=direction != 'ru'),
            gp(f'laws-an-infinitive-after-an-indeclinable-tail-after-a-named-law-{slug}-in-a-grounded-part-'
               f'{direction}-blank', BLANK, brief, 'ru', sentence, gone=gone),
        ]
    CASES += [
        body(f'laws-an-infinitive-after-an-indeclinable-tail-after-a-named-law-can-and-radio-not-break-in-a-'
             f'qualification-{direction}-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', brief, 'ru', 'qualification',
             INFINITIVE_TAILS_RU[0][1], gone=('радио',)),
        fact(f'laws-an-infinitive-after-an-indeclinable-tail-after-a-named-law-can-and-a-casino-not-break-in-a-fact-'
             f'{direction}-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', brief, 'ru', 'requirements',
             'Умеет Закон о бухгалтерском учёте и казино не нарушать.', gone=('казино',)),
    ]
for direction, brief in (('ru', JOB_RU_KNOWS_ACCOUNTING_DATED), ('en-to-ru', ACCOUNTING_EN_RU_NUMBERED)):
    CASES.append(guard(f'laws-an-infinitive-after-an-indeclinable-tail-after-a-named-laws-date-and-video-{direction}-'
                       f'blank', BLANK, brief, 'ru', 'Умеет Закон о бухгалтерском учёте от 13 апреля 2016 года и видео '
                       'не нарушать.', gone=('видео',), translated=direction != 'ru'))
CASES += [
    guard('laws-an-infinitive-after-an-indeclinable-tail-after-the-law-on-television-and-radio-ru-blank', BLANK,
          JOB_RU_KNOWS_TV, 'ru', 'Старается Закон о телевидении и радио не нарушать.', gone=('радио',),
          translated=False),
    gp('laws-an-infinitive-after-an-indeclinable-tail-after-the-law-on-television-and-radio-in-a-grounded-part-ru-'
       'blank', BLANK, JOB_RU_KNOWS_TV, 'ru', 'Старается Закон о телевидении и радио не нарушать.', gone=('радио',)),
    body('laws-an-infinitive-after-an-indeclinable-tail-after-the-law-on-television-and-radio-in-a-report-ru-blank',
         BLANK, 'pdf.biz.hisobot', JOB_RU_KNOWS_TV, 'ru', 'work_done', 'Умеет Закон о телевидении и казино не нарушать.',
         gone=('казино',)),
]
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU),
                         ('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU)):
    for slug, sentence, gone in (
            ('strives-and-video-not-break', 'Бухгалтер стремится Закон о бухгалтерском учёте и видео не нарушать.',
             ('видео',)),
            ('tries-by-the-law-and-radio-be-guided', 'Бухгалтер старается Законом о бухгалтерском учёте и радио '
                                                     'руководствоваться.', ('радио',)),
            ('can-and-a-casino-not-confuse', 'Бухгалтер умеет Закон о бухгалтерском учёте и казино не путать.',
             ('казино',))):
        CASES += [
            guard(f'laws-a-translated-head-noun-before-an-indeclinable-tail-and-an-infinitive-{slug}-{direction}-blank',
                  BLANK, brief, 'ru', sentence, gone=gone, translated=True),
            gp(f'laws-a-translated-head-noun-before-an-indeclinable-tail-and-an-infinitive-{slug}-in-a-grounded-part-'
               f'{direction}-blank', BLANK, brief, 'ru', sentence, gone=gone),
        ]
# 28c1b69's keep the reading holds: a modal after the infinitive in a comma clause is that clause's verb.
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    CASES.append(guard(f'laws-the-customers-law-before-an-infinitive-and-a-modal-a-balance-may-not-be-carried-'
                       f'{direction}-keep', KEEP, brief, 'ru', 'Согласно Закону о бухгалтерском учёте, сальдо переносить '
                       'нельзя.', translated=direction != 'ru'))
# What the reading costs against 28c1b69 (pr78-r3 k F): after a verb that governs an infinitive, an abbreviation or a
# noun that keeps its form before the infinitive is the law's last word as the radio is ("Умеет Закон о бухгалтерском
# учёте и НДС применять на практике" may name "Закон о бухгалтерском учёте и НДС"), the tie-break family of "Знает Закон
# о бухгалтерском учёте и МСФО"; the opening word is the name's and blanks.
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence, gone in (
            ('can-and-vat-apply', 'Умеет Закон о бухгалтерском учёте и НДС применять на практике.', ('НДС',)),
            ('tries-and-a-balance-not-break', 'Старается Закон о бухгалтерском учёте и сальдо не нарушать.',
             ('сальдо',)),
            ('strives-and-ifrs-apply', 'Стремится Закон о бухгалтерском учёте и МСФО применять на практике.',
             ('МСФО',))):
        CASES.append(guard(f'laws-the-customers-law-before-an-abbreviation-or-indeclinable-and-an-infinitive-{slug}-'
                           f'{direction}-accepted_false_blank', ACCEPTED, brief, 'ru', sentence, gone=gone,
                           translated=direction != 'ru', pair=INFINITIVE_RADIO))

# ---- A verb a law itself may take after "и" or a comma and a noun that keeps its form or an abbreviation (pr78-r2 c2
# O and A13, the owner's decision): "Знает Закон о бухгалтерском учёте и радио не нарушает", "Соблюдает Закон ... и НДС
# не регулируется иначе", "Согласно Закону ..., казино не регулирует", "Бухгалтер ведёт учёт и руководствуется при
# этом Законом ... и ПО регулируется работа". The law may be the verb's subject or object, the noun the name's last
# word; never invent, so the name does not end at the noun and the opening word or the head noun is the name's (28c1b69
# blanked the lines with "не" or "ПО", reading them as a word in the name's case or "по"; it printed the others).
LAW_VERB_TAILS_RU = (
    ('knows-and-radio-does-not-break', 'Знает Закон о бухгалтерском учёте и радио не нарушает.', ('радио',)),
    ('keeps-and-vat-is-not-regulated-otherwise', 'Соблюдает Закон о бухгалтерском учёте и НДС не регулируется иначе.',
     ('НДС',)),
    ('guided-and-a-casino-does-not-break', 'Руководствуется Законом о бухгалтерском учёте и казино не нарушает.',
     ('казино',)),
    ('according-to-and-a-show-does-not-regulate', 'Согласно Закону о бухгалтерском учёте, шоу не регулирует.',
     ('шоу',)),
    ('knows-and-software-does-not-regulate', 'Знает Закон о бухгалтерском учёте, ПО не регулирует.', ('ПО',)),
    ('keeps-and-a-bureau-strictly-keeps', 'Соблюдает Закон о бухгалтерском учёте и бюро строго соблюдает.', ('бюро',)),
    ('knows-and-a-balance-may-break', 'Знает Закон о бухгалтерском учёте и сальдо может нарушать.', ('сальдо',)),
    ('knows-and-video-was-amended', 'Знает Закон о бухгалтерском учёте и видео было изменено.', ('видео',)),
    ('applies-and-radio-requires', 'Применяет Закон о бухгалтерском учёте и радио требует отчётности.', ('радио',)),
    ('according-to-a-semicolon-and-an-llc-sets', 'Согласно Закону о бухгалтерском учёте; ООО устанавливает порядок.',
     ('ООО',)),
    ('knows-and-radio-lobbies', 'Знает Закон о бухгалтерском учёте и радио не лоббирует.', ('радио',)),
    ('knows-and-a-casino-initiates', 'Знает Закон о бухгалтерском учёте, казино не инициирует.', ('казино',)))
LAW_VERB_RADIO = 'laws-a-verb-a-law-may-take-after-an-indeclinable-tail-knows-and-radio-does-not-break-ru-blank'
LAW_VERB_COMMA = 'laws-a-verb-a-law-may-take-after-an-indeclinable-tail-according-to-and-a-show-does-not-regulate-ru-blank'
LAW_VERB_SEMICOLON = ('laws-a-verb-a-law-may-take-after-an-indeclinable-tail-according-to-a-semicolon-and-an-llc-sets-'
                      'ru-blank')
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence, gone in LAW_VERB_TAILS_RU:
        CASES += [
            guard(f'laws-a-verb-a-law-may-take-after-an-indeclinable-tail-{slug}-{direction}-blank', BLANK, brief,
                  'ru', sentence, gone=gone, translated=direction != 'ru'),
            gp(f'laws-a-verb-a-law-may-take-after-an-indeclinable-tail-{slug}-in-a-grounded-part-{direction}-blank',
               BLANK, brief, 'ru', sentence, gone=gone),
        ]
    CASES += [
        body(f'laws-a-verb-a-law-may-take-after-an-indeclinable-tail-knows-and-radio-does-not-break-in-a-qualification-'
             f'{direction}-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', brief, 'ru', 'qualification',
             LAW_VERB_TAILS_RU[0][1], gone=('радио',)),
        body(f'laws-a-verb-a-law-may-take-after-an-indeclinable-tail-according-to-and-a-show-in-a-report-{direction}-'
             f'blank', BLANK, 'pdf.biz.hisobot', brief, 'ru', 'work_done', LAW_VERB_TAILS_RU[3][1], gone=('шоу',)),
    ]
for direction, brief in (('ru', JOB_RU_KNOWS_ACCOUNTING_DATED), ('en-to-ru', ACCOUNTING_EN_RU_NUMBERED)):
    CASES.append(guard(f'laws-a-verb-a-law-may-take-after-an-indeclinable-tail-after-a-named-laws-date-and-radio-'
                       f'{direction}-blank', BLANK, brief, 'ru', 'Знает Закон о бухгалтерском учёте от 13 апреля 2016 '
                       'года и радио не нарушает.', gone=('радио',), translated=direction != 'ru'))
CASES += [
    guard('laws-a-verb-a-law-may-take-after-an-indeclinable-tail-after-the-law-on-television-and-radio-ru-blank', BLANK,
          JOB_RU_KNOWS_TV, 'ru', 'Соблюдает Закон о телевидении и радио не нарушает.', gone=('радио',),
          translated=False),
    gp('laws-a-verb-a-law-may-take-after-an-indeclinable-tail-after-the-law-on-television-a-comma-and-radio-in-a-'
       'grounded-part-ru-blank', BLANK, JOB_RU_KNOWS_TV, 'ru', 'Знает Закон о телевидении, радио не регулирует.',
       gone=('радио',)),
]
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU),
                         ('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU)):
    for slug, sentence, gone in (
            ('guided-at-that-and-software-regulates-work', 'Бухгалтер ведёт учёт и руководствуется при этом Законом о '
                                                           'бухгалтерском учёте и ПО регулируется работа.', ('ПО',)),
            ('knows-and-a-casino-does-not-break', 'Бухгалтер знает Закон о бухгалтерском учёте и казино не нарушает.',
             ('казино',)),
            ('keeps-and-vat-does-not-regulate', 'Бухгалтер соблюдает Закон о бухгалтерском учёте, НДС не регулирует.',
             ('НДС',))):
        CASES += [
            guard(f'laws-a-translated-head-noun-before-an-indeclinable-tail-and-a-verb-a-law-may-take-{slug}-'
                  f'{direction}-blank', BLANK, brief, 'ru', sentence, gone=gone, translated=True),
            gp(f'laws-a-translated-head-noun-before-an-indeclinable-tail-and-a-verb-a-law-may-take-{slug}-in-a-'
               f'grounded-part-{direction}-blank', BLANK, brief, 'ru', sentence, gone=gone),
        ]
# 28c1b69's keeps the reading holds: a verb that cannot take a law opens the noun's clause, with "не", a modal, a copula
# and a participle of such a verb too.
CLAUSE_VERBS_NO_LAW_RU = (
    ('vat-not-understated', 'Знает Закон о бухгалтерском учёте и НДС не занижает.'),
    ('a-balance-not-confused', 'Соблюдает Закон о бухгалтерском учёте, сальдо не путает.'),
    ('a-balance-can-be-computed', 'Знает Закон о бухгалтерском учёте и сальдо может рассчитать.'),
    ('an-llc-must-keep-books', 'Знает Закон о бухгалтерском учёте и ООО обязано вести учёт.'),
    ('a-balance-may-be-carried', 'Согласно Закону о бухгалтерском учёте, сальдо может быть перенесено.'),
    ('a-jsc-publishes', 'Соблюдает Закон о бухгалтерском учёте и АО публикует отчётность.'))
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence in CLAUSE_VERBS_NO_LAW_RU:
        CASES.append(guard(f'laws-the-customers-law-before-a-clause-whose-verb-takes-no-law-{slug}-{direction}-keep',
                           KEEP, brief, 'ru', sentence, translated=direction != 'ru'))
# What the owner's decision costs against 28c1b69: the customer's law before an abbreviation or such a noun opening a
# clause whose verb a law may take ("Соблюдает Закон ... и НДС не нарушает", "Согласно Закону ..., ИП освобождается от
# учёта", "..., НДС учитывается отдельно", "..., ООО применяет упрощённую систему", "..., НДС следует начислять", the
# sweep's "...; УСН применяется малыми предприятиями"):
# the same words in the same place may name an invented law, so the opening word is the name's and blanks.
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence, gone, pair in (
            ('vat-does-not-break', 'Соблюдает Закон о бухгалтерском учёте и НДС не нарушает.', ('НДС',), LAW_VERB_RADIO),
            ('a-sole-trader-is-exempt', 'Согласно Закону о бухгалтерском учёте, ИП освобождается от ведения учёта.',
             ('ИП',), LAW_VERB_COMMA),
            ('vat-is-taken-into-account', 'Согласно Закону о бухгалтерском учёте, НДС учитывается отдельно.', ('НДС',),
             LAW_VERB_COMMA),
            ('an-llc-applies-a-system', 'Согласно Закону о бухгалтерском учёте, ООО применяет упрощённую систему.',
             ('ООО',), LAW_VERB_COMMA),
            ('vat-should-be-charged', 'Согласно Закону о бухгалтерском учёте, НДС следует начислять ежемесячно.',
             ('НДС',), LAW_VERB_COMMA),
            ('a-semicolon-the-simplified-tax-is-applied', 'Согласно Закону о бухгалтерском учёте; УСН применяется '
                                                          'малыми предприятиями.', ('УСН',), LAW_VERB_SEMICOLON)):
        CASES.append(guard(f'laws-the-customers-law-before-a-clause-whose-verb-a-law-may-take-{slug}-{direction}-'
                           f'accepted_false_blank', ACCEPTED, brief, 'ru', sentence, gone=gone,
                           translated=direction != 'ru', pair=pair))

# ---- A word in capitals in the name's case after "и" before a verb (b1 S, SM, b3): round 15 read every word in capitals
# as an abbreviation that may open a clause, so "Знает Закон о бухгалтерском учёте и АУДИТЕ ведёт книги" printed with
# "аудите" read as a clause's subject, and with a word between, "Знает Закон о телевидении и СМИ редактор освещает
# события" with "редактор" its subject; 28c1b69 read the word as one in the name's case and blanked; c491da9 blanks.
# Only a short abbreviation (two to four letters, no word of the lexicon nor a case of one) opens a clause, its verb
# right after it or after "не".
CAPITALS_IN_CASE_TAILS_RU = (
    ('knows-and-audit-keeps-books', 'Знает Закон о бухгалтерском учёте и АУДИТЕ ведёт книги.', ('АУДИТЕ',)),
    ('keeps-and-taxes-reports', 'Соблюдает Закон о бухгалтерском учёте и НАЛОГАХ отчитывается вовремя.',
     ('НАЛОГАХ',)),
    ('knows-and-the-media-an-editor-covers', 'Знает Закон о бухгалтерском учёте и СМИ редактор освещает события.',
     ('СМИ',)),
    ('knows-and-the-media-does-not-break', 'Знает Закон о бухгалтерском учёте и СМИ не нарушает.', ('СМИ',)),
    ('keeps-and-an-institute-regulates', 'Соблюдает Закон о бухгалтерском учёте и НИИ регулирует отчётность.',
     ('НИИ',)),
    ('guided-and-the-traffic-police-strictly-keeps', 'Руководствуется Законом о бухгалтерском учёте и ГАИ строго '
                                                     'соблюдает.', ('ГАИ',)))
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence, gone in CAPITALS_IN_CASE_TAILS_RU:
        CASES += [
            guard(f'laws-a-word-in-capitals-in-the-names-case-after-a-named-law-{slug}-{direction}-blank', BLANK, brief,
                  'ru', sentence, gone=gone, translated=direction != 'ru'),
            gp(f'laws-a-word-in-capitals-in-the-names-case-after-a-named-law-{slug}-in-a-grounded-part-{direction}-'
               f'blank', BLANK, brief, 'ru', sentence, gone=gone),
        ]
    CASES.append(fact(f'laws-a-word-in-capitals-in-the-names-case-after-a-named-law-knows-and-audit-in-a-fact-'
                      f'{direction}-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', brief, 'ru', 'knowledge',
                      'Знает Закон о бухгалтерском учёте и АУДИТЕ не нарушает.', gone=('АУДИТЕ',)))
CASES += [
    guard('laws-a-word-in-capitals-in-the-names-case-after-the-law-on-television-and-the-media-ru-blank', BLANK,
          JOB_RU_KNOWS_TV, 'ru', 'Соблюдает Закон о телевидении и СМИ регулирует вещание.', gone=('СМИ',),
          translated=False),
    guard('laws-a-word-in-capitals-in-the-names-case-after-the-law-on-television-the-media-and-an-editor-ru-blank',
          BLANK, JOB_RU_KNOWS_TV, 'ru', 'Знает Закон о телевидении и СМИ редактор освещает события.', gone=('СМИ',),
          translated=False),
]
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU),
                         ('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU)):
    for slug, sentence, gone in (
            ('knows-and-audit-keeps-books', 'Бухгалтер знает Закон о бухгалтерском учёте и АУДИТЕ ведёт книги.',
             ('АУДИТЕ',)),
            ('knows-and-the-media-an-editor-covers', 'Бухгалтер знает Закон о бухгалтерском учёте и СМИ редактор '
                                                     'освещает события.', ('СМИ',))):
        CASES += [
            guard(f'laws-a-translated-head-noun-before-a-word-in-capitals-in-the-names-case-{slug}-{direction}-blank',
                  BLANK, brief, 'ru', sentence, gone=gone, translated=True),
            gp(f'laws-a-translated-head-noun-before-a-word-in-capitals-in-the-names-case-{slug}-in-a-grounded-part-'
               f'{direction}-blank', BLANK, brief, 'ru', sentence, gone=gone),
        ]
# The keeps a short abbreviation opening a clause has in a translated paper (eb8b05c keeps them; 28c1b69 read the
# abbreviation as a word in the name's case): its verb, one that takes no law, right after it or after "не".
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU),
                         ('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU)):
    for slug, sentence in (('the-tax-inspectorate-checks', 'Согласно Закону о бухгалтерском учёте, ГНИ проверяет '
                                                           'отчётность.'),
                           ('the-media-covers', 'Знает Закон о бухгалтерском учёте и СМИ освещает события.'),
                           ('the-traffic-police-does-not-fine', 'Знает Закон о бухгалтерском учёте и ГАИ не штрафует '
                                                                'бухгалтера.')):
        CASES.append(guard(f'laws-the-customers-law-before-a-short-abbreviation-in-capitals-opening-a-clause-{slug}-'
                           f'{direction}-keep', KEEP, brief, 'ru', sentence, translated=True))

# ---- A subordinate clause with its comma left out before the law (b1 Q): "как" after a verb ("Бухгалтер знает как
# Закон о ..."), and "почему", "зачем", "насколько", "каким образом", "сразу как", "чем" open a clause whose subject is
# the law, so its verb after the name may be the law's own. Round 15 read "как" after a verb as a role and lacked the
# others, so the verb before the law was the law's sentence's and "и радио работает" another clause: "Бухгалтер знает
# как Закон о бухгалтерском учёте и радио работает на практике" printed; c491da9 blanks.
SUBORDINATE_LAW_TAILS_RU = (
    ('knows-how-and-radio-works', 'Бухгалтер знает как Закон о бухгалтерском учёте и радио работает на практике.',
     ('радио',)),
    ('understands-why-and-a-casino-exists', 'Бухгалтер понимает почему Закон о бухгалтерском учёте и казино '
                                            'существует.', ('казино',)),
    ('explains-what-for-and-ifrs-appeared', 'Бухгалтер объясняет зачем Закон о бухгалтерском учёте и МСФО появились.',
     ('МСФО',)),
    ('knows-how-far-and-radio-works', 'Бухгалтер знает насколько Закон о бухгалтерском учёте и радио работает '
                                      'эффективно.', ('радио',)),
    ('understands-in-what-way-and-video-works', 'Бухгалтер понимает каким образом Закон о бухгалтерском учёте и видео '
                                                'работает.', ('видео',)),
    ('starts-as-soon-as-and-the-media-appears', 'Бухгалтер начинает работу сразу как Закон о бухгалтерском учёте и '
                                                'СМИ появляются.', ('СМИ',)),
    ('works-better-than-and-a-bureau-works', 'Бухгалтер работает лучше чем Закон о бухгалтерском учёте и бюро '
                                             'работает.', ('бюро',)))
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU),
                         ('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU)):
    for slug, sentence, gone in SUBORDINATE_LAW_TAILS_RU:
        CASES += [
            guard(f'laws-a-translated-head-noun-before-a-tail-in-a-subordinate-clause-{slug}-{direction}-blank', BLANK,
                  brief, 'ru', sentence, gone=gone, translated=True),
            gp(f'laws-a-translated-head-noun-before-a-tail-in-a-subordinate-clause-{slug}-in-a-grounded-part-'
               f'{direction}-blank', BLANK, brief, 'ru', sentence, gone=gone),
        ]
    CASES.append(body(f'laws-a-translated-head-noun-before-a-tail-in-a-subordinate-clause-knows-how-and-radio-works-in-'
                      f'a-qualification-{direction}-blank', BLANK, 'pdf.biz.lavozim_yoriqnomasi', brief, 'ru',
                      'qualification', SUBORDINATE_LAW_TAILS_RU[0][1], gone=('радио',)))
# "как" after the subject still names a role (round 15's keep, 28c1b69 keeps it): the verb is the law's sentence's.
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU)):
    CASES.append(guard(f'laws-the-customers-translated-law-after-a-role-with-kak-and-a-clause-whose-verb-takes-no-law-'
                       f'{direction}-keep', KEEP, brief, 'ru', 'Бухгалтер как специалист знает Закон о бухгалтерском '
                       'учёте и сальдо не путает.', translated=True))

# ---- An adverb in -имо, -емо, -исто or -ато after the customer's law (pr78-r3 k, k2): "зримо", "неумолимо",
# "непоколебимо", "предсказуемо", "смекалисто", "напористо", "угловато", "простовато", "солоно". Round 15 read none as
# an adverb, so it was a noun that keeps its -о and the customer's law blanked; 28c1b69 passed every lower-case word in
# -о over and keeps them. The nouns of those shapes still go on the name ("эскимо", "мемо", "стаккато", "фортиссимо",
# "маккиато").
SHAPED_ADVERBS_IN_O_RU = (
    ('relentlessly', 'Соблюдает Закон о бухгалтерском учёте неумолимо.'),
    ('visibly', 'Применяет Закон о бухгалтерском учёте зримо.'),
    ('unshakeably-and-a-clause', 'Соблюдает Закон о бухгалтерском учёте непоколебимо и умеет вести книги.'),
    ('predictably', 'Применяет Закон о бухгалтерском учёте предсказуемо.'),
    ('shrewdly-and-applies-it', 'Знает Закон о бухгалтерском учёте и смекалисто применяет его.'),
    ('assertively-and-upholds-it', 'Знает Закон о бухгалтерском учёте и напористо отстаивает его нормы.'),
    ('awkwardly', 'Соблюдает Закон о бухгалтерском учёте угловато.'),
    ('simplistically-a-comma-clause', 'Знает Закон о бухгалтерском учёте, простовато толкуя его.'),
    ('vaguely-having-studied', 'Изучив Закон о бухгалтерском учёте расплывчато, бухгалтер ведёт книги.'))
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence in SHAPED_ADVERBS_IN_O_RU:
        CASES += [
            guard(f'laws-the-customers-law-before-an-adverb-in-imo-isto-or-ato-{slug}-{direction}-keep', KEEP, brief,
                  'ru', sentence, translated=direction != 'ru'),
            gp(f'laws-the-customers-law-before-an-adverb-in-imo-isto-or-ato-{slug}-in-a-grounded-part-{direction}-keep',
               KEEP, brief, 'ru', sentence),
        ]
    CASES.append(body(f'laws-the-customers-law-before-an-adverb-in-imo-isto-or-ato-unshakeably-and-a-clause-in-a-report-'
                      f'{direction}-keep', KEEP, 'pdf.biz.hisobot', brief, 'ru', 'work_done', SHAPED_ADVERBS_IN_O_RU[2][1]))
for direction, brief in (('en-to-ru', ACCOUNTING_EN_RU), ('uz-to-ru', ACCOUNTING_UZ_RU),
                         ('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU)):
    for slug, sentence in (('relentlessly', 'Бухгалтер соблюдает Закон о бухгалтерском учёте неумолимо.'),
                           ('assertively-and-a-clause', 'Бухгалтер применяет Закон о бухгалтерском учёте напористо и ведёт '
                                                   'книги.')):
        CASES.append(guard(f'laws-the-customers-translated-law-before-an-adverb-in-imo-isto-or-ato-{slug}-{direction}-'
                           f'keep', KEEP, brief, 'ru', sentence, translated=True))
for direction, brief in RUSSIAN_ACCOUNTING + (('uz-cyrillic-to-ru', ACCOUNTING_UZC_RU),):
    for slug, sentence, gone in (
            ('and-an-eskimo', 'Знает Закон о бухгалтерском учёте и эскимо.', ('эскимо',)),
            ('and-a-memo', 'Соблюдает Закон о бухгалтерском учёте и мемо.', ('мемо',)),
            ('staccato-as-a-genitive', 'Знает Закон о бухгалтерском учёте стаккато.', ('стаккато',)),
            ('and-fortissimo', 'Знает Закон о бухгалтерском учёте и фортиссимо.', ('фортиссимо',)),
            ('as-well-as-a-macchiato', 'Применяет Закон о бухгалтерском учёте, а также маккиато.', ('маккиато',))):
        CASES.append(guard(f'laws-a-noun-of-an-adverbs-shape-in-imo-or-ato-after-a-named-law-{slug}-{direction}-blank',
                           BLANK, brief, 'ru', sentence, gone=gone, translated=direction != 'ru'))

CASE_IDS = [case.id for case in CASES]


# ---------------------------------------------------------------- running a case


def _draft(entry_id, brief, locale, revision=None):
    entry = catalogue.get(entry_id)
    length = LENGTHS.get(entry_id, 1)
    data = {'options': {'category': entry.id, 'length': length}, 'prompt': brief, 'output_locale': locale,
            'output_format': 'pdf', 'excerpts': [], 'source_ids': []}
    if revision:
        data['revision'] = revision
    data['content'] = {'title': '', 'sections': skeleton.seed(entry, length, skeleton.cues_of(data)),
                       'questions': [], 'citations': []}
    return data


def _answer(data, title='', sections=None, questions=()):
    """The model's answer: every seeded section, updated where given; a section the seed lacks is added."""
    sections = sections or {}
    made, seen = [], set()
    for seeded in data['content']['sections']:
        section = copy.deepcopy(seeded)
        section.update(sections.get(seeded['id'], {}))
        made.append(section)
        seen.add(seeded['id'])
    for section_id, update in sections.items():
        if section_id not in seen:
            made.append({'id': section_id, 'heading': '', 'body': '', 'notes': '', 'layout': 'text', 'items': [],
                         **update})
    return {'title': title, 'sections': made, 'questions': list(questions), 'citations': []}


def _section(content, section_id):
    return next((section for section in content['sections'] if section.get('id') == section_id), None)


def _facts(content):
    section = _section(content, 'facts') or {}
    return {item['label']: item['text'] for item in section.get('items') or []}


def _strings(content):
    """Every text of a finished paper a template or the fallback could print."""
    found = [content.get('title') or '']
    for section in content.get('sections') or []:
        found += [section.get(key) or '' for key in ('heading', 'body', 'notes')]
        for entry in section.get('items') or []:
            if isinstance(entry, dict):
                found += [str(entry.get(key) or '') for key in ('label', 'text', 'value')]
    for asked in content.get('questions') or []:
        found += [str(asked.get(key) or '') for key in ('stem', 'answer', 'explanation')]
        found += [str(option) for option in asked.get('options') or []]
    return [text for text in found if text]


def _finish(case):
    """(the text where the case's value was put, every text of the finished paper) after finish.apply."""
    data = _draft(case.entry, case.brief, case.locale)
    if case.translated is not None:
        assert finish._translated(data) is case.translated, 'the brief is not read in the language the case says'
    kind, _, target = case.where.partition(':')
    sections = {part_id: dict(update) for part_id, update in case.parts}
    given = [{'label': field_id, 'text': value, 'value': ''} for field_id, value in case.facts]
    title, questions = '', ()
    if kind == 'fact':
        given.append({'label': target, 'text': case.value, 'value': ''})
    elif kind == 'body':
        sections.setdefault(target, {})['body'] = case.value
    elif kind == 'item':
        sections.setdefault(target, {})['items'] = [{'label': '', 'text': case.value, 'value': ''}]
    elif kind == 'cell':
        sections.setdefault(target, {})['items'] = [{'label': case.value, 'text': case.row[0], 'value': case.row[1]}]
    elif kind == 'title':
        title = case.value
    elif kind == 'question':
        questions = [case.value]
    if given:
        sections['facts'] = {'items': given, 'layout': 'list'}
    codes = []
    made, _ = finish.apply(data, _answer(data, title, sections, questions), file_names=[], codes=codes)
    if kind == 'fact':
        found = _facts(made).get(target)
    elif kind == 'body':
        found = (_section(made, target) or {}).get('body') or ''
    elif kind == 'item':
        found = [entry.get('text') for entry in (_section(made, target) or {}).get('items') or []]
    elif kind == 'cell':
        found = [entry.get('label') for entry in (_section(made, target) or {}).get('items') or []]
    elif kind == 'title':
        found = made['title']
    else:
        found = [asked.get('stem') for asked in made.get('questions') or []]
    return found, _strings(made)


def _unit(case):
    """(the text or verdict a unit call gives for the case's value) with the brief as the customer's words."""
    trusted = facts.trusting(case.brief)
    translated = finish._translated({'prompt': case.brief, 'output_locale': case.locale})
    if case.translated is not None:
        assert translated is case.translated, 'the brief is not read in the language the case says'
    call, _, kind = case.call.partition(':')
    if call == 'ground_paper':
        # In the paper's language, as the finish reads a grounded part (facts.common's `language`).
        return finish.ground_paper(case.value, trusted, translated=translated, language=case.locale)[0]
    if call == 'guard':
        return facts.guard(case.value, trusted, translated=translated)[0]
    return facts.supported(case.value, kind, trusted, translated=translated, strict=True, words=True)


def _shows(texts, word):
    """Whether `word` is printed in any of `texts`, whole or with an ending ("Artelga", "Acme’s"), never inside
    another word."""
    pattern = re.compile(r'(?<![^\W_])' + re.escape(word))
    return any(pattern.search(text) for text in texts)


@pytest.mark.parametrize('case', CASES, ids=CASE_IDS)
def test_grounding_matrix(case):
    if case.entry:
        found, printed = _finish(case)
        where = found if isinstance(found, list) else [found or '']
    else:
        found = _unit(case)
        printed = where = [found] if isinstance(found, str) else []
    if case.direction == KEEP:
        if isinstance(found, bool):
            assert found, f'{case.value!r} is the customer\'s and must be kept'
        elif isinstance(found, list):
            assert case.value.get('stem') in found if isinstance(case.value, dict) else case.value in found, \
                f'{case.value!r} must stay verbatim; the paper has {found!r}'
        else:
            assert found == case.value, f'{case.value!r} must stay verbatim; the paper has {found!r}'
        return
    if isinstance(found, bool):
        assert not found, f'{case.value!r} names what the customer never gave and must not be kept'
        return
    assert case.gone, 'a blank case names the words that must not reach the paper'
    leaked = [word for word in case.gone if _shows(printed, word) or _shows(where, word)]
    assert not leaked, f'{leaked} reached the paper: {found!r}'


def test_every_accepted_false_blank_names_the_leak_it_pays_for():
    by_id = {case.id: case for case in CASES}
    assert len(by_id) == len(CASES), 'case ids are unique'
    for case in CASES:
        assert case.id.endswith('-' + case.direction), f'{case.id} ends with its direction'
        if case.direction == ACCEPTED:
            assert by_id.get(case.pair) is not None and by_id[case.pair].direction == BLANK, \
                f'{case.id} names the blank case it is the price of'


# ---------------------------------------------------------------- what a change reads back (d09da98)


CHANGE_PLAN = ('Samarqandda tikuvchilik sexi ochish uchun biznes-reja kerak. Direktor Ergasheva Dilnoza. '
               'O‘z mablag‘imiz 90 mln so‘m, bankdan 150 mln so‘m kredit olamiz.')


@dataclass(frozen=True)
class Change:
    id: str
    direction: str
    entry: str
    brief: str
    locale: str
    first: dict                 # the first answer's sections
    request: str
    second: dict                # the answer to the change's request
    where: str                  # 'body:<part>' or 'fact:<field>'
    value: str
    gone: tuple = ()
    pair: str = ''
    first_request: str = ''     # the change request the first version was made under, if any

    def __str__(self):
        return self.id


CHANGES = [
    # An invented bank a grounded cell's free first word let through in v1 never becomes the customer's in v2.
    Change('change-free-first-word-of-a-cell-not-read-back-uz-blank', BLANK, 'pdf.biz.biznes_reja', CHANGE_PLAN, 'uz',
           {'finance_sources': {'items': [{'label': 'Agrobank krediti', 'text': '150 mln so‘m', 'value': ''},
                                          {'label': 'O‘z mablag‘i', 'text': '90 mln so‘m', 'value': ''}]},
            'facts': {'items': [{'label': 'director', 'text': 'Ergasheva Dilnoza'},
                                {'label': 'loan_bank', 'text': 'Agrobank'}]}},
           'Moliyalashtirish qismini kengaytiring.',
           {'operations': {'body': 'Kredit mablag‘lari Agrobank tomonidan ajratiladi.'},
            'facts': {'items': [{'label': 'director', 'text': 'Ergasheva Dilnoza'},
                                {'label': 'loan_bank', 'text': 'Agrobank'}]}},
           'body:operations', 'Kredit mablag‘lari Agrobank tomonidan ajratiladi.', gone=('Agrobank',)),
    # A translated reference's publisher, left to the translation, never makes v2's university the customer's.
    Change('change-translated-reference-publisher-not-read-back-ru-to-uz-blank', BLANK, 'pdf.kurs_ishi',
           'Напишите курсовую работу на узбекском языке на тему «Маркетинговая стратегия малого бизнеса». '
           'Студент Каримов Жасур.', 'uz',
           {'references': {'items': [{'label': '1', 'text': 'Marketing strategiyasi asoslari. Cambridge Business '
                                                           'Academy nashriyoti.', 'value': ''}]},
            'facts': {'items': [{'label': 'student_name', 'text': 'Karimov Jasur'}]}},
           'Сделайте введение подробнее.',
           {'facts': {'items': [{'label': 'university', 'text': 'Cambridge Business Academy'},
                                {'label': 'student_name', 'text': 'Karimov Jasur'}]}},
           'fact:university', 'Cambridge Business Academy', gone=('Cambridge',)),
    # The customer's own facts of v1 stay theirs after a change.
    Change('change-the-customers-facts-read-back-uz-keep', KEEP, 'pdf.biz.biznes_reja', CHANGE_PLAN, 'uz',
           {'facts': {'items': [{'label': 'director', 'text': 'Ergasheva Dilnoza'}]}},
           'Moliyalashtirish qismini kengaytiring.',
           {'operations': {'body': 'Sexni direktor Ergasheva Dilnoza boshqaradi.'},
            'facts': {'items': [{'label': 'director', 'text': 'Ergasheva Dilnoza'}]}},
           'body:operations', 'Sexni direktor Ergasheva Dilnoza boshqaradi.'),
    # d09da98 accepts it: a name an earlier change request gave ("Sardor") that lives on only as a grounded part's
    # free first word reads exactly as a model's free first word, so the change after it blanks the name.
    Change('change-name-from-an-earlier-request-two-changes-later-uz-accepted_false_blank', ACCEPTED,
           'pdf.biz.biznes_reja', CHANGE_PLAN, 'uz',
           {'operations': {'body': 'Sardor sexni boshqaradi.'},
            'facts': {'items': [{'label': 'director', 'text': 'Ergasheva Dilnoza'}]}},
           'Xulosani kengaytiring.',
           {'operations': {'body': 'Sexni Sardor boshqaradi.'},
            'facts': {'items': [{'label': 'director', 'text': 'Ergasheva Dilnoza'}]}},
           'body:operations', 'Sexni Sardor boshqaradi.', gone=('Sardor',),
           pair='change-free-first-word-of-a-cell-not-read-back-uz-blank',
           first_request='Sexni boshqaruvchi Sardor ekanini yozing.'),
]


@pytest.mark.parametrize('change', CHANGES, ids=[change.id for change in CHANGES])
def test_what_a_change_reads_back(change):
    data = _draft(change.entry, change.brief, change.locale)
    if change.first_request:
        data['revision'] = {'request': change.first_request, 'original_prompt': change.brief}
    first, _ = finish.apply(data, _answer(data, sections=change.first), file_names=[], codes=[])
    if change.first_request:
        assert all(_shows(_strings(first), word) for word in change.gone), \
            'the earlier request gave these words, so the first version printed them'
    revision = {'request': change.request, 'original_prompt': change.brief, 'before': copy.deepcopy(first)}
    again = _draft(change.entry, change.request, change.locale, revision=revision)
    made, _ = finish.apply(again, _answer(again, sections=change.second), file_names=[], codes=[])
    kind, _, target = change.where.partition(':')
    found = _facts(made).get(target) if kind == 'fact' else (_section(made, target) or {}).get('body') or ''
    if change.direction == KEEP:
        assert found == change.value, f'{change.value!r} must stay verbatim; the paper has {found!r}'
        return
    if change.direction == ACCEPTED:
        assert any(other.id == change.pair and other.direction == BLANK for other in CHANGES)
    leaked = [word for word in change.gone if _shows(_strings(made), word)]
    assert not leaked, f'{leaked} reached the paper after the change: {found!r}'



# An earlier version's fact of a figure's kind or of no field is held by its figures alone (`facts._figures_only`), read
# out of its sentence (the re-check of round 11, p7): the first reading leaves the apostrophe ordinal of its placing
# unread ("to‘rtinchi" of "to‘rtinchi o‘rinni egalladi"), and read alone that word is the bare "4" the sentence never
# gives, so the revised paper's "4 yil" passed; c491da9 and eb8b05c stopped reading there and failed the job.
HELD_PLACINGS = [
    (f'numbers-an-earlier-versions-{slug}-in-{fact}-grounds-no-years-in-{kind}-uz-blank', entry, part, label, held, n)
    for kind, entry, part in (('references', 'pdf.xat.tavsifnoma', 'achievements'), ('reports', 'pdf.biz.hisobot',
                                                                                     'summary'))
    for label, fact in (('', 'a-fact-of-no-field'), ('note', 'a-note-fact'), ('achievements', 'an-achievements-fact'),
                        ('date', 'a-date-fact'))
    for slug, held, n in (('fourth-place', 'Viloyat olimpiadasida to‘rtinchi o‘rinni egalladi.', 4),
                          ('tenth-place', 'Tanlovda o‘ninchi o‘rinda.', 10))]


@pytest.mark.parametrize('id, entry, part, label, held, n', HELD_PLACINGS, ids=[row[0] for row in HELD_PLACINGS])
def test_an_earlier_versions_placing_grounds_no_bare_figure(id, entry, part, label, held, n):
    brief = PLACING_LETTERS['uz'].strip()
    data = _draft(entry, brief, 'uz')
    before = _answer(data, sections={'facts': {'items': [{'label': label, 'text': held, 'value': ''}],
                                               'layout': 'list'}})
    data['revision'] = {'before': before, 'request': 'Matnni qisqartiring.', 'original_prompt': brief}
    assert str(n) not in facts.trusted(data).values, f'the earlier placing gives the bare figure {n}'
    line = f'U {n} yil matematika to‘garagiga qatnashgan.'
    made, _ = finish.apply(data, _answer(data, sections={part: {'body': line}}), file_names=[], codes=[])
    assert not _shows(_strings(made), f'{n} yil'), f'the earlier placing grounded the invented "{n} yil"'

# ---------------------------------------------------------------- a deck's cover lines (round 3 of the convergence)


@dataclass(frozen=True)
class Cover:
    id: str
    direction: str
    line: str
    said: str = ' Men 7-sinf o‘quvchisiman.'   # what the customer adds to the deck fixture's brief

    def __str__(self):
        return self.id


COVERS = [
    # A number and a letter are a class as a class label's value, as a cover line's whole value and beside a pupil's
    # word (must, regression from 0157a2a): the customer wrote "7-sinf", never a parallel.
    Cover('cover-class-letter-as-sinfs-value-uz-blank', BLANK, 'Sinf: 7B'),
    Cover('cover-class-letter-as-class-value-uz-blank', BLANK, 'Class: 7B'),
    Cover('cover-class-letter-as-the-whole-line-uz-blank', BLANK, '7B'),
    Cover('cover-class-letter-beside-a-pupils-word-uz-blank', BLANK, 'Bajardi: 7B o‘quvchisi'),
    Cover('cover-class-letter-quoted-uz-blank', BLANK, 'Sinf: 7-«B»'),
    Cover('cover-class-letter-before-sinf-uz-blank', BLANK, '7B sinf'),
    Cover('cover-the-customers-class-uz-keep', KEEP, 'Sinf: 7'),
    Cover('cover-the-customers-class-letter-uz-keep', KEEP, 'Sinf: 7B', said=' Men 7-«B» sinf o‘quvchisiman.'),
    Cover('cover-the-customers-1c-uz-keep', KEEP, '1C', said=' Mavzu 1С dasturi haqida.'),
    # A technology-shaped class letter is a class on a cover (must, from 595f182): Uzbek classes are lettered A, B, V,
    # G, D.
    Cover('cover-technology-shaped-letter-as-sinfs-value-uz-blank', BLANK,
          'Sinf: 5G', said=' Men 5-sinf o‘quvchisiman.'),
    Cover('cover-technology-shaped-letter-5g-as-the-whole-line-uz-blank', BLANK, '5G',
          said=' Men 5-sinf o‘quvchisiman.'),
    Cover('cover-technology-shaped-letter-3d-as-the-whole-line-uz-blank', BLANK, '3D',
          said=' Men 3-sinf o‘quvchisiman.'),
    Cover('cover-technology-shaped-letter-uzbek-cyrillic-brief-uz-blank', BLANK, '5G', said=' Men 5-синф ўқувчисиман.'),
]


def _deck_cover(cover):
    """(the cover's lines, codes) after finish.apply on the himoya deck fixture with `cover.line` added to its cover."""
    import json
    from pathlib import Path

    from apps.studio import title_lines
    from apps.studio.categories import sample
    fixture = json.loads((Path(__file__).parent / 'fixtures' / 'categories' / 'deck_himoya_figures.json')
                         .read_text(encoding='utf-8'))
    data, content = sample.draft(catalogue.get('slides.himoya'), fixture, 'uz', 10)
    content = title_lines.apply(data, content)
    data['prompt'] = str(data['prompt']) + cover.said
    content['sections'][0]['body'] = '\n'.join(['Bajardi: Yusupov Jasur, 412-guruh', cover.line, 'Toshkent — 2026'])
    codes = []
    finished, _ = finish.apply(data, content, file_names=[], codes=codes)
    return [line for line in finished['sections'][0]['body'].split('\n') if line.strip()], codes


@pytest.mark.parametrize('cover', COVERS, ids=[cover.id for cover in COVERS])
def test_a_deck_cover_line(cover):
    lines, codes = _deck_cover(cover)
    assert 'Bajardi: Yusupov Jasur, 412-guruh' in lines, 'the customer\'s own cover line stays'
    if cover.direction == KEEP:
        assert cover.line in lines, f'{cover.line!r} is the customer\'s and must stay on the cover: {lines!r}'
    else:
        assert cover.line not in lines and 'cover:line' in codes, f'{cover.line!r} reached the cover: {lines!r}'
