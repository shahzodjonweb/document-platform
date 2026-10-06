"""Deterministic Unicode document renderer. Content is always text, never HTML code."""
from pathlib import Path
import io
import re
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT,TA_CENTER,TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,PageBreak,KeepTogether,Table,TableStyle,Flowable,Image as FlowImage
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[2]
FONT=ROOT/'processors'/'assets'/'fonts'/'NotoSans-Regular.ttf'

def font_path():
    for p in [FONT,Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),Path('/System/Library/Fonts/Supplemental/Arial.ttf'),ROOT/'operations/static/ops/fonts/dm-sans-variable.ttf']:
        if p.exists():return p
    raise RuntimeError('Unicode font missing')

# A document is one flowing text, held to the page count it was quoted at.
#
# Sections are written a page of text each, but they are not pages: they run on
# from one another, a heading appears only where a new topic starts, and a topic
# with plenty to say runs under one heading for two or three pages. What keeps
# the count honest is the fit at the end — the whole document is set a little
# tighter if it runs over, and only if the tightest readable setting cannot hold
# it are sentences taken from the ends of sections.
#
# Paragraphs are separated by their own spacing and nothing else. Blank lines in
# the text used to become empty paragraphs of their own, which put a line and a
# half of air between every paragraph and left documents looking unfinished.

# Floors, not preferences: below these the document stops being comfortable to
# read, and a shorter section is better than an unreadable one.
MIN_BODY_SIZE = 9.0
MIN_BODY_LEADING = 12.5
FIT_STEPS = 6
SENTENCE = re.compile(r'((?<=[.!?…])\s+)')
BULLET = re.compile(r'^\s*(?:[•·▪◦‣*\-–—]\s+)')
INK = '#1A1A1A'
MUTED = '#5F6368'


def _units(body):
    """The body in the largest pieces it can be cut at, separators kept.

    Sentences where there are any — the separators travel with them so paragraph
    breaks survive the cut — and words where there are none.
    """
    parts = SENTENCE.split(body)
    units = [parts[i] + (parts[i + 1] if i + 1 < len(parts) else '')
             for i in range(0, len(parts), 2)]
    units = [unit for unit in units if unit.strip()]
    if len(units) > 1:
        return units
    words = body.split(' ')
    return [word + ' ' for word in words[:-1]] + words[-1:] if len(words) > 1 else [body]


def _short(text, limit):
    """A running title cut at a word, not through one."""
    text = ' '.join(str(text or '').split())
    return text if len(text) <= limit else text[:limit].rsplit(' ', 1)[0].rstrip(',;:') + '…'


def _tint(hexcolour, amount):
    """The colour mixed toward white: 0 is the colour, 1 is white."""
    value = hexcolour.lstrip('#')
    red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    mix = lambda channel: round(channel + (255 - channel) * amount)
    return '#%02X%02X%02X' % (mix(red), mix(green), mix(blue))


class Decorated(Flowable):
    """A heading with its design's device: a side bar, a tinted band or a rule."""

    def __init__(self, paragraph, kind, colour):
        super().__init__()
        self.paragraph, self.kind, self.colour = paragraph, kind, colour
        self.inset = {'bar': 12, 'band': 10}.get(kind, 0)
        self.pad = 6 if kind == 'band' else 0
        self.keepWithNext = True
        self.spaceBefore, self.spaceAfter = paragraph.style.spaceBefore, paragraph.style.spaceAfter

    def wrap(self, width, height):
        self.width = width
        _, self.text_height = self.paragraph.wrap(width - self.inset - (self.pad and 10), height)
        extra = 2 * self.pad + (6 if self.kind == 'ruled' else 0)
        return width, self.text_height + extra

    def draw(self):
        canvas = self.canv
        if self.kind == 'bar':
            canvas.setFillColor(colors.HexColor(self.colour))
            canvas.rect(0, 1, 3.5, self.text_height - 2, stroke=0, fill=1)
        elif self.kind == 'band':
            canvas.setFillColor(colors.HexColor(_tint(self.colour, 0.9)))
            canvas.roundRect(0, 0, self.width, self.text_height + 2 * self.pad, 4, stroke=0, fill=1)
        elif self.kind == 'ruled':
            canvas.setStrokeColor(colors.HexColor(_tint(self.colour, 0.6)))
            canvas.setLineWidth(0.8)
            canvas.line(0, 0.5, self.width, 0.5)
        self.paragraph.drawOn(canvas, self.inset, self.pad + (6 if self.kind == 'ruled' else 0))


def _markup(text):
    return escape(text or '')


