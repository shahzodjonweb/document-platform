"""Who a post goes to (apps/core/posts.py): audiences by plan, people by username."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.commerce.models import SubscriptionPeriod
from apps.commerce.services import annotate_effective_plan, effective_plan
from apps.core import posts
from apps.core.errors import DomainError
from apps.core.models import Account, Post, PostRecipient
from tests.test_manual_payments import paid

pytestmark = pytest.mark.django_db


def person(uid, username='', plan=None, **fields):
    account = Account.objects.create(telegram_user_id=uid, username=username, display_name=f'Person {uid}', **fields)
    return paid(account, plan) if plan else account


@pytest.fixture
def people():
    now = timezone.now()
    return {
        'free': person(1001, 'free_one'),
        'plus': person(1002, 'plus_one', 'plus'),
        'premium': person(1003, 'premium_one', 'premium'),
        # Support comped a plan: it wins over what was paid, and lapses.
        'comped': person(1004, 'comped_one', staff_plan='premium', staff_plan_expires_at=now + timedelta(days=3)),
        'lapsed_comp': person(1005, 'lapsed_comp', staff_plan='plus', staff_plan_expires_at=now - timedelta(days=1)),
        'contained': person(1006, 'contained_one', 'premium'),
        'web_only': Account.objects.create(email='web@example.test', display_name='Web only'),
        'deleting': person(1008, 'leaving_one', deletion_requested_at=now),
        'tester': person(1009, 'tester_one', is_test=True),
    }


def ids(query):
    return {account.telegram_user_id for account in query}


def test_effective_plan_annotation_matches_effective_plan(people):
    contained = people['contained']
    contained.staff_plan = 'free'
    contained.save(update_fields=['staff_plan'])
    revoked = person(1010, 'revoked_one', 'plus')
    SubscriptionPeriod.objects.filter(account=revoked).update(revoked_at=timezone.now())
    ended = person(1011, 'ended_one', 'premium')
    SubscriptionPeriod.objects.filter(account=ended).update(ends_at=timezone.now() - timedelta(minutes=1))
    rows = annotate_effective_plan(Account.objects.filter(is_test=False))
    assert {a.pk: a.current_plan for a in rows} == {a.pk: effective_plan(a) for a in rows}
    plans = {a.telegram_user_id: a.current_plan for a in rows}
    assert plans[1004] == 'premium' and plans[1005] == 'free' and plans[1006] == 'free'
    assert plans[1010] == 'free' and plans[1011] == 'free' and plans[1002] == 'plus'


def test_audiences_follow_the_plan_in_force_not_the_cached_one(people):
    # Account.plan is a cache; a post must not trust it.
    Account.objects.filter(pk=people['free'].pk).update(plan='premium')
    assert ids(posts.audience('everyone')) == {1001, 1002, 1003, 1004, 1005, 1006}
    assert ids(posts.audience('free')) == {1001, 1005}
    assert ids(posts.audience('plus')) == {1002}
    assert ids(posts.audience('premium')) == {1003, 1004, 1006}
    assert ids(posts.audience('paid')) == {1002, 1003, 1004, 1006}


def test_test_accounts_are_an_audience_only_on_a_development_machine(people, settings):
    settings.DEBUG = True
    assert 1009 in ids(posts.audience('everyone'))
    settings.DEBUG = False
    assert 1009 not in ids(posts.audience('everyone'))


def test_usernames_are_parsed_loosely_and_checked_strictly():
    entries, invalid = posts.parse_usernames(
        '@Plus_One, premium_one\nhttps://t.me/free_one  @PLUS_ONE;1004 t.me/@comped_one bad-name! abc 0 ٣٣٣')
    assert entries == ['Plus_One', 'premium_one', 'free_one', '1004', 'comped_one']
    assert invalid == ['bad-name!', 'abc', '0', '٣٣٣']
    assert posts.parse_usernames('') == ([], [])


def test_people_are_found_by_username_or_id_and_unknowns_are_reported(people):
    post = Post.objects.create(text='Hi', audience='usernames',
                               usernames='@PLUS_ONE 1003 nobody_here leaving_one tester_one bad!')
    data = posts.preview(post)
    assert data['count'] == 2
    assert [(item['entry'], item['account'].telegram_user_id) for item in data['found']] == [('PLUS_ONE', 1002), ('1003', 1003)]
    assert data['not_found'] == ['nobody_here', 'leaving_one', 'tester_one'] and data['invalid'] == ['bad!']
    assert ids(posts.audience(post)) == {1002, 1003}


def test_a_username_two_accounts_held_goes_to_the_newest_and_is_flagged(people):
    old = people['plus']
    Account.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=30))
    newer = person(1020, 'Plus_One')
    rows = posts.resolve_usernames(['plus_one'])
    assert rows == [('plus_one', newer, True)]
    # An empty username matches nobody, however many accounts have none.
    assert posts.resolve_usernames(['1001'])[0][1].pk == people['free'].pk


def test_drafts_are_checked_before_anything_is_kept():
    def make(**kwargs):
        values = {'text': 'Hello', 'audience_kind': 'everyone'}
        values.update(kwargs)
        return posts.create(None, **values)
    for kwargs, code in [({'text': '  '}, 'post_text_required'),
                         ({'text': 'x' * 4097}, 'post_text_too_long'),
                         # Telegram counts an emoji as two.
                         ({'text': '🙂' * 2049}, 'post_text_too_long'),
                         ({'button_label': 'x' * 65}, 'post_button_too_long'),
                         ({'audience_kind': 'vip'}, 'post_audience_invalid'),
                         ({'audience_kind': 'usernames', 'usernames': ' \n '}, 'post_people_required'),
                         ({'audience_kind': 'usernames', 'usernames': ' '.join(f'user_{n:04}' for n in range(501))},
                          'post_people_too_many'),
                         ({'image': b'%PDF-1.4 not an image'}, 'post_image_invalid'),
                         ({'image': b'x' * (posts.IMAGE_BYTES + 1)}, 'post_image_too_large')]:
        with pytest.raises(DomainError) as error:
            make(**kwargs)
        assert error.value.code == code, kwargs
    assert not Post.objects.exists()
    post = make(text='Line one\r\nLine two  ', button_label='  Seen   it ', usernames='ignored')
    assert (post.text, post.button_label, post.usernames, post.status) == ('Line one\nLine two', 'Seen it', '', 'draft')


def test_sending_snapshots_the_audience_and_its_plans(people):
    post = posts.create(None, text='News', audience_kind='paid')
    started = posts.start(post.pk)
    assert started.status == 'sending' and started.audience_count == 4 and started.started_at
    plans = dict(PostRecipient.objects.filter(post=post).values_list('account__telegram_user_id', 'plan_at_send'))
    assert plans == {1002: 'plus', 1003: 'premium', 1004: 'premium', 1006: 'premium'}
    with pytest.raises(DomainError, match='post_not_draft'):
        posts.start(post.pk)


def test_an_empty_audience_is_refused():
    post = posts.create(None, text='News', audience_kind='plus')
    with pytest.raises(DomainError, match='post_audience_empty'):
        posts.start(post.pk)
    post.refresh_from_db()
    assert post.status == 'draft'


def test_a_test_that_arrived_counts_as_that_persons_copy(people):
    post = posts.create(None, text='News', audience_kind='everyone')
    test = posts.send_test(post.pk, '@free_one')
    other = posts.send_test(post.pk, 'premium_one')
    PostRecipient.objects.filter(pk=test.pk).update(status='delivered', delivered_at=timezone.now())
    PostRecipient.objects.filter(pk=other.pk).update(status='failed', attempts=5)
    with pytest.raises(DomainError, match='post_test_not_found'):
        posts.send_test(post.pk, 'nobody_here')
    posts.start(post.pk)
    rows = PostRecipient.objects.filter(post=post)
    assert rows.count() == 6 and not rows.filter(is_test=True).exists()
    test.refresh_from_db()
    other.refresh_from_db()
    assert test.status == 'delivered', 'not sent twice'
    assert (other.status, other.attempts) == ('pending', 0), 'a test that did not arrive goes out with the rest'


def test_stopping_skips_what_has_not_gone_and_keeps_what_has(people):
    post = posts.create(None, text='News', audience_kind='everyone')
    posts.start(post.pk)
    first = PostRecipient.objects.filter(post=post).order_by('created_at', 'pk').first()
    PostRecipient.objects.filter(pk=first.pk).update(status='delivered', viewed_at=timezone.now())
    posts.stop(post.pk)
    post.refresh_from_db()
    assert post.status == 'stopped' and post.finished_at
    counts = posts.stats(post)
    assert (counts['delivered'], counts['viewed'], counts['skipped'], counts['waiting']) == (1, 1, 5, 0)
    with pytest.raises(DomainError, match='post_not_sending'):
        posts.stop(post.pk)


def test_settle_finishes_a_post_with_nothing_left_on_its_way(people):
    post = posts.create(None, text='News', audience_kind='free')
    posts.start(post.pk)
    assert posts.settle() == 0
    PostRecipient.objects.filter(post=post).update(status='delivered')
    assert posts.settle() == 1
    post.refresh_from_db()
    assert post.status == 'sent' and post.finished_at


def test_a_view_is_the_owners_tap_once(people):
    post = posts.create(None, text='News', audience_kind='free')
    posts.start(post.pk)
    row = PostRecipient.objects.get(post=post, account=people['free'])
    PostRecipient.objects.filter(pk=row.pk).update(status='failed', error_code='interrupted')
    assert posts.record_view(row.id.hex, 1002) is None, 'someone else'
    assert posts.record_view('not-hex', 1001) is None
    assert posts.record_view(row.id.hex, 1001).pk == row.pk
    row.refresh_from_db()
    seen = row.viewed_at
    assert seen and row.status == 'delivered', 'the tap proves the cut-off send arrived'
    posts.record_view(row.id.hex, 1001)
    row.refresh_from_db()
    assert row.viewed_at == seen


def test_a_post_everyone_already_has_from_a_test_is_sent_at_once():
    person(1001, 'only_one')
    post = posts.create(None, text='News', audience_kind='usernames', usernames='@only_one')
    test = posts.send_test(post.pk, 'only_one')
    PostRecipient.objects.filter(pk=test.pk).update(status='delivered', delivered_at=timezone.now())
    post = posts.start(post.pk)
    assert post.status == 'sent' and post.finished_at and posts.stats(post)['delivered'] == 1
