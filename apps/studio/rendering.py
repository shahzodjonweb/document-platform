"""Deterministic Unicode document renderer. Content is always text, never HTML code."""
from pathlib import Path
import io
import re
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,PageBreak,KeepTogether,Image as FlowImage
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[2]
FONT=ROOT/'processors'/'assets'/'fonts'/'NotoSans-Regular.ttf'

def font_path():
    for p in [FONT,Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),Path('/System/Library/Fonts/Supplemental/Arial.ttf'),ROOT/'operations/static/ops/fonts/dm-sans-variable.ttf']:
        if p.exists():return p
    raise RuntimeError('Unicode font missing')

# How a section is made to keep to its own page.
#
# The page count is what the customer asked for and what they were charged for,
# so it cannot depend on the model's sense of how much prose fills a page — and
# a model cannot count characters, so asking it nicely is not enough. A model
# writing twice the target turned a five-page document into ten pages, one
# section spilling onto a second page each time.
#
# So the fit is measured and enforced here: set the whole document a little
# tighter if that is all it takes, and only shorten a section when even the
# tightest readable setting cannot hold it. Tightening is uniform across the
# document so pages do not visibly change size partway through.

# reportlab's frame keeps 6pt of padding on every side, so the space a story
# actually has is smaller than the margins suggest. Measuring without this
# understates every section and the fit silently fails.
FRAME_PADDING = 6
# Floors, not preferences: below these the document stops being comfortable to
# read, and a shorter section is better than an unreadable one.
MIN_BODY_SIZE = 9.0
MIN_BODY_LEADING = 12.5
FIT_STEPS = 6
SENTENCE = re.compile(r'((?<=[.!?…])\s+)')


def _units(body):
    """The body in the largest pieces it can be cut at, separators kept.

    Sentences where there are any — the separators travel with them so paragraph
    breaks survive the cut — and words where there are none, so a wall of text
    can still be held to its page.
    """
    parts = SENTENCE.split(body)
    units = [parts[i] + (parts[i + 1] if i + 1 < len(parts) else '')
             for i in range(0, len(parts), 2)]
    units = [unit for unit in units if unit.strip()]
    if len(units) > 1:
        return units
    words = body.split(' ')
    return [word + ' ' for word in words[:-1]] + words[-1:] if len(words) > 1 else [body]


def _block_height(text, style, width):
    total = 0
    for line in (text or ' ').split('\n'):
        total += Paragraph(escape(line) or '&#160;', style).wrap(width, 100000)[1] + style.spaceAfter
    return total


def section_height(section, styles, width):
    """How tall this section renders, heading included."""
    total = 0
    if section['heading'].strip():
        heading = styles['heading']
        total += (Paragraph(escape(section['heading']), heading).wrap(width, 100000)[1]
                  + heading.spaceBefore + heading.spaceAfter)
    return total + _block_height(section['body'], styles['body'], width)


def shorten_to_fit(section, styles, width, height):
    """The longest whole-sentence prefix of the body that still fits one page."""
    units = _units(section['body'])
    if len(units) < 2:
        return section['body'], False

    def prefix(count):
        return ''.join(units[:count]).rstrip() + '…'

    low, high = 1, len(units)
    while low < high:
        middle = (low + high + 1) // 2
        if section_height({**section, 'body': prefix(middle)}, styles, width) <= height:
            low = middle
        else:
            high = middle - 1
    if low >= len(units):
        return section['body'], False
    return prefix(low), True


def usable_height(styles, height):
    """The frame height a summed measurement can be compared against.

    Summing flowable heights is not how reportlab lays a page out: the heading's
    `spaceBefore` is dropped at the top of a frame and the last paragraph's
    `spaceAfter` never has to fit, so a naive sum reads a page as roughly 30pt
    roomier than it is — enough to put one section of a five-page document onto
    a second page. Those two are given back, plus one line of cushion, which
    also keeps the fit on the safe side of a measurement that is close.
    """
    return (height - 2 * FRAME_PADDING
            - styles['heading'].spaceBefore - styles['body'].spaceAfter - styles['body'].leading)


def fit_to_pages(sections, styles, width, height, body_size, body_leading):
    """Hold every section to one page, tightening first and shortening last.

    Returns the sections to render and whether any had to be shortened; the body
    style is left at whatever size the document settled on.
    """
    width -= 2 * FRAME_PADDING
    for step in range(FIT_STEPS + 1):
        share = step / FIT_STEPS
        styles['body'].fontSize = body_size - (body_size - MIN_BODY_SIZE) * share
        styles['body'].leading = body_leading - (body_leading - MIN_BODY_LEADING) * share
        room = usable_height(styles, height)
        if all(section_height(section, styles, width) <= room for section in sections):
            return sections, False
    room = usable_height(styles, height)
    shortened = False
    result = []
    for section in sections:
        body, cut = shorten_to_fit(section, styles, width, room)
        shortened = shortened or cut
        result.append({**section, 'body': body})
    return result, shortened


