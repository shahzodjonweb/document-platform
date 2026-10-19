"""How a CV is set on A4: eight drawers built on ReportLab's page templates and frames.

Every drawer gets the same prepared CV (`render.prepare`) and the same type
scale for a fit step, and arranges them its own way:

* `column` — one column; name, headline and a contact line over an accent rule;
  headings in the accent with a thin rule in the second colour. A photo
  template puts a square portrait at the top right.
* `sidebar_left` / `sidebar_right` — a tinted (or, on dark templates, filled)
  strip the height of the page holding a round portrait, the contacts, skills,
  languages and certificates; the name and the career in the main column.
* `band` — a coloured band across the top of page 1 with the name, headline,
  contacts and a square portrait; below it the career and, in a narrow column
  on the right, skills, languages and certificates. Page 2 is one column.
* `centered` — everything centred above left-aligned entries; headings between
  hairlines.
* `timeline` — dates in a gutter on the left, a line with a dot for every role
  and degree, the text to the right of it.
* `compact` — a header across the page and two columns below it, for long
  careers that should still fit.
* `executive` — section headings in a left margin column, entries beside them.

Sidebar and band side columns are drawn on the canvas, not flowed: Platypus
only starts pages for the main story, so side content could never make a page
of its own. It is therefore measured before every build and bounded to page 1;
what does not fit moves into the main column as whole groups — certificates
first, then languages, then skills — and the contacts and the photo always
stay. Fills are always plain `canvas.rect`s, so `check.py` can read every
background back and test the contrast of the text on it.
"""
import io
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, FrameBreak, KeepTogether, NextPageTemplate,
                                PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle)

from . import fonts
from .templates import FONT_PAIRS

W, H = A4
MM = 72 / 25.4
INK = '#1A1A1A'
MUTED = '#5F6368'
WHITE = '#FFFFFF'
# Fit steps, loosest first: name, headline, heading, body, leading, item gap, section gap (pt).
STEPS = (
    (26, 12, 10.5, 10.0, 14.0, 2.5, 11),
    (25, 11.5, 10.2, 9.6, 13.3, 2.0, 9.5),
    (24, 11, 10.0, 9.3, 12.7, 1.8, 8.5),
    (23, 10.5, 9.6, 9.0, 12.2, 1.5, 7.5),
    (22, 10, 9.4, 8.8, 11.8, 1.2, 6.5),
)
MIN_BODY_SIZE = 8.8
MIN_LEADING = 11.8
# The order sections are read in, and the ones a side column holds.
ORDER = ('profile', 'experience', 'education', 'skills', 'languages', 'projects', 'certificates', 'extra')
SIDE = ('skills', 'languages', 'certificates')
# What leaves a full side column first: the least essential group.
MOVE_ORDER = ('certificates', 'languages', 'skills')
SIDEBARS = ('sidebar_left', 'sidebar_right')
# A compact CV's two columns on page 1, when everything fits without flowing on.
COMPACT_LEFT = ('profile', 'experience', 'projects', 'extra')
COMPACT_RIGHT = ('education', 'skills', 'languages', 'certificates')


# ------------------------------------------------------------------ colours

def _hex6(value):
    return str(value or '').lstrip('#').upper()


def _mix(one, two, amount):
    """`one` moved toward `two` by `amount` (0 keeps `one`, 1 is `two`)."""
    a, b = _hex6(one), _hex6(two)
    channel = lambda i: round(int(a[i:i + 2], 16) + (int(b[i:i + 2], 16) - int(a[i:i + 2], 16)) * amount)
    return '#%02X%02X%02X' % (channel(0), channel(2), channel(4))


def _reads(value, ground, target=4.6):
    from apps.studio.slides import _reads_on
    return '#' + _reads_on(_hex6(value), _hex6(ground), target)


def palette(look):
    """Every colour text or decoration is set in, each checked against the ground it sits on."""
    from apps.studio.slides import ink_on
    tone, drawer = look['tone'], look['drawer']
    paper = look['tint'] if tone == 'paper' and look['tint'] else WHITE
    accent = _reads(look['accent'], paper, 4.6)
    rule = '#' + _hex6(look['secondary']) if look['secondary'] else _mix(accent, paper, 0.55)
    colours = {'paper': paper, 'ink': INK, 'muted': _reads(MUTED, paper), 'accent': accent, 'rule': rule,
               'hairline': _mix(rule, paper, 0.25)}
    if drawer in SIDEBARS:
        dark = tone == 'dark'
        ground = look['fill'] if dark else (look['tint'] or _mix(accent, WHITE, 0.92))
        colours.update(side=ground, side_ink=WHITE if dark else INK,
                       side_muted=_reads(_mix(WHITE, ground, 0.28), ground) if dark else _reads(MUTED, ground),
                       side_accent=WHITE if dark else _reads(accent, ground, 4.6),
                       side_rule=('#' + _hex6(look['secondary'])) if look['secondary'] else
                       (_mix(WHITE, ground, 0.5) if dark else rule),
                       ring=('#' + _hex6(look['secondary'])) if look['secondary'] else WHITE)
    if drawer == 'band':
        ground = look['fill']
        text = '#' + ink_on(_hex6(ground))
        colours.update(band=ground, band_ink=text, band_muted=_reads(_mix(text, ground, 0.18), ground),
                       band_rule=('#' + _hex6(look['secondary'])) if look['secondary'] else _mix(text, ground, 0.5),
                       side=WHITE, side_ink=INK, side_muted=colours['muted'], side_accent=accent,
                       side_rule=rule)
    return colours


# ------------------------------------------------------------------ type

class Scale:
    """The type sizes and spacing of one fit step."""

    def __init__(self, step, drawer):
        name, headline, heading, body, leading, item, section = STEPS[step]
        self.step = step
        self.name = 30 - step if drawer == 'executive' else 22 if drawer == 'compact' else name
        self.headline, self.heading, self.item, self.section = headline, heading, item, section
        self.body, self.leading = max(MIN_BODY_SIZE, body), max(MIN_LEADING, leading)
        self.title = self.body + 0.6
        self.small = round(max(8.3, self.body - 0.9), 2)
        self.side = round(max(8.4, self.body - 0.6), 2)
        self.side_leading = round(max(11.2, self.leading - 1.6), 2)
        # The space between two entries: the table's item gap on top of a third of a line.
        self.entry = round(self.item + self.leading * 0.36, 2)


