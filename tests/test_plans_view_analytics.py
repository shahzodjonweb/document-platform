"""Who looks at the plans in the bot, from where, and what they do next.

The owner asked who opens the plans screen. Every look is kept (not once a
day), with where it was opened from, so the admin shows how many people looked,
how many times, from which screen, on which plan, and how many then asked to
pay by card or paid.
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import AsyncMock, Mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, RequestFactory
from django.utils import timezone

from apps.commerce import manual
from apps.commerce.models import ManualPayment, PaymentNotice
from apps.core import channel_gate, funnel
from apps.core.identity import resolve_account
from apps.core.models import Account, AnalyticsEvent, BotCallback, BotConversation
from operations.analytics_extra import plans_screen
from operations.i18n import CATALOGS
from operations.metrics import Filters
from operations.middleware import COOKIE as ZONE_COOKIE
from telegram.billing import COPY, PLAN_COPY
from telegram.payment_notices import drain
from tests.test_bot_no_flood import Chat
from tests.test_channel_gate import Telegram, require_channels
from tests.test_manual_payments import configure, finance, png, submitted
from tests.test_operations import staff_client

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]


@pytest.fixture
def customer(settings):
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    account = resolve_account({'id': 986001, 'first_name': 'Looker'}, is_test=True)
    BotConversation.objects.create(telegram_user_id=account.telegram_user_id, locale='en', language_selected_at=timezone.now())
    return account


@pytest.fixture
def telegram(monkeypatch):
    fake = Telegram()
    monkeypatch.setattr(channel_gate, '_call', fake)
    monkeypatch.setattr(channel_gate, '_token', lambda: '1:TOKEN')
    return fake


def looks(account):
    """Where each look at the plans came from, oldest first."""
    rows = AnalyticsEvent.objects.filter(account=account, event_type='plans.viewed').order_by('occurred_at')
    return [row.properties.get('source') for row in rows]


def on_plans(chat):
    assert PLAN_COPY['en']['title'] in chat.last(), chat.last()


def token(chat, action, **payload):
    """The button for `action` on the bot's newest screens, as Telegram would send it back."""
    for message in reversed(chat.result['messages']):
        for row in message['buttons']:
            for button in row:
                data = button.get('callback_data')
                ref = BotCallback.objects.filter(pk=data, action=action).first() if data else None
                if ref and all(ref.payload.get(k) == v for k, v in payload.items()):
                    return data
    raise AssertionError(f'No {action} button')


# ---------------------------------------------------------------- the bot counts


def from_menu(chat):
    chat.do(text='/menu')
    chat.tap('plans', **{'from': 'menu'})


def from_account(chat):
    chat.do(text='/account')
    chat.tap('plans', **{'from': 'account'})


def from_command(chat):
    chat.do(text='/plans')


def from_buy(chat):
    chat.do(text='/buy')


def from_an_old_pack_command(chat):
    # A pack no longer sold opens the plans on sale instead.
    chat.do(text='/buy ai100')


def from_channels(chat):
    require_channels()
    chat.do(text='/menu')
    chat.tap('ai_tool', feature_id='ai.pdf_topic')
    chat.tap('plans', **{'from': 'channels'})


def from_subscription(chat):
    chat.do(text='/subscription')
    chat.tap('plans', **{'from': 'subscription'})


def from_payment(chat):
    configure()
    chat.do(text='/plans')
    chat.tap('commerce_manual_plan', plan='plus')
    AnalyticsEvent.objects.filter(event_type='plans.viewed').delete()  # only Back is under test
    chat.tap('plans', **{'from': 'payment'})


def from_notice(chat):
    configure()
    chat.do(text='/plans')
    chat.tap('commerce_manual_plan', plan='plus')
    chat.tap('commerce_manual_receipt')
    chat.do(uploaded=SimpleUploadedFile('receipt.jpg', png(), 'image/jpeg'))
    AnalyticsEvent.objects.filter(event_type='plans.viewed').delete()
    # "Receipt received" comes with Subscription and Plans under it.
    chat.tap('plans', **{'from': 'notice'})


