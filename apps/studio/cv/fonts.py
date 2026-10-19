"""The two type families a CV is set in, and what they can draw.

A CV is set in Noto Sans and Noto Serif, bundled in `processors/assets/fonts/`
(SIL OFL 1.1, see NOTICE.txt there). Both cover Latin, Cyrillic, the Uzbek
letters and the apostrophes Uzbek is written with, in regular, bold and italic,
so a CV in any of the three languages never falls back to a font that is not in
the file. They are registered under our own names (`CVSans`, `CVSerif`) and as
families, so `<b>` and `<i>` inside a paragraph pick the right face.

`coverage()` is what the renderer reads before setting text: a character no face
can draw (an emoji, an icon a model put next to a phone number) is left out
rather than printed as an empty box.
"""
import functools
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FOLDER = ROOT / 'processors' / 'assets' / 'fonts'
FACES = {
    'CVSans': 'NotoSans-Regular.ttf', 'CVSans-Bold': 'NotoSans-Bold.ttf', 'CVSans-Italic': 'NotoSans-Italic.ttf',
    'CVSerif': 'NotoSerif-Regular.ttf', 'CVSerif-Bold': 'NotoSerif-Bold.ttf', 'CVSerif-Italic': 'NotoSerif-Italic.ttf',
}
FAMILIES = ('CVSans', 'CVSerif')
# What every face must be able to draw: Russian and Uzbek Cyrillic, the
# apostrophes of Uzbek Latin (o‘, g‘, the tutuq belgisi ʼ), the dashes, bullet,
# middle dot, numero sign and no-break space a CV uses, and Latin-1 plus
# Latin Extended-A for names from anywhere in Europe.
GLYPHS = frozenset(
    [chr(code) for code in range(0x0410, 0x0450)]
    + list('ЁёЎўҚқҒғҲҳ')
    + ['‘', '’', 'ʻ', 'ʼ', '–', '—', '•', '·', '№', '\u00A0']
    + [chr(code) for code in range(0x20, 0x7F)]
    + [chr(code) for code in range(0xA0, 0x180)]
)


def path(face):
    return FOLDER / FACES[face]


def register():
    """Register the six faces and both families once per process."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    known = set(pdfmetrics.getRegisteredFontNames())
    for face in FACES:
        if face not in known:
            pdfmetrics.registerFont(TTFont(face, str(path(face))))
    for family in FAMILIES:
        if family not in known:
            # There is no bold italic file: a bold italic run is set in bold.
            pdfmetrics.registerFontFamily(family, normal=family, bold=f'{family}-Bold',
                                          italic=f'{family}-Italic', boldItalic=f'{family}-Bold')


@functools.lru_cache(maxsize=8)
def coverage(face):
    """The code points `face` has a glyph for; a family name means all three of its faces."""
    from reportlab.pdfbase.ttfonts import TTFontFile
    if face not in FACES:
        raise KeyError(face)
    faces = [name for name in FACES if name.split('-')[0] == face] if face in FAMILIES else [face]
    found = None
    for name in faces:
        mapped = frozenset(TTFontFile(str(path(name))).charToGlyph)
        found = mapped if found is None else found & mapped
    return found


@functools.lru_cache(maxsize=1)
def internal_names():
    """The PostScript name each bundled file carries, as a PDF reader reports it after the subset tag."""
    from reportlab.pdfbase.ttfonts import TTFontFile
    names = {}
    for face in FACES:
        name = TTFontFile(str(path(face))).name
        names[face] = name.decode() if isinstance(name, bytes) else str(name)
    return names
