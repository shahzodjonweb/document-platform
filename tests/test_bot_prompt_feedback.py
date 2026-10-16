"""The bot tells the customer what is wrong with a description, and keeps what they wrote.

In production most failed AI documents were a description with no topic
("make a pdf on the topic", "bright slides", "convert to pdf"), refused by the
server or made about a subject the model invented, or a reply the model could
not finish, followed by a notice that only said the provider failed. Now:

* A description that names no topic becomes one question, in place of
  "Preparing…": what was kept, and what is missing. The topic sent next is
  put in front of what was kept. Nothing is made or counted until then.
* Slides asked of the PDF service (or the reverse) are offered the other
  service, on that question and, said first, on the review.
* A failed AI document says what to try, with Retry and a new description.
* A whole description sent as the answer replaces what was kept; a PDF sent
  is the topic; a conversion ("pdf ga o‘tkaz") is sent to the file tools.

Every description here is written for the test; none is a customer's.
"""
import asyncio
import io
import json
import re
from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.commerce.models import LocalBotMessage
from apps.core import channel_gate
from apps.core.allowance import ai_documents_this_week
from apps.core.errors import DomainError
from apps.core.identity import resolve_account
from apps.core.models import BotCallback, BotConversation, BotJobNotice, ChannelMembership, Job, Quote
from apps.studio.domain import DOCUMENT, SLIDES, pack, unpack
from apps.studio.models import GenerationDraft
from operations.integrations import save_config
from telegram.bot import BRIEF_CHARS, REUSABLE, brief_quote, kept_brief
from telegram.channels import COPY as GATE
from telegram.errors import bot_error
from telegram.local import LocalTelegramSession
from telegram.notifications import attempt_notice, enqueue_notice
from telegram.notifications import COPY as NOTICE
from telegram.ux_copy import MESSAGES, TOOL_NAMES, UX
from tests.test_bot_generation import customer, describe, latest  # noqa: F401
from tests.test_bot_no_flood import Chat
from tests.test_bot_terminal_notifications import terminal_job
from tests.test_channel_gate import Telegram, require_channels
from tests.test_manual_payments import pdf

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]


@pytest.fixture(autouse=True)
def model():
    # A model to write with: in local authoring the text is the document itself,
    # and there is no topic to ask for.
    save_config('ai', {'mode': 'openai', 'model': 'gpt-5.6-luna', 'api_key': 'sk-offline-test-only'})


def ask(account, service=DOCUMENT):
    """A chat that has chosen an AI service and is asked for its description."""
    chat = Chat(account)
    chat.do(text='/ai')
    assert chat.tap('ai_tool', feature_id=service) == 0
    return chat


def screen(account):
    """The bot's newest message: its text, and its buttons as rows of actions."""
    message = LocalBotMessage.objects.filter(account=account, direction='outbound').order_by('-created_at').first()
    actions = [[BotCallback.objects.get(pk=button['callback_data']).action if button.get('callback_data') else 'url'
                for button in row] for row in message.buttons]
    return message, actions


def pending(account):
    """The chat's state and what it keeps, without the topic question's own name."""
    conversation = BotConversation.objects.get(pk=account.telegram_user_id)
    return conversation.state, {key: value for key, value in conversation.prompt.items() if key != 'question'}


def jpeg():
    from PIL import Image
    out = io.BytesIO()
    Image.new('RGB', (60, 80), (200, 30, 30)).save(out, 'JPEG')
    return out.getvalue()


def speak(account, locale):
    account.locale = locale
    account.save(update_fields=['locale'])
    BotConversation.objects.filter(pk=account.telegram_user_id).update(locale=locale)


# --- No topic: one question, in place --------------------------------------------

