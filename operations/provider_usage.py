"""Read-only reporting of provider metadata; customer content stays private."""
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import HttpResponseBadRequest
from django.views.decorators.http import require_GET

from apps.studio.models import ProviderAttempt
from apps.studio.provider_usage import TOKEN_FIELDS
from .auth import require_staff
from .metrics import Filters
from .views import context, finish_render


LABELS = {
    'en': {
        'basis': 'Actual provider attempts, including failed and rejected responses. Token totals count each provider response once. No document content is stored in this report.',
        'retention': 'Usage metadata is retained for 90 days. Earlier calls are not backfilled. These are token counts, not an invoice or a currency estimate.',
        'subsets': 'Cached and cache-write tokens are parts of input tokens; reasoning tokens are part of output tokens. Do not add them to the totals.',
        'attempts': 'Provider attempts', 'responses': 'Unique responses / attempts without an ID',
        'duplicates': 'Replayed responses', 'failed': 'Failed or rejected attempts',
        'unknown_environment': 'Attempts without environment metadata (excluded from the selected environment)',
        'input_tokens': 'Known input tokens', 'output_tokens': 'Known output tokens',
        'total_tokens': 'Known total tokens', 'cached_input_tokens': 'Known cached input tokens',
        'cache_write_input_tokens': 'Known cache-write input tokens', 'reasoning_output_tokens': 'Known reasoning output tokens',
        'unknown': 'Unknown', 'unreported': 'Responses with this count unreported',
        'models': 'Usage by model and stage', 'recent': 'Recent provider attempts',
        'requested': 'Requested model', 'resolved': 'Returned model', 'stage': 'Stage',
        'latency': 'Latency (ms)', 'started': 'Started', 'received': 'Response received',
        'succeeded': 'Succeeded', 'rejected': 'Response rejected', 'failed_status': 'Request failed',
        'generate': 'Generate', 'outline': 'Outline', 'revision': 'Revise', 'photo_pick': 'Photo choice', 'expand': 'Expand', 'repair': 'Repair',
        'replayed': 'Replay · excluded from token totals', 'span': 'Sections',
        'empty': 'No provider attempts in this period.',
        'reasons': 'Rejected responses by reason', 'reason': 'Reason', 'count': 'Responses',
        'rejection_': 'Reason not recorded',
        'rejection_cut_off': 'Cut off at its token limit', 'rejection_not_completed': 'Not completed by the provider',
        'rejection_refusal': 'The model refused', 'rejection_no_output': 'No text in the reply',
        'rejection_not_json': 'Reply was not JSON', 'rejection_schema': 'Did not match the schema',
        'rejection_section_count': 'Wrong number of sections', 'rejection_section_identity': 'Section ids did not match',
        'rejection_source_citation': 'Citation not found in the sources', 'rejection_content': 'Content outside the limits',
        'rejection_usage': 'Implausible token counts', 'rejection_oversized': 'Reply over 2 MB',
        'rejection_unreadable': 'Reply could not be read',
    },
    'uz': {
        'basis': 'Haqiqiy provayder so‘rovlari, jumladan xato va rad etilgan javoblar. Har bir provayder javobining tokenlari bir marta sanaladi. Hisobotda hujjat mazmuni saqlanmaydi.',
        'retention': 'Sarf metama’lumotlari 90 kun saqlanadi. Oldingi so‘rovlar tiklanmaydi. Bu token soni — to‘lov hisoboti yoki puldagi baho emas.',
        'subsets': 'Keshdan o‘qilgan va keshga yozilgan tokenlar kirish tokenlarining, mulohaza tokenlari esa chiqish tokenlarining bir qismidir. Ularni jamiga qayta qo‘shmang.',
        'attempts': 'Provayder so‘rovlari', 'responses': 'Noyob javoblar / IDsiz so‘rovlar',
        'duplicates': 'Takroriy javoblar', 'failed': 'Xato yoki rad etilgan so‘rovlar',
        'unknown_environment': 'Muhiti noma’lum so‘rovlar (tanlangan muhit hisobiga kirmaydi)',
        'input_tokens': 'Ma’lum kirish tokenlari', 'output_tokens': 'Ma’lum chiqish tokenlari',
        'total_tokens': 'Ma’lum jami tokenlar', 'cached_input_tokens': 'Keshdan o‘qilgan ma’lum tokenlar',
        'cache_write_input_tokens': 'Keshga yozilgan ma’lum tokenlar', 'reasoning_output_tokens': 'Ma’lum mulohaza tokenlari',
        'unknown': 'Noma’lum', 'unreported': 'Bu ko‘rsatkich berilmagan javoblar',
        'models': 'Model va bosqich bo‘yicha sarf', 'recent': 'So‘nggi provayder so‘rovlari',
        'requested': 'So‘ralgan model', 'resolved': 'Javob bergan model', 'stage': 'Bosqich',
        'latency': 'Davomiylik (ms)', 'started': 'Boshlandi', 'received': 'Javob olindi',
        'succeeded': 'Bajarildi', 'rejected': 'Javob rad etildi', 'failed_status': 'So‘rov xatosi',
        'generate': 'Yaratish', 'outline': 'Reja', 'revision': 'Tahrirlash', 'photo_pick': 'Rasm tanlash', 'expand': 'To‘ldirish', 'repair': 'Tuzatish',
        'replayed': 'Takroriy · jami tokenlarga kiritilmaydi', 'span': 'Bo‘limlar',
        'empty': 'Bu davrda provayder so‘rovlari yo‘q.',
        'reasons': 'Rad etilgan javoblar sababi bo‘yicha', 'reason': 'Sabab', 'count': 'Javoblar',
        'rejection_': 'Sabab yozilmagan',
        'rejection_cut_off': 'Token chegarasida uzilib qoldi', 'rejection_not_completed': 'Provayder javobni yakunlamadi',
        'rejection_refusal': 'Model javob berishni rad etdi', 'rejection_no_output': 'Javobda matn yo‘q',
        'rejection_not_json': 'Javob JSON emas', 'rejection_schema': 'Sxemaga mos kelmadi',
        'rejection_section_count': 'Bo‘limlar soni noto‘g‘ri', 'rejection_section_identity': 'Bo‘lim IDlari mos kelmadi',
        'rejection_source_citation': 'Iqtibos manbalarda topilmadi', 'rejection_content': 'Mazmun cheklovlardan tashqarida',
        'rejection_usage': 'Token soni ishonchsiz', 'rejection_oversized': 'Javob 2 MB dan katta',
        'rejection_unreadable': 'Javobni o‘qib bo‘lmadi',
    },
    'ru': {
        'basis': 'Фактические запросы к провайдеру, включая ошибки и отклонённые ответы. Токены каждого ответа учитываются один раз. Содержимое документов в отчёте не хранится.',
        'retention': 'Метаданные расхода хранятся 90 дней. Предыдущие запросы не восстанавливаются. Это количество токенов, а не счёт или оценка стоимости.',
        'subsets': 'Токены чтения и записи кеша входят во входные токены, токены рассуждений — в выходные. Не прибавляйте их к общему количеству.',
        'attempts': 'Запросы к провайдеру', 'responses': 'Уникальные ответы / запросы без ID',
        'duplicates': 'Повторные ответы', 'failed': 'Ошибки и отклонённые ответы',
        'unknown_environment': 'Запросы без сведений об окружении (не входят в выбранное окружение)',
        'input_tokens': 'Известные входные токены', 'output_tokens': 'Известные выходные токены',
        'total_tokens': 'Известное общее число токенов', 'cached_input_tokens': 'Известные токены чтения кеша',
        'cache_write_input_tokens': 'Известные токены записи кеша', 'reasoning_output_tokens': 'Известные токены рассуждений',
        'unknown': 'Неизвестно', 'unreported': 'Ответы без этого показателя',
        'models': 'Расход по модели и этапу', 'recent': 'Последние запросы к провайдеру',
        'requested': 'Запрошенная модель', 'resolved': 'Модель в ответе', 'stage': 'Этап',
        'latency': 'Время (мс)', 'started': 'Начат', 'received': 'Ответ получен',
        'succeeded': 'Выполнен', 'rejected': 'Ответ отклонён', 'failed_status': 'Ошибка запроса',
        'generate': 'Создание', 'outline': 'План', 'revision': 'Редактирование', 'photo_pick': 'Выбор фото', 'expand': 'Дополнение', 'repair': 'Исправление',
        'replayed': 'Повтор · исключён из суммы токенов', 'span': 'Разделы',
        'empty': 'За этот период запросов к провайдеру нет.',
        'reasons': 'Отклонённые ответы по причинам', 'reason': 'Причина', 'count': 'Ответы',
        'rejection_': 'Причина не записана',
        'rejection_cut_off': 'Обрезан на лимите токенов', 'rejection_not_completed': 'Провайдер не завершил ответ',
        'rejection_refusal': 'Модель отказалась отвечать', 'rejection_no_output': 'В ответе нет текста',
        'rejection_not_json': 'Ответ не в формате JSON', 'rejection_schema': 'Не соответствует схеме',
        'rejection_section_count': 'Неверное число разделов', 'rejection_section_identity': 'ID разделов не совпали',
        'rejection_source_citation': 'Цитата не найдена в источниках', 'rejection_content': 'Содержимое вне допустимых пределов',
        'rejection_usage': 'Неправдоподобное число токенов', 'rejection_oversized': 'Ответ больше 2 МБ',
        'rejection_unreadable': 'Не удалось прочитать ответ',
    },
}


