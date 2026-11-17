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
  so. A fix never keeps it by letting the pair leak.

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
from dataclasses import dataclass

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
        return finish.ground_paper(case.value, trusted, translated=translated)[0]
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