def test_a_description_with_no_topic_becomes_one_question_and_nothing_is_made(customer):
    chat = ask(customer)
    assert chat.do(text='I need a 5 page document') == 1, '"Preparing…" becomes the question; nothing else is sent'
    message, actions = screen(customer)
    assert UX['en']['ai_topic_question'] in message.text
    assert '📝 Noted: “I need a 5 page document”.' in message.text, 'what was kept is quoted back'
    assert '<code>The water cycle, for 6th grade</code>' in message.text
    assert '⚠️' not in message.text and 'Check the request' not in message.text, 'a question, not an error'
    assert actions == [['ai_examples'], ['home']], 'no other service was asked for'
    assert not GenerationDraft.objects.filter(account=customer).exists()
    assert not Quote.objects.filter(account=customer).exists() and not Job.objects.filter(account=customer).exists()
    assert ai_documents_this_week(customer) == 0
    assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT, 'brief': ['I need a 5 page document']})
    # What they wrote waits in the chat's state: no button carries it.
    assert not any('5 page' in json.dumps(ref.payload) for ref in BotCallback.objects.filter(account=customer))

    # The topic goes first, so it is the title; the length asked for still holds.
    assert chat.do(text='Blue whales') == 1
    review = chat.last()
    assert 'Ready to start' in review and '📄 Blue whales' in review and 'Pages: 5' in review, review
    assert latest(customer)['prompt'] == 'Blue whales\nI need a 5 page document'
    assert pending(customer) == ('', {}), 'answered: nothing is kept any more'
    assert not Job.objects.filter(account=customer).exists(), 'the review comes first, as ever'


def test_still_no_topic_keeps_every_piece_and_asks_once_more(customer):
    chat = ask(customer, SLIDES)
    assert chat.do(text='10 slides please') == 1
    assert chat.do(text='in blue') == 1, 'asked again in one message'
    assert '“10 slides please · in blue”' in chat.last()
    assert pending(customer)[1]['brief'] == ['10 slides please', 'in blue']
    assert not GenerationDraft.objects.filter(account=customer).exists()
    assert chat.do(text='Volcanoes for year 8') == 1
    assert 'Slides: 10' in chat.last() and '📄 Volcanoes for year 8' in chat.last(), chat.last()
    assert latest(customer, SLIDES)['prompt'] == 'Volcanoes for year 8\n10 slides please\nin blue'


def test_a_description_sent_again_is_taken_as_its_topic(customer):
    """The check reads words; a topic it does not know must not keep anyone asking."""
    chat = ask(customer)
    assert chat.do(text='Make it 5 pages') == 1
    assert UX['en']['ai_topic_again'] in chat.last(), 'the way past the question is said'
    assert chat.do(text='make it  5 pages') == 1, 'the same words again'
    assert 'Ready to start' in chat.last(), chat.last()
    assert latest(customer)['prompt'] == 'make it  5 pages', 'said once, not twice'
    assert 'topic_given' not in latest(customer)['options'], 'a request, not a setting'
    assert pending(customer) == ('', {})


def test_a_second_answer_to_the_topic_question_is_taken_as_it_is(customer):
    chat = ask(customer, SLIDES)
    chat.do(text='10 slides please')
    chat.do(text='in blue')
    assert chat.do(text='with pictures') == 1
    assert 'Ready to start' in chat.last(), 'asked twice is enough'
    assert latest(customer, SLIDES)['prompt'] == 'with pictures\n10 slides please\nin blue'


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_the_topic_question_says_how_to_go_past_it(customer, locale):
    speak(customer, locale)
    chat = ask(customer)
    chat.do(text='5 sahifa' if locale == 'uz' else '5 страниц' if locale == 'ru' else '5 pages')
    assert UX[locale]['ai_topic_again'] in chat.last()


def test_what_is_kept_is_capped_and_the_first_piece_stays(customer):
    # The question is asked twice at most (a second answer is taken as it is),
    # so the cap guards what one long piece or a stale state can hold.
    chat = ask(customer, SLIDES)
    chat.do(text='10 slides please ' + 'in blue ' * 140)  # long, but under the 300 words the check reads
    assert len(''.join(pending(customer)[1]['brief'])) <= BRIEF_CHARS
    # The first says how many; the newest after it fill the rest.
    assert kept_brief(['a', 'b', 'c', 'd']) == ['a', 'c', 'd']
    assert kept_brief(['', 'a']) == ['a'] and kept_brief([]) == []
    assert kept_brief(['x' * 600, 'y' * 300, 'z' * 300]) == ['x' * 600, 'z' * 300]
    assert kept_brief(['w' * 1500, 'v']) == ['w' * BRIEF_CHARS]
    assert brief_quote(['12 ta slayd\n  kk', 'ko‘k rangda']) == '12 ta slayd kk · ko‘k rangda'
    long = brief_quote(['word ' * 100])
    assert len(long) == 160 and long.endswith('…')


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_the_question_is_asked_in_the_customers_language(customer, locale):
    speak(customer, locale)
    chat = ask(customer)
    assert chat.do(text='Ko‘k rangda bo‘lsin') == 1
    shown = chat.last()
    assert UX[locale]['ai_topic_question'] in shown
    assert UX[locale]['ai_topic_kept'].format(brief='Ko‘k rangda bo‘lsin') in shown
    assert UX[locale]['ai_topic_sample'] in shown and TOOL_NAMES[DOCUMENT][locale] in shown


