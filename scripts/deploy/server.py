#!/usr/bin/env python3
"""PDF Master release protocol v2; identical in both application repositories.

Receives only CI-built images over authenticated SSH. Never runs git on the
server, edits another Compose project, prunes Docker, or deletes data volumes.
"""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

MAX_BUNDLE = 3 * 1024**3


class DeploymentError(Exception):
    pass


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def image_config_id(stream, image):
    """Canonical config digest from Docker's classic or OCI-backed save format.

    Docker 29's containerd store reports a manifest digest as image inspect.Id;
    the classic store reports the configuration digest. The config blob binds
    the runtime configuration and uncompressed layer digests in both stores.
    Read the archive without extracting paths or retaining layer contents.
    """
    configs, manifest = {}, None
    with tarfile.open(fileobj=stream, mode='r|*') as archive:
        for item in archive:
            if not item.isfile() or item.size > 4 * 1024**2:
                continue
            if item.name != 'manifest.json' and not (item.name.endswith('.json') or item.name.startswith('blobs/sha256/')):
                continue
            raw = archive.extractfile(item).read()
            try:
                value = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                continue
            if item.name == 'manifest.json':
                if manifest is not None or not isinstance(value, list):
                    raise DeploymentError('Invalid Docker save manifest.')
                manifest = value
            elif isinstance(value, dict) and 'architecture' in value and isinstance(value.get('rootfs', {}).get('diff_ids'), list):
                if item.name in configs:
                    raise DeploymentError('Duplicate image configuration blob.')
                configs[item.name] = 'sha256:' + hashlib.sha256(raw).hexdigest()
    matches = [entry for entry in (manifest or []) if isinstance(entry, dict) and
               image in [tag.removeprefix('docker.io/library/') for tag in (entry.get('RepoTags') or [])]]
    if len(matches) != 1 or matches[0].get('Config') not in configs:
        raise DeploymentError('Cannot verify the saved image configuration identity.')
    return configs[matches[0]['Config']]


