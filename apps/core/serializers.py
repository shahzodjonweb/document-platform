from django.utils import timezone
from .errors import DomainError, error_data
from .models import FileAsset
from .services import quote_affordable

def account_data(a):
    from apps.commerce.services import refresh_account_entitlement
    refresh_account_entitlement(a)
    return {'id':str(a.id),'telegram_user_id':str(a.telegram_user_id) if a.telegram_user_id is not None else None,'email':a.email,'email_verified':bool(a.email_verified_at),'google_email':a.google_email or None,'login_methods':{'email':bool(a.password_hash and a.email_verified_at),'google':bool(a.google_sub),'telegram':a.telegram_user_id is not None},'display_name':a.display_name,'username':a.username,'locale':a.locale,'mode':a.mode,'time_zone':a.time_zone,'timezone':a.time_zone,'preferences':a.preferences,'plan':a.plan,'is_test':a.is_test,'created_at':a.created_at}

def asset_data(a):
    state = 'expired' if a.expires_at<=timezone.now() else a.state
    return {'id':str(a.id),'name':a.name,'size_bytes':a.size_bytes,'page_count':a.page_count,'mime_type':a.mime_type,'state':state,'expires_at':a.expires_at,'page_sizes':a.metadata.get('page_sizes',[]),'form_fields':a.metadata.get('form_fields',[]),'image_counts':a.metadata.get('image_counts',[]),'encrypted':bool(a.metadata.get('encrypted')),'password_secret_id':a.metadata.get('password_secret_id'),'preview_url':f'/api/v1/files/{a.id}/preview' if a.mime_type=='application/pdf' and (not a.metadata.get('encrypted') or a.metadata.get('password_secret_id')) else None}

def quote_data(q):
    affordable,usage=quote_affordable(q.account,q)
    return {'id':str(q.id),'quote_id':str(q.id),'quote_version':'1','feature_id':q.feature_id,'plan_version_id':q.policy['version'],'tariff_version_id':q.policy['tariff_version'],'input_fingerprints':q.input_fingerprints,'normalized_parameters':q.parameters,'meters':[{'meter':m,'amount':v} for m,v in q.meters.items() if v],'available_balances':usage['meters'],'affordable':affordable,'expires_at':q.expires_at,'output_expectations':{'retention_hours':24},'limitations':['development_beta'],'plan':q.policy['plan']}

def job_data(job):
    files={str(a.pk):asset_data(a) for a in FileAsset.objects.filter(account=job.account,id__in=job.input_ids)}
    artifacts=[]
    for artifact in job.artifacts.select_related('file').all():
        row=asset_data(artifact.file)
        row.update({'id':str(artifact.pk),'role':artifact.role,'download_url':f'/api/v1/artifacts/{artifact.pk}/download','preview_url':f'/api/v1/artifacts/{artifact.pk}/preview' if artifact.file.mime_type=='application/pdf' and not artifact.file.metadata.get('encrypted') else None})
        artifacts.append(row)
    return {'id':str(job.id),'feature_id':job.feature_id,'status':job.status,'created_at':job.created_at,'started_at':job.started_at,'completed_at':job.completed_at,'input_files':[files[i] for i in job.input_ids if i in files],'artifacts':artifacts,'meters':job.meters,'settled_meters':job.settled_meters,'error':error_data(DomainError(job.error_code),job.account.locale) if job.error_code else None,'warnings':job.warnings,'parameters':job.parameters,'origin_channel':job.origin_channel}
