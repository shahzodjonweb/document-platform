"""Today: what happened since midnight, and what is waiting for someone.

Counts only: no customer content appears here, so every staff role can open
it. Cards that lead somewhere a role cannot go are left out for that role.
"""
from dataclasses import replace
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.db.models import Min, Sum
from django.utils import timezone

from apps.core.models import Job, SupportTicket

# The business runs on Tashkent time; a report timezone in the URL wins.
ZONE = 'Asia/Tashkent'


def day(filters, request, back=0):
    """The filters narrowed to one calendar day (today, or `back` days ago)."""
    zone = request.GET.get('timezone') or ZONE
    date = timezone.now().astimezone(ZoneInfo(zone)).date() - timedelta(days=back)
    return replace(filters, date_from=str(date), date_to=str(date + timedelta(days=1)), timezone=zone)


def counts(filters, money):
    from apps.commerce.models import Payment
    from apps.studio.models import GenerationRecord
    start, end = filters.bounds
    jobs = filters.jobs()
    row = {
        'new_users': filters.accounts().count(),
        'active_users': jobs.values('account_id').distinct().count(),
        'tasks': jobs.count(),
        'ai_documents': GenerationRecord.objects.filter(
            account__is_test=filters.environment == 'development', created_at__gte=start, created_at__lt=end).count(),
    }
    if money:
        row['received'] = Payment.objects.filter(
            currency='UZS', sandbox=filters.environment == 'development', account__in=filters.accounts(False),
            occurred_at__gte=start, occurred_at__lt=end).aggregate(n=Sum('amount_xtr'))['n'] or 0
    return row


def summary(request, filters, labels, ok):
    """Everything the Today page shows, for a role checked with `ok(roles)`."""
    from apps.commerce.models import ManualPayment
    today, yesterday = day(filters, request), day(filters, request, 1)
    money = ok(['Analyst', 'Finance'])
    now, before = counts(today, money), counts(yesterday, money)
    links = {'new_users': ('users', ['Support']), 'active_users': ('analytics/engagement', ['Analyst']),
             'tasks': ('jobs', ['Operations', 'Support']), 'ai_documents': ('generations', ['Support', 'Operations']),
             'received': ('payments', ['Finance'])}
    stats = [{'key': key, 'label': labels['today_' + key], 'value': value, 'yesterday': before[key],
              'href': '/ops/' + links[key][0] if ok(links[key][1]) else ''}
             for key, value in now.items()]

    actions = []
    if ok(['Finance']):
        waiting = ManualPayment.objects.filter(status='submitted')
        actions.append({'key': 'payments', 'icon': 'card', 'count': waiting.count(), 'href': '/ops/payments#review',
                        'title': labels['today_payments'], 'oldest': waiting.aggregate(at=Min('submitted_at'))['at'],
                        'empty': labels['today_payments_none']})
    if ok(['Support']):
        open_cases = SupportTicket.objects.filter(status='open')
        actions.append({'key': 'support', 'icon': 'support', 'count': open_cases.count(), 'href': '/ops/support?status=open',
                        'title': labels['today_support'], 'oldest': open_cases.aggregate(at=Min('created_at'))['at'],
                        'empty': labels['today_support_none']})
    if ok(['Operations']):
        failed = today.jobs().filter(status='failed')
        actions.append({'key': 'failed', 'icon': 'alert', 'count': failed.count(), 'href': '/ops/jobs?status=failed',
                        'title': labels['today_failed'], 'oldest': None, 'empty': labels['today_failed_none']})

    environment_jobs = Job.objects.filter(account__is_test=filters.environment == 'development')
    health = {'queue': environment_jobs.filter(status__in=['queued', 'running']).count(),
              'failed': now['tasks'] and today.jobs().filter(status='failed').count(),
              'storage': storage_state(), 'system_href': '/ops/system' if ok(['Operations']) else ''}
    return {'today_filters': today, 'stats': stats, 'actions': actions, 'health': health,
            'recent_jobs': today.jobs().select_related('account').order_by('-created_at')[:8]
            if ok(['Operations', 'Support']) else []}


def storage_state():
    """'ok', 'problem' or '' (files are kept on the server, nothing to watch)."""
    try:
        from apps.core import storage
        from apps.core.storage_health import summary as storage_summary
        if not storage.config().get('ready'):
            return ''
        return 'ok' if storage_summary()['healthy'] else 'problem'
    except Exception:
        return ''
