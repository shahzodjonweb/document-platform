"""Stock photos for slide decks, from Pixabay.

This is the one place the server fetches a URL it did not write itself: the
search API returns image URLs, and those are downloaded. So every rule here is
about keeping that narrow.

* The API origin is a constant, `safesearch=true` is always sent (Pixabay
  defaults it to false), and a redirect from the API is refused outright — the
  key travels in its query string.
* An image URL is fetched only if it is https, on exactly `pixabay.com` or
  `cdn.pixabay.com`, with no userinfo and no port; every redirect hop is checked
  against the same rule.
* Bytes are capped, decoded only as JPEG or PNG after a pixel check, and
  re-encoded as a plain JPEG with no EXIF before they go anywhere near a deck.
* Nothing here is ever allowed to fail a job. A photo that cannot be had is a
  slide drawn as text, and the customer is told.

Relevance is checked twice. Search results are ranked by how many words of the
slide's photo subject their Pixabay tags share, and the ones sharing none are
dropped. Then the model looks at the best few for each slide beside that slide's
text and picks one, or none — a loosely related photo is worse than no photo.
When the model cannot be asked, the best tag match is used on its own.

Pixabay's terms shape the rest: search responses are cached for 24 hours,
images are downloaded rather than hotlinked, and requests happen only inside a
confirmed job — never while a draft is being written or priced.
"""
import hashlib
import io
import json
import re
import time
import urllib.request
import warnings
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import timedelta
from urllib.parse import urlencode, urlsplit

API = 'https://pixabay.com/api/'
IMAGE_HOSTS = frozenset({'pixabay.com', 'cdn.pixabay.com'})
USER_AGENT = 'PDFMaster/1.0'
SEARCH_TIMEOUT = 6
DOWNLOAD_TIMEOUT = 10
BUDGET_SECONDS = 90
SEARCH_HITS = 20
# Candidates per slide shown to the model, as small previews.
CANDIDATES = 4
PREVIEW_EDGE = 512
PREVIEW_BYTES = 120_000
# The model's look at the candidates may take this long, and is skipped when
# less time than that is left.
PICK_SECONDS = 40
PICK_MIN_SECONDS = 12
SEARCH_BYTES = 256_000
IMAGE_BYTES = 5 * 1024 * 1024
SOURCE_PIXELS = 6_000_000
MAX_REDIRECTS = 2
LONG_EDGE = 1600
MAX_JPEG = 450_000
CACHE_HOURS = 24
# Pixabay allows 100 requests a minute per key; stay under it across every
# worker, because the limit is on the key, not on the process.
RATE = (90, 60)


class PhotoResult:
    __slots__ = ('photos', 'wanted', 'limited', 'failed', 'unmatched')

    def __init__(self, photos=None, wanted=0, limited=0, failed=0, unmatched=0):
        self.photos, self.wanted, self.limited, self.failed = photos or {}, wanted, limited, failed
        # Of the failed: slides where no candidate fitted, as opposed to a fault.
        self.unmatched = unmatched

    @property
    def warnings(self):
        return (['images_skipped'] if self.failed else []) + (['images_limited'] if self.limited else [])


# ---------------------------------------------------------------- network


def _open(request, timeout, handler):
    """Every byte this module fetches comes through here, so tests can stop it."""
    return urllib.request.build_opener(handler).open(request, timeout=timeout)


def _read(response, limit):
    raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('too_large')
    return raw


def _image_url_ok(url):
    """Only an https URL on exactly one of Pixabay's own hosts."""
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) <= 32 or ord(c) == 127 for c in url):
        return False
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    hostname = (parts.hostname or '').lower()
    return (parts.scheme == 'https' and parts.username is None and parts.password is None
            and port is None and hostname in IMAGE_HOSTS and parts.netloc.lower() == hostname)


class _PinnedRedirect(urllib.request.HTTPRedirectHandler):
    """Follow a download's redirect only to another Pixabay host, and not far."""

    def __init__(self):
        super().__init__()
        self.hops = 0

    def redirect_request(self, request, fp, code, message, headers, newurl):
        self.hops += 1
        if self.hops > MAX_REDIRECTS or not _image_url_ok(newurl):
            raise ValueError('redirect_refused')
        return super().redirect_request(request, fp, code, message, headers, newurl)


