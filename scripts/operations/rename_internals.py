"""Rename the server's PDF Master internals to DocMaster: check, migrate, rollback, cleanup.

Done on 2026-11-11; only cleanup is offered as a server operation now.

Runs on the server through scripts/operations/remote.py (python3 - <mode>), as
the deploy account, for both components at once:

  ~/pdf-master/{platform,web}      ->  ~/docmaster/{platform,web}   (.env, state, releases, override)
  Compose projects pdfmaster-*     ->  docmaster-*                  (the same active release, restarted)
  volumes pdfmaster-platform_*     ->  docmaster-platform_*         (copied; the old ones are never written)
  database/role pdfmaster          ->  docmaster                    (renamed inside the copy only)
  images pdfmaster-*:<release>     ->  docmaster-*:<release>        (tagged; old tags kept)
  PDFMASTER_HTTP_PORT, PUBLIC_DOMAIN in each .env                    (renamed / the new hosts)

The storage bucket keeps its name (owner's decision). The shared OrderDesk
Caddy is untouched here: the gateways answer to both their old and new
network aliases, so routing keeps working until proxy-publish moves to the new
names.

check     reads only and reports whether migrate can run.
migrate   stops at the first failed step; run rollback after a failure.
rollback  undoes whatever migrate got to: stops the new projects, moves the
          folders and files back, and starts the old containers on their
          untouched volumes. Only safe before the first deploy after migrate.
cleanup   once the migration is accepted: removes the stopped pdfmaster-*
          projects (containers, volumes, networks), the old image tags, and the
          files migrate kept for rollback. Rollback is impossible afterwards.
"""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

HOME = Path.home()
OLD_ROOT, NEW_ROOT = HOME / 'pdf-master', HOME / 'docmaster'
COMPONENTS = ('platform', 'web')
VOLUMES = ('database', 'private-files', 'static-files', 'redis')
DOMAINS = {'platform': ('pdfmaster-admin.orderdesk.live', 'api.docmaster.live'),
           'web': ('pdfmaster.orderdesk.live', 'docmaster.live')}
PROGRESS = 'rename-progress.json'
BACKUP = '.pre-rename'
COPY_LABEL = 'docmaster.rename=copy'
# Exactly the changes the repositories' own compose files make (document-platform
# and document-web infra/production/compose.yaml), so a restarted release and the
# next deployed one run the same configuration.
STACK_RULES = (
    ('name: pdfmaster-platform', 'name: docmaster-platform'),
    ('name: pdfmaster-web', 'name: docmaster-web'),
    ('${PDFMASTER_IMAGE:', '${DOCMASTER_IMAGE:'),
    ('${PDFMASTER_ENV_FILE:', '${DOCMASTER_ENV_FILE:'),
    ('${PDFMASTER_HTTP_PORT:', '${DOCMASTER_HTTP_PORT:'),
    ('postgresql://pdfmaster:', 'postgresql://docmaster:'),
    ('@db:5432/pdfmaster', '@db:5432/docmaster'),
    ('POSTGRES_USER: pdfmaster', 'POSTGRES_USER: docmaster'),
    ('POSTGRES_DB: pdfmaster', 'POSTGRES_DB: docmaster'),
    ('pg_isready -U pdfmaster -d pdfmaster', 'pg_isready -U docmaster -d docmaster'),
)
TABLES = ('core_account', 'core_job', 'core_fileasset')


class Stop(Exception):
    pass


def say(*parts):
    print(*parts, flush=True)


def run(args, input=None, timeout=900, check=True, env=None):
    result = subprocess.run(args, input=input, text=True, capture_output=True, timeout=timeout, env=env)
    if check and result.returncode:
        label = ' '.join(args[:4])
        raise Stop(f'command failed: {label} (exit {result.returncode}): {result.stderr.strip()[-400:]}')
    return result.stdout.strip()


# ---------------------------------------------------------------- pure rewrites (unit-tested)

