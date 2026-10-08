"""Bounded, real PDF operations; no database, transport or billing decisions.

Paths are trusted private-storage paths supplied by the worker, never parameters
accepted from a client. Every output is reopened before its manifest is returned.
"""
from __future__ import annotations

import importlib.metadata
from contextlib import closing
import io
import logging
import math
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
import warnings
import zipfile
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree

from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_PAGES = 1000
MAX_INPUTS = 1000
MAX_INPUT_BYTES = 512 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_RENDER_PIXELS = 200_000_000
MAX_OUTPUT_BYTES = 512 * 1024 * 1024
MAX_ZIP_EXPANDED = 256 * 1024 * 1024
MAX_ZIP_MEMBERS = 3000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
logging.getLogger('pypdf').setLevel(logging.CRITICAL)


class ProcessorError(Exception):
    """Stable safe codes. Never include filenames, content or passwords."""
    def __init__(self, code: str, message: str | None = None):
        self.code = code
        self.message = message or code.replace('_', ' ').capitalize()
        super().__init__(self.message)


def _schema(properties=None, required=()):
    return {'type': 'object', 'additionalProperties': False,
            'properties': properties or {}, 'required': list(required)}


PAGES = {'type': 'string', 'maxLength': 6000, 'description': 'One-based pages: 1,3-5 or all'}
PARAMETER_SCHEMAS = {
    'pdf.merge': _schema(),
    'pdf.compress': _schema(),
    'pdf.split': _schema({'ranges': {'type': 'array', 'items': PAGES, 'maxItems': MAX_PAGES}}),
    'pdf.extract_pages': _schema({'pages': PAGES}, ('pages',)),
    'pdf.delete_pages': _schema({'pages': PAGES}, ('pages',)),
    'pdf.reorder': _schema({'order': {'type': 'array', 'items': {'type': 'integer', 'minimum': 1}, 'maxItems': MAX_PAGES}}, ('order',)),
    'pdf.rotate': _schema({'pages': PAGES, 'angle': {'type': 'integer', 'enum': [90, 180, 270]}}),
    'pdf.images_to_pdf': _schema({
        'paper_size': {'type': 'string', 'enum': ['fit', 'A4', 'Letter', 'original'], 'default': 'fit', 'description': 'Fit uses ISO A4 for a detected document when auto-crop is on; other images keep their aspect with an 842-point long edge.'},
        'orientation': {'type': 'string', 'enum': ['auto', 'portrait', 'landscape'], 'default': 'auto'},
        'margin': {'type': 'number', 'minimum': 0, 'maximum': 72, 'default': 0},
        'auto_crop': {'type': 'boolean', 'default': True, 'description': 'Crop and straighten a confidently detected document; otherwise keep the full image.'},
        'enhance_text': {'type': 'boolean', 'default': True, 'description': 'Reduce shadows and improve text contrast on every page; a detected document becomes clean white paper.'}}),
    'pdf.to_images': _schema({'pages': PAGES, 'format': {'type': 'string', 'enum': ['png', 'jpg']},
        'dpi': {'type': 'integer', 'minimum': 72, 'maximum': 200}}),
    # Password material is accepted ONLY as a separate in-memory secret argument.
    'pdf.protect': _schema(), 'pdf.unlock_known': _schema(),
    'convert.word_to_pdf': _schema(), 'convert.pptx_to_pdf': _schema(),
}
from .advanced import SCHEMAS as ADVANCED_SCHEMAS
from .editor import SCHEMAS as EDITOR_SCHEMAS
PARAMETER_SCHEMAS.update(ADVANCED_SCHEMAS)
PARAMETER_SCHEMAS.update(EDITOR_SCHEMAS)


@lru_cache(maxsize=1)
def office_runtime() -> dict[str, Any]:
    """Probe the trusted deployment-configured executable, never client input."""
    configured = os.environ.get('PDFMASTER_SOFFICE_BIN')
    executable = configured or shutil.which('libreoffice') or shutil.which('soffice')
    if not executable or not Path(executable).is_file() or not os.access(executable, os.X_OK):
        return {'available': False, 'reason': 'engine_unavailable'}
    try:
        probe = subprocess.run([executable, '--version'], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=8, check=False)
        version = probe.stdout[:1024].decode('utf-8', errors='replace').strip()
        if probe.returncode or not version.startswith(('LibreOffice', 'LibreOfficeDev')):
            return {'available': False, 'reason': 'engine_unavailable'}
        return {'available': True, 'executable': executable, 'version': version,
                'development_only': any(part in version.lower() for part in ('alpha', 'beta', 'dev'))}
    except (OSError, subprocess.TimeoutExpired):
        return {'available': False, 'reason': 'engine_unavailable'}