def styles(look, scale, colours):
    heading_face, body_face = FONT_PAIRS[look['fonts']]
    hb, bb, bi = heading_face + '-Bold', body_face + '-Bold', body_face + '-Italic'
    drawer = look['drawer']
    base = dict(fontName=body_face, bulletFontName=body_face, textColor=colors.HexColor(INK),
                wordWrap='LTR', splitLongWords=1, allowWidows=0, allowOrphans=0)

    def style(name, **values):
        merged = {**base, **values}
        for key in ('textColor', 'bulletColor'):
            if isinstance(merged.get(key), str):
                merged[key] = colors.HexColor(merged[key])
        return ParagraphStyle(name, **merged)

    centred = TA_CENTER if drawer == 'centered' else TA_LEFT
    name_colour = colours['accent'] if drawer in ('centered', 'executive', *SIDEBARS) else INK
    s = scale
    found = {
        '_muted': colours['muted'],
        'name': style('name', fontName=hb, fontSize=s.name, leading=round(s.name * 1.14, 2),
                      textColor=name_colour, alignment=centred, spaceAfter=round(s.name * 0.12, 2)),
        'headline': style('headline', fontName=heading_face, fontSize=s.headline,
                          leading=round(s.headline * 1.3, 2), textColor=colours['accent'], alignment=centred,
                          spaceAfter=round(s.headline * 0.42, 2)),
        'contact': style('contact', fontSize=s.small, leading=round(s.small * 1.45, 2),
                         textColor=colours['muted'], alignment=centred),
        'heading': style('heading', fontName=hb, fontSize=s.heading, leading=round(s.heading * 1.25, 2),
                         textColor=INK if drawer == 'centered' else colours['accent'],
                         alignment=centred),
        'title': style('title', fontName=hb, fontSize=s.title, leading=s.leading),
        'date': style('date', fontSize=s.small, leading=s.leading, textColor=colours['muted'], alignment=TA_RIGHT),
        'org': style('org', fontName=bi if heading_face == 'CVSerif' else body_face, fontSize=s.body - 0.3,
                     leading=s.leading, textColor=colours['muted'], spaceAfter=1),
        'body': style('body', fontSize=s.body, leading=s.leading),
        'line': style('line', fontSize=s.body, leading=s.leading),
        'bullet': style('bullet', fontSize=s.body, leading=s.leading, leftIndent=11, bulletIndent=1.5,
                        bulletColor=colours['accent'], bulletFontSize=s.body),
        'gutter': style('gutter', fontName=bb, fontSize=s.small, leading=s.leading,
                        textColor=colours['muted'], alignment=TA_RIGHT),
        'margin': style('margin', fontName=hb, fontSize=max(8.6, s.heading - 1.0),
                        leading=round(max(8.6, s.heading - 1.0) * 1.3, 2), textColor=colours['accent']),
    }
    side = colours.get('side_ink', INK)
    found.update({
        'side_heading': style('side_heading', fontName=hb, fontSize=round(s.side + 0.6, 2),
                              leading=round((s.side + 0.6) * 1.25, 2),
                              textColor=colours.get('side_accent', colours['accent'])),
        'side_label': style('side_label', fontName=bb, fontSize=7.4, leading=9.6,
                            textColor=colours.get('side_muted', colours['muted'])),
        'side_value': style('side_value', fontSize=s.side, leading=s.side_leading, textColor=side),
        'side_title': style('side_title', fontName=bb, fontSize=s.side, leading=s.side_leading, textColor=side),
        'side_muted': style('side_muted', fontSize=round(s.side - 0.2, 2), leading=s.side_leading,
                            textColor=colours.get('side_muted', colours['muted'])),
    })
    if 'band' in colours:
        found.update({
            'band_name': style('band_name', fontName=hb, fontSize=s.name, leading=round(s.name * 1.12, 2),
                               textColor=colours['band_ink'], spaceAfter=round(s.name * 0.1, 2)),
            'band_headline': style('band_headline', fontName=heading_face, fontSize=s.headline,
                                   leading=round(s.headline * 1.3, 2), textColor=colours['band_ink'],
                                   spaceAfter=round(s.headline * 0.45, 2)),
            'band_contact': style('band_contact', fontSize=s.small, leading=round(s.small * 1.45, 2),
                                  textColor=colours['band_muted']),
        })
    return found


def esc(text):
    return escape(str(text or ''))


def prose(text):
    """Escaped running text whose last two words stay together, so no line ends a paragraph alone."""
    words = str(text or '').split(' ')
    if len(words) >= 4 and len(words[-2]) + len(words[-1]) <= 24:
        words[-2:] = [words[-2] + '\u00A0' + words[-1]]
    return escape(' '.join(words))


def dates(text):
    """Escaped dates that, when they must wrap, wrap only after the dash: "01.2023 –" over "наст. время"."""
    text = str(text or '').replace(' ', '\u00A0')
    return escape(re.sub('\u00A0([–—-])\u00A0', '\u00A0\\1 ', text))


def unbroken(text):
    """A short phrase kept on one line (a contact, a language and its level)."""
    text = str(text or '')
    return text.replace(' ', '\u00A0') if len(text) <= 40 else text


# Where a long email or link may break, best first: after the @, after a slash,
# before a dot, before a hyphen or underscore.
BREAKS = (r'(?<=@)', r'(?<=/)', r'(?=\.)', r'(?=[-_])')


def _split_word(word, font, size, width):
    if stringWidth(word, font, size) <= width:
        return [word]
    for pattern in BREAKS:
        cuts = [match.start() for match in re.finditer(pattern, word) if 0 < match.start() < len(word)]
        fitting = [cut for cut in cuts if stringWidth(word[:cut], font, size) <= width]
        if fitting:
            cut = fitting[-1]
            return [word[:cut], *_split_word(word[cut:], font, size, width)]
    # No natural break fits: ReportLab splits the word where it must.
    return [word]


def breakable(text, font, size, width):
    """Escaped text in which a word too wide for `width` (an email, a link) breaks at a natural point."""
    return ' '.join('<br/>'.join(escape(piece) for piece in _split_word(word, font, size, width))
                    for word in str(text or '').split(' '))


# ------------------------------------------------------------------ flowables

