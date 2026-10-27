"""Posts: messages the owner sends to the bot's users, and who saw them.

Administrators only. A post is written as a draft and checked on its own page
(who it reaches, a test to oneself) before it is sent; the same page then shows
how many it reached and who tapped its button (apps/core/posts.py,
telegram/posts.py).
"""
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.core import posts
from apps.core.errors import DomainError
from apps.core.models import Post, PostRecipient
from .auth import audit, require_staff
from .i18n import get_locale
from .views import context, finish_render

SHOW = {
    'viewed': Q(viewed_at__isnull=False),
    'not_viewed': Q(status='delivered', viewed_at__isnull=True),
    'not_reached': Q(status__in=('failed', 'blocked', 'skipped')),
}


def _error(t, code):
    return t.get('post_error_' + code.removeprefix('post_'), t['post_error_generic'])


def _page(request, pk, **params):
    query = '&'.join(f'{key}={value}' for key, value in params.items())
    return redirect(f'/ops/posts/{pk}?lang={get_locale(request)}' + (f'&{query}' if query else ''))


def _title(post, length=80):
    line = ' '.join(post.text.split())
    return line if len(line) <= length else line[:length].rstrip() + '…'


@require_staff()
@require_GET
def post_list(request):
    data = context(request, 'posts')
    t = data['t']
    shown = Q(recipients__is_test=False)
    rows = Post.objects.select_related('created_by').annotate(
        delivered=Count('recipients', filter=shown & Q(recipients__status='delivered')),
        viewed=Count('recipients', filter=shown & Q(recipients__viewed_at__isnull=False)),
    ).order_by('-created_at')
    pagination = Paginator(rows, 30).get_page(request.GET.get('p'))
    data.update(pagination=pagination, q=f'lang={data["lang"]}',
                rows=[{'post': post, 'title': _title(post), 'audience': t['post_audience_' + post.audience],
                       'status': t['post_status_' + post.status]} for post in pagination],
                saved=t.get('post_saved_' + request.GET.get('saved', ''), ''))
    return finish_render(request, 'ops/posts.html', data)


@require_staff()
@require_http_methods(['GET', 'POST'])
def post_compose(request):
    data = context(request, 'posts')
    t = data['t']
    form = {'text': '', 'button_label': '', 'audience': 'everyone', 'usernames': ''}
    if request.method == 'POST':
        form = {key: request.POST.get(key, '') for key in form}
        upload = request.FILES.get('image')
        try:
            # One byte over the limit is enough to refuse it.
            raw = upload.read(posts.IMAGE_BYTES + 1) if upload else None
            post = posts.create(request.ops_user, text=form['text'], audience_kind=form['audience'],
                                usernames=form['usernames'], button_label=form['button_label'], image=raw)
        except DomainError as error:
            data['error'] = _error(t, error.code)
        else:
            audit(request.ops_user, 'post.created', post.pk,
                  after={'audience': post.audience, 'image': bool(post.image_key)})
            return _page(request, post.pk, saved='created')
    data.update(form=form, audiences=[(key, t['post_audience_' + key]) for key in posts.AUDIENCES],
                text_limit=posts.TEXT_LIMIT, button_limit=posts.BUTTON_LIMIT)
    return finish_render(request, 'ops/post_compose.html', data)


@require_staff()
@require_GET
def post_detail(request, pk):
    post = get_object_or_404(Post.objects.select_related('created_by'), pk=pk)
    data = context(request, 'posts')
    t = data['t']
    stats = posts.stats(post)
    show = request.GET.get('show', 'viewed')
    show = show if show in SHOW else 'viewed'
    people = (PostRecipient.objects.filter(post=post, is_test=False).filter(SHOW[show]).select_related('account')
              .order_by('-viewed_at' if show == 'viewed' else '-delivered_at', 'created_at'))
    pagination = Paginator(people, 50).get_page(request.GET.get('p'))
    preview = posts.preview(post) if post.status == 'draft' else None
    tiles = [
        {'label': t['post_reach'] if preview else t['post_audience'],
         'value': preview['count'] if preview else stats['audience'], 'note': ''},
    ]
    if not preview:
        tiles += [
            {'label': t['post_delivered'], 'value': stats['delivered'],
             'note': t['post_waiting'].format(n=stats['waiting']) if stats['waiting'] else ''},
            {'label': t['post_viewed'], 'value': stats['viewed'],
             'note': t['post_viewed_share'].format(n=stats['viewed_share'])},
            {'label': t['post_not_reached'], 'value': stats['failed'] + stats['blocked'] + stats['skipped'],
             'note': t['post_not_reached_desc']},
        ]
    code = request.GET.get('error', '')
    data.update(
        post=post, title=_title(post), stats=stats, tiles=tiles, preview=preview, show=show,
        shows=[(key, t['post_show_' + key]) for key in SHOW], people=pagination,
        rows=[{'row': row, 'status': t['post_recipient_' + row.status]} for row in pagination],
        q=f'lang={data["lang"]}&show={show}',
        tests=[{'row': row, 'status': t['post_recipient_' + row.status]}
               for row in PostRecipient.objects.filter(post=post, is_test=True).select_related('account')
               .order_by('-created_at')],
        audience_label=t['post_audience_' + post.audience], status_label=t['post_status_' + post.status],
        button_label=post.button_label or t['post_button_default'],
        paused=post.status == 'sending' and post.paused_until and post.paused_until > timezone.now(),
        saved=t.get('post_saved_' + request.GET.get('saved', ''), ''),
        error=_error(t, code) if code else '',
        send_confirm=t['post_send_confirm'].format(n=preview['count']) if preview else '',
    )
    return finish_render(request, 'ops/post.html', data)


@require_staff()
@require_POST
def post_send(request, pk):
    try:
        post = posts.start(pk)
    except DomainError as error:
        return _page(request, pk, error=error.code)
    audit(request.ops_user, 'post.sent', post.pk,
          after={'audience': post.audience, 'count': post.audience_count, 'image': bool(post.image_key)})
    return _page(request, pk, saved='sent')


@require_staff()
@require_POST
def post_test(request, pk):
    try:
        row = posts.send_test(pk, request.POST.get('person', '')[:200])
    except DomainError as error:
        return _page(request, pk, error=error.code)
    audit(request.ops_user, 'post.test', pk, after={'account': str(row.account_id)})
    return _page(request, pk, saved='test')


@require_staff()
@require_POST
def post_stop(request, pk):
    try:
        post = posts.stop(pk)
    except DomainError as error:
        return _page(request, pk, error=error.code)
    audit(request.ops_user, 'post.stopped', post.pk, after=posts.stats(post))
    return _page(request, pk, saved='stopped')


@require_staff()
@require_POST
def post_discard(request, pk):
    try:
        posts.discard(pk)
    except DomainError as error:
        return _page(request, pk, error=error.code)
    audit(request.ops_user, 'post.discarded', pk)
    return redirect(f'/ops/posts?lang={get_locale(request)}&saved=discarded')


@require_staff()
@require_GET
def post_image(request, pk):
    from apps.core import storage
    post = Post.objects.filter(pk=pk).exclude(image_key='').first()
    if not post:
        raise Http404()
    path = storage.local(post.image_key)
    if not path.is_file():
        raise Http404()
    response = FileResponse(path.open('rb'), content_type='image/jpeg')
    response['Content-Disposition'] = 'inline; filename="post.jpg"'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'no-store, private'
    response['Content-Security-Policy'] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
    return response