def capabilities() -> dict[str, dict[str, Any]]:
    result = {}
    for feature, schema in PARAMETER_SCHEMAS.items():
        office = feature in ('convert.word_to_pdf','convert.pptx_to_pdf')
        runtime = office_runtime() if office else {}
        available = not office or runtime['available']
        result[feature] = {'available': available, 'parameters': schema,
            'engine': 'libreoffice' if office else ('pdfium' if feature == 'pdf.to_images' else ('reportlab/pillow' if feature == 'pdf.images_to_pdf' else 'pypdf')),
            'requires_secret': feature in ('pdf.protect', 'pdf.unlock_known'),
            'production_qualified': False,
            'reason': None if available else 'engine_unavailable'}
        if office:
            result[feature].update({k: v for k, v in runtime.items() if k != 'executable'})
        if feature.startswith('ocr.'):
            from .advanced import tesseract_runtime
            result[feature].update({k:v for k,v in tesseract_runtime().items() if k!='executable'})
        if feature=='convert.pdf_to_docx':result[feature].update(engine='pypdf/python-docx',limitations=['editable_text_reflowed_layout_not_preserved'])
        if feature=='convert.pdf_to_xlsx':result[feature].update(engine='pdfplumber/openpyxl',limitations=['native_tables_only_review_cells'])
        if feature in EDITOR_SCHEMAS:result[feature].update(engine='pypdf/reportlab',coordinate_system='top_left_pdf_points')
    return result


def _regular_file(value: str | Path) -> Path:
    path = Path(value)
    if path.is_symlink() or not path.is_file():
        raise ProcessorError('invalid_file')
    if path.stat().st_size <= 0 or path.stat().st_size > MAX_FILE_BYTES:
        raise ProcessorError('file_size_limit')
    return path


def _check_pdf_actions(reader: PdfReader, allow_forms=False) -> None:
    root = reader.root_object
    form = root.get('/AcroForm')
    if form and form.get_object().get('/XFA'):
        raise ProcessorError('active_content_unsupported')
    if form and form.get_object().get('/Fields') and not allow_forms:
        # Page reconstruction must not silently orphan canonical field trees or
        # invalidate signatures. Qualify preservation before accepting forms.
        raise ProcessorError('interactive_pdf_unsupported')
    if form and any(field.get('/FT')=='/Sig' and field.get('/V') for field in (reader.get_fields() or {}).values()):
        raise ProcessorError('signed_pdf_unsupported')
    if form:
        pending=list(form.get_object().get('/Fields',[]));seen=set()
        while pending:
            node=pending.pop().get_object()
            identity=id(node)
            if identity in seen:continue
            seen.add(identity)
            if len(seen)>10000:raise ProcessorError('active_content_unsupported')
            if '/AA' in node or '/A' in node:raise ProcessorError('active_content_unsupported')
            pending.extend(node.get('/Kids',[]))
    names = root.get('/Names', {})
    if hasattr(names, 'get_object'):
        names = names.get_object()
    if any(k in root for k in ('/OpenAction', '/AA')) or any(k in names for k in ('/JavaScript', '/EmbeddedFiles')):
        raise ProcessorError('active_content_unsupported')
    for page in reader.pages:
        if '/AA' in page:
            raise ProcessorError('active_content_unsupported')
        for raw_annotation in page.get('/Annots', []):
            annotation = raw_annotation.get_object()
            if '/AA' in annotation or annotation.get('/Subtype') in ('/FileAttachment', '/RichMedia', '/Movie', '/Sound'):
                raise ProcessorError('active_content_unsupported')
            action = annotation.get('/A')
            if action:
                from urllib.parse import urlsplit
                action=action.get_object()
                if action.get('/S') not in ('/URI','/GoTo') or '/Next' in action:
                    raise ProcessorError('active_content_unsupported')
                if action.get('/S')=='/URI' and urlsplit(str(action.get('/URI',''))).scheme.lower() not in ('http','https','mailto'):
                    raise ProcessorError('active_content_unsupported')


def _pdf_reader(path: Path, password: str | None = None, allow_locked=False, allow_forms=False):
    try:
        reader = PdfReader(path, strict=True)
        if reader.is_encrypted:
            if not password:
                if allow_locked:
                    return reader
                raise ProcessorError('password_required')
            if not reader.decrypt(password):
                raise ProcessorError('password_invalid')
        count = len(reader.pages)
        if not 0 < count <= MAX_PAGES:
            raise ProcessorError('page_limit')
        for page in reader.pages:
            w, h = float(page.mediabox.width), float(page.mediabox.height)
            unit = float(page.get('/UserUnit', 1))
            if not all(math.isfinite(v) for v in (w, h, unit)) or min(w, h, unit) <= 0 or max(w * unit, h * unit) > 14_400:
                raise ProcessorError('page_dimensions_invalid')
        _check_pdf_actions(reader,allow_forms=allow_forms)
        return reader
    except ProcessorError:
        raise
    except Exception:
        raise ProcessorError('invalid_pdf') from None


