"""Making a document or a deck from the chat.

Two services and one message. The page count, the questions and the tone all
come out of what the customer writes, so these tests are as much about what the
bot stops asking for as about what it produces.
"""
import pytest
from django.utils import timezone

from apps.core.errors import DomainError
from apps.core.identity import resolve_account
from apps.core.models import BotConversation, BotDraft, Job, Quote
from apps.core.services import upload_file
from apps.studio.domain import DOCUMENT, GENERATION_IDS, SLIDES, unpack
from apps.studio.models import GenerationDraft
from apps.studio.pages import requested_pages
from apps.commerce.services import create_invoice, sandbox_pay
from operations.integrations import save_config
from telegram import generation
from telegram.local import dispatch_local
from telegram.ux_copy import PROMPT_EXAMPLES

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]


@pytest.fixture
def customer(settings):
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    save_config('telegram', {'token': '', 'username': 'fixture_bot', 'webapp_url': 'https://pdfmaster.example/en/app'})
    account = resolve_account({'id': 980411, 'first_name': 'Generation test'}, is_test=True)
    BotConversation.objects.create(telegram_user_id=account.telegram_user_id, locale='en',
                                   language_selected_at=timezone.now())
    # A bare plan field is reset by the entitlement refresh, so buy the period.
    invoice, _ = create_invoice(account, 'premium', f'bot-generation-{account.id}')
    sandbox_pay(account, invoice.id)
    account.refresh_from_db()
    assert account.plan == 'premium'
    return account


def buttons(result):
    return [button for message in result['messages'] for row in message['buttons'] for button in row]


def labels(result):
    return [button['label'] for button in buttons(result)]


def tap(customer, result, fragment):
    for button in reversed(buttons(result)):
        if fragment.lower() in button['label'].lower() and button.get('callback_data'):
            return dispatch_local(customer, callback_data=button['callback_data'])
    raise AssertionError(f'No button matching {fragment!r} in {labels(result)}')


def body(result):
    return '\n'.join(message['text'] for message in result['messages'])


def latest(account, feature_id=DOCUMENT):
    return unpack(GenerationDraft.objects.filter(account=account, feature_id=feature_id)
                  .latest('created_at').encrypted_data)


def describe(customer, description, service='PDF on a topic'):
    tap(customer, dispatch_local(customer, text='/ai'), service)
    return dispatch_local(customer, text=description)


SERVICE_LABELS = ['✨ PDF on a topic · AI', '✨ Slides on a topic · AI']


def test_the_two_services_lead_the_menus_with_no_folder_to_open(customer):
    """They are two services, not a category worth a folder of its own.

    A folder holding exactly two things costs a tap and hides them; both are
    offered directly, at the top, on the main menu and in All tools.
    """
    start = dispatch_local(customer, text='/ai')
    assert labels(start)[:2] == SERVICE_LABELS, labels(start)
    assert not any('create with ai' in label.lower() for label in labels(start))
    # Both say they are the AI feature. Without the folder that said it for them,
    # nothing else on the menu distinguishes them from the file tools.
    file_tools = [label for label in labels(start) if label not in SERVICE_LABELS]
    for label in SERVICE_LABELS:
        assert label.startswith('✨') and label.endswith('AI')
    assert not any('✨' in label for label in file_tools), file_tools
    assert set(generation.SERVICES) == GENERATION_IDS == {DOCUMENT, SLIDES}

    tools = tap(customer, start, 'All tools')
    assert labels(tools)[:2] == SERVICE_LABELS, labels(tools)

    # And one tap reaches the description, not a menu of two.
    asked = tap(customer, dispatch_local(customer, text='/ai'), 'PDF on a topic')
    conversation = BotConversation.objects.get(pk=customer.telegram_user_id)
    assert conversation.state == 'ai_input' and conversation.prompt['feature_id'] == DOCUMENT
    assert 'Describe what you want' in body(asked)


