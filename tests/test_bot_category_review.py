"""The review of a category draft, its one extra question and the notices under its file (architecture 4, 7, 8.1).

A draft made in a category says so on its review, under the service's name.
When its entry has a question and it is wanted for what was written (a
defence deck with no figures and no file, a topic deck naming no one for its
title slide), the review says what will be blank or a draft without it, and
offers one button under Generate. The button opens the question in the
category's words; the answer, text, files or both, is added to the draft
once, under the title-slide header for a deck whose question is for its cover,
and the review is drawn again without the question. Skipping it is tapping
Generate. A count is offered within the category's own bounds, and a category
draft is never offered the other service: its description names the other
format as its subject, and that draft would lose the category.

Under the finished file the category says what to do with it: its `finished`
notice, its `blanks` notice when code blanked or took out a fact the customer
did not give (the job warning facts_blanked), and its `draft` notice when a
new deck has slides written from its topic alone.

A draft without a category, Boshqa's, keeps today's review and caption: the
existing review and delivery tests pin those and are not edited.

The people, organisations and descriptions are invented for these tests.
"""
import asyncio
import html
import re
import secrets
from unittest.mock import AsyncMock, Mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.commerce.models import BotDelivery, LocalBotMessage
from apps.core.errors import DomainError
from apps.core.models import BotCallback, BotInputReceipt, FileAsset, Job
from apps.core.services import execute_job
from apps.studio import categories, title_lines
from apps.studio.domain import DOCUMENT, SLIDES, pack, unpack
from apps.studio.models import GenerationDraft
from apps.studio.pages import ceiling
from apps.studio.scripts import CYRILLIC
from telegram import generation as ai
from telegram.bot import COPY
from telegram.delivery import CAPTION_LIMIT, RESULT_COPY, attempt, category_notices, ready_caption, share_link, with_notices
from telegram.errors import source_error
from telegram.ux_copy import LOCALES, MESSAGES, TOOL_NAMES, UX, counted
from tests.test_bot_categories import (DEFENCE, HIMOYA, TEST, customer, latest, model, opened, pending,  # noqa: F401
                                       ready, screen, speak, switch, tapped, turn)
from tests.test_bot_cv import feed_together
from tests.test_bot_no_flood import Chat
from tests.test_category_sources import docx, pdf
from tests.test_upload_ai_source import office_pages  # noqa: F401

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled', 'office_pages')]

MAVZU = 'slides.mavzu'          # its question is for the title slide (ask.cover)
PITCH = 'slides.pitch'          # no question at all
BAYRAM = 'slides.tadbir.bayram'  # says what to check under every file (notices.finished)
DECKS = [HIMOYA, MAVZU, PITCH, BAYRAM]

TOPIC_DECK = 'Ekologiya fanidan 8 ta slayd: suv resurslarini tejash.'
FIGURES = 'Kurs ishi himoyasi uchun 10 ta slayd: “Kichik biznesda raqamli marketing”. Savdo 35% ga oshdi.'
RESULTS = 'Natijalar: savdo 35% ga oshdi, mijozlar soni 1 200 nafardan 1 650 nafarga yetdi.'
THESIS = 'Kirish. Ushbu kurs ishi “Yashil vodiy” MChJ misolida raqamli marketingni o‘rganadi. Xulosa: savdo oshdi.'
COVER_LINES = {
    'uz': 'Namuna davlat universiteti\nKarimova Dilnoza, 205-guruh',
    'ru': 'Университет «Намуна»\nКаримова Дилноза, группа 205',
    'en': 'Namuna State University\nDilnoza Karimova, group 205',
}


@pytest.fixture
def decks(switch):
    """The switch on with the deck categories these tests open ticked, beside the three of the bot's own tests."""
    turn(live=[*DECKS, TEST])
    return turn


def described(account, text, category=HIMOYA, service=SLIDES):
    """The review of `text`, written in `category`'s question."""
    chat = opened(account, service)
    assert chat.tap('ai_tool', feature_id=service, category=category) == 0
    assert chat.do(text=text) == 1, '"Preparing…" becomes the review'
    return chat


def rows_of(account):
    _, actions, payloads, labels = screen(account)
    return actions, payloads, labels