class Heading(Flowable):
    """A section heading in capitals, a little tracked, with the drawer's rule.

    `kind` is `rule` (a thin rule beneath, the full width), `plain` (no rule) or
    `centered` (centred between two hairlines). A heading too long for one line
    — the model names the `extra` section itself — wraps as a paragraph.
    """

    def __init__(self, text, style, *, kind='rule', rule=None, rule_width=0.6, tracking=0.7, space_before=0,
                 gap=3.0, after=4.0):
        super().__init__()
        self.text, self.style, self.kind = str(text or '').upper(), style, kind
        self.rule, self.rule_width, self.tracking, self.gap = rule, rule_width, tracking, gap
        self.spaceBefore, self.spaceAfter = space_before, after
        self.keepWithNext = True

    def getSpaceBefore(self):
        return self.spaceBefore

    def getSpaceAfter(self):
        return self.spaceAfter

    def wrap(self, width, height):
        self.width = width
        size = self.style.fontSize
        self.text_width = (stringWidth(self.text, self.style.fontName, size)
                           + self.tracking * max(0, len(self.text) - 1))
        room = width - (56 if self.kind == 'centered' else 0)
        self.para = None
        if self.text_width > room:
            self.para = Paragraph(esc(self.text), self.style)
            _, self.text_height = self.para.wrap(width, height)
        else:
            self.text_height = round(size * 1.22, 2)
        self.height = self.text_height + (self.gap + self.rule_width if self.kind == 'rule' else 0)
        return width, self.height

    def draw(self):
        canvas, size = self.canv, self.style.fontSize
        top = self.height
        if self.para:
            self.para.drawOn(canvas, 0, top - self.text_height)
        else:
            canvas.setFont(self.style.fontName, size)
            canvas.setFillColor(self.style.textColor)
            x = (self.width - self.text_width) / 2 if self.kind == 'centered' else 0
            canvas.drawString(x, top - size, self.text, charSpace=self.tracking)
            if self.kind == 'centered' and self.rule:
                middle = top - size + size * 0.34
                canvas.setStrokeColor(colors.HexColor(self.rule))
                canvas.setLineWidth(0.5)
                canvas.line(0, middle, max(0, x - 9), middle)
                canvas.line(min(self.width, x + self.text_width + 9), middle, self.width, middle)
        if self.kind == 'rule' and self.rule:
            canvas.setStrokeColor(colors.HexColor(self.rule))
            canvas.setLineWidth(self.rule_width)
            canvas.line(0, self.rule_width / 2, self.width, self.rule_width / 2)


class TitleRow(Flowable):
    """An entry's title on the left and its dates on the right, on one baseline."""

    def __init__(self, title, date, style, date_style, space_before=0, markup=None):
        super().__init__()
        self.title = Paragraph(markup or esc(title), style) if (title or markup) else None
        self.date, self.style, self.date_style = str(date or ''), style, date_style
        self.spaceBefore = space_before

    def getSpaceBefore(self):
        return self.spaceBefore

    def wrap(self, width, height):
        self.width = width
        size = self.date_style.fontSize
        self.date_width = stringWidth(self.date, self.date_style.fontName, size) if self.date else 0
        self.date_para = None
        if self.date_width > width * 0.42:
            self.date_width = width * 0.42
            self.date_para = Paragraph(dates(self.date), self.date_style)
            self.date_para.wrap(self.date_width, height)
        room = width - (self.date_width + 10 if self.date else 0)
        self.title_height = self.title.wrap(room, height)[1] if self.title else self.style.leading
        date_height = self.date_para.height if self.date_para else (self.date_style.leading if self.date else 0)
        self.height = max(self.title_height, date_height)
        return width, self.height

    def draw(self):
        canvas = self.canv
        if self.title:
            self.title.drawOn(canvas, 0, self.height - self.title_height)
        if self.date_para:
            self.date_para.drawOn(canvas, self.width - self.date_width,
                                  self.height - self.date_para.height - (self.style.fontSize - self.date_style.fontSize))
        elif self.date:
            canvas.setFont(self.date_style.fontName, self.date_style.fontSize)
            canvas.setFillColor(self.date_style.textColor)
            canvas.drawRightString(self.width, self.height - self.style.fontSize, self.date)


class Stack(Flowable):
    """Flowables set one under another inside a fixed column, as one unit (a timeline entry's text)."""

    def __init__(self, parts):
        super().__init__()
        self.parts = parts

    def wrap(self, width, height):
        self.width, self.sizes = width, []
        total = 0
        for index, part in enumerate(self.parts):
            _, h = part.wrap(width, 10 ** 6)
            before = part.getSpaceBefore() if index else 0
            self.sizes.append((before, h))
            total += before + h
        self.height = total
        return width, total

    def draw(self):
        y = self.height
        for part, (before, h) in zip(self.parts, self.sizes):
            y -= before + h
            part.drawOn(self.canv, 0, y)


class TimelineItem(Flowable):
    """One dated entry of the timeline: the date in the gutter, a dot on the line, the text beside it."""

    def __init__(self, label, parts, *, geometry, colours, label_style, title_size, dot=True, line=True,
                 first=False, last=False, gap=0, space_before=0, continued=False):
        super().__init__()
        self.label, self.parts, self.geometry, self.colours = label, parts, geometry, colours
        self.label_style, self.title_size = label_style, title_size
        self.dot, self.line, self.first, self.last, self.gap = dot, line, first, last, gap
        self.spaceBefore, self.continued = space_before, continued

    def getSpaceBefore(self):
        return self.spaceBefore

    def wrap(self, width, height):
        gutter, _, content = self.geometry
        self.width = width
        self.stack = Stack(self.parts)
        _, text_height = self.stack.wrap(width - content, height)
        self.label_para = Paragraph(dates(self.label), self.label_style) if self.label and not self.continued else None
        label_height = self.label_para.wrap(gutter, height)[1] if self.label_para else 0
        self.height = max(text_height, label_height) + self.gap
        return width, self.height

    def split(self, width, height):
        # Only an entry taller than what is left of a frame gets here: its text
        # parts go on as far as they fit, the rest continues without the dot.
        if height < self.title_size * 3:
            return []
        gutter, line_x, content = self.geometry
        if self.label and not self.continued:
            # The dates stay with the first lines, so they must fit beside them.
            if Paragraph(dates(self.label), self.label_style).wrap(gutter, 10 ** 6)[1] > height:
                return []
        room, used, head = height, 0, []
        for index, part in enumerate(self.parts):
            _, h = part.wrap(width - content, 10 ** 6)
            before = part.getSpaceBefore() if index else 0
            if used + before + h > room:
                break
            used += before + h
            head.append(part)
        if not head:
            return []
        tail = self.parts[len(head):]
        first = TimelineItem(self.label, head, geometry=self.geometry, colours=self.colours,
                             label_style=self.label_style, title_size=self.title_size, dot=self.dot,
                             line=self.line, first=self.first, last=False, gap=0, space_before=self.spaceBefore,
                             continued=self.continued)
        if not tail:
            return [first]
        rest = TimelineItem(self.label, tail, geometry=self.geometry, colours=self.colours,
                            label_style=self.label_style, title_size=self.title_size, dot=False,
                            line=self.line, first=False, last=self.last, gap=self.gap, continued=True)
        return [first, rest]

    def draw(self):
        canvas = self.canv
        gutter, line_x, content = self.geometry
        top = self.height
        if self.label_para:
            self.label_para.drawOn(canvas, 0, top - self.label_para.height
                                   - max(0, self.title_size - self.label_style.fontSize))
        self.stack.drawOn(canvas, content, top - self.stack.height)
        dot_y = top - self.title_size * 0.62
        if self.line:
            canvas.setStrokeColor(colors.HexColor(self.colours['rule']))
            canvas.setLineWidth(0.8)
            upper = dot_y if self.first and self.dot else top
            lower = self.gap if self.last else 0
            if upper > lower:
                canvas.line(line_x, lower, line_x, upper)
        if self.dot:
            canvas.setFillColor(colors.HexColor(self.colours['accent']))
            canvas.circle(line_x, dot_y, 2.2, stroke=0, fill=1)


