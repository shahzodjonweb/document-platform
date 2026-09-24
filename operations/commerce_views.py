from datetime import timedelta
from django.db.models import Sum,Count,Min,Q
from django.core.paginator import Paginator
from django.http import HttpResponseBadRequest,HttpResponseForbidden
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from apps.core.errors import DomainError
from apps.commerce.models import Payment,Refund,Subscription,SubscriptionPeriod,ReconciliationIssue,OfferVersion
from apps.commerce.services import refund_payment,reconcile_transactions
from .auth import require_staff,audit
from .metrics import Filters
from .views import context,finish_render

LABELS={
'en':{'gross':'Stars collected','refunds':'Stars refunded','net':'Net Stars','payers':'Paying accounts','paid':'Current paid subscribers','renewals':'Renewal transactions','first':'First-time payers','run_rate':'Renewing run-rate / 30 days','sandbox':'Sandbox transactions · no real money','basis':'Payments and refunds use their own occurrence dates. Subscriber snapshot uses the selected end date, capped at now. Test purchases are excluded from production.','amount':'Amount','kind':'Purchase type','plan':'Plan','date':'Date','account':'Account','refund':'Request refund','reason':'Reason','reconcile':'Reconcile Telegram transactions','issues':'Reconciliation alerts','empty':'No transactions in this period.','refunded':'Refunded','pending':'Pending refund','status':'Status','detail':'Payment details','receipt':'Receipt','success':'Operation recorded.','failed':'Provider could not confirm the action. Try again later.','no_reason':'Enter a reason of at least 5 characters.','subscription':'Subscription','task_pack':'Task pack','ai_pack':'AI credits','renewal':'Renewal','initial':'First purchase','reconciliation':'Reconciliation','latest':'Recent transactions'},
'uz':{'gross':'Tushgan Stars','refunds':'Qaytarilgan Stars','net':'Sof Stars','payers':'To‘lov qilgan hisoblar','paid':'Faol pulli obunachilar','renewals':'Obuna uzaytirishlar','first':'Birinchi marta to‘laganlar','run_rate':'30 kunlik uzaytirish miqdori','sandbox':'Sinov to‘lovlari · haqiqiy pul emas','basis':'To‘lov va qaytarishlar sodir bo‘lgan sanasi bo‘yicha. Obunachilar tanlangan yakun sanasiga, hozirgi vaqtdan oshmagan holda hisoblanadi. Sinov to‘lovlari production hisobotiga kirmaydi.','amount':'Miqdor','kind':'Xarid turi','plan':'Tarif','date':'Sana','account':'Hisob','refund':'Pulni qaytarish','reason':'Sabab','reconcile':'Telegram to‘lovlarini solishtirish','issues':'Solishtirish ogohlantirishlari','empty':'Bu davrda to‘lovlar yo‘q.','refunded':'Qaytarilgan','pending':'Qaytarish kutilmoqda','status':'Holat','detail':'To‘lov tafsilotlari','receipt':'Kvitansiya','success':'Amal qayd etildi.','failed':'Provayder tasdiqlamadi. Keyinroq qayta urining.','no_reason':'Kamida 5 belgili sabab kiriting.','subscription':'Obuna','task_pack':'Vazifalar paketi','ai_pack':'AI kreditlar','renewal':'Uzaytirish','initial':'Birinchi xarid','reconciliation':'Solishtirish','latest':'So‘nggi to‘lovlar'},
'ru':{'gross':'Полученные Stars','refunds':'Возвращённые Stars','net':'Чистые Stars','payers':'Плательщики','paid':'Текущие платные подписчики','renewals':'Продления','first':'Впервые оплатившие','run_rate':'Сумма продлений / 30 дней','sandbox':'Тестовые платежи · без реальных денег','basis':'Платежи и возвраты учитываются по собственным датам. Снимок подписок — на выбранную конечную дату, не позднее текущей. Тестовые покупки исключены из production.','amount':'Сумма','kind':'Тип покупки','plan':'План','date':'Дата','account':'Аккаунт','refund':'Запросить возврат','reason':'Причина','reconcile':'Сверить платежи Telegram','issues':'Проблемы сверки','empty':'За этот период платежей нет.','refunded':'Возвращён','pending':'Ожидается возврат','status':'Статус','detail':'Детали платежа','receipt':'Квитанция','success':'Операция записана.','failed':'Провайдер не подтвердил действие. Повторите позже.','no_reason':'Укажите причину длиной не менее 5 символов.','subscription':'Подписка','task_pack':'Пакет задач','ai_pack':'Кредиты ИИ','renewal':'Продление','initial':'Первая покупка','reconciliation':'Сверка','latest':'Последние платежи'}}

