"""Check only PDF Master services and process synthetic, explicitly test data."""
import json
from pathlib import Path
import re
import subprocess
import urllib.request
import uuid


def command(args, source=None):
    result = subprocess.run(args, input=source, text=True, capture_output=True, timeout=740)
    if result.returncode:
        # Runtime output can contain credentials; expose only controlled markers.
        for line in result.stdout.splitlines():
            if line.startswith('VERIFY_'):
                print(line)
        raise SystemExit('PDF Master verification command failed; no environment or credentials printed.')
    return result.stdout


def cleanup_identity(container):
    """Pin the cleanup incarnation and require a release without prior restarts."""
    try:
        state = container['State']
        identifier = container['Id']
        started = state['StartedAt']
        restarts = container['RestartCount']
    except (KeyError, TypeError):
        raise SystemExit('Cleanup verification received an invalid container state.') from None
    if (type(restarts) is not int or restarts != 0 or state.get('OOMKilled')
            or state.get('Running') is not True or state.get('Status') != 'running'
            or state.get('Restarting') or state.get('Dead')):
        raise SystemExit('Cleanup verification failed: container stopped, restarted or was OOM-killed.')
    if (not isinstance(identifier, str) or not re.fullmatch(r'[0-9a-f]{64}', identifier)
            or not isinstance(started, str) or not started):
        raise SystemExit('Cleanup verification received an invalid container identity.')
    return {'id': identifier, 'started_at': started}


def cleanup_command(args):
    """Capture Docker output without forwarding potentially private log lines."""
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        raise SystemExit('Cleanup verification could not read container state or logs.') from None
    if result.returncode:
        raise SystemExit('Cleanup verification could not read container state or logs.')
    return result.stdout, result.stderr


def verify_cleanup_cycle(baseline):
    """Run after all probes, so a delayed startup OOM cannot pass verification."""
    ids, _ = cleanup_command(['docker', 'ps', '-aq', '--no-trunc', '--filter',
                              'label=com.docker.compose.project=pdfmaster-platform', '--filter',
                              'label=com.docker.compose.service=cleanup'])
    if ids.split() != [baseline['id']]:
        raise SystemExit('Cleanup verification failed: the container changed during service checks.')
    template = '{"Id":{{json .Id}},"RestartCount":{{.RestartCount}},"State":{{json .State}}}'

    def state():
        output, _ = cleanup_command(['docker', 'inspect', '--format', template, baseline['id']])
        try:
            container = json.loads(output)
        except (ValueError, TypeError):
            raise SystemExit('Cleanup verification received an invalid container state.') from None
        if cleanup_identity(container) != baseline:
            raise SystemExit('Cleanup verification failed: the container restarted during service checks.')

    state()
    output, error = cleanup_command(['docker', 'logs', '--since', baseline['started_at'],
                                     '--tail', '200', baseline['id']])
    if not re.search(r'^Deleted [0-9]+ expired files\.\r?$',
                     output + '\n' + error, flags=re.MULTILINE):
        raise SystemExit('Cleanup verification failed: the current container has not completed a cleanup cycle.')
    state()
    print('VERIFY_CLEANUP_CYCLE_OK', flush=True)


api = None
cleanup_baseline = None
for component, expected in [('platform', {'api', 'db', 'redis', 'worker', 'batches', 'cleanup', 'bot', 'gateway'}),
                            ('web', {'web', 'gateway'})]:
    ids = command(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=pdfmaster-' + component]).split()
    containers = json.loads(command(['docker', 'inspect', *ids])) if ids else []
    services = {c['Config']['Labels']['com.docker.compose.service']: c for c in containers}
    if not expected.issubset(services):
        raise SystemExit('Missing PDF Master services: ' + ', '.join(sorted(expected - services.keys())))
    for name in sorted(expected):
        container = services[name]
        state = container['State']
        health = state.get('Health', {}).get('Status', 'no-healthcheck')
        print('SERVICE', json.dumps({'project': component, 'service': name, 'state': state['Status'],
                                     'health': health, 'restarts': container['RestartCount'],
                                     'oom_killed': state['OOMKilled']}))
        if state['Status'] != 'running' or health not in {'healthy', 'no-healthcheck'} or state['OOMKilled']:
            raise SystemExit('Unhealthy PDF Master service: ' + name)
        if name != 'gateway' and 'orderdesk_default' in container['NetworkSettings']['Networks']:
            raise SystemExit('Only a PDF Master gateway may join the shared proxy network')
    active = json.loads((Path.home() / 'pdf-master' / component / 'state.json').read_text())['active']
    print('ACTIVE_RELEASE', component, active['commit'])
    if component == 'platform':
        api = services['api']['Id']
        commit = active['commit']
        redis = services['redis']['Id']
        cleanup_baseline = cleanup_identity(services['cleanup'])
for port, path in [(8310, '/en/app'), (8311, '/api/v1/health'), (8311, '/ops/login'), (8311, '/static/ops/main.css')]:
    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=15) as response:
        if response.status != 200:
            raise SystemExit('PDF Master gateway route failed')
