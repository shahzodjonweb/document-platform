import json
import uuid
from functools import wraps
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse, FileResponse
from django.middleware.csrf import get_token, rotate_token
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from .models import Account, FileAsset, Job, Quote, Artifact, SupportTicket, WebhookReceipt
from .errors import DomainError, error_data
from .identity import resolve_account, exchange_miniapp, create_challenge, get_bound_challenge, exchange_challenge
from .policy import catalog, SEED, FEATURES, usage_snapshot
from .services import upload_file, create_quote, submit_job, execute_job, cancel_job, storage_path, record_event
from .serializers import account_data, asset_data, quote_data, job_data

def current_account(request):
    account_id=request.session.get('customer_account_id')
    return Account.objects.filter(pk=account_id,deletion_requested_at__isnull=True).first() if account_id else None

def api(methods=('GET',), auth=True):
    def decorate(fn):
        @wraps(fn)
        def wrapped(request,*args,**kwargs):
            account=None
            try:
                if request.method not in methods: raise DomainError('method_not_allowed',405)
                account=current_account(request)
                if auth and account is None: raise DomainError('authentication_required',401)
                request.account=account
                value=fn(request,*args,**kwargs)
                return value if hasattr(value,'status_code') else JsonResponse(value)
            except DomainError as exc:
                return JsonResponse({'error':error_data(exc,account.locale if account else 'en',getattr(request,'request_id',''))},status=exc.status)
            except (ValueError,TypeError,KeyError,json.JSONDecodeError,ValidationError):
                return JsonResponse({'error':error_data(DomainError('invalid_request'),'en',getattr(request,'request_id',''))},status=400)
        return wrapped
    return decorate

def body(request):
    if request.content_type!='application/json': raise DomainError('invalid_content_type',415)
    if len(request.body)>32768: raise DomainError('invalid_request',413)
    value=json.loads(request.body or '{}')
    if not isinstance(value,dict): raise DomainError('invalid_request')
    return value

def throttle(request,key,limit=20):
    identity=request.META.get('REMOTE_ADDR','unknown')
    cache_key=f'rate:{key}:{identity}'
    count=cache.get(cache_key,0)
    if count>=limit: raise DomainError('rate_limited',429,retryable=True)
    cache.set(cache_key,count+1,60)

def sign_in(request,account):
    request.session.cycle_key()
    request.session['customer_account_id']=str(account.id)
    rotate_token(request)
    return {'authenticated':True,'user':account_data(account),'csrf_token':get_token(request),'development_login_enabled':settings.DEVELOPMENT_LOGIN_ENABLED}

@api(('GET','DELETE'),auth=False)
def session(request):
    if request.method=='DELETE':
        request.session.pop('customer_account_id',None)
        request.session.cycle_key()
        rotate_token(request)
        return {'authenticated':False,'user':None,'csrf_token':get_token(request)}
    return {'authenticated':bool(request.account),'user':account_data(request.account) if request.account else None,'csrf_token':get_token(request),'development_login_enabled':settings.DEVELOPMENT_LOGIN_ENABLED}

@api(('POST',),auth=False)
def dev_login(request):
    if not settings.DEBUG or not settings.DEVELOPMENT_LOGIN_ENABLED or request.META.get('REMOTE_ADDR') not in ('127.0.0.1','::1'): raise DomainError('not_found',404)
    data=body(request)
    account=resolve_account({'id':900000001,'first_name':'Local explorer','username':'local_demo','language_code':data.get('locale','en')},'web',True)
    return sign_in(request,account)

@api(('POST',),auth=False)
def miniapp_login(request):
    throttle(request,'miniapp')
    return sign_in(request,exchange_miniapp(body(request).get('init_data',body(request).get('initData',''))))

@api(('POST',),auth=False)
def challenges(request):
    throttle(request,'challenge',10)
    body(request)
    challenge,token,verifier=create_challenge(request.META.get('HTTP_USER_AGENT','Unknown browser'))
    response=JsonResponse({'id':str(challenge.pk),'status':'pending','expires_at':challenge.expires_at,'telegram_url':f'https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start=login_{token}','browser_hint':challenge.browser_hint},status=201)
    response.set_cookie('pdfmaster_challenge',verifier,max_age=300,httponly=True,secure=not settings.DEBUG,samesite='Lax',path='/api/v1/auth/browser/')
    return response

