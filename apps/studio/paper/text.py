"""text_rules: the one pass every string a paper block draws goes through.

A category paper is a printed form: a clerk reads it and a customer signs it.
So the text is set as a typesetter would set it, whatever the model or the
customer typed:

- a character the face cannot draw is written as the text that says the same
  (→ as –) or left out, and counted, never printed as an empty box: the CV's
  cleaner (cv.render._Cleaner), over the coverage of the template's face;
- Uzbek apostrophes are the house ones, ‘ in o‘ and g‘ and ’ for the tutuq;
- a no-break space glues an initial to what follows it ("B. A. Rahimova"), a
  number to its word ("35 daqiqa", "№ 5", "1 150 000") and a dash to the word
  before it, so no line starts with "A." alone, a unit or a dash;
- a run of underscores is a blank to fill in by hand. It is drawn as a rule of
  one of three widths (a day, a number, a name: blocks.json `inline_blank`)
  made of no-break spaces under an underline, so it is never broken across
  lines and holds the width the hand needs whatever the font size.

`markup` returns Paragraph markup: everything else is escaped, so text is
always text and never a tag. Nothing here adds a word.
"""
import re
import unicodedata
from xml.sax.saxutils import escape

from reportlab.pdfbase.pdfmetrics import stringWidth

from ..uzbek import TURNED

NBSP = ' '
MM = 72 / 25.4
# Underscores of an inline blank, and the widths they draw at (blocks.json
# inline_blank: a day, a number, a name). The run's length picks the width:
# 2-3 a day, 4-12 a number or a word, 13 and more a name or a line.
BLANK_RUN = re.compile(r'_{2,}')
WIDTHS_MM = (9, 28, 55)
# The run each kind of field draws when it has no value, by the width it needs.
RUNS = {'day': '___', 'number': '_' * 8, 'name': '_' * 16}
SHORT_KINDS = frozenset(('date', 'number', 'money', 'ref', 'phone', 'choice', 'flag'))
# The tutuq belgisi between two letters, typed with whatever was to hand; o‘ and g‘ are TURNED's.
TUTUQ = re.compile(r"(?<=[^\W\d_])['ʼ`´](?=[^\W\d_])")
UPPER = 'A-ZА-ЯЁЎҚҒҲ'
# "B. A. Rahimova": the space after a capital initial, before another initial or a name.
INITIAL = re.compile(rf'(?<![^\W\d_])([{UPPER}]\.)[ ]+(?=[{UPPER}])')
# "35 daqiqa", "2026 yil", "5 ta": a number and the short word after it.
UNIT = re.compile(r'(?<=\d)[ ]+(?=[^\W\d_]{1,12}(?![^\W\d_]))')
# "1 150 000": the groups of a number.
GROUPS = re.compile(r'(?<=\d)[ ]+(?=\d{3}(?!\d))')
# "№ 5", "No. 5", "p. 12".
NUMBERED = re.compile(r'(№|No\.|Nr\.|p\.|b\.|стр\.|с\.)[ ]+(?=\d)')
# A dash after a space starts no line.
DASH = re.compile(r'[ ]+(?=[–—](?:\s|$))')


def width_mm(run):
    """The width a blank of this many underscores is drawn at."""
    return WIDTHS_MM[0] if run <= 3 else WIDTHS_MM[1] if run <= 12 else WIDTHS_MM[2]


def run_for(kind):
    """The underscores a field of this kind draws when it has no value: a number's width or a name's."""
    return RUNS['number'] if kind in SHORT_KINDS else RUNS['name']


class Rules:
    """text_rules for one face and language. `dropped` holds the characters the face could not draw."""

    def __init__(self, family, locale):
        from ..cv import fonts
        from ..cv.render import _Cleaner
        fonts.register()
        self.family, self.locale = family, locale
        self.cleaner = _Cleaner(fonts.coverage(family))

    @property
    def dropped(self):
        return self.cleaner.dropped

    def plain(self, value):
        """The text as the face draws it, apostrophes and glue applied; lines kept, spaces single."""
        text = self.cleaner(unicodedata.normalize('NFC', str(value if value is not None else '')))
        if self.locale == 'uz':
            text = TUTUQ.sub('’', TURNED.sub('‘', text))
        for pattern, glue in ((INITIAL, r'\1' + NBSP), (NUMBERED, r'\1' + NBSP)):
            text = pattern.sub(glue, text)
        for pattern in (GROUPS, UNIT, DASH):
            text = pattern.sub(NBSP, text)
        return text

    def markup(self, value, *, font, size, room=None):
        """`value` as Paragraph markup in `font` at `size`: escaped, blanks drawn as rules no wider than `room`."""
        text = self.plain(value)
        space = stringWidth(NBSP, font, size) or size * 0.25
        out, last = [], 0
        for found in BLANK_RUN.finditer(text):
            out.append(escape(text[last:found.start()]))
            width = width_mm(len(found.group(0))) * MM
            if room:
                width = min(width, room * 0.9)
            count = max(2, round(width / space))
            out.append(f'<u width="{max(0.4, size * 0.045):.2f}" offset="{-size * 0.2:.2f}">{NBSP * count}</u>')
            last = found.end()
        out.append(escape(text[last:]))
        return ''.join(out).replace('\n', '<br/>')
