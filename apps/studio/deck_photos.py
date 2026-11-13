"""A deck's pictures changed in the slide editor: Add to all slides, Another picture, Remove, From my phone, Find more.

None of it is an AI edit and none of it is a job, so nothing is counted against
the week or the file (allowance.edits_of reads jobs alone). The work that
fetches or reads picture bytes is a picture task in the editor lane (tasks.py),
never the request: `fill` names English search words for the slides that have
none, searches Pixabay and lets the model pick, as a paid deck's photo step
does; `next` puts a slide's next candidate on it, downloading the large copy
when only its preview is stored; `upload` makes the customer's own photo (the
web shrinks it to 1600 px first) a plain JPEG with no EXIF; `search` finds four
candidates for one slide from English words. `remove` reads no bytes, and is
done here and now.

Each that lands changes the draft and its version, as a save does: the web
saves first and holds the deck while one runs, then reads the draft back. The
cover keeps its place and words; a slide whose layout draws no picture takes
image_split, or else image_full, only if its words still all show (measured as
a send is), and is otherwise refused (`picture_no_room`): nothing is ever cut.

Pixabay's terms keep this narrow (photos.py): the `photos_task` switch, three
fills and ten searches an account a day (five a minute), twelve pictures a
deck at most and never more than the plan's, and a share of the key's rate
that leaves the rest to paid decks. Swapping to a stored candidate is free.
Provider calls are recorded against the task (ProviderUsage.task).
"""
import hashlib
import uuid

from django.db import transaction
from django.utils import timezone

from apps.core import storage
from apps.core.errors import DomainError
from apps.core.models import FileAsset

from .domain import EXPORT, draft_jobs, pack, require, unpack
from .models import EditorTask, GenerationDraft, ProviderUsage

PHOTOS = 'photos'
FILL, NEXT, UPLOAD, SEARCH, REMOVE = 'fill', 'next', 'upload', 'search', 'remove'
ACTIONS = (FILL, NEXT, UPLOAD, SEARCH, REMOVE)
STYLES = ('photo', 'illustration')
FILLS_PER_DAY = 3
SEARCHES_PER_DAY = 10
SEARCHES_PER_MINUTE = 5
PER_DECK = 12
# A slide's candidates kept on offer: a search's four, and the pictures it wore before.
CANDIDATES_KEPT = 8
# What a slide takes to hold a picture beside its words, tried in this order.
PHOTO_LAYOUTS = ('image_split', 'image_full')
# Slides a picture is never added to by Add to all slides: dividers and the closing slide.
WORDS_ONLY = ('section', 'closing')
UPLOAD_TYPES = ('image/jpeg', 'image/png')
# What one fill's search, pick and downloads may take, and its naming before them.
FILL_SECONDS = 90
NAMING_SECONDS = 20


# --- What a deck has -------------------------------------------------------------------------

def _on():
    from operations.integrations import editor_config
    config = editor_config()
    return config['deck_editor'] and config['photos_task']


def per_deck(account):
    """Pictures one deck may hold: twelve, or fewer if the plan allows fewer."""
    from apps.core.policy import plan_limits
    return max(0, min(PER_DECK, int(plan_limits(account).get('max_deck_images', 0) or 0)))


def _photos(data):
    return (data.get('_render') or {}).setdefault('photos', {})


def pinned(data):
    """{section id: asset id} of the slides that wear a picture now."""
    photos = (data.get('_render') or {}).get('photos') or {}
    ids = {section['id'] for section in data['content']['sections']}
    return {sid: photo['asset_id'] for sid, photo in photos.items() if sid in ids and photo.get('asset_id')}


def _day_start(now):
    from .tasks import _day_start as start
    return start(now)


def used_today(account, action):
    """This account's picture tasks of `action` today, Tashkent's day, those that failed aside."""
    return (EditorTask.objects.filter(account=account, kind=PHOTOS, action=action, created_at__gte=_day_start(timezone.now()))
            .exclude(status='failed').count())


