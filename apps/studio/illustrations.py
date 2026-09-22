"""One bounded supporting illustration per confirmed job; no URL fetch fallback."""
import base64
import io
import json
import urllib.request
from PIL import Image
from apps.core.errors import DomainError
from .provider import _NoRedirect
from .models import ProviderUsage


def require_configuration(config):
    if config['mode']!='openai' or not config.get('api_key') or not config.get('image_model'):
        raise DomainError('image_provider_not_configured',409)


def generate_image(config,prompt,request_id):
    require_configuration(config)
    if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>4000:raise DomainError('invalid_parameters')
    body={'model':config['image_model'],'prompt':prompt,'n':1,'size':'1024x1024','quality':'low','output_format':'png'}
    try:
        request=urllib.request.Request('https://api.openai.com/v1/images/generations',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+config['api_key'],'Content-Type':'application/json','Idempotency-Key':str(request_id)})
        with urllib.request.build_opener(_NoRedirect).open(request,timeout=120) as response:raw=response.read(12_000_001)
        if len(raw)>12_000_000:raise ValueError()
        result=json.loads(raw);items=result['data']
        if len(items)!=1 or not isinstance(items[0].get('b64_json'),str):raise ValueError()
        decoded=base64.b64decode(items[0]['b64_json'],validate=True)
        if len(decoded)>8_000_000:raise ValueError()
        with Image.open(io.BytesIO(decoded)) as picture:
            if picture.format!='PNG' or picture.size!=(1024,1024) or getattr(picture,'n_frames',1)!=1:raise ValueError()
            picture.load();clean=io.BytesIO();picture.convert('RGB').save(clean,format='PNG')
        usage=result.get('usage',{})
        if not isinstance(usage,dict):raise ValueError()
        safe={key:usage.get(key,0) for key in ('input_tokens','output_tokens')}
        if any(type(value) is not int or not 0<=value<=1_000_000 for value in safe.values()):raise ValueError()
        return clean.getvalue(),safe
    except Exception:raise DomainError('provider_failed',502,retryable=True) from None


def execute_illustration(job,data,config,output_dir):
    if job.policy.get('provider_image_model')!=config.get('image_model'):raise DomainError('provider_changed',409)
    try:
        raw,usage=generate_image(config,data['prompt'],job.id)
        ProviderUsage.objects.create(job=job,provider='openai_images',model=config['image_model'],outcome='succeeded',**usage)
        path=output_dir/'illustration.png';path.write_bytes(raw)
        return {'artifacts':[{'path':str(path),'name':path.name,'mime_type':'image/png','page_count':1,'role':'user_document','metadata':{'kind':'image','width':1024,'height':1024}}], 'actual_meters':dict(job.meters),'metadata':{'engine':'openai_images','warnings':[]}}
    except Exception:
        ProviderUsage.objects.create(job=job,provider='openai_images',model=config.get('image_model',''),outcome='failed')
        raise
