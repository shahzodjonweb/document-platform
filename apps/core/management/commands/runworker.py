import time
import shutil
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.core.models import OutboxEvent,Job
from apps.core.services import execute_job,settle_job,storage_path
from apps.core.scheduling import select_outbox
class Command(BaseCommand):
    help='Drain the fair normal-job outbox. Run runbatches separately for batch parents.'
    def add_arguments(self,parser): parser.add_argument('--once',action='store_true')
    def handle(self,*args,**options):
        while True:
            # Release customer reservations after a lost attempt. Provider-side
            # costs are separate from this customer usage settlement.
            for job in Job.objects.filter(status='running',lease_expires_at__lte=timezone.now()).order_by('lease_expires_at')[:50]:
                settle_job(job.id,'failed',error_code='worker_interrupted')
                shutil.rmtree(storage_path(f'outputs/{job.account_id}/{job.id}'),ignore_errors=True)
            events=select_outbox(limit=20)
            for event in events:
                job=execute_job(event.job_id)
                if job.status in ('succeeded','failed','canceled','no_op','expired'):
                    event.delivered_at=timezone.now()
                    event.save(update_fields=['delivered_at'])
            if options['once']: break
            if not events: time.sleep(1)
