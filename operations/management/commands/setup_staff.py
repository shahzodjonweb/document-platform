import getpass
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from operations.auth import ROLES
from operations.models import StaffSession


class Command(BaseCommand):
    help = "Create or reset a staff account with a role. Password is prompted, never an argument."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--role", choices=sorted(ROLES), default="Administrator")

    def handle(self, *args, **options):
        password = getpass.getpass("Staff password (minimum 12 characters): ")
        if len(password) < 12:
            raise CommandError("Choose a password of at least 12 characters")
        user, created = get_user_model().objects.get_or_create(username=options["username"])
        user.is_staff = True
        user.is_active = True
        user.set_password(password)
        user.save()
        user.groups.set([Group.objects.get_or_create(name=options["role"])[0]])
        StaffSession.objects.filter(user=user).delete()
        self.stdout.write(self.style.SUCCESS("Staff account configured; existing sessions revoked."))
