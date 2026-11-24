import json
from functools import wraps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.utils import timezone
from apps.core.views import current_account,body,throttle
from apps.core.errors import DomainError,error_data
from apps.core.models import Artifact
from .models import Payment,BotDelivery
from . import services
from django.views.decorators.csrf import csrf_exempt
from apps.core.views import api
from .serializers import payment_data,subscription_data,manual_payment_data,checkout_data
from . import manual
from . import checkout

MESSAGES={
'en':{'checkout_unavailable':'Couldn’t open the payment page. Please try again in a minute.','checkout_disabled':'Payments aren’t available right now.','invalid_plan':'Choose Plus or Premium.','manual_payment_pending':'Your previous payment is being reviewed. Wait for it, or cancel it first.','manual_payment_closed':'This payment is already closed. Start a new one.','manual_payment_expired':'This payment expired after two days without a receipt. Start a new one.','invalid_receipt':'Send the receipt as a photo or screenshot (JPG or PNG) or a PDF.','receipt_too_large':'The receipt must be smaller than 10 MB.','manual_payment_unavailable':'Couldn’t start the payment. Please try again.','rate_limited':'Too many attempts. Please wait a little and try again.','sandbox_disabled':'This local payment simulator is available only for test accounts.','audit_reason_required':'Enter a short reason for this action.','invalid_referral':'This referral code is not valid for your account.','referral_already_claimed':'Your account already has a referral.','referral_window_closed':'Referral codes can be added during the first seven days.','permission_denied':'You do not have permission to perform this action.'},
'uz':{'checkout_unavailable':'To‘lov sahifasini ochib bo‘lmadi. Bir daqiqadan so‘ng qayta urinib ko‘ring.','checkout_disabled':'To‘lov hozircha mavjud emas.','invalid_plan':'Plus yoki Premium tarifini tanlang.','manual_payment_pending':'Oldingi to‘lovingiz tekshirilmoqda. Natijani kuting yoki avval uni bekor qiling.','manual_payment_closed':'Bu to‘lov yopilgan. Yangisini boshlang.','manual_payment_expired':'Kvitansiya yuborilmagani uchun to‘lov ikki kundan keyin bekor bo‘ldi. Yangisini boshlang.','invalid_receipt':'Kvitansiyani rasm yoki skrinshot (JPG yoki PNG) yoxud PDF ko‘rinishida yuboring.','receipt_too_large':'Kvitansiya hajmi 10 MB dan kichik bo‘lishi kerak.','manual_payment_unavailable':'To‘lovni boshlab bo‘lmadi. Qayta urinib ko‘ring.','rate_limited':'Urinishlar juda ko‘p. Biroz kutib, qayta urinib ko‘ring.','sandbox_disabled':'Mahalliy to‘lov simulyatori faqat sinov hisoblari uchun mavjud.','audit_reason_required':'Amal uchun qisqa sabab kiriting.','invalid_referral':'Bu tavsiya kodi hisobingiz uchun yaroqsiz.','referral_already_claimed':'Hisobingizda tavsiya allaqachon mavjud.','referral_window_closed':'Tavsiya kodini dastlabki yetti kunda qo‘shish mumkin.','permission_denied':'Bu amalni bajarishga ruxsatingiz yo‘q.'},
'ru':{'checkout_unavailable':'Не удалось открыть страницу оплаты. Попробуйте ещё раз через минуту.','checkout_disabled':'Оплата сейчас недоступна.','invalid_plan':'Выберите Plus или Premium.','manual_payment_pending':'Предыдущий платёж проверяется. Дождитесь решения или сначала отмените его.','manual_payment_closed':'Этот платёж уже закрыт. Начните новый.','manual_payment_expired':'Платёж отменён: квитанция не пришла за два дня. Начните новый.','invalid_receipt':'Отправьте квитанцию фото или скриншотом (JPG или PNG) либо PDF-файлом.','receipt_too_large':'Квитанция должна быть меньше 10 МБ.','manual_payment_unavailable':'Не удалось начать оплату. Попробуйте ещё раз.','rate_limited':'Слишком много попыток. Подождите немного и повторите.','sandbox_disabled':'Локальный симулятор оплаты доступен только тестовым аккаунтам.','audit_reason_required':'Укажите краткую причину действия.','invalid_referral':'Этот реферальный код недействителен для вашего аккаунта.','referral_already_claimed':'Для аккаунта уже указан пригласивший пользователь.','referral_window_closed':'Код можно добавить в первые семь дней.','permission_denied':'У вас нет разрешения на это действие.'}}


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
def subscription(request): return subscription_data(request.account)