def _paragraphs(body, styles):
    """The body's lines as paragraphs; blank lines are spacing already, not paragraphs."""
    flowables = []
    for line in (body or '').split('\n'):
        if not line.strip():
            continue
        if BULLET.match(line):
            flowables.append(Paragraph(_markup(BULLET.sub('', line)), styles['bullet'], bulletText='•'))
        else:
            flowables.append(Paragraph(_markup(line.strip()), styles['body']))
    return flowables


def _photo(photo, width, height_cap=250):
    from PIL import Image
    with Image.open(io.BytesIO(photo['jpeg'])) as picture:
        scale = min(width / picture.width, height_cap / picture.height)
        size = (picture.width * scale, picture.height * scale)
    image = FlowImage(io.BytesIO(photo['jpeg']), width=size[0], height=size[1])
    image.hAlign = 'LEFT'
    return image


def _table(section, styles, look, width):
    columns = section.get('columns') or []
    items = section.get('items') or []
    count = 3 if (len(columns) >= 3 or any(item.get('value') for item in items)) else 2
    share = {2: (0.36, 0.64), 3: (0.3, 0.45, 0.25)}[count]
    cell = styles['cell']
    rows = []
    if columns:
        rows.append([Paragraph(_markup(name), styles['cell_head']) for name in (columns + [''] * 3)[:count]])
    for item in items:
        values = (item.get('label', ''), item.get('text', ''), item.get('value', ''))[:count]
        rows.append([Paragraph(_markup(value), cell) for value in values])
    if not rows:
        return None
    plain = look['style'] == 'plain'
    head_fill = '#EFEFEF' if plain else _tint(look['accent'], 0.86)
    commands = [('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CFCFCF')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6)]
    if columns:
        commands.append(('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(head_fill)))
    first = 1 if columns else 0
    for row in range(first + 1, len(rows), 2):
        commands.append(('BACKGROUND', (0, row), (-1, row), colors.HexColor('#FAFAFA')))
    table = Table(rows, colWidths=[width * part for part in share], repeatRows=1 if columns else 0)
    table.setStyle(TableStyle(commands))
    table.hAlign = 'LEFT'
    return table


def _labelled(item, look):
    label, text = _markup(item.get('label', '')), _markup(item.get('text', ''))
    if label and text:
        return f'<font color="{look["accent"]}">{label}</font> — {text}'
    return label or text


def _list(section, styles, look):
    return [Paragraph(_labelled(item, look), styles['bullet'], bulletText='•')
            for item in section.get('items') or [] if item.get('label') or item.get('text')]


def _callout(section, styles, look, width):
    lines = [Paragraph(_labelled(item, look), styles['callout'], bulletText='•')
             for item in section.get('items') or [] if item.get('label') or item.get('text')]
    if not lines:
        return None
    plain = look['style'] == 'plain'
    box = Table([[lines]], colWidths=[width])
    box.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F3F3F3' if plain else _tint(look['accent'], 0.92))),
        ('LINEBEFORE', (0, 0), (0, -1), 3, colors.HexColor('#444444' if plain else look['accent'])),
        ('TOPPADDING', (0, 0), (-1, -1), 9), ('BOTTOMPADDING', (0, 0), (-1, -1), 9),
        ('LEFTPADDING', (0, 0), (-1, -1), 12), ('RIGHTPADDING', (0, 0), (-1, -1), 12)]))
    box.hAlign = 'LEFT'
    return box


def _heading(text, number, styles, look):
    kind = look['style']
    label = f'{number}. {text}' if kind == 'numbered' else text
    paragraph = Paragraph(_markup(label), styles['heading'])
    if kind in ('bar', 'band', 'ruled'):
        return Decorated(paragraph, kind, look['accent'])
    paragraph.keepWithNext = True
    return paragraph


def document_story(sections, styles, look, width, photos=None):
    """The flowing text of a document: headings where topics start, then everything in between."""
    story, number = [], 0
    photos = photos or {}
    for section in sections:
        heading = (section.get('heading') or '').strip()
        if heading:
            number += 1
            story.append(_heading(heading, number, styles, look))
        layout = section.get('layout') or 'text'
        photo = photos.get(section.get('id')) if layout == 'image' else None
        if photo is not None:
            try:
                story.extend([Spacer(1, 2), _photo(photo, width), Spacer(1, 8)])
            except Exception:
                pass
        story.extend(_paragraphs(section.get('body', ''), styles))
        extra = None
        if layout == 'table':
            extra = _table(section, styles, look, width)
        elif layout == 'callout':
            extra = _callout(section, styles, look, width)
        elif layout == 'list':
            story.extend(_list(section, styles, look))
        if extra is not None:
            story.extend([Spacer(1, 4), extra, Spacer(1, 10)])
    return story


