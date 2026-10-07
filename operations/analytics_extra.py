from datetime import timedelta
from dataclasses import replace
from django.db.models import Count,Min
from django.utils import timezone
from apps.core.models import AnalyticsEvent,Job

def engagement(filters):
    start,end=filters.bounds;as_of=min(end,timezone.now())
    # Activity is filtered by event channel, independent of the signup channel.
    accounts=replace(filters,channel='').accounts(False)
    events=AnalyticsEvent.objects.filter(account__in=accounts,occurred_at__lt=as_of,event_type__in=('job.accepted','practice.completed'))
    if filters.channel:events=events.filter(channel=filters.channel)
    cohort=list(filters.accounts().values('id','created_at'))
    stages=[]
    for name in ('account.created','upload.accepted','quote.created','job.succeeded'):
        count=AnalyticsEvent.objects.filter(account_id__in=[a['id'] for a in cohort],occurred_at__gte=start,occurred_at__lt=end,event_type=name).values('account_id').distinct().count()
        stages.append({'event':name,'count':len(cohort) if name=='account.created' else count})
    retention=[]
    # Small first-stage reporting queries; mature buckets only, never count future windows as zero.
    for day in (1,7,30):
        mature=[a for a in cohort if a['created_at']+timedelta(days=day+1)<=as_of]
        retained=0
        for a in mature:
            retained+=events.filter(account_id=a['id'],occurred_at__gte=a['created_at']+timedelta(days=day),occurred_at__lt=a['created_at']+timedelta(days=day+1)).exists()
        retention.append({'day':day,'eligible':len(mature),'retained':retained,'percent':round(retained*100/len(mature),1) if mature else None})
    activity=[{'days':days,'users':events.filter(occurred_at__gte=as_of-timedelta(days=days)).values('account_id').distinct().count()} for days in (1,7,30)]
    return {'funnel':stages,'retention':retention,'activity':activity,'as_of':as_of,'bot_funnel':bot_funnel(filters)}


# What each step of the bot funnel is called, in the admin's three languages.
FUNNEL_LABELS={
    'bot.start':('Opened the bot','Botni ochdi','Открыли бота'),
    'bot.language':('Chose a language','Til tanladi','Выбрали язык'),
    'bot.verified':('Passed the one-tap check','Tekshiruvdan o‘tdi','Прошли проверку'),
    'bot.home':('Saw the menu','Menyuni ko‘rdi','Увидели меню'),
    'service.chosen':('Chose a service','Xizmat tanladi','Выбрали сервис'),
    'gate.shown':('Were asked to join the channel','Kanalga a’zo bo‘lish so‘raldi','Попросили подписаться'),
    'gate.joined':('Joined the channel','Kanalga a’zo bo‘ldi','Подписались'),
    'ai.described':('Described a document','Hujjatni tasvirladi','Описали документ'),
    'job.accepted':('Started a task','Vazifani boshladi','Запустили задачу'),
    'job.succeeded':('Got a result','Natija oldi','Получили результат'),
}


def bot_funnel(filters):
    """How many people reached each step in the bot in the period, and the share who went on.

    A step is counted once per person: before an account exists a person is a
    hashed visitor, after it their account.
    """
    from apps.core.funnel import BEFORE_ACCOUNT,STEPS
    start,end=filters.bounds
    events=AnalyticsEvent.objects.filter(occurred_at__gte=start,occurred_at__lt=end,channel='bot',
                                         environment=filters.environment)
    rows=[];previous=None
    for name in STEPS:
        found=events.filter(event_type=name)
        if name in BEFORE_ACCOUNT:
            count=len({(properties or {}).get('visitor') for properties in found.values_list('properties',flat=True)}-{None})
        else:
            count=found.exclude(account=None).values('account_id').distinct().count()
        share=round(count*100/previous) if previous else None
        en,uz,ru=FUNNEL_LABELS[name]
        rows.append({'event':name,'count':count,'share':share,'label_en':en,'label_uz':uz,'label_ru':ru})
        previous=count
    return rows if any(row['count'] for row in rows) else []
