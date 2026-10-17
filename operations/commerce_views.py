from datetime import timedelta
from django.db.models import Sum,Count,Min,Q
from django.core.paginator import Paginator
from django.http import HttpResponseBadRequest,HttpResponseForbidden
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from apps.core.errors import DomainError
from apps.commerce.models import Payment,Refund,SubscriptionPeriod,ManualPayment
from .auth import require_staff,audit
from .metrics import Filters
from .views import context,finish_render

LABELS={
'en':{'payers':'Paying accounts','paid':'Current paid subscribers','first':'First-time payers','sandbox':'Sandbox transactions · no real money','basis':'Payments and refunds use their own occurrence dates. Subscriber snapshot uses the selected end date, capped at now. Test purchases are excluded from production.','amount':'Amount','kind':'Purchase type','plan':'Plan','date':'Date','account':'Account','reason':'Reason','empty':'No transactions in this period.','refunded':'Refunded','status':'Status','detail':'Payment details','receipt':'Receipt','success':'Operation recorded.','no_reason':'Enter a reason of at least 5 characters.','subscription':'Subscription','renewal':'Renewal','latest':'Recent transactions'},
'uz':{'payers':'To‘lov qilgan hisoblar','paid':'Faol pulli obunachilar','first':'Birinchi marta to‘laganlar','sandbox':'Sinov to‘lovlari · haqiqiy pul emas','basis':'To‘lov va qaytarishlar sodir bo‘lgan sanasi bo‘yicha. Obunachilar tanlangan yakun sanasiga, hozirgi vaqtdan oshmagan holda hisoblanadi. Sinov to‘lovlari production hisobotiga kirmaydi.','amount':'Miqdor','kind':'Xarid turi','plan':'Tarif','date':'Sana','account':'Hisob','reason':'Sabab','empty':'Bu davrda to‘lovlar yo‘q.','refunded':'Qaytarilgan','status':'Holat','detail':'To‘lov tafsilotlari','receipt':'Kvitansiya','success':'Amal qayd etildi.','no_reason':'Kamida 5 belgili sabab kiriting.','subscription':'Obuna','renewal':'Uzaytirish','latest':'So‘nggi to‘lovlar'},
'ru':{'payers':'Плательщики','paid':'Текущие платные подписчики','first':'Впервые оплатившие','sandbox':'Тестовые платежи · без реальных денег','basis':'Платежи и возвраты учитываются по собственным датам. Снимок подписок — на выбранную конечную дату, не позднее текущей. Тестовые покупки исключены из production.','amount':'Сумма','kind':'Тип покупки','plan':'План','date':'Дата','account':'Аккаунт','reason':'Причина','empty':'За этот период платежей нет.','refunded':'Возвращён','status':'Статус','detail':'Детали платежа','receipt':'Квитанция','success':'Операция записана.','no_reason':'Укажите причину длиной не менее 5 символов.','subscription':'Подписка','renewal':'Продление','latest':'Последние платежи'}}

