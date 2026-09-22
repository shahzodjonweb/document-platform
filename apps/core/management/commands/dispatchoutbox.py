from django.core.management.base import BaseCommand
from apps.core.models import OutboxEvent
from apps.core.tasks import process_job
class Command(BaseCommand):
    help='Publish uncompleted outbox work to Celery. Repeated publication is safe.'
    def handle(self,*args,**options):
        for event in OutboxEvent.objects.filter(topic='job.execute',delivered_at__isnull=True):
            process_job.delay(str(event.job_id))
        self.stdout.write('Published pending jobs. Worker settlement marks delivery.')
