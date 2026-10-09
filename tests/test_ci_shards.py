"""CI's shards cover the suite exactly once, whatever the timings say."""
from types import SimpleNamespace

from scripts.shards import split


def items(layout):
    return [SimpleNamespace(nodeid=f'{name}::test_{n}') for name, count in layout.items() for n in range(count)]


def shards(collected, total, timings):
    shard_of = split(collected, total, timings)
    return [[item.nodeid for item in collected if shard_of[id(item)] == index] for index in range(total)]


def test_every_test_runs_in_exactly_one_shard_and_every_shard_agrees():
    collected = items({'tests/test_a.py': 40, 'tests/test_b.py': 3, 'tests/test_c.py': 12, 'tests/test_new.py': 5})
    timings = {'tests/test_a.py': 600, 'tests/test_b.py': 20, 'tests/test_c.py': 90}
    first = shards(collected, 4, timings)
    assert sorted(sum(first, [])) == sorted(item.nodeid for item in collected)
    # Every runner collects the same tests in the same order and must split them the same way.
    assert shards(items({'tests/test_a.py': 40, 'tests/test_b.py': 3, 'tests/test_c.py': 12,
                         'tests/test_new.py': 5}), 4, timings) == first


def test_a_file_heavier_than_a_share_is_cut_and_the_rest_stay_whole():
    collected = items({'tests/test_heavy.py': 30, 'tests/test_light.py': 6, 'tests/test_other.py': 6})
    result = shards(collected, 3, {'tests/test_heavy.py': 300, 'tests/test_light.py': 30, 'tests/test_other.py': 30})
    holding = lambda name: [index for index, shard in enumerate(result) if any(n.startswith(name) for n in shard)]
    assert len(holding('tests/test_heavy.py')) >= 2
    assert len(holding('tests/test_light.py')) == 1 and len(holding('tests/test_other.py')) == 1


def test_without_timings_files_count_the_same_and_still_cover_everything():
    collected = items({f'tests/test_{n}.py': 2 for n in range(9)})
    result = shards(collected, 3, {})
    assert sorted(len(shard) for shard in result) == [6, 6, 6]