MANUAL_LABELS={'en': {'uzs_gross': "So'm received (card transfers)", 'uzs_refunds': "So'm refunded", 'uzs_net': "Net so'm", 'manual_pending': 'Card transfers to review', 'manual_queue': 'Card transfers to review', 'manual_none': 'Nothing to review.', 'awaiting_count': 'started, no receipt yet', 'reference': 'Reference', 'submitted': 'Sent', 'review': 'Review', 'manual_detail': 'Card transfer', 'check_bank': 'Before approving, open your bank app and check that {amount} arrived around {time}. A screenshot alone proves nothing.', 'duplicate': 'This exact receipt file was also sent for {references}. Check carefully.', 'receipt_view': 'Open receipt', 'pdf_download': 'Download PDF receipt', 'no_receipt': 'No receipt yet.', 'receipt_deleted': 'Receipt deleted after the retention period.', 'payer_note': 'Customer note', 'approve': 'Approve and start the plan', 'approve_note': 'Note (for the audit log)', 'approve_default': 'Transfer seen in the bank app', 'reject': 'Reject', 'reject_reason': 'Reason (the customer will see this)', 'refund_manual': 'Mark refunded (after you returned the money)', 'starts': 'Plan starts', 'ends': 'Paid until', 'decided': 'Decided', 'card_sent_to': 'Card it was sent to', 'channel': 'Channel', 'status_awaiting': 'Waiting for the transfer', 'status_submitted': 'Waiting for your review', 'status_approved': 'Approved', 'status_rejected': 'Rejected', 'status_cancelled': 'Cancelled by the customer', 'status_expired': 'Expired', 'status_refunded': 'Refunded', 'current_price': 'Price today', 'period_label': 'Approval gives', 'period_value': '{days} days of {plan}', 'price_more': 'This request was opened at an older, higher price: the customer was asked for {amount}, and the regular price is {price} today. Approving gives {days} days instead of 30, so the extra money buys extra time.', 'price_less': 'This request was opened before the price rose: the customer was asked for {amount}, and the plan costs {price} today. Approving still gives the usual 30 days.', 'price_discount_now': 'This request was opened at the regular price: the customer was asked for {amount}, and the plan is on discount today at {price}. Approving gives the usual 30 days.', 'price_discount_ended': 'This request was opened during a discount: the customer was asked for {amount}, and the plan costs {price} today. Approving still gives the usual 30 days.', 'current_regular': '{price} (regular {regular})', 'price_off_sale': 'This plan is not on sale any more. Approving still gives the usual 30 days.'}, 'uz': {'uzs_gross': "Tushgan so'm (karta o‘tkazmalari)", 'uzs_refunds': "Qaytarilgan so'm", 'uzs_net': "Sof so'm", 'manual_pending': 'Tekshiriladigan karta to‘lovlari', 'manual_queue': 'Tekshiriladigan karta to‘lovlari', 'manual_none': 'Tekshiriladigan to‘lov yo‘q.', 'awaiting_count': 'boshlangan, kvitansiya hali yo‘q', 'reference': 'Raqam', 'submitted': 'Yuborilgan', 'review': 'Ko‘rib chiqish', 'manual_detail': 'Karta orqali to‘lov', 'check_bank': 'Tasdiqlashdan oldin bank ilovangizni oching va {time} atrofida {amount} kelganini tekshiring. Skrinshotning o‘zi hech narsani isbotlamaydi.', 'duplicate': 'Aynan shu kvitansiya fayli {references} uchun ham yuborilgan. Diqqat bilan tekshiring.', 'receipt_view': 'Kvitansiyani ochish', 'pdf_download': 'PDF kvitansiyani yuklab olish', 'no_receipt': 'Kvitansiya hali yo‘q.', 'receipt_deleted': 'Kvitansiya saqlash muddatidan keyin o‘chirildi.', 'payer_note': 'Mijoz izohi', 'approve': 'Tasdiqlash va tarifni yoqish', 'approve_note': 'Izoh (audit jurnali uchun)', 'approve_default': 'O‘tkazma bank ilovasida ko‘rildi', 'reject': 'Rad etish', 'reject_reason': 'Sabab (mijoz ko‘radi)', 'refund_manual': 'Qaytarildi deb belgilash (pulni qaytargandan keyin)', 'starts': 'Tarif boshlanishi', 'ends': 'To‘langan muddat', 'decided': 'Qaror', 'card_sent_to': 'Pul yuborilgan karta', 'channel': 'Kanal', 'status_awaiting': 'O‘tkazma kutilmoqda', 'status_submitted': 'Tekshiruvingiz kutilmoqda', 'status_approved': 'Tasdiqlangan', 'status_rejected': 'Rad etilgan', 'status_cancelled': 'Mijoz bekor qilgan', 'status_expired': 'Muddati o‘tgan', 'status_refunded': 'Qaytarilgan', 'current_price': 'Bugungi narx', 'period_label': 'Tasdiqlansa beriladi', 'period_value': '{plan} tarifi, {days} kun', 'price_more': 'Bu so‘rov avvalgi, qimmatroq narxda ochilgan: mijozdan {amount} so‘ralgan, tarifning odatdagi narxi esa bugun {price}. Tasdiqlasangiz, 30 kun o‘rniga {days} kun beriladi — ortiqcha to‘langan pul qo‘shimcha muddatga aylanadi.', 'price_less': 'Bu so‘rov narx oshishidan oldin ochilgan: mijozdan {amount} so‘ralgan, tarif esa bugun {price} turadi. Tasdiqlasangiz, odatdagidek 30 kun beriladi.', 'price_discount_now': 'Bu so‘rov odatdagi narxda ochilgan: mijozdan {amount} so‘ralgan, tarif esa bugun chegirma bilan {price} turadi. Tasdiqlasangiz, odatdagidek 30 kun beriladi.', 'price_discount_ended': 'Bu so‘rov chegirma paytida ochilgan: mijozdan {amount} so‘ralgan, tarif esa bugun {price} turadi. Tasdiqlasangiz, odatdagidek 30 kun beriladi.', 'current_regular': '{price} (odatdagi narx {regular})', 'price_off_sale': 'Bu tarif endi sotilmaydi. Tasdiqlasangiz, odatdagidek 30 kun beriladi.'}, 'ru': {'uzs_gross': 'Получено сумов (переводы на карту)', 'uzs_refunds': 'Возвращено сумов', 'uzs_net': 'Чистые сумы', 'manual_pending': 'Переводы на проверку', 'manual_queue': 'Переводы на проверку', 'manual_none': 'Проверять нечего.', 'awaiting_count': 'начато, квитанции ещё нет', 'reference': 'Код', 'submitted': 'Отправлено', 'review': 'Проверить', 'manual_detail': 'Перевод на карту', 'check_bank': 'Прежде чем подтвердить, откройте банковское приложение и проверьте, что {amount} поступили около {time}. Скриншот сам по себе ничего не доказывает.', 'duplicate': 'Точно такой же файл квитанции прислан и для {references}. Проверьте внимательно.', 'receipt_view': 'Открыть квитанцию', 'pdf_download': 'Скачать PDF-квитанцию', 'no_receipt': 'Квитанции ещё нет.', 'receipt_deleted': 'Квитанция удалена после срока хранения.', 'payer_note': 'Комментарий клиента', 'approve': 'Подтвердить и включить тариф', 'approve_note': 'Комментарий (для журнала аудита)', 'approve_default': 'Перевод виден в банковском приложении', 'reject': 'Отклонить', 'reject_reason': 'Причина (клиент её увидит)', 'refund_manual': 'Отметить возврат (после того как вернули деньги)', 'starts': 'Начало тарифа', 'ends': 'Оплачено до', 'decided': 'Решение', 'card_sent_to': 'Карта получателя', 'channel': 'Канал', 'status_awaiting': 'Ожидается перевод', 'status_submitted': 'Ожидает вашей проверки', 'status_approved': 'Подтверждён', 'status_rejected': 'Отклонён', 'status_cancelled': 'Отменён клиентом', 'status_expired': 'Истёк', 'status_refunded': 'Возвращён', 'current_price': 'Цена сегодня', 'period_label': 'При подтверждении', 'period_value': '{plan} на {days} дн.', 'price_more': 'Запрос открыт по старой, более высокой цене: клиенту выставлено {amount}, а обычная цена тарифа сегодня — {price}. При подтверждении клиент получит {days} дн. вместо 30 — переплата станет дополнительным сроком.', 'price_less': 'Запрос открыт до повышения цены: клиенту выставлено {amount}, а сегодня тариф стоит {price}. При подтверждении клиент получит обычные 30 дней.', 'price_discount_now': 'Запрос открыт по обычной цене: клиенту выставлено {amount}, а сегодня тариф со скидкой стоит {price}. При подтверждении клиент получит обычные 30 дней.', 'price_discount_ended': 'Запрос открыт во время скидки: клиенту выставлено {amount}, а сегодня тариф стоит {price}. При подтверждении клиент получит обычные 30 дней.', 'current_regular': '{price} (обычная цена {regular})', 'price_off_sale': 'Этот тариф больше не продаётся. При подтверждении клиент получит обычные 30 дней.'}}
for _lang,_labels in MANUAL_LABELS.items(): LABELS[_lang].update(_labels)
REJECT_LABELS={'en':{'need_message':'Choose a message for the customer, or write your own.','reject_choice':'Message to the customer','choice_not_received':'Transfer not received','choice_amount_mismatch':"Amount doesn't match",'choice_unreadable':'Receipt unreadable','own_message':'Or write your own'},'uz':{'need_message':'Mijoz uchun xabarni tanlang yoki o‘zingiz yozing.','reject_choice':'Mijozga xabar','choice_not_received':'O‘tkazma kelmadi','choice_amount_mismatch':'Summa mos emas','choice_unreadable':'Kvitansiya o‘qilmaydi','own_message':'Yoki o‘zingiz yozing'},'ru':{'need_message':'Выберите сообщение для клиента или напишите своё.','reject_choice':'Сообщение клиенту','choice_not_received':'Перевод не поступил','choice_amount_mismatch':'Сумма не совпадает','choice_unreadable':'Квитанция нечитаема','own_message':'Или напишите своё'}}
for _lang,_labels in REJECT_LABELS.items(): LABELS[_lang].update(_labels)

