"""Sending posts (telegram/posts.py): paced, durable, never twice."""
import asyncio
import io
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import BufferedInputFile
from django.utils import timezone
from PIL import Image

from apps.core import posts
from apps.core.models import Account, Post, PostRecipient
from telegram import posts as sender

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    slept = []

    async def sleep(seconds):
        slept.append(seconds)
    monkeypatch.setattr(sender.asyncio, 'sleep', sleep)
    return slept


def people(count, locale='en'):
    first = Account.objects.count()
    return [Account.objects.create(telegram_user_id=5000 + n, username=f'reader_{n:03}', locale=locale)
            for n in range(first, first + count)]


def png():
    out = io.BytesIO()
    Image.new('RGB', (40, 30), 'teal').save(out, 'PNG')
    return out.getvalue()


def sent(count=3, **kwargs):
    people(count, kwargs.pop('locale', 'en'))
    post = posts.create(None, text=kwargs.pop('text', 'Big news <b>today</b>'), audience_kind='everyone', **kwargs)
    return posts.start(post.pk)


def bot(**methods):
    reply = Mock(message_id=77, photo=None)
    return Mock(send_message=AsyncMock(return_value=reply), send_photo=AsyncMock(return_value=reply), **methods)


def rows(post):
    return list(PostRecipient.objects.filter(post=post).order_by('created_at', 'account__telegram_user_id'))


def test_a_text_post_goes_to_everyone_once_as_plain_text_with_its_button(no_pause):
    post = sent(3)
    fake = bot()
    assert asyncio.run(sender.drain(fake)) == 3
    assert asyncio.run(sender.drain(fake)) == 0
    assert fake.send_message.await_count == 3 and len(no_pause) >= 3
    assert all(0 < pause <= sender.PACE for pause in no_pause[:3]), 'never faster than the pace'
    call = fake.send_message.await_args_list[0]
    assert call.args[1] == 'Big news <b>today</b>' and call.kwargs['parse_mode'] is None
    button = call.kwargs['reply_markup'].inline_keyboard[0][0]
    first = rows(post)[0]
    assert button.text == '👌 Got it' and button.callback_data == f'post:{first.id.hex}'
    assert len(button.callback_data.encode()) <= 64
    assert {row.status for row in rows(post)} == {'delivered'} and first.message_id == 77
    post.refresh_from_db()
    assert post.status == 'sent' and post.finished_at


@pytest.mark.parametrize('locale,label', [('uz', '👌 Tushunarli'), ('ru', '👌 Понятно')])
def test_the_default_button_speaks_each_persons_language(locale, label):
    post = sent(1, locale=locale)
    fake = bot()
    asyncio.run(sender.drain(fake))
    assert fake.send_message.await_args.kwargs['reply_markup'].inline_keyboard[0][0].text == label
    assert not post.button_label


def test_a_chosen_button_label_is_used_for_everyone():
    sent(1, button_label='Seen it ✅', locale='ru')
    fake = bot()
    asyncio.run(sender.drain(fake))
    assert fake.send_message.await_args.kwargs['reply_markup'].inline_keyboard[0][0].text == 'Seen it ✅'


def test_an_image_is_uploaded_once_and_then_sent_by_telegrams_name_for_it():
    post = sent(3, image=png(), text='Caption')
    first = Mock(message_id=1, photo=[Mock(file_id='small'), Mock(file_id='AgACbig')])
    later = Mock(message_id=2, photo=None)
    fake = bot()
    fake.send_photo = AsyncMock(side_effect=[first, later, later])
    asyncio.run(sender.drain(fake))
    calls = fake.send_photo.await_args_list
    assert isinstance(calls[0].args[1], BufferedInputFile) and calls[0].kwargs['caption'] == 'Caption'
    assert calls[0].args[1].data[:3] == b'\xff\xd8\xff', 'the cleaned JPEG, not the upload'
    assert [call.args[1] for call in calls[1:]] == ['AgACbig', 'AgACbig']
    assert fake.send_message.await_count == 0
    post.refresh_from_db()
    assert post.image_file_id == 'AgACbig'


def test_without_telegrams_name_for_the_image_the_bytes_are_sent_again():
    # The local simulator answers without `photo`.
    sent(2, image=png())
    fake = bot()
    asyncio.run(sender.drain(fake))
    assert all(isinstance(call.args[1], BufferedInputFile) for call in fake.send_photo.await_args_list)


def test_a_forgotten_image_name_is_dropped_so_the_next_try_uploads():
    post = sent(1, image=png())
    Post.objects.filter(pk=post.pk).update(image_file_id='gone')
    fake = bot()
    fake.send_photo = AsyncMock(side_effect=TelegramBadRequest(method=Mock(), message='wrong file identifier'))
    asyncio.run(sender.drain(fake))
    post.refresh_from_db()
    row = rows(post)[0]
    assert post.image_file_id == '' and row.status == 'retrying' and row.attempts == 1


def test_slow_down_pauses_the_whole_post_and_it_carries_on_after():
    post = sent(3)
    fake = bot()
    fake.send_message = AsyncMock(side_effect=[Mock(message_id=1), TelegramRetryAfter(method=Mock(), message='flood', retry_after=30), Mock(message_id=3), Mock(message_id=4)])
    asyncio.run(sender.drain(fake))
    one, two, three = rows(post)
    assert (one.status, two.status, three.status) == ('delivered', 'retrying', 'pending')
    assert two.error_code == 'telegram_rate_limited' and fake.send_message.await_count == 2
    post.refresh_from_db()
    assert post.paused_until > timezone.now() + timedelta(seconds=25)
    assert asyncio.run(sender.drain(fake)) == 0, 'nothing goes while it is paused'
    Post.objects.filter(pk=post.pk).update(paused_until=timezone.now() - timedelta(seconds=1))
    PostRecipient.objects.filter(pk=two.pk).update(next_attempt_at=timezone.now())
    asyncio.run(sender.drain(fake))
    assert {row.status for row in rows(post)} == {'delivered'}


