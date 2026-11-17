"""Bounded live check of the configured AI provider.

Run this where the credentials already live — on the server, inside the api
container — so the key never moves. It reads the encrypted configuration from
the database, never prints it, and makes a small, fixed number of real calls.

    docker compose -p docmaster-platform --env-file .env \
      -f releases/<release>/stack/compose.yaml \
      exec api python scripts/operations/ai_smoke.py

Cost: three requests by default. Nothing is written to a customer account and
no job or ledger row is created.

A category deck (apps/studio/categories), one real run per entry before the
owner ticks it on /ops/categories:

    ... exec api python scripts/operations/ai_smoke.py --category slides.himoya --locale uz --case figures

It makes the deck the way a job does, with no account: the draft seeded from
the entry's slots, one provider.generate (a long deck may be written in
parts), quality.check with the slides finish.exempt spares, title_lines and
finish.apply, and render_pptx with finish.pins, into `--out` (a new temporary
folder by default). The message is the entry's invented sample for `--case`
(categories/samples, else the test fixtures), or `--prompt`. It prints codes
and counts only: whether the slides came back as asked, which fixed headings
and layouts the model kept, what the check would send back, what finish took
out, which pins gave way and whether the file passes the alphabet read-back.
`--category slides.` runs every deck entry, at one run each.

A paper category the same way (`--category pdf.xat.ariza`, or `pdf.xat.` for
a family, `pdf.` for every paper), as a job makes it once its entry is ready:
the draft seeded from the entry's parts at the length the domain gives the
message within the plan's 35 pages (`--slides` overrides the pages; a test's
questions come from the message), one provider.generate (written in spans),
quality.check with finish.exempt, title_lines and finish.apply, and
execution.draw_paper, which draws it in its own template. The message is the
entry's first bot example in `--locale` (invented, as the catalogue's copy
is), or `--prompt`; `--case` is a deck's. It reports whether the paper was
drawn by its template and not the emergency fallback, its pages against the
quote (with the sheets the template leaves out of it, page_rule.uncounted, such
as a lesson's cover), the template's codes and the alphabet read-back. The
top-up of a count paper is not run, as one call is the smoke's budget: a paper
the model wrote short is reported short here, where the job would fill it once.
Nothing is stored, and the switch need not be on.
"""
import argparse
import os
import sys
import tempfile
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

PASS, FAIL, NOTE = 'PASS', 'FAIL', 'NOTE'
results = []

parser = argparse.ArgumentParser(description='Bounded live check of the configured AI provider.')
parser.add_argument('--category',
                    help='a category id, or a prefix ending in "." (slides., pdf.xat.) for every entry under it')
parser.add_argument('--locale', default='uz', choices=('uz', 'ru', 'en'))
parser.add_argument('--case', default='figures', help='the sample to take the message from: figures or topic_only')
parser.add_argument('--slides', type=int,
                    help='the slide or page count; by default the one the entry gives the message')
parser.add_argument('--prompt', help='the customer\'s message, in place of the sample\'s')
parser.add_argument('--out', help='where the decks are written; a new temporary folder by default')
args = parser.parse_args()


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


