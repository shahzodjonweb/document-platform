"""Export the versioned public JSON contract independently from staff routes."""
import hashlib
import json
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand

S={'type':'string'}
I={'type':'integer','minimum':0}
B={'type':'boolean'}
UUID={'type':'string','format':'uuid'}
DT={'type':'string','format':'date-time'}
def obj(properties,required=()): return {'type':'object','properties':properties,'required':list(required)}
def arr(items): return {'type':'array','items':items}
def ref(name): return {'$ref':f'#/components/schemas/{name}'}
def _slide_fields():
    from apps.studio.layouts import AUTO, LAYOUT_IDS
    return {'layout':{'type':'string','enum':[AUTO,*LAYOUT_IDS]},
            'items':arr(obj({'label':{'type':'string'},'text':{'type':'string'},'value':{'type':'string'}})),
            'columns':arr({'type':'string'}),'image_query':{'type':'string'}}

def extend_schema(models, endpoint, paths):
    """Public studio and commerce schemas; staff configuration stays excluded."""
    from operations.integrations import EDITOR_FLAGS
    O={'type':'object'}
    SLIDE_FIELDS=_slide_fields()
    nullable_string={'type':['string','null']}
    version=obj({'version':I},['version'])
    deleted=obj({'deleted':B},['deleted'])
    models.update({
        # Slides also carry the layout they chose and what fills it. Optional:
        # a document section never has them, and an older deck has `auto`.
        'GenerationSection':obj({'id':S,'heading':S,'body':S,'notes':S,**SLIDE_FIELDS},['id','heading','body']),
        'GenerationQuestion':obj({'id':S,'stem':S,'options':arr(S),'answer':S,'explanation':S,'topic':S,'marks':I},['id','stem','answer','marks']),
        'GenerationContent':obj({'title':S,'sections':arr(ref('GenerationSection')),'questions':arr(ref('GenerationQuestion')),'citations':arr(obj({'asset_id':UUID,'page':I}))},['title','sections','questions']),
        'GenerationDraft':obj({'id':UUID,'feature_id':S,'version':I,'provider_mode':S,'expires_at':DT,'title':S,'prompt':S,'source_text':S,'source_ids':arr(UUID),'excerpts':arr(obj({'asset_id':UUID,'page':I,'text':S})),'cv_unread':{**arr(obj({'asset_id':UUID,'pages':I,'whole':B},['asset_id','pages'])),'description':'A CV made from files (`ai.cv`): each file not read whole, with how many of its pages were left out; `whole` when none of it was read. Absent when everything was read.'},'cv_facts':{**obj({'given':arr(S),'missing':arr(S),'optional_missing':arr(S)},['given','missing','optional_missing']),'description':'A new CV (`ai.cv`): which of its facts the description and files give. `given` lists the facts found, `missing` the required ones not found (`name`, `contact`, `background`) and `optional_missing` the optional ones not found, each in the order of the feature\'s `cv_facts`. A draft made after the customer insisted can still have `missing` facts. Absent on a change.'},'output_locale':{'enum':['en','uz','ru']},'output_format':{'enum':['pdf','pptx']},'options':O,'content':ref('GenerationContent'),'outline':arr(obj({'id':S,'title':S,'body':S}))},['id','feature_id','version','provider_mode','expires_at','title','output_locale','output_format','content']),
        'SavedDefinition':obj({'id':UUID,'name':S,'kind':{'enum':['workflow','template','form']},'version':I,'content':O,'output_locale':S,'steps':arr(ref('WorkflowStep'))},['id','name','kind','version']),
        'WorkflowStep':obj({'feature_id':S,'parameters':O},['feature_id']),
        'WorkflowQuote':obj({'workflow_id':UUID,'version':I,'input_ids':arr(UUID),'steps':arr(ref('WorkflowStep')),'confirmation_required':B,'confirmation_token':S,'expires_at':DT,'limitations':arr(S)},['workflow_id','version','input_ids','steps','confirmation_required','confirmation_token','expires_at','limitations']),
        'WorkflowRun':obj({'id':UUID,'status':S,'jobs':arr(ref('Job'))},['id','status','jobs']),
        'PracticeResult':obj({'score':I,'max_score':I,'questions':arr(obj({'question_id':S,'correct':B,'expected_answer':S,'explanation':S,'marks':I})),'weak_topics':arr(S),'grading':S},['score','max_score','questions','weak_topics','grading']),
        'EducationProject':obj({'id':UUID,'title':S,'version':I,'expires_at':DT,'created_at':DT,'attempts':arr(ref('PracticeResult')),'content':ref('GenerationContent')},['id','title','version','expires_at','attempts']),
        'ShareGrant':obj({'id':UUID,'artifact_id':UUID,'url':S,'expires_at':DT,'revoked':B},['id','expires_at']),
        'EditorDocument':obj({'id':UUID,'version':I,'file':ref('Asset'),'pages':arr(obj({'width':{'type':'number'},'height':{'type':'number'}},['width','height'])),'form_fields':arr(obj({'name':S,'type':S},['name','type'])),'image_counts':arr(I),'commands':arr(ref('EditorCommand')),'input_ids':arr(UUID),'limits':{**obj({'commands':I,'bytes':I},['commands','bytes']),'description':'The most a draft holds: `commands` changes, measuring `bytes` as UTF-8 compact JSON with the defaults filled in, the count of `new TextEncoder().encode(JSON.stringify(commands)).length`.'},'updated_at':{'type':['string','null'],'format':'date-time','description':'When the draft last changed; null until it first does.'},'device':{'type':'string','maxLength':40,'description':'The device that last changed it, as it named itself; empty when it did not.'}},['id','version','file','pages','commands','input_ids','limits','updated_at','device']),
        'Payment':obj({'id':UUID,'invoice_id':UUID,'kind':S,'plan':nullable_string,'amount':I,'currency':S,'sandbox':B,'occurred_at':DT,'is_renewal':B,'refunded':I,'status':S,'refund_status':nullable_string,'provider':S},['id','invoice_id','kind','amount','currency','sandbox','occurred_at','is_renewal','refunded','status']),
        'Subscription':obj({'id':UUID,'plan':S,'status':S,'renewal_enabled':B,'current_period_end':DT,'active_until':{'type':['string','null'],'format':'date-time'},'scheduled_plan':nullable_string,'scheduled_at':{'type':['string','null'],'format':'date-time'},'requires_new_checkout':B,'sandbox':B,'provider':S},['id','plan','status','renewal_enabled','current_period_end','sandbox']),
        'ManualPayment':obj({'id':UUID,'reference':S,'plan':{'enum':['plus','premium']},'amount':I,'currency':S,'status':{'enum':['awaiting','submitted','approved','rejected','cancelled','expired','refunded']},'channel':S,'card':obj({'number':nullable_string,'last4':S,'holder':S,'label':S},['number','last4','holder','label']),'receipt_received':B,'payer_note':S,'created_at':DT,'expires_at':DT,'submitted_at':{'type':['string','null'],'format':'date-time'},'decided_at':{'type':['string','null'],'format':'date-time'},'rejection_reason':nullable_string,'starts_at':{'type':['string','null'],'format':'date-time'},'active_until':{'type':['string','null'],'format':'date-time'}},['id','reference','plan','amount','currency','status','card','receipt_received','created_at','expires_at']),
        # `price` is what the customer sends today; `regular_price` is the plan's
        # price before any discount, and `discount` the one running, if any.
        'ManualPaymentOptions':obj({'enabled':B,'currency':S,'period_days':I,'plans':arr(obj({'plan':{'enum':['plus','premium']},'price':I,'regular_price':I,'discount':{'anyOf':[ref('PlanDiscount'),{'type':'null'}]}},['plan','price','regular_price','discount'])),'automatic':obj({'available':B},['available']),'payment':{'anyOf':[ref('ManualPayment'),{'type':'null'}]}},['enabled','currency','period_days','plans','automatic','payment']),
        'SubscriptionState':obj({'plan':S,'subscription':{'anyOf':[ref('Subscription'),{'type':'null'}]},'sandbox':B},['plan','subscription','sandbox']),
        'BotDelivery':obj({'id':UUID,'status':S,'attempts':I},['id','status','attempts']),
        'DeckPins':obj({'design':S,'deck_seed':S,'body_size':{'type':'number'},'variants':{'type':'object','additionalProperties':S},
                        'photos':{'type':'object','additionalProperties':obj({'asset_id':{'type':['string','null'],'format':'uuid'},'candidates':arr(obj({'asset_id':UUID},['asset_id']))},['asset_id','candidates'])}},
                       ['design','deck_seed','body_size','variants','photos']),
    })
    models['GenerationMaterial']=obj({'key':S,'title':S,'sections':arr(ref('GenerationSection')),'questions':arr(ref('GenerationQuestion')),'citations':arr(obj({'asset_id':UUID,'page':I,'quote':S}))},['key','title','sections','questions'])
    models['GenerationContent']['properties']['materials']=arr(ref('GenerationMaterial'))
    models['GenerationContent']['properties']['citations']['items']['properties']['quote']=S
    for field in ('transcription_ready','transcription_reviewed'):models['GenerationDraft']['properties'][field]={'type':'boolean','readOnly':True}
    models['GenerationDraft']['properties']['revision']=obj({'source_draft_id':UUID,'source_version':I,'selected_section_ids':arr(S),'base_content':ref('GenerationContent')})
    models['GenerationDraft']['properties']['render']={**ref('DeckPins'),'readOnly':True,'description':'A generated deck (`ai.pptx`): how it was drawn, so an edit changes only the slide it touches. `variants` and `photos` are by section id; a photo `asset_id` is the account\'s own file, null when none was kept, and `candidates` are small copies kept on offer for that slide, possibly none. `deck_seed` is opaque. Absent until a deck has been made.'}
    # Typed command alternatives exactly match the processor's strict allowlist.
    from processors.editor import FIELDS
    # What a field is, past a plain string. `original` and `text` carry the bound normalize holds them to.
    TYPED={'angle':{'type':'integer','enum':[90,180,270]},'order':{'type':'array','minItems':1,'items':{'type':'integer','minimum':1}},
           'bold':B,'italic':B,'font':{'enum':['sans','serif']},'color':{'type':'string','pattern':'^#[0-9A-Fa-f]{6}$'},
           'text':{'type':'string','maxLength':2000},'original':{'type':'string','minLength':1,'maxLength':2000}}
    OPTIONAL={'font_size','color','stroke_width','font','bold','italic'}
    commands=[]
    for kind,fields in FIELDS.items():
        fieldspec={name:TYPED.get(name,S) for name in fields}
        fieldspec['type']={'const':kind}
        for name in ('page','input_index','image_index'):
            if name in fields:fieldspec[name]={'type':'integer','minimum':0 if name=='image_index' else 1}
        for name in ('x','y','width','height','font_size','stroke_width'):
            if name in fields:fieldspec[name]={'type':'number','minimum':0}
        if 'points' in fields:fieldspec['points']={'type':'array','minItems':2,'maxItems':200,'items':{'type':'array','minItems':2,'maxItems':2,'items':{'type':'number','minimum':0}}}
        command=obj(fieldspec,sorted(fields-OPTIONAL-({'text'} if kind=='redact' else set())));command['additionalProperties']=False;commands.append(command)
    models['EditorCommand']={'oneOf':commands,'description':'PDF points from displayed top-left, pages start at 1, image indices start at 0. Image input indices reference extra uploaded assets. Redaction requires explicit rasterization acknowledgement and a separate export. Every position is in source page numbers: `reorder.order` lists all source pages, deleted ones too, and the final order is that minus the deleted pages.'}
    studio_feature=obj({'id':S,'name':S,'surface':S,'eligible':B,'requires_provider':B,'parameter_schema':O,'locales':arr(S),'cv_facts':{**obj({'required':arr(S),'optional':arr(S)},['required','optional']),'description':'Only for `ai.cv`: the facts a CV is made of, in the order they are shown. A new CV is refused with `cv_missing` (400; `message_params.missing` and `optional_missing` list the facts) while a `required` one is missing from what the customer gave and wrote, unless they insist (`options.topic_given`).'}},['id','name','eligible'])
    template=obj({'id':S,'name':S,'locales':arr(S),'kind':S,'style':O,'eligible':B},['id','name'])
    models['BatchQuote']=obj({'id':UUID,'quote_id':UUID,'feature_id':S,'groups':arr(obj({'index':I,'feature_id':S,'input_ids':arr(UUID),'normalized_parameters':O})),'affordable':B,'expires_at':DT,'max_children':I,'reservation_mode':S,'template':obj({'id':UUID,'name':S,'version':I},['id','name','version']),'limitations':arr(S)},['id','quote_id','feature_id','groups','affordable','expires_at','reservation_mode','limitations'])
    models['BatchRun']=obj({'id':UUID,'quote_id':UUID,'feature_id':S,'status':S,'created_at':DT,'completed_at':{'type':['string','null'],'format':'date-time'},'children':arr(obj({'index':I,'feature_id':S,'status':S,'job':{'anyOf':[ref('Job'),{'type':'null'}]},'error':{'anyOf':[ref('Error'),{'type':'null'}]}})),'jobs':arr(ref('Job')),'counts':{'type':'object','additionalProperties':I}},['id','quote_id','feature_id','status','children','jobs','counts'])
    endpoint('/health','get','getHealth',obj({'status':S,'service':S,'api_version':S},['status','service','api_version']),public=True)
    endpoint('/batches/quotes','post','quoteBatch',ref('BatchQuote'),{'oneOf':[obj({'feature_id':{'enum':['batch.convert','batch.compress','batch.image_sets']},'groups':arr(obj({'feature_id':S,'input_ids':arr(UUID),'parameters':O},['input_ids']))},['feature_id','groups']),obj({'feature_id':{'const':'editor.batch_forms'},'template_id':UUID,'template_version':I,'input_ids':arr(UUID)},['feature_id','template_id','template_version','input_ids'])]},code='201')
    endpoint('/batches','get','listBatches',obj({'results':arr(ref('BatchRun'))},['results']))
    endpoint('/batches','post','submitBatch',ref('BatchRun'),obj({'quote_id':UUID},['quote_id']),code='201',description='Child jobs reserve when started and settle separately. Successful children stay charged when other children fail; no parent task charge.')
    endpoint('/batches/{id}','get','getBatch',ref('BatchRun'))
    endpoint('/batches/{id}','post','continueBatch',ref('BatchRun'),obj({}))
    endpoint('/batches/{id}/resume','post','resumeBatch',ref('BatchRun'),obj({}))
    endpoint('/batches/{id}/resume','get','getBatchResumeStatus',ref('BatchRun'))
    endpoint('/studio/config','get','getStudioConfig',obj({'provider':obj({'id':S,'mode':S,'label':S,'configured':B},['id','mode','label','configured']),'features':arr(studio_feature),'generation_features':arr(studio_feature),'templates':arr(template),'limits':{**O,'properties':{'editor':{**obj({name:B for name in EDITOR_FLAGS},EDITOR_FLAGS),'description':'Which parts of the new editors are on. The web treats a missing one as off.'}}}},['provider','features','generation_features','templates','limits']))
    create=obj({'feature_id':S,'title':S,'prompt':S,'source_text':S,'source_ids':arr(UUID),'output_locale':{'enum':['en','uz','ru']},'output_format':{'enum':['pdf','pptx']},'options':O},['feature_id'])
    endpoint('/generation/drafts','get','listGenerationDrafts',obj({'results':arr(ref('GenerationDraft'))},['results']))
    endpoint('/generation/drafts','post','createGenerationDraft',ref('GenerationDraft'),create,code='201',description='Uncharged encrypted authoring draft. Local authoring is not an AI response. Provider generation happens only after a confirmed quote.')
    endpoint('/generation/drafts/{id}','get','getGenerationDraft',ref('GenerationDraft'))
    endpoint('/generation/drafts/{id}','patch','updateGenerationDraft',ref('GenerationDraft'),obj({'version':I,'title':S,'prompt':S,'source_text':S,'source_ids':arr(UUID),'output_locale':{'enum':['en','uz','ru']},'output_format':{'enum':['pdf','pptx']},'options':O,'content':ref('GenerationContent'),'outline':arr(obj({'id':S,'title':S,'body':S,'notes':S,**SLIDE_FIELDS}))},['version']))
    endpoint('/generation/drafts/{id}','delete','deleteGenerationDraft',deleted)
    endpoint('/generation/drafts/{id}/outline','post','reviewGenerationOutline',ref('GenerationDraft'),version)
    deck_design=obj({'id':S,'name':S,'theme':{'enum':['light','dark','bold']},'photo':B,'pattern':S,'composition':S,'preview':S,'heading_font':S,'body_font':S,'colours':{'type':'object','additionalProperties':S}},['id','name','theme','colours'])
    endpoint('/studio/deck-designs','get','listDeckDesigns',obj({'categories':arr(obj({'id':S,'name':S,'designs':arr(deck_design)},['id','name','designs'])),'default_pages':I},['categories','default_pages']),description='Every design a deck can wear, grouped by category, in the colours each renders in. `locale` (en, uz, ru) names the categories.')
    paths['/studio/deck-designs']['get'].setdefault('parameters',[]).append({'name':'locale','in':'query','schema':{'enum':['en','uz','ru']}})
    endpoint('/studio/deck-designs/{design}.png','get','getDeckDesignPreview',S,public=True,description='A design\'s cover as the theme picker shows it, with a sample title in `locale`. Public and immutable: the catalogue\'s `preview` URL carries the design\'s version.')
    paths['/studio/deck-designs/{design}.png']['get']['parameters']=[{'name':'design','in':'path','required':True,'schema':S},{'name':'locale','in':'query','schema':{'enum':['en','uz','ru']}},{'name':'v','in':'query','schema':S}]
    paths['/studio/deck-designs/{design}.png']['get']['responses']['200']={'description':'PNG cover thumbnail','content':{'image/png':{'schema':{'type':'string','format':'binary'}}}}
    from apps.studio.cv.templates import DRAWERS,TONES
    face={'enum':['serif','sans']}
    models['CvTemplate']=obj({'id':S,'name':S,'category':S,'drawer':{'enum':list(DRAWERS)},'photo':B,'tone':{'enum':list(TONES)},'preview':S,'fonts':obj({'heading':face,'body':face},['heading','body']),'colours':obj({role:S for role in ('accent','secondary','tint','ink','fill')},['accent','secondary','tint','ink','fill'])},['id','name','category','drawer','photo','tone','preview','fonts','colours'])
    endpoint('/studio/cv-templates','get','listCvTemplates',obj({'categories':arr(obj({'id':S,'name':S,'templates':arr(ref('CvTemplate'))},['id','name','templates'])),'default':S},['categories','default']),description='Every template a CV can wear, grouped by category, in the colours each renders in. `locale` (en, uz, ru) names the categories; `default` is the template Auto starts from.')
    paths['/studio/cv-templates']['get'].setdefault('parameters',[]).append({'name':'locale','in':'query','schema':{'enum':['en','uz','ru']}})
    endpoint('/studio/cv-templates/{template}.png','get','getCvTemplatePreview',S,public=True,description='A template\'s page 1 with a fictional sample CV in `locale`, 480 px wide. Public and immutable: the catalogue\'s `preview` URL carries the catalogue\'s version.')
    paths['/studio/cv-templates/{template}.png']['get']['parameters']=[{'name':'template','in':'path','required':True,'schema':S},{'name':'locale','in':'query','schema':{'enum':['en','uz','ru']}},{'name':'v','in':'query','schema':S}]
    paths['/studio/cv-templates/{template}.png']['get']['responses']['200']={'description':'PNG page thumbnail','content':{'image/png':{'schema':{'type':'string','format':'binary'}}}}
    endpoint('/studio/cv-reads','get','listCvReads',obj({'reads':arr(ref('CvRead')),'ahead':I,'estimated_seconds':{'type':['integer','null'],'minimum':0}},['reads','ahead','estimated_seconds']),description='How the reading of a CV\'s files stands. A file uploaded with `purpose` `cv_source` is read once, in a queue the accounts take turns in, never while a draft is made: a CV draft (`ai.cv`, `cv_source` `linkedin` or `file`) whose files are still queued or being read is refused with `cv_reading` (409; `message_params.ahead` and `estimated_seconds` as here), to be made again once they are read. `ids` names the account\'s own files, at most ten; an id that is no live file of theirs is `file_unavailable` (404). A file with no read yet is queued. `ahead` is how many reads of other customers\' files finish before the first of these still queued is read (the account\'s own files are not ahead of it): 0 when none waits or one of them is being read; each read\'s own `ahead` counts every read before that file. `estimated_seconds` is about how long until the last is read, counting what is left of the reads in progress: 0 when none waits, null with no recent reads to tell it from or while no reader is taking the queued reads. Asked every two seconds or so while waiting; more than 120 in an account\'s minute (counted from its first request) is `rate_limited`.')
    paths['/studio/cv-reads']['get']['parameters']=[{'name':'ids','in':'query','required':True,'style':'form','explode':True,'schema':{'type':'array','items':UUID,'minItems':1,'maxItems':10}}]
    endpoint('/studio/cv-reads','delete','cancelCvReads',obj({'cancelled':I},['cancelled']),description='Takes files the customer removed from a CV out of the reading queue: their reads still queued are dropped. A read already started finishes; ids that are gone or not the account\'s are passed over. A file dropped here and used after all is queued again when a draft asks for it.')
    paths['/studio/cv-reads']['delete']['parameters']=paths['/studio/cv-reads']['delete'].get('parameters',[])+paths['/studio/cv-reads']['get']['parameters']
    endpoint('/generation/drafts/{id}/setup','post','setupGenerationDraft',obj({'draft':ref('GenerationDraft'),'quote':ref('Quote')},['draft','quote']),obj({'pages':{'type':'integer','minimum':1,'maximum':200},'deck_design':S,'cv_template':S},[]),description='A deck\'s slide count and design, or a CV\'s template, chosen over what its description says. A deck (`ai.pptx`) takes `pages` and `deck_design` (a design id or `auto`); a CV (`ai.cv`) takes `cv_template` (a template id or `auto`); anything else is refused. Returns the new quote; the review in the Telegram chat is redrawn with it.')
    endpoint('/generation/drafts/{id}/quote','post','quoteGenerationDraft',ref('Quote'),obj({'version':I,'stage':{'enum':['document','outline']}},['version']),code='201')
    models.update({
        'DeckExportSummary':obj({'slides':I,'format':{'enum':['pptx','pdf','both']},'kept_until':{**DT,'description':'When a file made now would expire.'},'size_estimate':{**I,'description':'About how many bytes the files come to.'},'cost':ref('QuoteCost'),
                                 'warnings':{**arr(S),'description':'What the file would come without: `logo_left_out` when the logo is no longer stored.'}},['slides','format','kept_until','size_estimate','cost','warnings']),
        'DeckSlideFit':obj({'id':S,'index':{**I,'description':'The slide\'s position in the deck, from 0.'},'fits':B,'words_over':{**I,'description':'Words of this slide that would not show.'},
                            'lines_used':{**I,'description':'Lines its text takes at the sizes it is set in. Past `lines_max` whenever it does not fit.'},'lines_max':I,
                            'layouts_fitting':{**arr({'type':'string','enum':_slide_fields()['layout']['enum'][1:]}),'description':'The layouts that can carry this slide and show all of it.'}},
                           ['id','index','fits','words_over','lines_used','lines_max','layouts_fitting']),
    })
    endpoint('/generation/drafts/{id}/export-quote','post','quoteDeckExport',{'allOf':[ref('Quote'),obj({'summary':ref('DeckExportSummary')},['summary'])]},
             obj({'version':I,'format':{'enum':['pptx','pdf','both']},'deliver':{'enum':['chat','download']}},['version','format','deliver']),code='201',
             description='The price of sending a generated deck again from its draft, as PowerPoint, PDF or both: no AI edit, one file task, submitted through `/jobs`. It holds nothing of the deck but ids and the format. Refused, with status 409, when: `version_conflict`; `generation_running`; `deck_not_editable` (not a deck, or none has been drawn from this draft yet); `pinned_asset_expired` (`message_params.sections`: [{id, index}], the slides whose picture is no longer stored); `slide_text_too_long` (`message_params.sections`: [{id, index, words_over}], the slides whose text would not all show).')
    endpoint('/generation/drafts/{id}/fit','post','measureDeckSlide',ref('DeckSlideFit'),obj({'section':ref('GenerationSection')},['section']),
             description='How one slide as it stands in the editor sits on this deck, and the layouts that would hold it whole. Nothing is saved or drawn into a file. A section whose id the deck does not have is measured as a slide added at the end. `deck_not_editable` as for the export quote.')
    frame=obj({'field':{'enum':['heading','body','picture']},**{side:{'type':'number'} for side in 'xywh'}},['field','x','y','w','h'])
    models.update({
        'DeckRenderSlide':obj({'index':{**I,'description':'The slide\'s position in the deck, from 0.'},'key':{**S,'description':'What its picture is made from: the same key is the same picture.'},'url':{**S,'description':'The picture, 1280 by 720 px.'},'thumb_url':{**S,'description':'The picture, 96 by 54 px.'},
                               'frames':{**arr(frame),'description':'Where the slide\'s heading, body and picture lie, as fractions of the slide.'},'fits':B,'letters_over':{**I,'description':'Letters of this slide that do not show.'}},
                              ['index','key','url','thumb_url','frames','fits','letters_over']),
        'DeckRender':obj({'status':{'enum':['none','queued','running','done','failed','stale'],'description':'`none`: nothing has been asked for, or it has gone; POST asks. `queued` and `running`: a task will draw this version or a later one. `done`: `slides` are this version. `failed`: see `error`. `stale`: this version was not drawn and the deck has moved on.'},
                          'version':I,'slides':arr(ref('DeckRenderSlide')),'error':{**nullable_string,'description':'Why the last try failed: `render_deck_interrupted` is worth asking again, `pinned_asset_expired` is not until the picture is changed.'}},
                         ['status','version','slides','error']),
    })
    endpoint('/generation/drafts/{id}/render','get','getDeckRender',ref('DeckRender'),
             description='How the drawing of this version of the deck stands; the draft\'s current one without `version`. Reads only. Answers `feature_unavailable` with the deck editor off.')
    paths['/generation/drafts/{id}/render']['get']['parameters'].append({'name':'version','in':'query','schema':{'type':'integer','minimum':1}})
    endpoint('/generation/drafts/{id}/render','post','requestDeckRender',obj({'task_id':UUID,'status':{'enum':['queued','running','done','failed']}},['task_id','status']),obj({'version':I},['version']),code='202',
             description='Have this version of the deck drawn, in a queue of its own and free, when a field is committed: not on every autosave. A newer ask replaces one still queued. Only the slides that changed are drawn. `version_conflict`; `deck_not_editable`; `lane_busy` (429, retryable) past the day\'s budget or with three tasks waiting.')
    for suffix,operation,about in (('png','getDeckSlide','1280 by 720 px'),('thumb.png','getDeckSlideThumb','96 by 54 px')):
        route=f'/generation/drafts/{{id}}/slides/{{key}}.{suffix}'
        endpoint(route,'get',operation,S,description=f'A slide already drawn, {about}, inline. Nothing is drawn for this request: anything else is 404.')
        paths[route]['get']['parameters'].append({'name':'key','in':'path','required':True,'schema':{'type':'string'}})
        paths[route]['get']['responses']['200']={'description':'Private PNG; no-store','content':{'image/png':{'schema':{'type':'string','format':'binary'}}}}
    cover_lines={**arr({'type':'string','maxLength':160}),'maxItems':8,'description':'Lines as they go on a title slide, label and all ("Tayyorladi: …").'}
    deck_locale={'enum':['en','uz','ru'],'description':'The language of the deck the lines were written for: their labels are in it.'}
    cover_roles={**arr({'anyOf':[{'enum':['made','checked','group','school']},{'type':'null'}]}),'maxItems':8}
    models.update({
        'CoverLines':obj({'lines':cover_lines,'locale':{'anyOf':[deck_locale,{'type':'null'}],'description':'The language of the deck the lines were written for; null when the client did not say.'},
                          'roles':{**cover_roles,'description':'One per line, in step with `lines`: the Cover sheet row it was kept from, null where the client did not say.'}},['lines','locale','roles']),
        'LatinPreview':obj({'texts':arr(S),'changed':B},['texts','changed']),
    })
    endpoint('/studio/cover-lines','get','getCoverLines',ref('CoverLines'),description='The cover lines this account asked to keep for its next decks, their language and the row of each; [], null and [] when none. New decks in that language also carry them on their title slide for what neither their description nor their own cover says (who made it, who checks it, the class, the school), in the room the description leaves: a line with a row says that row, one without says what its words do. `feature_unavailable` with the deck editor off.')
    endpoint('/studio/cover-lines','post','rememberCoverLines',ref('CoverLines'),obj({'lines':cover_lines,'locale':deck_locale,'roles':{**cover_roles,'description':'The Cover sheet row of each line: who made it, who checks it, the class or group, the school; null for a line it does not say. One per line given, a blank line\'s included (it goes with its line); all null without it.'}},['lines']),description='Keep these 1–8 lines of ≤160 characters (packed at rest) for the next decks, with the language of the deck they were written for and the row of each. `invalid_parameters` otherwise, for a language not listed, or for roles that are not one per line or not one of those.')
    endpoint('/studio/cover-lines','delete','forgetCoverLines',ref('CoverLines'),description='Forget the kept cover lines: answers as a GET with none kept, `{"lines": [], "locale": null, "roles": []}`.')
    endpoint('/studio/latin','post','previewLatin',ref('LatinPreview'),obj({'texts':{**arr(S),'minItems':1,'maxItems':40}},['texts']),description='Each text in Uzbek Latin letters as a send keeps it (scripts.to_script), at most 12 000 characters in all. Saves nothing.')
    paths['/generation/drafts/{id}']['patch']['responses']['413']={'description':'`payload_too_large`: a deck draft body over 128 KiB (other drafts: `invalid_request` over 32 KiB). Nothing is saved.','content':{'application/json':{'schema':obj({'error':ref('Error')})}}}
    endpoint('/generation/jobs/{id}/retry-quote','post','quoteGenerationRetry',ref('Quote'),obj({}),code='201',description='Review a fresh quote for an unchanged failed generation. Completed provider batches may be reused only within this explicit retry chain; confirmation and allowance checks still apply.')
    endpoint('/generation/drafts/{id}/generate','post','generateDraft',ref('Job'),obj({'quote_id':UUID},['quote_id']),code='201')
    for path,kind in [('/workflows','Workflow'),('/templates','Template'),('/editor/form-templates','FormTemplate')]:
        listing=obj({'results':arr(ref('SavedDefinition')),'limit':I,'published':arr(template)},['results','limit','published'])
        request=obj({'name':S,'steps':arr(ref('WorkflowStep')),'content':O,'output_locale':S},['name'])
        endpoint(path,'get','list'+kind+'s',listing)
        endpoint(path,'post','create'+kind,ref('SavedDefinition'),request,code='201')
        endpoint(path+'/{id}','get','get'+kind,ref('SavedDefinition'))
        endpoint(path+'/{id}','patch','update'+kind,ref('SavedDefinition'),obj({**request['properties'],'version':I},['name','version']))
        endpoint(path+'/{id}','delete','delete'+kind,deleted)
    endpoint('/workflows/{id}/quote','post','quoteWorkflow',ref('WorkflowQuote'),obj({'input_ids':arr(UUID)},['input_ids']))
    endpoint('/workflows/{id}/run','post','runWorkflow',ref('WorkflowRun'),obj({'input_ids':arr(UUID),'version':I,'confirmed':{'const':True},'confirmation_token':S},['input_ids','version','confirmed','confirmation_token']),description='Each step consumes the previous result. Failure stops subsequent steps; successful steps remain charged.')
    endpoint('/education/projects','get','listEducationProjects',obj({'results':arr(ref('EducationProject')),'limit':I,'retention_days':I},['results','limit','retention_days']))
    endpoint('/education/projects','post','createEducationProject',ref('EducationProject'),obj({'draft_id':UUID,'title':S,'save_consent':{'const':True}},['draft_id','save_consent']),code='201')
    endpoint('/education/projects/{id}','get','getEducationProject',ref('EducationProject'))
    endpoint('/education/projects/{id}','patch','extendEducationProject',ref('EducationProject'),obj({'version':I,'save_consent':{'const':True}},['version','save_consent']))
    endpoint('/education/projects/{id}','delete','deleteEducationProject',deleted)
    endpoint('/education/projects/{id}/practice','post','submitPractice',ref('PracticeResult'),obj({'answers':{'type':'object','additionalProperties':S}},['answers']),description='Exact-match practice feedback; not a final grade.')
    endpoint('/shares','get','listShares',obj({'results':arr(ref('ShareGrant'))},['results']))
    endpoint('/shares','post','createShare',ref('ShareGrant'),obj({'artifact_id':UUID,'expires_hours':{'type':'integer','minimum':1,'maximum':24}},['artifact_id']),description='Only learner_material/public_preview artifacts from explicitly shareable teacher features may be shared. Teacher-only content is denied even for legacy incorrect roles or existing bearer links. The bearer URL is returned only when created.')
    endpoint('/shares/{id}','get','getShare',ref('ShareGrant'))
    endpoint('/shares/{id}','delete','revokeShare',ref('ShareGrant'))
    endpoint('/shared/{token}','get','downloadSharedArtifact',S,public=True)
    paths['/shared/{token}']['get']['parameters']=[{'name':'token','in':'path','required':True,'schema':S}]
    paths['/shared/{token}']['get']['responses']['200']={'description':'Role-restricted bearer-link attachment, no-store','content':{'application/octet-stream':{'schema':{'type':'string','format':'binary'}}}}
    document=models['EditorDocument']
    models['EditorDocumentRow']={**obj({name:value for name,value in document['properties'].items() if name!='commands'},[name for name in document['required'] if name!='commands']),'description':'A draft as a list shows it: without its marks, which only the draft itself answers with.'}
    endpoint('/editor/documents','get','listEditorDocuments',obj({'results':arr(ref('EditorDocumentRow'))},['results']))
    endpoint('/editor/documents','post','createEditorDocument',ref('EditorDocument'),obj({'file_id':UUID},['file_id']),code='201',description='One draft per account and file: 201 for a new one, 200 with the marks already there for a file opened before. A file the editor cannot open is `unsupported_file`, with `message_params.reason` one of `password`, `signed`, `pptx_upload`, `not_pdf` when it is known. A file of this account that has run out is `file_expired` (410); one the customer deleted, is unknown or belongs to another account is `file_unavailable` (404).')
    paths['/editor/documents']['post']['responses']['200']=paths['/editor/documents']['post']['responses']['201']
    paths['/editor/documents']['post']['responses']['410']={'description':'`file_expired`: the file has run out and has to be sent again.','content':{'application/json':{'schema':obj({'error':ref('Error')})}}}
    endpoint('/editor/documents/{id}','get','getEditorDocument',ref('EditorDocument'))
    endpoint('/editor/documents/{id}','patch','updateEditorDocument',ref('EditorDocument'),obj({'version':I,'commands':arr(ref('EditorCommand')),'input_ids':arr(UUID),'device':{'type':'string','maxLength':40}},['version','commands']))
    conflict=lambda description:{'description':description,'content':{'application/json':{'schema':obj({'error':ref('Error')})}}}
    paths['/editor/documents/{id}']['patch']['responses']['400']=conflict('Invalid request. `invalid_editor_command`: one change cannot be saved. `message_params` has `index`, its position in `commands` counted from 0, and `code`, why it was refused. Nothing is saved.')
    paths['/editor/documents/{id}']['patch']['responses']['409']=conflict('`version_conflict`: the draft changed elsewhere. `message_params` has `updated_at`, `device` and the marks each side holds, `theirs` and `mine`. Nothing is saved.')
    paths['/editor/documents/{id}']['patch']['responses']['413']={'description':'`payload_too_large`: the draft measures over `limits.bytes`, or the body over 128 KiB. Nothing is saved.','content':{'application/json':{'schema':obj({'error':ref('Error')})}}}
    endpoint('/editor/documents/{id}','delete','deleteEditorDocument',deleted)
    models.update({
        'QuoteCost':obj({'kind':{'enum':['file_task','included','none'],'description':'`file_task`: this send uses one of the week\'s file tasks. `included`: the plan has no weekly limit. `none`: it uses nothing, as the same file already exists or is being made or, with `count_once` on, this draft has been counted this week.'},
                         'left':{'type':['integer','null'],'description':'File tasks left this week, before this send; null when `included`.'},'limit':{'type':['integer','null']}},['kind','left','limit']),
        'EditorQuoteSummary':obj({'changes_by_page':{'type':'object','additionalProperties':I,'description':'How many changes each page holds, by its number in the file as uploaded. A form field or a new page order belongs to no page.'},
                                  'pages_before':I,'pages_after':I,'raster_pages':{**arr(I),'description':'The pages, numbered as uploaded, that will become pictures for their black-out. A page being deleted is not among them.'},
                                  'size_estimate':{**I,'description':'About how many bytes the file comes to. In a chat, a file over 50 MB arrives as a link.'},'kept_until':{**DT,'description':'When a file made now would expire.'},'cost':ref('QuoteCost')},
                                 ['changes_by_page','pages_before','pages_after','raster_pages','size_estimate','kept_until','cost']),
    })
    endpoint('/editor/documents/{id}/quote','post','quoteEditorDocument',{'allOf':[ref('Quote'),obj({'summary':ref('EditorQuoteSummary')},[])]},
             obj({'version':I,'deliver':{'enum':['chat','download'],'description':'Where the file goes: this is a send of the stored draft, by a pointer to it. The Quote holds no marks and comes with `summary`. Left out by the web from before these sends, whose quote carries the marks.'},'accept_rasterization':B},['version']),code='201',
             description='One send of the stored draft: one quote, one job, one file task. The marks are read again at submission and when the job runs; if they have changed since, that is `version_conflict` and nothing is counted. A send identical to the last file made, or to the one being made, returns that job rather than a new one.')
    paths['/editor/documents/{id}/quote']['post']['responses']['400']=conflict('`rasterization_consent_required`: pages would become pictures and `accept_rasterization` was not true; `message_params.pages` lists them. `editor_text_overflow`: a text does not fit its page; `message_params.index` is its position in `commands`, counted from 0. `invalid_editor_command`, as on saving. Nothing is quoted.')
    paths['/editor/documents/{id}/quote']['post']['responses']['409']=conflict('`version_conflict`: the draft changed elsewhere. `message_params` has `updated_at`, `device` and `theirs`, the marks it holds now; the request carries no marks, so the client counts its own. `telegram_link_required`: `deliver` is `chat` and the account has no Telegram. Nothing is quoted.')
    paths['/editor/documents/{id}/quote']['post']['responses']['429']=conflict('`weekly_file_limit`: this week\'s file tasks are used up. `send_limit`: too many sends for now, `retryable`; `message_params` has `limit` and `per`, `day` for this draft or `hour` for the account. Nothing is quoted.')
    endpoint('/billing/subscription','get','getSubscription',ref('SubscriptionState'))
    endpoint('/billing/transactions','get','getTransactions',obj({'results':arr(ref('Payment'))},['results']))
    channel_state=obj({'required':B,'joined':B,'channels':arr(obj({'title':S,'url':S,'joined':B},['title','url','joined']))},['required','joined','channels'])
    endpoint('/channels','get','getRequiredChannels',channel_state,description='Telegram channels a Free or Plus account must join before using a service (Premium is never asked). When required and not joined, task requests fail with channels_required and the same channels in message_params.')
    endpoint('/channels/check','post','checkRequiredChannels',channel_state,obj({}),description="Ask Telegram again after the customer says they've joined.")
    endpoint('/billing/manual','get','getManualPayment',ref('ManualPaymentOptions'),description='Card transfer to the owner, reviewed by hand. The card is shown only to signed-in customers.')
    endpoint('/billing/manual','post','createManualPayment',ref('ManualPayment'),obj({'plan':{'enum':['plus','premium']}},['plan']),code='201')
    endpoint('/billing/manual/{id}','get','getManualPaymentDetail',ref('ManualPayment'))
    endpoint('/billing/manual/{id}','delete','cancelManualPayment',ref('ManualPayment'))
    endpoint('/billing/manual/{id}/receipt','post','uploadManualPaymentReceipt',ref('ManualPayment'),obj({}),description='The transfer receipt: a JPG/PNG photo or a PDF, at most 10 MB, with an optional note.')
    contact=obj({'username':S,'url':S},['username','url'])
    company=obj({'name':S,'tin':S,'address':S,'phone':S,'email':S},['name','tin','address','phone','email'])
    endpoint('/contacts','get','getContacts',obj({'support':contact,'ads':contact,'bot':contact,'company':company},['support','ads','bot','company']),public=True,description='The Telegram accounts for support and for advertising or partnerships, as set in the admin, empty when not set; the bot (its public username and t.me link, empty when not set); and the company\'s legal details (name, taxpayer number, address, phone, email), the phone and email empty when not set.')
    ndt={'type':['string','null'],'format':'date-time'}
    reward=obj({'tier':I,'months':I,'invites':I,'days':I,'starts_at':ndt,'ends_at':ndt,'created_at':DT},['tier','months','invites','days','starts_at','ends_at','created_at'])
    next_reward=obj({'tier':I,'months':I,'invites':{**I,'description':'Counted friends this reward needs in all.'},'have':{**I,'description':'Friends counted toward this reward so far, 0 to `step`.'},'remaining':I},['tier','months','invites','have','remaining'])
    endpoint('/referrals','get','getReferrals',obj({'code':S,'url':nullable_string,'rewards_count':{**I,'description':'Every friend ever counted, including those from before invitations earned Plus.'},'pending_count':{**I,'description':'Friends who joined with the link and have not been counted yet.'},'monthly_cap':I,'qualification':S,'sandbox':B,
        'step':{**I,'description':'Counted friends per reward.'},'counted':{**I,'description':'Friends counted toward Plus months.'},'counted_this_month':I,'month_full':{**B,'description':'This month\'s friends are all counted; new ones count from `next_month`.'},'next_month':{**DT,'description':'The start of the next calendar month, Tashkent time.'},'waiting_next_month':{**I,'description':'Friends who finished a task but wait for next month\'s room.'},
        'next_reward':next_reward,'rewards':arr(reward)},['code','url','rewards_count','pending_count','monthly_cap','qualification','sandbox','step','counted','counted_this_month','month_full','next_month','waiting_next_month','next_reward','rewards']),
        description='Invite friends, earn Plus. A friend counts after opening the bot with `url` and finishing a first task, at most `monthly_cap` a calendar month (Tashkent). Every `step` counted friends earn Plus, one month more each time: 1 month, then 2, then 3. The months follow any paid period. Reading this counts the friends who are due.')
    endpoint('/referrals','post','claimReferral',obj({'id':I,'status':S}),obj({'code':S},['code']))
    endpoint('/artifacts/{id}/deliver','post','deliverArtifactToTelegram',ref('BotDelivery'),obj({}),code='201')
    local_asset=obj({'id':UUID,'name':S,'mime_type':S,'size_bytes':I,'download_url':S,'preview_url':nullable_string,'expires_at':DT})
    local_message=obj({'id':UUID,'direction':S,'text':S,'buttons':arr(arr(obj({'label':S,'callback_data':nullable_string,'url':nullable_string}))),'asset':{'anyOf':[local_asset,{'type':'null'}]},'created_at':DT},['id','direction','text','buttons','asset','created_at'])
    local_history=obj({'sandbox':B,'transport':S,'messages':arr(local_message)},['sandbox','transport','messages'])
    for method,operation in [('get','getLocalTelegram'),('post','sendLocalTelegram'),('delete','clearLocalTelegram')]:
        endpoint('/telegram/local/messages',method,operation,local_history,obj({'text':S,'callback_data':S}) if method=='post' else None,description='Offline bot transport, only sandbox test accounts. No Telegram network message is sent.')
    paths['/telegram/local/messages']['post']['requestBody']['content']['multipart/form-data']={'schema':obj({'file':{'type':'string','format':'binary'}},['file'])}
    paths['/billing/manual/{id}/receipt']['post']['requestBody']['content']={'multipart/form-data':{'schema':obj({'file':{'type':'string','format':'binary'},'note':{'type':'string','maxLength':120}},['file'])}}
    for path in ['/batches','/generation/drafts/{id}/generate','/workflows/{id}/run','/education/projects/{id}/practice','/artifacts/{id}/deliver']:
        paths[path]['post']['parameters'].append({'name':'Idempotency-Key','in':'header','required':True,'schema':{'type':'string','minLength':8,'maxLength':128}})