def _hit(value):
    """The few fields of a search hit worth keeping, or None if it is malformed."""
    if not isinstance(value, dict) or value.get('type') != 'photo':
        return None
    identifier, width, height = value.get('id'), value.get('imageWidth'), value.get('imageHeight')
    url = value.get('largeImageURL')
    if not (type(identifier) is int and identifier > 0 and type(width) is int and width > 0
            and type(height) is int and height > 0 and _image_url_ok(url)):
        return None
    page = value.get('pageURL')
    page = page if isinstance(page, str) and page.startswith('https://pixabay.com/') and len(page) <= 512 else ''
    # Tags are kept only as hashed words: enough to rank by, while the cache
    # still holds nothing that reads as what the deck was about.
    tags = value.get('tags')
    tags = ' '.join(sorted({_word_hash(word) for word in _words(tags[:300])})) if isinstance(tags, str) else ''
    # The 640px rendition, which the model looks at when choosing. Pinned like
    # every other URL; a hit without one can still be chosen by its tags.
    preview = value.get('webformatURL')
    preview = preview if _image_url_ok(preview) else ''
    return {'id': identifier, 'page_url': page, 'url': url, 'width': width, 'height': height,
            'tags': tags, 'preview': preview}


def search(query, key, per_page=SEARCH_HITS):
    """Up to `per_page` validated photo hits for an already-cleaned query."""
    from .provider import _NoRedirect
    params = urlencode({'key': key, 'q': query, 'lang': 'en', 'image_type': 'photo',
                        'orientation': 'horizontal', 'safesearch': 'true', 'per_page': per_page,
                        'min_width': 1200, 'order': 'popular'})
    request = urllib.request.Request(API + '?' + params, headers={'User-Agent': USER_AGENT})
    with _open(request, SEARCH_TIMEOUT, _NoRedirect()) as response:
        data = json.loads(_read(response, SEARCH_BYTES))
    if not isinstance(data, dict) or type(data.get('totalHits')) is not int or not isinstance(data.get('hits'), list):
        raise ValueError('shape')
    return [hit for hit in (_hit(value) for value in data['hits'][:per_page]) if hit]


def prepare(raw, long_edge=LONG_EDGE, max_bytes=MAX_JPEG):
    """Untrusted image bytes as a plain JPEG a deck can hold, or ValueError."""
    from PIL import Image, ImageOps
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(raw), formats=['JPEG', 'PNG']) as picture:
            if picture.width * picture.height > SOURCE_PIXELS or getattr(picture, 'n_frames', 1) != 1:
                raise ValueError('image_shape')
            picture.load()
            clean = ImageOps.exif_transpose(picture).convert('RGB')
    clean.thumbnail((long_edge, long_edge))
    for quality in (82, 72):
        out = io.BytesIO()
        # No `exif=`: nothing from the source file survives into the deck.
        clean.save(out, 'JPEG', quality=quality, optimize=True)
        if out.tell() <= max_bytes:
            return {'jpeg': out.getvalue(), 'width': clean.width, 'height': clean.height}
    raise ValueError('image_too_large')


def download(url, long_edge=LONG_EDGE, max_bytes=MAX_JPEG):
    if not _image_url_ok(url):
        raise ValueError('host')
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with _open(request, DOWNLOAD_TIMEOUT, _PinnedRedirect()) as response:
        return prepare(_read(response, IMAGE_BYTES), long_edge, max_bytes)


def preview(url):
    """A small copy for the model to look at, re-encoded like any other photo."""
    return download(url, PREVIEW_EDGE, PREVIEW_BYTES)['jpeg']


# ---------------------------------------------------------------- relevance


def _words(text):
    """Plain lower-case words, a trailing plural `s` dropped, for matching tags."""
    words = []
    for word in re.findall(r'[a-z0-9]+', str(text or '').lower()):
        if len(word) > 3 and word.endswith('s') and not word.endswith('ss'):
            word = word[:-1]
        words.append(word)
    return words


