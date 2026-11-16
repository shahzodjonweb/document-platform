"""Draw a deck category as a customer would get it, from invented sample content, to look at beside its mock-up.

    python -m apps.studio.categories.sample --deck slides.himoya --lengths 6,10,15 --locale uz --case topic_only --out /tmp/himoya
    python -m apps.studio.categories.sample --deck slides.himoya --locale uz,ru,en --case figures,topic_only --out /tmp/himoya

For each length, language and case the deck goes the way a job takes it,
with the sample standing in for the model: the draft is seeded from the
entry's slots (skeleton.seed, the cues read from the sample's message), the
sample's slides are put on those slots, title_lines.apply sets the dictated
cover lines, finish.apply dresses, grounds and guards, and render_pptx draws
it in the entry's default look with finish.pins on the first render. Each
run writes the .pptx and a contact sheet of its slides (drawn as
variants/bench.py draws its sheets, with compositions/preview, so no
LibreOffice is needed), and prints what finish took out, which pins gave way
and which slides were shortened.

Sample content is invented: no real person, organisation or customer text.
It is read from, in order, `--sample FILE`, `categories/samples/<entry id>/<case>.json`
(the entry's own samples, C2s), and `tests/fixtures/categories/deck_<name>_<case>.json`
(this package's test fixtures, `<name>` the entry id without `slides.`, dots
as underscores). A file is:

    {"entry": "slides.himoya", "case": "figures",
     "prompt": {"uz": "...", "ru": "...", "en": "..."},       # the customer's one message
     "title":  {"uz": "...", "ru": "...", "en": "..."},       # the deck's title, as the model returns it
     "slots":  {"<part id>": [{"uz": {section}, "ru": {section}, "en": {section}}, ...]}}

where a section holds any of heading, body, notes, items, columns and layout
(a layout the slot does not allow is put back by finish, as a model's is). A
repeating slot takes its listed instances in turn and, past them, a slot
with nothing listed is drawn as the honest form a model is told to write for
a slot it has no material for. With no file at all every slot is such a form,
which is said, so a new entry can be looked at before its samples exist.
"""
import argparse
import json
from pathlib import Path

from .catalogue import LOCALES

CASES = ('figures', 'topic_only')
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def sample_path(entry_id, case, explicit=None):
    """The sample file for this entry and case, or None when there is none."""
    if explicit:
        return Path(explicit)
    for path in (HERE / 'samples' / entry_id / f'{case}.json',
                 ROOT / 'tests' / 'fixtures' / 'categories'
                 / f"deck_{entry_id.removeprefix('slides.').replace('.', '_')}_{case}.json"):
        if path.is_file():
            return path
    return None


def load(entry_id, case, explicit=None):
    """The sample as a dict ({} when there is none), checked to be for this entry."""
    path = sample_path(entry_id, case, explicit)
    if path is None:
        return {}
    sample = json.loads(path.read_text(encoding='utf-8'))
    if sample.get('entry', entry_id) != entry_id:
        raise SystemExit(f'{path} is a sample of {sample["entry"]}, not {entry_id}')
    return sample


def _form(part, locale):
    """The honest form a model writes for a slot it has nothing for: its heading, ruled lines."""
    from .finish import BLANK, FORM_LINES
    heading = (part.get('heading') or {}).get(locale) or BLANK
    return {'heading': heading, 'body': '\n'.join(BLANK for _ in range(FORM_LINES))}


def draft(entry, sample, locale, length):
    """(data, content): a draft of `length` slides as the domain seeds it, and the sample's answer on its slots."""
    from . import skeleton
    prompt = (sample.get('prompt') or {}).get(locale) or entry.label(locale)
    data = {'options': {'category': entry.id, 'pages': length}, 'prompt': prompt, 'source_text': '',
            'source_ids': [], 'excerpts': [], 'output_locale': locale, 'output_format': 'pptx'}
    cues = skeleton.cues_of(data)
    data['content'] = {'title': '', 'sections': skeleton.seed(entry, length, cues), 'questions': [], 'citations': []}
    given = sample.get('slots') or {}
    sections = []
    for use, seeded in zip(skeleton.parts(entry, length, cues), data['content']['sections']):
        listed = given.get(use.part['id']) or []
        written = (listed[use.instance - 1].get(locale) if use.instance <= len(listed) else None) \
            or _form(use.part, locale)
        sections.append({**seeded, **{key: value for key, value in written.items()
                                      if key in ('heading', 'body', 'notes', 'items', 'columns', 'layout')}})
    title = (sample.get('title') or {}).get(locale) or sections[0].get('heading') or entry.label(locale)
    return data, {'title': title, 'sections': sections, 'questions': [], 'citations': []}


