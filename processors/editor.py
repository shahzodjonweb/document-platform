"""Validated PDF editing commands. Coordinates are points from displayed top left.

Existing-text mutation edits real PDF text operands, never draws over old text.
Redaction from a command list sent whole rasterizes every page and copies no
original PDF objects; a stored draft's send (`combined`) rasterizes only the
pages with a box and removes what else could carry them (see _pipeline).
"""
from __future__ import annotations
import copy
import io
import math
import re
from pathlib import Path
from pypdf import PdfReader,PdfWriter,Transformation
from pypdf.generic import ArrayObject,FloatObject,IndirectObject,NameObject,NumberObject,TextStringObject,ContentStream,DictionaryObject,DecodedStreamObject,StreamObject

FEATURE_COMMANDS={
 'editor.visual':{'add_text','highlight','note','draw','fill_form','signature','insert_image','replace_text','replace_image','remove_image','redact','edit_text','whiteout','rotate_page','delete_page','reorder'},
 'editor.add_text':{'add_text','whiteout'},'editor.highlight':{'highlight'},'editor.annotate':{'note','draw'},
 'editor.fill_forms':{'fill_form'},'editor.signature_image':{'signature'},'editor.existing_text':{'replace_text','edit_text'},
 'editor.insert_images':{'insert_image'},'editor.replace_images':{'replace_image','remove_image'},'editor.redact':{'redact'},
}
# A kind with no narrower feature of its own (the page operations) belongs to editor.visual.
COMMAND_FEATURES={command:'editor.visual' for command in FEATURE_COMMANDS['editor.visual']}|{command:feature for feature,commands in FEATURE_COMMANDS.items() if feature!='editor.visual' for command in commands}
# In the contract, and refused by execute until a stage can apply it.
UNAPPLIED_COMMANDS={'edit_text'}
PAGE_COMMANDS={'rotate_page','delete_page','reorder'}
SCHEMAS={feature:{'type':'object','additionalProperties':False,'properties':{
 'commands':{'type':'array','minItems':1,'maxItems':100,'items':{'type':'object','description':'Validated PDF command; coordinates use top-left PDF points'}},
 'accept_rasterization':{'type':'boolean'}},'required':['commands']} for feature in FEATURE_COMMANDS}
FIELDS={
 'add_text':{'type','page','x','y','text','font_size','color','font','bold','italic'},
 'highlight':{'type','page','x','y','width','height','color'},
 'note':{'type','page','x','y','text'},
 'draw':{'type','page','points','color','stroke_width'},
 'fill_form':{'type','field','value'},
 'signature':{'type','page','x','y','width','height','input_index'},
 'insert_image':{'type','page','x','y','width','height','input_index'},
 'replace_text':{'type','page','find','replacement'},
 'replace_image':{'type','page','image_index','input_index'},
 'remove_image':{'type','page','image_index'},
 'redact':{'type','page','x','y','width','height','text'},
 'edit_text':{'type','page','x','y','width','height','original','text'},
 'whiteout':{'type','page','x','y','width','height','color'},
 'rotate_page':{'type','page','angle'},
 'delete_page':{'type','page'},
 'reorder':{'type','order'},
}


# Pixels a point when a page becomes a picture, and the lightest grey still called black when it is looked at again.
RASTER_SCALE=2.0
BLACK=16
# How far past a page's edge a mark may reach: a page's size comes here rounded by whichever library reads it.
EDGE=.01
# An annotation's flag for staying upright whichever way its page is shown.
NO_ROTATE=16


def _number(value,minimum=0,maximum=14400):
    from .engine import ProcessorError
    if type(value) not in (int,float) or not math.isfinite(value) or not minimum<=value<=maximum:raise ProcessorError('invalid_editor_command')
    return value


def _text(value,maximum,minimum=0,allowed='\n\t'):
    from .engine import ProcessorError
    if not isinstance(value,str) or not minimum<=len(value)<=maximum or any(ord(c)<32 and c not in allowed for c in value):raise ProcessorError('invalid_editor_command')