def financial_report(filters):
    """Money in so'm: card transfers received and given back, who paid, and who is paid up.

    Only so'm is money here. Payment rows in another currency are history from
    a checkout that no longer exists; they stay in the list of transactions and
    out of the totals.
    """
    start,end=filters.bounds;as_of=min(end,timezone.now());sandbox=filters.environment=='development'
    every=Payment.objects.filter(account__in=filters.accounts(False),sandbox=sandbox)
    cards=every.filter(currency='UZS')
    rows=cards.filter(occurred_at__gte=start,occurred_at__lt=end)
    gross=rows.aggregate(n=Sum('amount_xtr'))['n'] or 0
    returned=Refund.objects.filter(payment__in=cards,status='confirmed',confirmed_at__gte=start,confirmed_at__lt=end).aggregate(n=Sum('amount_xtr'))['n'] or 0
    active=SubscriptionPeriod.objects.filter(account__in=filters.accounts(False),sandbox=sandbox,starts_at__lte=as_of,ends_at__gt=as_of).filter(Q(revoked_at__isnull=True)|Q(revoked_at__gt=as_of))
    first=cards.values('account_id').annotate(first=Min('occurred_at')).filter(first__gte=start,first__lt=end).count()
    return {'totals':{'uzs_gross':gross,'uzs_refunds':returned,'uzs_net':gross-returned,'payers':rows.values('account_id').distinct().count(),'paid':active.values('account_id').distinct().count(),'first':first,'manual_pending':ManualPayment.objects.filter(status='submitted').count()},'rows':every.filter(occurred_at__gte=start,occurred_at__lt=end).select_related('account').order_by('-occurred_at'),'as_of':as_of}

