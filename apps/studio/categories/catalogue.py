"""The closed set of AI PDF and AI Slides categories: loaded, checked and asked.

A category is `options.category` on the two existing services, so a customer
who picks none gets today's product. What each category is (its parts,
fields, rules, copy and templates) is data in `data/`, one file per entry and
per PDF template, plus `index.json` for the lists the bot shows. Code reads it
only through this module:

- `get(id)` any entry, whatever its status; `of(data)` the entry of a draft or
  job, None without one, and `category_unknown` for an id this catalogue does
  not hold (a catalogue rolled back), so a job fails before any provider call;
- `on()`, `live(fid)` and `menu(fid, group)`: what customers may pick now. They
  read the switch row (`operations.categories_settings`) on every call, and are
  off while that module does not exist;
- `check()`, the checks a person cannot be trusted to remember (alphabets,
  references, budgets, the ids lock), run by the catalogue test and by
  `python -m apps.studio.categories.catalogue --check [prefix] | --lock`.

The files are read and validated once per process, on first use: the schema,
then every reference a later reader would otherwise trip over. A file that
fails raises `CatalogueError` naming each problem, as `operations/i18n.py`
does for a missing key, and the catalogue test fails before a deploy.

Ids are append-only. `data/ids.lock.json` records every entry, field, part and
template id with its kind; the check fails when one disappears or changes
kind, so a draft made yesterday finds its parts in today's catalogue. An entry
is retired, a part marked `retired`, never deleted. `--lock` adds new ids; the
lock is never edited by hand.
"""
import functools
import hashlib
import importlib
import json
import re
import sys
from collections import namedtuple
from dataclasses import dataclass, field as attribute
from pathlib import Path

from apps.core.errors import DomainError

from ..language import CYRILLIC

DATA = Path(__file__).resolve().parent / 'data'
LOCALES = ('uz', 'ru', 'en')
FEATURES = {'pdf': 'ai.pdf_topic', 'slides': 'ai.pptx'}
SERVICES = {feature: service for service, feature in FEATURES.items()}
DRAFT, READY, RETIRED = 'draft', 'ready', 'retired'
OTHER = 'other'
# Recorded when a customer taps a category in the bot, beside the documents made
# with it, so chosen-versus-made can be read from the first day.
CHOSEN_EVENT = 'category.chosen'
# A category paper is many short parts rather than one section a page, so its
# draft holds more sections and longer lists than validate_content allows a
# Boshqa document; decks keep their slide bounds.
Bounds = namedtuple('Bounds', 'sections items')
PAPER_BOUNDS = Bounds(sections=60, items=40)
# The drawing blocks of the PDF template engine (blocks.json of the research,
# its kind "block"); engine passes are not placed by a template. A ready entry
# also needs each of its blocks registered in apps/studio/paper/registry.py.
BLOCKS = frozenset((
    'paragraph', 'line', 'heading', 'doc_title', 'list', 'table', 'kv_table', 'callout', 'inline_blank',
    'ruled_blank', 'signature_row', 'date_line', 'doc_head', 'party_block', 'approval_block', 'title_page', 'toc',
    'reference_list', 'cell_strip', 'question_list', 'answer_key', 'formula_line', 'split_row', 'clauses',
    'letterhead', 'key_figures', 'card_grid', 'gantt_grid', 'extra_sheets', 'footnote', 'amount_in_words'))
# The cue computed from the files and the message, never declared by an entry.
SOURCES_CUE = 'sources'
BLOCK_BUDGET = 5000
SLOT = re.compile(r'\{(\w+)\}')


class CatalogueError(ValueError):
    """The data files do not hold together; `problems` names each fault as "<file>: <what>"."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__('The category catalogue does not load:\n' + '\n'.join(self.problems))


@dataclass(frozen=True)
class Entry:
    """One category. `raw` is the loaded file and is shared: read it, never change it."""

    id: str
    service: str
    feature_id: str
    status: str
    raw: dict = attribute(repr=False, compare=False)
    # 8 hex of the entry and its templates, so a prompt cache key moves when either does.
    digest: str = attribute(default='', compare=False)

    def label(self, locale):
        labels = self.raw['labels']
        return labels.get(locale) or labels['en']

    def name(self, locale):
        """The label without its emoji: the title of a paper whose title is its category (an Ariza)."""
        return self.label(locale).split(' ', 1)[-1]

    def field(self, field_id):
        return next((item for item in self.raw['fields'] if item['id'] == field_id), None)

    def part(self, part_id):
        """The part a section id belongs to; `chapter_2`, a later instance of a grouped part, is `chapter`'s."""
        found = next((item for item in self.raw['parts'] if item['id'] == part_id), None)
        if found is None and re.fullmatch(r'.+_\d+', str(part_id)):
            base = self.part(str(part_id).rsplit('_', 1)[0])
            return base if base is not None and base.get('group') else None
        return found

    @property
    def parts(self):
        return tuple(self.raw['parts'])

    @property
    def fields(self):
        return tuple(self.raw['fields'])

    @property
    def templates(self):
        return tuple(self.raw['templates'])

    @property
    def look(self):
        return self.raw['look']

    @property
    def length(self):
        return self.raw['length']

    @property
    def ask(self):
        return self.raw['ask']

    @property
    def topic(self):
        return self.raw['topic']


