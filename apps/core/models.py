import uuid
from django.db import models
from django.db.models import Q
from django.utils import timezone

class Account(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    telegram_user_id = models.BigIntegerField(unique=True, null=True, blank=True)
    email = models.EmailField(max_length=254, unique=True, null=True, blank=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    password_hash = models.CharField(max_length=256, blank=True, db_default='')
    google_sub = models.CharField(max_length=255, unique=True, null=True, blank=True)
    google_email = models.EmailField(max_length=254, blank=True, db_default='')
    auth_version = models.PositiveIntegerField(default=0, db_default=0)
    username = models.CharField(max_length=64, blank=True)
    display_name = models.CharField(max_length=150, blank=True)
    locale = models.CharField(max_length=2, default='en')
    mode = models.CharField(max_length=16, default='general')
    time_zone = models.CharField(max_length=64, default='UTC')
    preferences = models.JSONField(default=dict)
    plan = models.CharField(max_length=12, default='free')
    # A plan assigned by staff is not a purchase and must never enter revenue
    # reporting, so it lives here rather than as a fabricated payment period.
    staff_plan = models.CharField(max_length=12, blank=True, db_default='')
    staff_plan_expires_at = models.DateTimeField(null=True, blank=True)
    is_test = models.BooleanField(default=False)
    first_verified_channel = models.CharField(max_length=16, default='web')
    created_at = models.DateTimeField(default=timezone.now)
    deletion_requested_at = models.DateTimeField(null=True, blank=True)
    def __str__(self): return self.display_name or str(self.id)

class AuthChallenge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    token_hash = models.CharField(max_length=64, unique=True)
    verifier_hash = models.CharField(max_length=64)
    browser_hint = models.CharField(max_length=160)
    account = models.ForeignKey(Account, null=True, on_delete=models.CASCADE)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True)
    approved_at = models.DateTimeField(null=True)
    intent = models.CharField(max_length=8, default='login', db_default='login')
    link_account = models.ForeignKey(Account, null=True, on_delete=models.CASCADE, related_name='+')
    link_auth_version = models.PositiveIntegerField(default=0, db_default=0)
    telegram_user = models.JSONField(default=dict, db_default={})


class EmailChallenge(models.Model):
    """One-use verification codes. Pending signups do not create accounts."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(max_length=254)
    code_hash = models.CharField(max_length=64)
    purpose = models.CharField(max_length=16)
    account = models.ForeignKey(Account, null=True, on_delete=models.CASCADE)
    auth_version = models.PositiveIntegerField(default=0)
    password_hash = models.CharField(max_length=256, blank=True)
    display_name = models.CharField(max_length=150, blank=True)
    locale = models.CharField(max_length=2, default='en')
    eligible = models.BooleanField(default=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True)


class GoogleChallenge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    state_hash = models.CharField(max_length=64, unique=True)
    browser_hash = models.CharField(max_length=64)
    nonce = models.CharField(max_length=128)
    verifier = models.CharField(max_length=128)
    intent = models.CharField(max_length=8)
    account = models.ForeignKey(Account, null=True, on_delete=models.CASCADE)
    auth_version = models.PositiveIntegerField(default=0)
    client_id = models.CharField(max_length=255)
    redirect_uri = models.URLField(max_length=500)
    locale = models.CharField(max_length=2, default='en')
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True)


class AuthRateLimit(models.Model):
    """Shared between API processes; keys contain no raw IP or email."""
    key = models.CharField(max_length=64, primary_key=True)
    count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)

class AuthReceipt(models.Model):
    digest = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(default=timezone.now)


class BotVerification(models.Model):
    """Owner-bound bot abuse checks, independent of language and draft resets."""
    telegram_user_id = models.BigIntegerField(primary_key=True)
    nonce = models.CharField(max_length=32, blank=True, default='')
    challenge = models.JSONField(default=dict)
    pending = models.JSONField(default=dict)
    expires_at = models.DateTimeField(null=True, blank=True)
    verified_until = models.DateTimeField(null=True, blank=True)
    failures = models.PositiveSmallIntegerField(default=0)
    cooldown_until = models.DateTimeField(null=True, blank=True)
    prompt_sent_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

class UsageGrant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='usage_grants')
    meter = models.CharField(max_length=24)
    source = models.CharField(max_length=16, default='included')
    source_id = models.CharField(max_length=160, unique=True)
    quantity = models.PositiveIntegerField()
    consumed = models.PositiveIntegerField(default=0)
    reserved = models.PositiveIntegerField(default=0)
    valid_from = models.DateTimeField()
    expires_at = models.DateTimeField(null=True)
    class Meta:
        constraints = [models.CheckConstraint(condition=Q(quantity__gte=models.F('consumed') + models.F('reserved')), name='grant_no_overspend')]

class FileAsset(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='files')
    name = models.CharField(max_length=255)
    object_key = models.CharField(max_length=180, unique=True)
    mime_type = models.CharField(max_length=100)
    sha256 = models.CharField(max_length=64)
    size_bytes = models.PositiveBigIntegerField()
    page_count = models.PositiveIntegerField()
    state = models.CharField(max_length=16, default='ready')
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()

class Quote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    feature_id = models.CharField(max_length=100)
    parameters = models.JSONField(default=dict)
    input_ids = models.JSONField(default=list)
    input_fingerprints = models.JSONField(default=list)
    secret_id = models.UUIDField(null=True)
    meters = models.JSONField(default=dict)
    policy = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()

class Job(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='jobs')
    quote = models.OneToOneField(Quote, on_delete=models.PROTECT)
    feature_id = models.CharField(max_length=100)
    parameters = models.JSONField(default=dict)
    input_ids = models.JSONField(default=list)
    policy = models.JSONField(default=dict)
    meters = models.JSONField(default=dict)
    settled_meters = models.JSONField(default=dict)
    idempotency_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=24, default='queued')
    origin_channel = models.CharField(max_length=16, default='web')
    error_code = models.CharField(max_length=64, blank=True)
    warnings = models.JSONField(default=list)
    created_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True)
    completed_at = models.DateTimeField(null=True)
    lease_expires_at = models.DateTimeField(null=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    engine = models.CharField(max_length=120, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['account', 'idempotency_key'], name='job_account_idempotency')]

class Reservation(models.Model):
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='reservations')
    grant = models.ForeignKey(UsageGrant, on_delete=models.PROTECT)
    meter = models.CharField(max_length=24)
    amount = models.PositiveIntegerField()
    settled = models.BooleanField(default=False)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['job', 'grant'], name='one_reservation_per_grant')]

class UsageLedger(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    job = models.ForeignKey(Job, on_delete=models.PROTECT)
    grant = models.ForeignKey(UsageGrant, on_delete=models.PROTECT)
    meter = models.CharField(max_length=24)
    kind = models.CharField(max_length=16)
    amount = models.PositiveIntegerField()
    created_at = models.DateTimeField(default=timezone.now)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['job', 'grant', 'kind'], name='one_ledger_transition')]

class Artifact(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='artifacts')
    file = models.OneToOneField(FileAsset, on_delete=models.CASCADE)
    role = models.CharField(max_length=24, default='user_document')

class OutboxEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(Job, on_delete=models.CASCADE)
    topic = models.CharField(max_length=32, default='job.execute')
    created_at = models.DateTimeField(default=timezone.now)
    delivered_at = models.DateTimeField(null=True)
    published_at = models.DateTimeField(null=True)
    publish_lease_until = models.DateTimeField(null=True)
    publish_attempts = models.PositiveIntegerField(default=0, db_default=0)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['job', 'topic'], name='outbox_job_topic')]

class AnalyticsEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, null=True, on_delete=models.SET_NULL)
    event_type = models.CharField(max_length=64)
    feature_id = models.CharField(max_length=100, blank=True)
    job = models.ForeignKey(Job, null=True, on_delete=models.SET_NULL)
    channel = models.CharField(max_length=16, default='web')
    locale = models.CharField(max_length=2, default='en')
    plan_at_event = models.CharField(max_length=12, default='free')
    environment = models.CharField(max_length=16, default='development')
    properties = models.JSONField(default=dict)
    occurred_at = models.DateTimeField(default=timezone.now)

class SupportTicket(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='support_tickets')
    job = models.ForeignKey(Job, null=True, blank=True, on_delete=models.SET_NULL)
    subject = models.CharField(max_length=160)
    message = models.TextField()
    category = models.CharField(max_length=24, default='general')
    status = models.CharField(max_length=16, default='open')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

class BotDraft(models.Model):
    parameters = models.JSONField(default=dict)
    version = models.PositiveIntegerField(default=1)
    account = models.OneToOneField(Account, on_delete=models.CASCADE)
    feature_id = models.CharField(max_length=100, default='pdf.merge')
    input_ids = models.JSONField(default=list)
    quote = models.ForeignKey(Quote, null=True, on_delete=models.SET_NULL)
    state = models.CharField(max_length=24, default='collecting')
    updated_at = models.DateTimeField(auto_now=True)

class BotConversation(models.Model):
    """Telegram UI state without prematurely allocating a customer account.

    Email/Google customers can enter through a linking deep link before their
    Telegram identity is attached to their existing Account.
    """
    telegram_user_id = models.BigIntegerField(primary_key=True)
    locale = models.CharField(max_length=2, blank=True, default='')
    language_selected_at = models.DateTimeField(null=True, blank=True)
    language_nonce = models.CharField(max_length=32, blank=True, default='')
    language_expires_at = models.DateTimeField(null=True, blank=True)
    pending = models.JSONField(default=dict)
    state = models.CharField(max_length=32, blank=True, default='')
    prompt = models.JSONField(default=dict)
    # The generation review on screen — {draft_id, chat_id, message_id, local} —
    # so a change made in the Mini App can redraw it in the chat.
    review = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

class BotCallback(models.Model):
    token = models.CharField(max_length=40, primary_key=True)
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    action = models.CharField(max_length=100)
    payload = models.JSONField(default=dict)
    expires_at = models.DateTimeField()


class BotJobNotice(models.Model):
    """Durable terminal-status outbox; populated only by new bot settlements."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField(Job, on_delete=models.CASCADE, related_name='bot_notice')
    status = models.CharField(max_length=16, default='pending')
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    lease_until = models.DateTimeField(null=True)
    message_id = models.BigIntegerField(null=True)
    error_code = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    delivered_at = models.DateTimeField(null=True)

    class Meta:
        indexes = [models.Index(fields=['status', 'next_attempt_at'], name='bot_notice_due')]

class WebhookReceipt(models.Model):
    update_id = models.BigIntegerField(unique=True)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)
    processed_at = models.DateTimeField(null=True)

