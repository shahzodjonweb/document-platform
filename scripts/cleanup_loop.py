"""Container scheduler; run as a separate service, never in an HTTP request."""
import os
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from django.core.management import call_command
while True:
    call_command('cleanupfiles')
    time.sleep(300)
