"""Posts the owner writes in the admin (Admin → Posts) and sends to the bot's users.

This half decides who a post goes to, keeps its image, starts and stops it,
records the tap that counts as a view, and counts. telegram/posts.py sends.

Telegram tells a bot nothing about who read its messages, so a view is a tap on
the one button under a post: "delivered" is what Telegram accepted, "viewed" is
who tapped.
"""
import os
import re
import secrets
import uuid

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.db.models.functions import Lower
from django.utils import timezone

from .errors import DomainError
from .models import Account, Post, PostRecipient

AUDIENCES = ('everyone', 'free', 'plus', 'premium', 'paid', 'usernames')
PAID = ('plus', 'premium')
# Telegram's limits, in its own units (UTF-16 code units: an emoji is two).
TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024
BUTTON_LIMIT = 64
IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_PIXELS = 40_000_000
IMAGE_EDGE = 2400
PEOPLE_LIMIT = 500
# Telegram usernames; collectible ones can be four characters long.
NAME = re.compile(r'[A-Za-z][A-Za-z0-9_]{3,31}')
LINK = re.compile(r'(?:https?://)?(?:t\.me|telegram\.me)/', re.IGNORECASE)
# Rows still on their way: a post is sent once none are left.
WAITING = ('pending', 'retrying', 'sending')


def telegram_length(text):
    return len(text.encode('utf-16-le')) // 2


def reachable():
    """Everyone a post can go to: people with Telegram who have not asked to be deleted.

    Test accounts are left out, except on a development machine, where the local
    bot simulator's people are the only ones there are."""
    query = Account.objects.filter(telegram_user_id__isnull=False, deletion_requested_at__isnull=True)
    return query if settings.DEBUG else query.filter(is_test=False)


def parse_usernames(text):
    """What the owner typed for "specific people": @names, t.me links and
    Telegram ids, separated by commas, spaces or new lines.

    Returns (entries, invalid): entries without the @ and without repeats, ids as
    digits; invalid, what is neither."""
    entries, invalid, seen = [], [], set()
    for raw in re.split(r'[\s,;]+', text or ''):
        entry = LINK.sub('', raw.strip(), count=1).strip('@/')
        key = entry.casefold()
        if not entry or key in seen:
            continue
        seen.add(key)
        if entry.isascii() and entry.isdigit() and 0 < int(entry) < 2**63:
            entries.append(entry)
        elif NAME.fullmatch(entry):
            entries.append(entry)
        else:
            invalid.append(raw.strip())
    return entries, invalid


def resolve_usernames(entries):
    """[(entry, account or None, ambiguous)] in the order typed.

    An id is exact. A username is only what the person had the last time they
    used the bot, and two accounts can have held the same one: the newest
    account is taken and the entry is marked so the owner can check the name."""
    ids = {int(entry) for entry in entries if entry.isdigit()}
    names = {entry.casefold() for entry in entries if not entry.isdigit()}
    by_id, by_name = {}, {}
    if ids or names:
        query = reachable().annotate(handle=Lower('username')).filter(
            Q(telegram_user_id__in=ids) | (Q(handle__in=names) & ~Q(username='')))
        for account in query.order_by('-created_at'):
            if account.telegram_user_id in ids:
                by_id[account.telegram_user_id] = account
            if account.handle in names:
                by_name.setdefault(account.handle, []).append(account)
    rows = []
    for entry in entries:
        if entry.isdigit():
            rows.append((entry, by_id.get(int(entry)), False))
        else:
            found = by_name.get(entry.casefold(), [])
            rows.append((entry, found[0] if found else None, len(found) > 1))
    return rows


def audience(post_or_audience, usernames=''):
    """The accounts a post goes to, each with its plan now as `current_plan`."""
    from apps.commerce.services import annotate_effective_plan
    if isinstance(post_or_audience, Post):
        kind, usernames = post_or_audience.audience, post_or_audience.usernames
    else:
        kind = post_or_audience
    query = reachable()
    if kind == 'usernames':
        found = {account.pk for _, account, _ in resolve_usernames(parse_usernames(usernames)[0]) if account}
        query = query.filter(pk__in=found)
    query = annotate_effective_plan(query)
    if kind == 'paid':
        return query.filter(current_plan__in=PAID)
    if kind in ('free', 'plus', 'premium'):
        return query.filter(current_plan=kind)
    return query


def preview(post):
    """Who the post would reach if it were sent now, for the confirm step."""
    data = {'count': audience(post).count(), 'found': [], 'not_found': [], 'invalid': [], 'ambiguous': []}
    if post.audience == 'usernames':
        entries, data['invalid'] = parse_usernames(post.usernames)
        for entry, account, ambiguous in resolve_usernames(entries):
            if not account:
                data['not_found'].append(entry)
                continue
            data['found'].append({'entry': entry, 'account': account, 'ambiguous': ambiguous})
            if ambiguous:
                data['ambiguous'].append(entry)
    return data


