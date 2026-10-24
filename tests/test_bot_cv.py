"""A CV from the chat: one message about yourself, a photo if you like, a review, a PDF.

The third AI service (`ai.cv`) asks first how the CV is made; these tests
follow the first way, written about yourself (tests/test_bot_cv_sources.py
follows the LinkedIn profile and the old CV). From there it works like the
other two: one message in, a
priced review out, nothing counted until Generate. What differs is what it asks
for and what it shows. It says what a CV needs (a name, a phone or an email, a
job with dates or a school) and what only adds to it, asks for whatever of the
three is missing, all on one screen, and keeps everything already written
while it does. A photo sent before or after the description is the CV's
portrait, kept with the question and never as a file task. The review shows the
template and the photo, not a page count to adjust. Everyone in these tests is
made up (example.com contacts).
"""
import html
import io
import json

import pytest
from asgiref.sync import async_to_sync
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.commerce.models import LocalBotMessage
from apps.core.models import BotCallback, BotConversation, BotDraft, BotInputReceipt, FileAsset, Job, Quote
from apps.studio.cv.content import name_in
from apps.studio.domain import CV
from apps.studio.models import GenerationDraft
from operations.integrations import save_config
from telegram import generation
from telegram.bot import (CV_BRIEF_CHARS, CV_BRIEF_PIECES, CV_SAMPLES, can_add_line, cv_asked, cv_insists, kept_brief,
                          missing_lines, review_screen, sent_back, tells_little)
from telegram.local import dispatch_local
from telegram.ux_copy import LOCALES, MESSAGES, PROMPT_EXAMPLES, TOOL_NAMES, UX
from tests.test_bot_generation import customer, labels, latest, tap  # noqa: F401
from tests.test_cv_content import BRIEF
from tests.test_manual_payments import pdf

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]

SERVICE = 'CV · AI'
FLAGS = {'🇬🇧', '🇺🇿', '🇷🇺'}
# BRIEF without its first line: everything about the person but who they are.
NAMELESS = BRIEF.split('\n', 1)[1]
# The same with a number of the customer's own: BRIEF's is the screens' sample number, so sent after a
# missing screen it is our example sent back (sent_back), not the customer's description.
OWN_NAMELESS = NAMELESS.replace('+998 90 123 45 67', '+998 91 234 56 78')


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
    """The CV service chosen from the menu, written about yourself: its question on screen."""
    return tap(account, tap(account, dispatch_local(account, text='/start'), SERVICE), UX['en']['cv_mode_text'])


def write(account, description):
    """A CV described in one message, as the menu leads to it."""
    ask(account)
    return dispatch_local(account, text=description)


def cv(account):
    return GenerationDraft.objects.filter(account=account, feature_id=CV).latest('created_at')


def speaks(account, locale):
    account.locale = locale
    account.save(update_fields=['locale'])
    BotConversation.objects.filter(pk=account.telegram_user_id).update(locale=locale)


def listed(words, locale='en'):
    """The required facts a question lists as missing, in the order it lists them."""
    copy = UX[locale]
    return [fact for fact in ('name', 'contact', 'background') if f'• {copy["cv_fact_" + fact]} — ' in words]


def asks_for(locale='en'):
    """What the CV question says before anything is written: what it needs, one fact to a line, and what only adds to
    it on one line, all but the photo, which has a line of its own; by the facts' labels."""
    from apps.studio.cv.content import OPTIONAL_FACTS, REQUIRED_FACTS
    copy = UX[locale]
    needs = '\n'.join([copy['cv_required'], *(f'• {copy[f"cv_fact_{fact}"][:1].upper()}{copy[f"cv_fact_{fact}"][1:]}'
                                              for fact in REQUIRED_FACTS)])
    adds = copy['cv_optional'].format(facts=', '.join(copy[f'cv_fact_{fact}'] for fact in OPTIONAL_FACTS
                                                      if fact != 'photo'))
    return f'{copy["cv_ask"]}\n\n{needs}\n\n{adds}'


def example_of(fact, locale='en'):
    """The example a missing screen shows beside a fact: each of its values its own code, 'or' between."""
    copy = UX[locale]
    key = {'name': 'cv_name_sample', 'contact': 'cv_fact_contact_sample', 'background': 'cv_fact_background_sample'}[fact]
    return f' {copy["cv_or"]} '.join(f'<code>{way}</code>' for way in copy[key].split(' — '))


def file_task_waiting(account):
    draft = BotDraft.objects.filter(account=account).first()
    return bool(draft and draft.input_ids)


# --- The service and its question ------------------------------------------------------

def test_the_cv_is_the_third_service_on_the_home_screen(customer):
    rows = dispatch_local(customer, text='/start')['messages'][-1]['buttons']
    assert [row[0]['label'] for row in rows[:3]] == [
        '✨ PDF on a topic · AI', '✨ Slides on a topic · AI', '✨ CV · AI']


def test_cv_opens_the_question_about_you(customer):
    words, shown = screen(tap(customer, dispatch_local(customer, text='/cv'), UX['en']['cv_mode_text']))
    assert words.startswith('<b>✨ CV · AI</b>\n' + UX['en']['cv_ask']), words[:300]
    # What a CV needs, and what only adds to it, are said before anything is written, by the facts' labels.
    assert f'{asks_for()}\n\n<i>{UX["en"]["cv_photo_hint"]}</i>' in words, words[:600]
    assert ('\n✅ Required:\n• Full name\n• Phone or email\n• Work experience (with years) or education\n\n'
            '➕ Optional: the job you want, city, birth date or age, skills, languages, certificates, projects, '
            'LinkedIn or other links\n\n') in words, words[:600]
    # One example, whole CV as it is, in plain type in a quote that opens on a tap: never a wall of <code>.
    assert words.endswith(f'{UX["en"]["cv_example"]}\n<blockquote expandable>{PROMPT_EXAMPLES[CV][0][0]}</blockquote>')
    assert '<code>' not in words and PROMPT_EXAMPLES[CV][1][0] not in words, words
    # No page count is asked for: one page or two is the template's to decide.
    assert 'how many pages' not in words and UX['en']['ai_pages_hint'] not in words
    assert shown == [UX['en']['ai_examples'], UX['en']['ai_back']]
    # Back is the first CV screen, where the other ways to make one are.
    assert actions(customer) == [['ai_examples'], ['cv_mode']]
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
    caught = write(customer, PROMPT_EXAMPLES[CV][1][0])
    assert screen(caught)[0] == UX['en']['cv_example_copied']
    assert not GenerationDraft.objects.filter(account=customer).exists()


# --- One message to a review ----------------------------------------------------------------

