"""Changing a PDF's own words: PdfCraft where a look at the page allows it, else retyped or covered, and never a word of the page in an error, a log or a job's metadata.

Every page here is made up and drawn by the test. The tests marked REQUIRES_PDFCRAFT
run the real binary (CI fetches the Linux build, as production runs); the rest
use a stand-in or none.
"""
import json
import logging
import os
import shlex
import sys
import time
from collections import namedtuple
from pathlib import Path

import numpy
import pypdfium2 as pdfium
import pytest
from pypdf import PdfReader,PdfWriter
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from processors import pdfcraft,text_edit
from processors.editor import normalize
from processors.engine import ProcessorError,execute
from processors.sandbox import execute_sandbox
from processors.text_edit import Page,changed,check_edit,check_removal,close,face_of,family,imported,match,norm,overlay,paper,room,row_of,style_of

ROOT=Path(__file__).resolve().parents[1]
FONTS=ROOT/'processors/assets/fonts'
REQUIRES_PDFCRAFT=pytest.mark.skipif(not os.environ.get('PDFMASTER_PDFCRAFT_BIN'),reason='needs PDFMASTER_PDFCRAFT_BIN')
W,H=595.28,841.89
for face in ('NotoSans-Regular','NotoSans-Bold','NotoSerif-Regular','NotoSerif-Bold'):
    if face not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont(face,str(FONTS/f'{face}.ttf')))

# One line as drawn: its font, size, start and baseline from the top, words and colour.
Row=namedtuple('Row','font size x y text color',defaults=('#000000',))
UZ=[Row('NotoSans-Bold',18,72,72,'Toshkent shahri haqida','#1a3d7c'),
    Row('NotoSans-Regular',11,72,100,'Toshkent O‘zbekistonning poytaxti va eng katta shahri.'),
    Row('NotoSans-Regular',11,72,115,'Shahar qadimiy tarixga ega bo‘lib, Buyuk ipak yo‘lida joylashgan.'),
    Row('NotoSans-Regular',11,72,130,'Bugungi kunda bu yerda uch million aholi yashaydi.'),
    Row('NotoSans-Regular',11,72,160,'Metro 1977 yilda ochilgan va hozir 50 bekatga ega.','#b00020')]
# A line that reaches far across the page, so a 60 % longer one cannot stay its size.
LONG=Row('NotoSans-Regular',11,72,200,'Har yili minglab sayyohlar shaharning muzeylari, bozorlari va bog‘larini ziyorat qilishadi.')
EN=[Row('Helvetica-Bold',16,72,72,'Quarterly Summary'),Row('Helvetica',11,72,100,'The team delivered every planned feature this quarter.'),Row('Helvetica',11,72,115,'Revenue grew by twelve percent over the same period.')]


def drawn(path,rows,pages=1,size=(W,H)):
    canvas=Canvas(str(path),pagesize=size)
    for number in range(1,pages+1):
        for row in rows:
            canvas.setFont(row.font,row.size);canvas.setFillColor(HexColor(row.color));canvas.drawString(row.x,size[1]-row.y,row.text.replace('{page}',str(number)))
        canvas.showPage()
    canvas.save()
    return path


def box(row,text=None):
    """Where the web puts a line's box: from its first letter, 0.95 of its size above the baseline to 0.3 below."""
    return {'x':row.x,'y':row.y-.95*row.size,'width':stringWidth(text or row.text,row.font,row.size),'height':1.25*row.size}


def edit(row,text,page=1,original=None):
    return {'type':'edit_text','page':page,**box(row,original),'original':original or row.text,'text':text}


def run(source,commands,tmp_path,pdfcraft=True,out='out'):
    result=execute('editor.visual',[source],{'commands':commands,'accept_rasterization':True,'combined':True},tmp_path/out,pdfcraft=pdfcraft)
    return result,result['artifacts'][0]['path']


def engines(result):
    return [row['engine'] for row in result['metadata']['per_command']]


def text_of(path,index=0):
    return ' '.join(PdfReader(path).pages[index].extract_text().split())


def type3(path):
    """Whether any page of the file draws with a Type3 font: PdfCraft's fallback for a letter the font lacks."""
    found=False
    for page in PdfReader(path).pages:
        fonts=(page.get('/Resources') or {}).get('/Font') or {}
        found|=any(str(font.get_object().get('/Subtype'))=='/Type3' for font in fonts.get_object().values())
    return found


def pixels(path,index=0):
    with pdfium.PdfDocument(str(path)) as document:
        bitmap=document[index].render(scale=100/72)
        return numpy.asarray(bitmap.to_pil().convert('RGB'),dtype=numpy.int16)


def changed_outside(before,after,*rects):
    """Pixels that differ between two renders, outside the given boxes (points, padded 6 by 4)."""
    changes=numpy.abs(pixels(before)-pixels(after)).max(axis=2)>40;scale=100/72
    for x0,top,x1,bottom in rects:changes[max(0,int((top-4)*scale)):int((bottom+4)*scale),max(0,int((x0-6)*scale)):int((x1+6)*scale)]=False
    return int(changes.sum())


def row_rect(row,text=None):
    return [row.x,row.y-1.1*row.size,row.x+stringWidth(text or row.text,row.font,row.size),row.y+.35*row.size]


# With the real binary.

@REQUIRES_PDFCRAFT
def test_a_word_swapped_in_uzbek_latin_stays_in_the_lines_own_face(tmp_path):
    source=drawn(tmp_path/'uz.pdf',UZ);new='Shahar qadimiy tarixga ega bo‘lib, Buyuk ipak yo‘lida turibdi.'
    result,path=run(source,[edit(UZ[2],new)],tmp_path)
    assert engines(result)==['pdfcraft'] and result['metadata']['engine'].startswith('pdfcraft/')
    assert result['metadata']['engine_versions']['pdfcraft']==pdfcraft.version()
    words=text_of(path)
    assert norm(new) in norm(words) and 'joylashgan' not in words and norm(UZ[1].text) in norm(words)
    edited=[c for c in Page.read(path,1).letters if 112<c['base']<118]
    assert {family(c['font']) for c in edited}=={'notosans'} and not type3(path)
    assert changed_outside(source,path,row_rect(UZ[2]))==0


