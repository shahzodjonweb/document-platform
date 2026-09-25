"""Versioned authoring, encrypted drafts and role-aware generated artifacts."""
import hashlib
import json
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from apps.core.errors import DomainError
from apps.core.models import Quote
from apps.core.policy import FEATURES, POLICY_VERSION, plan_limits, SEED
from apps.core.services import owned_assets, storage_path
from operations.integrations import cipher, ai_config
from .models import GenerationDraft

EXCLUDED={'ai.language','ai.length_style','ai.outline','ai.speaker_notes','school.results','school.weak_topics','school.adult_mode','teacher.saved_templates','teacher.branding','teacher.separate_exports','teacher.share_materials'}
GENERATION_IDS={fid for fid in FEATURES if fid.startswith(('ai.','study.','school.','teacher.')) and fid not in EXCLUDED}

def pack(value): return cipher().encrypt(json.dumps(value,ensure_ascii=False).encode())
def unpack(value): return json.loads(cipher().decrypt(bytes(value)))
def allowed(account,fid):
    return fid in FEATURES and FEATURES[fid]['plans'][account.plan] not in ('not_included','unavailable','none','excluded')
def require(account,fid):
    if not settings.ENABLE_BETA_TOOLS or fid not in GENERATION_IDS: raise DomainError('feature_unavailable',409)
    if not allowed(account,fid): raise DomainError('feature_not_in_plan',403)

def limits(account):
    seed=plan_limits(account)
    return {'sections':seed['max_generated_pdf_pages'], 'slides':seed['max_generated_slides'], 'questions':{'free':5,'plus':30,'premium':100}[account.plan], 'source_chars':seed['max_ai_input_tokens']*3}

def validate_content(account,content,output_format='pdf'):
    if not isinstance(content,dict): raise DomainError('invalid_parameters')
    caps=limits(account)
    title=str(content.get('title','Document'))[:160]
    sections=content.get('sections',[])
    max_sections=caps['slides'] if output_format=='pptx' else caps['sections']
    if not isinstance(sections,list) or not 1<=len(sections)<=max_sections: raise DomainError('generation_limit')
    clean=[]
    for i,s in enumerate(sections):
        if not isinstance(s,dict) or len(str(s.get('body','')))>6000: raise DomainError('generation_limit')
        clean.append({'id':str(s.get('id',f's{i+1}'))[:40],'heading':str(s.get('heading',s.get('title','')))[:160],'body':str(s.get('body','')),'notes':str(s.get('notes',''))[:2000]})
    questions=content.get('questions',[])
    if not isinstance(questions,list) or len(questions)>caps['questions']: raise DomainError('generation_limit')
    qs=[]
    for i,q in enumerate(questions):
        if not isinstance(q,dict): raise DomainError('invalid_parameters')
        opts=q.get('options',[])
        if not isinstance(opts,list) or len(opts)>8: raise DomainError('invalid_parameters')
        marks=q.get('marks',1)
        if type(marks)!=int or not 1<=marks<=100: raise DomainError('invalid_parameters')
        qs.append({'id':str(q.get('id',f'q{i+1}'))[:40],'stem':str(q.get('stem',''))[:2000],'options':[str(v)[:500] for v in opts],'answer':str(q.get('answer',''))[:2000],'explanation':str(q.get('explanation',''))[:3000],'topic':str(q.get('topic',title))[:100],'marks':marks})
    if len({q['id'] for q in qs})!=len(qs): raise DomainError('invalid_parameters')
    citations=content.get('citations',[])
    if not isinstance(citations,list) or len(citations)>100 or any(not isinstance(c,dict) or len(json.dumps(c))>4000 for c in citations):raise DomainError('invalid_parameters')
    if len({section['id'] for section in clean})!=len(clean):raise DomainError('invalid_parameters')
    return {'title':title,'sections':clean,'questions':qs,'citations':citations}

def draft_data(d):
    data=unpack(d.encrypted_data)
    if d.feature_id=='study.handwriting':
        from .handwriting import transcription_ready
        data['transcription_ready']=transcription_ready(data)
        data['transcription_reviewed']=data['transcription_ready'] and data.get('_transcription',{}).get('reviewed') is True
    data.pop('_transcription',None)
    return {'id':str(d.id),'feature_id':d.feature_id,'version':d.version,'provider_mode':d.provider_mode,'expires_at':d.expires_at,**data,'outline':[{'id':s['id'],'title':s['heading'],'body':s['body']} for s in data['content']['sections']]}