def _pages(normalized,metadata):
    """What holds across the page operations. All of them speak in source page numbers."""
    from .engine import ProcessorError
    count=metadata[0]['page_count'] if metadata else None
    seen=set();deleted=0;ordered=False
    for index,command in enumerate(normalized):
        kind=command['type']
        if kind in ('rotate_page','delete_page'):
            if (kind,command['page']) in seen:raise ProcessorError('invalid_editor_command',index=index)
            seen.add((kind,command['page']))
        if kind=='delete_page':
            deleted+=1
            if count is not None and deleted>=count:raise ProcessorError('invalid_editor_command',index=index)
        if kind=='reorder':
            order=command.get('order')
            # Every source page, deleted ones too, so a later delete never invalidates the order.
            if ordered or not isinstance(order,list) or not 1<=len(order)<=(count or 1000) or any(type(page) is not int for page in order) or sorted(order)!=list(range(1,(count or len(order))+1)):raise ProcessorError('invalid_editor_command',index=index)
            ordered=True


def _command(feature,raw,metadata):
    from .engine import ProcessorError
    if not isinstance(raw,dict) or raw.get('type') not in FEATURE_COMMANDS[feature]:raise ProcessorError('invalid_editor_command')
    command=dict(raw);kind=command['type']
    if set(command)-FIELDS[kind]:raise ProcessorError('invalid_editor_command')
    if kind not in ('fill_form','reorder'):
        if type(command.get('page')) is not int or not 1<=command['page']<=(metadata[0]['page_count'] if metadata else 1000):raise ProcessorError('invalid_editor_command')
    for axis in ('x','y'):
        if axis in FIELDS[kind]:_number(command.get(axis))
    for size in ('width','height'):
        if size in FIELDS[kind]:_number(command.get(size),1)
    if kind in ('add_text','note'):_text(command.get('text'),2000,1)
    if kind=='add_text':
        command.setdefault('font_size',16);_number(command['font_size'],6,96)
        if command.get('font','sans') not in ('sans','serif'):raise ProcessorError('invalid_editor_command')
        for style in ('bold','italic'):
            if type(command.get(style,False)) is not bool:raise ProcessorError('invalid_editor_command')
    if kind=='edit_text':
        _text(command.get('original'),2000,1);_text(command.get('text'),2000)
    if kind=='redact' and 'text' in command:_text(command['text'],2000)
    if kind=='rotate_page' and (type(command.get('angle')) is not int or command['angle'] not in (90,180,270)):raise ProcessorError('invalid_editor_command')
    if kind in ('add_text','highlight','draw','whiteout'):
        command.setdefault('color',{'highlight':'#FFFF00','whiteout':'#FFFFFF'}.get(kind,'#000000'))
        if not isinstance(command['color'],str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}',command['color']):raise ProcessorError('invalid_editor_command')
    if kind=='draw':
        points=command.get('points')
        if not isinstance(points,list) or not 2<=len(points)<=200:raise ProcessorError('invalid_editor_command')
        for point in points:
            if not isinstance(point,list) or len(point)!=2:raise ProcessorError('invalid_editor_command')
            for coordinate in point:_number(coordinate)
        command.setdefault('stroke_width',2);_number(command['stroke_width'],.5,12)
    if kind=='fill_form':
        # A field's name is the PDF's own, whatever it holds, and execute matches it against the real fields. Only NUL cannot be stored.
        if not isinstance(command.get('field'),str) or not 1<=len(command['field'])<=200 or '\x00' in command['field']:raise ProcessorError('invalid_editor_command')
        _text(command.get('value'),2000,allowed='\n\t\r')
    if kind=='replace_text':
        _text(command.get('find'),500,1);_text(command.get('replacement'),500)
    if kind in ('insert_image','signature','replace_image'):
        if type(command.get('input_index')) is not int or not 1<=command['input_index']<=(len(metadata)-1 if metadata else 25):raise ProcessorError('invalid_editor_command')
        if metadata and metadata[command['input_index']]['kind']!='image':raise ProcessorError('unsupported_type')
    if kind in ('replace_image','remove_image'):
        if type(command.get('image_index')) is not int or not 0<=command['image_index']<1000:raise ProcessorError('invalid_editor_command')
    return command


def _deleted(commands):
    return {c['page'] for c in commands if c['type']=='delete_page'}


def raster_pages(commands):
    """The source pages that will really become pictures: a box on a page being deleted draws nothing."""
    return sorted({c['page'] for c in commands if c['type']=='redact'}-_deleted(commands))


