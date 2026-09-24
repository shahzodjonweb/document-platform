"""User journeys through real aiogram routing and document/account services."""
import asyncio
import io
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from xml.etree import ElementTree

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendDocument, SendMessage
from aiogram.types import Update
from pypdf import PdfReader
from PIL import Image
from django.utils import timezone

from apps.commerce.models import BotDelivery
from apps.core.identity import exchange_challenge
from apps.core.models import Account, BotCallback, BotConversation, BotDraft, BotInputReceipt, Job, Quote, SupportTicket, UsageLedger
from apps.core.services import execute_job, settle_job, storage_path
from telegram.bot import build_dispatcher
from telegram.ux_copy import UX
from telegram.delivery import drain
from tests.test_bot_transport import Harness, pdf, prepare
from tests.test_telegram_linking import challenge_for, email_account


pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]


def texts(harness):
    return [call.text for call in harness.session.calls if isinstance(call, SendMessage)]


def say(harness, text):
    message = harness.incoming(text=text)
    asyncio.run(harness.dispatcher.feed_update(harness.bot, Update(update_id=harness.count, message=message)))


def test_first_visit_linking_resumes_original_browser_request_after_language_choice():
    account = email_account()
    challenge, token, verifier = challenge_for(account)
    harness = Harness(onboard=False)
    harness.command('/start login_' + token)
    assert Account.objects.count() == 1
    assert not Account.objects.filter(telegram_user_id=42).exists()

    harness.click(harness.language('en'))
    challenge.refresh_from_db()
    assert challenge.approved_at is None
    assert Account.objects.count() == 1
    harness.click(harness.action('link_login'))
    challenge.refresh_from_db()
    assert challenge.approved_at is not None
    account.refresh_from_db()
    assert account.telegram_user_id is None
    assert Account.objects.count() == 1

    linked = exchange_challenge(challenge.id, verifier, link_account=account)
    account.refresh_from_db()
    assert linked.id == account.id and account.telegram_user_id == 42
    assert Account.objects.count() == 1


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_new_user_completes_localized_merge_in_four_actions_from_home(locale):
    harness = Harness(onboard=False)
    harness.command('/start')
    assert not Account.objects.exists()
    harness.click(harness.language(locale))
    account = Account.objects.get(telegram_user_id=42)
    assert account.locale == locale

    # Exactly four actions after Home: tool, two files, Run. No category or Review.
    harness.click(harness.action('tool', feature_id='pdf.merge'))
    harness.document('first', pdf((220,)), name='first.pdf')
    harness.document('second', pdf((320,)), name='второй.pdf')
    assert not Job.objects.exists()
    assert not UsageLedger.objects.exists()
    harness.click(harness.action('run'))

    job = Job.objects.get(account=account)
    assert job.status == 'succeeded', job.error_code
    output = PdfReader(storage_path(job.artifacts.get().file.object_key))
    assert [float(page.mediabox.width) for page in output.pages] == [220, 320]
    result = [call for call in harness.session.calls if isinstance(call, SendDocument)]
    assert len(result) == 1 and result[0].caption and result[0].reply_markup

    # Completed work requires no discard confirmation to start again.
    harness.click(harness.action('new'))
    assert all(not draft.input_ids for draft in BotDraft.objects.filter(account=account))
    assert Job.objects.filter(account=account).count() == 1
    harness.dispatcher = build_dispatcher()
    harness.command('/start')
    assert harness.action('tool', feature_id='pdf.merge')
    account.refresh_from_db()
    assert account.locale == locale


def test_run_button_is_acknowledged_before_processing_and_replay_never_recharges():
    prepare('pdf.rotate', {'angle': 90})
    harness = Harness()
    harness.command('/done')
    button = harness.action('run')
    start = len(harness.session.calls)

    def execute_after_ack(job_id):
        assert any(isinstance(call, AnswerCallbackQuery) for call in harness.session.calls[start:]), (
            'Telegram callback spinner must stop before document processing starts'
        )
        return execute_job(job_id)

    with patch('telegram.bot.execute_job', side_effect=execute_after_ack):
        harness.click(button)
        harness.click(button)

    assert Job.objects.count() == 1
    assert Job.objects.get().status == 'succeeded'
    assert UsageLedger.objects.filter(kind='consume', meter='file_tasks').count() == 1
    assert sum(isinstance(call, SendDocument) for call in harness.session.calls) == 1


