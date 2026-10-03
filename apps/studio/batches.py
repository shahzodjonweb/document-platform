"""Batch parents never consume allowances: each ordinary child settles once."""
import hashlib
import json
import uuid
from datetime import timedelta
from types import SimpleNamespace
from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.urls import path
from django.utils import timezone
from apps.core.errors import DomainError,error_data
from apps.core.models import Account,Quote,Job
from apps.core.policy import plan_limits,POLICY_VERSION,FEATURES
from apps.core.services import create_quote,submit_job,execute_job,owned_assets,validate_inputs,quote_affordable,engine_inspect,storage_path,TERMINAL
from apps.core.serializers import job_data
from apps.core.views import api,body,throttle
from .batch_models import BatchQuote,BatchRun,BatchItem

CHILDREN={
    'batch.convert':{'convert.word_to_pdf','convert.pptx_to_pdf','convert.pdf_to_docx','convert.pdf_to_xlsx','pdf.to_images'},
    'batch.compress':{'pdf.compress'},
    'batch.image_sets':{'pdf.images_to_pdf'},
    'editor.batch_forms':{'editor.fill_forms'},
}
DONE=('succeeded','partial','failed')

def require_batch(account,feature_id):
    caps=plan_limits(account)
    if not settings.ENABLE_BETA_TOOLS or feature_id not in CHILDREN:raise DomainError('feature_unavailable',409)
    if FEATURES[feature_id]['plans'][account.plan] in ('none','excluded','not_included','unavailable'):raise DomainError('feature_not_in_plan',403)
    return caps

def validate_form_template(content):
    """Saved form data cannot smuggle other editor commands into a batch."""
    from processors import normalize_parameters,ProcessorError
    if not isinstance(content,dict) or set(content)!={'commands'}:raise DomainError('invalid_parameters')
    try:normalized=normalize_parameters('editor.fill_forms',content)
    except ProcessorError as exc:raise DomainError(exc.code) from None
    commands=normalized['commands']
    if len({command['field'] for command in commands})!=len(commands):raise DomainError('invalid_editor_command')
    if any(any(ord(c)<32 for c in command['field']) or any(ord(c)<32 and c not in '\n\t' for c in command['value']) for command in commands):raise DomainError('invalid_editor_command')
    return {'commands':commands}