@REQUIRES_PDFCRAFT
def test_the_switch_reaches_the_child_through_the_sandbox(tmp_path):
    source=drawn(tmp_path/'uz.pdf',UZ)
    commands=[edit(UZ[3],'Bugungi kunda bu yerda ikki million aholi yashaydi.')]
    result=execute_sandbox('editor.visual',[source],{'commands':commands,'combined':True},tmp_path/'on',pdfcraft=True)
    assert [row['engine'] for row in result['metadata']['per_command']]==['pdfcraft']
    result=execute_sandbox('editor.visual',[source],{'commands':commands,'combined':True},tmp_path/'off')
    assert [row['engine'] for row in result['metadata']['per_command']]==['covered'] and 'pdfcraft' not in result['metadata']['engine']


@REQUIRES_PDFCRAFT
@pytest.mark.parametrize('rows,index,new',[
    (UZ,2,'Shahar qadimiy tarixga ega bo‘lib, Буюк ipak yo‘lida joylashgan.'),
    (EN,1,'The team delivered every planned feature this квартал.'),
],ids=['noto-sans','helvetica'])
def test_cyrillic_typed_into_a_latin_line_reads_back_with_no_type3_font(tmp_path,rows,index,new):
    source=drawn(tmp_path/'latin.pdf',rows)
    result,path=run(source,[edit(rows[index],new)],tmp_path)
    assert engines(result)[0] in ('pdfcraft-noto','retyped')
    assert norm(new) in norm(text_of(path)) and not type3(path)
    assert all(family(c['font']) for c in Page.read(path,1).letters),'every letter has a named font'


@REQUIRES_PDFCRAFT
def test_a_line_made_60_percent_longer_is_set_smaller_and_stays_on_the_page(tmp_path):
    source=drawn(tmp_path/'long.pdf',[*UZ,LONG]);new=LONG.text[:-1]+', ularning soni yildan yilga ortib bormoqda va ko‘paymoqda.'
    assert stringWidth(new,LONG.font,LONG.size)>1.6*stringWidth(LONG.text,LONG.font,LONG.size)
    result,path=run(source,[edit(LONG,new)],tmp_path)
    assert engines(result)==['retyped']
    assert norm(new) in norm(text_of(path)) and 'ziyorat qilishadi.' not in text_of(path).replace(new,'')
    letters=[c for c in Page.read(path,1).letters if LONG.y-3<c['base']<LONG.y+3]
    assert letters and max(c['right'] for c in letters)<=W-text_edit.MARGIN+.5,'on the page, short of its margin'
    sizes={round(c['size'],1) for c in letters}
    assert len(sizes)==1 and text_edit.SMALLEST*LONG.size<=sizes.pop()<LONG.size
    assert abs(min(c['x'] for c in letters)-LONG.x)<.5 and all(abs(c['base']-LONG.y)<.3 for c in letters),'where the old words stood'
    assert changed_outside(source,path,[LONG.x,LONG.y-12,W,LONG.y+4])==0,'nothing else on the page changed'


@REQUIRES_PDFCRAFT
def test_empty_text_takes_the_line_out_and_leaves_the_rest(tmp_path):
    source=drawn(tmp_path/'uz.pdf',UZ)
    result,path=run(source,[edit(UZ[1],'')],tmp_path)
    assert engines(result)==['removed'] and result['metadata']['engine'].startswith('pdfcraft/')
    words=norm(text_of(path))
    assert norm(UZ[1].text) not in words and all(norm(row.text) in words for row in UZ if row is not UZ[1])
    assert changed_outside(source,path,row_rect(UZ[1]))==0


@REQUIRES_PDFCRAFT
def test_two_edits_on_one_page_each_land(tmp_path):
    source=drawn(tmp_path/'uz.pdf',UZ)
    first,second='Toshkent shahri tarixi','Metro 1977 yilda ochilgan va hozir 60 bekatga ega.'
    result,path=run(source,[edit(UZ[0],first),edit(UZ[4],second)],tmp_path)
    assert engines(result)==['pdfcraft','pdfcraft']
    words=norm(text_of(path))
    assert norm(first) in words and norm(second) in words and norm(UZ[2].text) in words and 'haqida' not in words
    red=[c for c in Page.read(path,1).letters if UZ[4].y-3<c['base']<UZ[4].y+3]
    assert {c['color'] for c in red}=={'#b00020'},'the red line stays red'


@REQUIRES_PDFCRAFT
def test_a_box_that_matches_nothing_is_covered(tmp_path):
    source=drawn(tmp_path/'uz.pdf',UZ)
    command={**edit(UZ[3],'Yangi qator'),'original':'Boshqa so‘zlar'}
    result,path=run(source,[command],tmp_path)
    assert engines(result)==['covered'] and 'pdfcraft' not in result['metadata']['engine']
    assert 'Yangi qator' in text_of(path)
    # The paper's colour over the old words, the new ones on top.
    page=pixels(path);scale=100/72;x0,top=int(UZ[3].x*scale),int((UZ[3].y-.9*UZ[3].size)*scale)
    right=int((UZ[3].x+stringWidth(UZ[3].text,UZ[3].font,UZ[3].size)-2)*scale)
    tail=page[top:int((UZ[3].y+2)*scale),int((UZ[3].x+stringWidth('Yangi qator',UZ[3].font,UZ[3].size)+4)*scale):right]
    assert tail.min()>=250,'the old words past the new ones are painted out'


@REQUIRES_PDFCRAFT
def test_with_the_switch_off_pdfcraft_is_not_asked(tmp_path):
    source=drawn(tmp_path/'uz.pdf',UZ)
    result,path=run(source,[edit(UZ[2],'Shahar qadimiy tarixga ega.')],tmp_path,pdfcraft=False)
    assert engines(result)==['covered'] and 'pdfcraft' not in result['metadata']['engine_versions']


def turned_page(path,rows,angle=90):
    """A page with /Rotate whose words read across the page as shown: the box is placed in the shown frame."""
    canvas=Canvas(str(path),pagesize=(W,H));canvas.rotate(90)
    for row in rows:canvas.setFont(row.font,row.size);canvas.drawString(row.x,-row.y,row.text)
    canvas.showPage();canvas.save()
    writer=PdfWriter(clone_from=PdfReader(path));writer.pages[0].rotate(angle);writer.write(path)
    return path