def style_of(data):
    style = (data.get('_render') or {}).get('photo_style') or data.get('options', {}).get('photo_style')
    return style if style in STYLES else 'photo'


def state(account, data):
    """What the Pictures sheet says before a tap: whether it is on, and what is left of today's and the deck's."""
    from operations.integrations import pixabay_config
    on = bool(_on())
    return {'on': on, 'stock': on and pixabay_config()['ready'], 'per_deck': per_deck(account), 'pinned': len(pinned(data)),
            'fills_left': max(0, FILLS_PER_DAY - used_today(account, FILL)),
            'searches_left': max(0, SEARCHES_PER_DAY - used_today(account, SEARCH)), 'style': style_of(data)}


def _fill_targets(data):
    """The slides Add to all slides would give a picture, in deck order: none yet, and not a divider or the end."""
    have = pinned(data)
    sections = data['content']['sections']
    return [section['id'] for index, section in enumerate(sections)
            if section['id'] not in have and (index == 0 or section.get('layout') not in WORDS_ONLY)]


# --- Asking ----------------------------------------------------------------------------------

def _draft(account, draft_id):
    draft = GenerationDraft.objects.filter(account=account, pk=draft_id, expires_at__gt=timezone.now()).first()
    if draft is None:
        raise DomainError('not_found', 404)
    require(account, EXPORT)
    return draft


def _held(account, draft):
    """A generation waiting on the draft, or a send of it under way: what it reads must not move under it."""
    from apps.core.allowance import IN_FLIGHT
    from apps.core.models import Job
    return draft_jobs(account, draft.pk, ('queued',)) or Job.objects.filter(
        account=account, feature_id=EXPORT, status__in=IN_FLIGHT, parameters__generation_draft_id=str(draft.pk)).exists()


def waiting(draft_id):
    """Whether a picture task of this draft is queued or running: until it lands, nothing else may move the draft's pictures or be sent from it."""
    return EditorTask.objects.filter(draft_id=draft_id, kind=PHOTOS, status__in=('queued', 'running')).exists()


def _limit(kind, limit):
    return DomainError('photos_limit', 429, {'limit_kind': kind, 'limit': limit})


