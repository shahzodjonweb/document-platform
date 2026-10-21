#!/usr/bin/env python3
"""Boot this repository's real production stack in an ephemeral CI project."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

def run(command,**kwargs):return subprocess.run(command,check=True,**kwargs)

def wait_for_cleanup_cycle(compose, env, *, timeout=150, interval=2):
    """Qualify the first full cleanup pass within its production memory limit.

    Compose's ``--wait`` only sees this service start because it has no HTTP
    health check. An OOM restart after that point must fail the release. Logs
    are captured privately; only the fixed completion marker is reported.
    """
    deadline = time.monotonic() + timeout

    def capture(command):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError('Cleanup smoke timed out before its first completed cycle.')
        try:
            return run(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, timeout=min(10, remaining))
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            raise RuntimeError('Cleanup smoke could not read the container state.') from None

    container = capture(compose + ['ps', '-q', 'cleanup']).stdout.strip()
    if not re.fullmatch(r'[0-9a-f]{12,64}', container):
        raise RuntimeError('Cleanup smoke did not find exactly one running cleanup container.')
    template = '{"RestartCount":{{.RestartCount}},"State":{{json .State}}}'
    started_at = None

    def state():
        nonlocal started_at
        raw = capture(['docker', 'inspect', '--format', template, container]).stdout
        try:
            snapshot = json.loads(raw)
            current = snapshot['State']
            restarts = snapshot['RestartCount']
            started = current['StartedAt']
        except (ValueError, TypeError, KeyError):
            raise RuntimeError('Cleanup smoke received an invalid container state.') from None
        if current.get('OOMKilled'):
            raise RuntimeError('Cleanup smoke failed: the container was OOM-killed.')
        if type(restarts) is not int or restarts != 0:
            raise RuntimeError('Cleanup smoke failed: the container restarted.')
        if (current.get('Running') is not True or current.get('Status') != 'running'
                or current.get('Restarting') or current.get('Dead')):
            raise RuntimeError('Cleanup smoke failed: the container is not running.')
        if not isinstance(started, str) or not started:
            raise RuntimeError('Cleanup smoke received an invalid container start time.')
        if started_at is not None and started != started_at:
            raise RuntimeError('Cleanup smoke failed: the container restarted.')
        started_at = started

    while True:
        state()
        logs = capture(['docker', 'logs', '--tail', '200', container])
        # stdout and stderr can contain traceback details and storage settings;
        # never forward them to CI output, including when qualification fails.
        marker = re.search(r'^Deleted ([0-9]+) expired files\.\r?$',
                           logs.stdout + '\n' + logs.stderr, flags=re.MULTILINE)
        if marker:
            state()  # Reject an OOM/restart racing the success log read.
            print('Cleanup first cycle completed; container remained running without restarts or OOM.')
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError('Cleanup smoke timed out before its first completed cycle.')
        time.sleep(min(interval, remaining))


# One generated document photo through the real sandbox child, inside the
# read-only worker with its production memory limit: the scanner's weights
# must be in the image (nothing is downloaded) and a scan must fit.
SCANNER_CHECK = """import tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from processors.scanner import load_models
from processors.sandbox import execute_sandbox, execution_timeout
load_models()
photo = Image.new('RGB', (700, 900), (46, 64, 54))
draw = ImageDraw.Draw(photo)
draw.polygon(((130, 80), (570, 125), (590, 810), (70, 750)), fill=(244, 244, 242))
font = ImageFont.truetype('processors/assets/fonts/NotoSans-Regular.ttf', 23)
for number, top in enumerate(range(180, 600, 48), 1):
    draw.text((155, top), f'{number}. Document scan 123', font=font, fill=(35, 35, 35))
with tempfile.TemporaryDirectory() as folder:
    source = Path(folder) / 'photo.png'
    photo.save(source)
    result = execute_sandbox('pdf.images_to_pdf', [source], {}, Path(folder) / 'out',
                             timeout=execution_timeout('pdf.images_to_pdf', 1))
