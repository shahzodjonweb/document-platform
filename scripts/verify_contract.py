"""Fail CI if the public artifact drifts from its source or contains staff paths."""
import hashlib
import json
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from apps.core.management.commands.export_contract import schema
path=ROOT/'contracts/public.openapi.json'
expected=(json.dumps(schema(),ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode()
assert path.read_bytes()==expected, 'Run manage.py export_contract and repin the frontend contract'
assert (ROOT/'contracts/public.openapi.json.sha256').read_text().split()[0]==hashlib.sha256(expected).hexdigest()
assert not any('/ops' in k or '/admin' in k for k in schema()['paths'])
print('Public contract matches its generator and checksum; staff routes are excluded.')
# The CV fact parity corpus the web's ticks are held to: the server's answer on every case, as it is now.
from apps.studio.management.commands.export_cv_fact_cases import payload as cv_fact_cases
assert (ROOT/'contracts/cv_fact_cases.json').read_text(encoding='utf-8')==cv_fact_cases(), 'Run manage.py export_cv_fact_cases and copy it to the web'
print('CV fact cases match the server detectors.')