@endpoint()
def transactions(request):
    # Plus months earned by inviting friends cost nothing; the invitations page lists them.
    return {'results':[payment_data(payment) for payment in Payment.objects.filter(account=request.account).exclude(provider='referral').order_by('-occurred_at')[:100]]}

@endpoint(('GET','POST'))
def referrals(request):
    if request.method=='POST':
        referral=services.claim_referral(request.account,body(request).get('code',''))
        return {'id':referral.id,'status':referral.status}
    from .referrals import progress
    services.qualify_referrals(request.account)
    code=services.referral_code(request.account)
    state=progress(request.account)
    from .providers import telegram_config
    username=telegram_config().get('username')
    return {'code':code.code,'url':f'https://t.me/{username}?start=ref_{code.code}' if username else None,
            'rewards_count':state['qualified_total'],'pending_count':state['pending'],'monthly_cap':state['monthly_cap'],
            'qualification':'first_successful_task','sandbox':request.account.is_test,
            **{key:state[key] for key in ('step','counted','counted_this_month','month_full','next_month','waiting_next_month','next_reward','rewards')}}

@endpoint(('POST',))
def deliver_artifact(request,artifact_id):
    artifact=Artifact.objects.filter(pk=artifact_id,account=request.account).first()
    if not artifact: raise DomainError('not_found',404)
    if request.account.telegram_user_id is None: raise DomainError('telegram_link_required',409)
    key=request.headers.get('Idempotency-Key','')
    if not 8<=len(key)<=128: raise DomainError('idempotency_key_required')
    if artifact.file.state!='ready' or artifact.file.expires_at<=timezone.now(): raise DomainError('file_expired',410)
    # A result held for a kept draft's changes past its day is sent to the chat no more (telegram/delivery.attempt).
    from apps.studio.keeping import held_past_its_day,held_refusal
    if held_past_its_day(artifact.file): raise held_refusal()
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
    if request.method=='GET':
        # The simulator has no loop of its own: a chat waiting for its CV's
        # files is looked at as the page asks, as the bot's loop looks at it.
        from apps.core.models import BotConversation
        from telegram.local import look_local,posts_local
        from telegram.posts import due
        chat=request.account.telegram_user_id
        if chat is not None and BotConversation.objects.filter(pk=chat,state='cv_wait').exists(): return look_local(request.account)
        # Posts from the admin arrive the same way: as the page asks.
        if chat is not None and due(request.account,limit=1): return posts_local(request.account)
        return history(request.account)
    throttle(request,'telegram_local',60)
    if request.FILES.get('file'): return dispatch_local(request.account,uploaded=request.FILES['file'])
    data=body(request)
    return dispatch_local(request.account,text=data.get('text'),callback_data=data.get('callback_data'))


@endpoint(('GET','POST'))
def manual_payments(request):
    """Card transfer: what is on sale, and this customer's latest payment."""
    if request.method=='GET':
        return {**manual.options(request.account),'payment':manual_payment_data(manual.latest_payment(request.account)),
                'checkout':checkout_data(checkout.latest(request.account),owner=True)}
    throttle(request,'manual-payments',20)
    payment,created=manual.create(request.account,body(request).get('plan'),'web')
    return JsonResponse(manual_payment_data(payment),status=201 if created else 200)

@endpoint(('GET','DELETE'))
def manual_payment_detail(request,payment_id):
    if request.method=='DELETE': return manual_payment_data(manual.cancel(request.account,payment_id))
    from .models import ManualPayment
    payment=ManualPayment.objects.filter(pk=payment_id,account=request.account).first()
    if not payment: raise DomainError('not_found',404)
    return manual_payment_data(payment)