@dataclass(frozen=True)
class Node:
    """One button of a list: a category (with its entry), a group of categories, or Boshqa (`other`)."""

    id: str
    kind: str
    labels: dict = attribute(repr=False, compare=False)
    entry: Entry | None = attribute(default=None, compare=False)

    def label(self, locale):
        return self.labels.get(locale) or self.labels['en']


@dataclass(frozen=True)
class Catalogue:
    entries: dict
    templates: dict
    index: dict
    version: str
    # feature id -> entry ids in the order the lists show them, groups opened in place.
    order: dict


Problem = namedtuple('Problem', 'subject text warning')
Problem.__str__ = lambda self: f"{self.subject}: {'warning: ' if self.warning else ''}{self.text}"


# ---------------------------------------------------------------- loading


def _json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _hex(*values, size):
    digest = hashlib.sha256()
    for value in values:
        digest.update(_canonical(value).encode())
    return digest.hexdigest()[:size]


@functools.lru_cache(maxsize=1)
def _validators():
    import jsonschema
    schema = _json(DATA / 'catalogue.schema.json')
    template = {'$ref': '#/$defs/template', '$defs': schema['$defs']}
    return jsonschema.Draft202012Validator(schema), jsonschema.Draft202012Validator(template)


def read(folder=DATA):
    """The data files as dicts: (entries by file name, templates by file name, index), file names without .json."""
    entries = {path.stem: _json(path) for path in sorted(folder.glob('*.json'))
               if path.name not in ('index.json', 'ids.lock.json', 'catalogue.schema.json')}
    templates = {path.stem: _json(path) for path in sorted((folder / 'templates').glob('*.json'))}
    return entries, templates, _json(folder / 'index.json')


def build(entries, templates, index):
    """A catalogue from loaded files; raises CatalogueError when the schema or a reference does not hold."""
    entry_schema, template_schema = _validators()
    problems = []
    for name, raw in entries.items():
        problems += [f'{name}: {_where(error)}{error.message[:200]}' for error in entry_schema.iter_errors(raw)]
    for name, raw in templates.items():
        problems += [f'templates/{name}: {_where(error)}{error.message[:200]}'
                     for error in template_schema.iter_errors(raw)]
    if problems:
        # References are only worth reading once every file has the shape they assume.
        raise CatalogueError(problems)
    problems += _index_problems(entries, index)
    for name, raw in entries.items():
        problems += [f'{name}: {text}' for text in _entry_problems(name, raw, entries, templates, index)]
    for name, raw in templates.items():
        problems += [f'templates/{name}: {text}' for text in _template_problems(name, raw, entries)]
    if problems:
        raise CatalogueError(problems)
    made = {}
    for name, raw in entries.items():
        digest = _hex(raw, *(templates[template] for template in raw['templates']), size=8)
        made[name] = Entry(raw['id'], raw['service'], FEATURES[raw['service']], raw['status'], raw, digest)
    order = {feature: tuple(item for item in _walk(index, feature) if item in made) for feature in SERVICES}
    version = _hex(entries, templates, index, size=12)
    return Catalogue(made, templates, index, version, order)


def _where(error):
    return '/'.join(str(step) for step in error.absolute_path) + ': ' if error.absolute_path else ''


def _walk(index, feature):
    """Ids of a feature's lists in their order, a group's children where the group stands."""
    groups = index.get('groups', {})
    for item in index.get('lists', {}).get(feature, ()):
        yield from (groups[item]['children'] if item in groups else (item,))


def _is_text3(value):
    return isinstance(value, dict) and set(value) == set(LOCALES) and all(isinstance(v, str) for v in value.values())


