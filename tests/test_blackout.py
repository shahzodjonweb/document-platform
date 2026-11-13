"""Black-out that keeps a page's words: PdfCraft takes out what each box covers, and a page that fails a look becomes a picture, only with consent to it.

Every page here is made up and drawn by the test: no customer's words. The tests
marked REQUIRES_PDFCRAFT run the real binary (CI fetches the Linux build, as
production runs); the rest need none. What a page keeps is checked here by other
means than the stage's own: every carrier of words read out of the file, and the
page rendered before and after outside its boxes.
"""
import json
import math
import os
import re
from pathlib import Path

import numpy
import pypdfium2 as pdfium
import pytest
from pypdf import PdfReader,PdfWriter
from pypdf.annotations import FreeText
from pypdf.generic import ArrayObject,DecodedStreamObject,DictionaryObject,FloatObject,NameObject,NumberObject,StreamObject,TextStringObject
from PIL import Image,ImageDraw
from reportlab.pdfgen.canvas import Canvas

from processors import blackout
from processors.engine import ProcessorError,execute
from processors.helpers import run as helper
from processors.sandbox import helper_sandbox
from processors.text_edit import norm
from tests.test_text_edit import stand_in

REQUIRES_PDFCRAFT=pytest.mark.skipif(not os.environ.get('DOCMASTER_PDFCRAFT_BIN'),reason='needs DOCMASTER_PDFCRAFT_BIN')
W,H=595.28,841.89
PHONE='+998 90 123 45 67'
CARD='8600 1234 5678 9012'
OTHER='+998 91 765 43 21'
# The made-up number's line: Helvetica 11 from x 72 on the baseline 130 points down, after "Phone: ".
FOUND={'x':108,'y':119.5,'width':96,'height':13.8,'text':PHONE}
DRAWN={'x':108,'y':119.5,'width':96,'height':13.8}
# Inside the table: the cell's number, and a box that reaches its border.
CELL={'x':204,'y':340,'width':100,'height':14,'text':OTHER}
BORDER={'x':200,'y':330,'width':130,'height':30}


def sheet(path,pages=1,table=False,size=(W,H),turn=0):
    canvas=Canvas(str(path),pagesize=size)
    for number in range(1,pages+1):
        height=size[1]
        canvas.setFont('Helvetica-Bold',16);canvas.drawString(72,height-72,f'Contact sheet {number}')
        canvas.setFont('Helvetica',11)
        for y,text in ((110,'Name: Example Person'),(130,'Phone: '+PHONE),(150,'Card: '+CARD),(170,'Passport: AA1234567 issued 2020')):canvas.drawString(72,height-y,text)
        if table:
            # One stroked rectangle for the table's outline, as some writers draw it.
            canvas.setLineWidth(1);canvas.rect(70,height-360,300,60,stroke=1,fill=0);canvas.line(70,height-330,370,height-330);canvas.line(200,height-360,200,height-300)
            canvas.drawString(76,height-322,'PINFL');canvas.drawString(206,height-322,'31234567890123')
            canvas.drawString(76,height-352,'Phone');canvas.drawString(206,height-352,OTHER)
        canvas.showPage()
    canvas.save()
    if turn:
        writer=PdfWriter(clone_from=str(path))
        for page in writer.pages:page.rotate(turn)
        writer.write(str(path))
    return path


def form(path,border=True):
    canvas=Canvas(str(path),pagesize=(W,H));canvas.setFont('Helvetica',11);canvas.drawString(72,H-100,'Phone number:')
    style={} if border else {'borderWidth':0,'borderColor':None,'fillColor':None}
    canvas.acroForm.textfield(name='phone',x=160,y=H-110,width=180,height=20,value=PHONE,**({'borderWidth':1} if border else style))
    canvas.acroForm.textfield(name='city',x=160,y=H-150,width=180,height=20,value='Tashkent',borderWidth=1)
    canvas.showPage();canvas.save()
    return path


