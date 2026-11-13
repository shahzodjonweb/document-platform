"""Changes to a PDF's own words (edit_text): the stage before every mark.

Each change takes the first way whose result passes a look at the page as
rendered. PdfCraft's own `ok` is never trusted: it answers ok for a line run off
the page or set in a Japanese fallback face.

  pdfcraft       PdfCraft sets the new words in the line's own font: by line for
                 one run, by its paragraph with only that row changed for several
  pdfcraft-noto  the same, with the changed letters in an imported Noto face
                 (Liberation for Helvetica and Arial) the document's font lacks
  retyped        PdfCraft takes the old run(s) out and, once that is seen to be
                 clean, the new words are drawn where they stood in the nearest
                 Noto face, a little smaller when they need the room
  covered        the old words are painted over in the paper's colour and the new
                 ones drawn on top: only when PdfCraft is off, missing or refuses,
                 or its taking out failed the look, and always for words drawn out
                 of sight over a scan (OCR). The old words stay underneath.

A change with no words takes its line out: `removed` when PdfCraft took the runs
out, `blanked` when they are painted over and stay underneath. Neither sets a
word in another face, which is what the web counts retyped and covered rows for.
The stage works on the source file in source page numbers, before any page is
turned. The file it leaves is what the marks go on; retyped and covered words
come back as overlays the mark stage draws in the displayed frame, like any mark.

PdfCraft's report and the page's words stay in this process: what leaves the
stage is engines, codes and numbers.
"""
from __future__ import annotations
import ctypes
import math
import re
import shutil
import statistics
import time
import unicodedata
from collections import Counter
from functools import lru_cache
from pathlib import Path
from . import pdfcraft

# Pages are looked at in 100 dpi renders, where the pixel thresholds below were measured
# (scratchpad probe: they matched a person's judgement on 70 edits).
SCALE=100/72
INK=40
OUTSIDE=60
COLLIDE=10
STRETCH=.08
BASELINE=.3
# How near the page's right edge new words may reach.
MARGIN=9
# Retyped words shrink to fit their room, to 60 % of their size and never under 6 pt.
SMALLEST=.6
FLOOR=6
# Points by which pdf.js and pdfium may read a line's ends apart: a change the web let through is refused only past this.
SLACK=1
# Text render modes that draw nothing: 3 is OCR's words laid unseen over a scan, 7 only clips.
UNSEEN={3,7}
# Seconds of PdfCraft before the remaining changes are covered: editor.visual has 90 in all.
BUDGET=60
MAX_BYTES=150*1024*1024
MAX_PAGES=500
# A page larger than this at 100 dpi is too large to look at closely: its changes are covered.
RENDER_PIXELS=12_000_000
FACES=Path(__file__).resolve().parent/'assets'/'fonts'
QUOTES=str.maketrans({mark:"'" for mark in '‘ʻ’ʼ'})
STANDARD=re.compile(r'(Helvetica|Times|Courier|Symbol|ZapfDingbats)\b')
SERIF=re.compile(r'times|serif|georgia|cambria|garamond|mincho|book|minion|palatino',re.I)
BOLD=re.compile(r'bold|black',re.I)
ITALIC=re.compile(r'italic|oblique',re.I)
# The PDF font flag a bold face may carry. pdfium's weight is no guide: Chrome's Noto Sans Regular reads 625, its Noto Serif Regular 704.
FORCE_BOLD=1<<18
# The engines that leave the old words in the file under the paper's colour: PdfCraft changed nothing for them.
PAINTED={'covered','blanked'}
# What another try by paragraph can mend: the letters' face (an imported one), colour or weight (said outright). A line too long for its room it cannot.
MENDABLE={'refused','text','font_kept','font_new','type3','color','style'}


def norm(text):
    """Words as compared: NFKC, without white space or soft hyphens, and one apostrophe for the ways Uzbek writes it."""
    text=unicodedata.normalize('NFKC',text or '').translate(QUOTES)
    return ''.join(c for c in text if not c.isspace() and c not in '\xad\ufffe\x02')


def family(font):
    """ArialMT, Arial-BoldMT and ABCDEF+Arial are one family; a nameless font (Type3) is ''."""
    name=re.sub(r'[-,].*','',(font or '').split('+')[-1])
    return re.sub(r'(PS)?MT$|PS$','',name).lower()


def close(name,sources):
    """The document's own font, or the twin a reader would not notice (Helvetica and Arial, the Times faces)."""
    twins={'helvetica','arial'}
    return name in sources or (name in twins and bool(twins&sources)) or (name.startswith('times') and any(known.startswith('times') for known in sources))


def changed(old,new):
    """Where new differs from old, as (start, end) in new: what lies outside it both share."""
    start=0
    while start<min(len(old),len(new)) and old[start]==new[start]:start+=1
    end=0
    while end<min(len(old),len(new))-start and old[-1-end]==new[-1-end]:end+=1
    return start,len(new)-end


