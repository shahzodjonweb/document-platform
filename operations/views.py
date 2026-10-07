import csv
import hashlib
import io
import json
import uuid
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import Group
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.middleware.csrf import rotate_token
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateformat import format as date_format
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.models import Account, Job, UsageLedger
from .auth import COOKIE, allowed, audit, begin_session, development_access, require_staff, staff_user
from .i18n import CATALOGS, EN, get_locale
from .metrics import DEFINITIONS_VERSION, Filters, report, system_snapshot
from .middleware import viewer_zone
from .models import AuditLog, LoginAttempt, StaffSession

PAGE_ROLES = {
    'today':['Analyst','Operations','Finance','Support','Content manager'],
    'overview':['Analyst','Operations','Finance'], 'users':['Support'],
    'analytics/acquisition':['Analyst'], 'analytics/engagement':['Analyst'],
    'analytics/features':['Analyst','Operations'], 'analytics/revenue':['Analyst','Finance'],
    'analytics/ai-usage':['Analyst','Operations','Finance'],
    'jobs':['Operations','Support'], 'generations':['Support','Operations'], 'plans':['Finance','Content manager'],
    'payments':['Finance'], 'audit':[], 'system':['Operations'],
    'localization':['Content manager'], 'integrations':[], 'staff':[],
}
PAGE_KEYS = {'today':'today','overview':'overview','users':'users','analytics/acquisition':'acquisition',
             'analytics/engagement':'engagement','analytics/features':'features','analytics/revenue':'revenue','analytics/ai-usage':'ai_usage',
             'jobs':'jobs','generations':'generations','plans':'plans','payments':'payments','audit':'audit','system':'system','localization':'localization'}
# Sidebar: (group label key, [(page, label key, icon)]). The analytics reports
# share one entry; their own tabs switch between them.
NAV = [
    ('', [('today','today','today')]),
    ('customers', [('users','users','users'),('generations','generations','sparkle')]),
    ('money', [('payments','payments','card'),('analytics/revenue','revenue','trending')]),
    ('product', [('overview','nav_analytics','chart'),('jobs','nav_tasks','list'),('analytics/ai-usage','ai_usage','cpu'),('plans','plans','layers')]),
    ('settings', [('integrations','integrations','plug'),('staff','staff','shield'),('audit','audit','history'),('system','system','activity'),('localization','localization','globe')]),
]
ANALYTICS = ['overview','analytics/acquisition','analytics/engagement','analytics/features']
# Each report page() renders lays itself out in one partial.
SECTIONS = {'today':'today','overview':'analytics','analytics/acquisition':'analytics','analytics/engagement':'analytics',
            'analytics/features':'analytics','users':'users','jobs':'jobs','audit':'audit',
            'plans':'plans','system':'system','localization':'localization'}
JOB_STATES = ['queued','running','succeeded','failed','canceled']
USER_SORTS = {'new':'-created_at','old':'created_at','name':'display_name','plan':'-plan'}
PLAN_GROUPS = [('group_price',['price_uzs','price_xtr']),
               ('group_allowance',['file_tasks','file_page_units','ai_credits']),
               ('group_daily',['daily_file_tasks','daily_ai_documents']),
               ('group_task',['max_file_mib','max_pages_per_job','concurrent_jobs']),
               ('group_ai',['max_ai_source_pages','max_ai_source_files','max_deck_images','max_ai_input_tokens',
                            'max_generated_pdf_pages','max_generated_slides']),
               ('group_saved',['saved_workflows','saved_teacher_templates'])]


