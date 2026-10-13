"""A change is made from its request alone.

The review of a change used to carry the new-document controls: a ➖/➕ page
stepper, a deck theme and the language buttons. Customers took them for part of
the change, and a stepper next to "add a picture to every slide" invited a count
the request never asked for. A change now shows what it will do and nothing to
adjust; a new document keeps every control, and the old controls left in the
chat refuse a change.

A change asking only for the file in another format was priced as an AI edit
that changed nothing. Now it is no AI edit: a deck goes to PowerPoint → PDF, a
PDF asked for as slides is offered a new deck on its topic, and a file asked
for in the format it has is sent again.
"""
import pytest

from apps.core.models import BotDraft, FileAsset, Quote
from apps.studio.domain import DOCUMENT, SLIDES
from apps.studio.models import GenerationDraft
from operations.integrations import save_config
from telegram.local import dispatch_local
from tests.test_bot_generation import customer, free_customer, describe, tap  # noqa: F401

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]

FLAGS = {'🇬🇧', '🇺🇿', '🇷🇺'}
DECK = 'Tides\n\nThe moon pulls the sea.\n\nIt happens twice a day.\n\nSpring tides are the highest.'


def screen(result):
    """The bot's newest message as it reads now: (text, button labels)."""
    shown = [message for message in result['messages'] if message.get('direction') != 'inbound'][-1]
    return shown['text'], [button['label'] for row in shown['buttons'] for button in row]


def made(customer, description=DECK, service='Slides on a topic'):
    """A document generated and delivered in the chat, with its Make changes button."""
    save_config('ai', {'mode': 'local_fixture'})
    return tap(customer, describe(customer, description, service=service), 'Generate')


def change(customer, delivered, request):
    tap(customer, delivered, 'Make changes')
    return dispatch_local(customer, text=request)


@pytest.fixture
def converter(monkeypatch):
    """PowerPoint → PDF needs LibreOffice, which is not installed everywhere tests run."""
    monkeypatch.setattr('processors.engine.office_runtime', lambda: {'available': True, 'version': 'LibreOffice 24.2'})


def test_a_change_is_reviewed_without_the_new_document_controls(customer):
    delivered = made(customer)
    words, labels = screen(change(customer, delivered, 'Use a friendlier tone throughout.'))
    assert '✏️ Use a friendlier tone throughout.' in words, words
    assert 'Slides: ' in words, 'the count is still shown'
    assert '➖' not in labels and '➕' not in labels, labels
    assert not any('slides' in label and label[0].isdigit() for label in labels), 'no count button either'
    assert '🎨 Design and slides' not in labels and 'Design:' not in words, (labels, words)
    assert not FLAGS & {label.replace('✅ ', '') for label in labels}, labels
    assert labels[0] == '✨ Generate', labels
    assert '✏️ Make changes' in labels and 'Cancel' in ' '.join(labels), labels


def test_a_new_document_keeps_every_control(customer):
    save_config('ai', {'mode': 'openai', 'model': 'gpt-5.6-luna', 'api_key': 'sk-offline-test-only'})
    words, labels = screen(describe(customer, 'Volcanoes, 6 slides', service='Slides on a topic'))
    assert {'➖', '6 slides', '➕', '🎨 Design and slides'} <= set(labels), labels
    assert FLAGS <= {label.replace('✅ ', '') for label in labels}, labels
    assert 'Design: Auto' in words, words


def test_a_deck_with_question_slides_keeps_its_count_through_a_change(customer):
    """Question slides are slides: a change that keeps them is not "4 → 5"."""
    delivered = made(customer, f'{DECK}\n\nThree questions at the end.')
    before = GenerationDraft.objects.filter(account=customer, feature_id=SLIDES).latest('created_at')
    from apps.studio.domain import unpack
    slides = unpack(before.encrypted_data)['options']['length']
    words, _ = screen(change(customer, delivered, 'Use a friendlier tone throughout.'))
    assert f'Slides: {slides}' in words and '→' not in words, words


def test_pictures_a_plan_cannot_add_are_said_on_a_change(free_customer, monkeypatch):
    from tests.test_photos import KEY
    from telegram import generation
    save_config('pixabay', {'pixabay_key': KEY, 'enabled': 'true'})
    delivered = made(free_customer, 'Tides\n\nThe moon pulls the sea.', service='PDF on a topic')
    # The plan adds no pictures, and the change asks for three.
    monkeypatch.setattr(generation, 'images_wanted', lambda draft: (3, 0))
    words, labels = screen(change(free_customer, delivered, 'Rasmlar qo‘shing'))
    assert 'your plan does not add them' in words, words
    assert any(label.startswith('💎') and 'pictures' in label for label in labels), labels
    # With photos switched off no plan could add them: nothing is offered.
    save_config('pixabay', {'pixabay_key': KEY, 'enabled': ''})
    words, labels = screen(change(free_customer, delivered, 'Rasmlar qo‘shing'))
    assert 'pictures' not in words and not any('pictures' in label for label in labels), (words, labels)


