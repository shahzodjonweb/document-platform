"""Slide decks that look designed rather than generated.

A slide is not a short page. It is a headline and a few bullets, with what the
presenter would say kept in the notes — so this module builds from that shape
rather than flowing prose into a box.

Three things here are load-bearing and easy to break by accident:

* **The first shape added to every slide is the accent element**, filled with
  the accent exactly as the customer's branding supplied it. Derived text
  colours are contrast-corrected; the brand colour itself never is, because
  repainting someone's brand to win a contrast check is worse than the check.
* **One slide per section, always.** The slide count is what was quoted and
  billed. Nothing here adds or removes a slide: it sets the deck tighter, moves
  a slide to two columns, and only then drops bullets.
* **No binary parts may survive the save.** `processors/engine.py` refuses any
  `.bin` member on upload, so a deck carrying python-pptx's inherited printer
  settings would be rejected by the platform that produced it.

Text is written as real paragraphs with wrapping left to the viewer. The old
renderer measured line breaks itself and wrote one paragraph per wrapped line
with `word_wrap=False`, which meant the "editable deck" fell apart the moment
anyone edited it.
"""
import colorsys
import io
import re

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from .rendering import FIT_STEPS, SENTENCE, font_path

# python-pptx cannot embed fonts: `font.name` is a name the viewer resolves for
# itself. So the deck names faces that ship with Microsoft Office on Windows and
# macOS and cover Cyrillic, rather than the Noto Sans the server happens to have.
# If these substitute badly in Google Slides or Keynote, Georgia/Verdana are the
# duller but even safer fallback — two constants, nothing else changes.
HEADING_FONT = 'Cambria'
BODY_FONT = 'Corbel'
BULLET_FONT = 'Arial'

SLIDE_WIDTH = Inches(13.333)
SLIDE_HEIGHT = Inches(7.5)
MARGIN = Inches(0.85)

MAX_BULLETS = 5
BULLET_WORDS = 14
MIN_BODY_SIZE = 15
MAX_BODY_SIZE = 20
# Measured metrics come from reportlab's Noto; the viewer renders Corbel. The
# estimate only has to be close enough to choose a size, so it is padded rather
# than made exact.
WIDTH_SAFETY = 1.10
LINE_MULTIPLE = 1.22

MARKER = re.compile(r'^\s*(?:[•·▪◦‣*\-–—]+\s*|\(?[0-9]{1,2}[.)]\s+|\(?[a-zA-Z][.)]\s+)')


def _register_font():
    if 'PDFMaster' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('PDFMaster', str(font_path())))


# ---------------------------------------------------------------- colour


def _hex(value):
    value = (value or '').lstrip('#')
    return value if re.fullmatch(r'[0-9a-fA-F]{6}', value) else '255E49'


def _rgb(value):
    return RGBColor.from_string(_hex(value).upper())