def draft_of(account, feature_id=SLIDES):
    return GenerationDraft.objects.filter(account=account, feature_id=feature_id).latest('created_at')


def upload(name, raw):
    return SimpleUploadedFile(name, raw)


# --- The review ----------------------------------------------------------------------------------


@pytest.mark.parametrize('locale', LOCALES)
def test_the_review_names_the_category_and_offers_its_question_under_generate(customer, decks, locale):
    speak(customer, locale)
    described(customer, DEFENCE)
    entry = categories.get(HIMOYA)
    text, actions, payloads, labels = screen(customer)
    assert text.startswith(f'<b>{UX[locale]["review_title"]}</b>\n{TOOL_NAMES[SLIDES][locale]}\n'
                           f'{html.escape(entry.label(locale))}\n📄 ')
    review = html.escape(entry.ask['review'][locale])
    assert f'\n\n{review}\n\n{UX[locale]["ai_review_hint"]}' in text
    draft = draft_of(customer)
    assert actions[0] == ['ai_run'] and actions[1] == ['ai_details']
    assert labels[1] == [UX[locale]['ai_details_button']] and payloads[1] == [{'draft_id': str(draft.id)}]
    # The reword button describes again in the category, beside the menu.
    assert actions[-1] == ['ai_tool', 'home'] and payloads[-1][0] == {'feature_id': SLIDES, 'category': HIMOYA}


def test_no_question_when_it_is_not_wanted_or_the_category_has_none(customer, decks):
    # Figures in the message: the result slides have something to show.
    described(customer, FIGURES)
    text, *_ = screen(customer)
    actions, _, _ = rows_of(customer)
    assert categories.get(HIMOYA).ask['review']['en'] not in text and ['ai_details'] not in actions
    assert categories.get(HIMOYA).label('en') in text

    # A pitch has no question at all.
    described(customer, 'Startap pitch: “Toza havo” ilovasi, 8 ta slayd.', PITCH)
    actions, _, _ = rows_of(customer)
    assert ['ai_details'] not in actions


def test_a_file_sent_with_the_description_answers_what_the_question_would_ask(customer, decks):
    chat = opened(customer, SLIDES)
    chat.tap('ai_tool', feature_id=SLIDES, category=HIMOYA)
    assert chat.do(uploaded=upload('thesis.docx', docx(THESIS)), caption=DEFENCE) == 1
    actions, _, _ = rows_of(customer)
    assert ['ai_details'] not in actions, 'a defence with its thesis attached has its results to show'


def test_a_category_is_never_offered_the_other_service(customer, decks, model):
    asks_slides = 'Fotosintez haqida 10 ta slayd tayyorlab bering'
    # Boshqa, today's question: the description asks for slides, and the review offers them.
    chat = opened(customer)
    chat.tap('ai_tool', feature_id=DOCUMENT, category='other')
    chat.do(text=asks_slides)
    actions, _, _ = rows_of(customer)
    assert actions[0] == ['ai_switch'] and UX['en']['ai_wrong_tool_slides'] in screen(customer)[0]
    # In a category: no banner, no switch row, Generate named as always.
    described(customer, asks_slides, TEST, DOCUMENT)
    text, actions, _, labels = screen(customer)
    assert UX['en']['ai_wrong_tool_slides'] not in text
    assert actions[0] == ['ai_run'] and labels[0] == [UX['en']['ai_generate']]
    assert all('ai_switch' not in row for row in actions)


def stepper(account):
    actions, payloads, labels = rows_of(account)
    row = next(index for index, row in enumerate(actions) if 'ai_count' in row)
    return actions[row], payloads[row], labels[row]


