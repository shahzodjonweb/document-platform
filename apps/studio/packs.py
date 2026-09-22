"""Concrete, named education packs. Local mode reorganizes supplied work only."""
import copy
import json
from apps.core.errors import DomainError

# key, locale labels, role, file format, needs questions, paired private key
SPECS={
 'teacher.variants':[(k,[f'Version {k.upper()}',f'{k.upper()} variant',f'Вариант {k.upper()}'],'learner_material','pdf',True,True) for k in ('a','b','c')],
 'teacher.differentiated':[
  ('basic',['Basic worksheet','Boshlang‘ich mashqlar','Базовый уровень'],'learner_material','pdf',True,True),
  ('standard',['Standard worksheet','Standart mashqlar','Стандартный уровень'],'learner_material','pdf',True,True),
  ('advanced',['Advanced worksheet','Murakkab mashqlar','Продвинутый уровень'],'learner_material','pdf',True,True)],
 'teacher.lesson_pack':[
  ('lesson-plan',['Lesson plan','Dars rejasi','План урока'],'teacher_feedback','pdf',False,False),
  ('worksheet',['Learner worksheet','O‘quvchi mashqlari','Рабочий лист'],'learner_material','pdf',True,True),
  ('slides',['Lesson slides','Dars slaydlari','Слайды урока'],'learner_material','pptx',False,False)],
 'study.exam_pack':[
  ('review',['Exam review','Imtihon takrorlash','Повторение к экзамену'],'user_document','pdf',False,False),
  ('practice',['Practice test','Sinov testi','Тренировочный тест'],'user_document','pdf',True,True)],
 'school.weekly_pack':[(key,labels,'learner_material','pdf',True,False) for key,labels in [
  ('monday',['Monday','Dushanba','Понедельник']),('tuesday',['Tuesday','Seshanba','Вторник']),('wednesday',['Wednesday','Chorshanba','Среда']),('thursday',['Thursday','Payshanba','Четверг']),('friday',['Friday','Juma','Пятница'])]],
}

def slots(feature):return SPECS.get(feature,[])
def question_multiplier(feature):return sum(row[4] for row in slots(feature)) or 1

def output_ceiling(feature,caps,tariff):
    total=0
    for key,labels,role,fmt,questions,paired in slots(feature):
        total+=caps['slides' if fmt=='pptx' else 'sections']*tariff['pptx_output_credits_per_slide' if fmt=='pptx' else 'pdf_output_credits_per_started_page']
        if paired:total+=caps['sections']*tariff['pdf_output_credits_per_started_page']
    if feature=='school.weekly_pack':total+=caps['sections']*tariff['pdf_output_credits_per_started_page']
    return total

def _question(q):
    result=copy.deepcopy(q)
    # Resolve letter labels before shuffling choices so answer pairing stays true.
    answer=result['answer'].strip();options=result.get('options',[])
    if answer not in options and len(answer)==1 and answer.upper() in 'ABCDEFGH' and ord(answer.upper())-65<len(options):result['answer']=options[ord(answer.upper())-65]
    return result

