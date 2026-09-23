"""Isolated browser verification server: synthetic config, private mailbox, port8001."""
import os
import sys
from pathlib import Path
root = Path('/tmp/pdfmaster-auth-e2e')
root.mkdir(mode=0o700, exist_ok=True)
os.umask(0o077)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.update(DJANGO_SETTINGS_MODULE='config.settings', DEBUG='1',
    SECRET_KEY='isolated-customer-auth-browser-fixture-not-production',
    DATABASE_URL='sqlite:////tmp/pdfmaster-auth-e2e/db.sqlite3',
    PRIVATE_STORAGE_ROOT=str(root/'private'), TELEGRAM_WEBAPP_URL='http://127.0.0.1:3001/en/app',
    ALLOWED_HOSTS='127.0.0.1,localhost,testserver', CSRF_TRUSTED_ORIGINS='http://127.0.0.1:3001,http://localhost:3001',
    DEVELOPMENT_LOGIN_ENABLED='0', ENABLE_DOCUMENT_TOOLS='1', LOCAL_SYNC_JOBS='1')
import django
django.setup()
from django.core.management import call_command
from django.core.mail import get_connection
from operations import integrations
call_command('migrate', interactive=False, verbosity=0)
integrations.save_config('email', {'enabled':'true','host':'local-fixture.invalid','port':'587','from_email':'noreply@example.test','use_tls':'true'})
# Only this local test process replaces SMTP with a private Playwright mailbox.
integrations._email_connection = lambda cfg: get_connection('django.core.mail.backends.filebased.EmailBackend', file_path=str(root/'mail'))
call_command('runserver', '127.0.0.1:8001', use_reloader=False, verbosity=0)