def _index_problems(entries, index):
    problems = []
    lists, groups = index.get('lists') or {}, index.get('groups') or {}
    if set(lists) != set(SERVICES):
        problems.append(f'index: lists must be exactly {sorted(SERVICES)}, not {sorted(lists)}')
    if not _is_text3(index.get('other')):
        problems.append('index: other: the Boshqa label needs uz, ru and en')
    placed = {}
    for feature, items in lists.items():
        service = SERVICES.get(feature, '?')
        if items.count(OTHER) != 1:
            problems.append(f'index: {feature}: Boshqa (other) must be in the list once')
        for position, item in enumerate(items, 1):
            if item == OTHER:
                continue
            if item in groups:
                placed.setdefault(item, []).append((feature, None, position))
                if not item.startswith(service + '.'):
                    problems.append(f'index: {feature}: group {item} belongs to another service')
            elif re.fullmatch(rf'{service}\.[a-z][a-z0-9_]*', item):
                placed.setdefault(item, []).append((feature, None, position))
            else:
                problems.append(f'index: {feature}: {item} is not a group, a {service} category id or other')
    for group, node in groups.items():
        if group not in placed:
            problems.append(f'index: group {group} is in no list')
        if not _is_text3(node.get('label')) or not _is_text3(node.get('other')):
            problems.append(f'index: group {group} needs its label and its Boshqa label in uz, ru and en')
        children = node.get('children') or []
        if children.count(OTHER) != 1:
            problems.append(f'index: group {group}: Boshqa (other) must be in the group once')
        for position, child in enumerate(children, 1):
            if child == OTHER:
                continue
            if not re.fullmatch(rf'{re.escape(group)}\.[a-z][a-z0-9_]*', child):
                problems.append(f'index: group {group}: {child} is not a category id under {group}')
            placed.setdefault(child, []).append((None, group, position))
    for item, places in placed.items():
        if len(places) > 1:
            problems.append(f'index: {item} is listed {len(places)} times')
    for name, raw in entries.items():
        if raw['status'] == RETIRED:
            continue
        places = placed.get(raw['id'])
        if not places:
            problems.append(f"{name}: not in index.json; every entry that is not retired is listed")
            continue
        feature, group, position = places[0]
        if group != raw['parent'] or (feature is not None and feature != FEATURES[raw['service']]):
            problems.append(f"{name}: parent is {raw['parent']} but index.json lists it under {group or feature}")
        if position != raw['order']:
            problems.append(f"{name}: order is {raw['order']} but index.json shows it at {position}")
    return problems


