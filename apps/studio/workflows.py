"""Frozen workflow confirmations with resumable, idempotent ordinary child jobs."""
import hashlib
import json
import uuid
from datetime import timedelta
from django.core import signing
from django.db import transaction
from django.utils import timezone
from apps.core.errors import DomainError
from apps.core.models import Account,Job
from apps.core.policy import POLICY_VERSION,plan_limits,require_feature
from apps.core.serializers import job_data
from apps.core.services import owned_assets,validate_inputs,create_quote,submit_job,execute_job,TERMINAL
from processors import normalize_parameters,ProcessorError
from processors.engine import parse_pages
from .models import SavedDefinition,WorkflowRun

SALT='pdfmaster.workflow.confirmation.v1'
METERS=('file_tasks','file_page_units','ai_credits')
KINDS={'convert.word_to_pdf':'docx','convert.pptx_to_pdf':'pptx','convert.pdf_to_docx':'pdf','convert.pdf_to_xlsx':'pdf'}

def _access(account):
    if account.plan not in ('plus','premium'):raise DomainError('feature_not_in_plan',403)

def _row(account,pk):
    row=SavedDefinition.objects.filter(account=account,id=pk,kind='workflow').first()
    if not row:raise DomainError('not_found',404)
    return row

def quote(account,pk,ids):
    _access(account);row=_row(account,pk)
    assets=owned_assets(account,ids)
    # Sequential tools consume one file. Archive/text/table outputs must be last.
    if len(assets)!=1:raise DomainError('input_count_exceeded')
    if assets[0].metadata.get('encrypted'):raise DomainError('unlock_first')
    kind=assets[0].metadata.get('kind');pages=assets[0].page_count
    steps=[];meters={k:0 for k in METERS}
    for index,step in enumerate(row.definition['steps']):
        fid=step['feature_id'];require_feature(account,fid)
        if index==0:validate_inputs(account,fid,[str(assets[0].id)])
        expected=KINDS.get(fid,'pdf')
        if fid.startswith('ocr.'):
            if kind not in ('pdf','image'):raise DomainError('unsupported_file')
        elif kind!=expected:raise DomainError('unsupported_file')
        try:parameters=normalize_parameters(fid,step.get('parameters',{}),[{'kind':kind,'page_count':pages}])
        except ProcessorError as error:raise DomainError(error.code) from None
        rate=1 if fid.startswith('ocr.') else 2 if fid in ('convert.pdf_to_docx','convert.pdf_to_xlsx') else 0
        amount={'file_tasks':0 if rate else 1,'file_page_units':0 if rate else pages,'ai_credits':pages*rate}
        steps.append({'feature_id':fid,'parameters':parameters,'meters':amount})
        for meter in METERS:meters[meter]+=amount[meter]
        if fid=='pdf.extract_pages':pages=len(parse_pages(parameters['pages'],pages))
        elif fid=='pdf.delete_pages':pages-=len(parse_pages(parameters['pages'],pages))
        elif fid=='convert.pdf_to_docx':kind='docx';pages=plan_limits(account)['max_pages_per_job']
        elif fid=='convert.pdf_to_xlsx':kind='xlsx'
        elif fid=='pdf.to_images':kind='archive'
        elif fid=='ocr.extract_text':kind='text'
        elif fid.startswith('ocr.'):
            pages=len(parse_pages(parameters['pages'],pages));kind='pdf'
        else:kind='pdf'
    payload={'workflow_id':str(row.id),'account_id':str(account.id),'version':row.version,'plan':account.plan,'policy_version':POLICY_VERSION,'input_ids':[str(a.id) for a in assets],'fingerprints':[{'id':str(a.id),'sha256':a.sha256} for a in assets],'steps':steps,'meters':meters}
    return {'workflow_id':str(row.id),'version':row.version,'input_ids':payload['input_ids'],'steps':steps,'meters':[{'meter':k,'amount':v} for k,v in meters.items() if v],'confirmation_required':True,'confirmation_token':signing.dumps(payload,salt=SALT,compress=True),'expires_at':timezone.now()+timedelta(minutes=10),'limitations':['Each step uses the preceding result; failures stop the remaining steps. Successful steps remain charged.','After editable Word conversion, following steps use the plan page maximum as a conservative ceiling.']}

