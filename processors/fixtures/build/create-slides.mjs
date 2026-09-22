import { Presentation, PresentationFile } from '@oai/artifact-tool';
import path from 'node:path';
const rows = [
 ['en', 'Office conversion verification', 'Document pages remain readable', 'This synthetic fixture checks English text, layout and editable slide shapes.'],
 ['uz', 'Office konvertatsiyasini tekshirish', 'Hujjat sahifalari aniq ko‘rinadi', 'Bu sinov o‘zbekcha matn va tahrirlanadigan slayd obyektlarini tekshiradi.'],
 ['ru', 'Проверка преобразования Office', 'Страницы документа остаются читаемыми', 'Этот тест проверяет русский текст, разметку и редактируемые объекты слайда.'],
];
const deck=Presentation.create({slideSize:{width:1280,height:720}});
function text(slide,value,left,top,width,height,size,bold=false,color='#172133'){
 const shape=slide.shapes.add({geometry:'textbox',position:{left,top,width,height},fill:'none',line:{fill:'none',width:0}});
 shape.text=value;shape.text.style={typeface:'Noto Sans',fontSize:size,bold,color,autoFit:'none'};
}
for(const [locale,title,heading,body] of rows){
 const slide=deck.slides.add();slide.background.fill='#F7F9FC';
 text(slide,title,72,52,1136,115,42,true);
 text(slide,heading,72,226,1136,76,31,true,'#235CC5');
 text(slide,body,72,342,1070,145,28);
 text(slide,`PDF Master / ${locale} / 2026-09-22`,72,620,1136,40,21);
 slide.speakerNotes.textFrame.setText('Synthetic local software acceptance fixture. No customer information.');
}
await (await PresentationFile.exportPptx(deck)).save(path.resolve('processors/fixtures/office-multilingual.pptx'));
