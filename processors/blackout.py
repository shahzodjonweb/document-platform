"""Black-out that keeps a page's words as words: the stage before the text stage and every mark.

A box (`redact`) hides for good whatever lies under it. Here PdfCraft takes out the
text, pictures, drawing, notes and form fields under each box and draws the black
box in their place (`redact_mark`, `redact_apply`); the rest of the page stays as
it was, words that can still be found and copied. A page keeps that only after a
look at it, rendered before and after at 150 dpi, and read out every other way:

  left     a word that stood in a box can still be read: its letters, the page's
           text, or a note or field of the page that stayed
  others   something outside the boxes changed: PdfCraft takes the whole drawing
           a box touches (a table's border, a panel) and a whole note or field
  black    a box is not black all over
  refused  PdfCraft refused, failed or ran out of time
  parts    the file PdfCraft wrote lost a page, a field or a note elsewhere

Some pages go without trying, as nothing short of a picture is sure for them:

  scan     words drawn out of sight on the page (OCR over a scan): what shows is the picture
  image    a box over a picture, which PdfCraft would take whole
  mark     a box over another change of the same send, drawn after this stage on top of the black
  engine   PdfCraft is off or missing, or the file too large for it
  large    a page too large to look at closely
  invalid  a box the page cannot hold (only `check` says this; a send refuses it)

A page that does not keep its words becomes a picture of itself at the raster stage
(editor._raster_stage), and only with the customer's consent. `check` finds out
beforehand which pages will, from the same file and boxes, so a send can ask for
exactly those.

A note or field a box meets is first drawn into its page where it shows and taken
out (a field with all its value), so only the part under the box goes. A box made by
finding words (`text`) has PdfCraft find them again inside it and mark only their
own letters: the black is where the words are, not where the web estimated them. A
box with none of them is marked whole. PdfCraft takes every letter a box touches,
one mostly outside it too, so such a letter's going is no change outside the box.

The page's words stay in this process: what leaves it is pages, codes and numbers.
"""
from __future__ import annotations
import math
import shutil
import time
from pathlib import Path
from . import pdfcraft
from .text_edit import Page,norm

# Pages are looked at as rendered at 150 dpi, with their form fields drawn as a viewer fills them in.
SCALE=150/72
INK=40
# Changed pixels outside every box allowed at 150 dpi: anti-aliasing, never a line or a letter.
OUTSIDE=40
# Points around a box, and around a letter it took, where drawing the black blends with what is beside it.
PAD=1
# Points by which a found word may stand out of its box, and a box must reach into a picture to touch it.
NEAR=2
TOUCH=.25
BLACK=16
# Seconds of PdfCraft for black-out in a send or a check; the rest of a send's PdfCraft time is the text stage's.
BUDGET=25
MAX_BYTES=150*1024*1024
MAX_PAGES=500
# Pixels of pages held as they were before, while PdfCraft works: about 45 A4 pages. Past it a page is too large to look at.
LOOK_PIXELS=100_000_000
# Shorter words than this are too common to look for in the page's other carriers.
SHORTEST=3
# The rules a page's outcome follows: a stored outcome of other rules is not used (apps/studio/editor_blackout.py).
VERSION=1
# Annotation flags: hidden, not shown on screen, and kept upright however the page turns.
HIDDEN=2
NO_ROTATE=16
NO_VIEW=32
# Where a note or a field keeps words of its own.
WORDS=('/Contents','/RC','/Subj','/TU','/V','/DV')
# The other changes of a send that are drawn over the page after this stage.
DRAWN={'add_text','highlight','note','draw','signature','insert_image','whiteout','edit_text'}


def boxes(commands):
    """The black-out boxes of a send by source page, each with its command's index. A box on a page being deleted draws nothing."""
    from .editor import _deleted
    deleted=_deleted(commands);found={}
    for index,command in enumerate(commands):
        if command['type']=='redact' and command['page'] not in deleted:found.setdefault(command['page'],[]).append((index,command))
    return found


def _rect(command):
    return [command['x'],command['y'],command['x']+command['width'],command['y']+command['height']]


def _meets(a,b,slack=0.0):
    return min(a[2],b[2])-max(a[0],b[0])>slack and min(a[3],b[3])-max(a[1],b[1])>slack


def _within(point,rect,pad=0.0):
    return rect[0]-pad<=point[0]<=rect[2]+pad and rect[1]-pad<=point[1]<=rect[3]+pad


