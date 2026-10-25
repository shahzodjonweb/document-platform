"""Variants: many ways to draw each content layout, so no two decks look alike.

A layout (apps/studio/layouts.py) is what a slide says — a process of four
steps, three figures, a quote. It used to have one drawer
(apps/studio/slide_layouts.py), so every process slide of every deck was the
same row of numbered circles, whatever the design. A variant is another way to
draw the same content: chevrons, a staircase, a ring of steps, a dark panel
beside the list. The content and its fields do not change, so the model, the
outline editor and revisions know nothing about variants; only the renderer
chooses.

How a slide gets its variant (`choose`):

* **Only a designed deck wears them.** A deck without a design
  (deck_designs.look()['id'] == '') is drawn exactly as before, by the classic
  drawers.
* **Each deck has its own order.** The variants of a layout are ranked by a
  hash of the deck's seed (its design and title), so two decks rarely share a
  look, and the same deck draws the same way every time it is rendered.
* **A deck does not repeat itself.** The second process slide takes the next
  variant in the deck's order, not the first one again.
* **A variant must hold the slide whole.** Before a variant is used it is
  drawn once on a scratch slide; if it would cut a word, set a list well below
  the deck's size, or fail, the next one is tried, and the classic drawer —
  always in every pool, as the variant `classic` — is the last resort. A
  variant is never the reason a deck loses text.

Every variant draws only inside the content frame (`kit.FRAME`): the area
between the eyebrow and the footer that every composition keeps on the surface
colour. Covers, dividers and closing slides stay the compositions'.
tests/test_slide_variants.py fills each variant to its layout's guide in
English, Russian and Uzbek and checks it in every theme with
compositions.check; `python -m apps.studio.variants.bench` does the same and
draws contact sheets when designing one.
"""
import hashlib
import importlib
import logging
import pkgutil
import re
from pathlib import Path

log = logging.getLogger(__name__)

# The content layouts variants are drawn for. Covers, dividers and closing
# slides are arranged by the deck's composition; questions keep their drawer.
KINDS = ('agenda', 'bullets', 'two_column', 'statement', 'quote', 'big_number', 'stats', 'timeline', 'process',
         'comparison', 'pros_cons', 'cards', 'matrix', 'chart', 'table', 'image_split', 'image_full')
CLASSIC = 'classic'

# kind -> {name: Variant}; filled as each kind's modules are imported.
VARIANTS = {}
_LOADED = set()
_MODULE = re.compile(r'(?P<kind>[a-z_]+?)(?:_\d+)?')

# What a variant's `counts` counts, per layout: the entries the classic
# drawer itself draws, so a variant sees the same slide it does.
LABELLED = {'agenda': 6, 'process': 5, 'cards': 6, 'matrix': 4}
LINES = ('bullets', 'image_split', 'image_full', 'statement')


class Variant:
    """One way to draw a layout: `draw(ctx, section, lines)`, like a classic drawer.

    `counts` is the range of entries it is drawn for (None: any the layout
    accepts); `accepts(section, lines)` any further condition. `photo` is
    where a photo layout's picture goes, in inches, if not where the classic
    drawer puts it.
    """

    __slots__ = ('kind', 'name', 'draw', 'counts', 'accepts', 'photo')

    def __init__(self, kind, name, draw, counts=None, accepts=None, photo=None):
        self.kind, self.name, self.draw = kind, name, draw
        self.counts, self.accepts, self.photo = counts, accepts, photo

    @property
    def id(self):
        return f'{self.kind}.{self.name}'

    def holds(self, section, lines):
        """Whether this variant is drawn for this content at all (before trying it)."""
        if self.counts:
            low, high = self.counts
            if not low <= count(self.kind, section, lines) <= high:
                return False
        return self.accepts is None or bool(self.accepts(section, lines))

    def __repr__(self):
        return f'<Variant {self.id}>'


def variant(kind, name, *, counts=None, accepts=None, photo=None):
    """Register the decorated drawer as variant `name` of layout `kind`."""
    if kind not in KINDS:
        raise ValueError(f'variants are drawn for content layouts only, not {kind!r}')
    if not re.fullmatch(r'[a-z][a-z0-9_]*', name) or name == CLASSIC:
        raise ValueError(f'bad variant name {name!r}')

    def register(function):
        pool = VARIANTS.setdefault(kind, {})
        if name in pool:
            raise ValueError(f'variant {kind}.{name} is registered twice')
        pool[name] = Variant(kind, name, function, counts, accepts, photo)
        return function
    return register


