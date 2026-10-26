"""Photos made into one PDF are one file task of the week, however many photos.

The bot takes photos in an album, one by one or sent as files; the web takes
them in one upload. Either way they make one quote and one job, and that one
job is all the week counts. A Free customer with one task left can still make
a PDF of many photos, and a job that failed gives its place back.
"""
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from apps.commerce.models import LocalBotMessage
from apps.core.allowance import file_jobs_this_week, usage_snapshot
from apps.core.errors import DomainError
from apps.core.identity import resolve_account
from apps.core.models import BotCallback, BotConversation, BotDraft, FileAsset, Job, Quote
from apps.core.services import create_quote, submit_job
from tests.test_bot_no_flood import Chat
from tests.test_platform import login_client

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]

FREE_WEEK = 15


@pytest.fixture
def customer(settings, monkeypatch):
    import telegram.bot as bot
    monkeypatch.setattr(bot, 'ALBUM_SETTLE', 0)
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    settings.LOCAL_SYNC_JOBS = True
    account = resolve_account({'id': 985001, 'first_name': 'Photo chat'}, is_test=True)
    BotConversation.objects.create(telegram_user_id=account.telegram_user_id, locale='en', language_selected_at=timezone.now())
    return account


@pytest.fixture(autouse=True)
def photos_kept_as_sent(monkeypatch):
    """The scanner's weights are fetched only for CI and the image build, and
    what the week counts does not depend on them: each photo is kept as sent,
    and the real processor still makes a PDF of one page per photo."""
    import processors.scanner as scanner
    from processors import engine, sandbox
    monkeypatch.setattr(scanner, 'scan_photo', lambda image, paper='auto': (image, {'document_detected': False, 'sheet': None}))
    monkeypatch.setattr(sandbox, 'execute_sandbox', lambda feature, paths, parameters, out, **kwargs:
                        engine.execute(feature, paths, parameters, out))


def jpeg(shade=240):
    stream = io.BytesIO()
    Image.new('RGB', (240, 320), (shade, shade, shade - 5)).save(stream, format='JPEG')
    return stream.getvalue()


def png():
    stream = io.BytesIO()
    Image.new('RGB', (240, 320), (236, 236, 230)).save(stream, format='PNG')
    return stream.getvalue()


def photo(index, group=None):
    """A photo as the bot receives it: Telegram calls every photo photo.jpg."""
    return {'uploaded': SimpleUploadedFile('photo.jpg', jpeg(230 + index), 'image/jpeg'), 'media_group_id': group}


def used_up(account, count):
    """Tasks already made this week, as finished jobs."""
    for _ in range(count):
        quote = Quote.objects.create(account=account, feature_id='pdf.merge', expires_at=timezone.now())
        Job.objects.create(account=account, quote=quote, feature_id='pdf.merge', status='succeeded',
                           idempotency_key=str(quote.id), request_hash='x')


def start_button(chat):
    """The Start button on the newest screen, or None when the week is used up."""
    newest = LocalBotMessage.objects.filter(account=chat.account, direction='outbound').order_by('-created_at').first()
    for row in newest.buttons:
        for button in row:
            data = button.get('callback_data')
            if data and BotCallback.objects.filter(pk=data, action='run').exists():
                return data
    return None


def run(chat):
    """Taps Start on the PDF-from-images screen and returns the job it made."""
    before = set(Job.objects.filter(account=chat.account).values_list('id', flat=True))
    chat.tap('run')
    made = Job.objects.filter(account=chat.account).exclude(id__in=before)
    assert made.count() == 1, 'one Start makes one job'
    return made.get()


def images_jobs(account):
    return Job.objects.filter(account=account, feature_id='pdf.images_to_pdf')


# ---------------------------------------------------------------- bot


def test_an_album_of_photos_is_one_file_task(customer):
    chat = Chat(customer)
    for index in range(6):
        chat.do(**photo(index, group='album-1'))
    draft = BotDraft.objects.get(account=customer)
    assert draft.feature_id == 'pdf.images_to_pdf' and len(draft.input_ids) == 6
    assert 'File tools this week: 0 of 15' in chat.last(), 'nothing counts before Start'
    assert file_jobs_this_week(customer) == 0
    job = run(chat)
    assert job.status == 'succeeded' and len(job.input_ids) == 6
    assert images_jobs(customer).count() == 1
    assert file_jobs_this_week(customer) == 1
    assert usage_snapshot(customer)['file_jobs'] == {'limit': FREE_WEEK, 'used': 1, 'remaining': FREE_WEEK - 1}
    assert job.artifacts.get().file.page_count == 6


def test_photos_sent_one_by_one_and_as_files_are_one_file_task(customer):
    chat = Chat(customer)
    for index in range(4):
        chat.do(**photo(index))
        assert file_jobs_this_week(customer) == 0, 'a photo on its own is not a task'
    # A photo sent as a file, uncompressed, joins the same PDF.
    chat.do(uploaded=SimpleUploadedFile('scan.png', png(), 'image/png'))
    draft = BotDraft.objects.get(account=customer)
    assert len(draft.input_ids) == 5
    assert Quote.objects.filter(account=customer).count() >= 5, 'each screen prices the draft again'
    job = run(chat)
    assert job.status == 'succeeded' and len(job.input_ids) == 5
    assert file_jobs_this_week(customer) == 1, 'quotes are not tasks; the one job is'