def normalize(feature,parameters,metadata=None):
    """`combined` is a stored draft's send: one job of every kind, with consent asked only for pages that really become pictures.

    Never taken from a caller (apps.core.services.create_quote refuses it).
    """
    from .engine import ProcessorError
    if not isinstance(parameters,dict) or set(parameters)-{'commands','accept_rasterization','combined'}:raise ProcessorError('invalid_parameters')
    commands=parameters.get('commands')
    if not isinstance(commands,list) or not 1<=len(commands)<=100:raise ProcessorError('invalid_editor_command')
    normalized=[]
    for index,raw in enumerate(commands):
        try:normalized.append(_command(feature,raw,metadata))
        except ProcessorError as error:error.index=index;raise
    _pages(normalized,metadata)
    accepted=parameters.get('accept_rasterization',False)
    combined=parameters.get('combined',False)
    if type(accepted) is not bool or type(combined) is not bool:raise ProcessorError('invalid_parameters')
    if combined:
        if raster_pages(normalized) and not accepted:raise ProcessorError('rasterization_consent_required')
        return {'commands':normalized,'accept_rasterization':accepted,'combined':True}
    if any(c['type']=='redact' for c in normalized) and not accepted:raise ProcessorError('rasterization_consent_required')
    if any(c['type']=='redact' for c in normalized) and any(c['type']!='redact' for c in normalized):raise ProcessorError('redaction_requires_separate_export')
    return {'commands':normalized,'accept_rasterization':accepted}


def _font(family='sans',bold=False,italic=False):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    # No bold italic is vendored, and bold says more than the slant.
    style='Bold' if bold else 'Italic' if italic else 'Regular'
    name=f'PDFMasterNoto{family.title()}{style}'
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name,str(Path(__file__).resolve().parent/f'assets/fonts/Noto{family.title()}-{style}.ttf')))
    return name


def _text_font(command):
    return _font(command.get('font','sans'),command.get('bold',False),command.get('italic',False))


def _text_fits(command,width,height):
    from reportlab.pdfbase.pdfmetrics import stringWidth
    size=command['font_size'];font=_text_font(command);lines=command['text'].splitlines()
    return all(command['x']+stringWidth(line,font,size)<=width for line in lines) and command['y']+len(lines)*size*1.3<=height


def overflowing(commands,page_sizes):
    """The first text that cannot fit its page by the rule _overlay holds it to, or None.

    Asked before a send (apps/studio/editor_domain.py), when the customer can
    still change it. No customer bytes are parsed: only our own font.
    """
    deleted=_deleted(commands)
    for index,command in enumerate(commands):
        if command['type']=='add_text' and command['page'] not in deleted and command['page']<=len(page_sizes):
            size=page_sizes[command['page']-1]
            if not _text_fits(command,size['width'],size['height']):return index
    return None


def _geometry(page,command):
    from .engine import ProcessorError
    width,height=float(page.mediabox.width),float(page.mediabox.height)
    if float(page.get('/UserUnit',1))!=1 or list(page.cropbox)!=list(page.mediabox) or abs(float(page.mediabox.left))>EDGE or abs(float(page.mediabox.bottom))>EDGE:raise ProcessorError('unsupported_page_geometry')
    if 'x' in command:
        if command['x']>=width or command['y']>=height or command.get('width',0)+command['x']>width+EDGE or command.get('height',0)+command['y']>height+EDGE:raise ProcessorError('editor_out_of_bounds')
    if 'points' in command and any(x>width+EDGE or y>height+EDGE for x,y in command['points']):raise ProcessorError('editor_out_of_bounds')
    return width,height


def _overlay(page,command,image_path=None):
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.lib.utils import ImageReader
    from reportlab.lib.colors import HexColor
    from PIL import Image,ImageOps
    from .engine import ProcessorError
    width,height=_geometry(page,command)
    buffer=io.BytesIO();canvas=Canvas(buffer,pagesize=(width,height),pageCompression=1)
    if command['type']=='add_text':
        size=command['font_size'];font=_text_font(command);lines=command['text'].splitlines()
        if not _text_fits(command,width,height):raise ProcessorError('editor_text_overflow')
        canvas.setFillColor(HexColor(command['color']));canvas.setFont(font,size)
        for index,line in enumerate(lines):canvas.drawString(command['x'],height-command['y']-size-index*size*1.3,line)
    elif command['type']=='whiteout':
        canvas.setFillColor(HexColor(command['color']));canvas.rect(command['x'],height-command['y']-command['height'],command['width'],command['height'],fill=1,stroke=0)
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


