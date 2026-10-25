"""Check a layout's variants and draw them, while designing or reviewing one.

    python -m apps.studio.variants.bench cards                # check every cards variant
    python -m apps.studio.variants.bench cards --only orbit,ladder --sheet /tmp/cards.png
    python -m apps.studio.variants.bench cards --module cards_2 --sheet /tmp/cards.png --quick

Each variant is drawn alone on a slide, filled to its layout's guide
(fixtures.py) for every count it is drawn for, in English, Russian and
Uzbek, then in the dark and bold themes with accents that strain contrast,
and inside two other compositions. A run fails when the variant:

* cut a word or set its list well below the deck's size (it would never be
  chosen for that content — variants.choose passes it over);
* set running text below 12 pt, or any text below 9 pt;
* drew outside the frame (kit.FRAME), or fell back to another layout;
* left text hard to read, on a picture, across a line, overlapping other
  text or off the slide (compositions.check).

`--sheet` writes a contact sheet: each variant in a row, filled in English
(light), in Russian (dark), briefly in Uzbek (bold), and in the card
composition.
"""
import argparse
import contextlib
import tempfile
from pathlib import Path

from pptx import Presentation
from pptx.util import Emu

from . import CLASSIC, KINDS, VARIANTS, get, load, load_module
from . import fixtures
from .kit import FOOT, FRAME

THEMES = ('light', 'dark', 'bold')
# A dark accent, a mid-tone one and a pale one, each with a second colour.
ACCENTS = (('#1F3A68', '#E0A458'), ('#D94A26', '#2F80ED'), ('#F4D35E', '#2A9D8F'))
COMPOSITIONS = ('card', 'sidebar', 'frame')
EDGE = 0.02


@contextlib.contextmanager
def _design(theme, accent, secondary, composition, bold):
    from .. import deck_designs
    key = f'_bench_{composition}_{theme}_{accent.lstrip("#")}_{int(bold)}'
    deck_designs.DESIGNS[key] = {**deck_designs._design(accent, secondary, theme, 'Georgia', 'Calibri', 'bench',
                                                        bold=bold, composition=composition), 'category': 'bench'}
    try:
        yield key
    finally:
        deck_designs.DESIGNS.pop(key, None)


def render(variant_id, section, path, *, locale='en', theme='light', accent=ACCENTS[0], composition='classic',
           bold=False, photo=None):
    """Draw `section` with the variant forced on a one-slide deck at `path`; (result, record)."""
    from ..compositions.sample import photo as sample_photo
    from ..slides import render_pptx
    chosen = get(variant_id)
    original, record = chosen.draw, {}

    def recording(ctx, section, lines):
        start = len(ctx.slide.shapes)
        original(ctx, section, lines)
        record.update(start=start, end=len(ctx.slide.shapes), shortened=ctx.shortened, squeezed=ctx.squeezed,
                      size=ctx.size)
    photo = chosen.kind.startswith('image') if photo is None else photo
    chosen.draw = recording
    try:
        with _design(theme, accent[0], accent[1], composition, bold) as key:
            result = render_pptx({'title': 'Bench', 'questions': [], 'citations': [],
                                  'sections': [{**section, '_variant': variant_id}]},
                                 Path(path), locale=locale, style={'deck_design': key, 'brand_name': 'Acme Studio'},
                                 photos={'s1': sample_photo()} if photo else None)
    finally:
        chosen.draw = original
    return result, record


def _inches(value):
    return Emu(value or 0).inches


def faults(path, result, record, variant_id, *, fit=True):
    """What is wrong with one rendered bench slide, as short lines."""
    from ..compositions.check import problems
    kind = variant_id.split('.')[0]
    found = []
    drawn = result['metadata']['layouts'][0]
    if drawn != kind:
        return [f'fell back to {drawn}']
    if not record:
        return ['the variant was not drawn']
    if fit and record['shortened']:
        found.append('cut text')
    if fit and record['squeezed']:
        found.append(f'list squeezed below {record["size"] - 2:.1f} pt')
    slide = Presentation(str(path)).slides[0]
    shapes = list(slide.shapes)
    for shape in shapes[record['start']:record['end']]:
        left, top = _inches(shape.left), _inches(shape.top)
        right, bottom = left + _inches(shape.width), top + _inches(shape.height)
        if (left < FRAME[0] - EDGE or top < FRAME[1] - EDGE or right > FRAME[0] + FRAME[2] + EDGE
                or bottom > FOOT + EDGE):
            name = repr(shape.text_frame.text[:24]) if shape.has_text_frame and shape.text_frame.text else shape.name
            found.append(f'{name} outside the frame at ({left:.2f}, {top:.2f})-({right:.2f}, {bottom:.2f})')
        if not shape.has_text_frame:
            continue
        if fit and '…' in shape.text_frame.text:
            found.append(f'{shape.text_frame.text[:24]!r} ends in an ellipsis')
        for paragraph in shape.text_frame.paragraphs:
            for run in paragraph.runs:
                size = run.font.size.pt if run.font.size else 18
                if len(run.text) > 40 and size < 12:
                    found.append(f'{run.text[:24]!r} at {size} pt (running text needs 12)')
                elif size < 9:
                    found.append(f'{run.text[:24]!r} at {size} pt (nothing below 9)')
    found += [problem.split(': ', 1)[-1] for problem in problems(path, result['metadata']['layouts'])]
    return found