class Header(Flowable):
    """The name, headline and contacts on page 1, with a square portrait at the right when there is one."""

    def __init__(self, paragraphs, *, photo=None, photo_size=0, photo_gap=0, rule=None, rule_width=0,
                 rule_gap=0, after=0):
        super().__init__()
        self.paragraphs, self.photo, self.photo_size, self.photo_gap = paragraphs, photo, photo_size, photo_gap
        self.rule, self.rule_width, self.rule_gap, self.after = rule, rule_width, rule_gap, after

    def getSpaceAfter(self):
        return self.after

    def wrap(self, width, height):
        self.width = width
        room = width - (self.photo_size + self.photo_gap if self.photo else 0)
        self.sizes, total = [], 0
        for index, para in enumerate(self.paragraphs):
            h = para.wrap(room, height)[1]
            after = para.style.spaceAfter if index < len(self.paragraphs) - 1 else 0
            self.sizes.append((h, after))
            total += h + after
        self.text_height = total
        body = max(total, self.photo_size if self.photo else 0)
        self.height = body + (self.rule_gap + self.rule_width if self.rule else 0)
        return width, self.height

    def draw(self):
        canvas = self.canv
        y = self.height
        if self.photo:
            # The text block sits level with the middle of the portrait when it is shorter.
            y -= max(0, (self.photo_size - self.text_height) / 2)
        for para, (h, after) in zip(self.paragraphs, self.sizes):
            y -= h
            para.drawOn(canvas, 0, y)
            y -= after
        if self.photo:
            size = self.photo_size
            canvas.drawImage(ImageReader(io.BytesIO(self.photo)), self.width - size, self.height - size, size, size)
        if self.rule:
            canvas.setStrokeColor(colors.HexColor(self.rule))
            canvas.setLineWidth(self.rule_width)
            canvas.line(0, self.rule_width / 2, self.width, self.rule_width / 2)


# ------------------------------------------------------------------ contacts

URL_KEYS = ('linkedin', 'website', 'github')


def shown_contact(key, value):
    """A contact as it is printed: links without their scheme, a Telegram handle with its @."""
    value = str(value or '').strip()
    if key in URL_KEYS or key == 'telegram':
        value = re.sub(r'^(?:https?://)?(?:www\.)?', '', value, flags=re.I).rstrip('/')
    if key == 'telegram' and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{3,31}', value):
        value = '@' + value
    return value


def contact_line(contacts):
    parts = []
    for key, label, value in contacts:
        shown = shown_contact(key, value)
        if key == 'telegram':
            parts.append(f'Telegram {shown}')
        elif key == 'birth' or key not in ('phone', 'email', 'location', *URL_KEYS):
            parts.append(f'{label}: {shown}')
        else:
            parts.append(shown)
    # A no-break space keeps each separator with the contact before it.
    return '\u00A0·  '.join(esc(unbroken(part)) for part in parts)


# ------------------------------------------------------------------ blocks

def _lines(item):
    return [line for line in item.get('lines') or [] if line.strip()]


def entry_parts(kind, item, st, *, date=True, space_before=0):
    """An entry's flowables in a column: title and dates, the organisation line, then its lines."""
    lines = _lines(item)
    markup = None
    if kind == 'certificates' and lines and item.get('label'):
        # A certificate and its issuer on one line: five of them should not take a page.
        markup = (f'{esc(item["label"])}<font name="{st["org"].fontName}" size="{st["org"].fontSize}" '
                  f'color="{st["_muted"]}"> · {esc(", ".join(lines))}</font>')
        lines = []
    parts = [TitleRow(item.get('label', ''), item.get('value', '') if date else '', st['title'], st['date'],
                      space_before, markup)] if (item.get('label') or (date and item.get('value'))) else []
    rest = lines
    if kind in ('experience', 'education', 'certificates') and lines:
        parts.append(Paragraph(esc(lines[0]), st['org']))
        rest = lines[1:]
    for line in rest:
        if kind == 'experience':
            parts.append(Paragraph(prose(line), st['bullet'], bulletText='•'))
        else:
            parts.append(Paragraph(prose(line), st['line']))
    if parts and not isinstance(parts[0], TitleRow):
        parts.insert(0, Spacer(1, space_before))
    return parts


def skills_paragraphs(section, st, style='body'):
    out = []
    for item in section['items']:
        label, text = item.get('label', ''), ', '.join(_lines(item))
        if label and text:
            out.append(Paragraph(f'<font name="{st["title"].fontName}">{esc(label)}:</font> {prose(text)}', st[style]))
        elif label or text:
            out.append(Paragraph(esc(label or text), st[style]))
    return out


def languages_paragraph(section, st, style='body'):
    pieces = []
    for item in section['items']:
        label, text = item.get('label', ''), ', '.join(_lines(item))
        if label and text:
            pieces.append(f'<font name="{st["title"].fontName}">{esc(unbroken(label))}</font>\u00A0—\u00A0'
                          f'{esc(unbroken(text))}')
        elif label or text:
            pieces.append(esc(label or text))
    return [Paragraph('\u00A0\u00A0·\u00A0\u00A0 '.join(pieces), st[style])] if pieces else []