def noted(path,rect,text='Call '+PHONE):
    sheet(path)
    writer=PdfWriter(clone_from=str(path))
    writer.add_annotation(0,FreeText(text=text,rect=rect,font='Helvetica',font_size='11pt',font_color='000000',border_color='000000',background_color='ffffff'))
    writer.write(str(path))
    return path


def scanned(path,tmp_path):
    """A scan: a picture of the words, and the same words laid out of sight over it, as OCR leaves them."""
    picture=Image.new('RGB',(1240,1754),'white');draw=ImageDraw.Draw(picture)
    for x in range(310,760,30):draw.rectangle((x,250,x+20,290),fill='black')
    picture.save(tmp_path/'scan.png')
    canvas=Canvas(str(path),pagesize=(W,H));canvas.drawImage(str(tmp_path/'scan.png'),0,0,W,H)
    words=canvas.beginText(72,H-130);words.setTextRenderMode(3);words.setFont('Helvetica',19);words.textLine('Phone: '+PHONE);canvas.drawText(words)
    canvas.showPage();canvas.save()
    return path


def pictured(path,tmp_path):
    Image.new('RGB',(120,60),'#3366cc').save(tmp_path/'logo.png')
    canvas=Canvas(str(path),pagesize=(W,H));canvas.setFont('Helvetica',11);canvas.drawString(72,H-130,'Phone: '+PHONE)
    # 300 to 420 across, 200 to 260 down.
    canvas.drawImage(str(tmp_path/'logo.png'),300,H-260,120,60);canvas.showPage();canvas.save()
    return path


def box(page=1,**place):
    return {'type':'redact','page':page,**place}


def send(source,commands,tmp_path,agreed=None,pdfcraft=True,out='out'):
    """A stored draft's send: `agreed` the pages the customer agreed may become pictures, None for no consent at all."""
    parameters={'commands':commands,'combined':True,'accept_rasterization':agreed is not None,**({'raster_pages':agreed} if agreed is not None else {})}
    result=execute('editor.visual',[source],parameters,tmp_path/out,pdfcraft=pdfcraft,vector_blackout=pdfcraft)
    return result,result['artifacts'][0]['path']


def kinds(result):
    return [row['engine'] for row in result['metadata']['per_command']]


def said(path):
    """Every word the file can be read for: its pages' text by pypdf and pdfium, its fields, notes, bookmarks and every stream's bytes."""
    reader=PdfReader(path);found=[]
    found+=[page.extract_text() for page in reader.pages]
    with pdfium.PdfDocument(str(path)) as document:
        for page in document:
            text=page.get_textpage();found.append(text.get_text_range());text.close();page.close()
    for field in (reader.get_fields() or {}).values():found+=[str(field.get(key,'')) for key in ('/V','/DV','/TU')]
    for page in reader.pages:
        for ref in page.get('/Annots') or ():
            note=ref.get_object();found+=[str(note.get(key,'')) for key in ('/Contents','/RC','/T','/Subj','/V')]
    found+=[str(item.title) for item in reader.outline if hasattr(item,'title')] if reader.outline else []
    for number in range(1,int(reader.trailer['/Size'])):
        try:value=reader.get_object(number)
        except Exception:continue
        if isinstance(value,StreamObject):
            try:found.append(value.get_data().decode('latin-1'))
            except Exception:pass
    return norm(' '.join(found))


def look(path,index=0,scale=150/72):
    with pdfium.PdfDocument(str(path)) as document:
        document.init_forms();page=document[index]
        bitmap=page.render(scale=scale)
        try:return numpy.asarray(bitmap.to_pil().convert('RGB'),dtype=numpy.int16)
        finally:bitmap.close();page.close()


def changed_outside(before,after,rects,scale=150/72,pad=1.5):
    """Pixels that changed outside every rect, rects in points from the top left as shown."""
    changes=numpy.abs(look(before)-look(after)).max(axis=2)>40
    for x0,y0,x1,y1 in rects:changes[max(0,int((y0-pad)*scale)):math.ceil((y1+pad)*scale),max(0,int((x0-pad)*scale)):math.ceil((x1+pad)*scale)]=False
    return int(changes.sum())


