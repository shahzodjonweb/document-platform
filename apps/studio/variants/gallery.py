"""Every variant of every layout on contact sheets, for reviewing the whole catalogue.

    python -m apps.studio.variants.gallery /tmp/variants             # one sheet per layout
    python -m apps.studio.variants.gallery /tmp/variants cards stats --theme dark --locale ru

Each slide is a variant filled to its layout's guide at a middle count, the
classic drawer first, in one sample design.
"""
import argparse
import tempfile
from pathlib import Path

from . import CLASSIC, KINDS, load
from . import bench, fixtures


def sheet(kind, out, *, theme='light', locale='en', accent=bench.ACCENTS[0], composition='classic', width=640,
          columns=3):
    from ..compositions import preview
    pool = load(kind)
    names = [CLASSIC] + sorted(name for name in pool if name != CLASSIC)
    images, labels = [], []
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'gallery.pptx'
        for name in names:
            variant_id = f'{kind}.{name}'
            counts = bench._counts(pool[name]) or [fixtures.RANGES[kind][0]]
            count = counts[len(counts) // 2]
            bench.render(variant_id, fixtures.section(kind, count, locale), path, locale=locale, theme=theme,
                         accent=accent, composition=composition)
            images.append(preview.slide_images(path, width=width)[0])
            labels.append(f'{variant_id} · {count}')
    preview.contact_sheet(images, columns=columns, labels=labels).save(out)
    return out, len(names) - 1


def main(argv=None):
    import os
    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('folder')
    parser.add_argument('kinds', nargs='*', choices=[[]] + list(KINDS), default=[])
    parser.add_argument('--theme', default='light', choices=bench.THEMES)
    parser.add_argument('--locale', default='en', choices=fixtures.LOCALES)
    parser.add_argument('--composition', default='classic')
    options = parser.parse_args(argv)
    folder = Path(options.folder)
    folder.mkdir(parents=True, exist_ok=True)
    total = 0
    for kind in options.kinds or KINDS:
        out, count = sheet(kind, folder / f'{kind}-{options.theme}-{options.locale}.png', theme=options.theme,
                           locale=options.locale, composition=options.composition)
        total += count
        print(f'{kind}: {count} variants -> {out}')
    print(f'{total} variants')


if __name__ == '__main__':
    main()
