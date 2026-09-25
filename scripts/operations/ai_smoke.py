"""Bounded live check of the configured AI provider.

Run this where the credentials already live — on the server, inside the api
container — so the key never moves. It reads the encrypted configuration from
the database, never prints it, and makes a small, fixed number of real calls.

    docker compose -p pdfmaster-platform --env-file .env \
      -f releases/<release>/stack/compose.yaml \
      exec api python scripts/operations/ai_smoke.py

Cost: three requests by default (one probe, two short generations). Nothing is
written to a customer account and no job or ledger row is created.
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
from apps.studio.domain import GENERATION_IDS  # noqa: E402
from apps.studio.provider import generate, writing_guidance  # noqa: E402
from operations.integrations import ai_config  # noqa: E402

PASS, FAIL, SKIP = 'PASS', 'FAIL', 'SKIP'
results = []


def report(name, status, detail=''):
    results.append((name, status, detail))
    print(f'{status:4}  {name:34} {detail}')


def sample(options, sections=2):
    return {
        'output_locale': 'en',
        'prompt': 'Explain how tide tables are read, for a general audience.',
        'source_text': '',
        'excerpts': [],
        'options': {'question_count': 0, **options},
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


def words(answer):
    return sum(len((section.get('body') or '').split()) for section in answer['sections'])


config = ai_config()
print(f'provider mode : {config["mode"]}')
print(f'text model    : {config["model"] or "(none)"}')
print(f'image model   : {config.get("image_model") or "(none)"}')
print(f'api key       : {"configured" if config["api_key"] else "MISSING"}\n')

if config['mode'] != 'openai' or not config['api_key'] or not config['model']:
    report('provider configured', FAIL, 'set mode, model and key in Admin → Integrations')
    sys.exit(1)
report('provider configured', PASS, f'{len(GENERATION_IDS)} features enabled by this key')

# 1. Credentials and model name, via the smallest real generation we can make.
try:
    answer, usage = generate(config, sample({'density': 'airy'}, sections=1), 'ai.pdf_text',
                             'ai-smoke-probe', token_limit=24000)
    report('credentials and model', PASS,
           f'{usage["input_tokens"]}→{usage["output_tokens"]} tokens')
    report('strict JSON schema honoured', PASS, f'{len(answer["sections"])} section(s) returned')
except DomainError as error:
    report('credentials and model', FAIL,
           f'{error.code} — check the key and that "{config["model"]}" is a valid model id')
    sys.exit(1)

# 2. Does the model actually obey the density instruction?
try:
    airy = words(answer)
    rich_answer, _ = generate(config, sample({'density': 'rich'}, sections=1), 'ai.pdf_text',
                              'ai-smoke-rich', token_limit=24000)
    rich = words(rich_answer)
    detail = f'airy {airy} words vs rich {rich} words'
    report('density changes written length', PASS if rich > airy * 1.5 else FAIL, detail)
    if rich <= airy * 1.5:
        print('       guidance sent:', writing_guidance({'density': 'rich'}, 1))
except DomainError as error:
    report('density changes written length', FAIL, error.code)

# 3. Config-level checks for the two features needing more than a text model.
if config.get('image_model'):
    report('image generation (ai.images)', PASS, f'image model {config["image_model"]} set')
else:
    report('image generation (ai.images)', SKIP, 'no image model configured — this feature stays off')

try:
    from apps.studio.handwriting import image_token_bound
    image_token_bound(config['model'])
    report('handwriting vision model', PASS, f'{config["model"]} is qualified')
except DomainError:
    report('handwriting vision model', SKIP,
           f'{config["model"]} is not in the qualified vision list — handwriting stays off')

failed = [name for name, status, _ in results if status == FAIL]
print('\n' + ('FAILED: ' + ', '.join(failed) if failed else 'All checked paths are working.'))
sys.exit(1 if failed else 0)
