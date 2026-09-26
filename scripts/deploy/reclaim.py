#!/usr/bin/env python3
"""Reclaim disk a PDF Master component has filled, by hand.

The release protocol now does this on every deployment, but it runs on the
server and therefore needs enough free space to land there first. When a disk
is already full, run this once to break the deadlock.

It reports before it removes anything. Nothing is deleted without --apply.

    python3 reclaim.py --component platform
    python3 reclaim.py --component platform --apply

It keeps the active release, the previous one rollback depends on, any pending
one, and the newest few database dumps and delivered script directories. It
stays inside ~/pdf-master/<component>/ and never prunes Docker globally: the
host serves other projects.
"""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

KEEP = 5


def size_of(path):
    total = 0
    for item in path.rglob('*') if path.is_dir() else []:
        if item.is_file() and not item.is_symlink():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def human(value):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if value < 1024 or unit == 'GB':
            return f'{value:.0f} {unit}' if unit == 'B' else f'{value:.1f} {unit}'
        value /= 1024


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--component', required=True, choices=('platform', 'web'))
    parser.add_argument('--root', type=Path, default=None)
    parser.add_argument('--keep', type=int, default=KEEP)
    parser.add_argument('--apply', action='store_true', help='actually remove; otherwise report only')
    args = parser.parse_args()

    root = (args.root or Path.home() / 'pdf-master' / args.component).resolve()
    if not root.is_dir():
        raise SystemExit(f'No such component directory: {root}')

    state_path = root / 'state.json'
    state = json.loads(state_path.read_text()) if state_path.is_file() else {}
    keep_ids, keep_images = set(), set()
    for slot in ('active', 'previous', 'pending'):
        release = state.get(slot) or {}
        if release.get('release_id'):
            keep_ids.add(release['release_id'])
            keep_images.add(release.get('image'))
    print(f'component : {args.component}')
    print(f'root      : {root}')
    print(f'keeping   : {", ".join(sorted(keep_ids)) or "(nothing active yet)"}\n')

    doomed, freed = [], 0
    releases = root / 'releases'
    if releases.is_dir():
        for directory in sorted(releases.iterdir()):
            if not directory.is_dir() or directory.is_symlink() or directory.name in keep_ids:
                continue
            meta = {}
            try:
                meta = json.loads((directory / 'release.json').read_text())
            except (OSError, ValueError):
                pass
            image = meta.get('image')
            size = size_of(directory)
            freed += size
            doomed.append(('release', directory, image if image not in keep_images else None, size))

    for name, pattern in (('backup', 'backups/before-*.dump'), ('delivery', 'incoming/*')):
        items = sorted(
            (p for p in root.glob(pattern) if not p.is_symlink()),
            key=lambda p: p.stat().st_mtime if p.exists() else 0)
        for path in items[:max(0, len(items) - args.keep)]:
            size = size_of(path) if path.is_dir() else path.stat().st_size
            freed += size
            doomed.append((name, path, None, size))

    if not doomed:
        print('Nothing to reclaim.')
        return
    for kind, path, image, size in doomed:
        print(f'  {kind:9} {human(size):>9}  {path.name}' + (f'   (image {image})' if image else ''))
    print(f'\n{"Would free" if not args.apply else "Freeing"}: {human(freed)} in {len(doomed)} items')

    if not args.apply:
        print('\nRe-run with --apply to remove these.')
        return
    stranded = 0
    for kind, path, image, _ in doomed:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                path.unlink()
            except OSError:
                pass
        if image:
            # Docker refuses an image a running container still uses, which is
            # the guard we want. If Docker cannot be reached at all the files
            # still go: freeing the disk is the whole point of running this.
            try:
                result = subprocess.run(['docker', 'image', 'rm', image],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        check=False)
                stranded += 1 if result.returncode else 0
            except OSError:
                stranded += 1
    if stranded:
        print(f'\n{stranded} image(s) were left in place — still in use, already gone, '
              'or Docker was unreachable. The disk space above was still freed.')
    print('Done. Re-run the deployment; it keeps itself bounded from now on.')


if __name__ == '__main__':
    main()
