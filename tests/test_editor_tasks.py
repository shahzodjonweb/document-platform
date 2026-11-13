"""The editor lane: its queue, what it draws, and the routes that ask for it.

Pdfium runs for real through the bounded child. LibreOffice is stood in for
(`converted`) where a test only needs its PDF, or by a small script through the
real child (`soffice`); the real one is marked REQUIRES_OFFICE and listed in
tests/core_tests.txt, so CI runs it.
"""
import copy
import io
import json
import logging
import os
import signal
import subprocess
import time
import uuid
import zipfile
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path

import pytest
from django.core.management import call_command
from django.db.models import F
from django.db.models.query import QuerySet
from django.utils import timezone
from PIL import Image
from pptx import Presentation
from reportlab.pdfgen import canvas

from apps.core import storage
from apps.core.errors import DomainError
from apps.core.models import FileAsset, PagePreview
from apps.core.services import cleanup_expired, storage_path
from apps.studio import tasks
from apps.studio.domain import unpack, update_draft
from apps.studio.models import EditorTask, GenerationDraft, SlideRender
from processors import ProcessorError, sandbox
from processors.engine import office_runtime
from tests.test_deck_pins import customer, edit_section, generate, stock_photos  # noqa: F401
from tests.test_platform import account, login_client, upload

pytestmark = pytest.mark.django_db

REQUIRES_OFFICE = pytest.mark.skipif(not office_runtime()['available'], reason='No working configured LibreOffice runtime')
PRIVATE = 'Zanzibarmarker'


@pytest.fixture(autouse=True)
def lane(monkeypatch, settings):
    """The deck editor on, and tasks waiting in the queue for a runner, as in production."""
    monkeypatch.setenv('EDITOR_FLAG_DECK_EDITOR', '1')
    settings.LOCAL_SYNC_JOBS = False
    yield
    tasks.forget_office()


@pytest.fixture
def deck(customer, settings):  # noqa: F811
    settings.LOCAL_SYNC_JOBS = True
    draft, _ = generate(customer, asked=[])
    settings.LOCAL_SYNC_JOBS = False
    return draft


@pytest.fixture
def converted(monkeypatch):
    """LibreOffice as the lane sees it: a PDF of as many pages as the copy has slides. Lists each copy's slides' XML."""
    copies = []

    def convert(source, folder, slides):
        kept = Presentation(str(source))
        copies.append([slide._element for slide in kept.slides])
        assert len(copies[-1]) == slides
        folder.mkdir()
        path = folder / 'converted.pdf'
        page = canvas.Canvas(str(path), pagesize=(960, 540))
        for _ in copies[-1]:
            page.drawString(72, 300, 'A slide')
            page.showPage()
        page.save()
        return {'path': str(path), 'page_count': slides}
    monkeypatch.setattr(tasks, 'convert_deck', convert)
    return copies


def task(owner, kind=tasks.PREVIEW, **fields):
    from apps.studio.domain import pack
    return EditorTask.objects.create(account=owner, kind=kind, encrypted_payload=pack({'asset_id': str(uuid.uuid4()), 'page': 1}), **fields)


def handled(monkeypatch, kind=tasks.PREVIEW, *, result=None, raises=None, seen=None):
    def handler(row):
        if seen is not None:
            seen.append(row.pk)
        if raises:
            raise raises
        return result or {'ok': True}
    monkeypatch.setitem(tasks.HANDLERS, kind, handler)


def elapsed(row, seconds, *, kind=None, now=None):
    start = (now or timezone.now()) - timedelta(seconds=seconds + 1)
    EditorTask.objects.filter(pk=row.pk).update(status=tasks.DONE, started_at=start, finished_at=start + timedelta(seconds=seconds), spent_seconds=seconds, **({'kind': kind} if kind else {}))


def rendered(draft):
    """The next task run, and what it gave."""
    assert tasks.next_task()
    row = EditorTask.objects.filter(draft=draft).order_by('-created_at').first()
    return row, unpack(row.encrypted_result) if row.encrypted_result else None


def ask(draft):
    draft.refresh_from_db()
    return tasks.request_render(draft.account, draft.pk, draft.version)


def api_client(owner):
    return login_client(owner)


# --- Lease and runners -----------------------------------------------------------------------

def test_a_task_is_taken_under_a_lease_and_two_runners_never_hold_the_same_one():
    owner = account()
    first, second = task(owner), task(owner)
    taken = [tasks.claim(), tasks.claim()]
    assert {row.pk for row in taken} == {first.pk, second.pk}
    assert tasks.claim() is None
    assert all(row.status == tasks.RUNNING and row.lease_expires_at > timezone.now() and row.attempts == 1 for row in taken)
    assert tasks.take(taken[0]) is None, 'a runner that looked before the other took it comes away with nothing'


