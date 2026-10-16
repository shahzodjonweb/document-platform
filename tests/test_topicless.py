"""A new AI document whose description names no topic is refused before it is made.

"12 ta slayd kk", "Ko‘k rangda bo‘lsin 12 betlik", "Mavzuga oid PDF yasab ber":
sent to the model, a request like this either came back with a subject the
model made up, spending a weekly document on it, or failed with a reply too
thin to pass the checks. Now the customer is told what is missing, and which
tool to use when the description asks for the other format. Nothing is
counted. A change request, a draft with source files or pasted text, and a
draft already accepted are never refused.

Every prompt here is written for the test; none is a customer's.
"""
import json
import time

import pytest

from apps.core.allowance import ai_documents_this_week, usage_snapshot
from apps.core.errors import DomainError, error_data
from apps.core.models import Account, Quote
from apps.studio.domain import DOCUMENT, SLIDES, create_draft, unpack, update_draft
from apps.studio.models import GenerationDraft
from apps.studio.topics import asked_other_service, asks_to_convert, explain, names_no_topic, restates
from tests.test_platform import account, login_client, upload

pytestmark = pytest.mark.django_db

# --- What names no topic ----------------------------------------------------------

NO_TOPIC = [
    # The shapes that failed or invented a topic, reworded.
    'Mavxuga oid pdf tayyorlab ber', 'Yorqin slaydlar yasab bering', 'pdfga otqazib ber', '14 ta slayd kk',
    '8 betlik boʻlsin', 'Yashil rangda boʻlsin 10 betlik',
    '20 ta betlik bo‘lsin qizil rangda bo‘lsin chiroyli chiqsin',
    # The tools' own names, echoed back.
    'Mavzuga oid PDF', 'Mavzuga oid Slayd', 'PDF hujjat', 'PowerPoint slaydlar', 'PDF on a topic',
    'Slides on a topic', 'PDF Document', 'PowerPoint Slides', 'PDF по теме', 'Слайды по теме', 'PDF документ',
    'PowerPoint слайды',
    # The word "topic" with nothing after it.
    'mavzu: ', 'Mavzu:', 'Topic:', 'topic: ', 'Тема:', 'Мавзу:', 'presentation about', 'презентация на тему',
    # English.
    'make a pdf', 'a nice document please', 'Make me a beautiful presentation with pictures', '10 slides please',
    'I need a 5 page document', 'create slides in blue', 'write an essay for university',
    'Generate 12 slides, modern design',
    # Russian.
    'сделай презентацию', 'красивые слайды на 10 страниц', 'Нужно 8 слайдов',
    'сделайте реферат на 5 страниц пожалуйста',
    'презентация в синих тонах на 12 слайдов', 'Нужен доклад для урока', 'сделай презентацию по-английски',
    # Uzbek in Cyrillic.
    'слайд тайёрлаб бер', '10 та слайд керак', 'чиройли презентация тайёрлаб беринг', 'мавзуга оид слайд',
    'Яшил рангда бўлсин 15 бетлик',
    # Uzbek in Latin: counts, looks, parts, audiences and languages, all of them instructions.
    'Ochiq darsga 10 ta slayd kerak. Har slaydda tushuntirish va misol, oxirida 5 ta savol. '
    'Ko‘k rangda chiroyli chiqsin.',
    'Universitetga mustaqil ish kerak, 10 sahifa. Ilmiy uslubda yozing', 'Rasmlar bilan 10 ta slayd',
    'referat yozib ber', 'Ingliz tilida 10 ta slayd', "bo'lsin 12 ta", 'pdf qilib ber', 'word ga otkazib ber',
    'o‘zbek tilida 15 ta slayd tayyorlab ber', 'och pushti va binafsharang rangda 10 slayd', 'chiroyli dizayn 10 slayd',
    '7-sinf uchun 10 ta slayd', 'slayd tuz', '10 ta slayd zamonaviy dizaynda', 'Yorqin ranglarda slayd kerak',
    'pdf kerak', 'Rasmlar ham bo‘lsin, 10 bet', 'Sahifalar soni 16 ta', 'mavzuga oid rasmlar bilan slayd',
    # Every way o‘ is typed.
    "Ko'k rangda bo'lsin 9 betlik", 'Ko‘k rangda bo‘lsin 9 betlik', 'Koʼk rangda boʼlsin 9 betlik',
    'Kok rangda bolsin 9 betlik', 'Kók rangda bólsin 9 betlik', 'Ko`k rangda bo`lsin 9 betlik',
    'Koʻk rangda boʻlsin 9 betlik',
    # Typing slips: a letter doubled, dropped, swapped or wrong.
    'slyad kerak 10 ta', 'slayt kerak 10 ta', 'slaydd kerakk', 'chiroooyli prezintatsiya qilib bering',
    'презинтацию сделай', 'chroyli slayd kerak', 'mavzuya oid slayd', 'Mavzga oid pdf yasang',
    # Filler that says nothing ("edi", "tez", "пж"), and the slot words with "topic" in the slot.
    'slayd kerak edi', 'referat kerak edi', 'Slayd kerak edi 10 ta', 'prezentatsiya kerak tez', 'tezroq slayd kerak',
    'slayd kk tez', 'slayd qilib bera olasizmi', 'презентацию сделай пж', 'сделай презу', 'Can you make a presentation',
    'Kurs ishi kerak', 'prezintatsya kerak', 'Mavzu bo‘yicha slayd', "Mavzu bo'yicha referat", 'Mavzu asosida slayd',
    'Mavzu to‘g‘risida 10 ta slayd',
    # Colours that are things first still bind before a colour noun; "light" leads a colour.
    'Oltin rangda 10 slayd', 'Havo rang slayd', 'create slides in light blue',
    # Read a line at a time, an instruction on one line still binds on it.
    'in blue\n10 slides please',
]

