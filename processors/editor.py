"""Validated PDF editing commands. Coordinates are points from displayed top left.

Existing-text mutation edits real PDF text operands, never draws over old text.
Redaction explicitly rasterizes every page and copies no original PDF objects.
"""
from __future__ import annotations
import io
import math
import re
from pathlib import Path
from pypdf import PdfReader,PdfWriter
from pypdf.generic import ArrayObject,FloatObject,NameObject,NumberObject,TextStringObject,ContentStream,DictionaryObject,DecodedStreamObject

FEATURE_COMMANDS={
 'editor.visual':{'add_text','highlight','note','draw','fill_form','signature','insert_image','replace_text','replace_image','remove_image','redact'},
 'editor.add_text':{'add_text'},'editor.highlight':{'highlight'},'editor.annotate':{'note','draw'},
 'editor.fill_forms':{'fill_form'},'editor.signature_image':{'signature'},'editor.existing_text':{'replace_text'},
 'editor.insert_images':{'insert_image'},'editor.replace_images':{'replace_image','remove_image'},'editor.redact':{'redact'},
}
COMMAND_FEATURES={command:feature for feature,commands in FEATURE_COMMANDS.items() if feature!='editor.visual' for command in commands}
SCHEMAS={feature:{'type':'object','additionalProperties':False,'properties':{
 'commands':{'type':'array','minItems':1,'maxItems':100,'items':{'type':'object','description':'Validated PDF command; coordinates use top-left PDF points'}},
 'accept_rasterization':{'type':'boolean'}},'required':['commands']} for feature in FEATURE_COMMANDS}
FIELDS={
 'add_text':{'type','page','x','y','text','font_size','color'},
 'highlight':{'type','page','x','y','width','height','color'},
 'note':{'type','page','x','y','text'},
 'draw':{'type','page','points','color','stroke_width'},
 'fill_form':{'type','field','value'},
 'signature':{'type','page','x','y','width','height','input_index'},
 'insert_image':{'type','page','x','y','width','height','input_index'},
 'replace_text':{'type','page','find','replacement'},
 'replace_image':{'type','page','image_index','input_index'},
 'remove_image':{'type','page','image_index'},
 'redact':{'type','page','x','y','width','height'},
}


def _number(value,minimum=0,maximum=14400):
    from .engine import ProcessorError
    if type(value) not in (int,float) or not math.isfinite(value) or not minimum<=value<=maximum:raise ProcessorError('invalid_editor_command')
    return value


def normalize(feature,parameters,metadata=None):
    from .engine import ProcessorError
    if not isinstance(parameters,dict) or set(parameters)-{'commands','accept_rasterization'}:raise ProcessorError('invalid_parameters')
    commands=parameters.get('commands')
    if not isinstance(commands,list) or not 1<=len(commands)<=100:raise ProcessorError('invalid_editor_command')
    normalized=[]
    for raw in commands:
        if not isinstance(raw,dict) or raw.get('type') not in FEATURE_COMMANDS[feature]:raise ProcessorError('invalid_editor_command')
        command=dict(raw);kind=command['type']
        if set(command)-FIELDS[kind]:raise ProcessorError('invalid_editor_command')
        if kind!='fill_form':
            if type(command.get('page')) is not int or not 1<=command['page']<=(metadata[0]['page_count'] if metadata else 1000):raise ProcessorError('invalid_editor_command')
        for axis in ('x','y'):
            if axis in FIELDS[kind]:_number(command.get(axis))
        for size in ('width','height'):
            if size in FIELDS[kind]:_number(command.get(size),1)
        if kind in ('add_text','note'):
            if not isinstance(command.get('text'),str) or not 1<=len(command['text'])<=2000 or any(ord(c)<32 and c not in '\n\t' for c in command['text']):raise ProcessorError('invalid_editor_command')
        if kind=='add_text':
            command.setdefault('font_size',16);_number(command['font_size'],6,96)
        if kind in ('add_text','highlight','draw'):
            command.setdefault('color','#FFFF00' if kind=='highlight' else '#000000')
            if not isinstance(command['color'],str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}',command['color']):raise ProcessorError('invalid_editor_command')
        if kind=='draw':
            points=command.get('points')
            if not isinstance(points,list) or not 2<=len(points)<=200:raise ProcessorError('invalid_editor_command')
            for point in points:
                if not isinstance(point,list) or len(point)!=2:raise ProcessorError('invalid_editor_command')
                for coordinate in point:_number(coordinate)
            command.setdefault('stroke_width',2);_number(command['stroke_width'],.5,12)
        if kind=='fill_form':
            if not isinstance(command.get('field'),str) or not 1<=len(command['field'])<=200 or not isinstance(command.get('value'),str) or len(command['value'])>2000:raise ProcessorError('invalid_editor_command')
        if kind=='replace_text':
            for key in ('find','replacement'):
                if not isinstance(command.get(key),str) or len(command[key])>500:raise ProcessorError('invalid_editor_command')
            if not command['find']:raise ProcessorError('invalid_editor_command')
        if kind in ('insert_image','signature','replace_image'):
            if type(command.get('input_index')) is not int or not 1<=command['input_index']<=(len(metadata)-1 if metadata else 25):raise ProcessorError('invalid_editor_command')
            if metadata and metadata[command['input_index']]['kind']!='image':raise ProcessorError('unsupported_type')
        if kind in ('replace_image','remove_image'):
            if type(command.get('image_index')) is not int or not 0<=command['image_index']<1000:raise ProcessorError('invalid_editor_command')
        normalized.append(command)
    accepted=parameters.get('accept_rasterization',False)
    if type(accepted) is not bool:raise ProcessorError('invalid_parameters')
    if any(c['type']=='redact' for c in normalized) and not accepted:raise ProcessorError('rasterization_consent_required')
    if any(c['type']=='redact' for c in normalized) and any(c['type']!='redact' for c in normalized):raise ProcessorError('redaction_requires_separate_export')
    return {'commands':normalized,'accept_rasterization':accepted}