def _held(holder,key,kind):
    """What a key holds, if it is that kind of thing. A PDF null means the same as no key."""
    value=holder.get(key);value=value.get_object() if value is not None else None
    return value if isinstance(value,kind) else None


def _numbers(value):
    """The numbers of an array, or none where this is no array of numbers."""
    value=value.get_object() if value is not None else None
    items=[item.get_object() for item in value] if isinstance(value,ArrayObject) else []
    return [float(item) for item in items] if all(isinstance(item,(NumberObject,FloatObject)) for item in items) else []


def _widget_turn(widget):
    """How far a widget is drawn turned against its page, in degrees counter-clockwise."""
    turn=_held(_held(widget,'/MK',DictionaryObject) or {},'/R',(NumberObject,FloatObject))
    return int(turn)%360 if turn is not None else 0


def _form_appearance(writer,widget,value):
    """Embed Unicode appearance text while retaining the canonical editable field."""
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from .engine import ProcessorError
    box=widget['/Rect'];width=float(box[2])-float(box[0]);height=float(box[3])-float(box[1]);turn=_widget_turn(widget)
    # The words run along a turned field, as they did before its page was unturned.
    if turn in (90,270):width,height=height,width
    lines=value.splitlines() or [''];font=_font();size=min(11,(height-6)/(len(lines)*1.25))
    if size<5 or any(stringWidth(line,font,size)>width-8 for line in lines):raise ProcessorError('form_value_overflow')
    buffer=io.BytesIO();canvas=Canvas(buffer,pagesize=(width,height),pageCompression=0)
    canvas.setFillColorRGB(1,1,1);canvas.rect(0,0,width,height,fill=1,stroke=0);canvas.setFillColorRGB(0,0,0);canvas.setFont(font,size)
    for i,line in enumerate(lines):canvas.drawString(4,height-4-size-i*size*1.25,line)
    canvas.save();source=PdfReader(io.BytesIO(buffer.getvalue())).pages[0]
    appearance=DecodedStreamObject();appearance.set_data(source.get_contents().get_data())
    appearance.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Form'),NameObject('/BBox'):ArrayObject([FloatObject(0),FloatObject(0),FloatObject(width),FloatObject(height)]),NameObject('/Resources'):source['/Resources'].clone(writer)})
    if turn:_turn_appearance(appearance,Transformation().rotate(turn))
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


def _blacked_out(document,number,commands,rendered):
    """One page as a picture with its boxes painted on. `rendered` is the pixels used so far, returned grown."""
    from PIL import ImageDraw
    from .engine import ProcessorError,MAX_PIXELS,MAX_RENDER_PIXELS
    page=document[number-1];width,height=page.get_size();scale=RASTER_SCALE
    pixels=math.ceil(width*scale)*math.ceil(height*scale);rendered+=pixels
    if pixels>MAX_PIXELS or rendered>MAX_RENDER_PIXELS:raise ProcessorError('render_pixel_limit')
    bitmap=page.render(scale=scale)
    try:picture=bitmap.to_pil().convert('RGB')
    finally:bitmap.close();page.close()
    drawing=ImageDraw.Draw(picture)
    for command in commands:
        if command['type']!='redact' or command['page']!=number:continue
        x,y,w,h=command['x'],command['y'],command['width'],command['height']
        if x+w>width+EDGE or y+h>height+EDGE:raise ProcessorError('editor_out_of_bounds')
        # Expand by a pixel at each edge so anti-aliased boundary glyphs are removed.
        drawing.rectangle((max(0,math.floor(x*scale)-1),max(0,math.floor(y*scale)-1),min(picture.width,math.ceil((x+w)*scale)+1),min(picture.height,math.ceil((y+h)*scale)+1)),fill='black')
    return picture,width,height,rendered