NAMES_A_TOPIC = [
    # English: a subject, however short, and look words used as subjects.
    'make a pdf about photosynthesis', 'presentation about design', '10 slides on the French Revolution', 'Colours',
    'Blue whales', 'Design', 'slides about beautiful design', 'Present simple', 'Red Book 10 slides', 'Summer',
    'Light and dark 10 slides', 'Present perfect tense 10 slides', 'Paper', 'English',
    # The examples the refusal itself gives.
    'The water cycle, 5 pages for 6th grade', 'Tabiatda suvning aylanishi, 6-sinf uchun 5 bet',
    'Круговорот воды в природе, 5 страниц для 6 класса',
    # Russian.
    'презентация про фотосинтез', 'презентация на тему экология', 'Дизайн интерьера 10 слайдов', 'Красная книга',
    'Цвета', 'презентация о дизайне', 'Фотосинтез', 'Сердце человека', 'Русский язык 5 класс',
    'Нужно 10 слайдов по истории', 'Тема: Дизайн', 'Цветы', 'Цветные металлы', 'Белый медведь',
    # Uzbek in Cyrillic.
    'Амир Темур ҳақида слайд тайёрлаб бер', 'Тил ҳақида 10 бет', 'Туз', 'Ранглар ҳақида слайд',
    # Uzbek in Latin.
    'Mavzu: Amir Temur', 'Mavzu: Rasm', 'Mavzu - Suv', 'Ranglar', 'Ranglar haqida slayd', 'Rasm',
    'Dizayn haqida slayd', 'Qizil kitob 10 ta slayd', "Ko'k", 'Tuz', 'Yoz fasli', 'Til', 'Rus tili',
    'Oltin O‘rda 10 slayd', 'Yashil iqtisodiyot', 'Kitob', 'Ishsizlik', 'Fotosintez', 'Rasmiy hujjatlar',
    'Present perfect 10 slayd', 'Ingliz tili 5-sinf 10 ta slayd', 'Ona tili', 'Matematika 10 slayd', 'Mustaqillik',
    "Yasama yo'ldosh", "So'z yasalishi", 'Qoʻqon xonligi 10 slayd', 'Kasb tanlash', 'Ranglar 10 ta slayd',
    'Oila', 'Slayd dizayni', 'Qizil rang', 'Oq va qora', 'Qora dengiz', 'Oq oltin', 'Yorqin kelajak', 'Sodda gap',
    'Oddiy kasrlar', 'Ingliz tili 10 ta slayd', 'Interyer dizayni', 'Rasm chizish', 'Test', 'Matn',
    'Sinf rahbari', 'PowerPoint dasturida slayd yaratish', 'Taqdimot tayyorlash', 'Kitob o‘qish', 'Bayroq ranglari',
    'Bolalar psixologiyasi', 'Mehnat', 'Vatan', 'Dars', 'Maktab', 'Chiroy haqida 5 bet', 'Buyuk mutafakkirlar',
    'Amir Temur hayoti 10 ta slayd yasab ber', 'Zilzila haqida 6 list kitob',
    # A word one letter from a request word is still a word: "yashab" is living, not making.
    'Yashab qolish 10 ta slayd',
    # A quoted title, and a year (a count never has four digits).
    'slayd "Mening oilam"', '«Alpomish» dostoni 10 ta slayd', '1945', 'Mavzu: 1945',
    # Long descriptions with one subject in them.
    'Iltimos, 15 ta slayd tayyorlab bering, chiroyli dizaynda, rasmlar bilan. Mavzusi: quyosh tizimi sayyoralari.',
    'Нужна презентация на 12 слайдов в синих тонах про вулканы, с картинками и выводом в конце',
    # Nouns that begin like a Russian colour: a colour is an adjective, in its own forms.
    'Синонимы презентация', 'Синтаксис презентация', 'Синус презентация', 'Синтез белка презентация',
    'Сингапур презентация', 'Беларусь презентация', 'Белки презентация', 'Бельгия презентация', 'Белка презентация',
    'Чернобыль презентация', 'Черногория презентация', 'Черника презентация', 'Красноярск презентация',
    'Краснодар презентация', 'Голуби презентация', 'Желтуха презентация', 'Желток презентация',
    'Светлана презентация', 'Сердце презентация', 'Серебро презентация', 'Сербия презентация', 'Сервер презентация',
    'Сериалы презентация', 'Сера презентация', 'Чернозём презентация', 'Синица презентация',
    # Things first, colours only before a colour noun; "past" is no colour at all.
    'Havo slayd', 'Havo taqdimot', 'Havo referat', 'Ҳаво слайд', 'Oltin slayd', 'Oltin referat', 'Олтин слайд',
    'Kumush referat', 'Oq oltin slayd', 'Feruza slayd', 'Past simple slides', 'Past Simple 10 slides',
    'Simple past slides', 'Past simple presentation', 'Past simple slayd', 'US Navy presentation', 'Light presentation',
    # Subjects a prefix or a folded letter once swallowed.
    'Faylasuflar 10 ta slayd', 'Faylasuflar haqida slayd', 'Faylasuf slayd', 'Файласуфлар слайд', 'Inshootlar slayd',
    'Inshootlar 10 ta slayd', 'Документооборот презентация', 'Документооборот 10 слайдов', 'Штукатурка презентация',
    'Подготовка к школе презентация', 'Подготовка презентация', 'Цветник презентация', 'Soda slayd',
    'Soda 10 ta slayd', 'Сода презентация', 'Bee presentation', 'Beer presentation', 'Anna presentation',
    # A format named as the topic.
    'Word', 'WORD', 'PowerPoint', 'Ворд', 'Mavzu: Word', 'Mavzu: PowerPoint', 'Mavzu: PDF', 'Mavzu: Slayd', 'Тема: Word', 'Тема: Презентация',
    'Word haqida slayd', 'Word haqida referat', 'PowerPoint haqida 10 ta slayd', 'PowerPoint haqida slayd',
    # English lessons named by their words, and "How to …" titles.
    'Some and any slides', 'Some and any 10 slides', 'Much and many presentation', 'Much and many slides',
    'Can and could slides', 'Can and could 10 slides', 'Will and would presentation', 'Have and has 10 slides',
    'Was and were slides', 'In on at slides', 'In, on, at 10 slides', 'A an the presentation', 'A, an, the slides',
    'Make and do slides', 'To do list slides', 'How to make a presentation', 'How to write an essay',
    'How to create a PowerPoint', 'How to give a good presentation',
    # Acronyms, and Russian words that read as English in Latin letters.
    'IT 10 ta slayd', 'IT slayd', 'IT presentation', 'Море презентация', 'Мост презентация',
    'Черное море презентация', 'Чёрное море презентация',
    # "my" and "our" do not make the audience an instruction.
    'My school 10 slides', 'My school presentation', 'Our school presentation', 'My class presentation',
    'My university presentation', 'My teacher presentation',
    # Speech styles are an Ona tili topic; "ilmiy uslubda" is the request.
    'Ilmiy uslub slayd', 'Ilmiy uslub 10 ta slayd', 'Ilmiy uslub referat',
    # The bot joins the topic it asked for on a line of its own.
    'Havo\nslayd kerak', 'Oltin\nslayd kerak', 'IT\nslayd kerak', 'My school\nslayd kerak', 'Сердце\nslayd kerak',
    'Past simple\nslayd kerak', 'Faylasuflar\nslayd kerak',
]

