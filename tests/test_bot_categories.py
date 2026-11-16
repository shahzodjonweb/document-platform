"""The list of categories in front of AI PDF and AI Slides, and every way into it (architecture 8.1, 8.2).

With the switch on and a category ticked, tapping AI PDF or AI Slides opens a
list: one button per category or group customers may pick now, and Boshqa
(“Other”), which is today's question. A category opens its own question, with
its own prompt and examples, and the draft written there carries it
(`options.category`). Every door keeps it: the gate, a refusal, the topic
question, the examples, a failed job's “Change the description”, the review's.

With the switch off, or nothing ticked for a service, there is no list and
every way in is today's question, whatever a button from an older list names.
The existing bot tests run with the switch off and are not edited; the twin of
"one tap reaches the description" is here.

The people, organisations and descriptions are invented for these tests.
"""
import copy
import html
import re
import secrets
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.commerce.models import LocalBotMessage
from apps.core import channel_gate
from apps.core.identity import resolve_account
from apps.core.models import AnalyticsEvent, BotCallback, BotConversation, ChannelMembership, Job
from apps.studio import categories
from apps.studio.categories import catalogue
from apps.studio.domain import DOCUMENT, SLIDES, unpack
from apps.studio.models import GenerationDraft
from operations.integrations import save_config
from operations.models import IntegrationConfig
from telegram import generation
from telegram.bot import ai_state, category_flow
from telegram.channels import COPY as GATE
from telegram.ux_copy import LOCALES, MESSAGES, TOOL_NAMES, UX
from tests.test_bot_no_flood import Chat
from tests.test_channel_gate import Telegram, require_channels
from tests.test_manual_payments import paid

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]

TEST = 'pdf.test'           # top of the PDF list; asks for a topic, in its own words
ARIZA = 'pdf.xat.ariza'     # in the group pdf.xat; about itself, so no topic is asked
GROUP = 'pdf.xat'
HIMOYA = 'slides.himoya'    # top of the slides list; asks for a topic in today's words
EVERY = [TEST, ARIZA, HIMOYA]

QUIZ = 'Biologiya, 7-sinf, fotosintez mavzusida 20 ta savollik test.'
DEFENCE = 'Kurs ishi himoyasi uchun 6 ta slayd: “Kichik biznesda raqamli marketing”. Bajardi: Laylo Rahimova.'
APPLICATION = '“Yashil vodiy” MChJ direktoriga ariza: 10-dekabrdan 5 kunlik ta’til so‘rayman. Nodira Saidova.'


@pytest.fixture
def ready(monkeypatch):
    """The catalogue with its entries marked ready, as N1 and N2 will mark them."""
    entries, templates, index = copy.deepcopy(catalogue.read())
    for raw in entries.values():
        raw['status'] = 'ready'
    made = catalogue.build(entries, templates, index)
    monkeypatch.setattr(catalogue, '_catalogue', lambda: made)
    return made


def turn(on=True, live=tuple(EVERY)):
    """The switch row as the owner leaves it on /ops/categories (operations/categories_settings.py)."""
    IntegrationConfig.objects.update_or_create(pk='categories', defaults={'configuration': {'on': on, 'live': list(live)}})


@pytest.fixture
def switch(ready):
    turn()
    return turn


@pytest.fixture
def customer(settings, monkeypatch):
    import telegram.bot as bot
    monkeypatch.setattr(bot, 'ALBUM_SETTLE', 0)
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    save_config('telegram', {'token': '', 'username': 'fixture_bot', 'webapp_url': 'https://docmaster.example/en/app'})
    account = resolve_account({'id': 985101, 'first_name': 'Category test'}, is_test=True)
    BotConversation.objects.create(telegram_user_id=account.telegram_user_id, locale='en',
                                   language_selected_at=timezone.now())
    paid(account, 'premium')
    cache.clear()
    return account


@pytest.fixture
def model():
    # A model to write with: in local authoring the text is the document and no topic is ever asked.
    save_config('ai', {'mode': 'openai', 'model': 'gpt-5.6-luna', 'api_key': 'sk-offline-test-only'})


def speak(account, locale):
    account.locale = locale
    account.save(update_fields=['locale'])
    BotConversation.objects.filter(pk=account.telegram_user_id).update(locale=locale)


def pending(account):
    conversation = BotConversation.objects.get(pk=account.telegram_user_id)
    return conversation.state, {key: value for key, value in conversation.prompt.items() if key != 'question'}


