"""A staff-only authentication realm. Customer cookies confer no staff authority.

Staff sign in with a username and password. Authenticator codes were removed at
the owner's request (2026-10-06); the per-address sign-in limit in views.login
still applies.
"""
import hashlib
import secrets
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect
from django.utils import timezone

from .models import AuditLog, StaffSession

COOKIE = "ops_session"
ROLES = {"Analyst", "Support", "Operations", "Finance", "Content manager", "Administrator"}


def development_access(request):
    return bool(settings.DEBUG and getattr(settings, "DEV_AUTH_ENABLED", False)
                and request.META.get("REMOTE_ADDR") in {"127.0.0.1", "::1"}
                and request.get_host().split(":")[0] in {"localhost", "127.0.0.1", "testserver"})


def begin_session(response, user):
    token = secrets.token_urlsafe(48)
    StaffSession.objects.create(user=user, token_hash=hashlib.sha256(token.encode()).hexdigest(),
                                expires_at=timezone.now() + timedelta(hours=8))
    response.set_cookie(COOKIE, token, max_age=8 * 3600, httponly=True,
                        secure=not settings.DEBUG, samesite="Strict", path="/ops/")
    return response


def staff_user(request):
    token = request.COOKIES.get(COOKIE, "")
    if not token or len(token) > 128:
        return None
    session = StaffSession.objects.select_related("user").filter(
        token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at__gt=timezone.now(),
        user__is_active=True, user__is_staff=True).first()
    return session.user if session else None


def allowed(user, roles):
    return user.is_superuser or user.groups.filter(name__in=set(roles) | {"Administrator"}).exists()


def require_staff(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            user = staff_user(request)
            if not user:
                if "/api/" in request.path:
                    return JsonResponse({"error": {"code": "staff_auth_required"}}, status=401)
                return redirect("/ops/login")
            if not allowed(user, roles):
                return HttpResponseForbidden("Staff permission required / Ruxsat kerak / Нет доступа")
            request.ops_user = user
            response = view(request, *args, **kwargs)
            response["Cache-Control"] = "no-store"
            response["X-Robots-Tag"] = "noindex, nofollow"
            response["X-Frame-Options"] = "DENY"
            return response
        return wrapped
    return decorator


# Staff are not asked why they did something: every action is recorded with who,
# what, when and before → after, and described in words here.
DESCRIPTIONS = {
    'quota.grant': 'Granted extra allowance', 'job.cancel': 'Cancelled a task',
    'account.plan_assign': 'Assigned a plan', 'account.plan_clear': 'Removed an assigned plan',
    'plan.limits': 'Changed plan limits', 'plan.reset': 'Reset a plan to its defaults',
    'file.download': 'Opened a customer document', 'generation.view': 'Opened a customer’s AI request', 'generation.file': 'Opened a document the AI made for a customer',
    'integration.save': 'Saved integration settings', 'integration.test': 'Tested an integration',
    'integration.start': 'Started the local bot', 'integration.stop': 'Stopped the local bot',
    'payment.refund': 'Refunded a payment', 'payment.manual_approve': 'Approved a card payment',
    'payment.manual_reject': 'Rejected a card payment', 'payment.manual_refund': 'Recorded a card payment refund',
    'staff.created': 'Added a staff member', 'staff.access_changed': 'Changed staff access',
    'support.reply': 'Replied to a support request', 'support.status_changed': 'Changed a support request status',
}


def audit(user, action, target, reason=None, before=None, after=None):
    reason = str(reason or '').strip() or DESCRIPTIONS.get(action, action.replace('.', ' ').replace('_', ' ').capitalize())
    return AuditLog.objects.create(actor=user, action=action, target=str(target), reason=reason[:1000],
                                   before=before or {}, after=after or {})
