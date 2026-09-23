"""Apply the explicitly approved two-site addition; never restart a container."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

IMPORT = 'import /config/pdfmaster-sites/*.caddy'
ORIGINAL_SHA256 = '9b0f8129600c282326193228f3e30296e5c735a224d219e65f04051e2f2c5d82'
SITES = '''pdfmaster.orderdesk.live {
    reverse_proxy pdfmaster-web-gateway:8080
}

pdfmaster-admin.orderdesk.live {
    reverse_proxy pdfmaster-platform-gateway:8080
}
'''
DOMAINS = {'pdfmaster.orderdesk.live', 'pdfmaster-admin.orderdesk.live'}


def run(args, data=None):
    result = subprocess.run(args, input=data, text=True, capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError('Proxy operation failed: ' + ' '.join(args[:3]))
    return result.stdout


def inventory():
    ids = run(['docker', 'ps', '-aq']).split()
    return json.loads(run(['docker', 'inspect', *ids])) if ids else []


def preserved(containers):
    return {c['Id']: {'name': c['Name'], 'started': c['State']['StartedAt'],
                     'status': c['State']['Status']}
            for c in containers
            if not c['Config']['Labels'].get('com.docker.compose.project', '').startswith('pdfmaster-')}


def ensure_file(path, content, mode=0o600):
    if path.is_symlink():
        raise RuntimeError('Refusing symlink: ' + path.name)
    if path.exists():
        if path.read_text() != content:
            raise RuntimeError('Existing configuration differs: ' + path.name)
        return
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def without_new_routes(config):
    config = copy.deepcopy(config)
    for server in config['apps']['http']['servers'].values():
        server['routes'] = [r for r in server.get('routes', [])
                            if not any(set(m.get('host', [])) & DOMAINS for m in r.get('match', []))]
    return config


def changed_paths(before, after, path='config'):
    """Report structure only; never expose ACME email or other config values."""
    if type(before) is not type(after):
        return [path + ': type changed']
    if isinstance(before, dict):
        found = []
        for key in sorted(before.keys() | after.keys()):
            if key not in before or key not in after:
                found.append(path + '.' + key + ': added/removed')
            else:
                found.extend(changed_paths(before[key], after[key], path + '.' + key))
        return found
    if isinstance(before, list):
        if len(before) != len(after):
            return [path + f': length {len(before)} -> {len(after)}']
        return [change for index, (a, b) in enumerate(zip(before, after))
                for change in changed_paths(a, b, path + f'[{index}]')]
    return [path + ': value changed'] if before != after else []


def main():
    mode = sys.argv[1]
    if mode not in {'prepare', 'publish'}:
        raise RuntimeError('Unsupported mode')
    os.umask(0o077)
    containers = inventory()
    baseline = preserved(containers)
    proxies = [c for c in containers if c['Name'] == '/orderdesk-caddy-1'
               and c['Config']['Labels'].get('com.docker.compose.project') == 'orderdesk'
               and c['State']['Status'] == 'running']
    if len(proxies) != 1:
        raise RuntimeError('Expected existing proxy was not found')
    proxy = proxies[0]
    mounts = [m for m in proxy['Mounts'] if m['Destination'] == '/etc/caddy/Caddyfile']
    if len(mounts) != 1 or mounts[0]['Type'] != 'bind':
        raise RuntimeError('Unexpected Caddyfile mount')
    config_path = Path(mounts[0]['Source'])
    if config_path.is_symlink() or not config_path.is_file() or not str(config_path).startswith('/opt/orderdesk/releases/'):
        raise RuntimeError('Unexpected Caddyfile source')
    source = config_path.read_text()
    original = source.replace('\n' + IMPORT + '\n', '')
    if hashlib.sha256(original.encode()).hexdigest() != ORIGINAL_SHA256:
        raise RuntimeError('Existing Caddyfile changed since review; inspect before proceeding')
    proposed = original + '\n' + IMPORT + '\n'
    docker_exec = ['docker', 'exec', '-i', proxy['Id']]

    def adapt(text):
        return json.loads(run([*docker_exec, 'caddy', 'adapt', '--config', '-', '--adapter', 'caddyfile'], text))

    old_config = adapt(original)
    new_config = adapt(original + '\n' + SITES)
    if without_new_routes(new_config) != old_config:
        print('CONFIG_STRUCTURE_DIFFERENCE', json.dumps(changed_paths(old_config, without_new_routes(new_config))), flush=True)
        raise RuntimeError('Proposed routing modifies an existing site')
    run([*docker_exec, 'caddy', 'validate', '--config', '-', '--adapter', 'caddyfile'], original + '\n' + SITES)
    root = Path.home() / 'pdf-master'
    directory = root / 'proxy'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    ensure_file(directory / 'original.Caddyfile', original)
    ensure_file(directory / 'sites.caddy', SITES)
    ensure_file(directory / 'baseline.json', json.dumps(baseline, indent=2) + '\n')
    for component in ('platform', 'web'):
        own_root = root / component
        own_root.mkdir(exist_ok=True, mode=0o700)
        override = f'''services:
  gateway:
    networks:
      default:
      proxy:
        aliases: [pdfmaster-{component}-gateway]
networks:
  proxy:
    external: true
    name: orderdesk_default
'''
        ensure_file(own_root / 'compose.override.yaml', override)
    if source != proposed:
        # Preserve the inode: Docker has this exact file bind-mounted read-only.
        with config_path.open('r+') as stream:
            if stream.read() != source:
                raise RuntimeError('Caddyfile changed during preparation')
            stream.seek(0)
            stream.write(proposed)
            stream.truncate()
            stream.flush()
            os.fsync(stream.fileno())
    if mode == 'prepare':
        if baseline != preserved(inventory()):
            raise RuntimeError('An existing container changed during preparation')
        print('PROXY_PREPARED: configuration validated; existing route unchanged; no reload or container restart')
        return

    # Activate only after both upstreams answer through the ingress network.
    for alias, route in [('pdfmaster-web-gateway', '/en/app'), ('pdfmaster-platform-gateway', '/ops/login')]:
        run([*docker_exec, 'wget', '-q', '-O', '/dev/null', 'http://' + alias + ':8080' + route])
    existing = subprocess.run([*docker_exec, 'cat', '/config/pdfmaster-sites/sites.caddy'],
                              text=True, capture_output=True, timeout=30)
    if existing.returncode == 0 and existing.stdout != SITES:
        raise RuntimeError('Existing PDF Master routes differ; refusing overwrite')
    run([*docker_exec, 'sh', '-c', 'umask 077; mkdir -p /config/pdfmaster-sites; cat > /config/pdfmaster-sites/sites.caddy'], SITES)
    adapted = json.loads(run([*docker_exec, 'caddy', 'adapt', '--config', '/etc/caddy/Caddyfile']))
    if adapted != new_config:
        raise RuntimeError('On-disk Caddy configuration differs from validated proposal')
    run([*docker_exec, 'caddy', 'validate', '--config', '/etc/caddy/Caddyfile'])
    try:
        run([*docker_exec, 'caddy', 'reload', '--config', '/etc/caddy/Caddyfile'])
    except RuntimeError:
        run([*docker_exec, 'caddy', 'reload', '--config', '-', '--adapter', 'caddyfile'], original)
        raise
    if baseline != preserved(inventory()):
        raise RuntimeError('An existing container changed during proxy publication')
    print('PROXY_PUBLISHED: two PDF Master hosts added; existing routes and container IDs/start times unchanged')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
