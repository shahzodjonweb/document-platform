"""Draw category papers from invented sample content, to look at beside their mock-ups and to check (6.5).

    python -m apps.studio.paper.sample --sheet OUT.png [--template ID] [--locale uz|ru|en] [--case full|blank|long]
    python -m apps.studio.paper.sample --blocks OUT.png [--locale uz]
    python -m apps.studio.paper.sample --check TEMPLATE [--pages DIR] [--locale ...] [--case ...]

`--sheet` tiles papers, one row each with its pages side by side and a line
under it (template, case, language, pages, ladder step, codes). With
`--template` it draws that template in every case and language; without it,
every template that has samples, in Uzbek and the `full` case. `--locale` and
`--case` narrow either (comma-separated lists work). `--mocks DIR` (the
research folder) puts each template's mock-up (its `mock` path) at the start of
its rows.

`--blocks` tiles the block sheet: every sample a block module lists in its
`SAMPLES`, each drawn alone in its own frame, under its block's name.

`--check` draws a template's samples and prints what `check.problems` finds,
with `--pages DIR` writing every page as a PNG; it exits 1 when anything is
found.

A paper is drawn as a job draws it once the model's answer is finished: the
sample's content is handed to `render_paper` with its template, the quoted
pages and the cues. So a sample is finished content (categories.finish has
already run): facts verified, fixed headings written.

Sample files. `paper/samples/<template id>/<case>.json` (the family package
writes them; `--samples DIR` or `root=` reads another folder):

    {"template": "official_ariza", "case": "full",
     "entry": "pdf.xat.ariza",     # optional: the template's first entry
     "pages": 1,                   # optional: the quote; else the entry's default length
     "cues": ["sources"],          # optional: the draft's cues (cue: predicates)
     "day": "2026-09-15",          # optional: the day a clock field reads; else SAMPLE_DAY
     "uz": {content}, "ru": {content}, "en": {content}}

where a content is `{"title", "sections", "questions"}` as render_paper takes
it; `"facts": {"<field id>": "<value>"}` in a content is written as its facts
section. The three cases (architecture 6.5):

- `full`: every fact given;
- `blank`: no fact, so every blank is drawn. Without its own file it is the
  full sample with its facts taken out;
- `long`: more than the page rule holds. Without its own file it is the full
  sample with prose for its rule's pages and a half (fixed) or its quote and
  a page and a half (flow, count), shared among its prose parts in
  proportion to their length and each part still one paragraph, and its rows
  and questions three times over (up to their part's and the paper's
  bounds): a fixed paper takes its one page more, a flow paper runs past its
  quote and says so, a count paper is cut.

Block samples. A block module's `SAMPLES` is a list of dicts (or a dict of
lists by block name, or a function returning either); each draws one block.

A module that exports `sample_paper(locale, samples) -> (entry, template,
content)` draws its own: its samples name parts, fields and labels of the
entry and template it makes (R1's core blocks do this), so each sample is
drawn as `render_paper(content, path, locale, entry=entry,
template=template, pages=1)` of `sample_paper(locale, [sample])`, under its
`name` or `case`. A module without it gives each sample whole:

    {"block": "signature_row", "name": "date, signature, name",
     "params": {...},                  # the placement's parameters
     "section": {...},                 # the written part's section, if it draws one
     "part": "signature" | {...},      # a part id of the entry, or a part as a dict
     "fields": ["signer_name"],        # the placement's fields (else the part's)
     "facts": {"signer_name": "..."},  # verified values
     "field_defs": [{...}],            # fields as the catalogue writes them, when there is no entry
     "template": "official_ariza",     # optional: its page, type and labels; else a plain A4 frame
     "entry": "pdf.xat.ariza",         # optional: its fields and parts; else the template's first entry
     "labels": {"key": {"uz": ..., "ru": ..., "en": ...}},
     "title": "...", "questions": [...], "locale": "uz"}

`section`, `facts`, `title` and `questions`, or any value inside them, may be
given per language as {"uz": ..., "ru": ..., "en": ...}.

Everything in a sample is invented: no real person, organisation or customer text.
"""
import copy
import datetime
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..categories import catalogue
from ..categories.catalogue import LOCALES, PAPER_BOUNDS, Entry
from ..categories.skeleton import FACTS