def test_the_new_words_say_the_same_in_every_language():
    keys = ('ai_topic_kept', 'ai_topic_question', 'ai_topic_example', 'ai_topic_sample', 'ai_failed_advice',
            'ai_pdf_anyway', 'ai_slides_anyway', 'ai_review_hint_button', 'ai_topic_pdf_only', 'ai_convert')
    for key in keys:
        en, uz, ru = MESSAGES[key]
        assert len({frozenset(re.findall(r'{\w+}', value)) for value in (en, uz, ru)}) == 1, key
        assert not re.search('[а-яёўқғҳ]', uz, re.IGNORECASE), f'{key}: Uzbek is written in Latin'
        assert '<' not in en + uz + ru and '&' not in en + uz + ru, f'{key} is shown as HTML'
    failed = [bot_error(DomainError('provider_failed'), locale) for locale in ('en', 'uz', 'ru')]
    assert not any(word in value.lower() for value in failed for word in ('provider', 'provayder', 'провайдер'))
    assert 'ИИ' in failed[2] and 'AI' not in failed[2]


def test_the_topic_question_says_each_thing_once():
    (kept_en, kept_uz, kept_ru), (en, uz, ru) = MESSAGES['ai_topic_kept'], MESSAGES['ai_topic_question']
    assert 'keep' not in kept_en + en and en.lower().count('topic') == 1
    assert uz.count('yoz') == 0, 'Mavzuni yozing — uni yozganingizga: yoz- twice'
    assert 'о чём сделать' not in ru and ru.count('тем') == 2


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_a_failed_deck_is_not_called_a_document_and_warns_once(locale):
    _, job = terminal_job('failed', locale=locale)
    Job.objects.filter(pk=job.pk).update(feature_id=SLIDES, parameters={}, error_code='provider_failed')
    text, _ = sent(job)
    assert not any(word in text.lower() for word in ('document', 'hujjat', 'документ')), text
    assert text.count('⚠️') == 1, 'the header says it once'
    assert text.splitlines()[1] == TOOL_NAMES[SLIDES][locale]


# --- The other service ------------------------------------------------------------

def test_slides_asked_of_the_pdf_service_without_a_topic_switch_and_keep_what_was_written(customer):
    chat = ask(customer)
    assert chat.do(text='create slides in blue') == 1
    message, actions = screen(customer)
    assert f'<b>{UX["en"]["ai_wrong_tool_slides"]}</b>' in message.text
    assert actions[0] == ['ai_retarget'] and message.buttons[0][0]['label'] == UX['en']['ai_switch_slides']
    ref = BotCallback.objects.get(pk=message.buttons[0][0]['callback_data'])
    assert ref.payload == {'feature_id': SLIDES, 'question': BotConversation.objects.get(
        pk=customer.telegram_user_id).prompt['question']}, 'the button names the service and its question, never the description'

    assert chat.tap('ai_retarget', feature_id=SLIDES) == 0, 'the question changes in place'
    assert pending(customer) == ('ai_input', {'feature_id': SLIDES, 'brief': ['create slides in blue']})
    message, actions = screen(customer)
    assert TOOL_NAMES[SLIDES]['en'] in message.text and '“create slides in blue”' in message.text
    assert 'ai_retarget' not in sum(actions, []), 'slides are what this service makes'

    assert chat.do(text='Volcanoes') == 1
    assert 'Ready to start' in chat.last() and 'Slides:' in chat.last()
    assert latest(customer, SLIDES)['prompt'] == 'Volcanoes\ncreate slides in blue'
    assert not GenerationDraft.objects.filter(account=customer, feature_id=DOCUMENT).exists()


