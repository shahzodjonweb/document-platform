"""What a finished file is called when the customer gets it.

Every result is named here, when its task settles (services.settle_job), not
by the code that made it. The file on disk keeps a fixed name — result.pdf,
part-001.pdf, cv.pdf — so its storage key holds nothing the customer wrote;
the name they see lives only on the FileAsset, and reaches them as the
Telegram document's name and the download's Content-Disposition.

- Made from a file they gave: that file's name, what was done to it and a
  code — `report-compressed-3f9a1c.pdf`. A merge takes the first file's name.
- Made from nothing with a usable name (a topic, pasted text, phone photos
  called IMG_1234): the title, or the person a CV is about, when there is one,
  otherwise the service — `Photosynthesis-3f9a1c.pdf`, `photos-3f9a1c.pdf`.

The code is the start of the job's id: random, the same for every file of one
task, and made longer when the account already has a file of that name.

Letters of every alphabet stay, so an Uzbek or Russian name reads as written:
Telegram takes the name as UTF-8, and Django sends a non-ASCII download name as
RFC 5987 `filename*`. Everything else — quotes, slashes, dots, spaces, emoji,
control and direction marks — becomes a hyphen.
"""
import re
import unicodedata
from pathlib import Path

STEM_LIMIT = 60
# Uzbek Latin writes o‘, g‘ and the tutuq with these; inside a word they stay.
APOSTROPHES = '‘’ʻʼ'
# What a tool did, said after the name of the file it was done to.
DONE = {
    'pdf.compress': 'compressed', 'pdf.merge': 'merged', 'pdf.extract_pages': 'extracted',
    'pdf.delete_pages': 'pages-removed', 'pdf.reorder': 'reordered', 'pdf.rotate': 'rotated',
    'pdf.to_images': 'images', 'pdf.protect': 'protected', 'pdf.unlock_known': 'unlocked',
    'convert.pdf_to_xlsx': 'tables', 'ocr.extract_text': 'text', 'ocr.searchable_pdf': 'searchable',
    'editor.redact': 'redacted', 'ai.cv': 'CV',
}
# A result with no name of its own to go by, and nothing done to say.
SERVICE = {'ai.pdf_topic': 'document', 'ai.pptx': 'slides', 'pdf.images_to_pdf': 'photos'}
# The titles a document gets when nobody gave it one (apps/studio/domain.py).
UNTITLED = {'untitled document', 'untitled', 'document'}
EXTENSIONS = {
    'application/pdf': '.pdf', 'application/zip': '.zip', 'application/json': '.json', 'text/plain': '.txt',
    'image/png': '.png', 'image/jpeg': '.jpg',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
}
# The words cameras, phones, scanners and messengers name pictures with.
STOCK = {
    'img', 'image', 'images', 'photo', 'photos', 'pic', 'picture', 'pxl', 'dsc', 'dscn', 'dscf', 'dcim',
    'mvimg', 'mp', 'screenshot', 'screen', 'shot', 'scan', 'scanned', 'file', 'document', 'doc', 'untitled',
    'whatsapp', 'telegram', 'camera', 'cam', 'at', 'wa', 'jpeg', 'jpg', 'png', 'heic', 'copy',
    'фото', 'изображение', 'снимок', 'скриншот', 'скан', 'rasm', 'surat', 'skrinshot',
}
CODE = re.compile(r'-[0-9a-f]{6,32}(?:-\d+)?$')


