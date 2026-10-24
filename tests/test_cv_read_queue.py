"""The files a CV is made from wait their turn in a queue, read by `runreader`, never in a request.

The owner asked for a queue instead of "try again": before it, the files
were read inside the API request (two sync workers) and inside the bot,
behind a lock, and a second customer reading at the same time was told to
try again. Now an upload for a CV queues its file's read
(apps/studio/cv/reads.py), the reader reads one file at a time with the
accounts taking turns, and a draft is made from what it kept, or is refused
with `cv_reading` saying how many reads are ahead. These tests follow the
queue (its order, two readers, a reader that dies or is stopped), what is
kept (encrypted, gone with the file), the drafts and the API around it.
Everyone in them is fictional (example.com contacts).
"""
import json
import os
import signal
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection
from django.utils import timezone

from apps.core.errors import DomainError, error_data
from apps.core.services import upload_file
from apps.studio import extraction
from apps.studio.cv import reads, sources
from apps.studio.domain import CV, create_draft, unpack, update_draft
from apps.studio.models import CvSourceRead
from tests.test_cv_content import customer  # noqa: F401  (a fixture)
from tests.test_cv_sources import _lines, _pdf, one_column_pdf
from tests.test_platform import account, login_client

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parents[1]
TEXT = 'Timur Rakhimov, +998 90 123 45 67, lead engineer at Example Motors since 2020; MSc Mechanical Engineering.'


@pytest.fixture
def queued(settings):
    """As in production: a file is queued as it is uploaded and read only by the reader."""
    settings.LOCAL_SYNC_JOBS = False


class Reader:
    """extraction.read_cv as a fake: each file gives TEXT, or fails when its name says 'bad'; the files it read."""

    def __init__(self):
        self.read = []

    def __call__(self, path, kind, *, ocr_pages, seconds):
        self.read.append(kind)
        if Path(str(path)).name in self.failing:
            raise DomainError('source_extraction_failed')
        return {'pages': [{'page': 1, 'text': TEXT}], 'names': ['Timur Rakhimov'], 'ocr_pages': 0, 'ocr_skipped': 0}

    failing = set()


@pytest.fixture
def reader(monkeypatch):
    fake = Reader()
    fake.failing = set()
    monkeypatch.setattr(extraction, 'read_cv', fake)
    return fake


def cv_file(owner, name='old-cv.pdf', raw=None):
    """A file uploaded for a CV, as the web and the bot upload one."""
    return upload_file(owner, SimpleUploadedFile(name, raw or one_column_pdf()), 'web', purpose='cv_source')


def read_of(asset):
    return CvSourceRead.objects.get(asset=asset)


def made_from(owner, *assets):
    return {'feature_id': CV, 'source_ids': [str(asset.id) for asset in assets], 'options': {'cv_source': 'file'}}


def refused(owner, data):
    with pytest.raises(DomainError) as error:
        create_draft(owner, data)
    return error.value


# --- The order of the queue -------------------------------------------------------------------

def test_reads_are_first_in_first_out_and_the_accounts_take_turns(queued, reader, customer):
    other = account(77)
    screenshots = [cv_file(customer, f'shot-{number}.pdf') for number in range(3)]
    single = cv_file(other, 'old-cv.pdf')
    # Nobody served yet: oldest first, then each account a read a round.
    order, reading = reads.queue()
    assert reading == 0
    assert [row.asset_id for row in order] == [screenshots[0].id, single.id, screenshots[1].id, screenshots[2].id]
    taken = []
    while True:
        row = reads.claim()
        if row is None:
            break
        taken.append(row.asset_id)
        reads.perform(row)
    # The other account's one PDF waited for one screenshot, not three.
    assert taken == [screenshots[0].id, single.id, screenshots[1].id, screenshots[2].id]
    assert {read_of(asset).status for asset in [*screenshots, single]} == {'done'}
    assert reader.read == ['pdf'] * 4


def test_the_account_served_longest_ago_goes_first_and_a_read_that_waited_long_goes_ahead(queued, reader, customer):
    other = account(77)
    first = cv_file(customer, 'first.pdf')
    reads.perform(reads.claim())
    assert read_of(first).status == 'done'
    mine, theirs = cv_file(customer, 'mine.pdf'), cv_file(other, 'theirs.pdf')
    # The account just served waits behind one that never was, though its read is older.
    assert [row.asset_id for row in reads.queue()[0]] == [theirs.id, mine.id]
    # Waited AGING_SECONDS, it goes ahead whoever was served last.
    CvSourceRead.objects.filter(asset=mine).update(created_at=timezone.now() - timedelta(seconds=reads.AGING_SECONDS + 1))
    assert [row.asset_id for row in reads.queue()[0]] == [mine.id, theirs.id]


