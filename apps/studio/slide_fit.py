"""What of a slide's text shows, known by drawing the slide and reading what came out.

A manual send may not lose a word without the customer seeing it (the owner's
rule), so a send needs to know, per slide, before anything is sent. There are
many ways for a word not to reach a slide: a field's word limit, a box that
holds only so much, a list of six lines, a divider with room for one, an item
with no label, in the classic drawers and in two hundred variants. So nothing
here follows those paths: `left_out` compares the words a slide's fields hold
with the words on the slide, whichever drawer put them there.

`measure_deck` needs no LibreOffice, no network, no picture and no file: only
the draft's own fields, so the API can call it. Sixty slides of every field full
take 0.6 s on an M2 Pro (render_pptx 1.3 s) with pins that hold, up to 8 s with
none (each slide walks its variants), and one slide with every layout tried 0.03
to 0.05 s, or 0.35 s when none holds it.
"""
import copy
import math
import re
import time
from collections import Counter

from pptx.oxml.ns import qn

from . import layouts, slides, variants
from .slide_layouts import DRAW, PHOTO_ZONES, Ctx, _text_lines

_TEXT = qn('a:t')
# How python-pptx writes a control character into the slide's text.
_CONTROL = re.compile(r'_x[0-9A-Fa-f]{4}_|[\x00-\x1f]')
_EDGES = re.compile(r'^\W+|\W+$')


def _keys(text):
    """`text`'s words as told apart on a slide: in any case, without the punctuation round them.

    A word a drawer set in capitals or ended in '…' is still that word. One cut
    letter by letter is not, and a mark standing alone is no word. Upper first:
    'ı' and 'i' come out alike, as they do once set in capitals.
    """
    found = (_EDGES.sub('', word).upper().casefold() for word in _CONTROL.sub(' ', str(text or '')).split())
    return [word for word in found if word]


def _written(kind, section):
    """A slide's body line by line, as `slides.bullets_of` reads it: a list marker is not a word of it.

    With no body a list draws the slide's items instead, which is how a layout
    that could not hold them falls back. A cover, a divider or a caption draws
    the first of them at most, and has no place for items: the editor offers
    none there, so they must not hold up a send.
    """
    lines = [slides.MARKER.sub('', line) for line in str(section.get('body') or '').split('\n')]
    lines = [line for line in lines if line.strip()]
    if lines or kind not in ('bullets', 'two_column', 'statement', 'image_split'):
        return lines
    return [slides.MARKER.sub('', line) for line in layouts.as_lines(section)]


def _shown_fields(kind, section):
    """The heading (first) and the fields a layout has a place for, as its classic drawer reads them.

    What it has no place for is not missing from it: a list's items beside its
    body, a chart's sentences, the value of a process step. A field it reads
    only in part counts whole: a divider draws the first line of its body, and
    the rest does not show.
    """
    heading = str(section.get('heading') or '')
    items = section.get('items') or []
    columns = [column for column in section.get('columns') or [] if column]

    def cells(*keys, rows=items):
        return [row.get(key) or '' for row in rows for key in keys]
    if kind == 'questions':
        return [heading, *(text for entry in section['_questions']
                           for text in (entry['stem'], *entry.get('options', [])))]
    if kind == 'quote':
        return [heading, section.get('body') or '', *cells('label', 'text', rows=items[:1])]
    if kind == 'big_number':
        return [heading, *cells('value', 'label', 'text', rows=items[:1])]
    if kind in ('stats', 'timeline', 'cards'):
        return [heading, *cells('value', 'label', 'text')]
    if kind in ('agenda', 'process'):
        return [heading, *cells('label', 'text')]
    if kind == 'matrix':
        return [heading, *columns[:2], *cells('label', 'text')]
    if kind == 'chart':
        return [heading, *columns[:1], *cells('label', 'value')]
    if kind == 'comparison':
        return [heading, *columns[:2], *cells('label', 'text', 'value')]
    if kind == 'pros_cons':
        return [heading, *columns[:2], *(item.get('label') or item.get('text') or '' for item in items)]
    if kind == 'table':
        # A chart that fell back to two columns keeps its figure and its sentence in the second.
        fallen = section.get('layout') == 'chart' and len(columns) == 2
        keys = ('label', 'value', 'text') if fallen else ('label', 'text', 'value')[:len(columns)]
        return [heading, *columns[:3], *cells(*keys)]
    if slides._titled_columns(kind, section):
        return [heading, *cells('label', 'text')]
    return [heading, *_written(kind, section)]


