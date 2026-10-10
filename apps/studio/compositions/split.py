"""Split: a colour block holds the title; the other side is pattern or photograph.

Cover and closing are split down the slide: a full-height block in the accent
with the title, a rule and the subtitle in the ink that reads on it, and on
the other side the design's pattern, a large soft disc, or the cover photo.
Dividers fill the slide with the accent and set the section number large.
Content slides carry a broad accent spine down the left.
"""
from . import NUMBER, FOOTER, SLIDE_H, SLIDE_W, Composition, Plan, Text, composition

BLOCK = 6.1      # the cover block's width
BAND_END = 6.62  # blocks stop above the footer row, which stays on the surface


@composition
class Split(Composition):
    name = 'split'

    def ground(self, canvas, kind, photo=False):
        if kind == 'cover':
            return self._cover(canvas, photo, mirrored=False)
        if kind == 'closing':
            return self._cover(canvas, False, mirrored=True)
        if kind == 'section':
            return self._divider(canvas)
        canvas.background('surface')
        canvas.accent((0, 0, 0.42, SLIDE_H))
        canvas.rect((0.42, 0, 0.06, SLIDE_H), 'secondary')
        return None

    def _cover(self, canvas, photo, mirrored):
        canvas.background('surface')
        left = SLIDE_W - BLOCK if mirrored else 0
        canvas.accent((left, 0, BLOCK, BAND_END))
        other = 0 if mirrored else BLOCK
        width = SLIDE_W - BLOCK
        if not photo:
            # The disc stays above the footer row, where the brand name sits on the surface.
            size = min(width * 0.78, BAND_END - 1.1)
            canvas.oval((other + (width - size) / 2, 0.55, size, size), 'accent_soft')
            canvas.art((other, 0, width, BAND_END), fade='down' if mirrored else 'left')
        text_left = left + 0.7
        return Plan(
            title=Text((text_left, 1.0, BLOCK - 1.3, 3.55), 'on_accent', 44, anchor='bottom', lines=4),
            rule=((text_left, 4.78, 1.1, 0.06), 'on_accent'),
            subtitle=Text((text_left, 5.0, BLOCK - 1.3, 1.25), 'on_accent', 17, anchor='top'),
            quiet='muted',
            photo=(BLOCK, 0, SLIDE_W - BLOCK, BAND_END) if photo else None)

    def _divider(self, canvas):
        canvas.background('accent')
        canvas.accent((0, 0, SLIDE_W, SLIDE_H))
        canvas.art((8.4, 0, SLIDE_W - 8.4, SLIDE_H), fade='left', colour='on_accent', strength=0.18)
        return Plan(
            eyebrow=Text((0.85, 0.7, 4.0, 2.0), 'on_accent', 88, anchor='top', numeral=True),
            title=Text((0.85, 3.0, 7.4, 2.4), 'on_accent', 40, anchor='top', lines=3),
            title_with_kicker=Text((0.85, 3.0, 7.4, 1.9), 'on_accent', 38, anchor='top', lines=2),
            kicker=Text((0.85, 5.05, 7.4, 0.9), 'on_accent', 17, anchor='top'),
            quiet='on_accent')