def role_check(user):
    """allowed() for one request, with the staff member's groups read once."""
    if not user:
        return lambda roles: False
    names = set(user.groups.values_list('name', flat=True))
    return lambda roles: bool(user.is_superuser or names & (set(roles) | {'Administrator'}))


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
    ok = role_check(user)
    nav = []
    if user:
        # Work waiting for someone shows as a count beside its page.
        badges = {}
        if ok(PAGE_ROLES['payments']):
            from apps.commerce.models import ManualPayment
            badges['payments'] = ManualPayment.objects.filter(status='submitted').count()
        for group, items in NAV:
            permitted = [{'path':path,'url':'/ops/'+path+'?'+query,'label':labels[key],'icon':icon,
                          'active':page==path or (path=='overview' and page in ANALYTICS),'badge':badges.get(path,0)}
                         for path,key,icon in items if ok(PAGE_ROLES[path])]
            if permitted:
                nav.append({'label':labels[group] if group else '','items':permitted})
    params = request.GET.copy()
    locale_links = []
    for locale, name in [('en','English'),('uz','O‘zbekcha'),('ru','Русский')]:
        params['lang'] = locale
        locale_links.append({'label':name,'locale':locale,'url':'?'+params.urlencode()})
    return {'t':labels,'lang':lang,'query':query,'page':page,'page_key':PAGE_KEYS.get(page,page),
            'title':labels.get(PAGE_KEYS.get(page,page),page),'nav':nav,'staff':user,
            'staff_role':user.groups.first().name if user and user.groups.exists() else labels['staff'],
            'locale_links':locale_links,'dev_enabled':development_access(request),'zone':viewer_zone(),
            'can_inspect_jobs':ok(['Operations','Support']),'can_search_users':ok(PAGE_ROLES['users']),'ok':ok}


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
        if user and user.is_active and user.is_staff:
            recent.delete()
            rotate_token(request)
            audit(user,'staff.login',user.pk,'Password verified')
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
    return begin_session(redirect('/ops/today?environment=development'),user)


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
    if section not in SECTIONS or not allowed(request.ops_user,PAGE_ROLES[section]):
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
    if section=='today':
        from .today import summary as today_summary
        data.update(today_summary(request,filters,data['t'],data['ok']))
        # Today's cards lead to the same day on the pages behind them.
        params=request.GET.copy();params.pop('p',None)
        params['lang']=data['lang']
        for key in ('date_from','date_to','timezone'):params[key]=getattr(data['today_filters'],key)
        data['today_query']=params.urlencode()
    if section in ANALYTICS:
        data['analytics_tabs']=[{'label':data['t'][PAGE_KEYS[path]],'url':'/ops/'+path+'?'+data['query'],'active':path==section}
                                for path in ANALYTICS if data['ok'](PAGE_ROLES[path])]
    if section in {'users','jobs','audit'}:
        if section=='users':
            search=request.GET.get('q','').strip()[:150]
            # A search looks through every account; the plain list shows who joined in the period.
            sort=request.GET.get('sort','new')
            rows=account_search(filters,search).order_by(USER_SORTS.get(sort,'-created_at'),'id')
            plan=request.GET.get('plan','')
            if plan in {'free','plus','premium'}:rows=rows.filter(plan=plan)
            data.update(search=search,plan_filter=plan,plan_tabs=['','free','plus','premium'],sort=sort if sort in USER_SORTS else 'new')
        elif section=='jobs':
            rows=filters.jobs().select_related('account').order_by('-created_at')
            state=request.GET.get('status','')
            if state:rows=rows.filter(status=state)
            data.update(status_filter=state,job_states=JOB_STATES)
        else:
            rows=AuditLog.objects.select_related('actor').filter(created_at__gte=filters.bounds[0],created_at__lt=filters.bounds[1]).order_by('-created_at')
        data['pagination']=Paginator(rows,30).get_page(request.GET.get('p'))
        if section=='audit':
            for row in data['pagination']:
                row.changes=audit_changes(row.before,row.after)
    if section=='plans':
        from . import plans as plan_settings
        defaults=plan_settings.seed()['plans'];changed=plan_settings.overrides()
        data['plan_rows']=[{'id':key,'title':key.capitalize(),'edited':bool(changed.get(key)),
                            **plan_settings.limits_for(key,value)} for key,value in defaults.items()]
        # Each field carries its seed value so an operator can see what they
        # are changing it from, and its bounds so the form refuses nonsense.
        data['plan_fields']=[{'name':name,'low':low,'high':high} for name,(low,high) in plan_settings.FIELDS.items()]
        # Fields are grouped the way an operator thinks about a plan.
        data['plan_edit_rows']=[{'id':row['id'],'title':row['title'],'edited':row['edited'],
                                 'groups':[{'label':data['t'][group],
                                            'fields':[{'name':name,'label':data['t'].get('field_'+name,name),
                                                       'low':plan_settings.FIELDS[name][0],'high':plan_settings.FIELDS[name][1],
                                                       'nullable':name in plan_settings.NULLABLE,
                                                       'value':row.get(name),'seed':defaults[row['id']].get(name)}
                                                      for name in names if name in plan_settings.FIELDS and name in defaults[row['id']]]}
                                           for group,names in PLAN_GROUPS]}
                               for row in data['plan_rows']]
        data['can_edit_plans']=allowed(request.ops_user,['Finance','Content manager'])
    if section=='system':data['system_cards']=[{'key':key,'label':data['t'][key],'value':value} for key,value in system_snapshot(filters).items()]
    if section=='localization':data['locale_rows']=[{'id':key,'label':{'en':'English','uz':'O‘zbekcha','ru':'Русский'}.get(key,key),'count':len(value),'coverage':'100%'} for key,value in CATALOGS.items()]
    data['now']=timezone.now()
    data['section_template']='ops/sections/'+SECTIONS[section]+'.html'
    return finish_render(request,'ops/page.html',data)