def left_out(kind, section, shapes, marked=False, keeping=()):
    """How many of the words a slide's fields hold are not in `shapes`, what its drawer drew.

    `marked`: a drawer said it cut something, which is then at least one word
    even if the same word happens to stand elsewhere on the slide. Not the deck's
    own `shortened` for a body of more than six lines: a title page draws its eight.
    `keeping`: fields that must show as well, those of the layout it would leave.
    """
    return max(sum(_missing(kind, section, shapes, keeping).values()), 1 if marked else 0)


def _missing(kind, section, shapes, keeping=()):
    wanted = Counter(word for field in _shown_fields(kind, section) for word in _keys(field))
    wanted |= Counter(word for field in keeping for word in _keys(field))
    return wanted - Counter(word for shape in shapes for text in shape.iter(_TEXT) for word in _keys(text.text))


def _spread(shape, xfrm):
    """Where `shape` lies, as fractions of the slide (its `xfrm` as written), or None if it has no place of its own."""
    node = shape.find(xfrm)
    offset, extent = (None, None) if node is None else (node.find(qn('a:off')), node.find(qn('a:ext')))
    if offset is None or extent is None:
        return None
    width, height = int(slides.SLIDE_WIDTH), int(slides.SLIDE_HEIGHT)
    return {'x': round(int(offset.get('x')) / width, 4), 'y': round(int(offset.get('y')) / height, 4),
            'w': round(int(extent.get('cx')) / width, 4), 'h': round(int(extent.get('cy')) / height, 4)}


def _own_shapes(slide):
    """What was drawn on a slide but its brand name and number, which are the deck's whatever words they share with its fields."""
    def chrome(shape):
        name = shape.find(f"{qn('p:nvSpPr')}/{qn('p:cNvPr')}")
        return name is not None and name.get('name') in (slides.BRAND_BOX, slides.NUMBER_BOX)
    return [shape for shape in list(slide.shapes._spTree)[2:] if not chrome(shape)]


def slide_frames(kind, section, slide, pictured=False):
    """Where a drawn slide's heading, body and picture lie: [{field, x, y, w, h}], as fractions of the slide.

    Told as `left_out` tells what shows, from what came out and whichever drawer
    drew it: the box with the most of the heading's words and no others is the
    heading, one holding only the fields' words is body, and the rest (a drawing
    with no words) is nobody's to edit, as its number and a brand name never are.
    `pictured`: the slide has its picture, the largest on it (a logo is the only
    other). Holds no text.
    """
    fields = _shown_fields(kind, section)
    heading, body = set(_keys(fields[0])), {word for field in fields[1:] for word in _keys(field)}
    frames, pictures = [], []
    worded = [(shape, {word for text in shape.iter(_TEXT) for word in _keys(text.text)}) for shape in _own_shapes(slide)]
    title = max(((shape, words) for shape, words in worded if words and words <= heading), key=lambda box: len(box[1]), default=(None,))[0]
    for shape, words in worded:
        if shape.tag == qn('p:pic'):
            spread = _spread(shape, f"{qn('p:spPr')}/{qn('a:xfrm')}")
            if spread:
                pictures.append(spread)
            continue
        field = 'heading' if shape is title else 'body' if words and words <= body else None
        # A table sits in a frame of its own; every other shape in its properties.
        spread = field and (_spread(shape, f"{qn('p:spPr')}/{qn('a:xfrm')}") or _spread(shape, qn('p:xfrm')))
        if spread:
            frames.append({'field': field, **spread})
    if pictured and pictures:
        frames.append({'field': 'picture', **max(pictures, key=lambda spread: spread['w'] * spread['h'])})
    return frames


def letters_left_out(kind, section, slide):
    """How many letters of a drawn slide's words do not show, as the budget beside its fields counts them."""
    return sum(len(word) * count for word, count in _missing(kind, section, _own_shapes(slide)).items())


# ---------------------------------------------------------------- lines


def _spacing(properties, tag):
    node = properties.find(qn(tag)) if properties is not None else None
    node = node.find(qn('a:spcPts')) if node is not None else None
    return int(node.get('val')) / 100 if node is not None else 0


def _leading(properties, size):
    node = properties.find(qn('a:lnSpc')) if properties is not None else None
    if node is None:
        return size * 1.15
    exact = node.find(qn('a:spcPts'))
    if exact is not None:
        return int(exact.get('val')) / 100
    return size * int(node.find(qn('a:spcPct')).get('val')) / 100000