def section_flowables(section, st, scale, heading):
    """A section in a plain column: its heading kept with the first entry, each entry kept whole."""
    kind = section['id']
    if kind == 'profile':
        body = [Paragraph(prose(line), st['body']) for line in section['lines']]
        return [KeepTogether([heading, *body[:1]]), *body[1:]]
    if kind == 'skills':
        groups = skills_paragraphs(section, st)
        if not groups:
            return []
        spaced = [groups[0]] + [Indent(para, space_before=scale.item + 1.5) for para in groups[1:]]
        return [KeepTogether([heading, spaced[0]]), *spaced[1:]]
    if kind == 'languages':
        return [KeepTogether([heading, *languages_paragraph(section, st)])]
    entries = [entry_parts(kind, item, st, space_before=scale.entry if index else 0)
               for index, item in enumerate(section['items'])]
    entries = [parts for parts in entries if parts]
    if not entries:
        return []
    return [KeepTogether([heading, *entries[0]]), *[KeepTogether(parts) for parts in entries[1:]]]


class Indent(Flowable):
    """A flowable with space before it that is dropped at the top of a frame."""

    def __init__(self, inner, space_before=0):
        super().__init__()
        self.inner, self.spaceBefore = inner, space_before

    def getSpaceBefore(self):
        return self.spaceBefore

    def wrap(self, width, height):
        self.width, self.height = width, self.inner.wrap(width, height)[1]
        return width, self.height

    def split(self, width, height):
        parts = self.inner.split(width, height)
        if parts:
            parts[0] = Indent(parts[0], self.spaceBefore)
        return parts

    def draw(self):
        self.inner.drawOn(self.canv, 0, 0)


# ------------------------------------------------------------------ side column

def side_blocks(cv, st, colours, width, *, contacts=True, groups=SIDE):
    """The side column's groups in order, each a list of flowables with its own spacing."""
    def heading(text):
        return [Paragraph(esc(text.upper()), st['side_heading']), Bar(colours.get('side_rule', colours['rule'])),
                Spacer(1, 6)]
    blocks = []
    if contacts and cv['contacts']:
        parts = heading(cv['labels']['contact'])
        for key, label, value in cv['contacts']:
            value = breakable(shown_contact(key, value), st['side_value'].fontName, st['side_value'].fontSize, width)
            parts += [Paragraph(esc(label.upper()), st['side_label']), Paragraph(value, st['side_value']),
                      Spacer(1, 4.5)]
        blocks.append(('contacts', parts))
    by_id = {section['id']: section for section in cv['sections']}
    for group in groups:
        section = by_id.get(group)
        if not section or not section['items']:
            continue
        parts = heading(section['heading'])
        for item in section['items']:
            label, lines, value = item.get('label', ''), _lines(item), item.get('value', '')
            if group == 'skills':
                if label:
                    parts.append(Paragraph(esc(label), st['side_title']))
                if lines:
                    parts.append(Paragraph(prose(', '.join(lines)), st['side_value']))
            elif group == 'languages':
                level = ', '.join(lines)
                text = f'<font name="{st["side_title"].fontName}">{esc(label)}</font>' if label else ''
                if level:
                    text += (' — ' if text else '') + esc(level)
                parts.append(Paragraph(text, st['side_value']))
            else:
                if label:
                    parts.append(Paragraph(esc(label), st['side_title']))
                meta = ' · '.join(piece for piece in (', '.join(lines), value) if piece)
                if meta:
                    parts.append(Paragraph(esc(meta), st['side_muted']))
            parts.append(Spacer(1, 4.5))
        blocks.append((group, parts))
    # The gap between groups.
    for _, parts in blocks[:-1]:
        parts.append(Spacer(1, 8))
    return blocks


def stack_height(flowables, width):
    """How tall `flowables` stand one under another, nothing split: KeepTogether reports its content's height."""
    scratch, total = Canvas(io.BytesIO()), 0
    for index, flowable in enumerate(flowables):
        _, h = flowable.wrapOn(scratch, width, 10 ** 6)
        if isinstance(flowable, KeepTogether):
            h = flowable._H
        total += h + flowable.getSpaceAfter() + (flowable.getSpaceBefore() if index else 0)
    return total


def measure(parts, width):
    return sum(part.wrap(width, 10 ** 6)[1] for part in parts)


def fit_side(blocks, width, room):
    """Move whole groups out of a side column until the rest fits `room`: certificates, then languages, then skills."""
    kept, moved = list(blocks), []
    for group in MOVE_ORDER:
        if sum(measure(parts, width) for _, parts in kept) <= room:
            break
        if any(name == group for name, _ in kept):
            kept = [(name, parts) for name, parts in kept if name != group]
            moved.append(group)
    return kept, moved


def draw_blocks(canvas, blocks, x, top, width):
    y = top
    for _, parts in blocks:
        for part in parts:
            _, h = part.wrapOn(canvas, width, 10 ** 6)
            part.drawOn(canvas, x, y - h)
            y -= h
    return y


class Bar(Flowable):
    """The short rule under a side column heading."""

    def __init__(self, colour, length=22, weight=1.4):
        super().__init__()
        self.colour, self.length, self.weight = colour, length, weight

    def wrap(self, width, height):
        return width, self.weight + 3

    def draw(self):
        self.canv.setFillColor(colors.HexColor(self.colour))
        self.canv.rect(0, 0, self.length, self.weight, stroke=0, fill=1)


# ------------------------------------------------------------------ portraits

def round_photo(canvas, jpeg, cx, cy, diameter, ring):
    radius = diameter / 2
    canvas.saveState()
    path = canvas.beginPath()
    path.circle(cx, cy, radius)
    canvas.clipPath(path, stroke=0, fill=0)
    canvas.drawImage(ImageReader(io.BytesIO(jpeg)), cx - radius, cy - radius, diameter, diameter)
    canvas.restoreState()
    canvas.setStrokeColor(colors.HexColor(ring))
    canvas.setLineWidth(1.5)
    canvas.circle(cx, cy, radius + 0.75, stroke=1, fill=0)


def square_photo(canvas, jpeg, x, y, size, border=None):
    canvas.drawImage(ImageReader(io.BytesIO(jpeg)), x, y, size, size)
    if border:
        canvas.setStrokeColor(colors.HexColor(border))
        canvas.setLineWidth(1.5)
        canvas.rect(x - 0.75, y - 0.75, size + 1.5, size + 1.5, stroke=1, fill=0)


# ------------------------------------------------------------------ the sheet

def _box(x0, y0, x1, y1):
    """A ReportLab rectangle as pdfplumber reads it: (x0, top, x1, bottom)."""
    return (round(x0, 2), round(H - y1, 2), round(x1, 2), round(H - y0, 2))