# Nothing is asked for, so these are left to the model as before: a look or a
# part alone ("Modern design", "План урока") could be the subject itself.
TOO_LITTLE_TO_REFUSE = ['Chiroyli', 'Modern design', 'План урока', 'Savollar', 'Yorqin ranglarda', '']


@pytest.mark.parametrize('prompt', NO_TOPIC)
def test_a_description_of_instructions_alone_names_no_topic(prompt):
    assert names_no_topic(prompt), explain(prompt)


@pytest.mark.parametrize('prompt', NAMES_A_TOPIC)
def test_a_description_with_a_subject_in_it_is_never_refused(prompt):
    assert not names_no_topic(prompt), explain(prompt)


@pytest.mark.parametrize('prompt', TOO_LITTLE_TO_REFUSE)
def test_a_look_or_a_part_alone_is_not_refused(prompt):
    assert not names_no_topic(prompt), explain(prompt)


def test_the_lists_are_big_enough_to_mean_something():
    assert len(NO_TOPIC) >= 70 and len(NAMES_A_TOPIC) >= 85
    assert not set(NO_TOPIC) & set(NAMES_A_TOPIC)


@pytest.mark.parametrize('text', [
    '"' + 'slayd ' * 5000,
    '« ' + 'mavzu ' * 5000,
    'oid ' * 5000 + 'slayd',
    'haqida ' * 5000,
    'qizil ' * 5000 + 'rangda slayd',
    'slayd ' * 299,
    'x' * 50000,
], ids=['open-quote', 'open-guillemet', 'slot-words', 'slot-words-alone', 'colour-run', 'just-under-the-cap',
        'one-long-word'])