def request(account, draft_id, body):
    """A picture action asked for: (the task doing it, None), or (None, the draft as it now stands) for `remove`."""
    from operations.integrations import pixabay_config
    from .layouts import clean_query
    from .render_export import _editable
    if not _on():
        raise DomainError('feature_unavailable', 409)
    action, version, sid = body.get('action'), body.get('version'), body.get('section_id')
    if action not in ACTIONS or type(version) is not int:
        raise DomainError('invalid_parameters')
    draft = _draft(account, draft_id)
    if version != draft.version:
        raise DomainError('version_conflict', 409)
    if _held(account, draft):
        raise DomainError('generation_running', 409)
    data = unpack(draft.encrypted_data)
    _editable(draft, data)
    sections = {section['id']: section for section in data['content']['sections']}
    if action != FILL and (not isinstance(sid, str) or sid not in sections):
        raise DomainError('invalid_parameters')
    style = body.get('style', style_of(data))
    if style not in STYLES:
        raise DomainError('invalid_parameters')
    if action == REMOVE:
        if waiting(draft.pk):
            raise DomainError('lane_busy', 429, retryable=True)
        return None, remove(account, draft, sid)
    have = pinned(data)
    cap = per_deck(account)
    payload = {'action': action, 'version': version, 'section_id': sid if action != FILL else None, 'style': style}
    photo = _photos(data).get(sid) or {}
    if action in (FILL, SEARCH) and not pixabay_config()['ready']:
        raise DomainError('photos_unavailable', 409)
    if action in (NEXT, UPLOAD) and sid not in have and len(have) >= cap:
        raise _limit('deck', cap)
    if action == FILL:
        if len(have) >= cap:
            raise _limit('deck', cap)
        if not _fill_targets(data):
            raise DomainError('deck_pictures_complete', 409)
    elif action == SEARCH:
        query = clean_query(body.get('query'))
        if not query:
            raise DomainError('invalid_parameters')
        from apps.core.views import account_limit
        try:
            account_limit(account, 'deck_photo_searches', SEARCHES_PER_MINUTE)
        except DomainError as exc:
            if exc.code == 'rate_limited':
                raise _limit('search_minute', SEARCHES_PER_MINUTE) from None
            raise
        payload['query'] = query
    elif action == NEXT:
        asset_id = body.get('asset_id')
        candidates = photo.get('candidates') or []
        if asset_id is not None and (not isinstance(asset_id, str) or not any(c.get('asset_id') == asset_id for c in candidates)):
            raise DomainError('invalid_parameters')
        if not candidates:
            raise DomainError('invalid_parameters')
        chosen = next(c for c in candidates if c.get('asset_id') == asset_id) if asset_id else candidates[0]
        # Only a picture stored whole needs nothing from Pixabay: its kill switch stops the rest.
        if not chosen.get('full') and not pixabay_config()['ready']:
            raise DomainError('photos_unavailable', 409)
        payload['asset_id'] = asset_id
    elif action == UPLOAD:
        from .photos import IMAGE_BYTES
        asset_id = body.get('asset_id')
        try:
            asset_id = str(uuid.UUID(asset_id)) if isinstance(asset_id, str) else None
        except ValueError:
            asset_id = None
        asset = FileAsset.objects.filter(account=account, pk=asset_id, state='ready', expires_at__gt=timezone.now()).first() if asset_id else None
        if asset is None:
            raise DomainError('not_found', 404)
        if asset.mime_type not in UPLOAD_TYPES or asset.size_bytes > IMAGE_BYTES:
            raise DomainError('invalid_image')
        payload['asset_id'] = str(asset.pk)

    def check():
        """Under the account's lock, so two taps at once cannot both take the last one."""
        if waiting(draft.pk):
            raise DomainError('lane_busy', 429, retryable=True)
        if action == FILL and used_today(account, FILL) >= FILLS_PER_DAY:
            raise _limit('fill', FILLS_PER_DAY)
        if action == SEARCH and used_today(account, SEARCH) >= SEARCHES_PER_DAY:
            raise _limit('search', SEARCHES_PER_DAY)

    from . import tasks
    return tasks.enqueue(account, PHOTOS, payload, draft=draft, action=action, check=check), None


def task_state(account, draft_id, task_id):
    """How a picture task stands, as the web follows it: its status, and its result or refusal."""
    row = EditorTask.objects.filter(account=account, draft_id=draft_id, kind=PHOTOS, pk=task_id).first()
    if row is None:
        raise DomainError('not_found', 404)
    result = unpack(row.encrypted_result) if row.status == 'done' and row.encrypted_result else None
    return {'task_id': str(row.pk), 'status': row.status, 'action': row.action, 'result': result,
            'error': row.error if row.status == 'failed' else None}


# --- Writing ---------------------------------------------------------------------------------

def _write(account, draft_id, change, *, row=None, version=None, cap=None):
    """`change(data, draft)` made to the draft as it is now, under its lock, as a new version of it.

    A task writes only while it still holds its lease (`row`: one the sweep gave
    up on may not land after it), only on the `version` it was asked on (a save
    from another tab, a removal or another design since would be undone by it),
    and never under a send or a generation of the draft, which reads the version
    it was quoted on. `cap`: pictures of slides no longer in the deck go first
    once there are more than that, so a slide put back by Undo never takes a deck past it.
    """
    from .render_export import _editable
    with transaction.atomic():
        draft = GenerationDraft.objects.select_for_update().filter(account=account, pk=draft_id, expires_at__gt=timezone.now()).first()
        if draft is None:
            raise DomainError('not_found', 404)
        if row is not None and not EditorTask.objects.select_for_update().filter(pk=row.pk, status='running', attempts=row.attempts).exists():
            raise DomainError('editor_task_failed')
        if version is not None and draft.version != version:
            raise DomainError('version_conflict', 409)
        if _held(account, draft):
            raise DomainError('generation_running', 409)
        data = unpack(draft.encrypted_data)
        _editable(draft, data)
        change(data, draft)
        if cap is not None:
            _trim(data, cap)
        draft.encrypted_data = pack(data)
        draft.version += 1
        draft.save(update_fields=['encrypted_data', 'version'])
    return draft


