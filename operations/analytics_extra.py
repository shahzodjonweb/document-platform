from datetime import timedelta
from dataclasses import replace
from django.db.models import Count,Min
from django.utils import timezone
from apps.core.models import AnalyticsEvent,Job

def engagement(filters):
    start,end=filters.bounds;as_of=min(end,timezone.now())
    # Activity is filtered by event channel, independent of the signup channel.
    accounts=replace(filters,channel='').accounts(False)
    events=AnalyticsEvent.objects.filter(account__in=accounts,occurred_at__lt=as_of,event_type__in=('job.accepted','practice.completed'))
    if filters.channel:events=events.filter(channel=filters.channel)
    cohort=list(filters.accounts().values('id','created_at'))
    stages=[]
    for name in ('account.created','upload.accepted','quote.created','job.succeeded'):
        count=AnalyticsEvent.objects.filter(account_id__in=[a['id'] for a in cohort],occurred_at__gte=start,occurred_at__lt=end,event_type=name).values('account_id').distinct().count()
        stages.append({'event':name,'count':len(cohort) if name=='account.created' else count})
    retention=[]
    # Small first-stage reporting queries; mature buckets only, never count future windows as zero.
    for day in (1,7,30):
        mature=[a for a in cohort if a['created_at']+timedelta(days=day+1)<=as_of]
        retained=0
        for a in mature:
            retained+=events.filter(account_id=a['id'],occurred_at__gte=a['created_at']+timedelta(days=day),occurred_at__lt=a['created_at']+timedelta(days=day+1)).exists()
        retention.append({'day':day,'eligible':len(mature),'retained':retained,'percent':round(retained*100/len(mature),1) if mature else None})
    activity=[{'days':days,'users':events.filter(occurred_at__gte=as_of-timedelta(days=days)).values('account_id').distinct().count()} for days in (1,7,30)]
    return {'funnel':stages,'retention':retention,'activity':activity,'as_of':as_of}