def _look(font):
    """A face's weight and slant, as its name says them."""
    name=(font or '').split('+')[-1]
    return bool(BOLD.search(name)),bool(ITALIC.search(name))


def _span(letters,start,end):
    """The old letters a change replaced, or the two it stands between when it only adds."""
    return letters[start:end] or letters[max(0,start-1):start+1]


def _one_row(text):
    """A line's new words: a break or tab in them is a space, or PdfCraft would start a row."""
    return re.sub(r'[\r\n\t]',' ',text)


def _box(command):
    return [command['x'],command['y'],command['x']+command['width'],command['y']+command['height']]


def _union(rects):
    rects=list(rects)
    return [min(r[0] for r in rects),min(r[1] for r in rects),max(r[2] for r in rects),max(r[3] for r in rects)]


def _band(first,second,share=.5):
    """Whether two boxes [x0, top, x1, bottom] share a row: they overlap by `share` of the shorter one's height."""
    return min(first[3],second[3])-max(first[1],second[1])>share*min(first[3]-first[1],second[3]-second[1])


def inside(letters,rect,pad=2,lift=1):
    """The letters standing in a row box, left to right: baseline within its height, centre within its width."""
    return sorted((c for c in letters if rect[1]-lift<=c['base']<=rect[3]+lift and rect[0]-pad<=(c['left']+c['right'])/2<=rect[2]+pad),key=lambda c:c['left'])


class Page:
    """One page as pdfium reads and renders it, in the displayed frame: points from its top left as shown.

    Each letter is one character of norm(): a ligature is two, a space none.
    """
    def __init__(self,width,height,letters,pixels=None,scale=SCALE,count=1):
        self.width,self.height,self.letters,self.pixels,self.scale,self.count=width,height,letters,pixels,scale,count

    @classmethod
    def read(cls,path,number,scale=SCALE,forms=False):
        """`scale` is the most it is rendered at; `forms` draws form fields as a viewer fills them in."""
        import numpy
        import pypdfium2 as pdfium
        import pypdfium2.raw as raw
        with pdfium.PdfDocument(str(path)) as document:
            if forms:document.init_forms()
            count=len(document);page=document[number-1]
            try:
                left,bottom,right,top=page.get_mediabox();turn=page.get_rotation()%360
                wide,tall=right-left,top-bottom
                width,height=(tall,wide) if turn in (90,270) else (wide,tall)
                def shown(x,y):
                    u,v=x-left,top-y
                    return {90:(tall-v,u),180:(wide-u,tall-v),270:(v,wide-u)}.get(turn,(u,v))
                letters=[];text=page.get_textpage()
                try:
                    l,r,b,t,ox,oy=(ctypes.c_double() for _ in range(6))
                    name,flags,fill,matrix=ctypes.create_string_buffer(256),ctypes.c_int(),[ctypes.c_uint() for _ in range(4)],raw.FS_MATRIX()
                    for index in range(raw.FPDFText_CountChars(text)):
                        code=raw.FPDFText_GetUnicode(text,index)
                        chars=norm(chr(code)) if 0<code<=0x10FFFF else ''
                        if not chars:continue
                        raw.FPDFText_GetCharBox(text,index,l,r,b,t);raw.FPDFText_GetCharOrigin(text,index,ox,oy)
                        name.value=b'';raw.FPDFText_GetFontInfo(text,index,name,256,ctypes.byref(flags));raw.FPDFText_GetFillColor(text,index,*fill)
                        # pdfium's size leaves out the page's scale (Chrome draws at 0.75), the char's matrix has it.
                        factor=math.hypot(matrix.c,matrix.d) if raw.FPDFText_GetMatrix(text,index,matrix) else 1
                        (x0,y0),(x1,y1)=shown(l.value,t.value),shown(r.value,b.value);x,base=shown(ox.value,oy.value)
                        holder=raw.FPDFText_GetTextObject(text,index)
                        letter={'left':min(x0,x1),'right':max(x0,x1),'top':min(y0,y1),'bottom':max(y0,y1),'x':x,'base':base,
                                'size':raw.FPDFText_GetFontSize(text,index)*factor,'font':name.value.decode('utf-8','ignore'),'flags':flags.value,
                                'color':'#%02x%02x%02x'%tuple(part.value for part in fill[:3]),
                                'unseen':bool(holder) and raw.FPDFTextObj_GetTextRenderMode(holder) in UNSEEN}
                        letters.extend({**letter,'char':char} for char in chars)
                finally:text.close()
                scale=min(scale,math.sqrt(RENDER_PIXELS/max(1,width*height)))
                bitmap=page.render(scale=scale)
                try:pixels=numpy.asarray(bitmap.to_pil().convert('RGB'),dtype=numpy.int16)
                finally:bitmap.close()
            finally:page.close()
        return cls(width,height,letters,pixels,scale,count)