def read_json(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def command(args, *, env=None, input_stream=None, output_stream=None):
    # Capture errors: do not print commands/env or Docker configuration containing
    # database credentials. Operators can inspect service logs on their server.
    result = subprocess.run(args, env=env, stdin=input_stream,
                            stdout=output_stream or subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=900)
    if result.returncode:
        raise DeploymentError("Command failed: " + " ".join(args[:3]) +
                              ". Inspect PDF Master service logs on the server.")
    return result.stdout.decode().strip() if output_stream is None else ""


def environment(root, component):
    path = root / ".env"
    if not path.is_file() or path.is_symlink():
        raise DeploymentError("Initialize this component environment with init_environment.py first.")
    if path.stat().st_mode & 0o077:
        raise DeploymentError("Set production .env permissions to 600.")
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*=.*", line):
            raise DeploymentError("Production .env requires plain KEY=value entries.")
        key, value = line.split("=", 1)
        if key in values:
            raise DeploymentError("Production .env contains duplicate keys.")
        values[key] = value
    expected_domain = 'pdfmaster-admin.orderdesk.live' if component == 'platform' else 'pdfmaster.orderdesk.live'
    if values.get('PUBLIC_DOMAIN') != expected_domain:
        raise DeploymentError('PUBLIC_DOMAIN does not match this component domain.')
    if component == 'platform':
        for key in ("SECRET_KEY", "POSTGRES_PASSWORD", "FILE_SECRET_KEY", "INTEGRATION_ENCRYPTION_KEY"):
            if len(values.get(key, "")) < 32 or "replace" in values[key].lower():
                raise DeploymentError("Missing or placeholder production secret: " + key)
        if not re.fullmatch(r"[A-Za-z0-9_-]+", values["POSTGRES_PASSWORD"]):
            raise DeploymentError("POSTGRES_PASSWORD must be URL-safe letters, digits, _ or -.")
        for key in ("DEBUG", "DEVELOPMENT_LOGIN_ENABLED", "LOCAL_SYNC_JOBS", "COMMERCE_SANDBOX_ENABLED"):
            if values.get(key, "0") != "0":
                raise DeploymentError("Development settings must remain disabled: " + key)
        origins = values.get("CSRF_TRUSTED_ORIGINS", "").split(",")
        if not origins or any(not re.fullmatch(r"https://[a-zA-Z0-9.-]+(?::[0-9]+)?", x) for x in origins):
            raise DeploymentError("Set explicit HTTPS CSRF_TRUSTED_ORIGINS.")
        if not values.get("ALLOWED_HOSTS") or "*" in values["ALLOWED_HOSTS"]:
            raise DeploymentError("Set explicit ALLOWED_HOSTS.")
    port = values.get("PDFMASTER_HTTP_PORT", "8310")
    if not port.isdigit() or not 1024 <= int(port) <= 65535:
        raise DeploymentError("PDFMASTER_HTTP_PORT must be an unprivileged port.")
    if values.get("COMPOSE_PROFILES", "") not in ("", "bot"):
        raise DeploymentError("Only the optional bot profile is supported.")
    return values


def validate_manifest(meta):
    if meta.get("protocol") != 2 or meta.get("component") not in ("platform", "web"):
        raise DeploymentError("Unsupported release protocol/component.")
    if not re.fullmatch(r"[0-9a-f]{40}", meta.get("commit", "")):
        raise DeploymentError("Invalid commit.")
    for field in ("contract_sha256", "archive_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", meta.get(field, "")):
            raise DeploymentError("Invalid release checksum.")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", meta.get("image_id", "")):
        raise DeploymentError("Invalid Docker image identity.")
    if type(meta.get("run_id")) is not int or meta["run_id"] <= 0 or type(meta.get("run_attempt")) is not int or meta["run_attempt"] <= 0:
        raise DeploymentError("Invalid workflow run identifier.")
    release_id = f"{meta['commit']}-{meta['run_id']}-{meta['run_attempt']}"
    if meta.get("release_id") != release_id:
        raise DeploymentError("Invalid release identifier.")
    expected = f"pdfmaster-{meta['component']}:{release_id}"
    if meta.get("image") != expected or meta.get("architecture") not in ("amd64", "arm64"):
        raise DeploymentError("Invalid image name/architecture.")
    if type(meta.get("run_id")) is not int or meta["run_id"] <= 0:
        raise DeploymentError("Invalid workflow run identifier.")
    return meta


def unpack(bundle, destination):
    # Each component carries only its own stack. No links, path traversal,
    # devices or duplicate names are accepted from the release archive.
    with tarfile.open(bundle, "r:gz") as archive:
        members = archive.getmembers()
        names = [x.name for x in members]
        allowed = {"release.json", "image.tar.gz", "stack/compose.yaml", "stack/nginx.conf"}
        if len(names) != len(set(names)) or set(names) - allowed or sum(x.size for x in members) > MAX_BUNDLE:
            raise DeploymentError("Invalid/oversized release archive.")
        if not {"release.json", "image.tar.gz"}.issubset(names) or any(not x.isfile() for x in members):
            raise DeploymentError("Release archive must contain regular files only.")
        for member in members:
            target = destination / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            os.chmod(target, 0o600)
    meta = validate_manifest(read_json(destination / "release.json"))
    if set(names) != {'release.json', 'image.tar.gz', 'stack/compose.yaml', 'stack/nginx.conf'}:
        raise DeploymentError('Each isolated release must carry its own complete stack configuration.')
    if digest(destination / "image.tar.gz") != meta["archive_sha256"]:
        raise DeploymentError("Image archive checksum mismatch.")
    return meta


@contextlib.contextmanager
def deployment_lock(root, timeout=600):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / "deploy.lock").open("a") as lock:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise DeploymentError("Another PDF Master deployment still holds the lock.")
                time.sleep(1)
        yield


