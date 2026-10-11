"""Images to PDF in the bot: every photo is scanned, with no switches to set.

Old scan-switch buttons stay in chats forever; tapping one, or running a draft
saved with those switches, still works and simply drops them.
"""
import asyncio
import html
import io
from xml.etree import ElementTree

import pytest
from aiogram.methods import EditMessageText, SendMessage
from aiogram.types import PhotoSize, Update
from PIL import Image

from apps.core.models import Account, BotCallback, BotDraft, Job, UsageLedger
from telegram.bot import callback, option_summary
from telegram.ux_copy import UX
from tests.test_bot_transport import Harness


pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]


def picture():
    stream = io.BytesIO()
    Image.new('RGB', (90, 130), '#315278').save(stream, format='JPEG')
    return stream.getvalue()


def ready(locale='en'):
    harness = Harness(onboard=False)
    harness.command('/start')
    harness.click(harness.language(locale))
    return harness


def screen(harness):
    return next(call for call in reversed(harness.session.calls)
                if isinstance(call, (SendMessage, EditMessageText)) and call.reply_markup)


DEFAULTS = {'paper_size': 'fit', 'orientation': 'auto', 'margin': 0}
LEGACY = ('auto_crop', 'enhance_text')


def settings_refs(harness):
    """The settings callbacks behind the buttons on the current screen."""
    refs = []
    for row in screen(harness).reply_markup.inline_keyboard:
        for button in row:
            ref = BotCallback.objects.filter(pk=button.callback_data, action='settings').first()
            if ref:
                refs.append(ref)
    return refs


def assert_no_switches(harness, locale):
    assert not any(set(LEGACY) & set(ref.payload.get('parameters', {})) for ref in settings_refs(harness))
    text = html.unescape(screen(harness).text)
    assert UX[locale]['document_scan_hint'] in text
    assert 'True' not in text and 'False' not in text
    ElementTree.fromstring('<root>' + screen(harness).text + '</root>')


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_tool_screen_explains_scanning_before_upload_without_switches(locale):
    harness = ready(locale)
    before = sum(isinstance(call, SendMessage) for call in harness.session.calls)
    harness.click(harness.action('tool', feature_id='pdf.images_to_pdf'))
    draft = BotDraft.objects.get()
    assert draft.parameters == DEFAULTS
    assert draft.input_ids == [] and draft.quote_id is None
    assert sum(isinstance(call, SendMessage) for call in harness.session.calls) == before
    assert_no_switches(harness, locale)
    assert not Job.objects.exists() and not UsageLedger.objects.exists()


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
@pytest.mark.parametrize('as_photo', [False, True])
def test_direct_photo_and_image_uploads_have_defaults_and_can_start_immediately(settings, locale, as_photo):
    settings.LOCAL_SYNC_JOBS = False
    harness = ready(locale)
    payload = picture()
    if as_photo:
        harness.session.files['photo'] = payload
        incoming = harness.incoming(photo=[PhotoSize(file_id='photo', file_unique_id='photo', width=90,
                                                     height=130, file_size=len(payload))])
        asyncio.run(harness.dispatcher.feed_update(harness.bot, Update(update_id=harness.count, message=incoming)))
    else:
        harness.document('image', payload, name='document.jpg')
    draft = BotDraft.objects.get()
    assert draft.feature_id == 'pdf.images_to_pdf'
    assert draft.parameters == DEFAULTS and draft.quote.parameters == DEFAULTS
    assert_no_switches(harness, locale)
    assert not Job.objects.exists() and not UsageLedger.objects.exists()
    harness.click(harness.action('run'))
    job = Job.objects.get()
    assert job.parameters == DEFAULTS
    assert job.origin_channel == 'bot' and job.status == 'queued'


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_fit_page_choice_is_localized_and_preserves_explicit_margin(locale):
    harness = ready(locale)
    harness.document('image', picture(), name='document.jpg')
    harness.command('/paper A4')
    harness.command('/margin 24')
    harness.command('/settings')
    fit_button = harness.action('settings', parameters={'paper_size': 'fit'})
    ref = BotCallback.objects.get(pk=fit_button)
    label = next(button.text for row in screen(harness).reply_markup.inline_keyboard for button in row
                 if button.callback_data == fit_button)
    assert label == UX[locale]['fit_page']
    harness.click(fit_button)
    draft = BotDraft.objects.get()
    assert draft.parameters['paper_size'] == 'fit' and draft.parameters['margin'] == 24
    assert draft.quote.parameters == draft.parameters
    assert UX[locale]['fit_page'] in html.unescape(option_summary(draft.account, draft))
    assert ref.payload['draft_id'] == draft.id


@pytest.mark.parametrize('old', [{'auto_crop': False}, {'enhance_text': False}, {'auto_crop': True}])
def test_an_old_switch_button_still_in_a_chat_is_accepted_and_dropped(settings, old):
    settings.LOCAL_SYNC_JOBS = False
    harness = ready()
    harness.document('image', picture(), name='document.jpg')
    harness.command('/paper Letter')
    harness.command('/settings')
    draft = BotDraft.objects.get()
    # The button as the bot drew it before the switches were retired.
    binding = next(ref.payload for ref in settings_refs(harness))
    old_button = asyncio.run(callback(draft.account, 'settings',
                                      {**binding, 'parameters': old, 'advanced': False}))
    harness.click(old_button)
    changed = BotDraft.objects.get()
    assert changed.parameters == {**DEFAULTS, 'paper_size': 'Letter'}
    assert changed.version == draft.version + 1 and changed.quote.parameters == changed.parameters
    assert UX['en']['document_scan_hint'] in html.unescape(screen(harness).text)
    harness.click(harness.action('run'))
    assert Job.objects.get().parameters == {**DEFAULTS, 'paper_size': 'Letter'}


def test_a_draft_saved_with_switches_runs_without_them(settings):
    settings.LOCAL_SYNC_JOBS = False
    harness = ready()
    harness.document('image', picture(), name='document.jpg')
    BotDraft.objects.update(parameters={**DEFAULTS, 'auto_crop': False, 'enhance_text': True})
    harness.command('/margin 12')
    draft = BotDraft.objects.get()
    assert draft.parameters == {**DEFAULTS, 'margin': 12} and draft.quote.parameters == draft.parameters
    harness.click(harness.action('run'))
    assert Job.objects.get().parameters == {**DEFAULTS, 'margin': 12}


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_summary_of_a_saved_draft_ignores_its_old_switches(locale):
    from types import SimpleNamespace
    draft = SimpleNamespace(feature_id='pdf.images_to_pdf',
                            parameters={'paper_size': 'A4', 'auto_crop': False, 'enhance_text': True})
    account = SimpleNamespace(locale=locale)
    summary = html.unescape(option_summary(account, draft))
    assert 'A4' in summary
    assert 'True' not in summary and 'False' not in summary and 'auto_crop' not in summary
    assert draft.parameters == {'paper_size': 'A4', 'auto_crop': False, 'enhance_text': True}