def test_one_message_becomes_a_priced_review_with_the_template_and_the_photo(customer, model):
    review = write(customer, BRIEF)
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
    # Its phone and its jobs are there: only the name is listed, with its example, and what is there is said.
    assert listed(words) == ['name'] and '• full name — e.g. <code>Dilnoza Rahimova</code>' in words, words
    assert '✅ Already there: phone or email · work experience (with years) or education' in words, words
    assert UX['en']['cv_name_again'] in words and '📝 Noted: “Data analyst in Tashkent.' in words
    assert UX['en']['cv_missing_again'] not in words
    assert UX['en']['ai_topic_question'] not in words and UX['en']['ai_topic_again'] not in words
    assert actions(customer) == [['ai_examples'], ['home']], 'no other service is offered'
    assert state(customer) == ('ai_input', {'feature_id': CV, 'brief': [long], 'ask': 'missing', 'missing': ['name']})
    assert not GenerationDraft.objects.filter(account=customer).exists()
    assert not Quote.objects.filter(account=customer).exists()

    words, _ = screen(dispatch_local(customer, text='Dilnoza Karimova'))
    assert '📄 Dilnoza Karimova' in words and 'Pages: 1–2' in words, words
    assert latest(customer, CV)['prompt'] == f'Dilnoza Karimova\n{long}', 'the name, then every word written before'


def test_a_name_the_check_cannot_see_is_taken_when_sent_again(customer, model):
    ask(customer)
    dispatch_local(customer, text=NAMELESS)
    assert listed(screen(dispatch_local(customer, text='dilnoza karimova'))[0]) == ['name']
    words, _ = screen(dispatch_local(customer, text='dilnoza karimova'))
    assert '📄 dilnoza karimova' in words and 'Pages: 1–2' in words, words
    # Sent again, it is the CV's title, the customer's own answer; the review says the name was not seen.
    assert latest(customer, CV)['title'] == 'dilnoza karimova' and latest(customer, CV)['prompt'] == f'dilnoza karimova\n{NAMELESS}'
    assert '💡 You can still add: full name ·' in words, words


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
    assert UX['en']['cv_photo_attached'] in words and listed(words) == ['name'], words
    asset = FileAsset.objects.get(account=customer, name='me.jpg')
    assert state(customer) == ('ai_input', {'feature_id': CV, 'brief': [NAMELESS], 'portrait_asset_id': str(asset.id),
                                            'ask': 'missing', 'missing': ['name']})
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
    write(customer, BRIEF)
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
    write(customer, BRIEF)
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
    return tap(customer, write(customer, BRIEF), 'Generate')


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
        assert not re.search('[а-яё]', en, re.IGNORECASE), f'{key}: English has no Russian in it'
        assert "'" not in uz, f'{key}: Uzbek uses ‘ and ʼ, not a typewriter apostrophe'
        assert '<' not in en + uz + ru and '&' not in en + uz + ru, f'{key} is shown as HTML'
    for row in PROMPT_EXAMPLES[CV]:
        assert not re.search('[а-яё]', row[1], re.IGNORECASE) and "'" not in row[1]


# --- What a CV is not made of ----------------------------------------------------------------------

@pytest.mark.parametrize('locale', LOCALES)
def test_a_greeting_lists_all_three_required_facts_with_an_example_each(customer, model, locale):
    speaks(customer, locale)
    copy = UX[locale]
    tap(customer, dispatch_local(customer, text='/cv'), copy['cv_mode_text'])
    words, _ = screen(dispatch_local(customer, text={'en': 'Hello', 'uz': 'Assalomu alaykum',
                                                     'ru': 'Здравствуйте'}[locale]))
    assert listed(words, locale) == ['name', 'contact', 'background'], words
    assert copy['cv_missing_title'] in words and copy['cv_got'].split('{')[0] not in words
    for fact in ('name', 'contact', 'background'):
        assert copy['cv_missing_item'].format(fact=copy[f'cv_fact_{fact}'], example=example_of(fact, locale)) in words
    # A greeting tells nothing: no name sent again could make a CV of it, so the screen asks for the work or studies.
    assert copy['cv_missing_send'] in words and words.endswith(copy['cv_missing_more']), words
    assert copy['cv_name_again'] not in words and copy['cv_missing_again'] not in words
    assert state(customer)[1]['missing'] == ['name', 'contact', 'background']
    assert not GenerationDraft.objects.filter(account=customer).exists()


def test_a_name_alone_is_asked_for_the_rest_and_then_makes_the_cv(customer, model):
    ask(customer)
    words, _ = screen(dispatch_local(customer, text='Assalomu alaykum'))
    assert listed(words) == ['name', 'contact', 'background'], words
    # A name says who, not how to reach them or what to put on the CV: both are asked for.
    words, _ = screen(dispatch_local(customer, text='Dilnoza Karimova'))
    assert listed(words) == ['contact', 'background'] and '📄' not in words, words
    # A greeting and a name sent again would make no CV: the screen asks for more, not for the same again.
    assert UX['en']['cv_got'].format(facts='full name') in words and words.endswith(UX['en']['cv_missing_more']), words
    assert UX['en']['cv_missing_again'] not in words
    assert state(customer) == ('ai_input', {'feature_id': CV, 'brief': ['Assalomu alaykum', 'Dilnoza Karimova'],
                                            'ask': 'missing', 'missing': ['contact', 'background']})
    words, _ = screen(dispatch_local(customer, text=OWN_NAMELESS))
    assert '📄 Dilnoza Karimova' in words and 'Pages: 1–2' in words, words
    assert latest(customer, CV)['prompt'] == f'{OWN_NAMELESS}\nAssalomu alaykum\nDilnoza Karimova'


def test_a_first_message_that_is_only_a_name_asks_for_the_rest(customer, model):
    ask(customer)
    words, _ = screen(dispatch_local(customer, text='Dilnoza Karimova'))
    assert listed(words) == ['contact', 'background'] and not GenerationDraft.objects.filter(account=customer).exists()
    # Sending the same again, however often, never makes a CV of a name alone.
    for _ in range(3):
        words, _ = screen(dispatch_local(customer, text='dilnoza karimova'))
        assert listed(words) == ['contact', 'background'], words
    assert not GenerationDraft.objects.filter(account=customer).exists()


def test_a_greeting_sent_again_never_makes_a_cv(customer, model):
    ask(customer)
    for _ in range(3):
        words, _ = screen(dispatch_local(customer, text='Hello'))
        assert listed(words) == ['name', 'contact', 'background'], words
    assert not GenerationDraft.objects.filter(account=customer).exists()
    assert not Quote.objects.filter(account=customer).exists()
    assert state(customer)[1]['brief'] == ['Hello'], 'the same words are kept once'