@REQUIRES_PDFCRAFT
def test_a_turned_page_is_covered_where_it_shows(tmp_path):
    rows=[Row('NotoSans-Regular',12,60,80,'Birinchi qator matni shu yerda.'),Row('NotoSans-Regular',12,60,100,'Ikkinchi qator matni shu yerda.')]
    source=turned_page(tmp_path/'turned.pdf',rows)
    shown=Page.read(source,1)
    assert (round(shown.width),round(shown.height))==(round(H),round(W))
    assert ''.join(c['char'] for c in shown.letters if 77<c['base']<83)==norm(rows[0].text),'the fixture reads across as shown'
    result,path=run(source,[edit(rows[0],'Yangi birinchi qator.')],tmp_path)
    assert engines(result)==['covered']
    made=Page.read(path,1)
    assert (round(made.width),round(made.height))==(round(H),round(W))
    now=''.join(c['char'] for c in made.letters if 77<c['base']<83 and c['left']<rows[0].x+stringWidth('Yangi birinchi qator.',rows[0].font,12)+1)
    assert now.endswith(norm('Yangi birinchi qator.')),'the new words stand where the old line showed'
    assert norm(rows[1].text) in norm(text_of(path))


@REQUIRES_PDFCRAFT
def test_an_edit_on_a_page_that_is_deleted_is_skipped(tmp_path):
    rows=[Row('NotoSans-Regular',12,72,80,'Sahifa {page} matni')]
    source=drawn(tmp_path/'pages.pdf',rows,pages=2)
    command=edit(Row('NotoSans-Regular',12,72,80,'Sahifa 2 matni'),'Yangi matn',page=2)
    result,path=run(source,[command,{'type':'delete_page','page':2}],tmp_path)
    assert result['metadata']['per_command'][0]['status']=='skipped' and 'pdfcraft' not in result['metadata']['engine']
    assert len(PdfReader(path).pages)==1 and 'Yangi' not in text_of(path)


@REQUIRES_PDFCRAFT
def test_an_edit_and_a_reorder_land_on_the_right_page(tmp_path):
    rows=[Row('NotoSans-Regular',12,72,80,'Sahifa {page} matni')]
    source=drawn(tmp_path/'pages.pdf',rows,pages=3)
    command=edit(Row('NotoSans-Regular',12,72,80,'Sahifa 2 matni'),'Sahifa 2 yangi matni',page=2)
    result,path=run(source,[command,{'type':'reorder','order':[2,3,1]}],tmp_path)
    assert engines(result)[0]=='pdfcraft'
    assert [text_of(path,index) for index in range(3)]==['Sahifa 2 yangi matni','Sahifa 3 matni','Sahifa 1 matni']


@REQUIRES_PDFCRAFT
def test_a_line_beside_another_run_is_kept_clear_of_it(tmp_path):
    rows=[Row('NotoSans-Regular',10,50,80,'Chap ustun birinchi qatori.'),Row('NotoSans-Regular',10,310,80,'O‘ng ustun birinchi qatori.')]
    source=drawn(tmp_path/'columns.pdf',rows)
    new='Chap ustun birinchi qatori ancha uzunroq bo‘lib, o‘ng ustunga yetib boradi.'
    result,path=run(source,[edit(rows[0],new)],tmp_path)
    assert engines(result)==['retyped']
    letters=[c for c in Page.read(path,1).letters if 77<c['base']<83 and c['left']<309]
    assert ''.join(c['char'] for c in letters)==norm(new) and max(c['right'] for c in letters)<310,'clear of the next words'
    assert norm(rows[1].text) in norm(text_of(path))


@REQUIRES_PDFCRAFT
def test_words_too_long_even_at_the_smallest_size_are_refused_with_their_index(tmp_path):
    rows=[Row('NotoSans-Regular',10,50,80,'Chap ustun.'),Row('NotoSans-Regular',10,120,80,'O‘ng ustun.')]
    source=drawn(tmp_path/'columns.pdf',rows)
    with pytest.raises(ProcessorError) as caught:
        run(source,[{'type':'note','page':1,'x':5,'y':5,'text':'Eslatma'},edit(rows[0],'Juda uzun so‘zlar bu yerga sig‘maydi')],tmp_path)
    assert caught.value.code=='editor_text_too_long' and caught.value.index==1 and not list((tmp_path/'out').iterdir())


def mixed_row(path):
    """One row of three styles, as Sejda's demo has them: plain, a bold word, a red word."""
    canvas=Canvas(str(path),pagesize=(W,H));x=72;runs=[]
    for font,color,words in (('NotoSans-Regular','#000000','Shartnoma '),('NotoSans-Bold','#000000','muddati'),('NotoSans-Regular','#000000',' 2026 yil 31 dekabrgacha '),('NotoSans-Regular','#c00000','uzaytirildi'),('NotoSans-Regular','#000000',' va imzolandi.')):
        canvas.setFont(font,11);canvas.setFillColor(HexColor(color));canvas.drawString(x,H-100,words);runs.append((x,words));x+=stringWidth(words,font,11)
    canvas.showPage();canvas.save()
    text=''.join(words for _,words in runs)
    return path,{'type':'edit_text','page':1,'x':72,'y':100-.95*11,'width':x-72,'height':1.25*11,'original':text,'text':text}


@REQUIRES_PDFCRAFT
@pytest.mark.parametrize('old,new,color,bold',[('uzaytirildi','qisqartirildi','#c00000',False),('muddati','vaqti','#000000',True)],ids=['red-word','bold-word'])
def test_a_word_changed_in_a_row_of_several_styles_keeps_its_own_style(tmp_path,old,new,color,bold):
    source,command=mixed_row(tmp_path/'mixed.pdf');command['text']=command['text'].replace(old,new)
    result,path=run(source,[command],tmp_path)
    assert engines(result)[0] in ('pdfcraft','pdfcraft-noto')
    row=sorted((c for c in Page.read(path,1).letters if abs(c['base']-100)<.5),key=lambda c:c['left'])
    said=''.join(c['char'] for c in row);at=said.index(new)
    assert said==norm(command['text'])
    assert {c['color'] for c in row[at:at+len(new)]}=={color} and {text_edit._look(c['font'])[0] for c in row[at:at+len(new)]}=={bold}
    assert {c['color'] for c in row[:9]}=={'#000000'} and not any(text_edit._look(c['font'])[0] for c in row[:9]),'the row around it is as it was'


