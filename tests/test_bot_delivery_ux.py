"""Worker completion and durable Telegram result navigation."""
import asyncio
import io
import re
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone
from pypdf import PdfWriter

from apps.commerce.models import BotDelivery
from apps.core.identity import resolve_account
from apps.core.allowance import file_jobs_this_week
from apps.core.models import Account, BotCallback, BotConversation, BotDraft, FileAsset, Job
from apps.core.services import create_quote, execute_job, settle_job, submit_job, upload_file
from apps.studio.domain import DOCUMENT, EXPORT, SLIDES, pack
from apps.studio.models import EditorDocument, GenerationDraft
from operations import plans as plan_settings
from operations.integrations import save_config
from telegram import bot as bot_module
from telegram.bot import COPY, private_chat, received_edit_rows
from telegram.delivery import RESULT_COPY, app_button, attempt, enqueue, result_controls
from telegram.local import dispatch_local
from telegram.ux_copy import EDIT_BUTTON_COPY, TOOL_NAMES, UX
from tests.test_bot_edit_review import made, screen
from tests.test_bot_generation import customer as chatting, describe, free_customer, tap  # noqa: F401


pytestmark = pytest.mark.django_db(transaction=True)


def completed_job(*, origin='bot', locale='en', execute=True):
    account = resolve_account({'id': 667788, 'first_name': 'Delivery fixture', 'language_code': locale}, is_test=True)
    stream = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    writer.write(stream)
    asset = upload_file(account, SimpleUploadedFile('source.pdf', stream.getvalue()))
    quote = create_quote(account, 'pdf.rotate', [str(asset.id)], {'angle': 90})
    job, _ = submit_job(account, quote.id, 'delivery-ux-job', origin=origin)
    if execute:
        job = execute_job(job.id)
        assert job.status == 'succeeded', job.error_code
    return account, job


def test_worker_completion_atomically_enqueues_one_delivery_without_transport(monkeypatch):
    monkeypatch.setattr('aiogram.Bot.send_document', AsyncMock(side_effect=AssertionError('Settlement must not contact Telegram')))
    account, job = completed_job()
    artifact = job.artifacts.get()
    delivery = BotDelivery.objects.get()
    assert delivery.status == 'pending' and delivery.attempts == 0
    assert delivery.account_id == account.pk and delivery.artifact_id == artifact.pk
    assert delivery.idempotency_key == f'job:{job.id}:{artifact.id}'
    assert enqueue(artifact, delivery.idempotency_key).pk == delivery.pk
    settle_job(job.id, 'succeeded')
    execute_job(job.id)
    assert BotDelivery.objects.count() == 1
    assert Job.objects.get(pk=job.pk).attempt_count == 1 and file_jobs_this_week(account) == 1


def test_delivery_and_settlement_roll_back_together():
    account, job = completed_job(execute=False)
    with pytest.raises(RuntimeError, match='rollback'):
        with transaction.atomic():
            result = execute_job(job.id)
            assert result.status == 'succeeded' and BotDelivery.objects.count() == 1
            raise RuntimeError('rollback')
    job.refresh_from_db()
    assert job.status == 'queued' and not job.artifacts.exists()
    assert not BotDelivery.objects.exists()
    assert file_jobs_this_week(account) == 1, 'the rolled back task is queued and holds its place'


@pytest.mark.parametrize('origin', ['web'])
def test_browser_jobs_do_not_send_unsolicited_telegram_results(origin):
    _, job = completed_job(origin=origin)
    assert job.status == 'succeeded' and not BotDelivery.objects.exists()


def test_unlinked_identity_does_not_fail_successful_processing():
    account, job = completed_job(execute=False)
    Account.objects.filter(pk=account.pk).update(telegram_user_id=None)
    job = execute_job(job.id)
    assert job.status == 'succeeded' and not BotDelivery.objects.exists()


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_result_caption_and_navigation_are_localized_and_owner_bound(locale):
    account, job = completed_job(locale=locale)
    delivery = BotDelivery.objects.get()
    bot = Mock(send_document=AsyncMock(return_value=Mock(message_id=321)))
    asyncio.run(attempt(delivery.id, bot))
    delivery.refresh_from_db()
    assert delivery.status == 'delivered' and delivery.message_id == 321
    args = bot.send_document.await_args
    assert args.args[0] == account.telegram_user_id
    assert args.kwargs['caption'] == RESULT_COPY[locale]['ready']
    buttons = [row[0] for row in args.kwargs['reply_markup'].inline_keyboard]
    assert [button.text for button in buttons] == [UX[locale][key] for key in ('home', 'recent', 'new_task')]
    for button, action in zip(buttons, ('home', 'recent', 'new')):
        callback = BotCallback.objects.get(pk=button.callback_data)
        assert callback.account_id == account.pk and callback.action == action
        assert callback.payload == {'delivery_id': str(delivery.id)}
        assert callback.expires_at == job.artifacts.get().file.expires_at
    asyncio.run(attempt(delivery.id, bot))
    assert bot.send_document.await_count == 1