def from_limit(chat):
    from operations import plans as plan_settings
    plan_settings.save('free', {'weekly_ai_documents': 1})
    chat.do(text='/menu')
    chat.tap('ai_tool', feature_id='ai.pdf_topic')
    chat.do(text='A two page note about tides for students')
    chat.tap('ai_run')
    chat.do(text='/menu')
    chat.tap('ai_tool', feature_id='ai.pdf_topic')
    chat.do(text='Another two page note about the moon')
    assert 'This week’s AI documents are used up' in chat.last()
    chat.tap('plans', **{'from': 'limit'})


WAYS = {'menu': (from_menu, 'menu'), 'account': (from_account, 'account'), 'plans': (from_command, 'command'),
        'buy': (from_buy, 'command'), 'old_pack': (from_an_old_pack_command, 'command'),
        'channels': (from_channels, 'channels'), 'subscription': (from_subscription, 'subscription'),
        'payment': (from_payment, 'payment'), 'notice': (from_notice, 'notice'), 'limit': (from_limit, 'limit')}


@pytest.mark.parametrize('way', list(WAYS))
def test_every_way_to_the_plans_is_one_look_with_where_it_was_opened(customer, telegram, way):
    opened, source = WAYS[way]
    chat = Chat(customer)
    opened(chat)
    on_plans(chat)
    assert looks(customer) == [source]
    event = AnalyticsEvent.objects.get(event_type='plans.viewed')
    assert (event.channel, event.locale, event.plan_at_event) == ('bot', 'en', 'free')
    assert source in funnel.PLAN_SOURCES


def test_two_looks_are_two_views_and_one_person(customer):
    chat = Chat(customer)
    chat.do(text='/plans')
    from_menu(chat)
    assert looks(customer) == ['command', 'menu'], 'every look is kept, not one a day'
    today = timezone.now().date()
    report = plans_screen(Filters(str(today), str(today + timedelta(days=1)), 'UTC', 'development', '', ''),
                          CATALOGS['en'], with_viewers=True)
    assert (report['views'], report['people']) == (2, 1)
    assert report['viewers'][0]['views'] == 2 and report['viewers'][0]['source'] == 'Main menu'


def test_a_double_tap_on_a_plans_button_is_one_look(customer):
    # Telegram sends both taps before the screen has changed, and each draws
    # the plans again with fresh buttons, so the second edit succeeds too and
    # only the button tells the two apart.
    chat = Chat(customer)
    chat.do(text='/menu')
    plans = token(chat, 'plans', **{'from': 'menu'})
    chat.do(callback_data=plans)
    chat.do(callback_data=plans)
    on_plans(chat)
    assert looks(customer) == ['menu']
    # A Plans button on a new menu is a look of its own, however soon.
    from_menu(chat)
    assert looks(customer) == ['menu', 'menu']
    # Only a tap is caught: a screen drawn without one is always counted.
    funnel.plans_viewed(customer, 'menu')
    funnel.plans_viewed(customer, 'menu')
    assert looks(customer) == ['menu'] * 4


def test_the_renewal_reminder_opens_the_plans_as_a_message_from_the_bot(customer):
    """The reminder is how a card customer comes back to pay, so its Plans
    button says where it is. The /plans in its text sends the command, and is
    counted as one: the admin's label says so."""
    configure()
    manual.approve(submitted(customer, 'plus').id, finance())
    PaymentNotice.objects.all().delete()
    manual.housekeeping(timezone.now() + timedelta(days=28))
    bot = Mock(send_message=AsyncMock(return_value=Mock(message_id=55)))
    asyncio.run(drain(bot))
    (chat_id, text), sent = bot.send_message.await_args.args, bot.send_message.await_args.kwargs
    assert chat_id == customer.telegram_user_id and text.endswith('/plans')
    assert PaymentNotice.objects.get().kind == 'renewal_reminder'
    [[plans]] = sent['reply_markup'].inline_keyboard
    assert plans.text == COPY['en']['plans']
    assert BotCallback.objects.get(pk=plans.callback_data).payload == {'from': 'notice'}
    chat = Chat(customer)
    chat.do(callback_data=plans.callback_data)
    on_plans(chat)
    assert looks(customer) == ['notice']
    assert 'a link in a message' in CATALOGS['en']['plans_from_command']


