"""Untrusted photos made safe to keep and to show."""
import io
import warnings


def clean_photo(raw, *, max_bytes, max_pixels, edge):
    """A JPEG, PNG or WebP decoded and re-encoded as a JPEG no larger than
    `edge` on either side, transparency on white. Re-encoding drops the location
    and every other piece of metadata. Raises ValueError for anything that is
    not such a picture."""
    from PIL import Image, ImageOps
    if not raw or len(raw) > max_bytes:
        raise ValueError('size')
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(raw), formats=['JPEG', 'PNG', 'WEBP']) as picture:
            if picture.width * picture.height > max_pixels:
                raise ValueError('pixels')
            picture.load()
            turned = ImageOps.exif_transpose(picture)
            if turned.mode.startswith('I'):
                # 16-bit grey: scaled to 8 bits, not clipped to white. A
                # transparent grey is matched at full depth, before scaling.
                import numpy
                key = turned.info.get('transparency')
                wide = turned.convert('I')
                turned = wide.point(lambda value: value / 257).convert('L')
                turned.info.pop('transparency', None)
                if isinstance(key, int):
                    alpha = Image.fromarray((numpy.asarray(wide) != key).astype('uint8') * 255)
                    turned = Image.merge('LA', (turned, alpha))
            if turned.mode in ('RGBA', 'LA', 'PA') or 'transparency' in turned.info:
                # Transparent parts on white: dropping the alpha would turn them black.
                turned = turned.convert('RGBA')
                clean = Image.new('RGB', turned.size, (255, 255, 255))
                clean.paste(turned, mask=turned.getchannel('A'))
            else:
                clean = turned.convert('RGB')
    clean.thumbnail((edge, edge))
    out = io.BytesIO()
    # No `exif=`: nothing from the sender's file survives but the pixels.
    clean.save(out, 'JPEG', quality=85, optimize=True)
    return out.getvalue()