@pytest.mark.parametrize('locale,greeting', [
    ('en', 'Hello, my name is Dilnoza Karimova, please make me a CV'),
    ('uz', 'Assalomu alaykum, men Dilnoza Karimova, menga rezyume kerak'),
    ('ru', 'Здравствуйте, меня зовут Дильноза Каримова, мне нужно резюме')], ids=LOCALES)
def test_a_greeting_with_a_name_sent_again_never_makes_a_cv(customer, model, locale, greeting):
    # Sent again, it is still a greeting and a name: read once, it says nothing else about the person.
    speaks(customer, locale)
    tap(customer, dispatch_local(customer, text='/cv'), UX[locale]['cv_mode_text'])
    for _ in range(3):
        words, _ = screen(dispatch_local(customer, text=greeting))
        assert listed(words, locale) == ['contact', 'background'], words
    assert not GenerationDraft.objects.filter(account=customer).exists()
    assert not Quote.objects.filter(account=customer).exists()
    assert state(customer)[1]['brief'] == [greeting], 'the same words are kept once'


@pytest.mark.parametrize('locale,said', [
    ('en', 'Dilnoza Karimova, +998 91 234 56 78'),
    ('uz', 'Dilnoza Karimova, dilnoza.k@example.org'),
    ('ru', 'Дильноза Каримова, +998 91 234 56 78, dilnoza.k@example.org')], ids=LOCALES)
def test_a_name_with_a_phone_or_an_email_sent_again_never_makes_a_cv(customer, model, locale, said):
    # Who the person is and how to reach them, not what they did: sent again, however often, it is still no CV,
    # and the screen never says that sending it again would make one.
    speaks(customer, locale)
    copy = UX[locale]
    tap(customer, dispatch_local(customer, text='/cv'), copy['cv_mode_text'])
    for _ in range(3):
        words, _ = screen(dispatch_local(customer, text=said))
        assert not GenerationDraft.objects.filter(account=customer).exists(), words
        assert listed(words, locale) == ['background'], words
    assert not Quote.objects.filter(account=customer).exists()
    assert state(customer)[1]['brief'] == [said], 'the same words are kept once'
    assert words.endswith(copy['cv_missing_more']), words
    assert copy['cv_missing_again'] not in words and copy['cv_name_again'] not in words


@pytest.mark.parametrize('locale,bio', [
    ('en', 'Dilnoza Karimova, cashier at Korzinka'),
    ('uz', 'Dilnoza Karimova, Korzinkada kassirman'),
    ('ru', 'Дильноза Каримова, кассир в Корзинке')], ids=LOCALES)
def test_the_same_message_again_is_offered_only_where_it_can_make_the_cv(customer, model, locale, bio):
    # A name and a job with no years: sent again it says no more, so the screen asks for more about the work or
    # studies instead of saying to send it again, however often it is sent.
    speaks(customer, locale)
    copy = UX[locale]
    tap(customer, dispatch_local(customer, text='/cv'), copy['cv_mode_text'])
    for _ in range(3):
        words, _ = screen(dispatch_local(customer, text=bio))
        assert listed(words, locale) == ['contact', 'background'], words
        assert words.endswith(f'{copy["cv_missing_send"]}\n{copy["cv_missing_more"]}'), words
        for key in ('cv_missing_again', 'cv_missing_again_contact', 'cv_name_again'):
            assert copy[key] not in words, key
    assert not GenerationDraft.objects.filter(account=customer).exists()


def test_a_short_description_the_check_missed_is_offered_and_made_when_sent_again(customer, model):
    # Twelve words and more about the work, with no years the check could read: the same again makes the CV.
    bio = ('Dilnoza Karimova, +998 91 234 56 78. '
           'I sell phones and accessories at a stall in the Chorsu bazaar and keep its books')
    words, _ = screen(write(customer, bio))
    assert listed(words) == ['background'] and words.endswith(UX['en']['cv_missing_again']), words
    words, shown = screen(dispatch_local(customer, text=bio))
    assert '📄 Dilnoza Karimova' in words and shown[0] == '✨ Generate', words
    assert latest(customer, CV)['prompt'] == bio and generation.facts_of(cv(customer))['missing'] == ['background']


def test_what_is_written_tells_little_with_its_phones_and_emails_aside():
    # A name, a phone and an email say who and how to reach, not what the person did.
    for written in (['Dilnoza Karimova, +998 91 234 56 78'], ['Dilnoza Karimova +998 90 123 45 67'],
                    ['Dilnoza Karimova', 'dilnoza.k@example.org', '+998 91 234 56 78'],
                    ['Дильноза Каримова, тел. 90 123 45 67'], ['Hello'], [], ['', 'Dilnoza Karimova, +998 93 123 1999']):
        assert tells_little(written), written
    # A year still says something, and so do a dozen words; a period is no phone.
    for written in (['Dilnoza Karimova, +998 91 234 56 78, 2019'], ['Kassir, Korzinka, 2019-2022, +998 91 234 56 78'],
                    ['Dilnoza Karimova', 'I sell phones and accessories at a stall in the Chorsu bazaar, keep its books']):
        assert not tells_little(written), written


def test_words_sent_again_are_taken_by_one_rule_in_both_ways_of_making_a_cv():
    sentence = 'I keep the books for a family bakery and sell bread at the counter on weekends'
    # Never words that are not the same as words kept.
    assert not cv_insists(False, ['contact'], ['Dilnoza Karimova'], 'Dilnoza Karimova')
    # Only the contact missing: anything sent again.
    assert cv_insists(True, ['contact'], ['Hello'], 'Hello')
    # The name missing: only a name-like answer; a sentence that is clearly no name never is.
    assert cv_insists(True, ['name'], [sentence, 'dilnoza karimova'], 'dilnoza karimova')
    assert not cv_insists(True, ['name'], [sentence, 'And I can work weekends.'], 'And I can work weekends.')
    # The work or studies missing: only what tells more than a name, a phone and an email, counted once.
    reached = 'Dilnoza Karimova, +998 91 234 56 78'
    assert not cv_insists(True, ['background'], [reached], reached)
    assert not cv_insists(True, ['name', 'contact', 'background'], ['I need a CV please'], 'I need a CV please')
    described = f'Dilnoza Karimova. {sentence}'
    assert cv_insists(True, ['contact', 'background'], [described], described)
    # The screen asks whether sending again could make the CV at all: with the name missing, a name-like answer.
    assert cv_insists(True, ['name', 'background'], [sentence])
    assert not cv_insists(True, ['name', 'background'], ['Hello'])


