"""Stock photos: the one place the server fetches a URL it did not write.

Every network call here goes through a fake `_open`, and the suite-wide guard in
conftest makes any test that forgets fail rather than reach Pixabay.
"""
import io
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from PIL import Image
from django.utils import timezone

from apps.studio import photos
from apps.studio.models import PhotoSearch, ProviderUsage
from operations.integrations import save_config

pytestmark = pytest.mark.django_db
KEY = '12345678-0123456789abcdef0123456789abcdef'


def jpeg(width=1600, height=1000, **kwargs):
    buffer = io.BytesIO()
    Image.new('RGB', (width, height), (110, 140, 160)).save(buffer, 'JPEG', quality=85, **kwargs)
    return buffer.getvalue()


def hit(n, url=None):
    return {'id': n, 'type': 'photo', 'imageWidth': 1920, 'imageHeight': 1280,
            'pageURL': f'https://pixabay.com/photos/x-{n}/',
            'largeImageURL': url or f'https://pixabay.com/get/img{n}_1280.jpg'}


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class Network:
    """A stand-in Pixabay: searches answer with `hits`, downloads with `image`."""

    def __init__(self, hits=None, image=None, fail=None):
        self.hits = [hit(n) for n in range(1, 9)] if hits is None else hits
        self.image, self.fail = image or jpeg(), fail
        self.calls = []

    def __call__(self, request, timeout, handler):
        self.calls.append((request.full_url, timeout, handler))
        if self.fail:
            raise self.fail
        if request.full_url.startswith(photos.API):
            return Response(json.dumps({'total': 99, 'totalHits': 99, 'hits': self.hits}).encode())
        return Response(self.image)

    @property
    def searches(self):
        return [url for url, _, _ in self.calls if url.startswith(photos.API)]


@pytest.fixture
def pixabay(monkeypatch):
    save_config('pixabay', {'pixabay_key': KEY, 'enabled': 'true'})
    network = Network()
    monkeypatch.setattr(photos, '_open', network)
    return network


def slides(*queries, layout='image_split'):
    first = {'id': 's1', 'heading': 'Deck', 'body': 'Sub', 'notes': '', 'layout': 'cover',
             'items': [], 'columns': [], 'image_query': ''}
    return [first] + [{'id': f's{n + 2}', 'heading': 'H', 'body': 'a\nb', 'notes': '', 'layout': layout,
                       'items': [], 'columns': [], 'image_query': query} for n, query in enumerate(queries)]


# ---------------------------------------------------------------- the pin


@pytest.mark.parametrize('url,ok', [
    ('https://pixabay.com/get/abc.jpg', True),
    ('https://cdn.pixabay.com/photo/2020/x.jpg', True),
    ('https://PIXABAY.com/get/abc.jpg', True),
    ('http://pixabay.com/get/abc.jpg', False),
    ('https://pixabay.com.evil.net/x.jpg', False),
    ('https://evilpixabay.com/x.jpg', False),
    ('https://user:pw@pixabay.com/x.jpg', False),
    ('https://pixabay.com:8443/x.jpg', False),
    ('https://pixabay.com /x.jpg', False),
    ('https://169.254.169.254/latest/meta-data', False),
    ('file:///etc/passwd', False),
    ('https://pixabay.com/' + 'x' * 2100, False),
    (None, False),
])
def test_only_pixabay_urls_are_ever_fetched(url, ok):
    assert photos._image_url_ok(url) is ok


def test_a_download_may_only_be_redirected_to_another_pixabay_host():
    import urllib.request
    request = urllib.request.Request('https://pixabay.com/get/x.jpg')
    with pytest.raises(ValueError):
        photos._PinnedRedirect().redirect_request(request, None, 302, 'Found', {}, 'https://evil.example/x.jpg')
    hops = photos._PinnedRedirect()
    for _ in range(photos.MAX_REDIRECTS):
        followed = hops.redirect_request(request, None, 302, 'Found', {}, 'https://cdn.pixabay.com/x.jpg')
        assert followed.full_url == 'https://cdn.pixabay.com/x.jpg'
    with pytest.raises(ValueError):
        hops.redirect_request(request, None, 302, 'Found', {}, 'https://cdn.pixabay.com/x.jpg')