def _trim(data, cap):
    """At most `cap` pictures pinned, counting slides deleted since (Undo can put them back): theirs go first."""
    photos = _photos(data)
    here = {section['id'] for section in data['content']['sections']}
    gone = [sid for sid, photo in photos.items() if photo.get('asset_id') and sid not in here]
    while gone and sum(1 for photo in photos.values() if photo.get('asset_id')) > cap:
        photos.pop(gone.pop(0))


def _kept_candidates(candidates):
    """At most CANDIDATES_KEPT, the newest last, and each picture once."""
    seen, kept = set(), []
    for candidate in reversed(candidates):
        mark = candidate.get('asset_id') or f"{candidate.get('provider', 'pixabay')}:{candidate.get('id')}"
        if mark in seen:
            continue
        seen.add(mark)
        kept.append(candidate)
    return list(reversed(kept))[-CANDIDATES_KEPT:]


def _worn(photo):
    """The picture a slide wears, as a candidate it can have back: stored whole, so taking it again needs no network."""
    asset = FileAsset.objects.filter(pk=photo['asset_id']).first() if photo.get('asset_id') else None
    if asset is None:
        return None
    facts = asset.metadata or {}
    return {'asset_id': str(asset.pk), 'url': '', 'id': facts.get('id', 0), 'page_url': facts.get('page_url', ''),
            'provider': facts.get('provider', 'pixabay'), 'full': True}


def _same(a, b):
    """Whether two candidates are one picture: one stored file, or one Pixabay hit."""
    if a.get('asset_id') and a.get('asset_id') == b.get('asset_id'):
        return True
    return a.get('provider', 'pixabay') == 'pixabay' == b.get('provider', 'pixabay') and bool(a.get('id')) and a.get('id') == b.get('id')


def _wear(data, sid, asset_id, layout=None, candidates=None, query=None, taken=None):
    """Slide `sid` wears picture `asset_id`; the one it wore before goes last among its candidates.

    `taken`: the candidate it came from, which is then no longer on offer.
    """
    photos = _photos(data)
    photo = photos.get(sid) or {}
    offered = list((photo.get('candidates') or []) if candidates is None else candidates)
    if taken is not None:
        offered = [candidate for candidate in offered if not _same(candidate, taken)]
    before = _worn(photo)
    if before is not None and before['asset_id'] != asset_id:
        offered.append(before)
    offered = [candidate for candidate in offered if candidate.get('asset_id') != asset_id]
    photos[sid] = {'asset_id': asset_id, 'candidates': _kept_candidates(offered)}
    for section in data['content']['sections']:
        if section['id'] == sid:
            if layout:
                section['layout'] = layout
            if query and not section.get('image_query'):
                section['image_query'] = query


def remove(account, draft, sid):
    """The slide's picture taken off: kept first among its candidates, so Undo or Another picture brings it back at once."""
    def change(data, _):
        photos = _photos(data)
        photo = photos.get(sid) or {}
        worn = _worn(photo)
        if worn is None:
            raise DomainError('invalid_parameters')
        # The worn one leads, so Another picture puts it back first.
        rest = [c for c in photo.get('candidates') or [] if c.get('asset_id') != worn['asset_id']]
        photos[sid] = {'asset_id': None, 'candidates': [worn, *rest][:CANDIDATES_KEPT]}
    return _write(account, draft.pk, change)


# --- Room on the slide -----------------------------------------------------------------------

