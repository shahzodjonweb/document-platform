"""A CV from the chat: one message about yourself, a photo if you like, a review, a PDF.

The third AI service (`ai.cv`) works like the other two: one message in, a
priced review out, nothing counted until Generate. What differs is what it asks
for and what it shows. It asks only for what a CV cannot be made without, the
person's name, and keeps everything already written while it does. A photo sent
before or after the description is the CV's portrait, kept with the question
and never as a file task. The review shows the template and the photo, not a
page count to adjust. Everyone in these tests is made up (example.com contacts).
"""
import io
import json

import pytest
from asgiref.sync import async_to_sync
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.commerce.models import LocalBotMessage
from apps.core.models import BotCallback, BotConversation, BotDraft, BotInputReceipt, FileAsset, Job, Quote
from apps.studio.cv.content import name_in
from apps.studio.domain import CV
from apps.studio.models import GenerationDraft
from operations.integrations import save_config
from telegram import generation
from telegram.bot import CV_BRIEF_CHARS, review_screen
from telegram.local import dispatch_local
from telegram.ux_copy import LOCALES, MESSAGES, PROMPT_EXAMPLES, TOOL_NAMES, UX
from tests.test_bot_generation import customer, describe, labels, latest, tap  # noqa: F401
from tests.test_cv_content import BRIEF
from tests.test_manual_payments import pdf

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]

SERVICE = 'CV · AI'
FLAGS = {'🇬🇧', '🇺🇿', '🇷🇺'}
# BRIEF without its first line: everything about the person but who they are.
NAMELESS = BRIEF.split('\n', 1)[1]


@pytest.fixture
def model():
    # A model to write with: the description is sent as the prompt, as in production.
    save_config('ai', {'mode': 'openai', 'model': 'gpt-5.6-luna', 'api_key': 'sk-offline-test-only'})


def screen(result):
    """The bot's newest message as it reads now: (text, button labels)."""
    shown = [message for message in result['messages'] if message.get('direction') != 'inbound'][-1]
    return shown['text'], [button['label'] for row in shown['buttons'] for button in row]


def actions(account):
    """The newest message's buttons, as rows of actions ('url' for a link)."""
    message = LocalBotMessage.objects.filter(account=account, direction='outbound').order_by('-created_at').first()
    return [[BotCallback.objects.get(pk=button['callback_data']).action if button.get('callback_data') else 'url'
             for button in row] for row in message.buttons]


def state(account):
    conversation = BotConversation.objects.get(pk=account.telegram_user_id)
    return conversation.state, {key: value for key, value in conversation.prompt.items() if key != 'question'}


def image(name='me.jpg', fmt='JPEG', size=(300, 400)):
    from PIL import Image
    out = io.BytesIO()
    Image.new('RGB', size, (120, 140, 160)).save(out, fmt)
    return SimpleUploadedFile(name, out.getvalue(), f'image/{fmt.lower()}')


def ask(account):
    """The CV service chosen from the menu: its question on screen."""
    return tap(account, dispatch_local(account, text='/start'), SERVICE)


def cv(account):
    return GenerationDraft.objects.filter(account=account, feature_id=CV).latest('created_at')


def file_task_waiting(account):
    draft = BotDraft.objects.filter(account=account).first()
    return bool(draft and draft.input_ids)


# --- The service and its question ------------------------------------------------------

def test_the_cv_is_the_third_service_on_the_home_screen(customer):
    rows = dispatch_local(customer, text='/start')['messages'][-1]['buttons']
    assert [row[0]['label'] for row in rows[:3]] == [
        '✨ PDF on a topic · AI', '✨ Slides on a topic · AI', '✨ CV · AI']


def test_cv_opens_the_question_about_you(customer):
    words, shown = screen(dispatch_local(customer, text='/cv'))
    assert words.startswith('<b>✨ CV · AI</b>\n' + UX['en']['cv_ask']), words[:300]
    assert f'<i>{UX["en"]["cv_photo_hint"]}</i>' in words
    assert f'1. <code>{PROMPT_EXAMPLES[CV][0][0]}</code>' in words
    # No page count is asked for: one page or two is the template's to decide.
    assert 'how many pages' not in words and UX['en']['ai_pages_hint'] not in words
    assert shown == [UX['en']['ai_examples'], UX['en']['ai_back']]
    assert state(customer) == ('ai_input', {'feature_id': CV})


