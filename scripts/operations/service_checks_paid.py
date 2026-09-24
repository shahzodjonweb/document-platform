"""Runtime checks for paid-only PDF editors, using synthetic temporary files.

These checks deliberately call the real bounded processor child process rather
than change account entitlements or create payment records. They validate engine
availability and serialized output, not the paid HTTP/quote/billing pipeline.
No external AI service is called, and every input/output is removed afterward.
"""
import re
import tempfile
import uuid
from pathlib import Path

from PIL import Image
from pypdf import PdfReader
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from processors.sandbox import execute_sandbox


def _paid_error(exc):
    code = getattr(exc, 'code', '')
    return {'status': 'failed', 'scope': 'processor_runtime_only', 'error': type(exc).__name__,
            'code': code if isinstance(code, str) and re.fullmatch(r'[a-z0-9_]{1,80}', code) else 'probe_failed'}


def _paid_pdf(path, *, image=None, redaction=False):
    canvas = Canvas(str(path), pagesize=(400, 600), pageCompression=0)
    canvas.setFont('Helvetica', 18)
    if redaction:
        canvas.drawString(40, 550, 'PUBLIC TOP')
        canvas.drawString(40, 470, 'CANARYSECRET123')
    else:
        canvas.drawString(40, 550, 'Account OLD VALUE')
    if image:
        canvas.drawImage(ImageReader(image), 40, 400, 100, 80)
    canvas.showPage()
    canvas.save()
    return path


def _paid_artifact(result, directory, *, suffix='.pdf'):
    artifacts = result.get('artifacts', [])
    if len(artifacts) != 1:
        raise AssertionError('Expected one processor artifact')
    path = Path(artifacts[0]['path']).resolve()
    if not path.is_relative_to(directory.resolve()) or path.suffix != suffix:
        raise AssertionError('Unexpected processor artifact path')
    if not path.is_file() or not 0 < path.stat().st_size <= 5 * 1024 * 1024:
        raise AssertionError('Unexpected processor artifact size')
    return path


def _paid_execute(feature, source, parameters, directory, *, image=None):
    return execute_sandbox(feature, [source] + ([image] if image else []), parameters,
                           directory, timeout=45)


def _paid_existing_text(root):
    source = _paid_pdf(root / 'source.pdf')
    directory = root / 'output'
    result = _paid_execute('editor.existing_text', source, {'commands': [
        {'type': 'replace_text', 'page': 1, 'find': 'OLD', 'replacement': 'NEW'},
    ]}, directory)
    page = PdfReader(_paid_artifact(result, directory)).pages[0]
    text = page.extract_text()
    if 'Account NEW VALUE' not in text or 'OLD' in text or b'OLD' in page.get_contents().get_data():
        raise AssertionError('Text replacement was not serialized')
    if result['metadata'].get('text_replacements') != 1:
        raise AssertionError('Expected one text replacement')
    return {'status': 'passed', 'scope': 'processor_runtime_only', 'replacements': 1,
            'original_text_removed': True, 'output_pages': 1}


def _paid_insert_images(root):
    source = _paid_pdf(root / 'source.pdf')
    inserted = root / 'inserted.png'
    Image.new('RGB', (100, 80), (250, 51, 49)).save(inserted)
    directory = root / 'output'
    result = _paid_execute('editor.insert_images', source, {'commands': [
        {'type': 'insert_image', 'page': 1, 'x': 40, 'y': 100, 'width': 100, 'height': 80, 'input_index': 1},
    ]}, directory, image=inserted)
    page = PdfReader(_paid_artifact(result, directory)).pages[0]
    if len(page.images) != 1 or 'Account OLD VALUE' not in page.extract_text():
        raise AssertionError('Image insertion changed unrelated text or did not add an image')
    with page.images[0].image.convert('RGB') as image:
        if image.getpixel((50, 40)) != (250, 51, 49):
            raise AssertionError('Inserted image pixels differ')
    return {'status': 'passed', 'scope': 'processor_runtime_only', 'images_inserted': 1,
            'image_pixels_verified': True, 'original_text_preserved': True, 'output_pages': 1}


