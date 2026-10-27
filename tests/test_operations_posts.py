"""Admin → Posts: write, check, test, send, stop; who it reached and who saw it."""
import io
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from apps.core import posts, storage
from apps.core.models import Account, Post, PostRecipient, StoredObject
from operations.i18n import CATALOGS
from operations.models import AuditLog
from tests.test_object_storage import bucket  # noqa: F401  (fixture)
from tests.test_operations import staff_client

pytestmark = pytest.mark.django_db
EN = CATALOGS['en']


def picture(kind='PNG'):
    out = io.BytesIO()
    Image.new('RGB', (60, 40), 'orange').save(out, kind)
    return SimpleUploadedFile('picture.' + kind.lower(), out.getvalue(), 'image/' + kind.lower())


def reader(uid, username, **fields):
    return Account.objects.create(telegram_user_id=uid, username=username, display_name=f'Reader {uid}', **fields)


@pytest.mark.parametrize('lang', ['en', 'uz', 'ru'])
def test_every_posts_page_renders_in_every_language(lang):
    client, _ = staff_client()
    reader(7001, 'reader_one')
    draft = posts.create(None, text='Draft text', audience_kind='usernames', usernames='@reader_one nobody_here bad!')
    sent = posts.create(None, text='Sent text', audience_kind='everyone')
    posts.start(sent.pk)
    for url in ('/ops/posts', '/ops/posts/new', f'/ops/posts/{draft.pk}', f'/ops/posts/{sent.pk}',
                f'/ops/posts/{sent.pk}?show=not_viewed', f'/ops/posts/{sent.pk}?show=not_reached'):
        response = client.get(url + ('&' if '?' in url else '?') + f'lang={lang}')
        assert response.status_code == 200, url
        assert f'lang="{lang}"'.encode() in response.content and response['Cache-Control'] == 'no-store'
    page = client.get(f'/ops/posts/{draft.pk}?lang={lang}').content.decode()
    t = CATALOGS[lang]
    assert 'Reader 7001' in page and t['post_not_found'] in page and t['post_invalid'] in page
    assert t['post_send_confirm'].format(n=1) in page
    assert f'/ops/posts?lang={lang}' in client.get(f'/ops/today?lang={lang}').content.decode(), 'in the sidebar'


@pytest.mark.parametrize('role', ['Analyst', 'Support', 'Operations', 'Finance', 'Content manager'])
def test_only_administrators_reach_posts(role):
    client, _ = staff_client(role)
    post = posts.create(None, text='Hello', audience_kind='everyone')
    for url in ('/ops/posts', '/ops/posts/new', f'/ops/posts/{post.pk}', f'/ops/posts/{post.pk}/image'):
        assert client.get(url).status_code == 403, url
    for url in ('/ops/posts/new', *(f'/ops/posts/{post.pk}/{action}' for action in ('send', 'test', 'stop', 'discard'))):
        assert client.post(url, {'text': 'x', 'audience': 'everyone', 'person': '1'}).status_code == 403, url
    post.refresh_from_db()
    assert post.status == 'draft' and Post.objects.count() == 1 and not PostRecipient.objects.exists()
    assert b'/ops/posts' not in client.get('/ops/today').content


def test_post_actions_need_the_csrf_token_before_anything_happens():
    client, _ = staff_client(csrf=True)
    reader(7001, 'reader_one')
    post = posts.create(None, text='Hello', audience_kind='everyone')
    assert client.post('/ops/posts/new', {'text': 'x', 'audience': 'everyone'}).status_code == 403
    for action in ('send', 'test', 'stop', 'discard'):
        assert client.post(f'/ops/posts/{post.pk}/{action}', {'person': 'reader_one'}).status_code == 403
    post.refresh_from_db()
    assert post.status == 'draft' and Post.objects.count() == 1 and not PostRecipient.objects.exists()
    assert not AuditLog.objects.exists()


def test_writing_a_post_keeps_a_draft_and_sends_nothing():
    client, staff = staff_client()
    reader(7001, 'reader_one')
    response = client.post('/ops/posts/new?lang=en', {'text': 'Hello all\r\nSecond line', 'audience': 'everyone',
                                                      'button_label': 'Seen it', 'usernames': '', 'image': picture()})
    post = Post.objects.get()
    assert response.status_code == 302 and response['Location'] == f'/ops/posts/{post.pk}?lang=en&saved=created'
    assert (post.text, post.button_label, post.status, post.created_by) == ('Hello all\nSecond line', 'Seen it', 'draft', staff)
    assert post.image_key.startswith(f'posts/{post.pk}/') and post.image_key.endswith('.jpg')
    assert not PostRecipient.objects.exists()
    assert AuditLog.objects.get(action='post.created').after == {'audience': 'everyone', 'image': True}
    page = client.get(response['Location']).content.decode()
    assert EN['post_saved_created'] in page and 'Hello all\nSecond line' in page and 'Seen it' in page
    image = client.get(f'/ops/posts/{post.pk}/image')
    assert image['Content-Type'] == 'image/jpeg' and image['X-Content-Type-Options'] == 'nosniff'
    assert 'no-store' in image['Cache-Control'] and image['Content-Security-Policy'].startswith("default-src 'none'")
    assert b''.join(image.streaming_content)[:3] == b'\xff\xd8\xff', 're-encoded, nothing of the upload kept'
    assert client.get(f'/ops/posts/{posts.create(None, text="No image", audience_kind="free").pk}/image').status_code == 404