def usage_report(filters):
    start, end = filters.bounds
    dated = ProviderAttempt.objects.filter(created_at__gte=start, created_at__lt=end)
    if filters.locale:
        dated = dated.filter(locale=filters.locale)
    if filters.channel:
        dated = dated.filter(origin_channel=filters.channel)
    rows = dated.filter(environment=filters.environment)
    canonical = rows.filter(duplicate_response=False)
    totals = rows.aggregate(attempts=Count('id'), duplicates=Count('id', filter=Q(duplicate_response=True)),
                            failed=Count('id', filter=Q(status__in=['failed', 'rejected'])))
    totals['responses'] = canonical.count()
    counts = canonical.aggregate(**{field + '_sum': Sum(field) for field in TOKEN_FIELDS},
                                 **{field + '_unknown': Count('id', filter=Q(**{field + '__isnull': True})) for field in TOKEN_FIELDS})
    for field in TOKEN_FIELDS:
        counts[field] = counts.pop(field + '_sum')
        if not totals['responses']:
            counts[field] = 0
    aggregates = dict(responses=Count('id'), input_sum=Sum('input_tokens'), output_sum=Sum('output_tokens'),
                      input_unknown=Count('id', filter=Q(input_tokens__isnull=True)),
                      output_unknown=Count('id', filter=Q(output_tokens__isnull=True)))
    return dict(totals=totals, counts=counts, unknown_environment=dated.filter(environment='unknown').count(),
                model_rows=canonical.values('provider', 'feature_id', 'requested_model', 'resolved_model', 'stage')
                .annotate(**aggregates).order_by('-responses', 'requested_model', 'stage'),
                reason_rows=rows.filter(status='rejected').values('rejection')
                .annotate(responses=Count('id')).order_by('-responses', 'rejection'),
                rows=rows.order_by('-created_at', '-id'))