def run(entry, sample, case, locale, length, out, *, design=None, width=480):
    """Draw one deck into `out`; a summary of it as a dict."""
    from .. import title_lines
    from ..compositions import preview
    from ..slides import render_pptx
    from . import finish, skeleton
    data, content = draft(entry, sample, locale, length)
    content = title_lines.apply(data, content)
    codes = []
    content, warnings = finish.apply(data, content, file_names=[], codes=codes)
    pinned = finish.pins(data, content)
    design = design or entry.look['designs'][0]
    stem = f'{entry.id}-{case}-{locale}-{length}'
    deck = render_pptx(content, Path(out) / f'{stem}.pptx', locale, 'user_document', style={'deck_design': design},
                       pins=pinned)
    metadata = deck['metadata']
    slots = [use.part['id'] for use in skeleton.parts(entry, length, skeleton.cues_of(data))]
    labels = [f"{section['id']} {slot} · {variant or kind}" for section, slot, kind, variant
              in zip(content['sections'], slots, metadata['layouts'], metadata['variants'])]
    images = preview.slide_images(deck['path'], width=width)
    preview.contact_sheet(images, columns=5 if length > 8 else 3, labels=labels).save(Path(out) / f'{stem}.png')
    return {'stem': stem, 'slides': deck['page_count'], 'design': metadata['design'], 'warnings': warnings,
            'codes': codes, 'repinned': metadata['repinned'], 'shortened': [item['id'] for item in metadata['shortened']]}


def _listed(text, allowed, name):
    values = [value.strip() for value in text.split(',') if value.strip()]
    wrong = [value for value in values if allowed is not None and value not in allowed]
    if wrong or not values:
        raise SystemExit(f'--{name}: {", ".join(wrong) or "nothing"} is not one of {", ".join(allowed)}')
    return values


def main(argv=None):
    import os
    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()
    from . import catalogue
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--deck', required=True, help='a deck entry id, e.g. slides.himoya')
    parser.add_argument('--lengths', default='6,10,15', help='comma-separated slide counts')
    parser.add_argument('--locale', default='uz', help='uz, ru, en, or several comma-separated')
    parser.add_argument('--case', default='figures', help='figures, topic_only, or both comma-separated')
    parser.add_argument('--out', required=True, help='the folder the decks and sheets are written to')
    parser.add_argument('--sample', help='a sample file to use instead of the entry’s own (one case)')
    parser.add_argument('--design', help='draw in this deck design instead of the entry’s default look')
    parser.add_argument('--width', type=int, default=480, help='width of each slide on the sheet')
    options = parser.parse_args(argv)
    entry = catalogue.get(options.deck)
    if entry is None or entry.service != 'slides':
        parser.error(f'{options.deck} is not a deck entry of the catalogue')
    lengths = [int(value) for value in _listed(options.lengths, None, 'lengths')]
    if any(not entry.length['min'] <= value <= entry.length['max'] for value in lengths):
        parser.error(f'{entry.id} takes {entry.length["min"]} to {entry.length["max"]} slides')
    out = Path(options.out)
    out.mkdir(parents=True, exist_ok=True)
    failed = 0
    for case in _listed(options.case, CASES, 'case'):
        sample = load(entry.id, case, options.sample)
        if not sample:
            print(f'{entry.id} has no {case} sample: every slot is drawn as a blank form')
        for locale in _listed(options.locale, LOCALES, 'locale'):
            for length in lengths:
                made = run(entry, sample, case, locale, length, out, design=options.design, width=options.width)
                wrong = made['slides'] != length
                failed += wrong
                print(f"{'FAIL' if wrong else 'ok  '} {made['stem']}: {made['slides']} slides in {made['design']}"
                      f"; took out {', '.join(made['codes']) or 'nothing'}"
                      f"; repinned {', '.join(made['repinned']) or 'none'}"
                      f"; shortened {', '.join(made['shortened']) or 'none'}")
    print(f'decks and sheets: {out}')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