def test_the_count_is_offered_within_the_categorys_bounds(customer, decks):
    entry = categories.get(HIMOYA)
    lowest, most = entry.length['min'], entry.length['max']
    assert ceiling(customer, 'pptx') > most, 'the plan allows more than the category: the category is the bound'

    described(customer, f'Kurs ishi himoyasi uchun {most} ta slayd: “Kichik biznesda raqamli marketing”.')
    actions, payloads, labels = stepper(customer)
    assert actions == ['ai_length', 'ai_count'] and payloads[0]['pages'] == most - 1
    assert labels[1] == counted('en', most, 'slide')

    described(customer, f'Kurs ishi himoyasi uchun {lowest} ta slayd: “Kichik biznesda raqamli marketing”.')
    actions, payloads, _ = stepper(customer)
    assert actions == ['ai_count', 'ai_length'] and payloads[1]['pages'] == lowest + 1

    # Boshqa at the same count steps below it, as today.
    chat = opened(customer, SLIDES)
    chat.tap('ai_tool', feature_id=SLIDES, category='other')
    chat.do(text=f'{lowest} ta slayd: kichik biznesda raqamli marketing')
    actions, _, _ = stepper(customer)
    assert actions == ['ai_length', 'ai_count', 'ai_length']


def test_what_the_files_gave_is_said_on_the_review(customer, decks):
    described(customer, FIGURES)
    draft = draft_of(customer)
    data = unpack(draft.encrypted_data)
    # Written by the server only (domain: unread_sources, sources_cut); set here as it would set them.
    data['options'] = {**data['options'], 'unread_sources': [secrets.token_hex(4), secrets.token_hex(4)],
                       'sources_cut': True}
    GenerationDraft.objects.filter(pk=draft.pk).update(encrypted_data=pack(data))
    draft.refresh_from_db()
    from telegram.bot import review_screen
    _, quote = ai.quote(customer, draft.id)
    body, _ = asyncio.run(review_screen(customer, draft, quote))
    assert html.escape(UX['en']['ai_sources_unread'].format(files=counted('en', 2, 'file'))) in body
    assert UX['en']['ai_sources_cut'] in body


def test_a_scanned_file_beside_a_readable_one_is_said_as_left_out(customer, decks):
    chat = opened(customer, SLIDES)
    chat.tap('ai_tool', feature_id=SLIDES, category=HIMOYA)
    assert chat.do(uploaded=upload('scan.pdf', pdf(''))) == 1
    assert chat.do(uploaded=upload('thesis.docx', docx(THESIS)), caption=DEFENCE) == 1
    data = latest(customer, SLIDES)
    assert len(data['source_ids']) == 2 and data['options']['unread_sources'] == [str(FileAsset.objects.get(name='scan.pdf').id)]
    assert UX['en']['ai_sources_unread'].format(files=counted('en', 1, 'file')) in html.unescape(screen(customer)[0])


# --- The question ---------------------------------------------------------------------------------


@pytest.mark.parametrize('locale', LOCALES)
def test_the_question_is_the_categorys_and_back_is_the_review(customer, decks, locale):
    speak(customer, locale)
    described(customer, TOPIC_DECK, MAVZU)
    draft = draft_of(customer)
    entry = categories.get(MAVZU)
    assert tapped(customer, {'draft_id': str(draft.id)}, 'ai_details') == 0, 'the review becomes the question'
    text, actions, payloads, labels = screen(customer)
    assert text == (f'<b>{TOOL_NAMES[SLIDES][locale]} · {html.escape(entry.label(locale))}</b>\n'
                    f'{html.escape(entry.ask["prompt"][locale])}\n\n'
                    f'<blockquote>{html.escape(entry.ask["hint"][locale])}</blockquote>\n\n{UX[locale]["ai_details_how"]}')
    assert actions == [['ai_details', 'home']] and labels == [[UX[locale]['ai_back'], UX[locale]['home']]]
    assert payloads[0][0] == {'draft_id': str(draft.id), 'back': True}
    assert pending(customer) == ('ai_details', {'draft_id': str(draft.id), 'feature_id': SLIDES, 'category': MAVZU})

    # Back: the review again, still offering the question, and nothing is kept.
    tapped(customer, {'draft_id': str(draft.id), 'back': True}, 'ai_details')
    assert pending(customer) == ('', {})
    actions, _, _ = rows_of(customer)
    assert actions[1] == ['ai_details']


