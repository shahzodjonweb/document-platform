"""A deck's pictures changed in the slide editor, and its design: free, capped, and never an AI edit.

Every picture action is a request the web makes on a drawn deck. The ones that
fetch or read picture bytes run as picture tasks (here at once, LOCAL_SYNC_JOBS);
Pixabay is the fake network of test_photos, and the model is stood in for.
"""
import io
import json
from datetime import timedelta

import pytest
from PIL import Image
from django.core.cache import caches
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.core import allowance, storage
from apps.core.models import FileAsset, Job
from apps.core.services import upload_file
from apps.studio import deck_photos, photo_choice, photos as stock
from apps.studio.domain import pack, unpack
from apps.studio.models import EditorTask, GenerationDraft, ProviderUsage
from apps.studio.render_export import chosen_photos, over_budget
from tests.test_deck_pins import COVER, LIST, PHOTO, WORDS, customer, deck_sections, generate, pins_of, stock_photos  # noqa: F401
from tests.test_photos import KEY, Network, hit, jpeg  # noqa: F401
from tests.test_platform import login_client
from operations.integrations import save_config

pytestmark = pytest.mark.django_db
# The real fetcher: `stock_photos` stands in for it while a deck is generated.
FETCH = stock.fetch_for_deck


@pytest.fixture(autouse=True)
def switches(monkeypatch, settings):
    monkeypatch.setenv('EDITOR_FLAG_DECK_EDITOR', '1')
    monkeypatch.setenv('EDITOR_FLAG_PHOTOS_TASK', '1')
    settings.LOCAL_SYNC_JOBS = True
    caches['limits'].clear()


class Library(Network):
    """test_photos' Pixabay, with other photos for other words, as a real library has."""

    def __call__(self, request, timeout, handler):
        if request.full_url.startswith(stock.API) and self.hits:
            from urllib.parse import parse_qs, urlsplit
            query = parse_qs(urlsplit(request.full_url).query)['q'][0]
            base = sum(map(ord, query)) * 100
            self.hits = [hit(base + n) for n in range(1, 9)]
        return super().__call__(request, timeout, handler)


@pytest.fixture
def pixabay(monkeypatch):
    """Pixabay on, the fetcher real again, and the model naming each slide's subject and choosing the first photo shown."""
    save_config('pixabay', {'pixabay_key': KEY, 'enabled': 'true'})
    network = Library()
    monkeypatch.setattr(stock, '_open', network)
    monkeypatch.setattr(stock, 'fetch_for_deck', FETCH)
    # Set as the admin sets it: a stand-in for ai_config would stay in any module first imported meanwhile.
    save_config('ai', {'mode': 'openai', 'model': 'test-model', 'api_key': 'sk-offline-test'})
    monkeypatch.setattr(photo_choice, 'name_queries', lambda config, title, slides, **kw: {slide['id']: f'harbour {slide["id"]}' for slide in slides})
    monkeypatch.setattr(photo_choice, 'choose', lambda config, title, slides, **kw: {slide['id']: 1 for slide in slides})
    return network


@pytest.fixture
def deck(customer, stock_photos):  # noqa: F811
    draft, _ = generate(customer)
    return draft


def post(customer, path, body):  # noqa: F811
    return login_client(customer).post(f'/api/v1/{path}', json.dumps(body), content_type='application/json')


def act(customer, draft, action, **body):  # noqa: F811
    draft.refresh_from_db()
    return post(customer, f'generation/drafts/{draft.id}/photos', {'action': action, 'version': draft.version, **body})


def followed(customer, draft, answer):  # noqa: F811
    """What the web reads while it waits on a picture task."""
    assert answer.status_code == 202, answer.content
    return login_client(customer).get(f'/api/v1/generation/drafts/{draft.id}/photos/{answer.json()["task_id"]}').json()


def code(answer):
    return answer.json()['error']['code']


def data_of(draft):
    return unpack(GenerationDraft.objects.get(pk=draft.pk).encrypted_data)


def section(draft, sid):
    return next(s for s in data_of(draft)['content']['sections'] if s['id'] == sid)


def opened(customer, draft):  # noqa: F811
    return login_client(customer).get(f'/api/v1/generation/drafts/{draft.id}').json()


# ---------------------------------------------------------------- Add to all slides