@pytest.mark.parametrize('locale', LOCALES)
def test_every_cv_example_is_a_brief_that_reaches_a_review(customer, locale):
    """Each names the person and no page count, and is priced like any description."""
    customer.locale = locale
    customer.save(update_fields=['locale'])
    BotConversation.objects.filter(pk=customer.telegram_user_id).update(locale=locale)
    for row in PROMPT_EXAMPLES[CV]:
        sample = row[LOCALES.index(locale)]
        draft = generation.build(customer, CV, sample)
        assert generation.title_of(draft) == name_in(sample) != ''
        _, quote = generation.quote(customer, draft.id)
        words, rows = async_to_sync(review_screen)(customer, draft, quote)
        assert f'{UX[locale]["ai_pages"]}: 1–2' in words and UX[locale]['cv_photo_none_add'] in words, words
        assert rows[0][0].text == UX[locale]['ai_generate']
    # The whole list of examples still fits in one Telegram message.
    listing, _ = screen(dispatch_local(customer, text='/examples'))
    assert len(listing) < 4096 and TOOL_NAMES[CV][locale] in listing


def test_an_example_sent_back_unchanged_asks_for_your_own_details(customer):
    caught = describe(customer, PROMPT_EXAMPLES[CV][1][0], service=SERVICE)
    assert screen(caught)[0] == UX['en']['cv_example_copied']
    assert not GenerationDraft.objects.filter(account=customer).exists()


# --- One message to a review ----------------------------------------------------------------

def test_one_message_becomes_a_priced_review_with_the_template_and_the_photo(customer, model):
    review = describe(customer, BRIEF, service=SERVICE)
    words, shown = screen(review)
    draft = cv(customer)
    assert '📄 Dilnoza Karimova' in words and 'Pages: 1–2' in words, words
    assert 'Template: Auto — classic unless you pick one' in words
    assert '📷 Photo: none — to add one, send it here' in words
    # No count to put right: the stepper is a document's and a deck's.
    assert '➖' not in shown and '➕' not in shown and 'Pages: 8' not in words, shown
    assert shown[0] == '✨ Generate' and FLAGS <= {label.replace('✅ ', '') for label in shown}, shown
    (setup,) = [button for message in review['messages'][-1:] for row in message['buttons'] for button in row
                if button['label'] == '🎨 CV template']
    # An https Mini App: the simulator records its address as the button's link.
    assert setup['url'] == f'https://pdfmaster.example/en/app/cv-setup?draft={draft.id}'
    assert latest(customer, CV)['title'] == 'Dilnoza Karimova' and latest(customer, CV)['prompt'] == BRIEF
    assert not Job.objects.filter(account=customer).exists(), 'nothing runs before the review'
    # The review stays open to a photo for as long as it is the chat's screen.
    assert state(customer) == ('cv_review', {'draft_id': str(draft.id)})


def test_a_description_without_a_name_asks_only_for_the_name_and_keeps_every_word(customer, model):
    # Longer than a topic brief may keep (1000 characters): a CV's is kept whole.
    work = ' '.join(f'Quarterly sales report number {n} for the Samarkand branch, built in Power BI.' for n in range(1, 25))
    long = f'{NAMELESS}\n{work}'
    assert 1800 <= len(long) <= CV_BRIEF_CHARS and name_in(long) == ''
    ask(customer)
    words, _ = screen(dispatch_local(customer, text=long))
    assert UX['en']['cv_name_question'] in words and '<code>Dilnoza Karimova</code>' in words, words
    assert UX['en']['cv_name_again'] in words and '📝 Noted: “Data analyst in Tashkent.' in words
    assert UX['en']['ai_topic_question'] not in words and UX['en']['ai_topic_again'] not in words
    assert actions(customer) == [['ai_examples'], ['home']], 'no other service is offered'
    assert state(customer) == ('ai_input', {'feature_id': CV, 'brief': [long], 'ask': 'name'})
    assert not GenerationDraft.objects.filter(account=customer).exists()
    assert not Quote.objects.filter(account=customer).exists()

    words, _ = screen(dispatch_local(customer, text='Dilnoza Karimova'))
    assert '📄 Dilnoza Karimova' in words and 'Pages: 1–2' in words, words
    assert latest(customer, CV)['prompt'] == f'Dilnoza Karimova\n{long}', 'the name, then every word written before'


