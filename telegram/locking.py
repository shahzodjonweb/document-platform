"""A process lock survives admin web-process restarts without exposing tokens."""
import os
from contextlib import contextmanager
from django.conf import settings

@contextmanager
def polling_lock():
    import fcntl
    path=settings.PRIVATE_STORAGE_ROOT / 'runbot.lock'
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(path,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        os.chmod(path,0o600)
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('A Telegram polling process is already running for this project.') from None
        os.ftruncate(fd,0);os.write(fd,str(os.getpid()).encode());os.fsync(fd)
        yield
    finally:
        os.close(fd)