class Deployer:
    def __init__(self, root, component, runner=command):
        if component not in ('platform', 'web'):
            raise DeploymentError('Unknown deployment component.')
        self.root = root.resolve()
        self.component = component
        self.project = 'pdfmaster-' + component
        self.run = runner

    def preflight(self):
        self.settings = environment(self.root, self.component)
        version = self.run(['docker', 'compose', 'version', '--short']).lstrip('v').split('.')
        if tuple(int(x) for x in version[:2]) < (2, 24):
            raise DeploymentError('Docker Compose 2.24 or newer is required.')
        self.architecture = self.run(['docker', 'info', '--format', '{{.Architecture}}'])
        self.architecture = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(self.architecture, self.architecture)
        marker = self.root / '.owner'
        owner = self.project + '-deploy-v2\n'
        if not marker.exists():
            label = 'label=com.docker.compose.project=' + self.project
            containers = self.run(['docker', 'ps', '-aq', '--filter', label])
            volumes = self.run(['docker', 'volume', 'ls', '-q', '--filter', label])
            if containers or volumes:
                raise DeploymentError('An unmanaged ' + self.project + ' project already exists; inspect it before adoption.')
            marker.write_text(owner)
        elif marker.read_text() != owner:
            raise DeploymentError('Unexpected deployment ownership marker.')
        return self.settings

    def compose(self, release, *args, output_stream=None):
        config = self.root / 'releases' / release['release_id'] / 'stack' / 'compose.yaml'
        env = {k: v for k, v in os.environ.items() if not k.startswith('COMPOSE_')}
        env.update(self.settings)
        env.update(PDFMASTER_IMAGE=release['image'], PDFMASTER_ENV_FILE=str(self.root / '.env'))
        compose = ['docker', 'compose', '--project-name', self.project,
                   '--env-file', str(self.root / '.env'), '-f', str(config)]
        override = self.root / 'compose.override.yaml'
        if override.exists():
            if override.is_symlink() or not override.is_file():
                raise DeploymentError('Invalid server-owned Compose override.')
            compose += ['-f', str(override)]
        return self.run(compose + list(args), env=env, output_stream=output_stream)

    def activate(self, release):
        self.compose(release, 'config', '--quiet')
        if self.component == 'platform':
            self.compose(release, 'up', '-d', '--wait', '--wait-timeout', '120', 'db', 'redis')
            directory = self.root / 'backups'
            directory.mkdir(exist_ok=True, mode=0o700)
            path = directory / f'before-{time.time_ns()}.dump'
            with path.open('xb') as stream:
                os.chmod(path, 0o600)
                self.compose(release, 'exec', '-T', 'db', 'pg_dump', '-U', 'pdfmaster',
                             '-d', 'pdfmaster', '-Fc', output_stream=stream)
            self.compose(release, 'run', '--rm', '--no-deps', 'init')
        self.start_services(release)

    def start_services(self, release):
        services = ['web'] if self.component == 'web' else ['api', 'worker', 'batches', 'cleanup']
        if self.component == 'platform' and self.settings.get('COMPOSE_PROFILES') == 'bot':
            services.append('bot')
        self.compose(release, 'up', '-d', '--wait', '--wait-timeout', '180', *services)
        if self.component == 'platform' and 'bot' not in services:
            if self.compose(release, '--profile', 'bot', 'ps', '-q', 'bot'):
                self.compose(release, '--profile', 'bot', 'stop', 'bot')
        # Recreate only this project's gateway after replacing its upstream.
        self.compose(release, 'up', '-d', '--no-deps', '--force-recreate', '--wait',
                     '--wait-timeout', '120', 'gateway')
        paths = ['/en/app'] if self.component == 'web' else ['/api/v1/health', '/ops/login', '/static/ops/main.css']
        for path in paths:
            self.compose(release, 'exec', '-T', 'gateway', 'wget', '-q', '-O', '/dev/null',
                         'http://127.0.0.1:8080' + path)

    def restore(self, release):
        if self.component == 'platform':
            self.compose(release, 'run', '--rm', '--no-deps', 'init',
                         'python', 'manage.py', 'collectstatic', '--noinput')
        self.start_services(release)

    def deploy(self, bundle):
        self.preflight()
        with tempfile.TemporaryDirectory(prefix='release-', dir=self.root) as temp:
            staging = Path(temp)
            meta = unpack(bundle, staging)
            if meta['component'] != self.component:
                raise DeploymentError('Release belongs to a different isolated project.')
            if meta['architecture'] != self.architecture:
                raise DeploymentError('Image/server architecture mismatch; set DEPLOY_PLATFORM.')
            state_path = self.root / 'state.json'
            state = read_json(state_path, {'active': None, 'previous': None, 'last_run': [0, 0]})
            if [meta['run_id'], meta['run_attempt']] < state['last_run']:
                return {'status': 'ignored_stale_release', 'component': self.component}
            old = state.get('active')
            if old and old['release_id'] == meta['release_id']:
                return {'status': 'already_deployed', 'component': self.component, 'commit': meta['commit']}
            destination = self.root / 'releases' / meta['release_id']
            existing = read_json(destination / 'release.json')
            if existing and existing['image_id'] != meta['image_id']:
                raise DeploymentError('This release identifier already has a different immutable image.')
            with (staging / 'image.tar.gz').open('rb') as stream:
                self.run(['docker', 'load'], input_stream=stream)
            identity = self.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', meta['image']])
            if identity != meta['image_id']:
                # Different Docker stores can use different .Id representations.
                # Re-export only this loaded image and verify its config blob;
                # never relax verification to a mutable tag or skip the check.
                with tempfile.TemporaryFile(dir=self.root) as exported:
                    self.run(['docker', 'image', 'save', meta['image']], output_stream=exported)
                    exported.seek(0)
                    identity = image_config_id(exported, meta['image'])
            if identity != meta['image_id']:
                raise DeploymentError('Loaded image identity mismatch.')
            if not existing:
                destination.parent.mkdir(parents=True, exist_ok=True)
                (staging / 'image.tar.gz').unlink()
                shutil.move(str(staging), destination)
                os.chmod(destination / 'stack' / 'nginx.conf', 0o644)
            state['pending'] = meta
            state['last_run'] = [meta['run_id'], meta['run_attempt']]
            write_json(state_path, state)
            try:
                self.activate(meta)
            except Exception:
                if old:
                    try:
                        self.restore(old)
                    except Exception:
                        raise DeploymentError('Deployment and image rollback failed. Inspect this project logs and backups.') from None
                    state['pending'] = None
                    write_json(state_path, state)
                raise DeploymentError('Release failed health/migration checks; previous image restored when available. Other projects were not changed. Database migrations were not reversed.') from None
            state.update(previous=old, active=meta, pending=None)
            write_json(state_path, state)
            return {'status': 'deployed', 'component': self.component, 'project': self.project,
                    'commit': meta['commit'], 'url': 'https://' + self.settings['PUBLIC_DOMAIN']}

    def rollback(self):
        self.preflight()
        path = self.root / 'state.json'
        state = read_json(path, {})
        previous = state.get('previous')
        if not previous:
            raise DeploymentError('No previous healthy release is recorded.')
        self.restore(previous)
        state['active'], state['previous'] = previous, state['active']
        state['pending'] = None
        write_json(path, state)
        return {'status': 'rolled_back', 'component': self.component, 'database': 'unchanged'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('deploy', 'rollback'))
    parser.add_argument('--component', required=True, choices=('platform', 'web'))
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--root', type=Path)
    args = parser.parse_args()
    root = args.root or Path.home() / 'pdf-master' / args.component
    os.umask(0o077)
    try:
        with deployment_lock(root):
            deployer = Deployer(root, args.component)
            if args.action == 'deploy':
                if args.bundle is None:
                    raise DeploymentError('--bundle is required.')
                result = deployer.deploy(args.bundle)
            else:
                result = deployer.rollback()
        print(json.dumps(result))
    except (DeploymentError, OSError, ValueError, tarfile.TarError, subprocess.TimeoutExpired) as exc:
        print(str(exc) if isinstance(exc, DeploymentError) else 'Deployment failed; inspect the server locally.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