def _middle(letter):
    return (letter['left']+letter['right'])/2,(letter['top']+letter['bottom'])/2


def _reach(command):
    """Where another change of a send draws, in the frame boxes are placed in, or None for one that draws nowhere in particular."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from .editor import _text_font
    kind=command['type']
    if kind=='add_text':
        lines=command['text'].splitlines() or [''];size=command['font_size']
        return [command['x'],command['y'],command['x']+max(stringWidth(line,_text_font(command),size) for line in lines),command['y']+len(lines)*size*1.3]
    if kind=='note':return [command['x'],command['y'],command['x']+22,command['y']+22]
    if kind=='draw':
        half=command['stroke_width']/2;xs=[x for x,_ in command['points']];ys=[y for _,y in command['points']]
        return [min(xs)-half,min(ys)-half,max(xs)+half,max(ys)+half]
    # New words may run on to the right of their line's box, as far as the page lets them.
    if kind=='edit_text':return [command['x'],command['y'],math.inf,command['y']+command['height']]
    return _rect(command)


def marked(commands):
    """Pages where a box meets another change of the same send. That change is drawn after this stage, on top of the black; at the raster stage the box is drawn last.

    A picture changed by its number (replace_image, remove_image) is found again after
    PdfCraft has written the file: its page goes to a picture too.
    """
    found=boxes(commands);pages=set()
    for command in commands:
        page=command.get('page')
        if page not in found:continue
        if command['type'] in ('replace_image','remove_image'):pages.add(page)
        elif command['type'] in DRAWN:
            reach=_reach(command)
            if any(_meets(reach,_rect(box)) for _,box in found[page]):pages.add(page)
    return pages


class Blacked:
    """What the stage leaves the pipeline. `path` is the file the next stage reads; `vector` the pages PdfCraft blacked out;
    `raster` the others, each with its reason; `drawn` the rects blacked out by command index; `forgotten` the names of the
    fields taken out; `secrets` the words that went, which never leave this process."""
    def __init__(self,path):
        self.path,self.vector,self.raster,self.drawn,self.forgotten,self.secrets=Path(path),set(),{},{},set(),[]

    def outcome(self):
        """{page: 'vector' or the reason it becomes a picture}."""
        return {**{page:'vector' for page in self.vector},**self.raster}


def _held(holder,key,kind):
    from .editor import _held as held
    return held(holder,key,kind)


def _appearance(note):
    """The picture a viewer shows of a note or field, or None when it has none of its own."""
    from pypdf.generic import DictionaryObject,StreamObject
    looks=_held(note,'/AP',DictionaryObject)
    normal=looks.get('/N') if looks is not None else None
    normal=normal.get_object() if normal is not None else None
    if isinstance(normal,StreamObject):return normal
    if isinstance(normal,DictionaryObject):
        state=note.get('/AS');chosen=normal.get(state) if state is not None else None
        chosen=chosen.get_object() if chosen is not None else None
        if isinstance(chosen,StreamObject):return chosen
    return None


def _placement(look,rect):
    """The matrix that sets an appearance on its note's /Rect, as a viewer does (ISO 32000 12.5.5), or None for one with no box."""
    from .editor import _numbers
    frame=_numbers(look.get('/BBox'));matrix=_numbers(look.get('/Matrix'))
    if len(frame)!=4:return None
    a,b,c,d,e,f=matrix if len(matrix)==6 else (1,0,0,1,0,0)
    corners=[(a*x+c*y+e,b*x+d*y+f) for x in frame[::2] for y in frame[1::2]]
    x0,x1=min(p[0] for p in corners),max(p[0] for p in corners);y0,y1=min(p[1] for p in corners),max(p[1] for p in corners)
    if x1-x0<=0 or y1-y0<=0:return None
    sx,sy=(rect[2]-rect[0])/(x1-x0),(rect[3]-rect[1])/(y1-y0)
    return sx,sy,rect[0]-sx*x0,rect[1]-sy*y0


def _prune(writer,ids):
    """Takes the widgets with these object numbers out of the form's fields, with any field left with none."""
    from pypdf.generic import ArrayObject,NameObject
    form=writer.root_object.get('/AcroForm')
    if not ids or form is None:return
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


