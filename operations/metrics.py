"""Metric definitions v1.0: one set of filters feeds charts, rows and exports."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo
from django.db.models import Count, Min, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from apps.core.models import Account, Job, FileAsset, OutboxEvent
from .middleware import known_zone, viewer_zone

DEFINITIONS_VERSION = '1.0.0'


@dataclass(frozen=True)
class Filters:
    date_from: str
    date_to: str
    timezone: str
    environment: str
    locale: str
    channel: str

    @classmethod
    def from_request(cls, request):
        # Reports count days in the viewer's own zone unless they pick another.
        tz_name = request.GET.get('timezone') or viewer_zone()
        if not known_zone(tz_name):
            raise ValueError('Invalid report timezone')
        tz = ZoneInfo(tz_name)
        today = timezone.now().astimezone(tz).date()
        try:
            start = date.fromisoformat(request.GET.get('date_from', str(today - timedelta(days=29))))
            end = date.fromisoformat(request.GET.get('date_to', str(today + timedelta(days=1))))
        except ValueError:
            raise ValueError('Use ISO dates: YYYY-MM-DD')
        if not 0 < (end - start).days <= 366:
            raise ValueError('Choose a date range of 1–366 days')
        env = request.GET.get('environment', 'production')
        locale = request.GET.get('locale', '')
        channel = request.GET.get('channel', '')
        if env not in {'production', 'development'} or locale not in {'', 'en', 'uz', 'ru'} or channel not in {'', 'web', 'bot', 'mini_app'}:
            raise ValueError('Invalid report filter')
        return cls(str(start), str(end), tz_name, env, locale, channel)

    @property
    def bounds(self):
        tz = ZoneInfo(self.timezone)
        return tuple(datetime.combine(date.fromisoformat(d), time.min, tz).astimezone(dt_timezone.utc)
                     for d in (self.date_from, self.date_to))

    def accounts(self, in_period=True):
        query = Account.objects.filter(is_test=self.environment == 'development')
        if self.locale:
            query = query.filter(locale=self.locale)
        if self.channel:
            query = query.filter(first_verified_channel=self.channel)
        start, end = self.bounds
        return query.filter(created_at__gte=start, created_at__lt=end) if in_period else query.filter(created_at__lt=end)

    def jobs(self):
        # Channel is task-origin channel for task metrics, first channel for acquisition.
        query = Job.objects.filter(account__is_test=self.environment == 'development')
        if self.locale:
            query = query.filter(account__locale=self.locale)
        if self.channel:
            query = query.filter(origin_channel=self.channel)
        start, end = self.bounds
        return query.filter(created_at__gte=start, created_at__lt=end)


def report(filters):
    accounts, jobs = filters.accounts(), filters.jobs()
    succeeded = jobs.filter(status='succeeded').count()
    failed = jobs.filter(status='failed').count()
    start, end = filters.bounds
    daily_values = {str(row['day']):row['count'] for row in accounts.annotate(
        day=TruncDate('created_at', tzinfo=ZoneInfo(filters.timezone))).values('day').annotate(count=Count('id'))}
    daily = []
    day, stop = date.fromisoformat(filters.date_from), date.fromisoformat(filters.date_to)
    while day < stop:
        daily.append({'date':str(day),'label':day.strftime('%d.%m'),'count':daily_values.get(str(day), 0)})
        day += timedelta(days=1)
    maximum = max([r['count'] for r in daily] + [1])
    for row in daily:
        row['height'] = round(100 * row['count'] / maximum, 1)
    feature_rows = list(jobs.values('feature_id').annotate(
        attempts=Count('id'), succeeded=Count('id', filter=Q(status='succeeded')),
        failed=Count('id', filter=Q(status='failed')), canceled=Count('id', filter=Q(status='canceled')),
        no_op=Count('id', filter=Q(status='no_op')), users=Count('account_id', distinct=True)).order_by('-attempts'))
    mature = accounts.filter(created_at__lte=min(timezone.now(), end) - timedelta(days=7)).annotate(
        first_success=Min('jobs__completed_at', filter=Q(jobs__status='succeeded')))
    mature_count, activated_count = 0, 0
    for account in mature.iterator():
        mature_count += 1
        activated_count += bool(account.first_success and account.first_success <= account.created_at + timedelta(days=7))
    durations = sorted((row['completed_at'] - row['started_at']).total_seconds() for row in jobs.filter(
        status='succeeded', started_at__isnull=False, completed_at__isnull=False).values('started_at','completed_at'))
    return {
        'definitions_version':DEFINITIONS_VERSION, 'filters':filters.__dict__, 'freshness':timezone.now().isoformat(),
        'totals':{'new_users':accounts.count(), 'active_users':jobs.values('account_id').distinct().count(),
                  'completed':succeeded, 'failed':failed,
                  'success_rate':round(100*succeeded/(succeeded+failed), 1) if succeeded+failed else None,
                  'queued':jobs.filter(status__in=['queued','running','finalizing']).count(),
                  'activated':round(100*activated_count/mature_count, 1) if mature_count else None,
                  'mature_cohort':mature_count},
        'daily':daily, 'feature_rows':feature_rows,
        'plan_mix':list(accounts.values('plan').annotate(count=Count('id')).order_by('plan')),
        'channel_mix':list(accounts.values('first_verified_channel').annotate(count=Count('id')).order_by('first_verified_channel')),
        'locale_mix':list(accounts.values('locale').annotate(count=Count('id')).order_by('locale')),
        'latency':{'median':round(durations[len(durations)//2],2) if durations else None,
                   'p95':round(durations[min(len(durations)-1,int(len(durations)*.95))],2) if durations else None},
    }


def system_snapshot(filters):
    files = FileAsset.objects.filter(account__in=filters.accounts(False))
    return {'stored_files':files.exclude(state__in=['deleted','revoked']).count(),
            'storage':files.exclude(state__in=['deleted','revoked']).aggregate(total=Sum('size_bytes'))['total'] or 0,
            'expired_pending':files.filter(expires_at__lte=timezone.now()).exclude(state__in=['deleted','revoked']).count(),
            'outbox_pending':OutboxEvent.objects.filter(delivered_at__isnull=True,job__in=filters.jobs()).count()}
