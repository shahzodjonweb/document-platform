"""Where a CV's facts come from: one message, the customer's LinkedIn profile, or their old CV.

The customer chooses first (`options.cv_source`). 'text' is the one message a
CV has always been made from. 'linkedin' is their LinkedIn profile, which our
server cannot open: LinkedIn needs a sign-in and forbids reading its pages by
program, so it is the profile saved with LinkedIn's own "Save to PDF", or
screenshots of it. 'file' is an old CV: a PDF, a Word file, photos or a scan.
In those two the file holds the facts and what the customer writes is notes
on top of it: the job they want now, what to change, what to add. A photo
sent there is a page to read, never the portrait.

The files are read once, when the draft is made (extraction.read_cv), and
what they say is kept with the draft as its excerpts. Nothing reads them
again: an update that keeps them keeps what was read, one that adds a file
reads only that file, a CV made again from the same files soon after (its
name asked for, new notes) takes what this process read of them, and a
change to the CV is made from the excerpts it was made from, after the files
themselves are gone (they are kept 24 hours). What could not be read (pages
past the OCR share, a file that failed or had no time left) is kept with
the draft as `cv_unread` and said on its review, never left out unsaid.
"""
import re
import tempfile
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path

from apps.core.errors import DomainError

TEXT, LINKEDIN, FILE = 'text', 'linkedin', 'file'
MODES = (TEXT, LINKEDIN, FILE)
# What each mode takes. A LinkedIn profile is its own PDF or screenshots of it, never a Word file.
KINDS = {LINKEDIN: ('pdf', 'image'), FILE: ('pdf', 'docx', 'image')}
MIME = {'application/pdf': 'pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
        'image/jpeg': 'image', 'image/png': 'image'}
# Ten files: an album of screenshots is at most ten. Pages are all the files' together.
MAX_FILES = 10
MAX_PAGES = 30
# Pages read by OCR for one draft, and how long all its files may take to read:
# the request that makes the draft has to answer well inside the proxy's 120 s.
MAX_OCR_PAGES = 10
READ_SECONDS = 75
# Fewer words than this in all the files is a file with nothing to read in it.
MIN_WORDS = 8
# A LinkedIn profile's address: linkedin.com/in/…, an older /pub/ one, or a lnkd.in short link.
LINKEDIN_LINK = re.compile(r"(?:https?://)?(?:[\w\-]+\.)?(?:linkedin\.com/(?:in|pub|profile)/|lnkd\.in/)[^\s<>]*",
                           re.IGNORECASE)


def mode(options):
    """The way the CV is made, as `options` names it: 'text' when it names none."""
    source = (options or {}).get('cv_source', TEXT)
    if source not in MODES:
        raise DomainError('invalid_parameters')
    return source


def max_files(account):
    """How many files a CV may be made from: ten, or fewer when the plan's source files are fewer."""
    from apps.core.policy import plan_limits
    return min(MAX_FILES, int(plan_limits(account).get('max_ai_source_files', MAX_FILES) or MAX_FILES))


def max_pages(account):
    """How many pages all of a CV's files may have: thirty, or fewer when the plan's source pages are fewer."""
    from apps.core.policy import plan_limits
    return min(MAX_PAGES, int(plan_limits(account).get('max_ai_source_pages', MAX_PAGES) or MAX_PAGES))


# The words people ask with, greet with and point at their profile with, in
# English, Uzbek and Russian. None of them is a fact about the person. The web
# app stops a link-only description with the same set (document-web
# app/composables/useCvSources.ts ASKING) and never with a word more: a word
# only the web took for asking would stop a description this side makes a CV of.
ASKING = frozenset(' '.join((
    'hello hi here is my the a an at from for me it please make create professional good cv resume profile link page',
    'thank thanks you very much this',
    'assalomu alaykum salom mana mening shu shundan menga yaxshi rezyume profil profilim havola qilib bering iltimos',
    'tayyorlab rahmat',
    'здравствуйте привет вот ссылка на мой моя мне профиль в из него по моему сделайте сделать составьте пожалуйста',
    'резюме спасибо',
)).split())
LETTERS = re.compile(r"[^\W\d_]+")