def _flatten(source,target,found):
    """Each note and field a box meets, drawn into its page where it shows and then taken out. Returns the names of the fields taken out, or None when no box meets one."""
    from pypdf import PdfWriter
    from pypdf.generic import ArrayObject,DecodedStreamObject,DictionaryObject,NameObject,StreamObject
    from .editor import _numbers,_qualified_field_name,_rotated_box
    writer=PdfWriter(clone_from=str(source));forgotten=set();changed=False
    # A field's picture may name fonts it does not hold: a viewer finds them in the form's own (/DR).
    form=writer.root_object.get('/AcroForm');form=form.get_object() if form is not None else None
    lent=form.get('/DR') if isinstance(form,DictionaryObject) else None
    for number,rows in found.items():
        page=writer.pages[number-1];notes=_held(page,'/Annots',ArrayObject)
        if not notes:continue
        width,height=float(page.mediabox.width),float(page.mediabox.height);turn=int(page.rotation or 0)%360
        # Boxes are placed on the page as shown; notes stand in its own frame, from its bottom left.
        frames=[]
        for _,command in rows:
            x,y,w,h=_rotated_box(command,width,height,(360-turn)%360)
            frames.append([x,height-y-h,x+w,height-y])
        kept,gone,shown=[],[],[]
        for ref in notes:
            note=ref.get_object();rect=_numbers(note.get('/Rect')) if isinstance(note,DictionaryObject) else []
            if len(rect)!=4:
                kept.append(ref);continue
            left,right=sorted(rect[::2]);bottom,top=sorted(rect[1::2])
            if not any(_meets([left,bottom,right,top],frame) for frame in frames):
                kept.append(ref);continue
            gone.append(ref);flags=int(_held(note,'/F',object) or 0)
            look=_appearance(note)
            if look is not None and not flags&(HIDDEN|NO_VIEW) and not (turn and flags&NO_ROTATE) and note.get('/Subtype') not in ('/Popup','/Link') and '/OC' not in note:
                placed=_placement(look,[left,bottom,right,top])
                if placed:shown.append((look,placed))
        if not gone:continue
        changed=True
        ids={ref.idnum for ref in gone if hasattr(ref,'idnum')}
        # A note's pop-up goes with it, and a pop-up that went is no longer its note's.
        for ref in kept:
            note=ref.get_object()
            if not isinstance(note,DictionaryObject):continue
            parent=note.get('/Parent')
            if note.get('/Subtype')=='/Popup' and getattr(parent,'idnum',None) in ids:ids.add(ref.idnum)
            elif getattr(note.get('/Popup'),'idnum',None) in ids:del note['/Popup']
        kept=[ref for ref in kept if getattr(ref,'idnum',None) not in ids]
        for ref in gone:
            note=ref.get_object()
            if note.get('/Subtype')=='/Widget':forgotten.add(_qualified_field_name(note))
        _prune(writer,ids)
        page[NameObject('/Annots')]=ArrayObject(kept)
        if shown:
            resources=page.get('/Resources');resources=DictionaryObject(resources.get_object()) if resources is not None else DictionaryObject()
            drawings=resources.get('/XObject');drawings=DictionaryObject(drawings.get_object()) if drawings is not None else DictionaryObject()
            operations=[]
            for look,(sx,sy,tx,ty) in shown:
                if not isinstance(look,StreamObject):continue
                look[NameObject('/Subtype')]=NameObject('/Form')
                if '/Resources' not in look and lent is not None:look[NameObject('/Resources')]=lent
                name=NameObject(f'/DMShown{len(drawings)}')
                while name in drawings:name=NameObject(name+'x')
                drawings[name]=look.indirect_reference if look.indirect_reference is not None else writer._add_object(look)
                operations.append(f'q {sx:.6f} 0 0 {sy:.6f} {tx:.6f} {ty:.6f} cm {name} Do Q')
            resources[NameObject('/XObject')]=drawings;page[NameObject('/Resources')]=resources
            # The page's own drawing in a q/Q of its own, as it may leave the state changed.
            before,after=DecodedStreamObject(),DecodedStreamObject()
            before.set_data(b'q\n');after.set_data(('\nQ\n'+'\n'.join(operations)+'\n').encode())
            contents=page.get('/Contents');contents=contents.get_object() if contents is not None else None
            old=list(page['/Contents']) if isinstance(contents,ArrayObject) else ([page.raw_get('/Contents')] if contents is not None else [])
            page[NameObject('/Contents')]=ArrayObject([writer._add_object(before),*old,writer._add_object(after)])
    if not changed:return None
    with Path(target).open('xb') as stream:writer.write(stream)
    return forgotten