def test_a_name_the_check_cannot_see_is_taken_when_sent_again(customer, model):
    ask(customer)
    dispatch_local(customer, text=NAMELESS)
    assert UX['en']['cv_name_question'] in screen(dispatch_local(customer, text='dilnoza karimova'))[0]
    words, _ = screen(dispatch_local(customer, text='dilnoza karimova'))
    assert '📄 dilnoza karimova' in words and 'Pages: 1–2' in words, words


# --- The photo --------------------------------------------------------------------------------

def test_a_photo_sent_in_the_chat_becomes_the_cvs_photo(customer, model):
    ask(customer)
    words, _ = screen(dispatch_local(customer, uploaded=image()))
    assert UX['en']['cv_photo_attached'] in words and UX['en']['cv_photo_hint'] not in words, words
    asset = FileAsset.objects.get(account=customer, name='me.jpg')
    assert state(customer) == ('ai_input', {'feature_id': CV, 'portrait_asset_id': str(asset.id)})
    assert BotInputReceipt.objects.filter(account=customer, asset=asset).count() == 1
    assert not file_task_waiting(customer), 'a photo for a CV is no file task'

    words, _ = screen(dispatch_local(customer, text=BRIEF))
    assert '📷 Photo: attached' in words, words
    options = latest(customer, CV)['options']
    assert options['portrait_asset_id'] == str(asset.id) and options['portrait_sha256'] == asset.sha256
    # Pinned by the draft the quote pins, not as an input file whose expiry would fail the quote.
    assert str(asset.id) not in Quote.objects.filter(account=customer, feature_id=CV).latest('created_at').input_ids
    # The menu offers no images-to-PDF task to continue.
    assert UX['en']['continue_task'] not in screen(dispatch_local(customer, text='/start'))[1]


def test_a_photo_sent_while_the_name_is_asked_for_waits_with_what_was_written(customer, model):
    ask(customer)
    dispatch_local(customer, text=NAMELESS)
    words, _ = screen(dispatch_local(customer, uploaded=image()))
    assert UX['en']['cv_photo_attached'] in words and UX['en']['cv_name_question'] in words, words
    asset = FileAsset.objects.get(account=customer, name='me.jpg')
    assert state(customer) == ('ai_input', {'feature_id': CV, 'brief': [NAMELESS], 'portrait_asset_id': str(asset.id),
                                            'ask': 'name'})
    words, _ = screen(dispatch_local(customer, text='Dilnoza Karimova'))
    assert '📷 Photo: attached' in words and latest(customer, CV)['options']['portrait_asset_id'] == str(asset.id)


def test_a_photo_and_its_caption_are_one_message(customer, model):
    ask(customer)
    words, _ = screen(dispatch_local(customer, uploaded=image(), caption=BRIEF))
    assert '📄 Dilnoza Karimova' in words and '📷 Photo: attached' in words, words
    asset = FileAsset.objects.get(account=customer, name='me.jpg')
    data = latest(customer, CV)
    assert data['prompt'] == BRIEF and data['options']['portrait_asset_id'] == str(asset.id)


def test_a_photo_sent_on_the_review_goes_on_that_cv(customer, model):
    describe(customer, BRIEF, service=SERVICE)
    draft = cv(customer)
    result = dispatch_local(customer, uploaded=image())
    words, shown = screen(result)
    asset = FileAsset.objects.get(account=customer, name='me.jpg')
    assert '📷 Photo: attached' in words and shown[0] == '✨ Generate', words
    assert cv(customer).id == draft.id, 'the same CV, priced again'
    assert latest(customer, CV)['options']['portrait_asset_id'] == str(asset.id)
    # The new review's Generate pays for the CV with its photo.
    generate = result['messages'][-1]['buttons'][0][0]
    quote = Quote.objects.get(pk=BotCallback.objects.get(pk=generate['callback_data']).payload['quote_id'])
    assert quote.parameters['generation_draft_id'] == str(draft.id)
    assert quote.parameters['draft_version'] == cv(customer).version
    assert not file_task_waiting(customer)
    assert state(customer) == ('cv_review', {'draft_id': str(draft.id)})
    # Once the chat has moved on, a photo is a file task again.
    dispatch_local(customer, text='/start')
    dispatch_local(customer, uploaded=image('scan.jpg'))
    assert file_task_waiting(customer)