def _room(data, wanted):
    """{section id: layout} for the slides of `wanted` that can wear a picture with all their words showing.

    The layout is None for one that keeps its own (a photo layout, or the
    cover). Measured as a send is, with pictures on every slide that has or
    would have one; a slide that holds nowhere is left out.
    """
    from .branding import drawn_style
    from .slide_fit import measure_deck
    from .slide_layouts import PHOTO_ZONES
    from .slides import prepare_slides
    content, locale = data['content'], data['output_locale']
    have = set(pinned(data)) | set(wanted)
    prepared, _ = prepare_slides(content, locale, have)
    drawn = {section.get('id'): kind for kind, _, section in prepared}
    # The cover is a cover whatever its layout says (layouts.resolve); a photo layout tries the other one after its own.
    tries = {sid: [None] if drawn.get(sid) == 'cover'
             else [None] + [layout for layout in PHOTO_LAYOUTS if layout != drawn.get(sid)] if drawn.get(sid) in PHOTO_ZONES
             else list(PHOTO_LAYOUTS) for sid in wanted}
    found, left = {}, list(wanted)
    for attempt in range(3):
        trying = {sid: tries[sid][attempt] for sid in left if attempt < len(tries[sid])}
        if not trying:
            break
        trial = {**content, 'sections': [{**section, 'layout': trying[section['id']]} if trying.get(section['id']) else section
                                         for section in content['sections']]}
        measured = {slide['id']: slide['fits'] for slide in measure_deck(trial, locale, drawn_style(data), data['_render'], have)}
        # A layout that cannot take this slide falls back to one without a picture (layouts.resolve): fitting there shows none.
        shown = {section.get('id'): kind for kind, _, section in prepare_slides(trial, locale, have)[0]}
        for sid, layout in trying.items():
            if measured.get(sid) and shown.get(sid) in PHOTO_ZONES:
                found[sid] = layout
        left = [sid for sid in left if sid not in found]
    return found


# --- The tasks -------------------------------------------------------------------------------

def _usage(row, outcome):
    ProviderUsage.objects.create(task=row, provider='pixabay', outcome=outcome)


def _keep(account, draft, sid, source, jpeg, **facts):
    from .execution import keep_picture
    return keep_picture(account, draft.pk, sid, source, jpeg, expires_at=draft.expires_at, **facts)


def _slide_text(section):
    from .photos import _slide_text as text
    return text(section)


def _fill(row, draft, data, payload):
    """Pictures for the slides that have none, as many as the deck has room for, and the model's pick of each."""
    from operations.integrations import ai_config
    from . import photo_choice, photos as stock
    from .layouts import clean_query
    account = row.account
    cap = per_deck(account)
    room = cap - len(pinned(data))
    targets = _fill_targets(data)
    asked = len(targets)
    sections = {section['id']: section for section in data['content']['sections']}
    queries = {sid: clean_query(sections[sid].get('image_query')) for sid in targets}
    unnamed = [sid for sid in targets if not queries[sid]]
    ai = ai_config()
    if unnamed and ai.get('mode') == 'openai' and ai.get('api_key') and ai.get('model'):
        try:
            named = photo_choice.name_queries(ai, data['content'].get('title', ''), [{'id': sid, 'text': _slide_text(sections[sid])} for sid in unnamed],
                                              timeout=NAMING_SECONDS, account=account)
        except Exception:
            named = {}
        queries.update(named)
    targets = [sid for sid in targets if queries.get(sid)]
    fitting = _room(data, targets) if targets and room > 0 else {}
    # The first slides with room, as many as the deck takes: a slide with none never holds up the ones after it.
    room_for = {sid: fitting[sid] for sid in [sid for sid in targets if sid in fitting][:max(0, room)]}
    # The slides as the search sees them: the ones to fill, each in the layout it would wear, and no other asking.
    # The cover asks as a cover (photos.wanted), whatever its own layout says.
    asking = [{**section, 'layout': room_for[section['id']] or ('cover' if index == 0 else section.get('layout')), 'image_query': queries[section['id']]}
              if section['id'] in room_for else {**section, 'image_query': ''} for index, section in enumerate(data['content']['sections'])]
    result = stock.fetch_for_deck(asking, cap=len(room_for), budget=FILL_SECONDS, style=payload['style'], account=account, task=True) if room_for else stock.PhotoResult()
    if result.wanted or result.failed:
        _usage(row, 'succeeded' if not result.failed else 'partial' if result.photos else 'failed')
    kept = {}
    for sid, photo in result.photos.items():
        offered = [{'asset_id': _keep(account, draft, sid, hit, hit['jpeg'], candidate=True) if hit.get('jpeg') else None,
                    'url': hit['url'], 'id': hit['id'], 'page_url': hit['page_url'], 'provider': 'pixabay'}
                   for hit in result.candidates.get(sid) or [] if hit['id'] != photo['id']]
        kept[sid] = (_keep(account, draft, sid, photo, photo['jpeg'], candidate=False, width=photo['width'], height=photo['height']), offered)

    def change(current, _):
        sections_now = {section['id'] for section in current['content']['sections']}
        for sid, (asset_id, offered) in kept.items():
            if sid in sections_now and sid not in pinned(current):
                _wear(current, sid, asset_id, room_for.get(sid), offered, queries.get(sid))
        current['_render']['photo_style'] = payload['style']
    written = _write(account, draft.pk, change, row=row, version=payload['version'], cap=cap) if kept else None
    return {'version': written.version if written else draft.version, 'added': len(kept), 'asked': asked,
            'no_room': len(targets) - len(fitting), 'unnamed': len([sid for sid in unnamed if not queries.get(sid)]),
            'unmatched': result.unmatched, 'failed': max(0, result.failed - result.unmatched)}


