"""The review screen is where a misread request gets put right, before paying.

The first ad wave showed counts read wrong ("10 varoqlik" → 5), languages not
honoured ("ingliz tilida"), and limits met with no way forward. The screen now
shows the count, the language and the plan's limits, each fixable in one tap.
"""
import pytest

from apps.core.models import BotConversation
from apps.studio.domain import DOCUMENT, SLIDES
from apps.studio.models import GenerationDraft
from operations.integrations import save_config
from tests.test_bot_generation import body, buttons, customer, describe, free_customer, labels, latest, tap  # noqa: F401
from telegram.local import dispatch_local

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]


@pytest.fixture(autouse=True)
def model():
    save_config('ai', {'mode': 'openai', 'model': 'gpt-5.6-luna', 'api_key': 'sk-offline-test-only'})


def stepper(result):
    """The last review's [➖] [count] [➕] row, as labels."""
    screen = [message for message in result['messages'] if message.get('direction') != 'inbound'][-1]
    return next([button['label'] for button in row] for row in screen['buttons']
                if any(button['label'] in ('➖', '➕') for button in row))


def test_the_count_can_be_changed_before_paying(customer):
    review = describe(customer, 'A 4 page introduction to tide tables.')
    assert 'Pages: 4' in body(review)
    assert stepper(review) == ['➖', '4 pages', '➕']
    longer = tap(customer, review, '➕')
    assert 'Pages: 5' in body(longer), body(longer)[-400:]
    assert stepper(longer) == ['➖', '5 pages', '➕']
    assert latest(customer)['options']['length'] == 5
    assert len(latest(customer)['content']['sections']) == 5
    shorter = tap(customer, longer, '➖')
    assert 'Pages: 4' in body(shorter)
    # The count in the middle only shows it: a tap changes nothing.
    same = tap(customer, shorter, '4 pages')
    assert latest(customer)['options']['length'] == 4 and stepper(same) == ['➖', '4 pages', '➕']
    # The chosen count stays chosen: it is not read again from the description.
    assert latest(customer)['options']['pages'] == 4


def test_a_deck_is_counted_in_slides(customer):
    review = describe(customer, '6 ta slayd: suv aylanishi', service='Slides on a topic')
    assert 'Slides: 6' in body(review), body(review)[-400:]
    assert stepper(review) == ['➖', '6 slides', '➕']


def test_the_count_is_said_in_each_language():
    from telegram.ux_copy import counted
    assert [counted('en', n, 'slide') for n in (1, 10)] == ['1 slide', '10 slides']
    assert [counted('uz', n, 'page') for n in (1, 10)] == ['1 sahifa', '10 sahifa']
    assert [counted('ru', n, 'slide') for n in (1, 3, 5, 11, 12, 21, 22, 25)] == [
        '1 слайд', '3 слайда', '5 слайдов', '11 слайдов', '12 слайдов', '21 слайд', '22 слайда', '25 слайдов']
    assert counted('ru', 10, 'page') == '10 страниц' and counted('ru', 2, 'page') == '2 страницы'


def test_at_the_page_ceiling_no_plan_is_sold_on_pages(free_customer):
    """Every plan has the same page ceiling (owner's decision, 2026-10-16), so a
    count past it is said as ours, and no bigger plan is offered for it."""
    from apps.core.policy import limits_for_plan, plan_limits
    allowed = plan_limits(free_customer)['max_generated_pdf_pages']
    assert allowed == limits_for_plan('premium')['max_generated_pdf_pages'], 'Free has Premium’s ceiling'
    review = describe(free_customer, f'A {allowed + 5} page report on tide tables.')
    assert f'Pages: {allowed}' in body(review)
    assert f'{allowed + 5} asked for; {allowed} is the most we make in one go.' in body(review), body(review)[-400:]
    assert 'plan' not in body(review).split('Pages:')[1].split('Language:')[0].lower()
    assert not any(label.startswith('➕') for label in labels(review)), 'no more pages than the ceiling'
    assert not any(label.startswith('💎') for label in labels(review)), labels(review)