def _deliver(monkeypatch, locale='en', username='PdfMasterTestBot'):
    monkeypatch.setattr('telegram.delivery.telegram_config', lambda: {'username': username, 'webapp_url': ''})
    account, job = completed_job(locale=locale)
    delivery = BotDelivery.objects.get()
    bot = Mock(send_document=AsyncMock(return_value=Mock(message_id=330)))
    asyncio.run(attempt(delivery.id, bot))
    delivery.refresh_from_db()
    assert delivery.status == 'delivered'
    return account, delivery, bot, bot.send_document.await_args.kwargs


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_a_forwarded_file_carries_a_link_to_the_bot_with_its_owners_referral(monkeypatch, locale):
    from apps.commerce.models import ReferralCode
    account, _, _, sent = _deliver(monkeypatch, locale)
    code = ReferralCode.objects.get(account=account).code
    link = f'https://t.me/PdfMasterTestBot?start=ref_{code}'
    assert sent['parse_mode'] == 'HTML'
    # One short line and nothing else: who made it, linking to the bot.
    expected = {'en': f'✅ 📎 Made with <a href="{link}">@PdfMasterTestBot</a>',
                'uz': f'✅ 📎 <a href="{link}">@PdfMasterTestBot</a> yordamida tayyorlandi',
                'ru': f'✅ 📎 Сделано в <a href="{link}">@PdfMasterTestBot</a>'}[locale]
    assert sent['caption'] == expected


def test_the_forwarded_link_is_a_working_invitation(monkeypatch):
    """Someone new who starts the bot from the link is counted as the owner's invitation."""
    from apps.commerce.models import Referral
    from apps.commerce.services import claim_referral
    from types import SimpleNamespace
    from telegram.onboarding import _pending_for
    owner, _, _, sent = _deliver(monkeypatch)
    start = sent['caption'].split('?start=', 1)[1].split('"', 1)[0]
    # What Telegram sends the bot when the link is opened.
    pending = _pending_for(SimpleNamespace(text=f'/start {start}', document=None, photo=None))
    newcomer = resolve_account({'id': 991122, 'first_name': 'Friend', 'language_code': 'en'}, is_test=True)
    claim_referral(newcomer, pending['referral_code'])
    assert Referral.objects.get(invitee=newcomer).inviter_id == owner.pk


def test_every_delivery_to_one_owner_uses_the_same_referral_code(monkeypatch):
    from apps.commerce.models import ReferralCode
    account, delivery, bot, first = _deliver(monkeypatch)
    BotDelivery.objects.filter(pk=delivery.pk).update(status='retrying', next_attempt_at=timezone.now())
    asyncio.run(attempt(delivery.id, bot))
    assert bot.send_document.await_args.kwargs['caption'] == first['caption']
    assert ReferralCode.objects.filter(account=account).count() == 1


@pytest.mark.parametrize('username', ['', '@', 'bad name', 'x"><script>', 'abc', 'a' * 40])
def test_without_a_valid_bot_username_the_caption_has_no_link(monkeypatch, username):
    _, _, _, sent = _deliver(monkeypatch, username=username)
    assert sent['caption'] == RESULT_COPY['en']['ready'] and '<' not in sent['caption']


def test_a_referral_that_cannot_be_made_still_links_the_bot(monkeypatch):
    def broken(account):
        raise RuntimeError('database hiccup')
    monkeypatch.setattr('apps.commerce.services.referral_code', broken)
    _, _, _, sent = _deliver(monkeypatch, username='@PdfMasterTestBot')
    assert '<a href="https://t.me/PdfMasterTestBot">@PdfMasterTestBot</a>' in sent['caption']


def test_failed_send_reuses_navigation_tokens_and_does_not_recount():
    account, job = completed_job()
    delivery = BotDelivery.objects.get()
    bot = Mock(send_document=AsyncMock(side_effect=RuntimeError('private transport failure')))
    asyncio.run(attempt(delivery.id, bot))
    first_tokens = set(BotCallback.objects.values_list('token', flat=True))
    assert len(first_tokens) == 3
    delivery.refresh_from_db()
    assert delivery.status == 'retrying'
    BotDelivery.objects.filter(pk=delivery.pk).update(next_attempt_at=timezone.now() - timedelta(seconds=1))
    bot.send_document = AsyncMock(return_value=Mock(message_id=322))
    asyncio.run(attempt(delivery.id, bot))
    assert set(BotCallback.objects.values_list('token', flat=True)) == first_tokens
    assert Job.objects.get(pk=job.pk).attempt_count == 1
    assert Job.objects.count() == 1 and file_jobs_this_week(account) == 1


