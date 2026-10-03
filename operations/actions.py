import uuid
from datetime import timedelta
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
    audit(request.ops_user,'quota.grant',target,after=quantities)
    return redirect(f'/ops/users/{pk}?saved=1')

@require_staff('Operations')
@require_POST
def cancel(request,pk):
    job=Job.objects.select_related('account').filter(pk=pk).first()
    if not job:return HttpResponseBadRequest('Unknown task.')
    try:result=cancel_job(job.account,pk)
    except DomainError:return HttpResponseBadRequest('This task cannot be canceled in its current state.')
    audit(request.ops_user,'job.cancel',pk,after={'status':result.status})
    return redirect(f'/ops/jobs/{pk}?saved=1')


PLANS = ('free', 'plus', 'premium')


@require_staff()
@require_POST
@transaction.atomic
def set_plan(request, pk):
    """Assign or clear a plan for one account.

    This is not a purchase: it never creates a payment, never appears in
    revenue, and leaves any paid period untouched underneath so it returns when
    the assignment lapses.
    """
    plan = request.POST.get('plan', '').strip()
    if plan and plan not in PLANS:
        return HttpResponseBadRequest('Unknown plan.')
    days = request.POST.get('days', '').strip()
    try:
        expires = timezone.now() + timedelta(days=int(days)) if days else None
        if expires and not 1 <= int(days) <= 3650:
            raise ValueError()
    except ValueError:
        return HttpResponseBadRequest('Duration must be between 1 and 3650 days.')
    account = Account.objects.select_for_update().filter(pk=pk).first()
    if not account:
        return HttpResponseBadRequest('Unknown account.')

    before = {'staff_plan': account.staff_plan, 'effective': account.plan,
              'expires_at': account.staff_plan_expires_at.isoformat() if account.staff_plan_expires_at else ''}
    account.staff_plan = plan
    account.staff_plan_expires_at = expires if plan else None
    account.save(update_fields=['staff_plan', 'staff_plan_expires_at'])
    from apps.commerce.services import refresh_account_entitlement
    effective = refresh_account_entitlement(account)
    audit(request.ops_user, 'account.plan_assign' if plan else 'account.plan_clear', pk,
          before=before, after={'staff_plan': plan, 'effective': effective,
                                'expires_at': expires.isoformat() if expires else ''})
    return redirect(f'/ops/users/{pk}?saved=1')


@require_staff('Finance', 'Content manager')
@require_POST
@transaction.atomic
def save_plan(request, plan_id):
    """Change what a plan allows, for everyone on it, without a deploy."""
    from . import plans as plan_settings
    if request.POST.get('reset'):
        plan_settings.reset(plan_id)
        audit(request.ops_user, 'plan.reset', plan_id)
        return redirect('/ops/plans?saved=1')
    values = {field: request.POST[field] for field in plan_settings.FIELDS if field in request.POST}
    try:
        before, after = plan_settings.save(plan_id, values)
    except plan_settings.PlanError as error:
        return HttpResponseBadRequest(str(error))
    if not after:
        return redirect('/ops/plans?saved=1')
    audit(request.ops_user, 'plan.limits', plan_id, before=before, after=after)
    return redirect('/ops/plans?saved=1')


@require_staff('Support', 'Operations')
def download_file(request, pk):
    """Open one customer document, recording who opened which file and when.

    Staff can reach customer documents so support can actually investigate a
    report. Every access is written to the audit trail before the bytes are
    served.
    """
    from django.http import FileResponse
    from apps.core.models import FileAsset
    from apps.core.services import storage_path
    asset = FileAsset.objects.select_related('account').filter(pk=pk).first()
    if not asset:
        return HttpResponseBadRequest('Unknown file.')
    if asset.state != 'ready' or asset.expires_at <= timezone.now():
        return HttpResponseBadRequest('This file has expired or been removed.')
    path = storage_path(asset.object_key)
    if not path.is_file():
        return HttpResponseBadRequest('This file is no longer stored.')
    audit(request.ops_user, 'file.download', pk,
          after={'account': str(asset.account_id), 'name': asset.name, 'bytes': asset.size_bytes})
    response = FileResponse(path.open('rb'), as_attachment=True, filename=asset.name,
                            content_type=asset.mime_type)
    response['Cache-Control'] = 'private, no-store'
    response['Content-Security-Policy'] = "sandbox; default-src 'none'"
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response
