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
