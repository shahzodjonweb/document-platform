"""Process variants: steps as chevrons."""
from . import variant
from .kit import FOOT, LEFT, WIDTH, block, chevron_points, entries, header, polygon, split, text


@variant('process', 'chevrons')
def chevrons(ctx, section, lines):
    """A row of interlocking chevrons, one per step and numbered; the step's name and sentence under it."""
    top = header(ctx, section)
    steps = entries('process', section)
    point, gap = 0.32, 0.08
    # Each chevron's notch takes the one before it's tip, `gap` apart.
    spans = split(LEFT, WIDTH, len(steps), gap - point)
    step = spans[1][0] - spans[0][0] if len(spans) > 1 else WIDTH
    for position, (item, (x, width)) in enumerate(zip(steps, spans)):
        fill, ink = ('accent', 'on_accent') if position % 2 == 0 else ('deep', 'on_deep')
        polygon(ctx, chevron_points((x, top + 0.05, width, 0.72), point, notch=position > 0), fill)
        inset = point + 0.06 if position > 0 else 0.2
        text(ctx, (x + inset, top + 0.13, width - inset - point - 0.06, 0.56), f'{position + 1:02d}', size=20,
             colour=ink, bold=True, heading=True, anchor='middle')
        block(ctx, (x + 0.04, top + 0.98, step - 0.3, FOOT - top - 1.0), [
            dict(text=item['label'], words=7, size=17, floor=13, colour='ink', bold=True, heading=True, after=6),
            dict(text=item.get('text'), words=22, size=14, floor=12, colour='muted'),
        ])
