"""Sample CVs for the template picker, the tests and reviewing templates by eye.

Dilnoza Karimova does not exist: the person, the employers and the contacts
are made up (the email and the website are on example.com). The short CV is
what every picker thumbnail shows: two roles, one degree, three skill groups,
three languages and a certificate, one page in every template. The long one —
six roles, three degrees, five skill groups, four languages, four projects,
five certificates and three extras — runs to two pages and is what the fit and
the side-column moves are tested on.

    python -m apps.studio.cv.sample --sheet out.png [--locale uz] [--long]

tiles all fifty templates (page 1, and page 2 beside it with --long), each id
under its tile;

    python -m apps.studio.cv.sample --check classic_navy [--locale ru] [--long]

renders one template and prints what `check.problems` finds.
"""
import functools
import io

LOCALES = ('en', 'uz', 'ru')


def _section(sid, heading='', body='', items=()):
    return {'id': sid, 'heading': heading, 'body': body, 'notes': '',
            'items': [{'label': label, 'text': text, 'value': value} for label, text, value in items]}


def _cv(name, headline, summary, contacts, experience, education, skills, languages, projects=(),
        certificates=(), extra_heading='', extra=()):
    return {'title': name, 'questions': [], 'citations': [], 'sections': [
        _section('profile', headline, summary, [(key, value, '') for key, value in contacts]),
        _section('experience', items=[(title, '\n'.join(lines), dates) for title, dates, lines in experience]),
        _section('education', items=[(degree, '\n'.join(lines), years) for degree, years, lines in education]),
        _section('skills', items=[(group, text, '') for group, text in skills]),
        _section('languages', items=[(language, level, '') for language, level in languages]),
        _section('projects', items=[(title, text, year) for title, year, text in projects]),
        _section('certificates', items=[(title, issuer, year) for title, year, issuer in certificates]),
        _section('extra', extra_heading if extra else '', items=[(title, text, year) for title, year, text in extra]),
    ]}


PHONE = '+998 90 123 45 67'
EMAIL = 'dilnoza.karimova@example.com'
TELEGRAM = '@dilnoza_sample'
LINKEDIN = 'linkedin.com/in/dilnoza-karimova-sample'
WEBSITE = 'dilnoza.example.com'