def screen(account):
    """The newest bot message as (text, rows of actions, rows of payloads, rows of labels), after any edits."""
    message = LocalBotMessage.objects.filter(account=account, direction='outbound').order_by('-created_at').first()
    refs = [[BotCallback.objects.filter(pk=button.get('callback_data')).first() for button in row] for row in message.buttons]
    actions = [[ref.action if ref else 'url' for ref in row] for row in refs]
    payloads = [[ref.payload if ref else None for ref in row] for row in refs]
    labels = [[button['label'] for button in row] for row in message.buttons]
    return message.text, actions, payloads, labels


def opened(account, service=DOCUMENT):
    """A chat that tapped AI PDF (or AI Slides) on the menu."""
    chat = Chat(account)
    chat.do(text='/ai')
    assert chat.tap('ai_tool', feature_id=service) == 0, 'the menu becomes the next screen; nothing is added'
    return chat


def latest(account, feature_id=DOCUMENT):
    return unpack(GenerationDraft.objects.filter(account=account, feature_id=feature_id).latest('created_at').encrypted_data)


def label(entry_id, locale='en'):
    return categories.get(entry_id).label(locale)


def old_button(account, payload, days=20):
    """An ai_tool button from a message sent `days` ago, still in the chat, as a customer scrolls back to it."""
    token = secrets.token_urlsafe(12)
    BotCallback.objects.create(token=token, account=account, action='ai_tool', payload=payload,
                               expires_at=timezone.now() - timedelta(days=days))
    LocalBotMessage.objects.create(account=account, direction='outbound', text='An older screen',
                                   buttons=[[{'label': 'Old', 'callback_data': token, 'url': None}]],
                                   telegram_message_id=secrets.randbelow(1_000_000) + 1)
    return token


def tapped(account, payload, action='ai_tool'):
    """Taps the newest button with exactly this payload, wherever it is on screen."""
    ref = BotCallback.objects.filter(account=account, action=action, payload=payload).order_by('-expires_at').first()
    assert ref is not None, f'no {action} button {payload}'
    return Chat(account).do(callback_data=ref.pk)


# --- The list -------------------------------------------------------------------------------------


@pytest.mark.parametrize('locale', LOCALES)
def test_the_list_and_its_group_in_every_language(customer, switch, locale):
    speak(customer, locale)
    opened(customer)
    text, actions, payloads, labels = screen(customer)
    service = TOOL_NAMES[DOCUMENT][locale]
    assert text == f'<b>{service}</b>\n{UX[locale]["ai_cat_choose"]}'
    index = catalogue._catalogue().index
    assert labels == [[label(TEST, locale)], [index['groups'][GROUP]['label'][locale]], [index['other'][locale]],
                      [UX[locale]['ai_back']]]
    assert actions == [['ai_tool'], ['ai_tool'], ['ai_tool'], ['home']]
    assert payloads[:3] == [[{'feature_id': DOCUMENT, 'category': TEST}], [{'feature_id': DOCUMENT, 'category': GROUP}],
                            [{'feature_id': DOCUMENT, 'category': 'other'}]]
    assert pending(customer) == ('ai_category', {'feature_id': DOCUMENT})

    # A group is a list of its own: its categories, its own Boshqa, Back to the list beside the menu.
    tapped(customer, {'feature_id': DOCUMENT, 'category': GROUP})
    text, actions, payloads, labels = screen(customer)
    assert text == f'<b>{service} · {index["groups"][GROUP]["label"][locale]}</b>\n{UX[locale]["ai_cat_choose"]}'
    assert labels == [[label(ARIZA, locale)], [index['groups'][GROUP]['other'][locale]],
                      [UX[locale]['ai_back'], UX[locale]['home']]]
    assert actions == [['ai_tool'], ['ai_tool'], ['ai_tool', 'home']]
    assert payloads == [[{'feature_id': DOCUMENT, 'category': ARIZA}],
                        [{'feature_id': DOCUMENT, 'category': 'other', 'group': GROUP}],
                        [{'feature_id': DOCUMENT}, {}]]
    assert pending(customer) == ('ai_category', {'feature_id': DOCUMENT, 'group': GROUP})

    # The slides list holds what is ticked for slides, and its own Boshqa.
    opened(customer, SLIDES)
    text, actions, payloads, labels = screen(customer)
    assert text == f'<b>{TOOL_NAMES[SLIDES][locale]}</b>\n{UX[locale]["ai_cat_choose"]}'
    assert labels == [[label(HIMOYA, locale)], [index['other'][locale]], [UX[locale]['ai_back']]]


