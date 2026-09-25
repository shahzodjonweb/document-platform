"""Making a document from the chat.

The bot used to hand every AI feature to the web app. It now runs them itself:
one menu, one message, one priced review, then the same job pipeline every
other tool uses. Editing a PDF is still web-only, and so are the three features
that build on something already authored there.
"""
import pytest
from django.utils import timezone

from apps.core.errors import DomainError
from apps.core.identity import resolve_account
from apps.core.models import BotConversation, BotDraft, Job, Quote
from apps.core.services import upload_file
from apps.studio.domain import GENERATION_IDS
from apps.studio.domain import unpack
from apps.studio.models import GenerationDraft
from operations.integrations import save_config
from telegram import generation
from telegram.local import dispatch_local

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]


@pytest.fixture
def customer(settings):
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    save_config('telegram', {'token': '', 'username': 'fixture_bot', 'webapp_url': 'https://pdfmaster.example/en/app'})
    account = resolve_account({'id': 980411, 'first_name': 'Generation test'}, is_test=True)
    BotConversation.objects.create(telegram_user_id=account.telegram_user_id, locale='en',
                                   language_selected_at=timezone.now())
    account.plan = 'premium'
    account.save(update_fields=['plan'])
    return account


def buttons(result):
    return [button for message in result['messages'] for row in message['buttons'] for button in row]


def labels(result):
    return [button['label'] for button in buttons(result)]


def token_for(result, label_fragment):
    for button in reversed(buttons(result)):
        if label_fragment.lower() in button['label'].lower() and button.get('callback_data'):
            return button['callback_data']
    raise AssertionError(f'No button matching {label_fragment!r} in {labels(result)}')


def tap(customer, result, label_fragment):
    return dispatch_local(customer, callback_data=token_for(result, label_fragment))


def body(result):
    return '\n'.join(message['text'] for message in result['messages'])


def test_the_menu_covers_every_generation_feature_exactly_once():
    listed = [fid for ids in generation.GROUPS.values() for fid in ids]
    assert sorted(listed) == sorted(GENERATION_IDS), 'every AI feature is reachable from a menu'
    assert len(listed) == len(set(listed)), 'and appears in exactly one group'


def test_a_document_is_made_from_one_chat_message(customer):
    menu = dispatch_local(customer, text='/ai')
    assert 'Documents & slides' in body(menu) + ' '.join(labels(menu))

    documents = tap(customer, menu, 'Documents & slides')
    assert 'Document from a topic' in ' '.join(labels(documents))

    asked = tap(customer, documents, 'Document from a topic')
    assert 'topic or instructions' in body(asked)
    conversation = BotConversation.objects.get(pk=customer.telegram_user_id)
    assert conversation.state == 'ai_input'
    assert conversation.prompt['feature_id'] == 'ai.pdf_topic'

    # Authoring the draft is free; the review screen is what precedes any spend.
    review = dispatch_local(customer, text='How tide tables are read, for a general audience.')
    assert GenerationDraft.objects.filter(account=customer, feature_id='ai.pdf_topic').count() == 1
    assert not Job.objects.filter(account=customer).exists(), 'nothing is submitted before the review'
    assert 'Ready to start' in body(review)
    assert 'Generate' in ' '.join(labels(review))

    tap(customer, review, 'Generate')
    job = Job.objects.get(account=customer)
    assert job.feature_id == 'ai.pdf_topic'
    assert job.origin_channel == 'bot'


def test_the_finished_document_is_sent_back_into_the_chat(customer):
    # conftest runs jobs synchronously, so the whole pipeline is exercised here.
    review = _review_for(customer, 'ai.pdf_topic', 'Documents & slides', 'Document from a topic',
                         'How tide tables are read, for a general audience.')
    tap(customer, review, 'Generate')
    job = Job.objects.get(account=customer)
    assert job.status == 'succeeded', job.error_code
    artifact = job.artifacts.select_related('file').first()
    assert artifact and artifact.file.name.endswith('.pdf')
    from apps.core.services import storage_path
    assert storage_path(artifact.file.object_key).read_bytes()[:5] == b'%PDF-'