@pytest.mark.parametrize('fields,key', [
    ({'text': '   '}, 'post_error_text_required'),
    ({'text': 'x' * 4097}, 'post_error_text_too_long'),
    ({'text': 'x' * 1025, 'image': 'picture'}, 'post_error_text_too_long'),
    ({'button_label': 'x' * 65}, 'post_error_button_too_long'),
    ({'audience': 'vip'}, 'post_error_audience_invalid'),
    ({'audience': 'usernames', 'usernames': ''}, 'post_error_people_required'),
    ({'image': 'pdf'}, 'post_error_image_invalid'),
    ({'image': 'big'}, 'post_error_image_too_large'),
])
def test_a_post_that_cannot_be_sent_is_refused_and_the_form_kept(fields, key):
    client, _ = staff_client()
    data = {'text': 'Kept text', 'audience': 'everyone', 'button_label': '', 'usernames': ''}
    data.update(fields)
    if data.get('image') == 'picture':
        data['image'] = picture()
    elif data.get('image') == 'pdf':
        data['image'] = SimpleUploadedFile('a.png', b'%PDF-1.4 hidden pdf', 'image/png')
    elif data.get('image') == 'big':
        data['image'] = SimpleUploadedFile('a.jpg', b'\xff' * (posts.IMAGE_BYTES + 1), 'image/jpeg')
    response = client.post('/ops/posts/new?lang=en', data)
    assert response.status_code == 200
    page = response.content.decode()
    assert EN[key] in page
    if fields.get('text') is None:
        assert 'Kept text' in page
    assert not Post.objects.exists() and not StoredObject.objects.exists()


def test_sending_queues_the_audience_once_and_stopping_skips_the_rest():
    client, _ = staff_client()
    for n in range(3):
        reader(7001 + n, f'reader_{n}')
    post = posts.create(None, text='Hello', audience_kind='everyone')
    response = client.post(f'/ops/posts/{post.pk}/send?lang=en')
    assert response['Location'] == f'/ops/posts/{post.pk}?lang=en&saved=sent'
    assert PostRecipient.objects.filter(post=post, status='pending').count() == 3
    assert AuditLog.objects.get(action='post.sent').after == {'audience': 'everyone', 'count': 3, 'image': False}
    again = client.post(f'/ops/posts/{post.pk}/send?lang=en')
    assert again['Location'].endswith('error=post_not_draft') and PostRecipient.objects.count() == 3
    page = client.get(again['Location']).content.decode()
    assert EN['post_error_not_draft'] in page and EN['post_stop'] in page
    assert client.post(f'/ops/posts/{post.pk}/discard?lang=en')['Location'].endswith('error=post_not_draft')
    client.post(f'/ops/posts/{post.pk}/stop?lang=en')
    post.refresh_from_db()
    assert post.status == 'stopped' and PostRecipient.objects.filter(status='skipped').count() == 3
    assert AuditLog.objects.get(action='post.stopped').after['skipped'] == 3


def test_an_error_in_the_address_is_never_shown_as_written():
    client, _ = staff_client()
    post = posts.create(None, text='Hello', audience_kind='everyone')
    page = client.get(f'/ops/posts/{post.pk}?lang=en&error=<script>alert(1)</script>').content.decode()
    assert EN['post_error_generic'] in page and '<script>alert' not in page


def test_a_test_goes_to_one_person_and_is_not_counted():
    client, _ = staff_client()
    owner = reader(7001, 'owner_self')
    post = posts.create(None, text='Hello', audience_kind='everyone')
    response = client.post(f'/ops/posts/{post.pk}/test?lang=en', {'person': '@owner_self'})
    assert response['Location'].endswith('saved=test')
    row = PostRecipient.objects.get()
    assert row.is_test and row.account == owner and row.status == 'pending'
    assert AuditLog.objects.get(action='post.test').after == {'account': str(owner.pk)}
    missing = client.post(f'/ops/posts/{post.pk}/test?lang=en', {'person': 'nobody_here'})
    assert missing['Location'].endswith('error=post_test_not_found')
    page = client.get(f'/ops/posts/{post.pk}?lang=en').content.decode()
    assert 'Reader 7001' in page and EN['post_recipient_pending'] in page