def test_an_image_too_large_for_a_cv_is_said_at_once(customer, model):
    ask(customer)
    words, _ = screen(dispatch_local(customer, uploaded=image('big.png', 'PNG', (3000, 2400))))
    assert words.startswith(UX['en']['cv_photo_rejected']) and UX['en']['cv_ask'] in words, words
    assert state(customer) == ('ai_input', {'feature_id': CV})
    words, _ = screen(dispatch_local(customer, text=BRIEF))
    assert '📷 Photo: none' in words, 'the description is not refused for it'


def test_a_pdf_sent_for_a_cv_is_not_read(customer, model):
    ask(customer)
    words, _ = screen(dispatch_local(customer, uploaded=SimpleUploadedFile('old-cv.pdf', pdf(), 'application/pdf')))
    assert words.startswith(UX['en']['cv_photo_only']) and UX['en']['cv_ask'] in words, words
    assert not FileAsset.objects.filter(account=customer).exists() and not file_task_waiting(customer)
    assert state(customer) == ('ai_input', {'feature_id': CV})


def test_the_same_photo_delivered_twice_is_one_photo(customer, model, monkeypatch):
    ask(customer)
    # Telegram sends the same update again: the same message id.
    monkeypatch.setattr('telegram.local.secrets.randbelow', lambda limit: 41)
    dispatch_local(customer, uploaded=image())
    words, _ = screen(dispatch_local(customer, uploaded=image()))
    assert UX['en']['cv_photo_attached'] in words, words
    assert FileAsset.objects.filter(account=customer).count() == 1 and BotInputReceipt.objects.count() == 1
    assert not file_task_waiting(customer)


def test_writing_the_description_again_keeps_the_photo(customer, model):
    ask(customer)
    dispatch_local(customer, uploaded=image())
    review = dispatch_local(customer, text=BRIEF)
    asset = FileAsset.objects.get(account=customer, name='me.jpg')
    words, _ = screen(tap(customer, review, 'Change the description'))
    assert UX['en']['cv_photo_attached'] in words, words
    assert state(customer) == ('ai_input', {'feature_id': CV, 'portrait_asset_id': str(asset.id)})


# --- The setup screen ------------------------------------------------------------------------------

def test_the_template_picked_on_the_setup_screen_redraws_the_review(customer, model):
    from tests.test_platform import login_client
    describe(customer, BRIEF, service=SERVICE)
    draft = cv(customer)
    client = login_client(customer)
    response = client.post(f'/api/v1/generation/drafts/{draft.id}/setup', data=json.dumps({'cv_template': 'lab'}),
                           content_type='application/json')
    assert response.status_code == 200, response.content
    result = response.json()
    assert latest(customer, CV)['options']['template_style']['cv_template'] == 'lab'
    # The review in the chat is the new one, edited in place, and pays for the new quote.
    shown = BotConversation.objects.get(telegram_user_id=customer.telegram_user_id).review
    message = LocalBotMessage.objects.get(account=customer, direction='outbound', telegram_message_id=shown['message_id'])
    assert 'Template: Lab' in message.text and 'Pages: 1–2' in message.text, message.text
    generate = [button for row in message.buttons for button in row if button['label'] == '✨ Generate']
    assert BotCallback.objects.get(token=generate[0]['callback_data']).payload['quote_id'] == result['quote']['id']
    # A page count is not a CV's to choose.
    response = client.post(f'/api/v1/generation/drafts/{draft.id}/setup', data=json.dumps({'pages': 3}),
                           content_type='application/json')
    assert response.status_code == 400


# --- Made, sent, changed ------------------------------------------------------------------------------