CASES = ('full', 'blank', 'long')
HERE = Path(__file__).resolve().parent
SAMPLES = HERE / 'samples'
# Clock fields read this day in samples, so a sheet and a test draw the same paper every day.
SAMPLE_DAY = datetime.date(2026, 9, 15)
# The long case runs past the page rule by about this many pages of prose and no further: enough to make the
# paper overflow, not so much that a fixed template with four prose parts is eight pages and fails its own rule.
LONG_FIXED, LONG_FLOW = 0.5, 1.5
# Each prose part grows at least this much, so a sample already past the budget is still longer than its full case.
LONG_GROWTH = 1.5
# Rows and questions three times over, up to their bound.
LONG_ROWS = 3
# A character of body text, taken as this share of the type size wide, sizes what a page of the frame holds.
CHAR_EMS = 0.5
# The block sheet's own page when a sample names no template: A4 with plain margins, one step of serif type.
SHEET = {'id': 'block_sheet', 'name': {'uz': 'Bloklar', 'ru': 'Блоки', 'en': 'Blocks'},
         'page': {'margins_mm': {'left': 20, 'right': 20, 'top': 15, 'bottom': 15}},
         'type': {'face': 'serif', 'ladder': [[11, 15]], 'align': 'left'}, 'page_rule': {'kind': 'flow'},
         'furniture': {'first': 'none', 'later': 'none', 'format': 'n'}, 'labels': {}, 'flow': []}
GREY, INK = '#E6E8EB', '#1A1A1A'


# ---------------------------------------------------------------- samples


def sample_path(template_id, case, root=None):
    """The sample file of a template's case, or None when there is none."""
    path = Path(root or SAMPLES) / template_id / f'{case}.json'
    return path if path.is_file() else None


def templates_with_samples(root=None):
    """The template ids of the catalogue that have a `full` sample, in id order."""
    return [name for name in sorted(catalogue._catalogue().templates) if sample_path(name, 'full', root)]


def _read(path, template_id):
    sample = json.loads(path.read_text(encoding='utf-8'))
    if sample.get('template', template_id) != template_id:
        raise ValueError(f'{path} is a sample of {sample["template"]}, not {template_id}')
    return sample


def _blanked(sample):
    made = copy.deepcopy(sample)
    for locale in LOCALES:
        content = made.get(locale)
        if isinstance(content, dict):
            content.pop('facts', None)
            content['sections'] = [section for section in content.get('sections') or []
                                   if not (isinstance(section, dict) and section.get('id') == FACTS)]
    return made


def page_chars(template):
    """About how many characters of body text one page of the template's frame holds at its first type step."""
    from .page import geometry
    left, bottom, width, height = geometry(template)
    size, leading = template['type']['ladder'][0]
    return int(width / (CHAR_EMS * size)) * int(height / leading)


def long_budget(template, pages):
    """The characters of prose the derived long case gives a paper quoted `pages`: its rule's overflow, sized."""
    from .check import PLAN_CAP
    rule = template['page_rule']
    if rule.get('kind') == 'fixed':
        held = int(rule.get('pages') or pages) + LONG_FIXED
    else:
        held = min(pages + LONG_FLOW, PLAN_CAP)
    return int(held * page_chars(template))


