from pathlib import Path
import json
from django.conf import settings

class DomainError(Exception):
    def __init__(self, code, status=400, params=None, retryable=False):
        self.code, self.status, self.params, self.retryable = code, status, params or {}, retryable
        super().__init__(code)

def error_data(error, locale='en', request_id=''):
    path = settings.BASE_DIR / 'i18n' / f'{locale if locale in ("en", "uz", "ru") else "en"}.json'
    messages = json.loads(path.read_text()) if path.exists() else {}
    return {'code': error.code, 'message_key': f'errors.{error.code}', 'message': messages.get(error.code, messages.get('invalid_request', 'The request could not be completed.')), 'message_params': error.params, 'request_id': request_id, 'field_errors': {}, 'retryable': error.retryable}
