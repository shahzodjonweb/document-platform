import hashlib
import json
import secrets
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from apps.core.views import api,body,download_asset,throttle
from apps.core.errors import DomainError
from apps.core.models import Artifact,FileAsset,Job
from apps.core.serializers import asset_data,quote_data,job_data
from apps.core.services import owned_assets,create_quote,submit_job,execute_job,record_event
from apps.core.policy import FEATURES,plan_limits,require_feature
from operations.integrations import ai_config
from .domain import DOCUMENT,SLIDES,GENERATION_IDS,_image_cap,allowed,create_draft,draft_data,draft_jobs,update_draft,generation_quote,pack,unpack,limits
from .models import GenerationDraft,SavedDefinition,EducationProject,PracticeAttempt,ShareGrant,EditorDocument,WorkflowRun

@api()
def config(request):
    """Two services, and what a description is allowed to ask them for."""
    from .pages import DEFAULT_PAGES, ceiling
    cfg=ai_config();features=[]
    for fid in (DOCUMENT,SLIDES):
        formats=['pptx'] if fid==SLIDES else ['pdf']
        features.append({'id':fid,'name':FEATURES[fid]['name'],'surface':'generate',
                         'eligible':settings.ENABLE_BETA_TOOLS and allowed(request.account,fid),
                         'requires_provider':False,
                         'parameter_schema':{'output_locale':{'enum':['en','uz','ru']},'output_format':{'enum':formats}},
                         'max_pages':ceiling(request.account,'pptx' if fid==SLIDES else 'pdf'),
                         'max_images':_image_cap(request.account,fid),
                         'locales':['en','uz','ru']})
    return {'provider':{'id':cfg['mode'],'mode':cfg['mode'],
                        'label':'Local authoring (no AI)' if cfg['mode']=='local_fixture' else 'OpenAI' if cfg['mode']=='openai' else 'Not configured',
                        'configured':cfg['mode']=='local_fixture' or bool(cfg['api_key'] and cfg['model'])},
            'features':features,'generation_features':features,
            'default_pages':DEFAULT_PAGES,'limits':limits(request.account)}

@api(('GET','POST'))
def drafts(request):
    if request.method=='POST':
        throttle(request,'generation_drafts',20)
        return JsonResponse(draft_data(create_draft(request.account,body(request))),status=201)
    return {'results':[draft_data(d) for d in GenerationDraft.objects.filter(account=request.account,expires_at__gt=timezone.now()).order_by('-created_at')[:100]]}

@api(('GET','PATCH','DELETE'))
def draft_detail(request,pk):
    d=GenerationDraft.objects.filter(account=request.account,id=pk,expires_at__gt=timezone.now()).first()
    if not d:raise DomainError('not_found',404)
    if request.method=='DELETE':d.delete();return {'deleted':True}
    if request.method=='PATCH':d=update_draft(request.account,pk,body(request))
    return draft_data(d)

@api(('POST',))
def outline(request,pk):
    # Review/outline authoring is free. Live generation is only invoked after quote confirmation.
    d=GenerationDraft.objects.filter(account=request.account,id=pk,expires_at__gt=timezone.now()).first()
    if not d:raise DomainError('not_found',404)
    if body(request).get('version')!=d.version:raise DomainError('version_conflict',409)
    return draft_data(d)

@api(('GET',))
def deck_designs(request):
    """Every design a deck can wear, grouped, with the colours each renders in."""
    from .deck_designs import catalogue
    from .pages import SETUP_SLIDES
    locale=request.GET.get('locale',request.account.locale)
    return {'categories':catalogue(locale if locale in ('en','uz','ru') else 'en'),'default_pages':SETUP_SLIDES}

@api(('POST',))
def draft_setup(request,pk):
    """A deck's slide count and design, chosen on the setup screen over what the description says.

    One call changes both and returns the new price, and the review in the
    bot's chat is redrawn with it, so its Generate button pays for this.
    """
    throttle(request,'generation_drafts',20)
    data=body(request)
    if not data or set(data)-{'pages','deck_design'}:raise DomainError('invalid_parameters')
    d=GenerationDraft.objects.filter(account=request.account,id=pk,expires_at__gt=timezone.now()).first()
    if not d:raise DomainError('not_found',404)
    if d.feature_id!=SLIDES:raise DomainError('invalid_parameters')
    # A deck already made is changed with a new description, not by restyling
    # its draft; one still being made is refused by update_draft.
    if draft_jobs(request.account,d.id,('succeeded','no_op')):raise DomainError('generation_finished',409)
    d=update_draft(request.account,pk,{'version':d.version,'options':{**unpack(d.encrypted_data)['options'],**data}})
    quote=generation_quote(request.account,d.id,d.version)
    from telegram.bot import refresh_review
    refresh_review(request.account,d,quote)
    return {'draft':draft_data(d),'quote':quote_data(quote)}

