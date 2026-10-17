from django.utils import timezone
from .models import Subscription,Refund
from .services import active_period,effective_plan,sandbox_enabled


def payment_data(payment):
    """A payment as its customer sees it: `amount` and `refunded` are in `currency`, so'm for a card transfer."""
    refund=Refund.objects.filter(payment=payment).first()
    refunded=refund.amount_xtr if refund and refund.status=='confirmed' else 0
    return {'id':str(payment.id),'invoice_id':str(payment.invoice_id),'kind':payment.kind,'plan':payment.plan or None,'amount':payment.amount_xtr,'currency':payment.currency,'sandbox':payment.sandbox,'occurred_at':payment.occurred_at,'is_renewal':payment.is_renewal,'refunded':refunded,'status':'refunded' if refunded else 'paid','refund_status':refund.status if refund else None,'provider':payment.provider}


def subscription_data(account):
    subscription=Subscription.objects.filter(account=account).first()
    period=active_period(account)
    result=None
    if subscription:
        status=('active' if subscription.renewal_enabled else 'cancel_at_period_end') if period else ('expired' if subscription.current_period_end<=timezone.now() else subscription.status)
        result={'id':str(subscription.id),'plan':subscription.plan,'status':status,'renewal_enabled':subscription.renewal_enabled,'current_period_end':subscription.current_period_end,'active_until':period.ends_at if period else None,'scheduled_plan':subscription.scheduled_plan or None,'scheduled_at':subscription.scheduled_at,'requires_new_checkout':bool(subscription.scheduled_plan and subscription.scheduled_plan!='free'),'sandbox':subscription.sandbox,'provider':subscription.provider}
    return {'plan':effective_plan(account),'subscription':result,'sandbox':sandbox_enabled(account)}


def manual_payment_data(payment):
    """A card transfer as its customer sees it.

    The full card number is shown only while the transfer is still to be made
    or reviewed; afterwards the last four digits are enough. The owner's note on
    an approval is internal; a rejection's reason is for the customer.
    """
    if payment is None: return None
    card=payment.card or {}
    open_=payment.status in ('awaiting','submitted')
    number=str(card.get('number') or '')
    period=getattr(payment.payment,'period',None) if payment.payment_id else None
    return {'id':str(payment.id),'reference':payment.reference,'plan':payment.plan,'amount':payment.amount,'currency':payment.currency,
            'status':payment.status,'channel':payment.channel,
            'card':{'number':number if open_ else None,'last4':number[-4:],'holder':card.get('holder',''),'label':card.get('label','')},
            'receipt_received':bool(payment.receipt_key or payment.receipt_deleted_at),'payer_note':payment.payer_note,
            'created_at':payment.created_at,'expires_at':payment.expires_at,'submitted_at':payment.submitted_at,'decided_at':payment.decided_at,
            'rejection_reason':payment.decision_note if payment.status=='rejected' else None,
            'starts_at':period.starts_at if period else None,'active_until':period.ends_at if period else None}