def black(path,rect,index=0,scale=150/72):
    pixels=look(path,index,scale);x0,y0,x1,y1=rect
    return int(pixels[math.ceil(y0*scale)+1:math.floor(y1*scale)-1,math.ceil(x0*scale)+1:math.floor(x1*scale)-1].max())<=16


def place(command):
    return [command['x'],command['y'],command['x']+command['width'],command['y']+command['height']]


# --- With PdfCraft ---------------------------------------------------------------------------

@REQUIRES_PDFCRAFT
def test_a_found_number_goes_and_the_page_keeps_its_words(tmp_path):
    source=sheet(tmp_path/'sheet.pdf')
    result,path=send(source,[box(**FOUND)],tmp_path)
    assert kinds(result)==['pdfcraft'] and result['metadata']['rasterized_pages']==[] and result['metadata']['engine'].startswith('pdfcraft/')
    words=said(path)
    assert norm(PHONE) not in words,'the number cannot be read out of the file in any way'
    assert all(norm(kept) in words for kept in ('Contact sheet 1','Name: Example Person','Card: '+CARD)),'the rest of the page is still words'
    assert changed_outside(source,path,[place(FOUND)])==0,'nothing outside the box changed'
    assert black(path,[109.92,121.2,201.96,132.2]),'the black stands where PdfCraft found the number'


@REQUIRES_PDFCRAFT
def test_a_drawn_box_takes_the_letters_under_it(tmp_path):
    source=sheet(tmp_path/'sheet.pdf')
    result,path=send(source,[box(**DRAWN)],tmp_path)
    assert kinds(result)==['pdfcraft'] and result['metadata']['rasterized_pages']==[]
    assert norm(PHONE) not in said(path) and norm('Phone:') in said(path)
    assert black(path,place(DRAWN)) and changed_outside(source,path,[place(DRAWN)])==0


@REQUIRES_PDFCRAFT
def test_a_table_border_under_the_box_turns_the_page_to_a_picture_with_consent(tmp_path):
    source=sheet(tmp_path/'table.pdf',table=True)
    assert blackout.check(source,[box(**BORDER)],tmp_path/'check',True)=={1:'others'},'PdfCraft would take the whole table outline'
    with pytest.raises(ProcessorError) as refused:send(source,[box(**BORDER)],tmp_path)
    assert refused.value.code=='rasterization_consent_required' and refused.value.index==0
    result,path=send(source,[box(**BORDER)],tmp_path,agreed=[1],out='agreed')
    assert kinds(result)==['pdfium'] and result['metadata']['rasterized_pages']==[1]
    assert said(path).find(norm(OTHER))<0 and not PdfReader(path).pages[0].extract_text().strip(),'a picture, with no words at all'
    assert black(path,place(BORDER))


@REQUIRES_PDFCRAFT
def test_a_box_inside_a_cell_of_a_one_rectangle_table_is_a_picture_too(tmp_path):
    source=sheet(tmp_path/'table.pdf',table=True)
    assert blackout.check(source,[box(**CELL)],tmp_path/'check',True)=={1:'others'},'the outline holds the cell, so it would go'


@REQUIRES_PDFCRAFT
def test_a_filled_field_under_the_box_goes_with_its_value(tmp_path):
    source=form(tmp_path/'form.pdf')
    whole=box(x=158,y=88,width=184,height=24)
    commands=[whole,{'type':'fill_form','field':'phone','value':'+998 99 000 00 00'},{'type':'fill_form','field':'city','value':'Samarkand'}]
    result,path=send(source,commands,tmp_path)
    assert kinds(result)==['pdfcraft','pypdf','pypdf'] and result['metadata']['rasterized_pages']==[]
    assert [row['status'] for row in result['metadata']['per_command']]==['applied','skipped','applied'],'the field went with the box: it is not filled in'
    fields=PdfReader(path).get_fields()
    assert set(fields)=={'city'} and fields['city']['/V']=='Samarkand'
    assert norm(PHONE) not in said(path) and norm('Phone number:') in said(path)
    assert black(path,place(whole))