def _redact(source,commands,out):
    import pypdfium2 as pdfium
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.lib.utils import ImageReader
    from .engine import ProcessorError,_artifact
    destination=out/'redacted.pdf';canvas=Canvas(str(destination),pageCompression=1);total=0
    with pdfium.PdfDocument(str(source)) as document:
        document.init_forms()
        for index in range(len(document)):
            picture,width,height,total=_blacked_out(document,index+1,commands,total)
            canvas.setPageSize((width,height));canvas.drawImage(ImageReader(picture),0,0,width,height);canvas.showPage();picture.close()
    canvas.save()
    artifact=_artifact(destination)
    # Prove original recoverable text, annotation/form trees and attachments are absent.
    reader=PdfReader(destination)
    if reader.get_fields() or any(page.extract_text().strip() or page.get('/Annots') for page in reader.pages):raise ProcessorError('redaction_validation_failed')
    return [artifact],{'engine':'pdfium/pillow/reportlab','warnings':['all_pages_rasterized_text_and_forms_removed','original_versions_may_still_exist'],'redaction_mode':'rasterized_destructive'}


def _blank(value):
    for key in list(value):del value[key]


def _forget_annotations(writer,page):
    """What a page that goes held beyond its drawing: its notes, and the values of its form fields. Returns the names of the fields."""
    annotations=page.get('/Annots') or []
    widgets=[ref.get_object() for ref in annotations if ref.get_object().get('/Subtype')=='/Widget']
    names={_qualified_field_name(widget) for widget in widgets}
    ids={widget.indirect_reference.idnum for widget in widgets if widget.indirect_reference}
    form=writer.root_object.get('/AcroForm')
    if ids and form is not None:
        form=form.get_object()
        def keep(ref):
            node=ref.get_object()
            if getattr(ref,'idnum',None) in ids:return False
            kids=node.get('/Kids')
            if kids is None:return True
            kids=kids.get_object()
            kids[:]=[kid for kid in kids if keep(kid)]
            return bool(kids)
        for key in ('/Fields','/CO'):
            if key in form:form[NameObject(key)]=ArrayObject([ref for ref in form[key] if keep(ref)])
        form.pop('/XFA',None)
    for ref in annotations:_blank(ref.get_object())
    return names


def _drawings(page):
    """The ids of the pictures and drawings a page has to hand."""
    resources=page.get('/Resources') or {}
    return {ref.idnum for ref in (resources.get('/XObject') or {}).values() if isinstance(ref,IndirectObject)}


def _unshare(writer,gone,pages):
    """A dictionary of resources shared across pages keeps a removed page's pictures in the file, unless each page that stays lists only what it draws."""
    for page in pages:
        resources=page.get('/Resources') or {};drawings=resources.get('/XObject') or {}
        names={name for name,ref in drawings.items() if getattr(ref,'idnum',None) in gone}
        if not names:continue
        contents=page.get_contents()
        used={operands[0] for operands,operator in ContentStream(contents,writer).operations if operator==b'Do'} if contents is not None else set()
        if names-used:
            own=DictionaryObject(drawings)
            for name in names-used:del own[name]
            kept=DictionaryObject(resources);kept[NameObject('/XObject')]=writer._add_object(own)
            page[NameObject('/Resources')]=writer._add_object(kept)


def _as_picture(writer,page,picture,width,height):
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.lib.utils import ImageReader
    buffer=io.BytesIO();canvas=Canvas(buffer,pagesize=(width,height),pageCompression=1)
    canvas.drawImage(ImageReader(picture),0,0,width,height);canvas.save();picture.close()
    drawn=PdfReader(io.BytesIO(buffer.getvalue())).pages[0]
    # Nothing of the page stays but its place and size: not its text, thumbnail, tags or actions.
    for key in list(page):
        if key not in ('/Type','/Parent','/MediaBox','/CropBox'):del page[key]
    page[NameObject('/Resources')]=drawn['/Resources'].clone(writer)
    page[NameObject('/Contents')]=drawn.raw_get('/Contents').clone(writer)


def _raster_stage(writer,commands,raster,out):
    """Black-out: each page with a box becomes a picture of itself as marked so far, and nothing else of it stays."""
    import pypdfium2 as pdfium
    stage=out/'stage.pdf';total=0;forgotten=set()
    with stage.open('xb') as stream:writer.write(stream)
    try:
        with pdfium.PdfDocument(str(stage)) as document:
            document.init_forms()
            for number in raster:
                picture,width,height,total=_blacked_out(document,number,commands,total)
                page=writer.pages[number-1];forgotten|=_forget_annotations(writer,page)
                _as_picture(writer,page,picture,width,height)
    finally:stage.unlink(missing_ok=True)
    return forgotten