def claimed_in_turn():
    """Every queued read taken as the reader takes them, one after another: the files in the order they were read."""
    taken = []
    while True:
        row = reads.claim()
        if row is None:
            return taken
        taken.append(row.asset_id)
        reads.perform(row)


def test_the_place_said_is_the_place_read_in_when_reads_have_waited_long(queued, reader, customer):
    other, third = account(77), account(78)
    aged = timezone.now() - timedelta(seconds=reads.AGING_SECONDS + 60)
    backlog = [cv_file(other, f'shot-{number}.pdf') for number in range(10)]
    for number, asset in enumerate(backlog):
        CvSourceRead.objects.filter(asset=asset).update(created_at=aged + timedelta(seconds=number))
    mine = cv_file(customer, 'old-cv.pdf')
    # Every read that waited long goes first, all ten: this one is told ten ahead, not one.
    order, reading = reads.queue()
    assert reads.places(order, reading)[read_of(mine).pk] == 10
    assert reads.state(customer, [mine])['ahead'] == 10
    assert refused(customer, made_from(customer, mine)).params['ahead'] == 10
    # Some of a third account's reads aged too, some not: the order said is the order they are read in.
    for number in range(2):
        asset = cv_file(third, f'aged-{number}.pdf')
        CvSourceRead.objects.filter(asset=asset).update(created_at=aged + timedelta(seconds=20 + number))
    fresh = [cv_file(third, f'fresh-{number}.pdf') for number in range(3)]
    said = [row.asset_id for row in reads.queue()[0]]
    assert said[:12] == [*[asset.id for asset in backlog], *said[10:12]] and said.index(mine.id) == 12
    assert said == claimed_in_turn()
    assert said[12:] == [mine.id, *[asset.id for asset in fresh]]


def test_a_read_taken_by_one_reader_is_never_taken_by_another(queued, customer):
    first, second = cv_file(customer, 'first.pdf'), cv_file(customer, 'second.pdf')
    row = reads.queue()[0][0]
    # Two readers chose the same read: the one that takes it first has it; the other gets nothing.
    assert reads.take(row) is not None and reads.take(row) is None
    # A second reader asking next is given the next read.
    assert reads.claim().asset_id == second.id and reads.claim() is None
    assert read_of(first).attempts == 1 and read_of(second).status == 'reading'


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != 'postgresql', reason='SKIP LOCKED needs PostgreSQL; SQLite has no row locks')
def test_a_second_reader_passes_over_the_read_the_first_holds_without_waiting(settings):
    from django.db import connections, transaction
    settings.LOCAL_SYNC_JOBS = False
    owner = account(91)
    first, second = cv_file(owner, 'first.pdf'), cv_file(owner, 'second.pdf')
    held, release = threading.Event(), threading.Event()

    def first_reader():
        try:
            with transaction.atomic():
                CvSourceRead.objects.select_for_update().get(asset=first)
                held.set()
                release.wait(10)
        finally:
            connections.close_all()
    thread = threading.Thread(target=first_reader)
    thread.start()
    try:
        assert held.wait(10)
        begun = time.monotonic()
        taken = reads.claim()
        assert taken.asset_id == second.id and time.monotonic() - begun < 3
    finally:
        release.set()
        thread.join()
    assert read_of(first).status == 'queued'


# --- A reader that dies, or is stopped --------------------------------------------------------