def stamped(path,background=False):
    """A note with a picture of its own (/AP): its words, on a blue panel or on nothing."""
    sheet(path);writer=PdfWriter(clone_from=str(path))
    look=DecodedStreamObject();look.set_data((b'q 0 0 1 rg 0 0 200 30 re f Q ' if background else b'')+b'BT /F1 11 Tf 6 10 Td (Call +998 90 123 45 67) Tj ET')
    face=writer._add_object(DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')}))
    look.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Form'),NameObject('/BBox'):ArrayObject([FloatObject(0),FloatObject(0),FloatObject(200),FloatObject(30)]),
                 NameObject('/Resources'):DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):face})})})
    writer.add_annotation(0,DictionaryObject({NameObject('/Type'):NameObject('/Annot'),NameObject('/Subtype'):NameObject('/Square'),NameObject('/F'):NumberObject(4),
        NameObject('/Rect'):ArrayObject([FloatObject(300),FloatObject(H-460),FloatObject(500),FloatObject(H-430)]),NameObject('/Contents'):TextStringObject('Call '+PHONE),NameObject('/AP'):DictionaryObject({NameObject('/N'):writer._add_object(look)})}))
    writer.write(str(path))
    return path


def test_a_note_is_drawn_into_its_page_where_it_showed(tmp_path):
    source=stamped(tmp_path/'note.pdf',background=True)
    assert blackout._flatten(source,tmp_path/'flat.pdf',{1:[(0,box(x=380,y=428,width=60,height=34))]})==set()
    assert not PdfReader(tmp_path/'flat.pdf').pages[0].get('/Annots'),'taken out as a note'
    assert changed_outside(source,tmp_path/'flat.pdf',[])==0,'and drawn exactly where it showed'
    assert blackout._flatten(source,tmp_path/'none.pdf',{1:[(0,box(**DRAWN))]}) is None and not (tmp_path/'none.pdf').exists(),'a box that meets no note writes nothing'


@REQUIRES_PDFCRAFT
def test_a_note_partly_under_the_box_keeps_what_shows_outside_it(tmp_path):
    source=stamped(tmp_path/'note.pdf')
    # Over the number, short of "Call".
    part=box(x=330,y=428,width=170,height=34)
    assert blackout.check(source,[part],tmp_path/'check',True)=={1:'vector'}
    result,path=send(source,[part],tmp_path)
    assert result['metadata']['rasterized_pages']==[] and not PdfReader(path).pages[0].get('/Annots')
    page=norm(PdfReader(path).pages[0].extract_text())
    assert 'Call' in page and page.count(norm(PHONE))==1,'drawn into the page, and only what the box covered went: the page\'s own number stays'
    assert changed_outside(source,path,[place(part)])<=40
    # On a panel, the box takes the whole panel: the page would change outside it.
    assert blackout.check(stamped(tmp_path/'panel.pdf',background=True),[part],tmp_path/'panel',True)=={1:'others'}


@REQUIRES_PDFCRAFT
def test_a_field_partly_under_the_box_is_a_picture(tmp_path):
    # pdfium draws a text field from its value: the field's own picture, drawn into the page, does not match it to the pixel.
    for border in (True,False):
        source=form(tmp_path/f'form-{border}.pdf',border=border)
        assert blackout.check(source,[box(x=200,y=92,width=100,height=16)],tmp_path/f'check-{border}',True)=={1:'others'}