def _entry_problems(name, raw, entries, templates, index):
    problems = []
    service = raw['service']
    if name != raw['id']:
        problems.append(f"the file is named {name}.json but holds {raw['id']}")
    if not raw['id'].startswith(service + '.'):
        problems.append(f'the id does not start with its service {service}')
    parent = raw['parent']
    if parent is not None and (parent not in (index.get('groups') or {}) or not raw['id'].startswith(parent + '.')):
        problems.append(f'parent {parent} is not a group of index.json that holds this id')
    fields = [item['id'] for item in raw['fields']]
    parts = [item['id'] for item in raw['parts']]
    for kind, ids in (('field', fields), ('part', parts), ('template', raw['templates'])):
        twice = sorted({item for item in ids if ids.count(item) > 1})
        if twice:
            problems.append(f"{kind} ids used twice: {', '.join(twice)}")
    cues = set(raw['cues']) | {SOURCES_CUE}
    groups = raw.get('groups') or {}
    for item in raw['fields']:
        if item.get('derived_from') is not None and (item['derived_from'] not in fields
                                                      or item['derived_from'] == item['id']):
            problems.append(f"field {item['id']}: derived_from {item['derived_from']} is not another field")
        if (item['kind'] == 'choice') != bool(item.get('choices')):
            problems.append(f"field {item['id']}: choices go with kind choice, and a choice field needs them")
    from ..layouts import LAYOUT_IDS
    for part in raw['parts']:
        where = f"part {part['id']}"
        unknown = set(part.get('fields', ())) - set(fields)
        if unknown:
            problems.append(f"{where}: unknown fields {sorted(unknown)}")
        if part.get('group') is not None and part['group'] not in groups:
            problems.append(f"{where}: group {part['group']} is not declared in groups")
        if part.get('when') and part['when'].split(':', 1)[1] not in cues:
            problems.append(f"{where}: when {part['when']} names no cue of this entry")
        if part.get('block') is not None and part['block'] not in BLOCKS:
            problems.append(f"{where}: block {part['block']} is not a drawing block")
        if (part['kind'] == 'slide') != (service == 'slides'):
            problems.append(f"{where}: kind {part['kind']} does not belong to a {service} entry")
        unknown = set(part.get('layouts', ())) - set(LAYOUT_IDS)
        if unknown:
            problems.append(f"{where}: unknown layouts {sorted(unknown)}")
        if part.get('checks') and part.get('source') != 'draft':
            # A customer slot is grounded whole and a template slot holds fixed words: checks would mean nothing.
            problems.append(f"{where}: checks go with source draft only")
    used = {part.get('group') for part in raw['parts']}
    for group, size in groups.items():
        if group not in used:
            problems.append(f'group {group} is used by no part')
        if size['min'] > size['max']:
            problems.append(f'group {group}: min is above max')
    length = raw['length']
    if not length['min'] <= length['default'] <= length['max']:
        problems.append('length: default is outside min..max')
    for rule in length.get('by_cue', ()):
        if rule['cue'] not in cues:
            problems.append(f"length: by_cue names no cue {rule['cue']}")
        if not length['min'] <= rule['default'] <= length['max']:
            problems.append(f"length: by_cue {rule['cue']} is outside min..max")
    if (length['mode'] == 'derived') != ('per' in length):
        problems.append('length: per goes with mode derived, and a derived length needs it')
    if raw['questions']['default'] > raw['questions']['max']:
        problems.append('questions: default is above max')
    for names in raw.get('exclusive', ()):
        if set(names) - set(raw['cues']):
            problems.append(f'exclusive names cues this entry does not declare: {sorted(set(names) - set(raw["cues"]))}')
    if raw['ask'] and set(raw['ask']['fields']) - set(fields):
        problems.append(f"ask: unknown fields {sorted(set(raw['ask']['fields']) - set(fields))}")
    for rule in (raw['look'] or {}).get('by_cue', ()):
        if rule['cue'] not in cues:
            problems.append(f"look: by_cue names no cue {rule['cue']}")
    for position, template in enumerate(raw['templates']):
        if template not in templates:
            problems.append(f'template {template} has no file in data/templates')
            continue
        if raw['id'] not in templates[template]['entries']:
            problems.append(f'template {template} does not list this entry among its entries')
        if position == 0 and templates[template].get('pick'):
            problems.append(f'template {template} is the default (first) and carries a pick')
        if position > 0 and not templates[template].get('pick'):
            problems.append(f'template {template} is not the default and has no pick')
    return problems


def _template_problems(name, raw, entries):
    problems = []
    if name != raw['id']:
        problems.append(f"the file is named {name}.json but holds {raw['id']}")
    listing = []
    for entry_id in raw['entries']:
        entry = entries.get(entry_id)
        if entry is None:
            problems.append(f'entries: {entry_id} is not in the catalogue')
        elif raw['id'] not in entry['templates']:
            problems.append(f'entries: {entry_id} does not list this template')
        else:
            listing.append(entry)
    labels = set(raw['labels'])
    for entry in listing:
        fields = {item['id']: item for item in entry['fields']}
        parts = {item['id'] for item in entry['parts']}
        cues = set(entry['cues']) | {SOURCES_CUE}
        where = f"for {entry['id']}"
        for position, place in enumerate(raw['flow']):
            at = f"flow {position} ({place['block']})"
            if place['block'] not in BLOCKS:
                problems.append(f'{at}: {place["block"]} is not a drawing block')
            if place.get('part') is not None and place['part'] not in parts:
                problems.append(f"{at}: part {place['part']} is not a part {where}")
            unknown = set(place.get('fields', ())) - set(fields)
            if unknown:
                problems.append(f'{at}: unknown fields {sorted(unknown)} {where}')
            problems += [f'{at}: {text} {where}' for text in _when_problems(place.get('when'), fields, parts, cues)]
        unknown = set(raw['furniture'].get('header', ())) - set(fields)
        if unknown:
            problems.append(f'furniture: header names unknown fields {sorted(unknown)} {where}')
        slots = {slot for text in raw['labels'].values() for value in text.values() for slot in SLOT.findall(value)}
        if slots - set(fields):
            problems.append(f'labels: slots {sorted(slots - set(fields))} are not fields {where}')
    for position, place in enumerate(raw['flow']):
        missing = sorted(set(_label_keys(place.get('params') or {})) - labels)
        if missing:
            problems.append(f"flow {position} ({place['block']}): labels {missing} are not in the template's labels")
    return problems


