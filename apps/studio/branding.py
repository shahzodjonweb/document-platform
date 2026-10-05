"""Owned, bounded branding assets; no remote URLs or client filesystem paths."""
import hashlib
import io
import re
from PIL import Image, ImageOps
from apps.core.errors import DomainError
from apps.core.services import owned_assets
from apps.core import storage


def prepare_branding(account, feature_id, options):
    from .domain import allowed
    options=dict(options)
    branding=options.get('branding')
    if not branding:
        options.pop('branding',None)
        return options
    if not isinstance(branding,dict) or set(branding)-{'name','accent','logo_asset_id','logo_sha256'}:
        raise DomainError('invalid_parameters')
    permission='teacher.branding' if feature_id.startswith('teacher.') else 'template.branding'
    if not allowed(account,permission):raise DomainError('feature_not_in_plan',403)
    name=branding.get('name','');accent=branding.get('accent',options['template_style']['accent'])
    if not isinstance(name,str) or len(name)>120 or any(ord(char)<32 for char in name):raise DomainError('invalid_parameters')
    if not isinstance(accent,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',accent):raise DomainError('invalid_parameters')
    clean={'name':name.strip(),'accent':accent}
    if branding.get('logo_asset_id'):
        asset=_logo_asset(account,branding['logo_asset_id'])
        if branding.get('logo_sha256') and branding['logo_sha256']!=asset.sha256:raise DomainError('file_changed',409)
        clean.update(logo_asset_id=str(asset.id),logo_sha256=asset.sha256)
    options['branding']=clean
    return options


def _logo_asset(account,identifier):
    asset=owned_assets(account,[identifier])[0]
    if asset.mime_type not in ('image/png','image/jpeg','image/webp') or asset.size_bytes>2*1024*1024:
        raise DomainError('invalid_image')
    width,height=asset.metadata.get('width',0),asset.metadata.get('height',0)
    if not 0<width*height<=4_000_000:raise DomainError('image_pixel_limit')
    return asset


def generation_inputs(data):
    ids=list(data['source_ids'])
    logo=data['options'].get('branding',{}).get('logo_asset_id')
    if logo and logo not in ids:ids.append(logo)
    return ids


def render_style(account,data,feature_id="ai.pdf_text"):
    style=dict(data['options'].get('template_style',{}))
    brand=data['options'].get('branding',{})
    if not brand:return style
    # Revalidate entitlement/expiry and immutable asset bytes after queuing.
    prepare_branding(account,feature_id,data['options'])
    # A brand colour is a fact about the customer: it beats a deck design's accent.
    style.update(accent=brand['accent'],brand_name=brand['name'],accent_fixed=True)
    if brand.get('logo_asset_id'):
        asset=_logo_asset(account,brand['logo_asset_id'])
        path=storage.local(asset.object_key)
        if path.stat().st_size>2*1024*1024:raise DomainError('invalid_image')
        with path.open('rb') as source:raw=source.read(2*1024*1024+1)
        if len(raw)>2*1024*1024:raise DomainError('invalid_image')
        if hashlib.sha256(raw).hexdigest()!=brand['logo_sha256']:raise DomainError('file_changed',409)
        try:
            with Image.open(io.BytesIO(raw)) as picture:
                if picture.width*picture.height>4_000_000 or getattr(picture,'n_frames',1)!=1:raise ValueError()
                picture=ImageOps.exif_transpose(picture).convert('RGBA');picture.thumbnail((640,240))
                output=io.BytesIO();picture.save(output,format='PNG');style['logo_png']=output.getvalue()
        except Exception:raise DomainError('invalid_image') from None
    return style