@pytest.fixture
def delivered(customer):
    """A CV made without a model and sent to the chat, with its Make changes button."""
    save_config('ai', {'mode': 'local_fixture'})
    return tap(customer, describe(customer, BRIEF, service=SERVICE), 'Generate')


def test_generate_sends_the_cv_named_after_the_person(customer, delivered):
    job = Job.objects.get(account=customer, feature_id=CV)
    assert job.status == 'succeeded', job.error_code
    asset = job.artifacts.get().file
    assert asset.name == 'Dilnoza Karimova CV.pdf' and asset.page_count in (1, 2)
    assert LocalBotMessage.objects.filter(account=customer, direction='outbound', asset=asset).exists()
    assert '✏️ Make changes' in labels(delivered), labels(delivered)
    assert state(customer) == ('', {}), 'the review is the job now: a photo sent next is a file task'


def test_a_cv_asked_for_as_a_pdf_is_sent_again(customer, delivered):
    words, _ = screen(tap(customer, delivered, 'Make changes'))
    assert UX['en']['cv_revise_examples'] in words and 'pages' not in words.split('<code>')[1], words
    asset = Job.objects.get(account=customer, feature_id=CV).artifacts.get().file
    drafts = GenerationDraft.objects.filter(account=customer).count()
    result = dispatch_local(customer, text='pdf shaklida yubor')
    assert GenerationDraft.objects.filter(account=customer).count() == drafts, 'no AI edit is made'
    assert LocalBotMessage.objects.filter(account=customer, direction='outbound', asset=asset).count() == 2
    assert any('already a PDF file' in message['text'] for message in result['messages'])


def test_a_change_to_a_cv_is_reviewed_without_the_new_cv_controls(customer, delivered):
    tap(customer, delivered, 'Make changes')
    words, shown = screen(dispatch_local(customer, text='Add IELTS 7.5 (2023) to the certificates'))
    assert '✏️ Add IELTS 7.5 (2023) to the certificates' in words and 'Pages: 1–2' in words, words
    assert '➖' not in shown and '➕' not in shown and '🎨 CV template' not in shown, shown
    assert not FLAGS & {label.replace('✅ ', '') for label in shown} and 'Template:' not in words
    assert '📷 Photo: none' in words and 'send it here' not in words
    assert shown[0] == '✨ Generate' and '✏️ Make changes' in shown, shown
    assert state(customer) == ('', {}), 'a change takes no photo sent on its review'


def test_a_cv_asked_for_as_slides_is_told_a_change_does_not_convert(customer, delivered):
    tap(customer, delivered, 'Make changes')
    result = dispatch_local(customer, text='Slayd qilib bering')
    assert any(UX['en']['ai_format_only'] in message['text'] for message in result['messages'])


# --- A CV the AI could not finish ------------------------------------------------------------------

@pytest.mark.parametrize('locale', LOCALES)
def test_a_failed_cv_says_what_a_cv_needs(locale):
    from apps.core.models import Job as Jobs
    from tests.test_bot_prompt_feedback import sent
    from tests.test_bot_terminal_notifications import terminal_job
    _, job = terminal_job('failed', locale=locale)
    Jobs.objects.filter(pk=job.pk).update(feature_id=CV, parameters={}, error_code='provider_failed')
    words, rows = sent(job)
    assert words.splitlines()[1] == TOOL_NAMES[CV][locale]
    assert words.endswith('\n\n' + UX[locale]['cv_failed_advice']) and UX[locale]['ai_failed_advice'] not in words
    assert rows[:2] == [[('ai_retry', UX[locale]['retry_task'])], [('ai_tool', UX[locale]['ai_change_topic'])]]


def test_the_cv_words_say_the_same_in_every_language():
    import re
    for key in [key for key in MESSAGES if key.startswith('cv_')]:
        en, uz, ru = MESSAGES[key]
        assert len({frozenset(re.findall(r'{\w+}', value)) for value in (en, uz, ru)}) == 1, key
        assert not re.search('[а-яёўқғҳ]', uz, re.IGNORECASE), f'{key}: Uzbek is written in Latin'
        assert "'" not in uz, f'{key}: Uzbek uses ‘ and ʼ, not a typewriter apostrophe'
        assert '<' not in en + uz + ru and '&' not in en + uz + ru, f'{key} is shown as HTML'
    for row in PROMPT_EXAMPLES[CV]:
        assert not re.search('[а-яё]', row[1], re.IGNORECASE) and "'" not in row[1]