def _strings(node):
    """The words a note or field keeps besides its picture: its own and, for a widget, those of the fields above it."""
    from pypdf.generic import DictionaryObject,StreamObject
    found=[];seen=0
    while isinstance(node,DictionaryObject) and seen<25:
        for key in WORDS:
            value=node.get(key);value=value.get_object() if value is not None else None
            if isinstance(value,StreamObject):
                try:value=value.get_data().decode('utf-8','ignore')
                except Exception:value=''
            if isinstance(value,str):found.append(value)
        parent=node.get('/Parent');node=parent.get_object() if parent is not None else None;seen+=1
    return found


def _counts(text,secrets):
    return {secret:text.count(secret) for secret in secrets}


class _Look:
    """One page before any change: as rendered and read, its pictures, the words PdfCraft found in it, and its boxes."""
    def __init__(self,number,rows,page,text):
        self.number,self.rows,self.page,self.text=number,rows,page,text
        self.pictures=[];self.found={}


def _secret(look,command,rect):
    """The words a box hides: those it was made by finding, else the letters that stood in it."""
    if command.get('text'):return norm(command['text'])
    return ''.join(c['char'] for c in look.page.letters if _within(_middle(c),rect))


def _targets(look):
    """What each box of the page has PdfCraft mark: the found words' own rects inside it, else the box."""
    marks={}
    for index,command in look.rows:
        box=_rect(command);own=[]
        for rects in look.found.get(index,()):
            if all(_within(((r[0]+r[2])/2,(r[1]+r[3])/2),box,NEAR) for r in rects):own.extend(rects)
        marks[index]=[list(map(float,r)) for r in own] or [box]
    return marks


def _verify(look,after,made,marks,secrets):
    """The checks a page PdfCraft blacked out fails, from the page before and after: none when it keeps its words."""
    import numpy
    from pypdf.generic import ArrayObject,DictionaryObject
    from .editor import _numbers
    faults=set();rects=[rect for row in marks.values() for rect in row]
    boxes=[_rect(command) for _,command in look.rows]
    if any(c['unseen'] for c in after.letters) or any(any(_within(_middle(c),rect) for rect in rects) for c in after.letters):faults.add('left')
    said=norm(made.extract_text())
    before,now=_counts(look.text,secrets),_counts(said,secrets)
    for secret in secrets:
        if len(secret)>=2 and now[secret]>max(0,before[secret]-secrets.count(secret)):faults.add('left')
    height=float(made.mediabox.height);width=float(made.mediabox.width)
    for ref in _held(made,'/Annots',ArrayObject) or ():
        note=ref.get_object();rect=_numbers(note.get('/Rect')) if isinstance(note,DictionaryObject) else []
        if len(rect)==4 and not made.rotation:
            left,right=sorted(rect[::2]);bottom,top=sorted(rect[1::2])
            if any(_meets([left,height-top,right,height-bottom],box) for box in [*boxes,*rects]):faults.add('left')
        words=norm(' '.join(_strings(note)))
        if any(len(secret)>=SHORTEST and secret in words for secret in secrets):faults.add('left')
    if look.page.pixels is None or after.pixels is None or look.page.pixels.shape!=after.pixels.shape:
        faults.add('others');return faults
    scale=look.page.scale;changes=numpy.abs(look.page.pixels.astype(numpy.int16)-after.pixels).max(axis=2)>INK
    def clear(rect,pad):
        changes[max(0,int((rect[1]-pad)*scale)):max(0,math.ceil((rect[3]+pad)*scale)),max(0,int((rect[0]-pad)*scale)):max(0,math.ceil((rect[2]+pad)*scale))]=False
    for rect in rects:clear(rect,PAD)
    # A letter a box touched goes whole.
    for c in look.page.letters:
        glyph=[c['left'],c['top'],c['right'],c['bottom']]
        if any(_meets(glyph,rect) for rect in rects):clear(glyph,PAD)
    if int(changes.sum())>OUTSIDE:faults.add('others')
    tall,wide=after.pixels.shape[:2]
    for rect in rects:
        left,top=max(0,math.ceil(rect[0]*scale)+1),max(0,math.ceil(rect[1]*scale)+1)
        right,bottom=min(wide,math.floor(rect[2]*scale)-1),min(tall,math.floor(rect[3]*scale)-1)
        if right<=left:left=min(wide-1,max(0,int((rect[0]+rect[2])/2*scale)));right=left+1
        if bottom<=top:top=min(tall-1,max(0,int((rect[1]+rect[3])/2*scale)));bottom=top+1
        if int(after.pixels[top:bottom,left:right].max())>BLACK:faults.add('black')
    return faults