def test_every_search_is_safe_and_refuses_redirects(pixabay):
    from apps.studio.provider import _NoRedirect
    photos.search('modern office', KEY)
    url, timeout, handler = pixabay.calls[-1]
    query = parse_qs(urlsplit(url).query)
    assert url.startswith('https://pixabay.com/api/?')
    assert query['safesearch'] == ['true'], 'Pixabay defaults safesearch to false'
    assert query['image_type'] == ['photo'] and query['lang'] == ['en']
    assert query['orientation'] == ['horizontal'] and query['q'] == ['modern office']
    assert isinstance(handler, _NoRedirect), 'the key is in the URL, so the API may not redirect'
    assert timeout == photos.SEARCH_TIMEOUT


def test_a_hit_pointing_anywhere_but_pixabay_is_dropped(pixabay):
    pixabay.hits = [hit(1, 'https://evil.example/x.jpg'), {'id': 'x'}, hit(2), {'type': 'video'}]
    found = photos.search('office', KEY)
    assert [h['id'] for h in found] == [2]


# ---------------------------------------------------------------- the bytes


def test_a_photo_is_resized_reencoded_and_stripped_of_exif():
    exif = Image.Exif()
    exif[0x0112] = 6            # rotated 90 degrees
    exif[0x010F] = 'CameraMaker'
    prepared = photos.prepare(jpeg(3000, 2000, exif=exif.tobytes()))
    with Image.open(io.BytesIO(prepared['jpeg'])) as picture:
        assert picture.format == 'JPEG'
        assert max(picture.size) <= photos.LONG_EDGE
        assert picture.size == (prepared['width'], prepared['height'])
        assert picture.height > picture.width, 'the orientation was applied'
        assert not picture.getexif(), 'nothing from the source file survives'
    assert len(prepared['jpeg']) <= photos.MAX_JPEG


def _webp():
    buffer = io.BytesIO()
    Image.new('RGB', (1600, 1000)).save(buffer, 'WEBP')
    return buffer.getvalue()


def _gif():
    buffer = io.BytesIO()
    frames = [Image.new('P', (400, 300), n) for n in range(3)]
    frames[0].save(buffer, 'GIF', save_all=True, append_images=frames[1:])
    return buffer.getvalue()


@pytest.mark.parametrize('raw', [
    pytest.param(lambda: _webp(), id='webp'),
    pytest.param(lambda: _gif(), id='animated'),
    pytest.param(lambda: jpeg(3100, 2000), id='too-many-pixels'),
    pytest.param(lambda: jpeg()[:600], id='truncated'),
    pytest.param(lambda: b'not an image at all', id='garbage'),
])
def test_bytes_that_are_not_a_plain_photo_are_refused(raw):
    with pytest.raises(Exception):
        photos.prepare(raw())


def test_an_oversized_download_is_refused_before_it_is_decoded(pixabay):
    pixabay.image = b'x' * (photos.IMAGE_BYTES + 10)
    with pytest.raises(ValueError):
        photos.download('https://pixabay.com/get/big.jpg')


# ---------------------------------------------------------------- the deck


def test_photos_are_fetched_for_the_slides_that_want_them(pixabay):
    result = photos.fetch_for_deck(slides('office', 'team meeting'), cap=6, budget=30)
    assert set(result.photos) == {'s2', 's3'} and not result.failed and not result.warnings
    assert result.photos['s2']['id'] != result.photos['s3']['id'], 'no photo twice in a deck'
    assert result.photos['s2']['page_url'].startswith('https://pixabay.com/')