def test_one_tap_reaches_the_list_and_a_description_typed_on_it_is_todays_flow(customer, switch):
    """The twin of test_bot_generation's "one tap reaches the description", for the switch on.

    Tapping the service and writing at once is still one message: the words
    are a description for Boshqa, made as today's document, with no category.
    """
    chat = opened(customer)
    assert pending(customer) == ('ai_category', {'feature_id': DOCUMENT})
    assert chat.do(text='A 4 page introduction to tide tables for beginners.') == 1, '"Preparing…" becomes the review'
    assert 'Ready to start' in chat.last() and 'Pages: 4' in chat.last()
    data = latest(customer)
    assert 'category' not in data['options']
    assert pending(customer) == ('', {})


def test_boshqa_is_todays_question_exactly(customer, switch):
    chat = opened(customer)
    assert chat.tap('ai_tool', feature_id=DOCUMENT, category='other') == 0
    text, actions, payloads, _ = screen(customer)
    assert 'Describe what you want' in text and 'how many pages' in text
    assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT})
    # Back goes to the list it was chosen on, beside the menu.
    assert actions == [['ai_examples'], ['ai_tool', 'home']]
    assert payloads[1][0] == {'feature_id': DOCUMENT}
    assert chat.do(text='A 3 page guide to tide tables.') == 1
    assert 'category' not in latest(customer)['options']

    # The Boshqa of a group ("Another letter") is the same question, and its Back returns to the group.
    opened(customer)
    tapped(customer, {'feature_id': DOCUMENT, 'category': GROUP})
    tapped(customer, {'feature_id': DOCUMENT, 'category': 'other', 'group': GROUP})
    text, actions, payloads, _ = screen(customer)
    assert 'Describe what you want' in text and pending(customer) == ('ai_input', {'feature_id': DOCUMENT})
    assert payloads[1][0] == {'feature_id': DOCUMENT, 'category': GROUP}


def test_with_the_switch_off_every_way_in_is_todays_question(customer, ready):
    turn(on=False)
    chat = opened(customer)
    text, actions, _, _ = screen(customer)
    assert 'Describe what you want' in text and actions == [['ai_examples'], ['home']]
    assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT})
    # A button from a list drawn while it was on: a category, a group, Boshqa, all today's question.
    for named in (TEST, GROUP, 'other'):
        assert chat.do(callback_data=old_button(customer, {'feature_id': DOCUMENT, 'category': named}, 3)) == 0
        assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT}), named
        assert 'Describe what you want' in screen(customer)[0]
    # On, but nothing ticked for the PDF service: no list for it either.
    turn(live=[HIMOYA])
    opened(customer)
    assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT})
    assert generation.door(DOCUMENT, None) == ('prompt', None, False)
    assert generation.door(SLIDES, None) == ('list', None, False)


@pytest.mark.parametrize('switched', [{'on': False, 'live': list(EVERY)}, {'on': True, 'live': []}, None])
def test_with_nothing_live_no_way_in_loads_the_catalogue(customer, monkeypatch, switched):
    """Off (the shipped default), or on with nothing ticked, today's question never waits on the catalogue.

    Every /document, /slides and menu tap asks for the list; a catalogue that
    failed to load (it is not cached then, so every tap would try again) must
    not break any of them, nor a button from an older list, nor a description
    written in a category before the switch went off.
    """
    if switched is not None:
        turn(**switched)

    def broken():
        raise catalogue.CatalogueError(['the catalogue failed to load'])
    monkeypatch.setattr(catalogue, '_catalogue', broken)
    chat = Chat(customer)
    for command, service in (('/document', DOCUMENT), ('/create', DOCUMENT), ('/slides', SLIDES)):
        chat.do(text=command)
        assert pending(customer) == ('ai_input', {'feature_id': service}), command
        assert 'Describe what you want' in screen(customer)[0], command
    for service in (DOCUMENT, SLIDES):
        opened(customer, service)
        text, actions, _, _ = screen(customer)
        assert 'Describe what you want' in text and actions == [['ai_examples'], ['home']]
        assert pending(customer) == ('ai_input', {'feature_id': service})
    for named in (TEST, GROUP, HIMOYA, 'other'):
        assert chat.do(callback_data=old_button(customer, {'feature_id': DOCUMENT, 'category': named}, 3)) == 0
        assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT}), named
    # A chat left on a category's list or question when the switch went off: a file sent there is
    # taken as today's (category_flow), the examples are the service's, and the document is made
    # without the category.
    for state, prompt in (('ai_category', {'feature_id': DOCUMENT}), ('ai_input', ai_state(DOCUMENT, TEST))):
        BotConversation.objects.filter(pk=customer.telegram_user_id).update(state=state, prompt=prompt)
        assert category_flow(BotConversation.objects.get(pk=customer.telegram_user_id)) is None, state
    examples = old_button(customer, {'feature_id': DOCUMENT, 'category': TEST}, 3)
    BotCallback.objects.filter(pk=examples).update(action='ai_examples')
    chat.do(callback_data=examples)
    assert screen(customer)[2][0] == [{'feature_id': DOCUMENT}], 'the service’s own examples, back to today’s question'
    BotConversation.objects.filter(pk=customer.telegram_user_id).update(
        state='ai_input', prompt=ai_state(DOCUMENT, TEST))
    assert chat.do(text=QUIZ) == 1
    assert 'Ready to start' in chat.last()
    assert 'category' not in latest(customer)['options']
    assert generation.category_review(GenerationDraft.objects.filter(account=customer).latest('created_at')) is None