def _keeps_its_parts(source,made,pages,forgotten):
    """Whether PdfCraft's file, which it writes whole, holds every page the source had, every field but those taken out, and every note on the pages without a box."""
    from pypdf import PdfReader
    from .engine import _pdf_reader
    def notes(page):
        found=page.get('/Annots')
        return len(found.get_object()) if found is not None else 0
    try:
        first,second=PdfReader(source),_pdf_reader(made,allow_forms=True)
        return (len(first.pages)==len(second.pages) and set(first.get_fields() or {})-forgotten==set(second.get_fields() or {})
                and all(notes(one)==notes(other) for number,(one,other) in enumerate(zip(first.pages,second.pages),1) if number not in pages))
    except Exception:
        return False


class _Run:
    def __init__(self,source,root,executable):
        self.root,self.executable,self.deadline,self.count=Path(root),executable,time.monotonic()+BUDGET,0
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        # PdfCraft reads and writes only under its root.
        self.source=self.root/'source.pdf';shutil.copyfile(source,self.source)

    def left(self):
        return self.deadline-time.monotonic()

    def run(self,steps):
        return pdfcraft.run(self.executable,steps,self.root,timeout=max(1,min(pdfcraft.SECONDS,self.left())))

    def look(self,looks):
        """Each page's pictures and, for a box made by finding words, where PdfCraft finds them on its page."""
        steps=[{'tool':'doc_open','args':{'path':str(self.source)}}];asks=[]
        for look in looks:
            steps.append({'tool':'page_images','args':{'doc':1,'page':look.number}});asks.append((look,None))
            for index,command in look.rows:
                if norm(command.get('text')):
                    steps.append({'tool':'text_find','args':{'doc':1,'query':command['text'],'start_page':look.number,'limit':200}});asks.append((look,index))
        report=self.run(steps)
        for step,(look,index) in enumerate(asks,1):
            answer=pdfcraft.result(report,step) or {}
            if index is None:
                look.pictures=[p['visible_rect'] for p in answer.get('images') or () if isinstance(p,dict) and p.get('kind')=='image' and isinstance(p.get('visible_rect'),list) and len(p['visible_rect'])==4]
            else:
                look.found[index]=[match['rects'] for match in answer.get('matches') or () if isinstance(match,dict) and match.get('page')==look.number
                                   and isinstance(match.get('rects'),list) and match['rects'] and all(isinstance(r,list) and len(r)==4 and all(type(v) in (int,float) for v in r) for r in match['rects'])]

    def apply(self,looks,marks):
        """One run: the pages' notes and fields under a box drawn in and taken out, then PdfCraft's marks applied. (file, fields taken out), or None when PdfCraft refused."""
        self.count+=1
        flat=self.root/f'flat-{self.count}.pdf';target=self.root/f'blacked-{self.count}.pdf'
        forgotten=_flatten(self.source,flat,{look.number:look.rows for look in looks})
        opened=flat if forgotten is not None else self.source
        steps=[{'tool':'doc_open','args':{'path':str(opened)}}]
        for look in looks:
            for index,_ in look.rows:
                for rect in marks[look.number][index]:steps.append({'tool':'redact_mark','args':{'doc':1,'page':look.number,'rect':rect,'fill':'#000000'}})
        steps+=[{'tool':'redact_apply','args':{'doc':1,'pages':sorted(look.number for look in looks)}},{'tool':'doc_save','args':{'doc':1,'path':str(target)}}]
        try:report=self.run(steps)
        finally:flat.unlink(missing_ok=True)
        if report.get('ok') is not True or not all(isinstance(step,dict) and step.get('status')=='ok' for step in report['steps']) or not target.is_file():
            target.unlink(missing_ok=True);return None
        return target,forgotten or set()