TEXT = {
    'en': {
        'name': 'Dilnoza Karimova',
        'location': 'Tashkent, Uzbekistan',
        'short_headline': 'Senior Data Analyst',
        'short_summary': (
            'Data analyst with six years of experience in retail and fintech, turning sales and customer data '
            'into decisions managers act on. Builds reporting from the warehouse to the dashboard, designs and '
            'reads A/B tests, and explains results in plain language. Looking for a senior role in a product '
            'team that values evidence over opinion.'),
        'long_headline': 'Head of Data Analytics',
        'long_summary': (
            'Analytics leader with ten years of experience in retail, fintech and logistics. Built and led a '
            'team of eight analysts and engineers, set up the company\'s first data warehouse and made weekly '
            'decisions measurably faster. At home anywhere from SQL to the boardroom: designs experiments, '
            'forecasts demand and turns findings into plans operations teams adopt. Mentors women starting '
            'careers in data.'),
        'roles': [
            ('Head of Data Analytics', '01.2023 – present', [
                'Registon Retail Group · Tashkent',
                'Lead a team of eight analysts and data engineers in three offices',
                'Launched a data warehouse serving 120 stores and 900 daily users',
                'Cut fresh-food write-offs by 18% with store-level demand forecasts',
                'Introduced quarterly analytics planning shared with every department']),
            ('Senior Data Analyst', '03.2021 – 12.2022', [
                'Registon Retail Group · Tashkent',
                'Built the weekly sales dashboard used by 40 store managers',
                'Ran 30 A/B tests on loyalty offers, lifting repeat purchases 7%',
                'Replaced manual Excel reports with automated Airflow pipelines',
                'Presented monthly results to the board in plain language']),
            ('Data Analyst', '07.2018 – 02.2021', [
                'Tumaris Fintech · Tashkent',
                'Designed the churn model adopted by the customer retention team',
                'Automated monthly risk reports, saving two analyst days a month',
                'Defined the product metrics for the mobile app launch',
                'Trained five colleagues in SQL and Power BI']),
            ('Business Intelligence Analyst', '09.2016 – 06.2018', [
                'Bodomzor Logistics · Tashkent',
                'Traced delivery delays and shortened average delivery time by a day',
                'Built fleet cost reports for the operations director',
                'Cleaned and merged data from four warehouse systems',
                'Supported the tender team with market and pricing analysis']),
            ('Junior Analyst', '08.2015 – 08.2016', [
                'Kamalak Telecom · Samarkand',
                'Prepared weekly subscriber reports for regional sales managers',
                'Tracked tariff campaign results across twelve districts',
                'Answered urgent data requests from marketing and finance',
                'Kept a shared dictionary of report definitions']),
            ('Analytics Intern', '06.2014 – 08.2014', [
                'Navruz Market Research · Tashkent',
                'Coded and checked survey answers from 2,000 households',
                'Built summary tables for a consumer confidence report',
                'Assisted interviewers during fieldwork in Tashkent region',
                'Presented findings on youth spending to the client team']),
        ],
        'short_roles': [
            ('Senior Data Analyst', '03.2021 – present', [
                'Registon Retail Group · Tashkent',
                'Built the weekly sales dashboard used by 40 store managers',
                'Cut fresh-food write-offs by 18% with a demand forecast',
                'Run A/B tests on loyalty offers and present results to the board']),
            ('Data Analyst', '07.2018 – 02.2021', [
                'Tumaris Fintech · Tashkent',
                'Automated monthly risk reports, saving two analyst days a month',
                'Designed the churn model adopted by the customer retention team',
                'Trained five colleagues in SQL and Power BI']),
        ],
        'short_degree': ('BSc in Economics and Statistics', '2014 – 2018', [
            'Westminster International University in Tashkent · Tashkent',
            'First-class honours; thesis on retail demand forecasting']),
        'degrees': [
            ('MSc in Data Science', '2019 – 2021', [
                'Inha University in Tashkent · Tashkent',
                'Thesis: forecasting retail demand with gradient boosting']),
            ('BSc in Economics', '2011 – 2015', [
                'Westminster International University in Tashkent · Tashkent', 'First-class honours']),
            ('Exchange semester in Statistics', '02.2014 – 06.2014', ['University of Warsaw · Warsaw, Poland']),
        ],
        'short_skills': [
            ('Analytics', 'SQL, Python (pandas), A/B testing, forecasting, cohort analysis'),
            ('Visualisation', 'Power BI, Tableau, Looker Studio'),
            ('Data tools', 'PostgreSQL, ClickHouse, Airflow, dbt, Git')],
        'skills': [
            ('Analytics', 'SQL, Python (pandas, scikit-learn), A/B testing, forecasting, cohort analysis'),
            ('Visualisation', 'Power BI, Tableau, Looker Studio, Excel'),
            ('Data engineering', 'PostgreSQL, ClickHouse, Airflow, dbt, Git, Docker'),
            ('Product and business', 'unit economics, product metrics, market sizing, pricing'),
            ('Leadership', 'hiring, mentoring, roadmap planning, stakeholder management')],
        'languages': [('Uzbek', 'native'), ('Russian', 'fluent'), ('English', 'C1 (IELTS 7.5)'), ('Turkish', 'B1')],
        'projects': [
            ('Fresh-food demand forecast', '2023',
             'Store-level forecast for 1,200 products; write-offs fell 18% in six months.'),
            ('Customer churn early warning', '2020',
             'Gradient boosting model that flags customers at risk two months ahead.'),
            ('Open transport dashboard', '2021',
             'Volunteer dashboard of Tashkent bus punctuality built on open data.'),
            ('Analytics course for beginners', '2024',
             'Eight-week evening course; 60 graduates, a third now work in data.')],
        'certificates': [
            ('Microsoft Certified: Power BI Data Analyst Associate', '2022', 'Microsoft'),
            ('Google Data Analytics Professional Certificate', '2021', 'Google, Coursera'),
            ('dbt Fundamentals', '2023', 'dbt Labs'),
            ('Machine Learning Specialization', '2020', 'Stanford Online, Coursera'),
            ('IELTS Academic, overall band 7.5', '2019', 'British Council')],
        'extra_heading': 'Volunteering and speaking',
        'extra': [
            ('Mentor, Women in Data Tashkent', '2022 – present', 'Mentor six early-career analysts every year.'),
            ('Speaker, Tashkent Data Meetup', '2023', 'Talk on forecasting fresh-food demand in retail.'),
            ('Volunteer tutor, Yunusabad Youth Centre', '2019 – 2021',
             'Taught school students spreadsheet basics at weekends.')],
    },
    'uz': {
        'name': 'Dilnoza Karimova',
        'location': 'Toshkent, O‘zbekiston',
        'short_headline': 'Yetakchi maʼlumotlar tahlilchisi',
        'short_summary': (
            'Chakana savdo va fintex sohalarida olti yillik tajribaga ega maʼlumotlar tahlilchisi. Savdo va '
            'mijozlar haqidagi maʼlumotlarni rahbarlar amalda tayanadigan qarorlarga aylantiraman: hisobotlarni '
            'maʼlumotlar omboridan dashbordgacha quraman, A/B testlar o‘tkazaman va natijalarni sodda tilda '
            'tushuntiraman. Taxmin emas, dalil qadrlanadigan mahsulot jamoasida yetakchi tahlilchi lavozimini '
            'izlayapman.'),
        'long_headline': 'Maʼlumotlar tahlili bo‘limi rahbari',
        'long_summary': (
            'Chakana savdo, fintex va logistika sohalarida o‘n yillik tajribaga ega tahlil rahbari. Sakkiz nafar '
            'tahlilchi va muhandisdan iborat jamoani shakllantirib boshqardim, kompaniyaning birinchi maʼlumotlar '
            'omborini yo‘lga qo‘ydim va haftalik qarorlarni sezilarli tezlashtirdim. SQL so‘rovlaridan tortib '
            'boshqaruv kengashigacha bemalol ishlayman: tajribalarni rejalashtiraman, talabni prognozlayman va '
            'xulosalarni jamoalar qabul qiladigan rejalarga aylantiraman. Data sohasiga kirib kelayotgan ayollarga '
            'murabbiylik qilaman.'),
        'roles': [
            ('Maʼlumotlar tahlili bo‘limi rahbari', '01.2023 – hozirgacha', [
                'Registon Retail Group · Toshkent',
                'Uch ofisdagi sakkiz nafar tahlilchi va maʼlumotlar muhandisiga rahbarlik qilaman',
                '120 do‘kon va kuniga 900 foydalanuvchi uchun maʼlumotlar omborini ishga tushirdim',
                'Do‘konlar kesimidagi talab prognozi bilan isrofni 18% ga kamaytirdim',
                'Barcha bo‘limlar bilan choraklik tahlil rejasini tuzishni joriy etdim']),
            ('Yetakchi maʼlumotlar tahlilchisi', '03.2021 – 12.2022', [
                'Registon Retail Group · Toshkent',
                '40 ta do‘kon rahbari foydalanadigan haftalik savdo dashbordini yaratdim',
                'Sodiqlik takliflarida 30 ta A/B test o‘tkazib, takroriy xaridni 7% ga oshirdim',
                'Qo‘lda tuziladigan Excel hisobotlari o‘rniga Airflow asosida avtomatik jarayonlar qurdim',
                'Oylik natijalarni boshqaruv kengashiga sodda tilda taqdim etdim']),
            ('Maʼlumotlar tahlilchisi', '07.2018 – 02.2021', [
                'Tumaris Fintech · Toshkent',
                'Mijozlar ketishini bashorat qiluvchi model yaratdim, uni saqlash bo‘limi joriy etdi',
                'Oylik risk hisobotlarini avtomatlashtirib, har oy ikki ish kunini tejadim',
                'Mobil ilovani ishga tushirish uchun mahsulot ko‘rsatkichlarini belgiladim',
                'Besh nafar hamkasbimni SQL va Power BI bo‘yicha o‘qitdim']),
            ('BI tahlilchisi', '09.2016 – 06.2018', [
                'Bodomzor Logistics · Toshkent',
                'Yetkazib berishdagi kechikishlar sababini topib, o‘rtacha muddatni bir kunga qisqartirdim',
                'Operatsion direktor uchun avtopark xarajatlari hisobotlarini tuzdim',
                'To‘rtta ombor tizimidagi maʼlumotlarni tozalab, yagona bazaga birlashtirdim',
                'Tender jamoasini bozor va narxlar tahlili bilan qo‘llab-quvvatladim']),
            ('Kichik tahlilchi', '08.2015 – 08.2016', [
                'Kamalak Telecom · Samarqand',
                'Hududiy savdo menejerlari uchun haftalik abonentlar hisobotini tayyorladim',
                'O‘n ikki tumanda tarif kampaniyalari natijalarini kuzatib bordim',
                'Marketing va moliya bo‘limlarining shoshilinch so‘rovlariga javob berdim',
                'Hisobot ko‘rsatkichlari uchun umumiy lug‘at yuritdim']),
            ('Tahlil bo‘yicha stajyor', '06.2014 – 08.2014', [
                'Navro‘z Market Research · Toshkent',
                '2000 ta xonadon so‘rovnomasi javoblarini kodladim va tekshirdim',
                'Isteʼmolchilar ishonchi hisoboti uchun yig‘ma jadvallar tuzdim',
                'Toshkent viloyatidagi dala ishlarida intervyuchilarga yordam berdim',
                'Yoshlar xarajatlari bo‘yicha xulosalarni mijoz jamoasiga taqdim etdim']),
        ],
        'short_roles': [
            ('Yetakchi maʼlumotlar tahlilchisi', '03.2021 – hozirgacha', [
                'Registon Retail Group · Toshkent',
                '40 ta do‘kon rahbari foydalanadigan haftalik savdo dashbordini yaratdim',
                'Tez buziladigan mahsulotlarga talab prognozi bilan isrofni 18% ga kamaytirdim',
                'Sodiqlik takliflari bo‘yicha A/B testlar o‘tkazib, natijalarni boshqaruvga taqdim etaman']),
            ('Maʼlumotlar tahlilchisi', '07.2018 – 02.2021', [
                'Tumaris Fintech · Toshkent',
                'Oylik risk hisobotlarini avtomatlashtirib, har oy ikki ish kunini tejadim',
                'Mijozlar ketishini bashorat qiluvchi model yaratdim, uni saqlash bo‘limi joriy etdi',
                'Besh nafar hamkasbimni SQL va Power BI bo‘yicha o‘qitdim']),
        ],
        'short_degree': ('Iqtisodiyot va statistika bakalavri', '2014 – 2018', [
            'Toshkent shahridagi Xalqaro Vestminster universiteti · Toshkent',
            'Imtiyozli diplom; bitiruv ishi chakana savdoda talabni prognozlash haqida']),
        'degrees': [
            ('Maʼlumotlar ilmi (Data Science) magistri', '2019 – 2021', [
                'Toshkent shahridagi Inha universiteti · Toshkent',
                'Dissertatsiya: chakana savdoda talabni gradiyent busting yordamida prognozlash']),
            ('Iqtisodiyot bakalavri', '2011 – 2015', [
                'Toshkent shahridagi Xalqaro Vestminster universiteti · Toshkent', 'Imtiyozli diplom']),
            ('Statistika bo‘yicha almashinuv semestri', '02.2014 – 06.2014', ['Varshava universiteti · Varshava, Polsha']),
        ],
        'short_skills': [
            ('Tahlil', 'SQL, Python (pandas), A/B testlar, prognozlash, kogort tahlili'),
            ('Vizualizatsiya', 'Power BI, Tableau, Looker Studio'),
            ('Maʼlumotlar vositalari', 'PostgreSQL, ClickHouse, Airflow, dbt, Git')],
        'skills': [
            ('Tahlil', 'SQL, Python (pandas, scikit-learn), A/B testlar, prognozlash, kogort tahlili'),
            ('Vizualizatsiya', 'Power BI, Tableau, Looker Studio, Excel'),
            ('Maʼlumotlar muhandisligi', 'PostgreSQL, ClickHouse, Airflow, dbt, Git, Docker'),
            ('Mahsulot va biznes', 'unit-iqtisodiyot, mahsulot ko‘rsatkichlari, bozor hajmini baholash, narx siyosati'),
            ('Rahbarlik', 'xodim tanlash, murabbiylik, yo‘l xaritasini rejalashtirish, hamkorlar bilan muloqot')],
        'languages': [('O‘zbek tili', 'ona tili'), ('Rus tili', 'erkin'), ('Ingliz tili', 'C1 (IELTS 7.5)'),
                      ('Turk tili', 'B1')],
        'projects': [
            ('Tez buziladigan mahsulotlar talabi prognozi', '2023',
             '1200 ta mahsulot bo‘yicha do‘konlar kesimidagi prognoz; olti oyda isrof 18% ga kamaydi.'),
            ('Mijozlar ketishini erta aniqlash', '2020',
             'Xavf ostidagi mijozlarni ikki oy oldin aniqlaydigan gradiyent busting modeli.'),
            ('Ochiq transport dashbordi', '2021',
             'Toshkent avtobuslari qatnovining aniqligini ochiq maʼlumotlar asosida ko‘rsatuvchi ko‘ngilli loyiha.'),
            ('Boshlovchilar uchun tahlil kursi', '2024',
             'Sakkiz haftalik kechki kurs: 60 nafar bitiruvchi, ularning uchdan biri hozir data sohasida ishlaydi.')],
        'certificates': [
            ('Microsoft Certified: Power BI Data Analyst Associate', '2022', 'Microsoft'),
            ('Google Data Analytics Professional Certificate', '2021', 'Google, Coursera'),
            ('dbt Fundamentals', '2023', 'dbt Labs'),
            ('Machine Learning Specialization', '2020', 'Stanford Online, Coursera'),
            ('IELTS Academic, umumiy ball 7.5', '2019', 'British Council')],
        'extra_heading': 'Ko‘ngillilik va chiqishlar',
        'extra': [
            ('Murabbiy, Women in Data Tashkent hamjamiyati', '2022 – hozirgacha',
             'Har yili oltita boshlovchi tahlilchiga murabbiylik qilaman.'),
            ('Maʼruzachi, Tashkent Data Meetup', '2023',
             'Chakana savdoda tez buziladigan mahsulotlar talabini prognozlash haqida maʼruza.'),
            ('Ko‘ngilli o‘qituvchi, Yunusobod yoshlar markazi', '2019 – 2021',
             'Dam olish kunlari maktab o‘quvchilariga elektron jadvallar asoslarini o‘rgatdim.')],
    },
    'ru': {
        'name': 'Дильноза Каримова',
        'location': 'Ташкент, Узбекистан',
        'short_headline': 'Старший аналитик данных',
        'short_summary': (
            'Аналитик данных с шестилетним опытом в ритейле и финтехе. Превращаю данные о продажах и клиентах '
            'в решения, на которые опираются руководители: строю отчётность от хранилища до дашборда, провожу '
            'A/B-тесты и объясняю результаты простым языком. Ищу позицию старшего аналитика в продуктовой '
            'команде, где решения принимают на основе данных.'),
        'long_headline': 'Руководитель отдела аналитики данных',
        'long_summary': (
            'Руководитель аналитики с десятилетним опытом в ритейле, финтехе и логистике. Собрала и возглавила '
            'команду из восьми аналитиков и инженеров данных, запустила первое в компании хранилище данных и '
            'заметно ускорила еженедельные решения. Уверенно работаю на всех уровнях — от SQL-запросов до совета '
            'директоров: планирую эксперименты, прогнозирую спрос и превращаю выводы в планы, которые принимают '
            'операционные команды. Наставляю женщин, которые начинают карьеру в данных.'),
        'roles': [
            ('Руководитель отдела аналитики данных', '01.2023 – наст. время', [
                'Registon Retail Group · Ташкент',
                'Руковожу командой из восьми аналитиков и инженеров данных в трёх офисах',
                'Запустила хранилище данных для 120 магазинов и 900 пользователей в день',
                'Снизила списания свежих продуктов на 18% благодаря прогнозу спроса',
                'Ввела ежеквартальное планирование аналитики вместе со всеми отделами']),
            ('Старший аналитик данных', '03.2021 – 12.2022', [
                'Registon Retail Group · Ташкент',
                'Создала еженедельный дашборд продаж для 40 директоров магазинов',
                'Провела 30 A/B-тестов программ лояльности: повторные покупки выросли на 7%',
                'Заменила ручные отчёты в Excel автоматическими пайплайнами на Airflow',
                'Ежемесячно докладывала правлению итоги простым языком']),
            ('Аналитик данных', '07.2018 – 02.2021', [
                'Tumaris Fintech · Ташкент',
                'Разработала модель оттока клиентов, которую внедрил отдел удержания',
                'Автоматизировала ежемесячные отчёты по рискам и сэкономила два рабочих дня',
                'Определила продуктовые метрики к запуску мобильного приложения',
                'Обучила пятерых коллег SQL и Power BI']),
            ('BI-аналитик', '09.2016 – 06.2018', [
                'Bodomzor Logistics · Ташкент',
                'Нашла причины задержек доставки и сократила средний срок на день',
                'Подготовила отчёты по затратам автопарка для операционного директора',
                'Очистила и объединила данные четырёх складских систем',
                'Поддерживала тендерную команду анализом рынка и цен']),
            ('Младший аналитик', '08.2015 – 08.2016', [
                'Kamalak Telecom · Самарканд',
                'Готовила еженедельные отчёты по абонентам для региональных менеджеров',
                'Отслеживала результаты тарифных кампаний в двенадцати районах',
                'Отвечала на срочные запросы данных от маркетинга и финансов',
                'Вела общий словарь показателей для всех отчётов']),
            ('Стажёр-аналитик', '06.2014 – 08.2014', [
                'Navruz Market Research · Ташкент',
                'Кодировала и проверяла ответы анкет 2000 домохозяйств',
                'Составила сводные таблицы для отчёта о потребительском доверии',
                'Помогала интервьюерам в полевых работах в Ташкентской области',
                'Представила клиенту выводы о расходах молодёжи']),
        ],
        'short_roles': [
            ('Старший аналитик данных', '03.2021 – наст. время', [
                'Registon Retail Group · Ташкент',
                'Создала еженедельный дашборд продаж для 40 директоров магазинов',
                'Снизила списания свежих продуктов на 18% благодаря прогнозу спроса',
                'Провожу A/B-тесты программ лояльности и докладываю итоги правлению']),
            ('Аналитик данных', '07.2018 – 02.2021', [
                'Tumaris Fintech · Ташкент',
                'Автоматизировала ежемесячные отчёты по рискам и сэкономила два рабочих дня',
                'Разработала модель оттока клиентов, которую внедрил отдел удержания',
                'Обучила пятерых коллег SQL и Power BI']),
        ],
        'short_degree': ('Бакалавр экономики и статистики', '2014 – 2018', [
            'Международный Вестминстерский университет в Ташкенте · Ташкент',
            'Диплом с отличием; выпускная работа о прогнозировании спроса в ритейле']),
        'degrees': [
            ('Магистр в области Data Science', '2019 – 2021', [
                'Университет Инха в Ташкенте · Ташкент',
                'Диссертация: прогнозирование спроса в ритейле с помощью градиентного бустинга']),
            ('Бакалавр экономики', '2011 – 2015', [
                'Международный Вестминстерский университет в Ташкенте · Ташкент', 'Диплом с отличием']),
            ('Семестр по обмену: статистика', '02.2014 – 06.2014', ['Варшавский университет · Варшава, Польша']),
        ],
        'short_skills': [
            ('Аналитика', 'SQL, Python (pandas), A/B-тесты, прогнозирование, когортный анализ'),
            ('Визуализация', 'Power BI, Tableau, Looker Studio'),
            ('Инструменты данных', 'PostgreSQL, ClickHouse, Airflow, dbt, Git')],
        'skills': [
            ('Аналитика', 'SQL, Python (pandas, scikit-learn), A/B-тесты, прогнозирование, когортный анализ'),
            ('Визуализация', 'Power BI, Tableau, Looker Studio, Excel'),
            ('Инженерия данных', 'PostgreSQL, ClickHouse, Airflow, dbt, Git, Docker'),
            ('Продукт и бизнес', 'юнит-экономика, продуктовые метрики, оценка рынка, ценообразование'),
            ('Управление', 'найм, наставничество, планирование дорожной карты, работа со стейкхолдерами')],
        'languages': [('Узбекский', 'родной'), ('Русский', 'свободно'), ('Английский', 'C1 (IELTS 7.5)'),
                      ('Турецкий', 'B1')],
        'projects': [
            ('Прогноз спроса на свежие продукты', '2023',
             'Прогноз по 1200 товарам на уровне магазина: за полгода списания снизились на 18%.'),
            ('Раннее выявление оттока клиентов', '2020',
             'Модель градиентного бустинга, которая за два месяца предупреждает о риске ухода клиента.'),
            ('Открытый транспортный дашборд', '2021',
             'Волонтёрский дашборд пунктуальности ташкентских автобусов на открытых данных.'),
            ('Курс аналитики для начинающих', '2024',
             'Восьминедельный вечерний курс: 60 выпускников, треть из них уже работает с данными.')],
        'certificates': [
            ('Microsoft Certified: Power BI Data Analyst Associate', '2022', 'Microsoft'),
            ('Google Data Analytics Professional Certificate', '2021', 'Google, Coursera'),
            ('dbt Fundamentals', '2023', 'dbt Labs'),
            ('Machine Learning Specialization', '2020', 'Stanford Online, Coursera'),
            ('IELTS Academic, общий балл 7.5', '2019', 'British Council')],
        'extra_heading': 'Волонтёрство и выступления',
        'extra': [
            ('Наставник, сообщество Women in Data Tashkent', '2022 – наст. время',
             'Каждый год веду шестерых начинающих аналитиков.'),
            ('Спикер, Tashkent Data Meetup', '2023',
             'Доклад о прогнозировании спроса на свежие продукты в ритейле.'),
            ('Волонтёр-преподаватель, молодёжный центр Юнусабада', '2019 – 2021',
             'По выходным учила школьников основам работы с электронными таблицами.')],
    },
}


