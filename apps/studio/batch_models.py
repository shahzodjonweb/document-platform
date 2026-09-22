"""Immutable batch confirmations and durable independently billed children."""
import uuid
from django.db import models
from django.utils import timezone

class BatchQuote(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    account=models.ForeignKey('core.Account',on_delete=models.CASCADE)
    feature_id=models.CharField(max_length=100)
    child_quote_ids=models.JSONField(default=list)
    meters=models.JSONField(default=dict)
    policy=models.JSONField(default=dict)
    created_at=models.DateTimeField(default=timezone.now)
    expires_at=models.DateTimeField()

class BatchRun(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    account=models.ForeignKey('core.Account',on_delete=models.CASCADE)
    quote=models.OneToOneField(BatchQuote,on_delete=models.PROTECT)
    idempotency_key=models.CharField(max_length=128)
    request_hash=models.CharField(max_length=64)
    status=models.CharField(max_length=24,default='queued')
    lease_until=models.DateTimeField(null=True)
    lease_token=models.UUIDField(null=True)
    created_at=models.DateTimeField(default=timezone.now)
    completed_at=models.DateTimeField(null=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['account','idempotency_key'],name='one_batch_submission')]

class BatchItem(models.Model):
    run=models.ForeignKey(BatchRun,on_delete=models.CASCADE,related_name='children')
    index=models.PositiveIntegerField()
    quote=models.OneToOneField('core.Quote',on_delete=models.PROTECT)
    job=models.OneToOneField('core.Job',null=True,on_delete=models.PROTECT)
    status=models.CharField(max_length=24,default='pending')
    error_code=models.CharField(max_length=80,blank=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['run','index'],name='one_batch_position')]
        ordering=['index']
