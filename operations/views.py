import csv
import hashlib
import io
import json
import uuid
from datetime import timedelta
from functools import wraps
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import Group
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q,Case,When,IntegerField,Value
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.middleware.csrf import rotate_token
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.models import Account, Job, SupportTicket, UsageLedger
from .auth import COOKIE, allowed, audit, begin_session, development_access, require_staff, staff_user, verify_totp
from .i18n import CATALOGS, EN, get_locale
from .metrics import DEFINITIONS_VERSION, Filters, report, system_snapshot
from .models import AuditLog, LoginAttempt, StaffSession

PAGE_ROLES = {
    'overview':['Analyst','Operations','Finance'], 'users':['Support'],
    'analytics/acquisition':['Analyst'], 'analytics/engagement':['Analyst'],
    'analytics/features':['Analyst','Operations'], 'analytics/revenue':['Analyst','Finance'],
    'analytics/ai-usage':['Analyst','Operations','Finance'],
    'jobs':['Operations','Support'], 'plans':['Finance','Content manager'],
    'payments':['Finance'], 'support':['Support'], 'audit':[], 'system':['Operations'],
    'localization':['Content manager'], 'integrations':[], 'staff':[],
}
PAGE_KEYS = {'overview':'overview','users':'users','analytics/acquisition':'acquisition',
             'analytics/engagement':'engagement','analytics/features':'features','analytics/revenue':'revenue','analytics/ai-usage':'ai_usage',
             'jobs':'jobs','plans':'plans','payments':'payments','support':'support','audit':'audit','system':'system','localization':'localization'}
NAV = [('analytics',[('overview','overview','▦'),('analytics/acquisition','acquisition','↗'),('analytics/engagement','engagement','◷'),('analytics/features','features','◇'),('analytics/revenue','revenue','◉'),('analytics/ai-usage','ai_usage','✦')]),
       ('manage',[('users','users','♧'),('jobs','jobs','▤'),('support','support','♡'),('payments','payments','◎')]),
       ('platform',[('plans','plans','☷'),('localization','localization','◎'),('audit','audit','☑'),('system','system','⌁'),('integrations','integrations','⚙'),('staff','staff','♙')])]


def landing(user):
    return next(('/ops/'+path for path, roles in PAGE_ROLES.items() if allowed(user, roles)), '/ops/login')


def context(request, page='overview'):
    lang = get_locale(request)
    labels = CATALOGS[lang]
    user = getattr(request, 'ops_user', None)
    # Replace old repeated language values rather than appending another one.
    # Filters survive navigation; pagination restarts on the destination page.
    params = request.GET.copy()
    params['lang'] = lang
    params.pop('p', None)
    query = params.urlencode()
    nav = []
    if user:
        # Card transfers waiting for a decision show as a count beside Payments.
        waiting = 0
        if allowed(user, PAGE_ROLES['payments']):
            from apps.commerce.models import ManualPayment
            waiting = ManualPayment.objects.filter(status='submitted').count()
        for group, items in NAV:
            permitted = [{'path':path,'url':'/ops/'+path+'?'+query,'label':labels[key],'icon':icon,'active':page==path,'badge':waiting if path=='payments' else 0} for path,key,icon in items if allowed(user,PAGE_ROLES[path])]
            if permitted:
                nav.append({'label':labels[group],'items':permitted})
    params = request.GET.copy()
    locale_links = []
    for locale, name in [('en','English'),('uz','O‘zbekcha'),('ru','Русский')]:
        params['lang'] = locale
        locale_links.append({'label':name,'locale':locale,'url':'?'+params.urlencode()})
    return {'t':labels,'lang':lang,'query':query,'page':page,'page_key':PAGE_KEYS.get(page,page),
            'title':labels.get(PAGE_KEYS.get(page,page),page),'nav':nav,'staff':user,
            'staff_role':user.groups.first().name if user and user.groups.exists() else labels['staff'],
            'locale_links':locale_links,'dev_enabled':development_access(request),
            'can_inspect_jobs':bool(user and allowed(user,['Operations','Support']))}


def finish_render(request, template, data, status=200):
    response = render(request,template,data,status=status)
    response.set_cookie('ops_locale',data['lang'],max_age=31536000,samesite='Lax',secure=not settings.DEBUG,path='/ops/')
    response['Cache-Control']='no-store'
    response['X-Robots-Tag']='noindex, nofollow'
    return response