def test_cancel_discards_only_current_draft_and_old_run_button_cannot_submit():
    prepare('pdf.rotate', {'angle': 90})
    harness = Harness()
    harness.command('/done')
    old_run = harness.action('run')
    harness.command('/cancel')
    harness.click(harness.action('discard', new=False))
    harness.click(old_run)
    assert not Job.objects.exists()
    assert not UsageLedger.objects.exists()
    assert all(not draft.input_ids for draft in BotDraft.objects.all())
    assert texts(harness)


def test_support_accepts_plain_reply_and_cancel_does_not_create_ticket():
    harness = Harness()
    harness.command('/support')
    say(harness, 'My task completed but I cannot open the result.')
    assert not SupportTicket.objects.exists()
    harness.click(harness.action('support_send'))
    ticket = SupportTicket.objects.get()
    assert ticket.message == 'My task completed but I cannot open the result.'
    assert ticket.category == 'general'
    harness.command('/paysupport')
    harness.command('/cancel')
    say(harness, 'This is ordinary conversation after cancel.')
    assert SupportTicket.objects.count() == 1


def test_guided_page_selection_survives_restart_and_invalid_reply_then_rotates_only_selected_pages():
    account, asset = prepare('pdf.rotate')
    harness = Harness()
    harness.command('/settings')
    harness.click(harness.action('settings', parameters={'angle': 180}))
    harness.click(harness.action('prompt', kind='pages'))

    # Recreate routing as happens on a bot restart; state must live in storage.
    harness.dispatcher = build_dispatcher()
    say(harness, 'not a page number')
    assert BotDraft.objects.get(account=account).input_ids == [str(asset.id)]
    assert not Job.objects.exists()
    say(harness, '1,3')
    draft = BotDraft.objects.get(account=account)
    assert draft.parameters == {'angle': 180, 'pages': '1,3'}
    harness.click(harness.action('run'))
    job = Job.objects.get(account=account)
    assert job.status == 'succeeded', job.error_code
    output = PdfReader(storage_path(job.artifacts.get().file.object_key))
    assert [page.rotation for page in output.pages] == [180, 0, 180]


def test_production_run_returns_queued_then_worker_result_is_delivered_once(settings):
    settings.LOCAL_SYNC_JOBS = False
    account, _ = prepare('pdf.rotate', {'angle': 180})
    account.is_test = False
    account.save(update_fields=['is_test'])
    harness = Harness()
    harness.command('/done')
    with patch('telegram.bot.execute_job', side_effect=AssertionError('The worker must execute production jobs')):
        harness.click(harness.action('run'))

    job = Job.objects.get()
    assert job.status == 'queued'
    assert not any(isinstance(call, SendDocument) for call in harness.session.calls)
    assert not UsageLedger.objects.filter(kind='consume').exists()

    finished = execute_job(job.id)
    assert finished.status == 'succeeded', finished.error_code
    asyncio.run(drain(harness.bot))
    asyncio.run(drain(harness.bot))
    assert sum(isinstance(call, SendDocument) for call in harness.session.calls) == 1
    assert BotDelivery.objects.filter(status='delivered', artifact__job=job).count() == 1
    assert UsageLedger.objects.filter(job=job, kind='consume', meter='file_tasks').count() == 1
    job.refresh_from_db()
    assert job.attempt_count == 1


