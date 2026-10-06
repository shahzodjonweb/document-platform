"""Run a reviewed PDF Master operation using credentials only on the Actions runner."""
import os
import json
from pathlib import Path
import re
import subprocess
import tempfile

operation = os.environ['OPERATION']
if operation not in {'inventory', 'public-key', 'ssh-check', 'proxy-prepare', 'proxy-publish', 'setup-admin', 'verify-services', 'stabilize-cleanup'}:
    raise SystemExit('Unsupported server operation')
host = os.environ['DEPLOY_HOST'].strip()
user = os.environ['DEPLOY_USER'].strip()
port = os.environ.get('DEPLOY_PORT', '22')
if host != '77.42.34.241' or user not in {'root', 'orderdesk-deploy'}:
    raise SystemExit('Credentials do not identify the authorized PDF Master server/account.')
if not port.isdigit() or not 1 <= int(port) <= 65535:
    raise SystemExit('Invalid SSH port')
with tempfile.TemporaryDirectory() as folder:
    key, known = Path(folder)/'key', Path(folder)/'known_hosts'
    key.write_text(os.environ['DEPLOY_SSH_KEY'].rstrip()+'\n')
    known.write_text(os.environ['DEPLOY_KNOWN_HOSTS'].rstrip()+'\n')
    key.chmod(0o600); known.chmod(0o600)
    target = host if port == '22' else f'[{host}]:{port}'
    for args in (['ssh-keygen','-y','-P','','-f',str(key)], ['ssh-keygen','-F',target,'-f',str(known)]):
        if subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            raise SystemExit('Invalid private key or missing pinned host entry.')
    if operation == 'public-key':
        public = subprocess.check_output(['ssh-keygen','-y','-P','','-f',str(key)], text=True).strip()
        print('PUBLIC_KEY_TO_AUTHORIZE: ' + public)
        raise SystemExit(0)
    args = ['ssh' ,'-F','/dev/null','-i',str(key),'-p',port,
            '-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes',
            '-o',f'UserKnownHostsFile={known}','-o','GlobalKnownHostsFile=/dev/null',
            '-o','ConnectTimeout=15','-o','ServerAliveInterval=15',f'{user}@{host}', 'python3 -']
    if operation == 'ssh-check':
        # These are the two accounts identified by the user and the existing
        # project's deployment documentation. Check authentication only; never
        # modify that project, authorize keys, or change the selected deploy user.
        connected = False
        for account in ('root', 'orderdesk-deploy'):
            check = [*args[:-2], f'{account}@{host}', 'id -un']
            result = subprocess.run(check, capture_output=True, text=True, timeout=30)
            accepted = result.returncode == 0 and result.stdout.strip() == account
            print(f'ACCOUNT_{account.upper().replace("-", "_")}: '
                  + ('accepted' if accepted else 'rejected'), flush=True)
            connected = connected or accepted
        raise SystemExit(0 if connected else 1)
    script = operation + '.py'
    if operation in {'proxy-prepare', 'proxy-publish'}:
        script = 'proxy_setup.py'
        args[-1] = 'python3 - ' + operation.removeprefix('proxy-')
    if operation == 'setup-admin':
        payload = json.loads(os.environ.get('ADMIN_BOOTSTRAP', '{}'))
        # A stored secret may still carry the retired authenticator key; it is ignored.
        if not {'username', 'password'} <= set(payload) or set(payload) - {'username', 'password', 'totp_secret'}:
            raise SystemExit('Missing complete private admin enrollment data')
        payload = {key: payload[key] for key in ('username', 'password')}
        script = 'setup_admin.py'
        source = 'BOOTSTRAP = ' + repr(payload) + '\n' + Path(__file__).with_name(script).read_text()
        result = subprocess.run(args,input=source.encode(),timeout=800)
    elif operation == 'verify-services':
        helpers = {name: Path(__file__).with_name(name).read_text() for name in (
            'service_checks_background.py', 'service_checks_documents.py', 'service_checks_paid.py')}
        source = 'CHECK_SOURCES = ' + repr(helpers) + '\n' + Path(__file__).with_name(script).read_text()
        result = subprocess.run(args, input=source.encode(), timeout=800)
    else:
        with Path(__file__).with_name(script).open('rb') as source:
            result = subprocess.run(args,stdin=source,timeout=800)
    raise SystemExit(result.returncode)
