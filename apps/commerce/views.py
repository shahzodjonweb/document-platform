import json
from functools import wraps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.utils import timezone
from apps.core.views import current_account,body,throttle
from apps.core.errors import DomainError,error_data
from apps.core.models import SupportTicket,Artifact
from .models import Invoice,Payment,Referral,SupportMessage,BotDelivery
from . import services
from .serializers import invoice_data,payment_data,subscription_data,refund_data

MESSAGES={
'en':{'sandbox_disabled':'This local payment simulator is available only for test accounts.','payment_amount_mismatch':'The payment amount does not match the invoice.','invalid_invoice':'This invoice could not be verified.','invoice_expired':'This invoice has expired. Create a new one.','subscription_already_active':'You already have active paid access. Schedule a change for the next period.','subscription_invoice_pending':'Finish or cancel the pending subscription invoice first.','subscription_not_active':'There is no active subscription to change.','renewal_disabled':'Renewal is currently disabled.','invalid_plan_change':'Choose a different plan for the next period.','payment_provider_unavailable':'The payment provider could not confirm this action. Please try again later.','audit_reason_required':'Enter a short reason for this action.','invalid_referral':'This referral code is not valid for your account.','referral_already_claimed':'Your account already has a referral.','referral_window_closed':'Referral codes can be added during the first seven days.','permission_denied':'You do not have permission to perform this action.'},
'uz':{'sandbox_disabled':'Mahalliy to‘lov simulyatori faqat sinov hisoblari uchun mavjud.','payment_amount_mismatch':'To‘lov summasi hisob-fakturaga mos emas.','invalid_invoice':'Hisob-fakturani tekshirib bo‘lmadi.','invoice_expired':'Hisob-faktura muddati tugadi. Yangisini yarating.','subscription_already_active':'Pulli obunangiz faol. Tarif almashishni keyingi davrga rejalashtiring.','subscription_invoice_pending':'Avval kutilayotgan obuna hisob-fakturasini yakunlang yoki bekor qiling.','subscription_not_active':'O‘zgartirish uchun faol obuna mavjud emas.','renewal_disabled':'Avtomatik uzaytirish o‘chirilgan.','invalid_plan_change':'Keyingi davr uchun boshqa tarifni tanlang.','payment_provider_unavailable':'To‘lov provayderi amalni tasdiqlamadi. Keyinroq qayta urining.','audit_reason_required':'Amal uchun qisqa sabab kiriting.','invalid_referral':'Bu tavsiya kodi hisobingiz uchun yaroqsiz.','referral_already_claimed':'Hisobingizda tavsiya allaqachon mavjud.','referral_window_closed':'Tavsiya kodini dastlabki yetti kunda qo‘shish mumkin.','permission_denied':'Bu amalni bajarishga ruxsatingiz yo‘q.'},
'ru':{'sandbox_disabled':'Локальный симулятор оплаты доступен только тестовым аккаунтам.','payment_amount_mismatch':'Сумма платежа не соответствует счёту.','invalid_invoice':'Не удалось проверить этот счёт.','invoice_expired':'Срок счёта истёк. Создайте новый.','subscription_already_active':'У вас уже есть платный доступ. Запланируйте смену на следующий период.','subscription_invoice_pending':'Сначала оплатите или отмените ожидающий счёт подписки.','subscription_not_active':'Нет активной подписки для изменения.','renewal_disabled':'Продление сейчас отключено.','invalid_plan_change':'Выберите другой план на следующий период.','payment_provider_unavailable':'Провайдер платежей не подтвердил действие. Повторите позже.','audit_reason_required':'Укажите краткую причину действия.','invalid_referral':'Этот реферальный код недействителен для вашего аккаунта.','referral_already_claimed':'Для аккаунта уже указан пригласивший пользователь.','referral_window_closed':'Код можно добавить в первые семь дней.','permission_denied':'У вас нет разрешения на это действие.'}}


def endpoint(methods=('GET',)):
    def decorate(fn):
        @wraps(fn)
        def wrapped(request,*args,**kwargs):
            account=None
            try:
                if request.method not in methods: raise DomainError('method_not_allowed',405)
                account=current_account(request)
                if account is None: raise DomainError('authentication_required',401)
                services.refresh_account_entitlement(account);request.account=account
                value=fn(request,*args,**kwargs)
                return value if hasattr(value,'status_code') else JsonResponse(value)
            except (ValueError,TypeError,KeyError,ValidationError):
                exc=DomainError('invalid_request')
            except DomainError as error: exc=error
            locale=account.locale if account else 'en';data=error_data(exc,locale,getattr(request,'request_id',''))
            data['message']=MESSAGES.get(locale,MESSAGES['en']).get(exc.code,data['message'])
            return JsonResponse({'error':data},status=exc.status)
        return wrapped
    return decorate

@endpoint()
def offers(request):
    rows=services.available_offers(request.account)
    return {'offers':[services.offer_data(offer) for offer in rows],'sandbox':services.sandbox_enabled(request.account),'checkout_enabled':bool(rows),'currency':'XTR','billing_mode':'sandbox' if services.sandbox_enabled(request.account) else 'live' if rows else 'disabled'}

@endpoint(('GET','POST'))
def invoices(request):
    if request.method=='GET': return {'results':[invoice_data(value) for value in Invoice.objects.filter(account=request.account).select_related('offer').order_by('-created_at')[:100]]}
    throttle(request,'invoices',20)
    invoice,created=services.create_invoice(request.account,body(request).get('offer_id'),request.headers.get('Idempotency-Key',''))
    invoice=services.present_invoice(invoice)
    return JsonResponse(invoice_data(invoice),status=201 if created else 200)