def test_history_is_owner_bound_and_expired_output_recovers_without_reprocessing():
    account, _ = prepare('pdf.rotate')
    harness = Harness()
    harness.command('/done')
    harness.click(harness.action('run'))
    job = Job.objects.get(account=account)
    assert job.status == 'succeeded'
    harness.command('/myfiles')
    history = harness.session.calls[-1]
    entry = next(
        button for row in history.reply_markup.inline_keyboard for button in row
        if BotCallback.objects.filter(pk=button.callback_data, action='job', payload__job_id=str(job.id)).exists()
    )
    harness.click(entry.callback_data, uid=43)
    assert not Account.objects.filter(telegram_user_id=43).exists()
    harness.click(entry.callback_data)
    download = harness.action('download')
    output = job.artifacts.get().file
    output.expires_at = timezone.now() - timedelta(seconds=1)
    output.save(update_fields=['expires_at'])
    before = len(harness.session.calls)
    harness.click(download)
    new_calls = harness.session.calls[before:]
    assert not any(isinstance(call, SendDocument) for call in new_calls)
    assert any(UX[account.locale]['result_expired'] in (getattr(call, 'text', '') or '') for call in new_calls)
    assert Job.objects.count() == 1
    assert UsageLedger.objects.filter(kind='consume', meter='file_tasks').count() == 1


def test_long_special_character_file_names_keep_telegram_screens_valid():
    harness = Harness()
    for index in range(6):
        harness.document(f'long-{index}', pdf((220,)), name=('&<>' * 40) + str(index) + '.pdf')
    harness.command('/done')
    assert harness.action('run')
    for call in harness.session.calls:
        if isinstance(call, (SendMessage, EditMessageText)) and call.parse_mode == 'HTML':
            # Telegram's HTML parser rejects partial entities and malformed tags;
            # an offline sender must not hide that production transport failure.
            fragment = ElementTree.fromstring('<root>' + call.text + '</root>')
            assert len(''.join(fragment.itertext())) <= 4096


def test_long_valid_options_are_readable_without_altering_requested_pages():
    pages = '1,' + (' ' * 3500) + '3'
    account, _ = prepare('pdf.rotate', {'pages': pages})
    harness = Harness()
    harness.command('/settings')
    harness.command('/done')
    assert harness.action('run')
    assert BotDraft.objects.get(account=account).parameters['pages'] == pages
    assert Quote.objects.get(account=account).parameters['pages'] == pages
    for call in harness.session.calls:
        if isinstance(call, (SendMessage, EditMessageText)) and call.parse_mode == 'HTML':
            fragment = ElementTree.fromstring('<root>' + call.text + '</root>')
            assert len(''.join(fragment.itertext())) <= 4096


def test_upload_uses_inspected_kind_and_wrong_kind_preserves_current_draft():
    account, asset = prepare('pdf.rotate', {'angle': 180})
    original = BotDraft.objects.get(account=account)
    picture = io.BytesIO()
    Image.new('RGB', (12, 18), 'blue').save(picture, format='PNG')
    harness = Harness()
    # A misleading extension must not put an image into a PDF-only operation.
    harness.document('looks-like-pdf', picture.getvalue(), name='picture.pdf', message_id=75)
    original.refresh_from_db()
    assert original.input_ids == [str(asset.id)]
    assert original.parameters['angle'] == 180
    assert not BotInputReceipt.objects.filter(account=account, message_id=75).exists()
    assert not Job.objects.exists()
    assert any(UX[account.locale]['wrong_file'] in value for value in texts(harness))


def test_failed_telegram_download_recovers_without_losing_input_or_charging():
    account, asset = prepare('pdf.rotate', {'angle': 90})
    harness = Harness()
    harness.bot.download = AsyncMock(side_effect=TimeoutError('private transport failure'))
    harness.document('timed-out', pdf((200,)), name='new.pdf', message_id=76)
    assert BotDraft.objects.get(account=account).input_ids == [str(asset.id)]
    assert not BotInputReceipt.objects.filter(account=account, message_id=76).exists()
    assert not Job.objects.exists()
    assert not UsageLedger.objects.exists()
    assert all('private transport failure' not in value for value in texts(harness))
    assert harness.action('controls')


