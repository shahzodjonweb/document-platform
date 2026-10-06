"""The service audit must reject late cleanup OOMs and obsolete success logs."""
import ast
import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/operations/verify-services.py'
IDENTIFIER = 'a' * 64
STARTED = '2026-10-06T10:00:00.123456789Z'
PRIVATE = 'VERIFY_PRIVATE fixture-sensitive-storage-key'


def helpers():
    # This operations script executes live probes at top level and is delivered
    # through SSH/stdin. Load its pure helpers without executing those probes.
    parsed = ast.parse(SCRIPT.read_text())
    names = {'cleanup_identity', 'cleanup_command', 'verify_cleanup_cycle'}
    module = ast.Module(body=[node for node in parsed.body
                              if isinstance(node, ast.FunctionDef) and node.name in names], type_ignores=[])
    namespace = {'json': json, 're': re}
    exec(compile(module, str(SCRIPT), 'exec'), namespace)
    return namespace


def container(**state):
    return {'Id': IDENTIFIER, 'RestartCount': 0, 'State': {
        'Running': True, 'Status': 'running', 'Restarting': False,
        'Dead': False, 'OOMKilled': False, 'StartedAt': STARTED, **state,
    }}


class DockerProbe:
    def __init__(self, *, ids=IDENTIFIER, states=None, logs=('Deleted 4 expired files.\n', '')):
        self.ids = ids
        self.states = list(states or [container()])
        self.logs = logs
        self.commands = []

    def run(self, args):
        self.commands.append(args)
        if args[:2] == ['docker', 'ps']:
            assert '--no-trunc' in args
            assert 'label=com.docker.compose.project=pdfmaster-platform' in args
            assert 'label=com.docker.compose.service=cleanup' in args
            return self.ids + '\n', ''
        if args[:2] == ['docker', 'inspect']:
            assert args[-1] == IDENTIFIER
            value = self.states[0]
            if len(self.states) > 1:
                self.states.pop(0)
            return json.dumps(value), ''
        if args[:2] == ['docker', 'logs']:
            assert args == ['docker', 'logs', '--since', STARTED, '--tail', '200', IDENTIFIER]
            return self.logs
        raise AssertionError('Unexpected Docker command')


def test_live_verification_pins_cleanup_release_and_reads_only_current_cycle(capsys):
    namespace = helpers()
    baseline = namespace['cleanup_identity'](container())
    probe = DockerProbe(logs=(PRIVATE + '\nDeleted 4 expired files.\n', PRIVATE))
    namespace['cleanup_command'] = probe.run
    namespace['verify_cleanup_cycle'](baseline)
    assert len([args for args in probe.commands if args[:2] == ['docker', 'inspect']]) == 2
    output = capsys.readouterr()
    assert output.out == 'VERIFY_CLEANUP_CYCLE_OK\n'
    assert not output.err


@pytest.mark.parametrize('change', ['oom', 'restart', 'stopped'])
def test_live_initial_cleanup_state_rejects_past_failure(change):
    namespace = helpers()
    value = container()
    if change == 'oom':
        value['State']['OOMKilled'] = True
    elif change == 'restart':
        value['RestartCount'] = 1
    else:
        value['State'].update(Running=False, Status='exited')
    with pytest.raises(SystemExit, match='stopped, restarted or was OOM-killed'):
        namespace['cleanup_identity'](value)


def test_live_final_cleanup_check_rejects_container_replacement():
    namespace = helpers()
    namespace['cleanup_command'] = DockerProbe(ids='b' * 64).run
    with pytest.raises(SystemExit, match='container changed'):
        namespace['verify_cleanup_cycle'](namespace['cleanup_identity'](container()))


def test_live_final_cleanup_check_rejects_manual_restart():
    namespace = helpers()
    namespace['cleanup_command'] = DockerProbe(states=[container(StartedAt='2026-10-06T10:01:00Z')]).run
    with pytest.raises(SystemExit, match='restarted during service checks'):
        namespace['verify_cleanup_cycle'](namespace['cleanup_identity'](container()))


def test_live_final_cleanup_check_rejects_oom_racing_success_log(capsys):
    namespace = helpers()
    namespace['cleanup_command'] = DockerProbe(states=[container(), container(OOMKilled=True)]).run
    with pytest.raises(SystemExit, match='OOM-killed'):
        namespace['verify_cleanup_cycle'](namespace['cleanup_identity'](container()))
    assert not capsys.readouterr().out


def test_live_final_cleanup_check_requires_a_completed_cycle(capsys):
    namespace = helpers()
    namespace['cleanup_command'] = DockerProbe(logs=(PRIVATE, 'Starting a cleanup run')).run
    with pytest.raises(SystemExit, match='has not completed a cleanup cycle'):
        namespace['verify_cleanup_cycle'](namespace['cleanup_identity'](container()))
    output = capsys.readouterr()
    assert not output.out and not output.err


def test_live_cleanup_command_failure_suppresses_even_verify_prefixed_private_logs(capsys):
    namespace = helpers()
    namespace['subprocess'] = SimpleNamespace(
        run=lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=PRIVATE, stderr=PRIVATE))
    with pytest.raises(SystemExit, match='could not read container state or logs'):
        namespace['cleanup_command'](['docker', 'logs', IDENTIFIER])
    output = capsys.readouterr()
    assert not output.out and not output.err