print('VERIFY_GATEWAYS_OK')
# The Redis key is unique to this audit and expires even if this process stops.
redis_key = 'pdfmaster:service-audit:' + uuid.uuid4().hex
assert command(['docker', 'exec', redis, 'redis-cli', 'PING']).strip() == 'PONG'
assert command(['docker', 'exec', redis, 'redis-cli', 'SET', redis_key, 'probe', 'EX', '15']).strip() == 'OK'
assert command(['docker', 'exec', redis, 'redis-cli', 'GET', redis_key]).strip() == 'probe'
command(['docker', 'exec', redis, 'redis-cli', 'DEL', redis_key])
print('VERIFY_REDIS_ROUNDTRIP_OK', flush=True)
source = 'CHECK_SOURCES = ' + repr(CHECK_SOURCES) + '\n' + '''
import json,time,uuid,sys,types
from pathlib import Path
from django.conf import settings
from django.db import connection,transaction
from django.db.migrations.executor import MigrationExecutor
from operations.integrations import telegram_config,antibot_config
assert not settings.DEBUG and not settings.DEV_AUTH_ENABLED and not settings.LOCAL_SYNC_JOBS
with connection.cursor() as cursor:
    cursor.execute('SELECT 1'); assert cursor.fetchone()[0]==1
executor=MigrationExecutor(connection)
assert not executor.migration_plan(executor.loader.graph.leaf_nodes())
print('VERIFY_DATABASE_QUERY_MIGRATIONS_OK',flush=True)
modules={}
for name,code in CHECK_SOURCES.items():
    module_name='service_audit_'+name.replace('.','_')
    module=types.ModuleType(module_name)
    module.__file__=str(Path.cwd()/'scripts'/'operations'/name)
    sys.modules[module_name]=module
    namespace=module.__dict__
    exec(compile(code,name,'exec'),namespace);modules[name]=namespace
background=modules['service_checks_background.py']
started=time.monotonic()
audit_id=str(uuid.uuid4())
context=background['prepare_canaries'](audit_id)
print('VERIFY_CANARIES_PREPARED',flush=True)
results=[]
def emit(category,result):
    row={'check':category,**result};results.append(row)
    print('VERIFY_CHECK',json.dumps(row,sort_keys=True),flush=True)
# File storage: the bucket takes, returns and deletes a file, and nothing waits too long to upload.
from datetime import timedelta
from django.utils import timezone as dj_timezone
from apps.core import storage
from apps.core.models import StoredObject
storage_settings=storage.config()
print('VERIFY_STORAGE_CONFIG','ready='+str(bool(storage_settings.get('ready'))),'configured='+str(bool(storage_settings.get('configured'))),flush=True)
storage_since=dj_timezone.now()
if storage_settings.get('ready'):
    try:
        storage.check(storage_settings);roundtrip='passed'
    except Exception:
        roundtrip='failed'
    totals=storage.health()
    late=StoredObject.objects.filter(remote=False,created_at__lt=dj_timezone.now()-timedelta(minutes=15)).count()
    emit('object_storage',{'status':'passed' if roundtrip=='passed' and not late else 'failed','roundtrip':roundtrip,
                           'in_bucket':totals['remote_files'],'waiting':totals['waiting_files'],'late':late})
ab=antibot_config()
print('VERIFY_ANTIBOT_CONFIG', 'bot_enabled='+str(bool(ab['bot_enabled'])), 'web_enabled='+str(bool(ab['web_enabled'])), 'web_configured='+str(bool(ab['configured'])))
from telegram.verification import prepare,consume
with transaction.atomic():
    synthetic_id=-int(uuid.uuid4().int % (2**62))-1
    challenge=prepare(synthetic_id)
    assert challenge['status']=='required' and len(challenge['challenge']['choices'])==8
    callback='human:'+str(synthetic_id)+':'+challenge['nonce']+':'+challenge['challenge']['answer']
    assert consume(synthetic_id,callback)['status']=='verified'
    assert consume(synthetic_id,callback)['status']=='already_verified'
    transaction.set_rollback(True)
emit('bot_verification',{'status':'passed','scope':'rollback_only_native_challenge'})
emit('bot_polling_process',background['polling_process_lock']())
''' + "cfg=telegram_config()\nprint('VERIFY_TELEGRAM_CREDENTIALS', 'configured' if cfg['token'] else 'awaiting_admin_configuration')\nif cfg['token']:\n    # Read metadata only: never consume updates, change settings or send messages.\n    import json,urllib.request,urllib.parse\n    from telegram.commands import COMMANDS\n    def bot_metadata(method,params=None):\n        data=urllib.parse.urlencode(params or {}).encode()\n        try:\n            with urllib.request.urlopen(urllib.request.Request('https://api.telegram.org/bot'+cfg['token']+'/'+method,data=data),timeout=15) as response:\n                result=json.load(response)\n            assert result.get('ok')\n            return result['result']\n        except Exception:\n            raise RuntimeError('Telegram metadata verification failed; details suppressed') from None\n    identity=bot_metadata('getMe')\n    assert identity.get('is_bot')\n    print('VERIFY_BOT_USERNAME', identity['username'])\n    for locale,commands in COMMANDS.items():\n        installed=bot_metadata('getMyCommands',{'language_code':locale})\n        assert {row['command']:row['description'] for row in installed}==commands\n        print('VERIFY_BOT_COMMANDS',locale,len(installed))\n    webhook=bot_metadata('getWebhookInfo')\n    assert not webhook.get('url'), 'Expected polling configuration'\n    print('VERIFY_BOT_POLLING_CONFIGURATION_OK')\n" + '''
modules['service_checks_documents.py']['check_documents'](audit_id,lambda row:emit('document',row))
paid=modules['service_checks_paid.py']['check_paid_processors'](audit_id)
for feature,result in paid.items():
    emit('paid_processor',{'feature':feature,**result})
while True:
    observed=background['poll_background'](context)
    if not any(r['status']=='pending' for r in observed.values()) or time.monotonic()-started>335:
        break
    time.sleep(2)
for name,result in observed.items():
    if result['status']=='pending':result={**result,'status':'failed','code':'scheduler_deadline'}
    emit(name,result)
if storage_settings.get('ready'):
    # Every file this audit wrote (uploads, results, previews) must reach the bucket.
    deadline=time.monotonic()+90
    while True:
        written=StoredObject.objects.filter(created_at__gte=storage_since)
        pending=written.filter(remote=False).count()
        if not pending or time.monotonic()>deadline:break
        time.sleep(3)
    emit('object_storage_audit_files',{'status':'passed' if not pending else 'failed',
                                       'written':written.count(),'not_in_bucket':pending})
    # Keep the batch canaries alive until this check finishes. Document probes
    # retire their own files immediately and can race the ordinary cleanup.
    # A private audit cache exercises downloads without unlinking working copies.
    emit('object_storage_fetch_back',modules['service_checks_storage.py']['check_fetch_back'](context))
print('VERIFY_CANARY_RETENTION',json.dumps(background['retire_canaries'](context)))
failed=[r for r in results if r['status']!='passed']
print('VERIFY_SUMMARY',json.dumps({'checks':len(results),'failed':len(failed),'seconds':round(time.monotonic()-started,1)}),flush=True)
if failed:raise SystemExit(1)
'''
output = command(['docker', 'exec', '-i', api, 'python', 'manage.py', 'shell', '-c',
                  "import sys\ntry:\n exec(sys.stdin.read())\nexcept Exception as exc:\n print('VERIFY_FAILURE',type(exc).__name__,getattr(exc,'code','unspecified'))\n raise SystemExit(1)"], source)
for line in output.splitlines():
    if line.startswith('VERIFY_'):
        print(line)
verify_cleanup_cycle(cleanup_baseline)
