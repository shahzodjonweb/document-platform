"""A CV's files waiting their turn with the reader, in the chat: one message that becomes the review.

The owner asked for a queue instead of "try again". The bot reads no file: an
upload for a CV queues its read (apps/studio/cv/reads.py), and while one of a
CV's files still waits, the chat waits too ('cv_wait'). One message says where
the files are in the queue ("2 files ahead of you", "You're next", "Reading
now") and, once they are read, becomes the review, or the question or refusal
in its place. Files and notes sent meanwhile join the same CV; /start or
Cancel ends the wait; a wait past ten minutes says so, with Try again to look
again. These tests run the reads as production does, queued and read only by
the reader, which the test runs by hand (reads.next_read), and take the bot's
looks by hand too (telegram.local.look_local, as the bot's loop takes one
every two seconds). Jobs still run as they are submitted. Everyone in them is
fictional (example.com contacts).
"""
import time

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.commerce.models import LocalBotMessage
from apps.core.models import BotConversation, FileAsset, Job
from apps.core.services import upload_file
from apps.studio import extraction
from apps.studio.cv import reads
from apps.studio.domain import CV
from apps.studio.models import CvSourceRead, GenerationDraft
from operations.integrations import save_config
from telegram.errors import COPY as ERRORS
from telegram.local import dispatch_local, look_local
from telegram.ux_copy import LOCALES, TOOL_NAMES, UX, counted
from tests.test_bot_cv import cv, image, model, screen, state  # noqa: F401
from tests.test_bot_cv_sources import (another_customer, choose, feed_two, nameless_pdf, outbound, reading, send,
                                       speak, upload)
from tests.test_bot_generation import customer, latest, tap  # noqa: F401
from tests.test_cv_content import BRIEF
from tests.test_cv_sources import blank_pdf, one_column_pdf

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]

EN = UX['en']


@pytest.fixture
def queued(monkeypatch):
    """The reads as in production: a file is queued as it is uploaded, and only the reader reads it.

    Only the reads: settings.LOCAL_SYNC_JOBS still runs a job as it is
    submitted, so a CV can be made once its files are read.
    """
    from django.conf import settings as django_settings

    class Settings:
        LOCAL_SYNC_JOBS = False

        def __getattr__(self, name):
            return getattr(django_settings, name)
    monkeypatch.setattr(reads, 'settings', Settings())


def look(account):
    """The bot's loop looking at the chat once: the chat as it reads after."""
    return look_local(account)


def waiting(account):
    """The chat's newest message from the bot: (text, button labels)."""
    message = LocalBotMessage.objects.filter(account=account, direction='outbound').latest('created_at')
    return message.text, [button['label'] for row in message.buttons for button in row]


def wait(account):
    return BotConversation.objects.get(pk=account.telegram_user_id).prompt


def wait_back(account, **seconds):
    """The wait as if what it notes (its start, its last redraw) had happened `seconds` earlier."""
    prompt = wait(account)
    for key, value in seconds.items():
        prompt[key] = float(prompt[key]) - value
    BotConversation.objects.filter(pk=account.telegram_user_id).update(prompt=prompt)


def queued_for(owner, count):
    """Another customer's CV files, uploaded on the web before this chat's: their reads are queued first."""
    return [upload_file(owner, SimpleUploadedFile(f'other-{index}.pdf', one_column_pdf()), 'web', purpose='cv_source')
            for index in range(count)]


# --- One waiting message, which becomes the review ---------------------------------------------

