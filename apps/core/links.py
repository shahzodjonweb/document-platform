"""Links into the admin, as the bot sends them to the owner.

One origin for all of them: ADMIN_ORIGIN when it is set, else https:// and the
site host that serves the API and the admin (the one starting "api.", or the
first site host). Never guessed from CSRF_TRUSTED_ORIGINS, which may still list
admin hosts long gone (an old pdfmaster-admin.* stayed there after the admin
moved to api.docmaster.live/ops).
"""
from urllib.parse import urlsplit

from django.conf import settings


def admin_origin():
    """The admin's origin, such as https://api.docmaster.live, or '' when none is known."""
    explicit = (getattr(settings, 'ADMIN_ORIGIN', '') or '').strip().rstrip('/')
    parts = urlsplit(explicit)
    # An origin and nothing more; a local one only while developing. One that is not is no reason to send none.
    if parts.hostname and not parts.path and not parts.query and (parts.scheme == 'https' or (settings.DEBUG and parts.scheme == 'http')):
        return explicit
    hosts = [host.strip() for host in getattr(settings, 'SITE_HOSTS', []) if host.strip()]
    host = next((host for host in hosts if host.startswith('api.')), hosts[0] if hosts else '')
    return f'https://{host}' if host else ''


def admin_url(path):
    """A page of the admin, such as /ops/payments, as a whole link; '' when no origin is known."""
    origin = admin_origin()
    return origin + path if origin else ''