def test_the_sample_guard_and_the_rule_for_words_sent_again_read_in_time_that_grows_with_the_text():
    import time
    for text in ('Men ' * 32_500, '1 ' * 65_000, '+998 ' * 26_000, 'a@b.co ' * 18_500, '2019 ' * 26_000, '-' * 130_000,
                 ' ' * 130_000, 'dilnoza@example.co' * 7_200, 'Sales manager, Bahor Foods, 2021' * 4_000):
        started = time.monotonic()
        sent_back(text)
        tells_little([text])
        cv_insists(True, ['name', 'contact', 'background'], [text], text)
        assert time.monotonic() - started < 1.5, text[:20]


@pytest.mark.parametrize('locale,bio', [
    ('en', 'Dilnoza Karimova, Tashkent State University student'),
    ('uz', 'Dilnoza Karimova, Toshkent davlat universiteti talabasi'),
    ('ru', 'Дильноза Каримова, студентка Ташкентского университета')], ids=LOCALES)
def test_a_short_bio_with_a_school_sent_again_is_made_without_its_contact(customer, model, locale, bio):
    speaks(customer, locale)
    copy = UX[locale]
    tap(customer, dispatch_local(customer, text='/cv'), copy['cv_mode_text'])
    words, _ = screen(dispatch_local(customer, text=bio))
    # A name and a school, nothing to reach the person by: the screen says how to go on without it.
    assert listed(words, locale) == ['contact'] and words.endswith(copy['cv_missing_again_contact']), words
    assert copy['cv_missing_again'] not in words and copy['cv_name_again'] not in words
    words, shown = screen(dispatch_local(customer, text=bio))
    assert shown[0] == copy['ai_generate'] and copy['cv_missing_title'] not in words, words
    assert latest(customer, CV)['prompt'] == bio and generation.facts_of(cv(customer))['missing'] == ['contact']
    # The review says what it still lacks, first.
    assert copy['cv_can_add'].split('{')[0] + copy['cv_fact_contact'] in words, words
    assert GenerationDraft.objects.filter(account=customer).count() == 1


def test_no_phone_or_email_said_twice_makes_the_cv_without_one(customer, model):
    words, _ = screen(write(customer, 'Dilnoza Karimova, Tashkent State University student'))
    assert listed(words) == ['contact'], words
    words, _ = screen(dispatch_local(customer, text='I have no phone'))
    assert listed(words) == ['contact'] and not GenerationDraft.objects.filter(account=customer).exists(), words
    words, shown = screen(dispatch_local(customer, text='I have no phone'))
    assert '📄 Dilnoza Karimova' in words and shown[0] == '✨ Generate', words
    assert generation.facts_of(cv(customer))['missing'] == ['contact']


def test_a_sample_sent_back_is_answered_as_ours_and_never_kept(customer, model):
    ask(customer)
    dispatch_local(customer, text='Hello')
    # The sample number, tapped and sent as it is: the same screen, saying it is our example; nothing kept or made.
    words, _ = screen(dispatch_local(customer, text='+998 90 123 45 67'))
    assert UX['en']['cv_example_copied'] in words and listed(words) == ['name', 'contact', 'background'], words
    assert state(customer)[1]['brief'] == ['Hello'] and state(customer)[1]['missing'] == ['name', 'contact', 'background']
    # Several at once, one a line, one of them another language's: the same.
    words, _ = screen(dispatch_local(customer, text='Dilnoza Rahimova\n dilnoza@EXAMPLE.com \n'
                                                    'Менеджер по продажам, Bahor Foods, 2021–2024'))
    assert UX['en']['cv_example_copied'] in words and listed(words) == ['name', 'contact', 'background'], words
    assert state(customer)[1]['brief'] == ['Hello']
    # The customer's own details are theirs, and kept.
    words, _ = screen(dispatch_local(customer, text=f'Dilnoza Karimova\n{PHONE}'))
    assert listed(words) == ['background'] and UX['en']['cv_example_copied'] not in words, words
    for sample in ('Sales manager, Bahor Foods, 2021–2024', 'TDIU, marketing yo‘nalishi, 2018-yilda bitirganman'):
        words, _ = screen(dispatch_local(customer, text=sample))
        assert UX['en']['cv_example_copied'] in words and listed(words) == ['background'], words
    assert state(customer)[1]['brief'] == ['Hello', f'Dilnoza Karimova\n{PHONE}']
    assert not GenerationDraft.objects.filter(account=customer).exists() and not Quote.objects.filter(account=customer).exists()
    # Their own job makes the CV.
    words, _ = screen(dispatch_local(customer, text='Sales manager, Example Retail, 2021–2024'))
    assert '📄 Dilnoza Karimova' in words and UX['en']['cv_example_copied'] not in words, words


def test_a_name_like_the_sample_sent_again_at_once_is_the_customers_own(customer, model):
    ask(customer)
    dispatch_local(customer, text=NAMELESS)
    words, _ = screen(dispatch_local(customer, text='Dilnoza Rahimova'))
    assert UX['en']['cv_example_copied'] in words and listed(words) == ['name'], words
    assert state(customer)[1]['brief'] == [NAMELESS]
    # Someone whose name it is sends it again: it is theirs.
    words, _ = screen(dispatch_local(customer, text='Dilnoza Rahimova'))
    assert '📄 Dilnoza Rahimova' in words and UX['en']['cv_example_copied'] not in words, words
    assert latest(customer, CV)['prompt'] == f'Dilnoza Rahimova\n{NAMELESS}'


def test_a_lower_case_name_like_the_sample_is_taken_once_it_is_kept(customer, model):
    ask(customer)
    dispatch_local(customer, text=NAMELESS)
    assert UX['en']['cv_example_copied'] in screen(dispatch_local(customer, text='dilnoza rahimova'))[0]
    # Sent again at once it is kept, as any answer is; the check cannot see a lower-case name, so it is asked again.
    words, _ = screen(dispatch_local(customer, text='dilnoza rahimova'))
    assert listed(words) == ['name'] and UX['en']['cv_example_copied'] not in words, words
    assert state(customer)[1]['brief'] == [NAMELESS, 'dilnoza rahimova']
    # Kept, it is the customer's: sent again, it is taken as the name, as any name the check cannot see.
    words, _ = screen(dispatch_local(customer, text='dilnoza rahimova'))
    assert '📄 dilnoza rahimova' in words, words