@api(('POST',))
def draft_quote(request,pk):
    data=body(request);stage=data.get('stage','document')
    if stage not in ('document','outline'):raise DomainError('invalid_parameters')
    if stage=='outline':
        from .outlines import create_outline_quote
        quote=create_outline_quote(request.account,pk,data.get('version'))
    else:quote=generation_quote(request.account,pk,data.get('version'))
    return JsonResponse(quote_data(quote),status=201)

@api(('POST',))
def retry_quote(request,pk):
    from .checkpoints import retry_quote as prepare_retry
    throttle(request,'generation_retry_quote',20)
    return JsonResponse(quote_data(prepare_retry(request.account,pk)),status=201)

@api(('POST',))
def generate(request,pk):
    from apps.core.models import Quote
    data=body(request);q=Quote.objects.filter(pk=data.get('quote_id'),account=request.account,parameters__generation_draft_id=str(pk)).first()
    if not q:raise DomainError('not_found',404)
    job,created=submit_job(request.account,q.id,request.headers.get('Idempotency-Key',''))
    if settings.LOCAL_SYNC_JOBS and created:job=execute_job(job.id)
    return JsonResponse(job_data(job),status=201 if created else 200)

def definition_data(row):return {'id':str(row.id),'name':row.name,'kind':row.kind,'version':row.version,**row.definition}
def definition_cap(account,kind):
    caps=plan_limits(account)
    return caps['saved_workflows'] if kind=='workflow' else caps['saved_teacher_templates'] if kind=='template' else 30 if account.plan=='premium' else 0
def validate_definition(data,kind):
    name=str(data.get('name','')).strip()[:160]
    if not name:raise DomainError('name_required')
    if kind=='workflow':
        steps=data.get('steps',[])
        if not isinstance(steps,list) or not 1<=len(steps)<=5:raise DomainError('invalid_parameters')
        valid={'pdf.rotate','pdf.extract_pages','pdf.delete_pages','pdf.reorder','pdf.compress','pdf.to_images','convert.word_to_pdf','convert.pptx_to_pdf','ocr.searchable_pdf','ocr.extract_text','convert.pdf_to_docx','convert.pdf_to_xlsx'}
        for step in steps:
            if not isinstance(step,dict) or step.get('feature_id') not in valid or not isinstance(step.get('parameters',{}),dict):raise DomainError('invalid_parameters')
        return name,{'steps':steps}
    content=data.get('content',data.get('definition',{}))
    if not isinstance(content,dict) or len(json.dumps(content))>20000:raise DomainError('invalid_parameters')
    if kind=='form':
        from .batches import validate_form_template
        content=validate_form_template(content)
    return name,{'content':content,'output_locale':data.get('output_locale','en')}

@api(('GET','POST'))
def definitions(request,kind):
    from .templates import published
    qs=SavedDefinition.objects.filter(account=request.account,kind=kind)
    if request.method=='POST':
        name,value=validate_definition(body(request),kind)
        with transaction.atomic():
            from apps.core.models import Account
            Account.objects.select_for_update().get(pk=request.account.pk)
            if qs.count()>=definition_cap(request.account,kind):raise DomainError('saved_limit',403)
            row=SavedDefinition.objects.create(account=request.account,kind=kind,name=name,definition=value)
        return JsonResponse(definition_data(row),status=201)
    return {'results':[definition_data(v) for v in qs.order_by('-created_at')],'limit':definition_cap(request.account,kind),'published':published(request.account) if kind=='template' else []}

@api(('GET','PATCH','DELETE'))
def definition_detail(request,pk,kind):
    with transaction.atomic():
        row=SavedDefinition.objects.select_for_update().filter(account=request.account,kind=kind,id=pk).first()
        if not row:raise DomainError('not_found',404)
        if request.method=='DELETE':row.delete();return {'deleted':True}
        if request.method=='PATCH':
            data=body(request)
            if data.get('version')!=row.version:raise DomainError('version_conflict',409)
            row.name,row.definition=validate_definition(data,kind);row.version+=1;row.save()
        return definition_data(row)

@api(('POST',))
def workflow_quote(request,pk):
    from .workflows import quote
    return quote(request.account,pk,body(request).get('input_ids',[]))