def test_add_to_all_slides_gives_pictures_only_where_every_word_still_shows(customer, deck, pixabay):  # noqa: F811
    before = deck.version
    state = followed(customer, deck, act(customer, deck, 'fill'))
    assert state['status'] == 'done' and state['action'] == 'fill', state
    result = state['result']
    deck.refresh_from_db()
    assert result['version'] == deck.version == before + 1 and result['added'] >= 1
    data = data_of(deck)
    pins = data['_render']['photos']
    assert pins[LIST]['asset_id'] and section(deck, LIST)['layout'] in deck_photos.PHOTO_LAYOUTS
    assert section(deck, LIST)['image_query'] == f'harbour {LIST}', 'the words the model named, kept for Find more'
    assert result['added'] == result['asked'] == 6 and result['unmatched'] == 0
    picture = FileAsset.objects.get(pk=pins[LIST]['asset_id'])
    assert picture.metadata['kind'] == 'deck_photo' and picture.metadata['draft_id'] == str(deck.pk) and not picture.metadata['candidate']
    assert picture.expires_at >= deck.expires_at
    # What was there stays: the cover's and the photo slide's own pictures.
    assert pins[COVER]['asset_id'] and pins[PHOTO]['asset_id']
    # Nothing it added would stop a send: every slide still shows all its words.
    assert over_budget(data, chosen_photos(data)) == []
    assert result['added'] + result['no_room'] + result['unmatched'] + result['failed'] == result['asked']
    assert ProviderUsage.objects.filter(task__draft=deck, provider='pixabay', job__isnull=True).count() == 1


def test_a_slide_too_full_for_a_picture_keeps_its_words_and_none(customer, stock_photos, request):  # noqa: F811
    long = '\n'.join(' '.join(['harbour'] * 20) for _ in range(6))
    sections = [dict(s, body=long, items=[]) if s['id'] == LIST else s for s in deck_sections()]
    draft, _ = generate(customer, sections=sections)
    request.getfixturevalue('pixabay')
    layout = section(draft, LIST)['layout']
    assert act(customer, draft, 'next', section_id=LIST).status_code == 400, 'no candidates to take'
    state = followed(customer, draft, act(customer, draft, 'fill'))
    assert state['status'] == 'done' and not data_of(draft)['_render']['photos'].get(LIST, {}).get('asset_id')
    assert section(draft, LIST)['layout'] == layout and section(draft, LIST)['body'] == long
    assert state['result']['no_room'] >= 1


def test_fills_are_three_a_day_and_failed_ones_do_not_count(customer, deck, pixabay, monkeypatch):  # noqa: F811
    pixabay.hits = []
    for _ in range(deck_photos.FILLS_PER_DAY):
        assert followed(customer, deck, act(customer, deck, 'fill'))['status'] == 'done'
    refused = act(customer, deck, 'fill')
    assert refused.status_code == 429 and code(refused) == 'photos_limit'
    assert refused.json()['error']['message_params'] == {'limit_kind': 'fill', 'limit': 3}
    assert opened(customer, deck)['pictures']['fills_left'] == 0
    # A failed one gives its place back.
    EditorTask.objects.filter(action='fill').update(status='failed')
    assert act(customer, deck, 'fill').status_code == 202
    # Tomorrow, Tashkent's, there are three again.
    later = timezone.now() + timedelta(days=1)
    monkeypatch.setattr(timezone, 'now', lambda: later)
    deck.expires_at = later + timedelta(hours=5)
    deck.save(update_fields=['expires_at'])
    assert opened(customer, deck)['pictures']['fills_left'] == 3


def test_a_deck_holds_twelve_pictures_and_no_more_than_its_plan(customer, deck, pixabay, monkeypatch):  # noqa: F811
    monkeypatch.setattr(deck_photos, 'PER_DECK', 2)
    refused = act(customer, deck, 'fill')
    assert refused.status_code == 429 and refused.json()['error']['message_params']['limit_kind'] == 'deck'
    # Changing a picture a slide has is no more of them.
    assert followed(customer, deck, act(customer, deck, 'next', section_id=PHOTO))['status'] == 'done'
    assert deck_photos.per_deck(customer) == 2
    monkeypatch.setattr('apps.core.policy.plan_limits', lambda account: {'max_deck_images': 1})
    assert deck_photos.per_deck(customer) == 1


def test_the_switch_off_refuses_every_picture_action(customer, deck, monkeypatch):  # noqa: F811
    monkeypatch.setenv('EDITOR_FLAG_PHOTOS_TASK', '0')
    for action in deck_photos.ACTIONS:
        answer = act(customer, deck, action, section_id=PHOTO)
        assert answer.status_code == 409 and code(answer) == 'feature_unavailable', action
    assert opened(customer, deck)['pictures']['on'] is False


