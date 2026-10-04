"""AI requests: what customers asked the AI for and what it made.

Support and Operations review them for quality and misuse. The list shows
only who, when, which service and the first words of the request; opening one
shows the whole request and the document, and is written to the audit log
first, as opening any customer document is.
"""
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404

from apps.studio.models import GenerationRecord
from apps.studio.review import REVIEW_DAYS, output_path, page_image, request_data
from .auth import allowed, audit, require_staff
from .views import context, finish_render

ROLES = ('Support', 'Operations')
SERVICES = {'ai.pdf_topic': 'gen_document', 'ai.pptx': 'gen_slides'}
# Prompts are encrypted, so a search for words in them reads the newest records
# in turn; this bounds how many one search may open.
TEXT_SEARCH_LIMIT = 3000


def _excerpt(data, length=180):
    words = (data.get('revision') or {}).get('request') or data.get('prompt') or data.get('title') or ''
    words = ' '.join(words.split())
    return words if len(words) <= length else words[:length].rstrip() + '…'


def _rows(records, t):
    rows = []
    for record in records:
        data = request_data(record)
        rows.append({'record': record, 'excerpt': _excerpt(data), 'revision': bool(data.get('revision')),
                     'service': t[SERVICES.get(record.feature_id, 'gen_document')],
                     'format': (data.get('output_format') or '').upper(), 'status': record.job.status})
    return rows


@require_staff(*ROLES)
def generations(request):
    data = context(request, 'generations')
    t = data['t']
    records = GenerationRecord.objects.select_related('account', 'job').order_by('-created_at')
    who = request.GET.get('q', '').strip()[:150]
    if who:
        match = Q(account__display_name__icontains=who) | Q(account__username__icontains=who) | Q(account__id__icontains=who)
        if who.isdigit():
            match |= Q(account__telegram_user_id=int(who))
        records = records.filter(match)
    service = request.GET.get('service', '')
    if service in SERVICES:
        records = records.filter(feature_id=service)
    words = ' '.join(request.GET.get('text', '').split())[:120].casefold()
    if words:
        # Read in turn, newest first, within the bound above.
        matched = [r.pk for r in records[:TEXT_SEARCH_LIMIT] if words in _haystack(request_data(r))]
        records = records.filter(pk__in=matched)
    pagination = Paginator(records, 30).get_page(request.GET.get('p'))
    params = request.GET.copy()
    params.pop('p', None)
    data.update(pagination=pagination, rows=_rows(pagination, t), services=[(key, t[label]) for key, label in SERVICES.items()],
                selected_service=service, who=who, words=request.GET.get('text', ''), page_query=params.urlencode(),
                intro=t['gen_intro'].format(days=REVIEW_DAYS))
    return finish_render(request, 'ops/generations.html', data)


def _haystack(data):
    parts = [data.get('prompt', ''), data.get('title', ''), (data.get('revision') or {}).get('request', '')]
    parts += [s.get('heading', '') + ' ' + s.get('body', '') for s in data.get('sections', [])]
    return ' '.join(parts).casefold()


@require_staff(*ROLES)
def generation_detail(request, pk):
    record = get_object_or_404(GenerationRecord.objects.select_related('account', 'job'), pk=pk)
    data = context(request, 'generations')
    t = data['t']
    audit(request.ops_user, 'generation.view', record.pk,
          after={'account': str(record.account_id), 'job': str(record.job_id)})
    contents = request_data(record)
    try:
        page = max(1, int(request.GET.get('page', 1)))
    except ValueError:
        page = 1
    pages = max(record.output_pages, 1)
    page = min(page, pages)
    kept = output_path(record) is not None
    job = record.job
    if kept:
        outcome = ''
    elif job.status in ('queued', 'running', 'finalizing'):
        outcome = t['gen_running']
    elif job.status == 'succeeded':
        outcome = t['gen_no_output']
    else:
        outcome = t['gen_failed'].format(code=job.error_code or job.status)
    data.update(record=record, request_data=contents, job=job, kept=kept, outcome=outcome,
                is_pdf=record.output_mime == 'application/pdf', page=page, pages=pages,
                page_label=t['gen_page'].format(n=page, count=pages),
                service=t[SERVICES.get(record.feature_id, 'gen_document')],
                kept_until=t['gen_kept_until'].format(date=record.expires_at.strftime('%d %b %Y')),
                can_inspect_jobs=allowed(request.ops_user, ['Operations', 'Support']))
    return finish_render(request, 'ops/generation.html', data)


@require_staff(*ROLES)
def generation_file(request, pk):
    record = get_object_or_404(GenerationRecord, pk=pk)
    path = output_path(record)
    if not path:
        return HttpResponseBadRequest('This document is no longer kept.')
    audit(request.ops_user, 'generation.file', record.pk,
          after={'account': str(record.account_id), 'name': record.output_name, 'bytes': record.output_size})
    response = FileResponse(path.open('rb'), as_attachment=True, filename=record.output_name or path.name,
                            content_type=record.output_mime or 'application/octet-stream')
    response['Cache-Control'] = 'private, no-store'
    response['Content-Security-Policy'] = "sandbox; default-src 'none'"
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@require_staff(*ROLES)
def generation_page(request, pk, page):
    """One page of the kept PDF as an image, for reading it on the review page."""
    record = get_object_or_404(GenerationRecord, pk=pk)
    try:
        image = page_image(record, page)
    except Exception:
        image = None
    if not image:
        raise Http404()
    response = FileResponse(image.open('rb'), content_type='image/png')
    response['Cache-Control'] = 'private, no-store'
    response['Content-Security-Policy'] = "default-src 'none'"
    response['X-Content-Type-Options'] = 'nosniff'
    return response
