import uuid
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