def clean(text, limit=STEM_LIMIT):
    """`text` as part of a file name: letters and digits of any alphabet and `_`,
    with a hyphen for each run of anything else, at most `limit` characters."""
    text = unicodedata.normalize('NFC', str(text or ''))
    kept = []
    for index, char in enumerate(text):
        if char.isalnum() or char == '_':
            kept.append(char)
        elif char in APOSTROPHES + "'`":
            # Inside a word an apostrophe stays, typed ones as Uzbek writes them
            # (o‘, g‘, then ʼ), so a name reads as written; anywhere else it goes.
            if 0 < index < len(text) - 1 and text[index - 1].isalpha() and text[index + 1].isalpha():
                kept.append(char if char in APOSTROPHES else '‘' if text[index - 1] in 'oOgG' else 'ʼ')
        else:
            kept.append('-')
    stem = re.sub(r'[-_]*-[-_]*', '-', ''.join(kept)).strip('-_')
    if len(stem) > limit:
        # At a word's end when one is near enough, so a long title is cut, not chopped.
        cut = stem[:limit + 1]
        stem = (cut.rsplit('-', 1)[0] if '-' in cut[limit // 2:] else stem[:limit]).strip('-_')
    return stem


def stock(stem):
    """True for a picture's name nobody chose: IMG_1234, photo_2026-10-20_10-11-12, WhatsApp Image …"""
    for token in re.split(r'[\W_]+', stem.casefold()):
        if not token or token.isdigit() or token.rstrip('0123456789') in STOCK:
            continue
        if re.fullmatch(r'[0-9a-f]{4,}', token) and any(char.isdigit() for char in token):
            continue
        return False
    return True


def _base(name):
    """A file's name without its folder or extension. A browser uploads `"`, CR
    and LF in a name as %22, %0D and %0A (HTML's multipart encoding)."""
    name = re.sub(r'%(22|0D|0A)', lambda found: chr(int(found.group(1), 16)), str(name or ''), flags=re.I)
    return re.sub(r'\.[A-Za-z0-9]{1,5}$', '', Path(name.replace('\\', '/')).name)


def stem_of(asset):
    """The cleaned name of a file the customer gave, without its extension, or
    '' when it says nothing (a camera's name for a photo). One of our own results
    loses its code, so a result made from a result does not carry two."""
    from .models import Artifact
    base = _base(asset.name)
    if (asset.mime_type or '').startswith('image/') and stock(base):
        return ''
    stem = clean(base)
    if CODE.search(stem) and Artifact.objects.filter(file_id=asset.pk).exists():
        stem = CODE.sub('', stem)
    return stem


def _extension(output):
    suffix = Path(str(output.get('path') or output.get('name') or '')).suffix.lower()
    if re.fullmatch(r'\.[a-z0-9]{1,5}', suffix):
        return suffix
    return EXTENSIONS.get(str(output.get('mime_type') or '').split(';')[0].strip(), '')


def _parts(job, output, index, count):
    """The name's stem and what was done, before the code."""
    from apps.studio.domain import GENERATION_IDS
    from .models import FileAsset
    feature = job.feature_id
    if feature in GENERATION_IDS:
        # A CV's title is the person's name. With no name, a CV made from an old
        # CV or a LinkedIn export goes by that file.
        title = str(output.get('title') or '').strip()
        stem = '' if title.casefold() in UNTITLED else clean(title)
        source = _base(output.get('source_name'))
        stem = stem or ('' if stock(source) else clean(source))
        done = 'outline' if (job.parameters or {}).get('stage') == 'outline' else DONE.get(feature, '')
    else:
        ids = [str(value) for value in job.input_ids or []]
        assets = {str(asset.pk): asset for asset in FileAsset.objects.filter(account_id=job.account_id, pk__in=ids)}
        first = next((assets[value] for value in ids if value in assets), None)
        stem = stem_of(first) if first else ''
        done = f'part-{index + 1}' if feature == 'pdf.split' else DONE.get(feature) or ('edited' if feature.startswith('editor.') else '')
    if count > 1 and feature != 'pdf.split':
        done = '-'.join(filter(None, (done, str(index + 1))))
    if not stem and not done:
        stem = SERVICE.get(feature, 'result')
    # Compressing a compressed file says so once.
    if done and (stem.casefold() == done.casefold() or stem.casefold().endswith('-' + done.casefold())):
        done = ''
    return stem, done


def result_name(job, output, index=0, count=1):
    """The download name of the `index`th of `count` results of `job`, unique
    among the account's files (see the module docstring)."""
    from .models import FileAsset
    stem, done = _parts(job, output, index, count)
    extension = _extension(output)
    code = job.pk.hex

    def build(tail):
        return '-'.join(filter(None, (stem, done, tail))) + extension

    taken = FileAsset.objects.filter(account_id=job.account_id)
    for size in (6, 10, 32):
        name = build(code[:size])
        if not taken.filter(name=name).exists():
            return name
    number = 2
    while taken.filter(name=build(f'{code}-{number}')).exists():
        number += 1
    return build(f'{code}-{number}')


def preview_name(asset, page):
    """A page picture of `asset`: its name, the page and the start of its id."""
    return '-'.join(filter(None, (clean(_base(asset.name)), f'page-{page}', asset.pk.hex[:6]))) + '.png'
