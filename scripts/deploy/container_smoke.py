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


# A generated Cyrillic page edited by PdfCraft under the processor child's
# limits, inside the read-only worker without any capability: the binary must
# be in the image and start, change the text in place, and write only under
# the root it is given. Its env is PATH plus HOME, TMPDIR and XDG_* at that root.
# The listing covers $HOME and the container's tmpfs mounts, and nothing else
# writes to those during the check.
PDFCRAFT_CHECK = """import json
import os
import subprocess
import tempfile
from pathlib import Path
from pypdf import PdfReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from processors.__main__ import apply_limits
apply_limits()
binary = os.environ['PDFMASTER_PDFCRAFT_BIN']
version = json.loads(Path('processors/pdfcraft/manifest.json').read_text())['version']

def listing(skip):
    seen = {}
    for top in {str(Path.home()), '/tmp', tempfile.gettempdir(), '/run', '/dev/shm'}:
        for folder, folders, files in os.walk(top):
            folders[:] = [name for name in folders if os.path.join(folder, name) != skip]
            for path in (folder, *(os.path.join(folder, name) for name in folders + files)):
                state = os.lstat(path)
                seen[path] = (state.st_mode, state.st_size, state.st_mtime_ns)
    return seen

def report_of(root, child, steps):
    (root / 'steps.json').write_text(json.dumps(steps, ensure_ascii=False))
    done = subprocess.run([binary, 'run', '--script', str(root / 'steps.json'), '--report', '--root', str(root)],
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, cwd=root, env=child, timeout=60)
    try:
        report = json.loads(done.stdout)
    except ValueError:
        report = {}  # a crash prints no report, and says why on stderr
    failed = [step for step in report.get('steps', []) if step.get('status') != 'ok']
    assert done.returncode == 0 and report.get('ok') is True and report.get('steps') and not failed, f'pdfcraft-cli run: {done.returncode} {failed} {done.stderr[-500:]}'
    return report

with tempfile.TemporaryDirectory(prefix='pdfcraft-check-') as folder:
    root = Path(folder).resolve()
    source, edited = root / 'source.pdf', root / 'edited.pdf'
    pdfmetrics.registerFont(TTFont('Noto', 'processors/assets/fonts/NotoSans-Regular.ttf'))
    page = canvas.Canvas(str(source), pagesize=(595, 842))
    page.setFont('Noto', 12)
    for top, line in ((770, 'Договор поставки учебников'), (730, 'Стороны договорились, что поставка'),
                      (714, 'придёт в Ташкент до конца месяца.'), (670, 'Остальные условия остаются прежними.')):
        page.drawString(72, top, line)
    page.save()
    child = {'PATH': os.environ['PATH'], **dict.fromkeys(('HOME', 'TMPDIR', 'XDG_CACHE_HOME', 'XDG_CONFIG_HOME',
             'XDG_DATA_HOME', 'XDG_STATE_HOME', 'XDG_RUNTIME_DIR'), str(root))}
    before = listing(str(root))
    probe = subprocess.run([binary, '--version'], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           cwd=root, env=child, timeout=30)
    assert probe.returncode == 0 and f'pdfcraft-cli {version}' in probe.stdout, f'version probe: {probe.returncode} {probe.stderr[-500:]}'
    opened = [{'tool': 'doc_open', 'args': {'path': str(source)}}, {'tool': 'text_paragraphs', 'args': {'doc': 1, 'page': 1}}]
    listed = report_of(root, child, opened)['steps'][1]['result'][0]['paragraphs']
    target = next(item for item in listed if 'Ташкент' in item['text'])
    assert target['editor_text'].count('\\n') == 1, 'the two rows were not read as one paragraph with a row break'
    report_of(root, child, [*opened, {'tool': 'text_edit', 'args': {'doc': 1, 'page': 1, 'paragraph': target['paragraph'],
              'text': target['editor_text'].replace('Ташкент', 'Самарканд')}},
              {'tool': 'doc_save', 'args': {'doc': 1, 'path': str(edited)}}])
    after = listing(str(root))
    outside = sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))
    assert not outside, f'pdfcraft-cli wrote outside its root: {outside[:10]}'
    text = ''.join(PdfReader(edited).pages[0].extract_text().split())
    assert 'Самарканд' in text and 'Ташкент' not in text, 'the new word is not in the saved file'
    assert all(line in text for line in ('Договорпоставкиучебников', 'Стороныдоговорились,чтопоставка', 'Остальныеусловияостаютсяпрежними.')), 'the other text changed'
print(f'PdfCraft {version} edited a generated Cyrillic page in the read-only worker and wrote nothing outside its root.')
"""


def check_pdfcraft(compose, env):
    run(compose + ['exec', '-T', 'worker', 'python', '-c', PDFCRAFT_CHECK], env=env, timeout=180)
    container = run(compose + ['ps', '-q', 'worker'], env=env, stdout=subprocess.PIPE, text=True).stdout.strip()
    state = run(['docker', 'inspect', '--format', '{{.State.OOMKilled}} {{.RestartCount}} {{.State.Running}}',
                 container], stdout=subprocess.PIPE, text=True).stdout.split()
    if state != ['false', '0', 'true']:
        raise RuntimeError('PdfCraft smoke failed: the worker was OOM-killed, restarted or stopped.')