def test_large_result_has_actionable_web_link_without_reading_the_file(monkeypatch):
    _, job = completed_job(locale='uz')
    artifact = job.artifacts.get()
    artifact.file.size_bytes = 51 * 1024 * 1024
    artifact.file.save(update_fields=['size_bytes'])
    monkeypatch.setattr('telegram.delivery.telegram_config', lambda: {'webapp_url': 'https://pdfmaster.example/uz/app'})
    monkeypatch.setattr('apps.core.storage.read_bytes', lambda key: (_ for _ in ()).throw(AssertionError('Large file must not be read')))
    bot = Mock(send_message=AsyncMock(return_value=Mock(message_id=323)), send_document=AsyncMock())
    delivery = BotDelivery.objects.get()
    asyncio.run(attempt(delivery.id, bot))
    delivery.refresh_from_db()
    assert delivery.status == 'delivered' and not bot.send_document.called
    args = bot.send_message.await_args
    assert args.args[1] == RESULT_COPY['uz']['large']
    assert args.kwargs['reply_markup'].inline_keyboard[0][0].url == 'https://pdfmaster.example/uz/app'
    assert len(args.kwargs['reply_markup'].inline_keyboard) == 4


def test_expired_result_does_not_create_navigation_or_call_telegram():
    _, job = completed_job()
    artifact = job.artifacts.get()
    artifact.file.expires_at = timezone.now() - timedelta(seconds=1)
    artifact.file.save(update_fields=['expires_at'])
    bot = Mock(send_document=AsyncMock())
    delivery = BotDelivery.objects.get()
    asyncio.run(attempt(delivery.id, bot))
    delivery.refresh_from_db()
    assert delivery.status == 'failed' and delivery.error_code == 'file_expired'
    assert not BotCallback.objects.exists() and not bot.send_document.called


# ✏️ Edit: the editor opened from the chat, behind the edit_buttons switch.
WEB = 'https://pdfmaster.example/en/app'
PPTX = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'


@pytest.fixture
def web_app():
    save_config('telegram', {'token': '', 'username': 'fixture_bot', 'webapp_url': WEB})


@pytest.fixture
def edit_buttons(monkeypatch, web_app):
    monkeypatch.setenv('EDITOR_FLAG_EDIT_BUTTONS', '1')


@pytest.fixture
def deck_editor(monkeypatch, edit_buttons):
    monkeypatch.setenv('EDITOR_FLAG_DECK_EDITOR', '1')


def result_as(job, *, feature=None, mime=None, kind=None, **metadata):
    """The delivered file of a finished job, turned into the kind of result a test is about."""
    if feature:
        Job.objects.filter(pk=job.pk).update(feature_id=feature)
    asset = job.artifacts.get().file
    asset.mime_type = mime or asset.mime_type
    asset.metadata = {**asset.metadata, **metadata, 'kind': kind or asset.metadata['kind']}
    asset.save(update_fields=['mime_type', 'metadata'])
    return BotDelivery.objects.get(), asset


def keyboard(delivery):
    return result_controls(BotDelivery.objects.select_related('account', 'artifact__file').get(pk=delivery.pk)).inline_keyboard


def edit_button(delivery, locale='en'):
    """The Edit button, always alone on the first row, or None."""
    first = keyboard(delivery)[0]
    return first[0] if first[0].text == UX[locale]['edit'] and len(first) == 1 else None


def deck_draft(account, expires_at=None):
    data = {'sections': [], 'output_format': 'pptx', '_render': {'layouts': {}}}
    return GenerationDraft.objects.create(account=account, feature_id=SLIDES, encrypted_data=pack(data),
                                          expires_at=expires_at or timezone.now() + timedelta(hours=24))


@pytest.mark.parametrize('locale,label', [('en', '✏️ Edit'), ('uz', '✏️ Tahrirlash'), ('ru', '✏️ Изменить')])
def test_a_delivered_pdf_opens_in_the_editor_above_the_buttons_it_always_had(edit_buttons, locale, label):
    _, job = completed_job(locale=locale)
    delivery = BotDelivery.objects.get()
    rows = keyboard(delivery)
    assert rows[0][0].text == label and rows[0][0].url is None, 'a Mini App inside Telegram'
    assert rows[0][0].web_app.url == f'https://pdfmaster.example/{locale}/app/editor?file_id={job.artifacts.get().file_id}'
    assert [row[0].text for row in rows[1:]] == [UX[locale][key] for key in ('home', 'recent', 'new_task')]
    assert all(len(row) == 1 for row in rows), 'one button a row: the longest label still fits a phone'


