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
    # The credits an offer carried before weekly limits replaced them; kept on
    # old offers as history, empty on every offer since.
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
    # Who took the money: 'manual' for a card transfer the owner reviewed,
    # 'inpay' for an automatic payment. The 'telegram_stars' rows date from
    # before Stars was removed and stay as history.
    provider=models.CharField(max_length=24,default='telegram_stars')
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
    provider=models.CharField(max_length=24,default='telegram_stars')
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
    # A manual subscription never renews by itself; the customer pays again.
    provider=models.CharField(max_length=24,default='telegram_stars')
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
    """History: the credits a payment granted while plans were sold as credits.
    Nothing writes these any more; a plan is its weekly limits."""
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
    """History: credits already spent when their payment was refunded, from the
    time plans were sold as credits. Nothing writes these any more."""
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
    # The credits a qualified referral once earned, from before invitations
    # earned Plus; empty on every referral since.
    grant=models.OneToOneField('core.UsageGrant',null=True,on_delete=models.PROTECT)
    # Whether this friend counts toward Plus months (apps/commerce/referrals.py).
    # False only on friends counted before invitations earned Plus: they stay
    # in the totals as history and never toward a reward.
    # A database default too: migrations run while the old code still serves,
    # and it creates referrals without this column.
    counts_toward_reward=models.BooleanField(default=True,db_default=True)


class ReferralReward(models.Model):
    """Plus months earned by inviting friends, and the bot message that says so.

    The n-th five counted friends earn n months (30 days each), written as an
    ordinary Plus period (provider 'referral') by apps/commerce/periods.py. One
    row per step, so a step is never rewarded twice. The message is durable
    like PaymentNotice: claimed under a lease, sent once, retried with backoff.
    """
    inviter=models.ForeignKey('core.Account',on_delete=models.PROTECT,related_name='referral_rewards')
    tier=models.PositiveIntegerField()
    invites=models.PositiveIntegerField()
    days=models.PositiveIntegerField()
    period=models.OneToOneField(SubscriptionPeriod,null=True,on_delete=models.PROTECT,related_name='referral_reward')
    created_at=models.DateTimeField(default=timezone.now)
    status=models.CharField(max_length=16,default='pending')
    attempts=models.PositiveIntegerField(default=0)
    next_attempt_at=models.DateTimeField(default=timezone.now)
    lease_until=models.DateTimeField(null=True)
    message_id=models.BigIntegerField(null=True)
    error_code=models.CharField(max_length=64,blank=True)
    delivered_at=models.DateTimeField(null=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['inviter','tier'],name='one_referral_reward_per_tier')]
        indexes=[models.Index(fields=['status','next_attempt_at'],name='referral_reward_due')]

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


class ManualPayment(models.Model):
    """A card transfer to the owner's card, which the owner reviews by hand.

    Nothing here grants a plan. Approval creates the same Invoice, Payment and
    SubscriptionPeriod a Telegram payment does, tagged `manual`, so the plan
    behaves exactly like any other paid plan.
    """
    OPEN=('awaiting','submitted')
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    reference=models.CharField(max_length=12,unique=True)
    account=models.ForeignKey('core.Account',on_delete=models.PROTECT,related_name='manual_payments')
    plan=models.CharField(max_length=12)
    amount=models.PositiveIntegerField()
    # The plan's regular price when the request was opened: a request opened
    # at a discount stays one however the prices move afterwards. Null on
    # requests from before discounts, which were all opened at the regular price.
    regular_amount=models.PositiveIntegerField(null=True)
    currency=models.CharField(max_length=3,default='UZS')
    # The card the customer was told to pay, as it was then: the owner may
    # change cards while a transfer is on its way.
    card=models.JSONField(default=dict)
    status=models.CharField(max_length=16,default='awaiting')
    channel=models.CharField(max_length=8,default='web')
    receipt_key=models.CharField(max_length=200,blank=True)
    receipt_type=models.CharField(max_length=40,blank=True)
    receipt_size=models.PositiveIntegerField(default=0)
    receipt_sha256=models.CharField(max_length=64,blank=True,db_index=True)
    receipt_deleted_at=models.DateTimeField(null=True)
    payer_note=models.CharField(max_length=120,blank=True)
    created_at=models.DateTimeField(default=timezone.now)
    expires_at=models.DateTimeField()
    submitted_at=models.DateTimeField(null=True)
    decided_at=models.DateTimeField(null=True)
    decided_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL)
    decision_note=models.CharField(max_length=500,blank=True)
    payment=models.OneToOneField(Payment,null=True,on_delete=models.PROTECT,related_name='manual')
    class Meta:
        indexes=[models.Index(fields=['status','submitted_at'],name='manual_payment_queue')]
        constraints=[models.UniqueConstraint(fields=['account'],condition=models.Q(status__in=('awaiting','submitted')),name='one_open_manual_payment')]


