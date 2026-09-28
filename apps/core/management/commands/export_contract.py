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
        'GenerationDraft':obj({'id':UUID,'feature_id':S,'version':I,'provider_mode':S,'expires_at':DT,'title':S,'prompt':S,'source_text':S,'source_ids':arr(UUID),'excerpts':arr(obj({'asset_id':UUID,'page':I,'text':S})),'output_locale':{'enum':['en','uz','ru']},'output_format':{'enum':['pdf','pptx']},'options':O,'content':ref('GenerationContent'),'outline':arr(obj({'id':S,'title':S,'body':S}))},['id','feature_id','version','provider_mode','expires_at','title','output_locale','output_format','content']),
        'SavedDefinition':obj({'id':UUID,'name':S,'kind':{'enum':['workflow','template','form']},'version':I,'content':O,'output_locale':S,'steps':arr(ref('WorkflowStep'))},['id','name','kind','version']),
        'WorkflowStep':obj({'feature_id':S,'parameters':O,'meters':O},['feature_id']),
        'WorkflowQuote':obj({'workflow_id':UUID,'version':I,'input_ids':arr(UUID),'steps':arr(ref('WorkflowStep')),'meters':arr(obj({'meter':S,'amount':I},['meter','amount'])),'confirmation_required':B,'confirmation_token':S,'expires_at':DT,'limitations':arr(S)},['workflow_id','version','input_ids','steps','meters','confirmation_required','confirmation_token','expires_at','limitations']),
        'WorkflowRun':obj({'id':UUID,'status':S,'jobs':arr(ref('Job'))},['id','status','jobs']),
        'PracticeResult':obj({'score':I,'max_score':I,'questions':arr(obj({'question_id':S,'correct':B,'expected_answer':S,'explanation':S,'marks':I})),'weak_topics':arr(S),'grading':S},['score','max_score','questions','weak_topics','grading']),
        'EducationProject':obj({'id':UUID,'title':S,'version':I,'expires_at':DT,'created_at':DT,'attempts':arr(ref('PracticeResult')),'content':ref('GenerationContent')},['id','title','version','expires_at','attempts']),
        'ShareGrant':obj({'id':UUID,'artifact_id':UUID,'url':S,'expires_at':DT,'revoked':B},['id','expires_at']),
        'EditorDocument':obj({'id':UUID,'version':I,'file':ref('Asset'),'pages':arr(obj({'width':{'type':'number'},'height':{'type':'number'}},['width','height'])),'form_fields':arr(obj({'name':S,'type':S},['name','type'])),'image_counts':arr(I),'commands':arr(ref('EditorCommand')),'input_ids':arr(UUID)},['id','version','file','pages','commands','input_ids']),
        'BillingOffer':obj({'id':S,'version':S,'kind':S,'plan':nullable_string,'name':S,'price_xtr':I,'currency':S,'period_seconds':{'type':['integer','null']},'quantities':{'type':'object','additionalProperties':I},'sandbox':B,'checkout_enabled':B},['id','version','kind','name','price_xtr','currency','quantities','sandbox','checkout_enabled']),
        'Invoice':obj({'id':UUID,'offer_id':S,'kind':S,'plan':nullable_string,'status':S,'amount_xtr':I,'currency':S,'sandbox':B,'invoice_url':nullable_string,'created_at':DT,'expires_at':DT,'paid_at':{'type':['string','null'],'format':'date-time'}},['id','offer_id','kind','status','amount_xtr','currency','sandbox','expires_at']),
        'Payment':obj({'id':UUID,'invoice_id':UUID,'kind':S,'plan':nullable_string,'amount_xtr':I,'currency':S,'sandbox':B,'occurred_at':DT,'is_renewal':B,'refunded_xtr':I,'status':S,'refund_status':nullable_string},['id','invoice_id','kind','amount_xtr','currency','sandbox','occurred_at','is_renewal','refunded_xtr','status']),
        'Subscription':obj({'id':UUID,'plan':S,'status':S,'renewal_enabled':B,'current_period_end':DT,'active_until':{'type':['string','null'],'format':'date-time'},'scheduled_plan':nullable_string,'scheduled_at':{'type':['string','null'],'format':'date-time'},'requires_new_checkout':B,'sandbox':B},['id','plan','status','renewal_enabled','current_period_end','sandbox']),
        'SubscriptionState':obj({'plan':S,'subscription':{'anyOf':[ref('Subscription'),{'type':'null'}]},'sandbox':B,'checkout_enabled':B},['plan','subscription','sandbox','checkout_enabled']),
        'Refund':obj({'id':UUID,'payment_id':UUID,'status':S,'amount_xtr':I,'confirmed_at':{'type':['string','null'],'format':'date-time'},'error_code':nullable_string},['id','payment_id','status','amount_xtr']),
        'SupportMessage':obj({'id':UUID,'message':S,'sender':{'enum':['customer','staff']},'created_at':DT},['id','message','sender','created_at']),
        'BotDelivery':obj({'id':UUID,'status':S,'attempts':I},['id','status','attempts']),
    })
    models['GenerationMaterial']=obj({'key':S,'title':S,'sections':arr(ref('GenerationSection')),'questions':arr(ref('GenerationQuestion')),'citations':arr(obj({'asset_id':UUID,'page':I,'quote':S}))},['key','title','sections','questions'])
    models['GenerationContent']['properties']['materials']=arr(ref('GenerationMaterial'))
    models['GenerationContent']['properties']['citations']['items']['properties']['quote']=S
    for field in ('transcription_ready','transcription_reviewed'):models['GenerationDraft']['properties'][field]={'type':'boolean','readOnly':True}
    models['GenerationDraft']['properties']['revision']=obj({'source_draft_id':UUID,'source_version':I,'selected_section_ids':arr(S),'base_content':ref('GenerationContent')})
    # Typed command alternatives exactly match the processor's strict allowlist.
    from processors.editor import FIELDS
    commands=[]
    for kind,fields in FIELDS.items():
        fieldspec={name:S for name in fields}
        fieldspec['type']={'const':kind}
        for name in ('page','input_index','image_index'):
            if name in fields:fieldspec[name]={'type':'integer','minimum':0 if name=='image_index' else 1}
        for name in ('x','y','width','height','font_size','stroke_width'):
            if name in fields:fieldspec[name]={'type':'number','minimum':0}
        if 'points' in fields:fieldspec['points']={'type':'array','minItems':2,'maxItems':200,'items':{'type':'array','minItems':2,'maxItems':2,'items':{'type':'number','minimum':0}}}
        command=obj(fieldspec,sorted(fields-{'font_size','color','stroke_width'}));command['additionalProperties']=False;commands.append(command)
    models['EditorCommand']={'oneOf':commands,'description':'PDF points from displayed top-left, pages start at 1, image indices start at 0. Image input indices reference extra uploaded assets. Redaction requires explicit rasterization acknowledgement and a separate export.'}
    studio_feature=obj({'id':S,'name':S,'surface':S,'eligible':B,'requires_provider':B,'parameter_schema':O,'locales':arr(S)},['id','name','eligible'])
    template=obj({'id':S,'name':S,'locales':arr(S),'kind':S,'style':O,'eligible':B},['id','name'])
    models['BatchQuote']=obj({'id':UUID,'quote_id':UUID,'feature_id':S,'groups':arr(obj({'index':I,'feature_id':S,'input_ids':arr(UUID),'normalized_parameters':O,'meters':{'type':'object','additionalProperties':I}})),'meters':arr(obj({'meter':S,'amount':I})),'affordable':B,'available_balances':ref('Balances'),'expires_at':DT,'max_children':I,'reservation_mode':S,'template':obj({'id':UUID,'name':S,'version':I},['id','name','version']),'limitations':arr(S)},['id','quote_id','feature_id','groups','meters','affordable','expires_at','reservation_mode','limitations'])
    models['BatchRun']=obj({'id':UUID,'quote_id':UUID,'feature_id':S,'status':S,'created_at':DT,'completed_at':{'type':['string','null'],'format':'date-time'},'children':arr(obj({'index':I,'feature_id':S,'status':S,'job':{'anyOf':[ref('Job'),{'type':'null'}]},'error':{'anyOf':[ref('Error'),{'type':'null'}]}})),'jobs':arr(ref('Job')),'meters':{'type':'object','additionalProperties':I},'settled_meters':{'type':'object','additionalProperties':I},'counts':{'type':'object','additionalProperties':I}},['id','quote_id','feature_id','status','children','jobs','meters','settled_meters','counts'])
    endpoint('/health','get','getHealth',obj({'status':S,'service':S,'api_version':S},['status','service','api_version']),public=True)
    endpoint('/batches/quotes','post','quoteBatch',ref('BatchQuote'),{'oneOf':[obj({'feature_id':{'enum':['batch.convert','batch.compress','batch.image_sets']},'groups':arr(obj({'feature_id':S,'input_ids':arr(UUID),'parameters':O},['input_ids']))},['feature_id','groups']),obj({'feature_id':{'const':'editor.batch_forms'},'template_id':UUID,'template_version':I,'input_ids':arr(UUID)},['feature_id','template_id','template_version','input_ids'])]},code='201')
    endpoint('/batches','get','listBatches',obj({'results':arr(ref('BatchRun'))},['results']))
    endpoint('/batches','post','submitBatch',ref('BatchRun'),obj({'quote_id':UUID},['quote_id']),code='201',description='Child jobs reserve when started and settle separately. Successful children stay charged when other children fail; no parent task charge.')
    endpoint('/batches/{id}','get','getBatch',ref('BatchRun'))
    endpoint('/batches/{id}','post','continueBatch',ref('BatchRun'),obj({}))
    endpoint('/batches/{id}/resume','post','resumeBatch',ref('BatchRun'),obj({}))
    endpoint('/batches/{id}/resume','get','getBatchResumeStatus',ref('BatchRun'))
    endpoint('/studio/config','get','getStudioConfig',obj({'provider':obj({'id':S,'mode':S,'label':S,'configured':B},['id','mode','label','configured']),'features':arr(studio_feature),'generation_features':arr(studio_feature),'templates':arr(template),'limits':O},['provider','features','generation_features','templates','limits']))
    create=obj({'feature_id':S,'title':S,'prompt':S,'source_text':S,'source_ids':arr(UUID),'output_locale':{'enum':['en','uz','ru']},'output_format':{'enum':['pdf','pptx']},'options':O},['feature_id'])
    endpoint('/generation/drafts','get','listGenerationDrafts',obj({'results':arr(ref('GenerationDraft'))},['results']))
    endpoint('/generation/drafts','post','createGenerationDraft',ref('GenerationDraft'),create,code='201',description='Uncharged encrypted authoring draft. Local authoring is not an AI response. Provider generation happens only after a confirmed quote.')
    endpoint('/generation/drafts/{id}','get','getGenerationDraft',ref('GenerationDraft'))
    endpoint('/generation/drafts/{id}','patch','updateGenerationDraft',ref('GenerationDraft'),obj({'version':I,'title':S,'prompt':S,'source_text':S,'source_ids':arr(UUID),'output_locale':{'enum':['en','uz','ru']},'output_format':{'enum':['pdf','pptx']},'options':O,'content':ref('GenerationContent'),'outline':arr(obj({'id':S,'title':S,'body':S,'notes':S,**SLIDE_FIELDS}))},['version']))
    endpoint('/generation/drafts/{id}','delete','deleteGenerationDraft',deleted)
    endpoint('/generation/drafts/{id}/outline','post','reviewGenerationOutline',ref('GenerationDraft'),version)
    endpoint('/generation/drafts/{id}/quote','post','quoteGenerationDraft',ref('Quote'),obj({'version':I,'stage':{'enum':['document','outline']}},['version']),code='201')
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
    endpoint('/editor/documents','get','listEditorDocuments',obj({'results':arr(ref('EditorDocument'))},['results']))
    endpoint('/editor/documents','post','createEditorDocument',ref('EditorDocument'),obj({'file_id':UUID},['file_id']),code='201')
    endpoint('/editor/documents/{id}','get','getEditorDocument',ref('EditorDocument'))
    endpoint('/editor/documents/{id}','patch','updateEditorDocument',ref('EditorDocument'),obj({'version':I,'commands':arr(ref('EditorCommand')),'input_ids':arr(UUID)},['version','commands']))
    endpoint('/editor/documents/{id}','delete','deleteEditorDocument',deleted)
    endpoint('/editor/documents/{id}/quote','post','quoteEditorDocument',ref('Quote'),obj({'version':I,'accept_rasterization':B},['version']),code='201')
    endpoint('/billing/offers','get','getBillingOffers',obj({'offers':arr(ref('BillingOffer')),'sandbox':B,'checkout_enabled':B,'currency':S,'billing_mode':{'enum':['sandbox','live','disabled']}},['offers','sandbox','checkout_enabled','currency','billing_mode']))
    endpoint('/billing/invoices','get','getInvoices',obj({'results':arr(ref('Invoice'))},['results']))
    endpoint('/billing/invoices','post','createInvoice',ref('Invoice'),obj({'offer_id':S},['offer_id']),code='201')
    endpoint('/billing/invoices/{id}','get','getInvoice',ref('Invoice'))
    endpoint('/billing/invoices/{id}','delete','cancelInvoice',ref('Invoice'))
    endpoint('/billing/invoices/{id}/sandbox-pay','post','sandboxPayInvoice',obj({'payment':ref('Payment'),'invoice':ref('Invoice'),'subscription':{'anyOf':[ref('Subscription'),{'type':'null'}]},'plan':S,'sandbox':B,'created':B}),obj({}),description='Local payment simulator restricted to test accounts and explicit sandbox enablement.')
    endpoint('/billing/subscription','get','getSubscription',ref('SubscriptionState'))
    for suffix,operation in [('cancel-renewal','cancelRenewal'),('resume-renewal','resumeRenewal')]:
        endpoint('/billing/subscription/'+suffix,'post',operation,ref('SubscriptionState'),obj({}))
    endpoint('/billing/subscription/schedule-plan-change','post','schedulePlanChange',ref('SubscriptionState'),obj({'plan':{'enum':['free','plus','premium']}},['plan']))
    endpoint('/billing/subscription/sandbox-renew','post','sandboxRenewSubscription',obj({'payment':ref('Payment'),'subscription':ref('Subscription'),'sandbox':B,'created':B}),obj({}))
    endpoint('/billing/transactions','get','getTransactions',obj({'results':arr(ref('Payment'))},['results']))
    endpoint('/billing/payments/{id}/sandbox-refund','post','sandboxRefundPayment',ref('Refund'),obj({'reason':S}))
    endpoint('/billing/payments/{id}/refund-request','post','requestPaymentRefund',obj({'ticket_id':UUID,'status':S},['ticket_id','status']),obj({'reason':{'type':'string','minLength':3,'maxLength':4000}},['reason']))
    endpoint('/referrals','get','getReferrals',obj({'code':S,'url':nullable_string,'rewards_count':I,'pending_count':I,'awarded_credits':I,'monthly_cap':I,'expires_in_days':I,'qualification':S,'sandbox':B}))
    endpoint('/referrals','post','claimReferral',obj({'id':I,'status':S}),obj({'code':S},['code']))
    message_list=obj({'ticket_id':UUID,'status':S,'messages':arr(ref('SupportMessage'))},['ticket_id','status','messages'])
    endpoint('/support/{id}/messages','get','getSupportMessages',message_list)
    endpoint('/support/{id}/messages','post','replySupportTicket',message_list,obj({'message':S},['message']))
    endpoint('/artifacts/{id}/deliver','post','deliverArtifactToTelegram',ref('BotDelivery'),obj({}),code='201')
    local_asset=obj({'id':UUID,'name':S,'mime_type':S,'size_bytes':I,'download_url':S,'preview_url':nullable_string,'expires_at':DT})
    local_message=obj({'id':UUID,'direction':S,'text':S,'buttons':arr(arr(obj({'label':S,'callback_data':nullable_string,'url':nullable_string}))),'asset':{'anyOf':[local_asset,{'type':'null'}]},'created_at':DT},['id','direction','text','buttons','asset','created_at'])
    local_history=obj({'sandbox':B,'transport':S,'messages':arr(local_message)},['sandbox','transport','messages'])
    for method,operation in [('get','getLocalTelegram'),('post','sendLocalTelegram'),('delete','clearLocalTelegram')]:
        endpoint('/telegram/local/messages',method,operation,local_history,obj({'text':S,'callback_data':S}) if method=='post' else None,description='Offline bot transport, only sandbox test accounts. No Telegram network message is sent.')
    paths['/telegram/local/messages']['post']['requestBody']['content']['multipart/form-data']={'schema':obj({'file':{'type':'string','format':'binary'}},['file'])}
    for path in ['/batches','/generation/drafts/{id}/generate','/workflows/{id}/run','/education/projects/{id}/practice','/billing/invoices','/billing/subscription/sandbox-renew','/artifacts/{id}/deliver']:
        paths[path]['post']['parameters'].append({'name':'Idempotency-Key','in':'header','required':True,'schema':{'type':'string','minLength':8,'maxLength':128}})


