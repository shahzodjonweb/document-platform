from django.core.management.base import BaseCommand
from apps.commerce.services import expire_subscriptions,qualify_referrals
class Command(BaseCommand):
    help='Expire paid periods and qualify referrals. Card transfers are reviewed by hand, so there is no provider to reconcile against.'
    def handle(self,*args,**options):
        expired=expire_subscriptions();rewards=qualify_referrals()
        self.stdout.write(f'Expired subscriptions: {expired}; qualified referrals: {rewards}.')