# The fonts in decks drawn by the real LibreOffice, and those decks for whoever
# reviews a font change: in the log and the deck-samples artifact, never judged,
# and on pull requests only for the same reason.
def deck_samples(compose, env):
    if env.get('GITHUB_EVENT_NAME') != 'pull_request':
        return
    try:
        run(compose + ['exec', '-T', 'worker', 'python', 'scripts/deploy/deck_samples.py'], env=env, timeout=190)
        if env.get('DECK_SAMPLES_DIR'):
            run(compose + ['cp', 'worker:/data/private/scratch/deck-samples/.', env['DECK_SAMPLES_DIR']], env=env, timeout=60)
    except Exception as error:
        print(f'DECK-FONTS the probe did not finish: {type(error).__name__}')


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


# A deck of 12 photo slides drawn as the editor lane draws one, inside the
# read-only editor with its production memory limit, by the real LibreOffice and
# pdfium: each slide comes out at its size and one edit converts one slide. Its
# numbers and faces go in the log, to be read against the host's budget.
EDITOR_CHECK = """import io
import os
import resource
import tempfile
import time
from pathlib import Path
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from PIL import Image, ImageDraw
from pypdf import PdfReader
from apps.studio import tasks
from apps.studio.variants import fixtures

def photo(seed):
    picture = Image.effect_noise((1600, 1000), 40 + seed).convert('RGB')
    ImageDraw.Draw(picture).ellipse((200 + seed * 40, 200, 900, 800), fill=(30, 90 + seed, 140))
    buffer = io.BytesIO()
    picture.save(buffer, 'JPEG', quality=80)
    return {'jpeg': buffer.getvalue(), 'width': 1600, 'height': 1000, 'provider': 'pixabay', 'id': seed, 'page_url': 'https://pixabay.com/photos/x/'}

sections = [{**fixtures.light('image_split', 3), 'id': f's{number}'} for number in range(1, 13)]
sections[0] = {**sections[0], 'heading': 'Port review', 'body': 'Spring', 'layout': 'cover'}
content = {'title': 'Port review', 'questions': [], 'citations': [], 'sections': sections}
pictures = {section['id']: photo(number) for number, section in enumerate(sections)}
style = {'brand_name': 'Acme Studio', 'deck_design': 'midnight'}

def draw(known):
    began = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='editor-check-') as folder:
        slides, images = tasks.draw_slides(content, 'ru', style, {}, pictures, known, Path(folder))
        for png, thumb, frames in images.values():
            with Image.open(png) as large, Image.open(thumb) as small:
                assert large.size == (1280, 720) and small.size == (96, 54), 'a slide came out the wrong size'
            assert frames, 'a slide has no frames'
        made = sum(png.stat().st_size for png, _, _ in images.values())
        pdf = Path(folder) / 'pdf' / 'converted.pdf'
        weight = pdf.stat().st_size if pdf.exists() else 0
        faces = {str(font.get_object()['/BaseFont']) for page in PdfReader(pdf).pages for font in page['/Resources'].get('/Font', {}).values()} if pdf.exists() else set()
    return slides, images, time.monotonic() - began, made, weight, faces

slides, images, first, made, weight, faces = draw(lambda keys: set())
assert len(images) == 12, 'not every slide was drawn'
assert faces, 'no fonts in the PDF'
keys = {slide['key'] for slide in slides}
sections[5] = {**sections[5], 'heading': 'Another heading'}
_, again, second, _, _, _ = draw(lambda asked: asked & keys)
assert len(again) == 1, f'one edit converted {len(again)} slides'
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
child = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss // 1024
try:
    peak = int(Path('/sys/fs/cgroup/memory.peak').read_text()) // 1024 // 1024
except (OSError, ValueError):
    peak = None
print(f'EDITOR-RENDER 12 photo slides {first:.2f} s, one edited {second:.2f} s, PNGs {made // 1024} KB, PDF {weight // 1024} KB, faces {sorted(faces)}')
print(f'EDITOR-RENDER peak MB: this process {rss}, largest child {child}, container {peak}')
print('The editor lane drew a deck of photos in the read-only editor container.')
"""


def check_editor(compose, env):
    run(compose + ['exec', '-T', 'editor', 'python', '-c', EDITOR_CHECK], env=env, timeout=180)
    container = run(compose + ['ps', '-q', 'editor'], env=env, stdout=subprocess.PIPE, text=True).stdout.strip()
    state = run(['docker', 'inspect', '--format', '{{.State.OOMKilled}} {{.RestartCount}} {{.State.Running}}',
                 container], stdout=subprocess.PIPE, text=True).stdout.split()
    if state != ['false', '0', 'true']:
        raise RuntimeError('Editor smoke failed: the editor was OOM-killed, restarted or stopped.')


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
                services=['api','worker','batches','reader','editor','cleanup','bot','gateway']
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
                check_pdfcraft(compose, env)
                check_reader(compose, env)
                check_editor(compose, env)
                wait_for_cleanup_cycle(compose, env)
                deck_samples(compose, env)
            print('Isolated '+args.component+' production stack and gateway routes verified.')
        finally:
            # Only the uniquely named ephemeral CI project may have volumes removed.
            subprocess.run(compose+['down','--volumes'],env=env,stdout=subprocess.DEVNULL)
    print('Container smoke check passed.')


if __name__ == '__main__':
    main()