def test_a_runner_that_lost_its_lease_cannot_finish_a_task_another_has_taken():
    row = task(account())
    gone = tasks.claim()
    EditorTask.objects.filter(pk=row.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
    assert tasks.sweep() == 1
    again = tasks.claim()
    assert again.pk == row.pk and again.attempts == 2
    assert not tasks.finish(gone, tasks.DONE, result={'old': True})
    assert tasks.finish(again, tasks.DONE, result={'new': True})
    row.refresh_from_db()
    assert unpack(row.encrypted_result) == {'new': True}


def test_a_task_whose_runner_keeps_dying_is_failed_as_interrupted_after_three_tries():
    row = task(account())
    for attempt in range(1, tasks.MAX_ATTEMPTS + 1):
        assert tasks.claim().attempts == attempt
        EditorTask.objects.filter(pk=row.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        tasks.sweep()
    row.refresh_from_db()
    assert (row.status, row.error, row.attempts) == (tasks.FAILED, 'preview_interrupted', tasks.MAX_ATTEMPTS)
    assert row.finished_at is not None and tasks.claim() is None


def test_a_lease_still_running_is_left_alone():
    task(account())
    tasks.claim()
    assert tasks.sweep() == 0


# --- Only what was interrupted is tried again ------------------------------------------------

@pytest.mark.parametrize('code', ['processor_timeout', 'processor_failed', 'conversion_failed'])
def test_a_crash_or_a_hang_is_tried_again_and_at_last_failed_as_interrupted(monkeypatch, code):
    seen = []
    row = task(account(), tasks.RENDER)
    handled(monkeypatch, tasks.RENDER, raises=ProcessorError(code), seen=seen)
    for _ in range(tasks.MAX_ATTEMPTS):
        assert tasks.next_task()
    row.refresh_from_db()
    assert len(seen) == tasks.MAX_ATTEMPTS
    assert (row.status, row.error) == (tasks.FAILED, 'render_deck_interrupted')
    assert not tasks.next_task()


def test_after_a_crash_the_next_task_runs(monkeypatch):
    owner = account()
    bad, good = task(owner, tasks.RENDER), task(owner, created_at=timezone.now() + timedelta(seconds=1))
    seen = []

    def handler(row):
        seen.append(row.pk)
        if row.pk == bad.pk:
            raise ProcessorError('processor_timeout')
        return {'ok': True}
    monkeypatch.setitem(tasks.HANDLERS, tasks.RENDER, handler)
    monkeypatch.setitem(tasks.HANDLERS, tasks.PREVIEW, handler)
    while tasks.next_task():
        pass
    good.refresh_from_db()
    assert good.status == tasks.DONE and good.pk in seen


@pytest.mark.parametrize('failure', [DomainError('pinned_asset_expired', 409), ProcessorError('engine_unavailable'), ProcessorError('output_size_limit')])
def test_any_other_refusal_is_the_tasks_answer_and_is_not_tried_again(monkeypatch, failure):
    row = task(account())
    handled(monkeypatch, raises=failure)
    tasks.next_task()
    row.refresh_from_db()
    assert (row.status, row.error, row.attempts) == (tasks.FAILED, failure.code, 1)
    assert not tasks.next_task()


@pytest.mark.parametrize('code', ['processor_timeout', 'processor_failed'])
def test_a_customers_file_that_stalls_the_child_is_not_tried_again_and_has_a_short_allowance(monkeypatch, code):
    from apps.core.previews import preview_asset
    owner = account()
    asset = upload(owner)
    client = login_client(owner)
    url = f'/api/v1/files/{asset.id}/preview'
    assert client.get(url).status_code == 202
    asked = []

    def stalls(*args, **kwargs):
        asked.append(kwargs)
        raise ProcessorError(code)
    monkeypatch.setattr('apps.core.previews.execute_sandbox', stalls)
    assert tasks.next_task()
    row = EditorTask.objects.get()
    assert (row.status, row.error, row.attempts) == (tasks.FAILED, code, 1)
    assert len(asked) == 1 and asked[0]['timeout'] == tasks.PREVIEW_SECONDS and not tasks.next_task()
    answer = client.get(url)
    assert answer.status_code == 409 and answer.json()['error']['code'] == code
    # A request that draws for itself, with the deck editor off, keeps what it always had.
    with pytest.raises(DomainError):
        preview_asset(owner, asset.id)
    assert asked[-1]['timeout'] == 90


def test_something_unforeseen_fails_the_task_once_and_logs_nothing_of_the_customer(monkeypatch, caplog):
    row = task(account())
    handled(monkeypatch, raises=ValueError(PRIVATE))
    with caplog.at_level(logging.ERROR):
        tasks.next_task()
    row.refresh_from_db()
    assert (row.status, row.error) == (tasks.FAILED, 'editor_task_failed')
    assert PRIVATE not in caplog.text and 'ValueError' in caplog.text


# --- Coalescing and the queue's bounds -------------------------------------------------------

def test_a_newer_render_replaces_the_queued_one_and_keeps_its_place(deck):
    first = tasks.enqueue(deck.account, tasks.RENDER, {'version': 1}, draft=deck)
    before = first.created_at
    second = tasks.enqueue(deck.account, tasks.RENDER, {'version': 2}, draft=deck)
    assert second.pk == first.pk
    second.refresh_from_db()
    assert unpack(second.encrypted_payload) == {'version': 2} and second.created_at == before
    assert EditorTask.objects.filter(draft=deck).count() == 1


def test_a_render_may_wait_while_one_of_the_same_draft_runs(deck):
    first = tasks.enqueue(deck.account, tasks.RENDER, {'version': 1}, draft=deck)
    assert tasks.claim().pk == first.pk
    second = tasks.enqueue(deck.account, tasks.RENDER, {'version': 2}, draft=deck)
    assert second.pk != first.pk and second.status == tasks.QUEUED


def test_a_lost_render_is_failed_rather_than_queued_beside_a_newer_one(deck):
    tasks.enqueue(deck.account, tasks.RENDER, {'version': 1}, draft=deck)
    lost = tasks.claim()
    newer = tasks.enqueue(deck.account, tasks.RENDER, {'version': 2}, draft=deck)
    EditorTask.objects.filter(pk=lost.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
    assert tasks.sweep() == 1
    lost.refresh_from_db()
    assert (lost.status, lost.error) == (tasks.FAILED, 'render_deck_interrupted')
    assert EditorTask.objects.get(status=tasks.QUEUED).pk == newer.pk


def test_an_account_has_at_most_three_waiting_but_a_replacement_takes_no_place(deck):
    owner = deck.account
    tasks.enqueue(owner, tasks.RENDER, {'version': 1}, draft=deck)
    for page in (1, 2):
        tasks.enqueue(owner, tasks.PREVIEW, {'asset_id': 'a', 'page': page})
    with pytest.raises(DomainError) as refused:
        tasks.enqueue(owner, tasks.PREVIEW, {'asset_id': 'a', 'page': 3})
    assert (refused.value.code, refused.value.status, refused.value.retryable) == ('lane_busy', 429, True)
    tasks.enqueue(owner, tasks.RENDER, {'version': 2}, draft=deck)
    tasks.enqueue(account(43), tasks.PREVIEW, {'asset_id': 'b', 'page': 1})


def test_accounts_take_turns_and_one_customers_many_wait_behind_anothers_one():
    busy, quiet = account(), account(43)
    now = timezone.now()
    many = [task(busy, created_at=now + timedelta(seconds=number)) for number in range(3)]
    one = task(quiet, created_at=now + timedelta(seconds=10))
    order = [tasks.claim(now=now + timedelta(seconds=20 + turn)).pk for turn in range(4)]
    assert order == [many[0].pk, one.pk, many[1].pk, many[2].pk]


def test_a_task_that_has_waited_long_goes_first():
    busy, quiet = account(), account(43)
    now = timezone.now()
    old = task(busy, created_at=now - timedelta(seconds=400))
    task(quiet, created_at=now - timedelta(seconds=10))
    EditorTask.objects.create(account=busy, kind=tasks.PREVIEW, status=tasks.DONE, started_at=now, finished_at=now)
    assert tasks.claim(now=now).pk == old.pk


@pytest.mark.parametrize('kind', ['inspect', 'text_check', 'anything'])
def test_kinds_of_later_steps_are_refused_by_name_and_never_stubbed(kind):
    with pytest.raises(DomainError) as refused:
        tasks.enqueue(account(), kind, {})
    assert refused.value.code == 'editor_task_unsupported'
    assert not EditorTask.objects.exists()


def test_a_row_of_a_later_kind_fails_by_name_in_the_runner():
    row = task(account(), kind='inspect')
    assert tasks.next_task()
    row.refresh_from_db()
    assert (row.status, row.error, row.encrypted_result) == (tasks.FAILED, 'editor_task_unsupported', None)


def test_what_a_task_holds_is_encrypted():
    owner = account()
    row = tasks.enqueue(owner, tasks.PREVIEW, {'asset_id': PRIVATE, 'page': 1})
    assert PRIVATE.encode() not in bytes(row.encrypted_payload)
    tasks.finish(tasks.claim(), tasks.DONE, result={'text': PRIVATE})
    row.refresh_from_db()
    assert PRIVATE.encode() not in bytes(row.encrypted_result)


# --- Budgets ---------------------------------------------------------------------------------

def test_past_the_days_seconds_of_a_kind_an_account_is_told_the_lane_is_busy(monkeypatch):
    monkeypatch.setenv('EDITOR_BUDGET_PREVIEW', '30')
    owner, other = account(), account(43)
    elapsed(task(owner), 29)
    tasks.enqueue(owner, tasks.PREVIEW, {'asset_id': 'a', 'page': 1})
    elapsed(task(owner), 2)
    with pytest.raises(DomainError) as refused:
        tasks.enqueue(owner, tasks.PREVIEW, {'asset_id': 'a', 'page': 2})
    assert (refused.value.code, refused.value.status, refused.value.retryable) == ('lane_busy', 429, True)
    assert tasks.seconds_today(owner)[tasks.PREVIEW] == pytest.approx(31)
    tasks.enqueue(other, tasks.PREVIEW, {'asset_id': 'b', 'page': 1})


def test_one_kinds_budget_leaves_the_other_kinds(monkeypatch, deck):
    monkeypatch.setenv('EDITOR_BUDGET_PREVIEW', '1')
    elapsed(task(deck.account), 2)
    tasks.enqueue(deck.account, tasks.RENDER, {'version': 1}, draft=deck)


def test_a_paid_plan_has_its_multiple_and_free_does_not(monkeypatch, customer):  # noqa: F811
    monkeypatch.setenv('EDITOR_BUDGET_PREVIEW', '30')
    monkeypatch.setenv('EDITOR_BUDGET_PAID_MULTIPLIER', '3')
    assert customer.plan != 'free'
    elapsed(task(customer), 60)
    tasks.enqueue(customer, tasks.PREVIEW, {'asset_id': 'a', 'page': 1})
    elapsed(task(customer), 40)
    with pytest.raises(DomainError):
        tasks.enqueue(customer, tasks.PREVIEW, {'asset_id': 'a', 'page': 2})
    assert tasks.budget_of(account(43), tasks.PREVIEW) == 30


def test_the_day_starts_in_tashkent_and_gives_the_seconds_back(monkeypatch):
    monkeypatch.setenv('EDITOR_BUDGET_PREVIEW', '30')
    owner = account()
    # 18:30 UTC is 23:30 in Tashkent; an hour on, a new day has begun there.
    night = datetime(2026, 11, 2, 18, 30, tzinfo=dt_timezone.utc)
    elapsed(task(owner), 40, now=night)
    assert tasks.seconds_today(owner, night + timedelta(minutes=1))
    assert not tasks.seconds_today(owner, night + timedelta(hours=1))


def test_the_budget_counts_tasks_whose_result_was_pruned():
    owner = account()
    row = task(owner)
    elapsed(row, 40)
    EditorTask.objects.filter(pk=row.pk).update(encrypted_result=b'x')
    tasks.prune(timezone.now() + timedelta(hours=2))
    row.refresh_from_db()
    assert row.encrypted_payload is None and row.encrypted_result is None
    assert tasks.seconds_today(owner)[tasks.PREVIEW] == pytest.approx(40)


def test_every_attempt_of_a_task_that_hangs_is_charged_even_while_it_waits_again(monkeypatch):
    owner = account()
    task(owner, tasks.RENDER)

    def hangs(row):
        row.started_at -= timedelta(seconds=18)
        raise ProcessorError('processor_timeout')
    monkeypatch.setitem(tasks.HANDLERS, tasks.RENDER, hangs)
    assert tasks.next_task()
    assert EditorTask.objects.get().status == tasks.QUEUED
    assert tasks.seconds_today(owner)[tasks.RENDER] == pytest.approx(18, abs=1)
    while tasks.next_task():
        pass
    assert tasks.seconds_today(owner)[tasks.RENDER] == pytest.approx(54, abs=2)


@pytest.mark.parametrize('attempts, status', [(0, tasks.QUEUED), (tasks.MAX_ATTEMPTS - 1, tasks.FAILED)])
def test_a_lane_that_was_down_charges_no_more_than_the_lease(attempts, status):
    row = task(account(), attempts=attempts)
    tasks.claim()
    now = timezone.now()
    EditorTask.objects.filter(pk=row.pk).update(started_at=now - timedelta(hours=1), lease_expires_at=now - timedelta(minutes=57))
    assert tasks.sweep() == 1
    row.refresh_from_db()
    assert row.status == status and row.spent_seconds == tasks.LEASE_SECONDS


def test_the_admins_user_page_shows_the_accounts_seconds_in_the_lane():
    from tests.test_operations import staff_client
    owner = account()
    elapsed(task(owner), 41)
    assert {'kind': tasks.PREVIEW, 'seconds': 41, 'budget': 120} in tasks.lane_rows(owner)
    client, _ = staff_client()
    page = client.get(f'/ops/users/{owner.pk}').content.decode()
    assert 'Editor lane today' in page and '41\u00a0s of\u00a0120\u00a0s' in page


def test_the_admins_user_page_lists_documents_and_not_slide_pictures(deck, converted):
    from tests.test_operations import staff_client
    FileAsset.objects.filter(account=deck.account).update(name='a-document.pdf')
    ask(deck)
    rendered(deck)
    assert FileAsset.objects.filter(account=deck.account, metadata__kind='deck_slide').exists()
    client, _ = staff_client()
    page = client.get(f'/ops/users/{deck.account.pk}').content.decode()
    assert 'a-document.pdf' in page and 'slide.png' not in page


# --- Pruning ---------------------------------------------------------------------------------

def test_cleanup_drops_results_after_an_hour_and_rows_after_two_days():
    owner = account()
    done = task(owner)
    tasks.finish(tasks.claim(), tasks.DONE, result={'text': PRIVATE})
    recent = task(owner)
    tasks.finish(tasks.claim(), tasks.DONE, result={'text': PRIVATE})
    EditorTask.objects.filter(pk=done.pk).update(finished_at=timezone.now() - timedelta(minutes=61))
    cleanup_expired()
    done.refresh_from_db()
    recent.refresh_from_db()
    assert done.encrypted_payload is None and done.encrypted_result is None and done.status == tasks.DONE
    assert recent.encrypted_result is not None
    EditorTask.objects.filter(pk=done.pk).update(finished_at=timezone.now() - timedelta(days=3))
    cleanup_expired()
    assert not EditorTask.objects.filter(pk=done.pk).exists() and EditorTask.objects.filter(pk=recent.pk).exists()


def test_a_task_never_taken_goes_in_the_end_and_a_running_one_does_not():
    owner = account()
    never = task(owner, created_at=timezone.now() - timedelta(days=3))
    running = task(owner, status=tasks.RUNNING, created_at=timezone.now() - timedelta(days=3), started_at=timezone.now())
    tasks.prune()
    assert not EditorTask.objects.filter(pk=never.pk).exists() and EditorTask.objects.filter(pk=running.pk).exists()


# --- The runner ------------------------------------------------------------------------------

def test_the_runner_sweeps_at_start_beats_its_heart_and_stops_when_the_queue_is_done(monkeypatch, tmp_path):
    row = task(account(), status=tasks.RUNNING, attempts=1, started_at=timezone.now(), lease_expires_at=timezone.now() - timedelta(seconds=1))
    seen = []
    handled(monkeypatch, seen=seen)
    beat = tmp_path / 'beat'
    call_command('runeditor', once=True, heartbeat=str(beat))
    assert beat.exists() and seen == [row.pk]
    row.refresh_from_db()
    assert row.status == tasks.DONE


def test_sigterm_finishes_the_task_in_hand_and_takes_no_other(monkeypatch, tmp_path):
    owner = account()
    first = task(owner)
    second = task(owner, created_at=timezone.now() + timedelta(seconds=1))

    def handler(row):
        os.kill(os.getpid(), signal.SIGTERM)
        return {'ok': True}
    monkeypatch.setitem(tasks.HANDLERS, tasks.PREVIEW, handler)
    call_command('runeditor', heartbeat=str(tmp_path / 'beat'))
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.status == tasks.DONE and second.status == tasks.QUEUED


# --- render_deck -----------------------------------------------------------------------------

def test_a_render_keeps_a_picture_and_a_thumbnail_of_every_slide_by_the_drafts_clock(deck, converted):
    ask(deck)
    row, result = rendered(deck)
    assert row.status == tasks.DONE, row.error
    assert result['version'] == deck.version and [slide['index'] for slide in result['slides']] == list(range(8))
    renders = SlideRender.objects.select_related('file', 'thumb').filter(draft=deck)
    assert renders.count() == 8 and {render.key for render in renders} == {slide['key'] for slide in result['slides']}
    for render in renders:
        with Image.open(storage.local(render.file.object_key)) as large, Image.open(storage.local(render.thumb.object_key)) as small:
            assert large.size == (1280, 720) and large.format == 'PNG'
            assert small.size == (96, 54) and small.format == 'PNG'
        for asset in (render.file, render.thumb):
            assert asset.expires_at == deck.expires_at and asset.metadata['kind'] == 'deck_slide' and asset.object_key.startswith('previews/')
    assert not list(storage_path('scratch').glob('editor-*')), 'scratch is cleaned'


def test_one_edit_to_a_deck_converts_that_one_slide(deck, converted):
    ask(deck)
    _, before = rendered(deck)
    edit_section(deck.account, deck, 's5', heading='A new heading')
    ask(deck)
    _, after = rendered(deck)
    changed = [old['index'] for old, new in zip(before['slides'], after['slides']) if old['key'] != new['key']]
    assert changed == [4]
    assert [len(copied) for copied in converted] == [8, 1]
    assert SlideRender.objects.filter(draft=deck).count() == 9


def test_nothing_changed_converts_nothing_and_the_second_render_reuses_every_picture(deck, converted):
    ask(deck)
    rendered(deck)
    EditorTask.objects.filter(draft=deck).delete()
    ask(deck)
    row, result = rendered(deck)
    assert row.status == tasks.DONE and len(converted) == 1 and len(result['slides']) == 8


def test_a_slide_added_at_the_end_converts_itself_and_only_slides_that_show_the_count(deck, converted):
    ask(deck)
    _, before = rendered(deck)
    content = copy.deepcopy(unpack(GenerationDraft.objects.get(pk=deck.pk).encrypted_data)['content'])
    content['sections'].append({'id': 's9', 'heading': 'One more', 'body': 'A line\nAnother line', 'notes': '', 'layout': 'bullets', 'items': [], 'columns': [], 'image_query': ''})
    deck.refresh_from_db()
    update_draft(deck.account, deck.pk, {'version': deck.version, 'content': content})
    ask(deck)
    _, after = rendered(deck)
    assert len(after['slides']) == 9
    same = sum(old['key'] == new['key'] for old, new in zip(before['slides'], after['slides']))
    assert len(converted[-1]) == 9 - same
    assert same >= 1, 'a slide that does not say how many there are is not converted again'
    # Whatever was converted says how many there are, or is the new slide: nothing else.
    total = len(after['slides'])
    for element in converted[-1][:-1]:
        text = ''.join(element.itertext())
        assert f'/ {total:02d}' in text or f'{total:02d}' in text


def test_a_slide_moved_is_drawn_again_with_its_new_number(deck, converted):
    ask(deck)
    _, before = rendered(deck)
    content = copy.deepcopy(unpack(GenerationDraft.objects.get(pk=deck.pk).encrypted_data)['content'])
    content['sections'][3], content['sections'][4] = content['sections'][4], content['sections'][3]
    deck.refresh_from_db()
    update_draft(deck.account, deck.pk, {'version': deck.version, 'content': content})
    ask(deck)
    _, after = rendered(deck)
    keys = {slide['key'] for slide in before['slides']}
    assert {slide['index'] for slide in after['slides'] if slide['key'] not in keys} == {3, 4}


def test_a_new_renderer_draws_every_slide_again(deck, converted, monkeypatch):
    ask(deck)
    _, before = rendered(deck)
    monkeypatch.setattr('apps.studio.deck_designs.version', lambda: 'another')
    EditorTask.objects.filter(draft=deck).delete()
    ask(deck)
    _, after = rendered(deck)
    assert not {slide['key'] for slide in before['slides']} & {slide['key'] for slide in after['slides']}
    assert len(converted[-1]) == 8


def test_a_slide_says_where_its_fields_lie_and_no_word_of_them(deck, converted):
    ask(deck)
    _, result = rendered(deck)
    for slide in result['slides']:
        assert slide['fits'] and slide['letters_over'] == 0
        assert any(frame['field'] == 'heading' for frame in slide['frames'])
        for frame in slide['frames']:
            assert set(frame) == {'field', 'x', 'y', 'w', 'h'} and frame['field'] in ('heading', 'body', 'picture')
            assert -0.01 <= frame['x'] <= 1 and -0.01 <= frame['y'] <= 1 and 0 < frame['w'] <= 1.01 and 0 < frame['h'] <= 1.01
    row = SlideRender.objects.filter(draft=deck).first()
    assert row.frames and all(isinstance(value, (str, float, int)) for frame in row.frames for value in frame.values())


def test_a_brand_name_and_a_slide_number_are_never_a_field_though_the_fields_hold_their_words(tmp_path):
    from apps.studio import slides as kit
    from apps.studio.slides import ZONES
    # Whichever number a slide comes out with, its heading and its body hold it, and every heading the brand.
    sections = [{'id': f's{n}', 'heading': f'Acme {n} {n + 1} {n + 2} ways', 'body': f'We have {n} {n + 1} {n + 2} offices', 'notes': '', 'layout': 'bullets', 'items': [], 'columns': [], 'image_query': ''} for n in range(1, 11)]
    sections.append({**sections[0], 'id': 's11', 'heading': 'Acme'})
    content = {'title': 'Tides', 'questions': [], 'citations': [], 'sections': sections}
    drawn, _ = tasks.draw_slides(content, 'en', {'brand_name': 'Acme'}, {}, {}, set, tmp_path)
    assert len(drawn) >= len(sections)
    tops = {round(int(zone.top) / int(kit.SLIDE_HEIGHT), 4) for zone in (ZONES['footer'], ZONES['number'])}
    for slide in drawn:
        headings = [frame for frame in slide['frames'] if frame['field'] == 'heading']
        assert len(headings) <= 1
        assert not [frame for frame in slide['frames'] if frame['y'] in tops], slide['index']
    assert sum(1 for slide in drawn if any(frame['field'] == 'heading' for frame in slide['frames'])) >= len(sections)


def test_the_heading_is_the_box_with_the_most_of_its_words():
    from pptx.util import Inches
    from apps.studio.slide_fit import slide_frames
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    for top, words in ((1, '3'), (2, '3 ways to win'), (3, 'ways')):
        slide.shapes.add_textbox(Inches(1), Inches(top), Inches(4), Inches(0.5)).text_frame.text = words
    section = {'heading': '3 ways to win', 'body': 'Some ways', 'items': [], 'columns': [], 'layout': 'bullets'}
    frames = slide_frames('bullets', section, slide)
    assert [frame['field'] for frame in frames] == ['heading', 'body']
    assert frames[0]['y'] == pytest.approx(2 * 914400 / 6858000, abs=0.001)


def test_a_slide_with_a_picture_says_where_it_lies(customer, settings, converted, stock_photos):  # noqa: F811
    settings.LOCAL_SYNC_JOBS = True
    draft, _ = generate(customer, asked=[])
    settings.LOCAL_SYNC_JOBS = False
    ask(draft)
    row, result = rendered(draft)
    assert row.status == tasks.DONE, row.error
    pictured = {slide['index'] for slide in result['slides'] if any(frame['field'] == 'picture' for frame in slide['frames'])}
    assert 0 in pictured and 5 in pictured and 1 not in pictured


def test_a_slide_too_long_is_drawn_as_it_would_show_and_says_how_much_is_lost(deck, converted):
    edit_section(deck.account, deck, 's5', body='\n'.join(f'{PRIVATE} {"слово " * 60}{number}' for number in range(8)))
    ask(deck)
    row, result = rendered(deck)
    assert row.status == tasks.DONE
    over = result['slides'][4]
    assert not over['fits'] and over['letters_over'] > 0
    assert all(slide['fits'] for index, slide in enumerate(result['slides']) if index != 4)


def test_the_copy_keeps_only_the_slides_asked_for_their_pictures_and_their_numbers(tmp_path):
    from apps.studio.slides import render_pptx
    jpeg = io.BytesIO()
    Image.new('RGB', (800, 500), (10, 120, 200)).save(jpeg, 'JPEG')
    photo = {'jpeg': jpeg.getvalue(), 'width': 800, 'height': 500, 'provider': 'pixabay', 'id': 1, 'page_url': 'https://pixabay.com/x'}
    sections = [{'id': f's{number}', 'heading': f'Heading {number}', 'body': 'One line\nAnother line', 'notes': '', 'layout': 'bullets', 'items': [], 'columns': [], 'image_query': ''} for number in range(1, 7)]
    sections[1]['layout'] = 'image_split'
    content = {'title': 'Tides', 'questions': [], 'citations': [], 'sections': sections}
    render_pptx(content, tmp_path / 'deck.pptx', 'en', 'user_document', photos={'s2': photo})
    presentation = Presentation(str(tmp_path / 'deck.pptx'))
    tasks._only_these(presentation, {3, 5}, tmp_path / 'copy.pptx')
    kept = Presentation(str(tmp_path / 'copy.pptx'))
    assert ['Heading 4' in ''.join(slide._element.itertext()) for slide in kept.slides] == [True, False]
    assert ['Heading 6' in ''.join(slide._element.itertext()) for slide in kept.slides] == [False, True]
    with zipfile.ZipFile(tmp_path / 'copy.pptx') as archive:
        names = archive.namelist()
        assert sum(name.startswith('ppt/slides/slide') for name in names) == 2
        assert not any(name.startswith('ppt/media/') for name in names), 'the picture of a slide dropped does not reach LibreOffice'
        xml = [archive.read(name).decode() for name in names if name.startswith('ppt/slides/slide')]
    assert not any('slidenum' in text for text in xml)
    numbers = sorted(''.join(slide._element.itertext()) for slide in kept.slides)
    assert any('4' in text for text in numbers) and any('6' in text for text in numbers)


# --- What can go wrong during a render -------------------------------------------------------

def test_a_draft_deleted_mid_render_leaves_nothing(deck, monkeypatch, converted):
    ask(deck)
    real = tasks.convert_deck

    def deleting(source, folder, slides):
        made = real(source, folder, slides)
        GenerationDraft.objects.filter(pk=deck.pk).delete()
        return made
    monkeypatch.setattr(tasks, 'convert_deck', deleting)
    assert tasks.next_task()
    assert not FileAsset.objects.filter(metadata__kind='deck_slide').exists() and not SlideRender.objects.exists()
    assert not EditorTask.objects.exists() and not tasks.next_task()
    assert not list(storage_path('scratch').glob('editor-*'))


def test_deleting_a_draft_waits_for_a_render_storing_its_pictures_and_takes_them_too(deck, monkeypatch, tmp_path):
    png = tmp_path / 'slide.png'
    png.write_bytes(b'picture')
    real, stored = QuerySet.select_for_update, []

    def locking(queryset, *args, **kwargs):
        # The render that held the draft's lock commits just as this request gets it.
        if queryset.model is GenerationDraft and not stored:
            stored.append(None)
            stored[0] = tasks._store(deck.account_id, deck.pk, {'k' * 64: (png, png, [])}, {'k' * 64})
            assert SlideRender.objects.filter(draft=deck).exists()
        return real(queryset, *args, **kwargs)
    monkeypatch.setattr(QuerySet, 'select_for_update', locking)
    assert api_client(deck.account).delete(f'/api/v1/generation/drafts/{deck.pk}').status_code == 200
    assert stored == [True]
    assert not GenerationDraft.objects.filter(pk=deck.pk).exists()
    assert not SlideRender.objects.exists() and not FileAsset.objects.filter(metadata__kind='deck_slide').exists()


def test_a_draft_edited_mid_render_keeps_each_versions_answer(deck, monkeypatch, converted):
    ask(deck)
    old_version = deck.version
    real = tasks.convert_deck
    saved = []

    def editing(source, folder, slides):
        if not saved:
            saved.append(edit_section(deck.account, deck, 's5', heading='Edited during the render'))
        return real(source, folder, slides)
    monkeypatch.setattr(tasks, 'convert_deck', editing)
    assert tasks.next_task()
    new_version = saved[0].version
    assert new_version > old_version
    said = tasks.render_state(deck.account, deck.pk, old_version)
    assert said['status'] == tasks.DONE and said['version'] == old_version
    drawn_before = {slide['key'] for slide in said['slides']}
    now = tasks.render_state(deck.account, deck.pk, new_version)
    assert now['status'] == 'none' and now['slides'] == []
    assert tasks.request_render(deck.account, deck.pk, new_version)[0] == tasks.QUEUED
    assert tasks.render_state(deck.account, deck.pk, new_version)['status'] == tasks.QUEUED
    assert tasks.next_task()
    fresh = tasks.render_state(deck.account, deck.pk, new_version)
    assert fresh['status'] == tasks.DONE and {slide['key'] for slide in fresh['slides']} != drawn_before
    # Both versions' pictures stand: each row is by its key.
    assert drawn_before <= set(SlideRender.objects.filter(draft=deck).values_list('key', flat=True))
    assert tasks.render_state(deck.account, deck.pk, old_version)['status'] == tasks.DONE
    assert tasks.render_state(deck.account, deck.pk, old_version - 1)['status'] == 'stale'


def test_a_render_asked_for_while_a_later_one_waits_is_told_it_is_on_its_way(deck):
    ask(deck)
    edited = edit_section(deck.account, deck, 's5', heading='Edited')
    tasks.request_render(deck.account, deck.pk, edited.version)
    assert tasks.render_state(deck.account, deck.pk, deck.version)['status'] == tasks.QUEUED


@pytest.mark.parametrize('code', ['processor_timeout', 'conversion_failed'])
def test_a_libreoffice_that_crashes_or_hangs_interrupts_the_render_and_cleans_up(deck, monkeypatch, code):
    calls = []

    def broken(source, folder, slides):
        calls.append(1)
        raise ProcessorError(code)
    monkeypatch.setattr(tasks, 'convert_deck', broken)
    ask(deck)
    for _ in range(tasks.MAX_ATTEMPTS):
        assert tasks.next_task()
        assert not list(storage_path('scratch').glob('editor-*'))
    said = tasks.render_state(deck.account, deck.pk)
    assert (said['status'], said['error']) == (tasks.FAILED, 'render_deck_interrupted')
    assert len(calls) == tasks.MAX_ATTEMPTS and not SlideRender.objects.exists()


def test_a_picture_that_has_gone_fails_the_render_by_name(customer, settings, converted, stock_photos):  # noqa: F811
    settings.LOCAL_SYNC_JOBS = True
    draft, _ = generate(customer, asked=[])
    settings.LOCAL_SYNC_JOBS = False
    FileAsset.objects.filter(metadata__kind='deck_photo').update(state='deleted')
    ask(draft)
    row, _ = rendered(draft)
    assert (row.status, row.error, row.attempts) == (tasks.FAILED, 'pinned_asset_expired', 1)
    said = tasks.render_state(customer, draft.pk)
    assert (said['status'], said['error']) == (tasks.FAILED, 'pinned_asset_expired')


def test_a_picture_whose_file_has_gone_is_drawn_again(deck, converted):
    ask(deck)
    rendered(deck)
    gone = SlideRender.objects.select_related('file').first()
    storage.delete(gone.file.object_key)
    assert tasks.render_state(deck.account, deck.pk)['status'] == tasks.DONE
    EditorTask.objects.filter(draft=deck).delete()
    ask(deck)
    rendered(deck)
    assert len(converted[-1]) == 1


def test_a_picture_no_render_uses_goes_after_an_hour(deck, converted):
    ask(deck)
    _, first = rendered(deck)
    edit_section(deck.account, deck, 's5', heading='Edited')
    ask(deck)
    rendered(deck)
    assert SlideRender.objects.filter(draft=deck).count() == 9
    old = SlideRender.objects.get(draft=deck, key=first['slides'][4]['key'])
    path = storage_path(old.file.object_key)
    tasks.prune()
    assert path.exists(), 'its result can still name it'
    tasks.prune(timezone.now() + timedelta(minutes=61))
    assert not SlideRender.objects.filter(pk=old.pk).exists() and not path.exists()
    assert not FileAsset.objects.filter(pk=old.file_id).exists()
    assert SlideRender.objects.filter(draft=deck).count() == 8


def test_an_old_picture_in_use_has_its_hour_from_the_last_result_that_named_it(deck, converted):
    ask(deck)
    _, first = rendered(deck)
    original = next(section for section in unpack(deck.encrypted_data)['content']['sections'] if section['id'] == 's4')['heading']
    SlideRender.objects.filter(draft=deck).update(created_at=timezone.now() - timedelta(hours=2))
    edit_section(deck.account, deck, 's5', heading='Edited')
    ask(deck)
    _, second = rendered(deck)
    edit_section(deck.account, deck, 's4', heading='Edited too')
    ask(deck)
    _, third = rendered(deck)
    keys = [{slide['key'] for slide in result['slides']} for result in (first, second, third)]
    reused = (keys[0] & keys[1]) - keys[2]
    assert len(reused) == 1
    tasks.prune()
    assert SlideRender.objects.filter(draft=deck, key__in=reused).count() == 1
    assert tasks.render_state(deck.account, deck.pk, second['version'])['status'] == tasks.DONE
    conversions = len(converted)
    edit_section(deck.account, deck, 's4', heading=original)
    ask(deck)
    rendered(deck)
    assert len(converted) == conversions, 'taken back within the hour, it is not drawn again'


def test_cleanup_drops_a_picture_no_render_uses_with_no_other_render_and_keeps_the_last_renders(deck, converted):
    ask(deck)
    _, first = rendered(deck)
    edit_section(deck.account, deck, 's5', heading='Edited')
    ask(deck)
    _, second = rendered(deck)
    stale = {slide['key'] for slide in first['slides']} - {slide['key'] for slide in second['slides']}
    assert len(stale) == 1
    old = SlideRender.objects.select_related('file', 'thumb').get(draft=deck, key__in=stale)
    paths = [storage_path(old.file.object_key), storage_path(old.thumb.object_key)]
    current = SlideRender.objects.filter(draft=deck).exclude(pk=old.pk).count()
    cleanup_expired()
    assert all(path.exists() for path in paths)
    SlideRender.objects.filter(draft=deck).update(used_at=F('used_at') - timedelta(minutes=61))
    cleanup_expired()
    assert not any(path.exists() for path in paths) and not FileAsset.objects.filter(pk__in=(old.file_id, old.thumb_id)).exists()
    assert SlideRender.objects.filter(draft=deck).count() == current
    # The last render's stay however long ago it was: the next one reuses them.
    SlideRender.objects.filter(draft=deck).update(used_at=F('used_at') - timedelta(days=3))
    cleanup_expired()
    assert SlideRender.objects.filter(draft=deck).count() == current


def test_pictures_go_with_the_draft(deck, converted):
    ask(deck)
    rendered(deck)
    client = api_client(deck.account)
    keys = [render.file.object_key for render in SlideRender.objects.select_related('file')]
    assert client.delete(f'/api/v1/generation/drafts/{deck.pk}').status_code == 200
    assert not FileAsset.objects.filter(metadata__kind='deck_slide').exists() and not SlideRender.objects.exists()
    assert not any(storage_path(key).exists() for key in keys)


def test_pictures_expire_with_the_draft_and_cleanup_leaves_no_row(deck, converted):
    ask(deck)
    rendered(deck)
    keys = [render.file.object_key for render in SlideRender.objects.select_related('file')]
    FileAsset.objects.filter(metadata__kind='deck_slide').update(expires_at=timezone.now() - timedelta(seconds=1))
    GenerationDraft.objects.filter(pk=deck.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    cleanup_expired()
    assert not FileAsset.objects.filter(metadata__kind='deck_slide').exists() and not SlideRender.objects.exists()
    assert not any(storage_path(key).exists() for key in keys)


def test_a_send_extends_the_pictures_with_the_draft(deck, converted):
    from types import SimpleNamespace
    from apps.core.services import _extend_draft
    ask(deck)
    rendered(deck)
    deadline = timezone.now() + timedelta(days=9)
    _extend_draft(SimpleNamespace(parameters={'generation_draft_id': str(deck.pk)}, account=deck.account), deadline)
    assert {asset.expires_at for asset in FileAsset.objects.filter(metadata__kind='deck_slide')} == {deadline}


def test_a_send_leaves_pictures_no_render_uses_to_their_own_clock(deck, converted):
    from types import SimpleNamespace
    from apps.core.services import _extend_draft
    ask(deck)
    _, first = rendered(deck)
    edit_section(deck.account, deck, 's5', heading='Edited')
    ask(deck)
    _, second = rendered(deck)
    deadline = timezone.now() + timedelta(days=9)
    _extend_draft(SimpleNamespace(parameters={'generation_draft_id': str(deck.pk)}, account=deck.account), deadline)
    stale = {slide['key'] for slide in first['slides']} - {slide['key'] for slide in second['slides']}
    assert stale
    for render in SlideRender.objects.select_related('file', 'thumb').filter(draft=deck):
        for asset in (render.file, render.thumb):
            assert (asset.expires_at == deadline) is (render.key not in stale)


# --- The conversion itself, through the real child -------------------------------------------

@pytest.fixture
def soffice(tmp_path, monkeypatch):
    """A stand-in LibreOffice for the real child: it says what it was given, and leaves a PDF of two pages."""
    from pypdf import PdfWriter
    writer = PdfWriter()
    for _ in range(2):
        writer.add_blank_page(width=960, height=540)
    made = tmp_path / 'made.pdf'
    writer.write(made)
    binary = tmp_path / 'soffice'
    binary.write_text(f'''#!/bin/sh
if [ "$1" = "--version" ]; then echo "LibreOffice 24.2.0"; exit 0; fi
env > "{tmp_path}/env.log"
echo "$1" >> "{tmp_path}/profiles.log"
ulimit -a > "{tmp_path}/limits.log"
if [ -f "{tmp_path}/hang" ]; then sleep 300 & echo $! > "{tmp_path}/child.pid"; wait; fi
while [ $# -gt 1 ]; do
  if [ "$1" = "--outdir" ]; then folder="$2"; fi
  shift
done
cp "{made}" "$folder/input.pdf"
''')
    binary.chmod(0o755)
    monkeypatch.setenv('DOCMASTER_SOFFICE_BIN', str(binary))
    office_runtime.cache_clear()
    yield tmp_path
    monkeypatch.delenv('DOCMASTER_SOFFICE_BIN')
    office_runtime.cache_clear()


def a_deck(folder):
    from apps.studio.slides import render_pptx
    sections = [{'id': f's{number}', 'heading': f'Heading {number}', 'body': 'A line', 'notes': '', 'layout': 'bullets', 'items': [], 'columns': [], 'image_query': ''} for number in (1, 2)]
    return Path(render_pptx({'title': 'Tides', 'questions': [], 'citations': [], 'sections': sections}, folder / 'deck.pptx', 'en', 'user_document')['path'])


def test_conversions_share_a_warm_profile_in_deck_faces_with_the_childs_environment(soffice, monkeypatch, tmp_path):
    monkeypatch.setenv('DATABASE_URL', 'postgresql://secret')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'secret')
    source = a_deck(tmp_path)
    tasks.convert_deck(source, tmp_path / 'one', 2)
    tasks.convert_deck(source, tmp_path / 'two', 2)
    profiles = (soffice / 'profiles.log').read_text().split()
    assert len(profiles) == 2 and profiles[0] == profiles[1] and 'editor-office-' in profiles[0]
    env = dict(line.split('=', 1) for line in (soffice / 'env.log').read_text().splitlines() if '=' in line)
    assert 'editor-office-' in env['FONTCONFIG_FILE'] and 'editor-office-' in env['HOME']
    assert env['TMPDIR'] != env['HOME'], 'what a crash leaves goes with the conversion'
    assert 'secret' not in (soffice / 'env.log').read_text()
    assert 'DATABASE_URL' not in env and 'TELEGRAM_BOT_TOKEN' not in env
    assert env.get('DOCMASTER_CPU_SECONDS') and env.get('DOCMASTER_ADDRESS_SPACE_MB')


def test_a_customers_file_never_passes_through_the_warm_profile(soffice, tmp_path):
    source = a_deck(tmp_path)
    with pytest.raises(ProcessorError) as refused:
        sandbox.execute_sandbox('convert.pptx_to_pdf', [source], {}, tmp_path / 'one', office_home=str(tmp_path / 'home'))
    assert refused.value.code == 'invalid_parameters'
    sandbox.execute_sandbox('convert.pptx_to_pdf', [source], {}, tmp_path / 'two')
    assert 'editor-office-' not in (soffice / 'profiles.log').read_text() and str(tmp_path / 'home') not in (soffice / 'profiles.log').read_text()
    # A parameter cannot name it: only the lane's own call can.
    with pytest.raises(ProcessorError):
        sandbox.execute_sandbox('convert.pptx_to_pdf', [source], {'office_home': str(tmp_path / 'home')}, tmp_path / 'three')


def test_a_hung_libreoffice_is_killed_with_its_group_and_the_profile_starts_cold(soffice, monkeypatch, tmp_path):
    source = a_deck(tmp_path)
    tasks.convert_deck(source, tmp_path / 'first', 2)
    warm = tasks._office['home']
    (soffice / 'hang').write_text('')
    monkeypatch.setattr(tasks, 'office_seconds', lambda slides: 1)
    with pytest.raises(ProcessorError) as hung:
        tasks.convert_deck(source, tmp_path / 'second', 2)
    assert hung.value.code == 'processor_timeout'
    assert not Path(warm).exists() and tasks._office['home'] is None
    child = int((soffice / 'child.pid').read_text())
    for _ in range(50):
        if subprocess.run(['ps', '-p', str(child), '-o', 'stat='], capture_output=True, text=True).stdout.strip() in ('', 'Z'):
            break
        time.sleep(0.1)
    else:
        pytest.fail('the process LibreOffice started is still running')
    (soffice / 'hang').unlink()
    assert tasks.convert_deck(source, tmp_path / 'third', 2)['page_count'] == 2
    assert tasks._office['home'] != warm


def test_the_allowance_is_twenty_seconds_for_twelve_slides_and_scales_with_the_measurements():
    assert tasks.office_seconds(1) == tasks.office_seconds(12) == 20
    assert 30 <= tasks.office_seconds(60) <= 60


# --- The real LibreOffice --------------------------------------------------------------------

@REQUIRES_OFFICE
def test_a_real_render_draws_each_slide_with_its_own_number_and_converts_only_what_changed(deck):
    from pypdf import PdfReader
    ask(deck)
    row, result = rendered(deck)
    assert row.status == tasks.DONE, row.error
    for render in SlideRender.objects.select_related('file', 'thumb').filter(draft=deck):
        with Image.open(storage.local(render.file.object_key)) as large, Image.open(storage.local(render.thumb.object_key)) as small:
            assert large.size == (1280, 720) and small.size == (96, 54)
            assert len(set(large.convert('RGB').resize((64, 36)).getdata())) > 1, 'a slide came out blank'
    # A copy holding only the fifth slide: LibreOffice must still call it the fifth.
    from apps.studio.slides import render_pptx
    import tempfile
    data = unpack(GenerationDraft.objects.get(pk=deck.pk).encrypted_data)
    with tempfile.TemporaryDirectory() as folder:
        folder = Path(folder)
        render_pptx(data['content'], folder / 'deck.pptx', data['output_locale'], 'user_document', pins=data['_render'])
        tasks._only_these(Presentation(str(folder / 'deck.pptx')), {4}, folder / 'one.pptx')
        pdf = tasks.convert_deck(folder / 'one.pptx', folder / 'pdf', 1)
        assert pdf['page_count'] == 1
        assert '5' in PdfReader(pdf['path']).pages[0].extract_text()
    edit_section(deck.account, deck, 's5', heading='A new heading')
    ask(deck)
    before = SlideRender.objects.filter(draft=deck).count()
    row, after = rendered(deck)
    assert row.status == tasks.DONE, row.error
    assert SlideRender.objects.filter(draft=deck).count() == before + 1
    assert [slide['key'] == old['key'] for slide, old in zip(after['slides'], result['slides'])].count(False) == 1


# --- Routes ----------------------------------------------------------------------------------

def test_with_the_deck_editor_off_every_route_answers_feature_unavailable(deck, monkeypatch, converted):
    ask(deck)
    rendered(deck)
    key = SlideRender.objects.filter(draft=deck).first().key
    client = api_client(deck.account)
    base = f'/api/v1/generation/drafts/{deck.pk}'
    monkeypatch.setenv('EDITOR_FLAG_DECK_EDITOR', '0')
    answers = [client.get(f'{base}/render'), client.post(f'{base}/render', {'version': deck.version}, content_type='application/json'),
               client.get(f'{base}/slides/{key}.png'), client.get(f'{base}/slides/{key}.thumb.png')]
    assert [(answer.status_code, answer.json()['error']['code']) for answer in answers] == [(409, 'feature_unavailable')] * 4


def test_with_the_deck_editor_off_a_preview_stays_what_it_was(monkeypatch):
    monkeypatch.setenv('EDITOR_FLAG_DECK_EDITOR', '0')
    owner = account()
    asset = upload(owner)
    answer = login_client(owner).get(f'/api/v1/files/{asset.id}/preview')
    assert answer.status_code == 200 and answer['Content-Type'] == 'image/png'
    assert not EditorTask.objects.exists()


def test_a_render_is_asked_for_polled_and_served_inline(deck, converted):
    client = api_client(deck.account)
    base = f'/api/v1/generation/drafts/{deck.pk}'
    assert client.get(f'{base}/render').json() == {'status': 'none', 'version': deck.version, 'slides': [], 'error': None}
    asked = client.post(f'{base}/render', {'version': deck.version}, content_type='application/json')
    assert asked.status_code == 202 and asked.json()['status'] == 'queued'
    again = client.post(f'{base}/render', {'version': deck.version}, content_type='application/json')
    assert again.json()['task_id'] == asked.json()['task_id'], 'asked again, it is the same task'
    assert client.get(f'{base}/render?version={deck.version}').json()['status'] == 'queued'
    assert tasks.next_task()
    said = client.get(f'{base}/render?version={deck.version}').json()
    assert said['status'] == 'done' and len(said['slides']) == 8
    assert client.post(f'{base}/render', {'version': deck.version}, content_type='application/json').json()['status'] == 'done'
    assert EditorTask.objects.filter(draft=deck).count() == 1
    slide = said['slides'][2]
    assert set(slide) == {'index', 'key', 'url', 'thumb_url', 'frames', 'fits', 'letters_over'}
    for url, size in ((slide['url'], (1280, 720)), (slide['thumb_url'], (96, 54))):
        answer = client.get(url)
        assert answer.status_code == 200 and answer['Content-Type'] == 'image/png'
        assert answer['Content-Disposition'].startswith('inline') and answer['Cache-Control'] == 'private, no-store'
        with Image.open(io.BytesIO(b''.join(answer.streaming_content))) as picture:
            assert picture.size == size


def test_only_a_ready_slide_of_ones_own_draft_is_served(deck, converted):
    ask(deck)
    rendered(deck)
    render = SlideRender.objects.select_related('file').filter(draft=deck).first()
    client = api_client(deck.account)
    base = f'/api/v1/generation/drafts/{deck.pk}/slides'
    assert client.get(f'{base}/{"0" * 64}.png').status_code == 404
    assert client.get(f'{base}/{"0" * 64}.thumb.png').status_code == 404
    other = api_client(account(43))
    assert other.get(f'{base}/{render.key}.png').status_code == 404
    assert other.get(f'/api/v1/generation/drafts/{deck.pk}/render').status_code == 404
    assert other.post(f'/api/v1/generation/drafts/{deck.pk}/render', {'version': deck.version}, content_type='application/json').status_code == 404
    FileAsset.objects.filter(pk=render.file_id).update(expires_at=timezone.now() - timedelta(seconds=1))
    assert client.get(f'{base}/{render.key}.png').status_code == 404
    FileAsset.objects.filter(pk=render.file_id).update(expires_at=timezone.now() + timedelta(hours=1))
    storage_path(render.file.object_key).unlink()
    assert client.get(f'{base}/{render.key}.png').status_code == 404


def test_a_stale_version_is_a_conflict_and_a_document_cannot_be_drawn(deck, customer):  # noqa: F811
    from apps.studio.domain import DOCUMENT, create_draft
    client = api_client(deck.account)
    answer = client.post(f'/api/v1/generation/drafts/{deck.pk}/render', {'version': deck.version - 1}, content_type='application/json')
    assert answer.status_code == 409 and answer.json()['error']['code'] == 'version_conflict'
    answer = client.post(f'/api/v1/generation/drafts/{deck.pk}/render', {}, content_type='application/json')
    assert answer.status_code == 409
    document = create_draft(customer, {'feature_id': DOCUMENT, 'title': 'Notes', 'source_text': 'Words.', 'options': {}})
    answer = client.post(f'/api/v1/generation/drafts/{document.pk}/render', {'version': document.version}, content_type='application/json')
    assert answer.status_code == 409 and answer.json()['error']['code'] == 'deck_not_editable'


def test_past_its_budget_a_render_is_refused_with_lane_busy_over_http(deck, monkeypatch):
    monkeypatch.setenv('EDITOR_BUDGET_RENDER_DECK', '1')
    monkeypatch.setenv('EDITOR_BUDGET_PAID_MULTIPLIER', '1')
    elapsed(task(deck.account), 5, kind=tasks.RENDER)
    answer = api_client(deck.account).post(f'/api/v1/generation/drafts/{deck.pk}/render', {'version': deck.version}, content_type='application/json')
    assert answer.status_code == 429
    error = answer.json()['error']
    assert error['code'] == 'lane_busy' and error['retryable'] is True


def test_the_api_draws_nothing_and_a_preview_is_the_lanes(monkeypatch):
    owner = account()
    asset = upload(owner)
    client = login_client(owner)
    url = f'/api/v1/files/{asset.id}/preview?page=1'
    drawn = []
    real = sandbox.execute_sandbox
    monkeypatch.setattr('apps.core.previews.execute_sandbox', lambda *args, **kwargs: drawn.append(args) or real(*args, **kwargs))
    first = client.get(url)
    assert first.status_code == 202 and not drawn
    assert client.get(url).json() == first.json(), 'asked again, it is the same task'
    assert EditorTask.objects.filter(kind=tasks.PREVIEW).count() == 1
    assert tasks.next_task() and drawn
    answer = client.get(url)
    assert answer.status_code == 200 and answer['Content-Type'] == 'image/png' and answer['Content-Disposition'].startswith('inline')
    assert PagePreview.objects.filter(asset=asset).count() == 1


def test_uncached_previews_are_ten_a_minute_and_asking_after_one_does_not_count(monkeypatch):
    owner = account()
    asset = upload(owner)
    FileAsset.objects.filter(pk=asset.pk).update(page_count=30)
    client = login_client(owner)
    monkeypatch.setattr(tasks, 'MAX_QUEUED', 99)
    for _ in range(30):
        assert client.get(f'/api/v1/files/{asset.id}/preview?page=1').status_code == 202
    for page in range(2, 11):
        assert client.get(f'/api/v1/files/{asset.id}/preview?page={page}').status_code == 202
    answer = client.get(f'/api/v1/files/{asset.id}/preview?page=11')
    assert answer.status_code == 429 and answer.json()['error']['code'] == 'rate_limited'


def test_a_fourth_page_waiting_is_told_the_lane_is_busy():
    owner = account()
    asset = upload(owner)
    FileAsset.objects.filter(pk=asset.pk).update(page_count=30)
    client = login_client(owner)
    for page in range(1, 4):
        assert client.get(f'/api/v1/files/{asset.id}/preview?page={page}').status_code == 202
    answer = client.get(f'/api/v1/files/{asset.id}/preview?page=4')
    assert answer.status_code == 429 and answer.json()['error']['code'] == 'lane_busy'


def test_a_preview_that_failed_is_said_again_for_a_minute(monkeypatch):
    owner = account()
    asset = upload(owner)
    client = login_client(owner)
    url = f'/api/v1/files/{asset.id}/preview'
    assert client.get(url).status_code == 202
    handled(monkeypatch, raises=DomainError('invalid_output'))
    assert tasks.next_task()
    answer = client.get(url)
    assert answer.status_code == 409 and answer.json()['error']['code'] == 'invalid_output'
    assert EditorTask.objects.count() == 1
    EditorTask.objects.update(finished_at=timezone.now() - timedelta(seconds=61))
    assert client.get(url).status_code == 202


def test_a_preview_is_refused_at_the_door_as_it_always_was_and_is_not_queued():
    owner = account()
    asset = upload(owner)
    client = login_client(owner)
    assert client.get(f'/api/v1/files/{asset.id}/preview?page=0').status_code == 400
    assert client.get(f'/api/v1/files/{asset.id}/preview?page=99').status_code == 400
    assert login_client(account(43)).get(f'/api/v1/files/{asset.id}/preview').status_code == 404
    FileAsset.objects.filter(pk=asset.pk).update(state='deleted')
    assert client.get(f'/api/v1/files/{asset.id}/preview').status_code == 410
    assert not EditorTask.objects.exists()


def test_with_local_sync_jobs_a_task_runs_as_it_is_queued(deck, settings, converted):
    settings.LOCAL_SYNC_JOBS = True
    status, row = ask(deck)
    assert status == tasks.DONE and row.status == tasks.DONE


# --- Where it runs ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent


def test_the_lane_has_its_own_container_read_only_like_the_worker():
    import yaml
    production = yaml.safe_load((ROOT / 'infra/production/compose.yaml').read_text())['services']
    editor = production['editor']
    assert editor['command'] == ['python', 'manage.py', 'runeditor']
    assert editor['mem_limit'] == '1536m' and editor['cpus'] == 1 and editor['pids_limit'] == 256 and editor['stop_grace_period'] == '120s'
    assert editor['read_only'] is True and editor['cap_drop'] == ['ALL'] and editor['image'] == production['worker']['image']
    assert 'editor-heartbeat' in ' '.join(editor['healthcheck']['test'])
    # The child's allowances for the largest deck, and drawing it, fit in the grace.
    assert tasks.office_seconds(60) + 10 + tasks.IMAGE_SECONDS + tasks.IMAGE_SECONDS_PER_SLIDE * 60 < 120
    assert yaml.safe_load((ROOT / 'infra/compose.yaml').read_text())['services']['editor']['command'] == ['python', 'manage.py', 'runeditor']


def test_the_service_audit_checks_the_lane():
    audit = (ROOT / 'scripts/operations/verify-services.py').read_text()
    assert "('platform', {'api', 'db', 'redis', 'worker', 'ai-worker', 'batches', 'reader', 'editor', 'cleanup', 'bot', 'gateway'})" in audit


def test_the_heartbeat_the_healthcheck_reads_is_the_one_the_runner_touches():
    from apps.studio.management.commands.runeditor import HEARTBEAT
    assert HEARTBEAT in (ROOT / 'infra/production/compose.yaml').read_text()


def smoke_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location('docmaster_editor_smoke', ROOT / 'scripts/deploy/container_smoke.py')
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    return smoke


def test_the_container_smoke_starts_the_lane_and_runs_its_check_there(monkeypatch):
    smoke = smoke_module()
    assert "'editor'" in (ROOT / 'scripts/deploy/container_smoke.py').read_text().split("services=['api'", 1)[1][:80]
    seen = []

    def run(command, **kwargs):
        seen.append(command)
        answer = 'abc123' if 'ps' in command else 'false 0 true'
        return subprocess.CompletedProcess(command, 0, stdout=answer)
    monkeypatch.setattr(smoke, 'run', run)
    smoke.check_editor(['docker', 'compose'], {})
    assert seen[0] == ['docker', 'compose', 'exec', '-T', 'editor', 'python', '-c', smoke.EDITOR_CHECK]
    monkeypatch.setattr(smoke, 'run', lambda command, **kwargs: subprocess.CompletedProcess(command, 0, stdout='abc123' if 'ps' in command else 'true 1 true'))
    with pytest.raises(RuntimeError, match='OOM-killed'):
        smoke.check_editor(['docker', 'compose'], {})


def test_the_container_smokes_check_runs_against_the_lane(converted, capsys):
    # All but LibreOffice itself: that it holds in the image is for the smoke to find.
    exec(compile(smoke_module().EDITOR_CHECK, 'check_editor', 'exec'), {})
    printed = capsys.readouterr().out
    assert 'EDITOR-RENDER 12 photo slides' in printed and 'EDITOR-RENDER peak MB' in printed
    assert [len(copied) for copied in converted] == [12, 1]


def test_every_new_code_has_its_message_in_each_language():
    for locale in ('en', 'uz', 'ru'):
        messages = json.loads((ROOT / 'i18n' / f'{locale}.json').read_text(encoding='utf-8'))
        for code in ('lane_busy', 'render_deck_interrupted', 'preview_interrupted', 'editor_task_unsupported', 'editor_task_failed'):
            assert messages[code]
            if locale == 'uz':
                assert "o'" not in messages[code] and "g'" not in messages[code] and not any('Ѐ' <= letter <= 'ӿ' for letter in messages[code])