def test_reading_a_long_description_takes_linear_time(text):
    # A prompt may be 50,000 characters; a pattern that backtracks over it, or
    # a word compared with every other, once held a worker for minutes.
    start = time.perf_counter()
    names_no_topic(text)
    assert time.perf_counter() - start < 0.5


# --- Which tool the description asks for ---------------------------------------

@pytest.mark.parametrize('prompt,feature,expected', [
    # A format that is the topic asks for nothing: a referat about PowerPoint is a PDF.
    ('PowerPoint haqida referat', DOCUMENT, ''),
    ('Презентация о PowerPoint', DOCUMENT, SLIDES),
    ('Word haqida slayd', SLIDES, ''),
    ('Mavzu: PDF', SLIDES, ''),
    ('Vulqonlar haqida 10 ta slayd', DOCUMENT, SLIDES),
    ('Yorqin slayd yasab bering', DOCUMENT, SLIDES),
    ('сделай презентацию', DOCUMENT, SLIDES),
    ('Mavzuga oid PDF', DOCUMENT, ''),
    ('pdf ga otkazib ber', DOCUMENT, ''),
    ('pdf qilib bering', SLIDES, DOCUMENT),
    ('PDF документ', SLIDES, DOCUMENT),
    ('12 ta slayd kerak', SLIDES, ''),
    ('10 ta slayd PDF qilib bering', SLIDES, ''),
    ('11 betlik bo‘lsin', DOCUMENT, ''),
    ('11 betlik bo‘lsin', SLIDES, ''),
])
def test_the_other_tool_is_named_only_when_the_description_asks_for_its_format(prompt, feature, expected):
    assert asked_other_service(prompt, feature) == expected


