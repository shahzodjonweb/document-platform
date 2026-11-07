from operations.integrations import editor_flags, telegram_config
from operations.middleware import known_zone
import json
import logging
import re
import secrets
import uuid
from functools import wraps
from django.conf import settings
from django.core.cache import caches
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.http import JsonResponse, FileResponse
from django.middleware.csrf import get_token, rotate_token
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from .models import Account, FileAsset, Job, Quote, Artifact, WebhookReceipt
from .errors import DomainError, error_data
from .antibot import require_web_verification
from .identity import resolve_account, exchange_miniapp, create_challenge, get_bound_challenge, exchange_challenge
from .policy import catalog, SEED, FEATURES, usage_snapshot
from .services import upload_file, create_quote, submit_job, execute_job, cancel_job, record_event
from .serializers import account_data, asset_data, quote_data, job_data

def current_account(request):
    account_id=request.session.get('customer_account_id')
    account=Account.objects.filter(pk=account_id,deletion_requested_at__isnull=True).first() if account_id else None
    if account and request.session.get('customer_auth_version', 0) != account.auth_version:
        request.session.pop('customer_account_id', None)
        account = None
    if account:
        from apps.commerce.services import refresh_account_entitlement
        refresh_account_entitlement(account)
    return account

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

def body(request,limit=32768,too_large='invalid_request'):
    if request.content_type!='application/json': raise DomainError('invalid_content_type',415)
    if len(request.body)>limit: raise DomainError(too_large,413)
    value=json.loads(request.body or '{}')
    if not isinstance(value,dict): raise DomainError('invalid_request')
    return value

def throttle(request,key,limit=20):
    if key in ('miniapp','challenge','exchange'):
        from .auth_views import limit as auth_limit
        return auth_limit(request, key, limit)
    # Never REMOTE_ADDR: that is the gateway, for everyone at once.
    account=getattr(request,'account',None)
    if account: identity=f'account:{account.pk}'
    else:
        identity=request.session.get('rate_identity')
        if not identity: identity=request.session['rate_identity']=secrets.token_urlsafe(32)
        identity=f'session:{identity}'
    count_request(key,identity,limit)

def account_limit(account,key,limit):
    """At most `limit` requests a minute for one account, as `throttle` counts them."""
    count_request(key,f'account:{account.pk}',limit)

def count_request(key,identity,limit):
    """One more request in a minute counted from the first, on the store every process shares.

    A fixed window: the count expires a minute after it began, whatever comes
    after. Set again on every request, the expiry moved on with each, and a
    tab asking every two seconds was refused after two minutes of waiting.
    incr keeps the expiry (locmem and redis alike).

    With that store away the same limit is counted in the database for this
    call, slower but still shared: a Redis outage refuses nobody it should not.
    """
    cache_key=f'rate:{key}:{identity}'
    try:
        store=caches['limits']
        store.add(cache_key,0,60)
        try:count=store.incr(cache_key)
        except ValueError:
            # The minute ended between add and incr: this request begins the next.
            store.add(cache_key,0,60);count=store.incr(cache_key)
        # Redis checks the key, then counts: a key expiring between the two comes back with no expiry at all.
        if count==1:store.touch(cache_key,60)
    except Exception:
        logging.getLogger(__name__).warning('Limiter store unavailable; counting %s in the database',key)
        from .customer_auth import auth_limit
        try:auth_limit(f'rate:{key}',identity,limit,60)
        except DatabaseError:logging.getLogger(__name__).exception('Limiter could not count %s',key)
        return
    if count>limit:raise DomainError('rate_limited',429,retryable=True)

def sign_in(request,account):
    request.session.cycle_key()
    request.session['customer_account_id']=str(account.id)
    request.session['customer_auth_version']=account.auth_version
    request.session.pop('google_browser', None)
    rotate_token(request)
    return {'authenticated':True,'user':account_data(account),'csrf_token':get_token(request),'development_login_enabled':settings.DEVELOPMENT_LOGIN_ENABLED}

