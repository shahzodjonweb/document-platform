import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections,connection
from apps.core.shutdown import graceful_stop
from apps.studio.cv.reads import next_read
class Command(BaseCommand):
    help='Read the files CVs are made from, one at a time, the accounts taking turns (apps/studio/cv/reads.py).'
    def add_arguments(self,parser):parser.add_argument('--once',action='store_true',help='Read what is queued, then stop.')
    def handle(self,*args,**options):
        # SIGTERM (a deploy) finishes the read in hand and takes no new one;
        # one left by a reader that died is read again once its lease lapses.
        with graceful_stop() as stop:
            while not stop:
                # A connection the database dropped is opened again; never one a caller's transaction holds.
                if not connection.in_atomic_block:close_old_connections()
                read=next_read()
                if options['once'] and not read:return
                if not read and not stop:time.sleep(1)
