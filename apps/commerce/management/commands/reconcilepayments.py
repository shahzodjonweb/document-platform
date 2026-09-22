from django.core.management.base import BaseCommand
from apps.commerce.services import reconcile_transactions,expire_subscriptions,qualify_referrals
class Command(BaseCommand):
    help='Reconcile server-confirmed Telegram transaction metadata, expire periods and qualify referrals.'
    def add_arguments(self,parser): parser.add_argument('--local-only',action='store_true')
    def handle(self,*args,**options):
        expired=expire_subscriptions();rewards=qualify_referrals()
        self.stdout.write(f'Expired subscriptions: {expired}; qualified referrals: {rewards}.')
        if not options['local_only']:
            result=reconcile_transactions();self.stdout.write(f'Checked {result.checked}; matched {result.matched}; issues {result.issues}.')
