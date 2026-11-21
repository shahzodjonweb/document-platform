"""Metric definitions v1.0: one set of filters feeds charts, rows and exports."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo
from django.db.models import Count, Min, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from apps.core.models import Account, Job, FileAsset, OutboxEvent
from apps.commerce.models import BotDelivery
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


# What the category panel watches, as the share of each category's documents
# that carry it: a fact the AI was not given and left blank (a job warning), a
# PDF drawn on the emergency page or a block drawn plain (the renderer's
# metadata), and a deck slide whose planned layout did not hold.
CATEGORY_CODES = ('facts_blanked', 'template_fallback', 'block_fallback', 'repinned')


def category_label(category_id, lang):
    """A category's label in the catalogue, or '' for an id it no longer holds (shown as the id itself)."""
    from apps.studio import categories
    entry = categories.get(category_id)
    return entry.label(lang) if entry is not None else ''


def ai_documents(filters):
    """AI PDF and AI Slides documents of the period: not a change to one, not an outline.

    A JSON key is tested for being absent rather than excluded, because
    exclude() on one also drops every job without the key.
    """
    from apps.studio.categories.catalogue import FEATURES
    return (filters.jobs().filter(feature_id__in=FEATURES.values(), parameters__revision__isnull=True)
            .filter(Q(parameters__stage__isnull=True) | ~Q(parameters__stage='outline')))


def category_jobs(filters):
    """The AI documents made with a category. `Job.parameters.category` is the quote's, so a job
    without it (Boshqa, the web, anything from before categories) is not one of them."""
    return ai_documents(filters).filter(parameters__category__isnull=False)


def _codes(warnings, metadata):
    """Which watched codes one finished document carries, from its job's warnings and its file's metadata."""
    named = {code for code in [*(warnings or ()), *((metadata or {}).get('warnings') or ())] if isinstance(code, str)}
    found = {code for code in ('facts_blanked', 'template_fallback', 'repinned') if code in named}
    if any(code.startswith('block_fallback:') for code in named):
        found.add('block_fallback')
    if (metadata or {}).get('template_fallback'):
        found.add('template_fallback')
    if (metadata or {}).get('repinned'):
        found.add('repinned')
    return found