class Checkout(models.Model):
    """One automatic payment through inPAY, from the page it opens to the plan it buys.

    The amount and the plan are ours, fixed when the customer chose them. The
    row grants nothing by itself: a plan starts only when inPAY's own answer
    says this payment succeeded, for exactly this amount (apps/commerce/checkout.py),
    and then through the same Invoice, Payment and SubscriptionPeriod every paid
    plan is held in, tagged `inpay`.

    `status` is where we last knew it to stand. Only `paid` and `refunded` are
    final: a payment inPAY reports as paid is honoured whatever the row said
    before, since the customer's money is already taken.
    """
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    account=models.ForeignKey('core.Account',on_delete=models.PROTECT,related_name='checkouts')
    plan=models.CharField(max_length=12)
    amount=models.PositiveIntegerField()
    # The plan's regular price when the payment was opened, as ManualPayment keeps it.
    regular_amount=models.PositiveIntegerField(null=True)
    currency=models.CharField(max_length=3,default='UZS')
    provider=models.CharField(max_length=24,default='inpay')
    # Which of inPAY's APIs opened it ('v2' or 'v1'): its status is asked the same way.
    api=models.CharField(max_length=4)
    # False for a payment made with a test key: no money moved, so no plan is granted.
    livemode=models.BooleanField(default=True)
    # inPAY's id for the payment; empty until inPAY has answered.
    provider_id=models.CharField(max_length=64,blank=True)
    checkout_url=models.TextField(blank=True)
    # created (inPAY not asked yet) → pending → paid | failed | cancelled | expired;
    # review: inPAY took a payment that does not match this row; refunded.
    status=models.CharField(max_length=16,default='created')
    failure=models.CharField(max_length=64,blank=True)
    channel=models.CharField(max_length=8,default='web')
    created_at=models.DateTimeField(default=timezone.now)
    expires_at=models.DateTimeField()
    paid_at=models.DateTimeField(null=True)
    # When inPAY was last asked about it, and how many times.
    checked_at=models.DateTimeField(null=True)
    checks=models.PositiveIntegerField(default=0)
    receipt_url=models.TextField(blank=True)
    payment=models.OneToOneField(Payment,null=True,on_delete=models.PROTECT,related_name='checkout')
    class Meta:
        indexes=[models.Index(fields=['status','created_at'],name='checkout_queue'),
                 models.Index(fields=['account','created_at'],name='checkout_account')]
        constraints=[models.UniqueConstraint(fields=['provider','provider_id'],condition=~models.Q(provider_id=''),name='one_checkout_per_provider_id')]


class SavedCard(models.Model):
    """A customer's card saved at inPAY (Avto to'lov) for paying again without a code.

    The card number never reaches us: the customer types it on inPAY's page
    and inPAY keeps it. We hold inPAY's card id, the masked number to show,
    and the mandate inPAY gives as proof of the customer's consent. Only an
    `active` card is ever charged (apps/commerce/autopay.py).
    """
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    account=models.ForeignKey('core.Account',on_delete=models.PROTECT,related_name='saved_cards')
    # Which kassa's Avto to'lov holds it: a card saved through one cannot be charged through another.
    kassa=models.CharField(max_length=8,default='bot')
    customer_ref=models.CharField(max_length=64)
    provider_card_id=models.BigIntegerField(null=True)
    # binding (inPAY's page is open) → active | expired (never finished); removed;
    # removing: taken away here, still to be told to inPAY.
    status=models.CharField(max_length=12,default='binding')
    masked_pan=models.CharField(max_length=32,blank=True)
    expiry=models.CharField(max_length=8,blank=True)
    mandate_id=models.CharField(max_length=64,blank=True)
    # The most the customer agreed to be charged at once, as they set it on inPAY's page.
    consent_max=models.PositiveIntegerField(null=True)
    bind_url=models.TextField(blank=True)
    bind_expires_at=models.DateTimeField(null=True)
    # The plan to pay for, and renew every month, once the card is saved.
    intent=models.CharField(max_length=12,blank=True)
    removed_by=models.CharField(max_length=16,blank=True)
    created_at=models.DateTimeField(default=timezone.now)
    activated_at=models.DateTimeField(null=True)
    removed_at=models.DateTimeField(null=True)
    last_used_at=models.DateTimeField(null=True)
    checked_at=models.DateTimeField(null=True)
    class Meta:
        indexes=[models.Index(fields=['status','created_at'],name='saved_card_queue'),
                 models.Index(fields=['account','status'],name='saved_card_account')]
        constraints=[models.UniqueConstraint(fields=['kassa','provider_card_id'],condition=models.Q(provider_card_id__isnull=False),
                                             name='one_saved_card_per_provider_card')]

    @property
    def last4(self):
        digits=''.join(c for c in self.masked_pan if c.isdigit())
        return digits[-4:] if len(digits)>=4 else ''