def test_no_plan_is_offered_for_pages_slides_or_pictures_even_if_one_gives_more(free_customer):
    """Plans differ only in their weekly limits, so the review never sells pages,
    slides or pictures, not even when a stored override still gives Premium more."""
    from apps.core.policy import limits_for_plan, plan_limits
    from operations import plans as plan_settings
    from operations.integrations import save_config as configure
    from operations.models import IntegrationConfig
    from tests.test_photos import KEY
    import telegram.generation as generation
    import telegram.ux_copy as ux_copy
    configure('pixabay', {'pixabay_key': KEY, 'enabled': 'true'})
    allowed, cap = plan_limits(free_customer)['max_generated_pdf_pages'], plan_limits(free_customer)['max_deck_images']
    IntegrationConfig.objects.update_or_create(pk=plan_settings.KEY, defaults={'configuration': {'premium': {
        'max_generated_pdf_pages': allowed + 20, 'max_generated_slides': 120, 'max_deck_images': 40}}})
    assert limits_for_plan('premium')['max_generated_pdf_pages'] == allowed + 20
    review = describe(free_customer, f'A {allowed + 10} page report on tide tables.')
    assert f'Pages: {allowed}' in body(review), body(review)[-400:]
    assert not any(label.startswith('💎') for label in labels(review)), labels(review)
    deck = describe(free_customer, 'Vulqonlar haqida 30 ta slayd, har bir slaydda rasm bo‘lsin', service='Slides on a topic')
    assert f'a deck gets up to {cap}' in body(deck), body(deck)[-500:]
    assert not any(label.startswith('💎') for label in labels(deck)), labels(deck)
    assert not hasattr(generation, 'next_plan')
    assert not {'ai_more_pages', 'ai_more_slides', 'ai_more_images'} & set(ux_copy.MESSAGES)


def test_the_language_is_shown_and_switched_in_one_tap(customer):
    review = describe(customer, 'A 3 page guide to tide tables.')
    assert 'Language: 🇬🇧 English' in body(review), body(review)[-400:]
    switched = tap(customer, review, '🇷🇺')
    assert 'Language: 🇷🇺 Русский' in body(switched)
    assert latest(customer)['output_locale'] == 'ru'
    assert any(label == '✅ 🇷🇺' for label in labels(switched)), labels(switched)


def test_a_change_that_alters_the_count_says_so(customer):
    """A change request that turns a deck of N into M shows N → M before paying."""
    save_config('ai', {'mode': 'local_fixture'})
    material = ' '.join(['tide'] * 390)
    review = describe(customer, f'A 2 page guide to tide tables.\n\n{material}\n\n{material}')
    delivered = tap(customer, review, 'Generate')
    asked = tap(customer, delivered, 'Make changes')
    assert 'What should change?' in body(asked)
    changed = dispatch_local(customer, text='Make it 4 pages.')
    assert 'Pages: 2 → 4' in body(changed), body(changed)[-400:]
    # And a picture on every page is not a count of one.
    asked = tap(customer, delivered, 'Make changes')
    kept = dispatch_local(customer, text='Har 1ta sahifaga rasm qo‘shilsin.')
    latest_screen = [m['text'] for m in kept['messages'] if m.get('direction') != 'inbound'][-1]
    assert 'Pages: 2' in latest_screen and '→' not in latest_screen, latest_screen


def test_a_chosen_count_is_checked_and_held_to_the_plan(free_customer):
    from apps.core.errors import DomainError
    from apps.core.policy import plan_limits
    from apps.studio.domain import create_draft, unpack
    allowed = plan_limits(free_customer)['max_generated_pdf_pages']
    draft = create_draft(free_customer, {'prompt': 'A 3 page guide to tides', 'options': {'pages': 50}})
    options = unpack(draft.encrypted_data)['options']
    assert (options['length'], options['requested_pages']) == (allowed, 50), 'the choice wins over the description'
    for wrong in ('5', 0, 201, 2.5, True):
        with pytest.raises(DomainError, match='invalid_parameters'):
            create_draft(free_customer, {'prompt': 'A guide to tides', 'options': {'pages': wrong}})


def test_pictures_beyond_the_cap_are_said_but_no_plan_is_offered(free_customer):
    """The picture cap is the same on every plan: it is said, never sold."""
    from apps.core.policy import plan_limits
    from operations.integrations import save_config as configure
    from tests.test_photos import KEY
    configure('pixabay', {'pixabay_key': KEY, 'enabled': 'true'})
    cap = plan_limits(free_customer)['max_deck_images']
    assert 0 < cap < 15, 'this test needs a cap below the slides asked for'
    review = describe(free_customer, 'Vulqonlar haqida 15 ta slayd, har bir slaydda rasm bo‘lsin',
                      service='Slides on a topic')
    assert f'You asked for pictures; a deck gets up to {cap}.' in body(review), body(review)[-500:]
    assert 'your plan' not in body(review)
    assert not any(label.startswith('💎') for label in labels(review)), labels(review)


def test_our_own_example_sent_back_is_caught(customer):
    from apps.studio.models import GenerationDraft
    from telegram.ux_copy import PROMPT_EXAMPLES
    example = PROMPT_EXAMPLES['ai.pptx'][0][0]
    caught = describe(customer, example, service='Slides on a topic')
    assert 'That is one of our examples' in body(caught), body(caught)[-300:]
    assert not GenerationDraft.objects.filter(account=customer).exists(), 'nothing is built from it'
    # The question is still open: their own description goes straight through.
    own = dispatch_local(customer, text='10 slides on volcanoes for year 8, 3 questions at the end.')
    assert 'Slides: 10' in body(own), body(own)[-300:]


