import hashlib
import json
import secrets
from datetime import timedelta
from django.conf import settings
from django.db import IntegrityError,transaction
from django.http import JsonResponse
from django.utils import timezone
from apps.core.views import account_limit,api,body,count_request,download_asset,throttle
from apps.core.errors import DomainError
from apps.core.models import Artifact,FileAsset,Job
from apps.core.serializers import asset_data,quote_data,job_data
from apps.core.services import owned_assets,create_quote,submit_job,execute_job,record_event
from apps.core.policy import EDITOR_LIMITS,FEATURES,payload_bytes,plan_limits,require_feature
from operations.integrations import ai_config,editor_flags
from .domain import CV,DOCUMENT,SLIDES,GENERATION_IDS,_image_cap,allowed,create_draft,draft_data,draft_jobs,update_draft,generation_quote,pack,unpack,limits
from .editor_domain import file_gone,normalized_commands,quote_draft,version_conflict
from .editor_policy import COMMAND_COLUMNS,store_commands,stored_commands
from .models import GenerationDraft,SavedDefinition,EducationProject,PracticeAttempt,ShareGrant,EditorDocument,WorkflowRun

@api()
def config(request):
    """Three services, and what a description is allowed to ask them for.

    A CV is one page or two, whatever the plan's page cap: the renderer, not
    the description, decides which. It is made from one message, a LinkedIn
    profile or an old CV (`source_modes`), each of the last two from files of
    the kinds `source_kinds` names, at most `max_source_files` of them. What it
    is made of is `cv_facts`: the facts it is asked for when missing
    (`required`) and the ones only offered (`optional`), in the order shown.
    """
    from .cv import sources as cv_sources
    from .cv.content import OPTIONAL_FACTS,REQUIRED_FACTS
    from .cv.render import MAX_PAGES as CV_PAGES
    from .pages import DEFAULT_PAGES, ceiling
    cfg=ai_config();features=[]
    for fid in (DOCUMENT,SLIDES,CV):
        formats=['pptx'] if fid==SLIDES else ['pdf']
        features.append({'id':fid,'name':FEATURES[fid]['name'],'surface':'generate',
                         'eligible':settings.ENABLE_BETA_TOOLS and allowed(request.account,fid),
                         'requires_provider':False,
                         'parameter_schema':{'output_locale':{'enum':['en','uz','ru']},'output_format':{'enum':formats}},
                         'max_pages':CV_PAGES if fid==CV else ceiling(request.account,'pptx' if fid==SLIDES else 'pdf'),
                         'max_images':_image_cap(request.account,fid),
                         'locales':['en','uz','ru']})
        if fid==CV:
            features[-1].update(source_modes=list(cv_sources.MODES),
                                source_kinds={mode:list(kinds) for mode,kinds in cv_sources.KINDS.items()},
                                max_source_files=cv_sources.max_files(request.account),
                                max_source_pages=cv_sources.max_pages(request.account),
                                cv_facts={'required':list(REQUIRED_FACTS),'optional':list(OPTIONAL_FACTS)})
    return {'provider':{'id':cfg['mode'],'mode':cfg['mode'],
                        'label':'Local authoring (no AI)' if cfg['mode']=='local_fixture' else 'OpenAI' if cfg['mode']=='openai' else 'Not configured',
                        'configured':cfg['mode']=='local_fixture' or bool(cfg['api_key'] and cfg['model'])},
            'features':features,'generation_features':features,
            'default_pages':DEFAULT_PAGES,'limits':{**limits(request.account),'editor':editor_flags()}}

def _queue_cv_reads(account,data,options=None):
    """The reads of a CV draft's files queued before the draft is made (cv/reads.py ensure_ids).

    A file uploaded before reads were queued has none; one queued inside the
    draft's own transaction would be taken back with a `cv_reading` refusal.
    """
    from .cv.sources import KINDS
    options=options if options is not None else data.get('options',data.get('parameters',{}))
    if isinstance(options,dict) and options.get('cv_source') in KINDS:
        from .cv.reads import ensure_ids
        ensure_ids(account,data.get('source_ids',data.get('input_ids')))