def _mask(changes,rect,scale,across=6,down=4):
    changes[max(0,int((rect[1]-down)*scale)):max(0,int((rect[3]+down)*scale)),max(0,int((rect[0]-across)*scale)):max(0,int((rect[2]+across)*scale))]=False


def _changes(before,after):
    """The pixels that changed between two looks at a page, or None when they cannot be compared."""
    import numpy
    if before.pixels is None or after.pixels is None or before.pixels.shape!=after.pixels.shape:return None
    return numpy.abs(before.pixels-after.pixels).max(axis=2)>INK


def _limit(width,lines,row,rect):
    """How far right a row may reach: short of the page's margin and of the next run in its band, and never less than it reached already."""
    after=[line['rect'][0] for line in lines if line['line'] not in row and _band(line['rect'],rect) and line['rect'][0]>=rect[2]-1]
    return max(min([width-MARGIN,*(x-1 for x in after)]),rect[2])


def _moved(lines_before,lines_after,row,paragraph=None):
    """The runs outside the row no longer listed where they were, saying what they said.

    A paragraph PdfCraft laid out again may shift its other rows a little (lost kerning).
    """
    listed={}
    for line in lines_after:listed.setdefault(line['text'],[]).append(line['rect'])
    moved=[]
    for line in lines_before:
        if line['line'] in row:continue
        rect=line['rect']
        tolerance=1.5 if paragraph and _band(rect,paragraph,0) and paragraph[0]-1<=rect[0]<=paragraph[2] else .05
        if not any(abs(other[1]-rect[1])<=tolerance and abs(other[0]-rect[0])<=tolerance for other in listed.get(line['text'],())):moved.append(line['line'])
    return moved


def check_edit(before,after,lines_before,lines_after,row,old_text,new_text,allowed=(),paragraph=None):
    """The checks one edited row fails, from the page before and after the edit: none when it is clean.

    `row` holds the numbers of the listed runs that made the row before; `allowed`
    the families new letters may be in besides the row's own; `paragraph` the box
    of the paragraph PdfCraft laid out again, when it was edited by paragraph.
    """
    faults=set()
    old=_union(line['rect'] for line in lines_before if line['line'] in row)
    # The row after: the runs in its band from its old start, as long as they follow one another closely.
    chain=sorted((line for line in lines_after if _band(line['rect'],old) and line['rect'][0]>=old[0]-1),key=lambda line:line['rect'][0])
    edited,right=[],None
    for line in chain:
        if right is None and abs(line['rect'][0]-old[0])>1:continue
        if right is not None and line['rect'][0]>right+.5*(old[3]-old[1]):break
        edited.append(line);right=max(right or 0,line['rect'][2])
    rects=[old,*(line['rect'] for line in edited)]
    new=[old[0],min(r[1] for r in rects),max(r[2] for r in rects),max(r[3] for r in rects)]
    end=right if right is not None else old[2]
    was=inside(before.letters,old)
    now=inside(after.letters,[old[0],new[1],end,new[3]])
    # Nothing of the old words may be left past the new ones.
    left=[c for c in after.letters if old[1]-1<=c['base']<=old[3]+1 and end+1<(c['left']+c['right'])/2<=old[2]]
    if ''.join(c['char'] for c in now)!=norm(new_text) or left:faults.add('text')
    if _moved(lines_before,lines_after,row,paragraph):faults.add('others')
    if new[2]>_limit(before.width,lines_before,row,old)+.01 or new[1]<min(0,old[1])-.5 or new[3]>max(before.height,old[3])+.5:faults.add('fit')
    changes=_changes(before,after)
    if changes is None:faults.add('outside')
    else:
        outside=changes.copy();_mask(outside,old,before.scale);_mask(outside,new,before.scale)
        if paragraph:_mask(outside,paragraph,before.scale,2,1)
        if int(outside.sum())>OUTSIDE:faults.add('outside')
        scale=before.scale;top,bottom=max(0,int((old[1]-1)*scale)),max(0,int((old[3]+1)*scale));column=max(0,int((old[2]+2)*scale))
        if int((changes[top:bottom,column:]&(before.pixels[top:bottom,column:].min(axis=2)<200)).sum())>COLLIDE:faults.add('collide')
    if 'text' in faults or not now:return faults
    sources={family(c['font']) for c in was}
    old_norm,new_norm=norm(old_text),norm(new_text);start,stop=changed(old_norm,new_norm);fresh=set(range(start,stop))
    new_fonts=[family(now[i]['font']) for i in sorted(fresh)];kept_fonts=[family(c['font']) for i,c in enumerate(now) if i not in fresh]
    if any(not close(name,sources) for name in kept_fonts):faults.add('font_kept')
    if any(not close(name,sources) and name not in allowed for name in new_fonts):faults.add('font_new')
    if '' in new_fonts or '' in kept_fonts:faults.add('type3')
    if any(all(abs(c['size']-size)>.05 for size in {c['size'] for c in was}) for c in now):faults.add('size')
    if ''.join(c['char'] for c in was)==old_norm:
        # Letter for letter: a kept letter keeps its own colour and weight, a new one takes those of the letters it replaced.
        shift=len(new_norm)-len(old_norm);span=_span(was,start,stop-shift)
        for i,c in enumerate(now):
            models=span if i in fresh else [was[i if i<start else i-shift]]
            if c['color'] not in {model['color'] for model in models}:faults.add('color')
            if _look(c['font']) not in {_look(model['font']) for model in models}:faults.add('style')
    elif {c['color'] for c in now}-{c['color'] for c in was}:faults.add('color')
    if not was or abs(statistics.median(c['base'] for c in now)-statistics.median(c['base'] for c in was))>BASELINE:faults.add('baseline')
    widths={}
    for c in was:widths.setdefault((c['char'],family(c['font'])),[]).append(c['right']-c['left'])
    known={key:statistics.median(values) for key,values in widths.items()}
    ratios=[(c['right']-c['left'])/known[key] for c in now if known.get(key:=(c['char'],family(c['font'])),0)>.3]
    if ratios and abs(statistics.median(ratios)-1)>STRETCH:faults.add('stretch')
    return faults


