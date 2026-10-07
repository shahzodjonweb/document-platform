"""The review screen is where a misread request gets put right, before paying.

The first ad wave showed counts read wrong ("10 varoqlik" → 5), languages not
honoured ("ingliz tilida"), and limits met with no way forward. The screen now
shows the count, the language and the plan's limits, each fixable in one tap.
"""
import pytest

from operations.integrations import save_config
from tests.test_bot_generation import body, buttons, customer, describe, free_customer, labels, latest, tap  # noqa: F401
from telegram.local import dispatch_local

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]


@pytest.fixture(autouse=True)
def model():
    save_config('ai', {'mode': 'openai', 'model': 'gpt-5.6-luna', 'api_key': 'sk-offline-test-only'})


def test_the_count_can_be_changed_before_paying(customer):
    review = describe(customer, 'A 4 page introduction to tide tables.')
    assert 'Pages: 4' in body(review)
    longer = tap(customer, review, '➕ 5')
    assert 'Pages: 5' in body(longer), body(longer)[-400:]
    assert latest(customer)['options']['length'] == 5
    assert len(latest(customer)['content']['sections']) == 5
    shorter = tap(customer, longer, '➖ 4')
    assert 'Pages: 4' in body(shorter)
    # The chosen count stays chosen: it is not read again from the description.
    assert latest(customer)['options']['pages'] == 4


def test_a_deck_is_counted_in_slides(customer):
    review = describe(customer, '6 ta slayd: suv aylanishi', service='Slides on a topic')
    assert 'Slides: 6' in body(review), body(review)[-400:]


def test_at_the_plan_limit_more_means_a_bigger_plan(free_customer):
    from apps.core.policy import limits_for_plan, plan_limits
    allowed = plan_limits(free_customer)['max_generated_pdf_pages']
    review = describe(free_customer, 'A 12 page report on tide tables.')
    assert f'Pages: {allowed}' in body(review)
    assert not any(label.startswith('➕') for label in labels(review)), 'no more pages on this plan'
    offer = [label for label in labels(review) if label.startswith('💎')]
    assert offer == [f"💎 Up to {limits_for_plan('plus')['max_generated_pdf_pages']} pages with Plus"], labels(review)
    plans = tap(free_customer, review, '💎 Up to')
    assert 'Plus' in body(plans)


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


def test_pictures_beyond_the_plan_are_said_and_offered(free_customer):
    from apps.core.policy import plan_limits
    from operations.integrations import save_config as configure
    from tests.test_photos import KEY
    configure('pixabay', {'pixabay_key': KEY, 'enabled': 'true'})
    cap = plan_limits(free_customer)['max_deck_images']
    assert 0 < cap < 10, 'this test needs a plan that adds fewer pictures than slides'
    review = describe(free_customer, '10 ta slayd, har bir slaydda rasm bo‘lsin', service='Slides on a topic')
    assert f'your plan adds up to {cap}' in body(review), body(review)[-500:]
    assert any(label.startswith('💎') and 'pictures' in label for label in labels(review)), labels(review)
