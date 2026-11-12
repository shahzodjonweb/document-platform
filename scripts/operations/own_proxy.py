"""DocMaster's own HTTPS proxy, and the removal of OrderDesk from the server.

Until now DocMaster's hosts were served by OrderDesk's Caddy (orderdesk-caddy-1),
whose network the two DocMaster gateways joined. OrderDesk is a retired project
(owner's decision, 2026-11-13: delete it, no backup), so DocMaster gets its own:

check             reads only: what OrderDesk has on the server, and whether the
                  takeover can run (gateways answer, our Caddyfile validates).
takeover          creates the docmaster-proxy network, joins both gateways to it,
                  copies OrderDesk's Caddy certificate store (no new issuance),
                  then stops orderdesk-caddy-1 and starts docmaster-proxy on 80/443.
                  If HTTPS does not answer within 90 s it stops ours and starts
                  OrderDesk's Caddy again.
remove-orderdesk  after a takeover: deletes every OrderDesk container, volume,
                  network and image, /opt/orderdesk and its crontab lines. Final.
publish           later Caddyfile/compose changes to our proxy, validated first.

Runs on the server through scripts/operations/remote.py (python3 - <mode>).
The Caddyfile and compose file are also in infra/production/proxy/ (tests keep
them identical to the text here).
"""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time

ROOT = Path.home() / 'docmaster'
PROXY_DIR = ROOT / 'proxy'
COMPONENTS = ('platform', 'web')
NETWORK = 'docmaster-proxy'
PROJECT = 'docmaster-proxy'
CONTAINER = 'docmaster-proxy-caddy-1'
OLD_PROJECT = 'orderdesk'
OLD_CADDY = '/orderdesk-caddy-1'
OLD_NETWORK = 'orderdesk_default'
OLD_DIR = Path('/opt/orderdesk')
# Repositories only OrderDesk used; their every tag goes with it.
OLD_REPOSITORIES = ('ghcr.io/shahzodjonweb/obunachi-qoshish-bot', 'chrislusf/seaweedfs')
IMAGE = 'caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d'

CADDYFILE = '''# DocMaster's own HTTPS proxy (compose project docmaster-proxy). Published to
# ~/docmaster/proxy/Caddyfile by the proxy-publish server operation
# (scripts/operations/own_proxy.py, which carries this text and is tested to match it).
docmaster.live {
    reverse_proxy docmaster-web-gateway:8080
}

www.docmaster.live {
    redir https://docmaster.live{uri} permanent
}

api.docmaster.live {
    reverse_proxy docmaster-platform-gateway:8080
}
'''

COMPOSE = '''# DocMaster's own HTTPS proxy: the one container on ports 80 and 443. It reaches the
# component gateways on the docmaster-proxy network, which the proxy-takeover operation
# creates outside any compose project, so neither the proxy nor a deploy removes it.
# Published to ~/docmaster/proxy/compose.yaml by scripts/operations/own_proxy.py.
name: docmaster-proxy
services:
  caddy:
    image: caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy-data:/data
      - caddy-config:/config
    networks: [proxy]
    mem_limit: 256m
    cpus: 0.5
    logging:
      driver: json-file
      options: {max-size: 10m, max-file: "3"}
networks:
  proxy:
    external: true
    name: docmaster-proxy
volumes:
  caddy-data:
  caddy-config:
'''

# (host, path, expected status) once our Caddy serves; www is a permanent redirect.
HTTPS_CHECKS = (('docmaster.live', '/en', 200), ('www.docmaster.live', '/', 301),
                ('api.docmaster.live', '/api/v1/health', 200))
# Through the docmaster-proxy network, as Caddy reaches them (Django checks the Host).
GATEWAY_CHECKS = (('docmaster-web-gateway', 'docmaster.live', '/en'),
                  ('docmaster-platform-gateway', 'api.docmaster.live', '/api/v1/health'))
# Files of the shared-Caddy setup (proxy_setup.py) left in ~/docmaster/proxy.
SHARED_SETUP_LEFTOVERS = ('original.Caddyfile', 'sites.caddy')


class Stop(Exception):
    pass


def say(*parts):
    print(*parts, flush=True)


def run(args, input=None, timeout=300, check=True):
    result = subprocess.run(args, input=input, text=True, capture_output=True, timeout=timeout)
    if check and result.returncode:
        raise Stop(f'command failed: {" ".join(args[:4])} (exit {result.returncode}): {result.stderr.strip()[-300:]}')
    return result.stdout.strip()