def _paid_replace_images(root):
    red, blue = root / 'red.png', root / 'blue.png'
    Image.new('RGB', (100, 80), 'red').save(red)
    Image.new('RGB', (100, 80), 'blue').save(blue)
    source = _paid_pdf(root / 'source.pdf', image=red)
    directory = root / 'replaced'
    result = _paid_execute('editor.replace_images', source, {'commands': [
        {'type': 'replace_image', 'page': 1, 'image_index': 0, 'input_index': 1},
    ]}, directory, image=blue)
    page = PdfReader(_paid_artifact(result, directory)).pages[0]
    if len(page.images) != 1:
        raise AssertionError('Image replacement changed the image count')
    with page.images[0].image.convert('RGB') as image:
        red_pixel, _, blue_pixel = image.getpixel((50, 40))
        if blue_pixel <= 240 or red_pixel >= 15:
            raise AssertionError('Replacement pixels were not serialized')
    removed_directory = root / 'removed'
    removed = _paid_execute('editor.replace_images', source, {'commands': [
        {'type': 'remove_image', 'page': 1, 'image_index': 0},
    ]}, removed_directory)
    removed_page = PdfReader(_paid_artifact(removed, removed_directory)).pages[0]
    if len(removed_page.images) or 'Account OLD VALUE' not in removed_page.extract_text():
        raise AssertionError('Image removal failed or changed unrelated text')
    return {'status': 'passed', 'scope': 'processor_runtime_only', 'images_replaced': 1,
            'image_pixels_verified': True, 'image_removal_verified': True, 'output_pages': 1}


def _paid_redact(root):
    source = _paid_pdf(root / 'source.pdf', redaction=True)
    directory = root / 'output'
    result = _paid_execute('editor.redact', source, {'commands': [
        {'type': 'redact', 'page': 1, 'x': 25, 'y': 105, 'width': 300, 'height': 60},
    ], 'accept_rasterization': True}, directory)
    path = _paid_artifact(result, directory)
    reader = PdfReader(path)
    if len(reader.pages) != 1:
        raise AssertionError('Unexpected redaction page count')
    page = reader.pages[0]
    if page.extract_text().strip() or reader.get_fields() or page.get('/Annots'):
        raise AssertionError('Recoverable text, forms or annotations remain')
    if b'CANARYSECRET123' in path.read_bytes() or len(page.images) != 1:
        raise AssertionError('Redaction retained original text or did not serialize the raster')
    with page.images[0].image.convert('RGB') as image:
        if image.getpixel((150, 260)) != (0, 0, 0):
            raise AssertionError('Redaction pixels are not opaque')
    recovery_directory = root / 'ocr-recovery'
    recovery = execute_sandbox('ocr.extract_text', [path], {'language': 'eng'}, recovery_directory, timeout=45)
    recovered = _paid_artifact(recovery, recovery_directory, suffix='.txt').read_text()
    if 'PUBLIC' not in recovered or 'SECRET' in recovered or 'CANARY' in recovered:
        raise AssertionError('OCR recovery did not preserve public text and remove the canary')
    if result['metadata'].get('redaction_mode') != 'rasterized_destructive':
        raise AssertionError('Unexpected redaction mode')
    return {'status': 'passed', 'scope': 'processor_runtime_only', 'output_pages': 1,
            'original_text_removed': True, 'opaque_pixels_verified': True,
            'ocr_recovery_verified': True, 'rasterization_acknowledged': True}


def check_paid_processors(audit_id):
    """Run all four checks independently; return safe summaries without contents."""
    audit_id = uuid.UUID(str(audit_id))
    results = {}
    with tempfile.TemporaryDirectory(prefix='pdfmaster-paid-check-' + audit_id.hex[:12] + '-') as temporary:
        for feature, check in (
            ('editor.existing_text', _paid_existing_text),
            ('editor.insert_images', _paid_insert_images),
            ('editor.replace_images', _paid_replace_images),
            ('editor.redact', _paid_redact),
        ):
            try:
                directory = Path(temporary) / feature
                directory.mkdir(mode=0o700)
                results[feature] = check(directory)
            except Exception as exc:
                results[feature] = _paid_error(exc)
    return results
