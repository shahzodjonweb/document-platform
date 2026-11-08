"""The combined editor job: every kind in one file, in order, marks in the source frame, and a page that goes leaves nothing behind."""
import io
import pytest
import pypdfium2 as pdfium
from PIL import Image
from pypdf import PdfReader,PdfWriter
from pypdf.annotations import FreeText
from pypdf.generic import ArrayObject,DecodedStreamObject,DictionaryObject,NameObject,NullObject,NumberObject,StreamObject,TextStringObject
from reportlab.lib.colors import HexColor
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.utils import ImageReader
from processors import editor
from processors.editor import FIELDS,normalize,overflowing,raster_pages
from processors.engine import ProcessorError,execute
from processors.sandbox import execute_sandbox

W,H=400,600
BOX={'x':20,'y':30,'width':100,'height':40}


def source(tmp_path,pages=3,name='source.pdf'):
    """Pages that say which they are, near the top left: a box at BOX covers the words."""
    path=tmp_path/name;canvas=Canvas(str(path),pagesize=(W,H),pageCompression=0)
    for number in range(1,pages+1):
        canvas.setFont('Helvetica',14);canvas.drawString(25,H-55,f'PAGE-{number}-WORDS');canvas.showPage()
    canvas.save()
    return path


def picture(color=(200,30,30),size=(40,40)):
    return ImageReader(Image.new('RGB',size,color))


def photo(tmp_path,color=(30,30,200)):
    path=tmp_path/'photo.png';Image.new('RGB',(60,60),color).save(path)
    return path


def run(path,commands,tmp_path,images=(),accept=True,out='out'):
    result=execute('editor.visual',[path,*images],{'commands':commands,'accept_rasterization':accept,'combined':True},tmp_path/out)
    return result,PdfReader(result['artifacts'][0]['path'])


def texts(reader):
    return [page.extract_text() for page in reader.pages]


def everything_in(path):
    """Every object the file holds, opened up: what anyone with the file could read out of it."""
    reader=PdfReader(path);parts=[]
    for number in range(1,int(reader.trailer['/Size'])):
        try:value=reader.get_object(number)
        except Exception:continue
        if value is None:continue
        if isinstance(value,StreamObject):parts.append(value.get_data().decode('latin1'))
        parts.append(repr({key:item for key,item in value.items() if key!='__streamdata__'}) if isinstance(value,dict) else repr(value))
    return '\n'.join(parts)


def rendered(reader_path,index,scale=1):
    with pdfium.PdfDocument(str(reader_path)) as document:
        page=document[index];bitmap=page.render(scale=scale)
        try:return bitmap.to_pil().convert('RGB')
        finally:bitmap.close();page.close()


def path_of(result):
    return result['artifacts'][0]['path']


def test_a_reorder_alone_is_a_whole_job(tmp_path):
    result,reader=run(source(tmp_path),[{'type':'reorder','order':[3,1,2]}],tmp_path)
    assert [t.strip() for t in texts(reader)]==['PAGE-3-WORDS','PAGE-1-WORDS','PAGE-2-WORDS']
    assert result['metadata']['per_command']==[{'index':0,'status':'applied','engine':'pypdf'}] and result['metadata']['rasterized_pages']==[]
    assert result['artifacts'][0]['page_count']==3