def test_a_first_description_is_the_customers_and_a_name_like_the_samples_is_ours_only_alone(customer, model):
    # Nothing has been shown yet to copy: a first message is the customer's.
    words, _ = screen(write(customer, 'Dilnoza Rahimova'))
    assert listed(words) == ['contact', 'background'] and UX['en']['cv_example_copied'] not in words, words
    # The sample name is ours only on its own: beside anything else it may be the customer's own name.
    assert sent_back('Dilnoza Rahimova') and sent_back(' DILNOZA   rahimova \n')
    assert not sent_back('Dilnoza Rahimova, cashier')
    assert not sent_back('Dilnoza Karimova') and not sent_back('') and not sent_back('\n \n')
    assert sent_back('  +998 90 123 45 67  \n\nDILNOZA@example.com')


def test_a_message_holding_a_sample_phone_email_job_or_school_is_ours():
    # Held anywhere in a message, in any language, however it is spaced or dashed: our example, not the customer's.
    for value in ('Dilnoza Karimova, +998 90 123 45 67', 'My email: Dilnoza@Example.com, call after six', '+998901234567',
                  'Aziz Karimov\nSales manager , Bahor Foods , 2021 - 2024',
                  "TDIU, marketing yo'nalishi, 2018-yilda bitirganman",
                  'Азиз Каримов, ТГЭУ, маркетинг, окончила в 2018 году',
                  'Tashkent State University of Economics,\nmarketing, 2018'):
        assert sent_back(value), value
    # The customer's own details are theirs, however like the samples they look.
    for value in ('Aziz Karimov, +998 91 234 56 78', 'aziz@example.org', 'Sales manager, Bahor Foods, 2019–2021',
                  'Tashkent State University, economics, 2018', 'Dilnoza Karimova\n+998 91 234 56 78'):
        assert not sent_back(value), value


@pytest.mark.parametrize('locale,greeting,name', [
    ('en', 'Hello', 'Aziz Karimov'), ('uz', 'Assalomu alaykum', 'Aziz Karimov'), ('ru', 'Здравствуйте', 'Азиз Каримов')],
    ids=LOCALES)
def test_the_missing_screens_own_lines_copied_back_are_answered_as_ours(customer, model, locale, greeting, name):
    import html
    import re
    speaks(customer, locale)
    copy = UX[locale]
    tap(customer, dispatch_local(customer, text='/cv'), copy['cv_mode_text'])
    shown = html.unescape(re.sub(r'<[^>]+>', '', screen(dispatch_local(customer, text=greeting))[0]))
    bullets = '\n'.join(line for line in shown.split('\n') if line.startswith('• '))
    assert bullets.count('• ') == 3, shown
    # The list copied as a long press copies it, the bullets dropped, or the whole screen: ours, and nothing kept.
    for value in (bullets, bullets.replace('• ', ''), shown, bullets.split('\n')[0]):
        words, _ = screen(dispatch_local(customer, text=value))
        assert copy['cv_example_copied'] in words and listed(words, locale) == ['name', 'contact', 'background'], words
        assert state(customer)[1]['brief'] == [greeting], value
    # The customer's own name after it: what is missing is still the phone and the work, never taken from our example.
    words, _ = screen(dispatch_local(customer, text=name))
    assert listed(words, locale) == ['contact', 'background'] and copy['cv_example_copied'] not in words, words
    assert state(customer)[1]['brief'] == [greeting, name]
    assert not GenerationDraft.objects.filter(account=customer).exists()


def test_a_message_holding_a_sample_sent_again_at_once_is_still_ours(customer, model):
    ask(customer)
    dispatch_local(customer, text='Hello')
    # Nobody has the sample's number: sent once or again, it is our example, and nothing is kept.
    for _ in range(3):
        words, _ = screen(dispatch_local(customer, text='Aziz Karimov, +998 90 123 45 67'))
        assert UX['en']['cv_example_copied'] in words and listed(words) == ['name', 'contact', 'background'], words
        assert state(customer)[1]['brief'] == ['Hello'], words
    assert not GenerationDraft.objects.filter(account=customer).exists()


# The missing screen's list with the customer's own details in place of ours: its labels say it is a copy of the screen.
OWN_IN_FORMAT = {
    'en': '• full name — e.g. Aziz Karimov\n• phone or email — e.g. +998 91 555 44 33\n'
          '• work experience (with years) or education — e.g. Cashier, Korzinka, 2019–2022',
    'uz': '• to‘liq ism-familiya — masalan: Aziz Karimov\n• telefon yoki email — masalan: +998 91 555 44 33\n'
          '• ish tajribasi (yillari bilan) yoki taʼlim — masalan: Kassir, Korzinka, 2019–2022',
    'ru': '• имя и фамилия — например: Азиз Каримов\n• телефон или почта — например: +998 91 555 44 33\n'
          '• опыт работы (с годами) или образование — например: Кассир, Корзинка, 2019–2022'}
SAMPLE_PHONE = {'en': 'Dilnoza Karimova +998 90 123 45 67', 'uz': 'Dilnoza Karimova +998 90 123 45 67',
                'ru': 'Дильноза Каримова +998 90 123 45 67'}


def copied_list(words):
    """The missing screen's list as a long press copies it: its bullet lines, the markup gone."""
    import html
    import re
    shown = html.unescape(re.sub(r'<[^>]+>', '', words))
    return '\n'.join(line for line in shown.split('\n') if line.startswith('• '))


@pytest.mark.parametrize('locale,greeting,name', [
    ('en', 'Hello', 'Aziz Karimov'), ('uz', 'Salom', 'Aziz Karimov'), ('ru', 'Здравствуйте', 'Азиз Каримов')], ids=LOCALES)
def test_the_copied_list_or_a_sample_phone_sent_again_is_never_kept(customer, model, locale, greeting, name):
    from django.core.cache import cache
    speaks(customer, locale)
    copy = UX[locale]
    tap(customer, dispatch_local(customer, text='/cv'), copy['cv_mode_text'])
    bullets = copied_list(screen(dispatch_local(customer, text=greeting))[0])
    assert bullets.count('• ') == 3, bullets
    # The list copied back, a name with the sample's number, or the list's labels with the customer's own details:
    # our example however often it is sent, and nothing kept, so nothing of ours is ever taken as theirs.
    for value in (bullets, SAMPLE_PHONE[locale], OWN_IN_FORMAT[locale]):
        for _ in range(3):
            cache.delete(f'rate:bot_generation:{customer.pk}')
            words, _ = screen(dispatch_local(customer, text=value))
            assert copy['cv_example_copied'] in words and listed(words, locale) == ['name', 'contact', 'background'], words
            assert state(customer)[1]['brief'] == [greeting], value
    # The customer's own name after it: the phone and the work are still asked for, and no CV is made of our example.
    words, _ = screen(dispatch_local(customer, text=name))
    assert listed(words, locale) == ['contact', 'background'] and copy['cv_example_copied'] not in words, words
    assert state(customer)[1]['brief'] == [greeting, name]
    assert not GenerationDraft.objects.filter(account=customer).exists() and not Quote.objects.filter(account=customer).exists()