def test_blocked_and_failing_people_are_recorded_and_the_post_still_finishes():
    post = sent(2)
    fake = bot()
    fake.send_message = AsyncMock(side_effect=[TelegramForbiddenError(method=Mock(), message='blocked'), RuntimeError('down')])
    asyncio.run(sender.drain(fake))
    blocked, failing = rows(post)
    assert (blocked.status, blocked.error_code) == ('blocked', 'telegram_blocked')
    assert (failing.status, failing.attempts) == ('retrying', 1)
    assert failing.next_attempt_at > timezone.now() + timedelta(seconds=15)
    fake.send_message = AsyncMock(side_effect=RuntimeError('down'))
    for _ in range(4):
        PostRecipient.objects.filter(pk=failing.pk).update(next_attempt_at=timezone.now())
        asyncio.run(sender.drain(fake))
    failing.refresh_from_db()
    assert (failing.status, failing.attempts, failing.error_code) == ('failed', 5, 'telegram_delivery_failed')
    post.refresh_from_db()
    assert post.status == 'sent'
    counts = posts.stats(post)
    assert (counts['delivered'], counts['blocked'], counts['failed']) == (0, 1, 1)


def test_a_send_cut_off_mid_way_is_not_sent_again():
    post = sent(2)
    cut, running = rows(post)
    now = timezone.now()
    PostRecipient.objects.filter(pk=cut.pk).update(status='sending', lease_until=now - timedelta(seconds=1))
    # One whose lease is still running is another process's send.
    PostRecipient.objects.filter(pk=running.pk).update(status='sending', lease_until=now + timedelta(seconds=60))
    fake = bot()
    asyncio.run(sender.drain(fake))
    cut.refresh_from_db()
    running.refresh_from_db()
    assert (cut.status, cut.error_code) == ('failed', 'interrupted') and running.status == 'sending'
    assert fake.send_message.await_count == 0


def test_a_stopped_post_sends_nothing_more_and_a_draft_only_its_tests():
    post = sent(2)
    posts.stop(post.pk)
    fake = bot()
    asyncio.run(sender.drain(fake))
    assert fake.send_message.await_count == 0
    draft = posts.create(None, text='Draft', audience_kind='everyone')
    posts.send_test(draft.pk, 'reader_001')
    asyncio.run(sender.drain(fake))
    assert fake.send_message.await_count == 1 and fake.send_message.await_args.args[0] == 5001
    draft.refresh_from_db()
    assert draft.status == 'draft' and posts.stats(draft)['delivered'] == 0, 'tests are not counted'


def test_a_test_goes_before_a_big_post_already_on_its_way():
    sent(3)
    draft = posts.create(None, text='Draft', audience_kind='everyone')
    test = posts.send_test(draft.pk, '5002')
    assert sender.due()[0] == test.pk


def test_test_accounts_are_never_sent_to_over_the_real_network(settings):
    settings.DEBUG = True
    account = Account.objects.create(telegram_user_id=6001, is_test=True)
    post = posts.create(None, text='News', audience_kind='everyone')
    posts.start(post.pk)
    assert sender.due() == [], 'the bot loop leaves test accounts to the local simulator'
    row = PostRecipient.objects.get(post=post, account=account)

    async def run():
        real = Bot('123456:TEST_DO_NOT_USE_NETWORK')
        real.send_message = AsyncMock(side_effect=AssertionError('Network must not be contacted'))
        try:
            await sender.attempt(row.id, real)
        finally:
            await real.session.close()
    asyncio.run(run())
    row.refresh_from_db()
    assert (row.status, row.error_code) == ('blocked', 'test_account_delivery')


def test_the_local_simulator_receives_its_posts_when_the_page_asks(settings):
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    from apps.core.identity import resolve_account
    from apps.commerce.models import LocalBotMessage
    from telegram.local import posts_local
    account = resolve_account({'id': 6101, 'first_name': 'Local', 'username': 'local_reader'}, is_test=True)
    post = posts.create(None, text='Hello simulator', audience_kind='usernames', usernames='@local_reader')
    posts.start(post.pk)
    posts_local(account)
    message = LocalBotMessage.objects.get(account=account, direction='outbound')
    row = PostRecipient.objects.get(post=post)
    assert message.text == 'Hello simulator' and message.buttons[0][0]['callback_data'] == f'post:{row.id.hex}'
    assert row.status == 'delivered'
    post.refresh_from_db()
    assert post.status == 'sent'


def test_the_webhook_run_drains_until_nothing_is_due():
    sent(3)
    fake = bot()
    asyncio.run(sender.standalone_drain(fake))
    assert fake.send_message.await_count == 3


def test_the_polling_loop_survives_a_bad_turn(monkeypatch, no_pause):
    turns = []

    async def drain(bot):
        turns.append(1)
        if len(turns) == 1:
            raise RuntimeError('database went away')
        if len(turns) == 3:
            raise asyncio.CancelledError
        return 0
    monkeypatch.setattr(sender, 'drain', drain)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(sender.post_loop(SimpleNamespace()))
    assert len(turns) == 3 and no_pause == [3, 3]