def test_slides_asked_of_the_pdf_service_are_offered_as_slides(customer):
    review = describe(customer, 'Mustaqil ish 10 ta slayd kerak — neft va gaz quduqlari')
    assert 'You asked for slides' in body(review), body(review)[-400:]
    switched = tap(customer, review, 'Make slides instead')
    assert 'Slides: 10' in body(switched), body(switched)[-400:]
    assert latest(customer, 'ai.pptx')['options']['length'] == 10
    plain = describe(customer, 'A 3 page guide to tide tables.')
    assert not any('instead' in label for label in labels(plain))


def test_a_deck_review_opens_the_setup_screen(customer):
    review = describe(customer, 'Tides for a school lesson', service='Slides on a topic')
    assert 'Design: Auto' in body(review), body(review)[-400:]
    draft = GenerationDraft.objects.filter(account=customer, feature_id=SLIDES).latest('created_at')
    (setup,) = [button for button in buttons(review) if button['label'] == '🎨 Design and slides']
    # An https Mini App: the simulator records its address as the button's link.
    assert setup['url'] == f'https://pdfmaster.example/en/app/deck-setup?draft={draft.id}'
    shown = BotConversation.objects.get(telegram_user_id=customer.telegram_user_id).review
    assert shown['draft_id'] == str(draft.id) and shown['local'] is True
    # A document has no design to choose.
    document = describe(customer, 'A 3 page guide to tide tables.')
    assert '🎨 Design and slides' not in labels(document)[-8:]


def test_the_setup_screen_beats_the_description_and_redraws_the_review(customer):
    import json
    from tests.test_platform import login_client
    review = describe(customer, 'A dark green deck, 12 slides about tides', service='Slides on a topic')
    assert 'Slides: 12' in body(review)
    draft = GenerationDraft.objects.filter(account=customer, feature_id=SLIDES).latest('created_at')
    client = login_client(customer)
    response = client.post(f'/api/v1/generation/drafts/{draft.id}/setup',
                           data=json.dumps({'pages': 7, 'deck_design': 'midnight'}), content_type='application/json')
    assert response.status_code == 200, response.content
    result = response.json()
    options = latest(customer, SLIDES)['options']
    assert options['length'] == 7 and options['template_style']['deck_design'] == 'midnight'
    assert 'deck_theme' not in options['template_style'] and not options['template_style'].get('accent_fixed')
    assert result['draft']['options']['length'] == 7 and result['quote']['id']
    # The review in the chat is the new one, edited in place, and pays for the new quote.
    screen = BotConversation.objects.get(telegram_user_id=customer.telegram_user_id).review
    from apps.commerce.models import LocalBotMessage
    from apps.core.models import BotCallback
    message = LocalBotMessage.objects.get(account=customer, direction='outbound', telegram_message_id=screen['message_id'])
    assert 'Slides: 7' in message.text and 'Design: Midnight' in message.text, message.text
    generate = [button for row in message.buttons for button in row if button['label'] == '✨ Generate']
    assert BotCallback.objects.get(token=generate[0]['callback_data']).payload['quote_id'] == result['quote']['id']


def test_the_setup_screen_refuses_what_it_does_not_offer(customer):
    import json
    from tests.test_platform import login_client
    describe(customer, 'Tides', service='Slides on a topic')
    deck = GenerationDraft.objects.filter(account=customer, feature_id=SLIDES).latest('created_at')
    describe(customer, 'A 3 page guide to tide tables.')
    document = GenerationDraft.objects.filter(account=customer, feature_id=DOCUMENT).latest('created_at')
    client = login_client(customer)
    for draft, payload in ((deck, {'deck_design': 'nope'}), (deck, {'pages': '7'}), (deck, {'colour': 'red'}),
                           (deck, {}), (document, {'pages': 4})):
        response = client.post(f'/api/v1/generation/drafts/{draft.id}/setup', data=json.dumps(payload),
                               content_type='application/json')
        assert response.status_code == 400, (payload, response.content)
    designs = client.get('/api/v1/studio/deck-designs?locale=ru').json()
    assert designs['default_pages'] == 10 and designs['categories'][0]['name'] == 'Классика'


