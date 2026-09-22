import time
from django.core.management.base import BaseCommand
from apps.studio.batches import drain_batches
class Command(BaseCommand):
    help='Drive persisted batch parents through ordinary independently settled jobs.'
    def add_arguments(self,parser):parser.add_argument('--once',action='store_true')
    def handle(self,*args,**options):
        while True:
            drain_batches()
            if options['once']:return
            time.sleep(2)