# ---------------------------------------------------------------- one slide


def test_another_picture_downloads_the_large_copy_and_keeps_the_last_on_offer(customer, deck, pixabay):  # noqa: F811
    pins = pins_of(deck)['photos'][PHOTO]
    worn, shown = pins['asset_id'], [c['asset_id'] for c in pins['candidates'] if c['asset_id']]
    state = followed(customer, deck, act(customer, deck, 'next', section_id=PHOTO, asset_id=shown[1]))
    assert state['status'] == 'done', state
    downloads = [url for url, *_ in pixabay.calls if not url.startswith(stock.API)]
    assert downloads == [pins['candidates'][1]['url']], 'the large copy, not the preview the model saw'
    now = pins_of(deck)['photos'][PHOTO]
    assert now['asset_id'] == state['result']['asset_id'] != worn
    assert now['candidates'][-1]['asset_id'] == worn and now['candidates'][-1]['full']
    assert not any(c['asset_id'] == shown[1] for c in now['candidates'])
    # Back to the one it wore: stored whole, so Pixabay is not asked, even switched off.
    calls = len(pixabay.calls)
    save_config('pixabay', {'pixabay_key': KEY, 'enabled': 'false'})
    state = followed(customer, deck, act(customer, deck, 'next', section_id=PHOTO, asset_id=worn))
    assert state['status'] == 'done' and pins_of(deck)['photos'][PHOTO]['asset_id'] == worn and len(pixabay.calls) == calls


def test_remove_is_done_at_once_and_another_picture_brings_it_back(customer, deck, pixabay):  # noqa: F811
    worn = pins_of(deck)['photos'][PHOTO]['asset_id']
    before = deck.version
    answer = act(customer, deck, 'remove', section_id=PHOTO)
    assert answer.status_code == 200 and answer.json()['version'] == before + 1
    photo = answer.json()['render']['photos'][PHOTO]
    assert photo['asset_id'] is None and photo['candidates'][0]['asset_id'] == worn
    assert answer.json()['pictures']['pinned'] == 1
    calls = len(pixabay.calls)
    state = followed(customer, deck, act(customer, deck, 'next', section_id=PHOTO))
    assert state['status'] == 'done' and pins_of(deck)['photos'][PHOTO]['asset_id'] == worn and len(pixabay.calls) == calls
    assert act(customer, deck, 'remove', section_id=LIST).status_code == 400, 'nothing to take off'


def test_my_own_photo_is_made_a_plain_jpeg_with_nothing_of_the_file_kept(customer, deck):  # noqa: F811
    buffer = io.BytesIO()
    exif = Image.Exif()
    exif[0x010F] = 'PhoneMaker'
    Image.new('RGB', (1600, 1200), (20, 90, 160)).save(buffer, 'JPEG', exif=exif)
    mine = upload_file(customer, SimpleUploadedFile('IMG_0001.jpg', buffer.getvalue(), 'image/jpeg'))
    state = followed(customer, deck, act(customer, deck, 'upload', section_id=LIST, asset_id=str(mine.pk)))
    assert state['status'] == 'done', state
    kept = FileAsset.objects.get(pk=pins_of(deck)['photos'][LIST]['asset_id'])
    assert kept.metadata['provider'] == 'upload' and kept.pk != mine.pk
    with Image.open(io.BytesIO(storage.read_bytes(kept.object_key))) as picture:
        assert picture.format == 'JPEG' and not picture.getexif() and max(picture.size) <= stock.LONG_EDGE
    assert section(deck, LIST)['layout'] in deck_photos.PHOTO_LAYOUTS
    # Somebody else's file, or one that is not a picture, is refused at the tap.
    from tests.test_platform import upload
    paper = upload(customer)
    assert code(act(customer, deck, 'upload', section_id=LIST, asset_id=str(paper.pk))) == 'invalid_image'
    assert code(act(customer, deck, 'upload', section_id=LIST, asset_id='not-a-file')) == 'not_found'


