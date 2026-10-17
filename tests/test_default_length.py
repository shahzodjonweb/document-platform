"""A description that names no count gets ten pages or ten slides, on every plan.

The owner's decision of 2026-10-16: the default was five, and it is now ten for
documents and decks alike, whatever the plan. A count the description names
still wins, and the plan's ceiling, the same on every plan now, still clamps it.
The deck setup screen starts at the same ten, so opening it to pick a design
does not quietly change the length the review showed.
"""
import json

import pytest

from apps.core.identity import resolve_account
from apps.studio import pages
from apps.studio.domain import DOCUMENT, SLIDES, create_draft, generation_quote, unpack
from operations.integrations import save_config
from tests.test_manual_payments import paid
from tests.test_platform import login_client

pytestmark = pytest.mark.django_db

PLANS = ['free', 'plus', 'premium']
SERVICES = [(DOCUMENT, 'pdf'), (SLIDES, 'pptx')]


@pytest.fixture(autouse=True)
def model(settings):
    # With a model to write them, an unasked-for count is the default. Local
    # authoring follows the material it is given instead (domain._prepare_draft).
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    save_config('ai', {'mode': 'openai', 'model': 'gpt-5.6-luna', 'api_key': 'sk-offline-test-only'})


def on_plan(plan):
    account = resolve_account({'id': 991100 + PLANS.index(plan), 'first_name': f'{plan} plan',
                               'language_code': 'en'}, is_test=True)
    if plan != 'free':
        paid(account, plan)
    assert account.plan == plan
    return account


def drafted(account, fid, prompt):
    draft = create_draft(account, {'feature_id': fid, 'title': 'Tides', 'prompt': prompt})
    return draft, unpack(draft.encrypted_data)


def test_the_default_is_ten_and_fits_one_writing_call():
    assert pages.DEFAULT_PAGES == 10
    assert pages.SETUP_SLIDES == pages.DEFAULT_PAGES, 'the setup screen starts where the review does'
    # Ten sections are one call, inside one response, so the default never pays
    # for a second round trip or risks a reply cut off mid-JSON.
    assert pages.DEFAULT_PAGES <= pages.PAGES_PER_CALL
    assert pages.batches(pages.DEFAULT_PAGES) == [(0, pages.DEFAULT_PAGES)]
    assert pages.call_tokens(pages.DEFAULT_PAGES) <= pages.RESPONSE_CEILING
    assert pages.response_tokens(pages.DEFAULT_PAGES) < pages.RESPONSE_CEILING


def test_a_default_document_that_comes_out_short_is_topped_up_in_one_uncut_call():
    """Ten pages written at the two thirds a model usually manages render as about eight;
    the call that writes the rest asks for all of it, under the response ceiling."""
    from apps.studio import filling
    content = {'title': 'Tides', 'sections': [{'id': f's{n}', 'heading': f'Part {n}', 'body': 'x' * 2500}
                                              for n in range(pages.DEFAULT_PAGES)]}
    missing = filling.shortfall(content, pages.DEFAULT_PAGES, 8)
    assert missing >= 2 * pages.CHARS_PER_PAGE * 0.8
    words = round(missing / pages.CHARS_PER_WORD * filling.ASK_RATIO)
    body = filling.request_body({'model': 'gpt-5.6-luna'}, {'output_locale': 'uz', 'prompt': 'Tides'}, content, words)
    assert body['max_output_tokens'] < pages.RESPONSE_CEILING, 'not cut down to the ceiling'


@pytest.mark.parametrize('plan', PLANS)
@pytest.mark.parametrize('fid,fmt', SERVICES)
def test_a_description_without_a_count_gets_ten_on_every_plan(plan, fid, fmt):
    account = on_plan(plan)
    assert pages.ceiling(account, fmt) >= pages.DEFAULT_PAGES, 'no plan clamps the default'
    draft, data = drafted(account, fid, 'Tide tables explained simply for beginners')
    assert data['options']['length'] == 10
    assert data['options']['requested_pages'] is None, 'a default, not a count the customer named'
    assert len(data['content']['sections']) == 10
    # Ten is quoted, and fits the plan's input budget and the job's lease.
    quote = generation_quote(account, draft.id, draft.version)
    assert quote.policy['generation_bounds']['output_pages'] == 11, 'ten and the page of headroom'
    assert quote.policy['lease_seconds'] <= 2400


@pytest.mark.parametrize('plan', PLANS)
@pytest.mark.parametrize('fid,prompt', [(DOCUMENT, 'A 3 page guide to tide tables'),
                                        (SLIDES, '3 ta slayd: suv qalqishi')])
def test_a_count_in_the_description_still_wins(plan, fid, prompt):
    _, data = drafted(on_plan(plan), fid, prompt)
    assert data['options']['length'] == 3 and data['options']['requested_pages'] == 3
    assert len(data['content']['sections']) == 3


@pytest.mark.parametrize('fid,fmt', SERVICES)
def test_the_plan_ceiling_still_clamps_a_count_and_says_so(fid, fmt):
    account = on_plan('free')
    top = pages.ceiling(account, fmt)
    unit = 'slides' if fid == SLIDES else 'pages'
    _, data = drafted(account, fid, f'Tides, {top + 40} {unit}')
    assert data['options']['length'] == top
    assert data['options']['requested_pages'] == top + 40, 'kept, so the review can show the cut'


def test_a_default_deck_counts_its_question_slide_among_the_ten():
    """"5 questions at the end" with no count is ten slides: nine written and one of questions."""
    _, data = drafted(on_plan('free'), SLIDES, 'A deck about tides with 5 questions at the end')
    assert data['options']['length'] == 10 and data['options']['question_slides'] == 1
    assert len(data['content']['sections']) == 9
    _, document = drafted(on_plan('free'), DOCUMENT, 'A guide to tides with 5 questions at the end')
    assert document['options']['length'] == 10 and len(document['content']['sections']) == 10


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_the_bot_says_the_default_it_gives(locale):
    """The line under the bot's "describe what you want" names the count it will make."""
    import re
    from telegram.ux_copy import UX
    hint = UX[locale]['ai_pages_hint']
    assert re.findall(r'\d+', hint) == [str(pages.DEFAULT_PAGES)], hint


def test_the_studio_and_the_deck_setup_screen_publish_ten():
    client = login_client(on_plan('free'))
    assert client.get('/api/v1/studio/config').json()['default_pages'] == 10
    assert client.get('/api/v1/studio/deck-designs?locale=uz').json()['default_pages'] == 10


def test_saving_a_design_on_the_setup_screen_keeps_a_default_deck_at_ten():
    """The screen sends the count it shows, and for a deck that named none that is the default."""
    account = on_plan('free')
    draft, data = drafted(account, SLIDES, 'Tides for year 7')
    assert data['options']['length'] == 10
    client = login_client(account)
    shown = client.get('/api/v1/studio/deck-designs').json()['default_pages']
    response = client.post(f'/api/v1/generation/drafts/{draft.id}/setup',
                           data=json.dumps({'pages': shown, 'deck_design': 'midnight'}),
                           content_type='application/json')
    assert response.status_code == 200, response.content
    assert response.json()['draft']['options']['length'] == 10