@api(('GET','POST'))
def drafts(request):
    if request.method=='POST':
        throttle(request,'generation_drafts',20)
        data=body(request)
        if data.get('feature_id')==CV:_queue_cv_reads(request.account,data)
        return JsonResponse(draft_data(create_draft(request.account,data)),status=201)
    return {'results':[draft_data(d) for d in GenerationDraft.objects.filter(account=request.account,expires_at__gt=timezone.now()).order_by('-created_at')[:100]]}

# How often one account may reword a CV draft in a minute: each is read again
# for the person's name. Counted per account, as every customer reaches us
# through the same gateway address.
CV_UPDATES_PER_MINUTE=30
# The deck editor saves a deck whole on every edit: a long one in Cyrillic, two bytes a letter, passes 32 KiB well inside its caps.
DECK_PATCH_BYTES=131072

@api(('GET','PATCH','DELETE'))
def draft_detail(request,pk):
    d=GenerationDraft.objects.filter(account=request.account,id=pk,expires_at__gt=timezone.now()).first()
    if not d:raise DomainError('not_found',404)
    if request.method=='DELETE':
        from .tasks import drop_renders
        # Under the draft's lock: a render storing its pictures finishes first and they are seen here, or it finds the draft gone.
        with transaction.atomic():
            GenerationDraft.objects.select_for_update().filter(pk=d.pk).first()
            drop_renders(d)
            d.delete()
        return {'deleted':True}
    if request.method=='PATCH':
        data=body(request,limit=DECK_PATCH_BYTES,too_large='payload_too_large') if d.feature_id==SLIDES else body(request)
        if d.feature_id==CV:
            account_limit(request.account,'cv_draft_updates',CV_UPDATES_PER_MINUTE)
            _queue_cv_reads(request.account,data,unpack(d.encrypted_data).get('options',{}))
        d=update_draft(request.account,pk,data)
    return _with_editor_state(request.account,d,draft_data(d))

def _with_editor_state(account,d,data):
    """A drawn deck as the slide editor reads it, opened or saved: whether a send this week uses a file task, and what its pictures allow today."""
    if d.feature_id!=SLIDES or not data.get('render') or not editor_flags()['deck_editor']:return data
    from apps.core.allowance import counted_this_week
    from .deck_photos import state
    return {**data,'send':{'counted_this_week':counted_this_week(account,{'generation_draft_id':str(d.pk)})},'pictures':state(account,unpack(d.encrypted_data))}

# How often one account may ask how its CV's files are being read: the web
# asks every two seconds while it waits, from a tab or two (60 a minute), and
# again as a file is uploaded or a draft is refused while it is read.
CV_READS_PER_MINUTE=120

@api(('GET','DELETE'))
def cv_reads(request):
    """How the reading of a CV's files stands: each file's read, how many reads are ahead, and about how long.

    `ids` names the files, the account's own, at most as many as a CV is made
    from; an id that is no live file of theirs is `file_unavailable` (404).
    A file with no read yet (uploaded before reads were queued) is queued.

    DELETE takes files the customer removed from the form out of the line:
    their reads still queued are dropped, so nobody waits behind a file no CV
    will use. A read already started finishes; an id that is gone, or not the
    account's, is passed over. A file dropped here and used after all is
    queued again when a draft asks for it.
    """
    from .cv import reads,sources as cv_sources
    ids=request.GET.getlist('ids')
    if len(ids)>cv_sources.MAX_FILES:raise DomainError('invalid_inputs')
    if request.method=='DELETE':
        import uuid
        from .models import CvSourceRead
        valid=[]
        for value in ids:
            try:valid.append(uuid.UUID(str(value)))
            except ValueError:continue
        cancelled,_=CvSourceRead.objects.filter(account=request.account,asset_id__in=valid,status='queued').delete()
        return {'cancelled':cancelled}
    account_limit(request.account,'cv_reads',CV_READS_PER_MINUTE)
    return reads.state(request.account,owned_assets(request.account,ids))

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