def _lines_in(width, height, paragraphs):
    """(lines taken, lines held) of one box in EMU: what its height has left, in lines like its last."""
    used, tall, leading = 0, 0, 0
    for paragraph in paragraphs:
        words = '\n'.join(text.text or '' for text in paragraph.iter(_TEXT))
        font = paragraph.find(f"{qn('a:r')}/{qn('a:rPr')}")
        if font is None or not words.strip():
            continue
        size = int(font.get('sz', 1800)) / 100
        properties = paragraph.find(qn('a:pPr'))
        inset = sum(int(properties.get(side, 0)) for side in ('marL', 'marR')) if properties is not None else 0
        latin = font.find(qn('a:latin'))
        face = None if latin is None else latin.get('typeface')
        count = _text_lines(words, size, width - inset, bold=font.get('b') == '1',
                            heading={slides.HEADING_FONT: True, slides.BODY_FONT: False}.get(face))
        leading = _leading(properties, size)
        used += count
        tall += count * leading + _spacing(properties, 'a:spcBef') + _spacing(properties, 'a:spcAft')
    return used, used + int(max(0, height / 12700 - tall) // leading) if leading else used


def _boxes(shapes):
    """(text body, width, height) of each box in `shapes` that holds text; a table's cells are boxes too."""
    for shape in shapes:
        body = shape.find(qn('p:txBody'))
        extent = shape.find(f"{qn('p:spPr')}/{qn('a:xfrm')}/{qn('a:ext')}")
        if body is not None and extent is not None:
            yield body, int(extent.get('cx')), int(extent.get('cy'))
        table = next(shape.iter(qn('a:tbl')), None) if body is None else None
        if table is None:
            continue
        widths = [int(column.get('w')) for column in table.find(qn('a:tblGrid'))]
        for row in table.findall(qn('a:tr')):
            for width, cell in zip(widths, row.findall(qn('a:tc'))):
                margins = cell.find(qn('a:tcPr'))
                margins = {} if margins is None else margins.attrib
                yield (cell.find(qn('a:txBody')),
                       width - int(margins.get('marL', 91440)) - int(margins.get('marR', 91440)),
                       int(row.get('h')) - int(margins.get('marT', 45720)) - int(margins.get('marB', 45720)))


def _budget(kind, section, shapes, words_over):
    """(lines used, lines held) by a slide's text at the sizes it is set in: '4 of 6 lines'.

    Its body's boxes, or its heading's on a slide with nothing else. A number on
    the slide that no field holds (its place in the deck) is no line of its
    text. Words that do not show would take lines of their own, so a slide that
    loses any is always over.
    """
    fields = _shown_fields(kind, section)
    heading, body = set(_keys(fields[0])), {word for field in fields[1:] for word in _keys(field)}
    title, used, held, count = None, 0, 0, 0
    for text, width, height in _boxes(shapes):
        words = {word for piece in text.iter(_TEXT) for word in _keys(piece.text)}
        if words and title is None and words <= heading:
            title = _lines_in(width, height, text.findall(qn('a:p')))
        elif words and words <= body:
            lines = _lines_in(width, height, text.findall(qn('a:p')))
            used, held, count = used + lines[0], held + lines[1], count + len(words)
    if not held and title:
        used, held = title
    if words_over:
        used = max(used + math.ceil(words_over / max(1, count // max(1, used))), held + 1)
    return used, held


# ---------------------------------------------------------------- measuring


class _Sheet(variants.Scratch):
    """One slide emptied before each use: a new one for each try takes as long as drawing on it."""

    def __init__(self, width, height):
        super().__init__(width, height)
        self._only = None

    def slide(self):
        self._only = self._only or super().slide()
        for shape in self.drawn():
            shape.getparent().remove(shape)
        return self._only

    def drawn(self):
        return list(self._only.shapes._spTree)[2:]  # past the tree's own two properties


def measure_deck(content, locale='en', style=None, pins=None, photos=(), only=None, seconds=None):
    """Each slide of a deck as `render_pptx` would draw it, in order, question slides last.

    A slide is {id, index, fits, words_over, lines_used, lines_max,
    layouts_fitting}. `photos`: the sections that have a picture (its bytes play
    no part). `only`: the section ids to measure, and each of those also says
    which layouts would hold it whole, which takes a drawing per layout;
    `layouts_fitting` is otherwise left empty.

    With `only`, the slides of the same layout before it choose their variants
    first, as they do when the deck is drawn, so it is measured on the variant it
    would get. Another layout's are spoken for by the pins alone in
    `layouts_fitting`, which the slide is measured again on once it takes one.

    A slide that holds its pin costs one drawing, and any other one for each
    variant tried: 60 with no pin that hold on few variants or none take 8 s.
    With `seconds`, once that has passed the rest are not measured: the caller
    has them measured when the deck is drawn. With `only` it is those slides
    before that are cut short, and the slides asked about are still measured but
    say no layouts: a list that far along would be only part of the answer.
    """
    pins = pins or {}
    style, look, roles = slides.deck_look(style, pins)
    with slides.measured_in(look):
        return _measure_deck(content, locale, style, look, roles, pins, photos, only, seconds)


def _measure_deck(content, locale, style, look, roles, pins, photos, only, seconds):
    from .compositions import Canvas, compose
    pinned = pins.get('variants') or {}
    prepared, _ = slides.prepare_slides(content, locale, photos)
    total, sheet = len(prepared), _Sheet(slides.SLIDE_WIDTH, slides.SLIDE_HEIGHT)
    size = slides._deck_size(prepared, pins.get('body_size'))
    deck_seed = pins.get('deck_seed') or variants.seed(look, content)
    arrangement = compose(look.get('composition', 'classic'))

    def chooser(taken):
        return slides.variant_chooser(look, roles, style, size, locale, total, deck_seed, pinned, sheet, taken)

    def drawn(kind, section, lines, index, variant_for, keeping=()):
        """(words left out, lines used, lines held), as drawn on the sheet by this slide's variant."""
        photo = section.get('id') in photos and kind in PHOTO_ZONES
        chosen = variant_for(kind, section, lines, index, photo)
        # What a variant other than classic draws is on the sheet already, from the trial it passed.
        if chosen is None or chosen.name == variants.CLASSIC or section.get('_variant'):
            slide = sheet.slide()
            framed = kind in ('cover', 'closing', 'section')
            plan = arrangement.ground(Canvas(slide, roles, look, kind), kind, photo) if framed else None
            start = len(slide.shapes._spTree)
            context = Ctx(slide, roles, style, index, total, size, locale, photo, plan, look['heading_bold'])
            (chosen.draw if chosen is not None else DRAW[kind])(context, section, lines)
            shapes, marked = slide.shapes._spTree[start:], context.shortened
        else:
            shapes, marked = sheet.drawn(), False
        words = left_out(kind, section, shapes, marked, keeping)
        return (words, *_budget(kind, section, shapes, words))

    def late():
        return seconds is not None and time.monotonic() - started > seconds

    def fitting(kind, section, lines, index, taken):
        """The layouts that can carry this slide and show all it shows now; a closing slide only at the deck's end.

        A divider has no place for a slide's cards, which is not to hold them: they would go unseen.
        """
        fields = _shown_fields(kind, section)
        found = []
        for layout in layouts.LAYOUT_IDS:
            if late():
                return []
            candidate = {**section, 'layout': layout}
            if (layouts.resolve(candidate, lines, index, total, section.get('id') in photos) == layout
                    and (layout != 'closing' or index == len(content['sections']) - 1)
                    and not drawn(layout, candidate, lines, index, chooser(copy.deepcopy(taken)), fields)[0]):
                found.append(layout)
        return found

    taken = variants.taken_by(pinned.values())
    variant_for = chooser(taken)
    asked = [index for index, row in enumerate(prepared) if only is not None and row[2].get('id') in only]
    kinds = {prepared[index][0] for index in asked}
    measured = []
    started = time.monotonic()
    for index, (kind, lines, section) in enumerate(prepared if only is None else prepared[:max(asked, default=-1) + 1]):
        if only is None and late():
            break
        if only is not None and section.get('id') not in only:
            if kind in kinds and not late():
                variant_for(kind, section, lines, index, section.get('id') in photos and kind in PHOTO_ZONES)
            continue
        before = copy.deepcopy(taken) if only is not None else None
        words, used, held = drawn(kind, section, lines, index, variant_for)
        other_layouts = fitting(kind, section, lines, index, before) if only is not None and kind != 'questions' else []
        measured.append({'id': section.get('id'), 'index': index, 'fits': not words, 'words_over': words,
                         'lines_used': used, 'lines_max': held, 'layouts_fitting': other_layouts})
    return measured
