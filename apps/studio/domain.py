"""Versioned authoring, encrypted drafts and role-aware generated artifacts."""
import hashlib
from copy import deepcopy
import json
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from apps.core.errors import DomainError
from apps.core.models import Quote
from apps.core.policy import FEATURES, POLICY_VERSION, plan_limits, SEED
from apps.core.services import owned_assets
from apps.core import storage
from operations.integrations import cipher, ai_config
from .models import GenerationDraft

# Two services: a document, or slides. Everything the retired features encoded
# — audience, tone, subject, question count, structure — is said in the
# description instead, and the description is already the prompt. The retired
# ids stay in FEATURES so drafts and jobs made before this still resolve their
# names; they just cannot be authored any more.
DOCUMENT='ai.pdf_topic'
SLIDES='ai.pptx'
GENERATION_IDS={DOCUMENT,SLIDES}
# Server-owned fields a client may never send.
READONLY_FIELDS={'_transcription','transcription_ready','transcription_reviewed','_source_seed','revision'}

def pack(value): return cipher().encrypt(json.dumps(value,ensure_ascii=False).encode())
def unpack(value): return json.loads(cipher().decrypt(bytes(value)))
def allowed(account,fid):
    return fid in FEATURES and FEATURES[fid]['plans'][account.plan] not in ('not_included','unavailable','none','excluded')
def ai_documents_today(account,now=None):
    """AI documents this account has started today (UTC), as the daily task cap counts days.

    An outline is a step towards a document, not one; a job that failed,
    was cancelled or expired produced nothing and is not counted. Nor is a
    change to a document already made: free customers spent their day
    correcting what came back wrong, and a change still costs its credits.
    """
    from apps.core.models import Job
    today=(now or timezone.now()).replace(hour=0,minute=0,second=0,microsecond=0)
    started=Job.objects.filter(account=account,feature_id__in=GENERATION_IDS,created_at__gte=today).exclude(status__in=('failed','canceled','expired','no_op')).values_list('parameters',flat=True)
    return sum(1 for parameters in started if (parameters or {}).get('stage')!='outline' and not (parameters or {}).get('revision'))

def require_daily_ai(account):
    """Free accounts make a few AI documents a day; paid plans have no daily limit."""
    limit=plan_limits(account).get('daily_ai_documents')
    if limit is None:return
    if ai_documents_today(account)>=limit:
        tomorrow=timezone.now().replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
        raise DomainError('daily_ai_limit',429,{'limit':limit,'resets_at':tomorrow.isoformat()})

def require(account,fid):
    if not settings.ENABLE_BETA_TOOLS or fid not in GENERATION_IDS: raise DomainError('feature_unavailable',409)
    if not allowed(account,fid): raise DomainError('feature_not_in_plan',403)