def _hls(value):
    red, green, blue = (int(_hex(value)[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return colorsys.rgb_to_hls(red, green, blue)


def _from_hls(hue, lightness, saturation):
    red, green, blue = colorsys.hls_to_rgb(hue % 1.0, min(1.0, max(0.0, lightness)),
                                           min(1.0, max(0.0, saturation)))
    return '%02X%02X%02X' % (round(red * 255), round(green * 255), round(blue * 255))


def _luminance(value):
    channels = []
    for index in (0, 2, 4):
        channel = int(_hex(value)[index:index + 2], 16) / 255
        channels.append(channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(one, other):
    """WCAG contrast between two hex colours, lighter over darker."""
    first, second = _luminance(one), _luminance(other)
    high, low = max(first, second), min(first, second)
    return (high + 0.05) / (low + 0.05)


def _reads_on(value, background, target):
    """Move a colour away from its background until it reads, or run out of room.

    Which way is away depends on the background, so this serves a light deck and
    a dark one with the same call.
    """
    hue, lightness, saturation = _hls(value)
    step = -0.03 if _luminance(background) > 0.18 else 0.03
    for _ in range(40):
        if contrast_ratio(value, background) >= target:
            break
        lightness += step
        if not 0.0 <= lightness <= 1.0:
            break
        value = _from_hls(hue, lightness, saturation)
    return value


# Surface, secondary surface and soft-tint lightnesses per theme. Everything
# else is derived and contrast-corrected, so a theme is three numbers and a
# decision about what the cover and the dividers are filled with.
THEME_GROUND = {
    'light': (0.975, 0.94, 0.86),
    'dark': (0.11, 0.165, 0.26),
    'bold': (0.975, 0.94, 0.86),
}


def palette(accent, theme='light'):
    """A small set of roles derived from the one colour a customer can choose.

    `accent` is returned untouched — it is the brand, and it is what fills the
    accent shape. Everything that carries text is contrast-corrected against the
    surface it sits on, which is most of what separates a designed deck from a
    generated one, and is what lets an arbitrary accent be safe.
    """
    accent = _hex(accent).upper()
    theme = theme if theme in THEME_GROUND else 'light'
    hue, _, saturation = _hls(accent)
    ground, alt, soft = THEME_GROUND[theme]
    dark = ground < 0.5
    surface = _from_hls(hue, ground, min(saturation, 0.12 if dark else 0.10))
    roles = {
        'accent': accent,
        'theme': theme,
        'surface': surface,
        'surface_alt': _from_hls(hue, alt, min(saturation, 0.14)),
        'accent_soft': _from_hls(hue, soft, min(saturation, 0.35)),
        'ink': _from_hls(hue, 0.95 if dark else 0.13, min(saturation, 0.08 if dark else 0.25)),
        'muted': _from_hls(hue, 0.66 if dark else 0.45, min(saturation, 0.15)),
        'accent_text': accent,
    }
    roles['ink'] = _reads_on(roles['ink'], surface, 7.0)
    roles['muted'] = _reads_on(roles['muted'], surface, 4.5)
    roles['accent_text'] = _reads_on(roles['accent_text'], surface, 4.5)
    # Text on the accent itself: start from whichever end already reads better,
    # then push it until it does. Picking the better of black and white is not
    # enough — a mid-tone accent is too far from both.
    on_dark, on_light = _from_hls(hue, 0.13, min(saturation, 0.2)), 'FFFFFF'
    best = on_light if contrast_ratio(on_light, accent) >= contrast_ratio(on_dark, accent) else on_dark
    roles['on_accent'] = _reads_on(best, accent, 4.5)
    # A bold deck puts the accent itself behind the cover and the dividers; the
    # others keep them quiet, so the accent stays an accent.
    if theme == 'bold':
        roles['cover_fill'], roles['cover_ink'] = accent, roles['on_accent']
        roles['band'], roles['band_ink'] = accent, roles['on_accent']
    else:
        roles['cover_fill'] = 'FFFFFF' if theme == 'light' else surface
        roles['cover_ink'] = roles['ink'] if theme == 'dark' else _reads_on(roles['ink'], 'FFFFFF', 7.0)
        roles['band'], roles['band_ink'] = roles['surface_alt'], roles['ink']
    roles['cover_muted'] = (roles['cover_ink'] if theme == 'bold'
                            else _reads_on(roles['muted'], roles['cover_fill'], 4.5))
    return roles


# ---------------------------------------------------------------- content


def bullets_of(body, limit=MAX_BULLETS, words=BULLET_WORDS):
    """The lines of a slide, as bullets, with the model's own markers removed.

    Returns `(bullets, shortened)`. A model told "one bullet per line" will still
    sometimes write "• " at the start of each, and rendering that under a real
    bullet glyph gives "• • Revenue rose" — stripping it is the single most
    visible line in this function.

    A body that arrives as one long paragraph is split into sentences instead.
    That is what makes a legacy draft, a locally authored one, or a model that
    ignored the brief render as a deck rather than as one enormous bullet.
    """
    lines = [MARKER.sub('', line).strip() for line in (body or '').split('\n')]
    lines = [line for line in lines if line]
    if len(lines) == 1 and len(lines[0]) > words * 8:
        lines = [part.strip() for part in SENTENCE.split(lines[0]) if part.strip()]
    shortened = False
    kept = []
    for line in lines[:limit]:
        pieces = line.split(' ')
        if len(pieces) > words * 2:
            line = ' '.join(pieces[:words * 2]).rstrip(' ,;:') + '…'
            shortened = True
        kept.append(line)
    if len(lines) > limit:
        shortened = True
        if kept:
            kept[-1] = kept[-1].rstrip('.') + '…'
    return kept, shortened


# ---------------------------------------------------------------- theme


def _theme_part(deck):
    return deck.slide_masters[0].part.part_related_by(RT.THEME)


def apply_theme(deck, roles):
    """Repaint the inherited Office theme so the deck is not stock Calibri blue.

    python-pptx has no theme API and loads `theme1.xml` as an opaque part, so
    this rewrites its bytes. Only the colour values and the two font names are
    touched: the format scheme, the object defaults and the eleven stock layouts
    stay exactly as Office wrote them, so "New Slide" in PowerPoint still works
    and there is no way to produce a file that needs repairing.

    Pinned to python-pptx==1.0.2 by the writable `blob` on a generic part; the
    guard test in tests/test_slides_deck.py fails loudly if that moves.
    """
    from lxml import etree
    part = _theme_part(deck)
    theme = etree.fromstring(part.blob)
    scheme = theme.find(qn('a:themeElements'))
    if scheme is None:
        return
    colours = scheme.find(qn('a:clrScheme'))
    fonts = scheme.find(qn('a:fontScheme'))
    wanted = {'dk1': roles['ink'], 'dk2': roles['ink'], 'lt1': 'FFFFFF', 'lt2': roles['surface'],
              'accent1': roles['accent'], 'accent2': roles['accent_soft'], 'accent3': roles['muted'],
              'accent4': roles['ink'], 'accent5': roles['surface_alt'], 'accent6': roles['accent_text'],
              'hlink': roles['accent_text'], 'folHlink': roles['muted']}
    if colours is not None:
        for name, value in wanted.items():
            slot = colours.find(qn('a:' + name))
            if slot is None:
                continue
            for child in list(slot):
                slot.remove(child)
            srgb = slot.makeelement(qn('a:srgbClr'), {'val': value})
            slot.append(srgb)
    if fonts is not None:
        for tag, face in (('a:majorFont', HEADING_FONT), ('a:minorFont', BODY_FONT)):
            group = fonts.find(qn(tag))
            if group is None:
                continue
            latin = group.find(qn('a:latin'))
            if latin is not None:
                latin.set('typeface', face)
    part.blob = etree.tostring(theme, xml_declaration=True, encoding='UTF-8', standalone=True)


def strip_binary_parts(deck):
    """Leave no binary part behind.

    `processors/engine.py` refuses any `.bin` member on upload, so a deck still
    carrying python-pptx's inherited printer settings would be rejected by the
    platform that made it. The thumbnail goes for a different reason: it is a
    blank 4:3 Office preview that becomes the file's icon for a 16:9 deck.
    """
    for relationship in list(deck.part.rels.values()):
        if relationship.reltype.endswith('/printerSettings'):
            deck.part.drop_rel(relationship.rId)
    package = deck.part.package
    for relationship in list(package._rels.values()):
        if relationship.reltype.endswith('/thumbnail'):
            package.drop_rel(relationship.rId)


# ---------------------------------------------------------------- text


def _frame(shape, anchor=MSO_ANCHOR.TOP):
    """A text frame that reflows when it is edited.

    python-pptx writes `wrap="none"` with `spAutoFit` by default, which is why
    the old decks grew their boxes off the slide instead of rewrapping.
    """
    frame = shape.text_frame
    frame.word_wrap = True
    frame.auto_size = MSO_AUTO_SIZE.NONE
    frame.vertical_anchor = anchor
    frame.margin_left = frame.margin_right = 0
    frame.margin_top = frame.margin_bottom = 0
    return frame


def _paragraph(frame, index):
    return frame.paragraphs[0] if index == 0 else frame.add_paragraph()


def _write(paragraph, text, *, font, size, colour, bold=False, spacing=1.15,
           before=0, after=0, align=PP_ALIGN.LEFT):
    paragraph.text = text
    paragraph.alignment = align
    paragraph.line_spacing = spacing
    paragraph.space_before = Pt(before)
    paragraph.space_after = Pt(after)
    for run in paragraph.runs:
        run.font.name = font
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = _rgb(colour)
    return paragraph


def _bullet(paragraph, colour, size):
    """A real hanging bullet: the glyph sits outside the text, not above it.

    python-pptx has no bullet API. `marL` with a matching negative `indent` is
    what makes a wrapped bullet line up under its own text instead of under the
    dot — the difference between a list and someone having typed a dot.
    """
    properties = paragraph._pPr if paragraph._pPr is not None else paragraph._p.get_or_add_pPr()
    hang = Pt(size * 0.95)
    properties.set('marL', str(int(hang)))
    properties.set('indent', str(-int(hang)))
    for tag, attributes in ((qn('a:buClr'), None),
                            (qn('a:buFont'), {'typeface': BULLET_FONT, 'pitchFamily': '34', 'charset': '0'}),
                            (qn('a:buChar'), {'char': '•'})):
        for existing in properties.findall(tag):
            properties.remove(existing)
        element = properties.makeelement(tag, attributes or {})
        if tag == qn('a:buClr'):
            element.append(element.makeelement(qn('a:srgbClr'), {'val': _hex(colour).upper()}))
        properties.append(element)


def _no_bullet(paragraph):
    properties = paragraph._pPr if paragraph._pPr is not None else paragraph._p.get_or_add_pPr()
    for tag in ('a:buClr', 'a:buFont', 'a:buChar', 'a:buAutoNum', 'a:buNone'):
        for existing in properties.findall(qn(tag)):
            properties.remove(existing)
    properties.append(properties.makeelement(qn('a:buNone'), {}))


def _text_width(text, size):
    _register_font()
    return pdfmetrics.stringWidth(text, 'PDFMaster', size) * WIDTH_SAFETY


def _wrapped_lines(text, size, width_emu):
    width = Emu(int(width_emu)).pt
    return max(1, -(-_text_width(text, size) // max(width, 1)))


# ---------------------------------------------------------------- layout


class Zone:
    """Where something sits on a slide, in EMU.

    Geometry is named rather than written inline at the call site, because that
    is the seam a later image variant needs: a half-width picture layout becomes
    another zone table, not another renderer.
    """

    __slots__ = ('left', 'top', 'width', 'height')

    def __init__(self, left, top, width, height):
        self.left, self.top, self.width, self.height = int(left), int(top), int(width), int(height)

    def box(self):
        return self.left, self.top, self.width, self.height


CONTENT_WIDTH = int(SLIDE_WIDTH - 2 * MARGIN)
ZONES = {
    'eyebrow': Zone(MARGIN, Inches(0.62), CONTENT_WIDTH, Inches(0.3)),
    'headline': Zone(MARGIN, Inches(1.0), CONTENT_WIDTH, Inches(1.25)),
    'rule': Zone(MARGIN, Inches(2.38), Inches(1.1), Pt(3)),
    'body': Zone(MARGIN, Inches(2.75), CONTENT_WIDTH, Inches(3.65)),
    'body_left': Zone(MARGIN, Inches(2.75), int(CONTENT_WIDTH * 0.47), Inches(3.65)),
    'body_right': Zone(int(MARGIN + CONTENT_WIDTH * 0.53), Inches(2.75),
                       int(CONTENT_WIDTH * 0.47), Inches(3.65)),
    'column_rule': Zone(int(MARGIN + CONTENT_WIDTH * 0.5), Inches(2.85), Pt(2), Inches(3.4)),
    'cover_title': Zone(MARGIN, Inches(2.35), int(CONTENT_WIDTH * 0.78), Inches(2.1)),
    'cover_rule': Zone(MARGIN, Inches(4.65), Inches(1.6), Pt(4)),
    'cover_subtitle': Zone(MARGIN, Inches(4.95), int(CONTENT_WIDTH * 0.7), Inches(0.9)),
    'statement': Zone(MARGIN, Inches(2.5), int(CONTENT_WIDTH * 0.86), Inches(2.6)),
    'divider_band': Zone(0, Inches(2.55), SLIDE_WIDTH, Inches(2.4)),
    'divider_title': Zone(MARGIN, Inches(3.05), int(CONTENT_WIDTH * 0.8), Inches(1.4)),
    'footer': Zone(MARGIN, Inches(6.82), int(CONTENT_WIDTH * 0.7), Inches(0.32)),
    'number': Zone(int(SLIDE_WIDTH - MARGIN - Inches(1.0)), Inches(6.82), Inches(1.0), Inches(0.32)),
    'accent_bar': Zone(0, 0, Inches(0.18), SLIDE_HEIGHT),
    # Deliberately bleeds off the bottom-right corner: a disc that runs past the
    # edge reads as a design device, where one tucked inside reads as a bubble.
    # It is added before any text, so it always sits behind it.
    'cover_mark': Zone(int(SLIDE_WIDTH - Inches(3.4)), int(SLIDE_HEIGHT - Inches(3.4)),
                       Inches(4.6), Inches(4.6)),
}


def layout_for(index, bullets, total):
    """Which layout a slide gets. Deterministic: the same content is the same deck."""
    if index == 0 and total >= 2:
        return 'cover'
    if not bullets:
        return 'divider'
    if len(bullets) == 1 and len(bullets[0]) <= 90:
        return 'statement'
    if len(bullets) >= 5:
        return 'two_column'
    return 'bullets'


def _shape(slide, zone, colour, shape=MSO_SHAPE.RECTANGLE):
    element = slide.shapes.add_shape(shape, *zone.box())
    element.fill.solid()
    element.fill.fore_color.rgb = _rgb(colour)
    element.line.fill.background()
    element.shadow.inherit = False
    return element


def _slide_number(slide, zone, roles):
    """A real slide-number field, so deleting a slide renumbers the rest."""
    frame = _frame(slide.shapes.add_textbox(*zone.box()))
    paragraph = frame.paragraphs[0]
    _write(paragraph, '', font=BODY_FONT, size=10, colour=roles['muted'], align=PP_ALIGN.RIGHT)
    field = paragraph._p.makeelement(qn('a:fld'), {'id': '{B7A4E0C1-4C1E-4D3E-9F2A-0A1B2C3D4E5F}',
                                                   'type': 'slidenum'})
    properties = field.makeelement(qn('a:rPr'), {'lang': 'en-US'})
    fill = properties.makeelement(qn('a:solidFill'), {})
    fill.append(fill.makeelement(qn('a:srgbClr'), {'val': _hex(roles['muted']).upper()}))
    properties.append(fill)
    latin = properties.makeelement(qn('a:latin'), {'typeface': BODY_FONT})
    properties.append(latin)
    field.append(properties)
    text = field.makeelement(qn('a:t'), {})
    text.text = '1'
    field.append(text)
    paragraph._p.append(field)


# ---------------------------------------------------------------- slides


def _furniture(slide, roles, style, index, total, kind):
    """Everything every slide carries. The accent element is added first."""
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = _rgb(roles['cover_fill'] if kind == 'cover' else roles['surface'])
    # shapes[0] is the accent element on every slide, filled with the brand
    # colour exactly as given. tests/test_slides_deck.py pins this.
    _shape(slide, ZONES['accent_bar'], roles['accent'])
    if kind == 'cover':
        _shape(slide, ZONES['cover_mark'], roles['accent_soft'], MSO_SHAPE.OVAL)
    brand = (style or {}).get('brand_name', '')
    if brand:
        frame = _frame(slide.shapes.add_textbox(*ZONES['footer'].box()))
        _write(frame.paragraphs[0], brand, font=BODY_FONT, size=10, colour=roles['muted'])
        _no_bullet(frame.paragraphs[0])
    if kind != 'cover':
        _slide_number(slide, ZONES['number'], roles)
    logo = (style or {}).get('logo_png')
    if logo:
        from PIL import Image
        with Image.open(io.BytesIO(logo)) as picture:
            scale = min(1.5 / picture.width, 0.48 / picture.height)
            width, height = picture.width * scale, picture.height * scale
        slide.shapes.add_picture(io.BytesIO(logo), Inches(12.65 - width), Inches(7.15 - height),
                                 width=Inches(width), height=Inches(height))


def _headline(slide, zone, text, roles, *, size, colour=None, anchor=MSO_ANCHOR.BOTTOM, lines=2):
    """A headline that shrinks to fit rather than being renamed "Section"."""
    while size > 18 and _wrapped_lines(text, size, zone.width) > lines:
        size -= 2
    frame = _frame(slide.shapes.add_textbox(*zone.box()), anchor)
    paragraph = _write(frame.paragraphs[0], text, font=HEADING_FONT, size=size,
                       colour=colour or roles['ink'], spacing=1.08)
    _no_bullet(paragraph)
    return paragraph


def _bullet_block(slide, zone, bullets, roles, size):
    frame = _frame(slide.shapes.add_textbox(*zone.box()))
    for index, bullet in enumerate(bullets):
        paragraph = _write(_paragraph(frame, index), bullet, font=BODY_FONT, size=size,
                           colour=roles['ink'], spacing=LINE_MULTIPLE,
                           before=0 if index == 0 else size * 0.55)
        _bullet(paragraph, roles['accent_text'], size)
    return frame


def _eyebrow(slide, text, roles):
    frame = _frame(slide.shapes.add_textbox(*ZONES['eyebrow'].box()))
    _no_bullet(_write(frame.paragraphs[0], text, font=BODY_FONT, size=10,
                      colour=roles['muted'], bold=True))


def _draw(slide, kind, section, bullets, roles, style, index, total, size, locale):
    _furniture(slide, roles, style, index, total, kind)
    heading = section['heading'].strip() or section.get('_title', '')
    if kind == 'cover':
        _headline(slide, ZONES['cover_title'], heading, roles, size=44,
                  colour=roles['cover_ink'], lines=3)
        # On a bold deck the cover is the accent, so the rule has to be the ink.
        _shape(slide, ZONES['cover_rule'],
               roles['cover_ink'] if roles['theme'] == 'bold' else roles['accent'])
        subtitle = bullets[0] if bullets else ''
        if subtitle:
            frame = _frame(slide.shapes.add_textbox(*ZONES['cover_subtitle'].box()))
            _no_bullet(_write(frame.paragraphs[0], subtitle, font=BODY_FONT, size=18,
                              colour=roles['cover_muted'], spacing=1.25))
        return
    if kind == 'divider':
        _shape(slide, ZONES['divider_band'], roles['band'])
        _eyebrow(slide, f'{index + 1:02d} / {total:02d}', roles)
        _headline(slide, ZONES['divider_title'], heading, roles, size=34,
                  colour=roles['band_ink'], anchor=MSO_ANCHOR.TOP, lines=2)
        return
    _eyebrow(slide, f'{index + 1:02d} / {total:02d}', roles)
    if kind == 'statement':
        # The headline steps back so the one idea can carry the slide. Setting
        # the statement smaller than its own heading made it read as a subtitle.
        _headline(slide, ZONES['headline'], heading, roles, size=20,
                  colour=roles['muted'], anchor=MSO_ANCHOR.BOTTOM, lines=2)
        _shape(slide, ZONES['rule'], roles['accent'])
        frame = _frame(slide.shapes.add_textbox(*ZONES['statement'].box()), MSO_ANCHOR.TOP)
        _no_bullet(_write(frame.paragraphs[0], bullets[0], font=HEADING_FONT,
                          size=40 if len(bullets[0]) <= 52 else 32,
                          colour=roles['ink'], spacing=1.14))
        return
    _headline(slide, ZONES['headline'], heading, roles, size=32)
    _shape(slide, ZONES['rule'], roles['accent'])
    if kind == 'two_column':
        half = -(-len(bullets) // 2)
        _bullet_block(slide, ZONES['body_left'], bullets[:half], roles, size)
        _bullet_block(slide, ZONES['body_right'], bullets[half:], roles, size)
        _shape(slide, ZONES['column_rule'], roles['accent_soft'])
        return
    _bullet_block(slide, ZONES['body'], bullets, roles, size)


def _fits(bullets, size, zone):
    """Roughly how tall a bullet block runs, without wrapping anything for real."""
    height = 0
    for index, bullet in enumerate(bullets):
        lines = _wrapped_lines(bullet, size, zone.width - Pt(size))
        height += lines * size * LINE_MULTIPLE + (0 if index == 0 else size * 0.55)
    return height <= Emu(zone.height).pt


def _deck_size(prepared):
    """One body size for the whole deck, so slides do not change size partway."""
    for step in range(FIT_STEPS + 1):
        size = MAX_BODY_SIZE - (MAX_BODY_SIZE - MIN_BODY_SIZE) * step / FIT_STEPS
        if all(kind in ('cover', 'divider', 'statement')
               or _fits(bullets, size, ZONES['body_left' if kind == 'two_column' else 'body'])
               for kind, bullets in prepared):
            return size
    return MIN_BODY_SIZE


def render_pptx(content, path, locale='en', role='user_document', style=None):
    """One section, one slide — with the first one as the deck's title slide.

    The cover is `sections[0]` rather than an extra slide, so the count the
    customer asked for is the count delivered and the price is unchanged. With a
    single section there is nothing to introduce, so it stays a content slide.
    """
    style = style or {}
    roles = palette(style.get('accent', '#255e49'), style.get('deck_theme', 'light'))
    sections = [dict(section) for section in content['sections']]
    question_label = {'en': 'Question', 'uz': 'Savol', 'ru': 'Вопрос'}[locale]
    for number, question in enumerate(content.get('questions', []), 1):
        sections.append({'id': f'q{number}', 'heading': f'{question_label} {number}',
                         'body': '\n'.join([question['stem']] + list(question.get('options', []))),
                         'notes': ''})

    total = len(sections)
    shortened = False
    prepared = []
    for index, section in enumerate(sections):
        bullets, cut = bullets_of(section['body'])
        shortened = shortened or cut
        kind = layout_for(index, bullets, total)
        if kind == 'cover':
            section = {**section, '_title': content['title']}
            if not section['heading'].strip():
                section['heading'] = content['title']
            bullets = bullets[:1]
        prepared.append((kind, bullets, section))

    deck = Presentation()
    deck.slide_width, deck.slide_height = SLIDE_WIDTH, SLIDE_HEIGHT
    apply_theme(deck, roles)
    size = _deck_size([(kind, bullets) for kind, bullets, _ in prepared])

    for index, (kind, bullets, section) in enumerate(prepared):
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        _draw(slide, kind, section, bullets, roles, style, index, total, size, locale)
        # The cover introduces the deck; there is nothing for a presenter to say
        # over it. Learner and public copies never carry notes at all.
        notes = '' if kind == 'cover' or role in ('learner_material', 'public_preview') else section.get('notes', '')
        slide.notes_slide.notes_text_frame.text = notes

    deck.core_properties.title = content['title']
    deck.core_properties.author = 'PDF Master'
    strip_binary_parts(deck)
    deck.save(str(path))
    return {'path': str(path), 'name': path.name,
            'mime_type': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'page_count': len(deck.slides), 'role': role, 'shortened': shortened}
