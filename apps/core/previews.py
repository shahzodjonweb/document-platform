"""Owner-authorized one-page previews; never enter the usage ledger."""
import hashlib
import os
import shutil
import tempfile
import uuid
import zipfile
from datetime import timedelta
from pathlib import Path
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from processors import ProcessorError
from processors.sandbox import execute_sandbox
from .models import FileAsset,PagePreview
from .services import storage_path
from . import storage
from .errors import DomainError
from .secrets import get_secret,decrypt


@transaction.atomic
def preview_asset(account,asset_id,page=1,secret_id=None):
    asset=FileAsset.objects.select_for_update().filter(account=account,pk=asset_id).first()
    if not asset: raise DomainError('not_found',404)
    if asset.state!='ready' or asset.expires_at<=timezone.now(): raise DomainError('file_expired',410)
    if type(page) is not int or page<1 or page>asset.page_count: raise DomainError('invalid_pages')
    if asset.mime_type!='application/pdf': raise DomainError('preview_unavailable',409)
    path=storage.local(asset.object_key)
    if not path.is_file(): raise DomainError('file_unavailable',404)
    deadline=asset.expires_at
    password=None
    if asset.metadata.get('encrypted'):
        handle=get_secret(account,secret_id or asset.metadata.get('password_secret_id'),asset=asset)
        password=decrypt(handle)
        deadline=min(deadline,handle.expires_at)
    cached=PagePreview.objects.select_related('file').filter(asset=asset,page=page).first()
    if cached and cached.file.state=='ready' and cached.file.expires_at>timezone.now() and storage.exists(cached.file.object_key): return cached.file
    if cached:
        storage.delete(cached.file.object_key)
        cached.file.delete()
    scratch_root=storage_path('scratch');scratch_root.mkdir(parents=True,exist_ok=True,mode=0o700)
    with tempfile.TemporaryDirectory(prefix='preview-',dir=scratch_root) as scratch:
        scratch=Path(scratch)
        try:
            render_source=path
            if password:
                decrypted=execute_sandbox('pdf.unlock_known',[path],{},scratch/'decrypted',secret=password)
                render_source=Path(decrypted['artifacts'][0]['path'])
            result=execute_sandbox('pdf.to_images',[render_source],{'pages':str(page),'format':'png','dpi':96},scratch/'render')
            image=Path(result['artifacts'][0]['path'])
            if not image.is_file() or not image.resolve().is_relative_to(scratch.resolve()): raise DomainError('invalid_output')
            if result['artifacts'][0]['mime_type']=='application/zip':
                with zipfile.ZipFile(image) as archive:
                    entries=archive.infolist()
                    expected=f'page-{page:04d}.png'
                    if len(entries)!=1 or entries[0].filename!=expected or entries[0].file_size>20*1024*1024: raise DomainError('invalid_output')
                    payload=archive.read(expected)
                image=scratch/'preview.png'
                image.write_bytes(payload)
            elif result['artifacts'][0]['mime_type']!='image/png': raise DomainError('invalid_output')
            if image.stat().st_size>20*1024*1024: raise DomainError('preview_unavailable',409)
            key=f'previews/{account.id}/{asset.id}/{page}-{uuid.uuid4().hex}.png'
            target=storage_path(key);target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            shutil.copyfile(image,target);os.chmod(target,0o600)
            preview=FileAsset.objects.create(account=account,name=f'page-{page}.png',object_key=key,mime_type='image/png',size_bytes=target.stat().st_size,page_count=1,sha256=hashlib.sha256(target.read_bytes()).hexdigest(),metadata={'kind':'image','source_asset_id':str(asset.id),'page':page,'dpi':96},expires_at=deadline)
            PagePreview.objects.create(asset=asset,page=page,file=preview)
            storage.save(key,'image/png')
            return preview
        except ProcessorError as exc: raise DomainError(exc.code) from None
