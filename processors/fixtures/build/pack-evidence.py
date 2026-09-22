"""Synthetic multilingual pack evidence. No provider request or customer data."""
from pathlib import Path
import os,sys,shutil,json
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from apps.studio.packs import local_materials,render
from processors import execute
import pypdfium2 as pdfium
out=ROOT/'docs/verification/packs'
phrases={
 'en':('Addition lesson','Building understanding','Use counters to show two groups. Combine them and count the total. Explain the result in a complete sentence.','What is 2 + 3?','Five counters make one total.'),
 'uz':('Qo‘shish darsi','Tushunchani shakllantirish','Ikki guruhni sanoq donalari bilan ko‘rsating. Ularni birlashtiring va jami sonni sanang. Natijani to‘liq gap bilan tushuntiring.','2 + 3 nechaga teng?','Beshta dona jami sonni tashkil qiladi.'),
 'ru':('Урок сложения','Формирование понимания','Покажите две группы счётными предметами. Объедините их и посчитайте общее количество. Объясните результат полным предложением.','Чему равно 2 + 3?','Всего получилось пять предметов.'),
}
manifest={}
for locale,(title,heading,body,stem,explanation) in phrases.items():
 target=out/locale
 if target.exists():shutil.rmtree(target)
 target.mkdir()
 content={'title':title,'sections':[{'id':'s1','heading':heading,'body':body,'notes':''}],'questions':[{'id':'q1','stem':stem,'options':['4','5','6'],'answer':'5','explanation':explanation,'topic':'addition','marks':1}],'citations':[]}
 material=local_materials('teacher.lesson_pack',content,locale)
 artifacts=render('teacher.lesson_pack',material,target,locale,{'accent':'#3b6588'},{'sections':30,'slides':50})
 converted=execute('convert.pptx_to_pdf',[target/'slides.pptx'],{},target/'slides-render')
 targets=[target/'worksheet.pdf',target/'worksheet-answers.pdf',Path(converted['artifacts'][0]['path'])]
 for path in targets:
  with pdfium.PdfDocument(str(path)) as document:
   for index in range(len(document)):
    page=document[index];bitmap=page.render(scale=1.15);image=bitmap.to_pil().convert('RGB');image.save(target/f'{path.stem}-{index+1}.png');bitmap.close();page.close()
 manifest[locale]=[{'name':a['name'],'role':a['role'],'pages':a['page_count']} for a in artifacts]
(out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(out)