@require_http_methods(['GET','POST'])
def login(request):
    data=context(request)
    existing_user = staff_user(request)
    if existing_user:
        return redirect(landing(existing_user))
    if request.method=='POST':
        key=hashlib.sha256((request.META.get('REMOTE_ADDR','')+':'+request.POST.get('username','')[:150]).encode()).hexdigest()
        recent=LoginAttempt.objects.filter(key=key,created_at__gte=timezone.now()-timedelta(minutes=15))
        if recent.count() >= 5:
            data['error']=data['t']['rate_limit']
            return finish_render(request,'ops/login.html',data,429)
        LoginAttempt.objects.create(key=key)
        user=authenticate(request,username=request.POST.get('username','')[:150],password=request.POST.get('password','')[:1024])
        if user and user.is_active and user.is_staff and verify_totp(user,request.POST.get('code','')):
            recent.delete()
            rotate_token(request)
            audit(user,'staff.login',user.pk,'Password and authenticator verified')
            return begin_session(redirect(landing(user)),user)
        data['error']=data['t']['invalid_login']
    return finish_render(request,'ops/login.html',data)


@require_POST
def development_login(request):
    if not development_access(request):
        return HttpResponseForbidden('Local development only')
    user,created=get_user_model().objects.get_or_create(username='local-operator',defaults={'is_staff':True,'is_active':True})
    if created:
        user.set_unusable_password();user.save()
    if not user.is_staff or not user.is_active:
        return HttpResponseForbidden('Local staff disabled')
    user.groups.add(Group.objects.get_or_create(name='Administrator')[0])
    rotate_token(request)
    audit(user,'staff.development_login',user.pk,'Explicit loopback development sign-in')
    return begin_session(redirect('/ops/overview?environment=development'),user)


@require_POST
def logout(request):
    token=request.COOKIES.get(COOKIE,'')
    StaffSession.objects.filter(token_hash=hashlib.sha256(token.encode()).hexdigest()).delete()
    response=redirect('/ops/login'); response.delete_cookie(COOKIE,path='/ops/')
    return response


@require_staff('Analyst','Support','Operations','Finance','Content manager')
def page(request, section='overview'):
    if request.path in {'/ops','/ops/'}:
        return redirect(landing(request.ops_user))
    if section not in PAGE_ROLES or not allowed(request.ops_user,PAGE_ROLES[section]):
        return HttpResponseForbidden('Staff permission required')
    data=context(request,section)
    try:
        filters=Filters.from_request(request)
    except ValueError as error:
        return HttpResponseBadRequest(str(error))
    data['filters']=filters
    data['export_url']='/ops/export/'+ ('features' if section=='analytics/features' else 'jobs' if section=='jobs' else 'users')+'?'+data['query']
    data['can_export']=section in {'users','jobs','analytics/features'}
    if section in {'overview','analytics/acquisition','analytics/engagement','analytics/features'}:
        summary=report(filters)
        data.update(summary)
        data['metric_cards']=[
            {'label':data['t'][key],'value':summary['totals'][key], 'definition':data['t'][definition], 'suffix':'%' if key=='success_rate' else '', 'href':href}
            for key,definition,href in [('new_users','new_definition','/ops/analytics/acquisition'),('active_users','active_definition','/ops/analytics/engagement'),('completed','completed_definition','/ops/analytics/features'),('success_rate','success_definition','/ops/analytics/features')]
        ]
        data['recent_jobs']=filters.jobs().order_by('-created_at')[:6]
        data['chart_total']=summary['totals']['new_users']
    if section in {'analytics/acquisition','analytics/engagement'}:
        from .analytics_extra import engagement
        data['cohorts']=engagement(filters)
    if section in {'users','jobs','support','audit'}:
        if section=='users':
            rows=filters.accounts().order_by('-created_at')
            search=request.GET.get('q','').strip()[:150]
            if search:
                query=Q(id__icontains=search)|Q(username__icontains=search)
                if search.isdigit():query |= Q(telegram_user_id=int(search))
                rows=rows.filter(query)
        elif section=='jobs':
            rows=filters.jobs().select_related('account').order_by('-created_at')
            state=request.GET.get('status','')
            if state:rows=rows.filter(status=state)
        elif section=='support':
            rows=SupportTicket.objects.filter(account__in=filters.accounts(False),created_at__gte=filters.bounds[0],created_at__lt=filters.bounds[1]).select_related('account').annotate(priority_rank=Case(When(account__plan='premium',then=Value(0)),default=Value(1),output_field=IntegerField())).order_by('priority_rank','created_at')
        else:
            rows=AuditLog.objects.select_related('actor').filter(created_at__gte=filters.bounds[0],created_at__lt=filters.bounds[1]).order_by('-created_at')
        data['pagination']=Paginator(rows,30).get_page(request.GET.get('p'))
    if section=='plans':
        from . import plans as plan_settings
        defaults=plan_settings.seed()['plans'];changed=plan_settings.overrides()
        data['plan_rows']=[{'id':key,'title':key.capitalize(),'edited':bool(changed.get(key)),
                            **plan_settings.limits_for(key,value)} for key,value in defaults.items()]
        # Each field carries its seed value so an operator can see what they
        # are changing it from, and its bounds so the form refuses nonsense.
        data['plan_fields']=[{'name':name,'low':low,'high':high} for name,(low,high) in plan_settings.FIELDS.items()]
        data['plan_edit_rows']=[{'id':row['id'],'title':row['title'],'edited':row['edited'],
                                 'fields':[{'name':f['name'],'low':f['low'],'high':f['high'],
                                            'nullable':f['name'] in plan_settings.NULLABLE,
                                            'value':row.get(f['name']),'seed':defaults[row['id']].get(f['name'])}
                                           for f in data['plan_fields'] if f['name'] in defaults[row['id']]]}
                               for row in data['plan_rows']]
        data['can_edit_plans']=allowed(request.ops_user,['Finance','Content manager'])
    if section=='system':data['system_cards']=[{'label':data['t'][key],'value':value} for key,value in system_snapshot(filters).items()]
    if section=='localization':data['locale_rows']=[{'id':key,'count':len(value),'coverage':'100%'} for key,value in CATALOGS.items()]
    data['now']=timezone.now()
    return finish_render(request,'ops/page.html',data)


