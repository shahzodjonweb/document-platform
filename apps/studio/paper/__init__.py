"""The paper engine: a category PDF drawn in its own template (architecture 6).

A template (`categories/data/templates/<id>.json`) is data: the page, the
type ladder, a page rule, the page furniture, the fixed words in three
languages and a `flow` of block placements. This package draws one:

- `ready(data)`: whether a draft's paper can be drawn here: a PDF category
  whose chosen template this worker holds with every block registered;
- `template_for(data)` / `pick(entry, locale, cues)`: the template a paper is
  drawn in, the entry's first unless another's `pick` holds;
- `render_paper(content, path, locale, *, entry, template, pages, ...)`: the
  PDF, with render_pdf's result shape and `metadata {category, template,
  fit_step, warnings, ...}`.

How a paper is drawn: the flow is resolved into placements (`ctx.places`,
groups once per instance, `when` predicates); each placement's block makes
its flowables (`registry.draw`); the story is laid out on the template's
pages (`page.build`) at each ladder step the page rule needs (`fit.fit`).

Nothing about a paper's content can fail the job here:
- a block that raises is drawn by its plain fallback (`block_fallback:<name>`);
- a placement that breaks the layout (a cell taller than a page) is found by
  the mark before it, and the paper is built again with it drawn plain, then
  without it, unless it carries facts or a keep group (an addressee, the
  signatures): a paper without those is broken, so it goes to the fallback;
- a template this worker does not know, one with an unregistered block, or a
  build that fails anyway, gives the emergency fallback (architecture 6.7): the
  paper's parts as a plain document drawn by today's renderer, with
  `template_fallback` in its metadata, which the admin counts.

The engine only draws. The content it is given is already finished
(categories.finish): facts verified, invented things blanked, fixed headings
written. Every word it adds is a template label or a clock value.
"""
import copy
import inspect
import logging
import os
from pathlib import Path

# `python -m apps.studio.paper.sample` imports this package before the tool's own code runs, and the catalogue's
# imports read Django settings: name them when nothing has (a worker and the tests always have).
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

from apps.core.errors import DomainError  # noqa: E402

from ..categories import catalogue  # noqa: E402
from ..categories.catalogue import LOCALES  # noqa: E402
from ..categories.skeleton import FACTS, cues_of  # noqa: E402
from . import fit, page, registry  # noqa: E402
from .ctx import Ctx, places  # noqa: E402

log = logging.getLogger(__name__)

TEMPLATE_FALLBACK = 'template_fallback'
# The final passes did not settle: the contents' numbers or the "n / N" total may be a page off.
UNSETTLED = 'page_numbers_unsettled'
# How many times a build that breaks is tried again with the placement that broke it drawn plain, then left out.
RETRIES = 6
# Final builds after the fit: one with the contents' page numbers and the page count it found, one more only if
# that moved a page.
FINAL_PASSES = 2


def _locale(locale):
    return locale if locale in LOCALES else 'en'


def pick(entry, locale, cues=frozenset()):
    """The template id a paper of `entry` is drawn in: the first later one whose `pick` holds, else the default."""
    ids = list(entry.templates)
    if not ids:
        return None
    for template_id in ids[1:]:
        try:
            rule = catalogue.template(template_id).get('pick') or ''
        except KeyError:
            continue
        kind, _, name = rule.partition(':')
        if (kind == 'cue' and name in cues) or (kind == 'nocue' and name not in cues) \
                or (kind == 'locale' and name == _locale(locale)):
            return template_id
    return ids[0]


def template_for(data):
    """The template id of a draft's paper (its category, language and cues), or None when it is no category paper."""
    try:
        entry = catalogue.of(data)
    except DomainError:
        return None
    if entry is None or entry.service != 'pdf':
        return None
    return pick(entry, data.get('output_locale'), cues_of(data))


def flow_blocks(template):
    """The block names a template's flow draws with."""
    return {placement['block'] for placement in template.get('flow') or ()}