@api(('GET','DELETE'),auth=False)
def session(request):
    if request.method=='DELETE':
        request.session.pop('customer_account_id',None)
        request.session.pop('google_browser',None)
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
    data=body(request)
    require_web_verification(request,data)
    return sign_in(request,exchange_miniapp(data.get('init_data',data.get('initData',''))))

@api(('POST',),auth=False)
def challenges(request):
    throttle(request,'challenge',10)
    data=body(request)
    require_web_verification(request,data)
    intent=data.get('intent','login')
    if intent not in ('login','link'): raise DomainError('invalid_request')
    if intent=='link' and not request.account: raise DomainError('authentication_required',401)
    if intent=='link' and request.account.telegram_user_id: raise DomainError('telegram_already_linked',409)
    challenge,token,verifier=create_challenge(request.META.get('HTTP_USER_AGENT','Unknown browser'), request.account if intent=='link' else None)
    response=JsonResponse({'id':str(challenge.pk),'status':'pending','expires_at':challenge.expires_at,'telegram_url':f'https://t.me/{telegram_config()['username']}?start=login_{token}','browser_hint':challenge.browser_hint},status=201)
    response.set_cookie('pdfmaster_challenge',verifier,max_age=300,httponly=True,secure=not settings.DEBUG,samesite='Lax',path='/api/v1/auth/browser/')
    return response

@api(auth=False)
def challenge_status(request,challenge_id):
    challenge=get_bound_challenge(challenge_id,request.COOKIES.get('pdfmaster_challenge',''))
    return {'id':str(challenge.pk),'status':'approved' if challenge.approved_at else 'pending','expires_at':challenge.expires_at}

@api(('POST',),auth=False)
def challenge_exchange(request,challenge_id):
    throttle(request,'exchange')
    response=JsonResponse(sign_in(request,exchange_challenge(challenge_id,request.COOKIES.get('pdfmaster_challenge',''),link_account=request.account)))
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
            if not known_zone(tz): raise DomainError('invalid_timezone')
            a.time_zone=tz
        if 'preferences' in data:
            preferences=data['preferences']
            if not isinstance(preferences,dict) or set(preferences)-{'theme','paper_size','notifications','output_locale','adult_assistance'}: raise DomainError('invalid_profile_fields')
            if not isinstance(preferences.get('adult_assistance',False),bool): raise DomainError('invalid_profile_fields')
            a.preferences=preferences
        a.save(update_fields=['locale','mode','time_zone','preferences'])
    return account_data(a)

@api(auth=False)
def catalog_view(request): return {'features':catalog(request.account),'draft':True,'release':'development_beta'}

@api(auth=False)
def plans(request):
    released={f['id'] for f in catalog(request.account)}
    # Administrator edits are what the platform enforces, so they are also what
    # the pricing page advertises; reading the seed here would misstate it.
    from .policy import limits_for_plan
    from apps.commerce.pricing import plan_price
    def row(key,limits):
        # `price_uzs` is the regular price and `discount` today's, worked out
        # once for every reader; `limits.price_uzs` stays the regular price
        # for readers written before discounts. The discount as the owner
        # typed it stays theirs: `discount` says what is on today, and an
        # expired or half-filled one is not for the public.
        offer=plan_price(key,limits)
        public={field:value for field,value in limits.items() if field not in ('discount_price_uzs','discount_until')}
        return {'id':key,'name':key.title(),'price_uzs':offer['regular'] if offer else None,'discount':offer['discount'] if offer else None,'limits':public,
                'features':[fid for fid in released if FEATURES[fid]['plans'][key] not in ('none','excluded','not_included','unavailable')]}
    return {'draft':True,'currency':'UZS','period_seconds':SEED['period_seconds'],'plans':[row(key,limits_for_plan(key)) for key in SEED['plans']]}

@api()
def usage(request): return usage_snapshot(request.account)

