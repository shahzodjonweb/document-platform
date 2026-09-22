import base64
import hashlib
from datetime import timedelta
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.utils import timezone
from .models import SecretHandle
from .errors import DomainError

def cipher():
    configured=getattr(settings,'FILE_SECRET_KEY','')
    key=configured.encode() if configured else base64.urlsafe_b64encode(hashlib.sha256((settings.SECRET_KEY+':pdf-file-passwords:v1').encode()).digest())
    return Fernet(key)

def create_secret(account,password,asset=None):
    if not isinstance(password,str) or not 1<=len(password)<=256: raise DomainError('password_required')
    return SecretHandle.objects.create(account=account,asset=asset,ciphertext=cipher().encrypt(password.encode()),expires_at=timezone.now()+timedelta(minutes=10))

def get_secret(account,secret_id,asset=None,job=None):
    handle=SecretHandle.objects.filter(id=secret_id,account=account,expires_at__gt=timezone.now()).first()
    if not handle or (handle.job_id and (not job or handle.job_id!=job.id)): raise DomainError('password_expired',409)
    if asset and handle.asset_id!=asset.id: raise DomainError('password_expired',409)
    return handle

def decrypt(handle):
    try: return cipher().decrypt(bytes(handle.ciphertext),ttl=600).decode()
    except (InvalidToken,ValueError): raise DomainError('password_expired',409) from None
