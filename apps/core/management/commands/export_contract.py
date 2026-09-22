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

def schema():
    models={
        'User':obj({'id':UUID,'telegram_user_id':S,'display_name':S,'username':S,'locale':{'enum':['en','uz','ru']},'mode':{'enum':['general','student','school','teacher']},'time_zone':S,'timezone':S,'preferences':{'type':'object'},'plan':{'enum':['free','plus','premium']},'is_test':B,'created_at':DT},['id','display_name','locale','plan']),
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
    endpoint('/auth/telegram/miniapp','post','exchangeMiniApp',ref('Session'),obj({'init_data':S},['init_data']),True)
    challenge=obj({'id':UUID,'status':S,'expires_at':DT,'telegram_url':S,'browser_hint':S})
    endpoint('/auth/browser/challenges','post','createLoginChallenge',challenge,obj({}),True,'201')
    endpoint('/auth/browser/challenges/{id}','get','getLoginChallenge',challenge,public=True)
    endpoint('/auth/browser/challenges/{id}/exchange','post','exchangeLoginChallenge',ref('Session'),obj({}),True)
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
    return {'openapi':'3.1.0','info':{'title':'PDF Master public API','version':'1.0.0','description':'Development beta. Staff operations are intentionally excluded. Paid checkout remains disabled.'},'servers':[{'url':'/api/v1'}],'paths':paths,'components':{'securitySchemes':{'customerSession':{'type':'apiKey','in':'cookie','name':'pdfmaster_session'}},'schemas':models}}

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
