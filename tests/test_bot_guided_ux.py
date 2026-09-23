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
from apps.core.models import Account, BotDraft, BotInputReceipt, Job, Quote, SupportTicket, UsageLedger
from apps.core.services import execute_job, settle_job, storage_path
from telegram.bot import build_dispatcher
from telegram.delivery import drain
from tests.test_bot_transport import Harness, pdf, prepare
from tests.test_telegram_linking import challenge_for, email_account


pytestmark = pytest.mark.django_db(transaction=True)


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

    harness.click(harness.token('English'))
    challenge.refresh_from_db()
    assert challenge.approved_at is None
    assert Account.objects.count() == 1
    harness.click(harness.token('Confirm Telegram link'))
    challenge.refresh_from_db()
    assert challenge.approved_at is not None
    account.refresh_from_db()
    assert account.telegram_user_id is None
    assert Account.objects.count() == 1

    linked = exchange_challenge(challenge.id, verifier, link_account=account)
    account.refresh_from_db()
    assert linked.id == account.id and account.telegram_user_id == 42
    assert Account.objects.count() == 1


@pytest.mark.parametrize(('locale', 'language', 'tools', 'merge', 'review', 'run', 'new_task', 'confirm_new'), [
    ('en', 'English', 'PDF tools', 'Merge PDFs', 'Review quote', 'Run task', 'New task', 'Start fresh'),
    ('uz', 'O‘zbekcha', 'PDF vositalari', 'PDF birlashtirish', 'Hisob-kitobni ko‘rish', 'Vazifani bajarish', 'Yangi vazifa', 'Yangidan boshlash'),
    ('ru', 'Русский', 'Инструменты PDF', 'Объединить PDF', 'Проверить расчёт', 'Выполнить', 'Новая задача', 'Начать заново'),
])
def test_new_user_completes_localized_button_and_upload_journey(
    locale, language, tools, merge, review, run, new_task, confirm_new,
):
    harness = Harness(onboard=False)
    harness.command('/start')
    assert not Account.objects.exists()
    harness.click(harness.token(language))
    account = Account.objects.get(telegram_user_id=42)
    assert account.locale == locale
    harness.click(harness.token(tools))
    harness.click(harness.token(merge))
    harness.document('first', pdf((220,)), name='first.pdf')
    harness.document('second', pdf((320,)), name='второй.pdf')
    harness.click(harness.token(review))
    assert not Job.objects.exists()
    harness.click(harness.token(run))

    job = Job.objects.get(account=account)
    assert job.status == 'succeeded', job.error_code
    output = PdfReader(storage_path(job.artifacts.get().file.object_key))
    assert [float(page.mediabox.width) for page in output.pages] == [220, 320]
    result = [call for call in harness.session.calls if isinstance(call, SendDocument)]
    assert len(result) == 1 and result[0].caption and result[0].reply_markup

    harness.click(harness.token(new_task))
    harness.click(harness.token(confirm_new))
    assert all(not draft.input_ids for draft in BotDraft.objects.filter(account=account))
    assert Job.objects.filter(account=account).count() == 1
    harness.dispatcher = build_dispatcher()
    harness.command('/start')
    assert harness.token(tools)
    account.refresh_from_db()
    assert account.locale == locale


def test_run_button_is_acknowledged_before_processing_and_replay_never_recharges():
    prepare('pdf.rotate', {'angle': 90})
    harness = Harness()
    harness.command('/done')
    button = harness.token('Run task')
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
    old_run = harness.token('Run task')
    harness.command('/cancel')
    harness.click(harness.token('Yes, cancel draft'))
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
    harness.click(harness.token('Send request'))
    ticket = SupportTicket.objects.get()
    assert ticket.message == 'My task completed but I cannot open the result.'
    assert ticket.category == 'general'
    harness.command('/paysupport')
    harness.command('/cancel')
    harness.click(harness.token('Yes, cancel draft'))
    say(harness, 'This is ordinary conversation after cancel.')
    assert SupportTicket.objects.count() == 1


def test_guided_page_selection_survives_restart_and_invalid_reply_then_rotates_only_selected_pages():
    account, asset = prepare('pdf.rotate')
    harness = Harness()
    harness.command('/settings')
    harness.click(harness.token('180°'))
    harness.click(harness.token('Choose pages'))

    # Recreate routing as happens on a bot restart; state must live in storage.
    harness.dispatcher = build_dispatcher()
    say(harness, 'not a page number')
    assert BotDraft.objects.get(account=account).input_ids == [str(asset.id)]
    assert not Job.objects.exists()
    say(harness, '1,3')
    draft = BotDraft.objects.get(account=account)
    assert draft.parameters == {'angle': 180, 'pages': '1,3'}
    harness.click(harness.token('Review quote'))
    harness.click(harness.token('Run task'))
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
        harness.click(harness.token('Run task'))

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
    harness.click(harness.token('Run task'))
    job = Job.objects.get(account=account)
    assert job.status == 'succeeded'
    harness.command('/myfiles')
    history = harness.session.calls[-1]
    entry = next(
        button for row in history.reply_markup.inline_keyboard for button in row
        if button.text.startswith('Ready · Rotate pages')
    )
    harness.click(entry.callback_data, uid=43)
    assert not Account.objects.filter(telegram_user_id=43).exists()
    harness.click(entry.callback_data)
    download = harness.token('Send result again')
    output = job.artifacts.get().file
    output.expires_at = timezone.now() - timedelta(seconds=1)
    output.save(update_fields=['expires_at'])
    before = len(harness.session.calls)
    harness.click(download)
    new_calls = harness.session.calls[before:]
    assert not any(isinstance(call, SendDocument) for call in new_calls)
    assert any('expired' in (getattr(call, 'text', '') or '').lower() for call in new_calls)
    assert Job.objects.count() == 1
    assert UsageLedger.objects.filter(kind='consume', meter='file_tasks').count() == 1


def test_long_special_character_file_names_keep_telegram_screens_valid():
    harness = Harness()
    for index in range(6):
        harness.document(f'long-{index}', pdf((220,)), name=('&<>' * 40) + str(index) + '.pdf')
    harness.command('/done')
    assert harness.token('Run task')
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
    assert harness.token('Run task')
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
    assert any('file type' in value.lower() for value in texts(harness))


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
    assert harness.token('Continue current task')


def test_failed_job_retry_requires_new_review_and_explicit_run(settings):
    settings.LOCAL_SYNC_JOBS = False
    account, _ = prepare('pdf.rotate')
    harness = Harness()
    harness.command('/done')
    harness.click(harness.token('Run task'))
    failed = Job.objects.get(account=account)
    settle_job(failed.id, 'failed', error_code='processing_failed')
    harness.click(harness.token('Check status'))
    harness.click(harness.token('Review and try again'))
    assert Job.objects.filter(account=account).count() == 1
    assert BotDraft.objects.get(account=account).quote_id is None
    harness.click(harness.token('Review quote'))
    assert BotDraft.objects.get(account=account).quote_id != failed.quote_id
    assert Job.objects.filter(account=account).count() == 1
    assert harness.token('Run task')
    assert not UsageLedger.objects.filter(account=account, kind='consume').exists()