@REQUIRES_PDFCRAFT
def test_a_note_under_the_box_goes_whole(tmp_path):
    source=noted(tmp_path/'note.pdf',(300,H-260,500,H-230))
    cover=box(x=298,y=229,width=204,height=33)
    result,path=send(source,[cover],tmp_path)
    assert result['metadata']['rasterized_pages']==[] and not PdfReader(path).pages[0].get('/Annots')
    assert 'Call' not in json.dumps(said(path)),'its words went with it'
    assert norm(PHONE) in said(path),'the page\'s own number was not under the box, and stays'


@REQUIRES_PDFCRAFT
def test_a_note_elsewhere_that_says_the_words_turns_the_page_to_a_picture(tmp_path):
    source=noted(tmp_path/'note.pdf',(300,H-460,500,H-430))
    assert blackout.check(source,[box(**FOUND)],tmp_path/'check',True)=={1:'left'}
    result,path=send(source,[box(**FOUND)],tmp_path,agreed=[1])
    assert result['metadata']['rasterized_pages']==[1] and norm(PHONE) not in said(path)


@REQUIRES_PDFCRAFT
def test_an_ocr_page_finds_nothing(tmp_path):
    source=scanned(tmp_path/'scan.pdf',tmp_path)
    cover=box(x=145,y=115,width=225,height=30)
    assert blackout.check(source,[cover],tmp_path/'check',True)=={1:'scan'},'words out of sight over a scan: the picture is what shows'
    result,path=send(source,[cover],tmp_path,agreed=[1])
    assert result['metadata']['rasterized_pages']==[1] and kinds(result)==['pdfium']
    assert said(path).find(norm(PHONE))<0 and not PdfReader(path).pages[0].extract_text().strip(),'no words are left to find, out of sight or not'
    assert black(path,place(cover))


@REQUIRES_PDFCRAFT
def test_a_box_over_a_picture_turns_the_page(tmp_path):
    source=pictured(tmp_path/'logo.pdf',tmp_path)
    assert blackout.check(source,[box(x=280,y=190,width=60,height=40)],tmp_path/'check',True)=={1:'image'}
    assert blackout.check(source,[box(**DRAWN)],tmp_path/'apart',True)=={1:'vector'},'a box beside the picture does not touch it'


@REQUIRES_PDFCRAFT
def test_pages_keep_or_turn_on_their_own(tmp_path):
    source=sheet(tmp_path/'two.pdf',pages=2,table=True)
    commands=[box(1,**FOUND),box(2,**BORDER)]
    with pytest.raises(ProcessorError) as refused:send(source,commands,tmp_path,agreed=[])
    assert refused.value.code=='rasterization_consent_required' and refused.value.index==1,'consent to no page is consent to none'
    result,path=send(source,commands,tmp_path,agreed=[2],out='agreed')
    assert kinds(result)==['pdfcraft','pdfium'] and result['metadata']['rasterized_pages']==[2]
    reader=PdfReader(path)
    assert norm('Contact sheet 1') in norm(reader.pages[0].extract_text()) and not reader.pages[1].extract_text().strip()
    assert norm(PHONE) not in said(path)
    # A send quoted before pages were told apart agreed to every page with a box.
    old=execute('editor.visual',[source],{'commands':commands,'combined':True,'accept_rasterization':True},tmp_path/'old',pdfcraft=True,vector_blackout=True)
    assert old['metadata']['rasterized_pages']==[1,2],'and is not tried again: every page it agreed to is a picture'


@REQUIRES_PDFCRAFT
def test_a_box_on_a_turned_page_is_placed_as_shown(tmp_path):
    source=sheet(tmp_path/'turned.pdf',turn=90)
    # Turned a quarter clockwise, the page is H wide and the line that was 130 points down stands 130 points in from its right.
    shown=box(x=H-133.3,y=108,width=13.8,height=96)
    result,path=send(source,[shown],tmp_path)
    assert result['metadata']['rasterized_pages']==[] and norm(PHONE) not in said(path) and norm('Example Person') in said(path)


