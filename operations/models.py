import uuid
from django.conf import settings
from django.db import models


class StaffSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)


class AuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=80)
    target = models.CharField(max_length=160, blank=True)
    reason = models.CharField(max_length=1000)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = [("view_analytics", "View aggregate analytics"), ("manage_support", "Manage support cases")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("Audit records are append-only")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Audit records are append-only")


class LoginAttempt(models.Model):
    key = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)


class IntegrationConfig(models.Model):
    """Secrets are encrypted separately from non-sensitive integration settings."""
    key = models.CharField(max_length=40, primary_key=True)
    encrypted_secrets = models.BinaryField(default=bytes)
    configuration = models.JSONField(default=dict)
    checked_at = models.DateTimeField(null=True)
    check_status = models.CharField(max_length=32, default='not_checked')
    updated_at = models.DateTimeField(auto_now=True)