def rewrite_stack(text):
    """A release's compose file under the new names; refuses anything it cannot fully rename."""
    for old, new in STACK_RULES:
        text = text.replace(old, new)
    leftovers = [line for line in text.splitlines()
                 if re.search(r'pdfmaster|PDFMASTER', line) and not line.lstrip().startswith('#')]
    if leftovers:
        raise Stop('stack file still names pdfmaster: ' + '; '.join(x.strip() for x in leftovers[:3]))
    return text


def rewrite_env(text, component):
    """The .env with the port variable renamed and the new public host; nothing else changes."""
    old_domain, new_domain = DOMAINS[component]
    out, seen = [], set()
    for line in text.splitlines():
        key = line.split('=', 1)[0] if '=' in line and not line.lstrip().startswith('#') else None
        if key == 'PDFMASTER_HTTP_PORT':
            line = 'DOCMASTER_HTTP_PORT=' + line.split('=', 1)[1]
        elif key == 'PUBLIC_DOMAIN':
            value = line.split('=', 1)[1]
            if value not in (old_domain, new_domain):
                raise Stop(f'{component} .env has an unexpected PUBLIC_DOMAIN')
            line = 'PUBLIC_DOMAIN=' + new_domain
        if key:
            seen.add(line.split('=', 1)[0])
        out.append(line)
    if 'DOCMASTER_HTTP_PORT' not in seen or 'PUBLIC_DOMAIN' not in seen:
        raise Stop(f'{component} .env lacks the port or PUBLIC_DOMAIN')
    return '\n'.join(out) + '\n'


def rewrite_state(state, component):
    """Release state with every image under its new name; returns (state, [(old, new) tags])."""
    tags = []
    for key in ('active', 'previous', 'pending'):
        release = state.get(key)
        if isinstance(release, dict) and isinstance(release.get('image'), str):
            old = release['image']
            new = re.sub(r'^pdfmaster-' + component + ':', 'docmaster-' + component + ':', old)
            if new != old:
                tags.append((old, new))
                release['image'] = new
    return state, tags


def rewrite_override(text, component):
    """The gateway answers to its new alias and keeps the old one until proxy-publish moves."""
    old, new = f'pdfmaster-{component}-gateway', f'docmaster-{component}-gateway'
    if new in text:
        return text
    if f'aliases: [{old}]' not in text:
        raise Stop(f'{component} compose.override.yaml has an unexpected alias line')
    return text.replace(f'aliases: [{old}]', f'aliases: [{new}, {old}]')


# ---------------------------------------------------------------- server facts

def containers(project, running_only=False):
    args = ['docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=' + project]
    return run(args if running_only else args[:2] + ['-a'] + args[2:]).split()


def service_container(project, service):
    found = run(['docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=' + project,
                 '--filter', 'label=com.docker.compose.service=' + service]).split()
    if len(found) != 1:
        raise Stop(f'expected one running {service} in {project}, found {len(found)}')
    return found[0]


def volume_exists(name):
    return bool(run(['docker', 'volume', 'ls', '-q', '--filter', 'name=^' + name + '$']))


def read_env(path):
    values = {}
    for line in path.read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values[key.strip()] = value
    return values


def table_counts(db, user, database):
    sql = ' union all '.join(f"select '{t}', count(*) from {t}" for t in TABLES)
    out = run(['docker', 'exec', db, 'psql', '-U', user, '-d', database, '-tAF', '|', '-c', sql])
    return dict(line.split('|') for line in out.splitlines() if line)


def volume_stats(volume, image):
    out = run(['docker', 'run', '--rm', '--entrypoint', 'sh', '-v', volume + ':/v:ro', image, '-c',
               'du -sk /v | cut -f1; find /v | wc -l'])
    kib, files = out.split()
    return int(kib), int(files)


@contextlib.contextmanager
def locks(root):
    """Hold both components' deploy locks, so no release lands mid-migration."""
    handles = []
    try:
        for component in COMPONENTS:
            handle = (root / component / 'deploy.lock').open('a')
            deadline = time.monotonic() + 120
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