def test_once_generate_is_tapped_the_setup_screen_cannot_reopen_the_review(customer):
    import json
    from apps.core.services import submit_job
    from apps.studio.domain import generation_quote
    from tests.test_platform import login_client
    save_config('ai', {'mode': 'local_fixture'})
    from telegram.commands import COMMANDS_VERSION, MENU_KEY
    review = describe(customer, 'Tides\n\nThe moon pulls the sea.\n\nIt happens twice a day.', service='Slides on a topic')
    shown = BotConversation.objects.get(telegram_user_id=customer.telegram_user_id).review
    # The chat's menu version shares the field and survives the review being stored.
    assert shown['draft_id'] and shown[MENU_KEY] == COMMANDS_VERSION
    tap(customer, review, 'Generate')
    # The review became the job's status; it is never redrawn as a review again.
    # Only the menu version stays.
    assert BotConversation.objects.get(telegram_user_id=customer.telegram_user_id).review == {MENU_KEY: COMMANDS_VERSION}
    # A deck still queued runs from its draft as quoted: the setup screen may not change it.
    describe(customer, 'Volcanoes\n\nMagma rises.\n\nIt erupts.', service='Slides on a topic')
    draft = GenerationDraft.objects.filter(account=customer, feature_id=SLIDES).latest('created_at')
    quote = generation_quote(customer, draft.id, draft.version)
    submit_job(customer, quote.id, 'setup-while-queued', 'bot')
    response = login_client(customer).post(f'/api/v1/generation/drafts/{draft.id}/setup',
                                           data=json.dumps({'pages': 7, 'deck_design': 'royal'}),
                                           content_type='application/json')
    assert response.status_code == 409 and response.json()['error']['code'] == 'generation_running'
    draft.refresh_from_db()
    assert 'deck_design' not in latest(customer, SLIDES)['options']


def test_a_queued_deck_cannot_be_changed_and_a_made_one_cannot_be_restyled(customer):
    import json
    from apps.core.services import submit_job
    from apps.studio.domain import generation_quote
    from telegram.bot import forget_review
    from tests.test_platform import login_client
    review = describe(customer, 'Volcanoes, 6 slides', service='Slides on a topic')
    draft = GenerationDraft.objects.filter(account=customer, feature_id=SLIDES).latest('created_at')
    job, _ = submit_job(customer, generation_quote(customer, draft.id, draft.version).id, 'queued-deck', 'bot')
    # The review's count button cannot change a draft its queued job runs from.
    refused = tap(customer, review, '➕')
    assert 'already being made' in body(refused), body(refused)[-300:]
    assert latest(customer, SLIDES)['options']['length'] == 6
    # Once it is made, the setup screen does not restyle it either.
    job.status = 'succeeded'
    job.save(update_fields=['status'])
    response = login_client(customer).post(f'/api/v1/generation/drafts/{draft.id}/setup',
                                           data=json.dumps({'deck_design': 'royal'}), content_type='application/json')
    assert response.status_code == 409 and response.json()['error']['code'] == 'generation_finished'
    # Generating one draft does not forget the review since shown for another.
    describe(customer, 'Rivers, 5 slides', service='Slides on a topic')
    newer = BotConversation.objects.get(telegram_user_id=customer.telegram_user_id).review
    assert newer['draft_id'] != str(draft.id)
    forget_review(customer, draft.id)
    assert BotConversation.objects.get(telegram_user_id=customer.telegram_user_id).review == newer


def compress(customer):
    """A PDF sent and Compress chosen: the file task's screen, ready to start, as (text, labels)."""
    from django.core.files.uploadedfile import SimpleUploadedFile
    from tests.test_manual_payments import pdf
    sent = dispatch_local(customer, uploaded=SimpleUploadedFile('notes.pdf', pdf(), 'application/pdf'))
    result = tap(customer, sent, 'Compress')
    shown = [message for message in result['messages'] if message.get('direction') != 'inbound'][-1]
    return result, shown['text'], [button['label'] for row in shown['buttons'] for button in row]


def test_a_file_task_on_free_says_where_the_week_stands(free_customer):
    _, words, buttons_shown = compress(free_customer)
    assert 'File tools this week: 0 of 15' in words, words
    assert 'Will use' not in words and 'Page units' not in words
    assert '▶️ Start' in buttons_shown


def test_a_used_up_week_offers_the_plans_in_place_of_start(free_customer):
    from operations import plans as plan_settings
    plan_settings.save('free', {'weekly_file_jobs': 1})
    tap(free_customer, compress(free_customer)[0], 'Start')
    _, words, buttons_shown = compress(free_customer)
    assert 'File tools this week: 1 of 1' in words and 'file tasks are used up' in words, words
    assert '⭐ Plans' in buttons_shown and '▶️ Start' not in buttons_shown


def test_unlimited_file_tools_show_no_count(customer):
    _, words, buttons_shown = compress(customer)
    assert 'File tools this week' not in words and '▶️ Start' in buttons_shown