def ready(data):
    """Whether a draft's paper is drawn by this engine: a PDF category, its template known, every block registered."""
    template_id = template_for(data)
    if template_id is None:
        return False
    try:
        template = catalogue.template(template_id)
    except KeyError:
        return False
    return not registry.missing(flow_blocks(template))


# ---------------------------------------------------------------- drawing


def _elastic(entry, content):
    """The ids of the sections a count rule may cut: elastic prose parts, never facts or a list or a table."""
    found = set()
    for section in content.get('sections') or []:
        part = entry.part(section.get('id')) if isinstance(section, dict) else None
        if part and part['kind'] == 'prose' and part.get('elastic'):
            found.add(section['id'])
    return found


def _cut(content, elastic, ratio):
    """`content` with its elastic prose cut to `ratio` of its sentences, marked where cut."""
    if ratio is None or not elastic:
        return content
    from ..rendering import _trimmed
    cut = copy.deepcopy(content)
    sections = cut.get('sections') or []
    chosen = [section for section in sections if isinstance(section, dict) and section.get('id') in elastic]
    trimmed = iter(_trimmed(chosen, ratio))
    cut['sections'] = [next(trimmed) if isinstance(section, dict) and section.get('id') in elastic else section
                       for section in sections]
    return cut


class _Paper:
    """One paper being drawn: every build at every step, and the placements that broke a layout."""

    def __init__(self, content, locale, entry, template, pages, cues, day, style):
        self.content, self.locale, self.entry, self.template = content, locale, entry, template
        self.pages, self.cues, self.day, self.style = pages, cues, day, style
        left, bottom, self.width, self.height = page.geometry(template)
        # Placements as (flow index, instance): drawn plain, and left out.
        self.failed, self.dropped = set(), set()
        self.placed = {}
        self.elastic = _elastic(entry, content)

    def ctx(self):
        """A context of the content as given, at the loosest step: what `when` predicates read before any build."""
        return Ctx(content=self.content, entry=self.entry, template=self.template, locale=self.locale, step=0,
                   pages=self.pages, width=self.width, frame_height=self.height, cues=self.cues, day=self.day,
                   style=self.style)

    def build(self, step, ratio=None, *, known=None, total=None, state=None):
        """One build at `step` with the elastic prose cut to `ratio`; a placement that breaks it is drawn plain.

        `state` is the (failed, dropped) a build was made with: the final
        passes start from the build the fit chose, not from what other steps
        broke since. The Built keeps the state it was made with.
        """
        if state is not None:
            self.failed, self.dropped = set(state[0]), set(state[1])
        content = _cut(self.content, self.elastic, ratio)
        for _ in range(RETRIES + 1):
            ctx = Ctx(content=content, entry=self.entry, template=self.template, locale=self.locale, step=step,
                      pages=self.pages, width=self.width, frame_height=self.height, cues=self.cues, day=self.day,
                      style=self.style, known_pages=known)
            made = page.Built()
            resolved = places(ctx)
            self.placed = {(place.index, place.instance): place for place in resolved}
            try:
                page.build(ctx, fit.story(ctx, resolved, self.failed, self.dropped), total=total, made=made)
            except Exception as error:
                if not self._blame(made.at):
                    raise
                log.warning('Paper %s: a placement broke the layout at step %s (%s); drawn plain', self.entry.id,
                            step, type(error).__name__)
                continue
            made.ctx = ctx
            made.state = (frozenset(self.failed), frozenset(self.dropped))
            return made
        raise RuntimeError('the paper did not lay out after drawing its breaking placements plain')

    def _blame(self, keys):
        """Note the placement that broke a build: drawn plain next time, left out the time after. False: none left.

        A placement that carries facts or belongs to a keep group is never
        left out: False, so the build fails and the paper takes the emergency
        fallback, which keeps every fact and which the admin counts.
        """
        for key in keys:
            if key not in self.failed:
                self.failed.add(key)
                return True
        for key in keys:
            place = self.placed.get(key)
            if place is not None and (place.fields or place.keep):
                return False
        for key in keys:
            if key not in self.dropped:
                self.dropped.add(key)
                return True
        return False


