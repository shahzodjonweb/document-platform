"""Admin-managed credentials. Never put tokens in URLs returned to clients or logs."""
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import urllib.request
from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from apps.core.errors import DomainError
from .models import IntegrationConfig

_process = None
_lock = threading.Lock()

def cipher():
    legacy = Fernet(base64.urlsafe_b64encode(hashlib.sha256((settings.SECRET_KEY + ':integration-secrets-v1').encode()).digest()))
    configured=os.getenv('INTEGRATION_ENCRYPTION_KEY','')
    if configured:return Fernet(configured.encode())
    if not settings.DEBUG:return legacy
    # Persist a random local key outside Git even when the demo signing key is used.
    root=settings.PRIVATE_STORAGE_ROOT
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=root/'integration.key'
    try:
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:pass
    else:
        with os.fdopen(fd,'wb') as output:output.write(Fernet.generate_key())
    # Legacy reader preserves drafts created before local key provisioning.
    return MultiFernet([Fernet(path.read_bytes()),legacy])

def read_config(key):
    row = IntegrationConfig.objects.filter(pk=key).first()
    if not row: return {}, {}
    secrets = json.loads(cipher().decrypt(bytes(row.encrypted_secrets))) if row.encrypted_secrets else {}
    return row.configuration, secrets

def telegram_config():
    cfg, secret = read_config('telegram')
    return {'token':secret.get('token') or settings.TELEGRAM_BOT_TOKEN,
            'username':cfg.get('username') or settings.TELEGRAM_BOT_USERNAME,
            'webhook_secret':secret.get('webhook_secret') or settings.TELEGRAM_WEBHOOK_SECRET,
            'webapp_url':cfg.get('webapp_url') or settings.TELEGRAM_WEBAPP_URL}

def ai_config():
    cfg, secret = read_config('ai')
    return {'mode':cfg.get('mode','local_fixture' if settings.DEBUG else 'disabled'),
            'model':cfg.get('model') or os.getenv('AI_MODEL',''),
            'image_model':cfg.get('image_model') or os.getenv('AI_IMAGE_MODEL',''),
            'api_key':secret.get('api_key') or os.getenv('OPENAI_API_KEY','')}

@transaction.atomic
def save_config(key, values):
    cfg, secrets = read_config(key)
    if key == 'telegram':
        token = values.get('token','').strip()
        if token:
            if not re.fullmatch(r'[0-9]{5,20}:[A-Za-z0-9_-]{25,150}',token): raise DomainError('invalid_bot_token')
            secrets['token'] = token
        username = values.get('username','').strip().lstrip('@')
        if username and not re.fullmatch(r'[A-Za-z0-9_]{5,32}',username): raise DomainError('invalid_bot_username')
        url = values.get('webapp_url',settings.TELEGRAM_WEBAPP_URL).strip()
        from urllib.parse import urlparse
        try:
            parsed = urlparse(url)
            valid_host=bool(parsed.hostname) and not parsed.username and not parsed.password
            valid_port=parsed.port is None or 1<=parsed.port<=65535
        except ValueError:raise DomainError('invalid_webapp_url') from None
        if not valid_host or not valid_port or any(ord(c)<33 for c in url):raise DomainError('invalid_webapp_url')
        if parsed.scheme != 'https' and not (settings.DEBUG and parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1')): raise DomainError('invalid_webapp_url')
        cfg.update(username=username,webapp_url=url)
    elif key == 'ai':
        mode = values.get('mode','local_fixture')
        if mode not in ('local_fixture','openai','disabled') or (mode=='local_fixture' and not settings.DEBUG): raise DomainError('invalid_parameters')
        if values.get('api_key','').strip(): secrets['api_key']=values['api_key'].strip()
        model=values.get('model','').strip()
        if mode=='openai' and (not (secrets.get('api_key') or os.getenv('OPENAI_API_KEY','')) or not model): raise DomainError('provider_not_configured')
        image_model=values.get('image_model',cfg.get('image_model','')).strip()
        if image_model and not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}',image_model):raise DomainError('invalid_parameters')
        cfg.update(mode=mode,model=model[:100],image_model=image_model)
    else: raise DomainError('invalid_parameters')
    return IntegrationConfig.objects.update_or_create(key=key,defaults={'configuration':cfg,'encrypted_secrets':cipher().encrypt(json.dumps(secrets).encode()),'check_status':'not_checked'})[0]

def test_telegram():
    cfg=telegram_config()
    if not cfg['token']: raise DomainError('bot_not_configured')
    # The URL is internal to this bounded request and never returned/logged on errors.
    try:
        req=urllib.request.Request('https://api.telegram.org/bot'+cfg['token']+'/getMe',data=b'{}',headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=10) as response: data=json.loads(response.read(65536))
        if not data.get('ok') or not data.get('result',{}).get('is_bot'): raise ValueError()
    except Exception: raise DomainError('bot_connection_failed',409) from None
    username=data['result'].get('username','')
    row,_=IntegrationConfig.objects.get_or_create(key='telegram')
    row.configuration={**row.configuration,'username':username};row.checked_at=timezone.now();row.check_status='connected'
    row.save(update_fields=['configuration','checked_at','check_status'])
    return username

def _locked_runner_pid():
    import fcntl
    import shlex
    path=settings.PRIVATE_STORAGE_ROOT/'runbot.lock'
    try:
        with path.open('r') as handle:
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                raw=handle.read(30).strip()
                if not raw.isdigit():return None
                pid=int(raw)
                result=subprocess.run(['/bin/ps','-p',str(pid),'-o','args='],capture_output=True,text=True,timeout=2)
                args=shlex.split(result.stdout.strip())
                if pid>1 and result.returncode==0 and len(args)>=3 and args[1]==str(settings.BASE_DIR/'manage.py') and args[2]=='runbot':return pid
                return None
            return None
    except (OSError,ValueError,subprocess.SubprocessError):return None

def runner_status():
    with _lock:
        return 'running' if (_process is not None and _process.poll() is None) or _locked_runner_pid() else 'stopped'

def control_runner(action):
    global _process
    if not settings.DEBUG: raise DomainError('local_control_only',403)
    with _lock:
        known_pid=_locked_runner_pid()
        running=(_process is not None and _process.poll() is None) or bool(known_pid)
        if action=='stop':
            if _process is not None and _process.poll() is None:_process.terminate()
            elif known_pid:
                import signal
                try:os.kill(known_pid,signal.SIGTERM)
                except ProcessLookupError:pass
            return
        if action!='start': raise DomainError('invalid_parameters')
        if running: return
        cfg=telegram_config()
        if not cfg['token']: raise DomainError('bot_not_configured')
        if cfg['webhook_secret']: raise DomainError('webhook_polling_conflict',409)
        test_telegram()
        # Credentials are fetched by the child from encrypted DB; never passed in argv.
        _process=subprocess.Popen([sys.executable,str(settings.BASE_DIR/'manage.py'),'runbot'],cwd=settings.BASE_DIR,
                                  stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