@pytest.mark.parametrize('angle,expected',[(90,(600-30-40,20)),(180,(400-20-100,600-30-40)),(270,(30,400-20-100))])
def test_a_mark_is_placed_on_the_page_as_it_was_and_turns_with_it(tmp_path,angle,expected):
    mark={'type':'whiteout','page':2,**BOX,'color':'#FF0000'}
    result,reader=run(source(tmp_path),[{'type':'rotate_page','page':2,'angle':angle},mark],tmp_path)
    image=rendered(path_of(result),1)
    x,y=expected;w,h=(40,100) if angle%180 else (100,40)
    assert image.getpixel((x+w//2,y+h//2))==(255,0,0)
    assert image.getpixel((x-6,y+h//2))!=(255,0,0) and image.getpixel((x+w+6,y+h//2))!=(255,0,0)


def test_rotate_then_delete_with_marks_all_in_source_numbers(tmp_path):
    commands=[{'type':'add_text','page':1,'x':20,'y':100,'text':'ON-ONE'},{'type':'add_text','page':2,'x':20,'y':100,'text':'ON-TWO'},
              {'type':'add_text','page':3,'x':20,'y':100,'text':'ON-THREE'},{'type':'rotate_page','page':3,'angle':90},{'type':'delete_page','page':1},{'type':'delete_page','page':2}]
    result,reader=run(source(tmp_path,4),commands,tmp_path)
    assert len(reader.pages)==2
    assert 'ON-THREE' in texts(reader)[0] and 'PAGE-3-WORDS' in texts(reader)[0] and 'PAGE-4-WORDS' in texts(reader)[1]
    assert reader.pages[0].rotation==90 and reader.pages[1].rotation==0
    assert [row['status'] for row in result['metadata']['per_command']]==['skipped','skipped','applied','applied','applied','applied']
    held=everything_in(path_of(result))
    assert 'PAGE-1-WORDS' not in held and 'PAGE-2-WORDS' not in held and 'ON-TWO' not in held,'a deleted page is not hidden, it is gone'


def test_a_mark_that_could_not_fit_a_deleted_page_does_not_fail_the_job(tmp_path):
    commands=[{'type':'add_text','page':1,'x':390,'y':10,'text':'x'*300},{'type':'delete_page','page':1}]
    result,reader=run(source(tmp_path),commands,tmp_path)
    assert len(reader.pages)==2 and result['metadata']['per_command'][0]['status']=='skipped'


def test_delete_and_reorder_together_keep_the_order_asked(tmp_path):
    commands=[{'type':'reorder','order':[4,3,2,1]},{'type':'delete_page','page':3}]
    _,reader=run(source(tmp_path,4),commands,tmp_path)
    assert [t.strip() for t in texts(reader)]==['PAGE-4-WORDS','PAGE-2-WORDS','PAGE-1-WORDS']


def test_black_out_turns_only_its_page_to_a_picture(tmp_path):
    result,reader=run(source(tmp_path),[{'type':'redact','page':2,**BOX}],tmp_path)
    assert result['metadata']['rasterized_pages']==[2] and result['metadata']['per_command'][0]['engine']=='pdfium'
    assert result['artifacts'][0]['metadata']['rasterized_pages']==[2]
    assert 'PAGE-1-WORDS' in texts(reader)[0] and texts(reader)[1].strip()=='' and 'PAGE-3-WORDS' in texts(reader)[2]
    assert 'PAGE-2-WORDS' not in everything_in(path_of(result)),'the words under the box are out of the file, not behind a picture'
    assert [path.name for path in (tmp_path/'out').iterdir()]==['edited.pdf'],'the stage file is gone'
    image=rendered(path_of(result),1,2)
    assert image.getpixel((2*(20+50),2*(30+20)))==(0,0,0)


def test_black_out_takes_what_was_marked_before_it_and_stays_where_its_page_went(tmp_path):
    commands=[{'type':'add_text','page':2,'x':20,'y':200,'text':'BURNT-IN'},{'type':'redact','page':2,**BOX},{'type':'rotate_page','page':2,'angle':90},{'type':'reorder','order':[2,3,1]},{'type':'delete_page','page':3}]
    result,reader=run(source(tmp_path),commands,tmp_path)
    assert len(reader.pages)==2 and texts(reader)[0].strip()=='' and 'PAGE-1-WORDS' in texts(reader)[1]
    assert 'BURNT-IN' not in everything_in(path_of(result)) and reader.pages[0].rotation==90
    image=rendered(path_of(result),0)
    assert image.getpixel((600-30-20,20+50))==(0,0,0)
    assert image.size==(600,400)
    # The mark itself shows, as a picture, turned with its page: lines of ink beside the box.
    assert image.crop((600-200-20,20,600-200,20+160)).convert('L').getextrema()[0]<100


def turned(tmp_path,angle=90):
    writer=PdfWriter(clone_from=source(tmp_path));writer.pages[0].rotate(angle)
    path=tmp_path/'turned.pdf';writer.write(path)
    return path


def test_a_page_the_file_shows_turned_is_marked_as_it_is_shown(tmp_path):
    mark={'type':'whiteout','page':1,**BOX,'color':'#FF0000'}
    result,reader=run(turned(tmp_path),[mark,{'type':'redact','page':1,'x':200,'y':200,'width':100,'height':100}],tmp_path)
    image=rendered(path_of(result),0)
    assert image.size==(600,400) and image.getpixel((70,50))==(255,0,0) and image.getpixel((250,250))==(0,0,0)
    assert texts(reader)[0].strip()==''


def test_a_page_the_file_shows_turned_can_be_turned_further(tmp_path):
    result,reader=run(turned(tmp_path),[{'type':'whiteout','page':1,**BOX,'color':'#FF0000'},{'type':'rotate_page','page':1,'angle':90}],tmp_path)
    image=rendered(path_of(result),0)
    assert image.size==(400,600) and image.getpixel((400-30-20,20+50))==(255,0,0)


def test_a_box_on_a_page_with_a_crop_is_refused_like_any_mark(tmp_path):
    writer=PdfWriter(clone_from=source(tmp_path));writer.pages[0].cropbox.left=10
    path=tmp_path/'cropped.pdf';writer.write(path)
    with pytest.raises(ProcessorError) as caught:run(path,[{'type':'redact','page':1,**BOX}],tmp_path)
    assert caught.value.code=='unsupported_page_geometry'


def test_a_box_on_a_deleted_page_asks_no_consent_and_draws_nothing(tmp_path):
    commands=[{'type':'redact','page':2,**BOX},{'type':'delete_page','page':2}]
    assert raster_pages(commands)==[]
    assert normalize('editor.visual',{'commands':commands,'combined':True})['accept_rasterization'] is False
    result,reader=run(source(tmp_path),commands,tmp_path,accept=False)
    assert result['metadata']['rasterized_pages']==[] and result['metadata']['per_command'][0]['status']=='skipped' and len(reader.pages)==2


def test_a_box_that_will_really_be_drawn_needs_consent(tmp_path):
    with pytest.raises(ProcessorError) as caught:run(source(tmp_path),[{'type':'redact','page':2,**BOX}],tmp_path,accept=False)
    assert caught.value.code=='rasterization_consent_required'


def test_a_failed_look_at_the_finished_file_names_the_box_and_leaves_no_file(tmp_path,monkeypatch):
    real=editor._blacked_out
    monkeypatch.setattr(editor,'_blacked_out',lambda document,number,commands,rendered:real(document,number,[],rendered))
    out=tmp_path/'out'
    with pytest.raises(ProcessorError) as caught:
        execute('editor.visual',[source(tmp_path)],{'commands':[{'type':'note','page':1,'x':1,'y':1,'text':'n'},{'type':'redact','page':2,**BOX}],'accept_rasterization':True,'combined':True},out)
    assert caught.value.code=='editor_check_failed' and caught.value.index==1 and not list(out.iterdir())


@pytest.fixture
def form(tmp_path):
    path=tmp_path/'form.pdf';canvas=Canvas(str(path),pagesize=(W,H),pageCompression=0)
    for number in (1,2):
        canvas.setFont('Helvetica',14);canvas.drawString(25,H-55,f'PAGE-{number}-WORDS')
        canvas.acroForm.textfield(name=f'field{number}',value=f'VALUE-{number}',x=20,y=300,width=200,height=30)
        canvas.showPage()
    canvas.save()
    return path


def test_a_field_under_black_out_keeps_no_value_in_the_form(tmp_path,form):
    result,reader=run(form,[{'type':'redact','page':1,**BOX}],tmp_path)
    assert set(reader.get_fields())=={'field2'} and not reader.pages[0].get('/Annots')
    held=everything_in(path_of(result))
    assert 'VALUE-1' not in held and 'PAGE-1-WORDS' not in held and 'VALUE-2' in held


def test_one_field_across_two_pages_keeps_its_value_while_a_page_still_shows_it(tmp_path):
    writer=PdfWriter(clone_from=source(tmp_path))
    parent=writer._add_object(DictionaryObject({NameObject('/T'):TextStringObject('group'),NameObject('/FT'):NameObject('/Tx'),NameObject('/V'):TextStringObject('SHARED-VALUE'),NameObject('/Kids'):ArrayObject()}))
    for index in (0,1):
        widget=writer._add_object(DictionaryObject({NameObject('/Type'):NameObject('/Annot'),NameObject('/Subtype'):NameObject('/Widget'),NameObject('/Rect'):ArrayObject([NumberObject(20),NumberObject(300),NumberObject(200),NumberObject(330)]),NameObject('/Parent'):parent}))
        parent.get_object()['/Kids'].append(widget)
        writer.pages[index][NameObject('/Annots')]=ArrayObject([widget])
    writer._root_object[NameObject('/AcroForm')]=DictionaryObject({NameObject('/Fields'):ArrayObject([parent])})
    path=tmp_path/'kids.pdf';writer.write(path)
    result,reader=run(path,[{'type':'redact','page':1,**BOX}],tmp_path)
    assert 'group' in reader.get_fields() and len(reader.pages[1]['/Annots'])==1 and 'SHARED-VALUE' in everything_in(path_of(result))
    result,reader=run(path,[{'type':'redact','page':1,**BOX},{'type':'delete_page','page':2}],tmp_path,out='both')
    assert not reader.get_fields() and 'SHARED-VALUE' not in everything_in(path_of(result))


def test_a_deleted_page_takes_its_field_and_a_value_set_on_it_is_not_held_against_the_job(tmp_path,form):
    commands=[{'type':'fill_form','field':'field1','value':'NEW-VALUE'},{'type':'fill_form','field':'field2','value':'KEPT-VALUE'},{'type':'delete_page','page':1}]
    result,reader=run(form,commands,tmp_path)
    assert {name:str(field['/V']) for name,field in reader.get_fields().items()}=={'field2':'KEPT-VALUE'}
    assert [row['status'] for row in result['metadata']['per_command']]==['skipped','applied','applied']
    held=everything_in(path_of(result))
    assert 'NEW-VALUE' not in held and 'VALUE-1' not in held


def test_a_note_on_a_page_that_goes_is_gone_with_it(tmp_path):
    base=source(tmp_path);writer=PdfWriter(clone_from=base)
    writer.add_annotation(0,FreeText(text='NOTE-ON-ONE',rect=(20,300,200,340)))
    writer.add_annotation(1,FreeText(text='NOTE-ON-TWO',rect=(20,300,200,340)))
    writer.add_annotation(2,FreeText(text='NOTE-ON-THREE',rect=(20,300,200,340)))
    path=tmp_path/'notes.pdf';writer.write(path)
    result,reader=run(path,[{'type':'redact','page':1,**BOX},{'type':'delete_page','page':2}],tmp_path)
    held=everything_in(path_of(result))
    assert 'NOTE-ON-ONE' not in held and 'NOTE-ON-TWO' not in held and 'NOTE-ON-THREE' in held


def test_bookmarks_go_with_black_out_and_a_deletion_keeps_them(tmp_path):
    writer=PdfWriter(clone_from=source(tmp_path));writer.add_outline_item('TITLE-OF-CHAPTER',0);writer.add_outline_item('TITLE-OF-OTHER',1)
    path=tmp_path/'outline.pdf';writer.write(path)
    result,reader=run(path,[{'type':'redact','page':1,**BOX}],tmp_path)
    held=everything_in(path_of(result))
    assert 'TITLE-OF-CHAPTER' not in held and not reader.outline
    result,reader=run(path,[{'type':'delete_page','page':1}],tmp_path,out='deleted')
    assert 'PAGE-1-WORDS' not in everything_in(path_of(result)),'a bookmark pointing at the page does not keep it'
    assert [item.title for item in reader.outline]==['TITLE-OF-CHAPTER','TITLE-OF-OTHER']


def test_a_picture_shared_through_common_resources_goes_with_the_only_page_that_drew_it(tmp_path):
    base=tmp_path/'plain.pdf';canvas=Canvas(str(base),pagesize=(W,H),pageCompression=0)
    canvas.drawImage(picture(),20,H-120,80,80);canvas.setFont('Helvetica',14);canvas.drawString(25,H-200,'ONE');canvas.showPage()
    canvas.setFont('Helvetica',14);canvas.drawString(25,H-55,'TWO');canvas.showPage();canvas.save()
    writer=PdfWriter(clone_from=base)
    first,second=writer.pages[0],writer.pages[1]
    shared=DictionaryObject(first['/Resources']);shared[NameObject('/Font')]=second['/Resources']['/Font'].clone(writer)
    reference=writer._add_object(shared);first[NameObject('/Resources')]=reference;second[NameObject('/Resources')]=reference
    path=tmp_path/'shared.pdf';writer.write(path)
    assert len(PdfReader(path).pages[1].images)==1,'the fixture shares it, as the Qt PDF writer does'
    result,reader=run(path,[{'type':'redact','page':1,'x':15,'y':35,'width':90,'height':90}],tmp_path)
    assert len(reader.pages[1].images)==0 and 'TWO' in texts(reader)[1]
    images=[reader.get_object(n) for n in range(1,int(reader.trailer['/Size']))]
    assert sum(1 for value in images if isinstance(value,dict) and value.get('/Subtype')=='/Image')<=2,'only the new picture and its mask'
    assert (200,30,30) not in {color for _,color in rendered(path_of(result),0).getcolors(1<<20)}


def test_a_picture_still_drawn_on_a_page_that_stays_stays(tmp_path):
    base=tmp_path/'two.pdf';canvas=Canvas(str(base),pagesize=(W,H),pageCompression=0)
    canvas.drawImage(picture(),20,H-120,80,80);canvas.showPage()
    canvas.drawImage(picture(),20,H-120,80,80);canvas.showPage();canvas.save()
    result,reader=run(base,[{'type':'delete_page','page':1}],tmp_path)
    assert len(reader.pages)==1 and len(reader.pages[0].images)==1


def full_fixture(tmp_path):
    path=tmp_path/'full.pdf';canvas=Canvas(str(path),pagesize=(W,H),pageCompression=0)
    for number in range(1,7):
        canvas.setFont('Helvetica',14);canvas.drawString(25,H-55,f'PAGE-{number}-WORDS')
        if number in (2,3):canvas.drawImage(picture(),200,H-300,100,100)
        if number==4:canvas.acroForm.textfield(name='name',value='',x=20,y=300,width=200,height=30)
        canvas.showPage()
    canvas.save()
    return path


KINDS={
 'add_text':{'type':'add_text','page':1,'x':20,'y':100,'text':'Yangi matn','font':'serif','bold':True},
 'highlight':{'type':'highlight','page':1,'x':20,'y':120,'width':100,'height':20},
 'note':{'type':'note','page':1,'x':20,'y':150,'text':'Eslatma'},
 'draw':{'type':'draw','page':1,'points':[[20,200],[100,240]]},
 'fill_form':{'type':'fill_form','field':'name','value':'Ali'},
 'signature':{'type':'signature','page':1,'x':200,'y':200,'width':60,'height':60,'input_index':1},
 'insert_image':{'type':'insert_image','page':1,'x':200,'y':300,'width':60,'height':60,'input_index':1},
 'replace_text':{'type':'replace_text','page':5,'find':'PAGE-5','replacement':'PAGE-E'},
 'replace_image':{'type':'replace_image','page':2,'image_index':0,'input_index':1},
 'remove_image':{'type':'remove_image','page':3,'image_index':0},
 'redact':{'type':'redact','page':6,**BOX},
 # Over the page's own words, where the web puts a line's box (0.95 of the size above the baseline, 0.3 below).
 'edit_text':{'type':'edit_text','page':1,'x':25,'y':55-.95*14,'width':stringWidth('PAGE-1-WORDS','Helvetica',14),'height':1.25*14,'original':'PAGE-1-WORDS','text':'PAGE-1-EDITED'},
 'whiteout':{'type':'whiteout','page':1,'x':20,'y':400,'width':50,'height':20},
 'rotate_page':{'type':'rotate_page','page':1,'angle':90},
 'delete_page':{'type':'delete_page','page':5},
 'reorder':{'type':'reorder','order':[6,5,4,3,2,1]},
}


def test_the_table_covers_every_kind():
    assert set(KINDS)==set(FIELDS)


@pytest.mark.parametrize('kind',sorted(KINDS))
def test_each_kind_alone_is_a_job(kind,tmp_path):
    result,reader=run(full_fixture(tmp_path),[KINDS[kind]],tmp_path,[photo(tmp_path)])
    # With PdfCraft's switch off (as here) a change to the page's own words is covered and retyped.
    assert result['metadata']['per_command']==[{'index':0,'status':'applied','engine':{'redact':'pdfium','edit_text':'covered'}.get(kind,'pypdf')}]
    assert len(reader.pages)==(5 if kind=='delete_page' else 6)


def test_every_kind_runs_in_one_job(tmp_path):
    commands=[KINDS[kind] for kind in KINDS if kind!='replace_text']
    result,reader=run(full_fixture(tmp_path),commands,tmp_path,[photo(tmp_path)])
    assert len(reader.pages)==5 and result['metadata']['rasterized_pages']==[6]
    assert all(row['status']=='applied' for row in result['metadata']['per_command'])
    final=texts(reader)
    assert final[0].strip()=='' and 'PAGE-4-WORDS' in final[1] and 'PAGE-1-EDITED' in final[4] and 'Yangi matn' in final[4]
    assert str(reader.get_fields()['name']['/V'])=='Ali' and reader.pages[4].rotation==90
    assert len(reader.pages[2].images)==0 and len(reader.pages[3].images)==1
    assert {str(annotation.get_object()['/Subtype']) for annotation in reader.pages[4]['/Annots']}=={'/Highlight','/Text'}


def test_edit_text_is_applied_and_a_bad_one_says_which_change(tmp_path):
    commands=[KINDS['note'],KINDS['edit_text']]
    result,reader=run(source(tmp_path),commands,tmp_path)
    assert result['metadata']['per_command'][1]=={'index':1,'status':'applied','engine':'covered'} and 'PAGE-1-EDITED' in texts(reader)[0]
    result=execute_sandbox('editor.visual',[source(tmp_path,name='again.pdf')],{'commands':commands,'combined':True},tmp_path/'sandboxed')
    assert result['metadata']['per_command'][1]['engine']=='covered'
    off=[KINDS['note'],{**KINDS['edit_text'],'x':W-5}];out=tmp_path/'off'
    with pytest.raises(ProcessorError) as caught:
        execute('editor.visual',[source(tmp_path,name='off.pdf')],{'commands':off,'combined':True},out)
    assert caught.value.code=='editor_out_of_bounds' and caught.value.index==1 and not list(out.iterdir())
    with pytest.raises(ProcessorError) as caught:
        execute_sandbox('editor.visual',[source(tmp_path,name='off-again.pdf')],{'commands':off,'combined':True},tmp_path/'off-sandboxed')
    assert caught.value.code=='editor_out_of_bounds' and caught.value.index==1,'the change at fault crosses out of the child process'


@pytest.mark.parametrize('font,style,embedded',[('sans',{},'NotoSans-Regular'),('sans',{'bold':True},'NotoSans-Bold'),('sans',{'italic':True},'NotoSans-Italic'),('serif',{},'NotoSerif-Regular'),('serif',{'bold':True},'NotoSerif-Bold'),('serif',{'italic':True},'NotoSerif-Italic'),('serif',{'bold':True,'italic':True},'NotoSerif-Bold')])
def test_text_is_set_in_the_family_and_weight_asked(tmp_path,font,style,embedded):
    text='Ўзбек o‘g‘il Привет'
    _,reader=run(source(tmp_path),[{'type':'add_text','page':1,'x':20,'y':100,'text':text,'font':font,**style}],tmp_path)
    assert text in texts(reader)[0]
    fonts=[str(value.get_object()['/BaseFont']) for value in reader.pages[0]['/Resources']['/Font'].values()]
    assert any(embedded in name for name in fonts),fonts


def test_cover_paints_over_what_is_under_it(tmp_path):
    result,_=run(source(tmp_path),[{'type':'whiteout','page':1,**BOX}],tmp_path)
    assert rendered(path_of(result),0).crop((20,30,120,70)).convert('L').getextrema()==(255,255)


def test_a_list_sent_whole_keeps_todays_rules(tmp_path):
    redact={'type':'redact','page':1,**BOX}
    with pytest.raises(ProcessorError) as caught:normalize('editor.visual',{'commands':[redact,KINDS['note']],'accept_rasterization':True})
    assert caught.value.code=='redaction_requires_separate_export'
    result=execute('editor.visual',[source(tmp_path)],{'commands':[redact],'accept_rasterization':True},tmp_path/'out')
    reader=PdfReader(path_of(result))
    assert all(not text.strip() for text in texts(reader)),'today\'s web tells the customer every page becomes a picture'
    assert result['metadata']['redaction_mode']=='rasterized_destructive' and 'all_pages_rasterized_text_and_forms_removed' in result['metadata']['warnings']


def test_overflowing_holds_a_text_to_the_rule_the_page_will():
    page={'width':W,'height':H}
    fits={'type':'add_text','page':1,'x':10,'y':10,'text':'я'*10,'font_size':16}
    wide={**fits,'text':'я'*200};tall={**fits,'text':'\n'.join(['a']*40)};serif={**fits,'text':'W'*37,'font_size':16}
    assert overflowing([fits],[page]) is None
    assert overflowing([fits,wide],[page])==1 and overflowing([tall],[page])==0
    assert overflowing([wide,{'type':'delete_page','page':1}],[page]) is None
    assert overflowing([wide],[]) is None,'a file with no recorded sizes is left to the run'
    # What it says agrees with the page, in the font asked.
    for command in ({**serif,'font':'sans'},{**serif,'font':'serif','bold':True}):
        writer=PdfWriter();writer.add_blank_page(W,H)
        try:editor._overlay(writer.pages[0],command);drew=True
        except ProcessorError:drew=False
        assert drew==(overflowing([command],[page]) is None)


RED,BLUE=(255,0,0),(0,0,255)


def where(image,color):
    """The box round what is drawn in this colour, or None."""
    mask=Image.new('L',image.size);pixels=image.load();marked=mask.load()
    for y in range(image.height):
        for x in range(image.width):
            if all(abs(a-b)<40 for a,b in zip(pixels[x,y],color)):marked[x,y]=255
    return mask.getbbox()


def shown(path,index=0):
    """A page as a customer sees it opened: with its notes and its fields."""
    with pdfium.PdfDocument(str(path)) as document:
        document.init_forms()
        page=document[index];bitmap=page.render(scale=1)
        try:return bitmap.to_pil().convert('RGB')
        finally:bitmap.close();page.close()


def holding(tmp_path,angle=90,flags=0,**field):
    """A wide page the file shows turned, with a filled field (red) and a note (blue), each with its picture ready."""
    plain=tmp_path/'wide.pdf';canvas=Canvas(str(plain),pagesize=(400,200),pageCompression=0)
    canvas.setFont('Helvetica',14);canvas.drawString(25,150,'WORDS')
    canvas.acroForm.textfield(name='secret',value='VALUE-1',x=20,y=20,width=150,height=30,fillColor=HexColor('#FF0000'),borderWidth=0,**field)
    canvas.showPage();canvas.save()
    writer=PdfWriter(clone_from=plain);page=writer.pages[0]
    look=DecodedStreamObject();look.set_data(b'0 0 1 rg 0 0 60 40 re f')
    look.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Form'),NameObject('/BBox'):ArrayObject([NumberObject(0),NumberObject(0),NumberObject(60),NumberObject(40)])})
    note=DictionaryObject({NameObject('/Type'):NameObject('/Annot'),NameObject('/Subtype'):NameObject('/FreeText'),NameObject('/F'):NumberObject(flags),NameObject('/Rect'):ArrayObject([NumberObject(200),NumberObject(100),NumberObject(260),NumberObject(140)]),NameObject('/Contents'):TextStringObject('PRIVATE-NOTE'),NameObject('/AP'):DictionaryObject({NameObject('/N'):writer._add_object(look)})})
    page['/Annots'].append(writer._add_object(note));page.rotate(angle)
    path=tmp_path/'holding.pdf';writer.write(path)
    return path


@pytest.mark.parametrize('angle',[90,180,270])
@pytest.mark.parametrize('commands',[[{'type':'reorder','order':[1]}],[{'type':'whiteout','page':1,'x':0,'y':0,'width':1,'height':1}]],ids=['page-order','a-mark'])
def test_notes_and_fields_stay_where_a_turned_page_showed_them(tmp_path,angle,commands):
    path=holding(tmp_path,angle);before=shown(path)
    assert where(before,RED) and where(before,BLUE),'the fixture shows both'
    result,reader=run(path,commands,tmp_path)
    after=shown(path_of(result))
    assert after.size==before.size and where(after,RED)==where(before,RED) and where(after,BLUE)==where(before,BLUE)
    assert reader.pages[0].rotation==0 and reader.get_fields()['secret']['/V']=='VALUE-1'


@pytest.mark.parametrize('angle',[90,180,270])
def test_a_note_that_stays_upright_keeps_its_place_on_a_turned_page(tmp_path,angle):
    path=holding(tmp_path,angle,flags=16);before=shown(path)
    result,_=run(path,[{'type':'reorder','order':[1]}],tmp_path)
    assert where(shown(path_of(result)),BLUE)==where(before,BLUE)


@pytest.mark.parametrize('angle',[90,180,270])
def test_black_out_on_a_turned_page_takes_the_value_and_the_note_it_was_placed_over(tmp_path,angle):
    path=holding(tmp_path,angle);before=shown(path)
    boxes=[{'type':'redact','page':1,'x':left,'y':top,'width':right-left,'height':bottom-top} for left,top,right,bottom in (where(before,RED),where(before,BLUE))]
    result,reader=run(path,boxes,tmp_path)
    after=shown(path_of(result))
    assert where(after,RED) is None and where(after,BLUE) is None
    held=everything_in(path_of(result))
    assert 'VALUE-1' not in held and 'PRIVATE-NOTE' not in held and not reader.get_fields()
    assert texts(reader)[0].strip()==''


def test_a_value_set_on_a_turned_page_runs_along_its_field(tmp_path):
    path=holding(tmp_path,90);field=where(shown(path),RED)
    assert field[3]-field[1]>field[2]-field[0],'shown standing up'
    result,reader=run(path,[{'type':'fill_form','field':'secret','value':'A NEW VALUE'}],tmp_path)
    assert reader.get_fields()['secret']['/V']=='A NEW VALUE'
    words=where(shown(path_of(result)).crop(field),(0,0,0))
    assert words[3]-words[1]>words[2]-words[0],'its words stand up with it'


def a_look(writer,words=b''):
    """A bar along the bottom of a note, so that its picture shows if it was turned or stretched."""
    look=DecodedStreamObject();look.set_data(words+b'0 0 1 rg 0 0 100 5 re f')
    look.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Form'),NameObject('/BBox'):ArrayObject([NumberObject(0),NumberObject(0),NumberObject(100),NumberObject(20)])})
    return writer._add_object(look)


def a_note(**held):
    return DictionaryObject({NameObject('/Type'):NameObject('/Annot'),NameObject('/Subtype'):NameObject('/FreeText'),NameObject('/Rect'):ArrayObject([NumberObject(v) for v in (50,50,150,70)]),**{NameObject('/'+key):value for key,value in held.items()}})


def turned_pages(tmp_path,angles,**held):
    """A wide page for each angle, each with a note holding what it is given. Returns the path."""
    writer=PdfWriter()
    for angle in angles:
        page=writer.add_blank_page(400,200);page[NameObject('/Annots')]=ArrayObject([writer._add_object(a_note(**{key:value(writer) if callable(value) else value for key,value in held.items()}))])
        if angle:page[NameObject('/Rotate')]=NumberObject(angle)
    path=tmp_path/'turned-pages.pdf';writer.write(path)
    return path


def shared(kind):
    """The same appearance on every page, held the ways a file can hold it: the picture, its states, or all of its /AP."""
    made={}
    def once(writer):
        if not made:
            look=a_look(writer)
            made['value']={'picture':lambda:DictionaryObject({NameObject('/N'):look}),'states':lambda:DictionaryObject({NameObject('/N'):writer._add_object(DictionaryObject({NameObject('/Yes'):look}))}),'whole':lambda:writer._add_object(DictionaryObject({NameObject('/N'):look}))}[kind]()
        return made['value']
    return once


@pytest.mark.parametrize('kind',['picture','states','whole'])
def test_an_appearance_shared_with_a_page_turned_otherwise_stays_right_on_each(tmp_path,kind):
    angles=[90,0,90,180];path=turned_pages(tmp_path,angles,AP=shared(kind),**({'AS':NameObject('/Yes')} if kind=='states' else {}))
    before=[where(shown(path,index),BLUE) for index in range(4)]
    assert all(before) and before[0]!=before[1],'the fixture shows each'
    result,reader=run(path,[{'type':'reorder','order':[1,2,3,4]}],tmp_path)
    assert [where(shown(path_of(result),index),BLUE) for index in range(4)]==before
    assert all(page.rotation==0 for page in reader.pages)


def test_a_box_on_a_turned_page_takes_the_picture_a_note_had_and_no_other(tmp_path):
    writer=PdfWriter()
    for words,angle in ((b'% GONE-LOOK\n',90),(b'% KEPT-LOOK\n',0)):
        page=writer.add_blank_page(400,200);page[NameObject('/Annots')]=ArrayObject([writer._add_object(a_note(AP=writer._add_object(DictionaryObject({NameObject('/N'):a_look(writer,words)}))))])
        if angle:page[NameObject('/Rotate')]=NumberObject(angle)
    path=tmp_path/'looks.pdf';writer.write(path)
    left,top,right,bottom=where(shown(path),BLUE)
    result,_=run(path,[{'type':'redact','page':1,'x':left,'y':top,'width':right-left,'height':bottom-top}],tmp_path)
    held=everything_in(path_of(result))
    assert 'GONE-LOOK' not in held and 'KEPT-LOOK' in held


NOTHING={
    'no appearance':{'AP':NullObject()},
    'no normal look':{'AP':DictionaryObject({NameObject('/N'):NullObject()})},
    'no state':{'AP':DictionaryObject({NameObject('/N'):DictionaryObject({NameObject('/Yes'):NullObject()})})},
    'no other look':{'AP':DictionaryObject({NameObject('/N'):DictionaryObject(),NameObject('/D'):NullObject()})},
    'no place':{'Rect':NullObject()},
    'no flags or geometry':{'F':NullObject(),'QuadPoints':NullObject(),'Vertices':NullObject(),'L':NullObject(),'CL':NullObject(),'InkList':NullObject()},
    'no turn of its own':{'Subtype':NameObject('/Widget'),'MK':NullObject()},
}


@pytest.mark.parametrize('held',NOTHING.values(),ids=NOTHING.keys())
@pytest.mark.parametrize('commands',[[{'type':'reorder','order':[1]}],[{'type':'whiteout','page':1,'x':0,'y':0,'width':1,'height':1}]],ids=['page-order','a-mark'])
def test_a_null_on_a_turned_page_means_the_same_as_nothing(tmp_path,held,commands):
    result,reader=run(turned_pages(tmp_path,[90],**held),commands,tmp_path)
    assert result['artifacts'] and reader.pages[0].rotation==0


def test_a_picture_with_nulls_beside_it_is_still_drawn_on_a_turned_page(tmp_path):
    writer=PdfWriter();page=writer.add_blank_page(400,200)
    ref=writer._add_object(NumberObject(50))
    page[NameObject('/Annots')]=ArrayObject([writer._add_object(a_note(F=NullObject(),Rect=ArrayObject([ref,ref,NumberObject(150),NumberObject(70)]),AP=DictionaryObject({NameObject('/N'):a_look(writer),NameObject('/D'):NullObject()})))])
    look=page['/Annots'][0].get_object()['/AP']['/N'];look[NameObject('/Matrix')]=NullObject()
    page[NameObject('/Rotate')]=NumberObject(90)
    path=tmp_path/'beside.pdf';writer.write(path);before=where(shown(path),BLUE)
    assert before,'the fixture shows it'
    result,_=run(path,[{'type':'reorder','order':[1]}],tmp_path)
    assert where(shown(path_of(result)),BLUE)==before


@pytest.mark.parametrize('annots',[NullObject(),ArrayObject([NullObject()])],ids=['no-list','no-entry'])
def test_a_null_in_the_list_of_notes_of_a_turned_page_is_no_note(annots):
    # The reader at the door refuses these two today. Should it stop, the page still turns.
    writer=PdfWriter();page=writer.add_blank_page(400,200)
    page[NameObject('/Annots')]=annots;page[NameObject('/Rotate')]=NumberObject(90)
    editor._unturned(writer,page,set(),{})
    assert page.rotation==0 and float(page.mediabox.width)==pytest.approx(200)


def test_a_field_whose_kids_are_held_by_reference_can_go_with_its_page(tmp_path):
    writer=PdfWriter(clone_from=source(tmp_path))
    kids=writer._add_object(ArrayObject())
    parent=writer._add_object(DictionaryObject({NameObject('/T'):TextStringObject('group'),NameObject('/FT'):NameObject('/Tx'),NameObject('/V'):TextStringObject('SHARED-VALUE'),NameObject('/Kids'):kids}))
    for index in (0,1):
        widget=writer._add_object(DictionaryObject({NameObject('/Type'):NameObject('/Annot'),NameObject('/Subtype'):NameObject('/Widget'),NameObject('/Rect'):ArrayObject([NumberObject(20),NumberObject(300),NumberObject(200),NumberObject(330)]),NameObject('/Parent'):parent}))
        kids.get_object().append(widget)
        writer.pages[index][NameObject('/Annots')]=ArrayObject([widget])
    writer._root_object[NameObject('/AcroForm')]=DictionaryObject({NameObject('/Fields'):ArrayObject([parent])})
    path=tmp_path/'kids.pdf';writer.write(path)
    result,reader=run(path,[{'type':'redact','page':1,**BOX}],tmp_path)
    assert 'group' in reader.get_fields() and len(reader.pages[1]['/Annots'])==1
    result,reader=run(path,[{'type':'delete_page','page':1},{'type':'delete_page','page':2}],tmp_path,out='both')
    assert not reader.get_fields() and 'SHARED-VALUE' not in everything_in(path_of(result))


def blank(tmp_path,width,height,angle=0):
    writer=PdfWriter();writer.add_blank_page(width,height);writer.add_blank_page(width,height)
    for page in writer.pages:page.rotate(angle)
    path=tmp_path/'sized.pdf';writer.write(path)
    return path


@pytest.mark.parametrize('width,height,angle',[(419.53,595.28,0),(498.9,708.66,0),(283.46,500,0),(612,792,180),(612,792,90),(612,792,270),(400,600,90)])
def test_a_box_and_a_mark_reaching_the_edge_of_the_page_are_inside_it(tmp_path,width,height,angle):
    across,down=(height,width) if angle in (90,270) else (width,height)
    edge={'x':across-50,'y':down-20,'width':50,'height':20}
    result,reader=run(blank(tmp_path,width,height,angle),[{'type':'redact','page':1,**edge},{'type':'whiteout','page':2,**edge},{'type':'draw','page':2,'points':[[across-10,down-10],[across,down]]}],tmp_path)
    assert result['metadata']['rasterized_pages']==[1] and len(reader.pages)==2


def test_a_box_past_the_edge_of_the_page_is_still_refused(tmp_path):
    for kind in ('redact','whiteout'):
        with pytest.raises(ProcessorError) as caught:
            run(blank(tmp_path,419.53,595.28),[{'type':kind,'page':1,'x':369.53,'y':0,'width':50.5,'height':20}],tmp_path,out=kind)
        assert caught.value.code=='editor_out_of_bounds'