@api(auth=False)
def challenge_status(request,challenge_id):
    challenge=get_bound_challenge(challenge_id,request.COOKIES.get('pdfmaster_challenge',''))
    return {'id':str(challenge.pk),'status':'approved' if challenge.approved_at else 'pending','expires_at':challenge.expires_at}

@api(('POST',),auth=False)
def challenge_exchange(request,challenge_id):
    throttle(request,'exchange')
    response=JsonResponse(sign_in(request,exchange_challenge(challenge_id,request.COOKIES.get('pdfmaster_challenge',''))))
    response.delete_cookie('pdfmaster_challenge',path='/api/v1/auth/browser/')
    return response

@api(('GET','PATCH','DELETE'))
def me(request):
    a=request.account
    if request.method=='DELETE':
        a.deletion_requested_at=timezone.now()
        a.save(update_fields=['deletion_requested_at'])
        FileAsset.objects.filter(account=a).update(state='revoked',expires_at=timezone.now())
        request.session.pop('customer_account_id',None)
        return {'status':'deletion_requested'}
    if request.method=='PATCH':
        data=body(request)
        allowed={'locale','mode','time_zone','timezone','preferences'}
        if set(data)-allowed: raise DomainError('invalid_profile_fields')
        if 'locale' in data:
            if data['locale'] not in ('en','uz','ru'): raise DomainError('invalid_locale')
            a.locale=data['locale']
        if 'mode' in data:
            if data['mode'] not in ('general','student','school','teacher'): raise DomainError('invalid_mode')
            a.mode=data['mode']
        tz=data.get('time_zone',data.get('timezone'))
        if tz:
            try: ZoneInfo(tz)
            except (ZoneInfoNotFoundError,ValueError): raise DomainError('invalid_timezone') from None
            a.time_zone=tz
        if 'preferences' in data:
            preferences=data['preferences']
            if not isinstance(preferences,dict) or set(preferences)-{'theme','paper_size','notifications','output_locale'}: raise DomainError('invalid_profile_fields')
            a.preferences=preferences
        a.save(update_fields=['locale','mode','time_zone','preferences'])
    return account_data(a)

@api(auth=False)
def catalog_view(request): return {'features':catalog(request.account),'draft':True,'release':'development_beta'}

@api(auth=False)
def plans(request):
    released={f['id'] for f in catalog(request.account)}
    return {'draft':True,'checkout_enabled':False,'currency':'XTR','period_seconds':SEED['period_seconds'],'plans':[{'id':key,'name':key.title(),'price_xtr':limits['price_xtr'],'limits':limits,'checkout_enabled':False,'features':[fid for fid in released if FEATURES[fid]['plans'][key] not in ('none','excluded','not_included','unavailable')]} for key,limits in SEED['plans'].items()]}

@api()
def usage(request): return usage_snapshot(request.account)

@api(('POST',))
def uploads(request):
    throttle(request,'uploads',30)
    if 'file' not in request.FILES: raise DomainError('file_required')
    return JsonResponse(asset_data(upload_file(request.account,request.FILES['file'],password=request.POST.get('password'))),status=201)

@api(('GET','DELETE'))
def file_detail(request,asset_id):
    asset=FileAsset.objects.filter(pk=asset_id,account=request.account).first()
    if not asset: raise DomainError('not_found',404)
    if request.method=='DELETE':
        if any(str(asset.id) in j.input_ids for j in Job.objects.filter(account=request.account,status__in=('queued','running','finalizing'))): raise DomainError('file_in_use',409)
        asset.state='revoked'
        asset.expires_at=timezone.now()
        asset.save(update_fields=['state','expires_at'])
        storage_path(asset.object_key).unlink(missing_ok=True)
        for preview in asset.page_previews.select_related('file'):
            preview.file.state='revoked';preview.file.expires_at=timezone.now()
            preview.file.save(update_fields=['state','expires_at'])
            storage_path(preview.file.object_key).unlink(missing_ok=True)
    return asset_data(asset)

def download_asset(request,asset):
    if asset.state!='ready' or asset.expires_at<=timezone.now(): raise DomainError('file_expired',410)
    path=storage_path(asset.object_key)
    if not path.is_file(): raise DomainError('file_unavailable',404)
    response=FileResponse(path.open('rb'),as_attachment=True,filename=asset.name,content_type=asset.mime_type)
    response['Cache-Control']='private, no-store'
    response['Content-Security-Policy']="sandbox; default-src 'none'"
    return response

@api()
def file_download(request,asset_id):
    asset=FileAsset.objects.filter(pk=asset_id,account=request.account).first()
    if not asset: raise DomainError('not_found',404)
    return download_asset(request,asset)