def test_an_old_switch_button_opens_a_plain_question(customer):
    assert 'ai_retarget' in REUSABLE, 'it only opens a question, so a scrolled-back tap still works'
    chat = ask(customer)
    chat.do(text='create slides in blue')
    ref = BotCallback.objects.get(account=customer, action='ai_retarget')
    assert ref.expires_at > timezone.now() + timedelta(days=7)
    question = next(message for message in LocalBotMessage.objects.filter(account=customer, direction='outbound')
                    if any(button.get('callback_data') == ref.pk for row in message.buttons for button in row))
    chat.do(text='Volcanoes')
    assert 'Ready to start' in chat.last()
    # Answered since: the tap is a plain choice of the service.
    assert chat.do(callback_data=ref.pk) == 0
    assert pending(customer) == ('ai_input', {'feature_id': SLIDES})
    question.refresh_from_db()
    assert 'Describe what you want' in question.text and TOOL_NAMES[SLIDES]['en'] in question.text
    # A question left open too long is not resumed either.
    chat = ask(customer)
    chat.do(text='create slides in blue')
    BotConversation.objects.filter(pk=customer.telegram_user_id).update(updated_at=timezone.now() - timedelta(minutes=31))
    assert chat.tap('ai_retarget', feature_id=SLIDES) == 0
    assert pending(customer) == ('ai_input', {'feature_id': SLIDES})
    assert 'Describe what you want' in screen(customer)[0].text


@pytest.fixture
def member(settings, monkeypatch):
    """A Free customer, whose services wait behind the owner's channels."""
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    account = resolve_account({'id': 984077, 'first_name': 'Channel member'}, is_test=True)
    BotConversation.objects.create(telegram_user_id=account.telegram_user_id, locale='en',
                                   language_selected_at=timezone.now())
    fake = Telegram()
    monkeypatch.setattr(channel_gate, '_call', fake)
    monkeypatch.setattr(channel_gate, '_token', lambda: '1:TOKEN')
    require_channels()
    fake.statuses = {'@pdfmaster_news': 'member'}
    return account, fake


def test_the_switch_passes_the_channel_check_and_comes_back_to_the_question(member):
    account, telegram = member
    chat = ask(account)
    chat.do(text='create slides in blue')
    # They leave the channel before choosing slides.
    telegram.statuses = {}
    ChannelMembership.objects.all().delete()
    assert chat.tap('ai_retarget', feature_id=SLIDES) == 0
    assert GATE['en']['gate_one'] in chat.last()
    telegram.statuses = {'@pdfmaster_news': 'member'}
    chat.tap('channels_check')
    assert UX['en']['ai_topic_question'] in chat.last() and '“create slides in blue”' in chat.last()
    assert pending(account) == ('ai_input', {'feature_id': SLIDES, 'brief': ['create slides in blue']})


def test_the_topic_typed_behind_the_channels_goes_to_the_service_chosen(member):
    account, telegram = member
    chat = ask(account)
    chat.do(text='create slides in blue')
    telegram.statuses = {}
    ChannelMembership.objects.all().delete()
    chat.tap('ai_retarget', feature_id=SLIDES)
    assert pending(account) == ('ai_input', {'feature_id': SLIDES, 'brief': ['create slides in blue']})
    chat.do(text='Volcanoes')
    telegram.statuses = {'@pdfmaster_news': 'member'}
    chat.tap('channels_check')
    assert list(GenerationDraft.objects.filter(account=account).values_list('feature_id', flat=True)) == [SLIDES]
    assert 'Slides:' in chat.last(), chat.last()


# --- What drops what was kept ---------------------------------------------------

def test_the_menu_another_service_or_a_file_starts_afresh(customer):
    chat = ask(customer)
    chat.do(text='I need a 5 page document')
    chat.tap('home')
    assert pending(customer) == ('', {})
    assert chat.do(text='Blue whales') == 1 and 'Send a file or use the buttons below' in chat.last()
    assert not GenerationDraft.objects.filter(account=customer).exists()

    chat = ask(customer)
    chat.do(text='I need a 5 page document')
    chat.tap('ai_examples')
    assert pending(customer)[1]['brief'] == ['I need a 5 page document'], 'looking at examples keeps it'
    chat.tap('ai_tool', feature_id=SLIDES)
    assert pending(customer) == ('ai_input', {'feature_id': SLIDES})


# --- What the answer to the question can be -------------------------------------

