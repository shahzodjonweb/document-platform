"""How CI splits the suite into shards, and the timings the split is balanced by.

conftest.py (repo root) applies `split` when PYTEST_SHARD=3/8 is set; CI runs
one job per shard (.github/workflows/ci.yml). Whole test files are dealt out
heaviest first to the least-loaded shard, by the seconds each took when last
measured (tests/shard_timings.json; a file not listed counts as a typical one).
Keeping a file together keeps its module fixtures — some scan a document once
for the whole file — from running on every shard. A file heavier than a
shard's share is cut into consecutive chunks.

Every shard computes the same split from the same collection, so each test
runs in exactly one shard. Stale timings only unbalance the shards; they never
drop a test.

Refresh the timings when a file gets much slower or faster:

    python -m pytest tests apps/commerce/tests --junitxml=/tmp/timings.xml
    python scripts/shards.py /tmp/timings.xml
"""
import json
import math
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TIMINGS = ROOT / 'tests' / 'shard_timings.json'


def timings():
    return json.loads(TIMINGS.read_text()) if TIMINGS.exists() else {}


def split(items, total, timings):
    """Shard number (0-based) for every item."""
    files = {}
    for item in items:
        files.setdefault(item.nodeid.split('::')[0], []).append(item)
    known = sorted(timings.values())
    typical = known[len(known) // 2] if known else 1.0
    weights = {name: float(timings.get(name, typical)) for name in files}
    share = sum(weights.values()) / total
    units = []
    for name, members in files.items():
        pieces = max(1, min(len(members), math.ceil(weights[name] / share))) if share else 1
        size = math.ceil(len(members) / pieces)
        for start in range(0, len(members), size):
            chunk = members[start:start + size]
            units.append((weights[name] * len(chunk) / len(members), name, start, chunk))
    loads = [0.0] * total
    shard_of = {}
    for weight, name, start, chunk in sorted(units, key=lambda unit: (-unit[0], unit[1], unit[2])):
        target = min(range(total), key=lambda index: (loads[index], index))
        loads[target] += weight
        for item in chunk:
            shard_of[id(item)] = target
    return shard_of


def record(report):
    """Write TIMINGS from a pytest JUnit report: seconds per test file."""
    seconds = {}
    for case in ElementTree.parse(report).iter('testcase'):
        module = case.get('classname', '').split('.')
        # classname is "tests.test_x" or "tests.test_x.TestClass": find the module part.
        for end in range(len(module), 0, -1):
            path = Path(*module[:end]).with_suffix('.py')
            if (ROOT / path).is_file():
                name = path.as_posix()
                seconds[name] = seconds.get(name, 0.0) + float(case.get('time') or 0)
                break
    TIMINGS.write_text(json.dumps({k: round(v, 1) for k, v in sorted(seconds.items())}, indent=1) + '\n')
    print(f'{len(seconds)} files, {sum(seconds.values()) / 60:.1f} min -> {TIMINGS.relative_to(ROOT)}')


if __name__ == '__main__':
    record(sys.argv[1])