# ---------------------------------------------------------------- pure parts (unit-tested)

def gateway_override(component):
    """The server-owned compose.override.yaml: the gateway joins DocMaster's proxy network."""
    return f'''services:
  gateway:
    networks:
      default:
      proxy:
        aliases: [docmaster-{component}-gateway]
networks:
  proxy:
    external: true
    name: {NETWORK}
'''


def shared_override(component):
    """The override written for OrderDesk's shared Caddy (the only one takeover replaces)."""
    return f'''services:
  gateway:
    networks:
      default:
      proxy:
        aliases: [docmaster-{component}-gateway, pdfmaster-{component}-gateway]
networks:
  proxy:
    external: true
    name: {OLD_NETWORK}
'''


def status_line(data):
    """The status code of a raw HTTP response's first line."""
    first = data.split(b'\r\n', 1)[0].split()
    if len(first) < 2 or not first[0].startswith(b'HTTP/') or not first[1].isdigit():
        raise Stop('not an HTTP response')
    return int(first[1])


def old_images(rows, container_images):
    """`docker images` rows "ID repository:tag" that go with OrderDesk: its containers' images
    and every tag of a repository only it used. Returns what to pass to `docker image rm`."""
    picked = []
    for row in rows:
        image_id, _, reference = row.partition(' ')
        repository = reference.rsplit(':', 1)[0]
        if repository in OLD_REPOSITORIES or any(full.startswith('sha256:' + image_id) for full in container_images):
            picked.append(image_id if reference.endswith(':<none>') or reference.startswith('<none>') else reference)
    return picked


def without_old_lines(crontab):
    """The crontab without lines that name OrderDesk; (new text, removed count)."""
    lines = crontab.splitlines()
    kept = [line for line in lines if 'orderdesk' not in line.lower()]
    return ('\n'.join(kept) + '\n') if kept else '', len(lines) - len(kept)


# ---------------------------------------------------------------- server facts

def inspect(ids):
    return json.loads(run(['docker', 'inspect', *ids])) if ids else []


def project_containers(project):
    return inspect(run(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + project]).split())


def gateway(component):
    found = run(['docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=docmaster-' + component,
                 '--filter', 'label=com.docker.compose.service=gateway']).split()
    if len(found) != 1:
        raise Stop(f'expected one running docmaster-{component} gateway, found {len(found)}')
    return found[0]


def old_caddy():
    found = [c for c in project_containers(OLD_PROJECT) if c['Name'] == OLD_CADDY]
    return found[0] if found else None


def https_status(host, path, port=443, timeout=10):
    """GET over TLS to this host's own port, with SNI and full certificate verification."""
    context = ssl.create_default_context()
    with socket.create_connection(('127.0.0.1', port), timeout=timeout) as raw:
        with context.wrap_socket(raw, server_hostname=host) as tls:
            tls.sendall(f'GET {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: docmaster-proxy-check\r\n'
                        'Connection: close\r\n\r\n'.encode())
            return status_line(tls.recv(256))


def https_ready(wait=90):
    deadline = time.monotonic() + wait
    last = {}
    while True:
        for host, path, expected in HTTPS_CHECKS:
            try:
                last[host] = https_status(host, path)
            except (OSError, Stop) as error:
                last[host] = type(error).__name__
        if all(last[host] == expected for host, _, expected in HTTPS_CHECKS):
            return last
        if time.monotonic() > deadline:
            raise Stop('HTTPS checks failed: ' + json.dumps(last))
        time.sleep(3)


def gateways_answer(network):
    for alias, host, path in GATEWAY_CHECKS:
        run(['docker', 'run', '--rm', '--network', network, '--entrypoint', 'wget', IMAGE,
             '-q', '-O', '/dev/null', '--header', 'Host: ' + host, f'http://{alias}:8080{path}'], timeout=120)


def validate(caddyfile):
    with tempfile.TemporaryDirectory(dir=Path.home()) as folder:
        path = Path(folder) / 'Caddyfile'
        path.write_text(caddyfile)
        os.chmod(folder, 0o755); os.chmod(path, 0o644)
        run(['docker', 'run', '--rm', '-v', f'{path}:/etc/caddy/Caddyfile:ro', IMAGE,
             'caddy', 'validate', '--config', '/etc/caddy/Caddyfile', '--adapter', 'caddyfile'], timeout=120)