@REQUIRES_PDFCRAFT
def test_a_form_keeps_its_fields_through_pdfcraft(tmp_path):
    path=tmp_path/'form.pdf';canvas=Canvas(str(path),pagesize=(W,H))
    canvas.setFont('NotoSans-Regular',12);canvas.drawString(72,H-80,'Ariza beruvchi ismi');canvas.acroForm.textfield(name='ism',value='',x=72,y=600,width=200,height=24)
    canvas.showPage();canvas.save()
    result,made=run(path,[edit(Row('NotoSans-Regular',12,72,80,'Ariza beruvchi ismi'),'Ariza beruvchi familiyasi'),{'type':'fill_form','field':'ism','value':'Ali'}],tmp_path)
    assert engines(result)[0]=='pdfcraft' and str(PdfReader(made).get_fields()['ism']['/V'])=='Ali'


# Without the binary: a stand-in, or none.

def stand_in(folder,body):
    """A pdfcraft-cli that answers its version as the pinned release and runs `body` (Python) for a script."""
    binary=folder/'pdfcraft-cli'
    binary.write_text(f'#!{sys.executable}\nimport json,os,sys,time\nif sys.argv[1:]==["--version"]:\n    print("pdfcraft-cli {pdfcraft.version()}");sys.exit(0)\n{body}\n')
    binary.chmod(0o755)
    return binary


def test_pdfcraft_runs_in_its_root_with_nothing_of_the_workers_environment(tmp_path,monkeypatch):
    notes=tmp_path/'notes.json'
    binary=stand_in(tmp_path,f'json.dump({{"argv":sys.argv[1:],"env":dict(os.environ),"cwd":os.getcwd(),"stdin":sys.stdin.read(),"group":os.getpgrp(),"files":sorted(os.listdir("."))}},open({str(notes)!r},"w"))\nprint("{{}}")')
    monkeypatch.setenv('PDFMASTER_PDFCRAFT_BIN',str(binary));monkeypatch.setenv('SECRET_KEY','do-not-pass');monkeypatch.setenv('DATABASE_URL','postgres://nobody')
    source=drawn(tmp_path/'uz.pdf',UZ)
    result,_=run(source,[edit(UZ[2],'Yangi qator')],tmp_path)
    assert engines(result)==['covered'],'a report it cannot read is covered'
    seen=json.loads(notes.read_text());root=Path(seen['cwd'])
    assert root.parent==tmp_path/'out' and root.name.startswith('pdfcraft-')
    # What the stand-in's own interpreter adds on macOS (locale coercion, CoreFoundation) is not what it was given.
    given={name:value for name,value in seen['env'].items() if name not in ('LC_CTYPE','__CF_USER_TEXT_ENCODING')}
    assert given=={'PATH':os.environ.get('PATH',''),**dict.fromkeys(pdfcraft.ISOLATION,str(root))}
    assert seen['argv']==['run','--script',str(root/'steps.json'),'--report','--root',str(root)] and seen['stdin']==''
    assert seen['group']==os.getpgrp(),'in the child\'s own process group, which the sandbox kills whole'
    assert 'work-0.pdf' in seen['files'] and not root.exists(),'the root goes with the job'


def test_a_binary_that_is_not_the_pinned_release_is_not_asked(tmp_path,monkeypatch):
    binary=tmp_path/'pdfcraft-cli';started=tmp_path/'started'
    binary.write_text(f'#!/bin/sh\necho "$1" >> {shlex.quote(str(started))}\necho "pdfcraft-cli 0.15.0"\n');binary.chmod(0o755)
    monkeypatch.setenv('PDFMASTER_PDFCRAFT_BIN',str(binary))
    result,_=run(drawn(tmp_path/'uz.pdf',UZ),[edit(UZ[2],'Yangi qator')],tmp_path)
    assert engines(result)==['covered'] and started.read_text().split()==['--version']
    monkeypatch.setenv('PDFMASTER_PDFCRAFT_BIN',str(tmp_path/'missing'))
    assert pdfcraft.binary(tmp_path) is None


def test_a_run_that_hangs_is_cut_short_and_the_rest_are_covered(tmp_path,monkeypatch):
    started=tmp_path/'started'
    binary=stand_in(tmp_path,f'open({str(started)!r},"a").write("run\\n");time.sleep(30)')
    monkeypatch.setenv('PDFMASTER_PDFCRAFT_BIN',str(binary));monkeypatch.setattr(pdfcraft,'SECONDS',1)
    began=time.monotonic()
    result,path=run(drawn(tmp_path/'uz.pdf',UZ),[edit(UZ[1],'Birinchi yangi qator'),edit(UZ[3],'Ikkinchi yangi qator')],tmp_path)
    assert time.monotonic()-began<10 and engines(result)==['covered','covered']
    assert started.read_text().split()==['run'],'after one hang PdfCraft is not asked again'
    assert 'Birinchi yangi qator' in text_of(path) and 'Ikkinchi yangi qator' in text_of(path)


def test_past_the_budget_the_rest_are_covered_without_asking(tmp_path,monkeypatch):
    started=tmp_path/'started'
    binary=stand_in(tmp_path,f'open({str(started)!r},"a").write("run\\n");print("{{}}")')
    monkeypatch.setenv('PDFMASTER_PDFCRAFT_BIN',str(binary));monkeypatch.setattr(text_edit,'BUDGET',0)
    result,_=run(drawn(tmp_path/'uz.pdf',UZ),[edit(UZ[1],'Birinchi yangi qator'),edit(UZ[3],'Ikkinchi yangi qator')],tmp_path)
    assert engines(result)==['covered','covered'] and not started.exists()


@REQUIRES_PDFCRAFT
def test_a_file_pdfcraft_rewrote_without_all_its_parts_is_not_used(tmp_path,monkeypatch):
    monkeypatch.setattr(text_edit,'_keeps_its_parts',lambda source,made:False)
    source=drawn(tmp_path/'uz.pdf',UZ)
    result,path=run(source,[edit(UZ[3],'Bugungi kunda bu yerda ikki million aholi yashaydi.'),edit(UZ[1],'')],tmp_path)
    assert engines(result)==['covered','blanked'] and 'pdfcraft' not in result['metadata']['engine']
    assert 'ikki million' in text_of(path)