def _when_problems(when, fields, parts, cues):
    if not when:
        return []
    kind, _, rest = when.partition(':')
    name, _, value = rest.partition('=')
    if kind in ('fact', 'nofact', 'blank'):
        if name not in fields:
            return [f'when {when} names no field']
        choices = fields[name].get('choices')
        if value and choices and value not in choices:
            return [f'when {when}: {value} is not one of the choices of {name}']
    elif kind in ('part', 'nopart') and name not in parts:
        return [f'when {when} names no part']
    elif kind in ('cue', 'nocue') and name not in cues:
        return [f'when {when} names no cue']
    return []


def _label_keys(params):
    """The template labels a placement's parameters name: any `label`, and the values of `captions` and `labels`."""
    if isinstance(params, list):
        for item in params:
            yield from _label_keys(item)
    elif isinstance(params, dict):
        for key, value in params.items():
            if key == 'label' and isinstance(value, str):
                yield value
            elif key in ('captions', 'labels') and isinstance(value, dict):
                yield from (item for item in value.values() if isinstance(item, str))
            else:
                yield from _label_keys(value)


@functools.lru_cache(maxsize=1)
def _catalogue():
    return build(*read())


# ---------------------------------------------------------------- asking


def get(category_id):
    """The entry with this id, whatever its status, or None."""
    return _catalogue().entries.get(category_id) if isinstance(category_id, str) else None


def of(data):
    """The category of a draft (its options) or a job (its parameters): None without one.

    An id the catalogue does not hold raises `category_unknown`: run as a
    Boshqa document it would be today's pipeline with a category's price and
    promise, so the job fails before any provider call and is not counted.
    """
    data = data or {}
    options = data.get('options')
    if options is None:
        options = data.get('parameters') or {}
    if options.get('category') is None:
        return None
    entry = get(options['category'])
    if entry is None:
        raise DomainError('category_unknown', 500)
    return entry


def bounds(data):
    """What validate_content allows a draft: the paper bounds for a category PDF, None (today's) otherwise."""
    entry = of(data)
    return PAPER_BOUNDS if entry is not None and entry.service == 'pdf' else None


def for_feature(feature_id):
    """Every entry of a service that is not retired, in the lists' order: what the switch page shows."""
    catalogue = _catalogue()
    return [catalogue.entries[item] for item in catalogue.order.get(feature_id, ())
            if catalogue.entries[item].status != RETIRED]


def _optional(name):
    """The module `name`, or None while it (or its package) does not exist yet; a module that breaks still raises."""
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as error:
        if error.name and (name == error.name or name.startswith(error.name + '.')):
            return None
        raise


def _switch():
    settings = _optional('operations.categories_settings')
    return settings.get() if settings is not None else {'on': False, 'live': []}


def on():
    """Whether the lists and category sources are switched on at all."""
    return bool(_switch().get('on'))


def live(feature_id):
    """The entries customers may pick now: switched on, ticked by the owner, ready, in the lists' order."""
    switch = _switch()
    if not switch.get('on'):
        return []
    ticked = set(switch.get('live') or ())
    return [entry for entry in for_feature(feature_id) if entry.id in ticked and entry.status == READY]


def menu(feature_id, group=None):
    """The buttons of a service's list, or of one group in it; [] when nothing in it is live.

    A category is shown when it is live, a group when something under it is,
    and Boshqa always beside them. An empty answer means no list at all: the
    service opens today's prompt.
    """
    index = _catalogue().index
    shown = {entry.id: entry for entry in live(feature_id)}
    if group is None:
        items, other = index['lists'].get(feature_id, ()), index['other']
    elif group in index['groups'] and group in index['lists'].get(feature_id, ()):
        items, other = index['groups'][group]['children'], index['groups'][group]['other']
    else:
        return []
    nodes = []
    for item in items:
        if item == OTHER:
            nodes.append(Node(OTHER, 'other', other))
        elif item in index['groups']:
            if any(child in shown for child in index['groups'][item]['children']):
                nodes.append(Node(item, 'group', index['groups'][item]['label']))
        elif item in shown:
            nodes.append(Node(item, 'category', shown[item].raw['labels'], shown[item]))
    return nodes if any(node.kind != 'other' for node in nodes) else []


