"""Run one CI shard of the suite: PYTEST_SHARD=3/8. See scripts/shards.py."""
import os


def pytest_collection_modifyitems(config, items):
    shard = os.environ.get('PYTEST_SHARD', '')
    if not shard:
        return
    from scripts.shards import split, timings
    index, total = (int(part) for part in shard.split('/'))
    if not 1 <= index <= total:
        raise ValueError(f'PYTEST_SHARD={shard} is not between 1/{total} and {total}/{total}')
    shard_of = split(items, total, timings())
    kept = [item for item in items if shard_of[id(item)] == index - 1]
    keep = {id(item) for item in kept}
    config.hook.pytest_deselected(items=[item for item in items if id(item) not in keep])
    items[:] = kept