def _trimmed(sections, ratio):
    """Every section's body cut to the same share of its sentences, marked where cut."""
    import math
    result = []
    for section in sections:
        units = _units(section.get('body') or '')
        keep = max(1, math.ceil(len(units) * ratio))
        body = section.get('body') or ''
        if keep < len(units):
            body = ''.join(units[:keep]).rstrip() + '…'
        result.append({**section, 'body': body})
    return result


def fit_document(sections, target, styles, body_size, body_leading, count_pages):
    """Hold the document to `target` pages: tighter type first, fewer sentences last.

    `count_pages(sections)` builds the document and returns its page count.
    Returns the sections to render and whether any were shortened; the body
    style is left at the size the document settled on.
    """
    for step in range(FIT_STEPS + 1):
        share = step / FIT_STEPS
        styles['body'].fontSize = styles['bullet'].fontSize = body_size - (body_size - MIN_BODY_SIZE) * share
        styles['body'].leading = styles['bullet'].leading = body_leading - (body_leading - MIN_BODY_LEADING) * share
        if count_pages(sections) <= target:
            return sections, False
    low, high = 0.25, 1.0
    for _ in range(7):
        middle = (low + high) / 2
        if count_pages(_trimmed(sections, middle)) <= target:
            low = middle
        else:
            high = middle
    return _trimmed(sections, low), True