def test_only_the_sample_name_can_be_the_customers_own():
    from telegram.bot import sample_held
    # The name alone may be someone's: ours the first time only (sent_back), never held for good.
    for value in ('Dilnoza Rahimova', 'Дильноза Рахимова', ' DILNOZA   rahimova \n'):
        assert sent_back(value) and not sample_held(value), value
    # The sample's number, address, job or school, and the list's labels with the word before the example, in
    # any language, with the dash or without: held for good.
    for value in ('+998 90 123 45 67', 'Dilnoza Karimova +998 90 123 45 67', 'DILNOZA@example.com',
                  'Sales manager, Bahor Foods, 2021–2024', 'ТГЭУ, маркетинг, окончила в 2018 году',
                  '• full name — e.g. Aziz Karimov', 'phone or email e.g. aziz@mail.uz',
                  "to'liq ism-familiya - masalan: Aziz Karimov", 'telefon yoki email masalan +998 91 555 44 33',
                  'опыт работы (с годами) или образование — например: Кассир, 2019–2022', *OWN_IN_FORMAT.values()):
        assert sample_held(value) and sent_back(value), value
    # The customer's own words, the labels said their own way: theirs.
    for value in ('Full name: Aziz Karimov', 'Phone or email: +998 91 234 56 78', 'Telefon: +998 91 234 56 78',
                  'Имя и фамилия: Азиз Каримов', 'Tashkent State University, economics, 2018', 'Dilnoza Karimova', ''):
        assert not sample_held(value), value


def test_only_an_answer_that_looks_like_a_name_is_taken_as_one(customer, model):
    ask(customer)
    dispatch_local(customer, text=NAMELESS)
    dispatch_local(customer, text='I also have a driving licence, category B.')
    # Asked again and again, but with no name: never made with "And I can work weekends." as its title.
    for answer in ('And I can work weekends.', 'And I can work weekends.'):
        words, _ = screen(dispatch_local(customer, text=answer))
        assert listed(words) == ['name'] and not GenerationDraft.objects.filter(account=customer).exists(), words
    words, _ = screen(dispatch_local(customer, text='Dilnoza Karimova'))
    assert '📄 Dilnoza Karimova' in words, words


def test_the_nameless_description_sent_again_is_asked_for_the_name_again(customer, model):
    ask(customer)
    dispatch_local(customer, text=NAMELESS)
    words, _ = screen(dispatch_local(customer, text=NAMELESS))
    assert listed(words) == ['name'] and UX['en']['cv_name_again'] in words, words
    assert not GenerationDraft.objects.filter(account=customer).exists()


@pytest.mark.parametrize('locale', LOCALES)
def test_the_cv_examples_read_as_text_in_quotes_that_open_on_a_tap(customer, locale):
    speaks(customer, locale)
    question = tap(customer, dispatch_local(customer, text='/cv'), UX[locale]['cv_mode_text'])
    words, _ = screen(tap(customer, question, UX[locale]['ai_examples']))
    for number, row in enumerate(PROMPT_EXAMPLES[CV], 1):
        assert f'<blockquote expandable>{number}. {html.escape(row[LOCALES.index(locale)])}</blockquote>' in words
    assert '<code>' not in words and len(words) < 4096, words


def test_the_examples_lead_back_to_the_open_question_with_what_was_written(customer, model):
    ask(customer)
    question = dispatch_local(customer, text=NAMELESS)
    examples = tap(customer, question, UX['en']['ai_examples'])
    words, _ = screen(tap(customer, examples, SERVICE))
    assert listed(words) == ['name'] and '📝 Noted: “Data analyst in Tashkent.' in words, words
    assert state(customer)[1]['brief'] == [NAMELESS] and state(customer)[1]['missing'] == ['name']
    dispatch_local(customer, text='Dilnoza Karimova')
    assert latest(customer, CV)['prompt'] == f'Dilnoza Karimova\n{NAMELESS}'


# --- What is missing, listed once and answered in pieces ---------------------------------------------

# Everything about the person but how to reach them.
CONTACTLESS = ('Dilnoza Karimova\nSales manager at Example Retail, Tashkent, 2021-2024: ran the online shop.\n'
               'Bachelor in economics, Tashkent State University, 2018.')
# The customer's own number: the screens' sample number (+998 90 123 45 67) sent back is our example, not theirs.
PHONE = '+998 91 234 56 78'


def test_missing_facts_are_listed_on_one_screen_and_answered_in_pieces(customer, model):
    ask(customer)
    # A name and nothing else: the two other required facts are listed together, each with an example.
    words, _ = screen(dispatch_local(customer, text='Dilnoza Karimova'))
    assert listed(words) == ['contact', 'background'], words
    assert '• phone or email — e.g. <code>+998 90 123 45 67</code> or <code>dilnoza@example.com</code>' in words
    assert ('• work experience (with years) or education — e.g. <code>Sales manager, Bahor Foods, 2021–2024</code> or '
            '<code>Tashkent State University of Economics, marketing, 2018</code>') in words, words
    # A name alone sent again never makes a CV, so the screen does not offer that: it asks for the work or studies.
    assert UX['en']['cv_got'].format(facts='full name') in words and words.endswith(UX['en']['cv_missing_more']), words
    assert UX['en']['cv_name_again'] not in words and UX['en']['cv_missing_again'] not in words
    assert actions(customer) == [['ai_examples'], ['home']]
    assert state(customer) == ('ai_input', {'feature_id': CV, 'brief': ['Dilnoza Karimova'], 'ask': 'missing',
                                            'missing': ['contact', 'background']})
    # A phone, in a message of its own: the screen updates and no longer lists it.
    words, _ = screen(dispatch_local(customer, text=PHONE))
    assert listed(words) == ['background'], words
    assert UX['en']['cv_got'].format(facts='full name · phone or email') in words
    assert state(customer) == ('ai_input', {'feature_id': CV, 'brief': ['Dilnoza Karimova', PHONE], 'ask': 'missing',
                                            'missing': ['background']})
    assert not GenerationDraft.objects.filter(account=customer).exists() and not Quote.objects.filter(account=customer).exists()
    # A job with its dates: nothing is missing, so the review follows at once, with no step in between.
    job = 'Sales manager, Example Retail, 2021–2024'
    words, shown = screen(dispatch_local(customer, text=job))
    assert '📄 Dilnoza Karimova' in words and shown[0] == '✨ Generate', words
    assert UX['en']['cv_missing_title'] not in words
    data = latest(customer, CV)
    assert data['prompt'] == f'{job}\nDilnoza Karimova\n{PHONE}' and data['title'] == 'Dilnoza Karimova'
    assert generation.facts_of(cv(customer))['missing'] == []
    assert state(customer) == ('cv_review', {'draft_id': str(cv(customer).id)})
    # What only adds to it is one line on the review: not a question, not a button.
    assert '💡 You can still add: the job you want · city · birth date or age · skills' in words, words
    assert not Job.objects.filter(account=customer).exists()