def linkedin_link_only(text):
    """Whether a description is a LinkedIn profile's link and no fact about the person.

    A bare link, or one in a request ("Здравствуйте, вот ссылка на мой
    профиль, сделайте резюме: …", "Please make my CV from my profile at …").
    It cannot be opened, so the customer is told how to save the profile as a
    PDF instead (`cv_linkedin_link`). Any other word, an email, a phone number
    or a year is a fact, however short the description ("Ali Valiyev, SMM
    manager. linkedin.com/in/…"), and the CV is made from it. A name alone is
    no CV: it is taken out before the words are read, so a request that gives
    only the name and the link is still told how to save the profile.
    """
    text = str(text or '')
    if not LINKEDIN_LINK.search(text):
        return False
    from .content import EMAIL, PHONE, YEAR, name_in
    rest = LINKEDIN_LINK.sub(' ', text)
    name = name_in(rest)
    if name:
        rest = rest.replace(name, ' ', 1)
    if EMAIL.search(rest) or PHONE.search(rest) or YEAR.search(rest):
        return False
    words = [word.lower() for word in LETTERS.findall(rest)]
    return all(word == 'linkedin' or word in ASKING for word in words)


def checked(account, ids, source):
    """The files of a CV made from files, checked for its mode before any is read: (assets, kinds).

    Refused: `generation_limit` for more files or pages than one CV is made
    from, `cv_file_kind` for a file the mode does not read, `cv_file_unreadable`
    for a protected PDF.
    """
    if len(ids) > max_files(account):
        raise DomainError('generation_limit')
    from apps.core.services import owned_assets
    assets = owned_assets(account, ids)
    kinds = [MIME.get(asset.mime_type) if asset.metadata.get('kind') in ('pdf', 'docx', 'image') else None
             for asset in assets]
    if any(kind not in KINDS[source] for kind in kinds):
        raise DomainError('cv_file_kind')
    if any(asset.metadata.get('encrypted') for asset in assets):
        raise DomainError('cv_file_unreadable')
    if sum(asset.page_count for asset in assets) > max_pages(account):
        raise DomainError('generation_limit')
    return assets, kinds


def prepare(account, prompt, ids, options, previous=None):
    """The files of a new CV checked for its mode and read: (ids, excerpts, unread).

    'text' takes none. 'linkedin' and 'file' take one to ten of the kinds
    their mode reads (KINDS). `previous` is the draft being updated: its
    excerpts are kept when its files are, and a file it read whole is not
    read again beside a new one. `unread` says what could not be read (read).
    Refused: `cv_file_required` with no file, `cv_linkedin_link` when the
    description is only a LinkedIn link, the refusals of checked(), and
    `cv_file_unreadable` for files with no text in them.
    """
    source = mode(options)
    if not isinstance(ids, list):
        raise DomainError('invalid_parameters')
    if source == TEXT:
        if ids:
            raise DomainError('invalid_parameters')
        if linkedin_link_only(prompt):
            raise DomainError('cv_linkedin_link')
        return ids, [], []
    if not ids:
        raise DomainError('cv_linkedin_link' if linkedin_link_only(prompt) else 'cv_file_required')
    previous = previous or {}
    same = (previous.get('options') or {}).get('cv_source') == source and previous.get('excerpts')
    if same and previous.get('source_ids') == ids:
        return ids, previous['excerpts'], list(previous.get('cv_unread') or [])
    assets, kinds = checked(account, ids, source)
    known = results_of(previous['excerpts'], previous.get('cv_unread')) if same else {}
    excerpts, unread = read(assets, kinds, known, account=account)
    return [str(asset.id) for asset in assets], excerpts, unread


# --- Reading -------------------------------------------------------------------------------

# What a file's reading gave, kept a while in this process so that it is read
# once: a CV made again from it (its name asked for, new notes, a screenshot
# sent after it) takes what it gave instead of reading it again, and so does
# a draft whose files were read ahead (the bot reads them off its shared
# thread first: read_entries). Kept by the file's id and checksum, at most
# CACHE_SECONDS and CACHE_BYTES in all; the oldest goes first.
CACHE_SECONDS = 30 * 60
CACHE_BYTES = 8 * 1024 * 1024
_cache = OrderedDict()
_cache_lock = threading.Lock()
_cache_size = [0]