def _counts(chosen):
    low, high = fixtures.RANGES[chosen.kind]
    if chosen.counts:
        low, high = max(low, chosen.counts[0]), min(high, chosen.counts[1])
    return [n for n in range(low, high + 1)
            if chosen.holds(fixtures.section(chosen.kind, n), _lines(fixtures.section(chosen.kind, n)))]


def _lines(section):
    from .. import layouts
    from ..slides import bullets_of
    lines, _ = bullets_of(section['body'])
    if not lines and section.get('items'):
        lines, _ = bullets_of('\n'.join(layouts.as_lines(section)))
    return lines


def check(variant_id, *, quick=False, folder=None):
    """Every fault of one variant over the bench's runs: ['condition: fault', ...]."""
    chosen = get(variant_id)
    counts = _counts(chosen)
    if not counts:
        return ['holds none of its layout\'s guide content']
    found = []
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(folder or scratch) / 'bench.pptx'

        def run(label, section, fit=True, **options):
            result, record = render(variant_id, section, path, **options)
            found.extend(f'{label}: {fault}' for fault in faults(path, result, record, variant_id, fit=fit))

        for n in (counts if not quick else sorted({counts[0], counts[-1]})):
            for locale in fixtures.LOCALES:
                run(f'{n} {locale}', fixtures.section(chosen.kind, n, locale), locale=locale,
                    bold=locale == 'ru')
        widest = counts[-1]
        for theme in ('dark', 'bold'):
            for accent in (ACCENTS if not quick else ACCENTS[1:2]):
                run(f'{widest} {theme} {accent[0]}', fixtures.section(chosen.kind, widest), theme=theme,
                    accent=accent)
        for composition in (COMPOSITIONS if not quick else COMPOSITIONS[:1]):
            run(f'{widest} {composition}', fixtures.section(chosen.kind, widest), composition=composition,
                accent=('#5B2A86', '#E0A458'))
        run(f'{counts[0]} brief', fixtures.light(chosen.kind, counts[0]), fit=False)
    return found


def sheet(variant_ids, out, width=480, each=None):
    """A contact sheet: one row per variant, four conditions across; `each`, a folder for every slide alone."""
    from ..compositions import preview
    images, labels = [], []
    if each:
        Path(each).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'sheet.pptx'
        for variant_id in variant_ids:
            chosen = get(variant_id)
            counts = _counts(chosen) or [fixtures.RANGES[chosen.kind][0]]
            runs = (
                ('en light', fixtures.section(chosen.kind, counts[-1], 'en'), {}),
                ('ru dark', fixtures.section(chosen.kind, counts[-1], 'ru'),
                 {'locale': 'ru', 'theme': 'dark', 'accent': ACCENTS[1], 'bold': True}),
                ('uz bold brief', fixtures.light(chosen.kind, counts[0], 'uz'),
                 {'locale': 'uz', 'theme': 'bold', 'accent': ACCENTS[2]}),
                (f'en card {counts[len(counts) // 2]}', fixtures.section(chosen.kind, counts[len(counts) // 2], 'en'),
                 {'composition': 'card', 'accent': ('#5B2A86', '#E0A458')}),
            )
            for label, section, options in runs:
                render(variant_id, section, path, **options)
                images.append(preview.slide_images(path, width=width)[0])
                labels.append(f'{variant_id} · {label}')
                if each:
                    preview.slide_images(path, width=1280)[0].save(
                        Path(each) / f'{variant_id}-{label.replace(" ", "_")}.png')
    preview.contact_sheet(images, columns=4, labels=labels).save(out)
    return out


def ids(kind, module=None, only=None):
    if module:
        # Only this module: another of the same layout may be half-written.
        if not load_module(module):
            raise SystemExit(f'{module} does not import (see the traceback above)')
        pool = VARIANTS.get(kind, {})
    else:
        pool = load(kind)
    names = [name for name in sorted(pool) if name != CLASSIC]
    if module:
        names = [name for name in names if pool[name].draw.__module__.rsplit('.', 1)[-1] == module]
    if only:
        names = [name for name in names if name in only]
    return [f'{kind}.{name}' for name in names]


def main(argv=None):
    import os
    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('kind', choices=KINDS)
    parser.add_argument('--module', help='only the variants defined in this module, e.g. cards_2')
    parser.add_argument('--only', help='comma-separated variant names')
    parser.add_argument('--sheet', help='write a contact sheet PNG here')
    parser.add_argument('--width', type=int, default=480, help='width of each slide on the sheet')
    parser.add_argument('--each', help='also write every sheet slide alone, 1280 wide, into this folder')
    parser.add_argument('--quick', action='store_true', help='fewest counts, one accent, one composition')
    parser.add_argument('--classic', action='store_true', help='check the classic drawer too')
    options = parser.parse_args(argv)
    chosen = ids(options.kind, options.module, set(options.only.split(',')) if options.only else None)
    if options.classic:
        chosen = [f'{options.kind}.{CLASSIC}'] + chosen
    if not chosen:
        parser.error('no variants match')
    failed = 0
    for variant_id in chosen:
        found = check(variant_id, quick=options.quick)
        failed += bool(found)
        print(f'{"FAIL" if found else "ok  "} {variant_id}')
        for line in found[:40]:
            print(f'       {line}')
        if len(found) > 40:
            print(f'       ... {len(found) - 40} more')
    if options.sheet:
        print('sheet:', sheet(chosen, options.sheet, options.width, options.each))
    print(f'{len(chosen) - failed}/{len(chosen)} variants pass')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