def check_removal(before,after,lines_before,lines_after,row):
    """The checks taking a row's runs out fails: none of its letters may be left, and nothing else may change."""
    faults=set()
    old=_union(line['rect'] for line in lines_before if line['line'] in row)
    if inside(after.letters,old,0,0):faults.add('text')
    if _moved(lines_before,lines_after,row):faults.add('others')
    changes=_changes(before,after)
    if changes is None:faults.add('outside')
    else:
        _mask(changes,old,before.scale)
        if int(changes.sum())>OUTSIDE:faults.add('outside')
    return faults


def baseline_of(line,page):
    """Where a listed run stands: pdfium's letters in it, or its box less the usual descent when it has none."""
    found=inside(page.letters,line['rect'],0,0)
    if found:return statistics.median(c['base'] for c in found)
    return line['rect'][3]-(.25 if STANDARD.match(line.get('font') or '') else .293)*line['size']


def match(lines,command,page):
    """The listed runs that make the command's line, left to right, or None.

    A run counts when it overlaps the box by half the narrower width and stands
    within its height. Some stretch of them, together, must say the original words.
    """
    box=_box(command);wanted=norm(command['original']);found=[]
    for line in lines:
        rect=line['rect'];narrower=min(rect[2]-rect[0],box[2]-box[0])
        if narrower<=0 or min(rect[2],box[2])-max(rect[0],box[0])<.5*narrower:continue
        if box[1]-.5<=baseline_of(line,page)<=box[3]+.5:found.append(line)
    found.sort(key=lambda line:line['rect'][0])
    for start in range(len(found)):
        if not norm(found[start]['text']):continue
        said=''
        for end in range(start,len(found)):
            said+=norm(found[end]['text'])
            if said==wanted:return found[start:end+1]
            if not wanted.startswith(said):break
    return None


def row_of(paragraphs,found,lines):
    """The paragraph row the runs sit in: (paragraph, row index, the row's text before them, after them), or None unless they are one stretch of one row."""
    numbers=[line['line'] for line in found];texts={line['line']:line['text'] for line in lines}
    for paragraph in paragraphs:
        rows=paragraph['rows'];said=paragraph['editor_text'].split('\n')
        for index,row in enumerate(rows):
            if numbers[0] not in row:continue
            at=row.index(numbers[0])
            if len(rows)!=len(said) or row[at:at+len(numbers)]!=numbers or any(number not in texts for number in row):return None
            before=''.join(texts[number] for number in row[:at]);after=''.join(texts[number] for number in row[at+len(numbers):])
            if before+''.join(texts[number] for number in numbers)+after!=said[index]:return None
            return paragraph,index,before,after
    return None


