"""Container scheduler; run as a separate service, never in an HTTP request."""
import os
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
import logging
from django.core.management import call_command
from django.db import close_old_connections
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
# One failed run is logged and the next one comes five minutes later, rather
# than the process dying and every scheduled job (file expiry, the storage
# sync and its health check) stopping until the container restarts.
while True:
    close_old_connections()
    try:
        call_command('cleanupfiles')
    except Exception:
        logging.getLogger('cleanup').exception('Cleanup run failed; the next run is in five minutes')
    time.sleep(300)