def render_pdf(content,path,locale='en',role='user_document',style=None):
    style=style or {};accent=style.get('accent','#255e49')
    layout=style.get('layout','clean');margin=style.get('margin',48)
    body_size=style.get('body_size',10.5);body_leading=style.get('body_leading',17)
    if 'PDFMaster' not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont('PDFMaster',str(font_path())))
    styles={
      'title':ParagraphStyle('title',fontName='PDFMaster',fontSize=30 if layout=='executive' else 21 if layout=='compact' else 25,leading=35 if layout=='executive' else 29,textColor=colors.HexColor(accent),spaceAfter=22),
      'heading':ParagraphStyle('heading',fontName='PDFMaster',fontSize=15,leading=22,textColor=colors.HexColor(accent),spaceBefore=15,spaceAfter=10),
      'body':ParagraphStyle('body',fontName='PDFMaster',fontSize=body_size,leading=body_leading,spaceAfter=12,wordWrap='LTR'),
      'small':ParagraphStyle('small',fontName='PDFMaster',fontSize=8,leading=12,textColor=colors.HexColor('#59695f'),spaceAfter=9)}
    labels={'en':('Questions','Teacher answer key','Review before use'), 'uz':('Savollar','O‘qituvchi javoblari','Ishlatishdan oldin tekshiring'), 'ru':('Вопросы','Ответы для учителя','Проверьте перед использованием')}[locale]
    details={'en':{'key':'Answer key','card':'Card','question':'Question','answer':'Answer','marks':'points','source':'Source','page':'p.'},'uz':{'key':'Javoblar','card':'Kartochka','question':'Savol','answer':'Javob','marks':'ball','source':'Manba','page':'b.'},'ru':{'key':'Ответы','card':'Карточка','question':'Вопрос','answer':'Ответ','marks':'баллы','source':'Источник','page':'стр.'}}[locale]
    content_layout=style.get('content_layout','answer_key' if role=='teacher_key' else 'document')
    top_margin=50 if layout=='executive' else 38 if layout=='compact' else 45
    shortened=False
    story=[]
    logo=(style or {}).get('logo_png')
    if logo:
        from PIL import Image
        with Image.open(io.BytesIO(logo)) as picture:
            scale=min(110/picture.width,40/picture.height)
            mark=FlowImage(io.BytesIO(logo),width=picture.width*scale,height=picture.height*scale);mark.hAlign='LEFT';story.extend([mark,Spacer(1,10)])
    brand=(style or {}).get('brand_name','')
    if brand:story.append(Paragraph(escape(brand),styles['small']))
    story.append(Paragraph(escape(content['title']),styles['title']))
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
        # One section is one page, in both directions: a page break after each so
        # a short section cannot merge into the next, and a measured fit so a
        # long one cannot spill into an extra page.
        frame_width=A4[0]-2*margin
        frame_height=A4[1]-top_margin-48
        sections,shortened=fit_to_pages([dict(s) for s in content['sections']],styles,frame_width,frame_height,body_size,body_leading)
        for index,section in enumerate(sections):
            if index:story.append(PageBreak())
            if section['heading'].strip():story.append(Paragraph(escape(section['heading']),styles['heading']))
            for line in (section['body'] or ' ').split('\n'):
                story.append(Paragraph(escape(line) or '&#160;',styles['body']))
        if content.get('questions'):story.append(Paragraph(labels[0],styles['heading']))
        for i,q in enumerate(content.get('questions',[])):
            story.append(Paragraph(escape(f"{i+1}. {q['stem']} ({q['marks']})"),styles['body']))
            for option in q.get('options',[]):story.append(Paragraph(escape('• '+option),styles['body']))
            story.append(Spacer(1,20))
    for ref in content.get('citations',[]):
        if isinstance(ref,dict) and 'page' in ref:story.append(Paragraph(escape(f"{details['source']} {str(ref.get('asset_id',''))[:8]} · {details['page']} {ref['page']}"),styles['small']))
    def footer(canvas,doc):
        canvas.setFont('PDFMaster',8);canvas.setFillColor(colors.HexColor('#68756b'))
        canvas.drawString(margin,26,content['title'][:55]);canvas.drawRightString(A4[0]-margin,26,str(doc.page))
        if layout=='executive':
            canvas.setStrokeColor(colors.HexColor(accent));canvas.setLineWidth(3);canvas.line(margin,A4[1]-24,A4[0]-margin,A4[1]-24)
        elif layout=='notes':
            canvas.setStrokeColor(colors.HexColor('#ddd6e8'));canvas.setLineWidth(.5);canvas.line(margin-13,45,margin-13,A4[1]-35)
    SimpleDocTemplate(str(path),pagesize=A4,rightMargin=margin,leftMargin=margin,topMargin=top_margin,bottomMargin=48,title=content['title'],author='PDF Master').build(story,onFirstPage=footer,onLaterPages=footer)
    return {'path':str(path),'name':path.name,'mime_type':'application/pdf','page_count':len(PdfReader(path).pages),'role':role,'shortened':shortened}