def _word_hash(word):
    return hashlib.sha256(('tag|' + word).encode()).hexdigest()[:12]


def rank(hits, query):
    """Hits whose tags share a word with the query, best first.

    The subject is asked for main word first, so a match on the first word
    counts double; Pixabay's own order breaks ties. A hit sharing no word with
    the query is not a candidate at all — that is how a search for "warehouse
    forklift" came back with a sunset.
    """
    wanted = [_word_hash(word) for word in _words(query)]
    if not wanted:
        return []
    scored = []
    for position, hit in enumerate(hits):
        tags = set(str(hit.get('tags', '')).split())
        shared = sum(1 for word in set(wanted) if word in tags)
        if shared:
            scored.append((shared + (wanted[0] in tags), position, hit))
    scored.sort(key=lambda entry: (-entry[0], entry[1]))
    return [hit for _, _, hit in scored]


def _broader(query):
    """The main subject alone: the first two words of a longer query."""
    words = query.split()
    return ' '.join(words[:2]) if len(words) > 2 else ''


# ---------------------------------------------------------------- deck


def wanted(sections):
    """The slides that asked for a photo, in deck order."""
    from .layouts import PHOTO_LAYOUTS
    chosen = []
    for index, section in enumerate(sections):
        if not section.get('image_query'):
            continue
        layout = section.get('layout')
        # `image` is a document section's photo layout; the rest are a deck's.
        if layout in PHOTO_LAYOUTS or layout == 'image' or (layout == 'cover' and index == 0 and len(sections) >= 2):
            chosen.append(section)
    return chosen


def _cache_key(query):
    # v2: hits carry tags and a preview, which v1 answers did not keep.
    return hashlib.sha256(('v2|' + query).encode()).hexdigest()


def _slide_text(section):
    """What the model reads about a slide when choosing its photo."""
    parts = [section.get('heading', ''), section.get('body', '')]
    parts += [item.get('label', '') for item in section.get('items') or [] if isinstance(item, dict)]
    return ' '.join(' '.join(str(part or '') for part in parts).split())[:400]