@require_staff('Support')
def user_detail(request, pk):
    from apps.core.models import FileAsset
    from apps.core.policy import limits_for_plan,usage_snapshot
    from apps.commerce.services import active_period,staff_plan
    account=get_object_or_404(Account,pk=pk)
    data=context(request,'users');data.update({'account':account,'detail_type':'user','recent_jobs':account.jobs.order_by('-created_at')[:20],
        'ledger':UsageLedger.objects.filter(account=account).order_by('-created_at')[:50], 'grants':account.usage_grants.order_by('-valid_from')[:20]})
    data['can_grant']=allowed(request.ops_user,[])
    data['grant_key']=str(uuid.uuid4())
    # What the allowance actually is right now, so a grant is an informed one
    # rather than a number typed into an empty box.
    snapshot=usage_snapshot(account)['meters']
    # Amounts staff actually reach for, so a top-up is one tap rather than a
    # guess typed into an empty box.
    presets={'file_tasks':(10,50,100),'file_page_units':(100,500,1000),'ai_credits':(100,500,2000)}
    data['balances']=[{'meter':meter,'label':data['t'][label],'presets':presets[meter],**snapshot[meter]}
                      for meter,label in (('file_tasks','tasks'),('file_page_units','pages'),('ai_credits','credits'))]
    data['plan_options']=['free','plus','premium']
    data['staff_plan']=staff_plan(account)
    period=active_period(account)
    data['paid_plan']=period.plan if period else ''
    data['plan_limits']=[{'label':key.replace('_',' '),'value':value} for key,value in limits_for_plan(account.plan).items()]
    # Customer documents, newest first. Opening one is a separate audited act.
    data['files']=FileAsset.objects.filter(account=account).order_by('-created_at')[:50]
    data['can_open_files']=allowed(request.ops_user,['Support','Operations'])
    audit(request.ops_user,'account.metadata_view',pk,'Staff inspected account metadata')
    return finish_render(request,'ops/detail.html',data)


@require_staff('Operations','Support')
def job_detail(request, pk):
    job=get_object_or_404(Job.objects.select_related('account'),pk=pk)
    data=context(request,'jobs');data['can_cancel']=allowed(request.ops_user,['Operations']) and job.status=='queued';data.update({'job':job,'detail_type':'job','ledger':UsageLedger.objects.filter(job=job).order_by('created_at')})
    return finish_render(request,'ops/detail.html',data)


