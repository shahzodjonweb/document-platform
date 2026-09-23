"""Check only PDF Master services and process synthetic, explicitly test data."""
import json
from pathlib import Path
import subprocess
import urllib.request


def command(args, source=None):
    result = subprocess.run(args, input=source, text=True, capture_output=True, timeout=180)
    if result.returncode:
        # Runtime output can contain credentials; expose only controlled markers.
        for line in result.stdout.splitlines():
            if line.startswith('VERIFY_'):
                print(line)
        raise SystemExit('PDF Master verification command failed; no environment or credentials printed.')
    return result.stdout


api = None
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
for port, path in [(8310, '/en/app'), (8311, '/api/v1/health'), (8311, '/ops/login'), (8311, '/static/ops/main.css')]:
    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=15) as response:
        if response.status != 200:
            raise SystemExit('PDF Master gateway route failed')
print('VERIFY_GATEWAYS_OK')
source = 'deployment_commit = ' + repr(commit) + '''
import io,time
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from pypdf import PdfReader,PdfWriter
from apps.core.models import Account,Job,Artifact
from apps.core.services import upload_file,create_quote,submit_job,storage_path
from operations.integrations import telegram_config
assert not settings.DEBUG and not settings.DEV_AUTH_ENABLED and not settings.LOCAL_SYNC_JOBS
account,created=Account.objects.get_or_create(telegram_user_id=-2026092401,
    defaults={'is_test':True,'display_name':'Deployment verification','locale':'en'})
assert account.is_test
key='deployment-smoke-'+deployment_commit
job=Job.objects.filter(account=account,idempotency_key=key).first()
if job is None:
    files=[]
    for count in (1,2):
        document=PdfWriter()
        for page in range(count):document.add_blank_page(width=300,height=400)
        content=io.BytesIO();document.write(content)
        files.append(upload_file(account,SimpleUploadedFile(f'verification-{count}.pdf',content.getvalue(),content_type='application/pdf')))
    quote=create_quote(account,'pdf.merge',[str(asset.pk) for asset in files],{})
    job,_=submit_job(account,quote.pk,key)
deadline=time.monotonic()+90
while job.status in ('queued','running','finalizing') and time.monotonic()<deadline:
    time.sleep(1);job.refresh_from_db()
print('VERIFY_WORKER_RESULT',job.status,job.error_code or 'none')
assert job.status=='succeeded'
artifact=Artifact.objects.select_related('file').get(job=job)
pages=len(PdfReader(storage_path(artifact.file.object_key)).pages)
print('VERIFY_OUTPUT_PAGES',pages)
assert pages==3
assert job.settled_meters=={'file_tasks':1,'file_page_units':3,'ai_credits':0}
print('VERIFY_REAL_MERGE_OK',str(job.pk))
cfg=telegram_config()
print('VERIFY_TELEGRAM_CREDENTIALS', 'configured' if cfg['token'] else 'awaiting_admin_configuration')
if cfg['token']:
    # Read metadata only: never consume updates, change settings or send messages.
    import json,urllib.request,urllib.parse
    from telegram.commands import COMMANDS
    def bot_metadata(method,params=None):
        data=urllib.parse.urlencode(params or {}).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request('https://api.telegram.org/bot'+cfg['token']+'/'+method,data=data),timeout=15) as response:
                result=json.load(response)
            assert result.get('ok')
            return result['result']
        except Exception:
            raise RuntimeError('Telegram metadata verification failed; details suppressed') from None
    identity=bot_metadata('getMe')
    assert identity.get('is_bot')
    print('VERIFY_BOT_USERNAME', identity['username'])
    for locale,commands in COMMANDS.items():
        installed=bot_metadata('getMyCommands',{'language_code':locale})
        assert {row['command']:row['description'] for row in installed}==commands
        print('VERIFY_BOT_COMMANDS',locale,len(installed))
    webhook=bot_metadata('getWebhookInfo')
    assert not webhook.get('url'), 'Expected polling configuration'
    print('VERIFY_BOT_POLLING_CONFIGURATION_OK')
'''
output = command(['docker', 'exec', '-i', api, 'python', 'manage.py', 'shell', '-c',
                  'import sys; exec(sys.stdin.read())'], source)
for line in output.splitlines():
    if line.startswith('VERIFY_'):
        print(line)