@endpoint(('POST',))
def manual_payment_receipt(request,payment_id):
    throttle(request,'manual-receipts',20)
    upload=request.FILES.get('file')
    if upload is None: raise DomainError('invalid_receipt')
    if upload.size>manual.RECEIPT_BYTES: raise DomainError('receipt_too_large',413)
    raw=upload.read(manual.RECEIPT_BYTES+1)
    return manual_payment_data(manual.attach_receipt(request.account,payment_id,raw,request.POST.get('note',''),'web'))


@endpoint(('POST',))
def checkouts(request):
    """Automatic payment through inPAY: open a payment for a plan and return its page."""
    throttle(request,'checkouts',10)
    row,created=checkout.create(request.account,body(request).get('plan'),'web')
    return JsonResponse(checkout_data(row,owner=True),status=201 if created else 200)

@api(('GET',),auth=False)
def checkout_detail(request,checkout_id):
    """Where an automatic payment stands, for the page inPAY returns the customer to.

    Open without signing in: a customer who paid from the bot lands here in a
    browser that never saw them, and the id is not guessable. Asking is also
    what makes us ask inPAY, at most every few seconds (checkout.refresh).
    """
    from .models import Checkout
    throttle(request,'checkout-status',60)
    row=Checkout.objects.filter(pk=checkout_id).exclude(status='created').first()
    if not row: raise DomainError('not_found',404)
    row=checkout.refresh(row)
    return checkout_data(row,owner=bool(request.account and request.account.pk==row.account_id))

@csrf_exempt
def inpay_webhook(request):
    """inPAY says a payment moved. That is a reason to ask inPAY, never the answer itself.

    A v2 webhook is signed, and one signed with anything but its kassa's saved
    secret is turned away. Either way nothing is granted from what is posted
    here: the payment is looked up by its id and inPAY is asked where it stands.
    The answer is an error, so inPAY sends the webhook again later, whenever we
    could not ask, or inPAY says "paid" in the webhook and not yet when asked.

    Both kassas, the website's and the bot's, report here. A payment's own
    kassa holds the secret it is signed with; one we do not know is checked
    against every saved secret.
    """
    from operations.integrations import INPAY_KASSAS, inpay_config
    from . import inpay
    from .models import Checkout
    if request.method!='POST': return JsonResponse({'ok':False},status=405)
    raw=request.body
    if len(raw)>65536: return JsonResponse({'ok':False},status=413)
    try: payload=json.loads(raw or b'{}')
    except ValueError: payload=None
    identifier=inpay.webhook_payment(payload)
    row=Checkout.objects.filter(provider=checkout.PROVIDER,provider_id=identifier).first() if identifier else None
    kassas=[checkout.kassa(row.channel)] if row is not None else list(INPAY_KASSAS)
    held=[cfg['webhook_secret'] for cfg in map(inpay_config,kassas) if cfg['api']=='v2' and cfg['webhook_secret']]
    signed=False
    if held:
        header=request.headers.get('X-Inpay-Signature','')
        states={inpay.signature_state(secret,header,raw) for secret in held}
        state='valid' if 'valid' in states else 'stale' if 'stale' in states else 'invalid'
        if state=='invalid':
            # Signed, about one of our payments, and not with the secret we hold: the
            # secret was likely changed in the cabinet, and the owner should know.
            if header and row is not None: checkout.signature_refused(row.channel)
            return JsonResponse({'ok':False},status=401)
        signed=state=='valid'
    if payload is None: return JsonResponse({'ok':False},status=400)
    # About something that is not one of our payments, or one already settled: taken, so it is not sent again.
    if row is None or row.status in checkout.FINAL: return JsonResponse({'ok':True})
    # An unsigned call could be anyone repeating a payment's id: it asks inPAY no more often than a waiting page does.
    question=checkout.due(row,force=signed)
    # inPAY was asked a moment ago and this news may be newer than its answer: "again later".
    if question is None: return JsonResponse({'ok':False},status=503)
    try: remote=checkout.look(question)
    except inpay.Refused as refused:
        checkout.lookup_refused(refused,row.channel)
        return JsonResponse({'ok':False},status=503)
    except inpay.Unavailable: return JsonResponse({'ok':False},status=503)
    checkout.apply(row.pk,remote)
    # inPAY's event says paid and inPAY's own answer does not, yet: be told again.
    if inpay.webhook_claim(payload)=='paid' and remote['state']!='paid': return JsonResponse({'ok':False},status=503)
    return JsonResponse({'ok':True})
