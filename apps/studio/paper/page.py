"""One build of a paper: the A4 sheet, its frame, its page furniture and its metadata.

The frame is the template's `page.margins_mm`, the same on every page; page 1
and the later pages differ only in what is printed outside it
(`page_furniture`, blocks.json):

- `first`: none | number (the number under the frame);
- `later`: none | number_top (the number alone over the frame, as an official
  paper's second page carries it) | number_bottom | header_number (a running
  header of the template's `header` facts, cut at a word, with a hairline
  under it, and the number under the frame);
- `format`: n | n_of_N ("2 / 3", for which the engine builds once more with the
  page count it found).

A paper that turns out one page long carries no number at all (the engine
builds it once more with `total=1` when its first page is numbered).

The build is the CV's pattern (cv/layouts.py Sheet.build): a BaseDocTemplate
with `invariant=1`, so the same content always gives the same bytes, and an
`afterFlowable` hook that notes how low text reached on each page (the last
page's fill), the page every contents anchor landed on, and the placement
being laid out, so one that breaks the layout can be drawn plain instead.
"""
import io
from dataclasses import dataclass, field as attribute

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import BaseDocTemplate, Flowable, Frame, NextPageTemplate, PageTemplate

from apps.core.brand import PRODUCT_NAME

from .ctx import Anchor, INK
from .text import MM

W, H = A4
FURNITURE_SIZE = 9


def geometry(template):
    """(left, bottom, width, height) of the frame in points, from the template's margins."""
    margins = template['page']['margins_mm']
    left, right, top, bottom = (margins[key] * MM for key in ('left', 'right', 'top', 'bottom'))
    return left, bottom, W - left - right, H - top - bottom


def box(x0, y0, x1, y1):
    """A ReportLab rectangle as pdfplumber reads it: (x0, top, x1, bottom)."""
    return (round(x0, 2), round(H - y1, 2), round(x1, 2), round(H - y0, 2))


class Mark(Flowable):
    """Where a placement's flowables begin in the story: the engine knows which one is being laid out."""

    _ZEROSIZE = 1

    def __init__(self, indexes):
        super().__init__()
        self.indexes = tuple(indexes)

    def wrap(self, width, height):
        return 0, 0

    def draw(self):
        pass


@dataclass
class Built:
    """What one build made: the PDF, its page count, its last page's fill, where its anchors landed."""

    data: bytes = b''
    pages: int = 0
    fill: float = 1.0
    anchors: dict = attribute(default_factory=dict)
    at: tuple = ()
    # The placements (failed, dropped) it was built with: see paper._Paper.build.
    state: tuple = (frozenset(), frozenset())


def _cut(text, font, size, room):
    """A running header cut at a word to fit `room` points; a single word too long for it is cut at a letter."""
    text = ' '.join(text.split())
    if stringWidth(text, font, size) <= room:
        return text
    words = text.split(' ')
    while len(words) > 1 and stringWidth(' '.join(words) + '…', font, size) > room:
        words.pop()
    text = ' '.join(words).rstrip(',;:·–—')
    while len(text) > 1 and stringWidth(text + '…', font, size) > room:
        text = text[:-1]
    return text + '…'


def header_text(ctx):
    """The running header: the template's header facts joined, else the paper's title."""
    names = ctx.template['furniture'].get('header') or ()
    values = [ctx.fact(name) for name in names]
    text = ' · '.join(value for value in values if value)
    return ctx.plain(text or ctx.content.get('title') or '')


def furniture(ctx, total=None):
    """The onPage hook that prints the page furniture outside the frame."""
    spec = ctx.template['furniture']
    left, bottom, width, height = geometry(ctx.template)
    top = H - bottom - height
    font = ctx.face
    size = min(FURNITURE_SIZE, ctx.styles['small'].fontSize)
    header = header_text(ctx) if spec.get('later') == 'header_number' else ''

    def number(page):
        return f'{page} / {total}' if spec.get('format') == 'n_of_N' and total else str(page)

    def draw(canvas, document):
        page = document.page
        kind = spec.get('first', 'none') if page == 1 else spec.get('later', 'none')
        if kind == 'none' or total == 1:
            return
        canvas.saveState()
        canvas.setFillColor(INK)
        canvas.setFont(font, size)
        centre = left + width / 2
        if kind == 'number_top':
            canvas.drawCentredString(centre, H - min(12 * MM, top * 0.6), number(page))
        else:
            canvas.drawCentredString(centre, max(6 * MM, bottom * 0.45), number(page))
        if kind == 'header_number' and header:
            line = H - top * 0.55
            canvas.drawString(left, line, _cut(header, font, size, width))
            canvas.setStrokeColor(INK)
            canvas.setLineWidth(0.4)
            canvas.line(left, line - size * 0.45, left + width, line - size * 0.45)
        canvas.restoreState()
    return draw


def furniture_boxes(template):
    """Where page furniture may print, per page kind, as pdfplumber boxes: everything outside the frame's band."""
    left, bottom, width, height = geometry(template)
    top = H - bottom - height
    spec = template['furniture']
    found = {}
    for kind_key in ('first', 'later'):
        kind = spec.get(kind_key, 'none')
        boxes = []
        if kind in ('number', 'number_bottom', 'header_number'):
            boxes.append(box(left, 0, left + width, bottom))
        if kind in ('number_top', 'header_number'):
            boxes.append(box(left, H - top, left + width, H))
        found[kind_key] = boxes
    return found


def build(ctx, story, *, total=None, made=None):
    """Lay `story` out on the template's pages; a Built. Raises whatever ReportLab raises.

    `made`, when given, is the Built filled in: after a raise its `at` names the
    placements being laid out when the layout broke.
    """
    left, bottom, width, height = geometry(ctx.template)
    buffer = io.BytesIO()
    title = ctx.plain(ctx.content.get('title') or '')
    name = ctx.template.get('name') or {}
    document = BaseDocTemplate(buffer, pagesize=A4, leftMargin=left, rightMargin=W - left - width, topMargin=H - bottom
                               - height, bottomMargin=bottom, title=title, author=PRODUCT_NAME, creator=PRODUCT_NAME,
                               subject=name.get(ctx.locale) or name.get('en', ''), lang=ctx.locale, invariant=1,
                               initialFontName=ctx.face)
    hook = furniture(ctx, total)
    document.addPageTemplates([
        PageTemplate('first', [Frame(left, bottom, width, height, 0, 0, 0, 0, id='main')], onPage=hook),
        PageTemplate('later', [Frame(left, bottom, width, height, 0, 0, 0, 0, id='main')], onPage=hook)])
    made = made if made is not None else Built()
    lowest = {}

    def reached(flowable):
        page = document.page
        if isinstance(flowable, Mark):
            made.at = flowable.indexes
        elif isinstance(flowable, Anchor):
            made.anchors.setdefault(flowable.key, page)
        frame = getattr(document, 'frame', None)
        if frame is not None and not getattr(flowable, '_ZEROSIZE', 0):
            lowest[page] = min(lowest.get(page, H), frame._y)
    document.afterFlowable = reached
    document.build([NextPageTemplate('later'), *story])
    made.data = buffer.getvalue()
    # The page the build ended on is the page count: no need to read the PDF back.
    made.pages = document.page
    if made.pages in lowest:
        made.fill = round(max(0.0, (bottom + height - lowest[made.pages]) / height), 3)
    else:
        made.fill = 0.0
    return made