def test_an_old_service_button_opens_the_list_and_commands_draw_it_with_no_check(customer, switch):
    chat = Chat(customer)
    chat.do(text='/start')
    assert chat.do(callback_data=old_button(customer, {'feature_id': DOCUMENT})) == 0
    assert pending(customer) == ('ai_category', {'feature_id': DOCUMENT})
    for command, service in (('/document', DOCUMENT), ('/create', DOCUMENT), ('/slides', SLIDES)):
        assert chat.do(text=command) == 1
        assert pending(customer) == ('ai_category', {'feature_id': service}), command


# --- A category's question ------------------------------------------------------------------------


@pytest.mark.parametrize('locale', LOCALES)
def test_a_category_opens_its_own_question_and_its_draft_carries_it(customer, switch, locale):
    speak(customer, locale)
    chat = opened(customer)
    assert chat.tap('ai_tool', feature_id=DOCUMENT, category=TEST) == 0
    entry = categories.get(TEST)
    text, actions, payloads, labels = screen(customer)
    examples = [example[locale] for example in entry.raw['bot']['examples']]
    assert text.startswith(f'<b>{TOOL_NAMES[DOCUMENT][locale]} · {entry.label(locale)}</b>\n'
                           f'{html.escape(entry.raw["bot"]["prompt"][locale])}\n\n{UX[locale]["ai_examples"]}:\n\n'
                           f'1. <code>{html.escape(examples[0])}</code>')
    assert '<blockquote expandable>2. ' in text and UX[locale]['ai_cat_files'] in text
    assert 'Describe what you want' not in text
    assert actions == [['ai_examples'], ['ai_tool', 'home']]
    assert payloads[0][0] == {'feature_id': DOCUMENT, 'category': TEST}
    assert payloads[1][0] == {'feature_id': DOCUMENT}, 'Back is the list it was chosen on'
    assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT, 'category': TEST})

    assert chat.do(text=QUIZ) == 1, '"Preparing…" becomes the review'
    assert '✅' in chat.last()
    assert latest(customer)['options']['category'] == TEST
    assert pending(customer) == ('', {})


def test_a_category_in_a_group_goes_back_to_its_group(customer, switch):
    opened(customer)
    tapped(customer, {'feature_id': DOCUMENT, 'category': GROUP})
    tapped(customer, {'feature_id': DOCUMENT, 'category': ARIZA})
    text, actions, payloads, _ = screen(customer)
    assert label(ARIZA) in text and pending(customer) == ('ai_input', {'feature_id': DOCUMENT, 'category': ARIZA})
    assert payloads[1][0] == {'feature_id': DOCUMENT, 'category': GROUP}
    tapped(customer, {'feature_id': DOCUMENT, 'category': GROUP})
    assert pending(customer) == ('ai_category', {'feature_id': DOCUMENT, 'group': GROUP})