@api(auth=False)
def deck_design_preview(request,design):
    """A design's cover as the theme picker shows it. No customer data: public and cacheable."""
    from django.http import HttpResponse
    from .deck_designs import DESIGNS,thumbnail
    locale=request.GET.get('locale','en')
    if design not in DESIGNS or locale not in ('en','uz','ru'):raise DomainError('not_found',404)
    response=HttpResponse(thumbnail(design,locale),content_type='image/png')
    # The URL carries the design's version, so a cached copy is never stale.
    response['Cache-Control']='public, max-age=604800, immutable'
    return response

@api(('GET',))
def cv_templates(request):
    """Every template a CV can wear, grouped, with the colours each renders in and the one Auto starts from."""
    from .cv.templates import DEFAULT_TEMPLATE,catalogue
    locale=request.GET.get('locale',request.account.locale)
    return {'categories':catalogue(locale if locale in ('en','uz','ru') else 'en'),'default':DEFAULT_TEMPLATE}

@api(auth=False)
def cv_template_preview(request,template):
    """A template's page 1 with the sample CV, as the picker shows it. No customer data: public and cacheable."""
    from django.http import HttpResponse
    from .cv.templates import TEMPLATES,thumbnail
    locale=request.GET.get('locale','en')
    if template not in TEMPLATES or locale not in ('en','uz','ru'):raise DomainError('not_found',404)
    response=HttpResponse(thumbnail(template,locale),content_type='image/png')
    # The URL carries the catalogue's version, so a cached copy is never stale.
    response['Cache-Control']='public, max-age=604800, immutable'
    return response

# What each service's setup screen may choose: a deck its slide count and
# design, a CV its template. A document has no setup screen.
SETUP_KEYS={SLIDES:{'pages','deck_design'},CV:{'cv_template'}}

@api(('POST',))
def draft_setup(request,pk):
    """A deck's slide count and design, or a CV's template, chosen on the setup screen over what the description says.

    One call changes them and returns the new price, and the review in the
    bot's chat is redrawn with it, so its Generate button pays for this.
    """
    throttle(request,'generation_drafts',20)
    data=body(request)
    if not data or set(data)-set().union(*SETUP_KEYS.values()):raise DomainError('invalid_parameters')
    d=GenerationDraft.objects.filter(account=request.account,id=pk,expires_at__gt=timezone.now()).first()
    if not d:raise DomainError('not_found',404)
    if set(data)-SETUP_KEYS.get(d.feature_id,set()):raise DomainError('invalid_parameters')
    # A change is decided by its request alone. A setup screen still open on one
    # would restyle it, and its count, which a change does not carry, starts at
    # the setup screen's default (pages.SETUP_SLIDES), not the deck's own length.
    if unpack(d.encrypted_data).get('revision'):raise DomainError('controls_expired',409)
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

# One draws every slide of a deck, up to two seconds of an API worker (render_export.MEASURE_SECONDS);
# the other one slide in every layout, about 0.8 s at worst however long the deck (FIT_SECONDS and the slide itself). Counted per account,
# as every customer reaches us through the same gateway address.
EXPORT_QUOTES_PER_MINUTE=10
FITS_PER_MINUTE=60

def _require_deck_editor():
    if not editor_flags()['deck_editor']:raise DomainError('feature_unavailable',409)

@api(('POST',))
def draft_export_quote(request,pk):
    """The price of sending a deck again from its draft, with what Review says about it (render_export.py)."""
    _require_deck_editor()
    account_limit(request.account,'deck_export_quotes',EXPORT_QUOTES_PER_MINUTE)
    data=body(request)
    from .render_export import export_quote,quote_summary
    quote=export_quote(request.account,pk,data.get('version'),data.get('format'),data.get('deliver'))
    return JsonResponse({**quote_data(quote),'summary':quote_summary(request.account,quote)},status=201)

@api(('POST',))
def draft_fit(request,pk):
    """How one slide as it is being typed sits on the deck, and the layouts that would hold it whole. Nothing is saved."""
    _require_deck_editor()
    account_limit(request.account,'deck_fits',FITS_PER_MINUTE)
    from .render_export import fit_section
    return fit_section(request.account,pk,body(request).get('section'))

# How often one account may ask for its deck to be drawn (each field committed), ask how a drawing
# stands (a tab asks about twice a second while it waits) and fetch its slides (a strip of 60, then a page of 60).
RENDERS_PER_MINUTE=60
RENDER_POLLS_PER_MINUTE=240
SLIDE_IMAGES_PER_MINUTE=600

