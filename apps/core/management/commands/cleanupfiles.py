from django.core.management.base import BaseCommand
from apps.core.services import cleanup_expired
class Command(BaseCommand):
    help='Revoke and delete expired private binaries while preserving task metadata.'
    def handle(self,*args,**options): self.stdout.write(f'Deleted {cleanup_expired()} expired files.')