def test_an_answer_is_added_once_and_the_question_is_gone(customer, decks):
    chat = described(customer, DEFENCE)
    draft = draft_of(customer)
    tapped(customer, {'draft_id': str(draft.id)}, 'ai_details')
    assert chat.do(text=RESULTS) == 1, '"Preparing…" becomes the review'
    text, actions, _, _ = screen(customer)
    assert text.startswith(UX['en']['ai_details_added'] + '\n\n')
    assert ['ai_details'] not in actions and categories.get(HIMOYA).ask['review']['en'] not in text
    data = unpack(GenerationDraft.objects.get(pk=draft.pk).encrypted_data)
    assert data['options']['details_added'] is True and data['options']['category'] == HIMOYA
    assert (data['prompt'] or data['source_text']).endswith(f'{DEFENCE}\n\n{RESULTS}')
    assert GenerationDraft.objects.filter(account=customer).count() == 1, 'the same draft, priced again'
    assert pending(customer) == ('', {})

    # The button on a copy of the review still in the chat, tapped again: an old button, nothing added.
    before = GenerationDraft.objects.get(pk=draft.pk).version
    token = BotCallback.objects.get(account=customer, action='ai_details', payload={'draft_id': str(draft.id)}).pk
    LocalBotMessage.objects.create(account=customer, direction='outbound', text='An older review',
                                   buttons=[[{'label': 'Old', 'callback_data': token, 'url': None}]],
                                   telegram_message_id=secrets.randbelow(1_000_000) + 1)
    Chat(customer).do(callback_data=token)
    assert COPY['en']['stale_button'] in screen(customer)[0] and pending(customer) == ('', {})
    assert GenerationDraft.objects.get(pk=draft.pk).version == before
    with pytest.raises(DomainError) as refused:
        ai.add_details(customer, draft.id, 'Yana bir natija: 12 ta yangi mijoz.')
    assert refused.value.code == 'controls_expired'


def test_the_question_closes_once_the_draft_is_generated(customer, decks, settings):
    described(customer, DEFENCE)
    draft = draft_of(customer)
    _, quote = ai.quote(customer, draft.id)
    settings.LOCAL_SYNC_JOBS = False
    ai.start(customer, quote.id)
    assert ai.details_open(customer, draft.id) == (None, None)
    tapped(customer, {'draft_id': str(draft.id)}, 'ai_details')
    assert COPY['en']['stale_button'] in screen(customer)[0]


def test_an_answer_with_a_file_joins_its_sources(customer, decks):
    chat = described(customer, DEFENCE)
    draft = draft_of(customer)
    tapped(customer, {'draft_id': str(draft.id)}, 'ai_details')
    assert chat.do(uploaded=upload('thesis.docx', docx(THESIS)), caption=RESULTS) == 1
    thesis = FileAsset.objects.get(account=customer, name='thesis.docx')
    data = unpack(GenerationDraft.objects.get(pk=draft.pk).encrypted_data)
    assert data['source_ids'] == [str(thesis.id)] and data['options']['details_added'] is True
    assert any('raqamli marketingni' in item['text'] for item in data['excerpts'])
    assert (data['prompt'] or data['source_text']).endswith(RESULTS)
    # The customer's own source: received once, never staged for the file tools.
    assert thesis.metadata['kind'] == 'docx' and BotInputReceipt.objects.filter(account=customer, asset=thesis).count() == 1
    assert UX['en']['ai_details_added'] in screen(customer)[0]


def test_files_alone_are_an_answer_and_an_album_is_one(customer, decks, monkeypatch):
    monkeypatch.setattr('telegram.bot.ALBUM_SETTLE', 0.3)
    described(customer, DEFENCE)
    draft = draft_of(customer)
    tapped(customer, {'draft_id': str(draft.id)}, 'ai_details')
    group = secrets.token_hex(6)
    feed_together(customer, [(upload('thesis.docx', docx(THESIS)), '', group),
                             (upload('results.txt', RESULTS.encode()), '', group)], 0.02)
    data = unpack(GenerationDraft.objects.get(pk=draft.pk).encrypted_data)
    names = dict(FileAsset.objects.filter(account=customer).values_list('name', 'id'))
    assert data['source_ids'] == [str(names['thesis.docx']), str(names['results.txt'])]
    assert (data['prompt'] or data['source_text']).endswith(DEFENCE), 'no words were added'
    assert data['options']['details_added'] is True