def style_of(page,command,found=None):
    """How the old words were set, read before they go: where they start and stand, size, colour and the nearest Noto face, and how far right they reached."""
    box=_box(command);rects=[line['rect'] for line in found] if found else [box]
    letters=[c for c in page.letters if box[1]-.5<=c['base']<=box[3]+.5 and any(r[0]-1<=(c['left']+c['right'])/2<=r[2]+1 for r in rects)]
    # PdfCraft's size is the one drawn; pdfium's needs the char's matrix, and a box alone says only what the web assumed.
    sizes=[max(found,key=lambda line:len(norm(line['text'])))['size']] if found else []
    sizes+=[statistics.median(c['size'] for c in letters)] if letters else []
    size=next((size for size in sizes if 1<=size<=1000),command['height']/1.25)
    if letters:
        font,flags=Counter((c['font'],c['flags']) for c in letters).most_common(1)[0][0]
        color=Counter(c['color'] for c in letters).most_common(1)[0][0]
    else:font,flags,color=(found[0].get('font') or '') if found else '',0,'#000000'
    sans='sans' in font.lower()
    return {'left':min(c['x'] for c in letters) if letters else min(r[0] for r in rects),
            'base':statistics.median(c['base'] for c in letters) if letters else command['y']+.76*command['height'],
            'right':max([box[2],*(r[2] for r in rects),*(c['right'] for c in letters)]),
            'size':size,'color':color,'bold':_look(font)[0] or bool(flags&FORCE_BOLD),
            'family':'serif' if not sans and (bool(SERIF.search(font)) or bool(flags&2)) else 'sans','font':font,'letters':letters}


def room(page,style,command):
    """How wide the new words may be: to the page's margin or just short of the next words in the row, never less than the old words took."""
    box=_box(command);mine={id(c) for c in style['letters']}
    nearest=[c['left'] for c in page.letters if id(c) not in mine and box[1]<=c['base']<=box[3] and c['left']>=style['right']-.5]
    return max(min([page.width-MARGIN,*(x-1 for x in nearest)]),style['right'])-style['left']


def paper(page,rect):
    """The paper's colour around a box: the median of a 2 pt ring just outside it, white when there is none."""
    import numpy
    if page.pixels is None:return '#FFFFFF'
    scale=page.scale;tall,wide=page.pixels.shape[:2]
    outer=[max(0,int((rect[0]-2)*scale)),max(0,int((rect[1]-2)*scale)),min(wide,math.ceil((rect[2]+2)*scale)),min(tall,math.ceil((rect[3]+2)*scale))]
    if outer[2]<=outer[0] or outer[3]<=outer[1]:return '#FFFFFF'
    region=page.pixels[outer[1]:outer[3],outer[0]:outer[2]];keep=numpy.ones(region.shape[:2],bool)
    keep[max(0,int(rect[1]*scale)-outer[1]):max(0,math.ceil(rect[3]*scale)-outer[1]),max(0,int(rect[0]*scale)-outer[0]):max(0,math.ceil(rect[2]*scale)-outer[0])]=False
    ring=region[keep]
    return '#%02X%02X%02X'%tuple(int(value) for value in numpy.median(ring,axis=0)) if len(ring) else '#FFFFFF'


def overlay(command,style,text,space,cover=None):
    """The new words as a mark, where the old stood. With `cover` (a box and the paper's colour) the old words are painted over first.

    Words wider than their room are set smaller, down to SMALLEST of their size and
    never under FLOOR, and past that narrowed, so they never reach the next words.
    They are refused only where the web refused them before the send. Its guess is
    the line's own width scaled by the new words' Noto Sans width over the old's:
    their width in the document's font, which is often narrower than the face they
    are drawn in here (Noto Serif is a sixth wider than Times). Measured in Noto
    alone, a change the web had said would be set a little smaller would fail the
    whole send.
    """
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from .editor import _font
    from .engine import ProcessorError
    size,narrow=style['size'],1
    if text:
        least=min(size,max(SMALLEST*size,FLOOR));face=_font(style['family'],style['bold'])
        sans=_font();said=stringWidth(command.get('original') or '',sans,10)
        guess=command['width']*stringWidth(text,sans,10)/said if said>0 else stringWidth(text,face,size)
        if space<=0 or guess*least/size>space+SLACK:raise ProcessorError('editor_text_too_long')
        wide=stringWidth(text,face,size)
        if wide>space:
            size=max(least,size*space/wide)
            narrow=min(1,space/stringWidth(text,face,size))
    rect,color=cover if cover else (_box(command),None)
    return {'type':'retype','page':command['page'],'x':rect[0],'y':rect[1],'width':rect[2]-rect[0],'height':rect[3]-rect[1],'cover':color,
            'left':style['left'],'baseline':style['base'],'size':size,'narrow':narrow,'color':style['color'],'font':style['family'],'bold':style['bold'],'text':text}


def face_of(style,bold=None):
    """The face whose letters stand in for those the document's font lacks: Liberation is Helvetica's and Arial's twin. `bold` is the replaced letters' weight, when known."""
    weight='Bold' if (style['bold'] if bold is None else bold) else 'Regular'
    if family(style['font']) in ('helvetica','arial'):return FACES/f'LiberationSans-{weight}.ttf'
    return FACES/f'Noto{style["family"].title()}-{weight}.ttf'