def test_find_more_offers_four_from_english_words_ten_a_day_five_a_minute(customer, deck, pixabay):  # noqa: F811
    worn = pins_of(deck)['photos'][PHOTO]['asset_id']
    state = followed(customer, deck, act(customer, deck, 'search', section_id=PHOTO, query='  Container SHIP  в порту '))
    assert state['status'] == 'done' and state['result']['found'] == stock.CANDIDATES
    searched = [url for url, *_ in pixabay.calls if url.startswith(stock.API)]
    assert len(searched) == 1 and 'q=container+ship' in searched[0]
    photo = pins_of(deck)['photos'][PHOTO]
    assert photo['asset_id'] == worn, 'a search offers; it never changes the picture'
    assert len([c for c in photo['candidates'] if not c.get('full')]) == stock.CANDIDATES
    assert code(act(customer, deck, 'search', section_id=PHOTO, query='наш порт')) == 'invalid_parameters', 'only English words go out'
    for _ in range(4):
        followed(customer, deck, act(customer, deck, 'search', section_id=PHOTO, query='harbour'))
    minute = act(customer, deck, 'search', section_id=PHOTO, query='harbour')
    assert minute.status_code == 429 and minute.json()['error']['message_params']['limit_kind'] == 'search_minute'
    for _ in range(5):
        caches['limits'].clear()
        assert act(customer, deck, 'search', section_id=PHOTO, query='harbour').status_code == 202
    caches['limits'].clear()
    day = act(customer, deck, 'search', section_id=PHOTO, query='harbour')
    assert day.status_code == 429 and day.json()['error']['message_params'] == {'limit_kind': 'search', 'limit': 10}


def test_picture_tasks_take_their_own_share_of_the_key_and_leave_jobs_the_rest(customer, deck, pixabay, monkeypatch):  # noqa: F811
    asked = []
    real = __import__('apps.core.customer_auth', fromlist=['auth_limit']).auth_limit

    def counting(scope, identity, limit, seconds):
        asked.append((scope, limit))
        return real(scope, identity, limit, seconds)
    monkeypatch.setattr('apps.core.customer_auth.auth_limit', counting)
    followed(customer, deck, act(customer, deck, 'search', section_id=PHOTO, query='crane'))
    assert asked == [('pixabay-api-tasks', 60), ('pixabay-api', 90)]
    asked.clear()
    stock.fetch_for_deck([{'id': 's1', 'heading': 'x', 'body': 'y', 'layout': 'image_split', 'image_query': 'forklift'}], cap=1, budget=30)
    assert asked == [('pixabay-api', 90)], "a paid deck's search never waits on the tasks' share"


# ---------------------------------------------------------------- what it never does


def test_manual_picture_actions_use_no_ai_edit_and_no_task_of_the_week(customer, deck, pixabay):  # noqa: F811
    root = data_of(deck).get('options', {}).get('revise_draft_id') or str(deck.pk)
    jobs, usage = Job.objects.count(), allowance.usage_snapshot(customer)
    followed(customer, deck, act(customer, deck, 'fill'))
    followed(customer, deck, act(customer, deck, 'search', section_id=PHOTO, query='crane'))
    followed(customer, deck, act(customer, deck, 'next', section_id=PHOTO))
    assert act(customer, deck, 'remove', section_id=PHOTO).status_code == 200
    mine = upload_file(customer, SimpleUploadedFile('me.jpg', jpeg(), 'image/jpeg'))
    followed(customer, deck, act(customer, deck, 'upload', section_id=PHOTO, asset_id=str(mine.pk)))
    assert post(customer, f'generation/drafts/{deck.id}/design', {'version': GenerationDraft.objects.get(pk=deck.pk).version, 'design': 'midnight'}).status_code == 200
    assert Job.objects.count() == jobs
    assert allowance.edits_of(customer, root) == 0
    after = allowance.usage_snapshot(customer)
    assert after['ai_documents'] == usage['ai_documents'] and after['file_jobs'] == usage['file_jobs']


def test_a_picture_action_waits_for_nothing_and_moves_nothing_under_a_send(customer, deck, pixabay):  # noqa: F811
    stale = post(customer, f'generation/drafts/{deck.id}/photos', {'action': 'next', 'version': deck.version - 1, 'section_id': PHOTO})
    assert stale.status_code == 409 and code(stale) == 'version_conflict'
    from apps.studio.render_export import export_quote
    from apps.core.services import submit_job
    deck.refresh_from_db()
    quote = export_quote(customer, deck.id, deck.version, 'pptx', 'download')
    submit_job(customer, quote.id, 'send-0001')
    held = act(customer, deck, 'next', section_id=PHOTO)
    assert held.status_code == 409 and code(held) == 'generation_running'