def test_a_file_of_another_kind_asks_again_and_adds_nothing(customer, decks):
    chat = described(customer, DEFENCE)
    draft = draft_of(customer)
    tapped(customer, {'draft_id': str(draft.id)}, 'ai_details')
    before = GenerationDraft.objects.get(pk=draft.pk).version
    chat.do(uploaded=upload('chart.png', b'\x89PNG\r\n\x1a\n'))
    text, *_ = screen(customer)
    assert text.startswith(html.escape(UX['en']['ai_topic_files_only'])) and categories.get(HIMOYA).ask['prompt']['en'] in html.unescape(text)
    assert GenerationDraft.objects.get(pk=draft.pk).version == before and not FileAsset.objects.filter(account=customer).exists()
    assert pending(customer)[0] == 'ai_details'


def test_a_file_with_no_text_asks_again_saying_why(customer, decks):
    chat = described(customer, DEFENCE)
    draft = draft_of(customer)
    tapped(customer, {'draft_id': str(draft.id)}, 'ai_details')
    chat.do(uploaded=upload('scan.pdf', pdf('')))
    said = source_error(DomainError('source_unreadable', 400, {'asset_ids': ['x']}), 'en')
    text, *_ = screen(customer)
    assert said and text.startswith(html.escape(said))
    assert 'details_added' not in unpack(GenerationDraft.objects.get(pk=draft.pk).encrypted_data)['options']
    assert pending(customer)[0] == 'ai_details'


# --- The title slide ------------------------------------------------------------------------------


@pytest.mark.parametrize('locale', LOCALES)
def test_a_cover_answer_goes_under_the_title_slide_header_the_cover_reads(customer, decks, locale):
    draft = ai.build(customer, SLIDES, TOPIC_DECK, category=MAVZU)
    data = unpack(draft.encrypted_data)
    data['output_locale'] = locale
    GenerationDraft.objects.filter(pk=draft.pk).update(encrypted_data=pack(data))
    ai.add_details(customer, draft.id, COVER_LINES[locale])
    brief = ai.brief_of(unpack(GenerationDraft.objects.get(pk=draft.pk).encrypted_data))
    assert brief.endswith(f'\n\n{ai.COVER_HEADERS[locale]}\n{COVER_LINES[locale]}')
    # title_lines.place reads the lines under the header as the customer's own for the cover.
    assert title_lines.dictated(brief) == COVER_LINES[locale].split('\n')
    assert title_lines.dictated(f'{TOPIC_DECK}\n\n{COVER_LINES[locale]}') == [], 'without it they are not read as title lines'


@pytest.mark.parametrize('header', sorted(ai.COVER_HEADERS.values()))
def test_title_lines_read_every_header_the_answer_goes_under(header):
    for lines in COVER_LINES.values():
        assert title_lines.dictated(f'{TOPIC_DECK}\n\n{header}\n{lines}') == lines.split('\n')


def test_an_answer_for_a_question_not_about_the_cover_has_no_header(customer, decks):
    draft = ai.build(customer, SLIDES, DEFENCE, category=HIMOYA)
    ai.add_details(customer, draft.id, RESULTS)
    brief = ai.brief_of(unpack(GenerationDraft.objects.get(pk=draft.pk).encrypted_data))
    assert brief == f'{DEFENCE}\n\n{RESULTS}'


# --- Under the file -------------------------------------------------------------------------------


def generated(account, category, text, settings, files=()):
    """A category deck made and settled as the worker settles it: (job, its delivery)."""
    draft = ai.build(account, SLIDES, text, files, category=category)
    _, quote = ai.quote(account, draft.id)
    settings.LOCAL_SYNC_JOBS = False
    job = execute_job(ai.start(account, quote.id).id)
    assert job.status == 'succeeded', job.error_code
    return job, BotDelivery.objects.get(artifact__job=job)


def ready_line(account, locale):
    """The caption every file has: who made it, linking to the bot (customer configures fixture_bot)."""
    return ready_caption(RESULT_COPY[locale], *share_link(account, 'fixture_bot'))


def sent(delivery):
    bot = Mock(send_document=AsyncMock(return_value=Mock(message_id=410)))
    asyncio.run(attempt(delivery.id, bot))
    return bot.send_document.await_args.kwargs['caption']


