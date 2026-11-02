#!/usr/bin/env python3
"""The fonts in decks drawn by the real LibreOffice, and decks for a person to look at.

The fit a deck is drawn to assumes faces no developer's machine can check without
LibreOffice. On a pull request, container_smoke.py runs this inside the read-only
worker after every check that can fail the build, and nothing here can fail it:
`grep DECK-FONTS` finds the results, and what it drew goes up as the deck-samples
artifact. Made-up text only (apps.studio.variants.fixtures).

Each deck goes through the real processor child with the deck's faces. The first
design's also goes through the path customers' own files take, which must still
embed what it did before the deck faces existed (`TODAY`), and nothing else. A
line that is not as expected says so: a person reads it, because no image of ours
has been told it must pass.
"""
from pathlib import Path
import os
import shutil
import sys
import tempfile
import time
import traceback

BUDGET = 160
OUT = 'deck-samples'
LOCALES = ('en', 'ru', 'uz')
# None is a deck with no design: Cambria and Calibri on the classic drawers. Then Noto Serif in classic,
# compositions, Noto Sans, a classic in Corbel. The first is what the customers' path is compared on, the last wait for the budget.
DESIGNS = (None, 'boardroom', 'treetop', 'grotesk', 'midnight', 'forest')
KINDS = ('bullets', 'two_column', 'cards', 'table', 'stats', 'process', 'timeline', 'quote')
OURS = ('Carlito', 'Caladea', 'LiberationSans')
# What LibreOffice stands in on a customer's path, as PR #37's probe printed it in this image.
TODAY = ('NotoSans', 'NotoSerif')
VENDORED = (*OURS, *TODAY)


def say(*parts):
    print('DECK-FONTS', *parts, flush=True)


def fonts_in(path):
    """The fonts a PDF embeds, as it names them, without the subset's prefix."""
    from pypdf import PdfReader
    names = set()
    for page in PdfReader(path).pages:
        for font in page['/Resources'].get('/Font', {}).values():
            names.add(str(font.get_object()['/BaseFont']).lstrip('/').split('+')[-1])
    return sorted(names)


def family(name):
    return name.replace(' ', '').split('-')[0]


def problems(fonts, design, locale, deck_faces):
    """What is not as this step expects of one PDF: `deck_faces`, whether the deck's faces were asked for."""
    families = {family(name) for name in fonts}
    if not families:
        return ['no fonts']
    if not deck_faces:
        found = [f'{name} reached a customer\'s path' for name in sorted(families & set(OURS))]
        found += [f'{name} is new on a customer\'s path' for name in sorted(families - set(VENDORED))]
        return found + [f'{name} is gone from a customer\'s path' for name in TODAY if name not in families]
    found = [f'{name} is not ours' for name in sorted(families - set(VENDORED))]
    if design is None:
        found += [f'no {name}' for name in ('Carlito', 'Caladea') if name not in families]
        # A letter Caladea lacks: every Russian heading. Uzbek in Latin needs none of it.
        if (locale == 'ru') != ('NotoSerif' in families):
            found.append('Noto Serif ' + ('missing from Cyrillic headings' if locale == 'ru' else 'with no Cyrillic'))
    return found


def sample_deck(locale):
    from apps.studio.variants import fixtures
    sections = [{**fixtures.section('statement', 1, locale), 'layout': 'cover', 'id': 's0'}]
    sections += [{**fixtures.section(kind, fixtures.RANGES[kind][1], locale), 'id': f's{number}'} for number, kind in enumerate(KINDS, 1)]
    return {'title': sections[0]['heading'], 'questions': [], 'citations': [], 'sections': sections}


def draw(design, locale, path):
    from apps.studio.slides import render_pptx
    style = {'brand_name': 'Acme Studio', **({'deck_design': design} if design else {'accent': '#255E49'})}
    render_pptx(sample_deck(locale), path, locale=locale, style=style)


def convert(source, folder, seconds, deck_faces):
    from processors.sandbox import execute_sandbox
    result = execute_sandbox('convert.pptx_to_pdf', [source], {}, folder, timeout=seconds + 10, office_timeout=seconds, deck_fonts=deck_faces)
    return result['artifacts'][0]['path']


def one(out, scratch, design, locale, deck_faces, left, *, draw=draw, convert=convert, fonts_in=fonts_in):
    """One conversion's line, with its files kept beside the others: True when it came out as expected."""
    name = f'{design or "no-design"}-{locale}'
    folder = Path(tempfile.mkdtemp(prefix='pdf-', dir=scratch))
    deck = out / f'{name}.pptx'
    if not deck.exists():
        draw(design, locale, deck)
    began = time.monotonic()
    pdf = convert(deck, folder, int(min(60, left())), deck_faces)
    fonts = fonts_in(pdf)
    wrong = problems(fonts, design, locale, deck_faces)
    say(name, 'deck faces' if deck_faces else 'customer path', f'{time.monotonic() - began:.1f} s:', ', '.join(fonts), '| UNEXPECTED: ' + '; '.join(wrong) if wrong else '| as expected')
    shutil.move(pdf, out / f'{name}{"" if deck_faces else "-customer-path"}.pdf')
    return not wrong


def main(root=None, budget=BUDGET, **tools):
    began = time.monotonic()
    left = lambda: began + budget - time.monotonic()
    done, good = 0, 0
    try:
        if not tools:
            os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
            sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
            import django
            django.setup()
        base = Path(root or os.environ.get('PRIVATE_STORAGE_ROOT') or tempfile.gettempdir()).resolve() / 'scratch'
        out, scratch = base / OUT, base / f'{OUT}-work'
        for folder in (out, scratch):
            shutil.rmtree(folder, ignore_errors=True)
            folder.mkdir(parents=True, mode=0o700)
        runs = [(DESIGNS[0], locale, deck_faces) for locale in LOCALES for deck_faces in (True, False)]
        runs += [(design, locale, True) for design in DESIGNS[1:] for locale in LOCALES]
        for design, locale, deck_faces in runs:
            if left() < 20:
                say('out of budget before', design, locale)
                break
            done += 1
            try:
                good += one(out, scratch, design, locale, deck_faces, left, **tools)
            except Exception:
                say(design, locale, 'failed:', traceback.format_exc(limit=1).replace('\n', ' ')[-300:])
        shutil.rmtree(scratch, ignore_errors=True)
        say(f'{good} of {done} as expected; files in', out)
    except Exception:
        say('stopped early:', traceback.format_exc(limit=2).replace('\n', ' ')[-400:])
    return 0


if __name__ == '__main__':
    sys.exit(main())
