import base64
import getpass
import secrets
from urllib.parse import quote
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from operations.auth import ROLES, secret_cipher
from operations.models import StaffSession, StaffTOTP


class Command(BaseCommand):
    help = "Create a staff account with a role and enroll TOTP. Password is prompted, never an argument."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--role", choices=sorted(ROLES), default="Administrator")
        parser.add_argument("--reset-mfa", action="store_true")

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
        if created or options["reset_mfa"] or not StaffTOTP.objects.filter(user=user).exists():
            secret = base64.b32encode(secrets.token_bytes(20)).decode()
            StaffTOTP.objects.update_or_create(user=user, defaults={
                "encrypted_secret": secret_cipher().encrypt(secret.encode()).decode(), "last_counter": -1})
            self.stdout.write("Add this one-time enrollment URI to your authenticator; do not commit it:")
            self.stdout.write(f"otpauth://totp/PDF%20Master:{quote(user.username)}?secret={secret}&issuer=PDF%20Master")
        StaffSession.objects.filter(user=user).delete()
        self.stdout.write(self.style.SUCCESS("Staff account configured; existing sessions revoked."))
