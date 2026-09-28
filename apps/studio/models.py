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


class ProviderAttempt(models.Model):
    """Content-free provider accounting, retained independently of customer jobs.

    Missing usage is unknown, never zero. A provider response may be replayed
    by idempotency: every network attempt remains visible, but only the first
    response has a response_key and contributes to token totals.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey('core.Job', on_delete=models.SET_NULL, null=True, related_name='provider_attempts')
    request_key = models.CharField(max_length=64, db_index=True)
    provider = models.CharField(max_length=24, default='openai')
    feature_id = models.CharField(max_length=100)
    requested_model = models.CharField(max_length=100)
    resolved_model = models.CharField(max_length=100, blank=True)
    stage = models.CharField(max_length=24, default='generate')
    span_start = models.PositiveIntegerField(null=True)
    span_end = models.PositiveIntegerField(null=True)
    environment = models.CharField(max_length=16, default='unknown')
    locale = models.CharField(max_length=2, blank=True)
    origin_channel = models.CharField(max_length=16, blank=True)
    status = models.CharField(max_length=16, default='started')
    provider_status = models.CharField(max_length=24, blank=True)
    response_id = models.CharField(max_length=255, blank=True)
    response_key = models.CharField(max_length=64, unique=True, null=True)
    duplicate_response = models.BooleanField(default=False)
    duplicate_of = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, related_name='+')
    input_tokens = models.PositiveBigIntegerField(null=True)
    output_tokens = models.PositiveBigIntegerField(null=True)
    total_tokens = models.PositiveBigIntegerField(null=True)
    cached_input_tokens = models.PositiveBigIntegerField(null=True)
    cache_write_input_tokens = models.PositiveBigIntegerField(null=True)
    reasoning_output_tokens = models.PositiveBigIntegerField(null=True)
    latency_ms = models.PositiveBigIntegerField(null=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    received_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        indexes = [models.Index(fields=['environment', 'created_at'], name='provider_attempt_env_date')]


class ProviderCheckpoint(models.Model):
    """Encrypted successful provider parts for safe reuse after worker retries."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey('core.Account', on_delete=models.CASCADE)
    root_job = models.ForeignKey('core.Job', on_delete=models.CASCADE, related_name='provider_checkpoints')
    draft = models.ForeignKey(GenerationDraft, on_delete=models.CASCADE)
    request_hash = models.CharField(max_length=64)
    stage = models.CharField(max_length=24)
    span_start = models.PositiveIntegerField()
    span_end = models.PositiveIntegerField()
    status = models.CharField(max_length=16, default='pending')
    lease_token = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    encrypted_result = models.BinaryField(default=bytes)
    expires_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['account', 'root_job', 'request_hash'], name='unique_provider_checkpoint')]

class PhotoSearch(models.Model):
    """A stock-photo search result, kept for the 24 hours Pixabay requires.

    Keyed by a hash of the query so the search words themselves are never
    stored. Empty results are cached too: asking again within the day would
    only spend the rate limit on the same answer.
    """
    key=models.CharField(max_length=64,primary_key=True)
    hits=models.JSONField(default=list)
    expires_at=models.DateTimeField(db_index=True)


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