@lru_cache(maxsize=8)
def face_name(path):
    """A face's PostScript name, which PdfCraft lists an imported face by (LiberationSans-Regular.ttf is 'LiberationSans')."""
    from reportlab.pdfbase.ttfonts import TTFontFile
    name=TTFontFile(str(path),charInfo=0).name
    return name.decode('latin-1') if isinstance(name,bytes) else name


def imported(report,face):
    """The resource a face was imported as, from a run of open, paragraphs, text_font_import and text_fonts; None when there is none.

    A page that holds the face whole already (an earlier change put it there, or
    an earlier send of this file) is answered with no resource: its listing has it.
    """
    answer=pdfcraft.result(report,2)
    if answer is None:return None
    resource=answer.get('resource') or answer.get('font_resource')
    if isinstance(resource,str):return resource
    fonts=(pdfcraft.result(report,3) or {}).get('fonts')
    held=[font['resource'] for font in fonts if isinstance(font,dict) and font.get('full_face') is True and font.get('font')==face_name(face) and isinstance(font.get('resource'),str)] if isinstance(fonts,list) else []
    return held[0] if held else None


def _numbers(value,count):
    return isinstance(value,list) and len(value)==count and all(type(item) in (int,float) and math.isfinite(item) for item in value)


def _lines(value):
    """PdfCraft's listed runs, or None when any is not as this code reads it."""
    if not isinstance(value,list):return None
    for line in value:
        if not isinstance(line,dict) or type(line.get('line')) is not int or not _numbers(line.get('rect'),4) or not isinstance(line.get('text'),str) or not _numbers([line.get('size')],1) or not isinstance(line.get('font',''),str):return None
    return value


def _paragraphs(value):
    """PdfCraft's paragraphs that are as this code reads them; the rest are left out."""
    kept=[]
    for paragraph in value if isinstance(value,list) else []:
        if (isinstance(paragraph,dict) and type(paragraph.get('paragraph')) is int and isinstance(paragraph.get('editor_text'),str) and _numbers(paragraph.get('rect'),4)
                and isinstance(paragraph.get('rows'),list) and all(isinstance(row,list) and row and all(type(n) is int for n in row) for row in paragraph['rows'])):kept.append(paragraph)
    return kept


class Edited:
    """What the stage leaves the pipeline: the file the marks go on, overlays and engines by command index, and whether PdfCraft changed the file."""
    def __init__(self,path):
        self.path,self.overlays,self.engines,self.pdfcraft=path,{},{},False