def _office_inspect(path: Path) -> dict:
    """Read-only OOXML preflight. Nothing is extracted to the filesystem."""
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ZIP_MEMBERS:
                raise ProcessorError('archive_limit')
            names = set()
            expanded = 0
            for entry in entries:
                name = entry.filename
                pure = PurePosixPath(name)
                mode = entry.external_attr >> 16
                if '\\' in name or pure.is_absolute() or '..' in pure.parts or ':' in name or stat.S_ISLNK(mode) or name in names:
                    raise ProcessorError('unsafe_archive')
                names.add(name)
                expanded += entry.file_size
                if entry.flag_bits & 1 or entry.file_size > MAX_ZIP_EXPANDED or expanded > MAX_ZIP_EXPANDED or entry.file_size > max(1024 * 1024, entry.compress_size * 100):
                    raise ProcessorError('archive_limit')
                low = name.lower()
                if any(x in low for x in ('vbaproject', 'activex', '/embeddings/')) or low.endswith('.bin'):
                    raise ProcessorError('active_content_unsupported')
            if '[Content_Types].xml' not in names:
                raise ProcessorError('unsupported_type')
            for entry in entries:
                # DTD/entities are never needed for accepted Office XML.
                if entry.filename.endswith(('.xml', '.rels')):
                    payload = archive.read(entry)
                    upper = payload.upper()
                    if b'<!DOCTYPE' in upper or b'<!ENTITY' in upper or b'MACROENABLED' in upper:
                        raise ProcessorError('active_content_unsupported')
                    if entry.filename.endswith('.rels'):
                        xml = ElementTree.fromstring(payload)
                        if any(n.attrib.get('TargetMode') == 'External' for n in xml):
                            raise ProcessorError('external_content_unsupported')
            if 'word/document.xml' in names:
                return {'mime_type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'page_count': None, 'kind': 'docx'}
            if 'ppt/presentation.xml' in names:
                pages = sum(bool(re.fullmatch(r'ppt/slides/slide\d+\.xml', n)) for n in names)
                if not 0 < pages <= MAX_PAGES:
                    raise ProcessorError('page_limit')
                return {'mime_type': 'application/vnd.openxmlformats-officedocument.presentationml.presentation', 'page_count': pages, 'kind': 'pptx'}
    except ProcessorError:
        raise
    except Exception:
        raise ProcessorError('invalid_archive') from None
    raise ProcessorError('unsupported_type')


def inspect_file(path: str | Path, password: str | None = None, *, office_preflight: bool = True, allow_forms: bool = True) -> dict[str, Any]:
    path = _regular_file(path)
    with path.open('rb') as stream:
        header = stream.read(16)
    base = {'size_bytes': path.stat().st_size, 'encrypted': False}
    if header.startswith(b'%PDF-'):
        reader = _pdf_reader(path, password, allow_locked=True,allow_forms=allow_forms)
        if reader.is_encrypted and not password:
            return {**base, 'mime_type': 'application/pdf', 'page_count': None, 'encrypted': True, 'kind': 'pdf', 'password_required': True}
        fields=reader.get_fields() or {}
        return {**base, 'mime_type': 'application/pdf', 'page_count': len(reader.pages), 'encrypted': reader.is_encrypted, 'kind': 'pdf',
            'has_forms':bool(fields),'form_fields':[{'name':name,'type':str(field.get('/FT',''))} for name,field in fields.items()],
            'image_counts':[len(page.images) for page in reader.pages],
            'page_sizes':[{'width':float(page.cropbox.height if page.rotation%180 else page.cropbox.width),'height':float(page.cropbox.width if page.rotation%180 else page.cropbox.height)} for page in reader.pages]}
    if header.startswith(b'PK\x03\x04'):
        metadata = {**base, **_office_inspect(path)}
        if office_preflight and office_runtime()['available']:
            feature = 'convert.word_to_pdf' if metadata['kind'] == 'docx' else 'convert.pptx_to_pdf'
            # Temporary preflight PDFs are never exposed or persisted as assets.
            with tempfile.TemporaryDirectory(prefix='pdfmaster-office-preflight-') as scratch:
                artifacts = _office_pdf(path, feature, Path(scratch), metadata)
                metadata.update({'page_count': artifacts[0]['page_count'],
                    'preflight_kind': 'libreoffice_pdf', 'office_engine': office_runtime()['version'],
                    'office_development_only': office_runtime()['development_only']})
        return metadata
    if header.startswith((b'\x89PNG\r\n\x1a\n', b'\xff\xd8\xff', b'RIFF')):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(path, formats=['PNG', 'JPEG', 'WEBP']) as picture:
                    width, height = picture.size
                    if width * height > MAX_PIXELS or max(width, height) > 30_000 or getattr(picture, 'n_frames', 1) != 1:
                        raise ProcessorError('image_pixel_limit')
                    mime = Image.MIME[picture.format]
                    picture.verify()
            return {**base, 'mime_type': mime, 'page_count': 1, 'width': width, 'height': height, 'kind': 'image'}
        except ProcessorError:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise ProcessorError('image_pixel_limit') from None
        except Exception:
            raise ProcessorError('invalid_image') from None
    raise ProcessorError('unsupported_type')


def parse_pages(value: str, count: int, *, allow_all=True) -> list[int]:
    """Return zero-based page indexes in supplied order; duplicates are invalid."""
    if not isinstance(value, str) or not value or len(value) > 6000 or not 0 < count <= MAX_PAGES:
        raise ProcessorError('invalid_pages')
    if value.strip() == 'all' and allow_all:
        return list(range(count))
    indexes = []
    for part in value.split(','):
        match = re.fullmatch(r'\s*(\d{1,4})(?:\s*-\s*(\d{1,4}))?\s*', part)
        if not match:
            raise ProcessorError('invalid_pages')
        first, last = int(match[1]), int(match[2] or match[1])
        if not 1 <= first <= last <= count:
            raise ProcessorError('invalid_pages')
        indexes.extend(range(first - 1, last))
        if len(indexes) > count:
            raise ProcessorError('invalid_pages')
    if len(indexes) != len(set(indexes)):
        raise ProcessorError('invalid_pages')
    return indexes


def normalize_parameters(feature_id: str, parameters: dict | None, input_metadata: list[dict] | None = None) -> dict:
    if feature_id not in PARAMETER_SCHEMAS:
        raise ProcessorError('feature_unavailable')
    parameters = {} if parameters is None else parameters
    if feature_id in ADVANCED_SCHEMAS:
        from .advanced import normalize
        return normalize(feature_id,parameters,input_metadata)
    if feature_id in EDITOR_SCHEMAS:
        from .editor import normalize
        return normalize(feature_id,parameters,input_metadata)
    if not isinstance(parameters, dict) or any(k not in PARAMETER_SCHEMAS[feature_id]['properties'] for k in parameters):
        raise ProcessorError('invalid_parameters')
    normalized = dict(parameters)
    count = (input_metadata[0].get('page_count') if input_metadata else None)
    for field in PARAMETER_SCHEMAS[feature_id]['required']:
        if field not in parameters:
            raise ProcessorError('invalid_parameters')
    if feature_id in ('pdf.rotate', 'pdf.to_images'):
        normalized.setdefault('pages', 'all')
    if 'pages' in normalized:
        parse_pages(normalized['pages'], count or MAX_PAGES)
        if feature_id == 'pdf.delete_pages' and count and len(parse_pages(normalized['pages'], count)) == count:
            raise ProcessorError('empty_output')
    if feature_id == 'pdf.split' and 'ranges' in normalized:
        ranges = normalized['ranges']
        if not isinstance(ranges, list) or not 1 <= len(ranges) <= MAX_PAGES:
            raise ProcessorError('invalid_pages')
        for pages in ranges:
            parse_pages(pages, count or MAX_PAGES)
    if feature_id == 'pdf.reorder':
        order = normalized['order']
        if not isinstance(order, list) or not order or len(order) > MAX_PAGES or any(type(v) is not int for v in order):
            raise ProcessorError('invalid_pages')
        expected = count or len(order)
        if sorted(order) != list(range(1, expected + 1)):
            raise ProcessorError('invalid_pages')
    if feature_id == 'pdf.rotate':
        normalized.setdefault('angle', 90)
        if type(normalized['angle']) is not int or normalized['angle'] not in (90, 180, 270):
            raise ProcessorError('invalid_parameters')
    if feature_id == 'pdf.to_images':
        normalized.setdefault('format', 'png')
        normalized.setdefault('dpi', 96)
        if normalized['format'] not in ('png', 'jpg') or type(normalized['dpi']) is not int or not 72 <= normalized['dpi'] <= 200:
            raise ProcessorError('invalid_parameters')
    if feature_id == 'pdf.images_to_pdf':
        normalized.setdefault('paper_size', 'fit')
        normalized.setdefault('orientation', 'auto')
        normalized.setdefault('margin', 0)
        for field in ('auto_crop', 'enhance_text'):
            normalized.setdefault(field, True)
            if type(normalized[field]) is not bool:
                raise ProcessorError('invalid_parameters')
        if normalized['paper_size'] not in ('fit', 'A4', 'Letter', 'original') or normalized['orientation'] not in ('auto', 'portrait', 'landscape'):
            raise ProcessorError('invalid_parameters')
        margin = normalized['margin']
        if type(margin) not in (int, float) or not math.isfinite(margin) or not 0 <= margin <= 72:
            raise ProcessorError('invalid_parameters')
    return normalized


def _write_pdf(writer: PdfWriter, destination: Path, password=None, allow_forms=False):
    # Never retain source document info/XMP automatically in newly assembled files.
    writer.metadata = None
    writer.root_object.pop('/Metadata', None)
    with destination.open('xb') as stream:
        writer.write(stream)
    os.chmod(destination, 0o600)
    return _artifact(destination, password=password,allow_forms=allow_forms)


def _artifact(path: Path, page_count: int | None = None, password=None,allow_forms=False) -> dict:
    if path.stat().st_size > MAX_OUTPUT_BYTES:
        raise ProcessorError('output_size_limit')
    if path.suffix == '.pdf':
        info = inspect_file(path, password,allow_forms=allow_forms)
        if info.get('page_count') is None:
            raise ProcessorError('output_invalid')
    else:
        info = {'mime_type': 'application/zip', 'page_count': page_count, 'size_bytes': path.stat().st_size}
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise ProcessorError('output_invalid')
            if len(archive.infolist()) != page_count:
                raise ProcessorError('output_invalid')
            for entry in archive.infolist():
                if not re.fullmatch(r'page-\d{4}\.(png|jpg)', entry.filename):
                    raise ProcessorError('output_invalid')
                with archive.open(entry) as member, Image.open(member, formats=['PNG', 'JPEG']) as picture:
                    picture.verify()
    return {'path': str(path.resolve()), 'name': path.name, 'mime_type': info['mime_type'],
            'page_count': info['page_count'], 'size_bytes': info['size_bytes']}


def _page_encoding(picture):
    """Measure whether a page deflates well before choosing its PDF stream.

    ReportLab Flate-encodes a Pillow image's raw pixels, so a 12-megapixel
    camera photo became a 36 MB page. A cleaned document or a flat graphic
    deflates to a fraction of its size and stays lossless; anything with camera
    grain is re-encoded as a metadata-free JPEG stream instead.
    """
    import zlib
    width, height = picture.size
    rows = min(height, 48)
    raw = compressed = 0
    for fraction in (.12, .38, .62, .88):
        top = max(0, min(height - rows, round(height * fraction)))
        strip = picture.crop((0, top, width, top + rows)).tobytes()
        raw += len(strip)
        compressed += len(zlib.compress(strip, 1))
    return 'flate' if compressed <= raw * .35 else 'jpeg'


def _stripped_jpeg(data: bytes):
    """The upload's own DCT stream without any APPn/COM segment, or None.

    An untouched JPEG upload keeps every pixel this way, while EXIF, ICC,
    XMP and comment segments never reach the PDF. Adobe-marked files can be
    CMYK or inverted and are re-encoded instead.
    """
    if data[:2] != b'\xff\xd8':
        return None
    out = bytearray(b'\xff\xd8')
    index = 2
    while index + 4 <= len(data):
        if data[index] != 0xFF:
            return None
        marker = data[index + 1]
        if marker == 0xD9:
            out += data[index:index + 2]
            return bytes(out)
        if marker == 0xD8 or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            index += 2
            continue
        length = int.from_bytes(data[index + 2:index + 4], 'big')
        segment = data[index:index + 2 + length]
        if marker == 0xEE and b'Adobe' in segment:
            return None
        if not (0xE0 <= marker <= 0xEF or marker == 0xFE):
            out += segment
        index += 2 + length
        if marker == 0xDA:
            out += data[index:]
            return bytes(out)
    return None


def _page_image(picture, encoding, original=None):
    """Return the ReportLab image source for one page."""
    from reportlab.lib.utils import ImageReader
    if encoding != 'jpeg':
        return ImageReader(picture)
    if original is not None:
        return ImageReader(io.BytesIO(original))
    # Pillow copies a source comment into a new JPEG; drop every info field.
    picture.info.clear()
    buffer = io.BytesIO()
    picture.save(buffer, 'JPEG', quality=88, subsampling=0)
    buffer.seek(0)
    return ImageReader(buffer)


def _image_pdf(paths: list[Path], parameters: dict, out: Path):
    from reportlab import rl_config
    from reportlab.lib.pagesizes import A4, letter
    from reportlab.pdfgen.canvas import Canvas
    # Binary image streams: ASCII85 would inflate every page by a quarter.
    rl_config.useA85 = 0
    destination = out / 'images.pdf'
    canvas = Canvas(str(destination), pageCompression=1, invariant=1)
    outcomes = []
    layouts = []
    for path in paths:
        with Image.open(path, formats=['PNG', 'JPEG', 'WEBP']) as raw:
            # A plain upright RGB JPEG can be embedded as its own pixels.
            plain_jpeg = (raw.format == 'JPEG' and raw.mode == 'RGB'
                          and raw.getexif().get(0x0112, 1) == 1)
            picture = ImageOps.exif_transpose(raw)
            if picture.mode in ('I;16', 'I;16B', 'I;16L', 'I;16N', 'I'):
                # Pillow clips 16-bit samples at 255 when converting to RGB,
                # which turned a 16-bit scan into a white page. Rescale first:
                # full-range 16-bit data by 257, narrower data by its peak.
                import numpy as np
                samples = np.asarray(picture).astype(np.float32)
                peak = float(samples.max())
                if peak > 255:
                    samples = samples * (255 / (65535 if peak > 4095 else peak))
                picture = Image.fromarray(np.clip(samples, 0, 255).astype(np.uint8), 'L')
            # Composite alpha onto white and omit all EXIF/ICC metadata.
            if picture.mode in ('RGBA', 'LA') or 'transparency' in picture.info:
                rgba = picture.convert('RGBA')
                rgb = Image.new('RGB', picture.size, 'white')
                rgb.paste(rgba, mask=rgba.getchannel('A'))
                picture = rgb
            else:
                picture = picture.convert('RGB')
            from .document_scan import prepare_image
            picture, outcome = prepare_image(picture, auto_crop=parameters['auto_crop'],
                                               enhance_text=parameters['enhance_text'])
            outcomes.append(outcome)
            iw, ih = picture.size
            margin = parameters['margin']
            requested_paper = parameters['paper_size']
            automatic_a4 = (requested_paper == 'fit' and parameters['auto_crop']
                            and outcome['document_detected'])
            effective_paper = 'A4' if automatic_a4 else requested_paper
            if effective_paper == 'original':
                # Original means one image pixel per PDF point at 72 dpi, held
                # to the 200-inch PDF page limit for an unusually long panorama.
                original_scale = min(1., (14_400 - 2 * margin) / max(iw, ih))
                width = min(14_400., iw * original_scale + 2 * margin)
                height = min(14_400., ih * original_scale + 2 * margin)
            elif effective_paper == 'fit':
                # Match the processed image's shape without making high-resolution
                # uploads physically enormous. Explicit margins surround the image.
                fit_scale = 842 / max(iw, ih)
                width, height = iw * fit_scale + 2 * margin, ih * fit_scale + 2 * margin
                if ((parameters['orientation'] == 'landscape' and width < height)
                        or (parameters['orientation'] == 'portrait' and width > height)):
                    width, height = height, width
            else:
                width, height = A4 if effective_paper == 'A4' else letter
                landscape = parameters['orientation'] == 'landscape' or (parameters['orientation'] == 'auto' and iw > ih)
                if landscape:
                    width, height = height, width
            if max(width, height) > 14_400 or min(width - 2 * margin, height - 2 * margin) <= 0:
                raise ProcessorError('page_dimensions_invalid')
            scale = min((width - 2 * margin) / iw, (height - 2 * margin) / ih)
            x, y = (width - iw * scale) / 2, (height - ih * scale) / 2
            canvas.setPageSize((width, height))
            encoding = _page_encoding(picture)
            original = None
            if encoding == 'jpeg' and plain_jpeg and not outcome['cropped'] and not outcome['enhanced']:
                original = _stripped_jpeg(path.read_bytes())
            canvas.drawImage(_page_image(picture, encoding, original), x, y,
                iw * scale, ih * scale, mask='auto')
            layouts.append({'requested_paper_size': requested_paper,
                'effective_paper_size': effective_paper, 'automatic_a4': automatic_a4,
                'image_encoding': encoding,
                'page_size_points': [width, height],
                'image_placement_points': [x, y, iw * scale, ih * scale]})
            canvas.showPage()
    canvas.save()
    os.chmod(destination, 0o600)
    return [_artifact(destination)], {'image_processing': {
        'pages': outcomes,
        'layouts': layouts,
        'document_pages': sum(row['document_detected'] for row in outcomes),
        'cropped_pages': sum(row['cropped'] for row in outcomes),
        'enhanced_pages': sum(row['enhanced'] for row in outcomes)}}


def _pdf_images(path: Path, parameters: dict, out: Path, count: int):
    import pypdfium2 as pdfium
    indexes = parse_pages(parameters['pages'], count)
    scale = parameters['dpi'] / 72
    fmt = parameters['format']
    destination = out / 'pages.zip'
    total_pixels = 0
    total_bytes = 0
    with pdfium.PdfDocument(str(path)) as document, zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_STORED) as archive:
        document.init_forms()
        for index in indexes:
            with closing(document[index]) as page:
                width, height = page.get_size()
                pixels = math.ceil(width * scale) * math.ceil(height * scale)
                total_pixels += pixels
                if pixels > MAX_PIXELS or total_pixels > MAX_RENDER_PIXELS:
                    raise ProcessorError('render_pixel_limit')
                bitmap = page.render(scale=scale, rev_byteorder=True)
                try:
                    picture = bitmap.to_pil().convert('RGB')
                    buffer = io.BytesIO()
                    picture.save(buffer, format='PNG' if fmt == 'png' else 'JPEG', quality=90)
                    total_bytes += buffer.tell()
                    if total_bytes > MAX_OUTPUT_BYTES:
                        raise ProcessorError('output_size_limit')
                    archive.writestr(f'page-{index + 1:04d}.{fmt}', buffer.getvalue())
                finally:
                    bitmap.close()
    os.chmod(destination, 0o600)
    return [_artifact(destination, len(indexes))]



