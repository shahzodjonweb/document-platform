"""The story of a paper and the three page rules that hold it to its length (architecture 6.4).

`story(ctx, places, failed)` calls each placement's block (registry.draw) in
flow order, skips one whose `when` does not hold, starts a page where the
flow says so, and joins consecutive placements that share a `keep` tag into
one `Closing`: they never separate across a page, and the last lines of the
paragraph before them travel with them (blocks.json `keep_group`), as an
official paper's overflow page carries the end of the request with the
enclosures and the signatures. How many lines is the group's first
placement's `tail_lines`; without it two for the `closing` tag and none for
any other, so a test's passage group never pulls the last option of the
question before it onto the next page. The paragraph is the last Paragraph
of the story before the group, past any Spacer after it. A placement in
`failed` broke the layout of an earlier build and is drawn by its plain
fallback.

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

from reportlab.platypus import KeepTogether, PageBreak, Paragraph, Spacer
from reportlab.platypus.flowables import Flowable, _listWrapOn

from . import registry
from .ctx import holds
from .page import Mark

TAIL_LINES = 2
CLOSING = 'closing'
TRIM_ROUNDS = 7
TRIM_FLOOR = 0.25
LONGER = 'longer_than_quoted'
SHORTENED = 'shortened_to_fit'


class Closing(Flowable):
    """A keep group with the paragraph before it: never separated, the paragraph's last lines going with it.

    `before` is the keep-with-next run that ended the story before it (a
    heading, its anchor and marks): it travels with the paragraph's first
    lines, so a heading is never left at a page's foot and the chain of
    keep-with-next flowables never reaches this flowable, whose height is not
    a real one. `mark` is the group's Mark, laid out before the paragraph.

    It is never drawn itself. Its wrap asks for more room than any frame has,
    so the frame always splits it, and the split decides: everything here when
    it fits; else as many of the paragraph's lines as fit here, its last
    `tail` lines going on with the group (a paragraph taller than a page is
    cut again on the next one); else, when not one line fits here, everything
    on the next page. ReportLab lays out the first flowable of a split without
    splitting it, so each list returned starts with one that fits. When even
    an empty page cannot hold the group and there is no line to split, it
    gives up and flows, so a group taller than a page still prints.
    """

    def __init__(self, before, mark, lead, group, tail, frame_height):
        super().__init__()
        self.before, self.mark, self.lead, self.group = list(before), mark, lead, list(group)
        self.tail, self.frame_height = tail, frame_height

    def _flowables(self):
        return [*self.before, self.mark, *([self.lead] if self.lead is not None else []), *self.group]

    def wrap(self, width, height):
        return width, 0xffffff

    def split(self, width, height):
        everything = self._flowables()
        _, need = _listWrapOn(everything, width, self.canv)
        if need <= height + 1e-6:
            return everything
        if self.lead is not None:
            parts = self._head(width, height)
            if parts:
                return parts
        return everything if height >= self.frame_height - 1 else []

    def _head(self, width, height):
        """The run before, the paragraph's lines that fit here, and a Closing of the rest; None when no line fits."""
        lead = self.lead
        _, above = _listWrapOn([*self.before, self.mark], width, self.canv)
        lead.wrap(width, height)
        lines = len(getattr(lead.blPara, 'lines', ()) or ())
        leading, space = lead.style.leading, lead.getSpaceBefore()
        head = min(lines - self.tail, int((height - above - space) // leading))
        # A paragraph refuses a split that leaves one line alone (orphans and widows): try one line fewer.
        for count in range(head, 0, -1):
            parts = lead.split(width, count * leading + space + 0.5)
            if len(parts) == 2:
                rest = Closing((), Mark(self.mark.indexes), parts[1], self.group, self.tail, self.frame_height)
                return [*self.before, self.mark, parts[0], rest]
        return None

    def draw(self):
        pass


def _real(flowable):
    """Whether a flowable prints or takes room: not a Mark or an Anchor, not a page break."""
    return not getattr(flowable, '_ZEROSIZE', 0) and not isinstance(flowable, PageBreak)


def _mark(made, keys):
    """The Mark before a placement, keeping a heading before it with what follows (a Mark must not break the chain)."""
    mark = Mark(keys)
    if made and made[-1].getKeepWithNext():
        mark.keepWithNext = 1
    return mark


def _tail(place):
    """How many lines of the paragraph before a keep group travel with it: `tail_lines`, else two for a closing."""
    params = place.params if isinstance(place.params, dict) else {}
    return int(params.get('tail_lines', TAIL_LINES if place.keep == CLOSING else 0))


def story(ctx, places, failed=frozenset(), dropped=frozenset()):
    """The flowables of a paper, in flow order; see the module's docstring.

    `failed` and `dropped` hold placements as (flow index, instance), so a
    layout one chapter's table broke does not change the same placement in
    the other chapters. A placement in `dropped` broke the layout even drawn
    plain: it is left out, still recorded as `block_fallback:<name>`.
    """
    made, keeping = [], None

    def close():
        nonlocal keeping
        if keeping is None:
            return
        _, keys, group, tail = keeping
        keeping = None
        if not group:
            return
        # The lead is the paragraph the story ends with, past any Spacer after it (a block's gap); a heading
        # (keep-with-next) is no lead, it joins the run before.
        lead, gap, end = None, [], len(made)
        while tail > 0 and end and isinstance(made[end - 1], Spacer):
            end -= 1
        if tail > 0 and end and isinstance(made[end - 1], Paragraph) and not made[end - 1].getKeepWithNext():
            lead, gap = made[end - 1], made[end:]
            del made[end - 1:]
        before = []
        while made and made[-1].getKeepWithNext():
            before.insert(0, made.pop())
        made.append(Mark(keys))
        if lead is None and not before and len(group) == 1:
            made.append(KeepTogether(group))
        else:
            made.append(Closing(before, Mark(keys), lead, gap + group, tail, ctx.frame_height))

    for place in places:
        if not holds(place.when, ctx, place):
            continue
        key = (place.index, place.instance)
        if key in dropped:
            ctx.warn(f'block_fallback:{place.block}')
            continue
        flowables = registry.draw(ctx, place, plain_only=key in failed)
        if place.page_break_before:
            close()
            # Only between two things that print: a placement that draws nothing, or one first in the paper,
            # starts no page (a blank last page would be one more than the paper has).
            if any(map(_real, flowables)) and any(map(_real, made)):
                made.append(PageBreak())
        if place.keep:
            if keeping is not None and keeping[0] != place.keep:
                close()
            if keeping is None:
                keeping = (place.keep, (), [], _tail(place))
            keeping = (keeping[0], keeping[1] + (key,), keeping[2] + flowables, keeping[3])
            continue
        close()
        made.append(_mark(made, (key,)))
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
    # The most pages the rule allows without `longer_than_quoted`.
    target: int = 0


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
    return Choice(at(step, ratio), step, ratio, codes, target)
