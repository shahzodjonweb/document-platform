#!/usr/bin/env python3
"""Fetch the PdfCraft command line tool, pinned in processors/pdfcraft/manifest.json.

Standard library only: the image build runs it before the application is
copied in. The archive for this machine is streamed to a temporary file and
checked against its byte count and SHA-256. Only then are the binary and its
licence files copied out, flat, into the destination, each through a temporary
name and a rename, so a folder never holds a partial binary under its real
name. An archive holding anything but plain files and folders under safe names
is refused whole. Everything ends up a=rX. A destination that already holds
what this archive installed is left alone. Any failure exits non-zero.

    python scripts/fetch_pdfcraft.py --dest /opt/pdfmaster/pdfcraft
"""
import argparse
import fnmatch
import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import platform
import stat
import sys
import tarfile
import tempfile
import time
import urllib.request
import zlib

MANIFEST = Path(__file__).resolve().parent.parent / 'processors' / 'pdfcraft' / 'manifest.json'
ATTEMPTS = 4
TIMEOUT = 60
CHUNK = 1 << 20
BINARY = 'pdfcraft-cli'
LICENCES = ('LICENSE-*', 'NOTICE', 'OFL-*')
# What the last install wrote, so that a later run can tell it is still whole.
STAMP = '.installed.json'


class Mismatch(Exception):
    """The server sent a complete file with the wrong bytes: retrying cannot help."""


class Unsafe(Exception):
    """The archive holds something that must never be unpacked."""


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(CHUNK), b''):
            digest.update(block)
    return digest.hexdigest()


def mode_of(name):
    return 0o555 if name == BINARY else 0o444


def correct(path, spec, mode):
    return (path.is_file() and not path.is_symlink() and stat.S_IMODE(path.stat().st_mode) == mode
            and path.stat().st_size == spec['bytes'] and sha256(path) == spec['sha256'])


def installed(folder, archive):
    """Whether the folder still holds exactly what this archive put there."""
    try:
        stamp = json.loads((folder / STAMP).read_text())
        return (stamp['archive_sha256'] == archive['sha256'] and BINARY in stamp['files']
                and all(correct(folder / name, spec, mode_of(name)) for name, spec in stamp['files'].items()))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def pick_archive(manifest, machine):
    """The archive for platform.machine(); a machine the release does not cover has none."""
    try:
        return manifest['archives'][machine]
    except KeyError:
        raise Mismatch(f'no archive for {machine}') from None


def download(archive, target):
    """One attempt: stream into the target and verify it."""
    digest, size = hashlib.sha256(), 0
    request = urllib.request.Request(archive['url'], headers={'User-Agent': 'docmaster-pdfcraft'})
    with open(target, 'wb') as out, urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        while block := response.read(CHUNK):
            size += len(block)
            if size > archive['bytes']:
                raise Mismatch(f'more than the pinned {archive["bytes"]} bytes')
            digest.update(block)
            out.write(block)
    if size != archive['bytes']:
        raise OSError(f'incomplete download: {size} of {archive["bytes"]} bytes')
    if digest.hexdigest() != archive['sha256']:
        raise Mismatch(f'sha256 {digest.hexdigest()} is not the pinned {archive["sha256"]}')


def fetch(archive, target):
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return download(archive, target)
        except Mismatch:
            raise
        except (OSError, http.client.HTTPException) as error:
            if attempt == ATTEMPTS:
                raise
            print(f'  attempt {attempt} failed ({error}); retrying', file=sys.stderr)
            time.sleep(2 ** attempt)


def wanted(name):
    return name == BINARY or any(fnmatch.fnmatchcase(name, pattern) for pattern in LICENCES)


def selection(members):
    """{flat name: member} of what to unpack, after refusing an archive that holds anything unsafe."""
    chosen = {}
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or '..' in path.parts or '\\' in member.name:
            raise Unsafe(f'unsafe member name {member.name!r}')
        if not (member.isfile() or member.isdir()):
            raise Unsafe(f'{member.name!r} is neither a file nor a folder')
        if member.isfile() and wanted(path.name):
            if path.name in chosen:
                raise Unsafe(f'two members are named {path.name!r}')
            chosen[path.name] = member
    if BINARY not in chosen:
        raise Unsafe(f'no {BINARY} in the archive')
    if not any(fnmatch.fnmatchcase(name, LICENCES[0]) for name in chosen):
        raise Unsafe('no licence in the archive')
    return chosen


def unpack(source, name, folder):
    """Copy one member out through a temporary name; returns its size and digest."""
    handle, temporary = tempfile.mkstemp(prefix=f'.{name}.', suffix='.part', dir=folder)
    try:
        digest, size = hashlib.sha256(), 0
        with os.fdopen(handle, 'wb') as out:
            while block := source.read(CHUNK):
                size += len(block)
                digest.update(block)
                out.write(block)
        os.chmod(temporary, mode_of(name))
        os.replace(temporary, folder / name)
        return {'bytes': size, 'sha256': digest.hexdigest()}
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def install(path, archive, folder):
    """Unpack the verified archive into the folder, then seal it. Nothing else in the folder is touched."""
    with tarfile.open(path, 'r:gz') as bundle:
        chosen = selection(bundle.getmembers())
        folder.mkdir(parents=True, exist_ok=True)
        folder.chmod(0o755)
        (folder / STAMP).unlink(missing_ok=True)
        files = {}
        for name, member in chosen.items():
            with bundle.extractfile(member) as source:
                files[name] = unpack(source, name, folder)
    (folder / STAMP).write_text(json.dumps({'archive_sha256': archive['sha256'], 'files': files}, indent=1) + '\n')
    (folder / STAMP).chmod(0o444)
    folder.chmod(0o555)
    return files


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--dest', required=True, type=Path, help='folder for the binary and its licences')
    parser.add_argument('--manifest', type=Path, default=MANIFEST, help='manifest.json to follow')
    args = parser.parse_args(argv)
    try:
        archive = pick_archive(json.loads(args.manifest.read_text()), platform.machine())
        if installed(args.dest, archive):
            print(f'{BINARY}: present')
            return 0
        with tempfile.TemporaryDirectory(prefix='pdfcraft-fetch-') as scratch:
            path = Path(scratch) / 'archive.tar.gz'
            fetch(archive, path)
            files = install(path, archive, args.dest)
    except (Mismatch, Unsafe, OSError, ValueError, http.client.HTTPException, tarfile.TarError, EOFError, zlib.error) as error:
        print(f'PdfCraft failed: {error}', file=sys.stderr)
        return 1
    print(f'{BINARY}: fetched {archive["bytes"]} bytes, unpacked {len(files)} files')
    return 0


if __name__ == '__main__':
    sys.exit(main())
