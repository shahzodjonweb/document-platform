"""How each slide layout is drawn.

One drawer per layout id in `layouts.CATALOGUE`, registered with `@draws`. A
drawer receives a slide on which the ground (background and accent bar), any
photo and the chrome (brand, slide number, logo) are already in place, and adds
only the layout's own text and shapes. That keeps the shape order the same on
every slide, and keeps any one layout readable on its own.

Two rules hold for every drawer. Text is only ever written on the slide's own
surface or on a panel whose colour role was contrast-corrected for it — never
over a photo. And every field is clipped to a word limit, marking the deck as
shortened, rather than being allowed to run off its box.
"""
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from . import slides as kit
from .layouts import PRO, parse_number

DRAW = {}

LEFT, WIDTH = 0.85, 13.333 - 2 * 0.85
TOP, BOTTOM = 2.75, 6.4
LABELS = {
    'pros': {'en': 'For', 'uz': 'Afzalliklari', 'ru': 'За'},
    'cons': {'en': 'Against', 'uz': 'Kamchiliklari', 'ru': 'Против'},
    'vs': {'en': 'vs', 'uz': 'va', 'ru': 'vs'},
}


def draws(*kinds):
    def register(function):
        for kind in kinds:
            DRAW[kind] = function
        return function
    return register


class Ctx:
    """What a drawer needs to know about the slide it is drawing."""

    __slots__ = ('slide', 'roles', 'style', 'index', 'total', 'size', 'locale', 'photo', 'shortened')

    def __init__(self, slide, roles, style, index, total, size, locale, photo=False):
        self.slide, self.roles, self.style = slide, roles, style
        self.index, self.total, self.size, self.locale = index, total, size, locale
        self.photo, self.shortened = photo, False


def Z(left, top, width, height):
    return kit.Zone(Inches(left), Inches(top), Inches(width), Inches(height))


def clip(ctx, text, words):
    """A field held to a word limit, with the deck marked shortened if it was cut."""
    parts = str(text or '').split()
    if len(parts) <= words:
        return ' '.join(parts)
    ctx.shortened = True
    return ' '.join(parts[:words]).rstrip(',;:.') + '…'


def fit(text, size, zone, lines, floor):
    """The largest size up to `size` at which the text keeps to `lines` lines."""
    while size > floor and kit._wrapped_lines(text, size, zone.width) > lines:
        size -= 2
    return size


def put(ctx, zone, value, *, size, colour, font=None, bold=False, align=PP_ALIGN.LEFT,
        anchor=MSO_ANCHOR.TOP, spacing=1.15):
    """One paragraph of text in a zone, with wrapping left to the viewer."""
    frame = kit._frame(ctx.slide.shapes.add_textbox(*zone.box()), anchor)
    paragraph = kit._write(frame.paragraphs[0], value, font=font or kit.BODY_FONT, size=size,
                           colour=colour, bold=bold, align=align, spacing=spacing)
    kit._no_bullet(paragraph)
    return frame


def header(ctx, section, *, width=None, size=32):
    """Eyebrow, headline and accent rule — the top of most content slides."""
    width = width or WIDTH
    # Every box, not just the text in it, stays out of a photo's zone: someone
    # editing the deck can type into the whole box.
    put(ctx, Z(LEFT, 0.62, width, 0.3), f'{ctx.index + 1:02d} / {ctx.total:02d}', size=10,
        colour=ctx.roles['muted'], bold=True)
    kit._headline(ctx.slide, Z(LEFT, 1.0, width, 1.25), clip(ctx, section['heading'], 14),
                  ctx.roles, size=size)
    kit._shape(ctx.slide, kit.ZONES['rule'], ctx.roles['accent'])


def items_of(section):
    return section.get('items') or []


def columns_of(section):
    return [column for column in section.get('columns') or [] if column]


def body_text(section):
    return ' '.join(str(section.get('body') or '').split())


# ---------------------------------------------------------------- existing