def _font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    if 'PDFMasterNoto' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('PDFMasterNoto',str(Path(__file__).resolve().parent/'assets/fonts/NotoSans-Regular.ttf')))
    return 'PDFMasterNoto'


def _geometry(page,command):
    from .engine import ProcessorError
    width,height=float(page.mediabox.width),float(page.mediabox.height)
    if float(page.get('/UserUnit',1))!=1 or list(page.cropbox)!=list(page.mediabox) or float(page.mediabox.left)!=0 or float(page.mediabox.bottom)!=0:raise ProcessorError('unsupported_page_geometry')
    if 'x' in command:
        if command['x']>=width or command['y']>=height or command.get('width',0)+command['x']>width or command.get('height',0)+command['y']>height:raise ProcessorError('editor_out_of_bounds')
    if 'points' in command and any(x>width or y>height for x,y in command['points']):raise ProcessorError('editor_out_of_bounds')
    return width,height


def _overlay(page,command,image_path=None):
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.lib.utils import ImageReader
    from reportlab.lib.colors import HexColor
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from PIL import Image,ImageOps
    from .engine import ProcessorError
    width,height=_geometry(page,command)
    buffer=io.BytesIO();canvas=Canvas(buffer,pagesize=(width,height),pageCompression=1)
    if command['type']=='add_text':
        size=command['font_size'];font=_font();lines=command['text'].splitlines()
        if any(command['x']+stringWidth(line,font,size)>width for line in lines) or command['y']+len(lines)*size*1.3>height:raise ProcessorError('editor_text_overflow')
        canvas.setFillColor(HexColor(command['color']));canvas.setFont(font,size)
        for index,line in enumerate(lines):canvas.drawString(command['x'],height-command['y']-size-index*size*1.3,line)
    elif command['type']=='draw':
        canvas.setStrokeColor(HexColor(command['color']));canvas.setLineWidth(command['stroke_width'])
        path=canvas.beginPath();path.moveTo(command['points'][0][0],height-command['points'][0][1])
        for x,y in command['points'][1:]:path.lineTo(x,height-y)
        canvas.drawPath(path)
    else:
        with Image.open(image_path,formats=['PNG','JPEG','WEBP']) as raw:
            picture=ImageOps.exif_transpose(raw).convert('RGBA')
            canvas.drawImage(ImageReader(picture),command['x'],height-command['y']-command['height'],command['width'],command['height'],mask='auto',preserveAspectRatio=True,anchor='c')
    canvas.save();page.merge_page(PdfReader(io.BytesIO(buffer.getvalue())).pages[0])


