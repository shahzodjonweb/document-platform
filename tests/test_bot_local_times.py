"""Bot times are shown on the clock of the person's own device (account.time_zone)."""
import io
from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from aiogram.methods import EditMessageText, SendMessage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from apps.commerce import manual
from apps.commerce.models import PaymentNotice, Subscription, SubscriptionPeriod
from apps.core.models import BotDraft, Job, Quote
from apps.core.policy import usage_snapshot
from apps.core.services import create_quote, submit_job, upload_file
from telegram.clock import local_time, offset_label, stamp
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
    assert local in dispatch_local(customer, text='/changeplan free')['messages'][-1]['text']


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


def test_renewal_controls_and_the_reminder_date_the_end_on_the_customer_clock(customer):
    customer.time_zone = 'Asia/Tashkent'
    customer.save(update_fields=['time_zone'])
    ends = approved(customer)
    local = f'{ends.astimezone(TASHKENT):%Y-%m-%d %H:%M} UTC+5'
    Subscription.objects.filter(account=customer).update(renewal_enabled=True)
    confirm = tap(customer, dispatch_local(customer, text='/subscription'), 'renewal off')
    assert local in confirm['messages'][-1]['text']
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
