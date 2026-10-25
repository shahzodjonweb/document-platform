"""Bullets variants: the heading on a panel of its own."""
from . import variant
from .kit import FOOT, LEFT, RIGHT, bullets, eyebrow, headline, inks, rect, rule, strong


@variant('bullets', 'night_panel')
def night_panel(ctx, section, lines):
    """The heading on a deep panel down the left of the frame; the list beside it, the full height."""
    width, panel = 3.9, inks(strong(ctx))
    rect(ctx, (LEFT, 0.62, width, FOOT - 0.62), panel['fill'])
    eyebrow(ctx, (LEFT + 0.35, 0.9, width - 0.7, 0.3), colour=panel['muted'])
    rule(ctx, (LEFT + 0.35, 1.3, 0.9, 3 / 72), colour=panel['ink'])
    headline(ctx, section, (LEFT + 0.35, 1.5, width - 0.7, 4.6), size=30, lines=6, anchor='top',
             colour=panel['ink'])
    bullets(ctx, (LEFT + width + 0.55, 0.95, RIGHT - LEFT - width - 0.55, FOOT - 1.05), lines)
