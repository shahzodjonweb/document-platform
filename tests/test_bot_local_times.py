"""Bot times are shown on the clock of the person's own device (account.time_zone)."""
import io
from datetime import date, datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from aiogram.methods import EditMessageText, SendMessage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from apps.commerce import manual
from apps.commerce.models import PaymentNotice, Subscription, SubscriptionPeriod
from apps.core.models import BotConversation, BotDraft, Job, Quote
from apps.core.policy import usage_snapshot
from apps.core.services import create_quote, submit_job, upload_file
from telegram.clock import day_label, local_time, offset_label, stamp
from telegram.local import dispatch_local
from tests.test_bot_generation import buttons, customer as writer, describe, tap  # noqa: F401
from tests.test_bot_manual_payments import bot_mock, customer, run_notices  # noqa: F401
from tests.test_bot_transport import Harness, account as bot_account
from tests.test_manual_payments import configure, finance, pdf, png

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]
TASHKENT = ZoneInfo('Asia/Tashkent')


def zoned(name):
    return SimpleNamespace(time_zone=name)


def test_a_time_moves_onto_the_account_clock_with_a_short_zone_label():
    moment = datetime(2026, 10, 7, 20, 30, tzinfo=dt_timezone.utc)
    assert stamp(zoned('Asia/Tashkent'), moment) == '2026-10-08 01:30 UTC+5'
    assert stamp(zoned('Asia/Kolkata'), moment, '%H:%M') == '02:00 UTC+5:30'
    assert stamp(zoned('America/St_Johns'), moment, '%H:%M') == '18:00 UTC-2:30'
    assert stamp(zoned('Asia/Tashkent'), '2026-10-07T20:30:00+00:00') == '2026-10-08 01:30 UTC+5'
    assert stamp(zoned('Asia/Tashkent'), datetime(2026, 10, 7, 20, 30)) == '2026-10-08 01:30 UTC+5', 'naive is UTC'


@pytest.mark.parametrize('name', ['UTC', '', None, 'Mars/Olympus', 'Asia', '../etc/passwd'])
def test_utc_or_an_unknown_zone_reads_as_utc(name):
    moment = datetime(2026, 10, 7, 20, 30, tzinfo=dt_timezone.utc)
    assert stamp(zoned(name), moment) == '2026-10-07 20:30 UTC'
    assert offset_label(local_time(zoned(name), moment)) == 'UTC'


def approved(customer):
    configure()
    payment = manual.attach_receipt(customer, manual.create(customer, 'premium')[0].id, png())
    PaymentNotice.objects.all().delete()
    manual.approve(payment.id, finance())
    # Late evening in UTC is already the next day in Tashkent.
    ends = (timezone.now() + timedelta(days=10)).replace(hour=20, minute=30, second=0, microsecond=0)
    Subscription.objects.filter(account=customer).update(current_period_end=ends)
    SubscriptionPeriod.objects.filter(account=customer).update(ends_at=ends)
    return ends


def test_subscription_screens_show_the_end_on_the_customer_clock(customer):
    customer.time_zone = 'Asia/Tashkent'
    customer.save(update_fields=['time_zone'])
    ends = approved(customer)
    local = f'{ends.astimezone(TASHKENT):%Y-%m-%d %H:%M} UTC+5'
    text = dispatch_local(customer, text='/subscription')['messages'][-1]['text']
    assert local in text and f'{ends:%Y-%m-%d %H:%M}' not in text


def test_an_unknown_zone_keeps_the_subscription_end_in_utc(customer):
    customer.time_zone = 'Mars/Olympus'
    customer.save(update_fields=['time_zone'])
    ends = approved(customer)
    text = dispatch_local(customer, text='/subscription')['messages'][-1]['text']
    assert f'{ends:%Y-%m-%d %H:%M} UTC' in text and 'UTC+' not in text


def test_the_approval_message_dates_the_end_on_the_customer_clock(customer):
    customer.time_zone = 'Asia/Tashkent'
    customer.save(update_fields=['time_zone'])
    ends = approved(customer)
    bot = bot_mock()
    run_notices(bot)
    text = bot.send_message.await_args.args[1]
    assert ends.astimezone(TASHKENT).strftime('%d.%m.%Y') in text and ends.strftime('%d.%m.%Y') not in text