def data(run):
    jobs={str(j.id):j for j in Job.objects.filter(id__in=run.job_ids,account=run.account).select_related('account')}
    return {'id':str(run.id),'status':run.status,'jobs':[job_data(jobs[key]) for key in run.job_ids if key in jobs]}

def start(account,pk,request,key):
    if not isinstance(key,str) or not 8<=len(key)<=128:raise DomainError('idempotency_key_required')
    if not isinstance(request,dict):raise DomainError('invalid_parameters')
    digest=hashlib.sha256(json.dumps({'workflow_id':str(pk),'request':request},sort_keys=True).encode()).hexdigest()
    with transaction.atomic():
        Account.objects.select_for_update().get(pk=account.pk)
        run=WorkflowRun.objects.select_for_update().filter(account=account,idempotency_key=key).first()
        if run:
            if run.request_hash!=digest:raise DomainError('idempotency_conflict',409)
            if run.status in ('succeeded','partial','failed') or run.lease_until and run.lease_until>timezone.now():return run,None
        else:
            _access(account);row=_row(account,pk)
            try:payload=signing.loads(request.get('confirmation_token',''),salt=SALT,max_age=600)
            except signing.SignatureExpired:raise DomainError('quote_expired',409) from None
            except (signing.BadSignature,TypeError):raise DomainError('confirmation_required',409) from None
            if request.get('confirmed') is not True or payload.get('account_id')!=str(account.id) or payload.get('workflow_id')!=str(row.id) or request.get('input_ids')!=payload.get('input_ids'):raise DomainError('confirmation_required',409)
            if request.get('version')!=row.version or payload.get('version')!=row.version:raise DomainError('version_conflict',409)
            if payload.get('plan')!=account.plan or payload.get('policy_version')!=POLICY_VERSION:raise DomainError('quote_policy_changed',409)
            assets=owned_assets(account,payload['input_ids'])
            if payload['fingerprints']!=[{'id':str(a.id),'sha256':a.sha256} for a in assets]:raise DomainError('file_changed',409)
            run=WorkflowRun.objects.create(account=account,definition=row,idempotency_key=key,request_hash=digest,snapshot=payload)
        token=uuid.uuid4();run.lease_token=token;run.lease_until=timezone.now()+timedelta(minutes=3);run.save(update_fields=['lease_token','lease_until'])
    return run,token

def execute(run,token):
    if token is None:return run
    ids=run.snapshot['input_ids'];successful=0
    try:
        for index,step in enumerate(run.snapshot['steps']):
            if not WorkflowRun.objects.filter(pk=run.id,lease_token=token).update(lease_until=timezone.now()+timedelta(minutes=3)):return WorkflowRun.objects.get(pk=run.id)
            key=f'workflow:{run.id}:{index}'
            job=Job.objects.filter(account=run.account,idempotency_key=key).first()
            if job is None:
                q=create_quote(run.account,step['feature_id'],ids,step['parameters'])
                if any(q.meters.get(m,0)>step['meters'].get(m,0) for m in METERS):raise DomainError('quote_exceeded',409)
                job,_=submit_job(run.account,q.id,key)
            if str(job.id) not in run.job_ids:
                run.job_ids.append(str(job.id));WorkflowRun.objects.filter(pk=run.id,lease_token=token).update(job_ids=run.job_ids)
            if job.status not in TERMINAL:job=execute_job(job.id)
            if job.status not in TERMINAL:
                WorkflowRun.objects.filter(pk=run.id,lease_token=token).update(lease_until=None,lease_token=None)
                return WorkflowRun.objects.get(pk=run.id)
            if job.status not in ('succeeded','no_op'):raise DomainError(job.error_code or 'processing_failed')
            successful+=1
            if job.status=='succeeded':ids=[str(a.file_id) for a in job.artifacts.all()]
        status='succeeded'
    except DomainError:status='partial' if successful else 'failed'
    except Exception:
        WorkflowRun.objects.filter(pk=run.id,lease_token=token).update(lease_until=None,lease_token=None)
        raise
    WorkflowRun.objects.filter(pk=run.id,lease_token=token).update(status=status,lease_until=None,lease_token=None)
    return WorkflowRun.objects.get(pk=run.id)