# One CV's files are read at a time on one machine: between the API's workers,
# which are two (a reading holds one for as long as it takes, a minute at
# most), and in the bot. Another waits SLOT_SECONDS for its turn and is then
# asked to try again shortly (`rate_limited`), so a worker is always free for
# everything else the API serves. Only reading takes the turn: what was read
# before is taken at once.
SLOT = Path(tempfile.gettempdir()) / 'pdfmaster-cv-reading.lock'
SLOT_SECONDS = 4


@contextmanager
def _turn():
    import fcntl
    with open(SLOT, 'a') as handle:
        deadline = time.monotonic() + SLOT_SECONDS
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise DomainError('rate_limited', 429, retryable=True) from None
                time.sleep(0.2)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _remember(key, value, size):
    with _cache_lock:
        if key in _cache:
            _cache_size[0] -= _cache.pop(key)[2]
        _cache[key] = (time.monotonic() + CACHE_SECONDS, value, size)
        _cache_size[0] += size
        while _cache and _cache_size[0] > CACHE_BYTES:
            _cache_size[0] -= _cache.popitem(last=False)[1][2]


def _recall(key):
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        if entry[0] < time.monotonic():
            _cache_size[0] -= _cache.pop(key)[2]
            return None
        _cache.move_to_end(key)
        return entry[1]


def forget():
    """Drop everything read and kept (tests)."""
    with _cache_lock:
        _cache.clear()
        _cache_size[0] = 0


def _size(result):
    return 256 + sum(len(page.get('text') or '') for page in (result or {}).get('pages') or [])


def entries(assets, kinds, account=None):
    """The files as the reader takes them: one {'asset_id', 'sha256', 'kind', 'pages', 'scan', 'path'} each.

    'scan' is whether it may need OCR: an image always, a PDF with a picture
    on a page. The path is on this machine (storage.local), fetched if need be.
    """
    from apps.core import storage
    owner = str(getattr(account, 'pk', '') or '')
    return [{'account': owner, 'asset_id': str(asset.id), 'sha256': asset.sha256, 'kind': kind,
             'pages': int(asset.page_count or 0),
             'scan': kind == 'image' or kind == 'pdf' and any(asset.metadata.get('image_counts') or []),
             'path': str(storage.local(asset.object_key))}
            for asset, kind in zip(assets, kinds)]


def results_of(excerpts, unread=None):
    """What a draft's excerpts say each of its files gave, for the files read whole: {asset_id: result}."""
    partly = {str(entry.get('asset_id')) for entry in unread or [] if isinstance(entry, dict)}
    results = {}
    for excerpt in excerpts or []:
        identifier = str(excerpt.get('asset_id'))
        if identifier in partly:
            continue
        result = results.setdefault(identifier, {'pages': [], 'names': [], 'ocr_pages': 0, 'ocr_skipped': 0})
        result['pages'].append({'page': excerpt['page'], 'text': excerpt['text'],
                                **({'ocr': True} if excerpt.get('ocr') else {})})
        if excerpt.get('names') and not result['names']:
            result['names'] = list(excerpt['names'])
        result['ocr_pages'] += bool(excerpt.get('ocr'))
    return results


def read_entries(files, known=None):
    """Each file's reading, in order: the reader's result, or None for a file it could not read or had no time for.

    Pages read by OCR are shared fairly: each file is allowed what is left of
    MAX_OCR_PAGES less a page for every file after it that may need OCR, so
    a long scan never leaves a screenshot after it unread; READ_SECONDS is the
    time for them all. A file read before is not read again (its result is
    kept: `known` from the draft, or this process's cache), and neither is the
    same set of files (what the bot read ahead). Reading waits its turn
    (_turn): `rate_limited` when another CV's files are read for longer.
    Touches no database: the bot runs it off its shared thread.
    """
    known = known or {}
    together = ('set', files[0]['account'] if files else '',
                tuple((entry['asset_id'], entry['sha256']) for entry in files))
    kept = _recall(together)
    if kept is not None:
        return kept
    results = [known.get(entry['asset_id']) for entry in files]
    for index, entry in enumerate(files):
        if results[index] is None:
            cached = _recall(('file', entry['asset_id'], entry['sha256']))
            if cached is not None and (cached.get('failed') or not cached['ocr_skipped']):
                results[index] = cached
    if all(result is not None for result in results):
        _remember(together, results, sum(_size(result) for result in results))
        return results
    with _turn():
        _read(files, results)
    results = [None if result is not None and result.get('failed') else result for result in results]
    _remember(together, results, sum(_size(result) for result in results))
    return results


