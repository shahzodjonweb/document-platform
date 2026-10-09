import time
from django.core.management.base import BaseCommand
from apps.core.shutdown import graceful_stop
from apps.studio.batches import drain_batches
class Command(BaseCommand):
    help='Drive persisted batch parents through ordinary independently settled jobs.'
    def add_arguments(self,parser):parser.add_argument('--once',action='store_true')
    def handle(self,*args,**options):
        # SIGTERM (a deploy) finishes the batch in hand and starts no new one.
        with graceful_stop() as stop:
            while not stop:
                drain_batches(stop=stop)
                if options['once']:return
                if not stop:time.sleep(2)