def test_a_search_is_cached_for_a_day_and_only_its_hash_is_stored(pixabay):
    photos.fetch_for_deck(slides('office'), cap=6, budget=30)
    assert len(pixabay.searches) == 1
    photos.fetch_for_deck(slides('office'), cap=6, budget=30)
    assert len(pixabay.searches) == 1, 'a second deck within the day reuses the answer'
    row = PhotoSearch.objects.get()
    assert 'office' not in row.key and 'office' not in json.dumps(row.hits).replace('pixabay.com/photos', '')
    PhotoSearch.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    photos.fetch_for_deck(slides('office'), cap=6, budget=30)
    assert len(pixabay.searches) == 2, 'an expired answer is asked for again'


def test_the_plan_decides_how_many_photos_a_deck_gets(pixabay):
    result = photos.fetch_for_deck(slides('a', 'b', 'c', 'd', 'e'), cap=2, budget=30)
    assert len(result.photos) == 2 and result.limited == 3
    assert result.warnings == ['images_limited']
    assert list(result.photos) == ['s2', 's3'], 'the first slides in the deck get them'


@pytest.mark.parametrize('failure', [TimeoutError('slow'), OSError('down'), ValueError('bad')])
def test_a_provider_that_fails_costs_only_the_photos(pixabay, failure):
    pixabay.fail = failure
    result = photos.fetch_for_deck(slides('office', 'team'), cap=6, budget=30)
    assert result.photos == {} and result.failed == 2 and result.warnings == ['images_skipped']


def test_nothing_is_fetched_when_photos_are_switched_off(monkeypatch):
    network = Network()
    monkeypatch.setattr(photos, '_open', network)
    save_config('pixabay', {'pixabay_key': KEY, 'enabled': 'false'})
    result = photos.fetch_for_deck(slides('office'), cap=6, budget=30)
    assert network.calls == [] and result.photos == {} and result.warnings == []


def test_the_shared_rate_limit_holds_calls_under_pixabays(pixabay, monkeypatch):
    from apps.core.errors import DomainError

    def exhausted(*args, **kwargs):
        raise DomainError('rate_limited', 429)

    monkeypatch.setattr('apps.core.customer_auth.auth_limit', exhausted)
    result = photos.fetch_for_deck(slides('office'), cap=6, budget=30)
    assert pixabay.searches == [] and result.warnings == ['images_skipped']


# ---------------------------------------------------------------- the job


@pytest.fixture
def paid_deck(settings, monkeypatch):
    from apps.studio import provider
    from tests.test_page_fill import live
    customer = live(settings)
    answer = {'title': 'Deck', 'answer_supported': True, 'citations': [], 'questions': [],
              'sections': slides('modern office', 'team meeting')}
    monkeypatch.setattr(provider, 'generate', lambda *args, **kwargs: (answer, {'input_tokens': 1, 'output_tokens': 1}))
    return customer


def _run(customer):
    from apps.core.services import execute_job, submit_job
    from apps.studio.domain import SLIDES, create_draft, generation_quote
    draft = create_draft(customer, {'feature_id': SLIDES, 'prompt': 'A 3 slide deck about our office.'})
    quote = generation_quote(customer, draft.id, draft.version)
    job, _ = submit_job(customer, quote.id, f'photos-{draft.id}')
    return quote, execute_job(job.id)


def test_a_paid_deck_carries_its_photos_and_their_licence_record(paid_deck, pixabay):
    from pptx import Presentation
    from apps.core.services import storage_path
    quote, job = _run(paid_deck)
    assert job.status == 'succeeded', job.error_code
    artifact = job.artifacts.get().file
    deck = Presentation(str(storage_path(artifact.object_key)))
    assert len(deck.slides) == 3
    assert sum(shape.shape_type == 13 for slide in deck.slides for shape in slide.shapes) == 2
    assert [entry['slide'] for entry in artifact.metadata['photos']] == [2, 3]
    assert all(entry['provider'] == 'pixabay' and entry['id'] for entry in artifact.metadata['photos'])
    assert ProviderUsage.objects.get(job=job, provider='pixabay').outcome == 'succeeded'
    assert 'images_skipped' not in job.warnings