def _template_digest(template):
    return hashlib.sha256(json.dumps(template.definition,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

def _form_groups(account,template_id,template_version,input_ids):
    from .models import SavedDefinition
    if type(template_version) is not int or template_version<1:raise DomainError('version_conflict',409)
    try:identifier=uuid.UUID(str(template_id))
    except (TypeError,ValueError):raise DomainError('not_found',404) from None
    template=SavedDefinition.objects.select_for_update().filter(pk=identifier,account=account,kind='form').first()
    if not template:raise DomainError('not_found',404)
    if template.version!=template_version:raise DomainError('version_conflict',409)
    parameters=validate_form_template(template.definition.get('content'))
    groups=[]
    for asset in owned_assets(account,input_ids):
        if asset.mime_type!='application/pdf':raise DomainError('unsupported_file')
        if asset.metadata.get('encrypted'):raise DomainError('unlock_first')
        metadata=asset.metadata
        if 'form_fields' not in metadata:
            # Result files may predate richer inspection metadata. Never parse
            # untrusted PDF bytes inside the web process to discover fields.
            metadata=engine_inspect(storage_path(asset.object_key))
        fields={f['name']:f['type'] for f in metadata.get('form_fields',[])}
        for command in parameters['commands']:
            if command['field'] not in fields:raise DomainError('form_field_not_found')
            if fields[command['field']]!='/Tx':raise DomainError('unsupported_form_field')
        groups.append({'feature_id':'editor.fill_forms','input_ids':[str(asset.id)],'parameters':parameters})
    snapshot={'id':str(template.id),'name':template.name,'version':template.version,'sha256':_template_digest(template)}
    return groups,snapshot

def _verify_form_template(account,snapshot):
    from .models import SavedDefinition
    template=SavedDefinition.objects.select_for_update().filter(pk=snapshot['id'],account=account,kind='form').first()
    if not template or template.version!=snapshot['version'] or _template_digest(template)!=snapshot['sha256']:raise DomainError('version_conflict',409)

def _quotes(row):
    values={str(q.id):q for q in Quote.objects.filter(account=row.account,id__in=row.child_quote_ids)}
    if len(values)!=len(row.child_quote_ids):raise DomainError('file_unavailable',404)
    return [values[key] for key in row.child_quote_ids]

@transaction.atomic
def create_batch_quote(account,feature_id,groups=None,*,template_id=None,template_version=None,input_ids=None):
    caps=require_batch(account,feature_id)
    from apps.core.channel_gate import require as require_channels
    require_channels(account)
    template=None
    if feature_id=='editor.batch_forms':
        if groups is not None:raise DomainError('invalid_parameters')
        if not isinstance(input_ids,list) or not 1<=len(input_ids)<=caps['batch_files']:raise DomainError('batch_limit',413)
        groups,template=_form_groups(account,template_id,template_version,input_ids)
    if not isinstance(groups,list) or not 1<=len(groups)<=caps['batch_files']:raise DomainError('batch_limit',413)
    children=[];total_bytes=0;total_pages=0
    for group in groups:
        if not isinstance(group,dict):raise DomainError('invalid_parameters')
        child_id=group.get('feature_id')
        if child_id is None and feature_id!='batch.convert':child_id=next(iter(CHILDREN[feature_id]))
        if not isinstance(child_id,str) or child_id not in CHILDREN[feature_id]:raise DomainError('invalid_batch_tool')
        assets=owned_assets(account,group.get('input_ids'))
        total_bytes+=sum(a.size_bytes for a in assets);total_pages+=sum(a.page_count for a in assets)
        if total_bytes>caps['max_aggregate_input_mib']*1024*1024:raise DomainError('aggregate_size_exceeded',413)
        if total_pages>caps['max_pages_per_job']:raise DomainError('page_limit_exceeded',413)
        children.append(create_quote(account,child_id,group['input_ids'],group.get('parameters',{})))
    meters={meter:sum(q.meters.get(meter,0) for q in children) for meter in ('file_tasks','file_page_units','ai_credits')}
    policy={'plan':account.plan,'version':POLICY_VERSION,'max_children':caps['batch_files'],'aggregate_bytes':total_bytes,'aggregate_pages':total_pages}
    if template:policy['template']=template
    return BatchQuote.objects.create(account=account,feature_id=feature_id,child_quote_ids=[str(q.id) for q in children],meters=meters,policy=policy,expires_at=min(q.expires_at for q in children))

def quote_data(row):
    affordable,usage=quote_affordable(row.account,SimpleNamespace(meters=row.meters))
    groups=[{'index':i,'feature_id':q.feature_id,'input_ids':q.input_ids,'normalized_parameters':q.parameters,'meters':q.meters} for i,q in enumerate(_quotes(row))]
    result={'id':str(row.id),'quote_id':str(row.id),'feature_id':row.feature_id,'groups':groups,'meters':[{'meter':k,'amount':v} for k,v in row.meters.items() if v],'affordable':affordable,'available_balances':usage['meters'],'expires_at':row.expires_at,'max_children':row.policy['max_children'],'reservation_mode':'per_child','limitations':['Children reserve allowances when they start. Only successful children are charged. Unstarted children can expire or fail if allowances change.']}
    if 'template' in row.policy:
        result['template']={k:row.policy['template'][k] for k in ('id','name','version')}
        result['limitations'].append('Reusable form batches fill existing text fields only. Each PDF must contain every saved field. Oversized values fail uncharged; successful outputs retain interactive form fields.')
    return result

@transaction.atomic
def submit_batch(account,quote_id,key):
    if not isinstance(key,str) or not 8<=len(key)<=128:raise DomainError('idempotency_key_required')
    account=Account.objects.select_for_update().get(pk=account.pk)
    digest=hashlib.sha256(str(quote_id).encode()).hexdigest()
    prior=BatchRun.objects.filter(account=account,idempotency_key=key).first()
    if prior:
        if prior.request_hash!=digest:raise DomainError('idempotency_conflict',409)
        return prior,False
    row=BatchQuote.objects.select_for_update().filter(pk=quote_id,account=account).first()
    if not row:raise DomainError('not_found',404)
    require_batch(account,row.feature_id)
    if BatchRun.objects.filter(quote=row).exists():raise DomainError('quote_already_submitted',409)
    if row.expires_at<=timezone.now():raise DomainError('quote_expired',409)
    if row.policy['plan']!=account.plan or row.policy['version']!=POLICY_VERSION:raise DomainError('quote_policy_changed',409)
    if 'template' in row.policy:_verify_form_template(account,row.policy['template'])
    children=_quotes(row)
    if Job.objects.filter(quote__in=children).exists():raise DomainError('quote_already_submitted',409)
    for child in children:
        assets=validate_inputs(account,child.feature_id,child.input_ids)
        if [{'id':str(a.id),'sha256':a.sha256} for a in assets]!=child.input_fingerprints:raise DomainError('file_changed',409)
    if not quote_affordable(account,SimpleNamespace(meters=row.meters))[0]:raise DomainError('quota_exceeded',409)
    run=BatchRun.objects.create(account=account,quote=row,idempotency_key=key,request_hash=digest)
    BatchItem.objects.bulk_create([BatchItem(run=run,index=i,quote=q) for i,q in enumerate(children)])
    return run,True

@transaction.atomic
def claim(run_id):
    run=BatchRun.objects.select_for_update().select_related('account','quote').get(pk=run_id)
    now=timezone.now()
    if run.status in DONE or run.lease_until and run.lease_until>now:return None
    run.status='running';run.lease_token=uuid.uuid4();run.lease_until=now+timedelta(minutes=3)
    run.save(update_fields=['status','lease_token','lease_until'])
    return run

def execute_batch(run_id):
    run=claim(run_id)
    if run is None:return BatchRun.objects.get(pk=run_id)
    for item in run.children.select_related('quote','job').order_by('index'):
        if item.status in TERMINAL:continue
        if not BatchRun.objects.filter(pk=run.id,lease_token=run.lease_token).update(lease_until=timezone.now()+timedelta(minutes=3)):break
        try:
            if item.job_id is None:
                job,_=submit_job(run.account,item.quote_id,f'batch:{run.id}:{item.index}')
                item.job=job;item.status=job.status;item.save(update_fields=['job','status'])
            else:job=item.job
            if job.status not in TERMINAL:job=execute_job(job.id)
            item.status=job.status;item.error_code=job.error_code;item.save(update_fields=['status','error_code'])
            if job.status not in TERMINAL:break
        except DomainError as exc:
            # A busy account is transient. Keep the persisted parent for the worker.
            if exc.code=='concurrency_limit':break
            item.status='failed';item.error_code=exc.code;item.save(update_fields=['status','error_code'])
    states=list(run.children.values_list('status',flat=True))
    values={'lease_until':None,'lease_token':None}
    if all(state in TERMINAL for state in states):
        successes=sum(state in ('succeeded','no_op') for state in states)
        values.update(status='succeeded' if successes==len(states) else 'partial' if successes else 'failed',completed_at=timezone.now())
    else:values['status']='queued'
    BatchRun.objects.filter(pk=run.id,lease_token=run.lease_token).update(**values)
    return BatchRun.objects.get(pk=run.id)

def drain_batches(limit=10):
    from django.db.models import Q
    ids=BatchRun.objects.filter(status__in=('queued','running')).filter(Q(lease_until__isnull=True)|Q(lease_until__lte=timezone.now())).order_by('created_at').values_list('id',flat=True)[:limit]
    for identifier in list(ids):execute_batch(identifier)

def run_data(run):
    rows=[];settled={meter:0 for meter in run.quote.meters};counts={}
    for item in run.children.select_related('quote','job','job__account').order_by('index'):
        status=item.job.status if item.job_id else item.status
        data=job_data(item.job) if item.job_id else None
        counts[status]=counts.get(status,0)+1
        if data:
            for k,v in data['settled_meters'].items():settled[k]=settled.get(k,0)+v
        rows.append({'index':item.index,'feature_id':item.quote.feature_id,'status':status,'job':data,'error':data['error'] if data else error_data(DomainError(item.error_code),run.account.locale) if item.error_code else None})
    return {'id':str(run.id),'quote_id':str(run.quote_id),'feature_id':run.quote.feature_id,'status':run.status,'created_at':run.created_at,'completed_at':run.completed_at,'children':rows,'jobs':[r['job'] for r in rows if r['job']],'meters':run.quote.meters,'settled_meters':settled,'counts':counts}

@api(('POST',))
def quotes(request):
    throttle(request,'batch_quotes',20)
    data=body(request)
    return JsonResponse(quote_data(create_batch_quote(request.account,data.get('feature_id'),data.get('groups'),template_id=data.get('template_id'),template_version=data.get('template_version'),input_ids=data.get('input_ids'))),status=201)

@api(('GET','POST'))
def batches(request):
    if request.method=='GET':return {'results':[run_data(r) for r in BatchRun.objects.filter(account=request.account).select_related('quote','account').order_by('-created_at')[:50]]}
    throttle(request,'batch_submit',20)
    run,created=submit_batch(request.account,body(request).get('quote_id'),request.headers.get('Idempotency-Key',''))
    if settings.LOCAL_SYNC_JOBS:run=execute_batch(run.id)
    return JsonResponse(run_data(run),status=201 if created else 200)

@api(('GET','POST'))
def detail(request,pk):
    run=BatchRun.objects.filter(account=request.account,pk=pk).select_related('quote','account').first()
    if not run:raise DomainError('not_found',404)
    if request.method=='POST' and settings.LOCAL_SYNC_JOBS:run=execute_batch(run.id)
    return run_data(run)

urlpatterns=[path('batches/quotes',quotes),path('batches',batches),path('batches/<uuid:pk>',detail),path('batches/<uuid:pk>/resume',detail)]