@endpoint(('GET','DELETE'))
def invoice_detail(request,invoice_id):
    if request.method=='DELETE': return invoice_data(services.cancel_invoice(request.account,invoice_id))
    invoice=Invoice.objects.select_related('offer').filter(pk=invoice_id,account=request.account).first()
    if not invoice: raise DomainError('not_found',404)
    return invoice_data(invoice)

@endpoint(('POST',))
def sandbox_pay(request,invoice_id):
    payment,created=services.sandbox_pay(request.account,invoice_id)
    request.account.refresh_from_db()
    return {'payment':payment_data(payment),'invoice':invoice_data(payment.invoice),'subscription':subscription_data(request.account)['subscription'],'plan':request.account.plan,'sandbox':True,'created':created}

@endpoint()
def subscription(request): return subscription_data(request.account)

@endpoint(('POST',))
def cancel_renewal(request):
    services.set_renewal(request.account,False);return subscription_data(request.account)

@endpoint(('POST',))
def resume_renewal(request):
    services.set_renewal(request.account,True);return subscription_data(request.account)

@endpoint(('POST',))
def schedule_change(request):
    services.schedule_plan_change(request.account,body(request).get('plan'));return subscription_data(request.account)

@endpoint(('POST',))
def sandbox_renew(request):
    payment,created=services.sandbox_renew(request.account,request.headers.get('Idempotency-Key',''))
    return {'payment':payment_data(payment),'subscription':subscription_data(request.account)['subscription'],'sandbox':True,'created':created}

@endpoint()
def transactions(request):
    return {'results':[payment_data(payment) for payment in Payment.objects.filter(account=request.account).order_by('-occurred_at')[:100]]}

@endpoint(('POST',))
def sandbox_refund(request,payment_id):
    services.require_sandbox(request.account)
    payment=Payment.objects.select_related('account').filter(pk=payment_id,account=request.account,sandbox=True).first()
    if not payment: raise DomainError('not_found',404)
    refund=services.refund_payment(payment,body(request).get('reason','Local sandbox refund'),sandbox_account=request.account)
    return refund_data(refund)

@endpoint(('POST',))
def refund_request(request,payment_id):
    payment=Payment.objects.filter(pk=payment_id,account=request.account).first()
    if not payment: raise DomainError('not_found',404)
    reason=body(request).get('reason','')
    if not isinstance(reason,str) or not 3<=len(reason)<=4000: raise DomainError('invalid_support_ticket')
    ticket=SupportTicket.objects.create(account=request.account,subject='Payment refund request',message=reason,category='payments')
    services.CommerceAction.objects.create(account=request.account,action='refund.requested',target=str(payment.id),metadata={'ticket_id':str(ticket.id)})
    return {'ticket_id':str(ticket.id),'status':'review_requested'}

@endpoint(('GET','POST'))
def referrals(request):
    if request.method=='POST':
        referral=services.claim_referral(request.account,body(request).get('code',''))
        return {'id':referral.id,'status':referral.status}
    services.qualify_referrals(request.account)
    code=services.referral_code(request.account)
    sent=Referral.objects.filter(inviter=request.account)
    qualified=sent.filter(status='qualified').count()
    from .providers import telegram_config
    username=telegram_config().get('username')
    return {'code':code.code,'url':f'https://t.me/{username}?start=ref_{code.code}' if username else None,'rewards_count':qualified,'pending_count':sent.filter(status='pending').count(),'awarded_credits':qualified*10,'monthly_cap':5,'expires_in_days':30,'qualification':'first_successful_task','sandbox':request.account.is_test}

@endpoint(('GET','POST'))
def support_messages(request,ticket_id):
    ticket=SupportTicket.objects.filter(pk=ticket_id,account=request.account).first()
    if not ticket: raise DomainError('not_found',404)
    if request.method=='POST': services.add_support_message(request.account,ticket_id,body(request).get('message',''))
    rows=[{'id':str(ticket.id),'message':ticket.message,'sender':'customer','created_at':ticket.created_at}]
    rows.extend({'id':str(m.id),'message':m.body,'sender':'staff' if m.sender_staff_id else 'customer','created_at':m.created_at} for m in ticket.messages.order_by('created_at'))
    return {'ticket_id':str(ticket.id),'status':ticket.status,'messages':rows}

@endpoint(('POST',))
def deliver_artifact(request,artifact_id):
    artifact=Artifact.objects.filter(pk=artifact_id,account=request.account).first()
    if not artifact: raise DomainError('not_found',404)
    key=request.headers.get('Idempotency-Key','')
    if not 8<=len(key)<=128: raise DomainError('idempotency_key_required')
    if artifact.file.state!='ready' or artifact.file.expires_at<=timezone.now(): raise DomainError('file_expired',410)
    delivery,created=BotDelivery.objects.get_or_create(account=request.account,idempotency_key=key,defaults={'artifact':artifact})
    if delivery.artifact_id!=artifact.id: raise DomainError('idempotency_conflict',409)
    if request.account.is_test:
        from telegram.local import deliver_local
        delivery=deliver_local(request.account,delivery)
    return JsonResponse({'id':str(delivery.id),'status':delivery.status,'attempts':delivery.attempts},status=201 if created else 200)

@endpoint(('GET','POST','DELETE'))
def local_telegram(request):
    from telegram.local import history,dispatch_local
    from .models import LocalBotMessage
    services.require_sandbox(request.account)
    if request.method=='DELETE':
        LocalBotMessage.objects.filter(account=request.account).delete()
        return history(request.account)
    if request.method=='GET': return history(request.account)
    throttle(request,'telegram_local',60)
    if request.FILES.get('file'): return dispatch_local(request.account,uploaded=request.FILES['file'])
    data=body(request)
    return dispatch_local(request.account,text=data.get('text'),callback_data=data.get('callback_data'))