@api()
def channels(request):
    """The Telegram channels this account must join to use the services, if any."""
    from .channel_gate import status
    return status(request.account)

@api(('POST',))
def channels_check(request):
    """"I've joined": ask Telegram again instead of trusting the last answer."""
    from .channel_gate import status
    from .customer_auth import auth_limit
    auth_limit('channel-check', str(request.account.pk), 10, 60)
    return status(request.account, refresh=True)

@api(('POST',))
def uploads(request):
    throttle(request,'uploads',30)
    if 'file' not in request.FILES: raise DomainError('file_required')
    # `purpose` 'cv_source' is a file a CV is made from: it may carry links
    # (services.upload_file), and is queued for the reader at once. `cv_read`
    # says how its reading stands (apps/studio/cv/reads.py upload_state).
    purpose=request.POST.get('purpose','')
    asset=upload_file(request.account,request.FILES['file'],password=request.POST.get('password'),purpose=purpose)
    data=asset_data(asset)
    if purpose=='cv_source':
        from apps.studio.cv.reads import upload_state
        data['cv_read']=upload_state(asset)
    return JsonResponse(data,status=201)

@api(('GET','DELETE'))
def file_detail(request,asset_id):
    asset=FileAsset.objects.filter(pk=asset_id,account=request.account).first()
    if not asset: raise DomainError('not_found',404)
    if request.method=='DELETE':
        if any(str(asset.id) in j.input_ids for j in Job.objects.filter(account=request.account,status__in=('queued','running','finalizing'))): raise DomainError('file_in_use',409)
        asset.state='revoked'
        asset.expires_at=timezone.now()
        # Cleanup soon makes this row look like any file that ran out; the editor tells the two apart.
        asset.metadata['deleted_by_customer']=True
        asset.save(update_fields=['state','expires_at','metadata'])
        from . import storage
        storage.delete(asset.object_key)
        # What a CV's file gave goes with it.
        from apps.studio.models import CvSourceRead
        CvSourceRead.objects.filter(asset=asset).delete()
        for preview in asset.page_previews.select_related('file'):
            preview.file.state='revoked';preview.file.expires_at=timezone.now()
            preview.file.save(update_fields=['state','expires_at'])
            storage.delete(preview.file.object_key)
    return asset_data(asset)

# Eighteen digits pass every file there is; int() refuses a very long run of them.
BYTE_RANGE=re.compile(r'bytes=([0-9]{0,18})-([0-9]{0,18})',re.IGNORECASE)

def byte_range(header,size):
    """What a Range header asks of `size` bytes: (first,last), False when nothing there can
    answer it, None when the whole file does (ill-formed, another unit, several ranges)."""
    found=BYTE_RANGE.fullmatch(header.strip())
    if not found or not (found[1] or found[2]): return None
    if not found[1]:
        if not int(found[2]) or not size: return False
        return max(size-int(found[2]),0),size-1
    first=int(found[1]);last=int(found[2]) if found[2] else size-1
    if found[2] and last<first: return None
    return (first,min(last,size-1)) if first<size else False

def download_asset(request,asset,ranges=False):
    if asset.state!='ready' or asset.expires_at<=timezone.now(): raise DomainError('file_expired',410)
    from . import storage
    span=None
    # This answer carries no validator, so an If-Range never matches it: that asks for the whole file.
    if ranges and 'Range' in request.headers and 'If-Range' not in request.headers:
        size=storage.size(asset.object_key)
        if size is None: raise DomainError('file_unavailable',404)
        span=byte_range(request.headers['Range'],size)
        if span is False:
            response=JsonResponse({'error':error_data(DomainError('range_not_satisfiable',416),request.account.locale,getattr(request,'request_id',''))},status=416)
            response['Content-Range']=f'bytes */{size}'
            return response
    if span:
        source=storage.open_range(asset.object_key,*span)
        if not source: raise DomainError('file_unavailable',404)
        response=FileResponse(source,as_attachment=True,filename=asset.name,content_type=asset.mime_type,status=206)
        response['Content-Length']=span[1]-span[0]+1
        response['Content-Range']=f'bytes {span[0]}-{span[1]}/{size}'
    else:
        path=storage.local(asset.object_key)
        if not path.is_file(): raise DomainError('file_unavailable',404)
        response=FileResponse(path.open('rb'),as_attachment=True,filename=asset.name,content_type=asset.mime_type)
    if ranges: response['Accept-Ranges']='bytes'
    response['Cache-Control']='private, no-store'
    response['Content-Security-Policy']="sandbox; default-src 'none'"
    return response