def test_files_waiting_for_the_reader_show_one_message_that_becomes_the_review(customer, queued):
    save_config('ai', {'mode': 'local_fixture'})
    choose(customer, 'cv_mode_file')
    before = outbound(customer)
    words, shown = screen(send(customer, 'old-cv.pdf', one_column_pdf(), caption='Looking for a lead engineer role'))
    old = FileAsset.objects.get(account=customer, name='old-cv.pdf')
    # "Preparing…" became the waiting message: one message, saying the file waits and nothing is ahead of it.
    assert outbound(customer) == before + 1
    assert words == (f'<b>{TOOL_NAMES[CV]["en"]}</b>\n{EN["cv_wait_one"]}\n📎 From: old-cv.pdf\n{EN["cv_wait_next"]}\n\n'
                     f'<i>{EN["cv_wait_hint"]}</i>'), words
    assert shown == [EN['cancel_button']]
    assert state(customer)[0] == 'cv_wait' and wait(customer)['then'] == 'build'
    assert wait(customer)['notes'] == ['Looking for a lead engineer role'] and wait(customer)['source_ids'] == [str(old.id)]
    assert CvSourceRead.objects.get(asset=old).status == 'queued'
    assert not GenerationDraft.objects.filter(account=customer).exists()
    # Looked at again while it still waits: the same message, unchanged.
    look(customer)
    assert waiting(customer)[0] == words and outbound(customer) == before + 1
    # Read by the reader, the next look makes the CV: the waiting message is its review.
    assert reads.next_read()
    words, shown = screen(look(customer))
    assert outbound(customer) == before + 1, 'the waiting message became the review'
    assert '📄 Timur Rakhimov' in words and '\n📎 From: old-cv.pdf\n' in words, words
    assert '📝 Notes: “Looking for a lead engineer role”' in words and shown[0] == '✨ Generate'
    data = latest(customer, CV)
    assert data['source_ids'] == [str(old.id)] and data['prompt'] == 'Looking for a lead engineer role'
    # The review keeps when the file came, so one more sent moments later joins the CV (cv_takes_more).
    assert state(customer)[0] == 'cv_review' and state(customer)[1]['draft_id'] == str(cv(customer).id)
    assert {'files_at', 'drawn_at'} <= set(state(customer)[1])
    # The CV is made from it as from any review.
    tap(customer, look(customer), 'Generate')
    assert Job.objects.get(account=customer, feature_id=CV).status == 'succeeded'


def test_the_waiting_message_says_where_the_files_are_in_the_queue_and_moves_with_it(customer, model, queued,
                                                                                      monkeypatch):
    monkeypatch.setattr('telegram.bot.CV_WAIT_EDIT', 30)
    other = another_customer()
    queued_for(other, 2)
    choose(customer, 'cv_mode_file')
    words, _ = screen(send(customer, 'old-cv.pdf', one_column_pdf()))
    # The accounts take turns: one of the other customer's two files is ahead of this one, not both.
    assert '\n🕐 1 file ahead of you\n' in words, words
    # The reader reads the other customer's first file: this one is next. A place is said
    # again at most every CV_WAIT_EDIT seconds, never on every look.
    assert reads.next_read()
    look(customer)
    assert '\n🕐 1 file ahead of you\n' in waiting(customer)[0]
    wait_back(customer, shown_at=31)
    look(customer)
    assert f'\n{EN["cv_wait_next"]}\n' in waiting(customer)[0], waiting(customer)[0]
    # Its turn: it is being read now.
    taken = reads.claim()
    assert taken.asset.name == 'old-cv.pdf'
    wait_back(customer, shown_at=31)
    look(customer)
    assert f'\n{EN["cv_wait_now"]}\n' in waiting(customer)[0], waiting(customer)[0]
    reads.perform(taken)
    words, _ = screen(look(customer))
    assert '📄 Timur Rakhimov' in words and state(customer)[0] == 'cv_review', words
    # The other customer's second file is still queued for its turn.
    assert CvSourceRead.objects.filter(account=other, status='queued').count() == 1


@pytest.mark.parametrize('locale', LOCALES)
def test_the_waiting_message_in_every_language(customer, model, queued, locale):
    speak(customer, locale)
    queued_for(another_customer(), 2)
    choose(customer, 'cv_mode_file', locale)
    copy = UX[locale]
    words, shown = screen(send(customer, 'old-cv.pdf', one_column_pdf()))
    assert copy['cv_wait_one'] in words and copy['cv_wait_hint'] in words, words
    assert copy['cv_wait_ahead'].format(files=counted(locale, 1, 'file')) in words, words
    assert shown == [copy['cancel_button']]
    # Two files of one CV are "files"; the counted file is plural-safe in Russian and Uzbek.
    send(customer, 'more.pdf', nameless_pdf())
    words, _ = waiting(customer)
    assert copy['cv_wait_many'] in words and words.startswith(copy['cv_files_added']), words


# --- Joining the wait -------------------------------------------------------------------------