def rejection_label(code, lang='en'):
    """Why a reply was rejected, in words; '' when nothing was recorded."""
    labels = LABELS.get(lang, LABELS['en'])
    return labels.get('rejection_' + code, code) if code else ''


def failure_reason(job, lang='en'):
    """Why a job that failed on the provider ended, in words, or ''.

    Named only when the reply that ended it came back and was refused
    (ProviderAttemptQuerySet.final_rejection), never an earlier one that was
    put right before something else failed.
    """
    if job.error_code != 'provider_failed':
        return ''
    return rejection_label(job.provider_attempts.final_rejection(), lang)


@require_staff('Analyst', 'Operations', 'Finance')
@require_GET
def usage_page(request):
    data = context(request, 'analytics/ai-usage')
    labels = LABELS[data['lang']]
    try:
        filters = Filters.from_request(request)
    except ValueError as error:
        return HttpResponseBadRequest(str(error))
    report = usage_report(filters)
    data.update(report, filters=filters, a=labels)
    data['cards'] = [{'label': labels[key], 'value': report['totals'][key]} for key in ('attempts', 'responses', 'duplicates', 'failed')]
    data['token_cards'] = [{'label': labels[field], 'value': report['counts'][field],
                           'unknown': report['counts'][field + '_unknown']} for field in TOKEN_FIELDS]
    data['pagination'] = Paginator(report['rows'], 30).get_page(request.GET.get('p'))
    data['model_rows'] = [{**row, 'stage_label': labels.get(row['stage'], row['stage']),
                          'input_tokens': row['input_sum'], 'output_tokens': row['output_sum']} for row in report['model_rows']]
    # Every rejection now keeps a reason, so only rows from before reasons were
    # kept have none: said so, not left blank.
    data['reason_rows'] = [{'label': labels.get('rejection_' + row['rejection'], row['rejection']),
                            'responses': row['responses']} for row in report['reason_rows']]
    for row in data['pagination']:
        row.status_label = labels.get('failed_status' if row.status == 'failed' else row.status, row.status)
        row.stage_label = labels.get(row.stage, row.stage)
        row.rejection_label = rejection_label(row.rejection, data['lang']) if row.status == 'rejected' else ''
    return finish_render(request, 'ops/ai_usage.html', data)