def compose(root, component, *args):
    """Compose for the new project, as scripts/deploy/server.py runs it."""
    base = root / component
    state = json.loads((base / 'state.json').read_text())
    release = state['active']
    settings = read_env(base / '.env')
    env = {k: v for k, v in os.environ.items() if not k.startswith('COMPOSE_')}
    env.update(settings)
    env.update(DOCMASTER_IMAGE=release['image'], DOCMASTER_ENV_FILE=str(base / '.env'))
    command = ['docker', 'compose', '--project-name', 'docmaster-' + component, '--env-file', str(base / '.env'),
               '-f', str(base / 'releases' / release['release_id'] / 'stack' / 'compose.yaml')]
    if (base / 'compose.override.yaml').is_file():
        command += ['-f', str(base / 'compose.override.yaml')]
    return run(command + list(args), env=env, timeout=900)


# ---------------------------------------------------------------- modes

def check():
    problems = []
    say('ROOTS', f'old={OLD_ROOT.is_dir()} new={NEW_ROOT.exists()}')
    if not OLD_ROOT.is_dir():
        problems.append('~/pdf-master is missing')
    if NEW_ROOT.exists():
        problems.append('~/docmaster already exists')
    for component in COMPONENTS:
        base = OLD_ROOT / component
        if not base.is_dir():
            problems.append(f'{base} missing')
            continue
        env = read_env(base / '.env')
        say(component.upper(), 'env keys:', ','.join(sorted(env)))
        if 'PDFMASTER_HTTP_PORT' not in env:
            problems.append(f'{component} .env has no PDFMASTER_HTTP_PORT')
        try:
            rewrite_env((base / '.env').read_text(), component)
        except Stop as error:
            problems.append(str(error))
        owner = (base / '.owner').read_text() if (base / '.owner').exists() else ''
        say(component.upper(), 'owner:', owner.strip())
        state = json.loads((base / 'state.json').read_text())
        active = state.get('active') or {}
        say(component.upper(), 'active:', active.get('release_id'), active.get('image'),
            '| previous:', (state.get('previous') or {}).get('release_id'), '| pending:', bool(state.get('pending')))
        if state.get('pending'):
            problems.append(f'{component} has a pending release')
        for _, release in (('active', active), ('previous', state.get('previous') or {})):
            if release.get('image') and not run(['docker', 'images', '-q', release['image']]):
                problems.append(f'{component} image {release["image"]} is not on the server')
        stack = base / 'releases' / str(active.get('release_id')) / 'stack' / 'compose.yaml'
        try:
            rewrite_stack(stack.read_text())
            say(component.upper(), 'stack rewrite: clean')
        except (Stop, OSError) as error:
            problems.append(f'{component} active stack: {error}')
        override = base / 'compose.override.yaml'
        if override.is_file():
            try:
                rewrite_override(override.read_text(), component)
                say(component.upper(), 'override rewrite: clean')
            except Stop as error:
                problems.append(str(error))
        running = containers('pdfmaster-' + component, running_only=True)
        say(component.upper(), 'running containers:', len(running))
        if containers('docmaster-' + component):
            problems.append(f'docmaster-{component} containers already exist')
    db = service_container('pdfmaster-platform', 'db')
    image = run(['docker', 'inspect', '--format', '{{.Config.Image}}', db])
    counts = table_counts(db, 'pdfmaster', 'pdfmaster')
    say('DATABASE', 'image:', image, '| rows:', json.dumps(counts))
    total = 0
    for volume in VOLUMES:
        name = 'pdfmaster-platform_' + volume
        if not volume_exists(name):
            problems.append(f'volume {name} missing')
            continue
        kib, files = volume_stats(name, image)
        total += kib
        say('VOLUME', name, f'{kib / 1024:.0f} MiB', files, 'entries')
        if volume_exists('docmaster-platform_' + volume):
            say('VOLUME', 'docmaster-platform_' + volume, 'already exists (removed by migrate if it is an unused copy)')
    root_dir = run(['docker', 'info', '--format', '{{.DockerRootDir}}'])
    free = shutil.disk_usage(root_dir if os.path.exists(root_dir) else '/').free // 1024
    say('DISK', f'free {free / 1024 / 1024:.1f} GiB, copies need {total / 1024 / 1024:.1f} GiB')
    if free < total * 1.5 + 2 * 1024 * 1024:
        problems.append('not enough free disk for the volume copies')
    cron = run(['crontab', '-l'], check=False)
    mentions = [line for line in cron.splitlines() if 'pdf-master' in line or 'pdfmaster' in line]
    say('CRONTAB', f'{len(mentions)} line(s) name pdf-master' + (': ' + ' | '.join(mentions) if mentions else ''))
    if mentions:
        problems.append('the crontab names ~/pdf-master; update it with the migration')
    if problems:
        say('RENAME_CHECK_PROBLEMS', json.dumps(problems))
        return 1
    say('RENAME_CHECK_READY: migrate can run')
    return 0