def test_one_message_is_the_whole_brief(customer):
    asked = tap(customer, dispatch_local(customer, text='/ai'), 'PDF on a topic')
    assert 'Describe what you want' in body(asked)
    assert 'how many pages' in body(asked)
    conversation = BotConversation.objects.get(pk=customer.telegram_user_id)
    assert conversation.state == 'ai_input'
    assert conversation.prompt['feature_id'] == DOCUMENT

    review = dispatch_local(customer, text='A 4 page introduction to tide tables for beginners.')
    assert not Job.objects.filter(account=customer).exists(), 'nothing runs before the review'
    assert 'Pages: 4' in body(review), body(review)[-300:]

    tap(customer, review, 'Generate')
    job = Job.objects.get(account=customer)
    assert job.feature_id == DOCUMENT and job.origin_channel == 'bot'


@pytest.mark.parametrize('description,expected', [
    ('A 7 page guide to tide tables', 7),
    ('Tide tables explained simply', 5),
    ('Suv qalqishi haqida 3 sahifa', 3),
    ('Отчёт о приливах на 6 страниц', 6),
])
def test_the_page_count_comes_out_of_the_description(customer, description, expected):
    # With a model to write them, an unasked-for count is the default of five.
    save_config('ai', {'mode': 'openai', 'model': 'gpt-5.6-luna', 'api_key': 'sk-offline-test-only'})
    review = describe(customer, description)
    assert f'Pages: {expected}' in body(review), body(review)[-300:]
    assert latest(customer)['options']['length'] == expected


@pytest.fixture
def free_customer(settings):
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    save_config('telegram', {'token': '', 'username': 'fixture_bot', 'webapp_url': 'https://pdfmaster.example/en/app'})
    account = resolve_account({'id': 980412, 'first_name': 'Free plan'}, is_test=True)
    BotConversation.objects.create(telegram_user_id=account.telegram_user_id, locale='en',
                                   language_selected_at=timezone.now())
    assert account.plan == 'free'
    return account


def test_a_request_beyond_the_plan_is_said_out_loud(free_customer):
    from apps.core.policy import plan_limits
    allowed = plan_limits(free_customer)['max_generated_pdf_pages']
    review = describe(free_customer, 'A 20 page report on tide tables.')
    assert allowed < 20, 'this test needs a request the free plan has to clamp'
    assert f'Pages: {allowed}' in body(review), 'the free plan gets what the free plan allows'
    assert '20 asked for' in body(review), 'and the clamp is shown, not hidden'
    assert latest(free_customer)['options']['requested_pages'] == 20


def test_questions_are_only_priced_when_they_are_asked_for(customer):
    save_config('ai', {'mode': 'openai', 'model': 'gpt-5.6-luna', 'api_key': 'sk-offline-test-only'})
    describe(customer, 'A 3 page guide to tide tables.')
    plain = Quote.objects.latest('created_at')
    assert latest(customer)['options']['question_count'] == 0

    describe(customer, 'A 3 page guide to tide tables with 10 questions at the end.')
    assert latest(customer)['options']['question_count'] == 10
    assert Quote.objects.latest('created_at').meters['ai_credits'] > plain.meters['ai_credits']


def test_the_review_screen_shows_the_cost_before_anything_runs(customer):
    save_config('ai', {'mode': 'openai', 'model': 'gpt-5.6-luna', 'api_key': 'sk-offline-test-only'})
    review = describe(customer, 'A 5 page briefing on tide tables.')

    quote = Quote.objects.get(account=customer)
    assert quote.meters['ai_credits'] > 0, 'a real provider costs credits'
    assert f"AI credits: {quote.meters['ai_credits']}" in body(review)
    assert 'Will use' in body(review) and 'Available' in body(review)
    assert not Job.objects.filter(account=customer).exists()


def test_tapping_generate_twice_creates_one_job(customer):
    review = describe(customer, 'A 2 page briefing on tide tables.')
    tap(customer, review, 'Generate')
    tap(customer, review, 'Generate')
    assert Job.objects.filter(account=customer).count() == 1, 'the quote-bound key holds'


def test_the_finished_pdf_is_really_produced(customer):
    """conftest runs jobs synchronously, so this is the real pipeline."""
    material = ' '.join(['tide'] * 390)
    review = describe(customer, f'A 1 page guide to tide tables.\n\n{material}')
    tap(customer, review, 'Generate')

    job = Job.objects.get(account=customer)
    assert job.status == 'succeeded', job.error_code
    artifact = job.artifacts.select_related('file').get()
    assert artifact.file.name.endswith('.pdf') and artifact.file.page_count == 1