@contextlib.contextmanager
def deploy_locks():
    """Both components' deploy locks, so no release recreates a gateway mid-change."""
    handles = []
    try:
        for component in COMPONENTS:
            handle = (ROOT / component / 'deploy.lock').open('a')
            deadline = time.monotonic() + 300
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() > deadline:
                        raise Stop(f'a {component} deployment holds the lock; try again when it ends')
                    time.sleep(2)
            handles.append(handle)
        yield
    finally:
        for handle in handles:
            handle.close()


def write_in_place(path, content):
    """Write keeping the inode: the Caddyfile is bind-mounted into the running container."""
    if path.is_symlink():
        raise Stop('refusing symlink ' + path.name)
    if not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(content)
        return True
    if path.read_text() == content:
        return False
    with path.open('r+') as stream:
        stream.write(content); stream.truncate(); stream.flush(); os.fsync(stream.fileno())
    return True


def compose(*args):
    return run(['docker', 'compose', '--project-name', PROJECT, '-f', str(PROXY_DIR / 'compose.yaml'), *args], timeout=600)


def volume_name(volume):
    return f'{PROJECT}_{volume}'


def volume_empty(name):
    return run(['docker', 'run', '--rm', '-v', name + ':/v:ro', '--entrypoint', 'sh', IMAGE, '-c',
                'ls -A /v | head -1']) == ''


# ---------------------------------------------------------------- modes

def check():
    problems = []
    if not ROOT.is_dir():
        problems.append('~/docmaster is missing')
    containers = project_containers(OLD_PROJECT)
    for c in containers:
        say('ORDERDESK_CONTAINER', json.dumps({'name': c['Name'], 'image': c['Config']['Image'],
                                               'status': c['State']['Status']}))
    volumes = run(['docker', 'volume', 'ls', '-q', '--filter', 'label=com.docker.compose.project=' + OLD_PROJECT]).split()
    say('ORDERDESK_VOLUMES', json.dumps(volumes))
    networks = run(['docker', 'network', 'ls', '--format', '{{.Name}}', '--filter',
                    'label=com.docker.compose.project=' + OLD_PROJECT]).split()
    say('ORDERDESK_NETWORKS', json.dumps(networks))
    rows = run(['docker', 'images', '--no-trunc', '--format', '{{.ID}} {{.Repository}}:{{.Tag}}']).splitlines()
    rows = [row.removeprefix('sha256:') for row in rows]
    say('ORDERDESK_IMAGES', json.dumps(old_images(rows, [c['Image'] for c in containers])))
    if OLD_DIR.exists():
        size = run(['du', '-sh', str(OLD_DIR)], check=False).split('\t')[0]
        mine = OLD_DIR.stat().st_uid == os.getuid()
        say('ORDERDESK_DIR', str(OLD_DIR), size or '?', '| owned by this account:', mine)
    cron = run(['crontab', '-l'], check=False)
    say('ORDERDESK_CRONTAB_LINES', without_old_lines(cron)[1])
    caddy = old_caddy()
    if caddy:
        data = [m for m in caddy['Mounts'] if m['Destination'] == '/data']
        say('ORDERDESK_CADDY', caddy['State']['Status'], '| /data:', data[0].get('Name') if data else None)
        if not data or data[0]['Type'] != 'volume':
            problems.append('orderdesk-caddy-1 has no /data volume to copy certificates from')
    else:
        say('ORDERDESK_CADDY absent')
    ours = inspect(run(['docker', 'ps', '-aq', '--filter', 'name=^' + CONTAINER + '$']).split())
    say('DOCMASTER_PROXY', ours[0]['State']['Status'] if ours else 'absent')
    run(['docker', 'pull', '-q', IMAGE], timeout=600)
    validate(CADDYFILE)
    say('CADDYFILE valid')
    network = NETWORK if run(['docker', 'network', 'ls', '-q', '--filter', 'name=^' + NETWORK + '$']) else OLD_NETWORK
    try:
        gateways_answer(network)
        say('GATEWAYS answer on', network)
    except Stop as error:
        problems.append(str(error))
    for component in COMPONENTS:
        override = (ROOT / component / 'compose.override.yaml').read_text()
        state = ('ours' if override == gateway_override(component) else
                 'shared' if override == shared_override(component) else 'unknown')
        say('OVERRIDE', component, state)
        if state == 'unknown':
            problems.append(f'{component} compose.override.yaml is not a reviewed version')
    if problems:
        say('PROXY_CHECK_PROBLEMS', json.dumps(problems))
        return 1
    say('PROXY_CHECK_READY')
    return 0