def test_a_read_lost_with_its_reader_is_read_again_and_failed_after_its_attempts(queued, reader, customer):
    asset = cv_file(customer)
    for attempt in range(1, reads.MAX_ATTEMPTS + 1):
        row = reads.claim()
        assert row is not None and row.attempts == attempt
        # The reader's container is killed mid-read; its lease lapses.
        CvSourceRead.objects.filter(pk=row.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        assert reads.sweep() == 1
        lost = read_of(asset)
        if attempt < reads.MAX_ATTEMPTS:
            assert lost.status == 'queued' and lost.lease_expires_at is None
    assert lost.status == 'failed' and lost.error == 'reader_interrupted' and reader.read == []
    # A read whose lease has not lapsed is left to its reader.
    other = cv_file(customer, 'other.pdf')
    reads.claim()
    assert reads.sweep() == 0 and read_of(other).status == 'reading'


def test_a_reader_whose_read_was_given_up_cannot_overwrite_the_one_that_took_it_again(queued, customer):
    asset = cv_file(customer)
    stale = reads.claim()
    CvSourceRead.objects.filter(pk=stale.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
    reads.sweep()
    fresh = reads.claim()
    assert fresh.attempts == 2
    assert not reads.finish(stale, 'failed', error='reader_error')
    assert reads.finish(fresh, 'done', result={'pages': [{'page': 1, 'text': TEXT}], 'names': [], 'ocr_pages': 0,
                                               'ocr_skipped': 0})
    assert read_of(asset).status == 'done' and read_of(asset).error == ''


def test_the_reader_finishes_the_read_in_hand_on_sigterm_and_takes_no_other(queued, customer, monkeypatch):
    first, second = cv_file(customer, 'first.pdf'), cv_file(customer, 'second.pdf')
    seen = []

    def read_file(asset):
        seen.append(asset.id)
        # The deploy stops the container while this file is being read.
        os.kill(os.getpid(), signal.SIGTERM)
        return {'pages': [{'page': 1, 'text': TEXT}], 'names': [], 'ocr_pages': 0, 'ocr_skipped': 0}
    monkeypatch.setattr(reads, 'read_file', read_file)
    before = signal.getsignal(signal.SIGTERM)
    call_command('runreader')  # Without --once: it returns only because it was asked to stop.
    assert seen == [first.id]
    assert read_of(first).status == 'done' and read_of(second).status == 'queued'
    assert signal.getsignal(signal.SIGTERM) is before


def test_a_linkedin_export_is_read_by_the_real_reader_and_its_cv_made_from_what_was_kept(queued, customer):
    from tests.test_cv_sources import linkedin_pdf
    export = cv_file(customer, 'Profile.pdf', linkedin_pdf())
    data = {'feature_id': CV, 'source_ids': [str(export.id)], 'options': {'cv_source': 'linkedin'}}
    assert refused(customer, data).code == 'cv_reading'
    call_command('runreader', '--once')
    row = read_of(export)
    assert row.status == 'done' and row.pages == 2 and row.ocr_pages == 0, row.error
    made = unpack(create_draft(customer, data).encrypted_data)
    assert made['title'] == 'Dilnoza Karimova'
    assert 'dilnoza.karimova@example.com' in made['excerpts'][0]['text']


def test_runreader_once_reads_what_is_queued_and_stops(queued, reader, customer):
    assets = [cv_file(customer, f'page-{number}.pdf') for number in range(2)]
    call_command('runreader', '--once')
    assert [read_of(asset).status for asset in assets] == ['done', 'done'] and reader.read == ['pdf', 'pdf']


# --- What is kept -------------------------------------------------------------------------------

def test_what_a_file_gave_is_encrypted_at_rest(queued, reader, customer):
    asset = cv_file(customer)
    reads.next_read()
    row = read_of(asset)
    assert row.status == 'done' and row.pages == 1 and row.ocr_pages == 0
    assert reads.result_of(row)['pages'][0]['text'] == TEXT
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT * FROM {CvSourceRead._meta.db_table}')
        stored = repr(cursor.fetchall())
    for words in ('Timur', 'Rakhimov', 'Example Motors'):
        assert words not in stored
    assert b'Timur' not in bytes(row.encrypted_result)


def test_a_read_goes_with_its_file(queued, reader, customer):
    from apps.core.services import cleanup_expired
    deleted, expired, revoked = cv_file(customer, 'a.pdf'), cv_file(customer, 'b.pdf'), cv_file(customer, 'c.pdf')
    call_command('runreader', '--once')
    deleted.delete()
    assert not CvSourceRead.objects.filter(asset_id=deleted.id).exists()
    # Expired with its file (24 hours), and gone when the customer deletes the file.
    type(expired).objects.filter(pk=expired.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    cleanup_expired()
    assert not CvSourceRead.objects.filter(asset_id=expired.id).exists()
    assert login_client(customer).delete(f'/api/v1/files/{revoked.id}').status_code == 200
    assert not CvSourceRead.objects.filter(asset_id=revoked.id).exists()


def test_a_file_no_cv_reads_is_failed_at_once_and_never_waited_for(queued, customer):
    from tests.test_cv_sources import encrypted_pdf, picture
    webp = cv_file(customer, 'old-cv.webp', picture(one_column_pdf(), 1.0, 'WEBP'))
    locked = upload_file(customer, SimpleUploadedFile('locked.pdf', encrypted_pdf()), 'web', password='fictional-password',
                         purpose='cv_source')
    # More pages than any CV is made from: refused at once, never read for the minute it would take.
    long = cv_file(customer, 'long.pdf', _pdf(lambda page, number: _lines(page, 60, 780, [
        ('Helvetica', 11, f'Page {number} of a long report, not a CV', 14)]), sources.MAX_PAGES + 10))
    assert (read_of(webp).status, read_of(webp).error) == ('failed', 'cv_file_kind')
    assert (read_of(locked).status, read_of(locked).error) == ('failed', 'cv_file_unreadable')
    assert long.page_count == 40 and (read_of(long).status, read_of(long).error) == ('failed', 'generation_limit')
    assert reads.claim() is None
    # Its draft is refused as before, at once.
    assert refused(customer, made_from(customer, long)).code == 'generation_limit'
    # A file of exactly the most pages is read.
    whole = cv_file(customer, 'whole.pdf', _pdf(lambda page, number: _lines(page, 60, 780, [
        ('Helvetica', 11, f'Page {number}', 14)]), sources.MAX_PAGES))
    assert read_of(whole).status == 'queued'


# --- Drafts made from what was read ---------------------------------------------------------------

def test_a_draft_waits_with_how_many_reads_are_ahead_and_is_made_at_once_when_they_are_done(queued, reader, customer):
    other = account(77)
    theirs = [cv_file(other, f'shot-{number}.pdf') for number in range(3)]
    mine = cv_file(customer, 'old-cv.pdf')
    # Their first screenshot is being read; their next two and this file wait.
    reads.claim()
    waiting = refused(customer, made_from(customer, mine))
    assert waiting.code == 'cv_reading' and waiting.status == 409 and waiting.retryable
    # The account never served goes before theirs: only the read in hand is ahead.
    assert waiting.params == {'ahead': 1, 'estimated_seconds': None}
    # One of theirs is being read: none is ahead of them, as the bot says it (their own files never are).
    assert refused(other, made_from(other, *theirs)).params['ahead'] == 0
    # Said as a wait, never as "try again".
    message = error_data(waiting, 'en')['message']
    assert '1 ahead' in message and 'try again' not in message.lower()
    call_command('runreader', '--once')
    read_before = list(reader.read)
    draft = create_draft(customer, made_from(customer, mine))
    data = unpack(draft.encrypted_data)
    # Made from what the reader kept: nothing is read for the draft.
    assert reader.read == read_before and data['title'] == 'Timur Rakhimov' and TEXT in data['excerpts'][0]['text']
    assert 'cv_unread' not in data


def test_how_long_the_reads_ahead_take_is_told_from_the_latest_reads(queued, reader, customer):
    other = account(77)
    for number in range(2):
        cv_file(other, f'done-{number}.pdf')
    call_command('runreader', '--once')
    now = timezone.now()
    CvSourceRead.objects.update(started_at=now - timedelta(seconds=10), finished_at=now - timedelta(seconds=6))
    cv_file(other, 'reading.pdf')
    reads.claim()
    mine = cv_file(customer, 'old-cv.pdf')
    # One read ahead and this one, four seconds each.
    assert refused(customer, made_from(customer, mine)).params == {'ahead': 1, 'estimated_seconds': 8}


def test_a_customer_alone_in_the_queue_is_told_nobody_is_ahead_on_the_web_as_in_the_bot(queued, reader, customer):
    from telegram.generation import cv_reading
    shots = [cv_file(customer, f'shot-{number}.pdf') for number in range(4)]
    ids = [str(asset.id) for asset in shots]
    told = login_client(customer).get('/api/v1/studio/cv-reads', {'ids': ids}).json()
    # Each file is told the files before it, the customer none of their own.
    assert [entry['ahead'] for entry in told['reads']] == [0, 1, 2, 3]
    assert told['ahead'] == 0 == cv_reading(customer, ids)['ahead']
    assert refused(customer, made_from(customer, *shots)).params['ahead'] == 0
    # Another customer's file in line before them is.
    other = account(77)
    theirs = cv_file(other, 'theirs.pdf')
    CvSourceRead.objects.filter(asset=theirs).update(created_at=timezone.now() - timedelta(minutes=1))
    assert reads.state(customer, shots)['ahead'] == 1 == cv_reading(customer, ids)['ahead']
    # Once theirs is read, the first of the customer's is being read: none ahead, said as "reading now".
    reads.perform(reads.claim())
    reads.claim()
    assert reads.state(customer, shots)['ahead'] == 0 and cv_reading(customer, ids) == {'reading': True, 'ahead': 0}


def test_the_time_said_counts_what_is_left_of_the_reads_in_progress(queued, reader, customer):
    other = account(77)
    done = {'pages': [{'page': 1, 'text': TEXT}], 'names': [], 'ocr_pages': 0, 'ocr_skipped': 0}
    for number in range(2):
        cv_file(other, f'done-{number}.pdf')
    call_command('runreader', '--once')
    now = timezone.now()

    def lately():
        # Reads take ten seconds lately.
        CvSourceRead.objects.filter(status='done').update(started_at=now - timedelta(seconds=20),
                                                          finished_at=now - timedelta(seconds=10))
    lately()
    cv_file(other, 'reading.pdf')
    theirs = reads.claim()
    mine = cv_file(customer, 'old-cv.pdf')

    def told():
        return reads.state(customer, [mine])['estimated_seconds']
    # What is left of theirs, then this one.
    assert told() == 20
    # Read for six seconds already: what is left of it is never less than as long again.
    CvSourceRead.objects.filter(pk=theirs.pk).update(started_at=now - timedelta(seconds=6))
    assert 16 <= told() <= 17
    # Longer than reads take: the longer it takes, the longer the time said, never "about 5 seconds" for minutes.
    CvSourceRead.objects.filter(pk=theirs.pk).update(started_at=now - timedelta(seconds=30))
    assert 40 <= told() <= 41
    # Past the time a read has, its reader stopped mid-read: read again once its lease lapses.
    CvSourceRead.objects.filter(pk=theirs.pk).update(started_at=now - timedelta(seconds=100),
                                                     lease_expires_at=now + timedelta(seconds=80))
    assert 95 <= told() <= 101
    # The customer's own file being read and one more of theirs behind it: what is left of it, and one more.
    reads.finish(theirs, reads.DONE, result=done)
    lately()
    later = cv_file(customer, 'later.pdf')
    first = reads.claim()
    assert first.asset_id == mine.id and reads.state(customer, [mine, later])['estimated_seconds'] == 20
    # No reader taking the queued reads: how long is not known, so no time is said.
    reads.finish(first, reads.DONE, result=done)
    CvSourceRead.objects.filter(asset=later).update(created_at=timezone.now() - timedelta(seconds=reads.IDLE_SECONDS + 5))
    assert reads.state(customer, [later])['estimated_seconds'] is None
    assert refused(customer, made_from(customer, later)).params['estimated_seconds'] is None


def test_a_file_the_reader_failed_on_is_said_and_with_nothing_read_the_cv_is_refused(queued, reader, customer):
    good, bad = cv_file(customer, 'good.pdf'), cv_file(customer, 'bad.pdf')
    reader.failing = {Path(bad.object_key).name}
    call_command('runreader', '--once')
    assert (read_of(bad).status, read_of(bad).error) == ('failed', 'source_extraction_failed')
    data = unpack(create_draft(customer, made_from(customer, good, bad)).encrypted_data)
    assert data['cv_unread'] == [{'asset_id': str(bad.id), 'pages': 1, 'whole': True}]
    assert refused(customer, {**made_from(customer, bad), 'prompt': 'Timur Rakhimov'}).code == 'cv_file_unreadable'


def test_an_update_waits_for_a_file_added_to_the_draft(queued, reader, customer):
    first = cv_file(customer, 'first.pdf')
    call_command('runreader', '--once')
    draft = create_draft(customer, made_from(customer, first))
    added = cv_file(customer, 'added.pdf')
    with pytest.raises(DomainError) as waiting:
        update_draft(customer, draft.id, {'version': draft.version, 'source_ids': [str(first.id), str(added.id)]})
    assert waiting.value.code == 'cv_reading'
    call_command('runreader', '--once')
    again = update_draft(customer, draft.id, {'version': draft.version,
                                               'source_ids': [str(first.id), str(added.id)]})
    assert [excerpt['asset_id'] for excerpt in unpack(again.encrypted_data)['excerpts']] == [str(first.id), str(added.id)]


def test_a_file_uploaded_before_the_queue_is_queued_when_a_draft_asks_for_it(queued, reader, customer):
    from apps.core.services import upload_file as plain
    older = plain(customer, SimpleUploadedFile('old-cv.pdf', one_column_pdf()))
    assert not CvSourceRead.objects.filter(asset=older).exists()
    assert refused(customer, made_from(customer, older)).code == 'cv_reading'
    assert read_of(older).status == 'queued' and reader.read == []
    # Through the API's update too, though update_draft's transaction takes back what it queued.
    call_command('runreader', '--once')
    draft = create_draft(customer, made_from(customer, older))
    later = plain(customer, SimpleUploadedFile('later.pdf', one_column_pdf()))
    response = login_client(customer).patch(f'/api/v1/generation/drafts/{draft.id}', data=json.dumps(
        {'version': draft.version, 'source_ids': [str(older.id), str(later.id)]}), content_type='application/json')
    assert response.status_code == 409 and response.json()['error']['code'] == 'cv_reading', response.content
    assert read_of(later).status == 'queued'


def test_in_tests_and_local_development_a_file_is_read_as_it_is_queued(settings, reader, customer):
    assert settings.LOCAL_SYNC_JOBS
    asset = cv_file(customer)
    assert read_of(asset).status == 'done' and reader.read == ['pdf']
    assert unpack(create_draft(customer, made_from(customer, asset)).encrypted_data)['title'] == 'Timur Rakhimov'
    # An older upload is read the moment a draft asks for it.
    from apps.core.services import upload_file as plain
    older = plain(customer, SimpleUploadedFile('older.pdf', one_column_pdf()))
    create_draft(customer, made_from(customer, older))
    assert read_of(older).status == 'done' and reader.read == ['pdf', 'pdf']


def test_the_draft_shares_the_ocr_pages_its_files_were_read_with(queued, customer, monkeypatch):
    def read_file(asset):
        count = 10 if asset.name == 'scan.pdf' else 1
        return {'pages': [{'page': number, 'text': f'Page {number} of the old CV read by optical recognition',
                           'ocr': True} for number in range(1, count + 1)],
                'names': [], 'ocr_pages': count, 'ocr_skipped': 0}
    monkeypatch.setattr(reads, 'read_file', read_file)
    scan = cv_file(customer, 'scan.pdf', _pdf(lambda page, _: _lines(page, 60, 780, [('Helvetica', 11, 'x', 14)]), 10))
    shot = cv_file(customer, 'shot.pdf')
    call_command('runreader', '--once')
    data = unpack(create_draft(customer, {**made_from(customer, scan, shot), 'prompt': TEXT}).encrypted_data)
    # Ten OCR pages a draft: nine of the scan's and the screenshot, the scan's last said.
    assert [excerpt['asset_id'] for excerpt in data['excerpts']].count(str(scan.id)) == 9
    assert data['cv_unread'] == [{'asset_id': str(scan.id), 'pages': 1}]


# --- The API ---------------------------------------------------------------------------------------

def test_an_upload_for_a_cv_says_how_its_read_stands(queued, customer):
    client = login_client(customer)
    first = client.post('/api/v1/files/uploads', {'file': SimpleUploadedFile('first.pdf', one_column_pdf()),
                                                  'purpose': 'cv_source'})
    assert first.status_code == 201 and first.json()['cv_read'] == {'status': 'queued', 'ahead': 0, 'error': None}
    second = client.post('/api/v1/files/uploads', {'file': SimpleUploadedFile('second.pdf', one_column_pdf()),
                                                   'purpose': 'cv_source'})
    assert second.json()['cv_read'] == {'status': 'queued', 'ahead': 1, 'error': None}
    plain = client.post('/api/v1/files/uploads', {'file': SimpleUploadedFile('tool.pdf', one_column_pdf())})
    assert plain.status_code == 201 and 'cv_read' not in plain.json()
    assert not CvSourceRead.objects.filter(asset_id=plain.json()['id']).exists()


def test_an_upload_read_at_once_locally_says_it_is_done(settings, reader, customer):
    response = login_client(customer).post('/api/v1/files/uploads', {
        'file': SimpleUploadedFile('old-cv.pdf', one_column_pdf()), 'purpose': 'cv_source'})
    assert response.json()['cv_read'] == {'status': 'done', 'ahead': 0, 'error': None}


def test_the_web_asks_how_the_reads_stand_for_the_customers_own_files(queued, reader, customer):
    client = login_client(customer)
    first, second = cv_file(customer, 'first.pdf'), cv_file(customer, 'second.pdf')
    reads.claim()
    response = client.get('/api/v1/studio/cv-reads', {'ids': [str(first.id), str(second.id)]})
    assert response.status_code == 200, response.content
    # Each file says the reads before it; the customer, being read now, has none of others' ahead.
    assert response.json() == {'reads': [
        {'asset_id': str(first.id), 'status': 'reading', 'ahead': 0, 'pages': 0, 'ocr_pages': 0, 'error': None},
        {'asset_id': str(second.id), 'status': 'queued', 'ahead': 1, 'pages': 0, 'ocr_pages': 0, 'error': None},
    ], 'ahead': 0, 'estimated_seconds': None}
    call_command('runreader', '--once')
    done = client.get('/api/v1/studio/cv-reads', {'ids': [str(second.id)]}).json()
    assert done == {'reads': [{'asset_id': str(second.id), 'status': 'done', 'ahead': 0, 'pages': 1, 'ocr_pages': 0,
                               'error': None}], 'ahead': 0, 'estimated_seconds': 0}
    # Another account's file is no file of theirs, as everywhere else.
    stranger = cv_file(account(77), 'theirs.pdf')
    foreign = client.get('/api/v1/studio/cv-reads', {'ids': [str(first.id), str(stranger.id)]})
    assert foreign.status_code == 404 and foreign.json()['error']['code'] == 'file_unavailable'
    assert client.get('/api/v1/studio/cv-reads').status_code == 400
    many = client.get('/api/v1/studio/cv-reads', {'ids': [str(first.id)] * 11})
    assert many.status_code == 400 and many.json()['error']['code'] == 'invalid_inputs'
    # A file uploaded before the queue is queued when asked about.
    from apps.core.services import upload_file as plain
    older = plain(customer, SimpleUploadedFile('older.pdf', one_column_pdf()))
    asked = client.get('/api/v1/studio/cv-reads', {'ids': [str(older.id)]}).json()
    assert asked['reads'][0]['status'] == 'queued' and read_of(older).status == 'queued'


class Clock:
    """The cache's clock, moved by hand: a minute of asking takes no minute."""

    def __init__(self):
        self.now = time.time()

    def time(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    from django.core.cache.backends import base, locmem
    fake = Clock()
    monkeypatch.setattr(locmem, 'time', fake)
    monkeypatch.setattr(base, 'time', fake)
    cache.clear()
    yield fake
    cache.clear()


def test_asking_every_two_seconds_is_never_refused_however_long_the_wait(queued, customer, clock):
    from apps.studio import views
    client = login_client(customer)
    asset = cv_file(customer)
    # Five minutes of a tab asking every two seconds, the files still waiting: the
    # minute is counted from its first request, never pushed on by the next.
    refused_at = []
    for second in range(0, 300, 2):
        clock.now += 2
        if client.get('/api/v1/studio/cv-reads', {'ids': [str(asset.id)]}).status_code == 429:
            refused_at.append(second)
    assert refused_at == []
    # Two tabs at once, a request a second, and a refresh now and then: still never refused.
    for second in range(120):
        clock.now += 1
        for _ in range(2 if second % 10 == 0 else 1):
            assert client.get('/api/v1/studio/cv-reads', {'ids': [str(asset.id)]}).status_code == 200, second
    # More than CV_READS_PER_MINUTE in one minute is refused, until that minute is over.
    clock.now += 61
    statuses = [client.get('/api/v1/studio/cv-reads', {'ids': [str(asset.id)]}).status_code
                for _ in range(views.CV_READS_PER_MINUTE + 1)]
    assert statuses.count(200) == views.CV_READS_PER_MINUTE and statuses[-1] == 429
    limited = client.get('/api/v1/studio/cv-reads', {'ids': [str(asset.id)]})
    assert limited.status_code == 429 and limited.json()['error']['code'] == 'rate_limited'
    clock.now += 61
    assert client.get('/api/v1/studio/cv-reads', {'ids': [str(asset.id)]}).status_code == 200


def test_a_draft_waiting_for_its_files_is_a_409_with_the_reads_ahead(queued, customer):
    asset = cv_file(customer)
    response = login_client(customer).post('/api/v1/generation/drafts', data=json.dumps(made_from(customer, asset)),
                                           content_type='application/json')
    assert response.status_code == 409
    error = response.json()['error']
    assert error['code'] == 'cv_reading' and error['retryable'] is True
    assert error['message_params'] == {'ahead': 0, 'estimated_seconds': None}
    assert error['message'] == error_data(DomainError('cv_reading'), customer.locale)['message']


def test_the_contract_names_the_reads_and_the_uploads_read():
    from apps.core.management.commands.export_contract import schema
    contract = schema()
    listed = contract['paths']['/studio/cv-reads']['get']
    assert listed['parameters'][0]['name'] == 'ids' and listed['parameters'][0]['explode'] is True
    shape = listed['responses']['200']['content']['application/json']['schema']
    assert shape['required'] == ['reads', 'ahead', 'estimated_seconds']
    assert set(contract['components']['schemas']['CvRead']['required']) == {
        'asset_id', 'status', 'ahead', 'pages', 'ocr_pages', 'error'}
    upload = contract['paths']['/files/uploads']['post']['responses']['201']['content']['application/json']['schema']
    assert upload['allOf'][1]['properties']['cv_read']['$ref'] == '#/components/schemas/CvUploadRead'


# --- What the customer is told ------------------------------------------------------------------

@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_the_wait_is_said_in_every_language_with_how_many_are_ahead(locale):
    from telegram.errors import COPY, bot_error
    for ahead in (1, 2, 5, 21):
        for said in (error_data(DomainError('cv_reading', 409, {'ahead': ahead}), locale)['message'],
                     bot_error(DomainError('cv_reading', 409, {'ahead': ahead}), locale)):
            assert str(ahead) in said and '{ahead}' not in said and len(said) < 260
    # None ahead, or a count the error does not carry: the files are being read now.
    for params in ({'ahead': 0}, {}, {'ahead': 'many'}):
        assert bot_error(DomainError('cv_reading', 409, params), locale) == COPY[locale]['cv_reading_now']
        message = error_data(DomainError('cv_reading', 409, params), locale)['message']
        assert '{ahead}' not in message and not any(char.isdigit() for char in message)
    for message in (error_data(DomainError('cv_reading', 409, {'ahead': 3}), locale)['message'],
                    COPY[locale]['cv_reading'], COPY[locale]['cv_reading_now']):
        if locale == 'uz':
            # Latin only, with the house o‘ and the tutuq; a count needs no plural ("3 ta fayl").
            assert not any('Ѐ' <= char <= 'ӿ' for char in message) and "'" not in message and '’' not in message
        if locale == 'ru':
            # No noun after the count, so no plural to agree: "перед ними ещё 3".
            assert 'AI' not in message and 'попробуйте' not in message.lower()
        if locale == 'en':
            assert 'try again' not in message.lower()


# --- Where the reader runs --------------------------------------------------------------------------

def test_the_reader_has_its_own_container_and_the_bot_its_small_one_again():
    import yaml
    production = yaml.safe_load((ROOT / 'infra/production/compose.yaml').read_text())['services']
    assert production['reader']['command'] == ['python', 'manage.py', 'runreader']
    assert production['reader']['mem_limit'] == '1g' and production['reader']['cpus'] == 1
    # Long enough for one file's reading and its child's grace.
    grace = int(production['reader']['stop_grace_period'].rstrip('s'))
    assert grace >= sources.READ_SECONDS + extraction.CV_GRACE_SECONDS + 30
    assert production['reader']['image'] == production['worker']['image']
    assert production['bot']['mem_limit'] == '384m' and production['bot']['cpus'] == 0.5
    local = yaml.safe_load((ROOT / 'infra/compose.yaml').read_text())['services']
    assert local['reader']['command'] == ['python', 'manage.py', 'runreader']


def test_the_container_smoke_starts_the_reader_and_reads_a_page_in_it(monkeypatch):
    import importlib.util
    import subprocess
    spec = importlib.util.spec_from_file_location('pdfmaster_reader_smoke', ROOT / 'scripts/deploy/container_smoke.py')
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    assert "'reader'" in (ROOT / 'scripts/deploy/container_smoke.py').read_text().split("services=['api'", 1)[1][:80]
    compose = ['docker', 'compose', '-p', 'pdfmaster-ci-test-only']
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if command[:2] == ['docker', 'inspect']:
            return subprocess.CompletedProcess(command, 0, stdout=state)
        return subprocess.CompletedProcess(command, 0, stdout='c' * 64 + '\n')
    monkeypatch.setattr(smoke, 'run', run)
    state = 'false 0 true\n'
    smoke.check_reader(compose, {})
    assert commands[0][:len(compose) + 4] == [*compose, 'exec', '-T', 'reader', 'python']
    state = 'true 1 false\n'
    with pytest.raises(RuntimeError, match='OOM-killed'):
        smoke.check_reader(compose, {})


def test_nothing_is_left_of_the_lock_that_asked_people_to_try_again():
    text = (ROOT / 'apps/studio/cv/sources.py').read_text()
    assert 'rate_limited' not in text and 'flock' not in text and not hasattr(sources, 'SLOT')



def test_a_file_taken_off_the_form_leaves_the_line_and_a_started_read_finishes(queued, reader, customer):
    """DELETE studio/cv-reads drops the account's queued reads of those files, and nothing else."""
    import uuid
    other = account(78)
    mine = [cv_file(customer, f'shot-{number}.pdf') for number in range(3)]
    theirs = cv_file(other, 'old-cv.pdf')
    CvSourceRead.objects.filter(asset=mine[2]).update(status='reading')
    query = '&'.join(f'ids={asset.id}' for asset in [*mine, theirs]) + f'&ids={uuid.uuid4()}&ids=not-a-uuid'
    response = login_client(customer).delete(f'/api/v1/studio/cv-reads?{query}')
    assert response.status_code == 200, response.content
    assert response.json() == {'cancelled': 2}
    left = {(row.asset_id, row.status) for row in CvSourceRead.objects.all()}
    assert left == {(mine[2].id, 'reading'), (theirs.id, 'queued')}
    # Used after all, a dropped file is queued again when a draft asks for it.
    assert refused(customer, made_from(customer, mine[0])).code == 'cv_reading'
    assert read_of(mine[0]).status == 'queued'
