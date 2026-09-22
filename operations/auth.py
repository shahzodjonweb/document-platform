"""A staff-only authentication realm. Customer cookies confer no staff authority."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import timedelta
from functools import wraps

from cryptography.fernet import Fernet
from django.conf import settings
from django.db import transaction
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect
from django.utils import timezone

from .models import AuditLog, StaffSession, StaffTOTP

COOKIE = "ops_session"
ROLES = {"Analyst", "Support", "Operations", "Finance", "Content manager", "Administrator"}


def secret_cipher():
    key = hashlib.sha256((settings.SECRET_KEY + ":staff-totp-v1").encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def totp_code(secret, counter):
    digest = hmac.new(base64.b32decode(secret, casefold=True), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1000000
    return f"{code:06d}"


@transaction.atomic
def verify_totp(user, code):
    device = StaffTOTP.objects.select_for_update().filter(user=user).first()
    if not device or not isinstance(code, str) or len(code) != 6 or not code.isdigit():
        return False
    secret = secret_cipher().decrypt(device.encrypted_secret.encode()).decode()
    counter = int(time.time()) // 30
    for candidate in (counter - 1, counter, counter + 1):
        if candidate > device.last_counter and hmac.compare_digest(code, totp_code(secret, candidate)):
            device.last_counter = candidate
            device.save(update_fields=["last_counter"])
            return True
    return False


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


def audit(user, action, target, reason, before=None, after=None):
    return AuditLog.objects.create(actor=user, action=action, target=str(target), reason=reason,
                                   before=before or {}, after=after or {})
