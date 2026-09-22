"""Bounded dispatch with aging, account rotation, and durable publication leases.

The catalog grants Premium queue priority; Free and Plus share standard service.
Waiting five minutes overrides tier priority. Publication is at-least-once;
the ordinary job row lock and settlement ledger remain the exactly-once boundary.
"""
from collections import defaultdict,deque
from datetime import timedelta,datetime,timezone as dt_timezone
from django.db import transaction
from django.db.models import Case,When,Value,IntegerField,Max,Q
from django.utils import timezone
from .models import Job,OutboxEvent

AGING_SECONDS=300
PUBLICATION_LEASE_SECONDS=60
PUBLICATION_RETRY_SECONDS=300
DEFAULT_WINDOW=200
MAX_WINDOW=1000
MAX_DISPATCH=50


def select_outbox(*,limit=20,window=DEFAULT_WINDOW,for_publish=False,now=None):
    now=now or timezone.now()
    if type(limit) is not int or type(window) is not int or limit<1 or window<1:raise ValueError('Positive dispatch limits required')
    limit=min(limit,MAX_DISPATCH);window=min(max(window,limit),MAX_WINDOW)
    cutoff=now-timedelta(seconds=AGING_SECONDS)
    query=OutboxEvent.objects.filter(topic='job.execute',delivered_at__isnull=True,job__status='queued')
    if for_publish:query=query.filter(Q(publish_lease_until__isnull=True)|Q(publish_lease_until__lte=now))
    rank=Case(When(created_at__lte=cutoff,then=Value(0)),When(job__policy__plan='premium',then=Value(1)),default=Value(2),output_field=IntegerField())
    candidates=list(query.annotate(queue_rank=rank).select_related('job').order_by('queue_rank','created_at','id')[:window])
    owners={row.job.account_id for row in candidates}
    served={row['account_id']:row['last'] for row in Job.objects.filter(account_id__in=owners,started_at__isnull=False).values('account_id').annotate(last=Max('started_at'))}
    for row in OutboxEvent.objects.filter(job__account_id__in=owners,published_at__isnull=False).values('job__account_id').annotate(last=Max('published_at')):
        owner=row['job__account_id'];served[owner]=max(served.get(owner) or row['last'],row['last'])
    queues=defaultdict(deque)
    for row in candidates:queues[row.job.account_id].append(row)
    never=datetime.min.replace(tzinfo=dt_timezone.utc)
    def owner_order(owner):
        head=queues[owner][0]
        # Oldest aged work leads even when its account was recently served.
        secondary=head.created_at if head.queue_rank==0 else served.get(owner,never)
        return head.queue_rank,secondary,head.created_at,str(owner)
    chosen=[]
    while queues and len(chosen)<limit:
        for owner in sorted(queues,key=owner_order):
            chosen.append(queues[owner].popleft())
            if not queues[owner]:del queues[owner]
            if len(chosen)==limit:break
    return chosen


@transaction.atomic
def claim_publication(identifier,*,now=None):
    now=now or timezone.now()
    row=OutboxEvent.objects.select_for_update().select_related('job').filter(pk=identifier,topic='job.execute',delivered_at__isnull=True,job__status='queued').first()
    if row is None or row.publish_lease_until and row.publish_lease_until>now:return None
    row.publish_lease_until=now+timedelta(seconds=PUBLICATION_LEASE_SECONDS)
    row.publish_attempts+=1
    row.save(update_fields=['publish_lease_until','publish_attempts'])
    return row


def finish_publication(row,success,*,now=None):
    now=now or timezone.now()
    values={'publish_lease_until':now+timedelta(seconds=PUBLICATION_RETRY_SECONDS) if success else None}
    if success:values['published_at']=now
    # A timed-out old publisher cannot erase a newer dispatcher's lease.
    return OutboxEvent.objects.filter(pk=row.id,delivered_at__isnull=True,publish_attempts=row.publish_attempts,publish_lease_until=row.publish_lease_until).update(**values)


def publish_pending(publish,*,limit=20,now=None):
    result={'published':0,'failed':0,'skipped':0}
    if type(limit) is not int or limit<1:raise ValueError('Positive dispatch limit required')
    now=now or timezone.now()
    # Keep broker backlog bounded so future priority/aging decisions remain
    # useful. Running jobs have already left the broker's waiting window.
    outstanding=OutboxEvent.objects.filter(topic='job.execute',delivered_at__isnull=True,job__status='queued',publish_lease_until__gt=now).count()
    remaining=max(0,min(limit,MAX_DISPATCH)-outstanding)
    if not remaining:return result
    for candidate in select_outbox(limit=remaining,for_publish=True,now=now):
        row=claim_publication(candidate.id,now=now)
        if row is None:result['skipped']+=1;continue
        try:publish(str(row.job_id))
        except Exception:
            # Broker errors can contain credentials; expose counters only.
            finish_publication(row,False,now=now);result['failed']+=1
        else:
            finish_publication(row,True,now=now);result['published']+=1
    return result
