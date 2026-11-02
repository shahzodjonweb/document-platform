"""The faces a generated deck is measured with and LibreOffice draws it with.

A .pptx only names its faces, and the server has none of them, so fit was
measured in one face and previewed in whatever stood in. Here each deck face has
one stand-in that both use, on every machine, from files we ship. Only deck
conversions get them (`write_fontconfig`): installed system-wide they would move
LibreOffice's stand-ins for customers' own Word and PowerPoint files, whose text
would reflow and whose page counts could change.

A stand-in is a list: a letter is drawn in the first family that has it. Caladea
has no Cyrillic and no U+02BC, so a Cambria heading in Russian is Noto Serif and
its digits Caladea; LibreOffice's glyph fallback and slides._face_units agree.

Real widths over the stand-in's, Regular on en/ru/uz sentences, measured against
Office's own faces (Microsoft PowerPoint for Mac, November 2026), to be read
against slides.WIDTH_SAFETY, 1.10:

    Calibri     Carlito      1.000 1.000 1.000   metric twin, Cyrillic too
    Arial       Liberation   1.000 1.000 1.000   metric twin, Cyrillic too
    Corbel      Carlito      1.004 1.009 1.007
    Candara     Carlito      1.033 1.020 1.027
    Cambria     Caladea      1.045 0.898 1.036   not a twin of Cambria 6.90; Russian is Noto Serif, wider than the real
    Trebuchet   Noto Sans    0.964 0.949 0.973   Carlito would be 1.11, past the margin
    Georgia     Noto Serif   0.921 0.915 0.921
    Constantia  Noto Serif   0.911 0.899 0.904

So on Latin Cambria sentences a real viewer takes up to 4.5% more room than the
measure before the margin, which leaves 5% of it (3.6% in bold), and on Cyrillic
Cambria 10% less: the measure errs wide there, never narrow.

Sentences hide figures. Caladea's digits are 362-517 against Cambria's 554 each,
a '1' alone 1.53 of the measure, so a digit is measured no narrower than its
face's DIGIT_FLOORS, while LibreOffice still draws the stand-in's. The widest
digit over the measure then, Regular and Bold, to be read against 1.10 and against
1.166 (bold is measured as Regular times 1.06):

    Calibri 1.000 1.000    Corbel  1.035 1.097    Trebuchet 0.917 1.024    Georgia    1.020 1.165
    Arial   1.000 1.000    Candara 1.089 1.059    Cambria   0.999 1.069    Constantia 0.977 1.032
"""
from pathlib import Path
from xml.sax.saxutils import escape

FOLDER = Path(__file__).resolve().parent / 'assets' / 'fonts'
# The file that measures a family. Decks are set in Regular and Bold only: bold
# is measured as Regular times slide_layouts._text_lines's allowance.
FILES = {'Carlito': 'Carlito-Regular.ttf', 'Caladea': 'Caladea-Regular.ttf', 'Liberation Sans': 'LiberationSans-Regular.ttf',
         'Noto Sans': 'NotoSans-Regular.ttf', 'Noto Serif': 'NotoSerif-Regular.ttf'}
SANS = ('Carlito', 'Noto Sans')
STAND_INS = {'Calibri': SANS, 'Corbel': SANS, 'Candara': SANS,
             'Arial': ('Liberation Sans', 'Noto Sans'),
             'Trebuchet MS': ('Noto Sans',),
             'Cambria': ('Caladea', 'Noto Serif', 'Noto Sans'),
             'Georgia': ('Noto Serif', 'Noto Sans'), 'Constantia': ('Noto Serif', 'Noto Sans')}
OTHER = ('Noto Sans',)
# The least a digit measures in, in thousandths of the size: Cambria's own, and what Georgia's bold '0' (701) needs.
DIGIT_FLOORS = {'Cambria': 554, 'Georgia': 602}


def stand_in(face):
    """The families `face` is drawn and measured in; one this table has never heard of goes as Noto Sans."""
    return STAND_INS.get(face, OTHER)


def font_files():
    """Every file behind a deck's fit and drawing: what each family measures in, and the bold LibreOffice draws beside it."""
    return [FOLDER / name for regular in FILES.values() for name in (regular, regular.replace('Regular', 'Bold'))]


def _alias(family, kind, others):
    names = ''.join(f'<family>{escape(name)}</family>' for name in others)
    # `same` holds these as strongly as the family asked for: weaker, a font for the text's language beats them.
    return f'  <alias binding="same"><family>{escape(family)}</family><{kind}>{names}</{kind}></alias>\n'


def fontconfig_text(cache):
    """The system's fonts for everything else (a slide in Arabic still draws), our folder, and the stand-ins first."""
    aliases = [_alias(face, 'prefer', families) for face, families in STAND_INS.items()]
    # Asked for a letter the first family lacks, LibreOffice may name that family rather than the deck's.
    aliases += [_alias(first, 'accept', others) for first, others in {families[0]: families[1:] for families in STAND_INS.values() if families[1:]}.items()]
    return ('<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n<fontconfig>\n'
            '  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>\n'
            f'  <dir>{escape(str(FOLDER))}</dir>\n  <cachedir>{escape(str(cache))}</cachedir>\n'
            + ''.join(aliases) + '</fontconfig>\n')


def write_fontconfig(folder):
    """A fontconfig file inside `folder`, for one conversion's FONTCONFIG_FILE; its cache stays in `folder` too."""
    path = Path(folder) / 'deck-fonts.conf'
    path.write_text(fontconfig_text(Path(folder) / 'fontconfig'), encoding='utf-8')
    return path