def _normalize_office_viewer_hint(path: Path) -> None:
    """Remove only older LibreOffice's default initial-page viewer destination.

    This runs exclusively on fresh converter output, never uploaded PDF inputs.
    Legacy LibreOffice emits [page-ref /XYZ null null 0] for its default view;
    this is a destination, not an action dictionary. Keep every other OpenAction
    unsupported, including GoTo dictionaries, scripts, launch and remote actions.
    """
    from pypdf.generic import ArrayObject,IndirectObject,NameObject,NullObject,NumberObject,FloatObject
    if path.stat().st_size>MAX_OUTPUT_BYTES:raise ProcessorError('output_size_limit')
    try:
        reader=PdfReader(path,strict=True)
        root=reader.root_object
        if '/OpenAction' not in root:return
        destination=root['/OpenAction']
        safe=(isinstance(destination,ArrayObject) and len(destination)==5
              and isinstance(destination[0],IndirectObject)
              and isinstance(destination[1],NameObject) and destination[1]=='/XYZ'
              and isinstance(destination[2],NullObject) and isinstance(destination[3],NullObject)
              and type(destination[4]) in (NumberObject,FloatObject) and destination[4]==0)
        if safe:
            safe=any(page.indirect_reference==destination[0] for page in reader.pages)
        if not safe:raise ProcessorError('active_content_unsupported')
        del root['/OpenAction']
        # A harmless hint must not hide unrelated active content. Validate the
        # complete remaining action policy before writing; _artifact reopens the
        # serialized output and checks page/dimension/size limits afterward.
        _check_pdf_actions(reader)
        normalized=path.with_suffix('.normalized.pdf')
        writer=PdfWriter(clone_from=reader)
        with normalized.open('xb') as stream:writer.write(stream)
        os.chmod(normalized,0o600)
        os.replace(normalized,path)
    except ProcessorError:
        raise
    except Exception:
        raise ProcessorError('invalid_pdf') from None

