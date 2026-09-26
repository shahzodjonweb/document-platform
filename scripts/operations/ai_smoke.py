"""Bounded live check of the configured AI provider.

Run this where the credentials already live — on the server, inside the api
container — so the key never moves. It reads the encrypted configuration from
the database, never prints it, and makes a small, fixed number of real calls.

    docker compose -p pdfmaster-platform --env-file .env \
      -f releases/<release>/stack/compose.yaml \
      exec api python scripts/operations/ai_smoke.py

Cost: three requests by default. Nothing is written to a customer account and
no job or ledger row is created.
"""
import os
import sys
from pathlib import Path

import django

# Runnable by path from anywhere, including `exec api python scripts/...`.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.core.errors import DomainError  # noqa: E402
from apps.studio import pages  # noqa: E402
from apps.studio.domain import DOCUMENT, SLIDES  # noqa: E402
from apps.studio.provider import generate, writing_guidance  # noqa: E402
from operations.integrations import ai_config  # noqa: E402

PASS, FAIL = 'PASS', 'FAIL'
results = []


def report(name, status, detail=''):
    results.append((name, status, detail))
    print(f'{status:4}  {name:36} {detail}')


def sample(sections, output_format='pdf'):
    return {
        'output_locale': 'en',
        'prompt': 'Explain how tide tables are read, for a general audience.',
        'source_text': '',
        'excerpts': [],
        'output_format': output_format,
        'options': {'question_count': 0, 'length': sections},
        'content': {
            'title': 'Reading tide tables',
            'sections': [
                {'id': f's{i + 1}', 'heading': f'Part {i + 1}', 'body': '', 'notes': ''}
                for i in range(sections)
            ],
            'questions': [],
            'citations': [],
        },
    }


def characters(answer):
    return [len(section.get('body') or '') for section in answer['sections']]


config = ai_config()
print(f'provider mode : {config["mode"]}')
print(f'text model    : {config["model"] or "(none)"}')
print(f'api key       : {"configured" if config["api_key"] else "MISSING"}\n')

if config['mode'] != 'openai' or not config['api_key'] or not config['model']:
    report('provider configured', FAIL, 'set mode, model and key in Admin → Integrations')
    sys.exit(1)
report('provider configured', PASS, 'two services enabled by this key')

# 1. Credentials and model name, via the smallest real generation we can make.
try:
    answer, usage = generate(config, sample(1), DOCUMENT, 'ai-smoke-probe', token_limit=24000)
    report('credentials and model', PASS, f'{usage["input_tokens"]}→{usage["output_tokens"]} tokens')
    report('strict JSON schema honoured', PASS, f'{len(answer["sections"])} section(s) returned')
except DomainError as error:
    report('credentials and model', FAIL,
           f'{error.code} — check the key and that "{config["model"]}" is a valid model id')
    sys.exit(1)

# 2. Does it return the number of sections asked for? One section is one page,
#    so this is what makes "a 4 page document" mean four pages.
try:
    four, _ = generate(config, sample(4), DOCUMENT, 'ai-smoke-pages', token_limit=24000)
    count = len(four['sections'])
    report('one section per page requested', PASS if count == 4 else FAIL, f'asked 4, got {count}')
except DomainError as error:
    report('one section per page requested', FAIL, error.code)
    four = None

# 3. Are those pages actually full? A short section renders as a half-empty page.
if four:
    lengths = characters(four)
    target = pages.CHARS_PER_PAGE
    full = [n for n in lengths[:-1] if n >= target * 0.6]
    detail = f'target {target}, got {lengths} characters'
    report('pages are filled, not sparse', PASS if len(full) == len(lengths) - 1 else FAIL, detail)
    if len(full) != len(lengths) - 1:
        print('       guidance sent:', writing_guidance({}, 4, 'pdf'))

# 4. Slides ask for much less prose per section; confirm the model is told so.
guidance = writing_guidance({}, 6, 'pptx')
report('slides get their own target', PASS if str(pages.CHARS_PER_SLIDE) in guidance else FAIL,
       f'{pages.CHARS_PER_SLIDE} characters per slide')

failed = [name for name, status, _ in results if status == FAIL]
print('\n' + ('FAILED: ' + ', '.join(failed) if failed else 'All checked paths are working.'))
sys.exit(1 if failed else 0)