# --- Refused when a draft is made ------------------------------------------------

@pytest.fixture
def customer(settings):
    settings.DEBUG = True  # local authoring stands in for the AI provider
    return account()


def refusal(customer, data):
    with pytest.raises(DomainError) as refused:
        create_draft(customer, data)
    return refused.value


def test_a_new_document_without_a_topic_is_refused_and_nothing_is_counted(customer):
    before = usage_snapshot(customer)
    error = refusal(customer, {'feature_id': DOCUMENT, 'prompt': '11 betlik bo‘lsin, ko‘k rangda'})
    assert (error.code, error.status, error.params) == ('topic_required', 400, {'service': ''})
    assert not GenerationDraft.objects.filter(account=customer).exists()
    assert not Quote.objects.filter(account=customer).exists()
    assert usage_snapshot(customer) == before and ai_documents_this_week(customer) == 0


@pytest.mark.parametrize('feature,prompt,service', [
    (DOCUMENT, 'Chiroyli slayd tayyorlab bering', SLIDES),
    (DOCUMENT, 'сделайте презентацию на 10 слайдов', SLIDES),
    (SLIDES, 'pdf qilib bering, 5 betlik', DOCUMENT),
    (SLIDES, '12 ta slayd kerak', ''),
])
def test_the_refusal_names_the_tool_for_the_format_asked_for(customer, feature, prompt, service):
    error = refusal(customer, {'feature_id': feature, 'prompt': prompt})
    assert error.code == 'topic_required' and error.params == {'service': service}


def test_a_topic_in_the_title_field_is_a_topic(customer):
    """The web has a separate title; by default it is the description's first line."""
    draft = create_draft(customer, {'feature_id': SLIDES, 'title': 'Quyosh tizimi', 'prompt': '10 ta slayd kerak'})
    assert unpack(draft.encrypted_data)['prompt'] == '10 ta slayd kerak'
    error = refusal(customer, {'feature_id': SLIDES, 'title': '10 ta slayd kerak', 'prompt': '10 ta slayd kerak'})
    assert error.code == 'topic_required'
    # Only a title and no description: the title is the description.
    assert refusal(customer, {'feature_id': DOCUMENT, 'title': 'PDF hujjat'}).code == 'topic_required'
    assert create_draft(customer, {'feature_id': DOCUMENT, 'title': 'Vulqonlar'})


def test_pasted_text_is_what_the_document_is_about(customer):
    draft = create_draft(customer, {'feature_id': DOCUMENT, 'prompt': '5 betlik bo‘lsin',
                                    'source_text': 'Tides rise and fall twice a day because of the Moon.'})
    assert unpack(draft.encrypted_data)['prompt'] == '5 betlik bo‘lsin'


def test_a_source_file_is_what_the_document_is_about(customer, monkeypatch):
    """The web sends the service's name as the description when only a file is given."""
    monkeypatch.setattr('apps.studio.extraction.extract_pages',
                        lambda path: [(1, 'Glaciers move slowly downhill under their own weight.')])
    asset = upload(customer, widths=(200,))
    draft = create_draft(customer, {'feature_id': DOCUMENT, 'prompt': 'PDF Document', 'source_ids': [str(asset.id)]})
    assert unpack(draft.encrypted_data)['source_ids'] == [str(asset.id)]


def test_a_draft_already_made_is_never_refused_when_it_is_changed(customer):
    """update_draft runs for every review button, outline edit and reworded description."""
    draft = create_draft(customer, {'feature_id': SLIDES, 'prompt': 'Vulqonlar haqida 6 ta slayd'})
    draft = update_draft(customer, draft.id, {'version': draft.version, 'prompt': '12 ta slayd bo‘lsin'})
    assert unpack(draft.encrypted_data)['prompt'] == '12 ta slayd bo‘lsin'
    client = login_client(customer)
    response = client.patch(f'/api/v1/generation/drafts/{draft.id}',
                            data=json.dumps({'version': draft.version, 'prompt': 'Chiroyli dizaynda bo‘lsin'}),
                            content_type='application/json')
    assert response.status_code == 200, response.content