# --- What a CV is not made of ----------------------------------------------------------------------

@pytest.mark.parametrize('locale', LOCALES)
def test_a_greeting_asks_for_the_details_not_the_name(customer, model, locale):
    customer.locale = locale
    customer.save(update_fields=['locale'])
    BotConversation.objects.filter(pk=customer.telegram_user_id).update(locale=locale)
    dispatch_local(customer, text='/cv')
    words, _ = screen(dispatch_local(customer, text={'en': 'Hello', 'uz': 'Assalomu alaykum',
                                                     'ru': 'Здравствуйте'}[locale]))
    assert UX[locale]['cv_details_question'] in words and UX[locale]['cv_name_question'] not in words, words
    assert not GenerationDraft.objects.filter(account=customer).exists()


def test_a_name_alone_is_asked_for_the_rest_and_then_makes_the_cv(customer, model):
    ask(customer)
    words, _ = screen(dispatch_local(customer, text='Assalomu alaykum'))
    assert UX['en']['cv_details_question'] in words, words
    # A name says who, not what to put on the CV: the details are asked for again.
    words, _ = screen(dispatch_local(customer, text='Dilnoza Karimova'))
    assert UX['en']['cv_details_question'] in words and '📄' not in words, words
    assert state(customer) == ('ai_input', {'feature_id': CV, 'brief': ['Assalomu alaykum', 'Dilnoza Karimova'],
                                            'ask': 'details'})
    words, _ = screen(dispatch_local(customer, text=NAMELESS))
    assert '📄 Dilnoza Karimova' in words and 'Pages: 1–2' in words, words
    assert latest(customer, CV)['prompt'] == f'{NAMELESS}\nAssalomu alaykum\nDilnoza Karimova'


def test_a_first_message_that_is_only_a_name_asks_for_the_details(customer, model):
    ask(customer)
    words, _ = screen(dispatch_local(customer, text='Dilnoza Karimova'))
    assert UX['en']['cv_details_question'] in words and not GenerationDraft.objects.filter(account=customer).exists()
    # Sending the same again, however often, never makes a CV of a name alone.
    for _ in range(3):
        words, _ = screen(dispatch_local(customer, text='dilnoza karimova'))
        assert UX['en']['cv_details_question'] in words, words
    assert not GenerationDraft.objects.filter(account=customer).exists()


def test_only_an_answer_that_looks_like_a_name_is_taken_as_one(customer, model):
    ask(customer)
    dispatch_local(customer, text=NAMELESS)
    dispatch_local(customer, text='I also have a driving licence, category B.')
    # Answered twice, but with no name: asked again, never made with "And I can work weekends." as its title.
    words, _ = screen(dispatch_local(customer, text='And I can work weekends.'))
    assert UX['en']['cv_name_question'] in words and not GenerationDraft.objects.filter(account=customer).exists()
    words, _ = screen(dispatch_local(customer, text='Dilnoza Karimova'))
    assert '📄 Dilnoza Karimova' in words, words


def test_the_nameless_description_sent_again_is_asked_for_the_name_again(customer, model):
    ask(customer)
    dispatch_local(customer, text=NAMELESS)
    words, _ = screen(dispatch_local(customer, text=NAMELESS))
    assert UX['en']['cv_name_question'] in words and UX['en']['cv_name_again'] in words, words
    assert not GenerationDraft.objects.filter(account=customer).exists()


def test_the_examples_lead_back_to_the_open_question_with_what_was_written(customer, model):
    ask(customer)
    question = dispatch_local(customer, text=NAMELESS)
    examples = tap(customer, question, UX['en']['ai_examples'])
    words, _ = screen(tap(customer, examples, SERVICE))
    assert UX['en']['cv_name_question'] in words and '📝 Noted: “Data analyst in Tashkent.' in words, words
    assert state(customer)[1]['brief'] == [NAMELESS]
    dispatch_local(customer, text='Dilnoza Karimova')
    assert latest(customer, CV)['prompt'] == f'Dilnoza Karimova\n{NAMELESS}'


