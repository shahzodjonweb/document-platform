import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone

class OfferVersion(models.Model):
    id=models.CharField(primary_key=True,max_length=80)
    offer_id=models.CharField(max_length=30)
    version=models.CharField(max_length=32)
    kind=models.CharField(max_length=16)
    plan=models.CharField(max_length=12,blank=True)
    name=models.CharField(max_length=80)
    price_xtr=models.PositiveIntegerField(null=True)
    period_seconds=models.PositiveIntegerField(null=True)
    quantities=models.JSONField(default=dict)
    sandbox=models.BooleanField(default=True)
    enabled=models.BooleanField(default=False)
    created_at=models.DateTimeField(default=timezone.now)

class Invoice(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    account=models.ForeignKey('core.Account',on_delete=models.PROTECT)
    offer=models.ForeignKey(OfferVersion,on_delete=models.PROTECT)
    snapshot=models.JSONField(default=dict)
    amount_xtr=models.PositiveIntegerField()
    currency=models.CharField(max_length=3,default='XTR')
    status=models.CharField(max_length=16,default='created')
    idempotency_key=models.CharField(max_length=128)
    request_hash=models.CharField(max_length=64)
    payload_hash=models.CharField(max_length=64)
    invoice_url=models.TextField(blank=True)
    sandbox=models.BooleanField(default=True)
    created_at=models.DateTimeField(default=timezone.now)
    expires_at=models.DateTimeField()
    paid_at=models.DateTimeField(null=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['account','idempotency_key'],name='one_invoice_request')]

class Payment(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    account=models.ForeignKey('core.Account',on_delete=models.PROTECT)
    invoice=models.ForeignKey(Invoice,on_delete=models.PROTECT,related_name='payments')
    provider_charge_id=models.CharField(max_length=200,unique=True)
    provider_payment_charge_id=models.CharField(max_length=200,blank=True)
    amount_xtr=models.PositiveIntegerField()
    currency=models.CharField(max_length=3,default='XTR')
    kind=models.CharField(max_length=16)
    plan=models.CharField(max_length=12,blank=True)
    is_renewal=models.BooleanField(default=False)
    sandbox=models.BooleanField(default=True)
    occurred_at=models.DateTimeField(default=timezone.now)
    received_at=models.DateTimeField(default=timezone.now)

class Subscription(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    account=models.OneToOneField('core.Account',on_delete=models.PROTECT,related_name='subscription')
    invoice=models.ForeignKey(Invoice,on_delete=models.PROTECT)
    offer=models.ForeignKey(OfferVersion,on_delete=models.PROTECT)
    plan=models.CharField(max_length=12)
    status=models.CharField(max_length=24,default='active')
    renewal_enabled=models.BooleanField(default=True)
    first_charge_id=models.CharField(max_length=200)
    current_period_end=models.DateTimeField()
    scheduled_plan=models.CharField(max_length=12,blank=True)
    scheduled_at=models.DateTimeField(null=True)
    sandbox=models.BooleanField(default=True)
    created_at=models.DateTimeField(default=timezone.now)
    updated_at=models.DateTimeField(auto_now=True)

class SubscriptionPeriod(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    subscription=models.ForeignKey(Subscription,on_delete=models.PROTECT,related_name='periods')
    payment=models.OneToOneField(Payment,on_delete=models.PROTECT,related_name='period')
    account=models.ForeignKey('core.Account',on_delete=models.PROTECT)
    plan=models.CharField(max_length=12)
    starts_at=models.DateTimeField()
    ends_at=models.DateTimeField()
    revoked_at=models.DateTimeField(null=True)
    sandbox=models.BooleanField(default=True)

class PaymentGrant(models.Model):
    payment=models.ForeignKey(Payment,on_delete=models.PROTECT,related_name='grant_links')
    grant=models.OneToOneField('core.UsageGrant',on_delete=models.PROTECT,related_name='payment_source')
    revoked_at=models.DateTimeField(null=True)

class Refund(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    payment=models.OneToOneField(Payment,on_delete=models.PROTECT,related_name='refund')
    amount_xtr=models.PositiveIntegerField()
    status=models.CharField(max_length=16,default='pending')
    reason=models.CharField(max_length=500)
    requested_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL)
    created_at=models.DateTimeField(default=timezone.now)
    confirmed_at=models.DateTimeField(null=True)
    error_code=models.CharField(max_length=64,blank=True)

class BalanceAdjustment(models.Model):
    account=models.ForeignKey('core.Account',on_delete=models.PROTECT)
    refund=models.ForeignKey(Refund,on_delete=models.PROTECT)
    meter=models.CharField(max_length=24)
    consumed_units=models.PositiveIntegerField()
    reserved_units=models.PositiveIntegerField()
    reason=models.CharField(max_length=100,default='refunded_grant_already_used')
    status=models.CharField(max_length=16,default='review')
    created_at=models.DateTimeField(default=timezone.now)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['refund','meter'],name='one_refund_adjustment')]

class CommerceAction(models.Model):
    account=models.ForeignKey('core.Account',on_delete=models.PROTECT)
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL)
    action=models.CharField(max_length=48)
    target=models.CharField(max_length=100)
    reason=models.CharField(max_length=500,blank=True)
    metadata=models.JSONField(default=dict)
    created_at=models.DateTimeField(default=timezone.now)

