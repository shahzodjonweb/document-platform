import uuid

from django.conf import settings


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        request.request_id = str(uuid.uuid4())
        response = self.get_response(request)
        if request.path.startswith('/api/v1/auth/') or request.path == '/api/v1/me':
            response['Cache-Control'] = 'private, no-store'
            response['Referrer-Policy'] = 'no-referrer'
        response['X-Request-ID'] = request.request_id
        return response



# The browser sign-in challenge (apps/core/views.py challenges): a five-minute
# verifier bound to the Telegram login, sent only under its own path.
CHALLENGE_COOKIE = 'docmaster_challenge'
CHALLENGE_PATH = '/api/v1/auth/browser/'
CHALLENGE_AGE = 300


def challenge_cookie_attributes():
    return {'path': CHALLENGE_PATH, 'domain': None, 'secure': not settings.DEBUG, 'httponly': True, 'samesite': 'Lax'}


def session_cookie_attributes():
    return {'path': settings.SESSION_COOKIE_PATH, 'domain': settings.SESSION_COOKIE_DOMAIN,
            'secure': settings.SESSION_COOKIE_SECURE, 'httponly': settings.SESSION_COOKIE_HTTPONLY,
            'samesite': settings.SESSION_COOKIE_SAMESITE}


def _session_age(request):
    """What SessionMiddleware would give the cookie: None for a browser-session cookie."""
    session = getattr(request, 'session', None)
    if session is None or session.get_expire_at_browser_close():
        return None
    return session.get_expiry_age()


class LegacyCookieMiddleware:
    """Rename migration: carry cookies set under the pre-rename "pdfmaster_" names.

    A request with an old cookie and not the new one is read as if it carried
    the new one, so nobody is signed out and no sign-in in progress is lost.
    The response then sets the new cookie, with the attributes it is always
    set with, unless the view already set or deleted it (sign-in, sign-out, an
    expired session), and deletes the old one. It sits before SessionMiddleware.

    Remove it, its entry in settings.MIDDLEWARE and its tests
    (tests/test_rename_migrations.py) once SESSION_COOKIE_AGE (two weeks) has
    passed since the rename shipped: every old session cookie has expired by
    then, and the challenge cookie lives five minutes.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def renamed():
        """Old name -> (new name, its attributes, its max-age for this request)."""
        return {
            'pdfmaster_session': (settings.SESSION_COOKIE_NAME, session_cookie_attributes, _session_age),
            'pdfmaster_challenge': (CHALLENGE_COOKIE, challenge_cookie_attributes, lambda request: CHALLENGE_AGE),
        }

    def __call__(self, request):
        carried = []
        for old, (new, attributes, age) in self.renamed().items():
            if old not in request.COOKIES:
                continue
            # When both are sent the new one wins and the old one only goes.
            fresh = new not in request.COOKIES
            if fresh:
                request.COOKIES[new] = request.COOKIES[old]
            carried.append((old, new, attributes(), age, fresh))
        response = self.get_response(request)
        for old, new, attributes, age, fresh in carried:
            if fresh and new not in response.cookies:
                response.set_cookie(new, request.COOKIES[new], max_age=age(request), **attributes)
            response.delete_cookie(old, path=attributes['path'], domain=attributes['domain'], samesite=attributes['samesite'])
        return response