class Sheet:
    """One build of one CV in one drawer at one fit step.

    `build(target)` writes the PDF to `target` (a path or a BytesIO) and leaves
    behind what the renderer reports: the frames text may sit in, per page
    template, and the side groups that moved into the main column.
    """

    def __init__(self, cv, look, step, portrait=None, *, breaks=0, balance=None, title='', author='', subject='',
                 locale='en'):
        fonts.register()
        self.cv, self.look, self.step, self.breaks, self.balance = cv, look, step, breaks, balance
        self.drawer = look['drawer']
        self.photo = portrait if look['photo'] else None
        self.scale = Scale(step, self.drawer)
        self.colours = palette(look)
        self.st = styles(look, self.scale, self.colours)
        self.meta = {'title': title, 'author': author, 'subject': subject, 'lang': locale}
        self.moved, self.frames = [], {}
        # The lowest point text reached in each frame of each page: {(page, frame id): y}.
        self.reach = {}

    # -- common pieces

    def heading(self, text, *, first=False):
        """A section heading: centred between hairlines on `centered`, over a thin rule everywhere else."""
        centred = self.drawer == 'centered'
        return Heading(text, self.st['heading'], kind='centered' if centred else 'rule', rule=self.colours['rule'],
                       rule_width=0.5 if centred else 0.6, space_before=0 if first else self.scale.section + 2,
                       gap=3.2, after=self.scale.leading * (0.5 if centred else 0.32))

    def header_paragraphs(self, width, *, contacts=True, prefix=''):
        """Name, headline and contacts for a header `width` wide.

        A name with a word too long for the width (a double-barrelled surname in
        a sidebar's main column) is set smaller rather than broken mid-word.
        """
        st, cv = self.st, self.cv
        style = st[prefix + 'name']
        longest = max((stringWidth(word, style.fontName, style.fontSize) for word in cv['name'].split()), default=0)
        if longest > width:
            size = max(14, style.fontSize * width / longest * 0.98)
            style = ParagraphStyle(style.name + '_fitted', parent=style, fontSize=round(size, 2),
                                   leading=round(size * 1.14, 2))
        parts = [Paragraph(esc(cv['name']), style)]
        if cv['headline']:
            parts.append(Paragraph(esc(cv['headline']), st[prefix + 'headline']))
        if contacts and cv['contacts']:
            parts.append(Paragraph(contact_line(cv['contacts']), st[prefix + 'contact']))
        return parts

    def sections(self, ids):
        """The CV's sections whose ids are in `ids`, in reading order (unknown ids last)."""
        rank = {key: index for index, key in enumerate(ORDER)}
        chosen = [section for section in self.cv['sections'] if section['id'] in ids or
                  (section['id'] not in rank and 'extra' in ids)]
        return sorted(chosen, key=lambda section: rank.get(section['id'], len(ORDER)))

    def column_story(self, ids):
        story = []
        for index, section in enumerate(self.sections(ids)):
            heading = self.heading(section['heading'], first=not index)
            story.append(section_flowables(section, self.st, self.scale, heading))
        return story

    def with_breaks(self, groups):
        """Flatten section groups, forcing the last `breaks` sections onto the next page (the widow rule)."""
        story = []
        for index, group in enumerate(groups):
            if self.breaks and index == len(groups) - self.breaks and index > 0:
                story.append(PageBreak())
            story.extend(group)
        return story

    # -- drawers

    def build(self, target):
        drawer = self.drawer
        if drawer in SIDEBARS:
            templates, story = self.sidebar()
        elif drawer == 'band':
            templates, story = self.band()
        elif drawer == 'compact':
            templates, story = self.compact()
        elif drawer == 'executive':
            templates, story = self.executive()
        elif drawer == 'timeline':
            templates, story = self.timeline()
        else:
            templates, story = self.single()
        document = BaseDocTemplate(target, pagesize=A4, leftMargin=0, rightMargin=0, topMargin=0, bottomMargin=0,
                                   creator='PDF Master', invariant=1, initialFontName=FONT_PAIRS[self.look['fonts']][1],
                                   **self.meta)
        document.addPageTemplates(templates)

        def reached(flowable):
            frame = getattr(document, 'frame', None)
            if frame is not None:
                key = (document.page, getattr(frame, 'id', ''))
                self.reach[key] = min(self.reach.get(key, H), frame._y)
        document.afterFlowable = reached
        document.build([NextPageTemplate('later'), *story])
        return self

    def paint(self, canvas):
        """The page's ground: the paper tint on paper templates, white otherwise (drawn as nothing)."""
        if self.colours['paper'] != WHITE:
            canvas.setFillColor(colors.HexColor(self.colours['paper']))
            canvas.rect(0, 0, W, H, stroke=0, fill=1)

    def single(self):
        """`column` and `centered`: one column, the header at the top of the story."""
        centred = self.drawer == 'centered'
        side = 20 * MM if centred else 18 * MM
        top, bottom = (18 * MM, 15 * MM) if centred else (16 * MM, 14 * MM)
        frame = (side, bottom, W - 2 * side, H - top - bottom)
        photo = self.photo and self.drawer == 'column'
        header = Header(self.header_paragraphs(frame[2] - (34 * MM if photo else 0)),
                        photo=self.photo['jpeg'] if photo else None,
                        photo_size=28 * MM, photo_gap=6 * MM,
                        rule=None if centred else self.colours['accent'], rule_width=0.8,
                        rule_gap=self.scale.leading * 0.55 + (3 * MM if photo else 0), after=self.scale.section + 4)
        groups = self.column_story(ORDER)
        story = [header, *self.with_breaks(groups)]
        boxes = [_box(frame[0], frame[1], frame[0] + frame[2], frame[1] + frame[3])]
        self.frames = {'first': boxes, 'later': boxes}

        def page(canvas, doc):
            self.paint(canvas)
        templates = [PageTemplate('first', [Frame(*frame, 0, 0, 0, 0, id='main')], onPage=page),
                     PageTemplate('later', [Frame(*frame, 0, 0, 0, 0, id='main')], onPage=page)]
        return templates, story

    def executive(self):
        """Headings in a 42 mm margin column, entries beside them; one table row per entry."""
        side, top, bottom = 20 * MM, 18 * MM, 16 * MM
        frame = (side, bottom, W - 2 * side, H - top - bottom)
        label_width = 42 * MM
        content = frame[2] - label_width
        st, scale = self.st, self.scale
        header = Header(self.header_paragraphs(frame[2]), rule=self.colours['rule'], rule_width=2.5,
                        rule_gap=scale.leading * 0.6, after=scale.section + 6)
        groups = []
        for index, section in enumerate(self.sections(ORDER)):
            kind = section['id']
            label = Heading(section['heading'], st['margin'], kind='plain', tracking=0.5, after=0)
            if kind == 'profile':
                cells = [[Paragraph(esc(line), st['body']) for line in section['lines']]]
            elif kind == 'skills':
                cells = [[para] for para in skills_paragraphs(section, st)]
            elif kind == 'languages':
                cells = [languages_paragraph(section, st)]
            else:
                cells = [entry_parts(kind, item, st) for item in section['items']]
            cells = [cell for cell in cells if cell]
            if not cells:
                continue
            rows = [[label if not row else '', cell] for row, cell in enumerate(cells)]
            # The heading's first baseline level with the entry's: titles are larger than body text.
            first = scale.title if kind not in ('profile', 'skills', 'languages') else scale.body
            table = Table(rows, colWidths=[label_width, content], splitByRow=1, splitInRow=1)
            gap = scale.entry if kind not in ('skills',) else scale.item + 2
            table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), gap), ('RIGHTPADDING', (0, 0), (0, -1), 10),
                ('TOPPADDING', (0, 0), (0, 0), max(0, first - st['margin'].fontSize))]))
            table.spaceBefore = 0 if not index else scale.section
            groups.append([table])
        story = [header, *self.with_breaks(groups)]
        boxes = [_box(frame[0], frame[1], frame[0] + frame[2], frame[1] + frame[3])]
        self.frames = {'first': boxes, 'later': boxes}

        def page(canvas, doc):
            self.paint(canvas)
        templates = [PageTemplate('first', [Frame(*frame, 0, 0, 0, 0, id='main')], onPage=page),
                     PageTemplate('later', [Frame(*frame, 0, 0, 0, 0, id='main')], onPage=page)]
        return templates, story

    def timeline(self):
        """Dates in a 30 mm gutter, a line at 34 mm with a dot per role and degree, the text from 38 mm."""
        side, top, bottom = 18 * MM, 16 * MM, 14 * MM
        frame = (side, bottom, W - 2 * side, H - top - bottom)
        geometry = (30 * MM, 34 * MM, 38 * MM)
        st, scale, colours = self.st, self.scale, self.colours
        header = Header(self.header_paragraphs(frame[2]), rule=colours['accent'], rule_width=0.8,
                        rule_gap=scale.leading * 0.55, after=scale.section + 4)
        groups = []
        for index, section in enumerate(self.sections(ORDER)):
            kind = section['id']
            heading = self.heading(section['heading'], first=False)
            entries = []
            if kind == 'profile':
                entries = [TimelineItem('', [Paragraph(esc(line), st['body']) for line in section['lines']],
                                        geometry=geometry, colours=colours, label_style=st['gutter'],
                                        title_size=scale.title, dot=False, line=False)]
            elif kind in ('skills', 'languages'):
                gutter = st['gutter']
                if all(stringWidth(item.get('label', ''), gutter.fontName, gutter.fontSize) <= geometry[0] - 2
                       for item in section['items']):
                    # Each group or language in the gutter, its list beside it, like the dates.
                    for number, item in enumerate(section['items']):
                        text = ', '.join(_lines(item))
                        entries.append(TimelineItem(item.get('label', ''), [Paragraph(prose(text or ' '), st['body'])],
                                                    geometry=geometry, colours=colours, label_style=gutter,
                                                    title_size=scale.body, dot=False, line=False,
                                                    space_before=(scale.item + 1.5) if number else 0))
                else:
                    # A name too long for the gutter would wrap there: the whole section sits beside it instead.
                    paragraphs = (skills_paragraphs(section, st) if kind == 'skills'
                                  else languages_paragraph(section, st))
                    for number, para in enumerate(paragraphs):
                        entries.append(TimelineItem('', [para], geometry=geometry, colours=colours,
                                                    label_style=gutter, title_size=scale.body, dot=False, line=False,
                                                    space_before=(scale.item + 1.5) if number else 0))
            else:
                dated = kind in ('experience', 'education')
                count = len(section['items'])
                for number, item in enumerate(section['items']):
                    parts = entry_parts(kind, item, st, date=False)
                    if not parts:
                        continue
                    entries.append(TimelineItem(item.get('value', ''), parts, geometry=geometry, colours=colours,
                                                label_style=self.st['date'], title_size=scale.title, dot=dated,
                                                line=dated, first=number == 0, last=number == count - 1,
                                                gap=scale.entry if number < count - 1 else 0))
            if entries:
                groups.append([KeepTogether([heading, entries[0]]), *entries[1:]])
        story = [header, *self.with_breaks(groups)]
        boxes = [_box(frame[0], frame[1], frame[0] + frame[2], frame[1] + frame[3])]
        self.frames = {'first': boxes, 'later': boxes}

        def page(canvas, doc):
            self.paint(canvas)
        templates = [PageTemplate('first', [Frame(*frame, 0, 0, 0, 0, id='main')], onPage=page),
                     PageTemplate('later', [Frame(*frame, 0, 0, 0, 0, id='main')], onPage=page)]
        return templates, story

    def sidebar(self):
        """A full-height strip with the portrait, contacts and short lists; the career beside it."""
        left = self.drawer == 'sidebar_left'
        side_x0, side_x1 = (0, 66 * MM) if left else (136 * MM, W)
        main_x0, main_x1 = (74 * MM, 194 * MM) if left else (16 * MM, 128 * MM)
        pad, top, bottom = 10 * MM, 16 * MM, 14 * MM
        inner_x, inner_w = side_x0 + pad, side_x1 - side_x0 - 2 * pad
        photo_d = 36 * MM
        side_top = H - (14 * MM + photo_d + 8 * MM if self.photo else top)
        room = side_top - bottom
        blocks, self.moved = fit_side(side_blocks(self.cv, self.st, self.colours, inner_w), inner_w, room)
        main_ids = [key for key in ORDER if key not in SIDE or key in self.moved]
        header = Header(self.header_paragraphs(main_x1 - main_x0, contacts=False), rule=None,
                        after=self.scale.section + 2)
        story = [header, *self.with_breaks(self.column_story(main_ids))]
        frame = (main_x0, bottom, main_x1 - main_x0, H - top - bottom)
        main = _box(main_x0, bottom, main_x1, H - top)
        side = _box(inner_x, bottom, inner_x + inner_w, side_top)
        self.frames = {'first': [main, side], 'later': [main]}
        colours = self.colours

        def ground(canvas):
            self.paint(canvas)
            canvas.setFillColor(colors.HexColor(colours['side']))
            canvas.rect(side_x0, 0, side_x1 - side_x0, H, stroke=0, fill=1)

        def first(canvas, doc):
            ground(canvas)
            if self.photo:
                round_photo(canvas, self.photo['jpeg'], (side_x0 + side_x1) / 2, H - 14 * MM - photo_d / 2,
                            photo_d, colours['ring'])
            draw_blocks(canvas, blocks, inner_x, side_top, inner_w)

        def later(canvas, doc):
            ground(canvas)
        templates = [PageTemplate('first', [Frame(*frame, 0, 0, 0, 0, id='main')], onPage=first),
                     PageTemplate('later', [Frame(*frame, 0, 0, 0, 0, id='main')], onPage=later)]
        return templates, story

    def band(self):
        """A coloured band across page 1 with the name and portrait; a narrow side column below it."""
        st, colours, scale = self.st, self.colours, self.scale
        side_margin, top, bottom = 16 * MM, 16 * MM, 14 * MM
        photo = 32 * MM
        text_x = side_margin
        text_right = (W - 10 * MM - photo - 8 * MM) if self.photo else W - side_margin
        widths = text_right - text_x
        text = self.header_paragraphs(widths, prefix='band_')
        sizes = [para.wrap(widths, 10 ** 6)[1] for para in text]
        afters = [para.style.spaceAfter for para in text[:-1]] + [0]
        text_height = sum(sizes) + sum(afters)
        band = max((52 if self.photo else 44) * MM, text_height + 20 * MM)
        main_x0, main_x1, col_x0, col_x1 = side_margin, 132 * MM, 140 * MM, W - side_margin
        first_top = H - band - 8 * MM
        col_w = col_x1 - col_x0
        blocks, self.moved = fit_side(side_blocks(self.cv, st, colours, col_w, contacts=False), col_w,
                                      first_top - bottom)
        main_ids = [key for key in ORDER if key not in SIDE or key in self.moved]
        story = self.with_breaks(self.column_story(main_ids))
        first_frame = (main_x0, bottom, main_x1 - main_x0, first_top - bottom)
        later_frame = (side_margin, bottom, W - 2 * side_margin, H - top - bottom)
        text_top = H - (band - text_height) / 2
        self.frames = {'first': [_box(main_x0, bottom, main_x1, first_top), _box(col_x0, bottom, col_x1, first_top),
                                 _box(text_x, H - band, text_right, H)],
                       'later': [_box(*later_frame[:2], later_frame[0] + later_frame[2], H - top)]}

        def first(canvas, doc):
            self.paint(canvas)
            canvas.setFillColor(colors.HexColor(colours['band']))
            canvas.rect(0, H - band, W, band, stroke=0, fill=1)
            y = text_top
            for para, h, after in zip(text, sizes, afters):
                para.wrapOn(canvas, widths, 10 ** 6)
                y -= h
                para.drawOn(canvas, text_x, y)
                y -= after
            if self.photo:
                square_photo(canvas, self.photo['jpeg'], W - 10 * MM - photo, H - band / 2 - photo / 2, photo,
                             border=WHITE)
            end = draw_blocks(canvas, blocks, col_x0, first_top, col_w)
            if blocks:
                canvas.setStrokeColor(colors.HexColor(colours['hairline']))
                canvas.setLineWidth(0.5)
                canvas.line(col_x0 - 4 * MM, end, col_x0 - 4 * MM, first_top)

        def later(canvas, doc):
            self.paint(canvas)
        templates = [PageTemplate('first', [Frame(*first_frame, 0, 0, 0, 0, id='main')], onPage=first),
                     PageTemplate('later', [Frame(*later_frame, 0, 0, 0, 0, id='main')], onPage=later)]
        return templates, story

    def compact(self):
        """A header across the page, two columns below; long careers flow from one column into the next."""
        st, colours, scale = self.st, self.colours, self.scale
        side, top, bottom, gap = 14 * MM, 14 * MM, 13 * MM, 8 * MM
        column = (W - 2 * side - gap) / 2
        photo = 26 * MM
        room = W - 2 * side - (photo + 6 * MM if self.photo else 0)
        text = self.header_paragraphs(room)
        sizes = [para.wrap(room, 10 ** 6)[1] for para in text]
        afters = [para.style.spaceAfter for para in text[:-1]] + [0]
        text_height = sum(sizes) + sum(afters)
        block = max(text_height, photo if self.photo else 0)
        header = block + 4.5 * MM
        body_top = H - top - header - 5.5 * MM
        frames_first = [(side, bottom, column, body_top - bottom), (side + column + gap, bottom, column, body_top - bottom)]
        # A last page whose text would fill one column and leave the other empty
        # is built again with both columns cut to half its length (`balance`).
        later_height = min(self.balance or H, H - top - bottom)
        later_bottom = H - top - later_height
        frames_later = [(side, later_bottom, column, later_height),
                        (side + column + gap, later_bottom, column, later_height)]
        # Everything on the left and the short lists on the right reads best; a
        # career too long for one column flows on into the next instead.
        left = self.with_breaks(self.column_story(COMPACT_LEFT))
        if not self.breaks and stack_height(left, column) <= body_top - bottom:
            right = self.column_story(COMPACT_RIGHT)
            if right:
                right[0][0] = _restart(right[0][0])
            story = [*left, FrameBreak(), *[flowable for group in right for flowable in group]]
        else:
            story = self.with_breaks(self.column_story(ORDER))
        self.frames = {'first': [_box(x, y, x + w, y + h) for x, y, w, h in frames_first]
                       + [_box(side, H - top - header, W - side, H - top + 2)],
                       'later': [_box(x, y, x + w, y + h) for x, y, w, h in frames_later]}

        def first(canvas, doc):
            self.paint(canvas)
            y = H - top - max(0, (block - text_height) / 2)
            for para, h, after in zip(text, sizes, afters):
                para.wrapOn(canvas, room, 10 ** 6)
                y -= h
                para.drawOn(canvas, side, y)
                y -= after
            if self.photo:
                square_photo(canvas, self.photo['jpeg'], W - side - photo, H - top - photo, photo)
            canvas.setStrokeColor(colors.HexColor(colours['rule']))
            canvas.setLineWidth(1.6)
            canvas.line(side, H - top - header, W - side, H - top - header)

        def later(canvas, doc):
            self.paint(canvas)
        templates = [PageTemplate('first', [Frame(*f, 0, 0, 0, 0, id=f'c{i}') for i, f in enumerate(frames_first)],
                                  onPage=first),
                     PageTemplate('later', [Frame(*f, 0, 0, 0, 0, id=f'c{i}') for i, f in enumerate(frames_later)],
                                  onPage=later)]
        return templates, story


def _restart(flowable):
    """The first flowable of a column: no space above it."""
    if isinstance(flowable, KeepTogether) and flowable._content and isinstance(flowable._content[0], Heading):
        flowable._content[0].spaceBefore = 0
    return flowable
