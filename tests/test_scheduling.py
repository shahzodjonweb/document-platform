"""Fair dispatch selection and at-least-once publication / exactly-once work."""
import uuid
from datetime import timedelta
from unittest.mock import Mock
import pytest
from django.core.management import call_command
from django.db import connection
from django.utils import timezone
from apps.core.allowance import file_jobs_this_week
from apps.core.models import Account,Quote,Job,OutboxEvent
from apps.core.services import create_quote,submit_job,execute_job
from apps.core.scheduling import select_outbox,claim_publication,finish_publication,publish_pending,AGING_SECONDS,PUBLICATION_LEASE_SECONDS
from tests.test_platform import account,upload

pytestmark=pytest.mark.django_db


def queued(owner,plan,created,*,status='queued',topic='job.execute',delivered=False,feature='pdf.rotate'):
    q=Quote.objects.create(account=owner,feature_id=feature,parameters={},input_ids=[],policy={'plan':plan},expires_at=created+timedelta(hours=1))
    j=Job.objects.create(account=owner,quote=q,feature_id=feature,parameters={},input_ids=[],policy={'plan':plan},idempotency_key=uuid.uuid4().hex,request_hash=uuid.uuid4().hex,status=status,created_at=created)
    return OutboxEvent.objects.create(job=j,topic=topic,created_at=created,delivered_at=created if delivered else None)


def new_owner(number):return Account.objects.create(telegram_user_id=number,is_test=True)


def test_a_newer_premium_job_is_not_dispatched_before_an_older_free_job():
    # Every plan shares one queue: the plan never moves a job ahead of older work.
    now=timezone.now();free=queued(new_owner(501),'free',now-timedelta(seconds=40));plus=queued(new_owner(502),'plus',now-timedelta(seconds=20));premium=queued(new_owner(503),'premium',now-timedelta(seconds=1))
    assert [r.id for r in select_outbox(now=now)]==[free.id,plus.id,premium.id]
    assert select_outbox(limit=1,now=now)[0].id==free.id
    # Nor does a plan label on the account move its accepted job.
    Account.objects.filter(pk=premium.job.account_id).update(plan='premium')
    assert select_outbox(limit=1,now=now)[0].id==free.id


def test_age_override_prevents_free_starvation_under_new_premium_arrivals():
    now=timezone.now();free=queued(new_owner(510),'free',now-timedelta(seconds=AGING_SECONDS+1));plus=queued(new_owner(511),'plus',now-timedelta(seconds=AGING_SECONDS+10));premium=queued(new_owner(512),'premium',now)
    assert [r.id for r in select_outbox(limit=3,window=3,now=now)]==[plus.id,free.id,premium.id]
    fresh=queued(new_owner(513),'premium',now+timedelta(seconds=1))
    assert select_outbox(limit=1,now=now+timedelta(seconds=2))[0].id==plus.id


def test_round_robin_gives_each_owner_one_slot_before_a_second():
    now=timezone.now();a=new_owner(520);b=new_owner(521);c=new_owner(522)
    first=queued(a,'premium',now-timedelta(seconds=60));second=queued(a,'premium',now-timedelta(seconds=50));third=queued(a,'premium',now-timedelta(seconds=40));peer=queued(b,'premium',now-timedelta(seconds=30));free=queued(c,'free',now-timedelta(seconds=20))
    assert [r.id for r in select_outbox(limit=5,now=now)]==[first.id,peer.id,free.id,second.id,third.id]


def test_rotation_persists_between_publication_passes():
    now=timezone.now();a=new_owner(530);b=new_owner(531)
    first=queued(a,'premium',now-timedelta(seconds=60));second=queued(a,'premium',now-timedelta(seconds=50));peer=queued(b,'premium',now-timedelta(seconds=20))
    publisher=Mock();assert publish_pending(publisher,limit=1,now=now)['published']==1
    assert publisher.call_args.args==(str(first.job_id),)
    assert select_outbox(limit=1,for_publish=True,now=now+timedelta(seconds=1))[0].id==peer.id
    assert first.job_id!=second.job_id


def test_selection_bounded_and_excludes_running_terminal_delivered_other_topics():
    now=timezone.now();owner=new_owner(540)
    for state in ('running','succeeded','failed','canceled','no_op'):queued(owner,'premium',now,status=state)
    queued(owner,'premium',now,delivered=True);queued(owner,'premium',now,topic='other.topic')
    valid=queued(owner,'free',now)
    assert [r.id for r in select_outbox(limit=1,window=1,now=now)]==[valid.id]
    assert len(select_outbox(limit=10000,window=10000,now=now))==1
    with pytest.raises(ValueError):select_outbox(limit=0)


def test_publication_claim_lease_and_stale_owner_fencing():
    now=timezone.now();event=queued(new_owner(550),'free',now)
    first=claim_publication(event.id,now=now);assert first.publish_attempts==1
    assert claim_publication(event.id,now=now+timedelta(seconds=1)) is None
    second=claim_publication(event.id,now=now+timedelta(seconds=PUBLICATION_LEASE_SECONDS+1));assert second.publish_attempts==2
    assert finish_publication(first,False,now=now)==0
    assert finish_publication(second,True,now=now+timedelta(seconds=62))==1
    event.refresh_from_db();assert event.published_at and event.delivered_at is None
    assert select_outbox(for_publish=True,now=now+timedelta(seconds=63))==[]
    assert [r.id for r in select_outbox(for_publish=True,now=now+timedelta(seconds=363))]==[event.id]