@api(('GET','POST'))
def draft_render(request,pk):
    """The deck as slide pictures, drawn in the editor lane and never here: POST asks for a version, GET says how it stands."""
    _require_deck_editor()
    from . import tasks
    if request.method=='POST':
        account_limit(request.account,'deck_renders',RENDERS_PER_MINUTE)
        status,task=tasks.request_render(request.account,pk,body(request).get('version'))
        return JsonResponse({'task_id':str(task.pk),'status':status},status=202)
    account_limit(request.account,'deck_render_polls',RENDER_POLLS_PER_MINUTE)
    version=request.GET.get('version')
    return tasks.render_state(request.account,pk,None if version is None else int(version))

@api()
def draft_slide(request,pk,key,thumb=False):
    """One slide's picture as stored, inline. Nothing is ever drawn for this request: a slide not ready is not found."""
    _require_deck_editor()
    account_limit(request.account,'deck_slide_images',SLIDE_IMAGES_PER_MINUTE)
    from .models import SlideRender
    render=SlideRender.objects.select_related('file','thumb').filter(draft_id=pk,draft__account=request.account,draft__expires_at__gt=timezone.now(),key=key).first()
    if not render:raise DomainError('not_found',404)
    try:response=download_asset(request,render.thumb if thumb else render.file)
    except DomainError:raise DomainError('not_found',404) from None
    response['Content-Disposition']='inline; filename="slide.png"'
    return response

# A picture action is a tap; each is followed about twice a second while it runs, and a sheet shows a slide's few pictures.
PHOTO_ACTIONS_PER_MINUTE=30
PHOTO_POLLS_PER_MINUTE=240
PICTURES_PER_MINUTE=300
DESIGNS_PER_MINUTE=30

@api(('POST',))
def draft_photos(request,pk):
    """A deck's pictures changed (deck_photos.py): `remove` now, the rest as a picture task followed at …/photos/{task}."""
    _require_deck_editor()
    account_limit(request.account,'deck_photos',PHOTO_ACTIONS_PER_MINUTE)
    from .deck_photos import request as ask
    task,draft=ask(request.account,pk,body(request))
    if draft is not None:return _with_editor_state(request.account,draft,draft_data(draft))
    return JsonResponse({'task_id':str(task.pk),'status':task.status},status=202)

@api()
def draft_photo_task(request,pk,task):
    """How a picture task stands. Once done its result names the draft's new version, which the web then reads."""
    _require_deck_editor()
    account_limit(request.account,'deck_photo_polls',PHOTO_POLLS_PER_MINUTE)
    from .deck_photos import task_state
    return task_state(request.account,pk,task)

@api()
def draft_picture(request,pk,asset):
    """One of the deck's own pictures, inline: what a slide wears or has on offer. Nothing is fetched or drawn for it."""
    _require_deck_editor()
    account_limit(request.account,'deck_pictures',PICTURES_PER_MINUTE)
    picture=FileAsset.objects.filter(pk=asset,account=request.account,metadata__kind='deck_photo',metadata__draft_id=str(pk)).first()
    if not picture or not GenerationDraft.objects.filter(pk=pk,account=request.account,expires_at__gt=timezone.now()).exists():raise DomainError('not_found',404)
    try:response=download_asset(request,picture)
    except DomainError:raise DomainError('not_found',404) from None
    response['Content-Disposition']='inline; filename="picture.jpg"'
    return response

@api(('POST',))
def draft_design(request,pk):
    """Another design for a drawn deck, as the Design sheet picks it: one save, a new version, nothing else moved."""
    _require_deck_editor()
    account_limit(request.account,'deck_designs',DESIGNS_PER_MINUTE)
    from .deck_photos import set_design
    d=set_design(request.account,pk,body(request))
    return _with_editor_state(request.account,d,draft_data(d))

# The Cover sheet reads its lines as it opens and saves them on "Remember", now and then.
COVER_LINES_PER_MINUTE=30