def _artifact(path, built, *, entry, template_id, step, ratio, codes, template):
    warnings = list(dict.fromkeys([*built.ctx.warnings, *codes]))
    if built.ctx.rules.dropped:
        warnings.append('glyphs_dropped')
    left, bottom, width, height = page.geometry(template)
    frame = [page.box(left, bottom, left + width, bottom + height)]
    return {'path': str(path), 'name': path.name, 'mime_type': 'application/pdf', 'page_count': built.pages,
            'role': 'user_document', 'shortened': ratio is not None,
            'metadata': {'category': entry.id, 'template': template_id, 'fit_step': step, 'warnings': warnings,
                         'trim_ratio': ratio, 'last_page_fill': built.fill,
                         'frames': {'first': frame, 'later': frame}, 'furniture': page.furniture_boxes(template)}}


def render_paper(content, path, locale, *, entry, template, pages, style=None, cues=frozenset(), day=None,
                 fallback=None):
    """Draw a finished category paper to `path`; returns render_pdf's result shape.

    `template` is a template id (or a loaded template), `pages` the quoted
    page count (skeleton.pages), `cues` the draft's cues (skeleton.cues_of:
    `cue:` predicates and `pick`), `day` the Tashkent day a clock field is read
    on (today when None). `fallback(content, path) -> artifact` draws the
    emergency fallback; when None the engine's own is used. Never raises on
    content: see the module's docstring.
    """
    path = Path(path)
    locale = _locale(locale)
    template_id = template if isinstance(template, str) else (template or {}).get('id')
    try:
        raw = catalogue.template(template) if isinstance(template, str) else template
        if not raw:
            raise KeyError(template_id)
    except KeyError:
        log.warning('Paper %s: template %s is not known here; drawn by the fallback', entry.id, template_id)
        return _emergency(content, path, locale, entry, template_id, pages, fallback, 'template_unknown')
    absent = registry.missing(flow_blocks(raw))
    if absent:
        log.warning('Paper %s: blocks %s are not registered; drawn by the fallback', entry.id, ', '.join(absent))
        return _emergency(content, path, locale, entry, template_id, pages, fallback, 'blocks_missing')
    try:
        paper = _Paper(content, locale, entry, raw, pages, frozenset(cues or ()), day, style)
        steps = len(raw['type']['ladder'])
        uncounted = fit.uncounted(raw['page_rule'], paper.ctx())
        choice = fit.fit(paper.build, raw['page_rule'], steps, pages + uncounted)
        built, settled = _final(paper, choice, raw['furniture'])
        codes = list(choice.codes) + ([] if settled else [UNSETTLED])
        if built.pages > choice.target and fit.LONGER not in codes:
            # The final pass may move a page (the contents' numbers grew a line): the rule is read on what ships.
            codes.append(fit.LONGER)
        path.write_bytes(built.data)
        made = _artifact(path, built, entry=entry, template_id=template_id, step=choice.step, ratio=choice.ratio,
                         codes=codes, template=raw)
        made['metadata']['uncounted'] = uncounted
        return made
    except Exception as error:
        log.warning('Paper %s: template %s could not be built (%s); drawn by the fallback', entry.id, template_id,
                    registry.described(error))
        return _emergency(content, path, locale, entry, template_id, pages, fallback, 'build_failed')


def _final(paper, choice, furniture):
    """The build delivered: the fit's, built again when it prints what only a finished build knows.

    That is the contents' page numbers, the page count of "n / N", and a
    paper that turned out one page long: it carries no page number, so a
    numbered first page is built again without it.

    Returns (built, settled): unsettled when the last pass still moved a
    heading or the page count, so what it prints may be a page off.
    """
    built = choice.attempt
    total = furniture.get('format') == 'n_of_N' or (built.pages == 1 and furniture.get('first', 'none') != 'none')
    if not (total or built.ctx.wants_contents):
        return built, True
    settled = False
    for _ in range(FINAL_PASSES):
        again = paper.build(choice.step, choice.ratio, known=built.anchors, total=built.pages, state=built.state)
        settled = again.pages == built.pages and again.anchors == built.anchors
        built = again
        if settled:
            break
    return built, settled