def category_report(filters, t, lang='en'):
    """AI documents by category beside how often each category was chosen, and how each one's documents fared.

    Made: the `feature_rows` columns for the jobs of `category_jobs`. Chosen:
    the bot's `category.chosen` taps (a closed id, never anything the customer
    wrote), so chosen-versus-made can be read from the first day. The watched
    codes are shares of each category's succeeded documents and the failure
    rate is failed / (succeeded + failed), as the success rate is. Rows follow
    the lists' order; an id the catalogue no longer holds keeps its row,
    labelled by its id. Boshqa is not a category and has no row.
    """
    from django.db.models import CharField, Value
    from django.db.models.fields.json import KT
    from django.db.models.functions import Coalesce
    from apps.core.models import AnalyticsEvent, Artifact
    from apps.studio import categories
    from apps.studio.categories.catalogue import FEATURES
    jobs = category_jobs(filters).annotate(category=KT('parameters__category'))
    made = {row['category']: row for row in jobs.values('category').annotate(
        attempts=Count('id'), succeeded=Count('id', filter=Q(status='succeeded')),
        failed=Count('id', filter=Q(status='failed')), canceled=Count('id', filter=Q(status='canceled')),
        no_op=Count('id', filter=Q(status='no_op')), users=Count('account_id', distinct=True))}
    start, end = filters.bounds
    events = AnalyticsEvent.objects.filter(event_type=categories.CHOSEN_EVENT, environment=filters.environment,
                                           occurred_at__gte=start, occurred_at__lt=end)
    if filters.channel:
        events = events.filter(channel=filters.channel)
    if filters.locale:
        events = events.filter(locale=filters.locale)
    chosen = {row['category']: row for row in events.annotate(
        category=Coalesce(KT('properties__category'), Value('unknown'), output_field=CharField()))
        .values('category').annotate(chosen=Count('id'), choosers=Count('account_id', distinct=True))}
    # One document per job: its warnings, then the codes its file's metadata carries.
    finished = jobs.filter(status='succeeded')
    found = {job_id: (category, _codes(warnings, None)) for job_id, category, warnings
             in finished.values_list('id', 'category', 'warnings')}
    for job_id, warnings, repinned, fallback in (Artifact.objects.filter(job__in=finished.values('id'), role='user_document')
                                                 .values_list('job_id', 'file__metadata__warnings',
                                                              'file__metadata__repinned',
                                                              'file__metadata__template_fallback')):
        if job_id in found:
            found[job_id][1].update(_codes(None, {'warnings': warnings, 'repinned': repinned,
                                                  'template_fallback': fallback}))
    carried = {}
    for category, codes in found.values():
        for code in codes:
            carried[(category, code)] = carried.get((category, code), 0) + 1
    order = [entry.id for feature in FEATURES.values() for entry in categories.for_feature(feature)]
    seen = set(made) | set(chosen)
    services = {'pdf': t['categories_service_pdf'], 'slides': t['categories_service_slides']}
    rows = []
    for category in [item for item in order if item in seen] + sorted(seen - set(order)):
        counts = made.get(category, {})
        succeeded, failed = counts.get('succeeded', 0), counts.get('failed', 0)
        entry = categories.get(category)
        row = {'id': category, 'label': category_label(category, lang),
               'service': services[entry.service] if entry is not None else '',
               'chosen': chosen.get(category, {}).get('chosen', 0), 'choosers': chosen.get(category, {}).get('choosers', 0),
               **{name: counts.get(name, 0) for name in ('attempts', 'succeeded', 'failed', 'canceled', 'no_op', 'users')},
               'failure_rate': round(100 * failed / (succeeded + failed), 1) if succeeded + failed else None}
        for code in CATEGORY_CODES:
            row[code] = round(100 * carried.get((category, code), 0) / succeeded, 1) if succeeded else None
        row['shares'] = [row[code] for code in CATEGORY_CODES]
        rows.append(row)
    # How much of the AI documents of the period a category made, beside the lists.
    every = ai_documents(filters).count()
    made_total = sum(row['attempts'] for row in rows)
    return {'rows': rows, 'chosen': sum(row['chosen'] for row in rows), 'made': made_total,
            'succeeded': sum(row['succeeded'] for row in rows), 'every': every,
            'share': round(100 * made_total / every, 1) if every else None,
            'of_all': t['catreport_of_all'].format(n=made_total, total=every),
            'codes': [{'code': code, 'label': t['catreport_' + code], 'definition': t[f'catreport_{code}_def']}
                      for code in CATEGORY_CODES]}


# A result file the bot still has to send (telegram/delivery.py drain).
DELIVERY_WAITING = ('pending', 'retrying', 'sending')


def system_snapshot(filters):
    files = FileAsset.objects.filter(account__in=filters.accounts(False))
    return {'stored_files':files.exclude(state__in=['deleted','revoked']).count(),
            'storage':files.exclude(state__in=['deleted','revoked']).aggregate(total=Sum('size_bytes'))['total'] or 0,
            'expired_pending':files.filter(expires_at__lte=timezone.now()).exclude(state__in=['deleted','revoked']).count(),
            'outbox_pending':OutboxEvent.objects.filter(delivered_at__isnull=True,job__in=filters.jobs()).count(),
            # Files the bot has not sent minutes after they were ready. A few may wait out Telegram's rate limit;
            # many, staying for long, mean the bot's sender has stopped. (Development: test accounts are never sent.)
            'deliveries_waiting':BotDelivery.objects.filter(account__is_test=filters.environment == 'development',
                                                            status__in=DELIVERY_WAITING,
                                                            created_at__lt=timezone.now()-timedelta(minutes=2)).count()}