@api(('POST',))
def quotes(request):
    throttle(request,'quotes',60)
    data=body(request)
    return JsonResponse(quote_data(create_quote(request.account,data.get('feature_id'),data.get('input_ids'),data.get('parameters',{}),data.get('secret_id'))),status=201)

@api(('GET','POST'))
def jobs(request):
    if request.method=='POST':
        data=body(request)
        job,created=submit_job(request.account,data.get('quote_id'),request.headers.get('Idempotency-Key',''))
        if settings.LOCAL_SYNC_JOBS and created: job=execute_job(job.id)
        return JsonResponse(job_data(job),status=201 if created else 200)
    query=Job.objects.filter(account=request.account).order_by('-created_at')
    return {'results':[job_data(j) for j in query[:100]],'count':query.count()}

@api()
def job_detail(request,job_id):
    job=Job.objects.filter(pk=job_id,account=request.account).first()
    if not job: raise DomainError('not_found',404)
    return job_data(job)

@api(('POST',))
def job_cancel(request,job_id): return job_data(cancel_job(request.account,job_id))

@api()
def artifact_download(request,artifact_id):
    artifact=Artifact.objects.select_related('file','job').filter(pk=artifact_id,account=request.account).first()
    if not artifact: raise DomainError('not_found',404)
    response=download_asset(request,artifact.file)
    record_event(request.account,'artifact.downloaded',job=artifact.job)
    return response

@api(('GET','POST'))
def support(request):
    if request.method=='POST':
        throttle(request,'support',10)
        data=body(request)
        subject=str(data.get('subject','')).strip()
        message=str(data.get('message','')).strip()
        if not subject or len(subject)>160 or not message or len(message)>4000: raise DomainError('invalid_support_ticket')
        job=None
        if data.get('job_id'):
            job=Job.objects.filter(pk=data['job_id'],account=request.account).first()
            if not job: raise DomainError('not_found',404)
        ticket=SupportTicket.objects.create(account=request.account,job=job,subject=subject,message=message,category=str(data.get('category','general'))[:24])
        return JsonResponse({'id':str(ticket.id),'subject':ticket.subject,'status':ticket.status,'created_at':ticket.created_at},status=201)
    return {'results':[{'id':str(t.id),'subject':t.subject,'message':t.message,'status':t.status,'category':t.category,'created_at':t.created_at} for t in SupportTicket.objects.filter(account=request.account).order_by('-created_at')[:100]]}

@api(('GET','POST'))
def billing(request):
    if request.method=='POST': raise DomainError('checkout_disabled',409)
    return {'checkout_enabled':False,'plan':request.account.plan,'transactions':[],'subscription':None,'reason':'production_prices_not_configured'}

@api(auth=False)
def health(request): return {'status':'ok','service':'pdfmaster-platform','api_version':'v1'}

@csrf_exempt
@api(('POST',),auth=False)
def telegram_webhook(request):
    import hmac
    if not settings.TELEGRAM_WEBHOOK_SECRET or not hmac.compare_digest(request.headers.get('X-Telegram-Bot-Api-Secret-Token',''),settings.TELEGRAM_WEBHOOK_SECRET): raise DomainError('authentication_required',401)
    data=body(request)
    update_id=data.get('update_id')
    if not isinstance(update_id,int): raise DomainError('invalid_request')
    _,created=WebhookReceipt.objects.get_or_create(update_id=update_id,defaults={'payload':data})
    return {'ok':True,'accepted':created}

def csrf_failure(request,reason=''):
    return JsonResponse({'error':error_data(DomainError('csrf_failed',403),request_id=getattr(request,'request_id',''))},status=403)

@api(('POST',))
def secret_create(request):
    from .secrets import create_secret
    data=body(request)
    handle=create_secret(request.account,data.get('password'))
    return JsonResponse({'id':str(handle.pk),'expires_at':handle.expires_at},status=201)

@api()
def file_preview(request,asset_id):
    from .previews import preview_asset
    throttle(request,'previews',30)
    page=int(request.GET.get('page','1'))
    preview=preview_asset(request.account,asset_id,page,request.GET.get('secret_id'))
    response=download_asset(request,preview)
    response['Content-Disposition']='inline; filename="preview.png"'
    return response

@api()
def artifact_preview(request,artifact_id):
    artifact=Artifact.objects.filter(pk=artifact_id,account=request.account).first()
    if not artifact: raise DomainError('not_found',404)
    return file_preview(request,artifact.file_id)