def test_failed_job_retry_requires_new_review_and_explicit_run(settings):
    settings.LOCAL_SYNC_JOBS = False
    account, _ = prepare('pdf.rotate')
    harness = Harness()
    harness.command('/done')
    harness.click(harness.action('run'))
    failed = Job.objects.get(account=account)
    settle_job(failed.id, 'failed', error_code='processing_failed')
    harness.click(harness.action('job'))
    harness.click(harness.action('retry'))
    assert Job.objects.filter(account=account).count() == 1
    assert BotDraft.objects.get(account=account).quote_id != failed.quote_id
    assert Job.objects.filter(account=account).count() == 1
    assert harness.action('run')
    assert not UsageLedger.objects.filter(account=account, kind='consume').exists()


def screen_actions(harness):
    """The latest visible screen, rather than a callback left in older history."""
    call = next(call for call in reversed(harness.session.calls)
                if getattr(call, 'reply_markup', None))
    return [ref for row in call.reply_markup.inline_keyboard for button in row
            if (ref := BotCallback.objects.filter(pk=button.callback_data).first())]


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_direct_image_completes_in_upload_and_run_only(locale):
    harness = Harness(onboard=False)
    harness.command('/start')
    harness.click(harness.language(locale))
    picture = io.BytesIO()
    Image.new('RGB', (60, 90), 'blue').save(picture, format='PNG')
    harness.document('image', picture.getvalue(), name='picture.png')
    draft = BotDraft.objects.get()
    assert draft.feature_id == 'pdf.images_to_pdf'
    assert draft.quote_id is not None
    assert any(ref.action == 'run' for ref in screen_actions(harness))
    assert not Job.objects.exists() and not UsageLedger.objects.exists()
    harness.click(harness.action('run'))
    job = Job.objects.get()
    assert job.status == 'succeeded', job.error_code
    assert len(PdfReader(storage_path(job.artifacts.get().file.object_key)).pages) == 1
    assert sum(isinstance(call, SendDocument) for call in harness.session.calls) == 1


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_direct_pdf_offers_useful_actions_then_runs_without_review(locale):
    harness = Harness(onboard=False)
    harness.command('/start')
    harness.click(harness.language(locale))
    harness.document('pdf', pdf((210,)), name='one.pdf')
    draft = BotDraft.objects.get()
    assert draft.state == 'choosing_tool' and draft.quote_id is None
    available = {ref.payload.get('feature_id') for ref in screen_actions(harness) if ref.action == 'tool'}
    assert {'pdf.compress', 'pdf.rotate', 'pdf.split'} <= available
    assert not Job.objects.exists()
    harness.click(harness.action('tool', feature_id='pdf.rotate'))
    assert any(ref.action == 'run' for ref in screen_actions(harness))
    harness.click(harness.action('run'))
    job = Job.objects.get()
    assert job.status == 'succeeded', job.error_code
    assert PdfReader(storage_path(job.artifacts.get().file.object_key)).pages[0].rotation == 90


def test_edit_requotes_and_previous_run_is_rejected_without_charge():
    account, _ = prepare('pdf.rotate')
    harness = Harness()
    harness.command('/settings')
    first_run = harness.action('run')
    initial_quote = BotDraft.objects.get(account=account).quote_id
    harness.click(harness.action('settings', parameters={'angle': 180}))
    draft = BotDraft.objects.get(account=account)
    assert draft.quote_id != initial_quote
    assert draft.quote.parameters['angle'] == 180
    new_run = harness.action('run')
    harness.click(first_run)
    assert not Job.objects.exists() and not UsageLedger.objects.exists()
    harness.click(new_run)
    harness.click(new_run)
    job = Job.objects.get()
    assert job.parameters['angle'] == 180 and job.status == 'succeeded'
    assert UsageLedger.objects.filter(kind='consume', meter='file_tasks').count() == 1