class _Work:
    """The working file, and PdfCraft while it may still be asked."""

    def __init__(self,source,root,executable,spent=0.0):
        # `spent`: seconds of PdfCraft the send has had already (black-out), which come off this stage's.
        self.root,self.executable,self.started,self.count,self.pages=root,executable,time.monotonic()-spent,0,{}
        self.path=source
        if executable:
            # PdfCraft reads and writes only under its root.
            self.path=root/'work-0.pdf';shutil.copyfile(source,self.path)

    def page(self,number):
        key=(self.path,number)
        if key not in self.pages:
            self.pages={held:page for held,page in self.pages.items() if held[0]==self.path};self.pages[key]=Page.read(self.path,number)
        return self.pages[key]

    def usable(self):
        return self.executable is not None and time.monotonic()-self.started<BUDGET

    def run(self,steps):
        try:return pdfcraft.run(self.executable,steps,self.root,timeout=max(1,min(pdfcraft.SECONDS,BUDGET+15-(time.monotonic()-self.started))))
        except pdfcraft.Failed:
            # A run that hung or answered nonsense would again: whatever is left is covered.
            self.executable=None
            raise

    def _open(self):
        return {'tool':'doc_open','args':{'path':str(self.path)}}

    def listing(self,number):
        report=self.run([self._open(),{'tool':'text_lines','args':{'doc':1,'page':number}},{'tool':'text_paragraphs','args':{'doc':1,'page':number}}])
        lines,paragraphs=pdfcraft.result(report,1),pdfcraft.result(report,2)
        lines=_lines(lines.get('lines')) if report.get('ok') is True and lines else None
        return (lines,_paragraphs((paragraphs or {}).get('paragraphs'))) if lines is not None else None

    def save(self,number,steps):
        """One run on the working file: the steps, then the page listed and the file saved anew. (file, runs listed after), or None when PdfCraft refused."""
        import pypdfium2 as pdfium
        self.count+=1;target=self.root/f'work-{self.count}.pdf'
        steps=[self._open(),*steps,{'tool':'text_lines','args':{'doc':1,'page':number}},{'tool':'doc_save','args':{'doc':1,'path':str(target)}}]
        try:report=self.run(steps)
        except pdfcraft.Failed:
            target.unlink(missing_ok=True);raise
        listed=pdfcraft.result(report,len(steps)-2)
        lines=_lines(listed.get('lines')) if listed else None
        if report.get('ok') is not True or lines is None or not target.is_file():
            target.unlink(missing_ok=True);return None
        try:after=Page.read(target,number)
        except pdfium.PdfiumError:
            target.unlink(missing_ok=True);return None
        if after.count!=self.page(number).count:
            target.unlink(missing_ok=True);return None
        return target,lines,after

    def keep(self,target):
        if self.path.parent==self.root:self.path.unlink(missing_ok=True)
        self.path=target

    def attempt(self,number,lines,steps,row,old,new,allowed=(),paragraph=None):
        """Runs one edit and looks at it: the faults found, none when the edit is kept."""
        before=self.page(number);made=self.save(number,steps)
        if not made:return {'refused'}
        target,after_lines,after=made
        faults=check_edit(before,after,lines,after_lines,row,old,new,allowed,paragraph)
        if faults:target.unlink(missing_ok=True)
        else:self.keep(target)
        return faults

    def replace(self,number,lines,paragraphs,found,new,style):
        """Paths a and b: 'pdfcraft' or 'pdfcraft-noto' when one is kept, else None."""
        numbers=[line['line'] for line in found];held=row_of(paragraphs,found,lines)
        if len(found)==1:faults=self.attempt(number,lines,[{'tool':'text_edit','args':{'doc':1,'page':number,'line':numbers[0],'text':new}}],set(numbers),found[0]['text'],new)
        if not held:return 'pdfcraft' if len(found)==1 and not faults else None
        paragraph,index,before,after=held
        rows=paragraph['editor_text'].split('\n');rows[index]=before+new+after;text='\n'.join(rows)
        row=set(paragraph['rows'][index]);reach=_union(line['rect'] for line in lines if line['line'] in row)
        old_row,new_row=before+''.join(line['text'] for line in found)+after,before+new+after
        others=[line['rect'][2] for line in lines if any(line['line'] in other for other in paragraph['rows']) and line['line'] not in row]
        # Wide enough that no row wraps; how far this one may reach is the look's to judge.
        width=round(max([_limit(self.page(number).width,lines,row,reach),*others])+.5-paragraph['rect'][0],2)
        args={'doc':1,'page':number,'paragraph':paragraph['paragraph'],'text':text,'width':width}
        listing={'tool':'text_paragraphs','args':{'doc':1,'page':number}}
        def by_paragraph(edit,allowed=(),before_edit=()):
            return self.attempt(number,lines,[listing,*before_edit,{'tool':'text_edit','args':edit}],row,old_row,new_row,allowed,paragraph['rect'])
        if len(found)>1:faults=by_paragraph(args)
        if not faults:return 'pdfcraft'
        start,stop=changed(paragraph['editor_text'],text)
        if not faults&MENDABLE or start>=stop or not self.usable():return None
        # What the replaced letters were: inserted text otherwise takes the run before it, which may be another colour or weight.
        was=inside(self.page(number).letters,reach);old_norm,new_norm=norm(old_row),norm(new_row);first,last=changed(old_norm,new_norm)
        span=_span(was,first,last-len(new_norm)+len(old_norm)) if ''.join(c['char'] for c in was)==old_norm else []
        color=Counter(c['color'] for c in span).most_common(1)[0][0] if span else style['color']
        bold=any(_look(c['font'])[0] for c in span) if span else style['bold']
        stretch=[len(text[:start].encode()),len(text[:stop].encode())]
        if faults<={'color','style'}:
            # Only the colour or weight went wrong: said outright, in the document's own font.
            faults=by_paragraph({**args,'ranges':[{'range':stretch,'color':color,'bold':bold}]})
            if not faults:return 'pdfcraft'
            if not faults&MENDABLE or not self.usable():return None
        # PdfCraft takes an imported face's letters only by paragraph (line mode ignores ranges), and the whole face is embedded: only now.
        face=face_of(style,bold);copy=self.root/face.name
        if not copy.exists():shutil.copyfile(face,copy)
        importing={'tool':'text_font_import','args':{'doc':1,'page':number,'path':str(copy)}}
        resource=imported(self.run([self._open(),listing,importing,{'tool':'text_fonts','args':{'doc':1,'page':number}}]),face)
        if resource is None:return None
        faults=by_paragraph({**args,'ranges':[{'range':stretch,'font_resource':resource,'color':color}]},{family(face.stem)},[importing])
        return None if faults else 'pdfcraft-noto'

    def edit(self,command):
        """One change by PdfCraft: (engine, overlays), or (None, the old words' style) when it is for covering."""
        number=command['page'];new=_one_row(command['text'])
        before=self.page(number)
        if before.scale<SCALE:return None,None
        listed=self.listing(number)
        if not listed:return None,None
        lines,paragraphs=listed
        found=match(lines,command,before)
        if not found:return None,None
        style=style_of(before,command,found);mark=None
        # Words drawn out of sight (OCR over a scan): what shows is the picture under them, which only a cover changes.
        if any(c['unseen'] for c in style['letters']):return None,style
        if norm(new):
            engine=self.replace(number,lines,paragraphs,found,new,style)
            if engine:return engine,[]
            # Drawn in Noto from here on: whether the words fit at all is known before the old ones go.
            mark=overlay(command,style,new,room(before,style,command))
        if not self.usable():return None,style
        # Retyped: the old runs out, the highest number first, since taking one out renumbers those after it.
        numbers=sorted((line['line'] for line in found),reverse=True)
        made=self.save(number,[{'tool':'text_edit','args':{'doc':1,'page':number,'line':n,'text':''}} for n in numbers])
        if not made:return None,style
        target,after_lines,after=made
        if check_removal(before,after,lines,after_lines,set(numbers)):
            target.unlink(missing_ok=True);return None,style
        self.keep(target)
        return ('retyped',[mark]) if mark else ('removed',[])

    def cover(self,command,style=None):
        page=self.page(command['page']);new=_one_row(command['text']);style=style or style_of(page,command)
        letters=style['letters'];box=_box(command)
        # Over every letter of the old words, padded, and on the page.
        rect=_union([box,*([c['left'],c['top'],c['right'],c['bottom']] for c in letters)])
        rect=[max(0,rect[0]-.5),max(0,rect[1]-.5),min(page.width,rect[2]+.5),min(page.height,rect[3]+.5)]
        return [overlay(command,style,new if norm(new) else '',room(page,style,command),cover=(rect,paper(page,rect)))]


