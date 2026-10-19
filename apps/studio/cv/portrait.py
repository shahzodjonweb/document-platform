"""The customer's portrait on a CV: which uploads may become one, and the square that is placed.

A portrait is an asset the customer uploaded (a JPG or PNG sent in the chat or
in the Studio), named by `options.portrait_asset_id`. When a draft is prepared
the asset is checked once — the customer's own, still there, a JPEG or PNG
(WebP would open nowhere in the renderer), at most 5 MB and 6 megapixels — and
its fingerprint is pinned into `options.portrait_sha256`; the quote lists it
with the draft's other inputs. At render time the bytes are read again and
must still match the pin.

A portrait is a nice-to-have, never a reason to lose a CV: a photo that cannot
be read at render time leaves the CV without one and the job warns
`cv_photo_unusable`; a change to a CV, or an update of a new one, whose photo
has expired drops it and records `cv_photo_gone` in `options.cv_warnings` for
the pipeline to pass on. It is therefore not one of the quote's input files,
whose expiry would fail the quote or the job: the draft pins its fingerprint,
the quote pins the draft, and `load` checks the bytes against the pin.
Whatever the source file carried (EXIF, location, comments) does not survive:
the placed image is a fresh JPEG of the pixels only; a transparent PNG (a
cut-out with its background removed) is laid on white first.
"""
import hashlib
import io
import re
import warnings

from apps.core.errors import DomainError

CV = 'ai.cv'
MIME_TYPES = ('image/jpeg', 'image/png')
MAX_BYTES = 5 * 1024 * 1024
LONG_EDGE = 600
MAX_JPEG = 250_000
UNUSABLE = 'cv_photo_unusable'
GONE = 'cv_photo_gone'