def clean_image(raw):
    import io
    from PIL import Image
    from .images import clean_photo
    if len(raw) > IMAGE_BYTES:
        raise DomainError('post_image_too_large', 413)
    try:
        data = clean_photo(raw, max_bytes=IMAGE_BYTES, max_pixels=IMAGE_PIXELS, edge=IMAGE_EDGE)
    except Exception:
        raise DomainError('post_image_invalid') from None
    with Image.open(io.BytesIO(data)) as picture:
        width, height = picture.size
    # Telegram refuses a photo more than 20 times as long as it is wide.
    if max(width, height) > 20 * min(width, height):
        raise DomainError('post_image_shape')
    return data


def _write_image(key, data):
    from .services import storage_path
    path = storage_path(key)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('xb') as output:
        os.chmod(path, 0o600)
        output.write(data)


def create(actor, *, text, audience_kind, usernames='', button_label='', image=None):
    """A draft: nothing is sent until the owner confirms it on its page."""
    text = (text or '').replace('\r\n', '\n').strip()
    button_label = ' '.join((button_label or '').split())
    if not text:
        raise DomainError('post_text_required')
    if telegram_length(text) > (CAPTION_LIMIT if image else TEXT_LIMIT):
        raise DomainError('post_text_too_long')
    if len(button_label) > BUTTON_LIMIT:
        raise DomainError('post_button_too_long')
    if audience_kind not in AUDIENCES:
        raise DomainError('post_audience_invalid')
    if audience_kind == 'usernames':
        entries, invalid = parse_usernames(usernames)
        if not entries and not invalid:
            raise DomainError('post_people_required')
        if len(entries) + len(invalid) > PEOPLE_LIMIT:
            raise DomainError('post_people_too_many')
        usernames = '\n'.join(line.strip() for line in usernames.replace('\r\n', '\n').strip().split('\n'))
    elif (usernames or '').strip():
        # People typed in, but another audience chosen: never guess which was meant.
        raise DomainError('post_people_unused')
    else:
        usernames = ''
    data = clean_image(image) if image else None
    from . import storage
    from .services import storage_path
    post_id, key = uuid.uuid4(), ''
    if data:
        key = f'posts/{post_id}/{secrets.token_hex(8)}.jpg'
        _write_image(key, data)
    try:
        with transaction.atomic():
            post = Post.objects.create(id=post_id, created_by=actor, text=text, button_label=button_label,
                                       audience=audience_kind, usernames=usernames, image_key=key)
            if key:
                storage.save(key, 'image/jpeg')
    except BaseException:
        if key:
            storage_path(key).unlink(missing_ok=True)
        raise
    return post


def _draft(post_id):
    post = Post.objects.select_for_update().filter(pk=post_id).first()
    if not post:
        raise DomainError('not_found', 404)
    if post.status != 'draft':
        raise DomainError('post_not_draft', 409)
    return post


def _reset(row, **fields):
    now = timezone.now()
    values = {'status': 'pending', 'attempts': 0, 'next_attempt_at': now, 'lease_until': None,
              'message_id': None, 'error_code': '', 'delivered_at': None, 'viewed_at': None}
    values.update(fields)
    for name, value in values.items():
        setattr(row, name, value)
    row.save(update_fields=list(values))


@transaction.atomic
def send_test(post_id, entry):
    """The draft sent to one person (usually the owner) to see how it looks.
    Test sends are never counted."""
    post = _draft(post_id)
    entries, _ = parse_usernames(entry)
    rows = resolve_usernames(entries[:1])
    account = rows[0][1] if rows else None
    if not account:
        raise DomainError('post_test_not_found')
    row = PostRecipient.objects.select_for_update().filter(post=post, account=account).first()
    if row and row.status == 'sending':
        # The last test is on its way; resetting it would send it twice.
        return row
    if row:
        _reset(row, is_test=True)
    else:
        row = PostRecipient.objects.create(post=post, account=account, is_test=True, plan_at_send=account.plan)
    return row