def test_one_picture_task_at_a_time_for_a_deck(customer, deck, pixabay, settings):  # noqa: F811
    settings.LOCAL_SYNC_JOBS = False
    assert act(customer, deck, 'next', section_id=PHOTO).status_code == 202
    busy = post(customer, f'generation/drafts/{deck.id}/photos', {'action': 'search', 'version': deck.version, 'section_id': PHOTO, 'query': 'crane'})
    assert busy.status_code == 429 and code(busy) == 'lane_busy'


# ---------------------------------------------------------------- reading and design


def test_a_deck_shows_only_its_own_pictures(customer, deck):  # noqa: F811
    asset = pins_of(deck)['photos'][PHOTO]['asset_id']
    shown = login_client(customer).get(f'/api/v1/generation/drafts/{deck.id}/pictures/{asset}.jpg')
    assert shown.status_code == 200 and shown['Content-Disposition'].startswith('inline')
    other, _ = generate(customer)
    assert login_client(customer).get(f'/api/v1/generation/drafts/{other.id}/pictures/{asset}.jpg').status_code == 404
    from tests.test_platform import account
    stranger = account(77)
    assert login_client(stranger).get(f'/api/v1/generation/drafts/{deck.id}/pictures/{asset}.jpg').status_code == 404


def test_opening_says_what_a_send_and_the_pictures_allow(customer, deck):  # noqa: F811
    shown = opened(customer, deck)
    assert shown['send'] == {'counted_this_week': False}
    assert shown['pictures'] == {'on': True, 'stock': False, 'per_deck': 12, 'pinned': 2, 'fills_left': 3, 'searches_left': 10, 'style': 'photo'}
    assert 'send' not in login_client(customer).get('/api/v1/generation/drafts').json()['results'][0]
    content = data_of(deck)['content']
    saved = login_client(customer).patch(f'/api/v1/generation/drafts/{deck.id}', json.dumps({'version': deck.version, 'content': content}), content_type='application/json')
    assert saved.json()['pictures'] == shown['pictures'], 'a save answers with them too, or the web would lose its Pictures tab'


def test_another_design_is_the_pins_and_nothing_else(customer, deck):  # noqa: F811
    before = data_of(deck)
    answer = post(customer, f'generation/drafts/{deck.id}/design', {'version': deck.version, 'design': 'switchback'})
    assert answer.status_code == 200 and answer.json()['render']['design'] == 'switchback'
    after = data_of(deck)
    assert after['_render'] == {**before['_render'], 'design': 'switchback'} and after['content'] == before['content']
    assert answer.json()['version'] == deck.version + 1
    for wrong in ('nope', None, 'alpine'):
        refused = post(customer, f'generation/drafts/{deck.id}/design', {'version': deck.version + 1, 'design': wrong})
        assert refused.status_code == 400, wrong
    assert code(post(customer, f'generation/drafts/{deck.id}/design', {'version': deck.version, 'design': 'midnight'})) == 'version_conflict'


def test_a_draft_saved_after_a_picture_keeps_it(customer, deck):  # noqa: F811
    assert act(customer, deck, 'remove', section_id=PHOTO).status_code == 200
    pins = pins_of(deck)
    deck.refresh_from_db()
    content = data_of(deck)['content']
    content['sections'][1]['heading'] = 'Changed by hand'
    answer = login_client(customer).patch(f'/api/v1/generation/drafts/{deck.id}', json.dumps({'version': deck.version, 'content': content}), content_type='application/json')
    assert answer.status_code == 200 and pins_of(deck) == pins


# ---------------------------------------------------------------- what may land, and when


def save_content(customer, draft, change):  # noqa: F811
    draft.refresh_from_db()
    content = data_of(draft)['content']
    change(content)
    answer = login_client(customer).patch(f'/api/v1/generation/drafts/{draft.id}', json.dumps({'version': draft.version, 'content': content}), content_type='application/json')
    assert answer.status_code == 200, answer.content
    return answer