def money_cards(totals,labels):
    """The so'm totals, then the people behind them."""
    keys=[key for key in ('uzs_gross','uzs_refunds','uzs_net','payers','paid','first') if key in totals]
    return [{'key':key,'label':labels[key],'value':totals[key],'money':key.startswith('uzs_')} for key in keys]


@require_staff('Finance','Analyst')
@require_http_methods(['GET'])
def finance_page(request,section='payments'):
    from .auth import allowed
    if section=='payments' and not allowed(request.ops_user,['Finance']):return HttpResponseForbidden('Staff permission required')
    data=context(request,section);data['f']=LABELS[data['lang']]
    try:filters=Filters.from_request(request)
    except ValueError as e:return HttpResponseBadRequest(str(e))
    report=financial_report(filters);data.update(report);data['filters']=filters;data['pagination']=Paginator(report['rows'],30).get_page(request.GET.get('p'));data['cards']=money_cards(report['totals'],data['f']);data['now']=timezone.now()
    from .auth import allowed
    data['can_finance']=allowed(request.ops_user,['Finance'])
    if data['can_finance']:
        data['manual_queue']=ManualPayment.objects.filter(status='submitted').select_related('account').order_by('submitted_at')[:50]
        data['manual_awaiting']=ManualPayment.objects.filter(status='awaiting',expires_at__gt=timezone.now()).count()
    return finish_render(request,'ops/finance.html',data)

@require_staff('Finance')
@require_http_methods(['GET'])
def payment_detail(request,pk):
    """One payment row that is not a card transfer: history to look at, nothing to do to it."""
    payment=Payment.objects.select_related('account','invoice').filter(pk=pk).first()
    if not payment:return HttpResponseBadRequest('Unknown payment')
    data=context(request,'payments');data['f']=LABELS[data['lang']];data['payment']=payment;data['refund']=Refund.objects.filter(payment=payment).first()
    return finish_render(request,'ops/payment.html',data)


def _money(amount,currency):
    return f'{amount:,}'.replace(',',' ')+(" so'm" if currency=='UZS' else f' {currency}')


