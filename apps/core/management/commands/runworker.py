import time
import shutil
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.core.models import OutboxEvent,Job
from apps.core.services import execute_job,settle_job,storage_path
class Command(BaseCommand):
    help='Drain durable job outbox; use --once for a finite run.'
    def add_arguments(self,parser): parser.add_argument('--once',action='store_true')
    def handle(self,*args,**options):
        while True:
            # A lost parser attempt has no external monetary side effects; release its reservation.
            for job in Job.objects.filter(status='running',lease_expires_at__lte=timezone.now()):
                settle_job(job.id,'failed',error_code='worker_interrupted')
                shutil.rmtree(storage_path(f'outputs/{job.account_id}/{job.id}'),ignore_errors=True)
            events=list(OutboxEvent.objects.filter(topic='job.execute',delivered_at__isnull=True).order_by('created_at')[:20])
            for event in events:
                job=execute_job(event.job_id)
                if job.status in ('succeeded','failed','canceled','no_op','expired'):
                    event.delivered_at=timezone.now()
                    event.save(update_fields=['delivered_at'])
            if options['once']: break
            if not events: time.sleep(1)