# --- Sent together ----------------------------------------------------------------------------------

def feed_together(account, items, gap=0.01):
    """Messages fed to one dispatcher side by side, `gap` seconds apart, as polling (handle_as_tasks) feeds them.

    Each item is text, or (upload, caption, album id) for a file.
    """
    import asyncio
    import secrets
    from datetime import datetime, timezone as tz
    from aiogram import Bot
    from aiogram.types import Chat, Document, Message, Update, User
    from telegram.local import LocalTelegramSession
    session = LocalTelegramSession(account)
    user = User(id=account.telegram_user_id, is_bot=False, first_name='Sample', language_code=account.locale)
    updates = []
    base = secrets.randbelow(1_000_000) + 1000
    for index, item in enumerate(items):
        data = {'message_id': base + index, 'date': datetime.now(tz.utc),
                'chat': Chat(id=account.telegram_user_id, type='private'), 'from_user': user}
        if isinstance(item, str):
            data['text'] = item
        else:
            upload, caption, group = item
            file_id = secrets.token_hex(12)
            session.files[file_id] = upload.read()
            data['document'] = Document(file_id=file_id, file_unique_id=file_id, file_name=upload.name,
                                        file_size=len(session.files[file_id]))
            data.update({key: value for key, value in (('caption', caption), ('media_group_id', group)) if value})
        LocalBotMessage.objects.create(account=account, direction='inbound', text='sample',
                                       telegram_message_id=base + index)
        updates.append(Update(update_id=base + index, message=Message(**data)))

    async def run():
        from telegram.bot import build_dispatcher
        bot = Bot('123456:LOCAL_SIMULATOR_NO_NETWORK', session=session)
        dispatcher = build_dispatcher()

        async def one(update, delay):
            await asyncio.sleep(delay)
            await dispatcher.feed_update(bot, update)
        try:
            await asyncio.gather(*(one(update, gap * number) for number, update in enumerate(updates)))
        finally:
            await bot.session.close()
    async_to_sync(run)()


@pytest.fixture
def slow_telegram(monkeypatch):
    """Telegram over a network: each call and each file download takes a while."""
    import asyncio
    from telegram.local import LocalTelegramSession
    stream, request = LocalTelegramSession.stream_content, LocalTelegramSession.make_request

    def set_latency(api, download):
        async def slow_stream(self, url, **kwargs):
            await asyncio.sleep(download)
            async for chunk in stream(self, url, **kwargs):
                yield chunk

        async def slow_request(self, bot, method, timeout=None):
            await asyncio.sleep(api)
            return await request(self, bot, method, timeout)
        monkeypatch.setattr(LocalTelegramSession, 'stream_content', slow_stream)
        monkeypatch.setattr(LocalTelegramSession, 'make_request', slow_request)
    return set_latency


@pytest.mark.parametrize('api,download,gap', [(0, 0, 0.01), (0.15, 0.3, 0.01), (0.15, 0.3, 0.3), (0.25, 0.1, 0.05)])
@pytest.mark.parametrize('photo_first', [True, False])
def test_a_photo_and_a_description_sent_together_make_one_cv_with_the_photo(customer, model, slow_telegram,
                                                                              photo_first, api, download, gap,
                                                                              monkeypatch):
    monkeypatch.setattr('telegram.bot.ALBUM_SETTLE', 0)
    ask(customer)
    slow_telegram(api, download)
    items = [(image(), '', ''), BRIEF]
    feed_together(customer, items if photo_first else items[::-1], gap)
    drafts = list(GenerationDraft.objects.filter(account=customer))
    asset = FileAsset.objects.get(account=customer, name='me.jpg')
    assert len(drafts) == 1 and latest(customer, CV)['options'].get('portrait_asset_id') == str(asset.id)
    assert state(customer) == ('cv_review', {'draft_id': str(drafts[0].id)})
    assert not file_task_waiting(customer)
    newest = LocalBotMessage.objects.filter(account=customer, direction='outbound').order_by('-created_at').first()
    assert '📄 Dilnoza Karimova' in newest.text and '📷 Photo: attached' in newest.text, newest.text


