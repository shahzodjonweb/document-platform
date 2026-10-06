"""CI must observe actual cleanup completion rather than just container start."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/deploy/container_smoke.py'
spec = importlib.util.spec_from_file_location('pdfmaster_cleanup_container_smoke', SCRIPT)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
COMPOSE = ['docker', 'compose', '-p', 'pdfmaster-ci-test-only']
CONTAINER = 'a' * 64
PRIVATE_LOG = 'S3 secret must never enter CI output: fixture-private-key'


def snapshot(**changes):
    value = {'RestartCount': 0, 'State': {
        'Running': True, 'Status': 'running', 'Restarting': False,
        'Dead': False, 'OOMKilled': False, 'StartedAt': '2026-10-06T10:00:00Z',
    }}
    if 'RestartCount' in changes:
        value['RestartCount'] = changes.pop('RestartCount')
    value['State'].update(changes)
    return value


class DockerProbe:
    def __init__(self, *, states=None, logs=None, container=CONTAINER):
        self.states = list(states or [snapshot()])
        self.logs = list(logs or [('Deleted 0 expired files.\n', '')])
        self.container = container
        self.commands = []
        self.now = 0

    def run(self, command, **kwargs):
        self.commands.append(command)
        assert kwargs['timeout'] > 0
        if command == COMPOSE + ['ps', '-q', 'cleanup']:
            return SimpleNamespace(stdout=self.container + '\n', stderr='')
        if command[:2] == ['docker', 'inspect']:
            state = self.states[0]
            if len(self.states) > 1:
                self.states.pop(0)
            return SimpleNamespace(stdout=json.dumps(state), stderr='')
        if command[:2] == ['docker', 'logs']:
            output, error = self.logs[0]
            if len(self.logs) > 1:
                self.logs.pop(0)
            return SimpleNamespace(stdout=output, stderr=error)
        raise AssertionError('Unexpected Docker command')

    def sleep(self, seconds):
        self.now += seconds

    def install(self, monkeypatch):
        monkeypatch.setattr(smoke, 'run', self.run)
        monkeypatch.setattr(smoke, 'time', SimpleNamespace(
            monotonic=lambda: self.now, sleep=self.sleep))


def test_smoke_waits_for_completed_cleanup_and_keeps_logs_private(monkeypatch, capsys):
    probe = DockerProbe(logs=[(PRIVATE_LOG + '\nStarting cleanup...\n', ''),
                              ('Deleted 12 expired files.\n', PRIVATE_LOG)])
    probe.install(monkeypatch)
    smoke.wait_for_cleanup_cycle(COMPOSE, {}, timeout=5, interval=1)
    assert probe.now == 1
    assert len([command for command in probe.commands if command[:2] == ['docker', 'inspect']]) == 3
    output = capsys.readouterr()
    assert 'Cleanup first cycle completed' in output.out
    assert 'fixture-private-key' not in output.out + output.err
    assert 'Deleted 12' not in output.out + output.err


@pytest.mark.parametrize('state, message', [
    (snapshot(OOMKilled=True), 'OOM-killed'),
    (snapshot(RestartCount=1), 'restarted'),
    (snapshot(Running=False, Status='exited'), 'not running'),
    (snapshot(Restarting=True), 'not running'),
])
def test_smoke_rejects_cleanup_failure_even_when_logs_show_an_old_success(
        monkeypatch, capsys, state, message):
    probe = DockerProbe(states=[state], logs=[('Deleted 1 expired files.\n', PRIVATE_LOG)])
    probe.install(monkeypatch)
    with pytest.raises(RuntimeError, match=message):
        smoke.wait_for_cleanup_cycle(COMPOSE, {}, timeout=5, interval=1)
    output = capsys.readouterr()
    assert 'first cycle completed' not in output.out
    assert 'fixture-private-key' not in output.out + output.err


def test_smoke_rechecks_oom_state_after_reading_completion_marker(monkeypatch, capsys):
    probe = DockerProbe(states=[snapshot(), snapshot(OOMKilled=True)])
    probe.install(monkeypatch)
    with pytest.raises(RuntimeError, match='OOM-killed'):
        smoke.wait_for_cleanup_cycle(COMPOSE, {}, timeout=5, interval=1)
    assert not capsys.readouterr().out


def test_smoke_detects_manual_restart_even_if_docker_restart_count_is_zero(monkeypatch):
    probe = DockerProbe(states=[snapshot(), snapshot(StartedAt='2026-10-06T10:00:03Z')])
    probe.install(monkeypatch)
    with pytest.raises(RuntimeError, match='restarted'):
        smoke.wait_for_cleanup_cycle(COMPOSE, {}, timeout=5, interval=1)


def test_smoke_times_out_a_running_cleanup_that_never_completes(monkeypatch, capsys):
    probe = DockerProbe(logs=[(PRIVATE_LOG, 'Traceback: fixture-sensitive-storage-url')])
    probe.install(monkeypatch)
    with pytest.raises(RuntimeError, match='timed out'):
        smoke.wait_for_cleanup_cycle(COMPOSE, {}, timeout=5, interval=1)
    assert probe.now == 5
    assert not capsys.readouterr().out


def test_smoke_refuses_missing_cleanup_service(monkeypatch):
    probe = DockerProbe(container='')
    probe.install(monkeypatch)
    with pytest.raises(RuntimeError, match='exactly one running cleanup container'):
        smoke.wait_for_cleanup_cycle(COMPOSE, {}, timeout=5, interval=1)


def test_completion_text_inside_an_error_is_not_a_success_marker(monkeypatch):
    probe = DockerProbe(logs=[('Error: Deleted 0 expired files. not actually completed', '')])
    probe.install(monkeypatch)
    with pytest.raises(RuntimeError, match='timed out'):
        smoke.wait_for_cleanup_cycle(COMPOSE, {}, timeout=5, interval=1)