def test_a_deck_category_is_made_in_its_category(customer, switch):
    chat = opened(customer, SLIDES)
    chat.tap('ai_tool', feature_id=SLIDES, category=HIMOYA)
    assert pending(customer) == ('ai_input', {'feature_id': SLIDES, 'category': HIMOYA})
    assert chat.do(text=DEFENCE) == 1
    assert 'Slides:' in chat.last()
    assert latest(customer, SLIDES)['options']['category'] == HIMOYA


def test_the_examples_are_the_categorys_and_come_back_to_it(customer, switch):
    chat = opened(customer)
    chat.tap('ai_tool', feature_id=DOCUMENT, category=TEST)
    assert chat.tap('ai_examples', feature_id=DOCUMENT, category=TEST) == 0
    text, actions, payloads, _ = screen(customer)
    for example in categories.get(TEST).raw['bot']['examples']:
        assert html.escape(example['en']) in text
    assert actions == [['ai_tool'], ['home']] and payloads[0][0] == {'feature_id': DOCUMENT, 'category': TEST}
    assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT, 'category': TEST}), 'looking at examples keeps it'
    chat.tap('ai_tool', feature_id=DOCUMENT, category=TEST)
    assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT, 'category': TEST})


def test_a_category_example_sent_back_is_ours_only_in_a_category(customer, switch):
    example = categories.get(HIMOYA).raw['bot']['examples'][1]['en']
    chat = opened(customer, SLIDES)
    chat.tap('ai_tool', feature_id=SLIDES, category=HIMOYA)
    assert chat.do(text=example) == 1
    text, actions, payloads, _ = screen(customer)
    assert text == UX['en']['ai_example_copied']
    assert payloads[0][0] == {'feature_id': SLIDES, 'category': HIMOYA}
    assert not GenerationDraft.objects.filter(account=customer).exists()
    # Boshqa knows only the services' own examples, as before categories.
    assert generation.is_example(example, HIMOYA) and not generation.is_example(example)


def test_an_entry_no_longer_offered_sends_its_old_button_to_the_list(customer, switch):
    opened(customer)
    tapped(customer, {'feature_id': DOCUMENT, 'category': GROUP})
    turn(live=[TEST, HIMOYA])
    # The ariza was unticked while its button was on screen: the list, saying so; its group is empty now.
    tapped(customer, {'feature_id': DOCUMENT, 'category': ARIZA})
    text, _, _, _ = screen(customer)
    assert text.startswith(UX['en']['ai_cat_gone'] + '\n\n<b>')
    assert pending(customer) == ('ai_category', {'feature_id': DOCUMENT})
    assert GROUP not in str(screen(customer)[2]), 'a group with nothing live under it is not shown'
    # Nothing ticked for PDFs any more: today's question.
    turn(live=[HIMOYA])
    tapped(customer, {'feature_id': DOCUMENT, 'category': TEST})
    assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT})
    # The category of the other service, or one the catalogue no longer holds, is not this service's.
    turn()
    assert generation.door(DOCUMENT, HIMOYA) == ('list', None, True)
    assert generation.door(DOCUMENT, 'pdf.rolled_back') == ('list', None, True)
    assert generation.door(DOCUMENT, ARIZA) == ('category', ARIZA, False)
    turn(live=[TEST])
    assert generation.door(DOCUMENT, ARIZA) == ('list', None, True)
    turn(live=[TEST, ARIZA])
    assert generation.door(DOCUMENT, GROUP) == ('list', GROUP, False)


def test_the_switch_turned_off_while_writing_still_makes_a_document(customer, switch):
    chat = opened(customer)
    chat.tap('ai_tool', feature_id=DOCUMENT, category=TEST)
    turn(on=False)
    assert chat.do(text=QUIZ) == 1
    assert 'Ready to start' in chat.last()
    assert 'category' not in latest(customer)['options']


# --- Doors ----------------------------------------------------------------------------------------


@pytest.fixture
def member(customer, monkeypatch):
    """A Free customer, whose services wait behind the owner's channels, and the fake Telegram that says who joined."""
    account = resolve_account({'id': 985102, 'first_name': 'Channel member'}, is_test=True)
    BotConversation.objects.create(telegram_user_id=account.telegram_user_id, locale='en',
                                   language_selected_at=timezone.now())
    fake = Telegram()
    monkeypatch.setattr(channel_gate, '_call', fake)
    monkeypatch.setattr(channel_gate, '_token', lambda: '1:TOKEN')
    require_channels()
    fake.statuses = {'@docmaster_news': 'member'}
    return account, fake


