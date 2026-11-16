"""The story of a paper and the three page rules that hold it to its length (architecture 6.4).

`story(ctx, places, failed)` calls each placement's block (registry.draw) in
flow order, skips one whose `when` does not hold, starts a page where the
flow says so, and joins consecutive placements that share a `keep` tag into
one `Closing`: they never separate across a page, and the last lines of the
paragraph before them travel with them (blocks.json `keep_group`, two lines
unless the group's first placement says `tail_lines`), as an official
paper's overflow page carries the end of the request with the enclosures and
the signatures. A placement in `failed` broke the layout of an earlier build
and is drawn by its plain fallback.

`fit(make, rule, steps, quoted)` chooses the build that is delivered. `make(step,
ratio)` builds the paper at ladder step `step` (0 the loosest) with its
elastic prose cut to `ratio` of its sentences (None: whole):

- `fixed` (an ariza, a letter): the first step that gives the rule's pages
  wins; when none does, the tightest, one page more with the closing group
  whole, and `longer_than_quoted`. Text is never cut.
- `flow` (a test, every ceiling paper): the loosest step, tighter only while
  the paper runs past the quote (`pages + 1`); never cut, never padded.
- `count` (the papers that fill their count): the first step within the
  count; else the tightest with the elastic prose cut sentence by sentence,
  marked as cut (rendering._trimmed, `shortened_to_fit`), unless the rule
  says `trim: false`. Front and back matter are inside the count because the
  whole paper is built and counted.

Under every rule a last page filled less than `stub_min` is pulled back by a
tighter step when one gives fewer pages.
"""
from dataclasses import dataclass

from reportlab.platypus import KeepTogether, PageBreak, Paragraph
from reportlab.platypus.flowables import Flowable, _listWrapOn

from . import registry
from .ctx import holds
from .page import Mark

TAIL_LINES = 2
TRIM_ROUNDS = 7
TRIM_FLOOR = 0.25
LONGER = 'longer_than_quoted'
SHORTENED = 'shortened_to_fit'


class Closing(Flowable):
    """A keep group with the paragraph before it: never separated, the paragraph's last lines going with it.

    It is never drawn itself. Its wrap asks for more room than any frame has,
    so the frame always splits it, and the split decides: everything here when
    it fits; else the paragraph's head here and its last `tail` lines with the
    group on the next page; else everything on the next page. On a page that
    cannot hold it even when empty it gives up and flows, so a group taller
    than a page still prints.
    """

    def __init__(self, lead, group, tail, frame_height):
        super().__init__()
        self.lead, self.group, self.tail, self.frame_height = lead, list(group), tail, frame_height

    def _flowables(self):
        return ([self.lead] if self.lead is not None else []) + self.group

    def wrap(self, width, height):
        return width, 0xffffff

    def split(self, width, height):
        everything = self._flowables()
        _, need = _listWrapOn(everything, width, self.canv)
        if need <= height + 1e-6 or height >= self.frame_height - 1:
            return everything
        if self.lead is None:
            return []
        _, group = _listWrapOn(self.group, width, self.canv)
        leading = self.lead.style.leading
        self.lead.wrap(width, height)
        lines = len(getattr(self.lead.blPara, 'lines', ()) or ())
        head = min(lines - self.tail, int((height - self.lead.getSpaceBefore()) // leading))
        if head < 1:
            return []
        parts = self.lead.split(width, head * leading + self.lead.getSpaceBefore() + 0.5)
        if len(parts) != 2:
            return []
        return [parts[0], Closing(parts[1], self.group, self.tail, self.frame_height)]

    def draw(self):
        pass


def _mark(made, indexes):
    """The Mark before a placement, keeping a heading before it with what follows (a Mark must not break the chain)."""
    mark = Mark(indexes)
    if made and made[-1].getKeepWithNext():
        mark.keepWithNext = 1
    return mark


def story(ctx, places, failed=frozenset(), dropped=frozenset()):
    """The flowables of a paper, in flow order; see the module's docstring.

    A placement in `dropped` broke the layout even drawn plain: it is left out,
    still recorded as `block_fallback:<name>`.
    """
    made, keeping = [], None

    def close():
        nonlocal keeping
        if keeping is None:
            return
        _, indexes, group, tail = keeping
        keeping = None
        if not group:
            return
        lead = None
        if tail > 0 and made and isinstance(made[-1], Paragraph):
            lead = made.pop()
        made.append(_mark(made, indexes))
        made.append(Closing(lead, group, tail, ctx.frame_height) if lead is not None or len(group) > 1
                    else KeepTogether(group))

    for place in places:
        if not holds(place.when, ctx, place):
            continue
        if place.index in dropped:
            ctx.warn(f'block_fallback:{place.block}')
            continue
        flowables = registry.draw(ctx, place, plain_only=place.index in failed)
        if place.page_break_before:
            close()
            if made:
                made.append(PageBreak())
        if place.keep:
            if keeping is not None and keeping[0] != place.keep:
                close()
            if keeping is None:
                tail = place.params.get('tail_lines', TAIL_LINES) if isinstance(place.params, dict) else TAIL_LINES
                keeping = (place.keep, (), [], int(tail))
            keeping = (keeping[0], keeping[1] + (place.index,), keeping[2] + flowables, keeping[3])
            continue
        close()
        made.append(_mark(made, (place.index,)))
        made.extend(flowables)
    close()
    return made


# ---------------------------------------------------------------- page rules


@dataclass
class Choice:
    """The build to deliver and what the rule says of it."""

    attempt: object
    step: int
    ratio: float | None
    codes: list


def fit(make, rule, steps, quoted):
    """The build a page rule delivers: a Choice. `make(step, ratio)` returns an object with `pages` and `fill`."""
    kind = rule.get('kind', 'flow')
    quoted = max(1, int(quoted or 1))
    codes = []
    made = {}

    def at(step, ratio=None):
        if (step, ratio) not in made:
            made[(step, ratio)] = make(step, ratio)
        return made[(step, ratio)]
    tightest = steps - 1
    chosen = None
    if kind == 'fixed':
        target = int(rule.get('pages') or quoted)
        chosen = next(((step, None) for step in range(steps) if at(step).pages <= target), None)
        if chosen is None:
            chosen = (tightest, None)
            codes.append(LONGER)
    elif kind == 'count':
        target = quoted
        chosen = next(((step, None) for step in range(steps) if at(step).pages <= target), None)
        if chosen is None and rule.get('trim', True):
            low, high, found = TRIM_FLOOR, 1.0, None
            for _ in range(TRIM_ROUNDS):
                middle = round((low + high) / 2, 4)
                if at(tightest, middle).pages <= target:
                    low, found = middle, middle
                else:
                    high = middle
            if found is None and at(tightest, TRIM_FLOOR).pages <= target:
                found = TRIM_FLOOR
            if found is not None:
                chosen = (tightest, found)
                codes.append(SHORTENED)
        if chosen is None:
            chosen = (tightest, None)
            codes.append(LONGER)
    else:
        target = quoted + 1
        step = 0
        while at(step).pages > target and step < tightest:
            step += 1
        chosen = (step, None)
        if at(step).pages > target:
            codes.append(LONGER)
    step, ratio = chosen
    stub = rule.get('stub_min')
    if stub and at(step, ratio).pages > 1 and at(step, ratio).fill < stub:
        for tighter in range(step + 1, steps):
            if at(tighter, ratio).pages < at(step, ratio).pages:
                step = tighter
                if LONGER in codes and at(step, ratio).pages <= target:
                    codes.remove(LONGER)
                break
    return Choice(at(step, ratio), step, ratio, codes)
