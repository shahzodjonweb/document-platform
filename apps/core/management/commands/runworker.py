import time
import shutil
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.core.models import OutboxEvent,Job
from apps.core.services import execute_job,settle_job,storage_path
from apps.core.scheduling import select_outbox
from apps.core.shutdown import graceful_stop
# Which jobs a runner takes. `all` is the worker that runs every tool; `ai` is the
# AI lane (the ai-worker service): AI writing jobs only. Both take AI jobs, so two
# run at once, and the worker alone still runs everything should the lane be down.
LANES=('all','ai')


def lane_features(lane):
    """The tools a lane's runner selects, or None for every tool."""
    if lane=='ai':
        from apps.studio.domain import GENERATION_IDS
        return sorted(GENERATION_IDS)
    return None


class Command(BaseCommand):
    help='Drain the fair normal-job outbox. Run runbatches separately for batch parents.'
    def add_arguments(self,parser):
        parser.add_argument('--once',action='store_true')
        parser.add_argument('--lane',choices=LANES,default='all',help='all: every tool (the worker); ai: AI writing jobs only (the ai-worker).')
    def handle(self,*args,**options):
        features=lane_features(options.get('lane') or 'all')
        selection={} if features is None else {'features':features}
        # SIGTERM (a deploy) finishes the job in hand and takes no new one.
        with graceful_stop() as stop:
            while not stop:
                # Release customer reservations after a lost attempt. Provider-side
                # costs are separate from this customer usage settlement.
                for job in Job.objects.filter(status='running',lease_expires_at__lte=timezone.now()).order_by('lease_expires_at')[:50]:
                    settle_job(job.id,'failed',error_code='worker_interrupted')
                    shutil.rmtree(storage_path(f'outputs/{job.account_id}/{job.id}'),ignore_errors=True)
                events=select_outbox(limit=20,**selection)
                for event in events:
                    # The rest stay queued for the worker that replaces this one.
                    if stop: break
                    job=execute_job(event.job_id)
                    if job.status in ('succeeded','failed','canceled','no_op','expired'):
                        event.delivered_at=timezone.now()
                        event.save(update_fields=['delivered_at'])
                if options['once']: break
                if not events and not stop: time.sleep(1)
