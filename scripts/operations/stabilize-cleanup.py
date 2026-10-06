"""Raise only the authorized cleanup container's live memory limit, without restart.

Run by the pinned-host operations workflow. Docker output, inspection data and
application logs stay private; only controlled result markers are printed.
"""
import calendar
import copy
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import time


PROJECT = 'pdfmaster-platform'
SERVICE = 'cleanup'
NAME = '/pdfmaster-platform-cleanup-1'
MIB = 1024 * 1024
MEMORY = 384 * MIB
SWAP = 768 * MIB
SUCCESS = 'STABILIZE_CLEANUP_OK memory_mib=384 current_cycle=completed isolation=verified'
STAMP = r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z'
COMPLETION = re.compile(r'(' + STAMP + r') Deleted [0-9]+ expired files\.')


class StabilizationError(RuntimeError):
    pass


def run(args, *, timeout=20):
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise StabilizationError('Docker command unavailable or timed out') from None
    if result.returncode:
        raise StabilizationError('Docker command failed; private output suppressed')
    if len(result.stdout) + len(result.stderr) > 2 * MIB:
        raise StabilizationError('Docker response exceeded the private output limit')
    return result


def host_memory():
    try:
        value = Path('/proc/meminfo').read_text()
        values = {key: int(number) * 1024 for key, number in
                  re.findall(r'^(MemTotal|MemAvailable):\s+(\d+) kB$', value, re.MULTILINE)}
        return values['MemTotal'], values['MemAvailable']
    except (OSError, KeyError, ValueError):
        raise StabilizationError('Host memory could not be verified') from None


def inspect_all(*, timeout=20):
    deadline = time.monotonic() + timeout
    identifiers = run(['docker', 'ps', '-aq', '--no-trunc'], timeout=timeout).stdout.split()
    if (not identifiers or len(set(identifiers)) != len(identifiers)
            or any(not re.fullmatch(r'[a-f0-9]{64}', item) for item in identifiers)):
        raise StabilizationError('Container inventory could not be verified')
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise StabilizationError('Container inventory timed out')
    try:
        containers = json.loads(run(['docker', 'inspect', *identifiers], timeout=remaining).stdout)
        if not isinstance(containers, list) or len(containers) != len(identifiers):
            raise ValueError
        if {item['Id'] for item in containers} != set(identifiers):
            raise ValueError
        return containers
    except (ValueError, TypeError, KeyError):
        raise StabilizationError('Container inventory was invalid') from None


def fingerprint(container):
    """Only immutable identity and deployment isolation fields, never env."""
    return copy.deepcopy({
        'id': container['Id'], 'name': container['Name'],
        'started': container['State']['StartedAt'],
        'image_id': container['Image'], 'image': container['Config']['Image'],
        'mounts': container['Mounts'],
        'networks': container['NetworkSettings']['Networks'],
        'ports': container['NetworkSettings']['Ports'],
    })


def timestamp_ns(value):
    if not isinstance(value, str) or not re.fullmatch(STAMP, value):
        raise StabilizationError('Cleanup start timestamp was invalid')
    base, _, fraction = value[:-1].partition('.')
    try:
        seconds = calendar.timegm(datetime.strptime(base, '%Y-%m-%dT%H:%M:%S').timetuple())
    except ValueError:
        raise StabilizationError('Cleanup start timestamp was invalid') from None
    return seconds * 1_000_000_000 + int((fraction + '0' * 9)[:9])