def _download(row, url):
    from . import photos as stock
    try:
        prepared = stock.download(url)
    except Exception:
        _usage(row, 'failed')
        raise DomainError('picture_unavailable', 409) from None
    _usage(row, 'succeeded')
    return prepared


def _stored(asset_id):
    """A stored picture's bytes, still what they were kept as; None when gone."""
    asset = FileAsset.objects.filter(pk=asset_id, state='ready', expires_at__gt=timezone.now()).first() if asset_id else None
    if asset is None:
        return None
    try:
        data = storage.read_bytes(asset.object_key)
    except OSError:
        return None
    return asset if hashlib.sha256(data).hexdigest() == asset.sha256 else None


def _layout_or_refuse(data, sid):
    room = _room(data, [sid])
    if sid not in room:
        raise DomainError('picture_no_room', 409)
    return room[sid]


def _next(row, draft, data, payload):
    """The slide's chosen candidate, or the first on offer, put on it: taken whole when stored so, else downloaded large."""
    from operations.integrations import pixabay_config
    account, sid = row.account, payload['section_id']
    photo = _photos(data).get(sid) or {}
    candidates = photo.get('candidates') or []
    chosen = next((c for c in candidates if c.get('asset_id') == payload.get('asset_id')), None) if payload.get('asset_id') else (candidates[0] if candidates else None)
    if chosen is None:
        raise DomainError('picture_unavailable', 409)
    layout = _layout_or_refuse(data, sid)
    if chosen.get('full'):
        asset = _stored(chosen.get('asset_id'))
        if asset is None:
            raise DomainError('picture_unavailable', 409)
        asset_id = str(asset.pk)
    else:
        if not pixabay_config()['ready']:
            raise DomainError('photos_unavailable', 409)
        prepared = _download(row, chosen.get('url'))
        asset_id = _keep(account, draft, sid, {'provider': chosen.get('provider', 'pixabay'), 'id': chosen.get('id'), 'page_url': chosen.get('page_url', '')},
                         prepared['jpeg'], candidate=False, width=prepared['width'], height=prepared['height'])
    written = _write(account, draft.pk, lambda current, _: _wear(current, sid, asset_id, layout, taken=chosen),
                     row=row, version=payload['version'], cap=per_deck(account))
    return {'version': written.version, 'asset_id': asset_id}


