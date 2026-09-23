"""Run a reviewed PDF Master operation using credentials only on the Actions runner."""
import os
from pathlib import Path
import re
import subprocess
import tempfile

operation = os.environ['OPERATION']
if operation not in {'inventory'}:
    raise SystemExit('Unsupported server operation')
host = os.environ['DEPLOY_HOST'].strip()
user = os.environ['DEPLOY_USER'].strip()
port = os.environ.get('DEPLOY_PORT', '22')
if host != '77.42.34.241' or user != 'root':
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
    args = ['ssh','-F','/dev/null','-i',str(key),'-p',port,
            '-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes',
            '-o',f'UserKnownHostsFile={known}','-o','GlobalKnownHostsFile=/dev/null',
            '-o','ConnectTimeout=15','-o','ServerAliveInterval=15',f'{user}@{host}', 'python3 -']
    with Path(__file__).with_name(operation+'.py').open('rb') as source:
        result = subprocess.run(args,stdin=source,timeout=800)
    raise SystemExit(result.returncode)