def _keeps_its_parts(source,made):
    """Whether PdfCraft's file, which it writes whole, still opens as ours do and holds every page, form field and note the source had."""
    from pypdf import PdfReader
    from .engine import _pdf_reader
    def notes(page):
        found=page.get('/Annots')
        return len(found.get_object()) if found is not None else 0
    try:
        first,second=PdfReader(source),_pdf_reader(made,allow_forms=True)
        return (len(first.pages)==len(second.pages) and set(first.get_fields() or {})==set(second.get_fields() or {})
                and all(notes(one)==notes(other) for one,other in zip(first.pages,second.pages)))
    except Exception:
        return False


def _apply(work,edits,turned):
    from .engine import ProcessorError
    done=Edited(work.path)
    for index,command in edits:
        try:
            # (engine, overlays) when PdfCraft took it, else (None, the old words' style when it was read).
            engine,held=None,None
            if work.usable() and command['page'] not in turned:
                try:engine,held=work.edit(command)
                # PdfCraft's answer was not as this code reads it, or there was none: cover, as with no PdfCraft at all.
                except (pdfcraft.Failed,KeyError,TypeError,ValueError,IndexError,AttributeError):engine,held=None,None
            if engine:done.engines[index],done.overlays[index]=engine,held
            else:done.engines[index],done.overlays[index]='covered' if norm(command['text']) else 'blanked',work.cover(command,held)
        except ProcessorError as error:
            error.index=index;raise
    done.path=work.path;done.pdfcraft=any(engine not in PAINTED for engine in done.engines.values())
    return done


def stage(source,commands,root,allowed,spent=0.0):
    """Applies every edit_text of a job: an Edited. `allowed` is the pdfcraft switch; `root` a private folder inside the job's output; `spent` the seconds the black-out stage took.

    A page PdfCraft cannot be asked about goes straight to covering: a turned page,
    whose runs PdfCraft lists unturned while the web placed the box as shown, and
    everything when the switch is off, the binary missing or the file too large.
    """
    from pypdf import PdfReader
    from .editor import _deleted,_geometry,_rotated_box
    from .engine import ProcessorError
    source,root=Path(source),Path(root);deleted=_deleted(commands)
    edits=[(index,command) for index,command in enumerate(commands) if command['type']=='edit_text' and command['page'] not in deleted]
    if not edits:return Edited(source)
    reader=PdfReader(source);turned=set()
    for index,command in edits:
        page=reader.pages[command['page']-1];turn=int(page.rotation or 0)%360
        # The box is placed on the page as shown: held to the page's own frame, it is turned back first.
        x,y,w,h=_rotated_box(command,float(page.mediabox.width),float(page.mediabox.height),(360-turn)%360)
        try:_geometry(page,{**command,'x':x,'y':y,'width':w,'height':h})
        except ProcessorError as error:
            error.index=index;raise
        if turn:turned.add(command['page'])
    executable=pdfcraft.binary(root) if allowed and source.stat().st_size<=MAX_BYTES and len(reader.pages)<=MAX_PAGES else None
    done=_apply(_Work(source,root,executable,spent),edits,turned)
    if done.path!=source and not _keeps_its_parts(source,done.path):
        # Something else in the file did not survive PdfCraft's rewrite: every change is covered on the source instead.
        done=_apply(_Work(source,root,None),edits,turned)
    return done