def leave(telegram):
    telegram.statuses = {}
    ChannelMembership.objects.all().delete()


def test_the_gate_comes_back_to_the_category_tapped(switch, member):
    account, telegram = member
    opened(account)
    leave(telegram)
    tapped(account, {'feature_id': DOCUMENT, 'category': TEST})
    assert GATE['en']['gate_one'] in screen(account)[0]
    telegram.statuses = {'@docmaster_news': 'member'}
    ref = BotCallback.objects.filter(account=account, action='channels_check').order_by('-expires_at').first()
    assert ref.payload == {'kind': 'ai_prompt', 'feature_id': DOCUMENT, 'category': TEST}
    Chat(account).do(callback_data=ref.pk)
    assert pending(account) == ('ai_input', {'feature_id': DOCUMENT, 'category': TEST})
    assert label(TEST) in screen(account)[0]


def test_the_service_behind_the_gate_comes_back_to_the_list(switch, member):
    account, telegram = member
    leave(telegram)
    chat = Chat(account)
    chat.do(text='/start')
    chat.tap('ai_tool', feature_id=DOCUMENT)
    assert GATE['en']['gate_one'] in chat.last()
    telegram.statuses = {'@docmaster_news': 'member'}
    chat.tap('channels_check')
    assert pending(account) == ('ai_category', {'feature_id': DOCUMENT})


def test_boshqa_meets_todays_checks_from_document_and_the_menu(switch, member):
    account, telegram = member
    leave(telegram)
    # /document drew today's question with no check, so it draws the list with none, and Boshqa adds none.
    chat = Chat(account)
    chat.do(text='/document')
    assert pending(account) == ('ai_category', {'feature_id': DOCUMENT})
    assert chat.tap('ai_tool', feature_id=DOCUMENT, category='other') == 0
    assert pending(account) == ('ai_input', {'feature_id': DOCUMENT})
    assert 'Describe what you want' in chat.last()
    # From the menu, the service tap meets the channels, as it always did.
    chat.do(text='/start')
    chat.tap('ai_tool', feature_id=DOCUMENT)
    assert GATE['en']['gate_one'] in chat.last()


def test_a_rate_limit_asks_the_category_again(customer, switch):
    chat = opened(customer)
    chat.tap('ai_tool', feature_id=DOCUMENT, category=TEST)
    cache.set(f'rate:bot_generation:{customer.pk}', 10, 60)
    chat.do(text=QUIZ)
    assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT, 'category': TEST})
    text, _, payloads, _ = screen(customer)
    assert label(TEST) in text and payloads[0][0] == {'feature_id': DOCUMENT, 'category': TEST}


def test_the_topic_question_keeps_the_category_and_todays_join_order(customer, switch, model):
    chat = opened(customer)
    chat.tap('ai_tool', feature_id=DOCUMENT, category=TEST)
    assert chat.do(text='Menga test kerak') == 1
    text, actions, payloads, _ = screen(customer)
    assert categories.get(TEST).raw['topic_prompt']['en'] in text
    assert UX['en']['ai_topic_question'] not in text
    assert '📝 Noted: “Menga test kerak”.' in text
    assert payloads[-2][0] == {'feature_id': DOCUMENT, 'category': TEST}
    assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT, 'category': TEST, 'brief': ['Menga test kerak']})
    assert chat.do(text='Fotosintez, 7-sinf biologiya, 20 ta savol') == 1
    assert 'Ready to start' in chat.last()
    data = latest(customer)
    assert data['prompt'] == 'Fotosintez, 7-sinf biologiya, 20 ta savol\nMenga test kerak'
    assert data['options']['category'] == TEST


def test_a_category_about_itself_is_never_asked_for_a_topic(customer, switch, model):
    opened(customer)
    tapped(customer, {'feature_id': DOCUMENT, 'category': GROUP})
    tapped(customer, {'feature_id': DOCUMENT, 'category': ARIZA})
    assert Chat(customer).do(text='Ariza kerak') == 1
    assert 'Ready to start' in screen(customer)[0]
    assert latest(customer)['options']['category'] == ARIZA