@pytest.mark.parametrize('answer',['print("not a report")','print(json.dumps({"ok": True}))','print(json.dumps([1, 2]))','sys.stdout.write("x" * (3 * 1024 * 1024))','sys.exit(9)'],ids=['garbage','no-steps','a-list','too-long','crash'])
def test_a_report_it_cannot_read_is_covered(tmp_path,monkeypatch,answer):
    monkeypatch.setenv('PDFMASTER_PDFCRAFT_BIN',str(stand_in(tmp_path,answer)))
    result,path=run(drawn(tmp_path/'uz.pdf',UZ),[edit(UZ[2],'Yangi qator')],tmp_path)
    assert engines(result)==['covered'] and 'Yangi qator' in text_of(path)


def test_no_word_of_the_report_reaches_an_error_a_log_or_the_metadata(tmp_path,monkeypatch,caplog):
    marker='MAXFIY-SOZLAR-7731'
    report=json.dumps({'ok':False,'steps':[{'status':'error','error':marker,'tool':'doc_open'},{'status':'skipped'},{'status':'skipped'}]})
    monkeypatch.setenv('PDFMASTER_PDFCRAFT_BIN',str(stand_in(tmp_path,f'print({report!r});sys.stderr.write({marker!r})')))
    source=drawn(tmp_path/'uz.pdf',UZ)
    with caplog.at_level(logging.DEBUG):
        result,_=run(source,[edit(UZ[2],'Yangi qator')],tmp_path)
        assert engines(result)==['covered'] and marker not in json.dumps(result)
        # A job that fails all the same says a code and an index, nothing more.
        with pytest.raises(ProcessorError) as caught:
            run(source,[edit(UZ[2],'Yangi qator '*40)],tmp_path,out='failed')
        sandboxed=None
        try:execute_sandbox('editor.visual',[source],{'commands':[edit(UZ[2],'Yangi qator '*40)],'combined':True},tmp_path/'sandboxed',pdfcraft=True)
        except ProcessorError as error:sandboxed=error
    assert caught.value.code=='editor_text_too_long' and caught.value.index==0 and marker not in str(caught.value)
    assert sandboxed and sandboxed.code=='editor_text_too_long' and sandboxed.index==0 and marker not in str(sandboxed)
    assert marker not in caplog.text


def test_with_the_switch_off_the_binary_is_never_started(tmp_path,monkeypatch):
    started=tmp_path/'started'
    binary=tmp_path/'pdfcraft-cli';binary.write_text(f'#!/bin/sh\necho "$1" >> {shlex.quote(str(started))}\n');binary.chmod(0o755)
    monkeypatch.setenv('PDFMASTER_PDFCRAFT_BIN',str(binary))
    result,_=run(drawn(tmp_path/'uz.pdf',UZ),[edit(UZ[2],'Yangi qator')],tmp_path,pdfcraft=False)
    assert engines(result)==['covered'] and not started.exists()


def test_covered_words_sit_on_the_old_baseline_in_the_old_colour_and_face(tmp_path,monkeypatch):
    monkeypatch.delenv('PDFMASTER_PDFCRAFT_BIN',raising=False)
    rows=[Row('NotoSerif-Regular',14,72,90,'Hisobot oktabr oyida tayyorlandi.','#0b6e4f'),Row('NotoSans-Bold',14,72,120,'Xulosa va takliflar')]
    source=drawn(tmp_path/'styled.pdf',rows)
    result,path=run(source,[edit(rows[0],'Hisobot noyabr oyida tayyorlandi.'),edit(rows[1],'Xulosa')],tmp_path)
    assert engines(result)==['covered','covered']
    made=Page.read(path,1)
    serif=[c for c in made.letters if c['font'].endswith('NotoSerif-Regular') and abs(c['base']-90)<.3]
    bold=[c for c in made.letters if c['font'].endswith('NotoSans-Bold') and abs(c['base']-120)<.3]
    assert norm('Hisobot noyabr oyida tayyorlandi.') in ''.join(c['char'] for c in serif) and {c['color'] for c in serif}>={'#0b6e4f'}
    assert norm('Xulosa') in ''.join(c['char'] for c in bold)
    assert all(abs(c['size']-14)<.05 for c in serif+bold)


def test_an_empty_line_is_covered_with_nothing_drawn_on_it(tmp_path,monkeypatch):
    monkeypatch.delenv('PDFMASTER_PDFCRAFT_BIN',raising=False)
    source=drawn(tmp_path/'uz.pdf',UZ)
    result,path=run(source,[edit(UZ[1],'')],tmp_path)
    assert engines(result)==['blanked'],'no word is set in another face: the web counts none'
    page=pixels(path);scale=100/72
    assert page[int((UZ[1].y-9)*scale):int((UZ[1].y+2)*scale),int(72*scale):int(300*scale)].min()>=250


def test_a_box_off_the_page_is_refused_naming_the_change(tmp_path):
    source=drawn(tmp_path/'uz.pdf',UZ)
    with pytest.raises(ProcessorError) as caught:
        run(source,[{'type':'note','page':1,'x':5,'y':5,'text':'a'},{**edit(UZ[1],'b'),'x':590,'width':50}],tmp_path)
    assert caught.value.code=='editor_out_of_bounds' and caught.value.index==1


def test_retype_is_never_a_callers_kind():
    with pytest.raises(ProcessorError):
        normalize('editor.visual',{'commands':[{'type':'retype','page':1,'x':1,'y':1,'width':1,'height':1,'left':1,'baseline':1,'size':9,'color':'#000000','font':'sans','bold':False,'text':'a','cover':None}],'combined':True})


# The pure parts: matching, reading the style, and the look at the page.

def letters(text,x=72.0,base=100.0,size=10.0,font='AAAAAA+NotoSans-Regular',color='#000000',advance=5.0,flags=4):
    found=[]
    for char in text:
        if not char.isspace():
            found.append({'char':norm(char) or char,'left':x,'right':x+advance-.5,'top':base-.7*size,'bottom':base+.2*size,'x':x,'base':base,'size':size,'font':font,'flags':flags,'color':color})
        x+=advance
    return found


