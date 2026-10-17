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


def plans_screen(filters,t,with_viewers=False):
    """Who opened the plans screen in the bot in the period, how often, from where, and what they did next.

    A person is an account; every opening is a view, repeats included. What
    after: a card-transfer request opened, and a payment made, which is a card
    transfer the owner approved. Money given back is not a payment: a refunded
    card transfer is no longer 'approved'. Days are counted in the report's
    zone, the viewer's own unless they pick another.

    `t` is the admin's labels in the viewer's language. The list of who looked
    names customers, so it is only made when `with_viewers` says the viewer may
    open their accounts.
    """
    from zoneinfo import ZoneInfo
    from datetime import date
    from django.db.models import CharField,Exists,OuterRef,Subquery,Value
    from django.db.models.fields.json import KT
    from django.db.models.functions import Coalesce,TruncDate
    from apps.commerce.models import ManualPayment
    from apps.core.models import Account
    start,end=filters.bounds
    # Every view is the bot's, so a web or Mini App channel filter leaves none.
    events=AnalyticsEvent.objects.filter(event_type='plans.viewed',occurred_at__gte=start,occurred_at__lt=end,
                                         channel=filters.channel or 'bot',environment=filters.environment)
    if filters.locale:events=events.filter(locale=filters.locale)
    # A view from before sources were kept says nothing: it is 'other' too.
    def source():return Coalesce(KT('properties__source'),Value('other'),output_field=CharField())
    def label(key):return t.get('plans_from_'+str(key),t['plans_from_other'])
    def share(part,whole):return round(part*100/whole) if whole else None
    views=events.count()
    people=events.exclude(account=None).values('account_id').distinct().count()
    result={'views':views,'people':people,'daily':[],'by_source':[],'by_plan':[],'started':0,'paid':0,
            'started_share':None,'paid_share':None,'started_note':'','paid_note':'','viewers':[],'with_viewers':with_viewers}
    if not views:return result
    per_day={str(row['day']):row for row in events.annotate(day=TruncDate('occurred_at',tzinfo=ZoneInfo(filters.timezone)))
             .values('day').annotate(views=Count('id'),people=Count('account_id',distinct=True)).order_by('day')}
    day,stop=date.fromisoformat(filters.date_from),date.fromisoformat(filters.date_to)
    while day<stop:
        row=per_day.get(str(day),{})
        result['daily'].append({'date':str(day),'label':day.strftime('%d.%m'),'views':row.get('views',0),'people':row.get('people',0)})
        day+=timedelta(days=1)
    highest=max([row['views'] for row in result['daily']]+[1])
    for row in result['daily']:row['height']=round(100*row['views']/highest,1)
    result['by_source']=[{'source':row['source'],'label':label(row['source']),'views':row['views'],'people':row['people']}
                         for row in events.annotate(source=source()).values('source')
                         .annotate(views=Count('id'),people=Count('account_id',distinct=True)).order_by('-views','source')]
    order={'free':0,'plus':1,'premium':2}
    result['by_plan']=sorted(events.values('plan_at_event').annotate(views=Count('id'),people=Count('account_id',distinct=True)).order_by(),
                             key=lambda row:(order.get(row['plan_at_event'],3),row['plan_at_event']))
    # One row per person, worked out in the database: when they first looked
    # in the period, and whether a card request or a payment came after that.
    mine=events.filter(account_id=OuterRef('pk'))
    viewers=Account.objects.filter(pk__in=events.values('account_id')).annotate(
        first_view=Subquery(mine.order_by('occurred_at').values('occurred_at')[:1]))
    requested=ManualPayment.objects.filter(account_id=OuterRef('pk'),created_at__gte=OuterRef('first_view'))
    viewers=viewers.annotate(started=Exists(requested),paid=Exists(requested.filter(status='approved')))
    result['started']=viewers.filter(started=True).count()
    result['paid']=viewers.filter(paid=True).count()
    result['started_share'],result['paid_share']=share(result['started'],people),share(result['paid'],people)
    # "50% of the people who looked", worded for each language.
    for key in ('started','paid'):
        part=result[key+'_share']
        result[key+'_note']=t['plans_of_people'].format(n=part) if part is not None else t[f'plans_{key}_definition']
    if with_viewers:
        latest=mine.order_by('-occurred_at')
        recent=viewers.annotate(
            last_view=Subquery(latest.values('occurred_at')[:1]),
            last_source=Subquery(latest.annotate(source=source()).values('source')[:1]),
            last_plan=Subquery(latest.values('plan_at_event')[:1]),
            view_count=Subquery(mine.order_by().values('account_id').annotate(n=Count('id')).values('n')[:1]),
        ).only('id','display_name','username','telegram_user_id').order_by('-last_view','pk')[:50]
        result['viewers']=[{'id':row.pk,'name':row.display_name or row.username or str(row.pk),'username':row.username,
                            'telegram_user_id':row.telegram_user_id,'plan':row.last_plan,'views':row.view_count,
                            'last_view':row.last_view,'source':label(row.last_source),'started':row.started,
                            'paid':row.paid} for row in recent]
    return result