def test_without_https_the_edit_button_is_a_plain_link(monkeypatch, settings):
    settings.DEBUG = True
    monkeypatch.setenv('EDITOR_FLAG_EDIT_BUTTONS', '1')
    save_config('telegram', {'token': '', 'username': 'fixture_bot', 'webapp_url': 'http://localhost:3000/en/app'})
    _, job = completed_job()
    button = edit_button(BotDelivery.objects.get())
    assert button.web_app is None and button.url == f'http://localhost:3000/en/app/editor?file_id={job.artifacts.get().file_id}'


def test_with_no_web_app_address_the_file_still_arrives_without_the_button(monkeypatch):
    monkeypatch.setenv('EDITOR_FLAG_EDIT_BUTTONS', '1')
    monkeypatch.setattr('telegram.delivery.telegram_config', lambda: {'username': '', 'webapp_url': ''})
    completed_job()
    delivery = BotDelivery.objects.get()
    bot = Mock(send_document=AsyncMock(return_value=Mock(message_id=330)))
    asyncio.run(attempt(delivery.id, bot))
    delivery.refresh_from_db()
    assert delivery.status == 'delivered'
    assert [row[0].text for row in bot.send_document.await_args.kwargs['reply_markup'].inline_keyboard] == [UX['en'][key] for key in ('home', 'recent', 'new_task')]


@pytest.mark.parametrize('feature,mime,kind', [
    ('convert.word_to_pdf', DOCX, 'docx'),
    ('pdf.to_images', 'application/zip', 'archive'),
    ('pdf.to_images', 'image/png', 'image'),
    ('pdf.compress', 'text/plain', 'text'),
    ('pdf.compress', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'xlsx'),
    ('convert.pdf_to_pptx', PPTX, 'pptx'),  # a PowerPoint file of no draft of ours
])
def test_a_file_the_editor_cannot_open_has_no_edit_button(deck_editor, feature, mime, kind):
    _, job = completed_job()
    delivery, _ = result_as(job, feature=feature, mime=mime, kind=kind)
    assert [row[0].text for row in keyboard(delivery)] == [UX['en'][key] for key in ('home', 'recent', 'new_task')]


def test_a_password_protected_result_has_no_edit_button(edit_buttons):
    _, job = completed_job()
    delivery, _ = result_as(job, encrypted=True)
    assert edit_button(delivery) is None