def test_files_and_notes_sent_while_waiting_join_the_same_cv(customer, model, queued):
    choose(customer, 'cv_mode_file')
    send(customer, 'old-cv.pdf', one_column_pdf(), caption='Lead engineer roles')
    before = outbound(customer)
    # Words: more of the notes, said on the waiting message, which stays the one message.
    dispatch_local(customer, text='Target employer: Example Motors')
    words, _ = waiting(customer)
    assert outbound(customer) == before and words.startswith(EN['cv_notes_added'] + '\n\n'), words
    assert wait(customer)['notes'] == ['Lead engineer roles', 'Target employer: Example Motors']
    # Another file: one more of the CV's files, said the same way.
    send(customer, 'more.pdf', nameless_pdf(), caption='Add the 2018 job too')
    words, _ = waiting(customer)
    old, more = (FileAsset.objects.get(account=customer, name=name) for name in ('old-cv.pdf', 'more.pdf'))
    assert outbound(customer) == before and words.startswith(EN['cv_files_added'] + '\n\n'), words
    assert EN['cv_wait_many'] in words and '📎 From: old-cv.pdf, more.pdf' in words, words
    assert wait(customer)['source_ids'] == [str(old.id), str(more.id)]
    # A file its way does not take is said there, and the wait goes on.
    send(customer, 'table.xlsx', b'PK\x03\x04 not a workbook')
    assert waiting(customer)[0].startswith(ERRORS['en']['cv_file_kind']) and state(customer)[0] == 'cv_wait'
    assert not FileAsset.objects.filter(account=customer, name='table.xlsx').exists()
    # One read is not enough: the CV is made once both are read, from both, with every note.
    assert reads.next_read()
    look(customer)
    assert state(customer)[0] == 'cv_wait' and not GenerationDraft.objects.filter(account=customer).exists()
    assert reads.next_read()
    words, _ = screen(look(customer))
    data = latest(customer, CV)
    assert outbound(customer) == before and '📄 Timur Rakhimov' in words, words
    assert data['source_ids'] == [str(old.id), str(more.id)]
    assert data['prompt'] == 'Lead engineer roles\nTarget employer: Example Motors\nAdd the 2018 job too'
    assert GenerationDraft.objects.filter(account=customer).count() == 1


def test_a_file_sent_on_the_review_waits_for_the_reader_and_joins_the_cv_on_it(customer, model, queued):
    choose(customer, 'cv_mode_file')
    send(customer, 'old-cv.pdf', one_column_pdf())
    reads.next_read()
    look(customer)
    draft = cv(customer)
    # A second file moments after the first, the review on screen: one more of its files, read in its turn.
    before = outbound(customer)
    words, _ = screen(send(customer, 'more.pdf', nameless_pdf()))
    old, more = (FileAsset.objects.get(account=customer, name=name) for name in ('old-cv.pdf', 'more.pdf'))
    assert EN['cv_wait_many'] in words and '📎 From: old-cv.pdf, more.pdf' in words, words
    assert state(customer)[0] == 'cv_wait' and wait(customer)['then'] == 'add' and wait(customer)['added'] == [str(more.id)]
    assert reads.next_read()
    words, _ = screen(look(customer))
    assert outbound(customer) == before + 1 and words.startswith(EN['cv_files_added']), words
    assert cv(customer).id == draft.id and latest(customer, CV)['source_ids'] == [str(old.id), str(more.id)]
    assert state(customer)[0] == 'cv_review'


def test_a_language_tapped_on_the_old_review_while_its_new_file_waits_keeps_the_wait(customer, model, queued):
    choose(customer, 'cv_mode_file')
    send(customer, 'old-cv.pdf', one_column_pdf())
    reads.next_read()
    review = look(customer)
    send(customer, 'more.pdf', nameless_pdf())
    # The review above is redrawn in Russian; the file sent after it still joins the CV once it is read.
    tap(customer, review, '🇷🇺')
    assert state(customer)[0] == 'cv_wait' and wait(customer)['then'] == 'add'
    reads.next_read()
    words, _ = screen(look(customer))
    old, more = (FileAsset.objects.get(account=customer, name=name) for name in ('old-cv.pdf', 'more.pdf'))
    data = latest(customer, CV)
    assert words.startswith(EN['cv_files_added']) and data['source_ids'] == [str(old.id), str(more.id)], words
    assert data['output_locale'] == 'ru' and state(customer)[0] == 'cv_review'


