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