def takeover():
    caddy = old_caddy()
    if not caddy or caddy['State']['Status'] != 'running':
        raise Stop('orderdesk-caddy-1 is not running; nothing to take over')
    data = [m for m in caddy['Mounts'] if m['Destination'] == '/data' and m['Type'] == 'volume']
    if len(data) != 1:
        raise Stop('orderdesk-caddy-1 has no /data volume')
    run(['docker', 'pull', '-q', IMAGE], timeout=600)
    validate(CADDYFILE)
    with deploy_locks():
        # 1. Our network, and both gateways on it under their names (a live connect, no restart).
        if not run(['docker', 'network', 'ls', '-q', '--filter', 'name=^' + NETWORK + '$']):
            run(['docker', 'network', 'create', '--label', 'docmaster.proxy=network', NETWORK])
        for component in COMPONENTS:
            container = gateway(component)
            attached = json.loads(run(['docker', 'inspect', '--format', '{{json .NetworkSettings.Networks}}', container]))
            if NETWORK not in attached:
                run(['docker', 'network', 'connect', '--alias', f'docmaster-{component}-gateway', NETWORK, container])
            override = ROOT / component / 'compose.override.yaml'
            if override.read_text() not in (shared_override(component), gateway_override(component)):
                raise Stop(f'{component} compose.override.yaml is not a reviewed version')
            override.write_text(gateway_override(component))
        gateways_answer(NETWORK)
        say('STEP 1 gateways on', NETWORK, 'and both overrides name it')
        # 2. Our files and the certificate store (copied once, into empty volumes).
        PROXY_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(PROXY_DIR, 0o755)
        write_in_place(PROXY_DIR / 'Caddyfile', CADDYFILE)
        write_in_place(PROXY_DIR / 'compose.yaml', COMPOSE)
        compose('config', '--quiet')
        version = run(['docker', 'compose', 'version', '--short']).lstrip('v')
        for volume in ('caddy-data', 'caddy-config'):
            name = volume_name(volume)
            if not run(['docker', 'volume', 'ls', '-q', '--filter', 'name=^' + name + '$']):
                run(['docker', 'volume', 'create', '--label', 'com.docker.compose.project=' + PROJECT,
                     '--label', 'com.docker.compose.volume=' + volume, '--label', 'com.docker.compose.version=' + version, name])
        if volume_empty(volume_name('caddy-data')):
            run(['docker', 'run', '--rm', '--entrypoint', 'sh', '-v', data[0]['Name'] + ':/from:ro',
                 '-v', volume_name('caddy-data') + ':/to', IMAGE, '-c', 'cp -a /from/. /to/'], timeout=600)
            say('STEP 2 certificate store copied from', data[0]['Name'])
        else:
            say('STEP 2 certificate store already present')
        # 3. The switch: OrderDesk's Caddy off, ours on, then HTTPS from this host.
        run(['docker', 'stop', '--time', '20', caddy['Id']])
        try:
            compose('up', '-d', '--wait', '--wait-timeout', '120')
            results = https_ready()
        except (Stop, subprocess.TimeoutExpired) as error:
            say('STEP 3 failed, switching back:', error)
            compose('down')
            run(['docker', 'start', caddy['Id']])
            raise Stop('takeover rolled back; orderdesk-caddy-1 serves again')
        # A container OrderDesk's restart policy could bring back must not race us for 80/443.
        run(['docker', 'update', '--restart', 'no', caddy['Id']])
        say('STEP 3 docmaster-proxy serves:', json.dumps(results))
    say('PROXY_TAKEN_OVER: docmaster-proxy holds 80/443; orderdesk-caddy-1 is stopped')
    return 0