def test_the_review_and_a_failed_job_describe_again_in_the_category(customer, switch, settings):
    chat = opened(customer)
    chat.tap('ai_tool', feature_id=DOCUMENT, category=TEST)
    chat.do(text=QUIZ)
    _, actions, payloads, _ = screen(customer)
    assert actions[-1] == ['ai_tool', 'home'] and payloads[-1][0] == {'feature_id': DOCUMENT, 'category': TEST}
    tapped(customer, {'feature_id': DOCUMENT, 'category': TEST})
    assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT, 'category': TEST})

    # A job made in the category that the AI could not finish: its notice and its own screen.
    from tests.test_bot_prompt_feedback import local_notice
    draft = GenerationDraft.objects.filter(account=customer).latest('created_at')
    from telegram import generation as ai
    _, quote = ai.quote(customer, draft.id)
    settings.LOCAL_SYNC_JOBS = False
    job = ai.start(customer, quote.id)
    assert job.parameters['category'] == TEST
    Job.objects.filter(pk=job.pk).update(status='failed', error_code='provider_failed')
    job.refresh_from_db()
    _, actions = local_notice(job)
    assert actions[1] == ['ai_tool']
    assert BotCallback.objects.filter(account=customer, action='ai_tool', payload__notice_id__isnull=False,
                                      payload__category=TEST).exists()
    chat = Chat(customer)
    chat.do(text='/myfiles')
    chat.tap('job', job_id=str(job.id))
    assert screen(customer)[2][1][0] == {'feature_id': DOCUMENT, 'category': TEST}


def test_a_category_tap_is_counted_once_per_choice(customer, switch):
    chat = opened(customer)
    chat.tap('ai_tool', feature_id=DOCUMENT, category=GROUP)
    chat.tap('ai_tool', feature_id=DOCUMENT, category='other', group=GROUP)
    assert not AnalyticsEvent.objects.filter(event_type=categories.CHOSEN_EVENT).exists(), 'lists and Boshqa are not choices'
    opened(customer)
    chat = Chat(customer)
    tapped(customer, {'feature_id': DOCUMENT, 'category': TEST})
    tapped(customer, {'feature_id': DOCUMENT, 'category': TEST}, 'ai_examples')
    tapped(customer, {'feature_id': DOCUMENT, 'category': TEST})
    events = AnalyticsEvent.objects.filter(event_type=categories.CHOSEN_EVENT)
    assert [(event.feature_id, event.properties, event.channel) for event in events] == [
        (DOCUMENT, {'category': TEST}, 'bot')], 'back from its examples is the same choice'
    opened(customer, SLIDES)
    tapped(customer, {'feature_id': SLIDES, 'category': HIMOYA})
    assert AnalyticsEvent.objects.filter(event_type=categories.CHOSEN_EVENT).count() == 2


# --- Pieces ---------------------------------------------------------------------------------------


def test_the_question_state_without_a_category_is_what_it_was():
    assert ai_state(DOCUMENT) == {'feature_id': DOCUMENT}
    assert ai_state(DOCUMENT, None, brief=['x'], question='q') == {'feature_id': DOCUMENT, 'brief': ['x'], 'question': 'q'}
    assert ai_state(SLIDES, HIMOYA) == {'feature_id': SLIDES, 'category': HIMOYA}


def test_build_carries_a_live_category_and_drops_one_that_is_not(customer, switch):
    draft = generation.build(customer, DOCUMENT, QUIZ, category=TEST)
    assert unpack(draft.encrypted_data)['options']['category'] == TEST
    turn(live=[HIMOYA])
    draft = generation.build(customer, DOCUMENT, APPLICATION, category=ARIZA)
    assert 'category' not in unpack(draft.encrypted_data).get('options', {})
    draft = generation.build(customer, DOCUMENT, APPLICATION, category=HIMOYA)
    assert 'category' not in unpack(draft.encrypted_data).get('options', {}), 'another service’s category is never sent'


NEW_KEYS = ('ai_cat_choose', 'ai_cat_gone', 'ai_cat_files')


@pytest.mark.parametrize('key', NEW_KEYS)
def test_the_list_words_say_the_same_in_every_language(key):
    en, uz, ru = MESSAGES[key]
    slots = [sorted(re.findall(r'\{(\w+)\}', value)) for value in (en, uz, ru)]
    assert slots[0] == slots[1] == slots[2]
    assert not re.search('[а-яёўқғҳ]', uz.lower()) and not re.search('[а-яё]', en.lower())
    assert "'" not in uz and '`' not in uz, 'Uzbek writes ‘ and ’, never a typewriter apostrophe'
    assert not any(mark in value for value in (en, uz, ru) for mark in '<&'), f'{key} is shown as HTML'