def test_two_albums_in_one_go_are_still_one_pdf_and_one_task(customer):
    chat = Chat(customer)
    for index in range(3):
        chat.do(**photo(index, group='first'))
    for index in range(3, 7):
        chat.do(**photo(index, group='second'))
    assert len(BotDraft.objects.get(account=customer).input_ids) == 7
    run(chat)
    assert images_jobs(customer).count() == 1 and file_jobs_this_week(customer) == 1


def test_the_last_task_of_the_week_takes_any_number_of_photos(customer):
    used_up(customer, FREE_WEEK - 1)
    chat = Chat(customer)
    for index in range(12):
        chat.do(**photo(index, group='big-album'))
    screen = chat.last()
    assert f'File tools this week: {FREE_WEEK - 1} of {FREE_WEEK}' in screen
    job = run(chat)
    assert job.status == 'succeeded' and len(job.input_ids) == 12
    assert file_jobs_this_week(customer) == FREE_WEEK
    # Only now is the week used up, by tasks, not by photos.
    chat.do(**photo(0))
    assert len(BotDraft.objects.get(account=customer).input_ids) == 1, 'the next photo starts a new PDF'
    assert start_button(chat) is None, 'at the limit Start becomes Plans'


def test_a_failed_pdf_gives_its_place_back_and_the_retry_counts_once(customer, monkeypatch):
    import processors.sandbox as sandbox

    def broken(*args, **kwargs):
        raise RuntimeError('the engine fell over')

    chat = Chat(customer)
    for index in range(5):
        chat.do(**photo(index, group='retry'))
    with monkeypatch.context() as patch:
        patch.setattr(sandbox, 'execute_sandbox', broken)
        failed = run(chat)
    assert failed.status == 'failed'
    assert file_jobs_this_week(customer) == 0, 'a failed job made nothing and counts nothing'
    # The same photos again: a new draft is needed, since the old one was submitted.
    for index in range(5):
        chat.do(**photo(index, group='retry-2'))
    retried = run(chat)
    assert retried.status == 'succeeded'
    assert file_jobs_this_week(customer) == 1


def test_tapping_start_twice_makes_one_job(customer):
    chat = Chat(customer)
    for index in range(3):
        chat.do(**photo(index, group='twice'))
    start = start_button(chat)
    chat.do(callback_data=start)
    try:
        chat.do(callback_data=start)
    except DomainError:
        pass
    assert images_jobs(customer).count() == 1 and file_jobs_this_week(customer) == 1


# ---------------------------------------------------------------- web


def web_upload(client, name, data, mime):
    response = client.post('/api/v1/files/uploads', {'file': SimpleUploadedFile(name, data, mime)})
    assert response.status_code == 201, response.content
    return response.json()['id']


def test_the_web_makes_one_task_of_many_photos(customer):
    used_up(customer, FREE_WEEK - 1)
    client = login_client(customer)
    ids = [web_upload(client, f'page-{index}.jpg', jpeg(230 + index), 'image/jpeg') for index in range(8)]
    quote = client.post('/api/v1/quotes', {'feature_id': 'pdf.images_to_pdf', 'input_ids': ids, 'parameters': {}},
                        content_type='application/json')
    assert quote.status_code == 201, quote.content
    body = quote.json()
    assert body['affordable'] is True, 'eight photos need one place, and one is left'
    assert body['usage']['file_jobs'] == {'limit': FREE_WEEK, 'used': FREE_WEEK - 1, 'remaining': 1}
    job = client.post('/api/v1/jobs', {'quote_id': body['id']}, content_type='application/json',
                      HTTP_IDEMPOTENCY_KEY='eight-photos-one-pdf')
    assert job.status_code == 201, job.content
    assert job.json()['status'] == 'succeeded'
    assert client.get('/api/v1/usage').json()['file_jobs'] == {'limit': FREE_WEEK, 'used': FREE_WEEK, 'remaining': 0}
    assert images_jobs(customer).count() == 1


def test_uploads_and_quotes_alone_never_count(customer):
    client = login_client(customer)
    ids = [web_upload(client, f'page-{index}.jpg', jpeg(230 + index), 'image/jpeg') for index in range(5)]
    for _ in range(3):
        create_quote(customer, 'pdf.images_to_pdf', ids, {})
    assert FileAsset.objects.filter(account=customer).count() == 5
    assert file_jobs_this_week(customer) == 0
    quote = create_quote(customer, 'pdf.images_to_pdf', ids, {})
    submit_job(customer, quote.id, 'five-photos')
    assert file_jobs_this_week(customer) == 1


# ---------------------------------------------------------------- admin


def test_the_admin_says_what_was_used_not_only_what_is_left(customer):
    from tests.test_operations_admin import staff_client
    chat = Chat(customer)
    for index in range(6):
        chat.do(**photo(index, group='admin'))
    run(chat)
    admin, _ = staff_client()
    page = admin.get(f'/ops/users/{customer.id}').content.decode()
    assert '<strong>1 of 15 used · 14\u00a0left</strong>' in page, 'six photos, one task'
    assert '<strong>0 of 5 used · 5\u00a0left</strong>' in page
    assert 'style="width:7%"' in page, 'the bar fills with what was used, as on the web'
    assert 'Left this week' not in page