processing = result['metadata']['image_processing']
assert processing['document_pages'] == 1, 'the generated page was not scanned'
assert processing['layouts'][0]['effective_paper_size'] in ('A4', 'Letter', 'Legal'), 'no sheet matched'
print('Document scanner loaded its models and scanned a generated page in the read-only worker.')
"""


def check_scanner(compose, env):
    run(compose + ['exec', '-T', 'worker', 'python', '-c', SCANNER_CHECK], env=env, timeout=300)
    container = run(compose + ['ps', '-q', 'worker'], env=env, stdout=subprocess.PIPE, text=True).stdout.strip()
    state = run(['docker', 'inspect', '--format', '{{.State.OOMKilled}} {{.RestartCount}} {{.State.Running}}',
                 container], stdout=subprocess.PIPE, text=True).stdout.split()
    if state != ['false', '0', 'true']:
        raise RuntimeError('Scanner smoke failed: the worker was OOM-killed, restarted or stopped.')


# One generated screenshot of a fictional CV read by OCR through the real
# bounded child, inside the read-only reader with its production memory
# limit: tesseract and its languages must be in the image, and a page must
# fit beside the reader.
READER_CHECK = """import os
import tempfile
from pathlib import Path
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from PIL import Image, ImageDraw, ImageFont
from apps.studio.extraction import read_cv
shot = Image.new('RGB', (1000, 600), (255, 255, 255))
draw = ImageDraw.Draw(shot)
font = ImageFont.truetype('processors/assets/fonts/NotoSans-Regular.ttf', 34)
for top, line in ((60, 'Dilnoza Karimova'), (140, 'Senior Data Analyst at Example Retail'), (220, 'SQL, Power BI, Python')):
    draw.text((60, top), line, font=font, fill=(20, 20, 20))
with tempfile.TemporaryDirectory() as folder:
    source = Path(folder) / 'shot.png'
    shot.save(source)
    result = read_cv(source, 'image', ocr_pages=1, seconds=60)
assert result['ocr_pages'] == 1 and 'Example Retail' in result['pages'][0]['text'], 'the screenshot was not read'
print('The CV reader read a generated screenshot by OCR in the read-only reader container.')
"""


def check_reader(compose, env):
    run(compose + ['exec', '-T', 'reader', 'python', '-c', READER_CHECK], env=env, timeout=180)
    container = run(compose + ['ps', '-q', 'reader'], env=env, stdout=subprocess.PIPE, text=True).stdout.strip()
    state = run(['docker', 'inspect', '--format', '{{.State.OOMKilled}} {{.RestartCount}} {{.State.Running}}',
                 container], stdout=subprocess.PIPE, text=True).stdout.split()
    if state != ['false', '0', 'true']:
        raise RuntimeError('Reader smoke failed: the reader was OOM-killed, restarted or stopped.')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('component',choices=('platform','web'))
    parser.add_argument('image')
    args=parser.parse_args()
    repo=Path(__file__).resolve().parents[2]
    name='pdfmaster-ci-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT']

    with tempfile.TemporaryDirectory() as temp:
        staging=Path(temp)
        run(['python3',str(repo/'scripts/deploy/init_environment.py'),'--component',args.component,'--root',str(staging)])
        env={**os.environ,'PDFMASTER_IMAGE':args.image,'PDFMASTER_ENV_FILE':str(staging/'.env'),
             'PDFMASTER_HTTP_PORT':'0'}
        compose=['docker','compose','-p',name,'--env-file',str(staging/'.env'),
                 '-f',str(repo/'infra/production/compose.yaml')]
        try:
            run(compose+['config','--quiet'],env=env)
            if args.component=='platform':
                run(compose+['up','-d','--wait','--wait-timeout','120','db','redis'],env=env)
                run(compose+['run','--rm','--no-deps','init'],env=env)
                services=['api','worker','batches','reader','cleanup','bot','gateway']
            else:
                services=['web','gateway']
            run(compose+['up','-d','--wait','--wait-timeout','180',*services],env=env)
            paths=['/en/app'] if args.component=='web' else ['/api/v1/health','/api/v1/plans','/ops/login','/static/ops/main.css']
            for path in paths:
                run(compose+['exec','-T','gateway','wget','-q','-O','/dev/null','http://127.0.0.1:8080'+path],env=env)
            if args.component=='platform':
                code="""import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.conf import settings
assert not settings.DEBUG and not settings.DEVELOPMENT_LOGIN_ENABLED and not settings.LOCAL_SYNC_JOBS
print('Production settings keep development features disabled.')
"""
                run(compose+['exec','-T','api','python','-c',code],env=env)
                check_scanner(compose, env)
                check_reader(compose, env)
                wait_for_cleanup_cycle(compose, env)
            print('Isolated '+args.component+' production stack and gateway routes verified.')
        finally:
            # Only the uniquely named ephemeral CI project may have volumes removed.
            subprocess.run(compose+['down','--volumes'],env=env,stdout=subprocess.DEVNULL)
    print('Container smoke check passed.')


if __name__ == '__main__':
    main()