def test_a_reminder_goes_out_even_when_its_button_cannot_be_made(customer, monkeypatch):
    configure()
    manual.approve(submitted(customer, 'plus').id, finance())
    PaymentNotice.objects.all().delete()
    manual.housekeeping(timezone.now() + timedelta(days=28))

    async def broken(*args, **kwargs):
        raise RuntimeError('callback table is locked')
    monkeypatch.setattr('telegram.billing.button', broken)
    bot = Mock(send_message=AsyncMock(return_value=Mock(message_id=55)))
    asyncio.run(drain(bot))
    assert bot.send_message.await_args.kwargs['reply_markup'] is None
    assert PaymentNotice.objects.get().status == 'delivered'


def test_an_old_plans_button_without_a_source_counts_as_other(customer):
    chat = Chat(customer)
    chat.do(text='/menu')
    # A Plans button sent before buttons said where they were, days ago.
    old = BotCallback.objects.create(token='old-plans-button', account=customer, action='plans', payload={},
                                     expires_at=timezone.now() - timedelta(days=3))
    chat.do(callback_data=old.pk)
    on_plans(chat)
    # Nor does a source nobody knows reach the report.
    odd = BotCallback.objects.create(token='odd-plans-button', account=customer, action='plans',
                                     payload={'from': 'somewhere'}, expires_at=timezone.now() + timedelta(days=1))
    chat.do(callback_data=odd.pk)
    assert looks(customer) == ['other', 'other']


def test_the_plans_open_even_when_the_look_cannot_be_counted(customer, monkeypatch):
    real = AnalyticsEvent.objects.create

    def broken(**values):
        if values.get('event_type') == 'plans.viewed':
            raise RuntimeError('analytics database is down')
        return real(**values)
    monkeypatch.setattr(AnalyticsEvent.objects, 'create', broken)
    chat = Chat(customer)
    assert chat.do(text='/plans') == 1
    on_plans(chat)
    from_menu(chat)
    on_plans(chat)
    assert looks(customer) == []


def test_a_plan_that_cannot_be_worked_out_still_counts_the_look(customer, monkeypatch):
    def broken(account, at=None):
        raise RuntimeError('subscription lookup failed')
    monkeypatch.setattr('apps.commerce.services.effective_plan', broken)
    funnel.plans_viewed(customer, 'menu')
    assert AnalyticsEvent.objects.get(event_type='plans.viewed').plan_at_event == 'free'


def test_the_plan_recorded_is_the_one_the_screen_says_they_have(customer):
    Account.objects.filter(pk=customer.pk).update(staff_plan='premium')
    customer.refresh_from_db()
    Chat(customer).do(text='/plans')
    assert AnalyticsEvent.objects.get(event_type='plans.viewed').plan_at_event == 'premium'


def test_test_accounts_and_development_machines_stay_out_of_production(customer, settings):
    Chat(customer).do(text='/plans')
    assert AnalyticsEvent.objects.get(event_type='plans.viewed').environment == 'development'
    AnalyticsEvent.objects.all().delete()
    settings.DEBUG = False
    real = Account.objects.create(telegram_user_id=986002, locale='uz')
    funnel.plans_viewed(customer, 'menu')
    funnel.plans_viewed(real, 'menu')
    environments = dict(AnalyticsEvent.objects.values_list('account_id', 'environment'))
    assert environments == {customer.pk: 'development', real.pk: 'production'}
    assert AnalyticsEvent.objects.get(account=real).locale == 'uz'
    settings.DEBUG = True
    funnel.plans_viewed(real, 'menu')
    assert AnalyticsEvent.objects.filter(account=real, environment='development').count() == 1