def line(number,text,x=72.0,base=100.0,size=10.0,advance=5.0,font='AAAAAA+NotoSans-Regular'):
    return {'line':number,'text':text,'rect':[x,base-1.069*size,x+advance*len(text),base+.293*size],'size':size,'font':font}


def blank(width=300,height=200):
    return numpy.full((int(height*100/72)+1,int(width*100/72)+1,3),255,dtype=numpy.int16)


def page_of(*groups,width=300,height=200,picture=None):
    return Page(width,height,[letter for group in groups for letter in group],blank(width,height) if picture is None else picture)


def test_norm_compares_words_the_way_they_read():
    assert norm(' O‘zbekiston ') == norm("O'zbekiston") == norm('Oʻzbekiston') == norm('O’zbekiston') == norm('Oʼzbekiston')
    assert norm('\ufb01le\xad name\n') == 'filename' and norm('a\u00a0b\tc') == 'abc'


def test_families_and_their_twins():
    assert family('ABCDEF+Arial-BoldMT')=='arial' and family('TimesNewRomanPSMT')=='timesnewroman' and family('')==''
    assert close('helvetica',{'arial'}) and close('arial',{'helvetica'}) and close('times',{'timesnewroman'})
    assert not close('bizudpgothic',{'notosans'}) and not close('',{'notosans'})


def test_changed_finds_the_new_letters():
    assert changed('Buyuk ipak','Буюк ipak')==(0,4) and changed('abc','abc')==(3,3) and changed('kitob','kitoblar')==(5,8)


def test_a_command_matches_the_runs_that_say_its_words():
    page=page_of(letters('Salom dunyo'),letters('Boshqa qator',base=114))
    lines=[line(1,'Salom '),line(2,'dunyo',x=102),line(3,'Boshqa qator',base=114)]
    command={'page':1,'x':72,'y':100-9.5,'width':55,'height':12.5,'original':'Salom dunyo','text':'x'}
    assert [found['line'] for found in match(lines,command,page)]==[1,2]
    assert match(lines,{**command,'original':'Salom'},page)==[lines[0]]
    assert match(lines,{**command,'original':'Boshqa qator'},page) is None,'the row below is not this box\'s'
    assert match(lines,{**command,'original':'Hech narsa'},page) is None
    assert match(lines,{**command,'x':200},page) is None,'a box beside the runs matches none'


def test_a_paragraph_row_is_found_with_what_stands_before_and_after():
    lines=[line(1,'Ism: '),line(2,'Ali',x=97),line(3,' Valiyev',x=112),line(4,'Ikkinchi qator',base=114)]
    paragraph={'paragraph':1,'editor_text':'Ism: Ali Valiyev\nIkkinchi qator','rows':[[1,2,3],[4]],'rect':[72,89,190,118]}
    assert row_of([paragraph],[lines[1]],lines)==(paragraph,0,'Ism: ',' Valiyev')
    assert row_of([paragraph],[lines[0],lines[2]],lines) is None,'not one stretch of the row'
    assert row_of([{**paragraph,'editor_text':'Ism:Ali Valiyev\nIkkinchi qator'}],[lines[1]],lines) is None


def clean_edit(**changes):
    """A line edited cleanly, before and after; `changes` spoil the after."""
    before=page_of(letters('Salom dunyo'),letters('Pastki qator',base=120))
    lines_before=[line(1,'Salom dunyo'),line(2,'Pastki qator',base=120)]
    after_letters=changes.get('letters',letters('Salom olam'))
    after=page_of(after_letters,letters('Pastki qator',base=120),picture=changes.get('picture'))
    lines_after=changes.get('lines',[line(1,'Salom olam'),line(2,'Pastki qator',base=120)])
    return check_edit(before,after,lines_before,lines_after,{1},'Salom dunyo','Salom olam',allowed=changes.get('allowed',()))


def test_a_clean_edit_passes_every_check():
    assert clean_edit()==set()


@pytest.mark.parametrize('spoilt,fault',[
    ({'letters':letters('Salom ola')},'text'),
    ({'letters':letters('Salom olam')+letters('o',x=123.5)},'text'),
    ({'lines':[line(1,'Salom olam')]},'others'),
    ({'lines':[line(1,'Salom olam'),line(2,'Pastki qator',base=121)]},'others'),
    ({'lines':[{**line(1,'Salom olam'),'rect':[72,89,295,103]},line(2,'Pastki qator',base=120)]},'fit'),
    ({'letters':letters('Salom')+letters('olam',x=102,font='BIZUDPGothic-Regular')},'font_new'),
    ({'letters':letters('Salom')+letters('olam',x=102,font='')},'type3'),
    ({'letters':letters('Salom',font='Helvetica')+letters('olam',x=102)},'font_kept'),
    ({'letters':letters('Salom olam',base=101)},'baseline'),
    ({'letters':letters('Salom olam',size=12)},'size'),
    ({'letters':letters('Salom olam',color='#ff0000')},'color'),
],ids=['short','left-behind','gone','moved','off-the-page','fallback-face','type3','kept-letters','baseline','size','colour'])
def test_each_check_catches_its_fault(spoilt,fault):
    assert fault in clean_edit(**spoilt)


def test_each_letter_keeps_its_own_colour_and_weight_and_new_ones_take_those_they_replace():
    before=page_of(letters('Salom ',font='X+NotoSans-Bold'),letters('dunyo',x=102,color='#c00000'))
    lines_before=[line(1,'Salom '),line(2,'dunyo',x=102)]
    def look(after):
        return check_edit(before,page_of(after),lines_before,[line(1,'Salom '),line(2,'olam',x=102)],{1,2},'Salom dunyo','Salom olam')
    assert look(letters('Salom ',font='X+NotoSans-Bold')+letters('olam',x=102,color='#c00000'))==set()
    assert look(letters('Salom ',font='X+NotoSans-Bold')+letters('olam',x=102))=={'color'},'the new word took the run before it'
    assert look(letters('Salom ',font='X+NotoSans-Bold')+letters('olam',x=102,color='#c00000',font='X+NotoSans-Bold'))=={'style'}
    assert look(letters('Salom ')+letters('olam',x=102,color='#c00000'))=={'style'},'a kept letter lost its weight'