def _carriers(writer,raster):
    """The parts of a document that repeat its pages' words. Tags go with any page that goes; a page blacked out also takes the bookmarks, which nothing here can read for what it hid. Attached files are refused at upload."""
    root=writer.root_object
    for key in ('/StructTreeRoot','/MarkInfo','/PieceInfo'):root.pop(key,None)
    if raster:
        for key in ('/Outlines','/Threads'):root.pop(key,None)


def _page_stage(writer,commands):
    """Page operations come last, in source page numbers, as every mark was placed in the source frame. Returns the source numbers in their final order."""
    pages=list(writer.pages);deleted=_deleted(commands)
    for command in commands:
        if command['type']=='rotate_page' and command['page'] not in deleted:pages[command['page']-1].rotate(command['angle'])
    order=next((c['order'] for c in commands if c['type']=='reorder'),range(1,len(pages)+1))
    final=[number for number in order if number not in deleted]
    kept=[pages[number-1] for number in final]
    tree=writer._pages.get_object()
    tree[NameObject('/Kids')]=ArrayObject([page.indirect_reference for page in kept]);tree[NameObject('/Count')]=NumberObject(len(kept))
    writer.flattened_pages[:]=kept
    return final


def _sweep(writer):
    """Only what the document can reach is written. Nothing but this takes out a removed page's parts, which still refer to one another."""
    objects=writer._objects;reached=set();stack=[reference for reference in (getattr(item,'indirect_reference',None) for item in (writer.root_object,writer._info)) if reference is not None]
    while stack:
        value=stack.pop()
        if isinstance(value,IndirectObject):
            if value.pdf is not writer or value.idnum in reached or not 0<value.idnum<=len(objects):continue
            reached.add(value.idnum);value=objects[value.idnum-1]
        if isinstance(value,DictionaryObject):stack.extend(value.values())
        elif isinstance(value,ArrayObject):stack.extend(value)
    for index in range(len(objects)):
        if index+1 not in reached:objects[index]=None


def _rotated_box(command,width,height,angle):
    """A box in the source frame, on a page now `width` by `height` after turning `angle` degrees clockwise."""
    x,y,w,h=command['x'],command['y'],command['width'],command['height']
    if angle==90:return width-y-h,x,h,w
    if angle==180:return width-x-w,height-y-h,w,h
    if angle==270:return y,height-x-w,h,w
    return x,y,w,h


def _check_boxes(path,commands,final):
    """Look at the file as made: every black-out box must be black, wherever its page ended up."""
    import pypdfium2 as pdfium
    from .engine import ProcessorError
    angles={c['page']:c['angle'] for c in commands if c['type']=='rotate_page'};positions={number:index for index,number in enumerate(final)}
    boxes={}
    for index,command in enumerate(commands):
        if command['type']=='redact' and command['page'] in positions:boxes.setdefault(command['page'],[]).append((index,command))
    with pdfium.PdfDocument(str(path)) as document:
        for number,rows in boxes.items():
            page=document[positions[number]];width,height=page.get_size()
            bitmap=page.render(scale=RASTER_SCALE)
            try:picture=bitmap.to_pil().convert('L')
            finally:bitmap.close();page.close()
            for index,command in rows:
                x,y,w,h=_rotated_box(command,width,height,angles.get(number,0))
                # One pixel in from the edge, where drawing the picture back blends it with its surroundings.
                left,top=math.ceil(x*RASTER_SCALE)+1,math.ceil(y*RASTER_SCALE)+1
                right,bottom=math.floor((x+w)*RASTER_SCALE)-1,math.floor((y+h)*RASTER_SCALE)-1
                if right<=left:left=int((x+w/2)*RASTER_SCALE);right=left+1
                if bottom<=top:top=int((y+h/2)*RASTER_SCALE);bottom=top+1
                if picture.crop((left,top,right,bottom)).getextrema()[1]>BLACK:raise ProcessorError('editor_check_failed',index=index)
            picture.close()