def test_a_deck_asked_for_as_a_pdf_is_converted_not_rewritten(customer, converter):
    delivered = made(customer)
    deck = FileAsset.objects.filter(account=customer, metadata__kind='pptx').latest('created_at')
    drafts = GenerationDraft.objects.filter(account=customer).count()
    quotes = Quote.objects.filter(account=customer, feature_id=SLIDES).count()
    words, labels = screen(change(customer, delivered, 'Bu ilovada ochilmayapti pdf shaklida yubor'))
    assert GenerationDraft.objects.filter(account=customer).count() == drafts, 'no AI edit is made'
    assert Quote.objects.filter(account=customer, feature_id=SLIDES).count() == quotes, 'nor priced'
    tool = BotDraft.objects.get(account=customer)
    assert tool.feature_id == 'convert.pptx_to_pdf' and tool.input_ids == [str(deck.id)]
    assert 'PowerPoint → PDF' in words and 'comes back as a PDF' in words, words
    assert '▶️ Start' in labels, labels


def test_a_deck_no_longer_kept_offers_the_converter_for_the_copy_in_the_chat(customer, converter):
    from datetime import timedelta
    from django.utils import timezone
    delivered = made(customer)
    FileAsset.objects.filter(account=customer, metadata__kind='pptx').update(expires_at=timezone.now() - timedelta(minutes=1))
    drafts = GenerationDraft.objects.filter(account=customer).count()
    result = change(customer, delivered, 'pdf shaklida yubor')
    words, labels = screen(result)
    assert 'no longer kept' in words, words
    assert GenerationDraft.objects.filter(account=customer).count() == drafts
    opened = tap(customer, result, 'PowerPoint → PDF')
    words, _ = screen(opened)
    assert 'Send a PowerPoint file' in words, words
    assert BotDraft.objects.get(account=customer).feature_id == 'convert.pptx_to_pdf'


def test_a_pdf_asked_for_with_other_changes_is_an_ai_edit_that_says_the_deck_stays_a_deck(customer, converter):
    """The pictures are made; the PDF is not, and the review says so before paying."""
    delivered = made(customer)
    drafts = GenerationDraft.objects.filter(account=customer).count()
    words, labels = screen(change(customer, delivered, 'pdf qilib yubor va rasmlar qo‘sh'))
    assert GenerationDraft.objects.filter(account=customer).count() == drafts + 1
    assert '✏️ pdf qilib yubor va rasmlar qo‘sh' in words and '✨ Generate' in labels, (words, labels)
    assert 'The deck comes back as PowerPoint' in words and 'write just “PDF”' in words, words


def test_a_document_asked_for_as_slides_with_other_changes_says_it_stays_a_pdf(customer):
    delivered = made(customer, 'Tides\n\nThe moon pulls the sea.', service='PDF on a topic')
    words, labels = screen(change(customer, delivered, 'slayd qilib ber va rasmlar qo‘sh'))
    assert '✨ Generate' in labels, labels
    assert 'The document stays a PDF' in words and 'Slides on a topic' in words, words
    # A change that names no other format says nothing about one.
    words, _ = screen(change(customer, delivered, 'Use a friendlier tone throughout.'))
    assert 'stays a PDF' not in words and 'comes back as PowerPoint' not in words, words


def sent_files(customer, asset):
    from apps.commerce.models import LocalBotMessage
    return LocalBotMessage.objects.filter(account=customer, direction='outbound', asset=asset).count()


@pytest.mark.parametrize('description,service,request_text,kind', [
    ('Tides\n\nThe moon pulls the sea.', 'PDF on a topic', 'pdf shaklida yubor', 'pdf'),
    (DECK, 'Slides on a topic', 'pptx qilib ber', 'pptx'),
])
def test_a_file_asked_for_in_the_format_it_has_is_sent_again(customer, description, service, request_text, kind):
    """A PDF is already a PDF: the same file again, no AI edit priced for nothing."""
    delivered = made(customer, description, service=service)
    feature = DOCUMENT if kind == 'pdf' else SLIDES
    file = FileAsset.objects.filter(account=customer, metadata__kind=kind).latest('created_at')
    drafts = GenerationDraft.objects.filter(account=customer).count()
    quotes = Quote.objects.filter(account=customer, feature_id=feature).count()
    sent = sent_files(customer, file)
    result = change(customer, delivered, request_text)
    assert GenerationDraft.objects.filter(account=customer).count() == drafts, 'no AI edit is made'
    assert Quote.objects.filter(account=customer, feature_id=feature).count() == quotes, 'nor priced'
    assert sent_files(customer, file) == sent + 1, 'the same file is sent again'
    notes = [m['text'] for m in result['messages'] if m.get('direction') != 'inbound']
    assert any('already a ' + ('PDF' if kind == 'pdf' else 'PowerPoint') + ' file' in note for note in notes), notes[-3:]
    # The file sent again can be changed like the first.
    assert 'Make changes' in screen(result)[1][0], screen(result)


