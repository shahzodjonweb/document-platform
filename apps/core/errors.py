from pathlib import Path
import json
from django.conf import settings

class DomainError(Exception):
    def __init__(self, code, status=400, params=None, retryable=False):
        self.code, self.status, self.params, self.retryable = code, status, params or {}, retryable
        super().__init__(code)

def page_limit_count(error):
    """The page count a 'page_limit' refusal names, grouped like "1 000".

    Upload refuses a file longer than this, so the message says the real
    figure; an error that does not carry it (a stored job's code) gets the
    figure in force.
    """
    limit = (error.params or {}).get('limit')
    if type(limit) is not int:
        from .policy import page_cap
        limit = page_cap()
    return f'{limit:,}'.replace(',', ' ')

def cv_reading_ahead(error):
    """How many reads are ahead of a CV's files ('cv_reading'), or 0 when none is or the error does not say."""
    ahead = (error.params or {}).get('ahead')
    return ahead if type(ahead) is int and ahead > 0 else 0

def cv_reading_message(error, messages, message):
    """A CV's files still being read: how many reads are ahead of them, or only that they are being read."""
    ahead = cv_reading_ahead(error)
    return message.replace('{ahead}', str(ahead)) if ahead else messages.get('cv_reading_now', message)

def error_data(error, locale='en', request_id=''):
    path = settings.BASE_DIR / 'i18n' / f'{locale if locale in ("en", "uz", "ru") else "en"}.json'
    messages = json.loads(path.read_text()) if path.exists() else {}
    message = messages.get(error.code, messages.get('invalid_request', 'The request could not be completed.'))
    if error.code == 'page_limit':
        message = message.replace('{limit}', page_limit_count(error))
    if error.code == 'cv_reading':
        message = cv_reading_message(error, messages, message)
    return {'code': error.code, 'message_key': f'errors.{error.code}', 'message': message, 'message_params': error.params, 'request_id': request_id, 'field_errors': {}, 'retryable': error.retryable}