def _mark(writer,command,paths):
    """The pypdf stage for one mark, at the file's own page: returns how many words it replaced."""
    from pypdf.annotations import Highlight,Text
    kind=command['type'];page=writer.pages[command['page']-1];width,height=_geometry(page,command)
    if kind in ('add_text','draw','whiteout'):_overlay(page,command)
    elif kind in ('insert_image','signature'):_overlay(page,command,paths[command['input_index']])
    elif kind=='replace_text':return _replace_text(page,command,writer)
    elif kind in ('replace_image','remove_image'):_replace_image(page,command,writer,paths[command['input_index']] if 'input_index' in command else None)
    elif kind=='note':
        x,y=command['x'],height-command['y']
        writer.add_annotation(command['page']-1,Text(rect=(x,max(0,y-22),min(width,x+22),y),text=command['text']))
    elif kind=='highlight':
        x,y,w,h=command['x'],height-command['y'],command['width'],command['height']
        writer.add_annotation(command['page']-1,Highlight(rect=(x,y-h,x+w,y),quad_points=ArrayObject([FloatObject(v) for v in (x,y,x+w,y,x,y-h,x+w,y-h)]),highlight_color=command['color'][1:]))
    return 0


def _turn_appearance(appearance,turn):
    """An annotation's picture is stretched to its /Rect from where its /Matrix leaves it, so a turn is all it needs."""
    old=_numbers(appearance.get('/Matrix'));a,b,c,d,e,f=old if len(old)==6 else (1,0,0,1,0,0)
    appearance[NameObject('/Matrix')]=ArrayObject(FloatObject(v) for v in Transformation((a,b,c,d,e,f)).transform(turn).ctm)


def _unturned(writer,page,seen,copies):
    """Takes a page's turn into its drawing, as every mark is placed on the page as shown. Its notes and fields are not drawing, and go with it.

    A note listed on several pages moves once (`seen`). An appearance may be shared
    with a page turned otherwise, or not at all, which needs it as it stands: a note
    gets a copy turned this far (`copies`), and the original is left alone.
    """
    box=page.mediabox;angle=page.rotation
    turn=Transformation().translate(-float(box.left+box.width/2),-float(box.bottom+box.height/2)).rotate(-angle)
    x,y=zip(turn.apply_on(box.lower_left),turn.apply_on(box.upper_right))
    turn=turn.translate(-min(x),-min(y));spin=Transformation().rotate(-angle)
    def moved(values):
        numbers=_numbers(values)
        return ArrayObject(FloatObject(v) for pair in zip(numbers[::2],numbers[1::2]) for v in turn.apply_on(pair))
    def turned(value,inner=True):
        look=value.get_object()
        if isinstance(look,StreamObject):
            key=id(look),angle
            if key not in copies:
                own=copy.copy(look);own.indirect_reference=None
                _turn_appearance(own,spin);copies[key]=writer._add_object(own)
            return copies[key]
        # One level of states (/Off, /Yes): a dictionary that may be shared too, so a new one.
        return DictionaryObject({name:turned(item,False) for name,item in look.items()}) if inner and isinstance(look,DictionaryObject) else value
    for ref in _held(page,'/Annots',ArrayObject) or ():
        note=ref.get_object();rect=_numbers(note.get('/Rect')) if isinstance(note,DictionaryObject) else []
        if len(rect)!=4 or id(note) in seen:continue
        seen.add(id(note))
        left,right=sorted(rect[::2]);bottom,top=sorted(rect[1::2])
        flags=_held(note,'/F',(NumberObject,FloatObject));upright=flags is not None and int(flags)&NO_ROTATE
        if upright:
            # Held by its top left corner and never turned, on the page as shown.
            x,y=turn.apply_on((left,top));corners=(x,y-top+bottom),(x+right-left,y)
        else:corners=turn.apply_on((left,bottom)),turn.apply_on((right,top))
        (x1,y1),(x2,y2)=corners
        note[NameObject('/Rect')]=ArrayObject(FloatObject(v) for v in (min(x1,x2),min(y1,y2),max(x1,x2),max(y1,y2)))
        for key in ('/QuadPoints','/Vertices','/L','/CL'):
            if _numbers(note.get(key)):note[NameObject(key)]=moved(note[key])
        strokes=_held(note,'/InkList',ArrayObject)
        if strokes:note[NameObject('/InkList')]=ArrayObject(moved(stroke) for stroke in strokes)
        if note.get('/Subtype')=='/Widget':note[NameObject('/MK')]=DictionaryObject({**(_held(note,'/MK',DictionaryObject) or {}),NameObject('/R'):NumberObject((_widget_turn(note)-angle)%360)})
        looks=_held(note,'/AP',DictionaryObject)
        if looks and not upright:note[NameObject('/AP')]=DictionaryObject({name:turned(look) for name,look in looks.items()})
    page.transfer_rotation_to_content()