class SecretHandle(models.Model):
    """Short-lived ciphertext only; never expose values through admin/API/history."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    asset = models.ForeignKey(FileAsset, null=True, on_delete=models.CASCADE)
    job = models.OneToOneField(Job, null=True, on_delete=models.CASCADE)
    ciphertext = models.BinaryField()
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()

class BotInputReceipt(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    chat_id = models.BigIntegerField()
    message_id = models.BigIntegerField()
    asset = models.ForeignKey(FileAsset, on_delete=models.CASCADE)
    created_at = models.DateTimeField(default=timezone.now)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['account','chat_id','message_id'],name='one_bot_input_receipt')]

class PagePreview(models.Model):
    asset = models.ForeignKey(FileAsset, on_delete=models.CASCADE, related_name='page_previews')
    page = models.PositiveIntegerField()
    file = models.OneToOneField(FileAsset, on_delete=models.CASCADE, related_name='preview_for')
    class Meta:
        constraints = [models.UniqueConstraint(fields=['asset','page'],name='one_preview_per_page')]


class ChannelMembership(models.Model):
    """Whether a customer has joined a required Telegram channel, as last seen.

    Kept for a few hours when they have, for a minute when they haven't, so
    every request does not become a call to Telegram and "I've joined" is
    believed almost at once.
    """
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='channel_memberships')
    chat = models.CharField(max_length=64)
    is_member = models.BooleanField()
    checked_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['account', 'chat'], name='one_channel_membership')]


class StoredObject(models.Model):
    """One file the platform keeps, by its key.

    With object storage connected, the bucket is where the file lives and this
    row says whether it has arrived there (`remote`). The shared volume keeps a
    working copy only while a task, preview or download needs it. Other records
    (a FileAsset, a receipt, an AI review copy) refer to the file by this key.
    """
    key = models.CharField(max_length=500, primary_key=True)
    size = models.PositiveBigIntegerField(default=0)
    content_type = models.CharField(max_length=120, blank=True, default='')
    remote = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    uploaded_at = models.DateTimeField(null=True, blank=True)
    used_at = models.DateTimeField(default=timezone.now, db_index=True)


class StaffAlert(models.Model):
    """A Telegram message to the owner about the platform itself (file storage
    stopped working, and when it recovers). Durable like the other outboxes:
    retried when Telegram is unavailable, sent once."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=40)
    text = models.TextField()
    status = models.CharField(max_length=16, default='pending')
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    error_code = models.CharField(max_length=64, blank=True, default='')
    created_at = models.DateTimeField(default=timezone.now)
    delivered_at = models.DateTimeField(null=True, blank=True)
