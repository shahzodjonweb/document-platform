"""Synthetic HTTP → queue → worker → download checks; never impersonate a customer."""
import io
import json
import mimetypes
import re
import tempfile
import time
import uuid
import zipfile
from importlib import import_module
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.cookies import SimpleCookie

from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas
from apps.core.models import Account, FileAsset, Job


API_URL = 'http://127.0.0.1:8000/api/v1/'



def _as_channel_member(account):
    """Free accounts are asked to join the owner's Telegram channels before a
    task runs. A synthetic account cannot join, so it is recorded as a member
    for the hour of the audit; the rule stays on for everyone else."""
    from apps.core.channel_gate import _config as channel_config
    from apps.core.models import ChannelMembership
    now = timezone.now()
    for channel in channel_config()['channels']:
        ChannelMembership.objects.update_or_create(account=account, chat=channel['chat'], defaults={
            'is_member': True, 'checked_at': now, 'expires_at': now + timedelta(hours=1)})

class ProbeFailure(Exception):
    def __init__(self, code):
        self.code = code if re.fullmatch(r'[a-zA-Z0-9_.-]{1,100}', str(code)) else 'probe_failed'


def require(condition, code):
    if not condition:
        raise ProbeFailure(code)


class Customer:
    """Provision a test-only session server-side, then use the actual HTTP API.

    This tests authorization/CSRF and all document endpoints, not external login.
    Session cookies stay in memory and are deleted when the probe finishes.
    """
    def __init__(self, audit_id, feature):
        self.account = Account.objects.create(is_test=True, display_name=f'Service audit {audit_id} {feature}')
        _as_channel_member(self.account)
        self.session = import_module(settings.SESSION_ENGINE).SessionStore()
        self.session['customer_account_id'] = str(self.account.pk)
        self.session['customer_auth_version'] = self.account.auth_version
        self.session.set_expiry(900)
        self.session.save()
        self.cookies = {settings.SESSION_COOKIE_NAME: self.session.session_key}
        self.csrf = None
        data = self.json('GET', 'auth/session')
        require(data.get('authenticated') and data['user']['is_test'], 'test_session')
        self.csrf = data['csrf_token']

    def request(self, method, path, data=None, content_type='application/json', headers=None, csrf=True):
        headers = {'Host': 'pdfmaster-admin.orderdesk.live', 'X-Forwarded-Proto': 'https',
                   'Origin': 'https://pdfmaster-admin.orderdesk.live',
                   'Referer': 'https://pdfmaster-admin.orderdesk.live/',
                   'Cookie': '; '.join(f'{k}={v}' for k, v in self.cookies.items()),
                   'Content-Type': content_type, **(headers or {})}
        if csrf and self.csrf:
            headers['X-CSRFToken'] = self.csrf
        request = Request(API_URL + path.removeprefix('/api/v1/'),
                          data=data, method=method, headers=headers)
        try:
            response = urlopen(request, timeout=100)
        except HTTPError as exc:
            response = exc
        with response:
            body = response.read(12 * 1024 * 1024 + 1)
            require(len(body) <= 12 * 1024 * 1024, 'response_limit')
            for value in response.headers.get_all('Set-Cookie', []):
                cookie = SimpleCookie(); cookie.load(value)
                self.cookies.update({key: morsel.value for key, morsel in cookie.items()})
            return response.status, body, response.headers

    def json(self, method, path, data=None, expected=(200, 201), headers=None):
        status, body, _ = self.request(method, path, json.dumps(data).encode() if data is not None else None, headers=headers)
        try:
            result = json.loads(body)
        except ValueError:
            raise ProbeFailure('non_json_response') from None
        if status not in expected:
            raise ProbeFailure(result.get('error', {}).get('code', 'http_' + str(status)))
        return result

    def upload(self, path, password=None):
        boundary = 'Audit' + uuid.uuid4().hex
        data = b''
        if password:
            data += f'--{boundary}\r\nContent-Disposition: form-data; name="password"\r\n\r\n{password}\r\n'.encode()
        data += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                 f'Content-Type: {mimetypes.guess_type(path.name)[0] or "application/octet-stream"}\r\n\r\n').encode()
        data += path.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
        status, body, _ = self.request('POST', 'files/uploads', data, 'multipart/form-data; boundary=' + boundary)
        result = json.loads(body)
        require(status == 201, result.get('error', {}).get('code', 'upload_failed'))
        return result

    def retire(self):
        self.session.delete()
        if not Job.objects.filter(account=self.account, status__in=('queued', 'running', 'finalizing')).exists():
            FileAsset.objects.filter(account=self.account).exclude(state='deleted').update(expires_at=timezone.now())