def limits(account):
    seed=plan_limits(account)
    # Source text has to fit the request budget alongside the document itself, so
    # it is half of it rather than three times it. Promising more source than a
    # call can carry only moves the refusal later.
    return {'sections':seed['max_generated_pdf_pages'], 'slides':seed['max_generated_slides'], 'questions':{'free':10,'plus':50,'premium':150}.get(account.plan,10), 'source_chars':seed['max_ai_input_tokens']//2}

def validate_content(account,content,output_format='pdf'):
    """Bring a model response inside the plan, trimming rather than refusing.

    The page count was clamped to the plan before the model was ever asked, so
    anything over it here is the model overrunning its brief. That is not the
    customer's mistake and it costs them nothing: it is cut back to what was
    quoted. Only content that is unusable — the wrong shape, or empty — is
    refused.
    """
    if not isinstance(content,dict): raise DomainError('invalid_parameters')
    caps=limits(account)
    title=str(content.get('title','Document'))[:160]
    sections=content.get('sections',[])
    max_sections=caps['slides'] if output_format=='pptx' else caps['sections']
    if not isinstance(sections,list): raise DomainError('invalid_parameters')
    if not sections: raise DomainError('content_required')
    from . import pages as paging
    body_cap=paging.max_section_chars(output_format)
    clean=[]
    for i,s in enumerate(sections[:max_sections]):
        if not isinstance(s,dict): raise DomainError('invalid_parameters')
        clean.append({'id':str(s.get('id',f's{i+1}'))[:40],'heading':str(s.get('heading',s.get('title','')))[:160],'body':str(s.get('body',''))[:body_cap],'notes':str(s.get('notes',''))[:2000]})
        # A slide also carries the layout it chose and what fills it. A document
        # section does only when it is more than text (a table, a list, a photo);
        # a plain one keeps exactly its four keys.
        try:
            if output_format=='pptx':
                from .layouts import clean_slide_fields
                clean[-1].update(clean_slide_fields(s))
            else:
                from .doc_designs import clean_fields
                clean[-1].update(clean_fields(s))
        except ValueError:raise DomainError('invalid_parameters') from None
    questions=content.get('questions',[])
    if not isinstance(questions,list): raise DomainError('invalid_parameters')
    questions=questions[:caps['questions']]
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

def ensure_selected_preservation(data,normalized):
    """Reject normalization that would silently alter an untouched selection.

    Stored content was valid when authored, but an account downgrade or changed
    plan limits can make today's normalizer trim it. A scoped revision must keep
    the whole existing document; needing a smaller plan allowance is a refusal,
    never permission to discard the other pages or questions.
    """
    selected=data.get('revision',{}).get('selected_section_ids')
    if not selected:return
    original=data['content']
    if ([s['id'] for s in normalized['sections']]!=[s['id'] for s in original['sections']]
            or normalized['title']!=original['title']
            or normalized['questions']!=original.get('questions',[])
            or [s for s in normalized['sections'] if s['id'] not in selected]
               !=[s for s in original['sections'] if s['id'] not in selected]):
        raise DomainError('generation_limit')

def draft_data(d):
    data=unpack(d.encrypted_data)
    data.pop('_source_seed',None)
    if data.get('revision'):
        data['revision']={key:value for key,value in data['revision'].items() if key!='base_content'}
    return {'id':str(d.id),'feature_id':d.feature_id,'version':d.version,'provider_mode':d.provider_mode,'expires_at':d.expires_at,**data,'outline':[{'id':s['id'],'title':s['heading'],'body':s['body']} for s in data['content']['sections']]}

def source_excerpts(account,ids):
    if not ids:return []
    assets=owned_assets(account,ids)
    # How many files a document may be built from follows the plan rather than
    # being the same five for everyone; total pages is capped separately.
    caps=plan_limits(account)
    if len(assets)>caps.get('max_ai_source_files',5) or sum(a.page_count for a in assets)>caps['max_ai_source_pages']:raise DomainError('generation_limit')
    # Extraction is performed in the bounded parser child, not inside the HTTP worker.
    result=[]
    for a in assets:
        if a.mime_type!='application/pdf' or a.metadata.get('encrypted'):raise DomainError('unsupported_file')
        from .extraction import extract_pages
        for page,text in extract_pages(storage.local(a.object_key)):
            result.append({'asset_id':str(a.id),'page':page,'text':text[:12000]})
    if sum(len(v['text']) for v in result)>limits(account)['source_chars']:raise DomainError('generation_limit')
    return result

def revision_source(account,identifier):
    """The document a change request is being applied to."""
    import uuid as _uuid
    try:identifier=_uuid.UUID(str(identifier))
    except (ValueError,TypeError):raise DomainError('invalid_parameters') from None
    source=GenerationDraft.objects.filter(account=account,id=identifier,expires_at__gt=timezone.now()).first()
    if not source:raise DomainError('not_found',404)
    original=unpack(source.encrypted_data)
    # A slide can be finished with nothing in its body — a stats slide is all
    # items — so items count as content too.
    if not any((section.get('body') or '').strip() or section.get('items') for section in original['content']['sections']):
        raise DomainError('revision_not_ready')
    return source,original


def _image_cap(account,fid):
    """How many photo layouts a deck may ask for: the plan's allowance, when photos are on.

    Set here rather than taken from the client, the same way the page and
    question counts are.
    """
    if fid not in GENERATION_IDS:return 0
    from operations.integrations import pixabay_config
    if not pixabay_config()['ready']:return 0
    return int(plan_limits(account).get('max_deck_images',0) or 0)

def _deck_style(fid,brief):
    """A deck's look, read out of the description like its slide count.

    There is no colour field: "a dark deck in navy" is the brief saying so. A
    design picked on the review screen (`options.deck_design`) replaces all of
    this in `_prepare_draft`. Account branding still overrides the accent later, because
    a brand colour is a fact about the customer rather than a preference. A
    document has no deck theme; it takes only the colour.
    """
    from . import pages as paging
    colours=paging.requested_colours(brief)
    # A document takes a colour it is asked for too, over its design's own.
    if fid!=SLIDES:
        return {'accent':colours[0],'accent_fixed':True} if colours else {}
    # Only what the brief actually names is fixed; the rest is the design the
    # model chooses (apps/studio/deck_designs.py). A second colour named
    # ("ko'k, yashil va qizil") becomes the deck's second colour.
    style={}
    theme=paging.requested_theme(brief)
    if theme:style['deck_theme']=theme
    if colours:style.update(accent=colours[0],accent_fixed=True)
    if len(colours)>1:style['secondary']=colours[1]
    return style

def _prepare_draft(account,data,revision_base=None):
    if set(data)&READONLY_FIELDS:raise DomainError('invalid_parameters')
    fid=data.get('feature_id',DOCUMENT);require(account,fid)
    # The service decides the format; the client does not get a say. A document
    # is a PDF and a deck is a PowerPoint. The value is still validated so a
    # malformed one is refused rather than silently ignored, and the forcing
    # happens after the revision block below, which inherits the original's
    # format — a change request against a draft made before slides became
    # PowerPoint would otherwise come back as a PDF.
    if data.get('output_format') not in (None,'pdf','pptx'):raise DomainError('invalid_parameters')
    locale=data.get('output_locale',account.locale)
    if locale not in ('en','uz','ru'):raise DomainError('invalid_locale')
    title=str(data.get('title',data.get('topic','Untitled document'))).strip()[:160] or 'Untitled document'
    text=data.get('source_text',data.get('text',''))
    prompt=data.get('prompt',title)
    if not isinstance(text,str) or not isinstance(prompt,str):raise DomainError('invalid_parameters')
    if len(text)+len(prompt)>limits(account)['source_chars']:raise DomainError('generation_limit')
    ids=data.get('source_ids',data.get('input_ids',[]))
    excerpts=source_excerpts(account,ids)
    if len(text)+len(prompt)+sum(len(s['text']) for s in excerpts)>limits(account)['source_chars']:raise DomainError('generation_limit')
    options=data.get('options',data.get('parameters',{}))
    if not isinstance(options,dict) or len(json.dumps(options))>4000 or set(options)&READONLY_FIELDS:raise DomainError('invalid_parameters')
    # A change request inherits the document it applies to: same service, same
    # format, same sources. Only what the customer asks to change may change.
    revising=options.get('revise_draft_id')
    saved_revision=(revision_base or {}).get('revision',{})
    if saved_revision.get('selected_section_ids') and str(revising)!=saved_revision.get('source_draft_id'):
        raise DomainError('invalid_parameters')
    original=None
    selection=[]
    source_version=None
    if not revising and {'revise_section_ids','revise_base_version'} & set(options):raise DomainError('invalid_parameters')
    if revising:
        saved=(revision_base or {}).get('revision',{})
        # Once created, a selected revision owns an immutable snapshot. Saving its
        # wording cannot silently pick up later edits to the original document.
        if saved.get('selected_section_ids') and str(revising)==saved.get('source_draft_id'):
            original={**revision_base,'content':deepcopy(saved['base_content'])}
            source_version=saved['base_version']
        else:
            source,original=revision_source(account,revising)
            fid=source.feature_id
            source_version=source.version
        require(account,fid)
        from .revisions import selected_ids
        selection=selected_ids(options,original['content'],source_version)
        if saved.get('selected_section_ids') and selection!=saved['selected_section_ids']:raise DomainError('invalid_parameters')
        # A change keeps the document's language unless one was chosen for it
        # on the review screen.
        locale=locale if options.get('locale_chosen') is True else original['output_locale']
        ids=original['source_ids'];excerpts=original['excerpts']
        title=original['title'] if revision_base is None else title
        text=original.get('source_text','')
        if not prompt.strip():raise DomainError('prompt_required')
        # Revisions inherit the confirmed look as well as the document. A typo
        # request has no template/theme instructions and must not reset either.
        inherited=(revision_base or original).get('options',{})
        for field,default in (('template_id','clean'),('branding',{})):
            previous=inherited.get(field,default)
            if selection and field in options and (options[field] or default)!=(previous or default):
                raise DomainError('invalid_parameters')
            if field not in options and (field in inherited or field=='template_id'):
                options={**options,field:deepcopy(previous)}
    fmt='pptx' if fid==SLIDES else 'pdf'
    # Length and question count are read out of the description rather than
    # asked for separately: one section is one page, and questions are priced,
    # so they appear only when the description asks for them. `requested_pages`
    # is kept beside the resolved count so a clamp can be shown, not hidden.
    from . import pages as paging
    brief=prompt if original is not None else f'{prompt}\n{text}'
    # The language the description asks for beats the account's, and one chosen
    # on the review screen beats both. A change request names a language only in
    # so many words ("ingliz tilida tayyorla"): it may be written in any language
    # about a document that stays in its own.
    if options.get('locale_chosen') is not True:
        named=paging.requested_locale(prompt,explicit_only=original is not None)
        if named:locale=named
    # Uzbek is written in the alphabet the description was written in; a change
    # keeps the document's.
    if original is not None:
        uz_script=(revision_base or original).get('options',{}).get('uz_script','latn')
    else:
        uz_script=paging.requested_script(prompt) if locale=='uz' else 'latn'
    # A count chosen on the review screen beats the one read from the
    # description: it is how a misread count gets put right before paying.
    chosen=options.get('pages')
    # So does a design chosen there: "Auto" leaves it to the model, as before.
    picked=options.get('deck_design')
    if picked is not None:
        from .deck_designs import DESIGNS,current
        # A draft saved with a design since retired keeps working, as its replacement.
        picked=current(picked)
        if fid!=SLIDES or picked!='auto' and picked not in DESIGNS:raise DomainError('invalid_parameters')
        options={**options,'deck_design':picked}
    if chosen is not None:
        if type(chosen) is not int or not 1<=chosen<=200:raise DomainError('invalid_parameters')
        length,asked=min(chosen,paging.ceiling(account,fmt)),chosen
    else:
        length,asked=paging.resolve(account,brief,fmt)
        # A change keeps the document's length unless the request names a new
        # total. A total of one is not taken from a change request: "har 1ta
        # slaydga rasm" (a picture on every slide) once made a nine-slide deck one.
        if original is not None and (asked is None or asked<2):
            asked=None;length=len(original['content']['sections'])
    if selection:
        if asked is not None and asked!=len(original['content']['sections']):raise DomainError('invalid_parameters')
        length=len(original['content']['sections'])
    # Local authoring has no model to write the pages, so an unasked-for default
    # would render as blank ones. Follow the material that was actually given.
    if original is None and asked is None and ai_config()['mode']=='local_fixture':
        supplied=len([p for p in (text or '\n\n'.join(x['text'] for x in excerpts)).split('\n\n') if p.strip()])
        if supplied:length=min(supplied,paging.ceiling(account,fmt))
    question_count=min(paging.requested_questions(brief),limits(account)['questions'])
    # A deck's questions go on slides of their own at the end, five to a slide,
    # and those slides are part of the count: "10 slides, 5 questions at the
    # end" is ten slides, not fifteen. `length` is the whole deck; the sections
    # are the slides the model writes.
    question_slides=0
    if fid==SLIDES:
        if original is None:question_slides=paging.question_slides(question_count)
        else:question_slides=int((revision_base or original).get('options',{}).get('question_slides',0) or 0)
    if original is not None and (asked is None or selection):
        sections_count=length
    else:
        question_slides=min(question_slides,max(0,length-1))
        sections_count=length-question_slides
    length=sections_count+question_slides
    # A document is plain prose in black and white unless its description asks
    # for more: pictures, tables or lists (layouts), or a look or colours (design).
    wants={}
    if fid!=SLIDES:
        from . import doc_designs
        wants={'wants_layouts':doc_designs.asks_for_layouts(brief),'wants_design':doc_designs.asks_for_design(brief)}
        if original is not None:
            # A change request keeps what the document already had.
            before=(revision_base or original).get('options',{})
            wants={key:value or bool(before.get(key)) for key,value in wants.items()}
    image_cap=_image_cap(account,fid)
    # A deck whose description asks for pictures gets as many as it names, or
    # one a slide ("har bir slaydda rasm"), within what the plan adds; the review
    # says so when the plan adds fewer.
    images_wanted=0
    if fid==SLIDES and original is None:
        from .doc_designs import asks_for_images
        if asks_for_images(brief):images_wanted=paging.requested_images(brief) or sections_count
    if fid!=SLIDES and not doc_designs.asks_for_images(brief) and not (original is not None and (revision_base or original).get('options',{}).get('image_cap')):
        image_cap=0
    options={**{k:v for k,v in options.items() if k not in ('wants_layouts','wants_design')},
             'question_count':question_count,'length':length,'requested_pages':asked,'question_slides':question_slides,
             'uz_script':uz_script,**({'images_wanted':images_wanted} if images_wanted else {}),
             'image_cap':image_cap,**wants}
    template_id=options.get('template_id','clean')
    from .templates import style_for
    # Density is fixed at the spacing the page-fill targets were measured
    # against; a page that must be full has nothing left to choose.
    density={}
    template_style=style_for(account,template_id)
    if template_style is None:
        from .models import SavedDefinition
        import re
        template=SavedDefinition.objects.filter(account=account,id=template_id,kind='template').first()
        if not template:raise DomainError('not_found',404)
        accent=template.definition.get('content',{}).get('style',{}).get('accent','#255e49')
        if not isinstance(accent,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',accent):raise DomainError('invalid_parameters')
        # A customer's own saved template carries a colour they chose.
        template_style={'accent':accent,'accent_fixed':True}
    style={**template_style,**density}
    if original is not None:
        inherited=(revision_base or original).get('options',{})
        previous_style=inherited.get('template_style',{})
        if template_id==inherited.get('template_id','clean'):
            # The saved style is server-authored. Still resolve the template
            # above to recheck its ownership and current plan permission.
            style=deepcopy(previous_style or style)
        elif fid==SLIDES:
            for key in ('deck_theme','deck_design'):
                if previous_style.get(key):style[key]=previous_style[key]
        if not selection and fid==SLIDES:
            theme=paging.requested_theme(brief)
            accent=paging.requested_accent(brief)
            if theme:style['deck_theme']=theme
            if accent:style.update(accent=accent,accent_fixed=True)
        # A selected-page revision never changes the whole document's style.
    else:
        style.update(_deck_style(fid,brief))
    if picked and picked!='auto':
        # A design picked on the review screen beats whatever look the
        # description implies: its colours and its dark or bold are dropped,
        # keeping only a saved template's own colour. Branding still wins below.
        style={**{key:value for key,value in style.items() if key not in ('deck_theme','secondary','accent','accent_fixed')},
               **{key:template_style[key] for key in ('accent','accent_fixed') if key in template_style},
               'deck_design':picked}
    options['template_style']=style
    from .branding import prepare_branding
    options=prepare_branding(account,fid,options)
    options.pop('adaptive_context',None)
    cfg=ai_config()
    if cfg['mode']=='disabled' or cfg['mode']=='openai' and (not cfg['api_key'] or not cfg['model']):raise DomainError('provider_not_configured',409)
    if not prompt.strip() and not text.strip() and not excerpts:raise DomainError('prompt_required')
    # Creation is uncharged authoring. Provider calls happen only after an accepted quote.
    if original is not None:
        # The model is handed the document as it stands so it can return it
        # with only the requested changes applied.
        sections=[dict(section) for section in original['content']['sections'][:sections_count]]
        while len(sections)<sections_count:
            sections.append({'id':f's{len(sections)+1}','heading':'','body':'','notes':''})
        draft_content={**original['content'],'sections':sections}
    else:
        chunks=[p.strip() for p in (text or '\n\n'.join(x['text'] for x in excerpts)).split('\n\n') if p.strip()]
        # No headings. They used to be seeded with a fixed Overview / Key ideas /
        # Practice / Review cycle, which handed every document a practice section
        # and a review section nobody asked for — and repeated the four of them
        # every four pages. The description is the brief, so the structure comes
        # from the description.
        sections=[{'id':f's{i+1}','heading':'', 'body':('\n\n'.join(chunks[i:]) if i==sections_count-1 else chunks[i]) if i<len(chunks) else '', 'notes':''} for i in range(sections_count)]
        draft_content={'title':title,'sections':sections,'questions':options.get('questions',[]),'citations':[{'asset_id':x['asset_id'],'page':x['page']} for x in excerpts]}
    content=validate_content(account,draft_content,fmt)
    if selection:
        ensure_selected_preservation({'content':draft_content,'revision':{'selected_section_ids':selection}},content)
    payload={'title':title,'prompt':prompt,'source_text':text,'source_ids':ids,'excerpts':excerpts,'output_locale':locale,'output_format':fmt,'options':options,'content':content}
    if original is not None:
        payload['revision']={'request':prompt,'source_draft_id':str(revising),
                             'original_prompt':original.get('revision',{}).get('original_prompt',original.get('prompt',''))}
        if selection:
            payload['revision'].update(selected_section_ids=selection,base_version=source_version,
                                       base_content=deepcopy(original['content']))
    else:
        from .revisions import source_seed
        seed=source_seed(payload)
        if seed:payload['_source_seed']=seed
    if len(payload['excerpts'])>plan_limits(account)['max_ai_source_pages']:raise DomainError('generation_limit')
    if payload['source_ids']:owned_assets(account,payload['source_ids'])
    if cfg['mode']=='openai':
        enforce_budget(cfg,payload,fid,plan_limits(account)['max_ai_input_tokens'])
    return fid,cfg,payload

def enforce_budget(config,payload,feature_id,token_limit):
    from .provider import enforce_input_budget
    return enforce_input_budget(config,payload,feature_id,token_limit)

def create_draft(account,data):
    fid,cfg,payload=_prepare_draft(account,data)
    return GenerationDraft.objects.create(account=account,feature_id=fid,encrypted_data=pack(payload),provider_mode=cfg['mode'],expires_at=timezone.now()+timedelta(hours=24))

def draft_jobs(account,draft_id,statuses):
    """Whether a job in one of `statuses` was submitted for a quote of this draft."""
    from apps.core.models import Job
    return Job.objects.filter(account=account,status__in=statuses,
                              quote__parameters__generation_draft_id=str(draft_id)).exists()

@transaction.atomic
def update_draft(account,draft_id,data):
    d=GenerationDraft.objects.select_for_update().filter(account=account,id=draft_id,expires_at__gt=timezone.now()).first()
    if not d:raise DomainError('not_found',404)
    # A queued job checks, when it starts, that its draft is still the one it
    # was quoted on (validate_generation_quote). Changing the draft before then
    # — the review's count or language buttons, the deck setup screen, the web
    # editor — would fail it. A running job has passed that check and works
    # from its own snapshot, so edits while it runs stay allowed
    # (tests/test_studio_adversarial.py).
    if draft_jobs(account,d.id,('queued',)):raise DomainError('generation_running',409)
    if data.get('version')!=d.version:raise DomainError('version_conflict',409)
    original=unpack(d.encrypted_data)
    allowed_keys={'version','title','prompt','source_text','source_ids','output_locale','output_format','options','content','outline'}
    if set(data)-allowed_keys:raise DomainError('invalid_parameters')
    fields={key:original[key] for key in ('title','prompt','source_text','source_ids','output_locale','output_format','options')}
    fields.update({key:value for key,value in data.items() if key in fields})
    _,cfg,payload=_prepare_draft(account,{'feature_id':d.feature_id,**fields},revision_base=original)
    if cfg['mode']!=d.provider_mode:raise DomainError('provider_changed',409)
    # The page count lives in the description, so a reworded brief rebuilds the
    # outline the same way a changed source does.
    rebuild=any(key in data and data[key]!=original.get(key) for key in ('prompt','source_text','source_ids','output_format'))
    # So does a count chosen on the review screen.
    rebuild=rebuild or payload['options'].get('length')!=original.get('options',{}).get('length')
    content=data.get('content',payload['content'] if rebuild and not original.get('revision',{}).get('selected_section_ids') else original['content'])
    if 'outline' in data:
        outline=data['outline']
        if not isinstance(outline,list) or any(not isinstance(s,dict) for s in outline):raise DomainError('invalid_parameters')
        slide_keys=('layout','items','columns','image_query')
        content={**content,'sections':[{'id':s.get('id',str(i)),'heading':s.get('title',''),'body':s.get('body',''),'notes':s.get('notes',''),
                                         **{key:s[key] for key in slide_keys if key in s}} for i,s in enumerate(outline)]}
    if 'title' in data and isinstance(content,dict):content={**content,'title':payload['title']}
    payload['content']=validate_content(account,content,payload['output_format'])
    payload['title']=payload['content']['title']
    # Only server-authored, untouched source copies can be deduplicated. Sending
    # content/outline is an explicit author edit, even if its text happens to match.
    if 'content' in data or 'outline' in data:
        payload.pop('_source_seed',None)
    elif not rebuild:
        payload.pop('_source_seed',None)
        if original.get('_source_seed'):payload['_source_seed']=original['_source_seed']
    if payload.get('revision',{}).get('selected_section_ids'):
        # Selected revisions may edit content, but structural changes need the
        # whole-document flow so selected identities cannot silently disappear.
        base=payload['revision']['base_content']
        if [s['id'] for s in payload['content']['sections']]!=[s['id'] for s in base['sections']]:
            raise DomainError('invalid_parameters')
    # An edited outline is the page count now, so keep them in step.
    payload['options']={**payload['options'],'length':len(payload['content']['sections'])+int(payload['options'].get('question_slides',0) or 0)}
    if cfg['mode']=='openai':
        enforce_budget(cfg,payload,d.feature_id,plan_limits(account)['max_ai_input_tokens'])
    d.encrypted_data=pack(payload);d.version+=1;d.save(update_fields=['encrypted_data','version'])
    return d

def generation_quote(account,draft_id,version):
    d=GenerationDraft.objects.filter(account=account,id=draft_id,expires_at__gt=timezone.now()).first()
    if not d:raise DomainError('not_found',404)
    require(account,d.feature_id)
    from apps.core.channel_gate import require as require_channels
    require_channels(account)
    if version!=d.version:raise DomainError('version_conflict',409)
    data=unpack(d.encrypted_data)
    # Said before the customer reviews the cost, not after they confirm it.
    if not data.get('revision'):require_daily_ai(account)
    cfg=ai_config()
    if cfg['mode']!=d.provider_mode:raise DomainError('provider_changed',409)
    # Sandbox is deterministic authoring; it never charges AI credits or pretends to call a model.
    tariff=SEED['tariff_v0_staging'];caps=limits(account)
    question_cap=max(len(data['content']['questions']),int(data['options'].get('question_count',0)))
    if not 0<=question_cap<=caps['questions']:raise DomainError('generation_limit')
    # Pages are now an explicit, user-chosen number rather than a soft hint, so
    # the price follows what was asked for instead of the plan's ceiling. One
    # page of headroom is reserved because a section written to fill its page
    # can spill onto the next; settlement consumes only what was produced, so
    # the headroom costs nothing unless it is used.
    output_cap=len(data['content']['sections'])+int(data['options'].get('question_slides',0) or 0)+1
    output_units=output_cap*tariff['pptx_output_credits_per_slide' if data['output_format']=='pptx' else 'pdf_output_credits_per_started_page']
    from .metering import generation_credits
    credits=0 if d.provider_mode=='local_fixture' else generation_credits(d.feature_id,len(data['excerpts']),question_cap,output_units,tariff)
    if cfg['mode']=='openai':
        enforce_budget(cfg,data,d.feature_id,plan_limits(account)['max_ai_input_tokens'])
    snapshot=hashlib.sha256(bytes(d.encrypted_data)).hexdigest()
    from .branding import generation_inputs
    input_ids=generation_inputs(data)
    # A long document is written in several provider calls and needs longer than
    # the default lease to finish them. Rendering and settlement are on top.
    from .provider import call_budget
    lease_seconds=call_budget(len(data['content']['sections']))+240
    if data['output_format']=='pptx':
        from .photos import BUDGET_SECONDS
        lease_seconds+=BUDGET_SECONDS
    return Quote.objects.create(account=account,feature_id=d.feature_id,input_ids=input_ids,input_fingerprints=[{'id':str(a.id),'sha256':a.sha256} for a in owned_assets(account,input_ids)] if input_ids else [],parameters={'generation_draft_id':str(d.id),'draft_version':d.version,'snapshot':snapshot,**({'revision':True} if data.get('revision') else {})},meters={'file_tasks':0,'file_page_units':0,'ai_credits':credits},policy={'plan':account.plan,'version':POLICY_VERSION,'tariff_version':'generation-draft-staging-v1','limits':plan_limits(account),'provider_mode':d.provider_mode,'provider_model':cfg['model'],'provider_image_model':cfg.get('image_model',''),'generation_bounds':{'question_cap':question_cap,'output_pages':output_cap,'key_pages':caps['sections'],'input_tokens':plan_limits(account)['max_ai_input_tokens'],'tariff':dict(tariff)},'lease_seconds':lease_seconds},expires_at=timezone.now()+timedelta(minutes=10))

def validate_generation_quote(account,quote):
    require(account,quote.feature_id)
    d=GenerationDraft.objects.filter(id=quote.parameters.get('generation_draft_id'),account=account,expires_at__gt=timezone.now()).first()
    if not d or d.version!=quote.parameters.get('draft_version') or hashlib.sha256(bytes(d.encrypted_data)).hexdigest()!=quote.parameters.get('snapshot'):raise DomainError('version_conflict',409)
    config=ai_config()
    if config['mode']!=d.provider_mode or quote.policy.get('provider_model','')!=config['model']:raise DomainError('provider_changed',409)
    return owned_assets(account,quote.input_ids) if quote.input_ids else []