@pytest.mark.parametrize('feature', [SLIDES, EXPORT])
@pytest.mark.parametrize('mime,kind', [(PPTX, 'pptx'), ('application/pdf', 'pdf')])
def test_a_deck_opens_its_slides_only_with_a_live_draft_and_the_deck_editor_on(deck_editor, monkeypatch, feature, mime, kind):
    account, job = completed_job()
    draft = deck_draft(account)
    delivery, _ = result_as(job, feature=feature, mime=mime, kind=kind, generation_draft_id=str(draft.id))
    assert edit_button(delivery).web_app.url == f'{WEB}/editor/deck/{draft.id}'

    GenerationDraft.objects.filter(pk=draft.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    assert edit_button(delivery) is None, 'the slides have gone'

    GenerationDraft.objects.filter(pk=draft.pk).update(expires_at=timezone.now() + timedelta(hours=1))
    assert edit_button(delivery) is not None
    monkeypatch.delenv('EDITOR_FLAG_DECK_EDITOR')
    assert edit_button(delivery) is None, 'the deck editor is off'


@pytest.mark.parametrize('data', [
    {'sections': [], 'output_format': 'pptx'},
    {'sections': [], 'output_format': 'pptx', '_render': {}},
    {'sections': [], 'output_format': 'pdf', '_render': {'layouts': {}}},
], ids=['no_pins', 'empty_pins', 'never_a_powerpoint'])
def test_a_live_draft_the_deck_editor_would_refuse_has_no_edit_button(deck_editor, data):
    account, job = completed_job()
    draft = deck_draft(account)
    GenerationDraft.objects.filter(pk=draft.pk).update(encrypted_data=pack(data))
    Job.objects.filter(pk=job.pk).update(parameters={'generation_draft_id': str(draft.id)})
    delivery, _ = result_as(job, feature=SLIDES, mime=PPTX, kind='pptx', generation_draft_id=str(draft.id))
    assert edit_button(delivery) is None
    assert keyboard(delivery)[0][0].text == '✨ Ask AI to change', 'asking AI still works'


def test_a_draft_that_cannot_be_read_does_not_hold_the_file_back(deck_editor):
    account, job = completed_job()
    draft = deck_draft(account)
    GenerationDraft.objects.filter(pk=draft.pk).update(encrypted_data=b'not what was packed')
    delivery, _ = result_as(job, feature=SLIDES, mime=PPTX, kind='pptx', generation_draft_id=str(draft.id))
    assert edit_button(delivery) is None


def test_another_accounts_deck_is_never_offered(deck_editor):
    account, job = completed_job()
    other = resolve_account({'id': 667799, 'first_name': 'Someone else'}, is_test=True)
    delivery, _ = result_as(job, feature=SLIDES, mime=PPTX, kind='pptx', generation_draft_id=str(deck_draft(other).id))
    assert edit_button(delivery) is None


def test_edit_sits_above_the_ai_change_which_keeps_its_place_and_token(deck_editor):
    account, job = completed_job()
    draft = deck_draft(account)
    Job.objects.filter(pk=job.pk).update(parameters={'generation_draft_id': str(draft.id)})
    delivery, _ = result_as(job, feature=SLIDES, mime=PPTX, kind='pptx', generation_draft_id=str(draft.id))
    rows = keyboard(delivery)
    assert [row[0].text for row in rows] == ['✏️ Edit', '✨ Ask AI to change', UX['en']['home'], UX['en']['recent'], UX['en']['new_task']]
    control = BotCallback.objects.get(action='ai_revise')
    assert rows[1][0].callback_data == control.token and control.payload == {'draft_id': str(draft.id)}


def test_a_document_made_by_ai_edits_as_the_pdf_it_is_even_when_its_draft_has_gone(deck_editor):
    """Its draft is for asking AI to change it; the file itself is what the editor opens."""
    account, job = completed_job()
    draft = GenerationDraft.objects.create(account=account, feature_id=DOCUMENT, encrypted_data=pack({}), expires_at=timezone.now() - timedelta(seconds=1))
    delivery, asset = result_as(job, feature=DOCUMENT, generation_draft_id=str(draft.id))
    assert edit_button(delivery).web_app.url == f'{WEB}/editor?file_id={asset.id}'


def edited_result(job, source_file):
    account = job.account
    document = EditorDocument.objects.create(account=account, file=source_file, input_ids=[str(source_file.id)])
    delivery, _ = result_as(job, feature='editor.visual', editor_document_id=str(document.id))
    return delivery, document


def test_an_edited_pdf_goes_back_to_its_source_with_its_marks(edit_buttons):
    account, job = completed_job()
    source = FileAsset.objects.get(pk=job.input_ids[0])
    delivery, _ = edited_result(job, source)
    assert edit_button(delivery).web_app.url == f'{WEB}/editor?file_id={source.id}'
    assert job.artifacts.get().file_id != source.id


def test_an_edited_pdf_whose_source_has_expired_offers_no_edit(edit_buttons):
    account, job = completed_job()
    source = FileAsset.objects.get(pk=job.input_ids[0])
    delivery, _ = edited_result(job, source)
    FileAsset.objects.filter(pk=source.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    assert edit_button(delivery) is None
    # And the file itself still arrives.
    bot = Mock(send_document=AsyncMock(return_value=Mock(message_id=331)))
    asyncio.run(attempt(delivery.id, bot))
    delivery.refresh_from_db()
    assert delivery.status == 'delivered'
    assert [row[0].text for row in bot.send_document.await_args.kwargs['reply_markup'].inline_keyboard] == [UX['en'][key] for key in ('home', 'recent', 'new_task')]


def test_an_edited_pdf_whose_draft_was_thrown_away_offers_no_edit(edit_buttons):
    account, job = completed_job()
    delivery, document = edited_result(job, FileAsset.objects.get(pk=job.input_ids[0]))
    document.delete()
    assert edit_button(delivery) is None


def test_a_retry_and_a_resend_draw_the_same_edit_button_and_add_no_tokens(edit_buttons):
    _, job = completed_job()
    delivery = BotDelivery.objects.get()
    bot = Mock(send_document=AsyncMock(side_effect=RuntimeError('private transport failure')))
    asyncio.run(attempt(delivery.id, bot))
    first = bot.send_document.await_args.kwargs['reply_markup'].inline_keyboard
    tokens = set(BotCallback.objects.values_list('token', flat=True))
    assert len(tokens) == 3, 'a link holds no token'
    BotDelivery.objects.filter(pk=delivery.pk).update(next_attempt_at=timezone.now() - timedelta(seconds=1))
    bot.send_document = AsyncMock(return_value=Mock(message_id=332))
    asyncio.run(attempt(delivery.id, bot))
    assert bot.send_document.await_args.kwargs['reply_markup'].inline_keyboard == first
    assert set(BotCallback.objects.values_list('token', flat=True)) == tokens

    again = enqueue(job.artifacts.get(), 'resend:one:again')
    assert again.pk != delivery.pk
    bot.send_document = AsyncMock(return_value=Mock(message_id=333))
    asyncio.run(attempt(again.id, bot))
    assert bot.send_document.await_args.kwargs['reply_markup'].inline_keyboard[0] == first[0]


def test_a_result_too_large_for_telegram_keeps_the_way_to_the_file_first(edit_buttons, monkeypatch):
    _, job = completed_job()
    FileAsset.objects.filter(pk=job.artifacts.get().file_id).update(size_bytes=51 * 1024 * 1024)
    monkeypatch.setattr('apps.core.storage.read_bytes', lambda key: (_ for _ in ()).throw(AssertionError('Large file must not be read')))
    bot = Mock(send_message=AsyncMock(return_value=Mock(message_id=334)), send_document=AsyncMock())
    asyncio.run(attempt(BotDelivery.objects.get().id, bot))
    rows = bot.send_message.await_args.kwargs['reply_markup'].inline_keyboard
    assert rows[0][0].url == WEB and rows[1][0].text == '✏️ Edit' and len(rows) == 5


def markup_of(delivery):
    """The keyboard exactly as Telegram gets it, with the random tokens named."""
    rows = keyboard(delivery)
    names = {control.token: control.action for control in BotCallback.objects.all()}
    return [[{**button.model_dump(exclude_none=True), **({'callback_data': names[button.callback_data]} if button.callback_data else {})} for button in row] for row in rows]


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
@pytest.mark.parametrize('deck_flag', [False, True])
def test_with_the_switch_off_a_result_is_exactly_as_it_was(web_app, monkeypatch, locale, deck_flag):
    if deck_flag:
        monkeypatch.setenv('EDITOR_FLAG_DECK_EDITOR', '1')
    account, job = completed_job(locale=locale)
    made_again = {'en': '✏️ Make changes', 'uz': '✏️ O‘zgartirish kiritish', 'ru': '✏️ Внести изменения'}[locale]
    home, recent, new = {'en': ('🏠 Main menu', '🗂 Recent tasks', '➕ New task'), 'uz': ('🏠 Bosh menyu', '🗂 So‘nggi vazifalar', '➕ Yangi vazifa'), 'ru': ('🏠 Главное меню', '🗂 Последние задачи', '➕ Новая задача')}[locale]
    delivery = BotDelivery.objects.get()
    plain = [[{'text': home, 'callback_data': 'home'}], [{'text': recent, 'callback_data': 'recent'}], [{'text': new, 'callback_data': 'new'}]]
    assert markup_of(delivery) == plain

    draft = deck_draft(account)
    Job.objects.filter(pk=job.pk).update(parameters={'generation_draft_id': str(draft.id)})
    delivery, _ = result_as(job, feature=SLIDES, mime=PPTX, kind='pptx', generation_draft_id=str(draft.id))
    assert markup_of(delivery) == [[{'text': made_again, 'callback_data': 'ai_revise'}], *plain]


def test_the_ai_wording_is_new_only_with_the_switch_on():
    assert UX['en']['ai_revise'] == '✏️ Make changes' and UX['en']['ai_edits_used'].startswith('✏️ ')
    for locale in UX:
        assert UX[locale][EDIT_BUTTON_COPY['ai_revise']].startswith('✨ ')
        assert UX[locale][EDIT_BUTTON_COPY['ai_edits_used']] == UX[locale]['ai_edits_used'].removeprefix('✏️ ')
    assert (UX['uz']['ai_ask_to_change'], UX['ru']['ai_ask_to_change']) == ('✨ AI bilan o‘zgartirish', '✨ Изменить с ИИ')


def test_the_new_copy_is_in_three_languages_and_uzbek_is_latin():
    for key in ('edit', 'send_to_chat', 'editor_hint', 'ai_ask_to_change', 'ai_edits_used_plain'):
        assert all(UX[locale][key] for locale in ('en', 'uz', 'ru'))
        assert not re.search('[А-Яа-яЁё\'’`]', UX['uz'][key]), UX['uz'][key]
        for locale in ('en', 'uz', 'ru'):
            assert not re.search(r'click|export|quote|rasteri|dpi|points|encoding', UX[locale][key], re.I), UX[locale][key]


def test_app_buttons_need_https():
    assert app_button('x', 'https://a.example/en/app').web_app.url == 'https://a.example/en/app'
    assert app_button('x', 'https://a.example/en/app').url is None
    assert app_button('x', 'http://localhost:3000/en/app').web_app is None
    assert app_button('x', 'http://localhost:3000/en/app').url == 'http://localhost:3000/en/app'


# The whole round, through the simulator.
def pdf_upload(name='notes.pdf'):
    stream = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    writer.write(stream)
    return SimpleUploadedFile(name, stream.getvalue(), 'application/pdf')


def outbound(result):
    return [message for message in result['messages'] if message['direction'] == 'outbound']


def shown_rows(message):
    return [[button['label'] for button in row] for row in message['buttons']]


def sent_file(result):
    return [message for message in outbound(result) if message['asset']][-1]


@pytest.mark.usefixtures('bot_verification_disabled', 'edit_buttons')
def test_a_pdf_sent_to_the_bot_and_its_result_both_show_the_row(chatting):
    received = dispatch_local(chatting, uploaded=pdf_upload())
    screen_ = outbound(received)[-1]
    asset = FileAsset.objects.filter(account=chatting).latest('created_at')
    assert screen_['buttons'][0] == [{'label': '✏️ Edit', 'callback_data': None, 'url': f'{WEB}/editor?file_id={asset.id}'}]
    assert any(TOOL_NAMES['pdf.rotate']['en'] in label for row in shown_rows(screen_) for label in row), 'every tool is still offered'
    assert BotDraft.objects.get(account=chatting).input_ids == [str(asset.id)], 'and the file still waits for one'

    chosen = tap(chatting, received, TOOL_NAMES['pdf.rotate']['en'])
    assert not any('Edit' == label.split(' ')[-1] for row in shown_rows(outbound(chosen)[-1]) for label in row), 'a chosen tool has its own screen'
    done = tap(chatting, chosen, '90°')
    delivered = tap(chatting, done, 'Start')
    file = sent_file(delivered)
    assert file['buttons'][0][0]['label'] == '✏️ Edit'
    assert file['buttons'][0][0]['url'] == f"{WEB}/editor?file_id={file['asset']['id']}"


@pytest.mark.usefixtures('bot_verification_disabled', 'edit_buttons')
def test_a_pdf_sent_for_a_tool_chosen_first_keeps_start_on_top(chatting):
    first = dispatch_local(chatting, text='/tools')
    tap(chatting, first, TOOL_NAMES['pdf.compress']['en'])
    rows = shown_rows(outbound(dispatch_local(chatting, uploaded=pdf_upload()))[-1])
    assert rows[0] == ['▶️ Start'] and rows[1] == ['✏️ Edit'], rows


@pytest.mark.usefixtures('bot_verification_disabled', 'edit_buttons')
def test_files_collected_for_a_merge_show_no_row(chatting):
    first = dispatch_local(chatting, text='/tools')
    tap(chatting, first, TOOL_NAMES['pdf.merge']['en'])
    for name in ('one.pdf', 'two.pdf'):
        rows = shown_rows(outbound(dispatch_local(chatting, uploaded=pdf_upload(name)))[-1])
        assert '✏️ Edit' not in [label for row in rows for label in row], rows


@pytest.mark.usefixtures('bot_verification_disabled', 'edit_buttons')
def test_a_pdf_sent_for_an_ai_document_stays_that_documents(chatting):
    tap(chatting, dispatch_local(chatting, text='/ai'), 'PDF on a topic')
    rows = shown_rows(outbound(dispatch_local(chatting, uploaded=pdf_upload()))[-1])
    assert '✏️ Edit' not in [label for row in rows for label in row], rows
    assert BotConversation.objects.get(pk=chatting.telegram_user_id).state == 'ai_input'


@pytest.mark.usefixtures('edit_buttons')
def test_a_web_app_button_is_not_offered_outside_a_private_chat(chatting):
    """Telegram refuses one in a group, and the whole screen with it."""
    asset = upload_file(chatting, pdf_upload())
    private, group = SimpleNamespace(chat=SimpleNamespace(id=chatting.telegram_user_id)), SimpleNamespace(chat=SimpleNamespace(id=-100123))
    assert asyncio.run(received_edit_rows(private, chatting, [str(asset.id)]))[0][0].web_app.url == f'{WEB}/editor?file_id={asset.id}'
    assert asyncio.run(received_edit_rows(group, chatting, [str(asset.id)])) == []
    assert private_chat(SimpleNamespace(chat_id=5)), 'a screen kept from an album has only its chat id'


@pytest.mark.usefixtures('bot_verification_disabled', 'web_app')
def test_with_the_switch_off_the_chat_is_exactly_as_it_was(chatting, monkeypatch):
    monkeypatch.setenv('EDITOR_FLAG_DECK_EDITOR', '1')
    calls = []
    monkeypatch.setattr('telegram.bot.app_button', lambda *args: calls.append(args))
    screen_ = outbound(dispatch_local(chatting, uploaded=pdf_upload()))[-1]
    assert screen_['text'] == '📎 notes.pdf\n' + COPY['en']['choose_pdf_action']
    assert shown_rows(screen_)[-1] == [UX['en']['home'], COPY['en']['web_tools']] and len(screen_['buttons']) == 5
    assert not any(label == '✏️ Edit' for row in shown_rows(screen_) for label in row)

    editor = outbound(dispatch_local(chatting, text='/editor'))[-1]
    asset = FileAsset.objects.filter(account=chatting).latest('created_at')
    assert editor['text'] == COPY['en']['web_hint']
    assert [[button['label'] for button in row] for row in editor['buttons']] == [[COPY['en']['open']], [UX['en']['home']]]
    assert editor['buttons'][0][0]['url'] == f'{WEB}/editor?file_id={asset.id}'
    assert calls == [], 'a link, not a Mini App'


@pytest.mark.usefixtures('bot_verification_disabled', 'edit_buttons')
def test_the_editor_command_opens_the_editor_inside_telegram(chatting, monkeypatch):
    opened = []
    real = bot_module.app_button
    monkeypatch.setattr('telegram.bot.app_button', lambda label, url: opened.append((label, url)) or real(label, url))
    empty = outbound(dispatch_local(chatting, text='/editor'))[-1]
    assert empty['text'] == UX['en']['editor_hint'] and opened[-1] == ('✏️ Edit', f'{WEB}/editor')
    assert shown_rows(empty) == [['✏️ Edit'], [UX['en']['home']]]

    dispatch_local(chatting, uploaded=pdf_upload())
    asset = FileAsset.objects.filter(account=chatting).latest('created_at')
    dispatch_local(chatting, text='/editor')
    assert opened[-1] == ('✏️ Edit', f'{WEB}/editor?file_id={asset.id}'), 'the file in the chat comes along'

    FileAsset.objects.filter(pk=asset.pk).update(mime_type=DOCX, metadata={**asset.metadata, 'kind': 'docx'})
    dispatch_local(chatting, text='/editor')
    assert opened[-1] == ('✏️ Edit', f'{WEB}/editor'), 'not one the editor would refuse'


@pytest.mark.usefixtures('bot_verification_disabled', 'edit_buttons')
def test_the_editor_command_is_a_plain_link_in_development(chatting):
    save_config('telegram', {'token': '', 'username': 'fixture_bot', 'webapp_url': 'http://localhost:3000/en/app'})
    editor = outbound(dispatch_local(chatting, text='/editor'))[-1]
    assert editor['buttons'][0][0]['url'] == 'http://localhost:3000/en/app/editor'


@pytest.mark.usefixtures('bot_verification_disabled', 'deck_editor')
def test_a_deck_delivered_in_the_chat_shows_the_row_and_asks_ai_with_the_new_words(chatting):
    delivered = made(chatting)
    file = sent_file(delivered)
    draft = GenerationDraft.objects.get(account=chatting, feature_id=SLIDES)
    assert file['asset']['name'].endswith('.pptx'), file['asset']
    assert file['buttons'][0][0]['label'] == '✏️ Edit'
    assert file['buttons'][0][0]['url'] == f'{WEB}/editor/deck/{draft.id}'
    assert shown_rows(file)[1] == ['✨ Ask AI to change']
    asked = tap(chatting, delivered, 'Ask AI to change')
    assert BotConversation.objects.get(pk=chatting.telegram_user_id).state == 'ai_revise', asked['messages'][-1]


@pytest.mark.usefixtures('bot_verification_disabled', 'edit_buttons')
def test_a_deck_delivered_with_the_deck_editor_off_has_no_row(chatting):
    file = sent_file(made(chatting))
    assert shown_rows(file)[0] == ['✨ Ask AI to change'], shown_rows(file)


@pytest.mark.usefixtures('bot_verification_disabled', 'edit_buttons')
def test_a_document_delivered_in_the_chat_shows_the_row(chatting):
    delivered = tap(chatting, describe(chatting, 'A 1 page guide to tide tables.\n\n' + ' '.join(['tide'] * 390)), 'Generate')
    file = sent_file(delivered)
    assert file['buttons'][0][0]['url'] == f"{WEB}/editor?file_id={file['asset']['id']}"
    assert shown_rows(file)[:2] == [['✏️ Edit'], ['✨ Ask AI to change']]


@pytest.mark.usefixtures('bot_verification_disabled', 'edit_buttons')
def test_the_review_of_a_change_counts_edits_without_the_pencil(free_customer):
    plan_settings.save('free', {'edits_per_file': 3})
    delivered = made(free_customer)
    tap(free_customer, delivered, 'Ask AI to change')
    review = dispatch_local(free_customer, text='Use a friendlier tone throughout.')
    words, labels = screen(review)
    assert '\nEdits of this file: 0 of 3 used' in words and '✏️ Edits of this file' not in words, words
    assert '✨ Ask AI to change' in labels, labels