def test_the_facts_asked_for_in_one_message_are_all_taken(customer, model):
    ask(customer)
    dispatch_local(customer, text='Dilnoza Karimova')
    words, _ = screen(dispatch_local(customer, text=f'{PHONE}\nSales manager, Example Retail, 2021–2024'))
    assert '📄 Dilnoza Karimova' in words and UX['en']['cv_missing_title'] not in words, words


def test_a_description_missing_only_its_contact_is_made_once_a_phone_is_sent(customer, model):
    words, _ = screen(write(customer, CONTACTLESS))
    assert listed(words) == ['contact'], words
    assert UX['en']['cv_got'].format(facts='full name · work experience (with years) or education') in words
    # Someone with neither a phone nor an email is told how the CV is made without them.
    assert words.endswith('↩️ No phone or email? Send the same message again and I’ll make the CV without one.'), words
    words, _ = screen(dispatch_local(customer, text=f'Phone {PHONE}'))
    assert '📄 Dilnoza Karimova' in words and UX['en']['cv_missing_title'] not in words, words
    assert latest(customer, CV)['prompt'] == f'Phone {PHONE}\n{CONTACTLESS}'
    assert generation.facts_of(cv(customer))['missing'] == []
    assert '💡 You can still add: phone' not in words


def test_the_same_description_sent_twice_is_made_with_only_its_contact_missing(customer, model):
    words, _ = screen(write(customer, CONTACTLESS))
    assert listed(words) == ['contact'] and not GenerationDraft.objects.filter(account=customer).exists()
    words, shown = screen(dispatch_local(customer, text=CONTACTLESS))
    # Made as it is, once, with the customer's own name as its title and the lack said on the review.
    assert '📄 Dilnoza Karimova' in words and shown[0] == '✨ Generate', words
    assert latest(customer, CV)['prompt'] == CONTACTLESS and latest(customer, CV)['title'] == 'Dilnoza Karimova'
    assert '💡 You can still add: phone or email · the job you want · birth date or age · skills' in words, words
    assert generation.facts_of(cv(customer))['missing'] == ['contact']
    assert GenerationDraft.objects.filter(account=customer).count() == 1


@pytest.mark.parametrize('locale,name,job', [
    ('uz', 'Dilnoza Karimova', '2021-2024-yillarda Example Retail do‘konida sotuvchi bo‘lib ishlaganman'),
    ('ru', 'Дильноза Каримова', 'Менеджер по продажам, Example Retail, 2021–2024')])
def test_the_facts_are_asked_for_and_answered_in_pieces_in_every_language(customer, model, locale, name, job):
    speaks(customer, locale)
    copy = UX[locale]
    tap(customer, dispatch_local(customer, text='/cv'), copy['cv_mode_text'])
    words, _ = screen(dispatch_local(customer, text=name))
    assert listed(words, locale) == ['contact', 'background'] and copy['cv_got'].format(facts=copy['cv_fact_name']) in words
    words, _ = screen(dispatch_local(customer, text=PHONE))
    assert listed(words, locale) == ['background'], words
    words, shown = screen(dispatch_local(customer, text=job))
    assert f'📄 {name}' in words and shown[0] == copy['ai_generate'], words
    assert copy['cv_missing_title'] not in words and copy['cv_can_add'].split('{')[0] in words, words
    assert latest(customer, CV)['title'] == name


def test_the_name_found_is_the_title_however_the_customer_insisted(customer, model):
    words, _ = screen(write(customer, CONTACTLESS))
    assert listed(words) == ['contact']
    # A line that is no contact, sent twice: the CV is made without one, and is still the person's, not the line's.
    dispatch_local(customer, text='Call me please')
    words, _ = screen(dispatch_local(customer, text='Call me please'))
    assert '📄 Dilnoza Karimova' in words and '📄 Call me please' not in words, words
    data = latest(customer, CV)
    assert data['title'] == 'Dilnoza Karimova' and data['prompt'].startswith('Call me please\nDilnoza Karimova')


def test_a_description_repeated_with_its_name_missing_is_made_only_if_it_looks_like_one(customer, model):
    nameless = NAMELESS.replace(', email dilnoza.karimova@example.com', '')
    words, _ = screen(write(customer, nameless))
    assert listed(words) == ['name'], words
    assert listed(screen(dispatch_local(customer, text=nameless))[0]) == ['name'], 'a description is no name'
    assert not GenerationDraft.objects.filter(account=customer).exists()


@pytest.mark.parametrize('locale', LOCALES)
def test_every_sample_a_screen_shows_satisfies_the_check_that_asks_for_it(locale):
    import re
    from types import SimpleNamespace
    from apps.studio.cv.content import REQUIRED_FACTS, facts
    account = SimpleNamespace(locale=locale)
    words = missing_lines(account, REQUIRED_FACTS)
    # Each code is one value, so a tap copies one: a phone or an email, a job or a school, never both.
    samples = re.findall(r'<code>(.*?)</code>', words)
    assert len(samples) == 5, samples
    name, phone, email, job, school = samples
    assert name_in(name) == name and not facts(name)['contact'] and not facts(name)['background']
    assert facts(phone)['contact'] and facts(email)['contact'] and 'example.com' in email
    assert facts(job)['background'] and facts(school)['background']
    copy = UX[locale]
    for sample in samples:
        assert f' {copy["cv_or"]} ' not in sample and ' — ' not in sample and ', or ' not in sample, sample
    # The alternative is said between the codes, in the reader's language.
    assert f'</code> {copy["cv_or"]} <code>' in words
    # Every one of them, in any language, is known as ours when it comes back.
    assert all(sent_back(sample) for sample in samples)


def test_the_samples_name_no_real_employer_and_the_examples_no_real_brand():
    # Everyone and every employer in what the screens show is made up.
    for key, values in MESSAGES.items():
        for value in values:
            assert 'Baraka' not in value, key
    assert all('Baraka' not in example for row in PROMPT_EXAMPLES[CV] for example in row)
    assert 'Bahor Foods' in UX['en']['cv_fact_background_sample']


