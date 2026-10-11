#!/usr/bin/env python3
"""Fetch the document scanner's model files, pinned in processors/scanner/models.json.

Standard library only: the image build runs it before the application is
copied in. Each file is streamed to a temporary name inside the destination
folder, checked against its byte count and SHA-256 and only then renamed into
place, so a folder never holds a partial or wrong model under its real name.
Files already present and correct are skipped. Any failure exits non-zero.

    python scripts/fetch_scanner_models.py --dest /opt/pdfmaster/scanner-models

The destination defaults to SCANNER_MODELS. Files without a URL ship in
processors/scanner/models/ and are only checked when present there.
"""
import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

MANIFEST = Path(__file__).resolve().parent.parent / 'processors' / 'scanner' / 'models.json'
ATTEMPTS = 4
TIMEOUT = 60
CHUNK = 1 << 20


class Mismatch(Exception):
    """The server sent a complete file with the wrong bytes: retrying cannot help."""


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(CHUNK), b''):
            digest.update(block)
    return digest.hexdigest()


def correct(path, spec):
    return path.is_file() and path.stat().st_size == spec['bytes'] and sha256(path) == spec['sha256']


def download(name, spec, folder):
    """One attempt: stream into a temporary file next to the target, verify, rename."""
    handle, temporary = tempfile.mkstemp(prefix=f'.{name}.', suffix='.part', dir=folder)
    try:
        digest, size = hashlib.sha256(), 0
        request = urllib.request.Request(spec['url'], headers={'User-Agent': 'pdfmaster-scanner-models'})
        with os.fdopen(handle, 'wb') as out, urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            while block := response.read(CHUNK):
                size += len(block)
                if size > spec['bytes']:
                    raise Mismatch(f'more than the pinned {spec["bytes"]} bytes')
                digest.update(block)
                out.write(block)
            out.flush()
            os.fsync(out.fileno())
        if size != spec['bytes']:
            raise OSError(f'incomplete download: {size} of {spec["bytes"]} bytes')
        if digest.hexdigest() != spec['sha256']:
            raise Mismatch(f'sha256 {digest.hexdigest()} is not the pinned {spec["sha256"]}')
        os.chmod(temporary, 0o644)
        os.replace(temporary, folder / name)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def fetch(name, spec, folder):
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return download(name, spec, folder)
        except Mismatch:
            raise
        except (OSError, urllib.error.URLError) as error:
            if attempt == ATTEMPTS:
                raise
            print(f'  {name}: attempt {attempt} failed ({error}); retrying', file=sys.stderr)
            time.sleep(2 ** attempt)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--dest', default=os.environ.get('SCANNER_MODELS'),
                        help='folder for the model files (default: $SCANNER_MODELS)')
    parser.add_argument('--manifest', type=Path, default=MANIFEST, help='models.json to follow')
    args = parser.parse_args(argv)
    if not args.dest:
        parser.error('--dest or SCANNER_MODELS is required')
    folder = Path(args.dest)
    folder.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(args.manifest.read_text())
    bundled = args.manifest.resolve().parent / 'models'
    failed = []
    for name, spec in manifest['files'].items():
        if Path(name).name != name or name.startswith('.'):
            failed.append(name)
            print(f'{name}: not a plain file name', file=sys.stderr)
            continue
        if not spec.get('url'):
            path = bundled / name
            if path.exists() and not correct(path, spec):
                failed.append(name)
                print(f'{name}: the bundled copy does not match models.json', file=sys.stderr)
            continue
        if correct(folder / name, spec):
            print(f'{name}: present')
            continue
        try:
            fetch(name, spec, folder)
            print(f'{name}: fetched {spec["bytes"]} bytes')
        except (Mismatch, OSError, urllib.error.URLError) as error:
            failed.append(name)
            print(f'{name}: {error}', file=sys.stderr)
    if failed:
        print('Scanner models failed: ' + ', '.join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