def square(raw):
    """Untrusted image bytes as the square JPEG a template places, or None.

    Turned upright by its EXIF orientation, cropped to a square across the
    middle — a little above the middle on a tall photo, where the face is —
    and re-encoded by `photos.prepare` without anything from the source file.
    """
    from PIL import Image, ImageOps
    from apps.studio import photos
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw), formats=['JPEG', 'PNG']) as picture:
                if picture.width * picture.height > photos.SOURCE_PIXELS or getattr(picture, 'n_frames', 1) != 1:
                    return None
                picture.load()
                upright = ImageOps.exif_transpose(picture)
                if upright.has_transparency_data:
                    # A cut-out keeps black (or palette entry 0) under its
                    # transparent pixels: it goes on white, as on paper.
                    rgba = upright.convert('RGBA')
                    upright = Image.alpha_composite(Image.new('RGBA', rgba.size, (255, 255, 255, 255)), rgba)
                upright = upright.convert('RGB')
        width, height = upright.size
        side = min(width, height)
        left = (width - side) // 2
        top = round((height - side) * (0.3 if height > width else 0.5))
        cropped = upright.crop((left, top, left + side, top + side))
        cropped.thumbnail((LONG_EDGE, LONG_EDGE))
        buffer = io.BytesIO()
        cropped.save(buffer, 'PNG')
        return photos.prepare(buffer.getvalue(), long_edge=LONG_EDGE, max_bytes=MAX_JPEG)
    except (ValueError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return None


def _asset(account, identifier):
    from apps.core.services import owned_assets
    from apps.studio import photos
    asset = owned_assets(account, [identifier])[0]
    if asset.mime_type not in MIME_TYPES or asset.size_bytes > MAX_BYTES:
        raise DomainError('invalid_image')
    width, height = asset.metadata.get('width', 0), asset.metadata.get('height', 0)
    if not 0 < width * height <= photos.SOURCE_PIXELS:
        raise DomainError('image_pixel_limit')
    return asset


# A change asking for the CV without its photo: "Rasmsiz qiling", "Уберите фото",
# "Remove the photo". Never a skill, a course or a job with photo in it:
# "фотошоп", "Fotografiya bo‘yicha kurs", "фотограф". Read on language.normalised text.
_PHOTO_UZ = r"(?:rasm|surat|foto(?:surat)?)(?:im|ingiz)?(?:ni)?"
_PHOTO_UZ_CYRILLIC = r"(?:расм|сурат|фото(?:сурат)?)(?:им|ингиз)?(?:ни)?"
WITHOUT_PHOTO = re.compile(
    r"(?<![\wЀ-ӿ'])(?:(?:rasm|surat|foto(?:surat)?)siz|(?:расм|сурат|фото(?:сурат)?)сиз"
    r"|" + _PHOTO_UZ + r"\s+(?:olib\s+tashla|o'chir|olma|qo'yma|kerak\s+emas|bo'lmasin|keragi\s+yo'q)\w*"
    r"|" + _PHOTO_UZ_CYRILLIC + r"\s+(?:олиб\s+ташла|ўчир|олма|қўйма|керак\s+эмас|бўлмасин)\w*"
    r"|без\s+(?:моего\s+|мое[йг]о?\s+)?фото(?:графи[июй])?"
    r"|(?:убер|убр|удал)\w*\s+(?:мо[её]\s+|мою\s+|это\s+)?фото(?:графи[июя])?"
    r"|фото(?:графи[ия])?\s+(?:не\s+нужн\w*|не\s+надо|убер\w*|убр\w*|удал\w*)"
    r"|(?:remove|delete|drop|take\s+(?:out|off))\s+(?:my\s+|the\s+|this\s+)?(?:profile\s+)?(?:photo|picture|portrait)s?"
    r"|no\s+(?:photo|picture|portrait)|without\s+(?:a\s+|my\s+|the\s+)?(?:photo|picture|portrait))"
    r"(?![\wЀ-ӿ'])", re.IGNORECASE)


def asks_without_photo(request):
    """Whether a change to a CV asks for it without its photo."""
    from apps.studio.language import normalised
    return WITHOUT_PHOTO.search(' '.join(normalised(request or '').split())) is not None


def prepare(account, fid, options, before_options=None, portrait_removed=False, current=None):
    """`options` with the portrait checked and pinned, for a new draft, an update or a change.

    `before_options` are the options of the CV being changed (None for a new
    draft or an update of one); `portrait_removed` says the change asked for no
    photo. `current` are the options of the draft being updated, when it is
    one: the photo it already carries is left out with `cv_photo_gone` once it
    has expired, as a change's is, and only a photo given anew is refused.
    Only a CV takes a portrait: on any other service the key is refused. The
    fingerprint is always the server's; one a client sends is ignored.
    `options.cv_warnings` is written afresh by every call.
    """
    options = dict(options or {})
    given = options.get('portrait_asset_id')
    if fid != CV:
        if given or options.get('portrait_sha256'):
            raise DomainError('invalid_parameters')
        for key in ('portrait_asset_id', 'portrait_sha256'):
            options.pop(key, None)
        return options
    if given is not None and not isinstance(given, str):
        raise DomainError('invalid_parameters')
    for key in ('portrait_sha256', 'cv_warnings'):
        options.pop(key, None)
    before = before_options if isinstance(before_options, dict) else None
    inherited = str((before or {}).get('portrait_asset_id') or '')
    identifier = str(given or '') or inherited
    if not identifier or (before is not None and portrait_removed):
        options.pop('portrait_asset_id', None)
        return options
    kept = before if before is not None else current if isinstance(current, dict) else None
    if kept is not None and identifier == str(kept.get('portrait_asset_id') or ''):
        # A change keeps the photo the CV was made with, and an update the photo
        # the draft has, while it is still there and unchanged; one that has
        # gone is left out, not a refusal.
        try:
            asset = _asset(account, identifier)
            pinned = kept.get('portrait_sha256')
            if pinned and pinned != asset.sha256:
                raise DomainError('file_changed', 409)
        except DomainError:
            options.pop('portrait_asset_id', None)
            options['cv_warnings'] = [GONE]
            return options
    else:
        asset = _asset(account, identifier)
    options.update(portrait_asset_id=str(asset.id), portrait_sha256=asset.sha256)
    return options


def load(account, data):
    """The placed portrait for a draft's payload, and the warnings to pass on: (photo or None, [codes]).

    No portrait asked for is (None, []). One asked for that cannot be used —
    gone, changed since the quote, unreadable — is (None, ['cv_photo_unusable'])
    and the CV is made without it. One that is used is kept for another day,
    as a job's input files are when it is settled, so a change made to the CV
    the next day still has it.
    """
    from apps.core import storage
    options = (data or {}).get('options') or {}
    identifier, pinned = options.get('portrait_asset_id'), options.get('portrait_sha256')
    if not identifier:
        return None, []
    try:
        asset = _asset(account, identifier)
        path = storage.local(asset.object_key)
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            raise ValueError('portrait_size')
        with path.open('rb') as source:
            raw = source.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != (pinned or asset.sha256):
            raise ValueError('portrait_changed')
    except (DomainError, ValueError, OSError):
        return None, [UNUSABLE]
    placed = square(raw)
    if not placed:
        return None, [UNUSABLE]
    from datetime import timedelta
    from django.utils import timezone
    from apps.core.models import FileAsset
    FileAsset.objects.filter(pk=asset.pk, expires_at__lt=timezone.now() + timedelta(hours=24)).update(
        expires_at=timezone.now() + timedelta(hours=24))
    return placed, []
