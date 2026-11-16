"""The paper blocks: what each block name of a template draws with, and how it is drawn plain.

A block module in `blocks/` registers its functions with `@block(name)`:

    @block('signature_row', fallback=signature_plain)
    def signature_row(ctx, place): ...

Every module in `blocks/` is imported when this one is, so `BLOCKS` names
every block this worker can draw: the catalogue's readiness gate and
`paper.ready` read it, and a template whose blocks are not all here is not
drawn by the engine.

A block that raises, at the call or later when its flowables are laid out,
is drawn by its `fallback` (blocks.json `plain_fallback`), or by `plain` when
it names none, and the build records `block_fallback:<name>`: the customer
gets the paper with that one part drawn simply, never a failed job.
"""
import importlib
import logging
import pkgutil
from dataclasses import dataclass
from typing import Callable

from reportlab.platypus import Paragraph, Spacer

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Block:
    name: str
    draw: Callable
    fallback: Callable | None = None


BLOCKS = {}


def block(name, *, fallback=None):
    """Register `function(ctx, place) -> [Flowable]` as the block `name`; `fallback` draws it plain."""
    def register(function):
        if name in BLOCKS and BLOCKS[name].draw is not function:
            raise ValueError(f'The paper block {name} is registered twice')
        BLOCKS[name] = Block(name, function, fallback)
        return function
    return register


def missing(names):
    """The block names of `names` this worker has not registered, sorted."""
    return sorted(set(names) - set(BLOCKS))


def plain(ctx, place):
    """Any placement drawn as plain lines: the part's heading, its text and rows, then its facts.

    Rows are "label — middle cells — value", so a table of any width loses no
    cell; a fact is "Label: value", with a blank where it has none and draws
    one. Nothing is drawn that the block would not have drawn.
    """
    story = []
    heading = ctx.heading(place.part, place.section)
    label = (place.params or {}).get('label')
    if not heading and isinstance(label, str) and label in (ctx.template.get('labels') or {}):
        heading = ctx.label(label)
    if heading:
        story.append(Paragraph(ctx.text(heading, 'bold'), ctx.styles['bold']))
    section = place.section or {}
    for line in str(section.get('body') or '').split('\n'):
        if line.strip():
            story.append(Paragraph(ctx.text(line.strip()), ctx.styles['body']))
    for item in section.get('items') or []:
        if not isinstance(item, dict):
            continue
        cells = [str(item.get(key) or '').strip() for key in ('label', 'text', 'value')]
        line = ' — '.join(cell for cell in cells if cell)
        if line:
            story.append(Paragraph(ctx.text(line), ctx.styles['body']))
    for field_id in place.fields:
        value = ctx.fact(field_id)
        if value is None and not ctx.blank(field_id):
            continue
        name = ctx.field_label(field_id)
        shown = value if value is not None else ctx.blank_run(field_id)
        story.append(Paragraph(ctx.text(f'{name}: {shown}' if name else shown), ctx.styles['body']))
    if story:
        story.append(Spacer(1, ctx.leading * 0.5))
    return story


def draw(ctx, place, *, plain_only=False):
    """The flowables of one placement: its block's, else its fallback's, recording `block_fallback:<name>`."""
    found = BLOCKS.get(place.block)
    if found is not None and not plain_only:
        try:
            return list(found.draw(ctx, place) or [])
        except Exception:
            log.exception('Paper block %s raised; drawn plain', place.block)
    ctx.warn(f'block_fallback:{place.block}')
    for fallback in ((found.fallback,) if found is not None and found.fallback else ()) + (plain,):
        try:
            return list(fallback(ctx, place) or [])
        except Exception:
            log.exception('The plain fallback of paper block %s raised', place.block)
    return []


def discover():
    """Import every module of `blocks/`, so each registers its blocks."""
    from . import blocks
    for module in pkgutil.iter_modules(blocks.__path__):
        if not module.name.startswith('_'):
            importlib.import_module(f'{blocks.__name__}.{module.name}')


discover()