def test_an_albums_caption_is_the_description_when_its_photos_arrive_together(customer, model, monkeypatch):
    monkeypatch.setattr('telegram.bot.ALBUM_SETTLE', 0.2)
    ask(customer)
    feed_together(customer, [(image('a.jpg'), BRIEF, 'album-1'), (image('b.jpg'), '', 'album-1')], 0.02)
    data = latest(customer, CV)
    assert data['prompt'] == BRIEF and data['options']['portrait_asset_id'] == str(
        FileAsset.objects.get(account=customer, name='b.jpg').id)


def test_a_description_telegram_split_in_two_is_one_cv(customer, model):
    more = 'Projects: a sales dashboard for 40 stores (2023), a churn model for Sample Bank (2021).'
    describe(customer, BRIEF, service=SERVICE)
    draft = cv(customer)
    words, shown = screen(dispatch_local(customer, text=more))
    assert words.startswith(UX['en']['cv_description_added']) and '📄 Dilnoza Karimova' in words, words
    assert shown[0] == '✨ Generate' and cv(customer).id == draft.id
    assert latest(customer, CV)['prompt'] == f'{BRIEF}\n{more}'
    assert state(customer) == ('cv_review', {'draft_id': str(draft.id)})
    # Much later, a message on the review is not taken into the CV, and the customer is told how to change it.
    from datetime import timedelta
    from django.utils import timezone
    BotConversation.objects.filter(pk=customer.telegram_user_id).update(updated_at=timezone.now() - timedelta(minutes=5))
    words, _ = screen(dispatch_local(customer, text='Is it ready?'))
    assert words.startswith(UX['en']['cv_text_not_added']) and '📄 Dilnoza Karimova' in words, words
    assert latest(customer, CV)['prompt'] == f'{BRIEF}\n{more}'


def test_the_two_halves_of_a_description_sent_together_are_one_cv(customer, model, slow_telegram):
    more = 'Projects: a sales dashboard for 40 stores (2023).'
    ask(customer)
    slow_telegram(0.15, 0)
    feed_together(customer, [BRIEF, more], 0.01)
    assert GenerationDraft.objects.filter(account=customer).count() == 1
    assert latest(customer, CV)['prompt'] == f'{BRIEF}\n{more}'


def test_a_caption_sent_with_a_photo_on_the_review_is_said_not_to_be_added(customer, model):
    describe(customer, BRIEF, service=SERVICE)
    words, _ = screen(dispatch_local(customer, uploaded=image(), caption='Also add: I speak Korean (TOPIK 3).'))
    assert words.startswith(UX['en']['cv_caption_not_added']) and '📷 Photo: attached' in words, words
    assert 'Korean' not in latest(customer, CV)['prompt']


def test_a_photo_on_a_template_without_a_place_for_it_is_said_on_the_review(customer, model):
    from tests.test_platform import login_client
    ask(customer)
    dispatch_local(customer, uploaded=image())
    dispatch_local(customer, text=BRIEF)
    draft = cv(customer)
    assert not cv_templates_photo('indigo_band')
    response = login_client(customer).post(f'/api/v1/generation/drafts/{draft.id}/setup',
                                           data=json.dumps({'cv_template': 'indigo_band'}), content_type='application/json')
    assert response.status_code == 200, response.content
    shown = BotConversation.objects.get(telegram_user_id=customer.telegram_user_id).review
    message = LocalBotMessage.objects.get(account=customer, direction='outbound', telegram_message_id=shown['message_id'])
    assert UX['en']['cv_photo_no_slot_line'] in message.text and UX['en']['cv_photo_line'] + '\n' not in message.text


def cv_templates_photo(key):
    from apps.studio.cv.templates import TEMPLATES
    return TEMPLATES[key]['photo']


def test_a_photo_sent_for_a_change_to_a_finished_cv_keeps_the_change_question(customer, delivered):
    tap(customer, delivered, 'Make changes')
    words, _ = screen(dispatch_local(customer, uploaded=image()))
    assert words.startswith(UX['en']['cv_revise_photo']) and UX['en']['cv_revise_examples'] in words, words
    assert state(customer)[0] == 'ai_revise' and not file_task_waiting(customer)