def _upload(row, draft, data, payload):
    """The customer's own photo, made a plain JPEG with no EXIF (photos.prepare), on the slide."""
    from . import photos as stock
    account, sid = row.account, payload['section_id']
    asset = _stored(payload['asset_id'])
    if asset is None or asset.account_id != account.pk:
        raise DomainError('picture_unavailable', 409)
    try:
        prepared = stock.prepare(storage.read_bytes(asset.object_key))
    except Exception:
        raise DomainError('invalid_image') from None
    layout = _layout_or_refuse(data, sid)
    asset_id = _keep(account, draft, sid, {'provider': 'upload', 'id': 0, 'page_url': ''}, prepared['jpeg'],
                     candidate=False, width=prepared['width'], height=prepared['height'])
    written = _write(account, draft.pk, lambda current, _: _wear(current, sid, asset_id, layout),
                     row=row, version=payload['version'], cap=per_deck(account))
    return {'version': written.version, 'asset_id': asset_id}


def _search(row, draft, data, payload):
    """Four candidates for one slide from English words, offered first; the picture it wears stays on it."""
    from operations.integrations import pixabay_config
    from . import photos as stock
    account, sid, style = row.account, payload['section_id'], payload['style']
    config = pixabay_config()
    if not config['ready']:
        raise DomainError('photos_unavailable', 409)
    try:
        hits = stock.find(payload['query'], config['api_key'], style, task=True)
    except Exception:
        _usage(row, 'failed')
        raise DomainError('picture_unavailable', 409) from None
    # Words a customer typed may share none with Pixabay's tags and still be what they want: its own order then.
    ranked = stock.rank(hits, payload['query']) or hits
    shortlist = stock._shortlist(ranked)
    found = []
    for hit in shortlist:
        try:
            jpeg = stock.preview(hit['preview'])
        except Exception:
            continue
        found.append({'asset_id': _keep(account, draft, sid, {'provider': 'pixabay', 'id': hit['id'], 'page_url': hit['page_url']}, jpeg, candidate=True),
                      'url': hit['url'], 'id': hit['id'], 'page_url': hit['page_url'], 'provider': 'pixabay'})
    _usage(row, 'succeeded' if found else 'failed')

    def change(current, _):
        photos = _photos(current)
        photo = photos.get(sid) or {'asset_id': None, 'candidates': []}
        older = [c for c in photo.get('candidates') or [] if c.get('full')]
        photo['candidates'] = (found + older)[:CANDIDATES_KEPT]
        photos[sid] = photo
        current['_render']['photo_style'] = style
    written = _write(account, draft.pk, change, row=row, version=payload['version']) if found else None
    return {'version': written.version if written else draft.version, 'found': len(found)}


HANDLERS = {FILL: _fill, NEXT: _next, UPLOAD: _upload, SEARCH: _search}


def run(row):
    """The picture task taken as `row`, done: what it changed, said in counts and ids, never words."""
    from .render_export import _editable
    payload = unpack(row.encrypted_payload)
    draft = GenerationDraft.objects.filter(pk=row.draft_id, account=row.account, expires_at__gt=timezone.now()).first()
    if draft is None:
        raise DomainError('not_found', 404)
    data = unpack(draft.encrypted_data)
    _editable(draft, data)
    return HANDLERS[payload['action']](row, draft, data, payload)


# --- Design ----------------------------------------------------------------------------------

def set_design(account, draft_id, body):
    """Another design for a drawn deck: its pins' design, which beats the options' (slides.deck_look). Nothing else moves."""
    from .deck_designs import DESIGNS
    from .render_export import _editable
    version, design = body.get('version'), body.get('design')
    if type(version) is not int or not isinstance(design, str) or design not in DESIGNS:
        raise DomainError('invalid_parameters')
    draft = _draft(account, draft_id)
    if version != draft.version:
        raise DomainError('version_conflict', 409)
    if _held(account, draft):
        raise DomainError('generation_running', 409)
    if waiting(draft.pk):
        raise DomainError('lane_busy', 429, retryable=True)
    _editable(draft, unpack(draft.encrypted_data))

    def change(data, _):
        data['_render']['design'] = design
    return _write(account, draft.pk, change)