def _replace_text(page,command,writer):
    from .engine import ProcessorError
    if not command['find'].isascii() or not command['replacement'].isascii():raise ProcessorError('unsupported_text_encoding')
    content=page.get_contents()
    if content is None:raise ProcessorError('text_not_found')
    stream=ContentStream(content,writer);font=None;changed=0
    fonts=page['/Resources'].get('/Font',{})
    if hasattr(fonts,'get_object'):fonts=fonts.get_object()
    standard={'Helvetica','Helvetica-Bold','Helvetica-Oblique','Helvetica-BoldOblique','Times-Roman','Times-Bold','Times-Italic','Times-BoldItalic','Courier','Courier-Bold','Courier-Oblique','Courier-BoldOblique'}
    def replace(value):
        nonlocal changed
        if not isinstance(value,TextStringObject) or command['find'] not in str(value):return value
        if font is None:raise ProcessorError('unsupported_text_encoding')
        definition=fonts[font].get_object()
        if definition.get('/Subtype')!='/Type1' or str(definition.get('/BaseFont','')).lstrip('/') not in standard or definition.get('/Encoding','/StandardEncoding') not in ('/StandardEncoding','/WinAnsiEncoding','/MacRomanEncoding') or '/ToUnicode' in definition:raise ProcessorError('unsupported_text_encoding')
        changed+=str(value).count(command['find'])
        return TextStringObject(str(value).replace(command['find'],command['replacement']))
    for operands,operator in stream.operations:
        if operator==b'Tf':font=operands[0]
        elif operator in (b'Tj',b"'",b'"') and operands:operands[-1]=replace(operands[-1])
        elif operator==b'TJ':operands[0]=ArrayObject([replace(value) for value in operands[0]])
    if not changed:raise ProcessorError('text_not_found')
    page.replace_contents(stream)
    return changed


def _replace_image(page,command,writer,image_path=None):
    from PIL import Image,ImageOps
    from .engine import ProcessorError
    images=page.images
    if command['image_index']>=len(images):raise ProcessorError('image_not_found')
    target=images[command['image_index']]
    if command['type']=='replace_image':
        with Image.open(image_path,formats=['PNG','JPEG','WEBP']) as raw:target.replace(ImageOps.exif_transpose(raw).convert('RGB'))
        return
    resources=page['/Resources'].get('/XObject',{})
    if hasattr(resources,'get_object'):resources=resources.get_object()
    names={name for name,ref in resources.items() if getattr(ref,'idnum',None)==getattr(target.indirect_reference,'idnum',None)}
    if not names:raise ProcessorError('unsupported_nested_image')
    stream=ContentStream(page.get_contents(),writer);original=len(stream.operations)
    stream.operations=[(operands,operator) for operands,operator in stream.operations if not (operator==b'Do' and operands[0] in names)]
    if len(stream.operations)==original:raise ProcessorError('image_not_found')
    page.replace_contents(stream)
    for name in names:del resources[name]


def _qualified_field_name(widget):
    names=[];node=widget
    for _ in range(25):
        if '/T' in node:names.insert(0,str(node['/T']))
        if '/Parent' not in node:break
        node=node['/Parent'].get_object()
    return '.'.join(names)


def _form_appearance(writer,widget,value):
    """Embed Unicode appearance text while retaining the canonical editable field."""
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from .engine import ProcessorError
    box=widget['/Rect'];width=float(box[2])-float(box[0]);height=float(box[3])-float(box[1])
    lines=value.splitlines() or [''];font=_font();size=min(11,(height-6)/(len(lines)*1.25))
    if size<5 or any(stringWidth(line,font,size)>width-8 for line in lines):raise ProcessorError('form_value_overflow')
    buffer=io.BytesIO();canvas=Canvas(buffer,pagesize=(width,height),pageCompression=0)
    canvas.setFillColorRGB(1,1,1);canvas.rect(0,0,width,height,fill=1,stroke=0);canvas.setFillColorRGB(0,0,0);canvas.setFont(font,size)
    for i,line in enumerate(lines):canvas.drawString(4,height-4-size-i*size*1.25,line)
    canvas.save();source=PdfReader(io.BytesIO(buffer.getvalue())).pages[0]
    appearance=DecodedStreamObject();appearance.set_data(source.get_contents().get_data())
    appearance.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Form'),NameObject('/BBox'):ArrayObject([FloatObject(0),FloatObject(0),FloatObject(width),FloatObject(height)]),NameObject('/Resources'):source['/Resources'].clone(writer)})
    widget[NameObject('/AP')]=DictionaryObject({NameObject('/N'):writer._add_object(appearance)})


def _fill_forms(writer,values):
    from .engine import ProcessorError
    fields=writer.get_fields() or {}
    if any(name not in fields for name in values):raise ProcessorError('form_field_not_found')
    for name in values:
        field=fields[name]
        if field.get('/FT') not in ('/Tx','/Btn','/Ch') or int(field.get('/Ff',0))&8192:raise ProcessorError('unsupported_form_field')
    writer.update_page_form_field_values(None,values,auto_regenerate=False)
    for page in writer.pages:
        for ref in page.get('/Annots',[]):
            widget=ref.get_object();name=_qualified_field_name(widget)
            if name in values:
                node=widget.get('/Parent',widget)
                if hasattr(node,'get_object'):node=node.get_object()
                if widget.get('/FT',node.get('/FT'))=='/Tx':_form_appearance(writer,widget,values[name])