def _text(locale):
    return TEXT[locale if locale in TEXT else 'en']


def short(locale='en'):
    """Two roles, one degree, three skill groups, three languages, one certificate: one page everywhere."""
    t = _text(locale)
    contacts = [('phone', PHONE), ('email', EMAIL), ('location', t['location']), ('telegram', TELEGRAM)]
    return _cv(t['name'], t['short_headline'], t['short_summary'], contacts, t['short_roles'], [t['short_degree']],
               t['short_skills'], t['languages'][:3], certificates=t['certificates'][:1])


def long(locale='en'):
    """Six roles of four lines, three degrees, five skill groups, four languages, projects, certificates, extras."""
    t = _text(locale)
    contacts = [('phone', PHONE), ('email', EMAIL), ('location', t['location']), ('telegram', TELEGRAM),
                ('linkedin', LINKEDIN), ('website', WEBSITE)]
    return _cv(t['name'], t['long_headline'], t['long_summary'], contacts, t['roles'], t['degrees'], t['skills'],
               t['languages'], t['projects'], t['certificates'], t['extra_heading'], t['extra'])


# More than any sidebar holds: what the side-column moves are tested on.
MORE_SKILLS = {
    'en': [('Statistics', 'regression, time series, hypothesis testing, sampling'),
           ('Cloud', 'BigQuery, AWS S3, Yandex Cloud'),
           ('Machine learning', 'scikit-learn, CatBoost, feature engineering'),
           ('Documentation', 'Confluence, Notion, data dictionaries')],
    'uz': [('Statistika', 'regressiya, vaqt qatorlari, gipotezalarni tekshirish, tanlanma'),
           ('Bulutli xizmatlar', 'BigQuery, AWS S3, Yandex Cloud'),
           ('Mashinali o‘qitish', 'scikit-learn, CatBoost, belgilarni tayyorlash'),
           ('Hujjatlashtirish', 'Confluence, Notion, maʼlumotlar lug‘atlari')],
    'ru': [('Статистика', 'регрессия, временные ряды, проверка гипотез, выборки'),
           ('Облака', 'BigQuery, AWS S3, Yandex Cloud'),
           ('Машинное обучение', 'scikit-learn, CatBoost, подготовка признаков'),
           ('Документация', 'Confluence, Notion, словари данных')],
}
MORE_LANGUAGES = {
    'en': [('German', 'A2'), ('Korean', 'A1')],
    'uz': [('Nemis tili', 'A2'), ('Koreys tili', 'A1')],
    'ru': [('Немецкий', 'A2'), ('Корейский', 'A1')],
}