# ---------------------------------------------------------------- the emergency fallback


def plain(content, entry, locale):
    """A paper as a plain document (architecture 6.7), for today's renderer.

    The title is the content's; the facts are one list of "Label: value" lines
    (a blank where a fact draws one), except choice, flag and file facts: a
    choice's value is a catalogue id such as `both`, which has no wording in
    the paper's language and would print an English code in an Uzbek or
    Russian paper; what it chose shows in the parts it shaped. Each written
    part is a section under its heading; a table's rows are list items whose
    cells are joined by " — ", so nothing is cut at three columns; the
    questions stay as they are.
    categories.finish.plain, when it exists, is preferred by `_emergency`.
    """
    locale = _locale(locale)
    sections = [section for section in content.get('sections') or [] if isinstance(section, dict)]
    made = []
    facts = next((section for section in sections if section.get('id') == FACTS), None)
    lines = []
    for item in (facts or {}).get('items') or []:
        if not isinstance(item, dict) or not item.get('label'):
            continue
        field = entry.field(item['label'])
        if not field or field['kind'] in ('choice', 'flag', 'file'):
            continue
        value = str(item.get('text') or item.get('value') or '').strip() or '____'
        lines.append(f"{field['label'].get(locale) or field['label']['en']}: {value}")
    if lines:
        made.append({'id': FACTS, 'heading': '', 'body': '\n'.join(lines), 'layout': 'text', 'items': []})
    for section in sections:
        if section.get('id') == FACTS:
            continue
        part = entry.part(section.get('id'))
        heading = str(section.get('heading') or '').strip()
        if part and part.get('heading_mode') == 'fixed' and part.get('heading'):
            heading = part['heading'].get(locale) or part['heading']['en']
        items = [item for item in section.get('items') or [] if isinstance(item, dict)]
        rows = [' — '.join(str(item.get(key) or '').strip() for key in ('label', 'text', 'value')
                           if str(item.get(key) or '').strip()) for item in items]
        body = '\n'.join(line for line in [str(section.get('body') or '').strip(), *rows] if line)
        if body or heading:
            made.append({'id': str(section.get('id')), 'heading': heading, 'body': body, 'layout': 'text',
                         'items': []})
    title = str(content.get('title') or '').strip() or entry.name(locale)
    return {**content, 'title': title, 'sections': made or [{'id': 'empty', 'heading': '', 'body': title,
                                                            'layout': 'text', 'items': []}],
            'questions': content.get('questions') or []}


def _emergency(content, path, locale, entry, template_id, pages, fallback, reason):
    """The emergency fallback's artifact, marked `template_fallback`; the reason is logged, never a value."""
    if fallback is not None:
        artifact = fallback(content, path)
    else:
        from ..categories import finish
        from ..rendering import render_pdf
        drawn = None
        if hasattr(finish, 'plain'):
            try:
                drawn = finish.plain({'options': {'category': entry.id, 'length': pages}, 'output_locale': locale,
                                      'content': content}, content)
            except Exception as error:
                log.warning('Paper %s: finish.plain failed (%s); the engine projects the paper itself', entry.id,
                            registry.described(error))
        drawn = drawn or plain(content, entry, locale)
        more = {}
        if 'pages' in inspect.signature(render_pdf).parameters:
            more['pages'] = max(len(drawn['sections']), int(pages or 1) + 1)
        artifact = render_pdf(drawn, path, locale, 'user_document', **more)
    metadata = artifact.setdefault('metadata', {})
    metadata.update(category=entry.id, template=template_id, fit_step=None, template_fallback=True)
    metadata['warnings'] = list(dict.fromkeys([*(metadata.get('warnings') or ()), TEMPLATE_FALLBACK]))
    log.info('Paper %s: emergency fallback (%s)', entry.id, reason)
    return artifact