class ReconciliationRun(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    sandbox=models.BooleanField(default=False)
    started_at=models.DateTimeField(default=timezone.now)
    completed_at=models.DateTimeField(null=True)
    checked=models.PositiveIntegerField(default=0)
    matched=models.PositiveIntegerField(default=0)
    issues=models.PositiveIntegerField(default=0)
    next_offset=models.PositiveIntegerField(default=0)

class ReconciliationIssue(models.Model):
    fingerprint=models.CharField(max_length=64,unique=True)
    charge_id=models.CharField(max_length=200)
    kind=models.CharField(max_length=64)
    amount_xtr=models.PositiveIntegerField(default=0)
    invoice=models.ForeignKey(Invoice,null=True,on_delete=models.PROTECT)
    status=models.CharField(max_length=16,default='open')
    occurred_at=models.DateTimeField(default=timezone.now)
    created_at=models.DateTimeField(default=timezone.now)

class ReferralCode(models.Model):
    account=models.OneToOneField('core.Account',on_delete=models.CASCADE)
    code=models.CharField(max_length=24,unique=True)

class Referral(models.Model):
    inviter=models.ForeignKey('core.Account',on_delete=models.PROTECT,related_name='referrals_sent')
    invitee=models.OneToOneField('core.Account',on_delete=models.PROTECT,related_name='referral_received')
    status=models.CharField(max_length=16,default='pending')
    created_at=models.DateTimeField(default=timezone.now)
    qualified_at=models.DateTimeField(null=True)
    grant=models.OneToOneField('core.UsageGrant',null=True,on_delete=models.PROTECT)

class SupportMessage(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    ticket=models.ForeignKey('core.SupportTicket',on_delete=models.CASCADE,related_name='messages')
    sender_account=models.ForeignKey('core.Account',null=True,on_delete=models.SET_NULL)
    sender_staff=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL)
    body=models.TextField()
    created_at=models.DateTimeField(default=timezone.now)

class BotDelivery(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    account=models.ForeignKey('core.Account',on_delete=models.PROTECT)
    artifact=models.ForeignKey('core.Artifact',on_delete=models.PROTECT)
    idempotency_key=models.CharField(max_length=128)
    status=models.CharField(max_length=16,default='pending')
    attempts=models.PositiveIntegerField(default=0)
    next_attempt_at=models.DateTimeField(default=timezone.now)
    lease_until=models.DateTimeField(null=True)
    message_id=models.BigIntegerField(null=True)
    error_code=models.CharField(max_length=64,blank=True)
    created_at=models.DateTimeField(default=timezone.now)
    delivered_at=models.DateTimeField(null=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['account','idempotency_key'],name='one_bot_delivery_request')]

class LocalBotMessage(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    account=models.ForeignKey('core.Account',on_delete=models.CASCADE)
    direction=models.CharField(max_length=8)
    text=models.TextField(blank=True)
    buttons=models.JSONField(default=list)
    asset=models.ForeignKey('core.FileAsset',null=True,on_delete=models.SET_NULL)
    telegram_message_id=models.PositiveIntegerField()
    created_at=models.DateTimeField(default=timezone.now)
