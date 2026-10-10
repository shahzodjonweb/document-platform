"""The arrangement every deck had before compositions: unchanged, for old decks and kept designs.

An accent bar down the left of every slide, the cover's title low on the left
with a disc bleeding off its corner, and a band across each divider. It returns
no plan: the cover, divider and closing drawers fall back to their own classic
layout (apps/studio/slide_layouts.py), and slides.render_pptx keeps the classic
photo and pattern placement.
"""
from pptx.enum.shapes import MSO_SHAPE

from . import Composition, composition


@composition
class Classic(Composition):
    name = 'classic'

    def ground(self, canvas, kind, photo=False):
        from .. import slides
        filled = kind in slides.FILLED
        canvas.background('cover_fill' if filled else 'surface')
        slides._shape(canvas.slide, slides.ZONES['accent_bar'], canvas.roles['accent'])
        if kind == 'cover' and not photo and not canvas.look.get('art'):
            slides._shape(canvas.slide, slides.ZONES['cover_mark'], canvas.roles['accent_soft'], MSO_SHAPE.OVAL)
        return None