def account_search(filters,search):
    """Accounts matching a name, username, Telegram ID or account ID; or, with no search, those who joined in the period."""
    rows=filters.accounts(in_period=not search)
    if search:
        query=Q(id__icontains=search)|Q(username__icontains=search.lstrip('@'))|Q(display_name__icontains=search)
        if search.isdigit():query |= Q(telegram_user_id=int(search))
        rows=rows.filter(query)
    return rows


def audit_changes(before,after):
    """What an audited action changed, field by field, for the audit table."""
    before=before if isinstance(before,dict) else {}
    after=after if isinstance(after,dict) else {}
    def short(value):
        text=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,default=str)
        # Saved times are UTC ISO strings: show them like every other time on the page.
        try:moment=parse_datetime(text)
        except ValueError:moment=None
        if moment and timezone.is_aware(moment):text=date_format(timezone.localtime(moment),'d M Y · H:i')
        return text if len(text)<=60 else text[:57]+'…'
    rows=[]
    for key in list(dict.fromkeys([*before,*after]))[:8]:
        if key in before and key in after and before[key]==after[key]:continue
        rows.append({'key':key,'before':short(before[key]) if key in before else None,'after':short(after[key]) if key in after else None})
    return rows


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
    data['plan_limits']=[{'label':data['t'].get('field_'+key,key.replace('_',' ')),'value':value} for key,value in limits_for_plan(account.plan).items()]
    # Customer documents, newest first. Opening one is a separate audited act.
    data['files']=FileAsset.objects.filter(account=account).order_by('-created_at')[:50]
    data['can_open_files']=allowed(request.ops_user,['Support','Operations'])
    if data['can_open_files']:
        from .generation_views import _rows
        data['generation_rows']=_rows(account.generation_records.select_related('job').order_by('-created_at')[:10],data['t'])
    # Card transfers are Finance's to see.
    if data['ok'](PAGE_ROLES['payments']):
        from apps.commerce.models import ManualPayment
        from .commerce_views import LABELS as MONEY_LABELS
        money=MONEY_LABELS[data['lang']]
        data['payment_rows']=[{'payment':row,'status':money.get('status_'+row.status,row.status)}
                              for row in ManualPayment.objects.filter(account=account).order_by('-created_at')[:20]]
    audit(request.ops_user,'account.metadata_view',pk,'Staff inspected account metadata')
    return finish_render(request,'ops/user.html',data)


@require_staff('Operations','Support')
def job_detail(request, pk):
    job=get_object_or_404(Job.objects.select_related('account'),pk=pk)
    data=context(request,'jobs');data['can_cancel']=allowed(request.ops_user,['Operations']) and job.status=='queued';data.update({'job':job,'detail_type':'job','ledger':UsageLedger.objects.filter(job=job).order_by('created_at')})
    return finish_render(request,'ops/job.html',data)


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
    # Times are in the viewer's zone, like on the page, and carry their UTC offset.
    local=lambda value:timezone.localtime(value) if isinstance(value,datetime) and timezone.is_aware(value) else value
    writer.writerow(['definitions_version',DEFINITIONS_VERSION]);writer.writerow(['generated_at',timezone.localtime().isoformat()]);writer.writerow(['times_timezone',viewer_zone()])
    for key,value in filters.__dict__.items():writer.writerow([key,csv_cell(value)])
    if kind=='users':
        fields=['id','telegram_user_id','display_name','locale','plan','first_verified_channel','created_at']
        records=account_search(filters,request.GET.get('q','').strip()[:150]).order_by('-created_at')
        if request.GET.get('plan','') in {'free','plus','premium'}:records=records.filter(plan=request.GET['plan'])
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
    for row in rows:writer.writerow([csv_cell(local(value)) for value in row])
    audit(request.ops_user,'report.export',kind,'User-requested filtered CSV export',after=filters.__dict__)
    response=HttpResponse('\ufeff'+output.getvalue(),content_type='text/csv; charset=utf-8')
    response['Content-Disposition']=f'attachment; filename="pdf-master-{kind}.csv"'
    return response