def _redact(source,commands,out):
    import pypdfium2 as pdfium
    from PIL import ImageDraw
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.lib.utils import ImageReader
    from .engine import ProcessorError,MAX_PIXELS,MAX_RENDER_PIXELS,_artifact
    destination=out/'redacted.pdf';canvas=Canvas(str(destination),pageCompression=1);total=0
    with pdfium.PdfDocument(str(source)) as document:
        document.init_forms()
        for index in range(len(document)):
            page=document[index];width,height=page.get_size();scale=2.0
            pixels=math.ceil(width*scale)*math.ceil(height*scale);total+=pixels
            if pixels>MAX_PIXELS or total>MAX_RENDER_PIXELS:raise ProcessorError('render_pixel_limit')
            bitmap=page.render(scale=scale)
            try:picture=bitmap.to_pil().convert('RGB')
            finally:bitmap.close();page.close()
            drawing=ImageDraw.Draw(picture)
            for command in commands:
                if command['page']!=index+1:continue
                x,y,w,h=command['x'],command['y'],command['width'],command['height']
                if x+w>width or y+h>height:raise ProcessorError('editor_out_of_bounds')
                # Expand by a pixel at each edge so anti-aliased boundary glyphs are removed.
                drawing.rectangle((max(0,math.floor(x*scale)-1),max(0,math.floor(y*scale)-1),min(picture.width,math.ceil((x+w)*scale)+1),min(picture.height,math.ceil((y+h)*scale)+1)),fill='black')
            canvas.setPageSize((width,height));canvas.drawImage(ImageReader(picture),0,0,width,height);canvas.showPage();picture.close()
    canvas.save()
    artifact=_artifact(destination)
    # Prove original recoverable text, annotation/form trees and attachments are absent.
    reader=PdfReader(destination)
    if reader.get_fields() or any(page.extract_text().strip() or page.get('/Annots') for page in reader.pages):raise ProcessorError('redaction_validation_failed')
    return [artifact],{'engine':'pdfium/pillow/reportlab','warnings':['all_pages_rasterized_text_and_forms_removed','original_versions_may_still_exist'],'redaction_mode':'rasterized_destructive'}


def execute(feature,paths,parameters,out,metadata):
    from .engine import _pdf_reader,_write_pdf,ProcessorError
    from pypdf.annotations import Highlight,Text
    commands=parameters['commands']
    if any(c['type']=='redact' for c in commands):return _redact(paths[0],commands,out)
    reader=_pdf_reader(paths[0],allow_forms=True)
    writer=PdfWriter();writer.clone_document_from_reader(reader)
    for page in writer.pages:
        if page.rotation:page.transfer_rotation_to_content()
    replacements=0;form_values={}
    for command in commands:
        kind=command['type']
        if kind=='fill_form':form_values[command['field']]=command['value'];continue
        page=writer.pages[command['page']-1];width,height=_geometry(page,command)
        if kind in ('add_text','draw'):_overlay(page,command)
        elif kind in ('insert_image','signature'):_overlay(page,command,paths[command['input_index']])
        elif kind=='replace_text':replacements+=_replace_text(page,command,writer)
        elif kind in ('replace_image','remove_image'):_replace_image(page,command,writer,paths[command['input_index']] if 'input_index' in command else None)
        elif kind=='note':
            x,y=command['x'],height-command['y']
            writer.add_annotation(command['page']-1,Text(rect=(x,max(0,y-22),min(width,x+22),y),text=command['text']))
        elif kind=='highlight':
            x,y,w,h=command['x'],height-command['y'],command['width'],command['height']
            writer.add_annotation(command['page']-1,Highlight(rect=(x,y-h,x+w,y),quad_points=ArrayObject([FloatObject(v) for v in (x,y,x+w,y,x,y-h,x+w,y-h)]),highlight_color=command['color'][1:]))
    if form_values:_fill_forms(writer,form_values)
    writer.compress_identical_objects(remove_duplicates=True,remove_unreferenced=True)
    artifact=_write_pdf(writer,out/'edited.pdf',allow_forms=True)
    reopened=PdfReader(artifact['path'])
    for name,value in form_values.items():
        if str((reopened.get_fields() or {}).get(name,{}).get('/V',''))!=value:raise ProcessorError('form_validation_failed')
    warnings=[]
    if replacements:warnings.append('existing_text_simple_standard_fonts_only')
    return [artifact],{'engine':'pypdf/reportlab','warnings':warnings,'text_replacements':replacements,'command_features':sorted({COMMAND_FEATURES[c['type']] for c in commands})}