@pytest.mark.parametrize('locale', LOCALES)
def test_the_file_carries_the_categorys_notices(customer, decks, settings, locale):
    speak(customer, locale)
    job, delivery = generated(customer, HIMOYA, DEFENCE, settings)
    notices = categories.get(HIMOYA).raw['bot']['notices']
    # Drafted from the topic with no file: the draft notice. Nothing blanked: no blanks notice.
    assert sent(delivery) == f'{ready_line(customer, locale)}\n\n{html.escape(notices["draft"][locale])}'

    # Code took out a fact the customer did not give: the blanks notice too.
    Job.objects.filter(pk=job.pk).update(warnings=['facts_blanked'])
    job.refresh_from_db()
    assert category_notices(job, locale) == [notices['blanks'][locale], notices['draft'][locale]]


def test_a_deck_made_with_a_file_is_no_draft_and_finished_is_always_said(customer, decks, settings):
    from apps.core.services import upload_file
    asset = upload_file(customer, upload('thesis.docx', docx(THESIS)), 'bot', purpose='ai_source')
    job, delivery = generated(customer, HIMOYA, DEFENCE, settings, [str(asset.id)])
    assert category_notices(job, 'en') == []
    assert sent(delivery) == ready_line(customer, 'en')

    job, delivery = generated(customer, BAYRAM, 'Navro‘z bayrami uchun 6 ta slayd, 5-sinf.', settings)
    finished = categories.get(BAYRAM).raw['bot']['notices']['finished']['en']
    assert category_notices(job, 'en')[0] == finished
    assert sent(delivery) == f'{ready_line(customer, "en")}\n\n{html.escape(finished)}'


def test_a_category_without_its_own_blanks_wording_uses_the_shared_one(customer, decks, settings, monkeypatch):
    job, _ = generated(customer, PITCH, 'Startap pitch: “Toza havo” ilovasi, 8 ta slayd.', settings)
    Job.objects.filter(pk=job.pk).update(warnings=['facts_blanked', 'shortened_to_fit'])
    job.refresh_from_db()
    entry = categories.get(PITCH)
    monkeypatch.setitem(entry.raw['bot'], 'notices', {})
    assert category_notices(job, 'uz') == [UX['uz']['facts_blanked']]


def test_a_document_without_a_category_has_no_notices_and_the_caption_keeps_its_limit():
    job = Mock(parameters={'generation_draft_id': 'x'}, warnings=['facts_blanked'])
    assert category_notices(job, 'en') == []
    assert with_notices('✅ Done!', []) == '✅ Done!'
    long = ['x' * 600, 'y' * 600]
    assert with_notices('✅ Done!', long) == f'✅ Done!\n\n{long[0]}', 'a notice that does not fit is left out'
    assert len(with_notices('✅ Done!', long)) <= CAPTION_LIMIT


def test_the_tasks_screen_says_blanks_in_the_shared_wording(customer, decks, settings):
    job, _ = generated(customer, HIMOYA, DEFENCE, settings)
    Job.objects.filter(pk=job.pk).update(warnings=['facts_blanked'])
    chat = Chat(customer)
    chat.do(text='/myfiles')
    chat.tap('job', job_id=str(job.id))
    assert screen(customer)[0].count(UX['en']['facts_blanked']) == 1


# --- Copy ----------------------------------------------------------------------------------------


NEW_KEYS = ('ai_details_button', 'ai_details_how', 'ai_details_added', 'ai_sources_unread', 'ai_sources_cut',
            'facts_blanked')


@pytest.mark.parametrize('key', NEW_KEYS)
def test_the_review_words_say_the_same_in_every_language(key):
    texts = dict(zip(LOCALES, MESSAGES[key]))
    slots = {locale: sorted(re.findall(r'\{(\w+)\}', value)) for locale, value in texts.items()}
    assert len(set(map(tuple, slots.values()))) == 1
    for locale in ('uz', 'en'):
        assert not CYRILLIC.search(texts[locale])
    assert "'" not in texts['uz'], 'Uzbek is written with ‘ and ’, never an ASCII apostrophe'
    assert len(texts['en']) <= 200


def test_the_cover_headers_are_the_ones_the_architecture_names():
    assert ai.COVER_HEADERS == {'uz': 'Titul slaydga:', 'ru': 'На титульном слайде:', 'en': 'Title slide:'}