@api(('POST',))
def workflow_run(request,pk):
    from .workflows import start,execute,data
    run,token=start(request.account,pk,body(request),request.headers.get('Idempotency-Key',''))
    return data(execute(run,token))

def project_data(p,details=False):
    value={'id':str(p.id),'title':p.title,'version':p.version,'expires_at':p.expires_at,'created_at':p.created_at,'attempts':[a.result for a in p.attempts.order_by('-created_at')[:20]]}
    if details:value['content']=unpack(p.encrypted_content)
    return value
@api(('GET','POST'))
def projects(request):
    qs=EducationProject.objects.filter(account=request.account,expires_at__gt=timezone.now())
    cap=plan_limits(request.account)['opt_in_study_projects']
    if request.method=='POST':
        data=body(request)
        if data.get('save_consent') is not True:raise DomainError('save_consent_required')
        draft=GenerationDraft.objects.filter(account=request.account,id=data.get('draft_id'),expires_at__gt=timezone.now()).first()
        if not draft:raise DomainError('not_found',404)
        content=unpack(draft.encrypted_data)['content']
        with transaction.atomic():
            from apps.core.models import Account
            Account.objects.select_for_update().get(pk=request.account.id)
            if qs.count()>=cap:raise DomainError('saved_limit',403)
            p=EducationProject.objects.create(account=request.account,title=str(data.get('title',content['title']))[:160],encrypted_content=pack(content),expires_at=timezone.now()+timedelta(days=90))
        return JsonResponse(project_data(p,True),status=201)
    return {'results':[project_data(p) for p in qs.order_by('-created_at')],'limit':cap,'retention_days':90}
@api(('GET','PATCH','DELETE'))
def project_detail(request,pk):
    with transaction.atomic():
        p=EducationProject.objects.select_for_update().filter(account=request.account,id=pk,expires_at__gt=timezone.now()).first()
        if not p:raise DomainError('not_found',404)
        if request.method=='DELETE':p.delete();return {'deleted':True}
        if request.method=='PATCH':
            data=body(request)
            if data.get('version')!=p.version or data.get('save_consent') is not True:raise DomainError('version_conflict',409)
            p.expires_at=timezone.now()+timedelta(days=90);p.version+=1;p.save(update_fields=['expires_at','version'])
        return project_data(p,True)
@api(('POST',))
def practice(request,pk):
    with transaction.atomic():
        p=EducationProject.objects.select_for_update().filter(account=request.account,id=pk,expires_at__gt=timezone.now()).first()
        if not p:raise DomainError('not_found',404)
        data=body(request);answers=data.get('answers',{});key=request.headers.get('Idempotency-Key','')
        if not isinstance(answers,dict) or not 8<=len(key)<=128:raise DomainError('invalid_parameters')
        digest=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
        prior=p.attempts.filter(idempotency_key=key).first()
        if prior:
            if prior.request_hash!=digest:raise DomainError('idempotency_conflict',409)
            return prior.result
        questions=unpack(p.encrypted_content).get('questions',[])
        if not questions or set(answers)-{q['id'] for q in questions}:raise DomainError('invalid_parameters')
        rows=[];weak=set();earned=0;total=0
        for q in questions:
            correct=str(answers.get(q['id'],'')).strip().casefold()==q['answer'].strip().casefold()
            if correct:earned+=q['marks']
            else:weak.add(q['topic'])
            total+=q['marks'];rows.append({'question_id':q['id'],'correct':correct,'expected_answer':q['answer'],'explanation':q['explanation'],'marks':q['marks'] if correct else 0})
        result={'score':earned,'max_score':total,'questions':rows,'weak_topics':sorted(weak),'grading':'exact_match_practice_not_final_grade'}
        PracticeAttempt.objects.create(project=p,idempotency_key=key,request_hash=digest,result=result)
        record_event(request.account,'practice.completed',properties={'correct':earned,'total':total})
        return result

