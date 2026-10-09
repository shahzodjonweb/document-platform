"""Choose what a CI run tests.

PYTEST_TIER=core runs only the main cases listed in tests/core_tests.txt: one
test for each main path a customer relies on, and one for each guard whose
regression would cost money, leak data or let someone in. CI runs that on every
push; the full suite stays here for manual runs (`workflow_dispatch`, or plain
pytest locally). A listed test that no longer exists fails the run, so the list
cannot shrink silently.

PYTEST_SHARD=3/8 runs one shard of whatever is selected. See scripts/shards.py.
"""
import os
import re
from pathlib import Path

import pytest

CORE = Path(__file__).with_name('tests') / 'core_tests.txt'


def core_ids():
    # A comment starts a line or follows a space: ids such as `[#1F3A68]` keep their `#`.
    lines = (re.sub(r'(^|\s)#.*$', '', line).strip() for line in CORE.read_text().splitlines())
    return [line for line in lines if line]


def keep_only(config, items, kept):
    keep = {id(item) for item in kept}
    config.hook.pytest_deselected(items=[item for item in items if id(item) not in keep])
    items[:] = kept


def pytest_collection_modifyitems(config, items):
    if os.environ.get('PYTEST_TIER', '') == 'core':
        wanted = core_ids()
        found = {item.nodeid for item in items}
        missing = [nodeid for nodeid in wanted if nodeid not in found]
        if missing:
            raise pytest.UsageError('tests/core_tests.txt lists tests that do not exist:\n  ' + '\n  '.join(missing))
        wanted = set(wanted)
        keep_only(config, items, [item for item in items if item.nodeid in wanted])
    shard = os.environ.get('PYTEST_SHARD', '')
    if not shard:
        return
    from scripts.shards import split, timings
    index, total = (int(part) for part in shard.split('/'))
    if not 1 <= index <= total:
        raise ValueError(f'PYTEST_SHARD={shard} is not between 1/{total} and {total}/{total}')
    shard_of = split(items, total, timings())
    keep_only(config, items, [item for item in items if shard_of[id(item)] == index - 1])