def _grown(body, room):
    """`body` said again, joined by spaces into one paragraph, to about `room` characters, cut after a sentence.

    One paragraph, so the long case tests wrapping, justification and widows
    inside it; cut at a word when no sentence ends in the last fifth.
    """
    room = max(int(room), round(len(body) * LONG_GROWTH))
    text = ' '.join([body] * (-(-room // (len(body) + 1)) + 1))
    sentence = max(text.rfind(mark, len(body), room + 1) for mark in ('. ', '! ', '? '))
    if sentence >= room * 0.8:
        return text[:sentence + 1]
    cut = text.rfind(' ', len(body), room + 1)
    return text[:cut if cut > 0 else room].rstrip(' ,;:')


def _bound(entry, template, section_id, given):
    """How many rows a part's section may hold: its part's and placements' max_items, under the paper's bound."""
    bounds = [PAPER_BOUNDS.items]
    part = entry.part(section_id) if entry is not None else None
    if part is not None:
        bounds.append(part.get('max_items'))
        bounds += [(placement.get('params') or {}).get('max_items') for placement in template.get('flow') or ()
                   if placement.get('part') == part['id']]
    return max(given, min(bound for bound in bounds if isinstance(bound, int) and bound > 0))


def _longer(sample, template):
    """The full sample made the long case (see the module's docstring), for `template`."""
    made = copy.deepcopy(sample)
    entry = catalogue.get(sample.get('entry') or (template.get('entries') or [''])[0])
    pages = int(sample.get('pages') or (entry.length['default'] if entry is not None else 1))
    budget = long_budget(template, pages)
    most = ((entry.raw.get('questions') or {}).get('max') if entry is not None else None) or PAPER_BOUNDS.items
    for locale in LOCALES:
        content = made.get(locale)
        if not isinstance(content, dict):
            continue
        sections = [section for section in content.get('sections') or []
                    if isinstance(section, dict) and section.get('id') != FACTS]
        prose = sum(len(str(section.get('body') or '').strip()) for section in sections)
        for section in sections:
            body = str(section.get('body') or '').strip()
            if body:
                section['body'] = _grown(body, budget * len(body) / prose)
            items = list(section.get('items') or [])
            if items:
                section['items'] = (items * LONG_ROWS)[:_bound(entry, template, section.get('id'), len(items))]
        questions = list(content.get('questions') or [])
        if questions:
            content['questions'] = (questions * LONG_ROWS)[:max(len(questions), min(most, PAPER_BOUNDS.items))]
    return made


def load(template_id, case, root=None):
    """A template's sample of `case`: its own file, else made from `full` (see the module's docstring); {} if none."""
    if case not in CASES:
        raise ValueError(f'{case} is not one of {", ".join(CASES)}')
    path = sample_path(template_id, case, root)
    if path is not None:
        return {**_read(path, template_id), 'case': case}
    full = sample_path(template_id, 'full', root)
    if full is None:
        return {}
    full = _read(full, template_id)
    made = _blanked(full) if case == 'blank' else _longer(full, catalogue.template(template_id))
    return {**made, 'case': case, 'derived': 'full'}


def _facts_section(facts):
    return {'id': FACTS, 'heading': '', 'body': '', 'layout': 'list',
            'items': [{'label': key, 'text': str(value)} for key, value in facts.items()]}


def content_of(sample, locale):
    """The finished content a sample gives in `locale` (a copy), its `facts` shorthand made a facts section."""
    given = sample.get(locale)
    if not isinstance(given, dict):
        raise KeyError(f'the {sample.get("template")} {sample.get("case")} sample has no {locale} content')
    content = copy.deepcopy(given)
    facts = content.pop('facts', None)
    sections = [section for section in content.get('sections') or [] if isinstance(section, dict)]
    if facts:
        sections = [_facts_section(facts)] + [section for section in sections if section.get('id') != FACTS]
    content['sections'] = sections
    content.setdefault('title', '')
    content.setdefault('questions', [])
    return content


@dataclass
class Drawn:
    """One sample drawn: the artifact render_paper returned, the content it drew, and what the checker holds it to."""

    template_id: str
    case: str
    locale: str
    entry: object
    template: dict
    content: dict
    pages: int
    artifact: dict
    expect: dict
    sample: dict

    @property
    def path(self):
        return Path(self.artifact['path'])

    def problems(self):
        from .check import problems
        return problems(self.path, self.expect)

    def note(self):
        """The line under the paper on a sheet: case, language, pages, step and codes."""
        metadata = self.artifact.get('metadata') or {}
        text = f'{self.template_id} · {self.case} · {self.locale} · {self.artifact["page_count"]}p'
        text += f' of {self.pages}' if self.pages else ''
        if metadata.get('fit_step') is not None:
            text += f' · s{metadata["fit_step"]}'
        codes = list(metadata.get('warnings') or ())
        return text + (' · ' + ', '.join(codes) if codes else '')


def draw(template_id, case, locale, folder, *, root=None, day=None):
    """Draw a template's sample of `case` in `locale` into `folder`; a Drawn. KeyError/ValueError when it cannot."""
    from . import render_paper
    from .check import expect_for
    template = catalogue.template(template_id)
    sample = load(template_id, case, root)
    if not sample:
        raise KeyError(f'{template_id} has no samples')
    entry = catalogue.get(sample.get('entry') or template['entries'][0])
    if entry is None:
        raise KeyError(f'the {template_id} sample names {sample.get("entry")}, which is not in the catalogue')
    content = content_of(sample, locale)
    pages = int(sample.get('pages') or entry.length['default'])
    cues = frozenset(sample.get('cues') or ())
    day = day or (datetime.date.fromisoformat(sample['day']) if sample.get('day') else SAMPLE_DAY)
    path = Path(folder) / f'{template_id}-{case}-{locale}.pdf'
    # The engine may hand the content on to the fallback: it draws a copy, so the content checked is the one given.
    artifact = render_paper(copy.deepcopy(content), path, locale, entry=entry, template=template_id, pages=pages,
                            cues=cues, day=day)
    expect = expect_for(artifact, content, entry=entry, template=template, locale=locale, pages=pages, cues=cues,
                        day=day)
    return Drawn(template_id, case, locale, entry, template, content, pages, artifact, expect, sample)


# ---------------------------------------------------------------- pictures


def page_images(path, width):
    """Every page of a PDF as an RGB image `width` pixels wide."""
    import pypdfium2
    document = pypdfium2.PdfDocument(str(path))
    try:
        return [document[index].render(scale=width / 595.27).to_pil().convert('RGB') for index in range(len(document))]
    finally:
        document.close()


def _font(size, bold=True):
    from PIL import ImageFont
    from ..cv import fonts
    return ImageFont.truetype(str(fonts.path('CVSans-Bold' if bold else 'CVSans')), size)


def _mock(template, mocks, width, height):
    if not mocks or not template.get('mock'):
        return None
    path = Path(mocks) / template['mock']
    if not path.is_file():
        return None
    from PIL import Image
    image = Image.open(path).convert('RGB')
    image.thumbnail((width, height))
    return image


def sheet(out, *, templates=None, locales=None, cases=None, root=None, width=260, most=8, mocks=None):
    """A sheet of papers, one row per (template, case, language); see the module's docstring. Returns `out`."""
    from PIL import Image, ImageDraw
    if templates:
        templates = list(templates)
        locales, cases = list(locales or LOCALES), list(cases or CASES)
    else:
        templates = templates_with_samples(root)
        locales, cases = list(locales or ('uz',)), list(cases or ('full',))
    if not templates:
        raise ValueError('no template has samples to draw')
    height = round(width * 841.89 / 595.27)
    label, gap, between = 26, 18, 8
    rows = []
    with tempfile.TemporaryDirectory() as folder:
        for template_id in templates:
            mock = _mock(catalogue.template(template_id), mocks, width, height)
            for case in cases:
                for locale in locales:
                    drawn = draw(template_id, case, locale, folder, root=root)
                    images = page_images(drawn.path, width)
                    note = drawn.note() + (f' · +{len(images) - most} more' if len(images) > most else '')
                    rows.append((([mock] if mock else []) + images[:most], note))
        columns = max(len(images) for images, _ in rows)
        canvas = Image.new('RGB', (gap + columns * (width + between) + gap, gap + len(rows) * (height + label + gap)),
                           GREY)
        pen = ImageDraw.Draw(canvas)
        font = _font(14)
        for row, (images, note) in enumerate(rows):
            y = gap + row * (height + label + gap)
            for column, image in enumerate(images):
                canvas.paste(image, (gap + column * (width + between), y))
            pen.text((gap, y + height + 5), note, fill=INK, font=font)
    canvas.save(out, 'PNG', optimize=True)
    return out


# ---------------------------------------------------------------- the block sheet


def _localised(value, locale):
    """`value` with everything given per language ({"uz", "ru", "en"} and nothing else) in `locale`, at any depth."""
    if isinstance(value, dict) and value and set(value) <= set(LOCALES):
        return _localised(value.get(locale) or value.get('en') or next(iter(value.values())), locale)
    if isinstance(value, dict):
        return {key: _localised(item, locale) for key, item in value.items()}
    if isinstance(value, list):
        return [_localised(item, locale) for item in value]
    return value


def block_samples(module):
    """A block module's SAMPLES as a list of dicts, each with its `block`."""
    found = getattr(module, 'SAMPLES', None)
    if callable(found):
        found = found()
    if isinstance(found, dict):
        found = [{'block': name, **item} for name, items in found.items()
                 for item in (items if isinstance(items, (list, tuple)) else [items])]
    return [item for item in found or () if isinstance(item, dict) and item.get('block')]


def _sample_entry(sample, template):
    """The entry a block sample is drawn for: the one it names, the template's first, else one made of its fields."""
    entry = catalogue.get(sample['entry']) if sample.get('entry') else None
    if entry is None and template.get('entries'):
        entry = catalogue.get(template['entries'][0])
    if entry is not None:
        return entry
    part = sample.get('part') if isinstance(sample.get('part'), dict) else None
    raw = {'id': 'block_sample', 'labels': {locale: 'Namuna' for locale in LOCALES},
           'fields': list(sample.get('field_defs') or ()), 'parts': [part] if part else [], 'templates': [],
           'length': {'unit': 'pages', 'mode': 'fixed', 'target': 'ceiling', 'default': 1, 'min': 1, 'max': 1}}
    return Entry('block_sample', 'pdf', catalogue.FEATURES['pdf'], 'draft', raw)


def draw_block(sample, locale, folder, index=0):
    """Draw one block sample alone on a page; (path to its PDF, its warnings)."""
    from . import page, registry
    from .ctx import Ctx, Place
    template = copy.deepcopy(catalogue.template(sample['template']) if sample.get('template') else SHEET)
    template['labels'] = {**(template.get('labels') or {}), **(sample.get('labels') or {})}
    entry = _sample_entry(sample, template)
    locale = sample.get('locale') or locale
    part = sample.get('part')
    if isinstance(part, str):
        part = entry.part(part)
    section = _localised(sample.get('section'), locale)
    facts = _localised(sample.get('facts') or {}, locale)
    sections = ([_facts_section(facts)] if facts else []) + ([dict(section)] if isinstance(section, dict) else [])
    content = {'title': _localised(sample.get('title'), locale) or '', 'sections': sections,
               'questions': _localised(sample.get('questions'), locale) or []}
    left, bottom, width, height = page.geometry(template)
    ctx = Ctx(content=content, entry=entry, template=template, locale=locale, step=0, pages=1, width=width,
              frame_height=height, day=SAMPLE_DAY)
    fields = tuple(sample.get('fields') or (part or {}).get('fields') or ())
    place = Place(sample['block'], section if isinstance(section, dict) else None, part, fields,
                  dict(sample.get('params') or {}))
    story = registry.draw(ctx, place)
    path = Path(folder) / f'block-{index}.pdf'
    path.write_bytes(page.build(ctx, story).data)
    return path, list(ctx.warnings)


def _cropped(image, pad=12):
    """A page cut to the band of it that is drawn on, full width, so a block's place across the page still shows."""
    from PIL import Image, ImageChops
    box = ImageChops.difference(image, Image.new('RGB', image.size, 'white')).getbbox()
    if not box:
        return image.crop((0, 0, image.width, min(image.height, 60)))
    return image.crop((0, max(0, box[1] - pad), image.width, min(image.height, box[3] + pad)))


def block_modules():
    """(name, module or the exception it raised on import) of every block module, in name order."""
    import importlib
    import pkgutil
    from . import blocks
    found = []
    for module_info in pkgutil.iter_modules(blocks.__path__):
        if module_info.name.startswith('_'):
            continue
        try:
            found.append((module_info.name, importlib.import_module(f'{blocks.__name__}.{module_info.name}')))
        except Exception as error:
            found.append((module_info.name, error))
    return found


def tile_name(module_name, sample):
    """The line over a block sample's tile: module, block, and the sample's `name` (R1 calls it `case`)."""
    called = sample.get('name') or sample.get('case')
    return f"{module_name}.{sample['block']}" + (f' · {called}' if called else '')


def draw_own(module, sample, locale, folder, index=0):
    """Draw one sample of a module that makes its own paper (`sample_paper`); (path to its PDF, its warnings)."""
    from . import render_paper
    entry, template, content = module.sample_paper(locale, [sample])
    path = Path(folder) / f'block-{index}.pdf'
    artifact = render_paper(content, path, locale, entry=entry, template=template, pages=1, day=SAMPLE_DAY)
    return Path(artifact['path']), list((artifact.get('metadata') or {}).get('warnings') or ())


def blocks_sheet(out, *, locale='uz', width=760, columns=2, modules=None):
    """The block sheet: every SAMPLES entry of every block module (or `modules`, as (name, module)), drawn alone."""
    from PIL import Image, ImageDraw
    tiles = []
    with tempfile.TemporaryDirectory() as folder:
        for module_name, module in (block_modules() if modules is None else modules):
            if isinstance(module, Exception):
                tiles.append((None, f'{module_name}: does not import ({type(module).__name__})'))
                continue
            own = callable(getattr(module, 'sample_paper', None))
            for sample in block_samples(module):
                name = tile_name(module_name, sample)
                try:
                    path, warnings = (draw_own(module, sample, locale, folder, len(tiles)) if own
                                      else draw_block(sample, locale, folder, len(tiles)))
                except Exception as error:
                    tiles.append((None, f'{name}: failed ({type(error).__name__})'))
                    continue
                images = page_images(path, width)
                image = _cropped(images[0])
                tiles.append((image, name + (' · ' + ', '.join(warnings) if warnings else '')
                              + (f' · {len(images)} pages' if len(images) > 1 else '')))
    if not tiles:
        raise ValueError('no block module lists SAMPLES')
    label, gap = 24, 16
    rows = [tiles[start:start + columns] for start in range(0, len(tiles), columns)]
    heights = [max((image.height if image else 40) for image, _ in row) + label for row in rows]
    canvas = Image.new('RGB', (gap + columns * (width + gap), gap + sum(height + gap for height in heights)), GREY)
    pen = ImageDraw.Draw(canvas)
    font = _font(13)
    y = gap
    for row, height in zip(rows, heights):
        for column, (image, note) in enumerate(row):
            x = gap + column * (width + gap)
            pen.text((x, y), note, fill=INK if image else '#B00020', font=font)
            if image:
                canvas.paste(image, (x, y + label))
        y += height + gap
    canvas.save(out, 'PNG', optimize=True)
    return out


# ---------------------------------------------------------------- the command


def _listed(text, allowed, name):
    if not text:
        return None
    values = [value.strip() for value in text.split(',') if value.strip()]
    wrong = [value for value in values if value not in allowed]
    if wrong or not values:
        raise SystemExit(f'--{name}: {", ".join(wrong) or "nothing"} is not one of {", ".join(allowed)}')
    return values


def check(template_id, *, locales=None, cases=None, root=None, pages=None, say=print):
    """Draw a template's samples and say what the checker finds; the number of papers with problems."""
    failed = 0
    with tempfile.TemporaryDirectory() as folder:
        for case in cases or CASES:
            for locale in locales or LOCALES:
                try:
                    drawn = draw(template_id, case, locale, folder, root=root)
                except (KeyError, ValueError) as error:
                    failed += 1
                    say(f'FAIL {template_id} · {case} · {locale}: cannot be drawn: {error}')
                    continue
                found = drawn.problems()
                failed += bool(found)
                say(f"{'FAIL' if found else 'ok  '} {drawn.note()}")
                for problem in found:
                    say(f'     {problem}')
                if pages:
                    Path(pages).mkdir(parents=True, exist_ok=True)
                    for number, image in enumerate(page_images(drawn.path, 1240), 1):
                        target = Path(pages) / f'{template_id}-{case}-{locale}-p{number}.png'
                        image.save(target)
                        say(f'     {target}')
    return failed


def main(argv=None):
    import argparse
    import django
    # The package's __init__ has named the settings module by now: `python -m` imports the package first.
    django.setup()
    parser = argparse.ArgumentParser(prog='python -m apps.studio.paper.sample', description=__doc__.split('\n')[0])
    parser.add_argument('--sheet', metavar='OUT.png', help='a sheet of papers drawn from their samples')
    parser.add_argument('--blocks', metavar='OUT.png', help='the block sheet, from every block module’s SAMPLES')
    parser.add_argument('--check', metavar='TEMPLATE', help='draw a template’s samples and print what is wrong')
    parser.add_argument('--template', help='with --sheet: this template in every case and language')
    parser.add_argument('--locale', help='uz, ru, en, or several comma-separated')
    parser.add_argument('--case', help='full, blank, long, or several comma-separated')
    parser.add_argument('--pages', metavar='DIR', help='with --check: write each page as a PNG here')
    parser.add_argument('--samples', metavar='DIR', help='read sample files from this folder instead')
    parser.add_argument('--mocks', metavar='DIR', help='with --sheet: the research folder the templates’ mocks are in')
    parser.add_argument('--width', type=int, default=260, help='with --sheet: the width of each page, in pixels')
    options = parser.parse_args(argv)
    locales, cases = _listed(options.locale, LOCALES, 'locale'), _listed(options.case, CASES, 'case')
    known = catalogue._catalogue().templates
    for name in (options.template, options.check):
        if name and name not in known:
            parser.error(f'{name} is not a template of the catalogue')
        if name and not sample_path(name, 'full', options.samples):
            parser.error(f'{name} has no samples yet: write {Path(options.samples or SAMPLES) / name}/full.json')
    status = 0
    if options.sheet:
        try:
            print(sheet(options.sheet, templates=[options.template] if options.template else None, locales=locales,
                        cases=cases, root=options.samples, width=options.width, mocks=options.mocks))
        except ValueError as error:
            print(error)
            status = 1
    if options.blocks:
        try:
            print(blocks_sheet(options.blocks, locale=(locales or ['uz'])[0]))
        except ValueError as error:
            print(error)
            status = 1
    if options.check:
        status = 1 if status or check(options.check, locales=locales, cases=cases, root=options.samples,
                            pages=options.pages) else 0
    if not (options.sheet or options.blocks or options.check):
        parser.print_help()
    return status


if __name__ == '__main__':
    raise SystemExit(main())