def test_a_paid_deck_whose_photos_fail_is_still_delivered_and_billed_the_same(paid_deck, pixabay):
    from apps.core.models import UsageLedger
    pixabay.fail = OSError('down')
    quote, job = _run(paid_deck)
    assert job.status == 'succeeded', job.error_code
    assert job.artifacts.get().file.page_count == 3, 'the photo slides are drawn as text'
    assert 'images_skipped' in job.warnings
    consumed = sum(UsageLedger.objects.filter(job=job, kind='consume', meter='ai_credits')
                   .values_list('amount', flat=True))
    assert 0 < consumed <= quote.meters['ai_credits']
    assert ProviderUsage.objects.get(job=job, provider='pixabay').outcome == 'failed'


def test_the_key_never_leaves_the_encrypted_store(paid_deck, pixabay, caplog):
    pixabay.fail = OSError(f'refused https://pixabay.com/api/?key={KEY}')
    _, job = _run(paid_deck)
    record = json.dumps({'warnings': job.warnings, 'error': job.error_code,
                         'metadata': job.artifacts.get().file.metadata,
                         'usage': list(ProviderUsage.objects.values())}, default=str)
    assert KEY not in record and KEY not in caplog.text


def test_the_model_is_told_the_plan_allowance_only_when_photos_are_on(settings):
    from apps.studio.domain import SLIDES, create_draft, unpack
    from tests.test_platform import account
    settings.DEBUG = True
    customer = account()
    options = lambda: unpack(create_draft(customer, {'feature_id': SLIDES, 'prompt': 'A 4 slide deck.',
                                                     'options': {'image_cap': 99}}).encrypted_data)['options']
    assert options()['image_cap'] == 0, 'off by default, and a client cannot raise it'
    save_config('pixabay', {'pixabay_key': KEY, 'enabled': 'true'})
    from apps.core.policy import plan_limits
    assert options()['image_cap'] == plan_limits(customer)['max_deck_images']


# ---------------------------------------------------------------- the admin


def test_the_pixabay_key_is_encrypted_and_never_shown(settings):
    from operations.models import IntegrationConfig
    from tests.test_operations import staff_client
    client, _ = staff_client()
    response = client.post('/ops/integrations', {'integration': 'pixabay', 'action': 'save',
                                                 'pixabay_key': KEY, 'enabled': 'true',
                                                 'reason': 'Turn on deck photos.'})
    assert response.status_code == 302
    row = IntegrationConfig.objects.get(pk='pixabay')
    assert KEY.encode() not in bytes(row.encrypted_secrets) and KEY not in json.dumps(row.configuration)
    page = client.get('/ops/integrations').content.decode()
    assert KEY not in page and 'pixabay-settings' in page
    from operations.models import AuditLog
    assert KEY not in json.dumps(list(AuditLog.objects.values()), default=str)


@pytest.mark.parametrize('bad', ['abc', '123-XYZ', 'x' * 60, '12345678-short'])
def test_a_key_that_is_not_a_pixabay_key_is_refused(bad):
    from apps.core.errors import DomainError
    with pytest.raises(DomainError, match='invalid_pixabay_key'):
        save_config('pixabay', {'pixabay_key': bad, 'enabled': 'false'})


def test_photos_cannot_be_switched_on_without_a_key():
    from apps.core.errors import DomainError
    with pytest.raises(DomainError, match='pixabay_not_configured'):
        save_config('pixabay', {'enabled': 'true'})


def test_the_photo_allowance_is_an_editable_plan_limit():
    from operations import plans
    from apps.core.policy import limits_for_plan
    assert [limits_for_plan(plan)['max_deck_images'] for plan in ('free', 'plus', 'premium')] == [2, 6, 12]
    assert plans.FIELDS['max_deck_images'] == (0, 60)
    with pytest.raises(plans.PlanError):
        plans.save('free', {'max_deck_images': '40'})