def fixtures(folder):
    def pdf(name, labels, form=False):
        path = folder / name
        canvas = Canvas(str(path), pagesize=(400, 600), pageCompression=0)
        for label in labels:
            canvas.setFont('Helvetica', 18); canvas.drawString(40, 550, label)
            if form:
                canvas.acroForm.textfield(name='customer', x=40, y=430, width=260, height=45, fontSize=12)
            canvas.showPage()
        canvas.save()
        return path
    paths = {'pdf': pdf('pages.pdf', ['alpha', 'beta', 'gamma']), 'other': pdf('other.pdf', ['delta']),
             'form': pdf('form.pdf', ['Form'], form=True)}
    paths['compress'] = pdf('compress.pdf', ['Repeated readable text ' * 60])
    for color in ('red', 'blue'):
        paths[color] = folder / (color + '.png'); Image.new('RGB', (100, 80), color).save(paths[color])
    paths['scan'] = folder / 'document-photo.png'
    scan = Image.new('RGB', (700, 900), (46, 64, 54))
    draw = ImageDraw.Draw(scan)
    draw.polygon([(130, 80), (570, 125), (590, 810), (70, 750)], fill=(244, 244, 242))
    font = ImageFont.truetype('processors/assets/fonts/NotoSans-Regular.ttf', 23)
    for number, top in enumerate(range(180, 600, 48), 1):
        draw.text((155, top), f'{number}. Document scan 123', font=font, fill=(35, 35, 35))
    draw.text((150, 675), 'Blue note: keep this ink', font=font, fill=(20, 55, 145))
    scan.save(paths['scan'])
    for language, text in [('eng', 'HELLO DOCUMENT 2026'), ('rus', 'ПРИВЕТ ДОКУМЕНТ 2026'), ('uzb', 'SALOM HUJJAT 2026')]:
        paths[language] = folder / (language + '.png')
        scan = Image.new('RGB', (1500, 320), 'white')
        ImageDraw.Draw(scan).text((50, 100), text, font=ImageFont.truetype('processors/assets/fonts/NotoSans-Regular.ttf', 58), fill='black')
        scan.save(paths[language])
    paths['protected'] = folder / 'protected.pdf'
    writer = PdfWriter(clone_from=paths['other']); writer.encrypt('synthetic-audit-password'); writer.write(paths['protected'])
    paths['table'] = folder / 'table.pdf'
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors
    canvas = Canvas(str(paths['table']), pagesize=(400, 600))
    table = Table([['Item', 'Value'], ['Alpha', '=2+2'], ['Beta', '20']], colWidths=[150, 150], rowHeights=30)
    table.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 1, colors.black)]))
    table.wrapOn(canvas, 300, 200); table.drawOn(canvas, 40, 350); canvas.save()
    paths['docx'] = Path('processors/fixtures/office-multilingual.docx')
    paths['pptx'] = Path('processors/fixtures/office-multilingual.pptx')
    return paths


def cases():
    add = {'type': 'add_text', 'page': 1, 'x': 40, 'y': 100, 'text': 'Salom Привет', 'font_size': 18}
    highlight = {'type': 'highlight', 'page': 1, 'x': 38, 'y': 35, 'width': 180, 'height': 24}
    note = {'type': 'note', 'page': 1, 'x': 300, 'y': 60, 'text': 'Примечание'}
    return [
        ('pdf.merge', ['pdf', 'other'], {}), ('pdf.compress', ['compress'], {}),
        ('pdf.split', ['pdf'], {'ranges': ['1-2', '3']}),
        ('pdf.extract_pages', ['pdf'], {'pages': '3,1'}), ('pdf.delete_pages', ['pdf'], {'pages': '2'}),
        ('pdf.reorder', ['pdf'], {'order': [3, 2, 1]}), ('pdf.rotate', ['pdf'], {'pages': '1,3', 'angle': 90}),
        ('pdf.images_to_pdf', ['red', 'blue'], {}), ('pdf.to_images', ['pdf'], {'format': 'png', 'pages': '3,1', 'dpi': 72}),
        ('pdf.images_to_pdf', ['scan'], {'auto_crop': True, 'enhance_text': True}),
        ('pdf.images_to_pdf', ['scan'], {'auto_crop': False, 'enhance_text': False}),
        ('pdf.protect', ['other'], {}), ('pdf.unlock_known', ['protected'], {}),
        ('convert.word_to_pdf', ['docx'], {}), ('convert.pptx_to_pdf', ['pptx'], {}),
        ('ocr.extract_text', ['eng'], {'language': 'eng'}), ('ocr.searchable_pdf', ['eng'], {'language': 'eng'}),
        ('convert.pdf_to_docx', ['other'], {'mode': 'text'}), ('convert.pdf_to_xlsx', ['table'], {}),
        ('editor.visual', ['other'], {'commands': [add, highlight, note]}),
        ('editor.add_text', ['other'], {'commands': [add]}), ('editor.highlight', ['other'], {'commands': [highlight]}),
        ('editor.annotate', ['other'], {'commands': [note]}),
        ('editor.fill_forms', ['form'], {'commands': [{'type': 'fill_form', 'field': 'customer', 'value': 'Павел Salom'}]}),
        ('editor.signature_image', ['other', 'red'], {'commands': [{'type': 'signature', 'page': 1, 'x': 40, 'y': 100, 'width': 140, 'height': 45, 'input_index': 1}]}),
        ('ocr.extract_text', ['rus'], {'language': 'rus'}), ('ocr.extract_text', ['uzb'], {'language': 'uzb'}),
    ]