@api(('GET','POST'))
def shares(request):
    if request.method=='POST':
        data=body(request)
        if not allowed(request.account,'teacher.share_materials'):raise DomainError('feature_not_in_plan',403)
        a=Artifact.objects.select_related('file').filter(id=data.get('artifact_id'),account=request.account,role__in=('learner_material','public_preview')).first()
        from .privacy import may_share_artifact
        if not a or not may_share_artifact(a):raise DomainError('share_role_forbidden',403)
        if a.file.state!='ready' or a.file.expires_at<=timezone.now():raise DomainError('file_expired',410)
        hours=data.get('expires_hours',24)
        if type(hours)!=int or not 1<=hours<=24:raise DomainError('invalid_parameters')
        token=secrets.token_urlsafe(32)
        row=ShareGrant.objects.create(account=request.account,artifact=a,token_hash=hashlib.sha256(token.encode()).hexdigest(),expires_at=min(a.file.expires_at,timezone.now()+timedelta(hours=hours)))
        return {'id':str(row.id),'url':'/api/v1/shared/'+token,'expires_at':row.expires_at}
    return {'results':[{'id':str(s.id),'artifact_id':str(s.artifact_id),'expires_at':s.expires_at,'revoked':bool(s.revoked_at)} for s in ShareGrant.objects.filter(account=request.account)]}
@api(('GET','DELETE'))
def share_detail(request,pk):
    s=ShareGrant.objects.filter(account=request.account,id=pk).first()
    if not s:raise DomainError('not_found',404)
    if request.method=='DELETE':s.revoked_at=timezone.now();s.save(update_fields=['revoked_at'])
    return {'id':str(s.id),'revoked':bool(s.revoked_at),'expires_at':s.expires_at}
@api(auth=False)
def shared(request,token):
    throttle(request,'shared',30)
    s=ShareGrant.objects.select_related('artifact__file').filter(token_hash=hashlib.sha256(token.encode()).hexdigest(),expires_at__gt=timezone.now(),revoked_at__isnull=True,artifact__role__in=('learner_material','public_preview')).first()
    from .privacy import may_share_artifact
    if not s or not may_share_artifact(s.artifact):raise DomainError('not_found',404)
    return download_asset(request,s.artifact.file)

def editor_data(e):
    return {'id':str(e.id),'version':e.version,'file':asset_data(e.file),'pages':e.file.metadata.get('page_sizes',[]),'form_fields':e.file.metadata.get('form_fields',[]),'image_counts':e.file.metadata.get('image_counts',[]),'commands':e.commands,'input_ids':e.input_ids}
@api(('GET','POST'))
def editors(request):
    if request.method=='POST':
        data=body(request);fid=data.get('file_id',data.get('input_id'))
        a=owned_assets(request.account,[fid])[0]
        if a.mime_type!='application/pdf' or a.metadata.get('encrypted'):raise DomainError('unsupported_file')
        e=EditorDocument.objects.create(account=request.account,file=a,input_ids=[str(a.id)])
        return JsonResponse(editor_data(e),status=201)
    return {'results':[editor_data(e) for e in EditorDocument.objects.filter(account=request.account,file__expires_at__gt=timezone.now(),file__state='ready').select_related('file')]}
@api(('GET','PATCH','DELETE'))
def editor_detail(request,pk):
    with transaction.atomic():
        e=EditorDocument.objects.select_for_update().select_related('file').filter(account=request.account,id=pk).first()
        if not e:raise DomainError('not_found',404)
        if e.file.state!='ready' or e.file.expires_at<=timezone.now():raise DomainError('file_expired',410)
        if request.method=='DELETE':e.delete();return {'deleted':True}
        if request.method=='PATCH':
            data=body(request)
            if data.get('version')!=e.version:raise DomainError('version_conflict',409)
            commands=data.get('commands',[])
            if not isinstance(commands,list) or len(commands)>100 or len(json.dumps(commands))>20000:raise DomainError('invalid_parameters')
            ids=data.get('input_ids',e.input_ids)
            if not ids or str(ids[0])!=str(e.file_id):raise DomainError('invalid_inputs')
            from apps.core.services import validate_inputs
            from .editor_policy import validate_commands_access
            from processors import normalize_parameters,ProcessorError
            assets=validate_inputs(request.account,'editor.visual',ids)
            validate_commands_access(request.account,commands)
            if commands:
                try:commands=normalize_parameters('editor.visual',{'commands':commands,'accept_rasterization':True},[a.metadata for a in assets])['commands']
                except ProcessorError as error:raise DomainError(error.code) from None
            e.commands=commands;e.input_ids=ids;e.version+=1;e.save(update_fields=['commands','input_ids','version'])
        return editor_data(e)
@api(('POST',))
def editor_quote(request,pk):
    e=EditorDocument.objects.filter(account=request.account,id=pk).first()
    if not e:raise DomainError('not_found',404)
    data=body(request)
    if data.get('version')!=e.version:raise DomainError('version_conflict',409)
    q=create_quote(request.account,'editor.visual',e.input_ids,{'commands':e.commands,'accept_rasterization':data.get('accept_rasterization',False)})
    return JsonResponse(quote_data(q),status=201)