def select_cleanup(containers):
    candidates = [item for item in containers
        if (item['Config'].get('Labels') or {}).get('com.docker.compose.project') == PROJECT
        and (item['Config'].get('Labels') or {}).get('com.docker.compose.service') == SERVICE
        and item['State'].get('Running') is True]
    if len(candidates) != 1 or candidates[0]['Name'] != NAME:
        raise StabilizationError('Expected exactly one running named PDF Master cleanup service')
    selected = candidates[0]
    state = selected['State']
    if state.get('Status') != 'running' or state.get('Restarting') or state.get('Dead') or state.get('OOMKilled'):
        raise StabilizationError('Cleanup is not in a stable running incarnation')
    if type(selected.get('RestartCount')) is not int or selected['RestartCount'] < 0:
        raise StabilizationError('Cleanup restart baseline was invalid')
    if selected['HostConfig'].get('Memory') not in {192 * MIB, MEMORY}:
        raise StabilizationError('Cleanup memory limit was outside the authorized values')
    timestamp_ns(state.get('StartedAt'))
    return selected


def unchanged(containers, original, others):
    current = {item['Id']: item for item in containers}
    identifier = original['Id']
    if identifier not in current:
        raise StabilizationError('Cleanup identity changed')
    selected = current[identifier]
    state = selected['State']
    if state.get('OOMKilled'):
        raise StabilizationError('Cleanup was OOM-killed after stabilization began')
    if state.get('Running') is not True or state.get('Status') != 'running' or state.get('Restarting') or state.get('Dead'):
        raise StabilizationError('Cleanup is no longer running')
    if (selected.get('RestartCount') != original.get('RestartCount')
            or state.get('StartedAt') != original['State']['StartedAt']):
        raise StabilizationError('Cleanup restarted after stabilization began')
    if selected['HostConfig'].get('Memory') != MEMORY or selected['HostConfig'].get('MemorySwap') != SWAP:
        raise StabilizationError('Cleanup memory update was not applied')
    if fingerprint(selected) != fingerprint(original):
        raise StabilizationError('Cleanup deployment identity or isolation changed')
    now_others = {item['Id']: fingerprint(item) for item in containers if item['Id'] != identifier}
    if now_others != others:
        raise StabilizationError('Another container changed during stabilization')
    return selected


def completed(output, started):
    start = timestamp_ns(started)
    for line in output.splitlines():
        marker = COMPLETION.fullmatch(line)
        if marker:
            try:
                if timestamp_ns(marker.group(1)) > start:
                    return True
            except StabilizationError:
                continue
    return False


def stabilize(*, timeout=135, interval=5):
    if not 0 < timeout <= 150 or not 0 < interval <= 10:
        raise StabilizationError('Invalid bounded verification period')
    total, available = host_memory()
    if total < 7 * 1024 ** 3 or available < 1024 ** 3:
        raise StabilizationError('Host needs at least 7 GiB total and 1 GiB available memory')
    before = inspect_all()
    selected = select_cleanup(before)
    original = copy.deepcopy(selected)
    others = {item['Id']: fingerprint(item) for item in before if item['Id'] != selected['Id']}
    # The exact inspected ID is the only mutation target. Docker update leaves
    # the process and its start time intact; no compose/restart/prune is used.
    run(['docker', 'update', '--memory', '384m', '--memory-swap', '768m', selected['Id']])
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise StabilizationError('Cleanup current cycle did not complete within the bounded wait')
        command_timeout = min(20, remaining)
        unchanged(inspect_all(timeout=command_timeout), original, others)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise StabilizationError('Cleanup current cycle did not complete within the bounded wait')
        logs = run(['docker', 'logs', '--timestamps', '--since', original['State']['StartedAt'],
                    '--tail', '200', selected['Id']], timeout=min(20, remaining))
        if completed(logs.stdout, original['State']['StartedAt']):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise StabilizationError('Cleanup verification exceeded the bounded wait')
            unchanged(inspect_all(timeout=min(20, remaining)), original, others)
            print(SUCCESS, flush=True)
            return
        time.sleep(min(interval, max(0, deadline - time.monotonic())))


if __name__ == '__main__':
    try:
        stabilize()
    except StabilizationError as error:
        print('STABILIZE_CLEANUP_FAILED ' + str(error), flush=True)
        raise SystemExit(1) from None
    except Exception:
        print('STABILIZE_CLEANUP_FAILED unexpected verification failure; private output suppressed', flush=True)
        raise SystemExit(1) from None