@api(('GET','POST','DELETE'))
def cover_lines(request):
    """The lines a customer keeps for their next decks' title slides (who made it, who checks it, class, school), with
    the language of the deck they come from and the Cover sheet row of each. Packed; Forget deletes them."""
    _require_deck_editor()
    account_limit(request.account,'cover_lines',COVER_LINES_PER_MINUTE)
    from . import cover_lines as kept
    if request.method=='POST':
        data=body(request)
        return kept.remember(request.account,data.get('lines'),data.get('locale'),data.get('roles'))
    if request.method=='DELETE':
        kept.forget(request.account)
    return kept.remembered(request.account)

# Asked after each field a customer finishes in an Uzbek deck that still has Cyrillic in it, not on every key.
LATIN_PER_MINUTE=60
LATIN_TEXTS,LATIN_CHARS=40,12000

@api(('POST',))
def latin(request):
    """Uzbek text in Latin letters, as the house writes it (o‘ g‘ with U+2018, ʼ U+02BC): a free preview, nothing saved."""
    _require_deck_editor()
    account_limit(request.account,'studio_latin',LATIN_PER_MINUTE)
    texts=body(request,limit=65536).get('texts')
    if (not isinstance(texts,list) or not 1<=len(texts)<=LATIN_TEXTS or any(not isinstance(text,str) for text in texts)
            or sum(map(len,texts))>LATIN_CHARS):raise DomainError('invalid_parameters')
    from .scripts import to_script
    out=[to_script(text,'uz') for text in texts]
    return {'texts':out,'changed':out!=texts}

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
# Saved form-filling templates an account may keep, on any plan that has them.
FORM_TEMPLATES=30

def definition_cap(account,kind):
    caps=plan_limits(account)
    if kind=='workflow':return caps['saved_workflows']
    if kind=='template':return caps['saved_teacher_templates']
    # Form templates follow the catalog like every other tool. This once named
    # Premium outright, so Free and Plus were held at none after the catalog gave
    # them the feature.
    return FORM_TEMPLATES if allowed(account,'editor.form_templates') else 0
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
    token_hash=hashlib.sha256(token.encode()).hexdigest()
    # Per link: whoever opens one mostly holds no cookie, and a session made for each would limit nothing and leave a row behind.
    count_request('shared',token_hash,30)
    s=ShareGrant.objects.select_related('artifact__file').filter(token_hash=token_hash,expires_at__gt=timezone.now(),revoked_at__isnull=True,artifact__role__in=('learner_material','public_preview')).first()
    from .privacy import may_share_artifact
    if not s or not may_share_artifact(s.artifact):raise DomainError('not_found',404)
    return download_asset(request,s.artifact.file)

def editor_row(e):
    """A draft in a list. Its marks are the customer's text, decrypted a row at a time, and a list has no use for them."""
    return {'id':str(e.id),'version':e.version,'file':asset_data(e.file),'pages':e.file.metadata.get('page_sizes',[]),'form_fields':e.file.metadata.get('form_fields',[]),'image_counts':e.file.metadata.get('image_counts',[]),'input_ids':e.input_ids,'limits':EDITOR_LIMITS,'updated_at':e.updated_at,'device':e.device}
def editor_data(e):
    return {**editor_row(e),'commands':stored_commands(e)}
def _file_to_open(account,fid):
    """A file that ran out says so, apart from one that was never this account's."""
    try:return owned_assets(account,[fid])[0]
    except DomainError as error:
        gone=FileAsset.objects.filter(account=account,id=fid,expires_at__lte=timezone.now()).first() if error.code=='file_unavailable' else None
        if gone:raise file_gone(gone) from None
        raise
def _refusal(a):
    """Why the editor cannot open a file, as the refusal says it, or None when it can."""
    if a.metadata.get('encrypted'):return 'password'
    if a.mime_type=='application/pdf':return None
    return 'pptx_upload' if a.metadata.get('kind')=='pptx' else 'not_pdf'