def test_a_photo_sent_first_is_known_for_the_portrait_or_a_page_once_it_is_read(customer, model, queued, monkeypatch):
    # The reader finds no text in the photo: it is the CV's portrait, as the first screen always took it.
    monkeypatch.setattr(extraction, 'read_cv', lambda path, kind, **_: {
        'pages': [{'page': 1, 'text': '', 'ocr': True}], 'names': [], 'ocr_pages': 1, 'ocr_skipped': 0})
    dispatch_local(customer, text='/cv')
    words, _ = screen(dispatch_local(customer, uploaded=image()))
    me = FileAsset.objects.get(account=customer, name='me.jpg')
    assert EN['cv_wait_one'] in words and wait(customer)['then'] == 'photo', words
    reads.next_read()
    words, _ = screen(look(customer))
    assert words.startswith(EN['cv_photo_kept_choose']) and EN['cv_choose_ask'] in words, words
    assert state(customer) == ('cv_choose', {'feature_id': CV, 'portrait_asset_id': str(me.id)})
    # A description written while it was read is its caption: the CV is written from it, with the photo.
    dispatch_local(customer, text='/cv')
    dispatch_local(customer, uploaded=image('portrait.jpg'))
    portrait = FileAsset.objects.get(account=customer, name='portrait.jpg')
    dispatch_local(customer, text=BRIEF)
    assert waiting(customer)[0].startswith(EN['cv_notes_added'])
    reads.next_read()
    words, _ = screen(look(customer))
    data = latest(customer, CV)
    assert '📄 Dilnoza Karimova' in words and EN['cv_photo_line'] in words, words
    assert data['options']['portrait_asset_id'] == str(portrait.id) and data['prompt'] == BRIEF


# --- What the reader could not read ---------------------------------------------------------------

def test_a_failed_read_is_a_file_not_read_and_nothing_read_is_said_so(customer, model, queued):
    choose(customer, 'cv_mode_file')
    send(customer, 'old-cv.pdf', one_column_pdf())
    send(customer, 'scan.pdf', one_column_pdf())
    scan = FileAsset.objects.get(account=customer, name='scan.pdf')
    # The reader reads the first and fails on the second (its time ran out).
    reads.perform(reads.claim())
    failing = reads.claim()
    assert failing.asset_id == scan.id and reads.finish(failing, reads.FAILED, error='read_timeout')
    words, _ = screen(look(customer))
    assert '📄 Timur Rakhimov' in words and EN['cv_unread'].format(what='1 file') in words, words
    assert latest(customer, CV)['cv_unread'] == [{'asset_id': str(scan.id), 'pages': 1, 'whole': True}]
    # A file the reader could not read at all, alone: nothing to make a CV of, and the ways on.
    choose(customer, 'cv_mode_file')
    send(customer, 'broken.pdf', one_column_pdf())
    reads.finish(reads.claim(), reads.FAILED, error='source_extraction_failed')
    words, shown = screen(look(customer))
    assert ERRORS['en']['cv_file_unreadable'] in words, words
    assert shown == [EN['cv_send_another'], EN['cv_write_instead'], EN['home']]
    # And one read with no words in it, as before the queue.
    send(customer, 'blank.pdf', blank_pdf())
    reads.next_read()
    words, _ = screen(look(customer))
    assert ERRORS['en']['cv_file_unreadable'] in words and state(customer)[0] == 'cv_source', words


# --- Ending the wait ------------------------------------------------------------------------------

def test_start_or_cancel_ends_the_wait_and_the_read_makes_no_cv(customer, model, queued):
    choose(customer, 'cv_mode_file')
    waited = send(customer, 'old-cv.pdf', one_column_pdf())
    shown_then = waiting(customer)[0]
    menu = dispatch_local(customer, text='/start')
    assert state(customer) == ('', {}) and TOOL_NAMES[CV]['en'] in str(screen(menu)[1])
    reads.next_read()
    look(customer)
    assert not GenerationDraft.objects.filter(account=customer).exists()
    assert TOOL_NAMES[CV]['en'] in str(screen(look(customer))[1]), 'the menu stays the newest screen'
    assert LocalBotMessage.objects.filter(account=customer, text=shown_then).exists()
    # Cancel on the waiting message: it becomes the menu, and the wait is over.
    choose(customer, 'cv_mode_file')
    waited = send(customer, 'old-cv.pdf', one_column_pdf())
    words, _ = screen(tap(customer, waited, EN['cancel_button']))
    assert state(customer) == ('', {}) and words.startswith('<b>👋 PDF Master</b>'), words
    reads.next_read()
    look(customer)
    assert not GenerationDraft.objects.filter(account=customer).exists()


