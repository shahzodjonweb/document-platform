"""Images to PDF in the bot: every photo is scanned, with no switches to set.

Crop and enhance were switches from 6 to 11 October 2026. The deploy that
retired them cleaned the drafts and marked the buttons still stored; tapping
an old one explains that both are automatic now and redraws the task.
"""
import asyncio
import html
import io
from xml.etree import ElementTree

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import PhotoSize, Update
from PIL import Image

from apps.core.errors import DomainError
from apps.core.models import Account, BotCallback, BotDraft, Job
from telegram.bot import COPY, callback, option_summary
from telegram.errors import bot_error
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
    assert not Job.objects.exists()


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
    assert not Job.objects.exists()
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


def deploy():
    """Run the data migration that retired the scan switches' stored keys."""
    import importlib
    from django.apps import apps as django_apps
    importlib.import_module('apps.core.migrations.0018_retire_scan_switch_keys').retire_scan_switches(django_apps, None)


def old_switch_button(harness, key):
    """A crop or enhance button as the bot drew it before the switches were retired."""
    draft = BotDraft.objects.get()
    binding = next(ref.payload for ref in settings_refs(harness))
    return asyncio.run(callback(draft.account, 'settings', {'draft_id': binding['draft_id'], 'version': binding['version'],
                                                          'parameters': {key: False}, 'advanced': False}))


def answers(harness):
    return [call for call in harness.session.calls if isinstance(call, AnswerCallbackQuery)]


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
@pytest.mark.parametrize('key', ['auto_crop', 'enhance_text'])
@pytest.mark.parametrize('migrated', [True, False], ids=['migrated', 'unmigrated'])
@pytest.mark.parametrize('moved_on', [False, True], ids=['same-screen', 'task-changed-since'])
def test_an_old_crop_or_enhance_button_explains_and_redraws_the_task(settings, locale, key, migrated, moved_on):
    settings.LOCAL_SYNC_JOBS = False
    harness = ready(locale)
    harness.document('image', picture(), name='document.jpg')
    harness.command('/paper Letter')
    harness.command('/settings')
    old_button = old_switch_button(harness, key)
    if migrated:
        deploy()
        assert BotCallback.objects.get(pk=old_button).payload['retired'] == 'scan_switches'
    expected = {**DEFAULTS, 'paper_size': 'Letter'}
    if moved_on:
        harness.command('/margin 12')
        expected['margin'] = 12
    draft = BotDraft.objects.get()
    harness.click(old_button)
    answer = answers(harness)[-1]
    assert (answer.text, answer.show_alert) == (UX[locale]['scan_switches_retired'], True)
    changed = BotDraft.objects.get()
    assert changed.parameters == expected and changed.version == draft.version
    redrawn = screen(harness)
    assert isinstance(redrawn, EditMessageText) and redrawn.message_id == 100
    assert_no_switches(harness, locale)
    assert COPY[locale]['controls_expired'] not in html.unescape(redrawn.text)
    harness.click(harness.action('run'))
    assert Job.objects.get().parameters == expected


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
@pytest.mark.parametrize('gone', ['discarded', 'other-tool'])
def test_an_old_switch_button_whose_task_is_gone_only_explains(locale, gone):
    harness = ready(locale)
    harness.document('image', picture(), name='document.jpg')
    harness.command('/settings')
    old_button = old_switch_button(harness, 'auto_crop')
    deploy()
    if gone == 'discarded':
        BotDraft.objects.all().delete()
    else:
        BotDraft.objects.update(feature_id='pdf.compress', parameters={})
    before = len(harness.session.calls)
    harness.click(old_button)
    after = harness.session.calls[before:]
    assert [type(call) for call in after] == [AnswerCallbackQuery], 'only the notice; the message is left as it was'
    assert after[0].text == UX[locale]['scan_switches_retired']


def test_a_draft_saved_with_switches_is_cleaned_at_deploy_and_runs(settings):
    settings.LOCAL_SYNC_JOBS = False
    harness = ready()
    harness.document('image', picture(), name='document.jpg')
    BotDraft.objects.update(parameters={**DEFAULTS, 'auto_crop': True, 'enhance_text': True})
    version = BotDraft.objects.get().version
    deploy()
    draft = BotDraft.objects.get()
    assert draft.parameters == DEFAULTS and draft.version == version, 'the screen on show keeps working'
    harness.command('/settings')
    assert_no_switches(harness, 'en')
    harness.command('/margin 12')
    draft = BotDraft.objects.get()
    assert draft.parameters == {**DEFAULTS, 'margin': 12} and draft.quote.parameters == draft.parameters
    harness.click(harness.action('run'))
    assert Job.objects.get().parameters == {**DEFAULTS, 'margin': 12}


def test_typed_scan_switches_are_an_unknown_setting(settings):
    harness = ready()
    harness.document('image', picture(), name='document.jpg')
    draft = BotDraft.objects.get()
    harness.command('/parameters {"auto_crop": false}')
    assert BotDraft.objects.get().parameters == draft.parameters
    assert bot_error(DomainError('invalid_parameters'), 'en') in html.unescape(screen(harness).text)