def test_new_task_guard_keeps_unsubmitted_files_and_stale_confirm_cannot_clear_later_draft():
    account, asset = prepare('pdf.rotate')
    harness = Harness()
    harness.command('/cancel')
    stale_discard = harness.action('discard', new=False)
    assert BotDraft.objects.get(account=account).input_ids == [str(asset.id)]
    harness.click(stale_discard)
    harness.document('later', pdf((310,)), name='later.pdf')
    current = BotDraft.objects.get(account=account)
    current_ids = current.input_ids[:]
    assert current_ids and str(asset.id) not in current_ids
    harness.click(stale_discard)
    current.refresh_from_db()
    assert current.input_ids == current_ids
    assert not Job.objects.exists() and not UsageLedger.objects.exists()


@pytest.mark.parametrize('command', ['/support', '/paysupport'])
def test_cancel_support_exits_in_one_action_and_preserves_uploaded_work(command):
    account, asset = prepare('pdf.rotate', {'angle': 180})
    harness = Harness()
    harness.command('/settings')
    quote_id = BotDraft.objects.get(account=account).quote_id
    harness.command(command)
    say(harness, 'Please help me with this document.')
    pending_send = harness.action('support_send')
    harness.command('/cancel')
    draft = BotDraft.objects.get(account=account)
    assert draft.input_ids == [str(asset.id)] and draft.parameters['angle'] == 180
    assert draft.quote_id == quote_id
    assert BotConversation.objects.get(pk=42).state == ''
    assert all(ref.action != 'discard' for ref in screen_actions(harness))
    harness.click(pending_send)
    assert not SupportTicket.objects.exists()
    assert not Job.objects.exists() and not UsageLedger.objects.exists()


def test_cancel_page_prompt_preserves_options_and_rejects_later_plain_reply():
    account, asset = prepare('pdf.rotate', {'angle': 180})
    harness = Harness()
    harness.command('/settings')
    original_parameters = BotDraft.objects.get(account=account).parameters.copy()
    harness.click(harness.action('prompt', kind='pages'))
    harness.command('/cancel')
    assert BotConversation.objects.get(pk=42).state == ''
    say(harness, '1,3')
    draft = BotDraft.objects.get(account=account)
    assert draft.input_ids == [str(asset.id)] and draft.parameters == original_parameters
    assert not Job.objects.exists() and not UsageLedger.objects.exists()


def test_upload_after_submission_starts_new_task_without_add_or_replace_dialogue(settings):
    settings.LOCAL_SYNC_JOBS = False
    account, asset = prepare('pdf.rotate')
    harness = Harness()
    harness.command('/settings')
    harness.click(harness.action('run'))
    old_job = Job.objects.get(account=account)
    assert old_job.status == 'queued'
    harness.document('next', pdf((510,)), name='next.pdf')
    draft = BotDraft.objects.get(account=account)
    assert len(draft.input_ids) == 1 and str(asset.id) not in draft.input_ids
    assert not any(ref.action == 'attach' for ref in screen_actions(harness))
    old_job.refresh_from_db()
    assert old_job.status == 'queued'
    assert Job.objects.count() == 1 and not UsageLedger.objects.filter(kind='consume').exists()


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_first_contact_image_needs_only_upload_language_and_start(locale):
    from apps.core.models import FileAsset
    harness = Harness(onboard=False)
    picture = io.BytesIO()
    Image.new('RGB', (60, 90), 'blue').save(picture, format='PNG')
    harness.document('new-customer-image', picture.getvalue(), name='first.png')
    assert not Account.objects.exists() and not FileAsset.objects.exists()
    assert not BotInputReceipt.objects.exists()
    harness.click(harness.language(locale))
    assert Account.objects.get(telegram_user_id=42).locale == locale
    assert FileAsset.objects.filter(name='first.png').count() == 1
    assert BotInputReceipt.objects.count() == 1
    assert any(ref.action == 'run' for ref in screen_actions(harness))
    assert not Job.objects.exists() and not UsageLedger.objects.exists()
    harness.click(harness.action('run'))
    assert Job.objects.get().status == 'succeeded'
    assert UsageLedger.objects.filter(kind='consume', meter='file_tasks').count() == 1