def test_tapping_generate_twice_creates_one_job(customer):
    review = _review_for(customer, 'ai.pdf_topic', 'Documents & slides', 'Document from a topic',
                         'A short briefing about tide tables.')
    tap(customer, review, 'Generate')
    tap(customer, review, 'Generate')
    assert Job.objects.filter(account=customer).count() == 1, 'the quote-bound key holds'


def test_no_tool_forces_an_upload(customer):
    """A document is read when attached and never demanded."""
    documents = tap(customer, dispatch_local(customer, text='/ai'), 'Documents & slides')
    asked = tap(customer, documents, 'Document from sources')
    assert 'Paste or type your material' in body(asked)

    # Typed material alone is enough.
    review = dispatch_local(customer, text='Tide tables list high and low water for each day.\n\n'
                                          'They are published a year ahead for each port.')
    draft = GenerationDraft.objects.get(account=customer, feature_id='ai.pdf_sources')
    assert 'Ready to start' in body(review)
    assert not unpack(draft.encrypted_data)['source_ids'], 'nothing was uploaded'

    # And a document still works when there is one.
    stage_pdf(customer)
    documents = tap(customer, dispatch_local(customer, text='/ai'), 'Documents & slides')
    asked_again = tap(customer, documents, 'Document from sources')
    assert 'From your files: 1' in body(asked_again)
    dispatch_local(customer, text='Summarise these for me.')
    with_file = GenerationDraft.objects.filter(account=customer, feature_id='ai.pdf_sources').latest('created_at')
    assert unpack(with_file.encrypted_data)['source_ids']


def test_a_question_can_carry_its_own_material(customer):
    """study.pdf_qa answers from pasted text when no PDF is attached."""
    study = tap(customer, dispatch_local(customer, text='/study'), 'Questions about a PDF')
    assert 'Or attach a PDF first' in body(study)

    dispatch_local(customer, text='When is the spring tide?\n\nSpring tides follow the new and full moon.')
    payload = unpack(GenerationDraft.objects.get(account=customer, feature_id='study.pdf_qa').encrypted_data)
    assert payload['prompt'] == 'When is the spring tide?'
    assert payload['source_text'] == 'Spring tides follow the new and full moon.'
    assert not payload['source_ids']


def test_features_that_need_the_web_app_say_so_instead_of_failing(customer):
    documents = tap(customer, dispatch_local(customer, text='/ai'), 'Documents & slides')
    # They are last in their group: least useful here, so never in the way.
    rest = tap(customer, documents, 'More tools')
    assert any(label.startswith('🖥') for label in labels(rest)), 'web-only tools are marked'

    explained = tap(customer, rest, 'Rewrite content')
    assert 'web app' in body(explained)
    assert any(button.get('url') for button in buttons(explained)), 'and offer the link across'
    assert not GenerationDraft.objects.filter(account=customer).exists()

    for feature_id in generation.WEB_ONLY:
        with pytest.raises(DomainError) as caught:
            generation.available(customer, feature_id)
        assert caught.value.code == 'generation_web_only'


def test_the_web_link_carries_the_files_already_in_the_chat(customer):
    stage_pdf(customer)
    menu = dispatch_local(customer, text='/ai')
    link = next(button['url'] for button in buttons(menu) if button.get('url'))
    assert f'file_id={BotDraft.objects.get(account=customer).input_ids[0]}' in link


def test_a_tool_outside_the_plan_is_locked_rather_than_hidden(customer):
    customer.plan = 'free'
    customer.save(update_fields=['plan'])
    documents = tap(customer, dispatch_local(customer, text='/ai'), 'Documents & slides')
    locked = [label for label in labels(documents) if label.startswith('🔒')]
    assert locked, f'expected a locked tool on the free plan, saw {labels(documents)}'

    # Visible and explained, not hidden, and it cannot be started by tapping it.
    blocked = tap(customer, documents, locked[0].removeprefix('🔒 '))
    assert not GenerationDraft.objects.filter(account=customer).exists()
    assert 'plan' in body(blocked).lower()