def test_a_whole_description_sent_as_the_answer_replaces_what_was_kept(customer):
    """Rewriting the whole request is a natural answer to "what should it be about?"."""
    chat = ask(customer)
    assert chat.do(text='10 slides please') == 1
    assert chat.do(text='A 3 page PDF report about volcanoes for year 8') == 1
    message, _ = screen(customer)
    assert message.text.startswith('<b>✅ Ready to start</b>'), 'not told it asked for slides: ' + message.text[:120]
    assert 'Pages: 3' in message.text
    assert latest(customer)['prompt'] == 'A 3 page PDF report about volcanoes for year 8'
    assert [button['label'] for button in message.buttons[0]] == [UX['en']['ai_generate']]
    # A topic alone is still joined to what was kept.
    chat = ask(customer, SLIDES)
    chat.do(text='10 slides please')
    chat.do(text='Volcanoes')
    assert latest(customer, SLIDES)['prompt'] == 'Volcanoes\n10 slides please'


def test_a_pdf_sent_while_the_topic_is_asked_for_is_what_it_is_about(customer):
    chat = ask(customer)
    chat.do(text='I need a 5 page document')
    assert chat.do(uploaded=SimpleUploadedFile('notes.pdf', pdf(), 'application/pdf')) == 1
    review = chat.last()
    assert 'Ready to start' in review and 'Pages: 5' in review, review
    data = latest(customer)
    assert data['prompt'] == 'I need a 5 page document' and len(data['source_ids']) == 1, 'nothing to type again'
    assert pending(customer) == ('', {})
    assert not Job.objects.filter(account=customer).exists(), 'the review comes first, as ever'


def test_a_photo_sent_while_the_topic_is_asked_for_keeps_what_was_written(customer):
    """The AI services read PDFs only: a photo is no topic, and the question stays."""
    chat = ask(customer)
    chat.do(text='I need a 5 page document')
    assert chat.do(uploaded=SimpleUploadedFile('board.jpg', jpeg(), 'image/jpeg')) == 1
    shown = chat.last()
    assert UX['en']['ai_topic_pdf_only'] in shown and UX['en']['ai_topic_question'] in shown
    assert '“I need a 5 page document”' in shown
    assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT, 'brief': ['I need a 5 page document']})
    assert not GenerationDraft.objects.filter(account=customer).exists()
    assert chat.do(text='Blue whales') == 1
    assert 'Pages: 5' in chat.last(), chat.last()
    assert latest(customer)['prompt'] == 'Blue whales\nI need a 5 page document'


@pytest.mark.parametrize('locale,words', [('uz', 'pdf ga otqaz'), ('en', 'convert to pdf'), ('ru', 'переведи в pdf')])
def test_a_conversion_asked_of_an_ai_service_is_sent_to_the_file_tools(customer, locale, words):
    speak(customer, locale)
    chat = ask(customer)
    assert chat.do(text=words) == 1
    message, actions = screen(customer)
    assert UX[locale]['ai_convert'] in message.text and UX[locale]['ai_topic_question'] not in message.text
    # The converters this server offers (Word and PowerPoint need LibreOffice), and All tools.
    assert ['tool'] in actions and actions[-1] == ['menu', 'home'], actions
    assert pending(customer) == ('', {}), 'a file sent next starts a file task'
    assert not GenerationDraft.objects.filter(account=customer).exists()


def test_a_refusal_for_no_topic_does_not_use_one_of_the_minutes_builds(customer):
    from django.core.cache import cache
    from telegram import generation as ai
    cache.delete(f'rate:bot_generation:{customer.pk}')
    for words in ['12 ta slayd kerak'] * 11 + ['pdf ga otqaz']:
        with pytest.raises(DomainError) as refused:
            ai.build(customer, SLIDES, words)
        assert refused.value.code in ('topic_required', 'convert_requested')
    assert ai.build(customer, SLIDES, 'Vulqonlar haqida 10 ta slayd')


def test_an_old_switch_button_never_carries_a_newer_question(customer):
    chat = ask(customer)
    chat.do(text='create slides in blue')
    old = BotCallback.objects.get(account=customer, action='ai_retarget')
    chat.do(text='Volcanoes')
    # Later, a new question in the PDF service, about a PDF; the old button is tapped.
    chat = ask(customer)
    chat.do(text='I need a 5 page document')
    assert chat.do(callback_data=old.pk) == 0
    assert pending(customer) == ('ai_input', {'feature_id': SLIDES}), 'a plain question, nothing carried'
    chat.do(text='Blue whales')
    assert latest(customer, SLIDES)['prompt'] == 'Blue whales'