def source_excerpts(account,ids):
    if not ids:return []
    assets=owned_assets(account,ids)
    if len(assets)>5 or sum(a.page_count for a in assets)>plan_limits(account)['max_ai_source_pages']:raise DomainError('generation_limit')
    # Extraction is performed in the bounded parser child, not inside the HTTP worker.
    result=[]
    for a in assets:
        if a.mime_type!='application/pdf' or a.metadata.get('encrypted'):raise DomainError('unsupported_file')
        from .extraction import extract_pages
        for page,text in extract_pages(storage_path(a.object_key)):
            result.append({'asset_id':str(a.id),'page':page,'text':text[:12000]})
    if sum(len(v['text']) for v in result)>limits(account)['source_chars']:raise DomainError('generation_limit')
    return result

def _prepare_draft(account,data,*,transcribed=False):
    from .handwriting import READONLY_FIELDS
    if set(data)&READONLY_FIELDS:raise DomainError('invalid_parameters')
    fid=data.get('feature_id','ai.pdf_text');require(account,fid)
    fmt=data.get('output_format','pptx' if fid in ('ai.pptx','ai.source_to_slides','school.project_slides') else 'pdf')
    if fid=='ai.images':fmt='png'
    if fmt not in ('pdf','pptx','png') or fmt=='png' and fid!='ai.images':raise DomainError('invalid_parameters')
    from .packs import slots
    if slots(fid):fmt='pdf'
    if fmt=='pptx' and not allowed(account,'ai.pptx'):raise DomainError('feature_not_in_plan',403)
    locale=data.get('output_locale',account.locale)
    if locale not in ('en','uz','ru'):raise DomainError('invalid_locale')
    title=str(data.get('title',data.get('topic','Untitled document'))).strip()[:160] or 'Untitled document'
    text=data.get('source_text',data.get('text',''))
    prompt=data.get('prompt',title)
    if not isinstance(text,str) or not isinstance(prompt,str):raise DomainError('invalid_parameters')
    if len(text)+len(prompt)>limits(account)['source_chars']:raise DomainError('generation_limit')
    ids=data.get('source_ids',data.get('input_ids',[]))
    if fid=='study.handwriting':
        from .handwriting import source_context,require_configuration
        if not transcribed:require_configuration(ai_config())
        excerpts=source_context(account,ids)
    else:excerpts=source_excerpts(account,ids)
    if len(text)+len(prompt)+sum(len(s['text']) for s in excerpts)>limits(account)['source_chars']:raise DomainError('generation_limit')
    # A question still needs something to answer from, but pasted text is a
    # source as much as an uploaded page is.
    if fid=='study.pdf_qa' and not text.strip() and not any(s['text'].strip() for s in excerpts):raise DomainError('source_required')
    options=data.get('options',data.get('parameters',{}))
    if not isinstance(options,dict) or len(json.dumps(options))>4000 or set(options)&READONLY_FIELDS:raise DomainError('invalid_parameters')
    length=options.get('length',min(2,limits(account)['sections']))
    if type(length) is not int:raise DomainError('invalid_parameters')
    question_count=options.get('question_count',min(5,limits(account)['questions']))
    if type(question_count) is not int or not 0<=question_count<=limits(account)['questions']:raise DomainError('generation_limit')
    options={**options,'question_count':question_count}
    template_id=options.get('template_id','clean')
    from .templates import density_style,style_for
    # Validated here so an unknown value fails at authoring time rather than
    # silently rendering at the default spacing.
    density=density_style(options.get('density'))
    template_style=style_for(account,template_id)
    if template_style is not None:options['template_style']={**template_style,**density}
    else:
        from .models import SavedDefinition
        import re
        template=SavedDefinition.objects.filter(account=account,id=template_id,kind='template').first()
        if not template:raise DomainError('not_found',404)
        accent=template.definition.get('content',{}).get('style',{}).get('accent','#255e49')
        if not isinstance(accent,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',accent):raise DomainError('invalid_parameters')
        options['template_style']={'accent':accent,**density}
    from .branding import prepare_branding
    options=prepare_branding(account,fid,options)
    if fid=='school.adaptive':
        from .models import EducationProject
        project=EducationProject.objects.filter(account=account,id=options.get('project_id'),expires_at__gt=timezone.now()).first()
        if not project:raise DomainError('not_found',404)
        attempts=list(project.attempts.order_by('-created_at')[:5])
        if not attempts:raise DomainError('practice_required')
        weak=sorted({topic for attempt in attempts for topic in attempt.result.get('weak_topics',[])})
        questions=unpack(project.encrypted_content).get('questions',[])
        options['adaptive_context']={'project_id':str(project.id),'weak_topics':weak,'practice_attempts':len(attempts),'review_questions':[{'stem':q['stem'],'topic':q['topic']} for q in questions if q['topic'] in weak][:20]}
    else:options.pop('adaptive_context',None)
    if not 1<=length<=limits(account)['slides' if fmt=='pptx' else 'sections']:raise DomainError('generation_limit')
    cfg=ai_config()
    if fid=='ai.images':
        from .illustrations import require_configuration
        require_configuration(cfg)
        if ids or text or options.get('branding') or options.get('source_draft_id') or not prompt.strip() or len(prompt)>4000:raise DomainError('invalid_parameters')
        length=1
    elif fid=='study.handwriting':
        if text or options.get('source_draft_id') or len(prompt)>1000:raise DomainError('invalid_parameters')
        length=1;options['question_count']=0
    elif cfg['mode']=='disabled' or cfg['mode']=='openai' and (not cfg['api_key'] or not cfg['model']):raise DomainError('provider_not_configured',409)
    # Creation is uncharged authoring. Provider calls happen only after an accepted quote.
    chunks=[p.strip() for p in (text or '\n\n'.join(x['text'] for x in excerpts)).split('\n\n') if p.strip()]
    headings={'en':['Overview','Key ideas','Practice','Review'],'uz':['Umumiy ma’lumot','Asosiy fikrlar','Mashq','Takrorlash'],'ru':['Обзор','Основные идеи','Практика','Повторение']}[locale]
    sections=[{'id':f's{i+1}','heading':headings[i%4], 'body':('\n\n'.join(chunks[i:]) if i==length-1 else chunks[i]) if i<len(chunks) else '', 'notes':''} for i in range(length)]
    content=validate_content(account,{'title':title,'sections':sections,'questions':options.get('questions',[]),'citations':[{'asset_id':x['asset_id'],'page':x['page']} for x in excerpts]},fmt)
    payload={'title':title,'prompt':prompt,'source_text':text,'source_ids':ids,'excerpts':excerpts,'output_locale':locale,'output_format':fmt,'options':options,'content':content}
    from .revisions import prepare_revision
    payload=prepare_revision(account,fid,payload)
    if len(payload['excerpts'])>plan_limits(account)['max_ai_source_pages']:raise DomainError('generation_limit')
    if payload['source_ids']:owned_assets(account,payload['source_ids'])
    if cfg['mode']=='openai' and fid!='ai.images' and not transcribed:
        enforce_budget(cfg,payload,fid,plan_limits(account)['max_ai_input_tokens'])
    return fid,cfg,payload

def enforce_budget(config,payload,feature_id,token_limit):
    if feature_id=='study.handwriting':
        from .handwriting import enforce_input_budget
        return enforce_input_budget(config,payload,token_limit)
    from .provider import enforce_input_budget
    return enforce_input_budget(config,payload,feature_id,token_limit)

def create_draft(account,data):
    fid,cfg,payload=_prepare_draft(account,data)
    return GenerationDraft.objects.create(account=account,feature_id=fid,encrypted_data=pack(payload),provider_mode=cfg['mode'],expires_at=timezone.now()+timedelta(hours=24))

@transaction.atomic
def update_draft(account,draft_id,data):
    d=GenerationDraft.objects.select_for_update().filter(account=account,id=draft_id,expires_at__gt=timezone.now()).first()
    if not d:raise DomainError('not_found',404)
    if data.get('version')!=d.version:raise DomainError('version_conflict',409)
    original=unpack(d.encrypted_data)
    allowed_keys={'version','title','prompt','source_text','source_ids','output_locale','output_format','options','content','outline'}
    if set(data)-allowed_keys:raise DomainError('invalid_parameters')
    fields={key:original[key] for key in ('title','prompt','source_text','source_ids','output_locale','output_format','options')}
    fields.update({key:value for key,value in data.items() if key in fields})
    from .handwriting import transcription_ready
    keep_transcription=d.feature_id=='study.handwriting' and transcription_ready(original) and fields['source_ids']==original['source_ids']
    _,cfg,payload=_prepare_draft(account,{'feature_id':d.feature_id,**fields},transcribed=keep_transcription)
    if cfg['mode']!=d.provider_mode and not keep_transcription:raise DomainError('provider_changed',409)
    rebuild=any(key in data and data[key]!=original.get(key) for key in ('source_text','source_ids','output_format')) or ('options' in data and data['options'].get('length')!=original['options'].get('length'))
    content=data.get('content',payload['content'] if rebuild and not keep_transcription else original['content'])
    if 'outline' in data:
        outline=data['outline']
        if not isinstance(outline,list) or any(not isinstance(s,dict) for s in outline):raise DomainError('invalid_parameters')
        content={**content,'sections':[{'id':s.get('id',str(i)),'heading':s.get('title',''),'body':s.get('body',''),'notes':s.get('notes','')} for i,s in enumerate(outline)]}
    if 'title' in data and isinstance(content,dict):content={**content,'title':payload['title']}
    payload['content']=validate_content(account,content,payload['output_format'])
    from .revisions import preserve_unselected
    payload['content']=preserve_unselected(payload,payload['content'])
    payload['title']=payload['content']['title']
    if keep_transcription:
        payload['_transcription']={**original['_transcription'],'reviewed':original['_transcription'].get('reviewed') is True or 'content' in data or 'outline' in data}
    if cfg['mode']=='openai' and d.feature_id!='ai.images' and not keep_transcription:
        enforce_budget(cfg,payload,d.feature_id,plan_limits(account)['max_ai_input_tokens'])
    d.encrypted_data=pack(payload);d.version+=1;d.save(update_fields=['encrypted_data','version'])
    return d

def generation_quote(account,draft_id,version):
    d=GenerationDraft.objects.filter(account=account,id=draft_id,expires_at__gt=timezone.now()).first()
    if not d:raise DomainError('not_found',404)
    require(account,d.feature_id)
    if version!=d.version:raise DomainError('version_conflict',409)
    data=unpack(d.encrypted_data)
    cfg=ai_config()
    from .handwriting import reviewed_export
    export=d.feature_id=='study.handwriting' and reviewed_export(account,data)
    if cfg['mode']!=d.provider_mode and not export:raise DomainError('provider_changed',409)
    # Sandbox is deterministic authoring; it never charges AI credits or pretends to call a model.
    import math
    tariff=SEED['tariff_v0_staging'];caps=limits(account)
    from .packs import slots,question_multiplier,output_ceiling
    question_cap=max(len(data['content']['questions']),int(data['options'].get('question_count',min(5,caps['questions']))))*question_multiplier(d.feature_id)
    if not 0<=question_cap<=caps['questions']:raise DomainError('generation_limit')
    output_cap=caps['slides'] if data['output_format']=='pptx' else caps['sections']
    output_units=output_cap*tariff['pptx_output_credits_per_slide' if data['output_format']=='pptx' else 'pdf_output_credits_per_started_page']
    key_units=caps['sections']*tariff['pdf_output_credits_per_started_page'] if d.feature_id.startswith('teacher.') else 0
    if slots(d.feature_id):output_units=output_ceiling(d.feature_id,caps,tariff);key_units=0
    from .metering import generation_credits
    credits=0 if d.provider_mode=='local_fixture' else generation_credits(d.feature_id,len(data['excerpts']),question_cap,output_units+key_units,tariff)
    if d.feature_id=='ai.images':
        from .illustrations import require_configuration
        require_configuration(cfg)
        credits=tariff['generated_image_credits']
    if export:credits=0
    if cfg['mode']=='openai' and d.feature_id!='ai.images' and not export:
        enforce_budget(cfg,data,d.feature_id,plan_limits(account)['max_ai_input_tokens'])
    snapshot=hashlib.sha256(bytes(d.encrypted_data)).hexdigest()
    from .branding import generation_inputs
    input_ids=generation_inputs(data)
    return Quote.objects.create(account=account,feature_id=d.feature_id,input_ids=input_ids,input_fingerprints=[{'id':str(a.id),'sha256':a.sha256} for a in owned_assets(account,input_ids)] if input_ids else [],parameters={'generation_draft_id':str(d.id),'draft_version':d.version,'snapshot':snapshot,**({'stage':'export'} if export else {})},meters={'file_tasks':0,'file_page_units':0,'ai_credits':credits},policy={'plan':account.plan,'version':POLICY_VERSION,'tariff_version':'generation-draft-staging-v1','limits':plan_limits(account),'provider_mode':d.provider_mode,'provider_model':cfg['model'],'provider_image_model':cfg.get('image_model',''),'generation_bounds':{'question_cap':question_cap,'output_pages':output_cap,'key_pages':caps['sections'],'input_tokens':plan_limits(account)['max_ai_input_tokens'],'tariff':dict(tariff)}},expires_at=timezone.now()+timedelta(minutes=10))

def validate_generation_quote(account,quote):
    require(account,quote.feature_id)
    d=GenerationDraft.objects.filter(id=quote.parameters.get('generation_draft_id'),account=account,expires_at__gt=timezone.now()).first()
    if not d or d.version!=quote.parameters.get('draft_version') or hashlib.sha256(bytes(d.encrypted_data)).hexdigest()!=quote.parameters.get('snapshot'):raise DomainError('version_conflict',409)
    config=ai_config()
    if quote.parameters.get('stage')=='export':
        from .handwriting import reviewed_export
        if d.feature_id!='study.handwriting' or not reviewed_export(account,unpack(d.encrypted_data)) or any(quote.meters.values()):raise DomainError('invalid_parameters')
    elif config['mode']!=d.provider_mode or quote.policy.get('provider_model','')!=config['model']:raise DomainError('provider_changed',409)
    if d.feature_id=='ai.images':
        from .illustrations import require_configuration
        require_configuration(config)
        if quote.policy.get('provider_image_model')!=config.get('image_model'):raise DomainError('provider_changed',409)
    return owned_assets(account,quote.input_ids) if quote.input_ids else []