def test_first_contact_pdf_album_resumes_original_order_without_repeat_uploads():
    harness = Harness(onboard=False)
    harness.document('first-pending', pdf((220,)), name='first.pdf', message_id=8)
    language = harness.language('en')
    harness.document('second-pending', pdf((320,)), name='second.pdf', message_id=9)
    assert not Account.objects.exists() and not BotInputReceipt.objects.exists()
    harness.click(language)
    assert BotInputReceipt.objects.count() == 2
    draft = BotDraft.objects.get()
    assert draft.feature_id == 'pdf.merge' and draft.quote_id
    assert any(ref.action == 'run' for ref in screen_actions(harness))
    harness.click(harness.action('run'))
    job = Job.objects.get()
    assert job.status == 'succeeded', job.error_code
    output = PdfReader(storage_path(job.artifacts.get().file.object_key))
    assert [float(page.mediabox.width) for page in output.pages] == [220, 320]


def test_single_file_replacement_preserves_work_until_confirm_and_clears_old_page_selection():
    account, asset = prepare('pdf.rotate', {'angle': 180, 'pages': '1,3'})
    harness = Harness()
    harness.command('/settings')
    before = BotDraft.objects.get(account=account)
    initial_quote = before.quote_id
    old_run = harness.action('run')
    harness.document('replacement', pdf((510,)), name='replacement.pdf', message_id=90)
    before.refresh_from_db()
    assert before.input_ids == [str(asset.id)]
    assert before.parameters == {'angle': 180, 'pages': '1,3'}
    assert before.quote_id == initial_quote
    assert not BotInputReceipt.objects.filter(account=account, message_id=90).exists()
    replacement = harness.action('attach', mode='replace')
    harness.click(replacement, uid=43)
    before.refresh_from_db()
    assert before.input_ids == [str(asset.id)] and before.quote_id == initial_quote
    harness.click(harness.action('controls'))  # Keep the current file.
    before.refresh_from_db()
    assert before.input_ids == [str(asset.id)] and before.quote_id == initial_quote

    harness.click(replacement)
    updated = BotDraft.objects.get(account=account)
    assert len(updated.input_ids) == 1 and str(asset.id) not in updated.input_ids
    assert updated.parameters['angle'] == 180
    assert updated.parameters.get('pages', 'all') == 'all'
    assert updated.quote_id and updated.quote_id != initial_quote
    assert BotInputReceipt.objects.filter(account=account, message_id=90).count() == 1
    harness.click(replacement)
    assert BotInputReceipt.objects.filter(account=account, message_id=90).count() == 1
    harness.click(old_run)
    assert not Job.objects.exists() and not UsageLedger.objects.exists()
    harness.click(harness.action('run', quote_id=str(updated.quote_id)))
    job = Job.objects.get(account=account)
    assert job.status == 'succeeded', job.error_code
    result = PdfReader(storage_path(job.artifacts.get().file.object_key))
    assert len(result.pages) == 1 and result.pages[0].rotation == 180
    assert float(result.pages[0].mediabox.width) == 510


def test_incompatible_tool_change_keeps_files_until_confirmation_and_stale_confirm_is_harmless():
    account, asset = prepare('pdf.rotate', {'angle': 180})
    harness = Harness()
    harness.command('/settings')
    before = BotDraft.objects.get(account=account)
    quote_id = before.quote_id
    old_run = harness.action('run')
    harness.command('/tools')
    harness.click(harness.action('tool', feature_id='pdf.images_to_pdf'))
    confirmation = harness.action('start_tool', feature_id='pdf.images_to_pdf')
    before.refresh_from_db()
    assert before.feature_id == 'pdf.rotate' and before.input_ids == [str(asset.id)]
    assert before.quote_id == quote_id
    harness.click(harness.action('controls'))  # Cancel the proposed tool change.
    before.refresh_from_db()
    assert before.input_ids == [str(asset.id)] and before.quote_id == quote_id
    harness.click(confirmation, uid=43)
    before.refresh_from_db()
    assert before.feature_id == 'pdf.rotate'

    harness.click(confirmation)
    draft = BotDraft.objects.get(account=account)
    assert draft.feature_id == 'pdf.images_to_pdf' and draft.input_ids == []
    assert draft.quote_id is None
    picture = io.BytesIO()
    Image.new('RGB', (80, 100), 'blue').save(picture, format='PNG')
    harness.document('new-image', picture.getvalue(), name='fresh.png')
    fresh = BotDraft.objects.get(account=account)
    assert fresh.input_ids and fresh.quote_id
    fresh_ids, fresh_quote = fresh.input_ids[:], fresh.quote_id
    harness.click(confirmation)
    fresh.refresh_from_db()
    assert fresh.input_ids == fresh_ids and fresh.quote_id == fresh_quote
    harness.click(old_run)
    assert not Job.objects.exists() and not UsageLedger.objects.exists()