def test_new_letters_may_be_in_the_imported_face():
    spoilt=letters('Salom')+letters('olam',x=102,font='NotoSans-Regular')
    assert 'font_new' not in clean_edit(letters=spoilt,allowed={'notosans'}) and 'font_new' in clean_edit(letters=[{**c,'font':'X+Inter'} for c in spoilt])


def test_pixels_changed_away_from_the_row_or_over_a_neighbours_ink_are_faults():
    far=blank();far[200:240,300:340]=0
    assert 'outside' in clean_edit(picture=far)
    near=blank();near[130:140,int(100*100/72):int(110*100/72)]=0
    assert 'outside' not in clean_edit(picture=near),'inside the row\'s padded box'
    before=page_of(letters('Salom dunyo'));inked=blank();inked[125:140,250:300]=0;before.pixels=inked
    after=page_of(letters('Salom olam'))
    faults=check_edit(before,after,[line(1,'Salom dunyo')],[line(1,'Salom olam')],{1},'Salom dunyo','Salom olam')
    assert 'collide' in faults


def test_a_removal_must_leave_nothing_of_the_row_and_change_nothing_else():
    before=page_of(letters('Salom dunyo'),letters('Pastki qator',base=120));lines_before=[line(1,'Salom dunyo'),line(2,'Pastki qator',base=120)]
    gone=page_of(letters('Pastki qator',base=120))
    assert check_removal(before,gone,lines_before,[line(1,'Pastki qator',base=120)],{1})==set()
    assert 'text' in check_removal(before,page_of(letters('Salom'),letters('Pastki qator',base=120)),lines_before,[line(2,'Pastki qator',base=120)],{1})
    assert 'others' in check_removal(before,page_of(),lines_before,[],{1})


def test_the_style_of_the_old_words():
    page=page_of(letters('Hisobot',font='ABCDEF+NotoSerif-Bold',color='#0b6e4f',size=14),letters('Boshqa',x=200,size=14))
    command={'page':1,'x':72,'y':100-.95*14,'width':35,'height':1.25*14,'original':'Hisobot','text':'x'}
    style=style_of(page,command)
    assert (style['family'],style['bold'],style['color'],style['size'],style['base'],style['left'])==('serif',True,'#0b6e4f',14,100,72)
    assert face_of(style).name=='NotoSerif-Bold.ttf'
    assert style_of(page,command,[{**line(1,'Hisobot',size=14),'size':13.5}])['size']==13.5,'PdfCraft\'s size wins'
    sans=style_of(page_of(letters('Ab',font='MicrosoftSansSerif',flags=2)),{**command,'width':10})
    assert sans['family']=='sans' and not sans['bold']
    # Weight comes from the name or the force-bold flag: pdfium's weight reads 625 for Chrome's regular Noto Sans.
    assert style_of(page_of(letters('Ab',font='BAAAAA+NotoSans-Regular',flags=text_edit.FORCE_BOLD)),{**command,'width':10})['bold']
    assert face_of(style,bold=False).name=='NotoSerif-Regular.ttf'
    assert face_of({**sans,'font':'Helvetica'}).name=='LiberationSans-Regular.ttf'
    empty=style_of(page_of(),command)
    assert empty['size']==14 and abs(empty['base']-(command['y']+.76*command['height']))<1e-9 and empty['color']=='#000000'


def test_the_room_ends_short_of_the_next_words_and_the_margin():
    page=page_of(letters('Chap'),letters('Ong',x=200))
    command={'page':1,'x':72,'y':90.5,'width':20,'height':12.5,'original':'Chap','text':'x'}
    style=style_of(page,command)
    assert room(page,style,command)==200-1-72
    alone=page_of(letters('Chap'))
    assert room(alone,style_of(alone,command),command)==300-text_edit.MARGIN-72


def test_retyped_words_shrink_to_fit_and_past_the_smallest_size_are_refused():
    style={'left':72,'base':100,'size':10,'color':'#000000','family':'sans','bold':False}
    wide=stringWidth('Salom dunyo','NotoSans-Regular',10)
    command={'page':1,'x':72,'y':90.5,'width':wide,'height':12.5,'original':'Salom dunyo'}
    assert (overlay(command,style,'Salom dunyo',wide+1)['size'],overlay(command,style,'Salom dunyo',wide+1)['narrow'])==(10,1)
    assert abs(overlay(command,style,'Salom dunyo',wide*.8)['size']-8)<1e-6
    with pytest.raises(ProcessorError) as caught:overlay(command,style,'Salom dunyo',wide*.5)
    assert caught.value.code=='editor_text_too_long'
    # Never under 6 pt, however much smaller the line was asked to be.
    small=stringWidth('Salom dunyo','NotoSans-Regular',8)
    with pytest.raises(ProcessorError):overlay({**command,'width':small},{**style,'size':8},'Salom dunyo',small*.7)
    covered=overlay(command,style,'',0,cover=([70,89,130,104],'#F0F0F0'))
    assert covered['cover']=='#F0F0F0' and covered['text']=='' and covered['width']==60


def web_guess(width,old,new):
    """The web's guess at new words' width on a line (useEditorTextLayer editTextFit): the line's own width by the Noto Sans widths of new over old."""
    return width*stringWidth(new,'NotoSans-Regular',10)/stringWidth(old,'NotoSans-Regular',10)


def test_words_the_web_lets_through_are_set_smaller_and_narrowed_never_refused_though_noto_is_wider():
    # A Times line: the web's guess is the width in Times, Noto Serif draws them a sixth wider.
    style={'left':72,'base':100,'size':10,'color':'#000000','family':'serif','bold':False}
    old,new='Jami daromad','Jami yillik daromad miqdori';width=stringWidth(old,'Times-Roman',10)
    command={'page':1,'x':72,'y':90.5,'width':width,'height':12.5,'original':old}
    space=.65*web_guess(width,old,new);noto=stringWidth(new,'NotoSerif-Regular',10)
    assert space/noto<text_edit.SMALLEST,'measured in Noto alone, this was refused'
    mark=overlay(command,style,new,space)
    assert mark['size']==6 and mark['narrow']<1 and abs(noto*.6*mark['narrow']-space)<1e-6,'the smallest size, narrowed to the room'
    with pytest.raises(ProcessorError):overlay(command,style,new,.55*web_guess(width,old,new))


