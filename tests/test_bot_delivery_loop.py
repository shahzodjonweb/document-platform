"""The bot's sender of result files keeps going whatever one look meets.

delivery_loop is an asyncio task nobody awaits before shutdown. Before this, one
database error on a look ended it for good and unlogged: the bot still answered
taps and took orders, but no finished file reached the chat until a restart.
"""
import asyncio
import io
import logging
import uuid
from unittest.mock import AsyncMock, Mock

import pytest
from asgiref.sync import sync_to_async
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError, connection, connections
from django.db.backends import utils as db_utils
from pypdf import PdfWriter

from apps.commerce.models import BotDelivery
from apps.core.identity import resolve_account
from apps.core.models import Account
from apps.core.services import create_quote, execute_job, submit_job, upload_file

# The loop runs its queries on another thread, as in the bot: it must see committed rows.
pytestmark = pytest.mark.django_db(transaction=True)

DROPPED = 'consuming input failed: server closed the connection unexpectedly'


def finished_job(telegram_id=667788):
    """A file job the bot ordered, finished by the worker: its file is queued for the bot to send."""
    account = resolve_account({'id': telegram_id, 'first_name': 'Loop', 'language_code': 'en'}, is_test=True)
    stream = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    writer.write(stream)
    asset = upload_file(account, SimpleUploadedFile('source.pdf', stream.getvalue()))
    quote = create_quote(account, 'pdf.rotate', [str(asset.id)], {'angle': 90})
    job, _ = submit_job(account, quote.id, 'loop-' + uuid.uuid4().hex[:12], origin='bot')
    job = execute_job(job.id)
    assert job.status == 'succeeded', job.error_code
    # A real customer: drain() leaves test accounts alone.
    Account.objects.filter(pk=account.pk).update(is_test=False)
    return job


def delivery_of(job):
    return BotDelivery.objects.get(artifact__job=job)


def fail_once_on(monkeypatch, table):
    """The next statement on `table` fails as when Postgres drops the connection; the ones after work."""
    original = db_utils.CursorWrapper.execute
    state = {'fired': False}

    def execute(self, sql, params=None):
        if not state['fired'] and table in sql:
            state['fired'] = True
            raise OperationalError(DROPPED)
        return original(self, sql, params)
    monkeypatch.setattr(db_utils.CursorWrapper, 'execute', execute)
    return state


def fake_bot():
    sent = Mock(message_id=1)
    return Mock(send_document=AsyncMock(return_value=sent), send_message=AsyncMock(return_value=sent))


def errors(caplog):
    return [record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR]


@pytest.fixture(autouse=True)
def fresh_log_runs():
    """Each test starts with no step failing, as a bot just started."""
    from telegram import delivery
    delivery._failing.clear()
    yield
    delivery._failing.clear()
    # The bot's queries ran on asgiref's shared thread: its connection would keep the test database from being dropped.
    asyncio.run(sync_to_async(connections.close_all)())


def owner_alert():
    """A message to the owner waiting to be sent: the last kind of notice a look sends."""
    from apps.core.models import StaffAlert
    from operations.integrations import save_config
    save_config('manual_payments', {'alert_telegram_id': '1234567', 'enabled': 'false'})
    return StaffAlert.objects.create(kind='storage', text='File storage works again.')


@pytest.mark.parametrize('table', ['core_botjobnotice', 'commerce_paymentnotice', 'commerce_referralreward'])
def test_a_notice_that_fails_holds_back_neither_the_files_nor_the_notices_after_it(monkeypatch, caplog, table):
    job = finished_job()
    alert = owner_alert()
    bot = fake_bot()
    probe = fail_once_on(monkeypatch, table)
    from telegram.delivery import drain
    with caplog.at_level(logging.ERROR):
        asyncio.run(drain(bot))
    assert probe['fired']
    assert delivery_of(job).status == 'delivered'
    assert bot.send_document.await_count == 1
    alert.refresh_from_db()
    assert alert.status == 'delivered'
    assert any('could not be sent' in line for line in errors(caplog)), errors(caplog)


def test_the_last_notice_failing_holds_back_no_file(monkeypatch, caplog):
    job = finished_job()
    owner_alert()
    bot = fake_bot()
    probe = fail_once_on(monkeypatch, 'core_staffalert')
    from telegram.delivery import drain
    with caplog.at_level(logging.ERROR):
        asyncio.run(drain(bot))
    assert probe['fired']
    assert delivery_of(job).status == 'delivered'
    assert any('Staff alerts could not be sent' in line for line in errors(caplog)), errors(caplog)


def test_a_look_whose_files_cannot_be_read_sends_them_on_the_next(monkeypatch, caplog):
    job = finished_job()
    bot = fake_bot()
    probe = fail_once_on(monkeypatch, 'commerce_botdelivery')
    from telegram.delivery import drain
    with caplog.at_level(logging.ERROR):
        asyncio.run(drain(bot))
        assert probe['fired'] and delivery_of(job).status == 'pending'
        asyncio.run(drain(bot))
    assert delivery_of(job).status == 'delivered'
    assert any('Result files could not be sent' in line for line in errors(caplog)), errors(caplog)