def test_the_switch_still_carries_the_description_while_it_is_asked_about_again(customer):
    chat = ask(customer)
    chat.do(text='create slides in blue')
    first = BotCallback.objects.get(account=customer, action='ai_retarget')
    chat.do(text='with pictures')  # still no topic: the same question, asked again
    assert chat.do(callback_data=first.pk) == 0
    assert pending(customer) == ('ai_input', {'feature_id': SLIDES, 'brief': ['create slides in blue', 'with pictures']})


def test_switching_a_draft_with_no_topic_asks_for_it(customer):
    """A draft accepted before descriptions were read for a topic (or whose file
    has gone) is switched to the other service: its topic is asked for there."""
    review = describe(customer, 'Volcanoes, 10 slides')
    draft = GenerationDraft.objects.filter(account=customer, feature_id=DOCUMENT).latest('created_at')
    data = unpack(draft.encrypted_data)
    data['prompt'] = data['title'] = '10 ta slayd kk'
    draft.encrypted_data = pack(data)
    draft.save(update_fields=['encrypted_data'])
    switch = next(button['callback_data'] for message in review['messages'] for row in message['buttons']
                  for button in row if button.get('callback_data')
                  and BotCallback.objects.filter(pk=button['callback_data'], action='ai_switch').exists())
    chat = Chat(customer)
    assert chat.do(callback_data=switch) == 0
    shown = chat.last()
    assert UX['en']['ai_topic_question'] in shown and TOOL_NAMES[SLIDES]['en'] in shown and '“10 ta slayd kk”' in shown
    assert pending(customer) == ('ai_input', {'feature_id': SLIDES, 'brief': ['10 ta slayd kk']})
    chat.do(text='Volcanoes')
    assert 'Ready to start' in chat.last() and 'Slides: 10' in chat.last(), chat.last()


# --- The review says the other service first -------------------------------------

def test_a_deck_asked_of_the_pdf_service_is_said_first_and_generate_says_it_makes_a_pdf(customer, settings):
    settings.LOCAL_SYNC_JOBS = False
    describe(customer, '10 slides on volcanoes for year 8')
    message, actions = screen(customer)
    assert message.text.startswith(f'<b>{UX["en"]["ai_wrong_tool_slides"]}</b>\n\n'), message.text[:200]
    labels = [[button['label'] for button in row] for row in message.buttons]
    assert labels[0] == [UX['en']['ai_switch_slides']] and labels[1] == [UX['en']['ai_pdf_anyway']], labels
    assert UX['en']['ai_generate'] not in sum(labels, [])
    assert 'Nothing counts until you tap “Make a PDF anyway”.' in message.text
    assert not Job.objects.filter(account=customer).exists(), 'never made without a tap'
    Chat(customer).do(callback_data=message.buttons[1][0]['callback_data'])
    assert Job.objects.get(account=customer).feature_id == DOCUMENT, 'the customer may still want the PDF'

    describe(customer, 'A 3 page PDF report on volcanoes', service='Slides on a topic')
    message, _ = screen(customer)
    assert message.text.startswith(f'<b>{UX["en"]["ai_wrong_tool_pdf"]}</b>')
    assert [button['label'] for button in message.buttons[1]] == [UX['en']['ai_slides_anyway']]
    assert '«Baribir slayd tayyorlash»' in UX['uz']['ai_review_hint_button'].format(
        button=UX['uz']['ai_slides_anyway'].split(' ', 1)[1])

    describe(customer, 'A 3 page guide to tide tables.')
    message, _ = screen(customer)
    assert message.text.startswith('<b>✅ Ready to start</b>') and UX['en']['ai_review_hint'] in message.text
    assert [button['label'] for button in message.buttons[0]] == [UX['en']['ai_generate']]


# --- A document the AI could not finish -----------------------------------------

def failed_document(account, settings):
    settings.LOCAL_SYNC_JOBS = False
    review = describe(account, 'A one page introduction to tidal energy.')
    Chat(account).do(callback_data=next(button['callback_data'] for message in review['messages']
                                        for row in message['buttons'] for button in row if 'Generate' in button['label']))
    job = Job.objects.get(account=account)
    Job.objects.filter(pk=job.pk).update(status='failed', error_code='provider_failed')
    job.refresh_from_db()
    return job


