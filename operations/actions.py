import json
import uuid
from django.db import transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_POST
from apps.core.models import Account,UsageGrant,Job
from apps.core.services import cancel_job,cleanup_expired
from apps.core.errors import DomainError
from .auth import require_staff,audit
from .models import AuditLog

@require_staff()
@require_POST
@transaction.atomic
def grant(request,pk):
    reason=request.POST.get('reason','').strip()
    if not 5<=len(reason)<=1000:return HttpResponseBadRequest('A specific reason is required.')
    try:
        key=str(uuid.UUID(request.POST.get('idempotency_key','')))
        quantities={m:int(request.POST.get(m,'0') or '0') for m in ('file_tasks','file_page_units','ai_credits')}
        if any(v<0 or v>100000 for v in quantities.values()) or not any(quantities.values()):raise ValueError()
        if quantities['file_tasks'] and not quantities['file_page_units']:raise ValueError()
    except (ValueError,TypeError):return HttpResponseBadRequest('Invalid grant quantities or request key.')
    account=Account.objects.select_for_update().filter(pk=pk).first()
    if not account:return HttpResponseBadRequest('Unknown account.')
    target=f'grant:{pk}:{key}'
    existing=AuditLog.objects.filter(action='quota.grant',target=target).first()
    if existing:
        if existing.after!=quantities:return HttpResponseBadRequest('Request key already used with different quantities.')
        return redirect(f'/ops/users/{pk}?saved=1')
    for meter,quantity in quantities.items():
        if quantity:
            UsageGrant.objects.create(account=account,meter=meter,source='adjustment',source_id=f'admin:{pk}:{key}:{meter}',quantity=quantity,valid_from=timezone.now())
    audit(request.ops_user,'quota.grant',target,reason,after=quantities)
    return redirect(f'/ops/users/{pk}?saved=1')

@require_staff('Operations')
@require_POST
def cancel(request,pk):
    reason=request.POST.get('reason','').strip()
    if not 5<=len(reason)<=1000:return HttpResponseBadRequest('A specific reason is required.')
    job=Job.objects.select_related('account').filter(pk=pk).first()
    if not job:return HttpResponseBadRequest('Unknown task.')
    try:result=cancel_job(job.account,pk)
    except DomainError:return HttpResponseBadRequest('This task cannot be canceled in its current state.')
    audit(request.ops_user,'job.cancel',pk,reason,after={'status':result.status})
    return redirect(f'/ops/jobs/{pk}?saved=1')