# ---------------------------------------------------------------- the admin shows


UTC = dt_timezone.utc


def at(day, hour=10, minute=0):
    return datetime(2026, 9, day, hour, minute, tzinfo=UTC)


def look(account, when, source, plan='free', environment='production'):
    return AnalyticsEvent.objects.create(account=account, event_type='plans.viewed', channel='bot', locale='en',
                                         plan_at_event=plan, environment=environment, occurred_at=when,
                                         properties={'source': source})


def card_request(account, created, status='awaiting'):
    return ManualPayment.objects.create(reference=uuid.uuid4().hex[:10].upper(), account=account, plan='plus',
                                        amount=20000, status=status, created_at=created,
                                        expires_at=created + timedelta(hours=48))


@pytest.fixture
def september(settings):
    """Four people in production who looked at the plans in September 2026, and what they did."""
    settings.DEBUG = True
    people = {name: Account.objects.create(telegram_user_id=986100 + i, display_name=name, username=name.lower(),
                                           created_at=at(1, 0))
              for i, name in enumerate(('Aziza', 'Bekzod', 'Dilnoza', 'Eldor'))}
    aziza, bekzod, dilnoza, eldor = people.values()
    look(aziza, at(5), 'menu')
    look(aziza, at(6), 'limit')
    card_request(aziza, at(6, 11), status='approved')        # asked to pay by card, and paid
    look(bekzod, at(6, 12), 'menu', plan='plus')
    card_request(bekzod, at(7))                                # asked, still waiting
    look(dilnoza, at(7), 'channels')
    card_request(dilnoza, at(8), status='approved')           # paid by card the next day
    look(eldor, at(8, 20, 30), 'command', plan='premium')
    card_request(eldor, at(1), status='approved')             # before the look: not what it led to
    # Late on 31 August in UTC, which is already 1 September in Tashkent.
    look(aziza, datetime(2026, 8, 31, 23, 0, tzinfo=UTC), 'account')
    # A test account, which production never counts.
    tester = Account.objects.create(telegram_user_id=986199, display_name='Tester', is_test=True)
    look(tester, at(10), 'notice', environment='development')
    return people


def filters_for(**values):
    query = {'date_from': '2026-09-01', 'date_to': '2026-10-01', 'timezone': 'UTC', **values}
    return Filters.from_request(RequestFactory().get('/', query))


def test_the_report_counts_people_views_sources_plans_and_what_came_next(september):
    report = plans_screen(filters_for(), CATALOGS['en'], with_viewers=True)
    assert (report['views'], report['people']) == (5, 4)
    assert [(row['source'], row['views'], row['people']) for row in report['by_source']] == [
        ('menu', 2, 2), ('channels', 1, 1), ('command', 1, 1), ('limit', 1, 1)]
    assert [(row['plan_at_event'], row['views'], row['people']) for row in report['by_plan']] == [
        ('free', 3, 2), ('plus', 1, 1), ('premium', 1, 1)]
    assert (report['started'], report['started_share'], report['paid'], report['paid_share']) == (3, 75, 2, 50)
    assert report['started_note'] == '75% of the people who looked'
    daily = {row['date']: (row['views'], row['people']) for row in report['daily'] if row['views']}
    assert daily == {'2026-09-05': (1, 1), '2026-09-06': (2, 2), '2026-09-07': (1, 1), '2026-09-08': (1, 1)}
    assert len(report['daily']) == 30
    viewers = [(row['name'], row['plan'], row['views'], row['source'], row['started'], row['paid'])
               for row in report['viewers']]
    assert viewers == [('Eldor', 'premium', 1, '/plans or /buy, typed or a link in a message', False, False),
                       ('Dilnoza', 'free', 1, 'Channel request', True, True),
                       ('Bekzod', 'plus', 1, 'Main menu', True, False),
                       ('Aziza', 'free', 2, 'A used-up limit', True, True)]
    assert report['viewers'][0]['last_view'] == at(8, 20, 30)