def validate_output(feature, outputs, parameters):
    if feature == 'pdf.to_images':
        with zipfile.ZipFile(io.BytesIO(outputs[0])) as archive:
            require(archive.namelist() == ['page-0003.png', 'page-0001.png'], 'image_archive_order')
            for name in archive.namelist():
                image = Image.open(io.BytesIO(archive.read(name))); image.verify()
        return
    if feature == 'ocr.extract_text':
        expected = {'eng': 'HELLO', 'rus': 'ПРИВЕТ', 'uzb': 'HUJJAT'}[parameters['language']]
        require(expected in outputs[0].decode(), 'ocr_text'); return
    if feature == 'convert.pdf_to_docx':
        from docx import Document
        require('delta' in '\n'.join(p.text for p in Document(io.BytesIO(outputs[0])).paragraphs), 'editable_word_text'); return
    if feature == 'convert.pdf_to_xlsx':
        from openpyxl import load_workbook
        book = load_workbook(io.BytesIO(outputs[0]), data_only=False); sheet = book.worksheets[0]
        require(sheet['A2'].value == 'Alpha' and sheet['B2'].value == '=2+2' and sheet['B2'].data_type == 's', 'table_cells_safe'); return
    readers = [PdfReader(io.BytesIO(output)) for output in outputs]
    if feature == 'pdf.protect':
        require(readers[0].is_encrypted and readers[0].decrypt('synthetic-audit-password'), 'pdf_encryption')
    pages = readers[0].pages
    texts = [page.extract_text().strip() for page in pages]
    expected = {'pdf.merge': ['alpha', 'beta', 'gamma', 'delta'], 'pdf.extract_pages': ['gamma', 'alpha'],
                'pdf.delete_pages': ['alpha', 'gamma'], 'pdf.reorder': ['gamma', 'beta', 'alpha'],
                'pdf.unlock_known': ['delta'], 'pdf.protect': ['delta']}
    if feature in expected: require(texts == expected[feature], 'page_text_order')
    if feature == 'pdf.unlock_known': require(not readers[0].is_encrypted, 'unlocked')
    if feature == 'pdf.split': require([len(r.pages) for r in readers] == [2, 1] and readers[1].pages[0].extract_text().strip() == 'gamma', 'split_pages')
    if feature == 'pdf.rotate': require([page.rotation for page in pages] == [90, 0, 90], 'page_rotation')
    if feature == 'pdf.compress': require('Repeated readable text' in texts[0], 'compressed_text')
    if feature == 'pdf.images_to_pdf':
        require(len(pages) == (1 if 'auto_crop' in parameters else 2) and all(len(p.images) > 0 for p in pages), 'image_pages')
        if 'auto_crop' in parameters:
            picture = pages[0].images[0].image.convert('RGB')
            if parameters['auto_crop']:
                require(picture.width < 650 and picture.height < 850, 'document_crop')
                require(sum(b > r + 35 and b > g + 25 for r, g, b in picture.get_flattened_data()) > 100, 'document_colored_ink')
            else:
                require(picture.size == (700, 900) and picture.getpixel((20, 20)) == (46, 64, 54), 'document_opt_out')
    if feature in ('convert.word_to_pdf', 'convert.pptx_to_pdf'):
        require(len(pages) == 3 and all(phrase in text for phrase, text in zip(
            ['Document pages remain readable', 'Hujjat sahifalari aniq ko‘rinadi', 'Страницы документа остаются читаемыми'], texts)), 'office_multilingual_pages')
    if feature == 'ocr.searchable_pdf': require('HELLO' in texts[0] and len(pages[0].images), 'searchable_text_layer')
    if feature in ('editor.visual', 'editor.add_text'): require('Salom Привет' in texts[0], 'unicode_overlay')
    if feature in ('editor.visual', 'editor.highlight', 'editor.annotate'):
        types = {a.get_object()['/Subtype'] for a in pages[0].get('/Annots', [])}
        expected = {'editor.visual': {'/Highlight', '/Text'}, 'editor.highlight': {'/Highlight'}, 'editor.annotate': {'/Text'}}[feature]
        require(expected.issubset(types), 'serialized_annotations')
    if feature == 'editor.fill_forms': require(readers[0].get_fields()['customer']['/V'] == 'Павел Salom', 'unicode_form')
    if feature == 'editor.signature_image': require(len(pages[0].images) == 1, 'signature_image')