def schema():
    models={
        'User':obj({'id':UUID,'telegram_user_id':{'type':['string','null']},'email':{'type':['string','null']},'email_verified':B,'google_email':{'type':['string','null']},'login_methods':obj({'email':B,'google':B,'telegram':B},['email','google','telegram']),'display_name':S,'username':S,'locale':{'enum':['en','uz','ru']},'mode':{'enum':['general','student','school','teacher']},'time_zone':S,'timezone':S,'preferences':{'type':'object'},'plan':{'enum':['free','plus','premium']},'is_test':B,'created_at':DT},['id','display_name','locale','plan']),
        'Session':obj({'authenticated':B,'user':{'anyOf':[ref('User'),{'type':'null'}]},'csrf_token':S,'development_login_enabled':B},['authenticated','user','csrf_token','development_login_enabled']),
        'MeterBalance':obj({'limit':I,'used':I,'reserved':I,'remaining':I},['limit','used','reserved','remaining']),
        'Balances':obj({name:ref('MeterBalance') for name in ('file_tasks','file_page_units','ai_credits')},['file_tasks','file_page_units','ai_credits']),
        'Usage':obj({'plan':S,'draft':B,'meters':ref('Balances'),'daily':obj({'limit':{'type':['integer','null']},'used':I,'reserved':I,'remaining':{'type':['integer','null']},'resets_at':DT}), 'resets_at':DT},['plan','meters','daily','resets_at']),
        'Asset':obj({'id':UUID,'name':S,'size_bytes':I,'page_count':I,'mime_type':S,'state':S,'expires_at':DT,'encrypted':B,'preview_url':{'type':['string','null']},'password_secret_id':{'type':['string','null']}},['id','name','size_bytes','page_count','mime_type','state','expires_at']),
        'Artifact':obj({'id':UUID,'name':S,'size_bytes':I,'page_count':I,'mime_type':S,'state':S,'expires_at':DT,'role':S,'preview_url':{'type':['string','null']},'download_url':S},['id','name','size_bytes','mime_type','download_url']),
        'Error':obj({'code':S,'message_key':S,'message':S,'message_params':{'type':'object'},'request_id':S,'field_errors':{'type':'object'},'retryable':B},['code','message_key','message','retryable']),
        'Feature':obj({'id':S,'name':S,'label_key':S,'category':S,'release':S,'enabled':B,'eligible':B,'plans':{'type':'object'},'parameters':{'type':'object'},'capabilities':{'type':'object'},'environment':S},['id','name','enabled','eligible','parameters']),
        'Plan':obj({'id':S,'name':S,'price_xtr':{'type':['integer','null']},'limits':{'type':'object'},'checkout_enabled':B,'features':arr(S)},['id','name','price_xtr','limits','checkout_enabled']),
        'Quote':obj({'id':UUID,'quote_id':UUID,'quote_version':S,'feature_id':S,'plan_version_id':S,'tariff_version_id':S,'input_fingerprints':arr(obj({'id':UUID,'sha256':S})), 'normalized_parameters':{'type':'object'},'meters':arr(obj({'meter':S,'amount':I},['meter','amount'])),'available_balances':ref('Balances'),'affordable':B,'expires_at':DT,'output_expectations':{'type':'object'},'limitations':arr(S),'plan':S},['id','quote_id','feature_id','meters','affordable','expires_at','available_balances']),
        'Job':obj({'id':UUID,'feature_id':S,'status':{'enum':['queued','running','finalizing','succeeded','failed','canceled','expired','no_op']},'created_at':DT,'started_at':{'type':['string','null'],'format':'date-time'},'completed_at':{'type':['string','null'],'format':'date-time'},'input_files':arr(ref('Asset')),'artifacts':arr(ref('Artifact')),'meters':{'type':'object','additionalProperties':I},'settled_meters':{'type':'object','additionalProperties':I},'error':{'anyOf':[ref('Error'),{'type':'null'}]},'warnings':arr(S),'parameters':{'type':'object'},'origin_channel':S},['id','feature_id','status','created_at','input_files','artifacts','meters','settled_meters','error','warnings']),
        'Ticket':obj({'id':UUID,'subject':S,'message':S,'status':S,'category':S,'created_at':DT},['id','subject','status','created_at']),
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
    endpoint('/plans','get','getPlans',obj({'plans':arr(ref('Plan')),'draft':B,'checkout_enabled':B,'currency':S,'period_seconds':I},['plans','draft','checkout_enabled']),public=True)
    endpoint('/usage','get','getUsage',ref('Usage'))
    endpoint('/files/uploads','post','uploadFile',ref('Asset'),code='201')
    paths['/files/uploads']['post']['requestBody']={'required':True,'content':{'multipart/form-data':{'schema':obj({'file':{'type':'string','format':'binary'},'password':{'type':'string','format':'password'}},['file'])}}}
    endpoint('/files/{id}','get','getFile',ref('Asset'))
    endpoint('/files/{id}','delete','deleteFile',ref('Asset'))
    endpoint('/secrets','post','createPasswordHandle',obj({'id':UUID,'expires_at':DT},['id','expires_at']),obj({'password':{'type':'string','format':'password','minLength':1,'maxLength':256}},['password']),code='201')
    endpoint('/quotes','post','createQuote',ref('Quote'),obj({'feature_id':S,'input_ids':arr(UUID),'parameters':{'type':'object'},'secret_id':UUID},['feature_id','input_ids']),code='201')
    endpoint('/jobs','post','submitJob',ref('Job'),obj({'quote_id':UUID},['quote_id']),code='201',description='Returns 200 on identical retry. Same key with changed quote returns 409.')
    endpoint('/jobs','get','listJobs',obj({'results':arr(ref('Job')),'count':I},['results','count']))
    endpoint('/jobs/{id}','get','getJob',ref('Job'))
    endpoint('/jobs/{id}/cancel','post','cancelJob',ref('Job'),obj({}))
    for path,operation in [('/files/{id}/download','downloadFile'),('/artifacts/{id}/download','downloadArtifact')]:
        endpoint(path,'get',operation,S)
        paths[path]['get']['responses']['200']={'description':'Private file, attachment; no-store','content':{'application/octet-stream':{'schema':{'type':'string','format':'binary'}}}}
    for path,operation in [('/files/{id}/preview','previewFile'),('/artifacts/{id}/preview','previewArtifact')]:
        endpoint(path,'get',operation,S)
        paths[path]['get']['parameters'].append({'name':'page','in':'query','schema':{'type':'integer','minimum':1,'default':1}})
        paths[path]['get']['responses']['200']={'description':'Private single-page PNG preview, no task charge','content':{'image/png':{'schema':{'type':'string','format':'binary'}}}}
    endpoint('/support','post','createSupportTicket',ref('Ticket'),obj({'subject':S,'message':S,'category':S,'job_id':UUID},['subject','message']),code='201')
    endpoint('/support','get','listSupportTickets',obj({'results':arr(ref('Ticket'))},['results']))
    for path,operation in [('/billing/subscription','getSubscription'),('/billing/transactions','getTransactions'),('/billing/invoices','getInvoices')]:
        endpoint(path,'get',operation,obj({'checkout_enabled':B,'plan':S,'transactions':arr({'type':'object'}),'subscription':{'type':'null'},'reason':S}))
    extend_schema(models,endpoint,paths)
    return {'openapi':'3.1.0','info':{'title':'PDF Master public API','version':'1.1.0','description':'Local development beta. Studio, editor, document jobs and sandbox commerce are covered. Staff operations are excluded. Live providers require server configuration.'},'servers':[{'url':'/api/v1'}],'paths':paths,'components':{'securitySchemes':{'customerSession':{'type':'apiKey','in':'cookie','name':'pdfmaster_session'}},'schemas':models}}

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
