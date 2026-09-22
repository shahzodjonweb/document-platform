import uuid
from django.db import models
from django.utils import timezone

class GenerationDraft(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    account=models.ForeignKey('core.Account',on_delete=models.CASCADE)
    feature_id=models.CharField(max_length=100)
    version=models.PositiveIntegerField(default=1)
    encrypted_data=models.BinaryField()
    provider_mode=models.CharField(max_length=24,default='local_fixture')
    created_at=models.DateTimeField(default=timezone.now)
    expires_at=models.DateTimeField()

class SavedDefinition(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    account=models.ForeignKey('core.Account',on_delete=models.CASCADE)
    kind=models.CharField(max_length=20)
    name=models.CharField(max_length=160)
    version=models.PositiveIntegerField(default=1)
    definition=models.JSONField(default=dict)
    created_at=models.DateTimeField(default=timezone.now)

class EducationProject(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    account=models.ForeignKey('core.Account',on_delete=models.CASCADE)
    title=models.CharField(max_length=160)
    encrypted_content=models.BinaryField()
    version=models.PositiveIntegerField(default=1)
    created_at=models.DateTimeField(default=timezone.now)
    expires_at=models.DateTimeField()

class PracticeAttempt(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    project=models.ForeignKey(EducationProject,on_delete=models.CASCADE,related_name='attempts')
    idempotency_key=models.CharField(max_length=128)
    request_hash=models.CharField(max_length=64)
    result=models.JSONField(default=dict)
    created_at=models.DateTimeField(default=timezone.now)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['project','idempotency_key'],name='one_practice_submission')]

class ShareGrant(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    account=models.ForeignKey('core.Account',on_delete=models.CASCADE)
    artifact=models.ForeignKey('core.Artifact',on_delete=models.CASCADE)
    token_hash=models.CharField(max_length=64,unique=True)
    expires_at=models.DateTimeField()
    revoked_at=models.DateTimeField(null=True)
    created_at=models.DateTimeField(default=timezone.now)

class EditorDocument(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    account=models.ForeignKey('core.Account',on_delete=models.CASCADE)
    file=models.ForeignKey('core.FileAsset',on_delete=models.CASCADE)
    version=models.PositiveIntegerField(default=1)
    commands=models.JSONField(default=list)
    input_ids=models.JSONField(default=list)
    created_at=models.DateTimeField(default=timezone.now)

class ProviderUsage(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    job=models.ForeignKey('core.Job',on_delete=models.CASCADE)
    provider=models.CharField(max_length=24)
    model=models.CharField(max_length=100,blank=True)
    input_tokens=models.PositiveIntegerField(default=0)
    output_tokens=models.PositiveIntegerField(default=0)
    outcome=models.CharField(max_length=24)
    created_at=models.DateTimeField(default=timezone.now)

class WorkflowRun(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    account=models.ForeignKey('core.Account',on_delete=models.CASCADE)
    definition=models.ForeignKey(SavedDefinition,on_delete=models.SET_NULL,null=True)
    idempotency_key=models.CharField(max_length=128)
    request_hash=models.CharField(max_length=64)
    job_ids=models.JSONField(default=list)
    status=models.CharField(max_length=24,default='running')
    created_at=models.DateTimeField(default=timezone.now)
    snapshot=models.JSONField(default=dict)
    lease_token=models.UUIDField(null=True)
    lease_until=models.DateTimeField(null=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['account','idempotency_key'],name='one_workflow_run')]

from .batch_models import BatchQuote,BatchRun,BatchItem