def remove_orderdesk():
    ours = inspect(run(['docker', 'ps', '-q', '--filter', 'name=^' + CONTAINER + '$']).split())
    if not ours:
        raise Stop('docmaster-proxy is not running; run proxy-takeover first')
    caddy = old_caddy()
    if caddy and caddy['State']['Status'] == 'running':
        raise Stop('orderdesk-caddy-1 is running; run proxy-takeover first')
    https_ready(wait=30)
    free_before = shutil.disk_usage('/').free
    with deploy_locks():
        for component in COMPONENTS:
            override = (ROOT / component / 'compose.override.yaml').read_text()
            if override != gateway_override(component):
                raise Stop(f'{component} override still names the shared network')
            container = gateway(component)
            attached = json.loads(run(['docker', 'inspect', '--format', '{{json .NetworkSettings.Networks}}', container]))
            if OLD_NETWORK in attached:
                run(['docker', 'network', 'disconnect', OLD_NETWORK, container])
        containers = project_containers(OLD_PROJECT)
        rows = [row.removeprefix('sha256:') for row in
                run(['docker', 'images', '--no-trunc', '--format', '{{.ID}} {{.Repository}}:{{.Tag}}']).splitlines()]
        images = old_images(rows, [c['Image'] for c in containers])
        if containers:
            run(['docker', 'rm', '-f', *[c['Id'] for c in containers]], timeout=600)
        volumes = run(['docker', 'volume', 'ls', '-q', '--filter', 'label=com.docker.compose.project=' + OLD_PROJECT]).split()
        for volume in volumes:
            if run(['docker', 'ps', '-aq', '--filter', 'volume=' + volume]):
                raise Stop(f'{volume} is still used by a container')
            run(['docker', 'volume', 'rm', volume])
        networks = run(['docker', 'network', 'ls', '-q', '--filter', 'label=com.docker.compose.project=' + OLD_PROJECT]).split()
        for network in networks:
            run(['docker', 'network', 'rm', network])
        for image in images:
            # A tag whose image another tag or a running container still holds is only untagged.
            run(['docker', 'image', 'rm', image], check=False)
        removed = [image for image in images if not run(['docker', 'images', '-q', image], check=False)]
        say('REMOVED', len(containers), 'containers,', len(volumes), 'volumes,', len(networks), 'networks,',
            len(removed), 'of', len(images), 'images')
    cron = run(['crontab', '-l'], check=False)
    kept, dropped = without_old_lines(cron)
    if dropped:
        run(['crontab', '-'], input=kept)
    say('CRONTAB', dropped, 'OrderDesk line(s) removed')
    if OLD_DIR.exists() and not OLD_DIR.is_symlink():
        failed = []
        shutil.rmtree(OLD_DIR, onerror=lambda function, path, info: failed.append(path))
        say('ORDERDESK_DIR', 'removed' if not OLD_DIR.exists() else f'partly removed; {len(failed)} path(s) need root')
    for name in SHARED_SETUP_LEFTOVERS:
        (PROXY_DIR / name).unlink(missing_ok=True)
    for path in PROXY_DIR.glob('baseline-*.json'):
        path.unlink()
    say('HTTPS', json.dumps(https_ready(wait=30)))
    freed = (shutil.disk_usage('/').free - free_before) / 1024 ** 3
    say(f'ORDERDESK_REMOVED: {freed:.1f} GiB freed; DocMaster is the only project on this server')
    return 0


def publish():
    if not inspect(run(['docker', 'ps', '-q', '--filter', 'name=^' + CONTAINER + '$']).split()):
        raise Stop('docmaster-proxy is not running; run proxy-takeover first')
    validate(CADDYFILE)
    caddyfile = write_in_place(PROXY_DIR / 'Caddyfile', CADDYFILE)
    composefile = write_in_place(PROXY_DIR / 'compose.yaml', COMPOSE)
    if composefile:
        compose('up', '-d', '--wait', '--wait-timeout', '120')
    elif caddyfile:
        run(['docker', 'exec', CONTAINER, 'caddy', 'reload', '--config', '/etc/caddy/Caddyfile'])
    say('HTTPS', json.dumps(https_ready(wait=60)))
    say('PROXY_PUBLISHED:', 'compose changed' if composefile else 'Caddyfile reloaded' if caddyfile else 'already current')
    return 0


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    modes = {'check': check, 'takeover': takeover, 'remove-orderdesk': remove_orderdesk, 'publish': publish}
    if mode not in modes:
        print('usage: own_proxy.py ' + '|'.join(modes), file=sys.stderr)
        return 2
    os.umask(0o077)
    try:
        return modes[mode]()
    except (Stop, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        say(f'PROXY_{mode.upper().replace("-", "_")}_FAILED: {error}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