def _read(files, results):
    """The files in `files` with no result yet read in place, within MAX_OCR_PAGES and READ_SECONDS (read_entries)."""
    from ..extraction import read_cv
    deadline = time.monotonic() + READ_SECONDS
    ocr_left = MAX_OCR_PAGES
    for index, entry in enumerate(files):
        if results[index] is not None:
            continue
        later = sum(1 for other, done in zip(files[index + 1:], results[index + 1:]) if done is None and other['scan'])
        allowed = max(min(1, ocr_left) if entry['scan'] else 0, ocr_left - later)
        key = ('file', entry['asset_id'], entry['sha256'])
        cached = _recall(key)
        if cached is not None and cached.get('allowed', 0) >= allowed:
            results[index] = cached
            continue
        seconds = deadline - time.monotonic()
        if seconds < 5:
            break
        begun = time.monotonic()
        try:
            result = read_cv(entry['path'], entry['kind'], ocr_pages=allowed, seconds=seconds)
        except DomainError:
            # A file the reader failed on is not tried again; one it ran out of time for may be.
            if time.monotonic() - begun < seconds:
                _remember(key, {'failed': True}, 256)
                results[index] = {'failed': True}
            continue
        result = {'pages': [page for page in result['pages'] if isinstance(page, dict) and type(page.get('page')) is int],
                  'names': [str(name)[:120] for name in result.get('names') or [] if isinstance(name, str)][:3],
                  'ocr_pages': int(result.get('ocr_pages') or 0), 'ocr_skipped': int(result.get('ocr_skipped') or 0),
                  'allowed': allowed}
        ocr_left = max(0, ocr_left - result['ocr_pages'])
        _remember(key, result, _size(result))
        results[index] = result


def excerpts_of(files, results):
    """The excerpts of files read (read_entries), and what of them was not read: (excerpts, unread).

    Every page with text, in the files' order: {'asset_id', 'page', 'text'}
    and, when it applies, 'ocr' and 'names'. 'ocr' marks a page read from an
    image. 'names' are, on a file's first page with text, its largest lines
    at the top: on a CV and a LinkedIn export, the person's name
    (content.require_name). `unread` names each file not read whole:
    {'asset_id', 'pages'} with how many of its pages were left out, and
    'whole' when none was read (one that cannot be read, or no time was left
    for it). Files that give fewer than MIN_WORDS words between them are
    `cv_file_unreadable`.
    """
    excerpts, unread = [], []
    for entry, result in zip(files, results):
        if result is None:
            unread.append({'asset_id': entry['asset_id'], 'pages': max(1, entry['pages']), 'whole': True})
            continue
        if result['ocr_skipped']:
            unread.append({'asset_id': entry['asset_id'], 'pages': result['ocr_skipped']})
        names = list(result['names'])
        for page in result['pages']:
            text = str(page.get('text') or '')[:12000]
            if not text.strip():
                continue
            excerpt = {'asset_id': entry['asset_id'], 'page': page['page'], 'text': text}
            if page.get('ocr') is True:
                excerpt['ocr'] = True
            if names:
                excerpt['names'], names = names, []
            excerpts.append(excerpt)
    if sum(len(re.findall(r'[^\W\d_]{2,}', excerpt['text'])) for excerpt in excerpts) < MIN_WORDS:
        raise DomainError('cv_file_unreadable')
    return excerpts, unread


def read(assets, kinds, known=None, *, account=None):
    """Every page of text in `assets`, in their order, and what could not be read: (excerpts, unread) as excerpts_of says."""
    files = entries(assets, kinds, account)
    return excerpts_of(files, read_entries(files, known))


def ahead(account, ids, source):
    """The files a CV from files will read, as read_entries takes them; [] when it will be refused before reading any.

    The bot reads them with read_entries off its shared thread, and the draft
    made next takes what was read (prepare).
    """
    if source not in KINDS or not isinstance(ids, list) or not ids:
        return []
    try:
        return entries(*checked(account, [str(identifier) for identifier in ids], source), account)
    except DomainError:
        return []


def for_model(excerpts):
    """A CV's excerpts as the model reads them: the page and its text, and whether OCR read it; the name hints stay here."""
    return [{key: value for key, value in excerpt.items() if key != 'names'} for excerpt in excerpts]