def category_deck(entry, out):
    """One category deck made as a job makes it, with no account and nothing stored; its checks are reported."""
    from apps.studio import quality, title_lines
    from apps.studio.categories import finish, sample as samples, skeleton
    from apps.studio.scripts import artifact_violations
    from apps.studio.slides import render_pptx
    name = entry.id
    given = samples.load(entry.id, args.case)
    prompt = args.prompt or (given.get('prompt') or {}).get(args.locale) or entry.label(args.locale)
    draft = {'output_locale': args.locale, 'prompt': prompt, 'source_text': '', 'source_ids': [], 'excerpts': [],
             'output_format': 'pptx', 'options': {'category': entry.id}}
    cues = skeleton.cues_of(draft)
    slides = skeleton.length(entry, asked=args.slides or pages.requested_pages(prompt), cues=cues)
    design = entry.look['designs'][0]
    draft['options'].update(pages=slides, length=slides, question_count=0, image_cap=0,
                            template_style={'deck_design': design})
    draft['content'] = {'title': '', 'sections': skeleton.seed(entry, slides, cues), 'questions': [], 'citations': []}
    try:
        answer, usage = generate(config, draft, SLIDES, f'ai-smoke-{entry.id}', token_limit=120000)
    except DomainError as error:
        report(f'{name} written', FAIL, error.code)
        return
    sections = answer.get('sections') or []
    report(f'{name} written', PASS, f'{usage.get("input_tokens", 0)}→{usage.get("output_tokens", 0)} tokens, '
           f'{args.locale}, {args.case if not args.prompt else "own message"}')
    ids = [section.get('id') for section in sections]
    report(f'{name} slides as asked', PASS if ids == [f's{n}' for n in range(1, slides + 1)] else FAIL,
           f'asked {slides}, got {len(sections)}')
    blueprint = skeleton.slots(entry, slides, cues)
    fixed = [(slot, section) for slot, section in zip(blueprint, sections) if slot['heading_mode'] == 'fixed']
    # A fixed heading left empty is what the model is told; one in its own words is not.
    reworded = sum(bool(section.get('heading')) and section.get('heading') != slot['heading'][args.locale]
                   for slot, section in fixed)
    astray = sum(section.get('layout') not in slot['layouts'] for slot, section in zip(blueprint, sections))
    report(f'{name} slots followed', NOTE if reworded or astray else PASS,
           f'fixed headings reworded {reworded}/{len(fixed)}, layouts outside their slot {astray}/{len(sections)}'
           f'{" (finish puts them back)" if reworded or astray else ""}')
    content = {'title': answer.get('title', ''), 'sections': sections, 'questions': [], 'citations': []}
    found = quality.check(content, locale=args.locale, fmt='pptx', prompt=prompt, exempt=finish.exempt(draft))
    wrong = {code: len(items) for code, items in found.issues.items() if items and code != 'script'}
    report(f'{name} quality', NOTE if found.to_repair() else PASS,
           ', '.join(f'{code} {count}' for code, count in sorted(wrong.items())) or 'nothing a job would send back')
    content = quality.normalise(content, args.locale)
    content = title_lines.apply(draft, content)
    codes = []
    content, warnings = finish.apply(draft, content, file_names=[], codes=codes)
    report(f'{name} held to the message', NOTE if codes else PASS,
           ', '.join(warnings + codes) or 'finish took nothing out')
    deck = render_pptx(content, Path(out) / f'{entry.id}-{args.case}-{args.locale}-{slides}.pptx', args.locale,
                       'user_document', style={'deck_design': design}, pins=finish.pins(draft, content))
    metadata = deck['metadata']
    report(f'{name} drawn', PASS if deck['page_count'] == slides else FAIL,
           f'{deck["page_count"]} slides in {metadata["design"]}, {len(metadata["repinned"])} pins gave way, '
           f'{len(metadata["shortened"])} shortened')
    cyrillic = artifact_violations(deck['path'], args.locale, '')
    report(f'{name} alphabet read-back', FAIL if cyrillic else PASS,
           f'{len(cyrillic)} Cyrillic words' if cyrillic else deck['path'])