@api(('GET','POST'))
def editors(request):
    if request.method=='POST':
        data=body(request);fid=data.get('file_id',data.get('input_id'))
        a=_file_to_open(request.account,fid)
        reason=_refusal(a)
        if reason:raise DomainError('unsupported_file',params={'reason':reason})
        # One draft per file (editor_one_draft_per_file): opening it again comes back to the same marks.
        e=EditorDocument.objects.filter(account=request.account,file=a).first()
        if e:return JsonResponse(editor_data(e),status=200)
        try:
            with transaction.atomic():
                e=EditorDocument.objects.create(account=request.account,file=a,input_ids=[str(a.id)])
        except IntegrityError:
            # Two opens at once: the other made it, and both come back to it.
            return JsonResponse(editor_data(EditorDocument.objects.get(account=request.account,file=a)),status=200)
        return JsonResponse(editor_data(e),status=201)
    return {'results':[editor_row(e) for e in EditorDocument.objects.filter(account=request.account,file__expires_at__gt=timezone.now(),file__state='ready').select_related('file')]}
@api(('GET','PATCH','DELETE'))
def editor_detail(request,pk):
    with transaction.atomic():
        e=EditorDocument.objects.select_for_update().select_related('file').filter(account=request.account,id=pk).first()
        if not e:raise DomainError('not_found',404)
        if e.file.state!='ready' or e.file.expires_at<=timezone.now():raise file_gone(e.file)
        if request.method=='DELETE':e.delete();return {'deleted':True}
        if request.method=='PATCH':
            data=body(request,limit=131072,too_large='payload_too_large')
            commands=data.get('commands',[])
            if data.get('version')!=e.version:raise version_conflict(e,mine=len(commands) if isinstance(commands,list) else 0)
            if not isinstance(commands,list) or len(commands)>EDITOR_LIMITS['commands']:raise DomainError('invalid_parameters')
            device=data.get('device','')
            if not isinstance(device,str) or len(device)>40 or any(ord(c)<32 for c in device):raise DomainError('invalid_parameters')
            ids=data.get('input_ids',e.input_ids)
            if not ids or str(ids[0])!=str(e.file_id):raise DomainError('invalid_inputs')
            from apps.core.services import validate_inputs
            from .editor_policy import validate_commands_access
            assets=validate_inputs(request.account,'editor.visual',ids)
            if commands:commands=normalized_commands(commands,assets)
            validate_commands_access(request.account,commands)
            # Measured with the defaults filled in: this is what is stored, sent back and quoted.
            if payload_bytes(commands)>EDITOR_LIMITS['bytes']:raise DomainError('payload_too_large',413)
            store_commands(e,commands);e.input_ids=ids;e.updated_at=timezone.now();e.device=device
            e.save(update_fields=[*COMMAND_COLUMNS,'input_ids','updated_at','device'])
        return editor_data(e)
# The Black out sheet asks once its boxes settle, and Review before a send; GET follows a check that is running.
BLACKOUT_CHECKS_PER_MINUTE=20
BLACKOUT_POLLS_PER_MINUTE=90
@api(('GET','POST'))
def editor_blackout(request,pk):
    """Which pages with a black-out box keep their words in a send, and why each other one becomes a picture (editor_blackout.py). POST asks for a check where a page is not known yet."""
    from .editor_blackout import ask,state
    if request.method=='POST':
        account_limit(request.account,'editor_blackout',BLACKOUT_CHECKS_PER_MINUTE)
        answer=ask(request.account,pk)
    else:
        account_limit(request.account,'editor_blackout_polls',BLACKOUT_POLLS_PER_MINUTE)
        answer=state(request.account,pk)
    return JsonResponse(answer,status=202 if answer['status'] in ('queued','running') else 200)
@api(('POST',))
def editor_quote(request,pk):
    e=EditorDocument.objects.filter(account=request.account,id=pk).first()
    if not e:raise DomainError('not_found',404)
    data=body(request)
    # `deliver` is a send of the stored draft. Without it this is today's web, whose quote and job carry the marks, until it goes.
    if 'deliver' in data:
        throttle(request,'quotes',60)
        q,summary=quote_draft(request.account,pk,data)
        return JsonResponse({**quote_data(q),'summary':summary},status=201)
    if data.get('version')!=e.version:raise version_conflict(e)
    q=create_quote(request.account,'editor.visual',e.input_ids,{'commands':stored_commands(e),'accept_rasterization':data.get('accept_rasterization',False)})
    return JsonResponse(quote_data(q),status=201)
