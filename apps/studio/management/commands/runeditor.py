import time
from pathlib import Path
from django.core.management.base import BaseCommand
from django.db import close_old_connections,connection
from apps.core.shutdown import graceful_stop
from apps.studio import tasks
# Read by the compose healthcheck: touched between tasks, of which the longest takes about two minutes.
HEARTBEAT='/tmp/editor-heartbeat'
class Command(BaseCommand):
    help='Do the editor\'s free work, one task at a time, the accounts taking turns (apps/studio/tasks.py).'
    def add_arguments(self,parser):
        parser.add_argument('--once',action='store_true',help='Do what is queued, then stop.')
        parser.add_argument('--heartbeat',default=HEARTBEAT)
    def handle(self,*args,**options):
        beat=Path(options['heartbeat'])
        # SIGTERM (a deploy) finishes the task in hand and takes no new one. What a runner that
        # died left is taken again once its lease lapses; this one may be starting in its place.
        tasks.sweep()
        try:
            with graceful_stop() as stop:
                while not stop:
                    beat.touch()
                    # A connection the database dropped is opened again; never one a caller's transaction holds.
                    if not connection.in_atomic_block:close_old_connections()
                    done=tasks.next_task()
                    if options['once'] and not done:return
                    if not done and not stop:time.sleep(1)
        finally:tasks.forget_office()