def render_pdf(content,path,locale='en',role='user_document',style=None,photos=None):
    from .doc_designs import look as design_look
    style=style or {};look=design_look(style);accent=look['accent']
    layout=style.get('layout','clean');margin=style.get('margin',48)
    body_size=style.get('body_size',10.5);body_leading=style.get('body_leading',17)
    if 'PDFMaster' not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont('PDFMaster',str(font_path())))
    kind=look['style']
    title_colour=accent
    styles={
      'title':ParagraphStyle('title',fontName='PDFMaster',fontSize=30 if layout=='executive' else 21 if layout=='compact' else 25,leading=35 if layout=='executive' else 29,textColor=colors.HexColor(title_colour),spaceAfter=18 if kind in ('ruled','numbered') else 22,alignment=TA_CENTER if kind in ('ruled','numbered') else TA_LEFT),
      'heading':ParagraphStyle('heading',fontName='PDFMaster',fontSize=15,leading=21,textColor=colors.HexColor(accent),spaceBefore=14,spaceAfter=8),
      'body':ParagraphStyle('body',fontName='PDFMaster',fontSize=body_size,leading=body_leading,spaceAfter=7,textColor=colors.HexColor(INK),wordWrap='LTR',alignment=TA_JUSTIFY if kind=='numbered' else TA_LEFT),
      'bullet':ParagraphStyle('bullet',fontName='PDFMaster',fontSize=body_size,leading=body_leading,spaceAfter=4,leftIndent=14,bulletIndent=2,textColor=colors.HexColor(INK)),
      'callout':ParagraphStyle('callout',fontName='PDFMaster',fontSize=body_size,leading=body_leading,spaceAfter=3,leftIndent=12,bulletIndent=0,textColor=colors.HexColor(INK)),
      'cell':ParagraphStyle('cell',fontName='PDFMaster',fontSize=max(8.5,body_size-1),leading=max(11,body_leading-4),textColor=colors.HexColor(INK)),
      'cell_head':ParagraphStyle('cell_head',fontName='PDFMaster',fontSize=max(8.5,body_size-1),leading=max(11,body_leading-4),textColor=colors.HexColor(INK if kind=='plain' else accent)),
      'small':ParagraphStyle('small',fontName='PDFMaster',fontSize=8,leading=12,textColor=colors.HexColor(MUTED),spaceAfter=9)}
    labels={'en':('Questions','Teacher answer key','Review before use'), 'uz':('Savollar','O‘qituvchi javoblari','Ishlatishdan oldin tekshiring'), 'ru':('Вопросы','Ответы для учителя','Проверьте перед использованием')}[locale]
    details={'en':{'key':'Answer key','card':'Card','question':'Question','answer':'Answer','marks':'points','source':'Source','page':'p.'},'uz':{'key':'Javoblar','card':'Kartochka','question':'Savol','answer':'Javob','marks':'ball','source':'Manba','page':'b.'},'ru':{'key':'Ответы','card':'Карточка','question':'Вопрос','answer':'Ответ','marks':'баллы','source':'Источник','page':'стр.'}}[locale]
    content_layout=style.get('content_layout','answer_key' if role=='teacher_key' else 'document')
    top_margin=50 if layout=='executive' else 38 if layout=='compact' else 45
    frame_width=A4[0]-2*margin-12
    shortened=False

    def opening():
        story=[]
        logo=(style or {}).get('logo_png')
        if logo:
            from PIL import Image
            with Image.open(io.BytesIO(logo)) as picture:
                scale=min(110/picture.width,40/picture.height)
                mark=FlowImage(io.BytesIO(logo),width=picture.width*scale,height=picture.height*scale);mark.hAlign='LEFT';story.extend([mark,Spacer(1,10)])
        brand=(style or {}).get('brand_name','')
        if brand:story.append(Paragraph(escape(brand),styles['small']))
        def rule(width,height,colour,align):
            line=Table([['']],colWidths=[width],rowHeights=[height])
            line.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor(colour))]));line.hAlign=align
            return line
        if kind=='ruled':story.extend([rule(frame_width,0.8,_tint(accent,0.5),'CENTER'),Spacer(1,12)])
        story.append(Paragraph(escape(content['title']),styles['title']))
        if kind in ('ruled','numbered'):story.extend([rule(frame_width,0.8,_tint(accent,0.5),'CENTER'),Spacer(1,14)])
        elif kind=='bar':story.extend([rule(56,2.5,accent,'LEFT'),Spacer(1,14)])
        return story

    def footer(canvas,doc):
        canvas.setFont('PDFMaster',8);canvas.setFillColor(colors.HexColor('#68756b'))
        canvas.drawString(margin,26,_short(content['title'],70));canvas.drawRightString(A4[0]-margin,26,str(doc.page))
        if layout=='executive':
            canvas.setStrokeColor(colors.HexColor(accent));canvas.setLineWidth(3);canvas.line(margin,A4[1]-24,A4[0]-margin,A4[1]-24)
        elif layout=='notes':
            canvas.setStrokeColor(colors.HexColor('#ddd6e8'));canvas.setLineWidth(.5);canvas.line(margin-13,45,margin-13,A4[1]-35)

    def build(story,target):
        SimpleDocTemplate(target,pagesize=A4,rightMargin=margin,leftMargin=margin,topMargin=top_margin,bottomMargin=48,title=content['title'],author='PDF Master').build(story,onFirstPage=footer,onLaterPages=footer)

    sections=[dict(s) for s in content['sections']]
    if content_layout=='document' and sections:
        def count_pages(candidate):
            buffer=io.BytesIO();build(opening()+document_story(candidate,styles,look,frame_width,photos),buffer)
            return len(PdfReader(io.BytesIO(buffer.getvalue())).pages)
        sections,shortened=fit_document(sections,len(sections),styles,body_size,body_leading,count_pages)
    story=opening()
    if content_layout=='answer_key':
        story.append(Paragraph(labels[1] if role=='teacher_key' else details['key'],styles['heading']))
        for q in content.get('questions',[]):
            heading=q['stem']+f" ({q['marks']} {details['marks']})"
            story.extend([Paragraph(escape(heading),styles['heading']),Paragraph(escape(q['answer']),styles['body']),Paragraph(escape(q['explanation']),styles['small'])])
    elif content_layout=='flashcards':
        for index,q in enumerate(content.get('questions',[]),1):
            card=[Paragraph(escape(f"{details['card']} {index}"),styles['heading']),Paragraph(escape(details['question']),styles['small']),Paragraph(escape(q['stem']),styles['body']),Paragraph(escape(details['answer']),styles['small']),Paragraph(escape(q['answer']),styles['body']),Paragraph(escape(q['explanation']),styles['small']),Spacer(1,14)]
            story.append(KeepTogether(card))
    else:
        story.extend(document_story(sections,styles,look,frame_width,photos))
        if content.get('questions'):story.append(Paragraph(labels[0],styles['heading']))
        for i,q in enumerate(content.get('questions',[])):
            story.append(Paragraph(escape(f"{i+1}. {q['stem']} ({q['marks']})"),styles['body']))
            for option in q.get('options',[]):story.append(Paragraph(escape('• '+option),styles['body']))
            story.append(Spacer(1,12))
    for ref in content.get('citations',[]):
        if isinstance(ref,dict) and 'page' in ref:story.append(Paragraph(escape(f"{details['source']} {str(ref.get('asset_id',''))[:8]} · {details['page']} {ref['page']}"),styles['small']))
    build(story,str(path))
    return {'path':str(path),'name':path.name,'mime_type':'application/pdf','page_count':len(PdfReader(path).pages),'role':role,'shortened':shortened,
            'metadata':{'design':look['id'],'layouts':[s.get('layout') or 'text' for s in sections]}}
