"""What customers actually wrote, and what the description must be read as.

Every prompt here comes from a real request (shortened) that was read wrong:
a pasted essay whose "1-bet" heading made a one-slide deck, "10 varoqlik"
missed because only the spelling "varaq" was known, "har bir slaydda rasm"
(a picture on every slide) read as a one-slide deck.
"""
import pytest

from apps.studio.pages import requested_pages


@pytest.mark.parametrize('description,expected', [
    # Uzbek numbers pages and slides with a hyphen: those are not counts.
    ('KUCHLI DAVLAT MAS’ULIYATLI FUQARODAN BOSHLANADI 1-bet Har bir inson uchun Vatan', None),
    ('O’rta maxsus 2 ta slayd kerak. 1-slayd mavzusi Mahalla. 2-mavzu Jamiyat', 2),
    # A pasted slide plan: the last slide it numbers is the count.
    ('Prezentatsiya rejasi 1-slayd. Mavzu 2-slayd. Bezovtalik 3-slayd. Sabablari 9-slayd. Xulosa', 9),
    # Something on every slide is not a count.
    ('Keyin har 1ta slaydga rasm qo‘shilsin. Matnga mos.', None),
    ("Fotosintez haqida slayd, har bir slaydda rasm bo'lsin", None),
    ('Slaydning har bir listida hikoya g‘oyasi yoritilsin', None),
    # Spellings and word orders people use.
    ('Best frend forever mavzusida 10 varoqlik slayd yasa maktab uchun', 10),
    ('Nutqning mantiqiyligi 14tashlab slayd Har slayd bitta fikr', 14),
    ('10 ta chiroyli slayd kerak', 10),
    ('Krebs sikli rasmlar. Sahifalar soni 20 ta.', 20),
    ("Har slaydda 2 ta fikr 5 ta savol bo'lsin. Yorqin rangda bo'lsin 15 ta bo'lsin", 15),
    ('12 ta slayddan iborat bo‘lsin', 12),
    ('hammasi 10ta slaydga sigsin ingliz tilida', 10),
    ("Ibn Xaldunning asari asosida 15 betlik slayd", 15),
    ("Qadimgi Yunoniston haqida 4-5 betli slayd kerak, 5 ta rasm", 5),
    ('Ochiq darsga 15 ta slayd kerak 10 sinf geografiya. Oxirida 10 ta savol. Kók rangda', 15),
    ('1. Мустакил иш 10 ta slayd kerak НЕФТ ВА ГАЗ ҚУДУҚЛАРИНИ', 10),
    # A number that counts something else is not a page count.
    ('9 sinf uchun xorazmshoxlar davlati', None),
    ('9 sinf slayd tarix', None),
    ('Hayot haqida 5 list kitob', None),
    ('bir sahifali eslatma', 1),
])
def test_real_descriptions_are_read_for_the_count_they_ask_for(description, expected):
    assert requested_pages(description) == expected


@pytest.mark.django_db
def test_a_change_request_does_not_shrink_a_deck_to_one_slide(settings, monkeypatch):
    from apps.studio.domain import SLIDES, create_draft, unpack
    from tests.test_platform import account
    from tests.test_studio import paid
    from operations.integrations import save_config
    from tests.test_provider_contract import CONFIG
    from apps.studio.models import GenerationDraft
    settings.DEBUG = True
    customer = paid(settings, account())
    save_config('ai', {'mode': 'openai', 'model': CONFIG['model'], 'api_key': 'offline-only'})
    deck = create_draft(customer, {'feature_id': SLIDES, 'prompt': 'Pedagogika fanining rivojlanishi, 9ta slayd'})
    # A generated deck can be changed; pretend this one was.
    data = unpack(deck.encrypted_data)
    data['content']['sections'] = [{**s, 'body': 'Matn.'} for s in data['content']['sections']]
    from apps.studio.domain import pack
    GenerationDraft.objects.filter(pk=deck.pk).update(encrypted_data=pack(data))
    from apps.studio import domain
    monkeypatch.setattr(domain, 'revision_source', lambda account, identifier: (deck, data))
    change = create_draft(customer, {'prompt': 'Keyin har 1ta slaydga rasm qo‘shilsin.',
                                     'options': {'revise_draft_id': str(deck.id)}})
    assert len(unpack(change.encrypted_data)['content']['sections']) == 9
    longer = create_draft(customer, {'prompt': '12 ta slayd qil', 'options': {'revise_draft_id': str(deck.id)}})
    assert len(unpack(longer.encrypted_data)['content']['sections']) == 12


@pytest.mark.parametrize('description,expected', [
    # Asked for in so many words: what the request ends on, or what to do.
    ('Ingiliz tilida tayyorla', 'en'),
    ('Slayd English languageda boʻlsin', 'en'),
    ('frenkenshteyn asari boyicha tahlil, hammasi 10ta slaydga sigsin ingliz tilida', 'en'),
    ('A 5 page guide in English about tides', 'en'),
    ('Документ на английском о приливах', 'en'),
    ("Hujjat ruscha bo'lsin", 'ru'),
    # Written in Russian, it is answered in Russian.
    ('История гласных среднего подъёма: вопрос о переходе [е] в [о] и аналогическом. 10ta slayd', 'ru'),
    # A language that is the subject is not the language to write in.
    ('Xitoy tilida omonimlar', None),
    ("Rus tilida fe'l zamonlari haqida slayd", None),
    ('Ingliz tili fani uchun 6 ta slayd kerak', None),
    ("ruscha so'zlar haqida", None),
    # Uzbek in Cyrillic is Uzbek.
    ('Ҳозирги замонавий жанговар ҳаракатларда артиллериянинг қўлланилиши', None),
    ('Мен жудаям кечиримли инсонман, базан сени хамма хатоларинг учун кечираман', None),
])
def test_the_language_to_write_in_is_read_from_the_description(description, expected):
    from apps.studio.pages import requested_locale
    assert requested_locale(description) == expected