def schema():
    models={
        'User':obj({'id':UUID,'telegram_user_id':{'type':['string','null']},'email':{'type':['string','null']},'email_verified':B,'google_email':{'type':['string','null']},'login_methods':obj({'email':B,'google':B,'telegram':B},['email','google','telegram']),'display_name':S,'username':S,'locale':{'enum':['en','uz','ru']},'mode':{'enum':['general','student','school','teacher']},'time_zone':S,'timezone':S,'preferences':{'type':'object'},'plan':{'enum':['free','plus','premium']},'is_test':B,'created_at':DT},['id','display_name','locale','plan']),
        'Session':obj({'authenticated':B,'user':{'anyOf':[ref('User'),{'type':'null'}]},'csrf_token':S,'development_login_enabled':B},['authenticated','user','csrf_token','development_login_enabled']),
        # A weekly allowance: limit and remaining are null on a plan with no limit.
        'WeeklyAllowance':obj({'limit':{'type':['integer','null']},'used':I,'remaining':{'type':['integer','null']}},['limit','used','remaining']),
        'Usage':obj({'plan':S,'week':obj({'starts_at':DT,'resets_at':DT,'time_zone':S},['starts_at','resets_at','time_zone']),'ai_documents':ref('WeeklyAllowance'),'file_jobs':ref('WeeklyAllowance'),'edits_per_file':{'type':['integer','null']},'resets_at':DT},['plan','week','ai_documents','file_jobs','edits_per_file','resets_at']),
        'Asset':obj({'id':UUID,'name':S,'size_bytes':I,'page_count':I,'mime_type':S,'state':S,'expires_at':DT,'encrypted':B,'preview_url':{'type':['string','null']},'password_secret_id':{'type':['string','null']}},['id','name','size_bytes','page_count','mime_type','state','expires_at']),
        'Artifact':obj({'id':UUID,'file_id':{**UUID,'description':'The stored file itself, as `POST /editor/documents` takes it.'},'name':S,'size_bytes':I,'page_count':I,'mime_type':S,'state':S,'expires_at':DT,'role':S,'preview_url':{'type':['string','null']},'download_url':S},['id','file_id','name','size_bytes','mime_type','download_url']),
        'Error':obj({'code':S,'message_key':S,'message':S,'message_params':{'type':'object'},'request_id':S,'field_errors':{'type':'object'},'retryable':B},['code','message_key','message','retryable']),
        'Feature':obj({'id':S,'name':S,'label_key':S,'category':S,'release':S,'enabled':B,'eligible':B,'plans':{'type':'object'},'parameters':{'type':'object'},'capabilities':{'type':'object'},'environment':S},['id','name','enabled','eligible','parameters']),
        # A discount while it runs: the lower price, the regular one it is
        # taken from, the whole per cent off and its last day (Asia/Tashkent).
        'PlanDiscount':obj({'price':I,'regular':I,'percent':I,'until':{'type':'string','format':'date'}},['price','regular','percent','until']),
        # `price_uzs` is the regular so'm price, null when not for sale; `limits.price_uzs` carries it too.
        'Plan':obj({'id':S,'name':S,'price_uzs':{'type':['integer','null']},'discount':{'anyOf':[ref('PlanDiscount'),{'type':'null'}]},'limits':{'type':'object'},'features':arr(S)},['id','name','price_uzs','discount','limits','features']),
        'Quote':obj({'id':UUID,'quote_id':UUID,'quote_version':S,'feature_id':S,'plan_version_id':S,'tariff_version_id':S,'input_fingerprints':arr(obj({'id':UUID,'sha256':S})), 'normalized_parameters':{'type':'object'},'affordable':B,'usage':obj({'ai_documents':ref('WeeklyAllowance'),'file_jobs':ref('WeeklyAllowance'),'edits_per_file':{'type':['integer','null']},'resets_at':DT}),'expires_at':DT,'output_expectations':{'type':'object'},'limitations':arr(S),'plan':S},['id','quote_id','feature_id','affordable','expires_at']),
        'Job':obj({'id':UUID,'feature_id':S,'status':{'enum':['queued','running','finalizing','succeeded','failed','canceled','expired','no_op']},'created_at':DT,'started_at':{'type':['string','null'],'format':'date-time'},'completed_at':{'type':['string','null'],'format':'date-time'},'input_files':arr(ref('Asset')),'artifacts':arr(ref('Artifact')),'error':{'anyOf':[ref('Error'),{'type':'null'}]},'warnings':arr(S),
                   'per_command':{**arr(obj({'index':{**I,'description':'Its position in the draft\'s `commands`, from 0.'},'status':{'enum':['applied','skipped'],'description':'`skipped`: its page was deleted in the same send.'},'engine':S},['index','status','engine'])),'description':'What a send from the editor did with each change, once it has run.'},
                   'rasterized_pages':{**arr(I),'description':'The pages, numbered as uploaded, that became pictures in a send from the editor.'},
                   'parameters':{'type':'object'},'origin_channel':S},['id','feature_id','status','created_at','input_files','artifacts','error','warnings']),
    }
    paths={}
    def endpoint(path,method,operation,response,request=None,public=False,code='200',description=''):
        value={'operationId':operation,'description':description,'responses':{code:{'description':'Success','content':{'application/json':{'schema':response}}},'400':{'description':'Invalid request','content':{'application/json':{'schema':obj({'error':ref('Error')})}}},'401':{'description':'Authentication required'},'403':{'description':'Permission or CSRF validation failed'},'409':{'description':'State conflict or quota unavailable'}},'security':[] if public else [{'customerSession':[]}]}
        if request: value['requestBody']={'required':True,'content':{'application/json':{'schema':request}}}
        parameters=[]
        if '{id}' in path: parameters.append({'name':'id','in':'path','required':True,'schema':UUID})
        if method in ('post','patch','delete'): parameters.append({'name':'X-CSRFToken','in':'header','required':True,'schema':S})
        if path=='/jobs' and method=='post': parameters.append({'name':'Idempotency-Key','in':'header','required':True,'schema':{'type':'string','minLength':8,'maxLength':128}})
        if parameters: value['parameters']=parameters
        paths.setdefault(path,{})[method]=value
    endpoint('/auth/session','get','getSession',ref('Session'),public=True)
    endpoint('/auth/session','delete','logout',ref('Session'),public=True)
    endpoint('/auth/dev-login','post','developmentLogin',ref('Session'),obj({'locale':S}),True,description='Explicit loopback development-only login; unavailable outside DEBUG.')
    antibot_token={'type':'string','maxLength':2048,'writeOnly':True,'description':'Fresh Turnstile proof with action customer_auth; required when web anti-bot verification is enabled.'}
    endpoint('/auth/telegram/miniapp','post','exchangeMiniApp',ref('Session'),obj({'init_data':S,'antibot_token':antibot_token},['init_data']),True)
    challenge=obj({'id':UUID,'status':S,'expires_at':DT,'telegram_url':S,'browser_hint':S})
    endpoint('/auth/browser/challenges','post','createLoginChallenge',challenge,obj({'intent':{'enum':['login','link']},'antibot_token':antibot_token}),True,'201')
    endpoint('/auth/browser/challenges/{id}','get','getLoginChallenge',challenge,public=True)
    endpoint('/auth/browser/challenges/{id}/exchange','post','exchangeLoginChallenge',ref('Session'),obj({}),True)
    provider=obj({'enabled':B,'configured':B},['enabled','configured'])
    endpoint('/auth/providers','get','getAuthProviders',obj({'email':provider,'google':provider,'telegram':provider,'antibot':obj({'enabled':B,'configured':B,'site_key':S,'binding':S},['enabled','configured','site_key','binding'])},['email','google','telegram','antibot']),public=True)
    sent=obj({'status':{'const':'verification_sent'},'challenge_id':UUID},['status','challenge_id'])
    password={'type':'string','minLength':12,'maxLength':128,'writeOnly':True}
    email={'type':'string','format':'email','maxLength':254}
    verification=obj({'challenge_id':UUID,'code':{'type':'string','pattern':'^[0-9]{8}$','writeOnly':True}},['challenge_id','code'])
    endpoint('/auth/email/register','post','registerEmail',sent,obj({'email':email,'password':password,'display_name':S,'locale':S,'antibot_token':antibot_token},['email','password']),public=True)
    endpoint('/auth/email/verify','post','verifyEmail',ref('Session'),verification,public=True)
    endpoint('/auth/email/link','post','linkEmail',sent,obj({'email':email,'password':password,'antibot_token':antibot_token},['email','password']))
    endpoint('/auth/email/login','post','loginEmail',ref('Session'),obj({'email':email,'password':{'type':'string','maxLength':128,'writeOnly':True},'antibot_token':antibot_token},['email','password']),public=True)
    endpoint('/auth/email/reset','post','requestPasswordReset',sent,obj({'email':email,'locale':S,'antibot_token':antibot_token},['email']),public=True)
    endpoint('/auth/email/reset/confirm','post','confirmPasswordReset',obj({'status':{'const':'password_reset'}},['status']),obj({**verification['properties'],'password':password},['challenge_id','code','password']),public=True)
    endpoint('/auth/password','post','changePassword',ref('Session'),obj({'current_password':{'type':'string','writeOnly':True},'password':password},['current_password','password']))
    endpoint('/auth/google/start','post','startGoogleAuth',obj({'authorization_url':S},['authorization_url']),obj({'intent':{'enum':['login','link']},'locale':S,'antibot_token':antibot_token}),public=True)
    endpoint('/auth/google/callback','get','completeGoogleAuth',S,public=True,code='302',description='Consumes one-use browser-bound OAuth state and redirects to the configured web app; no tokens are returned to the frontend.')
    endpoint('/me','get','getProfile',ref('User'))
    endpoint('/me','patch','updateProfile',ref('User'),obj({'locale':S,'mode':S,'time_zone':S,'preferences':{'type':'object'}}))
    endpoint('/me','delete','requestAccountDeletion',obj({'status':S}))
    endpoint('/catalog','get','getCatalog',obj({'features':arr(ref('Feature')),'draft':B,'release':S},['features']),public=True)
    endpoint('/plans','get','getPlans',obj({'plans':arr(ref('Plan')),'draft':B,'currency':{'const':'UZS'},'period_seconds':I},['plans','draft','currency','period_seconds']),public=True)
    endpoint('/usage','get','getUsage',ref('Usage'))
    read_status={'enum':['queued','reading','done','failed']}
    read_error={'type':['string','null'],'description':'Why a failed read failed: `cv_file_kind`, `cv_file_unreadable`, `generation_limit` (more pages than any CV is made from, failed as it is uploaded and never read), `source_extraction_failed`, `read_timeout`, `file_unavailable`, `reader_interrupted` or `reader_error`. A failed file is a file not read: the CV says so (`cv_unread`), or is `cv_file_unreadable` when nothing at all was read.'}
    models['CvUploadRead']=obj({'status':read_status,'ahead':I,'error':read_error},['status','ahead','error'])
    models['CvRead']=obj({'asset_id':UUID,'status':read_status,'ahead':{**I,'description':'Reads that finish before this one is read: 0 once it is being read.'},'pages':{**I,'description':'Pages with text, once read.'},'ocr_pages':{**I,'description':'Of them, pages read by OCR.'},'error':read_error},['asset_id','status','ahead','pages','ocr_pages','error'])
    upload={'allOf':[ref('Asset'),obj({'cv_read':{**ref('CvUploadRead'),'description':'Only for `purpose` `cv_source`: the file is queued for reading as it arrives, and this is how its read stands.'}})]}
    endpoint('/files/uploads','post','uploadFile',upload,code='201')
    paths['/files/uploads']['post']['requestBody']={'required':True,'content':{'multipart/form-data':{'schema':obj({'file':{'type':'string','format':'binary'},'password':{'type':'string','format':'password'},
        'purpose':{'type':'string','enum':['','cv_source'],'description':'`cv_source` for a file a CV is made from (an old CV or a LinkedIn profile): a Word file with links in it (an email, a LinkedIn address) is then taken. Such a file is read for the CV and refused by every file tool.'}},['file'])}}}
    endpoint('/files/{id}','get','getFile',ref('Asset'))
    endpoint('/files/{id}','delete','deleteFile',ref('Asset'))
    endpoint('/secrets','post','createPasswordHandle',obj({'id':UUID,'expires_at':DT},['id','expires_at']),obj({'password':{'type':'string','format':'password','minLength':1,'maxLength':256}},['password']),code='201')
    endpoint('/quotes','post','createQuote',ref('Quote'),obj({'feature_id':S,'input_ids':arr(UUID),'parameters':{'type':'object'},'secret_id':UUID},['feature_id','input_ids']),code='201')
    endpoint('/jobs','post','submitJob',ref('Job'),obj({'quote_id':UUID,'deliver_to_chat':{**B,'description':'Send the result to the account\'s Telegram chat as well. A quote with `deliver` `chat` does so without asking.'}},['quote_id']),code='201',description='Returns 200 on identical retry, and for a send of a draft that already made this very file or is making it, with that job and with its file kept another 24 hours. Same key with changed quote returns 409, and so does a quote already sent under another key (`quote_already_submitted`). `telegram_link_required` (409) when the result is to go to a chat and the account has no Telegram; `send_limit` (429, retryable) when a draft has been sent too often. A failed black-out check is a job failed with `editor_check_failed`, `error.message_params.index` naming the change, and is not counted.')
    endpoint('/jobs','get','listJobs',obj({'results':arr(ref('Job')),'count':I},['results','count']))
    endpoint('/jobs/{id}','get','getJob',ref('Job'))
    endpoint('/jobs/{id}/cancel','post','cancelJob',ref('Job'),obj({}))
    for path,operation in [('/files/{id}/download','downloadFile'),('/artifacts/{id}/download','downloadArtifact')]:
        endpoint(path,'get',operation,S)
        paths[path]['get']['responses']['200']={'description':'Private file, attachment; no-store','content':{'application/octet-stream':{'schema':{'type':'string','format':'binary'}}}}
    download=paths['/files/{id}/download']['get']
    download['parameters'].append({'name':'Range','in':'header','schema':S,'description':'One byte range: `bytes=0-99`, `bytes=100-` or `bytes=-500`. Several ranges, anything ill-formed, or an `If-Range` header answer with the whole file and 200.'})
    download['responses']['200']['headers']={'Accept-Ranges':{'schema':{'const':'bytes'}}}
    download['responses']['206']={'description':'The asked part of the private file, attachment; no-store','headers':{'Accept-Ranges':{'schema':{'const':'bytes'}},'Content-Range':{'description':'`bytes first-last/size`','schema':S}},'content':{'application/octet-stream':{'schema':{'type':'string','format':'binary'}}}}
    download['responses']['416']={'description':'The range starts past the end of the file: refused with `range_not_satisfiable`.','headers':{'Content-Range':{'description':'`bytes */size`','schema':S}},'content':{'application/json':{'schema':obj({'error':ref('Error')})}}}
    for path,operation in [('/files/{id}/preview','previewFile'),('/artifacts/{id}/preview','previewArtifact')]:
        endpoint(path,'get',operation,S)
        paths[path]['get']['parameters'].append({'name':'page','in':'query','schema':{'type':'integer','minimum':1,'default':1}})
        paths[path]['get']['responses']['200']={'description':'Private single-page PNG preview, no task charge','content':{'image/png':{'schema':{'type':'string','format':'binary'}}}}
        paths[path]['get']['responses']['202']={'description':'With the deck editor on, a page not drawn yet is being drawn: ask again. Refused with `lane_busy` (429, retryable) past the day\'s budget or with three tasks waiting.','content':{'application/json':{'schema':obj({'task_id':UUID},['task_id'])}}}
    extend_schema(models,endpoint,paths)
    return {'openapi':'3.1.0','info':{'title':'DocMaster public API','version':'1.1.0','description':'Local development beta. Studio, editor, document jobs and card-transfer billing are covered. Staff operations are excluded. Live providers require server configuration.'},'servers':[{'url':'/api/v1'}],'paths':paths,'components':{'securitySchemes':{'customerSession':{'type':'apiKey','in':'cookie','name':'pdfmaster_session'}},'schemas':models}}

class Command(BaseCommand):
    help='Export immutable public OpenAPI 3.1 contract and checksum.'
    def handle(self,*args,**options):
        target=settings.BASE_DIR/'contracts'/'public.openapi.json'
        target.parent.mkdir(parents=True,exist_ok=True)
        payload=json.dumps(schema(),ensure_ascii=False,indent=2,sort_keys=True)+'\n'
        target.write_text(payload)
        checksum=hashlib.sha256(payload.encode()).hexdigest()
        target.with_suffix('.json.sha256').write_text(checksum+'  public.openapi.json\n')
        self.stdout.write(f'{target}: {checksum}')
