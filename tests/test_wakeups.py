"""Runners are woken the moment there is work, and look on their old timer without Redis (apps/core/wakeups.py)."""
import asyncio
from types import SimpleNamespace

import pytest
from django.core.management import call_command

from apps.core import wakeups

pytestmark = pytest.mark.django_db


class FakeRedis:
    """Lists and the few calls wakeups.py makes."""
    def __init__(self):
        self.lists, self.expiries, self.popped = {}, {}, []

    def pipeline(self, transaction=False):
        return self

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    def expire(self, key, seconds):
        self.expiries[key] = seconds

    def execute(self):
        return []

    def blpop(self, keys, timeout):
        self.popped.append((tuple(keys), timeout))
        for key in keys:
            if self.lists.get(key):
                return key, self.lists[key].pop(0)
        return None

    def delete(self, *keys):
        for key in keys:
            self.lists.pop(key, None)


@pytest.fixture
def fake(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(wakeups, '_client', lambda blocking=False: redis)
    return redis


def test_without_redis_a_runner_looks_on_its_old_timer(monkeypatch, settings):
    settings.REDIS_URL = ''
    slept = []
    monkeypatch.setattr(wakeups.time, 'sleep', slept.append)
    wakeups.notify(wakeups.JOBS)
    assert wakeups.wait([wakeups.JOBS], 2, idle=1) is False and slept == [1]
    asyncio.run(wakeups.wait_async([wakeups.DELIVERIES], 0))


def test_a_token_wakes_the_runner_once_for_a_burst(fake):
    for _ in range(3):
        wakeups.notify(wakeups.AI_JOBS)
    assert fake.expiries[wakeups.PREFIX + wakeups.AI_JOBS] == wakeups.TOKEN_SECONDS
    assert wakeups.wait([wakeups.AI_JOBS], 2) is True
    # The rest of the burst is found by the look that follows; the next wait times out.
    assert wakeups.wait([wakeups.AI_JOBS], 2) is False
    assert fake.popped[-1] == ((wakeups.PREFIX + wakeups.AI_JOBS,), 2)


def test_a_redis_that_fails_never_fails_the_caller(monkeypatch):
    class Broken:
        def pipeline(self, transaction=False): raise ConnectionError('down')
        def blpop(self, keys, timeout): raise ConnectionError('down')
    monkeypatch.setattr(wakeups, '_client', lambda blocking=False: Broken())
    slept = []
    monkeypatch.setattr(wakeups.time, 'sleep', slept.append)
    wakeups.notify(wakeups.JOBS)
    assert wakeups.wait([wakeups.JOBS], 2, idle=1) is False and slept == [1]


def test_queuing_a_job_wakes_its_lanes_once_it_commits(settings, django_capture_on_commit_callbacks, fake):
    from apps.core.services import submit_job
    from apps.studio.domain import create_draft, generation_quote
    from tests.test_platform import account, quote, upload
    from tests.test_studio import paid
    settings.LOCAL_SYNC_JOBS = False
    settings.DEBUG = True
    owner = paid(settings, account())
    with django_capture_on_commit_callbacks(execute=True):
        submit_job(owner, quote(owner, upload(owner)).id, 'wake-file-job')
    assert fake.lists == {wakeups.PREFIX + wakeups.JOBS: [1]}
    fake.lists.clear()
    draft = create_draft(owner, {'feature_id': 'ai.pdf_topic', 'prompt': 'Ocean tides near harbours', 'output_locale': 'en'})
    with django_capture_on_commit_callbacks(execute=True):
        submit_job(owner, generation_quote(owner, draft.id, draft.version).id, 'wake-ai-job')
    assert set(fake.lists) == {wakeups.PREFIX + wakeups.JOBS, wakeups.PREFIX + wakeups.AI_JOBS}


def test_an_idle_runner_waits_for_its_own_lanes_wake_up(monkeypatch):
    from apps.core.management.commands import runworker
    waited = []

    def wait(names, seconds, idle=None):
        waited.append((names, seconds, idle))
        import os, signal
        os.kill(os.getpid(), signal.SIGTERM)
        return False
    monkeypatch.setattr(runworker.wakeups, 'wait', wait)
    monkeypatch.setattr(runworker, 'select_outbox', lambda limit, **kwargs: [])
    call_command('runworker', lane='ai')
    call_command('runworker')
    assert waited == [([wakeups.AI_JOBS], runworker.IDLE_SECONDS, 1), ([wakeups.JOBS], runworker.IDLE_SECONDS, 1)]


def test_a_bot_job_that_settles_wakes_the_delivery_loop(settings, django_capture_on_commit_callbacks, fake):
    from apps.core.models import Job
    from apps.core.services import settle_job, submit_job
    from tests.test_platform import account, quote, upload
    settings.LOCAL_SYNC_JOBS = False
    owner = account()
    job, _ = submit_job(owner, quote(owner, upload(owner)).id, 'wake-bot-job', origin='bot')
    fake.lists.clear()
    Job.objects.filter(pk=job.pk).update(status='running')
    with django_capture_on_commit_callbacks(execute=True):
        settle_job(job.id, 'failed', error_code='processing_failed')
    assert fake.lists == {wakeups.PREFIX + wakeups.DELIVERIES: [1]}