@api()
def file_download(request,asset_id):
    asset=FileAsset.objects.filter(pk=asset_id,account=request.account).first()
    if not asset: raise DomainError('not_found',404)
    return download_asset(request,asset,ranges=True)

@api(('POST',))
def quotes(request):
    throttle(request,'quotes',60)
    data=body(request)
    # Once the new editor is on, a draft goes by a pointer to it (POST /editor/documents/{id}/quote), not by carrying
    # its marks here. Batches of forms call create_quote themselves and stay as they are.
    if str(data.get('feature_id')).startswith('editor.') and editor_flags()['editor_v2']: raise DomainError('feature_unavailable',409)
    return JsonResponse(quote_data(create_quote(request.account,data.get('feature_id'),data.get('input_ids'),data.get('parameters',{}),data.get('secret_id'))),status=201)

@api(('GET','POST'))
def jobs(request):
    if request.method=='POST':
        throttle(request,'jobs',60)
        data=body(request)
        to_chat=data.get('deliver_to_chat',False)
        if type(to_chat) is not bool: raise DomainError('invalid_request')
        job,created=submit_job(request.account,data.get('quote_id'),request.headers.get('Idempotency-Key',''),'mini_app' if to_chat else 'web')
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

@api(('GET',),auth=False)
def contacts(request):
    """Where customers reach a person: the support and the ads Telegram accounts, and the company's legal details."""
    from operations.integrations import company_details, contacts_config
    return {**contacts_config(), 'company': company_details()}

@api(auth=False)
def health(request): return {'status':'ok','service':'pdfmaster-platform','api_version':'v1'}

@csrf_exempt
@api(('POST',),auth=False)
def telegram_webhook(request):
    import hmac
    if not telegram_config()['webhook_secret'] or not hmac.compare_digest(request.headers.get('X-Telegram-Bot-Api-Secret-Token',''),telegram_config()['webhook_secret']): raise DomainError('authentication_required',401)
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

# A page already drawn, or asked after while it is being drawn: the viewer of a long file asks for many.
PREVIEWS_CACHED_PER_MINUTE=120
# A page to be drawn: a task in the editor lane.
PREVIEWS_UNCACHED_PER_MINUTE=10

def _lane_preview(request,asset_id,page):
    """With the deck editor on the API draws nothing: a page not drawn yet is the lane's, 202 {task_id}, and the client asks again."""
    from .previews import cached_preview
    from apps.studio import tasks
    secret_id=request.GET.get('secret_id')
    preview=cached_preview(request.account,asset_id,page,secret_id)
    task=None if preview else tasks.waiting_preview(request.account,asset_id,page)
    if preview or task:account_limit(request.account,'previews_cached',PREVIEWS_CACHED_PER_MINUTE)
    else:
        account_limit(request.account,'previews_uncached',PREVIEWS_UNCACHED_PER_MINUTE)
        task=tasks.enqueue(request.account,tasks.PREVIEW,{'asset_id':str(asset_id),'page':page,'secret_id':secret_id})
    return preview,task

@api()
def file_preview(request,asset_id):
    from .previews import preview_asset
    from operations.integrations import editor_flags
    if editor_flags()['deck_editor']:
        preview,task=_lane_preview(request,asset_id,int(request.GET.get('page','1')))
        if task:return JsonResponse({'task_id':str(task.pk)},status=202)
    else:
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