class AutoRenewal(models.Model):
    """A customer's plan renewing every month from their saved card.

    `renews_at` is when the paid period ends and the next charge is due. A
    charge that fails is tried again a day and three days later (`next_try_at`,
    `attempts`), then renewal stops and the plan ends as any other would.
    """
    account=models.OneToOneField('core.Account',on_delete=models.CASCADE,related_name='auto_renewal')
    card=models.ForeignKey(SavedCard,on_delete=models.PROTECT,related_name='renewals')
    plan=models.CharField(max_length=12)
    # on → off (the customer or the owner turned it off) | stopped (it could not go on, `stopped_reason`)
    status=models.CharField(max_length=12,default='on')
    renews_at=models.DateTimeField()
    attempts=models.PositiveSmallIntegerField(default=0)
    next_try_at=models.DateTimeField(null=True)
    failure=models.CharField(max_length=64,blank=True)
    stopped_reason=models.CharField(max_length=32,blank=True)
    # The renews_at the customer was last reminded of, so each renewal is announced once.
    reminded_for=models.DateTimeField(null=True)
    created_at=models.DateTimeField(default=timezone.now)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        indexes=[models.Index(fields=['status','renews_at'],name='auto_renewal_due')]


class CardCharge(models.Model):
    """One charge of a saved card: the first month, a renewal, or a one-tap payment.

    Its id is the idempotency key inPAY is given, so a charge whose answer was
    lost is asked again under the same key and never taken twice. A plan is
    granted only from inPAY's answer that the charge succeeded, for exactly
    this amount, through the same Invoice, Payment and SubscriptionPeriod as
    every paid plan, tagged `inpay`.
    """
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    account=models.ForeignKey('core.Account',on_delete=models.PROTECT,related_name='card_charges')
    card=models.ForeignKey(SavedCard,on_delete=models.PROTECT,related_name='charges')
    renewal=models.ForeignKey(AutoRenewal,null=True,on_delete=models.SET_NULL,related_name='charges')
    plan=models.CharField(max_length=12)
    amount=models.PositiveIntegerField()
    regular_amount=models.PositiveIntegerField(null=True)
    currency=models.CharField(max_length=3,default='UZS')
    # first (with turning renewal on) | renewal | one_tap
    purpose=models.CharField(max_length=12)
    # created (inPAY not answered yet) → paid | failed; unknown: asked, answer lost, asked again
    # with the same key; review: inPAY took an amount this row does not describe; refunded.
    status=models.CharField(max_length=12,default='created')
    failure=models.CharField(max_length=64,blank=True)
    provider_charge_id=models.CharField(max_length=64,blank=True)
    provider_ref=models.CharField(max_length=64,blank=True)
    mandate_id=models.CharField(max_length=64,blank=True)
    # Which try of a renewal this is (1–3), and how many times inPAY was asked under its key.
    attempt=models.PositiveSmallIntegerField(default=1)
    tries=models.PositiveSmallIntegerField(default=0)
    payment=models.OneToOneField(Payment,null=True,on_delete=models.PROTECT,related_name='card_charge')
    created_at=models.DateTimeField(default=timezone.now)
    decided_at=models.DateTimeField(null=True)
    class Meta:
        indexes=[models.Index(fields=['status','created_at'],name='card_charge_queue'),
                 models.Index(fields=['account','created_at'],name='card_charge_account')]


class PaymentNotice(models.Model):
    """A bot message about a payment: to the customer, or to the owner.

    About one thing only: a card transfer (`manual`), an automatic payment
    (`checkout`), a saved-card charge (`charge`), or a renewal still to come
    (`renewal`, with `due_for`, the renewal it announces). Durable like
    BotDelivery, so a Telegram hiccup is retried rather than lost, and one row
    per kind so nothing is ever sent twice.
    """
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    manual=models.ForeignKey(ManualPayment,null=True,on_delete=models.CASCADE,related_name='notices')
    checkout=models.ForeignKey(Checkout,null=True,on_delete=models.CASCADE,related_name='notices')
    charge=models.ForeignKey(CardCharge,null=True,on_delete=models.CASCADE,related_name='notices')
    renewal=models.ForeignKey(AutoRenewal,null=True,on_delete=models.CASCADE,related_name='notices')
    due_for=models.DateTimeField(null=True)
    kind=models.CharField(max_length=24)
    status=models.CharField(max_length=16,default='pending')
    attempts=models.PositiveIntegerField(default=0)
    next_attempt_at=models.DateTimeField(default=timezone.now)
    lease_until=models.DateTimeField(null=True)
    message_id=models.BigIntegerField(null=True)
    error_code=models.CharField(max_length=64,blank=True)
    created_at=models.DateTimeField(default=timezone.now)
    delivered_at=models.DateTimeField(null=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['manual','kind'],name='one_payment_notice'),
                     models.UniqueConstraint(fields=['checkout','kind'],name='one_checkout_notice'),
                     models.UniqueConstraint(fields=['charge','kind'],name='one_card_charge_notice'),
                     models.UniqueConstraint(fields=['renewal','kind','due_for'],name='one_renewal_notice')]
        indexes=[models.Index(fields=['status','next_attempt_at'],name='payment_notice_due')]