def test_a_wait_past_ten_minutes_says_so_and_try_again_looks_again_without_sending_again(customer, model, queued):
    choose(customer, 'cv_mode_file')
    send(customer, 'old-cv.pdf', one_column_pdf())
    wait_back(customer, since=11 * 60)
    words, shown = screen(look(customer))
    assert words == f'<b>{TOOL_NAMES[CV]["en"]}</b>\n{EN["cv_wait_slow"]}' and shown == [EN['cv_try_again'], EN['cancel_button']]
    assert wait(customer)['stalled'] is True
    # A stopped wait is not looked at again by itself.
    stalled = look(customer)
    assert screen(stalled)[0] == words
    # Try again while it still waits: the waiting message again, for another ten minutes.
    again = tap(customer, stalled, EN['cv_try_again'])
    assert EN['cv_wait_one'] in screen(again)[0] and wait(customer)['stalled'] is False
    wait_back(customer, since=11 * 60)
    stalled = look(customer)
    reads.next_read()
    words, _ = screen(tap(customer, stalled, EN['cv_try_again']))
    assert '📄 Timur Rakhimov' in words and state(customer)[0] == 'cv_review', words
    assert FileAsset.objects.filter(account=customer).count() == 1, 'nothing was sent again'
    assert CvSourceRead.objects.filter(account=customer).count() == 1


def test_a_look_that_fails_stops_the_wait_as_a_long_one_and_never_stops_the_others(customer, model, queued, monkeypatch):
    choose(customer, 'cv_mode_file')
    send(customer, 'old-cv.pdf', one_column_pdf())
    reads.next_read()
    from telegram import generation
    real = generation.build
    monkeypatch.setattr(generation, 'build', lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('a fault')))
    words, shown = screen(look(customer))
    assert words.endswith(EN['cv_wait_slow']) and shown[0] == EN['cv_try_again'], words
    monkeypatch.setattr(generation, 'build', real)
    words, _ = screen(tap(customer, look(customer), EN['cv_try_again']))
    assert '📄 Timur Rakhimov' in words, words


# --- The bot reads nothing, and reads inline as before where they are inline -------------------------

def test_the_bot_reads_no_file_and_waiting_for_the_reader_never_holds_up_another_chat(customer, model, monkeypatch,
                                                                                       queued):
    # The reader would take three seconds over the file: the bot never waits for it, on any thread.
    calls = []
    monkeypatch.setattr(extraction, 'read_cv', reading(calls=calls, seconds=3.0))
    monkeypatch.setattr('telegram.bot.ALBUM_SETTLE', 0)
    other = another_customer()
    choose(customer, 'cv_mode_file')
    cv_done, start_done = feed_two(customer, upload('old-cv.pdf', one_column_pdf()), other, '/start', 0.3)
    assert cv_done < 3.0 and start_done < 3.0, (cv_done, start_done)
    assert TOOL_NAMES[CV]['en'] in str(LocalBotMessage.objects.filter(account=other, direction='outbound').latest(
        'created_at').buttons), 'the other chat was shown its menu'
    assert calls == [] and EN['cv_wait_one'] in waiting(customer)[0], (calls, waiting(customer))
    # The reader reads it once, and the bot's next look makes the CV from what it kept.
    assert reads.next_read() and calls == [('MainThread', 'pdf')]
    words, _ = screen(look(customer))
    assert '📄 Timur Rakhimov' in words and calls == [('MainThread', 'pdf')], words


def test_with_reads_inline_the_review_comes_at_once_and_the_chat_never_waits(customer, model):
    choose(customer, 'cv_mode_file')
    before = outbound(customer)
    words, _ = screen(send(customer, 'old-cv.pdf', one_column_pdf()))
    assert outbound(customer) == before + 1 and '📄 Timur Rakhimov' in words and EN['cv_wait_one'] not in words, words
    assert state(customer)[0] == 'cv_review'
    assert CvSourceRead.objects.get(asset__name='old-cv.pdf').status == 'done'
    # More files moments later on the review are added at once, as before.
    words, _ = screen(send(customer, 'more.pdf', nameless_pdf()))
    assert words.startswith(EN['cv_files_added']) and state(customer)[0] == 'cv_review', words


def test_the_bot_loop_looks_at_the_waits_it_finds_and_skips_the_simulators(customer, model, queued):
    from asgiref.sync import async_to_sync
    from telegram import bot as telegram_bot
    choose(customer, 'cv_mode_file')
    send(customer, 'old-cv.pdf', one_column_pdf())
    reads.next_read()
    assert customer.telegram_user_id in telegram_bot.CV_WAITING

    class Unused:
        """The real bot: a wait on the local simulator is never its to change."""

        def __getattr__(self, name):
            raise AssertionError(f'the real bot was used: {name}')

    async def turn():
        await telegram_bot.build_dispatcher().cv_waits(Unused())
    async_to_sync(turn)()
    assert customer.telegram_user_id not in telegram_bot.CV_WAITING and state(customer)[0] == 'cv_wait'
    assert '📄 Timur Rakhimov' in screen(look(customer))[0]