def test_the_account_screen_shows_the_reset_on_the_customer_clock(customer):
    customer.time_zone = 'Asia/Tashkent'
    customer.save(update_fields=['time_zone'])
    text = dispatch_local(customer, text='/account')['messages'][-1]['text']
    resets = usage_snapshot(customer)['resets_at']
    assert f'{resets.astimezone(TASHKENT):%Y-%m-%d %H:%M} UTC+5' in text and ' UTC\n' not in text
    assert f'{resets.astimezone(TASHKENT):%H:%M}' == '00:00' and resets.astimezone(TASHKENT).weekday() == 0, 'Monday 00:00'
    assert 'AI documents this week: 0 / 5' in text and 'File tools this week: 0 / 15' in text and 'Edits per file: 3' in text
    customer.time_zone = 'Europe/London'
    customer.save(update_fields=['time_zone'])
    text = dispatch_local(customer, text='/account')['messages'][-1]['text']
    assert f'{resets.astimezone(ZoneInfo("Europe/London")):%Y-%m-%d %H:%M}' in text, 'the same moment, on another clock'


def test_a_quote_expiry_is_shown_on_the_customer_clock():
    owner = bot_account()
    owner.time_zone = 'Asia/Tashkent'
    owner.save(update_fields=['time_zone'])
    harness = Harness()
    picture = io.BytesIO()
    Image.new('RGB', (60, 90), 'blue').save(picture, format='PNG')
    harness.document('image', picture.getvalue(), name='picture.png')
    quote = BotDraft.objects.get(account=owner).quote
    shown = [call.text for call in harness.session.calls if isinstance(call, (SendMessage, EditMessageText))]
    assert any(f'{quote.expires_at.astimezone(TASHKENT):%H:%M} UTC+5' in text for text in shown), shown
    assert not any('(UTC)' in text for text in shown)


def test_the_renewal_reminder_dates_the_end_on_the_customer_clock(customer):
    customer.time_zone = 'Asia/Tashkent'
    customer.save(update_fields=['time_zone'])
    ends = approved(customer)
    PaymentNotice.objects.all().delete()
    manual.housekeeping(now=ends - timedelta(days=1))
    bot = bot_mock()
    run_notices(bot)
    text = bot.send_message.await_args.args[1]
    assert ends.astimezone(TASHKENT).strftime('%d.%m.%Y') in text and ends.strftime('%d.%m.%Y') not in text


def test_recent_tasks_are_listed_on_the_customer_clock(customer):
    customer.time_zone = 'Asia/Tashkent'
    customer.save(update_fields=['time_zone'])
    asset = upload_file(customer, SimpleUploadedFile('source.pdf', pdf()))
    job, _ = submit_job(customer, create_quote(customer, 'pdf.rotate', [str(asset.id)], {'angle': 90}).id, 'local-times')
    started = datetime(2026, 10, 7, 20, 30, tzinfo=dt_timezone.utc)
    Job.objects.filter(pk=job.pk).update(created_at=started)
    labels = [button['label'] for button in buttons(dispatch_local(customer, text='/myfiles'))]
    assert any('10/08 01:30' in label for label in labels) and not any('10/07 20:30' in label for label in labels), labels


def test_an_ai_review_expiry_is_shown_on_the_customer_clock(writer):
    writer.time_zone = 'Asia/Tashkent'
    writer.save(update_fields=['time_zone'])
    review = describe(writer, 'A one page introduction to tidal energy.')['messages'][-1]['text']
    quote = Quote.objects.filter(account=writer).latest('created_at')
    assert f'{quote.expires_at.astimezone(TASHKENT):%Y-%m-%d %H:%M} UTC+5' in review, review


@pytest.mark.parametrize('locale,label,september,next_year', [
    ('en', '31 Oct', '5 Sep', '5 Jan {y}'), ('uz', '31-oktabr', '5-sentabr', '{y}-yil 5-yanvar'),
    ('ru', '31 октября', '5 сентября', '5 января {y}')])