def test_a_change_request_names_no_topic_and_is_not_refused(settings):
    """A change is about the document it changes: "make it 4 pages" is the whole request."""
    from tests.test_revisions import generated
    from tests.test_studio import paid
    settings.DEBUG = True
    customer = paid(settings, account())
    original = generated(customer)
    assert names_no_topic('4 betlik bo‘lsin')
    revised = create_draft(customer, {'prompt': '4 betlik bo‘lsin', 'options': {'revise_draft_id': str(original.id)}})
    assert unpack(revised.encrypted_data)['revision']['source_draft_id'] == str(original.id)


@pytest.mark.parametrize('data,code', [
    ({'feature_id': DOCUMENT, 'prompt': ''}, 'prompt_required'),
    ({'feature_id': DOCUMENT, 'prompt': '10 ta slayd', 'output_locale': 'xx'}, 'invalid_locale'),
    ({'feature_id': DOCUMENT, 'prompt': '10 ta slayd', 'output_format': 'docx'}, 'invalid_parameters'),
    ({'feature_id': DOCUMENT, 'prompt': '10 ta slayd', 'options': []}, 'invalid_parameters'),
    ({'feature_id': 'ai.retired', 'prompt': '10 ta slayd'}, 'feature_unavailable'),
])
def test_a_malformed_request_keeps_its_own_error(customer, data, code):
    assert refusal(customer, data).code == code


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_the_api_says_what_is_missing_in_the_customers_language(customer, locale):
    Account.objects.filter(pk=customer.pk).update(locale=locale)
    client = login_client(customer)
    response = client.post('/api/v1/generation/drafts',
                           data=json.dumps({'feature_id': DOCUMENT, 'prompt': 'Yorqin slayd yasab bering'}),
                           content_type='application/json')
    assert response.status_code == 400, response.content
    error = response.json()['error']
    assert error['code'] == 'topic_required' and error['message_params'] == {'service': SLIDES}
    assert error['message'] == error_data(DomainError('topic_required'), locale)['message']
    assert error['message'] != error_data(DomainError('invalid_request'), locale)['message']
    assert not GenerationDraft.objects.filter(account=customer).exists()


@pytest.mark.parametrize('locale,example', [
    ('en', 'The water cycle, for 6th grade'),
    ('uz', 'Tabiatda suvning aylanishi, 6-sinf uchun'),
    ('ru', 'Круговорот воды в природе, для 6 класса'),
])
def test_the_message_gives_an_example_that_would_itself_be_accepted(locale, example):
    message = error_data(DomainError('topic_required'), locale)['message']
    assert example in message and not names_no_topic(example)
    if locale == 'uz':
        assert not any(letter in message for letter in "'ʻʼ`"), 'o‘ and g‘ are written with ‘'


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_the_message_fits_slides_as_well_as_a_document(customer, locale):
    """One message for both services: a deck has no pages and is not a document."""
    Account.objects.filter(pk=customer.pk).update(locale=locale)
    client = login_client(customer)
    messages = {}
    for feature in (SLIDES, DOCUMENT):
        response = client.post('/api/v1/generation/drafts',
                               data=json.dumps({'feature_id': feature, 'prompt': '12 ta slayd kerak'}),
                               content_type='application/json')
        assert response.status_code == 400 and response.json()['error']['code'] == 'topic_required'
        messages[feature] = response.json()['error']['message'].lower()
    for word in ('document', 'page', 'hujjat', 'bet', 'документ', 'страниц'):
        assert word not in messages[SLIDES], (word, messages[SLIDES])


# --- A file conversion asked of an AI service -----------------------------------

@pytest.mark.parametrize('prompt', ['pdf ga otqaz', 'pdfga otqazib ber', 'word ga otkazib ber', 'convert to pdf',
                                    'переведи в pdf', 'Word faylni pdf ga o‘tkazib bering', 'turn into pdf please'])
def test_a_conversion_is_sent_to_the_file_tools(customer, prompt):
    assert asks_to_convert(prompt), explain(prompt)
    for feature in (DOCUMENT, SLIDES):
        error = refusal(customer, {'feature_id': feature, 'prompt': prompt})
        assert (error.code, error.params) == ('convert_requested', {'service': '', 'convert': True})
    assert not GenerationDraft.objects.filter(account=customer).exists()