@pytest.mark.parametrize('switch',[pytest.param(True,marks=REQUIRES_PDFCRAFT,id='retyped'),pytest.param(False,id='covered')])
def test_a_times_line_the_web_says_will_be_set_a_little_smaller_is_sent(tmp_path,monkeypatch,switch):
    if not switch:monkeypatch.delenv('PDFMASTER_PDFCRAFT_BIN',raising=False)
    line=Row('Times-Roman',12,72,200,'Hisobot oktabr oyida tayyorlandi va rahbariyatga taqdim etildi.')
    new=line.text[:-1]+', keyin esa barcha bo‘limlar boshliqlariga yuborildi va yig‘ilishda batafsil muhokama qilindi.'
    web=(W-text_edit.MARGIN-line.x)/web_guess(stringWidth(line.text,line.font,line.size),line.text,new)
    assert text_edit.SMALLEST<=web<.72 and (W-text_edit.MARGIN-line.x)/stringWidth(new,'NotoSerif-Regular',12)<text_edit.SMALLEST,'longer on the web, past 60 % in Noto'
    source=drawn(tmp_path/'times.pdf',[*EN,line])
    result,path=run(source,[edit(line,new)],tmp_path,pdfcraft=switch)
    assert engines(result)==['retyped' if switch else 'covered']
    drawn_in=[c for c in Page.read(path,1).letters if abs(c['base']-line.y)<.3 and c['font'].endswith('NotoSerif-Regular')]
    assert ''.join(c['char'] for c in drawn_in)==norm(new) and max(c['right'] for c in drawn_in)<=W-text_edit.MARGIN+.5
    assert all(abs(c['size']-text_edit.SMALLEST*12)<.05 for c in drawn_in),'at 60 %, narrowed to the room'
    assert norm(EN[1].text) in norm(text_of(path))


@REQUIRES_PDFCRAFT
def test_two_changes_on_one_page_that_need_the_same_imported_face_both_keep_the_documents_font(tmp_path):
    rows=[Row('Helvetica',11,72,100+20*index,f'Plain words in row {index}') for index in range(3)]
    source=drawn(tmp_path/'rows.pdf',rows)
    commands=[edit(row,row.text.replace('Plain','Простые')) for row in rows]
    result,path=run(source,commands,tmp_path)
    assert engines(result)==['pdfcraft-noto']*3,'the face the first change imported serves the rest'
    assert all(norm(command['text']) in norm(text_of(path)) for command in commands) and not type3(path)
    kept=[c for c in Page.read(path,1).letters if c['char'] in 'wordsinrw']
    assert kept and {family(c['font']) for c in kept}=={'helvetica'},'the letters kept are the document\'s own'


def test_a_face_already_on_the_page_is_found_in_its_listing_when_the_import_names_none():
    regular,bold=FONTS/'LiberationSans-Regular.ttf',FONTS/'LiberationSans-Bold.ttf'
    def report(answer,fonts,status='ok'):
        return {'ok':status=='ok','steps':[{'status':'ok','result':[{}]},{'status':'ok','result':[{}]},{'status':status,'result':[answer]},{'status':'ok','result':[{'fonts':fonts}]}]}
    listed=[{'font':'LiberationSans','full_face':False,'resource':'F2+0'},{'font':'LiberationSans-Bold','full_face':True,'resource':'PCFull1'},{'font':'LiberationSans','full_face':True,'resource':'PCFull0'}]
    assert imported(report({'font':'LiberationSans','resource':'PCFull2'},[]),regular)=='PCFull2'
    # PdfCraft answers an import of a face the page holds whole with no resource (no `font` either).
    assert imported(report({'undo':'Load document font'},listed),regular)=='PCFull0'
    assert imported(report({'undo':'Load document font'},listed),bold)=='PCFull1'
    assert imported(report({'undo':'Load document font'},listed[:1]),regular) is None,'a subset of the document is not the whole face'
    assert imported(report({},listed,status='error'),regular) is None


def ocr_page(path):
    """A scan's page as OCR leaves it, made up: a heading drawn in Helvetica, and a line in the same font drawn out of sight (render mode 3)."""
    canvas=Canvas(str(path),pagesize=(W,H));canvas.setFont('Helvetica',14);canvas.drawString(72,H-80,'Hisobot sarlavhasi')
    words=canvas.beginText(72,H-120);words.setFont('Helvetica',11);words.setTextRenderMode(3);words.textOut('skanerlangan sahifa matni');canvas.drawText(words)
    canvas.showPage();canvas.save()
    return path,Row('Helvetica',11,72,120,'skanerlangan sahifa matni')


def test_letters_drawn_out_of_sight_are_known(tmp_path):
    source,_=ocr_page(tmp_path/'ocr.pdf');letters=Page.read(source,1).letters
    assert {c['unseen'] for c in letters if abs(c['base']-120)<.5}=={True} and {c['unseen'] for c in letters if abs(c['base']-80)<.5}=={False}


@REQUIRES_PDFCRAFT
def test_a_line_drawn_out_of_sight_over_a_scan_is_covered_so_the_new_words_show(tmp_path):
    source,line=ocr_page(tmp_path/'ocr.pdf')
    result,path=run(source,[edit(line,'yangi sahifa matni')],tmp_path)
    assert engines(result)==['covered']
    shown=[c for c in Page.read(path,1).letters if abs(c['base']-line.y)<.3 and not c['unseen']]
    assert ''.join(c['char'] for c in shown)==norm('yangi sahifa matni')
    assert changed_outside(source,path)>0 and changed_outside(source,path,row_rect(line))==0,'the new words are seen, and only there'


def test_the_paper_colour_is_read_around_the_box():
    picture=blank();scale=100/72;picture[:,:]=(240,230,200);picture[int(95*scale):int(105*scale),int(100*scale):int(150*scale)]=0
    page=page_of(picture=picture)
    assert paper(page,[100,95,150,105])=='#F0E6C8'
    assert paper(Page(300,200,[],None),[100,95,150,105])=='#FFFFFF'
