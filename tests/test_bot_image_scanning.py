"""Image scanning options are visible at conversion, with safe one-tap edits."""
import asyncio
import html
import io
from xml.etree import ElementTree

import pytest
from aiogram.methods import EditMessageText, SendMessage
from aiogram.types import PhotoSize, Update
from PIL import Image

from apps.core.models import Account, BotCallback, BotDraft, Job, UsageLedger
from telegram.bot import option_summary
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


def switch(harness, key, value):
    for row in screen(harness).reply_markup.inline_keyboard:
        for button in row:
            ref = BotCallback.objects.filter(pk=button.callback_data, action='settings').first()
            if ref and ref.payload.get('parameters') == {key: value}:
                return button, ref
    raise AssertionError(f'Missing {key} switch on the current conversion screen')


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_tool_screen_shows_both_enabled_switches_before_upload_without_another_step(locale):
    harness = ready(locale)
    before = sum(isinstance(call, SendMessage) for call in harness.session.calls)
    harness.click(harness.action('tool', feature_id='pdf.images_to_pdf'))
    draft = BotDraft.objects.get()
    assert draft.parameters['auto_crop'] is True and draft.parameters['enhance_text'] is True
    assert draft.input_ids == [] and draft.quote_id is None
    assert sum(isinstance(call, SendMessage) for call in harness.session.calls) == before
    for key, label in [('auto_crop', 'auto_crop_label'), ('enhance_text', 'enhance_text_label')]:
        button, ref = switch(harness, key, False)
        assert button.text == f'✅ {UX[locale][label]}: {UX[locale]["option_on"]}'
        assert len(button.text) <= 64 and len(button.callback_data.encode()) <= 64
        assert ref.account_id == draft.account_id and ref.payload['version'] == draft.version
        assert not ref.payload.get('replace', False) and not ref.payload.get('advanced', False)
    assert UX[locale]['document_scan_hint'] in html.unescape(screen(harness).text)
    ElementTree.fromstring('<root>' + screen(harness).text + '</root>')
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
    assert draft.parameters['auto_crop'] is True and draft.parameters['enhance_text'] is True
    assert draft.quote.parameters['auto_crop'] is True and draft.quote.parameters['enhance_text'] is True
    assert switch(harness, 'auto_crop', False) and switch(harness, 'enhance_text', False)
    assert 'True' not in screen(harness).text and 'False' not in screen(harness).text
    assert UX[locale]['option_on'] in screen(harness).text
    assert not Job.objects.exists() and not UsageLedger.objects.exists()
    harness.click(harness.action('run'))
    job = Job.objects.get()
    assert job.parameters['auto_crop'] is True and job.parameters['enhance_text'] is True
    assert job.origin_channel == 'bot' and job.status == 'queued'


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_each_switch_opts_out_independently_preserves_layout_and_requotes_without_a_new_message(settings, locale):
    settings.LOCAL_SYNC_JOBS = False
    harness = ready(locale)
    harness.document('image', picture(), name='document.jpg')
    harness.command('/paper Letter')
    harness.command('/layout landscape')
    harness.command('/margin 12')
    original = BotDraft.objects.get()
    old_quote = original.quote_id
    old_run = harness.action('run')
    crop, crop_ref = switch(harness, 'auto_crop', False)
    stale_enhance, _ = switch(harness, 'enhance_text', False)
    sent = sum(isinstance(call, SendMessage) for call in harness.session.calls)

    # A different Telegram sender cannot use an owner's stored toggle.
    harness.onboard = True
    harness.click(crop.callback_data, uid=43)
    original.refresh_from_db()
    assert original.parameters['auto_crop'] is True and original.quote_id == old_quote
    assert not Account.objects.filter(telegram_user_id=43).exists()
    harness.click(crop.callback_data)
    changed = BotDraft.objects.get()
    assert changed.parameters == {'paper_size': 'Letter', 'orientation': 'landscape', 'margin': 12.0,
                                  'auto_crop': False, 'enhance_text': True}
    assert changed.quote_id != old_quote and changed.quote.parameters == changed.parameters
    assert changed.version == crop_ref.payload['version'] + 1
    assert sum(isinstance(call, SendMessage) for call in harness.session.calls) == sent
    assert switch(harness, 'auto_crop', True)[0].text.endswith(UX[locale]['option_off'])
    assert switch(harness, 'enhance_text', False)[0].text.endswith(UX[locale]['option_on'])

    # Old controls cannot reverse a later edit or spend an older quote.
    version, quote_id = changed.version, changed.quote_id
    harness.click(crop.callback_data)
    harness.click(stale_enhance.callback_data)
    harness.click(old_run)
    changed.refresh_from_db()
    assert changed.version == version and changed.quote_id == quote_id
    assert changed.parameters['auto_crop'] is False and changed.parameters['enhance_text'] is True
    assert not Job.objects.exists() and not UsageLedger.objects.exists()

    harness.command('/settings')
    enhance, _ = switch(harness, 'enhance_text', False)
    harness.click(enhance.callback_data)
    changed.refresh_from_db()
    assert changed.parameters['auto_crop'] is False and changed.parameters['enhance_text'] is False
    assert changed.parameters['paper_size'] == 'Letter' and changed.parameters['margin'] == 12
    assert changed.quote_id != quote_id and changed.quote.parameters == changed.parameters
    assert switch(harness, 'enhance_text', True)[0].text.startswith('⬜ ')
    harness.click(switch(harness, 'auto_crop', True)[0].callback_data)
    changed.refresh_from_db()
    assert changed.parameters['auto_crop'] is True and changed.parameters['enhance_text'] is False
    harness.click(harness.action('run'))
    assert Job.objects.get().parameters == changed.parameters


def test_opt_out_before_upload_survives_more_images_and_bot_restart(settings):
    from telegram.bot import build_dispatcher
    settings.LOCAL_SYNC_JOBS = False
    harness = ready()
    harness.click(harness.action('tool', feature_id='pdf.images_to_pdf'))
    harness.click(switch(harness, 'auto_crop', False)[0].callback_data)
    harness.click(switch(harness, 'enhance_text', False)[0].callback_data)
    assert BotDraft.objects.get().quote_id is None
    harness.dispatcher = build_dispatcher()
    harness.document('first', picture(), name='first.jpg')
    first_quote = BotDraft.objects.get().quote_id
    harness.document('second', picture(), name='second.jpg')
    draft = BotDraft.objects.get()
    assert len(draft.input_ids) == 2 and draft.quote_id != first_quote
    assert draft.parameters['auto_crop'] is False and draft.parameters['enhance_text'] is False
    assert draft.quote.parameters['auto_crop'] is False and draft.quote.parameters['enhance_text'] is False
    assert switch(harness, 'auto_crop', True) and switch(harness, 'enhance_text', True)
    harness.click(harness.action('run'))
    job = Job.objects.get()
    assert len(job.input_ids) == 2 and job.parameters['auto_crop'] is False and job.parameters['enhance_text'] is False


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_saved_image_drafts_with_missing_scan_flags_still_show_current_defaults(locale):
    from types import SimpleNamespace
    draft = SimpleNamespace(feature_id='pdf.images_to_pdf', parameters={'paper_size': 'A4'})
    account = SimpleNamespace(locale=locale)
    summary = html.unescape(option_summary(account, draft))
    assert f'{UX[locale]["auto_crop_label"]}: {UX[locale]["option_on"]}' in summary
    assert f'{UX[locale]["enhance_text_label"]}: {UX[locale]["option_on"]}' in summary
    assert draft.parameters == {'paper_size': 'A4'}