def _office_pdf(path: Path, feature_id: str, out: Path, metadata: dict):
    runtime = office_runtime()
    if not runtime['available']:
        raise ProcessorError('engine_unavailable')
    executable = runtime['executable']
    expected = 'docx' if feature_id == 'convert.word_to_pdf' else 'pptx'
    if metadata['kind'] != expected:
        raise ProcessorError('unsupported_type')
    # Caller must additionally provide OS-level no-network/read-only containment.
    with tempfile.TemporaryDirectory(prefix='office-', dir=out) as scratch:
        scratch = Path(scratch)
        source = scratch / f'input.{expected}'
        shutil.copyfile(path, source)
        profile = scratch / 'profile'
        try:
            completed = subprocess.run([executable, '-env:UserInstallation=' + profile.as_uri(),
                '--headless', '--nologo', '--nodefault', '--nofirststartwizard',
                '--convert-to', 'pdf', '--outdir', str(scratch), str(source)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=60, check=False, env={**os.environ, 'HOME': str(scratch)})
        except subprocess.TimeoutExpired:
            raise ProcessorError('processor_timeout') from None
        converted = scratch / 'input.pdf'
        if completed.returncode != 0 or not converted.is_file():
            raise ProcessorError('conversion_failed')
        _normalize_office_viewer_hint(converted)
        output = out / 'converted.pdf'
        shutil.move(converted, output)
        os.chmod(output, 0o600)
        return [_artifact(output)]


def execute(feature_id: str, input_paths: list[str | Path], parameters: dict | None,
            output_dir: str | Path, *, secret: str | None = None) -> dict:
    """Run one operation. Secret is ephemeral transport-only, never returned."""
    if not isinstance(input_paths, (list, tuple)) or not 1 <= len(input_paths) <= MAX_INPUTS:
        raise ProcessorError('invalid_inputs')
    paths = [_regular_file(path) for path in input_paths]
    if sum(path.stat().st_size for path in paths) > MAX_INPUT_BYTES:
        raise ProcessorError('file_size_limit')
    if feature_id not in ('pdf.merge', 'pdf.images_to_pdf') and feature_id not in EDITOR_SCHEMAS and len(paths) != 1:
        raise ProcessorError('invalid_inputs')
    if feature_id == 'pdf.merge' and len(paths) < 2:
        raise ProcessorError('invalid_inputs')
    if feature_id in ('pdf.protect', 'pdf.unlock_known') and (not isinstance(secret, str) or not 1 <= len(secret) <= 256):
        raise ProcessorError('password_required')
    metadata = [inspect_file(path, secret if feature_id == 'pdf.unlock_known' else None,
                             office_preflight=False) for path in paths]
    parameters = normalize_parameters(feature_id, parameters, metadata)
    pages = sum(m['page_count'] or 0 for m in metadata)
    if pages > MAX_PAGES:
        raise ProcessorError('page_limit')
    if feature_id == 'pdf.images_to_pdf':
        if any(m['kind'] != 'image' for m in metadata):
            raise ProcessorError('unsupported_type')
    elif feature_id in EDITOR_SCHEMAS:
        if metadata[0]['kind']!='pdf' or any(m['kind']!='image' for m in metadata[1:]):raise ProcessorError('unsupported_type')
    elif feature_id.startswith('ocr.'):
        if metadata[0]['kind'] not in ('pdf','image'):raise ProcessorError('unsupported_type')
    elif feature_id in ('convert.pdf_to_docx','convert.pdf_to_xlsx'):
        if metadata[0]['kind']!='pdf':raise ProcessorError('unsupported_type')
    elif not feature_id.startswith('convert.') and any(m['kind'] != 'pdf' for m in metadata):
        raise ProcessorError('unsupported_type')
    if any(m.get('password_required') for m in metadata):
        raise ProcessorError('password_required')
    out = Path(output_dir)
    if out.is_symlink():
        raise ProcessorError('unsafe_path')
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(out.iterdir()):
        raise ProcessorError('output_directory_not_empty')
    no_op = False
    details = {'engine_versions': {n: importlib.metadata.version(n) for n in ('pypdf', 'Pillow', 'pypdfium2', 'reportlab')}}
    details['engine'] = capabilities()[feature_id]['engine']
    if feature_id in ('convert.word_to_pdf','convert.pptx_to_pdf') and office_runtime()['available']:
        details['engine_versions']['libreoffice'] = office_runtime()['version']
    try:
        if feature_id in ADVANCED_SCHEMAS:
            from .advanced import execute as advanced_execute
            artifacts,extra=advanced_execute(feature_id,paths,parameters,out,metadata)
            details.update(extra)
        elif feature_id in EDITOR_SCHEMAS:
            from .editor import execute as editor_execute
            artifacts,extra=editor_execute(feature_id,paths,parameters,out,metadata)
            details.update(extra)
        elif feature_id == 'pdf.images_to_pdf':
            artifacts, extra = _image_pdf(paths, parameters, out)
            details.update(extra)
            details['engine_versions']['opencv-python-headless'] = importlib.metadata.version('opencv-python-headless')
        elif feature_id.startswith('convert.'):
            artifacts = _office_pdf(paths[0], feature_id, out, metadata[0])
        elif feature_id == 'pdf.to_images':
            artifacts = _pdf_images(paths[0], parameters, out, pages)
        else:
            readers = [_pdf_reader(path, secret if feature_id == 'pdf.unlock_known' else None) for path in paths]
            if feature_id == 'pdf.split':
                ranges = parameters.get('ranges') or [str(i + 1) for i in range(pages)]
                if sum(len(parse_pages(r, pages)) for r in ranges) > MAX_PAGES:
                    raise ProcessorError('page_limit')
                artifacts = []
                for i, value in enumerate(ranges):
                    writer = PdfWriter()
                    for index in parse_pages(value, pages):
                        writer.add_page(readers[0].pages[index])
                    artifacts.append(_write_pdf(writer, out / f'part-{i + 1:03d}.pdf'))
            else:
                writer = PdfWriter()
                if feature_id == 'pdf.merge':
                    for reader in readers:
                        for page in reader.pages:
                            writer.add_page(page)
                else:
                    reader = readers[0]
                    indexes = list(range(pages))
                    if feature_id == 'pdf.extract_pages':
                        indexes = parse_pages(parameters['pages'], pages)
                    elif feature_id == 'pdf.delete_pages':
                        removed = set(parse_pages(parameters['pages'], pages))
                        indexes = [i for i in indexes if i not in removed]
                    elif feature_id == 'pdf.reorder':
                        indexes = [i - 1 for i in parameters['order']]
                    for index in indexes:
                        writer.add_page(reader.pages[index])
                    if feature_id == 'pdf.rotate':
                        for index in parse_pages(parameters['pages'], pages):
                            writer.pages[index].rotate(parameters['angle'])
                    elif feature_id == 'pdf.compress':
                        for page in writer.pages:
                            page.compress_content_streams(level=9)
                        writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
                    elif feature_id == 'pdf.protect':
                        writer.encrypt(secret, owner_password=secrets.token_urlsafe(32), algorithm='AES-256')
                    elif feature_id == 'pdf.unlock_known' and not reader.is_encrypted:
                        raise ProcessorError('not_encrypted')
                artifacts = [_write_pdf(writer, out / 'result.pdf', secret if feature_id == 'pdf.protect' else None)]
                if feature_id == 'pdf.compress':
                    original = paths[0].stat().st_size
                    candidate = artifacts[0]['size_bytes']
                    # A <1% reduction is not useful enough to charge for.
                    no_op = candidate >= original * 0.99
                    if no_op:
                        shutil.copyfile(paths[0], out / 'result.pdf')
                        artifacts = [_artifact(out / 'result.pdf')]
                    details.update({'input_bytes': original, 'output_bytes': artifacts[0]['size_bytes'],
                        'saved_bytes': original - artifacts[0]['size_bytes'], 'lossless': True})
        output_pages = sum(a['page_count'] or 0 for a in artifacts)
        if output_pages > MAX_PAGES or sum(a['size_bytes'] for a in artifacts) > MAX_OUTPUT_BYTES:
            raise ProcessorError('output_size_limit')
        return {'artifacts': artifacts, 'actual_page_units': max(pages, output_pages),
                'no_op': no_op, 'metadata': details}
    except ProcessorError:
        for child in out.iterdir():
            if child.is_file():
                child.unlink()
        raise
    except Exception:
        for child in out.iterdir():
            if child.is_file():
                child.unlink()
        raise ProcessorError('processing_failed') from None