@REQUIRES_PDFCRAFT
def test_a_bookmark_that_says_the_words_goes_and_others_stay(tmp_path):
    source=sheet(tmp_path/'marked.pdf');writer=PdfWriter(clone_from=str(source));writer.add_outline_item('Call '+PHONE,0);writer.write(str(source))
    _,path=send(source,[box(**FOUND)],tmp_path)
    assert not PdfReader(path).outline and norm(PHONE) not in said(path)
    plain=sheet(tmp_path/'plain.pdf');writer=PdfWriter(clone_from=str(plain));writer.add_outline_item('Contacts',0);writer.write(str(plain))
    _,path=send(plain,[box(**FOUND)],tmp_path,out='plain')
    assert [item.title for item in PdfReader(path).outline]==['Contacts']


@REQUIRES_PDFCRAFT
def test_the_check_says_what_the_send_does_and_no_words(tmp_path):
    source=sheet(tmp_path/'two.pdf',pages=2,table=True)
    commands=[box(1,**FOUND),box(2,**BORDER)]
    answer=helper_sandbox('editor.blackout',[source],{'commands':commands},tmp_path/'check',pdfcraft=True)
    assert answer=={'pages':{'1':'vector','2':'others'}}
    result,_=send(source,commands,tmp_path,agreed=[2])
    assert result['metadata']['rasterized_pages']==[2]
    assert norm(PHONE) not in norm(json.dumps(result['metadata'])) and 'Phone' not in json.dumps(result['metadata'])


@REQUIRES_PDFCRAFT
def test_a_check_with_a_box_its_page_cannot_hold_says_so_for_that_page_alone(tmp_path):
    source=sheet(tmp_path/'two.pdf',pages=2)
    outside=box(2,x=W-10,y=100,width=50,height=20)
    assert blackout.check(source,[box(1,**FOUND),outside],tmp_path/'check',True)=={1:'vector',2:'invalid'}


@REQUIRES_PDFCRAFT
def test_a_box_made_by_finding_words_is_black_whole(tmp_path):
    # Its words are a part of what it covers: the whole box goes, whatever it was made for.
    source=sheet(tmp_path/'sheet.pdf')
    line=box(x=70,y=119.5,width=140,height=13.8,text='Phone')
    result,path=send(source,[line],tmp_path)
    assert result['metadata']['rasterized_pages']==[] and norm(PHONE) not in said(path) and norm('Phone') not in said(path)
    assert black(path,place(line))


def linked(path,uri):
    sheet(path);writer=PdfWriter(clone_from=str(path))
    writer.add_annotation(0,DictionaryObject({NameObject('/Type'):NameObject('/Annot'),NameObject('/Subtype'):NameObject('/Link'),
        NameObject('/Rect'):ArrayObject([FloatObject(300),FloatObject(H-560),FloatObject(400),FloatObject(H-540)]),
        NameObject('/A'):DictionaryObject({NameObject('/S'):NameObject('/URI'),NameObject('/URI'):TextStringObject(uri)})}))
    writer.write(str(path))
    return path


@REQUIRES_PDFCRAFT
def test_a_page_whose_other_notes_say_any_word_that_went_is_a_picture(tmp_path):
    # A link's address, a note's author and a note that says part of the number all keep the words, so the page goes whole.
    name=box(x=72,y=99.5,width=160,height=13.8)
    assert blackout.check(linked(tmp_path/'link.pdf','mailto:example.person@example.org'),[name],tmp_path/'link',True)=={1:'left'}
    authored=sheet(tmp_path/'author.pdf');writer=PdfWriter(clone_from=str(authored))
    writer.add_annotation(0,DictionaryObject({NameObject('/Type'):NameObject('/Annot'),NameObject('/Subtype'):NameObject('/Text'),
        NameObject('/Rect'):ArrayObject([FloatObject(300),FloatObject(H-560),FloatObject(322),FloatObject(H-538)]),
        NameObject('/Contents'):TextStringObject('Checked'),NameObject('/T'):TextStringObject('Example Person')}))
    writer.write(str(authored))
    assert blackout.check(authored,[name],tmp_path/'author',True)=={1:'left'},'the name went from the page'
    assert blackout.check(noted(tmp_path/'part.pdf',(300,H-460,500,H-430),'Call 90 123 45 67'),[box(**FOUND)],tmp_path/'part',True)=={1:'left'}
    assert blackout.check(linked(tmp_path/'away.pdf','https://example.org/'),[box(**FOUND)],tmp_path/'away',True)=={1:'vector'}