def local_notice(job):
    """The failure notice, sent into the simulated chat so its buttons can be tapped."""
    from aiogram import Bot
    BotJobNotice.objects.filter(job=job).delete()
    notice = enqueue_notice(job)

    async def send():
        bot = Bot('123456:LOCAL_SIMULATOR_NO_NETWORK', session=LocalTelegramSession(job.account))
        try:
            await attempt_notice(notice.id, bot)
        finally:
            await bot.session.close()
    asyncio.run(send())
    return screen(job.account)


def test_a_failed_document_says_what_to_try_and_offers_retry_and_a_new_description(customer, settings):
    job = failed_document(customer, settings)
    message, actions = local_notice(job)
    assert actions == [['ai_retry'], ['ai_tool'], ['job', 'recent'], ['home']]
    assert [button['label'] for button in message.buttons[0] + message.buttons[1]] == [
        UX['en']['retry_task'], UX['en']['ai_change_topic']]
    assert UX['en']['ai_failed_advice'] in message.text and 'provider' not in message.text.lower()
    assert message.text.count('count') == 1, 'it is said once that nothing was counted'

    # Retry shows the same description's review again; nothing runs.
    Chat(customer).do(callback_data=message.buttons[0][0]['callback_data'])
    message.refresh_from_db()
    assert 'Ready to start' in message.text and Job.objects.count() == 1

    # A new description: the service's question, ready for it.
    message, _ = local_notice(job)
    Chat(customer).do(callback_data=message.buttons[1][0]['callback_data'])
    message.refresh_from_db()
    assert 'Describe what you want' in message.text
    assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT})

    # The task's own screen says the same.
    chat = Chat(customer)
    chat.do(text='/myfiles')
    chat.tap('job', job_id=str(job.id))
    message, actions = screen(customer)
    assert UX['en']['ai_failed_advice'] in message.text
    assert actions[:2] == [['ai_retry'], ['ai_tool']]


def sent(job):
    """The notice's text and its buttons, as rows of (action, label)."""
    BotJobNotice.objects.filter(job=job).delete()
    job.refresh_from_db()
    notice = enqueue_notice(job)
    bot = Mock(send_message=AsyncMock(return_value=Mock(message_id=77)))
    asyncio.run(attempt_notice(notice.id, bot))
    call = bot.send_message.await_args
    rows = [[(BotCallback.objects.get(pk=button.callback_data).action, button.text) for button in row]
            for row in call.kwargs['reply_markup'].inline_keyboard]
    return call.args[1], rows


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_the_failure_notice_is_advice_in_each_language(locale):
    _, job = terminal_job('failed', locale=locale)
    Job.objects.filter(pk=job.pk).update(feature_id=DOCUMENT, parameters={}, error_code='provider_failed')
    text, rows = sent(job)
    assert text.splitlines()[1] == TOOL_NAMES[DOCUMENT][locale], 'which service, in place of a file task’s line'
    assert bot_error(DomainError('provider_failed'), locale) in text
    assert text.endswith('\n\n' + UX[locale]['ai_failed_advice'])
    assert NOTICE[locale]['not_counted'] not in text and NOTICE[locale]['failed'] not in text
    assert rows[:2] == [[('ai_retry', UX[locale]['retry_task'])], [('ai_tool', UX[locale]['ai_change_topic'])]]
    retry = BotCallback.objects.get(account=job.account, action='ai_retry')
    assert retry.payload['job_id'] == str(job.id)
    assert BotCallback.objects.get(account=job.account, action='ai_tool').payload['feature_id'] == DOCUMENT


@pytest.mark.parametrize('parameters,error', [
    ({'revision': True, 'root_draft_id': 'draft'}, 'provider_failed'),  # a change: its own Make changes
    ({'stage': 'outline'}, 'provider_failed'),                           # an outline has no Retry here
    ({}, 'generation_limit'),                                           # not the model failing
])
def test_other_failures_keep_the_plain_notice(parameters, error):
    _, job = terminal_job('failed')
    Job.objects.filter(pk=job.pk).update(feature_id=DOCUMENT, parameters=parameters, error_code=error)
    text, rows = sent(job)
    assert [action for row in rows for action, _ in row] == ['job', 'new', 'recent', 'home']
    assert UX['en']['ai_failed_advice'] not in text


def test_a_file_task_notice_is_unchanged():
    _, job = terminal_job('failed')
    text, rows = sent(job)
    assert [action for row in rows for action, _ in row] == ['job', 'new', 'recent', 'home']
    assert NOTICE['en']['failed'] in text and UX['en']['ai_failed_advice'] not in text
