"""The emergency memory update must target one container and prove isolation."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/operations/stabilize-cleanup.py'
spec = importlib.util.spec_from_file_location('pdfmaster_cleanup_stabilization', SCRIPT)
operation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(operation)
ID = 'a' * 64
OTHER = 'b' * 64
STARTED = '2026-10-06T10:00:00.123456789Z'
PRIVATE = 'fixture-private-secret-must-not-be-printed'


def container(identifier=ID, *, memory=192 * operation.MIB, **changes):
    value = {'Id': identifier, 'Name': operation.NAME if identifier == ID else '/orderdesk-web-1',
        'Image': 'sha256:fixture-image', 'Config': {'Image': 'fixture:current', 'Env': [PRIVATE],
            'Labels': {'com.docker.compose.project': operation.PROJECT if identifier == ID else 'orderdesk',
                       'com.docker.compose.service': 'cleanup' if identifier == ID else 'web'}},
        'State': {'Running': True, 'Status': 'running', 'Restarting': False, 'Dead': False,
                  'OOMKilled': False, 'StartedAt': STARTED}, 'RestartCount': 12,
        'HostConfig': {'Memory': memory, 'MemorySwap': memory * 2},
        'Mounts': [{'Source': '/private/fixture', 'Destination': '/data', 'RW': True}],
        'NetworkSettings': {'Networks': {'fixture_default': {'NetworkID': 'fixture-network'}}, 'Ports': {}}}
    value.update(changes)
    return value


class Probe:
    def __init__(self, *, containers=None, logs=None, after_update=None, after_logs=None,
                 total=8 * 1024 ** 3, available=2 * 1024 ** 3):
        self.containers = copy.deepcopy(containers if containers is not None else [container(), container(OTHER)])
        self.logs = list(logs or [f'{STARTED} {PRIVATE}\n2026-10-06T10:00:01.000000000Z Deleted 2 expired files.\n'])
        self.after_update, self.after_logs = after_update, after_logs
        self.total, self.available = total, available
        self.commands, self.now = [], 0

    def run(self, args, **kwargs):
        self.commands.append(args)
        assert 0 < kwargs.get('timeout', 20) <= 20
        stdout, stderr = '', PRIVATE
        if args == ['docker', 'ps', '-aq', '--no-trunc']:
            stdout = '\n'.join(item['Id'] for item in self.containers)
        elif args[:2] == ['docker', 'inspect']:
            assert set(args[2:]) == {item['Id'] for item in self.containers}
            stdout = json.dumps(self.containers)
        elif args[:2] == ['docker', 'update']:
            assert args == ['docker', 'update', '--memory', '384m', '--memory-swap', '768m', ID]
            selected = next(item for item in self.containers if item['Id'] == ID)
            selected['HostConfig'] = {'Memory': operation.MEMORY, 'MemorySwap': operation.SWAP}
            if self.after_update:
                self.after_update(self.containers)
            stdout = ID
        elif args[:2] == ['docker', 'logs']:
            assert args == ['docker', 'logs', '--timestamps', '--since', STARTED, '--tail', '200', ID]
            stdout = self.logs[0]
            if len(self.logs) > 1:
                self.logs.pop(0)
            if self.after_logs:
                self.after_logs(self.containers)
                self.after_logs = None
        else:
            raise AssertionError('Unexpected Docker command')
        return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=0)

    def install(self, monkeypatch):
        monkeypatch.setattr(operation, 'run', self.run)
        monkeypatch.setattr(operation, 'host_memory', lambda: (self.total, self.available))
        monkeypatch.setattr(operation, 'time', SimpleNamespace(monotonic=lambda: self.now,
            sleep=lambda seconds: setattr(self, 'now', self.now + seconds)))


def test_scoped_update_accepts_prior_restarts_and_waits_for_current_cycle_privately(monkeypatch, capsys):
    probe = Probe(logs=[PRIVATE, '2026-10-06T10:00:03Z Deleted 0 expired files.\n'])
    probe.install(monkeypatch)
    operation.stabilize(timeout=5, interval=1)
    assert probe.now == 1
    assert [args for args in probe.commands if args[:2] == ['docker', 'update']] == [
        ['docker', 'update', '--memory', '384m', '--memory-swap', '768m', ID]]
    output = capsys.readouterr()
    assert output.out.strip() == operation.SUCCESS
    assert PRIVATE not in output.out + output.err and 'Deleted 0' not in output.out
    assert all(args[:2] not in [['docker', 'restart'], ['docker', 'compose'], ['docker', 'prune']]
               for args in probe.commands)


@pytest.mark.parametrize('memory', [192 * operation.MIB, operation.MEMORY])
def test_only_authorized_initial_limits_are_accepted(monkeypatch, memory):
    probe = Probe(containers=[container(memory=memory), container(OTHER)])
    probe.install(monkeypatch)
    operation.stabilize(timeout=5, interval=1)


@pytest.mark.parametrize('change', ['wrong-name', 'wrong-project', 'wrong-service', 'duplicate', 'missing',
                                    'not-running', 'oom', 'unauthorized-memory', 'small-server', 'low-free'])
def test_unsafe_initial_selection_never_mutates(monkeypatch, capsys, change):
    probe = Probe()
    selected = probe.containers[0]
    if change == 'wrong-name': selected['Name'] = '/another-cleanup-1'
    elif change == 'wrong-project': selected['Config']['Labels']['com.docker.compose.project'] = 'orderdesk'
    elif change == 'wrong-service': selected['Config']['Labels']['com.docker.compose.service'] = 'worker'
    elif change == 'duplicate':
        duplicate = copy.deepcopy(selected); duplicate['Id'] = 'c' * 64
        duplicate['Name'] = '/pdfmaster-platform-cleanup-2'; probe.containers.append(duplicate)
    elif change == 'missing': probe.containers.pop(0)
    elif change == 'not-running': selected['State']['Running'] = False
    elif change == 'oom': selected['State']['OOMKilled'] = True
    elif change == 'unauthorized-memory': selected['HostConfig']['Memory'] = 256 * operation.MIB
    elif change == 'small-server': probe.total = 2 * 1024 ** 3
    elif change == 'low-free': probe.available = 1024 ** 3 - 1
    probe.install(monkeypatch)
    with pytest.raises(operation.StabilizationError):
        operation.stabilize(timeout=5, interval=1)
    assert not any(args[:2] == ['docker', 'update'] for args in probe.commands)
    output = capsys.readouterr()
    assert PRIVATE not in output.out + output.err and not output.out


@pytest.mark.parametrize('change', ['restart-count', 'started-at', 'oom', 'exited', 'memory', 'swap',
                                    'identity', 'other-started', 'other-image', 'other-mount',
                                    'other-network', 'other-port', 'other-added', 'other-deleted'])
def test_restart_oom_or_changed_isolation_cannot_report_success(monkeypatch, capsys, change):
    def alter(containers):
        selected, other = containers[:2]
        if change == 'restart-count': selected['RestartCount'] += 1
        elif change == 'started-at': selected['State']['StartedAt'] = '2026-10-06T10:00:04Z'
        elif change == 'oom': selected['State']['OOMKilled'] = True
        elif change == 'exited': selected['State']['Running'] = False
        elif change == 'memory': selected['HostConfig']['Memory'] = 192 * operation.MIB
        elif change == 'swap': selected['HostConfig']['MemorySwap'] = 1024 * operation.MIB
        elif change == 'identity': selected['Id'] = 'c' * 64
        elif change == 'other-started': other['State']['StartedAt'] = '2026-10-06T10:00:04Z'
        elif change == 'other-image': other['Image'] = 'sha256:different'
        elif change == 'other-mount': other['Mounts'][0]['Destination'] = '/new-data'
        elif change == 'other-network': other['NetworkSettings']['Networks'] = {}
        elif change == 'other-port': other['NetworkSettings']['Ports'] = {'80/tcp': []}
        elif change == 'other-added': containers.append(container('c' * 64))
        elif change == 'other-deleted': containers.pop()
    probe = Probe(after_logs=alter)
    probe.install(monkeypatch)
    with pytest.raises(operation.StabilizationError):
        operation.stabilize(timeout=5, interval=1)
    assert not capsys.readouterr().out


@pytest.mark.parametrize('log', [
    '2026-10-06T09:59:59Z Deleted 0 expired files.',
    STARTED + ' Deleted 0 expired files.',
    '2026-10-06T10:00:00.123456788Z Deleted 0 expired files.',
    'Deleted 0 expired files.',
    '2026-10-06T10:00:01Z Error: Deleted 0 expired files.',
    '2026-10-06T10:00:01Z Deleted 0 expired files. not actually completed',
    PRIVATE,
])
def test_old_unanchored_or_failed_markers_time_out_privately(monkeypatch, capsys, log):
    probe = Probe(logs=[log]); probe.install(monkeypatch)
    with pytest.raises(operation.StabilizationError, match='bounded wait'):
        operation.stabilize(timeout=3, interval=1)
    assert probe.now == 3 and not capsys.readouterr().out


def test_completion_must_be_strictly_after_start_with_nanosecond_precision():
    assert operation.completed('2026-10-06T10:00:00.123456790Z Deleted 1 expired files.', STARTED)
    assert not operation.completed(STARTED + ' Deleted 1 expired files.', STARTED)


def test_real_command_wrapper_never_exposes_docker_error_or_environment(monkeypatch, capsys):
    monkeypatch.setattr(operation.subprocess, 'run', lambda *args, **kwargs:
                        SimpleNamespace(returncode=1, stdout=PRIVATE, stderr=PRIVATE))
    with pytest.raises(operation.StabilizationError) as error:
        operation.run(['docker', 'inspect', ID])
    output = capsys.readouterr()
    assert PRIVATE not in str(error.value) + output.out + output.err


def test_inventory_rejects_abbreviated_container_ids(monkeypatch):
    monkeypatch.setattr(operation, 'run', lambda *args, **kwargs:
                        SimpleNamespace(stdout=ID[:12], stderr=''))
    with pytest.raises(operation.StabilizationError, match='inventory'):
        operation.inspect_all()