def test_a_picture_task_never_lands_over_what_changed_after_the_tap(customer, deck, settings):  # noqa: F811
    from apps.studio import tasks
    settings.LOCAL_SYNC_JOBS = False
    mine = upload_file(customer, SimpleUploadedFile('me.jpg', jpeg(), 'image/jpeg'))
    worn = pins_of(deck)['photos'][PHOTO]['asset_id']
    queued = act(customer, deck, 'upload', section_id=PHOTO, asset_id=str(mine.pk))
    assert queued.status_code == 202
    # Nothing else moves the deck's pictures, nor sends it, until the task is done.
    assert code(act(customer, deck, 'remove', section_id=PHOTO)) == 'lane_busy'
    deck.refresh_from_db()
    assert code(post(customer, f'generation/drafts/{deck.id}/design', {'version': deck.version, 'design': 'switchback'})) == 'lane_busy'
    assert code(post(customer, f'generation/drafts/{deck.id}/export-quote', {'version': deck.version, 'format': 'pptx', 'deliver': 'download'})) == 'generation_running'
    # A save from another tab meanwhile: the task gives way, and changes nothing.
    save_content(customer, deck, lambda content: content['sections'][1].update(heading='Changed elsewhere'))
    assert tasks.next_task()
    state = followed(customer, deck, queued)
    assert (state['status'], state['error']) == ('failed', 'version_conflict')
    assert pins_of(deck)['photos'][PHOTO]['asset_id'] == worn
    assert data_of(deck)['content']['sections'][1]['heading'] == 'Changed elsewhere'


def test_a_picture_task_given_up_by_the_sweep_is_never_run_again_nor_lands(customer, deck, pixabay, settings):  # noqa: F811
    from apps.studio import tasks
    settings.LOCAL_SYNC_JOBS = False
    act(customer, deck, 'next', section_id=PHOTO)
    row = EditorTask.objects.get(kind='photos')
    taken = tasks.take(row)
    tasks.sweep(now=timezone.now() + timedelta(seconds=tasks.LEASE_SECONDS + 1))
    row.refresh_from_db()
    assert (row.status, row.attempts) == ('failed', 1)
    worn = pins_of(deck)['photos'][PHOTO]['asset_id']
    assert tasks.perform(taken) is False, 'the slow runner finishing late is not kept'
    assert pins_of(deck)['photos'][PHOTO]['asset_id'] == worn


def test_a_slide_with_only_a_heading_takes_the_picture_layout_that_shows_one(customer, deck):  # noqa: F811
    save_content(customer, deck, lambda content: next(s for s in content['sections'] if s['id'] == LIST).update(body='', items=[]))
    mine = upload_file(customer, SimpleUploadedFile('me.jpg', jpeg(), 'image/jpeg'))
    state = followed(customer, deck, act(customer, deck, 'upload', section_id=LIST, asset_id=str(mine.pk)))
    assert state['status'] == 'done', state
    assert section(deck, LIST)['layout'] == 'image_full'
    data = data_of(deck)
    assert LIST in chosen_photos(data), 'the picture pinned is the picture drawn'


def test_a_deleted_slide_put_back_never_takes_a_deck_past_its_pictures(customer, deck, monkeypatch):  # noqa: F811
    monkeypatch.setattr(deck_photos, 'PER_DECK', 2)
    sections = data_of(deck)['content']['sections']
    photo_slide = next(s for s in sections if s['id'] == PHOTO)
    save_content(customer, deck, lambda content: content['sections'].remove(next(s for s in content['sections'] if s['id'] == PHOTO)))
    mine = upload_file(customer, SimpleUploadedFile('me.jpg', jpeg(), 'image/jpeg'))
    assert followed(customer, deck, act(customer, deck, 'upload', section_id=LIST, asset_id=str(mine.pk)))['status'] == 'done'
    save_content(customer, deck, lambda content: content['sections'].insert(5, photo_slide))
    data = data_of(deck)
    assert len(chosen_photos(data)) <= 2 and len(deck_photos.pinned(data)) <= 2


def test_deleting_a_deck_gives_back_none_of_the_days_fills(customer, stock_photos, request):  # noqa: F811
    first, _ = generate(customer)
    second, _ = generate(customer)
    request.getfixturevalue('pixabay').hits = []
    for _ in range(deck_photos.FILLS_PER_DAY):
        assert followed(customer, first, act(customer, first, 'fill'))['status'] == 'done'
    assert login_client(customer).delete(f'/api/v1/generation/drafts/{first.id}').status_code == 200
    assert ProviderUsage.objects.filter(provider='pixabay', job__isnull=True).count() == deck_photos.FILLS_PER_DAY
    kept = EditorTask.objects.filter(kind='photos')
    assert kept.count() == deck_photos.FILLS_PER_DAY and not kept.filter(draft__isnull=False).exists()
    assert not kept.filter(encrypted_payload__isnull=False).exists() and not kept.filter(encrypted_result__isnull=False).exists(), 'nothing of the deck stays'
    refused = act(customer, second, 'fill')
    assert refused.status_code == 429 and refused.json()['error']['message_params']['limit_kind'] == 'fill'