def test_a_day_is_named_as_the_language_writes_it_with_the_year_only_when_it_is_not_this_one(locale, label, september, next_year):
    """A discount's last day on the plans and payment screens: '31 Oct',
    '31-oktabr', '31 октября'. The year is added only when it is not the
    current Tashkent year, each language its own way ('5 Jan 2027',
    '2027-yil 5-yanvar', '5 января 2027'), so a discount ending this month
    needs none. The bot spells it as apps.commerce.pricing does, the one
    table the admin panel and the web app share; 'Sep', never 'Sept'."""
    from apps.commerce import pricing
    year = datetime.now(TASHKENT).year
    assert day_label(f'{year}-10-31', locale) == label
    assert day_label(date(year, 10, 31), locale) == label
    assert day_label(date(year, 9, 5), locale) == september
    assert day_label(date(year + 1, 1, 5), locale) == next_year.format(y=year + 1)
    assert pricing.day_label(date(year + 1, 1, 5), locale) == day_label(date(year + 1, 1, 5), locale)
    # A moment is read on the Tashkent clock: late evening in UTC is the next day there.
    assert day_label(datetime(year, 10, 30, 20, 30, tzinfo=dt_timezone.utc), locale) == label
    assert day_label(datetime(year, 10, 30, 20, 30), locale) == label, 'naive is UTC'
    assert day_label(f'{year}-10-31', 'xx') == day_label(f'{year}-10-31', 'en')
    with pytest.raises((TypeError, ValueError)):
        day_label('31 Oct', locale)


@pytest.mark.parametrize('name', ['UTC', '', 'Mars/Olympus'])
@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_a_reset_on_an_unknown_clock_reads_monday_in_tashkent(name, locale):
    """Every account starts on UTC, and the web app is what moves it, so the
    reset of a Telegram-only account was shown as '2026-10-18 19:00 UTC': a
    Sunday evening, for a week that starts on Monday in Tashkent."""
    from apps.core.allowance import week_bounds
    from apps.core.errors import DomainError
    from telegram.clock import week_reset, zone_known
    from telegram.errors import WEEK_START, bot_error
    resets = week_bounds()[1]
    reader = SimpleNamespace(time_zone=name, locale=locale)
    assert not zone_known(reader)
    assert week_reset(reader, resets) == WEEK_START[locale]
    refusal = bot_error(DomainError('weekly_ai_limit', 429, {'limit': 5, 'used': 5, 'resets_at': resets.isoformat()}),
                        locale, reader)
    assert WEEK_START[locale] in refusal and 'UTC' not in refusal
    tashkent = SimpleNamespace(time_zone='Asia/Tashkent', locale=locale)
    assert zone_known(tashkent) and week_reset(tashkent, resets) == f'{resets.astimezone(TASHKENT):%Y-%m-%d} 00:00 UTC+5'


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_telegram_only_screens_show_the_week_start_rather_than_a_utc_time(customer, locale):
    from operations import plans as plan_settings
    from telegram.bot import COPY as BOT_COPY
    from telegram.errors import WEEK_START
    from tests.test_bot_generation import tap
    customer.locale = locale
    customer.save(update_fields=['locale'])
    BotConversation.objects.filter(pk=customer.telegram_user_id).update(locale=locale)
    assert customer.time_zone == 'UTC', 'never opened the web app'
    account = dispatch_local(customer, text='/account')['messages'][-1]['text']
    assert f'{BOT_COPY[locale]["resets"]}: {WEEK_START[locale]}' in account and ' UTC' not in account
    # A file tool at the week's limit says when the week starts again, and
    # does not say "nothing counts until you tap Start" with no Start to tap.
    plan_settings.save('free', {'weekly_file_jobs': 1})
    sent = dispatch_local(customer, uploaded=SimpleUploadedFile('notes.pdf', pdf(), 'application/pdf'))
    screen = lambda result: [m for m in result['messages'] if m['direction'] == 'outbound'][-1]
    ready = screen(tap(customer, sent, '🗜'))
    assert BOT_COPY[locale]['tap_to_run'] in ready['text']
    asset = upload_file(customer, SimpleUploadedFile('other.pdf', pdf(), 'application/pdf'))
    submit_job(customer, create_quote(customer, 'pdf.compress', [str(asset.id)], {}).id, 'fills-the-week')
    full = screen(dispatch_local(customer, text='/settings'))
    hint = BOT_COPY[locale]['files_week_hint'].format(when=WEEK_START[locale])
    assert hint in full['text']
    assert BOT_COPY[locale]['tap_to_run'] not in full['text']
    assert BOT_COPY[locale]['plans'] in [button['label'] for row in full['buttons'] for button in row]
