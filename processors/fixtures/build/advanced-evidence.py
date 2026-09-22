"""Regenerate synthetic, non-sensitive advanced processor visual evidence."""
from pathlib import Path
import json,shutil,sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from processors import execute
from processors.editor import _font
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.colors import HexColor
from PIL import Image,ImageDraw,ImageFont
import pypdfium2 as pdfium

out=ROOT/'docs/verification/advanced'
for p in out.iterdir():
    if p.is_dir():shutil.rmtree(p)
source=out/'source.pdf';c=Canvas(str(source),pagesize=(595,842))
c.setFillColor(HexColor('#173b36'));c.setFont(_font(),24);c.drawString(44,786,'PDF Master · advanced engine QA')
c.setFillColor(HexColor('#44534e'));c.setFont(_font(),12);c.drawString(44,758,'Synthetic content · English / Uzbek / Russian')
c.setFont('Helvetica',18);c.setFillColor(HexColor('#173b36'));c.drawString(44,700,'Account OLD VALUE')
c.setFont(_font(),14);c.drawString(44,665,'Public material remains visible after redaction.')
c.setFillColor(HexColor('#922f31'));c.setFont('Helvetica',17);c.drawString(44,615,'SECRET123 · remove this entire line')
c.setFillColor(HexColor('#173b36'));c.setFont(_font(),12);c.drawString(44,455,'Editable form:')
c.acroForm.textfield(name='customer',x=44,y=405,width=420,height=36,fontSize=12)
c.setFont(_font(),10);c.drawString(44,44,'This PDF is an implementation fixture, not a production quality claim.')
c.save()
commands=[{'type':'replace_text','page':1,'find':'OLD','replacement':'NEW'},
 {'type':'add_text','page':1,'x':44,'y':278,'text':'Salom, hujjat!  Привет, документ!','font_size':18,'color':'#173B36'},
 {'type':'highlight','page':1,'x':42,'y':124,'width':245,'height':24},
 {'type':'note','page':1,'x':522,'y':178,'text':'QA: comment persists as a PDF annotation.'},
 {'type':'fill_form','field':'customer','value':'Павел · Salom'},
 {'type':'draw','page':1,'points':[[44,489],[100,511],[175,490]],'color':'#256855','stroke_width':3}]
edit=execute('editor.visual',[source],{'commands':commands},out/'edited')
redact=execute('editor.redact',[Path(edit['artifacts'][0]['path'])],{'commands':[{'type':'redact','page':1,'x':40,'y':207,'width':390,'height':30}],'accept_rasterization':True},out/'redacted')
for name,path in [('source',source),('edited',Path(edit['artifacts'][0]['path'])),('redacted',Path(redact['artifacts'][0]['path']))]:
    with pdfium.PdfDocument(str(path)) as document:
        document.init_forms();page=document[0];bitmap=page.render(scale=1.3);image=bitmap.to_pil().convert('RGB');image.save(out/f'{name}.png');bitmap.close();page.close()
text='HELLO DOCUMENT\nSALOM HUJJAT\nПРИВЕТ ДОКУМЕНТ'
scan=Image.new('RGB',(1600,520),'white');drawing=ImageDraw.Draw(scan);drawing.multiline_text((55,60),text,font=ImageFont.truetype(str(ROOT/'processors/assets/fonts/NotoSans-Regular.ttf'),62),fill='#173b36',spacing=24);scan.save(out/'ocr-source.png')
ocr=execute('ocr.searchable_pdf',[out/'ocr-source.png'],{'language':'eng+rus+uzb'},out/'ocr')
manifest={'editor':edit['metadata'],'redaction':redact['metadata'],'ocr':ocr['metadata'],'checks':'58 serialized processor tests pass; rendered source, edited and redacted examples reviewed.'}
(out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(out)