@pytest.mark.parametrize('locale', LOCALES)
def test_each_fact_is_said_by_one_label_on_every_screen_of_the_cv(locale):
    from types import SimpleNamespace
    from apps.studio.cv.content import OPTIONAL_FACTS, REQUIRED_FACTS
    copy = UX[locale]
    account = SimpleNamespace(locale=locale)
    labels = {fact: copy[f'cv_fact_{fact}'] for fact in (*REQUIRED_FACTS, *OPTIONAL_FACTS)}
    # The first screen's lists are the labels, so the hint never drifts from what the review offers.
    assert asks_for(locale).endswith(', '.join(labels[fact] for fact in OPTIONAL_FACTS if fact != 'photo'))
    assert all(f'\n• {labels[fact][:1].upper()}{labels[fact][1:]}' in asks_for(locale) for fact in REQUIRED_FACTS)
    # The missing screen's 'already there' line names the same facts the same way.
    assert copy['cv_got'].format(facts=labels['name']) in missing_lines(account, ['contact', 'background'])
    assert can_add_line(account, {'missing': ['contact']}) == copy['cv_can_add'].format(facts=labels['contact'])
    # Russian says имя и фамилия and опыт работы с годами wherever it says them.
    if locale == 'ru':
        assert labels['name'] == 'имя и фамилия' and labels['background'] == 'опыт работы (с годами) или образование'
        assert all('полное имя' not in value and 'с датами' not in value for value in copy.values() if isinstance(value, str))
    if locale == 'uz':
        assert labels['target'] == 'xohlagan lavozim'


def test_a_question_kept_before_the_facts_were_listed_is_still_answered(customer, model):
    def kept(state, **prompt):
        BotConversation.objects.filter(pk=customer.telegram_user_id).update(
            state=state, prompt={'feature_id': CV, **prompt}, updated_at=timezone.now())
    # Asked for the name (ask 'name'): an answer is taken as before, and a later screen is the new one.
    kept('ai_input', brief=[NAMELESS], question='old1', ask='name')
    words, _ = screen(dispatch_local(customer, text='Dilnoza Karimova'))
    assert '📄 Dilnoza Karimova' in words and latest(customer, CV)['prompt'] == f'Dilnoza Karimova\n{NAMELESS}'
    # Asked for the details of a greeting (ask 'details'): all three are asked for, now as a list.
    kept('ai_input', brief=['Hello'], question='old2', ask='details')
    words, _ = screen(dispatch_local(customer, text='My name is Dilnoza Karimova'))
    assert listed(words) == ['contact', 'background'] and state(customer)[1]['ask'] == 'missing', words
    # The same screen drawn again from a state with no list (the examples, a photo, the same photo twice).
    kept('ai_input', brief=[NAMELESS], question='old3', ask='name')
    words, _ = screen(dispatch_local(customer, uploaded=image()))
    assert listed(words) == ['name'] and state(customer)[1]['missing'] == ['name'], words
    assert cv_asked({'ask': 'details'}) == ['name', 'contact', 'background'] and cv_asked({'ask': 'name'}) == ['name']
    assert cv_asked({'ask': 'missing', 'missing': ['background', 'bogus']}) == ['background']
    assert cv_asked({'ask': 'file'}) == [] and cv_asked({}) == [] and cv_asked(None) == []


def test_the_same_photo_delivered_twice_draws_the_same_question(customer, model, monkeypatch):
    ask(customer)
    dispatch_local(customer, text='Dilnoza Karimova')
    monkeypatch.setattr('telegram.local.secrets.randbelow', lambda limit: 43)
    first = screen(dispatch_local(customer, uploaded=image()))
    again = screen(dispatch_local(customer, uploaded=image()))
    assert listed(first[0]) == listed(again[0]) == ['contact', 'background'] and UX['en']['cv_photo_line'] in again[0]
    assert UX['en']['cv_photo_attached'] in first[0]
    assert state(customer)[1]['missing'] == ['contact', 'background']
    assert FileAsset.objects.filter(account=customer).count() == 1


def test_a_cv_keeps_the_first_description_and_the_newest_eleven_pieces(customer, model):
    assert CV_BRIEF_PIECES == 12
    pieces = [f'piece {number}' for number in range(30)]
    kept = kept_brief(pieces, CV_BRIEF_CHARS, CV_BRIEF_PIECES)
    assert kept == ['piece 0', *pieces[-11:]]
    ask(customer)
    for number in range(14):
        words, _ = screen(dispatch_local(customer, text=f'Hello number {number}'))
    assert state(customer)[1]['brief'][0] == 'Hello number 0' and len(state(customer)[1]['brief']) == 12
    assert state(customer)[1]['brief'][-1] == 'Hello number 13' and listed(words) == ['name', 'contact', 'background']


def test_the_line_on_the_review_names_what_is_missing_first_and_four_at_most():
    from types import SimpleNamespace
    account = SimpleNamespace(locale='en')
    optional = ['target', 'location', 'birth', 'skills', 'languages', 'certificates', 'projects', 'links', 'photo']
    assert can_add_line(account, {'missing': [], 'optional_missing': optional}) == (
        '💡 You can still add: the job you want · city · birth date or age · skills')
    # After the customer insisted: what the CV lacks comes first, the photo is never named (its own line says it).
    assert can_add_line(account, {'missing': ['contact', 'background'], 'optional_missing': optional}) == (
        '💡 You can still add: phone or email · work experience (with years) or education · the job you want · city')
    assert can_add_line(account, {'missing': [], 'optional_missing': ['photo']}) == ''
    assert can_add_line(account, {'missing': [], 'optional_missing': ['links', 'photo', 'bogus']}) == (
        '💡 You can still add: LinkedIn or other links')
    assert can_add_line(account, {}) == can_add_line(account, None) == ''
    assert can_add_line(SimpleNamespace(locale='uz'), {'optional_missing': ['location', 'skills']}) == (
        '💡 Yana qo‘shishingiz mumkin: shahar · ko‘nikmalar')
    assert can_add_line(SimpleNamespace(locale='ru'), {'missing': ['contact']}) == '💡 Можно добавить ещё: телефон или почта'


def test_a_complete_description_has_nothing_to_add_but_what_it_leaves_out(customer, model):
    words, _ = screen(write(customer, BRIEF))
    # It gives a city, skills and languages, and a job wanted is not in it.
    assert '💡 You can still add: the job you want · birth date or age · certificates · projects' in words, words
    assert generation.facts_of(cv(customer))['missing'] == []


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
    write(customer, BRIEF)
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
    write(customer, BRIEF)
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