def test_a_file_asked_for_again_once_it_is_gone_says_so(customer):
    from datetime import timedelta
    from django.utils import timezone
    delivered = made(customer, 'Tides\n\nThe moon pulls the sea.', service='PDF on a topic')
    FileAsset.objects.filter(account=customer, metadata__kind='pdf').update(expires_at=timezone.now() - timedelta(minutes=1))
    drafts = GenerationDraft.objects.filter(account=customer).count()
    words, labels = screen(change(customer, delivered, 'pdf shaklida yubor'))
    assert 'no longer kept' in words and 'copy sent earlier in this chat' in words, words
    assert GenerationDraft.objects.filter(account=customer).count() == drafts
    assert '✏️ Make changes' in labels, labels


@pytest.mark.parametrize('request_text', ['pptx qilib ber', 'Taqdimot shaklida qilib bering', 'slayd qilib ber'])
def test_a_document_asked_for_as_slides_is_offered_a_new_deck_on_its_topic(customer, request_text):
    """A change cannot make slides of a PDF. A deck on the subject the document
    began with is offered instead, priced as a new deck only once asked for."""
    delivered = made(customer, 'Tides\n\nThe moon pulls the sea.', service='PDF on a topic')
    # Changed once already: the deck is made from the first description, not the change.
    changed = tap(customer, change(customer, delivered, 'Use a friendlier tone throughout.'), 'Generate')
    drafts = GenerationDraft.objects.filter(account=customer).count()
    quotes = Quote.objects.count()
    result = change(customer, changed, request_text)
    words, labels = screen(result)
    assert GenerationDraft.objects.filter(account=customer).count() == drafts, 'no AI edit is made'
    assert Quote.objects.count() == quotes, 'nothing is priced yet'
    assert 'can’t turn this PDF into slides' in words, words
    deck = tap(customer, result, 'Make slides on this topic')
    words, labels = screen(deck)
    from apps.studio.domain import unpack
    made_deck = GenerationDraft.objects.filter(account=customer, feature_id=SLIDES).latest('created_at')
    data = unpack(made_deck.encrypted_data)
    assert not data.get('revision') and 'The moon pulls the sea.' in data['source_text'], data
    assert request_text not in data['source_text'] + data['prompt']
    assert 'friendlier' not in data['source_text'] + data['prompt']
    assert '✨ Generate' in labels and '🎨 Design and slides' in labels, labels


def test_the_brief_of_a_change_is_the_description_it_began_from():
    from telegram.generation import brief_of
    assert brief_of({'prompt': 'pptx qilib ber', 'source_text': '',
                     'revision': {'original_prompt': 'Suv aylanishi, 6 sahifa'}}) == 'Suv aylanishi, 6 sahifa'
    assert brief_of({'prompt': 'Suv aylanishi, 6 sahifa', 'source_text': ''}) == 'Suv aylanishi, 6 sahifa'
    assert brief_of({'prompt': '', 'source_text': 'Tides'}) == 'Tides'


def test_a_format_only_change_the_server_refuses_is_said_plainly(customer, monkeypatch):
    """Should one reach the server, its refusal is the bot's own words, and the question again."""
    from apps.core.errors import DomainError
    from telegram import generation
    delivered = made(customer)
    monkeypatch.setattr(generation, 'asked_format', lambda account, draft_id, request: (None, None))

    def refuse(account, draft_id, request):
        raise DomainError('format_only_change')
    monkeypatch.setattr(generation, 'revise', refuse)
    result = change(customer, delivered, 'pdf shaklida yubor')
    shown = '\n'.join(m['text'] for m in result['messages'] if m.get('direction') != 'inbound')
    assert 'asks only for another file format' in shown, shown[-500:]
    assert 'What should change?' in screen(result)[0]


@pytest.mark.parametrize('locale,words', [('en', 'another file format'), ('uz', 'fayl formatini'), ('ru', 'другой формат')])
def test_safe_error_says_a_format_only_change_in_each_language(locale, words):
    import asyncio
    from types import SimpleNamespace
    from apps.core.errors import DomainError
    from telegram.bot import safe_error
    said = []

    async def answer(body, **kwargs):
        said.append(body)
    message = SimpleNamespace(from_user=SimpleNamespace(is_bot=False), answer=answer)
    asyncio.run(safe_error(message, SimpleNamespace(locale=locale, telegram_user_id=None), DomainError('format_only_change')))
    assert words in said[0], said


