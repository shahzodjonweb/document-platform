"""Create the first administrator in PDF Master's database; never print credentials."""
import json
import re
import subprocess


def command(args, source=None):
    result = subprocess.run(args, input=source, text=True, capture_output=True, timeout=90)
    if result.returncode:
        raise SystemExit('Admin enrollment failed; no credentials were logged. Inspect the platform locally.')
    return result.stdout


if not re.fullmatch(r'[a-zA-Z0-9_-]{3,64}', BOOTSTRAP['username']):
    raise SystemExit('Invalid administrator username')
if len(BOOTSTRAP['password']) < 32 or not re.fullmatch(r'[A-Z2-7]{32}', BOOTSTRAP['totp_secret']):
    raise SystemExit('Use a strong password and valid TOTP enrollment secret')
ids = command(['docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=pdfmaster-platform',
               '--filter', 'label=com.docker.compose.service=api']).split()
if len(ids) != 1:
    raise SystemExit('Expected one healthy PDF Master API container')
container = json.loads(command(['docker', 'inspect', ids[0]]))[0]
if container['State'].get('Health', {}).get('Status') != 'healthy':
    raise SystemExit('PDF Master API is not healthy')
code = 'enrollment = ' + repr(BOOTSTRAP) + '''
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from operations.auth import secret_cipher, audit
from operations.models import StaffTOTP
with transaction.atomic():
    users = get_user_model().objects
    existing = users.filter(username=enrollment['username']).first()
    if existing:
        device = StaffTOTP.objects.filter(user=existing).first()
        if (not existing.check_password(enrollment['password']) or not device or
            secret_cipher().decrypt(device.encrypted_secret.encode()).decode() != enrollment['totp_secret']):
            raise RuntimeError('Existing account differs; refusing to change credentials')
        print('ADMIN_ENROLLMENT_ALREADY_COMPLETE')
    else:
        if users.filter(is_staff=True).exists():
            raise RuntimeError('A staff account already exists; use normal account administration')
        user = users.create_user(username=enrollment['username'], password=enrollment['password'],
                                 is_staff=True, is_active=True)
        user.groups.set([Group.objects.get_or_create(name='Administrator')[0]])
        StaffTOTP.objects.create(user=user,
            encrypted_secret=secret_cipher().encrypt(enrollment['totp_secret'].encode()).decode(), last_counter=-1)
        audit(user, 'staff.bootstrap', user.pk, 'Initial production administrator enrollment')
        print('ADMIN_ENROLLMENT_CREATED')
'''
output = command(['docker', 'exec', '-i', ids[0], 'python', 'manage.py', 'shell', '-c',
                  'import sys; exec(sys.stdin.read())'], code)
if not any(line.startswith('ADMIN_ENROLLMENT_') for line in output.splitlines()):
    raise SystemExit('Admin enrollment did not confirm success')
print('ADMIN_ENROLLMENT_COMPLETE: credentials remain private; TOTP required for login')