@REQUIRES_PDFCRAFT
def test_a_bookmark_that_says_a_word_of_lines_that_went_goes(tmp_path):
    source=sheet(tmp_path/'marked.pdf');writer=PdfWriter(clone_from=str(source));writer.add_outline_item('Example',0);writer.write(str(source))
    # Two lines in one box: "Name: Example Person" and the number.
    _,path=send(source,[box(x=70,y=99.5,width=150,height=34)],tmp_path)
    assert not PdfReader(path).outline


@REQUIRES_PDFCRAFT
def test_a_small_drawing_a_box_touches_is_a_change_outside_it(tmp_path):
    # A minus sign drawn as a shape, 6 by 1.2 points, half a point of it under the box.
    path=tmp_path/'minus.pdf';canvas=Canvas(str(path),pagesize=(W,H));canvas.setFont('Helvetica',11);canvas.drawString(72,H-130,'Phone: '+PHONE)
    canvas.rect(203.5,H-126,6,1.2,stroke=0,fill=1);canvas.showPage();canvas.save()
    assert blackout.check(path,[box(**DRAWN)],tmp_path/'check',True)=={1:'others'}


def test_a_turned_page_whose_frame_does_not_start_at_the_corner_is_a_picture_not_a_refusal(tmp_path):
    from pypdf.generic import RectangleObject
    source=sheet(tmp_path/'offset.pdf');writer=PdfWriter(clone_from=str(source))
    page=writer.pages[0];page.mediabox=RectangleObject([10,10,W+10,H+10]);page.rotate(90);writer.write(str(source))
    shown=box(x=H-140,y=118,width=13.8,height=96)
    result,_=send(source,[shown],tmp_path,agreed=[1],pdfcraft=False)
    assert result['metadata']['rasterized_pages']==[1],'with PdfCraft off it is made as before'
    if os.environ.get('DOCMASTER_PDFCRAFT_BIN'):
        assert blackout.check(source,[shown],tmp_path/'check',True)=={1:'invalid'}
        result,_=send(source,[shown],tmp_path,agreed=[1],out='on')
        assert result['metadata']['rasterized_pages']==[1]


# --- Without PdfCraft -----------------------------------------------------------------------

def test_without_pdfcraft_every_page_with_a_box_is_a_picture(tmp_path,monkeypatch):
    monkeypatch.delenv('DOCMASTER_PDFCRAFT_BIN',raising=False)
    source=sheet(tmp_path/'sheet.pdf',pages=2)
    assert blackout.check(source,[box(1,**FOUND),box(2,**DRAWN)],tmp_path/'check',True)=={1:'engine',2:'engine'}
    result,path=send(source,[box(1,**FOUND)],tmp_path,agreed=[1])
    assert kinds(result)==['pdfium'] and result['metadata']['rasterized_pages']==[1] and not PdfReader(path).pages[0].extract_text().strip()
    result,_=send(source,[box(1,**FOUND)],tmp_path,agreed=[1],pdfcraft=False,out='off')
    assert result['metadata']['rasterized_pages']==[1],'the switch off is the same'