def examples():
    """Every example and pool text of the catalogue, in every language: the bot's own examples in a category flow."""
    found = set()
    for entry in _catalogue().entries.values():
        for text in (*entry.raw['bot']['examples'], *entry.raw['bot'].get('pool', ())):
            found.update(text.values())
    return found


def version():
    """12 hex of every entry, template and the index: changes whenever any of them does."""
    return _catalogue().version


def template(template_id):
    """A PDF template as loaded (shared: never change it); KeyError for an id this catalogue does not hold."""
    return _catalogue().templates[template_id]


# ---------------------------------------------------------------- checking


def check(prefix=None, *, catalogue=None, lock=None):
    """Everything wrong with the catalogue beyond its shape, as Problems; [] when it is fit to ship.

    A warning is a readiness gate an entry still in draft has not met; on a
    ready entry the same finding is an error. `prefix` keeps the findings
    about entries whose id starts with it (and the index's).
    """
    catalogue = catalogue or _catalogue()
    lock = read_lock() if lock is None else lock
    found = []
    for entry in catalogue.entries.values():
        found += _text_problems(entry.id, entry.raw)
        found += _entry_checks(entry, catalogue)
    for name, raw in catalogue.templates.items():
        found += _text_problems(f'templates/{name}', raw)
    found += _text_problems('index', {key: value for key, value in catalogue.index.items() if key != 'owner_labels'})
    found += _label_problems(catalogue)
    found += lock_problems(catalogue, lock)
    if prefix:
        templates = {name: raw['entries'] for name, raw in catalogue.templates.items()}
        found = [problem for problem in found if problem.subject.startswith(prefix) or problem.subject == 'index'
                 or any(item.startswith(prefix) for item in templates.get(problem.subject[10:], ()))]
    return found


def _text_problems(subject, raw):
    """Customer-facing words: Latin only in uz and en, house apostrophes in uz, no markup, the same {slots}."""
    found = []

    def walk(value, path):
        if _is_text3(value):
            where = '/'.join(path)
            for locale in ('uz', 'en'):
                if CYRILLIC.search(value[locale]):
                    found.append(Problem(subject, f'{where}: Cyrillic in {locale}: {value[locale][:60]!r}', False))
            if "'" in value['uz'] or '`' in value['uz']:
                found.append(Problem(subject, f"{where}: an ASCII apostrophe in uz (write ‘ in o‘ g‘, ’ for the "
                                              f"tutuq): {value['uz'][:60]!r}", False))
            for locale in LOCALES:
                if '<' in value[locale] or '&' in value[locale]:
                    found.append(Problem(subject, f'{where}: < or & in {locale}: {value[locale][:60]!r}', False))
            slots = {locale: sorted(SLOT.findall(value[locale])) for locale in LOCALES}
            if len({tuple(names) for names in slots.values()}) > 1:
                found.append(Problem(subject, f'{where}: the languages carry different slots {slots}', False))
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(item, path + [str(key)])
        elif isinstance(value, list):
            for position, item in enumerate(value):
                walk(item, path + [str(position)])
    walk(raw, [])
    return found


def _entry_checks(entry, catalogue):
    raw, found = entry.raw, []

    def gate(text):
        # On a ready entry a gate is an error; on a draft it is the work left before it can be.
        found.append(Problem(entry.id, text, entry.status != READY))
    required = sum(part.get('share', 0) for part in raw['parts'] if part['need'] == 'required'
                   and not part.get('retired'))
    if required > 1 + 1e-9:
        found.append(Problem(entry.id, f'the required parts share {required:.2f} of the pages, more than all', False))
    copy = _canonical([raw['bot']['prompt'], raw['bot']['examples'], raw['bot'].get('pool', []),
                       raw['bot']['notices']]).lower()
    for later in raw['later']:
        for word in later.get('words', ()):
            if word.lower() in copy:
                found.append(Problem(entry.id, f'bot copy promises a deferred thing: {word!r}', False))
    if raw['length']['mode'] == 'count':
        number = re.compile(rf"(?<!\d){raw['length']['default']}(?!\d)")
        for locale in LOCALES:
            if not number.search(raw['bot']['prompt'][locale]):
                gate(f"the default count {raw['length']['default']} is not in the {locale} bot prompt")
    if any(rule['to'] == 'rewrite' for rule in raw['rules']):
        gate('a rewrite rule is left: reword it for the model or drop it')
    size, estimated = block_size(entry)
    if size > BLOCK_BUDGET:
        gate(f"the instruction block is {size:,} characters{' (estimated)' if estimated else ''}, "
             f'over {BLOCK_BUDGET:,}')
    if entry.service == 'slides':
        found += [Problem(entry.id, text, False) for text in _deck_problems(raw)]
    else:
        registry = _optional('apps.studio.paper.registry')
        registered = set(getattr(registry, 'BLOCKS', None) or ())
        wanted = {part['block'] for part in raw['parts'] if part.get('block') and not part.get('retired')}
        for name in raw['templates']:
            wanted |= {place['block'] for place in catalogue.templates[name]['flow']}
        missing = sorted(wanted - registered)
        if missing:
            gate(f"blocks not yet registered in apps/studio/paper/registry.py: {', '.join(missing)}")
    return found