def test_switch_from_merge_to_single_pdf_tool_chooses_existing_file_without_reupload():
    harness = Harness()
    harness.document('first-choice', pdf((220,)), name='first.pdf')
    harness.document('second-choice', pdf((320,)), name='second.pdf')
    draft = BotDraft.objects.get()
    initial_ids = draft.input_ids[:]
    initial_quote = draft.quote_id
    old_run = harness.action('run')
    harness.command('/tools')
    harness.click(harness.action('tool', feature_id='pdf.rotate'))
    options = [ref for ref in screen_actions(harness)
               if ref.action == 'tool' and ref.payload.get('feature_id') == 'pdf.rotate']
    assert {ref.payload.get('asset_id') for ref in options} == set(initial_ids)
    draft.refresh_from_db()
    assert draft.input_ids == initial_ids and draft.feature_id == 'pdf.merge'
    assert draft.quote_id == initial_quote
    chosen = harness.action('tool', feature_id='pdf.rotate', asset_id=initial_ids[1])
    harness.click(chosen, uid=43)
    draft.refresh_from_db()
    assert draft.input_ids == initial_ids
    harness.click(chosen)
    draft.refresh_from_db()
    assert draft.input_ids == [initial_ids[1]] and draft.feature_id == 'pdf.rotate'
    assert draft.quote_id and draft.quote_id != initial_quote
    assert BotInputReceipt.objects.count() == 2
    harness.click(old_run)
    assert not Job.objects.exists() and not UsageLedger.objects.exists()
    harness.click(harness.action('run', quote_id=str(draft.quote_id)))
    job = Job.objects.get()
    assert job.status == 'succeeded', job.error_code
    result = PdfReader(storage_path(job.artifacts.get().file.object_key))
    assert len(result.pages) == 1 and float(result.pages[0].mediabox.width) == 320
    assert result.pages[0].rotation == 90


def test_submission_rechecks_draft_binding_atomically_and_valid_quote_replay_is_idempotent():
    from apps.core.errors import DomainError
    from telegram.workflows import configure, quote_draft, run_quote, snapshot

    account, _ = prepare('pdf.rotate', {'angle': 90})
    draft, stale_quote = quote_draft(account)
    stale_binding = snapshot(draft)
    # This edit can happen after an earlier UI authorization but before submission.
    configure(account, parameters={'angle': 180}, binding=stale_binding)
    with pytest.raises(DomainError) as rejected:
        run_quote(account, stale_quote.id, stale_binding)
    assert rejected.value.code == 'controls_expired'
    assert not Job.objects.exists() and not UsageLedger.objects.exists()

    current, valid_quote = quote_draft(account)
    valid_binding = snapshot(current)
    job, created = run_quote(account, valid_quote.id, valid_binding)
    replay, replay_created = run_quote(account, valid_quote.id, valid_binding)
    assert created and not replay_created and replay.id == job.id
    assert Job.objects.count() == 1 and job.parameters['angle'] == 180
    assert UsageLedger.objects.filter(kind='reserve', meter='file_tasks').count() == 1
    assert not UsageLedger.objects.filter(kind='consume').exists()
    execute_job(job.id)
    replay, replay_created = run_quote(account, valid_quote.id, valid_binding)
    assert replay.id == job.id and not replay_created
    assert UsageLedger.objects.filter(kind='consume', meter='file_tasks').count() == 1