def test_each_shortcut_opens_its_own_group_in_the_chat(customer):
    for command, heading in (('/create', 'Documents & slides'), ('/study', 'Studying'),
                             ('/school', 'Schoolwork'), ('/teach', 'Teaching')):
        result = dispatch_local(customer, text=command)
        assert heading in body(result), command
        assert not any((button.get('url') or '').endswith('/app/study') for button in buttons(result))


def test_long_menus_page_rather_than_truncate(customer):
    study = tap(customer, dispatch_local(customer, text='/ai'), 'Studying')
    first = [label for label in labels(study) if label not in ('◀️ Back', '▶️ More tools', '🏠 Main menu')]
    assert len(first) == generation.PAGE
    more = tap(customer, study, 'More tools')
    second = [label for label in labels(more) if label not in ('◀️ Back', '▶️ More tools', '🏠 Main menu')]
    assert second and not set(first) & set(second), 'the next page shows different tools'


def test_a_photo_tool_offers_to_continue_without_a_typed_message(customer):
    """Handwriting's whole input is the picture, so it must not wait for text."""
    study = tap(customer, dispatch_local(customer, text='/study'), 'Review handwritten notes')
    assert 'photo of the handwritten page' in body(study)
    assert 'Use this photo' not in ' '.join(labels(study)), 'nothing staged yet'

    stage_photo(customer)
    study = tap(customer, dispatch_local(customer, text='/study'), 'Review handwritten notes')
    assert 'Use this photo' in ' '.join(labels(study))

    # Transcription needs a vision model. Without one it says so rather than
    # leaving the customer on a screen with nothing that works.
    answered = tap(customer, study, 'Use this photo')
    assert 'Configure an AI provider' in body(answered)
    assert not GenerationDraft.objects.filter(account=customer).exists()


def test_the_review_screen_shows_the_cost_before_anything_runs(customer):
    """Generating spends AI credits. The customer must see that first."""
    save_config('ai', {'mode': 'openai', 'model': 'gpt-5.6-luna', 'api_key': 'sk-offline-test-only'})
    documents = tap(customer, dispatch_local(customer, text='/ai'), 'Documents & slides')
    tap(customer, documents, 'Document from a topic')
    review = dispatch_local(customer, text='How tide tables are read, for a general audience.')

    quote = Quote.objects.get(account=customer)
    assert quote.meters['ai_credits'] > 0, 'a real provider costs credits'
    assert f"AI credits: {quote.meters['ai_credits']}" in body(review), body(review)[-400:]
    assert 'Will use' in body(review) and 'Available' in body(review)
    assert not Job.objects.filter(account=customer).exists(), 'still nothing submitted'


def test_authoring_is_rate_limited_per_account(customer):
    from django.core.cache import cache
    cache.clear()
    for _ in range(10):
        generation.throttle(customer)
    with pytest.raises(DomainError) as caught:
        generation.throttle(customer)
    assert caught.value.code == 'rate_limited'


# --- helpers ---------------------------------------------------------------

def stage_pdf(account):
    from pypdf import PdfWriter
    import io
    from django.core.files.uploadedfile import SimpleUploadedFile
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    asset = upload_file(account, SimpleUploadedFile('notes.pdf', buffer.getvalue()), 'bot')
    draft, _ = BotDraft.objects.get_or_create(account=account, defaults={'state': 'collecting'})
    draft.input_ids = [str(asset.id)]
    draft.save(update_fields=['input_ids'])
    return asset


def stage_photo(account):
    import io as _io
    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image
    buffer = _io.BytesIO()
    Image.new('RGB', (64, 64), 'white').save(buffer, format='PNG')
    asset = upload_file(account, SimpleUploadedFile('page.png', buffer.getvalue()), 'bot')
    draft, _ = BotDraft.objects.get_or_create(account=account, defaults={'state': 'collecting'})
    draft.input_ids = [str(asset.id)]
    draft.save(update_fields=['input_ids'])
    return asset


def _review_for(account, feature_id, group_label, tool_label, prompt):
    menu = dispatch_local(account, text='/ai')
    group = tap(account, menu, group_label)
    tap(account, group, tool_label)
    return dispatch_local(account, text=prompt)