def _deck_problems(raw):
    from .. import variants
    from ..deck_designs import DESIGNS
    found = []
    look = raw['look']
    for design in (*look['designs'], *(rule['design'] for rule in look.get('by_cue', ()))):
        if design not in DESIGNS:
            found.append(f'look: {design} is not a deck design')
    pins = {pin for part in raw['parts'] for pin in part.get('pins', ())}
    pins |= {f'{kind}.{name}' for kind, names in look.get('variants', {}).items() for name in names}
    for pin in sorted(pins):
        try:
            variants.get(pin)
        except KeyError:
            found.append(f'{pin} is not a registered slide variant')
    return found


def block_size(entry):
    """(characters, estimated) of the category block the model reads (architecture 3.1).

    The block is built by apps/studio/categories/prompting.py; until that
    exists it is estimated from what it holds: the tone, the model rules, the
    fixed parts' write texts and one line per field.
    """
    prompting = _optional('apps.studio.categories.prompting')
    if prompting is not None and hasattr(prompting, 'block'):
        return len(prompting.block(entry)), False
    raw = entry.raw
    lines = [rule['text'] for rule in raw['rules'] if rule['to'] == 'model']
    lines += [part['write'] for part in raw['parts'] if part['kind'] == 'fixed' and not part.get('retired')]
    lines += [f"{item['id']}: {item['label']['en']}, {item['kind']}"
              + (f", {'|'.join(item['choices'])}" if item.get('choices') else '') for item in raw['fields']]
    return len(raw['tone']) + sum(len(line) + 1 for line in lines), True


def _label_problems(catalogue):
    """Buttons of one list must differ, and an entry the owner named carries the owner's words."""
    found, index = [], catalogue.index
    lists = [(feature, items, index['other']) for feature, items in index['lists'].items()]
    lists += [(group, node['children'], node['other']) for group, node in index['groups'].items()]
    for name, items, other in lists:
        buttons = [('other', other)]
        for item in items:
            if item in index['groups']:
                buttons.append((item, index['groups'][item]['label']))
            elif item in catalogue.entries:
                buttons.append((item, catalogue.entries[item].raw['labels']))
        for locale in LOCALES:
            seen = {}
            for item, labels in buttons:
                key = labels[locale].split(' ', 1)[-1].casefold()
                if key in seen:
                    found.append(Problem(item, f'the {locale} label is the same as {seen[key]} in the {name} list',
                                         False))
                seen[key] = item
    for item, words in (index.get('owner_labels') or {}).items():
        entry = catalogue.entries.get(item)
        if entry is not None and entry.name('uz') != words:
            found.append(Problem(item, f"the uz label must be the owner's {words!r}, not {entry.name('uz')!r}", False))
    return found


# ---------------------------------------------------------------- the ids lock


def read_lock(folder=DATA):
    path = folder / 'ids.lock.json'
    return _json(path) if path.exists() else {'entries': {}}


def locked_ids(catalogue):
    """What the lock records of a catalogue: per entry its service, field and part kinds, template ids."""
    return {entry.id: {'service': entry.service,
                       'fields': {item['id']: item['kind'] for item in entry.raw['fields']},
                       'parts': {item['id']: item['kind'] for item in entry.raw['parts']},
                       'templates': sorted(entry.raw['templates'])}
            for entry in catalogue.entries.values()}