def test_the_report_keeps_to_the_period_environment_channel_and_language(september):
    assert plans_screen(filters_for(date_from='2026-09-07'), CATALOGS['en'])['views'] == 2
    development = plans_screen(filters_for(environment='development'), CATALOGS['en'], with_viewers=True)
    assert (development['views'], development['people']) == (1, 1)
    assert development['viewers'][0]['name'] == 'Tester' and development['by_source'][0]['source'] == 'notice'
    assert plans_screen(filters_for(channel='web'), CATALOGS['en'])['views'] == 0
    assert plans_screen(filters_for(channel='bot'), CATALOGS['en'])['views'] == 5
    assert plans_screen(filters_for(locale='ru'), CATALOGS['en'])['views'] == 0
    # Days are the viewer's: in Tashkent the late 31 August look is on 1 September.
    tashkent = plans_screen(filters_for(timezone='Asia/Tashkent'), CATALOGS['en'], with_viewers=True)
    assert (tashkent['views'], tashkent['people']) == (6, 4)
    assert tashkent['daily'][0] == {'date': '2026-09-01', 'label': '01.09', 'views': 1, 'people': 1, 'height': 50.0}
    assert {row['date']: row['views'] for row in tashkent['daily'] if row['views']}['2026-09-09'] == 1
    # Not asked for, the names are not even looked up.
    assert plans_screen(filters_for(), CATALOGS['en'])['viewers'] == []


def test_only_an_approved_card_transfer_is_a_payment_and_money_given_back_is_not():
    names = ('Card back', 'Card paid', 'Card waiting')
    back, paid, waiting = (Account.objects.create(telegram_user_id=986400 + i, display_name=name)
                           for i, name in enumerate(names))
    for person in (back, paid, waiting):
        look(person, at(5), 'menu')
    card_request(back, at(5, 11), status='refunded')
    card_request(paid, at(5, 11), status='approved')
    # A receipt the owner has not approved has not paid for anything yet.
    card_request(waiting, at(5, 11), status='submitted')
    report = plans_screen(filters_for(), CATALOGS['en'], with_viewers=True)
    assert {row['name']: (row['started'], row['paid']) for row in report['viewers']} == {
        'Card back': (True, False), 'Card paid': (True, True), 'Card waiting': (True, False)}
    assert (report['started'], report['paid']) == (3, 1)
    assert 'Refunded payments are left out' in CATALOGS['en']['plans_paid_definition']
    assert 'Stars' not in CATALOGS['en']['plans_paid_definition']


def test_the_report_is_a_few_queries_however_many_people_looked(september, django_assert_max_num_queries):
    for number in range(60):
        person = Account.objects.create(telegram_user_id=986300 + number, display_name=f'Person {number}')
        look(person, at(12, number % 24), 'menu')
    with django_assert_max_num_queries(8):
        report = plans_screen(filters_for(), CATALOGS['en'], with_viewers=True)
    assert report['people'] == 64 and len(report['viewers']) == 50, 'the list stops at 50'


PAGE = '/ops/analytics/plans?date_from=2026-09-01&date_to=2026-10-01'