def old_button(customer, draft, action, payload):
    """A button on a review sent before a change lost its ➖/➕ and language buttons."""
    import secrets
    from datetime import timedelta
    from django.utils import timezone
    from apps.commerce.models import LocalBotMessage
    from apps.core.models import BotCallback
    token = secrets.token_urlsafe(12)
    BotCallback.objects.create(token=token, account=customer, action=action, payload={'draft_id': str(draft.id), **payload},
                               expires_at=timezone.now() + timedelta(minutes=30))
    LocalBotMessage.objects.create(account=customer, direction='outbound', text='Review', telegram_message_id=secrets.randbelow(10**6) + 1000,
                                   buttons=[[{'label': '➕', 'callback_data': token, 'url': None}]])
    return token


def test_old_count_and_language_buttons_on_a_change_open_the_menu(customer):
    from apps.studio.domain import unpack
    from telegram.bot import COPY
    delivered = made(customer)
    change(customer, delivered, 'Use a friendlier tone throughout.')
    draft = GenerationDraft.objects.filter(account=customer, feature_id=SLIDES).latest('created_at')
    before = unpack(draft.encrypted_data)
    assert before.get('revision')
    for action, payload in (('ai_length', {'pages': 2}), ('ai_locale', {'locale': 'ru'})):
        words, labels = screen(dispatch_local(customer, callback_data=old_button(customer, draft, action, payload)))
        assert COPY['en']['stale_button'] in words, words
        assert '✨ Slides on a topic · AI' in labels, labels
    draft.refresh_from_db()
    after = unpack(draft.encrypted_data)
    assert after['options'] == before['options'] and after['output_locale'] == before['output_locale']


def test_the_setup_screen_cannot_resize_or_restyle_a_change(customer):
    import json
    from apps.studio.domain import unpack
    from tests.test_platform import login_client
    delivered = made(customer)
    change(customer, delivered, 'Use a friendlier tone throughout.')
    draft = GenerationDraft.objects.filter(account=customer, feature_id=SLIDES).latest('created_at')
    before = unpack(draft.encrypted_data)['options']
    response = login_client(customer).post(f'/api/v1/generation/drafts/{draft.id}/setup',
                                           data=json.dumps({'pages': 7, 'deck_design': 'midnight'}),
                                           content_type='application/json')
    assert response.status_code == 409 and response.json()['error']['code'] == 'controls_expired', response.content
    draft.refresh_from_db()
    assert unpack(draft.encrypted_data)['options'] == before


def test_a_change_on_a_limited_plan_says_how_many_edits_its_file_has_used(free_customer):
    """Free has three AI edits a file; the review of a change says where the file stands."""
    delivered = made(free_customer)
    words, labels = screen(change(free_customer, delivered, 'Use a friendlier tone throughout.'))
    assert '✏️ Edits of this file: 0 of 3 used' in words, words
    assert 'AI documents this week' not in words, 'an edit is not one of the week’s documents'
    edited = tap(free_customer, change(free_customer, delivered, 'Use a friendlier tone throughout.'), 'Generate')
    words, _ = screen(change(free_customer, edited, 'Make it shorter.'))
    assert '✏️ Edits of this file: 1 of 3 used' in words, 'an edit of the edit counts against the same file'


def test_an_unlimited_plan_is_not_counted_on_a_change(customer):
    words, _ = screen(change(customer, made(customer), 'Use a friendlier tone throughout.'))
    assert 'Edits of this file' not in words


def test_a_file_with_no_edits_left_is_refused_before_the_change_is_written(free_customer):
    from apps.core.errors import DomainError
    from operations import plans as plan_settings
    from telegram import generation
    plan_settings.save('free', {'edits_per_file': 1})
    delivered = made(free_customer)
    original = GenerationDraft.objects.get(account=free_customer)
    edited = tap(free_customer, change(free_customer, delivered, 'Use a friendlier tone throughout.'), 'Generate')
    for screen_with_button in (edited, delivered):
        words, labels = screen(tap(free_customer, screen_with_button, 'Make changes'))
        assert 'AI edits are used up (1 per file)' in words, words
        assert '⭐ Plans' in labels, 'the way past the limit is offered'
    drafts = GenerationDraft.objects.count()
    with pytest.raises(DomainError) as refused:
        generation.revise(free_customer, original.id, 'Make it shorter.')
    assert refused.value.code == 'edit_limit' and GenerationDraft.objects.count() == drafts, 'no draft left behind'