@require_staff('Support')
@require_http_methods(['GET','POST'])
def support_detail(request, pk):
    ticket=get_object_or_404(SupportTicket.objects.select_related('account'),pk=pk)
    data=context(request,'support');data.update({'ticket':ticket,'detail_type':'support'})
    if request.method=='POST':
        reason=request.POST.get('reason','').strip()
        if not 5 <= len(reason) <= 1000:
            data['error']=data['t']['reason_required']
        else:
            reply=request.POST.get('reply','').strip()
            if len(reply)>4000:
                data['error']={'en':'Replies must contain at most 4,000 characters.','uz':'Javob 4 000 belgidan oshmasligi kerak.','ru':'Ответ должен содержать не более 4 000 символов.'}[data['lang']]
                return finish_render(request,'ops/detail.html',data,400)
            with transaction.atomic():
                ticket=SupportTicket.objects.select_for_update().get(pk=pk)
                if reply:
                    from apps.commerce.services import add_support_message
                    add_support_message(ticket.account,ticket.pk,reply,staff=request.ops_user)
                    audit(request.ops_user,'support.reply',pk,reason,after={'message_length':len(reply)})
                before=ticket.status
                ticket.status='waiting_customer' if reply else 'resolved' if request.POST.get('status')=='resolved' else 'open'
                ticket.save(update_fields=['status','updated_at'])
                audit(request.ops_user,'support.status_changed',pk,reason,{'status':before},{'status':ticket.status})
            return redirect(request.path+'?'+urlencode({'lang':data['lang'],'saved':'1'}))
    return finish_render(request,'ops/detail.html',data)


@require_staff('Analyst','Operations','Finance')
def api_summary(request):
    try:filters=Filters.from_request(request)
    except ValueError as error:return JsonResponse({'error':str(error)},status=400)
    return JsonResponse(report(filters))


def csv_cell(value):
    text=str(value if value is not None else '')
    return "'"+text if text.lstrip().startswith(('=','+','-','@','\t','\r','\n')) else text


@require_staff('Analyst','Support','Operations')
def export(request, kind):
    roles={'users':['Support'],'jobs':['Operations','Support'],'features':['Analyst','Operations']}
    if kind not in roles or not allowed(request.ops_user,roles[kind]):return HttpResponseForbidden('Staff permission required')
    try:filters=Filters.from_request(request)
    except ValueError as error:return HttpResponseBadRequest(str(error))
    output=io.StringIO();writer=csv.writer(output)
    writer.writerow(['definitions_version',DEFINITIONS_VERSION]);writer.writerow(['generated_at',timezone.now().isoformat()])
    for key,value in filters.__dict__.items():writer.writerow([key,csv_cell(value)])
    if kind=='users':
        fields=['id','telegram_user_id','display_name','locale','plan','first_verified_channel','created_at']
        records=filters.accounts().order_by('-created_at')
        search=request.GET.get('q','').strip()[:150]
        if search:
            query=Q(id__icontains=search)|Q(username__icontains=search)
            if search.isdigit():query |= Q(telegram_user_id=int(search))
            records=records.filter(query)
        if records.count()>10000:return HttpResponseBadRequest('Narrow filters to at most 10000 rows')
        rows=records.values_list(*fields)
    elif kind=='jobs':
        fields=['id','account_id','feature_id','status','origin_channel','created_at','completed_at','error_code']
        records=filters.jobs().order_by('-created_at')
        if request.GET.get('status'):records=records.filter(status=request.GET['status'])
        if records.count()>10000:return HttpResponseBadRequest('Narrow filters to at most 10000 rows')
        rows=records.values_list(*fields)
    else:
        fields=['feature_id','attempts','succeeded','failed','canceled','no_op','users'];rows=([row[f] for f in fields] for row in report(filters)['feature_rows'])
    writer.writerow(fields)
    for row in rows:writer.writerow([csv_cell(value) for value in row])
    audit(request.ops_user,'report.export',kind,'User-requested filtered CSV export',after=filters.__dict__)
    response=HttpResponse('\ufeff'+output.getvalue(),content_type='text/csv; charset=utf-8')
    response['Content-Disposition']=f'attachment; filename="pdf-master-{kind}.csv"'
    return response