@pytest.mark.parametrize('lang', ['en', 'uz', 'ru'])
def test_the_admin_shows_the_plans_screen_in_each_language(september, lang):
    client, _ = staff_client()
    client.cookies[ZONE_COOKIE] = 'Asia/Tashkent'
    response = client.get(f'{PAGE}&lang={lang}')
    assert response.status_code == 200
    page = response.content.decode()
    t = CATALOGS[lang]
    for key in ('plans_screen', 'plans_people', 'plans_views', 'plans_started', 'plans_paid', 'plans_by_source',
                'plans_by_plan', 'plans_viewers', 'plans_last_view', 'plans_from_menu', 'plans_from_account',
                'plans_payment_paid', 'plans_payment_started'):
        assert t[key] in page, key
    shown = response.context['plans_screen']
    # The report's days, and the times shown, are the computer's own (Tashkent here).
    assert (shown['views'], shown['people'], shown['started'], shown['paid']) == (6, 4, 3, 2)
    aziza = september['Aziza']
    assert f'href="/ops/users/{aziza.id}?lang={lang}"' in page and 'Dilnoza' in page and '@bekzod' in page
    assert '09 Sep 2026 · 01:30' in page, 'Eldor’s last look, 20:30 UTC, in Tashkent'
    assert t['plans_of_people'].format(n=50) in page
    assert 'data-testid="plans-screen"' in page


def test_the_payment_column_reads_naturally_in_russian_and_uzbek():
    # Russian badges agree with the column, «Оплата», not with whoever paid;
    # the Uzbek list says "newest on top" in its own words, not the English ones.
    ru, uz = CATALOGS['ru'], CATALOGS['uz']
    assert ru['plans_payment'] == 'Оплата'
    assert (ru['plans_payment_started'], ru['plans_payment_paid']) == ('Начата', 'Прошла')
    assert uz['plans_viewers_desc'].startswith('Ko‘pi bilan 50 kishi, eng so‘nggilari yuqorida.')


def test_the_plans_screen_says_when_no_one_looked(september):
    client, _ = staff_client()
    page = client.get(f'{PAGE}&lang=uz&channel=web').content.decode()
    assert CATALOGS['uz']['plans_none'] in page and 'Aziza' not in page


def test_the_plans_screen_is_for_staff_and_names_only_for_those_who_may_open_accounts(september):
    assert Client().get(PAGE).status_code == 302, 'signed out: to the sign-in page'
    support, _ = staff_client('Support')
    assert support.get(PAGE).status_code == 403
    analyst, _ = staff_client('Analyst')
    response = analyst.get(PAGE + '&lang=en')
    assert response.status_code == 200 and response.context['plans_screen']['views'] == 5
    page = response.content.decode()
    assert CATALOGS['en']['plans_identity_hidden'] in page
    for name in ('Aziza', 'Bekzod', 'Dilnoza', 'Eldor'):
        assert name not in page, name
    assert str(september['Aziza'].id) not in page
    admin, _ = staff_client()
    assert 'Aziza' in admin.get(PAGE + '&lang=en').content.decode()
    # Finance follows who pays after looking, as Analysts do.
    finance, _ = staff_client('Finance')
    assert finance.get(PAGE).status_code == 200


def test_the_plans_screen_has_its_own_analytics_tab(september):
    """Found at a glance beside the other reports, not at the foot of two of them."""
    admin, _ = staff_client()
    for lang in ('en', 'uz', 'ru'):
        page = admin.get(f'{PAGE}&lang={lang}')
        tabs = [(tab['label'], tab['url'].split('?')[0], tab['active']) for tab in page.context['analytics_tabs']]
        assert (CATALOGS[lang]['plans_screen'], '/ops/analytics/plans', True) in tabs
        assert [url for _, url, _ in tabs].index('/ops/analytics/plans') == 3, 'after Engagement'
        assert CATALOGS[lang]['plans_screen_desc'] in page.content.decode(), 'the page says what it shows'
    for other in ('engagement', 'acquisition'):
        response = admin.get(PAGE.replace('/plans?', f'/{other}?'))
        assert response.status_code == 200 and 'data-testid="plans-screen"' not in response.content.decode()
        assert '/ops/analytics/plans?' in response.content.decode(), 'its tab is there to open'