def category_paper(entry, out):
    """One category paper made as a job makes it, with no account and nothing stored; its checks are reported."""
    from apps.studio import quality, title_lines
    from apps.studio.categories import finish, skeleton
    from apps.studio.execution import draw_paper
    from apps.studio.scripts import artifact_violations
    name = entry.id
    prompt = args.prompt or entry.raw['bot']['examples'][0][args.locale]
    draft = {'output_locale': args.locale, 'prompt': prompt, 'source_text': '', 'source_ids': [], 'excerpts': [],
             'output_format': 'pdf', 'options': {'category': entry.id}}
    cues = skeleton.cues_of(draft)
    questions = min(pages.requested_questions(prompt) or entry.raw['questions']['default'],
                    entry.raw['questions']['max'])
    length = skeleton.length(entry, asked=args.slides or pages.requested_pages(prompt), cues=cues, ceiling=35,
                             questions=questions)
    draft['options'].update(length=length, question_count=questions, requested_pages=None, image_cap=0)
    draft['content'] = {'title': '', 'sections': skeleton.seed(entry, length, cues), 'questions': [],
                        'citations': []}
    try:
        answer, usage = generate(config, draft, DOCUMENT, f'ai-smoke-{entry.id}', token_limit=120000)
    except DomainError as error:
        report(f'{name} written', FAIL, error.code)
        return
    report(f'{name} written', PASS, f'{usage.get("input_tokens", 0)}→{usage.get("output_tokens", 0)} tokens, '
           f'{args.locale}, {length} page(s) quoted, {"example" if not args.prompt else "own message"}')
    content = {'title': answer.get('title', ''), 'sections': answer.get('sections') or [],
               'questions': answer.get('questions') or [], 'citations': []}
    found = quality.check(content, locale=args.locale, fmt='pdf', prompt=prompt, exempt=finish.exempt(draft))
    wrong = {code: len(items) for code, items in found.issues.items() if items and code != 'script'}
    report(f'{name} quality', NOTE if found.to_repair() else PASS,
           ', '.join(f'{code} {count}' for code, count in sorted(wrong.items())) or 'nothing a job would send back')
    content = title_lines.apply(draft, quality.normalise(content, args.locale))
    codes = []
    content, warnings = finish.apply(draft, content, file_names=[], codes=codes)
    report(f'{name} held to the message', NOTE if codes else PASS,
           ', '.join(warnings + codes) or 'finish took nothing out')
    drawn = draw_paper(draft, content, Path(out) / f'{entry.id}-{args.locale}-{length}.pdf')
    metadata = drawn.get('metadata') or {}
    template = metadata.get('template') or '?'
    report(f'{name} template', FAIL if metadata.get('template_fallback') else PASS,
           'the emergency fallback drew it' if metadata.get('template_fallback') else template)
    # A sheet the quote leaves out (a lesson's cover, a handout's key: page_rule.uncounted) is drawn on top of
    # it by design, with no longer_than_quoted; only a paper over both is the renderer's own NOTE.
    extra = int(metadata.get('uncounted') or 0)
    longer = 'longer_than_quoted' in (metadata.get('warnings') or ())
    report(f'{name} pages', PASS if drawn['page_count'] <= length + extra else NOTE if longer else FAIL,
           f'{drawn["page_count"]} of {length} quoted{f" and {extra} uncounted" if extra else ""}, '
           f'step {metadata.get("fit_step")}, '
           f'{", ".join(metadata.get("warnings") or ()) or "no codes"}')
    cyrillic = artifact_violations(drawn['path'], args.locale, '')
    report(f'{name} alphabet read-back', FAIL if cyrillic else PASS,
           f'{len(cyrillic)} Cyrillic words' if cyrillic else drawn['path'])


if args.category:
    from apps.studio import categories
    from apps.studio.categories import catalogue
    if args.category.endswith('.'):
        chosen = [entry for feature in catalogue.FEATURES.values() for entry in catalogue.for_feature(feature)
                  if entry.id.startswith(args.category)]
    else:
        chosen = [entry for entry in [categories.get(args.category)] if entry is not None]
    if not chosen:
        report('category', FAIL, f'{args.category} is not in this catalogue')
    out = args.out or tempfile.mkdtemp(prefix='ai-smoke-')
    Path(out).mkdir(parents=True, exist_ok=True)
    for entry in chosen:
        try:
            (category_deck if entry.service == 'slides' else category_paper)(entry, out)
        except Exception as error:
            # One entry that breaks the pipeline is a finding; the rest are still run.
            report(f'{entry.id}', FAIL, type(error).__name__)
    failed = [name for name, status, _ in results if status == FAIL]
    print('\n' + ('FAILED: ' + ', '.join(failed) if failed else 'Every category checked was made.'))
    sys.exit(1 if failed else 0)

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
# A slide is asked for as a slide: a layout chosen from the catalogue, and a
# list only when the layout is one. (This used to look for a character count,
# which the guidance deliberately never contains, so it failed on every run.)
guidance = writing_guidance({}, 6, 'pptx')
report('slides choose a layout', PASS if 'Choose a layout for every section' in guidance
       and '3 to 5 bullets, one per line' in guidance else FAIL, 'layout guide and list rule present')

failed = [name for name, status, _ in results if status == FAIL]
print('\n' + ('FAILED: ' + ', '.join(failed) if failed else 'All checked paths are working.'))
sys.exit(1 if failed else 0)
