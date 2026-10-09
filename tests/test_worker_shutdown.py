"""A deploy's SIGTERM lets the job in hand finish; nothing new is started.

Before, the worker died on the spot and the job it was running stayed
`running` until its lease lapsed, then failed as worker_interrupted.
"""
import os
import signal
from types import SimpleNamespace

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db


def event(job_id):
    return SimpleNamespace(job_id=job_id, delivered_at=None, save=lambda **kwargs: None)


def test_the_worker_finishes_the_job_in_hand_and_takes_no_other(monkeypatch):
    from apps.core.management.commands import runworker
    ran = []

    def execute(job_id):
        ran.append(job_id)
        # The deploy stops the container while this job is running.
        os.kill(os.getpid(), signal.SIGTERM)
        ran.append(f'{job_id} finished')
        return SimpleNamespace(status='succeeded')

    monkeypatch.setattr(runworker, 'select_outbox', lambda limit: [event('first'), event('second')])
    monkeypatch.setattr(runworker, 'execute_job', execute)
    before = signal.getsignal(signal.SIGTERM)
    call_command('runworker')  # Without --once: it returns only because it was asked to stop.
    assert ran == ['first', 'first finished']
    assert signal.getsignal(signal.SIGTERM) is before


def test_the_batch_runner_finishes_the_batch_in_hand_and_starts_no_other(monkeypatch):
    from apps.studio import batches
    ran = []

    def execute(identifier, stop=None):
        ran.append(identifier)
        os.kill(os.getpid(), signal.SIGTERM)
        assert stop, 'the batch in hand is told to stop between its children'

    class Ids(list):
        def __getitem__(self, item):
            return self if isinstance(item, slice) else list.__getitem__(self, item)

    query = SimpleNamespace(filter=lambda *a, **k: query, order_by=lambda *a: query,
                            values_list=lambda *a, **k: Ids(['one', 'two']))
    monkeypatch.setattr(batches.BatchRun, 'objects', query)
    monkeypatch.setattr(batches, 'execute_batch', execute)
    call_command('runbatches')
    assert ran == ['one']


def test_without_a_signal_to_listen_for_the_loop_runs_as_before():
    import threading
    from apps.core.shutdown import graceful_stop
    seen = []

    def run():
        with graceful_stop() as stop:
            seen.append(bool(stop))
    thread = threading.Thread(target=run)
    thread.start()
    thread.join()
    assert seen == [False]


def test_a_stopping_batch_starts_no_further_child_and_goes_back_to_the_queue(settings):
    from apps.core.shutdown import Stop
    from apps.studio.batches import create_batch_quote, execute_batch, submit_batch
    from tests.test_batches import groups, paid
    from tests.test_platform import account
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    customer = paid(account())
    run, _ = submit_batch(customer, create_batch_quote(customer, 'batch.convert', groups(customer)).id, 'stop-batch')
    stop = Stop()
    stop.requested = True
    run = execute_batch(run.id, stop)
    assert run.status == 'queued' and run.lease_until is None
    assert not run.children.filter(job__isnull=False).exists()
    # The next runner carries on and finishes it.
    assert execute_batch(run.id).status == 'succeeded'