@transaction.atomic
def start(post_id):
    """Send a draft to its audience as it stands now."""
    post = _draft(post_id)
    people = dict(audience(post).values_list('pk', 'current_plan'))
    if not people:
        raise DomainError('post_audience_empty', 409)
    # Someone who already has the post from a test keeps that message: it is the
    # same post, so it now counts, and they are not sent it twice. So does a test
    # on its way or cut off on the way (it may have arrived). A test that did not
    # arrive is sent again with everyone else's.
    for row in PostRecipient.objects.select_for_update().filter(post=post, is_test=True, account_id__in=people):
        if row.status in ('delivered', 'sending') or (row.status, row.error_code) == ('failed', 'interrupted'):
            row.is_test, row.plan_at_send = False, people[row.account_id]
            row.save(update_fields=['is_test', 'plan_at_send'])
        else:
            _reset(row, is_test=False, plan_at_send=people[row.account_id])
    now = timezone.now()
    PostRecipient.objects.bulk_create(
        (PostRecipient(post=post, account_id=pk, plan_at_send=plan, next_attempt_at=now, created_at=now)
         for pk, plan in people.items()), batch_size=1000, ignore_conflicts=True)
    post.audience_count, post.status, post.started_at = len(people), 'sending', now
    post.save(update_fields=['audience_count', 'status', 'started_at'])
    # Everyone may already have it from a test.
    if settle(now):
        post.refresh_from_db()
    return post


@transaction.atomic
def stop(post_id):
    """No more sends; what has arrived stays, and so do its views."""
    post = Post.objects.select_for_update().filter(pk=post_id).first()
    if not post:
        raise DomainError('not_found', 404)
    if post.status != 'sending':
        raise DomainError('post_not_sending', 409)
    now = timezone.now()
    PostRecipient.objects.filter(post=post, is_test=False, status__in=('pending', 'retrying')).update(
        status='skipped', error_code='stopped', lease_until=None)
    post.status, post.finished_at = 'stopped', now
    post.save(update_fields=['status', 'finished_at'])
    return post


def discard(post_id):
    """A draft deleted with its image. A post that went out stays as a record."""
    from . import storage
    with transaction.atomic():
        post = _draft(post_id)
        key = post.image_key
        post.delete()
    storage.delete(key)


def settle(now=None):
    """Posts with nothing left on its way are sent. Returns how many finished.

    A stopped post's copy that was on its way when it stopped is put away too:
    one that came back to be tried again is not sent, one cut off is counted as
    cut off (a tap can still prove it arrived)."""
    now = now or timezone.now()
    stopped = PostRecipient.objects.filter(post__status='stopped', is_test=False)
    stopped.filter(status__in=('pending', 'retrying')).update(status='skipped', error_code='stopped', lease_until=None)
    stopped.filter(status='sending', lease_until__lte=now).update(status='failed', error_code='interrupted',
                                                                  lease_until=None)
    waiting = PostRecipient.objects.filter(status__in=WAITING, is_test=False)
    finished = 0
    for post in Post.objects.filter(status='sending').exclude(pk__in=waiting.values('post_id')).only('pk'):
        finished += Post.objects.filter(pk=post.pk, status='sending').update(status='sent', finished_at=now)
    return finished


def record_view(token, telegram_user_id):
    """A tap on a post's button. The row it was for, or None when the button is
    not this person's (or the post is gone)."""
    try:
        pk = uuid.UUID(hex=token)
    except (TypeError, ValueError):
        return None
    row = PostRecipient.objects.select_related('account').filter(pk=pk).first()
    if not row or row.account.telegram_user_id != telegram_user_id:
        return None
    now = timezone.now()
    PostRecipient.objects.filter(pk=pk, viewed_at__isnull=True).update(viewed_at=now)
    # The tap proves the copy arrived: one cut off on the way, or one waiting to
    # be tried again after an error, is delivered and never sent again. One on
    # its way now is left to its own result.
    PostRecipient.objects.filter(pk=pk, status__in=('retrying', 'failed')).update(
        status='delivered', delivered_at=now, error_code='', lease_until=None)
    return row


def stats(post):
    """The post's numbers. Test sends are not in them."""
    rows = PostRecipient.objects.filter(post=post, is_test=False)
    counts = dict(rows.values('status').annotate(n=Count('pk')).values_list('status', 'n'))
    delivered = counts.get('delivered', 0)
    viewed = rows.filter(viewed_at__isnull=False).count()
    done = sum(counts.get(status, 0) for status in ('delivered', 'failed', 'blocked'))
    total = post.audience_count or sum(counts.values())
    return {
        'audience': total, 'delivered': delivered, 'viewed': viewed,
        'viewed_share': round(100 * viewed / delivered) if delivered else 0,
        'failed': counts.get('failed', 0), 'blocked': counts.get('blocked', 0),
        'waiting': sum(counts.get(status, 0) for status in WAITING), 'skipped': counts.get('skipped', 0),
        'done': done, 'progress': round(100 * (done + counts.get('skipped', 0)) / total) if total else 0,
    }