def test_a_change_request_names_its_language_in_so_many_words():
    from apps.studio.pages import requested_locale
    assert requested_locale('Сделай короче', explicit_only=True) is None
    assert requested_locale('Ingliz tilida tayyorla', explicit_only=True) == 'en'


@pytest.mark.parametrize('description,expected', [
    ('НЕФТ ВА ГАЗ ҚУДУҚЛАРИНИ БУРҒИЛАШ 10 ta slayd kerak', 'cyrl'),
    ('Ҳозирги замонавий жанговар ҳаракатларда', 'cyrl'),
    ('Orol dengizi muammosi', 'latn'),
    ('История гласных и фонем в языке', 'latn'),
])
def test_uzbek_is_written_in_the_alphabet_of_the_description(description, expected):
    from apps.studio.pages import requested_script
    assert requested_script(description) == expected


def test_a_latin_document_has_no_cyrillic_words_left_in_it():
    from apps.studio.uzbek import clean, clean_text, to_latin
    assert to_latin('Ўзбекистон') == 'O‘zbekiston' and to_latin('қўшиқ') == 'qo‘shiq' and to_latin('ер') == 'yer'
    text = "O'zbekistonda muҳим аҳамиятга эга. mаktab"
    assert clean_text(text) == 'O‘zbekistonda muhim ahamiyatga ega. maktab'
    # A word mixing the alphabets in a Cyrillic document goes to Cyrillic.
    assert clean_text('замонaвий', 'cyrl') == 'замонавий'
    content = {'title': 'Pedagogika', 'sections': [{'id': 's1', 'heading': 'Тарих', 'body': 'Bu муҳим.', 'notes': ''}],
               'questions': [{'stem': 'Nima?', 'options': ['Ҳа', "Yo'q"], 'answer': 'Ҳа', 'explanation': ''}]}
    cleaned = clean(content, 'latn', 'Pedagogika fanining rivojlanishi')
    assert cleaned['sections'][0]['heading'] == 'Tarix' and cleaned['sections'][0]['body'] == 'Bu muhim.'
    assert cleaned['questions'][0]['options'] == ['Ha', 'Yo‘q']
    # About Russian, or quoting Cyrillic, a Cyrillic word is content and stays.
    kept = clean(content, 'latn', 'Rus tilida fe’llar')
    assert kept['sections'][0]['heading'] == 'Тарих'


BLUE, NAVY, SKY, GREEN, RED, BROWN = '#1F4E9C', '#16305C', '#2B7BB9', '#1E6B45', '#9B1B1B', '#6B4423'


@pytest.mark.parametrize('description,colours,theme', [
    ('Ko‘k rangda chiroyli chiqsin', [BLUE], None),
    ('Kók rangda', [BLUE], None),
    ("orqasi och savorang bo'lsin", [SKY], None),
    ('Mavzu sezgi azolari och havorang 12 bet yorqin', [SKY], 'bold'),
    ('Toʻq koʻk rangda chiroyli chiqsin', [NAVY], None),
    ('Koʻk yashil qizil ranglar qatnashgan', [BLUE, GREEN, RED], None),
    ('jigarrang fonda', [BROWN], None),
    ('och rangda bo‘lsin', [], 'light'),
    ("ko'zni charchatmaydigan rangdan foydalan", [], 'light'),
])
def test_colours_are_read_in_the_order_they_are_named(description, colours, theme):
    from apps.studio.pages import requested_colours, requested_theme
    assert requested_colours(description) == colours
    assert requested_theme(description) == theme


@pytest.mark.parametrize('description,expected', [
    ('5 ta slayd, 4 ta rasm qo‘shilsin', 4), ('unga oid 5 ta rasm', 5), ('rasmiy uslubda', None),
])
def test_a_number_of_pictures_is_read(description, expected):
    from apps.studio.pages import requested_images
    assert requested_images(description) == expected


def test_official_style_is_not_a_request_for_pictures():
    from apps.studio.doc_designs import asks_for_images
    assert not asks_for_images('Rasmiy uslubda yozilsin')
    assert asks_for_images("chiroyli rasmlari ham bo'lsin")


@pytest.mark.django_db
def test_named_colours_and_pictures_reach_the_draft(settings):
    from apps.studio.domain import DOCUMENT, SLIDES, create_draft, unpack
    from tests.test_platform import account
    from tests.test_studio import paid
    settings.DEBUG = True
    customer = paid(settings, account())
    deck = unpack(create_draft(customer, {'feature_id': SLIDES, 'prompt': '8 ta slayd, koʻk va yashil ranglarda, har bir slaydda rasm'}).encrypted_data)
    style = deck['options']['template_style']
    assert (style['accent'], style['secondary'], style['accent_fixed']) == (BLUE, GREEN, True)
    assert deck['options']['images_wanted'] == 8
    counted = unpack(create_draft(customer, {'feature_id': SLIDES, 'prompt': '8 ta slayd, 3 ta rasm'}).encrypted_data)
    assert counted['options']['images_wanted'] == 3
    plain = unpack(create_draft(customer, {'feature_id': SLIDES, 'prompt': '8 ta slayd'}).encrypted_data)
    assert 'images_wanted' not in plain['options']
    document = unpack(create_draft(customer, {'feature_id': DOCUMENT, 'prompt': 'Sezgi azolari, och havorang, 3 bet'}).encrypted_data)
    assert document['options']['template_style']['accent'] == SKY and document['options']['wants_design']