@pytest.mark.parametrize('prompt', ['pdf qilib ber', 'Mavzuga oid PDF', '10 ta slayd kerak', 'make a pdf',
                                    'Chiroyli slayd qilib pdf ga otkazib ber', 'slaydga aylantir',
                                    'Word haqida referat', 'Vulqonlar haqida pdf ga otkazib ber'])
def test_a_new_document_asked_for_is_not_a_conversion(prompt):
    assert not asks_to_convert(prompt), explain(prompt)


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_the_api_points_a_conversion_to_the_file_tools(customer, locale):
    """The web shows the server's message as it is, so the message says where to go."""
    Account.objects.filter(pk=customer.pk).update(locale=locale)
    response = login_client(customer).post('/api/v1/generation/drafts',
                                           data=json.dumps({'feature_id': DOCUMENT, 'prompt': 'convert to pdf'}),
                                           content_type='application/json')
    assert response.status_code == 400
    error = response.json()['error']
    assert error['code'] == 'convert_requested' and error['message_params'] == {'service': '', 'convert': True}
    assert error['message'] == error_data(DomainError('convert_requested'), locale)['message']
    assert error['message'] not in (error_data(DomainError(code), locale)['message']
                                    for code in ('topic_required', 'invalid_request'))
    assert {'en': 'All tools', 'uz': 'Barcha vositalar', 'ru': 'Все инструменты'}[locale] in error['message']


def test_content_or_an_outline_on_a_new_draft_does_not_excuse_it(customer):
    """A new draft is made from its description: content or an outline sent with it is not kept."""
    for data in ({'feature_id': SLIDES, 'prompt': '12 ta slayd kerak', 'content': {'sections': []}},
                 {'feature_id': DOCUMENT, 'prompt': '10 betlik bo‘lsin', 'outline': 'x'}):
        assert refusal(customer, data).code == 'topic_required'
    response = login_client(customer).post('/api/v1/generation/drafts', content_type='application/json',
                                           data=json.dumps({'feature_id': SLIDES, 'prompt': '12 ta slayd kerak',
                                                            'content': {}}))
    assert response.status_code == 400 and response.json()['error']['code'] == 'topic_required'


def test_a_description_the_customer_insists_on_is_made_as_it_is(customer):
    """The bot's second answer and the web's "Continue anyway" send options.topic_given."""
    draft = create_draft(customer, {'feature_id': SLIDES, 'prompt': '12 ta slayd kerak',
                                    'options': {'topic_given': True, 'pages': 12}})
    options = unpack(draft.encrypted_data)['options']
    assert 'topic_given' not in options and options.get('pages') == 12, 'a request, not a setting'
    response = login_client(customer).post('/api/v1/generation/drafts', content_type='application/json',
                                           data=json.dumps({'feature_id': DOCUMENT, 'prompt': 'convert to pdf',
                                                            'options': {'topic_given': True}}))
    assert response.status_code == 201, response.content
    # Anything but True keeps the check.
    for value in ('true', 1, None):
        assert refusal(customer, {'feature_id': SLIDES, 'prompt': '12 ta slayd kerak',
                                  'options': {'topic_given': value}}).code == 'topic_required'


# --- An answer to the topic question that is a whole description -----------------

@pytest.mark.parametrize('answer,kept,whole', [
    ('A 3 page PDF report about volcanoes for year 8', ['10 slides please'], True),  # the other format
    ('Volcanoes, 12 slides', ['10 slides please'], True),                            # its own count
    ('Please make a presentation about volcanoes for my year 8 class with pictures', ['in blue'], True),
    ('Volcanoes', ['10 slides please'], False),
    ('Volcanoes for year 8', ['10 slides please', 'in blue'], False),
    ('Volcanoes, 5 pages', ['in blue'], False),        # nothing it replaces: the colour still holds
    ('Vulqonlar haqida slayd', ['10 ta slayd kerak'], False),
    ('PowerPoint haqida', ['10 ta referat kerak'], False),
    ('in blue', ['10 slides please'], False),          # still no topic
])
def test_an_answer_that_is_a_whole_description_replaces_what_was_kept(answer, kept, whole):
    assert restates(answer, kept) is whole