def test_a_box_under_another_change_of_the_send_is_a_picture_without_asking_pdfcraft(tmp_path):
    words={'type':'add_text','page':1,'x':110,'y':118,'text':'over it','font_size':12}
    beside={'type':'add_text','page':1,'x':300,'y':118,'text':'beside it','font_size':12}
    turned={'type':'replace_image','page':1,'image_index':0,'input_index':1}
    assert blackout.marked([box(**DRAWN),words])=={1} and blackout.marked([box(**DRAWN),beside])==set()
    assert blackout.marked([box(**DRAWN),turned])=={1},'a picture found again by its number after PdfCraft wrote the file'
    retyped={'type':'edit_text','page':1,'x':72,'y':119.5,'width':30,'height':13.8,'original':'Phone:','text':'Tel:'}
    assert blackout.marked([box(**DRAWN),retyped])=={1},'new words may run on into the box'
    assert blackout.marked([box(**DRAWN),{**words,'page':2}])==set() and blackout.marked([box(**DRAWN),words,{'type':'delete_page','page':1}])==set()
    done=blackout.run(sheet(tmp_path/'sheet.pdf'),[box(**DRAWN),words],tmp_path/'run',True,blackout.marked([box(**DRAWN),words]))
    assert done.outcome()=={1:'skip'}


def test_a_pdfcraft_that_answers_nonsense_leaves_every_page_to_a_picture(tmp_path,monkeypatch):
    monkeypatch.setenv('DOCMASTER_PDFCRAFT_BIN',str(stand_in(tmp_path,'print("not json")')))
    source=sheet(tmp_path/'sheet.pdf')
    assert blackout.check(source,[box(**FOUND)],tmp_path/'check',True)=={1:'refused'}
    with pytest.raises(ProcessorError) as refused:send(source,[box(**FOUND)],tmp_path)
    assert refused.value.code=='rasterization_consent_required'


def test_a_pdfcraft_that_refuses_the_marks_leaves_the_page_to_a_picture(tmp_path,monkeypatch):
    # Answers the look (no pictures, nothing found) and refuses everything after.
    body=('steps=json.load(open(sys.argv[sys.argv.index("--script")+1]))\n'
          'look=steps[1]["tool"]=="page_images"\n'
          'print(json.dumps({"ok":look,"steps":[{"status":"ok" if look else "error","result":[{"images":[],"matches":[]}]} for _ in steps]}))')
    monkeypatch.setenv('DOCMASTER_PDFCRAFT_BIN',str(stand_in(tmp_path,body)))
    assert blackout.check(sheet(tmp_path/'sheet.pdf'),[box(**DRAWN)],tmp_path/'check',True)=={1:'refused'}


def test_the_helper_takes_black_out_boxes_alone(tmp_path):
    source=sheet(tmp_path/'sheet.pdf')
    for parameters in ({},{'commands':[]},{'commands':[{'type':'note','page':1,'x':1,'y':1,'text':'n'}]}):
        with pytest.raises(ProcessorError) as refused:helper('editor.blackout',[str(source)],parameters,tmp_path/'out')
        assert refused.value.code=='invalid_parameters'
    with pytest.raises(ProcessorError) as refused:helper('editor.inspect',[str(source)],{'commands':[box(**DRAWN)]},tmp_path/'out')
    assert refused.value.code=='invalid_operation'


def test_consented_pages_are_checked_like_any_parameter(tmp_path):
    from processors.editor import normalize
    commands=[box(**DRAWN)];meta=[{'page_count':2,'kind':'pdf'}]
    assert normalize('editor.visual',{'commands':commands,'combined':True,'accept_rasterization':True,'raster_pages':[2,1]},meta)['raster_pages']==[1,2]
    for bad in ([3],[1,1],'1',[True],[0]):
        with pytest.raises(ProcessorError) as refused:normalize('editor.visual',{'commands':commands,'combined':True,'accept_rasterization':True,'raster_pages':bad},meta)
        assert refused.value.code=='invalid_parameters'
    with pytest.raises(ProcessorError):normalize('editor.redact',{'commands':commands,'accept_rasterization':True,'raster_pages':[1]},meta)
    # A send no longer refuses black-out without consent beforehand: whether a page needs it is known once PdfCraft has tried.
    assert normalize('editor.visual',{'commands':commands,'combined':True,'accept_rasterization':False},meta)['commands']==[{**box(**DRAWN)}]