@draws('cover')
def cover(ctx, section, lines):
    roles, photo = ctx.roles, ctx.photo
    title = section['heading'].strip() or section.get('_title', '')
    zone = Z(LEFT, 2.35, WIDTH * 0.5, 2.1) if photo else kit.ZONES['cover_title']
    kit._headline(ctx.slide, zone, clip(ctx, title, 14), roles, size=44,
                  colour=roles['cover_ink'], lines=3)
    # On a bold deck the cover is the accent, so the rule has to be the ink.
    kit._shape(ctx.slide, kit.ZONES['cover_rule'],
               roles['cover_ink'] if roles['theme'] == 'bold' else roles['accent'])
    if lines:
        subtitle_zone = Z(LEFT, 4.95, WIDTH * 0.5, 0.9) if photo else kit.ZONES['cover_subtitle']
        put(ctx, subtitle_zone, clip(ctx, lines[0], 24), size=18, colour=roles['cover_muted'],
            spacing=1.25)


@draws('section')
def section_(ctx, section, lines):
    roles = ctx.roles
    kit._shape(ctx.slide, kit.ZONES['divider_band'], roles['band'])
    kit._eyebrow(ctx.slide, f'{ctx.index + 1:02d} / {ctx.total:02d}', roles)
    kicker = lines[0] if lines and section.get('layout') not in (None, '', 'auto') else ''
    zone = Z(LEFT, 2.95, WIDTH * 0.8, 1.2) if kicker else kit.ZONES['divider_title']
    kit._headline(ctx.slide, zone, clip(ctx, section['heading'], 14), roles, size=34,
                  colour=roles['band_ink'], anchor=MSO_ANCHOR.TOP, lines=2)
    if kicker:
        put(ctx, Z(LEFT, 4.2, WIDTH * 0.8, 0.6), clip(ctx, kicker, 20), size=16,
            colour=roles['band_muted'])


@draws('statement')
def statement(ctx, section, lines):
    roles = ctx.roles
    kit._eyebrow(ctx.slide, f'{ctx.index + 1:02d} / {ctx.total:02d}', roles)
    # The headline steps back so the one idea can carry the slide. Setting the
    # statement smaller than its own heading made it read as a subtitle.
    kit._headline(ctx.slide, kit.ZONES['headline'], section['heading'], roles, size=20,
                  colour=roles['muted'], anchor=MSO_ANCHOR.BOTTOM, lines=2)
    kit._shape(ctx.slide, kit.ZONES['rule'], roles['accent'])
    line = lines[0] if lines else body_text(section)
    frame = kit._frame(ctx.slide.shapes.add_textbox(*kit.ZONES['statement'].box()), MSO_ANCHOR.TOP)
    kit._no_bullet(kit._write(frame.paragraphs[0], line, font=kit.HEADING_FONT,
                              size=40 if len(line) <= 52 else 32, colour=roles['ink'], spacing=1.14))


@draws('bullets')
def bullets(ctx, section, lines):
    header(ctx, section)
    kit._bullet_block(ctx.slide, kit.ZONES['body'], lines, ctx.roles, ctx.size)