def financial_report(filters):
    start,end=filters.bounds;as_of=min(end,timezone.now());sandbox=filters.environment=='development'
    base=Payment.objects.filter(account__in=filters.accounts(False),sandbox=sandbox)
    rows=base.filter(occurred_at__gte=start,occurred_at__lt=end)
    refunds=Refund.objects.filter(payment__in=base,status='confirmed',confirmed_at__gte=start,confirmed_at__lt=end)
    active=SubscriptionPeriod.objects.filter(account__in=filters.accounts(False),sandbox=sandbox,starts_at__lte=as_of,ends_at__gt=as_of).filter(Q(revoked_at__isnull=True)|Q(revoked_at__gt=as_of))
    gross=rows.aggregate(n=Sum('amount_xtr'))['n'] or 0;returned=refunds.aggregate(n=Sum('amount_xtr'))['n'] or 0
    first=base.values('account_id').annotate(first=Min('occurred_at')).filter(first__gte=start,first__lt=end).count()
    renewing=Subscription.objects.filter(account_id__in=active.values('account_id'),sandbox=sandbox,renewal_enabled=True)
    runrate=renewing.aggregate(n=Sum('offer__price_xtr'))['n'] or 0
    return {'totals':{'gross':gross,'refunds':returned,'net':gross-returned,'payers':rows.values('account_id').distinct().count(),'paid':active.values('account_id').distinct().count(),'renewals':rows.filter(is_renewal=True).count(),'first':first,'run_rate':runrate},'rows':rows.select_related('account').order_by('-occurred_at'),'as_of':as_of,'issues':ReconciliationIssue.objects.filter(status='open',invoice__sandbox=sandbox,invoice__account__in=filters.accounts(False)).order_by('-created_at')[:30]}

@require_staff('Finance','Analyst')
@require_http_methods(['GET'])
def finance_page(request,section='payments'):
    from .auth import allowed
    if section=='payments' and not allowed(request.ops_user,['Finance']):return HttpResponseForbidden('Staff permission required')
    data=context(request,section);data['f']=LABELS[data['lang']]
    try:filters=Filters.from_request(request)
    except ValueError as e:return HttpResponseBadRequest(str(e))
    report=financial_report(filters);data.update(report);data['filters']=filters;data['pagination']=Paginator(report['rows'],30).get_page(request.GET.get('p'));data['cards']=[{'label':data['f'][k],'value':v} for k,v in report['totals'].items()];data['now']=timezone.now()
    from .auth import allowed
    data['can_finance']=allowed(request.ops_user,['Finance'])
    return finish_render(request,'ops/finance.html',data)

@require_staff('Finance')
@require_http_methods(['GET','POST'])
def payment_detail(request,pk):
    payment=Payment.objects.select_related('account','invoice').filter(pk=pk).first()
    if not payment:return HttpResponseBadRequest('Unknown payment')
    data=context(request,'payments');data['f']=LABELS[data['lang']];data['payment']=payment;data['refund']=Refund.objects.filter(payment=payment).first()
    if request.method=='POST':
        reason=request.POST.get('reason','').strip()
        if len(reason)<5:data['error']=data['f']['no_reason']
        else:
            try:
                refund_payment(payment,reason,actor=request.ops_user,sandbox_account=payment.account if payment.sandbox else None)
                audit(request.ops_user,'payment.refund',payment.pk,reason,after={'sandbox':payment.sandbox})
                return redirect(request.path+'?lang='+data['lang'])
            except DomainError:data['error']=data['f']['failed']
    return finish_render(request,'ops/payment.html',data)