def fetch_for_deck(sections, *, cap, budget, job=None):
    """Photos for as many of the slides that want one as the plan allows.

    Database work — the cache, the shared rate limit and the record of the
    model's choice — stays on this thread; the pool only does network and
    decoding. Everything shares one deadline, and anything unfinished when it
    passes is a slide drawn as text.
    """
    from django.utils import timezone
    from apps.core.customer_auth import auth_limit
    from operations.integrations import ai_config, pixabay_config
    from .models import PhotoSearch

    asking = wanted(sections)
    config = pixabay_config()
    # Photos are not a feature right now: nothing is fetched, and nothing is a
    # failure the customer needs telling about.
    if not asking or not config['ready']:
        return PhotoResult()
    chosen, limited = asking[:max(0, cap)], len(asking) - min(len(asking), max(0, cap))
    result = PhotoResult(wanted=len(asking), limited=limited)
    if not chosen or budget < 5:
        result.failed = len(chosen)
        return result
    deadline = time.monotonic() + budget
    now = timezone.now()
    queries = {section['id']: section['image_query'] for section in chosen}
    hits = {}
    pool = ThreadPoolExecutor(max_workers=4)

    def searched(wanted_queries):
        """Answers for these queries, from the cache or Pixabay, into `hits`."""
        searching = {}
        for query in sorted(wanted_queries):
            row = PhotoSearch.objects.filter(key=_cache_key(query), expires_at__gt=now).first()
            if row is not None:
                hits[query] = row.hits
                continue
            try:
                auth_limit('pixabay-api', 'global', *RATE)
            except Exception:
                continue
            searching[pool.submit(search, query, config['api_key'])] = query
        done, _ = wait(searching, timeout=max(0, deadline - time.monotonic()))
        for future in done:
            try:
                found = future.result()
            except Exception:
                continue
            hits[searching[future]] = found
            PhotoSearch.objects.update_or_create(
                key=_cache_key(searching[future]),
                defaults={'hits': found, 'expires_at': now + timedelta(hours=CACHE_HOURS)})

    try:
        searched(set(queries.values()))
        # A subject too specific to find much is searched again as its main
        # subject alone, and ranked against the whole of it.
        thin = {query: _broader(query) for query in set(queries.values())
                if query in hits and len(rank(hits[query], query)) < 2 and _broader(query)}
        if thin:
            searched(set(thin.values()) - set(hits))
            for query, broader in thin.items():
                seen = {hit['id'] for hit in hits[query]}
                hits[query] = hits[query] + [hit for hit in hits.get(broader, []) if hit['id'] not in seen]
        ranked = {sid: rank(hits.get(query, []), query) for sid, query in queries.items()}

        title = sections[0].get('heading', '') if sections else ''
        picked = _ask_the_model(chosen, ranked, pool, deadline, ai_config(), job, title)
        # The model's choice is the only option it leaves a slide; when it could
        # not be asked, the tag ranking stands on its own, best first.
        options = ranked if picked is None else {sid: [hit] for sid, hit in picked.items()}

        # One photo per slide, and never the same photo twice in a deck.
        used, final = set(), {}
        for section in chosen:
            pick = next((hit for hit in options.get(section['id'], []) if hit['id'] not in used), None)
            if pick is not None:
                used.add(pick['id'])
                final[section['id']] = pick
        result.unmatched = sum(1 for section in chosen
                               if section['id'] not in final and ranked.get(section['id']))
        downloading = {pool.submit(download, pick['url']): (sid, pick) for sid, pick in final.items()}
        done, _ = wait(downloading, timeout=max(0, deadline - time.monotonic()))
        fetched = {}
        for future in done:
            try:
                prepared = future.result()
            except Exception:
                continue
            sid, pick = downloading[future]
            fetched[sid] = {**prepared, 'provider': 'pixabay', 'id': pick['id'], 'page_url': pick['page_url']}
        # Downloads finish in whatever order the network allows; the result is
        # given in deck order, so the same deck always comes back the same way.
        result.photos = {section['id']: fetched[section['id']] for section in chosen if section['id'] in fetched}
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    result.failed = len(chosen) - len(result.photos)
    return result


def _ask_the_model(chosen, ranked, pool, deadline, ai, job, title):
    """The model's pick for each slide — a hit, or absent for "none fits".

    None when the model could not be asked at all: no provider, too little
    time, no preview to show it, or any failure of the call itself.
    """
    from . import photo_choice
    if ai.get('mode') != 'openai' or not ai.get('api_key') or not ai.get('model'):
        return None
    if deadline - time.monotonic() < PICK_MIN_SECONDS + 10:
        return None
    shown = {sid: [hit for hit in options if hit.get('preview')][:CANDIDATES] for sid, options in ranked.items()}
    unique = {hit['id']: hit['preview'] for options in shown.values() for hit in options}
    if not unique:
        return None
    loading = {pool.submit(preview, url): identifier for identifier, url in unique.items()}
    # Leave the model its time, and the chosen photos theirs.
    done, _ = wait(loading, timeout=max(0, min(DOWNLOAD_TIMEOUT, deadline - time.monotonic() - PICK_MIN_SECONDS - 5)))
    previews = {}
    for future in done:
        try:
            previews[loading[future]] = future.result()
        except Exception:
            continue
    shown = {sid: [hit for hit in options if hit['id'] in previews] for sid, options in shown.items()}
    slides = [{'id': section['id'], 'text': _slide_text(section),
               'photos': [previews[hit['id']] for hit in shown[section['id']]]}
              for section in chosen if shown.get(section['id'])]
    if not slides:
        return None
    timeout = min(PICK_SECONDS, deadline - time.monotonic() - 5)
    if timeout < PICK_MIN_SECONDS:
        return None
    try:
        choice = photo_choice.choose(ai, title, slides, timeout=timeout, job=job)
    except Exception:
        return None
    return {sid: shown[sid][number - 1] for sid, number in choice.items() if number}