@pytest.mark.parametrize('number,expected', [(0, 'next'), (3, 3)])
def test_the_place_said_is_reading_next_or_how_many(number, expected):
    from telegram.bot import cv_place
    assert cv_place({'reading': False, 'ahead': number}) == expected
    assert cv_place({'reading': True, 'ahead': 0}) == 'now'


def test_what_the_cv_is_made_of_waits_in_the_chat_never_in_a_button(customer, model, queued):
    from apps.core.models import BotCallback
    choose(customer, 'cv_mode_file')
    send(customer, 'old-cv.pdf', one_column_pdf(), caption='Notes: expected salary 9000')
    old = FileAsset.objects.get(account=customer, name='old-cv.pdf')
    assert wait(customer)['notes'] == ['Notes: expected salary 9000']
    assert not any('salary' in str(row.payload) or str(old.id) in str(row.payload)
                   for row in BotCallback.objects.filter(account=customer))
    assert time.time() - float(wait(customer)['since']) < 60


def test_the_bot_runs_the_wait_loop_beside_the_deliveries_with_the_dispatcher_it_polls_with(monkeypatch):
    import asyncio
    from aiogram import Dispatcher
    from telegram import bot as telegram_bot
    seen = {}

    async def forever(name, *args):
        seen[name] = args
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            seen[name + ' stopped'] = True
            raise

    async def polling(self, bot, **kwargs):
        seen['polled'] = self
        await asyncio.sleep(0.05)

    async def no_commands(bot):
        return None
    monkeypatch.setattr('apps.commerce.providers.telegram_config', lambda: {'token': '123456:OFFLINE_TEST_TOKEN'})
    monkeypatch.setattr('telegram.commands.install_commands', no_commands)
    monkeypatch.setattr('telegram.delivery.delivery_loop', lambda bot: forever('deliveries', bot))
    monkeypatch.setattr(telegram_bot, 'cv_wait_loop', lambda bot, dispatcher: forever('waits', bot, dispatcher))
    monkeypatch.setattr(Dispatcher, 'start_polling', polling)
    asyncio.run(telegram_bot._run_polling())
    assert seen['waits'][1] is seen['polled'] and callable(seen['polled'].cv_waits)
    assert seen['waits'][0] is seen['deliveries'][0]
    assert seen['waits stopped'] and seen['deliveries stopped']


def test_the_wait_loop_finds_the_waits_kept_before_a_restart_and_outlives_a_failed_turn(customer, monkeypatch):
    import asyncio
    from asgiref.sync import async_to_sync
    from telegram import bot as telegram_bot
    BotConversation.objects.filter(pk=customer.telegram_user_id).update(state='cv_wait', prompt={'screen': [1, 2]})
    telegram_bot.CV_WAITING.discard(customer.telegram_user_id)
    monkeypatch.setattr(telegram_bot, 'CV_WAIT_POLL', 0.01)
    turns = []

    class Dispatcher:
        async def cv_waits(self, bot):
            turns.append(customer.telegram_user_id in telegram_bot.CV_WAITING)
            if len(turns) == 1:
                raise RuntimeError('one bad turn')

    async def run():
        task = asyncio.create_task(telegram_bot.cv_wait_loop(object(), Dispatcher()))
        while len(turns) < 3:
            await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    async_to_sync(run)()
    assert turns[:3] == [True, True, True]


def test_a_webhook_run_looks_once_at_the_chats_waiting_for_the_reader(customer, monkeypatch):
    from django.core.management import call_command
    from apps.core.management.commands import dispatchtelegram
    from telegram import bot as telegram_bot
    BotConversation.objects.filter(pk=customer.telegram_user_id).update(state='cv_wait', prompt={'screen': [1, 2]})
    telegram_bot.CV_WAITING.discard(customer.telegram_user_id)
    looked = []

    class Dispatcher:
        async def feed_update(self, bot, update):
            return None

        async def cv_waits(self, bot):
            looked.append(customer.telegram_user_id in telegram_bot.CV_WAITING)
    monkeypatch.setattr(dispatchtelegram, 'build_dispatcher', Dispatcher)
    monkeypatch.setattr('apps.commerce.providers.telegram_config',
                        lambda: {'token': '123456:OFFLINE_TEST_TOKEN', 'webhook_secret': 'offline-test-secret'})
    call_command('dispatchtelegram')
    assert looked == [True]