def test_the_page_shows_who_saw_it_who_did_not_and_who_it_never_reached():
    client, _ = staff_client()
    seen, unseen, blocked = reader(7001, 'seen_it'), reader(7002, 'not_yet'), reader(7003, 'blocked_us')
    post = posts.create(None, text='Hello', audience_kind='everyone')
    posts.start(post.pk)
    now = timezone.now()
    PostRecipient.objects.filter(account=seen).update(status='delivered', delivered_at=now, viewed_at=now)
    PostRecipient.objects.filter(account=unseen).update(status='delivered', delivered_at=now)
    PostRecipient.objects.filter(account=blocked).update(status='blocked', error_code='telegram_blocked')
    posts.settle()
    page = client.get(f'/ops/posts/{post.pk}?lang=en').content.decode()
    assert '@seen_it' in page and '@not_yet' not in page and '@blocked_us' not in page
    assert EN['post_viewed_share'].format(n=50) in page and EN['post_status_sent'] in page
    page = client.get(f'/ops/posts/{post.pk}?lang=en&show=not_viewed').content.decode()
    assert '@not_yet' in page and '@seen_it' not in page
    page = client.get(f'/ops/posts/{post.pk}?lang=en&show=not_reached').content.decode()
    assert '@blocked_us' in page and EN['post_recipient_blocked'] in page
    listing = client.get('/ops/posts?lang=en').content.decode()
    assert f'/ops/posts/{post.pk}' in listing and '2 <small class="muted">/ 3</small>' in listing


@pytest.mark.django_db(transaction=True)
def test_a_posts_image_is_kept_while_the_draft_exists_and_removed_with_it(bucket):  # noqa: F811
    client, _ = staff_client()
    client.post('/ops/posts/new?lang=en', {'text': 'Hi', 'audience': 'everyone', 'image': picture('JPEG')})
    post = Post.objects.get()
    key = post.image_key
    assert key in bucket.keys()
    StoredObject.objects.filter(key=key).update(created_at=timezone.now() - timedelta(days=2))
    storage.prune()
    assert key in bucket.keys(), 'a post uses it'
    response = client.post(f'/ops/posts/{post.pk}/discard?lang=en')
    assert response['Location'] == '/ops/posts?lang=en&saved=discarded'
    assert not Post.objects.exists() and key not in bucket.keys() and not storage.storage_path(key).exists()
    assert AuditLog.objects.filter(action='post.discarded', target=str(post.pk)).exists()
    assert EN['post_saved_discarded'] in client.get(response['Location']).content.decode()


def test_an_action_on_a_post_that_is_gone_goes_back_to_the_list_and_says_so():
    client, _ = staff_client()
    post = posts.create(None, text='Hello', audience_kind='everyone')
    posts.discard(post.pk)
    for action in ('send', 'test', 'stop', 'discard'):
        response = client.post(f'/ops/posts/{post.pk}/{action}?lang=en', {'person': 'someone_here'})
        assert response['Location'] == '/ops/posts?lang=en&error=not_found', action
    assert EN['post_error_not_found'] in client.get('/ops/posts?lang=en&error=not_found').content.decode()


def test_people_typed_for_another_audience_are_refused_on_the_form():
    client, _ = staff_client()
    page = client.post('/ops/posts/new?lang=en', {'text': 'Hello', 'audience': 'everyone',
                                                  'usernames': '@crowd_one'}).content.decode()
    assert EN['post_error_people_unused'] in page and '@crowd_one' in page and not Post.objects.exists()


def test_every_person_is_listed_once_across_the_pages():
    client, _ = staff_client()
    for n in range(120):
        reader(8000 + n, f'person_{n:03}')
    post = posts.create(None, text='Hello', audience_kind='everyone')
    posts.start(post.pk)
    posts.stop(post.pk)
    seen = []
    for page in (1, 2, 3):
        html = client.get(f'/ops/posts/{post.pk}?lang=en&show=not_reached&p={page}').content.decode()
        seen += [line.split('@', 1)[1].split(' ', 1)[0] for line in html.splitlines() if '<small>@person_' in line]
    assert len(seen) == 120 and len(set(seen)) == 120


def test_a_one_time_message_does_not_follow_the_owner_to_other_pages():
    client, _ = staff_client()
    post = posts.create(None, text='Hello', audience_kind='everyone')
    import re
    page = client.get(f'/ops/posts/{post.pk}?lang=en&error=post_audience_empty&saved=sent').content.decode()
    links = re.findall(r'href="(/ops/[^"]*)"', page.split('<main', 1)[0])
    assert '/ops/posts?lang=en' in links and '/ops/users?lang=en' in links
    assert not [link for link in links if 'error=' in link or 'saved=' in link]