def migrate():
    if NEW_ROOT.exists():
        raise Stop('~/docmaster already exists; run rollback or inspect first')
    progress_path = OLD_ROOT / PROGRESS
    with locks(OLD_ROOT):
        # 1. What is running, and the facts to compare the copy against.
        db = service_container('pdfmaster-platform', 'db')
        pg_image = run(['docker', 'inspect', '--format', '{{.Config.Image}}', db])
        before = table_counts(db, 'pdfmaster', 'pdfmaster')
        running = {c: containers('pdfmaster-' + c, running_only=True) for c in COMPONENTS}
        progress = {'running': running, 'step': 'started', 'at': time.time()}
        progress_path.write_text(json.dumps(progress))
        say('STEP 1 rows before:', json.dumps(before))
        # 2. A dump beside the deploy's own pre-release dumps.
        backups = OLD_ROOT / 'platform' / 'backups'
        backups.mkdir(exist_ok=True, mode=0o700)
        dump = backups / f'pre-rename-{time.time_ns()}.dump'
        with dump.open('xb') as stream:
            os.chmod(dump, 0o600)
            result = subprocess.run(['docker', 'exec', db, 'pg_dump', '-U', 'pdfmaster', '-d', 'pdfmaster', '-Fc'],
                                    stdout=stream, stderr=subprocess.PIPE, timeout=900)
        if result.returncode or dump.stat().st_size < 1024:
            raise Stop('pg_dump failed')
        say('STEP 2 dump', dump.name, f'{dump.stat().st_size // 1024} KiB')
        # 3. Stop: traffic first (gateways), then everything; job runners finish the job in hand.
        for component in ('web', 'platform'):
            gateways = [c for c in running[component]
                        if run(['docker', 'inspect', '--format', '{{index .Config.Labels "com.docker.compose.service"}}', c]) == 'gateway']
            if gateways:
                run(['docker', 'stop', '--time', '30', *gateways])
        for component in ('web', 'platform'):
            if running[component]:
                run(['docker', 'stop', '--time', '600', *running[component]], timeout=1200)
        progress['step'] = 'stopped'
        progress_path.write_text(json.dumps(progress))
        say('STEP 3 stopped', sum(len(v) for v in running.values()), 'containers')
        # 4. Copy the volumes; the old ones are only ever read.
        version = run(['docker', 'compose', 'version', '--short']).lstrip('v')
        for volume in VOLUMES:
            old, new = 'pdfmaster-platform_' + volume, 'docmaster-platform_' + volume
            if volume_exists(new):
                labels = run(['docker', 'volume', 'inspect', '--format', '{{json .Labels}}', new])
                if '"docmaster.rename":"copy"' not in labels:
                    raise Stop(f'{new} exists and is not a copy made by this migration')
                run(['docker', 'volume', 'rm', new])
            run(['docker', 'volume', 'create', '--label', 'com.docker.compose.project=docmaster-platform',
                 '--label', 'com.docker.compose.volume=' + volume, '--label', 'com.docker.compose.version=' + version,
                 '--label', COPY_LABEL, new])
            run(['docker', 'run', '--rm', '--entrypoint', 'sh', '-v', old + ':/from:ro', '-v', new + ':/to',
                 pg_image, '-c', 'cp -a /from/. /to/'], timeout=3600)
            a, b = volume_stats(old, pg_image), volume_stats(new, pg_image)
            if a[1] != b[1] or abs(a[0] - b[0]) > max(64, a[0] // 100):
                raise Stop(f'copy of {volume} differs: {a} vs {b}')
            say('STEP 4 copied', volume, f'{b[0] // 1024} MiB', b[1], 'entries')
        progress['step'] = 'copied'
        progress_path.write_text(json.dumps(progress))
        # 5. Rename the database and its role inside the copy.
        password = read_env(OLD_ROOT / 'platform' / '.env')['POSTGRES_PASSWORD']
        if not re.fullmatch(r'[A-Za-z0-9_-]+', password):
            raise Stop('unexpected POSTGRES_PASSWORD format')
        temp = 'docmaster-rename-db'
        run(['docker', 'rm', '-f', temp], check=False)
        run(['docker', 'run', '-d', '--name', temp, '-v', 'docmaster-platform_database:/var/lib/postgresql/data', pg_image])
        try:
            for _ in range(60):
                if subprocess.run(['docker', 'exec', temp, 'pg_isready', '-U', 'pdfmaster'], capture_output=True).returncode == 0:
                    break
                time.sleep(2)
            else:
                raise Stop('the copied database did not start')
            psql = ['docker', 'exec', '-i', temp, 'psql', '-v', 'ON_ERROR_STOP=1', '-d', 'postgres']
            run(psql + ['-U', 'pdfmaster'], input='CREATE ROLE docmaster_rename SUPERUSER LOGIN;\n')
            run(psql + ['-U', 'docmaster_rename'],
                input=('ALTER DATABASE pdfmaster RENAME TO docmaster;\n'
                       'ALTER ROLE pdfmaster RENAME TO docmaster;\n'
                       f"ALTER ROLE docmaster PASSWORD '{password}';\n"))
            run(psql + ['-U', 'docmaster'], input='DROP ROLE docmaster_rename;\n')
            after = table_counts(temp, 'docmaster', 'docmaster')
        finally:
            run(['docker', 'stop', '--time', '30', temp], check=False)
            run(['docker', 'rm', temp], check=False)
        if after != before:
            raise Stop(f'row counts differ after the rename: {before} vs {after}')
        progress['step'] = 'renamed-database'
        progress_path.write_text(json.dumps(progress))
        say('STEP 5 database docmaster, rows:', json.dumps(after))
        # 6. Files under the new names, each kept beside it as it was.
        for component in COMPONENTS:
            base = OLD_ROOT / component
            state_path = base / 'state.json'
            state = json.loads(state_path.read_text())
            targets = [base / '.env', base / '.owner', state_path]
            stacks = [base / 'releases' / r['release_id'] / 'stack' / 'compose.yaml'
                      for r in (state.get('active'), state.get('previous')) if isinstance(r, dict)]
            override = base / 'compose.override.yaml'
            for path in targets + stacks + ([override] if override.is_file() else []):
                shutil.copy2(path, str(path) + BACKUP)
            (base / '.env').write_text(rewrite_env((base / '.env').read_text(), component))
            os.chmod(base / '.env', 0o600)
            (base / '.owner').write_text(f'docmaster-{component}-deploy-v2\n')
            for index, stack in enumerate(stacks):
                try:
                    stack.write_text(rewrite_stack(stack.read_text()))
                except Stop:
                    if index == 0:
                        raise
                    say('STEP 6', component, 'previous release stack left as it was (older format)')
            if override.is_file():
                override.write_text(rewrite_override(override.read_text(), component))
            state, tags = rewrite_state(state, component)
            for old, new in tags:
                if run(['docker', 'images', '-q', old]):
                    run(['docker', 'tag', old, new])
            state_path.write_text(json.dumps(state, indent=2) + '\n')
            say('STEP 6', component, 'files renamed;', len(tags), 'image tags')
        progress['step'] = 'files'
        progress_path.write_text(json.dumps(progress))
        # 7. The folder.
        OLD_ROOT.rename(NEW_ROOT)
    progress_path = NEW_ROOT / PROGRESS
    progress['step'] = 'moved'
    progress_path.write_text(json.dumps(progress))
    say('STEP 7 ~/pdf-master is now ~/docmaster')
    # 8. The same active release, started under the new names.
    with locks(NEW_ROOT):
        compose(NEW_ROOT, 'platform', 'config', '--quiet')
        compose(NEW_ROOT, 'platform', 'up', '-d', '--wait', '--wait-timeout', '300')
        for path in ('/api/v1/health', '/ops/login'):
            compose(NEW_ROOT, 'platform', 'exec', '-T', 'gateway', 'wget', '-q', '-O', '/dev/null', 'http://127.0.0.1:8080' + path)
        say('STEP 8 platform up as docmaster-platform')
        compose(NEW_ROOT, 'web', 'config', '--quiet')
        compose(NEW_ROOT, 'web', 'up', '-d', '--wait', '--wait-timeout', '300')
        compose(NEW_ROOT, 'web', 'exec', '-T', 'gateway', 'wget', '-q', '-O', '/dev/null', 'http://127.0.0.1:8080/en/app')
        say('STEP 8 web up as docmaster-web')
    progress['step'] = 'done'
    progress_path.write_text(json.dumps(progress))
    say('RENAME_MIGRATED: docmaster-platform and docmaster-web are up; old containers and volumes kept stopped for rollback')
    return 0


def rollback():
    root = NEW_ROOT if NEW_ROOT.is_dir() else OLD_ROOT
    progress_file = root / PROGRESS
    progress = json.loads(progress_file.read_text()) if progress_file.exists() else {}
    for component in COMPONENTS:
        started = containers('docmaster-' + component, running_only=True)
        if started:
            run(['docker', 'stop', '--time', '120', *started], timeout=900)
            say('ROLLBACK stopped', len(started), f'docmaster-{component} containers')
    run(['docker', 'rm', '-f', 'docmaster-rename-db'], check=False)
    if NEW_ROOT.is_dir():
        if OLD_ROOT.exists():
            raise Stop('both ~/docmaster and ~/pdf-master exist; inspect by hand')
        NEW_ROOT.rename(OLD_ROOT)
        say('ROLLBACK ~/docmaster is ~/pdf-master again')
    for path in OLD_ROOT.rglob('*' + BACKUP):
        original = Path(str(path)[:-len(BACKUP)])
        shutil.copy2(path, original)
        path.unlink()
        say('ROLLBACK restored', original.relative_to(OLD_ROOT))
    for component in COMPONENTS:
        ids = progress.get('running', {}).get(component) or containers('pdfmaster-' + component)
        if ids:
            run(['docker', 'start', *ids], timeout=900)
            say('ROLLBACK started', len(ids), f'pdfmaster-{component} containers')
    time.sleep(20)
    for component, path in (('platform', '/api/v1/health'), ('web', '/en/app')):
        gateway = service_container('pdfmaster-' + component, 'gateway')
        run(['docker', 'exec', gateway, 'wget', '-q', '-O', '/dev/null', 'http://127.0.0.1:8080' + path])
    say('RENAME_ROLLED_BACK: the pdfmaster projects are up on their original volumes; the copies are left for inspection')
    return 0


OLD_PROJECTS = ('pdfmaster-platform', 'pdfmaster-web')
OLD_IMAGES = ('pdfmaster-platform', 'pdfmaster-web')


def cleanup_targets(root, listed_images):
    """What cleanup removes besides containers and volumes: the files migrate kept
    beside the renamed ones, its progress file and its dump, and the old image tags
    (`docker images` lines "repository:tag"). Pure, so it is unit-tested."""
    files = sorted(root.rglob('*' + BACKUP)) + [p for p in (root / PROGRESS,) if p.exists()]
    files += sorted((root / 'platform' / 'backups').glob('pre-rename-*.dump'))
    tags = [line for line in listed_images
            if line.split(':', 1)[0] in OLD_IMAGES and ':' in line and not line.endswith(':<none>')]
    return files, tags


def cleanup():
    """After an accepted migration: remove the stopped pdfmaster-* projects (containers,
    volumes, networks), the old image tags and migrate's kept files. Ends rollback."""
    if OLD_ROOT.exists() or not NEW_ROOT.is_dir():
        raise Stop('cleanup runs only after a finished migration (~/docmaster present, ~/pdf-master gone)')
    progress = NEW_ROOT / PROGRESS
    if progress.exists() and json.loads(progress.read_text()).get('step') != 'done':
        raise Stop('the migration did not finish; inspect before cleaning up')
    with locks(NEW_ROOT):
        # The renamed stacks must be the ones serving, on their own volumes.
        for component in COMPONENTS:
            state = json.loads((NEW_ROOT / component / 'state.json').read_text())
            if not str(state['active']['image']).startswith('docmaster-' + component + ':'):
                raise Stop(f'{component} active release is not a docmaster image')
            gateway = service_container('docmaster-' + component, 'gateway')
            run(['docker', 'exec', gateway, 'wget', '-q', '-O', '/dev/null',
                 'http://127.0.0.1:8080' + ('/api/v1/health' if component == 'platform' else '/en/app')])
        db = service_container('docmaster-platform', 'db')
        mounted = run(['docker', 'inspect', '--format', '{{range .Mounts}}{{.Name}} {{end}}', db]).split()
        if 'docmaster-platform_database' not in mounted:
            raise Stop('the running database is not on docmaster-platform_database')
        say('CLEANUP renamed stacks serving; rows:', json.dumps(table_counts(db, 'docmaster', 'docmaster')))
        free_before = shutil.disk_usage('/').free
        for project in OLD_PROJECTS:
            label = 'label=com.docker.compose.project=' + project
            if containers(project, running_only=True):
                raise Stop(f'{project} has running containers; it is not the stopped rollback copy')
            ids = containers(project)
            if ids:
                run(['docker', 'rm', *ids])
            volumes = run(['docker', 'volume', 'ls', '-q', '--filter', label]).split()
            for volume in volumes:
                if run(['docker', 'ps', '-aq', '--filter', 'volume=' + volume]):
                    raise Stop(f'{volume} is still used by a container')
                run(['docker', 'volume', 'rm', volume])
            networks = run(['docker', 'network', 'ls', '-q', '--filter', label]).split()
            for network in networks:
                run(['docker', 'network', 'rm', network], check=False)
            say('CLEANUP', project + ':', len(ids), 'containers,', len(volumes), 'volumes,', len(networks), 'networks removed')
        listed = run(['docker', 'images', '--format', '{{.Repository}}:{{.Tag}}']).splitlines()
        files, tags = cleanup_targets(NEW_ROOT, listed)
        for tag in tags:
            run(['docker', 'image', 'rm', tag])
        for path in files:
            path.unlink()
        say('CLEANUP', len(tags), 'old image tags and', len(files), 'kept files removed')
        freed = (shutil.disk_usage('/').free - free_before) / 1024 ** 3
        say(f'RENAME_CLEANED: old pdfmaster projects, images and files removed; {freed:.1f} GiB freed')
    return 0


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    if mode not in ('check', 'migrate', 'rollback', 'cleanup'):
        print('usage: rename_internals.py check|migrate|rollback|cleanup', file=sys.stderr)
        return 2
    os.umask(0o077)
    try:
        return {'check': check, 'migrate': migrate, 'rollback': rollback, 'cleanup': cleanup}[mode]()
    except (Stop, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        say(f'RENAME_{mode.upper()}_FAILED: {error}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