def count(kind, section, lines):
    """How many entries this slide has, as its layout's drawer counts them."""
    if kind in LINES:
        return len(lines)
    items = section.get('items') or []
    if kind in LABELLED:
        return len([item for item in items if item.get('label')][:LABELLED[kind]])
    if kind == 'two_column':
        return 2 if titled(section) else len(lines)
    if kind == 'timeline':
        return len(items[:6])
    return len(items)


def titled(section):
    """A two_column slide's two titled columns, or None when it splits its lines instead."""
    pair = [item for item in section.get('items') or [] if item.get('label') and item.get('text')]
    return pair if len(pair) == 2 and section.get('layout') == 'two_column' else None


# ---------------------------------------------------------------- catalogue


def _modules():
    folder = Path(__file__).resolve().parent
    for module in sorted(pkgutil.iter_modules([str(folder)]), key=lambda found: found.name):
        match = _MODULE.fullmatch(module.name)
        if match and match.group('kind') in KINDS:
            yield match.group('kind'), module.name


def load(kind):
    """Import `kind`'s variant modules (only those) and return its pool, classic included.

    A module that fails to import is logged and left out: a broken variant
    never costs a deck (tests/test_slide_variants.py imports every one).
    """
    if kind not in _LOADED:
        for owner, name in _modules():
            if owner == kind:
                load_module(name)
        _LOADED.add(kind)
        _classic(kind)
    return VARIANTS.get(kind, {})


def load_module(name):
    """Import one variant module, e.g. 'cards_2'; False if it failed."""
    try:
        importlib.import_module(f'{__name__}.{name}')
    except Exception:
        log.exception('Variant module %s failed to import', name)
        return False
    return True


def catalogue():
    """Every layout's pool of variants."""
    return {kind: load(kind) for kind in KINDS}


def _classic(kind):
    from ..slide_layouts import DRAW
    pool = VARIANTS.setdefault(kind, {})
    if CLASSIC not in pool and kind in DRAW:
        pool[CLASSIC] = Variant(kind, CLASSIC, DRAW[kind])


def get(variant_id):
    """The variant `kind.name`; KeyError if there is none.

    A variant already imported is returned without importing its layout's
    other modules, so one module can be drawn while another is being written.
    """
    kind, _, name = str(variant_id).partition('.')
    if kind not in KINDS:
        raise KeyError(variant_id)
    if name == CLASSIC:
        _classic(kind)
    pool = VARIANTS.get(kind, {})
    return pool[name] if name in pool else load(kind)[name]


# ---------------------------------------------------------------- choice


def seed(look, content):
    """What orders a deck's variants: its design and its title, so a revision keeps them."""
    return f'{look.get("id", "")}|{" ".join(str(content.get("title") or "").split()).lower()}'


def _rank(deck_seed, kind, name):
    return hashlib.sha256(f'{deck_seed}|{kind}|{name}'.encode()).hexdigest()


def order(kind, deck_seed):
    """`kind`'s variant names in this deck's own order."""
    return sorted(load(kind), key=lambda name: _rank(deck_seed, kind, name))


def choose(kind, section, lines, *, deck_seed, taken, trial):
    """The variant this slide is drawn with.

    `taken` maps a layout to the variants the deck has used so far (it is
    updated); `trial(variant)` draws one on a scratch slide and says whether it
    held the slide whole. The deck's order is walked from its first unused
    variant; one that does not hold is skipped, and classic always holds.
    """
    pool = load(kind)
    if not pool:
        return None
    used = taken.setdefault(kind, [])
    names = order(kind, deck_seed)
    names = [name for name in names if name not in used] + [name for name in names if name in used]
    chosen = pool.get(CLASSIC)
    for name in names:
        candidate = pool[name]
        if name == CLASSIC:
            chosen = candidate
            break
        try:
            if candidate.holds(section, lines) and trial(candidate):
                chosen = candidate
                break
        except Exception:  # a variant that cannot draw this slide never costs the deck
            log.exception('Variant %s failed on a trial slide', candidate.id)
    if chosen is not None:
        used.append(chosen.name)
    return chosen


class Scratch:
    """A throwaway presentation that variants are tried on before a slide is drawn."""

    def __init__(self, width, height):
        self.width, self.height, self._deck = width, height, None

    def slide(self):
        if self._deck is None:
            from pptx import Presentation
            self._deck = Presentation()
            self._deck.slide_width, self._deck.slide_height = self.width, self.height
        return self._deck.slides.add_slide(self._deck.slide_layouts[6])