def test_examples_are_offered_in_every_language(customer):
    listing = dispatch_local(customer, text='/examples')
    assert 'Write it like this' in body(listing)
    for feature_id in generation.SERVICES:
        assert PROMPT_EXAMPLES[feature_id][0][0] in body(listing)

    # Every example is a real brief: each one names a page count in its own
    # language, so a customer copying it gets exactly what it says.
    for feature_id, rows in PROMPT_EXAMPLES.items():
        for row in rows:
            for sample in row:
                assert requested_pages(sample), f'{feature_id}: "{sample[:44]}" names no page count'


def test_a_service_outside_the_plan_cannot_be_started(customer):
    from apps.core.policy import FEATURES
    original = FEATURES[SLIDES]['plans']['premium']
    FEATURES[SLIDES]['plans']['premium'] = 'not_included'
    try:
        with pytest.raises(DomainError) as caught:
            generation.available(customer, SLIDES)
        assert caught.value.code == 'feature_not_in_plan'
    finally:
        FEATURES[SLIDES]['plans']['premium'] = original


def test_a_delivered_document_can_be_changed_by_asking(customer):
    """The customer says what should change, in the same way they said what to make."""
    material = ' '.join(['tide'] * 390)
    review = describe(customer, f'A 1 page guide to tide tables.\n\n{material}')
    delivered = tap(customer, review, 'Generate')
    assert 'Make changes' in ' '.join(labels(delivered)), labels(delivered)

    asked = tap(customer, delivered, 'Make changes')
    assert 'What should change?' in body(asked)
    assert 'stays exactly as it is' in body(asked)
    conversation = BotConversation.objects.get(pk=customer.telegram_user_id)
    assert conversation.state == 'ai_revise'

    before = GenerationDraft.objects.filter(account=customer).count()
    changed = dispatch_local(customer, text='Use a friendlier tone throughout.')
    assert GenerationDraft.objects.filter(account=customer).count() == before + 1
    assert 'Use a friendlier tone throughout.' in body(changed), 'the review names the change'
    assert 'Pages: 1' in body(changed), 'a change keeps the length unless it asks otherwise'

    jobs_before = Job.objects.filter(account=customer).count()
    tap(customer, changed, 'Generate')
    assert Job.objects.filter(account=customer).count() == jobs_before + 1


def test_a_file_tool_result_offers_no_change_button(customer):
    """There is nothing to reword in a merged PDF."""
    from telegram.delivery import revisable_draft
    from apps.core.models import Artifact
    stage_pdf(customer)
    describe(customer, 'A 1 page guide.')
    artifact = Artifact.objects.filter(job__account=customer).first()
    if artifact:
        artifact.job.feature_id = 'pdf.merge'
        artifact.job.save(update_fields=['feature_id'])
        delivery = type('D', (), {'artifact': artifact, 'account': customer})()
        assert revisable_draft(delivery) == ''


def test_authoring_is_rate_limited_per_account(customer):
    from django.core.cache import cache
    cache.clear()
    for _ in range(10):
        generation.throttle(customer)
    with pytest.raises(DomainError) as caught:
        generation.throttle(customer)
    assert caught.value.code == 'rate_limited'


def test_local_authoring_follows_the_material_instead_of_inventing_pages(customer):
    """There is no model in local mode, so five pages would be four blank ones."""
    review = describe(customer, 'Tide tables explained simply.')
    assert 'Pages: 1' in body(review)
    assert latest(customer)['options']['requested_pages'] is None


def test_a_document_still_reads_a_pdf_when_one_is_sent(customer):
    stage_pdf(customer)
    describe(customer, 'A 2 page summary of the attached file.')
    assert latest(customer)['source_ids'], 'the staged PDF is used'


def stage_pdf(account):
    import io
    from django.core.files.uploadedfile import SimpleUploadedFile
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    asset = upload_file(account, SimpleUploadedFile('notes.pdf', buffer.getvalue()), 'bot')
    draft, _ = BotDraft.objects.get_or_create(account=account, defaults={'state': 'collecting'})
    draft.input_ids = [str(asset.id)]
    draft.save(update_fields=['input_ids'])
    return asset