def local_materials(feature,content,locale):
    language={'en':0,'uz':1,'ru':2}[locale]
    questions=[_question(q) for q in content['questions']]
    if not questions:raise DomainError('pack_content_required')
    if feature=='teacher.variants' and len(questions)<3:raise DomainError('variant_content_required')
    if feature=='school.weekly_pack' and len(questions)<5:raise DomainError('pack_content_required')
    result=[]
    for index,(key,labels,role,fmt,needs_questions,paired) in enumerate(slots(feature)):
        sections=copy.deepcopy(content['sections']);selected=copy.deepcopy(questions) if needs_questions else []
        if feature=='teacher.variants':
            selected=selected[index:]+selected[:index]
            for q in selected:
                options=q['options'];offset=index%len(options) if options else 0;q['options']=options[offset:]+options[:offset]
        elif feature=='teacher.differentiated':
            instructions={
             'basic':['Work in small steps. Identify the given information, explain one step at a time, then check your response.','Kichik qadamlar bilan ishlang. Berilgan ma’lumotlarni aniqlang, har bir qadamni tushuntiring va javobni tekshiring.','Работайте по шагам. Выделите исходные данные, объясните каждый шаг и проверьте ответ.'],
             'standard':['Complete the questions independently and show your reasoning.','Savollarni mustaqil bajaring va fikrlash yo‘lingizni ko‘rsating.','Выполните задания самостоятельно и покажите ход рассуждений.'],
             'advanced':['Justify each response, compare an alternative approach, and create a related question with an explained answer.','Har bir javobni asoslang, boshqa usul bilan taqqoslang va izohli javobga ega o‘xshash savol tuzing.','Обоснуйте ответы, сравните другой подход и составьте похожий вопрос с объяснением ответа.'],
            }
            sections=[{'id':'instructions','heading':labels[language],'body':instructions[key][language],'notes':''}]+sections
        elif feature=='teacher.lesson_pack' and key=='lesson-plan':
            stages=[['Preparation','Tayyorgarlik','Подготовка'],['Teaching and discussion','Tushuntirish va muhokama','Объяснение и обсуждение'],['Practice and review','Mashq va takrorlash','Практика и повторение']]
            sections=[{'id':'stage'+str(i+1),'heading':stage[language],'body':content['sections'][min(i,len(content['sections'])-1)]['body'],'notes':''} for i,stage in enumerate(stages)]
        elif feature=='school.weekly_pack':selected=selected[index::5]
        for section in sections:section['notes']=''
        result.append({'key':key,'title':content['title']+' · '+labels[language],'sections':sections,'questions':selected,'citations':content.get('citations',[])})
    return result

def validate_materials(account,feature,materials,question_cap):
    from .domain import validate_content
    expected={row[0]:row for row in slots(feature)}
    if not isinstance(materials,list) or len(materials)!=len(expected) or {m.get('key') for m in materials if isinstance(m,dict)}!=set(expected):raise DomainError('invalid_pack_content')
    rows={};question_total=0
    for value in materials:
        key=value['key'];spec=expected[key]
        clean=validate_content(account,{k:v for k,v in value.items() if k!='key'},spec[3])
        if spec[4] and not clean['questions']:raise DomainError('pack_content_required')
        if not spec[4] and clean['questions']:raise DomainError('invalid_pack_content')
        question_total+=len(clean['questions']);rows[key]={'key':key,**clean}
    if question_total>question_cap:raise DomainError('generation_limit')
    if feature=='teacher.variants':
        values=list(rows.values())
        if len({len(value['questions']) for value in values})!=1 or len({frozenset(q['topic'] for q in value['questions']) for value in values})!=1:raise DomainError('invalid_pack_content')
        signatures={json.dumps([{k:q[k] for k in ('stem','options','answer','marks','topic')} for q in value['questions']],sort_keys=True) for value in values}
        if len(signatures)!=len(values):raise DomainError('invalid_pack_content')
    if feature=='teacher.differentiated':
        signatures={json.dumps({'bodies':[s['body'] for s in value['sections']],'questions':value['questions']},sort_keys=True) for value in rows.values()}
        if len(signatures)!=len(rows):raise DomainError('invalid_pack_content')
    return [rows[key] for key in expected]

def render(feature,materials,out,locale,style,caps):
    from .rendering import render_pdf,render_pptx
    artifacts=[];all_questions=[]
    for material,spec in zip(materials,slots(feature)):
        key,labels,role,fmt,needs_questions,paired=spec
        fn=render_pptx if fmt=='pptx' else render_pdf
        artifact=fn(material,out/(key+'.'+fmt),locale,role,style=style)
        if artifact['page_count']>caps['slides' if fmt=='pptx' else 'sections']:raise DomainError('generation_limit')
        artifacts.append(artifact);all_questions.extend(material['questions'])
        if paired:
            artifact=render_pdf(material,out/(key+'-answers.pdf'),locale,'teacher_key',style=style)
            if artifact['page_count']>caps['sections']:raise DomainError('generation_limit')
            if feature=='study.exam_pack':artifact['role']='user_document'
            artifacts.append(artifact)
    if feature=='school.weekly_pack':
        answer={'title':materials[0]['title'].split(' · ')[0],'sections':[],'questions':all_questions,'citations':[]}
        artifact=render_pdf(answer,out/'weekly-answers.pdf',locale,'teacher_key',style=style)
        if artifact['page_count']>caps['sections']:raise DomainError('generation_limit')
        artifacts.append(artifact)
    return artifacts