def run(source,commands,root,allowed,skip=()):
    """Blacks out every box of a send that PdfCraft can, page by page: a Blacked. `allowed` is the pdfcraft switch; `root` a private folder; `skip` pages that go to pictures whatever happens (`marked`).

    Raises editor's errors, with the command's index, for a box its page cannot hold.
    """
    import pypdfium2 as pdfium
    from pypdf import PdfReader
    from .editor import _geometry,_rotated_box
    from .engine import ProcessorError
    source,root=Path(source),Path(root);found=boxes(commands);done=Blacked(source)
    if not found:return done
    reader=PdfReader(source)
    for number,rows in found.items():
        page=reader.pages[number-1];turn=int(page.rotation or 0)%360
        for index,command in rows:
            # Placed on the page as shown: held to the page's own frame, it is turned back first.
            x,y,w,h=_rotated_box(command,float(page.mediabox.width),float(page.mediabox.height),(360-turn)%360)
            try:_geometry(page,{**command,'x':x,'y':y,'width':w,'height':h})
            except ProcessorError as error:
                error.index=index;raise
    # Its version is asked inside the root, where it runs.
    if allowed:root.mkdir(parents=True,exist_ok=True,mode=0o700)
    executable=pdfcraft.binary(root) if allowed and source.stat().st_size<=MAX_BYTES and len(reader.pages)<=MAX_PAGES else None
    for number in found:
        if number in skip:done.raster[number]='mark'
        elif executable is None:done.raster[number]='engine'
    pending=[number for number in found if number not in done.raster]
    if not pending:return done
    import numpy
    looks=[];held=0
    for number in pending:
        try:page=Page.read(source,number,SCALE,forms=True)
        except pdfium.PdfiumError:
            done.raster[number]='refused';continue
        held+=page.pixels.shape[0]*page.pixels.shape[1] if page.pixels is not None else 0
        page.pixels=page.pixels.astype(numpy.uint8) if page.pixels is not None else None
        if page.scale<SCALE-1e-9 or held>LOOK_PIXELS:done.raster[number]='large'
        # Words laid out of sight over a scan: what shows is the picture under them.
        elif any(c['unseen'] for c in page.letters):done.raster[number]='scan'
        else:looks.append(_Look(number,found[number],page,norm(reader.pages[number-1].extract_text())))
    if not looks:return done
    work=_Run(source,root,executable)
    try:work.look(looks)
    except pdfcraft.Failed:
        for look in looks:done.raster[look.number]='refused'
        return done
    for look in list(looks):
        if any(_meets(_rect(command),picture,TOUCH) for _,command in look.rows for picture in look.pictures):
            done.raster[look.number]='image';looks.remove(look)
    marks={look.number:_targets(look) for look in looks}
    secrets={look.number:[_secret(look,command,_rect(command)) for _,command in look.rows] for look in looks}
    # Pages that fail go to pictures and the rest are tried again on their own, as PdfCraft writes the file whole.
    while looks:
        if work.left()<=1:
            for look in looks:done.raster[look.number]='refused'
            return done
        try:made=work.apply(looks,marks)
        except pdfcraft.Failed:made=None
        if made is None:
            for look in looks:done.raster[look.number]='refused'
            return done
        target,forgotten=made
        if not _keeps_its_parts(source,target,{look.number for look in looks},forgotten):
            target.unlink(missing_ok=True)
            for look in looks:done.raster[look.number]='parts'
            return done
        written=PdfReader(target);failed=[]
        for look in looks:
            try:after=Page.read(target,look.number,SCALE,forms=True)
            except pdfium.PdfiumError:
                failed.append((look,{'refused'}));continue
            faults=_verify(look,after,written.pages[look.number-1],marks[look.number],[s for s in secrets[look.number] if s])
            if faults:failed.append((look,faults))
        if not failed:
            done.path=target;done.vector={look.number for look in looks};done.forgotten=forgotten
            done.drawn={index:rects for look in looks for index,rects in marks[look.number].items()}
            done.secrets=[secret for look in looks for secret in secrets[look.number] if secret]
            return done
        target.unlink(missing_ok=True)
        for look,faults in failed:
            # One reason a page says, the gravest first.
            done.raster[look.number]=next(reason for reason in ('refused','left','black','others') if reason in faults)
            looks.remove(look)
    return done


def check(source,commands,root,allowed):
    """What a send would do with each page that has a box, found the way the send finds it: {page: 'vector' or why it becomes a picture}.

    A page whose box it cannot hold says 'invalid' (the send refuses it); a box over
    another change is the caller's to know, as it depends on the other changes alone.
    """
    from .engine import ProcessorError
    found=boxes(commands);invalid=set()
    while True:
        try:
            done=run(source,[c for c in commands if c['type']=='redact' and c['page'] not in invalid],root,allowed)
            break
        except ProcessorError as error:
            if error.index is None:raise
            kept=[c for c in commands if c['type']=='redact' and c['page'] not in invalid]
            invalid.add(kept[error.index]['page'])
            shutil.rmtree(root,ignore_errors=True)
    return {**done.outcome(),**{page:'invalid' for page in invalid if page in found}}
