"""Deterministic Unicode document renderer. Content is always text, never HTML code."""
from pathlib import Path
import io
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
        for section in content['sections']:
            story.append(Paragraph(escape(section['heading']),styles['heading']))
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
    SimpleDocTemplate(str(path),pagesize=A4,rightMargin=margin,leftMargin=margin,topMargin=50 if layout=='executive' else 38 if layout=='compact' else 45,bottomMargin=48,title=content['title'],author='PDF Master').build(story,onFirstPage=footer,onLaterPages=footer)
    return {'path':str(path),'name':path.name,'mime_type':'application/pdf','page_count':len(PdfReader(path).pages),'role':role}

def render_pptx(content,path,locale='en',role='user_document',style=None):
    style=style or {};accent=style.get('accent','#255e49').lstrip('#')
    layout=style.get('layout','clean');body_size=18 if layout=='compact' else 20
    line_count=14 if layout=='compact' else 9 if layout=='notes' else 11
    line_spacing=23 if layout=='compact' else 33 if layout=='notes' else 27
    from pptx import Presentation
    from pptx.util import Inches,Pt
    from pptx.dml.color import RGBColor
    if 'PDFMaster' not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont('PDFMaster',str(font_path())))
    def wrapped(text,size,width):
        lines=[]
        for paragraph in text.split('\n'):
            current=''
            for character in paragraph:
                if current and pdfmetrics.stringWidth(current+character,'PDFMaster',size)>width:
                    # Prefer a word break; very long tokens still wrap safely.
                    before,separator,tail=current.rpartition(' ')
                    if separator and before:lines.append(before);current=tail+character
                    else:lines.append(current);current=character
                else:current+=character
            lines.append(current)
        return lines
    deck=Presentation();deck.slide_width=Inches(13.333);deck.slide_height=Inches(7.5)
    content_layout=style.get('content_layout','answer_key' if role=='teacher_key' else 'document')
    sections=[] if content_layout in ('answer_key','flashcards') else list(content['sections'])
    # Questions are editable learner slide content. Answers never enter slides
    # with a learner role; the teacher receives the separate PDF key.
    for index,question in enumerate(content.get('questions',[]),1):
        question_label={'en':'Question','uz':'Savol','ru':'Вопрос'}[locale]
        if content_layout in ('answer_key','flashcards'):
            answer_label={'en':'Answer','uz':'Javob','ru':'Ответ'}[locale]
            marks_label={'en':'points','uz':'ball','ru':'баллы'}[locale]
            label=({'en':'Card','uz':'Kartochka','ru':'Карточка'}[locale] if content_layout=='flashcards' else question_label)+' '+str(index)
            body=question['stem']+(f" ({question['marks']} {marks_label})" if content_layout=='answer_key' else '')+'\n'+answer_label+': '+question['answer']+'\n'+question['explanation']
        else:label=question_label+' '+str(index);body=question['stem']+'\n'+'\n'.join(question.get('options',[]))
        sections.append({'heading':label,'body':body,'notes':''})
    for section in sections:
        heading_text=section['heading']
        body_text=section['body']
        if len(wrapped(heading_text,18,800))>2:
            body_text=heading_text+'\n'+body_text
            heading_text={'en':'Section','uz':'Bo‘lim','ru':'Раздел'}[locale]
        lines=wrapped(body_text,body_size,790)
        chunks=[lines[start:start+line_count] for start in range(0,len(lines),line_count)] or [['']]
        for ci,chunk in enumerate(chunks):
            slide=deck.slides.add_slide(deck.slide_layouts[6]);slide.background.fill.solid();slide.background.fill.fore_color.rgb=RGBColor.from_string('F5F7F1')
            bar=slide.shapes.add_shape(1,0,0,deck.slide_width if layout=='executive' else Inches(.16),Inches(.16) if layout=='executive' else deck.slide_height);bar.fill.solid();bar.fill.fore_color.rgb=RGBColor.from_string(accent);bar.line.fill.background()
            heading=slide.shapes.add_textbox(Inches(.7),Inches(.5),Inches(11.9),Inches(1.1)).text_frame
            title=heading_text+(f' · {ci+1}' if ci else '')
            size=30
            while size>18 and len(wrapped(title,size,800))>2:size-=2
            title_lines=wrapped(title,size,800)
            heading.word_wrap=False
            for j,line in enumerate(title_lines):
                p=heading.paragraphs[0] if j==0 else heading.add_paragraph();p.text=line;p.font.name='Noto Sans';p.font.size=Pt(size);p.font.color.rgb=RGBColor.from_string(accent);p.space_after=Pt(0);p.line_spacing=Pt(size+3)
            body=slide.shapes.add_textbox(Inches(.75),Inches(1.8),Inches(11.8),Inches(4.7)).text_frame;body.word_wrap=False
            for j,line in enumerate(chunk):
                p=body.paragraphs[0] if j==0 else body.add_paragraph();p.text=line;p.font.name='Noto Sans';p.font.size=Pt(body_size);p.space_after=Pt(0);p.line_spacing=Pt(line_spacing)
            brand=(style or {}).get('brand_name','')
            if brand:
                label=slide.shapes.add_textbox(Inches(.75),Inches(6.95),Inches(9.6),Inches(.3)).text_frame
                p=label.paragraphs[0];p.text=brand;p.font.name='Noto Sans';p.font.size=Pt(9);p.font.color.rgb=RGBColor.from_string(accent)
            logo=(style or {}).get('logo_png')
            if logo:
                from PIL import Image
                with Image.open(io.BytesIO(logo)) as picture:
                    scale=min(1.5/picture.width,.48/picture.height)
                    width,height=picture.width*scale,picture.height*scale
                slide.shapes.add_picture(io.BytesIO(logo),Inches(12.65-width),Inches(7.15-height),width=Inches(width),height=Inches(height))
            slide.notes_slide.notes_text_frame.text='' if role in ('learner_material','public_preview') else section.get('notes','')
    # python-pptx's bundled blank template includes a binary printer settings
    # part. Generated content does not need it; removing the relationship drops
    # that part on save and keeps the strict Office binary-content policy intact.
    for relationship in list(deck.part.rels.values()):
        if relationship.reltype.endswith('/printerSettings'):deck.part.drop_rel(relationship.rId)
    deck.save(str(path))
    return {'path':str(path),'name':path.name,'mime_type':'application/vnd.openxmlformats-officedocument.presentationml.presentation','page_count':len(deck.slides),'role':role}
