from django.core.management.base import BaseCommand,CommandError
from apps.core.models import Account
from telegram.local import dispatch_local
class Command(BaseCommand):
    help='Run a local test account through real aiogram command handlers without a bot token.'
    def add_arguments(self,parser):
        parser.add_argument('text',nargs='?',default='/start')
        parser.add_argument('--account',type=int,default=900000001)
    def handle(self,*args,**options):
        account=Account.objects.filter(telegram_user_id=options['account'],is_test=True).first()
        if not account: raise CommandError('Sign in to the local development account first.')
        result=dispatch_local(account,text=options['text'])
        for message in result['messages'][-5:]: self.stdout.write(f'{message["direction"]}: {message["text"]}')