def check_documents(audit_id, emit):
    results = []
    deadline = time.monotonic() + 410
    with tempfile.TemporaryDirectory(prefix='pdfmaster-service-audit-') as directory:
        paths = fixtures(Path(directory))
        for feature, inputs, parameters in cases():
            customer = None
            start = time.monotonic()
            row = {'feature': feature, 'variant': parameters.get('language', 'default'), 'scope': 'http_queue_worker_download'}
            if feature == 'pdf.images_to_pdf' and 'auto_crop' in parameters:
                row['variant'] = 'scanning_on' if parameters['auto_crop'] else 'scanning_off'
            try:
                require(time.monotonic() < deadline, 'audit_time_budget')
                customer = Customer(audit_id, feature)
                assets = [customer.upload(paths[key], 'synthetic-audit-password' if key == 'protected' else None) for key in inputs]
                payload = {'feature_id': feature, 'input_ids': [a['id'] for a in assets], 'parameters': parameters}
                if feature == 'pdf.protect':
                    payload['secret_id'] = customer.json('POST', 'secrets', {'password': 'synthetic-audit-password'})['id']
                quote = customer.json('POST', 'quotes', payload)
                key = 'service-audit-' + uuid.uuid4().hex
                job = customer.json('POST', 'jobs', {'quote_id': quote['id']}, headers={'Idempotency-Key': key})
                stop = min(deadline, time.monotonic() + 60)
                while job['status'] in ('queued', 'running', 'finalizing') and time.monotonic() < stop:
                    time.sleep(0.5); job = customer.json('GET', 'jobs/' + job['id'])
                require(job['status'] in ('succeeded', 'no_op'), (job.get('error') or {}).get('code', 'job_' + job['status']))
                require(Job.objects.get(pk=job['id'], account=customer.account).attempt_count >= 1, 'worker_attempt')
                outputs = []
                for artifact in job['artifacts']:
                    status, body, headers = customer.request('GET', artifact['download_url'])
                    require(status == 200 and headers.get('Content-Disposition', '').startswith('attachment'), 'download')
                    outputs.append(body)
                require(bool(outputs), 'missing_output')
                validate_output(feature, outputs, parameters)
                if feature == 'pdf.compress': require(len(outputs[0]) < paths['compress'].stat().st_size, 'compression_size')
                if feature == 'pdf.merge':
                    preview = job['artifacts'][0]['preview_url']
                    status, body, _ = customer.request('GET', preview)
                    require(status == 200 and body.startswith(b'\x89PNG'), 'preview_png')
                    retry = customer.json('POST', 'jobs', {'quote_id': quote['id']}, headers={'Idempotency-Key': key})
                    require(retry['id'] == job['id'], 'idempotency')
                    status, _, _ = customer.request('POST', 'quotes', json.dumps(payload).encode(), csrf=False)
                    require(status == 403, 'csrf_boundary')
                    other = Customer(audit_id, 'ownership')
                    try:
                        for path in ('jobs/' + job['id'], job['artifacts'][0]['download_url']):
                            status, _, _ = other.request('GET', path); require(status == 404, 'owner_boundary')
                        for fid in ('editor.existing_text', 'editor.insert_images', 'editor.replace_images', 'editor.redact'):
                            response = customer.json('POST', 'quotes', {**payload, 'feature_id': fid}, expected=(403,))
                            require(response.get('error', {}).get('code') == 'feature_not_in_plan', 'paid_access_boundary')
                    finally: other.retire()
                    row['access_idempotency_preview'] = 'passed'
                require(job['settled_meters'] == job['meters'], 'usage_settlement')
                row.update(status='passed', outputs=len(outputs))
            except Exception as exc:
                code = getattr(exc, 'code', 'probe_failed')
                row.update(status='failed', error=type(exc).__name__, code=code if re.fullmatch(r'[a-zA-Z0-9_.-]{1,100}', str(code)) else 'probe_failed')
            finally:
                if customer: customer.retire()
            row['seconds'] = round(time.monotonic() - start, 2)
            results.append(row); emit(row)
    return results