def crowded(locale='en'):
    """The long CV with nine skill groups and six languages."""
    content = long(locale)
    locale = locale if locale in TEXT else 'en'
    for section in content['sections']:
        if section['id'] == 'skills':
            section['items'] += [{'label': label, 'text': text, 'value': ''} for label, text in MORE_SKILLS[locale]]
        if section['id'] == 'languages':
            section['items'] += [{'label': label, 'text': text, 'value': ''} for label, text in MORE_LANGUAGES[locale]]
    return content


def many_roles(locale='en', count=12):
    """The long CV with `count` roles: more than two pages hold, so the fit has to cut."""
    content = long(locale)
    roles = _text(locale)['roles']
    for section in content['sections']:
        if section['id'] == 'experience':
            section['items'] = [{'label': title, 'text': '\n'.join(lines), 'value': dates}
                                for title, dates, lines in (roles * (count // len(roles) + 1))[:count]]
    return content


@functools.lru_cache(maxsize=1)
def portrait():
    """A grey silhouette, 600 × 600 JPEG bytes: a portrait slot filled, with nobody's face in it."""
    from PIL import Image, ImageDraw, ImageFilter
    image = Image.new('RGB', (600, 600), '#D5DBE1')
    draw = ImageDraw.Draw(image)
    draw.ellipse((95, 395, 505, 830), fill='#8E99A6')
    draw.rectangle((255, 330, 345, 430), fill='#8E99A6')
    draw.ellipse((190, 120, 410, 370), fill='#8E99A6')
    image = image.filter(ImageFilter.GaussianBlur(1.2))
    buffer = io.BytesIO()
    image.save(buffer, 'JPEG', quality=88)
    return buffer.getvalue()


def required(content, locale='en'):
    """The strings a rendered CV must show: the name, every contact, every skill group and language."""
    from .layouts import shown_contact
    from .render import _contact_key
    found = [content['title']]
    for section in content['sections']:
        if section['id'] == 'profile':
            found += [shown_contact(_contact_key(item['label']), item['text']) for item in section['items']]
        if section['id'] in ('skills', 'languages'):
            found += [item['label'] for item in section['items']]
    return found


def render(template, path, *, locale='en', variant='short', photo=None):
    """Render a sample (`short`, `long`, `crowded` or `many_roles`) in `template`; returns render_cv's result."""
    from .render import render_cv
    from .templates import TEMPLATES
    content = {'short': short, 'long': long, 'crowded': crowded, 'many_roles': many_roles}[variant](locale)
    if photo is None:
        photo = TEMPLATES[template]['photo']
    return render_cv(content, path, locale=locale, style={'cv_template': template},
                     portrait=portrait() if photo else None)


def _pages(path, width):
    import pypdfium2
    document = pypdfium2.PdfDocument(str(path))
    try:
        return [document[index].render(scale=width / 595.27).to_pil().convert('RGB') for index in range(len(document))]
    finally:
        document.close()


def sheet(out, *, locale='en', variant='short', width=300, ids=None):
    """A contact sheet of every template (or `ids`): page 1, and page 2 beside it for a two-page sample."""
    import tempfile
    from pathlib import Path
    from PIL import Image, ImageDraw, ImageFont
    from . import fonts
    from .templates import TEMPLATE_IDS
    ids = list(ids or TEMPLATE_IDS)
    pages_shown = 1 if variant == 'short' else 2
    height = round(width * 841.89 / 595.27)
    label, gap = 30, 16
    tile_w = width * pages_shown + (8 if pages_shown == 2 else 0)
    columns = 10 if pages_shown == 1 else 5
    rows = (len(ids) + columns - 1) // columns
    canvas = Image.new('RGB', (columns * (tile_w + gap) + gap, rows * (height + label + gap) + gap), '#E6E8EB')
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(str(fonts.path('CVSans-Bold')), 15)
    with tempfile.TemporaryDirectory() as folder:
        for index, key in enumerate(ids):
            path = Path(folder) / f'{key}.pdf'
            result = render(key, path, locale=locale, variant=variant)
            x = gap + (index % columns) * (tile_w + gap)
            y = gap + (index // columns) * (height + label + gap)
            for number, page in enumerate(_pages(path, width)[:pages_shown]):
                canvas.paste(page, (x + number * (width + 8), y))
            note = f'{key}  ·  {result["page_count"]}p  s{result["metadata"]["fit_step"]}'
            if result['metadata']['trimmed']:
                note += '  trim'
            if result['metadata']['sidebar_moved']:
                note += '  moved:' + ','.join(result['metadata']['sidebar_moved'])
            draw.text((x, y + height + 6), note, fill='#1A1A1A', font=font)
    canvas.save(out, 'PNG', optimize=True)
    return out


def main(argv=None):
    import argparse
    import tempfile
    from pathlib import Path
    parser = argparse.ArgumentParser(prog='python -m apps.studio.cv.sample', description=__doc__.split('\n')[0])
    parser.add_argument('--sheet', metavar='OUT.png')
    parser.add_argument('--check', metavar='TEMPLATE')
    parser.add_argument('--locale', default='en', choices=LOCALES)
    parser.add_argument('--long', action='store_true')
    parser.add_argument('--variant', choices=('short', 'long', 'crowded', 'many_roles'))
    parser.add_argument('--pages', metavar='DIR', help='with --check: also write each page as a PNG here')
    args = parser.parse_args(argv)
    variant = args.variant or ('long' if args.long else 'short')
    if args.sheet:
        print(sheet(args.sheet, locale=args.locale, variant=variant))
    if args.check:
        from .check import problems
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / f'{args.check}.pdf'
            result = render(args.check, path, locale=args.locale, variant=variant)
            content = {'short': short, 'long': long, 'crowded': crowded, 'many_roles': many_roles}[variant](args.locale)
            found = problems(path, result['metadata']['frames'], required(content, args.locale))
            meta = result['metadata']
            print(f'{args.check} {args.locale} {variant}: {result["page_count"]} page(s), step {meta["fit_step"]}, '
                  f'trimmed {meta["trimmed"] or "nothing"}, moved {meta["sidebar_moved"] or "nothing"}')
            print('\n'.join(found) if found else 'no problems')
            if args.pages:
                for number, page in enumerate(_pages(path, 1240), 1):
                    target = Path(args.pages) / f'{args.check}-{args.locale}-{variant}-p{number}.png'
                    page.save(target)
                    print(target)
    if not (args.sheet or args.check):
        parser.print_help()


if __name__ == '__main__':
    main()