@draws('two_column')
def two_column(ctx, section, lines):
    roles = ctx.roles
    header(ctx, section)
    titled = [item for item in items_of(section) if item.get('label') and item.get('text')]
    if len(titled) == 2 and section.get('layout') == 'two_column':
        for zone, item in zip((kit.ZONES['body_left'], kit.ZONES['body_right']), titled):
            frame = kit._frame(ctx.slide.shapes.add_textbox(*zone.box()))
            kit._no_bullet(kit._write(frame.paragraphs[0], clip(ctx, item['label'], 8),
                                      font=kit.HEADING_FONT, size=22, colour=roles['accent_text'],
                                      bold=True, after=10))
            kit._no_bullet(kit._write(frame.add_paragraph(), clip(ctx, item['text'], 40),
                                      font=kit.BODY_FONT, size=16, colour=roles['ink'],
                                      spacing=kit.LINE_MULTIPLE))
    else:
        half = -(-len(lines) // 2)
        kit._bullet_block(ctx.slide, kit.ZONES['body_left'], lines[:half], roles, ctx.size)
        kit._bullet_block(ctx.slide, kit.ZONES['body_right'], lines[half:], roles, ctx.size)
    kit._shape(ctx.slide, kit.ZONES['column_rule'], roles['accent_soft'])


# ---------------------------------------------------------------- text


@draws('quote')
def quote(ctx, section, lines):
    roles = ctx.roles
    kit._eyebrow(ctx.slide, f'{ctx.index + 1:02d} / {ctx.total:02d}', roles)
    if section['heading'].strip():
        kit._headline(ctx.slide, kit.ZONES['headline'], section['heading'], roles, size=20,
                      colour=roles['muted'], lines=2)
    put(ctx, Z(LEFT, 2.25, 1.0, 1.4), '“', size=110, colour=roles['accent_text'],
        font=kit.HEADING_FONT, spacing=1.0)
    words = clip(ctx, body_text(section), 45)
    put(ctx, Z(LEFT + 1.0, 2.7, WIDTH * 0.8, 2.6), words, size=30 if len(words) <= 140 else 25,
        colour=roles['ink'], font=kit.HEADING_FONT, spacing=1.2)
    who = items_of(section)[0]
    attribution = ', '.join(part for part in (clip(ctx, who.get('label'), 8), clip(ctx, who.get('text'), 12)) if part)
    put(ctx, Z(LEFT + 1.0, 5.45, WIDTH * 0.8, 0.6), f'— {attribution}', size=16, colour=roles['muted'])


@draws('closing')
def closing(ctx, section, lines):
    roles = ctx.roles
    kit._headline(ctx.slide, kit.ZONES['cover_title'], clip(ctx, section['heading'], 14), roles,
                  size=44, colour=roles['cover_ink'], lines=3)
    kit._shape(ctx.slide, kit.ZONES['cover_rule'],
               roles['cover_ink'] if roles['theme'] == 'bold' else roles['accent'])
    line = lines[0] if lines else ''
    if line:
        put(ctx, kit.ZONES['cover_subtitle'], clip(ctx, line, 24), size=18, colour=roles['cover_muted'],
            spacing=1.25)


# ---------------------------------------------------------------- data


@draws('big_number')
def big_number(ctx, section, lines):
    roles = ctx.roles
    header(ctx, section, size=28)
    item = items_of(section)[0]
    value = clip(ctx, item.get('value'), 3)
    zone = Z(LEFT, 2.75, 5.6, 2.6)
    put(ctx, zone, value, size=fit(value, 110, zone, 1, 60), colour=roles['accent_text'],
        font=kit.HEADING_FONT, anchor=MSO_ANCHOR.MIDDLE, spacing=1.0)
    frame = kit._frame(ctx.slide.shapes.add_textbox(*Z(LEFT + 6.0, 3.0, WIDTH - 6.0, 2.8).box()),
                       MSO_ANCHOR.MIDDLE)
    kit._no_bullet(kit._write(frame.paragraphs[0], clip(ctx, item.get('label'), 10),
                              font=kit.HEADING_FONT, size=28, colour=roles['ink'], after=8))
    if item.get('text'):
        kit._no_bullet(kit._write(frame.add_paragraph(), clip(ctx, item['text'], 30),
                                  font=kit.BODY_FONT, size=16, colour=roles['muted'],
                                  spacing=kit.LINE_MULTIPLE))


@draws('stats')
def stats(ctx, section, lines):
    roles = ctx.roles
    header(ctx, section)
    tiles = items_of(section)
    gap = 0.35
    width = (WIDTH - gap * (len(tiles) - 1)) / len(tiles)
    for position, item in enumerate(tiles):
        left = LEFT + position * (width + gap)
        kit._shape(ctx.slide, Z(left, 3.0, width, 0.06), roles['accent'])
        value = clip(ctx, item.get('value'), 3)
        zone = Z(left, 3.2, width, 1.1)
        put(ctx, zone, value, size=fit(value, 52, zone, 1, 28), colour=roles['accent_text'],
            font=kit.HEADING_FONT, spacing=1.0)
        put(ctx, Z(left, 4.4, width, 0.7), clip(ctx, item.get('label'), 8), size=18,
            colour=roles['ink'], bold=True)
        if item.get('text'):
            put(ctx, Z(left, 5.1, width, 1.2), clip(ctx, item['text'], 18), size=14,
                colour=roles['muted'])


@draws('chart')
def chart(ctx, section, lines):
    """Horizontal bars drawn from shapes.

    A python-pptx chart embeds an Excel workbook under /ppt/embeddings/, which
    our own upload check refuses — a customer could not re-upload their deck.
    Shapes render the same in every viewer and stay editable as shapes.
    """
    roles = ctx.roles
    header(ctx, section)
    bars = items_of(section)
    numbers = [parse_number(item.get('value')) or 0 for item in bars]
    top, span = 2.85, BOTTOM - 2.85
    unit = columns_of(section)[:1]
    if unit:
        put(ctx, Z(LEFT, 2.55, WIDTH, 0.3), clip(ctx, unit[0], 6), size=12, colour=roles['muted'],
            align=PP_ALIGN.RIGHT)
    # Few bars get thicker rows rather than leaving the lower half of the slide empty.
    row = min(0.85, span / len(bars))
    label_width, value_width = WIDTH * 0.27, WIDTH * 0.13
    area = WIDTH - label_width - value_width - 0.3
    peak = max(numbers) or 1
    for position, (item, number) in enumerate(zip(bars, numbers)):
        y = top + position * row
        put(ctx, Z(LEFT, y, label_width, row), clip(ctx, item.get('label'), 6), size=14,
            colour=roles['ink'], align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)
        length = max(0.04, area * number / peak)
        bar = kit._shape(ctx.slide, Z(LEFT + label_width + 0.15, y + row * 0.2, length, row * 0.6),
                         roles['accent'])
        # An outline in the corrected accent keeps a pale brand colour visible.
        bar.line.fill.solid()
        bar.line.fill.fore_color.rgb = kit._rgb(roles['accent_text'])
        bar.line.width = Pt(0.75)
        put(ctx, Z(LEFT + label_width + 0.3 + length, y, value_width + (area - length), row),
            clip(ctx, item.get('value'), 3), size=14, colour=roles['ink'], bold=True,
            anchor=MSO_ANCHOR.MIDDLE)


@draws('table')
def table(ctx, section, lines):
    roles = ctx.roles
    header(ctx, section)
    columns = columns_of(section)[:3]
    rows = items_of(section)[:6]
    height = min(BOTTOM - TOP, 0.62 * (len(rows) + 1))
    frame = ctx.slide.shapes.add_table(len(rows) + 1, len(columns), *Z(LEFT, TOP, WIDTH, height).box())
    grid = frame.table
    grid.horz_banding = False
    grid.first_row = True

    def cell(row, column, value, fill, colour, bold=False):
        target = grid.cell(row, column)
        target.fill.solid()
        target.fill.fore_color.rgb = kit._rgb(fill)
        target.margin_left = target.margin_right = Inches(0.12)
        target.margin_top = target.margin_bottom = Inches(0.06)
        target.vertical_anchor = MSO_ANCHOR.MIDDLE
        paragraph = target.text_frame.paragraphs[0]
        kit._write(paragraph, value, font=kit.BODY_FONT, size=16 if row == 0 else 15,
                   colour=colour, bold=bold)
        kit._no_bullet(paragraph)

    for column, name in enumerate(columns):
        cell(0, column, clip(ctx, name, 5), roles['accent'], roles['on_accent'], bold=True)
    for row, item in enumerate(rows, 1):
        fill, ink = (roles['surface'], roles['ink']) if row % 2 else (roles['card'], roles['card_ink'])
        values = [item.get('label', ''), item.get('text', ''), item.get('value', '')]
        for column in range(len(columns)):
            cell(row, column, clip(ctx, values[column], 12), fill, ink, bold=column == 0)


@draws('comparison')
def comparison(ctx, section, lines):
    roles = ctx.roles
    header(ctx, section)
    first, second = columns_of(section)[:2]
    label_width = WIDTH * 0.26
    column_width = (WIDTH - label_width - 0.7) / 2
    a_left = LEFT + label_width
    b_left = a_left + column_width + 0.7
    for left, name in ((a_left, first), (b_left, second)):
        kit._shape(ctx.slide, Z(left, 2.7, column_width, 0.6), roles['accent'])
        put(ctx, Z(left, 2.7, column_width, 0.6), clip(ctx, name, 5), size=18,
            colour=roles['on_accent'], bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    kit._shape(ctx.slide, Z(a_left + column_width + 0.1, 2.73, 0.5, 0.5), roles['card'], MSO_SHAPE.OVAL)
    put(ctx, Z(a_left + column_width + 0.1, 2.73, 0.5, 0.5), LABELS['vs'][ctx.locale], size=12,
        colour=roles['card_accent'], bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    rows = [item for item in items_of(section) if item.get('label')][:5]
    row = min(0.75, (BOTTOM - 3.45) / len(rows))
    for position, item in enumerate(rows):
        y = 3.45 + position * row
        if position:
            kit._shape(ctx.slide, Z(LEFT, y, WIDTH, 0.015), roles['accent_soft'])
        put(ctx, Z(LEFT, y, label_width - 0.2, row), clip(ctx, item['label'], 6), size=14,
            colour=roles['muted'], bold=True, anchor=MSO_ANCHOR.MIDDLE)
        put(ctx, Z(a_left, y, column_width, row), clip(ctx, item.get('text'), 14), size=15,
            colour=roles['ink'], align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        put(ctx, Z(b_left, y, column_width, row), clip(ctx, item.get('value'), 14), size=15,
            colour=roles['ink'], align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)


# ---------------------------------------------------------------- structure


@draws('agenda')
def agenda(ctx, section, lines):
    roles = ctx.roles
    header(ctx, section)
    entries = [item for item in items_of(section) if item.get('label')][:6]
    columns = 2 if len(entries) > 4 else 1
    per_column = -(-len(entries) // columns)
    width = (WIDTH - 0.5 * (columns - 1)) / columns
    row = (BOTTOM - TOP) / per_column
    for position, item in enumerate(entries):
        column, line = divmod(position, per_column)
        left, y = LEFT + column * (width + 0.5), TOP + line * row
        put(ctx, Z(left, y, 0.95, row), f'{position + 1:02d}', size=26, colour=roles['accent_text'],
            font=kit.HEADING_FONT)
        frame = kit._frame(ctx.slide.shapes.add_textbox(*Z(left + 1.0, y + 0.02, width - 1.0, row).box()))
        kit._no_bullet(kit._write(frame.paragraphs[0], clip(ctx, item['label'], 8), font=kit.BODY_FONT,
                                  size=20, colour=roles['ink'], bold=True, after=2))
        if item.get('text'):
            kit._no_bullet(kit._write(frame.add_paragraph(), clip(ctx, item['text'], 14),
                                      font=kit.BODY_FONT, size=14, colour=roles['muted']))


@draws('timeline')
def timeline(ctx, section, lines):
    roles = ctx.roles
    header(ctx, section)
    events = items_of(section)[:6]
    kit._shape(ctx.slide, Z(LEFT, 4.0, WIDTH, 0.04), roles['accent_soft'])
    slot = WIDTH / len(events)
    for position, item in enumerate(events):
        centre = LEFT + slot * (position + 0.5)
        left, width = centre - slot / 2 + 0.06, slot - 0.12
        kit._shape(ctx.slide, Z(centre - 0.13, 3.89, 0.26, 0.26), roles['accent'], MSO_SHAPE.OVAL)
        put(ctx, Z(left, 3.05, width, 0.7), clip(ctx, item.get('value'), 4), size=16,
            colour=roles['accent_text'], bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.BOTTOM)
        put(ctx, Z(left, 4.35, width, 0.7), clip(ctx, item.get('label'), 7), size=16,
            colour=roles['ink'], bold=True, align=PP_ALIGN.CENTER)
        if item.get('text'):
            put(ctx, Z(left, 5.05, width, 1.3), clip(ctx, item['text'], 14), size=13,
                colour=roles['muted'], align=PP_ALIGN.CENTER)


@draws('process')
def process(ctx, section, lines):
    roles = ctx.roles
    header(ctx, section)
    steps = [item for item in items_of(section) if item.get('label')][:5]
    slot = WIDTH / len(steps)
    first = LEFT + slot / 2
    kit._shape(ctx.slide, Z(first, 3.33, slot * (len(steps) - 1), 0.04), roles['accent_soft'])
    for position, item in enumerate(steps):
        centre = LEFT + slot * (position + 0.5)
        left, width = centre - slot / 2 + 0.08, slot - 0.16
        kit._shape(ctx.slide, Z(centre - 0.35, 3.0, 0.7, 0.7), roles['accent'], MSO_SHAPE.OVAL)
        put(ctx, Z(centre - 0.35, 3.0, 0.7, 0.7), str(position + 1), size=20, colour=roles['on_accent'],
            bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        put(ctx, Z(left, 3.9, width, 0.7), clip(ctx, item['label'], 7), size=17, colour=roles['ink'],
            bold=True, align=PP_ALIGN.CENTER)
        if item.get('text'):
            put(ctx, Z(left, 4.6, width, 1.7), clip(ctx, item['text'], 18), size=14,
                colour=roles['muted'], align=PP_ALIGN.CENTER)


@draws('pros_cons')
def pros_cons(ctx, section, lines):
    roles = ctx.roles
    header(ctx, section)
    names = columns_of(section)
    groups = (
        ([item for item in items_of(section) if item.get('value', '').strip().lower() in PRO], '+',
         names[0] if len(names) > 0 else LABELS['pros'][ctx.locale]),
        ([item for item in items_of(section) if item.get('value', '').strip().lower() not in PRO], '–',
         names[1] if len(names) > 1 else LABELS['cons'][ctx.locale]),
    )
    width = WIDTH * 0.485
    for position, (points, glyph, name) in enumerate(groups):
        left = LEFT + position * (WIDTH - width)
        kit._shape(ctx.slide, Z(left, TOP, width, BOTTOM - TOP), roles['card'])
        kit._shape(ctx.slide, Z(left, TOP, width, 0.07), roles['accent'])
        frame = kit._frame(ctx.slide.shapes.add_textbox(*Z(left + 0.4, TOP + 0.35, width - 0.8,
                                                             BOTTOM - TOP - 0.6).box()))
        kit._no_bullet(kit._write(frame.paragraphs[0], clip(ctx, name, 5), font=kit.HEADING_FONT,
                                  size=24, colour=roles['card_accent'], bold=True, after=14))
        for item in points[:5]:
            paragraph = kit._write(frame.add_paragraph(), clip(ctx, item.get('label') or item.get('text'), 14),
                                   font=kit.BODY_FONT, size=19, colour=roles['card_ink'],
                                   spacing=kit.LINE_MULTIPLE, before=12)
            kit._bullet(paragraph, roles['card_accent'], 19, glyph)


@draws('cards')
def cards(ctx, section, lines):
    roles = ctx.roles
    header(ctx, section)
    entries = [item for item in items_of(section) if item.get('label')][:6]
    per_row = 2 if len(entries) == 4 else 3 if len(entries) > 3 else len(entries)
    rows = -(-len(entries) // per_row)
    gap = 0.3
    width = (WIDTH - gap * (per_row - 1)) / per_row
    height = (BOTTOM - TOP - gap * (rows - 1)) / rows
    for position, item in enumerate(entries):
        row, column = divmod(position, per_row)
        left, top = LEFT + column * (width + gap), TOP + row * (height + gap)
        kit._shape(ctx.slide, Z(left, top, width, height), roles['card'])
        frame = kit._frame(ctx.slide.shapes.add_textbox(*Z(left + 0.25, top + 0.2, width - 0.5,
                                                             height - 0.4).box()))
        first = True
        if item.get('value'):
            kit._no_bullet(kit._write(frame.paragraphs[0], clip(ctx, item['value'], 3).upper(),
                                      font=kit.BODY_FONT, size=11, colour=roles['card_accent'],
                                      bold=True, after=4))
            first = False
        heading = frame.paragraphs[0] if first else frame.add_paragraph()
        kit._no_bullet(kit._write(heading, clip(ctx, item['label'], 7), font=kit.HEADING_FONT,
                                  size=19, colour=roles['card_ink'], bold=True, after=6))
        if item.get('text'):
            kit._no_bullet(kit._write(frame.add_paragraph(), clip(ctx, item['text'], 20 if rows == 1 else 14),
                                      font=kit.BODY_FONT, size=14, colour=roles['card_muted'],
                                      spacing=kit.LINE_MULTIPLE))


@draws('matrix')
def matrix(ctx, section, lines):
    roles = ctx.roles
    header(ctx, section)
    cells = [item for item in items_of(section) if item.get('label')][:4]
    axes = columns_of(section)[:2]
    bottom = BOTTOM - (0.35 if axes else 0)
    gap = 0.12
    width, height = (WIDTH - gap) / 2, (bottom - TOP - gap) / 2
    for position, item in enumerate(cells):
        row, column = divmod(position, 2)
        tinted = (row + column) % 2 == 1
        fill = roles['accent_soft'] if tinted else roles['card']
        ink = roles['soft_ink'] if tinted else roles['card_ink']
        muted = roles['soft_muted'] if tinted else roles['card_muted']
        left, top = LEFT + column * (width + gap), TOP + row * (height + gap)
        kit._shape(ctx.slide, Z(left, top, width, height), fill)
        frame = kit._frame(ctx.slide.shapes.add_textbox(*Z(left + 0.3, top + 0.2, width - 0.6,
                                                             height - 0.4).box()))
        kit._no_bullet(kit._write(frame.paragraphs[0], clip(ctx, item['label'], 6), font=kit.HEADING_FONT,
                                  size=20, colour=ink, bold=True, after=6))
        if item.get('text'):
            kit._no_bullet(kit._write(frame.add_paragraph(), clip(ctx, item['text'], 18),
                                      font=kit.BODY_FONT, size=14, colour=muted,
                                      spacing=kit.LINE_MULTIPLE))
    if axes:
        put(ctx, Z(LEFT, bottom + 0.05, WIDTH, 0.3), '  ·  '.join(clip(ctx, axis, 5) for axis in axes),
            size=12, colour=roles['muted'], align=PP_ALIGN.CENTER)


# ---------------------------------------------------------------- photo

# Where each photo layout puts its picture. Nothing here overlaps a text zone
# or the footer band, so text never has to be read against a photograph.
PHOTO_ZONES = {
    'cover': Z(13.333 * 0.56, 0, 13.333 * 0.44, 6.55),
    'image_split': Z(13.333 * 0.52, 0, 13.333 * 0.48, 6.55),
    'image_full': Z(0.18, 0, 13.333 - 0.18, 5.3),
}


@draws('image_split')
def image_split(ctx, section, lines):
    width = 13.333 * 0.52 - LEFT - 0.45
    header(ctx, section, width=width, size=30)
    kit._bullet_block(ctx.slide, Z(LEFT, TOP, width, BOTTOM - TOP), lines, ctx.roles, ctx.size)


@draws('image_full')
def image_full(ctx, section, lines):
    roles = ctx.roles
    kit._headline(ctx.slide, Z(LEFT, 5.4, WIDTH * 0.7, 0.7), clip(ctx, section['heading'], 12), roles,
                  size=26, anchor=MSO_ANCHOR.TOP, lines=1)
    caption = lines[0] if lines else ''
    if caption:
        put(ctx, Z(LEFT, 6.1, WIDTH * 0.7, 0.55), clip(ctx, caption, 18), size=14, colour=roles['muted'])


def place_photo(slide, zone, photo):
    """A photo filling its zone, cropped rather than stretched.

    The crop is set on the picture rather than baked into the image, so the
    customer can reframe it in PowerPoint.
    """
    import io
    picture = slide.shapes.add_picture(io.BytesIO(photo['jpeg']), *zone.box())
    target = zone.width / zone.height
    source = photo['width'] / photo['height']
    if source > target:
        spare = 1 - target / source
        picture.crop_left = picture.crop_right = spare / 2
    elif source < target:
        spare = 1 - source / target
        picture.crop_top, picture.crop_bottom = spare * 0.4, spare * 0.6
    return picture