def lock_problems(catalogue, lock):
    found, now = [], locked_ids(catalogue)
    for entry_id, was in (lock.get('entries') or {}).items():
        current = now.get(entry_id)
        if current is None:
            found.append(Problem(entry_id, 'a locked entry is gone: retire it (status retired), never delete it',
                                 False))
            continue
        if current['service'] != was['service']:
            found.append(Problem(entry_id, f"its service changed from {was['service']}", False))
        for kind in ('fields', 'parts'):
            for item, item_kind in was.get(kind, {}).items():
                if item not in current[kind]:
                    found.append(Problem(entry_id, f"the locked {kind[:-1]} {item} is gone"
                                         + (': mark it retired' if kind == 'parts' else ''), False))
                elif current[kind][item] != item_kind:
                    found.append(Problem(entry_id, f'the locked {kind[:-1]} {item} changed kind from {item_kind} '
                                         f'to {current[kind][item]}', False))
        for name in was.get('templates', ()):
            if name not in catalogue.templates:
                found.append(Problem(entry_id, f'the locked template {name} has no file any more', False))
    for entry_id, current in now.items():
        was = (lock.get('entries') or {}).get(entry_id)
        if not was:
            found.append(Problem(entry_id, 'a new entry, not in ids.lock.json yet: run '
                                 'python -m apps.studio.categories.catalogue --lock', False))
            continue
        new = []
        for kind in ('fields', 'parts'):
            new += [f'{kind[:-1]} {item}' for item in current[kind] if item not in was.get(kind, {})]
        new += [f'template {name}' for name in current['templates'] if name not in was.get('templates', ())]
        if new:
            found.append(Problem(entry_id, f"not in ids.lock.json yet ({', '.join(new)}): run "
                                 f'python -m apps.studio.categories.catalogue --lock', False))
    return found


def relock(catalogue, lock):
    """The lock with every new id added and nothing removed; CatalogueError when a locked id is gone or changed."""
    broken = [str(problem) for problem in lock_problems(catalogue, lock) if 'not in ids.lock.json' not in problem.text]
    if broken:
        raise CatalogueError(broken)
    entries = {entry_id: {**was} for entry_id, was in (lock.get('entries') or {}).items()}
    for entry_id, current in locked_ids(catalogue).items():
        was = entries.get(entry_id, {})
        entries[entry_id] = {'service': current['service'],
                             'fields': {**current['fields'], **was.get('fields', {})},
                             'parts': {**current['parts'], **was.get('parts', {})},
                             'templates': sorted(set(current['templates']) | set(was.get('templates', ())))}
    return {'note': 'Every category id that may never disappear, with its kind. Written by '
                    'python -m apps.studio.categories.catalogue --lock; never edited by hand.',
            'entries': {entry_id: entries[entry_id] for entry_id in sorted(entries)}}


def write_lock(lock, folder=DATA):
    # Sorted, so the file reads the same whatever order the entries list their ids in.
    text = json.dumps(lock, ensure_ascii=False, indent=1, sort_keys=True) + '\n'
    (folder / 'ids.lock.json').write_text(text, encoding='utf-8')


# ---------------------------------------------------------------- command line


def main(argv=None):
    """`--check [prefix]` reports what is wrong (exit 1 on an error); `--lock` adds new ids to the lock."""
    import argparse
    import os
    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()
    parser = argparse.ArgumentParser(description='Check the category catalogue, or add its new ids to the lock.')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', nargs='?', const='', metavar='PREFIX', help='only entries whose id starts so')
    action.add_argument('--lock', action='store_true', help='add new ids to data/ids.lock.json')
    options = parser.parse_args(argv)
    try:
        catalogue = build(*read())
    except CatalogueError as error:
        # A file that does not load breaks the whole catalogue, whatever the prefix.
        print('\n'.join(error.problems))
        return 1
    if options.lock:
        lock = read_lock()
        try:
            new = relock(catalogue, lock)
        except CatalogueError as error:
            print('\n'.join(error.problems))
            return 1
        if new == lock:
            print('ids.lock.json already holds every id')
        else:
            write_lock(new)
            print(f"ids.lock.json now locks {len(new['entries'])} entries")
        return 0
    found = check(options.check or None, catalogue=catalogue)
    for entry in catalogue.entries.values():
        if options.check and not entry.id.startswith(options.check):
            continue
        size, estimated = block_size(entry)
        print(f"{entry.id}: {entry.status}, {len(entry.fields)} fields, {len(entry.parts)} parts, block "
              f"{size:,} characters{' (estimated)' if estimated else ''}")
    for problem in found:
        print(f'  {problem}')
    errors = [problem for problem in found if not problem.warning]
    print(f'{len(errors)} errors, {len(found) - len(errors)} warnings, catalogue {catalogue.version}')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
else:
    # Loaded when first imported, so a broken file is found by whatever first asks.
    _catalogue()