def test_a_file_whose_send_fails_outside_its_own_guard_holds_back_no_other_file(monkeypatch, caplog):
    first, second = finished_job(667788), finished_job(667789)
    bot = fake_bot()
    import telegram.delivery as delivery
    stuck = delivery_of(first).id
    original = delivery.claim

    def claim(identifier):
        if identifier == stuck:
            raise OperationalError(DROPPED)
        return original(identifier)
    monkeypatch.setattr(delivery, 'claim', claim)
    with caplog.at_level(logging.ERROR):
        asyncio.run(delivery.drain(bot))
    assert delivery_of(second).status == 'delivered'
    assert delivery_of(first).status == 'pending'
    assert any(f'Result file {stuck} could not be sent' in line for line in errors(caplog)), errors(caplog)


def test_the_loop_outlives_an_error_and_sends_the_next_file(monkeypatch, caplog):
    import telegram.delivery as delivery
    from apps.core import wakeups
    bot = fake_bot()
    real_drain = delivery.drain
    looks = {'count': 0}

    async def drain(bot):
        looks['count'] += 1
        if looks['count'] == 1:
            raise OperationalError(DROPPED)
        await real_drain(bot)

    async def wait_async(names, seconds):
        await asyncio.sleep(0.05)
        return False
    monkeypatch.setattr(delivery, 'drain', drain)
    monkeypatch.setattr(wakeups, 'wait_async', wait_async)

    async def scenario():
        task = asyncio.create_task(delivery.delivery_loop(bot))
        for _ in range(100):
            if looks['count'] >= 2 or task.done():
                break
            await asyncio.sleep(0.05)
        # A customer's next order finishes after the error.
        job = await sync_to_async(finished_job)()
        for _ in range(200):
            if await sync_to_async(lambda: delivery_of(job).status)() == 'delivered':
                break
            await asyncio.sleep(0.05)
        alive = not task.done()
        task.cancel()
        return job, alive

    with caplog.at_level(logging.ERROR):
        job, alive = asyncio.run(scenario())
    assert alive
    assert delivery_of(job).status == 'delivered'
    assert bot.send_document.await_count == 1
    assert any('Deliveries could not be sent' in line for line in errors(caplog)), errors(caplog)


def test_the_system_page_counts_the_files_the_bot_has_not_sent_for_minutes():
    from datetime import timedelta
    from django.utils import timezone
    from operations.i18n import CATALOGS
    from operations.metrics import system_snapshot
    from tests.test_operations import filters, staff_client
    job = finished_job()
    # Just ready: the bot has two minutes before it counts.
    assert system_snapshot(filters())['deliveries_waiting'] == 0
    BotDelivery.objects.filter(artifact__job=job).update(created_at=timezone.now() - timedelta(minutes=5))
    assert system_snapshot(filters())['deliveries_waiting'] == 1
    assert system_snapshot(filters(environment='development'))['deliveries_waiting'] == 0
    client, _ = staff_client()
    page = client.get('/ops/system').content.decode()
    assert any(CATALOGS[locale]['deliveries_waiting'] in page for locale in CATALOGS)
    BotDelivery.objects.filter(artifact__job=job).update(status='delivered')
    assert system_snapshot(filters())['deliveries_waiting'] == 0


def test_a_file_that_keeps_failing_before_its_guard_is_given_up(monkeypatch):
    import telegram.delivery as delivery
    job = finished_job()
    BotDelivery.objects.filter(artifact__job=job).update(attempts=delivery.MAX_ATTEMPTS)
    bot = fake_bot()
    asyncio.run(delivery.drain(bot))
    row = delivery_of(job)
    assert (row.status, row.error_code) == ('failed', 'telegram_delivery_attempts_exhausted')
    assert bot.send_document.await_count == 0


def test_while_steps_keep_failing_the_traceback_is_logged_once(monkeypatch, caplog):
    import telegram.delivery as delivery
    job = finished_job()
    bot = fake_bot()
    original = db_utils.CursorWrapper.execute

    def execute(self, sql, params=None):
        if 'commerce_botdelivery' in sql:
            raise OperationalError(DROPPED)
        return original(self, sql, params)
    monkeypatch.setattr(db_utils.CursorWrapper, 'execute', execute)
    with caplog.at_level(logging.ERROR):
        for _ in range(3):
            asyncio.run(delivery.drain(bot))
    files = [record for record in caplog.records if record.getMessage().startswith('Result files could not be sent')]
    assert len(files) == 3
    assert [bool(record.exc_info) for record in files] == [True, False, False]
    monkeypatch.setattr(db_utils.CursorWrapper, 'execute', original)
    asyncio.run(delivery.drain(bot))
    assert delivery_of(job).status == 'delivered'
    assert 'Result files' not in delivery._failing


@pytest.mark.skipif(connection.vendor != 'postgresql', reason='a dropped connection needs Postgres: sqlite has none to drop')
def test_a_connection_postgres_dropped_is_opened_again_and_the_file_sent():
    """Postgres ends the bot thread's connection, as on a database restart: the next look opens a new one."""
    from telegram.delivery import drain
    job = finished_job()
    bot = fake_bot()

    def backend():
        with connection.cursor() as cursor:
            cursor.execute('select pg_backend_pid()')
            return cursor.fetchone()[0]
    # The bot's queries all run on asgiref's one shared thread.
    pid = asyncio.run(sync_to_async(backend)())
    with connections['default'].cursor() as cursor:
        cursor.execute('select pg_terminate_backend(%s)', [pid])
    asyncio.run(drain(bot))
    asyncio.run(drain(bot))
    assert delivery_of(job).status == 'delivered'
    assert asyncio.run(sync_to_async(backend)()) != pid
