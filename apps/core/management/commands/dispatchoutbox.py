from django.core.management.base import BaseCommand
from apps.core.tasks import process_job
from apps.core.scheduling import publish_pending
class Command(BaseCommand):
    help='Publish a fair bounded outbox window to Celery with durable retry leases.'
    def handle(self,*args,**options):
        counts=publish_pending(process_job.delay)
        self.stdout.write(f'Published {counts["published"]}; deferred failures {counts["failed"]}. Worker settlement marks delivery.')