def test_broker_failure_keeps_outbox_retryable_without_false_delivery():
    now=timezone.now();event=queued(new_owner(560),'plus',now)
    bad=Mock(side_effect=RuntimeError('Never log redis://private-credential@broker'))
    assert publish_pending(bad,now=now)=={'published':0,'failed':1,'skipped':0}
    event.refresh_from_db();assert event.delivered_at is None and event.published_at is None and event.publish_lease_until is None
    good=Mock();assert publish_pending(good,now=now)['published']==1
    assert publish_pending(good,now=now)['published']==0 and good.call_count==1


def test_republication_then_worker_repeat_executes_and_settles_once(monkeypatch):
    a=account();source=upload(a);quote=create_quote(a,'pdf.rotate',[str(source.id)],{})
    job,_=submit_job(a,quote.id,'scheduled-real-job');event=OutboxEvent.objects.get(job=job)
    publisher=Mock();monkeypatch.setattr('apps.core.management.commands.dispatchoutbox.process_job.delay',publisher)
    call_command('dispatchoutbox');call_command('dispatchoutbox')
    event.refresh_from_db();assert publisher.call_count==1 and event.delivered_at is None and event.published_at is not None
    OutboxEvent.objects.filter(pk=event.id).update(publish_lease_until=timezone.now()-timedelta(seconds=1))
    call_command('dispatchoutbox');assert publisher.call_count==2
    no_batch=Mock(side_effect=AssertionError('Normal worker must never execute batch parents'))
    monkeypatch.setattr('apps.studio.batches.drain_batches',no_batch)
    call_command('runworker',once=True);call_command('runworker',once=True);execute_job(job.id)
    job.refresh_from_db();event.refresh_from_db()
    assert job.status=='succeeded' and job.attempt_count==1 and event.delivered_at is not None
    assert Job.objects.count()==1 and file_jobs_this_week(a)==1
    assert not no_batch.called


def test_old_running_server_can_insert_outbox_without_new_columns():
    now=timezone.now();event=queued(new_owner(570),'free',now)
    # Mimic SQL emitted by the pre-migration server, without the new model fields.
    identifier=uuid.uuid4()
    with connection.cursor() as cursor:
        cursor.execute('INSERT INTO core_outboxevent (id, job_id, topic, created_at, delivered_at) VALUES (%s,%s,%s,%s,%s)',[identifier.hex,event.job_id.hex,'legacy.writer',now,None])
    row=OutboxEvent.objects.get(pk=identifier)
    assert row.publish_attempts==0 and row.published_at is None and row.publish_lease_until is None

def test_publisher_backpressure_does_not_flood_broker_on_repeated_passes():
    now=timezone.now()
    events=[queued(new_owner(10000+i),'premium',now-timedelta(seconds=30-i)) for i in range(25)]
    publisher=Mock()
    assert publish_pending(publisher,now=now)['published']==20
    assert publish_pending(publisher,now=now+timedelta(seconds=1))['published']==0
    assert publisher.call_count==20
    Job.objects.filter(pk=events[0].job_id).update(status='running',started_at=now)
    assert publish_pending(publisher,now=now+timedelta(seconds=2))['published']==1
    assert publisher.call_count==21


def test_the_ai_lane_selects_ai_writing_jobs_only_in_the_same_fair_order():
    # The worker still sees every job; the AI lane (ai-worker) only decks, documents and CVs.
    from apps.core.management.commands.runworker import lane_features
    now=timezone.now();a=new_owner(560);b=new_owner(561)
    rotate=queued(a,'free',now-timedelta(seconds=50))
    deck=queued(a,'free',now-timedelta(seconds=40),feature='ai.pptx')
    document=queued(b,'free',now-timedelta(seconds=30),feature='ai.pdf_topic')
    cv=queued(b,'free',now-timedelta(seconds=20),feature='ai.cv')
    export=queued(b,'free',now-timedelta(seconds=10),feature='export.generated_pptx')
    assert lane_features('all') is None
    assert [r.id for r in select_outbox(now=now)]==[rotate.id,document.id,deck.id,cv.id,export.id]
    assert [r.id for r in select_outbox(now=now,features=lane_features('ai'))]==[deck.id,document.id,cv.id]


def test_the_ai_lane_runner_leaves_other_jobs_to_the_worker(monkeypatch):
    from types import SimpleNamespace
    from apps.core.management.commands import runworker
    now=timezone.now();owner=new_owner(570)
    rotate=queued(owner,'free',now-timedelta(seconds=20))
    deck=queued(owner,'free',now-timedelta(seconds=10),feature='ai.pptx')
    ran=[]
    monkeypatch.setattr(runworker,'execute_job',lambda job_id:(ran.append(job_id),SimpleNamespace(status='succeeded'))[1])
    call_command('runworker',once=True,lane='ai',verbosity=0)
    assert ran==[deck.job_id]
    ran.clear()
    call_command('runworker',once=True,verbosity=0)
    assert ran==[rotate.job_id]


def test_the_ai_lane_has_its_own_container_like_the_worker_and_finishes_its_deck_on_a_deploy():
    import yaml
    from pathlib import Path
    root=Path(__file__).resolve().parent.parent
    production=yaml.safe_load((root/'infra/production/compose.yaml').read_text())['services']
    lane,worker=production['ai-worker'],production['worker']
    assert lane['command']==['python','manage.py','runworker','--lane','ai']
    assert worker['command']==['python','manage.py','runworker']
    assert lane['image']==worker['image'] and lane['read_only'] is True and lane['cap_drop']==['ALL']
    assert lane['stop_grace_period']==worker['stop_grace_period']=='600s'
    assert "'ai-worker'" in (root/'scripts/deploy/container_smoke.py').read_text().split("services=['api'",1)[1].split(']')[0]