@require_staff('Finance')
@require_http_methods(['GET','POST'])
def manual_payment_detail(request,pk):
    """Review one card transfer: approve it, reject it, or record a refund."""
    from apps.commerce import manual
    payment=ManualPayment.objects.select_related('account','decided_by','payment').filter(pk=pk).first()
    if not payment:return HttpResponseBadRequest('Unknown payment')
    data=context(request,'payments');data['f']=LABELS[data['lang']]
    if request.method=='POST':
        action=request.POST.get('action','')
        # Only a rejection needs words, and they are for the customer: a
        # ready-made message in their language, or the owner's own.
        message=manual.rejection_message(payment,request.POST.get('choice',''),request.POST.get('message','')) if action=='reject' else ''
        if action=='reject' and not 5<=len(message)<=500:data['error']=data['f']['need_message']
        else:
            try:
                if action=='approve':manual.approve(payment.pk,request.ops_user)
                elif action=='reject':manual.reject(payment.pk,request.ops_user,message)
                elif action=='refund':manual.refund(payment.pk,request.ops_user,'Refund recorded by staff')
                else:raise DomainError('invalid_parameters')
                audit(request.ops_user,'payment.manual_'+action,payment.pk,message or None,
                      before={'status':payment.status},after={'reference':payment.reference,'plan':payment.plan,'amount':payment.amount})
                return redirect(request.path+'?lang='+data['lang'])
            except DomainError:
                # Someone else may have decided it a moment ago: say where it stands.
                payment.refresh_from_db();data['error']=data['f'].get('status_'+payment.status,payment.status)
    period=getattr(payment.payment,'period',None) if payment.payment_id else None
    f=data['f']
    # A request opened before the prices or the discount changed asks for its
    # old amount. Say so before the owner decides, with the days approving
    # gives (manual.period_days): today's price is what the customer pays now,
    # the regular one is what a period costs. What the request was opened
    # against is its own regular price then (regular_amount): below it, the
    # request was opened at a discount, whatever the panel holds today. A
    # request from before discounts has none, and was opened at the regular price.
    offer=manual.offers().get(payment.plan)
    today=offer['price'] if offer else None;regular=offer['regular'] if offer else None
    if payment.status in ManualPayment.OPEN:
        days=manual.period_days(payment)
        cur=payment.currency
        opened_against=payment.regular_amount if payment.regular_amount is not None else payment.amount
        price_today=_money(today,cur) if today else '';price_regular=_money(regular,cur) if regular else ''
        values={'amount':_money(payment.amount,cur),'price':price_today,'regular':price_regular,'days':days}
        if not today:note='price_off_sale'
        elif payment.amount==today:note=''
        # The extra days are worked out on the regular price, so that is the price this note quotes.
        elif payment.amount>regular:note='price_more';values['price']=price_regular
        elif payment.amount<opened_against:note='price_discount_ended'  # opened at a discount; today's price is another
        elif payment.amount>today:note='price_discount_now'  # opened at the regular price, on discount today
        else:note='price_less'  # opened at the regular price, which rose since
        shown=f['current_regular'].format(price=price_today,regular=price_regular) if offer and offer['discount'] else price_today
        data.update(current_price=shown,period_days=f['period_value'].format(days=days,plan=payment.plan.title()),
                    price_note=f[note].format(**values) if note else '')
    duplicates=', '.join(manual.duplicates(payment).values_list('reference',flat=True))
    data['reject_choices']=[{'key':key,'label':f['choice_'+key]} for key in manual.REJECTIONS]
    data.update(manual=payment,period=period,status_label=f.get('status_'+payment.status,payment.status),amount=_money(payment.amount,payment.currency),
                duplicates=f['duplicate'].format(references=duplicates) if duplicates else '',
                check=f['check_bank'].format(amount=_money(payment.amount,payment.currency),time=timezone.localtime(payment.submitted_at or payment.created_at).strftime('%d %b %H:%M')),
                card_last4=str((payment.card or {}).get('number',''))[-4:])
    return finish_render(request,'ops/manual_payment.html',data)


@require_staff('Finance')
@require_http_methods(['GET'])
def manual_payment_receipt(request,pk):
    """The receipt, served to Finance staff only, and only after the view is audited."""
    from django.http import FileResponse,Http404
    from apps.core.services import storage_path
    payment=ManualPayment.objects.filter(pk=pk).first()
    if not payment or not payment.receipt_key:raise Http404()
    audit(request.ops_user,'payment.receipt_view',payment.pk,f'Reviewing card transfer {payment.reference}')
    from apps.core import storage
    path=storage.local(payment.receipt_key)
    if not path.exists():raise Http404()
    response=FileResponse(path.open('rb'),content_type=payment.receipt_type or 'application/octet-stream')
    kind='attachment' if payment.receipt_type=='application/pdf' else 'inline'
    response['Content-Disposition']=f'{kind}; filename="{payment.reference}.{"pdf" if kind=="attachment" else "jpg"}"'
    response['X-Content-Type-Options']='nosniff';response['Cache-Control']='no-store, private'
    response['Content-Security-Policy']="default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
    return response