def _pipeline(paths,commands,out):
    """One file from everything a draft holds. Every stage reads source page numbers: page operations come last.

    (1) the pypdf stage draws each mark, (2) the raster stage turns the pages
    with black-out boxes to pictures, (3) the page stage rotates, deletes and
    orders. Then the file is written and looked at. A page blacked out or
    deleted takes with it whatever else in the file could repeat it.
    """
    from .engine import _pdf_reader,_share_identical_objects,_write_pdf,ProcessorError
    reader=_pdf_reader(paths[0],allow_forms=True)
    writer=PdfWriter();writer.clone_document_from_reader(reader)
    seen=set();copies={}
    for page in writer.pages:
        if page.rotation:_unturned(writer,page,seen,copies)
    deleted=_deleted(commands);raster=raster_pages(commands)
    rows=[{'index':index,'status':'skipped' if command['type']!='delete_page' and command.get('page') in deleted else 'applied','engine':'pdfium' if command['type']=='redact' else 'pypdf'} for index,command in enumerate(commands)]
    replacements=0;form_values={}
    for command in commands:
        kind=command['type']
        if kind=='fill_form':form_values[command['field']]=command['value']
        elif kind in PAGE_COMMANDS or command['page'] in deleted:continue
        # A box is drawn at the raster stage, on a page that must be as simple as any mark asks.
        elif kind=='redact':_geometry(writer.pages[command['page']-1],command)
        else:replacements+=_mark(writer,command,paths)
    if form_values:_fill_forms(writer,form_values)
    # What each page to go could draw, read before it goes.
    gone=set().union(*(_drawings(writer.pages[number-1]) for number in [*raster,*deleted]))
    drawn=_raster_stage(writer,commands,raster,out) if raster else set()
    removed=set()
    for number in deleted:
        page=writer.pages[number-1];removed|=_forget_annotations(writer,page)
        for key in list(page):
            if key!='/Type':del page[key]
    final=_page_stage(writer,commands)
    if raster or deleted:
        _unshare(writer,gone,writer.pages);_carriers(writer,bool(raster))
    _share_identical_objects(writer)
    if raster or deleted:_sweep(writer)
    artifact=_write_pdf(writer,out/'edited.pdf',allow_forms=True)
    reopened=PdfReader(artifact['path']);fields=reopened.get_fields() or {}
    for name,value in form_values.items():
        if name in fields:
            if str(fields[name].get('/V',''))!=value:raise ProcessorError('form_validation_failed')
        elif name not in drawn|removed:raise ProcessorError('form_validation_failed')
    positions={number:index for index,number in enumerate(final)}
    if any(reopened.pages[positions[number]].extract_text().strip() or reopened.pages[positions[number]].get('/Annots') for number in raster):raise ProcessorError('redaction_validation_failed')
    if raster:_check_boxes(artifact['path'],commands,final)
    for index,command in enumerate(commands):
        if command['type']=='fill_form' and command['field'] in removed-fields.keys():rows[index]['status']='skipped'
    warnings=[]
    if replacements:warnings.append('existing_text_simple_standard_fonts_only')
    engine='pypdf/reportlab/pdfium' if raster else 'pypdf/reportlab'
    artifact['metadata']={'engine':engine,'rasterized_pages':raster}
    return [artifact],{'engine':engine,'warnings':warnings,'text_replacements':replacements,'command_features':sorted({COMMAND_FEATURES[c['type']] for c in commands}),'per_command':rows,'rasterized_pages':raster}


def execute(feature,paths,parameters,out,metadata):
    from .engine import ProcessorError
    commands=parameters['commands']
    for index,command in enumerate(commands):
        if command['type'] in UNAPPLIED_COMMANDS:raise ProcessorError('invalid_editor_command',index=index)
    # A list sent whole holds nothing but black-out, and today's web has promised every page as a picture.
    if not parameters.get('combined') and any(c['type']=='redact' for c in commands):return _redact(paths[0],commands,out)
    return _pipeline(paths,commands,out)
